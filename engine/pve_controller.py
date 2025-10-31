#!/usr/bin/env python3
"""
pve_controller.py - PvE mode AI opponent
"""

import torch
import numpy as np
import os
from typing import Dict, Any, Tuple, List

class PvEController:
    """Controls AI opponent in PvE mode."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.ai_model = None
        self.unit_registry = unit_registry
        self.quiet = config.get("quiet", True)
    
    # ============================================================================
    # MODEL LOADING
    # ============================================================================
    
    def load_ai_model_for_pve(self, game_state: Dict[str, Any], engine):
        """Load trained AI model for PvE Player 2 - with diagnostic logging."""
        # Only show debug output in debug training mode
        debug_mode = hasattr(self, 'training_config') and self.training_config and \
                     self.config.get('training_config_name') == 'debug'
        
        if debug_mode:
            print(f"DEBUG: _load_ai_model_for_pve called")
        
        try:
            from sb3_contrib import MaskablePPO
            from sb3_contrib.common.wrappers import ActionMasker
            if debug_mode:
                print(f"DEBUG: MaskablePPO import successful")
            
            # Get AI model key from unit registry
            ai_model_key = "SpaceMarine_Infantry_Troop_RangedSwarm"  # Default
            if debug_mode:
                print(f"DEBUG: Default AI model key: {ai_model_key}")
            
            if self.unit_registry:
                player1_units = [u for u in game_state["units"] if u["player"] == 1]
                if player1_units:
                    unit_type = player1_units[0]["unitType"]
                    ai_model_key = self.unit_registry.get_model_key(unit_type)
            
            model_path = f"ai/models/current/model_{ai_model_key}.zip"
            if debug_mode:
                print(f"DEBUG: Model path: {model_path}")
                print(f"DEBUG: Model exists: {os.path.exists(model_path)}")
            
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"AI model required for PvE mode not found: {model_path}")
            
            # Wrap self with ActionMasker for MaskablePPO compatibility
            def mask_fn(env):
                return env.get_action_mask()
            
            masked_env = ActionMasker(engine, mask_fn)
            
            # Load model with masked environment
            self.ai_model = MaskablePPO.load(model_path, env=masked_env)
            print(f"DEBUG: AI model loaded successfully")
            if not self.quiet:
                print(f"PvE: Loaded AI model: {ai_model_key}")
                
        except Exception as e:
            print(f"DEBUG: _load_ai_model_for_pve exception: {e}")
            print(f"DEBUG: Exception type: {type(e).__name__}")
            # Set _ai_model to None on any failure
            self._ai_model = None
            raise  # Re-raise to see the full error
    
    # ============================================================================
    # AI DECISION MAKING
    # ============================================================================
    
    def make_ai_decision(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        AI decision logic - replaces human clicks with model predictions.
        Uses SAME handler paths as humans after decision is made.
        """
        # Get observation for AI model
        obs = self._build_observation()
        
        # Get AI model prediction
        prediction_result = self._ai_model.predict(obs, deterministic=True)
        
        if isinstance(prediction_result, tuple) and len(prediction_result) >= 1:
            action_int = prediction_result[0]
        elif hasattr(prediction_result, 'item'):
            action_int = prediction_result.item()
        else:
            action_int = int(prediction_result)
        
        # Convert to semantic action using existing method
        semantic_action = self._convert_gym_action(action_int)
        
        # Ensure AI player context
        current_player = game_state["current_player"]
        if current_player == 1:  # AI player
            # Get eligible units from current phase pool
            current_phase = game_state["phase"]
            if current_phase == "move":
                if "move_activation_pool" not in game_state:
                    raise KeyError("game_state missing required 'move_activation_pool' field")
                eligible_pool = game_state["move_activation_pool"]
            elif current_phase == "shoot":
                if "shoot_activation_pool" not in game_state:
                    raise KeyError("game_state missing required 'shoot_activation_pool' field")
                eligible_pool = game_state["shoot_activation_pool"]
            else:
                eligible_pool = []
            
            # Find AI unit in pool
            ai_unit_id = None
            for unit_id in eligible_pool:
                unit = self._get_unit_by_id(str(unit_id))
                if unit and unit["player"] == 1:
                    ai_unit_id = str(unit_id)
                    break
            
            if ai_unit_id:
                semantic_action["unitId"] = ai_unit_id
            
        return semantic_action
    
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
            return eligible_units[0]["id"]
    
    # ============================================================================
    # ACTION SELECTION
    # ============================================================================
    
    def _ai_select_movement_destination(self, unit_id: str, game_state: Dict[str, Any]) -> Tuple[int, int]:
        """AI selects movement destination that actually moves the unit."""
        unit = self._get_unit_by_id(unit_id)
        if not unit:
            raise ValueError(f"Unit not found: {unit_id}")
        
        current_pos = (unit["col"], unit["row"])
        
        # Use movement handler to get valid destinations
        from engine.phase_handlers import movement_handlers
        valid_destinations = movement_handlers.movement_build_valid_destinations_pool(game_state, unit_id)
        
        # Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # AI_TURN.md COMPLIANCE: No actual moves available → unit must WAIT, not attempt invalid move
        if not actual_moves:
            raise ValueError(f"No valid movement destinations for unit {unit_id} - should use WAIT action")
        
        # Strategy: Move toward nearest enemy for aggressive positioning
        enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        if enemies:
            # Find nearest enemy
            nearest_enemy = min(enemies, key=lambda e: abs(e["col"] - unit["col"]) + abs(e["row"] - unit["row"]))
            enemy_pos = (nearest_enemy["col"], nearest_enemy["row"])
            
            # Select move that gets closest to nearest enemy
            best_move = min(actual_moves, 
                           key=lambda dest: abs(dest[0] - enemy_pos[0]) + abs(dest[1] - enemy_pos[1]))
            
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