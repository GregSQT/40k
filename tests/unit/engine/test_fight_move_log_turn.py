"""Les lignes pile-in / consolidation doivent porter le TOUR REEL.

`_append_fight_move_log` est l'emetteur UNIQUE des deux (gym via `_gym_commit_fight_move`, PvP via
`fight_handlers`). Il lisait `game_state["current_turn"]` — une cle qui n'existe dans AUCUN
game_state de ce moteur (le compteur s'appelle `turn`) — avec un repli silencieux sur 1. Resultat
mesure sur un run de 600 episodes : les 1521 lignes CONSOLIDATED de step.log sont datees T1, quel
que soit le round.

Le repli est exactement la valeur par defaut anti-erreur que T1 interdit : il rendait le defaut
invisible. Le contrat est desormais `require_key` — absence de `turn` = erreur explicite.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.fight_handlers import _append_fight_move_log
from shared.data_validation import ConfigurationError


def _game_state(**extra: Any) -> Dict[str, Any]:
    gs: Dict[str, Any] = {"action_logs": [], "action_log_seq": 0, "turn": 4}
    gs.update(extra)
    return gs


def _unit() -> Dict[str, Any]:
    return {"id": "7", "player": 2}


@pytest.mark.parametrize("kind, verb", [("pile_in", "PILED IN"), ("consolidation", "CONSOLIDATED")])
def test_fight_move_log_carries_the_real_turn(kind: str, verb: str) -> None:
    gs = _game_state()
    _append_fight_move_log(
        gs, _unit(), kind=kind, from_col=10, from_row=11, to_col=12, to_row=11,
        move_details=[{"modelId": "7#0", "fromCol": 10, "fromRow": 11, "toCol": 12, "toRow": 11}],
    )
    entry = gs["action_logs"][-1]
    assert entry["turn"] == 4, entry
    assert entry["type"] == kind
    assert verb in entry["message"]


def test_fight_move_log_refuses_a_state_without_turn() -> None:
    """T1 : pas de valeur par defaut pour masquer une donnee manquante."""
    gs = _game_state()
    del gs["turn"]
    with pytest.raises(ConfigurationError):
        _append_fight_move_log(
            gs, _unit(), kind="consolidation", from_col=1, from_row=1, to_col=2, to_row=1,
            move_details=[],
        )


def test_fight_move_log_stores_captured_models_segment() -> None:
    """Le segment [MODELS:] capturé immédiatement après commit_move est stocké dans l'entrée.

    Sans cette capture, `_build_step_log_details` appelle `_models_segment_for_unit` au moment
    du flush — APRÈS que pile-in ET consolidation aient toutes deux été commitées dans le même
    `_fight_v11_gym_settle`. Le segment pile-in contiendrait alors les positions
    post-consolidation, et l'analyzer mesurerait une distance pile-in+consolidation qu'il
    comparerait au budget pile-in (3") et signalerait en violation.
    """
    gs = _game_state()
    captured_seg = "[MODELS: 7#0@(5,5) 7#1@(5,6)]"
    _append_fight_move_log(
        gs, _unit(), kind="pile_in",
        from_col=4, from_row=4, to_col=5, to_row=4,
        move_details=[{"modelId": "7#0", "fromCol": 4, "fromRow": 4, "toCol": 5, "toRow": 4}],
        models_segment=captured_seg,
    )
    entry = gs["action_logs"][-1]
    assert entry.get("models_segment") == captured_seg


def test_build_step_log_details_prefers_captured_models_segment() -> None:
    """Le segment pré-capturé dans raw_log doit primer sur _models_segment_for_unit au flush.

    Sans la branche `if 'models_segment' in raw_log`, _build_step_log_details appellerait
    _models_segment_for_unit — qui lit les positions COURANTES, soit post-consolidation pour
    une ligne pile-in émise juste avant dans le même _fight_v11_gym_settle. Ce test tombe si
    la branche est retirée : _Bridge renvoie une valeur distincte, la comparaison échoue.
    """
    from engine.w40k_core import W40KEngine

    class _Bridge:
        def _models_segment_for_unit(self, unit_id: str) -> str:
            return "[MODELS: LIVE_POST_CONSO]"

    captured = "[MODELS: 7#0@(4,4)]"
    details = W40KEngine._build_step_log_details.__get__(_Bridge())(
        {"unitId": "7", "turn": 3, "models_segment": captured},
        3,
    )
    assert details["models_segment"] == captured, (
        "_build_step_log_details a appelé _models_segment_for_unit au lieu de lire "
        "raw_log['models_segment'] : la branche if a été retirée"
    )


def test_build_step_log_details_falls_back_to_live_segment_when_absent() -> None:
    """Sans models_segment dans raw_log, _models_segment_for_unit est appelé (branche else)."""
    from engine.w40k_core import W40KEngine

    class _Bridge:
        def _models_segment_for_unit(self, unit_id: str) -> str:
            return "[MODELS: LIVE]"

    details = W40KEngine._build_step_log_details.__get__(_Bridge())(
        {"unitId": "7", "turn": 2},
        2,
    )
    assert details["models_segment"] == "[MODELS: LIVE]"
