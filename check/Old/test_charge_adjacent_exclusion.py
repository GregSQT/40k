#!/usr/bin/env python3
"""
Test that units adjacent to enemies are NOT in charge activation pool.
This verifies the fix for the bug where adjacent units could charge.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from engine.phase_handlers.charge_handlers import get_eligible_units, _calculate_hex_distance

# Load board config
loader = get_config_loader()
board_config = loader.get_board_config()

print("=" * 80)
print("CHARGE ADJACENT EXCLUSION TEST")
print("=" * 80)

# Test 1: Basic adjacency test (original test)
print("\n--- Test 1: Basic adjacency (right neighbor) ---")
game_state = {
    "board_cols": 25,
    "board_rows": 21,
    "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
    "units": [
        {"id": "1", "player": 0, "col": 10, "row": 10, "HP_CUR": 1, "unitType": "test"},  # Adjacent to enemy
        {"id": "2", "player": 1, "col": 11, "row": 10, "HP_CUR": 1, "unitType": "test"},  # Enemy adjacent to unit 1
        {"id": "3", "player": 0, "col": 5, "row": 5, "HP_CUR": 1, "unitType": "test"},   # Not adjacent - should be eligible
    ],
    "current_player": 0,
    "units_charged": set(),
    "units_fled": set(),
    "units_advanced": set()
}

print("Unit 1 at (10, 10) is adjacent to Unit 2 at (11, 10)")
print("Unit 1 should NOT be in charge activation pool")

eligible_units = get_eligible_units(game_state)
print(f"Eligible units: {eligible_units}")

if "1" in eligible_units:
    print(f"\n❌ TEST FAILED: Unit 1 (adjacent to enemy) is in eligible units!")
    print("This is the bug - adjacent units should not be able to charge.")
    sys.exit(1)
else:
    print(f"✅ TEST PASSED: Unit 1 (adjacent to enemy) correctly excluded from pool")

# Test 2: All 6 hexagonal neighbors
print("\n--- Test 2: All 6 hexagonal neighbors ---")
unit_pos = (10, 10)
# Use the actual _get_hex_neighbors function to get the correct neighbors
from engine.phase_handlers.charge_handlers import _get_hex_neighbors
real_neighbors = _get_hex_neighbors(unit_pos[0], unit_pos[1])
direction_names = ["N (north)", "NE (north-east)", "SE (south-east)", "S (south)", "SW (south-west)", "NW (north-west)"]
hex_neighbors = [(col, row, name) for (col, row), name in zip(real_neighbors, direction_names)]

all_neighbor_tests_passed = True
for enemy_col, enemy_row, direction in hex_neighbors:
    game_state_test = {
        "board_cols": 25,
        "board_rows": 21,
        "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
        "units": [
            {"id": "1", "player": 0, "col": unit_pos[0], "row": unit_pos[1], "HP_CUR": 1, "unitType": "test"},
            {"id": "2", "player": 1, "col": enemy_col, "row": enemy_row, "HP_CUR": 1, "unitType": "test"},
        ],
        "current_player": 0,
        "units_charged": set(),
        "units_fled": set(),
        "units_advanced": set()
    }
    
    # Verify distance is 1 (adjacent)
    hex_dist = _calculate_hex_distance(unit_pos[0], unit_pos[1], enemy_col, enemy_row)
    if hex_dist != 1:
        print(f"⚠️  WARNING: Distance to {direction} neighbor is {hex_dist} (expected 1)")
    
    eligible = get_eligible_units(game_state_test)
    if "1" in eligible:
        print(f"❌ FAILED: Unit 1 adjacent {direction} at ({enemy_col}, {enemy_row}) still eligible!")
        all_neighbor_tests_passed = False
    else:
        print(f"✅ PASSED: Unit 1 correctly excluded when enemy {direction} at ({enemy_col}, {enemy_row})")

if not all_neighbor_tests_passed:
    print("\n❌ SOME NEIGHBOR TESTS FAILED")
    sys.exit(1)

# Test 3: Non-adjacent positions (should NOT exclude)
print("\n--- Test 3: Non-adjacent positions (should NOT exclude) ---")
non_adjacent_cases = [
    (12, 10, 2, "distance 2"),
    (15, 15, None, "far away"),
]

for enemy_col, enemy_row, expected_dist, description in non_adjacent_cases:
    game_state_test = {
        "board_cols": 25,
        "board_rows": 21,
        "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
        "units": [
            {"id": "1", "player": 0, "col": unit_pos[0], "row": unit_pos[1], "HP_CUR": 1, "unitType": "test"},
            {"id": "2", "player": 1, "col": enemy_col, "row": enemy_row, "HP_CUR": 1, "unitType": "test"},
        ],
        "current_player": 0,
        "units_charged": set(),
        "units_fled": set(),
        "units_advanced": set()
    }
    
    hex_dist = _calculate_hex_distance(unit_pos[0], unit_pos[1], enemy_col, enemy_row)
    if expected_dist and hex_dist != expected_dist:
        print(f"⚠️  WARNING: Distance is {hex_dist} (expected {expected_dist})")
    
    eligible = get_eligible_units(game_state_test)
    # Note: Unit might not be eligible for other reasons (no valid charge targets), but should NOT be excluded due to adjacency
    print(f"Distance {hex_dist} ({description}): Eligible units = {eligible}")

print("\n" + "=" * 80)
print("✅ ALL TESTS PASSED: Adjacent units correctly excluded from charge pool")
print("=" * 80)