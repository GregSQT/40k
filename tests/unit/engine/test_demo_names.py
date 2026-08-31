"""Tests unitaires pour engine.demo_names (DEMO_MODE=1).

Stratégie : forcer _ACTIVE=True et peupler les mappings directement
pour ne pas dépendre d'une variable d'env ou d'un fichier JSON.
"""
import importlib
from types import ModuleType
from typing import Any

import pytest


def _make_module(
    unit_names: dict[str, str] | None = None,
    weapon_names: dict[str, str] | None = None,
    ability_names: dict[str, str] | None = None,
) -> ModuleType:
    """Recharge demo_names avec _ACTIVE=True et les mappings fournis."""
    import engine.demo_names as mod

    mod._ACTIVE = True
    mod._unit_names.clear()
    mod._weapon_names.clear()
    mod._ability_names.clear()
    if unit_names:
        mod._unit_names.update(unit_names)
    if weapon_names:
        mod._weapon_names.update(weapon_names)
    if ability_names:
        mod._ability_names.update(ability_names)
    return mod


@pytest.fixture(autouse=True)
def _restore_module():
    """Remet _ACTIVE=False et vide les mappings après chaque test."""
    import engine.demo_names as mod
    yield
    mod._ACTIVE = False
    mod._unit_names.clear()
    mod._weapon_names.clear()
    mod._ability_names.clear()


# ---------------------------------------------------------------------------
# _sub
# ---------------------------------------------------------------------------

def test_sub_exact_match_has_priority():
    import engine.demo_names as mod
    mapping = {"Intercessor": "Soldier", "Space Marine Intercessor": "Generic"}
    assert mod._sub("Space Marine Intercessor", mapping) == "Generic"


def test_sub_partial_match():
    import engine.demo_names as mod
    mapping = {"Intercessor": "Soldier"}
    assert mod._sub("Assault Intercessor", mapping) == "Assault Soldier"


def test_sub_no_match_returns_unchanged():
    import engine.demo_names as mod
    assert mod._sub("Ork Boy", {"Intercessor": "Soldier"}) == "Ork Boy"


# ---------------------------------------------------------------------------
# apply_to_unit — inactive
# ---------------------------------------------------------------------------

def test_apply_noop_when_inactive():
    import engine.demo_names as mod
    mod._ACTIVE = False
    unit: dict[str, Any] = {"DISPLAY_NAME": "Space Marine"}
    mod.apply_to_unit(unit)
    assert unit["DISPLAY_NAME"] == "Space Marine"


# ---------------------------------------------------------------------------
# apply_to_unit — DISPLAY_NAME
# ---------------------------------------------------------------------------

def test_apply_display_name():
    mod = _make_module(unit_names={"Space Marine": "Soldier"})
    unit: dict[str, Any] = {"DISPLAY_NAME": "Space Marine"}
    mod.apply_to_unit(unit)
    assert unit["DISPLAY_NAME"] == "Soldier"


# ---------------------------------------------------------------------------
# apply_to_unit — armes (RNG + CC, unité et models)
# ---------------------------------------------------------------------------

def test_apply_rng_weapon():
    mod = _make_module(weapon_names={"Bolter": "Rifle"})
    unit: dict[str, Any] = {
        "DISPLAY_NAME": "X",
        "RNG_WEAPONS": [{"display_name": "Bolter", "_other": 1}],
        "CC_WEAPONS": [],
    }
    mod.apply_to_unit(unit)
    assert unit["RNG_WEAPONS"][0]["display_name"] == "Rifle"
    assert unit["RNG_WEAPONS"][0]["_other"] == 1


def test_apply_model_weapons():
    mod = _make_module(weapon_names={"Bolter": "Rifle"})
    unit: dict[str, Any] = {
        "DISPLAY_NAME": "X",
        "models": [
            {"RNG_WEAPONS": [{"display_name": "Bolter"}], "CC_WEAPONS": []},
        ],
    }
    mod.apply_to_unit(unit)
    assert unit["models"][0]["RNG_WEAPONS"][0]["display_name"] == "Rifle"


def test_apply_model_display_name():
    mod = _make_module(unit_names={"Intercessor": "Soldier", "Intercessor (Sergeant)": "Soldier (Sergeant)"})
    unit: dict[str, Any] = {
        "DISPLAY_NAME": "Intercessor",
        "models": [
            {"DISPLAY_NAME": "Intercessor (Sergeant)", "RNG_WEAPONS": [], "CC_WEAPONS": []},
            {"DISPLAY_NAME": "Intercessor", "RNG_WEAPONS": [], "CC_WEAPONS": []},
        ],
    }
    mod.apply_to_unit(unit)
    assert unit["DISPLAY_NAME"] == "Soldier"
    assert unit["models"][0]["DISPLAY_NAME"] == "Soldier (Sergeant)"
    assert unit["models"][1]["DISPLAY_NAME"] == "Soldier"


# ---------------------------------------------------------------------------
# apply_to_unit — UNIT_RULES (ne mute jamais les dicts originaux)
# ---------------------------------------------------------------------------

def test_apply_unit_rules_new_dict_not_mutated():
    mod = _make_module(ability_names={"Shock Assault": "Rush"})
    original_rule: dict[str, Any] = {"displayName": "Shock Assault", "id": "sa"}
    unit: dict[str, Any] = {
        "DISPLAY_NAME": "X",
        "UNIT_RULES": [original_rule],
    }
    mod.apply_to_unit(unit)
    assert unit["UNIT_RULES"][0]["displayName"] == "Rush"
    assert original_rule["displayName"] == "Shock Assault", "L'objet original ne doit pas être muté"


def test_apply_unit_rules_unchanged_when_no_match():
    mod = _make_module(ability_names={"Shock Assault": "Rush"})
    rule: dict[str, Any] = {"displayName": "Other Ability", "id": "oa"}
    unit: dict[str, Any] = {"DISPLAY_NAME": "X", "UNIT_RULES": [rule]}
    original_id = id(rule)
    mod.apply_to_unit(unit)
    assert unit["UNIT_RULES"][0]["displayName"] == "Other Ability"
    assert id(unit["UNIT_RULES"][0]) == original_id, "Pas de copie inutile si rien ne change"


def test_apply_unit_rules_list_always_reassigned():
    """UNIT_RULES est toujours remplacé par une nouvelle liste (même sans changement)."""
    mod = _make_module(ability_names={})
    rules_orig = [{"displayName": "X", "id": "x"}]
    unit: dict[str, Any] = {"DISPLAY_NAME": "Y", "UNIT_RULES": rules_orig}
    mod.apply_to_unit(unit)
    assert unit["UNIT_RULES"] is not rules_orig
