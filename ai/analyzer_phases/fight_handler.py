"""
fight_handler.py — gestion des actions FIGHT dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from shared.data_validation import require_key

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def handle_fight(
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
    """Traite une ligne d'action FIGHT."""
    from ai.analyzer import (
        _track_action_phase_accuracy,
        _position_cache_set,
        is_adjacent,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
    )

    stats = state.stats
    state.units_fought.add(unit_id)

    fight_match = re.search(
        r'Unit (\d+)\((\d+),\s*(\d+)\) (?:ATTACKED|FOUGHT) Unit (\d+)\((\d+),\s*(\d+)\)',
        action_desc
    )
    if fight_match:
        fighter_id = fight_match.group(1)
        fighter_col = int(fight_match.group(2))
        fighter_row = int(fight_match.group(3))
        target_id = fight_match.group(4)
        target_col = int(fight_match.group(5))
        target_row = int(fight_match.group(6))

        _track_action_phase_accuracy(stats, "fight", phase, state.current_episode_num, line)
        attacker_player = require_key(state.unit_player, fighter_id)
        fight_attacks_by_unit = require_key(stats, 'fight_attacks_by_unit')
        fight_attacks_by_player = require_key(fight_attacks_by_unit, attacker_player)
        fight_over_by_unit = require_key(stats, 'fight_over_cc_nb_by_unit')
        fight_over_by_player = require_key(fight_over_by_unit, attacker_player)
        if fighter_id not in fight_attacks_by_player:
            fight_attacks_by_player[fighter_id] = 0
        if fighter_id not in fight_over_by_player:
            fight_over_by_player[fighter_id] = 0
        fight_attacks_by_player[fighter_id] = fight_attacks_by_player[fighter_id] + 1
        if fighter_id in state.charged_units_current_fight:
            state.charged_units_fought.add(fighter_id)
        else:
            eligible_charged_units = []
            for charged_id in state.charged_units_current_fight:
                if charged_id in state.charged_units_fought:
                    continue
                if charged_id not in state.unit_positions:
                    continue
                if charged_id not in state.unit_hp or require_key(state.unit_hp, charged_id) <= 0:
                    continue
                if is_within_engine_engagement_zone(
                    charged_id,
                    state.unit_player,
                    state.unit_positions,
                    state.unit_hp,
                    engagement_zone=_get_engagement_zone_for_analyzer(),
                ):
                    eligible_charged_units.append(charged_id)
            if eligible_charged_units:
                stats['fight_alternation_violations'][attacker_player] += 1
                if stats['first_error_lines']['fight_alternation_violations'][attacker_player] is None:
                    stats['first_error_lines']['fight_alternation_violations'][attacker_player] = {
                        'episode': state.current_episode_num,
                        'line': line.strip(),
                        'eligible_charged_units': eligible_charged_units
                    }

        weapon_match = re.search(r'with \[([^\]]+)\]', action_desc)
        if weapon_match:
            weapon_display_name = weapon_match.group(1).strip()
            fighter_unit_type = require_key(state.unit_types, fighter_id)
            # RULE METRICS: Targeted Intercession granted reroll mechanics (fight)
            if re.search(r'\(TARGETED_INTERCESSION\)', action_desc, re.IGNORECASE):
                key = ("reroll_1_towound", fighter_unit_type)
                stats['special_rule_usage'][key][player] += 1
                key = ("reroll_towound_target_on_objective", fighter_unit_type)
                stats['special_rule_usage'][key][player] += 1
            if fighter_unit_type:
                limits = require_key(config.unit_attack_limits, fighter_unit_type)
                cc_nb_by_weapon = require_key(limits, "cc_nb_by_weapon")
                from ai.analyzer_perfig import resolve_weapon_value
                cc_nb_single = resolve_weapon_value(
                    weapon_display_name, cc_nb_by_weapon, config.cc_nb_by_weapon_global
                )
                if cc_nb_single is None:
                    stats['parse_errors'].append({
                        'episode': state.current_episode_num,
                        'turn': turn,
                        'phase': phase,
                        'line': line.strip(),
                        'error': f"Weapon '{weapon_display_name}' missing CC_NB for unit type {fighter_unit_type}"
                    })
                else:
                    # Class B : plafond d'attaques escouade = (socles vivants) × CC_NB/modèle.
                    n_fighter_models = len(state.current_line_models.get(fighter_id, {})) or 1
                    cc_nb = cc_nb_single * n_fighter_models
                    seq_key = (state.fight_phase_seq_id, fighter_id, weapon_display_name)
                    if (state.last_fight_fighter_id != fighter_id or
                            state.last_fight_weapon != weapon_display_name):
                        state.fight_sequence_counts[seq_key] = 0
                    state.last_fight_fighter_id = fighter_id
                    state.last_fight_weapon = weapon_display_name
                    if seq_key not in state.fight_sequence_counts:
                        state.fight_sequence_counts[seq_key] = 0
                    elif step_marker_present and step_inc:
                        state.fight_sequence_counts[seq_key] = 0
                    state.fight_sequence_counts[seq_key] += 1
                    if state.fight_sequence_counts[seq_key] > cc_nb:
                        attacker_player = require_key(state.unit_player, fighter_id)
                        stats['fight_over_cc_nb'][attacker_player] += 1
                        fight_over_by_unit = require_key(stats, 'fight_over_cc_nb_by_unit')
                        fight_over_by_player = require_key(fight_over_by_unit, attacker_player)
                        if fighter_id not in fight_over_by_player:
                            raise KeyError(f"Missing fight_over_cc_nb_by_unit for fighter_id={fighter_id}, player={attacker_player}")
                        fight_over_by_player[fighter_id] = fight_over_by_player[fighter_id] + 1
                        if stats['first_error_lines']['fight_over_cc_nb'][attacker_player] is None:
                            stats['first_error_lines']['fight_over_cc_nb'][attacker_player] = {'episode': state.current_episode_num, 'line': line.strip()}
        else:
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': "Fight action missing weapon name for CC_NB check"
            })

        # CRITICAL: Update position cache for fighter/target from log (source of truth at fight time)
        if fighter_id in state.unit_hp and require_key(state.unit_hp, fighter_id) > 0:
            _position_cache_set(state.unit_positions, fighter_id, fighter_col, fighter_row)
        if target_id in state.unit_hp and require_key(state.unit_hp, target_id) > 0:
            _position_cache_set(state.unit_positions, target_id, target_col, target_row)

        # RULE: Fight from non-adjacent — CONTRÔLE PER-SOCLE (12.04 / engagement range).
        # Combat légal si AU MOINS un socle attaquant est à portée d'engagement (bord-à-bord
        # ≤ engagement_zone subhexes) d'AU MOINS un socle cible. On réutilise les empreintes
        # moteur (compute_occupied_hexes / min_distance_between_sets). L'ancre-à-ancre
        # (is_adjacent, distance hex==1) était bien plus restrictif que la règle → faux positifs.
        from ai.analyzer_perfig import squads_min_edge_distance
        from ai.analyzer import _get_engagement_zone_for_analyzer
        fighter_models = state.current_line_models.get(fighter_id)
        target_models = state.positions_by_model.get(target_id)
        if fighter_models and target_models:
            ez = _get_engagement_zone_for_analyzer()
            fighter_base = state.unit_base.get(fighter_id, ("round", 1))
            target_base = state.unit_base.get(target_id, ("round", 1))
            edge = squads_min_edge_distance(
                fighter_models, fighter_base, target_models, target_base, max_distance=ez
            )
            fight_non_adjacent = edge > ez
        else:
            # Pas de données per-socle (log ancien/synthétique) → repli ancre legacy.
            fight_non_adjacent = not is_adjacent(fighter_col, fighter_row, target_col, target_row)
        if fight_non_adjacent:
            stats['fight_from_non_adjacent'][player] += 1
            if stats['first_error_lines']['fight_from_non_adjacent'][player] is None:
                stats['first_error_lines']['fight_from_non_adjacent'][player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Fight friendly
        if (target_id in state.unit_player and fighter_id in state.unit_player and
                state.unit_player[target_id] == state.unit_player[fighter_id]):
            attacker_player = state.unit_player[fighter_id]
            stats['fight_friendly'][attacker_player] += 1
            if stats['first_error_lines']['fight_friendly'][attacker_player] is None:
                stats['first_error_lines']['fight_friendly'][attacker_player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Dead unit Fighting (attacker is dead)
        attacker_is_dead = fighter_id in state.unit_hp and require_key(state.unit_hp, fighter_id) <= 0
        if attacker_is_dead:
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            attacker_died_before_fight = False
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == fighter_id:
                    if death_turn < turn:
                        attacker_died_before_fight = True
                        break
                    elif death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            attacker_died_before_fight = True
                            break
                        elif death_phase_order == current_phase_order and death_line_num < state.line_number:
                            attacker_died_before_fight = True
                            break
            if attacker_died_before_fight:
                attacker_player = require_key(state.unit_player, fighter_id)
                stats['fight_dead_unit_attacker'][attacker_player] += 1
                if stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] is None:
                    stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Fight a dead unit (target is dead)
        target_is_dead = target_id not in state.unit_hp or require_key(state.unit_hp, target_id) <= 0
        if target_is_dead:
            phase_order = {'MOVE': 1, 'SHOOT': 2, 'CHARGE': 3, 'FIGHT': 4}
            current_phase_order = require_key(phase_order, phase)
            target_died_before_fight = False
            for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
                if dead_unit_id == target_id:
                    if death_turn < turn:
                        target_died_before_fight = True
                        break
                    elif death_turn == turn:
                        death_phase_order = require_key(phase_order, death_phase)
                        if death_phase_order < current_phase_order:
                            target_died_before_fight = True
                            break
                        elif death_phase_order == current_phase_order and death_line_num < state.line_number:
                            target_died_before_fight = True
                            break
            if target_died_before_fight:
                attacker_player = require_key(state.unit_player, fighter_id)
                stats['fight_dead_unit_target'][attacker_player] += 1
                if stats['first_error_lines']['fight_dead_unit_target'][attacker_player] is None:
                    stats['first_error_lines']['fight_dead_unit_target'][attacker_player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # Sample action
        if not stats['sample_actions']['fight']:
            stats['sample_actions']['fight'] = line.strip()
    else:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Fight action missing expected format: {action_desc[:100]}"
        })
