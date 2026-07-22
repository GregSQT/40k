"""
analyzer_core.py — boucle principale de parse_step_log, extraite de analyzer.py.
Utilise AnalyzerState (state) et AnalyzerConfig (config) pour tout état mutable/config.
"""

import re
from typing import Dict, List, Tuple, Optional

from shared.data_validation import require_key, require_present
from engine.combat_utils import calculate_hex_distance

from ai.analyzer_state import AnalyzerState
from ai.analyzer_config import AnalyzerConfig
from ai.analyzer_phases.episode_handler import handle_episode_start
from ai.analyzer_phases.shoot_handler import handle_shoot, handle_wait, handle_skip, handle_advance
from ai.analyzer_phases.charge_handler import handle_charge
from ai.analyzer_phases.move_handler import handle_move_or_fled
from ai.analyzer_phases.fight_handler import handle_fight


PLAYER_ONE_ID = 1
PLAYER_TWO_ID = 2


def run(state: AnalyzerState, config: AnalyzerConfig, filepath: str) -> None:
    """Execute the main parsing loop. Modifies state.stats in-place."""
    from ai.analyzer import (
        _get_primary_objective_ids_for_scenario,
        _get_objective_name_to_id_map,
        _apply_damage_and_handle_death,
        _track_unit_reappearance,
        _position_cache_set,
        _position_cache_remove,
        _calculate_objective_control_snapshot,
        _calculate_primary_objective_points,
        _get_unit_hp_value,
        _track_action_phase_accuracy,
        _debug_log,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        is_adjacent,
        _build_occupied_positions,
        _build_enemy_adjacent_hexes,
        _bfs_shortest_path_length,
        has_line_of_sight,
        normalize_coordinates,
        parse_timestamp_to_seconds,
    )

    stats = state.stats
    unit_id: Optional[str] = None  # may be set from unit_start or deploy lines

    from ai.analyzer_perfig import parse_models_segment

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            state.line_number += 1
            # Segment per-figurine [MODELS:] : socles vivants de l'unité qui agit sur
            # CETTE ligne. On le stocke dans current_line_models (positions_by_model garde
            # l'état précédent pour les contrôles de move per-socle) puis on fusionne en fin
            # de traitement de la ligne. Aliveness pilotée par ce segment (résurrection des
            # unités faussement tuées par le modèle d'ancre 1-HP : cf. Class C engagement).
            # Fusionner d'abord les socles de la LIGNE PRÉCÉDENTE dans l'état persistant :
            # positions_by_model reflète alors tout jusqu'à la ligne N-1 (= positions
            # d'ORIGINE per-socle pour le contrôle de move de la ligne N), tandis que
            # current_line_models portera les positions de DESTINATION de la ligne N.
            for _muid, _mmodels in state.current_line_models.items():
                state.positions_by_model[_muid] = _mmodels
            state.current_line_models = parse_models_segment(line) or {}
            if state.current_line_models:
                for _uid, _models in state.current_line_models.items():
                    if not _models:
                        continue
                    # L'unité a des socles vivants sur le plateau -> elle est vivante.
                    # Réparer l'incohérence unit_positions/unit_hp créée par une "mort"
                    # d'ancre (HP_MAX squad = 1) alors que l'escouade a encore des figurines.
                    if _uid in state.unit_player:
                        if state.unit_hp.get(_uid, 0) <= 0:
                            state.unit_hp[_uid] = len(_models)
                            state.dead_units_current_episode.discard(_uid)
                        # Restaurer l'ancre si elle a été purgée par la fausse mort d'ancre :
                        # les handlers la resynchronisent ensuite depuis l'ancre loguée.
                        if _uid not in state.unit_positions:
                            _first_pos = next(iter(_models.values()))
                            _position_cache_set(state.unit_positions, _uid, _first_pos[0], _first_pos[1])

            # Episode start
            if '=== EPISODE' in line and 'START ===' in line:
                handle_episode_start(state, config, line)
                continue

            # Skip header lines
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or \
               line.startswith('NO STEP') or line.startswith('FAILED') or not line.strip():
                continue

            # Parse scenario
            scenario_match = re.search(r'Scenario: (.+)$', line)
            if scenario_match:
                state.current_scenario = scenario_match.group(1).strip()
                primary_objective_ids = _get_primary_objective_ids_for_scenario(state.current_scenario)
                state.primary_objective_configs = [
                    config.config_loader.load_primary_objective_config(obj_id)
                    for obj_id in primary_objective_ids
                ]
                continue

            # Parse walls
            wall_match = re.search(r'Walls: (.+)$', line)
            if wall_match:
                wall_str = wall_match.group(1).strip()
                if wall_str != 'none':
                    for coord_match in re.finditer(r'\((\d+),(\d+)\)', wall_str):
                        col, row = int(coord_match.group(1)), int(coord_match.group(2))
                        state.wall_hexes.add((col, row))
                continue

            # Parse objectives
            objectives_match = re.search(r'Objectives:\s*(.+)$', line)
            if objectives_match:
                objectives_payload = objectives_match.group(1).strip()
                if not objectives_payload:
                    raise ValueError(
                        f"Objectives line missing payload in episode {state.current_episode_num}: {line.strip()[:200]}"
                    )
                state.objective_hexes = {}
                # For temp scenarios (name contains __<hash>), the objectives file is gone;
                # build name→id from position so we can still parse the log.
                _inline_name_to_id: Dict[str, int] = {}
                _inline_next_id: int = 1
                for entry in objectives_payload.split('|'):
                    entry = entry.strip()
                    if not entry:
                        raise ValueError(
                            f"Objectives line contains empty entry in episode {state.current_episode_num}: {line.strip()[:200]}"
                        )
                    if ':' not in entry:
                        raise ValueError(
                            f"Objectives entry missing ':' in episode {state.current_episode_num}: {entry}"
                        )
                    name_part, hex_part = entry.split(':', 1)
                    name_part = name_part.strip()
                    obj_id_match = re.match(r'Obj(\d+)$', name_part)
                    if obj_id_match:
                        obj_id = int(obj_id_match.group(1))
                    else:
                        objective_name_map = _get_objective_name_to_id_map(state.current_scenario)
                        if name_part in objective_name_map:
                            obj_id = objective_name_map[name_part]
                        else:
                            # Temp scenario: assign sequential id from position in this line.
                            if name_part not in _inline_name_to_id:
                                _inline_name_to_id[name_part] = _inline_next_id
                                _inline_next_id += 1
                            obj_id = _inline_name_to_id[name_part]
                    if obj_id in state.objective_hexes:
                        raise ValueError(
                            f"Duplicate objective id {obj_id} in episode {state.current_episode_num}"
                        )
                    hexes: List[Tuple[int, int]] = []
                    for hex_str in hex_part.split(';'):
                        hex_str = hex_str.strip()
                        if not hex_str:
                            raise ValueError(
                                f"Empty objective hex in episode {state.current_episode_num}: {entry}"
                            )
                        coord_match = re.match(r'\((\d+),\s*(\d+)\)', hex_str)
                        if not coord_match:
                            raise ValueError(
                                f"Invalid objective hex '{hex_str}' in episode {state.current_episode_num}"
                            )
                        col, row = normalize_coordinates(
                            int(coord_match.group(1)),
                            int(coord_match.group(2)),
                        )
                        hexes.append((col, row))
                    if not hexes:
                        raise ValueError(
                            f"Objective {obj_id} has no hexes in episode {state.current_episode_num}"
                        )
                    state.objective_hexes[obj_id] = set(hexes)
                continue

            # Parse unit starting positions
            unit_start_match = re.match(r'.*Unit (\d+) \((\w+)\) P(\d+): Starting position \((-?\d+),\s*(-?\d+)\)', line)
            if unit_start_match:
                unit_id = str(unit_start_match.group(1))
                unit_type = unit_start_match.group(2)
                player = int(unit_start_match.group(3))
                col = int(unit_start_match.group(4))
                row = int(unit_start_match.group(5))
                
                # CRITICAL: Get HP_MAX from registry (REAL HP, not guessed)
                unit_data = require_key(config.unit_registry.units, unit_type)
                hp_max = require_key(unit_data, "HP_MAX")
                _debug_log(f"[ANALYZER] Unit {unit_id} ({unit_type}) HP_MAX={hp_max} from registry")
                unit_move_value = require_key(unit_data, "MOVE")
                
                # Initialize HP_CUR = HP_MAX (unit starts at full HP)
                state.unit_hp[unit_id] = hp_max
                
                state.unit_player[unit_id] = player
                _position_cache_set(state.unit_positions, unit_id, col, row)
                state.unit_types[unit_id] = unit_type
                stats['unit_types'][unit_id] = unit_type
                require_key(stats, 'unit_types_seen').add(unit_type)
                state.unit_move[unit_id] = unit_move_value * config.inches_to_subhex
                state.positions_at_turn_start[unit_id] = (col, row)
                state.unit_movement_history[unit_id] = [{"position": (col, row)}]
                base_token_match = re.search(r'base=\w+/(?:\d+|\[[^\]]*\])', line)
                if base_token_match:
                    from ai.analyzer_perfig import parse_base_token
                    state.unit_base[unit_id] = parse_base_token(base_token_match.group(0))
                continue

            # Parse unit deployment positions (authoritative start positions)
            deploy_match = re.match(
                r'.*E\d+\s+T\d+\s+P(\d+)\s+DEPLOYMENT\s+:\s+Unit\s+(\d+)\((\d+),\s*(\d+)\)\s+DEPLOYED\s+from\s+\((-?\d+),\s*(-?\d+)\)\s+to\s+\((\d+),\s*(\d+)\)',
                line
            )
            if deploy_match:
                player = int(deploy_match.group(1))
                unit_id = str(deploy_match.group(2))
                unit_type = state.unit_types.get(unit_id)
                if unit_type is None:
                    raise KeyError(f"Unit {unit_id} missing unit type before deployment parse")
                dest_col = int(deploy_match.group(7))
                dest_row = int(deploy_match.group(8))
                
                state.unit_player[unit_id] = player
                _position_cache_set(state.unit_positions, unit_id, dest_col, dest_row)
                state.positions_at_turn_start[unit_id] = (dest_col, dest_row)
                if unit_id not in state.unit_movement_history:
                    state.unit_movement_history[unit_id] = []
                state.unit_movement_history[unit_id].append({"position": (dest_col, dest_row)})
                continue

            # Episode end
            if 'EPISODE END' in line:
                if stats['current_episode_deaths']:
                    stats['death_orders'].append(tuple(stats['current_episode_deaths']))

                # Save turn distribution for this episode
                if state.episode_turn > 0:
                    stats['turns_distribution'][state.episode_turn] += 1
                stats['episode_lengths'].append((state.current_episode_num, state.episode_actions))
                
                # Calculate episode duration from Duration= field (wall-clock from step_logger)
                duration_match = re.search(r'Duration=(\d+(?:\.\d+)?)\s*s?\b', line)
                if not duration_match:
                    raise ValueError(
                        f"Missing Duration= in EPISODE END line for episode {state.current_episode_num}: "
                        f"{line.strip()[:200]}"
                    )
                duration_seconds = float(duration_match.group(1))
                stats['episode_durations'].append((state.current_episode_num, duration_seconds))

                winner_match = re.search(r'Winner=(-?\d+)', line)
                method_match = re.search(r'Method=(\w+)', line)

                if winner_match:
                    winner = int(winner_match.group(1))
                    win_method = method_match.group(1) if method_match else None

                    if winner == PLAYER_ONE_ID:
                        stats['wins_by_scenario'][state.current_scenario]['p1'] += 1
                    elif winner == PLAYER_TWO_ID:
                        stats['wins_by_scenario'][state.current_scenario]['p2'] += 1
                    elif winner == -1:
                        stats['wins_by_scenario'][state.current_scenario]['draws'] += 1

                    if win_method:
                        if winner in stats['win_methods'] and win_method in stats['win_methods'][winner]:
                            stats['win_methods'][winner][win_method] += 1
                        elif winner == -1:
                            stats['win_methods'][-1]['draw'] += 1
                    else:
                        stats['episodes_without_method'].append({
                            'winner': winner,
                            'line': line.strip()[:100]
                        })

                if state.primary_objective_configs:
                    if state.last_objective_snapshot is None:
                        raise ValueError(
                            f"Missing objective control snapshot at episode end {state.current_episode_num}"
                        )
                    if state.last_turn == 5 and state.last_player == PLAYER_TWO_ID:
                        for cfg in state.primary_objective_configs:
                            objective_id = require_key(cfg, "id")
                            score_key = (objective_id, state.last_turn, PLAYER_TWO_ID)
                            if score_key in state.scored_turns:
                                continue
                            points = _calculate_primary_objective_points(
                                state.last_objective_snapshot,
                                cfg,
                                PLAYER_TWO_ID
                            )
                            state.episode_victory_points[PLAYER_TWO_ID] += points
                            state.scored_turns.add(score_key)
                    stats['victory_points_by_episode'][state.current_episode_num] = {
                        PLAYER_ONE_ID: state.episode_victory_points[PLAYER_ONE_ID],
                        PLAYER_TWO_ID: state.episode_victory_points[PLAYER_TWO_ID],
                    }
                    stats['victory_points_values'][PLAYER_ONE_ID].append(
                        state.episode_victory_points[PLAYER_ONE_ID]
                    )
                    stats['victory_points_values'][PLAYER_TWO_ID].append(
                        state.episode_victory_points[PLAYER_TWO_ID]
                    )

                stats['current_episode_deaths'] = []
                stats['wounded_enemies'] = {1: set(), 2: set()}
                state.current_episode = []
                continue

            # Parse action line
            # Support both old format (T\d+) and new format (E\d+ T\d+)
            # STEP marker is optional (removed from logs)
            match = re.match(r'\[.*?\] (?:E\d+ )?T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\](?: \[STEP: (YES|NO)\])?', line)
            if match:
                turn = int(match.group(1))
                player = int(match.group(2))
                phase = match.group(3)
                action_desc = match.group(4)
                is_reactive_move = False
                success = match.group(5) == 'SUCCESS'
                step_marker_present = match.group(6) is not None
                step_inc = match.group(6) == 'YES' if step_marker_present else True
                rule_choice_line_match = re.match(
                    r'Unit (\d+)\((\d+),\s*(\d+)\) chose \[([^\]]+)\]',
                    action_desc,
                    re.IGNORECASE,
                )

                # CRITICAL: Apply damage regardless of STEP marker
                # Non-step lines still contain real attacks/shots and can kill units.
                # If we ignore STEP: NO damage, later rule checks (e.g., adjacency) can produce false positives
                # by treating dead units as alive.
                if re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+(\d+)',
                    action_desc,
                    re.IGNORECASE
                ):
                    target_match = re.search(
                        r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                        r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+(\d+)',
                        action_desc,
                        re.IGNORECASE
                    )
                    if target_match:
                        target_id = target_match.group(2)
                        damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                        if damage_match:
                            damage = int(damage_match.group(1))
                            # RULE: Shoot at dead unit (target already dead when shot)
                            if damage > 0:
                                target_already_dead = target_id not in state.unit_hp or require_key(state.unit_hp, target_id) <= 0
                                if target_already_dead:
                                    stats['shoot_at_dead_unit'][player] += 1
                                    if stats['first_error_lines']['shoot_at_dead_unit'][player] is None:
                                        stats['first_error_lines']['shoot_at_dead_unit'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
                            _apply_damage_and_handle_death(
                                target_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                                line, state.dead_units_current_episode, state.unit_hp, state.unit_types, state.unit_positions, state.unit_deaths, stats
                            )
                
                if 'attacked unit' in action_desc.lower() or 'fought unit' in action_desc.lower():
                    target_match = re.search(r'(?:ATTACKED|FOUGHT) Unit (\d+)', action_desc, re.IGNORECASE)
                    if target_match:
                        target_id = target_match.group(1)
                        damage_match = re.search(r'Dmg:(\d+)HP', action_desc)
                        if damage_match:
                            damage = int(damage_match.group(1))
                            _apply_damage_and_handle_death(
                                target_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                                line, state.dead_units_current_episode, state.unit_hp, state.unit_types, state.unit_positions, state.unit_deaths, stats
                            )
                
                # CHARGE IMPACT mortal wounds:
                # "Unit X(c,r) IMPACTED [...] Unit Y(c,r) - Hit:T+:N(HIT|FAIL) Wound:AUTO Save:NONE[MW] Dmg:ZHP"
                impact_damage_match = re.search(
                    r'IMPACTED\s+\[[^\]]+\]\s+Unit\s+(\d+)\(\d+,\d+\)\s+-\s+Hit:\d+\+:\d+\((?:HIT|FAIL)\)(?:\s+Wound:AUTO\s+Save:NONE\[MW\]\s+Dmg:(\d+)HP)?',
                    action_desc,
                    re.IGNORECASE
                )
                if impact_damage_match:
                    target_id = impact_damage_match.group(1)
                    damage_group = impact_damage_match.group(2)
                    damage = int(damage_group) if damage_group is not None else 0
                    if damage > 0:
                        _apply_damage_and_handle_death(
                            target_id, damage, player, turn, phase, state.line_number, state.current_episode_num,
                            line, state.dead_units_current_episode, state.unit_hp, state.unit_types, state.unit_positions, state.unit_deaths, stats
                        )

                # HAZARDOUS explicit self-destruction line:
                # "Unit X(c,r) was DESTROYED [HAZARDOUS]"
                hazardous_destroyed_match = re.search(
                    r'Unit\s+(\d+)\(\d+,\s*\d+\)\s+was\s+DESTROYED\s+\[HAZARDOUS\]',
                    action_desc,
                    re.IGNORECASE
                )
                if hazardous_destroyed_match:
                    destroyed_unit_id = hazardous_destroyed_match.group(1)
                    if destroyed_unit_id in state.unit_hp and require_key(state.unit_hp, destroyed_unit_id) > 0:
                        destroyed_unit_type = require_key(state.unit_types, destroyed_unit_id)
                        stats['current_episode_deaths'].append((player, destroyed_unit_id, destroyed_unit_type))
                        stats['wounded_enemies'][player].discard(destroyed_unit_id)
                        _position_cache_remove(state.unit_positions, destroyed_unit_id)
                        state.unit_deaths.append((turn, phase, destroyed_unit_id, state.line_number))
                        state.dead_units_current_episode.add(destroyed_unit_id)
                        _debug_log(
                            f"[DEATH REMOVED] E{state.current_episode_num} T{turn} {phase} "
                            f"target_id={destroyed_unit_id} target_type={destroyed_unit_type} reason=hazardous_destroyed_line"
                        )
                        del state.unit_hp[destroyed_unit_id]

                actor_match = re.match(r'Unit (\d+)\(', action_desc)
                if actor_match:
                    actor_id = actor_match.group(1)
                    _track_unit_reappearance(
                        actor_id,
                        state.unit_hp,
                        state.unit_player,
                        state.dead_units_current_episode,
                        state.revived_units_current_episode,
                        stats,
                        state.current_episode_num,
                        line
                    )
                    if rule_choice_line_match:
                        chosen_unit_id = rule_choice_line_match.group(1)
                        chosen_player = (
                            int(state.unit_player[chosen_unit_id])
                            if chosen_unit_id in state.unit_player
                            else int(player)
                        )
                        chosen_rule_label = rule_choice_line_match.group(4).strip().upper()
                        display_rule_ids = config.display_rule_name_to_ids.get(chosen_rule_label, set())
                        if len(display_rule_ids) != 1:
                            stats['rule_choice_selection_invalid'][chosen_player] += 1
                            if stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] is None:
                                stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] = {
                                    'episode': state.current_episode_num,
                                    'line': line.strip()
                                }
                            stats['parse_errors'].append({
                                'episode': state.current_episode_num,
                                'turn': turn,
                                'phase': phase,
                                'line': line.strip(),
                                'error': (
                                    f"Rule choice label '{chosen_rule_label}' is "
                                    f"{'unknown' if len(display_rule_ids) == 0 else 'ambiguous'}"
                                )
                            })
                        else:
                            selected_display_rule_id = next(iter(display_rule_ids))
                            selected_technical_rule_id = config.resolve_rule_id(
                                selected_display_rule_id
                            )
                            chosen_unit_type = require_key(state.unit_types, chosen_unit_id)
                            effect_to_sources_for_unit = config.unit_choice_effect_to_source_rules.get(
                                chosen_unit_type, {}
                            )
                            source_rule_ids = effect_to_sources_for_unit.get(
                                selected_technical_rule_id, set()
                            )
                            if not source_rule_ids:
                                stats['rule_choice_selection_invalid'][chosen_player] += 1
                                if stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] is None:
                                    stats['first_error_lines']['rule_choice_selection_invalid'][chosen_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }
                                stats['parse_errors'].append({
                                    'episode': state.current_episode_num,
                                    'turn': turn,
                                    'phase': phase,
                                    'line': line.strip(),
                                    'error': (
                                        f"Rule choice '{selected_technical_rule_id}' does not belong to "
                                        f"any choice source for unit type {chosen_unit_type}"
                                    )
                                })
                            else:
                                if chosen_unit_id not in state.selected_choice_by_unit_source:
                                    state.selected_choice_by_unit_source[chosen_unit_id] = {}
                                for source_rule_id in source_rule_ids:
                                    state.selected_choice_by_unit_source[chosen_unit_id][source_rule_id] = (
                                        selected_technical_rule_id
                                    )
                                key = (selected_technical_rule_id, chosen_unit_type)
                                stats['rule_choice_selection_usage'][key][chosen_player] += 1
                    action_desc_upper = action_desc.upper()
                    if not rule_choice_line_match:
                        actor_unit_type = require_key(state.unit_types, actor_id)
                        actor_player = (
                            int(state.unit_player[actor_id]) if actor_id in state.unit_player else int(player)
                        )
                        effect_to_sources_for_unit = config.unit_choice_effect_to_source_rules.get(
                            actor_unit_type, {}
                        )
                        if effect_to_sources_for_unit:
                            bracket_labels = re.findall(r'\[([^\]]+)\]', action_desc)
                            for raw_bracket_label in bracket_labels:
                                normalized_label = raw_bracket_label.strip().upper()
                                candidate_display_rule_ids = config.display_rule_name_to_ids.get(
                                    normalized_label, set()
                                )
                                for candidate_display_rule_id in candidate_display_rule_ids:
                                    candidate_technical_rule_id = config.resolve_rule_id(
                                        candidate_display_rule_id
                                    )
                                    if candidate_technical_rule_id not in effect_to_sources_for_unit:
                                        continue
                                    source_rule_ids = effect_to_sources_for_unit[candidate_technical_rule_id]
                                    if actor_id in state.selected_choice_by_unit_source:
                                        selected_sources = state.selected_choice_by_unit_source[actor_id]
                                    else:
                                        selected_sources = {}
                                    has_matching_source = any(
                                        selected_sources.get(source_rule_id) == candidate_technical_rule_id
                                        for source_rule_id in source_rule_ids
                                    )
                                    has_any_selection_for_sources = any(
                                        source_rule_id in selected_sources for source_rule_id in source_rule_ids
                                    )
                                    usage_key = (candidate_technical_rule_id, actor_unit_type)
                                    if has_matching_source:
                                        stats['rule_choice_usage'][usage_key]['correct'][actor_player] += 1
                                    elif has_any_selection_for_sources:
                                        stats['rule_choice_usage'][usage_key]['mismatch'][actor_player] += 1
                                        if stats['first_error_lines']['rule_choice_usage_mismatch'][actor_player] is None:
                                            stats['first_error_lines']['rule_choice_usage_mismatch'][actor_player] = {
                                                'episode': state.current_episode_num,
                                                'line': line.strip()
                                            }
                                    else:
                                        stats['rule_choice_usage'][usage_key]['missing'][actor_player] += 1
                                        if stats['first_error_lines']['rule_choice_usage_missing'][actor_player] is None:
                                            stats['first_error_lines']['rule_choice_usage_missing'][actor_player] = {
                                                'episode': state.current_episode_num,
                                                'line': line.strip()
                                            }
                    is_reactive_move = (
                        "REACTIVE MOVED" in action_desc_upper
                        or ("MOVED [" in action_desc_upper and " - TRIGGER: UNIT " in action_desc_upper)
                    )
                    is_move_after_shooting_marker = (
                        "MOVED AFTER SHOOTING" in action_desc_upper
                        or re.search(
                            r"MOVED\s+\[MOVE_AFTER_SHOOTING(?::\d+)?\]\s+FROM",
                            action_desc_upper,
                            re.IGNORECASE,
                        ) is not None
                    )
                    is_move_marker = (
                        ") MOVED" in action_desc_upper
                        and not is_reactive_move
                        and not is_move_after_shooting_marker
                    )
                    is_activation_marker = (
                        is_move_marker
                        or " ADVANCED " in action_desc_upper
                        or " CHARGED " in action_desc_upper
                        or " FAILED CHARGE " in action_desc_upper
                        or " FLED " in action_desc_upper
                    )
                    # Double-activation should only count unit activations, not per-shot/per-attack logs.
                    if phase in ('MOVE', 'SHOOT', 'CHARGE') and is_activation_marker:
                        if player is None:
                            raise ValueError("player is required for double-activation check")
                        phase_key = (turn, phase, int(player))
                        seen_units = state.phase_activation_seen.setdefault(phase_key, set())
                        if actor_id in seen_units:
                            double_activation_by_phase = require_key(stats, "double_activation_by_phase")
                            double_activation_by_phase[phase] += 1
                            first_errors = require_key(stats, "first_error_lines")
                            double_activation_first = require_key(first_errors, "double_activation_by_phase")
                            if double_activation_first[phase] is None:
                                double_activation_first[phase] = {'episode': state.current_episode_num, 'line': line.strip()}
                        else:
                            seen_units.add(actor_id)

                # Reset markers when turn changes
                if turn != state.last_turn:
                    state.units_moved = set()
                    state.units_shot = set()
                    # CRITICAL: Reset state.units_fled at the start of each turn
                    # According to AI_TURN.md and command_phase_start(), state.units_fled is reset at the start of each turn
                    # A unit that fled in T1 SHOULD be able to shoot/charge in T2
                    state.units_fled = set()
                    state.units_advanced = set()
                    state.units_fought = set()
                    state.charged_units_current_fight = set()
                    state.charged_units_fought = set()
                    state.units_moved_after_shooting_in_turn = set()
                    state.positions_at_turn_start = state.unit_positions.copy()
                    state.positions_at_move_phase_start = {}
                    state.last_player = None  # Reset last player on turn change
                    state.last_phase = None
                    state.last_shoot_shooter_id = None
                    state.last_shoot_weapon = None
                    state.last_shoot_target_id = None
                    state.last_fight_fighter_id = None
                    state.last_fight_weapon = None
                    state.last_turn = turn

                # Track positions at start of MOVE phase for fled detection
                # CRITICAL: Must track positions at the start of EACH player's MOVE phase, not just the first MOVE of the turn
                # When player changes OR when we see the first MOVE action of a turn, capture positions
                # BUT: Don't fill it yet - we'll fill it with positions "from" of MOVE actions below
                if phase == 'MOVE' and (state.last_player != player or not state.positions_at_move_phase_start):
                    # Don't fill state.positions_at_move_phase_start here - it will be filled below using "from" positions from log
                    state.positions_at_move_phase_start = {}
                
                # Update state.last_player after processing the action
                state.last_player = player

                if phase != state.last_phase:
                    if phase == 'COMMAND':
                        state.selected_choice_by_unit_source = {}
                    if phase == 'MOVE':
                        # Reset snapshot at the start of each MOVE phase
                        state.positions_at_move_phase_start = {}
                        state.charged_units_current_fight = set()
                        state.charged_units_fought = set()
                    if phase == 'SHOOT':
                        # Reset shot sequence counts at the start of each SHOOT phase
                        state.shot_sequence_counts = {}
                        state.last_shoot_shooter_id = None
                        state.last_shoot_weapon = None
                        state.last_shoot_target_id = None
                        state.units_moved_after_shooting_in_turn = set()
                        state.combi_profile_usage = {}
                        state.combi_conflicts_seen = set()
                    if phase == 'FIGHT':
                        state.fight_phase_seq_id += 1
                        state.last_fight_fighter_id = None
                        state.last_fight_weapon = None
                    state.last_phase = phase

                state.episode_turn = max(state.episode_turn, turn)

                if step_inc:
                    stats['total_actions'] += 1
                    state.episode_actions += 1
                    stats['actions_by_phase'][phase] += 1

                # REACTIVE MOVE metrics (normal + abnormal occurrences)
                # Supported log examples:
                # - "Unit X(...) REACTIVE MOVED from (...) to (...) [Roll: N]"
                # - "Unit X(...) MOVED [PREDATOR INSTINCT] from (...) to (...) [Roll: N] - trigger: Unit Y->(a,b)"
                # - "Unit X(...) DECLINED REACTIVE MOVE"
                reactive_decline_match = re.search(
                    r'Unit\s+(\d+).*DECLINED\s+REACTIVE\s+MOVE',
                    action_desc,
                    re.IGNORECASE
                )
                reactive_move_match = re.search(
                    r'Unit\s+(\d+)\((\d+),\s*(\d+)\)\s+'
                    r'(?:REACTIVE\s+MOVED(?:\s+\[[^\]]+\])?|MOVED\s+\[[^\]]+\])\s+'
                    r'from\s+\((\d+),\s*(\d+)\)\s+to\s+\((\d+),\s*(\d+)\)'
                    r'(?:\s+\[Roll:\s*(\d+)\])?',
                    action_desc,
                    re.IGNORECASE
                )
                # Guard against false reactive classification for normal keyword moves (e.g. MOVED [FLY]).
                # A move is reactive only when explicit reactive markers are present.
                if reactive_move_match and not is_reactive_move:
                    reactive_move_match = None

                if reactive_decline_match:
                    reactive_unit_id = reactive_decline_match.group(1)
                    reactive_player = state.unit_player.get(reactive_unit_id) if reactive_unit_id in state.unit_player else player
                    reactive_player = int(reactive_player) if reactive_player is not None else player
                    reactive_stats = require_key(stats, 'reactive_move_stats')
                    reactive_stats[reactive_player]['declined'] += 1

                if reactive_move_match:
                    reactive_unit_id = reactive_move_match.group(1)
                    reactive_player = state.unit_player.get(reactive_unit_id) if reactive_unit_id in state.unit_player else player
                    reactive_player = int(reactive_player) if reactive_player is not None else player
                    reactive_stats = require_key(stats, 'reactive_move_stats')
                    reactive_stats[reactive_player]['applied'] += 1
                    reactive_unit_type = require_key(state.unit_types, reactive_unit_id)
                    key = ("reactive_move", reactive_unit_type)
                    stats['special_rule_usage'][key][reactive_player] += 1
                    reactive_key = (state.current_episode_num, turn, reactive_player)
                    if reactive_key in state.reactive_activation_counts:
                        reactive_counts = state.reactive_activation_counts[reactive_key]
                    else:
                        reactive_counts = {}
                        state.reactive_activation_counts[reactive_key] = reactive_counts
                    if reactive_unit_id in reactive_counts:
                        reactive_counts[reactive_unit_id] += 1
                    else:
                        reactive_counts[reactive_unit_id] = 1
                    if reactive_counts[reactive_unit_id] == 2:
                        stats['double_activation_reactive_move'] += 1
                        first_errors = require_key(stats, "first_error_lines")
                        if first_errors['double_activation_reactive_move'] is None:
                            first_errors['double_activation_reactive_move'] = {
                                'episode': state.current_episode_num,
                                'line': line.strip()
                            }

                    from_col = int(reactive_move_match.group(4))
                    from_row = int(reactive_move_match.group(5))
                    to_col = int(reactive_move_match.group(6))
                    to_row = int(reactive_move_match.group(7))
                    roll_group = reactive_move_match.group(8)
                    roll_value = int(roll_group) if roll_group is not None else None
                    if reactive_unit_id not in state.unit_movement_history:
                        state.unit_movement_history[reactive_unit_id] = []
                    timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
                    timestamp = timestamp_match.group(1) if timestamp_match else None
                    state.unit_movement_history[reactive_unit_id].append({
                        'position': (to_col, to_row),
                        'timestamp': timestamp,
                        'action': 'reactive_move',
                        'turn': turn,
                        'episode': state.current_episode_num
                    })

                    reactive_abnormal = False
                    if phase not in ("MOVE", "SHOOT"):
                        reactive_abnormal = True
                    if roll_value is not None:
                        reactive_dist = calculate_hex_distance(from_col, from_row, to_col, to_row)
                        if reactive_dist > roll_value:
                            reactive_abnormal = True

                    if reactive_abnormal:
                        reactive_stats[reactive_player]['abnormal'] += 1
                        first_errors = require_key(stats, 'first_error_lines')
                        reactive_first = require_key(first_errors, 'reactive_move_abnormal')
                        if reactive_first[reactive_player] is None:
                            reactive_first[reactive_player] = {
                                'episode': state.current_episode_num,
                                'line': line.strip()
                            }

                    # Apply MOVE-like legality checks to reactive moves.
                    reactive_checks = require_key(stats, 'reactive_move_checks')
                    first_errors = require_key(stats, 'first_error_lines')

                    # Keep position cache aligned with log start position before validation.
                    if reactive_unit_id not in state.unit_positions or state.unit_positions[reactive_unit_id] != (from_col, from_row):
                        _position_cache_set(state.unit_positions, reactive_unit_id, from_col, from_row)

                    if reactive_unit_id not in state.unit_hp:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': f"Reactive move for unknown unit_id (missing in state.unit_hp): {reactive_unit_id}"
                        })
                    else:
                        unit_hp_at_reactive = dict(state.unit_hp)
                        positions_at_reactive = dict(state.unit_positions)
                        if (from_col, from_row) != (to_col, to_row):
                            if roll_value is not None:
                                occupied_positions = _build_occupied_positions(
                                    positions_at_reactive, unit_hp_at_reactive, reactive_unit_id
                                )
                                enemy_adjacent_hexes = _build_enemy_adjacent_hexes(
                                    positions_at_reactive, state.unit_player, unit_hp_at_reactive, reactive_player
                                )
                                shortest_steps = _bfs_shortest_path_length(
                                    from_col,
                                    from_row,
                                    to_col,
                                    to_row,
                                    int(roll_value),
                                    state.wall_hexes,
                                    occupied_positions,
                                    enemy_adjacent_hexes
                                )
                                if shortest_steps is None:
                                    reactive_checks['path_blocked'][reactive_player] += 1
                                    if first_errors['reactive_move_path_blocked'][reactive_player] is None:
                                        first_errors['reactive_move_path_blocked'][reactive_player] = {
                                            'episode': state.current_episode_num,
                                            'line': line.strip()
                                        }
                                elif shortest_steps > int(roll_value):
                                    reactive_checks['distance_over_roll'][reactive_player] += 1
                                    if first_errors['reactive_move_distance_over_roll'][reactive_player] is None:
                                        first_errors['reactive_move_distance_over_roll'][reactive_player] = {
                                            'episode': state.current_episode_num,
                                            'line': line.strip()
                                        }
                            else:
                                reactive_checks['distance_over_roll'][reactive_player] += 1
                                if first_errors['reactive_move_distance_over_roll'][reactive_player] is None:
                                    first_errors['reactive_move_distance_over_roll'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            positions_for_adjacency_check = dict(positions_at_reactive)
                            positions_for_adjacency_check[reactive_unit_id] = (to_col, to_row)
                            positions_for_adjacency_check_filtered = {}
                            for uid, hp_value in unit_hp_at_reactive.items():
                                if hp_value <= 0:
                                    continue
                                pos = positions_for_adjacency_check.get(uid)
                                if pos is None:
                                    continue
                                positions_for_adjacency_check_filtered[uid] = pos

                            reactive_dest_adjacent = is_within_engine_engagement_zone(
                                reactive_unit_id,
                                state.unit_player,
                                positions_for_adjacency_check_filtered,
                                unit_hp_at_reactive,
                                engagement_zone=_get_engagement_zone_for_analyzer(),
                                position_override=(to_col, to_row),
                            )
                            if reactive_dest_adjacent:
                                reactive_checks['to_adjacent_enemy'][reactive_player] += 1
                                if first_errors['reactive_move_to_adjacent_enemy'][reactive_player] is None:
                                    first_errors['reactive_move_to_adjacent_enemy'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            if (to_col, to_row) in state.wall_hexes:
                                reactive_checks['into_wall'][reactive_player] += 1
                                if first_errors['reactive_move_into_wall'][reactive_player] is None:
                                    first_errors['reactive_move_into_wall'][reactive_player] = {
                                        'episode': state.current_episode_num,
                                        'line': line.strip()
                                    }

                            if require_key(state.unit_hp, reactive_unit_id) > 0:
                                _position_cache_set(state.unit_positions, reactive_unit_id, to_col, to_row)

                # Determine action type and validate rules
                action_unit_id = require_present(unit_id, "unit_id")
                is_shoot_action = re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+\d+',
                    action_desc,
                    re.IGNORECASE
                ) is not None
                if not is_shoot_action:
                    state.last_shoot_shooter_id = None
                    state.last_shoot_weapon = None
                    state.last_shoot_target_id = None
                if re.search(
                    r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
                    r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit\s+\d+',
                    action_desc,
                    re.IGNORECASE
                ):
                        action_type = 'shoot'
                        handle_shoot(state, config, line, action_desc, action_unit_id, player, turn, phase, step_marker_present, step_inc)
                elif " WAIT" in action_desc:
                        action_type = 'wait'
                        if handle_wait(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                elif " SKIP" in action_desc:
                        action_type = 'skip'
                        handle_skip(state, line, action_desc, player, turn, phase)
                elif "ADVANCED from" in action_desc:
                        action_type = 'advance'
                        if handle_advance(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                elif re.search(r"CHARGED(?:\s+(?:\([A-Za-z0-9_ ]+\)|\[[A-Za-z0-9_ ]+\]))?\s+Unit", action_desc):
                        action_type = 'charge'
                        handle_charge(state, config, line, action_desc, action_unit_id, player, turn, phase)
                elif (
                    "MOVED from" in action_desc
                    or "MOVED AFTER SHOOTING" in action_desc
                    or ("MOVED [" in action_desc and " - trigger: Unit " not in action_desc)
                    or "FLED from" in action_desc
                ):
                        action_type = 'move'
                        fled_match_check = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) FLED from', action_desc)
                        if fled_match_check:
                            action_type = 'fled'
                        if handle_move_or_fled(state, config, line, action_desc, action_unit_id, player, turn, phase):
                            continue
                elif "FOUGHT Unit" in action_desc:
                        action_type = 'fight'
                        handle_fight(state, config, line, action_desc, action_unit_id, player, turn, phase, step_marker_present, step_inc)
                else:
                    action_type = 'other'

                if step_inc:
                    if not state.objective_hexes:
                        raise ValueError(
                            f"Objectives not parsed before step action in episode {state.current_episode_num}: "
                            f"{line.strip()[:200]}"
                        )
                    state.episode_step_index += 1
                    snapshot = _calculate_objective_control_snapshot(
                        state.objective_hexes,
                        state.objective_controllers,
                        state.unit_positions,
                        state.unit_player,
                        state.unit_types,
                        config.unit_registry,
                    )
                    stats['objective_control_history'][state.current_episode_num].append({
                        "step_index": state.episode_step_index,
                        "control": snapshot,
                    })
                    if not state.primary_objective_configs:
                        raise ValueError(
                            f"Primary objectives not loaded before step action in episode {state.current_episode_num}"
                        )
                    turn_player_key = (turn, player)
                    if turn >= 2 and turn_player_key not in state.seen_turn_player:
                        if turn == 5 and player == PLAYER_TWO_ID:
                            state.seen_turn_player.add(turn_player_key)
                        else:
                            if state.last_objective_snapshot is None:
                                raise ValueError(
                                    f"Missing objective control snapshot before scoring "
                                    f"(episode {state.current_episode_num}, turn {turn}, player {player})"
                                )
                            for cfg in state.primary_objective_configs:
                                objective_id = require_key(cfg, "id")
                                score_key = (objective_id, turn, player)
                                if score_key in state.scored_turns:
                                    continue
                                points = _calculate_primary_objective_points(
                                    state.last_objective_snapshot,
                                    cfg,
                                    player
                                )
                                state.episode_victory_points[player] += points
                                state.scored_turns.add(score_key)
                            state.seen_turn_player.add(turn_player_key)
                    state.last_objective_snapshot = snapshot

                stats['actions_by_type'][action_type] += 1
                stats['actions_by_player'][player][action_type] += 1

                state.current_episode.append(line.strip())
    
    # Check if last episode ended without EPISODE END
    if state.current_episode:
        stats['episodes_without_end'].append({
            'episode_num': state.current_episode_num,
            'actions': state.episode_actions,
            'turn': state.episode_turn,
            'last_line': state.current_episode[-1][:100] if state.current_episode else 'N/A'
        })
        
        stats['episode_lengths'].append((state.current_episode_num, state.episode_actions))
        # Save turn distribution for last episode
        if state.episode_turn > 0:
            stats['turns_distribution'][state.episode_turn] += 1

