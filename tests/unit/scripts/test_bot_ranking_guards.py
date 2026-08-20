"""Gardes de validation d'entree de scripts/bot_ranking.py."""
from __future__ import annotations

import sys

import pytest

from tests._chargeur_script import charger_script


@pytest.fixture(scope="module")
def bot_ranking():
    return charger_script("scripts/bot_ranking.py")


def test_bots_dupliques_levent_avant_tout_jeu(bot_ranking, monkeypatch):
    """--bots control,control leve ValueError avant que played atteigne 0."""
    eval_params = {"randomness": 0.0, "weights": {"control": 1.0, "tactical": 1.0}}
    monkeypatch.setattr(bot_ranking, "get_config_loader", lambda: None)
    monkeypatch.setattr(bot_ranking, "_load_bot_eval_params", lambda *a, **kw: eval_params)
    monkeypatch.setattr(bot_ranking, "require_key", lambda d, k: d[k])
    monkeypatch.setattr(sys, "argv", ["bot_ranking.py", "--bots", "control,control", "--episodes", "1"])
    with pytest.raises(ValueError, match="dupliques"):
        bot_ranking.main()
