#!/usr/bin/env python3
"""
action_decoder.py - Decodes actions and computes masks
"""

import numpy as np
from typing import Dict, List, Any
from engine.game_utils import get_unit_by_id

class ActionDecoder:
    """Decodes actions and computes valid action masks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    # ============================================================================
    # ACTION MASKING
    # ============================================================================
    
    def get_action_mask(self, game_state: Dict[str, Any]) -> np.ndarray:
        """Return action mask with dynamic target slot masking - True = valid action."""
        mask = np.zeros(12, dtype=bool)
        current_phase = game_state["phase"]
        eligible_units = self._get_eligible_units_for_current_phase(game_state)
        
        if not eligible_units:
            # No units can act - only system actions allowed (handled internally)
            return mask  # All False - no valid actions
        
        if current_phase == "move":
            # Movement phase: actions 0-3 (movement strategies) + 11 (wait)
            # Actions 0-3 now map to strategic heuristics:
            # 0 = aggressive (toward enemies)
            # 1 = tactical (shooting position)
            # 2 = defensive (away from enemies)
            # 3 = random (exploration)
            mask[[0, 1, 2, 3]] = True
            mask[11] = True  # Wait always valid
        elif current_phase == "shoot":
            # Shooting phase: actions 4-8 (target slots 0-4) + 11 (wait)
            # CRITICAL FIX: Dynamically enable based on ACTUAL available targets
            active_unit = eligible_units[0] if eligible_units else None
            if active_unit:
                from engine.phase_handlers import shooting_handlers
                valid_targets = shooting_handlers.shooting_build_valid_target_pool(
                    game_state, active_unit["id"]
                )
                num_targets = len(valid_targets)
                
                # CRITICAL: Only enable target slots if targets exist
                if num_targets > 0:
                    # Enable shoot actions for available targets only (up to 5 slots)
                    for i in range(min(5, num_targets)):
                        mask[4 + i] = True
            
            mask[11] = True  # Wait always valid (can choose not to shoot)
        elif current_phase == "charge":
            # Charge phase: action 9 (charge) + 11 (wait)
            mask[[9, 11]] = True
        elif current_phase == "fight":
            # Fight phase: action 10 (fight) only - no wait in fight
            mask[10] = True
        
        return mask
    
    def _get_valid_actions_for_phase(self, phase: str) -> List[int]:
        """Get valid action types for current phase with target selection support."""
        if phase == "move":
            return [0, 1, 2, 3, 11]  # Move directions + wait
        elif phase == "shoot":
            return [4, 5, 6, 7, 8, 11]  # Target slots 0-4 + wait
        elif phase == "charge":
            return [9, 11]  # Charge + wait
        elif phase == "fight":
            return [10]  # Fight only - NO WAIT in fight phase
        else:
            return [11]  # Only wait for unknown phases
    
    def _get_eligible_units_for_current_phase(self, game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get eligible units for current phase using handler's authoritative pools."""
        current_phase = game_state["phase"]
        
        if current_phase == "move":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "move_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'move_activation_pool' field")
            pool_unit_ids = game_state["move_activation_pool"]
            return [get_unit_by_id(uid, game_state) for uid in pool_unit_ids if get_unit_by_id(uid, game_state)]
        elif current_phase == "shoot":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "shoot_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'shoot_activation_pool' field")
            pool_unit_ids = game_state["shoot_activation_pool"]
            return [get_unit_by_id(uid, game_state) for uid in pool_unit_ids if get_unit_by_id(uid, game_state)]
        else:
            return []
    
    # ============================================================================
    # ACTION CONVERSION
    # ============================================================================
    
    def convert_gym_action(self, action: int, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """Convert gym integer action to semantic action with target selection support."""
        # CRITICAL: Convert numpy types to Python int FIRST
        if hasattr(action, 'item'):
            action_int = int(action.item())
        elif isinstance(action, np.ndarray):
            action_int = int(action.flatten()[0])
        else:
            action_int = int(action)
        
        current_phase = game_state["phase"]
        
        # Validate action against mask - convert invalid actions to SKIP
        action_mask = self.get_action_mask(game_state)        
        if not action_mask[action_int]:
            # Return invalid action for training penalty and proper pool management
            eligible_units = self._get_eligible_units_for_current_phase(game_state)
            if eligible_units:
                selected_unit_id = eligible_units[0]["id"]
                return {
                    "action": "invalid", 
                    "error": f"forbidden_in_{current_phase}_phase", 
                    "unitId": selected_unit_id,
                    "attempted_action": action_int,
                    "end_activation_required": True
                }
            else:
                return {"action": "advance_phase", "from": current_phase, "reason": "no_eligible_units"}
        
        # Get eligible units for current phase - AI_TURN.md sequential activation
        eligible_units = self._get_eligible_units_for_current_phase(game_state)
        
        if not eligible_units:
            current_phase = game_state["phase"]
            if current_phase == "move":
                self._shooting_phase_init()
                return {"action": "advance_phase", "from": "move", "to": "shoot"}
            elif current_phase == "shoot":
                self._advance_to_next_player()
                return {"action": "advance_phase", "from": "shoot", "to": "move"}
            else:
                return {"action": "invalid", "error": "no_eligible_units", "unitId": "SYSTEM"}
        
        # GUARANTEED UNIT SELECTION - use first eligible unit directly
        selected_unit_id = eligible_units[0]["id"]
        
        if current_phase == "move":
            if action_int in [0, 1, 2, 3]:  # Move with strategic heuristic
                # Actions 0-3 map to movement strategies:
                # 0 = aggressive (toward enemies)
                # 1 = tactical (shooting position)
                # 2 = defensive (away from enemies)
                # 3 = random (exploration)

                # Get unit to activate and build destinations
                from engine.phase_handlers import movement_handlers
                unit = movement_handlers._get_unit_by_id(game_state, selected_unit_id)

                # Build valid destinations using BFS
                movement_handlers.movement_build_valid_destinations_pool(game_state, selected_unit_id)
                valid_destinations = game_state.get("valid_move_destinations_pool", [])

                if not valid_destinations:
                    # No valid moves - skip
                    return {"action": "skip", "unitId": selected_unit_id}

                # Use strategic selector to pick destination
                dest_col, dest_row = movement_handlers._select_strategic_destination(
                    action_int,
                    valid_destinations,
                    unit,
                    game_state
                )

                return {
                    "action": "move",
                    "unitId": selected_unit_id,
                    "destCol": dest_col,
                    "destRow": dest_row
                }
            elif action_int == 11:  # WAIT - agent chooses not to move
                return {"action": "skip", "unitId": selected_unit_id}
                
        elif current_phase == "shoot":
            if action_int in [4, 5, 6, 7, 8]:  # Shoot target slots 0-4
                target_slot = action_int - 4  # Convert to slot index (0-4)
                
                # Get valid targets for this unit
                from engine.phase_handlers import shooting_handlers
                valid_targets = shooting_handlers.shooting_build_valid_target_pool(
                    game_state, selected_unit_id
                )
                
                # CRITICAL: Validate target slot is within valid range
                if target_slot < len(valid_targets):
                    target_id = valid_targets[target_slot]
                    
                    # Debug: Log first few target selections
                    if game_state["turn"] == 1 and not hasattr(self, '_target_logged'):
                        self._target_logged = True
                    
                    return {
                        "action": "shoot",
                        "unitId": selected_unit_id,
                        "targetId": target_id
                    }
                else:
                    return {
                        "action": "wait",
                        "unitId": selected_unit_id,
                        "invalid_action_penalty": True,
                        "attempted_action": action_int
                    }
                    
            elif action_int == 11:  # WAIT - agent chooses not to shoot
                return {"action": "wait", "unitId": selected_unit_id}
                
        elif current_phase == "charge":
            if action_int == 9:  # Charge action
                target = self._ai_select_charge_target(selected_unit_id)
                return {
                    "action": "charge", 
                    "unitId": selected_unit_id, 
                    "targetId": target
                }
            elif action_int == 11:  # WAIT - agent chooses not to charge
                return {"action": "wait", "unitId": selected_unit_id}
                
        elif current_phase == "fight":
            if action_int == 10:  # Fight action - NO WAIT option in fight phase
                selected_unit = self._ai_select_unit(eligible_units, "fight")
                target = self._ai_select_combat_target(selected_unit)
                return {
                    "action": "fight", 
                    "unitId": selected_unit, 
                    "targetId": target
                }
        
        valid_actions = self._get_valid_actions_for_phase(current_phase)
        if action_int not in valid_actions:
            return {"action": "invalid", "error": f"action_{action_int}_forbidden_in_{current_phase}_phase"}
        
        # SKIP is system response when no valid actions possible (not agent choice)
        return {"action": "skip", "reason": "no_valid_action_found"}
    
    # ============================================================================
    # TARGET VALIDATION
    # ============================================================================
    
    def get_all_valid_targets(self, unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all valid targets for unit based on current phase."""
        targets = []
        for enemy in game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                targets.append(enemy)
        return targets
    
    def can_melee_units_charge_target(self, target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if any friendly melee units can charge this target."""
        current_player = game_state["current_player"]
        
        for unit in game_state["units"]:
            if (unit["player"] == current_player and 
                unit["HP_CUR"] > 0 and
                unit["CC_DMG"] > 0):  # AI_TURN.md: Direct field access
                
                # Simple charge range check (2d6 movement + unit MOVE)
                distance = abs(unit["col"] - target["col"]) + abs(unit["row"] - target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                
                if distance <= max_charge_range:
                    return True
        
        return False