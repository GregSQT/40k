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
from shared.data_validation import require_key
from engine.combat_utils import (
    calculate_hex_distance,
    normalize_coordinates,
    set_unit_coordinates,
    get_unit_by_id,
    get_hex_neighbors,
)
from .shared_utils import (
    ACTION, WAIT, NO, PASS, ERROR, MOVE, FLED,
    build_enemy_adjacent_hexes, update_units_cache_position, is_unit_alive,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    build_occupied_positions_set,
    build_enemy_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid, get_engagement_zone, get_max_base_size_hex,
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


def _hex_radius_upper_for_engagement_prune(base_span: int) -> int:
    """Majorant (grille hex) du rayon empreinte depuis l’ancre — borne conservatrice pour la prune."""
    s = max(1, int(base_span))
    return max(1, (s + 1) // 2)


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
        e_col = int(require_key(ce, "col"))
        e_row = int(require_key(ce, "row"))
        e_span = min(_move_preview_footprint_span(ce), max_bs)
        e_r = _hex_radius_upper_for_engagement_prune(e_span)
        h = horizon_without_enemy_r + e_r
        if calculate_hex_distance(start_col, start_row, e_col, e_row) <= h:
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
    mover_id = str(require_key(mover, "id"))
    mover_player = int(require_key(mover, "player"))

    if ez <= 1:
        if enemy_adjacent_hexes is None:
            ck = f"enemy_adjacent_hexes_player_{mover_player}"
            enemy_adjacent_hexes = require_key(game_state, ck)
        for c, r in candidate_fp:
            if (c, r) in enemy_adjacent_hexes:
                return True
        return False

    req = engagement_minimum_clearance_norm(ez)
    mover_shape = mover.get("BASE_SHAPE", "round")
    mover_bs = mover.get("BASE_SIZE", 1)
    mover_bs_i = mover_bs if isinstance(mover_bs, int) else 1
    # Un seul _hex_center pour le déplaceur (identique pour chaque ennemi rond / rond).
    mover_center_xy_rr: Optional[Tuple[float, float]] = None
    if ez > 1 and mover_shape == "round":
        mover_center_xy_rr = _hex_center(center_col, center_row)

    if enemy_cache_items is not None:
        _enemy_iter: Any = enemy_cache_items
    else:
        _enemy_iter = (
            (eid, ce)
            for eid, ce in units_cache.items()
            if str(eid) != mover_id and int(require_key(ce, "player")) != mover_player
        )

    for eid, cache_entry in _enemy_iter:
        enemy_fp = cache_entry.get("occupied_hexes")
        if not enemy_fp:
            ec = require_key(cache_entry, "col")
            er = require_key(cache_entry, "row")
            enemy_fp = {(ec, er)}
        e_shape = cache_entry.get("BASE_SHAPE", "round")
        e_bs_raw = cache_entry.get("BASE_SIZE", 1)
        e_bs_i = e_bs_raw if isinstance(e_bs_raw, int) else 1
        e_col = require_key(cache_entry, "col")
        e_row = require_key(cache_entry, "row")

        if mover_shape == "round" and e_shape == "round":
            gap = euclidean_edge_clearance_round_round(
                center_col,
                center_row,
                mover_bs_i,
                e_col,
                e_row,
                e_bs_i,
                mover_center_xy=mover_center_xy_rr,
            )
            if gap < req - 1e-6:
                return True
        else:
            if min_distance_between_sets(candidate_fp, enemy_fp, max_distance=ez) <= ez:
                return True
    return False


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


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
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
    
    elif action_type == "skip":
        # Engine determined unit has no valid actions (e.g. no valid destinations)
        return _handle_skip_action(game_state, active_unit, had_valid_destinations=False)
    
    elif action_type == "left_click":
        return movement_click_handler(game_state, unit_id, action)
    
    elif action_type == "right_click":
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


def _attempt_movement_to_destination(game_state: Dict[str, Any], unit: Dict[str, Any], dest_col: int, dest_row: int, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
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

    unit_id_str = str(unit["id"])
    occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
    candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, unit, game_state)
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
        mover_shape = unit.get("BASE_SHAPE", "round")
        mover_bs_i = unit.get("BASE_SIZE", 1)
        mover_bs_i = mover_bs_i if isinstance(mover_bs_i, int) else 1
        if ez_blk > 1 and mover_shape == "round":
            req_blk = engagement_minimum_clearance_norm(ez_blk)
            _dest_mover_xy = _hex_center(dest_col_int, dest_row_int)
            for eid, cache_entry in units_cache.items():
                if str(eid) == mover_id_str:
                    continue
                if int(require_key(cache_entry, "player")) == mover_player_int:
                    continue
                if cache_entry.get("BASE_SHAPE", "round") != "round":
                    continue
                e_bs = cache_entry.get("BASE_SIZE", 1)
                e_bs_i = e_bs if isinstance(e_bs, int) else 1
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
                if gap < req_blk - 1e-6:
                    blocking_eid = str(eid)
                    break
        return False, {
            "error": "destination_adjacent_to_enemy",
            "enemy_id": blocking_eid,
            "destination": (dest_col_int, dest_row_int),
        }

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

    # Update units_cache after position change
    update_units_cache_position(game_state, unit_id_str_cache, dest_col_int, dest_row_int)

    # Retrieve new footprint from updated cache
    new_cache_entry = require_key(game_state, "units_cache").get(unit_id_str_cache)
    new_occupied = new_cache_entry.get("occupied_hexes") if new_cache_entry else None

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
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], int]:
    """BFS multi-hex vectorisé NumPy (cas ``ground``). Gère toutes les formes de socles.

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

    obstacles_traverse = walls_set | enemy_occupied_set
    obstacles_dest_any = walls_set | occupied_set
    obstacles_traverse_mask = _mask_from_cells(obstacles_traverse)
    obstacles_dest_mask = _mask_from_cells(obstacles_dest_any)

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

    bad_traverse = _placement_bad(obstacles_traverse_mask)
    bad_dest = _placement_bad(obstacles_dest_mask)

    # Voisins hex (offset coordinates). Définis ici car utilisés à la fois par la dilatation hex
    # de l'engagement mixte et par la propagation BFS.
    nb_even = np.asarray(
        [(0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1)], dtype=np.int64
    )
    nb_odd = np.asarray(
        [(0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)], dtype=np.int64
    )

    if ez > 1:
        from engine.hex_utils import (
            engagement_minimum_clearance_norm,
            round_base_radius_norm,
            _hex_center,
            precompute_footprint_offsets,
        )
        req = engagement_minimum_clearance_norm(ez)
        mover_shape = unit.get("BASE_SHAPE", "round")
        mover_bs = unit.get("BASE_SIZE", 1)
        mover_bs_i = mover_bs if isinstance(mover_bs, int) else 1
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

        # Partitionne les ennemis : paire round/round → formule euclidienne vectorisée ;
        # autres → on agrège leurs empreintes dans un mask dilatable en distance hex.
        mover_r_norm = round_base_radius_norm(mover_bs_i) if mover_is_round else 0.0
        hex_mixed_mask = np.zeros((board_cols, board_rows), dtype=bool)
        has_hex_mixed = False
        for _, ce in enemy_list:
            e_col = int(require_key(ce, "col"))
            e_row = int(require_key(ce, "row"))
            e_bs_raw = ce.get("BASE_SIZE", 1)
            e_bs_i = e_bs_raw if isinstance(e_bs_raw, int) else 1
            e_shape = ce.get("BASE_SHAPE", "round")
            if mover_is_round and e_shape == "round":
                e_r_norm = round_base_radius_norm(e_bs_i)
                ex, ey = _hex_center(e_col, e_row)
                dx = xs - float(ex)
                dy = ys - float(ey)
                d = np.hypot(dx, dy)
                eng_bad |= (d - mover_r_norm - e_r_norm) < (req - 1e-6)
            else:
                # Dépose l'empreinte hex de l'ennemi (peu importe sa forme) dans le mask commun.
                e_orient = int(require_key(ce, "orientation"))
                e_off_even, e_off_odd = precompute_footprint_offsets(e_shape, e_bs_i, e_orient)
                e_off = e_off_even if (e_col & 1) == 0 else e_off_odd
                for dc, dr in e_off:
                    fc = e_col + int(dc)
                    fr = e_row + int(dr)
                    if 0 <= fc < board_cols and 0 <= fr < board_rows:
                        hex_mixed_mask[fc, fr] = True
                has_hex_mixed = True

        if has_hex_mixed:
            # Dilatation hex (cube-distance) de rayon ``ez`` par propagation itérative par parité.
            # Équivalent à ``dilate_hex_set(mask, ez)`` : l'ancre viole l'engagement si une cellule
            # de son empreinte tombe dans cette dilatation → ``min_distance_between_sets ≤ ez``.
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
    elif ez == 1 and enemy_adjacent_hexes:
        enemy_adj_mask = _mask_from_cells(enemy_adjacent_hexes)
        eng_bad_even = _dilate_by_kernel(enemy_adj_mask, off_even_arr)
        eng_bad_odd = _dilate_by_kernel(enemy_adj_mask, off_odd_arr)
        eng_bad = np.where(col_parity_mask, eng_bad_even, eng_bad_odd)
    else:
        eng_bad = np.zeros((board_cols, board_rows), dtype=bool)

    traverse_bad = bad_traverse | eng_bad

    reach = np.zeros((board_cols, board_rows), dtype=bool)
    reach[start_col, start_row] = True

    allowed = ~traverse_bad
    allowed[start_col, start_row] = True

    for _ in range(int(move_range)):
        even_src = reach & col_parity_mask
        odd_src = reach & ~col_parity_mask
        new_reach = reach.copy()
        expanded_even = _spread_by_kernel(even_src, nb_even)
        expanded_odd = _spread_by_kernel(odd_src, nb_odd)
        new_reach |= expanded_even & allowed
        new_reach |= expanded_odd & allowed
        if np.array_equal(new_reach, reach):
            break
        reach = new_reach

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
        _fly_n_cells = board_cols * board_rows
        _fly_vis = bytearray(_fly_n_cells)
        _fly_vis[start_col + start_row * board_cols] = 1
        fly_visited_n = 1
        fly_queue = deque([(start_pos, 0)])
        valid_destinations: List[Tuple[int, int]] = []
        fly_rejected_footprint = 0

        _fly_bcols = board_cols
        _fly_brows = board_rows
        _fly_walls = game_state.get("wall_hexes", set())
        _fly_occupied = occupied_positions

        _fly_base_size = unit.get("BASE_SIZE", 1)
        _fly_single_hex = (ez <= 1 or _fly_base_size == 1)

        if not _fly_single_hex:
            from engine.hex_utils import precompute_footprint_offsets
            _fly_shape = unit.get("BASE_SHAPE", "round")
            _fly_orient = int(require_key(unit, "orientation"))
            _fly_off_even, _fly_off_odd = precompute_footprint_offsets(
                _fly_shape, _fly_base_size, _fly_orient
            )

        _m_bfs_start = _perf_clock.perf_counter() if _pt else None
        while fly_queue:
            (fc, fr), fly_dist = fly_queue.popleft()
            if fly_dist >= move_range:
                continue
            _nd = fly_dist + 1
            _p = fc & 1
            if _p == 0:
                _nbs = (
                    (fc, fr - 1), (fc + 1, fr - 1), (fc + 1, fr),
                    (fc, fr + 1), (fc - 1, fr), (fc - 1, fr - 1),
                )
            else:
                _nbs = (
                    (fc, fr - 1), (fc + 1, fr), (fc + 1, fr + 1),
                    (fc, fr + 1), (fc - 1, fr + 1), (fc - 1, fr),
                )
            for nb in _nbs:
                nc, nr = nb
                if nc < 0 or nr < 0 or nc >= _fly_bcols or nr >= _fly_brows:
                    continue
                _fidx = nc + nr * board_cols
                if _fly_vis[_fidx]:
                    continue
                _fly_vis[_fidx] = 1
                fly_visited_n += 1
                fly_queue.append((nb, _nd))
                if nb == start_pos:
                    continue
                if _fly_single_hex:
                    if nb in _fly_walls or nb in _fly_occupied:
                        fly_rejected_footprint += 1
                    elif _movement_engagement_violates(
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
                        fly_rejected_footprint += 1
                    else:
                        valid_destinations.append(nb)
                else:
                    offsets = _fly_off_even if (nc & 1) == 0 else _fly_off_odd
                    dest_ok = True
                    for dc, dr in offsets:
                        _fc, _fr = nc + dc, nr + dr
                        if _fc < 0 or _fr < 0 or _fc >= _fly_bcols or _fr >= _fly_brows:
                            dest_ok = False
                            break
                        if (_fc, _fr) in _fly_walls:
                            dest_ok = False
                            break
                        if (_fc, _fr) in _fly_occupied:
                            dest_ok = False
                            break
                    candidate_fp_nb = {(nc + dc, nr + dr) for dc, dr in offsets}
                    if dest_ok and not _movement_engagement_violates(
                        game_state,
                        unit,
                        nc,
                        nr,
                        candidate_fp_nb,
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
        if _fly_single_hex:
            _fly_fp_zone: Set[Tuple[int, int]] = set(valid_destinations)
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
    base_size = unit.get("BASE_SIZE", 1)
    is_single_hex = (ez <= 1 or base_size == 1)

    # Grille dense O(1) : même sémantique que ``dict`` (case visitée ou non pour ce BFS).
    _n_cells = board_cols * board_rows
    _vis = bytearray(_n_cells)
    _vis[start_col + start_row * board_cols] = 1
    visited_n = 1
    queue = deque([(start_pos, 0)])
    valid_destinations: List[Tuple[int, int]] = []
    blocked_enemy_adjacent_count = 0

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
                if ez <= 1:
                    if nb in _enemy_adj:
                        blocked_enemy_adjacent_count += 1
                        continue
                else:
                    if _movement_engagement_violates(
                        game_state,
                        unit,
                        nc,
                        nr,
                        {(nc, nr)},
                        units_cache,
                        None,
                        enemy_cache_items=_enemy_items_for_engagement_ez,
                        engagement_zone_ez=ez,
                    ):
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
        base_shape = unit.get("BASE_SHAPE", "round")
        orientation = int(require_key(unit, "orientation"))
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
                dist = calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_enemy:
                    min_dist_to_enemy = dist
                    best_dest = dest

        return best_dest

    # STRATEGY 1: TACTICAL - Move to position with most enemies in shooting range
    elif strategy_id == 1:
        # Use max ranged range from weapons
        weapon_range = get_max_ranged_range(unit)
        best_dest = valid_destinations[0]
        max_targets = 0

        for dest in valid_destinations:
            targets_in_range = 0
            for enemy_id in enemy_units:
                enemy_col, enemy_row = enemy_positions[enemy_id]
                dist = calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
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
                dist = calculate_hex_distance(dest[0], dest[1], enemy_col, enemy_row)
                if dist < min_dist_to_any_enemy:
                    min_dist_to_any_enemy = dist

            if min_dist_to_any_enemy > max_min_dist:
                max_min_dist = min_dist_to_any_enemy
                best_dest = dest

        return best_dest

    # STRATEGY 3: OBJECTIVE - Move closest to nearest objective hex
    else:
        objectives = game_state.get("objectives")
        if objectives:
            objective_hexes: List[Tuple[int, int]] = []
            for obj in objectives:
                if isinstance(obj, dict):
                    _hx = obj.get("hexes")
                    hexes = _hx if isinstance(_hx, list) else []
                else:
                    hexes = []
                for h in hexes:
                    if isinstance(h, dict):
                        objective_hexes.append((int(h["col"]), int(h["row"])))
                    elif isinstance(h, (list, tuple)) and len(h) == 2:
                        objective_hexes.append((int(h[0]), int(h[1])))

            if objective_hexes:
                best_dest = valid_destinations[0]
                min_dist = float('inf')
                for dest in valid_destinations:
                    for obj_col, obj_row in objective_hexes:
                        dist = calculate_hex_distance(dest[0], dest[1], obj_col, obj_row)
                        if dist < min_dist:
                            min_dist = dist
                            best_dest = dest
                return best_dest

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
        return True, {"action": "no_effect"}
    else:
        return True, {"action": "continue_selection"}

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
    move_success, move_result = _attempt_movement_to_destination(game_state, unit, dest_col, dest_row, config)

    if not move_success:
        # Move was blocked (occupied hex, adjacent to enemy, etc.)
        error_type = move_result.get('error', 'unknown')
        _log_movement_debug(game_state, "destination_selection", str(unit_id), f"destination ({dest_col},{dest_row}) BLOCKED error={error_type}")
        
        # If destination is invalid (adjacent to enemy), remove it from pool
        # to prevent infinite loops where agent keeps trying invalid destinations
        if error_type == "destination_adjacent_to_enemy" and "valid_move_destinations_pool" in game_state:
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

    game_state["action_logs"].append({
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
    })
    
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


