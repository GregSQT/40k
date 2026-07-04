#!/usr/bin/env python3
"""
movement_handlers.py - AI_TURN.md Movement Phase Implementation
Pure stateless functions implementing AI_TURN.md movement specification

References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any, cast
import math
import numpy as np
from collections import deque, OrderedDict
from .generic_handlers import end_activation, _log_with_context
from shared.data_validation import require_key, require_present
from engine.action_log_utils import append_action_log
from engine.combat_utils import (
    calculate_hex_distance,
    normalize_coordinates,
    set_unit_coordinates,
    get_unit_by_id,
    get_hex_neighbors,
)
from .shared_utils import (
    ACTION, WAIT, NO, PASS, ERROR, MOVE, FLED,
    build_enemy_adjacent_hexes, update_units_cache_position, translate_squad_to_destination,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    build_occupied_positions_set,
    build_enemy_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid, is_placement_valid_with_clearance,
    get_engagement_zone, get_max_base_size_hex,
    get_squad_move_budget, validate_move_plan, _validate_plan_coherency, commit_move,
    get_coherency_subhex, get_cohesion_max_subhex, get_min_neighbors,
    coherency_violation_flags,
    _compute_unit_occupied_hexes, _squad_is_in_enemy_er,
    roll_advance_for_squad,
)
from engine.hex_utils import (
    _hex_center,
    _SEG_TOL,
    ENGAGEMENT_NORM_HEX_WIDTH,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    geodesic_field,
    min_distance_between_sets,
    round_base_radius_norm,
)
from engine.phase_handlers.geodesic_move import _euclidean_move_field
from engine.hex_union_boundary_polygon import (
    compute_move_preview_mask_loops_world,
    _board_hex_radius_margin,
)
from engine.perf_timing import profile_move_pool_build

# Cache LRU (footprint ∪ géométrie plateau) — même sortie que ``compute_move_preview_mask_loops_world``.
_MASK_LOOP_CACHE_MAX = 64
_mask_loop_cache: "OrderedDict[Tuple[frozenset, float, float], Optional[List[List[Tuple[float, float]]]]]" = OrderedDict()


def _validate_move_orientation(raw_orientation: Any) -> int:
    """Validate a move orientation step from semantic action payload."""
    if isinstance(raw_orientation, bool) or not isinstance(raw_orientation, int):
        raise ValueError(f"Move orientation must be an integer in 0..5, got {raw_orientation!r}")
    if raw_orientation < 0 or raw_orientation > 5:
        raise ValueError(f"Move orientation must be in 0..5, got {raw_orientation!r}")
    return raw_orientation


def _require_footprint_base_size(base_shape: str, base_size: Any, context: str) -> Any:
    """Validate BASE_SIZE against BASE_SHAPE before footprint computation."""
    if base_shape == "round" or base_shape == "square":
        if isinstance(base_size, bool) or not isinstance(base_size, int):
            raise ValueError(f"{context}: {base_shape} BASE_SIZE must be int, got {base_size!r}")
        return base_size
    if base_shape == "oval":
        if not isinstance(base_size, (list, tuple)) or len(base_size) != 2:
            raise ValueError(f"{context}: oval BASE_SIZE must be [major, minor], got {base_size!r}")
        return base_size
    raise ValueError(f"{context}: unsupported BASE_SHAPE {base_shape!r}")


def _sync_move_preview_mask_loops(
    game_state: Dict[str, Any], footprint_zone: Set[Tuple[int, int]]
) -> None:
    """Polygone(s) masque pour le client — évite d’envoyer des milliers de (col,row) en JSON."""
    hr, margin = _board_hex_radius_margin(game_state)
    cache_key = (frozenset(footprint_zone), float(hr), float(margin))
    if cache_key in _mask_loop_cache:
        game_state["move_preview_footprint_mask_loops"] = _mask_loop_cache[cache_key]
        _mask_loop_cache.move_to_end(cache_key)
        return

    loops = compute_move_preview_mask_loops_world(footprint_zone, game_state)
    game_state["move_preview_footprint_mask_loops"] = loops

    _mask_loop_cache[cache_key] = loops
    _mask_loop_cache.move_to_end(cache_key)
    while len(_mask_loop_cache) > _MASK_LOOP_CACHE_MAX:
        _mask_loop_cache.popitem(last=False)

def _move_preview_footprint_span(unit: Dict[str, Any]) -> int:
    """Dimension max d’empreinte (hexes), alignée sur charge_handlers._charge_base_diameter — rayon disques UI."""
    bs = unit["BASE_SIZE"]
    if isinstance(bs, (list, tuple)) and len(bs) >= 1:
        try:
            return max(int(v) for v in bs)
        except (TypeError, ValueError):
            return 1
    if isinstance(bs, (list, tuple)):
        return 1
    try:
        return max(1, int(bs))
    except (TypeError, ValueError):
        return 1


def _hex_radius_upper_for_engagement_prune(base_span: int) -> int:
    """Majorant (grille hex) du rayon empreinte depuis l’ancre — borne conservatrice pour la prune."""
    s = max(1, int(base_span))
    return max(1, (s + 1) // 2)


def _build_objective_distance_cache(
    game_state: Dict[str, Any],
) -> Tuple[List[Set[Tuple[int, int]]], List[Tuple[int, int]]]:
    """Build exact objective distance refs with boundary reduction for move strategy 3."""
    cached = game_state.get("_objective_distance_cache")
    objectives = game_state.get("objectives")
    if (
        isinstance(cached, dict)
        and cached.get("objectives_ref") is objectives
        and isinstance(cached.get("objective_hex_sets"), list)
        and isinstance(cached.get("boundary_hexes"), list)
    ):
        return cached["objective_hex_sets"], cached["boundary_hexes"]

    objective_hex_sets: List[Set[Tuple[int, int]]] = []
    boundary_union: Set[Tuple[int, int]] = set()

    if isinstance(objectives, list):
        for obj in objectives:
            if not isinstance(obj, dict):
                continue
            raw_hexes = obj.get("hexes")
            if not isinstance(raw_hexes, list):
                continue

            objective_hex_set: Set[Tuple[int, int]] = set()
            for raw_hex in raw_hexes:
                if isinstance(raw_hex, dict):
                    objective_hex_set.add((int(raw_hex["col"]), int(raw_hex["row"])))
                elif isinstance(raw_hex, (list, tuple)) and len(raw_hex) == 2:
                    objective_hex_set.add((int(raw_hex[0]), int(raw_hex[1])))

            if not objective_hex_set:
                continue

            objective_hex_sets.append(objective_hex_set)
            for hex_pos in objective_hex_set:
                for neighbor in get_hex_neighbors(hex_pos[0], hex_pos[1]):
                    if neighbor not in objective_hex_set:
                        boundary_union.add(hex_pos)
                        break

    boundary_hexes = list(boundary_union)
    game_state["_objective_distance_cache"] = {
        "objectives_ref": objectives,
        "objective_hex_sets": objective_hex_sets,
        "boundary_hexes": boundary_hexes,
    }
    return objective_hex_sets, boundary_hexes


def _enemy_items_within_move_engagement_horizon(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    unit_id_str: str,
    mover_player_int: int,
    start_col: int,
    start_row: int,
    move_range: int,
    units_cache: Dict[str, Any],
) -> List[Tuple[Any, Any]]:
    """Ennemis susceptibles d’interagir avec un déplacement depuis ``(start_col, start_row)``.

    Borne conservatrice (distance hex entre **ancres**) :
    ``MOVE + r_m + r_e + engagement_zone + 1``, avec ``r_*`` dérivés du diamètre d’empreinte
    (ennemi plafonné par ``max_base_size_hex``). Toute destination légale est à ≤ ``MOVE`` pas
    de l’ancre de départ (inégalité triangulaire sur la métrique hex) ; on ajoute les rayons
    car l’engagement teste bord à bord / cellules, pas seulement l’écart entre ancres. Le ``+1``
    couvre l’arrondi hex ↔ espace continu (_hex_center). Exclure au-delà pourrait omettre un
    ennemi encore pertinent → liste sur-approximée, résultat identique à un scan complet.
    """
    ez = get_engagement_zone(game_state)
    max_bs = get_max_base_size_hex(game_state)
    mover_r = _hex_radius_upper_for_engagement_prune(_move_preview_footprint_span(unit))
    m = int(move_range)
    horizon_without_enemy_r = m + mover_r + int(ez) + 1

    out: List[Tuple[Any, Any]] = []
    for eid, ce in units_cache.items():
        if str(eid) == unit_id_str:
            continue
        if int(require_key(ce, "player")) == mover_player_int:
            continue
        e_span = min(_move_preview_footprint_span(ce), max_bs)
        e_r = _hex_radius_upper_for_engagement_prune(e_span)
        h = horizon_without_enemy_r + e_r
        # Distance à la figurine la PLUS PROCHE du squad (pas seulement l'ancre) : une escouade
        # multi-fig s'étend bien au-delà de son ancre (ex. 20 Termagants sur ~24 hex), donc un
        # filtre basé sur l'ancre seule omettrait un squad dont une fig est pourtant à portée.
        by_model = ce.get("occupied_hexes_by_model")
        if by_model:
            positions: Any = by_model.values()
        else:
            positions = ((int(require_key(ce, "col")), int(require_key(ce, "row"))),)
        if any(
            calculate_hex_distance(start_col, start_row, int(pc), int(pr)) <= h
            for pc, pr in positions
        ):
            out.append((eid, ce))
    return out


def _unit_has_keyword(unit: Dict[str, Any], keyword_id: str) -> bool:
    """
    Return True if UNIT_KEYWORDS contains keyword_id.

    UNIT_KEYWORDS entries must be objects with a `keywordId` field.
    """
    unit_keywords = unit.get("UNIT_KEYWORDS")
    if unit_keywords is None:
        return False
    if not isinstance(unit_keywords, list):
        raise ValueError(
            f"UNIT_KEYWORDS must be a list for unit {unit.get('id')}, got {type(unit_keywords).__name__}"
        )
    for keyword_entry in unit_keywords:
        if not isinstance(keyword_entry, dict):
            raise ValueError(
                f"UNIT_KEYWORDS entries must be objects for unit {unit.get('id')}: {keyword_entry!r}"
            )
        keyword_value = keyword_entry.get("keywordId")
        if keyword_value == keyword_id:
            return True
    return False


def _fly_traversal_active(game_state: Dict[str, Any], unit: Dict[str, Any], unit_id: Any) -> bool:
    """Take to the skies (Règles 21.03) : la traversée FLY (murs/figurines + ignore vertical) est
    active si l'unité a le keyword fly ET :
    - hors phase de mouvement, ou unité IA (gym / PvE joueur 2) → vol auto legacy (inchangé) ;
    - en phase move pour un joueur humain → seulement si le vol a été déclaré (units_took_to_skies).
    Source unique partagée par le pool d'ancre, le reachable par-figurine et le log de move.
    """
    if not _unit_has_keyword(unit, "fly"):
        return False
    in_move_phase = game_state.get("phase") == "move"
    is_gym = bool(game_state.get("gym_training_mode", False))
    is_pve = bool(game_state.get("pve_mode", False)) or bool(game_state.get("is_pve_mode", False))
    is_ai_unit = is_gym or (is_pve and int(require_key(unit, "player")) == 2)
    if not (in_move_phase and not is_ai_unit):
        return True
    return str(unit_id) in game_state.get("units_took_to_skies", set())


def _movement_engagement_violates(
    game_state: Dict[str, Any],
    mover: Dict[str, Any],
    center_col: int,
    center_row: int,
    candidate_fp: Set[Tuple[int, int]],
    units_cache: Dict[str, Any],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]] = None,
    *,
    enemy_cache_items: Optional[List[Tuple[Any, Any]]] = None,
    engagement_zone_ez: Optional[int] = None,
) -> bool:
    """True si le placement est interdit par la zone autour des ennemis.

    Plateau ×10 (``engagement_zone`` > 1) : pour deux socles **ronds**, écart
    bord à bord euclidien (repère ``_hex_center``) ≥ ``engagement_zone`` × pas
    horizontal — aligné preview combat / ``hexFootprint.ts``. Autres formes :
    repli sur ``min_distance_between_sets`` (comportement historique).
    Legacy (``engagement_zone`` ≤ 1) : toute case de l'empreinte dans
    ``enemy_adjacent_hexes`` (dilatation hex).
    """
    if engagement_zone_ez is not None:
        ez = engagement_zone_ez
    else:
        ez = get_engagement_zone(game_state)
    from engine.spatial_relations import move_anchor_violates_engagement_clearance

    return move_anchor_violates_engagement_clearance(
        game_state,
        mover,
        center_col,
        center_row,
        candidate_fp,
        units_cache,
        enemy_adjacent_hexes,
        enemy_cache_items=enemy_cache_items,
        engagement_zone_ez=ez,
    )


def _invalidate_all_destination_pools_after_movement(game_state: Dict[str, Any]) -> None:
    """
    Invalidate all destination pools after any unit movement.
    
    After a unit moves, all destination pools become stale because:
    - Occupied positions have changed
    - Enemy adjacent hexes have changed
    - Friendly adjacent hexes have changed (for future use)
    
    This function clears:
    - valid_move_destinations_pool (for all units)
    - valid_charge_destinations_pool (for all units)
    - valid_target_pool (for all units in shoot phase)
    - _target_pool_cache (global cache in shooting_handlers)
    
    Called after every movement in move, shoot (advance), and charge phases.
    """
    # Clear movement destination pools
    if "valid_move_destinations_pool" in game_state:
        game_state["valid_move_destinations_pool"] = []
    if "move_preview_footprint_zone" in game_state:
        game_state["move_preview_footprint_zone"] = set()
    if "move_preview_border" in game_state:
        game_state["move_preview_border"] = []
    if "move_preview_footprint_mask_loops" in game_state:
        game_state["move_preview_footprint_mask_loops"] = None

    # Clear charge destination pools
    if "valid_charge_destinations_pool" in game_state:
        game_state["valid_charge_destinations_pool"] = []
    if "_charge_dest_bfs_cache" in game_state:
        game_state["_charge_dest_bfs_cache"] = {}
    # Champ géodésique de move par-figurine (Étape 4.1) : vidé au phase start et après chaque
    # commit réel. Les poses provisoires du move-preview N'appellent PAS cette fonction → le champ
    # (indépendant des sœurs quand thru_friendly) survit aux poses et n'est calculé qu'une fois.
    if "_move_model_field_cache" in game_state:
        game_state["_move_model_field_cache"] = {}
    if "_charge_closest_hex_cache" in game_state:
        game_state["_charge_closest_hex_cache"] = {}
    if "_has_valid_charge_cache" in game_state:
        game_state["_has_valid_charge_cache"] = {}

    # Clear target pools for all units (shoot phase)
    for unit in require_key(game_state, "units"):
        if "valid_target_pool" in unit:
            unit["valid_target_pool"] = []
    
    # Clear global target pool cache (shooting_handlers)
    from .shooting_handlers import _target_pool_cache
    _target_pool_cache.clear()

    # Enemy adjacency caches are updated incrementally at movement execution time.
    

def _log_movement_debug(game_state: Dict[str, Any], function_name: str, unit_id: str, message: str) -> None:
    """Helper to keep debug logging calls stable (no-op)."""
    return


def movement_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_MOVE.md: Initialize movement phase and build activation pool
    """
    # Set phase
    game_state["phase"] = "move"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} move units_cache={units_cache}")
    
    # Pre-compute enemy_adjacent_hexes once at phase start for all players present.
    # Reactive movement may query adjacency from the opposing player's perspective.
    players_present = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        try:
            player_int = int(player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache at movement_phase_start: {player_raw!r}"
            ) from exc
        players_present.add(player_int)
    for player_int in players_present:
        build_enemy_adjacent_hexes(game_state, player_int)

    # Invalidate all destination pools at the START of the phase
    # This ensures pools are clean and don't contain stale data from previous phases
    _invalidate_all_destination_pools_after_movement(game_state)
    
    # Build activation pool
    movement_build_activation_pool(game_state)
    
    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT POOL BUILT")
    
    # Check if phase complete immediately (no eligible units)
    if not game_state["move_activation_pool"]:
        return movement_phase_end(game_state)
    
    return {
        "phase_initialized": True,
        "eligible_units": len(game_state["move_activation_pool"]),
        "phase_complete": False
    }


def movement_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    AI_MOVE.md: Build activation pool with eligibility checks
    """
    current_player = require_key(game_state, "current_player")
    # Clear pool before rebuilding (defense in depth)
    game_state["move_activation_pool"] = []
    eligible_units = get_eligible_units(game_state)
    game_state["move_activation_pool"] = eligible_units

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} move move_activation_pool={eligible_units}")
    
    # Log pool build result
    _log_with_context(game_state, "MOVE DEBUG", f"movement_build_activation_pool: pool_size={len(eligible_units)} units={eligible_units}")


def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md movement eligibility decision tree implementation.

    Returns list of unit IDs eligible for movement activation.
    Pure function - no internal state storage.
    """
    eligible_units = []
    current_player = game_state["current_player"]

    units_cache = require_key(game_state, "units_cache")
    ez_elig = get_engagement_zone(game_state)
    for unit_id, cache_entry in units_cache.items():
        # "unit.player === current_player?"
        if cache_entry["player"] != current_player:
            continue  # Wrong player (Skip, no log)

        # Check if unit has at least one legal destination.
        # FLY units can ignore path blockers (walls/units) while moving, so eligibility
        # must not be limited to adjacent traversable hexes.
        unit_obj = get_unit_by_id(game_state, unit_id)
        if unit_obj is None:
            raise ValueError(f"Unit {unit_id} not found in game_state while building move eligibility")
        has_fly_keyword = _unit_has_keyword(unit_obj, "fly")

        # Normalize MOVE to int for range checks
        move_range_raw = require_key(unit_obj, "MOVE")
        try:
            move_range = int(move_range_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid MOVE value for unit {unit_id}: {move_range_raw!r}") from exc
        if move_range <= 0:
            continue

        # Unité ENGAGÉE (régime fin ez>1) : son seul déplacement légal est un Fall Back, qui
        # AUTORISE le passage dans l'EZ. L'heuristique "voisin immédiat hors EZ" ci-dessous
        # l'exclurait à tort (elle démarre DANS l'EZ). On délègue au builder de pool (BFS
        # fall-back rules-exact) en lecture seule : éligible ssi au moins une destination légale
        # (arrivée hors EZ de tous les ennemis, atteignable en M, empreinte valide) existe.
        if ez_elig > 1 and _squad_is_in_enemy_er(game_state, unit_id):
            if movement_build_valid_destinations_pool(game_state, unit_id, read_only=True):
                eligible_units.append(unit_id)
            continue

        # This ensures the unit can actually move
        unit_col, unit_row = require_unit_position(unit_id, game_state)
        
        occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id)
        current_player = require_key(game_state, "current_player")
        if current_player is None:
            raise KeyError("game_state missing required 'current_player' field")
        cache_key = f"enemy_adjacent_hexes_player_{current_player}"
        if cache_key not in game_state:
            raise KeyError(f"enemy_adjacent_hexes cache missing for player {current_player} - build_enemy_adjacent_hexes() must be called at phase start")
        enemy_adjacent_hexes = game_state[cache_key]

        has_valid_adjacent_hex = False
        if has_fly_keyword:
            board_cols = require_key(game_state, "board_cols")
            board_rows = require_key(game_state, "board_rows")
            fly_visited: Set[Tuple[int, int]] = {(unit_col, unit_row)}
            fly_q = deque([((unit_col, unit_row), 0)])
            while fly_q and not has_valid_adjacent_hex:
                fc, fd = fly_q.popleft()
                if fd >= move_range:
                    continue
                for nb in get_hex_neighbors(fc[0], fc[1]):
                    if nb in fly_visited:
                        continue
                    nc, nr = nb
                    if nc < 0 or nc >= board_cols or nr < 0 or nr >= board_rows:
                        continue
                    fly_visited.add(nb)
                    fly_q.append((nb, fd + 1))
                    candidate_fp = compute_candidate_footprint(nc, nr, unit_obj, game_state)
                    base_ok = is_footprint_placement_valid(
                        candidate_fp,
                        game_state,
                        occupied_positions,
                        enemy_adjacent_hexes if ez_elig <= 1 else None,
                    )
                    if base_ok and (
                        ez_elig <= 1
                        or not _movement_engagement_violates(
                            game_state,
                            unit_obj,
                            nc,
                            nr,
                            candidate_fp,
                            units_cache,
                            enemy_adjacent_hexes,
                            engagement_zone_ez=ez_elig,
                        )
                    ):
                        has_valid_adjacent_hex = True
                        break
        else:
            neighbors = get_hex_neighbors(unit_col, unit_row)
            for neighbor_pos in neighbors:
                neighbor_col, neighbor_row = neighbor_pos
                candidate_fp = compute_candidate_footprint(neighbor_col, neighbor_row, unit_obj, game_state)
                base_ok = is_footprint_placement_valid(
                    candidate_fp,
                    game_state,
                    occupied_positions,
                    enemy_adjacent_hexes if ez_elig <= 1 else None,
                )
                if base_ok and (
                    ez_elig <= 1
                    or not _movement_engagement_violates(
                        game_state,
                        unit_obj,
                        neighbor_col,
                        neighbor_row,
                        candidate_fp,
                        units_cache,
                        enemy_adjacent_hexes,
                        engagement_zone_ez=ez_elig,
                    )
                ):
                    has_valid_adjacent_hex = True
                    break

        if not has_valid_adjacent_hex:
            continue  # Unit cannot move (no valid adjacent hex)

        # Unit passes all conditions
        eligible_units.append(unit_id)

    # Log eligible units result
    _log_with_context(game_state, "MOVE DEBUG", f"get_eligible_units: eligible={eligible_units} count={len(eligible_units)}")

    return eligible_units


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_MOVE.md: Handler action routing with complete autonomy
    """
    if game_state.get("pending_shooting_phase_init"):
        return False, {
            "error": "pending_shooting_phase_init",
            "hint": "Movement phase ended; call semantic action advance_phase with from=move to start shooting.",
        }

    # Handler self-initialization on first action
    if "phase" not in game_state:
        game_state_phase = None
    else:
        game_state_phase = game_state["phase"]
    
    if "move_activation_pool" not in game_state:
        move_pool_exists = False
    else:
        move_pool_exists = bool(game_state["move_activation_pool"])
    
    if game_state_phase != "move" or not move_pool_exists:
        movement_phase_start(game_state)
    
    # Pool empty? -> Phase complete
    if not game_state["move_activation_pool"]:
        return True, movement_phase_end(game_state)
    
    # Get unit from action (frontend specifies which unit to move)
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = None  # Allow None for gym training auto-selection
    else:
        action_type = action["action"]
        unit_id = action["unitId"]
        
    # For gym training, if no unitId specified, use first eligible unit
    if not unit_id:
        if game_state["move_activation_pool"]:
            unit_id = game_state["move_activation_pool"][0]
        else:
            return True, movement_phase_end(game_state)
    
    # Validate unit is eligible (keep for validation, remove only after successful action)
    if unit_id not in game_state["move_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # Get unit object for processing
    active_unit = get_unit_by_id(game_state, unit_id)
    if not active_unit:
        return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # Log action routing
    _log_movement_debug(game_state, "execute_action", str(unit_id), f"action={action_type}")
    
    # Flag detection for consistent behavior
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
    
    # Auto-activate unit if not already activated and preview not shown
    # In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True if action already has destination
    if not game_state.get("active_movement_unit") and action_type in ["move", "left_click"]:
        if is_gym_training:
            # Gym training: Check if action already has destination (ActionDecoder constructed it)
            if "destCol" in action and "destRow" in action:
                # Action already has destination - execute movement directly, no waiting needed
                # Just ensure unit is activated, then continue to movement_destination_selection_handler
                movement_unit_activation_start(game_state, unit_id)
                # Build valid destinations pool for validation
                movement_build_valid_destinations_pool(game_state, unit_id)
                # Continue to execute movement directly (fall through to movement_destination_selection_handler below)
            else:
                # DIAGNOSTIC: ActionDecoder should always provide destination, but it doesn't
                # This should not happen in gym training - log for debugging
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log
                diagnostic_msg = f"[MOVE DIAGNOSTIC] E{episode} T{turn} Unit {unit_id}: ActionDecoder did not provide destCol/destRow. action keys: {list(action.keys())}"
                add_console_log(game_state, diagnostic_msg)
                # No destination yet - return waiting_for_player to get destination selection
                return _handle_unit_activation(game_state, active_unit, config)
        else:
            # Human players: activate but don't return, continue to normal flow
            _handle_unit_activation(game_state, active_unit, config)
    
    if action_type == "activate_unit":
        return _handle_unit_activation(game_state, active_unit, config)
    
    elif action_type == "move":
        # Execute movement directly (destination already in action for gym training)
        return movement_destination_selection_handler(game_state, unit_id, action)

    elif action_type == "advance":
        # V11 : bascule l'activation move en mode Advance (jet D6 + budget M+jet). Commit via commit_move_plan.
        return movement_set_advance_mode_handler(game_state, unit_id, action)

    elif action_type == "take_to_skies":
        # Règles 21.03 : (dé)clare le vol de l'escouade FLY active (-2" + traversée murs/figurines).
        return movement_set_fly_mode_handler(game_state, unit_id, action)

    elif action_type == "commit_move_plan":
        # Validate (= bouton Validate) + commit d'un plan provisoire par-figurine.
        return movement_commit_move_plan_handler(game_state, unit_id, action)

    elif action_type == "skip":
        # Engine determined unit has no valid actions (e.g. no valid destinations)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)

    elif action_type == "wait":
        # V11 : Stationary humain — terminer l'activation sans bouger (log WAIT).
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=True)
    
    elif action_type == "left_click":
        return movement_click_handler(game_state, unit_id, action)
    
    elif action_type == "right_click":
        if game_state.get("active_movement_unit") is not None:
            return _handle_movement_postpone(game_state, active_unit)
        return _handle_skip_action(game_state, active_unit)
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty
        # AI_TURN.md EXACT: end_activation(ERROR, 0, PASS, MOVE, 1, 1)
        if unit_id in game_state["move_activation_pool"]:
            # Clear preview first
            movement_clear_preview(game_state)
            
            # AI_TURN.md EXACT: Invalid actions [shoot, charge, attack] → end_activation(ERROR, 0, PASS, MOVE, 1, 1)
            result = end_activation(
                game_state, active_unit,
                ERROR,       # Arg1: ERROR (not SKIP)
                0,             # Arg2: No step increment (error doesn't count as action)
                PASS,        # Arg3: PASS tracking
                MOVE,        # Arg4: Remove from move pool
                1              # Arg5: Error logging enabled
            )
            result["invalid_action_penalty"] = True
            # No default value - require explicit attempted_action
            attempted_action = action.get("attempted_action")
            if attempted_action is None:
                raise ValueError(f"Action missing 'attempted_action' field: {action}")
            result["attempted_action"] = attempted_action
            return True, result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}


def movement_set_advance_mode_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """V11 : déclare l'Advance de l'escouade active (Règles 09.06).

    Lance 1D6 (figé), ajoute l'escouade à ``units_advanced`` et mémorise le jet dans
    ``advance_rolls`` — source unique persistante lue par ``_advance_roll_for`` (budget M+jet
    des pools, commit ``move_type='advance'``, blocage tir/charge). L'Advance survit donc aux
    cancel/ré-activations jusqu'à la phase de commandement suivante. Le déplacement reste piloté
    par le flow squad par-figurine (bloc + placements fins, commit_move_plan).
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}

    # Advance = engagement irréversible : marque l'escouade ``units_advanced`` (bloque tir/charge)
    # et fige son jet dans ``advance_rolls``. Jet figé : un squad déjà advancé réutilise son jet
    # (pas de re-roll), donc le mode survit aux cancel/ré-activations jusqu'à la fin de la phase.
    rolls = game_state.setdefault("advance_rolls", {})
    existing = rolls.get(str(unit_id))
    if existing is not None:
        roll = int(existing)
        game_state["current_advance_roll"] = roll
    else:
        roll = int(roll_advance_for_squad(str(unit_id), game_state))
        rolls[str(unit_id)] = roll
    game_state.setdefault("units_advanced", set()).add(str(unit_id))
    # Reconstruit le pool d'ancre au budget gonflé : le preview rigide (movePreview)
    # s'étend, et le front le re-synchronise depuis game_state. Volontairement hors du
    # result (sinon le flow advancePreview V10 se déclencherait côté front).
    pool = movement_build_valid_destinations_pool(game_state, unit_id)
    return True, {
        "action": "advance_mode_set",
        "unitId": unit["id"],
        "advance_roll": roll,
        "valid_destinations": pool,
        "waiting_for_player": True,
    }


def movement_set_fly_mode_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Take to the skies (Règles 21.03) : (dé)clare le vol de l'escouade FLY active.

    Toggle : ajoute/retire l'escouade de ``units_took_to_skies``. Effet (lu par les pools et le
    commit via ``get_squad_move_budget`` + ``movement_build_valid_destinations_pool``) :
    -2" sur la distance max du move ET traversée des murs/figurines pendant ce déplacement.
    Déclaration faite avant de bouger l'unité ; réversible tant que le move n'est pas commit.
    """
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}
    if not _unit_has_keyword(unit, "fly"):
        return False, {"error": "unit_cannot_fly", "unitId": unit["id"]}

    tts = game_state.setdefault("units_took_to_skies", set())
    uid = str(unit_id)
    if uid in tts:
        tts.discard(uid)
        declared = False
    else:
        tts.add(uid)
        declared = True
    # Rebuild le pool au nouveau budget/traversée ; le front re-synchronise depuis game_state.
    pool = movement_build_valid_destinations_pool(game_state, unit_id)
    # Réponse état-complète comme l'activation : le front re-dérive engagement (would_flee) et
    # mode Advance (advance_roll) à partir de la réponse ; les omettre les réinitialiserait.
    return True, {
        "action": "fly_mode_set",
        "unitId": unit["id"],
        "took_to_skies": declared,
        "valid_destinations": pool,
        "waiting_for_player": True,
        "would_flee": bool(_squad_is_in_enemy_er(game_state, str(unit_id))),
        "advance_roll": _advance_roll_for(str(unit_id), game_state),
    }


def _handle_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Unit activation start + execution loop"""
    # Unit activation start
    movement_unit_activation_start(game_state, unit["id"])

    # Unit execution loop (automatic)
    execution_result = movement_unit_execution_loop(game_state, unit["id"])

    # Clean flag detection
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)

    # In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True - the action will have destination when it arrives
    if is_gym_training and isinstance(execution_result, tuple) and execution_result[0]:
        # Direct field access
        if "waiting_for_player" not in execution_result[1]:
            waiting_for_player = False
        else:
            waiting_for_player = execution_result[1]["waiting_for_player"]

        # In gym training, ActionDecoder always provides destination in action
        # So we should NOT return waiting_for_player=True or waiting_for_movement_choice
        # Just return activation result without action (activation is not an action to log)
        # The movement will be executed in the same step when action with destCol/destRow is processed
        # Return result without action to skip logging (activation is not logged, only the movement is)
        return True, {
            "unit_activated": True,
            "unitId": unit["id"],
            "valid_destinations": execution_result[1]["valid_destinations"] if "valid_destinations" in execution_result[1] else [],
            # No action field - activation is not an action to log
            # Movement will be logged when action with destCol/destRow is processed
        }

    # All non-gym players (humans AND PvE AI) get normal waiting_for_player response
    return execution_result


def movement_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> None:
    """AI_MOVE.md: Unit activation initialization"""
    game_state["valid_move_destinations_pool"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_border"] = []
    game_state["preview_hexes"] = []
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = unit_id
    # Le mode Advance d'une escouade vit dans ``units_advanced``/``advance_rolls`` (persistant
    # tout le tour) : rien à nettoyer ici, la ré-activation retrouve le budget M+jet figé.


def movement_unit_execution_loop(game_state: Dict[str, Any], unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Single movement execution (no loop like shooting)"""
    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}
    
    # Reuse pool if already built (e.g., from execute_action validation)
    # Only rebuild if pool is empty or doesn't exist
    if not game_state.get("valid_move_destinations_pool"):
        movement_build_valid_destinations_pool(game_state, unit_id)
    
    # Check if valid destinations exist
    if not game_state["valid_move_destinations_pool"]:
        # No valid moves - AI_TURN.md EXACT: end_activation(NO, 0, PASS, MOVE, 1, 1)
        # Skip = engine-determined "no valid actions", skip_reason for step logger
        movement_clear_preview(game_state)
        result = end_activation(
            game_state, unit,
            NO,         # Arg1: NO (no action taken)
            0,            # Arg2: No step increment (no action)
            PASS,       # Arg3: PASS tracking
            MOVE,       # Arg4: Remove from move_activation_pool
            1             # Arg5: Error logging enabled
        )
        result.update({
            "action": "skip",
            "skip_reason": "no_valid_move_destinations",
            "unitId": unit["id"],
            "activation_complete": True
        })
        return True, result
    
    # Generate preview
    preview_data = movement_preview(game_state["valid_move_destinations_pool"])
    game_state["preview_hexes"] = game_state["valid_move_destinations_pool"]
    
    # In gym training, ActionDecoder constructs complete movement with destCol/destRow
    # So we should NOT return waiting_for_player=True - the action will have destination when it arrives
    is_gym_training = game_state.get("gym_training_mode", False)
    
    if is_gym_training:
        # Gym training: Don't return waiting_for_player=True - ActionDecoder will provide destination in action
        # Return result without waiting_for_player so movement can be executed directly
        return True, {
            "unit_activated": True,
            "unitId": unit_id,
            "valid_destinations": game_state["valid_move_destinations_pool"],
            "preview_data": preview_data,
            "waiting_for_player": False  # AI executes movement directly, no waiting
        }
    else:
        # Desperate Escape (09.07) : escouade engagée ET battle-shocked → on SUSPEND le move.
        # Pas de preview ; le front affiche un popup d'avertissement, et sa validation déclenche
        # l'action hazard_confirm (hazard 06.03 + attribution 06.02 AVANT de bouger). Une escouade
        # engagée mais saine = Ordered Retreat (aucun hazard) → flux normal ci-dessous.
        engaged_de = _squad_is_in_enemy_er(game_state, str(unit_id))
        shocked_de = bool(unit.get("battle_shocked", False))
        if engaged_de and shocked_de:
            # Desperate Escape : résolution SÉQUENTIELLE. Tant que le hazard n'est pas roulé/
            # attribué, l'unité ne doit PAS être en cours de déplacement côté front : aucun pool
            # vert, aucun ghost. movement_clear_preview met aussi active_movement_unit=None, et on
            # le laisse ainsi (les handlers hazard n'en dépendent pas : confirm via action.unitId,
            # allocate via pending_hazard_allocation). _resume_after_hazard re-posera l'unité active
            # + le pool Fall Back une fois les MW attribuées → le flux move normal reprend.
            movement_clear_preview(game_state)
            return True, {
                "action": "requires_hazard",
                "unitId": unit_id,
                "requires_hazard": True,
                "waiting_for_player": True,
            }
        # Human players: return waiting_for_player for destination selection
        return True, {
            "unit_activated": True,
            "unitId": unit_id,  # ADDED: Required for reward calculation
            "valid_destinations": game_state["valid_move_destinations_pool"],
            "preview_data": preview_data,
            "waiting_for_player": True,
            # V11 : engagement de l'escouade dès l'activation (positions PRE-move). Pilote l'UI
            # des modes de deplacement (engagee => Fall-back/Stationary ; non engagee => Move/Advance).
            "would_flee": bool(_squad_is_in_enemy_er(game_state, str(unit_id))),
            # V11 : jet d'Advance figé si l'escouade a déjà advancé ce tour (sinon None) — restaure
            # le badge + l'état « advancé » du bouton à la ré-activation après un cancel.
            "advance_roll": _advance_roll_for(str(unit_id), game_state),
        }


def _attempt_movement_to_destination(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    dest_col: int,
    dest_row: int,
    config: Dict[str, Any],
    orientation: Optional[int] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md movement execution with destination validation.

    Implements AI_TURN.md movement restrictions and flee detection.
    
    Note: Pool is already built in movement_unit_execution_loop() just after activation.
    Since system is sequential, pool is already built and validated.
    However, we still verify critical restrictions here as a safety check.
    """
    # Normalize coordinates to int - raises error if invalid
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)

    # Store original position
    orig_col, orig_row = require_unit_position(unit, game_state)

    # Flee detection: was adjacent to enemy before move
    was_adjacent = _squad_is_in_enemy_er(game_state, str(unit["id"]))

    # Final footprint-aware occupation check IMMEDIATELY before position assignment.
    # Prevents race conditions from reactive moves between pool build and commit.
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    phase = game_state.get("phase", "move")

    import time as _mct
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled
    _mct_pt = perf_timing_enabled(game_state)
    _mct0 = _mct.perf_counter() if _mct_pt else None

    unit_id_str = str(unit["id"])
    footprint_unit = unit
    if orientation is not None:
        footprint_unit = {
            "BASE_SHAPE": unit["BASE_SHAPE"],
            "BASE_SIZE": unit["BASE_SIZE"],
            "orientation": orientation,
        }
    candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, footprint_unit, game_state)
    _mct1 = _mct.perf_counter() if _mct_pt else None
    if not is_placement_valid_with_clearance(
        game_state, candidate_fp,
        shape=footprint_unit["BASE_SHAPE"], base_size=footprint_unit["BASE_SIZE"],
        col=dest_col_int, row=dest_row_int, exclude_unit_id=unit_id_str,
    ):
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[MOVE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot move to ({dest_col_int},{dest_row_int}) - footprint blocked"
        from engine.game_utils import add_console_log, safe_print
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        return False, {
            "error": "destination_occupied",
            "destination": (dest_col_int, dest_row_int)
        }

    # Re-validate against enemy engagement zone at commit time (euclidien bord à bord ×10).
    units_cache = require_key(game_state, "units_cache")
    _mct2_pre = _mct.perf_counter() if _mct_pt else None
    if _movement_engagement_violates(
        game_state,
        unit,
        dest_col_int,
        dest_row_int,
        candidate_fp,
        units_cache,
        None,
    ):
        blocking_eid: Optional[str] = None
        ez_blk = get_engagement_zone(game_state)
        mover_player_int = int(require_key(unit, "player"))
        mover_id_str = str(require_key(unit, "id"))
        if ez_blk >= 1:
            for eid, cache_entry in units_cache.items():
                if str(eid) == mover_id_str:
                    continue
                if int(require_key(cache_entry, "player")) == mover_player_int:
                    continue
                enemy_fp = cache_entry.get("occupied_hexes")
                if not enemy_fp:
                    enemy_fp = {(require_key(cache_entry, "col"), require_key(cache_entry, "row"))}
                if min_distance_between_sets(candidate_fp, enemy_fp, max_distance=ez_blk) <= ez_blk:
                    blocking_eid = str(eid)
                    break
        return False, {
            "error": "destination_adjacent_to_enemy",
            "enemy_id": blocking_eid,
            "destination": (dest_col_int, dest_row_int),
        }

    _mct2 = _mct.perf_counter() if _mct_pt else None

    # Execute movement - position assignment
    # Log ALL position changes to detect unauthorized modifications
    # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) via MOVE"
    from engine.game_utils import add_console_log
    from engine.game_utils import safe_print
    add_console_log(game_state, log_message)
    safe_print(game_state, log_message)
    
    # Log BEFORE each assignment to catch any modification
    from engine.game_utils import conditional_debug_print
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
    # Assign normalized int coordinates using set_unit_coordinates
    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

    # Capture old footprint before cache update (for multi-hex adjacency delta)
    unit_id_str_cache = str(unit["id"])
    old_cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
    old_occupied = old_cache_entry.get("occupied_hexes") if old_cache_entry else None

    if orientation is not None:
        unit["orientation"] = orientation
        cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
        if cache_entry is None:
            raise KeyError(f"units_cache missing moved unit {unit_id_str_cache}")
        cache_entry["orientation"] = orientation

    # Update units_cache after position change.
    # Use translate_squad_to_destination for rigid squad movement: anchor + all
    # surviving models translate by the same delta, occupied_hexes_by_model is
    # resync'd from updated models_cache. This is the move-action semantic.
    translate_squad_to_destination(game_state, unit_id_str_cache, dest_col_int, dest_row_int)

    # Retrieve new footprint from updated cache
    new_cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
    new_occupied = new_cache_entry.get("occupied_hexes") if new_cache_entry else None

    _mct3 = _mct.perf_counter() if _mct_pt else None

    # Keep enemy adjacency caches synchronized incrementally with the move.
    moved_unit_player = int(require_key(unit, "player"))
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_int,
        new_row=dest_row_int,
        old_occupied=old_occupied,
        new_occupied=new_occupied,
    )

    _mct4 = _mct.perf_counter() if _mct_pt else None

    # Apply AI_TURN.md tracking
    # Normalize unit ID to string for consistent storage (units_fled stores strings)
    unit_id_str = str(unit["id"])
    game_state["units_moved"].add(unit_id_str)
    # Source unique du marquage de fuite (partagée avec le commit par-figurine PvP).
    # units_fled est un sous-ensemble de units_moved.
    flee_action = finalize_flee_marking(game_state, unit_id_str, was_adjacent)

    # Invalidate LoS cache when unit moves
    # When a unit moves, all LoS calculations involving that unit are now invalid
    # This prevents "shoot through wall" bugs caused by stale cache
    from .shooting_handlers import _invalidate_los_cache_for_moved_unit
    _invalidate_los_cache_for_moved_unit(game_state, unit["id"], old_col=orig_col, old_row=orig_row)
    game_state["_unit_move_version"] += 1

    _mct5 = _mct.perf_counter() if _mct_pt else None
    if _mct_pt and _mct0 is not None and _mct1 is not None and _mct2_pre is not None and _mct2 is not None and _mct3 is not None and _mct4 is not None and _mct5 is not None:
        append_perf_timing_line(
            f"MOVE_COMMIT_TIMING episode={episode} turn={turn} unitId={unit_id_str!r} phase={phase} "
            f"occ_build_s={_mct1 - _mct0:.6f} eng_check_s={_mct2 - _mct2_pre:.6f} "
            f"pos_update_s={_mct3 - _mct2:.6f} adj_cache_s={_mct4 - _mct3:.6f} "
            f"los_cache_s={_mct5 - _mct4:.6f} total_s={_mct5 - _mct0:.6f}"
        )

    # Pools are invalidated at the START of the phase, not after each movement
    # This prevents invalidating the "moved" tracking of units that just moved

    # Log successful movement
    action_type = flee_action.upper()
    _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) SUCCESS {action_type}")

    # Use normalized coordinates (dest_col_int, dest_row_int) in result
    # NOT dest_col/dest_row which might not be normalized
    return True, {
        "action": flee_action,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col_int,  # Use normalized coordinates
        "toRow": dest_row_int    # Use normalized coordinates
    }


def _is_in_enemy_engagement_zone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md flee detection logic.

    Check if unit is adjacent to enemy for flee marking.

    Uses proper hexagonal distance, not Chebyshev distance.
    For CC_RNG=1 (typical), this means checking if enemy is in 6 neighbors.
    For CC_RNG>1, use hex distance calculation.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1.
    """
    unit_col, unit_row = require_unit_position(unit, game_state)

    unit_id_str = str(unit["id"])
    units_cache = require_key(game_state, "units_cache")
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    cache_key = f"enemy_adjacent_hexes_player_{int(require_key(unit, 'player'))}"
    enemy_adj = game_state.get(cache_key)

    result = _movement_engagement_violates(
        game_state,
        unit,
        unit_col,
        unit_row,
        unit_fp,
        units_cache,
        enemy_adj if isinstance(enemy_adj, set) else None,
    )
    
    # Log adjacency check result
    _log_movement_debug(game_state, "is_adjacent_to_enemy", str(unit["id"]), f"ADJACENT" if result else "NOT_ADJACENT")

    return result


def finalize_flee_marking(game_state: Dict[str, Any], squad_id: str, was_engaged: bool) -> str:
    """Source unique du marquage de fuite, partagée par les deux chemins de commit move :
    le move rigide à l'ancre (``_attempt_movement_to_destination``) et le commit du plan
    par-figurine PvP (``movement_commit_move_plan_handler``).

    ``was_engaged`` est détecté en amont sur les positions PRÉ-déplacement via
    ``_squad_is_in_enemy_er`` (≥ 1 figurine de l'escouade dans l'Engagement Range d'une
    figurine ennemie — règle 09.07, toutes figs). Si vrai, l'escouade est ajoutée à
    ``units_fled``. À appeler APRÈS un déplacement réussi.

    Retourne le libellé d'action : "flee" si fuite, sinon "move".
    """
    squad_id_str = str(squad_id)
    if was_engaged:
        game_state["units_fled"].add(squad_id_str)
    return "flee" if was_engaged else "move"


def _euclidean_mover_ez_forbidden_mask(
    unit: Dict[str, Any],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    board_cols: int,
    board_rows: int,
) -> "np.ndarray":
    """Masque EZ euclidien (Étape 7.2) — miroir vectorisé de ``entries_in_engagement_zone(euclidean)``.

    ``eng_bad[c, r]`` ⇔ placer l'ANCRE du mover en ``(c, r)`` met son socle à un écart bord-à-bord
    euclidien ≤ ``engagement_minimum_clearance_norm(ez)`` (= ez × 1,5) d'un socle ennemi.
    Sémantique identique à ``euclidean_edge_distance`` : paire ronde↔ronde = clearance continu
    exact (centre + rayon) ; sinon = min entre centres de cellules occupées. Vectorisé par disque
    NumPy borné en bbox par source (pas O(cellules × ennemis)).
    """
    from engine.hex_utils import (
        engagement_minimum_clearance_norm,
        round_base_radius_norm,
        precompute_footprint_offsets,
    )

    ez_norm = engagement_minimum_clearance_norm(ez)
    eng_bad = np.zeros((board_cols, board_rows), dtype=bool)
    enemy_list = enemy_items if enemy_items is not None else []
    if not enemy_list or ez_norm <= 0:
        return eng_bad

    # Grille des centres de cellules (repère _hex_center), vectorisée.
    _hw = 1.5
    _hh = math.sqrt(3.0)
    _cols = np.arange(board_cols, dtype=np.float64)
    _rows = np.arange(board_rows, dtype=np.float64)
    grid_x = (_cols * _hw + _hw / 2.0)[:, None] + np.zeros((1, board_rows))
    grid_y = _rows[None, :] * _hh + ((_cols[:, None].astype(np.int64) & 1) * _hh) / 2.0 + _hh / 2.0

    def _stamp_disc(dst: "np.ndarray", sc: int, sr: int, reach: float) -> None:
        if reach <= 0:
            return
        ex = sc * _hw + _hw / 2.0
        ey = sr * _hh + ((sc & 1) * _hh) / 2.0 + _hh / 2.0
        dcol = int(reach / _hw) + 1
        drow = int(reach / _hh) + 1
        c0, c1 = max(0, sc - dcol), min(board_cols, sc + dcol + 1)
        r0, r1 = max(0, sr - drow), min(board_rows, sr + drow + 1)
        if c0 >= c1 or r0 >= r1:
            return
        dx = grid_x[c0:c1, r0:r1] - ex
        dy = grid_y[c0:c1, r0:r1] - ey
        dst[c0:c1, r0:r1] |= (dx * dx + dy * dy) <= (reach * reach + 1e-9)

    mover_shape = unit["BASE_SHAPE"]
    mover_bs = unit["BASE_SIZE"]
    mover_round = mover_shape == "round"
    r_m = round_base_radius_norm(cast(float, mover_bs)) if mover_round else 0.0

    # Dispatch identique à euclidean_edge_distance : round↔round (les DEUX ronds) = clearance
    # continu exact (centre + rayons) ; toute paire impliquant un non-rond = min entre centres de
    # cellules d'empreinte (les deux socles en cellules). On accumule les cellules ennemies des
    # paires « cell-min » ; les paires round-round exactes tamponnent directement un disque.
    cell_sources: List[Tuple[int, int]] = []
    for _, ce in enemy_list:
        e_shape = require_key(ce, "BASE_SHAPE")
        e_bs = _require_footprint_base_size(
            e_shape, require_key(ce, "BASE_SIZE"), f"units_cache enemy {ce.get('id', '?')}"
        )
        by_model = ce.get("occupied_hexes_by_model")
        model_positions = list(by_model.values()) if by_model else [
            (int(require_key(ce, "col")), int(require_key(ce, "row")))
        ]
        if mover_round and e_shape == "round":
            r_e = round_base_radius_norm(cast(float, e_bs))
            for ec, er in model_positions:
                _stamp_disc(eng_bad, int(ec), int(er), ez_norm + r_m + r_e)
        else:
            e_orient = int(require_key(ce, "orientation"))
            e_off_even, e_off_odd = precompute_footprint_offsets(e_shape, e_bs, e_orient)
            for ec, er in model_positions:
                e_off = e_off_even if (int(ec) & 1) == 0 else e_off_odd
                for dc, dr in e_off:
                    cell_sources.append((int(ec) + int(dc), int(er) + int(dr)))

    if cell_sources:
        # Cellules-mover interdites (centre à ≤ ez_norm d'une cellule ennemie), puis dilatation par
        # l'empreinte du mover : ancre interdite ssi une de ses cellules l'est (min cellule↔cellule).
        cell_forbidden = np.zeros((board_cols, board_rows), dtype=bool)
        for sc, sr in cell_sources:
            _stamp_disc(cell_forbidden, sc, sr, ez_norm)
        mover_orient = int(require_key(unit, "orientation")) if "orientation" in unit else 0
        off_even, off_odd = precompute_footprint_offsets(mover_shape, mover_bs, mover_orient)
        col_even = (np.arange(board_cols, dtype=np.int64) & 1) == 0
        col_parity = np.broadcast_to(col_even[:, None], (board_cols, board_rows)).copy()
        for offs, use_even in ((off_even, True), (off_odd, False)):
            acc = np.zeros((board_cols, board_rows), dtype=bool)
            for dc, dr in offs:
                dc, dr = int(dc), int(dr)
                c_src_lo, c_src_hi = max(0, dc), board_cols - max(0, -dc)
                r_src_lo, r_src_hi = max(0, dr), board_rows - max(0, -dr)
                if c_src_lo >= c_src_hi or r_src_lo >= r_src_hi:
                    continue
                acc[c_src_lo - dc:c_src_hi - dc, r_src_lo - dr:r_src_hi - dr] |= cell_forbidden[
                    c_src_lo:c_src_hi, r_src_lo:r_src_hi
                ]
            eng_bad |= acc & (col_parity if use_even else ~col_parity)

    return eng_bad


def _compute_mover_ez_forbidden_mask(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    board_cols: int,
    board_rows: int,
) -> "np.ndarray":
    """Masque ``(board_cols, board_rows)`` des ancres dont le placement du mover viole l'EZ ennemie.

    Source UNIQUE de la géométrie d'engagement (Board ×N, ``ez > 1``), partagée par le path IA
    vectorisé (``_build_multi_hex_vectorized``) et le path PvP par-figurine
    (``movement_build_model_destinations_pool`` / voile rouge). Garantit IA == PvP.

    Sémantique (identique à ``move_anchor_violates_engagement_clearance``) :
      - Paire **mover rond ↔ ennemi rond** : écart bord à bord euclidien (centres ``_hex_center``)
        ≥ ``engagement_minimum_clearance_norm(ez)``.
      - Sinon (mover non-rond ou ennemi non-rond) : ``min_distance_between_sets(fp_mover, fp_enemy)
        ≤ ez`` — équivalent à l'intersection de l'empreinte du mover avec la dilatation hex de
        rayon ``ez`` des empreintes ennemies.

    ``eng_bad[c, r] == True`` ⇔ placer l'ANCRE du mover en ``(c, r)`` viole l'EZ (empreinte du
    mover déjà prise en compte). À tester au niveau ancre, ne PAS re-dilater par l'empreinte.

    Métrique (Étape 7) : ``engagement:"euclidean"`` → disque euclidien vectorisé
    (``_euclidean_mover_ez_forbidden_mask``) ; ``"hex"`` (défaut) → dilatation hex ci-dessous.
    """
    from engine.spatial_relations import engagement_distance_metric
    if engagement_distance_metric() == "euclidean":
        return _euclidean_mover_ez_forbidden_mask(unit, enemy_items, ez, board_cols, board_rows)

    from engine.hex_utils import (
        engagement_minimum_clearance_norm,
        round_base_radius_norm,
        _hex_center,
        precompute_footprint_offsets,
    )

    mover_shape = unit["BASE_SHAPE"]
    mover_bs_i = unit["BASE_SIZE"]
    if "orientation" in unit:
        mover_orient = int(require_key(unit, "orientation"))
    else:
        mover_orient = 0
    off_even, off_odd = precompute_footprint_offsets(mover_shape, mover_bs_i, mover_orient)
    off_even_arr = np.asarray(off_even, dtype=np.int64).reshape(-1, 2)
    off_odd_arr = np.asarray(off_odd, dtype=np.int64).reshape(-1, 2)

    col_is_even = (np.arange(board_cols, dtype=np.int64) & 1) == 0
    col_parity_mask = np.broadcast_to(
        col_is_even[:, None], (board_cols, board_rows)
    ).copy()

    def _dilate_by_kernel(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        out = np.zeros_like(src)
        if kernel.size == 0:
            return out
        for dc, dr in kernel:
            c_src_lo = max(0, int(dc))
            c_src_hi = board_cols - max(0, -int(dc))
            r_src_lo = max(0, int(dr))
            r_src_hi = board_rows - max(0, -int(dr))
            if c_src_lo >= c_src_hi or r_src_lo >= r_src_hi:
                continue
            c_dst_lo = c_src_lo - int(dc)
            c_dst_hi = c_src_hi - int(dc)
            r_dst_lo = r_src_lo - int(dr)
            r_dst_hi = r_src_hi - int(dr)
            out[c_dst_lo:c_dst_hi, r_dst_lo:r_dst_hi] |= src[
                c_src_lo:c_src_hi, r_src_lo:r_src_hi
            ]
        return out

    def _spread_by_kernel(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        out = np.zeros_like(src)
        for dc, dr in kernel:
            src_c_lo = max(0, -int(dc))
            src_c_hi = board_cols - max(0, int(dc))
            src_r_lo = max(0, -int(dr))
            src_r_hi = board_rows - max(0, int(dr))
            if src_c_lo >= src_c_hi or src_r_lo >= src_r_hi:
                continue
            dst_c_lo = src_c_lo + int(dc)
            dst_c_hi = src_c_hi + int(dc)
            dst_r_lo = src_r_lo + int(dr)
            dst_r_hi = src_r_hi + int(dr)
            out[dst_c_lo:dst_c_hi, dst_r_lo:dst_r_hi] |= src[
                src_c_lo:src_c_hi, src_r_lo:src_r_hi
            ]
        return out

    nb_even = np.asarray(
        [(0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1)], dtype=np.int64
    )
    nb_odd = np.asarray(
        [(0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)], dtype=np.int64
    )

    # Métrique d'engagement unifiée : empreinte hex uniquement (jamais euclidien).
    eng_bad = np.zeros((board_cols, board_rows), dtype=bool)
    enemy_list = enemy_items if enemy_items is not None else []

    hex_mixed_mask = np.zeros((board_cols, board_rows), dtype=bool)
    has_hex_mixed = False
    for _, ce in enemy_list:
        e_shape = require_key(ce, "BASE_SHAPE")
        e_bs = _require_footprint_base_size(
            e_shape,
            require_key(ce, "BASE_SIZE"),
            f"units_cache enemy {ce.get('id', '?')}",
        )
        by_model = ce.get("occupied_hexes_by_model")
        model_positions = list(by_model.values()) if by_model else [
            (int(require_key(ce, "col")), int(require_key(ce, "row")))
        ]
        e_orient = int(require_key(ce, "orientation"))
        e_off_even, e_off_odd = precompute_footprint_offsets(e_shape, e_bs, e_orient)
        for e_col, e_row in model_positions:
            e_off = e_off_even if (e_col & 1) == 0 else e_off_odd
            for dc, dr in e_off:
                fc = e_col + int(dc)
                fr = e_row + int(dr)
                if 0 <= fc < board_cols and 0 <= fr < board_rows:
                    hex_mixed_mask[fc, fr] = True
        has_hex_mixed = True

    if has_hex_mixed:
        # Dilatation hex (cube-distance) de rayon ``ez`` par propagation itérative par parité,
        # puis dilatation par l'empreinte du mover → ``min_distance_between_sets ≤ ez``.
        dilated = hex_mixed_mask.copy()
        for _ in range(int(ez)):
            even_src = dilated & col_parity_mask
            odd_src = dilated & ~col_parity_mask
            nxt = dilated | _spread_by_kernel(even_src, nb_even) | _spread_by_kernel(
                odd_src, nb_odd
            )
            if np.array_equal(nxt, dilated):
                break
            dilated = nxt
        eng_bad_even_mix = _dilate_by_kernel(dilated, off_even_arr)
        eng_bad_odd_mix = _dilate_by_kernel(dilated, off_odd_arr)
        eng_bad |= np.where(col_parity_mask, eng_bad_even_mix, eng_bad_odd_mix)

    return eng_bad


def _build_multi_hex_vectorized(
    *,
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    start_col: int,
    start_row: int,
    move_range: int,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    walls_set: Set[Tuple[int, int]],
    enemy_occupied_set: Set[Tuple[int, int]],
    occupied_set: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    thru_ez: bool,
    thru_enemy: bool,
    thru_friendly: bool,
    fly: bool = False,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int]:
    """BFS/disk multi-hex vectorisé NumPy (``ground`` et ``fly``). Gère toutes les formes de socles.

    Retourne ``(valid_destinations, footprint_zone, visited_count)``.

    Invariants de sémantique (équivalence stricte avec le BFS Python hex orig.) :

    - **Bounds + walls + traversée** : l'empreinte doit tenir dans le plateau et ne chevaucher
      aucun mur. Les figs ennemies (``thru_enemy``), amies (``thru_friendly``) et la bande d'EZ
      (``thru_ez``) ne bloquent la traversée que si le toggle config correspondant est ``False``.
    - **Engagement zone** (toujours exclue de la **destination**, ``valid_mask & ~eng_bad``) :
        * ``ez <= 1`` : ``enemy_adjacent_hexes`` déjà pré-dilaté par ``build_enemy_adjacent_hexes``.
          Une ancre viole l'engagement ssi une cellule de son empreinte est dans cet ensemble.
        * ``ez > 1`` (Board ×10) :
          - Paire **mover rond ↔ ennemi rond** : écart bord à bord euclidien (centres
            ``_hex_center``) ≥ ``engagement_minimum_clearance_norm(ez)``.
          - Sinon (mover non-rond ou ennemi non-rond) : ``min_distance_between_sets(fp_mover,
            fp_enemy) ≤ ez`` équivalent à ancre dont l'empreinte intersecte la dilatation hex
            de rayon ``ez`` de l'empreinte ennemie.
    - **Destinations** : traversable ET empreinte ne chevauchant aucune cellule d'``occupied_set``.
    - **Start** : l'ancre de départ est toujours atteinte mais exclue des destinations.
    - **Footprint zone** : union des empreintes (empreinte de départ + empreinte de chaque
      destination), identique à l'union calculée côté BFS Python.
    """
    import numpy as np

    off_even_arr = np.asarray(off_even, dtype=np.int64).reshape(-1, 2)
    off_odd_arr = np.asarray(off_odd, dtype=np.int64).reshape(-1, 2)

    col_is_even = (np.arange(board_cols, dtype=np.int64) & 1) == 0
    col_parity_mask = np.broadcast_to(
        col_is_even[:, None], (board_cols, board_rows)
    ).copy()

    def _dilate_by_kernel(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        """``out[c, r] = any_{(dc, dr) ∈ kernel} src[c+dc, r+dr]``.

        Boucle slices uniquement : ``scipy.ndimage.binary_dilation`` a provoqué des segfaults
        sur certains environnements (extensions natives / ``origin``), donc pas de chemin SciPy ici.
        """
        out = np.zeros_like(src)
        if kernel.size == 0:
            return out
        for dc, dr in kernel:
            c_src_lo = max(0, int(dc))
            c_src_hi = board_cols - max(0, -int(dc))
            r_src_lo = max(0, int(dr))
            r_src_hi = board_rows - max(0, -int(dr))
            if c_src_lo >= c_src_hi or r_src_lo >= r_src_hi:
                continue
            c_dst_lo = c_src_lo - int(dc)
            c_dst_hi = c_src_hi - int(dc)
            r_dst_lo = r_src_lo - int(dr)
            r_dst_hi = r_src_hi - int(dr)
            out[c_dst_lo:c_dst_hi, r_dst_lo:r_dst_hi] |= src[
                c_src_lo:c_src_hi, r_src_lo:r_src_hi
            ]
        return out

    def _spread_by_kernel(src: "np.ndarray", kernel: "np.ndarray") -> "np.ndarray":
        """``out[c+dc, r+dr] = any src[c, r]`` pour chaque ``(dc, dr) ∈ kernel``.

        Utilisé pour : propagation BFS (src → voisin = src + offset) ou union d’empreintes
        (ancre valide → cellules (c+dc, r+dr) de son empreinte).
        """
        out = np.zeros_like(src)
        for dc, dr in kernel:
            src_c_lo = max(0, -int(dc))
            src_c_hi = board_cols - max(0, int(dc))
            src_r_lo = max(0, -int(dr))
            src_r_hi = board_rows - max(0, int(dr))
            if src_c_lo >= src_c_hi or src_r_lo >= src_r_hi:
                continue
            dst_c_lo = src_c_lo + int(dc)
            dst_c_hi = src_c_hi + int(dc)
            dst_r_lo = src_r_lo + int(dr)
            dst_r_hi = src_r_hi + int(dr)
            out[dst_c_lo:dst_c_hi, dst_r_lo:dst_r_hi] |= src[
                src_c_lo:src_c_hi, src_r_lo:src_r_hi
            ]
        return out

    def _mask_from_cells(cells: Set[Tuple[int, int]]) -> "np.ndarray":
        m = np.zeros((board_cols, board_rows), dtype=bool)
        if not cells:
            return m
        cs = np.fromiter((c for c, _ in cells), dtype=np.int64, count=len(cells))
        rs = np.fromiter((r for _, r in cells), dtype=np.int64, count=len(cells))
        in_b = (cs >= 0) & (cs < board_cols) & (rs >= 0) & (rs < board_rows)
        m[cs[in_b], rs[in_b]] = True
        return m

    obstacles_dest_any = walls_set | occupied_set
    obstacles_dest_mask = _mask_from_cells(obstacles_dest_any)
    obstacles_traverse_mask: np.ndarray = obstacles_dest_mask
    if not fly:
        # Traversée selon toggles : murs toujours bloquants ; figs ennemies/amies selon config.
        obstacles_traverse = set(walls_set)
        if not thru_enemy:
            obstacles_traverse |= enemy_occupied_set
        if not thru_friendly:
            obstacles_traverse |= (occupied_set - enemy_occupied_set)
        obstacles_traverse_mask = _mask_from_cells(obstacles_traverse)

    def _bounds_bad_parity(offsets_arr: "np.ndarray") -> "np.ndarray":
        min_dc = int(offsets_arr[:, 0].min())
        max_dc = int(offsets_arr[:, 0].max())
        min_dr = int(offsets_arr[:, 1].min())
        max_dr = int(offsets_arr[:, 1].max())
        bad = np.ones((board_cols, board_rows), dtype=bool)
        c_lo = max(0, -min_dc)
        c_hi = min(board_cols, board_cols - max_dc)
        r_lo = max(0, -min_dr)
        r_hi = min(board_rows, board_rows - max_dr)
        if c_lo < c_hi and r_lo < r_hi:
            bad[c_lo:c_hi, r_lo:r_hi] = False
        return bad

    def _placement_bad(obstacles_mask: "np.ndarray") -> "np.ndarray":
        hit_even = _dilate_by_kernel(obstacles_mask, off_even_arr)
        hit_odd = _dilate_by_kernel(obstacles_mask, off_odd_arr)
        hit = np.where(col_parity_mask, hit_even, hit_odd)
        bounds_bad_even = _bounds_bad_parity(off_even_arr)
        bounds_bad_odd = _bounds_bad_parity(off_odd_arr)
        bounds_bad = np.where(col_parity_mask, bounds_bad_even, bounds_bad_odd)
        return hit | bounds_bad

    bad_dest = _placement_bad(obstacles_dest_mask)
    bad_traverse: np.ndarray = bad_dest
    if not fly:
        bad_traverse = _placement_bad(obstacles_traverse_mask)

    if ez > 1:
        # Géométrie d'engagement : source unique partagée avec le path PvP (garantit IA == PvP).
        eng_bad = _compute_mover_ez_forbidden_mask(
            game_state, unit, enemy_items, ez, board_cols, board_rows
        )
    elif ez == 1 and enemy_adjacent_hexes:
        enemy_adj_mask = _mask_from_cells(enemy_adjacent_hexes)
        eng_bad_even = _dilate_by_kernel(enemy_adj_mask, off_even_arr)
        eng_bad_odd = _dilate_by_kernel(enemy_adj_mask, off_odd_arr)
        eng_bad = np.where(col_parity_mask, eng_bad_even, eng_bad_odd)
    else:
        eng_bad = np.zeros((board_cols, board_rows), dtype=bool)

    if fly:
        # FLY: reachable = disque (aucun obstacle de traversée : FLY ignore murs/figs, Règles 21.03).
        if _move_distance_metric(game_state) == "euclidean":
            # Disque euclidien CENTRE-À-CENTRE (règle 03.01), budget × 1.5 — IDENTIQUE au model pool
            # par-fig (geodesic_field sans obstacle) → preview escouade == commit. Repère _hex_center
            # (hex_width = 1.5, hex_height = √3), sans arrondi.
            _hw = ENGAGEMENT_NORM_HEX_WIDTH
            _hh = 3.0 ** 0.5
            _cols_i = np.arange(board_cols, dtype=np.int64)[:, None]
            _cx = _cols_i.astype(np.float64) * _hw + _hw / 2.0
            _cy = (
                np.arange(board_rows, dtype=np.float64)[None, :] * _hh
                + (_cols_i & 1).astype(np.float64) * (_hh / 2.0)
                + _hh / 2.0
            )
            _sx = start_col * _hw + _hw / 2.0
            _sy = start_row * _hh + (start_col & 1) * (_hh / 2.0) + _hh / 2.0
            _dist = np.hypot(_cx - _sx, _cy - _sy)
            reach = _dist <= (move_range * _hw + _SEG_TOL)
        else:
            # hex (gym / move_gym) : disque cube-distance (comportement historique).
            cols_arr = np.arange(board_cols, dtype=np.int64)[:, None]
            rows_arr = np.arange(board_rows, dtype=np.int64)[None, :]
            x_c = cols_arr
            z_c = rows_arr - (cols_arr - (cols_arr & 1)) // 2
            y_c = -x_c - z_c
            sx_c = np.int64(start_col)
            sz_c = np.int64(start_row) - (np.int64(start_col) - (np.int64(start_col) & 1)) // 2
            sy_c = -sx_c - sz_c
            cube_d = np.maximum(np.abs(x_c - sx_c), np.maximum(np.abs(y_c - sy_c), np.abs(z_c - sz_c)))
            reach = cube_d <= np.int64(move_range)
        valid_mask = reach & ~bad_dest & ~eng_bad
    else:
        # EZ traversable selon toggle ; toujours exclue de la destination (unengaged 09.05).
        traverse_bad = bad_traverse if thru_ez else (bad_traverse | eng_bad)

        # Deque BFS : visite uniquement les ancres accessibles — O(reachable) au lieu de
        # O(move_range × board_cols × board_rows) pour le wavefront NumPy.
        # Sémantique identique : même ensemble d'ancres atteignables en ≤ move_range pas.
        # traverse_bad (précomputé par _placement_bad) converti en bytearray F-order pour
        # lookup O(1) cohérent avec l'index nc + nr * board_cols du BFS single-hex.
        _tb_flat = bytearray(traverse_bad.ravel(order='F').astype(np.uint8))

        reach = np.zeros((board_cols, board_rows), dtype=bool)
        reach[start_col, start_row] = True

        _vis_bfs = bytearray(board_cols * board_rows)
        _vis_bfs[start_col + start_row * board_cols] = 1

        _nb_even_t = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
        _nb_odd_t  = ((0, -1), (1, 0),  (1, 1), (0, 1), (-1, 1), (-1, 0))

        _bfs_queue = deque([(start_col, start_row, 0)])
        while _bfs_queue:
            cc, cr, cd = _bfs_queue.popleft()
            if cd >= move_range:
                continue
            nd = cd + 1
            nb_t = _nb_even_t if (cc & 1) == 0 else _nb_odd_t
            for dc, dr in nb_t:
                nc = cc + dc
                nr = cr + dr
                if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                    continue
                _vidx = nc + nr * board_cols
                if _vis_bfs[_vidx]:
                    continue
                if _tb_flat[_vidx]:
                    continue
                _vis_bfs[_vidx] = 1
                reach[nc, nr] = True
                _bfs_queue.append((nc, nr, nd))

        valid_mask = reach & ~bad_dest & ~eng_bad
    valid_mask[start_col, start_row] = False

    valid_coords_cols, valid_coords_rows = np.where(valid_mask)
    valid_destinations: List[Tuple[int, int]] = [
        (int(c), int(r)) for c, r in zip(valid_coords_cols, valid_coords_rows)
    ]

    fpz_even_mask = valid_mask & col_parity_mask
    fpz_odd_mask = valid_mask & ~col_parity_mask
    footprint_zone_mask = _spread_by_kernel(fpz_even_mask, off_even_arr) | _spread_by_kernel(
        fpz_odd_mask, off_odd_arr
    )
    start_offsets = off_even_arr if (start_col & 1) == 0 else off_odd_arr
    for dc, dr in start_offsets:
        fc = start_col + int(dc)
        fr = start_row + int(dr)
        if 0 <= fc < board_cols and 0 <= fr < board_rows:
            footprint_zone_mask[fc, fr] = True

    fpz_cols, fpz_rows = np.where(footprint_zone_mask)
    footprint_zone: Set[Tuple[int, int]] = {
        (int(c), int(r)) for c, r in zip(fpz_cols, fpz_rows)
    }

    visited_count = int(reach.sum())
    return valid_destinations, footprint_zone, visited_count


def _advance_roll_for(squad_id: str, game_state: Dict[str, Any]) -> Optional[int]:
    """Jet d'Advance de cette escouade pour le tour, sinon None.

    Source unique du « mode Advance » (Règles 09.06) : une escouade qui a déclaré Advance
    est dans ``units_advanced`` (persistant jusqu'à la phase de commandement suivante) et son
    jet est mémorisé dans ``advance_rolls`` (squad_id → jet). Tant qu'elle y est, les pools
    de destinations utilisent un budget M+jet, le mode survit aux cancel/ré-activations, et
    elle ne peut ni tirer ni charger. Le jet est figé (pas de re-roll).
    """
    if str(squad_id) not in game_state.get("units_advanced", set()):
        return None
    roll = game_state["advance_rolls"].get(str(squad_id))
    return int(roll) if roll is not None else None


def _get_move_traversal_rules(game_state: Dict[str, Any]) -> Tuple[bool, bool, bool]:
    """Lit les 3 toggles de traversée depuis ``config["move"]`` (Règles 03.01).

    Retourne ``(thru_ez, thru_enemy, thru_friendly)`` :
      - ``can_move_through_enemy_engagement_zone`` : traverser la bande d'EZ ennemie.
      - ``can_move_through_enemy_model`` : traverser une figurine ennemie.
      - ``can_move_through_friendly_model`` : traverser une figurine amie.

    Ces toggles ne concernent QUE la traversée (pathfinding). Finir son move sur une case
    occupée ou dans l'EZ ennemie reste toujours interdit (occupation 03.01 / unengaged 09.05),
    indépendamment de ces valeurs. Pas de défaut : clé manquante = erreur explicite.
    """
    config = require_key(game_state, "config")
    move_rules = require_key(config, "move")
    return (
        bool(require_key(move_rules, "can_move_through_enemy_engagement_zone")),
        bool(require_key(move_rules, "can_move_through_enemy_model")),
        bool(require_key(move_rules, "can_move_through_friendly_model")),
    )


def _move_distance_metric(game_state: Dict[str, Any]) -> str:
    """Métrique de distance du MOVE (``hex``|``euclidean``) — sélecteur unique.

    Contexte : PvP/replay lisent ``distance_metric["move"]`` ; le training gym lit
    ``distance_metric["move_gym"]`` (le paramètre unique qui bascule le training, défaut
    ``hex`` pour la perf). Aucun défaut caché : section/clé/valeur invalide → erreur explicite.
    """
    from config_loader import get_config_loader
    from engine.combat_utils import VALID_DISTANCE_METRICS

    game_config = get_config_loader().get_game_config()
    if "distance_metric" not in game_config:
        raise KeyError("Missing 'distance_metric' section in game_config.json")
    metrics = game_config["distance_metric"]
    key = "move_gym" if game_state.get("gym_training_mode") else "move"
    if key not in metrics:
        raise KeyError(f"Missing distance_metric['{key}'] in game_config.json")
    metric = metrics[key]
    if metric not in VALID_DISTANCE_METRICS:
        raise ValueError(
            f"Invalid distance_metric['{key}'] = {metric!r}, expected one of {VALID_DISTANCE_METRICS}"
        )
    return metric


def _euclidean_ground_anchor_multihex(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    start_col: int,
    start_row: int,
    start_pos: Tuple[int, int],
    move_range: int,
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    walls: Set[Tuple[int, int]],
    occupied: Set[Tuple[int, int]],
    enemy_occupied: Set[Tuple[int, int]],
    enemy_adjacent_hexes: Set[Tuple[int, int]],
    enemy_items: Optional[List[Tuple[Any, Any]]],
    ez: int,
    thru_ez: bool,
    thru_enemy: bool,
    thru_friendly: bool,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int]:
    """Pool d'ancre GROUND euclidien multi-hex (preview escouade), miroir du model pool par-fig.

    Champ géodésique du centre de l'ancre (round: clearance continue ; non-round: empreinte
    discrète), puis filtre de destination sur l'empreinte COMPLÈTE (murs/occupé/EZ), identique
    au model pool → preview == commit. L'EZ suit les deux régimes existants :
    ``ez > 1`` testée sur l'ancre (le masque intègre déjà l'empreinte du mover) ;
    ``ez <= 1`` (legacy) dilatée par l'empreinte via ``enemy_adjacent_hexes``.
    """
    import numpy as np
    if ez > 1:
        _ez_mask = _compute_mover_ez_forbidden_mask(
            game_state, unit, enemy_items, ez, board_cols, board_rows
        )
        _ec, _er = np.where(_ez_mask)
        ez_forbidden: Set[Tuple[int, int]] = {(int(c), int(r)) for c, r in zip(_ec, _er)}
        dest_blocked_fp = walls | occupied           # EZ testée sur l'ancre (ci-dessous)
        ez_anchor_check = ez_forbidden
    else:
        ez_forbidden = enemy_adjacent_hexes
        dest_blocked_fp = walls | occupied | enemy_adjacent_hexes  # EZ dilatée par l'empreinte
        ez_anchor_check = set()

    obstacles_tr: Set[Tuple[int, int]] = set(walls)
    if not thru_enemy:
        obstacles_tr |= enemy_occupied
    if not thru_friendly:
        obstacles_tr |= (occupied - enemy_occupied)
    if not thru_ez:
        obstacles_tr |= ez_forbidden
    obstacles_tr.discard(start_pos)

    field = _euclidean_move_field(
        start_pos, base_shape, base_size, off_even, off_odd,
        obstacles_tr, board_cols, board_rows, move_range * ENGAGEMENT_NORM_HEX_WIDTH,
    )

    valid_destinations: List[Tuple[int, int]] = []
    footprint_zone: Set[Tuple[int, int]] = set()
    for _ac, _ar in field:
        if (_ac, _ar) == start_pos or (_ac, _ar) in ez_anchor_check:
            continue
        offs = off_even if (_ac & 1) == 0 else off_odd
        if any(
            not (0 <= _ac + _dc < board_cols and 0 <= _ar + _dr < board_rows)
            for _dc, _dr in offs
        ):
            continue
        if any((_ac + _dc, _ar + _dr) in dest_blocked_fp for _dc, _dr in offs):
            continue
        valid_destinations.append((_ac, _ar))
        for _dc, _dr in offs:
            footprint_zone.add((_ac + _dc, _ar + _dr))
    _s_offs = off_even if (start_col & 1) == 0 else off_odd
    for _dc, _dr in _s_offs:
        footprint_zone.add((start_col + _dc, start_row + _dr))
    footprint_zone -= walls
    return valid_destinations, footprint_zone, len(field)


@profile_move_pool_build
def movement_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str, read_only: bool = False) -> List[Tuple[int, int]]:
    """
    Build valid movement destinations using BFS pathfinding.

    ``read_only=True`` : calcule et RENVOIE la liste des destinations sans écrire le moindre
    état preview dans ``game_state`` (pool / footprint_zone / span / border / mask_loops). Utilisé
    par ``get_eligible_units`` comme oracle fall-back (source unique = ce builder, zéro divergence).

    Uses BFS to find REACHABLE hexes, not just hexes within distance.
    This prevents movement through walls (AI_TURN.md compliance).

    Pre-computes enemy adjacent hexes and occupied positions once at BFS start for O(1) lookups.

    Ground (non-Fly): la traversée suit les toggles ``config["move"]`` (``_get_move_traversal_rules``) :
    figs ennemies (``can_move_through_enemy_model``), amies (``can_move_through_friendly_model``)
    et bande d'EZ (``can_move_through_enemy_engagement_zone``) ne bloquent le pas du BFS que si
    le toggle est ``False``. La destination, elle, ne peut JAMAIS finir sur une case occupée
    (03.01) ni dans l'EZ ennemie (unengaged, 09.05), quels que soient les toggles.

    Fly: exploration ignores walls and occupation along the path; walls, occupation and engagement
    are enforced on the destination footprint only (see fly branch below).
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _pt = perf_timing_enabled(game_state)
    import time as _perf_clock

    _m0 = _perf_clock.perf_counter() if _pt else None

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    _adv_roll = _advance_roll_for(str(unit_id), game_state)
    if _adv_roll is not None:
        move_range = get_squad_move_budget(str(unit_id), game_state, "advance", advance_roll=_adv_roll)
    else:
        # Normal/fall-back via budget unique : applique aussi le malus Take to the skies (-2", Règles 21.03).
        move_range = get_squad_move_budget(str(unit_id), game_state, "normal")
    # Normalize coordinates to int - raises error if invalid
    start_col, start_row = require_unit_position(unit, game_state)
    start_pos = (start_col, start_row)

    # Use cached enemy_adjacent_hexes from phase start
    # Cache is built once per phase in movement_phase_start()/shooting_phase_start()/charge_phase_start()
    # This reduces O(n) per hex check to O(1) set lookup
    current_player = require_key(game_state, "current_player")
    if current_player is None:
        raise KeyError("game_state missing required 'current_player' field")
    
    # Cache must exist (no fallback) - raise error if missing
    cache_key = f"enemy_adjacent_hexes_player_{current_player}"
    if cache_key not in game_state:
            raise KeyError(f"enemy_adjacent_hexes cache missing for player {current_player} - build_enemy_adjacent_hexes() must be called at phase start")
    enemy_adjacent_hexes = game_state[cache_key]

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    current_player_int = int(current_player)
    enemy_occupied = build_enemy_occupied_positions_set(
        game_state, current_player=current_player_int
    )
    units_cache = require_key(game_state, "units_cache")
    ez = get_engagement_zone(game_state)
    _thru_ez, _thru_enemy, _thru_friendly = _get_move_traversal_rules(game_state)
    _mover_player_int = int(require_key(unit, "player"))
    # ez > 1 : une seule liste d’ennemis pour ``_movement_engagement_violates`` (évite O(units)×BFS).
    _enemy_items_for_engagement_ez: Optional[List[Tuple[Any, Any]]] = None
    if ez > 1:
        _enemy_items_for_engagement_ez = _enemy_items_within_move_engagement_horizon(
            game_state,
            unit,
            unit_id_str,
            _mover_player_int,
            start_col,
            start_row,
            int(move_range),
            units_cache,
        )

    if game_state.get("debug_mode", False) and "episode_number" in game_state and "turn" in game_state:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        total_units = len(units_cache)
        from engine.game_utils import add_console_log, safe_print
        log_msg = f"[OCCUPIED_POSITIONS] E{episode} T{turn} Unit {unit['id']}: total={total_units}, occupied_cells={len(occupied_positions)}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    # Generic cache-coherence diagnostics (debug mode only):
    # compare precomputed enemy adjacency cache vs. fresh reconstruction from units_cache.
    if game_state.get("debug_mode", False):
        expected_enemy_adjacent_hexes: Set[Tuple[int, int]] = set()
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        current_player_int = int(current_player)
        for enemy_id, enemy_entry in units_cache.items():
            enemy_player_raw = require_key(enemy_entry, "player")
            enemy_player_int = int(enemy_player_raw)
            if enemy_player_int == current_player_int:
                continue
            enemy_hp = require_key(enemy_entry, "HP_CUR")
            if enemy_hp <= 0:
                continue
            enemy_col, enemy_row = enemy_entry["col"], enemy_entry["row"]
            for neighbor_col, neighbor_row in get_hex_neighbors(enemy_col, enemy_row):
                if (
                    neighbor_col < 0
                    or neighbor_row < 0
                    or neighbor_col >= board_cols
                    or neighbor_row >= board_rows
                ):
                    continue
                expected_enemy_adjacent_hexes.add((neighbor_col, neighbor_row))

        cache_missing = expected_enemy_adjacent_hexes - enemy_adjacent_hexes
        cache_extra = enemy_adjacent_hexes - expected_enemy_adjacent_hexes
        if cache_missing or cache_extra:
            # TEMPORARY LOG: diagnostic for stale enemy adjacency cache investigation.
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            max_examples = 8
            missing_examples = sorted(cache_missing)[:max_examples]
            extra_examples = sorted(cache_extra)[:max_examples]
            add_debug_file_log(
                game_state,
                f"[TEMPORARY LOG][MOVE CACHE MISMATCH] E{episode} T{turn} Unit {unit_id}: "
                f"player={current_player_int} "
                f"cached={len(enemy_adjacent_hexes)} expected={len(expected_enemy_adjacent_hexes)} "
                f"missing={len(cache_missing)} extra={len(cache_extra)} "
                f"missing_examples={missing_examples} extra_examples={extra_examples}",
            )

    _m_prep_end = _perf_clock.perf_counter() if _pt else None

    # Take to the skies (Règles 21.03) : en phase move, une unité FLY ne traverse murs/figurines
    # QUE si le joueur a déclaré le vol. Logique partagée via _fly_traversal_active.
    _fly_active = _fly_traversal_active(game_state, unit, unit_id)

    # FLY units: BFS ignoring walls/occupation for traversal.
    # Only destination validation checks walls, occupation and engagement zone.
    # This replaces the O(cols×rows) scan with O(reachable) BFS.
    if _fly_active:
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        fly_visited_n = 0
        valid_destinations: List[Tuple[int, int]] = []
        fly_rejected_footprint = 0

        _fly_bcols = board_cols
        _fly_brows = board_rows
        _fly_walls = game_state.get("wall_hexes", set())
        _fly_occupied = occupied_positions

        _fly_base_size = unit["BASE_SIZE"]
        _fly_single_hex = (ez <= 1 or _fly_base_size == 1)

        _fly_off_even: Tuple[Tuple[int, int], ...] = ()
        _fly_off_odd: Tuple[Tuple[int, int], ...] = ()
        if not _fly_single_hex:
            from engine.hex_utils import precompute_footprint_offsets
            _fly_shape = unit["BASE_SHAPE"]
            if "orientation" in unit:
                _fly_orient = int(require_key(unit, "orientation"))
            else:
                _fly_orient = 0
            _fly_off_even, _fly_off_odd = precompute_footprint_offsets(
                _fly_shape, _fly_base_size, _fly_orient
            )

        # Multi-hex FLY: vectorized NumPy path (cube-distance disk + destination filter).
        if not _fly_single_hex:
            _m_bfs_start = _perf_clock.perf_counter() if _pt else None
            valid_destinations, _fly_fp_zone_vec, fly_visited_n = _build_multi_hex_vectorized(
                fly=True,
                game_state=game_state,
                unit=unit,
                start_col=start_col,
                start_row=start_row,
                move_range=move_range,
                off_even=_fly_off_even,
                off_odd=_fly_off_odd,
                board_cols=board_cols,
                board_rows=board_rows,
                walls_set=_fly_walls,
                enemy_occupied_set=set(),
                occupied_set=occupied_positions,
                enemy_adjacent_hexes=enemy_adjacent_hexes,
                enemy_items=_enemy_items_for_engagement_ez,
                ez=ez,
                thru_ez=_thru_ez,
                thru_enemy=_thru_enemy,
                thru_friendly=_thru_friendly,
            )
            _m_bfs_end = _perf_clock.perf_counter() if _pt else None
            if read_only:
                return valid_destinations
            game_state["valid_move_destinations_pool"] = valid_destinations
            game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)
            if game_state.get("gym_training_mode"):
                _fly_fp_zone: Set[Tuple[int, int]] = set()
            else:
                _fly_fp_zone = _fly_fp_zone_vec
            game_state["move_preview_footprint_zone"] = _fly_fp_zone
            game_state["move_preview_border"] = []
            _m_fly_before_sync = _perf_clock.perf_counter() if _pt else None
            if not game_state.get("gym_training_mode"):
                _sync_move_preview_mask_loops(game_state, _fly_fp_zone)
            _m_fly_done = _perf_clock.perf_counter() if _pt else None
            if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_fly_before_sync is not None and _m_fly_done is not None:
                _post_bfs = _m_fly_done - _m_bfs_end
                _fu = _m_fly_before_sync - _m_bfs_end
                _ml = _m_fly_done - _m_fly_before_sync
                append_perf_timing_line(
                    f"MOVE_POOL_BUILD unit={unit_id} fly=True prep_s={_m_prep_end - _m0:.6f} "
                    f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
                    f"footprint_union_s={_fu:.6f} mask_loops_s={_ml:.6f} "
                    f"total_s={_m_fly_done - _m0:.6f} visited={fly_visited_n} valid={len(valid_destinations)} "
                    f"anchors_n={len(valid_destinations)} footprint_hex_n={len(_fly_fp_zone)} "
                    f"MOVE={move_range}"
                )
            _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)} [FLY vectorized]")
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                add_debug_file_log(
                    game_state,
                    f"[MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id} [FLY vectorized]: "
                    f"start=({start_col},{start_row}) move_range={move_range} "
                    f"visited={fly_visited_n} valid={len(valid_destinations)} "
                    f"reject_footprint=0",
                )
            return valid_destinations

        # Precompute per-enemy proximity thresholds to skip engagement check for distant hexes.
        _fly_enemy_proximity_filter: Optional[List[Tuple[int, int, int]]] = None
        _fly_ez_prox_set: Optional[Set[Tuple[int, int]]] = None
        if ez > 1 and _enemy_items_for_engagement_ez is not None:
            from engine.hex_utils import dilate_hex_set as _dilate_hex_set
            _fly_mover_r = _hex_radius_upper_for_engagement_prune(_move_preview_footprint_span(unit))
            _fly_ez_i = int(ez)
            _fly_prox_list: List[Tuple[int, int, int]] = []
            for _, _fce in _enemy_items_for_engagement_ez:
                _fec = int(require_key(_fce, "col"))
                _fer = int(require_key(_fce, "row"))
                _fe_r = _hex_radius_upper_for_engagement_prune(_move_preview_footprint_span(_fce))
                _fly_prox_list.append((_fec, _fer, _fly_ez_i + _fly_mover_r + _fe_r + 1))
            _fly_enemy_proximity_filter = _fly_prox_list
            _fly_ez_prox_set = set()
            for _fec, _fer, _feth in _fly_prox_list:
                _fly_ez_prox_set |= _dilate_hex_set({(_fec, _fer)}, _feth, _fly_bcols, _fly_brows)
                _fly_ez_prox_set.add((_fec, _fer))

        _m_bfs_start = _perf_clock.perf_counter() if _pt else None
        _sx = start_col
        _sz = start_row - ((start_col - (start_col & 1)) >> 1)
        for _dx in range(-move_range, move_range + 1):
            _dy_lo = max(-move_range, -move_range - _dx)
            _dy_hi = min(move_range, move_range - _dx) + 1
            for _dy in range(_dy_lo, _dy_hi):
                nc = _sx + _dx
                nr = (_sz - _dx - _dy) + ((nc - (nc & 1)) >> 1)
                if nc < 0 or nr < 0 or nc >= _fly_bcols or nr >= _fly_brows:
                    continue
                nb = (nc, nr)
                if nb == start_pos:
                    continue
                fly_visited_n += 1
                if nb in _fly_walls or nb in _fly_occupied:
                    fly_rejected_footprint += 1
                else:
                    if _fly_ez_prox_set is not None and nb not in _fly_ez_prox_set:
                        valid_destinations.append(nb)
                    elif not _movement_engagement_violates(
                        game_state,
                        unit,
                        nc,
                        nr,
                        {(nc, nr)},
                        units_cache,
                        enemy_adjacent_hexes if ez <= 1 else None,
                        enemy_cache_items=_enemy_items_for_engagement_ez,
                        engagement_zone_ez=ez,
                    ):
                        valid_destinations.append(nb)
                    else:
                        fly_rejected_footprint += 1
        _m_bfs_end = _perf_clock.perf_counter() if _pt else None
        if read_only:
            return valid_destinations
        game_state["valid_move_destinations_pool"] = valid_destinations
        game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)
        if game_state.get("gym_training_mode"):
            _fly_fp_zone: Set[Tuple[int, int]] = set()
        elif _fly_single_hex:
            _fly_fp_zone = set(valid_destinations)
            _fly_fp_zone.add(start_pos)
        else:
            _fly_fp_zone = set()
            for vc, vr in valid_destinations:
                _offs = _fly_off_even if (vc & 1) == 0 else _fly_off_odd
                for dc, dr in _offs:
                    _fly_fp_zone.add((vc + dc, vr + dr))
            _start_offs = _fly_off_even if (start_pos[0] & 1) == 0 else _fly_off_odd
            for dc, dr in _start_offs:
                _fly_fp_zone.add((start_pos[0] + dc, start_pos[1] + dr))
        game_state["move_preview_footprint_zone"] = _fly_fp_zone
        # Non sérialisé (exclu API) ; la preview repose sur footprint_zone / mask_loops.
        game_state["move_preview_border"] = []
        _m_fly_before_sync = _perf_clock.perf_counter() if _pt else None
        if not game_state.get("gym_training_mode"):
            _sync_move_preview_mask_loops(game_state, _fly_fp_zone)
        _m_fly_done = _perf_clock.perf_counter() if _pt else None
        if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_fly_before_sync is not None and _m_fly_done is not None:
            _post_bfs = _m_fly_done - _m_bfs_end
            _fu = _m_fly_before_sync - _m_bfs_end
            _ml = _m_fly_done - _m_fly_before_sync
            append_perf_timing_line(
                f"MOVE_POOL_BUILD unit={unit_id} fly=True prep_s={_m_prep_end - _m0:.6f} "
                f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
                f"footprint_union_s={_fu:.6f} mask_loops_s={_ml:.6f} "
                f"total_s={_m_fly_done - _m0:.6f} visited={fly_visited_n} valid={len(valid_destinations)} "
                f"anchors_n={len(valid_destinations)} footprint_hex_n={len(_fly_fp_zone)} "
                f"MOVE={move_range}"
            )
        _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)} [FLY BFS]")
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_file_log(
                game_state,
                f"[MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id} [FLY BFS]: "
                f"start=({start_col},{start_row}) move_range={move_range} "
                f"visited={fly_visited_n} valid={len(valid_destinations)} "
                f"reject_footprint={fly_rejected_footprint}",
            )
        return valid_destinations

    # Pre-extract constants for the BFS hot loop (avoid repeated dict lookups)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes_set = game_state.get("wall_hexes", set())
    base_size = unit["BASE_SIZE"]
    is_single_hex = (ez <= 1 or base_size == 1)

    # Étape 4.1 : champ géodésique euclidien (any-angle) LIMITÉ au socle rond mono-hex
    # (base_size == 1), ground. Multi-hex / non-rond / fly restent sur le BFS hex → Étape 4b.
    # PvP/replay lisent ``move`` (euclidean) ; gym lit ``move_gym`` (défaut hex).
    _use_euclidean_move = (
        _move_distance_metric(game_state) == "euclidean"
        and base_size == 1
        and unit["BASE_SHAPE"] == "round"
    )

    # Grille dense O(1) : même sémantique que ``dict`` (case visitée ou non pour ce BFS).
    _n_cells = board_cols * board_rows
    _vis = bytearray(_n_cells)
    _vis[start_col + start_row * board_cols] = 1
    visited_n = 1
    queue = deque([(start_pos, 0)])
    valid_destinations: List[Tuple[int, int]] = []
    blocked_enemy_adjacent_count = 0
    footprint_zone: Set[Tuple[int, int]] = set()
    _off_even: Tuple[Tuple[int, int], ...] = ()
    _off_odd: Tuple[Tuple[int, int], ...] = ()

    _occupied = occupied_positions
    _enemy_occ = enemy_occupied
    _walls = wall_hexes_set
    _enemy_adj = enemy_adjacent_hexes
    _bcols = board_cols
    _brows = board_rows

    # Toggles de traversée (config["move"]). La destination exclut toujours occupé + EZ.
    _check_enemy = not _thru_enemy
    _check_friendly = not _thru_friendly
    _check_ez = not _thru_ez
    _friendly_occ = (_occupied - _enemy_occ) if _check_friendly else frozenset()

    _m_bfs_start = _perf_clock.perf_counter() if _pt else None
    if is_single_hex and _use_euclidean_move:
        # Champ géodésique any-angle. Obstacles = murs + (ennemis/amis/bande-EZ selon toggles) ;
        # option A (Minkowski) : clearance = rayon du socle → le trajet du centre borne la
        # distance de TOUT point du socle (règle 03). Overlap/EZ de destination restent hex.
        _obstacles: Set[Tuple[int, int]] = set(_walls)
        if _check_enemy:
            _obstacles |= _enemy_occ
        if _check_friendly:
            _obstacles |= _friendly_occ
        if _check_ez:
            _obstacles |= _enemy_adj
        _obstacles.discard(start_pos)  # on est déjà sur la case de départ
        _budget_norm = move_range * ENGAGEMENT_NORM_HEX_WIDTH
        _clearance = round_base_radius_norm(base_size)
        _field = geodesic_field(start_pos, _bcols, _brows, _obstacles, _budget_norm, _clearance)
        visited_n = len(_field)
        for _cell in _field:
            # Destination jamais sur case occupée (03.01) ni dans l'EZ ennemie (unengaged 09.05),
            # quels que soient les toggles de traversée — identique au BFS hex.
            if _cell == start_pos or _cell in _occupied or _cell in _enemy_adj:
                continue
            valid_destinations.append(_cell)
    elif is_single_hex:
        while queue:
            (cc, cr), cd = queue.popleft()
            if cd >= move_range:
                continue
            nd = cd + 1
            parity = cc & 1
            if parity == 0:
                nb_list = (
                    (cc, cr - 1), (cc + 1, cr - 1), (cc + 1, cr),
                    (cc, cr + 1), (cc - 1, cr), (cc - 1, cr - 1),
                )
            else:
                nb_list = (
                    (cc, cr - 1), (cc + 1, cr), (cc + 1, cr + 1),
                    (cc, cr + 1), (cc - 1, cr + 1), (cc - 1, cr),
                )
            for nb in nb_list:
                nc, nr = nb
                if nc < 0 or nr < 0 or nc >= _bcols or nr >= _brows:
                    continue
                _vidx = nc + nr * board_cols
                if _vis[_vidx]:
                    continue
                if nb in _walls:
                    continue
                if _check_enemy and nb in _enemy_occ:
                    continue
                if _check_friendly and nb in _friendly_occ:
                    continue
                if _check_ez and nb in _enemy_adj:
                    blocked_enemy_adjacent_count += 1
                    continue
                _vis[_vidx] = 1
                visited_n += 1
                queue.append((nb, nd))
                # Traversal selon toggles ; la destination ne peut jamais finir sur une case
                # occupée (03.01) ni dans l'EZ ennemie (unengaged, 09.05).
                if nb != start_pos and nb not in _occupied and nb not in _enemy_adj:
                    valid_destinations.append(nb)
    else:
        # Multi-hex units: pre-compute footprint offsets ONCE, then translate
        from engine.hex_utils import precompute_footprint_offsets
        base_shape = unit["BASE_SHAPE"]
        if "orientation" in unit:
            orientation = int(require_key(unit, "orientation"))
        else:
            orientation = 0
        _off_even, _off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)

        if _move_distance_metric(game_state) == "euclidean":
            # Ground multi-hex euclidien (preview escouade) — miroir du model pool par-fig
            # (round: clearance continue ; non-round: empreinte discrète). Le gym (move_gym=hex)
            # garde le chemin vectorisé hex ci-dessous.
            valid_destinations, footprint_zone, visited_n = _euclidean_ground_anchor_multihex(
                game_state, unit, start_col, start_row, start_pos, move_range,
                base_shape, base_size, _off_even, _off_odd,
                _bcols, _brows, _walls, _occupied, _enemy_occ, _enemy_adj,
                _enemy_items_for_engagement_ez, ez, _thru_ez, _thru_enemy, _thru_friendly,
            )
        else:
            # Chemin unique vectorisé NumPy, sémantiquement équivalent au BFS Python hexagonal.
            # Gère toutes les formes de socles (mover et ennemis) et toutes les valeurs de ``ez``.
            valid_destinations, footprint_zone, visited_n = _build_multi_hex_vectorized(
                game_state=game_state,
                unit=unit,
                start_col=start_col,
                start_row=start_row,
                move_range=move_range,
                off_even=_off_even,
                off_odd=_off_odd,
                board_cols=_bcols,
                board_rows=_brows,
                walls_set=_walls,
                enemy_occupied_set=_enemy_occ,
                occupied_set=_occupied,
                enemy_adjacent_hexes=_enemy_adj,
                enemy_items=_enemy_items_for_engagement_ez,
                ez=ez,
                thru_ez=_thru_ez,
                thru_enemy=_thru_enemy,
                thru_friendly=_thru_friendly,
            )

    _m_bfs_end = _perf_clock.perf_counter() if _pt else None

    # Bornage rigide d'escouade : une ancre n'est valide que si TOUTES les figs vivantes
    # restent dans le plateau après translation rigide (delta = dest_ancre - ancre_origine).
    # Borne les CENTRES des figs (même définition de "hors board" que validate_move_plan).
    # N'affecte PAS footprint_zone (calculé séparément côté multi-hex) → la zone reste
    # complète, donc inZone ne rétrécit pas et le ghost PvP ne blink pas au bord.
    if not is_single_hex:
        _sq_entry = units_cache.get(unit_id_str)
        _by_model = _sq_entry.get("occupied_hexes_by_model") if _sq_entry else None
        if _by_model:
            _fc = [int(c) for c, _ in _by_model.values()]
            _fr = [int(r) for _, r in _by_model.values()]
            _min_fc, _max_fc = min(_fc), max(_fc)
            _min_fr, _max_fr = min(_fr), max(_fr)
            # Enveloppe d'empreinte (socle multi-hex) sur les DEUX parités : garantit qu'aucune
            # cellule de l'empreinte d'aucune fig ne déborde, quelle que soit la parité de la
            # colonne de destination (qui peut flipper avec delta_col).
            _foff_c = [int(c) for c, _ in _off_even] + [int(c) for c, _ in _off_odd]
            _foff_r = [int(r) for _, r in _off_even] + [int(r) for _, r in _off_odd]
            _fc_off_min, _fc_off_max = min(_foff_c), max(_foff_c)
            _fr_off_min, _fr_off_max = min(_foff_r), max(_foff_r)
            _lo_c = start_col - _min_fc - _fc_off_min
            _hi_c = start_col + (board_cols - 1) - _max_fc - _fc_off_max
            _lo_r = start_row - _min_fr - _fr_off_min
            _hi_r = start_row + (board_rows - 1) - _max_fr - _fr_off_max
            valid_destinations = [
                (c, r)
                for (c, r) in valid_destinations
                if _lo_c <= c <= _hi_c and _lo_r <= r <= _hi_r
            ]

    if read_only:
        return valid_destinations

    game_state["valid_move_destinations_pool"] = valid_destinations
    game_state["move_preview_footprint_span"] = _move_preview_footprint_span(unit)

    if is_single_hex:
        footprint_zone = set(valid_destinations)
        footprint_zone.add(start_pos)

    game_state["move_preview_footprint_zone"] = footprint_zone
    game_state["move_preview_border"] = []
    _m_ground_before_sync = _perf_clock.perf_counter() if _pt else None
    if not game_state.get("gym_training_mode"):
        _sync_move_preview_mask_loops(game_state, footprint_zone)
    _m_ground_done = _perf_clock.perf_counter() if _pt else None
    if _pt and _m0 is not None and _m_prep_end is not None and _m_bfs_start is not None and _m_bfs_end is not None and _m_ground_before_sync is not None and _m_ground_done is not None:
        _fp_n = len(_off_even) if not is_single_hex else 1
        _post_bfs = _m_ground_done - _m_bfs_end
        _fu = _m_ground_before_sync - _m_bfs_end
        _ml = _m_ground_done - _m_ground_before_sync
        append_perf_timing_line(
            f"MOVE_POOL_BUILD unit={unit_id} fly=False single_hex={is_single_hex} prep_s={_m_prep_end - _m0:.6f} "
            f"bfs_s={_m_bfs_end - _m_bfs_start:.6f} post_bfs_s={_post_bfs:.6f} "
            f"footprint_union_s={_fu:.6f} mask_loops_s={_ml:.6f} "
            f"total_s={_m_ground_done - _m0:.6f} visited={visited_n} valid={len(valid_destinations)} "
            f"anchors_n={len(valid_destinations)} footprint_hex_n={len(footprint_zone)} "
            f"MOVE={move_range} base={base_size} fp={_fp_n}"
        )

    _log_movement_debug(game_state, "build_valid_destinations", str(unit_id), f"valid_destinations count={len(valid_destinations)}")
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        add_debug_file_log(
            game_state,
            f"[TEMPORARY LOG][MOVE POOL SUMMARY] E{episode} T{turn} Unit {unit_id}: "
            f"start=({start_col},{start_row}) move_range={move_range} "
            f"visited={visited_n} valid={len(valid_destinations)} "
            f"blocked_enemy_adjacent={blocked_enemy_adjacent_count}",
        )

    return valid_destinations


def movement_build_model_destinations_pool(
    game_state: Dict[str, Any],
    model_id: str,
    provisional_plan: Optional[Dict[str, Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """BFS des hexes atteignables pour UNE figurine (move par-figurine, squad.md).

    provisional_plan : {model_id: (col, row)} positions provisoires des figs
    déjà déplacées dans le plan. Si fourni, remplace models_cache pour les
    sibling figures (évite que les hexes originaux restent bloqués).

    Move normal : budget = MOVE de l'escouade (subhexes). Origine = position
    courante de la figurine dans models_cache (= position de debut de phase, car
    les moves par-figurine ne sont pas committes avant Validate).

    Sol (non-Fly) : ne traverse jamais un mur ; les figs ennemies, amies et la bande
    d'engagement ennemie ne bloquent la traversee que selon les toggles config["move"]
    (_get_move_traversal_rules). Desperate Escape (09.07) traverse les figs ennemies.
    Fly : traversal libre, seule la destination est validee.

    Destination retenue selon les memes regles que validate_move_plan (1 fig,
    sans coherency) : dans le plateau, hors mur, hors collision avec une AUTRE
    escouade, hors zone d'engagement ennemie. Les overlaps avec une coequipiere
    sont geres par preview_move_plan sur le plan complet. Lecture pure.

    Retourne {"destinations": [...], "footprint_mask_loops": [...]}.
    """
    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(
            f"movement_build_model_destinations_pool: model {model_id} not in models_cache"
        )
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    if not unit:
        return {"destinations": [], "footprint_mask_loops": []}

    _adv_roll = _advance_roll_for(squad_id, game_state)
    if _adv_roll is not None:
        budget = get_squad_move_budget(squad_id, game_state, "advance", advance_roll=_adv_roll)
    else:
        budget = get_squad_move_budget(squad_id, game_state, "normal")
    start_col = int(model["col"])
    start_row = int(model["row"])
    start_pos = (start_col, start_row)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    player = int(model["player"])
    cache_key = f"enemy_adjacent_hexes_player_{player}"
    enemy_adjacent_hexes = require_key(game_state, cache_key)
    enemy_occupied = build_enemy_occupied_positions_set(game_state, current_player=player)

    # Cellules occupees par les AUTRES escouades (collision destination interdite).
    other_occupied: Set[Tuple[int, int]] = set()
    for sid, entry in game_state.get("units_cache", {}).items():  # get allowed
        if str(sid) == squad_id:  # get allowed
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            for cell in occ:
                other_occupied.add((int(cell[0]), int(cell[1])))

    # Cellules occupees par les AUTRES figs du meme squad (collision intra-squad interdite).
    # provisional_plan override les positions sibling déjà déplacées dans le plan UI.
    same_squad_occupied: Set[Tuple[int, int]] = set()
    _models_cache = require_key(game_state, "models_cache")
    _squad_models = game_state.get("squad_models", {})  # get allowed
    for mid in _squad_models.get(squad_id, []):  # get allowed
        if str(mid) == str(model_id):  # get allowed
            continue
        if provisional_plan and str(mid) in provisional_plan:
            prov_col, prov_row = provisional_plan[str(mid)]
            sibling_fp = _compute_unit_occupied_hexes(prov_col, prov_row, unit, game_state)
        else:
            sibling = _models_cache.get(str(mid))
            if sibling is None:
                continue
            sibling_fp = _compute_unit_occupied_hexes(
                int(sibling["col"]), int(sibling["row"]), unit, game_state
            )
        same_squad_occupied.update(sibling_fp)

    # Take to the skies (Règles 21.03) : traversée FLY active seulement si vol déclaré (phase move,
    # humain) — sinon BFS sol. Pilote le reachable par-figurine ET, via lui, la validation au commit.
    has_fly = _fly_traversal_active(game_state, unit, squad_id)

    # Desperate Escape : unité battle-shocked tentant un fall-back depuis l'ER ennemie.
    # Les figurines peuvent traverser les positions ennemies (règle 09.07).
    desperate_escape = (
        unit.get("battle_shocked", False)
        and _squad_is_in_enemy_er(game_state, squad_id)
    )

    # Zone d'engagement ennemie au niveau ANCRE.
    # ez > 1 (Board ×N) : géométrie euclidienne par-mover, source unique partagée avec le path IA
    #   (``_compute_mover_ez_forbidden_mask``) → garantit IA == PvP. L'empreinte du mover est déjà
    #   prise en compte dans le masque, donc l'EZ se teste sur l'ancre et N'EST PAS re-dilatée par
    #   l'empreinte plus bas (``dest_blocked`` ne contient que la géométrie).
    # ez <= 1 (legacy) : dilatation hex pré-calculée (``enemy_adjacent_hexes``), traitée comme la
    #   géométrie (dilatée par l'empreinte dans le filtre multi-hex) — comportement inchangé.
    ez = get_engagement_zone(game_state)
    thru_ez, thru_enemy, thru_friendly = _get_move_traversal_rules(game_state)
    if ez > 1:
        import numpy as np
        units_cache = require_key(game_state, "units_cache")
        _enemy_items_ez = _enemy_items_within_move_engagement_horizon(
            game_state, unit, squad_id, player, start_col, start_row, int(budget), units_cache
        )
        _ez_mask = _compute_mover_ez_forbidden_mask(
            game_state, unit, _enemy_items_ez, ez, board_cols, board_rows
        )
        _ez_cols, _ez_rows = np.where(_ez_mask)
        ez_anchor_forbidden: Set[Tuple[int, int]] = {
            (int(c), int(r)) for c, r in zip(_ez_cols, _ez_rows)
        }
        dest_blocked = wall_hexes | other_occupied | same_squad_occupied
    else:
        ez_anchor_forbidden = enemy_adjacent_hexes
        dest_blocked = wall_hexes | other_occupied | same_squad_occupied | enemy_adjacent_hexes

    # Traversée selon toggles config["move"]. Desperate Escape (09.07) traverse les figs ennemies
    # quoi qu'il arrive. La destination (dest_blocked + ez_anchor_forbidden) reste inchangée :
    # jamais sur une case occupée, jamais dans l'EZ ennemie.
    _friendly_traverse = (
        (other_occupied | same_squad_occupied) - enemy_occupied
        if not thru_friendly
        else frozenset()
    )

    # Étape 4.1 — miroir par-figurine (PvP interactif) : champ géodésique euclidien du CENTRE de
    # l'ancre (règle 03.01), toutes formes. Rond → clearance continue = rayon socle (option A) ;
    # non-rond → empreinte discrète orientée (cf. _euclidean_move_field). L'empreinte multi-hex est
    # expansée + re-filtrée séparément plus bas. Mêmes obstacles de traversée que le BFS hex.
    # FLY (Règles 21.03) : euclidien aussi, mais champ SANS obstacle (ignore murs/figs) → le champ
    # géodésique dégénère en disque euclidien centre-à-centre (ligne droite, règle 03.01).
    _mm_base = require_key(model, "BASE_SIZE")
    _mm_shape = require_key(model, "BASE_SHAPE")
    _mm_use_euclidean = _move_distance_metric(game_state) == "euclidean"
    # Instrumentation perf (coût nul si W40K_PERF_TIMING désactivé) — cf. MODEL_POOL_BUILD au return.
    from engine.perf_timing import perf_timing_enabled
    import time as _mm_clock
    _mm_pt = perf_timing_enabled(game_state)
    _mm_t0 = _mm_clock.perf_counter() if _mm_pt else None
    _mm_field_s = 0.0
    _mm_cache_hit = False
    _mm_cells_n = 0
    _mm_obstacles_n = 0
    if _mm_use_euclidean:
        # Cache du CHAMP (sans les filtres de destination) : valide tant que les obstacles ne
        # changent pas. Les sœurs ne sont des obstacles que si NON thru_friendly → cache seulement
        # sûr quand thru_friendly (sinon le champ dépend du plan provisoire, recalcul obligatoire).
        # FLY : le champ n'a aucun obstacle → indépendant du plan provisoire → toujours cacheable.
        _mm_can_cache = thru_friendly or has_fly
        _mm_cache: Dict[Tuple[str, int, int, int], Dict[Tuple[int, int], float]] = game_state.setdefault(
            "_move_model_field_cache", {}
        )
        _mm_key: Tuple[str, int, int, int] = (str(model_id), start_col, start_row, int(budget))
        _mm_field = _mm_cache.get(_mm_key) if _mm_can_cache else None
        _mm_cache_hit = _mm_field is not None
        if _mm_field is None:
            if has_fly:
                # FLY ignore murs/figurines en traversée → aucun obstacle. Les filtres de
                # destination (occupé / EZ ennemie) restent appliqués plus bas, comme le BFS hex.
                _mm_obstacles: Set[Tuple[int, int]] = set()
            else:
                _mm_obstacles = set(wall_hexes)
                if not (desperate_escape or thru_enemy):
                    _mm_obstacles |= enemy_occupied
                if not thru_friendly:
                    _mm_obstacles |= _friendly_traverse
                if not (desperate_escape or thru_ez):
                    _mm_obstacles |= ez_anchor_forbidden
            _mm_obstacles.discard(start_pos)  # on est déjà sur la case de départ
            _mm_obstacles_n = len(_mm_obstacles)
            if _mm_shape == "round":
                _mm_off_even_f: Tuple[Tuple[int, int], ...] = ()
                _mm_off_odd_f: Tuple[Tuple[int, int], ...] = ()
            else:
                from engine.hex_utils import precompute_footprint_offsets
                _mm_off_even_f, _mm_off_odd_f = precompute_footprint_offsets(
                    _mm_shape, _mm_base, int(unit.get("orientation", 0)),  # get allowed
                )
            _mm_fb = _mm_clock.perf_counter() if _mm_pt else None
            _mm_field = _euclidean_move_field(
                start_pos, _mm_shape, _mm_base, _mm_off_even_f, _mm_off_odd_f,
                _mm_obstacles, board_cols, board_rows, budget * ENGAGEMENT_NORM_HEX_WIDTH,
            )
            if _mm_pt and _mm_fb is not None:
                _mm_field_s = _mm_clock.perf_counter() - _mm_fb
            if _mm_cache is not None and _mm_key is not None:
                _mm_cache[_mm_key] = _mm_field
        _mm_cells_n = len(_mm_field)
        # Filtres de destination appliqués À CHAQUE appel (dépendent du plan provisoire via
        # dest_blocked=same_squad) : jamais sur case occupée/mur ni dans l'EZ — identique au BFS hex.
        reachable: List[Tuple[int, int]] = [
            cell
            for cell in _mm_field
            if cell != start_pos and cell not in dest_blocked and cell not in ez_anchor_forbidden
        ]
    else:
        visited: Set[Tuple[int, int]] = {start_pos}
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
                if cell in visited:
                    continue
                if not has_fly:
                    if cell in wall_hexes:
                        continue
                    if not (desperate_escape or thru_enemy) and cell in enemy_occupied:
                        continue
                    if not thru_friendly and cell in _friendly_traverse:
                        continue
                    if not (desperate_escape or thru_ez) and cell in ez_anchor_forbidden:
                        continue
                visited.add(cell)
                queue.append((nc, nr, d + 1))
                # Validite destination : murs + toutes figs occupant la cellule + engagement ennemi
                # (ez_anchor_forbidden = EZ au niveau ancre).
                if cell in dest_blocked or cell in ez_anchor_forbidden:
                    continue
                reachable.append(cell)

    # Empêche le DÉPÔT sur un chevauchement de socle avec une coéquipière (au lieu de le
    # détecter après coup via le voile rouge) : on retire du pool les destinations où le socle
    # du mover chevaucherait une fig sœur, en clearance euclidienne par base RÉELLE — même
    # primitive (footprints_overlap) que movement_preview_move_plan → pool et voile cohérents.
    # Tangence (gap≈0) tolérée. dest_blocked (footprint hex) sous-estime le disque et laissait
    # passer ~16% de recouvrement à 5 sous-hex ; ce filtre le supprime à la source.
    from engine.hex_utils import Socle, footprints_overlap
    _mover_shape = require_key(model, "BASE_SHAPE")
    _mover_base = require_key(model, "BASE_SIZE")
    _mover_orient = int(unit.get("orientation", 0))  # get allowed
    _sibling_socles: List[Socle] = []
    for _sid_m in _squad_models.get(squad_id, []):  # get allowed
        if str(_sid_m) == str(model_id):  # get allowed
            continue
        _sib = models_cache.get(str(_sid_m))  # get allowed
        if _sib is None:
            continue
        if provisional_plan and str(_sid_m) in provisional_plan:
            _sc, _sr = int(provisional_plan[str(_sid_m)][0]), int(provisional_plan[str(_sid_m)][1])
        else:
            _sc, _sr = int(_sib["col"]), int(_sib["row"])
        _s_shape = require_key(_sib, "BASE_SHAPE")
        _s_base = require_key(_sib, "BASE_SIZE")
        _s_fp = None if _s_shape == "round" else compute_candidate_footprint(
            _sc, _sr,
            {"BASE_SHAPE": _s_shape, "BASE_SIZE": _s_base, "orientation": _mover_orient},
            game_state,
        )
        _sibling_socles.append(Socle(shape=_s_shape, base_size=_s_base, col=_sc, row=_sr, fp=_s_fp))
    if _sibling_socles:
        _intra_filtered: List[Tuple[int, int]] = []
        for _dc, _dr in reachable:
            _m_fp = None if _mover_shape == "round" else compute_candidate_footprint(
                _dc, _dr,
                {"BASE_SHAPE": _mover_shape, "BASE_SIZE": _mover_base, "orientation": _mover_orient},
                game_state,
            )
            _m_socle = Socle(shape=_mover_shape, base_size=_mover_base, col=_dc, row=_dr, fp=_m_fp)
            if not any(footprints_overlap(_m_socle, _s) for _s in _sibling_socles):
                _intra_filtered.append((_dc, _dr))
        reachable = _intra_filtered

    # Footprint zone per-fig : destinations ∪ start, expandées selon BASE_SIZE.
    base_size = unit["BASE_SIZE"]
    base_shape = unit["BASE_SHAPE"]
    orientation = unit.get("orientation", 0)  # get allowed
    # Non-rond (oval/square) → toujours multi-hex (base_size liste) : sans le garde de forme,
    # ``not isinstance(base_size, int)`` le classait à tort en single-hex → empreinte non expansée.
    is_single_hex = base_shape == "round" and (
        base_size == 1 or not isinstance(base_size, int) or base_size <= 1
    )  # get allowed
    if is_single_hex:
        footprint_zone: Set[Tuple[int, int]] = set(reachable)
        footprint_zone.add(start_pos)
    else:
        from engine.hex_utils import precompute_footprint_offsets
        off_even, off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)
        # Fix fonctionnel : exclure les destinations dont l'empreinte complète
        # chevauche dest_blocked (murs, figs alliées, figs ennemies, engagement).
        # Le BFS ne vérifie que le hex central ; ici on vérifie chaque cellule de l'empreinte.
        valid_reachable: List[Tuple[int, int]] = []
        for ac, ar in reachable:
            offs = off_even if (ac & 1) == 0 else off_odd
            # Empreinte complète dans le plateau : le BFS ne borne que le centre,
            # une cellule d'empreinte hors board n'est dans aucun set bloquant.
            if any(
                not (0 <= ac + dc < board_cols and 0 <= ar + dr < board_rows)
                for dc, dr in offs
            ):
                continue
            if not any((ac + dc, ar + dr) in dest_blocked for dc, dr in offs):
                valid_reachable.append((ac, ar))
        reachable = valid_reachable
        # Footprint zone depuis les destinations valides uniquement.
        footprint_zone = set()
        for ac, ar in reachable:
            offs = off_even if (ac & 1) == 0 else off_odd
            for dc, dr in offs:
                footprint_zone.add((ac + dc, ar + dr))
        s_offs = off_even if (start_col & 1) == 0 else off_odd
        for dc, dr in s_offs:
            footprint_zone.add((start_col + dc, start_row + dr))
        # Fix visuel : l'expansion du start peut déborder sur des murs adjacents.
        footprint_zone -= wall_hexes

    # Calcul mask loops sans ecriture permanente dans game_state.
    _prev_loops = game_state.get("move_preview_footprint_mask_loops")
    _sync_move_preview_mask_loops(game_state, footprint_zone)
    mask_loops = game_state.get("move_preview_footprint_mask_loops", [])  # get allowed
    game_state["move_preview_footprint_mask_loops"] = _prev_loops  # get allowed

    if _mm_pt and _mm_t0 is not None:
        from engine.perf_timing import append_perf_timing_line
        append_perf_timing_line(
            f"MODEL_POOL_BUILD model={model_id} metric={'euclidean' if _mm_use_euclidean else 'hex'} "
            f"cache_hit={_mm_cache_hit} field_build_s={_mm_field_s:.6f} total_s={_mm_clock.perf_counter() - _mm_t0:.6f} "
            f"field_cells={_mm_cells_n} reachable={len(reachable)} obstacles={_mm_obstacles_n} "
            f"base={_mm_base} budget={budget} fly={has_fly}"
        )

    return {"destinations": reachable, "footprint_mask_loops": mask_loops}


def movement_preview_move_plan(
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[str, int, int]]
) -> Dict[str, Any]:
    """Dry-run d'un plan provisoire par-figurine (move normal). Aucune ecriture.

    ``plan`` doit contenir TOUTES les figurines vivantes de l'escouade (sinon le
    test de cohesion est fausse).

    Voile rouge d'une fig = elle est sur un hex INTERDIT (mur, EZ ennemie, overlap
    avec une autre escouade ou une coequipiere, hors budget) OU hors COHESION 2"
    (moins du nb requis de voisins dans la distance de cohesion). En single-fig move
    le pool empeche deja les hex interdits → seul le cas cohesion survient ; en drop
    d'escouade rigide une fig peut tomber sur un hex interdit → voile rouge.

    Retourne :
      - per_model: {model_id: bool} — True = fig valide (placement legal ET cohesion).
        False => voile rouge cote UI.
      - coherency_ok: bool — cohesion respectee sur l'ensemble du plan.
      - can_validate: bool — toutes les figs valides (placement + cohesion).
    """
    _adv_roll = _advance_roll_for(str(squad_id), game_state)
    if _adv_roll is not None:
        budget = get_squad_move_budget(str(squad_id), game_state, "advance", advance_roll=_adv_roll)
    else:
        budget = get_squad_move_budget(str(squad_id), game_state, "normal")
    ez = get_engagement_zone(game_state)
    unit_obj = get_unit_by_id(game_state, str(squad_id))
    c_individual = {"budget_per_model": budget, "require_coherency": False}
    if ez > 1:
        # Board ×N : l'EZ est vérifiée ci-dessous par la formule euclidienne par-mover
        # (``_movement_engagement_violates``, même géométrie que le pathfinding → IA == PvP).
        # On désactive le check legacy centre-à-centre de ``validate_move_plan``.
        c_individual["forbid_enemy_er"] = False
    # Cohesion 03.03 par fig : deleguee a coherency_violation_flags (source UNIQUE partagee avec le
    # commit), qui respecte game_rules.cohesion_distance_mode (euclidean | footprint).
    positions: List[Tuple[int, int]] = [(int(nc), int(nr)) for _, nc, nr in plan]
    n = len(positions)

    # Calcul des empreintes par fig
    from engine.hex_utils import precompute_footprint_offsets as _pfo
    units_cache = game_state.get("units_cache", {})  # get allowed
    unit_entry = units_cache.get(str(squad_id), {})  # get allowed
    base_shape = require_key(unit_entry, "BASE_SHAPE")  # get allowed
    base_size = require_key(unit_entry, "BASE_SIZE")
    orientation = int(unit_entry.get("orientation", 0))  # get allowed
    is_single_hex = not isinstance(base_size, int) or base_size <= 1  # get allowed
    if is_single_hex:
        footprints: List[Set[Tuple[int, int]]] = [{pos} for pos in positions]
    else:
        _off_even, _off_odd = _pfo(base_shape, base_size, orientation)
        footprints = []
        for col, row in positions:
            offs = _off_even if (col & 1) == 0 else _off_odd
            footprints.append({(col + dc, row + dr) for dc, dr in offs})

    _mc_coh = require_key(game_state, "models_cache")
    cohesion_models = [
        {**_mc_coh[str(mid)], "col": int(nc), "row": int(nr)} for mid, nc, nr in plan
    ]
    cohesion_red = coherency_violation_flags(cohesion_models, game_state)

    wall_hexes_set = game_state.get("wall_hexes", set())
    other_occ_set: Set[Tuple[int, int]] = set()
    for sid, entry in units_cache.items():
        if str(sid) == str(squad_id):
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            for cell in occ:
                other_occ_set.add((int(cell[0]), int(cell[1])))

    # Collision intra-escouade : clearance EUCLIDIENNE par-figurine (≠ intersection de
    # footprints hex, qui sous-estime le disque et laisse passer un chevauchement de socle
    # ~16% à 5 sous-hex d'écart). Socle construit avec la base RÉELLE de chaque fig
    # (models_cache) → un Captain (base 8) parmi des Intercessors (base 6) n'est plus
    # sous-estimé. Tangence (gap≈0) tolérée, superposition stricte interdite.
    from engine.hex_utils import Socle, footprints_overlap
    _models_cache_intra = require_key(game_state, "models_cache")
    intra_socles: List["Socle"] = []
    for (mid, nc, nr), fp_par in zip(plan, footprints):
        m = require_key(_models_cache_intra, str(mid))
        m_shape = require_key(m, "BASE_SHAPE")
        m_base = require_key(m, "BASE_SIZE")
        if m_shape == base_shape and m_base == base_size:
            m_fp = fp_par
        else:
            m_fp = compute_candidate_footprint(
                int(nc), int(nr),
                {"BASE_SHAPE": m_shape, "BASE_SIZE": m_base, "orientation": orientation},
                game_state,
            )
        intra_socles.append(
            Socle(shape=m_shape, base_size=m_base, col=int(nc), row=int(nr), fp=m_fp)
        )

    per_model: Dict[str, bool] = {}
    for idx, (mid, nc, nr) in enumerate(plan):
        base_valid = validate_move_plan(
            [(str(mid), int(nc), int(nr))], game_state, c_individual
        )
        fp = footprints[idx]
        fp_wall = bool(wall_hexes_set and fp & wall_hexes_set)
        fp_other = bool(other_occ_set and fp & other_occ_set)
        fp_intra = any(
            footprints_overlap(intra_socles[idx], intra_socles[j])
            for j in range(n)
            if j != idx
        )
        # Board ×N : voile rouge si l'empreinte de la fig viole l'EZ ennemie (formule euclidienne
        # par-mover, identique au pathfinding). ez <= 1 : déjà couvert par validate_move_plan.
        ez_violation = (
            ez > 1
            and unit_obj is not None
            and _movement_engagement_violates(
                game_state, unit_obj, int(nc), int(nr), fp, units_cache,
                None, enemy_cache_items=None, engagement_zone_ez=ez,
            )
        )
        per_model[str(mid)] = bool(
            base_valid and not fp_wall and not fp_other and not fp_intra
            and not cohesion_red[idx] and not ez_violation
        )

    coherency_ok = not any(cohesion_red)
    all_valid = len(per_model) > 0 and all(per_model.values())
    # would_flee : l escouade est-elle actuellement engagee (positions PRE-move) ? Si oui,
    # tout commit sera un Fall Back => badge fui sur le ghost de preview. Independant du plan
    # (meme primitive bord-a-bord que le commit, cf was_engaged dans le handler de commit).
    would_flee = _squad_is_in_enemy_er(game_state, str(squad_id))
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
        "would_flee": bool(would_flee),
    }


def movement_commit_move_plan_handler(
    game_state: Dict[str, Any], squad_id: str, action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Valide (= bouton Validate) puis commit un plan provisoire par-figurine.

    ``action["plan"]`` : liste de ``[model_id, col, row]``, DOIT couvrir toutes
    les figurines vivantes de l'escouade (sinon la cohesion est fausse). Move
    normal ou fall_back selon engagement de l'escouade au moment du commit.

    Note brique 1 : aucun reactive move n'est declenche ici (move par-figurine) —
    a ajouter dans une tranche ulterieure si necessaire.
    """
    if "plan" not in action:
        raise KeyError(f"commit_move_plan action missing required 'plan' field: {action}")
    raw_plan = action["plan"]
    if not isinstance(raw_plan, list) or not raw_plan:
        return False, {"error": "empty_move_plan", "unitId": squad_id}
    plan: List[Tuple[str, int, int]] = []
    for entry in raw_plan:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3):
            raise ValueError(
                f"commit_move_plan: plan entry must be [model_id, col, row], got {entry!r}"
            )
        plan.append((str(entry[0]), int(entry[1]), int(entry[2])))

    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    alive = {m for m in squad_models.get(str(squad_id), []) if m in models_cache}  # get allowed
    plan_ids = {mid for mid, _, _ in plan}  # get allowed
    if plan_ids != alive:
        return False, {
            "error": "plan_models_mismatch",
            "unitId": squad_id,
            "expected": sorted(alive),
            "got": sorted(plan_ids),
        }

    # Validation = MEME regle que le voile rouge du preview (placement par-fig +
    # cohesion par composantes connexes). Coherent avec ce que l'UI affiche.
    preview = movement_preview_move_plan(game_state, str(squad_id), plan)
    if not preview["can_validate"]:
        return False, {
            "error": "invalid_move_plan",
            "unitId": squad_id,
            "per_model": preview["per_model"],
            "coherency_ok": preview["coherency_ok"],
        }

    # Desperate Escape (09.07) : le hazard est désormais résolu à l'ACTIVATION (action
    # hazard_confirm), plus au commit. Ici on commit un Fall Back déjà autorisé.
    was_engaged = _squad_is_in_enemy_er(game_state, str(squad_id))

    _adv_roll = _advance_roll_for(str(squad_id), game_state)
    if _adv_roll is not None:
        move_type = "advance"
    else:
        move_type = "fall_back" if was_engaged else "normal"

    # Snapshot par-figurine + ancre AVANT le commit, pour le log de mouvement
    # (moveDetails : depart -> arrivee de chaque figurine, expand/collapse cote GameLog).
    _uc_before = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if _uc_before is None:  # get allowed
        raise KeyError(f"units_cache missing squad {squad_id} before move commit")
    orig_anchor_col = int(_uc_before["col"])
    orig_anchor_row = int(_uc_before["row"])
    models_before = {
        mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"]))
        for mid in alive
    }

    commit_move(plan, game_state, move_type)

    unit = get_unit_by_id(game_state, squad_id)
    if not unit:
        return False, {"error": "unit_not_found", "unitId": squad_id}
    # Sync ancre de la liste units sur l'ancre recalculee dans units_cache
    # (commit_move ne touche que models_cache/units_cache).
    entry = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if entry is not None:  # get allowed
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))

    # Log de mouvement par-figurine (modele de la charge, sans roll sauf advance).
    # Ligne unite = message ancre ; detail expand/collapse = moveDetails par figurine.
    dest_anchor_col, dest_anchor_row = require_unit_position(unit, game_state)
    move_details = []
    for mid, nc, nr in plan:
        _fc, _fr = models_before[mid]
        move_details.append(
            {
                "modelId": mid,
                "fromCol": _fc,
                "fromRow": _fr,
                "toCol": int(nc),
                "toRow": int(nr),
            }
        )
    _ut_seg = f" {unit['unitType']}" if unit.get("unitType") else ""
    if move_type == "advance":
        action_name = "ADVANCED"
        was_flee = False
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} ADVANCED from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row}) [Advance:{_adv_roll}]"
        )
    elif move_type == "fall_back":
        action_name = "FLED"
        was_flee = True
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} FLED from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row})"
        )
    else:
        action_name = "MOVE"
        was_flee = False
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} MOVED from ({orig_anchor_col},{orig_anchor_row}) "
            f"to ({dest_anchor_col},{dest_anchor_row})"
        )
    append_action_log(
        game_state,
        {
            "type": "move",
            "message": movement_message,
            "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
            "phase": "move",
            "unitId": unit["id"],
            "player": unit["player"],
            "fromCol": orig_anchor_col,
            "fromRow": orig_anchor_row,
            "toCol": dest_anchor_col,
            "toRow": dest_anchor_row,
            "was_flee": was_flee,
            "timestamp": "server_time",
            "action_name": action_name,
            "reward": 0.0,
            "is_ai_action": unit["player"] == 2,
            "moveDetails": move_details,
        },
    )

    _invalidate_all_destination_pools_after_movement(game_state)
    movement_clear_preview(game_state)

    # Source unique du marquage de fuite (partagée avec le move rigide à l'ancre) :
    # marque units_fled + libellé "flee" si l'escouade était engagée avant le commit.
    flee_action = finalize_flee_marking(game_state, str(squad_id), was_engaged)

    result = end_activation(game_state, unit, ACTION, 1, MOVE, MOVE, 1)
    result.update(
        {
            "action": flee_action,
            "unitId": unit["id"],
            "activation_complete": True,
            "waiting_for_player": False,
            "reset_mode": "select",
            "clear_selected_unit": True,
        }
    )
    return True, result


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
        strategy_id: 0=aggressive, 1=tactical, 2=defensive, 3=objective
        valid_destinations: List of valid (col, row) tuples from BFS
        unit: Unit dict with position and stats
        game_state: Full game state for enemy detection

    Returns:
        Selected destination (col, row)
    """
    from engine.utils.weapon_helpers import get_max_ranged_range

    # Direct field access with validation
    if "units" not in game_state:
        raise KeyError("game_state missing required 'units' field")
    if "col" not in unit or "row" not in unit:
        raise KeyError(f"Unit missing required position fields: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_RNG
    if not unit.get("RNG_WEAPONS") and not unit.get("CC_WEAPONS"):
        raise KeyError(f"Unit missing required 'RNG_WEAPONS' or 'CC_WEAPONS' field: {unit}")

    # If no destinations, return current position
    if not valid_destinations:
        return require_unit_position(unit, game_state)

    # Get enemy units (units_cache = source of truth for living units)
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    enemy_units = [enemy_id for enemy_id, cache_entry in units_cache.items()
                   if int(cache_entry["player"]) != unit_player]

    # If no enemies, just pick first destination
    if not enemy_units:
        return valid_destinations[0]

    # Pre-extract enemy anchor positions once — O(1) per enemy, O(1) distance checks below.
    # Using anchor-to-anchor distance (centre hex) instead of footprint-to-footprint BFS:
    # for round units, footprint distance = centre_distance - r_mover - r_enemy, so the
    # constant offset doesn't change which destination ranks best. Valid for RL heuristics.
    from engine.combat_utils import calculate_hex_distance as _chd
    enemy_anchors = [
        (int(units_cache[str(eid)]["col"]), int(units_cache[str(eid)]["row"]))
        for eid in enemy_units
    ]

    # STRATEGY 0: AGGRESSIVE - Move closest to nearest enemy
    # O(m + n): find nearest enemy to current position, then pick destination closest to it.
    if strategy_id == 0:
        unit_col, unit_row = int(unit["col"]), int(unit["row"])
        nearest_ec, nearest_er = min(enemy_anchors, key=lambda e: _chd(unit_col, unit_row, e[0], e[1]))
        return min(valid_destinations, key=lambda d: _chd(d[0], d[1], nearest_ec, nearest_er))

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    # O(k × m) with k ≤ _MAX_TACTICAL_POOL to cap cost on large destination sets.
    elif strategy_id == 1:
        _MAX_TACTICAL_POOL = 400
        candidates = valid_destinations
        if len(candidates) > _MAX_TACTICAL_POOL:
            step = len(candidates) // _MAX_TACTICAL_POOL
            candidates = candidates[::step]
        weapon_range = get_max_ranged_range(unit)
        best_dest = candidates[0]
        max_targets = 0
        for dest in candidates:
            targets_in_range = sum(
                1 for ec, er in enemy_anchors
                if _chd(dest[0], dest[1], ec, er) <= weapon_range
            )
            if targets_in_range > max_targets:
                max_targets = targets_in_range
                best_dest = dest
        return best_dest

    # STRATEGY 2: DEFENSIVE - Move farthest from all enemies
    # O(m + n): approximate with enemy centroid — maximise distance from centroid.
    elif strategy_id == 2:
        n_e = len(enemy_anchors)
        cent_c = sum(e[0] for e in enemy_anchors) / n_e
        cent_r = sum(e[1] for e in enemy_anchors) / n_e
        return max(valid_destinations, key=lambda d: (d[0] - cent_c) ** 2 + (d[1] - cent_r) ** 2)

    # STRATEGY 3: OBJECTIVE - Move toward nearest uncontrolled objective (prefer capture over hold)
    else:
        objective_hex_sets, _ = _build_objective_distance_cache(game_state)
        if objective_hex_sets:
            unit_col, unit_row = int(require_present(unit["col"], "unit.col")), int(require_present(unit["row"], "unit.row"))
            unit_player = int(require_present(unit["player"], "unit.player"))
            objective_controllers = require_key(game_state, "objective_controllers")
            objectives = require_key(game_state, "objectives")

            # Prefer objectives not already controlled by this player
            uncontrolled_sets = [
                hs for i, hs in enumerate(objective_hex_sets)
                if i < len(objectives) and objective_controllers.get(str(objectives[i]["id"])) != unit_player
            ]
            candidate_sets = uncontrolled_sets if uncontrolled_sets else objective_hex_sets

            best_obj_set = min(
                candidate_sets,
                key=lambda hs: min(_chd(unit_col, unit_row, hc, hr) for hc, hr in hs)
            )
            # If any destination is on that objective, take it immediately
            for dest in valid_destinations:
                if dest in best_obj_set:
                    return dest
            # Otherwise move toward the centroid of that objective's hexes
            n = len(best_obj_set)
            centroid_c = sum(hc for hc, hr in best_obj_set) / n
            centroid_r = sum(hr for hc, hr in best_obj_set) / n
            return min(valid_destinations, key=lambda d: (d[0] - centroid_c) ** 2 + (d[1] - centroid_r) ** 2)

        return valid_destinations[0]


def movement_preview(valid_destinations: List[Tuple[int, int]]) -> Dict[str, Any]:
    """AI_MOVE.md: Generate preview data for green hexes"""
    return {
        "green_hexes": valid_destinations,
        "show_preview": True
    }


def movement_clear_preview(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clear movement preview"""
    game_state["preview_hexes"] = []
    game_state["valid_move_destinations_pool"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_border"] = []
    game_state["move_preview_footprint_mask_loops"] = None
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = None
    return {
        "show_preview": False,
        "clear_hexes": True
    }


def _handle_movement_postpone(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Quitter la sélection de destination (preview + active_movement_unit) sans retirer l'unité du
    ``move_activation_pool`` — aligné sur le report tir (``postpone`` / ``activation_ended: false``).
    """
    am = game_state.get("active_movement_unit")
    if am is None or am == "":
        return True, {"action": "no_effect", "activation_ended": False}
    if str(unit["id"]) != str(am):
        return False, {
            "error": "postpone_movement_wrong_unit",
            "expected_active_movement_unit": am,
            "unitId": unit["id"],
        }
    movement_clear_preview(game_state)
    return True, {
        "action": "postpone",
        "unitId": unit["id"],
        "activation_ended": False,
        "reset_mode": "select",
        "clear_selected_unit": True,
    }


def movement_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Route click actions"""
    if "clickTarget" not in action:
        click_target = "elsewhere"  # Default behavior for missing field
    else:
        click_target = action["clickTarget"]
    
    if click_target == "destination_hex":
        return movement_destination_selection_handler(game_state, unit_id, action)
    elif click_target == "friendly_unit":
        return False, {"error": "unit_switch_not_implemented"}
    elif click_target == "active_unit":
        unit_click = get_unit_by_id(game_state, unit_id)
        if not unit_click:
            return False, {"error": "unit_not_found", "unitId": unit_id}
        return _handle_movement_postpone(game_state, unit_click)
    else:
        # Clic ailleurs : report uniquement si une activation move attend une destination
        if game_state.get("active_movement_unit") is None:
            return True, {"action": "continue_selection"}
        unit_click = get_unit_by_id(game_state, unit_id)
        if not unit_click:
            return False, {"error": "unit_not_found", "unitId": unit_id}
        return _handle_movement_postpone(game_state, unit_click)

def movement_destination_selection_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle destination selection and execute movement"""
    # Direct field access with validation
    if "destCol" not in action:
        raise KeyError(f"Action missing required 'destCol' field: {action}")
    if "destRow" not in action:
        raise KeyError(f"Action missing required 'destRow' field: {action}")
    dest_col = action["destCol"]
    dest_row = action["destRow"]

    if dest_col is None or dest_row is None:
        return False, {"error": "missing_destination"}

    # Normalize coordinates to int - raises error if invalid
    dest_col, dest_row = normalize_coordinates(dest_col, dest_row)
    orientation = None
    if "orientation" in action:
        orientation = _validate_move_orientation(action["orientation"])

    # Pool is already built during activation - no need to rebuild here
    # System is sequential, so pool is still valid
    if "valid_move_destinations_pool" not in game_state:
        raise KeyError("game_state missing required 'valid_move_destinations_pool' field")
    valid_pool = game_state["valid_move_destinations_pool"]

    # Validate destination in valid pool
    if (dest_col, dest_row) not in valid_pool:
        # Destination not reachable via BFS pathfinding
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) NOT_IN_POOL pool_size={len(valid_pool)}")
        return False, {"error": "invalid_destination", "destination": (dest_col, dest_row)}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found", "unit_id": unit_id}

    # Desperate Escape (09.07) : le hazard roll (06.03) est désormais résolu à l'ACTIVATION
    # (action hazard_confirm), AVANT le preview — plus ici au commit. Ce chemin commit un
    # Fall Back déjà autorisé.

    # Destination validation is already done in movement_build_valid_destinations_pool()
    # (BFS + zone ennemie euclidienne bord à bord sur plateau ×10). Le pool doit rester
    # aligné avec _attempt_movement_to_destination (revalidation stricte au commit).

    # Use _attempt_movement_to_destination() to validate occupation
    # This function checks if destination is occupied, validates enemy adjacency, etc.
    config = {}  # Empty config for now
    import time as _mds_t
    from engine.perf_timing import append_perf_timing_line as _mds_log, perf_timing_enabled as _mds_pte
    _mds_pt = _mds_pte(game_state)
    _mds_t0 = _mds_t.perf_counter() if _mds_pt else None
    move_success, move_result = _attempt_movement_to_destination(
        game_state,
        unit,
        dest_col,
        dest_row,
        config,
        orientation=orientation,
    )
    _mds_t1 = _mds_t.perf_counter() if _mds_pt else None

    if not move_success:
        # Move was blocked (occupied hex, adjacent to enemy, etc.)
        error_type = move_result.get('error', 'unknown')
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) BLOCKED error={error_type}")
        
        # If destination is invalid (adjacent to enemy or occupied), remove it from pool
        # to prevent infinite loops where agent keeps trying invalid destinations
        if error_type in ("destination_adjacent_to_enemy", "destination_occupied") and "valid_move_destinations_pool" in game_state:
            invalid_dest = (dest_col, dest_row)
            if invalid_dest in game_state["valid_move_destinations_pool"]:
                game_state["valid_move_destinations_pool"].remove(invalid_dest)
                # Also update pending_movement_destinations if it exists
                if "pending_movement_destinations" in game_state and invalid_dest in game_state["pending_movement_destinations"]:
                    game_state["pending_movement_destinations"].remove(invalid_dest)

                # If pool is now empty, force skip this unit to prevent infinite loop
                if not game_state["valid_move_destinations_pool"]:
                    _log_movement_debug(game_state, "destination_selection", str(unit_id), "ALL destinations invalid - forcing skip to prevent infinite loop")
                    return _handle_skip_action(game_state, unit, had_valid_destinations=False)
        
        return False, move_result

    # V11 : Advance déjà marqué dans units_advanced au clic (movement_set_advance_mode_handler) ;
    # il persiste tout le tour, rien à faire ici (ce chemin ne passe pas par commit_move).

    # Extract movement info from result
    # Log successful destination selection
    _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) SELECTED")
    was_adjacent = (move_result.get("action") == "flee")
    # Use fromCol/fromRow from move_result (set by _attempt_movement_to_destination before movement)
    # These are the original coordinates BEFORE the movement
    orig_col = move_result.get("fromCol")
    orig_row = move_result.get("fromRow")
    if orig_col is None or orig_row is None:
        raise ValueError(f"move_result missing fromCol/fromRow: move_result keys={list(move_result.keys())}")

    # Position has already been updated by _attempt_movement_to_destination()
    # Validate it actually changed
    unit_col, unit_row = require_unit_position(unit, game_state)
    if unit_col != dest_col or unit_row != dest_row:
        return False, {"error": "position_update_failed"}
    
    # DEBUG: Log exact values before using unit coordinates
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: dest_col={dest_col} dest_row={dest_row} unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    # Invalidate all destination pools after movement
    # Positions have changed, so all pools (move, charge, shoot) are now stale
    _invalidate_all_destination_pools_after_movement(game_state)
    _mds_t2 = _mds_t.perf_counter() if _mds_pt else None

    move_kind = "flee" if was_adjacent else "move"
    reactive_result = maybe_resolve_reactive_move(
        game_state=game_state,
        moved_unit_id=str(unit["id"]),
        from_col=orig_col,
        from_row=orig_row,
        to_col=dest_col,
        to_row=dest_row,
        move_kind=move_kind,
        move_cause="normal",
    )
    _mds_t3 = _mds_t.perf_counter() if _mds_pt else None
    if _mds_pt and _mds_t0 is not None and _mds_t1 is not None and _mds_t2 is not None and _mds_t3 is not None:
        _mds_log(
            f"MOVE_DEST_TIMING episode={episode} turn={turn} unitId={unit_id!r} "
            f"attempt_s={_mds_t1 - _mds_t0:.6f} pool_invalidate_s={_mds_t2 - _mds_t1:.6f} "
            f"reactive_s={_mds_t3 - _mds_t2:.6f} total_s={_mds_t3 - _mds_t0:.6f}"
        )

    # Generate movement log per requested format
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # Calculate reward for this action (movement rewards are disabled)
    action_reward = 0.0
    action_name = "FLEE" if was_adjacent else "MOVE"
    
    is_fly_move = _fly_traversal_active(game_state, unit, unit_id)
    _ut_seg = f" {unit['unitType']}" if unit.get("unitType") else ""
    if was_adjacent:
        if is_fly_move:
            movement_message = (
                f"Unit {unit['id']}{_ut_seg} FLED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
        else:
            movement_message = (
                f"Unit {unit['id']}{_ut_seg} FLED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
    else:
        movement_message = (
            f"Unit {unit['id']}{_ut_seg} MOVED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            if is_fly_move
            else f"Unit {unit['id']}{_ut_seg} MOVED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
        )

    append_action_log(
        game_state,
        {
        "type": "move",
        "message": movement_message,
        "turn": game_state["current_turn"] if "current_turn" in game_state else 1,
        "phase": "move",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "was_flee": was_adjacent,
        "timestamp": "server_time",
        "action_name": action_name,  # NEW: For debug display
        "reward": round(action_reward, 2),  # NEW: Calculated reward
        "is_ai_action": unit["player"] == 2,  # FIXED: PvE AI is player 2 (was P0/P1, now P1/P2)
        "is_fly_move": is_fly_move,
        },
    )

    # Clear preview
    movement_clear_preview(game_state)

    # End activation with position data for reward calculation
    # AI_TURN.md EXACT: end_activation(Arg1, Arg2, Arg3, Arg4, Arg5)
    action_type = FLED if was_adjacent else MOVE
    result = end_activation(
        game_state, unit,
        ACTION,      # Arg1: Log the action (movement already logged)
        1,             # Arg2: +1 step increment
        action_type,   # Arg3: MOVE or FLED tracking
        MOVE,        # Arg4: Remove from move_activation_pool
        1              # Arg5: No error logging
    )

    # Add position data for reward calculation
    # Detect same-position moves (unit didn't actually move)
    actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
    
    if not actually_moved:
        # Unit stayed in same position - treat as wait, not move
        action_name = "wait"
    elif was_adjacent:
        action_name = "flee"
    else:
        action_name = "move"
    
    # Use unit coordinates AFTER movement - SINGLE SOURCE OF TRUTH
    # NOT move_result.get("toCol")/toRow which comes from action["destCol"]/destRow
    # NOT action["destCol"]/destRow which might be incorrect
    # The unit's position is the ONLY reliable source after movement execution
    result_to_col, result_to_row = require_unit_position(unit, game_state)
    
    # DEBUG: Log exact values being used for result
    from engine.game_utils import add_console_log, safe_print
    episode = game_state.get('episode_number', '?')
    turn = game_state.get('turn', '?')
    debug_msg = f"[MOVEMENT DEBUG] E{episode} T{turn} Unit {unit_id}: Using result_to_col={result_to_col} result_to_row={result_to_row} (unit_col={unit['col']} unit_row={unit['row']} move_result_toCol={move_result.get('toCol')} move_result_toRow={move_result.get('toRow')}) for logging"
    add_console_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": result_to_col,  # Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "toRow": result_to_row,  # Use unit coordinates after movement - SINGLE SOURCE OF TRUTH
        "reactive_moves_applied": reactive_result["reactive_moves_applied"],
        "reactive_moves_declined": reactive_result["reactive_moves_declined"],
        "is_fly_move": is_fly_move,
        "activation_complete": True,
        "waiting_for_player": False,  # Movement is complete, no waiting needed
        "reset_mode": "select",
        "clear_selected_unit": True
    })
    
    return True, result


def _handle_skip_action(game_state: Dict[str, Any], unit: Dict[str, Any], had_valid_destinations: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """AI_MOVE.md: Handle skip (no valid dests) or wait (agent chooses to pass).

    had_valid_destinations: True = agent chose to pass (wait). False = no valid destinations (skip).
    """
    # REMOVED: Duplicate logging - AI_TURN.md end_activation handles ALL logging
    # AI_TURN.md PRINCIPLE: end_activation is SINGLE SOURCE for action logging

    movement_clear_preview(game_state)

    if had_valid_destinations:
        # AI_TURN.md EXACT: end_activation(WAIT, 1, PASS, MOVE, 1, 1)
        result = end_activation(
            game_state, unit,
            WAIT,        # Arg1: Log wait action (SINGLE SOURCE)
            1,             # Arg2: +1 step increment
            PASS,        # Arg3: PASS tracking (not MOVE)
            MOVE,        # Arg4: Remove from move_activation_pool
            1              # Arg5: Error logging enabled
        )
        result.update({
            "action": "wait",  # Agent chose to pass
            "unitId": unit["id"],
            "activation_complete": True,
            "reset_mode": "select",
            "clear_selected_unit": True
        })
    else:
        # AI_TURN.md EXACT: end_activation(NO, 0, PASS, MOVE, 1, 1) - no step (unit could not act)
        result = end_activation(
            game_state, unit,
            NO,         # Arg1: NO (no action taken)
            0,            # Arg2: No step increment
            PASS,       # Arg3: PASS tracking
            MOVE,       # Arg4: Remove from move_activation_pool
            1             # Arg5: Error logging enabled
        )
        result.update({
            "action": "skip",
            "skip_reason": "no_valid_move_destinations",
            "unitId": unit["id"],
            "activation_complete": True,
            "reset_mode": "select",
            "clear_selected_unit": True
        })

    return True, result


def movement_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_MOVE.md: Clean up and end movement phase"""
    movement_clear_preview(game_state)
    
    # Track phase completion reason (AI_TURN.md compliance)
    if 'last_compliance_data' not in game_state:
        game_state['last_compliance_data'] = {}
    game_state['last_compliance_data']['phase_end_reason'] = 'eligibility'
    
    from engine.game_utils import add_console_log
    add_console_log(game_state, "MOVEMENT PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    move_pool = require_key(game_state, "move_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} move move_activation_pool={move_pool}")
    
    return {
        "phase_complete": True,
        "next_phase": "shoot",
        "units_processed": len([uid for uid in require_key(game_state, "units_cache").keys() if uid in game_state["units_moved"]])
    }
