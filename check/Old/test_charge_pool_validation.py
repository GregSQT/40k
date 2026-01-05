#!/usr/bin/env python3
"""
Test that _is_valid_charge_destination checks pool membership.
This verifies that destinations not in the pool are rejected.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from engine.phase_handlers.charge_handlers import _is_valid_charge_destination, charge_build_valid_destinations_pool

# Load board config
loader = get_config_loader()
board_config = loader.get_board_config()

game_state = {
    "board_cols": 25,
    "board_rows": 21,
    "wall_hexes": set(map(tuple, board_config["default"]["wall_hexes"])),
    "units": [
        {"id": "1", "player": 0, "col": 10, "row": 10, "HP_CUR": 1, "unitType": "test"},
        {"id": "2", "player": 1, "col": 12, "row": 10, "HP_CUR": 1, "unitType": "test"},
    ],
    "current_player": 0,
    "units_charged": set(),
    "charge_roll_values": {}
}

print("=" * 80)
print("CHARGE POOL VALIDATION TEST")
print("=" * 80)

unit = game_state["units"][0]
target_id = "2"
charge_roll = 3  # Small roll - limited destinations

# Build valid destinations pool
valid_destinations = charge_build_valid_destinations_pool(game_state, unit["id"], charge_roll)
game_state["valid_charge_destinations_pool"] = valid_destinations

print(f"Built pool with {len(valid_destinations)} destinations")
print(f"Sample destinations: {list(valid_destinations)[:5]}")

# Test 1: Destination IN pool should be valid
if valid_destinations:
    test_dest = valid_destinations[0]
    config = {}
    is_valid = _is_valid_charge_destination(
        game_state, test_dest[0], test_dest[1], unit, target_id, charge_roll, config
    )
    if not is_valid:
        print(f"\n❌ TEST FAILED: Destination {test_dest} (IN pool) was rejected!")
        sys.exit(1)
    else:
        print(f"\n✅ Destination {test_dest} (IN pool) correctly validated")

# Test 2: Destination NOT in pool should be invalid
# Find a hex that's NOT in the pool but passes other checks
invalid_dest = (unit["col"] + 10, unit["row"] + 10)  # Far away
is_valid = _is_valid_charge_destination(
    game_state, invalid_dest[0], invalid_dest[1], unit, target_id, charge_roll, config
)
if is_valid:
    print(f"\n❌ TEST FAILED: Destination {invalid_dest} (NOT in pool) was accepted!")
    print("This is the bug - _is_valid_charge_destination should check pool membership.")
    sys.exit(1)
else:
    print(f"\n✅ Destination {invalid_dest} (NOT in pool) correctly rejected")

print(f"\n✅ ALL TESTS PASSED: Pool validation works correctly")
print("=" * 80)