"""Psychic Hood du Librarian Terminator (feel_no_pain_vs_psychic).

Invariant : LibrarianTerminator doit porter feel_no_pain_vs_psychic threshold 4
dans ses UNIT_RULES (datasheet PDF confirmé par l'utilisateur 2026-08-31).
Verrou ROUGE/VERT sur le spec parsé par UnitRegistry et sur le getter moteur.
"""

from __future__ import annotations

import pytest

from ai.unit_registry import UnitRegistry
from engine.phase_handlers.shared_utils import _get_feel_no_pain_vs_psychic_threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_unit_rules(unit_type: str):
    return UnitRegistry().get_unit_data(unit_type)["UNIT_RULES"]


def _rule_by_id(rules, rule_id: str):
    return next((r for r in rules if r["ruleId"] == rule_id), None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_librarian_terminator_has_psychic_hood_rule():
    """UNIT_RULES du LibrarianTerminator contient feel_no_pain_vs_psychic."""
    rules = _get_unit_rules("LibrarianTerminator")
    rule = _rule_by_id(rules, "feel_no_pain_vs_psychic")
    assert rule is not None, (
        "LibrarianTerminator manque feel_no_pain_vs_psychic dans UNIT_RULES"
    )


def test_librarian_terminator_psychic_hood_threshold_4():
    """feel_no_pain_vs_psychic du LibrarianTerminator a threshold 4 (FNP 4+)."""
    rules = _get_unit_rules("LibrarianTerminator")
    rule = _rule_by_id(rules, "feel_no_pain_vs_psychic")
    assert rule is not None, "feel_no_pain_vs_psychic absent"
    assert rule.get("rule_args", {}).get("threshold") == 4, (
        f"Attendu threshold=4, obtenu {rule.get('rule_args')}"
    )


def test_get_feel_no_pain_vs_psychic_threshold_librarian_terminator():
    """Le getter moteur retourne 4 quand l'unité porte les règles du LibrarianTerminator."""
    rules = _get_unit_rules("LibrarianTerminator")
    unit = {"id": "LT1", "UNIT_RULES": rules}
    th = _get_feel_no_pain_vs_psychic_threshold(unit)
    assert th == 4, f"_get_feel_no_pain_vs_psychic_threshold attendu 4, obtenu {th}"
