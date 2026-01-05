#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from check.check_pathfinding import get_hex_neighbors, load_board_config

# Enemy at (9,7) - what hexes are adjacent?
enemy = (9, 7)
neighbors = get_hex_neighbors(enemy[0], enemy[1])
print(f"Enemy at {enemy} blocks movement THROUGH these hexes:")
for n in neighbors:
    print(f"  {n}")

# Can we reach (9,9) from (9,12)?
start = (9, 12)
target1 = (9, 9)
print(f"\n{start} -> {target1}: Can we get there?")
print(f"  {target1} is adjacent to enemy? {target1 in neighbors}")
