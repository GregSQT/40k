#!/usr/bin/env python3
"""
Script pour debugger le calcul LoS pour l'exemple concret :
Episode 2, Turn 1, Unit 1(21,6) SHOT at Unit 10(14,7)
"""

import sys
import os

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from engine.combat_utils import get_hex_line

def debug_los(shooter_col, shooter_row, target_col, target_row, wall_hexes):
    """Debug LoS calculation"""
    print(f"Shooter: ({shooter_col}, {shooter_row})")
    print(f"Target: ({target_col}, {target_row})")
    print(f"Walls: {wall_hexes}")
    print()
    
    # Get hex path
    hex_path = get_hex_line(shooter_col, shooter_row, target_col, target_row)
    print(f"Hex path ({len(hex_path)} hexes):")
    for i, (col, row) in enumerate(hex_path):
        is_wall = (col, row) in wall_hexes
        marker = " [WALL]" if is_wall else ""
        print(f"  {i}: ({col}, {row}){marker}")
    
    print()
    # Check LoS
    blocking_walls = []
    for i, (col, row) in enumerate(hex_path):
        if i == 0 or i == len(hex_path) - 1:
            continue  # Skip start and end
        if (col, row) in wall_hexes:
            blocking_walls.append((col, row))
    
    if blocking_walls:
        print(f"❌ LoS BLOCKED by walls: {blocking_walls}")
        return False
    else:
        print("✅ LoS CLEAR")
        return True

if __name__ == "__main__":
    # Example from analyzer_output.txt
    # Episode 2, Turn 1, Unit 1(21,6) SHOT at Unit 10(14,7)
    shooter_col, shooter_row = 21, 6
    target_col, target_row = 14, 7
    
    # We need to get walls from the log - for now, use empty set
    # User should provide walls from the log
    if len(sys.argv) > 1:
        # Parse walls from command line: "col1,row1 col2,row2 ..."
        wall_hexes = set()
        for wall_str in sys.argv[1:]:
            col, row = map(int, wall_str.split(','))
            wall_hexes.add((col, row))
    else:
        wall_hexes = set()
        print("Usage: python ai/debug_los.py col1,row1 col2,row2 ...")
        print("Example: python ai/debug_los.py 17,6 18,6 19,6")
        print()
        print("Running with empty walls (will show path only):")
        print()
    
    debug_los(shooter_col, shooter_row, target_col, target_row, wall_hexes)
