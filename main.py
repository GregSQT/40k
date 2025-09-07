#!/usr/bin/env python3
"""
main.py - W40K Engine Test and Development Entry Point

Test and validate the AI_TURN.md compliant W40K engine.
"""

import json
import os
from engine import W40KEngine


def load_config():
    """Load configuration from config files."""
    config = {}
    
    # Load board configuration
    board_config_path = "config/board_config.json"
    if not os.path.exists(board_config_path):
        raise FileNotFoundError(f"Required config file missing: {board_config_path}")
    
    with open(board_config_path, 'r', encoding='utf-8-sig') as f:
        content = f.read().strip()
        if not content:
            raise ValueError(f"Config file is empty: {board_config_path}")
        board_data = json.loads(content)
    
    # Load unit registry to get unit-to-file mappings
    unit_registry_path = "config/unit_registry.json"
    if not os.path.exists(unit_registry_path):
        raise FileNotFoundError(f"Required config file missing: {unit_registry_path}")
    
    # Debug file reading
    print(f"DEBUG: Reading from {unit_registry_path}")
    print(f"DEBUG: File exists: {os.path.exists(unit_registry_path)}")
    print(f"DEBUG: File size: {os.path.getsize(unit_registry_path)} bytes")
    
    with open(unit_registry_path, 'r', encoding='utf-8') as f:
        content = f.read()
        print(f"DEBUG: File content length: {len(content)}")
        print(f"DEBUG: First 100 chars: {repr(content[:100])}")
        
        if not content.strip():
            raise ValueError(f"File {unit_registry_path} is empty")
        
        unit_registry = json.loads(content)
    
    # Load actual unit definitions from TypeScript files
    unit_definitions = load_unit_definitions_from_ts(unit_registry)
    
    config["units"] = create_test_scenario(unit_definitions)
    
    return config


def load_unit_definitions_from_ts(unit_registry):
    """Load unit definitions by parsing TypeScript static class properties."""
    import re
    
    unit_definitions = {}
    
    for unit_name, faction in unit_registry["units"].items():
        # Map faction to proper path structure
        faction_path_map = {
            "space_marines": "SpaceMarine",
            "tyranids": "Tyranid"
        }
        
        if faction not in faction_path_map:
            print(f"Warning: Unknown faction {faction} for unit {unit_name}")
            continue
            
        # Build proper TypeScript file path
        faction_dir = faction_path_map[faction]
        ts_file_path = f"frontend/src/roster/{faction_dir}/units/{unit_name}.ts"
        
        if not os.path.exists(ts_file_path):
            print(f"Warning: Unit file not found: {ts_file_path}")
            continue
        
        try:
            with open(ts_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract static properties using regex
            unit_stats = {}
            
            # Pattern to match: static FIELD_NAME = value;
            static_pattern = r'static\s+([A-Z_]+)\s*=\s*([^;]+);'
            matches = re.findall(static_pattern, content)
            
            for field_name, value_str in matches:
                # Clean and convert the value
                value_str = value_str.strip().strip('"\'')
                
                # Convert to appropriate type
                if value_str.isdigit() or (value_str.startswith('-') and value_str[1:].isdigit()):
                    unit_stats[field_name] = int(value_str)
                elif value_str.replace('.', '').isdigit():
                    unit_stats[field_name] = float(value_str)
                else:
                    unit_stats[field_name] = value_str
            
            # No default values - unit files must be complete
            # If fields are missing, engine validation will catch this
            
            unit_definitions[unit_name] = unit_stats
            
        except Exception as e:
            print(f"Error parsing {ts_file_path}: {e}")
            continue
    
    return unit_definitions


def create_test_scenario(unit_definitions):
    """Create test scenario using actual unit definitions from TypeScript files."""
    print(f"DEBUG: Loaded {len(unit_definitions)} unit definitions")
    
    units = []
    unit_types = list(unit_definitions.keys())
    
    if len(unit_types) >= 2:
        # Player 0 unit  
        unit_type_0 = unit_types[0]
        unit_def_0 = unit_definitions[unit_type_0]
        units.append({
            **unit_def_0,
            "id": "player0_unit1",
            "player": 0,
            "col": 1,
            "row": 1,
            "unitType": unit_type_0,
            "CUR_HP": unit_def_0["MAX_HP"]  # Set current HP to max HP
        })
        
        # Player 1 unit
        unit_type_1 = unit_types[1] if len(unit_types) > 1 else unit_types[0]
        unit_def_1 = unit_definitions[unit_type_1]
        units.append({
            **unit_def_1,
            "id": "player1_unit1", 
            "player": 1,
            "col": 8,
            "row": 8,
            "unitType": unit_type_1,
            "CUR_HP": unit_def_1["MAX_HP"]  # Set current HP to max HP
        })
    else:
        print("Warning: Not enough unit definitions found, using defaults")
        units = create_default_test_units()
    
    return units


def create_default_test_units():
    """Create default test units if config files not available."""
    return [
        {
            "id": "marine_1",
            "player": 0,
            "unitType": "default_marine",
            "col": 1,
            "row": 1,
            "CUR_HP": 2,
            "MAX_HP": 2,
            "MOVE": 6,
            "T": 4,
            "ARMOR_SAVE": 3,
            "INVUL_SAVE": 7,
            "RNG_NB": 1,
            "RNG_RNG": 24,
            "RNG_ATK": 3,
            "RNG_STR": 4,
            "RNG_DMG": 1,
            "RNG_AP": 0,
            "CC_NB": 1,
            "CC_RNG": 1,
            "CC_ATK": 3,
            "CC_STR": 4,
            "CC_DMG": 1,
            "CC_AP": 0,
            "LD": 7,
            "OC": 1,
            "VALUE": 100,
            "ICON": "marine",
            "ICON_SCALE": 1.0
        },
        {
            "id": "ork_1",
            "player": 1,
            "unitType": "default_ork",
            "col": 8,
            "row": 8,
            "CUR_HP": 1,
            "MAX_HP": 1,
            "MOVE": 6,
            "T": 5,
            "ARMOR_SAVE": 6,
            "INVUL_SAVE": 7,
            "RNG_NB": 1,
            "RNG_RNG": 12,
            "RNG_ATK": 5,
            "RNG_STR": 4,
            "RNG_DMG": 1,
            "RNG_AP": 0,
            "CC_NB": 2,
            "CC_RNG": 1,
            "CC_ATK": 3,
            "CC_STR": 4,
            "CC_DMG": 1,
            "CC_AP": 0,
            "LD": 7,
            "OC": 1,
            "VALUE": 60,
            "ICON": "ork",
            "ICON_SCALE": 1.0
        }
    ]


def test_basic_functionality():
    """Test basic engine functionality."""
    print("=== W40K Engine Basic Functionality Test ===")
    
    # Load configuration
    config = load_config()
    print(f"Loaded config with {len(config['units'])} units")
    
    # Initialize engine
    engine = W40KEngine(config)
    print("Engine initialized successfully!")
    
    # Check compliance
    violations = engine.validate_compliance()
    if violations:
        print("⚠️  Compliance violations found:")
        for violation in violations:
            print(f"   - {violation}")
    else:
        print("✅ No AI_TURN.md compliance violations detected")
    
    # Test reset
    obs, info = engine.reset()
    print(f"Reset complete - Observation size: {len(obs)}, Phase: {info['phase']}")
    
    # Test some actions
    print("\n=== Testing Movement Actions ===")
    
    for i, action in enumerate([2, 2, 7, 1]):  # East, East, Wait, South
        obs, reward, done, truncated, info = engine.step(action)
        action_names = {0: "North", 1: "South", 2: "East", 3: "West", 7: "Wait"}
        action_name = action_names.get(action, f"Action_{action}")
        
        print(f"Step {i+1}: {action_name} -> Success: {info['success']}, Phase: {info['phase']}, Reward: {reward}")
        
        if info.get('result'):
            result = info['result']
            if 'type' in result:
                print(f"   Result: {result['type']}")
                if 'from' in result and 'to' in result:
                    print(f"   Movement: {result['from']} -> {result['to']}")
        
        if done:
            print(f"Game ended! Winner: {engine.game_state.get('winner', 'None')}")
            break
    
    print(f"\nFinal game state:")
    print(f"   Turn: {engine.game_state['turn']}")
    print(f"   Current player: {engine.game_state['current_player']}")
    print(f"   Episode steps: {engine.game_state['episode_steps']}")
    print(f"   Units moved: {engine.game_state['units_moved']}")
    print(f"   Units fled: {engine.game_state['units_fled']}")


def test_movement_handlers():
    """Test movement handlers directly."""
    print("\n=== Testing Movement Handlers ===")
    print("⚠️  Movement handlers not yet implemented - skipping test")
    return
    
    try:
        from engine.phase_handlers import movement_handlers
        print("✅ Movement handlers imported successfully")
        
        # Create simple test state
        test_state = {
            "current_player": 0,
            "units": [
                {
                    "id": "test_unit",
                    "player": 0,
                    "col": 5,
                    "row": 5,
                    "CUR_HP": 2,
                    "MOVE": 6,
                    "CC_RNG": 1
                }
            ],
            "units_moved": set(),
            "units_fled": set(),
            "board_width": 10,
            "board_height": 10,
            "wall_hexes": set()
        }
        
        # Test eligibility
        eligible = movement_handlers.get_eligible_units(test_state)
        print(f"✅ Eligible units: {eligible}")
        
        # Test valid destinations
        unit = test_state["units"][0]
        destinations = movement_handlers.get_valid_destinations(test_state, unit)
        print(f"✅ Valid destinations found: {len(destinations)}")
        
        # Test compliance
        violations = movement_handlers.validate_movement_compliance(test_state)
        if violations:
            print("⚠️  Movement handler violations:")
            for violation in violations:
                print(f"   - {violation}")
        else:
            print("✅ Movement handlers compliant")
            
    except ImportError as e:
        print(f"❌ Failed to import movement handlers: {e}")
        print("Make sure engine/phase_handlers/movement_handlers.py exists")


if __name__ == "__main__":
    try:
        test_basic_functionality()
        test_movement_handlers()
        
        print("\n=== Test Complete ===")
        print("Engine is ready for development!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()