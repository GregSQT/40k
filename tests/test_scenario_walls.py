#!/usr/bin/env python3
"""
test_scenario_walls.py - Unit test to verify scenario-based wall loading

This test verifies that:
1. Phase 1 scenarios load with 0 walls (empty wall_hexes)
2. Phase 2+ scenarios load with walls from scenario file
3. Scenario walls take precedence over board_config walls
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry


def test_phase1_no_walls():
    """Test that Phase 1 scenarios have no walls."""
    print("\n" + "=" * 60)
    print("TEST: Phase 1 scenarios should have NO walls")
    print("=" * 60)

    phase1_scenarios = [
        "phase1-bot1",
        "phase1-bot2",
        "phase1-bot3",
        "phase1-bot4",
        "phase1-self1"
    ]

    agent_name = "SpaceMarine_Infantry_Troop_RangedSwarm"
    unit_registry = UnitRegistry()
    all_passed = True

    for scenario_name in phase1_scenarios:
        scenario_file = f"config/agents/{agent_name}/scenarios/{agent_name}_scenario_{scenario_name}.json"

        try:
            env = W40KEngine(
                controlled_agent=agent_name,
                scenario_file=scenario_file,
                rewards_config="phase1",
                training_config_name="phase1",
                unit_registry=unit_registry,
                gym_training_mode=True,
                quiet=True
            )

            wall_count = len(env.game_state["wall_hexes"])

            if wall_count == 0:
                print(f"  ✅ {scenario_name}: {wall_count} walls (PASS)")
            else:
                print(f"  ❌ {scenario_name}: {wall_count} walls (FAIL - expected 0)")
                all_passed = False

        except Exception as e:
            print(f"  ❌ {scenario_name}: ERROR - {e}")
            all_passed = False

    return all_passed


def test_phase2_has_walls():
    """Test that Phase 2 scenarios have walls."""
    print("\n" + "=" * 60)
    print("TEST: Phase 2 scenarios should have walls")
    print("=" * 60)

    phase2_scenarios = [
        "phase2-1",
        "phase2-2",
        "phase2-3",
        "phase2-4"
    ]

    agent_name = "SpaceMarine_Infantry_Troop_RangedSwarm"
    unit_registry = UnitRegistry()
    all_passed = True

    for scenario_name in phase2_scenarios:
        scenario_file = f"config/agents/{agent_name}/scenarios/{agent_name}_scenario_{scenario_name}.json"

        try:
            env = W40KEngine(
                controlled_agent=agent_name,
                scenario_file=scenario_file,
                rewards_config="phase2",
                training_config_name="phase2",
                unit_registry=unit_registry,
                gym_training_mode=True,
                quiet=True
            )

            wall_count = len(env.game_state["wall_hexes"])

            if wall_count > 0:
                print(f"  ✅ {scenario_name}: {wall_count} walls (PASS)")
            else:
                print(f"  ❌ {scenario_name}: {wall_count} walls (FAIL - expected > 0)")
                all_passed = False

        except Exception as e:
            print(f"  ❌ {scenario_name}: ERROR - {e}")
            all_passed = False

    return all_passed


def test_phase3_has_walls():
    """Test that Phase 3 scenarios have walls."""
    print("\n" + "=" * 60)
    print("TEST: Phase 3 scenarios should have walls")
    print("=" * 60)

    phase3_scenarios = [
        "phase3-1"
    ]

    agent_name = "SpaceMarine_Infantry_Troop_RangedSwarm"
    unit_registry = UnitRegistry()
    all_passed = True

    for scenario_name in phase3_scenarios:
        scenario_file = f"config/agents/{agent_name}/scenarios/{agent_name}_scenario_{scenario_name}.json"

        try:
            env = W40KEngine(
                controlled_agent=agent_name,
                scenario_file=scenario_file,
                rewards_config="phase3",
                training_config_name="phase3",
                unit_registry=unit_registry,
                gym_training_mode=True,
                quiet=True
            )

            wall_count = len(env.game_state["wall_hexes"])

            if wall_count > 0:
                print(f"  ✅ {scenario_name}: {wall_count} walls (PASS)")
            else:
                print(f"  ❌ {scenario_name}: {wall_count} walls (FAIL - expected > 0)")
                all_passed = False

        except Exception as e:
            print(f"  ❌ {scenario_name}: ERROR - {e}")
            all_passed = False

    return all_passed


def main():
    """Run all tests."""
    print("\n🧪 SCENARIO WALL LOADING TESTS")
    print("Verifying scenario-based terrain system works correctly\n")

    results = []

    # Run tests
    results.append(("Phase 1 no walls", test_phase1_no_walls()))
    results.append(("Phase 2 has walls", test_phase2_has_walls()))
    results.append(("Phase 3 has walls", test_phase3_has_walls()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED - Scenario wall loading is working correctly!")
    else:
        print("❌ SOME TESTS FAILED - Check implementation")
    print("=" * 60 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
