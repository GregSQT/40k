#!/usr/bin/env python3
"""
Trace BFS pathfinding step-by-step to find where it fails.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check.check_pathfinding import get_hex_neighbors, load_board_config, is_reachable

# Load board config
board_size, wall_hexes = load_board_config()
cols, rows = board_size

# Setup from training log
occupied_hexes = {(11, 7), (13, 7), (15, 7), (11, 12), (13, 12), (15, 12), (9, 7)}

start_col, start_row = 9, 12
end_col, end_row = 3, 9
move_range = 6
start_pos = (start_col, start_row)
end_pos = (end_col, end_row)

print("=" * 80)
print(f"TRACING BFS: {start_pos} -> {end_pos}")
print("=" * 80)
print(f"Move range: {move_range}")
print(f"Occupied: {occupied_hexes}")
print(f"Walls: {len(wall_hexes)} hexes")

# BFS with detailed logging
visited = {start_pos}
queue = [(start_pos, 0)]
found = False

step = 0
while queue and step < 100:  # Safety limit
    step += 1
    current_pos, current_dist = queue.pop(0)
    current_col, current_row = current_pos

    if step <= 10 or current_pos == end_pos:
        print(f"\nStep {step}: Exploring {current_pos} at distance {current_dist}")

    # Max range check
    if current_dist >= move_range:
        if step <= 10:
            print(f"  -> At max range, stopping exploration from this hex")
        continue

    # Get neighbors
    neighbors = get_hex_neighbors(current_col, current_row)

    for neighbor_col, neighbor_row in neighbors:
        neighbor_pos = (neighbor_col, neighbor_row)

        # Skip if visited
        if neighbor_pos in visited:
            continue

        # Check bounds
        if neighbor_col < 0 or neighbor_col >= cols or neighbor_row < 0 or neighbor_row >= rows:
            if step <= 10:
                print(f"  -> {neighbor_pos}: OUT OF BOUNDS")
            continue

        # Check walls
        if neighbor_pos in wall_hexes:
            if step <= 10:
                print(f"  -> {neighbor_pos}: WALL")
            continue

        # Check occupied (but destination is OK)
        if neighbor_pos in occupied_hexes and neighbor_pos != end_pos:
            if step <= 10:
                print(f"  -> {neighbor_pos}: OCCUPIED")
            continue

        # Mark visited
        visited.add(neighbor_pos)

        # Found destination?
        if neighbor_pos == end_pos:
            print(f"\n🎯 FOUND DESTINATION at step {step}!")
            print(f"   Path length: {current_dist + 1} hexes")
            found = True
            break

        # Add to queue
        queue.append((neighbor_pos, current_dist + 1))
        if step <= 10:
            print(f"  -> {neighbor_pos}: OK, added to queue (dist={current_dist + 1})")

    if found:
        break

print("\n" + "=" * 80)
if found:
    print("RESULT: PATH FOUND")
else:
    print("RESULT: PATH NOT FOUND")
    print(f"Explored {len(visited)} hexes")
    print(f"\nEnd position {end_pos} reachable? NO")
    print("Reason: BFS exhausted all reachable hexes within range")
print("=" * 80)
