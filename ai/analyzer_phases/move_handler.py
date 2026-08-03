"""
move_handler.py — gestion des actions MOVE et FLED dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from shared.data_validation import require_key

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
        _build_move_bfs_blockers,
        _build_enemy_adjacent_hexes,
        _per_model_move_violation,
        get_adjacent_enemies,
    )
    # Import local : `analyzer_core` importe ce module au chargement (cycle sinon), comme les
    # helpers de `ai.analyzer` juste au-dessus.
    from ai.analyzer_core import move_line_re

    stats = state.stats

    # CRITICAL: Detect explicit FLED actions first.
    # Le token optionnel (`FLED [FLY] from`) est OBLIGATOIRE dans cette regex, comme dans celle
    # du MOVE : sans lui, une retraite volante n'est reconnue ni comme FLED ni comme MOVE, la
    # position de l'unité reste figée à son ancienne case, et TOUTES les adjacences calculées
    # ensuite le sont contre un fantôme (faux « move with adjacent_before » à l'autre bout du
    # plateau). Mesuré : 3 lignes non parsées suffisaient à en fabriquer 3.
    fled_match = move_line_re("FLED").search(action_desc)
    if fled_match:
        skip = _handle_fled(state, config, line, action_desc, player, turn, phase, fled_match,
                            _track_action_phase_accuracy, _position_cache_set, _debug_log,
                            _get_unit_hp_value)
        return skip

    move_match = move_line_re(r"MOVED(?:\s+AFTER\s+SHOOTING)?").search(action_desc)
    if move_match:
        skip = _handle_move(state, config, line, action_desc, player, turn, phase, move_match,
                            _track_action_phase_accuracy, _position_cache_set,
                            _get_unit_hp_value, _build_move_bfs_blockers,
                            _build_enemy_adjacent_hexes, _per_model_move_violation,
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
                 _get_unit_hp_value, _build_move_bfs_blockers,
                 _build_enemy_adjacent_hexes, _per_model_move_violation,
                 get_adjacent_enemies, is_within_engine_engagement_zone,
                 _get_engagement_zone_for_analyzer, _debug_log):
    from ai.analyzer_perfig import surviving_start_models
    from ai.analyzer import _get_inches_to_subhex_for_analyzer

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
    # 21.03 : la traversée FLY est DÉCLARÉE (« take to the skies »), pas acquise par le keyword —
    # une unité volante qui n'a pas déclaré marche et se heurte aux murs. Le marqueur du log est
    # donc la seule source correcte ; le keyword du registre exempterait à tort.
    move_is_fly = re.search(r'(?:MOVED|FLED)\s+\[FLY\]\s+from', action_desc, re.IGNORECASE) is not None
    if is_move_after_shooting:
        # 21.03 : le move-after-shooting n'est PAS un mouvement volant. `_fly_traversal_active`
        # ne rend vrai qu'en phase de move ou de charge ; celui-ci est construit en phase de
        # tir (`movement_build_valid_destinations_pool`), donc le moteur le pathfinde AU SOL et
        # n'écrit aucun `[FLY]`. Le keyword du registre exemptait ici toute unité volante du
        # BFS — un Gargoyle traversant un mur n'aurait jamais été remonté.
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
    else:
        from ai.analyzer_perfig import move_start_status, _DEFAULT_BASE
        _pos_status = move_start_status(
            state.positions_by_model.get(move_unit_id),
            state.unit_base.get(move_unit_id, _DEFAULT_BASE),
            state.unit_positions[move_unit_id],
            start_col, start_row,
            models_invalidated=move_unit_id in state.models_invalidated,
        )
        if _pos_status == 'mismatch':
            stats['position_log_mismatch']['move']['mismatch'] += 1
            if stats['first_error_lines']['position_log_mismatch']['move'] is None:
                stats['first_error_lines']['position_log_mismatch']['move'] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }
        elif _pos_status == 'absorbed':
            stats['position_log_mismatch']['move']['anchor_absorbed'] += 1

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
        # Socles de DÉPART, morts exclus (cf. surviving_start_models).
        start_models = surviving_start_models(
            state.positions_by_model.get(move_unit_id),  # get allowed
            state.current_line_models.get(move_unit_id),  # get allowed
        )
        was_adjacent_in_snapshot = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, enemy_positions_in_snapshot, state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=start_pos,
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            subject_models=start_models,
        )
        was_adjacent_in_current = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, enemy_positions_current, state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=start_pos,
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            subject_models=start_models,
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
            if move_is_fly:
                # 21.03 : le vol DÉCLARÉ retranche 2" à la distance max — même prédicat que la
                # traversée côté moteur (`get_squad_move_budget` / `took_to_the_skies`), donc
                # le marqueur `[FLY]` du journal atteste les deux. Le contrôle de la charge
                # retranchait déjà ces 2" ; move et advance ne le faisaient pas, si bien que les
                # trois contrôles « mutualisés » ne mesuraient pas la même chose : à x5, 30
                # subhex autorisés pour 20 légaux, et aucun vol hors budget n'était remonté.
                move_range = max(0, move_range - 2 * _get_inches_to_subhex_for_analyzer())
        occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
            state.positions_by_model, positions_at_movement, state.unit_base,
            state.unit_player, unit_hp_at_movement, move_unit_id,
        )

        # CONTRÔLE PER-SOCLE (03 Moving) : chaque figurine se déplace de SA position
        # d'origine (positions_by_model = état ligne N-1) vers SA destination (segment
        # [MODELS:] de cette ligne). En V11 l'ANCRE d'escouade peut faire un bond >
        # budget (reformation), alors que chaque socle reste ≤ budget → le contrôle
        # ancre-à-ancre produisait des faux « distance>budget » / « path blocked ».
        # Contrôle per-socle mutualisé avec advance, charge et pile-in/consolidation
        # (`_per_model_move_violation`). Les socles de DÉPART excluent les figurines mortes
        # entre-temps : le log ne dit pas laquelle est tombée, les garder mesurerait contre des
        # figurines retirées du plateau.
        move_over = _per_model_move_violation(
            surviving_start_models(
                state.positions_by_model.get(move_unit_id),  # get allowed
                state.current_line_models.get(move_unit_id),  # get allowed
            ),
            state.current_line_models.get(move_unit_id),  # get allowed
            (start_col, start_row), (dest_col, dest_row),
            move_range, move_is_fly,
            state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
        )
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
        # MÊME définition d'« engagé » que `dest_adjacent` ci-dessous : per-figurine, seuil
        # `engagement_zone`, métrique du run. Ce contrôle mesurait une adjacence d'ANCRE à
        # distance hex 1 — deux définitions dans la même fonction, et c'est la faible qui
        # commandait la forte (elle garde `move_to_adjacent_enemy`). À x5, `ez=10` mais
        # « distance d'ancre == 1 » n'est presque jamais vrai : la garde ne se levait plus et
        # tout mouvement finissant engagé était compté, y compris ceux qui l'étaient déjà.
        adjacent_before = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, positions_at_movement_filtered, unit_hp_at_movement,
            engagement_zone=_get_engagement_zone_for_analyzer(),
            position_override=(start_col, start_row),
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            subject_models=surviving_start_models(
                state.positions_by_model.get(move_unit_id),  # get allowed
                state.current_line_models.get(move_unit_id),  # get allowed
            ),
        )
        if adjacent_before:
            stats['move_adjacent_before_non_flee'][player] += 1
            if stats['first_error_lines']['move_adjacent_before_non_flee'][player] is None:
                stats['first_error_lines']['move_adjacent_before_non_flee'][player] = {
                    'episode': state.current_episode_num,
                    'line': line.strip(),
                }

        enemy_player = 3 - player
        enemy_player_int = int(enemy_player) if enemy_player is not None else None
        enemy_positions_str = ', '.join([f"Unit {uid} at {pos} (HP={require_key(unit_hp_at_movement, uid)})" for uid, pos in positions_for_adjacency_check_filtered.items() if (int(require_key(state.unit_player, uid)) if require_key(state.unit_player, uid) is not None else None) == enemy_player_int])
        _debug_log(f"[ANALYZER DEBUG] E{state.current_episode_num} T{turn} MOVE: Unit {move_unit_id} checking adjacency at ({dest_col},{dest_row}) against {len(positions_for_adjacency_check_filtered)} enemy positions: {enemy_positions_str}")
        dest_adjacent = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=(dest_col, dest_row),
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            # Socles d'ARRIVÉE : le `[MODELS:]` de CETTE ligne, pas l'état d'avant.
            subject_models=state.current_line_models.get(move_unit_id),  # get allowed
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
