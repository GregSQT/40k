#!/usr/bin/env python3
"""
Debug specific move from training log to find discrepancy.

From log: Unit 1 moved from (9, 12) to (3, 9) - validator says INVALID
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check.check_pathfinding import is_reachable, calculate_hex_distance, load_board_config

# Load board config
board_size, wall_hexes = load_board_config()

# Scenario: Turn 1, Player 0's first unit
# Units at start positions (from log)
units = [
    {"id": 1, "player": 0, "col": 9, "row": 12},   # This is the moving unit
    {"id": 2, "player": 0, "col": 11, "row": 12},
    {"id": 3, "player": 0, "col": 13, "row": 12},
    {"id": 4, "player": 0, "col": 15, "row": 12},
    {"id": 5, "player": 1, "col": 9, "row": 7},
    {"id": 6, "player": 1, "col": 11, "row": 7},
    {"id": 7, "player": 1, "col": 13, "row": 7},
    {"id": 8, "player": 1, "col": 15, "row": 7},
]

# Unit 1 is moving, so it's not in occupied hexes
moving_unit = units[0]
other_units = units[1:]

occupied_hexes = set((u["col"], u["row"]) for u in other_units)

# The move
start_col, start_row = 9, 12
end_col, end_row = 3, 9
move_range = 6

print("=" * 80)
print("DEBUG: Unit 1 move from (9, 12) to (3, 9)")
print("=" * 80)

# Calculate distance
dist = calculate_hex_distance(start_col, start_row, end_col, end_row)
print(f"\nHex distance: {dist}")
print(f"Move range: {move_range}")
print(f"Within range? {dist <= move_range}")

# Check if reachable via BFS
reachable = is_reachable(
    start_col, start_row,
    end_col, end_row,
    move_range,
    wall_hexes,
    occupied_hexes,
    board_size
)

print(f"\nValidator says reachable? {reachable}")

if not reachable:
    print("\n[VALIDATOR BUG] Path blocked - but game allowed it!")
    print("Possible causes:")
    print("1. Validator's BFS is too strict")
    print("2. Game engine's BFS is too permissive")
    print("3. Occupied hexes different between validator and game")
else:
    print("\n[VALIDATOR OK] Path is reachable")
    print("Something else is wrong with the validator")

print(f"\nOccupied hexes: {occupied_hexes}")
print(f"Wall hexes count: {len(wall_hexes)}")
