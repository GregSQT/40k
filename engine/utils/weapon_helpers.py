"""
Weapon Helper Functions

MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper functions for accessing weapon data
"""

from typing import Dict, Optional, Any
from shared.data_validation import require_key


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


def get_melee_range() -> int:
    """Melee range is always 1."""
    return 1


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
    return max((require_key(w, "NB") * require_key(w, "DMG")) for w in rng_weapons)


def get_max_melee_damage(unit: Dict[str, Any]) -> float:
    """
    Get maximum possible damage from melee weapons (NB * DMG).
    Returns 0.0 if unit has no melee weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper for threat calculations.
    """
    cc_weapons = require_key(unit, "CC_WEAPONS")
    if not cc_weapons:
        return 0.0
    return max((require_key(w, "NB") * require_key(w, "DMG")) for w in cc_weapons)
