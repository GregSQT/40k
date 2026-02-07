#!/usr/bin/env python3
"""
ai/macro_training_env.py - Macro training wrapper for hierarchical control.

Macro agent selects a unit; frozen micro agents execute the action.
"""

from typing import Dict, Any, List, Tuple, Optional
import json
import os

import gymnasium as gym
import numpy as np

from config_loader import get_config_loader
from shared.data_validation import require_key


class MacroTrainingWrapper(gym.Wrapper):
    """
    Wrapper that trains a macro agent to select which unit acts.

    - Macro action space: unit index (fixed size).
    - Micro actions: executed by frozen micro models per unit type.
    - Opponent (player 2) also uses frozen micro models.
    """

    def __init__(
        self,
        base_env: gym.Env,
        unit_registry,
        scenario_files: List[str],
        model_path_template: str,
        macro_player: int,
        debug_mode: bool = False,
    ) -> None:
        super().__init__(base_env)
        self.engine = self.env
        self.unit_registry = unit_registry
        self.debug_mode = debug_mode
        self.macro_player = int(macro_player)
        if self.macro_player not in (1, 2):
            raise ValueError(f"macro_player must be 1 or 2 (got {self.macro_player})")

        if not scenario_files:
            raise ValueError("scenario_files is required for MacroTrainingWrapper")
        self.scenario_files = scenario_files

        if "{model_key}" not in model_path_template:
            raise ValueError(
                "model_path_template must include '{model_key}' placeholder "
                f"(got {model_path_template})"
            )
        self.model_path_template = model_path_template

        config_loader = get_config_loader()
        game_config = config_loader.get_game_config()
        game_rules = require_key(game_config, "game_rules")
        gameplay = require_key(game_config, "gameplay")
        self.max_turns = require_key(game_rules, "max_turns")
        self.phase_order = require_key(gameplay, "phase_order")
        if not self.phase_order:
            raise ValueError("gameplay.phase_order cannot be empty for macro training")

        self.unit_feature_fields = [
            "best_ranged_target_onehot",
            "best_melee_target_onehot",
            "attack_mode_ratio",
            "hp_ratio",
            "value_norm",
            "pos_col_norm",
            "pos_row_norm",
            "dist_obj_norm",
        ]
        self.unit_feature_size = 12  # 3 + 3 + 6 scalars
        self.global_feature_size = 1 + len(self.phase_order) + 2 + 2 + 1

        self.max_units = self._get_max_units_from_scenarios(self.scenario_files)
        if self.max_units <= 0:
            raise ValueError(f"Invalid max_units for macro training: {self.max_units}")

        obs_size = self.global_feature_size + (self.unit_feature_size * self.max_units)
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(self.max_units)

        self.micro_models = self._load_micro_models_for_scenarios(self.scenario_files)

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        obs, info = self.env.reset(seed=seed, options=options)
        macro_obs, terminated, truncated, reward = self._advance_opponent_until_macro_turn()
        if terminated or truncated:
            return macro_obs, info
        return self._build_macro_vector(macro_obs), info

    def step(self, macro_action: int):
        macro_obs, terminated, truncated, reward = self._advance_opponent_until_macro_turn()
        if terminated or truncated:
            return self._build_macro_vector(macro_obs), reward, terminated, truncated, {}

        if self.engine.game_state.get("current_player") != self.macro_player:
            raise ValueError(
                f"Macro step called but current_player={self.engine.game_state.get('current_player')} "
                f"(expected {self.macro_player})"
            )

        unit_id = self._resolve_macro_action_to_unit_id(macro_action, macro_obs)
        self._prioritize_unit_in_pool(unit_id)

        micro_action = self._get_micro_action_for_unit(unit_id)
        _, reward, terminated, truncated, info = self.env.step(micro_action)

        macro_obs, term2, trunc2, reward2 = self._advance_opponent_until_macro_turn()
        reward += reward2
        terminated = terminated or term2
        truncated = truncated or trunc2

        return self._build_macro_vector(macro_obs), reward, terminated, truncated, info

    def get_action_mask(self) -> np.ndarray:
        if self.engine.game_state.get("current_player") != self.macro_player:
            raise ValueError(
                f"get_action_mask called outside macro turn: current_player={self.engine.game_state.get('current_player')}"
            )
        macro_obs = self.engine.build_macro_observation()
        eligible_mask = require_key(macro_obs, "eligible_mask")
        units = require_key(macro_obs, "units")
        if len(eligible_mask) != len(units):
            raise ValueError(
                f"eligible_mask length mismatch: mask={len(eligible_mask)} units={len(units)}"
            )
        if len(units) > self.max_units:
            raise ValueError(
                f"Scenario units exceed macro max_units: units={len(units)} max_units={self.max_units}"
            )

        active_shooting_unit = self.engine.game_state.get("active_shooting_unit")
        if active_shooting_unit is not None:
            active_id = str(active_shooting_unit)
            active_index = None
            for i, unit in enumerate(units):
                if str(require_key(unit, "id")) == active_id:
                    active_index = i
                    break
            if active_index is None:
                raise KeyError(f"Active shooting unit {active_id} missing from macro units list")
            if not eligible_mask[active_index]:
                raise ValueError(
                    f"Active shooting unit {active_id} not eligible in macro mask"
                )
            mask = np.zeros(self.max_units, dtype=bool)
            if active_index < self.max_units:
                mask[active_index] = True
            return mask

        mask = np.zeros(self.max_units, dtype=bool)
        for i, flag in enumerate(eligible_mask):
            if i >= self.max_units:
                break
            mask[i] = bool(flag)
        return mask

    def _build_macro_vector(self, macro_obs: Dict[str, Any]) -> np.ndarray:
        global_info = require_key(macro_obs, "global")
        units = require_key(macro_obs, "units")

        turn = float(require_key(global_info, "turn"))
        current_player = int(require_key(global_info, "current_player"))
        phase = require_key(global_info, "phase")
        objectives_controlled = require_key(global_info, "objectives_controlled")
        army_value_diff = float(require_key(global_info, "army_value_diff"))

        if self.max_turns <= 0:
            raise ValueError(f"Invalid max_turns for macro normalization: {self.max_turns}")
        turn_norm = turn / float(self.max_turns)

        if phase not in self.phase_order:
            raise ValueError(f"Unknown phase for macro observation: {phase}")
        phase_onehot = [1.0 if phase == p else 0.0 for p in self.phase_order]

        if current_player == 1:
            player_onehot = [1.0, 0.0]
        elif current_player == 2:
            player_onehot = [0.0, 1.0]
        else:
            raise ValueError(f"Invalid current_player for macro observation: {current_player}")

        p1_obj = float(require_key(objectives_controlled, "p1"))
        p2_obj = float(require_key(objectives_controlled, "p2"))

        global_vec = [turn_norm] + phase_onehot + player_onehot + [p1_obj, p2_obj, army_value_diff]
        if len(global_vec) != self.global_feature_size:
            raise ValueError(
                f"global feature size mismatch: expected={self.global_feature_size} got={len(global_vec)}"
            )

        if len(units) > self.max_units:
            raise ValueError(
                f"Scenario units exceed macro max_units: units={len(units)} max_units={self.max_units}"
            )

        unit_vecs: List[float] = []
        for unit in units:
            best_ranged = require_key(unit, "best_ranged_target_onehot")
            best_melee = require_key(unit, "best_melee_target_onehot")
            if len(best_ranged) != 3 or len(best_melee) != 3:
                raise ValueError("best_*_target_onehot must be length 3 for macro observation")

            unit_vec = [
                float(best_ranged[0]),
                float(best_ranged[1]),
                float(best_ranged[2]),
                float(best_melee[0]),
                float(best_melee[1]),
                float(best_melee[2]),
                float(require_key(unit, "attack_mode_ratio")),
                float(require_key(unit, "hp_ratio")),
                float(require_key(unit, "value_norm")),
                float(require_key(unit, "pos_col_norm")),
                float(require_key(unit, "pos_row_norm")),
                float(require_key(unit, "dist_obj_norm")),
            ]
            if len(unit_vec) != self.unit_feature_size:
                raise ValueError(
                    f"unit feature size mismatch: expected={self.unit_feature_size} got={len(unit_vec)}"
                )
            unit_vecs.extend(unit_vec)

        # Zero-pad to fixed size
        missing_units = self.max_units - len(units)
        if missing_units > 0:
            unit_vecs.extend([0.0] * (missing_units * self.unit_feature_size))

        obs = np.array(global_vec + unit_vecs, dtype=np.float32)
        if obs.shape[0] != self.observation_space.shape[0]:
            raise ValueError(
                f"Macro observation size mismatch: expected={self.observation_space.shape[0]} got={obs.shape[0]}"
            )
        return obs

    def _resolve_macro_action_to_unit_id(self, macro_action: int, macro_obs: Dict[str, Any]) -> str:
        units = require_key(macro_obs, "units")
        eligible_mask = require_key(macro_obs, "eligible_mask")
        active_shooting_unit = self.engine.game_state.get("active_shooting_unit")
        if active_shooting_unit is not None:
            active_id = str(active_shooting_unit)
            active_index = None
            for i, unit in enumerate(units):
                if str(require_key(unit, "id")) == active_id:
                    active_index = i
                    break
            if active_index is None:
                raise KeyError(f"Active shooting unit {active_id} missing from macro units list")
            if macro_action != active_index:
                raise ValueError(
                    f"Macro action must select active shooting unit {active_id} (index={active_index}), "
                    f"got {macro_action}"
                )
            if not eligible_mask[active_index]:
                raise ValueError(
                    f"Active shooting unit {active_id} not eligible in macro mask"
                )
            return active_id
        if macro_action < 0 or macro_action >= len(units):
            raise ValueError(f"Macro action out of range: {macro_action} (units={len(units)})")
        if not eligible_mask[macro_action]:
            raise ValueError(f"Macro action selected ineligible unit index: {macro_action}")
        unit_entry = units[macro_action]
        return str(require_key(unit_entry, "id"))

    def _get_micro_action_for_unit(self, unit_id: str) -> int:
        micro_obs = self.engine.build_observation_for_unit(str(unit_id))
        action_mask, _ = self.engine.action_decoder.get_action_mask_for_unit(
            self.engine.game_state, str(unit_id)
        )
        micro_model = self._get_micro_model_for_unit_id(str(unit_id))
        prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        if isinstance(prediction, tuple) and len(prediction) >= 1:
            action = prediction[0]
        elif hasattr(prediction, "item"):
            action = prediction.item()
        else:
            action = int(prediction)
        return int(action)

    def _get_micro_action_for_active_unit(self) -> int:
        game_state = self.engine.game_state
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(game_state)
        if not eligible_units:
            return 11  # WAIT to advance phase when pool is empty
        valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
        if not valid_actions:
            raise RuntimeError("MacroTrainingWrapper encountered an empty action mask")

        active_unit = eligible_units[0]
        unit_id = str(require_key(active_unit, "id"))
        micro_obs = self.engine.build_observation_for_unit(unit_id)
        micro_model = self._get_micro_model_for_unit_id(unit_id)
        prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        if isinstance(prediction, tuple) and len(prediction) >= 1:
            action = prediction[0]
        elif hasattr(prediction, "item"):
            action = prediction.item()
        else:
            action = int(prediction)
        return int(action)

    def _advance_opponent_until_macro_turn(self) -> Tuple[Dict[str, Any], bool, bool, float]:
        reward_total = 0.0
        terminated = False
        truncated = False
        info = {}
        max_iterations = 1000
        loop_count = 0

        while not (terminated or truncated) and self.engine.game_state.get("current_player") != self.macro_player:
            loop_count += 1
            if loop_count > max_iterations:
                phase = self.engine.game_state.get("phase", "?")
                raise RuntimeError(
                    f"MacroTrainingWrapper infinite loop detected: iterations={loop_count} phase={phase}"
                )
            opponent_action = self._get_micro_action_for_active_unit()
            _, reward, terminated, truncated, info = self.env.step(opponent_action)
            reward_total += reward

        macro_obs = self.engine.build_macro_observation()
        return macro_obs, terminated, truncated, reward_total

    def _prioritize_unit_in_pool(self, unit_id: str) -> None:
        game_state = self.engine.game_state
        phase = require_key(game_state, "phase")
        if phase == "move":
            pool_key = "move_activation_pool"
        elif phase == "shoot":
            pool_key = "shoot_activation_pool"
        elif phase == "charge":
            pool_key = "charge_activation_pool"
        elif phase == "fight":
            fight_subphase = require_key(game_state, "fight_subphase")
            if fight_subphase == "charging":
                pool_key = "charging_activation_pool"
            elif fight_subphase in ("alternating_active", "cleanup_active"):
                pool_key = "active_alternating_activation_pool"
            elif fight_subphase in ("alternating_non_active", "cleanup_non_active"):
                pool_key = "non_active_alternating_activation_pool"
            else:
                raise KeyError(f"Unknown fight_subphase for macro selection: {fight_subphase}")
        else:
            raise KeyError(f"Unsupported phase for macro selection: {phase}")

        pool = require_key(game_state, pool_key)
        unit_id_str = str(unit_id)
        selected = None
        new_pool = []
        for uid in pool:
            if str(uid) == unit_id_str and selected is None:
                selected = uid
            else:
                new_pool.append(uid)
        if selected is None:
            raise ValueError(f"Selected unit {unit_id} not found in {pool_key}")
        game_state[pool_key] = [selected] + new_pool

    def _get_micro_model_for_unit_id(self, unit_id: str):
        unit_by_id = {str(u["id"]): u for u in self.engine.game_state["units"]}
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_type = require_key(unit, "unitType")
        model_key = self.unit_registry.get_model_key(unit_type)
        if model_key not in self.micro_models:
            raise KeyError(f"Micro model not loaded for model_key={model_key}")
        return self.micro_models[model_key]

    def _get_max_units_from_scenarios(self, scenario_files: List[str]) -> int:
        max_units = 0
        for scenario_file in scenario_files:
            with open(scenario_file, "r", encoding="utf-8") as f:
                scenario_data = json.load(f)
            units = require_key(scenario_data, "units")
            if len(units) > max_units:
                max_units = len(units)
        return max_units

    def _load_micro_models_for_scenarios(self, scenario_files: List[str]) -> Dict[str, Any]:
        from sb3_contrib import MaskablePPO

        unit_types = set()
        for scenario_file in scenario_files:
            with open(scenario_file, "r", encoding="utf-8") as f:
                scenario_data = json.load(f)
            units = require_key(scenario_data, "units")
            for unit in units:
                unit_type = require_key(unit, "unit_type")
                unit_types.add(unit_type)

        model_keys = {self.unit_registry.get_model_key(u) for u in unit_types}
        micro_models = {}
        for model_key in model_keys:
            model_path = self.model_path_template.format(model_key=model_key)
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Micro model required for macro training not found: {model_path}")
            micro_models[model_key] = MaskablePPO.load(model_path)
        return micro_models


class MacroVsBotWrapper(MacroTrainingWrapper):
    """
    Macro vs bot evaluation wrapper.

    Macro selects unit for player 1; bot controls player 2.
    """

    def __init__(
        self,
        base_env: gym.Env,
        unit_registry,
        scenario_files: List[str],
        model_path_template: str,
        macro_player: int,
        bot,
        debug_mode: bool = False,
    ) -> None:
        super().__init__(
            base_env=base_env,
            unit_registry=unit_registry,
            scenario_files=scenario_files,
            model_path_template=model_path_template,
            macro_player=macro_player,
            debug_mode=debug_mode,
        )
        self.bot = bot

    def _get_bot_action_for_active_unit(self) -> int:
        game_state = self.engine.game_state
        action_mask, eligible_units = self.engine.action_decoder.get_action_mask_and_eligible_units(game_state)
        if not eligible_units:
            return 11  # WAIT to advance phase when pool is empty
        valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
        if not valid_actions:
            raise RuntimeError("MacroVsBotWrapper encountered an empty action mask")
        if hasattr(self.bot, 'select_action_with_state'):
            bot_choice = self.bot.select_action_with_state(valid_actions, game_state)
        else:
            bot_choice = self.bot.select_action(valid_actions)
        if bot_choice not in valid_actions:
            return valid_actions[0]
        return int(bot_choice)

    def _advance_opponent_until_macro_turn(self) -> Tuple[Dict[str, Any], bool, bool, float]:
        reward_total = 0.0
        terminated = False
        truncated = False
        max_iterations = 1000
        loop_count = 0

        while not (terminated or truncated) and self.engine.game_state.get("current_player") != self.macro_player:
            loop_count += 1
            if loop_count > max_iterations:
                phase = self.engine.game_state.get("phase", "?")
                raise RuntimeError(
                    f"MacroVsBotWrapper infinite loop detected: iterations={loop_count} phase={phase}"
                )
            bot_action = self._get_bot_action_for_active_unit()
            _, reward, terminated, truncated, _info = self.env.step(bot_action)
            reward_total += reward

        macro_obs = self.engine.build_macro_observation()
        return macro_obs, terminated, truncated, reward_total
