#!/usr/bin/env python3
"""Quick test to verify observation shape with objective control"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.w40k_core import W40KEngine
from config_loader import get_config_loader
from ai.unit_registry import UnitRegistry

def main():
    print("[TEST] Testing Pure RL Observation System (300 floats)...")

    config_loader = get_config_loader()
    unit_registry = UnitRegistry()

    engine = W40KEngine(
        config=None,
        rewards_config='default',
        training_config_name='debug',
        controlled_agent='SpaceMarine_Infantry_Troop_RangedSwarm',
        scenario_file='config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenarios/SpaceMarine_Infantry_Troop_RangedSwarm_scenario1.json',
        unit_registry=unit_registry,
        quiet=True
    )

    obs, info = engine.reset()

    print(f'[OK] Observation shape: {obs.shape}')
    print(f'[OK] Expected: (300,)')

    assert obs.shape == (300,), f'ERROR: Shape mismatch! Got {obs.shape}'

    print('[OK] Pure RL observation system verified!')
    print(f'[OK] Observation breakdown:')
    print(f'   [0:15]     Global context (incl. objectives): 15 floats')
    print(f'   [15:23]    Active unit:                        8 floats')
    print(f'   [23:55]    Directional terrain:               32 floats')
    print(f'   [55:127]   Allied units:                      72 floats (6x12)')
    print(f'   [127:265]  Enemy units:                      138 floats (6x23)')
    print(f'   [265:300]  Valid targets:                     35 floats (5x7)')
    print(f'   Total: {obs.shape[0]} floats [OK]')

if __name__ == "__main__":
    main()
