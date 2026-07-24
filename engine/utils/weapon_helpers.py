"""
Weapon Helper Functions

MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper functions for accessing weapon data
"""

from typing import Dict, Optional, Any
from shared.data_validation import require_key
from engine.combat_utils import expected_dice_value


def weapon_has_rule(weapon: Dict[str, Any], rule_id: str) -> bool:
    """True si l'arme declare la regle `rule_id` dans WEAPON_RULES.

    Gere les trois formes d'entree rencontrees en runtime : chaine 'NAME',
    chaine parametree 'NAME:param', ou objet ParsedWeaponRule (attribut `.rule`).
    Comparaison insensible a la casse. Aucun repli masquant : WEAPON_RULES est
    exige (require_key) et doit etre une liste, sinon erreur explicite.
    """
    rules = require_key(weapon, "WEAPON_RULES")
    if not isinstance(rules, list):
        raise TypeError(
            f"WEAPON_RULES must be a list, got {type(rules).__name__} "
            f"for weapon {weapon.get('display_name', weapon.get('NAME'))}"
        )
    target = rule_id.strip().upper()
    for entry in rules:
        if hasattr(entry, "rule"):
            name = getattr(entry, "rule")
        elif isinstance(entry, str):
            name = entry.split(":", 1)[0]
        else:
            raise TypeError(
                f"Unsupported WEAPON_RULES entry type: {type(entry).__name__} ({entry!r})"
            )
        if str(name).strip().upper() == target:
            return True
    return False


def get_selected_ranged_weapon(unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get currently selected ranged weapon."""
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing RNG_WEAPONS: {unit}")
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return None
    idx = require_key(unit, "selectedRngWeaponIndex")
    if idx < 0 or idx >= len(rng_weapons):
        raise IndexError(f"Invalid selectedRngWeaponIndex {idx} for unit {unit['id']}")
    return rng_weapons[idx]


def get_selected_melee_weapon(unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get currently selected melee weapon."""
    if "CC_WEAPONS" not in unit:
        raise KeyError(f"Unit missing CC_WEAPONS: {unit}")
    cc_weapons = require_key(unit, "CC_WEAPONS")
    if not cc_weapons:
        return None
    idx = require_key(unit, "selectedCcWeaponIndex")
    if idx < 0 or idx >= len(cc_weapons):
        raise IndexError(f"Invalid selectedCcWeaponIndex {idx} for unit {unit['id']}")
    return cc_weapons[idx]


def get_max_ranged_range(unit: Dict[str, Any]) -> int:
    """Get maximum range of all ranged weapons."""
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return 0
    return max(require_key(w, "RNG") for w in rng_weapons)


def get_max_ranged_damage(unit: Dict[str, Any]) -> float:
    """
    Get maximum possible damage from ranged weapons (NB * DMG).
    Returns 0.0 if unit has no ranged weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper for threat calculations.
    """
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        return 0.0
    return max((expected_dice_value(require_key(w, "NB"), "max_ranged_nb") *
                expected_dice_value(require_key(w, "DMG"), "max_ranged_dmg"))
               for w in rng_weapons)


def get_max_melee_damage(unit: Dict[str, Any]) -> float:
    """
    Get maximum possible damage from melee weapons (NB * DMG).
    Returns 0.0 if unit has no melee weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper for threat calculations.
    """
    cc_weapons = require_key(unit, "CC_WEAPONS")
    if not cc_weapons:
        return 0.0
    return max((expected_dice_value(require_key(w, "NB"), "max_melee_nb") *
                expected_dice_value(require_key(w, "DMG"), "max_melee_dmg"))
               for w in cc_weapons)
