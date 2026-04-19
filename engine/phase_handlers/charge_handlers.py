#!/usr/bin/env python3
"""
charge_handlers.py - AI_TURN.md Charge Phase Implementation
Pure stateless functions implementing AI_TURN.md charge specification

References: AI_TURN.md Section ⚡ CHARGE PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

import os
import time
from collections import deque
from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from shared.data_validation import require_key
from engine.game_utils import add_console_log, safe_print, add_debug_file_log
from engine.combat_utils import (
    normalize_coordinates,
    get_unit_by_id,
    get_hex_neighbors,
    expected_dice_value,
    resolve_dice_value,
    calculate_hex_distance as _calculate_hex_distance,
)
from .shared_utils import (
    ACTION, WAIT, NO, ERROR, PASS, CHARGE,
    update_units_cache_position, update_units_cache_hp, is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    build_occupied_positions_set, compute_candidate_footprint, is_footprint_placement_valid,
)

CHARGE_IMPACT_TRIGGER_THRESHOLD = 4
CHARGE_IMPACT_MORTAL_WOUNDS = 1


def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific direct or granted rule effect by ruleId."""
    return shared_unit_has_rule_effect(unit, rule_id)


def _get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId that grants/owns the effect; None if absent."""
    return shared_get_source_unit_rule_id_for_effect(unit, effect_rule_id)


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.displayName for an effect rule; None if absent."""
    return shared_get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)


def _charge_debug_positions_enabled(game_state: Dict[str, Any]) -> bool:
    """Verbose per-BFS charge position logging (expensive). Off unless env or flag set."""
    if game_state.get("charge_debug_positions"):
        return True
    return os.environ.get("W40K_CHARGE_DEBUG", "").lower() in ("1", "true", "yes")


FootprintOffsetPair = Optional[Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]]


def _charge_prepare_footprint_offsets(
    unit: Dict[str, Any], game_state: Dict[str, Any]
) -> FootprintOffsetPair:
    """Pre-compute even/odd footprint offsets for Board×10 multi-hex (same idea as fly BFS).

    Returns None to fall back to ``compute_candidate_footprint`` (legacy boards, 1-hex, or error).
    Result is cached per unit for the phase (see ``charge_phase_start`` reset).
    """
    cache: Dict[str, FootprintOffsetPair] = game_state.setdefault("_charge_fp_offset_pair_cache", {})
    uid = str(unit["id"])
    if uid in cache:
        return cache[uid]

    from .shared_utils import get_engagement_zone

    ez = get_engagement_zone(game_state)
    bs = unit.get("BASE_SIZE", 1)
    if ez <= 1 or bs == 1:
        cache[uid] = None
        return None
    try:
        from engine.hex_utils import precompute_footprint_offsets

        shape = unit.get("BASE_SHAPE", "round")
        orient = unit.get("orientation", 0)
        off_e, off_o = precompute_footprint_offsets(shape, bs, orient)
        out: FootprintOffsetPair = (off_e, off_o)
        cache[uid] = out
        return out
    except Exception:
        cache[uid] = None
        return None


def _candidate_footprint_charge(
    center_col: int,
    center_row: int,
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    offset_pair: FootprintOffsetPair,
) -> Set[Tuple[int, int]]:
    if offset_pair is not None:
        off_e, off_o = offset_pair
        offs = off_e if (center_col & 1) == 0 else off_o
        return {(center_col + dc, center_row + dr) for dc, dr in offs}
    return compute_candidate_footprint(center_col, center_row, unit, game_state)


def _charge_footprint_union_for_anchors(
    game_state: Dict[str, Any],
    unit_id: str,
    anchor_positions: List[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    """
    Union of all occupied hexes for each valid anchor — used for PvP violet preview.

    ``valid_destinations`` lists anchor cells only; the UI must show the full end footprint
    (around the declared target / engagement band), not a scatter of anchor dots near the charger.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit or not anchor_positions:
        return []
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    seen: Set[Tuple[int, int]] = set()
    ordered: List[Tuple[int, int]] = []
    for ac, ar in anchor_positions:
        fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        for h in fp:
            if h not in seen:
                seen.add(h)
                ordered.append(h)
    return ordered


def _resolve_charge_dest_to_anchor(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    valid_pool: List[Tuple[int, int]],
    dest_col: int,
    dest_row: int,
) -> Optional[Tuple[int, int]]:
    """Map a clicked hex (any cell of the end footprint) to the canonical anchor in ``valid_pool``.

    Ordre de résolution : (1) ancre exacte, (2) ancre dont l'empreinte couvre l'hex cliqué,
    (3) ancre la plus proche en distance hex (clic dans la zone violette hors empreinte exacte).
    """
    from engine.hex_utils import hex_distance

    if (dest_col, dest_row) in valid_pool:
        return (dest_col, dest_row)
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    for ac, ar in valid_pool:
        fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        if (dest_col, dest_row) in fp:
            return (int(ac), int(ar))
    best: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for ac, ar in valid_pool:
        d = hex_distance(int(ac), int(ar), int(dest_col), int(dest_row))
        if d < best_d:
            best_d = d
            best = (int(ac), int(ar))
    return best


def _charge_base_diameter(unit: Dict[str, Any]) -> int:
    """Diamètre de l'empreinte en hexes (fallback 1).

    BASE_SIZE peut être int (round/square) ou [major, minor] (oval).
    """
    bs = unit.get("BASE_SIZE", 1)
    if isinstance(bs, (list, tuple)) and len(bs) >= 1:
        try:
            return max(int(v) for v in bs)
        except (TypeError, ValueError):
            return 1
    try:
        return max(1, int(bs))
    except (TypeError, ValueError):
        return 1


def _charge_closest_charger_hex_to_target(
    charger_fp: Set[Tuple[int, int]],
    target_fp: Set[Tuple[int, int]],
) -> Tuple[Tuple[int, int], int]:
    """Renvoie (hex allié le plus proche de la cible, distance hex associée)."""
    from engine.hex_utils import hex_distance

    best_h: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for hc, hr in charger_fp:
        for tc, tr in target_fp:
            d = hex_distance(int(hc), int(hr), int(tc), int(tr))
            if d < best_d:
                best_d = d
                best_h = (int(hc), int(hr))
    if best_h is None:
        # charger_fp vide — repli arbitraire
        return ((0, 0), 0)
    return (best_h, best_d)


def _compute_charge_preview_zone(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    charge_roll: int,
) -> Tuple[Set[Tuple[int, int]], Tuple[int, int]]:
    """
    Zone violette cible-centrée (spec utilisateur) :

    - Hexes adjacents aux hex extérieurs de l'empreinte **cible** jusqu'à
      ``diamètre(empreinte chargeur) + engagement_zone`` pas (exclut l'empreinte cible).
    - Filtrée par la distance hex depuis **l'hex chargeur le plus proche de la cible**,
      qui doit rester ≤ ``charge_roll``.

    Renvoie ``(zone_hexes, closest_charger_hex_to_target)``.
    """
    from engine.hex_utils import dilate_hex_set_unbounded, hex_distance
    from .shared_utils import get_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    uid = str(unit["id"])
    tid = str(target["id"])
    ue = units_cache.get(uid)
    te = units_cache.get(tid)
    if not ue or not te:
        return (set(), (0, 0))

    charger_fp = set(ue.get("occupied_hexes") or {(int(ue["col"]), int(ue["row"]))})
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})

    closest_ch, _ = _charge_closest_charger_hex_to_target(charger_fp, target_fp)

    engagement_zone = get_engagement_zone(game_state)
    diameter = _charge_base_diameter(unit)
    max_ring = max(1, diameter + engagement_zone)

    # Zone extérieure autour de la cible : [1 .. max_ring] hexes depuis la cible.
    outer_with_target = dilate_hex_set_unbounded(target_fp, max_ring)
    target_zone = outer_with_target - target_fp

    # Disque autour de l'hex chargeur le plus proche : distance ≤ charge_roll.
    if charge_roll <= 0:
        return (set(), closest_ch)
    charger_disk = dilate_hex_set_unbounded({closest_ch}, int(charge_roll))

    # Bornes plateau
    board_cols = int(game_state.get("board_cols", 0) or 0)
    board_rows = int(game_state.get("board_rows", 0) or 0)

    zone: Set[Tuple[int, int]] = set()
    for h in target_zone & charger_disk:
        c, r = int(h[0]), int(h[1])
        if board_cols > 0 and (c < 0 or c >= board_cols):
            continue
        if board_rows > 0 and (r < 0 or r >= board_rows):
            continue
        # Confirme la contrainte de portée charge (sécurité, dilate est exact).
        if hex_distance(closest_ch[0], closest_ch[1], c, r) > int(charge_roll):
            continue
        zone.add((c, r))
    return (zone, closest_ch)


def _build_charge_anchors_in_zone(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target: Dict[str, Any],
    zone: Set[Tuple[int, int]],
    charge_roll: int,
) -> List[Tuple[int, int]]:
    """
    Ancres de placement valides dont :
    - le centre est dans la ``zone`` cible-centrée ;
    - l'empreinte ne chevauche pas la cible (``occupied_hexes``) ;
    - l'empreinte touche la zone d'engagement de la cible ;
    - le placement est légal (``is_footprint_placement_valid``).
    """
    from engine.hex_utils import dilate_hex_set_unbounded, hex_distance
    from .shared_utils import get_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    te = units_cache.get(str(target["id"]))
    if not te:
        return []
    target_fp = set(te.get("occupied_hexes") or {(int(te["col"]), int(te["row"]))})
    engagement_zone = get_engagement_zone(game_state)
    enemy_shell = dilate_hex_set_unbounded(target_fp, engagement_zone)

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)

    charger_fp_now = set((units_cache.get(unit_id_str) or {}).get("occupied_hexes") or set())
    closest_ch, _ = _charge_closest_charger_hex_to_target(charger_fp_now, target_fp)

    anchors: List[Tuple[int, int]] = []
    for ac, ar in zone:
        # Re-confirme la portée depuis l'hex chargeur le plus proche.
        if hex_distance(closest_ch[0], closest_ch[1], int(ac), int(ar)) > int(charge_roll):
            continue
        candidate_fp = _candidate_footprint_charge(int(ac), int(ar), unit, game_state, fp_pair)
        if candidate_fp & target_fp:
            continue
        if not (candidate_fp & enemy_shell):
            continue
        if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
            continue
        anchors.append((int(ac), int(ar)))
    return anchors


def _charge_bfs_max_distance(
    game_state: Dict[str, Any],
    unit_id: str,
    charge_roll: int,
    target_id: Optional[str],
) -> int:
    """
    Nombre maximum de pas d'ancre pour le BFS de charge.

    AI_TURN / charge_compliance : la distance utile se rapporte au contact avec la cible — sur
    plateau ×10, l'ancre ``col``/``row`` peut être du côté opposé à la cible alors qu'un hex de
    l'empreinte est déjà proche. On ajoute la distance hex (primaire → hex allié le plus proche
    de l'empreinte ennemie) au jet, pour que le pool et la zone violette s'étendent vers la cible.
    """
    from engine.hex_utils import hex_distance

    rid = int(charge_roll)
    if not target_id:
        return rid

    units_cache = require_key(game_state, "units_cache")
    uid = str(unit_id)
    tid = str(target_id)
    ue = units_cache.get(uid)
    te = units_cache.get(tid)
    if not ue or not te:
        return rid

    own_hexes = ue.get("occupied_hexes")
    if not own_hexes:
        own_hexes = {(int(ue["col"]), int(ue["row"]))}
    enemy_fp = te.get("occupied_hexes")
    if not enemy_fp:
        enemy_fp = {(int(te["col"]), int(te["row"]))}

    primary = (int(ue["col"]), int(ue["row"]))
    best_h: Optional[Tuple[int, int]] = None
    best_d = 10**9
    for hc, hr in own_hexes:
        for tc, tr in enemy_fp:
            d = hex_distance(int(hc), int(hr), int(tc), int(tr))
            if d < best_d:
                best_d = d
                best_h = (int(hc), int(hr))
    if best_h is None:
        return rid
    extra = hex_distance(primary[0], primary[1], best_h[0], best_h[1])
    return rid + extra


def charge_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize charge phase and build activation pool
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t_total0 = time.perf_counter() if _perf else None

    # Set phase
    game_state["phase"] = "charge"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} charge units_cache={units_cache}")

    # Tracking sets are NOT cleared at charge phase start
    # They persist from movement phase (units_fled, units_moved, units_shot remain)

    # Clear charge preview state
    game_state["valid_charge_destinations_pool"] = []
    game_state["_charge_dest_bfs_cache"] = {}
    game_state["_charge_fp_offset_pair_cache"] = {}
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = None
    game_state["charge_roll_values"] = {}  # Store 2d6 rolls per unit
    game_state["charge_target_selections"] = {}  # Store target selections per unit
    game_state["pending_charge_targets"] = []  # Store targets for gym training target selection
    game_state["pending_charge_unit_id"] = None  # Store unit ID waiting for target selection

    _t_before_enemy_adj = time.perf_counter() if _perf else None

    # PERFORMANCE: Pre-compute enemy_adjacent_hexes once at phase start for current player
    # Cache will be reused throughout the phase for all units (invalidated after each charge)
    current_player = require_key(game_state, "current_player")
    from .shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(game_state, current_player)

    _t_after_enemy_adj = time.perf_counter() if _perf else None

    # Build activation pool
    charge_build_activation_pool(game_state)

    if _perf and _t_total0 is not None and _t_before_enemy_adj is not None and _t_after_enemy_adj is not None:
        _t_end = time.perf_counter()
        append_perf_timing_line(
            f"CHARGE_PHASE_START episode={_ep} turn={_turn} "
            f"setup_until_adj_s={_t_before_enemy_adj - _t_total0:.6f} "
            f"enemy_adjacent_hexes_s={_t_after_enemy_adj - _t_before_enemy_adj:.6f} "
            f"pool_build_s={_t_end - _t_after_enemy_adj:.6f} total_s={_t_end - _t_total0:.6f}"
        )

    # Console log (disabled in training mode for performance)
    add_console_log(game_state, "CHARGE POOL BUILT")

    # Check if phase complete immediately (no eligible units)
    pool_after_build = game_state["charge_activation_pool"]
    if not pool_after_build:
        return charge_phase_end(game_state)

    return {
        "phase_initialized": True,
        "eligible_units": len(pool_after_build),
        "phase_complete": False
    }


def charge_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build charge activation pool with eligibility checks
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _t0 = time.perf_counter() if _perf else None

    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["charge_activation_pool"] = []
    eligible_units = get_eligible_units(game_state)
    game_state["charge_activation_pool"] = list(eligible_units)  # Ensure it's a new list, not a reference

    if _perf and _t0 is not None:
        append_perf_timing_line(
            f"CHARGE_BUILD_POOL episode={_ep} turn={_turn} "
            f"get_eligible_s={time.perf_counter() - _t0:.6f} eligible_count={len(eligible_units)}"
        )

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} charge charge_activation_pool={eligible_units}")

def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md charge eligibility decision tree implementation.

    Charge Eligibility Requirements:
    - Alive (in units_cache)
    - player === current_player
    - NOT in units_charged
    - NOT adjacent to enemy (distance > melee_range to all enemies)
    - NOT in units_fled
    - Has valid charge target (enemy within charge range via pathfinding)

    Returns list of unit IDs eligible for charge activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    units_cache = require_key(game_state, "units_cache")
    from engine.hex_utils import dilate_hex_set_unbounded
    from .shared_utils import get_engagement_zone

    engagement_zone = get_engagement_zone(game_state)
    enemy_engagement_shells_by_id: Dict[str, Set[Tuple[int, int]]] = {}
    for eid, entry in units_cache.items():
        ec, er = int(entry["col"]), int(entry["row"])
        efp = entry.get("occupied_hexes", {(ec, er)})
        enemy_engagement_shells_by_id[str(eid)] = dilate_hex_set_unbounded(efp, engagement_zone)

    full_occupied_positions = build_occupied_positions_set(game_state)

    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_id_str = str(unit_id)

        # "unit.player === current_player?"
        if cache_entry["player"] != current_player:
            continue  # Wrong player

        # "NOT adjacent to enemy?" — footprint distance <= engagement_zone
        unit_col_int, unit_row_int = require_unit_position(unit_id, game_state)
        unit_fp = cache_entry.get("occupied_hexes", {(unit_col_int, unit_row_int)})
        adjacent_found = False
        for enemy_id, enemy_entry in units_cache.items():
            if enemy_entry["player"] != cache_entry["player"]:
                if unit_fp & enemy_engagement_shells_by_id[str(enemy_id)]:
                    adjacent_found = True
                    break

        if adjacent_found:
            continue  # Already in melee, cannot charge

        # "NOT in units_fled?" unless the unit has a rule effect allowing charge after fleeing
        # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
        if unit_id_str in game_state["units_fled"]:
            if not _unit_has_rule(unit, "charge_after_flee"):
                continue  # Fled units cannot charge without explicit rule effect

        # Post-shoot movement restriction: cannot charge until end of turn.
        units_cannot_charge = require_key(game_state, "units_cannot_charge")
        if unit_id_str in units_cannot_charge:
            continue

        # ADVANCE_IMPLEMENTATION: Units that advanced cannot charge
        units_advanced = require_key(game_state, "units_advanced")
        if unit_id_str in units_advanced:
            if not _unit_has_rule(unit, "charge_after_advance"):
                continue  # Advanced units cannot charge without rule

        # "Has valid charge target?"
        # Must have at least one enemy within charge range (via BFS pathfinding)
        if not _has_valid_charge_target(game_state, unit, full_occupied_positions):
            continue  # No valid charge targets

        # Unit passes all conditions - add to pool
        eligible_units.append(unit_id_str)

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge phase handler action routing with complete autonomy
    """
    # Handler self-initialization on first action
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]

    if "charge_activation_pool" not in game_state:
        charge_pool_exists = False
    else:
        charge_pool_exists = bool(game_state["charge_activation_pool"])

    if game_state_phase != "charge" or not charge_pool_exists:
        charge_phase_start(game_state)

    # Pool empty? -> Phase complete
    if not game_state["charge_activation_pool"]:
        return True, charge_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to charge)
    # AI_TURN.md COMPLIANCE: Direct field access - no defaults
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = None  # Allow None for gym training auto-selection
    else:
        action_type = action["action"]
        unit_id = action["unitId"]

    # For gym training or PvE AI, if no unitId specified, use first eligible unit
    if not unit_id:
        config_gym_mode = config["gym_training_mode"] if "gym_training_mode" in config else False
        state_gym_mode = game_state["gym_training_mode"] if "gym_training_mode" in game_state else False
        is_gym_training = config_gym_mode or state_gym_mode
        current_player = require_key(game_state, "current_player")
        is_pve_ai = config.get("pve_mode", False) and current_player == 2
        if not is_gym_training and not is_pve_ai:
            return False, {
                "error": "unit_id_required",
                "action": action_type,
                "message": "unitId is required for human-controlled charge activation"
            }
        if game_state["charge_activation_pool"]:
            unit_id = game_state["charge_activation_pool"][0]
        else:
            return True, charge_phase_end(game_state)

    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        active_charge_unit = game_state.get("active_charge_unit")
        pool_size = len(require_key(game_state, "charge_activation_pool"))
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} execute_action action={action_type} "
            f"unit_id={unit_id} active_charge_unit={active_charge_unit} pool_size={pool_size}"
        )

    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["charge_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    # Get unit object for processing
    active_unit = get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}

    # Flag detection for consistent behavior
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # Auto-activate unit if not already activated and preview not shown
    # AI_TURN.md COMPLIANCE: Direct field access with explicit check
    if "active_charge_unit" not in game_state:
        active_charge_unit_exists = False
    else:
        active_charge_unit_exists = bool(game_state["active_charge_unit"])

    if not active_charge_unit_exists and action_type in ["charge", "left_click"]:
        if is_gym_training:
            # AI_TURN.md COMPLIANCE: In gym training, ActionDecoder may construct complete charge action
            # Check if action already has targetId and destCol/destRow (complete charge action)
            if "targetId" in action and "destCol" in action and "destRow" in action:
                # Action already has target and destination - execute charge directly, no waiting needed
                # Just ensure unit is activated, then execute charge via destination selection handler
                charge_unit_activation_start(game_state, unit_id)
                # Roll 2d6 and build destinations for validation (needed for charge execution)
                execution_result = charge_unit_execution_loop(game_state, unit_id)
                # Execute charge directly via destination selection handler
                return charge_destination_selection_handler(game_state, unit_id, action)
            else:
                # No target/destination yet - activate unit to get targets (will auto-select and execute)
                return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate and return waiting_for_player
            return _handle_unit_activation(game_state, active_unit, config)

    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)

    elif action_type == "charge":
        # Route based on what's in the action:
        # - If targetId but no destCol/destRow -> target selection (roll, build pool, preview)
        # - If destCol/destRow -> destination selection (execute charge)
        if "targetId" in action and "destCol" not in action:
            # Target selection step
            return charge_target_selection_handler(game_state, unit_id, action)
        elif "destCol" in action and "destRow" in action:
            # Destination selection step
            return charge_destination_selection_handler(game_state, unit_id, action)
        else:
            return False, {"error": "invalid_charge_action", "action": action}

    elif action_type == "skip":
        # Fin de phase manuelle (API) : forfait charge sans WAIT ni journalisation « wait » par unité
        # (had_valid_destinations=False → end_activation PASS, pas d'entrée action_logs type wait, pas +step).
        if action.get("manual_end_phase"):
            success, result = _handle_skip_action(
                game_state, active_unit, had_valid_destinations=False
            )
            result["action"] = "skip"
            result["skip_reason"] = "manual_end_phase"
            return success, result
        # Ignore skip action if unit is not active in charge phase
        # This prevents skip actions from shooting phase being processed in charge phase
        active_charge_unit = game_state.get("active_charge_unit")
        if active_charge_unit != unit_id:
            pool_ids = [str(u) for u in require_key(game_state, "charge_activation_pool")]
            if str(unit_id) in pool_ids:
                # Unit in charge pool but not activated (e.g. API end_phase without activate_unit).
                # Match active-unit skip: had_valid_destinations=True (AI_TURN.md line 515 path).
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)
            # CRITICAL: In gym training mode, skip must NOT trigger activation or movement.
            # Determine had_valid_destinations without executing charge logic.
            if is_gym_training:
                valid_targets = charge_build_valid_targets(game_state, unit_id)
                had_valid_destinations = len(valid_targets) > 0
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=had_valid_destinations)
            # PvE AI: treat skip as explicit wait to avoid infinite loop on non-active unit
            if "pve_mode" not in config:
                config_pve_mode = False
            else:
                config_pve_mode = config["pve_mode"]
            if not isinstance(config_pve_mode, bool):
                raise ValueError(f"pve_mode must be boolean (got {type(config_pve_mode).__name__})")
            current_player = require_key(game_state, "current_player")
            is_pve_ai = config_pve_mode and current_player == 2
            if is_pve_ai:
                valid_targets = charge_build_valid_targets(game_state, unit_id)
                had_valid_destinations = len(valid_targets) > 0
                return _handle_skip_action(game_state, active_unit, had_valid_destinations=had_valid_destinations)
            # Unit not in charge pool and not active — ignore (e.g. stale action)
            return True, {"action": "no_effect", "unitId": unit_id, "reason": "unit_not_active_in_charge_phase"}
        # AI_TURN.md Line 515: Agent chooses wait (has valid destinations, chooses to skip)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)

    elif action_type == "left_click":
        return charge_click_handler(game_state, unit_id, action)

    elif action_type == "right_click":
        # AI_TURN.md Line 536: Human cancels (right-click on active unit)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)

    elif action_type == "invalid":
        # Handle invalid actions with training penalty
        if unit_id in game_state["charge_activation_pool"]:
            # Clear preview first
            charge_clear_preview(game_state)

            # Invalid action during charge phase
            result = end_activation(
                game_state, active_unit,
                ERROR,       # Arg1: Error logging (invalid action)
                1,           # Arg2: +1 step increment
                PASS,        # Arg3: No tracking
                CHARGE,      # Arg4: Remove from charge pool
                1            # Arg5: Error logging
            )
            result["invalid_action_penalty"] = True
            # CRITICAL: No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id, "action": action_type}

    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "charge"}


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Charge unit activation start + execution loop"""
    # Unit activation start
    charge_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    execution_result = charge_unit_execution_loop(game_state, unit["id"])
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} _handle_unit_activation unit_id={unit['id']} "
            f"execution_result_ok={execution_result[0] if isinstance(execution_result, tuple) else 'invalid'}"
        )

    # Clean flag detection
    # AI_TURN.md COMPLIANCE: Direct field access with explicit validation
    if "gym_training_mode" not in config:
        config_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        config_gym_mode = config["gym_training_mode"]

    if "gym_training_mode" not in game_state:
        state_gym_mode = False  # Explicit: not in training mode if flag absent
    else:
        state_gym_mode = game_state["gym_training_mode"]

    is_gym_training = config_gym_mode or state_gym_mode

    # Determine PvE AI context (non-gym) for auto charge execution
    if "pve_mode" not in config:
        config_pve_mode = False
    else:
        config_pve_mode = config["pve_mode"]
    if not isinstance(config_pve_mode, bool):
        raise ValueError(f"pve_mode must be boolean (got {type(config_pve_mode).__name__})")
    current_player = require_key(game_state, "current_player")
    is_pve_ai = config_pve_mode and current_player == 2

    # AI_TURN.md COMPLIANCE: In gym training, AI executes charge directly without waiting_for_player
    # PvE AI uses the same auto-execution path to avoid waiting for human input.
    if (is_gym_training or is_pve_ai) and isinstance(execution_result, tuple) and execution_result[0]:
        # AI_TURN.md COMPLIANCE: Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        if waiting_for_player:
            if "debug_mode" in game_state and game_state["debug_mode"]:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_file_log(
                    game_state,
                    f"[CHARGE TRACE] E{episode} T{turn} _handle_unit_activation waiting_for_player=True "
                    f"unit_id={unit['id']} is_pve_ai={is_pve_ai} is_gym_training={is_gym_training}"
                )
            if "valid_targets" not in execution_result[1]:
                raise KeyError("Execution result missing required 'valid_targets' field")
            valid_targets = execution_result[1]["valid_targets"]

            if valid_targets:
                # AI_TURN.md: AI selects target automatically and executes charge directly
                # Do NOT return waiting_for_player=True - execute charge automatically
                if is_pve_ai:
                    selected_target = _ai_select_charge_target_pve(game_state, unit, valid_targets)
                else:
                    selected_target = valid_targets[0]
                if selected_target is None:
                    return _handle_skip_action(game_state, unit, had_valid_destinations=False)
                target_id = selected_target["id"]
                if game_state.get("debug_mode", False):
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    add_debug_file_log(
                        game_state,
                        f"[PVE CHARGE AUTO] E{episode} T{turn} unit_id={unit['id']} target_id={target_id}"
                    )
                
                # Execute target selection handler which will roll 2d6, build destinations, and execute charge
                # This follows AI_TURN.md: roll → select target → build destinations → select destination → execute
                from engine.phase_handlers.charge_handlers import charge_target_selection_handler
                target_action = {
                    "action": "charge",
                    "unitId": unit["id"],
                    "targetId": target_id
                }
                return charge_target_selection_handler(game_state, unit["id"], target_action)
            else:
                # No valid targets - auto skip
                return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def _ai_select_charge_target_pve(game_state: Dict[str, Any], unit: Dict[str, Any], valid_targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    PvE AI selects charge target using priority logic per AI_TURN.md.

    Priority order:
    1. Enemy closest to death (lowest HP_CUR)
    2. Highest threat (max of all weapons: STR × NB)
    """
    if not valid_targets:
        return None

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
    # Calculate priority score for each target
    def priority_score(t):
        # Priority 1: Lowest HP (higher priority = lower HP) (Phase 2: HP from cache)
        hp_cur = require_hp_from_cache(str(t["id"]), game_state)
        hp_priority = -hp_cur  # Negative so lower HP = higher score

        # Priority 2: Highest threat
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate threat from all weapons
        melee_threat = 0.0
        if t.get("CC_WEAPONS"):
            # Calculate max threat from all melee weapons
            for weapon in t["CC_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_melee_nb")
                melee_threat = max(melee_threat, threat)
        
        ranged_threat = 0.0
        if t.get("RNG_WEAPONS"):
            # Calculate max threat from all ranged weapons
            for weapon in t["RNG_WEAPONS"]:
                threat = require_key(weapon, "STR") * expected_dice_value(require_key(weapon, "NB"), "charge_ranged_nb")
                ranged_threat = max(ranged_threat, threat)
        
        threat = max(melee_threat, ranged_threat)

        return (hp_priority, threat)

    # Select target with highest priority
    best_target = max(valid_targets, key=priority_score)
    return best_target


def charge_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Charge unit activation initialization - NO ROLL YET.
    
    NEW RULE: At activation, unit can wait or choose a target.
    The charge roll is performed ONLY AFTER target selection.
    """
    game_state["valid_charge_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["active_charge_unit"] = unit_id
    # Do NOT roll 2d6 here - roll happens after target selection


def charge_build_valid_targets(game_state: Dict[str, Any], unit_id: str) -> List[Dict[str, Any]]:
    """
    Build list of valid charge targets for unit activation.
    
    Valid target criteria:
    - Enemy unit
    - within charge_max_distance hexes (via BFS pathfinding)
    - having non occupied adjacent hex(es) at 12 hexes or less from the active unit
    
    Returns list of target dicts with unit info.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
    
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(game_rules, "charge_max_distance")
    valid_targets = []
    
    # Build all hexes reachable via BFS within max charge distance
    try:
        reachable_hexes = charge_build_valid_destinations_pool(game_state, unit_id, CHARGE_MAX_DISTANCE)
    except Exception as e:
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit_id}: {str(e)}")
        return []
    
    if not reachable_hexes:
        return []  # No reachable hexes
    
    # Get all enemies - CRITICAL: is_unit_alive so dead units never enter pool
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
               if int(cache_entry["player"]) != unit_player]
    
    from engine.hex_utils import dilate_hex_set_unbounded
    from .shared_utils import get_engagement_zone, build_occupied_positions_set
    engagement_zone = get_engagement_zone(game_state)

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)

    unit_col_int, unit_row_int = require_unit_position(unit, game_state)
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col_int, unit_row_int)}) if unit_entry else {(unit_col_int, unit_row_int)}
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)

    enemy_index: List[Tuple[Any, Dict[str, Any], Set[Tuple[int, int]], Set[Tuple[int, int]]]] = []
    for enemy_id in enemies:
        enemy_entry = units_cache.get(str(enemy_id))
        if enemy_entry is None:
            raise KeyError(f"Enemy {enemy_id} not in units_cache (dead or absent)")
        ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
        enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
        shell = dilate_hex_set_unbounded(enemy_fp, engagement_zone)
        if unit_fp & shell:
            continue
        enemy_index.append((enemy_id, enemy_entry, enemy_fp, shell))

    per_enemy_has_geom: Dict[Any, bool] = {eid: False for eid, _, _, _ in enemy_index}
    per_enemy_non_occ: Dict[Any, bool] = {eid: False for eid, _, _, _ in enemy_index}

    for dest_col, dest_row in reachable_hexes:
        candidate_fp = _candidate_footprint_charge(dest_col, dest_row, unit, game_state, fp_offset_pair)
        blocked_by_occupation = bool(candidate_fp & occupied_positions)
        for enemy_id, _enemy_entry, enemy_fp, shell in enemy_index:
            if candidate_fp & enemy_fp:
                continue
            if candidate_fp & shell:
                per_enemy_has_geom[enemy_id] = True
                if not blocked_by_occupation:
                    per_enemy_non_occ[enemy_id] = True

    for enemy_id, enemy_entry, _enemy_fp, _shell in enemy_index:
        if per_enemy_has_geom.get(enemy_id) and per_enemy_non_occ.get(enemy_id):
            ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
            valid_targets.append({
                "id": enemy_id,
                "col": ec,
                "row": er,
                "HP_CUR": require_hp_from_cache(str(enemy_id), game_state),
                "player": enemy_entry["player"],
            })

    return valid_targets


def charge_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Charge unit execution loop - build and return valid charge targets.
    
    NEW RULE: At activation, show all possible charge targets without rolling.
    The roll happens AFTER target selection.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Build valid targets (enemies with non-occupied adjacent hexes reachable within 12 hexes)
    valid_targets = charge_build_valid_targets(game_state, unit_id)

    # Check if valid targets exist
    if not valid_targets:
        # No valid targets - pass (no step increment, no tracking)
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # Extract target IDs for blinking effect (PvP and PvE modes only)
    target_ids = [str(target["id"]) for target in valid_targets]
    
    # Check if PvP or PvE mode (not gym training)
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    should_blink = not is_gym  # Blink in PvP and PvE, not in gym training
    
    result = {
        "unit_activated": True,
        "unitId": unit_id,
        "charge_roll": None,  # No roll yet - will be rolled after target selection
        "valid_targets": valid_targets,  # List of target dicts
        "waiting_for_player": True
    }
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} charge_unit_execution_loop unit_id={unit_id} "
            f"valid_targets={len(valid_targets)} waiting_for_player=True"
        )
    
    # Add blinking effect for PvP and PvE modes
    if should_blink:
        result["blinking_units"] = target_ids
        result["start_blinking"] = True
    
    return True, result


def _attempt_charge_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md charge execution with destination validation.

    Implements AI_TURN.md charge restrictions:
    - Must end adjacent to target enemy
    - Within charge_range (2d6 roll result)
    - Path must be reachable via BFS pathfinding
    """
    # CRITICAL: Check units_fled just before execution (may have changed during phase)
    # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
    unit_id_str = str(unit["id"])
    if unit_id_str in require_key(game_state, "units_fled") and not _unit_has_rule(unit, "charge_after_flee"):
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        log_msg = f"[CHARGE ERROR] E{episode} T{turn} Unit {unit['id']} attempted to charge but has fled - REJECTED"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {"error": "unit_has_fled", "unitId": unit["id"], "action": "charge"}

    # Post-shoot movement restriction: cannot charge until end of turn.
    if unit_id_str in require_key(game_state, "units_cannot_charge"):
        return False, {
            "error": "unit_cannot_charge_after_move_after_shooting",
            "unitId": unit["id"],
            "action": "charge",
        }
    
    # NOTE: Pool is already built in charge_destination_selection_handler() after roll.
    # Since system is sequential, no need to rebuild here. Only verify destination is in pool.
    unit_id = unit["id"]
    if unit_id not in game_state["charge_roll_values"]:
        raise KeyError(f"Unit {unit_id} missing charge_roll_values")
    charge_roll = game_state["charge_roll_values"][unit_id]
    
    # Check if destination is in the pool (built after roll in charge_destination_selection_handler)
    dest_tuple = (int(dest_col), int(dest_row))
    pool = require_key(game_state, "valid_charge_destinations_pool")
    if dest_tuple not in pool:
        return False, {"error": "destination_not_in_pool", "target": (dest_col, dest_row), "action": "charge"}
    
    # Validate destination per AI_TURN.md charge rules
    if not _is_valid_charge_destination(game_state, dest_col, dest_row, unit, target_id, charge_roll, config):
        return False, {"error": "invalid_charge_destination", "target": (dest_col, dest_row), "action": "charge"}

    # Store original position
    orig_col, orig_row = require_unit_position(unit, game_state)

    # CRITICAL: Final occupation check IMMEDIATELY before position assignment
    # This prevents race conditions where multiple units select the same destination
    # before any of them have moved. Must check JUST before assignment, not earlier.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "charge")
    # CRITICAL: Normalize destination coordinates to int for consistent comparison
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)
    
    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    _fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(dest_col_int, dest_row_int, unit, game_state, _fp_pair)
    if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[CHARGE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot charge to ({dest_col_int},{dest_row_int}) - footprint blocked"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {
            "error": "charge_destination_occupied",
            "destination": (dest_col_int, dest_row_int)
        }

    # Execute charge - position assignment happens immediately after occupation check
    # CRITICAL: Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via CHARGE"
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)
    
    # CRITICAL: Normalize coordinates before assignment
    from engine.combat_utils import set_unit_coordinates
    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

    # Capture old footprint before cache update (for multi-hex adjacency delta)
    chg_uid_str = str(unit["id"])
    chg_old_entry = game_state.get("units_cache", {}).get(chg_uid_str)
    chg_old_occupied = chg_old_entry.get("occupied_hexes") if chg_old_entry else None

    # Update units_cache after position change
    update_units_cache_position(game_state, chg_uid_str, dest_col_int, dest_row_int)

    chg_new_entry = game_state.get("units_cache", {}).get(chg_uid_str)
    chg_new_occupied = chg_new_entry.get("occupied_hexes") if chg_new_entry else None

    moved_unit_player = int(require_key(unit, "player"))
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_int,
        new_row=dest_row_int,
        old_occupied=chg_old_occupied,
        new_occupied=chg_new_occupied,
    )

    # AI_TURN_SHOOTING_UPDATE.md: No need to invalidate los_cache here
    # The new architecture uses unit["los_cache"] which is built at unit activation in shooting phase
    # When a unit charges, los_cache doesn't exist yet (built at shooting activation)
    # Old code: _invalidate_los_cache_for_moved_unit(game_state, unit["id"]) - OBSOLETE

    # Mark as units_charged (NOT units_moved)
    game_state["units_charged"].add(unit["id"])

    # CRITICAL: Invalidate all destination pools after charge movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    from .movement_handlers import _invalidate_all_destination_pools_after_movement
    _invalidate_all_destination_pools_after_movement(game_state)

    # Clear charge roll, target selection, and pending targets after use
    if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit_id]
    if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit_id]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    return True, {
        "action": "charge",
        "unitId": unit["id"],
        "targetId": target_id,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll
    }


def _is_valid_charge_destination(game_state: Dict[str, Any], col: int, row: int, unit: Dict[str, Any],
                                 target_id: str, charge_roll: int, config: Dict[str, Any]) -> bool:
    """
    AI_TURN.md charge destination validation.

    Charge destination requirements:
    - Within board bounds
    - NOT a wall
    - NOT occupied by another unit
    - Adjacent to target enemy (distance <= melee_range from target) - GUARANTEED by pool
    - Reachable within charge_range (2d6 roll) via BFS pathfinding - GUARANTEED by pool

    NOTE: Pool already guarantees adjacency and reachability. This function only does defensive checks.
    """
    # CRITICAL: Convert coordinates to int for consistent comparison
    col_int, row_int = int(col), int(row)
    
    # Board bounds check
    if (col_int < 0 or row_int < 0 or
        col_int >= game_state["board_cols"] or
        row_int >= game_state["board_rows"]):
        return False

    # Wall collision check
    if (col_int, row_int) in game_state["wall_hexes"]:
        return False

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    _fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_charge(col_int, row_int, unit, game_state, _fp_pair)
    if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
        return False

    # CRITICAL: Verify destination is in the valid pool
    # The pool guarantees: adjacent to enemy, not occupied, reachable with charge_roll
    if "valid_charge_destinations_pool" not in game_state:
        return False  # Pool not built - invalid destination
    
    valid_pool = game_state["valid_charge_destinations_pool"]
    if (col_int, row_int) not in valid_pool:
        return False  # Destination not in valid pool - not reachable with this charge_roll or not adjacent to enemy
    
    return True


def _has_valid_charge_target(game_state: Dict[str, Any], unit: Dict[str, Any],
                            full_occupied_positions: Optional[Set[Tuple[int, int]]] = None) -> bool:
    """
    Check if unit has at least one valid charge target.

    AI_TURN.md Line 495: "Enemies exist within charge_max_distance hexes?"
    AI_TURN.md Line 562: "Enemy units within charge_max_distance hexes (via pathfinding)"

    CRITICAL: Must use BFS pathfinding distance, not straight-line distance.
    Build reachable hexes within max charge distance and check if any enemy
    is adjacent to those hexes.
    
    NOTE: Target can be at distance 13 because charge of 12 can reach adjacent to target at 13.
    
    Args:
        full_occupied_positions: Optional pre-computed set of all unit positions (from get_eligible_units).
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")
    _uid = str(unit["id"])
    _t_hvt0 = time.perf_counter() if _perf else None

    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(game_rules, "charge_max_distance")

    try:
        # BFS with early exit: any hex in charge_build_valid_destinations_pool already satisfies
        # engagement + placement rules (same as the old nested loop).
        valid_any = charge_build_valid_destinations_pool(
            game_state, unit["id"], CHARGE_MAX_DISTANCE,
            full_occupied_positions=full_occupied_positions,
            early_exit_if_valid=True,
        )
    except Exception as e:
        # If BFS fails, log error and return False (no valid targets)
        add_console_log(game_state, f"ERROR: BFS failed for unit {unit['id']}: {str(e)}")
        if _perf and _t_hvt0 is not None:
            append_perf_timing_line(
                f"CHARGE_HAS_VALID_TARGET episode={_ep} turn={_turn} unit_id={_uid} "
                f"bfs_pool_s={time.perf_counter() - _t_hvt0:.6f} nested_loop_s=0.000000 "
                f"reachable_n=0 enemy_n=0 outcome=bfs_error"
            )
        return False

    _t_after_bfs_pool = time.perf_counter() if _perf else None

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_n = sum(
        1 for _, enemy_entry in units_cache.items()
        if int(enemy_entry["player"]) != unit_player
    )

    outcome = "hit" if valid_any else "miss"
    if _perf and _t_hvt0 is not None and _t_after_bfs_pool is not None:
        append_perf_timing_line(
            f"CHARGE_HAS_VALID_TARGET episode={_ep} turn={_turn} unit_id={_uid} "
            f"bfs_pool_s={_t_after_bfs_pool - _t_hvt0:.6f} nested_loop_s=0.000000 "
            f"reachable_n={len(valid_any)} enemy_n={enemy_n} outcome={outcome}"
        )

    return bool(valid_any)


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is within engagement zone of any enemy (footprint distance).

    Used for charge eligibility — unit must NOT be already engaged.
    """
    from engine.utils.weapon_helpers import get_melee_range
    from engine.hex_utils import min_distance_between_sets
    cc_range = get_melee_range(game_state)
    unit_col, unit_row = require_unit_position(unit, game_state)

    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, enemy_entry in units_cache.items():
        if int(enemy_entry["player"]) != unit_player:
            enemy_fp = enemy_entry.get("occupied_hexes", {(enemy_entry["col"], enemy_entry["row"])})
            if min_distance_between_sets(unit_fp, enemy_fp, max_distance=cc_range) <= cc_range:
                return True
    return False


def _is_hex_adjacent_to_enemy(game_state: Dict[str, Any], col: int, row: int, player: int,
                               enemy_adjacent_hexes: Set[Tuple[int, int]] = None) -> bool:
    """
    AI_TURN.md adjacency restriction implementation.

    Check if hex position is adjacent to any enemy unit.

    CRITICAL FIX: Use proper hexagonal adjacency, not Chebyshev distance.
    Hexagonal grids require checking if enemy position is in the list of 6 neighbors.

    PERFORMANCE: If enemy_adjacent_hexes set is provided, uses O(1) set lookup
    instead of O(n) iteration through all units.
    """
    # PERFORMANCE: Use pre-computed set if available (5-10x speedup)
    if enemy_adjacent_hexes is not None:
        return (col, row) in enemy_adjacent_hexes

    # Calcul dynamique si aucun cache n'est fourni (comportement historique)
    hex_neighbors = set(get_hex_neighbors(col, row))

    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            # Check if enemy is in our 6 neighbors (true hex adjacency)
            if enemy_pos in hex_neighbors:
                return True
    return False


def _find_adjacent_enemy_at_destination(game_state: Dict[str, Any], col: int, row: int, player: int) -> Optional[str]:
    """
    Find an enemy unit adjacent to the given hex position.

    Used by gym training to auto-select charge target based on destination.
    Returns the ID of the first adjacent enemy, or None if no adjacent enemy.
    
    CRITICAL FIX: Also checks if enemy is ON the destination (distance == 0) and
    verifies that the destination is not occupied before returning target_id.
    """
    # First check if destination itself is occupied by an enemy (distance == 0)
    units_cache = require_key(game_state, "units_cache")
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            if enemy_pos == (col, row):
                # Enemy is ON the destination - this is invalid for charge
                return None
    
    # Then check neighbors (adjacent enemies, distance == 1)
    hex_neighbors = set(get_hex_neighbors(col, row))
    adjacent_enemies = []
    for enemy_id, enemy_entry in units_cache.items():
        if enemy_entry["player"] != player:
            enemy_pos = (enemy_entry["col"], enemy_entry["row"])
            if enemy_pos in hex_neighbors:
                adjacent_enemies.append(enemy_id)
    
    if adjacent_enemies:
        result_id = adjacent_enemies[0]
        return result_id
    else:
        return None


def charge_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str, charge_roll: int,
                                        target_id: Optional[str] = None,
                                        full_occupied_positions: Optional[Set[Tuple[int, int]]] = None,
                                        early_exit_if_valid: bool = False) -> List[Tuple[int, int]]:
    """
    Build valid charge destinations using BFS pathfinding.

    CRITICAL: Charge destinations must:
    - Be reachable within charge_roll distance (2d6) via BFS
    - Use a **legal footprint** at the end hex (``is_footprint_placement_valid``).
    - End in **engagement** vs the declared target (if ``target_id``) or vs **some** enemy :
      no overlap with enemy ``occupied_hexes``, and the footprint must intersect the
      **dilated** enemy footprint ``dilate_hex_set_unbounded(enemy_fp, engagement_zone)`` without
      overlapping the enemy core. For disjoint footprints this is **equivalent** to
      ``1 <= min_distance_between_sets <= engagement_zone`` (see ``hex_utils.dilate_hex_set_unbounded``).
      **Do not** call ``min_distance_between_sets`` inside this BFS — it would nest BFS per neighbor
      and destroy performance on large boards.

    Unlike movement, charges CAN move through hexes adjacent to enemies.

    Args:
        target_id: Optional target unit ID. If provided, only hexes engaging **this** target count.
        full_occupied_positions: Optional pre-computed set of all unit positions. If provided, unit's position
            is excluded internally. Used by get_eligible_units for performance.
        early_exit_if_valid: If True, stop the BFS as soon as one valid charge end hex is found
            (used for eligibility checks only). Does not populate the max-roll BFS cache.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _ep = game_state.get("episode_number", "?")
    _turn = game_state.get("turn", "?")

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    units_cache = require_key(game_state, "units_cache")

    charge_range = charge_roll  # 2d6 result
    _t_func0 = time.perf_counter() if _perf else None
    # CRITICAL: Normalize coordinates to int for consistent tuple comparison
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    # Get target enemy if specified, otherwise all enemies
    if target_id:
        target = get_unit_by_id(game_state, target_id)
        if not target or target["player"] == unit["player"] or not is_unit_alive(str(target["id"]), game_state):
            return []  # Invalid target
        enemies = [target]
    else:
        # Get all enemy positions for adjacency checks (used during activation preview)
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]
        if not enemies:
            return []  # No enemies to charge

    unit_id_str = str(unit["id"])
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    CHARGE_MAX_DISTANCE = require_key(game_rules, "charge_max_distance")
    tid_arg: Optional[str] = str(target_id) if target_id is not None else None
    bfs_max_distance = _charge_bfs_max_distance(game_state, unit_id_str, int(charge_range), tid_arg)
    cache = game_state.setdefault("_charge_dest_bfs_cache", {})
    cache_key = (unit_id_str, int(charge_range), target_id if target_id else None)
    if (
        not early_exit_if_valid
        and charge_range == CHARGE_MAX_DISTANCE
        and tid_arg is None
        and cache_key in cache
    ):
        cached_list = cache[cache_key]
        game_state["valid_charge_destinations_pool"] = cached_list
        if _perf and _t_func0 is not None:
            _t_done = time.perf_counter()
            append_perf_timing_line(
                f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
                f"bfs_loop_s=0.000000 total_s={_t_done - _t_func0:.6f} "
                f"visited_n=0 valid_dest_n={len(cached_list)} cache_hit=1 early_exit=0 short_circuit=0"
            )
        return cached_list

    if full_occupied_positions is not None:
        # Remove moving unit's footprint from the pre-computed set
        units_cache_ref = require_key(game_state, "units_cache")
        own_entry = units_cache_ref.get(unit_id_str)
        own_hexes = own_entry.get("occupied_hexes", {start_pos}) if own_entry else {start_pos}
        occupied_positions = full_occupied_positions - own_hexes
    else:
        occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)

    # Verbose debug: off unless W40K_CHARGE_DEBUG or game_state["charge_debug_positions"]
    if _charge_debug_positions_enabled(game_state) and "episode_number" in game_state and "turn" in game_state and "phase" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        phase = game_state.get("phase", "charge")
        def _hp_display(uid, gs):
            h = get_hp_from_cache(str(uid), gs)
            return h if h is not None else "dead"
        all_units_info = []
        for u_id, u_entry in units_cache.items():
            u_col, u_row = u_entry["col"], u_entry["row"]
            all_units_info.append(f"Unit {u_id} at ({int(u_col)},{int(u_row)}) HP={_hp_display(u_id, game_state)}")
        log_message = f"[CHARGE DEBUG] E{episode} T{turn} {phase} charge_build_valid_destinations Unit {unit_id}: occupied_positions={occupied_positions} all_units={all_units_info}"
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)

    # BFS pathfinding to find all reachable anchor positions within bfs_max_distance (jet + offset ×10)
    visited = {start_pos: 0}
    queue = deque([(start_pos, 0)])
    valid_destinations = []

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)
    _fp_tag = "offset" if fp_offset_pair is not None else "legacy"

    from engine.hex_utils import dilate_hex_set_unbounded
    from .shared_utils import get_engagement_zone

    engagement_zone = get_engagement_zone(game_state)

    indexed_enemy_engagement: List[Tuple[Any, Set[Tuple[int, int]], Set[Tuple[int, int]]]] = []
    for enemy_ref in enemies:
        eid = enemy_ref["id"] if isinstance(enemy_ref, dict) else enemy_ref
        enemy_entry = units_cache.get(str(eid))
        if enemy_entry is None:
            raise KeyError(f"Enemy {eid} not in units_cache (dead or absent)")
        ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
        enemy_fp = enemy_entry.get("occupied_hexes", {(ec, er)})
        shell = dilate_hex_set_unbounded(enemy_fp, engagement_zone)
        indexed_enemy_engagement.append((eid, enemy_fp, shell))

    _t_bfs0 = time.perf_counter() if _perf else None
    bfs_short_circuit = False
    while queue and not bfs_short_circuit:
        current_pos, current_dist = queue.popleft()
        current_col, current_row = current_pos

        if current_dist >= bfs_max_distance:
            continue

        neighbors = get_hex_neighbors(current_col, current_row)

        for neighbor_col, neighbor_row in neighbors:
            neighbor_col_int, neighbor_row_int = int(neighbor_col), int(neighbor_row)
            neighbor_pos = (neighbor_col_int, neighbor_row_int)
            neighbor_dist = current_dist + 1

            if neighbor_pos in visited:
                continue

            candidate_fp = _candidate_footprint_charge(
                neighbor_col_int, neighbor_row_int, unit, game_state, fp_offset_pair
            )

            if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
                continue

            visited[neighbor_pos] = neighbor_dist

            is_adjacent_to_enemy = False
            hex_overlaps_enemy = False
            for _eid, enemy_fp, shell in indexed_enemy_engagement:
                if candidate_fp & enemy_fp:
                    hex_overlaps_enemy = True
                    break
                if candidate_fp & shell:
                    is_adjacent_to_enemy = True
                    if tid_arg:
                        break

            if is_adjacent_to_enemy and not hex_overlaps_enemy and neighbor_pos != start_pos:
                valid_destinations.append(neighbor_pos)
                if early_exit_if_valid:
                    bfs_short_circuit = True
                    break

            queue.append((neighbor_pos, neighbor_dist))

    _t_bfs1 = time.perf_counter() if _perf else None

    game_state["valid_charge_destinations_pool"] = valid_destinations
    if charge_range == CHARGE_MAX_DISTANCE and not early_exit_if_valid and tid_arg is None:
        cache[cache_key] = list(valid_destinations)

    if _perf and _t_func0 is not None and _t_bfs0 is not None and _t_bfs1 is not None:
        _t_done = time.perf_counter()
        _ee = "1" if early_exit_if_valid else "0"
        _sc = "1" if bfs_short_circuit else "0"
        append_perf_timing_line(
            f"CHARGE_DEST_BFS episode={_ep} turn={_turn} unit_id={unit_id} charge_roll={charge_range} "
            f"bfs_max={bfs_max_distance} "
            f"bfs_loop_s={_t_bfs1 - _t_bfs0:.6f} total_s={_t_done - _t_func0:.6f} "
            f"visited_n={len(visited)} valid_dest_n={len(valid_destinations)} cache_hit=0 "
            f"early_exit={_ee} short_circuit={_sc} fp={_fp_tag}"
        )

    return valid_destinations




def _select_strategic_destination(
    strategy_id: int,
    valid_destinations: List[Tuple[int, int]],
    unit: Dict[str, Any],
    game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Select movement destination based on strategic heuristic.
    AI_TURN.md COMPLIANCE: Pure stateless function with direct field access.

    Args:
        strategy_id: 0=aggressive, 1=tactical, 2=defensive, 3=random
        valid_destinations: List of valid (col, row) tuples from BFS
        unit: Unit dict with position and stats
        game_state: Full game state for enemy detection

    Returns:
        Selected destination (col, row)
    """
    from engine.combat_utils import has_line_of_sight

    # Direct field access with validation
    if "units" not in game_state:
        raise KeyError("game_state missing required 'units' field")
    if "col" not in unit or "row" not in unit:
        raise KeyError(f"Unit missing required position fields: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")
    if "RNG_RNG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")

    # If no destinations, return current position
    if not valid_destinations:
        return require_unit_position(unit, game_state)

    # Get enemy units
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_units = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]

    # If no enemies, just pick first destination
    if not enemy_units:
        return valid_destinations[0]

    # Pre-build enemy positions from cache (avoids repeated require_unit_position calls)
    enemy_positions = {eid: (units_cache[str(eid)]["col"], units_cache[str(eid)]["row"]) for eid in enemy_units}

    # STRATEGY 0: AGGRESSIVE - Move closest to nearest enemy
    if strategy_id == 0:
        best_dest = valid_destinations[0]
        min_dist_to_enemy = float('inf')

        for dest in valid_destinations:
            # Find distance to nearest enemy from this destination
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_enemy:
                    min_dist_to_enemy = dist
                    best_dest = dest

        return best_dest

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    elif strategy_id == 1:
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        weapon_range = get_max_ranged_range(unit)
        best_dest = valid_destinations[0]
        max_targets = 0

        for dest in valid_destinations:
            targets_in_range = 0
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist <= weapon_range:
                    # Check LoS (simplified - assumes LoS if in range for now)
                    targets_in_range += 1

            if targets_in_range > max_targets:
                max_targets = targets_in_range
                best_dest = dest

        return best_dest

    # STRATEGY 2: DEFENSIVE - Move farthest from all enemies
    elif strategy_id == 2:
        best_dest = valid_destinations[0]
        max_min_dist = 0

        for dest in valid_destinations:
            # Find distance to nearest enemy (we want to maximize this)
            min_dist_to_any_enemy = float('inf')
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = _calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_any_enemy:
                    min_dist_to_any_enemy = dist

            if min_dist_to_any_enemy > max_min_dist:
                max_min_dist = min_dist_to_any_enemy
                best_dest = dest

        return best_dest

    # STRATEGY 3: RANDOM - Pick random destination for exploration
    else:
        import random
        return random.choice(valid_destinations)


def charge_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """Generate preview data for violet hexes (charge destinations)"""
    return {
        "violet_hexes": valid_destinations,  # Changed from green_hexes to violet_hexes
        "show_preview": True
    }


def charge_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clear charge preview"""
    game_state["preview_hexes"] = []
    game_state["valid_charge_destinations_pool"] = []
    # Clear active_charge_unit to allow next unit activation
    game_state["active_charge_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def charge_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Route charge click actions"""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "clickTarget" not in action:
        click_target = "elsewhere"
    else:
        click_target = action["clickTarget"]

    if click_target == "destination_hex":
        return charge_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "enemy" and "targetId" in action:
        # Click on enemy unit -> target selection (roll 2d6, build destinations)
        return charge_target_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented", "action": "charge"}
    elif click_target == "active_unit":
        # AI_TURN.md Line 1409: Left click on active_unit -> Charge postponed
        # Clear preview but keep unit in pool (different from skip which removes from pool)
        charge_clear_preview(game_state)
        # Clear charge roll and target selection if exists (postpone discards the roll)
        if "charge_roll_values" in game_state and unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "charge_postponed": True
        }
    else:
        return True, {"action": "continue_selection"}

def charge_target_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge target selection: roll 2d6, build pool, display preview.
    
    Flow:
    1. Agent chooses a target
    2. Roll 2d6
    3. Build pool of destinations for this target with the roll
    4. Display preview (violet hexes) for PvP/PvE modes
    5. Return waiting_for_player for destination selection
    """
    if "targetId" not in action:
        raise KeyError(f"Action missing required 'targetId' field: {action}")
    
    target_id = action["targetId"]
    if target_id is None:
        return False, {"error": "missing_target", "action": "charge"}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Re-evaluate adjacency at execution time.
    # Charge pool is built earlier and board state may change before target selection.
    if _is_adjacent_to_enemy(game_state, unit):
        return _handle_skip_action(game_state, unit, had_valid_destinations=False)

    # Roll 2d6 AFTER target selection — résultat en POUCES (règles GW).
    # Le badge UI affiche la valeur en inches (2..12). Sur Board ×10 les distances
    # moteur sont en sous-hex : on scale via ``inches_to_subhex`` pour rester homogène
    # avec ``charge_max_distance``, ``engagement_zone`` et les footprints.
    import random
    charge_roll = random.randint(1, 6) + random.randint(1, 6)
    game_state["charge_roll_values"][unit_id] = charge_roll
    _charge_scale = max(1, int(game_state.get("inches_to_subhex", 1) or 1))
    charge_roll_subhex = charge_roll * _charge_scale
    # Store target_id for destination selection
    if "charge_target_selections" not in game_state:
        game_state["charge_target_selections"] = {}
    game_state["charge_target_selections"][unit_id] = target_id
    
    # Clear pending targets after selection
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    # Build pool with actual roll for THIS SPECIFIC TARGET — zone cible-centrée
    # (spec utilisateur) : anneau autour de la cible [1 .. diamètre_chargeur + engagement_zone]
    # filtré par distance ≤ charge_roll depuis l'hex du chargeur le plus proche de la cible.
    _ref_c, _ref_r = require_unit_position(unit, game_state)
    charge_reference_hex: Tuple[int, int] = (int(_ref_c), int(_ref_r))
    target_unit_entry = get_unit_by_id(game_state, target_id)
    if (
        not target_unit_entry
        or target_unit_entry["player"] == unit["player"]
        or not is_unit_alive(str(target_unit_entry["id"]), game_state)
    ):
        display_zone_set: Set[Tuple[int, int]] = set()
        valid_pool: List[Tuple[int, int]] = []
    else:
        display_zone_set, closest_ch = _compute_charge_preview_zone(
            game_state, unit, target_unit_entry, int(charge_roll_subhex)
        )
        charge_reference_hex = (int(closest_ch[0]), int(closest_ch[1]))
        # Ancres géométriques (anneau cible + portée depuis l’hex allié le plus proche).
        zone_anchors = _build_charge_anchors_in_zone(
            game_state, unit, target_unit_entry, display_zone_set, int(charge_roll_subhex)
        )
        # BFS : chaque pas vérifie murs + empreintes (autres unités) — impossible de « traverser »
        # un mur ou un socle (allié ou ennemi) comme si c’était du vide. On garde l’intersection
        # avec la zone cible-centrée pour respecter la spec d’affichage autour de la cible.
        bfs_reachable = charge_build_valid_destinations_pool(
            game_state,
            str(unit_id),
            int(charge_roll_subhex),
            target_id=str(target_id),
        )
        bfs_set = set(bfs_reachable)
        valid_pool = [p for p in zone_anchors if p in bfs_set]
    game_state["valid_charge_destinations_pool"] = valid_pool
    if "debug_mode" in game_state and game_state["debug_mode"]:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[CHARGE TRACE] E{episode} T{turn} charge_target_selection unit_id={unit_id} "
            f"target_id={target_id} charge_roll={charge_roll} valid_pool={len(valid_pool)}"
        )

    # Check if pool is empty (roll too low)
    if not valid_pool:
        # Charge roll too low - charge failed
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        game_state["action_logs"].append({
            "type": "charge_fail",
            "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll} too low)",
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "timestamp": "server_time"
        })
        
        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        if "charge_target_selections" in game_state and unit_id in game_state["charge_target_selections"]:
            del game_state["charge_target_selections"][unit_id]
        
        # Clear preview
        charge_clear_preview(game_state)
        
        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
        
        # CRITICAL: Add start_pos and end_pos for proper logging (unit didn't move, so both are current position)
        # For failed charges with roll too low, there's no destination, so end_pos equals start_pos
        current_pos = require_unit_position(unit, game_state)
        action_logs = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": current_pos,  # Position actuelle (from) - unit didn't move
            "end_pos": current_pos,  # No destination (roll too low), so equals start_pos
            "activation_complete": True,
            "action_logs": action_logs
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Pool is valid - display preview (violet hexes) for PvP/PvE modes
    # Check if PvP or PvE mode
    is_pve = game_state.get("pve_mode", False) or game_state.get("is_pve_mode", False)
    is_gym = game_state.get("gym_training_mode", False)
    
    if not is_gym:  # PvP or PvE mode
        # Generate preview with violet hexes (charge destinations)
        preview_data = charge_preview(valid_pool)
        game_state["preview_hexes"] = valid_pool
        # Violet = union des empreintes finales légales (murs, occupation, engagement).
        # ``display_zone_set`` sert uniquement à énumérer les ancres candidates ; l'UI ne doit
        # pas montrer des hex « théoriques » où le socle ne peut pas tenir.
        display_union = _charge_footprint_union_for_anchors(
            game_state, str(unit_id), valid_pool
        )
        display_hexes = [[int(c), int(r)] for (c, r) in display_union]

        # Human players: return waiting_for_player for destination selection
        return True, {
            "action": "charge_target_selected",
            "unitId": unit_id,
            "targetId": target_id,
            "charge_roll": charge_roll,
            # Hex de référence pour la portée (empreinte chargeur la plus proche de la cible) —
            # l’UI doit l’utiliser pour la règle / tooltip ; ne pas le recalculer depuis units_cache.
            "charge_reference_hex": [charge_reference_hex[0], charge_reference_hex[1]],
            "valid_destinations": valid_pool,
            "charge_preview_display_hexes": display_hexes,
            "preview_data": preview_data,
            "clear_blinking_gentle": True,  # Stop blinking when target is selected
            "waiting_for_player": True  # Wait for destination selection
        }
    else:
        # AI_TURN.md COMPLIANCE: In gym training, AI selects destination automatically and executes charge
        # AI_TURN.md lines 1393-1396: Select destination hex → Move unit → end_activation
        # No preview needed, auto-select first valid destination
        preview_data = {}
        game_state["preview_hexes"] = []
        
        # Select first valid destination (AI chooses best destination automatically)
        if valid_pool:
            dest_col, dest_row = valid_pool[0]
            # Execute charge directly with selected destination
            destination_action = {
                "action": "charge",
                "unitId": unit_id,
                "targetId": target_id,
                "destCol": dest_col,
                "destRow": dest_row
            }
            return charge_destination_selection_handler(game_state, unit_id, destination_action)
        else:
            # No valid destinations (should not happen after pool check, but defensive)
            return False, {"error": "no_valid_destinations_after_target_selection", "action": "charge"}


def charge_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle charge destination selection and execute charge.
    
    This is called AFTER target selection and roll (charge_target_selection_handler).
    """
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")

    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination", "action": "charge"}
    
    # CRITICAL FIX: Normalize destination coordinates to int to ensure type consistency
    # This prevents type mismatch bugs (int vs float vs string) in position comparison
    try:
        dest_col, dest_row = normalize_coordinates(dest_col, dest_row)
    except (ValueError, TypeError):
        return False, {"error": "invalid_destination_type", "destCol": dest_col, "destRow": dest_row, "action": "charge"}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id, "action": "charge"}

    # Get target_id and charge_roll from previous step
    if "charge_target_selections" not in game_state or unit_id not in game_state["charge_target_selections"]:
        return False, {"error": "target_not_selected", "unit_id": unit_id, "action": "charge"}
    if "charge_roll_values" not in game_state or unit_id not in game_state["charge_roll_values"]:
        return False, {"error": "charge_roll_missing", "unit_id": unit_id, "action": "charge"}
    
    target_id = game_state["charge_target_selections"][unit_id]
    charge_roll = game_state["charge_roll_values"][unit_id]

    # Verify pool exists and destination is in it
    if "valid_charge_destinations_pool" not in game_state:
        return False, {"error": "destination_pool_not_built", "action": "charge"}
    
    valid_pool = game_state["valid_charge_destinations_pool"]

    resolved_anchor = _resolve_charge_dest_to_anchor(game_state, unit, valid_pool, dest_col, dest_row)
    if resolved_anchor is not None:
        dest_col, dest_row = resolved_anchor

    # Check if destination is in valid pool (reachable with this roll)
    if (dest_col, dest_row) not in valid_pool:
        # Charge roll too low - charge failed
        # Calculate distance for logging
        unit_col, unit_row = require_unit_position(unit, game_state)
        distance_to_dest = _calculate_hex_distance(unit_col, unit_row, dest_col, dest_row)
        
        # Log failure in action_logs
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        
        if "current_turn" not in game_state:
            current_turn = 1
        else:
            current_turn = game_state["current_turn"]
        
        game_state["action_logs"].append({
            "type": "charge_fail",
            "message": f"Unit {unit['id']} ({unit['col']}, {unit['row']}) FAILED charge to target {target_id} (Roll: {charge_roll}, needed: {distance_to_dest}+)",
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "player": unit["player"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "timestamp": "server_time"
        })
        
        # Clear charge roll after use
        if unit_id in game_state["charge_roll_values"]:
            del game_state["charge_roll_values"][unit_id]
        
        # Clear preview
        charge_clear_preview(game_state)
        
        # End activation with failure
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (charge failed)
            1,             # Arg2: +1 step increment (action was attempted)
            PASS,          # Arg3: NO tracking (charge didn't happen)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
        
        action_logs_val = game_state["action_logs"] if "action_logs" in game_state else []
        result.update({
            "action": "charge_fail",
            "unitId": unit["id"],
            "targetId": target_id,
            "charge_roll": charge_roll,
            "charge_failed": True,
            "charge_failed_reason": "roll_too_low",
            "start_pos": require_unit_position(unit, game_state),  # Position actuelle (from)
            "end_pos": (dest_col, dest_row),  # Destination prévue (to)
            "activation_complete": True,
            # CRITICAL: Include action_logs in result so they're sent to frontend
            "action_logs": action_logs_val
        })
        
        # Check if pool is now empty after removing this unit
        if not game_state["charge_activation_pool"]:
            phase_end_result = charge_phase_end(game_state)
            result.update(phase_end_result)
        
        return True, result

    # Charge roll is sufficient - execute charge
    # Execute charge using _attempt_charge_to_destination
    config = {}
    charge_success, charge_result = _attempt_charge_to_destination(game_state, unit, dest_col, dest_row, target_id, config)

    if not charge_success:
        # CRITICAL FIX: When charge fails, FORCE action type to charge_fail and add missing fields for proper logging
        # This prevents charge_fail actions from being logged as successful charges
        charge_result["action"] = "charge_fail"
        charge_result.setdefault("unitId", unit["id"])
        charge_result.setdefault("targetId", target_id)  # May be None, but needed for logging
        charge_result.setdefault("charge_failed_reason", charge_result.get("error", "unknown_error"))
        # CRITICAL: Add start_pos and end_pos for proper logging
        if "start_pos" not in charge_result:
            charge_result["start_pos"] = require_unit_position(unit, game_state)  # Position actuelle (from) - unit didn't move
        if "end_pos" not in charge_result:
            charge_result["end_pos"] = (dest_col, dest_row)  # Destination prévue (to) - even though charge failed
        return False, charge_result

    # Extract charge info
    orig_col = charge_result.get("fromCol")
    orig_row = charge_result.get("fromRow")

    # Position already updated by _attempt_charge_to_destination
    # CRITICAL FIX: Normalize types before comparison to prevent false negatives
    unit_col_int, unit_row_int = require_unit_position(unit, game_state)
    if unit_col_int != dest_col or unit_row_int != dest_row:
        return False, {
            "error": "position_update_failed", 
            "action": "charge",
            "expected": (dest_col, dest_row),
            "actual": require_unit_position(unit, game_state),
            "toCol": dest_col,
            "toRow": dest_row,
            "fromCol": orig_col,
            "fromRow": orig_row,
            "unitId": unit["id"]
        }

    # Generate charge log
    if "action_logs" not in game_state:
        game_state["action_logs"] = []

    # Calculate reward (simpler than movement - just charge action)
    action_reward = 0.0
    action_name = "CHARGE"

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    reward_configs = require_key(game_state, "reward_configs")
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    scenario_unit_type = require_key(unit, "unitType")
    reward_config_key = unit_registry.get_model_key(scenario_unit_type)

    unit_reward_config = require_key(reward_configs, reward_config_key)

    # Base charge reward is required in rewards config
    base_actions = require_key(unit_reward_config, "base_actions")
    action_reward = require_key(base_actions, "charge_success")

    # AI_TURN.md COMPLIANCE: Direct field access for current_turn
    if "current_turn" not in game_state:
        current_turn = 1  # Explicit default for turn counter
    else:
        current_turn = game_state["current_turn"]

    target_col, target_row = require_unit_position(target_id, game_state)
    charge_rule_marker = ""
    charge_ability_display_name = None
    if str(unit["id"]) in require_key(game_state, "units_fled") and _unit_has_rule(unit, "charge_after_flee"):
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_after_flee")
        if source_rule_display_name is None:
            raise ValueError(
                f"Unit {unit['id']} charged after flee without source unit rule"
            )
        charge_rule_marker = f" [{source_rule_display_name}]"
        charge_ability_display_name = source_rule_display_name
    elif str(unit["id"]) in require_key(game_state, "units_advanced") and _unit_has_rule(unit, "charge_after_advance"):
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_after_advance")
        if source_rule_display_name is None:
            raise ValueError(
                f"Unit {unit['id']} charged after advance without source unit rule"
            )
        charge_rule_marker = f" [{source_rule_display_name}]"
        charge_ability_display_name = source_rule_display_name
    charge_message = (
        f"Unit {unit['id']} ({orig_col}, {orig_row}) CHARGED{charge_rule_marker} "
        f"Unit {target_id} ({target_col}, {target_row}) from ({orig_col}, {orig_row}) "
        f"to ({dest_col}, {dest_row}) [Roll:{charge_roll}]"
    )

    game_state["action_logs"].append({
        "type": "charge",
        "message": charge_message,
        "turn": current_turn,
        "phase": "charge",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "targetId": target_id,
        "charge_roll": charge_roll,
        "ability_display_name": charge_ability_display_name,
        "timestamp": "server_time",
        "action_name": action_name,
        "reward": round(action_reward, 2),
        "is_ai_action": unit["player"] == 1
    })
    add_console_log(game_state, charge_message)

    if _unit_has_rule(unit, "charge_impact"):
        impact_ability_display_name = _get_source_unit_rule_display_name_for_effect(unit, "charge_impact")
        if impact_ability_display_name is None:
            unit_name = unit.get("DISPLAY_NAME") or unit.get("unitType") or "UNKNOWN"
            raise ValueError(
                f"Unit {unit['id']} ({unit_name}) triggered charge_impact without source rule displayName"
            )
        impact_roll = resolve_dice_value("D6", "charge_impact_roll")
        impact_hit_result = "FAIL"
        if impact_roll >= CHARGE_IMPACT_TRIGGER_THRESHOLD:
            impact_hit_result = "HIT"
            mortal_wounds = CHARGE_IMPACT_MORTAL_WOUNDS
            target_hp = require_hp_from_cache(str(target_id), game_state)
            new_target_hp = max(0, target_hp - mortal_wounds)
            update_units_cache_hp(game_state, str(target_id), new_target_hp)
        else:
            mortal_wounds = 0
        impact_message = (
            f"Unit {unit['id']}({dest_col},{dest_row}) IMPACTED [{impact_ability_display_name}] "
            f"Unit {target_id}({target_col},{target_row}) - "
            f"Hit:{CHARGE_IMPACT_TRIGGER_THRESHOLD}+:{impact_roll}({impact_hit_result})"
        )
        if impact_hit_result == "HIT":
            impact_message += f" Wound:AUTO Save:NONE[MW] Dmg:{mortal_wounds}HP"
        game_state["action_logs"].append({
            "type": "charge_impact",
            "message": impact_message,
            "turn": current_turn,
            "phase": "charge",
            "unitId": unit["id"],
            "targetId": target_id,
            "player": unit["player"],
            "impact_roll": impact_roll,
            "impact_threshold": CHARGE_IMPACT_TRIGGER_THRESHOLD,
            "impact_hit_result": impact_hit_result,
            "mortal_wounds": mortal_wounds,
            "ability_display_name": impact_ability_display_name,
            "attackerCol": dest_col,
            "attackerRow": dest_row,
            "targetCol": target_col,
            "targetRow": target_row,
            "reward": 0.0,
            "timestamp": "server_time",
            "is_ai_action": unit["player"] == 1,
        })
        add_console_log(game_state, impact_message)

    # Clear preview
    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    result = end_activation(
        game_state, unit,
        ACTION,        # Arg1: Log action
        1,             # Arg2: +1 step
        CHARGE,        # Arg3: CHARGE tracking
        CHARGE,        # Arg4: Remove from charge_activation_pool
        0              # Arg5: No error logging
    )
    
    # Update result with charge details
    result.update({
        "action": "charge",
        "phase": "charge",  # For metrics tracking
        "unitId": unit["id"],
        "targetId": target_id,
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "charge_roll": charge_roll,
        "ability_display_name": charge_ability_display_name,
        "charge_succeeded": True,  # For metrics tracking - successful charge
        "activation_complete": True
    })

    # Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def _is_adjacent_to_enemy_simple(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Flee detection: unit within engagement zone of any enemy (footprint distance).
    """
    from engine.utils.weapon_helpers import get_melee_range
    from engine.hex_utils import min_distance_between_sets
    cc_range = get_melee_range(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    for enemy_id, enemy_entry in units_cache.items():
        if int(enemy_entry["player"]) != unit_player:
            enemy_fp = enemy_entry.get("occupied_hexes", {(enemy_entry["col"], enemy_entry["row"])})
            if min_distance_between_sets(unit_fp, enemy_fp, max_distance=cc_range) <= cc_range:
                return True
    return False


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle skip action during charge phase

    Two cases per AI_TURN.md:
    - Line 515: Valid destinations exist, agent chooses wait -> end_activation (WAIT, 1, PASS, CHARGE)
    - Line 518/536: No valid destinations OR cancel -> end_activation (PASS, 0, PASS, CHARGE)
    """
    # Clear charge roll, target selection, and pending targets if unit skips
    if "charge_roll_values" in game_state and unit["id"] in game_state["charge_roll_values"]:
        del game_state["charge_roll_values"][unit["id"]]
    if "charge_target_selections" in game_state and unit["id"] in game_state["charge_target_selections"]:
        del game_state["charge_target_selections"][unit["id"]]
    if "pending_charge_targets" in game_state:
        del game_state["pending_charge_targets"]
    if "pending_charge_unit_id" in game_state:
        del game_state["pending_charge_unit_id"]

    charge_clear_preview(game_state)

    # AI_TURN.md EXACT: Different parameters based on whether valid destinations existed
    if had_valid_destinations:
        # AI_TURN.md Line 515: Agent actively chose to wait (valid destinations available)
        result = end_activation(
            game_state, unit,
            WAIT,          # Arg1: Log wait action
            1,             # Arg2: +1 step increment (action was taken)
            PASS,          # Arg3: NO tracking (wait does not mark as charged)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )
    else:
        # AI_TURN.md Line 518/536/542: No valid destinations or cancel
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging (no action taken)
            0,             # Arg2: NO step increment (no valid choice was made)
            PASS,          # Arg3: NO tracking (no charge happened)
            CHARGE,        # Arg4: Remove from charge_activation_pool
            0              # Arg5: No error logging
        )

    result.update({
        "action": "wait",
        "unitId": unit["id"],
        "activation_complete": True,
        "reset_mode": "select",
        "clear_selected_unit": True
    })

    # Check if pool is now empty after removing this unit
    if not game_state["charge_activation_pool"]:
        # Pool empty - phase complete
        phase_end_result = charge_phase_end(game_state)
        result.update(phase_end_result)

    return True, result


def charge_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Clean up and end charge phase"""
    charge_clear_preview(game_state)

    # Clear all charge rolls (phase complete)
    game_state["charge_roll_values"] = {}

    # Track phase completion reason
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'

    add_console_log(game_state, "CHARGE PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    charge_pool = require_key(game_state, "charge_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} charge charge_activation_pool={charge_pool}")

    return {
        "phase_complete": True,
        "next_phase": "fight",
        "units_processed": len([uid for uid in require_key(game_state, "units_cache").keys() if uid in game_state["units_charged"]])
    }


