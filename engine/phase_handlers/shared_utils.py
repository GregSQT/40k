#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import Dict, List, Tuple, Set, Optional, Any, Union, cast
import copy
import inspect

from shared.data_validation import require_key
from engine.action_log_utils import append_action_log
from engine.combat_utils import (
    get_unit_coordinates,
    normalize_coordinates,
    calculate_hex_distance,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    get_unit_by_id,
    set_unit_coordinates,
    DiceValue,
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
    if game_state is None:
        return {(col, row)}
    ez = get_engagement_zone(game_state)
    if ez <= 1:
        return {(col, row)}
    base_shape = unit["BASE_SHAPE"]
    base_size = unit["BASE_SIZE"]
    if "orientation" in unit:
        orientation = int(require_key(unit, "orientation"))
    else:
        orientation = 0
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
    # Bounds check (must iterate — no way to vectorize without numpy)
    for c, r in candidate_hexes:
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows:
            return False
    # Set-intersection checks are implemented in C and much faster than Python loops
    if wall_hexes and (candidate_hexes & wall_hexes):
        return False
    if occupied_positions and (candidate_hexes & occupied_positions):
        return False
    if enemy_adjacent_hexes is not None and (candidate_hexes & enemy_adjacent_hexes):
        return False
    return True


def _build_models_for_unit(
    unit: Dict[str, Any],
    unit_id: str,
    unit_col: int,
    unit_row: int,
    unit_hp_cur: int,
    unit_player: int,
    models_cache: Dict[str, Dict[str, Any]],
    squad_models: Dict[str, List[str]],
) -> None:
    """Build per-model entries for one squad (squad.md PR1 1b).

    For mono-figurine units (no explicit unit["models"] list), create exactly
    one model entry derived from the unit's own fields. For multi-figurine
    squads (unit["models"] declared), iterate and build one entry per fig.

    Maintains parallel structures models_cache (model_id -> dict) and
    squad_models (squad_id -> [model_id,...]) without touching units_cache.

    points_per_hp formula (homogeneous):
        VALUE / (model_count_at_start * HP_MAX)
    Mixed profiles (per spec, when models[] declares heterogeneous HP_MAX):
        VALUE / total_hp_pool, total_hp_pool = sum(HP_MAX_i for i in models)
    """
    hp_max = int(require_key(unit, "HP_MAX"))
    if hp_max <= 0:
        raise ValueError(f"Unit {unit_id} has invalid HP_MAX: {hp_max}")
    value = int(require_key(unit, "VALUE"))
    oc = int(require_key(unit, "OC"))
    t_stat = int(require_key(unit, "T"))
    armor_save = int(require_key(unit, "ARMOR_SAVE"))
    invul_save_raw = require_key(unit, "INVUL_SAVE")
    # Sentinel convention: INVUL_SAVE = 7 means "no invul save" (aligned with
    # observation_builder.py:1332 has_invul = invul_save < 7). Accept 0 in
    # legacy data and convert to 7.
    invul_save = int(invul_save_raw) if int(invul_save_raw) > 0 else 7
    shoot_left = int(require_key(unit, "SHOOT_LEFT"))
    attack_left = int(require_key(unit, "ATTACK_LEFT"))
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    cc_weapons = require_key(unit, "CC_WEAPONS")
    selected_rng = unit.get("selectedRngWeaponIndex")
    selected_cc = unit.get("selectedCcWeaponIndex")

    explicit_models = unit.get("models")
    if isinstance(explicit_models, list) and len(explicit_models) > 0:
        # Multi-figurine squad with explicit positions.
        model_specs = explicit_models
    else:
        # Backward compat: single-figurine squad derived from unit fields.
        model_specs = [{"col": unit_col, "row": unit_row, "HP_CUR": unit_hp_cur}]

    model_count_at_start = len(model_specs)
    # points_per_hp — homogeneous case (all models share unit HP_MAX). For
    # mixed profiles (future), each spec carries its own HP_MAX and the formula
    # becomes VALUE / sum(HP_MAX_i).
    total_hp_pool = 0
    for spec in model_specs:
        spec_hp_max = int(spec.get("HP_MAX", hp_max))
        if spec_hp_max <= 0:
            raise ValueError(f"Squad {unit_id}: model spec has invalid HP_MAX={spec_hp_max}")
        total_hp_pool += spec_hp_max
    points_per_hp = float(value) / float(total_hp_pool) if total_hp_pool > 0 else 0.0

    model_ids: List[str] = []
    for idx, spec in enumerate(model_specs):
        model_id = f"{unit_id}#{idx}"
        model_ids.append(model_id)
        spec_col, spec_row = normalize_coordinates(
            int(require_key(spec, "col")), int(require_key(spec, "row"))
        )
        spec_hp_max = int(spec.get("HP_MAX", hp_max))
        spec_hp_cur = int(spec.get("HP_CUR", spec_hp_max))
        models_cache[model_id] = {
            "squad_id": unit_id,
            "col": spec_col,
            "row": spec_row,
            "HP_CUR": spec_hp_cur,
            "HP_MAX": spec_hp_max,
            "player": unit_player,
            "wounds_allocated_this_activation": 0,
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left,
            "OC": int(spec.get("OC", oc)),
            "points_per_hp": points_per_hp,
            "ARMOR_SAVE": int(spec.get("ARMOR_SAVE", armor_save)),
            "INVUL_SAVE": int(spec.get("INVUL_SAVE", invul_save)),
            "T": int(spec.get("T", t_stat)),
            "RNG_WEAPONS": copy.deepcopy(spec.get("RNG_WEAPONS", rng_weapons)),
            "CC_WEAPONS": copy.deepcopy(spec.get("CC_WEAPONS", cc_weapons)),
            "selectedRngWeaponIndex": spec.get("selectedRngWeaponIndex", selected_rng),
            "selectedCcWeaponIndex": spec.get("selectedCcWeaponIndex", selected_cc),
        }
    squad_models[unit_id] = model_ids


def build_units_cache(game_state: Dict[str, Any]) -> None:
    """
    Build units_cache from game_state["units"].

    Creates game_state["units_cache"]: Dict[str, Dict] mapping unit_id (str) to
    {"col": int, "row": int, "HP_CUR": int, "player": int, "BASE_SHAPE": str,
     "BASE_SIZE": int|list, "orientation": int, "occupied_hexes": Set[(col,row)]}
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
    models_cache: Dict[str, Dict[str, Any]] = {}
    squad_models: Dict[str, List[str]] = {}

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

        base_shape = unit["BASE_SHAPE"]
        base_size = unit["BASE_SIZE"]
        if "orientation" in unit:
            orientation = int(require_key(unit, "orientation"))
        else:
            orientation = 0
        occupied = _compute_unit_occupied_hexes(col, row, unit, game_state)

        units_cache[unit_id] = {
            "col": col,
            "row": row,
            "HP_CUR": hp_cur,
            "player": player,
            # VALUE (points) : source de verite reward, requis par resolve_squad_shoot
            # / resolve_squad_fight. Present sur chaque unit (deja require_key dans
            # _build_models_for_unit).
            "VALUE": int(require_key(unit, "VALUE")),
            "BASE_SHAPE": base_shape,
            "BASE_SIZE": base_size,
            "orientation": orientation,
            "occupied_hexes": occupied,
            # PR4 4e-i : ajout dict parallele {model_id: (col, row)}.
            # Source de verite per-figurine pour le pipeline squad. Construit dans
            # la passe model_cache ci-dessous (apres _build_models_for_unit).
            # Initialise vide ici, rempli juste apres.
            "occupied_hexes_by_model": {},
        }

        for cell in occupied:
            occupation_map[cell] = unit_id

        # ====================================================================
        # MODEL-LEVEL CACHE (squad.md PR1 1b)
        # ====================================================================
        # Build models_cache + squad_models in parallel to units_cache.
        # Backward compat: if unit has no explicit "models" list, treat it as
        # a single-figurine squad (1 unit = 1 model).
        # Multi-figurine squads (future) declare unit["models"] = [{col,row,...},...].
        _build_models_for_unit(
            unit=unit,
            unit_id=unit_id,
            unit_col=col,
            unit_row=row,
            unit_hp_cur=hp_cur,
            unit_player=player,
            models_cache=models_cache,
            squad_models=squad_models,
        )
        # Fill occupied_hexes_by_model from models_cache (PR4 4e-i)
        units_cache[unit_id]["occupied_hexes_by_model"] = {
            mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
            for mid in squad_models.get(unit_id, [])  # get allowed
            if mid in models_cache
        }
        # F2 fix (audit) : pour multi-fig, recompute occupied_hexes = union des
        # footprints de toutes les figs. Pour mono-fig (1 fig au anchor),
        # occupied_hexes deja correct depuis _compute_unit_occupied_hexes(col,row,...).
        if len(squad_models.get(unit_id, [])) > 1:  # get allowed
            # game_state["units_cache"] pas encore set globalement, on patch via la variable locale
            game_state_view = dict(game_state)
            game_state_view["units_cache"] = units_cache
            game_state_view["models_cache"] = models_cache
            game_state_view["squad_models"] = squad_models
            game_state_view["occupation_map"] = occupation_map
            _recompute_squad_occupied_hexes(game_state_view, unit_id)

    game_state["units_cache"] = units_cache
    game_state["occupation_map"] = occupation_map
    game_state["models_cache"] = models_cache
    game_state["squad_models"] = squad_models

    # squad_cache: built APRES models_cache + squad_models (depend des deux).
    # model_count_at_start est capture maintenant et ne changera plus.
    squad_cache: Dict[str, Dict[str, Any]] = {}
    for squad_id in squad_models:
        entry = _compute_squad_cache_entry(game_state, squad_id)
        entry["model_count_at_start"] = entry["model_count"]
        squad_cache[squad_id] = entry
        # Mirror OC_TOTAL into units_cache (squad.md PR1 1d): observation_builder
        # et logique d'objectifs lisent l'OC agrege depuis units_cache.
        if squad_id in units_cache:
            units_cache[squad_id]["OC_TOTAL"] = entry["oc_total"]
    game_state["squad_cache"] = squad_cache

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
    if old_entry is None:
        raise KeyError(f"Unit {unit_id} not found in units_cache — cannot update HP for unknown unit")
    base_shape = old_entry["BASE_SHAPE"]
    base_size = old_entry["BASE_SIZE"]
    if old_entry and "orientation" in old_entry:
        orient_val = int(require_key(old_entry, "orientation"))
    else:
        orient_val = 0
    unit_stub = {
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orient_val,
    }
    new_occupied = _compute_unit_occupied_hexes(norm_col, norm_row, unit_stub, game_state)
    
    _update_occupation_map(game_state, unit_id, old_entry, new_occupied)
    
    game_state["units_cache"][unit_id] = {
        "col": norm_col,
        "row": norm_row,
        "HP_CUR": effective_hp,
        "player": player,
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orient_val,
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
    
    if "orientation" in entry:
        orient_val = int(require_key(entry, "orientation"))
    else:
        orient_val = 0
    unit_stub = {
        "BASE_SHAPE": entry["BASE_SHAPE"],
        "BASE_SIZE": entry["BASE_SIZE"],
        "orientation": orient_val,
    }
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
    game_state.pop("_cached_best_enemy_score", None)
    game_state.pop("_cached_best_enemy_global", None)
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
    from engine.spatial_relations import get_engagement_zone as _get_engagement_zone

    return _get_engagement_zone(game_state)


def get_max_base_size_hex(game_state: Dict[str, Any]) -> int:
    """Plafond (diamètre hex) pour borner les empreintes ennemies dans les filtres spatiaux.

    Utilisé par la prune conservatrice des ennemis en déplacement (ez > 1) : au-delà de ce
    diamètre, on tronque la contribution « rayon d'empreinte » pour rester sûr sans exploser
    la fenêtre si des données unité sont aberrantes.
    """
    config = game_state.get("config") or {}
    game_rules = config.get("game_rules") or {}
    return int(game_rules.get("max_base_size_hex", 35))


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
    ez_dilation = int(require_key(game_state, "inches_to_subhex"))
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

        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            unit_cells = set(by_model.values())
        else:
            unit_cells = {(int(require_key(entry, "col")), int(require_key(entry, "row")))}
        all_enemy_occupied.update(unit_cells)
        per_unit_occupied.append(unit_cells)

    from engine.hex_utils import dilate_hex_set
    zone_hexes = dilate_hex_set(all_enemy_occupied, ez_dilation, board_cols, board_rows)

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
    ez_dilation = int(require_key(game_state, "inches_to_subhex"))
    from engine.hex_utils import dilate_hex_set

    counters_by_player: Dict[int, Dict[Tuple[int, int], int]] = {
        player_int: {} for player_int in players_present
    }
    sets_by_player: Dict[int, Set[Tuple[int, int]]] = {
        player_int: set() for player_int in players_present
    }

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
        by_model = cache_entry.get("occupied_hexes_by_model")
        if by_model:
            unit_cells = set(by_model.values())
        else:
            unit_cells = {(int(require_key(cache_entry, "col")), int(require_key(cache_entry, "row")))}
        unit_zone = dilate_hex_set(unit_cells, ez_dilation, board_cols, board_rows)
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
    game_state: Optional[Dict[str, Any]] = None,
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
                if game_state is not None and game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    units_cache = game_state.get("units_cache", {})  # get allowed
                    unit_positions = {
                        uid: (e.get("col"), e.get("row"), e.get("player"), e.get("occupied_hexes"))
                        for uid, e in units_cache.items()
                    }
                    counter_snapshot = {
                        str(k): v for k, v in player_counters.items() if k in old_zone
                    }
                    add_debug_file_log(game_state, (
                        f"[DELTA_MISSING_HEX] missing={h} perspective_player={perspective_player} "
                        f"moved_unit_player={moved_unit_player} ez={engagement_zone} "
                        f"old_occupied={sorted(old_occupied)} new_occupied={sorted(new_occupied)} "
                        f"old_zone={sorted(old_zone)} "
                        f"counter_for_old_zone={counter_snapshot} "
                        f"counter_total_keys={len(player_counters)} "
                        f"unit_positions={unit_positions}"
                    ))
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
    # _hex_los_state_cache: NOT invalidated on reactive move (terrain-static, see
    # _invalidate_los_cache_for_moved_unit for rationale).
    # hex_los_cache: selective invalidation maintained (footprint-dependent).
    if "hex_los_cache" in game_state:
        positions_to_invalidate: List[Tuple[int, int]] = []
        if reactive_move_old_col is not None and reactive_move_old_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_old_col, reactive_move_old_row))
        if reactive_move_new_col is not None and reactive_move_new_row is not None:
            positions_to_invalidate.append(normalize_coordinates(reactive_move_new_col, reactive_move_new_row))
        if positions_to_invalidate:
            keys_to_remove = [k for k in game_state["hex_los_cache"].keys()
                              if k[0] in positions_to_invalidate or k[1] in positions_to_invalidate]
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
                append_action_log(
                    game_state,
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
                    },
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
                old_occupied={(orig_col, orig_row)},
                new_occupied={(dest_col, dest_row)},
                board_cols=board_cols,
                board_rows=board_rows,
                game_state=game_state,
            )

            # Keep action logs explicit for post-mortem analysis.
            if "action_logs" not in game_state:
                game_state["action_logs"] = []
            append_action_log(
                game_state,
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
                },
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


# ============================================================================
# DISTANCE PRIMITIVES — Engagement Range, Base-to-Base, Coherency
# ============================================================================
# Reference: Documentation/TODO/squad.md §"Definition des distances en hex-grid"
# Toutes les distances sont en subhexes. `inches_to_subhex` est l echelle du
# scenario (x5: 5 subhexes par pouce, x10: 10 subhexes par pouce).

BASE_TO_BASE_SUBHEX = 1


def get_engagement_range_subhex(game_state: Dict[str, Any]) -> int:
    """Engagement Range = 1" horizontal (regle officielle).
    Retourne le seuil ER en subhexes pour l echelle du scenario."""
    return int(require_key(game_state, "inches_to_subhex"))


def get_coherency_subhex(game_state: Dict[str, Any]) -> int:
    """Unit Coherency = 2" horizontal (regle officielle).
    Retourne le seuil coherency en subhexes pour l echelle du scenario."""
    return 2 * int(require_key(game_state, "inches_to_subhex"))


def is_base_to_base(col_a: int, row_a: int, col_b: int, row_b: int) -> bool:
    """B2B: hexes directement adjacents (distance hex == 1).
    Strictement plus contraignant que l Engagement Range."""
    return calculate_hex_distance(col_a, row_a, col_b, row_b) == BASE_TO_BASE_SUBHEX


def is_in_engagement_range(
    col_a: int, row_a: int, col_b: int, row_b: int, game_state: Dict[str, Any]
) -> bool:
    """ER: distance <= 1" horizontal."""
    return calculate_hex_distance(col_a, row_a, col_b, row_b) <= get_engagement_range_subhex(game_state)


# ============================================================================
# MODEL-LEVEL HELPERS (squad.md PR1 1b)
# ============================================================================
# Source de verite par-figurine = models_cache[model_id]. Source de verite
# agregee par-escouade = units_cache[squad_id]. Toute mutation par-figurine
# DOIT passer par ces helpers pour garder les deux caches synchronises.


def is_model_alive(model_id: str, game_state: Dict[str, Any]) -> bool:
    """True si la figurine est presente dans models_cache."""
    require_key(game_state, "models_cache")
    return model_id in game_state["models_cache"]


# ----------------------------------------------------------------------------
# squad_cache: agregats par escouade (PR1 1c)
# ----------------------------------------------------------------------------


def _compute_squad_cache_entry(
    game_state: Dict[str, Any], squad_id: str
) -> Dict[str, Any]:
    """Recompute complet d'une entree squad_cache depuis models_cache.

    Centroide = moyenne des positions des figurines vivantes.
    is_coherent = booleen recompute via validate_squad_coherency.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    alive = [models_cache[m] for m in model_ids if m in models_cache]
    n = len(alive)
    if n == 0:
        return {
            "is_coherent": True,  # escouade morte: pas de violation
            "model_count": 0,
            "model_count_at_start": 0,
            "oc_total": 0,
            "centroid_col": 0.0,
            "centroid_row": 0.0,
        }
    centroid_col = sum(int(m["col"]) for m in alive) / float(n)
    centroid_row = sum(int(m["row"]) for m in alive) / float(n)
    oc_total = sum(int(m["OC"]) for m in alive)
    is_coherent = validate_squad_coherency(game_state, squad_id)
    return {
        "is_coherent": is_coherent,
        "model_count": n,
        "model_count_at_start": 0,  # remplace par caller a l'init; preserve sinon
        "oc_total": oc_total,
        "centroid_col": centroid_col,
        "centroid_row": centroid_row,
    }


def _recompute_squad_cache(game_state: Dict[str, Any], squad_id: str) -> None:
    """Recalcule squad_cache[squad_id] tout en preservant model_count_at_start.

    A appeler depuis destroy_model et update_model_position (les deux seuls
    points d'ecriture de presence/position).
    Mirror OC_TOTAL vers units_cache si l escouade est vivante.
    """
    squad_cache = game_state.get("squad_cache")
    if squad_cache is None:
        return  # pas encore initialise (ex: avant build_units_cache)
    new_entry = _compute_squad_cache_entry(game_state, squad_id)
    old_entry = squad_cache.get(squad_id)
    if old_entry is not None and "model_count_at_start" in old_entry:
        new_entry["model_count_at_start"] = old_entry["model_count_at_start"]
    squad_cache[squad_id] = new_entry
    # Mirror OC_TOTAL → units_cache (cf. spec §"Contrat units_cache").
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is not None:
        units_entry["OC_TOTAL"] = new_entry["oc_total"]


def validate_squad_coherency(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Recalcul independant de la coherency d'une escouade.

    Ne lit PAS squad_cache["is_coherent"] — recompute depuis models_cache.

    Regles officielles (Core Concepts) :
      - squad_size == 1 : vacuously True (cas degenere).
      - 2 <= squad_size <= 6 : chaque figurine a >= 1 voisin a <= 2".
      - squad_size >= 7 : chaque figurine a >= 2 voisins a <= 2".
    Distance horizontale uniquement (moteur 2D, pas de verticale).
    Propriete locale (1 ou 2 voisins directs), pas de connectivite transitive.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    alive = [models_cache[m] for m in model_ids if m in models_cache]
    n = len(alive)
    if n <= 1:
        return True
    coherency_dist = get_coherency_subhex(game_state)
    min_neighbors = 2 if n >= 7 else 1
    positions = [(int(m["col"]), int(m["row"])) for m in alive]
    for i, (ci, ri) in enumerate(positions):
        neighbors = 0
        for j, (cj, rj) in enumerate(positions):
            if i == j:
                continue
            if calculate_hex_distance(ci, ri, cj, rj) <= coherency_dist:
                neighbors += 1
                if neighbors >= min_neighbors:
                    break
        if neighbors < min_neighbors:
            return False
    return True


def _recompute_squad_occupied_hexes(game_state: Dict[str, Any], squad_id: str) -> None:
    """Recalcule occupied_hexes (union des footprints de toutes les figs vivantes)
    ET occupied_hexes_by_model (map model_id -> position courante de la figurine),
    depuis models_cache.

    Fix F2 (audit) : occupied_hexes doit couvrir TOUTES les figs du squad, pas
    seulement le footprint de l'ancre. Sinon collisions inter-squads ignorent
    les figs non-ancres.

    occupied_hexes_by_model est la source de vérité par-modèle consommée par le
    frontend. Doit rester synchronisée avec models_cache à chaque mutation de
    position (move, charge, advance, pile-in).

    Egalement met a jour occupation_map (reverse lookup cell -> unit_id).
    Idempotent. Pas d'effet si squad_id absent du units_cache.
    """
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    base_shape = entry["BASE_SHAPE"]
    base_size = entry["BASE_SIZE"]
    orientation = int(entry.get("orientation", 0))  # get allowed
    unit_stub = {
        "BASE_SHAPE": base_shape,
        "BASE_SIZE": base_size,
        "orientation": orientation,
    }
    old_occupied = entry.get("occupied_hexes", set())
    new_occupied: Set[Tuple[int, int]] = set()
    new_by_model: Dict[str, Tuple[int, int]] = {}
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        m_col = int(m["col"])
        m_row = int(m["row"])
        new_by_model[mid] = (m_col, m_row)
        fp = _compute_unit_occupied_hexes(m_col, m_row, unit_stub, game_state)
        new_occupied.update(fp)
    entry["occupied_hexes"] = new_occupied
    entry["occupied_hexes_by_model"] = new_by_model
    # Sync occupation_map (retire cellules disparues, ajoute nouvelles)
    occ_map = game_state.get("occupation_map")
    if occ_map is not None:
        for cell in old_occupied:
            if cell not in new_occupied and occ_map.get(cell) == squad_id:
                del occ_map[cell]
        for cell in new_occupied:
            occ_map[cell] = squad_id


def translate_squad_to_destination(
    game_state: Dict[str, Any], squad_id: str, dest_col: int, dest_row: int
) -> None:
    """Déplacement rigide d'une escouade : translate toutes les figurines vivantes
    par le delta (dest - ancien_ancre), puis resync caches.

    Sémantique : "l'escouade entière bouge vers (dest_col, dest_row)". Préserve
    la formation relative entre figurines. À utiliser pour les actions de
    mouvement (move standard, charge, advance, pile-in, move_after_shooting).

    À NE PAS confondre avec update_units_cache_position seul, qui ne met à jour
    que l'ancre — utilisé après une mort de figurine pour resync l'ancre sans
    toucher aux figs survivantes.
    """
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return
    norm_dest_col, norm_dest_row = normalize_coordinates(int(dest_col), int(dest_row))
    old_col = int(entry.get("col", norm_dest_col))
    old_row = int(entry.get("row", norm_dest_row))
    delta_col = norm_dest_col - old_col
    delta_row = norm_dest_row - old_row
    if delta_col != 0 or delta_row != 0:
        models_cache = require_key(game_state, "models_cache")
        squad_models = require_key(game_state, "squad_models")
        for mid in squad_models.get(squad_id, []):  # get allowed
            m = models_cache.get(mid)
            if m is None:
                continue
            if int(m.get("HP_CUR", 0)) <= 0:  # get allowed
                continue
            m["col"] = int(m["col"]) + delta_col
            m["row"] = int(m["row"]) + delta_row
    # Update anchor first (sets entry.col/row, entry.occupied_hexes = anchor footprint).
    update_units_cache_position(game_state, squad_id, norm_dest_col, norm_dest_row)
    # Then override occupied_hexes (union de toutes les figs) + occupied_hexes_by_model
    # depuis models_cache déplacés. Ordre important : ce 2e appel écrase ce qui doit l'être.
    _recompute_squad_occupied_hexes(game_state, squad_id)


def _recompute_squad_hp_total(game_state: Dict[str, Any], squad_id: str) -> int:
    """Somme des HP_CUR des figurines vivantes d'une escouade.

    Lit models_cache via squad_models pour eviter O(N_total) scan.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    model_ids = squad_models.get(squad_id, [])  # get allowed
    total = 0
    for mid in model_ids:
        m = models_cache.get(mid)
        if m is not None:
            total += int(m["HP_CUR"])
    return total


def _recompute_squad_anchor(game_state: Dict[str, Any], squad_id: str) -> Optional[Tuple[int, int]]:
    """Position de l ancre = figurine vivante de plus petit index.

    Retourne (col, row) ou None si toutes les figurines sont mortes.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            return (int(m["col"]), int(m["row"]))
    return None


def update_model_position(
    game_state: Dict[str, Any], model_id: str, col: int, row: int
) -> None:
    """Met a jour la position d une figurine et propage a units_cache si ancre.

    Pour les escouades mono-figurine, met aussi a jour units_cache directement.
    Pour les multi-figurines (futures tranches), n update units_cache que si la
    figurine est l ancre courante (index minimum vivant).
    """
    require_key(game_state, "models_cache")
    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"update_model_position: model {model_id} not in models_cache (dead/absent)")
    norm_col, norm_row = normalize_coordinates(int(col), int(row))
    model["col"] = norm_col
    model["row"] = norm_row

    squad_id = str(model["squad_id"])
    # PR4 4e-i : sync occupied_hexes_by_model
    units_entry_oh = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry_oh is not None:
        oh_by_model = units_entry_oh.setdefault("occupied_hexes_by_model", {})
        oh_by_model[model_id] = (norm_col, norm_row)
    # F2 fix (audit) : recalcule occupied_hexes pour refleter TOUTES les figs
    _recompute_squad_occupied_hexes(game_state, squad_id)
    anchor = _recompute_squad_anchor(game_state, squad_id)
    if anchor is not None:
        anchor_col, anchor_row = anchor
        # Propage uniquement si l ancre a vraiment bouge — evite recompute
        # inutile pour les figurines non-ancres.
        units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
        if units_entry is not None and (
            int(units_entry.get("col", -1)) != anchor_col
            or int(units_entry.get("row", -1)) != anchor_row
        ):
            update_units_cache_position(game_state, squad_id, anchor_col, anchor_row)
    _recompute_squad_cache(game_state, squad_id)


def update_model_hp(game_state: Dict[str, Any], model_id: str, new_hp_cur: int) -> None:
    """Update HP d une figurine et propage le total a units_cache.

    Si HP <= 0 : appelle destroy_model (reason='combat').
    Sinon : met a jour models_cache + units_cache HP_CUR (somme du squad).
    """
    require_key(game_state, "models_cache")
    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"update_model_hp: model {model_id} not in models_cache (dead/absent)")
    effective_hp = max(0, int(new_hp_cur))
    if effective_hp <= 0:
        destroy_model(game_state, model_id, reason="combat")
        return
    model["HP_CUR"] = effective_hp
    squad_id = str(model["squad_id"])
    squad_total = _recompute_squad_hp_total(game_state, squad_id)
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is not None:
        units_entry["HP_CUR"] = squad_total


def destroy_model(game_state: Dict[str, Any], model_id: str, reason: str) -> None:
    """Retire une figurine du jeu et cascade les mises a jour.

    reason ∈ {"combat", "coherency_removal", "deployment_no_space"}

    Etapes (ordre critique) :
      1. Retire l entree de models_cache.
      2. Retire model_id de squad_models[squad_id].
      3. Recalcule l ancre de l escouade si la figurine detruite etait l ancre,
         et propage la nouvelle position a units_cache.
      4. Met a jour units_cache["HP_CUR"] = somme des HP des figurines vivantes.
      5. Si derniere figurine du squad : appelle remove_from_units_cache.

    Le scoring/reward (reason=="combat") et le retrait reglementaire
    (reason=="coherency_removal") sont distingues pour PR3+ — pour PR1 1b on
    enregistre simplement reason dans le debug log.
    """
    require_key(game_state, "models_cache")
    require_key(game_state, "squad_models")
    valid_reasons = ("combat", "coherency_removal", "deployment_no_space")
    if reason not in valid_reasons:
        raise ValueError(f"destroy_model: invalid reason {reason!r}, expected one of {valid_reasons}")

    model = game_state["models_cache"].get(model_id)
    if model is None:
        raise KeyError(f"destroy_model: model {model_id} not in models_cache (already dead?)")

    squad_id = str(model["squad_id"])
    old_col = int(model["col"])
    old_row = int(model["row"])

    # 1. Retire du models_cache.
    del game_state["models_cache"][model_id]
    # 2. Retire de squad_models (preserve l ordre des autres figurines).
    squad_list = game_state["squad_models"].get(squad_id)
    if squad_list is not None and model_id in squad_list:
        squad_list.remove(model_id)
    # PR4 4e-i : sync occupied_hexes_by_model (retire entree fig morte)
    units_entry_oh = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry_oh is not None:
        oh_by_model = units_entry_oh.get("occupied_hexes_by_model")
        if oh_by_model is not None:
            oh_by_model.pop(model_id, None)
    # F2 fix (audit) : recalcule occupied_hexes apres retrait de la fig
    _recompute_squad_occupied_hexes(game_state, squad_id)

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "?")
    add_debug_file_log(
        game_state,
        f"[MODEL DESTROY] E{episode} T{turn} {phase} model_id={model_id} squad={squad_id} "
        f"pos=({old_col},{old_row}) reason={reason}"
    )

    # 3/4/5. Cascade vers units_cache.
    units_entry = game_state.get("units_cache", {}).get(squad_id)  # get allowed
    if units_entry is None:
        return  # squad deja absent du units_cache (cas degenere)

    squad_total = _recompute_squad_hp_total(game_state, squad_id)
    if squad_total <= 0 or not game_state["squad_models"].get(squad_id):
        # Derniere figurine : retirer l escouade du units_cache + squad_cache.
        remove_from_units_cache(game_state, squad_id)
        squad_cache_local = game_state.get("squad_cache")
        if squad_cache_local is not None:
            squad_cache_local.pop(squad_id, None)
        return

    # Recalcule ancre si necessaire.
    anchor = _recompute_squad_anchor(game_state, squad_id)
    if anchor is not None:
        anchor_col, anchor_row = anchor
        if int(units_entry.get("col", -1)) != anchor_col or int(units_entry.get("row", -1)) != anchor_row:
            update_units_cache_position(game_state, squad_id, anchor_col, anchor_row)

    units_entry["HP_CUR"] = squad_total
    _recompute_squad_cache(game_state, squad_id)


# ============================================================================
# MULTI-MODEL MOVEMENT PLAN (squad.md PR2 2a)
# ============================================================================
# Pipeline mutualise pour Normal/Advance/Fall Back (et plus tard Charge/Pile In/
# Consolidation). Transaction atomique : dry-run complet → validation → commit
# en une passe. Aucune ecriture cache avant validation.


DEFAULT_MOVE_CONSTRAINTS: Dict[str, Any] = {
    "budget_per_model": None,    # None = pas de check budget
    "forbid_enemy_er": True,
    "require_coherency": True,
    "allow_walls": False,
    "allow_collisions": False,
}


def build_rigid_plan(
    anchor_dest_col: int,
    anchor_dest_row: int,
    squad_id: str,
    game_state: Dict[str, Any],
) -> Optional[List[Tuple[str, int, int]]]:
    """Translation rigide depuis l'ancre — Normal/Advance/Fall Back.

    L ancre = figurine vivante de plus petit index (cf. _recompute_squad_anchor).
    Toutes les figurines suivent le meme vecteur (dx, dy) = anchor_dest - anchor_origin.

    Returns list[(model_id, new_col, new_row)] ou None si squad sans figurine vivante.
    AUCUNE validation ici — voir validate_move_plan.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = squad_models.get(squad_id, [])  # get allowed
    alive_mids = [m for m in mids if m in models_cache]
    if not alive_mids:
        return None
    anchor_id = alive_mids[0]
    anchor_origin_col = int(models_cache[anchor_id]["col"])
    anchor_origin_row = int(models_cache[anchor_id]["row"])
    dest_col, dest_row = normalize_coordinates(int(anchor_dest_col), int(anchor_dest_row))
    dx = dest_col - anchor_origin_col
    dy = dest_row - anchor_origin_row
    plan: List[Tuple[str, int, int]] = []
    for mid in alive_mids:
        m = models_cache[mid]
        new_col, new_row = normalize_coordinates(int(m["col"]) + dx, int(m["row"]) + dy)
        plan.append((mid, new_col, new_row))
    return plan


def _validate_plan_coherency(
    plan_positions: Dict[str, Tuple[int, int]], game_state: Dict[str, Any]
) -> bool:
    """Verifie la coherency d un plan (positions hypothetiques, sans toucher caches).

    Meme regles que validate_squad_coherency : <=6 modeles → 1 voisin, >=7 → 2.
    """
    n = len(plan_positions)
    if n <= 1:
        return True
    coherency_dist = get_coherency_subhex(game_state)
    min_neighbors = 2 if n >= 7 else 1
    positions = list(plan_positions.values())
    for i, (ci, ri) in enumerate(positions):
        neighbors = 0
        for j, (cj, rj) in enumerate(positions):
            if i == j:
                continue
            if calculate_hex_distance(ci, ri, cj, rj) <= coherency_dist:
                neighbors += 1
                if neighbors >= min_neighbors:
                    break
        if neighbors < min_neighbors:
            return False
    return True


def validate_move_plan(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
) -> bool:
    """Verifie un plan multi-figurines en dry-run (aucune ecriture cache).

    Constraints (dict, defaut DEFAULT_MOVE_CONSTRAINTS) :
      - budget_per_model: int|None — distance hex max depuis position d origine
      - forbid_enemy_er: bool — interdit cellule dans ER d un ennemi
      - require_coherency: bool — coherency sur le plan final
      - allow_walls: bool — autorise traverser/finir sur un mur
      - allow_collisions: bool — autorise overlap avec autres escouades

    Validation atomique : un seul echec → False. Aucune ecriture.
    """
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    if not plan:
        return False

    models_cache = require_key(game_state, "models_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    first_model = models_cache.get(plan[0][0])
    if first_model is None:
        return False
    squad_id = str(first_model["squad_id"])
    player = int(first_model["player"])

    enemy_er_zone: Optional[Set[Tuple[int, int]]] = None
    if c["forbid_enemy_er"]:
        cache_key = f"enemy_adjacent_hexes_player_{player}"
        enemy_er_zone = require_key(game_state, cache_key)

    # Cellules occupees par les AUTRES escouades (collisions interdites).
    other_occupied: Set[Tuple[int, int]] = set()
    if not c["allow_collisions"]:
        units_cache = game_state.get("units_cache", {})  # get allowed
        for sid, entry in units_cache.items():
            if str(sid) == squad_id:
                continue
            occ = entry.get("occupied_hexes")
            if occ:
                for cell in occ:
                    other_occupied.add((int(cell[0]), int(cell[1])))

    # Budget per-model depuis position d origine actuelle.
    origin_positions: Dict[str, Tuple[int, int]] = {}
    if c["budget_per_model"] is not None:
        for mid, _, _ in plan:
            m = models_cache.get(mid)
            if m is None:
                return False
            origin_positions[mid] = (int(m["col"]), int(m["row"]))

    new_cells: Set[Tuple[int, int]] = set()
    for mid, nc, nr in plan:
        if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
            return False
        cell = (nc, nr)
        if not c["allow_walls"] and wall_hexes and cell in wall_hexes:
            return False
        if not c["allow_collisions"] and cell in other_occupied:
            return False
        if c["forbid_enemy_er"] and enemy_er_zone and cell in enemy_er_zone:
            return False
        if cell in new_cells:
            return False  # collision intra-plan (deux figs sur meme hex)
        new_cells.add(cell)
        if c["budget_per_model"] is not None:
            o_col, o_row = origin_positions[mid]
            if calculate_hex_distance(o_col, o_row, nc, nr) > int(c["budget_per_model"]):
                return False

    if c["require_coherency"]:
        plan_positions = {mid: (nc, nr) for mid, nc, nr in plan}
        if not _validate_plan_coherency(plan_positions, game_state):
            return False

    return True


def apply_snap_corrections(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    radius: int = 2,
    constraints: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, int, int]]:
    """Pour chaque figurine invalide individuellement, cherche un hex valide proche.

    Snap par-figurine sur contraintes locales (bounds, walls, collisions, enemy_er) —
    pas de garantie de coherency globale (responsabilite UX pour ajustement manuel).
    Ordre : par index de figurine dans le plan (deterministe).

    Recherche : anneaux concentriques de distance hex 1..radius autour de la destination
    invalide. Premier hex valide retenu (ordre balayage col puis row).

    Si aucun hex valide trouve dans le rayon, la figurine garde sa destination originale
    (l UX affichera le voile rouge).
    """
    c = dict(DEFAULT_MOVE_CONSTRAINTS)
    if constraints:
        c.update(constraints)
    c_individual = dict(c)
    c_individual["require_coherency"] = False

    corrected: List[Tuple[str, int, int]] = []
    for mid, nc, nr in plan:
        if validate_move_plan([(mid, nc, nr)], game_state, c_individual):
            corrected.append((mid, nc, nr))
            continue
        found_cell: Optional[Tuple[int, int]] = None
        for r in range(1, int(radius) + 1):
            for d_col in range(-r, r + 1):
                for d_row in range(-r, r + 1):
                    if max(abs(d_col), abs(d_row)) != r:
                        continue
                    cand_col, cand_row = nc + d_col, nr + d_row
                    if validate_move_plan([(mid, cand_col, cand_row)], game_state, c_individual):
                        found_cell = (cand_col, cand_row)
                        break
                if found_cell is not None:
                    break
            if found_cell is not None:
                break
        if found_cell is not None:
            corrected.append((mid, found_cell[0], found_cell[1]))
        else:
            corrected.append((mid, nc, nr))
    return corrected


def roll_advance_for_squad(squad_id: str, game_state: Dict[str, Any]) -> int:
    """Roll 1D6 partage par l escouade pour un Advance move.

    Stocke le resultat dans game_state["current_advance_roll"] pour les logs/replay,
    sera efface apres commit_move (responsabilite du caller).
    """
    import random
    roll = random.randint(1, 6)
    game_state["current_advance_roll"] = int(roll)
    return int(roll)


def get_squad_move_budget(
    squad_id: str,
    game_state: Dict[str, Any],
    move_type: str,
    advance_roll: Optional[int] = None,
) -> int:
    """Budget de deplacement par figurine (en subhexes) pour une escouade.

    - "normal" / "fall_back" → MOVE
    - "advance" → MOVE + advance_roll (caller doit fournir advance_roll)
    - "charge" / "pile_in" / "consolidation" → contraintes specifiques (PR2 2c / PR3)
      Pour pile_in/consolidation: 3 inches en subhexes.
      Pour charge: la valeur est charge_roll 2D6, caller la fournit via advance_roll
      (le parametre est polysemique : budget D6 partage par l escouade).

    MOVE est deja en subhexes dans le moteur (cf. game_state.py:118
    `"MOVE": config["MOVE"] * scale`).
    """
    valid_types = ("normal", "advance", "fall_back", "charge", "pile_in", "consolidation")
    if move_type not in valid_types:
        raise ValueError(f"get_squad_move_budget: invalid move_type {move_type!r}")
    if move_type in ("pile_in", "consolidation"):
        ish = int(require_key(game_state, "inches_to_subhex"))
        return 3 * ish
    units = game_state.get("units", [])  # get allowed
    unit = next((u for u in units if str(u.get("id")) == str(squad_id)), None)  # get allowed
    if unit is None:
        raise KeyError(f"get_squad_move_budget: squad {squad_id} not in game_state['units']")
    move_stat = int(require_key(unit, "MOVE"))
    if move_type == "advance":
        if advance_roll is None:
            raise ValueError("get_squad_move_budget: advance_roll required for move_type='advance'")
        return move_stat + int(advance_roll)
    if move_type == "charge":
        if advance_roll is None:
            raise ValueError("get_squad_move_budget: charge_roll (passed via advance_roll) required for move_type='charge'")
        # F5 fix (audit) : charge_roll est en POUCES (2D6), convertir en subhexes
        # pour rester coherent avec les autres move_types qui retournent subhexes.
        ish = int(require_key(game_state, "inches_to_subhex"))
        return int(advance_roll) * ish
    return move_stat  # normal, fall_back


def execute_squad_move(
    squad_id: str,
    anchor_dest_col: int,
    anchor_dest_row: int,
    move_type: str,
    game_state: Dict[str, Any],
    advance_roll: Optional[int] = None,
    extra_constraints: Optional[Dict[str, Any]] = None,
) -> bool:
    """Pipeline complet pour Normal/Advance/Fall Back: roll → plan → validate → commit.

    Pour move_type="advance" : si advance_roll est None, le helper roll lui-meme.
    Pour fall_back : aucun roll. Pour normal : aucun roll.

    Retourne True si le move a ete commit, False si la validation a echoue
    (aucune ecriture dans ce cas — transaction atomique).
    """
    if move_type == "advance" and advance_roll is None:
        advance_roll = roll_advance_for_squad(squad_id, game_state)
    plan = build_rigid_plan(anchor_dest_col, anchor_dest_row, squad_id, game_state)
    if plan is None:
        return False
    budget = get_squad_move_budget(squad_id, game_state, move_type, advance_roll=advance_roll)
    constraints: Dict[str, Any] = {"budget_per_model": budget}
    if extra_constraints:
        constraints.update(extra_constraints)
    if not validate_move_plan(plan, game_state, constraints):
        return False
    commit_move(plan, game_state, move_type)
    # Nettoyage du roll partage apres commit reussi (cf. spec).
    if move_type == "advance":
        game_state.pop("current_advance_roll", None)
    return True


# ============================================================================
# CHARGE PLAN (squad.md PR2 2c)
# ============================================================================


def _enemy_squad_ids(game_state: Dict[str, Any], player: int) -> List[str]:
    """Liste des squad_id ennemis vivants (player != donne)."""
    out: List[str] = []
    for sid, entry in game_state.get("units_cache", {}).items():  # get allowed
        try:
            if int(entry.get("player", -1)) != int(player):
                out.append(str(sid))
        except (TypeError, ValueError):
            continue
    return out


def _squad_model_positions(game_state: Dict[str, Any], squad_id: str) -> List[Tuple[int, int]]:
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    out: List[Tuple[int, int]] = []
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            out.append((int(m["col"]), int(m["row"])))
    return out


CHARGE_THRESHOLD_INCHES = 12


def charge_check_eligibility(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
) -> bool:
    """Verifie l eligibilite a charger (Regles officielles Charge Phase).

    - Au moins une figurine vivante du squad est a <= 12" d au moins une figurine
      ennemie (mesure figurine la plus proche, pas ancre).
    - Interdit si le squad est dans `units_advanced` ou `units_fled` ce tour.
    - Interdit si une figurine du squad est deja dans l ER d un ennemi (locked).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if not target_squad_ids:
        return False
    if str(squad_id) in game_state.get("units_advanced", set()):
        return False
    if str(squad_id) in game_state.get("units_fled", set()):
        return False
    our_positions = _squad_model_positions(game_state, squad_id)
    if not our_positions:
        return False
    ish = int(require_key(game_state, "inches_to_subhex"))
    er_dist = get_engagement_range_subhex(game_state)
    threshold_12 = CHARGE_THRESHOLD_INCHES * ish

    # Position ennemies (tous)
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_player = int(units_cache.get(str(squad_id), {}).get("player", -1))  # get allowed
    enemy_positions: List[Tuple[int, int]] = []
    for tsid in target_squad_ids:
        enemy_positions.extend(_squad_model_positions(game_state, str(tsid)))
    if not enemy_positions:
        return False
    # 12" check
    in_range = False
    for oc, orow in our_positions:
        for ec, er in enemy_positions:
            if calculate_hex_distance(oc, orow, ec, er) <= threshold_12:
                in_range = True
                break
        if in_range:
            break
    if not in_range:
        return False
    # Locked check (au moins une fig dans l ER d un ennemi quelconque)
    all_enemy_positions: List[Tuple[int, int]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        all_enemy_positions.extend(_squad_model_positions(game_state, esid))
    for oc, orow in our_positions:
        for ec, er in all_enemy_positions:
            if calculate_hex_distance(oc, orow, ec, er) <= er_dist:
                return False
    return True


def _hex_legal_for_charge(
    col: int,
    row: int,
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
) -> bool:
    """Cellule valide pour le placement d une figurine en cours de charge :
       - dans le plateau
       - pas un mur
       - pas occupee par une autre escouade (cible OU non) — collision physique
       - pas dans l ER d une escouade ennemie NON-cible (regle officielle)
    """
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())
    if col < 0 or row < 0 or col >= board_cols or row >= board_rows:
        return False
    cell = (col, row)
    if wall_hexes and cell in wall_hexes:
        return False
    # Collision : autres escouades (sauf nous-meme)
    units_cache = game_state.get("units_cache", {})  # get allowed
    for sid, entry in units_cache.items():
        if str(sid) == str(squad_id):
            continue
        occ = entry.get("occupied_hexes")
        if occ and cell in occ:
            return False
    # ER des escouades non-cibles
    our_player = int(units_cache.get(str(squad_id), {}).get("player", -1))  # get allowed
    er_dist = get_engagement_range_subhex(game_state)
    for esid in _enemy_squad_ids(game_state, our_player):
        if esid in [str(t) for t in target_squad_ids]:
            continue
        for ec, er in _squad_model_positions(game_state, esid):
            if calculate_hex_distance(col, row, ec, er) <= er_dist:
                return False
    return True


def charge_build_valid_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    target_squad_ids: List[str],
    charge_roll: int,
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan de charge multi-figurines (transaction atomique, aucune ecriture cache).

    Ordre de traitement : par index de figurine croissant.
    Pour chaque fig :
      (a) priorite : B2B avec un modele ennemi cible (hex hexagonalement adjacent)
      (b) sinon : se rapproche du cible le plus proche, hors ER des non-cibles
    Validation finale : TOUTES les figs finissent dans l ER d au moins un modele cible
    (regle officielle : charge legale exige ER apres deplacement). Coherency verifiee
    sur le plan final.

    Retourne le plan ou None si invalide (atomic : aucune fig deplacee).
    Le caller appelle commit_move(plan, gs, 'charge') sur succes.
    """
    if charge_roll <= 0:
        return None
    if not charge_check_eligibility(game_state, squad_id, target_squad_ids):
        return None
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    budget = int(charge_roll) * ish
    er_threshold = get_engagement_range_subhex(game_state)

    # Toutes les positions de figurines cibles
    target_positions: List[Tuple[int, int]] = []
    for tsid in target_squad_ids:
        target_positions.extend(_squad_model_positions(game_state, str(tsid)))
    if not target_positions:
        return None

    plan: List[Tuple[str, int, int]] = []
    occupied_after: Set[Tuple[int, int]] = set()  # cellules deja reservees par ce plan

    for mid in mids:
        m = models_cache[mid]
        orig_col, orig_row = int(m["col"]), int(m["row"])

        # (a) Tentative B2B : voisins immediats de chaque modele cible
        b2b_candidates: List[Tuple[int, int, int]] = []  # (dist_from_orig, col, row)
        for tc, tr in target_positions:
            for nc, nr in get_hex_neighbors(tc, tr):
                if (nc, nr) in occupied_after:
                    continue
                d_orig = calculate_hex_distance(orig_col, orig_row, nc, nr)
                if d_orig > budget:
                    continue
                if not _hex_legal_for_charge(nc, nr, game_state, squad_id, target_squad_ids):
                    continue
                b2b_candidates.append((d_orig, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_candidates:
            b2b_candidates.sort()  # plus proche d origine d abord
            _, pc, pr = b2b_candidates[0]
            picked = (pc, pr)
        else:
            # (b) Pas de B2B atteignable : avancer vers la cible la plus proche
            nearest_target = min(
                target_positions,
                key=lambda tp: calculate_hex_distance(orig_col, orig_row, tp[0], tp[1]),
            )
            tc, tr = nearest_target
            orig_dist_to_tgt = calculate_hex_distance(orig_col, orig_row, tc, tr)
            best_cand: Optional[Tuple[int, int, int]] = None  # (dist_to_target, col, row)
            for d in range(1, budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d:
                            continue
                        nc = orig_col + d_col
                        nr = orig_row + d_row
                        if (nc, nr) in occupied_after:
                            continue
                        if not _hex_legal_for_charge(nc, nr, game_state, squad_id, target_squad_ids):
                            continue
                        cand_d = calculate_hex_distance(nc, nr, tc, tr)
                        if cand_d >= orig_dist_to_tgt:
                            continue  # doit etre strictement plus proche
                        if best_cand is None or cand_d < best_cand[0]:
                            best_cand = (cand_d, nc, nr)
                if best_cand is not None:
                    break  # premier anneau utile retenu
            if best_cand is not None:
                _, pc, pr = best_cand
                picked = (pc, pr)
        if picked is None:
            return None  # cette fig ne peut bouger legalement → charge echouee
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale : ER pour chaque fig
    for mid, nc, nr in plan:
        in_er = any(
            calculate_hex_distance(nc, nr, tc, tr) <= er_threshold
            for tc, tr in target_positions
        )
        if not in_er:
            return None

    # Coherency finale
    plan_positions = {mid: (nc, nr) for mid, nc, nr in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None

    return plan


def commit_move(
    plan: List[Tuple[str, int, int]],
    game_state: Dict[str, Any],
    move_type: str,
) -> None:
    """Applique le plan complet en une passe et positionne les flags post-move.

    Pre-condition: plan validé via validate_move_plan (ce helper ne re-valide pas).
    Flags:
        "advance"   → units_advanced.add(squad_id)
        "fall_back" → units_fled.add(squad_id)
        "normal"/"charge"/"pile_in"/"consolidation" → aucun flag
    """
    valid_types = ("normal", "advance", "fall_back", "charge", "pile_in", "consolidation")
    if move_type not in valid_types:
        raise ValueError(
            f"commit_move: invalid move_type {move_type!r}, expected one of {valid_types}"
        )
    if not plan:
        return
    models_cache = require_key(game_state, "models_cache")
    first = models_cache.get(plan[0][0])
    if first is None:
        raise KeyError(f"commit_move: anchor model {plan[0][0]} not in models_cache")
    squad_id = str(first["squad_id"])
    for mid, nc, nr in plan:
        update_model_position(game_state, mid, nc, nr)
    if move_type == "advance":
        game_state.setdefault("units_advanced", set()).add(squad_id)
    elif move_type == "fall_back":
        game_state.setdefault("units_fled", set()).add(squad_id)
    elif move_type == "charge":
        game_state.setdefault("units_charged", set()).add(squad_id)


# ============================================================================
# PENDING INTENTS — SHOOT / FIGHT (squad.md PR3 3a)
# ============================================================================
# Structures de declaration-puis-resolution pour le tir et la melee multi-figs.
# Lifecycle :
#   - Cree lors de l activation de tir/fight (squad_shooting_unit_activation_start /
#     squad_fight_unit_activation_start).
#   - Nettoye par end_activation (responsabilite du caller) — assertion en debug
#     si pending existe deja au debut d une nouvelle activation.
#   - Jamais persiste entre deux activations.


def init_pending_intents(game_state: Dict[str, Any]) -> None:
    """Initialise les dicts pending si absents. Idempotent (safe re-call)."""
    game_state.setdefault("pending_squad_shoot_intents", {})
    game_state.setdefault("pending_squad_fight_intents", {})


def assert_no_pending_shoot_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Leve si pending_squad_shoot_intents[squad_id] existe deja.

    A appeler au debut de squad_shooting_unit_activation_start : un pending
    persistant signale un bug (activation precedente non nettoyee).
    """
    init_pending_intents(game_state)
    if squad_id in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"pending_squad_shoot_intents[{squad_id!r}] already exists at activation start — "
            f"previous activation was not cleaned by end_activation"
        )


def assert_no_pending_fight_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Leve si pending_squad_fight_intents[squad_id] existe deja."""
    init_pending_intents(game_state)
    if squad_id in game_state["pending_squad_fight_intents"]:
        raise RuntimeError(
            f"pending_squad_fight_intents[{squad_id!r}] already exists at activation start"
        )


def clear_pending_shoot_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Supprime le pending d une escouade (succes OU annulation d activation)."""
    init_pending_intents(game_state)
    game_state["pending_squad_shoot_intents"].pop(squad_id, None)


def clear_pending_fight_intent(game_state: Dict[str, Any], squad_id: str) -> None:
    """Supprime le pending d une escouade (succes OU annulation d activation)."""
    init_pending_intents(game_state)
    game_state["pending_squad_fight_intents"].pop(squad_id, None)


def reset_wounds_allocated_for_squad(game_state: Dict[str, Any], squad_id: str) -> None:
    """Reset wounds_allocated_this_activation sur toutes les figs vivantes d une escouade.

    Appele au moment de la declaration de cible (par activation attaquante)
    sur l ESCOUADE CIBLE. NE PAS reset sur toutes les escouades du jeu —
    scope per-activation par-cible (cf. spec §"Allocation prioritaire").
    """
    models_cache = require_key(game_state, "models_cache")
    for mid in game_state.get("squad_models", {}).get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            m["wounds_allocated_this_activation"] = 0


# ============================================================================
# SQUAD SHOOTING — declaration / lock (squad.md PR3 3b)
# ============================================================================
# Pipeline parallele: ces fonctions s invoquent independamment du shoot flow
# existant. Le decoder mono-fig est preserve. Branchement RL en PR4.


def squad_shooting_unit_activation_start(
    game_state: Dict[str, Any], squad_id: str
) -> None:
    """Initialise l activation tir d une escouade.

    - Verifie pas de pending leftover (bug detection).
    - Initialise pending_squad_shoot_intents[squad_id] = [].
    - Reset SHOOT_LEFT par fig selon l arme RNG selectionnee (NB).

    Reset de wounds_allocated_this_activation : NON ici — fait au moment de la
    declaration de cible (squad_declare_shoot), scope par-cible.
    """
    assert_no_pending_shoot_intent(game_state, squad_id)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get("RNG_WEAPONS", [])  # get allowed
        sel = m.get("selectedRngWeaponIndex")
        if weapons and sel is not None and 0 <= int(sel) < len(weapons):
            w = weapons[int(sel)]
            if isinstance(w, dict) and "NB" in w:
                m["SHOOT_LEFT"] = resolve_dice_value(w["NB"], f"squad_shoot_init_{mid}")
            else:
                m["SHOOT_LEFT"] = 0
        else:
            m["SHOOT_LEFT"] = 0
    game_state["pending_squad_shoot_intents"][squad_id] = []


def _model_can_shoot_target(
    game_state: Dict[str, Any], attacker_model: Dict[str, Any], target_squad_id: str
) -> bool:
    """Eligibilite d une figurine attaquante a tirer sur une escouade cible.

    Per-fig (squad.md §"LOS cache — strategie avec escouades") : la cible est
    eligible si AU MOINS UNE figurine cible est a la fois a portee de l arme
    selectionnee ET visible (LoS murs) depuis la position de la figurine
    attaquante. La LoS est testee figurine -> figurine cible, pas ancre -> ancre.

    Conditions :
      - attaquant a SHOOT_LEFT > 0
      - arme RNG selectionnee existe avec RNG > 0
      - au moins un modele cible dans le rayon RNG (subhexes) ET avec LoS depuis l attaquant
    """
    if int(attacker_model.get("SHOOT_LEFT", 0)) <= 0:  # get allowed
        return False
    weapons = attacker_model.get("RNG_WEAPONS", [])  # get allowed
    sel = attacker_model.get("selectedRngWeaponIndex")
    if not weapons or sel is None or not (0 <= int(sel) < len(weapons)):
        return False
    weapon = weapons[int(sel)]
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return False
    # weapon["RNG"] est DEJA en subhexes (conv. existant code, cf. shooting_handlers.py:726)
    range_subhex = int(weapon["RNG"])
    if range_subhex <= 0:
        return False
    # Import lazy : shooting_handlers importe shared_utils (eviter le cycle).
    from engine.phase_handlers.shooting_handlers import _get_los_visibility_state
    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    for tc, tr in _squad_model_positions(game_state, target_squad_id):
        if calculate_hex_distance(ac, ar, tc, tr) > range_subhex:
            continue
        _, can_see, _ = _get_los_visibility_state(game_state, ac, ar, tc, tr)
        if can_see:
            return True
    return False


def squad_declare_shoot(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    priority_target_squad_id: str,
    eligible_target_slots: List[str],
) -> List[Dict[str, Any]]:
    """Construit les declarations de tir pour une escouade (per-fig).

    Logique de selection par fig (par index croissant) :
      1. Si la fig peut tirer sur la cible prioritaire → declare sur la cible prioritaire.
      2. Sinon, prend le premier slot (par ordre `eligible_target_slots`) ou la fig
         peut tirer.
      3. Sinon, fig ne tire pas (pas d entree dans intents).

    Au premier tir declare sur une cible donnee : `reset_wounds_allocated_for_squad`
    sur cette cible (scope per-cible par-activation).

    Capture `target_squad_size_at_declaration` (taille de l escouade cible au
    moment de la declaration) — utilise pour BLAST bonus en resolution.

    Returns la liste des intents (aussi stockee dans pending_squad_shoot_intents).

    PR3 3b : pas de TTK residual (defere a PR3 3c ou PR4 — sans TTK, plusieurs
    figs peuvent overkill une meme cible). Spec : overkill = signal implicite
    (attaques perdues), pas de penalite explicite.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"squad_declare_shoot called before squad_shooting_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )

    intents: List[Dict[str, Any]] = game_state["pending_squad_shoot_intents"][attacker_squad_id]
    reset_targets: Set[str] = set()

    def _maybe_reset_target_wounds(target_sid: str) -> None:
        if target_sid not in reset_targets:
            reset_wounds_allocated_for_squad(game_state, target_sid)
            reset_targets.add(target_sid)

    def _target_size(target_sid: str) -> int:
        return sum(
            1 for mid in squad_models.get(target_sid, []) if mid in models_cache  # get allowed
        )

    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        chosen_target: Optional[str] = None
        if _model_can_shoot_target(game_state, m, priority_target_squad_id):
            chosen_target = priority_target_squad_id
        else:
            for slot_sid in eligible_target_slots:
                if slot_sid == priority_target_squad_id:
                    continue
                if _model_can_shoot_target(game_state, m, slot_sid):
                    chosen_target = slot_sid
                    break
        if chosen_target is None:
            continue  # fig bloquee, ne tire pas
        _maybe_reset_target_wounds(chosen_target)
        sel = m.get("selectedRngWeaponIndex")
        weapon_idx = int(sel) if sel is not None else 0
        # F3 fix (audit) : resoudre NB UNE SEULE FOIS a la declaration, stocker
        # dans l intent. Sinon le double-roll de_resolve_squad_shoot decouple le
        # nombre d attaques effectif de SHOOT_LEFT pour les armes a NB variable (D3/D6).
        weapons = m.get("RNG_WEAPONS", [])  # get allowed
        n_attacks_resolved = 0
        if 0 <= weapon_idx < len(weapons):
            w = weapons[weapon_idx]
            if isinstance(w, dict) and "NB" in w:
                try:
                    n_attacks_resolved = int(resolve_dice_value(w["NB"], f"squad_declare_shoot_NB_{mid}"))
                except Exception:
                    n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
        intents.append({
            "model_id": mid,
            "weapon_index": weapon_idx,
            "target_unit_id": chosen_target,
            "target_squad_size_at_declaration": _target_size(chosen_target),
            "n_attacks_resolved": n_attacks_resolved,
        })
    return intents


def squad_declare_shoot_model(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d une seule figurine (flux PvP humain).

    Contrairement a squad_declare_shoot (auto : cible prioritaire -> per-fig), le
    joueur assigne explicitement la cible d UNE figurine. Re-appeler avec un
    model_id deja declare REMPLACE sa cible (le joueur change d avis).

    Validation stricte (pas de valeur par défaut) :
      - activation tir demarree (pending initialise),
      - figurine appartient a l escouade attaquante et vivante,
      - escouade cible vivante,
      - la figurine peut tirer la cible (portee + LoS, _model_can_shoot_target).

    Reset wounds_allocated sur la cible a la PREMIERE declaration de l escouade
    sur cette cible (scope per-cible par-activation, mirroir de squad_declare_shoot).

    Returns l intent cree (pour feedback frontend).
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"squad_declare_shoot_model called before squad_shooting_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )
    if attacker_model_id not in squad_models.get(attacker_squad_id, []):  # get allowed
        raise ValueError(
            f"Model {attacker_model_id!r} not in squad {attacker_squad_id!r}"
        )
    m = models_cache.get(attacker_model_id)
    if m is None:
        raise ValueError(f"Model {attacker_model_id!r} not alive (absent de models_cache)")
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        raise ValueError(f"Target squad {target_squad_id!r} not alive")
    if not _model_can_shoot_target(game_state, m, target_squad_id):
        raise ValueError(
            f"Model {attacker_model_id!r} cannot shoot target {target_squad_id!r} "
            f"(hors portee ou pas de LoS)"
        )

    sel = m.get("selectedRngWeaponIndex")
    weapon_idx = int(sel) if sel is not None else 0

    intents: List[Dict[str, Any]] = game_state["pending_squad_shoot_intents"][attacker_squad_id]
    # Remplace la declaration existante de cette figurine POUR CETTE ARME (split fire :
    # une fig peut tirer plusieurs de ses armes sur des cibles differentes -> cle (model, arme)).
    intents[:] = [
        i for i in intents
        if not (i.get("model_id") == attacker_model_id and int(i.get("weapon_index", -1)) == weapon_idx)
    ]
    # Premiere declaration de l escouade sur cette cible -> reset wounds cible.
    if not any(str(i.get("target_unit_id")) == str(target_squad_id) for i in intents):
        reset_wounds_allocated_for_squad(game_state, target_squad_id)

    weapons = m.get("RNG_WEAPONS", [])  # get allowed
    n_attacks_resolved = 0
    if 0 <= weapon_idx < len(weapons):
        w = weapons[weapon_idx]
        if isinstance(w, dict) and "NB" in w:
            try:
                n_attacks_resolved = int(
                    resolve_dice_value(w["NB"], f"squad_declare_shoot_model_NB_{attacker_model_id}")
                )
            except Exception:
                n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    intent = {
        "model_id": attacker_model_id,
        "weapon_index": weapon_idx,
        "target_unit_id": target_squad_id,
        "target_squad_size_at_declaration": target_size,
        "n_attacks_resolved": n_attacks_resolved,
    }
    intents.append(intent)
    return intent


def squad_model_valid_targets(
    game_state: Dict[str, Any], attacker_squad_id: str, attacker_model_id: str
) -> List[str]:
    """Liste des escouades ennemies qu UNE figurine peut cibler (portee + LoS).

    Reutilise _model_can_shoot_target (meme eligibilite que squad_declare_shoot_model).
    Sert a alimenter le HP blink frontend pour la fig selectionnee (cibles valides
    clignotent, les autres sont grisees) — meme mecanisme que l activation legacy.

    Returns une liste de squad_id ennemis (str), vide si la fig ne peut rien viser.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    m = models_cache.get(attacker_model_id)
    if m is None:
        raise ValueError(f"Model {attacker_model_id!r} not alive (absent de models_cache)")
    attacker_player = int(m["player"])
    valid: List[str] = []
    for sid, mids in squad_models.items():
        if sid == attacker_squad_id:
            continue
        first = next((mid for mid in mids if mid in models_cache), None)
        if first is None:
            continue  # escouade morte
        if int(models_cache[first]["player"]) == attacker_player:
            continue  # allie
        if _model_can_shoot_target(game_state, m, sid):
            valid.append(sid)
    return valid


def squad_undeclare_shoot_model(
    game_state: Dict[str, Any], attacker_squad_id: str, attacker_model_id: str
) -> bool:
    """Retire la declaration d une figurine (flux PvP humain : le joueur deselectionne).

    Returns True si une declaration a ete retiree, False sinon.
    """
    init_pending_intents(game_state)
    intents = game_state["pending_squad_shoot_intents"].get(attacker_squad_id)
    if not intents:
        return False
    before = len(intents)
    intents[:] = [i for i in intents if i.get("model_id") != attacker_model_id]
    return len(intents) < before


# ============================================================================
# SQUAD SHOOTING — assignation PAR ARME (split fire PvP humain)
# ============================================================================
# Le flux par-figurine ci-dessus assigne 1 cible par figurine (arme selectionnee).
# Le flux par-arme ci-dessous assigne l ARME au niveau de l ESCOUADE : choisir
# l arme W dans le menu puis cliquer une cible T => toutes les figs portant W
# tirent W sur T. Intents indexes par (model_id, weapon_index) : une fig peut
# donc tirer plusieurs de ses armes sur des cibles differentes (split fire).
# Marche pour mono ET multi-figurine (mono = squad d 1 modele).


def _model_can_shoot_target_with_weapon(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    target_squad_id: str,
    weapon_index: int,
) -> bool:
    """Eligibilite per-arme : la fig peut tirer l arme `weapon_index` sur la cible.

    Contrairement a _model_can_shoot_target (arme selectionnee + SHOOT_LEFT > 0),
    teste une arme PRECISE (portee + LoS) sans gater sur SHOOT_LEFT : en 10e une
    figurine tire CHACUNE de ses armes une fois (split fire), SHOOT_LEFT etant le
    NB d une seule arme et donc inadapte comme garde multi-armes.
    """
    weapons = attacker_model.get("RNG_WEAPONS", [])  # get allowed
    if not (0 <= int(weapon_index) < len(weapons)):
        return False
    weapon = weapons[int(weapon_index)]
    if not isinstance(weapon, dict) or "RNG" not in weapon:
        return False
    # weapon["RNG"] est DEJA en subhexes (cf. _model_can_shoot_target).
    range_subhex = int(weapon["RNG"])
    if range_subhex <= 0:
        return False
    from engine.phase_handlers.shooting_handlers import _get_los_visibility_state
    ac = int(attacker_model["col"])
    ar = int(attacker_model["row"])
    for tc, tr in _squad_model_positions(game_state, target_squad_id):
        if calculate_hex_distance(ac, ar, tc, tr) > range_subhex:
            continue
        _, can_see, _ = _get_los_visibility_state(game_state, ac, ar, tc, tr)
        if can_see:
            return True
    return False


def squad_declare_shoot_weapon(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    weapon_index: int,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Assigne l arme `weapon_index` (niveau escouade) a la cible.

    Pour CHAQUE figurine vivante de l escouade qui possede cette arme et peut
    tirer la cible (portee + LoS), cree un intent (model_id, weapon_index) -> T.
    Re-appeler avec la meme arme REMPLACE la cible (retire d abord tous les
    intents de cette arme, toutes figs confondues).

    Reset wounds_allocated sur la cible a la PREMIERE declaration de l escouade
    sur cette cible (scope per-cible par-activation, mirroir squad_declare_shoot).

    Validation stricte (pas de valeur par defaut) :
      - activation tir demarree (pending initialise),
      - escouade cible vivante,
      - au moins une figurine peut tirer l arme sur la cible (sinon ValueError).

    Returns la liste des intents crees pour cette arme.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_shoot_intents"]:
        raise RuntimeError(
            f"squad_declare_shoot_weapon called before squad_shooting_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )
    if target_squad_id not in squad_models or not any(
        mid in models_cache for mid in squad_models.get(target_squad_id, [])  # get allowed
    ):
        raise ValueError(f"Target squad {target_squad_id!r} not alive")

    intents: List[Dict[str, Any]] = game_state["pending_squad_shoot_intents"][attacker_squad_id]
    widx = int(weapon_index)
    # Remplace toute declaration existante de CETTE arme (changement de cible).
    intents[:] = [i for i in intents if int(i.get("weapon_index", -1)) != widx]
    # Premiere declaration de l escouade sur cette cible -> reset wounds cible.
    if not any(str(i.get("target_unit_id")) == str(target_squad_id) for i in intents):
        reset_wounds_allocated_for_squad(game_state, target_squad_id)

    target_size = sum(
        1 for mid in squad_models.get(target_squad_id, []) if mid in models_cache  # get allowed
    )
    created: List[Dict[str, Any]] = []
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        if not _model_can_shoot_target_with_weapon(game_state, m, target_squad_id, widx):
            continue
        weapons = m.get("RNG_WEAPONS", [])  # get allowed
        w = weapons[widx]
        n_attacks_resolved = 0
        if isinstance(w, dict) and "NB" in w:
            try:
                n_attacks_resolved = int(
                    resolve_dice_value(w["NB"], f"squad_declare_shoot_weapon_NB_{mid}_{widx}")
                )
            except Exception:
                n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
        intent = {
            "model_id": mid,
            "weapon_index": widx,
            "target_unit_id": target_squad_id,
            "target_squad_size_at_declaration": target_size,
            "n_attacks_resolved": n_attacks_resolved,
        }
        intents.append(intent)
        created.append(intent)
    if not created:
        raise ValueError(
            f"Aucune figurine de {attacker_squad_id!r} ne peut tirer l arme {widx} "
            f"sur {target_squad_id!r} (hors portee ou pas de LoS)"
        )
    return created


def squad_undeclare_shoot_weapon(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_index: int
) -> bool:
    """Retire toutes les declarations de l arme `weapon_index`. Returns True si retire."""
    init_pending_intents(game_state)
    intents = game_state["pending_squad_shoot_intents"].get(attacker_squad_id)
    if not intents:
        return False
    widx = int(weapon_index)
    before = len(intents)
    intents[:] = [i for i in intents if int(i.get("weapon_index", -1)) != widx]
    return len(intents) < before


def squad_weapon_valid_targets(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_index: int
) -> List[str]:
    """Escouades ennemies qu AU MOINS UNE figurine peut viser avec l arme `weapon_index`.

    Reutilise _model_can_shoot_target_with_weapon (meme eligibilite que la
    declaration par-arme). Alimente le HP blink frontend pour l arme active.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    attacker_player: Optional[int] = None
    for mid in squad_models.get(attacker_squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is not None:
            attacker_player = int(m["player"])
            break
    if attacker_player is None:
        return []
    valid: List[str] = []
    for sid, mids in squad_models.items():
        if sid == attacker_squad_id:
            continue
        first = next((mid for mid in mids if mid in models_cache), None)
        if first is None:
            continue  # escouade morte
        if int(models_cache[first]["player"]) == attacker_player:
            continue  # allie
        if any(
            _model_can_shoot_target_with_weapon(game_state, models_cache[amid], sid, weapon_index)
            for amid in squad_models.get(attacker_squad_id, [])  # get allowed
            if amid in models_cache
        ):
            valid.append(sid)
    return valid


def squad_lock_shoot(game_state: Dict[str, Any], squad_id: str) -> List[Dict[str, Any]]:
    """Verrouille les declarations (lecture seule jusqu a resolution).

    PR3 3b : pas de flag explicite — la convention est que toute modification de
    pending_squad_shoot_intents[squad_id] apres ce call est un bug. La resolution
    (PR3 3c) lit ce dict et le nettoie via clear_pending_shoot_intent en fin.
    Retourne la liste verrouillee pour usage immediat par la resolution.
    """
    init_pending_intents(game_state)
    return list(game_state["pending_squad_shoot_intents"].get(squad_id, []))  # get allowed


# ============================================================================
# SQUAD SHOOTING — resolution (squad.md PR3 3c)
# ============================================================================
# Hit → Wound → Save → Damage. Allocation prioritaire. Damage excess perdu.
# BLAST bonus selon taille cible a la declaration. Fig morte mid-resolution
# (attaquante : ses attaques restantes annulees ; cible : voir allocation).


def wound_threshold(strength: int, toughness: int) -> int:
    """Seuil 1D6 pour blesser selon table W40K 10e :
       S >= 2T : 2+
       S > T (et pas >= 2T) : 3+
       S == T : 4+
       S < T (et pas <= T/2) : 5+
       S <= T/2 : 6+
    """
    s = int(strength); t = int(toughness)
    if s >= 2 * t:
        return 2
    if 2 * s <= t:
        return 6
    if s > t:
        return 3
    if s == t:
        return 4
    return 5


def save_threshold(armor_save: int, invul_save: int, ap: int) -> int:
    """Meilleur des deux sauvegardes (Sv degrade par AP vs Invul ignore AP).

    Convention W40K (alignee shooting_handlers.py:6873) : AP est NEGATIF (ex: -1, -2).
    AP -1 sur Sv 3+ → effective = 3 - (-1) = 4 (save degradee a 4+).
    invul_save == 7 = pas d invul (sentinel).
    """
    effective_armor = int(armor_save) - int(ap)
    inv = int(invul_save)
    if inv < 7 and inv < effective_armor:
        return inv
    return effective_armor


def _has_blast_keyword(weapon: Dict[str, Any]) -> bool:
    kws = weapon.get("KEYWORDS") or weapon.get("keywords") or []
    if isinstance(kws, list):
        return any(str(k).upper() == "BLAST" for k in kws)
    if isinstance(kws, str):
        return "BLAST" in kws.upper()
    return False


def _allocate_damage_to_squad(
    game_state: Dict[str, Any], target_squad_id: str, damage: int
) -> Optional[Dict[str, Any]]:
    """Applique `damage` HP a une figurine vivante du squad selon allocation prioritaire.

    Priorite (regle officielle simplifiee per-activation) :
      1. Premier modele vivant avec wounds_allocated_this_activation > 0.
      2. Sinon : premier modele vivant par ordre d index.
    Damage excess (> HP_CUR du modele) perdu — pas de carry-over.
    Si le modele est tue → destroy_model(reason='combat').
    Sinon → update_model_hp + increment wounds_allocated_this_activation.

    Returns {model_id, damage_dealt, destroyed} ou None si pas de cible vivante.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [m for m in squad_models.get(target_squad_id, []) if m in models_cache]  # get allowed
    if not alive:
        return None
    target_mid: Optional[str] = None
    for mid in alive:
        if int(models_cache[mid].get("wounds_allocated_this_activation", 0)) > 0:  # get allowed
            target_mid = mid
            break
    if target_mid is None:
        target_mid = alive[0]
    assert target_mid is not None
    m = models_cache[target_mid]
    hp_before = int(m["HP_CUR"])
    target_points_per_hp = float(require_key(m, "points_per_hp"))
    target_player = int(require_key(m, "player"))
    damage_dealt = min(int(damage), hp_before)
    new_hp = hp_before - damage_dealt
    destroyed = False
    if new_hp <= 0:
        # F4 cleanup (audit) : pas d incrementation wounds_allocated_this_activation
        # avant destroy — la fig est immediatement detachee du cache, l ecriture
        # serait un no-op silencieux.
        destroy_model(game_state, target_mid, reason="combat")
        destroyed = True
    else:
        m["wounds_allocated_this_activation"] = int(m.get("wounds_allocated_this_activation", 0)) + damage_dealt  # get allowed
        update_model_hp(game_state, target_mid, new_hp)
    return {
        "model_id": target_mid, "damage_dealt": damage_dealt, "destroyed": destroyed,
        "points_per_hp": target_points_per_hp, "target_player": target_player,
    }


def resolve_squad_shoot(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Resout toutes les declarations de pending_squad_shoot_intents[attacker_squad_id].

    Sequence par attaque :
      1. Hit roll (1D6 vs BS de l attaquant)
      2. Wound roll (table S vs T)
      3. Save roll (best of Sv+AP vs Invul)
      4. Damage : allocation prioritaire, excess perdu

    BLAST bonus : si l arme a keyword BLAST, +1 attaque par tranche de 5 figs
    dans la taille cible AU MOMENT DE LA DECLARATION (capture dans l intent).

    Fig attaquante morte mid-resolution : ses attaques restantes (et celles
    declarees mais non encore resolues) sont annulees — l intent est skip si
    le modele attaquant n existe plus dans models_cache.
    Fig cible morte mid-resolution : pas de carry-over, allocation_prioritaire
    sur prochaine vivante de la cible.

    Nettoie pending_squad_shoot_intents[attacker_squad_id] en fin (succes OU echec).

    Returns un summary dict pour log/debug.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = list(game_state["pending_squad_shoot_intents"].get(attacker_squad_id, []))  # get allowed
    summary: Dict[str, Any] = {
        "attacks_made": 0,
        "hits": 0,
        "wounds": 0,
        "failed_saves": 0,
        "damage_total": 0,
        "models_killed": 0,
        "events": [],
    }
    targets_meta: Dict[str, Dict[str, Any]] = {}
    # Accumulation par (weapon_name, target_sid) pour émettre 1 log par arme par escouade
    weapon_groups: Dict[tuple, Dict[str, Any]] = {}
    import random
    for intent in intents:
        attacker_mid = intent["model_id"]
        attacker = models_cache.get(attacker_mid)
        if attacker is None:
            continue  # fig morte mid-resolution
        target_sid = str(intent["target_unit_id"])
        if target_sid not in game_state.get("squad_models", {}):  # get allowed
            continue  # cible deja wipe
        if target_sid not in targets_meta:
            _tgt_uc = require_key(game_state, "units_cache")[target_sid]
            _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
            targets_meta[target_sid] = {
                "value": float(require_key(_tgt_uc, "VALUE")),
                "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
                "player": int(require_key(_tgt_uc, "player")),
            }
        weapon_index = int(intent.get("weapon_index", 0))  # get allowed
        weapons = attacker.get("RNG_WEAPONS", [])  # get allowed
        if not (0 <= weapon_index < len(weapons)):
            continue
        weapon = weapons[weapon_index]
        if not isinstance(weapon, dict):
            continue
        # F3 fix (audit) : lire n_attacks_resolved depuis l intent (resolu a la
        # declaration). Re-roll de NB si absent (compat legacy intents).
        if "n_attacks_resolved" in intent:
            n_attacks = int(intent["n_attacks_resolved"])
        else:
            nb_raw = weapon.get("NB", 1)
            try:
                n_attacks = resolve_dice_value(nb_raw, f"squad_shoot_attacks_{attacker_mid}")
            except Exception:
                n_attacks = int(nb_raw) if isinstance(nb_raw, (int, float)) else 1
        if _has_blast_keyword(weapon):
            tgt_size = int(intent.get("target_squad_size_at_declaration", 0))  # get allowed
            n_attacks += tgt_size // 5
        if n_attacks <= 0:
            continue
        # Convention moteur (cf. shooting_handlers.py:3010-3011, 6683, 6748) :
        # weapon["ATK"] = seuil hit (BS/WS), weapon["STR"] = force, weapon["AP"] = AP modifier
        bs = int(weapon.get("ATK", weapon.get("BS", 4)))
        strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
        ap = int(weapon.get("AP", 0))  # get allowed
        dmg_raw = weapon.get("DMG", 1)
        wound_th_lookup: Dict[int, int] = {}  # cache wound threshold by T

        # Pré-calcul des seuils pour l'affichage (Hit/Wound/Save)
        _pre_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
        display_wth = 0
        display_save_th = 0
        if _pre_alive:
            _pre_tgt = models_cache[_pre_alive[0]]
            display_wth = wound_threshold(strength, int(_pre_tgt["T"]))
            display_save_th = save_threshold(int(_pre_tgt["ARMOR_SAVE"]), int(_pre_tgt.get("INVUL_SAVE", 7)), ap)

        intent_attacks = 0
        intent_hits = 0
        intent_wounds = 0
        intent_failed_saves = 0
        intent_damage = 0
        intent_kills = 0
        killed_model_ids: List[str] = []

        for _ in range(int(n_attacks)):
            # Recheck cible alive et attaquant alive avant chaque attaque
            if attacker_mid not in models_cache:
                break
            target_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
            if not target_alive:
                break
            summary["attacks_made"] += 1
            intent_attacks += 1
            # 1. Hit roll
            hit_roll = random.randint(1, 6)
            if hit_roll == 1:  # 1 always miss (regle 10e)
                continue
            if hit_roll < bs:
                continue
            summary["hits"] += 1
            intent_hits += 1
            # 2. Wound roll — utilise T de la fig "allocation prioritaire" (proxy : 1ere vivante)
            first_alive = models_cache[target_alive[0]]
            t_target = int(first_alive["T"])
            wth = wound_th_lookup.get(t_target)
            if wth is None:
                wth = wound_threshold(strength, t_target)
                wound_th_lookup[t_target] = wth
            wound_roll = random.randint(1, 6)
            if wound_roll == 1:  # 1 always fail
                continue
            if wound_roll < wth:
                continue
            summary["wounds"] += 1
            intent_wounds += 1
            # 3. Save roll — meme cible (allocation prioritaire dans _allocate_damage_to_squad)
            sv = int(first_alive["ARMOR_SAVE"])
            invul = int(first_alive.get("INVUL_SAVE", 7))
            save_th = save_threshold(sv, invul, ap)
            save_roll = random.randint(1, 6)
            if save_roll != 1 and save_roll >= save_th:
                continue  # save reussi
            summary["failed_saves"] += 1
            intent_failed_saves += 1
            # 4. Damage
            try:
                dmg = resolve_dice_value(cast(DiceValue, dmg_raw), f"squad_shoot_dmg_{attacker_mid}")
            except Exception:
                dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
            if dmg <= 0:
                continue
            res = _allocate_damage_to_squad(game_state, target_sid, dmg)
            if res is None:
                break  # cible wipe
            summary["damage_total"] += int(res["damage_dealt"])
            intent_damage += int(res["damage_dealt"])
            if res["destroyed"]:
                summary["models_killed"] += 1
                intent_kills += 1
                killed_model_ids.append(str(res["model_id"]))
            summary["events"].append({
                "attacker": attacker_mid, "target": res["model_id"],
                "target_squad_id": target_sid,
                "target_player": int(res["target_player"]),
                "points_per_hp": float(res["points_per_hp"]),
                "damage": int(res["damage_dealt"]), "destroyed": bool(res["destroyed"]),
            })
        # Apres toutes les attaques de cet intent, decrement SHOOT_LEFT du modele attaquant
        if attacker_mid in models_cache:
            sl = int(models_cache[attacker_mid].get("SHOOT_LEFT", 0))  # get allowed
            models_cache[attacker_mid]["SHOOT_LEFT"] = max(0, sl - 1)

        # Accumulation par groupe (weapon, target) — log émis après la boucle
        if intent_attacks > 0:
            weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))
            group_key = (weapon_name, target_sid)
            if group_key not in weapon_groups:
                weapon_groups[group_key] = {
                    "attacker_squad_id": str(attacker.get("squad_id", attacker_mid)),
                    "weapon_name": weapon_name,
                    "target_sid": target_sid,
                    "bs": bs,
                    "display_wth": display_wth,
                    "display_save_th": display_save_th,
                    "player": int(attacker.get("player", 0)),  # get allowed
                    "attacks": 0,
                    "damage": 0,
                    "kills": 0,
                    "killed_model_ids": [],
                }
            g = weapon_groups[group_key]
            g["attacks"] += intent_attacks
            g["damage"] += intent_damage
            g["kills"] += intent_kills
            g["killed_model_ids"].extend(killed_model_ids)

    # Emit 1 log par groupe (weapon, target) pour toute l'escouade
    for (weapon_name_g, target_sid_g), g in weapon_groups.items():
        attacker_squad_id_str = g["attacker_squad_id"]
        sq_uc = game_state.get("units_cache", {}).get(attacker_squad_id_str, {})  # get allowed
        tgt_uc = game_state.get("units_cache", {}).get(target_sid_g, {})  # get allowed
        ac = int(sq_uc.get("col", 0))  # get allowed
        ar = int(sq_uc.get("row", 0))  # get allowed
        tc = int(tgt_uc.get("col", 0))  # get allowed
        tr = int(tgt_uc.get("row", 0))  # get allowed
        weapon_suffix = f" [{weapon_name_g}]" if weapon_name_g else ""
        attack_log = (
            f"Shots:{g['attacks']} - "
            f"Hit:{g['bs']}+ Wound:{g['display_wth']}+ Save:{g['display_save_th']}+ - "
            f"HP lost:{g['damage']} Killed:{g['kills']}"
        )
        msg = (
            f"Unit {attacker_squad_id_str}({ac},{ar}) SHOT"
            f" at Unit {target_sid_g}({tc},{tr}){weapon_suffix}"
            f" - {attack_log}"
        )
        append_action_log(game_state, {
            "type": "shoot",
            "message": msg,
            "turn": game_state.get("turn", 0),  # get allowed
            "phase": "shoot",
            "shooterId": attacker_squad_id_str,
            "targetId": target_sid_g,
            "weaponName": weapon_name_g if weapon_name_g else None,
            "player": g["player"],
            "shooterCol": ac,
            "shooterRow": ar,
            "targetCol": tc,
            "targetRow": tr,
            "damage": g["damage"],
            "target_died": g["kills"] > 0,
            "timestamp": "server_time",
            "is_ai_action": g["player"] == 1,
        })
        # for dead_mid in g["killed_model_ids"]:
        #     append_action_log(game_state, {
        #         "type": "death",
        #         #"message": f"Unit {target_sid_g} model {dead_mid} DESTROYED",
        #         "turn": game_state.get("turn", 0),
        #         "phase": "shoot",
        #         "targetId": target_sid_g,
        #         "unitId": target_sid_g,
        #         "player": int(tgt_uc.get("player", 0)),
        #         "timestamp": "server_time",
        #     })

    # Meta cibles + escouades wipe (pour reward shaping proportionnel)
    summary["targets_meta"] = targets_meta
    summary["squads_wiped"] = [
        sid for sid in targets_meta
        if not [m for m in game_state["squad_models"].get(sid, []) if m in models_cache]  # get allowed
    ]
    # Nettoyage atomique
    clear_pending_shoot_intent(game_state, attacker_squad_id)
    return summary


# ============================================================================
# SQUAD FIGHT — activation start + ordering (squad.md PR3 3d)
# ============================================================================


def squad_fight_unit_activation_start(
    game_state: Dict[str, Any], squad_id: str
) -> None:
    """Initialise l activation fight d une escouade.

    - Verifie pas de pending leftover (bug detection).
    - Initialise pending_squad_fight_intents[squad_id] = [].
    - Reset ATTACK_LEFT par fig selon l arme CC actuellement selectionnee (NB).

    Auto-selection d arme : NON ici — reportee au moment de la declaration de
    cible (la formule expected damage P(hit)*P(wound)*P(failed_save)*D requiert
    de connaitre T et Sv de la cible, cf. spec §"Auto-selection de l arme").
    Si la fig change d arme en declaration, ATTACK_LEFT sera recalcule a ce
    moment-la (responsabilite du caller de declaration).

    Reset de wounds_allocated sur la cible : NON ici — fait apres Pile In au
    moment de la declaration (scope per-cible).
    """
    assert_no_pending_fight_intent(game_state, squad_id)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for mid in squad_models.get(squad_id, []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        weapons = m.get("CC_WEAPONS", [])  # get allowed
        sel = m.get("selectedCcWeaponIndex")
        if weapons and sel is not None and 0 <= int(sel) < len(weapons):
            w = weapons[int(sel)]
            if isinstance(w, dict) and "NB" in w:
                m["ATTACK_LEFT"] = resolve_dice_value(w["NB"], f"squad_fight_init_{mid}")
            else:
                m["ATTACK_LEFT"] = 0
        else:
            m["ATTACK_LEFT"] = 0
    game_state["pending_squad_fight_intents"][squad_id] = []


def _squad_is_in_fight(game_state: Dict[str, Any], squad_id: str) -> bool:
    """Une escouade est eligible au combat si :
       - elle a charge ce tour (squad_id dans units_charged), OU
       - au moins une figurine est dans l ER d une unite ennemie.
    """
    if squad_id in game_state.get("units_charged", set()):
        return True
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_entry = units_cache.get(squad_id)
    if our_entry is None:
        return False
    our_player = int(our_entry.get("player", -1))
    er = get_engagement_range_subhex(game_state)
    our_positions = _squad_model_positions(game_state, squad_id)
    if not our_positions:
        return False
    for esid in _enemy_squad_ids(game_state, our_player):
        for tc, tr in _squad_model_positions(game_state, esid):
            for oc, orow in our_positions:
                if calculate_hex_distance(oc, orow, tc, tr) <= er:
                    return True
    return False


def squad_fight_activation_order(
    game_state: Dict[str, Any], active_player: int
) -> List[Tuple[str, str]]:
    """Construit l ordre d activation des escouades en Fight phase.

    Regle officielle (cf. spec §"Ordre d activation") :
      - Step 1 (Fights First) : escouades dans `units_charged` ou avec ability
        Fights First. Alternance : non-active player d abord, puis active.
      - Step 2 (Remaining Combats) : autres escouades eligibles. Meme alternance.
      - Chaque escouade s active une seule fois par phase.

    Returns liste ordonnee de tuples (squad_id, step) ou step ∈ {"fights_first", "remaining"}.

    PR3 3d : ne lit que les structures squad-level (units_charged, units_cache).
    Pour Fights First ability (regles speciales), `units_cache[sid].get("fights_first")`
    bool optionnel — defaut False.
    """
    units_charged = game_state.get("units_charged", set())
    units_cache = game_state.get("units_cache", {})  # get allowed
    eligible: Dict[str, str] = {}
    for sid, entry in units_cache.items():
        if not _squad_is_in_fight(game_state, str(sid)):
            continue
        ff = bool(entry.get("fights_first", False))
        if str(sid) in units_charged or ff:
            eligible[str(sid)] = "fights_first"
        else:
            eligible[str(sid)] = "remaining"

    def _player_of(sid: str) -> int:
        return int(units_cache.get(sid, {}).get("player", -1))  # get allowed

    def _alternate(squads_in_step: List[str], step_name: str) -> List[Tuple[str, str]]:
        # Tri non-active d abord, puis active. A egalite : ordre d'id (deterministe).
        non_active = sorted(s for s in squads_in_step if _player_of(s) != int(active_player))
        active = sorted(s for s in squads_in_step if _player_of(s) == int(active_player))
        out: List[Tuple[str, str]] = []
        # Alternance stricte non-active → active → non-active...
        i_na, i_ac = 0, 0
        turn_non_active = True
        while i_na < len(non_active) or i_ac < len(active):
            if turn_non_active and i_na < len(non_active):
                out.append((non_active[i_na], step_name)); i_na += 1
            elif not turn_non_active and i_ac < len(active):
                out.append((active[i_ac], step_name)); i_ac += 1
            elif i_na < len(non_active):
                out.append((non_active[i_na], step_name)); i_na += 1
            elif i_ac < len(active):
                out.append((active[i_ac], step_name)); i_ac += 1
            turn_non_active = not turn_non_active
        return out

    ff_squads = [s for s, st in eligible.items() if st == "fights_first"]
    rem_squads = [s for s, st in eligible.items() if st == "remaining"]
    return _alternate(ff_squads, "fights_first") + _alternate(rem_squads, "remaining")


# ============================================================================
# SQUAD FIGHT — Pile In + buddy rule (squad.md PR3 3e)
# ============================================================================


def fight_pile_in_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan Pile In multi-figurines (transaction atomique, aucune ecriture cache).

    Regle officielle (spec §"Pile In") :
    Chaque figurine non-B2B avec un ennemi peut se deplacer jusqu a 3" pour
    (a) finir B2B avec un ennemi si possible (OBLIGATOIRE si conditions remplies),
    (b) sinon minimiser la distance au plus proche ennemi.
    Apres placement, l escouade doit etre en coherency ET au moins une figurine
    doit etre dans l ER d une unite ennemie.

    Algorithme :
      - Ordre par index figurine.
      - Chaque fig deja en B2B (regle officielle) reste sur place.
      - Sinon : cherche dans le disque de rayon 3" l hex (i) B2B avec ennemi
        (priorite) ou (ii) plus proche d un ennemi qu avant.
      - A egalite : hex de plus petit index dans get_hex_neighbors.
      - Validation finale : coherency + ER.
      - Si validation echoue : retourne None (transaction atomique).

    Returns liste de (model_id, col, row) ou None.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None

    units_cache = game_state.get("units_cache", {})  # get allowed
    our_entry = units_cache.get(squad_id)
    if our_entry is None:
        return None
    our_player = int(our_entry.get("player", -1))

    # Positions ennemies (tous les modeles)
    enemy_positions: List[Tuple[int, int]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return None

    ish = int(require_key(game_state, "inches_to_subhex"))
    pile_in_budget = 3 * ish  # 3" en subhexes
    er_threshold = get_engagement_range_subhex(game_state)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    occupied_after: Set[Tuple[int, int]] = set()
    plan: List[Tuple[str, int, int]] = []

    def _is_b2b_with_enemy(col: int, row: int) -> bool:
        for ec, er in enemy_positions:
            if calculate_hex_distance(col, row, ec, er) == BASE_TO_BASE_SUBHEX:
                return True
        return False

    def _cell_legal(col: int, row: int) -> bool:
        # B3 cleanup (audit) : parametre exclude supprime (jamais utilise)
        if col < 0 or row < 0 or col >= board_cols or row >= board_rows:
            return False
        cell = (col, row)
        if wall_hexes and cell in wall_hexes:
            return False
        if cell in occupied_after:
            return False
        # Pas de collision avec autres escouades (sauf notre cellule d origine).
        for sid, entry in units_cache.items():
            if str(sid) == squad_id:
                continue
            occ = entry.get("occupied_hexes")
            if occ and cell in occ:
                return False
        return True

    for mid in mids:
        m = models_cache[mid]
        orig_col, orig_row = int(m["col"]), int(m["row"])
        # Deja B2B : reste sur place
        if _is_b2b_with_enemy(orig_col, orig_row):
            plan.append((mid, orig_col, orig_row))
            occupied_after.add((orig_col, orig_row))
            continue
        # Cherche (a) B2B candidate
        b2b_cands: List[Tuple[int, int, int]] = []  # (dist_from_orig, col, row)
        for ec, er in enemy_positions:
            for nc, nr in get_hex_neighbors(ec, er):
                if not _cell_legal(nc, nr):
                    continue
                d = calculate_hex_distance(orig_col, orig_row, nc, nr)
                if d > pile_in_budget:
                    continue
                b2b_cands.append((d, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_cands:
            b2b_cands.sort()  # plus proche d origine d abord
            _, pc, pr = b2b_cands[0]
            picked = (pc, pr)
        else:
            # (b) Plus proche d un ennemi
            nearest = min(
                enemy_positions,
                key=lambda ep: calculate_hex_distance(orig_col, orig_row, ep[0], ep[1]),
            )
            tc, tr = nearest
            orig_dist = calculate_hex_distance(orig_col, orig_row, tc, tr)
            best: Optional[Tuple[int, int, int]] = None  # (dist_to_target, col, row)
            for d in range(1, pile_in_budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d:
                            continue
                        nc, nr = orig_col + d_col, orig_row + d_row
                        if not _cell_legal(nc, nr):
                            continue
                        cand_d = calculate_hex_distance(nc, nr, tc, tr)
                        if cand_d >= orig_dist:
                            continue
                        if best is None or cand_d < best[0]:
                            best = (cand_d, nc, nr)
                if best is not None:
                    break
            if best is not None:
                _, pc, pr = best
                picked = (pc, pr)
        # Si pas de move utile : reste sur place (regle officielle : Pile In optionnel
        # par-figurine ; seule l obligation B2B contraint).
        if picked is None:
            picked = (orig_col, orig_row)
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale
    plan_positions = {mid: (c, r) for mid, c, r in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    in_er_count = 0
    for mid, c, r in plan:
        for ec, er in enemy_positions:
            if calculate_hex_distance(c, r, ec, er) <= er_threshold:
                in_er_count += 1
                break
    if in_er_count == 0:
        return None
    return plan


def get_fighting_models(game_state: Dict[str, Any], squad_id: str) -> List[str]:
    """Retourne les model_ids d une escouade autorises a frapper en melee.

    Regle officielle (spec §"Quelles figurines peuvent frapper — buddy rule") :
      Une fig peut attaquer si :
        (1) elle est dans l ER d une unite ennemie, OU
        (2) elle est en B2B avec une figurine ALLIEE de SON propre squad qui est
            elle-meme en B2B avec un modele ennemi.
      La condition (2) n est PAS transitive (1 niveau de buddy max).

    Ordre de retour : par index figurine (deterministe).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return []
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_player = int(units_cache.get(squad_id, {}).get("player", -1))  # get allowed
    er_threshold = get_engagement_range_subhex(game_state)
    enemy_positions: List[Tuple[int, int]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return []

    # Pre-calcule : pour chaque fig, est-elle en ER d un ennemi ? + position
    positions: Dict[str, Tuple[int, int]] = {}
    in_er: Dict[str, bool] = {}
    b2b_enemy: Dict[str, bool] = {}
    for mid in mids:
        m = models_cache[mid]
        pos = (int(m["col"]), int(m["row"]))
        positions[mid] = pos
        in_er[mid] = any(
            calculate_hex_distance(pos[0], pos[1], ec, er) <= er_threshold
            for ec, er in enemy_positions
        )
        b2b_enemy[mid] = any(
            calculate_hex_distance(pos[0], pos[1], ec, er) == BASE_TO_BASE_SUBHEX
            for ec, er in enemy_positions
        )

    # Condition (1) : in ER.
    # Condition (2) : B2B avec un allie du meme squad qui est B2B avec un ennemi.
    out: List[str] = []
    for mid in mids:
        if in_er[mid]:
            out.append(mid)
            continue
        my_pos = positions[mid]
        relayed = False
        for other_mid in mids:
            if other_mid == mid:
                continue
            if not b2b_enemy.get(other_mid, False):
                continue
            other_pos = positions[other_mid]
            if calculate_hex_distance(my_pos[0], my_pos[1], other_pos[0], other_pos[1]) == BASE_TO_BASE_SUBHEX:
                relayed = True
                break
        if relayed:
            out.append(mid)
    return out


# ============================================================================
# SQUAD FIGHT — declaration + resolution + consolidation (squad.md PR3 3f)
# ============================================================================


def _auto_select_cc_weapon_for_fig(
    attacker: Dict[str, Any], target_t: int, target_sv: int, target_invul: int
) -> int:
    """Choisit l index de l arme CC maximisant l expected damage P(hit)*P(wound)*P(failed_save)*D.

    Tie-break : index d arme le plus bas. Si pas d arme : retourne 0 (no-op).
    """
    weapons = attacker.get("CC_WEAPONS", [])  # get allowed
    if not weapons:
        return 0
    best_idx = 0
    best_score = -1.0
    for idx, w in enumerate(weapons):
        if not isinstance(w, dict):
            continue
        ws = int(w.get("ATK", w.get("WS", 4)))  # WS via ATK convention
        s = int(w.get("STR", w.get("S", 4)))
        ap = int(w.get("AP", 0))  # get allowed
        dmg_raw = w.get("DMG", 1)
        try:
            dmg = float(expected_dice_value(dmg_raw, f"auto_select_cc_dmg"))
        except Exception:
            dmg = float(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1.0
        # P(hit) : roll >= ws, et 1 always fail
        p_hit = max(0.0, (7 - ws) / 6.0) if ws <= 6 else 0.0
        wth = wound_threshold(s, target_t)
        p_wound = max(0.0, (7 - wth) / 6.0)
        save_th = save_threshold(target_sv, target_invul, ap)
        if save_th >= 7:
            p_failed_save = 1.0
        else:
            p_failed_save = max(0.0, (save_th - 1) / 6.0)
        score = p_hit * p_wound * p_failed_save * dmg
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def squad_declare_fight(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Construit les declarations de combat pour une escouade (per-fig).

    PR3 3f MVP : auto-cible = target_squad_id passe par le caller (l agent a deja
    choisi). Auto-selection d arme CC par fig selon expected damage vs T/Sv cible.
    Reset wounds_allocated_this_activation sur la cible (per-cible per-activation).

    Eligibilite per fig = `get_fighting_models` (in ER OR buddy rule).

    Returns la liste d intents (aussi stockee dans pending_squad_fight_intents).
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    if attacker_squad_id not in game_state["pending_squad_fight_intents"]:
        raise RuntimeError(
            f"squad_declare_fight called before squad_fight_unit_activation_start "
            f"for squad {attacker_squad_id!r}"
        )
    # Target info pour auto-select
    target_alive = [
        m for m in squad_models.get(target_squad_id, []) if m in models_cache  # get allowed
    ]
    if not target_alive:
        return []  # cible deja wipe
    t_sample = models_cache[target_alive[0]]
    target_t = int(t_sample.get("T", 4))
    target_sv = int(t_sample.get("ARMOR_SAVE", 7))
    target_invul = int(t_sample.get("INVUL_SAVE", 7))

    # Reset wounds_allocated sur la cible (per-cible per-activation).
    reset_wounds_allocated_for_squad(game_state, target_squad_id)

    fighting = get_fighting_models(game_state, attacker_squad_id)
    intents: List[Dict[str, Any]] = game_state["pending_squad_fight_intents"][attacker_squad_id]
    for mid in fighting:
        m = models_cache.get(mid)
        if m is None:
            continue
        chosen_idx = _auto_select_cc_weapon_for_fig(m, target_t, target_sv, target_invul)
        m["selectedCcWeaponIndex"] = chosen_idx
        # F3 fix (audit) : resoudre NB UNE SEULE FOIS, stocker dans intent.
        weapons = m.get("CC_WEAPONS", [])  # get allowed
        n_attacks_resolved = 0
        if 0 <= chosen_idx < len(weapons):
            w = weapons[chosen_idx]
            if isinstance(w, dict) and "NB" in w:
                try:
                    n_attacks_resolved = int(resolve_dice_value(w["NB"], f"squad_declare_fight_NB_{mid}"))
                except Exception:
                    n_attacks_resolved = int(w["NB"]) if isinstance(w["NB"], (int, float)) else 1
                m["ATTACK_LEFT"] = n_attacks_resolved
        intents.append({
            "model_id": mid,
            "weapon_index": chosen_idx,
            "target_unit_id": target_squad_id,
            "n_attacks_resolved": n_attacks_resolved,
        })
    return intents


def resolve_squad_fight(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> Dict[str, Any]:
    """Resolution melee (Hit→Wound→Save→Damage). Meme structure que resolve_squad_shoot.

    Differences :
      - Lit CC_WEAPONS au lieu de RNG_WEAPONS.
      - Pas de BLAST en melee.
      - Decremente ATTACK_LEFT au lieu de SHOOT_LEFT.
    """
    init_pending_intents(game_state)
    models_cache = require_key(game_state, "models_cache")
    intents = list(game_state["pending_squad_fight_intents"].get(attacker_squad_id, []))  # get allowed
    summary: Dict[str, Any] = {
        "attacks_made": 0, "hits": 0, "wounds": 0,
        "failed_saves": 0, "damage_total": 0, "models_killed": 0, "events": [],
    }
    targets_meta: Dict[str, Dict[str, Any]] = {}
    import random
    for intent in intents:
        attacker_mid = intent["model_id"]
        attacker = models_cache.get(attacker_mid)
        if attacker is None:
            continue
        target_sid = str(intent["target_unit_id"])
        if target_sid not in game_state.get("squad_models", {}):  # get allowed
            continue
        if target_sid not in targets_meta:
            _tgt_uc = require_key(game_state, "units_cache")[target_sid]
            _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
            targets_meta[target_sid] = {
                "value": float(require_key(_tgt_uc, "VALUE")),
                "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
                "player": int(require_key(_tgt_uc, "player")),
            }
        weapon_index = int(intent.get("weapon_index", 0))  # get allowed
        weapons = attacker.get("CC_WEAPONS", [])  # get allowed
        if not (0 <= weapon_index < len(weapons)):
            continue
        weapon = weapons[weapon_index]
        if not isinstance(weapon, dict):
            continue
        # F3 fix (audit) : lire n_attacks_resolved depuis l intent.
        if "n_attacks_resolved" in intent:
            n_attacks = int(intent["n_attacks_resolved"])
        else:
            nb_raw = weapon.get("NB", 1)
            try:
                n_attacks = resolve_dice_value(nb_raw, f"squad_fight_attacks_{attacker_mid}")
            except Exception:
                n_attacks = int(nb_raw) if isinstance(nb_raw, (int, float)) else 1
        if n_attacks <= 0:
            continue
        ws = int(weapon.get("ATK", weapon.get("WS", 4)))
        strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
        ap = int(weapon.get("AP", 0))  # get allowed
        dmg_raw = weapon.get("DMG", 1)
        wound_th_lookup: Dict[int, int] = {}
        for _ in range(int(n_attacks)):
            if attacker_mid not in models_cache:
                break
            target_alive = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
            if not target_alive:
                break
            summary["attacks_made"] += 1
            hit_roll = random.randint(1, 6)
            if hit_roll == 1 or hit_roll < ws:
                continue
            summary["hits"] += 1
            first_alive = models_cache[target_alive[0]]
            t_target = int(first_alive["T"])
            wth = wound_th_lookup.get(t_target)
            if wth is None:
                wth = wound_threshold(strength, t_target); wound_th_lookup[t_target] = wth
            wound_roll = random.randint(1, 6)
            if wound_roll == 1 or wound_roll < wth:
                continue
            summary["wounds"] += 1
            sv = int(first_alive["ARMOR_SAVE"])
            invul = int(first_alive.get("INVUL_SAVE", 7))
            save_th = save_threshold(sv, invul, ap)
            save_roll = random.randint(1, 6)
            if save_roll != 1 and save_roll >= save_th:
                continue
            summary["failed_saves"] += 1
            try:
                dmg = resolve_dice_value(cast(DiceValue, dmg_raw), f"squad_fight_dmg_{attacker_mid}")
            except Exception:
                dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
            if dmg <= 0:
                continue
            res = _allocate_damage_to_squad(game_state, target_sid, dmg)
            if res is None:
                break
            summary["damage_total"] += int(res["damage_dealt"])
            if res["destroyed"]:
                summary["models_killed"] += 1
            summary["events"].append({
                "attacker": attacker_mid, "target": res["model_id"],
                "target_squad_id": target_sid,
                "target_player": int(res["target_player"]),
                "points_per_hp": float(res["points_per_hp"]),
                "damage": int(res["damage_dealt"]), "destroyed": bool(res["destroyed"]),
            })
        if attacker_mid in models_cache:
            al = int(models_cache[attacker_mid].get("ATTACK_LEFT", 0))  # get allowed
            models_cache[attacker_mid]["ATTACK_LEFT"] = max(0, al - int(n_attacks))
    summary["targets_meta"] = targets_meta
    summary["squads_wiped"] = [
        sid for sid in targets_meta
        if not [m for m in game_state["squad_models"].get(sid, []) if m in models_cache]  # get allowed
    ]
    clear_pending_fight_intent(game_state, attacker_squad_id)
    return summary


def squad_consolidate_plan(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[List[Tuple[str, int, int]]]:
    """Plan Consolidation (apres melee, 3" max par fig).

    Regle officielle (spec §"Consolidation") — OR condition :
      (1) Si possible : finir dans l ER d une unite ennemie ET en coherency.
          Chaque fig doit finir plus proche de l ennemi le plus proche, B2B si possible.
      (2) Sinon : chaque fig peut se deplacer vers l objectif le plus proche, a
          condition que le deplacement mette l escouade a portee de cet objectif
          ET en coherency.
      (3) Sinon : pas de Consolidation.

    PR3 3f MVP : implementation de (1) uniquement (mouvement vers ennemi le plus proche).
    Option (2) "vers objectif" defere a PR3+ (necessite acces aux objectifs en
    game_state + concept "a portee d objectif").

    Retourne plan ou None si impossible. Atomic.
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not mids:
        return None
    units_cache = game_state.get("units_cache", {})  # get allowed
    our_entry = units_cache.get(squad_id)
    if our_entry is None:
        return None
    our_player = int(our_entry.get("player", -1))
    enemy_positions: List[Tuple[int, int]] = []
    for esid in _enemy_squad_ids(game_state, our_player):
        enemy_positions.extend(_squad_model_positions(game_state, esid))
    if not enemy_positions:
        return None  # plus d ennemi → consolidation (2) seulement, deferree

    ish = int(require_key(game_state, "inches_to_subhex"))
    budget = 3 * ish
    er_threshold = get_engagement_range_subhex(game_state)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    occupied_after: Set[Tuple[int, int]] = set()
    plan: List[Tuple[str, int, int]] = []

    def _cell_legal(c, r):
        if c < 0 or r < 0 or c >= board_cols or r >= board_rows: return False
        if wall_hexes and (c, r) in wall_hexes: return False
        if (c, r) in occupied_after: return False
        for sid, entry in units_cache.items():
            if str(sid) == squad_id: continue
            occ = entry.get("occupied_hexes")
            if occ and (c, r) in occ: return False
        return True

    for mid in mids:
        m = models_cache[mid]
        oc, orow = int(m["col"]), int(m["row"])
        nearest = min(enemy_positions, key=lambda ep: calculate_hex_distance(oc, orow, ep[0], ep[1]))
        tc, tr = nearest
        orig_dist = calculate_hex_distance(oc, orow, tc, tr)
        # B2B preference
        b2b_cands: List[Tuple[int, int, int]] = []
        for ec, er in enemy_positions:
            for nc, nr in get_hex_neighbors(ec, er):
                if not _cell_legal(nc, nr): continue
                d = calculate_hex_distance(oc, orow, nc, nr)
                if d > budget: continue
                b2b_cands.append((d, nc, nr))
        picked: Optional[Tuple[int, int]] = None
        if b2b_cands:
            b2b_cands.sort()
            _, pc, pr = b2b_cands[0]
            picked = (pc, pr)
        else:
            best: Optional[Tuple[int, int, int]] = None
            for d in range(1, budget + 1):
                for d_col in range(-d, d + 1):
                    for d_row in range(-d, d + 1):
                        if max(abs(d_col), abs(d_row)) != d: continue
                        nc, nr = oc + d_col, orow + d_row
                        if not _cell_legal(nc, nr): continue
                        cd = calculate_hex_distance(nc, nr, tc, tr)
                        if cd >= orig_dist: continue
                        if best is None or cd < best[0]:
                            best = (cd, nc, nr)
                if best is not None: break
            if best is not None:
                _, pc, pr = best
                picked = (pc, pr)
        if picked is None:
            picked = (oc, orow)
        plan.append((mid, picked[0], picked[1]))
        occupied_after.add(picked)

    # Validation finale : coherency + ER (au moins 1 fig)
    plan_positions = {mid: (c, r) for mid, c, r in plan}
    if not _validate_plan_coherency(plan_positions, game_state):
        return None
    in_er = any(
        any(calculate_hex_distance(c, r, ec, er) <= er_threshold for ec, er in enemy_positions)
        for _, c, r in plan
    )
    if not in_er:
        return None
    return plan


# ============================================================================
# END-OF-TURN COHERENCY REMOVAL (squad.md PR3 3g)
# ============================================================================


# ============================================================================
# SQUAD ACTION MASK (squad.md PR4 4b — pipeline parallele decoder)
# ============================================================================
# 16 micro-actions :
#   0-5  : Normal move direction D (cf. get_hex_neighbors, parity-aware)
#   6    : Advance (direction depuis macro_intent)
#   7    : Fall Back (direction auto)
#   8    : wait / end activation
#   9-13 : shoot slots 0-4
#   14   : charge (vers cible macro_intent)
#   15   : fight (Pile In + declare + resolve + Consolidation)
#
# Returns np-compatible list[int] de longueur 16, valeurs ∈ {0, 1}.


SQUAD_ACTION_SIZE = 26
SQUAD_ACTION_MOVE_DIR_BASE = 0
SQUAD_ACTION_MOVE_DIR_COUNT = 6
# PR4 4e-v_a : Advance et Fall Back ont chacun 6 directions (agent decide, aucune valeur par défaut)
SQUAD_ACTION_ADVANCE_DIR_BASE = 6
SQUAD_ACTION_ADVANCE_DIR_COUNT = 6
SQUAD_ACTION_FALL_BACK_DIR_BASE = 12
SQUAD_ACTION_FALL_BACK_DIR_COUNT = 6
SQUAD_ACTION_WAIT = 18
SQUAD_ACTION_SHOOT_SLOT_BASE = 19
SQUAD_ACTION_SHOOT_SLOT_COUNT = 5
SQUAD_ACTION_CHARGE = 24
SQUAD_ACTION_FIGHT = 25


def _squad_is_in_enemy_er(game_state: Dict[str, Any], squad_id: str) -> bool:
    """True si AU MOINS UNE figurine du squad est dans l ER d une fig ennemie."""
    units_cache = game_state.get("units_cache", {})  # get allowed
    entry = units_cache.get(squad_id)
    if entry is None:
        return False
    our_player = int(entry.get("player", -1))
    er = get_engagement_range_subhex(game_state)
    our_pos = _squad_model_positions(game_state, squad_id)
    if not our_pos:
        return False
    for esid in _enemy_squad_ids(game_state, our_player):
        for ec, er_pos in _squad_model_positions(game_state, esid):
            for oc, orow in our_pos:
                if calculate_hex_distance(oc, orow, ec, er_pos) <= er:
                    return True
    return False


def _squad_direction_move_legal(
    game_state: Dict[str, Any],
    squad_id: str,
    direction_idx: int,
    move_type: str,
    advance_roll: Optional[int] = None,
) -> bool:
    """Dry-run : verifie qu un mouvement de l ancre dans la direction `direction_idx`
    produit un plan rigide valide.

    direction_idx : 0..5, index dans get_hex_neighbors (parity-aware).
    move_type : "normal" / "advance" / "fall_back".
    advance_roll : pour move_type="advance", D6 roll partage (caller doit fournir).

    Aucune ecriture cache. Returns True si le plan rigide est valide
    (bounds + walls + collisions + ER ennemi + budget + coherency).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_mids = [m for m in squad_models.get(squad_id, []) if m in models_cache]  # get allowed
    if not alive_mids:
        return False
    anchor = models_cache[alive_mids[0]]
    anchor_col, anchor_row = int(anchor["col"]), int(anchor["row"])
    neighbors = get_hex_neighbors(anchor_col, anchor_row)
    if not (0 <= direction_idx < len(neighbors)):
        return False
    dest_col, dest_row = neighbors[direction_idx]
    plan = build_rigid_plan(dest_col, dest_row, squad_id, game_state)
    if plan is None:
        return False
    budget = get_squad_move_budget(squad_id, game_state, move_type, advance_roll=advance_roll)
    constraints = {"budget_per_model": budget}
    return validate_move_plan(plan, game_state, constraints)


def build_squad_action_mask(
    game_state: Dict[str, Any],
    squad_id: str,
    enemy_slot_ids: Optional[List[Optional[str]]] = None,
    advance_roll: Optional[int] = None,
) -> List[int]:
    """Construit le masque 26 actions pour une escouade active (PR4 4e-v_a).

    Decision utilisateur : agent decide direction Advance/Fall Back. Per-direction
    dry-run validation : chaque direction est mask=1 SEULEMENT si le plan rigide
    correspondant est valide (aucune valeur par défaut).

    Phase courante lue depuis game_state['phase']. Si squad absent/mort, mask all-zero.

    enemy_slot_ids : mapping slot 0..4 → squad_id ennemi (ou None). Defaut : 1ers 5
    enemy squads tries par str(sid) (PR4 4a coherence ; PR4 4d stable mapping disponible
    via get_enemy_slot_mapping).

    advance_roll : pour le mask des actions Advance (6-11), caller doit fournir le
    roll D6 partage. Si None, mask Advance fully a 0 (impossible de savoir le budget).
    """
    mask = [0] * SQUAD_ACTION_SIZE
    units_cache = game_state.get("units_cache", {})  # get allowed
    if squad_id not in units_cache:
        return mask
    entry = units_cache[squad_id]
    our_player = int(entry.get("player", -1))
    phase = str(game_state.get("phase", "")).lower()
    in_er = _squad_is_in_enemy_er(game_state, squad_id)
    has_advanced = squad_id in game_state.get("units_advanced", set())
    has_fled = squad_id in game_state.get("units_fled", set())
    has_moved = squad_id in game_state.get("units_moved", set())
    has_shot = squad_id in game_state.get("units_shot", set())
    has_fought = squad_id in game_state.get("units_fought", set())

    if enemy_slot_ids is None:
        enemy_sorted = sorted(
            (sid for sid, e in units_cache.items() if int(e["player"]) != our_player),
            key=lambda s: str(s),
        )
        enemy_slot_ids = list(enemy_sorted[:SQUAD_ACTION_SHOOT_SLOT_COUNT]) + [None] * max(
            0, SQUAD_ACTION_SHOOT_SLOT_COUNT - len(enemy_sorted)
        )

    # --- Move phase: directions Normal (0-5), Advance (6-11), Fall Back (12-17) ---
    if phase == "move":
        if not has_moved:
            # Normal move : interdit si in ER (locked). Per-direction dry-run.
            if not in_er:
                for d in range(SQUAD_ACTION_MOVE_DIR_COUNT):
                    if _squad_direction_move_legal(game_state, squad_id, d, "normal"):
                        mask[SQUAD_ACTION_MOVE_DIR_BASE + d] = 1
                # Advance : per-direction validation avec roll partage.
                # Si advance_roll=None : impossible d evaluer le budget, mask 0.
                if advance_roll is not None and not has_advanced and not has_fled:
                    for d in range(SQUAD_ACTION_ADVANCE_DIR_COUNT):
                        if _squad_direction_move_legal(
                            game_state, squad_id, d, "advance", advance_roll=advance_roll
                        ):
                            mask[SQUAD_ACTION_ADVANCE_DIR_BASE + d] = 1
            # Fall Back : uniquement si in ER ennemi. Per-direction dry-run.
            if in_er and not has_advanced and not has_fled:
                for d in range(SQUAD_ACTION_FALL_BACK_DIR_COUNT):
                    if _squad_direction_move_legal(game_state, squad_id, d, "fall_back"):
                        mask[SQUAD_ACTION_FALL_BACK_DIR_BASE + d] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Shoot phase: shoot slots 19-23 ---
    elif phase == "shoot":
        can_shoot = not has_fled and not has_advanced and not has_shot and not in_er
        if can_shoot:
            for slot_i, esid in enumerate(enemy_slot_ids):
                if esid is None or esid not in units_cache:
                    continue
                er = get_engagement_range_subhex(game_state)
                e_pos = _squad_model_positions(game_state, esid)
                ally_pos: List[Tuple[int, int]] = []
                for sid, e in units_cache.items():
                    if int(e["player"]) != our_player:
                        continue
                    if str(sid) == squad_id:
                        continue
                    ally_pos.extend(_squad_model_positions(game_state, str(sid)))
                locked_by_ally = any(
                    any(calculate_hex_distance(ec, er_, ac, ar) <= er for ac, ar in ally_pos)
                    for ec, er_ in e_pos
                )
                if locked_by_ally:
                    continue
                models_cache = game_state.get("models_cache", {})  # get allowed
                can_any_hit = False
                for mid in game_state.get("squad_models", {}).get(squad_id, []):  # get allowed
                    m = models_cache.get(mid)
                    if m is None:
                        continue
                    if _model_can_shoot_target(game_state, m, esid):
                        can_any_hit = True
                        break
                if can_any_hit:
                    mask[SQUAD_ACTION_SHOOT_SLOT_BASE + slot_i] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Charge phase: action 24 ---
    elif phase == "charge":
        any_charge_possible = False
        for esid in enemy_slot_ids:
            if esid is None:
                continue
            if charge_check_eligibility(game_state, squad_id, [esid]):
                any_charge_possible = True
                break
        if any_charge_possible:
            mask[SQUAD_ACTION_CHARGE] = 1
        mask[SQUAD_ACTION_WAIT] = 1

    # --- Fight phase: action 25 ---
    elif phase == "fight":
        eligible = _squad_is_in_fight(game_state, squad_id)
        if eligible and not has_fought:
            mask[SQUAD_ACTION_FIGHT] = 1
        if not eligible:
            mask[SQUAD_ACTION_WAIT] = 1

    # --- Other phases (command/deployment) ---
    else:
        mask[SQUAD_ACTION_WAIT] = 1

    return mask


# ============================================================================
# STABLE ENEMY SLOT MAPPING (squad.md PR4 4d)
# ============================================================================
# Mapping fixe a l init de partie : top-5 escouades ennemies par menace
# (HP_total * OC_total). Tie-break = ordre d index (deterministe).
# Apres init, le mapping NE CHANGE JAMAIS. Si une escouade slot meurt, son
# slot reste vide (masque=0). La 6eme escouade n est PAS promue.


def init_enemy_slot_mapping(game_state: Dict[str, Any], our_player: int) -> None:
    """Construit le mapping stable a l init de partie. Idempotent.

    Cle stockee : game_state[f"enemy_slot_mapping_p{our_player}"] = [sid_or_None, ...]
    Liste de 5 entrees, chaque slot = squad_id ennemi ou None si moins de 5 ennemis.

    A appeler UNE SEULE FOIS au debut de partie. Si la cle existe deja → no-op
    (preserve mapping initial même si squad meurt).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key in game_state:
        return
    units_cache = game_state.get("units_cache", {})  # get allowed
    squad_models = game_state.get("squad_models", {})  # get allowed
    models_cache = game_state.get("models_cache", {})  # get allowed
    # Calcule (squad_id, threat) pour chaque ennemi vivant a l init
    candidates: List[Tuple[str, float, int]] = []  # (sid, threat, idx)
    enemy_sorted = sorted(
        (sid for sid, e in units_cache.items() if int(e["player"]) != int(our_player)),
        key=lambda s: str(s),
    )
    for idx, sid in enumerate(enemy_sorted):
        entry = units_cache[sid]
        hp_total = int(entry.get("HP_CUR", 0))  # get allowed
        # OC_total : prefer cache value, calcul de secours
        oc_total = int(entry.get("OC_TOTAL", 0))  # get allowed
        if oc_total == 0:
            for mid in squad_models.get(sid, []):  # get allowed
                m = models_cache.get(mid)
                if m is not None:
                    oc_total += int(m.get("OC", 0))  # get allowed
        threat = float(hp_total) * float(oc_total)
        candidates.append((str(sid), threat, idx))
    # Tri : menace decroissante, tie-break index croissant (ordre creation)
    candidates.sort(key=lambda t: (-t[1], t[2]))
    slot_count = SQUAD_ACTION_SHOOT_SLOT_COUNT
    mapping: List[Optional[str]] = [None] * slot_count
    for slot_i in range(min(slot_count, len(candidates))):
        mapping[slot_i] = candidates[slot_i][0]
    game_state[cache_key] = mapping


def get_enemy_slot_mapping(
    game_state: Dict[str, Any], our_player: int
) -> List[Optional[str]]:
    """Retourne le mapping fige. Si squad d un slot est mort, retourne None pour ce slot.

    Si le mapping n a jamais ete initialise, le construit (init lazy).
    """
    cache_key = f"enemy_slot_mapping_p{int(our_player)}"
    if cache_key not in game_state:
        init_enemy_slot_mapping(game_state, our_player)
    raw = game_state.get(cache_key, [None] * SQUAD_ACTION_SHOOT_SLOT_COUNT)
    units_cache = game_state.get("units_cache", {})  # get allowed
    return [sid if (sid is not None and sid in units_cache) else None for sid in raw]


def end_of_turn_coherency_removal(
    game_state: Dict[str, Any], squad_id: str
) -> List[str]:
    """Retrait deterministe des figurines hors coherency (MVP PR3).

    Boucle :
      - Si squad coherent OU model_count <= 1 → stop.
      - Sinon : retire la figurine la plus eloignee du centroide geometrique.
        Tie-break : index croissant. Utilise destroy_model(reason='coherency_removal').
      - Recalcule coherency apres chaque retrait.

    Returns liste des model_ids retires (ordre de retrait).

    Note : la fig retiree par 'coherency_removal' ne genere ni reward kill ni perte
    d OC pour le combat (cf. spec §"Cascade de mise a jour" — reason discrimine).
    """
    removed: List[str] = []
    while True:
        models_cache = game_state.get("models_cache", {})  # get allowed
        squad_models = game_state.get("squad_models", {}).get(squad_id, [])  # get allowed
        alive = [m for m in squad_models if m in models_cache]
        if len(alive) <= 1:
            break
        if validate_squad_coherency(game_state, squad_id):
            break
        # Calcule centroide
        positions = [(int(models_cache[m]["col"]), int(models_cache[m]["row"])) for m in alive]
        cx = sum(p[0] for p in positions) / float(len(positions))
        cy = sum(p[1] for p in positions) / float(len(positions))
        # B1 cleanup (audit) : pre-calcule l index pour O(1) lookup vs alive.index O(n)
        index_of = {mid: i for i, mid in enumerate(alive)}
        # Fig la plus eloignee (distance euclidienne carree, evite sqrt)
        def _sq_dist(mid: str) -> float:
            m = models_cache[mid]
            dx = int(m["col"]) - cx
            dy = int(m["row"]) - cy
            return dx * dx + dy * dy
        # Sort by (-dist, index) — distance max d abord, puis index croissant pour tie-break
        sorted_alive = sorted(alive, key=lambda mid: (-_sq_dist(mid), index_of[mid]))
        target_mid = sorted_alive[0]
        destroy_model(game_state, target_mid, reason="coherency_removal")
        removed.append(target_mid)
    return removed
