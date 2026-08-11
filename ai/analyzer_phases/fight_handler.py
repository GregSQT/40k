"""
fight_handler.py — gestion des actions FIGHT dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING, Optional, Tuple

from ai.analyzer_perfig import parse_shooter_models_segment
from shared.data_validation import require_key

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


def _cc_cap_for_line(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    action_desc: str,
    attacker_player: int,
    fighter_unit_type: str,
    weapon_display_name: str,
    cc_nb_squad_type: int,
    n_fighter_models: int,
    shooters: Tuple[str, ...],
    target_models_at_declaration: int,
) -> Tuple[int, Optional[str]]:
    """Plafond d'attaques de MÊLÉE de cette ligne — le calcul est mutualisé avec le TIR.

    Ce site ne porte plus que ce qui est PROPRE à la mêlée : le bonus d'attaques du Waaagh, LU
    dans `T{tour} EFFECTS:` et jamais redeviné (le coder ici ferait vivre une seconde définition
    de la règle, qui divergerait le jour où la constante du moteur bouge ; le token `[WAAAGH!]`
    des lignes d'attaque reste un confort de lecture, ce n'est plus la donnée). Le comptage
    par-figurine lui-même vit dans `analyzer_perfig.per_model_attack_cap`, avec son jumeau de tir.

    [CLEAVE X] 24.06 relève ce plafond quand le moteur a posé son token : ses dés additionnels
    sont des ATTAQUES, elles occupent des lignes de journal, et les compter comme un dépassement
    a produit les 24 fausses « Attacks over CC_NB » du run du 2026-08-11 — la totalité du
    compteur. Le calcul est celui de [BLAST] au tir, au même endroit.

    Retourne `(plafond, erreur de journal ou None)`.
    """
    from ai.analyzer_perfig import additive_rule_extra_dice, per_model_attack_cap

    # `+1` / `1` sont tous deux acceptés : c'est le producteur qui choisit sa forme, le lecteur
    # ne lui impose rien.
    _effects = state.active_effects.get(int(attacker_player), {})  # get allowed : aucun effet
    _atk = _effects.get("waaagh_melee_atk")  # get allowed
    waaagh_bonus = int(str(_atk).lstrip("+")) if _atk is not None else 0

    cap = per_model_attack_cap(
        shooters, state.model_types, fighter_unit_type, weapon_display_name,
        config.unit_attack_limits, "cc_nb_by_weapon", config.cc_nb_by_weapon_global,
        cc_nb_squad_type, n_fighter_models, waaagh_bonus,
    )
    cleave_dice, cleave_error = additive_rule_extra_dice(
        "CLEAVE", action_desc, shooters, state.model_types, fighter_unit_type,
        weapon_display_name, config.unit_attack_limits, "cleave_by_weapon",
        config.cleave_by_weapon_global, n_fighter_models, target_models_at_declaration,
    )
    return cap + cleave_dice, cleave_error


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
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
    )

    stats = state.stats
    state.units_fought.add(unit_id)

    # Grammaire PARTAGÉE avec l'aiguillage et l'application des dégâts (`attack_line_re`) : trois
    # copies écrites à la main avaient déjà divergé sur le token `[WAAAGH!]`. Import local :
    # `analyzer_core` importe ce module au chargement (cycle sinon), comme les helpers ci-dessus.
    from ai.analyzer_core import attack_line_re

    fight_match = attack_line_re().search(action_desc)
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
                    positions_by_model=state.positions_by_model,
                    unit_base=state.unit_base,
                    **state.engagement_3d_kwargs(),
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
            # Résultat de touche 05.01, JUMEAU du tir : même table, même fonction. Cf.
            # ai/analyzer_hit.py.
            from ai.analyzer_hit import check_hit_result
            check_hit_result(state, stats, line, action_desc, player, is_melee=True)
            # Seuil de blessure 05.02, JUMEAU du tir : même contrôle, même fonction, avec le
            # +1 Force du Waaagh qui n'existe qu'ici (08.04). Cf. ai/analyzer_wound.py.
            from ai.analyzer_wound import check_wound_threshold
            check_wound_threshold(
                state, config, stats, line, action_desc, player, fighter_unit_type,
                weapon_display_name, target_id, parse_shooter_models_segment(action_desc), is_melee=True,
            )
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
                    # Effectif de l'unite qui frappe. [MODELS:] de la ligne courante d'abord
                    # (source de verite per-socle) ; a defaut l'effectif PERSISTANT connu de
                    # l'analyzer, tenu a jour a chaque ligne portant le segment. `_models_segment`
                    # rend une chaine vide quand l'unite a quitte `units_cache` avant le flush du
                    # log (derniere figurine tuee pendant l'action) : retomber directement sur 1
                    # sous-estimait alors le plafond d'attaques d'une escouade de 10 et fabriquait
                    # de faux verdicts « trop d'attaques ». 1 reste la borne minimale ultime.
                    n_fighter_models = (
                        len(state.current_line_models.get(fighter_id, {}))  # get allowed
                        or state.unit_models_alive.get(fighter_id, 0)  # get allowed
                        or 1
                    )
                    # PLAFOND PAR FIGURINE, pas par escouade. Une escouade n'est pas homogène :
                    # la règle 19 y replie un personnage COMME figurine, et le roster y met
                    # sergents et armes spéciales. Cinq armes distinctes s'appellent « Close
                    # Combat Weapon », de NB 2 à 6 : le nom d'affichage ne tranche pas, seul le
                    # type de la FIGURINE le fait ([MODEL_TYPES:] de l'entête d'épisode).
                    # Mesuré sur le run du 2026-08-08, ce plafond d'escouade produisait 20 fausses
                    # « Attacks over CC_NB » : 5 attaques d'un Ancient rattaché (NB=5) plafonnées
                    # au NB=3 de l'Intercessor porteur, 20 attaques de 10 Gretchin plafonnées à 10.
                    _shooters = parse_shooter_models_segment(action_desc)
                    # Le GROUPE de figurines qui frappe entre dans la clé, parce qu'il détermine
                    # le plafond. Sans lui, un compteur accumulé sur (phase, unité, arme) était
                    # comparé au plafond du DERNIER groupe : une escouade qui répartit ses
                    # attaques entre deux cibles voyait la somme des deux groupes opposée au
                    # plafond d'un seul — le faux positif que ce lot devait supprimer.
                    seq_key = (state.fight_phase_seq_id, fighter_id, weapon_display_name, _shooters)
                    if (state.last_fight_fighter_id != fighter_id or
                            state.last_fight_weapon != weapon_display_name or
                            state.last_fight_shooters != _shooters):
                        state.fight_sequence_counts[seq_key] = 0
                    state.last_fight_fighter_id = fighter_id
                    state.last_fight_weapon = weapon_display_name
                    state.last_fight_shooters = _shooters
                    if seq_key not in state.fight_sequence_counts:
                        state.fight_sequence_counts[seq_key] = 0
                    elif step_marker_present and step_inc:
                        state.fight_sequence_counts[seq_key] = 0
                    # Select Targets step — l'effectif de la cible y est figé, parce que c'est
                    # celui qu'exige [CLEAVE] 24.06 et que le combat tue en avançant. Lu AVANT
                    # les dégâts de la ligne courante (`models_alive_pre_line`) : la première
                    # ligne d'une activation peut déjà avoir retiré un socle.
                    #
                    # ⚠️ La clé est l'ACTIVATION (escouade attaquante × cible), PAS la séquence
                    # par arme : le moteur déclare TOUTES ses attaques d'un coup, avant d'en
                    # résoudre une seule. Figer par arme donnait à la dernière arme de la file
                    # l'effectif SURVIVANT aux précédentes — mesuré sur le run du 2026-08-11,
                    # 11 des 24 lignes restaient fausses (le Bigboss frappe après les Choppa de
                    # son escouade, qui ont déjà fait tomber la cible sous la tranche de 5).
                    activation_key = (state.fight_phase_seq_id, fighter_id, target_id)
                    if activation_key not in state.fight_sequence_target_models:
                        state.fight_sequence_target_models[activation_key] = require_key(
                            state.models_alive_pre_line, target_id
                        )
                    cc_nb, _cleave_error = _cc_cap_for_line(
                        state, config, action_desc, attacker_player, fighter_unit_type,
                        weapon_display_name, cc_nb_single, n_fighter_models, _shooters,
                        require_key(state.fight_sequence_target_models, activation_key),
                    )
                    if _cleave_error is not None:
                        stats['parse_errors'].append({
                            'episode': state.current_episode_num,
                            'turn': turn,
                            'phase': phase,
                            'line': line.strip(),
                            'error': _cleave_error,
                        })
                    # [SUSTAINED HITS X] 24.36 — JUMEAU du plafond de tir : une touche
                    # additionnelle n'est pas une attaque et ne consomme rien du pool. Le
                    # moteur l'écrit sans jet de touche et la marque explicitement.
                    if re.search(r'\[SUSTAINED(?: |_)?HITS\]', action_desc, re.IGNORECASE) is None:
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

        # RULE: Fight from non-adjacent — CONTRÔLE RETIRÉ (2026-07-24).
        # Non reconstructible depuis step.log, pour DEUX raisons prouvées (cf. investigation) :
        #   1. MÉTRIQUE. Le moteur gate le combat en EUCLIDIEN (config
        #      distance_metric.engagement="euclidean" → entries_in_engagement_zone / seuil
        #      engagement_minimum_clearance_norm = ez×1,5). Ce contrôle mesurait en HEX
        #      (squads_min_edge_distance = min_distance_between_sets). Sur socles à grand
        #      diamètre (ex. round/18 vs round/6), l'écart hex↔euclidien au bord dépasse 1 subhex :
        #      hexEdge=12 alors que euclidien=13,5 ≤ 15 → engagé pour le moteur, "non-adjacent"
        #      faussement pour l'analyzer.
        #   2. POSITION CIBLE. La position de la cible AU MOMENT DU COMBAT n'est PAS journalisée
        #      de façon fiable : positions_by_model est périmé (maj uniquement quand la cible AGIT),
        #      et [TARGET_MODELS:] liste les SURVIVANTS POST-PERTES (les socles proches détruits ont
        #      disparu → survivants plus loin). Aucune source log ne donne l'empreinte cible pré-perte.
        # Le moteur garantit déjà l'invariant au gate _fight_build_valid_target_pool (n'ajoute que
        # des cibles dans la zone d'engagement euclidienne). Un contrôle analyzer qui relirait ces
        # positions depuis le log referait le MÊME calcul que le moteur (mêmes empreintes, même
        # primitive) → tautologie, aucune détection. La vérification vit donc dans le moteur, figée
        # par tests/unit/engine/test_fight_spatial_contract.py (dont
        # test_fight_b_engagement_pool_large_base_euclidean_not_hex, qui verrouille précisément le cas
        # grand-socle hex≠euclidien à l'origine de ce faux positif).

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
            # Exception 05 Attack sequence : les attaques restantes de la MÊME activation
            # (même attaquant, même turn/phase) qui a détruit la cible sont des « excess
            # attacks lost », pas une attaque sur cadavre → ne pas compter.
            same_activation_kill = state.unit_kill_context.get(target_id) == (fighter_id, turn, phase)
            if target_died_before_fight and not same_activation_kill:
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


def handle_fight_move(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    line: str,
    action_desc: str,
    player: int,
    turn: int,
    phase: str,
) -> None:
    """Pile-in (12.03) et consolidation (12.08) — les deux déplacements de la phase de combat.

    MAXIMUM DISTANCE 3" pour l'un comme pour l'autre, et « moves as described in Moving (03) » :
    budget et obstacles sont donc communs, et c'est le seul contrôle mutualisé ici. Le RESTE de
    ces deux règles diffère (conditions d'éligibilité, figurines au contact qui ne bougent pas,
    post-conditions) : elles gardent donc des compteurs SÉPARÉS, faute de quoi une ligne
    d'exemple ne dit plus de laquelle elle vient.

    Ce contrôle vivait inline dans la boucle d'aiguillage de `analyzer_core`, au 8e niveau
    d'indentation, alors que toutes ses branches sœurs délèguent à un handler : il n'était
    atteignable en test qu'en faisant passer un fichier de log complet.
    """
    from ai.analyzer import (
        _build_move_bfs_blockers,
        _per_model_move_violation,
        _get_inches_to_subhex_for_analyzer,
        _position_cache_set,
    )
    from ai.analyzer_perfig import surviving_start_models

    stats = state.stats
    match = re.search(
        r'Unit (\d+)\(\d+,\s*\d+\) (CONSOLIDATED|PILED IN) from '
        r'\((\d+),\s*(\d+)\) to \((\d+),\s*(\d+)\)',
        action_desc,
    )
    if not match:
        return
    unit_id = match.group(1)
    kind = 'consolidation' if match.group(2) == 'CONSOLIDATED' else 'pile_in'
    anchor_from = (int(match.group(3)), int(match.group(4)))
    anchor_to = (int(match.group(5)), int(match.group(6)))

    if unit_id not in state.unit_hp or require_key(state.unit_hp, unit_id) <= 0:
        return

    prev_models = surviving_start_models(
        state.positions_by_model.get(unit_id),  # get allowed
        state.current_line_models.get(unit_id),  # get allowed
    )
    new_models = state.current_line_models.get(unit_id)  # get allowed
    moved = bool(prev_models and new_models) or anchor_from != anchor_to
    if moved:
        occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
            state.positions_by_model, state.unit_positions, state.unit_base,
            state.unit_player, state.unit_hp, unit_id,
        )
        # Budget pris à la MÊME source que le moteur : 3" × résolution du run.
        if _per_model_move_violation(
            prev_models, new_models, anchor_from, anchor_to,
            3 * _get_inches_to_subhex_for_analyzer(), False,
            state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
        ):
            stats['fight_move_invalid'][kind][player] += 1
            if stats['first_error_lines']['fight_move_invalid'][kind][player] is None:
                stats['first_error_lines']['fight_move_invalid'][kind][player] = {
                    'episode': state.current_episode_num, 'line': line.strip()
                }

    # Recale l'ancre : sans ça elle reste figée sur la position de combat et le move suivant
    # remonte un faux mismatch position/log (2.2).
    _position_cache_set(state.unit_positions, unit_id, anchor_to[0], anchor_to[1])
