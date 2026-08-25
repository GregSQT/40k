"""_get_unit_rule_arg — extraction d'argument de règle paramétrée.

Cas couverts :
- règle absente → None
- arg_key absent → ValueError
- mauvais type → TypeError
- valeur valide → retour correct
"""
import pytest

from engine.phase_handlers.shared_utils import _get_unit_rule_arg


def _unit_with_rule(rule_id: str, rule_args=None, *, unit_id: str = "U1"):
    """Unité minimale portant une règle avec effect_rule_ids = [rule_id]."""
    entry = {"ruleId": rule_id, "effect_rule_ids": [rule_id]}
    if rule_args is not None:
        entry["rule_args"] = rule_args
    return {"id": unit_id, "UNIT_RULES": [entry]}


def _unit_without_rule(*, unit_id: str = "U1"):
    return {"id": unit_id, "UNIT_RULES": []}


# ── règle absente → None ────────────────────────────────────────────────────

def test_rule_absent_returns_none():
    unit = _unit_without_rule()
    assert _get_unit_rule_arg(unit, "deadly_demise", "value", (int, str)) is None


# ── arg_key absent → ValueError ─────────────────────────────────────────────

def test_arg_key_missing_raises_value_error():
    unit = _unit_with_rule("feel_no_pain", rule_args={})
    with pytest.raises(ValueError, match="threshold.*missing"):
        _get_unit_rule_arg(unit, "feel_no_pain", "threshold", (int,))


def test_rule_args_not_dict_raises_value_error():
    unit = _unit_with_rule("feel_no_pain")
    with pytest.raises(ValueError, match="rule_args"):
        _get_unit_rule_arg(unit, "feel_no_pain", "threshold", (int,))


# ── mauvais type → TypeError ────────────────────────────────────────────────

def test_wrong_type_raises_type_error():
    unit = _unit_with_rule("deadly_demise", rule_args={"value": 3.5})
    with pytest.raises(TypeError, match="int/str"):
        _get_unit_rule_arg(unit, "deadly_demise", "value", (int, str))


def test_wrong_type_int_expected():
    unit = _unit_with_rule("feel_no_pain", rule_args={"threshold": "5"})
    with pytest.raises(TypeError, match="int"):
        _get_unit_rule_arg(unit, "feel_no_pain", "threshold", (int,))


# ── valeur valide → retour correct ──────────────────────────────────────────

def test_valid_int_returned():
    unit = _unit_with_rule("feel_no_pain", rule_args={"threshold": 5})
    assert _get_unit_rule_arg(unit, "feel_no_pain", "threshold", (int,)) == 5


def test_valid_str_returned():
    unit = _unit_with_rule("deadly_demise", rule_args={"value": "D3"})
    assert _get_unit_rule_arg(unit, "deadly_demise", "value", (int, str)) == "D3"


def test_valid_int_in_multi_type():
    unit = _unit_with_rule("deadly_demise", rule_args={"value": 1})
    assert _get_unit_rule_arg(unit, "deadly_demise", "value", (int, str)) == 1
