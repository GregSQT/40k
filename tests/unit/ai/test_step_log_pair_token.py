"""Verrou : token [PAIR] dans step.log pour les lignes charge et charge_fail.

is_pair=True → le formateur ajoute [PAIR] ; is_pair=False/absent → absent.

Cycle rouge→vert : commenter `base_msg += " [PAIR]"` (les deux sites, lignes ~1295
et ~1347 dans ai/step_logger.py) fait passer les deux tests _present en rouge.
"""
from __future__ import annotations

import pytest

from ai.step_logger import StepLogger


def _logger() -> StepLogger:
    sl = StepLogger.__new__(StepLogger)
    sl.enabled = True
    sl.debug_mode = False
    return sl


_CHARGE_DETAILS_BASE = {
    "target_id": "2",
    "start_pos": (5, 5),
    "end_pos": (6, 5),
    "charge_roll": 8,
    "charge_roll_initial": None,
    "is_fly_move": False,
    "ability_display_name": None,
    "target_coords": (6, 5),
}

_CHARGE_FAIL_DETAILS_BASE = {
    "target_id": "2",
    "target_coords": (10, 5),
    "charge_roll": 4,
    "charge_failed_reason": "roll_too_low",
}


# --- charge (succès) ---

def test_charge_pair_token_present():
    """is_pair=True sur une charge réussie → [PAIR] dans la ligne."""
    sl = _logger()
    msg = sl._format_replay_style_message("1", "charge", {**_CHARGE_DETAILS_BASE, "is_pair": True})
    assert "[PAIR]" in msg, f"[PAIR] attendu dans {msg!r}"


def test_charge_pair_token_absent_when_false():
    """is_pair=False sur une charge réussie → [PAIR] absent."""
    sl = _logger()
    msg = sl._format_replay_style_message("1", "charge", {**_CHARGE_DETAILS_BASE, "is_pair": False})
    assert "[PAIR]" not in msg, f"[PAIR] ne doit pas apparaître dans {msg!r}"


def test_charge_pair_token_absent_when_missing():
    """is_pair absent → [PAIR] absent (field optionnel)."""
    sl = _logger()
    details = {k: v for k, v in _CHARGE_DETAILS_BASE.items() if k != "is_pair"}
    msg = sl._format_replay_style_message("1", "charge", details)
    assert "[PAIR]" not in msg, f"[PAIR] ne doit pas apparaître dans {msg!r}"


# --- charge_fail ---

def test_charge_fail_pair_token_present():
    """is_pair=True sur une charge échouée → [PAIR] dans la ligne."""
    sl = _logger()
    msg = sl._format_replay_style_message("1", "charge_fail", {**_CHARGE_FAIL_DETAILS_BASE, "is_pair": True})
    assert "[PAIR]" in msg, f"[PAIR] attendu dans {msg!r}"


def test_charge_fail_pair_token_absent_when_false():
    """is_pair=False sur une charge échouée → [PAIR] absent."""
    sl = _logger()
    msg = sl._format_replay_style_message("1", "charge_fail", {**_CHARGE_FAIL_DETAILS_BASE, "is_pair": False})
    assert "[PAIR]" not in msg, f"[PAIR] ne doit pas apparaître dans {msg!r}"


def test_charge_fail_pair_token_absent_when_missing():
    """is_pair absent → [PAIR] absent (field optionnel, symétrie avec charge)."""
    sl = _logger()
    details = {k: v for k, v in _CHARGE_FAIL_DETAILS_BASE.items() if k != "is_pair"}
    msg = sl._format_replay_style_message("1", "charge_fail", details)
    assert "[PAIR]" not in msg, f"[PAIR] ne doit pas apparaître dans {msg!r}"
