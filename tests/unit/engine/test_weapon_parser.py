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
    validated: list[dict] = []

    def _spy_validate(weapon, registry):
        validated.append(weapon)
        return ["parsed-rule"]

    monkeypatch.setattr("engine.weapons.parser.validate_weapon_rules_field", _spy_validate)

    weapons = parser._parse_armory_file(armory_path)
    assert "plasma" in weapons
    assert weapons["plasma"]["NB"] == "2D6"
    assert weapons["plasma"]["DMG"] == "D6+1"

    # Le fail-fast est l'APPEL de validation : il doit rester, sur chaque arme.
    assert [w["display_name"] for w in validated] == ["Plasma Gun"]
    # ...mais son retour ne doit PAS etre re-stocke sur l'arme. `_parsed_rules` etait le canal
    # d'entree du defunt WeaponRulesApplier ; la clé n'a aucun lecteur et ne doit pas revenir
    # (elle forcerait api_server a l'exclure de nouveau pour ne pas la faire fuiter). Ce test
    # rougit si quelqu'un remet un cache sur le dict d'arme.
    assert "_parsed_rules" not in weapons["plasma"]
    assert not [k for k in weapons["plasma"] if k.startswith("_parsed")]


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
