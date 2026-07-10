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
    ManualAllocCtx,
    _build_manual_allocation,
    apply_manual_shoot_declare_order,
    apply_manual_shoot_allocation,
    manual_allocation_waiting_payload,
    _target_highest_bodyguard_toughness,
    save_threshold,
    get_fighting_models,
    squad_fight_unit_activation_start,
    squad_declare_fight,
    DeclareAttackCtx,
    declare_attack_model,
    declare_attack_weapon,
    declare_attack_weapon_qty,
    weapon_qty_max,
    undeclare_attack_weapon_qty,
    weapons_for_target,
    eligible_models_for_weapon,
    toggle_attack_model_weapon,
    models_status_for_target,
    models_weapons_for_squad,
    _union_weapons,
    _enemy_squad_ids,
    _synth_model_entry,
    MovePlan,
    MovePlanEntry,
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
    # LoS : invalidation ciblée + bump émis par translate_squad_to_destination →
    # update_units_cache_position → _touch_unit_los (choke-point a′). CORRIGE LE TROU
    # fight-translate : ce chemin ne bumpait JAMAIS _unit_move_version auparavant → pair-cache
    # périmé en observation/reward RL jusqu'au 1er move du tour suivant.


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

    # Objectif (12.08 Objective Consolidation) : viser la ZONE DU TERRAIN (14.02 « within that
    # terrain area »), PAS un marqueur central. Distance = empreinte → partie la plus proche de la
    # zone (14.01). « within range si possible, sinon plus proche » → on minimise la distance
    # empreinte→zone ; un anchor dont l'empreinte recouvre la zone a une distance 0 (within range)
    # et sort donc naturellement comme meilleur. IA et PvP appliquent ainsi la même règle.
    zone_sets = _fight_v11_objective_hex_sets(game_state)
    if not zone_sets:
        return None

    start_fp_obj = compute_candidate_footprint(start_col, start_row, unit, game_state)
    zone_dists = [
        (oid, hexes, min_distance_between_sets(start_fp_obj, hexes)) for oid, hexes in zone_sets
    ]
    start_d_obj = min(d for _, _, d in zone_dists)
    if start_d_obj == 0:
        return None  # déjà within range (≥1 figurine dans une zone) → rien à gagner

    # Palier = hexes des objectifs les plus proches (ex aequo réunis), comme pour les ennemis.
    target_zone_hexes: Set[Tuple[int, int]] = set()
    for oid, hexes, d in zone_dists:
        if d == start_d_obj:
            target_zone_hexes |= hexes
    if not target_zone_hexes:
        return None

    _ensure_consolidation_bfs(start_fp_obj)
    assert visited is not None and fp_by_anchor is not None
    _obj_pf = _cons_pf
    _obj_uid = unit_id_str
    _t_obj_filt0 = time.perf_counter() if _obj_pf else None
    # Carte de distance BFS depuis la zone (bornée à start_d_obj-1 pas) — remplace le calcul
    # par-anchor de min_distance_between_sets. d=0 sur les hexes de la zone (within range).
    _OBJ_INF = 10 ** 9
    _obj_dist_map: Dict[Tuple[int, int], int] = {h: 0 for h in target_zone_hexes}
    _t_distmap0 = time.perf_counter() if _obj_pf else None
    _obj_frontier: List[Tuple[int, int]] = list(target_zone_hexes)
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
        d_tier = min((_obj_dist_map.get(h, _OBJ_INF) for h in fp), default=_OBJ_INF)
        if d_tier >= start_d_obj:
            continue
        dist_by_anchor_obj.append((anchor, int(d_tier)))
    if _obj_pf and _t_obj_filt0 is not None:
        filter_s = time.perf_counter() - _t_obj_filt0
        loop_s = max(0.0, filter_s - dist_map_build_s)
        append_perf_timing_line(
            f"FIGHT_CONSOLIDATION_OBJ_ANCHOR_FILTER unitId={_obj_uid!r} start_d_obj={start_d_obj} "
            f"visited_n={len(visited)} dist_map_build_s={dist_map_build_s:.6f} "
            f"loop_s={loop_s:.6f} filter_s={filter_s:.6f}"
        )
    if not dist_by_anchor_obj:
        return None
    # Meilleur palier : distance minimale à la zone. d=0 = within range (recouvre la zone) → priorité
    # naturelle. Plus de préférence « marqueur ».
    best_o = min(d for _, d in dist_by_anchor_obj)
    tier_o = [a for a, d in dist_by_anchor_obj if d == best_o]
    if len(tier_o) == 1 and tier_o[0] == start_pos:
        return None
    return ("objective", tier_o, visited, None)


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


def _model_can_fight_target(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
) -> bool:
    """Eligibilite per-figurine au COMBAT (regle 04.02 — Select Targets / While Fighting).

    La cible doit etre ENGAGED avec la figurine qui porte l arme : on teste si la
    figurine attaquante (empreinte synthetique a sa position) est dans la zone
    d engagement d au moins une figurine de l unite cible. Pas de LoS en melee.

    Le squad_id attaquant est fourni par le moteur (les modeles n ont pas tous le
    champ "squad_id" — on ne le devine donc pas depuis le modele).
    """
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone
    units_cache = require_key(game_state, "units_cache")
    target_entry = units_cache.get(str(target_squad_id))
    if target_entry is None:
        return False
    if not attacker_squad_id:
        return False
    ez = get_engagement_zone(game_state)
    synth = _synth_model_entry(
        game_state, str(attacker_squad_id), attacker_model,
        int(attacker_model["col"]), int(attacker_model["row"])
    )
    return unit_entries_within_engagement_zone(synth, target_entry, ez)


def _model_can_fight_target_with_weapon(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
    weapon_index: int,
) -> bool:
    """Eligibilite per-arme melee : la fig possede l arme CC `weapon_index` ET est
    engagee avec la cible. Les armes de melee n ont pas de portee : la validite se
    reduit a l engagement (cf. _model_can_fight_target)."""
    weapons = attacker_model.get("CC_WEAPONS", [])  # get allowed
    if not (0 <= int(weapon_index) < len(weapons)):
        return False
    if not isinstance(weapons[int(weapon_index)], dict):
        return False
    return _model_can_fight_target(game_state, attacker_model, attacker_squad_id, target_squad_id)


# Contexte de declaration COMBAT : engagement (pas de LoS/portee). Jumeau de
# SHOOT_DECLARE_CTX cote tir. Reutilise le moteur generique declare_attack_*.
FIGHT_DECLARE_CTX = DeclareAttackCtx(
    intents_key="pending_squad_fight_intents",
    selected_weapon_attr="selectedCcWeaponIndex",
    weapons_key="CC_WEAPONS",
    phase_label="fight",
    can_target=_model_can_fight_target,
    can_target_with_weapon=_model_can_fight_target_with_weapon,
)


def squad_declare_fight_model(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d UNE figurine au COMBAT (flux PvP humain).

    Wrapper fin de declare_attack_model via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_model(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, attacker_model_id, target_squad_id
    )


def squad_declare_fight_weapon(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    weapon_index: int,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Assigne l arme CC `weapon_index` (niveau escouade) a la cible, au COMBAT.

    Wrapper fin de declare_attack_weapon via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_weapon(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_index, target_squad_id
    )


# ---------------------------------------------------------------------------
# Wrappers COMBAT cible-d abord par arme/quantite/figurine.
# Jumeaux exacts des squad_shoot_* (shared_utils.py) via FIGHT_DECLARE_CTX.
# Aucune logique nouvelle : engagement au lieu de portee/LoS, porte par le CTX.
# ---------------------------------------------------------------------------

def squad_declare_fight_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str,
    weapon_code: str, count: int, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Assigne `count` attaques de l arme CC `weapon_code` (identite) a la cible.

    `only_model_id` (optionnel) : attribution restreinte a CETTE figurine (menu par-fig).
    Wrapper fin de declare_attack_weapon_qty via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_weapon_qty(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, count, target_squad_id,
        only_model_id,
    )


def squad_fight_weapon_qty_max(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Borne du champ count au COMBAT — figs pouvant combattre `weapon_code` sur la cible."""
    return weapon_qty_max(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def squad_undeclare_fight_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Retire la ligne (weapon_code, cible) au COMBAT — bouton "-"."""
    return undeclare_attack_weapon_qty(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def squad_fight_weapons_for_target(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Menu cible-d abord au COMBAT — armes pouvant viser la cible avec (m, x). Cf. weapons_for_target."""
    return weapons_for_target(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, target_squad_id, only_model_id)


def squad_fight_eligible_models(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voile vert au COMBAT — figs pouvant combattre `weapon_code` sur la cible (+ assigned)."""
    return eligible_models_for_weapon(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id)


def squad_fight_toggle_model_weapon(
    game_state: Dict[str, Any], attacker_squad_id: str, model_id: str, weapon_code: str, target_squad_id: str
) -> str:
    """Clic sur fig verte au COMBAT — toggle l attribution de cette fig pour (code, cible)."""
    return toggle_attack_model_weapon(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, model_id, weapon_code, target_squad_id)


def squad_fight_models_status(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voiles vert/gris au COMBAT — état de chaque fig vis-à-vis de la cible (+ ses armes)."""
    return models_status_for_target(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, target_squad_id)


def squad_fight_models_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Armes CC par figurine au COMBAT (indépendant de la cible) — encart jaune au clic-fig."""
    return models_weapons_for_squad(game_state, FIGHT_DECLARE_CTX, attacker_squad_id)


def squad_union_cc_weapons(
    game_state: Dict[str, Any], squad_id: str
) -> List[Dict[str, Any]]:
    """Union des armes CC par-figurine (source du menu combat). Cf. _union_weapons."""
    return _union_weapons(game_state, "CC_WEAPONS", squad_id)


def squad_fight_menu_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Profils CC de l escouade pour le menu combat, avec `can_use` correct (par-figurine).

    usable = AU MOINS une figurine portant le profil est engagee avec AU MOINS une unite
    ennemie (calcule par-fig via _model_can_fight_target_with_weapon). Pas de portee/LoS ni
    d exclusion Pistol : la melee n a pas la restriction 10.06 (jumeau simplifie de
    squad_shoot_menu_weapons)."""
    from .shared_utils import init_pending_intents, require_key as _require_key
    models_cache = _require_key(game_state, "models_cache")
    squad_models = _require_key(game_state, "squad_models")
    init_pending_intents(game_state)

    mids = squad_models.get(attacker_squad_id, [])  # get allowed
    player = int(models_cache[mids[0]]["player"]) if mids and mids[0] in models_cache else None
    enemy_sids = _enemy_squad_ids(game_state, player) if player is not None else []

    result: List[Dict[str, Any]] = []
    for idx, w in enumerate(_union_weapons(game_state, "CC_WEAPONS", attacker_squad_id)):
        code = w["code"]
        usable = False
        for mid in mids:
            m = models_cache.get(mid)
            if m is None:
                continue
            weapons = m.get("CC_WEAPONS", [])  # get allowed
            local_idx = next(
                (i for i, ww in enumerate(weapons) if isinstance(ww, dict) and ww.get("code") == code),
                None,
            )
            if local_idx is None:
                continue
            if any(
                _model_can_fight_target_with_weapon(game_state, m, attacker_squad_id, sid, local_idx)
                for sid in enemy_sids
            ):
                usable = True
                break
        result.append({"index": idx, "weapon": w, "can_use": usable, "reason": None})
    return result


def _fight_ensure_activation_started(game_state: Dict[str, Any], squad_id: str) -> None:
    """Demarre l activation fight de l escouade si pas deja en cours (idempotent).

    Initialise pending_squad_fight_intents[squad_id] = [] pour accueillir les
    declarations manuelles. Ne reinitialise pas si des declarations existent deja
    (re-activation : on conserve l etat declare)."""
    from .shared_utils import init_pending_intents
    init_pending_intents(game_state)
    if squad_id not in game_state["pending_squad_fight_intents"]:
        squad_fight_unit_activation_start(game_state, squad_id)


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
    # Phase 2 (repli) : sinon, tout le pool dur (plus proche + engagé + engagements conservés).
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


def _fight_v11_register_selection(game_state: Dict[str, Any], uid: str) -> None:
    """
    Enregistre une unité « selected to fight » (12.04) et passe la main à l'adversaire
    (alternance par unité : « players alternate selecting one friendly unit »). Si l'autre
    joueur n'a plus d'unité éligible, ``fight_v11_advance_selection`` rebascule
    automatiquement vers le sélecteur courant. À appeler au moment de la sélection
    EFFECTIVE (pas dans advance_selection, qui doit rester idempotent pour le peek/PvP).
    """
    uid = str(uid)
    game_state["units_selected_to_fight"].add(uid)
    game_state.setdefault("units_fought", set()).add(uid)
    selector = game_state.get("fight_selector")
    if selector in (1, 2):
        game_state["fight_selector"] = 3 - selector


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
    Résout les attaques de mêlée d'une unité « selected to fight » via le moteur
    d'allocation par-figurine (groupes 05.03/05.04, T bodyguard 19.02, save par figurine
    allouée). Convergence §9.4b-2 : remplace l'ancien résolveur pool
    (``_execute_fight_attack_sequence``, cible = pool de PV homogène).

    Sélection de cible auto (ou ``preferred_target_id``), puis déclaration per-figurine
    (``squad_declare_fight`` : arme CC auto par figurine — 04.01) et allocation headless
    (défenseur non-humain garanti en mode auto → ``auto_decider``). Retourne la liste des
    ``attack_result`` (1 par blessure infligée), adaptée depuis le summary du moteur
    groupes (``target_died``/``damage``/ids consommés par le reward_calculator et
    l'inférence ``unitId`` de w40k_core). Liste vide = fight « à vide ».
    """
    unit_id = str(require_key(unit, "id"))
    if not (unit.get("CC_WEAPONS") or []):
        return []

    targets = _fight_build_valid_target_pool(game_state, unit)
    if not targets:
        return []
    tid = preferred_target_id if (preferred_target_id in targets) else _ai_select_fight_target(
        game_state, unit_id, targets
    )
    if get_unit_by_id(game_state, tid) is None:
        return []

    # Déclaration per-figurine + allocation via le moteur groupes (jumeau du chemin
    # training w40k_core). Le hook FIGHT_CTX.on_unit_destroyed retire la cible morte des
    # pools de combat (équivalent de l'ancien _remove_dead_unit_from_fight_pools).
    squad_fight_unit_activation_start(game_state, unit_id)
    squad_declare_fight(game_state, unit_id, tid)
    alloc = build_manual_fight_allocation(game_state, unit_id)
    if not alloc.get("done"):
        raise RuntimeError(
            f"_fight_v11_resolve_attacks: allocation combat non terminée en auto pour "
            f"unité {unit_id} (défenseur non-IA ?) — action={alloc.get('action')}"
        )
    summary = alloc["shoot_result"]
    return [
        {
            "attackerId": unit_id,
            "shooterId": unit_id,
            "targetId": str(ev["target_squad_id"]),
            "target_died": bool(ev["destroyed"]),
            "damage": int(ev["damage"]),
        }
        for ev in require_key(summary, "events")
    ]


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
            _fight_v11_register_selection(game_state, uid)
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


def _fight_fig_effective_level(entry: Dict[str, Any], model_id: str) -> int:
    """Niveau EFFECTIF (étage) d'une figurine d'une unité, lu dans le cache unité.

    ``level_by_model`` (source par-figurine, §2.5) prime ; repli sur le niveau d'unité. Sert au
    filtrage des collisions par étage en pile-in/consolidation (superposition inter-étage, §13.06).
    """
    lbm = entry.get("level_by_model")
    if lbm and model_id in lbm:
        return int(lbm[model_id])
    return int(entry.get("level", 0))  # get allowed (champ optionnel : level absent = sol)


def _fight_model_climb_reachable_floor_cells(*args: Any, **kwargs: Any) -> List[Tuple[int, int]]:
    """Wrapper lazy vers le reachable d'étage de la phase move (source unique du coût vertical).

    Import différé pour éviter tout cycle au chargement du module (movement_handlers ↔ fight_handlers).
    """
    from engine.phase_handlers.movement_handlers import _model_climb_reachable_floor_cells
    return _model_climb_reachable_floor_cells(*args, **kwargs)


def _fight_pile_in_build_model_pool(
    game_state: Dict[str, Any],
    model_id: str,
    closest_tier_ids: List[str],
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    view_level: int = 0,
) -> Dict[str, List[List[int]]]:
    """Pool de destinations PAR-FIGURINE pour le pile-in (12.03, move par-figurine).

    BFS d'UNE figurine du squad dans le budget fixe de 3" (× ``inches_to_subhex``), sans
    traverser murs ni figs (ennemies, alliées, coéquipières). ``provisional_plan``
    ({model_id: (col, row[, level])}) remplace les positions des coéquipières déjà posées dans le
    plan UI (recompute temps réel). ``closest_tier_ids`` = unité(s) ennemie(s) la/les plus proche(s)
    de l'ESCOUADE (palier WHILE commun à toutes les figs, cf. ``pile_in_move_destinations_12_03``).

    ``view_level`` (étages, §13.06) : niveau de VUE UI. 0 = plan sol (comportement historique
    inchangé). >= 1 = destinations sur le plancher de ce niveau, atteignables avec le coût vertical
    (source unique move : ``reachable_multilevel_field`` via ``_model_climb_reachable_floor_cells``),
    seedé au niveau EFFECTIF courant du mover → une fig déjà en hauteur reste sur son étage.

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
        _charge_model_socle,
    )
    from engine.hex_utils import footprints_overlap, Socle
    from engine.terrain_utils import resolve_model_floor_level

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
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (champ optionnel : board sans terrain)
    _orient = int(unit.get("orientation", 0))  # get allowed (champ optionnel : orientation absente = 0)
    _view_level = int(view_level or 0)

    closest = {str(t) for t in closest_tier_ids}
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    from engine.terrain_utils import low_clearance_ground_hexes
    from .shared_utils import build_enemy_occupied_positions_set
    # Obstacles au SOL filtrés par NIVEAU (miroir move) : seuls les ennemis au niveau 0 bloquent le
    # sol — un ennemi en hauteur ne gêne pas (superposition inter-étage §13.06). ``_low_clear`` =
    # clairance verticale (§13.06/§2.11 : une fig trop haute ne peut finir/passer sous un plancher bas).
    _enemy_ground = build_enemy_occupied_positions_set(game_state, current_player=player, level=0)
    _low_clear = low_clearance_ground_hexes(terrain_areas, float(require_key(unit, "MODEL_HEIGHT")))
    # Bloqueurs (ennemis + autres unités amies) → collision par TEST EUCLIDIEN officiel
    # (footprints_overlap), un socle PAR FIGURINE à sa base RÉELLE (miroir consolidation). Le test
    # par cellules (cand_fp & occupied) sous-estimait le disque et rejetait des socles tangents.
    # Chaque socle est étiqueté de son niveau EFFECTIF : une fig d'un autre étage ne gêne pas
    # (superposition inter-étage, §13.06, miroir move par-figurine).
    blocker_socles: List[Tuple[int, Any]] = []
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            if str(eid) in closest:
                target_entries.append(entry)
                target_fps.append(cells)
        if str(eid) == squad_id:
            continue  # coéquipières traitées à part (positions provisoires)
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for _bmid, (mc, mr) in by_model.items():
                _bm_entry = models_cache.get(str(_bmid))
                if _bm_entry is None:
                    continue
                # Empreinte COMPLÈTE par figurine (même convention que le mover/sœurs via
                # _charge_model_socle) : sans ça, un blocker à base non-ronde n'occupait que son
                # hex central (fp={(mc,mr)}) → superposition partielle permise (méthode empreinte).
                blocker_socles.append((
                    _fight_fig_effective_level(entry, str(_bmid)),
                    _charge_model_socle(game_state, _bm_entry, int(mc), int(mr)),
                ))
        else:
            blocker_socles.append((int(entry.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]), fp=cells)))
    if not target_entries:
        return empty

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)

    # Coéquipières : collision euclidienne, un socle à la base PROPRE de chaque fig
    # (_charge_model_socle) — un Captain terminator (base large) attaché à des terminators n'est
    # plus sous-estimé. Le plan provisoire override les figs déjà posées (col,row[,level]).
    sib_socles: List[Tuple[int, Any]] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            pc, pr = int(_pv[0]), int(_pv[1])
            _sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
            _sib_req = int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        _sib_eff = resolve_model_floor_level(
            pc, pr, sib["BASE_SHAPE"], sib["BASE_SIZE"], _orient, _sib_req, terrain_areas
        )
        sib_socles.append((_sib_eff, _charge_model_socle(game_state, sib, int(pc), int(pr))))

    wall_set = set(wall_hexes)
    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _candidate_footprint_charge(start_col, start_row, unit, game_state, fp_offset_pair)
    start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)

    # --- Candidats (col,row) selon le niveau de VUE (§13.06) ------------------------------------
    # view_level 0 : BFS sol historique (traverse figs amies, pas murs/ennemis). view_level >= 1 :
    # cases du plancher atteignables avec le coût vertical, seedées au niveau effectif du mover
    # (source unique move : reachable_multilevel_field). Niveau EFFECTIF de destination = view_level.
    if _view_level >= 1:
        present = sorted({int(fl["level"]) for a in terrain_areas for fl in a.get("floors", [])})  # get allowed (champ optionnel : area sans étage)
        if _view_level not in present:
            return empty
        from engine.game_state import unit_can_occupy_upper_floor
        if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
            return empty  # §13.06 : ne peut pas finir en hauteur
        start_eff = resolve_model_floor_level(
            start_col, start_row, model["BASE_SHAPE"], model["BASE_SIZE"], _orient,
            int(model.get("level", 0)), terrain_areas  # get allowed (champ optionnel : level absent = sol)
        )
        _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
            game_state, exclude_unit_id=squad_id, level=0
        )
        _ground_obs.discard((start_col, start_row))
        reachable = _fight_model_climb_reachable_floor_cells(
            game_state, unit, squad_id, model, (start_col, start_row), budget, _view_level,
            _ground_obs, terrain_areas, start_level=start_eff,
        )
        dest_eff = _view_level
        skip_wall_blocker = True  # murs/occupation d'étage déjà validés par le helper multi-niveaux
    else:
        # Mover DÉJÀ en hauteur descendant vers le SOL (vue 0) : reach = champ multi-niveaux niveau 0
        # (coût de DESCENTE §13.06 facturé sur le budget). Pile-in/conso ≤ 3" ne franchit en général pas
        # un étage, mais certaines unités ont un budget plus grand → descente facturée comme le move.
        _start_eff = resolve_model_floor_level(
            start_col, start_row, model["BASE_SHAPE"], model["BASE_SIZE"], _orient,
            int(model.get("level", 0)), terrain_areas  # get allowed (champ optionnel : level absent = sol)
        )
        if _start_eff >= 1:
            from engine.game_state import unit_can_occupy_upper_floor
            if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
                return empty  # incohérent : une fig posée en hauteur est forcément montante (13.06)
            _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
                game_state, exclude_unit_id=squad_id, level=0
            )
            _ground_obs.discard((start_col, start_row))
            reachable = _fight_model_climb_reachable_floor_cells(
                game_state, unit, squad_id, model, (start_col, start_row), budget, 0,
                _ground_obs, terrain_areas, start_level=_start_eff,
            )
            dest_eff = 0
            skip_wall_blocker = True
        else:
            # 03.01 : traverse figs amies, PAS ennemies ni murs (chemin = cellules). Départ sol : inchangé.
            path_blocked = wall_set | _enemy_ground | _low_clear
            visited: Set[Tuple[int, int]] = {(start_col, start_row)}
            reachable = []
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
            dest_eff = 0
            skip_wall_blocker = False

    # Bloqueurs/coéquipières au niveau EFFECTIF de destination uniquement (superposition inter-étage).
    _blockers_lvl = [s for lv, s in blocker_socles if lv == dest_eff]
    _sibs_lvl = [s for lv, s in sib_socles if lv == dest_eff]

    closer: List[List[int]] = []
    engaged: List[List[int]] = []
    for cc, rr in reachable:
        cand_fp = _candidate_footprint_charge(cc, rr, unit, game_state, fp_offset_pair)
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if not skip_wall_blocker and (cand_fp & wall_set):
            continue  # 03 « Ending a move » : mur discret (déjà exclu sur étage)
        cand_socle = _charge_model_socle(game_state, model, int(cc), int(rr))
        if any(footprints_overlap(cand_socle, b) for b in _blockers_lvl):
            continue
        if any(footprints_overlap(cand_socle, b) for b in _sibs_lvl):
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
    plan: MovePlan,
    closest_tier_ids: List[str],
    engaged_before_ids: List[str],
) -> Dict[str, Any]:
    """Dry-run d'un plan pile-in par-figurine (12.03 WHILE/AFTER + cohésion 03.03). Lecture pure.

    ``plan`` couvre TOUTES les figs vivantes, entrées ``(mid, col, row[, level])`` (le 4ᵉ élément =
    niveau d'étage de destination ; absent → niveau courant de la fig). Légalité par-fig =
    appartenance au pool ``closer`` calculé AU NIVEAU planifié de la fig (ou figurine laissée à sa
    position d'origine). On ajoute la cohésion d'unité et les contraintes AFTER au niveau unité :
    l'escouade finit engagée et chaque engagement de départ est conservé.

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

    def _plan_level(entry: MovePlanEntry) -> int:
        if len(entry) >= 4 and entry[3] is not None:
            return int(entry[3])
        m = models_cache.get(str(entry[0]))
        return int(m.get("level", 0)) if m else 0  # get allowed (champ optionnel : level absent = sol)

    norm = [(str(e[0]), int(e[1]), int(e[2]), _plan_level(e)) for e in plan]
    n = len(norm)
    if n == 0:
        return empty

    # 1) Légalité par-fig : dans son pool ``closer`` au NIVEAU planifié (autres figs = positions
    # provisoires (col,row,level)) ou immobile.
    pos_by_model = {mid: (c, r, lv) for mid, c, r, lv in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r, lv in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        m = models_cache.get(mid)
        orig = (int(m["col"]), int(m["row"])) if m else None
        if orig is not None and (c, r) == orig:
            per_model[mid] = True
            continue
        pool = _fight_pile_in_build_model_pool(
            game_state, mid, closest_tier_ids, provisional_plan=prov, view_level=lv
        )["closer"]
        per_model[mid] = [c, r] in pool

    # 2) Cohésion 03.03 (empreinte-à-empreinte, mêmes 2 puces que le move).
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    fps = [_candidate_footprint_charge(c, r, unit, game_state, fp_pair) for _, c, r, _ in norm]
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
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    selected_model: Optional[str] = None,
    view_level: int = 0,
) -> Dict[str, Any]:
    """État du plan pile-in par-figurine exposé au front (miroir simplifié de ``charge_model_plan_state``).

    Une seule « phase » (pas de within_1/engaged/closer) : chaque fig peut se déplacer ≤3" en finissant
    plus proche du palier ennemi le plus proche. ``provisional_plan`` = figs déjà posées (col,row[,level]) ;
    les autres restent à leur position/niveau d'origine. ``selected_model`` non-None → calcule SON pool +
    empreinte lissée. ``view_level`` (étages, §13.06) = niveau de VUE UI ; le pool proposé et le niveau de
    destination des figs posées suivent ce niveau (miroir move par-figurine).
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
    _vl = int(view_level or 0)
    prov: Dict[str, Tuple[int, int, int]] = {
        str(m): (int(v[0]), int(v[1]), int(v[2]) if len(v) >= 3 and v[2] is not None else _vl)
        for m, v in (provisional_plan or {}).items()
    }
    origin = {
        m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]), int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
        for m in alive
    }

    targets = _fight_v11_pile_in_targets(game_state, unit)
    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, targets) if targets else []

    unplaced = [m for m in alive if m not in prov]
    eligible: List[str] = []
    for m in unplaced:
        if _fight_pile_in_build_model_pool(
            game_state, m, closest_tier, provisional_plan=prov, view_level=_vl
        )["closer"]:
            eligible.append(m)

    pool: List[List[int]] = []
    mask_loops: List[List[List[float]]] = []
    if selected_model is not None and str(selected_model) in alive:
        sel = str(selected_model)
        sel_prov = {k: v for k, v in prov.items() if k != sel}
        pool = _fight_pile_in_build_model_pool(
            game_state, sel, closest_tier, provisional_plan=sel_prov, view_level=_vl
        )["closer"]
        if pool:
            fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
            fp_zone: Set[Tuple[int, int]] = set()
            for cc, rr in pool:
                fp_zone |= _candidate_footprint_charge(int(cc), int(rr), unit, game_state, fp_pair)
            loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
            if loops:
                mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    full_plan: List[Tuple[str, int, int, int]] = [
        (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
        else (m, origin[m][0], origin[m][1], origin[m][2]) for m in alive
    ]
    engaged_before = _fight_units_engaged_with(game_state, unit)
    prev = _fight_pile_in_preview_plan(game_state, squad_id, full_plan, closest_tier, engaged_before)

    # Figs (posées ou à l'origine) dont l'empreinte finit à ≤ EZ d'une cible pile-in → voile vert UI
    # (en mesure de frapper). Cibles exposées au front pour le cercle violet + hit-test du Focus.
    ez = int(get_engagement_zone(game_state))
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    target_entries = [units_cache[t] for t in targets if t in units_cache]
    engaged_models: List[str] = []
    for m, c, r, _lv in full_plan:
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
        "current_level": _vl,
        "origin_models": {m: [c, r] for m, (c, r, _l) in origin.items()},
        "provisional": {m: [c, r] for m, (c, r, _l) in prov.items()},
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
    game_state: Dict[str, Any], unit: Dict[str, Any], plan: MovePlan
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
    game_state: Dict[str, Any], squad_id: str, focus_target_id: str, mode: str = "defensive"
) -> Dict[str, Any]:
    """Auto-placement de pile-in (12.03) : positionne les figs du squad pour MAXIMISER le nombre de
    figs en mesure de frapper le focus (empreinte ≤ EZ bord-à-bord de ``focus_target_id``). Lecture pure.

    ``mode`` (départage à nombre de figs engagées ÉGAL, priorité absolue conservée) :
      - ``"defensive"`` : maximiser la distance au focus → rester à la limite EZ, le plus loin possible ;
      - ``"offensive"`` : minimiser la distance au focus → socle-à-socle où possible, sinon au plus près.

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
    # continu, méthode empreinte sinon), pas l'intersection de cellules — sinon des socles ronds
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

    # Rayon d'empreinte EN CASES par base (marge de balayage correcte ; cf. charge_autoplace_plan :
    # BASE_SIZE en mm dilatait ~13× trop loin). Les deux parités de colonne sont couvertes.
    def _base_fp_radius(rep_model: Dict[str, Any]) -> int:
        rmax = 0
        for pc, pr in ((0, 0), (1, 0)):
            for cell in _charge_model_footprint(game_state, rep_model, pc, pr):
                rmax = max(rmax, min_distance_between_sets({(pc, pr)}, {cell}))
        return int(rmax)

    fp_radius_by_base = {b: _base_fp_radius(models_cache[m[0]]) for b, m in by_base.items()}
    _max_fp_radius = max(fp_radius_by_base.values()) if fp_radius_by_base else 0

    # Champs de distance hex multi-source (sans obstacle), calculés UNE fois. Identité métrique cube
    # (hex_utils) : min_distance_between_sets(fp, S) == min(dist_field_S[cell] for cell in fp). Remplace
    # les appels par-slot min_distance_between_sets par un lookup O(1). dist_to_focus → df (objectif) et
    # near_cells (balayage borné, vs rectangle plein) ; dist_to_tier → slot_min (WHILE « plus proche »).
    def _distance_field(sources: Set[Tuple[int, int]], radius: int) -> Dict[Tuple[int, int], int]:
        field: Dict[Tuple[int, int], int] = {cell: 0 for cell in sources}
        frontier: List[Tuple[int, int]] = list(sources)
        for _lay in range(1, radius + 1):
            nf: List[Tuple[int, int]] = []
            for cc, rr in frontier:
                for nc, nr in get_hex_neighbors(cc, rr):
                    if 0 <= nc < board_cols and 0 <= nr < board_rows and (nc, nr) not in field:
                        field[(nc, nr)] = _lay
                        nf.append((nc, nr))
            frontier = nf
            if not frontier:
                break
        return field

    _max_margin = max((ez + r + 2 for r in fp_radius_by_base.values()), default=ez + 2)
    _focus_field_radius = _max_margin + _max_fp_radius + 1
    dist_to_focus = _distance_field(set(focus_fp), _focus_field_radius)
    _tier_sources: Set[Tuple[int, int]] = set()
    for _tfp in tier_fps:
        _tier_sources |= _tfp
    dist_to_tier = _distance_field(_tier_sources, board_cols + board_rows)

    # Zone d'intérêt = cellules ≤ _focus_field_radius du focus. Au-delà, un blocker ne peut chevaucher
    # aucun slot (dont l'empreinte est dans cette zone) → on filtre UNE fois pour le balayage des slots.
    # Le repli garde static_blockers complet (positions de repli potentiellement hors zone).
    _zone = set(dist_to_focus)
    near_blockers = [s for s in static_blockers if s.fp & _zone]

    # Liste GLOBALE des slots (toutes bases) : (col, row, Socle, slot_min_to_tier, dist_to_focus).
    all_slots: List[Tuple[int, int, Any, int, int]] = []
    # slots_by_base[bkey] = [index dans all_slots, ...]
    slots_by_base: Dict[Tuple[Any, Any], List[int]] = {}
    for bkey, mids in by_base.items():
        rep_id = mids[0]
        margin = ez + fp_radius_by_base[bkey] + 2
        near_cells = sorted(cell for cell, d in dist_to_focus.items() if d <= margin)
        idxs: List[int] = []
        for (c, r) in near_cells:
            soc = _socle(rep_id, c, r)
            fps = set(soc.fp)
            if any(not (0 <= x < board_cols and 0 <= y < board_rows) for x, y in fps):
                continue
            if _overlaps(soc, near_blockers):
                continue
            if not _engages_focus(c, r, fps):
                continue
            slot_min = min((dist_to_tier[cell] for cell in fps if cell in dist_to_tier), default=1 << 30)
            df_slot = min((dist_to_focus[cell] for cell in fps if cell in dist_to_focus), default=1 << 30)
            idxs.append(len(all_slots))
            all_slots.append((c, r, soc, slot_min, df_slot))
        slots_by_base[bkey] = idxs

    # --- Atteignabilité par fig (BFS centre-à-centre ≤ budget, amies traversables). ---
    starts = {mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in movable}
    start_fp = {mid: _model_fp(mid, *starts[mid]) for mid in movable}
    start_min = {mid: _fp_min_to_tier(start_fp[mid]) for mid in movable}

    _reach_cache: Dict[str, Dict[Tuple[int, int], int]] = {}

    def _reachable(mid: str) -> Dict[Tuple[int, int], int]:
        cached = _reach_cache.get(mid)
        if cached is not None:
            return cached  # même fig réutilisée au repli → pas de 2e BFS
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
        _reach_cache[mid] = dist
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
            sc, sr, soc, slot_min, _df = all_slots[si]
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
            for e_i in edges_by_slot.get(s1, []) + edges_by_slot.get(s2, []):  # get allowed
                rows.append(base_rows + k); cols.append(e_i)
        n_rows = base_rows + len(conflict_pairs)
        A = coo_matrix(([1.0] * len(rows), (rows, cols)), shape=(n_rows, n))
        lc = LinearConstraint(A, np.zeros(n_rows), np.ones(n_rows))  # type: ignore[arg-type]
        max_pd = max((e[2] for e in edges), default=0) + 1
        max_df = max((all_slots[e[1]][4] for e in edges), default=0) + 1
        # Objectif lexicographique (BIG ≫ W2 ≫ tie) : (1) maximiser le nb de figs engagées ; (2) selon
        # le mode, MIN distance au focus (offensif) ou MAX distance (défensif) ; (3) déplacement minimal.
        BIG = 1.0e6
        W2 = 1.0e3
        sign = 1.0 if mode == "offensive" else -1.0  # offensif → minimise dist ; défensif → maximise
        c = np.array(
            [-BIG + sign * W2 * (all_slots[si][4] / max_df) + pd / (max_pd * 1.0e3)
             for (_mid, si, pd) in edges],
            dtype=float,
        )
        res = milp(
            c=c, constraints=[lc], integrality=np.ones(n),
            bounds=Bounds(0, 1), options={"time_limit": 2.0},
        )
        if res.x is not None:
            for e_i, x in enumerate(res.x):
                if x > 0.5:
                    mid, si, _pd = edges[e_i]
                    sc, sr, soc, _sm, _df = all_slots[si]
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


def consolidate_autoplace_plan(
    game_state: Dict[str, Any], squad_id: str, mode: str = "defensive"
) -> Dict[str, Any]:
    """Auto-placement de consolidation (Focus off./déf., 12.08) — miroir du Focus pile-in/charge.

    Route vers le moteur ILP existant dont l'AFTER correspond exactement au mode V11 courant
    (déterminé par ``_fight_v11_consolidation_targets``) :
      - ``ongoing``  : AFTER « chaque fig conserve SES engagements de départ » (par-figurine) +
        figs base-contact figées → ``pile_in_autoplace_plan`` (focus = ennemi du palier le plus
        proche parmi les unités engagées) ;
      - ``engaging`` : AFTER « unité engagée avec TOUTES les cibles sélectionnées » (par-unité) →
        ``charge_autoplace_plan`` (couverture dure), budget 3", engagement d'ennemis non sélectionnés
        autorisé (New Foes To Face), FLY ignoré (mouvement normal) ;
      - ``objective`` : cible = zone (pas d'engagement) → non couvert par le Focus, erreur explicite.

    ``mode`` est l'intention du bouton : "offensive" (au plus près) | "defensive" (au plus loin).
    Lecture pure (renvoie {"plan": [[model_id, col, row], ...]}).
    """
    if mode not in ("offensive", "defensive"):
        raise ValueError(f"consolidate_autoplace_plan: mode invalide {mode!r}")
    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        return {"plan": []}

    cons_mode, tier = _fight_v11_consolidation_targets(game_state, unit)
    if cons_mode == "ongoing":
        closest = _fight_pile_in_closest_tier_ids(game_state, unit, list(tier))
        if not closest:
            raise ValueError(
                f"consolidate_autoplace_plan: ongoing sans ennemi le plus proche pour {squad_id}"
            )
        return pile_in_autoplace_plan(game_state, str(squad_id), str(closest[0]), mode=mode)
    if cons_mode == "engaging":
        if not tier:
            raise ValueError(
                f"consolidate_autoplace_plan: engaging sans cible sélectionnée pour {squad_id}"
            )
        from .charge_handlers import charge_autoplace_plan
        budget = 3 * int(require_key(game_state, "inches_to_subhex"))
        return charge_autoplace_plan(
            game_state, str(squad_id), mode,
            target_ids_override=[str(t) for t in tier],
            budget_override=budget,
            allow_nontarget_engagement=True,
            disable_fly=True,
        )
    if cons_mode == "objective":
        raise ValueError(
            f"consolidate_autoplace_plan: mode objective non supporté par le Focus "
            f"(cible = zone d'objectif, pas d'engagement) pour {squad_id}"
        )
    raise ValueError(
        f"consolidate_autoplace_plan: aucune consolidation applicable pour {squad_id}"
    )


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


# =====================================================================
# === V11 FIGHT PHASE — CONSOLIDATION par-figurine (12.08) ============
# =====================================================================
# Moteur GÉNÉRIQUE paramétré (plan §4) : une seule copie du cœur de mouvement,
# pilotée par tier_kind ∈ {enemy, zone}, lock_base_contact (Ongoing) et un AFTER
# par mode. NE TOUCHE PAS au pile-in (rebranché plus tard, factorisation A).


def _fight_v11_consolidation_engaging_candidates(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[str]:
    """Engaging (12.08) : ids des unités ennemies à ≤ consolidation_trigger_range (3") — sélectionnables."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    return _fight_v11_enemies_within_range(game_state, unit, trig)


def _fight_v11_consolidation_objective_candidates(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[Any]:
    """Objective (12.08) : ids des objectifs à ≤ consolidation_trigger_range (3") — sélectionnables."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    return _fight_v11_objectives_within_range(game_state, unit, trig)


def _fight_v11_consolidation_objective_zone(
    game_state: Dict[str, Any], objective_id: Any
) -> Set[Tuple[int, int]]:
    """Set d'hexes de la zone de contrôle d'un objectif (par id). ``raise`` si introuvable."""
    for oid, hexes in _fight_v11_objective_hex_sets(game_state):
        if oid == objective_id:
            return hexes
    raise ValueError(f"_fight_v11_consolidation_objective_zone: objectif {objective_id!r} sans hexes")


def _fight_v11_consolidation_targets(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[Optional[str], Any]:
    """``(mode, tier)`` du move de consolidation (12.08), cascade + sélection joueur.

    - ``ongoing``   → tier = ids de **toutes** les unités ennemies engagées (imposé) ;
    - ``engaging``  → tier = ids ennemis **sélectionnés par le joueur** (état
      ``consolidation_engaging_selection``), filtrés sur les candidats à ≤3". Tier vide =
      sélection en attente (move encore impossible) ;
    - ``objective`` → tier = **set d'hexes** de la zone de l'objectif sélectionné
      (``consolidation_objective_selection``), auto si 1 seul candidat. ``None`` = sélection
      en attente ;
    - ``(None, None)`` → aucune branche applicable (pas de consolidation possible).

    ``tier_kind`` est implicite : ``zone`` pour objective, ``enemy`` sinon.
    """
    mode = fight_v11_consolidation_mode(game_state, unit)
    if mode is None:
        return (None, None)
    uid = str(require_key(unit, "id"))
    if mode == "ongoing":
        tier = _fight_units_engaged_with(game_state, unit)
        if not tier:
            raise ValueError(
                f"_fight_v11_consolidation_targets: mode ongoing mais unité {uid} non engagée"
            )
        return ("ongoing", tier)
    if mode == "engaging":
        candidates = set(_fight_v11_consolidation_engaging_candidates(game_state, unit))
        sel = game_state.get("consolidation_engaging_selection", {}).get(uid, [])  # fallback allowed — aucune sélection engaging pour cette unité = tier vide (métier)
        tier = [str(e) for e in sel if str(e) in candidates]
        return ("engaging", tier)
    if mode == "objective":
        cands = _fight_v11_consolidation_objective_candidates(game_state, unit)
        if len(cands) == 1:
            chosen: Any = cands[0]
        else:
            chosen = game_state.get("consolidation_objective_selection", {}).get(uid)  # fallback allowed — aucune sélection objective pour cette unité = None (métier)
            if chosen not in cands:
                chosen = None
        if chosen is None:
            return ("objective", None)
        return ("objective", _fight_v11_consolidation_objective_zone(game_state, chosen))
    raise ValueError(f"_fight_v11_consolidation_targets: mode inattendu {mode!r}")


def _fight_consolidation_build_model_pool(
    game_state: Dict[str, Any],
    model_id: str,
    *,
    tier_kind: str,
    tier: Any,
    lock_base_contact: bool,
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    view_level: int = 0,
) -> Dict[str, List[List[int]]]:
    """Pool de destinations PAR-FIGURINE pour la CONSOLIDATION (12.08), moteur générique.

    Paramètres :
      - ``tier_kind`` ∈ {"enemy","zone"} : nature du palier WHILE ;
      - ``tier`` : pour "enemy" = ids du **palier ennemi le plus proche** (closest tier) ;
        pour "zone" = set d'hexes de la zone de l'objectif sélectionné ;
      - ``lock_base_contact`` : Ongoing — une figurine en base-contact ennemi NE BOUGE PAS (12.08) ;
      - ``view_level`` (étages, §13.06) : niveau de VUE UI. 0 = plan sol (historique). >= 1 = plancher
        de ce niveau, atteignable avec le coût vertical (source unique move), seedé au niveau EFFECTIF
        courant du mover → une fig déjà en hauteur reste sur son étage (miroir pile-in / move).

    WHILE MOVING (12.08) :
      - enemy (Ongoing/Engaging) : empreinte finale STRICTEMENT plus proche du palier le plus
        proche qu'au départ (engaged si possible) — même cœur que le pile-in ;
      - zone (Objective) : empreinte WITHIN RANGE de la zone (empreinte ∩ zone) si possible,
        SINON strictement plus proche de la zone.

    Retour ``{"closer":[...], "engaged":[...]}`` (engaged ⊆ closer ; enemy : ≤ EZ d'un ennemi du
    palier ; zone : empreinte ∩ zone). Lecture pure (réutilise les primitives charge/empreinte).
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _charge_prepare_footprint_offsets,
        _candidate_footprint_charge,
        _charge_synthetic_charger_cache_entry,
        _charge_model_socle,
    )
    from engine.hex_utils import footprints_overlap, Socle
    from engine.terrain_utils import resolve_model_floor_level

    if tier_kind not in ("enemy", "zone"):
        raise ValueError(f"_fight_consolidation_build_model_pool: tier_kind invalide {tier_kind!r}")
    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(f"_fight_consolidation_build_model_pool: model {model_id} not in models_cache")
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    empty: Dict[str, List[List[int]]] = {"closer": [], "engaged": []}
    if not unit:
        return empty

    # Ongoing : verrou base-contact (12.08 WHILE) — figurine collée à un ennemi = figée.
    if lock_base_contact and _fight_model_in_base_contact(game_state, model):
        return empty

    ez = int(get_engagement_zone(game_state))
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    units_cache = require_key(game_state, "units_cache")
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (champ optionnel : board sans terrain)
    _orient = int(unit.get("orientation", 0))  # get allowed (champ optionnel : orientation absente = 0)
    _view_level = int(view_level or 0)

    closest = {str(t) for t in tier} if tier_kind == "enemy" else set()
    zone_set: Set[Tuple[int, int]] = set(tier) if tier_kind == "zone" else set()
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    from engine.terrain_utils import low_clearance_ground_hexes
    from .shared_utils import build_enemy_occupied_positions_set
    # Obstacles au SOL filtrés par NIVEAU (miroir move) : seuls les ennemis au niveau 0 bloquent le
    # sol — un ennemi en hauteur ne gêne pas (superposition inter-étage §13.06). ``_low_clear`` =
    # clairance verticale (§13.06/§2.11 : une fig trop haute ne peut finir/passer sous un plancher bas).
    _enemy_ground = build_enemy_occupied_positions_set(game_state, current_player=player, level=0)
    _low_clear = low_clearance_ground_hexes(terrain_areas, float(require_key(unit, "MODEL_HEIGHT")))
    # Bloqueurs (ennemis + autres unités amies) → collision par TEST EUCLIDIEN officiel
    # (footprints_overlap), comme les autoplaces. Chaque socle étiqueté de son niveau EFFECTIF :
    # une fig d'un autre étage ne gêne pas (superposition inter-étage, §13.06, miroir pile-in).
    blocker_socles: List[Tuple[int, Any]] = []
    for eid, entry in units_cache.items():
        occ = entry.get("occupied_hexes")
        cells = set(occ) if occ else {(int(entry["col"]), int(entry["row"]))}
        if int(entry["player"]) != player:
            if tier_kind == "enemy" and str(eid) in closest:
                target_entries.append(entry)
                target_fps.append(cells)
        if str(eid) == squad_id:
            continue  # coéquipières traitées à part (positions provisoires)
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for _bmid, (mc, mr) in by_model.items():
                _bm_entry = models_cache.get(str(_bmid))
                if _bm_entry is None:
                    continue
                # Empreinte COMPLÈTE par figurine (même convention que le mover/sœurs via
                # _charge_model_socle) : sans ça, un blocker à base non-ronde n'occupait que son
                # hex central (fp={(mc,mr)}) → superposition partielle permise (méthode empreinte).
                blocker_socles.append((
                    _fight_fig_effective_level(entry, str(_bmid)),
                    _charge_model_socle(game_state, _bm_entry, int(mc), int(mr)),
                ))
        else:
            blocker_socles.append((int(entry.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]), fp=cells)))
    if tier_kind == "enemy" and not target_entries:
        return empty
    if tier_kind == "zone" and not zone_set:
        return empty

    fp_offset_pair = _charge_prepare_footprint_offsets(unit, game_state)

    # Coéquipières (collision euclidienne) : le plan provisoire override les figs déjà posées (col,row[,level]).
    sib_socles: List[Tuple[int, Any]] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            pc, pr = int(_pv[0]), int(_pv[1])
            _sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
            _sib_req = int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        _sib_eff = resolve_model_floor_level(
            pc, pr, sib["BASE_SHAPE"], sib["BASE_SIZE"], _orient, _sib_req, terrain_areas
        )
        sib_socles.append((_sib_eff, _charge_model_socle(game_state, sib, int(pc), int(pr))))

    wall_set = set(wall_hexes)
    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _candidate_footprint_charge(start_col, start_row, unit, game_state, fp_offset_pair)
    if tier_kind == "enemy":
        start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)
    else:
        start_min = min_distance_between_sets(start_fp, zone_set)

    # --- Candidats (col,row) selon le niveau de VUE (§13.06), miroir pile-in ---------------------
    if _view_level >= 1:
        present = sorted({int(fl["level"]) for a in terrain_areas for fl in a.get("floors", [])})  # get allowed (champ optionnel : area sans étage)
        if _view_level not in present:
            return empty
        from engine.game_state import unit_can_occupy_upper_floor
        if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
            return empty
        start_eff = resolve_model_floor_level(
            start_col, start_row, model["BASE_SHAPE"], model["BASE_SIZE"], _orient,
            int(model.get("level", 0)), terrain_areas  # get allowed (champ optionnel : level absent = sol)
        )
        _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
            game_state, exclude_unit_id=squad_id, level=0
        )
        _ground_obs.discard((start_col, start_row))
        reachable = _fight_model_climb_reachable_floor_cells(
            game_state, unit, squad_id, model, (start_col, start_row), budget, _view_level,
            _ground_obs, terrain_areas, start_level=start_eff,
        )
        dest_eff = _view_level
        skip_wall_blocker = True
    else:
        # Mover DÉJÀ en hauteur descendant vers le SOL (vue 0) : reach = champ multi-niveaux niveau 0
        # (coût de DESCENTE §13.06), miroir pile-in. Budget conso > 3" possible → descente facturée.
        _start_eff = resolve_model_floor_level(
            start_col, start_row, model["BASE_SHAPE"], model["BASE_SIZE"], _orient,
            int(model.get("level", 0)), terrain_areas  # get allowed (champ optionnel : level absent = sol)
        )
        if _start_eff >= 1:
            from engine.game_state import unit_can_occupy_upper_floor
            if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
                return empty  # incohérent : une fig posée en hauteur est forcément montante (13.06)
            _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
                game_state, exclude_unit_id=squad_id, level=0
            )
            _ground_obs.discard((start_col, start_row))
            reachable = _fight_model_climb_reachable_floor_cells(
                game_state, unit, squad_id, model, (start_col, start_row), budget, 0,
                _ground_obs, terrain_areas, start_level=_start_eff,
            )
            dest_eff = 0
            skip_wall_blocker = True
        else:
            # 03.01 : traverse les amies, PAS les ennemies ni les murs (BFS = cellules). Départ sol : inchangé.
            path_blocked = wall_set | _enemy_ground | _low_clear
            visited: Set[Tuple[int, int]] = {(start_col, start_row)}
            reachable = []
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
            dest_eff = 0
            skip_wall_blocker = False

    _blockers_lvl = [s for lv, s in blocker_socles if lv == dest_eff]
    _sibs_lvl = [s for lv, s in sib_socles if lv == dest_eff]

    closer: List[List[int]] = []
    engaged: List[List[int]] = []
    for cc, rr in reachable:
        cand_fp = _candidate_footprint_charge(cc, rr, unit, game_state, fp_offset_pair)
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if not skip_wall_blocker and (cand_fp & wall_set):
            continue  # finir sur un mur interdit (déjà exclu sur étage)
        cand_socle = _charge_model_socle(game_state, model, int(cc), int(rr))
        if any(footprints_overlap(cand_socle, b) for b in _blockers_lvl):
            continue  # chevauchement ennemi / autre unité amie AU MÊME ÉTAGE (euclidien, tangence OK)
        if any(footprints_overlap(cand_socle, b) for b in _sibs_lvl):
            continue  # chevauchement coéquipière au même étage (idem)
        if tier_kind == "enemy":
            d_min = min(
                min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps
            )
            if d_min >= start_min:
                continue  # WHILE : strictement plus proche du palier le plus proche
            closer.append([cc, rr])
            synth = _charge_synthetic_charger_cache_entry(game_state, unit, cc, rr, cand_fp)
            if any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
                engaged.append([cc, rr])
        else:  # zone (Objective)
            if cand_fp & zone_set:
                # within range = empreinte DANS la zone du terrain (14.02)
                closer.append([cc, rr])
                engaged.append([cc, rr])
            else:
                d_min = min_distance_between_sets(cand_fp, zone_set, max_distance=start_min)
                if d_min < start_min:  # « closer if not » (pas within mais se rapproche)
                    closer.append([cc, rr])

    return {"closer": closer, "engaged": engaged}


def _fight_consolidation_preview_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    plan: MovePlan,
    *,
    mode: str,
    tier_kind: str,
    tier: Any,
    closest_tier_ids: List[str],
    engaged_before_ids: List[str],
    lock_base_contact: bool,
) -> Dict[str, Any]:
    """Dry-run d'un plan de consolidation par-figurine (12.08 WHILE/AFTER + cohésion 03.03).

    AFTER par mode :
      - ongoing   : chaque engagement de départ conservé (niveau unité, miroir pile-in) ;
      - engaging  : unité engagée avec **toutes** les unités ennemies sélectionnées (tier) ;
      - objective : unité within range de l'objectif (≥1 figurine dans la zone).

    ⚠️ ``can_validate=False`` si la cible (tous les ciblés / la zone) est inatteignable : le
    « closer if not » du WHILE ne valide pas le move (move optionnel → on ne bouge pas). Lecture pure.
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
        "engaged_with_all_selected": False,
        "within_objective_range": False,
        "can_validate": False,
    }
    if not unit:
        return empty
    models_cache = require_key(game_state, "models_cache")

    def _plan_level(entry: MovePlanEntry) -> int:
        if len(entry) >= 4 and entry[3] is not None:
            return int(entry[3])
        m = models_cache.get(str(entry[0]))
        return int(m.get("level", 0)) if m else 0  # get allowed (champ optionnel : level absent = sol)

    norm = [(str(e[0]), int(e[1]), int(e[2]), _plan_level(e)) for e in plan]
    n = len(norm)
    if n == 0:
        return empty

    # 1) Légalité par-fig : dans son pool ``closer`` au NIVEAU planifié (autres figs = positions
    # provisoires (col,row,level)) ou immobile.
    pos_by_model = {mid: (c, r, lv) for mid, c, r, lv in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r, lv in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        m = models_cache.get(mid)
        orig = (int(m["col"]), int(m["row"])) if m else None
        if orig is not None and (c, r) == orig:
            per_model[mid] = True
            continue
        pool = _fight_consolidation_build_model_pool(
            game_state, mid, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=prov, view_level=lv,
        )["closer"]
        per_model[mid] = [c, r] in pool

    # 2) Cohésion 03.03 (empreinte-à-empreinte, mêmes 2 puces que le move).
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    fps = [_candidate_footprint_charge(c, r, unit, game_state, fp_pair) for _, c, r, _ in norm]
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

    # 3) AFTER (12.08) au niveau unité, selon le mode.
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
    engaged_with_all_selected = True
    within_objective_range = False
    after_ok = False
    if mode == "ongoing":
        for eid in engaged_before_ids:
            ce = units_cache.get(str(eid))
            if ce is None:
                continue
            if not unit_entries_within_engagement_zone(synth_unit, ce, ez):
                kept_engagements = False
                break
        after_ok = kept_engagements
    elif mode == "engaging":
        selected = [str(e) for e in tier]
        engaged_with_all_selected = bool(selected)
        for eid in selected:
            ce = units_cache.get(eid)
            if ce is None or not unit_entries_within_engagement_zone(synth_unit, ce, ez):
                engaged_with_all_selected = False
                break
        after_ok = engaged_with_all_selected
    elif mode == "objective":
        zone_set: Set[Tuple[int, int]] = set(tier) if tier else set()
        within_objective_range = bool(zone_set) and bool(union_fp & zone_set)
        after_ok = within_objective_range
    else:
        raise ValueError(f"_fight_consolidation_preview_plan: mode inattendu {mode!r}")

    can_validate = bool(all(per_model.values()) and coherency_ok and after_ok)
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "unit_engaged": unit_engaged,
        "kept_engagements": kept_engagements,
        "engaged_with_all_selected": engaged_with_all_selected,
        "within_objective_range": within_objective_range,
        "can_validate": can_validate,
    }


def _fight_consolidation_model_plan_state(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    selected_model: Optional[str] = None,
    view_level: int = 0,
) -> Dict[str, Any]:
    """État du plan de consolidation par-figurine exposé au front (miroir du pile-in par-figurine).

    Détermine ``(mode, tier)`` via ``_fight_v11_consolidation_targets``. En Engaging sans sélection
    de cibles, ou en Objective sans objectif choisi (>1 candidat), renvoie un état
    ``awaiting_*_selection`` exposant les candidats cliquables (le move reste bloqué).
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
    _vl = int(view_level or 0)
    prov: Dict[str, Tuple[int, int, int]] = {
        str(m): (int(v[0]), int(v[1]), int(v[2]) if len(v) >= 3 and v[2] is not None else _vl)
        for m, v in (provisional_plan or {}).items()
    }
    origin = {
        m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]), int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
        for m in alive
    }

    mode, tier = _fight_v11_consolidation_targets(game_state, unit)
    engaging_candidates = (
        _fight_v11_consolidation_engaging_candidates(game_state, unit) if mode == "engaging" else []
    )
    objective_candidates = (
        _fight_v11_consolidation_objective_candidates(game_state, unit) if mode == "objective" else []
    )
    base = {
        "phase": "fight",
        "fight_subphase": "consolidate",
        "consolidation_model_move": True,
        "consolidation_mode": mode,
        "unitId": squad_id,
        "active_fight_unit": squad_id,
        "current_level": _vl,
        "origin_models": {m: [c, r] for m, (c, r, _l) in origin.items()},
        "provisional": {m: [c, r] for m, (c, r, _l) in prov.items()},
        "selected_model": str(selected_model) if selected_model is not None else None,
        "engaging_candidates": [str(e) for e in engaging_candidates],
        "objective_candidates": [str(o) for o in objective_candidates],
        "waiting_for_player": True,
        "action": "wait",
    }

    # Sélection préalable requise (Engaging : ≥1 cible ; Objective : 1 objectif si >1 candidat).
    if mode is None:
        return {**base, "awaiting_target_selection": False, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}
    if mode == "engaging" and not tier:
        return {**base, "awaiting_target_selection": True, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}
    if mode == "objective" and tier is None:
        return {**base, "awaiting_objective_selection": True, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}

    tier_kind = "zone" if mode == "objective" else "enemy"
    lock_base_contact = mode == "ongoing"
    if tier_kind == "enemy":
        closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, list(tier))
    else:
        closest_tier = []

    unplaced = [m for m in alive if m not in prov]
    eligible: List[str] = []
    for m in unplaced:
        if _fight_consolidation_build_model_pool(
            game_state, m, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=prov, view_level=_vl,
        )["closer"]:
            eligible.append(m)

    pool: List[List[int]] = []
    mask_loops: List[List[List[float]]] = []
    if selected_model is not None and str(selected_model) in alive:
        sel = str(selected_model)
        sel_prov = {k: v for k, v in prov.items() if k != sel}
        pool = _fight_consolidation_build_model_pool(
            game_state, sel, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=sel_prov, view_level=_vl,
        )["closer"]
        if pool:
            fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
            fp_zone: Set[Tuple[int, int]] = set()
            for cc, rr in pool:
                fp_zone |= _candidate_footprint_charge(int(cc), int(rr), unit, game_state, fp_pair)
            loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
            if loops:
                mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    full_plan: List[Tuple[str, int, int, int]] = [
        (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
        else (m, origin[m][0], origin[m][1], origin[m][2]) for m in alive
    ]
    engaged_before = _fight_units_engaged_with(game_state, unit)
    prev = _fight_consolidation_preview_plan(
        game_state, squad_id, full_plan, mode=mode, tier_kind=tier_kind, tier=tier,
        closest_tier_ids=closest_tier, engaged_before_ids=engaged_before,
        lock_base_contact=lock_base_contact,
    )

    # Voile vert UI : figs « en position » (≤ EZ d'un ennemi du palier, ou dans la zone objectif).
    ez = int(get_engagement_zone(game_state))
    fp_pair = _charge_prepare_footprint_offsets(unit, game_state)
    engaged_models: List[str] = []
    if tier_kind == "enemy":
        target_entries = [units_cache[t] for t in closest_tier if t in units_cache]
        for m, c, r, _lv in full_plan:
            fp = _candidate_footprint_charge(int(c), int(r), unit, game_state, fp_pair)
            synth = _charge_synthetic_charger_cache_entry(game_state, unit, int(c), int(r), fp)
            if any(unit_entries_within_engagement_zone(synth, te, ez) for te in target_entries):
                engaged_models.append(m)
    else:
        zone_set: Set[Tuple[int, int]] = set(tier)
        for m, c, r, _lv in full_plan:
            fp = _candidate_footprint_charge(int(c), int(r), unit, game_state, fp_pair)
            if fp & zone_set:
                engaged_models.append(m)

    return {
        **base,
        "awaiting_target_selection": False,
        "awaiting_objective_selection": False,
        "engaged_models": engaged_models,
        "consolidation_targets": [str(t) for t in closest_tier] if tier_kind == "enemy" else [],
        "eligible_models": eligible,
        "pool": pool,
        "footprint_mask_loops": mask_loops,
        "unplaced": unplaced,
        "can_validate": prev["can_validate"],
        "per_model_valid": prev["per_model"],
        "coherency_ok": prev["coherency_ok"],
        "unit_engaged": prev["unit_engaged"],
        "kept_engagements": prev["kept_engagements"],
        "engaged_with_all_selected": prev["engaged_with_all_selected"],
        "within_objective_range": prev["within_objective_range"],
    }


def _fight_consolidation_commit_plan(
    game_state: Dict[str, Any], unit: Dict[str, Any], plan: MovePlan
) -> None:
    """Pose le plan de consolidation par-figurine (``commit_move`` type ``consolidation``) + resync l'ancre."""
    from .shared_utils import commit_move, set_unit_coordinates

    commit_move(plan, game_state, "consolidation")
    entry = require_key(game_state, "units_cache").get(str(require_key(unit, "id")))
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))


def _fight_v11_clear_consolidation_preview(game_state: Dict[str, Any]) -> None:
    """Purge l'aperçu de consolidation ET les **deux** sélections (engaging + objective) — sinon
    un objectif/une cible choisi reste collé au changement d'unité active / fin de conso."""
    game_state.pop("consolidation_engaging_selection", None)
    game_state.pop("consolidation_objective_selection", None)


# --- Engaging « New Foes to Face » (12.08 AFTER, §8.C) : résolution CIBLÉE ---------------------
# Au commit engaging, les ennemis engagés avec U non encore « selected to fight » doivent combattre
# (12.08). Sélecteur = ADVERSAIRE de U, sur un pool EXPLICITE restreint à ces unités (PAS
# fight_v11_advance_selection, qui relancerait l'alternance 12.04 entière — cf. §8.C). La liste est
# GELÉE au commit ; chaque New Foe résout un NORMAL fight via le flux d'allocation manuel existant.
# Invariants : I1 (U consolide 1×, consolidation_done), I2 (New Foe combat 1×, units_selected_to_fight),
# I3 (pas de double bascule), I4 (joueur actif finit ses consos avant l'adversaire — grouped_next),
# I5 (un New Foe devient consolidable côté adverse — fight_v11_is_consolidation_eligible le ramasse).


def _fight_v11_consolidation_new_foes_remaining(game_state: Dict[str, Any]) -> List[str]:
    """New Foes (liste gelée) encore vivants ET non encore « selected to fight »."""
    pending = game_state.get("consolidation_new_foes_pending")
    if not pending:
        return []
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    out: List[str] = []
    for nf in pending:
        nf = str(nf)
        if nf in selected or not is_unit_alive(nf, game_state):
            continue
        out.append(nf)
    return out


def _fight_v11_consolidation_clear_new_foes(game_state: Dict[str, Any]) -> None:
    game_state.pop("consolidation_new_foes_pending", None)
    game_state.pop("consolidation_new_foes_selector", None)
    game_state.pop("consolidation_new_foes_for_unit", None)


def _fight_v11_consolidation_new_foes_state(game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Payload d'attente présentant les New Foes restants au sélecteur (adversaire). ``None`` quand
    la liste est épuisée (→ purge des clés et reprise de la consolidation par l'appelant)."""
    remaining = _fight_v11_consolidation_new_foes_remaining(game_state)
    if not remaining:
        _fight_v11_consolidation_clear_new_foes(game_state)
        return None
    selector = int(
        game_state.get("consolidation_new_foes_selector", 3 - int(require_key(game_state, "current_player")))
    )
    for_unit = game_state.get("consolidation_new_foes_for_unit")
    game_state["fight_eligible_units"] = list(remaining)
    active = game_state.get("active_fight_unit")
    active = str(active) if active is not None else None
    if active is not None and active in remaining:
        u = get_unit_by_id(game_state, active)
        valid = _fight_build_valid_target_pool(game_state, u) if u else []
        game_state["valid_fight_targets"] = valid
        return {
            "phase": "fight", "fight_subphase": "consolidate",
            "consolidation_new_foes": list(remaining),
            "consolidation_new_foes_for_unit": str(for_unit) if for_unit is not None else None,
            "fight_selector": selector,
            "fight_eligible_units": list(remaining),
            "active_fight_unit": active, "valid_targets": valid,
            "waiting_for_player": True, "action": "wait",
        }
    game_state["active_fight_unit"] = None
    game_state["valid_fight_targets"] = []
    return {
        "phase": "fight", "fight_subphase": "consolidate",
        "consolidation_new_foes": list(remaining),
        "consolidation_new_foes_for_unit": str(for_unit) if for_unit is not None else None,
        "fight_selector": selector,
        "fight_eligible_units": list(remaining),
        "active_fight_unit": None, "valid_targets": [],
        "waiting_for_player": True, "action": "wait",
        "unitId": "SYSTEM",
    }


def _fight_v11_consolidation_resolve_new_foes(
    game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Au commit engaging : gèle les New Foes (ennemis engagés non sélectionnés) et présente le
    premier choix au sélecteur (adversaire). ``None`` si aucun New Foe (reprise immédiate)."""
    new_foes = fight_v11_engaging_triggered_unit_ids(game_state, unit)
    if not new_foes:
        return None
    game_state["consolidation_new_foes_pending"] = [str(x) for x in new_foes]
    game_state["consolidation_new_foes_for_unit"] = str(require_key(unit, "id"))
    game_state["consolidation_new_foes_selector"] = 3 - int(require_key(game_state, "current_player"))
    game_state["active_fight_unit"] = None
    _fight_v11_log(
        game_state,
        f"CONSOLIDATE engaging : New Foes to Face = {list(new_foes)} "
        f"(sélecteur P{game_state['consolidation_new_foes_selector']}, in-place)",
    )
    return _fight_v11_consolidation_new_foes_state(game_state)


def _fight_v11_consolidation_new_foes_step(
    game_state: Dict[str, Any],
    action: Dict[str, Any],
    config: Dict[str, Any],
    remaining: List[str],
) -> Tuple[bool, Dict[str, Any]]:
    """Résout une action sur un New Foe (attaquant) — NORMAL fight via le flux manuel existant.
    Sélecteur = adversaire, pool = ``remaining`` (restreint). Miroir de la résolution du dispatch
    FIGHT, sans relance de l'alternance 12.04."""
    atype = action.get("action")
    uid = action.get("unitId")
    uid = str(uid) if uid is not None else None
    active = game_state.get("active_fight_unit")
    active = str(active) if active is not None else None

    # L'adversaire choisit l'ordre : sélection d'un New Foe à faire combattre.
    if atype == "activate_unit":
        if uid is not None and uid in remaining:
            game_state["active_fight_unit"] = uid
            _fight_v11_log(game_state, f"NEW FOE {uid} ACTIVÉ (sélecteur adverse)")
        return _fight_v11_manual_state(game_state)

    if active is None or active not in remaining:
        return _fight_v11_manual_state(game_state)
    u = get_unit_by_id(game_state, active)
    if u is None:
        raise KeyError(f"New Foe {active} missing from game_state['units']")

    # Déclarations par-arme/figurine (calque du tir), puis validation.
    if atype in ("squad_fight_assign", "squad_fight_assign_weapon"):
        _fight_ensure_activation_started(game_state, active)
        target_id = str(require_key(action, "targetId"))
        if atype == "squad_fight_assign":
            model_id = str(require_key(action, "modelId"))
            if "weaponIndex" in action:
                m = require_key(game_state, "models_cache").get(model_id)
                if m is not None:
                    m["selectedCcWeaponIndex"] = int(action["weaponIndex"])
            squad_declare_fight_model(game_state, active, model_id, target_id)
        else:
            squad_declare_fight_weapon(game_state, active, int(require_key(action, "weaponIndex")), target_id)
        return _fight_v11_manual_state(game_state)

    if atype == "squad_fight_validate":
        from .shared_utils import init_pending_intents
        init_pending_intents(game_state)
        intents = game_state["pending_squad_fight_intents"].get(active, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
        if not intents:
            _fight_v11_log(game_state, f"NEW FOE validate {active} : aucune declaration -> ignore")
            return _fight_v11_manual_state(game_state)
        target_id = str(intents[0]["target_unit_id"])
        target_unit = get_unit_by_id(game_state, target_id)
        defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
        if not defender_human:
            raise RuntimeError(
                f"NEW FOE validate {active} : flux de declaration manuelle non supporte pour defenseur IA"
            )
        _fight_v11_register_selection(game_state, active)
        game_state["active_fight_unit"] = None
        alloc_result = build_manual_fight_allocation(game_state, active)
        if alloc_result.get("waiting_for_player"):
            return True, alloc_result
        return _fight_v11_manual_state(game_state)

    # Clic direct sur une cible → résolution + allocation (defenseur humain) ou auto (IA).
    if atype in ("fight", "left_click"):
        valid = _fight_build_valid_target_pool(game_state, u)
        if not valid:
            # Aucun ennemi à frapper (cas limite) : le New Foe est tout de même « selected to fight ».
            _fight_v11_register_selection(game_state, active)
            game_state["active_fight_unit"] = None
            _fight_v11_log(game_state, f"NEW FOE {active} : aucune cible valide (sélectionné sans attaque)")
            return _fight_v11_manual_state(game_state)
        _fight_v11_register_selection(game_state, active)
        pref = str(action["targetId"]) if "targetId" in action else None
        target_id = pref if (pref is not None and pref in valid) else _ai_select_fight_target(game_state, active, valid)
        target_unit = get_unit_by_id(game_state, target_id)
        defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
        game_state["active_fight_unit"] = None
        _fight_v11_log(game_state, f"NEW FOE {active} -> cible {target_id} (clic={pref}) defenseur_humain={defender_human}")
        if defender_human:
            squad_fight_unit_activation_start(game_state, active)
            squad_declare_fight(game_state, active, target_id)
            alloc_result = build_manual_fight_allocation(game_state, active)
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
        else:
            _fight_v11_resolve_attacks(game_state, u, config, preferred_target_id=target_id)
        return _fight_v11_manual_state(game_state)

    return _fight_v11_manual_state(game_state)


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
            # advance_selection synchronise fight_step/fight_selector (handoff 12.04) et
            # termine l'étape si plus personne n'est éligible. On ignore l'unité renvoyée :
            # le JOUEUR choisit librement parmi le pool du sélecteur courant (12.04), au lieu
            # de se voir imposer la première.
            if fight_v11_advance_selection(game_state) is None:
                fight_v11_enter_consolidate(game_state)
                continue
            pool = fight_v11_current_pool(game_state)
            if not pool:
                fight_v11_enter_consolidate(game_state)
                continue
            game_state["fight_eligible_units"] = list(pool)
            active = game_state.get("active_fight_unit")
            active = str(active) if active is not None else None
            if active is not None and active in pool:
                # L'unité a été choisie (activate_unit) → on présente ses cibles à frapper.
                u = get_unit_by_id(game_state, active)
                valid_targets = _fight_build_valid_target_pool(game_state, u) if u else []
                game_state["valid_fight_targets"] = valid_targets
                # Declarations offensives en cours (flux manuel par arme/figurine).
                fight_decls = [
                    {"model_id": i["model_id"], "weapon_index": i["weapon_index"],
                     "target_unit_id": i["target_unit_id"]}
                    for i in game_state.get("pending_squad_fight_intents", {}).get(active, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
                ]
                _fight_v11_log(
                    game_state,
                    f"état: FIGHT — unit {active} ACTIVE (selector=P{game_state['fight_selector']}, "
                    f"cibles={valid_targets}, declarations={len(fight_decls)})",
                )
                return True, {"phase": "fight", "fight_subphase": "fight",
                              "fight_step": game_state["fight_step"],
                              "fight_selector": game_state["fight_selector"],
                              "fight_eligible_units": list(pool),
                              "active_fight_unit": active, "valid_targets": valid_targets,
                              "declarations": fight_decls,
                              "overrun_eligible": bool(u and fight_v11_is_overrun_eligible(game_state, u)),
                              "waiting_for_player": True, "action": "wait"}
            # Aucune unité active → le joueur doit choisir (cercle vert sur le pool).
            game_state["active_fight_unit"] = None
            game_state["valid_fight_targets"] = []
            _fight_v11_log(
                game_state,
                f"état: FIGHT — choisir une unité (selector=P{game_state['fight_selector']}, "
                f"pool={list(pool)})",
            )
            return True, {"phase": "fight", "fight_subphase": "fight",
                          "fight_step": game_state["fight_step"],
                          "fight_selector": game_state["fight_selector"],
                          "fight_eligible_units": list(pool),
                          "active_fight_unit": None, "valid_targets": [],
                          "waiting_for_player": True, "action": "wait"}
        if sub == "consolidate":
            # New Foes to Face en cours (12.08 engaging AFTER) : tant qu'il en reste, on les
            # présente à l'adversaire AVANT de reprendre la consolidation (résolution immédiate, §8.C).
            if "consolidation_new_foes_pending" in game_state:
                nf_state = _fight_v11_consolidation_new_foes_state(game_state)
                if nf_state is not None:
                    return True, nf_state
            nxt = fight_v11_grouped_next(game_state, "consolidate")
            if nxt is None:
                return True, _fight_v11_phase_complete(game_state)
            # Présentation PARESSEUSE (miroir pile_in) : pool cliquable, aucune unité active.
            # Le joueur choisit l'unité à consolider (activate_unit) ou termine (end_consolidation).
            # Les sélections (engaging/objective) sont gérées au niveau de l'unité activée et ne
            # sont PAS purgées ici (sinon un refresh perdrait la sélection en cours).
            player, eligible = nxt
            done = {str(x) for x in game_state.get("consolidation_done", set())}
            pool = [str(u) for u in eligible if str(u) not in done]
            game_state["fight_eligible_units"] = pool
            game_state["active_fight_unit"] = None
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE P{player} : unités éligibles = {pool} (sélection libre)",
            )
            return True, {
                "phase": "fight", "fight_subphase": "consolidate",
                "fight_eligible_units": pool,
                "active_fight_unit": None,
                "waiting_for_player": True, "action": "wait",
                "unitId": "SYSTEM",
            }
        return True, _fight_v11_phase_complete(game_state)
    raise RuntimeError("_fight_v11_manual_state did not converge")


# ============================================================================
# COMBAT MANUEL — allocation des pertes par le defenseur (PvP), regles 05.03/05.04
# ============================================================================
# Reutilise le moteur d allocation generique (shared_utils) via FIGHT_CTX. La RESOLUTION
# des jets reste specifique au combat (_manual_roll_fight_intent : rerolls fight preserves,
# §B/§O). L application des degats est PAR-FIGURINE (update_model_hp/destroy_model) + les
# invalidations de cache fight (§D), via les hooks du ctx. Le chemin auto (PvE/gym) reste
# strictement inchange (HP-pool unite).


def _manual_roll_fight_intent(
    game_state: Dict[str, Any], intent: Dict[str, Any], targets_meta: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Jets melee d un intent (manuel) : hit -> wound (vs T majoritaire) -> save_roll BRUT,
    avec les 4 rerolls de combat (reroll_1_tohit / reroll_towound_objective / reroll_1_towound
    cote attaquant ; reroll_1_save cote cible). Ne compare PAS la save et ne tire PAS les
    degats (differes a l allocation, par figurine choisie). Meme forme de retour que le
    roller tir, consommee par _build_manual_allocation."""
    import random
    models_cache = require_key(game_state, "models_cache")
    attacker_mid = intent["model_id"]
    attacker = models_cache.get(attacker_mid)
    if attacker is None:
        return None
    target_sid = str(intent["target_unit_id"])
    if target_sid not in game_state.get("squad_models", {}):  # get allowed
        return None
    target = get_unit_by_id(game_state, target_sid)
    if target is None:
        return None
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
        return None
    weapon = weapons[weapon_index]
    if not isinstance(weapon, dict):
        return None
    n_attacks = int(intent["n_attacks_resolved"]) if "n_attacks_resolved" in intent else 0
    if n_attacks <= 0:
        return None
    ws = int(weapon["ATK"])
    strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
    ap = int(weapon.get("AP", 0))  # get allowed
    dmg_raw = require_key(weapon, "DMG")
    alive0 = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    if not alive0:
        return None
    wth = _calculate_wound_target(strength, _target_highest_bodyguard_toughness(game_state, target_sid))
    first_alive = models_cache[alive0[0]]
    display_wth = wth
    display_save_th = save_threshold(int(first_alive["ARMOR_SAVE"]), int(first_alive.get("INVUL_SAVE", 7)), ap)
    weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))  # get allowed
    # Conditions de reroll (constantes pour cet intent : abilities UNITE, pas figurine).
    # `attacker` est une figurine (models_cache) ; les UNIT_RULES sont sur l unite.
    attacker_unit = get_unit_by_id(game_state, str(attacker["squad_id"]))
    reroll_hit1 = attacker_unit is not None and _unit_has_rule(attacker_unit, "reroll_1_tohit_fight")
    reroll_wound1 = attacker_unit is not None and _unit_has_rule(attacker_unit, "reroll_1_towound")
    reroll_wound_obj = (
        attacker_unit is not None
        and _unit_has_rule(attacker_unit, "reroll_towound_target_on_objective")
        and _is_unit_on_objective(target, game_state)
    )
    reroll_save1 = _unit_has_rule(target, "reroll_1_save_fight")
    shot_records: List[Dict[str, Any]] = []
    pending_wounds: List[Dict[str, Any]] = []
    attacks = hits = wounds = 0
    for _ in range(int(n_attacks)):
        attacks += 1
        hit_roll = random.randint(1, 6)
        if hit_roll == 1 and reroll_hit1:
            hit_roll = random.randint(1, 6)
        if hit_roll < ws:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "MISS", "hitTarget": ws})
            continue
        hits += 1
        wound_roll = random.randint(1, 6)
        wound_success = wound_roll >= wth
        if not wound_success and ((wound_roll == 1 and reroll_wound1) or reroll_wound_obj):
            wound_roll = random.randint(1, 6)
            wound_success = wound_roll >= wth
        if not wound_success:
            shot_records.append({"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": ws, "strengthRoll": wound_roll, "strengthResult": "FAILED", "woundTarget": wth})
            continue
        wounds += 1
        save_roll = random.randint(1, 6)
        if save_roll == 1 and reroll_save1:
            save_roll = random.randint(1, 6)
        rec = {"attackRoll": hit_roll, "hitResult": "HIT", "hitTarget": ws, "strengthRoll": wound_roll, "strengthResult": "SUCCESS", "woundTarget": wth, "saveRoll": save_roll, "damageDealt": 0}
        shot_records.append(rec)
        pending_wounds.append({"save_roll": save_roll, "rec": rec})
    return {
        "attacker_mid": attacker_mid, "attacker": attacker, "target_sid": target_sid,
        "weapon_name": weapon_name, "bs": ws, "ap": ap, "dmg_raw": dmg_raw,
        "display_wth": display_wth, "display_save_th": display_save_th,
        "shot_records": shot_records, "pending_wounds": pending_wounds,
        "counts": {"attacks": attacks, "hits": hits, "wounds": wounds},
    }


def _fight_on_target_damaged(game_state: Dict[str, Any], target_sid: str) -> None:
    """Hook fight : invalide le kill_probability_cache de la cible a chaque blessure (§D)."""
    from engine.ai.weapon_selector import invalidate_cache_for_target
    cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
    invalidate_cache_for_target(cache, str(target_sid))


def _fight_on_unit_destroyed(game_state: Dict[str, Any], target_sid: str) -> None:
    """Hook fight : unite cible detruite -> retrait des pools de combat + invalidation cache (§D)."""
    _remove_dead_unit_from_fight_pools(game_state, str(target_sid))
    from engine.ai.weapon_selector import invalidate_cache_for_unit
    cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
    invalidate_cache_for_unit(cache, str(target_sid))


def _fight_auto_defender(game_state: Dict[str, Any], target_sid: str) -> bool:
    """Decideur auto du moteur d allocation combat (05.04) : True si le defenseur de la
    cible est controle par l IA -> le moteur tranche ordre + choix de figurine sans rendre
    la main. Aucun repli silencieux : cible introuvable = bug -> erreur explicite."""
    target = get_unit_by_id(game_state, str(target_sid))
    if target is None:
        raise KeyError(f"_fight_auto_defender: cible {target_sid!r} introuvable")
    return _is_ai_controlled_fight_unit(game_state, target)


FIGHT_CTX = ManualAllocCtx(
    alloc_key="pending_fight_allocation",
    declare_order_action="squad_fight_declare_order",
    manual_alloc_action="squad_fight_manual_alloc",
    phase_label="fight",
    log_type="combat",
    log_verb="FOUGHT",
    attacks_left_attr="ATTACK_LEFT",
    intents_key="pending_squad_fight_intents",
    decrement_by_attacks=True,
    emit_unit_death_log=True,
    on_target_damaged=_fight_on_target_damaged,
    on_unit_destroyed=_fight_on_unit_destroyed,
    auto_decider=_fight_auto_defender,
)


def build_manual_fight_allocation(game_state: Dict[str, Any], attacker_squad_id: str) -> Dict[str, Any]:
    """Allocation manuelle des pertes au COMBAT (defenseur humain). Cf. _build_manual_allocation."""
    return _build_manual_allocation(game_state, attacker_squad_id, FIGHT_CTX, _manual_roll_fight_intent)


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

    # Allocation manuelle des pertes (defenseur) en cours : seules les actions d allocation
    # passent ; toute autre action re-signale l attente (garde-fou, §J).
    if "pending_fight_allocation" in game_state:
        if atype == "squad_fight_declare_order":
            order = action.get("order")
            if order is None:
                return False, {"error": "missing_order"}
            res = apply_manual_shoot_declare_order(game_state, list(order), FIGHT_CTX)
            if res.get("waiting_for_player"):
                return True, res
            return _fight_v11_manual_state(game_state)
        if atype == "squad_fight_manual_alloc":
            chosen = action.get("modelId")
            if chosen is None:
                return False, {"error": "missing_model_id"}
            res = apply_manual_shoot_allocation(game_state, str(chosen), FIGHT_CTX)
            if res.get("waiting_for_player"):
                return True, res
            return _fight_v11_manual_state(game_state)
        if atype == "squad_fight_cancel":
            del game_state["pending_fight_allocation"]
            _fight_v11_log(game_state, "FIGHT allocation annulee par le joueur")
            return _fight_v11_manual_state(game_state)
        return True, manual_allocation_waiting_payload(game_state, FIGHT_CTX)

    # Combat cible-d abord par arme/quantite/figurine (jumeau du tir). Traite ICI, dans la
    # machine V11, et NON dans w40k_core : le garde-fou d allocation ci-dessus s applique donc
    # automatiquement (ces actions ne sont atteintes que hors allocation en cours). Lectures =
    # return immediat ; mutations = declaration puis etat manuel V11 rafraichi.
    if atype in (
        "squad_fight_menu_weapons", "squad_fight_weapons_for_target",
        "squad_fight_models_status", "squad_fight_models_weapons",
        "squad_fight_eligible_models", "squad_fight_weapon_qty_max",
        "squad_fight_assign_weapon_qty", "squad_fight_unassign_weapon_qty",
        "squad_fight_toggle_model_weapon",
    ):
        squad_id = str(require_key(action, "unitId"))
        # Idempotent : garantit pending_squad_fight_intents[squad_id] pour les lectures/menus.
        _fight_ensure_activation_started(game_state, squad_id)

        if atype == "squad_fight_menu_weapons":
            return True, {
                "action": atype, "unitId": squad_id,
                "weapons": squad_fight_menu_weapons(game_state, squad_id),
            }

        if atype == "squad_fight_weapons_for_target":
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            model_id = action.get("modelId")  # optionnel : menu par-fig (m/x scopes)
            return True, {
                "action": atype, "unitId": squad_id, "targetId": str(target_id),
                "weapons": squad_fight_weapons_for_target(
                    game_state, squad_id, str(target_id),
                    None if model_id is None else str(model_id),
                ),
            }

        if atype == "squad_fight_models_weapons":
            return True, {
                "action": atype, "unitId": squad_id,
                "models": squad_fight_models_weapons(game_state, squad_id),
            }

        if atype == "squad_fight_models_status":
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            return True, {
                "action": atype, "unitId": squad_id, "targetId": str(target_id),
                "models": squad_fight_models_status(game_state, squad_id, str(target_id)),
            }

        if atype == "squad_fight_eligible_models":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            return True, {
                "action": atype, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id),
                "models": squad_fight_eligible_models(game_state, squad_id, str(weapon_code), str(target_id)),
            }

        if atype == "squad_fight_weapon_qty_max":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : borne par-fig
            return True, {
                "action": atype, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id),
                "qty_max": squad_fight_weapon_qty_max(
                    game_state, squad_id, str(weapon_code), str(target_id),
                    None if model_id is None else str(model_id),
                ),
            }

        if atype == "squad_fight_assign_weapon_qty":
            weapon_code = action.get("weaponCode")
            count_raw = action.get("count")
            if weapon_code is None or count_raw is None:
                return False, {"error": "missing_weaponCode_or_count"}
            try:
                count = int(count_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_count_type"}
            target_id = str(require_key(action, "targetId"))
            model_id = action.get("modelId")  # optionnel : attribution par-fig
            try:
                squad_declare_fight_weapon_qty(
                    game_state, squad_id, str(weapon_code), count, target_id,
                    None if model_id is None else str(model_id),
                )
            except ValueError as e:
                return False, {"error": "cannot_fight", "reason": str(e)}
            return _fight_v11_manual_state(game_state)

        if atype == "squad_fight_unassign_weapon_qty":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : retrait par-fig
            squad_undeclare_fight_weapon_qty(
                game_state, squad_id, str(weapon_code), str(target_id),
                None if model_id is None else str(model_id),
            )
            return _fight_v11_manual_state(game_state)

        # squad_fight_toggle_model_weapon
        model_id = action.get("modelId")
        weapon_code = action.get("weaponCode")
        target_id = action.get("targetId")
        if model_id is None or weapon_code is None or target_id is None:
            return False, {"error": "missing_modelId_weaponCode_or_targetId"}
        try:
            squad_fight_toggle_model_weapon(
                game_state, squad_id, str(model_id), str(weapon_code), str(target_id)
            )
        except ValueError as e:
            return False, {"error": "cannot_fight", "reason": str(e)}
        return _fight_v11_manual_state(game_state)

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

        _view_level = int(action.get("level") or 0)

        def _prov_from_action() -> Dict[str, Tuple[int, int, int]]:
            # (col,row) ou (col,row,level) : le niveau d'étage capturé au drop de chaque fig (frontend)
            # est conservé → une fig posée sur un étage y reste (§13.06, miroir move par-figurine).
            prov: Dict[str, Tuple[int, int, int]] = {}
            for e in (action.get("plan") or []):
                lvl = int(e[3]) if len(e) >= 4 and e[3] is not None else _view_level
                prov[str(e[0])] = (int(e[1]), int(e[2]), lvl)
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
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "pile_in_autoplace":
            # Focus : auto-placement optimal (ILP) des figs pour maximiser celles frappant la cible.
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            focus = action.get("targetId")
            if focus is None:
                return False, {"error": "pile_in_autoplace requires targetId", "action": action}
            mode = str(action.get("mode", "defensive"))
            out = pile_in_autoplace_plan(game_state, act_uid, str(focus), mode=mode)
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
            origin = {
                m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]),
                    int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
                for m in alive
            }
            full_plan: List[Tuple[str, int, int, int]] = [
                (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
                else (m, origin[m][0], origin[m][1], origin[m][2])
                for m in alive
            ]
            targets = _fight_v11_pile_in_targets(game_state, u)
            closest = _fight_pile_in_closest_tier_ids(game_state, u, targets) if targets else []
            engaged_before = _fight_units_engaged_with(game_state, u)
            prev = _fight_pile_in_preview_plan(game_state, act_uid, full_plan, closest, engaged_before)
            if not prev["can_validate"]:
                _fight_v11_log(game_state, f"PILE IN unit {act_uid} → plan invalide {prev}")
                return True, _fight_pile_in_model_plan_state(
                    game_state, u, prov, None, view_level=_view_level
                )
            _uc_before = require_key(game_state, "units_cache")[act_uid]
            _from_col, _from_row = int(_uc_before["col"]), int(_uc_before["row"])
            _fight_pile_in_commit_plan(game_state, u, full_plan)
            game_state["pile_in_done"].add(act_uid)
            _fight_v11_clear_pile_in_preview(game_state)
            # Log par-figurine (mode fin type charge, sans roll) : ligne unite + moveDetails.
            _uc_after = require_key(game_state, "units_cache")[act_uid]
            _to_col, _to_row = int(_uc_after["col"]), int(_uc_after["row"])
            _move_details = [
                {
                    "modelId": m,
                    "fromCol": origin[m][0],
                    "fromRow": origin[m][1],
                    "toCol": int(nc),
                    "toRow": int(nr),
                    "toLevel": int(nlv),
                }
                for m, nc, nr, nlv in full_plan
            ]
            append_action_log(
                game_state,
                {
                    "type": "pile_in",
                    "message": (
                        f"Unit {u['id']} PILED IN from ({_from_col},{_from_row}) "
                        f"to ({_to_col},{_to_row})"
                    ),
                    "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
                    "phase": "fight",
                    "unitId": u["id"],
                    "player": u["player"],
                    "fromCol": _from_col,
                    "fromRow": _from_row,
                    "toCol": _to_col,
                    "toRow": _to_row,
                    "timestamp": "server_time",
                    "is_ai_action": u["player"] == 2,
                    "moveDetails": _move_details,
                },
            )
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
            state = _fight_pile_in_model_plan_state(
                game_state, u, view_level=_view_level
            )
            _fight_v11_log(
                game_state,
                f"PILE IN : unit {uid} sélectionnée (par-figurine, "
                f"{len(state['eligible_models'])} figs déplaçables)",
            )
            return True, state

        # Autre action en pile_in → ré-afficher l'état courant.
        return _fight_v11_manual_state(game_state)

    if sub == "fight":
        pool = fight_v11_current_pool(game_state)  # unités éligibles du sélecteur courant (12.04)
        active = game_state.get("active_fight_unit")
        active = str(active) if active is not None else None
        _fight_v11_log(
            game_state,
            f"FIGHT dispatch: pool={pool} active={active} uid_recu={uid} action={atype!r} "
            f"step={game_state.get('fight_step')} fought={sorted(game_state.get('units_fought', set()))}"
        )

        if skip:
            # « Passer » une unité en étape fight = clic droit (right_click → skip, calculé
            # plus haut). GARDÉ (encart 12 « you have to fight with all units that can ») :
            # autorisé UNIQUEMENT si l'unité active n'a AUCUNE cible valide. Sinon elle DOIT
            # combattre → skip refusé. Sans cible, elle est « selected to fight » sans attaque
            # (12.04) : elle sort du pool ET devient éligible à la consolidation (12.08).
            if active is not None and active in pool:
                u = get_unit_by_id(game_state, active)
                if u is None:
                    raise KeyError(f"Fight skip unit {active} missing from game_state['units']")
                valid = _fight_build_valid_target_pool(game_state, u)
                if valid:
                    _fight_v11_log(
                        game_state,
                        f"FIGHT skip REFUSÉ pour {active} : cibles valides {valid} "
                        f"(obligation de combattre, encart 12)",
                    )
                    return _fight_v11_manual_state(game_state)
                _fight_v11_register_selection(game_state, active)
                game_state["active_fight_unit"] = None
                _fight_v11_log(
                    game_state,
                    f"FIGHT unit {active} → passée (aucune cible valide, sélectionnée sans attaque)",
                )
            return _fight_v11_manual_state(game_state)

        if atype == "skip_fight":
            # Bouton « Skip » : abandonne TOUTES les attaques restantes (2 joueurs) et passe
            # directement à la consolidation. Contourne sciemment l'obligation de combattre
            # (raccourci de confort). Les unités encore éligibles sont marquées « selected to
            # fight » (sans attaque) pour rester éligibles à la consolidation (12.08, cf.
            # fight_v11_is_consolidation_eligible).
            for p in (1, 2):
                for e in fight_v11_eligible_unit_ids(game_state, p, fights_first_only=False):
                    game_state["units_selected_to_fight"].add(str(e))
            game_state["active_fight_unit"] = None
            fight_v11_enter_consolidate(game_state)
            _fight_v11_log(game_state, "FIGHT → SKIP global (toutes attaques abandonnées) → CONSOLIDATE")
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 1 — le joueur choisit librement une de SES unités éligibles (12.04).
        if atype == "activate_unit":
            if uid is not None and uid in pool:
                game_state["active_fight_unit"] = uid
                _fight_v11_log(game_state, f"FIGHT unit {uid} ACTIVÉE par le joueur")
            else:
                _fight_v11_log(game_state, f"FIGHT activate ignoré : {uid} hors pool {pool}")
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 2 (flux manuel par arme/figurine, calque du tir) — declarations
        # offensives puis validation. Additif : coexiste avec le clic-resolution direct.
        if active is not None and active in pool and atype in ("squad_fight_assign", "squad_fight_assign_weapon"):
            sel = active
            _fight_ensure_activation_started(game_state, sel)
            target_id = str(require_key(action, "targetId"))
            if atype == "squad_fight_assign":
                model_id = str(require_key(action, "modelId"))
                # Choix d arme optionnel par figurine (sinon arme courante / index 0).
                if "weaponIndex" in action:
                    models_cache = require_key(game_state, "models_cache")
                    m = models_cache.get(model_id)
                    if m is not None:
                        m["selectedCcWeaponIndex"] = int(action["weaponIndex"])
                squad_declare_fight_model(game_state, sel, model_id, target_id)
            else:
                widx = int(require_key(action, "weaponIndex"))
                squad_declare_fight_weapon(game_state, sel, widx, target_id)
            return _fight_v11_manual_state(game_state)

        # VALIDATION — resout les attaques DECLAREES (allocation manuelle des pertes).
        if active is not None and active in pool and atype == "squad_fight_validate":
            sel = active
            u = get_unit_by_id(game_state, sel)
            if u is None:
                raise KeyError(f"Fight unit {sel} missing from game_state['units']")
            from .shared_utils import init_pending_intents
            init_pending_intents(game_state)
            intents = game_state["pending_squad_fight_intents"].get(sel, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
            if not intents:
                _fight_v11_log(game_state, f"FIGHT validate {sel} : aucune declaration -> ignore")
                return _fight_v11_manual_state(game_state)
            # Defenseur : en PvP test les cibles appartiennent au joueur adverse (humain).
            target_id = str(intents[0]["target_unit_id"])
            target_unit = get_unit_by_id(game_state, target_id)
            defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
            if not defender_human:
                raise RuntimeError(
                    f"FIGHT validate {sel} : flux de declaration manuelle non supporte "
                    f"pour un defenseur IA (cible {target_id})"
                )
            _fight_v11_register_selection(game_state, sel)
            game_state["active_fight_unit"] = None
            alloc_result = build_manual_fight_allocation(game_state, sel)
            _fight_v11_log(
                game_state,
                f"FIGHT validate {sel} : alloc waiting={alloc_result.get('waiting_for_player')}"
            )
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 2 — unité active + clic sur une cible → résolution + allocation.
        if active is not None and active in pool and atype in ("fight", "left_click"):
            sel = active
            u = get_unit_by_id(game_state, sel)
            if u is None:
                raise KeyError(f"Fight unit {sel} missing from game_state['units']")
            _fight_v11_register_selection(game_state, sel)
            ftype = "normal"
            if action.get("fight_type") == "overrun" and fight_v11_is_overrun_eligible(game_state, u):
                ftype = "overrun"
                _fight_v11_auto_overrun_pile_in(game_state, u, config)
            valid = _fight_build_valid_target_pool(game_state, u)
            _fight_v11_log(game_state, f"FIGHT unit {sel} (type={ftype}) : pool cibles = {valid}")
            if valid:
                pref = str(action["targetId"]) if "targetId" in action else None
                target_id = pref if (pref is not None and pref in valid) else _ai_select_fight_target(game_state, sel, valid)
                target_unit = get_unit_by_id(game_state, target_id)
                defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
                _fight_v11_log(game_state, f"FIGHT unit {sel} -> cible {target_id} (clic={pref}) defenseur_humain={defender_human}")
                # L'unité a fini d'attaquer : on libère l'active (la prochaine sera re-choisie).
                game_state["active_fight_unit"] = None
                if defender_human:
                    # Defenseur humain (§G) : allocation manuelle des pertes (par-figurine).
                    squad_fight_unit_activation_start(game_state, sel)
                    squad_declare_fight(game_state, sel, target_id)
                    alloc_result = build_manual_fight_allocation(game_state, sel)
                    _fight_v11_log(
                        game_state,
                        f"FIGHT unit {sel} : alloc waiting={alloc_result.get('waiting_for_player')} done={alloc_result.get('done')}"
                    )
                    if alloc_result.get("waiting_for_player"):
                        return True, alloc_result
                else:
                    # Defenseur IA : resolution auto (chemin V11 inchange, HP-pool unite).
                    _fight_v11_log(game_state, f"FIGHT unit {sel} : defenseur IA -> resolution auto")
                    _fight_v11_resolve_attacks(game_state, u, config, preferred_target_id=target_id)
            else:
                _fight_v11_log(game_state, f"FIGHT unit {sel} : aucune cible valide")
            return _fight_v11_manual_state(game_state)

        _fight_v11_log(game_state, f"FIGHT: action ignorée (active={active}, uid={uid}, action={atype!r})")
        return _fight_v11_manual_state(game_state)

    if sub == "consolidate":
        # New Foes to Face (12.08 engaging AFTER, §8.C) : pool restreint à l'adversaire, prioritaire
        # sur la suite de la consolidation. PAS l'alternance 12.04.
        if "consolidation_new_foes_pending" in game_state:
            remaining = _fight_v11_consolidation_new_foes_remaining(game_state)
            if remaining:
                return _fight_v11_consolidation_new_foes_step(game_state, action, config, remaining)
            _fight_v11_consolidation_clear_new_foes(game_state)

        nxt = fight_v11_grouped_next(game_state, "consolidate")
        eligible = nxt[1] if nxt else []

        if atype == "end_consolidation":
            # « Terminer la consolidation » : marque tout le groupe actif comme traité.
            for e in eligible:
                game_state["consolidation_done"].add(str(e))
            game_state["active_fight_unit"] = None
            _fight_v11_clear_consolidation_preview(game_state)
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE → fin demandée par le joueur (groupe {list(eligible)} marqué traité)",
            )
            return _fight_v11_manual_state(game_state)

        active = game_state.get("active_fight_unit")
        act_uid = str(active) if active is not None else None

        _view_level = int(action.get("level") or 0)

        def _prov_from_action() -> Dict[str, Tuple[int, int, int]]:
            # (col,row) ou (col,row,level) : niveau d'étage capturé au drop de chaque fig (frontend)
            # conservé → une fig posée sur un étage y reste (§13.06, miroir move par-figurine).
            prov: Dict[str, Tuple[int, int, int]] = {}
            for e in (action.get("plan") or []):
                lvl = int(e[3]) if len(e) >= 4 and e[3] is not None else _view_level
                prov[str(e[0])] = (int(e[1]), int(e[2]), lvl)
            return prov

        if skip:
            # Le joueur renonce à consolider l'unité active → traitée sans déplacement.
            if act_uid is not None and act_uid in eligible:
                game_state["consolidation_done"].add(act_uid)
                game_state["active_fight_unit"] = None
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → SKIP (joueur)")
            _fight_v11_clear_consolidation_preview(game_state)
            return _fight_v11_manual_state(game_state)

        if atype == "cancel_consolidation":
            # Annulation du plan en cours : désélectionne l'unité SANS la consommer (elle reste
            # éligible/sélectionnable) et purge le preview + les sélections engaging/objective.
            if act_uid is not None:
                game_state["active_fight_unit"] = None
                _fight_v11_log(
                    game_state,
                    f"CONSOLIDATE unit {act_uid} → annulation (unité reste sélectionnable)",
                )
            _fight_v11_clear_consolidation_preview(game_state)
            return _fight_v11_manual_state(game_state)

        if atype == "activate_unit" and uid in eligible:
            # Sélection d'une unité à consolider → repart d'une sélection vierge + plan par-figurine.
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Consolidation unit {uid} missing from game_state['units']")
            game_state["active_fight_unit"] = uid
            _fight_v11_clear_consolidation_preview(game_state)
            done = {str(x) for x in game_state.get("consolidation_done", set())}
            game_state["fight_eligible_units"] = [e for e in eligible if str(e) not in done]
            state = _fight_consolidation_model_plan_state(
                game_state, u, view_level=_view_level
            )
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE : unit {uid} sélectionnée (mode={state.get('consolidation_mode')})",
            )
            return True, state

        # Actions portant sur l'unité active.
        if act_uid is None or act_uid not in eligible:
            return _fight_v11_manual_state(game_state)
        u = get_unit_by_id(game_state, act_uid)
        if u is None:
            raise KeyError(f"Consolidation unit {act_uid} missing from game_state['units']")

        if atype == "consolidation_select_target":
            # Engaging : toggle d'un ennemi candidat (≤3") dans la sélection préalable au move.
            target = action.get("targetId")
            if target is None:
                return False, {"error": "consolidation_select_target requires targetId", "action": action}
            tid = str(target)
            candidates = {str(c) for c in _fight_v11_consolidation_engaging_candidates(game_state, u)}
            if tid in candidates:
                sel_map = game_state.setdefault("consolidation_engaging_selection", {})
                cur = {str(x) for x in sel_map.get(act_uid, [])}  # fallback allowed — unité sans sélection préalable = ensemble vide (métier)
                if tid in cur:
                    cur.discard(tid)
                else:
                    cur.add(tid)
                sel_map[act_uid] = sorted(cur)
                _fight_v11_log(game_state, f"CONSOLIDATE engaging : sélection {act_uid} = {sel_map[act_uid]}")
            else:
                _fight_v11_log(game_state, f"CONSOLIDATE engaging : cible {tid} hors candidats {candidates}")
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidation_select_objective":
            # Objective : single-select de l'objectif (si >1 candidat).
            oid = action.get("objectiveId")
            if oid is None:
                return False, {"error": "consolidation_select_objective requires objectiveId", "action": action}
            candidates = _fight_v11_consolidation_objective_candidates(game_state, u)
            match = next((c for c in candidates if str(c) == str(oid)), None)
            if match is not None:
                game_state.setdefault("consolidation_objective_selection", {})[act_uid] = match
                _fight_v11_log(game_state, f"CONSOLIDATE objective : {act_uid} vise objectif {match}")
            else:
                _fight_v11_log(game_state, f"CONSOLIDATE objective : objectif {oid} hors candidats {candidates}")
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidation_plan_state":
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidate_autoplace":
            # Focus off./déf. : auto-placement ILP conforme 12.08 (ongoing → pile-in ; engaging → charge).
            mode = str(action.get("mode", "defensive"))
            out = consolidate_autoplace_plan(game_state, act_uid, mode=mode)
            return True, {"action": "consolidate_autoplace", "unitId": act_uid, **out}

        if atype == "commit_consolidation_plan":
            mode, tier = _fight_v11_consolidation_targets(game_state, u)
            # Move bloqué tant que la sélection préalable n'est pas faite.
            blocked = (
                mode is None
                or (mode == "engaging" and not tier)
                or (mode == "objective" and tier is None)
            )
            if blocked:
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → commit bloqué (sélection requise, mode={mode})")
                return True, _fight_consolidation_model_plan_state(
                    game_state, u, _prov_from_action(), None, view_level=_view_level
                )
            # Invariant post-guard : mode/tier sont renseignés (None ⇒ blocked, déjà retourné).
            assert mode is not None and tier is not None
            prov = _prov_from_action()
            models_cache = require_key(game_state, "models_cache")
            squad_models = require_key(game_state, "squad_models")
            alive = [str(m) for m in require_key(squad_models, act_uid) if str(m) in models_cache]
            origin = {
                m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]),
                    int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
                for m in alive
            }
            full_plan: List[Tuple[str, int, int, int]] = [
                (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
                else (m, origin[m][0], origin[m][1], origin[m][2])
                for m in alive
            ]
            tier_kind = "zone" if mode == "objective" else "enemy"
            lock_base_contact = mode == "ongoing"
            closest = _fight_pile_in_closest_tier_ids(game_state, u, list(tier)) if tier_kind == "enemy" else []
            engaged_before = _fight_units_engaged_with(game_state, u)
            prev = _fight_consolidation_preview_plan(
                game_state, act_uid, full_plan, mode=mode, tier_kind=tier_kind, tier=tier,
                closest_tier_ids=closest, engaged_before_ids=engaged_before,
                lock_base_contact=lock_base_contact,
            )
            if not prev["can_validate"]:
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → plan invalide {prev}")
                return True, _fight_consolidation_model_plan_state(
                    game_state, u, prov, None, view_level=_view_level
                )
            _uc_before = require_key(game_state, "units_cache")[act_uid]
            _from_col, _from_row = int(_uc_before["col"]), int(_uc_before["row"])
            _fight_consolidation_commit_plan(game_state, u, full_plan)
            game_state["consolidation_done"].add(act_uid)
            game_state["active_fight_unit"] = None
            # Log par-figurine (mode fin type charge, sans roll) : ligne unite + moveDetails.
            _uc_after = require_key(game_state, "units_cache")[act_uid]
            _to_col, _to_row = int(_uc_after["col"]), int(_uc_after["row"])
            _move_details = [
                {
                    "modelId": m,
                    "fromCol": origin[m][0],
                    "fromRow": origin[m][1],
                    "toCol": int(nc),
                    "toRow": int(nr),
                    "toLevel": int(nlv),
                }
                for m, nc, nr, nlv in full_plan
            ]
            append_action_log(
                game_state,
                {
                    "type": "consolidation",
                    "message": (
                        f"Unit {u['id']} CONSOLIDATED from ({_from_col},{_from_row}) "
                        f"to ({_to_col},{_to_row})"
                    ),
                    "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
                    "phase": "fight",
                    "unitId": u["id"],
                    "player": u["player"],
                    "fromCol": _from_col,
                    "fromRow": _from_row,
                    "toCol": _to_col,
                    "toRow": _to_row,
                    "timestamp": "server_time",
                    "is_ai_action": u["player"] == 2,
                    "moveDetails": _move_details,
                },
            )
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE unit {act_uid} → commit par-figurine (mode={mode}, {len(full_plan)} figs)",
            )
            # Engaging « New Foes to Face » (12.08 AFTER / §8.C) : résolution CIBLÉE in-place.
            new_foes_result: Optional[Dict[str, Any]] = None
            if mode == "engaging":
                new_foes_result = _fight_v11_consolidation_resolve_new_foes(game_state, u, config)
            _fight_v11_clear_consolidation_preview(game_state)
            if new_foes_result is not None and new_foes_result.get("waiting_for_player"):
                return True, new_foes_result
            return _fight_v11_manual_state(game_state)

        # Autre action en consolidate → ré-afficher l'état courant.
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
