"""Tests unitaires de _resolve_seat_seed (bot_evaluation.py).

Vérifie que agent_seat_seed=0 n'est pas écrasé par la seed globale
(le `or` falsy était le bug — remplacé par `is None`).
"""
import pytest

import ai.bot_evaluation as be
from shared.data_validation import ConfigurationError


def test_zero_seat_seed_not_overridden_by_global_seed() -> None:
    """agent_seat_seed=0 doit être retourné tel quel, pas remplacé par seed=99."""
    cfg = {"agent_seat_seed": 0, "seed": 99}
    assert be._resolve_seat_seed(cfg) == 0


def test_positive_seat_seed_returned() -> None:
    cfg = {"agent_seat_seed": 42, "seed": 99}
    assert be._resolve_seat_seed(cfg) == 42


def test_falls_back_to_global_seed_when_absent() -> None:
    """Quand agent_seat_seed est absent, on utilise seed globale."""
    cfg = {"seed": 7}
    assert be._resolve_seat_seed(cfg) == 7


def test_raises_when_neither_key_present() -> None:
    """Absence des deux clés → MissingKeyError via require_key."""
    with pytest.raises(ConfigurationError):
        be._resolve_seat_seed({})


def test_raises_on_non_int_seat_seed() -> None:
    cfg = {"agent_seat_seed": "bad"}
    with pytest.raises(TypeError, match="entier"):
        be._resolve_seat_seed(cfg)


def test_raises_on_bool_seat_seed() -> None:
    """bool est sous-classe de int mais doit être rejeté."""
    cfg = {"agent_seat_seed": True}
    with pytest.raises(TypeError, match="entier"):
        be._resolve_seat_seed(cfg)
