"""
shoot_handler.py — gestion des actions SHOT, WAIT, SKIP, ADVANCED dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, ranged_edge_distance, get_distance_metric
from ai.analyzer_perfig import position_is_on_battlefield

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def _analyzer_ranged_metric(config: "AnalyzerConfig") -> str:
    """Métrique de portée tir (hex|euclidean) — celle du RUN, lue dans l'entête `Run rules:`.

    La relire dans le config courant, c'est juger un vieux journal avec la métrique du jour :
    une bascule hex↔euclidean change silencieusement tous les verdicts de portée."""
    from ai.analyzer_config import get_run_rule
    return get_run_rule("metric.ranged")


def _analyzer_socle(config: "AnalyzerConfig", unit_type: str, col: int, row: int) -> Any:
    """Socle d'une unité à une position, empreinte reconstruite depuis le registry.

    Portée tir euclidienne bord-à-bord (règle 01.04) : l'analyzer mesure comme le
    moteur en rebâtissant l'empreinte à partir de BASE_SHAPE/BASE_SIZE.
    """
    from engine.hex_utils import Socle
    from ai.analyzer_perfig import _model_footprint
    # Le registre porte le socle de la DATASHEET (unités ×10) ; le board le convertit à sa
    # résolution — et à x1 le normalise en round/1 (une figurine = une case). Sans cette
    # conversion l'analyzer bâtissait une empreinte de 13 cases de diamètre pour un
    # Intercessor sur un board 44×60 : toute mesure bord-à-bord en découlait fausse.
    # Conversion résolue UNE FOIS par unit_type au chargement, empreinte mémoïsée : ce helper
    # est appelé deux fois par ligne de tir et une fois par ennemi vivant sur chaque WAIT.
    socle = config.unit_socle_by_type.get(unit_type)  # get allowed : cache rempli à la demande
    if socle is None:
        from engine.game_state import _scale_socle
        from ai.analyzer import _get_inches_to_subhex_for_analyzer
        data = config.unit_registry.get_unit_data(unit_type)
        socle = _scale_socle(
            require_key(data, "BASE_SHAPE"),
            require_key(data, "BASE_SIZE"),
            _get_inches_to_subhex_for_analyzer(),
            f"analyzer_socle/{unit_type}",
        )
        config.unit_socle_by_type[unit_type] = socle
    shape, size = socle
    return Socle(shape, size, int(col), int(row), set(_model_footprint(int(col), int(row), (shape, size))))


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

    # RULE METRICS: relance de blessure accordee par une ABILITE d unite.
    # Le token est le nom d affichage de la REGLE SOURCE, entre CROCHETS — convention de tous
    # les tokens du projet ([HEAVY], [COVER], [HAZARD]...), a laquelle le frontend accroche ses
    # tooltips. L ancienne regex cherchait `(TARGETED_INTERCESSION)` entre PARENTHESES avec un
    # underscore : une forme que le formateur n'a jamais produite, donc un compteur bloque a 0
    # (V11 §0hist.38). Espace ou underscore acceptes, le nom venant de la config.
    shooter_unit_type_for_reroll = require_key(state.unit_types, shooter_id)
    if re.search(r'\[TARGETED[ _]INTERCESSION\]', action_desc, re.IGNORECASE):
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
    is_close_quarters = False
    weapon_found = False
    weapon_range = None
    shooter_unit_type = require_key(state.unit_types, shooter_id)
    shooter_player_from_types = require_key(state.unit_player, shooter_id)
    weapon_info_matched = None
    weapon_display_name = None

    if weapon_match:
        weapon_display_name = weapon_match.group(1)
        # Seuil de blessure 05.02 : la ligne dit le seuil qu'elle a appliqué, on le recalcule
        # depuis F et E. Cf. ai/analyzer_wound.py.
        from ai.analyzer_phases.fight_handler import _shooter_models
        from ai.analyzer_wound import check_wound_threshold
        check_wound_threshold(
            state, config, stats, line, action_desc, player, shooter_unit_type,
            weapon_display_name, target_id, _shooter_models(action_desc), is_melee=False,
        )
        weapon_name_lower = weapon_display_name.lower()
        weapons_info = require_key(config.unit_weapons_cache, shooter_unit_type)
        for weapon_info in weapons_info:
            if weapon_info['name'].lower() == weapon_name_lower:
                is_close_quarters = weapon_info['is_close_quarters']
                weapon_range = weapon_info['range']
                weapon_found = True
                weapon_info_matched = weapon_info
                break
        if not weapon_found:
            # Escouade HÉTÉROGÈNE (V11) : l'arme loguée appartient souvent à un model-type du
            # squad et non à l'entrée `unit_type` — un Plasma Pistol de sergent dans une
            # escouade Vanguard. Les cartes GLOBALES existent pour ce cas (cf. AnalyzerConfig)
            # et n'étaient pas consultées ici : le pistolet ressortait non-[CLOSE_QUARTERS],
            # donc son tir au contact était compté en faute alors que 10.06 l'autorise.
            _cq_global = config.weapon_is_close_quarters_global.get(weapon_display_name)  # get allowed
            if _cq_global is not None:
                is_close_quarters = bool(_cq_global)
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
                # [SUSTAINED HITS X] 24.36 — une touche additionnelle n'est PAS une attaque :
                # elle ne consomme aucun tir du pool, donc elle ne compte pas dans le plafond.
                # Le moteur l'écrit sans jet de touche (`Hit None(...)`) et la marque
                # explicitement ; sans exclusion, 3 figurines × A3 + 3 critiques produisaient
                # 12 lignes pour un plafond de 9 → 3 faux « shots over RNG_NB ».
                sustained_hits_by_weapon = require_key(limits, "sustained_hits_by_weapon")
                sustained_hits_value = resolve_weapon_value(
                    weapon_name_for_limits, sustained_hits_by_weapon,
                    config.sustained_hits_by_weapon_global,
                )
                if sustained_hits_value is None:
                    sustained_hits_value = 0
                is_sustained_hit_line = re.search(
                    r'\[SUSTAINED(?: |_)?HITS\]', action_desc, re.IGNORECASE
                ) is not None
                if is_sustained_hit_line:
                    if sustained_hits_value <= 0:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': (
                                f"SUSTAINED HITS marker present for weapon without SUSTAINED_HITS "
                                f"rule: {shooter_unit_type}/{weapon_name_for_limits}"
                            )
                        })
                    else:
                        _sustained_key = (
                            "SUSTAINED_HITS",
                            f"{weapon_display_name} ({shooter_unit_type})",
                        )
                        _shooter_pl = require_key(state.unit_player, shooter_id)
                        stats['weapon_rule_usage'][_sustained_key][int(_shooter_pl)] += 1

                seq_key = (state.current_episode_num, turn, shooter_id, weapon_name_for_limits)
                if (state.last_shoot_shooter_id != shooter_id or
                        state.last_shoot_weapon != weapon_name_for_limits):
                    state.shot_sequence_counts[seq_key] = 0
                elif step_marker_present and step_inc:
                    state.shot_sequence_counts[seq_key] = 0
                if seq_key not in state.shot_sequence_counts:
                    state.shot_sequence_counts[seq_key] = 0
                if not is_sustained_hit_line:
                    state.shot_sequence_counts[seq_key] += 1
                current_shot_index = state.shot_sequence_counts[seq_key]
                shooter_player_for_stats = require_key(state.unit_player, shooter_id)
                # Class B (comptage per-figurine) : le plafond de tirs d'une escouade =
                # (nb de socles vivants qui tirent) × NB par modèle. Les socles vivants sont
                # listés dans le segment [MODELS:] de la ligne (current_line_models). Sans
                # segment (logs anciens/synthétiques) → 1 modèle (comportement ancre legacy).
                # Jumeau tir du calcul de fight_handler : [MODELS:] de la ligne, sinon
                # l'effectif persistant connu, sinon 1 (borne minimale). Voir fight_handler pour
                # le cas qui rend [MODELS:] absent.
                n_shooter_models = (
                    len(state.current_line_models.get(shooter_id, {}))  # get allowed
                    or state.unit_models_alive.get(shooter_id, 0)  # get allowed
                    or 1
                )
                rng_nb_squad = rng_nb * n_shooter_models
                rapid_fire_value_squad = rapid_fire_value * n_shooter_models
                # [RAPID FIRE] 24.30 — le controle per-shot « ce tir est-il LE tir bonus ? »
                # a ete SUPPRIME le 2026-07-29 (V11 §0hist.38). Il exigeait que le marqueur
                # n'apparaisse QUE sur les tirs d'index > NB de base : une distinction heritee
                # du moteur mort, qui resolvait les tirs un par un. Le moteur resout desormais
                # un POOL d'attaques — 24.30 dit « increase this weapon's ATTACKS by X », et
                # rien ne distingue une attaque d'une autre. Exiger du log qu'il designe « la »
                # attaque bonus, c'est exiger une information qui n'existe pas.
                # Ce qui reste, et qui est le VRAI invariant : le PLAFOND de tirs ci-dessous
                # (`shoot_over_rng_nb`), que le marqueur de groupe rend enfin verifiable —
                # sans lui, le plafond restait a NB de base et toute activation RAPID FIRE
                # produisait des faux « shots over RNG_NB ».
                # Non-regression : tests/unit/ai/test_step_log_weapon_rule_tokens.py
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
    #
    # Arguments de la mesure d'engagement de la CIBLE, capturés là où elle est faite. Le
    # diagnostic les rejoue pour NOMMER l'unité qui engage (cf. plus bas) : les reconstruire à
    # l'endroit du compteur ferait vivre deux fois le filtre des unités mesurables, et le
    # diagnostic pourrait décrire une autre situation que celle qui a déclenché.
    target_engagement_args: Optional[Dict[str, Any]] = None
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
            target_engagement_args = {
                "unit_player": state.unit_player,
                "unit_positions": positions_for_engagement,
                "unit_hp": state.unit_hp,
                "engagement_zone": _get_engagement_zone_for_analyzer(),
                "position_override": target_pos,
                "positions_by_model": state.positions_by_model,
                "unit_base": state.unit_base,
                **state.engagement_3d_kwargs(),
                "subject_models": state.positions_by_model.get(target_id),  # get allowed
            }
            target_engaged = is_within_engine_engagement_zone(
                target_id, **target_engagement_args
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
                # MÊME capture d'arguments que la branche jumelle (ligne du log portant la
                # position de la cible). L'oublier ici laissait le diagnostic sans mesure : il
                # imprimait « le compteur et la mesure se contredisent » alors que la mesure
                # n'avait simplement jamais été faite — accuser le compteur d'une omission de
                # câblage est pire que de ne rien dire.
                target_engagement_args = {
                    "unit_player": state.unit_player,
                    "unit_positions": positions_for_engagement,
                    "unit_hp": state.unit_hp,
                    "engagement_zone": _get_engagement_zone_for_analyzer(),
                    "position_override": target_pos_from_cache,
                    "positions_by_model": state.positions_by_model,
                    "unit_base": state.unit_base,
                    **state.engagement_3d_kwargs(),
                    "subject_models": state.positions_by_model.get(target_id),  # get allowed
                }
                target_engaged = is_within_engine_engagement_zone(
                    target_id, **target_engagement_args
                )
            else:
                target_engaged = False
    else:
        target_engaged = False

    # 10.06 / 17.03 — MONSTER/VEHICLE. Deux exemptions distinctes, aucune n'est un repli :
    #  - TIREUR M/V : engagé, il est éligible au close-quarters shooting avec TOUTES ses armes
    #    (10.06 « Has one or more [CLOSE-QUARTERS] weapons OR is a MONSTER/VEHICLE unit »), et
    #    peut cibler les unités avec lesquelles il est engagé, à -1 pour toucher.
    #  - CIBLE M/V : 17.03 « enemy MONSTER/VEHICLE units that are engaged can be selected as
    #    targets of ranged attacks ». L'interdiction de tirer sur une unité engagée ne la vise pas.
    # Sans ces deux exemptions, chaque tir d'un LandSpeeder au contact remontait deux erreurs
    # (« tir invalide adjacent » + « cible engagée ») alors que le moteur applique correctement
    # le -1 (Gatling 3+ -> 4+, Multi-Melta 4+ -> 5+ dans step.log).
    shooter_is_monster_or_vehicle = bool(require_key(
        config.unit_is_monster_or_vehicle_by_type, require_key(state.unit_types, shooter_id)
    ))
    target_is_monster_or_vehicle = (
        target_id in state.unit_types
        and bool(require_key(
            config.unit_is_monster_or_vehicle_by_type, require_key(state.unit_types, target_id)
        ))
    )

    # L'exemption TIREUR ne vaut que pour la cible avec laquelle il est LUI-MÊME engagé (10.06
    # « Models in your unit can target enemy units your unit is engaged with ») : un M/V qui
    # tire sur une autre unité engagée avec un allié reste en faute.
    # Le tireur est-il engagé, avec QUI QUE CE SOIT ? Conditionne l'exemption 17.03 ci-dessous.
    shooter_engaged_at_all = is_within_engine_engagement_zone(
        shooter_id,
        state.unit_player,
        state.unit_positions,
        state.unit_hp,
        engagement_zone=_get_engagement_zone_for_analyzer(),
        positions_by_model=state.positions_by_model,
        unit_base=state.unit_base,
        **state.engagement_3d_kwargs(),
        subject_models=state.current_line_models.get(shooter_id),  # get allowed
        subject_heights=state.current_line_heights.get(shooter_id),  # get allowed
        position_override=(shooter_col, shooter_row),
    )
    shooter_engaged_with_target = False
    if target_pos is not None:
        # Même primitive que tout le reste de l'analyzer, restreinte à CETTE cible : elle porte
        # la mesure per-figurine ET la métrique du run. Une mesure écrite à la main ici
        # rejouerait la divergence hex↔euclidien.
        #
        # Calculé pour TOUT tireur, plus seulement les MONSTER/VEHICLE : c'est la grandeur
        # qu'exige 10.06 (« you can only select enemy units that are ENGAGED WITH your unit as
        # targets »), donc celle du contrôle close-quarters ci-dessous. Restreint aux M/V, il
        # laissait ce contrôle mesurer une adjacence d'ancre — voir plus bas.
        shooter_engaged_with_target = is_within_engine_engagement_zone(
            shooter_id,
            state.unit_player,
            {target_id: (target_pos[0], target_pos[1])},
            state.unit_hp,
            engagement_zone=_get_engagement_zone_for_analyzer(),
            positions_by_model=state.positions_by_model,
            unit_base=state.unit_base,
            **state.engagement_3d_kwargs(),
            subject_models=state.current_line_models.get(shooter_id),  # get allowed
            subject_heights=state.current_line_heights.get(shooter_id),  # get allowed
            position_override=(shooter_col, shooter_row),
        )

    # 17.03 n'autorise que la CIBLE : un tireur non-M/V qui est LUI-MÊME engagé reste borné au
    # close-quarters shooting, donc aux armes [CLOSE_QUARTERS] (10.06, « Non-MONSTER/
    # Non-VEHICLE Models », rappelé mot pour mot par l'encadré de 17.03). Exempter sur la seule
    # nature de la cible desarmait le controle des qu'un vehicule ennemi etait au contact.
    target_mv_exempt = target_is_monster_or_vehicle and not shooter_engaged_at_all
    if (
        target_engaged
        and not is_close_quarters
        and not target_mv_exempt
        and not shooter_engaged_with_target
    ):
        stats['shoot_at_engaged_enemy'][player] += 1
        if stats['first_error_lines']['shoot_at_engaged_enemy'][player] is None:
            # NOMME l'unité qui engage la cible, avec la mesure du compteur — jumeau du
            # diagnostic 1.1 (cf. `engine_engagement_zone_offenders`). Sans elle, « cible
            # engagée » n'est pas vérifiable à la lecture : il faut refaire la mesure à la main
            # pour savoir avec QUI, et c'est ce qui a fait passer ce compteur pour un faux
            # positif pendant tout un chantier.
            from ai.analyzer import engine_engagement_zone_offenders
            _offenders = (
                engine_engagement_zone_offenders(target_id, **target_engagement_args)
                if target_engagement_args is not None else []
            )
            stats['first_error_lines']['shoot_at_engaged_enemy'][player] = {
                'episode': state.current_episode_num,
                'line': line.strip(),
                'adjacent_after': _offenders,
            }

    # Track CLOSE_QUARTERS weapon shots
    heavy_applied_in_log = re.search(r'(?:\[\s*HEAVY\s*\]|\sHEAVY\s)', action_desc, re.IGNORECASE) is not None
    if weapon_match and target_pos and weapon_found:
        # 10.06 CLOSE-QUARTERS SHOOTING, volet « Non-MONSTER/Non-VEHICLE Models » : « You can only
        # select [CLOSE-QUARTERS] weapons to make attacks with and you can only select enemy units
        # that are ENGAGED WITH your unit as targets. » La grandeur de la règle est donc
        # l'ENGAGEMENT (bord-à-bord, par figurine, zone d'engagement du run — ici 2 subhex), jamais
        # une adjacence d'hex.
        #
        # Ces deux contrôles mesuraient `calculate_hex_distance(ancre_tireur, ancre_cible) == 1`.
        # Faux deux fois : ancre au lieu du par-figurine, et adjacence au lieu de la zone
        # d'engagement. Le moteur, lui, applique bien `enemy_engaged_with_shooter`
        # (`shooting_handlers` ~L693) — le contrôle contredisait donc le moteur ET la règle :
        # 144 faux positifs mesurés sur un run de 600 épisodes. Troisième occurrence de la famille
        # « ancre vs par-figurine », après le contrôle LoS et le fight non-adjacent.
        if is_close_quarters:
            if shooter_engaged_with_target:
                stats['close_quarters_shots'][player]['engaged_target'] += 1
            else:
                stats['close_quarters_shots'][player]['unengaged_target'] += 1
                # Tireur non engagé : une arme [CLOSE-QUARTERS] est une arme de tir comme une
                # autre, elle peut viser n'importe quelle cible à portée. La faute n'existe que
                # pour un tireur ENGAGÉ, borné par 10.06 aux unités avec lesquelles il l'est.
                if shooter_engaged_at_all and not shooter_is_monster_or_vehicle:
                    stats['close_quarters_shot_at_unengaged_target'][player] += 1
                    if stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][player] is None:
                        stats['first_error_lines']['close_quarters_shot_at_unengaged_target'][player] = {
                            'episode': state.current_episode_num,
                            'line': line.strip()
                        }
        else:
            # 10.06 : un tireur MONSTER/VEHICLE engagé tire avec TOUTES ses armes sur l'unité
            # avec laquelle il est engagé — l'arme non-[CLOSE_QUARTERS] au contact est légale
            # pour lui (elle subit le -1, que le moteur applique déjà).
            if shooter_engaged_at_all and not shooter_is_monster_or_vehicle:
                stats['engaged_shot_with_non_close_quarters_weapon'][player] += 1
                stats['shoot_invalid'][player]['engaged_non_close_quarters'] += 1
                if stats['first_error_lines']['shoot_invalid'][player] is None:
                    stats['first_error_lines']['shoot_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        if weapon_range is not None:
            # Portée PER-SOCLE (10 Shooting / 06.01) : à portée si AU MOINS un socle tireur
            # est à ≤ RNG (bord-à-bord) d'AU MOINS un socle cible. On mesure sur les empreintes
            # (min_distance_between_sets) — parité avec l'engagement. L'ancre-à-ancre pouvait
            # déclarer hors-portée alors qu'un socle avancé atteint la cible.
            # UNE seule mesure, socles connus ou non. Les deux branches d'origine ne
            # mesuraient pas la même chose — empreintes du log en métrique hex d'un côté,
            # socle du REGISTRE en métrique de config de l'autre — si bien que le verdict
            # dépendait de la présence de `[MODELS:]`. La cible perd ses socles connus dès
            # qu'elle perd une figurine (le log ne dit pas laquelle) : le repli devenait alors
            # le cas courant, et douze tirs parfaitement à portée ressortaient « out of range ».
            # Sans socles : une figurine à l'ancre, seule donnée fraîche disponible.
            from ai.analyzer_perfig import _DEFAULT_BASE, squads_min_ranged_distance
            shooter_models = state.current_line_models.get(shooter_id) or {  # get allowed
                f"{shooter_id}#anchor": (shooter_col, shooter_row)
            }
            # Cible : `[TARGET_MODELS:]` de la ligne (survivants post-pertes) en priorité, sinon
            # ses socles connus. À défaut des deux on NE REND PAS de verdict : l'ancre d'une
            # escouade de sept figurines ne dit rien de la distance à la plus proche, et un tir
            # légal ressortait « out of range » pour cette seule raison.
            from ai.analyzer_perfig import parse_target_models_segment
            target_models = (
                parse_target_models_segment(action_desc)
                or state.positions_by_model.get(target_id)  # get allowed
            )
            edge_dist = None if not target_models else squads_min_ranged_distance(
                shooter_models, state.unit_base.get(shooter_id, _DEFAULT_BASE),  # get allowed
                target_models, state.unit_base.get(target_id, _DEFAULT_BASE),  # get allowed
                _analyzer_ranged_metric(config),
                # Cap NON tronqué : c'est `weapon_range` que la ligne suivante compare, et
                # `ranged_edge_distance` arrondit elle-même pour sa branche hex. Un `int()` ici
                # rendrait un minorant sous le seuil pour une cible située entre les deux — un
                # tir hors portée compté légal. Jumeau du même arbitrage dans
                # `shooting_handlers.hidden_enemy_out_of_detection`.
                max_distance=weapon_range,
            )
            if edge_dist is not None and edge_dist > weapon_range:
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
            if distance == 1 and "CLOSE_QUARTERS" in weapon_rules_list:
                key = ("CLOSE_QUARTERS", weapon_key)
                stats['weapon_rule_usage'][key][pl_int] += 1
        if heavy_applied_in_log:
            # [HEAVY] 24.16 — USAGE seulement, jamais VALIDITE. Le contrôle de validité
            # (`shooter in units_moved/units_advanced` → invalide) a été SUPPRIMÉ le
            # 2026-07-29 : c'était la borne conservatrice du moteur d'AVANT le 2026-07-26,
            # devenue un générateur de faux positifs. Le PDF autorise le bonus tant qu'aucune
            # figurine n'a parcouru PLUS DE 3" — un déplacement de 2" le conserve, et le
            # moteur l'accorde. Le critère n'est pas reconstructible depuis step.log (distance
            # de CHEMIN géodésique PAR FIGURINE contre des ancres départ/arrivée), et le token
            # n'est émis que si le moteur a APPLIQUÉ le bonus après avoir testé ses trois
            # clauses : re-dériver à côté ne peut que contredire l'autorité.
            # Vérification portée par tests/unit/engine/test_heavy_shoot.py.
            # Non-régression : tests/unit/ai/test_analyzer_no_heavy_after_move_false_positive.py
            stats['weapon_rule_usage'][("HEAVY", weapon_key)][pl_int] += 1

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
        # MÊME motif que la branche SHOOT (`\s*` autour de la virgule). L'ancienne forme exigeait
        # `Unit 1(5, 48)` avec un espace, or TOUS les producteurs écrivent `Unit 1(5,48)` sans
        # espace (`w40k_core.py` : `f"{unit_id}({col},{row})"`, 4 sites). MESURÉ sur un step.log
        # réel : 15 151 lignes WAIT en phase de tir, **0 matchée**, 15 151 par cette forme-ci.
        # Tout le bloc ci-dessous n'a donc JAMAIS tourné en production — et le `else` comptait
        # « aucune cible » sans avoir rien mesuré.
        unit_match = re.search(r'Unit (\d+)\s*\((\d+),\s*(\d+)\)', action_desc)
        if unit_match:
            wait_unit_id = unit_match.group(1)
            wait_col = int(unit_match.group(2))
            wait_row = int(unit_match.group(3))
            wait_unit_type = require_key(state.unit_types, wait_unit_id)
            available_weapons = require_key(config.unit_weapons_cache, wait_unit_type)
            ranged_weapons = [w for w in available_weapons if require_key(w, 'range') > 0]
            enemy_player = 3 - player
            # Grandeurs constantes sur toute la ligne : zone d'engagement et cartes verticales
            # viennent de l'entête `Run rules:` du journal, elles ne dépendent d'aucune cible.
            _wait_ez = _get_engagement_zone_for_analyzer()
            _wait_3d = state.engagement_3d_kwargs()
            # 10.04 : le tir NORMAL exige une unité UNENGAGED. Mesuré par la primitive partagée
            # de l'analyzer, comme `shooter_engaged_at_all` dans `handle_shoot` : per-figurine,
            # métrique du run, zone d'engagement du run (10 subhex à x5), et écarte les unités
            # hors table à l'énumération. L'ancienne boucle mesurait `hex_distance(ancre) == 1` —
            # aveugle à l'échelle ET à l'empreinte, donc un ennemi ENGAGÉ à 8 subhex laissait le
            # WAIT compté comme un choix délibéré. Quatrième occurrence de la famille
            # « ancre vs par-figurine » (LoS, fight non-adjacent, close-quarters).
            wait_unit_engaged = is_within_engine_engagement_zone(
                wait_unit_id,
                state.unit_player,
                state.unit_positions,
                state.unit_hp,
                engagement_zone=_wait_ez,
                positions_by_model=state.positions_by_model,
                unit_base=state.unit_base,
                **_wait_3d,
                subject_models=state.current_line_models.get(wait_unit_id),  # get allowed
                subject_heights=state.current_line_heights.get(wait_unit_id),  # get allowed
                position_override=(wait_col, wait_row),
            )

            # 10.06 ELIGIBLE IF : « Has one or more [CLOSE-QUARTERS] weapons **OR is a
            # MONSTER/VEHICLE unit** ». Le volet M/V manquait ici alors que `handle_shoot`
            # l'applique : un Dreadnought engagé, qui n'a aucune arme [CLOSE-QUARTERS], voyait son
            # WAIT requalifié en `skip` — la règle l'autorisait pourtant à tirer, c'était un vrai
            # choix du joueur et il était effacé.
            wait_unit_is_monster_or_vehicle = bool(require_key(
                config.unit_is_monster_or_vehicle_by_type, wait_unit_type
            ))

            if wait_unit_engaged:
                has_close_quarters = any(require_key(w, 'is_close_quarters') for w in ranged_weapons)
                if not has_close_quarters and not wait_unit_is_monster_or_vehicle:
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
                    # Hors table : une escouade en réserves n'est PAS une cible (20.01). Mesurée
                    # depuis la sentinelle elle est à portée de n'importe quelle arme, donc tout
                    # WAIT légal ressortait en `wait_with_los` / `wait_with_targets`.
                    if not position_is_on_battlefield(enemy_pos):
                        continue
                    if not has_line_of_sight(wait_col, wait_row, enemy_pos[0], enemy_pos[1], state.wall_hexes):
                        continue
                    enemy_unit_type = require_key(state.unit_types, uid)
                    _enemy_socle = _analyzer_socle(config, enemy_unit_type, enemy_pos[0], enemy_pos[1])
                    _wait_ranged_edge = ranged_edge_distance(_wait_socle, _enemy_socle, _wait_metric)
                    # Les trois grandeurs de 10.06 / 17.03, toutes indépendantes de l'arme donc
                    # calculées une fois par ennemi. Mêmes noms et mêmes appels que `handle_shoot`.
                    #  - `target_engaged` : la cible est-elle engagée avec un ALLIÉ du joueur ?
                    #    L'unité qui attend est retirée de l'énumération de la primitive (elle itère
                    #    `unit_positions`), sinon un tireur engagé perdrait la cible que 10.06
                    #    l'autorise justement à viser.
                    target_engaged = is_within_engine_engagement_zone(
                        uid,
                        state.unit_player,
                        state.unit_positions,
                        state.unit_hp,
                        engagement_zone=_wait_ez,
                        position_override=enemy_pos,
                        positions_by_model=state.positions_by_model,
                        unit_base=state.unit_base,
                        **_wait_3d,
                        subject_models=state.positions_by_model.get(uid),  # get allowed
                        exclude_unit_id=wait_unit_id,
                    )
                    #  - l'unité qui attend est-elle engagée avec CETTE cible ? (10.06 : « you can
                    #    only select enemy units that are ENGAGED WITH your unit as targets »)
                    wait_unit_engaged_with_target = is_within_engine_engagement_zone(
                        wait_unit_id,
                        state.unit_player,
                        {uid: enemy_pos},
                        state.unit_hp,
                        engagement_zone=_wait_ez,
                        positions_by_model=state.positions_by_model,
                        unit_base=state.unit_base,
                        **_wait_3d,
                        subject_models=state.current_line_models.get(wait_unit_id),  # get allowed
                        subject_heights=state.current_line_heights.get(wait_unit_id),  # get allowed
                        position_override=(wait_col, wait_row),
                    )
                    #  - 17.03 : « enemy MONSTER/VEHICLE units that are engaged can be selected as
                    #    targets of ranged attacks ». N'exempte que la CIBLE : un tireur non-M/V
                    #    lui-même engagé reste borné au close-quarters (encadré de 17.03).
                    target_is_monster_or_vehicle = bool(require_key(
                        config.unit_is_monster_or_vehicle_by_type, enemy_unit_type
                    ))
                    target_mv_exempt = target_is_monster_or_vehicle and not wait_unit_engaged
                    can_reach = False
                    for weapon in ranged_weapons:
                        weapon_range = require_key(weapon, 'range')
                        is_close_quarters = require_key(weapon, 'is_close_quarters')
                        # Portée bord-à-bord (sélecteur `ranged`).
                        if _wait_ranged_edge > weapon_range:
                            continue
                        # Les deux mêmes conditions que les deux contrôles d'erreur de
                        # `handle_shoot`, à l'identique — un tir impossible là-bas est une cible
                        # invalide ici, et écrire deux modèles de règles pour un seul chemin de
                        # jeu est ce qui a laissé `handle_wait` diverger.
                        #
                        # 1) 10.06, volet « Non-MONSTER/Non-VEHICLE Models » : un tireur ENGAGÉ ne
                        #    peut attaquer qu'avec des armes [CLOSE-QUARTERS]. Un M/V engagé, lui,
                        #    tire avec TOUTES ses armes (au -1, que le moteur applique).
                        if wait_unit_engaged and not is_close_quarters and not wait_unit_is_monster_or_vehicle:
                            continue
                        # 2) Cible engagée : intirable, sauf arme [CLOSE-QUARTERS], sauf exemption
                        #    17.03 (cible M/V, tireur non engagé), sauf si le tireur est engagé
                        #    avec ELLE — c'est précisément ce que 10.06 l'autorise à viser.
                        if (
                            target_engaged
                            and not is_close_quarters
                            and not target_mv_exempt
                            and not wait_unit_engaged_with_target
                        ):
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
            # Ligne WAIT sans position lisible : on ne peut RIEN mesurer. Compter
            # `wait_no_targets` ici affirmait « cette unité n'avait aucune cible » sans avoir
            # regardé le plateau — un vert vacant, et le canal par lequel les 15 151 WAIT d'un run
            # entier sont sortis « sans cible ». On remonte l'erreur de lecture et on ne classe
            # rien : un compartiment vide se voit, un compartiment faux ne se voit pas.
            stats['parse_errors'].append({
                'episode': state.current_episode_num,
                'turn': turn,
                'phase': phase,
                'line': line.strip(),
                'error': "WAIT line without a readable 'Unit <id>(<col>,<row>)' position",
            })
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
        _build_move_bfs_blockers,
        _build_enemy_adjacent_hexes,
        _per_model_move_violation,
        get_adjacent_enemies,
        _debug_log,
        _get_unit_hp_value,
    )
    from ai.analyzer_perfig import surviving_start_models

    stats = state.stats
    if phase == 'SHOOT':
        stats['shoot_vs_wait']['advance'] += 1
        stats['shoot_vs_wait_by_player'][player]['advance'] += 1

    # Token optionnel `[FLY]` accepté, comme dans les regex de MOVED/FLED : sans lui l'advance
    # d'une escouade volante n'est pas parsée et sa position reste figée.
    from ai.analyzer_core import move_line_re
    advance_match = move_line_re("ADVANCED").search(action_desc)
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
            models_invalidated=advance_unit_id in state.models_invalidated,
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
        # 21.03 — jumeau du move : la traversée suit la DÉCLARATION loguée, pas le keyword du
        # registre. Le keyword exemptait toute unité volante même quand elle n'avait pas déclaré
        # (donc n'avait pas payé les -2" et ne traversait rien).
        advance_is_fly = re.search(
            r'ADVANCED\s+\[FLY\]\s+from', action_desc, re.IGNORECASE
        ) is not None
        # 21.03 : le vol DÉCLARÉ retranche aussi 2" au budget (`get_squad_move_budget`), comme
        # pour le move et la charge. Sans ce retrait, aucun advance volant hors budget n'était
        # remonté — les contrôles « mutualisés » ne mesuraient pas la même chose.
        advance_budget = max(0, (
            require_key(state.unit_move, advance_unit_id)
            + advance_roll * _get_inches_to_subhex_for_analyzer()
            - (2 * _get_inches_to_subhex_for_analyzer() if advance_is_fly else 0)
        ))
        occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
            state.positions_by_model, state.unit_positions, state.unit_base,
            state.unit_player, state.unit_hp, advance_unit_id,
        )
        advance_unit_type = require_key(state.unit_types, advance_unit_id)
        # CONTRÔLE PER-SOCLE (09 Movement / Advance) : identique au move, budget = D6×scale.
        # Chaque figurine avance de son origine (positions_by_model, ligne N-1) vers sa
        # destination ([MODELS:] de cette ligne). L'ancre d'escouade peut dépasser le budget
        # (reformation) tout en gardant chaque socle ≤ budget → l'ancre-à-ancre produisait de
        # faux « distance>roll » / « path blocked ».
        # Contrôle per-socle mutualisé (`_per_model_move_violation`), socles morts exclus.
        adv_over = _per_model_move_violation(
            surviving_start_models(
                state.positions_by_model.get(advance_unit_id),  # get allowed
                state.current_line_models.get(advance_unit_id),  # get allowed
            ),
            state.current_line_models.get(advance_unit_id),  # get allowed
            (start_col, start_row), (dest_col, dest_row),
            advance_budget, advance_is_fly,
            state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
        )
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
    from ai.analyzer_perfig import surviving_start_models
    if is_within_engine_engagement_zone(
        advance_unit_id,
        state.unit_player,
        positions_at_advance_reconciled,
        unit_hp_at_advance,
        engagement_zone=_get_engagement_zone_for_analyzer(),
        positions_by_model=state.positions_by_model,
        unit_base=state.unit_base,
        **state.engagement_3d_kwargs(),
        # Socles AVANT l'avance, morts exclus (cf. surviving_start_models).
        subject_models=surviving_start_models(
            state.positions_by_model.get(advance_unit_id),  # get allowed
            state.current_line_models.get(advance_unit_id),  # get allowed
        ),
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
