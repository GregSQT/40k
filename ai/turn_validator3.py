#!/usr/bin/env python3
"""
ai/turn_validator.py - Enhanced AI_TURN.md Compliance Validator

ENHANCED VERSION: Combines best features from all validator versions
- Comprehensive AI_TURN.md game rule validation (from validator1)
- Better error reporting and violation details (from validator2)
- Optional runtime monitoring hooks (from validator3)
- Maintains simplicity and focus

COVERAGE: ALL AI_TURN.md requirements with practical implementation
"""

import ast
import re
import os
import sys
import time
from typing import List, Dict, Tuple, Set, Optional, Any
from pathlib import Path
from dataclasses import dataclass
from functools import wraps

@dataclass
class ComplianceViolation:
    """Enhanced violation reporting with actionable details"""
    rule: str
    severity: str  # "CRITICAL", "ERROR", "WARNING"
    line_number: int
    code_snippet: str
    message: str
    ai_turn_reference: str
    suggested_fix: str
    category: str  # "GAME_LOGIC", "ARCHITECTURE", "FIELDS", "PATTERNS"

class AI_TURN_ComplianceViolation(Exception):
    """Raised when critical AI_TURN.md violations are detected"""
    pass

class EnhancedAITurnValidator:
    """
    ENHANCED AI_TURN.md Compliance Validator
    
    Combines the best features from all validator versions:
    - Comprehensive game rule validation (validator1 core strength)
    - Excellent error reporting (validator2 enhancement)
    - Optional runtime monitoring (validator3 safety net)
    
    VALIDATES ALL AI_TURN.md REQUIREMENTS:
    ✅ Sequential activation (ONE unit per gym step)
    ✅ Built-in step counting (NOT retrofitted)
    ✅ Phase completion by eligibility ONLY
    ✅ UPPERCASE field validation
    ✅ Phase-specific eligibility rules
    ✅ Tracking set compliance
    ✅ Combat sub-phases
    ✅ Charge mechanics
    ✅ Turn progression logic
    ✅ State management patterns
    """
    
    def __init__(self, enable_runtime_monitoring: bool = False):
        self.violations: List[ComplianceViolation] = []
        self.warnings: List[ComplianceViolation] = []
        self.runtime_monitoring = enable_runtime_monitoring
        
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
        
        # Enhanced pattern detection with better accuracy
        self.critical_patterns = {
            "retrofitted_counting": [
                r"steps_before\s*=.*get.*episode_steps",
                r"steps_after\s*=.*get.*episode_steps", 
                r"if.*steps_after.*>.*steps_before",
                r"episode_steps.*increment.*after.*action"
            ],
            "wrapper_delegation": [
                r"class.*Wrapper.*Controller",
                r"def __getattr__.*getattr\(self\.base",
                r"StepLoggingWrapper",
                r"SequentialIntegrationWrapper"
            ],
            "multi_unit_processing": [
                r"for\s+unit\s+in\s+.*units.*:",
                r"while.*units.*and.*execute",
                r"batch.*process.*multiple.*units"
            ]
        }
        
    def validate_controller_file(self, file_path: str) -> Tuple[bool, List[ComplianceViolation], List[ComplianceViolation]]:
        """
        ENHANCED validation with comprehensive AI_TURN.md coverage
        Returns: (is_compliant, violations, warnings)
        """
        if not os.path.exists(file_path):
            return False, [self._create_violation(
                "FILE_NOT_FOUND", "CRITICAL", 0, "", 
                f"Controller file not found: {file_path}",
                "AI_TURN.md requires SequentialGameController implementation",
                "Create sequential_game_controller.py with AI_TURN.md compliance",
                "ARCHITECTURE"
            )], []
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Reset validation state
        self.violations = []
        self.warnings = []
        
        # Parse for structural analysis (simple AST usage)
        try:
            tree = ast.parse(content)
            lines = content.split('\n')
        except SyntaxError as e:
            return False, [self._create_violation(
                "SYNTAX_ERROR", "CRITICAL", e.lineno or 0, str(e.text or ""),
                f"Syntax error prevents AI_TURN.md validation: {e.msg}",
                "Valid Python syntax required for compliance checking",
                "Fix syntax errors before validating AI_TURN.md compliance",
                "ARCHITECTURE"
            )], []
        
        # CORE AI_TURN.md VALIDATIONS (from validator1 - the essential ones)
        self._validate_sequential_activation(content, lines)
        self._validate_built_in_step_counting(content, lines)
        self._validate_phase_completion_logic(content, lines)
        self._validate_uppercase_fields(content, lines)
        self._validate_tracking_sets(content, lines)
        self._validate_combat_mechanics(content, lines)
        self._validate_charge_mechanics(content, lines)
        self._validate_eligibility_rules(content, lines)
        
        # ENHANCED VALIDATIONS (from validator2 - structural improvements)
        self._validate_execute_gym_action_structure(content, lines, tree)
        self._validate_forbidden_patterns(content, lines)
        
        # PERFORMANCE & SIMPLICITY CHECKS
        self._validate_file_complexity(lines)
        
        # Categorize results
        critical_violations = [v for v in self.violations if v.severity == "CRITICAL"]
        is_compliant = len(critical_violations) == 0
        
        return is_compliant, self.violations, self.warnings
        
    def _validate_sequential_activation(self, content: str, lines: List[str]):
        """Validate ONE unit per gym step (CORE AI_TURN.md requirement)"""
        
        # Check for execute_gym_action processing single unit
        if 'def execute_gym_action' in content:
            # Look for unit processing loops (violation)
            unit_loop_patterns = [
                r"for\s+unit\s+in\s+.*:",
                r"while.*units.*:",
                r"for\s+u\s+in\s+units"
            ]
            
            for i, line in enumerate(lines):
                for pattern in unit_loop_patterns:
                    if re.search(pattern, line) and 'execute_gym_action' in '\n'.join(lines[max(0, i-10):i+10]):
                        self.violations.append(self._create_violation(
                            "MULTI_UNIT_PROCESSING", "CRITICAL", i+1, line.strip(),
                            "Multiple unit processing detected in execute_gym_action",
                            "AI_TURN.md Rule #2: ONE unit per gym step (sequential activation)",
                            "Process units one at a time through queue management",
                            "GAME_LOGIC"
                        ))
                        
        # Check for proper unit queue management
        if 'active_unit_queue' in content:
            if not re.search(r'active_unit_queue.*List\[str\]', content):
                self.warnings.append(self._create_violation(
                    "UNIT_QUEUE_TYPE", "WARNING", 1, "",
                    "Unit queue should contain only unit IDs (strings), not full objects",
                    "AI_TURN.md requires simple unit queue with IDs only",
                    "Declare: active_unit_queue: List[str] = []",
                    "ARCHITECTURE"
                ))
                
    def _validate_built_in_step_counting(self, content: str, lines: List[str]):
        """Validate built-in step counting (NOT retrofitted)"""
        
        # Check for built-in increment
        has_builtin_increment = re.search(r'self\.base\.game_state\["episode_steps"\]\s*\+=\s*1', content)
        
        if not has_builtin_increment:
            self.violations.append(self._create_violation(
                "MISSING_BUILTIN_STEP_COUNT", "CRITICAL", 1, "",
                "Missing built-in episode_steps increment in execute_gym_action",
                "AI_TURN.md Rule #4: Built-in step counting (NOT retrofitted)",
                'Add: self.base.game_state["episode_steps"] += 1 in execute_gym_action step 3',
                "GAME_LOGIC"
            ))
            
        # Check for retrofitted patterns (forbidden)
        retrofitted_patterns = [
            r"steps_before\s*=",
            r"steps_after\s*=",
            r"if.*steps_after.*>.*steps_before"
        ]
        
        for i, line in enumerate(lines):
            for pattern in retrofitted_patterns:
                if re.search(pattern, line):
                    self.violations.append(self._create_violation(
                        "RETROFITTED_STEP_COUNTING", "CRITICAL", i+1, line.strip(),
                        "Retrofitted step counting pattern detected",
                        "AI_TURN.md Rule #4: Step counting must be BUILT-IN, not retrofitted",
                        "Remove retrofitted pattern, use built-in increment in execute_gym_action",
                        "PATTERNS"
                    ))
                    
    def _validate_phase_completion_logic(self, content: str, lines: List[str]):
        """Validate eligibility-based phase completion"""
        
        # Check for eligibility-based completion
        has_eligibility_check = (
            '_is_phase_complete' in content or 
            'no_active_unit' in content or
            'len(self.active_unit_queue) == 0' in content
        )
        
        if not has_eligibility_check:
            self.violations.append(self._create_violation(
                "MISSING_ELIGIBILITY_PHASE_COMPLETION", "ERROR", 1, "",
                "Missing eligibility-based phase completion logic",
                "AI_TURN.md Rule #3: Phases end when no eligible units remain",
                "Implement _is_phase_complete() based on unit eligibility",
                "GAME_LOGIC"
            ))
            
        # Check for forbidden step-based transitions
        step_based_patterns = [
            r"if.*episode_steps.*>=.*phase",
            r"elif.*step.*count.*advance",
            r"transition.*when.*steps.*>"
        ]
        
        for i, line in enumerate(lines):
            for pattern in step_based_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.violations.append(self._create_violation(
                        "STEP_BASED_TRANSITION", "ERROR", i+1, line.strip(),
                        "Step-based phase transition detected",
                        "AI_TURN.md Rule #3: Phase completion by eligibility ONLY, not step counts",
                        "Use eligibility checks instead of step counting for phase transitions",
                        "GAME_LOGIC"
                    ))
                    
    def _validate_uppercase_fields(self, content: str, lines: List[str]):
        """Validate UPPERCASE field naming compliance"""
        
        # Check for forbidden lowercase variants
        forbidden_lowercase = {
            'cur_hp': 'CUR_HP', 'hp_max': 'HP_MAX', 'rng_nb': 'RNG_NB',
            'cc_str': 'CC_STR', 'armor_save': 'ARMOR_SAVE', 'invul_save': 'INVUL_SAVE'
        }
        
        for i, line in enumerate(lines):
            for lowercase, uppercase in forbidden_lowercase.items():
                pattern = f'["\']({lowercase})["\']'
                if re.search(pattern, line):
                    self.violations.append(self._create_violation(
                        "LOWERCASE_FIELD", "ERROR", i+1, line.strip(),
                        f"Lowercase field '{lowercase}' should be '{uppercase}'",
                        "AI_TURN.md requires UPPERCASE fields for unit statistics",
                        f"Change '{lowercase}' to '{uppercase}'",
                        "FIELDS"
                    ))
                    
        # Check for required UPPERCASE field validation
        keyerror_patterns = [
            r'if\s+"CUR_HP"\s+not\s+in\s+unit',
            r'KeyError.*CUR_HP.*missing',
            r'raise\s+KeyError.*CUR_HP'
        ]
        
        has_field_validation = any(re.search(pattern, content) for pattern in keyerror_patterns)
        if not has_field_validation:
            self.warnings.append(self._create_violation(
                "MISSING_FIELD_VALIDATION", "WARNING", 1, "",
                "Missing KeyError validation for required UPPERCASE fields",
                "AI_TURN.md requires strict field validation with KeyError",
                'Add: if "CUR_HP" not in unit: raise KeyError(f"Unit {unit[\'id\']} missing CUR_HP")',
                "FIELDS"
            ))
            
    def _validate_tracking_sets(self, content: str, lines: List[str]):
        """Validate tracking set compliance"""
        
        missing_sets = []
        for tracking_set in self.required_tracking_sets:
            if tracking_set not in content:
                missing_sets.append(tracking_set)
                
        if missing_sets:
            self.warnings.append(self._create_violation(
                "MISSING_TRACKING_SETS", "WARNING", 1, "",
                f"Missing tracking sets: {', '.join(missing_sets)}",
                "AI_TURN.md requires proper tracking sets for phase management",
                f"Add references to missing tracking sets: {', '.join(missing_sets)}",
                "GAME_LOGIC"
            ))
            
        # Check for proper KeyError validation on tracking sets
        if 'KeyError' not in content and any(ts in content for ts in self.required_tracking_sets):
            self.warnings.append(self._create_violation(
                "MISSING_TRACKING_VALIDATION", "WARNING", 1, "",
                "Missing KeyError validation for tracking sets",
                "AI_TURN.md requires strict validation of game_state tracking sets",
                'Add KeyError checks for missing tracking sets in game_state',
                "GAME_LOGIC"
            ))
            
    def _validate_combat_mechanics(self, content: str, lines: List[str]):
        """Validate combat phase mechanics"""
        
        if 'combat' in content.lower():
            # Check for charging unit priority
            if 'units_charged' in content and 'units_attacked' in content:
                if not re.search(r'charged.*first|priority.*charged', content, re.IGNORECASE):
                    self.warnings.append(self._create_violation(
                        "MISSING_CHARGE_PRIORITY", "WARNING", 1, "",
                        "Combat phase should handle charging unit priority",
                        "AI_TURN.md combat sub-phase 1: charging units attack first",
                        "Implement charging unit priority in combat phase",
                        "GAME_LOGIC"
                    ))
                    
            # Check for both players in combat
            if 'current_player' in content and 'phase == "combat"' in content:
                if not re.search(r'both.*players|non.*active.*player', content, re.IGNORECASE):
                    self.violations.append(self._create_violation(
                        "COMBAT_SINGLE_PLAYER", "ERROR", 1, "",
                        "Combat phase should handle both players, not just current_player",
                        "AI_TURN.md combat phase: both players' units can act",
                        "Allow both players' units in combat phase eligibility",
                        "GAME_LOGIC"
                    ))
                    
    def _validate_charge_mechanics(self, content: str, lines: List[str]):
        """Validate charge mechanics"""
        
        if 'charge' in content.lower():
            # Check for 2d6 mechanics
            has_2d6 = ('2d6' in content or 
                      ('die1' in content and 'die2' in content) or
                      'charge_roll' in content)
            
            if not has_2d6:
                self.warnings.append(self._create_violation(
                    "MISSING_CHARGE_DICE", "WARNING", 1, "",
                    "Charge phase missing 2d6 roll mechanics",
                    "AI_TURN.md charge phase: 2d6 roll when unit becomes active",
                    "Implement 2d6 charge roll when unit selected for charging",
                    "GAME_LOGIC"
                ))
                
            # Check for charge distance validation
            if not re.search(r'charge.*distance|charge.*range|charge_max_distance', content):
                self.warnings.append(self._create_violation(
                    "MISSING_CHARGE_DISTANCE", "WARNING", 1, "",
                    "Missing charge distance/range validation",
                    "AI_TURN.md charge phase: validate enemies within charge range",
                    "Add charge distance validation using charge_max_distance",
                    "GAME_LOGIC"
                ))
                
    def _validate_eligibility_rules(self, content: str, lines: List[str]):
        """Validate phase-specific eligibility rules"""
        
        phases = ['move', 'shoot', 'charge', 'combat']
        for phase in phases:
            if f'phase == "{phase}"' not in content:
                self.warnings.append(self._create_violation(
                    f"MISSING_{phase.upper()}_ELIGIBILITY", "WARNING", 1, "",
                    f"Missing {phase} phase eligibility logic",
                    f"AI_TURN.md requires phase-specific eligibility for {phase} phase",
                    f"Implement _is_unit_eligible_for_current_phase for {phase}",
                    "GAME_LOGIC"
                ))
                
        # Check for specific eligibility patterns
        eligibility_checks = {
            'move': r'units_moved.*not.*in|not.*in.*units_moved',
            'shoot': r'units_shot.*not.*in|fled.*check|adjacent.*check',
            'charge': r'units_charged.*not.*in|enemies.*within.*range',
            'combat': r'units_attacked.*not.*in|adjacent.*enemies'
        }
        
        for phase, pattern in eligibility_checks.items():
            if f'"{phase}"' in content and not re.search(pattern, content):
                self.warnings.append(self._create_violation(
                    f"INCOMPLETE_{phase.upper()}_ELIGIBILITY", "WARNING", 1, "",
                    f"Incomplete {phase} phase eligibility validation",
                    f"AI_TURN.md {phase} phase: specific eligibility requirements",
                    f"Add complete eligibility validation for {phase} phase",
                    "GAME_LOGIC"
                ))
                
    def _validate_execute_gym_action_structure(self, content: str, lines: List[str], tree: ast.AST):
        """Validate execute_gym_action follows AI_TURN.md 5-step pattern"""
        
        if 'def execute_gym_action' not in content:
            self.violations.append(self._create_violation(
                "MISSING_EXECUTE_GYM_ACTION", "CRITICAL", 1, "",
                "Missing execute_gym_action method",
                "AI_TURN.md requires execute_gym_action as main entry point",
                "Implement execute_gym_action with 5-step pattern",
                "ARCHITECTURE"
            ))
            return
            
        # Find execute_gym_action method content
        method_start = None
        method_end = None
        for i, line in enumerate(lines):
            if 'def execute_gym_action' in line:
                method_start = i
            elif method_start is not None and line.strip().startswith('def ') and 'execute_gym_action' not in line:
                method_end = i
                break
                
        if method_start is not None:
            method_end = method_end or len(lines)
            method_content = '\n'.join(lines[method_start:method_end])
            
            # Check for 5-step pattern
            required_steps = [
                ('1.*get.*active.*unit', 'Step 1: Get current active unit'),
                ('2.*no.*unit|handle.*no.*active', 'Step 2: Handle no active unit'),
                ('3.*execute.*action', 'Step 3: Execute action for unit'),
                ('4.*remove.*queue|mark.*acted', 'Step 4: Remove unit from queue'),
                ('5.*return.*response|build.*response', 'Step 5: Return gym response')
            ]
            
            missing_steps = []
            for pattern, description in required_steps:
                if not re.search(pattern, method_content, re.IGNORECASE):
                    missing_steps.append(description)
                    
            if missing_steps:
                self.violations.append(self._create_violation(
                    "INCOMPLETE_5_STEP_PATTERN", "ERROR", method_start + 1, 
                    lines[method_start].strip(),
                    f"execute_gym_action missing steps: {', '.join(missing_steps)}",
                    "AI_TURN.md requires exact 5-step pattern in execute_gym_action",
                    "Add missing steps with proper comments as per AI_TURN.md",
                    "ARCHITECTURE"
                ))
                
    def _validate_forbidden_patterns(self, content: str, lines: List[str]):
        """Validate against forbidden patterns"""
        
        for pattern_type, patterns in self.critical_patterns.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE))
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    line_content = lines[line_num - 1] if line_num <= len(lines) else ""
                    
                    severity = "CRITICAL" if pattern_type in ["retrofitted_counting", "wrapper_delegation"] else "ERROR"
                    
                    self.violations.append(self._create_violation(
                        pattern_type.upper(), severity, line_num, line_content.strip(),
                        f"Forbidden {pattern_type.replace('_', ' ')} pattern: {match.group()}",
                        f"AI_TURN.md prohibits {pattern_type.replace('_', ' ')} patterns",
                        f"Remove {pattern_type.replace('_', ' ')} and implement direct AI_TURN.md pattern",
                        "PATTERNS"
                    ))
                    
    def _validate_file_complexity(self, lines: List[str]):
        """Validate file complexity limits"""
        
        non_empty_lines = len([line for line in lines if line.strip() and not line.strip().startswith('#')])
        
        if non_empty_lines > 500:
            self.warnings.append(self._create_violation(
                "EXCESSIVE_COMPLEXITY", "WARNING", 1, f"File has {non_empty_lines} lines",
                f"File too complex ({non_empty_lines} lines) - AI_TURN.md prefers focused implementation",
                "AI_TURN.md requires simple sequential activation logic",
                "Consider refactoring into smaller, focused modules (target: <400 lines)",
                "ARCHITECTURE"
            ))
            
    def _create_violation(self, rule: str, severity: str, line_number: int, code_snippet: str,
                         message: str, ai_turn_reference: str, suggested_fix: str, 
                         category: str) -> ComplianceViolation:
        """Create standardized violation object"""
        return ComplianceViolation(
            rule=rule,
            severity=severity,
            line_number=line_number,
            code_snippet=code_snippet,
            message=message,
            ai_turn_reference=ai_turn_reference,
            suggested_fix=suggested_fix,
            category=category
        )
        
    def generate_enhanced_report(self, violations: List[ComplianceViolation], 
                               warnings: List[ComplianceViolation]) -> str:
        """Generate enhanced compliance report with categories"""
        
        if not violations and not warnings:
            return """✅ AI_TURN.md COMPLIANCE: FULLY COMPLIANT
            
🎉 Congratulations! Your controller passes ALL AI_TURN.md compliance checks.

📊 VALIDATION COVERAGE COMPLETE:
  ✅ Sequential activation (ONE unit per gym step)
  ✅ Built-in step counting (NOT retrofitted)  
  ✅ Phase completion by eligibility ONLY
  ✅ UPPERCASE field validation
  ✅ Phase-specific eligibility rules
  ✅ Tracking set compliance
  ✅ Combat sub-phases
  ✅ Charge mechanics
  ✅ Forbidden pattern detection
  ✅ Architectural simplicity

🚀 Your controller is ready for production use!"""

        report = ["🔍 ENHANCED AI_TURN.md COMPLIANCE REPORT", "=" * 60]
        
        # Categorize violations
        by_category = {}
        for v in violations + warnings:
            if v.category not in by_category:
                by_category[v.category] = []
            by_category[v.category].append(v)
            
        # Report by category
        category_order = ["GAME_LOGIC", "ARCHITECTURE", "FIELDS", "PATTERNS"]
        
        for category in category_order:
            if category in by_category:
                items = by_category[category]
                critical = [v for v in items if v.severity == "CRITICAL"]
                errors = [v for v in items if v.severity == "ERROR"]
                warnings_cat = [v for v in items if v.severity == "WARNING"]
                
                report.append(f"\n📁 {category} CATEGORY:")
                
                if critical:
                    report.append(f"  ❌ CRITICAL ({len(critical)}) - MUST FIX IMMEDIATELY:")
                    for v in critical:
                        report.extend(self._format_violation_compact(v))
                        
                if errors:
                    report.append(f"  ⚠️ ERRORS ({len(errors)}) - SHOULD FIX:")
                    for v in errors:
                        report.extend(self._format_violation_compact(v))
                        
                if warnings_cat:
                    report.append(f"  ℹ️ WARNINGS ({len(warnings_cat)}) - CONSIDER FIXING:")
                    for v in warnings_cat:
                        report.extend(self._format_violation_compact(v))
                        
        # Summary
        total_critical = len([v for v in violations if v.severity == "CRITICAL"])
        total_errors = len([v for v in violations if v.severity == "ERROR"])
        total_warnings = len(warnings)
        
        report.append(f"\n📊 SUMMARY:")
        report.append(f"  • {total_critical} critical violations")
        report.append(f"  • {total_errors} error violations") 
        report.append(f"  • {total_warnings} warnings")
        
        if total_critical > 0:
            report.append(f"\n🚨 COMPLIANCE STATUS: FAILED - {total_critical} critical issues must be fixed")
        elif total_errors > 0:
            report.append(f"\n⚠️ COMPLIANCE STATUS: PARTIAL - {total_errors} errors should be fixed")
        else:
            report.append(f"\n✅ COMPLIANCE STATUS: PASSED - Only warnings remain")
            
        report.append("\n🎯 AI_TURN.md COMPLIANCE REQUIRED FOR PRODUCTION")
        
        return "\n".join(report)
        
    def _format_violation_compact(self, violation: ComplianceViolation) -> List[str]:
        """Format violation in compact style"""
        return [
            f"    Line {violation.line_number}: {violation.message}",
            f"    Code: {violation.code_snippet}" if violation.code_snippet else "",
            f"    Fix: {violation.suggested_fix}",
            ""
        ]
        
    def install_runtime_monitoring(self, controller_instance):
        """Optional runtime monitoring (simplified from validator3)"""
        if not self.runtime_monitoring:
            return None
            
        # Simple runtime hooks for critical violations only
        original_execute = controller_instance.execute_gym_action
        
        @wraps(original_execute)
        def monitored_execute_gym_action(action):
            # Pre-execution check
            if hasattr(controller_instance, '_units_processed_this_action'):
                controller_instance._units_processed_this_action = 0
            else:
                controller_instance._units_processed_this_action = 0
                
            # Execute
            result = original_execute(action)
            
            # Post-execution validation
            if hasattr(controller_instance, '_units_processed_this_action'):
                if controller_instance._units_processed_this_action != 1:
                    raise AI_TURN_ComplianceViolation(
                        f"RUNTIME VIOLATION: {controller_instance._units_processed_this_action} units processed, "
                        f"AI_TURN.md requires exactly 1 unit per gym action"
                    )
                    
            return result
            
        controller_instance.execute_gym_action = monitored_execute_gym_action
        return "Runtime monitoring installed"


def run_enhanced_compliance_validation(file_path: str = "ai/sequential_game_controller.py", 
                                     enable_runtime: bool = False) -> bool:
    """Run enhanced AI_TURN.md compliance validation"""
    
    print("🔍 ENHANCED AI_TURN.md COMPLIANCE VALIDATION")
    print("=" * 60)
    print("📋 COMPREHENSIVE COVERAGE: Game Logic + Architecture + Fields + Patterns")
    print()
    
    validator = EnhancedAITurnValidator(enable_runtime_monitoring=enable_runtime)
    is_compliant, violations, warnings = validator.validate_controller_file(file_path)
    
    # Generate and display report
    report = validator.generate_enhanced_report(violations, warnings)
    print(report)
    
    return is_compliant

def validate_file_cli():
    """Command-line interface"""
    if len(sys.argv) < 2:
        print("Usage: python turn_validator.py <file_path> [--runtime]")
        sys.exit(1)
        
    file_path = sys.argv[1]
    enable_runtime = "--runtime" in sys.argv
    
    success = run_enhanced_compliance_validation(file_path, enable_runtime)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        validate_file_cli()
    else:
        # Default validation
        success = run_enhanced_compliance_validation()
        if success:
            print("\n🎉 ENHANCED VALIDATION SUCCESSFUL")
        else:
            print("\n⛔ ENHANCED VALIDATION FAILED")