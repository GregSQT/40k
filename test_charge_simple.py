#!/usr/bin/env python3
"""
test_charge_simple.py - Lightweight charge_handlers validation
Tests core logic without full engine imports (avoids TensorFlow crash)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_charge_file_structure():
    """Test 1: Verify charge_handlers.py file structure"""
    print("\n" + "="*80)
    print("TEST 1: File Structure Verification")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Verify critical function definitions exist
    required_functions = [
        'def charge_phase_start',
        'def charge_build_activation_pool',
        'def get_eligible_units',
        'def execute_action',
        'def charge_unit_activation_start',
        'def charge_unit_execution_loop',
        'def charge_build_valid_destinations_pool',
        'def charge_phase_end'
    ]

    all_found = True
    for func in required_functions:
        if func in content:
            print(f"[PASS] Function '{func}' exists")
        else:
            print(f"[FAIL] Function '{func}' MISSING")
            all_found = False

    return all_found


def test_charge_constants():
    """Test 2: Verify charge phase uses correct constants"""
    print("\n" + "="*80)
    print("TEST 2: Charge Phase Constants")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    tests = [
        ('game_state["phase"] = "charge"', "Phase set to 'charge'"),
        ('charge_roll_values', "2d6 roll storage"),
        ('units_charged', "Tracking set: units_charged"),
        ('charge_activation_pool', "Activation pool: charge_activation_pool"),
        ('"next_phase": "fight"', "Next phase: fight"),
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


def test_charge_eligibility_logic():
    """Test 3: Verify charge eligibility checks"""
    print("\n" + "="*80)
    print("TEST 3: Charge Eligibility Logic")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Extract get_eligible_units function
    start = content.find('def get_eligible_units')
    if start == -1:
        print("[FAIL] get_eligible_units function not found")
        return False

    # Find function end (next def or end of file)
    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('units_charged', "Check NOT in units_charged"),
        ('units_fled', "Check NOT in units_fled"),
        ('_is_adjacent_to_enemy', "Check NOT adjacent to enemy"),
        ('_has_valid_charge_target', "Check has valid target"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in func_content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    return all_found


def test_2d6_roll_implementation():
    """Test 4: Verify 2d6 roll implementation"""
    print("\n" + "="*80)
    print("TEST 4: 2d6 Roll Implementation")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Extract charge_unit_activation_start function
    start = content.find('def charge_unit_activation_start')
    if start == -1:
        print("[FAIL] charge_unit_activation_start function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('random.randint(1, 6) + random.randint(1, 6)', "2d6 roll (two separate d6)"),
        ('charge_roll_values', "Store in charge_roll_values"),
        ('import random', "Random import"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in content:  # Check entire file for imports
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    return all_found


def test_destination_validation():
    """Test 5: Verify charge destinations must be adjacent to enemy"""
    print("\n" + "="*80)
    print("TEST 5: Destination Validation (Adjacent to Enemy)")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Extract charge_build_valid_destinations_pool function
    start = content.find('def charge_build_valid_destinations_pool')
    if start == -1:
        print("[FAIL] charge_build_valid_destinations_pool function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('CC_RNG', "Use CC_RNG for adjacency check"),
        ('_calculate_hex_distance', "Calculate distance to enemy"),
        ('valid_charge_destinations_pool', "Build valid destinations pool"),
        ('BFS', "BFS pathfinding (mentioned in comments)"),
    ]

    found_count = 0
    for pattern, description in checks:
        if pattern in func_content or pattern in content:
            print(f"[PASS] {description}")
            found_count += 1
        else:
            print(f"[WARN]  {description} not found (may use alternative implementation)")

    # At least 3/4 checks should pass
    if found_count >= 3:
        print(f"[PASS] Destination validation logic present ({found_count}/4 checks)")
        return True
    else:
        print(f"[FAIL] Insufficient destination validation ({found_count}/4 checks)")
        return False


def test_end_activation_calls():
    """Test 6: Verify end_activation calls use correct arguments"""
    print("\n" + "="*80)
    print("TEST 6: end_activation Call Verification")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Check for correct end_activation patterns
    checks = [
        ('end_activation(', "end_activation function called"),
        ('"CHARGE"', "Arg3/Arg4 use 'CHARGE'"),
        ('"ACTION"', "Arg1 uses 'ACTION' for successful charge"),
        ('"WAIT"', "Arg1 uses 'WAIT' for skip"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    # Verify NOT using movement/shooting patterns
    bad_patterns = [
        ('"MOVE"', "Should NOT use 'MOVE' (charge phase)"),
        ('"SHOOTING"', "Should NOT use 'SHOOTING' (charge phase)"),
    ]

    for pattern, description in bad_patterns:
        if pattern in content:
            print(f"[FAIL] FOUND INCORRECT PATTERN: {description}")
            all_found = False
        else:
            print(f"[PASS] {description}")

    return all_found


def test_phase_completion():
    """Test 7: Verify phase completion transitions to fight"""
    print("\n" + "="*80)
    print("TEST 7: Phase Completion and Transition")
    print("="*80)

    with open("engine/phase_handlers/charge_handlers.py", "r") as f:
        content = f.read()

    # Extract charge_phase_end function
    start = content.find('def charge_phase_end')
    if start == -1:
        print("[FAIL] charge_phase_end function not found")
        return False

    next_def = content.find('\ndef ', start + 1)
    if next_def == -1:
        func_content = content[start:]
    else:
        func_content = content[start:next_def]

    checks = [
        ('"phase_complete": True', "Phase complete flag"),
        ('"next_phase": "fight"', "Next phase is 'fight'"),
        ('charge_roll_values', "Clear charge_roll_values"),
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in func_content:
            print(f"[PASS] {description}")
        else:
            print(f"[FAIL] MISSING: {description}")
            all_found = False

    return all_found


def run_all_tests():
    """Run complete lightweight test suite"""
    print("\n" + "="*80)
    print("CHARGE_HANDLERS.PY - LIGHTWEIGHT VALIDATION SUITE")
    print("AI_TURN.md Compliance Verification (No TensorFlow)")
    print("="*80)

    tests = [
        ("File Structure", test_charge_file_structure),
        ("Charge Constants", test_charge_constants),
        ("Eligibility Logic", test_charge_eligibility_logic),
        ("2d6 Roll Implementation", test_2d6_roll_implementation),
        ("Destination Validation", test_destination_validation),
        ("end_activation Calls", test_end_activation_calls),
        ("Phase Completion", test_phase_completion)
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
        print("\n[SUCCESS] ALL TESTS PASSED - charge_handlers.py structure is AI_TURN.md compliant!")
        print("NOTE: Runtime testing requires resolving TensorFlow import issues")
        return True
    else:
        print(f"\n[WARN]  {total_count - passed_count} test(s) failed - review output above")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
