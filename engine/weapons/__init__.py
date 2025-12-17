"""
engine.weapons - Weapon parsing, rules, and validation

This module provides weapon data and weapon rules functionality:
- Parse TypeScript armory files (single source of truth)
- Validate weapon rules (RAPID_FIRE, MELTA, etc.)
- Apply weapon rules during gameplay (Phase 2)

PUBLIC API:
  From parser.py:
    - get_armory_parser() - Get parser singleton
    - get_weapon() - Get single weapon by code
    - get_weapons() - Get multiple weapons (raises on missing)
    - ArmoryParser - Parser class
  
  From rules.py:
    - get_weapon_rules_registry() - Get rules registry singleton
    - parse_weapon_rule() - Parse "RULE_NAME:X" format
    - parse_weapon_rules() - Parse multiple rules
    - validate_weapon_rules_field() - Validate weapon WEAPON_RULES field
    - WeaponRulesRegistry - Rules registry class
    - ParsedWeaponRule - Parsed rule object
    - WeaponRulesApplier - Rule application (Phase 2)

USAGE:
  # Get weapons from armory
  from engine.weapons import get_weapon, get_armory_parser
  
  bolt_rifle = get_weapon("SpaceMarine", "BoltRifle")
  parser = get_armory_parser()
  armory = parser.get_armory("SpaceMarine")
  
  # Work with weapon rules
  from engine.weapons import get_weapon_rules_registry, parse_weapon_rule
  
  registry = get_weapon_rules_registry()
  rule = parse_weapon_rule("RAPID_FIRE:1", registry)
  print(rule.display_name)  # "Rapid Fire 1"
"""

# Parser exports
from engine.weapons.parser import (
    ArmoryParser,
    get_armory_parser,
    get_weapon,
    get_weapons,
)

# Rules exports
from engine.weapons.rules import (
    WeaponRulesRegistry,
    ParsedWeaponRule,
    WeaponRulesApplier,
    get_weapon_rules_registry,
    reset_weapon_rules_registry,
    parse_weapon_rule,
    parse_weapon_rules,
    validate_weapon_rules_field,
)

__all__ = [
    # Parser
    "ArmoryParser",
    "get_armory_parser",
    "get_weapon",
    "get_weapons",
    # Rules
    "WeaponRulesRegistry",
    "ParsedWeaponRule",
    "WeaponRulesApplier",
    "get_weapon_rules_registry",
    "reset_weapon_rules_registry",
    "parse_weapon_rule",
    "parse_weapon_rules",
    "validate_weapon_rules_field",
]

