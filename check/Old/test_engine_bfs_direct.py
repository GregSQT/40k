#!/usr/bin/env python3
"""
Direct test of engine's BFS pathfinding WITHOUT full engine initialization.
This avoids NumPy segfaults by testing the pathfinding logic in isolation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import minimal dependencies
from engine.combat_utils import get_hex_neighbors
from engine.phase_handlers.movement_handlers import _is_traversable_hex

# Load board config manually
import json
with open("config/board_config.json", "r") as f:
    board_config = json.load(f)

wall_hexes = set(map(tuple, board_config["default"]["wall_hexes"]))
board_cols = board_config["default"]["cols"]
board_rows = board_config["default"]["rows"]

# Build minimal game_state matching Turn 1 scenario
game_state = {
    "board_cols": board_cols,
    "board_rows": board_rows,
    "wall_hexes": wall_hexes,
    "units": [
        {"id": "1", "player": 0, "col": 9, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": "2", "player": 0, "col": 11, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": "3", "player": 0, "col": 13, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": "4", "player": 0, "col": 15, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": "5", "player": 1, "col": 9, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": "6", "player": 1, "col": 11, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": "7", "player": 1, "col": 13, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": "8", "player": 1, "col": 15, "row": 7, "HP_CUR": 1, "MOVE": 6},
    ]
}

# Manual BFS using engine's logic
unit = game_state["units"][0]  # Unit 1 at (9, 12)
start_pos = (9, 12)
move_range = 6

print("=" * 80)
print("ENGINE BFS TEST (Direct)")
print("=" * 80)
print(f"Unit 1 at {start_pos}, range={move_range}")
print(f"Wall hexes: {len(wall_hexes)}")
print(f"Other units: {[(u['id'], u['col'], u['row']) for u in game_state['units'] if u['id'] != '1']}")

visited = {start_pos: 0}
queue = [(start_pos, 0)]
valid_destinations = []

step = 0
while queue and step < 20:
    step += 1
    current_pos, current_dist = queue.pop(0)
    current_col, current_row = current_pos

    if step <= 15:
        print(f"\nStep {step}: pos={current_pos} dist={current_dist}")

    if current_dist >= move_range:
        if step <= 15:
            print("  -> At max range")
        continue

    neighbors = get_hex_neighbors(current_col, current_row)

    for neighbor_col, neighbor_row in neighbors:
        neighbor_pos = (neighbor_col, neighbor_row)
        neighbor_dist = current_dist + 1

        if neighbor_pos in visited:
            continue

        # Check traversability
        is_traversable = _is_traversable_hex(game_state, neighbor_col, neighbor_row, unit)

        if not is_traversable:
            if step <= 15:
                if neighbor_pos in wall_hexes:
                    print(f"  {neighbor_pos}: WALL")
                else:
                    print(f"  {neighbor_pos}: OCCUPIED")
            continue

        visited[neighbor_pos] = neighbor_dist
        valid_destinations.append(neighbor_pos)

        if step <= 15:
            print(f"  {neighbor_pos}: OK (dist={neighbor_dist})")

        if neighbor_pos == (3, 9):
            print(f"\n🎯 TARGET (3,9) FOUND at step {step}! Distance: {neighbor_dist}")

        queue.append((neighbor_pos, neighbor_dist))

print(f"\n" + "=" * 80)
print(f"BFS COMPLETE")
print(f"=" * 80)
print(f"Hexes explored: {len(visited)}")
print(f"Valid destinations: {len(valid_destinations)}")
print(f"Target (3,9) reachable? {(3, 9) in valid_destinations}")
print("=" * 80)
