#!/usr/bin/env python3
"""Test scenario loading fix"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai.gym40k import W40KEnv
from ai.scenario_manager import ScenarioManager
from ai.unit_registry import UnitRegistry

def test_scenario_loading():
    print("🧪 Testing scenario loading fix...")
    
    # Test 1: Default scenario loading
    env1 = W40KEnv(scenario_file=None)
    print(f"✅ Default scenario loaded")
    
    # Test 2: Generated scenario loading
    unit_registry = UnitRegistry()
    scenario_manager = ScenarioManager()
    
    agents = unit_registry.get_required_models()
    if len(agents) >= 2:
        scenario = scenario_manager.generate_training_scenario(
            "balanced_2v2", agents[0], agents[1]
        )
        scenario_path = scenario_manager.save_scenario_to_file(scenario, "test_scenario.json")
        
        env2 = W40KEnv(scenario_file=scenario_path)
        print(f"✅ Generated scenario loaded: {scenario_path}")
        
        # Verify units match the agents
        env2_units = [u for u in env2.units if u["player"] == 1]
        expected_units = unit_registry.get_units_for_model(agents[1])
        
        unit_types_match = all(u["unit_type"] in expected_units for u in env2_units)
        print(f"✅ Unit types match agent: {unit_types_match}")
        
        # Cleanup
        os.remove(scenario_path)
        env2.close()
    
    env1.close()
    print("🎉 Scenario loading test passed!")

if __name__ == "__main__":
    test_scenario_loading()