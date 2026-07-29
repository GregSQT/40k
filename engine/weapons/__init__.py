"""
engine.weapons - Weapon parsing, rules, and validation

This module provides weapon data and weapon rules functionality:
- Parse TypeScript armory files (single source of truth)
- Validate weapon rules (RAPID_FIRE, MELTA, etc.)

Ce paquet CHARGE et VALIDE le catalogue de regles d'armes ; il ne les APPLIQUE pas.
L'application en jeu passe par `engine/utils/weapon_helpers` + les handlers de phase
(cf. la pierre tombale de `WeaponRulesApplier` dans rules.py, 2026-07-29).

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
    "get_weapon_rules_registry",
    "reset_weapon_rules_registry",
    "parse_weapon_rule",
    "parse_weapon_rules",
    "validate_weapon_rules_field",
]

