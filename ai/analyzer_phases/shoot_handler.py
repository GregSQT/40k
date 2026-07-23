"""
shoot_handler.py — gestion des actions SHOT, WAIT, SKIP, ADVANCED dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING, Any

from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, ranged_edge_distance, get_distance_metric

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def _analyzer_ranged_metric(config: "AnalyzerConfig") -> str:
    """Métrique de portée tir (hex|euclidean) — même sélecteur unique que le moteur."""
    return get_distance_metric("ranged", config.config_loader.get_game_config())


def _analyzer_socle(config: "AnalyzerConfig", unit_type: str, col: int, row: int) -> Any:
    """Socle d'une unité à une position, empreinte reconstruite depuis le registry.

    Portée tir euclidienne bord-à-bord (règle 01.04) : l'analyzer mesure comme le
    moteur en rebâtissant l'empreinte à partir de BASE_SHAPE/BASE_SIZE.
    """
    from engine.hex_utils import Socle, compute_occupied_hexes
    data = config.unit_registry.get_unit_data(unit_type)
    shape = require_key(data, "BASE_SHAPE")
    size = require_key(data, "BASE_SIZE")
    fp = compute_occupied_hexes(int(col), int(row), shape, size)
    return Socle(shape, size, int(col), int(row), fp)


def handle_shoot(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    line: str,
    action_desc: str,
    unit_id: str,
    player: int,
    turn: int,
    phase: str,
    step_marker_present: bool,
    step_inc: bool,
) -> None:
    """Traite une ligne d'action SHOT."""
    from ai.analyzer import (
        _track_action_phase_accuracy,
        _position_cache_set,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        _debug_log,
        has_line_of_sight,
        _get_unit_hp_value,
    )

    stats = state.stats
    shooter_match = re.search(r'Unit (\d+)\s*\((\d+),\s*(\d+)\)', action_desc)
    target_match = re.search(
        r'\bSHOT(?:\s+\([A-Za-z0-9_ ]+\)|\s+\[[^\]]+\])*'
        r'(?:\s+\[RAPID(?: |_)?FIRE:(\d+)\])?\s+(?:at\s+)?Unit (\d+)(?:\s*\((\d+),\s*(\d+)\))?',
        action_desc,
        re.IGNORECASE
    )

    stats['shoot_vs_wait']['shoot'] += 1
    stats['shoot_vs_wait_by_player'][player]['shoot'] += 1

    if not (shooter_match and target_match):
        if not stats['sample_actions']['shoot']:
            stats['sample_actions']['shoot'] = line.strip()
        return

    shooter_id = shooter_match.group(1)
    shooter_col = int(shooter_match.group(2))
    shooter_row = int(shooter_match.group(3))
    target_id = target_match.group(2)
    state.units_shot.add(shooter_id)
    stats['shoot_invalid'][player]['total'] += 1
    _track_action_phase_accuracy(stats, "shoot", phase, state.current_episode_num, line)

    if (
        shooter_id in state.units_moved_after_shooting_in_turn
        and shooter_id in state.unit_positions
        and state.unit_positions[shooter_id] != (shooter_col, shooter_row)
    ):
        _debug_log(
            f"[ANALYZER DEBUG] Keep post-shot position for shooter {shooter_id}: "
            f"cache={state.unit_positions[shooter_id]} shot_line=({shooter_col},{shooter_row})"
        )
    else:
        _position_cache_set(state.unit_positions, shooter_id, shooter_col, shooter_row)

    if target_match.group(3) and target_match.group(4):
        target_col = int(target_match.group(3))
        target_row = int(target_match.group(4))
        target_pos = (target_col, target_row)
        if target_id in state.unit_hp and require_key(state.unit_hp, target_id) > 0:
            _position_cache_set(state.unit_positions, target_id, target_col, target_row)
    elif target_id in state.unit_positions:
        target_pos = state.unit_positions[target_id]
    else:
        target_pos = None

    # RULE: Dead unit shooting
    shooter_is_dead = shooter_id in state.unit_hp and require_key(state.unit_hp, shooter_id) <= 0
    if shooter_is_dead:
        is_false_positive = False
        phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
        current_phase_order = require_key(phase_order, phase)
        unit_died_before_shoot = False
        for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
            if dead_unit_id == shooter_id:
                if death_turn < turn:
                    unit_died_before_shoot = True
                    break
                elif death_turn == turn:
                    death_phase_order = require_key(phase_order, death_phase)
                    if death_phase_order < current_phase_order:
                        unit_died_before_shoot = True
                        break
                    elif death_phase_order == current_phase_order and death_line_num < state.line_number:
                        unit_died_before_shoot = True
                        break
                    elif death_phase_order == current_phase_order and death_line_num > state.line_number:
                        is_false_positive = True
                        break
        if unit_died_before_shoot and not is_false_positive:
            stats['shoot_dead_unit'][player] += 1
            if stats['first_error_lines']['shoot_dead_unit'][player] is None:
                stats['first_error_lines']['shoot_dead_unit'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # RULE: Shoot after flee
    if str(shooter_id) in state.units_fled:
        shooter_unit_type_for_flee = require_key(state.unit_types, shooter_id)
        shooter_unit_rules_for_flee = require_key(config.unit_rules_by_type, shooter_unit_type_for_flee)
        if "shoot_after_flee" in shooter_unit_rules_for_flee:
            key = ("shoot_after_flee", shooter_unit_type_for_flee)
            stats['special_rule_usage'][key][player] += 1
        else:
            stats['shoot_after_flee'][player] += 1
            if stats['first_error_lines']['shoot_after_flee'][player] is None:
                stats['first_error_lines']['shoot_after_flee'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # RULE METRICS: Targeted Intercession reroll (shooting)
    shooter_unit_type_for_reroll = require_key(state.unit_types, shooter_id)
    if re.search(r'\(TARGETED_INTERCESSION\)', action_desc, re.IGNORECASE):
        key = ("reroll_1_towound", shooter_unit_type_for_reroll)
        stats['special_rule_usage'][key][player] += 1
        key = ("reroll_towound_target_on_objective", shooter_unit_type_for_reroll)
        stats['special_rule_usage'][key][player] += 1

    # RULE: Shoot at friendly
    shooter_actual_player = require_key(state.unit_player, shooter_id)
    shooter_actual_player_int = int(shooter_actual_player) if shooter_actual_player is not None else None
    target_player = state.unit_player.get(target_id) if target_id in state.unit_player else None
    target_player_int = int(target_player) if target_player is not None else None
    if target_id in state.unit_player and shooter_actual_player_int is not None and target_player_int == shooter_actual_player_int:
        stats['shoot_at_friendly'][shooter_actual_player] += 1
        if stats['first_error_lines']['shoot_at_friendly'][shooter_actual_player] is None:
            stats['first_error_lines']['shoot_at_friendly'][shooter_actual_player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # RULE: Shoot through wall — contrôle SUPPRIMÉ (2026-07-16).
    #
    # Il testait la LoS ANCRE-A-ANCRE (`has_line_of_sight(shooter_col, shooter_row, ...)`), alors
    # que la règle 06.01 exige « any part of the observing model to any part of the model being
    # observed » : la LoS est socle-à-socle, PAR FIGURINE. Pire, les coords du step.log sont les
    # ancres d'ESCOUADE (`_emit_squad_shoot_log`, shared_utils ~L5758), pas la figurine tireuse
    # que le moteur a réellement testée (`_attacker_model_can_reach_squad`, shared_utils L4483 /
    # L5299) — le contrôle évaluait donc un prédicat sur des points que le moteur n'a jamais
    # utilisés. Sur un run réel : 6 faux positifs / 9 tirs P1, zéro vraie violation.
    #
    # Non réparable ici : reproduire fidèlement le prédicat moteur exige `game_state`
    # (empreintes de socles, terrain obscurcissant 13.10, LoS 3D plancher-occulteur) que
    # step.log ne porte pas et ne portera pas. Un contrôle post-hoc sur log est structurellement
    # incapable d'être correct.
    #
    # La vérification n'est pas abandonnée, elle est DEPLACEE là où `game_state` existe :
    # tests/unit/engine/test_shoot_los_perfig_parity.py (parité ancre↔per-figurine).
    # Le tir reste par ailleurs gaté à la source par `_attacker_model_can_reach_squad`.

    weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
    is_pistol = False
    weapon_found = False
    weapon_range = None
    shooter_unit_type = require_key(state.unit_types, shooter_id)
    shooter_player_from_types = require_key(state.unit_player, shooter_id)
    weapon_info_matched = None
    weapon_display_name = None

    if weapon_match:
        weapon_display_name = weapon_match.group(1)
        weapon_name_lower = weapon_display_name.lower()
        weapons_info = require_key(config.unit_weapons_cache, shooter_unit_type)
        for weapon_info in weapons_info:
            if weapon_info['name'].lower() == weapon_name_lower:
                is_pistol = weapon_info['is_pistol']
                weapon_range = weapon_info['range']
                weapon_found = True
                weapon_info_matched = weapon_info
                break
        if not weapon_found and shooter_unit_type:
            tyranid_weapons = ['deathspitter', 'fleshborer', 'devourer', 'scything talons', 'bonesword', 'lash whip']
            space_marine_weapons = ['bolt rifle', 'bolt pistol', 'chainsword', 'power sword', 'power fist', 'stalker bolt rifle']
            weapon_is_tyranid = any(tyranid_wpn in weapon_name_lower for tyranid_wpn in tyranid_weapons)
            weapon_is_space_marine = any(sm_wpn in weapon_name_lower for sm_wpn in space_marine_weapons)
            unit_is_space_marine = 'intercessor' in shooter_unit_type.lower() or 'captain' in shooter_unit_type.lower() or 'spacemarine' in shooter_unit_type.lower()
            unit_is_tyranid = 'tyranid' in shooter_unit_type.lower() or 'genestealer' in shooter_unit_type.lower() or 'hormagaunt' in shooter_unit_type.lower() or 'termagant' in shooter_unit_type.lower()
            if (weapon_is_tyranid and unit_is_space_marine) or (weapon_is_space_marine and unit_is_tyranid):
                if 'unit_id_mismatches' not in stats:
                    stats['unit_id_mismatches'] = []
                stats['unit_id_mismatches'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'shooter_id_logged': shooter_id,
                    'shooter_type_registered': shooter_unit_type,
                    'shooter_player_registered': shooter_player_from_types,
                    'weapon_logged': weapon_display_name,
                    'shooter_position': (shooter_col, shooter_row),
                    'line': line.strip()
                })

    if weapon_match and weapon_display_name is not None:
        if shooter_unit_type:
            limits = require_key(config.unit_attack_limits, shooter_unit_type)
            rng_nb_by_weapon = require_key(limits, "rng_nb_by_weapon")
            rapid_fire_by_weapon = require_key(limits, "rapid_fire_by_weapon")
            weapon_name_for_limits = weapon_display_name.strip()
            from ai.analyzer_perfig import resolve_weapon_value
            rng_nb = resolve_weapon_value(
                weapon_name_for_limits, rng_nb_by_weapon, config.rng_nb_by_weapon_global
            )
            if rng_nb is None:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Weapon '{weapon_name_for_limits}' missing RNG_NB for unit type {shooter_unit_type}"
                })
            else:
                rapid_fire_value = resolve_weapon_value(
                    weapon_name_for_limits, rapid_fire_by_weapon, config.rapid_fire_by_weapon_global
                )
                if rapid_fire_value is None:
                    rapid_fire_value = 0
                rapid_fire_match = re.search(r'\[RAPID(?: |_)?FIRE:(\d+)\]', action_desc, re.IGNORECASE)
                rapid_fire_bonus_for_this_shot = 0
                if rapid_fire_match:
                    rapid_fire_logged_value = int(rapid_fire_match.group(1))
                    if rapid_fire_value <= 0:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': (
                                f"RAPID FIRE marker present for weapon without RAPID_FIRE rule: "
                                f"{shooter_unit_type}/{weapon_name_for_limits}"
                            )
                        })
                    elif rapid_fire_logged_value != rapid_fire_value:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': (
                                f"RAPID FIRE marker value mismatch for {shooter_unit_type}/{weapon_name_for_limits}: "
                                f"log={rapid_fire_logged_value}, expected={rapid_fire_value}"
                            )
                        })
                    else:
                        rapid_fire_bonus_for_this_shot = rapid_fire_value
                combi_key = None
                if shooter_unit_type in config.unit_combi_by_weapon:
                    combi_by_weapon = config.unit_combi_by_weapon[shooter_unit_type]
                    if weapon_name_for_limits in combi_by_weapon:
                        combi_key = combi_by_weapon[weapon_name_for_limits]
                if combi_key is not None:
                    if shooter_id not in state.combi_profile_usage:
                        state.combi_profile_usage[shooter_id] = {}
                    if combi_key not in state.combi_profile_usage[shooter_id]:
                        state.combi_profile_usage[shooter_id][combi_key] = set()
                    combi_profiles = state.combi_profile_usage[shooter_id][combi_key]
                    combi_profiles.add(weapon_name_for_limits)
                    conflict_key = (state.current_episode_num, turn, shooter_id, combi_key)
                    if len(combi_profiles) > 1 and conflict_key not in state.combi_conflicts_seen:
                        shooter_player_for_stats = require_key(state.unit_player, shooter_id)
                        stats['shoot_combi_profile_conflicts'][shooter_player_for_stats] += 1
                        if stats['first_error_lines']['shoot_combi_profile_conflicts'][shooter_player_for_stats] is None:
                            stats['first_error_lines']['shoot_combi_profile_conflicts'][shooter_player_for_stats] = {
                                'episode': state.current_episode_num,
                                'line': line.strip()
                            }
                        state.combi_conflicts_seen.add(conflict_key)
                seq_key = (state.current_episode_num, turn, shooter_id, weapon_name_for_limits)
                if (state.last_shoot_shooter_id != shooter_id or
                        state.last_shoot_weapon != weapon_name_for_limits):
                    state.shot_sequence_counts[seq_key] = 0
                elif step_marker_present and step_inc:
                    state.shot_sequence_counts[seq_key] = 0
                if seq_key not in state.shot_sequence_counts:
                    state.shot_sequence_counts[seq_key] = 0
                state.shot_sequence_counts[seq_key] += 1
                current_shot_index = state.shot_sequence_counts[seq_key]
                shooter_player_for_stats = require_key(state.unit_player, shooter_id)
                # Class B (comptage per-figurine) : le plafond de tirs d'une escouade =
                # (nb de socles vivants qui tirent) × NB par modèle. Les socles vivants sont
                # listés dans le segment [MODELS:] de la ligne (current_line_models). Sans
                # segment (logs anciens/synthétiques) → 1 modèle (comportement ancre legacy).
                n_shooter_models = len(state.current_line_models.get(shooter_id, {})) or 1
                rng_nb_squad = rng_nb * n_shooter_models
                rapid_fire_value_squad = rapid_fire_value * n_shooter_models
                rapid_fire_bonus_window = (
                    rapid_fire_value > 0
                    and current_shot_index > rng_nb_squad
                    and current_shot_index <= (rng_nb_squad + rapid_fire_value_squad)
                )
                rapid_fire_marker_valid = (
                    rapid_fire_match is not None
                    and rapid_fire_bonus_for_this_shot > 0
                )
                if rapid_fire_bonus_window and rapid_fire_marker_valid:
                    stats['rapid_fire_correct'][shooter_player_for_stats] += 1
                elif rapid_fire_bonus_window != rapid_fire_marker_valid:
                    stats['rapid_fire_incorrect'][shooter_player_for_stats] += 1
                    if stats['first_error_lines']['rapid_fire_incorrect'][shooter_player_for_stats] is None:
                        stats['first_error_lines']['rapid_fire_incorrect'][shooter_player_for_stats] = {
                            'episode': state.current_episode_num,
                            'line': line.strip(),
                        }
                max_allowed_shots = rng_nb_squad + (
                    rapid_fire_value_squad if rapid_fire_bonus_for_this_shot > 0 else 0
                )
                if state.shot_sequence_counts[seq_key] > max_allowed_shots:
                    stats['shoot_over_rng_nb'][shooter_player_for_stats] += 1
                    if stats['first_error_lines']['shoot_over_rng_nb'][shooter_player_for_stats] is None:
                        stats['first_error_lines']['shoot_over_rng_nb'][shooter_player_for_stats] = {'episode': state.current_episode_num, 'line': line.strip()}
                state.last_shoot_shooter_id = shooter_id
                state.last_shoot_weapon = weapon_name_for_limits
                state.last_shoot_target_id = target_id

    # DEVASTATING_WOUNDS checks
    dw_flag_match = re.search(r'\[DEVASTATING WOUNDS\]', action_desc, re.IGNORECASE)
    wound_roll_match = re.search(r'Wound\s+(\d+)\((\d+)\+\)', action_desc, re.IGNORECASE)
    save_attempt_match = re.search(r'Save\s+(\d+)\((\d+)\+\)', action_desc, re.IGNORECASE)
    save_skipped_dw_match = re.search(r'Save\s+\[DEVASTATING WOUNDS\]', action_desc, re.IGNORECASE)
    if dw_flag_match and wound_roll_match:
        wound_roll_value = int(wound_roll_match.group(1))
        shooter_player_for_dw = require_key(state.unit_player, shooter_id)
        if wound_roll_value == 6 and save_skipped_dw_match:
            stats['devastating_wounds_correct'][shooter_player_for_dw] += 1
        elif wound_roll_value < 6 or (wound_roll_value == 6 and save_attempt_match):
            stats['devastating_wounds_incorrect'][shooter_player_for_dw] += 1
            if stats['first_error_lines']['devastating_wounds_incorrect'][shooter_player_for_dw] is None:
                stats['first_error_lines']['devastating_wounds_incorrect'][shooter_player_for_dw] = {
                    'episode': state.current_episode_num,
                    'line': line.strip(),
                }

    # RULE: Shoot at engaged enemy
    if target_pos:
        if target_id not in state.unit_player:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Engagement check missing unit_player for target_id: {target_id}"
            })
            target_engaged = False
        else:
            missing_ids = [uid for uid in state.unit_positions if uid not in state.unit_hp or uid not in state.unit_player]
            for missing_id in missing_ids:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Engagement check missing unit data for unit_id: {missing_id}"
                })
            positions_for_engagement = {
                uid: pos for uid, pos in state.unit_positions.items()
                if uid in state.unit_hp and uid in state.unit_player
            }
            target_engaged = is_within_engine_engagement_zone(
                target_id,
                state.unit_player,
                positions_for_engagement,
                state.unit_hp,
                engagement_zone=_get_engagement_zone_for_analyzer(),
                position_override=target_pos,
            )
    elif target_id in state.unit_positions:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Engagement check missing target_pos in log; using unit_positions for target_id: {target_id}"
        })
        if target_id not in state.unit_player:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Engagement check missing unit_player for target_id: {target_id}"
            })
            target_engaged = False
        else:
            missing_ids = [uid for uid in state.unit_positions if uid not in state.unit_hp or uid not in state.unit_player]
            for missing_id in missing_ids:
                stats['parse_errors'].append({
                    'episode': state.current_episode_num,
                    'turn': turn,
                    'phase': phase,
                    'line': line.strip(),
                    'error': f"Engagement check missing unit data for unit_id: {missing_id}"
                })
            positions_for_engagement = {
                uid: pos for uid, pos in state.unit_positions.items()
                if uid in state.unit_hp and uid in state.unit_player
            }
            target_pos_from_cache = positions_for_engagement.get(target_id)
            if target_pos_from_cache:
                target_engaged = is_within_engine_engagement_zone(
                    target_id,
                    state.unit_player,
                    positions_for_engagement,
                    state.unit_hp,
                    engagement_zone=_get_engagement_zone_for_analyzer(),
                    position_override=target_pos_from_cache,
                )
            else:
                target_engaged = False
    else:
        target_engaged = False

    if target_engaged and not is_pistol:
        stats['shoot_at_engaged_enemy'][player] += 1
        if stats['first_error_lines']['shoot_at_engaged_enemy'][player] is None:
            stats['first_error_lines']['shoot_at_engaged_enemy'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # Track PISTOL weapon shots
    heavy_applied_in_log = re.search(r'(?:\[\s*HEAVY\s*\]|\sHEAVY\s)', action_desc, re.IGNORECASE) is not None
    if weapon_match and target_pos and weapon_found:
        distance = calculate_hex_distance(shooter_col, shooter_row, target_pos[0], target_pos[1])
        shooter_engaged = is_within_engine_engagement_zone(
            shooter_id,
            state.unit_player,
            state.unit_positions,
            state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(),
            position_override=(shooter_col, shooter_row),
        )
        if is_pistol:
            if distance == 1:
                stats['pistol_shots'][player]['adjacent'] += 1
            else:
                stats['pistol_shots'][player]['not_adjacent'] += 1
                if shooter_engaged:
                    stats['pistol_engaged_shot_non_adjacent'][player] += 1
                    if stats['first_error_lines']['pistol_engaged_shot_non_adjacent'][player] is None:
                        stats['first_error_lines']['pistol_engaged_shot_non_adjacent'][player] = {
                            'episode': state.current_episode_num,
                            'line': line.strip()
                        }
        else:
            if distance == 1:
                stats['non_pistol_adjacent_shots'][player] += 1
                stats['shoot_invalid'][player]['adjacent_non_pistol'] += 1
                if stats['first_error_lines']['shoot_invalid'][player] is None:
                    stats['first_error_lines']['shoot_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        if weapon_range is not None:
            # Portée PER-SOCLE (10 Shooting / 06.01) : à portée si AU MOINS un socle tireur
            # est à ≤ RNG (bord-à-bord) d'AU MOINS un socle cible. On mesure sur les empreintes
            # (min_distance_between_sets) — parité avec l'engagement. L'ancre-à-ancre pouvait
            # déclarer hors-portée alors qu'un socle avancé atteint la cible.
            from ai.analyzer_perfig import squads_min_edge_distance
            shooter_models = state.current_line_models.get(shooter_id)
            target_models = state.positions_by_model.get(target_id)
            if shooter_models and target_models:
                shooter_base = state.unit_base.get(shooter_id, ("round", 1))
                target_base = state.unit_base.get(target_id, ("round", 1))
                edge_dist = squads_min_edge_distance(
                    shooter_models, shooter_base, target_models, target_base,
                    max_distance=int(weapon_range),
                )
                out_of_range = edge_dist > weapon_range
            else:
                # Repli ancre legacy (log ancien/synthétique sans [MODELS:]).
                _shoot_metric = _analyzer_ranged_metric(config)
                target_unit_type = require_key(state.unit_types, target_id)
                _shooter_socle = _analyzer_socle(config, shooter_unit_type, shooter_col, shooter_row)
                _target_socle = _analyzer_socle(config, target_unit_type, target_pos[0], target_pos[1])
                out_of_range = ranged_edge_distance(_shooter_socle, _target_socle, _shoot_metric) > weapon_range
            if out_of_range:
                stats['shoot_invalid'][player]['out_of_range'] += 1
                if stats['first_error_lines']['shoot_invalid'][player] is None:
                    stats['first_error_lines']['shoot_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # Track shots after advance
    if shooter_id in state.units_advanced:
        stats['shots_after_advance'][player] += 1
        if weapon_found and weapon_info_matched:
            weapon_rules_list = require_key(weapon_info_matched, "rules")
            shooter_unit_type_for_advance = require_key(state.unit_types, shooter_id)
            shooter_unit_rules_for_advance = require_key(config.unit_rules_by_type, shooter_unit_type_for_advance)
            if (
                "ASSAULT" not in weapon_rules_list
                and "shoot_after_advance" in shooter_unit_rules_for_advance
            ):
                key = ("shoot_after_advance", shooter_unit_type_for_advance)
                stats['special_rule_usage'][key][player] += 1

    # Track weapon rule usage
    if weapon_found and weapon_info_matched and weapon_display_name is not None:
        weapon_rules_list = require_key(weapon_info_matched, "rules")
        weapon_key = f"{weapon_display_name} ({shooter_unit_type})"
        shooter_pl = require_key(state.unit_player, shooter_id)
        pl_int = int(shooter_pl) if shooter_pl is not None else player
        if "TWIN_LINKED" in weapon_rules_list:
            key = ("TWIN_LINKED", weapon_key)
            stats['weapon_rule_usage'][key][pl_int] += 1
        if shooter_id in state.units_advanced and "ASSAULT" in weapon_rules_list:
            key = ("ASSAULT", weapon_key)
            stats['weapon_rule_usage'][key][pl_int] += 1
        if target_pos:
            distance = calculate_hex_distance(shooter_col, shooter_row, target_pos[0], target_pos[1])
            if distance == 1 and "PISTOL" in weapon_rules_list:
                key = ("PISTOL", weapon_key)
                stats['weapon_rule_usage'][key][pl_int] += 1
        if heavy_applied_in_log:
            key = ("HEAVY", weapon_key)
            stats['weapon_rule_usage'][key][pl_int] += 1
            moved_ids = {str(uid) for uid in state.units_moved}
            advanced_ids = {str(uid) for uid in state.units_advanced}
            heavy_valid = str(shooter_id) not in moved_ids and str(shooter_id) not in advanced_ids
            if not heavy_valid:
                stats['weapon_rule_invalid_usage'][key][pl_int] += 1
                invalid_first = require_key(stats, "weapon_rule_invalid_first_lines")
                if key not in invalid_first:
                    invalid_first[key] = {'episode': state.current_episode_num, 'line': line.strip()}

    # Target priority analysis
    stats['target_priority'][player]['total_shots'] += 1
    target_was_wounded = target_id in stats['wounded_enemies'][player]
    wounded_in_los = set()
    for wounded_id in stats['wounded_enemies'][player]:
        if wounded_id in state.unit_positions and wounded_id in state.unit_hp and require_key(state.unit_hp, wounded_id) > 0:
            wounded_pos = state.unit_positions[wounded_id]
            if has_line_of_sight(shooter_col, shooter_row, wounded_pos[0], wounded_pos[1], state.wall_hexes):
                wounded_in_los.add(wounded_id)
    if target_was_wounded:
        stats['target_priority'][player]['shots_at_wounded_in_los'] += 1
    elif len(wounded_in_los) > 0:
        stats['target_priority'][player]['shots_at_full_hp_while_wounded_in_los'] += 1
    else:
        stats['target_priority'][player]['shots_at_wounded_in_los'] += 1

    if not stats['sample_actions']['shoot']:
        stats['sample_actions']['shoot'] = line.strip()


def handle_wait(
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
    Traite une ligne d'action WAIT.
    Retourne True si la ligne doit être skippée (continue dans la boucle principale).
    """
    from ai.analyzer import (
        is_adjacent,
        _get_unit_hp_value,
        has_line_of_sight,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
    )

    stats = state.stats
    stats['shoot_vs_wait']['wait'] += 1
    stats['shoot_vs_wait_by_player'][player]['wait'] += 1

    wait_unit_match = re.search(r'Unit (\d+)', action_desc)
    if wait_unit_match:
        wait_unit_id = wait_unit_match.group(1)
        wait_unit_dead = wait_unit_id not in state.unit_hp or require_key(state.unit_hp, wait_unit_id) <= 0
        if wait_unit_dead:
            unit_died_before_wait = False
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == wait_unit_id:
                    if death_turn < turn:
                        unit_died_before_wait = True
                        break
                    if death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            unit_died_before_wait = True
                            break
                        if death_phase_order == current_phase_order and death_line_num < state.line_number:
                            unit_died_before_wait = True
                            break
            if unit_died_before_wait:
                stats['dead_unit_waiting'][player] += 1
                if stats['first_error_lines']['dead_unit_waiting'][player] is None:
                    stats['first_error_lines']['dead_unit_waiting'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    if phase == 'SHOOT':
        unit_match = re.search(r'Unit (\d+)\((\d+), (\d+)\)', action_desc)
        if unit_match:
            wait_unit_id = unit_match.group(1)
            wait_col = int(unit_match.group(2))
            wait_row = int(unit_match.group(3))
            wait_unit_type = require_key(state.unit_types, wait_unit_id)
            available_weapons = require_key(config.unit_weapons_cache, wait_unit_type)
            ranged_weapons = [w for w in available_weapons if require_key(w, 'range') > 0]
            enemy_player = 3 - player
            enemy_player_int = int(enemy_player) if enemy_player is not None else None
            is_adj = False
            for uid, p in state.unit_player.items():
                p_int = int(p) if p is not None else None
                if p_int == enemy_player_int and uid in state.unit_positions:
                    hp_value = _get_unit_hp_value(
                        state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Wait adjacency"
                    )
                    if hp_value is None or hp_value <= 0:
                        continue
                    enemy_pos = state.unit_positions[uid]
                    if is_adjacent(wait_col, wait_row, enemy_pos[0], enemy_pos[1]):
                        is_adj = True
                        break

            if is_adj:
                has_pistol = any(require_key(w, 'is_pistol') for w in ranged_weapons)
                if not has_pistol:
                    stats['shoot_vs_wait']['wait'] -= 1
                    stats['shoot_vs_wait_by_player'][player]['wait'] -= 1
                    stats['shoot_vs_wait']['skip'] += 1
                    stats['shoot_vs_wait_by_player'][player]['skip'] += 1
                    return True  # equivalent to continue in the main loop

            valid_targets = []
            enemy_player_int = int(enemy_player) if enemy_player is not None else None
            _wait_metric = _analyzer_ranged_metric(config)
            _wait_socle = _analyzer_socle(config, wait_unit_type, wait_col, wait_row)
            for uid, p in state.unit_player.items():
                p_int = int(p) if p is not None else None
                if p_int == enemy_player_int and uid in state.unit_positions:
                    hp_value = _get_unit_hp_value(
                        state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Wait valid targets"
                    )
                    if hp_value is None or hp_value <= 0:
                        continue
                    enemy_pos = state.unit_positions[uid]
                    distance = calculate_hex_distance(wait_col, wait_row, enemy_pos[0], enemy_pos[1])
                    if not has_line_of_sight(wait_col, wait_row, enemy_pos[0], enemy_pos[1], state.wall_hexes):
                        continue
                    enemy_unit_type = require_key(state.unit_types, uid)
                    _enemy_socle = _analyzer_socle(config, enemy_unit_type, enemy_pos[0], enemy_pos[1])
                    _wait_ranged_edge = ranged_edge_distance(_wait_socle, _enemy_socle, _wait_metric)
                    can_reach = False
                    for weapon in ranged_weapons:
                        weapon_range = require_key(weapon, 'range')
                        is_pistol = require_key(weapon, 'is_pistol')
                        # Portée bord-à-bord (sélecteur `ranged`) ; `distance` hex reste pour == 1.
                        if _wait_ranged_edge > weapon_range:
                            continue
                        if distance == 1 and not is_pistol:
                            continue
                        target_in_melee = False
                        player_int = int(player) if player is not None else None
                        for friendly_id, friendly_p in state.unit_player.items():
                            friendly_p_int = int(friendly_p) if friendly_p is not None else None
                            if friendly_p_int == player_int and friendly_id != wait_unit_id:
                                if friendly_id in state.unit_positions:
                                    friendly_pos = state.unit_positions[friendly_id]
                                    if is_adjacent(enemy_pos[0], enemy_pos[1], friendly_pos[0], friendly_pos[1]):
                                        target_in_melee = True
                                        break
                        if target_in_melee:
                            continue
                        can_reach = True
                        break
                    if can_reach:
                        valid_targets.append(uid)

            if valid_targets:
                stats['wait_by_phase'][player]['wait_with_los'] += 1
                stats['shoot_vs_wait_by_player'][player]['wait_with_targets'] += 1
            else:
                stats['wait_by_phase'][player]['wait_no_los'] += 1
                stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
        else:
            stats['wait_by_phase'][player]['wait_no_los'] += 1
            stats['shoot_vs_wait_by_player'][player]['wait_no_targets'] += 1
    elif phase == 'MOVE':
        stats['wait_by_phase'][player]['move_wait'] += 1

    return False


def handle_skip(
    state: "AnalyzerState",
    line: str,
    action_desc: str,
    player: int,
    turn: int,
    phase: str,
) -> None:
    """Traite une ligne d'action SKIP."""
    stats = state.stats
    stats['shoot_vs_wait']['skip'] += 1
    stats['shoot_vs_wait_by_player'][player]['skip'] += 1

    skip_unit_match = re.search(r'Unit (\d+)', action_desc)
    if skip_unit_match:
        skip_unit_id = skip_unit_match.group(1)
        skip_unit_dead = skip_unit_id not in state.unit_hp or require_key(state.unit_hp, skip_unit_id) <= 0
        if skip_unit_dead:
            unit_died_before_skip = False
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == skip_unit_id:
                    if death_turn < turn:
                        unit_died_before_skip = True
                        break
                    if death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            unit_died_before_skip = True
                            break
                        if death_phase_order == current_phase_order and death_line_num < state.line_number:
                            unit_died_before_skip = True
                            break
            if unit_died_before_skip:
                stats['dead_unit_skipping'][player] += 1
                if stats['first_error_lines']['dead_unit_skipping'][player] is None:
                    stats['first_error_lines']['dead_unit_skipping'][player] = {'episode': state.current_episode_num, 'line': line.strip()}


def handle_advance(
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
    Traite une ligne d'action ADVANCE.
    Retourne True si la ligne doit être skippée (continue dans la boucle principale).
    """
    from ai.analyzer import (
        _track_action_phase_accuracy,
        _position_cache_set,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        _get_inches_to_subhex_for_analyzer,
        _build_occupied_positions,
        _build_enemy_adjacent_hexes,
        _bfs_shortest_path_length,
        get_adjacent_enemies,
        _debug_log,
        _get_unit_hp_value,
    )

    stats = state.stats
    if phase == 'SHOOT':
        stats['shoot_vs_wait']['advance'] += 1
        stats['shoot_vs_wait_by_player'][player]['advance'] += 1

    advance_match = re.search(r'Unit (\d+)\((\d+),\s*(\d+)\) ADVANCED from \((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)', action_desc)
    if not advance_match:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Advance action missing 'from/to' format: {action_desc[:100]}"
        })
        return False

    advance_unit_id = advance_match.group(1)
    start_col = int(advance_match.group(4))
    start_row = int(advance_match.group(5))
    dest_col = int(advance_match.group(6))
    dest_row = int(advance_match.group(7))

    strategy_match = re.search(r'\[Strategy: (\w+)\]', action_desc)
    advance_strategy_label = strategy_match.group(1) if strategy_match else "aggressive"
    if advance_strategy_label in stats['advance_by_strategy'][player]:
        stats['advance_by_strategy'][player][advance_strategy_label] += 1

    _track_action_phase_accuracy(stats, "advance", phase, state.current_episode_num, line)

    stats['position_log_mismatch']['advance']['total'] += 1
    if advance_unit_id not in state.unit_positions:
        stats['position_log_mismatch']['advance']['missing'] += 1
        if stats['first_error_lines']['position_log_mismatch']['advance'] is None:
            stats['first_error_lines']['position_log_mismatch']['advance'] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }
    else:
        from ai.analyzer_perfig import move_start_status, _DEFAULT_BASE
        _pos_status = move_start_status(
            state.positions_by_model.get(advance_unit_id),
            state.unit_base.get(advance_unit_id, _DEFAULT_BASE),
            state.unit_positions[advance_unit_id],
            start_col, start_row,
        )
        if _pos_status == 'mismatch':
            stats['position_log_mismatch']['advance']['mismatch'] += 1
            if stats['first_error_lines']['position_log_mismatch']['advance'] is None:
                stats['first_error_lines']['position_log_mismatch']['advance'] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }
        elif _pos_status == 'absorbed':
            stats['position_log_mismatch']['advance']['anchor_absorbed'] += 1

    # RULE: Dead unit advancing
    advance_unit_dead = advance_unit_id not in state.unit_hp or require_key(state.unit_hp, advance_unit_id) <= 0
    if advance_unit_dead:
        unit_died_before_advance = False
        phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
        current_phase_order = require_key(phase_order, phase)
        for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
            if dead_unit_id == advance_unit_id:
                if death_turn < turn:
                    unit_died_before_advance = True
                    break
                if death_turn == turn:
                    death_phase_order = require_key(phase_order, death_phase)
                    if death_phase_order < current_phase_order:
                        unit_died_before_advance = True
                        break
                    if death_phase_order == current_phase_order and death_line_num < state.line_number:
                        unit_died_before_advance = True
                        break
        if unit_died_before_advance:
            stats['dead_unit_advancing'][player] += 1
            if stats['first_error_lines']['dead_unit_advancing'][player] is None:
                stats['first_error_lines']['dead_unit_advancing'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    advance_roll_match = re.search(r'\[Roll:\s*(\d+)\]', action_desc)
    if not advance_roll_match:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Advance action missing roll for distance validation: {action_desc[:100]}"
        })
    else:
        advance_roll = int(advance_roll_match.group(1))
        # Advance (09 Movement) = MOVE + D6 : le budget inclut le mouvement de base de
        # l'escouade, PAS seulement le jet. Le moteur applique « budget M+jet »
        # (movement_handlers.movement_set_advance_mode_handler). L'ancien budget = jet×scale
        # seul produisait de faux « distance>roll »/« path blocked » (chaque figurine dépasse
        # mécaniquement un budget amputé de M).
        advance_budget = (
            require_key(state.unit_move, advance_unit_id)
            + advance_roll * _get_inches_to_subhex_for_analyzer()
        )
        occupied_positions = _build_occupied_positions(state.unit_positions, state.unit_hp, advance_unit_id)
        enemy_adjacent_hexes = _build_enemy_adjacent_hexes(state.unit_positions, state.unit_player, state.unit_hp, player)
        advance_unit_type = require_key(state.unit_types, advance_unit_id)
        advance_is_fly = require_key(config.unit_is_fly_by_type, advance_unit_type)
        # CONTRÔLE PER-SOCLE (09 Movement / Advance) : identique au move, budget = D6×scale.
        # Chaque figurine avance de son origine (positions_by_model, ligne N-1) vers sa
        # destination ([MODELS:] de cette ligne). L'ancre d'escouade peut dépasser le budget
        # (reformation) tout en gardant chaque socle ≤ budget → l'ancre-à-ancre produisait de
        # faux « distance>roll » / « path blocked ».
        prev_models = state.positions_by_model.get(advance_unit_id)
        new_models = state.current_line_models.get(advance_unit_id)
        adv_blocked = False
        adv_over = False
        if prev_models and new_models:
            for mid in [m for m in new_models if m in prev_models]:
                o_col, o_row = prev_models[mid]
                d_col, d_row = new_models[mid]
                if (o_col, o_row) == (d_col, d_row):
                    continue
                if advance_is_fly:
                    if calculate_hex_distance(o_col, o_row, d_col, d_row) > advance_budget:
                        adv_over = True
                else:
                    steps = _bfs_shortest_path_length(
                        o_col, o_row, d_col, d_row,
                        advance_budget, state.wall_hexes, occupied_positions, enemy_adjacent_hexes
                    )
                    if steps is None:
                        adv_blocked = True
                    elif steps > advance_budget:
                        adv_over = True
        else:
            if advance_is_fly:
                if calculate_hex_distance(start_col, start_row, dest_col, dest_row) > advance_budget:
                    adv_over = True
            else:
                shortest_steps = _bfs_shortest_path_length(
                    start_col, start_row, dest_col, dest_row,
                    advance_budget, state.wall_hexes, occupied_positions, enemy_adjacent_hexes
                )
                if shortest_steps is None:
                    adv_blocked = True
                elif shortest_steps > advance_budget:
                    adv_over = True
        if adv_blocked:
            stats['move_path_blocked']['advance'][player] += 1
            if stats['first_error_lines']['move_path_blocked']['advance'][player] is None:
                stats['first_error_lines']['move_path_blocked']['advance'][player] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }
        if adv_over:
            stats['move_distance_over_limit']['advance'][player] += 1
            if stats['first_error_lines']['move_distance_over_limit']['advance'][player] is None:
                stats['first_error_lines']['move_distance_over_limit']['advance'][player] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }

    if phase == 'SHOOT' and advance_unit_id in state.units_advanced:
        stats['advance_twice_in_shoot_phase'][player] += 1
        if stats['first_error_lines']['advance_twice_in_shoot_phase'][player] is None:
            stats['first_error_lines']['advance_twice_in_shoot_phase'][player] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }
    state.units_advanced.add(advance_unit_id)

    # RULE: Advance after shoot
    if advance_unit_id in state.units_shot:
        stats['advance_after_shoot'][player] += 1
        if stats['first_error_lines']['advance_after_shoot'][player] is None:
            stats['first_error_lines']['advance_after_shoot'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # Sync position cache
    if advance_unit_id in state.unit_positions and state.unit_positions[advance_unit_id] != (start_col, start_row):
        _position_cache_set(state.unit_positions, advance_unit_id, start_col, start_row)
    positions_at_advance = dict(state.unit_positions)
    unit_hp_at_advance = dict(state.unit_hp)
    positions_at_advance_reconciled = dict(positions_at_advance)

    # RULE: Advance from adjacent
    if is_within_engine_engagement_zone(
        advance_unit_id,
        state.unit_player,
        positions_at_advance_reconciled,
        unit_hp_at_advance,
        engagement_zone=_get_engagement_zone_for_analyzer(),
        position_override=(start_col, start_row),
    ):
        adjacent_enemies = get_adjacent_enemies(
            start_col, start_row, state.unit_player, positions_at_advance_reconciled, unit_hp_at_advance, state.unit_types, player
        )
        adjacent_enemy_positions = []
        for enemy_id in adjacent_enemies:
            if enemy_id in positions_at_advance_reconciled:
                enemy_pos = positions_at_advance_reconciled[enemy_id]
                enemy_hp = unit_hp_at_advance.get(enemy_id)
                adjacent_enemy_positions.append(
                    f"{enemy_id}@({enemy_pos[0]},{enemy_pos[1]}) HP={enemy_hp}"
                )
        _debug_log(
            f"[ADVANCE_FROM_ADJACENT] E{state.current_episode_num} T{turn} P{player} "
            f"Unit {advance_unit_id} at ({start_col},{start_row}) adjacent_enemies={adjacent_enemies}"
        )
        _debug_log(
            f"[ADVANCE_FROM_ADJACENT POS] E{state.current_episode_num} T{turn} P{player} "
            f"Unit {advance_unit_id} adjacent_enemy_positions={adjacent_enemy_positions}"
        )
        stats['advance_from_adjacent'][player] += 1
        if stats['first_error_lines']['advance_from_adjacent'][player] is None:
            stats['first_error_lines']['advance_from_adjacent'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    # Record this movement in history
    if advance_unit_id not in state.unit_movement_history:
        state.unit_movement_history[advance_unit_id] = []
    timestamp_match = re.search(r'\[(\d+:\d+:\d+)\]', line)
    timestamp = timestamp_match.group(1) if timestamp_match else None
    state.unit_movement_history[advance_unit_id].append({
        'position': (dest_col, dest_row),
        'timestamp': timestamp,
        'action': 'advance',
        'turn': turn,
        'episode': state.current_episode_num
    })

    # RULE: Position collision
    colliding_units_before = {}
    for uid, current_pos in state.unit_positions.items():
        if current_pos != (dest_col, dest_row) or uid == advance_unit_id:
            continue
        if uid not in state.unit_hp:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': f"Advance collision missing unit_hp for unit_id: {uid}"
            })
            continue
        hp_value = _get_unit_hp_value(
            state.unit_hp, uid, stats, state.current_episode_num, turn, phase, line, "Advance collision"
        )
        if hp_value is None:
            continue
        if hp_value > 0:
            colliding_units_before[uid] = current_pos

    if advance_unit_id not in state.unit_hp:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Advance action for unknown unit_id (missing in unit_hp): {advance_unit_id}"
        })
        return True  # equivalent to continue in the main loop
    if require_key(state.unit_hp, advance_unit_id) > 0:
        _position_cache_set(state.unit_positions, advance_unit_id, dest_col, dest_row)

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
                    and move.get('episode') == state.current_episode_num
                    for move in state.unit_movement_history[uid]
                )
                if has_moved_to_dest:
                    real_colliding_units.append(uid)

    if real_colliding_units:
        stats['unit_position_collisions'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'position': (dest_col, dest_row),
            'units': real_colliding_units + [advance_unit_id],
            'action': 'advance',
            'advance_from': (start_col, start_row),
            'advance_to': (dest_col, dest_row)
        })

    # RULE: Move into wall
    if (dest_col, dest_row) in state.wall_hexes:
        stats['wall_collisions'][player] += 1
        if stats['first_error_lines']['wall_collisions'][player] is None:
            stats['first_error_lines']['wall_collisions'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

    if not stats['sample_actions']['advance']:
        stats['sample_actions']['advance'] = line.strip()

    return False
