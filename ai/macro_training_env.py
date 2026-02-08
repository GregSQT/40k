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
from engine.combat_utils import get_unit_coordinates, calculate_hex_distance, normalize_coordinates
from engine.macro_intents import (
    INTENT_COUNT,
    INTENT_TAKE_OBJECTIVE,
    INTENT_HOLD_OBJECTIVE,
    INTENT_FOCUS_KILL,
    INTENT_SCREEN,
    INTENT_ATTRITION,
    DETAIL_OBJECTIVE,
    DETAIL_ENEMY,
    DETAIL_ALLY,
    DETAIL_NONE,
    get_intent_detail_type,
)


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
                "and follow ai/models/<model_key>/model_<model_key>.zip "
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
        self.objective_feature_fields = [
            "obj_col_norm",
            "obj_row_norm",
            "control_state",
        ]
        self.objective_feature_size = 3

        self.max_units = self._get_max_units_from_scenarios(self.scenario_files)
        if self.max_units <= 0:
            raise ValueError(f"Invalid max_units for macro training: {self.max_units}")
        self.max_objectives = self._get_max_objectives_from_scenarios(self.scenario_files) + 1
        if self.max_objectives <= 0:
            raise ValueError(f"Invalid max_objectives for macro training: {self.max_objectives}")
        self.detail_max = max(self.max_units, self.max_objectives)
        if self.detail_max <= 0:
            raise ValueError(f"Invalid detail_max for macro training: {self.detail_max}")

        obs_size = (
            self.global_feature_size
            + (self.unit_feature_size * self.max_units)
            + (self.objective_feature_size * self.max_objectives)
        )
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_size,), dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(self.max_units * INTENT_COUNT * self.detail_max)

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

        unit_id, intent_id, detail_index = self._decode_macro_action(macro_action, macro_obs)
        self._set_macro_intent_target(intent_id, detail_index, macro_obs)
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
        objectives = require_key(macro_obs, "objectives")
        ally_ids = require_key(macro_obs, "ally_ids")
        enemy_ids = require_key(macro_obs, "enemy_ids")
        attrition_objective_index = require_key(macro_obs, "attrition_objective_index")
        if not objectives:
            raise ValueError("macro objectives list is empty")
        if attrition_objective_index is None:
            raise ValueError("attrition_objective_index is required for macro mask")
        if len(eligible_mask) != len(units):
            raise ValueError(
                f"eligible_mask length mismatch: mask={len(eligible_mask)} units={len(units)}"
            )
        if len(units) > self.max_units:
            raise ValueError(
                f"Scenario units exceed macro max_units: units={len(units)} max_units={self.max_units}"
            )
        def _intent_detail_indices(intent_id: int) -> List[int]:
            detail_type = get_intent_detail_type(intent_id)
            if intent_id == INTENT_ATTRITION:
                if attrition_objective_index < 0 or attrition_objective_index >= len(objectives):
                    raise ValueError(
                        f"attrition_objective_index out of range: {attrition_objective_index} "
                        f"(objectives={len(objectives)})"
                    )
                return [attrition_objective_index]
            if detail_type == DETAIL_OBJECTIVE:
                return list(range(min(len(objectives), self.detail_max)))
            if detail_type == DETAIL_ENEMY:
                return list(range(min(len(enemy_ids), self.detail_max)))
            if detail_type == DETAIL_ALLY:
                return list(range(min(len(ally_ids), self.detail_max)))
            if detail_type == DETAIL_NONE:
                return [0]
            raise ValueError(f"Unsupported macro intent detail type: {detail_type}")

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
            mask = np.zeros(self.max_units * INTENT_COUNT * self.detail_max, dtype=bool)
            if active_index < self.max_units:
                for intent_id in range(INTENT_COUNT):
                    detail_indices = _intent_detail_indices(intent_id)
                    for detail_index in detail_indices:
                        action_index = (
                            (active_index * INTENT_COUNT * self.detail_max)
                            + (intent_id * self.detail_max)
                            + detail_index
                        )
                        mask[action_index] = True
            return mask

        mask = np.zeros(self.max_units * INTENT_COUNT * self.detail_max, dtype=bool)
        for i, flag in enumerate(eligible_mask):
            if i >= self.max_units:
                break
            if not flag:
                continue
            for intent_id in range(INTENT_COUNT):
                detail_indices = _intent_detail_indices(intent_id)
                for detail_index in detail_indices:
                    action_index = (
                        (i * INTENT_COUNT * self.detail_max)
                        + (intent_id * self.detail_max)
                        + detail_index
                    )
                    mask[action_index] = True
        return mask

    def _build_macro_vector(self, macro_obs: Dict[str, Any]) -> np.ndarray:
        global_info = require_key(macro_obs, "global")
        units = require_key(macro_obs, "units")
        objectives = require_key(macro_obs, "objectives")

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
        if len(objectives) > self.max_objectives:
            raise ValueError(
                f"Scenario objectives exceed macro max_objectives: objectives={len(objectives)} max_objectives={self.max_objectives}"
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

        objective_vecs: List[float] = []
        for obj in objectives:
            obj_vec = [
                float(require_key(obj, "col_norm")),
                float(require_key(obj, "row_norm")),
                float(require_key(obj, "control_state")),
            ]
            if len(obj_vec) != self.objective_feature_size:
                raise ValueError(
                    f"objective feature size mismatch: expected={self.objective_feature_size} got={len(obj_vec)}"
                )
            objective_vecs.extend(obj_vec)

        missing_objectives = self.max_objectives - len(objectives)
        if missing_objectives > 0:
            objective_vecs.extend([0.0] * (missing_objectives * self.objective_feature_size))

        obs = np.array(global_vec + unit_vecs + objective_vecs, dtype=np.float32)
        if obs.shape[0] != self.observation_space.shape[0]:
            raise ValueError(
                f"Macro observation size mismatch: expected={self.observation_space.shape[0]} got={obs.shape[0]}"
            )
        return obs

    def _decode_macro_action(self, macro_action: int, macro_obs: Dict[str, Any]) -> Tuple[str, int, int]:
        units = require_key(macro_obs, "units")
        eligible_mask = require_key(macro_obs, "eligible_mask")
        objectives = require_key(macro_obs, "objectives")
        ally_ids = require_key(macro_obs, "ally_ids")
        enemy_ids = require_key(macro_obs, "enemy_ids")
        attrition_objective_index = require_key(macro_obs, "attrition_objective_index")
        if not objectives:
            raise ValueError("macro objectives list is empty for action decode")
        if attrition_objective_index is None:
            raise ValueError("attrition_objective_index is required for action decode")

        max_actions = self.max_units * INTENT_COUNT * self.detail_max
        if macro_action < 0 or macro_action >= max_actions:
            raise ValueError(
                f"Macro action out of range: {macro_action} (max={max_actions})"
            )

        unit_index = macro_action // (INTENT_COUNT * self.detail_max)
        intent_and_detail = macro_action % (INTENT_COUNT * self.detail_max)
        intent_id = intent_and_detail // self.detail_max
        detail_index = intent_and_detail % self.detail_max

        if unit_index < 0 or unit_index >= len(units):
            raise ValueError(f"Macro unit index out of range: {unit_index} (units={len(units)})")
        if not eligible_mask[unit_index]:
            raise ValueError(f"Macro action selected ineligible unit index: {unit_index}")

        detail_type = get_intent_detail_type(intent_id)
        if intent_id == INTENT_ATTRITION:
            if attrition_objective_index < 0 or attrition_objective_index >= len(objectives):
                raise ValueError(
                    f"attrition_objective_index out of range: {attrition_objective_index} "
                    f"(objectives={len(objectives)})"
                )
            if detail_index != attrition_objective_index:
                raise ValueError(
                    f"Macro attrition intent must select attrition objective index {attrition_objective_index}, "
                    f"got {detail_index}"
                )
        elif detail_type == DETAIL_OBJECTIVE:
            if detail_index < 0 or detail_index >= len(objectives):
                raise ValueError(
                    f"Macro objective detail index out of range: {detail_index} (objectives={len(objectives)})"
                )
        elif detail_type == DETAIL_ENEMY:
            if detail_index < 0 or detail_index >= len(enemy_ids):
                raise ValueError(
                    f"Macro enemy detail index out of range: {detail_index} (enemies={len(enemy_ids)})"
                )
        elif detail_type == DETAIL_ALLY:
            if detail_index < 0 or detail_index >= len(ally_ids):
                raise ValueError(
                    f"Macro ally detail index out of range: {detail_index} (allies={len(ally_ids)})"
                )
        elif detail_type == DETAIL_NONE:
            if detail_index != 0:
                raise ValueError(
                    f"Macro none detail index must be 0, got {detail_index}"
                )
        else:
            raise ValueError(f"Unsupported macro intent detail type: {detail_type}")

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
            if unit_index != active_index:
                raise ValueError(
                    f"Macro action must select active shooting unit {active_id} "
                    f"(index={active_index}), got {unit_index}"
                )
            if not eligible_mask[active_index]:
                raise ValueError(
                    f"Active shooting unit {active_id} not eligible in macro mask"
                )

        unit_entry = units[unit_index]
        return str(require_key(unit_entry, "id")), int(intent_id), int(detail_index)

    def _set_macro_intent_target(self, intent_id: int, detail_index: int, macro_obs: Dict[str, Any]) -> None:
        objectives = require_key(macro_obs, "objectives")
        ally_ids = require_key(macro_obs, "ally_ids")
        enemy_ids = require_key(macro_obs, "enemy_ids")
        attrition_objective_index = require_key(macro_obs, "attrition_objective_index")
        if not objectives:
            raise ValueError("macro objectives list is empty for macro intent target")
        if attrition_objective_index is None:
            raise ValueError("attrition_objective_index is required for macro intent target")

        detail_type = get_intent_detail_type(intent_id)
        if intent_id == INTENT_ATTRITION:
            detail_type = DETAIL_OBJECTIVE
            detail_index = int(attrition_objective_index)

        self.engine.game_state["macro_intent_id"] = int(intent_id)
        self.engine.game_state["macro_detail_type"] = int(detail_type)

        if detail_type == DETAIL_OBJECTIVE:
            if detail_index < 0 or detail_index >= len(objectives):
                raise ValueError(
                    f"macro objective detail index out of range: {detail_index} (objectives={len(objectives)})"
                )
            self.engine.game_state["macro_detail_id"] = int(detail_index)
            self.engine.game_state["macro_target_objective_index"] = int(detail_index)
            objective_id = require_key(objectives[detail_index], "id")
            self.engine.game_state["macro_target_objective_id"] = str(objective_id)
            self.engine.game_state["macro_target_unit_id"] = None
        elif detail_type == DETAIL_ENEMY:
            if detail_index < 0 or detail_index >= len(enemy_ids):
                raise ValueError(
                    f"macro enemy detail index out of range: {detail_index} (enemies={len(enemy_ids)})"
                )
            enemy_id = str(enemy_ids[detail_index])
            self.engine.game_state["macro_detail_id"] = int(enemy_id)
            self.engine.game_state["macro_target_unit_id"] = enemy_id
            self.engine.game_state["macro_target_objective_index"] = None
            self.engine.game_state["macro_target_objective_id"] = None
        elif detail_type == DETAIL_ALLY:
            if detail_index < 0 or detail_index >= len(ally_ids):
                raise ValueError(
                    f"macro ally detail index out of range: {detail_index} (allies={len(ally_ids)})"
                )
            ally_id = str(ally_ids[detail_index])
            self.engine.game_state["macro_detail_id"] = int(ally_id)
            self.engine.game_state["macro_target_unit_id"] = ally_id
            self.engine.game_state["macro_target_objective_index"] = None
            self.engine.game_state["macro_target_objective_id"] = None
        elif detail_type == DETAIL_NONE:
            self.engine.game_state["macro_detail_id"] = 0
            self.engine.game_state["macro_target_unit_id"] = None
            self.engine.game_state["macro_target_objective_index"] = None
            self.engine.game_state["macro_target_objective_id"] = None
        else:
            raise ValueError(f"Unsupported macro intent detail type: {detail_type}")

    def _get_micro_action_for_unit(self, unit_id: str) -> int:
        self._ensure_macro_target_for_unit(unit_id)
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

    def _ensure_macro_target_for_unit(self, unit_id: str) -> None:
        game_state = self.engine.game_state
        current_player = require_key(game_state, "current_player")
        if current_player == self.macro_player:
            if "macro_intent_id" not in game_state:
                raise KeyError("macro_intent_id missing for macro player action")
            if game_state["macro_intent_id"] is None:
                raise ValueError("macro_intent_id is None for macro player action")
            if "macro_detail_type" not in game_state:
                raise KeyError("macro_detail_type missing for macro player action")
            if game_state["macro_detail_type"] is None:
                raise ValueError("macro_detail_type is None for macro player action")
            if "macro_detail_id" not in game_state:
                raise KeyError("macro_detail_id missing for macro player action")
            if game_state["macro_detail_id"] is None:
                raise ValueError("macro_detail_id is None for macro player action")
            return
        attrition_index = require_key(game_state, "macro_attrition_objective_index")
        objectives = require_key(game_state, "objectives")
        if attrition_index < 0 or attrition_index >= len(objectives):
            raise ValueError(
                f"macro_attrition_objective_index out of range: {attrition_index} (objectives={len(objectives)})"
            )
        game_state["macro_intent_id"] = INTENT_ATTRITION
        game_state["macro_detail_type"] = DETAIL_OBJECTIVE
        game_state["macro_detail_id"] = int(attrition_index)
        game_state["macro_target_objective_index"] = int(attrition_index)
        objective_id = require_key(objectives[attrition_index], "id")
        game_state["macro_target_objective_id"] = str(objective_id)

    def _select_nearest_objective_index(self, unit_id: str) -> int:
        game_state = self.engine.game_state
        objectives = require_key(game_state, "objectives")
        if not objectives:
            raise ValueError("objectives are required for macro target selection")
        unit = None
        for entry in game_state["units"]:
            if str(require_key(entry, "id")) == str(unit_id):
                unit = entry
                break
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_col, unit_row = get_unit_coordinates(unit)
        best_index = None
        best_distance = None
        for idx, objective in enumerate(objectives):
            obj_hexes = require_key(objective, "hexes")
            if not obj_hexes:
                raise ValueError(f"Objective {objective.get('id')} has no hexes")
            sum_col = 0
            sum_row = 0
            for col, row in obj_hexes:
                norm_col, norm_row = normalize_coordinates(col, row)
                sum_col += norm_col
                sum_row += norm_row
            centroid_col = sum_col / float(len(obj_hexes))
            centroid_row = sum_row / float(len(obj_hexes))
            distance = calculate_hex_distance(
                unit_col,
                unit_row,
                int(round(centroid_col)),
                int(round(centroid_row))
            )
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = idx
        if best_index is None:
            raise ValueError("No objectives available for macro target selection")
        return int(best_index)

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
        self._ensure_macro_target_for_unit(unit_id)
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

    def _get_max_objectives_from_scenarios(self, scenario_files: List[str]) -> int:
        max_objectives = 0
        for scenario_file in scenario_files:
            with open(scenario_file, "r", encoding="utf-8") as f:
                scenario_data = json.load(f)
            if "objectives" not in scenario_data:
                raise KeyError("scenario objectives are required for macro objective selection")
            objectives = scenario_data["objectives"]
            if not isinstance(objectives, list):
                raise TypeError("scenario objectives must be a list")
            objective_count = len(objectives)
            if objective_count > max_objectives:
                max_objectives = objective_count
        return max_objectives

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
