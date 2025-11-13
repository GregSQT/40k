#!/usr/bin/env python3
"""
Quick test to verify movement destination selection fix.
This script tests that the agent can choose between different movement destinations.
"""

import sys
import os

# Add project root to path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from engine.w40k_core import W40KEngine
import numpy as np

def test_movement_destination_selection():
    """Test that agent can select different movement destinations."""

    print("=" * 80)
    print("TESTING MOVEMENT DESTINATION SELECTION FIX")
    print("=" * 80)

    # Create minimal config for testing
    config = {
        "board": {
            "cols": 20,
            "rows": 15,
            "wall_hexes": []
        },
        "units": [
            {
                "id": "1",
                "player": 0,
                "col": 10,
                "row": 7,
                "unitType": "SpaceMarine_Infantry_Troop_RangedSwarm",
                "HP_CUR": 2,
                "HP_MAX": 2,
                "MOVE": 6,
                "T": 4,
                "ARMOR_SAVE": 3,
                "INVUL_SAVE": 0,
                "LD": 6,
                "OC": 2,
                "RNG_RNG": 24,
                "RNG_NB": 2,
                "RNG_ATK": 3,
                "RNG_STR": 4,
                "RNG_AP": 1,
                "RNG_DMG": 1,
                "CC_NB": 3,
                "CC_RNG": 1,
                "CC_ATK": 3,
                "CC_STR": 4,
                "CC_AP": 0,
                "CC_DMG": 1
            }
        ],
        "observation_params": {
            "obs_size": 295,
            "perception_radius": 25,
            "max_nearby_units": 10,
            "max_valid_targets": 5
        },
        "max_turns_per_episode": 5,
        "gym_training_mode": True,
        "pve_mode": False,
        "controlled_player": 0
    }

    # Initialize engine
    engine = W40KEngine(config=config)
    obs, info = engine.reset()

    print(f"✓ Engine initialized")
    print(f"  Phase: {engine.game_state['phase']}")
    print(f"  Unit position: ({engine.game_state['units'][0]['col']}, {engine.game_state['units'][0]['row']})")

    # Step 1: Try action 0 (should activate unit and wait for destination)
    print("\n" + "-" * 80)
    print("STEP 1: Activate unit (action 0)")
    action_mask = engine.get_action_mask()
    print(f"  Action mask: {action_mask}")

    obs, reward, terminated, truncated, info = engine.step(0)

    print(f"  Result: {info.get('result', {})}")
    print(f"  Phase after: {engine.game_state['phase']}")

    # Check if destinations are pending
    if "pending_movement_destinations" in engine.game_state:
        destinations = engine.game_state["pending_movement_destinations"]
        print(f"  ✓ Destinations pending: {len(destinations)} destinations available")
        print(f"    Destinations: {destinations[:4]}")  # Show first 4

        # Step 2: Choose destination (action 0-3 should pick different destinations)
        print("\n" + "-" * 80)
        print("STEP 2: Choose destination (action 1 = 2nd destination)")
        action_mask = engine.get_action_mask()
        print(f"  Action mask: {action_mask}")

        unit_before = engine.game_state['units'][0]
        pos_before = (unit_before['col'], unit_before['row'])

        obs, reward, terminated, truncated, info = engine.step(1)

        unit_after = engine.game_state['units'][0]
        pos_after = (unit_after['col'], unit_after['row'])

        print(f"  Position before: {pos_before}")
        print(f"  Position after:  {pos_after}")

        if pos_before != pos_after:
            print(f"  ✓ Unit moved successfully!")
            print(f"  ✓ Selected destination: {pos_after}")

            # Verify it matches the 2nd destination (action 1)
            if len(destinations) > 1 and pos_after == destinations[1]:
                print(f"  ✓ CORRECT: Action 1 selected destination[1]")
                return True
            else:
                print(f"  ⚠ WARNING: Expected {destinations[1]}, got {pos_after}")
                return False
        else:
            print(f"  ✗ FAILED: Unit did not move")
            return False
    else:
        print(f"  ✗ FAILED: No pending destinations found")
        print(f"  Game state keys: {engine.game_state.keys()}")
        return False

if __name__ == "__main__":
    try:
        success = test_movement_destination_selection()
        print("\n" + "=" * 80)
        if success:
            print("✓ TEST PASSED: Movement destination selection works correctly")
            sys.exit(0)
        else:
            print("✗ TEST FAILED: Movement destination selection not working")
            sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)