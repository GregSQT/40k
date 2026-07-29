"""
rules.py - Weapon Rules System

Handles parsing, validation, and application of weapon rules (e.g., RAPID_FIRE, MELTA, BLAST).

AI_IMPLEMENTATION.md COMPLIANCE:
- NO DEFAULT: Raises error if weapon references non-existent rule
- Fail-fast: Validates all rules on engine initialization
- No hidden values: All rule definitions in config/weapon_rules.json
- UPPERCASE naming: WEAPON_RULES field

Design: Documentation/WEAPON_RULES_DESIGN.md
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from shared.data_validation import require_key, require_present, ConfigurationError


class WeaponRulesRegistry:
    """
    Registry of all available weapon rules loaded from config/weapon_rules.json.
    
    Single source of truth for weapon rule definitions.
    """
    
    def __init__(self, rules_file_path: Optional[str] = None):
        """
        Initialize weapon rules registry.
        
        Args:
            rules_file_path: Path to weapon_rules.json (defaults to config/weapon_rules.json)
        """
        if rules_file_path is None:
            project_root = Path(__file__).parent.parent.parent
            resolved_path: Path = project_root / "config" / "weapon_rules.json"
        else:
            resolved_path = Path(rules_file_path)

        self._rules_file_path = resolved_path
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._load_rules()
    
    def _load_rules(self):
        """Load weapon rules from JSON file."""
        if not self._rules_file_path.exists():
            raise ConfigurationError(
                f"Weapon rules file not found: {self._rules_file_path}"
            )
        
        with open(self._rules_file_path, 'r', encoding='utf-8') as f:
            self._rules = json.load(f)
        
        # Validate rule structure
        for rule_name, rule_def in self._rules.items():
            self._validate_rule_definition(rule_name, rule_def)
    
    def _validate_rule_definition(self, rule_name: str, rule_def: Dict[str, Any]):
        """
        Validate that a rule definition has required fields.
        
        Args:
            rule_name: Rule identifier (e.g., "RAPID_FIRE")
            rule_def: Rule definition dict
            
        Raises:
            ConfigurationError: If rule definition is invalid
        """
        # Required fields per WEAPON_RULES_DESIGN.md
        require_key(rule_def, "name")
        require_key(rule_def, "description")
        require_key(rule_def, "has_parameter")
        
        # Validate has_parameter is boolean
        if not isinstance(rule_def["has_parameter"], bool):
            raise ConfigurationError(
                f"Weapon rule '{rule_name}': 'has_parameter' must be boolean, "
                f"got {type(rule_def['has_parameter']).__name__}"
            )
    
    def get_rule(self, rule_name: str) -> Dict[str, Any]:
        """
        Get rule definition by name.
        
        Args:
            rule_name: Rule identifier (e.g., "RAPID_FIRE")
            
        Returns:
            Rule definition dict
            
        Raises:
            ConfigurationError: If rule doesn't exist
        """
        return require_key(self._rules, rule_name)
    
    def rule_exists(self, rule_name: str) -> bool:
        """Check if a rule exists in the registry."""
        return rule_name in self._rules
    
    def get_all_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get all rule definitions."""
        return self._rules.copy()


class ParsedWeaponRule:
    """
    Represents a parsed weapon rule with its parameter.
    
    Example: "RAPID_FIRE:1" -> ParsedWeaponRule(rule="RAPID_FIRE", parameter=1, definition={...})
    """
    
    def __init__(self, rule: str, parameter: Optional[int], definition: Dict[str, Any]):
        self.rule = rule
        self.parameter = parameter
        self.definition = definition
    
    def __repr__(self):
        if self.parameter is not None:
            return f"ParsedWeaponRule({self.rule}:{self.parameter})"
        return f"ParsedWeaponRule({self.rule})"
    
    @property
    def display_name(self) -> str:
        """Get formatted display name for UI (e.g., 'Rapid Fire 1')."""
        name = self.definition["name"]
        if self.parameter is not None:
            return f"{name} {self.parameter}"
        return name
    
    @property
    def description(self) -> str:
        """Get rule description, substituting X with parameter if present."""
        desc = self.definition["description"]
        if self.parameter is not None:
            # Replace X with actual parameter value
            desc = desc.replace(" X ", f" {self.parameter} ")
        return desc


def parse_weapon_rule(rule_string: str, registry: WeaponRulesRegistry) -> ParsedWeaponRule:
    """
    Parse weapon rule string in format "RULE_NAME" or "RULE_NAME:X".
    
    Args:
        rule_string: Rule string (e.g., "RAPID_FIRE:1" or "ASSAULT")
        registry: Weapon rules registry for validation
        
    Returns:
        ParsedWeaponRule object
        
    Raises:
        ConfigurationError: If rule is invalid or missing required parameter
        
    Examples:
        >>> parse_weapon_rule("RAPID_FIRE:1", registry)
        ParsedWeaponRule(RAPID_FIRE:1)
        
        >>> parse_weapon_rule("ASSAULT", registry)
        ParsedWeaponRule(ASSAULT)
        
        >>> parse_weapon_rule("INVALID_RULE", registry)
        ConfigurationError: Required key 'INVALID_RULE' is missing from mapping.
    """
    require_present(rule_string, "rule_string")
    
    # Split on colon to extract rule name and optional parameter
    parts = rule_string.split(":")
    rule_name = parts[0].strip()
    
    # Parse parameter if present
    parameter = None
    if len(parts) > 1:
        try:
            parameter = int(parts[1].strip())
        except ValueError:
            raise ConfigurationError(
                f"Invalid weapon rule parameter in '{rule_string}': "
                f"parameter must be an integer"
            )
        
        if parameter <= 0:
            raise ConfigurationError(
                f"Invalid weapon rule parameter in '{rule_string}': "
                f"parameter must be positive, got {parameter}"
            )
    
    # Validate rule exists in registry
    rule_def = registry.get_rule(rule_name)
    
    # Validate parameter requirement
    if rule_def["has_parameter"] and parameter is None:
        raise ConfigurationError(
            f"Weapon rule '{rule_name}' requires a parameter. "
            f"Use format '{rule_name}:X' (e.g., '{rule_name}:1')"
        )
    
    if not rule_def["has_parameter"] and parameter is not None:
        raise ConfigurationError(
            f"Weapon rule '{rule_name}' does not accept parameters. "
            f"Use format '{rule_name}' without ':X'"
        )
    
    return ParsedWeaponRule(rule_name, parameter, rule_def)


def parse_weapon_rules(rule_strings: List[str], registry: WeaponRulesRegistry) -> List[ParsedWeaponRule]:
    """
    Parse multiple weapon rule strings.
    
    Args:
        rule_strings: List of rule strings (e.g., ["RAPID_FIRE:1", "ASSAULT"])
        registry: Weapon rules registry for validation
        
    Returns:
        List of ParsedWeaponRule objects
        
    Raises:
        ConfigurationError: If any rule is invalid
    """
    parsed_rules = []
    for rule_string in rule_strings:
        parsed_rule = parse_weapon_rule(rule_string, registry)
        parsed_rules.append(parsed_rule)
    
    return parsed_rules


def validate_weapon_rules_field(weapon: Dict[str, Any], registry: WeaponRulesRegistry) -> List[ParsedWeaponRule]:
    """
    Validate WEAPON_RULES field on a weapon definition.
    
    This should be called during weapon loading to ensure fail-fast validation.
    
    Args:
        weapon: Weapon dict with optional WEAPON_RULES field
        registry: Weapon rules registry for validation
        
    Returns:
        List of ParsedWeaponRule objects (empty if no rules)
        
    Raises:
        ConfigurationError: If WEAPON_RULES field is invalid
    """
    # WEAPON_RULES is required (use [] if none)
    rule_strings = require_key(weapon, "WEAPON_RULES")
    
    # Validate field type
    if not isinstance(rule_strings, list):
        weapon_name = weapon.get("display_name", weapon.get("name", "unknown"))
        raise ConfigurationError(
            f"Weapon '{weapon_name}': WEAPON_RULES must be an array, "
            f"got {type(rule_strings).__name__}"
        )
    
    # Parse and validate all rules
    return parse_weapon_rules(rule_strings, registry)


# 2026-07-29 — la classe `WeaponRulesApplier` (et ses methodes `apply_rules` /
# `_apply_single_rule`) a ete SUPPRIMEE. Elle se presentait comme l'applicateur des regles
# d'armes en jeu ("Phase 2 implementation"), mais `_apply_single_rule` n'a jamais recu le
# moindre handler : elle renvoyait `context` inchange, et aucun code de production ne l'a
# jamais instanciee. Seul son test l'appelait, en verrouillant justement le fait qu'elle ne
# faisait rien — ce qui lui donnait une apparence de vie.
#
# POURQUOI ELLE EST MORTE : son objet a ete livre ailleurs, sans qu'on revienne la cabler.
# L'application effective des regles d'armes passe aujourd'hui par
# `engine/utils/weapon_helpers.weapon_has_rule` / `weapon_rule_parameter`, consommes par
# `engine/phase_handlers/attack_sequence.py` (SUSTAINED_HITS, LETHAL_HITS,
# DEVASTATING_WOUNDS, TWIN_LINKED, TORRENT, HAZARDOUS), `shooting_handlers.py`,
# `fight_handlers.py` et `engine/observation_weapon_profiles.py`.
#
# OU ALLER AUJOURD'HUI : pour APPLIQUER une regle -> `weapon_helpers` + le handler de phase
# concerne. Ce module-ci ne fait que CHARGER et VALIDER le catalogue
# (`config/weapon_rules.json`) au chargement des armes : registre, parsing, fail-fast.
# Ne pas reintroduire ici un applicateur pass-through.


# Global singleton registry
_weapon_rules_registry: Optional[WeaponRulesRegistry] = None


def get_weapon_rules_registry() -> WeaponRulesRegistry:
    """
    Get global weapon rules registry singleton.
    
    Returns:
        WeaponRulesRegistry instance
    """
    global _weapon_rules_registry
    if _weapon_rules_registry is None:
        _weapon_rules_registry = WeaponRulesRegistry()
    return _weapon_rules_registry


def reset_weapon_rules_registry():
    """Reset global registry (useful for testing)."""
    global _weapon_rules_registry
    _weapon_rules_registry = None

