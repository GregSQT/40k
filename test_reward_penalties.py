# test_reward_penalties.py
from engine.w40k_engine import W40KEngine
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader
import numpy as np

def test_phase_violation_penalties():
    """Test reward system penalizes phase violations correctly"""
    
    # Initialize unit registry and config (same pattern as working test)
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
    
    # Reset to start
    obs, info = engine.reset()
    print(f"Starting phase: {engine.game_state['phase']}")
    
    # Test various invalid actions
    invalid_actions = [
        (4, "move"),  # Shoot during movement
        (5, "move"),  # Charge during movement  
        (6, "move"),  # Fight during movement
    ]
    
    for action, expected_phase in invalid_actions:
        # Reset to ensure we're in movement phase
        if engine.game_state["phase"] != expected_phase:
            obs, info = engine.reset()  # Reset to movement phase
            
        print(f"\nTesting action {action} in {expected_phase} phase:")
        obs, reward, done, truncated, info = engine.step(action)
        print(f"  Reward: {reward}")
        print(f"  Info: {info}")
        
        # Should receive heavy penalty
        assert reward <= -0.5, f"Expected heavy penalty for invalid action {action}, got {reward}"
        print(f"  ✅ Penalty applied correctly")
    
    print("\n✅ Phase violation penalties PASSED")

if __name__ == "__main__":
    test_phase_violation_penalties()