"""
charge_handler.py — gestion des actions CHARGE dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from ai.analyzer_rules import note_rule_usage
from ai.analyzer_phases import died_before_phase
from shared.data_validation import require_key

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig


#: Bornes du jet de charge NU (11.02, 2D6). Le `charge_roll_bonus` de la Primitive A les décale
#: toutes deux de +1 — il s'ajoute au jet, pas au budget, et n'a aucun plafond.
_CHARGE_ROLL_MIN = 2
_CHARGE_ROLL_MAX = 12


def _check_charge_roll_range(
    state: "AnalyzerState",
    config: "AnalyzerConfig",
    line: str,
    action_desc: str,
    charge_unit_id: str,
    player: int,
) -> None:
    """11.02 + Primitive A : le jet imprimé tient-il dans les bornes que ses tokens annoncent ?

    Le jet écrit dans `[Roll: N]` est NET — le `+1` de Somethin' to Prove y est déjà. Un 13 est
    donc légitime, et un 13 SANS la capacité ne l'est pas : c'est exactement ce que ce contrôle
    sépare, et rien d'autre ne le faisait. Le budget de charge, lui, est déjà vérifié en aval
    (`charge_invalid.distance_over_roll`), mais il PART de ce jet : un jet faux y passe inaperçu.

    Le verdict « la capacité est en vigueur » vient des DATASHEETS des figurines vivantes (19.04),
    pas du token — un contrôle qui confronte deux sorties du même moteur ne prouve rien. Le token
    est vérifié CONTRE ce verdict, ce qui couvre les deux sens de l'erreur : bonus appliqué sans
    la capacité, et capacité en vigueur dont le jet n'a pas bougé.

    Ne se prononce pas quand les socles vivants du chargeur sont inconnus (`None`) : on ne devine
    pas quelle figurine porte encore la capacité.
    """
    from ai.analyzer_perfig import unit_effect_in_force

    roll_match = re.search(r'\[Roll:\s*(\d+)\]', action_desc)
    if roll_match is None:
        return
    in_force = unit_effect_in_force(state, config, charge_unit_id, "charge_roll_bonus")
    if in_force is None:
        return
    stats = state.stats
    bonus = 1 if in_force else 0
    roll = int(roll_match.group(1))
    tokens = config.effect_display_tokens.get("charge_roll_bonus", set())  # get allowed
    token_seen = any(f"[{name}]" in action_desc.upper() for name in tokens)
    detail = None
    if not (_CHARGE_ROLL_MIN + bonus <= roll <= _CHARGE_ROLL_MAX + bonus):
        detail = (
            f"jet {roll} hors de [{_CHARGE_ROLL_MIN + bonus},{_CHARGE_ROLL_MAX + bonus}] "
            f"(charge_roll_bonus={'oui' if bonus else 'non'})"
        )
    elif token_seen != bool(bonus):
        detail = (
            f"token de charge_roll_bonus {'present' if token_seen else 'absent'} "
            f"alors que la capacite est {'en vigueur' if bonus else 'absente'} (19.04)"
        )
    if detail is not None:
        stats['charge_roll_out_of_range'][player] += 1
        first = stats['first_error_lines']['charge_roll_out_of_range']
        if first[player] is None:
            first[player] = {
                'episode': state.current_episode_num,
                'line': line.strip(),
                'detail': detail,
            }
    if bonus:
        note_rule_usage(stats, "PROJ.1.3.charge_roll_bonus", player)


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
        _get_inches_to_subhex_for_analyzer,
        _build_move_bfs_blockers,
        _per_model_move_violation,
    )
    from ai.analyzer_perfig import surviving_start_models

    stats = state.stats

    # `*` et non `?` : la ligne peut porter DEUX marqueurs — le nom de la règle qui a permis la
    # charge, ET `[FLY]` (21.03). Avec `?`, la charge d'une unité volante bénéficiant d'une
    # relance n'était plus reconnue du tout, donc plus contrôlée. Même piège que sur le move.
    #
    # `[^\]]+` et non une classe de caractères énumérée : un nom de capacité n'est pas un
    # identifiant. `[WAAAGH!]` (capacité de faction) porte un `!`, qui sortait de
    # `[A-Za-z0-9_ ]` — la ligne devenait INVISIBLE pour l'analyzer, donc aucune charge comptée,
    # aucun contrôle `charge_invalid`, et la position de l'unité figée sur un fantôme. Le
    # marqueur de tir (`SHOT`) utilise déjà cette forme : c'est celle-ci qui est la référence.
    charge_match = re.search(
        r'Unit (\d+)\s*\((\d+),\s*(\d+)\)\s+CHARGED(?:\s+(?:\([^)]+\)|\[[^\]]+\]))*\s+Unit (\d+)(?:\s*\((\d+),\s*(\d+)\))?(?:,Unit \d+(?:\s*\(\d+,\s*\d+\))?)*\s+from \((\d+),\s*(\d+)\)\s+to \((\d+),\s*(\d+)\)',
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
        # 11.02 + Primitive A : bornes du jet imprimé. AVANT le contrôle de budget ci-dessous,
        # qui PART de ce jet — un jet faux y passerait pour un budget légitime.
        _check_charge_roll_range(state, config, line, action_desc, charge_unit_id, player)
        if charge_unit_id in state.units_advanced:
            charge_unit_type = require_key(state.unit_types, charge_unit_id)
            unit_rules = require_key(config.unit_rules_by_type, charge_unit_type)
            # Waaagh! (08.04) : DEUXIÈME source d'éligibilité à la charge après Advance, à côté
            # de la capacité de datasheet — et elle ne vit dans AUCUN `unit_rules` (capacité de
            # FACTION, cf. Documentation/Reference/jeu/regles_unites.md). Le seul témoin dans le journal est le
            # marqueur que le moteur écrit sur la ligne. Sans cette lecture, toute charge orke
            # après avance remonte en `charge_invalid.advanced` : une faute inventée, sur un
            # coup parfaitement légal.
            _waaagh_charge = re.search(r'\[WAAAGH!\]', action_desc, re.IGNORECASE) is not None
            if _waaagh_charge:
                key = ("waaagh", charge_unit_type)
                stats['special_rule_usage'][key][player] += 1
            elif "charge_after_advance" in unit_rules:
                key = ("charge_after_advance", charge_unit_type)
                stats['special_rule_usage'][key][player] += 1
            else:
                stats['charge_invalid'][player]['advanced'] += 1
                if stats['first_error_lines']['charge_invalid'][player] is None:
                    stats['first_error_lines']['charge_invalid'][player] = {'episode': state.current_episode_num, 'line': line.strip()}
        # reroll_charge — capacité exercée si [REROLLED:] présent dans la ligne CHARGED.
        if re.search(r'\[REROLLED:\d+\]', action_desc):
            _reroll_type = require_key(state.unit_types, charge_unit_id)
            _reroll_rules = config.unit_rules_by_type.get(_reroll_type, set())
            if "reroll_charge" in _reroll_rules:
                note_rule_usage(stats, "PROJ.1.3.reroll_charge", player)

        charge_roll_match = re.search(r'\[Roll:\s*(\d+)\]', action_desc)
        if charge_roll_match:
            # BUDGET (11.04 / 21.03) — MIROIR de l'advance, qui faisait déjà les trois choses
            # que ce contrôle ne faisait pas :
            #  - le jet loggué est en POUCES, la distance en subhex : sans conversion, à x5 un
            #    jet de 7 devenait un plafond de 7 subhex au lieu de 35, et TOUTE charge
            #    réussie remontait en faute ;
            #  - le vol déclaré retranche 2" (`_charge_budget_subhex` côté moteur) ;
            #  - la distance se mesure PAR FIGURINE, pas d'ancre à ancre : en V11 l'ancre
            #    d'escouade peut bondir plus loin qu'aucun socle (reformation) — faux positif —
            #    et un socle peut aller plus loin que l'ancre — vraie violation manquée.
            _scale = _get_inches_to_subhex_for_analyzer()
            charge_is_fly = re.search(r'\[FLY\]', action_desc, re.IGNORECASE) is not None
            charge_budget = int(charge_roll_match.group(1)) * _scale
            if charge_is_fly:
                charge_budget = max(0, charge_budget - 2 * _scale)

            # Blockers construits SEULEMENT si le chemin sera réellement parcouru : une
            # charge volante (21.03) mesure à vol d'oiseau et les jetterait intégralement.
            if charge_is_fly:
                occupied_positions, enemy_adjacent_hexes = set(), set()
            else:
                occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
                    state.positions_by_model, state.unit_positions, state.unit_base,
                    state.unit_player, state.unit_hp, charge_unit_id,
                )
            charge_over = _per_model_move_violation(
                surviving_start_models(
                    state.positions_by_model.get(charge_unit_id),  # get allowed
                    state.current_line_models.get(charge_unit_id),  # get allowed
                ),
                state.current_line_models.get(charge_unit_id),  # get allowed
                (start_col, start_row), (dest_col, dest_row),
                charge_budget, charge_is_fly,
                state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
            )

            if charge_over:
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
        else:
            from ai.analyzer_perfig import move_start_status, _DEFAULT_BASE
            _pos_status = move_start_status(
                state.positions_by_model.get(charge_unit_id),
                state.unit_base.get(charge_unit_id, _DEFAULT_BASE),
                state.unit_positions[charge_unit_id],
                start_col, start_row,
                models_invalidated=charge_unit_id in state.models_invalidated,
            )
            if _pos_status == 'mismatch':
                stats['position_log_mismatch']['charge']['mismatch'] += 1
                if stats['first_error_lines']['position_log_mismatch']['charge'] is None:
                    stats['first_error_lines']['position_log_mismatch']['charge'] = {
                        'episode': state.current_episode_num,
                        'line': line.strip()
                    }
            elif _pos_status == 'absorbed':
                stats['position_log_mismatch']['charge']['anchor_absorbed'] += 1

        # RULE: Dead unit charging
        charge_unit_dead = charge_unit_id not in state.unit_hp or require_key(state.unit_hp, charge_unit_id) <= 0
        if charge_unit_dead:
            if died_before_phase(charge_unit_id, turn, phase, state.line_number, state.unit_deaths):
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
                positions_by_model=state.positions_by_model,
                unit_base=state.unit_base,
                **state.engagement_3d_kwargs(),  # altitudes d'AVANT la ligne (jumeau des socles de départ)
                # Socles AVANT la charge, morts exclus (cf. surviving_start_models).
                subject_models=surviving_start_models(
                    state.positions_by_model.get(charge_unit_id),  # get allowed
                    state.current_line_models.get(charge_unit_id),  # get allowed
                ),
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
            if died_before_phase(charge_target_id, turn, phase, state.line_number, state.unit_deaths):
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

            # A charge lands in engagement with the target — the charger sharing the target's
            # anchor hex is the expected outcome, not a collision. Only ally-ally same-hex
            # occupation is a genuine positioning error.
            charger_player = state.unit_player.get(charge_unit_id)
            real_colliding_units = []
            for uid, pos_before in colliding_units_before.items():
                uid_player = state.unit_player.get(uid)
                if uid_player is not None and charger_player is not None and uid_player != charger_player:
                    continue
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

        # Sample action
        if not stats['sample_actions']['charge']:
            stats['sample_actions']['charge'] = line.strip()
    else:
        # Check if it's a FAILED charge
        #
        # DEUX FORMES, une par mode d'echec de 11.02, et les deux sont journalisees depuis le
        # 2026-08-12 : le jet est insuffisant pour la cible CHOISIE (« to unit N(c,r) »), ou il
        # n'amene AUCUNE cible a portee (« - no target within reach ») — l'escouade a declare puis
        # n'a rien pu viser, il n'y a pas de cible a nommer. N'accepter que la premiere forme
        # comptait la seconde en `parse_errors`, c'est-a-dire en erreur de format, alors que c'est
        # une ligne legitime.
        failed_charge_match = re.search(
            r'Unit (\d+)\s+FAILED CHARGE'
            r'(?: to unit (\d+)\((\d+),\s*(\d+)\)| - no target within reach)',
            action_desc,
            re.IGNORECASE
        )
        if failed_charge_match:
            # JUMEAU de la branche CHARGED : un jet raté porte les mêmes bornes et le même token,
            # et c'est la MOITIÉ des jets de charge d'une partie. Ne contrôler que les charges
            # réussies laisserait la moitié du dé hors de toute vérification.
            _check_charge_roll_range(
                state, config, line, action_desc, failed_charge_match.group(1), player
            )
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
