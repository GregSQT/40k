"""
fight_handler.py — gestion des actions FIGHT dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING, Optional, Tuple

from ai.analyzer_perfig import parse_shooter_models_segment
from ai.analyzer_rules import check_anti_x_threshold, note_rule_usage
from ai.analyzer_phases import died_before_phase
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
    # [FINEST HOUR] once_per_battle_melee_buff : la règle est portée par un modèle spécifique
    # (« this model's melee weapons get +N A »). Le bonus se calcule PAR FIGURINE et PAR TYPE
    # de figurine, car une escouade hétérogène (leader attaché + troupe) peut mêler des socles
    # avec et sans la règle sur la même ligne. On itère donc sur `shooters` comme per_model_attack_cap
    # et on consulte le type RÉEL de chaque socle (model_types), jamais le type d'escouade.
    if "[FINEST HOUR]" in action_desc:
        if shooters:
            for _mid in shooters:
                _model_type = state.model_types.get(_mid, fighter_unit_type)  # get allowed
                cap += config.once_per_battle_melee_bonus_by_type.get(_model_type, 0)  # get allowed
        else:
            # Repli : pas de [SHOOTER_MODELS:] → Finest Hour s'applique UNE FOIS par activation
            # (once_per_battle_melee_buff : once per battle, une escouade ne peut déclencher
            # l'abilité qu'une seule fois). Pas de multiplication par n_fighter_models.
            cap += config.once_per_battle_melee_bonus_by_type.get(fighter_unit_type, 0)  # get allowed
    # melee_attacks_bonus_while_waaagh (Da Biggest and da Best) : bonus PER-MODÈLE s'ajoutant
    # uniquement quand le Waaagh! est actif pour ce joueur (waaagh_bonus > 0). Distinct du
    # global waaagh_melee_atk déjà absorbé dans per_model_attack_cap via le paramètre `bonus`.
    # Le moteur applique les deux (fight_handlers.py:4710-4722) ; sans ce terme l'analyzer
    # sous-estime le plafond du Warboss de 4 et génère 4 faux positifs fight_over_cc_nb.
    if waaagh_bonus > 0 and shooters:
        for _mid in shooters:
            _mtype = state.model_types.get(_mid, fighter_unit_type)  # get allowed
            cap += config.melee_atk_bonus_waaagh_by_type.get(_mtype, 0)  # get allowed
    cleave_dice, cleave_error = additive_rule_extra_dice(
        "CLEAVE", action_desc, shooters, state.model_types, fighter_unit_type,
        weapon_display_name, config.unit_attack_limits, "cleave_by_weapon",
        config.cleave_by_weapon_global, n_fighter_models, target_models_at_declaration,
    )
    return cap + cleave_dice, cleave_error


def _note_melee_weapon_rule_usage(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    stats: dict,
    action_desc: str,
    line: str,
    turn: int,
    phase: str,
    fighter_id: str,
    fighter_unit_type: str,
    weapon_display_name: str,
    player: int,
) -> None:
    """Usage des règles d'armes de MÊLÉE (§1.8) — jumeau du site de tir, qui vivait seul.

    Le tableau §1.8 était bâti sur le seul équipement de TIR : aucune arme de mêlée n'y figurait,
    donc aucune règle propre à la mêlée n'a jamais été comptée. 32 paires (règle, arme) étaient
    hors du champ de la mesure, dont les deux armes [CLEAVE] dont le moteur écrit le token.

    CE QUI EST COMPTÉ ICI, et rien d'autre : les règles dont la ligne `FOUGHT` porte la trace.
      - `[CLEAVE:X]` et `[SUSTAINED HITS]` : tokens posés par le moteur quand la règle a JOUÉ ;
      - `[TWIN-LINKED]` : token posé par `_ability_token(woundRerollRule)` UNIQUEMENT quand une
        relance de blessure a effectivement eu lieu (cause `twin_linked`) — le token est absent
        si la blessure passe du premier coup. Même régime que les capacités d'unité relanceuses.

      - `DEVASTATING_WOUNDS` : `Save [DEVASTATING WOUNDS]`, que le formateur de mêlée écrit
        depuis le 2026-08-11 — il imprimait jusque-là `Save None(<seuil>+)`, un jet inexistant
        (24.10 : « no saving throw can be made »). Le compteur suit le token, comme au tir.

    CE QUI RESTE MUET, et pourquoi — le dire est la seule façon que le tableau ne mente pas :
      - `PRECISION`, `CLOSE_QUARTERS` : leur token n'existe qu'au TIR (`shoot_handler`), la
        mêlée n'en compte donc pas l'usage. Elles ressortent « NOT USED » de ce côté.
      - `PSYCHIC` : mot-clé d'INTERACTION (24.29), pas un effet discret à compter. Il reçoit
        le statut `N/A — KEYWORD` dans §1.8 (`_INTERACTION_ONLY_WEAPON_RULES`, `analyzer.py`) —
        il n'y a structurellement rien à incrémenter, et 0 ne signifie pas « jamais exercé ».
      - `TORRENT`, `IGNORES_COVER`, `LETHAL_HITS`, `EXTRA_ATTACKS`, `ANTI-X` : comptés depuis
        le 2026-08-19 (lot2) par token — `[TORRENT]`, `[IGNORES COVER]`, `[LETHAL HITS]`,
        `[EXTRA ATTACKS]`, `[ANTI-keyword:N+]` — avec contrôle de validité associé (TORRENT →
        Hit None, LETHAL HITS → Wound None, ANTI-X → seuil token = seuil armurerie).
    """
    from ai.analyzer_perfig import weapon_profile_for_line

    if not fighter_unit_type:
        return
    weapon_info, carrier_type, ambiguous = weapon_profile_for_line(
        parse_shooter_models_segment(action_desc), state.model_types, fighter_unit_type,
        weapon_display_name, config.unit_weapons_cache, is_melee=True,
    )
    if ambiguous:
        # Plusieurs datasheets hors escouade déclarent cette arme : le journal ne dit pas
        # laquelle a frappé. Attribuer au hasard inventerait un usage — même traitement qu'au
        # tir, le cas se voit dans `parse_errors` au lieu de se ranger sous une étiquette fausse.
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': (
                f"Ambiguous melee weapon carrier for '{weapon_display_name}': "
                f"{', '.join(ambiguous)}"
            ),
        })
        return
    if weapon_info is None or carrier_type is None:
        return
    weapon_rules_list = require_key(weapon_info, "rules")
    weapon_key = f"{weapon_display_name} ({carrier_type})"
    pl_int = int(require_key(state.unit_player, fighter_id))
    if '[TWIN-LINKED]' in action_desc:
        stats['weapon_rule_usage'][("TWIN_LINKED", weapon_key)][pl_int] += 1
    if re.search(r'\[SUSTAINED(?: |_)?HITS\]', action_desc, re.IGNORECASE):
        stats['weapon_rule_usage'][("SUSTAINED_HITS", weapon_key)][pl_int] += 1
    if re.search(r'\[CLEAVE:\d+\]', action_desc, re.IGNORECASE):
        stats['weapon_rule_usage'][("CLEAVE", weapon_key)][pl_int] += 1
    # 24.10 — JUMEAU EXACT du site de tir : `Save [DEVASTATING WOUNDS]` est la trace de
    # l'APPLICATION (sauvegarde sautée), donc ce qui se compte.
    if re.search(r'Save\s+\[DEVASTATING WOUNDS\]', action_desc, re.IGNORECASE):
        stats['weapon_rule_usage'][("DEVASTATING_WOUNDS", weapon_key)][pl_int] += 1
    # [TORRENT] 24.37, [IGNORES COVER] 24.18, [LETHAL HITS] 24.23, [EXTRA ATTACKS], [ANTI-X] 24.03
    # — JUMEAUX du site de tir. Compteurs + validité (voir shoot_handler pour le détail complet).
    _stripped = line.strip()
    _torrent_m = re.search(r'\[TORRENT\]', action_desc, re.IGNORECASE)
    if _torrent_m:
        stats['weapon_rule_usage'][("TORRENT", weapon_key)][pl_int] += 1
        from ai.analyzer_hit import HIT_SEGMENT_RE as _HIT_RE
        if _HIT_RE.search(action_desc):
            stats['torrent_wrong_hit_fight'][pl_int] += 1
            if stats['first_error_lines']['torrent_wrong_hit_fight'][pl_int] is None:
                stats['first_error_lines']['torrent_wrong_hit_fight'][pl_int] = {'episode': state.current_episode_num, 'line': _stripped}
    if re.search(r'\[IGNORES COVER\]', action_desc, re.IGNORECASE):
        stats['weapon_rule_usage'][("IGNORES_COVER", weapon_key)][pl_int] += 1
    _lethal_m = re.search(r'\[LETHAL HITS\]', action_desc, re.IGNORECASE)
    if _lethal_m:
        stats['weapon_rule_usage'][("LETHAL_HITS", weapon_key)][pl_int] += 1
        if re.search(r'\bWound\s+\d+\(\d+\+\)', action_desc):
            stats['lethal_hits_wrong_wound_fight'][pl_int] += 1
            if stats['first_error_lines']['lethal_hits_wrong_wound_fight'][pl_int] is None:
                stats['first_error_lines']['lethal_hits_wrong_wound_fight'][pl_int] = {'episode': state.current_episode_num, 'line': _stripped}
    if re.search(r'\[EXTRA ATTACKS\]', action_desc, re.IGNORECASE):
        stats['weapon_rule_usage'][("EXTRA_ATTACKS", weapon_key)][pl_int] += 1
    _anti_m = re.search(r'\[ANTI-(\w+):(\d+)\+\]', action_desc, re.IGNORECASE)
    if _anti_m:
        _anti_kw = _anti_m.group(1).upper()
        _anti_tok_thresh = int(_anti_m.group(2))
        _anti_rule_name = f"ANTI_{_anti_kw}"
        stats['weapon_rule_usage'][(_anti_rule_name, weapon_key)][pl_int] += 1
        check_anti_x_threshold(
            weapon_rules_list,
            _anti_kw, _anti_tok_thresh, _anti_rule_name,
            stats, state, turn, phase, line.strip(), weapon_key, " (mêlée)",
        )


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
        # Select Targets step de l'ACTIVATION (escouade attaquante × cible), figé à sa PREMIÈRE
        # ligne : c'est l'effectif qu'exige [CLEAVE] 24.06, et le combat tue en avançant. Lu
        # AVANT les dégâts de la ligne courante (`models_alive_pre_line`).
        #
        # Hors de toute branche de résolution d'arme — JUMEAU du tir : une arme dont le NB ne se
        # résout pas (`parse_error`) tue quand même, et si elle avait empêché le gel, l'arme
        # suivante aurait hérité de l'effectif d'APRÈS ses pertes.
        fight_activation_key = (state.fight_phase_seq_id, fighter_id, target_id)
        attacker_player = require_key(state.unit_player, fighter_id)
        # [TARGET_DECL:N] : effectif de la cible loggé par le moteur au SelectTargets step.
        # Present sur toutes les lignes du groupe ; None sur les anciens logs (pré-fix).
        _target_decl = re.search(r'\[TARGET_DECL:(\d+)\]', line)
        _alive_override = int(_target_decl.group(1)) if _target_decl else None
        frozen_target = state.freeze_select_targets(
            state.fight_sequence_target_models, fight_activation_key, target_id, attacker_player,
            log_anchor=(target_col, target_row),
            alive_override=_alive_override,
        )
        engagement_positions, engagement_hp, engagement_models = state.engagement_maps(
            frozen_target, target_id
        )
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
        elif '[FIGHTS FIRST]' in line:
            # 24.13 : FIGHTS FIRST combat avant l'alternance ordinaire — légal même si des
            # unités chargées n'ont pas encore combattu.
            pass
        else:
            eligible_charged_units = []
            for charged_id in state.charged_units_current_fight:
                if charged_id in state.charged_units_fought:
                    continue
                if charged_id not in engagement_positions:
                    continue
                if charged_id not in engagement_hp or require_key(engagement_hp, charged_id) <= 0:
                    continue
                if is_within_engine_engagement_zone(
                    charged_id,
                    state.unit_player,
                    engagement_positions,
                    engagement_hp,
                    engagement_zone=_get_engagement_zone_for_analyzer(),
                    positions_by_model=engagement_models,
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
            from ai.analyzer_hit import check_hit_result, check_melee_hit_threshold
            check_hit_result(state, stats, line, action_desc, player, is_melee=True)
            # Seuil de TOUCHE 05.01 + modificateurs Primitive A (chantier 06). `check_hit_result`
            # ci-dessus juge le VERDICT contre le seuil imprimé ; celui-ci juge le SEUIL lui-même
            # contre la WS des datasheets — sans lui, un +1 appliqué à tort passerait les deux.
            check_melee_hit_threshold(
                state, config, stats, line, action_desc, player, fighter_id,
                fighter_unit_type, weapon_display_name,
                parse_shooter_models_segment(action_desc),
            )
            # Primitive A : la règle a été JUGÉE sur cette ligne (le contrôle ci-dessus s'est
            # prononcé sur un seuil qui l'inclut), donc l'exercice se note ici et pas à l'entrée
            # du handler. `unit_effect_in_force` — pas `unit_rules_by_type[fighter_unit_type]` :
            # la capacité vient du LEADER attaché, jamais du type de l'escouade.
            from ai.analyzer_perfig import unit_effect_in_force
            for _effect, _rule in (
                ("hit_roll_bonus_fight", "PROJ.1.4.hit_roll_bonus_fight"),
                ("wound_roll_bonus_fight", "PROJ.1.4.wound_roll_bonus_fight"),
            ):
                if unit_effect_in_force(state, config, fighter_id, _effect):
                    note_rule_usage(stats, _rule, player)
            # Seuil de blessure 05.02, JUMEAU du tir : même contrôle, même fonction, avec le
            # +1 Force du Waaagh qui n'existe qu'ici (08.04). Cf. ai/analyzer_wound.py.
            from ai.analyzer_wound import check_wound_threshold, wound_bonus_applies
            check_wound_threshold(
                state, config, stats, line, action_desc, player, fighter_id, fighter_unit_type,
                weapon_display_name, target_id, parse_shooter_models_segment(action_desc), is_melee=True,
            )
            # 08.04 Oath of Moment — JUMEAU du tir : la règle joue aussi en mêlée.
            _oath_carriers = config.rule_to_units.get("oath_of_moment", set())
            if fighter_unit_type in _oath_carriers and wound_bonus_applies(action_desc):
                note_rule_usage(stats, "PROJ.1.2.oath_target", player)
                _oath_t = state.active_effects.get(player, {}).get("oath_target")  # get allowed : aucun effet actif pour ce joueur
                if _oath_t is not None and _oath_t != target_id:
                    stats['oath_target_mismatch'][player] += 1
                    if stats['first_error_lines']['oath_target_mismatch'][player] is None:
                        stats['first_error_lines']['oath_target_mismatch'][player] = {
                            'episode': state.current_episode_num, 'line': line.strip()
                        }
            _note_melee_weapon_rule_usage(
                state, config, stats, action_desc, line, turn, phase,
                fighter_id, fighter_unit_type, weapon_display_name, player,
            )
            # reroll_1_save_fight : la règle appartient à la CIBLE (défenseur qui relance sa svg).
            # Détection sur Save+[REROLLED:] dans le segment de sauvegarde.
            if re.search(r'Save\s+\d+\([^)]+\)\s+\[REROLLED:\d+\]', action_desc, re.IGNORECASE):
                _target_player = state.unit_player.get(target_id, player)  # get allowed
                _target_type = state.unit_types.get(target_id)  # get allowed
                if _target_type and "reroll_1_save_fight" in config.unit_rules_by_type.get(_target_type, set()):
                    note_rule_usage(stats, "PROJ.1.4.reroll_save_fight", _target_player)
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
                    cc_nb, _cleave_error = _cc_cap_for_line(
                        state, config, action_desc, attacker_player, fighter_unit_type,
                        weapon_display_name, cc_nb_single, n_fighter_models, _shooters,
                        frozen_target.models_alive,
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
                        if _alive_override is None:
                            # Effectif moteur non journalisé (log antérieur à [TARGET_DECL:N]) :
                            # l'effectif reconstruit peut diverger de l'état au SelectTargets step
                            # (fix 2 purge les entrées périmées) → CC_NB CLEAVE possiblement
                            # sous-estimé. Non jugeable sans la valeur originelle.
                            stats['fight_over_cc_nb_unverifiable'][attacker_player] += 1
                        else:
                            stats['fight_over_cc_nb'][attacker_player] += 1
                            fight_over_by_unit = require_key(stats, 'fight_over_cc_nb_by_unit')
                            fight_over_by_player = require_key(fight_over_by_unit, attacker_player)
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
        attacker_is_dead = fighter_id in state.unit_hp and state.unit_hp[fighter_id] <= 0
        if attacker_is_dead:
            if died_before_phase(fighter_id, turn, phase, state.line_number, state.unit_deaths):
                attacker_player = require_key(state.unit_player, fighter_id)
                stats['fight_dead_unit_attacker'][attacker_player] += 1
                if stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] is None:
                    stats['first_error_lines']['fight_dead_unit_attacker'][attacker_player] = {'episode': state.current_episode_num, 'line': line.strip()}

        # RULE: Fight a dead unit (target is dead)
        target_is_dead = target_id in state.unit_hp and state.unit_hp[target_id] <= 0
        if target_is_dead:
            target_died_before_fight = died_before_phase(target_id, turn, phase, state.line_number, state.unit_deaths)
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
        r'Unit (\d+)\(\d+,\s*\d+\) (CONSOLIDATED|(?:OVERRUN )?PILED IN) from '
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
    moved = anchor_from != anchor_to
    # Pile-in invalide (budget dépassé) : ne pas marquer comme ayant combattu afin que
    # la violation d'alternance 12.04 reste détectable si une unité non-chargée combat ensuite.
    pile_in_move_valid = True
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
            pile_in_move_valid = False

    # Une unité chargée sélectionnée sans cible vivante ne produit pas de ligne FOUGHT :
    # la marquer ici comme ayant eu son tour évite un faux positif d'alternance (12.04).
    # Condition : le pile-in doit être valide ; sinon la violation d'alternance reste détectable.
    if unit_id in state.charged_units_current_fight and pile_in_move_valid:
        state.charged_units_fought.add(unit_id)

    # Recale l'ancre : sans ça elle reste figée sur la position de combat et le move suivant
    # remonte un faux mismatch position/log (2.2).
    # Pile-in invalide : ne pas mettre à jour — l'ancre "réelle" reste à anchor_from,
    # ce qui préserve le statut en zone d'engagement pour le contrôle d'alternance 12.04.
    if pile_in_move_valid:
        _position_cache_set(state.unit_positions, unit_id, anchor_to[0], anchor_to[1])
    # Ancre mise à jour sans [MODELS:] (les lignes PILED IN/CONSOLIDATED n'en portent pas) :
    # purge pour forcer le retour à l'ancre dans les contrôles suivants (miroir du fix FLED/MOVED).
    state.positions_by_model.pop(unit_id, None)
