#!/usr/bin/env python3
"""
Test that charge destinations never include occupied hexes.

This test verifies the fix for the bug where Unit 3 charged onto Unit 6's hex (23, 6).
The charge_build_valid_destinations_pool function should NEVER include an occupied hex
as a valid destination.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from engine.phase_handlers.charge_handlers import charge_build_valid_destinations_pool

# Load board config
loader = get_config_loader()
board_config = loader.get_board_config()

# Build game_state matching the bug scenario:
# Unit 3 (P0) at (18, 6) trying to charge
# Unit 6 (P1) at (23, 6) - this hex should NEVER be a valid destination
game_state = {
    "board_cols": 25,
    "board_rows": 21,
    "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
    "units": [
        {"id": "1", "player": 0, "col": 21, "row": 7, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "2", "player": 0, "col": 5, "row": 7, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "3", "player": 0, "col": 18, "row": 6, "HP_CUR": 1, "CC_RNG": 1},  # Charging unit
        {"id": "4", "player": 0, "col": 5, "row": 8, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "5", "player": 1, "col": 10, "row": 0, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "6", "player": 1, "col": 23, "row": 6, "HP_CUR": 1, "CC_RNG": 1},  # OCCUPIED HEX - should NOT be in destinations
        {"id": "7", "player": 1, "col": 5, "row": 7, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "8", "player": 1, "col": 5, "row": 8, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "9", "player": 1, "col": 16, "row": 5, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "10", "player": 1, "col": 14, "row": 7, "HP_CUR": 1, "CC_RNG": 1},
        {"id": "11", "player": 1, "col": 17, "row": 5, "HP_CUR": 1, "CC_RNG": 1},
    ],
    "current_player": 0,
    "units_charged": set(),
    "charge_roll_values": {}
}

print("=" * 80)
print("CHARGE OCCUPIED HEX TEST")
print("=" * 80)
print(f"Testing Unit 3 charge from (18, 6)")
print(f"Unit 6 is at (23, 6) - this hex should NEVER be a valid destination")
print(f"Wall hexes loaded: {len(game_state['wall_hexes'])}")

# Set charge roll (simulating a roll of 9, which was the actual roll in the bug)
charge_roll = 9

# Build valid charge destinations
valid_dests = charge_build_valid_destinations_pool(game_state, "3", charge_roll)

print(f"\nEngine found {len(valid_dests)} valid charge destinations")

# CRITICAL TEST: Check that (23, 6) is NOT in valid destinations
occupied_hex = (23, 6)
if occupied_hex in valid_dests:
    print(f"\n❌ TEST FAILED: Occupied hex {occupied_hex} is in valid destinations!")
    print("This is the bug - a unit should never be able to charge onto an occupied hex.")
    sys.exit(1)
else:
    print(f"\n✅ TEST PASSED: Occupied hex {occupied_hex} is correctly excluded from valid destinations")

# Additional test: Check that NO occupied hexes are in the destinations
occupied_positions = {(u["col"], u["row"]) for u in game_state["units"]
                     if u["HP_CUR"] > 0 and u["id"] != "3"}

occupied_in_dests = [pos for pos in valid_dests if pos in occupied_positions]

if occupied_in_dests:
    print(f"\n❌ TEST FAILED: Found {len(occupied_in_dests)} occupied hexes in valid destinations:")
    for pos in occupied_in_dests:
        # Find which unit occupies this hex
        occupier = next((u for u in game_state["units"] 
                        if u["col"] == pos[0] and u["row"] == pos[1] and u["HP_CUR"] > 0), None)
        print(f"   - {pos} occupied by Unit {occupier['id'] if occupier else 'unknown'}")
    sys.exit(1)
else:
    print(f"\n✅ TEST PASSED: No occupied hexes found in valid destinations")

# Show some valid destinations for debugging
if valid_dests:
    print(f"\nFirst 10 valid destinations: {sorted(valid_dests)[:10]}")
    # Check if any are adjacent to Unit 6 (should be valid, but not ON Unit 6)
    unit_6_pos = (23, 6)
    adjacent_to_unit_6 = [pos for pos in valid_dests 
                          if abs(pos[0] - unit_6_pos[0]) <= 1 and abs(pos[1] - unit_6_pos[1]) <= 1
                          and pos != unit_6_pos]
    if adjacent_to_unit_6:
        print(f"\n✅ Found {len(adjacent_to_unit_6)} valid destinations adjacent to Unit 6 (but not on it)")
        print(f"   Adjacent destinations: {adjacent_to_unit_6[:5]}")
else:
    print("\n⚠️  WARNING: No valid destinations found (this might be expected depending on scenario)")

print("\n" + "=" * 80)
print("✅ ALL TESTS PASSED: Charge destinations correctly exclude occupied hexes")
print("=" * 80)

