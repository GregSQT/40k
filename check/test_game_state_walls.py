#!/usr/bin/env python3
"""Test if game_state has wall_hexes when engine initializes"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_loader import get_config_loader
from engine.w40k_core import W40KEngine
from ai.unit_registry import UnitRegistry

def test_engine_wall_loading():
    """Test if W40KEngine loads wall_hexes into game_state"""
    print("=" * 80)
    print("TESTING W40KENGINE WALL_HEXES LOADING")
    print("=" * 80)

    # Initialize components
    loader = get_config_loader()
    unit_registry = UnitRegistry()

    # Create engine with training parameters (matches train.py)
    engine = W40KEngine(
        config=None,  # Build from training system
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
        rewards_config="SpaceMarine_Infantry_Troop_RangedSwarm_phase1",
        training_config_name="phase1",
        scenario_file="config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1-1.json",
        unit_registry=unit_registry,
        gym_training_mode=True,
        quiet=False
    )

    print(f"\n[CHECK] Engine initialized")
    print(f"[CHECK] game_state keys: {list(engine.game_state.keys())[:15]}...")

    # Check wall_hexes
    if "wall_hexes" in engine.game_state:
        wall_hexes = engine.game_state["wall_hexes"]
        print(f"\n[OK] game_state['wall_hexes'] EXISTS")
        print(f"   Type: {type(wall_hexes)}")
        print(f"   Count: {len(wall_hexes)}")
        if len(wall_hexes) > 0:
            print(f"   Sample (first 5): {list(wall_hexes)[:5]}")
            print(f"\n[RESULT] SUCCESS - Walls are loaded!")
            return True
        else:
            print(f"\n[RESULT] FAILURE - wall_hexes is EMPTY!")
            return False
    else:
        print(f"\n[FAIL] game_state['wall_hexes'] DOES NOT EXIST")
        return False

if __name__ == "__main__":
    try:
        success = test_engine_wall_loading()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
