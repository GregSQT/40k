#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from check.check_pathfinding import get_hex_neighbors, load_board_config

# First invalid move: Unit 1 from (9,12) to (3,9)
start = (9, 12)
end = (3, 9)

board_size, wall_hexes = load_board_config()
print(f"Move: {start} -> {end}")

# Starting positions from log
units_p0 = [(9,12), (11,12), (13,12), (15,12)]
units_p1 = [(9,7), (11,7), (13,7), (15,7)]

# Occupied hexes (excluding unit 1)
occupied = set(units_p0[1:] + units_p1)  
enemy_positions = set(units_p1)

print(f"Occupied: {occupied}")
print(f"Enemies: {enemy_positions}")

# Manual BFS
visited = {start}
queue = [(start, 0)]
max_range = 6

while queue:
    pos, dist = queue.pop(0)
    
    if dist >= max_range:
        continue
    
    for n in get_hex_neighbors(pos[0], pos[1]):
        if n in visited:
            continue
        
        # Bounds
        if n[0] < 0 or n[0] >= 25 or n[1] < 0 or n[1] >= 21:
            continue
        
        # Wall
        if n in wall_hexes:
            if dist < 2:
                print(f"  Dist {dist+1}: {n} BLOCKED by WALL")
            continue
        
        # Occupied
        if n in occupied and n != end:
            if dist < 2:
                print(f"  Dist {dist+1}: {n} BLOCKED by OCCUPIED")
            continue
        
        visited.add(n)
        
        # Check enemy adjacent
        neighbors_of_n = set(get_hex_neighbors(n[0], n[1]))
        is_adjacent = bool(neighbors_of_n & enemy_positions)
        
        if n == end:
            print(f"\nFOUND destination at distance {dist+1}")
            print(f"  Adjacent to enemy? {is_adjacent}")
            if is_adjacent:
                print(f"  -> INVALID (cannot end adjacent to enemy)")
            else:
                print(f"  -> Check why checker says invalid...")
            break
        
        if is_adjacent:
            if dist < 2:
                print(f"  Dist {dist+1}: {n} BLOCKED by ENEMY ADJACENCY")
            continue
        
        queue.append((n, dist + 1))
        if dist == 0:
            print(f"  Dist {dist+1}: {n} added to queue")

if end not in visited:
    print(f"\nNOT FOUND - destination unreachable")
