#!/usr/bin/env python3
"""
movement_handlers.py - AI_TURN.md Movement Phase Implementation
Pure stateless functions implementing AI_TURN.md movement specification

References: AI_TURN.md Section 🏃 MOVEMENT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any
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
    build_enemy_adjacent_hexes, update_units_cache_position, translate_squad_to_destination, is_unit_alive,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    build_occupied_positions_set,
    build_enemy_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid, get_engagement_zone, get_max_base_size_hex,
    get_squad_move_budget, validate_move_plan, _validate_plan_coherency, commit_move,
    get_coherency_subhex, _compute_unit_occupied_hexes,
)
from engine.hex_utils import (
    _hex_center,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    min_distance_between_sets,
)
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

    elif action_type == "commit_move_plan":
        # Validate (= bouton Validate) + commit d'un plan provisoire par-figurine.
        return movement_commit_move_plan_handler(game_state, unit_id, action)

    elif action_type == "skip":
        # Engine determined unit has no valid actions (e.g. no valid destinations)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)
    
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
        # Human players: return waiting_for_player for destination selection
        return True, {
            "unit_activated": True,
            "unitId": unit_id,  # ADDED: Required for reward calculation
            "valid_destinations": game_state["valid_move_destinations_pool"],
            "preview_data": preview_data,
            "waiting_for_player": True
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
    was_adjacent = _is_adjacent_to_enemy(game_state, unit)

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
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, footprint_unit, game_state)
    _mct1 = _mct.perf_counter() if _mct_pt else None
    if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
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
        mover_shape = unit["BASE_SHAPE"]
        mover_bs_i = unit["BASE_SIZE"]
        if ez_blk > 1 and mover_shape == "round":
            req_blk = engagement_minimum_clearance_norm(ez_blk)
            _dest_mover_xy = _hex_center(dest_col_int, dest_row_int)
            for eid, cache_entry in units_cache.items():
                if str(eid) == mover_id_str:
                    continue
                if int(require_key(cache_entry, "player")) == mover_player_int:
                    continue
                if cache_entry["BASE_SHAPE"] != "round":
                    continue
                e_bs_i = cache_entry["BASE_SIZE"]
                e_col = require_key(cache_entry, "col")
                e_row = require_key(cache_entry, "row")
                gap = euclidean_edge_clearance_round_round(
                    dest_col_int,
                    dest_row_int,
                    mover_bs_i,
                    e_col,
                    e_row,
                    e_bs_i,
                    mover_center_xy=_dest_mover_xy,
                )
                if gap <= req_blk + 1e-6:
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
    if was_adjacent:
        game_state["units_fled"].add(unit_id_str)
        # Units that fled are also marked as moved (units_fled is a subset of units_moved)

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
    action_type = "FLEE" if was_adjacent else "MOVE"
    _log_movement_debug(game_state, "attempt_movement", str(unit["id"]), f"({orig_col},{orig_row})→({dest_col_int},{dest_row_int}) SUCCESS {action_type}")

    # Use normalized coordinates (dest_col_int, dest_row_int) in result
    # NOT dest_col/dest_row which might not be normalized
    return True, {
        "action": "flee" if was_adjacent else "move",
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col_int,  # Use normalized coordinates
        "toRow": dest_row_int    # Use normalized coordinates
    }


def _is_adjacent_to_enemy(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
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
    """
    import numpy as np
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

    req = engagement_minimum_clearance_norm(ez)
    mover_is_round = (mover_shape == "round")

    cs = np.arange(board_cols, dtype=np.float64)[:, None]
    rs = np.arange(board_rows, dtype=np.float64)[None, :]
    hex_width = 1.5
    hex_height = float(np.sqrt(3.0))
    xs = cs * hex_width + hex_width / 2.0
    parity_shift = ((np.arange(board_cols, dtype=np.int64) & 1).astype(np.float64))[:, None]
    ys = rs * hex_height + parity_shift * (hex_height / 2.0) + hex_height / 2.0

    eng_bad = np.zeros((board_cols, board_rows), dtype=bool)
    enemy_list = enemy_items if enemy_items is not None else []

    mover_r_norm = round_base_radius_norm(mover_bs_i) if mover_is_round else 0.0
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
        if mover_is_round and e_shape == "round":
            e_r_norm = round_base_radius_norm(e_bs)
            for e_col, e_row in model_positions:
                ex, ey = _hex_center(e_col, e_row)
                dx = xs - float(ex)
                dy = ys - float(ey)
                d = np.hypot(dx, dy)
                eng_bad |= (d - mover_r_norm - e_r_norm) <= (req + 1e-6)
        else:
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
    fly: bool = False,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int]:
    """BFS/disk multi-hex vectorisé NumPy (``ground`` et ``fly``). Gère toutes les formes de socles.

    Retourne ``(valid_destinations, footprint_zone, visited_count)``.

    Invariants de sémantique (équivalence stricte avec le BFS Python hex orig.) :

    - **Bounds + walls + enemy_occupied** : filtre de traversée. L'empreinte doit tenir dans le
      plateau et ne chevaucher ni mur ni cellule occupée par un ennemi. Une ancre invalide ne
      peut pas être traversée par le BFS.
    - **Engagement zone** :
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
        obstacles_traverse = walls_set | enemy_occupied_set
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
        # FLY: reachable = hex disk (no traversal obstacles). Direct cube-distance computation.
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
        traverse_bad = bad_traverse | eng_bad

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

        valid_mask = reach & ~bad_dest
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


@profile_move_pool_build
def movement_build_valid_destinations_pool(game_state: Dict[str, Any], unit_id: str) -> List[Tuple[int, int]]:
    """
    Build valid movement destinations using BFS pathfinding.

    Uses BFS to find REACHABLE hexes, not just hexes within distance.
    This prevents movement through walls (AI_TURN.md compliance).

    Pre-computes enemy adjacent hexes and occupied positions once at BFS start for O(1) lookups.

    Ground (non-Fly): BFS never steps through an enemy engagement hex — those neighbors are
    rejected before enqueue (``enemy_adjacent_hexes`` / ``_movement_engagement_violates`` on the
    footprint). You cannot cross that band to reach hexes beyond it without Fly. Ally-occupied
    hexes may be traversed but the footprint cannot end on any occupied hex; enemy-occupied
    hexes block traversal.

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

    move_range = unit["MOVE"]
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

    has_fly_keyword = _unit_has_keyword(unit, "fly")

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

    # FLY units: BFS ignoring walls/occupation for traversal.
    # Only destination validation checks walls, occupation and engagement zone.
    # This replaces the O(cols×rows) scan with O(reachable) BFS.
    if has_fly_keyword:
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
            )
            _m_bfs_end = _perf_clock.perf_counter() if _pt else None
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

    _occupied = occupied_positions
    _enemy_occ = enemy_occupied
    _walls = wall_hexes_set
    _enemy_adj = enemy_adjacent_hexes
    _bcols = board_cols
    _brows = board_rows

    _m_bfs_start = _perf_clock.perf_counter() if _pt else None
    if is_single_hex:
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
                if nb in _enemy_occ:
                    continue
                if nb in _enemy_adj:
                    blocked_enemy_adjacent_count += 1
                    continue
                _vis[_vidx] = 1
                visited_n += 1
                queue.append((nb, nd))
                # Traversal may pass through allied hexes; cannot end on any occupied cell.
                if nb != start_pos and nb not in _occupied:
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
        )

    _m_bfs_end = _perf_clock.perf_counter() if _pt else None
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

    Sol (non-Fly) : ne traverse jamais mur / hex occupe par un ennemi / bande
    d'engagement ennemie (enemy_adjacent_hexes). Les hexes allies sont
    traversables. Fly : traversal libre, seule la destination est validee.

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

    has_fly = _unit_has_keyword(unit, "fly")

    # Zone d'engagement ennemie au niveau ANCRE.
    # ez > 1 (Board ×N) : géométrie euclidienne par-mover, source unique partagée avec le path IA
    #   (``_compute_mover_ez_forbidden_mask``) → garantit IA == PvP. L'empreinte du mover est déjà
    #   prise en compte dans le masque, donc l'EZ se teste sur l'ancre et N'EST PAS re-dilatée par
    #   l'empreinte plus bas (``dest_blocked`` ne contient que la géométrie).
    # ez <= 1 (legacy) : dilatation hex pré-calculée (``enemy_adjacent_hexes``), traitée comme la
    #   géométrie (dilatée par l'empreinte dans le filtre multi-hex) — comportement inchangé.
    ez = get_engagement_zone(game_state)
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

    visited: Set[Tuple[int, int]] = {start_pos}
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
            if cell in visited:
                continue
            if not has_fly and (
                cell in wall_hexes or cell in enemy_occupied or cell in ez_anchor_forbidden
            ):
                continue
            visited.add(cell)
            queue.append((nc, nr, d + 1))
            # Validite destination : murs + toutes figs occupant la cellule + engagement ennemi
            # (ez_anchor_forbidden = EZ au niveau ancre).
            if cell in dest_blocked or cell in ez_anchor_forbidden:
                continue
            reachable.append(cell)

    # Footprint zone per-fig : destinations ∪ start, expandées selon BASE_SIZE.
    base_size = unit["BASE_SIZE"]
    base_shape = unit["BASE_SHAPE"]
    orientation = unit.get("orientation", 0)  # get allowed
    is_single_hex = (base_size == 1 or not isinstance(base_size, int) or base_size <= 1)  # get allowed
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
    budget = get_squad_move_budget(str(squad_id), game_state, "normal")
    ez = get_engagement_zone(game_state)
    unit_obj = get_unit_by_id(game_state, str(squad_id))
    c_individual = {"budget_per_model": budget, "require_coherency": False}
    if ez > 1:
        # Board ×N : l'EZ est vérifiée ci-dessous par la formule euclidienne par-mover
        # (``_movement_engagement_violates``, même géométrie que le pathfinding → IA == PvP).
        # On désactive le check legacy centre-à-centre de ``validate_move_plan``.
        c_individual["forbid_enemy_er"] = False
    # Cohesion par COMPOSANTES CONNEXES (squad.md) : on relie les figs distantes de <=
    # coherency_dist (2"), puis on cherche les groupes connectes. Le groupe STRICTEMENT
    # majoritaire (taille*2 > effectif total) reste vert ; tout groupe minoritaire ou a
    # egalite (taille*2 <= total) passe en rouge → 2 moities egales = tout le squad rouge.
    #
    # La distance utilisée est l'empreinte-à-empreinte (pas centre-à-centre) pour les
    # unités avec une grande base : deux figs dont les empreintes se touchent à ≤2" sont
    # en cohésion même si leurs centres sont à >2".
    positions: List[Tuple[int, int]] = [(int(nc), int(nr)) for _, nc, nr in plan]
    n = len(positions)
    coherency_dist = get_coherency_subhex(game_state)

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

    adjacency: List[List[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = min_distance_between_sets(footprints[i], footprints[j], max_distance=coherency_dist)
            if d <= coherency_dist:
                adjacency[i].append(j)
                adjacency[j].append(i)

    comp_id = [-1] * n
    comp_count = 0
    for start in range(n):
        if comp_id[start] != -1:
            continue
        stack = [start]
        comp_id[start] = comp_count
        while stack:
            k = stack.pop()
            for nb in adjacency[k]:
                if comp_id[nb] == -1:
                    comp_id[nb] = comp_count
                    stack.append(nb)
        comp_count += 1

    comp_size: Dict[int, int] = {}
    for c in comp_id:
        comp_size[c] = comp_size.get(c, 0) + 1  # get allowed
  # get allowed
    # cohesion_red[i] = la composante de la fig i n'est PAS strictement majoritaire.
    cohesion_red = [comp_size[comp_id[i]] * 2 <= n for i in range(n)] if n > 1 else [False] * n

    wall_hexes_set = game_state.get("wall_hexes", set())
    other_occ_set: Set[Tuple[int, int]] = set()
    for sid, entry in units_cache.items():
        if str(sid) == str(squad_id):
            continue
        occ = entry.get("occupied_hexes")
        if occ:
            for cell in occ:
                other_occ_set.add((int(cell[0]), int(cell[1])))

    per_model: Dict[str, bool] = {}
    for idx, (mid, nc, nr) in enumerate(plan):
        base_valid = validate_move_plan(
            [(str(mid), int(nc), int(nr))], game_state, c_individual
        )
        fp = footprints[idx]
        fp_wall = bool(wall_hexes_set and fp & wall_hexes_set)
        fp_other = bool(other_occ_set and fp & other_occ_set)
        fp_intra = any(bool(footprints[j] & fp) for j in range(n) if j != idx)
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
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
    }


def movement_commit_move_plan_handler(
    game_state: Dict[str, Any], squad_id: str, action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Valide (= bouton Validate) puis commit un plan provisoire par-figurine.

    ``action["plan"]`` : liste de ``[model_id, col, row]``, DOIT couvrir toutes
    les figurines vivantes de l'escouade (sinon la cohesion est fausse). Move
    normal uniquement.

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

    commit_move(plan, game_state, "normal")

    unit = get_unit_by_id(game_state, squad_id)
    if not unit:
        return False, {"error": "unit_not_found", "unitId": squad_id}
    # Sync ancre de la liste units sur l'ancre recalculee dans units_cache
    # (commit_move ne touche que models_cache/units_cache).
    entry = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
    if entry is not None:  # get allowed
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))

    _invalidate_all_destination_pools_after_movement(game_state)
    movement_clear_preview(game_state)

    result = end_activation(game_state, unit, ACTION, 1, MOVE, MOVE, 1)
    result.update(
        {
            "action": "move",
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
    
    is_fly_move = _unit_has_keyword(unit, "fly")
    if was_adjacent:
        if is_fly_move:
            movement_message = (
                f"Unit {unit['id']} FLED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
        else:
            movement_message = (
                f"Unit {unit['id']} FLED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            )
    else:
        movement_message = (
            f"Unit {unit['id']} MOVED [FLY] from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
            if is_fly_move
            else f"Unit {unit['id']} MOVED from ({orig_col},{orig_row}) to ({dest_col},{dest_row})"
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
