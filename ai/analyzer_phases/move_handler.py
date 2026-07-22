"""
move_handler.py — gestion des actions MOVE et FLED dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def handle_move_or_fled(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    line: str,
    action_desc: str,
    unit_id: str,
    player: int,
    turn: int,
    phase: str,
) -> bool:
    """
    Traite une ligne d'action MOVE ou FLED.
    Retourne True si la ligne doit être skippée (continue dans la boucle principale).
    """
    from ai.analyzer import (
        _track_action_phase_accuracy,
        _position_cache_set,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        _debug_log,
        _get_unit_hp_value,
        _build_occupied_positions,
        _build_enemy_adjacent_hexes,
        _bfs_shortest_path_length,
        get_adjacent_enemies,
    )

    stats = state.stats

    # CRITICAL: Detect explicit FLED actions first
    fled_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) FLED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
    if fled_match:
        skip = _handle_fled(state, config, line, action_desc, player, turn, phase, fled_match,
                            _track_action_phase_accuracy, _position_cache_set, _debug_log,
                            _get_unit_hp_value)
        return skip

    move_match = re.search(
        r'Unit (\d+)\((\d+),\s*(\d+)\)\s+MOVED(?:\s+AFTER\s+SHOOTING)?(?:\s+\[[^\]]+\])?\s+from\s+\((\d+),\s*(\d+)\)\s+to\s+\((\d+),\s*(\d+)\)',
        action_desc
    )
    if move_match:
        skip = _handle_move(state, config, line, action_desc, player, turn, phase, move_match,
                            _track_action_phase_accuracy, _position_cache_set,
                            _get_unit_hp_value, _build_occupied_positions,
                            _build_enemy_adjacent_hexes, _bfs_shortest_path_length,
                            get_adjacent_enemies, is_within_engine_engagement_zone,
                            _get_engagement_zone_for_analyzer, _debug_log)
        return skip
    else:
        if "REACTIVE MOVED" not in action_desc.upper():
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Move action missing 'from/to' format: {action_desc[:100]}"
            })
    return False


def _handle_fled(state, config, line, action_desc, player, turn, phase, fled_match,
                 _track_action_phase_accuracy, _position_cache_set, _debug_log, _get_unit_hp_value):
    stats = state.stats
    move_unit_id = fled_match.group(1)
    start_col = int(fled_match.group(4))
    start_row = int(fled_match.group(5))
    dest_col = int(fled_match.group(6))
    dest_row = int(fled_match.group(7))

    state.units_moved.add(move_unit_id)
    state.units_fled.add(move_unit_id)
    _track_action_phase_accuracy(stats, "fled", phase, state.current_episode_num, line)
    if stats['first_error_lines']['fled_action'][player] is None:
        stats['first_error_lines']['fled_action'][player] = {
            'episode': state.current_episode_num,
            'line': line.strip()
        }

    _debug_log(f"[FLED DEBUG] E{state.current_episode_num} T{turn} P{player}: Unit {move_unit_id} FLED from ({start_col},{start_row}) to ({dest_col},{dest_row})")
    if move_unit_id in state.unit_positions:
        _debug_log(f"[FLED DEBUG] BEFORE sync: unit_positions[{move_unit_id}] = {state.unit_positions[move_unit_id]}")
    else:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"FLED debug missing unit position for unit_id: {move_unit_id}"
        })
        _debug_log(f"[FLED DEBUG] BEFORE sync: unit_positions[{move_unit_id}] is missing")

    if move_unit_id not in state.unit_hp:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"FLED update missing unit_hp for unit_id: {move_unit_id}"
        })
        return True  # equivalent to continue

    unit_hp_value = require_key(state.unit_hp, move_unit_id)
    _debug_log(f"[FLED DEBUG] BEFORE update: unit_hp[{move_unit_id}] = {unit_hp_value}")
    if unit_hp_value > 0:
        old_position = state.unit_positions.get(move_unit_id)
        _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)
        _debug_log(f"[FLED DEBUG] AFTER update: unit_positions[{move_unit_id}] = {state.unit_positions[move_unit_id]} (was {old_position})")
    else:
        _debug_log(f"[FLED DEBUG] SKIPPED update: unit_hp[{move_unit_id}] = {unit_hp_value} (<= 0)")

    if move_unit_id not in state.unit_movement_history:
        state.unit_movement_history[move_unit_id] = []
    timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
    timestamp = timestamp_match.group(1) if timestamp_match else None
    state.unit_movement_history[move_unit_id].append({
        'position': (dest_col, dest_row),
        'timestamp': timestamp,
        'action': 'fled',
        'turn': turn,
        'episode': state.current_episode_num
    })

    if (start_col, start_row) != (dest_col, dest_row):
        colliding_units = []
        for uid, current_pos in state.unit_positions.items():
            if current_pos != (dest_col, dest_row) or uid == move_unit_id:
                continue
            if uid not in state.unit_hp:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Collision check missing unit_hp for unit_id: {uid}"
                })
                continue
            hp_value = _get_unit_hp_value(
                state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Move collision"
            )
            if hp_value is None:
                continue
            if hp_value > 0:
                colliding_units.append(uid)

        real_colliding_units = []
        for uid in colliding_units:
            if uid in state.unit_positions and state.unit_positions[uid] == (dest_col, dest_row):
                real_colliding_units.append(uid)
        if real_colliding_units:
            stats['unit_position_collisions'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'position': (dest_col, dest_row),
                'units': real_colliding_units + [move_unit_id],
                'action': 'move',
                'move_from': (start_col, start_row),
                'move_to': (dest_col, dest_row)
            })
        if (dest_col, dest_row) in state.wall_hexes:
            stats['wall_collisions'][player] += 1
    else:
        if require_key(state.unit_hp, move_unit_id) > 0:
            _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)

    if not stats['sample_actions']['move']:
        stats['sample_actions']['move'] = line.strip()
    return False  # skip normal move processing for FLED (was continue in original)


def _handle_move(state, config, line, action_desc, player, turn, phase, move_match,
                 _track_action_phase_accuracy, _position_cache_set,
                 _get_unit_hp_value, _build_occupied_positions,
                 _build_enemy_adjacent_hexes, _bfs_shortest_path_length,
                 get_adjacent_enemies, is_within_engine_engagement_zone,
                 _get_engagement_zone_for_analyzer, _debug_log):
    stats = state.stats
    move_unit_id = move_match.group(1)
    start_col = int(move_match.group(4))
    start_row = int(move_match.group(5))
    dest_col = int(move_match.group(6))
    dest_row = int(move_match.group(7))
    is_move_after_shooting = re.search(
        r'MOVED(?:\s+AFTER\s+SHOOTING)?\s+\[([^\]]+)\]\s+from',
        action_desc,
        re.IGNORECASE
    ) is not None and (
        "MOVED AFTER SHOOTING" in action_desc.upper()
        or re.search(
            r'MOVED\s+\[MOVE_AFTER_SHOOTING(?::\d+)?\]\s+from',
            action_desc,
            re.IGNORECASE
        ) is not None
    )
    move_unit_type = require_key(state.unit_types, move_unit_id)
    move_is_fly = re.search(r'MOVED\s+\[FLY\]\s+from', action_desc, re.IGNORECASE) is not None
    if is_move_after_shooting:
        move_is_fly = bool(require_key(config.unit_is_fly_by_type, move_unit_type))
        stats['move_after_shooting'][player] += 1
        stats['special_rule_usage'][("move_after_shooting", move_unit_type)][player] += 1
        state.units_moved_after_shooting_in_turn.add(move_unit_id)
    if is_move_after_shooting:
        _track_action_phase_accuracy(stats, "move_after_shooting", phase, state.current_episode_num, line)
    else:
        _track_action_phase_accuracy(stats, "move", phase, state.current_episode_num, line)

    stats['position_log_mismatch']['move']['total'] += 1
    if move_unit_id not in state.unit_positions:
        stats['position_log_mismatch']['move']['missing'] += 1
        if stats['first_error_lines']['position_log_mismatch']['move'] is None:
            stats['first_error_lines']['position_log_mismatch']['move'] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }
    elif state.unit_positions[move_unit_id] != (start_col, start_row):
        stats['position_log_mismatch']['move']['mismatch'] += 1
        if stats['first_error_lines']['position_log_mismatch']['move'] is None:
            stats['first_error_lines']['position_log_mismatch']['move'] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }

    # RULE: Dead unit moving
    move_unit_dead = move_unit_id not in state.unit_hp or require_key(state.unit_hp, move_unit_id) <= 0
    if move_unit_dead:
        unit_died_before_move = False
        phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
        current_phase_order = require_key(phase_order, phase)
        for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
            if dead_unit_id == move_unit_id:
                if death_turn < turn:
                    unit_died_before_move = True
                    break
                if death_turn == turn:
                    death_phase_order = require_key(phase_order, death_phase)
                    if death_phase_order < current_phase_order:
                        unit_died_before_move = True
                        break
                    if death_phase_order == current_phase_order and death_line_num < state.line_number:
                        unit_died_before_move = True
                        break
        if unit_died_before_move:
            stats['dead_unit_moving'][player] += 1
            if stats['first_error_lines']['dead_unit_moving'][player] is None:
                stats['first_error_lines']['dead_unit_moving'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    state.units_moved.add(move_unit_id)

    # Sync position cache with log start position
    if move_unit_id not in state.unit_positions or state.unit_positions[move_unit_id] != (start_col, start_row):
        _position_cache_set(state.unit_positions, move_unit_id, start_col, start_row)

    if move_unit_id not in state.positions_at_move_phase_start:
        state.positions_at_move_phase_start[move_unit_id] = (start_col, start_row)
        for uid, pos in state.unit_positions.items():
            if uid not in state.positions_at_move_phase_start:
                state.positions_at_move_phase_start[uid] = pos

    # RULE: Detect fled (adjacency at start of MOVE phase)
    if move_unit_id in state.positions_at_move_phase_start:
        start_pos = state.positions_at_move_phase_start[move_unit_id]
        enemy_player = 3 - player
        enemy_player_int = int(enemy_player) if enemy_player is not None else None
        enemy_positions_in_snapshot = {}
        for uid, pos in state.positions_at_move_phase_start.items():
            if uid not in state.unit_player or uid not in state.unit_hp:
                _debug_log(
                    f"[ANALYZER DEBUG] Snapshot adjacency missing unit data for unit_id: {uid} "
                    f"(episode={state.current_episode_num}, turn={turn}, phase={phase})"
                )
                continue
            hp_value = _get_unit_hp_value(
                state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Snapshot adjacency"
            )
            if hp_value is None:
                continue
            if (int(require_key(state.unit_player, uid)) if require_key(state.unit_player, uid) is not None else None) == enemy_player_int and hp_value > 0:
                enemy_positions_in_snapshot[uid] = pos
        enemy_positions_current = {}
        for uid, pos in state.unit_positions.items():
            if uid not in state.unit_player or uid not in state.unit_hp:
                _debug_log(
                    f"[ANALYZER DEBUG] Current adjacency missing unit data for unit_id: {uid} "
                    f"(episode={state.current_episode_num}, turn={turn}, phase={phase})"
                )
                continue
            hp_value = _get_unit_hp_value(
                state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Current adjacency"
            )
            if hp_value is None:
                continue
            if (int(require_key(state.unit_player, uid)) if require_key(state.unit_player, uid) is not None else None) == enemy_player_int and hp_value > 0:
                enemy_positions_current[uid] = pos
        was_adjacent_in_snapshot = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, enemy_positions_in_snapshot, state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=start_pos,
        )
        was_adjacent_in_current = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, enemy_positions_current, state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=start_pos,
        )
        if (was_adjacent_in_snapshot and was_adjacent_in_current and
                len(state.positions_at_move_phase_start) >= 2 and
                len(enemy_positions_current) > 0 and
                len(enemy_positions_in_snapshot) > 0):
            _debug_log(f"[FLED DEBUG] E{state.current_episode_num} T{turn} P{player}: Unit {move_unit_id} FLED from {start_pos} to ({dest_col},{dest_row}) - explicit FLED only (no inferred flag)")
        elif was_adjacent_in_snapshot and not was_adjacent_in_current:
            _debug_log(f"[FLED DEBUG] E{state.current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - snapshot says adjacent but current says not (stale positions in snapshot), NOT marking as fled")
        elif not was_adjacent_in_snapshot and was_adjacent_in_current:
            _debug_log(f"[FLED DEBUG] E{state.current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - current says adjacent but snapshot says not (stale positions in unit_positions), NOT marking as fled")
        elif len(enemy_positions_in_snapshot) == 0:
            _debug_log(f"[FLED DEBUG] E{state.current_episode_num} T{turn} P{player}: Unit {move_unit_id} at {start_pos} - no enemy data in snapshot, NOT marking as fled")

    if (start_col, start_row) != (dest_col, dest_row):
        if move_unit_id not in state.unit_movement_history:
            state.unit_movement_history[move_unit_id] = []
        timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
        timestamp = timestamp_match.group(1) if timestamp_match else None
        state.unit_movement_history[move_unit_id].append({
            'position': (dest_col, dest_row),
            'timestamp': timestamp,
            'action': 'move',
            'turn': turn,
            'episode': state.current_episode_num
        })

        if state.positions_at_move_phase_start:
            positions_at_movement = dict(state.positions_at_move_phase_start)
            for uid, pos in state.unit_positions.items():
                if uid in state.units_moved:
                    positions_at_movement[uid] = pos
        else:
            positions_at_movement = dict(state.unit_positions)

        unit_hp_at_movement = dict(state.unit_hp)

        if is_move_after_shooting:
            move_range = require_key(config.unit_move_after_shooting_distance_by_type, move_unit_type)
        else:
            move_range_raw = require_key(state.unit_move, move_unit_id)
            move_range = int(move_range_raw)
        occupied_positions = _build_occupied_positions(positions_at_movement, unit_hp_at_movement, move_unit_id)
        enemy_adjacent_hexes = _build_enemy_adjacent_hexes(positions_at_movement, state.unit_player, unit_hp_at_movement, player)

        # CONTRÔLE PER-SOCLE (03 Moving) : chaque figurine se déplace de SA position
        # d'origine (positions_by_model = état ligne N-1) vers SA destination (segment
        # [MODELS:] de cette ligne). En V11 l'ANCRE d'escouade peut faire un bond >
        # budget (reformation), alors que chaque socle reste ≤ budget → le contrôle
        # ancre-à-ancre produisait des faux « distance>budget » / « path blocked ».
        prev_models = state.positions_by_model.get(move_unit_id)
        new_models = state.current_line_models.get(move_unit_id)
        move_blocked = False
        move_over = False
        if prev_models and new_models:
            common_mids = [m for m in new_models if m in prev_models]
            checked_any = False
            for mid in common_mids:
                o_col, o_row = prev_models[mid]
                d_col, d_row = new_models[mid]
                if (o_col, o_row) == (d_col, d_row):
                    continue
                checked_any = True
                if move_is_fly:
                    if calculate_hex_distance(o_col, o_row, d_col, d_row) > move_range:
                        move_over = True
                else:
                    steps = _bfs_shortest_path_length(
                        o_col, o_row, d_col, d_row,
                        move_range, state.wall_hexes, occupied_positions, enemy_adjacent_hexes
                    )
                    if steps is None:
                        move_blocked = True
                    elif steps > move_range:
                        move_over = True
            if not checked_any:
                # Aucun socle commun n'a bougé (reformation pure autour de socles fixes) :
                # rien à valider côté distance.
                pass
        else:
            # Pas de données per-socle (log ancien/synthétique) → repli ancre legacy.
            if move_is_fly:
                if calculate_hex_distance(start_col, start_row, dest_col, dest_row) > move_range:
                    move_over = True
            else:
                shortest_steps = _bfs_shortest_path_length(
                    start_col, start_row, dest_col, dest_row,
                    move_range, state.wall_hexes, occupied_positions, enemy_adjacent_hexes
                )
                if shortest_steps is None:
                    move_blocked = True
                elif shortest_steps > move_range:
                    move_over = True

        if move_blocked:
            stats['move_path_blocked']['move'][player] += 1
            if stats['first_error_lines']['move_path_blocked']['move'][player] is None:
                stats['first_error_lines']['move_path_blocked']['move'][player] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }
        if move_over:
            if is_move_after_shooting:
                stats['move_after_shooting_distance_over_limit'][player] += 1
                if stats['first_error_lines']['move_after_shooting_distance_over_limit'][player] is None:
                    stats['first_error_lines']['move_after_shooting_distance_over_limit'][player] = {
                        'episode': state.current_episode_num, 'line': line.strip()
                    }
            else:
                stats['move_distance_over_limit']['move'][player] += 1
                if stats['first_error_lines']['move_distance_over_limit']['move'][player] is None:
                    stats['first_error_lines']['move_distance_over_limit']['move'][player] = {
                        'episode': state.current_episode_num, 'line': line.strip()
                    }

        # RULE: Position collision
        colliding_units_before = {}
        for uid, current_pos in state.unit_positions.items():
            if current_pos != (dest_col, dest_row) or uid == move_unit_id:
                continue
            if uid not in state.unit_hp:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Move collision missing unit_hp for unit_id: {uid}"
                })
                continue
            hp_value = _get_unit_hp_value(
                state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Move collision"
            )
            if hp_value is None:
                continue
            if hp_value > 0:
                colliding_units_before[uid] = current_pos

        if move_unit_id not in state.unit_hp:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Move action for unknown unit_id (missing in unit_hp): {move_unit_id}"
            })
            return True  # equivalent to continue
        if require_key(state.unit_hp, move_unit_id) > 0:
            _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)

        real_colliding_units = []
        for uid, pos_before in colliding_units_before.items():
            if (uid in state.unit_positions and
                    state.unit_positions[uid] == (dest_col, dest_row) and
                    state.unit_positions[uid] == pos_before and
                    uid in state.unit_hp and
                    require_key(state.unit_hp, uid) > 0):
                if uid in state.unit_movement_history:
                    has_moved_to_dest = any(
                        move['position'] == (dest_col, dest_row)
                        and move.get('turn') == turn
                        and move.get('episode') is not None
                        and move.get('episode') == state.current_episode_num
                        and state.current_episode_num > 0
                        for move in state.unit_movement_history[uid]
                    )
                    if has_moved_to_dest:
                        real_colliding_units.append(uid)
        if real_colliding_units:
            stats['unit_position_collisions'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'position': (dest_col, dest_row),
                'units': real_colliding_units + [move_unit_id],
                'action': 'move',
                'move_from': (start_col, start_row),
                'move_to': (dest_col, dest_row)
            })

        # RULE: Move to adjacent enemy
        positions_for_adjacency_check = dict(positions_at_movement)
        positions_for_adjacency_check[move_unit_id] = (dest_col, dest_row)
        positions_for_adjacency_check_filtered = {}
        for uid, hp_value in unit_hp_at_movement.items():
            if hp_value <= 0:
                continue
            pos = positions_for_adjacency_check.get(uid)
            if pos is None:
                _debug_log(
                    f"[ANALYZER DEBUG] Move adjacency missing position snapshot for unit_id: {uid} "
                    f"(episode={state.current_episode_num}, turn={turn}, phase={phase})"
                )
                continue
            positions_for_adjacency_check_filtered[uid] = pos
        positions_at_movement_filtered = {}
        for uid, hp_value in unit_hp_at_movement.items():
            if hp_value <= 0:
                continue
            pos = positions_at_movement.get(uid)
            if pos is None:
                _debug_log(
                    f"[ANALYZER DEBUG] Move adjacency (before) missing position snapshot for unit_id: {uid} "
                    f"(episode={state.current_episode_num}, turn={turn}, phase={phase})"
                )
                continue
            positions_at_movement_filtered[uid] = pos
        adjacent_before = get_adjacent_enemies(
            start_col, start_row, state.unit_player, positions_at_movement_filtered, unit_hp_at_movement, state.unit_types, player
        )
        if adjacent_before:
            stats['move_adjacent_before_non_flee'][player] += 1
            if stats['first_error_lines']['move_adjacent_before_non_flee'][player] is None:
                stats['first_error_lines']['move_adjacent_before_non_flee'][player] = {
                    'episode': state.current_episode_num,
                    'line': line.strip(),
                    'adjacent_before': adjacent_before
                }

        enemy_player = 3 - player
        enemy_player_int = int(enemy_player) if enemy_player is not None else None
        enemy_positions_str = ', '.join([f"Unit {uid} at {pos} (HP={require_key(unit_hp_at_movement, uid)})" for uid, pos in positions_for_adjacency_check_filtered.items() if (int(require_key(state.unit_player, uid)) if require_key(state.unit_player, uid) is not None else None) == enemy_player_int])
        _debug_log(f"[ANALYZER DEBUG] E{state.current_episode_num} T{turn} MOVE: Unit {move_unit_id} checking adjacency at ({dest_col},{dest_row}) against {len(positions_for_adjacency_check_filtered)} enemy positions: {enemy_positions_str}")
        dest_adjacent = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=(dest_col, dest_row),
        )
        if dest_adjacent:
            if not adjacent_before:
                stats['move_to_adjacent_enemy'][player] += 1
                if stats['first_error_lines']['move_to_adjacent_enemy'][player] is None:
                    adjacent_after = get_adjacent_enemies(dest_col, dest_row, state.unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement, state.unit_types, player)
                    stats['first_error_lines']['move_to_adjacent_enemy'][player] = {
                        'episode': state.current_episode_num,
                        'line': line.strip(),
                        'adjacent_before': adjacent_before,
                        'adjacent_after': adjacent_after
                    }

        # RULE: Move into wall
        if (dest_col, dest_row) in state.wall_hexes:
            stats['wall_collisions'][player] += 1
    else:
        if require_key(state.unit_hp, move_unit_id) > 0:
            _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)

    if not stats['sample_actions']['move']:
        stats['sample_actions']['move'] = line.strip()
    return False
