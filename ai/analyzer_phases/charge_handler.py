"""
charge_handler.py — gestion des actions CHARGE dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def handle_charge(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    line: str,
    action_desc: str,
    unit_id: str,
    player: int,
    turn: int,
    phase: str,
) -> None:
    """Traite une ligne d'action CHARGE (succès ou échec)."""
    from ai.analyzer import (
        _track_action_phase_accuracy,
        _position_cache_set,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        get_adjacent_enemies,
        _debug_log,
        _get_unit_hp_value,
    )

    stats = state.stats

    charge_match = re.search(
        r'Unit (\d+)\s*\((\d+),\s*(\d+)\)\s+CHARGED(?:\s+(?:\([A-Za-z0-9_ ]+\)|\[[A-Za-z0-9_ ]+\]))?\s+Unit (\d+)(?:\s*\((\d+),\s*(\d+)\))?\s+from \((\d+),\s*(\d+)\)\s+to \((\d+),\s*(\d+)\)',
        action_desc
    )
    if charge_match:
        charge_unit_id = charge_match.group(1)
        charge_target_id = charge_match.group(4)
        dest_col = int(charge_match.group(9))
        dest_row = int(charge_match.group(10))
        start_col = int(charge_match.group(7))
        start_row = int(charge_match.group(8))
        _track_action_phase_accuracy(stats, "charge", phase, state.current_episode_num, line)
        stats['charge_invalid'][player]['total'] += 1
        if charge_unit_id in state.units_advanced:
            charge_unit_type = require_key(state.unit_types, charge_unit_id)
            unit_rules = require_key(config.unit_rules_by_type, charge_unit_type)
            if "charge_after_advance" in unit_rules:
                key = ("charge_after_advance", charge_unit_type)
                stats['special_rule_usage'][key][player] += 1
            else:
                stats['charge_invalid'][player]['advanced'] += 1
                if stats['first_error_lines']['charge_invalid'][player] is None:
                    stats['first_error_lines']['charge_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        if charge_unit_id in state.units_fled:
            charge_unit_type_for_flee = require_key(state.unit_types, charge_unit_id)
            charge_unit_rules_for_flee = require_key(config.unit_rules_by_type, charge_unit_type_for_flee)
            if "charge_after_flee" in charge_unit_rules_for_flee:
                key = ("charge_after_flee", charge_unit_type_for_flee)
                stats['special_rule_usage'][key][player] += 1
            else:
                stats['charge_invalid'][player]['fled'] += 1
                if stats['first_error_lines']['charge_invalid'][player] is None:
                    stats['first_error_lines']['charge_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        charge_roll_match = re.search(r'\[Roll:(\d+)\]', action_desc)
        if charge_roll_match:
            charge_roll = int(charge_roll_match.group(1))
            charge_distance = calculate_hex_distance(start_col, start_row, dest_col, dest_row)
            if charge_distance > charge_roll:
                stats['charge_invalid'][player]['distance_over_roll'] += 1
                if stats['first_error_lines']['charge_invalid'][player] is None:
                    stats['first_error_lines']['charge_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

        stats['position_log_mismatch']['charge']['total'] += 1
        if charge_unit_id not in state.unit_positions:
            stats['position_log_mismatch']['charge']['missing'] += 1
            if stats['first_error_lines']['position_log_mismatch']['charge'] is None:
                stats['first_error_lines']['position_log_mismatch']['charge'] = {
                    'episode': state.current_episode_num,
                    'line': line.strip()
                }
        elif state.unit_positions[charge_unit_id] != (start_col, start_row):
            stats['position_log_mismatch']['charge']['mismatch'] += 1
            if stats['first_error_lines']['position_log_mismatch']['charge'] is None:
                stats['first_error_lines']['position_log_mismatch']['charge'] = {
                    'episode': state.current_episode_num,
                    'line': line.strip()
                }

        # RULE: Dead unit charging
        charge_unit_dead = charge_unit_id not in state.unit_hp or require_key(state.unit_hp, charge_unit_id) <= 0
        if charge_unit_dead:
            unit_died_before_charge = False
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == charge_unit_id:
                    if death_turn < turn:
                        unit_died_before_charge = True
                        break
                    if death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            unit_died_before_charge = True
                            break
                        if death_phase_order == current_phase_order and death_line_num < state.line_number:
                            unit_died_before_charge = True
                            break
            if unit_died_before_charge:
                stats['dead_unit_charging'][player] += 1
                if stats['first_error_lines']['dead_unit_charging'][player] is None:
                    stats['first_error_lines']['dead_unit_charging'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        if charge_unit_id in state.unit_hp and require_key(state.unit_hp, charge_unit_id) > 0:
            state.charged_units_current_fight.add(charge_unit_id)

        # CRITICAL: Sync position cache with log start position before processing
        if charge_unit_id in state.unit_positions and state.unit_positions[charge_unit_id] != (start_col, start_row):
            _position_cache_set(state.unit_positions, charge_unit_id, start_col, start_row)

        # RULE: Charge from adjacent
        if charge_unit_id not in state.units_advanced:
            if is_within_engine_engagement_zone(
                charge_unit_id,
                state.unit_player,
                state.unit_positions,
                state.unit_hp,
                engagement_zone=_get_engagement_zone_for_analyzer(),
                position_override=(start_col, start_row),
            ):
                adjacent_enemies = get_adjacent_enemies(start_col, start_row, state.unit_player, state.unit_positions, state.unit_hp, state.unit_types, player)
                if adjacent_enemies:
                    _debug_log(f"[CHARGE DEBUG] E{state.current_episode_num} T{turn} Unit {charge_unit_id} at ({start_col},{start_row}) is adjacent to enemies: {adjacent_enemies}")
                stats['charge_from_adjacent'][player] += 1
                if stats['first_error_lines']['charge_from_adjacent'][player] is None:
                    stats['first_error_lines']['charge_from_adjacent'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Charge after flee
        if charge_unit_id in state.units_fled:
            charge_unit_type_for_flee = require_key(state.unit_types, charge_unit_id)
            charge_unit_rules_for_flee = require_key(config.unit_rules_by_type, charge_unit_type_for_flee)
            if "charge_after_flee" in charge_unit_rules_for_flee:
                key = ("charge_after_flee", charge_unit_type_for_flee)
                stats['special_rule_usage'][key][player] += 1
            else:
                stats['charge_after_flee'][player] += 1
                if stats['first_error_lines']['charge_after_flee'][player] is None:
                    stats['first_error_lines']['charge_after_flee'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Charge a dead unit
        target_is_dead = charge_target_id not in state.unit_hp or require_key(state.unit_hp, charge_target_id) <= 0
        if target_is_dead:
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            target_died_before_charge = False
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == charge_target_id:
                    if death_turn < turn:
                        target_died_before_charge = True
                        break
                    elif death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            target_died_before_charge = True
                            break
                        elif death_phase_order == current_phase_order and death_line_num < state.line_number:
                            target_died_before_charge = True
                            break
            if target_died_before_charge:
                stats['charge_dead_unit'][player] += 1
                if stats['first_error_lines']['charge_dead_unit'][player] is None:
                    stats['first_error_lines']['charge_dead_unit'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # Record this movement in history
        if charge_unit_id not in state.unit_movement_history:
            state.unit_movement_history[charge_unit_id] = []
        timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
        timestamp = timestamp_match.group(1) if timestamp_match else None
        state.unit_movement_history[charge_unit_id].append({
            'position': (dest_col, dest_row),
            'timestamp': timestamp,
            'action': 'charge',
            'turn': turn,
            'episode': state.current_episode_num
        })

        # RULE: Position collision
        if (start_col, start_row) != (dest_col, dest_row):
            colliding_units_before = {}
            for uid, current_pos in state.unit_positions.items():
                if current_pos != (dest_col, dest_row) or uid == charge_unit_id:
                    continue
                if uid not in state.unit_hp:
                    stats['parse_errors'].append({
                        'episode': state.current_episode_num,
                        'turn': turn,
                        'phase': phase,
                        'line': line.strip(),
                        'error': f"Charge collision missing unit_hp for unit_id: {uid}"
                    })
                    continue
                hp_value = _get_unit_hp_value(
                    state.unit_hp,
                    uid,
                    stats,
                    state.current_episode_num,
                    turn,
                    phase,
                    line,
                    "Charge collision"
                )
                if hp_value is None:
                    continue
                if hp_value > 0:
                    colliding_units_before[uid] = current_pos

            if charge_unit_id not in state.unit_hp:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Charge action for unknown unit_id (missing in unit_hp): {charge_unit_id}"
                })
                return
            if require_key(state.unit_hp, charge_unit_id) > 0:
                _position_cache_set(state.unit_positions, charge_unit_id, dest_col, dest_row)

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
                    'units': real_colliding_units + [charge_unit_id],
                    'action': 'charge',
                    'charge_from': (start_col, start_row),
                    'charge_to': (dest_col, dest_row)
                })
        else:
            if require_key(state.unit_hp, charge_unit_id) > 0:
                _position_cache_set(state.unit_positions, charge_unit_id, dest_col, dest_row)

        # Sample action
        if not stats['sample_actions']['charge']:
            stats['sample_actions']['charge'] = line.strip()
    else:
        # Check if it's a FAILED charge
        failed_charge_match = re.search(
            r'Unit (\d+)\((\d+),\s*(\d+)\) FAILED CHARGE to unit (\d+)\((\d+),\s*(\d+)\)',
            action_desc,
            re.IGNORECASE
        )
        if failed_charge_match:
            if not stats['sample_actions']['charge']:
                stats['sample_actions']['charge'] = line.strip()
        else:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Charge action missing expected format: {action_desc[:100]}"
            })
