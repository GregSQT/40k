"""Journal de contrôle d'objectif (14.02) : dire POURQUOI un objectif est tenu ou non.

`objective_controllers` ne porte que le vainqueur. Un joueur posé sur un objectif qu'il ne
prend pas ne pouvait pas distinguer « contesté par plus d'OC », « battle-shocked donc OC à
'-' » (01.07) et « hors de la zone ». Ces tests verrouillent la ligne de journal qui porte les
trois informations, et le fait qu'elle n'est émise qu'aux frontières de phase.
"""

from typing import Any, Dict

import pytest

from services.api_server import _log_objective_control_snapshot


class _EngineStub:
    def __init__(self, game_state: Dict[str, Any]):
        self.game_state = game_state


def _game_state(*, detail, units, models, battle_shocked_ids=()):
    """État minimal : un objectif de 4 hexes, des figurines mono-socle rondes de taille 1."""
    units_cache = {}
    models_cache = {}
    squad_models = {}
    for unit_id, (col, row) in models.items():
        model_id = f"{unit_id}_m0"
        units_cache[unit_id] = {"orientation": 0}
        models_cache[model_id] = {
            "col": col,
            "row": row,
            "HP_CUR": 1,
            "HP_MAX": 1,
            "BASE_SHAPE": "round",
            "BASE_SIZE": 1,
        }
        squad_models[unit_id] = [model_id]
    return {
        "turn": 2,
        "phase": "move",
        "action_log_seq": 0,
        "action_logs": [],
        "objectives": [{"id": "obj_a", "name": "Centre", "hexes": [[10, 10], [10, 11], [11, 10], [11, 11]]}],
        "_objective_control_detail": detail,
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
        "battle_shocked_ids": list(battle_shocked_ids),
    }


def _messages(game_state):
    return [entry["message"] for entry in game_state["action_logs"]]


def test_capture_is_reported_with_oc_and_presence():
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 4,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert len(gs["action_logs"]) == 1
    message = _messages(gs)[0]
    assert "OBJECTIVE Centre" in message
    assert "OC P1=4 P2=0" in message
    assert "models in area P1=1 P2=0" in message
    assert "captured by P1" in message


def test_held_objective_is_distinguished_from_capture():
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 4,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": 1,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert "held by P1" in _messages(gs)[0]


def test_battle_shocked_unit_shows_presence_without_oc():
    """Le cas qui motive la ligne : des figurines DANS l'aire, zéro OC (01.07), objectif perdu.

    Sans le compteur de présence, le journal afficherait « OC P1=0 » et resterait indiscernable
    d'une unité restée hors de la zone.
    """
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 0,
                "player_2_oc": 2,
                "controller": 2,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}, {"id": "u2", "player": 2}],
        models={"u1": (10, 10), "u2": (11, 11)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    message = _messages(gs)[0]
    assert "OC P1=0 P2=2" in message
    assert "models in area P1=1 P2=1" in message
    assert "captured by P2" in message


def test_contested_objective_has_no_controller():
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 2,
                "player_2_oc": 2,
                "controller": None,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}, {"id": "u2", "player": 2}],
        models={"u1": (10, 10), "u2": (11, 11)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert "contested — no controller" in _messages(gs)[0]


def test_empty_objective_emits_no_per_objective_line():
    """Aucune figurine dans l'aire : rien à expliquer SUR CET OBJECTIF, donc pas de ligne pour lui.

    Le journal n'est pour autant pas muet : une ligne globale « aucun objectif disputé » sort une
    fois par tour (cf. `test_empty_board_says_so_once_per_turn`). C'est ce que ce test vérifiait
    avant qu'elle existe — il décrit désormais la bonne moitié du contrat.
    """
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 0,
                "player_2_oc": 0,
                "controller": None,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (40, 40)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert all("obj_a" not in entry.get("objectiveId", "") for entry in gs["action_logs"])
    assert all("OC P1=" not in entry["message"] for entry in gs["action_logs"])


def test_no_objective_detail_is_not_an_error():
    """Scénario sans objectif : pas de détail, pas de journal, pas d'exception."""
    gs = _game_state(
        detail={},
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert gs["action_logs"] == []


def test_same_control_state_is_logged_once():
    """Déduplication par CONTENU : l'API sérialise plusieurs fois le même état par phase.

    Elle ne peut PAS se fier au retour de `refresh_objective_control_on_boundary` : en PvE la
    frontière est consommée par la construction d'observation de l'IA avant que l'API ne la
    voie. L'appel est donc inconditionnel, et c'est cette clé qui évite les doublons.
    """
    detail = {
        "obj_a": {
            "player_1_oc": 4,
            "player_2_oc": 0,
            "controller": 1,
            "previous_controller": None,
        }
    }
    gs = _game_state(detail=detail, units=[{"id": "u1", "player": 1}], models={"u1": (10, 10)})
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    _log_objective_control_snapshot(engine)
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 1


def test_new_phase_relogs_even_when_control_is_unchanged():
    """Un contrôle inchangé d'une phase à l'autre reste une information : « toujours à toi »."""
    detail = {
        "obj_a": {
            "player_1_oc": 4,
            "player_2_oc": 0,
            "controller": 1,
            "previous_controller": 1,
        }
    }
    gs = _game_state(detail=detail, units=[{"id": "u1", "player": 1}], models={"u1": (10, 10)})
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    gs["phase"] = "shoot"
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 2


def test_control_change_within_a_phase_is_logged():
    """L'OC bouge dans la phase (pertes, battle-shock) : le nouvel état doit sortir."""
    detail = {
        "obj_a": {
            "player_1_oc": 4,
            "player_2_oc": 0,
            "controller": 1,
            "previous_controller": None,
        }
    }
    gs = _game_state(detail=detail, units=[{"id": "u1", "player": 1}], models={"u1": (10, 10)})
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    detail["obj_a"] = {
        "player_1_oc": 0,
        "player_2_oc": 3,
        "controller": 2,
        "previous_controller": 1,
    }
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 2
    assert "captured by P2" in _messages(gs)[1]


def test_log_sequence_is_assigned():
    """Les entrées passent par `append_action_log` : le `logSeq` monotone est posé."""
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 4,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert gs["action_logs"][0]["logSeq"] == 1
    assert gs["action_log_seq"] == 1


@pytest.mark.parametrize("missing_key", ["controller", "previous_controller", "player_1_oc", "player_2_oc"])
def test_incomplete_detail_raises_instead_of_guessing(missing_key):
    entry = {
        "player_1_oc": 4,
        "player_2_oc": 0,
        "controller": 1,
        "previous_controller": None,
    }
    del entry[missing_key]
    gs = _game_state(
        detail={"obj_a": entry},
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    from shared.data_validation import ConfigurationError

    with pytest.raises(ConfigurationError):
        _log_objective_control_snapshot(_EngineStub(gs))


def test_line_reaches_the_serialised_response_not_just_game_state():
    """Le VRAI chemin : `_game_state_for_json` journalise AVANT de copier `action_logs`.

    Motif récurrent de ce dépôt — du code testé mais jamais atteint par le chemin de production.
    Ici le risque est précis : si la journalisation passait après la construction du dict
    sérialisé, ou si `action_logs` était exclu du JSON, la ligne existerait dans le moteur sans
    jamais atteindre le navigateur, et le test unitaire ci-dessus resterait vert.
    """
    from services import api_server

    class _StateManagerStub:
        def refresh_objective_control_on_boundary(self, game_state):
            return False

    class _FullEngineStub:
        def __init__(self, game_state):
            self.game_state = game_state
            self.state_manager = _StateManagerStub()
            self.current_mode_code = "pve"
            self.unit_registry = None

    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 4,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    # Clés exigées par la sérialisation elle-même (cf. `test_api_server_helpers`).
    gs["terrain_areas"] = []
    gs["unit_by_id"] = {str(u["id"]): u for u in gs["units"]}
    serialised = api_server._game_state_for_json(_FullEngineStub(gs))

    messages = [entry["message"] for entry in serialised["action_logs"]]
    assert any("OBJECTIVE Centre" in m for m in messages), (
        f"la ligne d'objectif n'atteint pas la réponse sérialisée : {messages}"
    )
    # La clé de déduplication est INTERNE : convention `_` du moteur, jamais envoyée au client.
    assert "_objective_control_logged_for_api" not in serialised
    assert "_objective_control_detail" not in serialised


def _empty_state():
    """Table vide : aucune figurine dans l'aire, tous les objectifs à zéro."""
    return _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 0,
                "player_2_oc": 0,
                "controller": None,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (40, 40)},
    )


def test_empty_board_says_so_once_per_turn():
    """Un journal qui se tait ne dit pas s'il n'a rien à dire ou s'il est cassé.

    C'est ce silence qui a coûté trois sondes du chemin API le 2026-08-11 alors que la réponse
    était « personne n'est sur un objectif ». Une ligne le dit désormais — une seule par tour.
    """
    gs = _empty_state()
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 1
    assert "aucun objectif disputé" in _messages(gs)[0]


def test_empty_board_line_is_not_repeated_at_each_phase_boundary():
    """Six frontières par tour (14.02) : six lignes identiques rendraient le journal illisible."""
    gs = _empty_state()
    engine = _EngineStub(gs)
    for phase in ("command", "move", "shoot", "charge", "fight"):
        gs["phase"] = phase
        _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 1


def test_empty_board_line_returns_on_the_next_turn():
    gs = _empty_state()
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    gs["turn"] = int(gs["turn"]) + 1
    gs["phase"] = "command"
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 2


def test_a_contested_objective_suppresses_the_empty_line():
    """La ligne « aucun objectif disputé » ne doit sortir QUE si rien n'a été dit."""
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 4,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert len(gs["action_logs"]) == 1
    assert "aucun objectif disputé" not in _messages(gs)[0]


def test_board_emptied_within_the_turn_says_so_again():
    """La table se vide APRÈS avoir été occupée, dans le MÊME tour : le journal doit le redire.

    C'est le trou de la première version : la clé de déduplication du silence était posée au
    premier tour vide et jamais relâchée. Une dernière figurine qui meurt en phase de combat
    laissait donc le journal muet — exactement le cas ambigu que cette ligne existe pour
    supprimer. Mesuré avant correction : t1/command → ligne globale, t1/move → ligne par
    objectif, t1/fight revidé → RIEN.
    """
    gs = _empty_state()
    engine = _EngineStub(gs)
    _log_objective_control_snapshot(engine)
    assert "aucun objectif disputé" in _messages(gs)[0]

    # Une unité entre dans l'aire, même tour.
    gs["phase"] = "move"
    gs["models_cache"]["u1_m0"].update({"col": 10, "row": 10})
    gs["_objective_control_detail"]["obj_a"].update({"player_1_oc": 4, "controller": 1})
    gs["action_logs"] = []
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 1
    assert "OC P1=4" in _messages(gs)[0]

    # Elle meurt : tout redevient vide, toujours dans le même tour.
    gs["phase"] = "fight"
    gs["models_cache"]["u1_m0"]["HP_CUR"] = 0
    gs["_objective_control_detail"]["obj_a"].update({"player_1_oc": 0, "controller": None})
    gs["action_logs"] = []
    _log_objective_control_snapshot(engine)
    assert len(gs["action_logs"]) == 1, "le journal est redevenu muet dans le cas ambigu"
    assert "aucun objectif disputé" in _messages(gs)[0]


def test_eliminated_unit_absent_from_units_cache_does_not_crash():
    """Régression : une escouade éliminée reste dans `units` mais est retirée de `units_cache`
    par `update_units_cache_hp`. `iter_living_model_footprints` ne doit pas crasher avec
    ConfigurationError sur la clé manquante, il doit juste ne rien yielder."""
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 0,
                "player_2_oc": 0,
                "controller": None,
                "previous_controller": None,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (10, 10)},
    )
    # Simuler l'élimination : retrait de units_cache (comportement de update_units_cache_hp)
    del gs["units_cache"]["u1"]
    # Ne doit pas lever d'exception
    _log_objective_control_snapshot(_EngineStub(gs))


def test_a_held_objective_without_oc_is_not_silence():
    """Méthode `secured` (14.03) : le contrôle PERSISTE après le départ des figurines.

    Un objectif encore tenu à 0 OC rapporte des VP. Le sauter ferait affirmer « aucun objectif
    disputé » pendant que le joueur marque dessus. Aucune config livrée n'utilise `secured`
    aujourd'hui, mais la branche est supportée par le moteur : le test de vacuité doit décrire la
    règle, pas la configuration du moment.
    """
    gs = _game_state(
        detail={
            "obj_a": {
                "player_1_oc": 0,
                "player_2_oc": 0,
                "controller": 1,
                "previous_controller": 1,
            }
        },
        units=[{"id": "u1", "player": 1}],
        models={"u1": (40, 40)},
    )
    _log_objective_control_snapshot(_EngineStub(gs))
    assert len(gs["action_logs"]) == 1
    message = _messages(gs)[0]
    assert "aucun objectif disputé" not in message
    assert "held by P1" in message
