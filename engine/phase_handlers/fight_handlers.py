#!/usr/bin/env python3
"""
engine/phase_handlers/fight_handlers.py - AI_TURN.md Fight Phase Implementation
Pure stateless functions implementing AI_TURN.md fight specification

References: AI_TURN.md Section ⚔️ FIGHT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns

CRITICAL: On ne tire PAS en phase de fight. La règle PISTOL permet de tirer en phase
de SHOOTING même si l'unité est adjacente à une unité ennemie (exception au "engaged").
"""

import os
import sys
import time
from collections import deque
from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from shared.data_validation import require_key
from engine.action_log_utils import append_action_log
from engine.game_utils import add_console_log, safe_print
from engine.combat_utils import (
    normalize_coordinates,
    calculate_hex_distance,
    get_unit_by_id,
    get_unit_coordinates,
    get_hex_neighbors,
    resolve_dice_value,
    set_unit_coordinates,
)
from engine.game_state import GameStateManager
from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH
from .shared_utils import (
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, PASS, ERROR, FIGHT,
    update_units_cache_hp, remove_from_units_cache,
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    build_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid,
    is_placement_valid_with_clearance,
    update_units_cache_position,
    translate_squad_to_destination,
    update_enemy_adjacent_caches_after_unit_move,
)

_ADJACENT_EDGE_GAP_TOLERANCE_NORM = ENGAGEMENT_NORM_HEX_WIDTH
FightFootprintOffsetPair = Optional[Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]]
_unit_registry_singleton = None  # UnitRegistry reads static files — safe to share across all episodes


def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific direct or granted rule effect by ruleId."""
    return shared_unit_has_rule_effect(unit, rule_id)


def _get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId that grants/owns the effect; None if absent."""
    return shared_get_source_unit_rule_id_for_effect(unit, effect_rule_id)


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.displayName for an effect rule; None if absent."""
    return shared_get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)


def _is_ai_controlled_fight_unit(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Return True when the unit owner is AI based on strict player_types mapping."""
    player_types = require_key(game_state, "player_types")
    if not isinstance(player_types, dict):
        raise TypeError(f"game_state['player_types'] must be a dict, got {type(player_types).__name__}")
    unit_player = str(require_key(unit, "player"))
    if unit_player not in player_types:
        raise KeyError(f"Missing player_types entry for player {unit_player}")
    return player_types[unit_player] == "ai"


def _is_fight_auto_execution_allowed(game_state: Dict[str, Any]) -> bool:
    """
    Return whether fight-phase auto execution is allowed for the current mode.

    PvP modes are strictly manual: no auto-activation, no auto-targeting,
    no auto-chain execution in fight phase.
    """
    mode_code = game_state.get("current_mode_code")
    if mode_code is None:
        return True
    if not isinstance(mode_code, str):
        raise TypeError(
            f"game_state['current_mode_code'] must be str when present, got {type(mode_code).__name__}"
        )
    if mode_code in {"pvp", "pvp_test"}:
        return False
    if mode_code in {"pve", "pve_test", "endless_duty"}:
        return True
    raise ValueError(f"Unsupported current_mode_code for fight auto execution: {mode_code}")


def _fight_verbose_debug_enabled() -> bool:
    """Actif si ``W40K_FIGHT_DEBUG`` vaut 1/true/yes/on (trace fight détaillée)."""
    v = os.environ.get("W40K_FIGHT_DEBUG", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _fight_verbose_trace(message: str) -> None:
    """
    Trace fight détaillée : **stderr uniquement**, indépendant de ``game_state['debug_mode']``
    et de ``console_logs`` (piste A : ne pas mélanger avec le debug training).
    """
    if not _fight_verbose_debug_enabled():
        return
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _is_unit_on_objective(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Return True if unit coordinates are inside any objective hex."""
    unit_col, unit_row = require_unit_position(unit, game_state)
    objectives = require_key(game_state, "objectives")
    if not isinstance(objectives, list):
        raise TypeError(f"game_state['objectives'] must be a list, got {type(objectives).__name__}")

    for objective in objectives:
        objective_hexes = require_key(objective, "hexes")
        if not isinstance(objective_hexes, list):
            raise TypeError(f"objective['hexes'] must be a list, got {type(objective_hexes).__name__}")
        for objective_hex in objective_hexes:
            if isinstance(objective_hex, dict):
                obj_col, obj_row = normalize_coordinates(
                    require_key(objective_hex, "col"),
                    require_key(objective_hex, "row")
                )
            elif isinstance(objective_hex, (list, tuple)) and len(objective_hex) == 2:
                obj_col, obj_row = normalize_coordinates(objective_hex[0], objective_hex[1])
            else:
                raise TypeError(
                    "objective hex entry must be {'col','row'} or [col,row]/(col,row), "
                    f"got {objective_hex!r}"
                )
            if unit_col == obj_col and unit_row == obj_row:
                return True
    return False


def _append_fight_nb_roll_info_log(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon: Dict[str, Any],
    nb_roll: int
) -> None:
    """
    Append informational log line for randomized melee attack count rolls.
    """
    nb_value = require_key(weapon, "NB")
    if not isinstance(nb_value, str):
        return

    unit_id = require_key(unit, "id")
    unit_col, unit_row = require_unit_position(unit, game_state)
    weapon_name = str(require_key(weapon, "display_name"))

    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    append_action_log(
        game_state,
        {
            "type": "roll_info",
            "phase": "FIGHT",
            "player": require_key(unit, "player"),
            "unitId": unit_id,
            "message": (
                f"Unit {unit_id}({unit_col},{unit_row}) FIGHTS with [{weapon_name}]. "
                f"Number of attacks ({nb_value}): {nb_roll}"
            ),
        },
    )

# [V10 fight_phase_start supprimé — remplacé par fight_phase_start V11 (voir plus bas).
#  fight_build_activation_pools reste défini ci-dessous : encore utilisé par
#  tests/unit/engine/test_fight_activation_pools.py.]


def fight_build_activation_pools(game_state: Dict[str, Any]) -> None:
    """
    Build all 3 fight phase activation pools.

    Sub-Phase 1: charging_activation_pool (current player's charging units)
    Sub-Phase 2: active_alternating_activation_pool + non_active_alternating_activation_pool
    Sub-Phase 3: Cleanup (handled by sub-phase 2 logic when one pool empty)

    CRITICAL: Non-active player goes first in alternating phase per AI_TURN.md.
    """
    current_player = require_key(game_state, "current_player")
    try:
        current_player_int = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player_int not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player_int}")
    game_state["current_player"] = current_player_int
    current_player = current_player_int

    non_active_player = 3 - current_player

    # AI_TURN.md COMPLIANCE: Ensure units_fought exists before any checks
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()

    # AI_TURN.md COMPLIANCE: units_charged must exist (set by charge phase)
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field - charge phase must run before fight phase")
    units_charged_set = {str(uid) for uid in game_state["units_charged"]}
    units_fought_set = {str(uid) for uid in game_state["units_fought"]}

    # Sub-Phase 1: Charging units (current player only, units in units_charged AND adjacent)
    # CRITICAL: Clear pools before rebuilding (defense in depth)
    game_state["charging_activation_pool"] = []
    game_state["active_alternating_activation_pool"] = []
    game_state["non_active_alternating_activation_pool"] = []
    charging_activation_pool = []
    add_console_log(game_state, f"FIGHT POOL BUILD: Building charging pool for player {current_player}")
    units_cache = require_key(game_state, "units_cache")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if cache_entry["player"] == current_player:
            if str(unit_id) in units_fought_set:
                continue
            if str(unit_id) in units_charged_set:
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
                if valid_targets:
                    charging_activation_pool.append(unit_id)
                    add_console_log(game_state, f"ADDED TO CHARGING POOL: Unit {unit_id}")

    game_state["charging_activation_pool"] = charging_activation_pool
    add_console_log(game_state, f"CHARGING POOL SIZE: {len(charging_activation_pool)}")
    
    # DEBUG: Log all units in charging pool
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        for unit_id in charging_activation_pool:
            unit = get_unit_by_id(game_state, unit_id)
            if unit:
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight build_pools: Unit {unit_id} (player {unit['player']}) ADDED to charging_pool"
                _fight_verbose_trace(log_msg)

    # Sub-Phase 2: Alternating activation (units NOT in units_charged, adjacent to enemies)
    active_alternating = []
    non_active_alternating = []

    add_console_log(game_state, f"FIGHT POOL BUILD: Building alternating pools")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if str(unit_id) in units_fought_set:
            continue
        if str(unit_id) not in units_charged_set:
            valid_targets = _fight_build_valid_target_pool(game_state, unit)
            if valid_targets:
                if cache_entry["player"] == current_player:
                    active_alternating.append(unit_id)
                    add_console_log(game_state, f"ADDED TO ACTIVE ALTERNATING: Unit {unit_id} (player {cache_entry['player']})")
                else:
                    non_active_alternating.append(unit_id)
                    add_console_log(game_state, f"ADDED TO NON-ACTIVE ALTERNATING: Unit {unit_id} (player {cache_entry['player']})")

    game_state["active_alternating_activation_pool"] = active_alternating
    game_state["non_active_alternating_activation_pool"] = non_active_alternating
    add_console_log(game_state, f"ALTERNATING POOLS: active={len(active_alternating)}, non_active={len(non_active_alternating)}")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(
        game_state,
        f"[POOL BUILD] E{episode} T{turn} fight charging_activation_pool={charging_activation_pool} "
        f"active_alternating_activation_pool={active_alternating} "
        f"non_active_alternating_activation_pool={non_active_alternating}"
    )


def _fight_maybe_lazy_rebuild_alternating_pools(game_state: Dict[str, Any]) -> None:
    """
    Reconstruit ``active_alternating_activation_pool`` / ``non_active_alternating_activation_pool``
    via ``_rebuild_alternating_pools_for_fight`` uniquement lorsque la sous-phase **charge**
    est terminée (pool charge vide). À utiliser après une mort en fight ou un déplacement
    de consolidation ; le passage charge → alternance est déclenché depuis ``end_activation``.
    """
    if game_state.get("phase") != "fight":
        return
    charging = game_state.get("charging_activation_pool")
    if charging is not None and len(charging) > 0:
        return
    from .generic_handlers import _rebuild_alternating_pools_for_fight

    _rebuild_alternating_pools_for_fight(game_state)


def _remove_dead_unit_from_fight_pools(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    CRITICAL: Immediately remove a dead unit from all fight activation pools.
    
    This must be called as soon as a unit dies to prevent it from being activated
    in subsequent sub-phases of the same fight phase.
    """
    unit_id_str = str(unit_id)
    
    # Remove from charging pool
    if "charging_activation_pool" in game_state:
        game_state["charging_activation_pool"] = [uid for uid in game_state["charging_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from active alternating pool
    if "active_alternating_activation_pool" in game_state:
        game_state["active_alternating_activation_pool"] = [uid for uid in game_state["active_alternating_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from non-active alternating pool
    if "non_active_alternating_activation_pool" in game_state:
        game_state["non_active_alternating_activation_pool"] = [uid for uid in game_state["non_active_alternating_activation_pool"] if str(uid) != unit_id_str]
    
    # CRITICAL: Also remove from other phase pools (units can die in fight but be in other pools)
    # Import from shooting_handlers to reuse the function
    from .shooting_handlers import _remove_dead_unit_from_pools
    _remove_dead_unit_from_pools(game_state, unit_id)

    _fight_maybe_lazy_rebuild_alternating_pools(game_state)


def _fight_enemy_footprint_distances(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
) -> List[Tuple[Any, int]]:
    """Return fight footprint distances to enemy units using the B/engagement metric."""
    from engine.spatial_relations import enemy_footprint_distances

    return enemy_footprint_distances(game_state, unit, max_distance=None)


def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is adjacent to at least one enemy within engagement zone.

    Uses min distance between footprints (§3.3, §9.8) for multi-hex units.
    For legacy boards (engagement_zone=1, single-hex), equivalent to hex distance <= 1.
    """
    from engine.spatial_relations import get_engagement_zone
    from engine.spatial_relations import unit_within_engagement_zone_footprints
    cc_range = get_engagement_zone(game_state)

    if "console_logs" not in game_state:
        game_state["console_logs"] = []

    if unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=cc_range, max_distance=cc_range
    ):
        add_console_log(game_state, f"FIGHT ELIGIBLE: Unit {unit['id']} within engagement_zone {cc_range}")
        return True

    add_console_log(game_state, f"FIGHT NOT ELIGIBLE: Unit {unit['id']} has no enemies within engagement_zone {cc_range}")
    return False


def _fight_footprint_has_enemy_hex_contact(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    fp: Set[Tuple[int, int]],
) -> bool:
    """Return True when a footprint has A/contact hex adjacency with any enemy footprint."""
    from engine.hex_utils import min_distance_between_sets

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_id_str = str(unit["id"])
    for enemy_id, cache_entry in units_cache.items():
        if str(enemy_id) == unit_id_str:
            continue
        if int(cache_entry["player"]) == unit_player:
            continue
        enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
        if min_distance_between_sets(fp, enemy_fp, max_distance=1) <= 1:
            return True
    return False


def _fight_unit_is_hex_adjacent_to_enemy_footprint(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    « Collé » : au moins un hex de l'empreinte partage un bord avec un hex d'empreinte ennemie
    (distance minimale entre empreintes == 1).
    """
    unit_col, unit_row = require_unit_position(unit, game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    return _fight_footprint_has_enemy_hex_contact(game_state, unit, unit_fp)


def _fight_pile_in_closest_enemy_snapshot(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[int, List[str]]:
    """
    Retourne (d_min, ids des unités ennemies dont l'empreinte est à distance minimale d_min).
    """
    from engine.hex_utils import min_distance_between_sets

    unit_col, unit_row = require_unit_position(unit, game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}
    unit_player = int(unit["player"]) if unit["player"] is not None else None

    d_cap: Optional[int] = None
    for ce in units_cache.values():
        if int(ce["player"]) == unit_player:
            continue
        approx = abs(unit_col - int(ce["col"])) + abs(unit_row - int(ce["row"]))
        if d_cap is None or approx < d_cap:
            d_cap = approx

    d_min: Optional[int] = None
    closest_ids: List[str] = []
    for enemy_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) == unit_player:
            continue
        enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
        if d_min is not None and d_cap is not None:
            cap = min(d_cap, d_min)
        elif d_min is not None:
            cap = d_min
        else:
            cap = d_cap
        d = min_distance_between_sets(unit_fp, enemy_fp, max_distance=cap if cap is not None else 0)
        if d_min is not None and d > d_min:
            continue
        if d_min is None or d < d_min:
            d_min = d
            closest_ids = [str(enemy_id)]
        elif d == d_min:
            closest_ids.append(str(enemy_id))

    if d_min is None:
        raise ValueError("_fight_pile_in_closest_enemy_snapshot: no enemy on board")
    return d_min, closest_ids


def _fight_pile_in_new_fp_strictly_closer_to_closest_tier(
    game_state: Dict[str, Any],
    new_fp: Set[Tuple[int, int]],
    d_min: int,
    closest_ids: List[str],
    *,
    closest_enemy_fps: Optional[List[Set[Tuple[int, int]]]] = None,
    closer_shell_union: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """True si la nouvelle empreinte est strictement plus proche d'au moins une unité du palier le plus proche."""
    if d_min <= 0:
        return False
    if closer_shell_union is not None:
        return bool(new_fp & closer_shell_union)
    from engine.hex_utils import min_distance_between_sets

    enemy_fps = closest_enemy_fps
    if enemy_fps is None:
        units_cache = require_key(game_state, "units_cache")
        enemy_fps = []
        for eid in closest_ids:
            ce = units_cache.get(str(eid))
            if not ce:
                continue
            enemy_fps.append(ce.get("occupied_hexes", {(ce["col"], ce["row"])}))
    radius = d_min - 1
    for efp in enemy_fps:
        d = min_distance_between_sets(new_fp, efp, max_distance=radius)
        if d <= radius:
            return True
    return False


def _fight_pile_in_anchor_adjacent_to_enemy_footprint(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
    target_ids: Optional[List[str]] = None,
    *,
    candidate_footprint: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """
    True si l'empreinte à cette ancre est dans la zone d'engagement d'une cible.

    Pour deux socles ronds, "adjacent" signifie collé bord-à-bord, pas simplement
    dans la zone d'engagement (10 sous-hexes autour de l'empreinte).
    """
    from engine.hex_utils import (
        euclidean_edge_clearance_round_round,
        min_distance_between_sets,
    )
    from engine.spatial_relations import get_engagement_zone

    candidate_fp = candidate_footprint
    if candidate_fp is None:
        candidate_fp = compute_candidate_footprint(int(anchor_col), int(anchor_row), unit, game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_id_str = str(unit["id"])
    target_filter = {str(t) for t in target_ids} if target_ids is not None else None
    cc_range = get_engagement_zone(game_state)
    unit_shape = unit["BASE_SHAPE"]
    unit_base_size = unit["BASE_SIZE"]
    for enemy_id, cache_entry in units_cache.items():
        if str(enemy_id) == unit_id_str:
            continue
        if target_filter is not None and str(enemy_id) not in target_filter:
            continue
        if int(cache_entry["player"]) == unit_player:
            continue
        enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
        enemy_shape = cache_entry["BASE_SHAPE"]
        enemy_base_size = cache_entry["BASE_SIZE"]
        if (
            unit_shape == "round"
            and enemy_shape == "round"
            and isinstance(unit_base_size, int)
            and isinstance(enemy_base_size, int)
        ):
            gap = euclidean_edge_clearance_round_round(
                int(anchor_col),
                int(anchor_row),
                unit_base_size,
                int(cache_entry["col"]),
                int(cache_entry["row"]),
                enemy_base_size,
            )
            # Le non-chevauchement est déjà garanti par is_footprint_placement_valid
            # lors de la construction du pool. Ici "adjacent" = bord-à-bord collé,
            # pas "dans la zone d'engagement".
            if gap <= _ADJACENT_EDGE_GAP_TOLERANCE_NORM:
                return True
            continue
        if min_distance_between_sets(candidate_fp, enemy_fp, max_distance=cc_range) <= cc_range:
            return True
    return False


def _fight_pile_in_bfs_numpy(
    board_cols: int,
    board_rows: int,
    start_col: int,
    start_row: int,
    bfs_max: int,
    off_even_arr: "Any",
    off_odd_arr: "Any",
    obstacles: Set[Tuple[int, int]],
    closer_shell_union: Set[Tuple[int, int]],
) -> List[Tuple[int, int]]:
    """Numpy-vectorised BFS for fight pile-in (multi-hex units on ×10 boards).

    Operates on a subgrid [c0..c1] × [r0..r1] centered on start to minimise
    array size and speed up dilation/spread operations.
    """
    import numpy as np

    # Subgrid: BFS radius + footprint radius (max footprint offset + 1)
    fp_radius = max(
        int(np.abs(off_even_arr).max()),
        int(np.abs(off_odd_arr).max()),
    ) + 1
    margin = bfs_max + fp_radius + 1
    c0 = max(0, start_col - margin); c1 = min(board_cols, start_col + margin + 1)
    r0 = max(0, start_row - margin); r1 = min(board_rows, start_row + margin + 1)
    W = c1 - c0; H = r1 - r0

    # Local coordinates
    sc = start_col - c0; sr = start_row - r0

    # Local parity depends on absolute column index
    col_is_even = ((np.arange(c0, c1, dtype=np.int64)) & 1) == 0
    col_parity_mask = np.broadcast_to(col_is_even[:, None], (W, H)).copy()

    def _spread(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        out = np.zeros_like(src)
        for dc, dr in kernel:
            sl = max(0, -int(dc)); sh = W - max(0, int(dc))
            rl = max(0, -int(dr)); rh = H - max(0, int(dr))
            if sl >= sh or rl >= rh:
                continue
            out[sl + int(dc):sh + int(dc), rl + int(dr):rh + int(dr)] |= src[sl:sh, rl:rh]
        return out

    def _dilate(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        out = np.zeros_like(src)
        for dc, dr in kernel:
            sl = max(0, int(dc)); sh = W - max(0, -int(dc))
            rl = max(0, int(dr)); rh = H - max(0, -int(dr))
            if sl >= sh or rl >= rh:
                continue
            out[sl - int(dc):sh - int(dc), rl - int(dr):rh - int(dr)] |= src[sl:sh, rl:rh]
        return out

    def _mask_from(cells: Set[Tuple[int, int]]) -> "np.ndarray":
        m = np.zeros((W, H), dtype=bool)
        if not cells:
            return m
        cs = np.fromiter((c - c0 for c, _ in cells), dtype=np.int64, count=len(cells))
        rs = np.fromiter((r - r0 for _, r in cells), dtype=np.int64, count=len(cells))
        valid = (cs >= 0) & (cs < W) & (rs >= 0) & (rs < H)
        m[cs[valid], rs[valid]] = True
        return m

    nb_even = np.array([(0,-1),(1,-1),(1,0),(0,1),(-1,0),(-1,-1)], dtype=np.int64)
    nb_odd  = np.array([(0,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0)],   dtype=np.int64)

    # bad_placement[lc, lr] = footprint at absolute (lc+c0, lr+r0) overlaps obstacles or OOB
    obs_mask = _mask_from(obstacles)
    bad_e = _dilate(obs_mask, off_even_arr)
    bad_o = _dilate(obs_mask, off_odd_arr)
    bad_placement = np.where(col_parity_mask, bad_e, bad_o)
    # OOB: anchor (c, r) is OOB if any footprint cell falls outside the full board
    min_dc_e = int(off_even_arr[:, 0].min()); max_dc_e = int(off_even_arr[:, 0].max())
    min_dr_e = int(off_even_arr[:, 1].min()); max_dr_e = int(off_even_arr[:, 1].max())
    min_dc_o = int(off_odd_arr[:, 0].min());  max_dc_o = int(off_odd_arr[:, 0].max())
    min_dr_o = int(off_odd_arr[:, 1].min());  max_dr_o = int(off_odd_arr[:, 1].max())
    abs_cols = np.arange(c0, c1, dtype=np.int64)[:, None]
    abs_rows = np.arange(r0, r1, dtype=np.int64)[None, :]
    oob_e = ((abs_cols + min_dc_e < 0) | (abs_cols + max_dc_e >= board_cols) |
             (abs_rows + min_dr_e < 0) | (abs_rows + max_dr_e >= board_rows))
    oob_o = ((abs_cols + min_dc_o < 0) | (abs_cols + max_dc_o >= board_cols) |
             (abs_rows + min_dr_o < 0) | (abs_rows + max_dr_o >= board_rows))
    bad_placement |= np.where(col_parity_mask, oob_e, oob_o)
    allowed = ~bad_placement
    allowed[sc, sr] = True

    # in_shell[lc, lr] = footprint at that anchor overlaps closer_shell_union
    shell_mask = _mask_from(closer_shell_union)
    in_shell_e = _dilate(shell_mask, off_even_arr)
    in_shell_o = _dilate(shell_mask, off_odd_arr)
    in_shell = np.where(col_parity_mask, in_shell_e, in_shell_o)

    # BFS spread within the subgrid
    reach = np.zeros((W, H), dtype=bool)
    reach[sc, sr] = True
    for _ in range(bfs_max):
        even_src = reach & col_parity_mask
        odd_src  = reach & ~col_parity_mask
        new_reach = reach | (_spread(even_src, nb_even) & allowed) | (_spread(odd_src, nb_odd) & allowed)
        if np.array_equal(new_reach, reach):
            break
        reach = new_reach

    valid_mask = reach & allowed & in_shell
    valid_mask[sc, sr] = False

    lc, lr = np.where(valid_mask)
    return [(int(c + c0), int(r + r0)) for c, r in zip(lc, lr)]


def _fight_build_pile_in_valid_destinations(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    d_min: int,
    closest_ids: List[str],
    contact_target_ids: List[str],
) -> List[Tuple[int, int]]:
    """
    BFS jusqu'à 3\" (× inches_to_subhex) : mêmes contraintes de placement que charge
    (empreinte légale, pas chevauchement), avec fin strictement plus proche d'une cible du palier d'activation.

    Si au moins une ancre valide permet de finir au **même contact bord-à-bord / empreinte**
    que ``_fight_pile_in_anchor_adjacent_to_enemy_footprint`` vs une cible CC éligible **ou**
    une unité du palier ``closest_ids`` (même sémantique que la consolidation « contact »), seules
    ces ancres sont proposées. Sinon repli sur toutes les ancres strictement plus proches.

    PERF : si ``d_min <= 1``, aucune ancre ne peut être strictement plus proche sans overlap ;
    retour immédiat sans BFS. Empreintes des destinations valides réutilisées pour le filtre contact.
    """
    if d_min <= 1:
        return []

    scale = game_state["inches_to_subhex"]
    bfs_max = 3 * scale

    unit_id_str = str(unit["id"])
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)

    _bfs_board_cols = int(require_key(game_state, "board_cols"))
    _bfs_board_rows = int(require_key(game_state, "board_rows"))
    _bfs_wall_hexes: Set[Tuple[int, int]] = game_state.get("wall_hexes", set())

    from engine.hex_utils import precompute_footprint_offsets
    from engine.phase_handlers.shared_utils import get_engagement_zone as _get_ez
    _bfs_ez = _get_ez(game_state)
    _bfs_base_size = unit["BASE_SIZE"]
    _bfs_single_hex = (_bfs_ez <= 1 or _bfs_base_size == 1)
    _bfs_off_e: Tuple[Tuple[int, int], ...] = ()
    _bfs_off_o: Tuple[Tuple[int, int], ...] = ()

    if not _bfs_single_hex:
        _bfs_shape = unit["BASE_SHAPE"]
        _bfs_orient = int(unit["orientation"])
        _bfs_off_e, _bfs_off_o = precompute_footprint_offsets(_bfs_shape, _bfs_base_size, _bfs_orient)

    # Precompute closer_shell_union: union of all hexes within (d_min-1) hex steps
    # from any closest enemy footprint.
    units_cache_pre = require_key(game_state, "units_cache")
    closest_enemy_fps_pre: List[Set[Tuple[int, int]]] = []
    for eid in closest_ids:
        ce = units_cache_pre.get(str(eid))
        if ce:
            closest_enemy_fps_pre.append(ce.get("occupied_hexes", {(ce["col"], ce["row"])}))
    closer_shell_union: Set[Tuple[int, int]] = set()
    if closest_enemy_fps_pre and d_min > 1:
        seed: Set[Tuple[int, int]] = set()
        for efp in closest_enemy_fps_pre:
            seed.update(efp)
        shell_visited = set(seed)
        frontier = list(seed)
        for _ in range(d_min - 1):
            next_frontier: List[Tuple[int, int]] = []
            for c, r in frontier:
                for nc, nr in get_hex_neighbors(c, r):
                    if (nc, nr) not in shell_visited:
                        shell_visited.add((nc, nr))
                        next_frontier.append((nc, nr))
            frontier = next_frontier
        closer_shell_union = shell_visited

    # For multi-hex units on large boards, use numpy-vectorised BFS (avoids per-position set construction)
    import numpy as np
    _use_numpy = (not _bfs_single_hex and _bfs_off_e and _bfs_off_o and
                  _bfs_board_cols * _bfs_board_rows >= 10000)
    if _use_numpy:
        import numpy as np
        _off_e_arr = np.asarray(_bfs_off_e, dtype=np.int64).reshape(-1, 2)
        _off_o_arr = np.asarray(_bfs_off_o, dtype=np.int64).reshape(-1, 2)
        obstacles = _bfs_wall_hexes | occupied_positions
        valid_destinations = _fight_pile_in_bfs_numpy(
            _bfs_board_cols, _bfs_board_rows,
            start_col, start_row, bfs_max,
            _off_e_arr, _off_o_arr,
            obstacles, closer_shell_union,
        )
        pile_in_fp_by_anchor: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {}
        for vc, vr in valid_destinations:
            _offs = _bfs_off_e if (vc & 1) == 0 else _bfs_off_o
            pile_in_fp_by_anchor[(vc, vr)] = {(vc + dc, vr + dr) for dc, dr in _offs}
    else:
        _closer_shell: Optional[Set[Tuple[int, int]]] = closer_shell_union if closer_shell_union else None
        _bfs_bbox_e: Optional[Tuple[int, int, int, int]] = None
        _bfs_bbox_o: Optional[Tuple[int, int, int, int]] = None
        if not _bfs_single_hex and _bfs_off_e:
            _bfs_bbox_e = (min(dc for dc, dr in _bfs_off_e), max(dc for dc, dr in _bfs_off_e),
                           min(dr for dc, dr in _bfs_off_e), max(dr for dc, dr in _bfs_off_e))
        if not _bfs_single_hex and _bfs_off_o:
            _bfs_bbox_o = (min(dc for dc, dr in _bfs_off_o), max(dc for dc, dr in _bfs_off_o),
                           min(dr for dc, dr in _bfs_off_o), max(dr for dc, dr in _bfs_off_o))
        visited: Dict[Tuple[int, int], int] = {start_pos: 0}
        queue = deque([(start_pos, 0)])
        valid_destinations = []
        pile_in_fp_by_anchor = {}

        while queue:
            current_pos, current_dist = queue.popleft()
            current_col, current_row = current_pos
            if current_dist >= bfs_max:
                continue
            neighbor_dist = current_dist + 1
            for neighbor_col, neighbor_row in get_hex_neighbors(current_col, current_row):
                neighbor_pos = (neighbor_col, neighbor_row)
                if neighbor_pos in visited:
                    continue
                if _bfs_single_hex:
                    if (neighbor_col < 0 or neighbor_row < 0 or
                            neighbor_col >= _bfs_board_cols or neighbor_row >= _bfs_board_rows):
                        continue
                    if neighbor_pos in _bfs_wall_hexes or neighbor_pos in occupied_positions:
                        continue
                    visited[neighbor_pos] = neighbor_dist
                    queue.append((neighbor_pos, neighbor_dist))
                    if neighbor_pos == start_pos:
                        continue
                    if _closer_shell is not None and neighbor_pos not in _closer_shell:
                        continue
                    valid_destinations.append(neighbor_pos)
                    pile_in_fp_by_anchor[neighbor_pos] = {neighbor_pos}
                else:
                    _bbox = _bfs_bbox_e if (neighbor_col & 1) == 0 else _bfs_bbox_o
                    if _bbox is not None:
                        _min_dc, _max_dc, _min_dr, _max_dr = _bbox
                        if (neighbor_col + _min_dc < 0 or
                                neighbor_col + _max_dc >= _bfs_board_cols or
                                neighbor_row + _min_dr < 0 or
                                neighbor_row + _max_dr >= _bfs_board_rows):
                            visited[neighbor_pos] = neighbor_dist
                            continue
                    _offs = _bfs_off_e if (neighbor_col & 1) == 0 else _bfs_off_o
                    candidate_fp: Set[Tuple[int, int]] = {(neighbor_col + dc, neighbor_row + dr) for dc, dr in _offs}
                    if _bfs_wall_hexes and (candidate_fp & _bfs_wall_hexes):
                        visited[neighbor_pos] = neighbor_dist
                        continue
                    if occupied_positions and (candidate_fp & occupied_positions):
                        visited[neighbor_pos] = neighbor_dist
                        continue
                    visited[neighbor_pos] = neighbor_dist
                    queue.append((neighbor_pos, neighbor_dist))
                    if neighbor_pos == start_pos:
                        continue
                    if _closer_shell is not None and not (candidate_fp & _closer_shell):
                        continue
                    valid_destinations.append(neighbor_pos)
                    pile_in_fp_by_anchor[neighbor_pos] = candidate_fp

    if not contact_target_ids:
        return valid_destinations
    # Cibles pour le test « contact » : CC éligibles + palier distance minimale (pile-in GW :
    # se rapprocher du plus proche ; évite un repli non-collé alors qu'un contact avec ce palier existe).
    contact_filter = sorted(
        {str(x) for x in contact_target_ids} | {str(x) for x in closest_ids}
    )
    contact_destinations = [
        p
        for p in valid_destinations
        if _fight_pile_in_anchor_adjacent_to_enemy_footprint(
            game_state,
            unit,
            p[0],
            p[1],
            contact_filter,
            candidate_footprint=pile_in_fp_by_anchor[p],
        )
    ]
    if contact_destinations:
        return contact_destinations
    return valid_destinations


def _fight_compute_pile_in_footprint_zone(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    valid_anchors: List[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """
    Union des hexes occupés par l'empreinte à chaque ancre valide + empreinte actuelle.
    Aligné sur l'idée de ``move_preview_footprint_zone`` (phase move).
    """
    zone: Set[Tuple[int, int]] = set()
    for ac, ar in valid_anchors:
        fp = compute_candidate_footprint(int(ac), int(ar), unit, game_state)
        zone.update(fp)
    unit_id_str = str(unit["id"])
    start_col, start_row = require_unit_position(unit, game_state)
    units_cache = require_key(game_state, "units_cache")
    cache_entry = units_cache.get(unit_id_str)
    cur_fp = cache_entry.get("occupied_hexes", {(start_col, start_row)}) if cache_entry else {(start_col, start_row)}
    zone.update(cur_fp)
    return zone


def _fight_apply_pile_in_move(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    dest_col: int,
    dest_row: int,
    *,
    log_label: str = "PILE_IN",
) -> None:
    """Applique un déplacement court en phase fight (pile in, consolidation, etc.) — ne marque pas units_moved."""
    dest_col_i, dest_row_i = normalize_coordinates(dest_col, dest_row)
    orig_col, orig_row = require_unit_position(unit, game_state)
    unit_id_str = str(unit["id"])
    fp_pair = _fight_prepare_footprint_offsets(unit, game_state)
    candidate_fp = _candidate_footprint_fight(dest_col_i, dest_row_i, unit, game_state, fp_pair)
    if not is_placement_valid_with_clearance(
        game_state, candidate_fp,
        shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
        col=dest_col_i, row=dest_row_i, exclude_unit_id=unit_id_str,
    ):
        raise ValueError(
            f"Pile in illegal placement unit={unit_id_str} dest=({dest_col_i},{dest_row_i})"
        )

    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "fight")
    log_message = (
        f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: "
        f"({orig_col},{orig_row})→({dest_col_i},{dest_row_i}) via {log_label}"
    )
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)

    set_unit_coordinates(unit, dest_col_i, dest_row_i)
    old_cache = require_key(game_state, "units_cache").get(unit_id_str)
    old_occupied = set(old_cache.get("occupied_hexes")) if old_cache else None

    # Déplacement rigide : translate TOUTES les figurines (models_cache) + resync
    # occupied_hexes_by_model (source de vérité par-modèle lue par le front). Ne pas
    # utiliser update_units_cache_position seul, qui ne bouge que l'ancre → les socles
    # restaient figés à l'écran après un pile-in.
    translate_squad_to_destination(game_state, unit_id_str, dest_col_i, dest_row_i)

    new_cache = require_key(game_state, "units_cache").get(unit_id_str)
    new_occupied = new_cache.get("occupied_hexes") if new_cache else None
    moved_unit_player = int(require_key(unit, "player"))
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_i,
        new_row=dest_row_i,
        old_occupied=old_occupied,
        new_occupied=new_occupied,
    )
    from .shooting_handlers import _invalidate_los_cache_for_moved_unit

    _invalidate_los_cache_for_moved_unit(game_state, unit["id"], old_col=orig_col, old_row=orig_row)


def _fight_clear_consolidation_state(game_state: Dict[str, Any]) -> None:
    game_state.pop("fight_consolidation_pending", None)
    game_state.pop("valid_consolidation_destinations", None)
    game_state.pop("fight_consolidation_footprint_zone", None)
    game_state.pop("fight_consolidation_footprint_mask_loops", None)
    game_state.pop("fight_consolidation_branch", None)
    game_state.pop("_fight_consolidation_ctx", None)


def _fight_synth_cache_entry_at_footprint(
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
    candidate_fp: Set[Tuple[int, int]],
) -> Dict[str, Any]:
    """Construit une entrée ``units_cache``-compatible pour un test d'engagement à l'ancre donnée."""
    uid = str(require_key(unit, "id"))
    units_cache = require_key(game_state, "units_cache")
    src = units_cache.get(uid)
    if src is None:
        raise ValueError(f"_fight_synth_cache_entry_at_footprint: unit {uid} missing from units_cache")
    out = dict(src)
    out["col"] = int(anchor_col)
    out["row"] = int(anchor_row)
    out["occupied_hexes"] = set(candidate_fp)
    return out


def _fight_footprint_in_engagement_with_any_enemy(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
    candidate_fp: Set[Tuple[int, int]],
) -> bool:
    """True si l'empreinte candidate est en zone d'engagement (contrat ``spatial_relations``) avec ≥1 ennemi."""
    from engine.spatial_relations import unit_entries_within_engagement_zone, get_engagement_zone

    ez = get_engagement_zone(game_state)
    synth = _fight_synth_cache_entry_at_footprint(unit, game_state, anchor_col, anchor_row, candidate_fp)
    mover_id = str(require_key(unit, "id"))
    mover_player = int(require_key(unit, "player"))
    units_cache = require_key(game_state, "units_cache")
    for eid, ce in units_cache.items():
        if str(eid) == mover_id:
            continue
        if int(require_key(ce, "player")) == mover_player:
            continue
        if unit_entries_within_engagement_zone(synth, ce, ez):
            return True
    return False


def _fight_consolidation_unit_engaged_with_any_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité est en zone d'engagement (contrat B) d'au moins un ennemi — pas de consolidation objectif."""
    from engine.spatial_relations import get_engagement_zone, unit_within_engagement_zone_footprints

    cc_range = get_engagement_zone(game_state)
    return unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=cc_range, max_distance=cc_range
    )


def _fight_prepare_footprint_offsets(
    unit: Dict[str, Any], game_state: Dict[str, Any]
) -> FightFootprintOffsetPair:
    """
    Pré-calcule les offsets d'empreinte pair/impair pour accélérer le BFS de consolidation.

    Retourne ``None`` si le plateau est legacy / 1-hex / en erreur ; l'appelant doit alors utiliser ``compute_candidate_footprint``.
    """
    cache: Dict[Tuple[str, int], FightFootprintOffsetPair] = game_state.setdefault("_fight_fp_offset_pair_cache", {})
    uid = str(unit["id"])
    orient = int(unit["orientation"])
    cache_key = (uid, orient)
    if cache_key in cache:
        return cache[cache_key]

    from .shared_utils import get_engagement_zone

    ez = get_engagement_zone(game_state)
    bs = unit["BASE_SIZE"]
    if ez <= 1 or bs == 1:
        cache[cache_key] = None
        return None
    try:
        from engine.hex_utils import precompute_footprint_offsets

        shape = unit["BASE_SHAPE"]
        off_e, off_o = precompute_footprint_offsets(shape, bs, orient)
        out: FightFootprintOffsetPair = (off_e, off_o)
        cache[cache_key] = out
        return out
    except Exception:
        cache[cache_key] = None
        return None


def _candidate_footprint_fight(
    center_col: int,
    center_row: int,
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    offset_pair: FightFootprintOffsetPair,
) -> Set[Tuple[int, int]]:
    if offset_pair is not None:
        off_e, off_o = offset_pair
        offs = off_e if (center_col & 1) == 0 else off_o
        return {(center_col + dc, center_row + dr) for dc, dr in offs}
    return compute_candidate_footprint(center_col, center_row, unit, game_state)


def _fight_unit_positions_for_observation_builder(game_state: Dict[str, Any]) -> Dict[str, Tuple[int, int]]:
    """Positions ancre pour ``ObservationBuilder._target_priority_score`` (unités vivantes uniquement)."""
    positions: Dict[str, Tuple[int, int]] = {}
    for u in require_key(game_state, "units"):
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        positions[uid] = require_unit_position(u, game_state)
    return positions


def _fight_resolve_objective_marker_center_hex(objective: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Hex « marqueur » d'un objectif : centre déclaré (disque / config) ou médiode des ``hexes``
    (liste explicite sans ``center``). Les autres hexes de ``hexes`` sont la zone de contrôle ;
    la consolidation objectif se mesure vers ce marqueur, pas vers toute la zone.
    """
    center_raw = objective.get("center")
    if center_raw is not None:
        if isinstance(center_raw, (list, tuple)) and len(center_raw) >= 2:
            c, r = normalize_coordinates(center_raw[0], center_raw[1])
            return (int(c), int(r))
        if isinstance(center_raw, dict):
            c = require_key(center_raw, "col")
            r = require_key(center_raw, "row")
            nc, nr = normalize_coordinates(c, r)
            return (int(nc), int(nr))
    hexes = objective.get("hexes")
    if not isinstance(hexes, (list, tuple)) or not hexes:
        return None
    coords: List[Tuple[int, int]] = []
    for h in hexes:
        if isinstance(h, (list, tuple)) and len(h) >= 2:
            c, r = normalize_coordinates(h[0], h[1])
            coords.append((int(c), int(r)))
        elif isinstance(h, dict):
            c = require_key(h, "col")
            r = require_key(h, "row")
            nc, nr = normalize_coordinates(c, r)
            coords.append((int(nc), int(nr)))
    if not coords:
        return None
    best: Optional[Tuple[int, int]] = None
    best_sum: Optional[int] = None
    for cand in coords:
        s = 0
        for o in coords:
            s += calculate_hex_distance(cand[0], cand[1], o[0], o[1])
        if best_sum is None or s < best_sum:
            best_sum = s
            best = cand
    return best


def _fight_closest_objective_marker_snapshot(
    start_fp: Set[Tuple[int, int]],
    marker_points: List[Tuple[int, int]],
) -> Tuple[int, List[Tuple[int, int]]]:
    """Distance minimale empreinte → hex marqueur, et liste des marqueurs à cette distance."""
    from engine.hex_utils import min_distance_between_sets

    if not marker_points:
        raise ValueError("_fight_closest_objective_marker_snapshot: marker_points must be non-empty")
    d_min: Optional[int] = None
    closest: List[Tuple[int, int]] = []
    for mc, mr in marker_points:
        d = min_distance_between_sets(start_fp, {(mc, mr)})
        if d_min is None or d < d_min:
            d_min = d
            closest = [(mc, mr)]
        elif d == d_min and (mc, mr) not in closest:
            closest.append((mc, mr))
    assert d_min is not None
    return int(d_min), closest


def _fight_new_fp_strictly_closer_to_objective_marker_tier(
    new_fp: Set[Tuple[int, int]],
    d_min: int,
    closest_markers: List[Tuple[int, int]],
    *,
    closer_shell_union: Optional[Set[Tuple[int, int]]] = None,
    _perf_strict_eval_acc: Optional[List[float]] = None,
) -> bool:
    """Même idée que ``_fight_pile_in_new_fp_strictly_closer_to_closest_tier`` : empreinte plus proche du marqueur.

    Optimisation équivalente au test par dilatation : ``new_fp`` est strictement plus proche d'un marqueur
    du palier ssi sa distance minimale au palier est <= ``d_min - 1``.
    """
    if d_min <= 0:
        return False
    if closer_shell_union is not None:
        return bool(new_fp & closer_shell_union)
    from engine.hex_utils import min_distance_between_sets

    marker_set = set(closest_markers)
    if not marker_set:
        raise ValueError(
            "_fight_new_fp_strictly_closer_to_objective_marker_tier: closest_markers must be non-empty"
        )
    _td0 = 0.0
    if _perf_strict_eval_acc is not None:
        _td0 = time.perf_counter()
    d = min_distance_between_sets(new_fp, marker_set, max_distance=d_min - 1)
    if _perf_strict_eval_acc is not None:
        _perf_strict_eval_acc[0] += time.perf_counter() - _td0
    return d <= (d_min - 1)


def _fight_bfs_reachable_anchors_consolidation(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    *,
    start_footprint: Optional[Set[Tuple[int, int]]] = None,
) -> Tuple[Dict[Tuple[int, int], int], Dict[Tuple[int, int], Set[Tuple[int, int]]]]:
    """
    BFS jusqu'à 3\" (sous-hex) : ancres avec placement d'empreinte valide (sans filtre pile in).

    Retourne ``(visited, fp_by_anchor)`` : empreinte candidate déjà calculée à l'entrée dans
    ``visited`` (évite un second ``compute_candidate_footprint`` par ancre en consolidation).

    ``start_footprint`` : si fourni, réutilise l'empreinte de l'ancre de départ (ex. déjà
    calculée pour un early-exit objectif) au lieu d'un second appel identique.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _t_bfs0 = time.perf_counter() if _perf else None
    s_compute_fp = 0.0
    s_placement_valid = 0.0
    neighbor_eval_n = 0
    scale = game_state["inches_to_subhex"]
    bfs_max = 3 * scale
    unit_id_str = str(unit["id"])
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)
    fp_pair = _fight_prepare_footprint_offsets(unit, game_state)
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    if start_footprint is not None:
        start_fp = start_footprint
    else:
        start_fp = _candidate_footprint_fight(start_col, start_row, unit, game_state, fp_pair)
    visited: Dict[Tuple[int, int], int] = {start_pos: 0}
    fp_by_anchor: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {start_pos: start_fp}
    queue = deque([(start_pos, 0)])
    while queue:
        current_pos, current_dist = queue.popleft()
        current_col, current_row = current_pos
        if current_dist >= bfs_max:
            continue
        neighbor_dist = current_dist + 1
        for neighbor_col, neighbor_row in get_hex_neighbors(current_col, current_row):
            neighbor_pos = (neighbor_col, neighbor_row)
            if neighbor_pos in visited:
                continue
            neighbor_eval_n += 1
            _t1 = 0.0
            if _perf:
                _t1 = time.perf_counter()
            candidate_fp = _candidate_footprint_fight(
                neighbor_col, neighbor_row, unit, game_state, fp_pair
            )
            _t2 = 0.0
            if _perf:
                s_compute_fp += time.perf_counter() - _t1
                _t2 = time.perf_counter()
            if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
                if _perf:
                    s_placement_valid += time.perf_counter() - _t2
                continue
            if _perf:
                s_placement_valid += time.perf_counter() - _t2
            visited[neighbor_pos] = neighbor_dist
            fp_by_anchor[neighbor_pos] = candidate_fp
            queue.append((neighbor_pos, neighbor_dist))
    if _perf and _t_bfs0 is not None:
        append_perf_timing_line(
            f"FIGHT_CONSOLIDATION_BFS unitId={unit_id_str!r} bfs_max={bfs_max} visited_n={len(visited)} "
            f"neighbor_eval_n={neighbor_eval_n} compute_fp_s={s_compute_fp:.6f} "
            f"placement_valid_s={s_placement_valid:.6f} total_s={time.perf_counter() - _t_bfs0:.6f}"
        )
    return visited, fp_by_anchor


def _fight_fp_has_adjacent_enemy_footprint(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    fp: Set[Tuple[int, int]],
) -> bool:
    """
    Contact **A** strict (empreintes : ``min_distance_between_sets`` ≤ 1).

    Pour le palier « contact » **consolidation** / cohérence pile-in (rond↔rond bord-à-bord),
    utiliser ``_fight_pile_in_anchor_adjacent_to_enemy_footprint`` avec l'ancre et l'empreinte.
    """
    return _fight_footprint_has_enemy_hex_contact(game_state, unit, fp)


def _fight_plan_consolidation_destinations(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
) -> Optional[Tuple[str, List[Tuple[int, int]], Dict[Tuple[int, int], int], Optional[List[str]]]]:
    """
    Consolidation après attaques (alignée pile-in + engagement ``spatial_relations``) :

    - **Ennemis** : uniquement si la distance minimale empreinte → palier d'ennemis les plus proches
      est **> 1** : BFS 3\", placement valide, rapprochement **strict** + engagement + préférence contact
      (pile-in). Si la distance est déjà minimale (≤ 1, ex. adjacent au palier) : **aucune**
      consolidation vers l'ennemi (impossible de se rapprocher davantage). **Pas** de consolidation
      objectif tant que l'unité est **engagée** (zone d'engagement B).
    - **Objectif** : uniquement si **non engagée** ; si consolidation vers une figurine ennemie
      impossible (ou pas d'ennemi opposant),
      rapprochement du **hex marqueur** (centre déclaré ``center`` / médiode des ``hexes`` si pas de
      centre). Les autres hexes de la zone sont la **zone de contrôle** ; la consolidation vise à
      diminuer la distance empreinte → marqueur (comme le pile-in vers un palier), pas seulement à
      entrer dans la zone. Préférence si ex aequo : empreinte recouvrant le hex marqueur.
    - **Aucune** consolidation si aucune branche ne fournit d'ancre utile (hors position de départ seule).
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)
    unit_id_str = str(require_key(unit, "id"))
    _cons_pf = perf_timing_enabled(game_state)
    has_enemy = _fight_opposing_enemies_exist(game_state, unit)

    visited: Optional[Dict[Tuple[int, int], int]] = None
    fp_by_anchor: Optional[Dict[Tuple[int, int], Set[Tuple[int, int]]]] = None

    def _ensure_consolidation_bfs(start_footprint: Optional[Set[Tuple[int, int]]] = None) -> None:
        nonlocal visited, fp_by_anchor
        if visited is not None and fp_by_anchor is not None:
            return
        visited_out, fp_out = _fight_bfs_reachable_anchors_consolidation(
            game_state, unit, start_footprint=start_footprint
        )
        visited = visited_out
        fp_by_anchor = fp_out

    if has_enemy:
        _t_snapshot0 = time.perf_counter() if _cons_pf else None
        start_d_min, closest_ids = _fight_pile_in_closest_enemy_snapshot(game_state, unit)
        if _cons_pf and _t_snapshot0 is not None:
            append_perf_timing_line(
                f"FIGHT_CONSOLIDATION_SNAPSHOT unitId={unit_id_str!r} "
                f"enemy_n={len(closest_ids)} d_min={start_d_min} "
                f"snapshot_s={time.perf_counter() - _t_snapshot0:.6f}"
            )
        if start_d_min > 1:
            _ensure_consolidation_bfs()
            assert visited is not None and fp_by_anchor is not None
            _t_enemy_filt0 = time.perf_counter() if _cons_pf else None
            strict_enemy_calls_n = 0
            engagement_calls_n = 0
            distance_pair_eval_n = 0
            strict_eval_s = 0.0
            engagement_eval_s = 0.0
            distance_eval_s = 0.0
            shell_build_s = 0.0
            units_cache = require_key(game_state, "units_cache")
            closest_enemy_fps: List[Set[Tuple[int, int]]] = []
            for enemy_id in closest_ids:
                cache_entry = units_cache.get(str(enemy_id))
                if not cache_entry:
                    continue
                closest_enemy_fps.append(
                    cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
                )
            _t_shell0 = time.perf_counter() if _cons_pf else None
            closer_shell_union: Set[Tuple[int, int]] = set()
            if closest_enemy_fps:
                _seed: Set[Tuple[int, int]] = set()
                for _efp in closest_enemy_fps:
                    _seed.update(_efp)
                _shell_visited = set(_seed)
                _board_cols = game_state["board_cols"]
                _board_rows = game_state["board_rows"]
                _shell_frontier = [
                    h for h in _seed
                    if 0 <= h[0] < _board_cols and 0 <= h[1] < _board_rows
                ]
                for _ in range(start_d_min - 1):
                    if not _shell_frontier:
                        break
                    _next: List[Tuple[int, int]] = []
                    for _c, _r in _shell_frontier:
                        for _nc, _nr in get_hex_neighbors(_c, _r):
                            if (_nc, _nr) not in _shell_visited and 0 <= _nc < _board_cols and 0 <= _nr < _board_rows:
                                _shell_visited.add((_nc, _nr))
                                _next.append((_nc, _nr))
                    _shell_frontier = _next
                closer_shell_union = _shell_visited
            shell_build_s = (time.perf_counter() - _t_shell0) if _t_shell0 is not None else 0.0
            dist_by_anchor: List[Tuple[Tuple[int, int], int]] = []
            for anchor in visited:
                if anchor == start_pos:
                    continue
                if anchor not in fp_by_anchor:
                    raise KeyError(
                        "_fight_plan_consolidation_destinations: missing candidate footprint for anchor "
                        f"{anchor!r} (BFS fp_by_anchor inconsistency)"
                    )
                fp = fp_by_anchor[anchor]
                strict_enemy_calls_n += 1
                if _cons_pf:
                    _ts0 = time.perf_counter()
                if not _fight_pile_in_new_fp_strictly_closer_to_closest_tier(
                    game_state,
                    fp,
                    start_d_min,
                    closest_ids,
                    closest_enemy_fps=closest_enemy_fps,
                    closer_shell_union=closer_shell_union,
                ):
                    if _cons_pf:
                        strict_eval_s += time.perf_counter() - _ts0
                    continue
                if _cons_pf:
                    strict_eval_s += time.perf_counter() - _ts0
                ac, ar = anchor
                engagement_calls_n += 1
                if _cons_pf:
                    _te0 = time.perf_counter()
                if not _fight_footprint_in_engagement_with_any_enemy(
                    game_state, unit, int(ac), int(ar), fp
                ):
                    if _cons_pf:
                        engagement_eval_s += time.perf_counter() - _te0
                    continue
                if _cons_pf:
                    engagement_eval_s += time.perf_counter() - _te0
                dmin: Optional[int] = None
                for enemy_fp in closest_enemy_fps:
                    if _cons_pf:
                        _td0 = time.perf_counter()
                    d = min_distance_between_sets(fp, enemy_fp)
                    if _cons_pf:
                        distance_eval_s += time.perf_counter() - _td0
                    distance_pair_eval_n += 1
                    if dmin is None or d < dmin:
                        dmin = d
                if dmin is None or dmin >= start_d_min:
                    continue
                dist_by_anchor.append((anchor, int(dmin)))
            if _cons_pf and _t_enemy_filt0 is not None:
                filter_s = time.perf_counter() - _t_enemy_filt0
                tracked_s = strict_eval_s + engagement_eval_s + distance_eval_s
                other_s = max(0.0, filter_s - tracked_s)
                append_perf_timing_line(
                    f"FIGHT_CONSOLIDATION_ENEMY_ANCHOR_FILTER unitId={unit_id_str!r} start_d_min={start_d_min} "
                    f"visited_n={len(visited)} strict_closer_calls_n={strict_enemy_calls_n} "
                    f"engagement_calls_n={engagement_calls_n} distance_pair_eval_n={distance_pair_eval_n} "
                    f"shell_build_s={shell_build_s:.6f} strict_eval_s={strict_eval_s:.6f} "
                    f"engagement_eval_s={engagement_eval_s:.6f} "
                    f"distance_eval_s={distance_eval_s:.6f} other_filter_s={other_s:.6f} "
                    f"filter_s={filter_s:.6f} candidates_n={len(dist_by_anchor)}"
                )
            if dist_by_anchor:
                best_score = min(d for _, d in dist_by_anchor)
                tier = [a for a, d in dist_by_anchor if d == best_score]
                contact_tier: List[Tuple[int, int]] = []
                for anchor in tier:
                    ac, ar = anchor
                    fp = fp_by_anchor[anchor]
                    if _fight_pile_in_anchor_adjacent_to_enemy_footprint(
                        game_state,
                        unit,
                        int(ac),
                        int(ar),
                        None,
                        candidate_footprint=fp,
                    ):
                        contact_tier.append(anchor)
                final_cands = contact_tier if contact_tier else tier
                if not (len(final_cands) == 1 and final_cands[0] == start_pos):
                    return ("enemy", final_cands, visited, list(closest_ids))

    if _fight_consolidation_unit_engaged_with_any_enemy(game_state, unit):
        return None

    objectives = game_state.get("objectives")
    if not isinstance(objectives, (list, tuple)) or not objectives:
        return None
    marker_points: List[Tuple[int, int]] = []
    seen_markers: Set[Tuple[int, int]] = set()
    for obj in objectives:
        if not isinstance(obj, dict):
            continue
        pt = _fight_resolve_objective_marker_center_hex(obj)
        if pt is not None and pt not in seen_markers:
            seen_markers.add(pt)
            marker_points.append(pt)
    if not marker_points:
        return None

    start_fp_obj = compute_candidate_footprint(start_col, start_row, unit, game_state)
    start_d_obj, closest_markers = _fight_closest_objective_marker_snapshot(start_fp_obj, marker_points)
    if start_d_obj == 0:
        return None

    _ensure_consolidation_bfs(start_fp_obj)
    assert visited is not None and fp_by_anchor is not None
    _obj_pf = _cons_pf
    _obj_uid = unit_id_str
    _t_obj_filt0 = time.perf_counter() if _obj_pf else None
    strict_closer_calls_n = 0
    marker_set_obj = set(closest_markers)
    if not marker_set_obj:
        raise ValueError(
            "_fight_plan_consolidation_destinations: closest_markers must be non-empty"
        )
    # Pre-compute distance map from markers (single BFS, bounded at start_d_obj-1 steps).
    # This replaces both the shell check and the per-anchor min_distance_between_sets call.
    _OBJ_INF = 10 ** 9
    _obj_dist_map: Dict[Tuple[int, int], int] = {h: 0 for h in marker_set_obj}
    _t_distmap0 = time.perf_counter() if _obj_pf else None
    _obj_frontier: List[Tuple[int, int]] = list(marker_set_obj)
    for _mdist in range(1, start_d_obj):
        _obj_next: List[Tuple[int, int]] = []
        for _c, _r in _obj_frontier:
            for _nc, _nr in get_hex_neighbors(_c, _r):
                if (_nc, _nr) not in _obj_dist_map:
                    _obj_dist_map[(_nc, _nr)] = _mdist
                    _obj_next.append((_nc, _nr))
        _obj_frontier = _obj_next
        if not _obj_frontier:
            break
    dist_map_build_s = (time.perf_counter() - _t_distmap0) if _t_distmap0 is not None else 0.0
    dist_by_anchor_obj: List[Tuple[Tuple[int, int], int]] = []
    for anchor in visited:
        if anchor == start_pos:
            continue
        if anchor not in fp_by_anchor:
            raise KeyError(
                "_fight_plan_consolidation_destinations: missing candidate footprint for anchor "
                f"{anchor!r} (BFS fp_by_anchor inconsistency)"
            )
        fp = fp_by_anchor[anchor]
        strict_closer_calls_n += 1
        d_tier = min((_obj_dist_map.get(h, _OBJ_INF) for h in fp), default=_OBJ_INF)
        if d_tier >= start_d_obj:
            continue
        dist_by_anchor_obj.append((anchor, int(d_tier)))
    if _obj_pf and _t_obj_filt0 is not None:
        filter_s = time.perf_counter() - _t_obj_filt0
        loop_s = max(0.0, filter_s - dist_map_build_s)
        append_perf_timing_line(
            f"FIGHT_CONSOLIDATION_OBJ_ANCHOR_FILTER unitId={_obj_uid!r} start_d_obj={start_d_obj} "
            f"visited_n={len(visited)} strict_closer_calls_n={strict_closer_calls_n} "
            f"dist_map_build_s={dist_map_build_s:.6f} loop_s={loop_s:.6f} filter_s={filter_s:.6f}"
        )
    if not dist_by_anchor_obj:
        return None
    best_o = min(d for _, d in dist_by_anchor_obj)
    tier_o = [a for a, d in dist_by_anchor_obj if d == best_o]
    on_marker: List[Tuple[int, int]] = []
    for anchor in tier_o:
        fp = fp_by_anchor[anchor]
        for mc, mr in closest_markers:
            if (mc, mr) in fp:
                on_marker.append(anchor)
                break
    final_cands_obj = on_marker if on_marker else tier_o
    if len(final_cands_obj) == 1 and final_cands_obj[0] == start_pos:
        return None
    return ("objective", final_cands_obj, visited, None)


def _fight_opposing_enemies_exist(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_id_str = str(unit["id"])
    for uid, cache_entry in units_cache.items():
        if str(uid) == unit_id_str:
            continue
        if int(cache_entry["player"]) != unit_player:
            return True
    return False


def _ai_select_consolidation_destination(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    branch: str,
    destinations: List[Tuple[int, int]],
    visited: Dict[Tuple[int, int], int],
    closest_enemy_ids: Optional[List[str]],
) -> Tuple[int, int]:
    """
    Choisit l'ancre de consolidation : d'abord marche BFS minimale, puis en branche ennemie
    tie-break via ``ObservationBuilder._target_priority_score`` (même contrat que l'observation).
    """
    if not destinations:
        raise ValueError("_ai_select_consolidation_destination: empty destinations")
    best_w = min(visited.get(a, 10**9) for a in destinations)
    tier_walk = [a for a in destinations if visited.get(a, 10**9) == best_w]
    if branch != "enemy" or not closest_enemy_ids:
        return tier_walk[0]
    from engine.observation_builder import ObservationBuilder

    obs_builder = ObservationBuilder(require_key(game_state, "config"))
    positions = _fight_unit_positions_for_observation_builder(game_state)
    best_anchor = tier_walk[0]
    best_score = float("-inf")
    for anchor in tier_walk:
        local_best = float("-inf")
        for eid in closest_enemy_ids:
            enemy_u = get_unit_by_id(game_state, str(eid))
            if enemy_u is None or not is_unit_alive(str(eid), game_state):
                continue
            prio_tup = obs_builder._target_priority_score(enemy_u, unit, game_state, positions)
            eff = -float(prio_tup[0])
            if eff > local_best:
                local_best = eff
        if local_best > best_score or (
            local_best == best_score and (anchor[0], anchor[1]) < (best_anchor[0], best_anchor[1])
        ):
            best_score = local_best
            best_anchor = anchor
    return best_anchor


def _fight_post_process_fight_activation_result(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """Après ``end_activation`` fight : alternance / fin de phase (effets de bord sur ``result``)."""
    if result.get("phase_complete"):
        preserved_action = result.get("action")
        preserved_attack_results = result.get("all_attack_results")
        preserved_unit_id = result.get("unitId")
        phase_result = _fight_phase_complete(game_state)
        result.update(phase_result)
        if preserved_action is not None:
            result["action"] = preserved_action
        if preserved_attack_results:
            result["all_attack_results"] = preserved_attack_results
        if preserved_unit_id:
            result["unitId"] = preserved_unit_id
    else:
        _toggle_fight_alternation(game_state)
        _update_fight_subphase(game_state)


def _fight_try_begin_consolidation_after_attacks(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    config: Dict[str, Any],
    *,
    all_attack_results_snapshot: List[Any],
    result_reason: str,
    last_target_id: Optional[str] = None,
    perf_trigger: Optional[str] = None,
) -> Optional[Tuple[bool, Dict[str, Any]]]:
    """
    Après la dernière attaque : propose consolidation (humain) ou l'exécute (IA / gym).
    Retourne None si pas de consolidation ; sinon (True, résultat API).

    perf_trigger : libellé optionnel pour ``perf_timing`` (sinon ``result_reason``).
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _tr = perf_trigger if perf_trigger is not None else result_reason
    _fight_clear_consolidation_state(game_state)
    _t_plan0 = time.perf_counter() if _perf else None
    plan = _fight_plan_consolidation_destinations(game_state, unit)
    if _perf and _t_plan0 is not None:
        append_perf_timing_line(
            f"FIGHT_CONSOLIDATION_PLAN trigger={_tr!r} unitId={unit['id']!r} "
            f"plan_s={time.perf_counter() - _t_plan0:.6f} has_plan={1 if plan is not None else 0}"
        )
    if plan is None:
        return None
    branch, destinations, visited, closest_ids = plan
    if not destinations:
        return None
    # Dédupliquer ; si la seule option utile est « rester », pas de consolidation UI.
    dedup: List[Tuple[int, int]] = []
    seen_a: Set[Tuple[int, int]] = set()
    for a in destinations:
        if a not in seen_a:
            seen_a.add(a)
            dedup.append(a)
    destinations = dedup
    if not destinations:
        return None

    unit_id = unit["id"]
    is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)
    is_gym_training = require_key(config, "gym_training_mode")
    if not isinstance(is_gym_training, bool):
        raise TypeError(f"config['gym_training_mode'] must be bool, got {type(is_gym_training).__name__}")
    auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)

    if (is_ai_controlled or is_gym_training) and auto_execution_allowed:
        pc, pr = _ai_select_consolidation_destination(
            game_state, unit, branch, destinations, visited, closest_ids
        )
        _fight_apply_pile_in_move(game_state, unit, pc, pr, log_label="CONSOLIDATION")
        _fight_clear_consolidation_state(game_state)
        game_state["fight_attack_results"] = []
        result = end_activation(
            game_state,
            unit,
            ACTION,
            1,
            FIGHT,
            FIGHT,
            0,
        )
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []
        result["action"] = "combat"
        result["phase"] = "fight"
        result["unitId"] = unit_id
        result["waiting_for_player"] = False
        result["reason"] = result_reason
        result["fight_subphase"] = require_key(game_state, "fight_subphase")
        result["consolidation_executed"] = True
        result["consolidation_branch"] = branch
        result["all_attack_results"] = list(all_attack_results_snapshot)
        if last_target_id is not None:
            result["targetId"] = last_target_id
        _fight_maybe_lazy_rebuild_alternating_pools(game_state)
        _fight_post_process_fight_activation_result(game_state, unit, result)
        return True, result

    game_state["fight_consolidation_pending"] = True
    game_state["valid_consolidation_destinations"] = list(destinations)
    _t_fp0 = time.perf_counter() if _perf else None
    consolidation_fp_zone = _fight_compute_pile_in_footprint_zone(game_state, unit, destinations)
    if _perf and _t_fp0 is not None:
        append_perf_timing_line(
            f"FIGHT_CONSOLIDATION_FP_ZONE trigger={_tr!r} unitId={unit['id']!r} "
            f"fp_zone_s={time.perf_counter() - _t_fp0:.6f} dest_n={len(destinations)}"
        )
    game_state["fight_consolidation_footprint_zone"] = list(consolidation_fp_zone)
    game_state.pop("fight_consolidation_footprint_mask_loops", None)
    game_state["fight_consolidation_branch"] = branch
    game_state["_fight_consolidation_ctx"] = {
        "valid_destinations": list(destinations),
        "branch": branch,
        "all_attack_results": list(all_attack_results_snapshot),
    }
    game_state["active_fight_unit"] = unit_id
    game_state["fight_attack_results"] = []

    out: Dict[str, Any] = {
        "waiting_for_consolidation": True,
        "valid_consolidation_destinations": [list(x) for x in destinations],
        "fight_consolidation_branch": branch,
        "unitId": unit_id,
        "action": "combat",
        "phase": "fight",
        "all_attack_results": list(all_attack_results_snapshot),
        "reason": result_reason,
        "fight_subphase": require_key(game_state, "fight_subphase"),
    }
    if last_target_id is not None:
        out["targetId"] = last_target_id
    return True, out


def _handle_fight_consolidation_resolution(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Choix joueur : consolidation vers une ancre ou abandon (pas de déplacement)."""
    unit_id = unit["id"]
    if not game_state.get("fight_consolidation_pending"):
        return False, {"error": "consolidation_not_pending", "unitId": unit_id}

    ctx = game_state.get("_fight_consolidation_ctx")
    if not isinstance(ctx, dict):
        raise TypeError("game_state['_fight_consolidation_ctx'] must be a dict when fight_consolidation_pending")

    skip = action.get("skip") is True
    moved_consolidation = False
    dest_col: int = 0
    dest_row: int = 0
    if not skip:
        if "destCol" not in action or "destRow" not in action:
            return False, {"error": "consolidation_requires_dest_or_skip", "unitId": unit_id}
        dest_col, dest_row = normalize_coordinates(action["destCol"], action["destRow"])
        valids: List[Tuple[int, int]] = [
            (int(t[0]), int(t[1])) for t in (ctx.get("valid_destinations") or [])
        ]
        if (dest_col, dest_row) not in valids:
            return False, {
                "error": "invalid_consolidation_destination",
                "unitId": unit_id,
                "destination": (dest_col, dest_row),
            }
        _fight_apply_pile_in_move(game_state, unit, dest_col, dest_row, log_label="CONSOLIDATION")
        moved_consolidation = True

    snap_attacks = ctx.get("all_attack_results") or []

    _fight_clear_consolidation_state(game_state)

    result = end_activation(
        game_state,
        unit,
        ACTION,
        1,
        FIGHT,
        FIGHT,
        0,
    )
    game_state["active_fight_unit"] = None
    game_state["valid_fight_targets"] = []
    result["action"] = "combat"
    result["phase"] = "fight"
    result["unitId"] = unit_id
    result["waiting_for_player"] = False
    result["consolidation_completed"] = True
    result["fight_subphase"] = require_key(game_state, "fight_subphase")
    result["all_attack_results"] = list(snap_attacks)
    if moved_consolidation:
        result["toCol"] = dest_col
        result["toRow"] = dest_row
        _fight_maybe_lazy_rebuild_alternating_pools(game_state)
    _fight_post_process_fight_activation_result(game_state, unit, result)
    return True, result


def _ai_select_pile_in_destination(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    pile_dests: List[Tuple[int, int]],
    d_min: int,
    closest_ids: List[str],
) -> Tuple[int, int]:
    """
    Choisit la destination qui minimise la distance au palier d'ennemis les plus proches.

    PERF : empreintes ennemies du palier pré-calculées une fois (pas une lecture cache par destination).
    """
    from engine.hex_utils import min_distance_between_sets

    if not pile_dests:
        raise ValueError("_ai_select_pile_in_destination: empty pile_dests")
    units_cache = require_key(game_state, "units_cache")
    tier_efps: List[Set[Tuple[int, int]]] = []
    for eid in closest_ids:
        ce = units_cache.get(str(eid))
        if not ce:
            continue
        tier_efps.append(ce.get("occupied_hexes", {(ce["col"], ce["row"])}))
    best: Optional[Tuple[int, int]] = None
    best_score: Optional[int] = None
    for ac, ar in pile_dests:
        fp = compute_candidate_footprint(ac, ar, unit, game_state)
        tier_scores: List[int] = []
        for efp in tier_efps:
            tier_scores.append(min_distance_between_sets(fp, efp))
        if not tier_scores:
            continue
        m = min(tier_scores)
        if best_score is None or m < best_score:
            best_score = m
            best = (ac, ar)
    return best if best is not None else pile_dests[0]


def _handle_fight_pile_in_resolution(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Après choix joueur : pile in (hex) ou skip."""
    unit_id = unit["id"]
    if not game_state.get("fight_pile_in_pending"):
        return False, {"error": "pile_in_not_pending", "unitId": unit_id}

    ctx = game_state.get("_fight_pile_in_ctx")
    if not isinstance(ctx, dict):
        raise TypeError("game_state['_fight_pile_in_ctx'] must be a dict when fight_pile_in_pending")

    skip = action.get("skip") is True
    safe_print(
        game_state,
        f"[PILE_IN_DEBUG] resolution unit={unit_id} skip={skip} "
        f"action_keys={sorted(action.keys())} raw_dest=({action.get('destCol')},{action.get('destRow')}) "
        f"valids_count={len(ctx.get('valid_destinations') or [])} valids={ctx.get('valid_destinations')}",
    )
    if not skip:
        if "destCol" not in action or "destRow" not in action:
            return False, {"error": "pile_in_requires_dest_or_skip", "unitId": unit_id}
        dest_col, dest_row = normalize_coordinates(action["destCol"], action["destRow"])
        valids: List[Tuple[int, int]] = ctx.get("valid_destinations") or []
        if (dest_col, dest_row) not in valids:
            safe_print(
                game_state,
                f"[PILE_IN_DEBUG] INVALID dest=({dest_col},{dest_row}) NOT in valids unit={unit_id}",
            )
            return False, {
                "error": "invalid_pile_in_destination",
                "unitId": unit_id,
                "destination": (dest_col, dest_row),
            }
        _pos_before = require_unit_position(unit, game_state)
        _fight_apply_pile_in_move(game_state, unit, dest_col, dest_row)
        _pos_after = require_unit_position(unit, game_state)
        safe_print(
            game_state,
            f"[PILE_IN_DEBUG] APPLIED unit={unit_id} {_pos_before}->{_pos_after} dest=({dest_col},{dest_row})",
        )
        game_state["_pile_in_toCol"] = dest_col
        game_state["_pile_in_toRow"] = dest_row

    game_state["fight_pile_in_pending"] = False
    game_state["_fight_pile_in_ctx"] = None
    game_state.pop("valid_pile_in_destinations", None)
    game_state.pop("fight_pile_in_footprint_zone", None)
    game_state.pop("fight_pile_in_footprint_mask_loops", None)

    valid_targets = _fight_build_valid_target_pool(game_state, unit)
    if not valid_targets:
        result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []
        result["action"] = "wait"
        result["phase"] = "fight"
        result["unitId"] = unit_id
        result["pile_in_completed"] = True
        if result.get("phase_complete"):
            preserved_action = result.get("action")
            preserved_unit_id = result.get("unitId")
            phase_result = _fight_phase_complete(game_state)
            result.update(phase_result)
            if preserved_action is not None:
                result["action"] = preserved_action
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
        else:
            _toggle_fight_alternation(game_state)
            _update_fight_subphase(game_state)
        safe_print(
            game_state,
            f"[PILE_IN_DEBUG] RETURN no_targets unit={unit_id} "
            f"phase_complete={result.get('phase_complete')} subphase={game_state.get('fight_subphase')!r} "
            f"result_action={result.get('action')!r}",
        )
        return True, result

    game_state["active_fight_unit"] = unit_id
    game_state["valid_fight_targets"] = valid_targets

    is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)
    auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)
    is_gym_training = require_key(config, "gym_training_mode")
    if not isinstance(is_gym_training, bool):
        raise TypeError(f"config['gym_training_mode'] must be bool, got {type(is_gym_training).__name__}")

    if (is_ai_controlled or is_gym_training) and auto_execution_allowed and valid_targets:
        target_id = _ai_select_fight_target(game_state, str(unit_id), valid_targets)
        if target_id:
            return _handle_fight_attack(game_state, unit, target_id, config)

    safe_print(
        game_state,
        f"[PILE_IN_DEBUG] RETURN waiting_for_player unit={unit_id} "
        f"valid_targets={valid_targets} subphase={game_state.get('fight_subphase')!r}",
    )
    return True, {
        "unitId": unit_id,
        "waiting_for_player": True,
        "valid_targets": valid_targets,
        "ATTACK_LEFT": unit["ATTACK_LEFT"],
        "pile_in_completed": True,
        "action": "wait",
    }


def _ai_select_fight_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """
    AI target selection for fight phase using RewardMapper system.

    Fight priority (same as shooting): lowest HP, highest threat.
    """
    if not valid_targets:
        return ""

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        raise ValueError(f"Unit not found for fight target selection: unit_id={unit_id}")
    
    try:
        from ai.reward_mapper import RewardMapper

        reward_configs = require_key(game_state, "reward_configs")

        # Get unit type for config lookup
        global _unit_registry_singleton
        if _unit_registry_singleton is None:
            from ai.unit_registry import UnitRegistry
            _unit_registry_singleton = UnitRegistry()
        fighter_unit_type = unit["unitType"]
        fighter_agent_key = _unit_registry_singleton.get_model_key(fighter_unit_type)

        # Get unit-specific config (required)
        unit_reward_config = require_key(reward_configs, fighter_agent_key)

        reward_mapper = RewardMapper(unit_reward_config)

        # Build target list for reward mapper (single lookup per tid)
        all_targets = []
        for tid in valid_targets:
            t = get_unit_by_id(game_state, tid)
            if t:
                all_targets.append(t)

        best_target = valid_targets[0]
        best_reward = -999999

        for target_id in valid_targets:
            target = get_unit_by_id(game_state, target_id)
            if not target:
                continue

            # Fight phase uses same priority logic as shooting
            # RewardMapper handles both via target priority calculation
            reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, False, game_state)

            if reward > best_reward:
                best_reward = reward
                best_target = target_id

        return best_target

    except Exception as e:
        from engine.game_utils import add_console_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        unit_id_str = str(unit.get("id", "unknown"))
        add_console_log(game_state, f"[TARGET SELECTION ERROR] E{episode} T{turn} Unit {unit_id_str}: target selection failed: {str(e)} - returning first valid target")
        return valid_targets[0]


def _fight_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete fight phase with player progression and turn management.

    CRITICAL: Fight is the LAST phase. After fight:
    - P0 ->    P1 movement phase
    - P1 ->       increment turn, P0 movement phase
    """
    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    charging_pool = require_key(game_state, "charging_activation_pool")
    active_alt_pool = require_key(game_state, "active_alternating_activation_pool")
    non_active_alt_pool = require_key(game_state, "non_active_alternating_activation_pool")
    add_debug_file_log(
        game_state,
        f"[POOL PRE-TRANSITION] E{episode} T{turn} fight charging_activation_pool={charging_pool} "
        f"active_alternating_activation_pool={active_alt_pool} "
        f"non_active_alternating_activation_pool={non_active_alt_pool}"
    )

    # Final cleanup
    game_state["charging_activation_pool"] = []
    game_state["active_alternating_activation_pool"] = []
    game_state["non_active_alternating_activation_pool"] = []

    # Clear alternation tracking state
    if "fight_alternating_turn" in game_state:
        del game_state["fight_alternating_turn"]

    # AI_TURN.md COMPLIANCE: Clear fight sub-phase at phase end
    game_state["fight_subphase"] = None

    # Console log
    add_console_log(game_state, "FIGHT PHASE COMPLETE")

    # Normalize current_player for deterministic comparisons
    current_player = require_key(game_state, "current_player")
    try:
        current_player_int = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player_int not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player_int}")
    game_state["current_player"] = current_player_int

    # Player progression logic
    if game_state["current_player"] == 1:
        # Player 1 complete ->    Player 2 command phase
        game_state["current_player"] = 2

        # CRITICAL: Do NOT call command_phase_start() directly - cascade loop handles it
        # The cascade loop in w40k_core.py will call command_phase_start() automatically
        # when it sees next_phase="command"

        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "command",
            "current_player": 2,
            "units_processed": len(require_key(game_state, "units_fought")),
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 2:
        # Player 2 complete -> Check if incrementing turn would exceed limit
        cfg = game_state["config"] if "config" in game_state else None
        tc = cfg["training_config"] if cfg and "training_config" in cfg else None
        max_turns = tc["max_turns_per_episode"] if tc and "max_turns_per_episode" in tc else None
        if max_turns and (game_state["turn"] + 1) > max_turns:
            # Primary objective scoring for P2 on round 5 (fight phase)
            state_manager = GameStateManager(require_key(game_state, "config"))
            state_manager.apply_primary_objective_scoring(game_state, "fight")
            # Incrementing would exceed turn limit - end game without incrementing
            game_state["turn_limit_reached"] = True
            game_state["game_over"] = True
            return {
                "phase_complete": True,
                "game_over": True,
                "turn_limit_reached": True,
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
        else:
            # Safe to increment turn and continue to P1's command phase
            game_state["turn"] += 1
            game_state["current_player"] = 1

            # CRITICAL: Do NOT call command_phase_start() directly - cascade loop handles it
            # The cascade loop in w40k_core.py will call command_phase_start() automatically
            # when it sees next_phase="command"

            return {
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "command",
                "current_player": 1,
                "new_turn": game_state["turn"],
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
    else:
        raise ValueError(f"Unreachable: current_player={game_state['current_player']}")

def fight_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Fight phase end - redirects to complete function"""
    return _fight_phase_complete(game_state)

def _execute_action_v10_unused(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    [DÉPRÉCIÉ V10 — code mort, remplacé par execute_action V11 plus bas.]
    Fight phase handler action routing with 3 sub-phases.

    Sub-Phase 1: Charging units (charging_activation_pool)
    Sub-Phase 2: Alternating activation (non-active player first)
    Sub-Phase 3: Cleanup (remaining pool)
    """

    # Phase initialization on first call
    # AI_TURN.md COMPLIANCE: Direct field access
    if "phase" not in game_state:
        current_phase = None
    else:
        current_phase = game_state["phase"]

    if current_phase != "fight":
        fight_phase_start(game_state)

    # Check which sub-phase we're in
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "charging_activation_pool" not in game_state:
        charging_pool = []
    else:
        charging_pool = game_state["charging_activation_pool"]

    if "active_alternating_activation_pool" not in game_state:
        active_alternating = []
    else:
        active_alternating = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_alternating = []
    else:
        non_active_alternating = game_state["non_active_alternating_activation_pool"]

    # Determine current sub-phase
    if charging_pool:
        # Sub-phase 1: Charging units
        current_sub_phase = "charging"
        current_pool = charging_pool
    elif non_active_alternating or active_alternating:
        # Sub-phase 2: Alternating activation
        # AI_TURN.md Lines 737-846: ALTERNATING LOOP between non-active and active pools

        # Initialize alternation tracker if not set
        if "fight_alternating_turn" not in game_state:
            # AI_TURN.md Line 738: "Non-active player turn" goes FIRST
            game_state["fight_alternating_turn"] = "non_active"

        # Determine which pool to use based on whose turn it is
        current_turn = game_state["fight_alternating_turn"]
        current_player = require_key(game_state, "current_player")

        if current_turn == "non_active" and non_active_alternating:
            current_sub_phase = "alternating_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            # Check if there are units for the non-active player (opposite of current_player)
            opposite_player = 3 - current_player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == opposite_player:
                    eligible_units.append(uid)
            if not eligible_units and active_alternating:
                # Non-active player has no units, but active pool has units ->  switch to active
                current_sub_phase = "alternating_active"
                current_pool = active_alternating
            elif not eligible_units:
                # Neither player has units -> end phase
                return True, fight_phase_end(game_state)
        elif current_turn == "active" and active_alternating:
            current_sub_phase = "alternating_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == current_player:
                    eligible_units.append(uid)
            if not eligible_units and non_active_alternating:
                # Active player has no units, but non_active pool has units -> switch to non_active
                current_sub_phase = "alternating_non_active"
                current_pool = non_active_alternating
            elif not eligible_units:
                # Neither player has units -> end phase
                return True, fight_phase_end(game_state)
        elif non_active_alternating:
            # Active pool empty but non_active has units -> Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            opposite_player = 3 - current_player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == opposite_player:
                    eligible_units.append(uid)
            if not eligible_units:
                # Non-active player has no units in cleanup pool -> end phase
                return True, fight_phase_end(game_state)
        elif active_alternating:
            # Non-active pool empty but active has units -> Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == current_player:
                    eligible_units.append(uid)
            if not eligible_units:
                # Active player has no units in cleanup pool -> end phase
                return True, fight_phase_end(game_state)
        else:
            # Both pools empty
            return True, fight_phase_end(game_state)
    else:
        # No units left - phase complete
        return True, fight_phase_end(game_state)

    # AI_TURN.md COMPLIANCE: Store current sub-phase for frontend eligibility display
    game_state["fight_subphase"] = current_sub_phase

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]

    # Extract unit if not provided
    if unit is None:
        if "unitId" not in action:
            is_gym_training = require_key(config, "gym_training_mode")
            if not isinstance(is_gym_training, bool):
                raise TypeError(
                    f"config['gym_training_mode'] must be bool, got {type(is_gym_training).__name__}"
                )
            if not is_gym_training:
                return False, {
                    "error": "unit_id_required",
                    "action": action_type,
                    "message": "unitId is required for human-controlled fight activation"
                }
            # Auto-select first unit from current pool for gym training
            # CRITICAL: Filter out dead units from pool before selection
            alive_units_in_pool = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and is_unit_alive(str(u["id"]), game_state):
                    alive_units_in_pool.append(uid)
            if alive_units_in_pool:
                unit_id = alive_units_in_pool[0]
                unit = get_unit_by_id(game_state, unit_id)
                if not unit:
                    return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}
                if not _is_ai_controlled_fight_unit(game_state, unit):
                    return False, {
                        "error": "unit_id_required",
                        "action": action_type,
                        "message": "unitId is required for human-controlled fight activation"
                    }
                # Remove dead units from pool
                for dead_unit_id in set(current_pool) - set(alive_units_in_pool):
                    _remove_dead_unit_from_fight_pools(game_state, dead_unit_id)
            else:
                return True, fight_phase_end(game_state)
        else:
            unit_id = str(action["unitId"])
            unit = get_unit_by_id(game_state, unit_id)
            if not unit:
                return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}
    else:
        unit_id = str(unit["id"])

    # Validate unit is in current pool
    if unit_id not in current_pool:
        return False, {
            "error": "unit_not_in_current_pool",
            "unitId": unit_id,
            "current_sub_phase": current_sub_phase,
            "current_pool": current_pool
        }

    # État incohérent : consolidation en attente sans ancres valides → terminer l'activation.
    # Ne pas traiter None (clé absente) comme liste vide : évite de couper l'activation à tort.
    if game_state.get("fight_consolidation_pending"):
        raw_dests = game_state.get("valid_consolidation_destinations")
        if isinstance(raw_dests, list) and len(raw_dests) == 0:
            au = game_state.get("active_fight_unit")
            u_recover = get_unit_by_id(game_state, str(au)) if au is not None else None
            _fight_clear_consolidation_state(game_state)
            if u_recover and is_unit_alive(str(u_recover["id"]), game_state):
                result = end_activation(
                    game_state,
                    u_recover,
                    ACTION,
                    1,
                    FIGHT,
                    FIGHT,
                    0,
                )
                game_state["active_fight_unit"] = None
                game_state["valid_fight_targets"] = []
                result["action"] = "combat"
                result["phase"] = "fight"
                result["unitId"] = u_recover["id"]
                result["reason"] = "consolidation_impossible_stale_state"
                result["consolidation_aborted"] = True
                result["fight_subphase"] = require_key(game_state, "fight_subphase")
                _fight_post_process_fight_activation_result(game_state, u_recover, result)
                return True, result
            game_state["active_fight_unit"] = None
            game_state["valid_fight_targets"] = []

    # Check actor controller type from strict game_state player mapping.
    is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)

    # Auto-activate unit if not already active for AI or gym-training flows.
    is_gym_training = require_key(config, "gym_training_mode")
    if not isinstance(is_gym_training, bool):
        raise TypeError(
            f"config['gym_training_mode'] must be bool, got {type(is_gym_training).__name__}"
        )
    active_fight_unit = game_state.get("active_fight_unit")
    auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)
    if (is_ai_controlled or is_gym_training) and auto_execution_allowed and not active_fight_unit and action_type == "fight":
        activation_result = _handle_fight_unit_activation(game_state, unit, config)
        if not activation_result[0]:
            return activation_result  # Activation failed
        # Check if activation ended (no targets -> end_activation was called)
        # This happens when unit has no valid targets and was auto-skipped
        if activation_result[1].get("activation_ended") or activation_result[1].get("phase_complete"):
            return activation_result
        # Root-cause fix: if auto-activation already executed attacks, do NOT
        # continue in this same call, otherwise the same semantic action can
        # trigger an additional attack sequence.
        if activation_result[1].get("attack_executed") or activation_result[1].get("all_attack_results"):
            return activation_result
        if activation_result[1].get("waiting_for_pile_in"):
            return activation_result
        if activation_result[1].get("waiting_for_consolidation"):
            return activation_result
        # Otherwise continue with fight action - targets should now be populated

    # NOTE: AI_TURN.md line 667 specifies invalid actions should call end_activation (ERROR, 0, PASS, FIGHT)
    # We follow this rule strictly - invalid actions are not converted to valid actions

    # Fight phase action routing
    if action_type == "activate_unit":
        return _handle_fight_unit_activation(game_state, unit, config)

    elif action_type == "pile_in":
        return _handle_fight_pile_in_resolution(game_state, unit, action, config)

    elif action_type == "consolidation":
        return _handle_fight_consolidation_resolution(game_state, unit, action, config)

    elif action_type == "fight":
        # Fight action with target selection
        # Auto-select target if not provided (for all modes: gym training, PvE AI, bots, etc.)
        if game_state.get("fight_pile_in_pending"):
            return False, {
                "error": "pile_in_required_first",
                "unitId": unit_id,
                "phase": "fight",
            }
        if game_state.get("fight_consolidation_pending"):
            return False, {
                "error": "consolidation_required_first",
                "unitId": unit_id,
                "phase": "fight",
            }
        if "targetId" not in action:
            # Always rebuild for the current unit to avoid stale target pools
            # from a previous active unit/subphase.
            valid_targets = _fight_build_valid_target_pool(game_state, unit)
            game_state["valid_fight_targets"] = valid_targets
            if valid_targets:
                if is_ai_controlled and auto_execution_allowed:
                    # Use AI target selection for AI-controlled players only.
                    target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets)
                    if target_id:
                        action["targetId"] = target_id
                    else:
                        raise ValueError(f"AI target selection failed for unit {unit_id}")
                elif is_gym_training and auto_execution_allowed:
                    first_target: Any = valid_targets[0]
                    if isinstance(first_target, dict):
                        action["targetId"] = first_target["id"]
                    else:
                        action["targetId"] = first_target
                else:
                    return False, {
                        "error": "target_id_required",
                        "unitId": unit_id,
                        "phase": "fight",
                        "message": "targetId is required for human-controlled fight attack"
                    }
            else:
                # CRITICAL: Rebuild valid_targets if empty - valid_fight_targets may have been cleared
                # But only if unit has attacks remaining
                if require_key(unit, "ATTACK_LEFT") <= 0:
                    # No attacks left - skip this unit (engine-determined, not agent choice)
                    result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
                    game_state["active_fight_unit"] = None
                    game_state["valid_fight_targets"] = []
                    result["action"] = "skip"
                    result["skip_reason"] = "no_valid_actions"
                    result["phase"] = "fight"
                    result["unitId"] = unit_id
                    if result.get("phase_complete"):
                        phase_result = _fight_phase_complete(game_state)
                        result.update(phase_result)
                    else:
                        _toggle_fight_alternation(game_state)
                        _update_fight_subphase(game_state)
                    return True, result
                
                # Unit has attacks - rebuild valid_targets if empty
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
                if valid_targets:
                    # Found targets - update game_state and continue with attack
                    game_state["valid_fight_targets"] = valid_targets
                    if is_ai_controlled and auto_execution_allowed:
                        next_target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets)
                        if next_target_id:
                            action["targetId"] = next_target_id
                        else:
                            raise ValueError(f"AI target selection failed for unit {unit_id}")
                    elif is_gym_training and auto_execution_allowed:
                        first_target_g: Any = valid_targets[0]
                        action["targetId"] = first_target_g["id"] if isinstance(first_target_g, dict) else first_target_g
                    else:
                        return False, {
                            "error": "target_id_required",
                            "unitId": unit_id,
                            "phase": "fight",
                            "message": "targetId is required for human-controlled fight attack"
                        }
                    # Continue to attack execution below (skip the PASS logic)
                else:
                    # DEBUG: Check if unit is adjacent to enemy but not attacking
                    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
                        episode = game_state["episode_number"]
                        turn = game_state["turn"]
                        if is_adjacent:
                            attack_left = require_key(unit, "ATTACK_LEFT")
                            log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight execute_action: Unit {unit_id} ADJACENT to enemy but NO TARGETS (ATTACK_LEFT={attack_left}) - skipping without attack"
                            _fight_verbose_trace(log_msg)
                    
                    # No targets - skip this unit (e.g. target died before activation)
                    result = end_activation(
                        game_state, unit,
                        PASS, 1, PASS, FIGHT, 0
                    )
                    # CRITICAL: Clear active_fight_unit so next unit can be activated
                    game_state["active_fight_unit"] = None
                    game_state["valid_fight_targets"] = []
                    
                    result["action"] = "skip"
                    result["skip_reason"] = "no_valid_actions"
                    result["phase"] = "fight"
                    result["unitId"] = unit_id

                    if result.get("phase_complete"):
                        # CRITICAL: Preserve action before merging phase transition
                        preserved_action = result.get("action")
                        preserved_unit_id = result.get("unitId")
                        
                        phase_result = _fight_phase_complete(game_state)
                        # Merge phase transition info into result
                        result.update(phase_result)
                        
                        # CRITICAL: Restore preserved action for logging
                        if preserved_action is not None:
                            result["action"] = preserved_action
                        elif "action" not in result:
                            result["action"] = "wait"
                        if preserved_unit_id:
                            result["unitId"] = preserved_unit_id
                    else:
                        _toggle_fight_alternation(game_state)
                        _update_fight_subphase(game_state)
                    return True, result
        
        # CRITICAL: Ensure targetId is set before attack execution
        if "targetId" not in action:
            # This should not happen if code above is correct, but add safety check
            valid_targets = game_state["valid_fight_targets"] if "valid_fight_targets" in game_state else []
            if not valid_targets:
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
            if valid_targets:
                first_target = valid_targets[0]
                action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
            else:
                # No targets available - skip (e.g. target died before activation)
                result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
                game_state["active_fight_unit"] = None
                game_state["valid_fight_targets"] = []
                result["action"] = "skip"
                result["skip_reason"] = "no_valid_actions"
                result["phase"] = "fight"
                result["unitId"] = unit_id
                if result.get("phase_complete"):
                    phase_result = _fight_phase_complete(game_state)
                    result.update(phase_result)
                else:
                    _toggle_fight_alternation(game_state)
                    _update_fight_subphase(game_state)
                return True, result
        
        if require_key(unit, "ATTACK_LEFT") <= 0:
            result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
            game_state["active_fight_unit"] = None
            game_state["valid_fight_targets"] = []
            result["action"] = "skip"
            result["skip_reason"] = "no_attacks_remaining"
            result["phase"] = "fight"
            result["unitId"] = unit_id
            if result.get("phase_complete"):
                phase_result = _fight_phase_complete(game_state)
                result.update(phase_result)
            else:
                _toggle_fight_alternation(game_state)
                _update_fight_subphase(game_state)
            return True, result

        target_id = action["targetId"]
        return _handle_fight_attack(game_state, unit, target_id, config)

    elif action_type == "postpone":
        # Postpone action (only valid if ATTACK_LEFT = CC_NB)
        return _handle_fight_postpone(game_state, unit)

    elif action_type == "left_click":
        # Human player click handling
        if "clickTarget" not in action:
            click_target = "elsewhere"
        else:
            click_target = action["clickTarget"]
        # Alias front : même sémantique que le tir (``enemy``) pour une cible CC.
        if click_target == "enemy":
            click_target = "target"

        if click_target == "target" and "targetId" in action:
            return _handle_fight_attack(game_state, unit, action["targetId"], config)
        elif click_target == "friendly_unit" and "targetId" in action:
            # Switch unit (only if ATTACK_LEFT = CC_NB for current unit)
            return _handle_fight_unit_switch(game_state, unit, action["targetId"])
        elif click_target == "active_unit":
            return True, {"action": "no_effect"}
        else:
            return True, {"action": "continue_selection"}

    elif action_type == "right_click":
        # Right click = postpone (if ATTACK_LEFT = CC_NB)
        return _handle_fight_postpone(game_state, unit)

    elif action_type == "invalid":
        # AI_TURN.md line 667: INVALID ACTION ERROR -> end_activation (ERROR, 0, PASS, FIGHT)
        # ``end_activation`` : rebuild alternating si ``arg3 != FIGHT`` et retrait d'un pool alternating.
        result = end_activation(
            game_state, unit,
            ERROR,         # Arg1: ERROR logging (per AI_TURN.md line 667)
            0,             # Arg2: NO step increment (per AI_TURN.md line 667)
            PASS,          # Arg3: PASS tracking (per AI_TURN.md line 667)
            FIGHT,         # Arg4: Remove from fight pool
            1              # Arg5: Error logging
        )
        result["invalid_action_penalty"] = True
        # CRITICAL: No default value - require explicit attempted_action
        attempted_action = action.get("attempted_action")
        if attempted_action is None:
            raise ValueError(f"Action missing 'attempted_action' field: {action}")
        result["attempted_action"] = attempted_action

        # Check if ALL pools are empty ->  phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            if preserved_action:
                result["action"] = preserved_action
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        # DEBUG: Log final result before return (ATTACK_LEFT > 0 case)
        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING (ATTACK_LEFT>0) - result['action']={result.get('action')} result['unitId']={result.get('unitId')} result_keys={list(result.keys())}"
            _fight_verbose_trace(log_msg)

        return True, result

    else:
        # Only valid actions are fight, postpone
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "fight"}


def _handle_fight_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle fight unit activation start.

    Initialize unit for fighting:
    - Set ATTACK_LEFT = CC_NB
    - Build valid target pool (enemies adjacent within CC_RNG)
    - Return waiting_for_player if targets exist
    """
    unit_id = unit["id"]

    # CRITICAL: Clear fight_attack_results at the start of each new unit activation
    # This ensures attacks from different units are not mixed together
    game_state["fight_attack_results"] = []

    # Set ATTACK_LEFT = CC_NB at activation start
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    cc_weapons = unit["CC_WEAPONS"] if "CC_WEAPONS" in unit else []
    if cc_weapons:
        selected_idx = unit["selectedCcWeaponIndex"] if "selectedCcWeaponIndex" in unit else 0
        if selected_idx < 0 or selected_idx >= len(cc_weapons):
            raise IndexError(f"Invalid selectedCcWeaponIndex {selected_idx} for unit {unit['id']}")
        weapon = cc_weapons[selected_idx]
        nb_roll = resolve_dice_value(require_key(weapon, "NB"), "fight_nb_init")
        unit["ATTACK_LEFT"] = nb_roll
        unit["_current_fight_nb"] = nb_roll
        _append_fight_nb_roll_info_log(game_state, unit, weapon, nb_roll)
        unit["_fight_attacks_executed"] = 0
    else:
        unit["ATTACK_LEFT"] = 0  # Pas d'armes melee
        unit["_fight_attacks_executed"] = 0

    # DEBUG: Log unit activation
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight unit_activation: Unit {unit_id} ACTIVATED with ATTACK_LEFT={unit['ATTACK_LEFT']}"
        _fight_verbose_trace(log_msg)

    # Build valid target pool (enemies adjacent within CC_RNG)
    valid_targets = _fight_build_valid_target_pool(game_state, unit)
    
    # DEBUG: Log valid targets
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight unit_activation: Unit {unit_id} valid_targets={valid_targets} count={len(valid_targets)}"
        _fight_verbose_trace(log_msg)

    # Pile in (optionnel) : pas « collé », mais cibles CC valides — jusqu'à 3\", fin plus proche du palier ennemi le plus proche
    game_state["fight_pile_in_pending"] = False
    game_state.pop("valid_pile_in_destinations", None)
    game_state.pop("fight_pile_in_footprint_zone", None)
    game_state.pop("fight_pile_in_footprint_mask_loops", None)
    game_state.pop("_fight_pile_in_ctx", None)
    _fight_clear_consolidation_state(game_state)

    if valid_targets:
        if not _fight_unit_is_hex_adjacent_to_enemy_footprint(game_state, unit):
            d_min, closest_ids = _fight_pile_in_closest_enemy_snapshot(game_state, unit)
            pile_dests = _fight_build_pile_in_valid_destinations(
                game_state,
                unit,
                d_min,
                closest_ids,
                [str(t) for t in valid_targets],
            )
            if pile_dests:
                is_gym_training = require_key(config, "gym_training_mode")
                if not isinstance(is_gym_training, bool):
                    raise TypeError(
                        f"config['gym_training_mode'] must be bool, got {type(is_gym_training).__name__}"
                    )
                is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)
                auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)
                auto_pile = (is_ai_controlled or is_gym_training) and auto_execution_allowed
                if auto_pile:
                    pc, pr = _ai_select_pile_in_destination(
                        game_state, unit, pile_dests, d_min, closest_ids
                    )
                    try:
                        _fight_apply_pile_in_move(game_state, unit, pc, pr)
                    except ValueError:
                        pass  # destination became invalid between BFS and application — skip pile-in
                    valid_targets = _fight_build_valid_target_pool(game_state, unit)
                else:
                    game_state["fight_pile_in_pending"] = True
                    game_state["valid_pile_in_destinations"] = pile_dests
                    pile_in_fp_zone = _fight_compute_pile_in_footprint_zone(game_state, unit, pile_dests)
                    game_state["fight_pile_in_footprint_zone"] = list(pile_in_fp_zone)
                    game_state.pop("fight_pile_in_footprint_mask_loops", None)
                    game_state["_fight_pile_in_ctx"] = {
                        "d_min": d_min,
                        "closest_ids": list(closest_ids),
                        "valid_destinations": list(pile_dests),
                    }
                    game_state["active_fight_unit"] = unit_id
                    return True, {
                        "unit_activated": True,
                        "unitId": unit_id,
                        "waiting_for_pile_in": True,
                        "valid_pile_in_destinations": pile_dests,
                        "ATTACK_LEFT": unit["ATTACK_LEFT"],
                        "waiting_for_player": True,
                        "action": "wait",
                    }

    if not valid_targets:
        # DEBUG: Check if unit is adjacent to enemy but not attacking
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if is_adjacent and unit["ATTACK_LEFT"] > 0:
                log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight unit_activation: Unit {unit_id} ADJACENT to enemy but NO VALID TARGETS (ATTACK_LEFT={unit['ATTACK_LEFT']}) - ending without attack"
                _fight_verbose_trace(log_msg)
        
        # No targets - end activation with PASS
        # ATTACK_LEFT = CC_NB? YES -> no attack -> end_activation (PASS, 1, PASS, FIGHT)
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging
            1,             # Arg2: +1 step increment
            PASS,          # Arg3: No tracking (no attack made)
            FIGHT,         # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []
        
        # CRITICAL: Set action for logging (wait action since no attack was made)
        result["action"] = "wait"
        result["phase"] = "fight"
        result["unitId"] = unit_id

        # Check if ALL pools are empty -> phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            # Always restore action (even if None, to ensure it's not overwritten by phase_result)
            if preserved_action is not None:
                result["action"] = preserved_action
            elif "action" not in result:
                # If action was not preserved and phase_result doesn't have it, set default
                result["action"] = "wait"
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        # DEBUG: Log final result before return (ATTACK_LEFT = 0 case)
        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING (ATTACK_LEFT=0) - result['action']={result.get('action')} result['unitId']={result.get('unitId')} result_keys={list(result.keys())}"
            _fight_verbose_trace(log_msg)

        return True, result

    # Check for AI auto-execution (similar to shooting phase)
    is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)
    
    auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)
    if is_ai_controlled and auto_execution_allowed and valid_targets:
        # AUTO-FIGHT: AI-controlled player auto-selects target and executes attack.
        target_id = _ai_select_fight_target(game_state, unit_id, valid_targets)
        if target_id:
            # Execute fight attack directly and return result
            return _handle_fight_attack(game_state, unit, target_id, config)
        # No valid target selected - fall through to waiting_for_player

    # Targets exist - return waiting_for_player (for human players or if AI selection failed)
    game_state["active_fight_unit"] = unit_id
    game_state["valid_fight_targets"] = valid_targets

    return True, {
        "unit_activated": True,
        "unitId": unit_id,
        "valid_targets": valid_targets,
        "ATTACK_LEFT": unit["ATTACK_LEFT"],
        "waiting_for_player": True,
        "action": "wait"  # CRITICAL: Set action for logging (waiting for target selection)
    }


def _toggle_fight_alternation(game_state: Dict[str, Any]) -> None:
    """
    AI_TURN.md Lines 762-764, 844-846: Toggle alternation turn after activation.

    After a unit completes its activation in alternating phase, switch to other player.
    Only toggles if BOTH pools have units (true alternation).
    If only one pool has units, don't toggle (cleanup phase).
    """
    # Check if we're in alternating phase
    if "fight_alternating_turn" not in game_state:
        return  # Not in alternating phase yet

    # AI_TURN.md COMPLIANCE: Direct field access
    if "active_alternating_activation_pool" not in game_state:
        active_pool = []
    else:
        active_pool = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_pool = []
    else:
        non_active_pool = game_state["non_active_alternating_activation_pool"]

    # AI_TURN.md Lines 762-764, 844-846: "Check: Either pool empty?"
    # If BOTH pools have units -> continue alternating (toggle)
    # If ONE pool empty ->  exit loop to cleanup phase (don't toggle)
    if active_pool and non_active_pool:
        # Both pools have units -> toggle
        current_turn = game_state["fight_alternating_turn"]
        if current_turn == "non_active":
            game_state["fight_alternating_turn"] = "active"
        else:
            game_state["fight_alternating_turn"] = "non_active"
    # else: One pool empty -> cleanup phase, don't toggle


def _update_fight_subphase(game_state: Dict[str, Any]) -> None:
    """
    Recalculate fight_subphase after pool changes.

    Called after end_activation to update subphase when pools become empty.
    """
    # AI_TURN.md COMPLIANCE: Direct field access
    if "charging_activation_pool" not in game_state:
        charging_pool = []
    else:
        charging_pool = game_state["charging_activation_pool"]

    if "active_alternating_activation_pool" not in game_state:
        active_alternating = []
    else:
        active_alternating = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_alternating = []
    else:
        non_active_alternating = game_state["non_active_alternating_activation_pool"]

    # Determine current sub-phase based on which pools have units
    if charging_pool:
        game_state["fight_subphase"] = "charging"
    elif non_active_alternating or active_alternating:
        # Alternating phase - check whose turn
        if "fight_alternating_turn" not in game_state:
            # Initialize if not set (first time entering alternating)
            game_state["fight_alternating_turn"] = "non_active"

        current_turn = game_state["fight_alternating_turn"]

        if current_turn == "non_active" and non_active_alternating:
            game_state["fight_subphase"] = "alternating_non_active"
        elif current_turn == "active" and active_alternating:
            game_state["fight_subphase"] = "alternating_active"
        elif non_active_alternating:
            # Active pool empty, only non-active left
            game_state["fight_subphase"] = "cleanup_non_active"
        elif active_alternating:
            # Non-active pool empty, only active left
            game_state["fight_subphase"] = "cleanup_active"
        else:
            game_state["fight_subphase"] = None
    else:
        # All pools empty
        game_state["fight_subphase"] = None


def _fight_build_valid_target_pool(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """
    Build valid fight target pool.

    Valid targets:
    - Enemy units
    - Alive (in units_cache)
    - Within engagement zone (min footprint distance, §3.3/§9.8)

    NO LINE OF SIGHT CHECK (fight doesn't need LoS)
    """
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone
    cc_range = get_engagement_zone(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id_str)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache (dead or absent); cannot build fight target pool")
    unit_player = int(require_key(unit_entry, "player"))

    valid_targets = []

    for target_id, target_entry in units_cache.items():
        target_id_str = str(target_id)
        if target_id_str == unit_id_str:
            continue
        target_player = int(require_key(target_entry, "player"))
        if target_player == unit_player:
            continue
        if not unit_entries_within_engagement_zone(unit_entry, target_entry, cc_range):
            continue
        valid_targets.append(target_id)

    return valid_targets


def _fight_ensure_current_fight_nb(unit: Dict[str, Any], unit_id: Any) -> None:
    """
    If unit['_current_fight_nb'] is missing (e.g. stripped from serialized state),
    recover the original NB as ATTACK_LEFT + _fight_attacks_executed.

    Using ATTACK_LEFT alone is wrong mid-activation: it equals remaining attacks only,
    so the cap check can fire one strike early.
    """
    if "_current_fight_nb" in unit:
        return
    if "_fight_attacks_executed" not in unit:
        unit["_fight_attacks_executed"] = 0
    al = require_key(unit, "ATTACK_LEFT")
    if not isinstance(al, int):
        raise TypeError(
            f"unit['ATTACK_LEFT'] must be int when initializing _current_fight_nb, "
            f"got {type(al).__name__}"
        )
    if al <= 0:
        raise ValueError(
            f"Cannot initialize _current_fight_nb with non-positive ATTACK_LEFT: "
            f"{al} (unit_id={unit_id})"
        )
    k = unit["_fight_attacks_executed"]
    if not isinstance(k, int):
        raise TypeError(
            f"unit['_fight_attacks_executed'] must be int, got {type(k).__name__}"
        )
    if k < 0:
        raise ValueError(
            f"unit['_fight_attacks_executed'] cannot be negative: {k} (unit_id={unit_id})"
        )
    total = al + k
    if total <= 0:
        raise ValueError(
            f"Recovered _current_fight_nb must be > 0, got total={total} "
            f"(ATTACK_LEFT={al}, _fight_attacks_executed={k}, unit_id={unit_id})"
        )
    unit["_current_fight_nb"] = total


def _fight_finish_no_more_targets_after_attack(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    config: Dict[str, Any],
    attack_result: Dict[str, Any],
    last_target_id: Any,
    unit_id: Any,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Fin d'activation fight : plus de cibles valides alors qu'il reste des attaques (ATTACK_LEFT > 0).

    Extrait de ``_handle_fight_attack`` pour éviter la duplication entre les chemins
    « pool vide » et « IA sans cible suivante ».
    """
    # DEBUG: Check if unit is adjacent to enemy but has no more targets
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if is_adjacent and unit["ATTACK_LEFT"] > 0:
            log_msg = (
                f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight attack: Unit {unit_id} ADJACENT to enemy "
                f"but NO MORE TARGETS (ATTACK_LEFT={unit['ATTACK_LEFT']}) - ending without completing all attacks"
            )
            _fight_verbose_trace(log_msg)

    snap_nt = list(game_state.get("fight_attack_results") or [])
    cons_nt = _fight_try_begin_consolidation_after_attacks(
        game_state,
        unit,
        config,
        all_attack_results_snapshot=snap_nt,
        result_reason="no_more_targets",
        last_target_id=last_target_id,
        perf_trigger=(
            "no_more_targets_after_kill" if attack_result.get("target_died") else None
        ),
    )
    if cons_nt is not None:
        if isinstance(cons_nt[1], dict):
            cons_nt[1]["attack_result"] = attack_result
            cons_nt[1]["target_died"] = (
                attack_result["target_died"] if "target_died" in attack_result else False
            )
        return cons_nt

    result = end_activation(
        game_state, unit,
        ACTION,        # Arg1: Log action
        1,             # Arg2: +1 step
        FIGHT,         # Arg3: FIGHT tracking
        FIGHT,         # Arg4: Remove from fight pool
        0              # Arg5: No error logging
    )
    game_state["active_fight_unit"] = None
    game_state["valid_fight_targets"] = []

    result["action"] = "combat"
    result["phase"] = "fight"
    result["unitId"] = unit_id
    result["waiting_for_player"] = False
    result["targetId"] = last_target_id
    result["attack_result"] = attack_result
    result["target_died"] = attack_result["target_died"] if "target_died" in attack_result else False
    result["reason"] = "no_more_targets"
    result["fight_subphase"] = require_key(game_state, "fight_subphase")

    fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
    if not fight_attack_results and attack_result:
        raise ValueError(
            f"fight_attack_results is empty despite attack_result for unit {unit_id}"
        )
    result["all_attack_results"] = list(fight_attack_results)
    for i, ar in enumerate(result["all_attack_results"]):
        tid_nt = ar.get("targetId")
        if tid_nt is None:
            raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
        dmg_nt = ar.get("damage")
        if dmg_nt is None:
            raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        log_msg = (
            f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: SETTING all_attack_results "
            f"count={len(result['all_attack_results'])} for Unit {unit_id} (no_more_targets)"
        )
        _fight_verbose_trace(log_msg)
        for i, ar in enumerate(result["all_attack_results"]):
            tid_nt = ar.get("targetId")
            dmg_nt = ar.get("damage")
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: no_more_targets "
                f"attack[{i}] -> Unit {tid_nt} damage={dmg_nt}"
            )
            _fight_verbose_trace(log_msg)
    game_state["fight_attack_results"] = []

    if result.get("phase_complete"):
        preserved_action = result.get("action")
        preserved_attack_results = result.get("all_attack_results")
        preserved_unit_id = result.get("unitId")

        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: BEFORE phase_complete - "
                f"preserved_action={preserved_action} preserved_unit_id={preserved_unit_id} "
                f"result_keys={list(result.keys())}"
            )
            _fight_verbose_trace(log_msg)

        phase_result = _fight_phase_complete(game_state)
        result.update(phase_result)

        result["action"] = preserved_action if preserved_action else "combat"
        if preserved_attack_results:
            result["all_attack_results"] = preserved_attack_results
        if preserved_unit_id:
            result["unitId"] = preserved_unit_id

        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: AFTER phase_complete - "
                f"result['action']={result.get('action')} result_keys={list(result.keys())}"
            )
            _fight_verbose_trace(log_msg)
    else:
        _toggle_fight_alternation(game_state)
        _update_fight_subphase(game_state)

    return True, result


def _handle_fight_attack(game_state: Dict[str, Any], unit: Dict[str, Any], target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle fight attack execution.

    Execute attack_sequence(CC) using CC_* stats:
    - CC_ATK (to-hit roll)
    - CC_STR vs target TOUGH (wound roll)
    - CC_AP vs target SAVE (save roll)
    - CC_DMG (damage dealt)

    Decrement ATTACK_LEFT after each attack.
    Continue until ATTACK_LEFT = 0 or no valid targets remain.
    """
    unit_id = unit["id"]

    # Validate ATTACK_LEFT
    if "ATTACK_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'ATTACK_LEFT' field: {unit}")
    if unit["ATTACK_LEFT"] <= 0:
        return False, {"error": "no_attacks_remaining", "unitId": unit_id, "action": "combat"}

    # Première cible : même validation qu'avant (avant toute mutation d'arme sur une cible invalide)
    valid_targets_initial = _fight_build_valid_target_pool(game_state, unit)
    if target_id not in valid_targets_initial:
        return False, {
            "error": "invalid_target",
            "targetId": target_id,
            "valid_targets": valid_targets_initial,
            "action": "combat",
        }

    if "fight_attack_results" not in game_state:
        game_state["fight_attack_results"] = []

    from engine.ai.weapon_selector import select_best_melee_weapon
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    from engine.utils.weapon_helpers import get_selected_melee_weapon

    current_target_id: Any = target_id
    attack_result: Dict[str, Any]

    while True:
        _fight_ensure_current_fight_nb(unit, unit_id)

        total_attacks_allowed = require_key(unit, "_current_fight_nb")
        if not isinstance(total_attacks_allowed, int):
            raise TypeError(
                f"unit['_current_fight_nb'] must be int, got {type(total_attacks_allowed).__name__}"
            )
        if total_attacks_allowed <= 0:
            raise ValueError(
                f"unit['_current_fight_nb'] must be > 0, got {total_attacks_allowed} (unit_id={unit_id})"
            )
        if "_fight_attacks_executed" not in unit:
            unit["_fight_attacks_executed"] = 0
        attacks_executed = require_key(unit, "_fight_attacks_executed")
        if not isinstance(attacks_executed, int):
            raise TypeError(
                f"unit['_fight_attacks_executed'] must be int, got {type(attacks_executed).__name__}"
            )
        if attacks_executed < 0:
            raise ValueError(
                f"unit['_fight_attacks_executed'] cannot be negative: {attacks_executed} (unit_id={unit_id})"
            )
        if attacks_executed >= total_attacks_allowed:
            snap_cap = list(game_state.get("fight_attack_results") or [])
            cons_cap = _fight_try_begin_consolidation_after_attacks(
                game_state,
                unit,
                config,
                all_attack_results_snapshot=snap_cap,
                result_reason="attack_cap_reached",
                last_target_id=current_target_id,
            )
            if cons_cap is not None:
                cons_cap[1]["attack_cap_reached"] = True
                cons_cap[1]["attack_cap_total"] = total_attacks_allowed
                cons_cap[1]["attack_cap_executed"] = attacks_executed
                return cons_cap
            result = end_activation(
                game_state, unit,
                ACTION,
                1,
                FIGHT,
                FIGHT,
                0,
            )
            game_state["active_fight_unit"] = None
            game_state["valid_fight_targets"] = []
            result["action"] = "combat"
            result["phase"] = "fight"
            result["unitId"] = unit_id
            result["waiting_for_player"] = False
            result["targetId"] = current_target_id
            result["reason"] = "attack_cap_reached"
            result["fight_subphase"] = require_key(game_state, "fight_subphase")
            fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
            result["all_attack_results"] = list(fight_attack_results)
            game_state["fight_attack_results"] = []
            if result.get("phase_complete"):
                phase_result = _fight_phase_complete(game_state)
                result.update(phase_result)
            else:
                _toggle_fight_alternation(game_state)
                _update_fight_subphase(game_state)
            result["attack_cap_reached"] = True
            result["attack_cap_total"] = total_attacks_allowed
            result["attack_cap_executed"] = attacks_executed
            return True, result

        valid_targets_now = _fight_build_valid_target_pool(game_state, unit)
        if current_target_id not in valid_targets_now:
            return False, {
                "error": "invalid_target",
                "targetId": current_target_id,
                "valid_targets": valid_targets_now,
                "action": "combat",
            }

        tgt = get_unit_by_id(game_state, current_target_id)
        if not tgt:
            return False, {"error": "target_not_found", "targetId": current_target_id, "action": "combat"}

        best_weapon_idx = select_best_melee_weapon(unit, tgt, game_state)
        if best_weapon_idx >= 0:
            unit["selectedCcWeaponIndex"] = best_weapon_idx
            weapon = unit["CC_WEAPONS"][best_weapon_idx]
            current_attack_left = require_key(unit, "ATTACK_LEFT")
            far = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
            if current_attack_left == 0 and not far:
                nb_roll = resolve_dice_value(require_key(weapon, "NB"), "fight_nb_auto_select")
                unit["ATTACK_LEFT"] = nb_roll
                unit["_current_fight_nb"] = nb_roll
                _append_fight_nb_roll_info_log(game_state, unit, weapon, nb_roll)
        else:
            unit["ATTACK_LEFT"] = 0
            return False, {"error": "no_weapons_available", "unitId": unit["id"], "action": "combat"}

        attack_result = _execute_fight_attack_sequence(game_state, unit, current_target_id)
        _perf_after_kill = perf_timing_enabled(game_state) and bool(attack_result.get("target_died"))

        if _fight_verbose_debug_enabled():
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state["episode_number"]
                turn = game_state["turn"]
                damage = attack_result["damage"] if "damage" in attack_result else 0
                target_died = attack_result["target_died"] if "target_died" in attack_result else False
                log_msg = (
                    f"[FIGHT DEBUG] E{episode} T{turn} fight attack_executed: Unit {unit_id} -> "
                    f"Unit {current_target_id} damage={damage} target_died={target_died}"
                )
                _fight_verbose_trace(log_msg)
            else:
                missing_keys = []
                if "episode_number" not in game_state:
                    missing_keys.append("episode_number")
                if "turn" not in game_state:
                    missing_keys.append("turn")
                _fight_verbose_trace(
                    f"[FIGHT DEBUG] attack_executed trace: missing game_state keys {missing_keys}"
                )

        selected_weapon = get_selected_melee_weapon(unit)
        if selected_weapon:
            _fight_ensure_current_fight_nb(unit, unit_id)
            total_attacks = require_key(unit, "_current_fight_nb")
        else:
            total_attacks = 0

        attack_result["attackerId"] = unit_id
        attack_result["targetId"] = current_target_id
        attack_result["attack_number"] = total_attacks - unit["ATTACK_LEFT"]
        attack_result["total_attacks"] = total_attacks
        game_state["fight_attack_results"].append(attack_result)
        unit["_fight_attacks_executed"] = attacks_executed + 1

        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            far_list = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
            total_results = len(far_list)
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight attack_executed: Unit {unit_id} "
                f"fight_attack_results count={total_results}"
            )
            _fight_verbose_trace(log_msg)

        unit["ATTACK_LEFT"] -= 1

        if unit["ATTACK_LEFT"] <= 0:
            break

        _t_pool_after_kill = time.perf_counter() if _perf_after_kill else None
        valid_targets_after = _fight_build_valid_target_pool(game_state, unit)
        if _perf_after_kill and _t_pool_after_kill is not None:
            append_perf_timing_line(
                f"FIGHT_KILL_VALID_TARGET_POOL attackerId={unit_id!r} last_targetId={current_target_id!r} "
                f"pool_s={time.perf_counter() - _t_pool_after_kill:.6f} valid_targets_n={len(valid_targets_after)}"
            )
        if valid_targets_after:
            is_ai_controlled = _is_ai_controlled_fight_unit(game_state, unit)
            auto_execution_allowed = _is_fight_auto_execution_allowed(game_state)
            if is_ai_controlled and auto_execution_allowed:
                next_target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets_after)
                if next_target_id:
                    current_target_id = next_target_id
                    continue
            else:
                fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
                if not fight_attack_results and attack_result:
                    raise ValueError(
                        f"fight_attack_results is empty despite attack_result for unit {unit_id}"
                    )
                all_attack_results = fight_attack_results
                if attack_result and attack_result not in all_attack_results:
                    raise ValueError(
                        f"attack_result missing from all_attack_results for unit {unit_id}"
                    )
                for i, ar in enumerate(all_attack_results):
                    tid_wp = ar.get("targetId")
                    if tid_wp is None:
                        raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
                    dmg_wp = ar.get("damage")
                    if dmg_wp is None:
                        raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
                if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
                    episode = game_state["episode_number"]
                    turn = game_state["turn"]
                    log_msg = (
                        f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING "
                        f"waiting_for_player=True with all_attack_results count={len(all_attack_results)} "
                        f"for Unit {unit_id}"
                    )
                    _fight_verbose_trace(log_msg)
                    for i, ar in enumerate(all_attack_results):
                        tid_wp = ar.get("targetId")
                        dmg_wp = ar.get("damage")
                        log_msg = (
                            f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: "
                            f"waiting_for_player attack[{i}] -> Unit {tid_wp} damage={dmg_wp}"
                        )
                        _fight_verbose_trace(log_msg)
                if all_attack_results:
                    game_state["fight_attack_results"] = []
                return True, {
                    "attack_executed": True,
                    "attack_result": attack_result,
                    "unitId": unit["id"],
                    "ATTACK_LEFT": unit["ATTACK_LEFT"],
                    "valid_targets": valid_targets_after,
                    "waiting_for_player": True,
                    "action": "combat",
                    "fight_subphase": require_key(game_state, "fight_subphase"),
                    "all_attack_results": list(all_attack_results) if all_attack_results else [],
                }

        return _fight_finish_no_more_targets_after_attack(
            game_state, unit, config, attack_result, current_target_id, unit_id
        )

    snap_ac = list(game_state.get("fight_attack_results") or [])
    if not snap_ac and attack_result:
        snap_ac = [attack_result]
    cons_ac = _fight_try_begin_consolidation_after_attacks(
        game_state,
        unit,
        config,
        all_attack_results_snapshot=snap_ac,
        result_reason="attacks_complete",
        last_target_id=current_target_id,
        perf_trigger=(
            "attacks_complete_after_kill" if attack_result.get("target_died") else None
        ),
    )
    if cons_ac is not None:
        if isinstance(cons_ac[1], dict):
            cons_ac[1]["attack_result"] = attack_result
            cons_ac[1]["target_died"] = attack_result.get("target_died", False)
        return cons_ac

    result = end_activation(
        game_state, unit,
        ACTION,
        1,
        FIGHT,
        FIGHT,
        0,
    )
    game_state["active_fight_unit"] = None
    game_state["valid_fight_targets"] = []

    result["action"] = "combat"
    result["phase"] = "fight"
    result["unitId"] = unit_id
    result["waiting_for_player"] = False
    result["targetId"] = current_target_id
    result["attack_result"] = attack_result
    result["target_died"] = attack_result.get("target_died", False)
    result["reason"] = "attacks_complete"
    result["fight_subphase"] = require_key(game_state, "fight_subphase")

    fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
    if not fight_attack_results:
        if attack_result:
            fight_attack_results = [attack_result]
    result["all_attack_results"] = list(fight_attack_results)
    for i, ar in enumerate(result["all_attack_results"]):
        tid_ac = ar.get("targetId")
        if tid_ac is None:
            raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
        dmg_ac = ar.get("damage")
        if dmg_ac is None:
            raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
    if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        log_msg = (
            f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: SETTING all_attack_results "
            f"count={len(result['all_attack_results'])} for Unit {unit_id} (attacks_complete)"
        )
        _fight_verbose_trace(log_msg)
        for i, ar in enumerate(result["all_attack_results"]):
            tid_ac = ar.get("targetId")
            dmg_ac = ar.get("damage")
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: attacks_complete "
                f"attack[{i}] -> Unit {tid_ac} damage={dmg_ac}"
            )
            _fight_verbose_trace(log_msg)
    game_state["fight_attack_results"] = []

    if result.get("phase_complete"):
        preserved_action = result.get("action")
        preserved_attack_results = result.get("all_attack_results")
        preserved_unit_id = result.get("unitId")

        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: BEFORE phase_complete "
                f"(ATTACK_LEFT=0) - preserved_action={preserved_action} preserved_unit_id={preserved_unit_id} "
                f"result_keys={list(result.keys())}"
            )
            _fight_verbose_trace(log_msg)

        phase_result = _fight_phase_complete(game_state)
        result.update(phase_result)

        result["action"] = preserved_action if preserved_action else "combat"
        if preserved_attack_results:
            result["all_attack_results"] = preserved_attack_results
        if preserved_unit_id:
            result["unitId"] = preserved_unit_id

        if _fight_verbose_debug_enabled() and "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            log_msg = (
                f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: AFTER phase_complete "
                f"(ATTACK_LEFT=0) - result['action']={result.get('action')} result_keys={list(result.keys())}"
            )
            _fight_verbose_trace(log_msg)
    else:
        _toggle_fight_alternation(game_state)
        _update_fight_subphase(game_state)

    return True, result


def _handle_fight_postpone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle postpone action.

    CRITICAL: Can ONLY postpone if ATTACK_LEFT = CC_NB (no attacks made yet)
    If unit has already attacked, must complete activation.
    """
    unit_id = unit["id"]

    # Check ATTACK_LEFT = weapon NB?
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    if "ATTACK_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'ATTACK_LEFT' field: {unit}")
    
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(unit)
    if not selected_weapon:
        return False, {"error": "no_melee_weapon", "unitId": unit["id"], "action": "combat"}
    
    if unit["ATTACK_LEFT"] == require_key(unit, "_current_fight_nb"):
        # YES -> Postpone allowed
        # Do NOT call end_activation - just return postpone signal
        # Unit stays in pool for later activation
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "postpone_allowed": True
        }
    else:
        # NO -> Must complete activation
        return False, {
            "error": "postpone_not_allowed",
            "reason": "unit_has_already_attacked",
            "ATTACK_LEFT": unit["ATTACK_LEFT"],
            "CC_NB": unit["CC_NB"]
        }


def _handle_fight_unit_switch(game_state: Dict[str, Any], current_unit: Dict[str, Any], new_unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle unit switching during fight phase.

    Can only switch if current unit has ATTACK_LEFT = CC_NB (hasn't attacked yet).
    Otherwise must complete current unit's activation.
    """
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if postpone is allowed using selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(current_unit)
    if not selected_weapon:
        postpone_allowed = False
    else:
        postpone_allowed = (current_unit["ATTACK_LEFT"] == require_key(current_unit, "_current_fight_nb"))

    if postpone_allowed:
        # Switch to new unit
        new_unit = get_unit_by_id(game_state, new_unit_id)
        if not new_unit:
            return False, {"error": "unit_not_found", "unitId": new_unit_id, "action": "combat"}

        return _handle_fight_unit_activation(game_state, new_unit, {})
    else:
        # Must complete current unit
        return False, {
            "error": "must_complete_current_unit",
            "current_unit": current_unit["id"],
            "ATTACK_LEFT": current_unit["ATTACK_LEFT"]
        }


def _execute_fight_attack_sequence(game_state: Dict[str, Any], attacker: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(CC) using close combat stats.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    """
    import random
    from engine.utils.weapon_helpers import get_selected_melee_weapon

    target = get_unit_by_id(game_state, target_id)
    if not target:
        raise ValueError(f"Target unit not found: {target_id}")
    target_coords = get_unit_coordinates(target)

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get selected weapon
    weapon = get_selected_melee_weapon(attacker)
    if not weapon:
        raise ValueError(f"Attacker {attacker['id']} has no selected melee weapon")

    attacker_id = attacker["id"]

    # Initialize result variables
    wound_roll = 0
    wound_target = 0
    wound_success = False
    save_roll = 0
    save_target = 0
    save_success = False
    damage_dealt = 0
    target_died = False
    _fight_kill_attack_perf: Optional[Dict[str, float]] = None
    hit_ability_display_name = None
    wound_ability_display_name = None
    save_ability_display_name = None

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name in attack_log
    weapon_name = weapon.get("display_name", "")
    weapon_prefix = f" with [{weapon_name}]" if weapon_name else ""
    attacker_col, attacker_row = get_unit_coordinates(attacker)
    target_col, target_row = target_coords
    attacker_label = f"Unit {attacker_id}({attacker_col},{attacker_row})"
    target_label = f"Unit {target_id}({target_col},{target_row})"
    
    # Hit roll -> hit_roll >= weapon.ATK
    initial_hit_roll = random.randint(1, 6)
    hit_roll = initial_hit_roll
    hit_target = weapon["ATK"]
    can_reroll_hit_ones = hit_roll == 1 and _unit_has_rule(attacker, "reroll_1_tohit_fight")
    hit_log_suffix = ""
    if can_reroll_hit_ones:
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
            attacker, "reroll_1_tohit_fight"
        )
        if source_rule_display_name is None:
            raise ValueError(
                f"Attacker {attacker_id} rerolled hit roll of 1 without source unit rule"
            )
        hit_ability_display_name = source_rule_display_name
        hit_log_suffix = f" [{source_rule_display_name}]"
        hit_roll = random.randint(1, 6)
    hit_success = hit_roll >= hit_target

    if not hit_success:
        # MISS case
        if can_reroll_hit_ones:
            attack_log = (
                f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                f"Hit {initial_hit_roll}->{hit_roll}({hit_target}+){hit_log_suffix}"
            )
        else:
            attack_log = (
                f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                f"Hit {hit_roll}({hit_target}+)"
            )
    else:
        # HIT -> Continue to wound roll
        wound_roll = random.randint(1, 6)
        initial_wound_roll = wound_roll
        wound_rerolled = False
        wound_target = _calculate_wound_target(weapon["STR"], target["T"])
        wound_success = wound_roll >= wound_target
        wound_log_suffix = ""
        if not wound_success:
            can_reroll_failed_wound_on_objective = (
                _unit_has_rule(attacker, "reroll_towound_target_on_objective")
                and _is_unit_on_objective(target, game_state)
            )
            can_reroll_wound_ones = wound_roll == 1 and _unit_has_rule(attacker, "reroll_1_towound")
            if can_reroll_failed_wound_on_objective or can_reroll_wound_ones:
                wound_roll = random.randint(1, 6)
                wound_rerolled = True
                wound_success = wound_roll >= wound_target
                if can_reroll_failed_wound_on_objective:
                    source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                        attacker, "reroll_towound_target_on_objective"
                    )
                    if source_rule_display_name is None:
                        raise ValueError(
                            f"Attacker {attacker_id} rerolled wound on objective without source unit rule"
                        )
                    wound_ability_display_name = source_rule_display_name
                    wound_log_suffix = f" [{source_rule_display_name}]"
                else:
                    source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                        attacker, "reroll_1_towound"
                    )
                    if source_rule_display_name is None:
                        raise ValueError(
                            f"Attacker {attacker_id} rerolled wound roll of 1 without source unit rule"
                        )
                    wound_ability_display_name = source_rule_display_name
                    wound_log_suffix = f" [{source_rule_display_name}]"

        if not wound_success:
            # FAIL TO WOUND case
            if can_reroll_hit_ones:
                hit_log_value = f"{initial_hit_roll}->{hit_roll}"
            else:
                hit_log_value = str(hit_roll)
            if wound_rerolled:
                wound_log_value = f"{initial_wound_roll}->{wound_roll}"
            else:
                wound_log_value = str(wound_roll)
            attack_log = (
                f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                f"Hit {hit_log_value}({hit_target}+){hit_log_suffix} - "
                f"Wound {wound_log_value}({wound_target}+){wound_log_suffix}"
            )
        else:
            # WOUND -> Continue to save roll
            if wound_rerolled:
                wound_log_value = f"{initial_wound_roll}->{wound_roll}"
            else:
                wound_log_value = str(wound_roll)
            save_roll = random.randint(1, 6)
            initial_save_roll = save_roll
            save_log_suffix = ""
            if save_roll == 1 and _unit_has_rule(target, "reroll_1_save_fight"):
                source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                    target, "reroll_1_save_fight"
                )
                if source_rule_display_name is None:
                    raise ValueError(
                        f"Target {target_id} rerolled save roll of 1 without source unit rule"
                    )
                save_ability_display_name = source_rule_display_name
                save_log_suffix = f" [{source_rule_display_name}]"
                save_roll = random.randint(1, 6)
            save_target = _calculate_save_target(target, weapon["AP"])
            save_success = save_roll >= save_target
            damage_dealt_pending: Optional[int] = None
            if not save_success:
                damage_dealt_pending = resolve_dice_value(
                    require_key(weapon, "DMG"), "fight_damage"
                )
                target_hp_preview = require_hp_from_cache(str(target["id"]), game_state)
                if (
                    target_hp_preview - damage_dealt_pending <= 0
                    and _tutorial_fight_lethal_save_prevented(
                        game_state, str(target["id"])
                    )
                ):
                    save_roll = max(save_roll, save_target)
                    save_success = True
                    damage_dealt_pending = None
            if save_ability_display_name is not None:
                save_log_value = f"{initial_save_roll}->{save_roll}"
            else:
                save_log_value = str(save_roll)

            if save_success:
                # SAVED case
                if can_reroll_hit_ones:
                    hit_log_value = f"{initial_hit_roll}->{hit_roll}"
                else:
                    hit_log_value = str(hit_roll)
                attack_log = (
                    f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                    f"Hit {hit_log_value}({hit_target}+){hit_log_suffix} - "
                    f"Wound {wound_log_value}({wound_target}+){wound_log_suffix} - "
                    f"Save {save_log_value}({save_target}+){save_log_suffix}"
                )
            else:
                # DAMAGE case - apply damage. HP_CUR single write path: update_units_cache_hp only (Phase 2: from cache)
                if damage_dealt_pending is None:
                    raise RuntimeError(
                        "fight damage pending missing when save failed (internal bug)"
                    )
                damage_dealt = damage_dealt_pending
                from engine.perf_timing import perf_timing_enabled

                _perf_kill_track = perf_timing_enabled(game_state)
                if _perf_kill_track:
                    _fight_kill_attack_perf = {"_kill_wall_t0": time.perf_counter()}
                _tk = (
                    _fight_kill_attack_perf["_kill_wall_t0"]
                    if _fight_kill_attack_perf is not None
                    else None
                )
                target_hp = require_hp_from_cache(str(target["id"]), game_state)
                new_hp = max(0, target_hp - damage_dealt)
                update_units_cache_hp(game_state, str(target["id"]), new_hp)
                if _fight_kill_attack_perf is not None and _tk is not None:
                    _fight_kill_attack_perf["update_hp_s"] = time.perf_counter() - _tk
                    _tk = time.perf_counter()

                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate kill probability cache for target
                from engine.ai.weapon_selector import invalidate_cache_for_target
                cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
                invalidate_cache_for_target(cache, str(target["id"]))
                if _fight_kill_attack_perf is not None and _tk is not None:
                    _fight_kill_attack_perf["invalidate_target_cache_s"] = time.perf_counter() - _tk
                    _tk = time.perf_counter()

                target_died = not is_unit_alive(str(target["id"]), game_state)

                if target_died:
                    # CRITICAL: Immediately remove dead unit from fight activation pools
                    _remove_dead_unit_from_fight_pools(game_state, target_id)
                    if _fight_kill_attack_perf is not None and _tk is not None:
                        _fight_kill_attack_perf["remove_pools_and_rebuild_s"] = time.perf_counter() - _tk
                        _tk = time.perf_counter()
                    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate cache for dead unit
                    from engine.ai.weapon_selector import invalidate_cache_for_unit
                    invalidate_cache_for_unit(cache, str(target["id"]))
                    if _fight_kill_attack_perf is not None and _tk is not None:
                        _fight_kill_attack_perf["invalidate_dead_unit_cache_s"] = time.perf_counter() - _tk
                    if can_reroll_hit_ones:
                        hit_log_value = f"{initial_hit_roll}->{hit_roll}"
                    else:
                        hit_log_value = str(hit_roll)
                    attack_log = (
                        f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                        f"Hit {hit_log_value}({hit_target}+){hit_log_suffix} - "
                        f"Wound {wound_log_value}({wound_target}+){wound_log_suffix} - "
                        f"Save {save_log_value}({save_target}+){save_log_suffix} - "
                        f"Dmg:{damage_dealt}HP"
                    )
                elif _fight_kill_attack_perf is not None:
                    _fight_kill_attack_perf["remove_pools_and_rebuild_s"] = 0.0
                    _fight_kill_attack_perf["invalidate_dead_unit_cache_s"] = 0.0
                    if can_reroll_hit_ones:
                        hit_log_value = f"{initial_hit_roll}->{hit_roll}"
                    else:
                        hit_log_value = str(hit_roll)
                    attack_log = (
                        f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                        f"Hit {hit_log_value}({hit_target}+){hit_log_suffix} - "
                        f"Wound {wound_log_value}({wound_target}+){wound_log_suffix} - "
                        f"Save {save_log_value}({save_target}+){save_log_suffix} - "
                        f"Dmg:{damage_dealt}HP"
                    )
                else:
                    if can_reroll_hit_ones:
                        hit_log_value = f"{initial_hit_roll}->{hit_roll}"
                    else:
                        hit_log_value = str(hit_roll)
                    attack_log = (
                        f"{attacker_label} FOUGHT {target_label}{weapon_prefix} - "
                        f"Hit {hit_log_value}({hit_target}+){hit_log_suffix} - "
                        f"Wound {wound_log_value}({wound_target}+){wound_log_suffix} - "
                        f"Save {save_log_value}({save_target}+){save_log_suffix} - "
                        f"Dmg:{damage_dealt}HP"
                    )

    # AI_TURN.md COMPLIANCE: Log ALL attacks to action_logs (not just damage)
    # AI_TURN.md COMPLIANCE: Direct field access for required 'turn' field
    if "turn" not in game_state:
        raise KeyError("game_state missing required 'turn' field")

    # AI_TURN.md COMPLIANCE: shootDetails array matches frontend gameLogStructure.ts ShootDetail interface
    # Fields: targetDied, damageDealt, saveSuccess (camelCase to match frontend)
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon_name in action_logs
    _t_combat_log0 = time.perf_counter() if _fight_kill_attack_perf is not None and target_died else None
    append_action_log(
        game_state,
        {
            "type": "combat",  # Must match frontend gameLogStructure.ts type
            "weaponName": weapon_name if weapon_name else None,
            "message": attack_log,
            "turn": game_state["turn"],
            "phase": "fight",
            "attackerId": attacker_id,
            "targetId": target_id,
            "player": attacker["player"],
            "shootDetails": [{
                "shotNumber": 1,
                "attackRoll": hit_roll,
                "hitTarget": hit_target,
                "hitResult": "HIT" if hit_success else "MISS",
                "strengthRoll": wound_roll,
                "woundTarget": wound_target,
                "strengthResult": "SUCCESS" if wound_success else "FAILED",
                "saveRoll": save_roll,
                "saveTarget": save_target,
                "saveSuccess": save_success,
                "damageDealt": damage_dealt,
                "targetDied": target_died
            }],
            "wound_ability_display_name": wound_ability_display_name,
            "hit_ability_display_name": hit_ability_display_name,
            "save_ability_display_name": save_ability_display_name,
            "timestamp": "server_time",
        },
    )
    if _fight_kill_attack_perf is not None and target_died and _t_combat_log0 is not None:
        _fight_kill_attack_perf["append_combat_log_s"] = time.perf_counter() - _t_combat_log0

    if os.environ.get("W40K_ACTION_LOG_TRACE", "").strip().lower() in ("1", "true", "yes", "on"):
        cp = game_state.get("current_player")
        fsub = game_state.get("fight_subphase")
        alt = game_state.get("fight_alternating_turn")
        sys.stderr.write(
            "[ACTION_LOG_TRACE] fight_handlers _execute_fight_attack_sequence append combat "
            f"attackerId={attacker_id} targetId={target_id} player={attacker.get('player')} "
            f"current_player={cp} fight_subphase={fsub!r} fight_alternating_turn={alt!r} "
            f"action_logs_len={len(game_state['action_logs'])}\n"
        )
        sys.stderr.flush()

    # Add separate death log event if target was killed
    _t_death_log0 = time.perf_counter() if _fight_kill_attack_perf is not None and target_died else None
    if target_died:
        append_action_log(
            game_state,
            {
                "type": "death",
                "message": f"Unit {target_id} was DESTROYED",
                "turn": game_state["turn"],
                "phase": "fight",
                "targetId": target_id,
                "unitId": target_id,
                "player": target["player"],
                "timestamp": "server_time",
            },
        )
    if _fight_kill_attack_perf is not None and target_died:
        from engine.perf_timing import append_perf_timing_line

        if _t_death_log0 is None:
            raise RuntimeError(
                "fight kill perf: _t_death_log0 missing despite target_died (internal bug)"
            )
        _fight_kill_attack_perf["append_death_log_s"] = time.perf_counter() - _t_death_log0
        sd = _fight_kill_attack_perf
        wall0 = float(sd.pop("_kill_wall_t0"))
        eng = (
            float(sd["update_hp_s"])
            + float(sd["invalidate_target_cache_s"])
            + float(sd["remove_pools_and_rebuild_s"])
            + float(sd["invalidate_dead_unit_cache_s"])
        )
        total_to_logs = time.perf_counter() - wall0
        append_perf_timing_line(
            f"FIGHT_KILL_ATTACK_SEQUENCE attackerId={attacker_id!r} targetId={target_id!r} "
            f"update_hp_s={sd['update_hp_s']:.6f} "
            f"invalidate_target_cache_s={sd['invalidate_target_cache_s']:.6f} "
            f"remove_pools_and_rebuild_s={sd['remove_pools_and_rebuild_s']:.6f} "
            f"invalidate_dead_unit_cache_s={sd['invalidate_dead_unit_cache_s']:.6f} "
            f"append_combat_log_s={sd['append_combat_log_s']:.6f} "
            f"append_death_log_s={sd['append_death_log_s']:.6f} "
            f"engine_kill_path_s={eng:.6f} total_to_logs_s={total_to_logs:.6f}"
        )

    return {
        "hit_roll": hit_roll,
        "hit_target": hit_target,
        "hit_success": hit_success,
        "wound_roll": wound_roll,
        "wound_target": wound_target,
        "wound_success": wound_success,
        "save_roll": save_roll,
        "save_target": save_target,
        "save_success": save_success,
        "damage": damage_dealt,
        "target_died": target_died,
        "wound_ability_display_name": wound_ability_display_name,
        "hit_ability_display_name": hit_ability_display_name,
        "save_ability_display_name": save_ability_display_name,
        "attack_log": attack_log,
        "weapon_name": weapon_name,  # MULTIPLE_WEAPONS_IMPLEMENTATION.md
        "target_coords": target_coords
    }




def _tutorial_fight_lethal_save_prevented(
    game_state: Dict[str, Any], target_unit_id: str
) -> bool:
    """True if scenario lists this unit: a failed save that would kill is treated as success."""
    ids = game_state.get("tutorial_fight_no_death_unit_ids")
    if ids is None:
        return False
    if not isinstance(ids, frozenset):
        raise TypeError(
            "tutorial_fight_no_death_unit_ids must be frozenset or None, "
            f"got {type(ids).__name__}"
        )
    return str(target_unit_id) in ids


def _calculate_save_target(target: Dict[str, Any], ap: int) -> int:
    """Calculate save target with AP modifier and invulnerable save"""
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
    armor_save = target["ARMOR_SAVE"]
    invul_save = target["INVUL_SAVE"]
    
    # Apply AP to armor save (AP is negative, subtract to worsen save: 3+ with -1 AP = 4+)
    modified_armor_save = armor_save - ap
    
    # Handle invulnerable saves: 0 means no invul save, use 7 (impossible)
    effective_invul = invul_save if invul_save > 0 else 7
    
    # Use best available save (lower target number is better)
    best_save = min(modified_armor_save, effective_invul)
    
    # Cap impossible saves at 7, minimum save is 2+
    return max(2, min(best_save, 6))


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """EXACT COPY from 40k_OLD w40k_engine.py wound calculation"""
    if strength >= toughness * 2:
        return 2
    elif strength > toughness:
        return 3
    elif strength == toughness:
        return 4
    elif strength * 2 <= toughness:
        return 6
    else:
        return 5


# === HELPER FUNCTIONS (Minimal Implementation) ===

# Note: _is_adjacent_to_enemy_within_cc_range is defined at top of file


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Check if any enemy is within weapon range using footprint distance (§3.3).

    Simplified LoS: assumes clear LoS if distance is within range.
    """
    from engine.utils.weapon_helpers import get_max_ranged_range
    from engine.hex_utils import min_distance_between_sets
    rng_rng = get_max_ranged_range(unit)
    if rng_rng <= 0:
        return False

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    for enemy_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) != unit_player:
            enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            distance = min_distance_between_sets(unit_fp, enemy_fp)
            if distance <= rng_rng:
                return True
    return False


# =====================================================================
# === V11 FIGHT PHASE — FONDATIONS (Bloc 0) ===========================
# =====================================================================
# Helpers et primitives V11 (PDF `12 Fights phase.pdf`). ADDITIF PUR :
# NON branchés sur le flux V10 actif → comportement de jeu inchangé.
# Câblés aux blocs 1-5. Réf : Documentation/phase_fight_v11.md.
#
# Unités de distance : `engagement_zone` est exprimé dans la métrique
# native du moteur (contrat d'engagement, cf. spatial_relations). Les
# portées en POUCES (pile_in_target_range=5", consolidation_trigger_range=3")
# sont converties via `inches_to_subhex`, comme l'existant `bfs_max = 3*scale`.


def is_fights_first(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """
    True si l'unité est une **Fights First unit** (ability 24.13).

    Source du grant V1 : le charge move effectué ce tour confère l'ability
    « jusqu'à la fin du tour » (11.04 AFTER MOVING). On lit donc ``units_charged``
    (alimenté uniquement après un charge move effectué). L'API reste « ability » :
    le jour où l'ability datasheet existe (config/unit_rules.json), il suffira
    d'ajouter ici un ``or _unit_has_rule(unit, "fights_first")``.
    """
    if "units_charged" not in game_state:
        raise KeyError(
            "game_state missing required 'units_charged' field "
            "- charge phase must run before is_fights_first()"
        )
    units_charged = {str(uid) for uid in game_state["units_charged"]}
    return str(require_key(unit, "id")) in units_charged


def fight_ensure_v11_state(game_state: Dict[str, Any]) -> None:
    """
    Initialise (idempotent) les sets de suivi V11 de la phase de combat (§6) :
    - ``units_selected_to_fight`` : « selected to fight » cette phase (12.04) ;
    - ``pile_in_done`` / ``consolidation_done`` : 1 move max/unité par étape groupée.
    Suit le pattern d'init paresseuse de ``units_fought``.
    """
    if "units_selected_to_fight" not in game_state:
        game_state["units_selected_to_fight"] = set()
    if "pile_in_done" not in game_state:
        game_state["pile_in_done"] = set()
    if "consolidation_done" not in game_state:
        game_state["consolidation_done"] = set()


def fight_compute_engaged_snapshot(game_state: Dict[str, Any]) -> Dict[str, bool]:
    """
    Snapshot ``engaged_at_fight_step_start`` (12.04 / 12.06).

    Pour chaque unité vivante : True si engagée (zone d'engagement) avec ≥1 ennemi
    MAINTENANT. À appeler au DÉBUT de l'étape FIGHT (donc APRÈS le pile-in groupé).
    Sert à : éligibilité fight 12.04 (« was engaged at the start of this step ») ET
    overrun 12.06 (« was unengaged at the start of the Fight step » = négation).
    """
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_within_engagement_zone_footprints,
    )

    ez = get_engagement_zone(game_state)
    snapshot: Dict[str, bool] = {}
    for u in require_key(game_state, "units"):
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        snapshot[uid] = unit_within_engagement_zone_footprints(
            game_state, u, engagement_zone=ez, max_distance=ez
        )
    return snapshot


def _fight_units_engaged_with(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Liste des ids d'unités ennemies actuellement engagées avec ``unit`` (zone d'engagement)."""
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    ez = get_engagement_zone(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    entry = units_cache.get(unit_id_str)
    if entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache; cannot compute engagement")
    unit_player = int(require_key(entry, "player"))
    engaged: List[str] = []
    for eid, ce in units_cache.items():
        if str(eid) == unit_id_str:
            continue
        if int(require_key(ce, "player")) == unit_player:
            continue
        if unit_entries_within_engagement_zone(entry, ce, ez):
            engaged.append(str(eid))
    return engaged


def pile_in_targets_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Unités ennemies dont l'empreinte est dans ``pile_in_target_range`` (5" × inches_to_subhex)."""
    from engine.hex_utils import min_distance_between_sets

    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    rng_inches = int(require_key(game_rules, "pile_in_target_range"))
    scale = require_key(game_state, "inches_to_subhex")
    rng = rng_inches * int(scale)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    entry = units_cache.get(unit_id_str)
    if entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache; cannot compute pile-in targets")
    unit_player = int(require_key(entry, "player"))
    unit_fp = entry.get("occupied_hexes", {(entry["col"], entry["row"])})
    within: List[str] = []
    for eid, ce in units_cache.items():
        if str(eid) == unit_id_str:
            continue
        if int(require_key(ce, "player")) == unit_player:
            continue
        enemy_fp = ce.get("occupied_hexes", {(ce["col"], ce["row"])})
        if min_distance_between_sets(unit_fp, enemy_fp, max_distance=rng) <= rng:
            within.append(str(eid))
    return within


def pile_in_select_targets_12_03(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    chosen_target_ids: Optional[List[str]] = None,
) -> List[str]:
    """
    BEFORE MOVING (12.03) — sélection des cibles de pile-in :
    - unité **engagée** → toutes les unités ennemies engagées (``chosen_target_ids`` ignoré) ;
    - unité **non engagée** → ``chosen_target_ids`` requis : 1+ unités ennemies dans 5"
      (``pile_in_target_range``), validées ici (choix joueur PvP / heuristique IA en amont).
    """
    engaged = _fight_units_engaged_with(game_state, unit)
    if engaged:
        return engaged
    within = set(pile_in_targets_within_range(game_state, unit))
    if chosen_target_ids is None:
        raise ValueError(
            "pile_in_select_targets_12_03: chosen_target_ids required when unit is unengaged"
        )
    chosen = [str(t) for t in chosen_target_ids]
    if not chosen:
        raise ValueError("pile_in_select_targets_12_03: empty target selection for unengaged unit")
    invalid = [t for t in chosen if t not in within]
    if invalid:
        raise ValueError(
            f"pile_in_select_targets_12_03: targets not enemy units within "
            f"{int(require_key(require_key(game_state, 'config'), 'game_rules')['pile_in_target_range'])}\": {invalid}"
        )
    return chosen


def pile_in_move_destinations_12_03(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target_ids: List[str],
) -> List[Tuple[int, int]]:
    """
    WHILE / AFTER MOVING (12.03) — ancres valides d'un pile-in vers ``target_ids``.

    Contraintes DURES (le moteur déplace l'empreinte de l'unité d'un bloc — modèle
    atomique de figurine ; les contraintes par-figurine sont traduites au niveau empreinte) :
    - **figurines en contact socle immobiles** : si l'unité est déjà « collée » (contact
      bord-à-bord avec un ennemi) → aucune ancre (pas de pile-in possible) ;
    - **BFS ≤ 3"** (× inches_to_subhex), placement d'empreinte valide (pas de chevauchement) ;
    - **WHILE** : fin strictement plus proche de la cible de pile-in la plus proche ;
    - **AFTER** : l'unité doit finir **engagée** (filtre dur) ; chaque unité ennemie
      engagée AVANT le move doit **rester** engagée après (filtre dur).

    Retour : liste d'ancres (col, row), hors position de départ. Vide ⇒ pas de pile-in possible.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    if not target_ids:
        raise ValueError("pile_in_move_destinations_12_03: target_ids must be non-empty")

    # Contrainte « figurines en contact socle immobiles » → empreinte atomique collée = pas de move.
    if _fight_unit_is_hex_adjacent_to_enemy_footprint(game_state, unit):
        return []

    ez = get_engagement_zone(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    entry = units_cache.get(unit_id_str)
    if entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache; cannot plan pile-in")
    unit_fp = entry.get("occupied_hexes", {(entry["col"], entry["row"])})

    # Palier de la cible de pile-in la plus proche (parmi les cibles sélectionnées).
    d_min_sel: Optional[int] = None
    closest_tier: List[str] = []
    for tid in target_ids:
        ce = units_cache.get(str(tid))
        if ce is None:
            continue
        efp = ce.get("occupied_hexes", {(ce["col"], ce["row"])})
        d = min_distance_between_sets(unit_fp, efp)
        if d_min_sel is None or d < d_min_sel:
            d_min_sel = d
            closest_tier = [str(tid)]
        elif d == d_min_sel:
            closest_tier.append(str(tid))
    if d_min_sel is None:
        raise ValueError("pile_in_move_destinations_12_03: no live target footprints among target_ids")

    # Cible(s) la/les plus proche(s) — pour le palier WHILE « engaged with it if possible ».
    closest_tier_entries = [
        units_cache[str(tid)] for tid in closest_tier if str(tid) in units_cache
    ]

    # Unités ennemies engagées AVANT le move (à conserver après).
    engaged_before = _fight_units_engaged_with(game_state, unit)
    engaged_before_entries = [
        (eid, units_cache[str(eid)]) for eid in engaged_before if str(eid) in units_cache
    ]

    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)
    visited, fp_by_anchor = _fight_bfs_reachable_anchors_consolidation(game_state, unit)

    destinations: List[Tuple[int, int]] = []
    engaging_closest: List[Tuple[int, int]] = []
    for anchor in visited:
        if anchor == start_pos:
            continue
        fp = fp_by_anchor[anchor]
        ac, ar = anchor
        # WHILE : strictement plus proche de la cible de pile-in la plus proche.
        if not _fight_pile_in_new_fp_strictly_closer_to_closest_tier(
            game_state, fp, d_min_sel, closest_tier
        ):
            continue
        # AFTER : l'unité doit finir engagée (avec au moins un ennemi).
        if not _fight_footprint_in_engagement_with_any_enemy(game_state, unit, int(ac), int(ar), fp):
            continue
        # AFTER : conserver chaque engagement de départ.
        synth = _fight_synth_cache_entry_at_footprint(unit, game_state, int(ac), int(ar), fp)
        if not all(
            unit_entries_within_engagement_zone(synth, ce, ez)
            for _eid, ce in engaged_before_entries
        ):
            continue
        destinations.append(anchor)
        # WHILE « engaged with it if possible » : ancre engageant la cible la plus proche.
        if any(
            unit_entries_within_engagement_zone(synth, ce, ez)
            for ce in closest_tier_entries
        ):
            engaging_closest.append(anchor)
    # Phase 1 (12.03 WHILE « engaged with it if possible ») : si au moins une ancre engage la
    # cible de pile-in la plus proche, le move DOIT s'y faire → on ne garde que celles-là.
    # Phase 2 (fallback) : sinon, tout le pool dur (plus proche + engagé + engagements conservés).
    return engaging_closest if engaging_closest else destinations


# =====================================================================
# === V11 FIGHT PHASE — ÉLIGIBILITÉS & MACHINE DE SÉLECTION (Bloc 1) ===
# =====================================================================
# Fonctions ADDITIVES PURES (non branchées sur le routage V10 actif).
# Implémentent le cœur règles de l'étape FIGHT V11 (PDF 12.04→12.06) :
# éligibilités, types de fight, et la machine de sélection FF→Remaining.
# Pré-condition d'appel : `engaged_at_fight_step_start` (snapshot 12.04)
# présent dans game_state (pris au début de l'étape FIGHT, cf.
# fight_compute_engaged_snapshot). Câblage du routage = cut-over final.


def _fight_v11_engaged_now(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité est engagée (zone d'engagement) avec ≥1 ennemi MAINTENANT."""
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_within_engagement_zone_footprints,
    )

    ez = get_engagement_zone(game_state)
    return unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=ez, max_distance=ez
    )


def _fight_v11_charged_this_turn(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité a fait un charge move ce tour (source units_charged)."""
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field")
    return str(require_key(unit, "id")) in {str(x) for x in game_state["units_charged"]}


def fight_v11_is_pile_in_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité PILE IN groupé (étape n°2, 12.03 — sans le bullet overrun) :
    engagée maintenant OU a fait un charge move ce tour.
    """
    return _fight_v11_engaged_now(game_state, unit) or _fight_v11_charged_this_turn(game_state, unit)


def fight_v11_is_eligible_to_fight(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité FIGHT 12.04 : pas déjà « selected to fight » cette phase ET
    (engagée maintenant OU engagée au début de l'étape FIGHT OU a chargé ce tour).
    **Indépendant de la présence de cibles** (cas overrun : a chargé, cible détruite).
    """
    uid = str(require_key(unit, "id"))
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    if uid in selected:
        return False
    if _fight_v11_engaged_now(game_state, unit):
        return True
    snapshot = require_key(game_state, "engaged_at_fight_step_start")
    if not isinstance(snapshot, dict):
        raise TypeError("game_state['engaged_at_fight_step_start'] must be a dict")
    if snapshot.get(uid, False):
        return True
    return _fight_v11_charged_this_turn(game_state, unit)


def fight_v11_is_overrun_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité OVERRUN fight 12.06 : unengaged maintenant, OU était UNengaged au
    début de l'étape FIGHT (négation du snapshot) et est devenue engagée pendant la phase.
    """
    engaged_now = _fight_v11_engaged_now(game_state, unit)
    if not engaged_now:
        return True
    snapshot = require_key(game_state, "engaged_at_fight_step_start")
    was_engaged_at_start = bool(snapshot.get(str(require_key(unit, "id")), False))
    return (not was_engaged_at_start) and engaged_now


def fight_v11_is_normal_fight_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Éligibilité NORMAL fight 12.05 : l'unité est engagée."""
    return _fight_v11_engaged_now(game_state, unit)


def fight_v11_is_consolidation_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité CONSOLIDATION 12.08 : l'unité « was eligible to fight this phase »
    (≈ a été sélectionnée, cf. décision plan §6) ET est vivante.
    """
    uid = str(require_key(unit, "id"))
    if not is_unit_alive(uid, game_state):
        return False
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    return uid in selected


def fight_v11_eligible_unit_ids(
    game_state: Dict[str, Any],
    player: int,
    *,
    fights_first_only: bool,
) -> List[str]:
    """Ids des unités vivantes de ``player`` éligibles à combattre (12.04), filtrées FF si demandé."""
    player = int(player)
    out: List[str] = []
    for u in require_key(game_state, "units"):
        if int(require_key(u, "player")) != player:
            continue
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        if not fight_v11_is_eligible_to_fight(game_state, u):
            continue
        if fights_first_only and not is_fights_first(u, game_state):
            continue
        out.append(uid)
    return out


def fight_v11_advance_selection(game_state: Dict[str, Any]) -> Optional[str]:
    """
    Machine de sélection 12.04 (exhaustive). Détermine l'unité que le sélecteur
    courant doit sélectionner ensuite, en mettant à jour ``fight_step`` /
    ``fight_selector`` (handoff). Retourne l'id de l'unité, ou None quand l'étape
    FIGHT est terminée. Ne marque PAS « selected to fight » (l'appelant le fait à
    la sélection effective).

    Pré-conditions : ``current_player``, ``fight_step`` ∈ {"fights_first","remaining"},
    ``fight_selector`` ∈ {1,2}, snapshot ``engaged_at_fight_step_start`` présents.
    """
    active = int(require_key(game_state, "current_player"))
    step = require_key(game_state, "fight_step")
    selector = int(require_key(game_state, "fight_selector"))
    if step not in ("fights_first", "remaining"):
        raise ValueError(f"Invalid fight_step: {step!r}")
    if selector not in (1, 2):
        raise ValueError(f"Invalid fight_selector: {selector!r}")

    # Retour à Resolve Fights First (12.04) : si des unités FF redeviennent
    # éligibles pendant Remaining → re-sélecteur = joueur actif (inatteignable
    # tant que FF = charge seule, mais implémenté pour conformité).
    if step == "remaining":
        if (
            fight_v11_eligible_unit_ids(game_state, active, fights_first_only=True)
            or fight_v11_eligible_unit_ids(game_state, 3 - active, fights_first_only=True)
        ):
            step = "fights_first"
            selector = active

    # Boucle de transition (bornée : ff→remaining une fois, handoff sélecteur ≤2).
    for _ in range(8):
        if step == "fights_first":
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=True)
            if mine:
                game_state["fight_step"] = step
                game_state["fight_selector"] = selector
                return mine[0]
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=True)
            if theirs:
                selector = 3 - selector  # l'autre joueur sélectionne
                continue
            # Plus aucune FF des deux côtés → Remaining, ce même joueur sélectionne.
            step = "remaining"
            continue
        else:  # remaining
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=False)
            if mine:
                game_state["fight_step"] = step
                game_state["fight_selector"] = selector
                return mine[0]
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=False)
            if theirs:
                selector = 3 - selector
                continue
            # Plus aucune unité éligible → fin de l'étape FIGHT.
            game_state["fight_step"] = step
            game_state["fight_selector"] = selector
            return None
    raise RuntimeError("fight_v11_advance_selection: transition loop did not converge")


# =====================================================================
# === V11 FIGHT PHASE — CONSOLIDATION : cascade 3 modes (Bloc 5) ======
# =====================================================================
# Fonctions ADDITIVES PURES (non branchées). Cascade obligatoire 12.08 :
# Ongoing (engagée) → Engaging (ennemi dans 3") → Objective (objectif dans 3").
# Portées en pouces converties via inches_to_subhex.


def _fight_v11_enemies_within_range(
    game_state: Dict[str, Any], unit: Dict[str, Any], range_inches: int
) -> List[str]:
    """Ids des unités ennemies dont l'empreinte est dans ``range_inches`` (× inches_to_subhex)."""
    from engine.hex_utils import min_distance_between_sets

    scale = int(require_key(game_state, "inches_to_subhex"))
    rng = int(range_inches) * scale
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None:
        raise ValueError(f"Unit {uid} not in units_cache; cannot compute range query")
    up = int(require_key(entry, "player"))
    ufp = entry.get("occupied_hexes", {(entry["col"], entry["row"])})
    out: List[str] = []
    for eid, ce in units_cache.items():
        if str(eid) == uid:
            continue
        if int(require_key(ce, "player")) == up:
            continue
        efp = ce.get("occupied_hexes", {(ce["col"], ce["row"])})
        if min_distance_between_sets(ufp, efp, max_distance=rng) <= rng:
            out.append(str(eid))
    return out


def _fight_v11_objective_hex_sets(game_state: Dict[str, Any]) -> List[Tuple[Any, Set[Tuple[int, int]]]]:
    """(id, set des hexes) par objectif. Utilise ``hexes`` (zone de contrôle runtime)."""
    objectives = game_state.get("objectives")
    if not isinstance(objectives, (list, tuple)):
        return []
    out: List[Tuple[Any, Set[Tuple[int, int]]]] = []
    for obj in objectives:
        if not isinstance(obj, dict):
            continue
        hexes = obj.get("hexes")
        s: Set[Tuple[int, int]] = set()
        if isinstance(hexes, (list, tuple)):
            for h in hexes:
                if isinstance(h, dict):
                    s.add((int(require_key(h, "col")), int(require_key(h, "row"))))
                elif isinstance(h, (list, tuple)) and len(h) >= 2:
                    s.add((int(h[0]), int(h[1])))
        if s:
            out.append((obj.get("id"), s))
    return out


def _fight_v11_objectives_within_range(
    game_state: Dict[str, Any], unit: Dict[str, Any], range_inches: int
) -> List[Any]:
    """Ids des objectifs dont la zone de contrôle est dans ``range_inches`` de l'unité."""
    from engine.hex_utils import min_distance_between_sets

    scale = int(require_key(game_state, "inches_to_subhex"))
    rng = int(range_inches) * scale
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None:
        raise ValueError(f"Unit {uid} not in units_cache; cannot compute objective range")
    ufp = entry.get("occupied_hexes", {(entry["col"], entry["row"])})
    out: List[Any] = []
    for oid, hexes in _fight_v11_objective_hex_sets(game_state):
        if min_distance_between_sets(ufp, hexes, max_distance=rng) <= rng:
            out.append(oid)
    return out


def fight_v11_consolidation_mode(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Optional[str]:
    """
    Cascade obligatoire 12.08 (mode imposé) :
    - ``"ongoing"``   : l'unité est engagée ;
    - ``"engaging"``  : sinon, 1+ unités ennemies dans ``consolidation_trigger_range`` (3") ;
    - ``"objective"`` : sinon, 1+ objectifs dans 3" ;
    - ``None``        : aucune branche applicable (pas de consolidation possible).
    """
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    if _fight_v11_engaged_now(game_state, unit):
        return "ongoing"
    if _fight_v11_enemies_within_range(game_state, unit, trig):
        return "engaging"
    if _fight_v11_objectives_within_range(game_state, unit, trig):
        return "objective"
    return None


def fight_v11_engaging_triggered_unit_ids(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[str]:
    """
    Engaging consolidation (12.08 AFTER) : ennemis engagés avec l'unité (après le move)
    non encore « selected to fight » cette phase → l'adversaire devra les sélectionner
    et ils combattent in-place. Retourne ces ids.
    """
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    return [eid for eid in _fight_units_engaged_with(game_state, unit) if eid not in selected]


# =====================================================================
# === V11 FIGHT PHASE — ORCHESTRATION (drivers, Blocs 1/2/5) ==========
# =====================================================================
# Drivers ADDITIFS PURS (non branchés sur execute_action). Pilotent la
# séquence des 5 étapes V11 (12.01→12.09). Le flip des points d'entrée
# (execute_action/fight_phase_start) = cut-over final.


def _fight_v11_log(game_state: Dict[str, Any], message: str) -> None:
    """Log V11 fight (console_logs + terminal serveur). Trace le flux pile_in→fight→consolidate."""
    msg = f"[FIGHT V11] {message}"
    add_console_log(game_state, msg)
    # safe_print est désactivé (no-op) → écriture directe sur stderr pour visibilité terminal.
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def fight_v11_start(game_state: Dict[str, Any]) -> None:
    """
    START OF FIGHT PHASE (12.01) → entre dans l'étape PILE IN (12.02).
    Réinitialise les états de suivi V11 de la phase et positionne la sous-phase.
    """
    game_state["phase"] = "fight"
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field at fight_v11_start")
    game_state["units_selected_to_fight"] = set()
    game_state["pile_in_done"] = set()
    game_state["consolidation_done"] = set()
    game_state.pop("engaged_at_fight_step_start", None)
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    game_state["fight_subphase"] = "pile_in"


def fight_v11_enter_fight_step(game_state: Dict[str, Any]) -> None:
    """
    Transition PILE IN → FIGHT (étape 3). Prend le snapshot
    ``engaged_at_fight_step_start`` (APRÈS le pile-in groupé) et initialise la
    machine de sélection 12.04 (Resolve Fights First, sélecteur = joueur actif).
    """
    game_state["engaged_at_fight_step_start"] = fight_compute_engaged_snapshot(game_state)
    game_state["fight_subphase"] = "fight"
    game_state["fight_step"] = "fights_first"
    game_state["fight_selector"] = int(require_key(game_state, "current_player"))
    _fight_v11_log(
        game_state,
        f"PILE IN terminé → étape FIGHT (snapshot engagés="
        f"{sorted(k for k, v in game_state['engaged_at_fight_step_start'].items() if v)}, "
        f"selector=P{game_state['fight_selector']})",
    )


def fight_v11_enter_consolidate(game_state: Dict[str, Any]) -> None:
    """Transition FIGHT → CONSOLIDATE (étape 4)."""
    game_state["fight_subphase"] = "consolidate"
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    _fight_v11_log(game_state, "FIGHT terminé → étape CONSOLIDATE")


def _fight_v11_grouped_step_eligible(
    game_state: Dict[str, Any], subphase: str, player: int
) -> List[str]:
    """Unités vivantes de ``player`` éligibles pour l'étape groupée ``subphase``, non encore traitées."""
    if subphase == "pile_in":
        done = {str(x) for x in game_state.get("pile_in_done", set())}
    elif subphase == "consolidate":
        done = {str(x) for x in game_state.get("consolidation_done", set())}
    else:
        raise ValueError(f"_fight_v11_grouped_step_eligible: bad subphase {subphase!r}")
    player = int(player)
    out: List[str] = []
    for u in require_key(game_state, "units"):
        if int(require_key(u, "player")) != player:
            continue
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        if uid in done:
            continue
        if subphase == "pile_in":
            if fight_v11_is_pile_in_eligible(game_state, u):
                out.append(uid)
        else:
            if fight_v11_is_consolidation_eligible(game_state, u):
                out.append(uid)
    return out


def fight_v11_grouped_next(
    game_state: Dict[str, Any], subphase: str
) -> Optional[Tuple[int, List[str]]]:
    """
    Étape groupée (PILE IN 12.02 / CONSOLIDATE 12.07) : joueur **actif d'abord**
    (toutes ses unités éligibles non traitées), puis l'adverse. Retourne
    ``(player, [unit_ids])`` pour le tour de groupe courant, ou ``None`` quand les
    deux camps ont épuisé leurs unités éligibles (→ transition d'étape).
    « Skip » = marquer l'unité dans le set ``*_done`` sans déplacement.
    """
    if subphase not in ("pile_in", "consolidate"):
        raise ValueError(f"fight_v11_grouped_next: bad subphase {subphase!r}")
    active = int(require_key(game_state, "current_player"))
    mine = _fight_v11_grouped_step_eligible(game_state, subphase, active)
    if mine:
        return (active, mine)
    theirs = _fight_v11_grouped_step_eligible(game_state, subphase, 3 - active)
    if theirs:
        return (3 - active, theirs)
    return None


def fight_v11_current_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    Liste NON-MUTANTE des unités actionnables dans la sous-phase FIGHT V11 courante
    (pour observation_builder / action_decoder / masking). Miroir lecture-seule des
    drivers : grouped_next pour pile_in/consolidate, machine de sélection 12.04 pour fight.
    """
    sub = game_state.get("fight_subphase")
    if sub in ("pile_in", "consolidate"):
        nxt = fight_v11_grouped_next(game_state, sub)
        return list(nxt[1]) if nxt else []
    if sub == "fight":
        active = int(require_key(game_state, "current_player"))
        step = game_state.get("fight_step") or "fights_first"
        selector = int(game_state.get("fight_selector") or active)
        if step == "remaining" and (
            fight_v11_eligible_unit_ids(game_state, active, fights_first_only=True)
            or fight_v11_eligible_unit_ids(game_state, 3 - active, fights_first_only=True)
        ):
            step, selector = "fights_first", active
        for _ in range(8):
            ff = step == "fights_first"
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=ff)
            if mine:
                return mine
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=ff)
            if theirs:
                selector = 3 - selector
                continue
            if ff:
                step = "remaining"
                continue
            return []
        return []
    return []


def _fight_v11_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fin de phase FIGHT V11 (12.09) → progression joueur / tour (Fight = dernière phase).
    Sémantique identique à ``_fight_phase_complete`` mais SANS les pools V10.
    """
    game_state["fight_subphase"] = None
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    game_state["fight_eligible_units"] = []
    game_state["active_fight_unit"] = None
    add_console_log(game_state, "FIGHT PHASE COMPLETE (V11)")

    current_player = int(require_key(game_state, "current_player"))
    if current_player not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player}")
    units_processed = len(game_state.get("units_selected_to_fight", set()))

    if current_player == 1:
        game_state["current_player"] = 2
        return {
            "phase_complete": True, "phase_transition": True, "next_phase": "command",
            "current_player": 2, "units_processed": units_processed,
            "clear_blinking_gentle": True, "reset_mode": "select",
            "clear_selected_unit": True, "clear_attack_preview": True,
        }
    # current_player == 2
    cfg = game_state.get("config")
    tc = cfg.get("training_config") if isinstance(cfg, dict) else None
    max_turns = tc.get("max_turns_per_episode") if isinstance(tc, dict) else None
    if max_turns and (game_state["turn"] + 1) > max_turns:
        state_manager = GameStateManager(require_key(game_state, "config"))
        state_manager.apply_primary_objective_scoring(game_state, "fight")
        game_state["turn_limit_reached"] = True
        game_state["game_over"] = True
        return {
            "phase_complete": True, "game_over": True, "turn_limit_reached": True,
            "units_processed": units_processed, "clear_blinking_gentle": True,
            "reset_mode": "select", "clear_selected_unit": True, "clear_attack_preview": True,
        }
    game_state["turn"] += 1
    game_state["current_player"] = 1
    return {
        "phase_complete": True, "phase_transition": True, "next_phase": "command",
        "current_player": 1, "new_turn": game_state["turn"], "units_processed": units_processed,
        "clear_blinking_gentle": True, "reset_mode": "select",
        "clear_selected_unit": True, "clear_attack_preview": True,
    }


def _fight_v11_resolve_attacks(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    config: Dict[str, Any],
    *,
    preferred_target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Résout les attaques de mêlée d'une unité « selected to fight » (réutilise le
    résolveur de dés ``_execute_fight_attack_sequence``). Sélectionne l'arme vs la
    cible préférée/auto, roule NB, déplète les attaques en reciblant si une cible meurt.
    Retourne la liste des ``attack_result``. Liste vide = fight « à vide » (aucune cible).
    """
    from engine.ai.weapon_selector import select_best_melee_weapon

    unit_id = str(require_key(unit, "id"))
    results: List[Dict[str, Any]] = []
    cc_weapons = unit.get("CC_WEAPONS") or []
    if not cc_weapons:
        return results

    targets = _fight_build_valid_target_pool(game_state, unit)
    if not targets:
        return results
    tid = preferred_target_id if (preferred_target_id in targets) else _ai_select_fight_target(
        game_state, unit_id, targets
    )
    tgt = get_unit_by_id(game_state, tid)
    if not tgt:
        return results
    widx = select_best_melee_weapon(unit, tgt, game_state)
    if widx < 0:
        return results
    unit["selectedCcWeaponIndex"] = widx
    weapon = unit["CC_WEAPONS"][widx]
    unit["ATTACK_LEFT"] = resolve_dice_value(require_key(weapon, "NB"), "fight_v11_nb")

    while unit["ATTACK_LEFT"] > 0:
        targets = _fight_build_valid_target_pool(game_state, unit)
        if not targets:
            break
        if tid not in targets:
            tid = _ai_select_fight_target(game_state, unit_id, targets)
        attack_result = _execute_fight_attack_sequence(game_state, unit, tid)
        attack_result["attackerId"] = unit_id
        attack_result["targetId"] = tid
        results.append(attack_result)
        unit["ATTACK_LEFT"] -= 1
        if attack_result.get("target_died"):
            _remove_dead_unit_from_fight_pools(game_state, tid)
    return results


def fight_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:  # noqa: F811 (V11 override of V10)
    """
    START OF FIGHT PHASE V11 (12.01) — override de la version V10.
    Initialise les états V11 et entre dans l'étape PILE IN. Si aucune unité n'est
    éligible à aucune étape, termine la phase immédiatement.
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist at fight_phase_start (should be built at reset)")
    fight_v11_start(game_state)
    add_console_log(game_state, "FIGHT PHASE START (V11)")
    # Phase vide : aucune unité engagée ni ayant chargé → rien à résoudre à aucune étape
    # (pile-in/fight/consolidate) → compléter immédiatement (progression joueur/tour).
    any_actionable = any(
        is_unit_alive(str(require_key(u, "id")), game_state)
        and (_fight_v11_engaged_now(game_state, u) or _fight_v11_charged_this_turn(game_state, u))
        for u in require_key(game_state, "units")
    )
    if not any_actionable:
        _fight_v11_log(game_state, "Aucune unité engagée/chargée → phase FIGHT vide, complétion immédiate")
        return _fight_v11_phase_complete(game_state)

    if not _is_fight_auto_execution_allowed(game_state):
        # Manuel (PvP) : entre dans l'étape PILE IN interactive (aperçu des destinations ≤3").
        # _fight_v11_manual_state présente la 1ère unité et renvoie le contrat waiting_for_pile_in
        # (consommé par le front : mode pileInPreview). Consolidation reste auto-skip (V1).
        _fight_v11_log(game_state, "START (manuel) → étape PILE IN interactive")
        _ok, state = _fight_v11_manual_state(game_state)
        out = dict(state)
        out["phase_initialized"] = True
        return out

    # Auto (PvE/gym) : reste en PILE IN, _fight_v11_auto_step gère les moves.
    game_state["fight_eligible_units"] = fight_v11_current_pool(game_state)
    game_state["active_fight_unit"] = None
    _fight_v11_log(
        game_state,
        f"START → étape PILE IN (éligibles pile-in courants={game_state['fight_eligible_units']})",
    )
    return {"phase_initialized": True, "fight_subphase": "pile_in", "phase_complete": False}


def _fight_v11_auto_pile_in(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Pile-in groupé AUTO (politique décision #7 : toujours si possible). Marque pile_in_done."""
    uid = str(require_key(unit, "id"))
    try:
        engaged = _fight_units_engaged_with(game_state, unit)
        targets = engaged if engaged else pile_in_targets_within_range(game_state, unit)
        if targets:
            dests = pile_in_move_destinations_12_03(game_state, unit, targets)
            if dests:
                d_min, _closest = _fight_pile_in_closest_enemy_snapshot(game_state, unit)
                pc, pr = _ai_select_pile_in_destination(
                    game_state, unit, dests, d_min, [str(t) for t in targets]
                )
                try:
                    _fight_apply_pile_in_move(game_state, unit, pc, pr)
                except ValueError:
                    pass  # destination devenue invalide entre BFS et application
    finally:
        game_state["pile_in_done"].add(uid)


def _fight_v11_auto_overrun_pile_in(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Pile-in additionnel d'un overrun fight AUTO (12.06) : se rapprocher/engager si possible."""
    within = pile_in_targets_within_range(game_state, unit)
    if not within:
        return
    dests = pile_in_move_destinations_12_03(game_state, unit, within)
    if not dests:
        return
    pc, pr = _ai_select_pile_in_destination(game_state, unit, dests, 0, within)
    try:
        _fight_apply_pile_in_move(game_state, unit, pc, pr)
    except ValueError:
        pass


def _fight_v11_auto_consolidate(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Consolidation AUTO (V1) : skip (consolidation est OPTIONNELLE, 12 encart) — choix
    légal et conservateur. Marque consolidation_done. La consolidation auto effective
    (3 modes + déclencheur Engaging, décision #7) est affinée avec l'UI (Bloc front).
    """
    game_state["consolidation_done"].add(str(require_key(unit, "id")))


def _fight_v11_auto_step(game_state: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Une activation V11 par appel (granularité V10), résolution automatique (IA/gym/PvE)."""
    for _ in range(6):
        sub = require_key(game_state, "fight_subphase")
        if sub == "pile_in":
            nxt = fight_v11_grouped_next(game_state, "pile_in")
            if nxt is None:
                fight_v11_enter_fight_step(game_state)
                continue
            uid = nxt[1][0]
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for pile-in")
            _fight_v11_auto_pile_in(game_state, u, config)
            return True, {"action": "pile_in", "phase": "fight", "unitId": uid,
                          "fight_subphase": "pile_in", "waiting_for_player": False}
        if sub == "fight":
            uid = fight_v11_advance_selection(game_state)
            if uid is None:
                fight_v11_enter_consolidate(game_state)
                continue
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for fight")
            game_state["units_selected_to_fight"].add(uid)
            game_state.setdefault("units_fought", set()).add(uid)
            overrun = (
                fight_v11_is_overrun_eligible(game_state, u)
                and not _fight_v11_engaged_now(game_state, u)
            )
            if overrun:
                _fight_v11_auto_overrun_pile_in(game_state, u, config)
            results = _fight_v11_resolve_attacks(game_state, u, config)
            return True, {"action": "combat", "phase": "fight", "unitId": uid,
                          "fight_subphase": "fight", "all_attack_results": results,
                          "fight_type": "overrun" if overrun else "normal",
                          "waiting_for_player": False}
        if sub == "consolidate":
            nxt = fight_v11_grouped_next(game_state, "consolidate")
            if nxt is None:
                return True, _fight_v11_phase_complete(game_state)
            uid = nxt[1][0]
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for consolidate")
            _fight_v11_auto_consolidate(game_state, u, config)
            return True, {"action": "consolidation", "phase": "fight", "unitId": uid,
                          "fight_subphase": "consolidate", "waiting_for_player": False}
        return True, _fight_v11_phase_complete(game_state)
    raise RuntimeError("_fight_v11_auto_step did not converge")


def _fight_pile_in_build_model_pool(
    game_state: Dict[str, Any],
    model_id: str,
    closest_tier_ids: List[str],
    provisional_plan: Optional[Dict[str, Tuple[int, int]]] = None,
) -> Dict[str, List[List[int]]]:
    """Pool de destinations PAR-FIGURINE pour le pile-in (12.03, move par-figurine).

    BFS d'UNE figurine du squad dans le budget fixe de 3" (× ``inches_to_subhex``), sans
    traverser murs ni figs (ennemies, alliées, coéquipières). ``provisional_plan``
    ({model_id: (col, row)}) remplace les positions des coéquipières déjà posées dans le plan UI
    (recompute temps réel). ``closest_tier_ids`` = unité(s) ennemie(s) la/les plus proche(s) de
    l'ESCOUADE (palier WHILE commun à toutes les figs, cf. ``pile_in_move_destinations_12_03``).

    WHILE MOVING (12.03) : chaque destination doit finir l'empreinte du socle **strictement plus
    proche** du palier le plus proche qu'à son départ. Les contraintes AFTER au niveau unité
    (escouade engagée, engagements conservés) et la cohésion sont vérifiées au commit, pas ici.

    Retour : {"closer": [[col,row],...], "engaged": [[col,row],...]} (engaged ⊆ closer ; engaged =
    le socle finit à <= EZ d'au moins une cible du palier). Lecture pure.
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _charge_prepare_footprint_offsets,
        _candidate_footprint_charge,
        _charge_synthetic_charger_cache_entry,
    )

    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(f"_fight_pile_in_build_model_pool: model {model_id} not in models_cache")
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    empty: Dict[str, List[List[int]]] = {"closer": [], "engaged": []}
    if not unit:
        return empty

    ez = int(get_engagement_zone(game_state))
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    units_cache = require_key(game_state, "units_cache")

    closest = {str(t) for t in closest_tier_ids}
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    enemy_occupied: Set[Tuple[int, int]] = set()
    other_occupied: Set[Tuple[int, int]] = set()
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            enemy_occupied |= cells
            if str(eid) in closest:
                target_entries.append(entry)
                target_fps.append(cells)
        elif str(eid) != squad_id:
            other_occupied |= cells
    if not target_entries:
        return empty

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)

    # Coéquipières : collision (le plan provisoire override les figs déjà posées).
    same_squad_occupied: Set[Tuple[int, int]] = set()
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        if provisional_plan and str(mid) in provisional_plan:
            pc, pr = provisional_plan[str(mid)]
            sib_fp = _candidate_footprint_charge(int(pc), int(pr), unit, game_state, fp_offset_pair)
        else:
            sib = models_cache.get(str(mid))
            if sib is None:
                continue
            sib_fp = _candidate_footprint_charge(
                int(sib["col"]), int(sib["row"]), unit, game_state, fp_offset_pair
            )
        same_squad_occupied |= sib_fp

    # 03.01 : une figurine se déplace À TRAVERS les figs amies, mais PAS à travers les ennemies
    # (ni les murs). Donc le CHEMIN ne bloque que murs + ennemis ; les amis (coéquipières + autres
    # unités amies) ne bloquent pas le passage.
    path_blocked = set(wall_hexes) | enemy_occupied
    # 03 « Ending a move » : aucune fig ne peut FINIR sur une autre fig → l'empreinte finale ne doit
    # chevaucher aucune autre fig (amie ou ennemie) ni un mur.
    end_blocked = path_blocked | other_occupied | same_squad_occupied

    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _candidate_footprint_charge(start_col, start_row, unit, game_state, fp_offset_pair)
    start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)

    # BFS centre-à-centre ≤ budget : ne traverse ni mur ni fig ENNEMIE (les amies sont traversables).
    visited: Set[Tuple[int, int]] = {(start_col, start_row)}
    reachable: List[Tuple[int, int]] = []
    queue: deque = deque([(start_col, start_row, 0)])
    while queue:
        c, r, d = queue.popleft()
        if d >= budget:
            continue
        for nc, nr in get_hex_neighbors(c, r):
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            cell = (nc, nr)
            if cell in visited or cell in path_blocked:
                continue
            visited.add(cell)
            queue.append((nc, nr, d + 1))
            reachable.append(cell)

    closer: List[List[int]] = []
    engaged: List[List[int]] = []
    for cc, rr in reachable:
        cand_fp = _candidate_footprint_charge(cc, rr, unit, game_state, fp_offset_pair)
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if cand_fp & end_blocked:
            continue
        d_min = min(
            min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps
        )
        if d_min >= start_min:
            continue  # WHILE MOVING : strictement plus proche du palier le plus proche
        closer.append([cc, rr])
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, cc, rr, cand_fp)
        if any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
            engaged.append([cc, rr])

    return {"closer": closer, "engaged": engaged}


def _fight_pile_in_closest_tier_ids(
    game_state: Dict[str, Any], unit: Dict[str, Any], target_ids: List[str]
) -> List[str]:
    """Sous-ensemble de ``target_ids`` au palier de distance minimale de l'empreinte de l'unité —
    palier WHILE commun à toutes les figs (cf. ``pile_in_move_destinations_12_03``)."""
    from engine.hex_utils import min_distance_between_sets

    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None:
        return []
    unit_fp = set(entry.get("occupied_hexes") or {(int(entry["col"]), int(entry["row"]))})
    d_min: Optional[int] = None
    tier: List[str] = []
    for tid in target_ids:
        ce = units_cache.get(str(tid))
        if ce is None:
            continue
        efp = set(ce.get("occupied_hexes") or {(int(ce["col"]), int(ce["row"]))})
        d = min_distance_between_sets(unit_fp, efp)
        if d_min is None or d < d_min:
            d_min = d
            tier = [str(tid)]
        elif d == d_min:
            tier.append(str(tid))
    return tier


def _fight_pile_in_preview_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    plan: List[Tuple[str, int, int]],
    closest_tier_ids: List[str],
    engaged_before_ids: List[str],
) -> Dict[str, Any]:
    """Dry-run d'un plan pile-in par-figurine (12.03 WHILE/AFTER + cohésion 03.03). Lecture pure.

    ``plan`` couvre TOUTES les figs vivantes. Légalité par-fig = appartenance au pool ``closer``
    (ou figurine laissée à sa position d'origine). On ajoute la cohésion d'unité et les contraintes
    AFTER au niveau unité : l'escouade finit engagée et chaque engagement de départ est conservé.

    Retour : {per_model, coherency_ok, unit_engaged, kept_engagements, can_validate}.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import (
        get_engagement_zone,
        get_coherency_subhex,
        get_cohesion_max_subhex,
        get_min_neighbors,
    )
    from .charge_handlers import _charge_prepare_footprint_offsets, _candidate_footprint_charge

    unit = get_unit_by_id(game_state, str(squad_id))
    empty = {
        "per_model": {},
        "coherency_ok": False,
        "unit_engaged": False,
        "kept_engagements": False,
        "can_validate": False,
    }
    if not unit:
        return empty
    models_cache = require_key(game_state, "models_cache")
    norm = [(str(m), int(c), int(r)) for m, c, r in plan]
    n = len(norm)
    if n == 0:
        return empty

    # 1) Légalité par-fig : dans son pool ``closer`` (autres figs = positions provisoires) ou immobile.
    pos_by_model = {mid: (c, r) for mid, c, r in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        m = models_cache.get(mid)
        orig = (int(m["col"]), int(m["row"])) if m else None
        if orig is not None and (c, r) == orig:
            per_model[mid] = True
            continue
        pool = _fight_pile_in_build_model_pool(
            game_state, mid, closest_tier_ids, provisional_plan=prov
        )["closer"]
        per_model[mid] = [c, r] in pool

    # 2) Cohésion 03.03 (empreinte-à-empreinte, mêmes 2 puces que le move).
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    fps = [_candidate_footprint_charge(c, r, unit, game_state, fp_pair) for _, c, r in norm]
    coh = get_coherency_subhex(game_state)
    coh_max = get_cohesion_max_subhex(game_state)
    min_nb = get_min_neighbors(game_state)
    coherency_ok = True
    if n > 1:
        neigh = [0] * n
        too_far = [False] * n
        for i in range(n):
            for j in range(i + 1, n):
                d = min_distance_between_sets(fps[i], fps[j], max_distance=coh_max)
                if d <= coh:
                    neigh[i] += 1
                    neigh[j] += 1
                if d > coh_max:
                    too_far[i] = True
                    too_far[j] = True
        for i in range(n):
            if neigh[i] < min_nb or too_far[i]:
                coherency_ok = False
                break

    # 3) AFTER (12.03) au niveau unité : empreinte union engagée + engagements de départ conservés.
    union_fp: Set[Tuple[int, int]] = set()
    for f in fps:
        union_fp |= f
    anchor_c, anchor_r = norm[0][1], norm[0][2]
    synth_unit = _fight_synth_cache_entry_at_footprint(unit, game_state, anchor_c, anchor_r, union_fp)
    ez = int(get_engagement_zone(game_state))
    units_cache = require_key(game_state, "units_cache")
    player = int(require_key(unit, "player"))
    unit_engaged = any(
        int(ce["player"]) != player and unit_entries_within_engagement_zone(synth_unit, ce, ez)
        for eid, ce in units_cache.items()
        if str(eid) != str(squad_id)
    )
    kept_engagements = True
    for eid in engaged_before_ids:
        ce = units_cache.get(str(eid))
        if ce is None:
            continue
        if not unit_entries_within_engagement_zone(synth_unit, ce, ez):
            kept_engagements = False
            break

    can_validate = bool(
        all(per_model.values()) and coherency_ok and unit_engaged and kept_engagements
    )
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "unit_engaged": unit_engaged,
        "kept_engagements": kept_engagements,
        "can_validate": can_validate,
    }


def _fight_pile_in_model_plan_state(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    provisional_plan: Optional[Dict[str, Tuple[int, int]]] = None,
    selected_model: Optional[str] = None,
) -> Dict[str, Any]:
    """État du plan pile-in par-figurine exposé au front (miroir simplifié de ``charge_model_plan_state``).

    Une seule « phase » (pas de within_1/engaged/closer) : chaque fig peut se déplacer ≤3" en finissant
    plus proche du palier ennemi le plus proche. ``provisional_plan`` = figs déjà posées ; les autres
    restent à leur position d'origine. ``selected_model`` non-None → calcule SON pool + empreinte lissée.
    """
    from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _charge_prepare_footprint_offsets,
        _candidate_footprint_charge,
        _charge_synthetic_charger_cache_entry,
    )

    squad_id = str(require_key(unit, "id"))
    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [str(m) for m in require_key(squad_models, squad_id) if str(m) in models_cache]
    prov: Dict[str, Tuple[int, int]] = {
        str(m): (int(c), int(r)) for m, (c, r) in (provisional_plan or {}).items()
    }
    origin = {m: (int(models_cache[m]["col"]), int(models_cache[m]["row"])) for m in alive}

    targets = _fight_v11_pile_in_targets(game_state, unit)
    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, targets) if targets else []

    unplaced = [m for m in alive if m not in prov]
    eligible: List[str] = []
    for m in unplaced:
        if _fight_pile_in_build_model_pool(game_state, m, closest_tier, provisional_plan=prov)["closer"]:
            eligible.append(m)

    pool: List[List[int]] = []
    mask_loops: List[List[List[float]]] = []
    if selected_model is not None and str(selected_model) in alive:
        sel = str(selected_model)
        sel_prov = {k: v for k, v in prov.items() if k != sel}
        pool = _fight_pile_in_build_model_pool(game_state, sel, closest_tier, provisional_plan=sel_prov)["closer"]
        if pool:
            fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
            fp_zone: Set[Tuple[int, int]] = set()
            for cc, rr in pool:
                fp_zone |= _candidate_footprint_charge(int(cc), int(rr), unit, game_state, fp_pair)
            loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
            if loops:
                mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    full_plan: List[Tuple[str, int, int]] = [
        (m, prov[m][0], prov[m][1]) if m in prov else (m, origin[m][0], origin[m][1]) for m in alive
    ]
    engaged_before = _fight_units_engaged_with(game_state, unit)
    prev = _fight_pile_in_preview_plan(game_state, squad_id, full_plan, closest_tier, engaged_before)

    # Figs (posées ou à l'origine) dont l'empreinte finit à ≤ EZ d'une cible pile-in → voile vert UI
    # (en mesure de frapper). Cibles exposées au front pour le cercle violet + hit-test du Focus.
    ez = int(get_engagement_zone(game_state))
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    target_entries = [units_cache[t] for t in targets if t in units_cache]
    engaged_models: List[str] = []
    for m, c, r in full_plan:
        fp = _candidate_footprint_charge(int(c), int(r), unit, game_state, fp_pair)
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, int(c), int(r), fp)
        if any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
            engaged_models.append(m)

    return {
        "phase": "fight",
        "fight_subphase": "pile_in",
        "pile_in_model_move": True,
        "engaged_models": engaged_models,
        "pile_in_targets": [str(t) for t in targets],
        "unitId": squad_id,
        "active_fight_unit": squad_id,
        "origin_models": {m: [c, r] for m, (c, r) in origin.items()},
        "provisional": {m: [c, r] for m, (c, r) in prov.items()},
        "eligible_models": eligible,
        "selected_model": str(selected_model) if selected_model is not None else None,
        "pool": pool,
        "footprint_mask_loops": mask_loops,
        "unplaced": unplaced,
        "can_validate": prev["can_validate"],
        # Sous-conditions de légalité (diagnostic + voile rouge front) : voile par-fig invalide
        # (per_model False) et raisons unité (cohésion / engagement / engagements conservés).
        "per_model_valid": prev["per_model"],
        "coherency_ok": prev["coherency_ok"],
        "unit_engaged": prev["unit_engaged"],
        "kept_engagements": prev["kept_engagements"],
        "waiting_for_player": True,
        "action": "wait",
    }


def _fight_pile_in_commit_plan(
    game_state: Dict[str, Any], unit: Dict[str, Any], plan: List[Tuple[str, int, int]]
) -> None:
    """Pose le plan pile-in par-figurine (``commit_move`` type ``pile_in``) + resync l'ancre de l'unité."""
    from .shared_utils import commit_move, set_unit_coordinates

    commit_move(plan, game_state, "pile_in")
    entry = require_key(game_state, "units_cache").get(str(require_key(unit, "id")))
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))


def _fight_model_in_base_contact(
    game_state: Dict[str, Any], model_entry: Dict[str, Any]
) -> bool:
    """True si la figurine est en base-contact (socles collés, écart ≤ 0) avec ≥1 fig ennemie.

    Règle 12.03 WHILE : « Models in base-contact with one or more enemy models cannot be moved. »
    Socles ronds (Board ×10) → écart euclidien bord-à-bord ; sinon métrique empreinte (contact ⟺
    distance 0). Lecture pure, réutilise les primitives moteur (aucune géométrie réimplémentée).
    """
    from engine.hex_utils import euclidean_edge_clearance_round_round, min_distance_between_sets
    from .charge_handlers import _charge_model_footprint

    mc, mr = int(model_entry["col"]), int(model_entry["row"])
    mshape = model_entry["BASE_SHAPE"]
    mbs = model_entry["BASE_SIZE"]
    player = int(model_entry["player"])
    fp = _charge_model_footprint(game_state, model_entry, mc, mr)
    units_cache = require_key(game_state, "units_cache")
    for ce in units_cache.values():
        if int(ce["player"]) == player:
            continue
        eshape = ce["BASE_SHAPE"]
        ebs = ce["BASE_SIZE"]
        if mshape == "round" and eshape == "round" and isinstance(mbs, int) and isinstance(ebs, int):
            by_model = ce.get("occupied_hexes_by_model")
            positions = by_model.values() if by_model else [(int(ce["col"]), int(ce["row"]))]
            for ec, er in positions:
                if euclidean_edge_clearance_round_round(mc, mr, mbs, int(ec), int(er), ebs) <= 1e-6:
                    return True
        else:
            efp = ce.get("occupied_hexes") or {(int(ce["col"]), int(ce["row"]))}
            if min_distance_between_sets(fp, efp, max_distance=0) <= 0:
                return True
    return False


def pile_in_autoplace_plan(
    game_state: Dict[str, Any], squad_id: str, focus_target_id: str
) -> Dict[str, Any]:
    """Auto-placement de pile-in (12.03) : positionne les figs du squad pour MAXIMISER le nombre de
    figs en mesure de frapper le focus (empreinte ≤ EZ bord-à-bord de ``focus_target_id``). Lecture pure.

    Optimum EXACT par programme linéaire en nombres entiers (``scipy.optimize.milp`` / HiGHS), car les
    socles sont multi-hex (Board ×10) : le non-chevauchement entre empreintes est modélisé par une
    contrainte **par cellule** (chaque hex couvert par ≤ 1 fig posée), ce qu'un simple matching biparti
    ne capture pas. Formulation :
      - variable binaire x[f,s] = fig f posée au slot s (créée seulement pour les arêtes LÉGALES) ;
      - 1 fig ≤ 1 slot : Σ_s x[f,s] ≤ 1 ;
      - non-chevauchement : pour chaque cellule h, Σ_{(f,s): h ∈ empreinte(s)} x[f,s] ≤ 1 ;
      - objectif : maximiser Σ x (toutes les arêtes engagent le focus), départage = distance minimale.

    Contraintes de règle (12.03), par arête, conformes au pool/commit pile-in existant :
      - budget 3" (× inches_to_subhex), atteignabilité BFS centre-à-centre (mur/ennemi bloquent, amies
        traversables — 03.01) ;
      - figs en base-contact FIGÉES (ne bougent pas) ;
      - WHILE : empreinte au slot strictement plus proche du palier le plus proche que le départ de la fig ;
      - AFTER : chaque engagement de départ de la fig est conservé au slot.

    Les slots sont générés UNE fois par taille de socle sur la BANDE d'engagement du focus (pas tout le
    rayon). Les figs non affectées par l'ILP sont rapprochées au max le long de leur zone atteignable
    (strictement plus proche, sans chevaucher). Garde-fou final : aucun chevauchement de cellules.

    Retour : {"plan": [[model_id, col, row], ...]} couvrant toutes les figs vivantes.
    """
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy.sparse import coo_matrix
    from engine.hex_utils import min_distance_between_sets, footprints_overlap, Socle
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _charge_model_footprint,
        _charge_model_socle,
        _charge_synthetic_charger_cache_entry,
    )

    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        return {"plan": []}

    units_cache = require_key(game_state, "units_cache")
    focus_entry = units_cache.get(str(focus_target_id))
    if focus_entry is None:
        raise ValueError(
            f"pile_in_autoplace_plan: cible focus {focus_target_id} absente de units_cache"
        )

    targets = _fight_v11_pile_in_targets(game_state, unit)
    if str(focus_target_id) not in {str(t) for t in targets}:
        raise ValueError(
            f"pile_in_autoplace_plan: focus {focus_target_id} hors cibles pile-in {targets}"
        )
    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, targets)
    if not closest_tier:
        raise ValueError(f"pile_in_autoplace_plan: palier le plus proche introuvable pour {squad_id}")

    ez = int(get_engagement_zone(game_state))
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    walls = set(game_state.get("wall_hexes", set()))
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [str(m) for m in require_key(squad_models, str(squad_id)) if str(m) in models_cache]
    if not alive:
        return {"plan": []}

    player = int(require_key(unit, "player"))
    focus_occ = focus_entry.get("occupied_hexes")
    focus_fp = set(focus_occ) if focus_occ else {(int(focus_entry["col"]), int(focus_entry["row"]))}

    # Palier WHILE : empreintes des cibles les plus proches de l'unité.
    tier_fps: List[Set[Tuple[int, int]]] = []
    for tid in closest_tier:
        ce = units_cache.get(str(tid))
        if ce is None:
            continue
        occ = ce.get("occupied_hexes")
        tier_fps.append(set(occ) if occ else {(int(ce["col"]), int(ce["row"]))})

    # Collision = test EUCLIDIEN officiel du jeu (``footprints_overlap`` : rond↔rond bord-à-bord
    # continu, fallback empreinte sinon), pas l'intersection de cellules — sinon des socles ronds
    # disjoints en cellules mais chevauchants visuellement passent à travers.
    def _socle(mid: str, c: int, r: int) -> Any:
        return _charge_model_socle(game_state, models_cache[mid], c, r)

    def _overlaps(s: Any, others: List[Any]) -> bool:
        if walls and (s.fp & walls):
            return True
        return any(footprints_overlap(s, o) for o in others)

    # Socles bloquants PAR FIGURINE : ennemis + autres unités amies (rond↔rond exact par modèle).
    blocker_socles: List[Any] = []
    for eid, entry in units_cache.items():
        if str(eid) == str(squad_id):
            continue
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for mc, mr in by_model.values():
                blocker_socles.append(
                    Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                          col=int(mc), row=int(mr), fp={(int(mc), int(mr))})
                )
        else:
            occ = entry.get("occupied_hexes")
            blocker_socles.append(
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]),
                      fp=set(occ) if occ else {(int(entry["col"]), int(entry["row"]))})
            )

    # Ennemis (cellules occupées) : bloquent la TRAVERSÉE du BFS (les amies sont traversables, 03.01).
    enemy_occupied: Set[Tuple[int, int]] = set()
    for entry in units_cache.values():
        if int(entry["player"]) != player:
            occ = entry.get("occupied_hexes")
            enemy_occupied |= set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}

    # Figs figées (base-contact) : ne bougent pas ; leurs socles bloquent les placements.
    frozen_socles: List[Any] = []
    movable: List[str] = []
    for mid in alive:
        m = models_cache[mid]
        if _fight_model_in_base_contact(game_state, m):
            frozen_socles.append(_socle(mid, int(m["col"]), int(m["row"])))
        else:
            movable.append(mid)

    path_blocked = walls | enemy_occupied
    static_blockers = blocker_socles + frozen_socles

    def _model_fp(mid: str, c: int, r: int) -> Set[Tuple[int, int]]:
        return _charge_model_footprint(game_state, models_cache[mid], c, r)

    def _engages_focus(c: int, r: int, fp: Set[Tuple[int, int]]) -> bool:
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, c, r, fp)
        return unit_entries_within_engagement_zone(synth, focus_entry, ez)

    def _fp_min_to_tier(fp: Set[Tuple[int, int]]) -> int:
        return min(min_distance_between_sets(fp, t) for t in tier_fps) if tier_fps else 1 << 30

    # --- Slots : bande d'engagement du focus, par taille de socle distincte (coût). ---
    def _base_key(m: Dict[str, Any]) -> Tuple[Any, Any]:
        bs = m["BASE_SIZE"]
        return (m["BASE_SHAPE"], tuple(bs) if isinstance(bs, (list, tuple)) else bs)

    by_base: Dict[Tuple[Any, Any], List[str]] = {}
    for mid in movable:
        by_base.setdefault(_base_key(models_cache[mid]), []).append(mid)

    # Liste GLOBALE des slots (toutes bases) : (col, row, Socle, slot_min_to_tier).
    all_slots: List[Tuple[int, int, Any, int]] = []
    # slots_by_base[bkey] = [index dans all_slots, ...]
    slots_by_base: Dict[Tuple[Any, Any], List[int]] = {}
    fcs = [c for c, _ in focus_fp]
    frs = [r for _, r in focus_fp]
    for bkey, mids in by_base.items():
        rep_id = mids[0]
        rep = models_cache[rep_id]
        bs = rep["BASE_SIZE"]
        base_dim = max(bs) if isinstance(bs, (list, tuple)) else bs
        margin = ez + int(base_dim) + 2
        idxs: List[int] = []
        for c in range(min(fcs) - margin, max(fcs) + margin + 1):
            if c < 0 or c >= board_cols:
                continue
            for r in range(min(frs) - margin, max(frs) + margin + 1):
                if r < 0 or r >= board_rows:
                    continue
                soc = _socle(rep_id, c, r)
                if any(not (0 <= x < board_cols and 0 <= y < board_rows) for x, y in soc.fp):
                    continue
                if _overlaps(soc, static_blockers):
                    continue
                if not _engages_focus(c, r, set(soc.fp)):
                    continue
                idxs.append(len(all_slots))
                all_slots.append((c, r, soc, _fp_min_to_tier(set(soc.fp))))
        slots_by_base[bkey] = idxs

    # --- Atteignabilité par fig (BFS centre-à-centre ≤ budget, amies traversables). ---
    starts = {mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in movable}
    start_fp = {mid: _model_fp(mid, *starts[mid]) for mid in movable}
    start_min = {mid: _fp_min_to_tier(start_fp[mid]) for mid in movable}

    def _reachable(mid: str) -> Dict[Tuple[int, int], int]:
        sc, sr = starts[mid]
        dist: Dict[Tuple[int, int], int] = {(sc, sr): 0}
        queue: deque = deque([(sc, sr, 0)])
        while queue:
            c, r, d = queue.popleft()
            if d >= budget:
                continue
            for nc, nr in get_hex_neighbors(c, r):
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                cell = (nc, nr)
                if cell in dist or cell in path_blocked:
                    continue
                dist[cell] = d + 1
                queue.append((nc, nr, d + 1))
        return dist

    # Engagements de départ par fig (AFTER : à conserver au slot).
    def _start_engagements(mid: str) -> List[Dict[str, Any]]:
        synth = _charge_synthetic_charger_cache_entry(game_state, unit, *starts[mid], start_fp[mid])
        out: List[Dict[str, Any]] = []
        for eid, ce in units_cache.items():
            if int(ce["player"]) == player or str(eid) == str(squad_id):
                continue
            if unit_entries_within_engagement_zone(synth, ce, ez):
                out.append(ce)
        return out

    # --- Arêtes ILP : (fig f, slot s) légales. edges_by_slot[s] = liste d'indices d'arête. ---
    edges: List[Tuple[str, int, int]] = []  # (mid, slot_index, pathdist)
    for mid in movable:
        sm = start_min[mid]
        if sm <= 0:
            continue  # déjà au contact du palier : aucun slot strictement plus proche
        reach = _reachable(mid)
        start_eng = _start_engagements(mid)
        for si in slots_by_base[_base_key(models_cache[mid])]:
            sc, sr, soc, slot_min = all_slots[si]
            if slot_min >= sm:
                continue  # WHILE : strictement plus proche du palier
            pd = reach.get((sc, sr))
            if pd is None:
                continue  # slot hors budget (atteignabilité réelle)
            if start_eng:
                synth_slot = _charge_synthetic_charger_cache_entry(game_state, unit, sc, sr, set(soc.fp))
                if not all(unit_entries_within_engagement_zone(synth_slot, ce, ez) for ce in start_eng):
                    continue  # AFTER : un engagement de départ serait perdu
            edges.append((mid, si, pd))

    provisional: Dict[str, Tuple[int, int]] = {}
    placed_socles: List[Any] = list(static_blockers)

    if edges:
        n = len(edges)
        mids_idx = {mid: i for i, mid in enumerate(sorted({e[0] for e in edges}))}
        used_slots = sorted({e[1] for e in edges})
        slot_row = {si: k for k, si in enumerate(used_slots)}
        n_model = len(mids_idx)
        n_slot = len(used_slots)
        # Contraintes : (1) 1 fig ≤ 1 slot ; (2) 1 slot ≤ 1 fig ; (3) slots en CHEVAUCHEMENT euclidien
        # mutuellement exclusifs (packing exact multi-hex). Lignes : modèles, puis slots, puis conflits.
        rows: List[int] = []
        cols: List[int] = []
        for e_i, (mid, si, _pd) in enumerate(edges):
            rows.append(mids_idx[mid]); cols.append(e_i)              # (1)
            rows.append(n_model + slot_row[si]); cols.append(e_i)     # (2)
        # (3) paires de slots utilisés qui se chevauchent → 1 ligne par paire.
        conflict_pairs: List[Tuple[int, int]] = []
        for a in range(n_slot):
            sa = all_slots[used_slots[a]][2]
            for b in range(a + 1, n_slot):
                if footprints_overlap(sa, all_slots[used_slots[b]][2]):
                    conflict_pairs.append((used_slots[a], used_slots[b]))
        edges_by_slot: Dict[int, List[int]] = {}
        for e_i, (_mid, si, _pd) in enumerate(edges):
            edges_by_slot.setdefault(si, []).append(e_i)
        base_rows = n_model + n_slot
        for k, (s1, s2) in enumerate(conflict_pairs):
            for e_i in edges_by_slot.get(s1, []) + edges_by_slot.get(s2, []):
                rows.append(base_rows + k); cols.append(e_i)
        n_rows = base_rows + len(conflict_pairs)
        A = coo_matrix(([1.0] * len(rows), (rows, cols)), shape=(n_rows, n))
        lc = LinearConstraint(A, np.zeros(n_rows), np.ones(n_rows))
        max_pd = max((e[2] for e in edges), default=0) + 1
        # Objectif : maximiser le nb de figs posées (gain BIG/fig), départage par distance parcourue.
        BIG = 1.0e6
        c = np.array([-BIG + e[2] / max_pd for e in edges], dtype=float)
        res = milp(
            c=c, constraints=[lc], integrality=np.ones(n),
            bounds=Bounds(0, 1), options={"time_limit": 2.0},
        )
        if res.x is not None:
            for e_i, x in enumerate(res.x):
                if x > 0.5:
                    mid, si, _pd = edges[e_i]
                    sc, sr, soc, _sm = all_slots[si]
                    provisional[mid] = (sc, sr)
                    placed_socles.append(soc)

    # Figs mobiles non posées par l'ILP : rapprochement au max (strictement plus proche, sans chevaucher).
    placed = set(provisional)
    for mid in movable:
        if mid in placed:
            continue
        sm = start_min[mid]
        best: Optional[Tuple[int, int]] = None
        if sm > 0:
            best_score = None
            for (cc, rr), _pd in _reachable(mid).items():
                if (cc, rr) == starts[mid]:
                    continue
                soc = _socle(mid, cc, rr)
                if any(not (0 <= x < board_cols and 0 <= y < board_rows) for x, y in soc.fp):
                    continue
                if _overlaps(soc, placed_socles):
                    continue
                d_tier = _fp_min_to_tier(set(soc.fp))
                if d_tier >= sm:
                    continue  # WHILE
                d_focus = min_distance_between_sets(set(soc.fp), focus_fp)
                if best_score is None or d_focus < best_score:
                    best_score = d_focus
                    best = (cc, rr)
            if best is not None:
                provisional[mid] = best
                placed_socles.append(_socle(mid, *best))
        if mid not in provisional:
            provisional[mid] = starts[mid]  # reste à sa position (départ)

    # Figs figées : conservées à leur départ.
    for mid in alive:
        if mid not in provisional:
            m = models_cache[mid]
            provisional[mid] = (int(m["col"]), int(m["row"]))

    # Garde-fou : aucun chevauchement de socles (test euclidien officiel) dans le plan produit.
    # Erreur explicite plutôt qu'un plan illégal silencieux (le contact tangent gap≈0 reste autorisé).
    socs = {mid: _socle(mid, *provisional[mid]) for mid in alive}
    items = list(socs.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if footprints_overlap(items[i][1], items[j][1]):
                raise ValueError(
                    f"pile_in_autoplace_plan: chevauchement de socles entre {items[i][0]} "
                    f"({provisional[items[i][0]]}) et {items[j][0]} ({provisional[items[j][0]]})"
                )

    plan = [[mid, int(provisional[mid][0]), int(provisional[mid][1])] for mid in alive]
    return {"plan": plan}


def _fight_v11_pile_in_targets(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Cibles de pile-in (12.03) en auto-sélection : toutes les unités engagées si engagée,
    sinon les ennemis dans ``pile_in_target_range`` (5\")."""
    engaged = _fight_units_engaged_with(game_state, unit)
    return engaged if engaged else pile_in_targets_within_range(game_state, unit)


def _fight_v11_clear_pile_in_preview(game_state: Dict[str, Any]) -> None:
    game_state.pop("fight_pile_in_footprint_zone", None)
    game_state.pop("_fight_v11_pile_in_dests", None)


def _fight_v11_pile_in_present(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Prépare l'aperçu pile-in d'une unité (destinations ≤3" + footprint zone), exposé au front.
    Retourne le dict résultat ``waiting_for_pile_in`` ou None si aucune destination utile."""
    targets = _fight_v11_pile_in_targets(game_state, unit)
    if not targets:
        return None
    dests = pile_in_move_destinations_12_03(game_state, unit, targets)
    if not dests:
        return None
    uid = str(require_key(unit, "id"))
    game_state["active_fight_unit"] = uid
    # NB: fight_eligible_units (pool cliquable du front) est posé par l'appelant
    # avec la liste COMPLÈTE du groupe éligible (libre choix de l'unité à piler),
    # pas réduit à l'unité présentée.
    game_state["fight_pile_in_footprint_zone"] = list(
        _fight_compute_pile_in_footprint_zone(game_state, unit, dests)
    )
    game_state["_fight_v11_pile_in_dests"] = [(int(c), int(r)) for c, r in dests]
    return {
        "phase": "fight", "fight_subphase": "pile_in", "waiting_for_pile_in": True,
        "valid_pile_in_destinations": [[int(c), int(r)] for c, r in dests],
        "unitId": uid, "active_fight_unit": uid,
        "waiting_for_player": True, "action": "wait",
    }


def _fight_v11_manual_state(game_state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """État actionnable courant pour le joueur humain (PvP). Avance les transitions de sous-phase."""
    for _ in range(64):
        sub = require_key(game_state, "fight_subphase")
        if sub == "pile_in":
            nxt = fight_v11_grouped_next(game_state, "pile_in")
            if nxt is None:
                fight_v11_enter_fight_step(game_state)
                continue
            # Présentation PARESSEUSE : on n'auto-présente AUCUNE unité (aucun BFS calculé
            # d'avance). Le joueur choisit librement l'unité à piler (clic → activate_unit,
            # qui déclenche le calcul de SES destinations) ou termine l'étape (end_pile_in).
            # On expose seulement le pool cliquable + aucune unité active.
            player, eligible = nxt
            done = {str(x) for x in game_state.get("pile_in_done", set())}
            pool = [str(u) for u in eligible if str(u) not in done]
            game_state["fight_eligible_units"] = pool
            game_state["active_fight_unit"] = None
            _fight_v11_clear_pile_in_preview(game_state)
            _fight_v11_log(
                game_state,
                f"PILE IN P{player} : unités éligibles = {pool} (sélection libre)",
            )
            return True, {
                "phase": "fight", "fight_subphase": "pile_in",
                "fight_eligible_units": pool,
                "active_fight_unit": None,
                "waiting_for_player": True, "action": "wait",
                "unitId": "SYSTEM",
            }
        if sub == "fight":
            uid = fight_v11_advance_selection(game_state)
            if uid is None:
                fight_v11_enter_consolidate(game_state)
                continue
            u = get_unit_by_id(game_state, uid)
            valid_targets = _fight_build_valid_target_pool(game_state, u) if u else []
            game_state["fight_eligible_units"] = [uid]
            game_state["active_fight_unit"] = uid
            game_state["valid_fight_targets"] = valid_targets
            _fight_v11_log(
                game_state,
                f"état: FIGHT — unit {uid} à activer (step={game_state['fight_step']}, "
                f"selector=P{game_state['fight_selector']}, cibles={valid_targets})",
            )
            return True, {"phase": "fight", "fight_subphase": "fight",
                          "fight_step": game_state["fight_step"],
                          "fight_selector": game_state["fight_selector"],
                          "active_fight_unit": uid, "valid_targets": valid_targets,
                          "overrun_eligible": bool(u and fight_v11_is_overrun_eligible(game_state, u)),
                          "waiting_for_player": True, "action": "wait"}
        if sub == "consolidate":
            nxt = fight_v11_grouped_next(game_state, "consolidate")
            if nxt is None:
                return True, _fight_v11_phase_complete(game_state)
            # UI consolidation non câblée → auto-skip du groupe (move OPTIONNEL), on avance.
            player, eligible = nxt
            for u in eligible:
                game_state["consolidation_done"].add(u)
            _fight_v11_log(game_state, f"CONSOLIDATE P{player} auto-skip (UI non câblée): {list(eligible)}")
            continue
        return True, _fight_v11_phase_complete(game_state)
    raise RuntimeError("_fight_v11_manual_state did not converge")


def _fight_v11_manual_step(
    game_state: Dict[str, Any],
    unit: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Traite une action humaine (PvP) dans l'étape V11 courante, puis renvoie l'état suivant."""
    sub = require_key(game_state, "fight_subphase")
    atype = action.get("action")
    uid = action.get("unitId")
    if uid is None and unit is not None:
        uid = unit["id"]
    uid = str(uid) if uid is not None else None
    skip = action.get("skip") is True or atype in ("skip", "right_click")
    _fight_v11_log(game_state, f"action manuelle reçue: subphase={sub} action={atype!r} unitId={uid} skip={skip}")

    if sub == "pile_in":
        nxt = fight_v11_grouped_next(game_state, "pile_in")
        eligible = nxt[1] if nxt else []
        if atype == "end_pile_in":
            # Bouton « Terminer le pile-in » : marque tout le groupe actif comme traité
            # (les unités non pilées sont simplement passées) → on avance vers le groupe
            # adverse puis la sous-phase FIGHT.
            for e in eligible:
                game_state["pile_in_done"].add(str(e))
            _fight_v11_clear_pile_in_preview(game_state)
            _fight_v11_log(
                game_state,
                f"PILE IN → fin demandée par le joueur (groupe {list(eligible)} marqué traité)",
            )
            return _fight_v11_manual_state(game_state)
        # --- Pile-in PAR-FIGURINE (move fin, miroir charge) ---
        active = game_state.get("active_fight_unit")
        act_uid = str(active) if active is not None else None

        def _prov_from_action() -> Dict[str, Tuple[int, int]]:
            prov: Dict[str, Tuple[int, int]] = {}
            for e in (action.get("plan") or []):
                prov[str(e[0])] = (int(e[1]), int(e[2]))
            return prov

        if skip:
            # Le joueur renonce à piler l'unité active → marquée traitée sans déplacement.
            if act_uid is not None and act_uid in eligible:
                game_state["pile_in_done"].add(act_uid)
                _fight_v11_log(game_state, f"PILE IN unit {act_uid} → SKIP (joueur)")
            _fight_v11_clear_pile_in_preview(game_state)
            return _fight_v11_manual_state(game_state)

        if atype == "pile_in_plan_state":
            # Refresh de l'aperçu par-figurine (plan provisoire + figurine sélectionnée).
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            u = get_unit_by_id(game_state, act_uid)
            if u is None:
                raise KeyError(f"Pile-in unit {act_uid} missing from game_state['units']")
            sel = action.get("selected_model")
            return True, _fight_pile_in_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None
            )

        if atype == "pile_in_autoplace":
            # Focus : auto-placement optimal (ILP) des figs pour maximiser celles frappant la cible.
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            focus = action.get("targetId")
            if focus is None:
                return False, {"error": "pile_in_autoplace requires targetId", "action": action}
            out = pile_in_autoplace_plan(game_state, act_uid, str(focus))
            return True, {"action": "pile_in_autoplace", "unitId": act_uid, **out}

        if atype == "commit_pile_in_plan":
            # Validation finale : pose toutes les figs (posées + origine) si le plan est légal.
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            u = get_unit_by_id(game_state, act_uid)
            if u is None:
                raise KeyError(f"Pile-in unit {act_uid} missing from game_state['units']")
            prov = _prov_from_action()
            models_cache = require_key(game_state, "models_cache")
            squad_models = require_key(game_state, "squad_models")
            alive = [str(m) for m in require_key(squad_models, act_uid) if str(m) in models_cache]
            origin = {m: (int(models_cache[m]["col"]), int(models_cache[m]["row"])) for m in alive}
            full_plan: List[Tuple[str, int, int]] = [
                (m, prov[m][0], prov[m][1]) if m in prov else (m, origin[m][0], origin[m][1])
                for m in alive
            ]
            targets = _fight_v11_pile_in_targets(game_state, u)
            closest = _fight_pile_in_closest_tier_ids(game_state, u, targets) if targets else []
            engaged_before = _fight_units_engaged_with(game_state, u)
            prev = _fight_pile_in_preview_plan(game_state, act_uid, full_plan, closest, engaged_before)
            if not prev["can_validate"]:
                _fight_v11_log(game_state, f"PILE IN unit {act_uid} → plan invalide {prev}")
                return True, _fight_pile_in_model_plan_state(game_state, u, prov, None)
            _fight_pile_in_commit_plan(game_state, u, full_plan)
            game_state["pile_in_done"].add(act_uid)
            _fight_v11_clear_pile_in_preview(game_state)
            _fight_v11_log(
                game_state, f"PILE IN unit {act_uid} → commit par-figurine ({len(full_plan)} figs)"
            )
            return _fight_v11_manual_state(game_state)

        if atype == "activate_unit" and uid in eligible:
            # Sélection d'une unité à piler → présenter son plan par-figurine (mode fin).
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Pile-in unit {uid} missing from game_state['units']")
            game_state["active_fight_unit"] = uid
            done = {str(x) for x in game_state.get("pile_in_done", set())}
            game_state["fight_eligible_units"] = [e for e in eligible if str(e) not in done]
            state = _fight_pile_in_model_plan_state(game_state, u)
            _fight_v11_log(
                game_state,
                f"PILE IN : unit {uid} sélectionnée (par-figurine, "
                f"{len(state['eligible_models'])} figs déplaçables)",
            )
            return True, state

        # Autre action en pile_in → ré-afficher l'état courant.
        return _fight_v11_manual_state(game_state)

    if sub == "fight":
        sel = fight_v11_advance_selection(game_state)
        if sel is not None and (uid is None or uid == sel) and atype in ("fight", "left_click"):
            u = get_unit_by_id(game_state, sel)
            if u is None:
                raise KeyError(f"Fight unit {sel} missing from game_state['units']")
            game_state["units_selected_to_fight"].add(sel)
            game_state.setdefault("units_fought", set()).add(sel)
            ftype = "normal"
            if action.get("fight_type") == "overrun" and fight_v11_is_overrun_eligible(game_state, u):
                ftype = "overrun"
                _fight_v11_auto_overrun_pile_in(game_state, u, config)
            _fight_v11_log(game_state, f"FIGHT unit {sel} sélectionnée (type={ftype}, step={game_state.get('fight_step')})")
            _fight_v11_resolve_attacks(
                game_state, u, config, preferred_target_id=(str(action["targetId"]) if "targetId" in action else None)
            )
        else:
            _fight_v11_log(game_state, f"FIGHT: action ignorée (sélecteur attend unit {sel}, reçu {uid}, action {atype!r})")
        return _fight_v11_manual_state(game_state)

    if sub == "consolidate":
        nxt = fight_v11_grouped_next(game_state, "consolidate")
        if nxt is not None and uid in nxt[1]:
            game_state["consolidation_done"].add(uid)  # move UI (3 modes) câblée au Bloc front
            _fight_v11_log(game_state, f"CONSOLIDATE unit {uid} → SKIP (UI move non câblée, V1)")
        return _fight_v11_manual_state(game_state)

    return _fight_v11_manual_state(game_state)


def execute_action(  # noqa: F811 (V11 override of V10)
    game_state: Dict[str, Any],
    unit: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Routage de la phase FIGHT V11 (override). Sous-phases pile_in → fight → consolidate.
    - PvE / gym / endless (auto autorisé) : une activation résolue par appel (_fight_v11_auto_step).
    - PvP / pvp_test (manuel) : traite l'action humaine et renvoie l'état actionnable suivant.
    """
    if game_state.get("phase") != "fight":
        fight_phase_start(game_state)
    fight_ensure_v11_state(game_state)
    if _is_fight_auto_execution_allowed(game_state):
        return _fight_v11_auto_step(game_state, config)
    return _fight_v11_manual_step(game_state, unit, action, config)

    return False