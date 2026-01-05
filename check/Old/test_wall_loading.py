#!/usr/bin/env python3
"""Quick test to verify wall_hexes loads correctly"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader

def test_wall_loading():
    """Test if board_config loads with wall_hexes"""
    loader = get_config_loader()
    board_config = loader.get_board_config()

    print("=" * 80)
    print("BOARD CONFIG STRUCTURE")
    print("=" * 80)
    print(f"Keys in board_config: {list(board_config.keys())}")

    if "default" in board_config:
        print(f"\nKeys in board_config['default']: {list(board_config['default'].keys())}")

        if "wall_hexes" in board_config["default"]:
            wall_hexes = board_config["default"]["wall_hexes"]
            print(f"\n[OK] wall_hexes found!")
            print(f"   Type: {type(wall_hexes)}")
            print(f"   Count: {len(wall_hexes)}")
            print(f"   First 5: {wall_hexes[:5]}")

            # Convert to set of tuples like engine does
            wall_set = set(map(tuple, wall_hexes))
            print(f"\n[OK] Converted to set of tuples:")
            print(f"   Type: {type(wall_set)}")
            print(f"   Count: {len(wall_set)}")
            print(f"   Sample: {list(wall_set)[:5]}")

            return True
        else:
            print("\n[FAIL] wall_hexes NOT FOUND in board_config['default']")
            return False
    else:
        print("\n[FAIL] 'default' key NOT FOUND in board_config")
        return False

if __name__ == "__main__":
    success = test_wall_loading()
    sys.exit(0 if success else 1)
