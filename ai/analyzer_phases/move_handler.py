"""
move_handler.py — gestion des actions MOVE et FLED dans parse_step_log.
"""

import re
from typing import TYPE_CHECKING

from shared.data_validation import require_key
from ai.analyzer_rules import note_rule_usage
from ai.analyzer_phases import PHASE_ORDER

if TYPE_CHECKING:
    from ai.analyzer_state import AnalyzerState
    from ai.analyzer_config import AnalyzerConfig

_TIMESTAMP_RE = re.compile(r'\[(\d+:\d+:\d+)\]')


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


def _check_fall_back_move(state, line, action_desc, player, move_unit_id,
                          start_col, start_row, dest_col, dest_row, _position_cache_set) -> None:
    """Les trois volets de 09.07 FALL-BACK MOVE que `step.log` permet de contrôler.

    Vert vacant V10 : le fall-back était le SEUL des six déplacements sans aucun contrôle de
    budget ni de chemin — `_handle_fled` ne regardait que la collision d'ancre et le mur
    d'arrivée. Une unité pouvait donc traverser la moitié du plateau en battant en retraite sans
    que rien ne le remonte.

    « 09 Movement phase.pdf », 09.07, mot pour mot :

      MAXIMUM DISTANCE: Your unit's M characteristic.
      ELIGIBLE IF: Your unit is engaged.
      EFFECT: Your unit moves as described in Moving (03).
      AFTER MOVING: ▪ Your unit must be unengaged.

    Les trois se mesurent depuis `[MODELS:]`, et par les MÊMES primitives que move / advance /
    charge — pas une quatrième copie de la géométrie (c'est ce qui avait fait diverger les quatre
    contrôles avant leur mutualisation dans `_per_model_move_violation`).

    Ce qui n'est PAS contrôlé ici, et pourquoi :
    - le volet « WHILE MOVING ▸ Desperate Escape » (figurines ennemies traversables) reste hors
      de portée : le MODE est journalisé depuis L11 ([DESPERATE ESCAPE]/[ORDERED RETREAT]), mais
      le BFS laisse intentionnellement les ennemis traversables (cf. `force_thru_enemy` dans
      `analyzer._build_move_bfs_blockers`). Le [DESPERATE ESCAPE] est en revanche utilisé comme
      preuve d'engagement dans le volet ELIGIBLE IF (voir ci-dessous).
    - « AFTER MOVING: not eligible to shoot / declare a charge » est déjà porté par #14
      (`shoot_after_flee`) et #24 (`charge_invalid.fled`) ; le volet « start an action » exige
      les lignes d'action (16.01), absentes du journal.
    """
    from ai.analyzer import (
        _build_move_bfs_blockers,
        _per_model_move_violation,
        is_within_engine_engagement_zone,
        _get_engagement_zone_for_analyzer,
        _get_inches_to_subhex_for_analyzer,
    )
    from ai.analyzer_perfig import surviving_start_models

    if move_unit_id not in state.unit_hp or state.unit_hp[move_unit_id] <= 0:
        return

    stats = state.stats
    # Recale le cache sur la position de DÉPART du journal avant toute mesure — jumeau exact de
    # `_handle_move` (`state.unit_positions` sert de base à l'instantané ci-dessous, et le mobile
    # est déjà dans `units_moved`, donc c'est SA valeur de cache qui serait reprise).
    if move_unit_id not in state.unit_positions or state.unit_positions[move_unit_id] != (start_col, start_row):
        _position_cache_set(state.unit_positions, move_unit_id, start_col, start_row)

    if state.positions_at_move_phase_start:
        positions_at_movement = dict(state.positions_at_move_phase_start)
        for uid, pos in state.unit_positions.items():
            if uid in state.units_moved:
                positions_at_movement[uid] = pos
    else:
        positions_at_movement = dict(state.unit_positions)
    unit_hp_at_movement = dict(state.unit_hp)

    start_models = surviving_start_models(
        state.positions_by_model.get(move_unit_id),  # get allowed
        state.current_line_models.get(move_unit_id),  # get allowed
    )

    # ── ELIGIBLE IF: Your unit is engaged ──────────────────────────────────────────────────
    # Socles de DÉPART, même primitive que #3 (`move_adjacent_before_non_flee`) — dont ce
    # contrôle est le NÉGATIF : l'un punit le move normal parti d'un engagement, l'autre punit
    # le fall-back parti sans engagement. Les deux doivent donc mesurer la même grandeur.
    positions_before = {
        uid: pos for uid, pos in positions_at_movement.items()
        if unit_hp_at_movement.get(uid, 0) > 0  # get allowed : unité absente = pas d'obstacle
    }
    engaged_before = is_within_engine_engagement_zone(
        move_unit_id, state.unit_player, positions_before, unit_hp_at_movement,
        engagement_zone=_get_engagement_zone_for_analyzer(),
        position_override=(start_col, start_row),
        positions_by_model=state.positions_by_model, unit_base=state.unit_base,
        **state.engagement_3d_kwargs(),
        subject_models=start_models,
    )
    if not engaged_before and start_models:
        # Per-model positions may be stale: the surviving model was at the squad's rear when
        # frontline models were killed by enemy fire. Their last logged position is no longer
        # representative of the squad's engagement state. Retry on the anchor — if the anchor
        # says engaged, trust it over the stale per-model data.
        engaged_before = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, positions_before, unit_hp_at_movement,
            engagement_zone=_get_engagement_zone_for_analyzer(),
            position_override=(start_col, start_row),
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            **state.engagement_3d_kwargs(),
            subject_models=None,
        )
    if not engaged_before and '[DESPERATE ESCAPE]' in line:
        # The engine only emits [DESPERATE ESCAPE] when it enforces desperate-escape rolls
        # (09.07 + 06.03), which are themselves gated on the unit being engaged. If the
        # geometric reconstruction misses the engaging enemy (stale position, height
        # mismatch, enemy moved within the same turn), the tag is the authoritative proof.
        engaged_before = True
    if not engaged_before:
        stats['flee_from_unengaged'][player] += 1
        if stats['first_error_lines']['flee_from_unengaged'][player] is None:
            stats['first_error_lines']['flee_from_unengaged'][player] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }

    # ── AFTER MOVING: Your unit must be unengaged ──────────────────────────────────────────
    # Socles et hauteurs d'ARRIVÉE (le `[MODELS:]` de CETTE ligne) : mesurer une arrivée à
    # l'altitude du départ inverse le gate vertical de 03.04.
    positions_after = dict(positions_before)
    positions_after[move_unit_id] = (dest_col, dest_row)
    engaged_after = is_within_engine_engagement_zone(
        move_unit_id, state.unit_player, positions_after, unit_hp_at_movement,
        engagement_zone=_get_engagement_zone_for_analyzer(),
        position_override=(dest_col, dest_row),
        positions_by_model=state.positions_by_model, unit_base=state.unit_base,
        **state.engagement_3d_kwargs(),
        subject_models=state.current_line_models.get(move_unit_id),  # get allowed
        subject_heights=state.current_line_heights.get(move_unit_id),  # get allowed
    )
    if engaged_after:
        stats['flee_still_engaged'][player] += 1
        if stats['first_error_lines']['flee_still_engaged'][player] is None:
            stats['first_error_lines']['flee_still_engaged'][player] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }

    # ── MAXIMUM DISTANCE: M + chemin de 03 Moving ──────────────────────────────────────────
    # Aucune garde « la position a-t-elle changé ? » : `_per_model_move_violation` ne mesure que
    # les socles qui ont BOUGÉ, donc un fall-back immobile n'y coûte aucun BFS. Une garde à
    # l'ancre aurait au contraire fait sauter le contrôle sur les reformations, où l'ancre ne
    # bouge pas alors que les figurines, elles, se déplacent.
    # 21.03 : le vol est DÉCLARÉ, pas acquis par le keyword — même lecture que move et charge,
    # et la ligne `FLED [FLY]` porte bien le marqueur.
    flee_is_fly = re.search(r'FLED\s+\[FLY\]\s+from', action_desc, re.IGNORECASE) is not None
    flee_range = int(require_key(state.unit_move, move_unit_id))
    if flee_is_fly:
        flee_range = max(0, flee_range - 2 * _get_inches_to_subhex_for_analyzer())
    occupied_positions, enemy_adjacent_hexes = _build_move_bfs_blockers(
        state.positions_by_model, positions_at_movement, state.unit_base,
        state.unit_player, unit_hp_at_movement, move_unit_id,
        force_thru_enemy=True,
    )
    # 09.07 JUGÉE : les trois volets (éligibilité, budget, post-condition) ont été mesurés sur
    # cette ligne, les deux premiers au-dessus.
    note_rule_usage(stats, "09.07", player)
    if _per_model_move_violation(
        start_models,
        state.current_line_models.get(move_unit_id),  # get allowed
        (start_col, start_row), (dest_col, dest_row),
        flee_range, flee_is_fly,
        state.wall_hexes, occupied_positions, enemy_adjacent_hexes,
    ):
        stats['move_distance_over_limit']['flee'][player] += 1
        if stats['first_error_lines']['move_distance_over_limit']['flee'][player] is None:
            stats['first_error_lines']['move_distance_over_limit']['flee'][player] = {
                'episode': state.current_episode_num, 'line': line.strip()
            }


def _handle_fled(state, config, line, action_desc, player, turn, phase, fled_match,
                 _track_action_phase_accuracy, _position_cache_set, _debug_log, _get_unit_hp_value):
    stats = state.stats
    move_unit_id = fled_match.group(1)
    start_col = int(fled_match.group(4))
    start_row = int(fled_match.group(5))
    dest_col = int(fled_match.group(6))
    dest_row = int(fled_match.group(7))

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

    # Mutation différée après le guard : une unité absente de unit_hp ne doit pas être
    # enregistrée comme déplacée (sa position stale resterait dans units_moved et
    # contaminerait positions_at_movement comme bloqueur BFS fantôme).
    state.units_moved.add(move_unit_id)
    state.units_fled.add(move_unit_id)
    unit_hp_value = require_key(state.unit_hp, move_unit_id)
    _debug_log(f"[FLED DEBUG] BEFORE update: unit_hp[{move_unit_id}] = {unit_hp_value}")
    if unit_hp_value > 0:
        # Guard mort par state_resync : is_within_engine_engagement_zone retourne False pour
        # subject_hp<=0, donc engaged_before=False → flee_from_unengaged faux positif sans guard.
        _check_fall_back_move(state, line, action_desc, player, move_unit_id,
                              start_col, start_row, dest_col, dest_row, _position_cache_set)
        old_position = state.unit_positions.get(move_unit_id)
        _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)
        _debug_log(f"[FLED DEBUG] AFTER update: unit_positions[{move_unit_id}] = {state.unit_positions[move_unit_id]} (was {old_position})")
        # Ancre mise à jour sans segment [MODELS:] (les lignes FLED n'en portent pas) : les
        # socles restent à l'ancienne position dans positions_by_model → faux positifs
        # shoot_at_engaged_enemy quand le moteur tire sur une cible que cette unité n'engage
        # plus. On purge pour forcer le retour à l'ancre dans les contrôles suivants.
        if (start_col, start_row) != (dest_col, dest_row):
            state.positions_by_model.pop(move_unit_id, None)

        # Historique et collision gardés dans le bloc hp>0 : une unité morte n'ayant jamais
        # atteint dest, enregistrer sa destination provoquerait des faux positifs de collision
        # (unit_movement_history et unit_position_collisions incluraient move_unit_id à dest).
        if move_unit_id not in state.unit_movement_history:
            state.unit_movement_history[move_unit_id] = []
        timestamp_match = _TIMESTAMP_RE.search(line)
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

            mover_player = state.unit_player.get(move_unit_id)
            real_colliding_units = []
            for uid in colliding_units:
                uid_player = state.unit_player.get(uid)
                if uid_player is not None and mover_player is not None and uid_player != mover_player:
                    continue
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
            # 03.01 JUGÉE ici aussi : `wall_collisions` a TROIS sites d'incrément (move normal,
            # fall-back, advance) et n'en notait qu'un. La règle sortait donc « jamais exercée » sur
            # un journal de fall-back, alors que son contrôle avait travaillé — une fausse alerte sur
            # le seul verdict que ce chantier a créé.
            note_rule_usage(stats, "03.01", player)
            if (dest_col, dest_row) in state.wall_hexes:
                stats['wall_collisions'][player] += 1
        # start==dest : _position_cache_set(dest) déjà appelé en tête du bloc hp>0.
    else:
        _debug_log(f"[FLED DEBUG] SKIPPED update: unit_hp[{move_unit_id}] = {unit_hp_value} (<= 0)")

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
    from ai.analyzer import (
        _get_inches_to_subhex_for_analyzer,
        engine_engagement_zone_offenders,
        monster_or_vehicle_by_unit,
    )

    stats = state.stats
    move_unit_id = move_match.group(1)
    start_col = int(move_match.group(4))
    start_row = int(move_match.group(5))
    dest_col = int(move_match.group(6))
    dest_row = int(move_match.group(7))
    is_move_after_shooting = (
        re.search(r'MOVED AFTER SHOOTING', action_desc, re.IGNORECASE) is not None
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
        current_phase_order = require_key(PHASE_ORDER, phase)
        for death_turn, death_phase, dead_unit_id, death_line_num in state.unit_deaths:
            if dead_unit_id == move_unit_id:
                if death_turn < turn:
                    unit_died_before_move = True
                    break
                if death_turn == turn:
                    death_phase_order = require_key(PHASE_ORDER, death_phase)
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

    if move_unit_id not in state.unit_hp:
        stats['parse_errors'].append({
            'episode': state.current_episode_num,
            'turn': turn,
            'phase': phase,
            'line': line.strip(),
            'error': f"Move action for unknown unit_id (missing in unit_hp): {move_unit_id}"
        })
        return True  # equivalent to continue
    state.units_moved.add(move_unit_id)

    # Sync position cache with log start position
    if move_unit_id not in state.unit_positions or state.unit_positions[move_unit_id] != (start_col, start_row):
        _position_cache_set(state.unit_positions, move_unit_id, start_col, start_row)

    if move_unit_id not in state.positions_at_move_phase_start:
        state.positions_at_move_phase_start[move_unit_id] = (start_col, start_row)
        for uid, pos in state.unit_positions.items():
            if uid not in state.positions_at_move_phase_start:
                state.positions_at_move_phase_start[uid] = pos

    if (start_col, start_row) != (dest_col, dest_row):
        if move_unit_id not in state.unit_movement_history:
            state.unit_movement_history[move_unit_id] = []
        timestamp_match = _TIMESTAMP_RE.search(line)
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
            move_range = int(require_key(state.unit_move, move_unit_id))
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
            # 17.01 : le mouvement NORMAL est l'un des deux déplacements que l'exemption M/V
            # couvre (l'autre est l'advance). Le fall-back ci-dessus ne la reçoit pas.
            monster_or_vehicle_by_unit=monster_or_vehicle_by_unit(config, state, move_unit_id),
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
        if is_move_after_shooting:
            # Capacité de projet `move_after_shooting` JUGÉE : le budget de la capacité vient
            # d'être mesuré. Le move NORMAL de cette même branche est compté plus bas, sur 09.05.
            note_rule_usage(stats, "PROJET.move_after_shooting", player)
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

        if require_key(state.unit_hp, move_unit_id) > 0:
            _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)
            # Ancre mise à jour sans [MODELS:] (les lignes MOVED n'en portent pas) : purge pour
            # forcer l'ancre dans les contrôles d'engagement suivants et éviter les faux
            # positifs shoot_at_engaged_enemy sur des unités qui se sont éloignées de la cible.
            state.positions_by_model.pop(move_unit_id, None)

        # Deux ennemis qui se déplacent vers le même hexe par un move ordinaire = chevauchement
        # d'ancre attendu en engagement (les socles réels sont distincts). En revanche, un ennemi
        # qui ARRIVE des réserves (ingress, action='ingress') sur un hexe qu'une autre unité vient
        # occuper la même activation est une vraie collision : l'arrivée depuis (-1,-1) ne crée
        # aucune zone d'engagement préalable. Le test `action == 'ingress'` dans `has_ingress_to_dest`
        # distingue les deux cas sans supprimer le filtre ennemi global.
        mover_player = state.unit_player.get(move_unit_id)
        real_colliding_units = []
        for uid, pos_before in colliding_units_before.items():
            uid_player = state.unit_player.get(uid)
            is_enemy = (uid_player is not None and mover_player is not None
                        and uid_player != mover_player)
            if (uid in state.unit_positions and
                    state.unit_positions[uid] == (dest_col, dest_row) and
                    state.unit_positions[uid] == pos_before and
                    uid in state.unit_hp and
                    require_key(state.unit_hp, uid) > 0):
                if uid in state.unit_movement_history:
                    if is_enemy:
                        has_ingress_to_dest = any(
                            move['position'] == (dest_col, dest_row)
                            and move.get('turn') == turn
                            and move.get('episode') is not None
                            and move.get('episode') == state.current_episode_num
                            and move.get('action') == 'ingress'
                            for move in state.unit_movement_history[uid]
                        )
                        if has_ingress_to_dest:
                            real_colliding_units.append(uid)
                    else:
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
            **state.engagement_3d_kwargs(),
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

        _debug_log(f"[ANALYZER DEBUG] E{state.current_episode_num} T{turn} MOVE: Unit {move_unit_id} checking adjacency at ({dest_col},{dest_row}) against {len(positions_for_adjacency_check_filtered)} units")
        dest_adjacent = is_within_engine_engagement_zone(
            move_unit_id, state.unit_player, positions_for_adjacency_check_filtered, unit_hp_at_movement,
            engagement_zone=_get_engagement_zone_for_analyzer(), position_override=(dest_col, dest_row),
            positions_by_model=state.positions_by_model, unit_base=state.unit_base,
            **state.engagement_3d_kwargs(),
            # Socles d'ARRIVÉE : le `[MODELS:]` de CETTE ligne, pas l'état d'avant. Les hauteurs
            # suivent la même ligne — mesurer une arrivée à l'altitude du départ inverse le gate.
            subject_models=state.current_line_models.get(move_unit_id),  # get allowed
            subject_heights=state.current_line_heights.get(move_unit_id),  # get allowed
        )
        # 09.05 vient d'être JUGÉE sur cette ligne : le budget, l'engagement de départ et celui
        # d'arrivée ont tous trois été mesurés au-dessus. Le compteur est posé ICI et pas à
        # l'entrée du handler — un mouvement dont la géométrie n'aurait pas pu être mesurée ne
        # doit pas compter pour un exercice de la règle, sans quoi « jamais exercée » ne se
        # déclencherait plus jamais.
        #
        # ET PAS SUR UN MOVE APRÈS TIR : celui-ci emprunte le même chemin, mais son budget est
        # celui de la CAPACITÉ, compté sur `PROJET.move_after_shooting`. Sans cette garde, un run
        # dont tous les déplacements seraient des move-après-tir déclarait 09.05 « exercée » alors
        # que son volet MAXIMUM DISTANCE n'avait jamais été jugé.
        if not is_move_after_shooting:
            note_rule_usage(stats, "09.05", player)
        if dest_adjacent:
            if not adjacent_before:
                stats['move_to_adjacent_enemy'][player] += 1
                if stats['first_error_lines']['move_to_adjacent_enemy'][player] is None:
                    # MÊME mesure que le compteur juste au-dessus, avec les MÊMES arguments —
                    # sinon le diagnostic décrit une autre situation que celle qui a déclenché.
                    # `get_adjacent_enemies` (adjacence d'ANCRE, distance hex 1) vivait ici : à ×5
                    # il ne rendait jamais rien, d'où le « Adjacent after move: none » imprimé sous
                    # une erreur bien réelle.
                    adjacent_after = engine_engagement_zone_offenders(
                        move_unit_id, state.unit_player, positions_for_adjacency_check_filtered,
                        unit_hp_at_movement,
                        engagement_zone=_get_engagement_zone_for_analyzer(),
                        position_override=(dest_col, dest_row),
                        positions_by_model=state.positions_by_model, unit_base=state.unit_base,
                        **state.engagement_3d_kwargs(),
                        subject_models=state.current_line_models.get(move_unit_id),  # get allowed
                        subject_heights=state.current_line_heights.get(move_unit_id),  # get allowed
                    )
                    stats['first_error_lines']['move_to_adjacent_enemy'][player] = {
                        'episode': state.current_episode_num,
                        'line': line.strip(),
                        # `adjacent_before` n'est PAS stocké : cette branche est gardée par
                        # `not adjacent_before`, donc la liste serait vide par construction. La
                        # clé portait le BOOLÉEN du compteur là où le rapport itérait une liste —
                        # un TypeError latent, protégé seulement par cette garde.
                        'adjacent_after': adjacent_after,
                    }

        # 03.01 : la destination vient d'être confrontée aux murs. Le reste de la règle — chemin
        # réel, figurines, bord du plateau — est jugé dans le contrôle de budget ci-dessus, qui
        # rend un verdict unique ; c'est dit dans l'entrée de corpus (`co_verified_by`).
        note_rule_usage(stats, "03.01", player)
        # RULE: Move into wall
        if (dest_col, dest_row) in state.wall_hexes:
            stats['wall_collisions'][player] += 1
    else:
        if require_key(state.unit_hp, move_unit_id) > 0:
            _position_cache_set(state.unit_positions, move_unit_id, dest_col, dest_row)

    if not stats['sample_actions']['move']:
        stats['sample_actions']['move'] = line.strip()
    return False
