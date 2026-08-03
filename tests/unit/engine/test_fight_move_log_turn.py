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
