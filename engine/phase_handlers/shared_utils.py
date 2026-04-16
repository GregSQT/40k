#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import Dict, List, Tuple, Set, Optional, Any, Union
import inspect

from shared.data_validation import require_key
from engine.combat_utils import (
    get_unit_coordinates,
    normalize_coordinates,
    calculate_hex_distance,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    get_unit_by_id,
    set_unit_coordinates,
)

# end_activation / _handle_shooting_end_activation argument constants (AI_TURN.md)
ACTION = "ACTION"
WAIT = "WAIT"
NO = "NO"
PASS = "PASS"
ERROR = "ERROR"
MOVE = "MOVE"
SHOOTING = "SHOOTING"
CHARGE = "CHARGE"
FIGHT = "FIGHT"
FLED = "FLED"
ADVANCE = "ADVANCE"
NOT_REMOVED = "NOT_REMOVED"

ALLOWED_CHOICE_TIMING_TRIGGERS = {
    "on_deploy",
    "turn_start",
    "player_turn_start",
    "phase_start",
    "activation_start",
}
ALLOWED_CHOICE_TIMING_PHASES = {"command", "move", "shoot", "charge", "fight"}
ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE = {"owner", "opponent", "both"}


def _validate_choice_timing_object(choice_timing: Dict[str, Any], context: str) -> None:
    """Validate one choice_timing object from UNIT_RULES."""
    trigger_value = require_key(choice_timing, "trigger")
    if not isinstance(trigger_value, str) or trigger_value not in ALLOWED_CHOICE_TIMING_TRIGGERS:
        raise ValueError(
            f"{context}: invalid choice_timing.trigger '{trigger_value}'. "
            f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_TRIGGERS)}"
        )

    if "phase" in choice_timing:
        phase_value = choice_timing["phase"]
        if not isinstance(phase_value, str) or phase_value not in ALLOWED_CHOICE_TIMING_PHASES:
            raise ValueError(
                f"{context}: invalid choice_timing.phase '{phase_value}'. "
                f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_PHASES)}"
            )
    elif trigger_value in {"phase_start", "activation_start"}:
        raise KeyError(f"{context}: choice_timing.phase is required for trigger '{trigger_value}'")

    if "active_player_scope" in choice_timing:
        active_player_scope_value = choice_timing["active_player_scope"]
        if (
            not isinstance(active_player_scope_value, str)
            or active_player_scope_value not in ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE
        ):
            raise ValueError(
                f"{context}: invalid choice_timing.active_player_scope '{active_player_scope_value}'. "
                f"Allowed values: {sorted(ALLOWED_CHOICE_TIMING_ACTIVE_PLAYER_SCOPE)}"
            )
    elif trigger_value == "phase_start":
        raise KeyError(f"{context}: choice_timing.active_player_scope is required for trigger 'phase_start'")


def rebuild_choice_timing_index(game_state: Dict[str, Any]) -> None:
    """
    Rebuild choice timing index from currently deployed living units.

    Index structure:
    game_state["choice_timing_index"] = {
        "on_deploy": [entry, ...],
        "turn_start": [entry, ...],
        "player_turn_start": [entry, ...],
        "phase_start": [entry, ...],
        "activation_start": [entry, ...],
    }
    """
    units = require_key(game_state, "units")
    if not isinstance(units, list):
        raise TypeError(f"game_state['units'] must be a list, got {type(units).__name__}")

    choice_timing_index: Dict[str, List[Dict[str, Any]]] = {
        trigger: [] for trigger in ALLOWED_CHOICE_TIMING_TRIGGERS
    }
    for unit in units:
        unit_id = str(require_key(unit, "id"))
        unit_player_raw = require_key(unit, "player")
        try:
            unit_player = int(unit_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid player for unit {unit_id}: {unit_player_raw!r}") from exc

        # Only index deployed units (active deployment keeps undeployed units at -1,-1).
        unit_col, unit_row = get_unit_coordinates(unit)
        if unit_col < 0 or unit_row < 0:
            continue

        if not is_unit_alive(unit_id, game_state):
            continue

        unit_rules = require_key(unit, "UNIT_RULES")
        if not isinstance(unit_rules, list):
            raise TypeError(f"Unit {unit_id} UNIT_RULES must be list, got {type(unit_rules).__name__}")

        for rule in unit_rules:
            rule_id = require_key(rule, "ruleId")
            display_name = require_key(rule, "displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                raise ValueError(f"Unit {unit_id} rule '{rule_id}' has invalid displayName")

            choice_timing = rule.get("choice_timing")
            if choice_timing is None:
                continue
            if not isinstance(choice_timing, dict):
                raise TypeError(
                    f"Unit {unit_id} rule '{rule_id}' choice_timing must be object, "
                    f"got {type(choice_timing).__name__}"
                )

            _validate_choice_timing_object(choice_timing, f"Unit {unit_id} rule '{rule_id}'")
            trigger_value = require_key(choice_timing, "trigger")

            grants_rule_ids = rule.get("grants_rule_ids")
            if grants_rule_ids is None:
                grants_rule_ids = []
            if not isinstance(grants_rule_ids, list):
                raise TypeError(
                    f"Unit {unit_id} rule '{rule_id}' grants_rule_ids must be list, "
                    f"got {type(grants_rule_ids).__name__}"
                )
            usage_value = rule.get("usage")
            if usage_value is not None:
                if not isinstance(usage_value, str) or usage_value not in {"and", "or", "unique", "always"}:
                    raise ValueError(
                        f"Unit {unit_id} rule '{rule_id}' has invalid usage '{usage_value}'"
                    )

            entry = {
                "unit_id": unit_id,
                "unit_player": unit_player,
                "rule_id": rule_id,
                "display_name": display_name.strip(),
                "grants_rule_ids": [str(rule_ref) for rule_ref in grants_rule_ids],
                "usage": usage_value,
                "choice_timing": dict(choice_timing),
            }
            choice_timing_index[trigger_value].append(entry)

    game_state["choice_timing_index"] = choice_timing_index


# =============================================================================
# UNITS_CACHE - Single source of truth for position, HP, player of living units
# =============================================================================

def _compute_unit_occupied_hexes(
    col: int, row: int, unit: Dict[str, Any],
    game_state: Optional[Dict[str, Any]] = None,
) -> Set[Tuple[int, int]]:
    """Compute occupied_hexes for a unit based on its BASE_SHAPE and BASE_SIZE.

    Multi-hex footprints are only computed on Board ×10 (engagement_zone > 1).
    On legacy boards (engagement_zone=1), all units occupy a single cell.
    """
    ez = get_engagement_zone(game_state) if game_state is not None else 1
    if ez <= 1:
        return {(col, row)}
    base_shape = unit.get("BASE_SHAPE", "round")
    base_size = unit.get("BASE_SIZE", 1)
    orientation = unit.get("orientation", 0)
    if base_size == 1:
        return {(col, row)}
    from engine.hex_utils import compute_occupied_hexes
    return compute_occupied_hexes(col, row, base_shape, base_size, orientation)


def build_occupied_positions_set(
    game_state: Dict[str, Any],
    exclude_unit_id: Optional[str] = None,
) -> Set[Tuple[int, int]]:
    """Build set of all cells occupied by living units (full footprints).

    Uses occupied_hexes from units_cache for multi-hex units.
    For single-hex units, equivalent to {(col, row)} per unit.

    Args:
        game_state: Game state with units_cache
        exclude_unit_id: Optional unit to exclude (e.g. the moving unit)

    Returns:
        Set of (col, row) cells occupied by other units
    """
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in units_cache.items():
        if uid == exclude_unit_id:
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            occupied.update(occ)
        else:
            occupied.add((require_key(entry, "col"), require_key(entry, "row")))
    return occupied


def build_enemy_occupied_positions_set(
    game_state: Dict[str, Any],
    *,
    current_player: int,
) -> Set[Tuple[int, int]]:
    """Cells occupied by opposing players' units (full footprints)."""
    units_cache = require_key(game_state, "units_cache")
    current_player_int = int(current_player)
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in units_cache.items():
        player_raw = require_key(entry, "player")
        if int(player_raw) == current_player_int:
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            occupied.update(occ)
        else:
            occupied.add((require_key(entry, "col"), require_key(entry, "row")))
    return occupied


def compute_candidate_footprint(
    center_col: int, center_row: int,
    unit_or_stub: Dict[str, Any],
    game_state: Dict[str, Any],
) -> Set[Tuple[int, int]]:
    """Compute occupied_hexes for a unit placed at a candidate center position.

    For single-hex units or legacy boards (engagement_zone <= 1), returns {(center_col, center_row)}.
    For multi-hex units on x10 boards, computes the full round/oval/square footprint.

    Args:
        center_col, center_row: Candidate center position
        unit_or_stub: Dict with BASE_SHAPE and BASE_SIZE keys
        game_state: Game state (used to detect x10 mode via engagement_zone)

    Returns:
        Set of (col, row) cells forming the footprint
    """
    return _compute_unit_occupied_hexes(center_col, center_row, unit_or_stub, game_state)


def is_footprint_placement_valid(
    candidate_hexes: Set[Tuple[int, int]],
    game_state: Dict[str, Any],
    occupied_positions: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """Check if all cells of a candidate footprint are valid for placement.

    Validates: within board bounds, not a wall, not occupied by another unit.
    Optionally checks that no cell falls within the enemy engagement zone.

    Args:
        candidate_hexes: Set of (col, row) for the candidate footprint
        game_state: With board_cols, board_rows, wall_hexes
        occupied_positions: Pre-computed set of occupied cells
        enemy_adjacent_hexes: If provided, also blocks cells in enemy engagement zone

    Returns:
        True if ALL cells pass every check
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())
    for c, r in candidate_hexes:
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows:
            return False
        if (c, r) in wall_hexes:
            return False
        if (c, r) in occupied_positions:
            return False
        if enemy_adjacent_hexes is not None and (c, r) in enemy_adjacent_hexes:
            return False
    return True


def build_units_cache(game_state: Dict[str, Any]) -> None:
    """
    Build units_cache from game_state["units"].
    
    Creates game_state["units_cache"]: Dict[str, Dict] mapping unit_id (str) to
    {"col": int, "row": int, "HP_CUR": int, "player": int, "BASE_SHAPE": str,
     "BASE_SIZE": int|list, "occupied_hexes": Set[(col,row)]}
    for all units in game_state["units"].
    During gameplay, dead units are removed from cache (update_units_cache_hp calls remove_from_units_cache when HP <= 0).
    
    Also builds game_state["occupation_map"]: Dict[(col,row), unit_id] for cell→unit lookup.
    
    Called ONCE at reset() after units are initialized. Not called at phase start.
    
    Args:
        game_state: Game state with "units" list
        
    Returns:
        None (updates game_state["units_cache"] and game_state["occupation_map"])
    """
    if "units" not in game_state:
        raise KeyError("game_state must have 'units' field to build units_cache")
    
    units_cache: Dict[str, Dict[str, Any]] = {}
    occupation_map: Dict[Tuple[int, int], str] = {}
    
    for unit in game_state["units"]:
        hp_cur_raw = require_key(unit, "HP_CUR")
        try:
            hp_cur = max(0, int(float(hp_cur_raw)))
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit.get('id')} has invalid HP_CUR: {hp_cur_raw!r}") from None
        
        unit_id = str(require_key(unit, "id"))
        col, row = get_unit_coordinates(unit)  # Already normalizes
        player_raw = require_key(unit, "player")
        try:
            player = int(player_raw)
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit_id} has invalid player: {player_raw!r}") from None
        
        base_shape = unit.get("BASE_SHAPE", "round")
        base_size = unit.get("BASE_SIZE", 1)
        occupied = _compute_unit_occupied_hexes(col, row, unit, game_state)
        
        units_cache[unit_id] = {
            "col": col,
            "row": row,
            "HP_CUR": hp_cur,
            "player": player,
            "BASE_SHAPE": base_shape,
            "BASE_SIZE": base_size,
            "occupied_hexes": occupied,
        }
        
        for cell in occupied:
            occupation_map[cell] = unit_id
    
    game_state["units_cache"] = units_cache
    game_state["occupation_map"] = occupation_map

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    add_debug_file_log(game_state, f"[UNITS_CACHE BUILD] E{episode} T{turn} {phase} units_cache built with {len(units_cache)} units, occupation_map={len(occupation_map)} cells")


def _update_occupation_map(
    game_state: Dict[str, Any],
    unit_id: str,
    old_entry: Optional[Dict[str, Any]],
    new_occupied: Optional[Set[Tuple[int, int]]],
) -> None:
    """Incrementally update game_state["occupation_map"] when a unit moves or dies.

    Removes old cells, adds new cells. Skips if occupation_map not yet built.
    """
    occ_map = game_state.get("occupation_map")
    if occ_map is None:
        return
    if old_entry is not None:
        for cell in old_entry.get("occupied_hexes", set()):
            if occ_map.get(cell) == unit_id:
                del occ_map[cell]
    if new_occupied is not None:
        for cell in new_occupied:
            occ_map[cell] = unit_id


def update_units_cache_unit(
    game_state: Dict[str, Any],
    unit_id: str,
    col: int,
    row: int,
    hp_cur: int,
    player: int
) -> None:
    """
    Update or insert a unit entry in units_cache.
    
    If hp_cur <= 0, removes the entry (unit dead; single source of truth).
    Coordinates are normalized before storage.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: Column coordinate
        row: Row coordinate
        hp_cur: Current HP (0 for dead)
        player: Player number (1 or 2)
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before updating (call build_units_cache at reset)")
    
    # Normalize coordinates
    norm_col, norm_row = normalize_coordinates(col, row)
    effective_hp = max(0, int(hp_cur))
    
    # Update or insert (if hp_cur <= 0, remove instead)
    if effective_hp <= 0:
        remove_from_units_cache(game_state, unit_id)
        return
    
    old_entry = game_state["units_cache"].get(unit_id)
    base_shape = old_entry.get("BASE_SHAPE", "round") if old_entry else "round"
    base_size = old_entry.get("BASE_SIZE", 1) if old_entry else 1
    unit_stub = {"BASE_SHAPE": base_shape, "BASE_SIZE": base_size}
    new_occupied = _compute_unit_occupied_hexes(norm_col, norm_row, unit_stub, game_state)
    
    _update_occupation_map(game_state, unit_id, old_entry, new_occupied)
    
    game_state["units_cache"][unit_id] = {
        "col": norm_col,
        "row": norm_row,
        "HP_CUR": effective_hp,
        "player": player,
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "occupied_hexes": new_occupied,
    }


def _remove_unit_from_all_activation_pools(game_state: Dict[str, Any], unit_id_str: str) -> None:
    """
    Remove a unit from all activation pools (move, shoot, charge, fight).
    Called when unit dies so pools never contain dead units (single source of truth).
    """
    for pool_key in (
        "move_activation_pool",
        "shoot_activation_pool",
        "charge_activation_pool",
        "charging_activation_pool",
        "active_alternating_activation_pool",
        "non_active_alternating_activation_pool",
    ):
        if pool_key in game_state and game_state[pool_key] is not None:
            game_state[pool_key] = [uid for uid in game_state[pool_key] if str(uid) != unit_id_str]


def remove_from_units_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Remove a unit from units_cache (e.g. when unit dies: HP_CUR -> 0).
    
    Dead = absent from cache (single source of truth). Call from update_units_cache_hp when HP <= 0.
    Also removes the unit from all activation pools so pools never contain dead units.
    No-op if unit_id is not in cache.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str) to remove
        
    Returns:
        None (updates game_state["units_cache"] and activation pools)
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before removing (call build_units_cache at reset)")
    
    entry = game_state["units_cache"].get(unit_id)
    if entry is not None:
        removed_col = require_key(entry, "col")
        removed_row = require_key(entry, "row")
        removed_player = require_key(entry, "player")
        removed_col_int, removed_row_int = normalize_coordinates(removed_col, removed_row)
        removed_player_int = int(removed_player)

        _update_occupation_map(game_state, unit_id, entry, None)

        removed_occupied = entry.get("occupied_hexes")
        update_enemy_adjacent_caches_after_unit_removed(
            game_state,
            removed_unit_player=removed_player_int,
            old_col=removed_col_int,
            old_row=removed_row_int,
            old_occupied=removed_occupied,
        )

        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE REMOVE] E{episode} T{turn} {phase} unit_id={unit_id} "
            f"pos=({entry.get('col')},{entry.get('row')}) HP_CUR={entry.get('HP_CUR')} player={entry.get('player')}"
        )
    game_state["units_cache"].pop(unit_id, None)
    _remove_unit_from_all_activation_pools(game_state, str(unit_id))


def get_unit_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get unit entry from units_cache.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        Dict with {"col", "row", "HP_CUR", "player"} if unit is in cache, None otherwise.
        Dead units are removed from cache (absent).
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id)


def is_unit_alive(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """
    Check if a unit is alive (present in units_cache).
    
    units_cache contains ONLY living units; dead units are removed at end of action.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        True if unit is in cache, False otherwise
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id) is not None


def _get_unit_position_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Internal: get unit position from units_cache by unit_id.
    Use get_unit_position() for the public API.
    """
    entry = get_unit_from_cache(unit_id, game_state)
    if entry is None:
        return None
    return (entry["col"], entry["row"])


def get_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """
    Get current position of a unit from units_cache (single source of truth).
    Use this for any game logic that needs unit position when game_state is available.

    Args:
        unit_or_id: Unit ID (str or int) or unit dict (must have "id").
        game_state: Game state with "units_cache".

    Returns:
        (col, row) if unit is in cache, None if unit not in cache (e.g. dead/removed).

    Raises:
        ValueError: If unit_or_id is a dict without "id" (e.g. units_cache entry passed by mistake).
    """
    if isinstance(unit_or_id, dict):
        if "id" not in unit_or_id:
            raise ValueError(
                "get_unit_position received a dict without 'id' (possibly a units_cache entry). "
                "Pass a unit dict with 'id' or a unit ID (str/int)."
            )
        unit_id = str(require_key(unit_or_id, "id"))
    else:
        unit_id = str(unit_or_id)
    return _get_unit_position_from_cache(unit_id, game_state)


def require_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Get current position of a unit from units_cache; raises if unit not in cache.
    Use when the unit is required to be present (e.g. shooter, active unit).

    Returns:
        (col, row)

    Raises:
        ValueError: If unit not in units_cache (dead/absent).
    """
    pos = get_unit_position(unit_or_id, game_state)
    if pos is None:
        uid = str(unit_or_id.get("id", unit_or_id)) if isinstance(unit_or_id, dict) else str(unit_or_id)
        raise ValueError(f"Unit {uid} not in units_cache (dead or absent); cannot read position")
    return pos


def update_units_cache_position(game_state: Dict[str, Any], unit_id: str, col: int, row: int) -> None:
    """
    Update only the position of a unit in units_cache.
    
    Convenience function for use after set_unit_coordinates.
    Retrieves HP_CUR and player from existing entry.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: New column coordinate
        row: New row coordinate
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    entry = game_state["units_cache"].get(unit_id)
    if entry is None:
        return
    
    old_col = entry.get("col")
    old_row = entry.get("row")

    norm_col, norm_row = normalize_coordinates(col, row)
    
    unit_stub = {"BASE_SHAPE": entry.get("BASE_SHAPE", "round"), "BASE_SIZE": entry.get("BASE_SIZE", 1)}
    new_occupied = _compute_unit_occupied_hexes(norm_col, norm_row, unit_stub, game_state)
    _update_occupation_map(game_state, unit_id, entry, new_occupied)
    
    entry["col"] = norm_col
    entry["row"] = norm_row
    entry["occupied_hexes"] = new_occupied

    if game_state.get("debug_mode", False):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        caller = inspect.stack()[1].function
        from engine.game_utils import add_debug_file_log
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE POSITION_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id} "
            f"old=({old_col},{old_row}) new=({norm_col},{norm_row}) caller={caller}"
        )


def get_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[int]:
    """
    Get current HP of a unit from units_cache (Phase 2: single source of truth for HP_CUR).
    
    units_cache contains ONLY living units; dead units are removed. Returns None if unit not in cache.
    
    Returns:
        HP value if unit is in cache, None if unit not in cache (dead or absent).
    """
    entry = get_unit_from_cache(str(unit_id), game_state)
    if entry is None:
        return None
    return require_key(entry, "HP_CUR")


def require_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> int:
    """
    Return current HP for a unit that must be alive (in units_cache).
    Raises ValueError if unit is dead or absent.
    """
    hp = get_hp_from_cache(str(unit_id), game_state)
    if hp is None:
        raise ValueError(f"Unit {unit_id} not in units_cache (dead or absent); cannot read HP_CUR")
    return hp


def update_units_cache_hp(game_state: Dict[str, Any], unit_id: str, new_hp_cur: int) -> None:
    """
    Single write path for HP_CUR during gameplay: updates units_cache only (Phase 2).
    
    Use this as the ONLY write path for HP_CUR during gameplay (shooting, fight).
    At reset, HP_CUR is initialised from definitions; build_units_cache reads from units.
    
    units_cache contains ONLY living units. If new_hp_cur <= 0, unit is removed from cache
    immediately (end of action).
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        new_hp_cur: New HP value (will be clamped to >= 0)
        
    Returns:
        None (updates game_state["units_cache"] only)
    """
    require_key(game_state, "units_cache")
    
    effective_hp = max(0, int(new_hp_cur))
    unit_id_str = str(unit_id)
    
    entry = game_state["units_cache"].get(unit_id_str)
    if entry is None:
        return
    if effective_hp <= 0:
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE HP_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id_str} "
            f"old_hp={entry.get('HP_CUR')} new_hp={effective_hp} -> REMOVE"
        )
        remove_from_units_cache(game_state, unit_id_str)
    else:
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        add_debug_file_log(
            game_state,
            f"[UNITS_CACHE HP_UPDATE] E{episode} T{turn} {phase} unit_id={unit_id_str} "
            f"old_hp={entry.get('HP_CUR')} new_hp={effective_hp}"
        )
        entry["HP_CUR"] = effective_hp


def check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    units_cache = require_key(game_state, "units_cache")
    unit_by_id = {str(u["id"]): u for u in game_state["units"]}
    for unit_id, entry in units_cache.items():
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if entry["player"] == current_player:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            from engine.utils.weapon_helpers import get_selected_melee_weapon
            has_melee = False
            if unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                melee_weapon = get_selected_melee_weapon(unit)
                if melee_weapon and expected_dice_value(require_key(melee_weapon, "DMG"), "melee_charge_dmg") > 0:
                    has_melee = True
            if has_melee:  # Has melee capability
                unit_pos = get_unit_position(unit, game_state)
                target_pos = get_unit_position(target, game_state)
                if unit_pos is None or target_pos is None:
                    continue
                # Estimate charge range (unit move + average 2d6)
                distance = calculate_hex_distance(*unit_pos, *target_pos)
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                config = require_key(game_state, "config")
                game_rules = require_key(config, "game_rules")
                avg_charge_roll = require_key(game_rules, "avg_charge_roll")
                max_charge = unit["MOVE"] + avg_charge_roll
                if distance <= max_charge:
                    return True
    
    return False


def calculate_target_priority_score(unit: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_DMG/CC_DMG
    """
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max DMG from all weapons
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Calculate max threat from target's weapons
    target_rng_weapon = get_selected_ranged_weapon(target)
    target_cc_weapon = get_selected_melee_weapon(target)
    target_rng_dmg = expected_dice_value(require_key(target_rng_weapon, "DMG"), "target_rng_dmg") if target_rng_weapon else 0
    target_cc_dmg = expected_dice_value(require_key(target_cc_weapon, "DMG"), "target_cc_dmg") if target_cc_weapon else 0
    # Also check all weapons for max threat
    if target.get("RNG_WEAPONS"):
        target_rng_dmg = max(
            target_rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_rng_dmg_pool") for w in target["RNG_WEAPONS"])
        )
    if target.get("CC_WEAPONS"):
        target_cc_dmg = max(
            target_cc_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "target_cc_dmg_pool") for w in target["CC_WEAPONS"])
        )
    
    threat_level = max(target_rng_dmg, target_cc_dmg)
    
    # Phase 2: HP from cache only
    target_hp = require_hp_from_cache(str(target["id"]), game_state)
    
    # Calculate if unit can kill target in 1 phase (use selected weapon or first weapon)
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    if not unit_rng_weapon and unit.get("RNG_WEAPONS"):
        unit_rng_weapon = unit["RNG_WEAPONS"][0]
    unit_rng_dmg = expected_dice_value(require_key(unit_rng_weapon, "DMG"), "unit_rng_dmg") if unit_rng_weapon else 0
    can_kill_1_phase = target_hp <= unit_rng_dmg
    
    # Priority 1: High threat that melee can charge but won't kill (score: 1000)
    if threat_level >= 3:  # High threat threshold
        melee_can_charge = check_if_melee_can_charge(target, game_state)
        if melee_can_charge and target_hp > 2:  # Won't die to melee in 1 phase
            return 1000 + threat_level
    
    # Priority 2: High threat that can be killed in 1 shooting phase (score: 800) 
    if can_kill_1_phase and threat_level >= 3:
        return 800 + threat_level
    
    # Priority 3: High threat, lowest HP that can be killed (score: 600)
    if can_kill_1_phase and threat_level >= 2:
        return 600 + threat_level + (10 - target_hp)  # Prefer lower HP
    
    # Default: threat level only
    return threat_level


def enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich unit data for reward mapper compatibility (matches engine format).
    Unit must be alive (in units_cache). For dead targets use a stub with cur_hp=0 from caller.
    """
    if not unit:
        return {}
    
    # Direct field access with validation
    if "agent_mapping" not in game_state:
        agent_mapping = {}
    else:
        agent_mapping = game_state["agent_mapping"]
    
    unit_id_key = str(require_key(unit, "id"))
    if unit_id_key in agent_mapping:
        controlled_agent = agent_mapping[unit_id_key]
    elif "unitType" in unit:
        controlled_agent = unit["unitType"]
    elif "unit_type" in unit:
        controlled_agent = unit["unit_type"]
    else:
        controlled_agent = "default"
    
    enriched = unit.copy()
    
    # Phase 2: HP from cache only; unit must be alive (in cache)
    cur_hp = require_hp_from_cache(unit_id_key, game_state)
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_DMG/RNG_DMG
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Get max DMG from weapons
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    unit_cc_weapon = get_selected_melee_weapon(unit)
    rng_dmg = expected_dice_value(require_key(unit_rng_weapon, "DMG"), "enrich_rng_dmg") if unit_rng_weapon else 0
    cc_dmg = expected_dice_value(require_key(unit_cc_weapon, "DMG"), "enrich_cc_dmg") if unit_cc_weapon else 0
    # Also check all weapons for max DMG
    if unit.get("RNG_WEAPONS"):
        rng_dmg = max(
            rng_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "enrich_rng_dmg_pool") for w in unit["RNG_WEAPONS"])
        )
    if unit.get("CC_WEAPONS"):
        cc_dmg = max(
            cc_dmg,
            max(expected_dice_value(require_key(w, "DMG"), "enrich_cc_dmg_pool") for w in unit["CC_WEAPONS"])
        )
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": cc_dmg,
        "rng_dmg": rng_dmg,
        "CUR_HP": cur_hp
    })
    
    return enriched


def get_engagement_zone(game_state: Dict[str, Any]) -> int:
    """Read engagement_zone from game_rules config.

    Returns 1 for legacy boards (adjacency), 10 for Board ×10 (§9.0).
    """
    config = game_state.get("config") or {}
    game_rules = config.get("game_rules") or {}
    return int(game_rules.get("engagement_zone", 1))


def build_enemy_adjacent_hexes(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """Pre-compute all hexes within engagement_zone of enemy units.

    Returns a set of (col, row) that are in the engagement zone of at least one enemy.
    For legacy boards (engagement_zone=1): equivalent to adjacent hexes.
    For Board ×10 (engagement_zone=10): dilated multi-hex zone (§9.0).

    Calculates once per phase and stores in game_state cache.
    Call this function at phase start, then use game_state[f"enemy_adjacent_hexes_player_{player}"] directly.

    Uses units_cache as source of truth for living enemy positions and occupied_hexes.

    Args:
        game_state: Game state with units_cache
        player: The player checking adjacency (enemies are units with different player)

    Returns:
        Set of hex coordinates in the engagement zone of any living enemy unit
    """
    enemy_adjacent_counts, enemy_adjacent_hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(
        game_state, int(player)
    )

    cache_key = f"enemy_adjacent_hexes_player_{player}"
    counts_key = f"enemy_adjacent_counts_player_{player}"
    game_state[cache_key] = enemy_adjacent_hexes
    game_state[counts_key] = enemy_adjacent_counts
    
    return enemy_adjacent_hexes


def _compute_enemy_adjacent_cache_for_player_from_units_cache(
    game_state: Dict[str, Any], player: int
) -> Tuple[Dict[Tuple[int, int], int], Set[Tuple[int, int]]]:
    """Compute per-player engagement-zone counters and set from current units_cache.

    Uses engagement_zone from game_rules (1 for legacy, 10 for ×10).
    For each enemy unit, dilates its occupied_hexes by engagement_zone distance.
    """
    units_cache = require_key(game_state, "units_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    engagement_zone = get_engagement_zone(game_state)
    player_int = int(player)

    all_enemy_occupied: Set[Tuple[int, int]] = set()
    per_unit_occupied: list = []

    for entry in units_cache.values():
        hp_cur = require_key(entry, "HP_CUR")
        if hp_cur <= 0:
            continue
        entry_player_raw = require_key(entry, "player")
        try:
            entry_player = int(entry_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid player value in units_cache entry: {entry_player_raw!r}") from exc
        if entry_player == player_int:
            continue

        occ = entry.get("occupied_hexes")
        if occ:
            all_enemy_occupied.update(occ)
            per_unit_occupied.append(occ)
        else:
            enemy_col = require_key(entry, "col")
            enemy_row = require_key(entry, "row")
            cell = (enemy_col, enemy_row)
            all_enemy_occupied.add(cell)
            per_unit_occupied.append({cell})

    import time as _time
    _t0 = _time.perf_counter()
    from engine.hex_utils import dilate_hex_set
    zone_hexes = dilate_hex_set(all_enemy_occupied, engagement_zone, board_cols, board_rows)
    _t1 = _time.perf_counter()
    print(f"[PERF-EZ] player={player_int} ez={engagement_zone} src={len(all_enemy_occupied)} zone={len(zone_hexes)} dilate={(_t1-_t0)*1000:.0f}ms", flush=True)

    counts: Dict[Tuple[int, int], int] = {h: 1 for h in zone_hexes}

    return counts, zone_hexes


def _compute_enemy_adjacent_hexes_from_units_cache(
    game_state: Dict[str, Any], player: int
) -> Set[Tuple[int, int]]:
    """Compute engagement-zone hexes directly from current units_cache snapshot."""
    _, zone_hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(
        game_state, player
    )
    return zone_hexes


def _get_players_present_from_units_cache(game_state: Dict[str, Any]) -> Set[int]:
    """Return all player ids currently present in units_cache."""
    units_cache = require_key(game_state, "units_cache")
    players_present: Set[int] = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        try:
            player_int = int(player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache: {player_raw!r}"
            ) from exc
        players_present.add(player_int)
    return players_present


def _bounded_neighbors(
    col: int, row: int, board_cols: int, board_rows: int
) -> List[Tuple[int, int]]:
    """Get in-bounds hex neighbors."""
    neighbors: List[Tuple[int, int]] = []
    for n_col, n_row in get_hex_neighbors(col, row):
        if n_col < 0 or n_row < 0 or n_col >= board_cols or n_row >= board_rows:
            continue
        neighbors.append((n_col, n_row))
    return neighbors


def _footprint_external_neighbors(
    occupied_hexes: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
) -> List[Tuple[int, int]]:
    """Return all in-bounds hexes adjacent to a footprint but not part of it."""
    neighbor_set: Set[Tuple[int, int]] = set()
    for hx_col, hx_row in occupied_hexes:
        for n_col, n_row in get_hex_neighbors(hx_col, hx_row):
            if n_col < 0 or n_row < 0 or n_col >= board_cols or n_row >= board_rows:
                continue
            if (n_col, n_row) not in occupied_hexes:
                neighbor_set.add((n_col, n_row))
    return list(neighbor_set)


def _build_enemy_adjacent_structures_from_units_cache(
    game_state: Dict[str, Any],
    players_present: Set[int],
) -> Tuple[Dict[int, Dict[Tuple[int, int], int]], Dict[int, Set[Tuple[int, int]]]]:
    """
    Build per-player enemy-adjacent counters and sets from current units_cache snapshot.
    Uses dilate_hex_set with engagement_zone for consistency with build_enemy_adjacent_hexes.
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    units_cache = require_key(game_state, "units_cache")
    engagement_zone = get_engagement_zone(game_state)
    from engine.hex_utils import dilate_hex_set

    counters_by_player: Dict[int, Dict[Tuple[int, int], int]] = {
        player_int: {} for player_int in players_present
    }
    sets_by_player: Dict[int, Set[Tuple[int, int]]] = {
        player_int: set() for player_int in players_present
    }

    import time as _time, sys as _sys
    _t0 = _time.perf_counter()
    _dilate_count = 0
    for cache_entry in units_cache.values():
        hp_cur = require_key(cache_entry, "HP_CUR")
        if hp_cur <= 0:
            continue
        unit_player_raw = require_key(cache_entry, "player")
        try:
            unit_player_int = int(unit_player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache entry: {unit_player_raw!r}"
            ) from exc
        occupied = cache_entry.get("occupied_hexes")
        if not occupied or len(occupied) == 0:
            unit_col = require_key(cache_entry, "col")
            unit_row = require_key(cache_entry, "row")
            occupied = {(unit_col, unit_row)}
        unit_zone = dilate_hex_set(occupied, engagement_zone, board_cols, board_rows)
        _dilate_count += 1
        for perspective_player in players_present:
            if perspective_player == unit_player_int:
                continue
            player_counters = counters_by_player[perspective_player]
            player_set = sets_by_player[perspective_player]
            for h in unit_zone:
                if h in player_counters:
                    player_counters[h] = player_counters[h] + 1
                else:
                    player_counters[h] = 1
                player_set.add(h)

    _t1 = _time.perf_counter()
    print(f"[PERF-BUILD-ADJ] ez={engagement_zone} units={_dilate_count} time={(_t1-_t0)*1000:.0f}ms", flush=True)
    return counters_by_player, sets_by_player


def _apply_enemy_adjacent_delta_for_moved_unit(
    counters_by_player: Dict[int, Dict[Tuple[int, int], int]],
    sets_by_player: Dict[int, Set[Tuple[int, int]]],
    players_present: Set[int],
    moved_unit_player: int,
    old_occupied: Set[Tuple[int, int]],
    new_occupied: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    engagement_zone: int = 1,
) -> None:
    """
    Apply incremental enemy-adjacent cache update after one unit position change.
    Supports multi-hex footprints via old_occupied / new_occupied sets.
    Uses dilate_hex_set with engagement_zone to match the full-recompute path.
    """
    from engine.hex_utils import dilate_hex_set
    old_zone = dilate_hex_set(old_occupied, engagement_zone, board_cols, board_rows)
    new_zone = dilate_hex_set(new_occupied, engagement_zone, board_cols, board_rows)

    for perspective_player in players_present:
        if perspective_player == moved_unit_player:
            continue

        player_counters = require_key(counters_by_player, perspective_player)
        player_set = require_key(sets_by_player, perspective_player)

        for h in old_zone:
            if h not in player_counters:
                raise KeyError(
                    f"Delta update missing old zone hex {h} for player {perspective_player}"
                )
            current_count = player_counters[h]
            if current_count <= 0:
                raise ValueError(
                    f"Invalid non-positive adjacency count for {h} "
                    f"(player={perspective_player}, count={current_count})"
                )
            if current_count == 1:
                del player_counters[h]
                player_set.discard(h)
            else:
                player_counters[h] = current_count - 1

        for h in new_zone:
            if h in player_counters:
                player_counters[h] = player_counters[h] + 1
            else:
                player_counters[h] = 1
            player_set.add(h)


def _unit_has_rule_effect(unit: Dict[str, Any], rule_id: str) -> bool:
    """
    Check if unit has rule_id directly or through grants_rule_ids.
    """
    unit_rules = require_key(unit, "UNIT_RULES")
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(rule_id)
    for rule in unit_rules:
        resolved_effect_ids = _resolve_unit_rule_entry_effect_rule_ids(rule)
        if target_effect_rule_id in resolved_effect_ids:
            return True
    return False


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """
    Return source UNIT_RULES.displayName that grants/owns the effect; None if absent.
    """
    source_rule_id = get_source_unit_rule_id_for_effect(unit, effect_rule_id)
    if source_rule_id is None:
        return None

    unit_rules = require_key(unit, "UNIT_RULES")
    registry = _get_unit_rules_registry()
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(effect_rule_id)
    for rule in unit_rules:
        direct_rule_id = require_key(rule, "ruleId")
        if direct_rule_id != source_rule_id:
            continue
        usage_value = rule.get("usage")
        if usage_value is not None:
            if not isinstance(usage_value, str):
                raise ValueError(f"Unit rule '{source_rule_id}' has invalid usage: {usage_value!r}")
            normalized_usage = usage_value.strip().lower()
        else:
            normalized_usage = None
        if normalized_usage in {"or", "unique"}:
            selected_granted_rule_id = rule.get("_selected_granted_rule_id")
            if selected_granted_rule_id is None:
                raise ValueError(
                    f"Unit {require_key(unit, 'id')} rule '{source_rule_id}' requires "
                    "_selected_granted_rule_id for usage 'or/unique'"
                )
            if not isinstance(selected_granted_rule_id, str) or not selected_granted_rule_id.strip():
                raise ValueError(
                    f"Unit {require_key(unit, 'id')} rule '{source_rule_id}' has invalid "
                    f"_selected_granted_rule_id: {selected_granted_rule_id!r}"
                )
            selected_rule_id = selected_granted_rule_id.strip()
            if selected_rule_id not in registry:
                raise KeyError(
                    f"Unknown selected granted rule id '{selected_rule_id}' in config/unit_rules.json"
                )
            selected_rule_config = registry[selected_rule_id]
            selected_rule_name = selected_rule_config.get("name")
            if not isinstance(selected_rule_name, str) or not selected_rule_name.strip():
                raise ValueError(
                    f"Rule '{selected_rule_id}' must define non-empty 'name' for selected rule display"
                )
            selected_technical_rule_id = _resolve_effect_rule_id_to_technical(selected_rule_id)
            if selected_technical_rule_id != target_effect_rule_id:
                raise ValueError(
                    f"Selected rule '{selected_rule_id}' resolves to '{selected_technical_rule_id}', "
                    f"but requested effect is '{target_effect_rule_id}'"
                )
            return selected_rule_name.strip().upper()
        display_name = require_key(rule, "displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            unit_id = require_key(unit, "id")
            unit_name = unit.get("DISPLAY_NAME") or unit.get("unitType") or "UNKNOWN"
            raise ValueError(
                f"Unit {unit_id} ({unit_name}) has rule '{source_rule_id}' missing non-empty displayName"
            )
        return display_name.strip().upper()
    raise KeyError(f"Rule '{source_rule_id}' missing from UNIT_RULES for unit {require_key(unit, 'id')}")


_unit_rules_registry_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _get_unit_rules_registry() -> Dict[str, Dict[str, Any]]:
    """Load and cache rule registry from config/unit_rules.json."""
    global _unit_rules_registry_cache
    if _unit_rules_registry_cache is not None:
        return _unit_rules_registry_cache
    from config_loader import get_config_loader
    registry = get_config_loader().load_unit_rules_config()
    _unit_rules_registry_cache = registry
    return registry


def _resolve_effect_rule_id_to_technical(rule_id: str, visited: Optional[Set[str]] = None) -> str:
    """Resolve a rule id to technical effect id by following optional alias chain."""
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError(f"rule_id must be a non-empty string, got {rule_id!r}")
    normalized_rule_id = rule_id.strip()
    registry = _get_unit_rules_registry()
    if normalized_rule_id not in registry:
        raise KeyError(f"Unknown rule id '{normalized_rule_id}' in config/unit_rules.json")

    if visited is None:
        visited = set()
    if normalized_rule_id in visited:
        raise ValueError(f"Rule alias cycle detected while resolving '{normalized_rule_id}'")
    visited.add(normalized_rule_id)

    rule_config = registry[normalized_rule_id]
    alias_value = rule_config.get("alias")
    if alias_value is None:
        return normalized_rule_id
    if not isinstance(alias_value, str) or not alias_value.strip():
        raise ValueError(
            f"Rule '{normalized_rule_id}' has invalid alias in config/unit_rules.json: {alias_value!r}"
        )
    return _resolve_effect_rule_id_to_technical(alias_value.strip(), visited)


def _resolve_unit_rule_entry_effect_rule_ids(rule_entry: Dict[str, Any]) -> Set[str]:
    """Resolve direct and granted rule ids from one UNIT_RULES entry to technical effect ids."""
    direct_rule_id = require_key(rule_entry, "ruleId")
    if not isinstance(direct_rule_id, str) or not direct_rule_id.strip():
        raise ValueError(f"UNIT_RULES.ruleId must be non-empty string, got {direct_rule_id!r}")

    resolved_rule_ids: Set[str] = {_resolve_effect_rule_id_to_technical(direct_rule_id)}
    usage_value = rule_entry.get("usage")
    if usage_value is not None:
        if not isinstance(usage_value, str):
            raise ValueError(f"UNIT_RULES usage must be string, got {usage_value!r}")
        usage_value = usage_value.strip().lower()
    if usage_value not in {None, "and", "or", "unique", "always"}:
        raise ValueError(f"Invalid UNIT_RULES usage value: {usage_value!r}")
    granted_rule_ids = rule_entry.get("grants_rule_ids")
    if granted_rule_ids is None:
        return resolved_rule_ids
    if not isinstance(granted_rule_ids, list):
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has invalid grants_rule_ids type: "
            f"{type(granted_rule_ids).__name__}"
        )
    # always/and: all granted rules are active
    if usage_value in {None, "and", "always"}:
        for granted_rule_id in granted_rule_ids:
            if not isinstance(granted_rule_id, str) or not granted_rule_id.strip():
                raise ValueError(
                    f"UNIT_RULES entry for '{direct_rule_id}' has invalid granted rule id: {granted_rule_id!r}"
                )
            resolved_rule_ids.add(_resolve_effect_rule_id_to_technical(granted_rule_id))
        return resolved_rule_ids

    # or/unique: only selected grant is active
    selected_granted_rule_id = rule_entry.get("_selected_granted_rule_id")
    if selected_granted_rule_id is None:
        return resolved_rule_ids
    if not isinstance(selected_granted_rule_id, str) or not selected_granted_rule_id.strip():
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has invalid _selected_granted_rule_id: "
            f"{selected_granted_rule_id!r}"
        )
    if selected_granted_rule_id not in granted_rule_ids:
        raise ValueError(
            f"UNIT_RULES entry for '{direct_rule_id}' has selected rule "
            f"'{selected_granted_rule_id}' not present in grants_rule_ids"
        )
    selected_technical_rule_id = _resolve_effect_rule_id_to_technical(selected_granted_rule_id)
    resolved_rule_ids.add(selected_technical_rule_id)
    return resolved_rule_ids

def get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId for a technical effect rule."""
    unit_rules = require_key(unit, "UNIT_RULES")
    target_effect_rule_id = _resolve_effect_rule_id_to_technical(effect_rule_id)
    for rule in unit_rules:
        source_rule_id = require_key(rule, "ruleId")
        resolved_effect_ids = _resolve_unit_rule_entry_effect_rule_ids(rule)
        if target_effect_rule_id in resolved_effect_ids:
            return source_rule_id
    return None


def unit_has_rule_effect(unit: Dict[str, Any], rule_id: str) -> bool:
    """Public helper for effect check with display->technical rule mapping."""
    return _unit_has_rule_effect(unit, rule_id)


def get_source_unit_rule_display_name_for_effect(
    unit: Dict[str, Any], effect_rule_id: str
) -> Optional[str]:
    """Public helper returning source display name for a technical effect rule."""
    return _get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)
    return None


def _build_reactive_move_destinations_pool(
    game_state: Dict[str, Any],
    reactive_unit: Dict[str, Any],
    move_range: int,
    enemy_adjacent_hexes_override: Optional[Set[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """
    Build legal reactive move destinations using BFS with movement restrictions.
    """
    if move_range <= 0:
        raise ValueError(f"reactive_move move_range must be > 0, got {move_range}")
    start_col, start_row = require_unit_position(reactive_unit, game_state)
    start_pos = (start_col, start_row)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = require_key(game_state, "wall_hexes")

    reactive_player_raw = require_key(reactive_unit, "player")
    try:
        reactive_player = int(reactive_player_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Reactive unit {require_key(reactive_unit, 'id')} has invalid player: {reactive_player_raw!r}"
        ) from exc

    if enemy_adjacent_hexes_override is not None:
        enemy_adjacent_hexes = enemy_adjacent_hexes_override
    else:
        # Use phase cache by default.
        cache_key = f"enemy_adjacent_hexes_player_{reactive_player}"
        if cache_key not in game_state:
            raise KeyError(
                f"Missing required adjacency cache '{cache_key}'. "
                "Cache must be initialized at phase start."
            )
        enemy_adjacent_hexes = require_key(game_state, cache_key)
        if not isinstance(enemy_adjacent_hexes, set):
            raise ValueError(
                f"Invalid adjacency cache type for '{cache_key}': "
                f"{type(enemy_adjacent_hexes).__name__}"
            )

    # Build occupied positions from units_cache (all living units except the moving one).
    units_cache = require_key(game_state, "units_cache")
    reactive_unit_id = str(require_key(reactive_unit, "id"))
    occupied_positions: Set[Tuple[int, int]] = set()
    for unit_id, entry in units_cache.items():
        if str(unit_id) == reactive_unit_id:
            continue
        entry_col = require_key(entry, "col")
        entry_row = require_key(entry, "row")
        occupied_positions.add((entry_col, entry_row))

    wall_set: Set[Tuple[int, int]] = set()
    for wall_hex in wall_hexes:
        if isinstance(wall_hex, (tuple, list)) and len(wall_hex) == 2:
            wall_col, wall_row = normalize_coordinates(wall_hex[0], wall_hex[1])
            wall_set.add((wall_col, wall_row))
        else:
            raise ValueError(f"Invalid wall hex entry: {wall_hex!r}")

    visited: Set[Tuple[int, int]] = {start_pos}
    queue: List[Tuple[Tuple[int, int], int]] = [(start_pos, 0)]
    valid_destinations: List[Tuple[int, int]] = []

    while queue:
        (cur_col, cur_row), cur_dist = queue.pop(0)
        if cur_dist >= move_range:
            continue

        for neighbor_col, neighbor_row in get_hex_neighbors(cur_col, cur_row):
            neighbor = (neighbor_col, neighbor_row)
            if neighbor in visited:
                continue
            if neighbor_col < 0 or neighbor_row < 0 or neighbor_col >= board_cols or neighbor_row >= board_rows:
                continue
            if neighbor in wall_set:
                continue
            if neighbor in occupied_positions:
                continue
            if neighbor in enemy_adjacent_hexes:
                continue

            visited.add(neighbor)
            valid_destinations.append(neighbor)
            queue.append((neighbor, cur_dist + 1))

    # Deterministic destination order.
    valid_destinations.sort(key=lambda pos: (int(pos[0]), int(pos[1])))
    return valid_destinations


def _select_reactive_unit_order(
    game_state: Dict[str, Any], eligible_units: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Order eligible reactive units according to configured reactive mode.
    """
    mode_raw = require_key(game_state, "reactive_mode")
    if mode_raw not in {"micro", "macro"}:
        raise ValueError(f"Unsupported reactive_mode: {mode_raw!r}")

    if mode_raw == "micro":
        return sorted(eligible_units, key=lambda unit: str(require_key(unit, "id")))

    macro_order_raw = game_state.get("reactive_macro_order_current_window")
    if macro_order_raw is None:
        raise ValueError("ValueError[reactive_move.invalid_macro_order]: missing reactive_macro_order_current_window")
    if not isinstance(macro_order_raw, list):
        raise ValueError(
            "ValueError[reactive_move.invalid_macro_order]: "
            f"reactive_macro_order_current_window must be list, got {type(macro_order_raw).__name__}"
        )
    macro_order = [str(unit_id) for unit_id in macro_order_raw]
    if len(macro_order) == 0:
        raise ValueError("ValueError[reactive_move.invalid_macro_order]: macro order cannot be empty")

    eligible_by_id = {str(require_key(unit, "id")): unit for unit in eligible_units}
    ordered: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for unit_id in macro_order:
        if unit_id in eligible_by_id and unit_id not in seen:
            ordered.append(eligible_by_id[unit_id])
            seen.add(unit_id)
        elif unit_id not in eligible_by_id:
            raise ValueError(
                "ValueError[reactive_move.invalid_macro_order]: "
                f"unit_id={unit_id} not eligible in current reaction window"
            )

    return ordered


def _select_reactive_destination(
    valid_destinations: List[Tuple[int, int]], moved_to_col: int, moved_to_row: int
) -> Tuple[int, int]:
    """
    Deterministic destination policy: closest to moved enemy unit, tie-break by coordinates.
    """
    if not valid_destinations:
        raise ValueError("Cannot select reactive destination from empty pool")
    return min(
        valid_destinations,
        key=lambda pos: (calculate_hex_distance(pos[0], pos[1], moved_to_col, moved_to_row), pos[0], pos[1]),
    )


def _resolve_reactive_decision(
    game_state: Dict[str, Any],
    reactive_unit_id: str,
    valid_destinations: List[Tuple[int, int]],
    moved_to_col: int,
    moved_to_row: int,
) -> Tuple[str, Optional[Tuple[int, int]]]:
    """
    Resolve reactive decision for one unit.

    Returns:
        ("decline", None) or ("move", (col, row))
    """
    decision_mode = require_key(game_state, "reactive_decision_mode")
    if decision_mode not in {"auto", "state"}:
        raise ValueError(f"Unsupported reactive_decision_mode: {decision_mode!r}")

    if decision_mode == "auto":
        return "move", _select_reactive_destination(valid_destinations, moved_to_col, moved_to_row)

    payload = require_key(game_state, "reactive_decision_payload")
    if not isinstance(payload, dict):
        raise ValueError(
            f"reactive_decision_payload must be dict when decision_mode='state', got {type(payload).__name__}"
        )

    decision_entry = payload.get(reactive_unit_id)
    if decision_entry is None:
        raise ValueError(
            "ValueError[reactive_move.missing_decision]: "
            f"reactive_unit_id={reactive_unit_id} has no decision in reactive_decision_payload"
        )
    if not isinstance(decision_entry, dict):
        raise ValueError(
            "ValueError[reactive_move.invalid_decision_payload]: "
            f"reactive_unit_id={reactive_unit_id} decision must be dict, got {type(decision_entry).__name__}"
        )

    action = require_key(decision_entry, "action")
    if action == "decline_reactive_move":
        # Consume decision entry once used in this window.
        del payload[reactive_unit_id]
        return "decline", None
    if action != "reactive_move":
        raise ValueError(
            "ValueError[reactive_move.invalid_decision_action]: "
            f"reactive_unit_id={reactive_unit_id} action={action!r}"
        )

    destination = require_key(decision_entry, "destination")
    if isinstance(destination, dict):
        if "col" not in destination or "row" not in destination:
            raise KeyError(
                "ValueError[reactive_move.invalid_destination_payload]: "
                f"reactive_unit_id={reactive_unit_id} destination dict must have col/row"
            )
        dest_col, dest_row = normalize_coordinates(destination["col"], destination["row"])
    elif isinstance(destination, (tuple, list)) and len(destination) == 2:
        dest_col, dest_row = normalize_coordinates(destination[0], destination[1])
    else:
        raise ValueError(
            "ValueError[reactive_move.invalid_destination_payload]: "
            f"reactive_unit_id={reactive_unit_id} destination must be [col,row] or {{col,row}}, got {destination!r}"
        )

    selected_dest = (dest_col, dest_row)
    if selected_dest not in valid_destinations:
        raise ValueError(
            "ValueError[reactive_move.invalid_destination]: "
            f"reactive_unit_id={reactive_unit_id} destination={selected_dest} pool_size={len(valid_destinations)}"
        )

    del payload[reactive_unit_id]
    return "move", selected_dest


def refresh_all_positional_caches_after_reactive_move(
    game_state: Dict[str, Any],
    enemy_adjacent_counts_override: Optional[Dict[int, Dict[Tuple[int, int], int]]] = None,
    enemy_adjacent_sets_override: Optional[Dict[int, Set[Tuple[int, int]]]] = None,
    *,
    reactive_move_old_col: Optional[int] = None,
    reactive_move_old_row: Optional[int] = None,
    reactive_move_new_col: Optional[int] = None,
    reactive_move_new_row: Optional[int] = None,
) -> None:
    """
    Centralized cache refresh after any applied reactive move.
    """
    # Invalidate global LoS caches.
    game_state["los_cache"] = {}
    # hex_los_cache: selective invalidation when reactive move positions known (PERF)
    if "hex_los_cache" in game_state:
        positions_to_invalidate: List[Tuple[int, int]] = []
        if reactive_move_old_col is not None and reactive_move_old_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_old_col, reactive_move_old_row))
        if reactive_move_new_col is not None and reactive_move_new_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_new_col, reactive_move_new_row))
        if positions_to_invalidate:
            keys_to_remove = [
                k for k in game_state["hex_los_cache"].keys()
                if k[0] in positions_to_invalidate or k[1] in positions_to_invalidate
            ]
            for k in keys_to_remove:
                del game_state["hex_los_cache"][k]
        else:
            game_state["hex_los_cache"] = {}

    # Invalidate all destination/target pools via movement helper.
    from .movement_handlers import _invalidate_all_destination_pools_after_movement
    _invalidate_all_destination_pools_after_movement(game_state)

    # Invalidate unit-local LoS caches.
    for unit in require_key(game_state, "units"):
        if "los_cache" in unit:
            unit["los_cache"] = {}

    players_present = _get_players_present_from_units_cache(game_state)
    if enemy_adjacent_sets_override is not None:
        if enemy_adjacent_counts_override is None:
            raise KeyError(
                "enemy_adjacent_counts_override is required when enemy_adjacent_sets_override is provided"
            )
        for player_int in players_present:
            if player_int not in enemy_adjacent_counts_override:
                raise KeyError(
                    f"Missing adjacency counts override for player {player_int} during reactive cache refresh"
                )
            if player_int not in enemy_adjacent_sets_override:
                raise KeyError(
                    f"Missing adjacency override for player {player_int} during reactive cache refresh"
                )
            override_counts = require_key(enemy_adjacent_counts_override, player_int)
            override_set = require_key(enemy_adjacent_sets_override, player_int)
            if not isinstance(override_counts, dict):
                raise TypeError(
                    f"Adjacency counts override for player {player_int} must be dict, got {type(override_counts).__name__}"
                )
            if not isinstance(override_set, set):
                raise TypeError(
                    f"Adjacency override for player {player_int} must be set, got {type(override_set).__name__}"
                )
            game_state[f"enemy_adjacent_counts_player_{player_int}"] = dict(override_counts)
            game_state[f"enemy_adjacent_hexes_player_{player_int}"] = set(override_set)
        return

    # Direct recompute path for external callers: recompute from units_cache snapshot.
    for player_int in players_present:
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def update_enemy_adjacent_caches_after_unit_move(
    game_state: Dict[str, Any],
    moved_unit_player: int,
    old_col: int,
    old_row: int,
    new_col: int,
    new_row: int,
    old_occupied: Optional[Set[Tuple[int, int]]] = None,
    new_occupied: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """
    Update enemy adjacency caches after one unit movement.
    Only recomputes caches for players who see the moved unit as an enemy.
    When player X moves, only OTHER players' caches change (they see player X as enemy).
    Player X's own cache is unaffected (their enemies didn't move).
    """
    if old_col == new_col and old_row == new_row:
        return

    moved_player_int = int(moved_unit_player)
    players_present = _get_players_present_from_units_cache(game_state)
    if moved_player_int not in players_present:
        raise KeyError(
            f"Moved unit player {moved_unit_player} not present in units_cache players {sorted(players_present)}"
        )

    for player_int in players_present:
        if player_int == moved_player_int:
            continue
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def update_enemy_adjacent_caches_after_unit_removed(
    game_state: Dict[str, Any],
    removed_unit_player: int,
    old_col: int,
    old_row: int,
    old_occupied: Optional[Set[Tuple[int, int]]] = None,
) -> None:
    """
    Update enemy adjacency caches after one unit removal from units_cache.
    Only recomputes caches for players who saw the removed unit as an enemy.
    Unit is already removed from units_cache before this call.
    """
    removed_player_int = int(removed_unit_player)
    players_present = _get_players_present_from_units_cache(game_state)
    players_present.add(removed_player_int)

    for player_int in players_present:
        if player_int == removed_player_int:
            continue
        counts, hexes = _compute_enemy_adjacent_cache_for_player_from_units_cache(game_state, player_int)
        game_state[f"enemy_adjacent_counts_player_{player_int}"] = counts
        game_state[f"enemy_adjacent_hexes_player_{player_int}"] = hexes


def maybe_resolve_reactive_move(
    game_state: Dict[str, Any],
    moved_unit_id: str,
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    move_kind: str,
    move_cause: str,
) -> Dict[str, Any]:
    """
    Resolve reactive_move window after an enemy unit has ended movement.
    """
    # Validate event payload.
    moved_unit_id_str = str(moved_unit_id)
    from_col_int, from_row_int = normalize_coordinates(from_col, from_row)
    to_col_int, to_row_int = normalize_coordinates(to_col, to_row)
    if move_kind not in {"move", "advance", "flee", "reposition_normal"}:
        raise ValueError(f"Unsupported move_kind for reactive_move: {move_kind}")
    if move_cause not in {"normal", "reactive_move"}:
        raise ValueError(f"Unsupported move_cause for reactive_move: {move_cause}")

    if move_cause == "reactive_move":
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    if require_key(game_state, "reaction_window_active"):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        current_player = game_state.get("current_player", "?")
        raise RuntimeError(
            "RuntimeError[reactive_move.reentrance]: "
            f"episode={episode} turn={turn} phase={phase} current_player={current_player} "
            f"moved_unit_id={moved_unit_id_str} move_cause={move_cause} reaction_window_active=True"
        )

    moved_unit = get_unit_by_id(game_state, moved_unit_id_str)
    if moved_unit is None:
        raise KeyError(f"Moved unit not found for reactive_move: {moved_unit_id_str}")
    moved_player = require_key(moved_unit, "player")

    units_cache = require_key(game_state, "units_cache")

    # Build reaction candidates.
    reacted_set = require_key(game_state, "units_reacted_this_enemy_turn")
    if not isinstance(reacted_set, set):
        raise ValueError(
            f"units_reacted_this_enemy_turn must be set, got {type(reacted_set).__name__}"
        )

    eligible_units: List[Dict[str, Any]] = []
    for unit_id in units_cache.keys():
        unit = get_unit_by_id(game_state, unit_id)
        if unit is None:
            raise KeyError(f"Unit {unit_id} present in units_cache but missing from game_state['units']")

        unit_id_str = str(require_key(unit, "id"))
        if not is_unit_alive(unit_id_str, game_state):
            continue

        unit_player = require_key(unit, "player")
        if int(unit_player) == int(moved_player):
            continue
        if unit_id_str in reacted_set:
            continue
        if not _unit_has_rule_effect(unit, "reactive_move"):
            continue

        unit_col, unit_row = require_unit_position(unit, game_state)
        if calculate_hex_distance(unit_col, unit_row, to_col_int, to_row_int) > 9:
            continue

        eligible_units.append(unit)

    if not eligible_units:
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    ordered_units = _select_reactive_unit_order(game_state, eligible_units)
    if not ordered_units:
        return {"reactive_moves_applied": 0, "reactive_moves_declined": 0, "triggered": False}

    print(f"[PERF-REACTIVE] ordered_units={len(ordered_units)} eligible={len(eligible_units)}", flush=True)
    # Build adjacency structures only when at least one non-reacted unit is eligible.
    players_present = _get_players_present_from_units_cache(game_state)
    reactive_adjacent_counts_by_player, reactive_adjacent_sets_by_player = (
        _build_enemy_adjacent_structures_from_units_cache(game_state, players_present)
    )
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")

    game_state["reaction_window_active"] = True
    game_state["last_move_event_id"] = int(require_key(game_state, "last_move_event_id")) + 1
    applied_count = 0
    declined_count = 0
    try:
        for reactive_unit in ordered_units:
            reactive_unit_id = str(require_key(reactive_unit, "id"))
            reactive_player_raw = require_key(reactive_unit, "player")
            try:
                reactive_player_int = int(reactive_player_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Reactive unit {reactive_unit_id} has invalid player: {reactive_player_raw!r}"
                ) from exc
            if reactive_player_int not in reactive_adjacent_sets_by_player:
                raise KeyError(
                    f"Missing reactive adjacency snapshot for player {reactive_player_int}"
                )

            # Each reacting unit gets its own D6 range roll.
            move_range = resolve_dice_value("D6", "reactive_move_distance")
            valid_destinations = _build_reactive_move_destinations_pool(
                game_state,
                reactive_unit,
                move_range,
                enemy_adjacent_hexes_override=reactive_adjacent_sets_by_player[reactive_player_int],
            )
            if not valid_destinations:
                continue

            decision_action, selected_dest = _resolve_reactive_decision(
                game_state,
                reactive_unit_id,
                valid_destinations,
                to_col_int,
                to_row_int,
            )
            if decision_action == "decline":
                declined_count += 1
                if "action_logs" not in game_state:
                    game_state["action_logs"] = []
                game_state["action_logs"].append(
                    {
                        "type": "reactive_move_declined",
                        "unitId": reactive_unit_id,
                        "triggered_by_unit_id": moved_unit_id_str,
                        "trigger_move_kind": move_kind,
                        "trigger_move_cause": move_cause,
                        "range_roll": move_range,
                        "event_fromCol": from_col_int,
                        "event_fromRow": from_row_int,
                        "event_toCol": to_col_int,
                        "event_toRow": to_row_int,
                    }
                )
                continue

            if selected_dest is None:
                raise ValueError(
                    f"Reactive move decision returned action={decision_action!r} without destination for unit {reactive_unit_id}"
                )
            dest_col, dest_row = selected_dest

            orig_col, orig_row = require_unit_position(reactive_unit, game_state)
            set_unit_coordinates(reactive_unit, dest_col, dest_row)
            update_units_cache_position(game_state, reactive_unit_id, dest_col, dest_row)
            reacted_set.add(reactive_unit_id)
            game_state["last_move_cause"] = "reactive_move"
            ability_display_name = _get_source_unit_rule_display_name_for_effect(
                reactive_unit, "reactive_move"
            )
            if ability_display_name is None:
                unit_name = reactive_unit.get("DISPLAY_NAME") or reactive_unit.get("unitType") or "UNKNOWN"
                raise ValueError(
                    f"Unit {reactive_unit_id} ({unit_name}) triggered reactive_move without source rule displayName"
                )
            _apply_enemy_adjacent_delta_for_moved_unit(
                counters_by_player=reactive_adjacent_counts_by_player,
                sets_by_player=reactive_adjacent_sets_by_player,
                players_present=players_present,
                moved_unit_player=reactive_player_int,
                old_pos=(orig_col, orig_row),
                new_pos=(dest_col, dest_row),
                board_cols=board_cols,
                board_rows=board_rows,
            )

            # Keep action logs explicit for post-mortem analysis.
            if "action_logs" not in game_state:
                game_state["action_logs"] = []
            game_state["action_logs"].append(
                {
                    "type": "reactive_move",
                    "message": (
                        f"Unit {reactive_unit_id}({dest_col},{dest_row}) REACTIVE MOVED [{ability_display_name}] "
                        f"from ({orig_col},{orig_row}) to ({dest_col},{dest_row}) [Roll: {move_range}] "
                        f"- trigger: Unit {moved_unit_id_str}->({to_col_int},{to_row_int})"
                    ),
                    "unitId": reactive_unit_id,
                    "player": require_key(reactive_unit, "player"),
                    "ability_display_name": ability_display_name,
                    "triggered_by_unit_id": moved_unit_id_str,
                    "trigger_move_kind": move_kind,
                    "trigger_move_cause": move_cause,
                    "fromCol": orig_col,
                    "fromRow": orig_row,
                    "toCol": dest_col,
                    "toRow": dest_row,
                    "range_roll": move_range,
                    "event_fromCol": from_col_int,
                    "event_fromRow": from_row_int,
                    "event_toCol": to_col_int,
                    "event_toRow": to_row_int,
                }
            )

            refresh_all_positional_caches_after_reactive_move(
                game_state,
                enemy_adjacent_counts_override=reactive_adjacent_counts_by_player,
                enemy_adjacent_sets_override=reactive_adjacent_sets_by_player,
                reactive_move_old_col=orig_col,
                reactive_move_old_row=orig_row,
                reactive_move_new_col=dest_col,
                reactive_move_new_row=dest_row,
            )
            applied_count += 1
    finally:
        game_state["reaction_window_active"] = False

    return {
        "reactive_moves_applied": applied_count,
        "reactive_moves_declined": declined_count,
        "triggered": applied_count > 0 or declined_count > 0,
    }
