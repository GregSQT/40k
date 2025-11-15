#!/usr/bin/env python3
"""
Trace BFS pathfinding WITH enemy adjacency check to see where it blocks.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from check.check_pathfinding import get_hex_neighbors, load_board_config

# Load board config
board_size, wall_hexes = load_board_config()
cols, rows = board_size

# Setup from training log - Turn 1
# Player 0 units (friendly): 1(9,12), 2(11,12), 3(13,12), 4(15,12)
# Player 1 units (enemies): 5(9,7), 6(11,7), 7(13,7), 8(15,7)
# Unit 1 at (9,12) trying to move to (3,9)

start_pos = (9, 12)
end_pos = (3, 9)
move_range = 6

# Units that are NOT the moving unit (Unit 1)
occupied_hexes = {(11, 12), (13, 12), (15, 12), (11, 7), (13, 7), (15, 7), (9, 7)}

# Enemy positions for Unit 1 (Player 0)
enemy_positions = {(9, 7), (11, 7), (13, 7), (15, 7)}

print("=" * 80)
print(f"TRACING BFS WITH ENEMY ADJACENCY: {start_pos} -> {end_pos}")
print("=" * 80)
print(f"Move range: {move_range}")
print(f"Occupied: {occupied_hexes}")
print(f"Enemies: {enemy_positions}")
print(f"Walls: {len(wall_hexes)} hexes")

# Helper: Check if hex is adjacent to any enemy
def is_adjacent_to_enemy(col: int, row: int) -> bool:
    hex_neighbors = set(get_hex_neighbors(col, row))
    return bool(hex_neighbors & enemy_positions)

# BFS with detailed logging
visited = {start_pos}
queue = [(start_pos, 0)]
found = False

step = 0
while queue and step < 100:
    step += 1
    current_pos, current_dist = queue.pop(0)
    current_col, current_row = current_pos

    if step <= 15 or current_pos == end_pos:
        print(f"\nStep {step}: Exploring {current_pos} at distance {current_dist}")

    # Max range check
    if current_dist >= move_range:
        if step <= 15:
            print(f"  -> At max range, stopping exploration")
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
            if step <= 15:
                print(f"  {neighbor_pos}: OUT OF BOUNDS")
            continue

        # Check walls
        if neighbor_pos in wall_hexes:
            if step <= 15:
                print(f"  {neighbor_pos}: WALL")
            continue

        # Check occupied (but destination is OK)
        if neighbor_pos in occupied_hexes and neighbor_pos != end_pos:
            if step <= 15:
                print(f"  {neighbor_pos}: OCCUPIED")
            continue

        # Mark visited
        visited.add(neighbor_pos)

        # Found destination?
        if neighbor_pos == end_pos:
            print(f"\n🎯 FOUND DESTINATION at step {step}!")
            print(f"   Path length: {current_dist + 1} hexes")
            found = True
            break

        # CRITICAL: Check if adjacent to enemy BEFORE adding to queue
        if is_adjacent_to_enemy(neighbor_col, neighbor_row):
            if step <= 15:
                print(f"  {neighbor_pos}: OK but ADJACENT TO ENEMY - cannot explore further from here")
            # Don't add to queue - can't move through hexes adjacent to enemies
            continue

        # Add to queue
        queue.append((neighbor_pos, current_dist + 1))
        if step <= 15:
            print(f"  {neighbor_pos}: OK, added to queue (dist={current_dist + 1})")

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
    print("(Blocked by walls, occupied hexes, or enemy adjacency)")
print("=" * 80)
