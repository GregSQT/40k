#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from check.check_pathfinding import load_board_config

board_size, wall_hexes = load_board_config()

# Show area around the path from (9,12) to (3,9)
print("Board area - X=wall, O=occupied, E=enemy, .=empty\n")
print("   ", end="")
for col in range(0, 16):
    print(f"{col:2}", end=" ")
print()

occupied = {(11, 12), (13, 12), (15, 12)}
enemy_positions = {(9, 7), (11, 7), (13, 7), (15, 7)}
start = (9, 12)
end = (3, 9)

for row in range(5, 15):
    print(f"{row:2}: ", end="")
    for col in range(0, 16):
        pos = (col, row)
        if pos == start:
            ch = "S"
        elif pos == end:
            ch = "D"
        elif pos in wall_hexes:
            ch = "X"
        elif pos in occupied:
            ch = "O"
        elif pos in enemy_positions:
            ch = "E"
        else:
            ch = "."
        print(f" {ch} ", end="")
    print()
