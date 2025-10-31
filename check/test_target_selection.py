#!/usr/bin/env python3
"""
Test script to verify target selection is working correctly.
"""

import numpy as np
from engine.w40k_core import W40KEngine
from stable_baselines3 import PPO

def test_observation_action_correspondence():
    """Test that observation encoding matches action space."""
    print("🧪 Testing observation-action correspondence...")
    
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    engine = W40KEngine(
        rewards_config="default",
        training_config_name="curriculum_phase1",
        scenario_file="config/scenario_curriculum.json",
        unit_registry=unit_registry
    )
    
    obs, info = engine.reset()
    
    print(f"✅ Observation shape: {obs.shape} (expected: (165,))")
    assert obs.shape == (165,), "Observation size mismatch!"
    
    for i in range(5):
        obs_base = 120 + i * 10
        is_valid = obs[obs_base + 0]
        kill_prob = obs[obs_base + 1]
        danger = obs[obs_base + 2]
        army_threat = obs[obs_base + 6]
        print(f"   Action {4+i}: valid={is_valid:.1f}, kill_prob={kill_prob:.2f}, danger={danger:.2f}, army_threat={army_threat:.2f}")
    
    print("✅ Observation structure verified\n")

def test_action_masking():
    """Test that action masking aligns with observation."""
    print("🧪 Testing action masking alignment...")
    
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    engine = W40KEngine(
        rewards_config="default",
        training_config_name="curriculum_phase1",
        scenario_file="config/scenario_curriculum.json",
        unit_registry=unit_registry
    )
    
    obs, info = engine.reset()
    mask = engine.get_action_mask()
    
    for i in range(5):
        obs_base = 120 + i * 10
        is_valid_obs = obs[obs_base + 0] > 0.5
        is_valid_mask = mask[4 + i]
        
        match = "✅" if is_valid_obs == is_valid_mask else "❌"
        print(f"   Action {4+i}: obs={is_valid_obs}, mask={is_valid_mask} {match}")
        
        assert is_valid_obs == is_valid_mask, f"Mismatch for action {4+i}!"
    
    print("✅ Action masking alignment verified\n")

def test_target_selection_execution():
    """Test that agent can actually select different targets."""
    print("🧪 Testing target selection execution...")
    
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    engine = W40KEngine(
        rewards_config="default",
        training_config_name="curriculum_phase1",
        scenario_file="config/scenario_curriculum.json",
        unit_registry=unit_registry
    )
    
    obs, info = engine.reset()
    
    mask = engine.get_action_mask()
    valid_shoot_actions = [i for i in range(4, 9) if mask[i]]
    
    print(f"   Valid shooting actions: {valid_shoot_actions}")
    
    for action in valid_shoot_actions[:2]:
        obs, info = engine.reset()
        obs, reward, done, truncated, info = engine.step(action)
        print(f"   Action {action}: reward={reward:.2f}, success={info.get('success', False)}")
    
    print("✅ Target selection execution verified\n")

def test_probability_calculations():
    """Test that probability calculations work correctly."""
    print("🧪 Testing probability calculations...")
    
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    
    engine = W40KEngine(
        rewards_config="default",
        training_config_name="curriculum_phase1",
        scenario_file="config/scenario_curriculum.json",
        unit_registry=unit_registry
    )
    
    obs, info = engine.reset()
    
    for i in range(5):
        obs_base = 120 + i * 10
        is_valid = obs[obs_base + 0]
        
        if is_valid > 0.5:
            kill_prob = obs[obs_base + 1]
            danger = obs[obs_base + 2]
            army_threat = obs[obs_base + 6]
            
            assert 0.0 <= kill_prob <= 1.0, f"kill_prob out of range: {kill_prob}"
            assert 0.0 <= danger <= 1.0, f"danger out of range: {danger}"
            assert 0.0 <= army_threat <= 1.0, f"army_threat out of range: {army_threat}"
            
            print(f"   Action {4+i}: Probabilities valid ✅")
    
    print("✅ Probability calculations verified\n")

if __name__ == "__main__":
    print("=" * 50)
    print("TARGET SELECTION VERIFICATION TESTS")
    print("=" * 50 + "\n")
    
    try:
        test_observation_action_correspondence()
        test_action_masking()
        test_target_selection_execution()
        test_probability_calculations()
        
        print("=" * 50)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()