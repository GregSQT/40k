# test_engine_masking.py
from engine.w40k_engine import W40KEngine
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader
import numpy as np

def test_action_masking():
    """Test that engine correctly masks invalid actions during gym steps"""
    
    # Initialize unit registry and config separately (following train.py pattern)
    config_loader = get_config_loader()
    unit_registry = UnitRegistry()
    scenario_file = "config/scenario.json"
    
    engine = W40KEngine(
        config=None,
        rewards_config="default", 
        training_config_name="debug",
        controlled_agent="SpaceMarine_Infantry_Troop_RangedSwarm",
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True
    )
    
    # Reset to movement phase
    obs, info = engine.reset()
    print(f"Initial phase: {engine.game_state['phase']}")
    
    # Test action mask for movement phase
    action_mask = engine.get_action_mask()
    print(f"Movement phase mask: {action_mask}")
    
    # Verify expected pattern: [True, True, True, True, False, False, False, True]
    expected_move_mask = [True, True, True, True, False, False, False, True]
    assert np.array_equal(action_mask, expected_move_mask), f"Expected {expected_move_mask}, got {action_mask}"
    
    # Test invalid action (action 5 = charge during movement)
    obs, reward, done, truncated, info = engine.step(5)
    print(f"Invalid action reward: {reward}")
    print(f"Invalid action result: {info}")
    
    # Should receive negative reward and error message
    assert reward < 0, f"Expected negative reward for invalid action, got {reward}"
    
    print("✅ Action masking verification PASSED")

if __name__ == "__main__":
    test_action_masking()