#!/usr/bin/env python3
"""
Test the engine's actual BFS pathfinding with the exact game state from the log.
This will show us what the engine ACTUALLY allows vs what the validator checks.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool

# Load board config
loader = get_config_loader()
board_config = loader.get_board_config()

# Build minimal game_state matching Turn 1 scenario
game_state = {
    "board_cols": 25,
    "board_rows": 21,
    "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
    "units": [
        {"id": 1, "player": 0, "col": 9, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": 2, "player": 0, "col": 11, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": 3, "player": 0, "col": 13, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": 4, "player": 0, "col": 15, "row": 12, "HP_CUR": 1, "MOVE": 6},
        {"id": 5, "player": 1, "col": 9, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": 6, "player": 1, "col": 11, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": 7, "player": 1, "col": 13, "row": 7, "HP_CUR": 1, "MOVE": 6},
        {"id": 8, "player": 1, "col": 15, "row": 7, "HP_CUR": 1, "MOVE": 6},
    ]
}

print("=" * 80)
print("ENGINE PATHFINDING TEST")
print("=" * 80)
print(f"Testing Unit 1 movement from (9, 12)")
print(f"Wall hexes loaded: {len(game_state['wall_hexes'])}")

# Test Unit 1's valid destinations
unit_1 = game_state["units"][0]
valid_dests = movement_build_valid_destinations_pool(game_state, "1")

print(f"\nEngine found {len(valid_dests)} valid destinations")
print(f"\nIs (3, 9) in valid destinations? {(3, 9) in valid_dests}")

# Show some destinations for debugging
if valid_dests:
    print(f"\nFirst 10 destinations: {sorted(valid_dests)[:10]}")

# Check specific destination
target = (3, 9)
if target in valid_dests:
    print(f"\n✅ ENGINE ALLOWS move to {target}")
    print("This contradicts the validator which says path is blocked!")
else:
    print(f"\n❌ ENGINE BLOCKS move to {target}")
    print("This matches the validator - path is genuinely blocked")

print("=" * 80)
