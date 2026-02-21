#!/usr/bin/env python3
"""
action_decoder.py - Decodes actions and computes masks
"""

import numpy as np
from typing import Dict, List, Any, Optional
from shared.data_validation import require_key
from engine.game_utils import get_unit_by_id
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates, has_line_of_sight
from engine.phase_handlers.shared_utils import is_unit_alive

# Game phases - single source of truth for phase count
GAME_PHASES = ["deployment", "command", "move", "shoot", "charge", "fight"]

class ActionValidationError(ValueError):
    """Raised when an action fails strict normalization or mask validation."""

    def __init__(self, code: str, message: str, context: Dict[str, Any]):
        self.code = code
        self.context = context
        super().__init__(f"{code}: {message} | context={context}")


class ActionDecoder:
    """Decodes actions and computes valid action masks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    # ============================================================================
    # ACTION MASKING
    # ============================================================================
    
    def get_action_mask_and_eligible_units(self, game_state: Dict[str, Any]) -> tuple:
        """Return (mask, eligible_units). PERF: avoids recomputing eligible_units when both are needed."""
        eligible_units = self._get_eligible_units_for_current_phase(game_state)
        mask = self._build_mask_for_units(game_state["phase"], eligible_units, game_state)
        return mask, eligible_units

    def get_action_mask_for_unit(self, game_state: Dict[str, Any], unit_id: str) -> tuple:
        """Return (mask, [unit]) for a specific unit without reordering pools."""
        current_phase = game_state["phase"]
        eligible_units = self._get_eligible_units_for_current_phase(game_state)
        selected_unit = None
        for unit in eligible_units:
            if str(unit.get("id")) == str(unit_id):
                selected_unit = unit
                break
        if selected_unit is None:
            raise ValueError(f"Unit {unit_id} is not eligible in phase '{current_phase}'")
        mask = self._build_mask_for_units(current_phase, [selected_unit], game_state)
        return mask, [selected_unit]

    def _build_mask_for_units(
        self,
        current_phase: str,
        eligible_units: List[Dict[str, Any]],
        game_state: Dict[str, Any],
    ) -> np.ndarray:
        """Build action mask for provided eligible_units list."""
        mask = np.zeros(13, dtype=bool)  # ADVANCE_IMPLEMENTATION: 13 actions (0-12)
        if not eligible_units:
            # No units can act - phase should auto-advance
            # CRITICAL: Fight phase has no wait action - return all False mask
            # to trigger auto-advance in w40k_core.step()
            if current_phase == "fight":
                return mask
            # For other phases, enable WAIT action to allow phase processing
            mask[11] = True
            return mask

        if current_phase == "deployment":
            active_unit = eligible_units[0] if eligible_units else None
            if active_unit:
                current_deployer = self._get_current_deployer(game_state)
                valid_hexes = self._get_valid_deployment_hexes(game_state, current_deployer)
                num_hexes = len(valid_hexes)
                if num_hexes == 0:
                    raise ValueError(
                        f"Deployment deadlock: no valid hex for player {current_deployer}, "
                        f"unit {active_unit.get('id')}"
                    )
                for i in range(min(5, num_hexes)):
                    mask[4 + i] = True
            return mask
        if current_phase == "command":
            mask[11] = True
            return mask
        elif current_phase == "move":
            mask[[0, 1, 2, 3]] = True
            mask[11] = True
        elif current_phase == "shoot":
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
                if "valid_target_pool" not in active_unit or active_unit.get("valid_target_pool") is None:
                    if active_unit.get("_shoot_activation_started", False):
                        raise ValueError(
                            "valid_target_pool missing after shooting activation start; "
                            f"unit_id={active_unit.get('id')}"
                        )
                    from engine.phase_handlers.shooting_handlers import shooting_build_valid_target_pool
                    shooting_build_valid_target_pool(game_state, str(active_unit.get("id")))
                valid_targets = active_unit.get("valid_target_pool")
                if valid_targets is not None:
                    num_targets = len(valid_targets)
                    if num_targets > 0:
                        for i in range(min(5, num_targets)):
                            mask[4 + i] = True
                can_advance = active_unit.get("_can_advance", True)
                if can_advance:
                    units_advanced = require_key(game_state, "units_advanced")
                    unit_id_str = str(active_unit["id"])
                    if unit_id_str not in units_advanced:
                        mask[12] = True
            mask[11] = True
        elif current_phase == "charge":
            active_unit = eligible_units[0] if eligible_units else None
            if active_unit:
                active_charge_unit = game_state.get("active_charge_unit")
                if active_charge_unit == active_unit["id"]:
                    if "pending_charge_targets" in game_state:
                        valid_targets = game_state["pending_charge_targets"]
                        num_targets = len(valid_targets)
                        if num_targets > 0:
                            for i in range(min(5, num_targets)):
                                mask[4 + i] = True
                    elif "valid_charge_destinations_pool" in game_state and game_state.get("valid_charge_destinations_pool"):
                        valid_destinations = require_key(game_state, "valid_charge_destinations_pool")
                        num_destinations = len(valid_destinations)
                        if num_destinations > 0:
                            for i in range(min(5, num_destinations)):
                                mask[4 + i] = True
                    else:
                        mask[9] = True
                else:
                    mask[9] = True
            mask[11] = True
        elif current_phase == "fight":
            if eligible_units:
                mask[10] = True
        return mask

    def get_action_mask(self, game_state: Dict[str, Any]) -> np.ndarray:
        """Return action mask with dynamic target slot masking - True = valid action."""
        mask, _ = self.get_action_mask_and_eligible_units(game_state)
        return mask
    
    def _get_valid_actions_for_phase(self, phase: str) -> List[int]:
        """Get valid action types for current phase with target selection support."""
        if phase == "deployment":
            return [4, 5, 6, 7, 8]  # Deployment hex slots 0-4
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

        if current_phase == "deployment":
            deployment_state = require_key(game_state, "deployment_state")
            current_deployer = self._get_current_deployer(game_state)
            deployable_units = require_key(deployment_state, "deployable_units")
            deployable_list = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
            if deployable_list is None:
                raise KeyError(f"deployable_units missing player {current_deployer}")
            eligible = []
            for uid in deployable_list:
                unit = get_unit_by_id(str(uid), game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    eligible.append(unit)
            return eligible
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

    def normalize_action_input(
        self,
        raw_action: Any,
        phase: str,
        source: str,
        action_space_size: int,
    ) -> int:
        """Normalize action to int with strict type and range checks."""
        context = {
            "phase": phase,
            "source": source,
            "raw_action_repr": repr(raw_action),
            "raw_action_type": type(raw_action).__name__,
        }

        if isinstance(raw_action, bool):
            raise ActionValidationError("invalid_type", "bool action is not allowed", context)

        if isinstance(raw_action, np.ndarray):
            if raw_action.size != 1:
                raise ActionValidationError(
                    "invalid_shape",
                    f"numpy action must be scalar-like, got size={raw_action.size}",
                    context,
                )
            raw_action = raw_action.item()
            context["normalized_from"] = "ndarray"
            context["raw_action_type"] = type(raw_action).__name__

        if isinstance(raw_action, np.generic):
            raw_action = raw_action.item()
            context["normalized_from"] = "numpy_scalar"
            context["raw_action_type"] = type(raw_action).__name__

        if not isinstance(raw_action, int):
            raise ActionValidationError(
                "invalid_type",
                f"action must be int-compatible, got {type(raw_action).__name__}",
                context,
            )

        action_int = int(raw_action)
        if action_int < 0 or action_int >= action_space_size:
            context["normalized_action"] = action_int
            context["action_space_size"] = action_space_size
            raise ActionValidationError(
                "out_of_range",
                f"action {action_int} outside [0, {action_space_size - 1}]",
                context,
            )
        return action_int

    def validate_action_against_mask(
        self,
        action_int: int,
        action_mask: np.ndarray,
        phase: str,
        source: str,
        unit_id: Optional[Any] = None,
    ) -> None:
        """Validate normalized action against action mask."""
        if action_mask.dtype != bool:
            raise TypeError(f"action_mask must be bool dtype, got {action_mask.dtype}")
        if action_int >= len(action_mask):
            raise ActionValidationError(
                "out_of_range",
                f"action {action_int} outside mask length {len(action_mask)}",
                {"phase": phase, "source": source, "unit_id": unit_id},
            )
        if not bool(action_mask[action_int]):
            valid_actions = [i for i, is_valid in enumerate(action_mask) if bool(is_valid)]
            raise ActionValidationError(
                "masked_out",
                f"action {action_int} is masked out",
                {
                    "phase": phase,
                    "source": source,
                    "unit_id": unit_id,
                    "action": action_int,
                    "valid_actions": valid_actions,
                },
            )
    
    def convert_gym_action(
        self,
        action: int,
        game_state: Dict[str, Any],
        action_mask: Optional[np.ndarray] = None,
        eligible_units: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Convert gym integer action to semantic action with target selection support.
        PERF: When action_mask and eligible_units are provided (e.g. from step), avoids recomputing them."""
        current_phase = game_state["phase"]
        action_int = self.normalize_action_input(
            raw_action=action,
            phase=current_phase,
            source="gym",
            action_space_size=13,
        )

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
        
        if current_phase == "deployment":
            if action_int in [4, 5, 6, 7, 8]:
                current_deployer = self._get_current_deployer(game_state)
                valid_hexes = self._get_valid_deployment_hexes(game_state, current_deployer)
                if not valid_hexes:
                    return {
                        "action": "invalid",
                        "error": "no_valid_deployment_hexes",
                        "unitId": selected_unit_id,
                        "attempted_action": action_int,
                        "end_activation_required": False,
                    }
                dest_col, dest_row = self._select_deployment_hex_for_action(
                    action_int=action_int,
                    unit_id=selected_unit_id,
                    game_state=game_state,
                    current_deployer=current_deployer,
                    valid_hexes=valid_hexes,
                )
                return {
                    "action": "deploy_unit",
                    "unitId": selected_unit_id,
                    "destCol": dest_col,
                    "destRow": dest_row,
                }
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

    def _get_current_deployer(self, game_state: Dict[str, Any]) -> int:
        """Return current deployment player with strict validation."""
        deployment_state = require_key(game_state, "deployment_state")
        current_deployer = require_key(deployment_state, "current_deployer")
        try:
            return int(current_deployer)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid deployment current_deployer: {current_deployer}") from exc

    def _get_valid_deployment_hexes(self, game_state: Dict[str, Any], current_deployer: int) -> List[tuple]:
        """Build sorted list of currently valid deployment hexes for player."""
        deployment_state = require_key(game_state, "deployment_state")
        deployment_pools = require_key(deployment_state, "deployment_pools")
        pool = deployment_pools.get(current_deployer, deployment_pools.get(str(current_deployer)))
        if pool is None:
            raise KeyError(f"deployment_pools missing player {current_deployer}")

        occupied = set()
        for unit in require_key(game_state, "units"):
            unit_col = int(require_key(unit, "col"))
            unit_row = int(require_key(unit, "row"))
            if unit_col >= 0 and unit_row >= 0:
                occupied.add((unit_col, unit_row))

        valid_hexes = []
        for raw_hex in pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                col, row = int(raw_hex[0]), int(raw_hex[1])
            elif isinstance(raw_hex, dict):
                col = int(require_key(raw_hex, "col"))
                row = int(require_key(raw_hex, "row"))
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
            if (col, row) not in occupied:
                valid_hexes.append((col, row))

        return sorted(valid_hexes)

    def _get_enemy_reference_hexes(self, game_state: Dict[str, Any], current_deployer: int) -> List[tuple[int, int]]:
        """
        Build enemy reference hexes for distance scoring.

        Uses currently deployed enemy units when available; otherwise uses enemy deployment pool.
        """
        enemy_player = 2 if int(current_deployer) == 1 else 1
        enemy_deployed = []
        for unit in require_key(game_state, "units"):
            unit_player = int(require_key(unit, "player"))
            if unit_player != enemy_player:
                continue
            col = int(require_key(unit, "col"))
            row = int(require_key(unit, "row"))
            if col >= 0 and row >= 0:
                enemy_deployed.append((col, row))
        if enemy_deployed:
            return enemy_deployed

        deployment_state = require_key(game_state, "deployment_state")
        deployment_pools = require_key(deployment_state, "deployment_pools")
        if enemy_player in deployment_pools:
            enemy_pool = deployment_pools[enemy_player]
        elif str(enemy_player) in deployment_pools:
            enemy_pool = deployment_pools[str(enemy_player)]
        else:
            raise KeyError(f"deployment_pools missing player {enemy_player}")
        parsed_enemy_pool = []
        for raw_hex in enemy_pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                parsed_enemy_pool.append((int(raw_hex[0]), int(raw_hex[1])))
            elif isinstance(raw_hex, dict):
                parsed_enemy_pool.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
        return parsed_enemy_pool

    def _get_enemy_deployment_pool_hexes(
        self, game_state: Dict[str, Any], current_deployer: int
    ) -> List[tuple[int, int]]:
        """Get enemy deployment pool hexes (stable reference for potential LoS)."""
        enemy_player = 2 if int(current_deployer) == 1 else 1
        deployment_state = require_key(game_state, "deployment_state")
        deployment_pools = require_key(deployment_state, "deployment_pools")
        if enemy_player in deployment_pools:
            enemy_pool = deployment_pools[enemy_player]
        elif str(enemy_player) in deployment_pools:
            enemy_pool = deployment_pools[str(enemy_player)]
        else:
            raise KeyError(f"deployment_pools missing player {enemy_player}")
        parsed_enemy_pool = []
        for raw_hex in enemy_pool:
            if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                parsed_enemy_pool.append((int(raw_hex[0]), int(raw_hex[1])))
            elif isinstance(raw_hex, dict):
                parsed_enemy_pool.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
            else:
                raise TypeError(f"Invalid deployment hex format: {raw_hex}")
        return parsed_enemy_pool

    def _get_objective_hexes(self, game_state: Dict[str, Any]) -> List[tuple[int, int]]:
        """Extract objective hexes from game_state with strict validation."""
        objectives = require_key(game_state, "objectives")
        objective_hexes: List[tuple[int, int]] = []
        for objective in objectives:
            objective_hex_list = require_key(objective, "hexes")
            for raw_hex in objective_hex_list:
                if isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                    objective_hexes.append((int(raw_hex[0]), int(raw_hex[1])))
                elif isinstance(raw_hex, dict):
                    objective_hexes.append((int(require_key(raw_hex, "col")), int(require_key(raw_hex, "row"))))
                else:
                    raise TypeError(f"Invalid objective hex format: {raw_hex}")
        if not objective_hexes:
            raise ValueError("objectives are required for deployment scoring")
        return objective_hexes

    def _build_deployed_snapshot_version(
        self, deployed_snapshot: Dict[str, tuple[int, int, int]]
    ) -> tuple[tuple[str, int, int, int], ...]:
        """Build deterministic version token for currently deployed units."""
        version_items: List[tuple[str, int, int, int]] = []
        for unit_id, payload in deployed_snapshot.items():
            player, col, row = payload
            version_items.append((str(unit_id), int(player), int(col), int(row)))
        version_items.sort(key=lambda item: item[0])
        return tuple(version_items)

    def _has_line_of_sight_cached(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
        game_state: Dict[str, Any],
        los_pair_cache: Dict[tuple[int, int, int, int, tuple[tuple[str, int, int, int], ...]], bool],
        snapshot_version: tuple[tuple[str, int, int, int], ...],
    ) -> bool:
        """Memoized LoS lookup scoped to deployment snapshot version."""
        cache_key = (int(from_col), int(from_row), int(to_col), int(to_row), snapshot_version)
        if cache_key in los_pair_cache:
            return los_pair_cache[cache_key]
        result = has_line_of_sight(
            {"col": int(from_col), "row": int(from_row)},
            {"col": int(to_col), "row": int(to_row)},
            game_state,
        )
        los_pair_cache[cache_key] = result
        return result

    def _count_los_exposure(
        self,
        candidate_col: int,
        candidate_row: int,
        enemy_deployed_units: List[Dict[str, Any]],
        game_state: Dict[str, Any],
        los_pair_cache: Dict[tuple[int, int, int, int, tuple[tuple[str, int, int, int], ...]], bool],
        snapshot_version: tuple[tuple[str, int, int, int], ...],
    ) -> int:
        """Count deployed enemy units with LoS to candidate deployment hex."""
        exposure_count = 0
        for enemy in enemy_deployed_units:
            enemy_col = int(require_key(enemy, "col"))
            enemy_row = int(require_key(enemy, "row"))
            if enemy_col < 0 or enemy_row < 0:
                continue
            can_see = self._has_line_of_sight_cached(
                from_col=enemy_col,
                from_row=enemy_row,
                to_col=candidate_col,
                to_row=candidate_row,
                game_state=game_state,
                los_pair_cache=los_pair_cache,
                snapshot_version=snapshot_version,
            )
            if can_see:
                exposure_count += 1
        return exposure_count

    def _count_potential_los_from_reference_hexes(
        self,
        candidate_col: int,
        candidate_row: int,
        enemy_reference_hexes: List[tuple[int, int]],
        game_state: Dict[str, Any],
        los_pair_cache: Dict[tuple[int, int, int, int, tuple[tuple[str, int, int, int], ...]], bool],
        snapshot_version: tuple[tuple[str, int, int, int], ...],
    ) -> int:
        """
        Count potential LoS exposure from enemy reference deployment hexes.

        Used when enemy units are not yet deployed; gives a wall/cover-aware proxy.
        """
        potential_exposure = 0
        for ref_col, ref_row in enemy_reference_hexes:
            can_see = self._has_line_of_sight_cached(
                from_col=int(ref_col),
                from_row=int(ref_row),
                to_col=int(candidate_col),
                to_row=int(candidate_row),
                game_state=game_state,
                los_pair_cache=los_pair_cache,
                snapshot_version=snapshot_version,
            )
            if can_see:
                potential_exposure += 1
        return potential_exposure

    def _build_enemy_los_reference_hexes(
        self, enemy_reference_hexes: List[tuple[int, int]]
    ) -> List[tuple[int, int]]:
        """
        Build a compact deterministic subset of enemy reference hexes for LoS potential.

        Using all deployment hexes is too expensive and redundant. We keep tactical signal
        with strategic anchors: left/right extremes, top/bottom extremes, and center.
        """
        if not enemy_reference_hexes:
            raise ValueError("enemy_reference_hexes cannot be empty")

        sorted_by_col = sorted(enemy_reference_hexes, key=lambda h: (h[0], h[1]))
        sorted_by_row = sorted(enemy_reference_hexes, key=lambda h: (h[1], h[0]))

        leftmost = sorted_by_col[0]
        rightmost = sorted_by_col[-1]
        topmost = sorted_by_row[0]
        bottommost = sorted_by_row[-1]

        center_col = (leftmost[0] + rightmost[0]) // 2
        center_row = (topmost[1] + bottommost[1]) // 2
        center_hex = min(
            enemy_reference_hexes,
            key=lambda h: (abs(h[0] - center_col) + abs(h[1] - center_row), h[0], h[1]),
        )

        anchors = [leftmost, rightmost, topmost, bottommost, center_hex]
        unique_anchors: List[tuple[int, int]] = []
        seen = set()
        for anchor in anchors:
            if anchor not in seen:
                seen.add(anchor)
                unique_anchors.append(anchor)
        return unique_anchors

    def _build_deployed_snapshot(
        self, game_state: Dict[str, Any]
    ) -> Dict[str, tuple[int, int, int]]:
        """Build snapshot of deployed units: unit_id -> (player, col, row)."""
        snapshot: Dict[str, tuple[int, int, int]] = {}
        for unit in require_key(game_state, "units"):
            col = int(require_key(unit, "col"))
            row = int(require_key(unit, "row"))
            if col < 0 or row < 0:
                continue
            unit_id = str(require_key(unit, "id"))
            player = int(require_key(unit, "player"))
            snapshot[unit_id] = (player, col, row)
        return snapshot

    def _build_deployment_scoring_cache(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
    ) -> Dict[str, Any]:
        """Build full deployment scoring cache for current state."""
        deployed_snapshot = self._build_deployed_snapshot(game_state)
        snapshot_version = self._build_deployed_snapshot_version(deployed_snapshot)
        enemy_player = 2 if int(current_deployer) == 1 else 1

        ally_col_counts: Dict[int, int] = {}
        ally_deployed_hexes: List[tuple[int, int]] = []
        enemy_deployed_units: List[Dict[str, Any]] = []
        for player, col, row in deployed_snapshot.values():
            if player == int(current_deployer):
                ally_deployed_hexes.append((col, row))
                if col in ally_col_counts:
                    ally_col_counts[col] = ally_col_counts[col] + 1
                else:
                    ally_col_counts[col] = 1
            elif player == enemy_player:
                enemy_deployed_units.append({"col": col, "row": row})

        enemy_pool_hexes = self._get_enemy_deployment_pool_hexes(game_state, current_deployer)
        enemy_los_reference_hexes = self._build_enemy_los_reference_hexes(enemy_pool_hexes)

        los_exposure_by_hex: Dict[tuple[int, int], int] = {}
        potential_los_exposure_by_hex: Dict[tuple[int, int], int] = {}
        los_pair_cache: Dict[tuple[int, int, int, int, tuple[tuple[str, int, int, int], ...]], bool] = {}
        for col, row in valid_hexes:
            los_exposure_by_hex[(col, row)] = self._count_los_exposure(
                col,
                row,
                enemy_deployed_units,
                game_state,
                los_pair_cache,
                snapshot_version,
            )
            potential_los_exposure_by_hex[(col, row)] = self._count_potential_los_from_reference_hexes(
                col,
                row,
                enemy_los_reference_hexes,
                game_state,
                los_pair_cache,
                snapshot_version,
            )

        return {
            "current_deployer": int(current_deployer),
            "deployed_snapshot": deployed_snapshot,
            "deployed_snapshot_version": snapshot_version,
            "valid_hexes": list(valid_hexes),
            "valid_hex_set": set(valid_hexes),
            "ally_col_counts": ally_col_counts,
            "ally_deployed_hexes": ally_deployed_hexes,
            "enemy_deployed_units": enemy_deployed_units,
            "los_exposure_by_hex": los_exposure_by_hex,
            "potential_los_exposure_by_hex": potential_los_exposure_by_hex,
            "los_pair_cache": los_pair_cache,
        }

    def _update_deployment_scoring_cache_incremental(
        self,
        cache: Dict[str, Any],
        game_state: Dict[str, Any],
        current_deployer: int,
        current_snapshot: Dict[str, tuple[int, int, int]],
    ) -> bool:
        """
        Update deployment scoring cache incrementally after one new deployment.

        Returns True when incremental update succeeded, False when full rebuild is required.
        """
        if int(current_deployer) != int(require_key(cache, "current_deployer")):
            return False

        previous_snapshot = require_key(cache, "deployed_snapshot")
        previous_ids = set(previous_snapshot.keys())
        current_ids = set(current_snapshot.keys())
        removed_ids = previous_ids - current_ids
        added_ids = current_ids - previous_ids
        if removed_ids:
            return False
        if len(added_ids) != 1:
            return False

        added_id = next(iter(added_ids))
        player, col, row = current_snapshot[added_id]
        added_pos = (col, row)
        current_snapshot_version = self._build_deployed_snapshot_version(current_snapshot)

        valid_hex_set = require_key(cache, "valid_hex_set")
        valid_hexes = require_key(cache, "valid_hexes")
        if added_pos in valid_hex_set:
            valid_hex_set.remove(added_pos)
            valid_hexes.remove(added_pos)
        los_exposure_by_hex = require_key(cache, "los_exposure_by_hex")
        potential_los_exposure_by_hex = require_key(cache, "potential_los_exposure_by_hex")
        if added_pos in los_exposure_by_hex:
            del los_exposure_by_hex[added_pos]
        if added_pos in potential_los_exposure_by_hex:
            del potential_los_exposure_by_hex[added_pos]

        ally_col_counts = require_key(cache, "ally_col_counts")
        ally_deployed_hexes = require_key(cache, "ally_deployed_hexes")
        enemy_deployed_units = require_key(cache, "enemy_deployed_units")
        los_pair_cache = require_key(cache, "los_pair_cache")
        cached_snapshot_version = require_key(cache, "deployed_snapshot_version")
        if cached_snapshot_version != current_snapshot_version:
            los_pair_cache.clear()
            cache["deployed_snapshot_version"] = current_snapshot_version

        if int(player) == int(current_deployer):
            ally_deployed_hexes.append((col, row))
            if col in ally_col_counts:
                ally_col_counts[col] = ally_col_counts[col] + 1
            else:
                ally_col_counts[col] = 1
        else:
            enemy_unit = {"col": col, "row": row}
            enemy_deployed_units.append(enemy_unit)
            for hex_col, hex_row in valid_hexes:
                can_see = self._has_line_of_sight_cached(
                    from_col=int(col),
                    from_row=int(row),
                    to_col=int(hex_col),
                    to_row=int(hex_row),
                    game_state=game_state,
                    los_pair_cache=los_pair_cache,
                    snapshot_version=current_snapshot_version,
                )
                if can_see:
                    key = (hex_col, hex_row)
                    previous_value = require_key(los_exposure_by_hex, key)
                    los_exposure_by_hex[key] = previous_value + 1

        cache["deployed_snapshot"] = current_snapshot
        cache["deployed_snapshot_version"] = current_snapshot_version
        return True

    def _get_or_build_deployment_scoring_cache(
        self,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
    ) -> Dict[str, Any]:
        """
        Get deployment scoring cache with incremental updates when possible.

        Full rebuild is used only when state drift is not a single deployment delta.
        """
        current_snapshot = self._build_deployed_snapshot(game_state)
        cache_key = "_deployment_scoring_cache"
        if cache_key not in game_state:
            new_cache = self._build_deployment_scoring_cache(game_state, current_deployer, valid_hexes)
            game_state[cache_key] = new_cache
            return new_cache

        cache = require_key(game_state, cache_key)
        updated = self._update_deployment_scoring_cache_incremental(
            cache=cache,
            game_state=game_state,
            current_deployer=current_deployer,
            current_snapshot=current_snapshot,
        )
        if updated:
            return cache

        new_cache = self._build_deployment_scoring_cache(game_state, current_deployer, valid_hexes)
        game_state[cache_key] = new_cache
        return new_cache

    def _select_deployment_hex_for_action(
        self,
        action_int: int,
        unit_id: Any,
        game_state: Dict[str, Any],
        current_deployer: int,
        valid_hexes: List[tuple[int, int]],
    ) -> tuple[int, int]:
        """
        Select deployment hex using tactical criteria driven by deployment action.

        Action mapping:
        - 4: aggressive front
        - 5: objective pressure
        - 6: safe/cohesion
        - 7: left flank
        - 8: right flank
        """
        if action_int not in [4, 5, 6, 7, 8]:
            raise ValueError(f"Invalid deployment action: {action_int}")

        unit = get_unit_by_id(str(unit_id), game_state)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")

        cache = self._get_or_build_deployment_scoring_cache(game_state, current_deployer, valid_hexes)
        ally_col_counts = require_key(cache, "ally_col_counts")
        ally_deployed_hexes = require_key(cache, "ally_deployed_hexes")
        los_exposure_by_hex = require_key(cache, "los_exposure_by_hex")
        potential_los_exposure_by_hex = require_key(cache, "potential_los_exposure_by_hex")
        enemy_reference_hexes = self._get_enemy_reference_hexes(game_state, current_deployer)
        objective_hexes = self._get_objective_hexes(game_state)
        candidate_cols = [col for col, _ in valid_hexes]
        candidate_rows = [row for _, row in valid_hexes]
        center_col = (min(candidate_cols) + max(candidate_cols)) // 2
        center_row = (min(candidate_rows) + max(candidate_rows)) // 2

        def nearest_distance(col: int, row: int, refs: List[tuple[int, int]]) -> int:
            if not refs:
                raise ValueError("Reference hex list cannot be empty for deployment scoring")
            return min(calculate_hex_distance(col, row, ref_col, ref_row) for ref_col, ref_row in refs)

        def score_for_hex(col: int, row: int) -> tuple:
            nearest_enemy_distance = nearest_distance(col, row, enemy_reference_hexes)
            nearest_objective_distance = nearest_distance(col, row, objective_hexes)
            if ally_deployed_hexes:
                nearest_ally_distance = nearest_distance(col, row, ally_deployed_hexes)
            else:
                nearest_ally_distance = 0
            if (col, row) not in los_exposure_by_hex:
                raise KeyError(f"Missing los_exposure cache entry for hex ({col},{row})")
            if (col, row) not in potential_los_exposure_by_hex:
                raise KeyError(f"Missing potential_los_exposure cache entry for hex ({col},{row})")
            los_exposure = los_exposure_by_hex[(col, row)]
            potential_los_exposure = potential_los_exposure_by_hex[(col, row)]
            progress = -row if int(current_deployer) == 1 else row
            center_distance = abs(col - center_col)
            if col in ally_col_counts:
                horizontal_cluster_penalty = ally_col_counts[col]
            else:
                horizontal_cluster_penalty = 0

            if action_int == 4:
                return (
                    progress,
                    -nearest_enemy_distance,
                    -nearest_objective_distance,
                    -los_exposure,
                    -potential_los_exposure,
                    -horizontal_cluster_penalty,
                    -center_distance,
                )
            if action_int == 5:
                return (
                    -nearest_objective_distance,
                    -los_exposure,
                    -potential_los_exposure,
                    progress,
                    -nearest_enemy_distance,
                    -horizontal_cluster_penalty,
                    -center_distance,
                )
            if action_int == 6:
                return (
                    -los_exposure,
                    -potential_los_exposure,
                    nearest_enemy_distance,
                    -nearest_objective_distance,
                    -nearest_ally_distance,
                    -horizontal_cluster_penalty,
                    -center_distance,
                )
            if action_int == 7:
                return (
                    -los_exposure,
                    -potential_los_exposure,
                    -col,
                    -nearest_objective_distance,
                    nearest_enemy_distance,
                    -horizontal_cluster_penalty,
                )
            return (
                -los_exposure,
                -potential_los_exposure,
                col,
                -nearest_objective_distance,
                nearest_enemy_distance,
                -horizontal_cluster_penalty,
            )

        # Neutral tie-break: prefer balanced center placement, no left/right bias.
        best_hex = max(
            valid_hexes,
            key=lambda h: (
                score_for_hex(h[0], h[1]),
                -abs(h[0] - center_col),
                -abs(h[1] - center_row),
            ),
        )
        return best_hex
    
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
