#!/usr/bin/env python3
"""Debug a specific invalid move."""
import json
import sys
sys.path.insert(0, '.')
from check.check_pathfinding import get_hex_neighbors, is_reachable, load_board_config

start = (9, 12)
end = (3, 9)
move_range = 6

board_size, wall_hexes = load_board_config()
occupied = {(11, 12), (13, 12), (15, 12), (9, 7), (11, 7), (13, 7), (15, 7)}
enemy_positions = {(9, 7), (11, 7), (13, 7), (15, 7)}

print(f"Move: {start} -> {end}, range={move_range}")
print(f"Board: {board_size}, Walls: {len(wall_hexes)}, Occupied: {len(occupied)}")

result = is_reachable(start[0], start[1], end[0], end[1], move_range, wall_hexes, occupied, board_size, enemy_positions)
print(f"\nis_reachable(): {result}")

print(f"\nNeighbors of destination {end}:")
for n in get_hex_neighbors(end[0], end[1]):
    flags = []
    if n in wall_hexes: flags.append("WALL")
    if n in occupied: flags.append("OCC")
    if n in enemy_positions: flags.append("ENEMY")
    print(f"  {n}: {flags if flags else 'EMPTY'}")
