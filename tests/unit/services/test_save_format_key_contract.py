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

DEUX NIVEAUX, depuis le 2026-09-10. `MUTABLE_KEYS_BY_MAGIC` épingle les clés de PREMIER niveau ;
`MUTABLE_SUBKEYS_BY_MAGIC` épingle les sous-clés des dicts que le reset publie. Le second niveau
a été ajouté parce que le premier a laissé passer `reserves_declaration_queue` et
`reserves_declaration_closed` (étape 20.01), posées SOUS `deployment_state` — une clé mutable
déjà déclarée, donc un ensemble de premier niveau inchangé et un verrou VERT pendant toute la
dérive. Le bump TL06 a dû être décidé à la main. Une row restaure le dict parent EN BLOC
(`game_snapshots.rebuild_game_state` remplace la valeur mutable par celle de la row) : une
sous-clé manquante survit donc au chargement exactement comme une clé de premier niveau.

PORTÉE — ce que ce verrou NE couvre PAS, mesuré : il ne voit que les clés posées par le RESET.
Le moteur écrit 162 clés distinctes dans le game_state, dont beaucoup naissent paresseusement en
cours de partie ; une clé obligatoire créée hors reset lui échapperait. Il ne voit pas non plus
une clé dont la FORME change à contenu de nom constant, ni les champs des dicts d'unité portés
par la liste `units`. La profondeur est BORNÉE À 1 : mesuré sur le reset du scénario ci-dessous,
les seuls dicts à schéma situés plus bas (`_deployment_scoring_cache[joueur]`,
`_deployment_slot_candidates['candidates'][slot]`) vivent sous un niveau indexé par la donnée,
qu'aucun chemin statique ne peut nommer. Les neuf clés de la dérive TL03→TL04 et les deux clés
20.01 sont toutes dans le périmètre couvert.

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

UN SEUL LITTÉRAL, celui de la magic COURANTE (2026-09-10). Le fichier a porté jusqu'à cinq jeux
de 131 clés, un par format, dont quatre strictement identiques : ils n'étaient lus par aucun
contrôle qui ne fût pas lui-même chargé de les garder, et par aucun code de production. Les
formats passés vivent désormais dans `_FORMAT_FINGERPRINTS` / `_FORMAT_SUBKEY_FINGERPRINTS`,
une ligne (compte, empreinte) chacun. Ce registre est croyable parce que chaque ligne a été
confrontée à son littéral tant que sa magic était courante — c'est
`test_the_current_format_matches_its_recorded_fingerprint` — et parce qu'il est comparé à
`_LEGACY_MAGICS`, la liste de PRODUCTION des formats refusés, par
`test_every_legacy_magic_keeps_its_fingerprint`. Ce que le retrait coûte, dit franchement : le
CONTENU d'un format ancien ne se lit plus dans le fichier, seul l'historique le rend.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, FrozenSet, Iterable, Tuple

import pytest

from services.game_saves import _LEGACY_MAGICS, _MAGIC, SaveStore, _pack_record
from services.game_snapshots import _GS_STATIC_KEYS

# Ce module ne parle pas à l'API : la fixture d'auth du conftest serait du travail jeté.
from tests.unit.services._auth_neutre import authenticated_api_client  # noqa: F401

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
#: Même scénario que `test_game_snapshots_static_keys` : déploiement ACTIF, donc le reset publie
#: aussi les clés de déploiement et de réserves stratégiques.
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/agents/ArmageddonAgent_x1/scenarios/holdout_regular/scenario_bot-01.json"
)

#: Clés mutables publiées par le reset pour la magic COURANTE, et elle seule. Les formats déjà
#: écrits sur le disque des joueurs ne vivent plus ici en littéral : ils sont réduits à leur
#: couple (nombre de clés, empreinte) dans `_FORMAT_FINGERPRINTS`. Jusqu'au 2026-09-10 le fichier
#: portait un littéral par format — cinq jeux de 131 clés dont quatre strictement identiques —
#: gardés par un contrôle qui ne servait qu'à empêcher leur réécriture. Ils n'étaient lus par
#: RIEN d'autre : aucun code de production ne nomme la table (vérifié sur `services/`, `engine/`,
#: `ai/` et `scripts/`), et le refus de `game_saves._reject_legacy` énumère ses clauses en prose
#: littérale, sans jamais la consulter. L'empreinte garde ce que le littéral prouvait — qu'un
#: format passé n'a pas bougé — pour une ligne au lieu de quarante.
#:
#: LE RITUEL DE BUMP tient en deux gestes, et `test_every_legacy_magic_keeps_its_fingerprint`
#: rougit si le second manque : renommer le littéral ci-dessous à la nouvelle magic (en y ajoutant
#: la clé qui a motivé le bump), et inscrire le couple SORTANT dans `_FORMAT_FINGERPRINTS` —
#: `_fingerprint` et le compte se lisent sur le littéral avant de le renommer.
#: ⚠️ LE PREMIER TL06 N'A JAMAIS EXISTÉ : la fermeture des intentions de zone (2026-09-09) a
#: d'abord bumpé le format parce que cinq clés quittaient le reset, et le bump a été ANNULÉ le
#: même jour — les cinq clés sont restées publiées, et elles sont encore dans le littéral.
#: La raison est dans `services/game_saves._MAGIC` : le refus protège d'un état AMPUTÉ, pas d'un
#: état qui porte une clé de trop. Le TL06 du 2026-09-10 est un autre bump, motivé par un AJOUT
#: (étape 20.01), et il a d'abord REPRIS le numéro annulé — un fichier écrit entre 20:58 et 22:40
#: le 2026-09-09 porte pourtant bien cet en-tête sur un état sans les clés 20.01. C'est ce qui a
#: coûté le bump suivant : TL07 brûle le numéro ambigu et TL06 part en legacy. UN NUMÉRO ÉMIS NE
#: SE REPREND PAS, même annulé le jour même.
#: TL08 = TL07 à la clé de PREMIER niveau près : le bump vient d'une sous-clé de
#: `deployment_state` (`reserves_declaration_started`), donc de la table du second niveau — d'où
#: deux formats de suite au même compte (131) et à la même empreinte, fait mesuré et non doublon.
_TL08_KEYS: FrozenSet[str] = frozenset({
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

#: La table reste indexée par la magic — c'est ce qui rend le premier geste du bump vérifiable :
#: renommer le littéral sans re-tagger la clé laisserait `_MAGIC` sans entrée, et
#: `test_the_current_magic_declares_its_key_set` rougit.
MUTABLE_KEYS_BY_MAGIC: Dict[bytes, FrozenSet[str]] = {
    b"W40KTL08": _TL08_KEYS,
}

#: --- DEUXIÈME NIVEAU : sous-clés des dicts mutables publiés par le reset ---------------------
#: Même contrat que ci-dessus, un cran plus bas. Une row de save restaure le dict parent EN BLOC
#: (`game_snapshots.rebuild_game_state`), donc une sous-clé OBLIGATOIRE ajoutée au reset manque
#: exactement de la même façon dans une save écrite avant, et son premier lecteur lève au fond du
#: moteur une fois la partie en cours déjà écrasée — c'est le scénario 20.01 de TL06.
#:
#: PROFONDEUR BORNÉE À 1, et c'est une mesure, pas une commodité : sous les quatre dicts à schéma
#: ci-dessous, le seul niveau supplémentaire est indexé par la DONNÉE (`deployable_units` par
#: joueur, `candidates` par slot), qu'aucun chemin statique ne peut nommer. Les dicts à schéma
#: plus profonds (`_deployment_scoring_cache[joueur]`) vivent eux aussi sous un niveau de donnée.
#:
#: Une entrée décrit le format COURANT et lui seul, comme au premier niveau : elle ne s'élargit
#: jamais après coup, on la renomme à la nouvelle magic en inscrivant le couple sortant dans
#: `_FORMAT_SUBKEY_FINGERPRINTS`.
#: TL08 = TL07 + `reserves_declaration_started` dans `deployment_state` : le marqueur « une
#: réponse 20.01 a été donnée », lu par `_execute_change_roster_action` pour refuser le
#: remplacement d'armée une fois l'étape commencée. Une row TL07 restitue `deployment_state` en
#: bloc, donc sans lui, et ce lecteur lève.
_TL08_SUBKEYS: Dict[str, FrozenSet[str]] = {
    # Comptabilité MUTABLE de la phase de déploiement. Les trois dernières sont les clés 20.01
    # (`deployment_handlers.RESERVES_DECLARATION_QUEUE_KEY` / `_CLOSED_KEY` / `_STARTED_KEY`).
    "deployment_state": frozenset({
        "current_deployer", "deployable_units", "deployed_units", "deployment_complete",
        "reserves_declaration_queue", "reserves_declaration_closed",
        "reserves_declaration_started",
    }),
    "_deployment_slot_candidates": frozenset({"key", "candidates"}),
    "_grid_static_hex_arrays": frozenset({"walls", "objectives", "cover", "obscuring"}),
    "choice_timing_index": frozenset({
        "phase_start", "on_deploy", "turn_start", "activation_start", "player_turn_start",
    }),
    # Dicts que le reset publie VIDES : le format n'y porte aucune sous-clé, et l'épingle à ∅ le
    # dit. Le jour où le reset en publie une, la comparaison rougit et impose une décision —
    # sous-clé NOMMÉE et obligatoire → bump ; sous-clés dérivées des entités (unités, joueurs,
    # hexs) → déplacer la clé dans `_DATA_KEYED_MUTABLE_DICTS`, sans bump.
    "_charge_declaration_current": frozenset(),
    "_charge_initial_rolls": frozenset(),
    "_charge_plan_cache": frozenset(),
    "_edge_distance_cache": frozenset(),
    "_squad_move_pool_cache": frozenset(),
    "_zone_intent_declarations": frozenset(),
    "advance_rolls": frozenset(),
    "charge_range_rolls": frozenset(),
    "destroyed_models": frozenset(),
    "enemy_adjacent_counts_player_1": frozenset(),
    "enemy_adjacent_counts_player_2": frozenset(),
    "moved_distance_by_model": frozenset(),
    "objective_controllers": frozenset(),
    "occupation_map": frozenset(),
    "pending_squad_fight_intents": frozenset(),
    "pending_squad_shoot_intents": frozenset(),
    "reactive_decision_payload": frozenset(),
    "secured_objectives": frozenset(),
    "suppressed_squads": frozenset(),
    "unit_zone_assignments": frozenset(),
}

MUTABLE_SUBKEYS_BY_MAGIC: Dict[bytes, Dict[str, FrozenSet[str]]] = {
    b"W40KTL08": _TL08_SUBKEYS,
}

#: Dicts mutables dont les sous-clés sont des DONNÉES de la partie — identifiants d'unité ou de
#: figurine, numéro de joueur, coordonnées, clés de cache. Les épingler épinglerait le scénario
#: de la fixture, pas le format de save : une unité de plus dans le roster ferait rougir un
#: verrou qui n'a rien à dire sur le format. Ils sont donc déclarés ICI, explicitement, et non
#: simplement omis — `test_every_mutable_dict_of_the_reset_is_classified` exige que tout dict
#: mutable soit dans l'une ou l'autre table, ce qui force une décision sur chaque dict NOUVEAU
#: au lieu de rouvrir silencieusement le trou que TL06 a payé.
_DATA_KEYED_MUTABLE_DICTS: FrozenSet[str] = frozenset({
    # par identifiant d'unité, d'escouade ou de figurine
    "models_cache", "squad_cache", "squad_models", "unit_by_id", "units_cache", "units_cache_prev",
    # par numéro de joueur
    "_grid_deployment_zone_anchor", "_reserves_deployed", "_reserves_destroyed_turn3",
    "_reserves_placed", "command_points", "deployment_type_by_player",
    "model_count_at_start_by_player", "oath_target", "player_names", "player_types",
    "value_at_start", "victory_points", "waaagh_active", "waaagh_called",
    # par clé de cache (tuples d'entités, de profils ou d'hexs)
    "_best_weapon_cache", "_deployment_scoring_cache", "_entity_types_cache",
    "_obs_weapon_profiles_cache", "_socle_wall_blocked_cache",
})


def _fingerprint(keys: Iterable[str]) -> str:
    """Empreinte d'un ensemble de clés, indépendante de l'ordre d'écriture du littéral."""
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()[:16]


def _subkey_fingerprint(table: Dict[str, FrozenSet[str]]) -> str:
    """Empreinte d'une table parent → sous-clés, indépendante de l'ordre d'écriture du littéral."""
    return _fingerprint(f"{parent}\t{'|'.join(sorted(sub))}" for parent, sub in table.items())


#: REGISTRE DES FORMATS : une ligne par magic depuis TL04, la courante COMPRISE. C'est tout ce
#: qui reste des formats passés, dont le littéral a été retiré le 2026-09-10 — il n'était lu par
#: aucun contrôle qui ne fût pas lui-même chargé de le garder.
#:
#: Chaque ligne a été vérifiée CONTRE SON LITTÉRAL pendant que sa magic était courante
#: (`test_the_current_format_matches_its_recorded_fingerprint`), et elle ne bouge plus ensuite :
#: c'est ce qui la rend croyable une fois le littéral parti. Valeurs recalculables et non tombées
#: du ciel : `_fingerprint` est juste au-dessus et le compte se lit sur le littéral.
_FORMAT_FINGERPRINTS: Dict[bytes, Tuple[int, str]] = {
    b"W40KTL04": (128, "4f1bc5601c046cb5"),
    b"W40KTL05": (131, "bc1d5f0c7f07dc36"),
    # Même empreinte que TL05 : le bump TL06 portait sur deux clés du DEUXIÈME niveau, hors de
    # portée de ce contrat. L'égalité est un fait mesuré, pas un copier-coller à corriger.
    b"W40KTL06": (131, "bc1d5f0c7f07dc36"),
    # Même empreinte encore : TL07 ne brûlait qu'un numéro d'en-tête, et TL08 vient d'une
    # sous-clé. Deux bumps de suite sans mouvement au premier niveau — fait mesuré.
    b"W40KTL07": (131, "bc1d5f0c7f07dc36"),
    #: COURANTE — vérifiée contre `_TL08_KEYS` à chaque exécution.
    b"W40KTL08": (131, "bc1d5f0c7f07dc36"),
}

#: Même registre pour le SECOND niveau, né sous TL06 : les magics antérieures n'y figurent pas,
#: le fichier n'a jamais relevé leurs sous-clés.
_FORMAT_SUBKEY_FINGERPRINTS: Dict[bytes, Tuple[int, str]] = {
    b"W40KTL06": (24, "f5d15abb41f83555"),
    # TL07 n'ajoutait aucune sous-clé (numéro brûlé), d'où l'égalité avec TL06.
    b"W40KTL07": (24, "f5d15abb41f83555"),
    #: COURANTE — vérifiée contre `_TL08_SUBKEYS` à chaque exécution ; `reserves_declaration_started`
    #: est la sous-clé qui sépare cette empreinte de celle de TL07.
    b"W40KTL08": (24, "982bf7cde624e5aa"),
}

#: Première magic relevée par chacun des deux registres. Avant elles, le fichier n'a jamais décrit
#: le contenu d'un format : TL01 à TL03 sont refusées par `game_saves._reject_legacy` sans qu'on
#: sache autrement que par l'historique ce qu'elles portaient.
_PREMIERE_MAGIC_RELEVEE = b"W40KTL04"
_PREMIERE_MAGIC_SOUS_CLES_RELEVEE = b"W40KTL06"

#: Les neuf clés dont l'ajout n'a PAS été suivi d'un bump entre TL03 et TL04. Elles sont dans le
#: périmètre du verrou : c'est ce qui prouve qu'il aurait attrapé la dérive au lieu de la subir.
KEYS_ADDED_SINCE_TL03 = (
    "secured_objectives", "suppressed_squads", "_reserves_placed", "_reserves_deployed",
    "_ingress_offered", "_ingress_no_destination", "_ingress_arrived",
    "_pending_reserves_wasted", "_restored_model_counter",
)


@pytest.fixture(scope="module")
def reset_game_state() -> Dict[str, Any]:
    """Un SEUL épisode réinitialisé pour tout le module : les deux vues ci-dessous en dérivent."""
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
    return eng.game_state


@pytest.fixture(scope="module")
def reset_mutable_keys(reset_game_state: Dict[str, Any]) -> FrozenSet[str]:
    return frozenset(k for k in reset_game_state if k not in _GS_STATIC_KEYS)


@pytest.fixture(scope="module")
def reset_mutable_dicts(reset_game_state: Dict[str, Any]) -> Dict[str, FrozenSet[Any]]:
    """Sous-clés de PREMIER niveau de chaque valeur mutable qui est un dict (profondeur bornée)."""
    return {
        k: frozenset(v.keys())
        for k, v in reset_game_state.items()
        if k not in _GS_STATIC_KEYS and isinstance(v, dict)
    }


def test_the_reset_really_publishes_mutable_keys(reset_mutable_keys: FrozenSet[str]) -> None:
    """VERT VACANT : un ensemble vide ferait passer la comparaison sans rien prouver."""
    assert len(reset_mutable_keys) > 100, (
        f"seulement {len(reset_mutable_keys)} clés mutables après reset — le moteur n'a pas "
        "réellement initialisé un épisode, la comparaison qui suit ne prouverait rien"
    )


def test_the_current_format_matches_its_recorded_fingerprint() -> None:
    """Le littéral courant doit valoir son couple (compte, empreinte) au registre.

    C'est ce contrôle qui rend le registre CROYABLE : chaque ligne a été confrontée à son
    littéral tant que sa magic était courante, et c'est tout ce qui reste d'elle une fois le
    littéral retiré au bump suivant. Sans lui, un format sortant emporterait une empreinte que
    rien n'a jamais vérifiée, et le registre ne serait plus qu'une suite de chiffres.

    ROUGE si le littéral change sans que le couple suive — y compris pour un ajout légitime, où
    la marche à suivre est d'écrire ICI la nouvelle valeur, sciemment.
    """
    couple = _FORMAT_FINGERPRINTS[_MAGIC]
    assert (len(_TL08_KEYS), _fingerprint(_TL08_KEYS)) == couple, (
        f"le littéral de {_MAGIC.decode()} vaut {len(_TL08_KEYS)} clés / "
        f"{_fingerprint(_TL08_KEYS)}, le registre dit {couple[0]} / {couple[1]}."
    )
    couple = _FORMAT_SUBKEY_FINGERPRINTS[_MAGIC]
    assert (len(_TL08_SUBKEYS), _subkey_fingerprint(_TL08_SUBKEYS)) == couple, (
        f"la table de sous-clés de {_MAGIC.decode()} vaut {len(_TL08_SUBKEYS)} dicts / "
        f"{_subkey_fingerprint(_TL08_SUBKEYS)}, le registre dit {couple[0]} / {couple[1]}."
    )


def test_every_legacy_magic_keeps_its_fingerprint() -> None:
    """Un format qui cesse d'être courant laisse son empreinte au registre — sinon il disparaît.

    C'est le SECOND geste du bump, et le seul que rien d'autre ne rattrape : le premier (renommer
    le littéral à la nouvelle magic) fait rougir `test_the_current_magic_declares_its_key_set`,
    celui-ci fait rougir l'oubli de la ligne SORTANTE. Depuis le retrait des littéraux passés
    (2026-09-10), cette ligne est la seule trace de ce que portait un format déjà écrit.

    Le registre est comparé à `_LEGACY_MAGICS`, la liste de PRODUCTION des formats refusés : les
    deux ne peuvent pas diverger sans que ce test le dise.
    """
    for nom, registre, premiere in (
        ("_FORMAT_FINGERPRINTS", _FORMAT_FINGERPRINTS, _PREMIERE_MAGIC_RELEVEE),
        ("_FORMAT_SUBKEY_FINGERPRINTS", _FORMAT_SUBKEY_FINGERPRINTS, _PREMIERE_MAGIC_SOUS_CLES_RELEVEE),
    ):
        attendues = {m for m in _LEGACY_MAGICS if m >= premiere} | {_MAGIC}
        assert len(attendues) > 1, (
            f"VERT VACANT : {nom} n'aurait que la magic courante à couvrir, la comparaison "
            f"ci-dessous ne prouverait rien"
        )
        manquantes = sorted(m.decode() for m in attendues - set(registre))
        orphelines = sorted(m.decode() for m in set(registre) - attendues)
        assert set(registre) == attendues, (
            f"{nom} — formats sans empreinte : {manquantes} ; empreintes sans format : "
            f"{orphelines}. Inscris la ligne SORTANTE dans le même geste que le bump : son "
            f"compte et son empreinte se lisent sur le littéral avant de le renommer."
        )



def test_the_current_magic_declares_its_key_set() -> None:
    """La magic courante doit avoir une entrée : un bump sans entrée laisserait le verrou muet."""
    assert _MAGIC in MUTABLE_KEYS_BY_MAGIC, (
        f"format de save {_MAGIC.decode()} sans ensemble de clés déclaré dans "
        f"MUTABLE_KEYS_BY_MAGIC — ajoute l'entrée en même temps que le bump"
    )


def test_the_current_magic_declares_its_subkeys() -> None:
    """Idem au deuxième niveau : un bump sans entrée de sous-clés rendrait ce verrou-là muet."""
    assert _MAGIC in MUTABLE_SUBKEYS_BY_MAGIC, (
        f"format de save {_MAGIC.decode()} sans table de sous-clés déclarée dans "
        f"MUTABLE_SUBKEYS_BY_MAGIC — ajoute l'entrée en même temps que le bump"
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
        f"_LEGACY_LOSSES avec ce qui lui manque, et ajoute une NOUVELLE entrée dans "
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


def test_every_mutable_dict_of_the_reset_is_classified(
    reset_mutable_dicts: Dict[str, FrozenSet[Any]]
) -> None:
    """Tout dict mutable du reset est soit épinglé sous-clé par sous-clé, soit déclaré indexé par
    la donnée. Sans cette partition, un dict NOUVEAU n'entrerait dans aucune table et son contenu
    dériverait en silence — exactement ce que `deployment_state` a fait sous TL05.
    """
    epingles = set(MUTABLE_SUBKEYS_BY_MAGIC[_MAGIC])
    chevauchement = sorted(epingles & _DATA_KEYED_MUTABLE_DICTS)
    assert not chevauchement, (
        f"{chevauchement} sont à la fois épinglés et déclarés indexés par la donnée — un dict "
        f"relève d'un seul régime, sinon l'épingle ne dit plus ce qu'elle vérifie"
    )
    observes = set(reset_mutable_dicts)
    non_classes = sorted(observes - (epingles | _DATA_KEYED_MUTABLE_DICTS))
    fantomes = sorted((epingles | _DATA_KEYED_MUTABLE_DICTS) - observes)
    assert not non_classes and not fantomes, (
        f"dicts mutables du reset non classés : {non_classes} ; classés mais absents du reset : "
        f"{fantomes}.\nNON CLASSÉS : décide, pour chacun, si ses sous-clés sont un SCHÉMA (noms "
        f"fixes, écrits en clair par le code) — alors épingle-les dans l'entrée de "
        f"MUTABLE_SUBKEYS_BY_MAGIC de la magic courante — ou des DONNÉES de la partie (id "
        f"d'unité, joueur, hex, clé de cache) — alors ajoute la clé à _DATA_KEYED_MUTABLE_DICTS. "
        f"Une clé de premier niveau vraiment nouvelle fait de toute façon rougir "
        f"test_reset_keys_match_the_current_save_format et impose un bump.\nABSENTS : la clé ne "
        f"vient plus du reset, ou n'est plus un dict — retire-la de la table qui la déclare, en "
        f"ajoutant une NOUVELLE entrée de magic si c'est l'entrée épinglée qui change."
    )


def test_data_keyed_dicts_really_carry_data(
    reset_mutable_dicts: Dict[str, FrozenSet[Any]]
) -> None:
    """Un dict déclaré indexé par la donnée doit EN PORTER au reset — sinon rien ne l'excuse.

    C'est ce qui empêche `_DATA_KEYED_MUTABLE_DICTS` de devenir la poubelle où l'on range ce
    qu'on ne veut pas épingler : un dict vide au reset n'a aucune donnée à protéger du verrou,
    sa place est dans la table épinglée avec un ensemble de sous-clés vide.
    """
    assert _DATA_KEYED_MUTABLE_DICTS, (
        "VERT VACANT : aucune clé déclarée indexée par la donnée, la boucle ne prouverait rien"
    )
    vides = sorted(k for k in _DATA_KEYED_MUTABLE_DICTS & set(reset_mutable_dicts)
                   if not reset_mutable_dicts[k])
    assert not vides, (
        f"{vides} sont déclarés indexés par la donnée mais le reset les publie VIDES — déplace-les "
        f"dans l'entrée de MUTABLE_SUBKEYS_BY_MAGIC avec frozenset() comme jeu de sous-clés"
    )


def test_reset_subkeys_match_the_current_save_format(
    reset_mutable_dicts: Dict[str, FrozenSet[Any]]
) -> None:
    """Les sous-clés publiées par le reset doivent décrire le format de save courant.

    C'est le contrôle qui manquait le 2026-09-10 : les deux clés 20.01 posées dans
    `deployment_state` ont imposé le bump TL06 sans qu'aucun test ne rougisse.
    """
    expected = MUTABLE_SUBKEYS_BY_MAGIC[_MAGIC]
    ecarts = []
    for parent in sorted(expected):
        if parent not in reset_mutable_dicts:
            continue  # parent disparu : rapporté par test_every_mutable_dict_of_the_reset_is_classified
        observees = reset_mutable_dicts[parent]
        ajoutees = sorted(repr(k) for k in observees - expected[parent])
        retirees = sorted(repr(k) for k in expected[parent] - observees)
        if ajoutees or retirees:
            ecarts.append(f"{parent} (ajoutées: {ajoutees} ; retirées: {retirees})")
    assert not ecarts, (
        f"le reset d'épisode ne publie plus les mêmes SOUS-CLÉS que le format {_MAGIC.decode()} : "
        f"{'; '.join(ecarts)}.\n"
        f"AJOUTÉES : une save au format courant restitue le dict parent EN BLOC, donc amputé de "
        f"ces sous-clés, et leur premier lecteur lèvera au fond du moteur — après que le "
        f"chargement a déjà écrasé la partie en cours. Si la sous-clé est un nom FIXE écrit par "
        f"le code : bumpe services/game_saves._MAGIC, ajoute l'ancienne magic à _LEGACY_LOSSES "
        f"avec ce qui lui manque, et ajoute une NOUVELLE entrée dans "
        f"MUTABLE_SUBKEYS_BY_MAGIC — n'élargis pas l'entrée existante. Si le dict s'est mis à "
        f"porter des sous-clés dérivées des ENTITÉS (unité, joueur, hex), il ne relève plus de "
        f"l'épingle : déplace-le dans _DATA_KEYED_MUTABLE_DICTS, sans bump.\n"
        f"RETIRÉES : même arbitrage qu'au premier niveau — le refus protège d'un état AMPUTÉ, "
        f"pas d'un état qui porte une sous-clé de trop. Ne bumpe que si un lecteur consulte "
        f"encore la sous-clé."
    )


@pytest.mark.parametrize("subkey", ("reserves_declaration_queue", "reserves_declaration_closed"))
def test_the_subkey_lock_covers_the_2001_keys(
    subkey: str, reset_mutable_dicts: Dict[str, FrozenSet[Any]]
) -> None:
    """Les deux clés qui ont motivé ce deuxième niveau sont dans son périmètre.

    Sans ce contrôle, l'épingle pourrait porter sur un jeu de dicts qui exclut justement celui
    dont la dérive a coûté le bump TL06.
    """
    assert subkey in reset_mutable_dicts["deployment_state"], (
        f"{subkey!r} n'est plus posée par le reset dans deployment_state — le verrou de sous-clés "
        f"ne couvre plus le cas qui l'a motivé"
    )
    assert subkey in MUTABLE_SUBKEYS_BY_MAGIC[_MAGIC]["deployment_state"], (
        f"{subkey!r} n'est plus épinglée pour le format {_MAGIC.decode()}"
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


def _ecrire_save_sous_magic(tmp_path: Any, magic: bytes) -> SaveStore:
    """Écrit une partie d'un seul enregistrement sous `magic`, et rend le store qui la porte.

    Le cadre binaire vient de `_pack_record`, la fonction de PRODUCTION : un test qui le
    réécrirait à la main resterait vert le jour où le cadre change, sur un fichier que le serveur
    n'écrit plus. Seul l'en-tête est posé ici — c'est lui, et lui seul, que les refus ci-dessous
    mettent à l'épreuve.
    """
    store = SaveStore(str(tmp_path / "parties"))
    os.makedirs(store._dir, exist_ok=True)
    nom = f"partie_{magic.decode().lower()}"
    row = {
        "meta": {"id": "20260101-000000", "kind": "manual", "turn": 1},
        "state": {"game_state": {}, "engine_attrs": {}},
    }
    with open(os.path.join(store._dir, f"{nom}.pkl"), "wb") as f:
        f.write(magic)
        f.write(_pack_record(row))
    store.set_current(nom)
    return store


def _message_de_refus(tmp_path: Any, magic: bytes) -> str:
    """Charge une save écrite sous `magic`, exige le refus, et rend son message.

    LES DEUX ASSERTIONS COMMUNES SONT ICI, et c'est ce qui les rend inoubliables : recopiées par
    test, chaque nouvel en-tête périmé les réécrivait à la main.
      - « au format <magic> » : l'en-tête RELU, interpolé en tête de message, est la SEULE chose
        qui sépare un format périmé d'un autre — `_reject_legacy` énumère toutes ses clauses quel
        que soit le fichier, donc chercher un motif de clause ne prouve pas quel format a été
        refusé (mesuré : le refus d'un TL03 contient « TL06 » et « AMBIGU »).
      - « écrite avant … » : sépare la branche « format périmé » de la branche « format inconnu »,
        qui interpole elle aussi l'en-tête lu et rendrait la première assertion vraie sur un
        fichier tombé de `_LEGACY_MAGICS`.
    Chaque test n'ajoute donc que ce qui lui est propre : les clauses que SON format doit nommer.
    """
    store = _ecrire_save_sous_magic(tmp_path, magic)

    with pytest.raises(ValueError) as excinfo:
        store.point("20260101-000000")
    message = str(excinfo.value)
    assert f"au format {magic.decode()}" in message, message
    assert f"écrite avant {_MAGIC.decode()}" in message, message
    return message


def test_a_previous_format_is_refused_at_load(tmp_path: Any) -> None:
    """Une save au format précédent est refusée AVANT d'écraser la partie en cours.

    Aucune clause propre à asserter : ce format-là n'a rien de nommé à vérifier dans le message,
    seul son refus compte. Les deux assertions du helper suffisent — dont « écrite avant … », qui
    est celle qui sépare les DEUX branches de `_reject_legacy` : celle du format inconnu interpole
    l'en-tête lu, donc elle contient elle aussi `W40KTL03`. Vérifié : sans TL03 dans
    `_LEGACY_MAGICS`, le refus dégénère en « format de fichier inconnu », indiscernable d'un
    fichier corrompu.
    """
    # Fichier structurellement valide, mais écrit sous la magic précédente : seul l'en-tête décide.
    _message_de_refus(tmp_path, b"W40KTL03")


def test_the_2001_declaration_keys_are_named_in_the_refusal(tmp_path: Any) -> None:
    """Une save TL05 est refusée EN NOMMANT les deux clés 20.01 qui lui manquent.

    Ce que le bump TL06 ferme ne se voit PAS dans le contrat de clés de PREMIER niveau :
    `reserves_declaration_queue` et `reserves_declaration_closed` sont posées par le reset DANS
    `deployment_state`, donc au deuxième niveau — invisibles pour
    `test_reset_keys_match_the_current_save_format`, qui est resté VERT pendant toute la dérive.
    C'est `test_reset_subkeys_match_the_current_save_format` qui les épingle désormais ; ce
    test-ci vérifie l'autre moitié, le REFUS que le bump rend possible.

    Nommer les deux clés vérifie le CONTENU du message — le joueur doit lire ce qui manque à son
    fichier —, jamais que c'est bien TL05 qui a été refusé : `_reject_legacy` énumère toutes ses
    clauses quel que soit l'en-tête lu (mesuré : la clause 20.01 est aussi dans le refus d'un
    TL03). Ce qui discrimine est dans `_message_de_refus`, et les confondre rendrait ce test à
    moitié vacant.
    """
    message = _message_de_refus(tmp_path, b"W40KTL05")

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

    Ce qui prouve que c'est bien TL06 qui a été refusé est l'en-tête RELU, dans
    `_message_de_refus`, et non le mot « AMBIGUË » asserté ici : le message énumère toutes les
    clauses quel que soit le fichier, donc ce motif passerait aussi sur un refus de TL03 —
    mesuré. Il vérifie le contenu lu par le joueur, pas l'identité du format.
    """
    message = _message_de_refus(tmp_path, b"W40KTL06")

    assert "AMBIGU" in message, message


def test_the_tl07_header_is_refused(tmp_path: Any) -> None:
    """Une save `W40KTL07` est refusée en nommant la sous-clé 20.01 qui lui manque.

    TL08 a bumpé pour `reserves_declaration_started`, posée au reset dans `deployment_state`
    (`engine/phase_handlers/deployment_handlers.py`). Sans ce test, la clause TL07 du refus
    n'était prouvée par rien : les trois autres en-têtes périmés avaient chacun le leur, celui-là
    non — et un fichier TL07 chargé dans le moteur d'aujourd'hui rendrait un `deployment_state`
    amputé de ce marqueur, dont le lecteur lève une fois la partie en cours déjà écrasée.

    ROUGE si `W40KTL07` sort de `_LEGACY_MAGICS` : le refus dégénère alors en « format de fichier
    inconnu », indiscernable d'une corruption.
    """
    message = _message_de_refus(tmp_path, b"W40KTL07")

    assert "reserves_declaration_started" in message, message
