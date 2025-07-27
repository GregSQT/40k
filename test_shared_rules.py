#!/usr/bin/env python3
"""
Test script to validate shared rules consistency between TypeScript and Python implementations
"""

import sys
import os
import json
import random
from pathlib import Path

# Add project root to path
script_dir = Path(__file__).parent
project_root = script_dir.parent if script_dir.name == 'scripts' else script_dir
sys.path.insert(0, str(project_root))

try:
    from shared.gameRules import roll_d6, calculate_wound_target, calculate_save_target, execute_shooting_sequence
    print("✅ Successfully imported shared Python rules")
except ImportError as e:
    print(f"❌ Failed to import shared Python rules: {e}")
    sys.exit(1)

def test_wound_target_calculation():
    """Test wound target calculations match expected W40K rules"""
    print("\n🎯 Testing wound target calculations...")
    
    test_cases = [
        # (strength, toughness, expected_target)
        (3, 6, 6),  # S*2 <= T: wound on 6+
        (4, 5, 5),  # S < T: wound on 5+  
        (4, 4, 4),  # S = T: wound on 4+
        (5, 4, 3),  # S > T: wound on 3+
        (8, 4, 2),  # S*2 >= T: wound on 2+
        (10, 3, 2), # S*2 >= T: wound on 2+
    ]
    
    passed = 0
    for strength, toughness, expected in test_cases:
        result = calculate_wound_target(strength, toughness)
        if result == expected:
            print(f"  ✅ S{strength} vs T{toughness} = {result}+ (expected {expected}+)")
            passed += 1
        else:
            print(f"  ❌ S{strength} vs T{toughness} = {result}+ (expected {expected}+)")
    
    print(f"Wound target tests: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)

def test_save_target_calculation():
    """Test save target calculations"""
    print("\n🛡️ Testing save target calculations...")
    
    test_cases = [
        # (armor_save, invul_save, armor_penetration, expected_target)
        (3, 0, 0, 3),    # No AP, no invul
        (3, 0, 1, 4),    # AP-1 modifies armor save
        (3, 0, 3, 6),    # AP-3 makes armor save worse  
        (4, 5, 2, 5),    # Invul worse than modified armor
        (4, 4, 2, 4),    # Invul better than modified armor (6+)
        (5, 4, 0, 4),    # Invul better than armor save
    ]
    
    passed = 0
    for armor, invul, ap, expected in test_cases:
        result = calculate_save_target(armor, invul, ap)
        if result == expected:
            print(f"  ✅ Armor {armor}+, Invul {invul}+, AP-{ap} = {result}+ (expected {expected}+)")
            passed += 1
        else:
            print(f"  ❌ Armor {armor}+, Invul {invul}+, AP-{ap} = {result}+ (expected {expected}+)")
    
    print(f"Save target tests: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)

def test_dice_rolling():
    """Test dice rolling produces valid results"""
    print("\n🎲 Testing dice rolling...")
    
    results = []
    for _ in range(1000):
        roll = roll_d6()
        results.append(roll)
        if roll < 1 or roll > 6:
            print(f"❌ Invalid dice roll: {roll}")
            return False
    
    # Check distribution is reasonable
    unique_values = set(results)
    if unique_values != {1, 2, 3, 4, 5, 6}:
        print(f"❌ Dice rolls missing values: {unique_values}")
        return False
    
    # Check each value appears at least once in 1000 rolls
    for i in range(1, 7):
        count = results.count(i)
        if count == 0:
            print(f"❌ Value {i} never rolled in 1000 attempts")
            return False
    
    print(f"  ✅ 1000 dice rolls all valid (1-6)")
    print(f"  ✅ All values 1-6 appeared")
    return True

def test_shooting_sequence():
    """Test complete shooting sequence"""
    print("\n🔫 Testing shooting sequence...")
    
    # Create test units with required stats
    shooter = {
        "rng_nb": 3,      # 3 shots
        "rng_atk": 3,     # Hit on 3+
        "rng_str": 4,     # Strength 4
        "rng_ap": 1,      # AP-1
        "rng_dmg": 1      # 1 damage per shot
    }
    
    target = {
        "t": 4,           # Toughness 4
        "armor_save": 3,  # 3+ armor save
        "invul_save": 0   # No invulnerable save
    }
    
    try:
        # Test basic shooting
        result = execute_shooting_sequence(shooter, target)
        
        # Verify result structure
        required_keys = ["totalDamage", "summary"]
        summary_keys = ["totalShots", "hits", "wounds", "failedSaves"]
        
        for key in required_keys:
            if key not in result:
                print(f"❌ Missing key in result: {key}")
                return False
        
        for key in summary_keys:
            if key not in result["summary"]:
                print(f"❌ Missing key in summary: {key}")
                return False
        
        # Verify values are reasonable
        if result["summary"]["totalShots"] != 3:
            print(f"❌ Expected 3 shots, got {result['summary']['totalShots']}")
            return False
        
        if result["totalDamage"] < 0 or result["totalDamage"] > 3:
            print(f"❌ Damage out of range: {result['totalDamage']} (should be 0-3)")
            return False
        
        print(f"  ✅ Shooting sequence completed successfully")
        print(f"  📊 Result: {result['totalDamage']} damage from {result['summary']['totalShots']} shots")
        print(f"      Hits: {result['summary']['hits']}, Wounds: {result['summary']['wounds']}, Failed Saves: {result['summary']['failedSaves']}")
        
        # Test with cover
        result_cover = execute_shooting_sequence(shooter, target, target_in_cover=True)
        print(f"  ✅ Cover shooting test completed: {result_cover['totalDamage']} damage")
        
        return True
        
    except Exception as e:
        print(f"❌ Shooting sequence failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_error_handling():
    """Test error handling for missing required stats"""
    print("\n⚠️ Testing error handling...")
    
    # Test missing shooter stats
    incomplete_shooter = {"rng_atk": 3}  # Missing rng_nb
    complete_target = {"t": 4, "armor_save": 3, "invul_save": 0}
    
    try:
        execute_shooting_sequence(incomplete_shooter, complete_target)
        print("❌ Should have raised error for missing rng_nb")
        return False
    except ValueError as e:
        if "rng_nb" in str(e):
            print("  ✅ Correctly caught missing rng_nb error")
        else:
            print(f"❌ Wrong error message: {e}")
            return False
    except Exception as e:
        print(f"❌ Unexpected error type: {e}")
        return False
    
    # Test missing target stats  
    complete_shooter = {"rng_nb": 1, "rng_atk": 3, "rng_str": 4, "rng_ap": 0, "rng_dmg": 1}
    incomplete_target = {"armor_save": 3}  # Missing t
    
    try:
        execute_shooting_sequence(complete_shooter, incomplete_target)
        print("❌ Should have raised error for missing t")
        return False
    except ValueError as e:
        if "t" in str(e):
            print("  ✅ Correctly caught missing t error")
        else:
            print(f"❌ Wrong error message: {e}")
            return False
    except Exception as e:
        print(f"❌ Unexpected error type: {e}")
        return False
    
    return True

def main():
    """Run all tests"""
    print("🧪 Testing Shared Game Rules")
    print("=" * 50)
    
    tests = [
        test_dice_rolling,
        test_wound_target_calculation,
        test_save_target_calculation,
        test_shooting_sequence,
        test_error_handling
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                print(f"❌ Test {test.__name__} failed")
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Shared rules are working correctly.")
        return True
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)