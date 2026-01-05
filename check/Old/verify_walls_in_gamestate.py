#!/usr/bin/env python3
"""
MINIMAL TEST: Verify wall_hexes loads into game_state during engine initialization.
This script bypasses full training to avoid numpy segfaults.
"""

import sys
import os

# Suppress numpy warnings
os.environ['PYTHONWARNINGS'] = 'ignore'

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_walls_in_game_state():
    """Test if W40KEngine loads wall_hexes into game_state"""

    print("=" * 80)
    print("MINIMAL VERIFICATION: wall_hexes in game_state")
    print("=" * 80)

    # Import after path setup
    from config_loader import get_config_loader
    from ai.unit_registry import UnitRegistry

    print("\n[STEP 1] Loading config...")
    loader = get_config_loader()
    board_config = loader.get_board_config()
    wall_count_in_config = len(board_config["default"]["wall_hexes"])
    print(f"[OK] board_config has {wall_count_in_config} wall hexes")

    print("\n[STEP 2] Initializing W40KEngine...")
    from engine.w40k_core import W40KEngine

    unit_registry = UnitRegistry()

    try:
        # Create engine with minimal config (matches training system)
        engine = W40KEngine(
            config=None,
            controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
            rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm_phase1",
            training_config_name="phase1",
            scenario_file="config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-1.json",
            unit_registry=unit_registry,
            gym_training_mode=True,
            quiet=True  # Suppress debug output
        )

        print("[OK] Engine initialized successfully")

    except Exception as e:
        print(f"\n[FAIL] Engine initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print("\n[STEP 3] Checking game_state['wall_hexes']...")

    if "wall_hexes" not in engine.game_state:
        print("[FAIL] 'wall_hexes' key MISSING from game_state!")
        print(f"       Available keys: {list(engine.game_state.keys())}")
        return False

    wall_hexes = engine.game_state["wall_hexes"]
    wall_count_in_gamestate = len(wall_hexes)

    print(f"[OK] game_state['wall_hexes'] exists")
    print(f"     Type: {type(wall_hexes)}")
    print(f"     Count: {wall_count_in_gamestate}")

    if wall_count_in_gamestate > 0:
        print(f"     Sample (first 5): {list(wall_hexes)[:5]}")

    print("\n" + "=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    print(f"Config has:     {wall_count_in_config} walls")
    print(f"game_state has: {wall_count_in_gamestate} walls")

    if wall_count_in_gamestate == 0:
        print("\n[CRITICAL BUG FOUND] Wall hexes NOT loaded into game_state!")
        print("This explains why pathfinding ignores walls.")
        return False
    elif wall_count_in_gamestate != wall_count_in_config:
        print(f"\n[WARNING] Wall count mismatch!")
        print(f"Expected {wall_count_in_config}, got {wall_count_in_gamestate}")
        return False
    else:
        print("\n[SUCCESS] Walls loaded correctly into game_state!")
        print("If pathfinding is still broken, the issue is in the BFS algorithm.")
        return True

if __name__ == "__main__":
    try:
        success = test_walls_in_game_state()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
