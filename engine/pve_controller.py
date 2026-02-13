#!/usr/bin/env python3
"""
pve_controller.py - PvE mode AI opponent
"""

import torch
import numpy as np
import os
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List
from engine.combat_utils import calculate_hex_distance, calculate_pathfinding_distance, normalize_coordinates, get_unit_coordinates
from engine.phase_handlers.shared_utils import is_unit_alive
from shared.data_validation import require_key
from config_loader import get_config_loader
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

class PvEController:
    """Controls AI opponent in PvE mode."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.ai_model = None
        self.macro_model = None
        self.micro_models = {}
        self.micro_model_paths = {}
        self.macro_model_key = None
        self.unit_registry = unit_registry
        self.quiet = config.get("quiet", True)
    
    # ============================================================================
    # MODEL LOADING
    # ============================================================================
    
    def load_ai_model_for_pve(self, game_state: Dict[str, Any], engine):
        """Load trained AI model for PvE Player 2 - with diagnostic logging."""
        debug_mode = require_key(game_state, "debug_mode")
        if not isinstance(debug_mode, bool):
            raise ValueError(f"debug_mode must be boolean (got {type(debug_mode).__name__})")
        
        if debug_mode:
            print(f"DEBUG: _load_ai_model_for_pve called")
        
        try:
            from sb3_contrib import MaskablePPO
            from sb3_contrib.common.wrappers import ActionMasker
            if debug_mode:
                print(f"DEBUG: MaskablePPO import successful")
            
            macro_config = self._load_macro_controller_config()
            self.macro_model_key = require_key(macro_config, "macro_model_key")
            micro_only_mode = require_key(macro_config, "micro_only_mode")
            if not isinstance(micro_only_mode, bool):
                raise ValueError(f"micro_only_mode must be boolean (got {type(micro_only_mode).__name__})")
            config = get_config_loader()
            models_root = config.get_models_root()
            macro_model_path = os.path.join(
                models_root,
                self.macro_model_key,
                f"model_{self.macro_model_key}.zip"
            )
            if debug_mode:
                print(f"DEBUG: Macro model path: {macro_model_path}")
                print(f"DEBUG: Macro model exists: {os.path.exists(macro_model_path)}")
            macro_disabled = micro_only_mode and debug_mode
            if not macro_disabled:
                if not os.path.exists(macro_model_path):
                    raise FileNotFoundError(f"Macro model required for PvE mode not found: {macro_model_path}")
                self.macro_model = MaskablePPO.load(macro_model_path)
                self.ai_model = self.macro_model
                engine._ai_model = self.macro_model
            else:
                self.macro_model = None
                self.ai_model = None
                if not self.quiet:
                    print("PvE: Macro disabled for Debug mode (micro_only_mode=true)")
            
            # Wrap engine with ActionMasker for micro models (action space = 13)
            def mask_fn(env):
                return env.get_action_mask()
            masked_env = ActionMasker(engine, mask_fn)
            
            # Load micro models for all Player 2 unit types
            if not self.unit_registry:
                raise ValueError("unit_registry is required to load micro models for PvE")
            if "units_cache" not in game_state:
                raise KeyError("game_state missing required 'units_cache' field")
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            micro_model_keys = set()
            for unit_id, entry in game_state["units_cache"].items():
                if entry["player"] == 2:
                    unit = unit_by_id.get(str(unit_id))
                    if not unit:
                        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                    unit_type = require_key(unit, "unitType")
                    micro_model_keys.add(self.unit_registry.get_model_key(unit_type))
            
            self.micro_models = {}
            self.micro_model_paths = {}
            for model_key in micro_model_keys:
                model_path = os.path.join(
                    models_root,
                    model_key,
                    f"model_{model_key}.zip"
                )
                if debug_mode:
                    print(f"DEBUG: Micro model path: {model_path}")
                    print(f"DEBUG: Micro model exists: {os.path.exists(model_path)}")
                if not os.path.exists(model_path):
                    raise FileNotFoundError(f"Micro model required for PvE mode not found: {model_path}")
                self.micro_models[model_key] = MaskablePPO.load(model_path, env=masked_env)
                self.micro_model_paths[model_key] = model_path
            
            if not self.quiet:
                print(f"PvE: Loaded macro model: {self.macro_model_key}")
                print(f"PvE: Loaded micro models: {sorted(self.micro_models.keys())}")
                
        except Exception as e:
            print(f"DEBUG: _load_ai_model_for_pve exception: {e}")
            print(f"DEBUG: Exception type: {type(e).__name__}")
            # Set ai_model to None on any failure
            self.ai_model = None
            raise  # Re-raise to see the full error
    
    # ============================================================================
    # AI DECISION MAKING
    # ============================================================================
    
    def make_ai_decision(self, game_state: Dict[str, Any], engine) -> Dict[str, Any]:
        """
        AI decision logic - replaces human clicks with model predictions.
        Uses SAME handler paths as humans after decision is made.
        """
        if not self.micro_models:
            raise RuntimeError("Micro models not loaded for PvE")

        if self.macro_model is None:
            action_mask, eligible_units = engine.action_decoder.get_action_mask_and_eligible_units(game_state)
            if not eligible_units:
                raise RuntimeError("No eligible units for PvE decision (macro disabled)")
            active_shooting_unit = game_state.get("active_shooting_unit")
            if active_shooting_unit is not None:
                selected_unit_id = str(active_shooting_unit)
            else:
                selected_unit_id = str(require_key(eligible_units[0], "id"))
            macro_obs = engine.build_macro_observation()
            attrition_index = require_key(macro_obs, "attrition_objective_index")
            self._set_macro_intent_target(
                INTENT_ATTRITION, int(attrition_index), macro_obs, game_state
            )
            micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(selected_unit_id, game_state)
            micro_obs = engine.build_observation_for_unit(str(selected_unit_id))
            micro_obs = self._normalize_obs_for_inference(micro_obs, micro_model_path)
            micro_prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        else:
            macro_obs = engine.build_macro_observation()
            eligible_mask = np.array(require_key(macro_obs, "eligible_mask"), dtype=bool)
            if not np.any(eligible_mask):
                raise RuntimeError("Macro eligible_mask is empty - no eligible units to act")
            max_units, max_objectives, detail_max = self._infer_macro_dimensions(macro_obs)
            if max_objectives <= 0:
                raise ValueError("macro objectives list is empty")
            macro_obs = {
                **macro_obs,
                "objectives": require_key(macro_obs, "objectives")[:max_objectives]
            }
            macro_vector = self._build_macro_vector(macro_obs, max_units, max_objectives)
            macro_action_mask = self._build_macro_action_mask(macro_obs, max_units, max_objectives, detail_max, engine)
            macro_prediction = self.macro_model.predict(macro_vector, action_masks=macro_action_mask, deterministic=True)
            if isinstance(macro_prediction, tuple) and len(macro_prediction) >= 1:
                macro_action = macro_prediction[0]
            elif hasattr(macro_prediction, 'item'):
                macro_action = macro_prediction.item()
            else:
                macro_action = int(macro_prediction)
            macro_action_int = int(macro_action)
            selected_unit_id, intent_id, detail_index = self._decode_macro_action(
                macro_action_int, macro_obs, max_units, max_objectives, detail_max, eligible_mask, engine
            )
            self._set_macro_intent_target(intent_id, detail_index, macro_obs, game_state)
            micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(selected_unit_id, game_state)
            micro_obs = engine.build_observation_for_unit(str(selected_unit_id))
            micro_obs = self._normalize_obs_for_inference(micro_obs, micro_model_path)
            action_mask, eligible_units = engine.action_decoder.get_action_mask_for_unit(game_state, str(selected_unit_id))
            micro_prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        if isinstance(micro_prediction, tuple) and len(micro_prediction) >= 1:
            predicted_action = micro_prediction[0]
        elif hasattr(micro_prediction, 'item'):
            predicted_action = micro_prediction.item()
        else:
            predicted_action = int(micro_prediction)
        
        # Apply action mask like in training - force valid action if predicted action is invalid
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            current_phase = game_state.get("phase", "?")
            mask_indices = [i for i, v in enumerate(action_mask) if v]
            add_debug_file_log(
                game_state,
                f"[AI_DECISION DEBUG] E{episode} T{turn} P2 make_ai_decision: "
                f"phase={current_phase} predicted_action={predicted_action} "
                f"mask_true_indices={mask_indices}"
            )
        if not action_mask[predicted_action]:
            valid_actions = [i for i in range(len(action_mask)) if action_mask[i]]
            if valid_actions:
                action_int = valid_actions[0]
            else:
                raise RuntimeError(
                    "PvEController encountered an empty action mask for selected unit. "
                    "Engine must advance phase/turn instead of exposing empty masks."
                )
        else:
            action_int = predicted_action
        
        # Convert to semantic action using engine's method
        semantic_action = engine.action_decoder.convert_gym_action(
            action_int, game_state, action_mask=action_mask, eligible_units=eligible_units
        )
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_file_log(
                game_state,
                f"[AI_DECISION DEBUG] E{episode} T{turn} P2 make_ai_decision: "
                f"action_int={action_int} semantic_action={semantic_action}"
            )
        
        # Ensure AI player context
        current_player = game_state["current_player"]
        if current_player == 2:
            semantic_action["unitId"] = str(selected_unit_id)
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_file_log(
                    game_state,
                    f"[AI_DECISION DEBUG] E{episode} T{turn} P2 make_ai_decision: "
                    f"macro_unitId={selected_unit_id} action_int={action_int}"
                )
            print(f"🔍 [AI_DECISION] Final semantic_action: {semantic_action}")
        return semantic_action

    def _build_macro_vector(self, macro_obs: Dict[str, Any], max_units: int, max_objectives: int) -> np.ndarray:
        """
        Build macro observation vector compatible with MacroTrainingWrapper.
        Returns obs_vector.
        """
        global_info = require_key(macro_obs, "global")
        units = require_key(macro_obs, "units")
        objectives = require_key(macro_obs, "objectives")

        turn = float(require_key(global_info, "turn"))
        current_player = int(require_key(global_info, "current_player"))
        phase = require_key(global_info, "phase")
        objectives_controlled = require_key(global_info, "objectives_controlled")
        army_value_diff = float(require_key(global_info, "army_value_diff"))

        from config_loader import get_config_loader
        config_loader = get_config_loader()
        game_config = config_loader.get_game_config()
        game_rules = require_key(game_config, "game_rules")
        gameplay = require_key(game_config, "gameplay")

        max_turns = require_key(game_rules, "max_turns")
        phase_order = require_key(gameplay, "phase_order")
        if not phase_order:
            raise ValueError("gameplay.phase_order cannot be empty for macro observation")
        if max_turns <= 0:
            raise ValueError(f"Invalid max_turns for macro observation: {max_turns}")

        turn_norm = turn / float(max_turns)

        if phase not in phase_order:
            raise ValueError(f"Unknown phase for macro observation: {phase}")
        phase_onehot = [1.0 if phase == p else 0.0 for p in phase_order]

        if current_player == 1:
            player_onehot = [1.0, 0.0]
        elif current_player == 2:
            player_onehot = [0.0, 1.0]
        else:
            raise ValueError(f"Invalid current_player for macro observation: {current_player}")

        p1_obj = float(require_key(objectives_controlled, "p1"))
        p2_obj = float(require_key(objectives_controlled, "p2"))

        global_vec = [turn_norm] + phase_onehot + player_onehot + [p1_obj, p2_obj, army_value_diff]
        global_feature_size = len(global_vec)

        obs_size = self.macro_model.observation_space.shape[0]
        unit_feature_size = 12
        objective_feature_size = 3
        expected_size = global_feature_size + (unit_feature_size * max_units) + (objective_feature_size * max_objectives)
        if obs_size != expected_size:
            raise ValueError(
                f"Macro observation size mismatch: obs_size={obs_size}, "
                f"global_feature_size={global_feature_size}, unit_feature_size={unit_feature_size}, "
                f"objective_feature_size={objective_feature_size}, max_units={max_units}, "
                f"max_objectives={max_objectives}"
            )

        if len(units) > max_units:
            raise ValueError(
                f"Scenario units exceed macro max_units: units={len(units)} max_units={max_units}"
            )
        if len(objectives) > max_objectives:
            raise ValueError(
                f"Scenario objectives exceed macro max_objectives: objectives={len(objectives)} max_objectives={max_objectives}"
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
            if len(unit_vec) != unit_feature_size:
                raise ValueError(
                    f"unit feature size mismatch: expected={unit_feature_size} got={len(unit_vec)}"
                )
            unit_vecs.extend(unit_vec)

        missing_units = max_units - len(units)
        if missing_units > 0:
            unit_vecs.extend([0.0] * (missing_units * unit_feature_size))

        objective_vecs: List[float] = []
        for obj in objectives:
            obj_vec = [
                float(require_key(obj, "col_norm")),
                float(require_key(obj, "row_norm")),
                float(require_key(obj, "control_state")),
            ]
            if len(obj_vec) != objective_feature_size:
                raise ValueError(
                    f"objective feature size mismatch: expected={objective_feature_size} got={len(obj_vec)}"
                )
            objective_vecs.extend(obj_vec)

        missing_objectives = max_objectives - len(objectives)
        if missing_objectives > 0:
            objective_vecs.extend([0.0] * (missing_objectives * objective_feature_size))

        obs = np.array(global_vec + unit_vecs + objective_vecs, dtype=np.float32)
        if obs.shape[0] != obs_size:
            raise ValueError(
                f"Macro observation size mismatch: expected={obs_size} got={obs.shape[0]}"
            )

        return obs

    def _infer_macro_dimensions(self, macro_obs: Dict[str, Any]) -> Tuple[int, int, int]:
        """Infer (max_units, max_objectives, detail_max) from trained macro model shapes."""
        global_info = require_key(macro_obs, "global")
        turn = float(require_key(global_info, "turn"))
        current_player = int(require_key(global_info, "current_player"))
        phase = require_key(global_info, "phase")
        objectives_controlled = require_key(global_info, "objectives_controlled")
        army_value_diff = float(require_key(global_info, "army_value_diff"))

        from config_loader import get_config_loader
        config_loader = get_config_loader()
        game_config = config_loader.get_game_config()
        gameplay = require_key(game_config, "gameplay")
        phase_order = require_key(gameplay, "phase_order")
        if not phase_order:
            raise ValueError("gameplay.phase_order cannot be empty for macro dimension inference")

        turn_norm = turn / float(require_key(require_key(game_config, "game_rules"), "max_turns"))
        if phase not in phase_order:
            raise ValueError(f"Unknown phase for macro observation: {phase}")
        phase_onehot = [1.0 if phase == p else 0.0 for p in phase_order]

        if current_player == 1:
            player_onehot = [1.0, 0.0]
        elif current_player == 2:
            player_onehot = [0.0, 1.0]
        else:
            raise ValueError(f"Invalid current_player for macro observation: {current_player}")

        p1_obj = float(require_key(objectives_controlled, "p1"))
        p2_obj = float(require_key(objectives_controlled, "p2"))
        global_vec = [turn_norm] + phase_onehot + player_onehot + [p1_obj, p2_obj, army_value_diff]
        global_feature_size = len(global_vec)

        obs_size = int(self.macro_model.observation_space.shape[0])
        action_size = int(self.macro_model.action_space.n)
        unit_feature_size = 12
        objective_feature_size = 3

        for max_objectives in range(1, action_size + 1):
            remaining = obs_size - global_feature_size - (objective_feature_size * max_objectives)
            if remaining <= 0:
                continue
            if remaining % unit_feature_size != 0:
                continue
            max_units = remaining // unit_feature_size
            if max_units <= 0:
                continue
            if action_size % (max_units * INTENT_COUNT) != 0:
                continue
            detail_max = action_size // (max_units * INTENT_COUNT)
            if detail_max < max(max_units, max_objectives):
                continue
            expected_size = (
                global_feature_size
                + (unit_feature_size * max_units)
                + (objective_feature_size * max_objectives)
            )
            if expected_size == obs_size:
                return int(max_units), int(max_objectives), int(detail_max)

        raise ValueError(
            f"Unable to infer macro dimensions from model: obs_size={obs_size}, action_size={action_size}, "
            f"global_feature_size={global_feature_size}"
        )

    def _build_macro_action_mask(
        self,
        macro_obs: Dict[str, Any],
        max_units: int,
        max_objectives: int,
        detail_max: int,
        engine
    ) -> np.ndarray:
        """Build macro action mask compatible with MacroTrainingWrapper."""
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
        if len(units) > max_units:
            raise ValueError(
                f"Scenario units exceed macro max_units: units={len(units)} max_units={max_units}"
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
                return list(range(min(len(objectives), detail_max)))
            if detail_type == DETAIL_ENEMY:
                return list(range(min(len(enemy_ids), detail_max)))
            if detail_type == DETAIL_ALLY:
                return list(range(min(len(ally_ids), detail_max)))
            if detail_type == DETAIL_NONE:
                return [0]
            raise ValueError(f"Unsupported macro intent detail type: {detail_type}")

        active_shooting_unit = engine.game_state.get("active_shooting_unit")
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
            mask = np.zeros(max_units * INTENT_COUNT * detail_max, dtype=bool)
            for intent_id in range(INTENT_COUNT):
                detail_indices = _intent_detail_indices(intent_id)
                for detail_index in detail_indices:
                    action_index = (
                        (active_index * INTENT_COUNT * detail_max)
                        + (intent_id * detail_max)
                        + detail_index
                    )
                    mask[action_index] = True
            return mask

        mask = np.zeros(max_units * INTENT_COUNT * detail_max, dtype=bool)
        for i, flag in enumerate(eligible_mask):
            if i >= max_units:
                break
            if not flag:
                continue
            for intent_id in range(INTENT_COUNT):
                detail_indices = _intent_detail_indices(intent_id)
                for detail_index in detail_indices:
                    action_index = (
                        (i * INTENT_COUNT * detail_max)
                        + (intent_id * detail_max)
                        + detail_index
                    )
                    mask[action_index] = True
        return mask

    def _decode_macro_action(
        self,
        macro_action_int: int,
        macro_obs: Dict[str, Any],
        max_units: int,
        max_objectives: int,
        detail_max: int,
        eligible_mask: np.ndarray,
        engine
    ) -> Tuple[str, int, int]:
        units_list = require_key(macro_obs, "units")
        objectives = require_key(macro_obs, "objectives")
        ally_ids = require_key(macro_obs, "ally_ids")
        enemy_ids = require_key(macro_obs, "enemy_ids")
        attrition_objective_index = require_key(macro_obs, "attrition_objective_index")
        if not objectives:
            raise ValueError("macro objectives list is empty for action decode")
        if attrition_objective_index is None:
            raise ValueError("attrition_objective_index is required for action decode")

        max_actions = max_units * INTENT_COUNT * detail_max
        if macro_action_int < 0 or macro_action_int >= max_actions:
            raise ValueError(
                f"Macro action out of range: {macro_action_int} (max={max_actions})"
            )
        unit_index = macro_action_int // (INTENT_COUNT * detail_max)
        intent_and_detail = macro_action_int % (INTENT_COUNT * detail_max)
        intent_id = intent_and_detail // detail_max
        detail_index = intent_and_detail % detail_max
        if unit_index < 0 or unit_index >= len(units_list):
            raise ValueError(f"Macro unit index out of range: {unit_index} (units={len(units_list)})")
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

        active_shooting_unit = engine.game_state.get("active_shooting_unit")
        if active_shooting_unit is not None:
            active_id = str(active_shooting_unit)
            active_index = None
            for i, unit in enumerate(units_list):
                if str(require_key(unit, "id")) == active_id:
                    active_index = i
                    break
            if active_index is None:
                raise KeyError(f"Active shooting unit {active_id} missing from macro units list")
            if unit_index != active_index:
                raise ValueError(
                    f"Macro action must select active shooting unit {active_id} (index={active_index}), "
                    f"got {unit_index}"
                )

        selected_unit_id = require_key(units_list[unit_index], "id")
        return str(selected_unit_id), int(intent_id), int(detail_index)

    def _set_macro_intent_target(
        self,
        intent_id: int,
        detail_index: int,
        macro_obs: Dict[str, Any],
        game_state: Dict[str, Any]
    ) -> None:
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

        game_state["macro_intent_id"] = int(intent_id)
        game_state["macro_detail_type"] = int(detail_type)

        if detail_type == DETAIL_OBJECTIVE:
            if detail_index < 0 or detail_index >= len(objectives):
                raise ValueError(
                    f"macro objective detail index out of range: {detail_index} (objectives={len(objectives)})"
                )
            game_state["macro_detail_id"] = int(detail_index)
            game_state["macro_target_objective_index"] = int(detail_index)
            objective_id = require_key(objectives[detail_index], "id")
            game_state["macro_target_objective_id"] = str(objective_id)
            game_state["macro_target_unit_id"] = None
        elif detail_type == DETAIL_ENEMY:
            if detail_index < 0 or detail_index >= len(enemy_ids):
                raise ValueError(
                    f"macro enemy detail index out of range: {detail_index} (enemies={len(enemy_ids)})"
                )
            enemy_id = str(enemy_ids[detail_index])
            game_state["macro_detail_id"] = int(enemy_id)
            game_state["macro_target_unit_id"] = enemy_id
            game_state["macro_target_objective_index"] = None
            game_state["macro_target_objective_id"] = None
        elif detail_type == DETAIL_ALLY:
            if detail_index < 0 or detail_index >= len(ally_ids):
                raise ValueError(
                    f"macro ally detail index out of range: {detail_index} (allies={len(ally_ids)})"
                )
            ally_id = str(ally_ids[detail_index])
            game_state["macro_detail_id"] = int(ally_id)
            game_state["macro_target_unit_id"] = ally_id
            game_state["macro_target_objective_index"] = None
            game_state["macro_target_objective_id"] = None
        elif detail_type == DETAIL_NONE:
            game_state["macro_detail_id"] = 0
            game_state["macro_target_unit_id"] = None
            game_state["macro_target_objective_index"] = None
            game_state["macro_target_objective_id"] = None
        else:
            raise ValueError(f"Unsupported macro intent detail type: {detail_type}")

    def _select_nearest_objective_index(self, unit_id: str, game_state: Dict[str, Any]) -> int:
        objectives = require_key(game_state, "objectives")
        if not objectives:
            raise ValueError("objectives are required for macro target selection")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        unit = unit_by_id.get(str(unit_id))
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

    def _load_macro_controller_config(self) -> Dict[str, Any]:
        """Load macro controller config from config paths."""
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        core_config = config_loader.load_config("config", force_reload=False)
        paths = require_key(core_config, "paths")
        macro_config_path = require_key(paths, "macro_controller_config")
        full_path = Path(config_loader.root_path) / macro_config_path
        if not full_path.exists():
            raise FileNotFoundError(f"Macro controller config not found: {full_path}")
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_micro_model_for_unit_id(self, unit_id: str, game_state: Dict[str, Any]):
        """Get micro model for a specific unit id."""
        model, _ = self._get_micro_model_and_path_for_unit_id(unit_id, game_state)
        return model

    def _get_micro_model_and_path_for_unit_id(self, unit_id: str, game_state: Dict[str, Any]):
        """Get micro model and its path for a specific unit id (for VecNormalize inference)."""
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if not self.unit_registry:
            raise ValueError("unit_registry is required to resolve micro model key")
        unit_type = require_key(unit, "unitType")
        model_key = self.unit_registry.get_model_key(unit_type)
        if model_key not in self.micro_models:
            raise KeyError(f"Micro model not loaded for model_key={model_key}")
        model_path = self.micro_model_paths.get(model_key, "")
        return self.micro_models[model_key], model_path

    def _normalize_obs_for_inference(self, obs: np.ndarray, model_path: str) -> np.ndarray:
        """Normalize observation for inference if model was trained with VecNormalize."""
        if not model_path or not hasattr(self, "micro_model_paths"):
            return obs
        try:
            from ai.vec_normalize_utils import normalize_observation_for_inference
            return normalize_observation_for_inference(obs, model_path)
        except Exception:
            return obs
    
    def ai_select_unit(self, eligible_units: List[Dict[str, Any]], action_type: str) -> str:
        """AI selects which unit to activate - NO MODEL CALLS to prevent recursion."""
        if not eligible_units:
            raise ValueError("No eligible units available for selection")
        # Model prediction happens at api_server.py level, this just selects from eligible units
        # For AI_TURN.md compliance: select first eligible unit deterministically
        # The AI model determines the ACTION, not which unit to select
        return eligible_units[0]["id"]
    
    def _ai_select_unit_with_model(self, eligible_units: List[Dict[str, Any]], action_type: str) -> str:
        """Use trained DQN model to select best unit for AI player."""
        # Get current observation
        obs = self._build_observation()
        
        # Get AI action from trained model
        try:
            action, _ = self._ai_model.predict(obs, deterministic=True)
            semantic_action = self._convert_gym_action(action)
            
            # Extract unit selection from semantic action
            suggested_unit_id = semantic_action.get("unitId")
            
            # Validate AI's unit choice is in eligible list
            eligible_ids = [str(unit["id"]) for unit in eligible_units]
            if suggested_unit_id in eligible_ids:
                return suggested_unit_id
            else:
                # AI suggested invalid unit - use first eligible
                return eligible_units[0]["id"]
                
        except Exception as e:
            import logging
            logging.error(f"pve_controller._select_unit_from_pool failed: {str(e)} - returning first eligible unit")
            return eligible_units[0]["id"]
    
    # ============================================================================
    # ACTION SELECTION
    # ============================================================================
    
    def _ai_select_movement_destination(self, unit_id: str, game_state: Dict[str, Any]) -> Tuple[int, int]:
        """AI selects movement destination that actually moves the unit."""
        unit = self._get_unit_by_id(unit_id)
        if not unit:
            raise ValueError(f"Unit not found: {unit_id}")
        
        from engine.phase_handlers.shared_utils import require_unit_position
        current_pos = require_unit_position(unit, game_state)
        
        # Use movement handler to get valid destinations
        from engine.phase_handlers import movement_handlers
        valid_destinations = movement_handlers.movement_build_valid_destinations_pool(game_state, unit_id)
        
        # Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # AI_TURN.md COMPLIANCE: No actual moves available -> unit must WAIT, not attempt invalid move
        if not actual_moves:
            raise ValueError(f"No valid movement destinations for unit {unit_id} - should use WAIT action")
        
        # Strategy: Move toward nearest enemy for aggressive positioning
        # Uses BFS pathfinding to respect walls when calculating distance
        if "units_cache" not in game_state:
            raise KeyError("game_state missing required 'units_cache' field")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        enemies = []
        for enemy_id, entry in game_state["units_cache"].items():
            if entry["player"] != unit["player"]:
                enemy = unit_by_id.get(str(enemy_id))
                if not enemy:
                    raise KeyError(f"Unit {enemy_id} missing from game_state['units']")
                enemies.append(enemy)

        if enemies:
            # Find nearest enemy using BFS pathfinding distance (respects walls)
            from engine.phase_handlers.shared_utils import require_unit_position
            unit_col, unit_row = require_unit_position(unit, game_state)
            nearest_enemy = min(enemies, key=lambda e: calculate_pathfinding_distance(unit_col, unit_row, *require_unit_position(e, game_state), game_state))
            enemy_pos = require_unit_position(nearest_enemy, game_state)

            # Select move that gets closest to nearest enemy using BFS pathfinding distance
            best_move = min(actual_moves,
                           key=lambda dest: calculate_pathfinding_distance(dest[0], dest[1], enemy_pos[0], enemy_pos[1], game_state))
            
            # Only log once per movement action
            if not hasattr(self, '_logged_moves'):
                self._logged_moves = set()
            
            move_key = f"{unit_id}_{current_pos}_{best_move}"
            if move_key not in self._logged_moves:
                self._logged_moves.add(move_key)
            
            return best_move
        else:
            # No enemies - just take first available move
            selected = actual_moves[0]
            return selected
    
    def _ai_select_shooting_target(self, unit_id: str, game_state: Dict[str, Any]) -> str:
        """REMOVED: Engine bypassed handler decision tree. Use handler's complete AI_TURN.md flow."""
        raise NotImplementedError("AI shooting should use handler's decision tree, not engine shortcuts")
    
    def _ai_select_charge_target(self, unit_id: str, game_state: Dict[str, Any]) -> str:
        """AI selects charge target - placeholder implementation."""
        # TODO: Implement charge target selection
        raise NotImplementedError("Charge target selection not implemented")
    
    def _ai_select_combat_target(self, unit_id: str, game_state: Dict[str, Any]) -> str:
        """AI selects combat target - placeholder implementation."""
        # TODO: Implement combat target selection
        raise NotImplementedError("Combat target selection not implemented")