"""Tests unitaires — ConfigLoader.next_phase_after : séquence, phase inconnue, dernière phase."""

from __future__ import annotations

import pytest

from config_loader import get_config_loader


def _npa(phase: str) -> str:
    return get_config_loader().next_phase_after(phase)


def test_next_phase_after_sequence():
    assert _npa("deployment") == "command"
    assert _npa("command") == "move"
    assert _npa("move") == "shoot"
    assert _npa("shoot") == "charge"
    assert _npa("charge") == "fight"


def test_next_phase_after_unknown_raises():
    with pytest.raises(ValueError, match="inconnue"):
        _npa("unknown_phase")


def test_next_phase_after_last_raises():
    with pytest.raises(ValueError, match="dernière"):
        _npa("fight")
