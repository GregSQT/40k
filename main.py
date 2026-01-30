#!/usr/bin/env python3
"""
main.py - W40K Engine Test and Development Entry Point

Test and validate the AI_TURN.md compliant W40K engine.
"""

import json
import os
from engine import W40KEngine
from engine.phase_handlers.shared_utils import is_unit_alive


def load_config(scenario_path=None):
    """Load configuration from config files.

    Args:
        scenario_path: Optional path to scenario file. If None, uses default config/scenario.json

    Returns:
        Configuration dictionary with board, units, etc.
    """
    config = {}

    # Load board configuration
    board_config_path = "config/board_config.json"
    if not os.path.exists(board_config_path):
        raise FileNotFoundError(f"Required config file missing: {board_config_path}")

    with open(board_config_path, 'r', encoding='utf-8-sig') as f:
        content = f.read().strip()
        if not content:
            raise ValueError(f"Config file is empty: {board_config_path}")
        board_raw = json.loads(content)

    # Extract default config from nested structure
    config["board"] = board_raw["default"]

    # Load unit registry to get unit-to-file mappings
    unit_registry_path = "config/unit_registry.json"
    if not os.path.exists(unit_registry_path):
        raise FileNotFoundError(f"Required config file missing: {unit_registry_path}")

    with open(unit_registry_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

        if not content.strip():
            raise ValueError(f"File {unit_registry_path} is empty")

        unit_registry = json.loads(content)

    # Load actual unit definitions from TypeScript files
    unit_definitions = load_unit_definitions_from_ts(unit_registry)

    config["units"] = load_scenario_units(unit_definitions, scenario_path)

    return config


def load_unit_definitions_from_ts(unit_registry):
    """Load unit definitions by parsing TypeScript static class properties."""
    import re
    import os
    from engine.weapons import get_weapons
    
    unit_definitions = {}
    
    for unit_name, faction_path in unit_registry["units"].items():
        ts_file_path = f"frontend/src/roster/{faction_path}.ts"
        
        if not os.path.exists(ts_file_path):
            print(f"Warning: Unit file not found: {ts_file_path}")
            continue
        
        try:
            with open(ts_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            unit_stats = {}
            
            # Pattern 1: Static properties simples (HP_MAX, MOVE, etc.)
            static_pattern = r'static\s+([A-Z_]+)\s*=\s*([^;]+);'
            matches = re.findall(static_pattern, content)
            
            for field_name, value_str in matches:
                value_str = value_str.strip().strip('"\'')
                # Remove comments (everything after // or #)
                if '//' in value_str:
                    value_str = value_str.split('//')[0].strip()
                if '#' in value_str:
                    value_str = value_str.split('#')[0].strip()
                if value_str.isdigit() or (value_str.startswith('-') and value_str[1:].isdigit()):
                    unit_stats[field_name] = int(value_str)
                elif value_str.replace('.', '').isdigit():
                    unit_stats[field_name] = float(value_str)
                else:
                    unit_stats[field_name] = value_str
            
            # Pattern 2: RNG_WEAPON_CODES = ["code1", "code2"] ou [] (robuste)
            rng_codes_match = re.search(
                r'static\s+RNG_WEAPON_CODES\s*=\s*\[([^\]]*)\];',
                content,
                re.MULTILINE | re.DOTALL  # Support multi-lignes
            )
            if rng_codes_match:
                codes_str = rng_codes_match.group(1).strip()
                if codes_str:
                    # Gérer guillemets simples ET doubles
                    codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
                else:
                    codes = []  # Array vide
                
                # Détection faction robuste
                if faction_path.startswith('spaceMarine/'):
                    faction = 'SpaceMarine'
                elif faction_path.startswith('tyranid/'):
                    faction = 'Tyranid'
                else:
                    raise ValueError(f"Unknown faction in path: {faction_path}")
                
                unit_stats["RNG_WEAPONS"] = get_weapons(faction, codes)
            
            # Pattern 3: CC_WEAPON_CODES (même logique)
            cc_codes_match = re.search(
                r'static\s+CC_WEAPON_CODES\s*=\s*\[([^\]]*)\];',
                content,
                re.MULTILINE | re.DOTALL
            )
            if cc_codes_match:
                codes_str = cc_codes_match.group(1).strip()
                if codes_str:
                    codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
                else:
                    codes = []
                
                if faction_path.startswith('spaceMarine/'):
                    faction = 'SpaceMarine'
                elif faction_path.startswith('tyranid/'):
                    faction = 'Tyranid'
                else:
                    raise ValueError(f"Unknown faction in path: {faction_path}")
                
                unit_stats["CC_WEAPONS"] = get_weapons(faction, codes)
            
            # Validation: Au moins une arme requise
            if not unit_stats.get("RNG_WEAPONS") and not unit_stats.get("CC_WEAPONS"):
                raise ValueError(f"Unit {unit_name} must have at least RNG_WEAPONS or CC_WEAPONS")
            
            # Initialiser selectedWeaponIndex
            if unit_stats.get("RNG_WEAPONS"):
                unit_stats["selectedRngWeaponIndex"] = 0
            if unit_stats.get("CC_WEAPONS"):
                unit_stats["selectedCcWeaponIndex"] = 0
            
            unit_definitions[unit_name] = unit_stats
            
        except Exception as e:
            print(f"Error parsing {ts_file_path}: {e}")
            continue
    
    return unit_definitions

def load_scenario_units(unit_definitions, scenario_path=None):
    """Load units from scenario file with unit definitions.

    Args:
        unit_definitions: Dictionary of unit type -> unit stats
        scenario_path: Path to scenario file. If None, defaults to config/scenario.json
                      If file doesn't exist, returns empty list.

    Returns:
        List of unit instances for the scenario
    """
    if scenario_path is None:
        scenario_path = "config/scenario.json"

    if not os.path.exists(scenario_path):
        print(f"Warning: Scenario file not found: {scenario_path}, returning empty unit list")
        return []

    with open(scenario_path, 'r', encoding='utf-8') as f:
        scenario_data = json.load(f)
    
    if "units" not in scenario_data:
        raise KeyError("Scenario file missing required 'units' field")
    
    units = []
    for scenario_unit in scenario_data["units"]:
        # Validate required scenario fields
        required_fields = ["id", "unit_type", "player", "col", "row"]
        for field in required_fields:
            if field not in scenario_unit:
                raise KeyError(f"Scenario unit missing required field '{field}': {scenario_unit}")
        
        unit_type = scenario_unit["unit_type"]
        if unit_type not in unit_definitions:
            raise ValueError(f"Unknown unit type '{unit_type}' in scenario. Available: {list(unit_definitions.keys())}")
        
        # Get unit definition and merge with scenario position data
        unit_def = unit_definitions[unit_type]
        
        # Extract SHOOT_LEFT from RNG_WEAPONS[0] if exists
        shoot_left = 0
        if unit_def.get("RNG_WEAPONS") and len(unit_def["RNG_WEAPONS"]) > 0:
            shoot_left = unit_def["RNG_WEAPONS"][0].get("NB", 0)
        
        # Extract ATTACK_LEFT from CC_WEAPONS[0] if exists
        attack_left = 0
        if unit_def.get("CC_WEAPONS") and len(unit_def["CC_WEAPONS"]) > 0:
            attack_left = unit_def["CC_WEAPONS"][0].get("NB", 0)
        
        created_unit = {
            **unit_def,
            "id": str(scenario_unit["id"]),  # Ensure string ID for consistency
            "player": scenario_unit["player"],
            "col": scenario_unit["col"],
            "row": scenario_unit["row"],
            "unitType": unit_type,
            "HP_CUR": unit_def.get("HP_MAX", unit_def.get("HP_MAX", 1)),
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left
        }
        
        units.append(created_unit)
    return units

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
    
    # Test some actions with detailed debugging
    print("\n=== Testing Movement Actions ===")
    
    # Show initial state
    print(f"Initial state:")
    print(f"   Active player: {engine.game_state['current_player']}")
    print(f"   Phase: {engine.game_state['phase']}")
    print(f"   Units moved: {engine.game_state['units_moved']}")
    print(f"   Move activation pool: {engine.game_state['move_activation_pool']}")
    for unit in engine.game_state["units"]:
        print(f"   Unit {unit['id']}: Player {unit['player']} at ({unit['col']}, {unit['row']}) HP:{unit['HP_CUR']}")
    
    # Test turn/phase based logic (AI_TURN.md compliant)
    max_turns = 3
    done = False
    
    while engine.game_state["turn"] <= max_turns and not done:
        current_turn = engine.game_state["turn"]
        current_player = engine.game_state["current_player"]
        current_phase = engine.game_state["phase"]
        
        print(f"\n=== TURN {current_turn}, PLAYER {current_player}, {current_phase.upper()} PHASE ===")
        
        # Process activation pool until phase complete
        while engine.game_state["move_activation_pool"]:
            active_unit_id = engine.game_state["move_activation_pool"][0]
            active_unit = engine._get_unit_by_id(active_unit_id)
            
            if active_unit:
                action = {"action": "move", "unitId": active_unit["id"], "destCol": active_unit["col"] + 1, "destRow": active_unit["row"]}
                print(f"   Activating {active_unit['id']} at ({active_unit['col']}, {active_unit['row']})")
                success, result = engine.step(action)
                print(f"   Result: {result}")
            else:
                engine.game_state["move_activation_pool"].pop(0)
        
        # Phase complete when pool empty - no additional action needed
        print(f"   Phase complete - pool empty")
        
        if current_phase == 'move':
            # Try to move east for current player's first unit
            eligible_units = [u for u in engine.game_state["units"] if u["player"] == current_player and is_unit_alive(str(u["id"]), engine.game_state)]
            if eligible_units:
                unit = eligible_units[0]
                action = {"action": "move", "unitId": unit["id"], "destCol": unit["col"] + 1, "destRow": unit["row"]}
                action_name = f"Move {unit['id']} East"
            else:
                action = {"action": "skip", "unitId": 0}
                action_name = "Skip"
        else:
            action = {"action": "skip", "unitId": 0}
            action_name = "Skip"
        
        success, result = engine.step(action)
        print(f"   Action: {action_name} -> Success: {success}, New Phase: {engine.game_state['phase']}")
        print(f"   Result: {result}")
        
        # Debug state after each action
        print(f"   Units moved after action: {engine.game_state['units_moved']}")
        print(f"   Move activation pool: {engine.game_state['move_activation_pool']}")
        print(f"   Current player: {engine.game_state['current_player']}")
        for unit in engine.game_state["units"]:
            print(f"   Unit {unit['id']}: Player {unit['player']} at ({unit['col']}, {unit['row']})")
        
        if result and isinstance(result, dict):
            if 'action' in result:
                print(f"   Action type: {result['action']}")
                if 'fromCol' in result and 'toCol' in result:
                    print(f"   Movement: ({result['fromCol']}, {result['fromRow']}) -> ({result['toCol']}, {result['toRow']})")
        
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
                    "HP_CUR": 2,
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