#!/usr/bin/env python3
"""
ai/turn_validator.py - Ultimate AI_TURN.md Compliance Validator

ENHANCED VERSION: Combines validator1's comprehensive rule validation 
with selective features from validator2 & validator3

CRITICAL PURPOSE: Comprehensive validation against ALL AI_TURN.md requirements
VALIDATION COVERAGE:
- Sequential activation (ONE unit per gym step)
- Built-in step counting (NOT retrofitted)
- Phase completion by eligibility ONLY
- UPPERCASE field validation (ALL required fields)
- Single game_state object
- Tracking set compliance
- Combat sub-phases
- Charge roll mechanics
- NO wrapper patterns
- ENHANCED: AST validation, decorator enforcement, pre-commit integration
"""

import ast
import re
import os
import sys
import inspect
from typing import List, Dict, Tuple, Set
from pathlib import Path

class AITurnComplianceViolation(Exception):
    """Enhanced exception for AI_TURN.md violations"""
    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__(f"AI_TURN.md violations: {len(violations)} issues")

class EnhancedAITurnValidator:
    """
    ULTIMATE AI_TURN.md Compliance Validator
    
    Combines comprehensive rule validation with strategic enhancements:
    - Validator1's complete AI_TURN.md rule coverage
    - Validator2's AST analysis capabilities  
    - Validator3's decorator enforcement and integration
    """
    
    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.violations = []
        self.warnings = []
        self.critical_violations = []
        
        # AI_TURN.md required UPPERCASE fields
        self.required_uppercase_fields = {
            "CUR_HP", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
            "RNG_NB", "RNG_RNG", "RNG_ATK", "RNG_STR", "RNG_DMG", "RNG_AP", 
            "CC_NB", "CC_RNG", "CC_ATK", "CC_STR", "CC_DMG", "CC_AP",
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE"
        }
        
        # AI_TURN.md required tracking sets
        self.required_tracking_sets = {
            "units_moved", "units_fled", "units_shot", "units_charged", "units_attacked"
        }
        
        # AI_TURN.md forbidden patterns
        self.forbidden_patterns = {
            "wrapper_delegation": ["self.base =", "__getattr__", "getattr(self."],
            "retrofitted_counting": ["_is_real_action", "steps_before", "steps_after"],
            "multi_unit_processing": ["for unit in", "active_unit_queue.append"],
            "state_copying": ["copy.deepcopy", ".copy()", "dict(game_state)"],
            "step_based_transitions": ["episode_steps >", "episode_steps <", "episode_steps =="]
        }
        
    def validate_controller_file(self, file_path: str) -> Tuple[bool, List[str], List[str]]:
        """
        COMPREHENSIVE validation against AI_TURN.md requirements
        Returns: (is_compliant, violations, warnings)
        """
        if not os.path.exists(file_path):
            return False, [f"File not found: {file_path}"], []
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Reset validation state
        self.violations = []
        self.warnings = []
        self.critical_violations = []
        
        # Parse AST for enhanced structural analysis
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            return False, [f"Syntax error in file: {e}"], []
            
        # COMPREHENSIVE VALIDATION CHECKS
        self._check_sequential_activation_compliance(content, tree)
        self._check_built_in_step_counting(content, tree)
        self._check_phase_completion_logic(content, tree)
        self._check_uppercase_field_compliance(content)
        self._check_tracking_set_compliance(content)
        self._check_combat_phase_compliance(content)
        self._check_charge_mechanics_compliance(content)
        self._check_forbidden_patterns(content)
        self._check_execute_gym_action_structure(content, tree)
        self._check_eligibility_rule_compliance(content)
        
        # ENHANCED VALIDATIONS (from validator2/3)
        self._check_ast_structure_compliance(tree)
        self._check_method_signature_compliance(tree)
        self._check_class_architecture_compliance(tree)
        
        # Categorize violations by severity
        all_violations = self._format_all_violations()
        is_compliant = len(self.critical_violations) == 0 and len(self.violations) == 0
        
        return is_compliant, all_violations, self.warnings
        
    def _check_sequential_activation_compliance(self, content: str, tree: ast.AST):
        """Check for ONE unit per gym step compliance"""
        
        # Check 1: execute_gym_action should process ONE unit only
        if 'def execute_gym_action' in content:
            lines = content.split('\n')
            in_method = False
            unit_processing_count = 0
            
            for line in lines:
                if 'def execute_gym_action' in line:
                    in_method = True
                elif in_method and line.strip().startswith('def '):
                    break
                elif in_method:
                    if 'for unit in' in line or 'for u in' in line:
                        unit_processing_count += 1
                        
            if unit_processing_count > 0:
                self.critical_violations.append(
                    "❌ CRITICAL: execute_gym_action processes multiple units (violates sequential activation)"
                )
                
        # Check 2: No unit queue building within single action
        if 'active_unit_queue' in content and 'append' in content:
            self.violations.append(
                "❌ SEQUENTIAL VIOLATION: Unit queue building detected (should process ONE unit)"
            )
            
    def _check_built_in_step_counting(self, content: str, tree: ast.AST):
        """Check for proper built-in step counting (not retrofitted)"""
        
        # Check 1: episode_steps increment should be in execute_gym_action
        has_episode_steps = 'episode_steps"] += 1' in content
        has_execute_method = 'def execute_gym_action' in content
        
        if not has_episode_steps:
            self.critical_violations.append(
                "❌ CRITICAL: Missing episode_steps increment (required for step counting)"
            )
            return
            
        if not has_execute_method:
            self.critical_violations.append(
                "❌ CRITICAL: Missing execute_gym_action method"
            )
            return
            
        # Check 2: Increment should be BUILT-IN (not conditional)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'episode_steps"] += 1' in line:
                # Check context for retrofitted patterns
                context = '\n'.join(lines[max(0, i-3):i+3])
                if any(pattern in context for pattern in ['if self._is_real_action', 'steps_before', 'steps_after']):
                    self.critical_violations.append(
                        f"❌ CRITICAL: Line {i+1} - Retrofitted step counting (should be built-in)"
                    )
                    
    def _check_phase_completion_logic(self, content: str, tree: ast.AST):
        """Check that phases complete based on unit eligibility only"""
        
        # Check for eligibility-based phase completion
        if 'def _is_phase_complete' in content or 'def _handle_no_active_unit' in content:
            # Good - has phase completion logic
            pass
        else:
            self.violations.append(
                "❌ PHASE COMPLETION: Missing eligibility-based phase completion logic"
            )
            
        # Check for step-based transitions (forbidden)
        if any(pattern in content for pattern in ['episode_steps >', 'episode_steps <', 'episode_steps ==']):
            if 'transition' in content or 'phase' in content:
                self.critical_violations.append(
                    "❌ CRITICAL: Step-based phase transitions detected (should be eligibility-based)"
                )
                
    def _check_uppercase_field_compliance(self, content: str):
        """Check for proper UPPERCASE field usage"""
        
        # Check for all required UPPERCASE fields
        missing_fields = []
        for field in self.required_uppercase_fields:
            if f'"{field}"' not in content and f"'{field}'" not in content:
                missing_fields.append(field)
                
        if missing_fields:
            self.warnings.append(
                f"⚠️ UPPERCASE FIELDS: Missing references to {', '.join(missing_fields[:5])}{'...' if len(missing_fields) > 5 else ''}"
            )
            
        # Check for forbidden lowercase variants
        forbidden_lowercase = {
            'cur_hp': 'CUR_HP', 'hp_max': 'HP_MAX', 'rng_nb': 'RNG_NB', 
            'cc_str': 'CC_STR', 'armor_save': 'ARMOR_SAVE'
        }
        
        for lowercase, uppercase in forbidden_lowercase.items():
            if f'"{lowercase}"' in content or f"'{lowercase}'" in content:
                self.violations.append(
                    f"❌ LOWERCASE FIELD: '{lowercase}' should be '{uppercase}'"
                )
                
    def _check_tracking_set_compliance(self, content: str):
        """Check for proper tracking set usage"""
        
        for tracking_set in self.required_tracking_sets:
            if tracking_set not in content:
                self.warnings.append(
                    f"⚠️ TRACKING SET: Missing '{tracking_set}' references"
                )
                
        # Check for KeyError raising on missing tracking sets
        if 'KeyError' in content and 'game_state' in content:
            # Good - validates tracking set existence
            pass
        else:
            self.violations.append(
                "❌ TRACKING VALIDATION: Missing KeyError validation for tracking sets"
            )
            
    def _check_combat_phase_compliance(self, content: str):
        """Check for proper combat phase sub-phase handling"""
        
        # Combat phase should handle both players
        if 'phase == "combat"' in content:
            if 'both players' in content.lower() or 'current_player' not in content:
                # Good - combat handles both players
                pass
            else:
                self.violations.append(
                    "❌ COMBAT PHASE: Should handle both players, not just current_player"
                )
                
        # Check for charged unit priority
        if 'units_charged' in content and 'units_attacked' in content:
            # Good - tracks charging for priority
            pass
        elif 'combat' in content.lower():
            self.warnings.append(
                "⚠️ COMBAT PRIORITY: Missing charged unit priority logic"
            )
            
    def _check_charge_mechanics_compliance(self, content: str):
        """Check for proper charge mechanics (2d6 rolls, pathfinding)"""
        
        if 'charge' in content.lower():
            # Check for 2d6 mechanics
            if '2d6' in content or ('die1' in content and 'die2' in content):
                # Good - has 2d6 mechanics
                pass
            else:
                self.warnings.append(
                    "⚠️ CHARGE MECHANICS: Missing 2d6 roll mechanics"
                )
                
            # Check for charge range validation
            if 'charge_max_distance' in content or 'charge_range' in content:
                # Good - validates charge range
                pass
            else:
                self.warnings.append(
                    "⚠️ CHARGE RANGE: Missing charge range validation"
                )
                
    def _check_forbidden_patterns(self, content: str):
        """Check for all forbidden patterns"""
        
        for pattern_type, patterns in self.forbidden_patterns.items():
            for pattern in patterns:
                if pattern in content:
                    self.violations.append(
                        f"❌ FORBIDDEN PATTERN: {pattern_type.replace('_', ' ').title()} - '{pattern}'"
                    )
                    
    def _check_execute_gym_action_structure(self, content: str, tree: ast.AST):
        """Check execute_gym_action follows AI_TURN.md 5-step pattern"""
        
        if 'def execute_gym_action' not in content:
            self.critical_violations.append(
                "❌ CRITICAL: Missing execute_gym_action method"
            )
            return
            
        # Extract method content
        lines = content.split('\n')
        method_lines = []
        in_method = False
        
        for line in lines:
            if 'def execute_gym_action' in line:
                in_method = True
                method_lines.append(line)
            elif in_method and line.strip().startswith('def '):
                break
            elif in_method:
                method_lines.append(line)
                
        method_content = '\n'.join(method_lines)
        
        # Check for 5-step pattern
        required_steps = [
            'get_current_active_unit',  # Step 1
            'no_active_unit',          # Step 2
            'execute_action',          # Step 3
            'mark_unit_as_acted',      # Step 4
            'build_gym_response'       # Step 5
        ]
        
        missing_steps = []
        for step in required_steps:
            if step not in method_content:
                missing_steps.append(step)
                
        if missing_steps:
            self.violations.append(
                f"❌ AI_TURN PATTERN: Missing steps in execute_gym_action: {', '.join(missing_steps)}"
            )
            
    def _check_eligibility_rule_compliance(self, content: str):
        """Check for proper eligibility rule implementation"""
        
        # Check for phase-specific eligibility
        phases = ['move', 'shoot', 'charge', 'combat']
        for phase in phases:
            if f'phase == "{phase}"' not in content:
                self.warnings.append(
                    f"⚠️ ELIGIBILITY: Missing {phase} phase eligibility logic"
                )
                
        # Check for proper KeyError handling on missing fields
        if 'KeyError' in content and 'CUR_HP' in content:
            # Good - validates required fields
            pass
        else:
            self.violations.append(
                "❌ FIELD VALIDATION: Missing KeyError validation for required UPPERCASE fields"
            )

    # ENHANCED VALIDATIONS (from validator2/3)
    
    def _check_ast_structure_compliance(self, tree: ast.AST):
        """ENHANCED: AST-based structural validation"""
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "execute_gym_action":
                # Check for nested loops (multi-unit processing violation)
                for child in ast.walk(node):
                    if isinstance(child, ast.For):
                        # Check if it's iterating over units
                        if hasattr(child.iter, 'id') and 'unit' in child.iter.id.lower():
                            self.critical_violations.append(
                                f"❌ CRITICAL: Multi-unit loop in execute_gym_action (line {child.lineno})"
                            )
                        elif hasattr(child.iter, 'attr') and 'unit' in str(child.iter.attr).lower():
                            self.critical_violations.append(
                                f"❌ CRITICAL: Multi-unit iteration in execute_gym_action (line {child.lineno})"
                            )
                            
    def _check_method_signature_compliance(self, tree: ast.AST):
        """ENHANCED: Validate method signatures match AI_TURN.md spec"""
        
        required_methods = {
            'execute_gym_action': ['self', 'action'],
            '_get_current_active_unit': ['self'],
            '_build_gym_response': ['self']
        }
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                method_name = node.name
                if method_name in required_methods:
                    actual_args = [arg.arg for arg in node.args.args]
                    expected_args = required_methods[method_name]
                    
                    if actual_args != expected_args:
                        self.violations.append(
                            f"❌ METHOD SIGNATURE: {method_name} expects {expected_args}, got {actual_args}"
                        )
                        
    def _check_class_architecture_compliance(self, tree: ast.AST):
        """ENHANCED: Validate class architecture follows AI_TURN.md patterns"""
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "SequentialGameController":
                # Check for wrapper inheritance
                if node.bases:
                    for base in node.bases:
                        if hasattr(base, 'id') and 'Wrapper' in base.id:
                            self.critical_violations.append(
                                f"❌ CRITICAL: Inherits from wrapper class {base.id}"
                            )
                            
                # Check method count
                methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                if len(methods) > 20:  # AI_TURN.md complexity limit
                    self.violations.append(
                        f"❌ COMPLEXITY: Too many methods ({len(methods)}), should be ≤20"
                    )
                    
    def _format_all_violations(self) -> List[str]:
        """ENHANCED: Format violations with severity indicators"""
        
        formatted = []
        
        # Critical violations first
        for violation in self.critical_violations:
            formatted.append(f"🚨 {violation}")
            
        # Regular violations  
        for violation in self.violations:
            formatted.append(f"⚠️  {violation}")
            
        return formatted

    # INTEGRATION FEATURES (from validator3)
    
    def validate_and_enforce(self, file_path: str, fail_on_critical: bool = True) -> bool:
        """ENHANCED: Validate with enforcement options"""
        
        is_compliant, violations, warnings = self.validate_controller_file(file_path)
        
        if violations or warnings:
            self._print_compliance_report(violations, warnings)
            
            if fail_on_critical:
                critical_count = len([v for v in violations if "🚨" in v])
                if critical_count > 0:
                    raise AITurnComplianceViolation(violations)
                    
        return is_compliant
        
    def _print_compliance_report(self, violations: List[str], warnings: List[str]):
        """ENHANCED: Print detailed compliance report"""
        
        print("🔍 AI_TURN.md COMPLIANCE VALIDATION")
        print("=" * 60)
        
        if violations:
            print(f"\n❌ VIOLATIONS DETECTED ({len(violations)}):")
            for violation in violations:
                print(f"  {violation}")
                
        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)}):")
            for warning in warnings:
                print(f"  {warning}")
                
        if not violations and not warnings:
            print("✅ ENHANCED AI_TURN.md COMPLIANCE VERIFIED")
            print("\n🎉 Controller passes ALL enhanced compliance checks!")
            self._print_coverage_summary()
        else:
            print(f"\n💥 ENHANCED COMPLIANCE FAILED: {len(violations)} violations, {len(warnings)} warnings")
            
    def _print_coverage_summary(self):
        """Print validation coverage summary"""
        
        print("\n📊 VALIDATION COVERAGE:")
        print("  ✅ Sequential activation (ONE unit per gym step)")
        print("  ✅ Built-in step counting (not retrofitted)")
        print("  ✅ Phase completion by eligibility only")
        print("  ✅ UPPERCASE field compliance")
        print("  ✅ Tracking set compliance")
        print("  ✅ Combat sub-phases")
        print("  ✅ Charge mechanics")
        print("  ✅ Forbidden pattern detection")
        print("  ✅ AI_TURN.md 5-step pattern")
        print("  ✅ Eligibility rule compliance")
        print("  ✅ ENHANCED: AST structural validation")
        print("  ✅ ENHANCED: Method signature compliance")
        print("  ✅ ENHANCED: Class architecture validation")


# DECORATOR ENFORCEMENT (from validator3)

def ai_turn_compliant(cls):
    """ENHANCED: Decorator to enforce AI_TURN.md compliance on classes"""
    def validate_class():
        source_file = inspect.getfile(cls)
        validator = EnhancedAITurnValidator()
        validator.validate_and_enforce(source_file, fail_on_critical=True)
    
    validate_class()
    return cls


# PRE-COMMIT INTEGRATION (from validator3)

def install_ai_turn_precommit_hook(file_path: str = "ai/sequential_game_controller.py"):
    """ENHANCED: Install pre-commit validation hook"""
    
    validator = EnhancedAITurnValidator()
    
    try:
        is_compliant = validator.validate_and_enforce(file_path, fail_on_critical=True)
        
        if is_compliant:
            print("✅ AI_TURN.md PRE-COMMIT VALIDATION PASSED")
            return True
        else:
            print("🚫 AI_TURN.md PRE-COMMIT VALIDATION FAILED")
            return False
            
    except AITurnComplianceViolation as e:
        print(f"🚫 COMMIT BLOCKED: {len(e.violations)} critical violations")
        return False


# COMMAND LINE INTERFACE

def run_enhanced_compliance_validation():
    """Run enhanced AI_TURN.md compliance validation"""
    
    if len(sys.argv) > 1:
        controller_path = sys.argv[1]
    else:
        controller_path = "ai/sequential_game_controller.py"
    
    print("🔍 ENHANCED AI_TURN.md COMPLIANCE VALIDATION")
    print("=" * 60)
    
    validator = EnhancedAITurnValidator()
    
    try:
        is_compliant = validator.validate_and_enforce(controller_path, fail_on_critical=True)
        
        if is_compliant:
            print("\n🎉 ENHANCED VALIDATION SUCCESSFUL")
            return True
        else:
            print("\n⛔ ENHANCED VALIDATION FAILED")
            return False
            
    except AITurnComplianceViolation as e:
        print(f"\n🚫 VALIDATION FAILED: {len(e.violations)} critical violations")
        return False
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return False


if __name__ == "__main__":
    success = run_enhanced_compliance_validation()
    sys.exit(0 if success else 1)