"""Verrous du namespace `03_eval/` : un tag par (scenario holdout, adversaire NOMME).

Deux invariants, l'un ne remplacant pas l'autre :
  1. `BOT_DISPLAY_NAMES` est une table EXPLICITE — elle doit donc etre confrontee aux classes
     reelles de `ai/evaluation_bots`, sinon elle derive sans que rien ne tombe.
  2. `_log_scenario_scores` emet un scalaire par bot et par scenario holdout, sous le nom de
     classe et non sous la cle courte. La version precedente emettait UN scalaire par scenario
     valant son `worst_bot_score` : la courbe changeait d'adversaire d'une evaluation a l'autre.
"""

from typing import Any, Dict, List, Tuple

import pytest

from ai.bot_registry import bot_classes
from ai.training_callbacks import (
    ALL_BOT_NAMES,
    BOT_DISPLAY_NAMES,
    BotEvaluationCallback,
)


def test_display_names_cover_exactly_the_evaluation_bots() -> None:
    assert set(BOT_DISPLAY_NAMES) == set(ALL_BOT_NAMES)


@pytest.mark.parametrize("bot_key", sorted(BOT_DISPLAY_NAMES))
def test_display_name_is_the_real_class_of_the_registered_bot(bot_key: str) -> None:
    """Le nom affiche designe la classe REELLEMENT enregistree pour cette cle.

    ⚠️ Ce test cherchait ses classes dans `ai/evaluation_bots` uniquement. Depuis que le panel
    refondu vit dans `ai/bot_doctrines.py`, ce module n'est plus la
    reference : c'est `ai/bot_registry.bot_classes()`, qui est aussi ce que l'evaluation
    instancie. Le verrou est donc PLUS FORT qu'avant — il ne prouve plus qu'une classe du meme
    nom existe quelque part, mais que le nom affiche est celui de la classe reellement jouee.

    `random` est traite a part : `RandomBot` n'est pas dans `bot_classes()` (il ne prend pas de
    `randomness`, cf. la docstring du registre) alors qu'il produit bien une ligne de resultat.
    """
    class_name = BOT_DISPLAY_NAMES[bot_key]
    if bot_key == "random":
        from ai.evaluation_bots import RandomBot

        assert class_name == RandomBot.__name__
        return
    registered = bot_classes().get(bot_key)
    assert registered is not None, (
        f"BOT_DISPLAY_NAMES['{bot_key}'] n'a aucune classe enregistree dans ai/bot_registry"
    )
    assert class_name == registered.__name__, (
        f"BOT_DISPLAY_NAMES['{bot_key}'] = '{class_name}' mais le registre enregistre "
        f"'{registered.__name__}'"
    )


class _RecordingLogger:
    """Doublure du logger SB3 : `record` accumule, `dump` ne fait rien."""

    def __init__(self) -> None:
        self.records: List[Tuple[str, float]] = []

    def record(self, key: str, value: float) -> None:
        self.records.append((key, float(value)))

    def dump(self, step: int) -> None:
        pass


class _FakeModel:
    def __init__(self) -> None:
        self.logger = _RecordingLogger()
        self.num_timesteps = 4242


def _results() -> Dict[str, Any]:
    """Deux scenarios holdout + un scenario d'entrainement (qui ne doit RIEN emettre en 03_eval)."""
    return {
        "scenario_scores": {
            "holdout_regular_bot-01": {"combined": 0.4, "worst_bot_score": 0.2},
            "holdout_hard_bot-02": {"combined": 0.1, "worst_bot_score": 0.0},
            "training_bot-01": {"combined": 0.9, "worst_bot_score": 0.8},
        },
        "scenario_bot_stats": {
            "holdout_regular_bot-01": {
                "defensive": {"win_rate": 0.25},
                "tactical": {"win_rate": 0.75},
            },
            "holdout_hard_bot-02": {
                "defensive": {"win_rate": 0.0},
                "tactical": {"win_rate": 0.5},
            },
            "training_bot-01": {"defensive": {"win_rate": 1.0}},
        },
    }


def _log(results: Dict[str, Any]) -> List[Tuple[str, float]]:
    callback = BotEvaluationCallback.__new__(BotEvaluationCallback)
    model = _FakeModel()
    callback.model = model  # type: ignore[assignment]
    BotEvaluationCallback._log_scenario_scores(callback, results)
    return model.logger.records


def test_one_curve_per_holdout_scenario_and_bot_named_after_its_class() -> None:
    records = dict(_log(_results()))
    eval_keys = {key: value for key, value in records.items() if key.startswith("03_eval/")}
    assert eval_keys == {
        "03_eval/holdout_regular_bot_01/DefensiveBot": 0.25,
        "03_eval/holdout_regular_bot_01/TacticalBot": 0.75,
        "03_eval/holdout_hard_bot_02/DefensiveBot": 0.0,
        "03_eval/holdout_hard_bot_02/TacticalBot": 0.5,
    }


def test_legacy_namespace_is_gone() -> None:
    """`1_evals/` ne doit plus etre ecrit nulle part."""
    assert not [key for key, _ in _log(_results()) if key.startswith("1_evals")]


def test_unknown_bot_key_raises_instead_of_logging_the_short_key() -> None:
    """Un bot absent de la table doit LEVER — pas retomber sur sa cle courte (T1)."""
    results = _results()
    results["scenario_bot_stats"]["holdout_regular_bot-01"]["mystery"] = {"win_rate": 0.5}
    with pytest.raises(Exception):
        _log(results)
