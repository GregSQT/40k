#!/usr/bin/env python3
"""
Debug one of the invalid moves from the new log to understand why it's flagged.

First invalid move from the new log:
Line 46: Unit 7 moved from (13, 10) to (11, 11)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check.check_pathfinding import is_reachable, calculate_hex_distance, load_board_config

# Load board config
board_size, wall_hexes = load_board_config()

# From the log, this is episode 1 (first episode after training start)
# Let me manually trace what the units should be at Turn 2

# We need to find what the initial positions were and track them
# For now, let's test the specific move in isolation

# The move
start_col, start_row = 13, 10
end_col, end_row = 11, 11
move_range = 6

print("=" * 80)
print("DEBUG: Unit 7 move from (13, 10) to (11, 11)")
print("=" * 80)

# Calculate distance
dist = calculate_hex_distance(start_col, start_row, end_col, end_row)
print(f"\nHex distance: {dist}")
print(f"Move range: {move_range}")
print(f"Within range? {dist <= move_range}")

# For this test, we need to know what other units were present
# From the log context, this is Turn 2, Player 1, so we need to know:
# 1. Where all units are at this point
# 2. Which hexes are occupied
# 3. Which hexes have enemies

# Let's test with NO occupied hexes first (best case)
occupied_hexes = set()
enemy_positions = set()

reachable = is_reachable(
    start_col, start_row,
    end_col, end_row,
    move_range,
    wall_hexes,
    occupied_hexes,
    board_size,
    enemy_positions
)

print(f"\nValidator says reachable (no obstacles)? {reachable}")

if not reachable:
    print("\n[VALIDATOR BUG] Path blocked even with NO obstacles!")
    print("This means there's a wall in the way OR a fundamental pathfinding issue")

    # Check if destination is a wall
    if (end_col, end_row) in wall_hexes:
        print(f"ERROR: Destination {(end_col, end_row)} is a WALL!")

    # Check if start is a wall (shouldn't happen)
    if (start_col, start_row) in wall_hexes:
        print(f"ERROR: Start position {(start_col, start_row)} is a WALL!")

    # Manually trace path
    print("\nManually checking path hexes...")
    from check.check_pathfinding import get_hex_neighbors

    # BFS to find path
    visited = {(start_col, start_row)}
    queue = [((start_col, start_row), 0, [(start_col, start_row)])]

    while queue:
        (col, row), dist, path = queue.pop(0)

        if dist >= move_range:
            continue

        for ncol, nrow in get_hex_neighbors(col, row):
            if (ncol, nrow) in visited:
                continue
            if ncol < 0 or ncol >= board_size[0] or nrow < 0 or nrow >= board_size[1]:
                continue

            new_path = path + [(ncol, nrow)]

            if (ncol, nrow) == (end_col, end_row):
                print(f"Found path: {new_path}")
                print(f"Path length: {len(new_path) - 1}")

                # Check each hex in path
                for i, (pcol, prow) in enumerate(new_path):
                    is_wall = (pcol, prow) in wall_hexes
                    print(f"  Step {i}: ({pcol}, {prow}) {'[WALL!]' if is_wall else '[OK]'}")
                break

            if (ncol, nrow) not in wall_hexes:
                visited.add((ncol, nrow))
                queue.append(((ncol, nrow), dist + 1, new_path))
else:
    print("\n[VALIDATOR OK] Path is reachable with no obstacles")
    print("The issue must be with occupied hexes or enemy adjacency in the actual game")
