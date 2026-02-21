#!/usr/bin/env python3
"""
deployment_handlers.py - Deployment Phase Implementation (Test mode)
"""

from typing import Dict, Any, Tuple, List, Optional
from shared.data_validation import require_key
from engine.game_utils import get_unit_by_id
from engine.combat_utils import set_unit_coordinates
from engine.phase_handlers.shared_utils import update_units_cache_position


def deployment_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize deployment phase using precomputed deployment_state.
    """
    if "deployment_state" not in game_state:
        raise KeyError("deployment_state is required to start deployment phase")
    game_state["phase"] = "deployment"
    return {"phase_start": True}


def _get_deployment_pool(deployment_pools: Dict[Any, Any], player: int) -> List[Tuple[int, int]]:
    if player in deployment_pools:
        return deployment_pools[player]
    player_key = str(player)
    if player_key in deployment_pools:
        return deployment_pools[player_key]
    raise KeyError(f"deployment_pools missing player {player}")


def _get_deployable_remaining(deployment_state: Dict[str, Any], player: int) -> list:
    """Get remaining deployable units for player. Raises KeyError if player key missing."""
    deployable_units = require_key(deployment_state, "deployable_units")
    if player in deployable_units:
        return deployable_units[player]
    if str(player) in deployable_units:
        return deployable_units[str(player)]
    raise KeyError(f"deployable_units missing player {player}")


def _is_hex_occupied(game_state: Dict[str, Any], dest_col: int, dest_row: int) -> bool:
    for unit in require_key(game_state, "units"):
        if int(unit["col"]) == int(dest_col) and int(unit["row"]) == int(dest_row):
            return True
    return False


def _mark_deployed(deployment_state: Dict[str, Any], unit_id: str, current_deployer: int) -> None:
    deployable_units = require_key(deployment_state, "deployable_units")
    deployed_units = require_key(deployment_state, "deployed_units")
    if not isinstance(deployed_units, set):
        raise TypeError("deployment_state.deployed_units must be a set")
    deployed_units.add(unit_id)
    if current_deployer in deployable_units:
        deployable_units[current_deployer] = [uid for uid in deployable_units[current_deployer] if str(uid) != str(unit_id)]
    else:
        current_key = str(current_deployer)
        if current_key in deployable_units:
            deployable_units[current_key] = [uid for uid in deployable_units[current_key] if str(uid) != str(unit_id)]
        else:
            raise KeyError(f"deployable_units missing player {current_deployer}")


def _resolve_next_deployer_after_success(
    deployment_state: Dict[str, Any], current_deployer: int
) -> Optional[int]:
    """
    Resolve next deployer after a successful deployment with alternated order.

    Rules:
    - Player 1 starts (initialized elsewhere).
    - Alternate after each deployment while both players still have deployable units.
    - If only one player has deployable units left, that player continues.
    - Return None when deployment is complete.
    """
    remaining_current = _get_deployable_remaining(deployment_state, int(current_deployer))
    other_player = 2 if int(current_deployer) == 1 else 1
    remaining_other = _get_deployable_remaining(deployment_state, other_player)

    has_current = len(remaining_current) > 0
    has_other = len(remaining_other) > 0

    if has_current and has_other:
        return other_player
    if has_current:
        return int(current_deployer)
    if has_other:
        return other_player
    return None


def execute_deployment_action(game_state: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute deployment action.
    """
    current_phase = require_key(game_state, "phase")
    if current_phase != "deployment":
        return False, {"error": "invalid_phase", "phase": current_phase}

    action_type = require_key(action, "action")
    if action_type != "deploy_unit":
        return False, {"error": "invalid_deployment_action", "action": action_type}

    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = require_key(deployment_state, "current_deployer")
    unit_id = str(require_key(action, "unitId"))
    dest_col = require_key(action, "destCol")
    dest_row = require_key(action, "destRow")

    deployable_units = require_key(deployment_state, "deployable_units")
    deployable_list = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
    if deployable_list is None:
        raise KeyError(f"deployable_units missing player {current_deployer}")
    if unit_id not in [str(uid) for uid in deployable_list]:
        return False, {"error": "unit_not_deployable", "unitId": unit_id, "current_deployer": current_deployer}

    unit = get_unit_by_id(unit_id, game_state)
    if not unit:
        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
    unit_player = require_key(unit, "player")
    if int(unit_player) != int(current_deployer):
        return False, {"error": "unit_not_current_deployer", "unitId": unit_id, "current_deployer": current_deployer}

    deployment_pools = require_key(deployment_state, "deployment_pools")
    pool = _get_deployment_pool(deployment_pools, int(current_deployer))
    pool_set = {(int(col), int(row)) for col, row in pool}
    if (int(dest_col), int(dest_row)) not in pool_set:
        return False, {"error": "invalid_deploy_hex", "unitId": unit_id, "destCol": dest_col, "destRow": dest_row}

    if _is_hex_occupied(game_state, dest_col, dest_row):
        return False, {"error": "deploy_hex_occupied", "unitId": unit_id, "destCol": dest_col, "destRow": dest_row}

    set_unit_coordinates(unit, dest_col, dest_row)
    update_units_cache_position(game_state, unit_id, dest_col, dest_row)
    _mark_deployed(deployment_state, unit_id, int(current_deployer))

    next_deployer = _resolve_next_deployer_after_success(deployment_state, int(current_deployer))
    if next_deployer is None:
        deployment_state["deployment_complete"] = True
    else:
        deployment_state["current_deployer"] = next_deployer
        game_state["current_player"] = next_deployer

    result = {
        "action": "deploy_unit",
        "unitId": unit_id,
        "destCol": dest_col,
        "destRow": dest_row,
        "deployment_complete": deployment_state.get("deployment_complete", False)
    }

    if deployment_state.get("deployment_complete", False):
        game_state["current_player"] = 1
        result.update({
            "phase_complete": True,
            "next_phase": "command"
        })

    return True, result


