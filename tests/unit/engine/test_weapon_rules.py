import json
from pathlib import Path

import pytest

from engine.weapons import rules
from shared.data_validation import ConfigurationError


def _write_rules_file(tmp_path: Path, payload: dict) -> Path:
    rules_file = tmp_path / "weapon_rules.json"
    rules_file.write_text(json.dumps(payload), encoding="utf-8")
    return rules_file


def test_registry_loads_valid_rules_file(tmp_path: Path) -> None:
    rules_file = _write_rules_file(
        tmp_path,
        {
            "RAPID_FIRE": {"name": "Rapid Fire", "description": "Extra shots at X", "has_parameter": True},
            "ASSAULT": {"name": "Assault", "description": "Can advance and shoot", "has_parameter": False},
        },
    )
    registry = rules.WeaponRulesRegistry(str(rules_file))
    assert registry.rule_exists("RAPID_FIRE") is True
    assert registry.get_rule("ASSAULT")["name"] == "Assault"


def test_registry_rejects_invalid_has_parameter_type(tmp_path: Path) -> None:
    rules_file = _write_rules_file(
        tmp_path,
        {"BAD": {"name": "Bad", "description": "x", "has_parameter": "yes"}},
    )
    with pytest.raises(ConfigurationError, match=r"must be boolean"):
        rules.WeaponRulesRegistry(str(rules_file))


def test_parse_weapon_rule_validates_parameter_presence_and_format(tmp_path: Path) -> None:
    rules_file = _write_rules_file(
        tmp_path,
        {
            "RAPID_FIRE": {"name": "Rapid Fire", "description": "X", "has_parameter": True},
            "ASSAULT": {"name": "Assault", "description": "No param", "has_parameter": False},
        },
    )
    registry = rules.WeaponRulesRegistry(str(rules_file))

    parsed = rules.parse_weapon_rule("RAPID_FIRE:2", registry)
    assert parsed.rule == "RAPID_FIRE"
    assert parsed.parameter == 2
    assert parsed.display_name == "Rapid Fire 2"

    with pytest.raises(ConfigurationError, match=r"requires a parameter"):
        rules.parse_weapon_rule("RAPID_FIRE", registry)
    with pytest.raises(ConfigurationError, match=r"does not accept parameters"):
        rules.parse_weapon_rule("ASSAULT:1", registry)
    with pytest.raises(ConfigurationError, match=r"must be an integer"):
        rules.parse_weapon_rule("RAPID_FIRE:abc", registry)
    with pytest.raises(ConfigurationError, match=r"must be positive"):
        rules.parse_weapon_rule("RAPID_FIRE:0", registry)


def test_validate_weapon_rules_field_enforces_array_and_required_key(tmp_path: Path) -> None:
    rules_file = _write_rules_file(
        tmp_path,
        {"ASSAULT": {"name": "Assault", "description": "No param", "has_parameter": False}},
    )
    registry = rules.WeaponRulesRegistry(str(rules_file))
    weapon = {"display_name": "Bolt Rifle", "WEAPON_RULES": ["ASSAULT"]}
    parsed = rules.validate_weapon_rules_field(weapon, registry)
    assert len(parsed) == 1
    assert parsed[0].rule == "ASSAULT"

    with pytest.raises(ConfigurationError):
        rules.validate_weapon_rules_field({"display_name": "x"}, registry)
    with pytest.raises(ConfigurationError, match=r"must be an array"):
        rules.validate_weapon_rules_field({"display_name": "x", "WEAPON_RULES": "ASSAULT"}, registry)


def test_weapon_rules_applier_passes_through_context() -> None:
    registry = type("R", (), {})()
    applier = rules.WeaponRulesApplier(registry)
    dummy_rule = rules.ParsedWeaponRule("ASSAULT", None, {"name": "Assault", "description": "", "has_parameter": False})
    context = {"shots": 2}
    result = applier.apply_rules({"_parsed_rules": [dummy_rule]}, context)
    assert result == context


def test_registry_singleton_reset() -> None:
    original = rules.get_weapon_rules_registry()
    assert original is not None
    rules.reset_weapon_rules_registry()
    fresh = rules.get_weapon_rules_registry()
    assert fresh is not None
