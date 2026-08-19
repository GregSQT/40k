"""Tests unitaires — _next_phase_after : séquence, phase inconnue, dernière phase."""

from __future__ import annotations

import pytest

from tests.unit.engine._config_helpers import build_armageddon_engine


@pytest.fixture(scope="module")
def engine():
    return build_armageddon_engine(seed=0)


def test_next_phase_after_sequence(engine):
    assert engine._next_phase_after("move") == "shoot"
    assert engine._next_phase_after("shoot") == "charge"
    assert engine._next_phase_after("charge") == "fight"


def test_next_phase_after_unknown_raises(engine):
    with pytest.raises(ValueError, match="inconnue"):
        engine._next_phase_after("unknown_phase")


def test_next_phase_after_last_raises(engine):
    with pytest.raises(ValueError, match="dernière"):
        engine._next_phase_after("fight")
