"""Phase de tir : un verbe d'avant le pipeline squad est REFUSÉ hors gym, et reste une erreur en gym.

`shooting_handlers.execute_action` levait `RuntimeError` (« squad path expected ») sur
`activate_unit`, `shoot`, `select_weapon`, `left_click` et `invalid`, quel que soit le siège : un
client API qui envoyait `activate_unit` en phase de tir recevait un HTTP 500, là où
`commit_move_plan` ou `advance` rendaient déjà `invalid_action_for_phase`. Jumeau du garde de
`_handle_unit_activation` (movement_handlers), qui ne lève qu'en gym.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.shooting_handlers import execute_action
from tests.unit.engine.test_move_after_shooting_decision import _gs

#: Les cinq verbes, `shoot` compris : le refus précède le prélude d'activation (STRICT AI_TURN),
#: donc il est INERTE — aucune activation démarrée ni close par un verbe refusé.
_LEGACY_VERBS = ("activate_unit", "shoot", "select_weapon", "left_click", "invalid")


def _state(*, gym: bool) -> Dict[str, Any]:
    gs = _gs(gym=gym)
    gs["config"]["gym_training_mode"] = gym
    return gs


@pytest.mark.parametrize("verb", _LEGACY_VERBS)
def test_hors_gym_le_verbe_est_refuse_comme_hors_phase(verb: str):
    gs = _state(gym=False)
    success, result = execute_action(gs, None, {"action": verb, "unitId": "1"}, gs["config"])
    assert success is False
    assert result == {"error": "invalid_action_for_phase", "action": verb, "phase": "shoot"}
    # INERTE : ni activation démarrée, ni activation close, ni tireur actif posé.
    assert gs["shoot_activation_pool"] == ["1"]
    assert "active_shooting_unit" not in gs
    assert "_shoot_activation_started" not in gs["unit_by_id"]["1"]


@pytest.mark.parametrize("verb", _LEGACY_VERBS)
def test_en_gym_le_verbe_reste_une_rupture_de_contrat(verb: str):
    gs = _state(gym=True)
    with pytest.raises(RuntimeError, match="squad path expected|squad_select_weapon expected"):
        execute_action(gs, None, {"action": verb, "unitId": "1"}, gs["config"])
