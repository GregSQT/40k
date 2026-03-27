from pathlib import Path

import pytest

from engine.weapons.parser import ArmoryParser


def test_get_armory_path_supports_canonical_and_exact_case(tmp_path: Path) -> None:
    parser = ArmoryParser()
    parser._project_root = tmp_path

    canonical = tmp_path / "frontend" / "src" / "roster" / "spaceMarine" / "armory.ts"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {\n};", encoding="utf-8")
    assert parser._get_armory_path("SpaceMarine") == canonical

    canonical.unlink()
    exact = tmp_path / "frontend" / "src" / "roster" / "SpaceMarine" / "armory.ts"
    exact.parent.mkdir(parents=True, exist_ok=True)
    exact.write_text("export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {\n};", encoding="utf-8")
    assert parser._get_armory_path("SpaceMarine") == exact


@pytest.mark.anomaly
@pytest.mark.xfail(
    reason=(
        "ANOM-001: parser regex currently truncates D6+1 to D6 in NB/DMG extraction. "
        "Expected behavior is to preserve full dice expression."
    ),
    strict=False,
)
def test_parse_armory_file_extracts_weapon_and_resolves_dice_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = ArmoryParser()
    armory_path = tmp_path / "armory.ts"
    armory_path.write_text(
        """
const TWO_D6: DiceValue = "2D6";
export const TEST_ARMORY: Record<string, Weapon> = {
  plasma: {
    code_name: "plasma",
    display_name: "Plasma Gun",
    RNG: 24,
    NB: TWO_D6,
    ATK: 3,
    STR: 8,
    AP: 2,
    DMG: D6+1,
    WEAPON_RULES: ["ASSAULT"]
  }
};
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("engine.weapons.parser.get_weapon_rules_registry", lambda: object())
    monkeypatch.setattr(
        "engine.weapons.parser.validate_weapon_rules_field",
        lambda weapon, registry: ["parsed-rule"],
    )

    weapons = parser._parse_armory_file(armory_path)
    assert "plasma" in weapons
    assert weapons["plasma"]["NB"] == "2D6"
    assert weapons["plasma"]["DMG"] == "D6+1"
    assert weapons["plasma"]["_parsed_rules"] == ["parsed-rule"]


def test_parse_armory_file_requires_weapon_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = ArmoryParser()
    armory_path = tmp_path / "armory.ts"
    armory_path.write_text(
        """
export const TEST_ARMORY: Record<string, Weapon> = {
  bolter: {
    code_name: "bolter",
    display_name: "Bolter",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: 1,
    DMG: 1
  }
};
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("engine.weapons.parser.get_weapon_rules_registry", lambda: object())
    monkeypatch.setattr("engine.weapons.parser.validate_weapon_rules_field", lambda weapon, registry: [])
    with pytest.raises(ValueError, match=r"missing required WEAPON_RULES"):
        parser._parse_armory_file(armory_path)


def test_get_weapons_raises_when_weapon_missing(tmp_path: Path) -> None:
    parser = ArmoryParser()
    parser._cache["FactionX"] = {"known": {"display_name": "Known"}}
    with pytest.raises(KeyError, match=r"Weapon 'missing' not found"):
        parser.get_weapons("FactionX", ["known", "missing"])
