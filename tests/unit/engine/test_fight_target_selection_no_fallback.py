"""Sélection de cible en mêlée — les erreurs de config remontent, pas de repli silencieux.

Contexte (V11 §9.4, audit §0.19.1) : `_ai_select_fight_target` enveloppait tout son corps dans
un `try/except Exception` qui renvoyait `valid_targets[0]`. Il avalait notamment les DEUX
`require_key` (`reward_configs`, config de l'agent combattant) et le `ValueError` de
`get_model_key` sur un `unitType` inconnu — c'est-à-dire exactement les erreurs explicites que
la règle projet « aucun fallback pour masquer une erreur » impose de laisser remonter.

Aggravant : la seule trace du repli était `add_console_log`, qui est un **no-op tant que
`debug_mode` est faux** (cf. game_utils) — donc invisible en entraînement normal. Le symptôme
observable était un ciblage de mêlée dégradé (toujours la première cible du pool), sans
message.

Ces tests étaient ROUGES avant le retrait du `except` : la fonction retournait `"2"` au lieu de
lever (les deux require_key lèvent ConfigurationError, sous-classe de RuntimeError).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.fight_handlers import _ai_select_fight_target
from shared.data_validation import ConfigurationError


def _unit(uid: str, unit_type: str = "Intercessor") -> Dict[str, Any]:
    return {"id": uid, "unitType": unit_type}


def _game_state(reward_configs: Dict[str, Any], fighter_type: str = "Intercessor") -> Dict[str, Any]:
    fighter = _unit("1", fighter_type)
    return {
        "unit_by_id": {"1": fighter, "2": _unit("2"), "3": _unit("3")},
        "reward_configs": reward_configs,
    }


def test_missing_reward_configs_key_raises_instead_of_first_target():
    """`reward_configs` sans la clé de l'agent combattant → KeyError explicite, PAS un repli.

    Avant le fix : le `except Exception` renvoyait `valid_targets[0]` ("2") en silence.
    """
    gs = _game_state(reward_configs={})  # la clé de l'agent est absente
    with pytest.raises(ConfigurationError, match="CoreAgent"):
        _ai_select_fight_target(gs, "1", ["2", "3"])


def test_missing_reward_configs_entirely_raises():
    """`reward_configs` absent du game_state → erreur explicite (premier require_key)."""
    gs = _game_state(reward_configs={})
    del gs["reward_configs"]
    with pytest.raises(ConfigurationError, match="reward_configs"):
        _ai_select_fight_target(gs, "1", ["2", "3"])


def test_unknown_unit_type_raises_instead_of_first_target():
    """`unitType` inconnu du registry → ValueError de `get_model_key`, PAS un repli."""
    gs = _game_state(reward_configs={"CoreAgent": {}}, fighter_type="CeTypeNExistePas")
    with pytest.raises(ValueError, match="Unknown unit type"):
        _ai_select_fight_target(gs, "1", ["2", "3"])


def test_empty_target_pool_raises_instead_of_empty_string():
    """Pool vide → erreur explicite, PAS la sentinelle `""`.

    Les 4 sites d'appel gardent déjà ce cas en amont : la branche était morte, et son `return ""`
    aurait produit un identifiant d'unité vide en silence si elle avait été atteinte.
    """
    gs = _game_state(reward_configs={"CoreAgent": {}})
    with pytest.raises(ValueError, match="pool de cibles VIDE"):
        _ai_select_fight_target(gs, "1", [])


def test_target_missing_from_unit_by_id_raises():
    """Cible du pool absente de `unit_by_id` → erreur explicite, PAS un `continue` silencieux.

    Le pool est construit depuis `units_cache` : une cible qui y figure sans être dans
    `unit_by_id` est une désynchronisation d'index. Avant le fix, elle était sautée sans bruit.
    """
    gs = _game_state(reward_configs={"CoreAgent": {}})
    with pytest.raises(ValueError, match="absente de unit_by_id"):
        _ai_select_fight_target(gs, "1", ["2", "42"])  # "42" n'est pas dans unit_by_id


class _ScriptedRewardMapper:
    """RewardMapper de test : score piloté par id de cible, et compte ses appels."""

    scores: Dict[str, float] = {}
    calls: List[str] = []

    def __init__(self, _config):
        pass

    def get_shooting_priority_reward(self, _unit, target, _all_targets, _flag, _gs):
        tid = str(target["id"])
        type(self).calls.append(tid)
        return type(self).scores[tid]


@pytest.fixture
def scripted_mapper(monkeypatch):
    _ScriptedRewardMapper.calls = []
    monkeypatch.setattr("ai.reward_mapper.RewardMapper", _ScriptedRewardMapper)
    return _ScriptedRewardMapper


def test_selects_highest_scoring_target_not_the_first(scripted_mapper):
    """La cible retenue est celle de score MAXIMAL, pas la première du pool.

    Verrouille le remplacement de la boucle à sentinelle par `max(..., key=...)` : un bug qui
    renverrait `valid_targets[0]` passerait inaperçu sans ce test.
    """
    scripted_mapper.scores = {"2": 1.0, "3": 9.0}
    gs = _game_state(reward_configs={"CoreAgent": {}})
    assert _ai_select_fight_target(gs, "1", ["2", "3"]) == "3"


def test_selection_is_stable_across_identical_calls(scripted_mapper):
    """Déterminisme (§8.1) : deux appels identiques rendent la même cible."""
    scripted_mapper.scores = {"2": 4.0, "3": 7.0}
    gs = _game_state(reward_configs={"CoreAgent": {}})
    first = _ai_select_fight_target(gs, "1", ["2", "3"])
    second = _ai_select_fight_target(gs, "1", ["2", "3"])
    assert first == second == "3"


def test_tie_keeps_the_first_of_the_pool(scripted_mapper):
    """Égalité de score → PREMIER du pool, comme l'ancien `>` strict (non-régression)."""
    scripted_mapper.scores = {"2": 5.0, "3": 5.0}
    gs = _game_state(reward_configs={"CoreAgent": {}})
    assert _ai_select_fight_target(gs, "1", ["2", "3"]) == "2"
    assert _ai_select_fight_target(gs, "1", ["3", "2"]) == "3"


def test_each_target_is_scored_exactly_once(scripted_mapper):
    """Le refactor supprime le double `get_unit_by_id` : un seul scoring par cible."""
    scripted_mapper.scores = {"2": 1.0, "3": 2.0}
    gs = _game_state(reward_configs={"CoreAgent": {}})
    _ai_select_fight_target(gs, "1", ["2", "3"])
    assert sorted(scripted_mapper.calls) == ["2", "3"], scripted_mapper.calls


def test_unknown_fighter_unit_still_raises_value_error():
    """Non-régression : l'erreur explicite déjà présente AVANT le try n'est pas touchée."""
    gs = _game_state(reward_configs={"CoreAgent": {}})
    with pytest.raises(ValueError, match="Unit not found for fight target selection"):
        _ai_select_fight_target(gs, "99", ["2", "3"])
