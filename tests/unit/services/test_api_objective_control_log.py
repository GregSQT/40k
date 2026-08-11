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


def test_empty_objective_emits_nothing():
    """Aucune figurine dans l'aire : il n'y a rien à expliquer, donc pas de ligne."""
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
    assert gs["action_logs"] == []


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


@pytest.mark.parametrize("missing_key", ["controller", "previous_controller", "player_1_oc"])
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
