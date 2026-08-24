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


def test_parse_weapon_rule_refuse_un_seuil_anti_sous_2(tmp_path: Path) -> None:
    """[ANTI-X Y+] 24.03 : `Y+` est un seuil de jet de BLESSURE, donc >= 2 (05.02, un 1 non
    modifie rate toujours). `1+` passait le controle « entier > 0 » et donnait
    `crit_wound_on = 1` — CHAQUE de devenait une blessure critique reussie.

    Le refus doit tomber AU CHARGEMENT de l'armurerie : le seul controle qui existait avant se
    trouvait dans le formateur de `step.log`, sous le `except Exception` de `log_action`, et se
    manifestait donc en lignes d'attaque MANQUANTES au lieu d'une erreur.

    Le HAUT reste ouvert : un `7+` est une armurerie fautive, mais elle est ecrivable et le
    journal doit l'exposer telle quelle plutot que de la lisser.
    """
    rules_file = _write_rules_file(
        tmp_path,
        {
            "ANTI_INFANTRY": {"name": "Anti-Infantry", "description": "Y+", "has_parameter": True},
            "RAPID_FIRE": {"name": "Rapid Fire", "description": "X", "has_parameter": True},
        },
    )
    registry = rules.WeaponRulesRegistry(str(rules_file))

    with pytest.raises(ConfigurationError, match=r"\[ANTI\] threshold must be >= 2"):
        rules.parse_weapon_rule("ANTI_INFANTRY:1", registry)

    # Les bornes qui doivent RESTER acceptees : le minimum jouable, et le Y+ hors norme.
    assert rules.parse_weapon_rule("ANTI_INFANTRY:2", registry).parameter == 2
    assert rules.parse_weapon_rule("ANTI_INFANTRY:7", registry).parameter == 7
    # Le domaine est propre a [ANTI] : les autres regles parametrees gardent « entier > 0 ».
    assert rules.parse_weapon_rule("RAPID_FIRE:1", registry).parameter == 1


def test_validate_weapon_rules_field_enforces_array_and_required_key(tmp_path: Path) -> None:
    rules_file = _write_rules_file(
        tmp_path,
        {"ASSAULT": {"name": "Assault", "description": "No param", "has_parameter": False}},
    )
    registry = rules.WeaponRulesRegistry(str(rules_file))
    weapon = {"display_name": "Bolt Rifle", "code": "test_bolt_rifle", "WEAPON_RULES": ["ASSAULT"]}
    parsed = rules.validate_weapon_rules_field(weapon, registry)
    assert len(parsed) == 1
    assert parsed[0].rule == "ASSAULT"

    with pytest.raises(ConfigurationError):
        rules.validate_weapon_rules_field({"display_name": "x"}, registry)
    with pytest.raises(ConfigurationError, match=r"must be an array"):
        rules.validate_weapon_rules_field({"display_name": "x", "WEAPON_RULES": "ASSAULT"}, registry)


# 2026-07-29 — `test_weapon_rules_applier_passes_through_context` a ete SUPPRIME avec la
# classe `WeaponRulesApplier` (cf. pierre tombale dans engine/weapons/rules.py). Il
# n'assertait qu'une chose : que l'applicateur renvoyait son contexte inchange. Verrouiller
# une inaction donnait a du code mort une apparence de couverture. L'application reelle des
# regles d'armes est testee la ou elle vit : tests de `attack_sequence` / tir / melee.


def test_registry_singleton_reset() -> None:
    original = rules.get_weapon_rules_registry()
    assert original is not None
    rules.reset_weapon_rules_registry()
    fresh = rules.get_weapon_rules_registry()
    assert fresh is not None
