"""
Tyranid Armory - Centralized weapon definitions.

AI_IMPLEMENTATION.md COMPLIANCE:
- NO DEFAULT: get_weapon() raises KeyError if weapon missing (pas de fallback)
- Validation stricte: toutes les armes référencées doivent exister
- Même structure que armory TypeScript (synchronisation manuelle requise)
"""

from typing import Dict, List, Any, Optional

# ============================================================================
# TYRANID WEAPONS
# ============================================================================

TYRANID_ARMORY: Dict[str, Dict[str, Any]] = {
    # Ranged Weapons
    "fleshborer": {
        "code_name": "fleshborer",
        "display_name": "Fleshborer",
        "RNG": 18,
        "NB": 1,
        "ATK": 4,
        "STR": 5,
        "AP": 0,
        "DMG": 1,
    },
    "venom_cannon": {
        "code_name": "venom_cannon",
        "display_name": "Venom Cannon",
        "RNG": 24,
        "NB": 6,
        "ATK": 4,
        "STR": 7,
        "AP": -2,
        "DMG": 1,
    },
    
    # Melee Weapons
    "rending_claws": {
        "code_name": "rending_claws",
        "display_name": "Rending Claws",
        "NB": 4,
        "ATK": 2,
        "STR": 4,
        "AP": -2,
        "DMG": 1,
    },
    "rending_claws_prime": {
        "code_name": "rending_claws_prime",
        "display_name": "Rending Claws",
        "NB": 5,
        "ATK": 2,
        "STR": 6,
        "AP": -2,
        "DMG": 2,
    },
    "scything_talons": {
        "code_name": "scything_talons",
        "display_name": "Scything Talons",
        "NB": 3,
        "ATK": 4,
        "STR": 3,
        "AP": -1,
        "DMG": 1,
    },
    "flesh_hooks": {
        "code_name": "flesh_hooks",
        "display_name": "Flesh Hooks",
        "NB": 1,
        "ATK": 4,
        "STR": 3,
        "AP": 0,
        "DMG": 1,
    },
    "monstrous_scything_talons": {
        "code_name": "monstrous_scything_talons",
        "display_name": "Monstrous Scything Talons",
        "NB": 6,
        "ATK": 4,
        "STR": 9,
        "AP": -2,
        "DMG": 3,
    },
}


def get_weapon(code_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a weapon by code name.
    
    AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - returns None if missing.
    Caller must check and raise error if weapon is required.
    
    Args:
        code_name: Weapon code name (e.g., "fleshborer")
        
    Returns:
        Weapon dict or None if not found
    """
    return TYRANID_ARMORY.get(code_name)


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
                f"Weapon '{code_name}' not found in Tyranid armory. "
                f"Available weapons: {list(TYRANID_ARMORY.keys())}"
            )
        weapons.append(weapon)
    return weapons
