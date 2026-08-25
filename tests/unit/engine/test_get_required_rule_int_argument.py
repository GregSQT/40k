"""Tests unitaires pour _get_required_rule_int_argument (shooting_handlers).

Trois invariants :
- effet absent → ValueError
- valeur ≤ 0   → ValueError
- valeur valide → retour correct
"""

import pytest
from engine.phase_handlers.shooting_handlers import _get_required_rule_int_argument


def _make_unit(rule_args: dict) -> dict:
    return {
        "id": "unit-test",
        "UNIT_RULES": [
            {
                "ruleId": "move_after_shooting",
                "displayName": "Test Rule",
                "rule_args": rule_args,
            }
        ],
    }


def _make_unit_no_effect() -> dict:
    return {
        "id": "unit-no-effect",
        "UNIT_RULES": [],
    }


class TestGetRequiredRuleIntArgument:
    def test_effect_absent_raises_value_error(self):
        unit = _make_unit_no_effect()
        with pytest.raises(ValueError, match="move_after_shooting"):
            _get_required_rule_int_argument(unit, "move_after_shooting", "distance")

    def test_value_zero_raises_value_error(self):
        unit = _make_unit({"distance": 0})
        with pytest.raises(ValueError, match="must be > 0"):
            _get_required_rule_int_argument(unit, "move_after_shooting", "distance")

    def test_value_negative_raises_value_error(self):
        unit = _make_unit({"distance": -3})
        with pytest.raises(ValueError, match="must be > 0"):
            _get_required_rule_int_argument(unit, "move_after_shooting", "distance")

    def test_valid_value_returns_correctly(self):
        unit = _make_unit({"distance": 6})
        result = _get_required_rule_int_argument(unit, "move_after_shooting", "distance")
        assert result == 6
