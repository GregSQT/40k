#!/usr/bin/env python3
"""Quick test to verify observation shape after removing feature #8"""

from engine.w40k_core import W40KEngine
from config_loader import get_config_loader
from ai.unit_registry import UnitRegistry

def main():
    print("🧪 Testing Pure RL Observation System (295 floats)...")
    
    config_loader = get_config_loader()
    unit_registry = UnitRegistry()
    
    engine = W40KEngine(
        config=None,
        rewards_config='default',
        training_config_name='debug',
        controlled_agent='SpaceMarine_Infantry_Troop_RangedSwarm',
        scenario_file='config/scenario_SM_vs_Tyranids.json',  # Corrected path
        unit_registry=unit_registry,
        quiet=True
    )
    
    obs, info = engine.reset()
    
    print(f'✅ Observation shape: {obs.shape}')
    print(f'✅ Expected: (295,)')
    
    assert obs.shape == (295,), f'ERROR: Shape mismatch! Got {obs.shape}'
    
    print('✅ Pure RL observation system verified!')
    print(f'✅ Observation breakdown:')
    print(f'   [0:10]    Global context:      10 floats')
    print(f'   [10:18]   Active unit:          8 floats')
    print(f'   [18:50]   Directional terrain: 32 floats')
    print(f'   [50:120]  Nearby units:        70 floats (7×10)')
    print(f'   [120:165] Valid targets:       45 floats (5×9) ← Removed feature #8')
    print(f'   Total: {obs.shape[0]} floats ✅')

if __name__ == "__main__":
    main()