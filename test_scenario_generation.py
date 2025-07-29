#!/usr/bin/env python3
"""
test_scenario_generation.py - Simple test script to validate scenario generation fixes
Run this from the project root directory: python test_scenario_generation.py
"""

import os
import sys
import json
from pathlib import Path

# Add project paths
script_dir = Path(__file__).parent
project_root = script_dir
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "ai"))

def test_scenario_templates():
    """Test all scenario templates for position conflicts."""
    print("🧪 TESTING SCENARIO TEMPLATES")
    print("=" * 50)
    
    # Load scenario templates
    template_file = "config/scenario_templates.json"
    if not os.path.exists(template_file):
        print(f"❌ Template file not found: {template_file}")
        return False
    
    try:
        with open(template_file, 'r') as f:
            templates = json.load(f)
        print(f"✅ Loaded {len(templates)} templates from {template_file}")
    except Exception as e:
        print(f"❌ Error loading templates: {e}")
        return False
    
    # Test each template for sufficient positions
    units_per_player = 2  # From the code
    failed_templates = []
    
    for template_name, template_data in templates.items():
        print(f"\n🔍 Testing template: {template_name}")
        
        deployment_zones = template_data.get("deployment_zones", {})
        
        # Check player 0 positions
        player_0_positions = deployment_zones.get("0", [])
        if len(player_0_positions) < units_per_player:
            print(f"❌ Player 0: Need {units_per_player} positions, got {len(player_0_positions)}")
            print(f"   Positions: {player_0_positions}")
            failed_templates.append(f"{template_name}: Player 0 insufficient positions")
        else:
            # Check for duplicate positions
            position_set = set(tuple(pos) for pos in player_0_positions[:units_per_player])
            if len(position_set) != units_per_player:
                print(f"❌ Player 0: Duplicate positions detected in first {units_per_player} positions")
                print(f"   Positions: {player_0_positions[:units_per_player]}")
                failed_templates.append(f"{template_name}: Player 0 duplicate positions")
            else:
                print(f"✅ Player 0: {len(player_0_positions)} positions, {len(position_set)} unique")
        
        # Check player 1 positions
        player_1_positions = deployment_zones.get("1", [])
        if len(player_1_positions) < units_per_player:
            print(f"❌ Player 1: Need {units_per_player} positions, got {len(player_1_positions)}")
            print(f"   Positions: {player_1_positions}")
            failed_templates.append(f"{template_name}: Player 1 insufficient positions")
        else:
            # Check for duplicate positions
            position_set = set(tuple(pos) for pos in player_1_positions[:units_per_player])
            if len(position_set) != units_per_player:
                print(f"❌ Player 1: Duplicate positions detected in first {units_per_player} positions")
                print(f"   Positions: {player_1_positions[:units_per_player]}")
                failed_templates.append(f"{template_name}: Player 1 duplicate positions")
            else:
                print(f"✅ Player 1: {len(player_1_positions)} positions, {len(position_set)} unique")
        
        # Check for cross-player conflicts
        all_positions = set(tuple(pos) for pos in player_0_positions[:units_per_player])
        all_positions.update(set(tuple(pos) for pos in player_1_positions[:units_per_player]))
        total_expected = len(player_0_positions[:units_per_player]) + len(player_1_positions[:units_per_player])
        
        if len(all_positions) != total_expected:
            print(f"❌ Cross-player position conflicts detected!")
            print(f"   Expected {total_expected} unique positions, got {len(all_positions)}")
            failed_templates.append(f"{template_name}: Cross-player position conflicts")
        else:
            print(f"✅ No cross-player conflicts: {len(all_positions)} unique total positions")
    
    print(f"\n📊 TEMPLATE VALIDATION RESULTS")
    print("=" * 40)
    if failed_templates:
        print(f"❌ Failed templates: {len(failed_templates)}")
        for failure in failed_templates:
            print(f"   - {failure}")
        return False
    else:
        print(f"✅ All {len(templates)} templates passed validation!")
        return True

def test_scenario_generation():
    """Test actual scenario generation."""
    print("\n🎯 TESTING SCENARIO GENERATION")
    print("=" * 50)
    
    try:
        # Import scenario manager
        from ai.scenario_manager import ScenarioManager
        manager = ScenarioManager()
        print("✅ ScenarioManager initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize ScenarioManager: {e}")
        return False
    
    # Test available agents
    available_agents = manager.available_agents
    print(f"📋 Available agents: {available_agents}")
    
    if len(available_agents) < 2:
        print("⚠️ Need at least 2 agents for testing, using fallback agents")
        test_agents = ["SpaceMarine_Ranged", "SpaceMarine_Melee"]
    else:
        test_agents = available_agents
    
    # Test scenario generation for each template
    templates = manager.get_available_templates()
    failed_scenarios = []
    
    for template_name in templates:
        print(f"\n🔄 Testing scenario generation: {template_name}")
        
        try:
            # Generate scenario
            scenario = manager.generate_training_scenario(
                template_name, 
                test_agents[0], 
                test_agents[1]
            )
            
            # Validate generated scenario
            units = scenario.get("units", [])
            print(f"   Generated {len(units)} units")
            
            # Check for position conflicts
            position_map = {}
            conflicts = []
            
            for unit in units:
                pos_key = f"{unit['col']},{unit['row']}"
                if pos_key not in position_map:
                    position_map[pos_key] = []
                position_map[pos_key].append(f"Unit_{unit['id']}_{unit['unit_type']}_P{unit['player']}")
            
            for pos, units_at_pos in position_map.items():
                if len(units_at_pos) > 1:
                    conflicts.append(f"Position {pos}: {units_at_pos}")
            
            if conflicts:
                print(f"❌ Position conflicts detected:")
                for conflict in conflicts:
                    print(f"      {conflict}")
                failed_scenarios.append(f"{template_name}: Position conflicts")
            else:
                print(f"✅ No position conflicts detected")
                
                # Print unit positions for verification
                for unit in units:
                    print(f"      Unit {unit['id']}: {unit['unit_type']} (P{unit['player']}) at ({unit['col']},{unit['row']})")
            
        except Exception as e:
            print(f"❌ Failed to generate scenario: {e}")
            failed_scenarios.append(f"{template_name}: Generation failed - {str(e)}")
    
    print(f"\n📊 SCENARIO GENERATION RESULTS")
    print("=" * 40)
    if failed_scenarios:
        print(f"❌ Failed scenarios: {len(failed_scenarios)}")
        for failure in failed_scenarios:
            print(f"   - {failure}")
        return False
    else:
        print(f"✅ All {len(templates)} scenarios generated successfully!")
        return True

def test_specific_template(template_name="solo_spacemarine_ranged"):
    """Test a specific template in detail."""
    print(f"\n🔍 DETAILED TEST: {template_name}")
    print("=" * 50)
    
    try:
        from ai.scenario_manager import ScenarioManager
        manager = ScenarioManager()
        
        # Generate scenario multiple times to check consistency
        for i in range(3):
            print(f"\n🔄 Generation attempt {i+1}:")
            
            scenario = manager.generate_training_scenario(
                template_name, 
                "SpaceMarine_Ranged", 
                "SpaceMarine_Melee"
            )
            
            units = scenario.get("units", [])
            print(f"   Units generated: {len(units)}")
            
            for unit in units:
                print(f"   Unit {unit['id']}: {unit['unit_type']} (Player {unit['player']}) at ({unit['col']},{unit['row']})")
            
            # Save test scenario
            test_file = f"test_scenario_{template_name}_{i+1}.json"
            with open(test_file, 'w') as f:
                json.dump(scenario, f, indent=2)
            print(f"   Saved to: {test_file}")
        
        print(f"✅ Template {template_name} tested successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🧪 SCENARIO GENERATION VALIDATION SUITE")
    print("=" * 60)
    
    # Test 1: Template validation
    template_test = test_scenario_templates()
    
    # Test 2: Scenario generation
    generation_test = test_scenario_generation()
    
    # Test 3: Specific template detailed test
    specific_test = test_specific_template()
    
    # Final results
    print("\n🏁 FINAL RESULTS")
    print("=" * 30)
    print(f"Template Validation: {'✅ PASS' if template_test else '❌ FAIL'}")
    print(f"Scenario Generation: {'✅ PASS' if generation_test else '❌ FAIL'}")
    print(f"Specific Template:   {'✅ PASS' if specific_test else '❌ FAIL'}")
    
    if all([template_test, generation_test, specific_test]):
        print("\n🎉 ALL TESTS PASSED! Scenario generation is working correctly.")
        print("📝 You should now see no more unit overlap issues in new training runs.")
    else:
        print("\n❌ SOME TESTS FAILED! Check the error messages above.")
        print("📝 Apply the fixes mentioned in the analysis before training.")
    
    return all([template_test, generation_test, specific_test])

if __name__ == "__main__":
    # Run from project root directory
    if not os.path.exists("config/scenario_templates.json"):
        print("❌ Error: This script must be run from the project root directory")
        print("   Expected to find: config/scenario_templates.json")
        print("   Current directory:", os.getcwd())
        sys.exit(1)
    
    success = main()
    sys.exit(0 if success else 1)