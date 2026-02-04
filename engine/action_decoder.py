#!/usr/bin/env python3
"""
action_decoder.py - Decodes actions and computes masks
"""

import numpy as np
from typing import Dict, List, Any, Optional
from shared.data_validation import require_key
from engine.game_utils import get_unit_by_id
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates
from engine.phase_handlers.shared_utils import is_unit_alive

# Game phases - single source of truth for phase count
GAME_PHASES = ["command", "move", "shoot", "charge", "fight"]

class ActionDecoder:
    """Decodes actions and computes valid action masks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    # ============================================================================
    # ACTION MASKING
    # ============================================================================
    
    def get_action_mask_and_eligible_units(self, game_state: Dict[str, Any]) -> tuple:
        """Return (mask, eligible_units). PERF: avoids recomputing eligible_units when both are needed."""
        mask = np.zeros(13, dtype=bool)  # ADVANCE_IMPLEMENTATION: 13 actions (0-12)
        current_phase = game_state["phase"]
        eligible_units = self._get_eligible_units_for_current_phase(game_state)

        if not eligible_units:
            # No units can act - phase should auto-advance
            # CRITICAL: Fight phase has no wait action - return all False mask
            # to trigger auto-advance in w40k_core.step()
            if current_phase == "fight":
                # Fight phase with empty pools - return all False mask
                # This triggers auto-advance in step() function
                return mask, eligible_units  # All False
            # For other phases, enable WAIT action to allow phase processing
            mask[11] = True  # WAIT triggers phase transition when pool is empty
            return mask, eligible_units

        if current_phase == "command":
            # Command phase: auto-advances, but enable WAIT for consistency
            mask[11] = True  # WAIT action
            return mask, eligible_units
        elif current_phase == "move":
            # Movement phase: actions 0-3 (movement strategies) + 11 (wait)
            # Actions 0-3 now map to strategic heuristics:
            # 0 = aggressive (toward enemies)
            # 1 = tactical (shooting position)
            # 2 = defensive (away from enemies)
            # 3 = random (exploration)
            mask[[0, 1, 2, 3]] = True
            mask[11] = True  # Wait always valid
        elif current_phase == "shoot":
            # Shooting phase: actions 4-8 (target slots 0-4) + 11 (wait) + 12 (advance)
            # ALIGNED WITH MOVE PHASE: Use eligible_units[0] directly, no special active_shooting_unit logic
            # Auto-activation is handled in execute_action (like MOVE phase)
            active_unit = eligible_units[0] if eligible_units else None
            
            if active_unit:
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    current_player = game_state.get("current_player", "?")
                    active_shooting_unit = game_state.get("active_shooting_unit")
                    shoot_pool = game_state.get("shoot_activation_pool")
                    add_debug_file_log(
                        game_state,
                        f"[MASK DEBUG] E{episode} T{turn} P{current_player} shoot mask: "
                        f"active_unit={active_unit.get('id')} active_shooting_unit={active_shooting_unit} "
                        f"valid_target_pool={active_unit.get('valid_target_pool')} "
                        f"shoot_activation_pool={shoot_pool}"
                    )
                # Ensure valid_target_pool is built before masking (activation may not have run yet)
                if "valid_target_pool" not in active_unit or active_unit.get("valid_target_pool") is None:
                    if active_unit.get("_shoot_activation_started", False):
                        raise ValueError(
                            "valid_target_pool missing after shooting activation start; "
                            f"unit_id={active_unit.get('id')}"
                        )
                    from engine.phase_handlers.shooting_handlers import shooting_build_valid_target_pool
                    shooting_build_valid_target_pool(game_state, str(active_unit.get("id")))
                # Enable shoot actions only when pool already exists (built during activation)
                valid_targets = active_unit.get("valid_target_pool")
                if valid_targets is not None:
                    # Enable only valid target slots (up to 5)
                    num_targets = len(valid_targets)
                    if num_targets > 0:
                        for i in range(min(5, num_targets)):
                            mask[4 + i] = True
                
                # ADVANCE_IMPLEMENTATION: Enable advance action if unit can advance
                # CAN_ADVANCE = alive AND not fled AND not adjacent to enemy (already checked in eligibility)
                can_advance = active_unit.get("_can_advance", True)  # Default True if flag not set
                if can_advance:
                    # Check if unit has NOT already advanced this turn
                    units_advanced = require_key(game_state, "units_advanced")
                    unit_id_str = str(active_unit["id"])
                    if unit_id_str not in units_advanced:
                        mask[12] = True  # Advance action

            mask[11] = True  # Wait always valid (can choose not to shoot)
        elif current_phase == "charge":
            # Charge phase: Check if unit is activated and has targets waiting
            active_unit = eligible_units[0] if eligible_units else None
            if active_unit:
                active_charge_unit = game_state.get("active_charge_unit")
                if active_charge_unit == active_unit["id"]:
                    # Unit is activated - check if waiting for target selection
                    if "pending_charge_targets" in game_state:
                        valid_targets = game_state["pending_charge_targets"]
                        num_targets = len(valid_targets)
                        if num_targets > 0:
                            # Enable target slots (actions 4-8) for available targets
                            for i in range(min(5, num_targets)):
                                mask[4 + i] = True
                    # Check if waiting for destination selection (after target selected and roll)
                    elif "valid_charge_destinations_pool" in game_state and game_state.get("valid_charge_destinations_pool"):
                        # After target selection and roll, destinations are available
                        # Enable destination slots (actions 4-8) for available destinations
                        valid_destinations = require_key(game_state, "valid_charge_destinations_pool")
                        num_destinations = len(valid_destinations)
                        if num_destinations > 0:
                            # Enable destination actions for available destinations (up to 5 slots)
                            for i in range(min(5, num_destinations)):
                                mask[4 + i] = True
                    else:
                        # Unit activated but no targets/destinations - should not happen
                        mask[9] = True
                else:
                    # Unit not activated yet - action 9 activates it
                    mask[9] = True
            mask[11] = True  # Wait always valid
        elif current_phase == "fight":
            # Fight phase: action 10 (fight) only - no wait in fight
            # CRITICAL FIX: Only enable fight action if there are eligible units
            if eligible_units:
                mask[10] = True
            # If no eligible units, action mask will be all False - handler will end phase

        return mask, eligible_units

    def get_action_mask(self, game_state: Dict[str, Any]) -> np.ndarray:
        """Return action mask with dynamic target slot masking - True = valid action."""
        mask, _ = self.get_action_mask_and_eligible_units(game_state)
        return mask
    
    def _get_valid_actions_for_phase(self, phase: str) -> List[int]:
        """Get valid action types for current phase with target selection support."""
        if phase == "move":
            return [0, 1, 2, 3, 11]  # Move directions + wait
        elif phase == "shoot":
            return [4, 5, 6, 7, 8, 11, 12]  # Target slots 0-4 + wait + advance
        elif phase == "charge":
            return [9, 11]  # Charge + wait
        elif phase == "fight":
            return [10]  # Fight only - NO WAIT in fight phase
        else:
            return [11]  # Only wait for unknown phases
    
    def _get_eligible_units_for_current_phase(self, game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get eligible units for current phase using handler's authoritative pools.
        
        CRITICAL: Filter out dead units when reading from pools.
        Units can die between pool construction and pool usage, so we must filter here.
        """
        current_phase = game_state["phase"]

        if current_phase == "command":
            return []  # Empty pool for now, ready for future
        elif current_phase == "move":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "move_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'move_activation_pool' field")
            pool_unit_ids = game_state["move_activation_pool"]
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        elif current_phase == "shoot":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            # STEP 2: UNIT_ACTIVABLE_CHECK - Pick one unit from shoot_activation_pool
            # No filtering by SHOOT_LEFT or can_advance - pool is built once at phase start
            # Units are removed ONLY via end_activation() with Arg4 = SHOOTING
            if "shoot_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'shoot_activation_pool' field")
            pool_unit_ids = game_state["shoot_activation_pool"]
            current_player = require_key(game_state, "current_player")
            try:
                current_player_int = int(current_player)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid current_player value: {current_player}") from exc
            # PRINCIPLE: "Le Pool DOIT gérer les morts" - Pool should never contain dead units
            # If a unit dies after pool build, _remove_dead_unit_from_pools should have removed it
            # Defense in depth: filter dead units here as safety check only
            # CRITICAL: Pool contains string IDs (normalized at creation in shooting_build_activation_pool)
            eligible = []
            for uid in pool_unit_ids:
                # CRITICAL: Normalize uid to string for get_unit_by_id (which normalizes both sides)
                uid_str = str(uid)
                unit = get_unit_by_id(uid_str, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    cache_entry = require_key(game_state, "units_cache").get(uid_str)
                    if cache_entry is None:
                        raise KeyError(f"Unit {uid_str} missing from units_cache")
                    unit_player = require_key(cache_entry, "player")
                    try:
                        unit_player_int = int(unit_player)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"Invalid player value in units_cache for unit {uid_str}: {unit_player}") from exc
                    if unit_player_int == current_player_int:
                        # AI_TURN.md: All units in pool are eligible - no SHOOT_LEFT filtering
                        eligible.append(unit)
            return eligible
        elif current_phase == "charge":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "charge_activation_pool" not in game_state:
                return []  # Phase not initialized yet
            pool_unit_ids = game_state["charge_activation_pool"]
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        elif current_phase == "fight":
            # Fight phase has multiple sub-pools
            # Check all fight pools in priority order
            subphase = game_state.get("fight_subphase")
            if subphase == "charging":
                pool_unit_ids = require_key(game_state, "charging_activation_pool")
            elif subphase == "alternating_active":
                pool_unit_ids = require_key(game_state, "active_alternating_activation_pool")
            elif subphase in ("alternating_non_active", "alternating"):
                pool_unit_ids = require_key(game_state, "non_active_alternating_activation_pool")
            else:
                # Check all pools (all keys required)
                pool_unit_ids = (
                    require_key(game_state, "charging_activation_pool") +
                    require_key(game_state, "active_alternating_activation_pool") +
                    require_key(game_state, "non_active_alternating_activation_pool")
                )
            # CRITICAL: Filter out dead units (units can die between pool build and use)
            eligible = []
            for uid in pool_unit_ids:
                unit = get_unit_by_id(uid, game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
        else:
            return []
    
    # ============================================================================
    # ACTION CONVERSION
    # ============================================================================
    
    def convert_gym_action(
        self,
        action: int,
        game_state: Dict[str, Any],
        action_mask: Optional[np.ndarray] = None,
        eligible_units: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Convert gym integer action to semantic action with target selection support.
        PERF: When action_mask and eligible_units are provided (e.g. from step), avoids recomputing them."""
        # CRITICAL: Convert numpy types to Python int FIRST
        if hasattr(action, 'item'):
            action_int = int(action.item())
        elif isinstance(action, np.ndarray):
            action_int = int(action.flatten()[0])
        else:
            action_int = int(action)

        current_phase = game_state["phase"]

        # Use provided mask/units or compute (e.g. PvE, other callers)
        if action_mask is None or eligible_units is None:
            action_mask, eligible_units = self.get_action_mask_and_eligible_units(game_state)

        # Validate action against mask - convert invalid actions to SKIP
        if not action_mask[action_int]:
            # Return invalid action for training penalty and proper pool management
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
                unit = get_unit_by_id(selected_unit_id, game_state)

                # Build valid destinations using BFS
                movement_handlers.movement_build_valid_destinations_pool(game_state, selected_unit_id)
                valid_destinations = require_key(game_state, "valid_move_destinations_pool")

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
                
                # PERFORMANCE: Use cached pool from unit activation instead of recalculating
                # Pool is built at activation and after advance; it must be available here
                # Pool is automatically updated when targets die (dead targets are removed, shooting_handlers.py line 3183)
                selected_unit = get_unit_by_id(selected_unit_id, game_state)
                if not selected_unit:
                    raise ValueError(f"Selected unit not found for shooting: unit_id={selected_unit_id}")
                valid_targets = require_key(selected_unit, "valid_target_pool")
                if valid_targets is None:
                    raise ValueError(f"valid_target_pool is None for unit: unit_id={selected_unit_id}")
                
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
            
            elif action_int == 12:  # ADVANCE - agent chooses to advance instead of shoot
                # ADVANCE_IMPLEMENTATION: Convert to advance action
                # Handler will roll 1D6 and select destination
                return {
                    "action": "advance",
                    "unitId": selected_unit_id
                }
                
        elif current_phase == "charge":
            active_charge_unit = game_state.get("active_charge_unit")
            
            # Check if unit is activated and waiting for target selection
            if active_charge_unit == selected_unit_id and "pending_charge_targets" in game_state:
                valid_targets = game_state["pending_charge_targets"]
                if action_int in [4, 5, 6, 7, 8]:  # Target slots 0-4
                    target_slot = action_int - 4
                    if target_slot < len(valid_targets):
                        target_id = valid_targets[target_slot]["id"]
                        return {
                            "action": "charge",
                            "unitId": selected_unit_id,
                            "targetId": target_id
                        }
                    else:
                        return {
                            "action": "invalid",
                            "unitId": selected_unit_id,
                            "error": "invalid_target_slot",
                            "attempted_action": action_int
                        }
            
            # Check if unit is activated and waiting for destination selection (after target and roll)
            if active_charge_unit == selected_unit_id and "valid_charge_destinations_pool" in game_state:
                valid_destinations = require_key(game_state, "valid_charge_destinations_pool")
                if valid_destinations and action_int in [4, 5, 6, 7, 8]:
                    # Destination selection (gym mode auto-selects, but allow manual for consistency)
                    dest_slot = action_int - 4
                    if dest_slot < len(valid_destinations):
                        dest_col, dest_row = valid_destinations[dest_slot]
                        return {
                            "action": "charge",
                            "unitId": selected_unit_id,
                            "destCol": dest_col,
                            "destRow": dest_row
                        }
            
            if action_int == 9:  # Charge action - activates unit or triggers charge
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
        units_cache = require_key(game_state, "units_cache")
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        for enemy_id, cache_entry in units_cache.items():
            if int(cache_entry["player"]) != unit_player:
                enemy = get_unit_by_id(enemy_id, game_state)
                if enemy is None:
                    raise KeyError(f"Unit {enemy_id} missing from game_state['units']")
                targets.append(enemy)
        return targets
    
    def can_melee_units_charge_target(self, target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if any friendly melee units can charge this target."""
        current_player = game_state["current_player"]
        
        units_cache = require_key(game_state, "units_cache")
        for unit_id, cache_entry in units_cache.items():
            if cache_entry["player"] == current_player:
                unit = get_unit_by_id(unit_id, game_state)
                if unit is None:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                if (unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0 and
                    any(require_key(w, "DMG") > 0 for w in unit["CC_WEAPONS"])):  # Has melee capability
                    
                    # Simple charge range check (2d6 movement + unit MOVE)
                    distance = calculate_hex_distance(*get_unit_coordinates(unit), *get_unit_coordinates(target))
                    if "MOVE" not in unit:
                        raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                    max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                    
                    if distance <= max_charge_range:
                        return True
        
        return False
