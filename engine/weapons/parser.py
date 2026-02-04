"""
parser.py - Parse TypeScript armory files to extract weapon definitions.

SINGLE SOURCE OF TRUTH: Weapons are only declared in TypeScript armory files.
Python reads and parses these files at runtime - no duplicate Python armory needed.

AI_IMPLEMENTATION.md COMPLIANCE:
- NO DEFAULT: Raises error if weapon missing
- Validation stricte: All referenced weapons must exist
- Single source of truth: TypeScript armory files are canonical
- Weapon rules validation: All WEAPON_RULES validated on load (fail-fast)
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from engine.weapons.rules import get_weapon_rules_registry, validate_weapon_rules_field


class ArmoryParser:
    """Parse TypeScript armory files to extract weapon definitions."""
    
    def __init__(self):
        """Initialize armory parser with cache."""
        self._cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._project_root = Path(__file__).parent.parent.parent
    
    def _get_armory_path(self, faction: str) -> Path:
        """Get path to TypeScript armory file for faction."""
        # Normalize faction name (SpaceMarine -> spaceMarine, Tyranid -> tyranid)
        faction_lower = faction[0].lower() + faction[1:] if faction else faction
        
        armory_path = self._project_root / "frontend" / "src" / "roster" / faction_lower / "armory.ts"
        
        if not armory_path.exists():
            raise FileNotFoundError(
                f"Armory file not found for faction '{faction}': {armory_path}"
            )
        
        return armory_path
    
    def _parse_armory_file(self, armory_path: Path) -> Dict[str, Dict[str, Any]]:
        """
        Parse TypeScript armory file and extract all weapon definitions.
        
        AI_IMPLEMENTATION.md COMPLIANCE: Validates WEAPON_RULES on load (fail-fast).
        """
        with open(armory_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        weapons = {}
        
        # Get weapon rules registry for validation
        rules_registry = get_weapon_rules_registry()
        
        # Match weapon definitions in the ARMORY object
        # Pattern: weapon_code: { properties }
        # Matches multi-line weapon definitions like:
        # bolt_rifle: {
        #   code_name: "bolt_rifle",
        #   display_name: "Bolt Rifle",
        #   RNG: 24,
        #   ...
        # },
        
        # Find the ARMORY object definition
        armory_match = re.search(
            r'export const \w+_ARMORY:\s*Record<string,\s*Weapon>\s*=\s*\{(.*?)\n\};',
            content,
            re.DOTALL
        )
        
        if not armory_match:
            return weapons
        
        armory_content = armory_match.group(1)
        
        # Match individual weapon entries
        # Pattern: weapon_code: { ... },
        weapon_pattern = r'(\w+):\s*\{([^}]+)\}'
        
        for match in re.finditer(weapon_pattern, armory_content):
            weapon_code = match.group(1)
            weapon_body = match.group(2)
            
            weapon = {}
            
            # Extract weapon properties
            # display_name: "value"
            display_name_match = re.search(r'display_name:\s*["\']([^"\']+)["\']', weapon_body)
            if display_name_match:
                weapon['display_name'] = display_name_match.group(1)

            # Optional COMBI_WEAPON group key
            combi_match = re.search(r'COMBI_WEAPON:\s*["\']([^"\']+)["\']', weapon_body)
            if combi_match:
                weapon['COMBI_WEAPON'] = combi_match.group(1)
            
            # Numeric properties: RNG, NB, ATK, STR, AP, DMG
            # NB/DMG can be dice expressions (D3, D6) in addition to ints
            for prop in ['RNG', 'NB', 'ATK', 'STR', 'AP', 'DMG']:
                if prop in ['NB', 'DMG']:
                    prop_match = re.search(rf'{prop}:\s*(D[36]|-?\d+)', weapon_body)
                    if prop_match:
                        raw_value = prop_match.group(1)
                        if raw_value in ['D3', 'D6']:
                            weapon[prop] = raw_value
                        else:
                            weapon[prop] = int(raw_value)
                else:
                    prop_match = re.search(rf'{prop}:\s*(-?\d+)', weapon_body)
                    if prop_match:
                        weapon[prop] = int(prop_match.group(1))
            
            # WEAPON_RULES array: ["RAPID_FIRE:1", "ASSAULT"]
            # Pattern: WEAPON_RULES: ["rule1", "rule2", ...]
            weapon_rules_match = re.search(r'WEAPON_RULES:\s*\[([^\]]*)\]', weapon_body)
            weapon_name = weapon.get('display_name', weapon_code)
            if not weapon_rules_match:
                raise ValueError(f"Weapon '{weapon_name}' missing required WEAPON_RULES (use [] if none)")
            rules_content = weapon_rules_match.group(1)
            # Extract individual rule strings from quotes
            rule_strings = re.findall(r'["\']([^"\']+)["\']', rules_content)
            weapon['WEAPON_RULES'] = rule_strings
            
            # VALIDATE WEAPON_RULES: Parse and validate all rules (fail-fast)
            try:
                parsed_rules = validate_weapon_rules_field(weapon, rules_registry)
                # Cache parsed rules on weapon for performance
                weapon['_parsed_rules'] = parsed_rules
            except Exception as e:
                # Add context about which weapon failed
                weapon_name = weapon.get('display_name', weapon_code)
                raise ValueError(
                    f"Invalid WEAPON_RULES in weapon '{weapon_name}' ({weapon_code}) "
                    f"from {armory_path}: {str(e)}"
                ) from e
            
            weapons[weapon_code] = weapon
        
        return weapons
    
    def get_armory(self, faction: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all weapons for a faction by parsing TypeScript armory file.
        Results are cached for performance.
        
        Args:
            faction: Faction name (e.g., "SpaceMarine", "Tyranid")
        
        Returns:
            Dictionary mapping weapon codes to weapon data
        """
        # Check cache first
        if faction in self._cache:
            return self._cache[faction]
        
        # Parse armory file
        armory_path = self._get_armory_path(faction)
        weapons = self._parse_armory_file(armory_path)
        
        # Cache result
        self._cache[faction] = weapons
        
        return weapons
    
    def get_weapon(self, faction: str, code_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a single weapon by code name.
        
        Args:
            faction: Faction name (e.g., "SpaceMarine", "Tyranid")
            code_name: Weapon code name (e.g., "bolt_rifle")
        
        Returns:
            Weapon dict or None if not found
        """
        armory = self.get_armory(faction)
        return armory.get(code_name)
    
    def get_weapons(self, faction: str, code_names: List[str]) -> List[Dict[str, Any]]:
        """
        Get multiple weapons by code names.
        
        AI_IMPLEMENTATION.md COMPLIANCE: NO DEFAULT - raises KeyError if any weapon missing.
        
        Args:
            faction: Faction name (e.g., "SpaceMarine", "Tyranid")
            code_names: List of weapon code names
        
        Returns:
            List of weapon dicts
        
        Raises:
            KeyError: If any weapon code_name is missing from armory
        """
        armory = self.get_armory(faction)
        weapons = []
        
        for code_name in code_names:
            weapon = armory.get(code_name)
            if weapon is None:
                available_weapons = list(armory.keys())
                raise KeyError(
                    f"Weapon '{code_name}' not found in {faction} armory. "
                    f"Available weapons: {available_weapons}"
                )
            weapons.append(weapon)
        
        return weapons


# Global singleton instance
_armory_parser = None


def get_armory_parser() -> ArmoryParser:
    """Get global armory parser singleton."""
    global _armory_parser
    if _armory_parser is None:
        _armory_parser = ArmoryParser()
    return _armory_parser


def get_weapon(faction: str, code_name: str) -> Optional[Dict[str, Any]]:
    """
    Get a weapon by code name.
    Convenience function that uses global parser instance.
    """
    return get_armory_parser().get_weapon(faction, code_name)


def get_weapons(faction: str, code_names: List[str]) -> List[Dict[str, Any]]:
    """
    Get multiple weapons by code names.
    Convenience function that uses global parser instance.
    
    Raises KeyError if any weapon is missing.
    """
    return get_armory_parser().get_weapons(faction, code_names)

