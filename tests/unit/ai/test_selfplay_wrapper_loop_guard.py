"""Tests — la garde anti-boucle « P1 after » de `SelfPlayWrapper.step` compte UN step par step.

CE QUI A ETE MANQUE. La boucle « P1 after » incrementait `p1_actions_after` deux fois par
iteration (en tete, pour la garde, et en fin, apres le step moteur). La garde
`p1_actions_after > max_iterations` levait donc `RuntimeError` des `max_iterations / 2`
activations consecutives de P2, au lieu de `max_iterations` comme la boucle « P1 before » et
`BotControlledEnv._run_bot_until_not_bot_turn`.

POURQUOI AUCUN TEST NE L'A VU : aucun montage ne faisait rejouer P2 assez de fois d'affilee
apres P0 pour approcher le plafond ; le double de moteur rend un plafond de 200.
"""

from __future__ import annotations

import pytest

from ai.env_wrappers import SelfPlayWrapper
from tests.unit.ai.test_wrapper_agent_step_info import _OPPONENT_STEP_INFO, _ScriptedEngine

_AGENT_STEP_INFO = {"action": "shoot", "is_controlled_action": True, "phase": "shoot", "success": True}
_TURN_STEP_LIMIT = 4


class _CappedScriptedEngine(_ScriptedEngine):
    """Moteur scripte dont le plafond d'un tour vaut `_TURN_STEP_LIMIT`, pour l'approcher en 3 steps."""

    def get_turn_step_limit(self) -> int:
        return _TURN_STEP_LIMIT


def _wrapper_with_p2_replaying(times: int) -> tuple[SelfPlayWrapper, _CappedScriptedEngine]:
    """P0 joue, puis P2 rejoue `times` fois d'affilee avant de rendre la main a P0."""
    script = [{"info": _AGENT_STEP_INFO, "next_player": 2}]
    script += [{"info": _OPPONENT_STEP_INFO, "next_player": 2}] * (times - 1)
    script += [{"info": _OPPONENT_STEP_INFO, "next_player": 1}]
    engine = _CappedScriptedEngine(script)
    wrapper = SelfPlayWrapper(engine, frozen_model=None, update_frequency=100, allow_random_opponent=True)
    return wrapper, engine


def test_p2_replaying_under_the_cap_after_p0_is_accepted() -> None:
    """3 activations consecutives de P2 < plafond 4 : aucune garde ne doit lever."""
    wrapper, engine = _wrapper_with_p2_replaying(times=_TURN_STEP_LIMIT - 1)

    _obs, _reward, _terminated, _truncated, info = wrapper.step(4)

    assert engine.steps_taken == _TURN_STEP_LIMIT, "P0 puis 3 steps de P2 doivent tous etre joues"
    assert info["is_controlled_action"] is True


def test_p2_replaying_over_the_cap_after_p0_raises() -> None:
    """Le plafond reste effectif : 5 activations consecutives de P2 > plafond 4 → RuntimeError."""
    wrapper, _engine = _wrapper_with_p2_replaying(times=_TURN_STEP_LIMIT + 1)

    with pytest.raises(RuntimeError, match="P1 after"):
        wrapper.step(4)
