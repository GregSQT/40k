#!/usr/bin/env python3
"""Trace BFS pathfinding step-by-step."""
import json
import sys
sys.path.insert(0, '.')
from check.check_pathfinding import get_hex_neighbors, load_board_config

start = (9, 12)
end = (3, 9)
move_range = 6

board_size, wall_hexes = load_board_config()
cols, rows = board_size
occupied = {(11, 12), (13, 12), (15, 12), (9, 7), (11, 7), (13, 7), (15, 7)}
enemy_positions = {(9, 7), (11, 7), (13, 7), (15, 7)}

print(f"BFS from {start} to {end}, range={move_range}\n")

visited = {start}
queue = [(start, 0)]
iteration = 0

while queue and iteration < 100:
    iteration += 1
    current_pos, current_dist = queue.pop(0)
    
    if current_dist >= move_range:
        continue
    
    neighbors = get_hex_neighbors(current_pos[0], current_pos[1])
    
    for n_col, n_row in neighbors:
        n_pos = (n_col, n_row)
        
        if n_pos in visited:
            continue
        
        # Boundary check
        if n_col < 0 or n_col >= cols or n_row < 0 or n_row >= rows:
            continue
        
        # Wall check
        if n_pos in wall_hexes:
            if iteration <= 10:
                print(f"  [{current_dist+1}] {n_pos} - BLOCKED: WALL")
            continue
        
        # Occupied check
        if n_pos in occupied and n_pos != end:
            if iteration <= 10:
                print(f"  [{current_dist+1}] {n_pos} - BLOCKED: OCCUPIED")
            continue
        
        visited.add(n_pos)
        
        if n_pos == end:
            print(f"\n✓ FOUND {end} at distance {current_dist+1}")
            # Check adjacency
            neighbors_of_dest = set(get_hex_neighbors(n_col, n_row))
            if neighbors_of_dest & enemy_positions:
                print(f"  But ADJACENT TO ENEMY - would be INVALID")
            sys.exit(0)
        
        # Enemy adjacency check
        neighbors_set = set(get_hex_neighbors(n_col, n_row))
        if neighbors_set & enemy_positions:
            if iteration <= 10:
                print(f"  [{current_dist+1}] {n_pos} - BLOCKED: ADJACENT TO ENEMY")
            continue
        
        queue.append((n_pos, current_dist + 1))
        if iteration <= 10:
            print(f"  [{current_dist+1}] {n_pos} - added to queue")

print(f"\n✗ NOT FOUND after {iteration} iterations")
print(f"Visited {len(visited)} hexes")
