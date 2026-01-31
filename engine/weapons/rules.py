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
    
    def __init__(self, rules_file_path: str = None):
        """
        Initialize weapon rules registry.
        
        Args:
            rules_file_path: Path to weapon_rules.json (defaults to config/weapon_rules.json)
        """
        if rules_file_path is None:
            project_root = Path(__file__).parent.parent.parent
            rules_file_path = project_root / "config" / "weapon_rules.json"
        
        self._rules_file_path = Path(rules_file_path)
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


class WeaponRulesApplier:
    """
    Applies weapon rules during gameplay.
    
    This class will contain methods for applying specific rule logic
    (e.g., modifying shot count, damage, target validation).
    
    Phase 2 implementation - currently a placeholder.
    """
    
    def __init__(self, registry: WeaponRulesRegistry):
        """
        Initialize weapon rules applier.
        
        Args:
            registry: Weapon rules registry
        """
        self.registry = registry
    
    def apply_rules(self, weapon: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply weapon rules in a given combat context.
        
        Args:
            weapon: Weapon dict with WEAPON_RULES field
            context: Combat context (shooter, target, distance, etc.)
            
        Returns:
            Modified context with rule effects applied
            
        Note:
            Phase 2 implementation - specific rule logic to be added.
        """
        # Parse weapon rules
        parsed_rules = require_key(weapon, "_parsed_rules")
        
        # Apply each rule in order
        for rule in parsed_rules:
            context = self._apply_single_rule(rule, weapon, context)
        
        return context
    
    def _apply_single_rule(self, rule: ParsedWeaponRule, weapon: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a single weapon rule.
        
        This method will dispatch to specific rule implementations.
        
        Args:
            rule: Parsed weapon rule
            weapon: Weapon dict
            context: Combat context
            
        Returns:
            Modified context
            
        Note:
            Phase 2 implementation - specific rule handlers to be added.
        """
        # Phase 2: Add specific rule implementations here
        # Examples:
        # if rule.rule == "RAPID_FIRE":
        #     return self._apply_rapid_fire(rule, weapon, context)
        # elif rule.rule == "MELTA":
        #     return self._apply_melta(rule, weapon, context)
        
        # For now, just pass through unchanged
        return context


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

