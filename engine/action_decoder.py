#!/usr/bin/env python3
"""
action_decoder.py - Decodes actions and computes masks
"""

import numpy as np
from typing import Dict, List, Any
from engine.game_utils import get_unit_by_id
from engine.combat_utils import calculate_hex_distance

# Game phases - single source of truth for phase count
GAME_PHASES = ["move", "shoot", "charge", "fight"]

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
            # No units can act - phase should auto-advance
            # CRITICAL: Fight phase has no wait action - return all False mask
            # to trigger auto-advance in w40k_core.step()
            if current_phase == "fight":
                # Fight phase with empty pools - return all False mask
                # This triggers auto-advance in step() function
                return mask  # All False
            # For other phases, enable WAIT action to allow phase processing
            mask[11] = True  # WAIT triggers phase transition when pool is empty
            return mask
        
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
            # CRITICAL FIX: Only enable fight action if there are eligible units
            if eligible_units:
                mask[10] = True
            # If no eligible units, action mask will be all False - handler will end phase
        
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
        elif current_phase == "charge":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "charge_activation_pool" not in game_state:
                return []  # Phase not initialized yet
            pool_unit_ids = game_state["charge_activation_pool"]
            return [get_unit_by_id(uid, game_state) for uid in pool_unit_ids if get_unit_by_id(uid, game_state)]
        elif current_phase == "fight":
            # AI_TURN.md: Fight phase has multiple sub-pools
            # Check all fight pools in priority order
            subphase = game_state.get("fight_subphase")
            if subphase == "charging":
                pool_unit_ids = game_state.get("charging_activation_pool", [])
            elif subphase == "alternating_active":
                pool_unit_ids = game_state.get("active_alternating_activation_pool", [])
            elif subphase in ("alternating_non_active", "alternating"):
                pool_unit_ids = game_state.get("non_active_alternating_activation_pool", [])
            else:
                # Fallback: check all pools
                pool_unit_ids = (
                    game_state.get("charging_activation_pool", []) +
                    game_state.get("active_alternating_activation_pool", []) +
                    game_state.get("non_active_alternating_activation_pool", [])
                )
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
            # No eligible units - signal phase advance needed
            current_phase = game_state["phase"]
            return {"action": "advance_phase", "from": current_phase, "reason": "pool_empty"}
        
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
            if action_int == 9:  # Charge action - handler selects target internally
                return {
                    "action": "charge",
                    "unitId": selected_unit_id
                }
            elif action_int == 11:  # WAIT - agent chooses not to charge
                return {"action": "skip", "unitId": selected_unit_id}
                
        elif current_phase == "fight":
            if action_int == 10:  # Fight action - handler selects target internally
                return {
                    "action": "fight",
                    "unitId": selected_unit_id
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
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
                (unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0 and
                 any(w.get("DMG", 0) > 0 for w in unit["CC_WEAPONS"]))):  # Has melee capability
                
                # Simple charge range check (2d6 movement + unit MOVE)
                distance = calculate_hex_distance(unit["col"], unit["row"], target["col"], target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                
                if distance <= max_charge_range:
                    return True
        
        return False