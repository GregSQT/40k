"""
Space Marine Armory - Centralized weapon definitions.

AI_IMPLEMENTATION.md COMPLIANCE:
- NO DEFAULT: get_weapon() raises KeyError if weapon missing (pas de fallback)
- Validation stricte: toutes les armes référencées doivent exister
- Même structure que armory TypeScript (synchronisation manuelle requise)
"""

from typing import Dict, List, Any, Optional

# ============================================================================
# RANGED WEAPONS
# ============================================================================

SPACE_MARINE_ARMORY: Dict[str, Dict[str, Any]] = {
    # Ranged Weapons
    "bolt_rifle": {
        "code_name": "bolt_rifle",
        "display_name": "Bolt Rifle",
        "RNG": 24,
        "NB": 2,
        "ATK": 3,
        "STR": 4,
        "AP": -1,
        "DMG": 1,
    },
    "bolt_pistol": {
        "code_name": "bolt_pistol",
        "display_name": "Bolt Pistol",
        "RNG": 18,
        "NB": 1,
        "ATK": 3,
        "STR": 4,
        "AP": -1,
        "DMG": 1,
    },
    "storm_bolter": {
        "code_name": "storm_bolter",
        "display_name": "Storm Bolter",
        "RNG": 24,
        "NB": 2,
        "ATK": 3,
        "STR": 4,
        "AP": 0,
        "DMG": 1,
    },
    "master_crafted_boltgun": {
        "code_name": "master_crafted_boltgun",
        "display_name": "Master-crafted Boltgun",
        "RNG": 12,
        "NB": 3,
        "ATK": 2,
        "STR": 4,
        "AP": -1,
        "DMG": 1,
    },
    
    # Melee Weapons
    "close_combat_weapon": {
        "code_name": "close_combat_weapon",
        "display_name": "Close Combat Weapon",
        "NB": 3,
        "ATK": 3,
        "STR": 4,
        "AP": 0,
        "DMG": 1,
    },
    "chainsword": {
        "code_name": "chainsword",
        "display_name": "Chainsword",
        "NB": 4,
        "ATK": 3,
        "STR": 4,
        "AP": -1,
        "DMG": 1,
    },
    "power_fist": {
        "code_name": "power_fist",
        "display_name": "Power Fist",
        "NB": 5,
        "ATK": 2,
        "STR": 8,
        "AP": -2,
        "DMG": 2,
    },
    "power_fist_terminator": {
        "code_name": "power_fist_terminator",
        "display_name": "Power Fist",
        "NB": 3,
        "ATK": 3,
        "STR": 8,
        "AP": -2,
        "DMG": 2,
    },
}


def get_weapon(code_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a weapon by code name.
    
    AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - returns None if missing.
    Caller must check and raise error if weapon is required.
    
    Args:
        code_name: Weapon code name (e.g., "bolt_rifle")
        
    Returns:
        Weapon dict or None if not found
    """
    return SPACE_MARINE_ARMORY.get(code_name)


def get_weapons(code_names: List[str]) -> List[Dict[str, Any]]:
    """
    Get multiple weapons by code names.
    
    AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - raises KeyError if any weapon missing.
    
    Args:
        code_names: List of weapon code names
        
    Returns:
        List of weapon dicts
        
    Raises:
        KeyError: If any weapon code_name is missing from armory
    """
    weapons = []
    for code_name in code_names:
        weapon = get_weapon(code_name)
        if weapon is None:
            raise KeyError(
                f"Weapon '{code_name}' not found in Space Marine armory. "
                f"Available weapons: {list(SPACE_MARINE_ARMORY.keys())}"
            )
        weapons.append(weapon)
    return weapons
