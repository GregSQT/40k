"""Le format de save suit les clés obligatoires du reset d'épisode (verrou anti-oubli).

CE QUE CE FICHIER VERROUILLE. Une save ne stocke que le MUTABLE du game_state : le décor et la
config sont ré-attachés depuis le moteur vivant au chargement (`game_snapshots._GS_STATIC_KEYS`).
Quand le reset d'épisode publie une nouvelle clé obligatoire, les saves écrites avant ne la
contiennent pas, et `apply_live_state` écrase la partie en cours AVANT que le premier lecteur de
la clé ne lève, très loin du chargement.

La parade du projet est le bump de magic avec refus explicite des formats antérieurs
(`game_saves._MAGIC`, `_reject_legacy`) — c'est ce qui a été fait pour `command_points` en TL03.
Ce geste est manuel : il a été oublié pour les NEUF clés ajoutées au reset entre TL03 (2026-08-04)
et le 2026-08-31 (réserves stratégiques, ingress, suppression, `secured_objectives`).

Ce test rend l'oubli BRUYANT : il épingle l'ensemble des clés mutables posées par un reset, par
magic. Ajouter une clé au reset sans bumper la magic le fait passer au ROUGE.

PORTÉE — ce que ce verrou NE couvre PAS, mesuré : il ne voit que les clés posées par le RESET.
Le moteur écrit 162 clés distinctes dans le game_state, dont beaucoup naissent paresseusement en
cours de partie ; une clé obligatoire créée hors reset lui échapperait. Il ne voit pas non plus
une clé dont la FORME change à contenu de nom constant. Les neuf clés de la dérive observée sont
toutes dans le périmètre couvert.

Corollaire pour l'auteur d'un changement : quand ce test devient rouge par une clé AJOUTÉE, la
correction est d'ajouter une entrée sous une NOUVELLE magic et de bumper `_MAGIC` — pas d'élargir
l'entrée existante, qui décrit un format déjà écrit sur le disque des joueurs.

⚠️ UNE CLÉ RETIRÉE NE SE CORRIGE PAS PAREIL, et ce test l'a fait croire une fois : la fermeture
des intentions de zone (2026-09-09) a bumpé le format sur la foi du message d'échec ci-dessous, rendant
illisibles les parties enregistrées pour rien, avant d'être annulée le même jour. Le danger que la
magic écarte est un état AMPUTÉ, pas un état qui porte une clé de trop. Le critère est dans
`services/game_saves._MAGIC` : si plus AUCUN lecteur ne consulte la clé, la laisser publiée par le
reset, inerte, coûte moins que le refus. Si un lecteur subsiste — clé créée paresseusement et lue
en cours de partie — la row la réinjecterait avec une valeur périmée : bump. La clé devenue
STATIQUE faisait un troisième cas jusqu'au 2026-09-09 ; elle n'en fait plus un, `rebuild_game_state`
laissant désormais le live gagner (tests/unit/services/test_game_snapshots_static_keys.py).

Cet interdit était une CONSIGNE et il est désormais un CONTRÔLE : `_FROZEN_FINGERPRINTS` épingle
le compte et l'empreinte de chaque entrée qui n'est plus la magic courante. Écrire les entrées en
littéral, sans objet partagé, empêche qu'une clé déposée dans l'entrée figée remonte dans la
courante ; l'empreinte, elle, refuse en plus que cette réécriture passe INAPERÇUE — la
comparaison au reset ne lit que l'entrée courante et ne verra jamais rien de l'autre.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, FrozenSet, Iterable, Tuple

import pytest

from services.game_saves import _MAGIC
from services.game_snapshots import _GS_STATIC_KEYS

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
#: Même scénario que `test_game_snapshots_static_keys` : déploiement ACTIF, donc le reset publie
#: aussi les clés de déploiement et de réserves stratégiques.
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent_x1/scenarios/holdout_regular/scenario_bot-01.json"
)

#: Clés mutables publiées par le reset, PAR FORMAT DE SAVE. Une entrée décrit un format figé sur
#: le disque des joueurs : elle ne s'élargit jamais après coup, on en ajoute une nouvelle.
#: Les deux entrées sont écrites en LITTÉRAL et ne partagent aucun objet — une entrée dérivée
#: de la précédente aurait fait remonter dans l'entrée courante toute clé glissée dans une entrée
#: figée.
#: TL05 = TL04 + le couple de déclaration de montée 13.06 (`ascent_declaration_reset_state`,
#: `engine/phase_handlers/movement_handlers.py`) et le mémo de charge, tous trois posés par le
#: dict de reset de `W40KEngine.reset`.
#: ⚠️ LE PREMIER TL06 N'A JAMAIS EXISTÉ : la fermeture des intentions de zone (2026-09-09) a
#: d'abord bumpé le format parce que cinq clés quittaient le reset, et le bump a été ANNULÉ le
#: même jour — les cinq clés sont restées publiées, et elles sont toujours dans TL05 ci-dessus.
#: La raison est dans `services/game_saves._MAGIC` : le refus protège d'un état AMPUTÉ, pas d'un
#: état qui porte une clé de trop. Le TL06 du 2026-09-10 est un autre bump, motivé par un AJOUT
#: (étape 20.01), et il a d'abord REPRIS le numéro annulé — un fichier écrit entre 20:58 et 22:40
#: le 2026-09-09 porte pourtant bien cet en-tête sur un état sans les clés 20.01. C'est ce qui a
#: coûté le bump suivant : TL07 brûle le numéro ambigu et TL06 part en legacy. UN NUMÉRO ÉMIS NE
#: SE REPREND PAS, même annulé le jour même.
_TL04_KEYS: FrozenSet[str] = frozenset({
        '_best_weapon_cache', '_charge_declaration_current', '_charge_initial_rolls',
        '_charge_plan_cache', '_deployment_scoring_cache', '_deployment_slot_candidates',
        '_edge_distance_cache', '_entity_types_cache', '_grid_deployment_zone_anchor',
        '_grid_static_hex_arrays', '_ingress_arrived', '_ingress_no_destination', '_ingress_offered',
        '_objective_control_last_boundary', '_objective_hex_zones_cache', '_obs_objective_hex_arrays',
        '_obs_weapon_profiles_cache', '_obscuring_area_sets_cache', '_pending_reserves_wasted',
        '_pending_zone_shaping', '_pile_in_toCol', '_pile_in_toRow', '_reserves_deployed',
        '_reserves_destroyed_turn3', '_reserves_placed', '_restored_model_counter',
        '_shoot_pass_cache', '_socle_wall_blocked_cache', '_squad_move_pool_cache',
        '_unit_move_version', '_wall_set_cache', '_zone_intent_declarations', 'action_log_seq',
        'action_logs', 'active_movement_unit', 'active_rule_choice_prompt', 'advance_rolls',
        'charge_activation_pool', 'charge_range_rolls', 'choice_timing_index',
        'command_activation_pool', 'command_points', 'console_logs',
        'controlled_objective_samples_scoring_turns', 'current_player', 'debug_mode',
        'deployment_mode_schedule_mode', 'deployment_state', 'deployment_type',
        'deployment_type_by_player', 'deployment_zone', 'destroyed_models',
        'enemy_adjacent_counts_player_1', 'enemy_adjacent_counts_player_2',
        'enemy_adjacent_hexes_player_1', 'enemy_adjacent_hexes_player_2', 'enemy_slot_mapping_p1',
        'episode_number', 'episode_steps', 'fight_subphase', 'game_over', 'gym_distance_metric',
        'gym_training_mode', 'last_move_cause', 'last_move_event_id', 'log_delta',
        'macro_target_objective_id', 'macro_target_objective_index', 'model_count_at_start_by_player',
        'models_cache', 'move_activation_pool', 'move_preview_footprint_span',
        'moved_distance_by_model', 'oath_target', 'objective_controllers', 'occupation_map',
        'opponent_objective_samples_scoring_turns', 'pending_agent_decision',
        'pending_oath_selection', 'pending_rule_choice_queue', 'pending_shooting_phase_init',
        'pending_squad_fight_intents', 'pending_squad_shoot_intents', 'phase', 'player_names',
        'player_types', 'points_limit', 'preview_hexes', 'reaction_window_active',
        'reactive_decision_mode', 'reactive_decision_payload', 'reactive_macro_order_current_window',
        'reactive_mode', 'secured_objectives', 'shoot_activation_pool', 'squad_cache', 'squad_models',
        'suppressed_squads', 'training_config_name', 'turn', 'turn_limit_reached',
        'unit_activation_count', 'unit_by_id', 'unit_zone_assignments', 'units', 'units_advanced',
        'units_cache', 'units_cache_prev', 'units_cannot_charge', 'units_charged', 'units_fled',
        'units_fly_declaration_resolved', 'units_fly_declaration_resolved_charge', 'units_moved',
        'units_reacted_this_enemy_turn', 'units_shot', 'units_shot_previous_turn',
        'units_took_to_skies', 'units_took_to_skies_charge', 'unlimited_turns',
        'valid_move_destinations_pool', 'value_at_start', 'victory_points', 'waaagh_active',
        'waaagh_called', 'winner', 'zone_intent_free_steps_remaining', 'zone_intents',
})

_TL05_KEYS: FrozenSet[str] = frozenset({
        '_best_weapon_cache', '_charge_declaration_current', '_charge_engage_memo',
        '_charge_initial_rolls', '_charge_plan_cache', '_deployment_scoring_cache',
        '_deployment_slot_candidates', '_edge_distance_cache', '_entity_types_cache',
        '_grid_deployment_zone_anchor', '_grid_static_hex_arrays', '_ingress_arrived',
        '_ingress_no_destination', '_ingress_offered', '_objective_control_last_boundary',
        '_objective_hex_zones_cache', '_obs_objective_hex_arrays', '_obs_weapon_profiles_cache',
        '_obscuring_area_sets_cache', '_pending_reserves_wasted', '_pending_zone_shaping',
        '_pile_in_toCol', '_pile_in_toRow', '_reserves_deployed', '_reserves_destroyed_turn3',
        '_reserves_placed', '_restored_model_counter', '_shoot_pass_cache',
        '_socle_wall_blocked_cache', '_squad_move_pool_cache', '_unit_move_version',
        '_wall_set_cache', '_zone_intent_declarations', 'action_log_seq', 'action_logs',
        'active_movement_unit', 'active_rule_choice_prompt', 'advance_rolls',
        'charge_activation_pool', 'charge_range_rolls', 'choice_timing_index',
        'command_activation_pool', 'command_points', 'console_logs',
        'controlled_objective_samples_scoring_turns', 'current_player', 'debug_mode',
        'deployment_mode_schedule_mode', 'deployment_state', 'deployment_type',
        'deployment_type_by_player', 'deployment_zone', 'destroyed_models',
        'enemy_adjacent_counts_player_1', 'enemy_adjacent_counts_player_2',
        'enemy_adjacent_hexes_player_1', 'enemy_adjacent_hexes_player_2', 'enemy_slot_mapping_p1',
        'episode_number', 'episode_steps', 'fight_subphase', 'game_over', 'gym_distance_metric',
        'gym_training_mode', 'last_move_cause', 'last_move_event_id', 'log_delta',
        'macro_target_objective_id', 'macro_target_objective_index', 'model_count_at_start_by_player',
        'models_cache', 'move_activation_pool', 'move_preview_footprint_span',
        'moved_distance_by_model', 'oath_target', 'objective_controllers', 'occupation_map',
        'opponent_objective_samples_scoring_turns', 'pending_agent_decision',
        'pending_oath_selection', 'pending_rule_choice_queue', 'pending_shooting_phase_init',
        'pending_squad_fight_intents', 'pending_squad_shoot_intents', 'phase', 'player_names',
        'player_types', 'points_limit', 'preview_hexes', 'reaction_window_active',
        'reactive_decision_mode', 'reactive_decision_payload', 'reactive_macro_order_current_window',
        'reactive_mode', 'secured_objectives', 'shoot_activation_pool', 'squad_cache', 'squad_models',
        'suppressed_squads', 'training_config_name', 'turn', 'turn_limit_reached',
        'unit_activation_count', 'unit_by_id', 'unit_zone_assignments', 'units', 'units_advanced',
        'units_ascent_declaration_resolved', 'units_cache', 'units_cache_prev',
        'units_cannot_charge', 'units_charged', 'units_declared_ascent', 'units_fled',
        'units_fly_declaration_resolved', 'units_fly_declaration_resolved_charge', 'units_moved',
        'units_reacted_this_enemy_turn', 'units_shot', 'units_shot_previous_turn',
        'units_took_to_skies', 'units_took_to_skies_charge', 'unlimited_turns',
        'valid_move_destinations_pool', 'value_at_start', 'victory_points', 'waaagh_active',
        'waaagh_called', 'winner', 'zone_intent_free_steps_remaining', 'zone_intents',
})

#: TL06 = TL05 pour les clés de PREMIER NIVEAU : le bump du 2026-09-10 est motivé par deux
#: clés que ce verrou NE VOIT PAS — `reserves_declaration_queue` et
#: `reserves_declaration_closed`, posées par le reset DANS `deployment_state`, donc au
#: deuxième niveau, sous une clé mutable déjà déclarée ici. L'entrée est malgré tout écrite,
#: en littéral et non dérivée : `test_the_current_magic_declares_its_key_set` l'exigeait tant que
#: TL06 était la magic courante — depuis TL07 elle est FIGÉE et gardée par `_FROZEN_FINGERPRINTS`
#: —, et une entrée dérivée de TL05 ferait remonter dans l'entrée courante toute clé glissée dans
#: un format figé. Trois entrées identiques ne sont donc pas un doublon accidentel — c'est la
#: mesure que la dérive s'est produite hors de la portée du verrou.
_TL06_KEYS: FrozenSet[str] = frozenset({
        '_best_weapon_cache', '_charge_declaration_current', '_charge_engage_memo',
        '_charge_initial_rolls', '_charge_plan_cache', '_deployment_scoring_cache',
        '_deployment_slot_candidates', '_edge_distance_cache', '_entity_types_cache',
        '_grid_deployment_zone_anchor', '_grid_static_hex_arrays', '_ingress_arrived',
        '_ingress_no_destination', '_ingress_offered', '_objective_control_last_boundary',
        '_objective_hex_zones_cache', '_obs_objective_hex_arrays', '_obs_weapon_profiles_cache',
        '_obscuring_area_sets_cache', '_pending_reserves_wasted', '_pending_zone_shaping',
        '_pile_in_toCol', '_pile_in_toRow', '_reserves_deployed', '_reserves_destroyed_turn3',
        '_reserves_placed', '_restored_model_counter', '_shoot_pass_cache',
        '_socle_wall_blocked_cache', '_squad_move_pool_cache', '_unit_move_version',
        '_wall_set_cache', '_zone_intent_declarations', 'action_log_seq', 'action_logs',
        'active_movement_unit', 'active_rule_choice_prompt', 'advance_rolls',
        'charge_activation_pool', 'charge_range_rolls', 'choice_timing_index',
        'command_activation_pool', 'command_points', 'console_logs',
        'controlled_objective_samples_scoring_turns', 'current_player', 'debug_mode',
        'deployment_mode_schedule_mode', 'deployment_state', 'deployment_type',
        'deployment_type_by_player', 'deployment_zone', 'destroyed_models',
        'enemy_adjacent_counts_player_1', 'enemy_adjacent_counts_player_2',
        'enemy_adjacent_hexes_player_1', 'enemy_adjacent_hexes_player_2', 'enemy_slot_mapping_p1',
        'episode_number', 'episode_steps', 'fight_subphase', 'game_over', 'gym_distance_metric',
        'gym_training_mode', 'last_move_cause', 'last_move_event_id', 'log_delta',
        'macro_target_objective_id', 'macro_target_objective_index', 'model_count_at_start_by_player',
        'models_cache', 'move_activation_pool', 'move_preview_footprint_span',
        'moved_distance_by_model', 'oath_target', 'objective_controllers', 'occupation_map',
        'opponent_objective_samples_scoring_turns', 'pending_agent_decision',
        'pending_oath_selection', 'pending_rule_choice_queue', 'pending_shooting_phase_init',
        'pending_squad_fight_intents', 'pending_squad_shoot_intents', 'phase', 'player_names',
        'player_types', 'points_limit', 'preview_hexes', 'reaction_window_active',
        'reactive_decision_mode', 'reactive_decision_payload', 'reactive_macro_order_current_window',
        'reactive_mode', 'secured_objectives', 'shoot_activation_pool', 'squad_cache', 'squad_models',
        'suppressed_squads', 'training_config_name', 'turn', 'turn_limit_reached',
        'unit_activation_count', 'unit_by_id', 'unit_zone_assignments', 'units', 'units_advanced',
        'units_ascent_declaration_resolved', 'units_cache', 'units_cache_prev',
        'units_cannot_charge', 'units_charged', 'units_declared_ascent', 'units_fled',
        'units_fly_declaration_resolved', 'units_fly_declaration_resolved_charge', 'units_moved',
        'units_reacted_this_enemy_turn', 'units_shot', 'units_shot_previous_turn',
        'units_took_to_skies', 'units_took_to_skies_charge', 'unlimited_turns',
        'valid_move_destinations_pool', 'value_at_start', 'victory_points', 'waaagh_active',
        'waaagh_called', 'winner', 'zone_intent_free_steps_remaining', 'zone_intents',
})

#: TL07 = TL06 à la clé près : ce bump ne corrige aucun jeu de clés, il retire au format
#: courant un numéro AMBIGU (`W40KTL06` a désigné deux formats — cf. `game_saves._MAGIC`).
#: L'entrée est réécrite en littéral comme les précédentes, jamais dérivée : un alias ferait
#: muter l'entrée figée TL06 en même temps que la courante au prochain ajout de clé.
_TL07_KEYS: FrozenSet[str] = frozenset({
        '_best_weapon_cache', '_charge_declaration_current', '_charge_engage_memo',
        '_charge_initial_rolls', '_charge_plan_cache', '_deployment_scoring_cache',
        '_deployment_slot_candidates', '_edge_distance_cache', '_entity_types_cache',
        '_grid_deployment_zone_anchor', '_grid_static_hex_arrays', '_ingress_arrived',
        '_ingress_no_destination', '_ingress_offered', '_objective_control_last_boundary',
        '_objective_hex_zones_cache', '_obs_objective_hex_arrays', '_obs_weapon_profiles_cache',
        '_obscuring_area_sets_cache', '_pending_reserves_wasted', '_pending_zone_shaping',
        '_pile_in_toCol', '_pile_in_toRow', '_reserves_deployed', '_reserves_destroyed_turn3',
        '_reserves_placed', '_restored_model_counter', '_shoot_pass_cache',
        '_socle_wall_blocked_cache', '_squad_move_pool_cache', '_unit_move_version',
        '_wall_set_cache', '_zone_intent_declarations', 'action_log_seq', 'action_logs',
        'active_movement_unit', 'active_rule_choice_prompt', 'advance_rolls',
        'charge_activation_pool', 'charge_range_rolls', 'choice_timing_index',
        'command_activation_pool', 'command_points', 'console_logs',
        'controlled_objective_samples_scoring_turns', 'current_player', 'debug_mode',
        'deployment_mode_schedule_mode', 'deployment_state', 'deployment_type',
        'deployment_type_by_player', 'deployment_zone', 'destroyed_models',
        'enemy_adjacent_counts_player_1', 'enemy_adjacent_counts_player_2',
        'enemy_adjacent_hexes_player_1', 'enemy_adjacent_hexes_player_2', 'enemy_slot_mapping_p1',
        'episode_number', 'episode_steps', 'fight_subphase', 'game_over', 'gym_distance_metric',
        'gym_training_mode', 'last_move_cause', 'last_move_event_id', 'log_delta',
        'macro_target_objective_id', 'macro_target_objective_index', 'model_count_at_start_by_player',
        'models_cache', 'move_activation_pool', 'move_preview_footprint_span',
        'moved_distance_by_model', 'oath_target', 'objective_controllers', 'occupation_map',
        'opponent_objective_samples_scoring_turns', 'pending_agent_decision',
        'pending_oath_selection', 'pending_rule_choice_queue', 'pending_shooting_phase_init',
        'pending_squad_fight_intents', 'pending_squad_shoot_intents', 'phase', 'player_names',
        'player_types', 'points_limit', 'preview_hexes', 'reaction_window_active',
        'reactive_decision_mode', 'reactive_decision_payload', 'reactive_macro_order_current_window',
        'reactive_mode', 'secured_objectives', 'shoot_activation_pool', 'squad_cache', 'squad_models',
        'suppressed_squads', 'training_config_name', 'turn', 'turn_limit_reached',
        'unit_activation_count', 'unit_by_id', 'unit_zone_assignments', 'units', 'units_advanced',
        'units_ascent_declaration_resolved', 'units_cache', 'units_cache_prev',
        'units_cannot_charge', 'units_charged', 'units_declared_ascent', 'units_fled',
        'units_fly_declaration_resolved', 'units_fly_declaration_resolved_charge', 'units_moved',
        'units_reacted_this_enemy_turn', 'units_shot', 'units_shot_previous_turn',
        'units_took_to_skies', 'units_took_to_skies_charge', 'unlimited_turns',
        'valid_move_destinations_pool', 'value_at_start', 'victory_points', 'waaagh_active',
        'waaagh_called', 'winner', 'zone_intent_free_steps_remaining', 'zone_intents',
})

MUTABLE_KEYS_BY_MAGIC: Dict[bytes, FrozenSet[str]] = {
    b"W40KTL04": _TL04_KEYS,
    b"W40KTL05": _TL05_KEYS,
    b"W40KTL06": _TL06_KEYS,
    b"W40KTL07": _TL07_KEYS,
}


def _fingerprint(keys: Iterable[str]) -> str:
    """Empreinte d'un ensemble de clés, indépendante de l'ordre d'écriture du littéral."""
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()[:16]


#: Empreinte des entrées FIGÉES ci-dessus — toutes sauf celle de la magic courante. Écrire TL05
#: en littéral empêche qu'une clé déposée dans `_TL04_KEYS` remonte dans l'entrée courante,
#: mais ne dit toujours RIEN de cette clé : l'entrée figée décrit un format déjà écrit sur le
#: disque des joueurs, et rien ne la compare à quoi que ce soit — la réécrire reste muet.
#: `test_reset_keys_match_the_current_save_format` ne peut pas le voir, il ne lit que l'entrée
#: COURANTE ; d'où ce contrôle séparé. Valeurs RECALCULABLES et non tombées du ciel :
#: `_fingerprint` est trois lignes plus haut et le compte se lit sur le littéral.
_FROZEN_FINGERPRINTS: Dict[bytes, Tuple[int, str]] = {
    b"W40KTL04": (128, "4f1bc5601c046cb5"),
    b"W40KTL05": (131, "bc1d5f0c7f07dc36"),
    # Même empreinte que TL05 : le bump TL06 portait sur deux clés du DEUXIÈME niveau, hors de
    # portée de ce contrat. L'égalité est un fait mesuré, pas un copier-coller à corriger.
    b"W40KTL06": (131, "bc1d5f0c7f07dc36"),
}

#: Les neuf clés dont l'ajout n'a PAS été suivi d'un bump entre TL03 et TL04. Elles sont dans le
#: périmètre du verrou : c'est ce qui prouve qu'il aurait attrapé la dérive au lieu de la subir.
KEYS_ADDED_SINCE_TL03 = (
    "secured_objectives", "suppressed_squads", "_reserves_placed", "_reserves_deployed",
    "_ingress_offered", "_ingress_no_destination", "_ingress_arrived",
    "_pending_reserves_wasted", "_restored_model_counter",
)


@pytest.fixture(scope="module")
def reset_mutable_keys() -> FrozenSet[str]:
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    eng.reset(seed=0)
    return frozenset(k for k in eng.game_state if k not in _GS_STATIC_KEYS)


def test_the_reset_really_publishes_mutable_keys(reset_mutable_keys: FrozenSet[str]) -> None:
    """VERT VACANT : un ensemble vide ferait passer la comparaison sans rien prouver."""
    assert len(reset_mutable_keys) > 100, (
        f"seulement {len(reset_mutable_keys)} clés mutables après reset — le moteur n'a pas "
        "réellement initialisé un épisode, la comparaison qui suit ne prouverait rien"
    )


def test_frozen_format_entries_are_untouched() -> None:
    """Une entrée qui n'est plus la magic courante ne se réécrit pas — c'est un fait historique.

    ROUGE dès qu'une clé est ajoutée, retirée ou renommée dans `_TL04_KEYS`. Rien d'autre ne le
    voit : le verrou de format ne lit que l'entrée courante, donc ni TL04 ni TL05, écrites
    en littéral, ne sont lues par un autre contrôle.
    """
    assert _FROZEN_FINGERPRINTS, (
        "VERT VACANT : aucune entrée épinglée, la boucle ci-dessous ne prouverait rien"
    )
    for magic, (count, digest) in _FROZEN_FINGERPRINTS.items():
        keys = MUTABLE_KEYS_BY_MAGIC[magic]
        assert (len(keys), _fingerprint(keys)) == (count, digest), (
            f"l'entrée {magic.decode()} de MUTABLE_KEYS_BY_MAGIC a changé "
            f"({len(keys)} clés / {_fingerprint(keys)} contre {count} / {digest} épinglés). "
            f"Elle décrit un format déjà écrit sur le disque des joueurs : elle ne se corrige "
            f"pas, on ajoute une NOUVELLE entrée sous une nouvelle magic. Si la réécriture est "
            f"malgré tout voulue, c'est l'empreinte qu'il faut changer ICI, sciemment."
        )


def test_every_frozen_entry_is_pinned() -> None:
    """Toute entrée sauf la courante doit être épinglée — sinon le bump suivant laisse un trou.

    Au prochain bump, TL06 deviendra un fait historique à son tour ; sans ce contrôle, elle
    resterait librement réécrivable et le défaut ci-dessus se rouvrirait sous un autre nom.
    """
    figees = {m for m in MUTABLE_KEYS_BY_MAGIC if m != _MAGIC}
    manquantes = sorted(m.decode() for m in figees - set(_FROZEN_FINGERPRINTS))
    orphelines = sorted(m.decode() for m in set(_FROZEN_FINGERPRINTS) - figees)
    assert figees == set(_FROZEN_FINGERPRINTS), (
        f"entrées figées sans empreinte : {manquantes} ; empreintes sans entrée figée : "
        f"{orphelines}. Épingle une entrée dans le même geste que le bump qui la fige."
    )


def test_the_current_magic_declares_its_key_set() -> None:
    """La magic courante doit avoir une entrée : un bump sans entrée laisserait le verrou muet."""
    assert _MAGIC in MUTABLE_KEYS_BY_MAGIC, (
        f"format de save {_MAGIC.decode()} sans ensemble de clés déclaré dans "
        f"MUTABLE_KEYS_BY_MAGIC — ajoute l'entrée en même temps que le bump"
    )


def test_reset_keys_match_the_current_save_format(reset_mutable_keys: FrozenSet[str]) -> None:
    """Le jeu de clés publié par le reset doit décrire le format de save courant.

    DEUX RÉPONSES SELON LE SENS, et les confondre a déjà coûté les parties enregistrées une fois
    (bump du 2026-09-09, annulé le jour même) : un AJOUT impose le bump, un RETRAIT ne
    l'impose que si un lecteur consulte encore la clé. Le message ci-dessous dit les deux.
    """
    expected = MUTABLE_KEYS_BY_MAGIC[_MAGIC]
    added = sorted(reset_mutable_keys - expected)
    removed = sorted(expected - reset_mutable_keys)
    assert not added and not removed, (
        f"le reset d'épisode ne publie plus les mêmes clés mutables que le format "
        f"{_MAGIC.decode()} (ajoutées: {added} ; retirées: {removed}).\n"
        f"AJOUTÉES : une save au format courant rendrait un game_state AMPUTÉ de ces clés, et "
        f"leur premier lecteur lèverait au fond du moteur — après que le chargement a déjà écrasé "
        f"la partie en cours. Bumpe services/game_saves._MAGIC, ajoute l'ancienne magic à "
        f"_LEGACY_MAGICS avec son motif dans _reject_legacy, et ajoute une NOUVELLE entrée dans "
        f"MUTABLE_KEYS_BY_MAGIC — n'élargis pas l'entrée existante.\n"
        f"RETIRÉES : NE BUMPE PAS par réflexe. Si plus aucun lecteur ne consulte la clé, laisse-la "
        f"publiée par le reset, inerte et commentée comme telle : une row qui porte une clé de "
        f"trop n'a jamais fait lever personne, alors que le bump refuse toutes les parties "
        f"enregistrées. Bumpe SEULEMENT si un lecteur subsiste, c'est-à-dire si la clé est créée "
        f"paresseusement et lue en cours de partie : la row la réinjecterait avec sa valeur "
        f"d'alors, avant que le code vivant ne la pose. Une clé qui rejoint _GS_STATIC_KEYS ne "
        f"bumpe PAS — game_snapshots.rebuild_game_state fait gagner la valeur vivante sur celle "
        f"de la row."
    )


@pytest.mark.parametrize("key", KEYS_ADDED_SINCE_TL03)
def test_the_lock_covers_the_keys_that_slipped_through(
    key: str, reset_mutable_keys: FrozenSet[str]
) -> None:
    """Les neuf clés ajoutées sans bump depuis TL03 sont dans le périmètre du verrou.

    Sans ce contrôle, le verrou pourrait porter sur un ensemble de clés qui exclut justement
    celles dont l'oubli a motivé son écriture.
    """
    assert key in reset_mutable_keys, (
        f"{key!r} n'est plus publiée par le reset — le verrou ne couvre plus le cas qui l'a motivé"
    )


def test_a_previous_format_is_refused_at_load(tmp_path: Any) -> None:
    """Une save au format précédent est refusée AVANT d'écraser la partie en cours.

    L'assertion porte sur « écrite avant … », pas sur le nom du format : `_reject_legacy` a DEUX
    branches, et celle du format inconnu interpole l'en-tête lu, donc elle contient elle aussi
    `W40KTL03`. Chercher ce seul nom rendait le verrou vert quoi qu'il arrive — vérifié : sans
    TL03 dans `_LEGACY_MAGICS`, le refus dégénère en « format de fichier inconnu », indiscernable
    d'un fichier corrompu, et l'ancienne assertion passait quand même.
    """
    import struct

    from services.game_saves import SaveStore

    store = SaveStore(str(tmp_path / "parties"))
    os.makedirs(store._dir, exist_ok=True)
    # Fichier structurellement valide, mais écrit sous la magic précédente : seul l'en-tête décide.
    meta = {"id": "20260101-000000", "kind": "manual", "turn": 1}
    import pickle

    meta_bytes = pickle.dumps(meta)
    state_bytes = pickle.dumps({"game_state": {}, "engine_attrs": {}})
    length = struct.Struct(">Q")
    with open(os.path.join(store._dir, "partie_tl03.pkl"), "wb") as f:
        f.write(b"W40KTL03")
        f.write(length.pack(len(meta_bytes)) + meta_bytes)
        f.write(length.pack(len(state_bytes)) + state_bytes)
    store.set_current("partie_tl03")

    with pytest.raises(ValueError, match=f"écrite avant {_MAGIC.decode()}"):
        store.point("20260101-000000")


def test_the_2001_declaration_keys_are_named_in_the_refusal(tmp_path: Any) -> None:
    """Une save TL05 est refusée EN NOMMANT les deux clés 20.01 qui lui manquent.

    Ce que le bump TL06 ferme ne se voit PAS dans le contrat de clés ci-dessus, et c'est tout
    l'intérêt de ce test : `reserves_declaration_queue` et `reserves_declaration_closed` sont
    posées par le reset DANS `deployment_state`, donc au deuxième niveau — invisibles pour
    `test_reset_keys_match_the_current_save_format`, qui est resté VERT pendant toute la dérive.
    Le seul contrôle possible porte donc sur le refus lui-même.

    L'assertion vise le nom des clés et pas seulement « écrite avant … » : sans le motif, le
    message est indiscernable de celui des cinq autres formats périmés, et le joueur ne peut
    pas savoir ce qui manque à son fichier.
    """
    import pickle
    import struct

    from services.game_saves import SaveStore

    store = SaveStore(str(tmp_path / "parties"))
    os.makedirs(store._dir, exist_ok=True)
    meta = {"id": "20260101-000000", "kind": "manual", "turn": 1}
    meta_bytes = pickle.dumps(meta)
    state_bytes = pickle.dumps({"game_state": {}, "engine_attrs": {}})
    length = struct.Struct(">Q")
    with open(os.path.join(store._dir, "partie_tl05.pkl"), "wb") as f:
        f.write(b"W40KTL05")
        f.write(length.pack(len(meta_bytes)) + meta_bytes)
        f.write(length.pack(len(state_bytes)) + state_bytes)
    store.set_current("partie_tl05")

    with pytest.raises(ValueError) as excinfo:
        store.point("20260101-000000")
    message = str(excinfo.value)
    assert f"écrite avant {_MAGIC.decode()}" in message, message
    assert "reserves_declaration_queue" in message, message
    assert "reserves_declaration_closed" in message, message


def test_the_burned_tl06_header_is_refused(tmp_path: Any) -> None:
    """Une save au format `W40KTL06` est refusée : ce numéro a désigné DEUX formats.

    Le bump annulé du 2026-09-09 (fermeture des intentions de zone) a écrit `W40KTL06` de 20:58
    à 22:40, sur des states antérieurs aux clés 20.01 ; le bump du 2026-09-10 a repris le même
    numéro pour un format qui, lui, les contient. Un fichier de la première fenêtre serait donc
    accepté comme courant, écraserait la partie en cours, et ne lèverait qu'ensuite au fond du
    moteur — le scénario exact que la magic existe pour refuser. TL07 rend ce numéro illisible.

    ROUGE si `W40KTL06` redevient la magic courante ou sort de `_LEGACY_MAGICS` : dans le premier
    cas le fichier est accepté, dans le second le refus dégénère en « format de fichier inconnu »,
    indiscernable d'une corruption, et n'explique plus au joueur ce qui s'est passé.
    """
    import pickle
    import struct

    from services.game_saves import SaveStore

    store = SaveStore(str(tmp_path / "parties"))
    os.makedirs(store._dir, exist_ok=True)
    meta = {"id": "20260101-000000", "kind": "manual", "turn": 1}
    meta_bytes = pickle.dumps(meta)
    state_bytes = pickle.dumps({"game_state": {}, "engine_attrs": {}})
    length = struct.Struct(">Q")
    with open(os.path.join(store._dir, "partie_tl06.pkl"), "wb") as f:
        f.write(b"W40KTL06")
        f.write(length.pack(len(meta_bytes)) + meta_bytes)
        f.write(length.pack(len(state_bytes)) + state_bytes)
    store.set_current("partie_tl06")

    with pytest.raises(ValueError) as excinfo:
        store.point("20260101-000000")
    message = str(excinfo.value)
    assert f"écrite avant {_MAGIC.decode()}" in message, message
    assert "TL06" in message and "AMBIGU" in message, message
