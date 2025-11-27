#!/usr/bin/env python3
"""
test_fight_simple.py - Lightweight fight_handlers validation
Tests core logic without full engine imports (avoids TensorFlow crash)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_fight_file_structure():
    """Test 1: Verify fight_handlers.py file structure"""
    print("\n" + "="*80)
    print("TEST 1: File Structure Verification")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Verify critical function definitions exist
    required_functions = [
        'def fight_phase_start',
        'def fight_build_activation_pools',
        'def execute_action',
        'def _handle_fight_unit_activation',
        'def _handle_fight_attack',
        'def _handle_fight_postpone',
        'def _execute_fight_attack_sequence',
        'def _fight_build_valid_target_pool',
        'def fight_phase_end'
    ]

    all_found = True
    for func in required_functions:
        if func in content:
            print(f"[PASS] Function '{func}' exists")
        else:
            print(f"[FAIL] Function '{func}' MISSING")
            all_found = False

    return all_found


def test_fight_constants():
    """Test 2: Verify fight phase uses correct constants"""
    print("\n" + "="*80)
    print("TEST 2: Fight Phase Constants")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    tests = [
        ('game_state["phase"] = "fight"', "Phase set to 'fight'"),
        ('units_fought', "Tracking set: units_fought"),
        ('fight_charging_pool', "Pool: fight_charging_pool"),
        ('active_alternating_activation_pool', "Pool: active_alternating_activation_pool"),
        ('non_active_alternating_activation_pool', "Pool: non_active_alternating_activation_pool"),
        ('"next_phase": "move"', "Next phase: move"),
        ('from .generic_handlers import end_activation', "Generic end_activation import"),
    ]

    all_found = True
    for pattern, description in tests:
        if pattern in content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    return all_found


def test_fight_three_pools():
    """Test 3: Verify 3 fight pools are built"""
    print("\n" + "="*80)
    print("TEST 3: Three Fight Pools")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Extract fight_build_activation_pools function
    start = content.find('def fight_build_activation_pools')
    if start == -1:
        print("[FAIL] fight_build_activation_pools function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('fight_charging_pool', "Build fight_charging_pool"),
        ('active_alternating_activation_pool', "Build active_alternating_activation_pool"),
        ('non_active_alternating_activation_pool', "Build non_active_alternating_activation_pool"),
        ('units_charged', "Check units_charged for charging pool"),
        ('units_fought', "Check units_fought for exclusion"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in func_content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    return all_found


def test_cc_stats_usage():
    """Test 4: Verify CC_* stats used (not RNG_*)"""
    print("\n" + "="*80)
    print("TEST 4: CC_* Stats Usage")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Extract _execute_fight_attack_sequence function
    start = content.find('def _execute_fight_attack_sequence')
    if start == -1:
        print("[FAIL] _execute_fight_attack_sequence function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('CC_ATK', "Use CC_ATK (to-hit)"),
        ('CC_STR', "Use CC_STR (wound)"),
        ('CC_AP', "Use CC_AP (armor penetration)"),
        ('CC_DMG', "Use CC_DMG (damage)"),
        ('CC_NB', "Use CC_NB (number of attacks)"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in func_content or pattern in content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    # Verify NOT using RNG_* in fight attack
    bad_patterns = [
        'RNG_ATK',
        'RNG_STR',
        'RNG_AP',
        'RNG_DMG'
    ]

    for pattern in bad_patterns:
        if pattern in func_content:
            print(f"[FAIL] FOUND INCORRECT STAT: {pattern} (should use CC_* not RNG_*)")
            all_found = False

    if all_found:
        print("[PASS] No RNG_* stats found in fight attack sequence")

    return all_found


def test_postpone_mechanics():
    """Test 5: Verify postpone requires ATTACK_LEFT = CC_NB"""
    print("\n" + "="*80)
    print("TEST 5: Postpone Mechanics")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Extract _handle_fight_postpone function
    start = content.find('def _handle_fight_postpone')
    if start == -1:
        print("[FAIL] _handle_fight_postpone function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('ATTACK_LEFT', "Check ATTACK_LEFT"),
        ('CC_NB', "Check CC_NB"),
        ('ATTACK_LEFT == unit["CC_NB"]' in func_content or 'unit["ATTACK_LEFT"] == unit["CC_NB"]' in func_content, "Verify ATTACK_LEFT = CC_NB check"),
    ]

    all_found = True
    for check_item in checks:
        if isinstance(check_item, tuple):
            if isinstance(check_item[0], bool):
                # Direct boolean check
                if check_item[0]:
                    print(f"[PASS] {check_item[1]}")
                else:
                    print(f"[FAIL] {check_item[1]}")
                    all_found = False
            else:
                # String pattern check
                pattern, description = check_item
                if pattern in func_content:
                    print(f"[PASS] {description}")
                else:
                    print(f"[FAIL] MISSING: {description}")
                    all_found = False

    return all_found


def test_end_activation_calls():
    """Test 6: Verify end_activation calls use correct arguments"""
    print("\n" + "="*80)
    print("TEST 6: end_activation Call Verification")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    checks = [
        ('end_activation(', "end_activation function called"),
        ('"FIGHT"', "Arg3/Arg4 use 'FIGHT'"),
        ('"ACTION"', "Arg1 uses 'ACTION' for successful attack"),
        ('"PASS"', "Arg1 uses 'PASS' for no targets"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    # Verify NOT using incorrect phase names
    # Check context around end_activation calls
    end_activation_lines = [line for line in content.split('\n') if 'end_activation' in line and 'def ' not in line]

    incorrect_found = False
    for line in end_activation_lines:
        if '"SHOOTING"' in line or '"MOVE"' in line:
            print(f"[FAIL] FOUND INCORRECT PHASE in end_activation: {line.strip()}")
            incorrect_found = True

    if not incorrect_found:
        print("[PASS] No incorrect phase names in end_activation calls")
    else:
        all_found = False

    return all_found


def test_no_line_of_sight():
    """Test 7: Verify fight phase doesn't use line of sight"""
    print("\n" + "="*80)
    print("TEST 7: No Line of Sight Checks")
    print("="*80)

    with open("engine/phase_handlers/fight_handlers.py", "r", encoding="utf-8") as f:
        content = f.read()

    # Extract _fight_build_valid_target_pool function
    start = content.find('def _fight_build_valid_target_pool')
    if start == -1:
        print("[FAIL] _fight_build_valid_target_pool function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    # Check for NO LoS
    if 'line_of_sight' in func_content.lower() or '_has_line_of_sight' in func_content:
        print("[FAIL] Found line of sight check in fight target validation")
        return False
    else:
        print("[PASS] No line of sight checks in fight phase")

    # Check uses CC_RNG for adjacency
    if 'CC_RNG' in func_content:
        print("[PASS] Uses CC_RNG for adjacency check")
    else:
        print("[FAIL] MISSING CC_RNG for adjacency")
        return False

    return True


def run_all_tests():
    """Run complete lightweight test suite"""
    print("\n" + "="*80)
    print("FIGHT_HANDLERS.PY - LIGHTWEIGHT VALIDATION SUITE")
    print("AI_TURN.md Compliance Verification (No TensorFlow)")
    print("="*80)

    tests = [
        ("File Structure", test_fight_file_structure),
        ("Fight Constants", test_fight_constants),
        ("Three Fight Pools", test_fight_three_pools),
        ("CC_* Stats Usage", test_cc_stats_usage),
        ("Postpone Mechanics", test_postpone_mechanics),
        ("end_activation Calls", test_end_activation_calls),
        ("No Line of Sight", test_no_line_of_sight)
    ]

    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n[FAIL] FATAL ERROR in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for test_name, passed in results:
        status = "[PASS] PASS" if passed else "[FAIL] FAIL"
        print(f"{status} - {test_name}")

    print("="*80)
    print(f"RESULT: {passed_count}/{total_count} tests passed")
    print("="*80)

    if passed_count == total_count:
        print("\n[SUCCESS] ALL TESTS PASSED - fight_handlers.py structure is AI_TURN.md compliant!")
        print("NOTE: Runtime testing requires resolving TensorFlow import issues")
        return True
    else:
        print(f"\n[WARN]  {total_count - passed_count} test(s) failed - review output above")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
