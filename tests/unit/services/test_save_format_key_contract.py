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

Corollaire pour l'auteur d'un changement : quand ce test devient rouge, la correction est
d'ajouter une entrée sous une NOUVELLE magic et de bumper `_MAGIC` — pas d'élargir l'entrée
existante, qui décrit un format déjà écrit sur le disque des joueurs.
"""

from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet

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
#: Les trois clés que le reset publie en plus depuis TL04 : le couple de déclaration de montée
#: 13.06 (`ascent_declaration_reset_state`, `engine/phase_handlers/movement_handlers.py`) et le
#: mémo de charge, tous trois posés par le dict de reset de `W40KEngine.reset`.
_KEYS_ADDED_IN_TL05 = frozenset({
    "units_declared_ascent", "units_ascent_declaration_resolved", "_charge_engage_memo",
})

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

MUTABLE_KEYS_BY_MAGIC: Dict[bytes, FrozenSet[str]] = {
    b"W40KTL04": _TL04_KEYS,
    # TL05 est ÉCRIT comme une union, et c'est le point : la ligne dit ce que le format ajoute,
    # au lieu de noyer trois clés dans une seconde copie de cent-vingt. `_TL04_KEYS` est un
    # frozenset — l'entrée TL04 ne peut donc pas être élargie par ce partage, ce qui est
    # exactement l'interdit rappelé plus haut.
    b"W40KTL05": _TL04_KEYS | _KEYS_ADDED_IN_TL05,
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


def test_the_current_magic_declares_its_key_set() -> None:
    """La magic courante doit avoir une entrée : un bump sans entrée laisserait le verrou muet."""
    assert _MAGIC in MUTABLE_KEYS_BY_MAGIC, (
        f"format de save {_MAGIC.decode()} sans ensemble de clés déclaré dans "
        f"MUTABLE_KEYS_BY_MAGIC — ajoute l'entrée en même temps que le bump"
    )


def test_reset_keys_match_the_current_save_format(reset_mutable_keys: FrozenSet[str]) -> None:
    """Toute clé mutable ajoutée ou retirée au reset oblige à bumper la magic du format de save."""
    expected = MUTABLE_KEYS_BY_MAGIC[_MAGIC]
    added = sorted(reset_mutable_keys - expected)
    removed = sorted(expected - reset_mutable_keys)
    assert not added and not removed, (
        f"le reset d'épisode ne publie plus les mêmes clés mutables que le format "
        f"{_MAGIC.decode()} (ajoutées: {added} ; retirées: {removed}). Une save écrite au format "
        f"courant rendrait un game_state incompatible avec le moteur. Bumpe services/game_saves."
        f"_MAGIC, ajoute l'ancienne magic à _LEGACY_MAGICS avec son motif dans _reject_legacy, et "
        f"ajoute une NOUVELLE entrée dans MUTABLE_KEYS_BY_MAGIC — n'élargis pas l'entrée existante."
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
