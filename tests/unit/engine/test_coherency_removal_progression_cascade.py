"""Retrait pour cohérence 03.03 (fin de tour) : la DERNIÈRE désignation rend la progression
joueur/tour, et cette transition doit être EXÉCUTÉE par la cascade des deux points d'entrée.

`select_coherency_removal` sortait de `_process_semantic_action` (API) et de
`_process_squad_action` (gym / bot PvE) AVANT leur cascade de phases : la progression était jouée
(joueur courant basculé) mais la phase restait `fight`. Le `advance_phase` « pool vide » qui
suivait (client ou `step()`) refaisait alors la fin de phase de combat POUR L'AUTRE JOUEUR —
mesuré : P1 finit son tour 1, l'état passe directement au tour 2 de P1, le tour 1 de P2 n'est
jamais joué.

Même motif que la reprise hazard (`test_charge_impact_hazard_cascade.py`).
"""
from __future__ import annotations

from typing import Any, Dict

from engine.agent_decision import clear_pending_agent_decision
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)


def _incoherent_squad_cfg() -> Dict[str, Any]:
    """Trois figurines : `1#0` (20,20) isolée, `1#1`/`1#2` (30,20)/(31,20) — retirer `1#0`
    rend l'escouade cohérente."""
    squad = _unit_cfg(1, 1, 20, 20)
    squad["HP_CUR"] = 3
    squad["HP_MAX"] = 3
    squad["models"] = [
        {"col": 20, "row": 20, "VALUE": 100},
        {"col": 30, "row": 20, "VALUE": 100},
        {"col": 31, "row": 20, "VALUE": 100},
    ]
    return squad


def _engine_end_of_turn(*, gym: bool) -> W40KEngine:
    """Fin de la phase de combat de P1 (tour 1), machine V11 vide, désignation de cohérence
    armée sur l'escouade 1 (queue vide derrière)."""
    eng = _make_engine(_base_config([_incoherent_squad_cfg(), _unit_cfg(2, 2, 40, 40)]))
    gs = eng.game_state
    gs["gym_training_mode"] = gym
    if not gym:
        clear_pending_agent_decision(gs)
        gs["player_types"] = {"1": "human", "2": "human"}
        gs["current_mode_code"] = "pvp"
        eng.current_mode_code = "pvp"
    gs["phase"] = "fight"
    gs["current_player"] = 1
    gs["turn"] = 1
    gs["fight_subphase"] = None
    gs["pending_coherency_removal"] = {"squad_id": "1"}
    gs["pending_coherency_removal_v11"] = True
    gs["pending_coherency_removal_queue"] = []
    return eng


def _assert_progressed_to_player_2(gs: Dict[str, Any], result: Dict[str, Any]) -> None:
    assert "1#0" not in gs["models_cache"]
    assert result["coherency_removal_complete"] is True
    assert gs.get("pending_coherency_removal") is None
    assert gs["current_player"] == 2 and gs["turn"] == 1, (gs["current_player"], gs["turn"])
    assert gs["phase"] != "fight", (
        f"phase {gs['phase']!r} : la progression a basculé le joueur sans quitter la phase de "
        "combat — le prochain advance_phase la rejouerait pour P2"
    )


def test_api_la_derniere_designation_traverse_la_cascade():
    eng = _engine_end_of_turn(gym=False)
    gs = eng.game_state

    ok, result = eng.execute_semantic_action({"action": "select_coherency_removal", "model_id": "1#0"})

    assert ok is True, result
    _assert_progressed_to_player_2(gs, result)


def test_gym_la_derniere_designation_traverse_la_cascade():
    eng = _engine_end_of_turn(gym=True)
    gs = eng.game_state

    ok, result = eng._process_squad_action({"action": "select_coherency_removal", "model_id": "1#0"})

    assert ok is True, result
    _assert_progressed_to_player_2(gs, result)
    # Le rattrapage « pool vide » du step suivant ne rejoue plus la fin de phase de combat :
    # P2 joue bien son tour 1.
    assert gs["current_player"] == 2 and gs["turn"] == 1


def test_une_designation_non_finale_ne_progresse_pas():
    """Retirer `1#1` laisse `1#0` (20,20) et `1#2` (31,20) : l'escouade reste incohérente, elle
    est réarmée et la progression attend — la phase de combat et le joueur courant ne bougent
    pas."""
    eng = _engine_end_of_turn(gym=False)
    gs = eng.game_state

    ok, result = eng.execute_semantic_action({"action": "select_coherency_removal", "model_id": "1#1"})

    assert ok is True, result
    assert result["awaiting_coherency_removal"] is True
    assert gs["pending_coherency_removal"] == {"squad_id": "1"}
    assert gs["phase"] == "fight" and gs["current_player"] == 1
