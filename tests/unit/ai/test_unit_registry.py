import json
from pathlib import Path

import pytest

from ai.unit_registry import UnitRegistry


def _make_registry_stub() -> UnitRegistry:
    registry = UnitRegistry.__new__(UnitRegistry)
    registry.units = {}
    registry.factions = set()
    registry.roles = set()
    registry.faction_role_combinations = set()
    registry.faction_role_matrix = {}
    registry._unit_rules = {"rapid_fire": {}, "fallback_and_shoot": {}}
    return registry


def test_extract_faction_role_from_base_class_patterns() -> None:
    registry = _make_registry_stub()
    assert registry._extract_faction_role_from_base_class("SpaceMarineMeleeUnit", "spaceMarine") == ("SpaceMarine", "Melee")
    assert registry._extract_faction_role_from_base_class("TyranidRangeUnit", "tyranid") == ("Tyranid", "Ranged")
    assert registry._extract_faction_role_from_base_class("CustomSupportUnit", "myfaction") == ("Custom", "Support")
    assert registry._extract_faction_role_from_base_class("UnknownBase", "factionx") == ("Factionx", "Unknown")


def test_extract_faction_role_requires_non_empty_faction_dir_name() -> None:
    registry = _make_registry_stub()
    with pytest.raises(ValueError, match=r"faction_dir_name must be a non-empty string"):
        registry._extract_faction_role_from_base_class("UnknownBase", "   ")


def test_determine_move_type_keywords() -> None:
    registry = _make_registry_stub()
    assert registry._determine_move_type("PredatorTank", {}) == "Vehicle"
    assert registry._determine_move_type("AssaultIntercessor", {}) == "Infantry"
    assert registry._determine_move_type("AttackBike", {}) == "Bike"
    assert registry._determine_move_type("Termagant", {}) == "Infantry"


def test_get_required_explicit_fields_raise_when_missing() -> None:
    registry = _make_registry_stub()
    with pytest.raises(ValueError, match=r"TANKING_LEVEL"):
        registry._get_tanking_level("UnitA", {})
    with pytest.raises(ValueError, match=r"MOVE_TYPE"):
        registry._get_move_type("UnitA", {})
    with pytest.raises(ValueError, match=r"TARGET_TYPE"):
        registry._get_attack_target("UnitA", {}, "Melee")


def test_model_key_and_unit_data_accessors() -> None:
    registry = _make_registry_stub()
    registry.units = {"Intercessor": {"faction": "SpaceMarine", "role": "Ranged", "HP_MAX": 2}}
    registry.faction_role_matrix = {UnitRegistry.CORE_AGENT_KEY: ["Intercessor"]}

    assert registry.get_model_key("Intercessor") == UnitRegistry.CORE_AGENT_KEY
    assert registry.get_required_models() == [UnitRegistry.CORE_AGENT_KEY]
    assert registry.get_all_model_keys() == [UnitRegistry.CORE_AGENT_KEY]
    assert registry.get_units_for_model(UnitRegistry.CORE_AGENT_KEY) == ["Intercessor"]
    assert registry.get_faction_units("SpaceMarine") == ["Intercessor"]
    assert registry.get_role_units("Ranged") == ["Intercessor"]

    unit_data = registry.get_unit_data("Intercessor")
    assert unit_data == {"faction": "SpaceMarine", "role": "Ranged", "HP_MAX": 2}
    unit_data["HP_MAX"] = 999
    assert registry.units["Intercessor"]["HP_MAX"] == 2  # copie défensive

    with pytest.raises(ValueError, match=r"Unknown unit type"):
        registry.get_model_key("UnknownUnit")
    with pytest.raises(ValueError, match=r"Unknown unit type"):
        registry.get_unit_data("UnknownUnit")


def test_build_faction_role_matrix_single_agent_mode() -> None:
    registry = _make_registry_stub()
    registry.factions = {"SpaceMarine", "Tyranid"}
    registry.units = {
        "Intercessor": {"faction": "SpaceMarine", "role": "Ranged"},
        "Termagant": {"faction": "Tyranid", "role": "Ranged"},
    }
    registry._build_faction_role_matrix()
    assert UnitRegistry.CORE_AGENT_KEY in registry.faction_role_matrix
    assert sorted(registry.faction_role_matrix[UnitRegistry.CORE_AGENT_KEY]) == ["Intercessor", "Termagant"]


def test_extract_static_properties_parses_rules_weapons_and_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _make_registry_stub()
    monkeypatch.setattr(
        "engine.weapons.get_weapons",
        lambda faction, codes: [{"faction": faction, "code": c} for c in codes],
    )
    content = """
export class Intercessor extends SpaceMarineRangeUnit {
  static HP_MAX = 2;
  static MOVE = 6;
  static RNG_WEAPON_CODES = ["bolt_rifle"];
  static CC_WEAPON_CODES = ["knife"];
  static UNIT_RULES = [
    { ruleId: "rapid_fire", displayName: "Rapid Fire", grants_rule_ids: ["fallback_and_shoot"], usage: "and" }
  ];
  static UNIT_KEYWORDS = [{ keywordId: "Infantry" }];
}
"""
    props = registry._extract_static_properties(content, "spaceMarine")
    assert props["HP_MAX"] == 2
    assert props["MOVE"] == 6
    assert props["UNIT_RULES"][0]["ruleId"] == "rapid_fire"
    assert props["UNIT_KEYWORDS"][0]["keywordId"] == "Infantry"
    assert props["RNG_WEAPONS"][0]["faction"] == "SpaceMarine"
    assert props["RNG_WEAPONS"][0]["code"] == "bolt_rifle"
    assert props["CC_WEAPONS"][0]["code"] == "knife"
    assert props["selectedRngWeaponIndex"] == 0
    assert props["selectedCcWeaponIndex"] == 0


def test_extract_static_properties_requires_weapon_code_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _make_registry_stub()
    monkeypatch.setattr("engine.weapons.get_weapons", lambda faction, codes: [])
    content = """
export class Intercessor extends SpaceMarineRangeUnit {
  static HP_MAX = 2;
  static MOVE = 6;
  static CC_WEAPON_CODES = [];
}
"""
    with pytest.raises(ValueError, match=r"RNG_WEAPON_CODES"):
        registry._extract_static_properties(content, "spaceMarine")


def test_extract_static_properties_rejects_unknown_unit_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _make_registry_stub()
    monkeypatch.setattr("engine.weapons.get_weapons", lambda faction, codes: [])
    content = """
export class Intercessor extends SpaceMarineRangeUnit {
  static HP_MAX = 2;
  static MOVE = 6;
  static RNG_WEAPON_CODES = [];
  static CC_WEAPON_CODES = [];
  static UNIT_RULES = [{ ruleId: "unknown_rule", displayName: "Unknown Rule" }];
}
"""
    with pytest.raises(KeyError, match=r"Unknown unit rule id"):
        registry._extract_static_properties(content, "spaceMarine")


def test_save_registry_cache_writes_json(tmp_path: Path) -> None:
    registry = _make_registry_stub()
    registry.project_root = tmp_path
    registry.units = {"Intercessor": {"faction": "SpaceMarine"}}
    registry.factions = {"SpaceMarine"}
    registry.roles = {"Ranged"}
    registry.faction_role_combinations = {("SpaceMarine", "Ranged")}
    registry.faction_role_matrix = {UnitRegistry.CORE_AGENT_KEY: ["Intercessor"]}
    cache_file = tmp_path / "config" / "unit_registry_cache.json"

    registry.save_registry_cache(str(cache_file))
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["units"]["Intercessor"]["faction"] == "SpaceMarine"
    assert data["faction_role_matrix"][UnitRegistry.CORE_AGENT_KEY] == ["Intercessor"]
