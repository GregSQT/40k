#!/usr/bin/env python3
"""
pve_controller.py - PvE mode AI opponent
"""

import numpy as np
import os
from typing import Dict, Any, Tuple, List, cast
from engine.combat_utils import calculate_hex_distance, calculate_pathfinding_distance, normalize_coordinates, get_unit_coordinates
from engine.phase_handlers.shared_utils import is_unit_alive
from shared.data_validation import require_key
from engine.action_decoder import ActionValidationError
from config_loader import get_config_loader
from engine.macro_intents import BASE_ZONE_INTENT

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
        # Members used by model-driven selection paths, populated at runtime by the
        # owning engine/training harness when PvE runs against a trained model.
        self._ai_model: Any = None
        self._build_observation: Any = None
        self._convert_gym_action: Any = None
        self._get_unit_by_id: Any = None
    
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
            
            config = get_config_loader()
            models_root = config.get_models_root()
            # PvE runtime is explicitly micro-only (CoreAgent); MacroController is disabled.
            self.macro_model_key = None
            self.macro_model = None
            self.ai_model = None
            engine._ai_model = None
            if not self.quiet:
                print("PvE: Macro controller disabled (micro-only CoreAgent mode)")
            
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
            shared_micro_model_key = require_key(self.config, "controlled_agent")
            if not isinstance(shared_micro_model_key, str) or not shared_micro_model_key.strip():
                raise ValueError(
                    f"controlled_agent must be a non-empty string in PvE config "
                    f"(got {shared_micro_model_key!r})"
                )
            shared_micro_model_storage_key = config._resolve_agent_config_key(
                shared_micro_model_key.strip()
            )
            for model_key in micro_model_keys:
                model_path = os.path.join(
                    models_root,
                    shared_micro_model_storage_key,
                    f"model_{shared_micro_model_storage_key}.zip"
                )
                if debug_mode:
                    print(
                        f"DEBUG: Micro model key '{model_key}' mapped to shared "
                        f"storage key '{shared_micro_model_storage_key}'"
                    )
                    print(f"DEBUG: Micro model path: {model_path}")
                    print(f"DEBUG: Micro model exists: {os.path.exists(model_path)}")
                if not os.path.exists(model_path):
                    raise FileNotFoundError(f"Micro model required for PvE mode not found: {model_path}")
                self.micro_models[model_key] = MaskablePPO.load(model_path, env=masked_env)
                self.micro_model_paths[model_key] = model_path

            # Marker to indicate PvE micro models are loaded (used by W40KEngine reset guard).
            self.ai_model = self.micro_models
            
            if not self.quiet:
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

    def is_ready_for_decision(self) -> bool:
        """Return whether PvE controller has the required models for inference."""
        return bool(self.micro_models)
    
    def make_ai_decision(self, game_state: Dict[str, Any], engine) -> Dict[str, Any]:
        """
        AI decision logic - replaces human clicks with model predictions.
        Uses SAME handler paths as humans after decision is made.
        """
        if not self.micro_models:
            raise RuntimeError("Micro models not loaded for PvE")

        current_phase = require_key(game_state, "phase")

        action_mask, eligible_units = engine.action_decoder.get_action_mask_and_eligible_units(game_state)
        if not eligible_units:
            raise RuntimeError("No eligible units for PvE decision")
        active_shooting_unit = game_state.get("active_shooting_unit")
        if active_shooting_unit is not None:
            selected_unit_id = str(active_shooting_unit)
        else:
            selected_unit_id = str(require_key(eligible_units[0], "id"))
        micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(
            selected_unit_id, game_state, engine
        )
        micro_obs = engine.build_observation_for_unit(str(selected_unit_id))
        micro_obs = self._normalize_obs_for_inference(micro_obs, micro_model_path)
        micro_prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        if isinstance(micro_prediction, tuple) and len(micro_prediction) >= 1:
            predicted_action = micro_prediction[0]
        elif hasattr(micro_prediction, 'item'):
            predicted_action = cast(Any, micro_prediction).item()
        else:
            predicted_action = micro_prediction

        # Tutoriel étape 2 : pour chaque unité P2, même script qu'avant (charge en charge,
        # mouvement agressif en move) tant que cette unité n'a pas encore été comptée dans le
        # tracking. (Anciennement : un seul advance/charge global pour tout P2 → la 2e
        # Hormagaunt ne recevait plus le forçage.)
        scenario_file = getattr(engine, "_current_scenario_file", "") or ""
        if (
            "tutorial" in scenario_file
            and require_key(game_state, "current_player") == 2
        ):
            current_phase = require_key(game_state, "phase")
            selected_str = str(selected_unit_id)
            if current_phase == "move":
                units_moved = require_key(game_state, "units_moved")
                if selected_str not in units_moved and len(action_mask) > 0 and bool(
                    action_mask[0]
                ):
                    predicted_action = 0
            elif current_phase == "charge":
                units_charged = require_key(game_state, "units_charged")
                if selected_str not in units_charged and len(action_mask) > 9 and bool(
                    action_mask[9]
                ):
                    predicted_action = 9

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
        try:
            action_int = engine.action_decoder.normalize_action_input(
                raw_action=predicted_action,
                phase=require_key(game_state, "phase"),
                source="pve_controller",
                action_space_size=len(action_mask),
            )
            engine.action_decoder.validate_action_against_mask(
                action_int=action_int,
                action_mask=action_mask,
                phase=require_key(game_state, "phase"),
                source="pve_controller",
                unit_id=selected_unit_id,
            )
        except ActionValidationError as e:
            raise RuntimeError(f"PvE action validation failed: {e}") from e

        # Guard: bot must never generate zone intent actions (actions >= BASE_ZONE_INTENT)
        if action_int >= BASE_ZONE_INTENT:
            raise ValueError(
                f"pve_controller generated zone intent action {action_int} — "
                "bot must only produce actions in [0, BASE_ZONE_INTENT). "
                "This is an invariant violation."
            )

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

    def _evaluate_rule_choice_option_value(
        self, unit_id: str, game_state: Dict[str, Any], engine
    ) -> float:
        """
        Evaluate one rule-choice option using the policy value head.

        The selected option is expected to already be applied in game_state before this call.
        """
        micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(
            unit_id, game_state, engine
        )
        unit_observation = engine.build_observation_for_unit(str(unit_id))
        unit_observation = self._normalize_obs_for_inference(unit_observation, micro_model_path)
        obs_tensor, _ = micro_model.policy.obs_to_tensor(unit_observation)
        import torch
        with torch.no_grad():
            value_tensor = micro_model.policy.predict_values(obs_tensor)
        value_array = value_tensor.detach().cpu().numpy().reshape(-1)
        if value_array.size != 1:
            raise ValueError(
                f"Expected scalar policy value for rule choice evaluation, got shape {value_array.shape}"
            )
        option_value = float(value_array[0])
        if np.isnan(option_value):
            raise ValueError("Policy value for rule choice evaluation is NaN")
        return option_value

    def select_rule_choice_with_policy(
        self, prompt: Dict[str, Any], game_state: Dict[str, Any], engine
    ) -> str:
        """
        Select one rule-choice option with trained policy evaluation.

        Strategy:
        - Simulate each candidate option by setting `_selected_granted_rule_id`.
        - Build the unit observation for that simulated state.
        - Score with the micro-policy value head.
        - Pick the option with the highest value (deterministic tie-break by display_rule_id).
        """
        if not self.micro_models:
            raise RuntimeError("Micro models not loaded for policy-based rule choice")

        options = require_key(prompt, "options")
        if not isinstance(options, list) or not options:
            raise ValueError(f"Rule choice prompt requires non-empty options list, got: {options!r}")
        unit_id = str(require_key(prompt, "unit_id"))
        rule_id = require_key(prompt, "rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"Rule choice prompt requires non-empty rule_id, got: {rule_id!r}")

        unit = engine._get_unit_by_id(unit_id)
        if unit is None:
            raise KeyError(f"Cannot evaluate rule choice: unit {unit_id} not found")
        unit_rules = require_key(unit, "UNIT_RULES")
        if not isinstance(unit_rules, list):
            raise TypeError(f"UNIT_RULES must be a list for unit {unit_id}")

        source_rule_entry = None
        for unit_rule in unit_rules:
            if require_key(unit_rule, "ruleId") == rule_id:
                source_rule_entry = unit_rule
                break
        if source_rule_entry is None:
            raise KeyError(f"Rule '{rule_id}' not found in UNIT_RULES for unit {unit_id}")

        previous_selected_rule_id = source_rule_entry.get("_selected_granted_rule_id")
        option_scores: List[Tuple[str, float]] = []
        try:
            for option in options:
                display_rule_id = require_key(option, "display_rule_id")
                if not isinstance(display_rule_id, str) or not display_rule_id.strip():
                    raise ValueError(f"Invalid display_rule_id in rule choice option: {option!r}")
                normalized_display_rule_id = display_rule_id.strip()
                source_rule_entry["_selected_granted_rule_id"] = normalized_display_rule_id
                option_value = self._evaluate_rule_choice_option_value(unit_id, game_state, engine)
                option_scores.append((normalized_display_rule_id, option_value))
        finally:
            source_rule_entry["_selected_granted_rule_id"] = previous_selected_rule_id

        if not option_scores:
            raise ValueError(f"No option scores computed for prompt: {prompt!r}")

        best_value = max(score for _, score in option_scores)
        best_display_rule_ids = [
            display_rule_id for display_rule_id, score in option_scores if score == best_value
        ]
        if not best_display_rule_ids:
            raise ValueError(f"No best option found despite computed scores: {option_scores!r}")
        return sorted(best_display_rule_ids)[0]

    def _get_micro_model_for_unit_id(self, unit_id: str, game_state: Dict[str, Any]):
        """Get micro model for a specific unit id."""
        model, _ = self._get_micro_model_and_path_for_unit_id(unit_id, game_state)
        return model

    def _get_micro_model_and_path_for_unit_id(
        self, unit_id: str, game_state: Dict[str, Any], engine=None
    ):
        """Get micro model and its path for a specific unit id (for VecNormalize inference).
        If model_key is not loaded, attempts lazy load when engine is provided."""
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if not self.unit_registry:
            raise ValueError("unit_registry is required to resolve micro model key")
        unit_type = require_key(unit, "unitType")
        model_key = self.unit_registry.get_model_key(unit_type)
        if model_key not in self.micro_models:
            if engine is not None:
                self._load_micro_model_lazy(model_key, engine)
            else:
                raise KeyError(f"Micro model not loaded for model_key={model_key}")
        model_path = self.micro_model_paths.get(model_key, "")
        return self.micro_models[model_key], model_path

    def _load_micro_model_lazy(self, model_key: str, engine) -> None:
        """Load a single micro model on demand (for roster change after initial load)."""
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker

        def mask_fn(env):
            return env.get_action_mask()

        masked_env = ActionMasker(engine, mask_fn)
        config = get_config_loader()
        models_root = config.get_models_root()
        shared_micro_model_key = require_key(self.config, "controlled_agent")
        if not isinstance(shared_micro_model_key, str) or not shared_micro_model_key.strip():
            raise ValueError(
                f"controlled_agent must be a non-empty string in PvE config "
                f"(got {shared_micro_model_key!r})"
            )
        model_storage_key = config._resolve_agent_config_key(shared_micro_model_key.strip())
        model_path = os.path.join(
            models_root,
            model_storage_key,
            f"model_{model_storage_key}.zip",
        )
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Micro model required for PvE mode not found: {model_path}"
            )
        self.micro_models[model_key] = MaskablePPO.load(model_path, env=masked_env)
        self.micro_model_paths[model_key] = model_path
        if not self.quiet:
            print(
                f"PvE: Lazy-loaded micro model for '{model_key}' "
                f"using shared model '{model_storage_key}'"
            )

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