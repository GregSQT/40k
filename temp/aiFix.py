#!/usr/bin/env python3
"""
Fix the scenario generation issues for W40K AI training
"""

import os
import json
import re

def create_scenario_from_existing_data():
    """Create scenario.json from the existing Scenario.ts data found in project knowledge."""
    
    # Based on the Scenario.ts data from project knowledge
    scenario_data = [
        {
            "id": 1,
            "unit_type": "Intercessor",
            "player": 0,
            "col": 23,
            "row": 12,
            "cur_hp": 3,
            "hp_max": 3,
            "move": 4,
            "rng_rng": 8,
            "rng_dmg": 2,
            "cc_dmg": 1,
            "is_ranged": True,
            "is_melee": False,
            "alive": True
        },
        {
            "id": 2,
            "unit_type": "AssaultIntercessor",
            "player": 0,
            "col": 1,
            "row": 12,
            "cur_hp": 4,
            "hp_max": 4,
            "move": 6,
            "rng_rng": 4,
            "rng_dmg": 1,
            "cc_dmg": 2,
            "is_ranged": False,
            "is_melee": True,
            "alive": True
        },
        {
            "id": 3,
            "unit_type": "Intercessor",
            "player": 1,
            "col": 0,
            "row": 5,
            "cur_hp": 3,
            "hp_max": 3,
            "move": 4,
            "rng_rng": 8,
            "rng_dmg": 2,
            "cc_dmg": 1,
            "is_ranged": True,
            "is_melee": False,
            "alive": True
        },
        {
            "id": 4,
            "unit_type": "AssaultIntercessor",
            "player": 1,
            "col": 22,
            "row": 3,
            "cur_hp": 4,
            "hp_max": 4,
            "move": 6,
            "rng_rng": 4,
            "rng_dmg": 1,
            "cc_dmg": 2,
            "is_ranged": False,
            "is_melee": True,
            "alive": True
        }
    ]
    
    # Create ai directory if it doesn't exist
    os.makedirs("ai", exist_ok=True)
    
    # Write scenario.json
    with open("ai/scenario.json", "w", encoding="utf-8") as f:
        json.dump(scenario_data, f, indent=2)
    
    print(f"[OK] Created scenario.json with {len(scenario_data)} units")
    return True

def create_fixed_generate_scenario():
    """Create a fixed version of generate_scenario.py that works with your file structure."""
    
    script_content = '''#!/usr/bin/env python3
# generate_scenario.py - Fixed version

import re
import json
import os

def extract_unit_stats_from_ts(file_path):
    """Extract unit stats from TypeScript file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        stats = {
            "hp_max": 4,
            "move": 6,
            "rng_rng": 4,
            "rng_dmg": 1,
            "cc_dmg": 1,
            "is_ranged": False,
            "is_melee": True
        }
        
        # Extract static properties
        for line in content.split('\\n'):
            line = line.strip()
            if 'static MOVE =' in line:
                match = re.search(r'static MOVE\\s*=\\s*(\\d+)', line)
                if match:
                    stats["move"] = int(match.group(1))
            elif 'static HP_MAX =' in line:
                match = re.search(r'static HP_MAX\\s*=\\s*(\\d+)', line)
                if match:
                    stats["hp_max"] = int(match.group(1))
            elif 'static RNG_RNG =' in line:
                match = re.search(r'static RNG_RNG\\s*=\\s*(\\d+)', line)
                if match:
                    stats["rng_rng"] = int(match.group(1))
            elif 'static RNG_DMG =' in line:
                match = re.search(r'static RNG_DMG\\s*=\\s*(\\d+)', line)
                if match:
                    stats["rng_dmg"] = int(match.group(1))
            elif 'static CC_DMG =' in line:
                match = re.search(r'static CC_DMG\\s*=\\s*(\\d+)', line)
                if match:
                    stats["cc_dmg"] = int(match.group(1))
        
        # Determine unit type from file name
        if "Intercessor" in file_path and "Assault" not in file_path:
            stats["is_ranged"] = True
            stats["is_melee"] = False
        elif "AssaultIntercessor" in file_path:
            stats["is_ranged"] = False
            stats["is_melee"] = True
        
        return stats
    
    except FileNotFoundError:
        print(f"[WARN] File not found: {file_path}")
        return None

def find_unit_files():
    """Find unit files in the project."""
    possible_paths = [
        "frontend/src/roster/spaceMarine/Intercessor.ts",
        "frontend/src/roster/spaceMarine/AssaultIntercessor.ts",
        "src/roster/spaceMarine/Intercessor.ts", 
        "src/roster/spaceMarine/AssaultIntercessor.ts",
        "ts/Intercessor.ts",
        "ts/AssaultIntercessor.ts"
    ]
    
    found_files = {}
    for path in possible_paths:
        if os.path.exists(path):
            if "Intercessor" in path and "Assault" not in path:
                found_files["Intercessor"] = path
            elif "AssaultIntercessor" in path:
                found_files["AssaultIntercessor"] = path
    
    return found_files

def parse_scenario_ts():
    """Parse scenario from various possible locations."""
    scenario_paths = [
        "frontend/src/data/Scenario.ts",
        "src/data/Scenario.ts",
        "ts/Scenario.ts"
    ]
    
    for path in scenario_paths:
        if os.path.exists(path):
            print(f"[OK] Found scenario file: {path}")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Extract unit definitions
                units = []
                unit_id = 1
                
                # Look for unit definitions in TypeScript array
                # This is a simple parser - may need adjustment based on exact format
                lines = content.split('\\n')
                current_unit = None
                
                for line in lines:
                    line = line.strip()
                    if line.startswith('{') and ('id:' in line or 'name:' in line or 'type:' in line):
                        current_unit = {}
                    elif current_unit is not None:
                        if 'id:' in line:
                            match = re.search(r'id:\\s*(\\d+)', line)
                            if match:
                                current_unit['id'] = int(match.group(1))
                        elif 'type:' in line:
                            match = re.search(r'type:\\s*["\\'](.*?)["\\'']', line)
                            if match:
                                current_unit['unit_type'] = match.group(1).replace(' ', '')
                        elif 'player:' in line:
                            match = re.search(r'player:\\s*(\\d+)', line)
                            if match:
                                current_unit['player'] = int(match.group(1))
                        elif 'col:' in line:
                            match = re.search(r'col:\\s*(\\d+)', line)
                            if match:
                                current_unit['col'] = int(match.group(1))
                        elif 'row:' in line:
                            match = re.search(r'row:\\s*(\\d+)', line)
                            if match:
                                current_unit['row'] = int(match.group(1))
                        elif line.startswith('}'):
                            if current_unit and 'id' in current_unit:
                                units.append(current_unit)
                            current_unit = None
                
                return units
                
            except Exception as e:
                print(f"[WARN] Error parsing {path}: {e}")
                continue
    
    print("[WARN] No scenario file found, using default")
    return None

def main():
    print("Generating scenario.json...")
    
    # Try to find and parse unit files
    unit_files = find_unit_files()
    unit_stats = {}
    
    for unit_type, file_path in unit_files.items():
        stats = extract_unit_stats_from_ts(file_path)
        if stats:
            unit_stats[unit_type] = stats
            print(f"[OK] Loaded stats for {unit_type}")
        else:
            print(f"[WARN] Could not load stats for {unit_type}")
    
    # Try to parse scenario
    scenario_units = parse_scenario_ts()
    
    if not scenario_units:
        # Use default scenario
        scenario_units = [
            {"id": 1, "unit_type": "Intercessor", "player": 0, "col": 23, "row": 12},
            {"id": 2, "unit_type": "AssaultIntercessor", "player": 0, "col": 1, "row": 12},
            {"id": 3, "unit_type": "Intercessor", "player": 1, "col": 0, "row": 5},
            {"id": 4, "unit_type": "AssaultIntercessor", "player": 1, "col": 22, "row": 3}
        ]
        print("[OK] Using default scenario")
    
    # Combine scenario with unit stats
    final_units = []
    for unit in scenario_units:
        unit_type = unit.get('unit_type', 'Intercessor')
        stats = unit_stats.get(unit_type, {
            "hp_max": 4, "move": 6, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
            "is_ranged": True, "is_melee": False
        })
        
        final_unit = {
            "id": unit.get('id', len(final_units) + 1),
            "unit_type": unit_type,
            "player": unit.get('player', 0),
            "col": unit.get('col', 5),
            "row": unit.get('row', 5),
            "cur_hp": stats["hp_max"],
            "hp_max": stats["hp_max"],
            "move": stats["move"],
            "rng_rng": stats["rng_rng"],
            "rng_dmg": stats["rng_dmg"],
            "cc_dmg": stats["cc_dmg"],
            "is_ranged": stats["is_ranged"],
            "is_melee": stats["is_melee"],
            "alive": True
        }
        
        final_units.append(final_unit)
    
    # Write output
    os.makedirs("ai", exist_ok=True)
    output_path = os.path.join("ai", "scenario.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_units, f, indent=2)
    
    print(f"[OK] Generated scenario.json with {len(final_units)} units")
    print(f"     Output: {output_path}")
    
    return True

if __name__ == "__main__":
    main()
'''
    
    with open("generate_scenario.py", "w", encoding="utf-8") as f:
        f.write(script_content)
    print("[OK] Created fixed generate_scenario.py")

def create_bypass_training_script():
    """Create a training script that bypasses scenario generation."""
    
    bypass_script = '''#!/usr/bin/env python3
# train_ai_bypass.py - Training script that bypasses scenario generation

import os
import sys
import json

# Add current directory to path
sys.path.insert(0, os.getcwd())

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from ai.gym40k import W40KEnv

def create_default_scenario():
    """Create a default scenario directly."""
    scenario_data = [
        {
            "id": 1, "unit_type": "Intercessor", "player": 0,
            "col": 23, "row": 12, "cur_hp": 3, "hp_max": 3,
            "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
            "is_ranged": True, "is_melee": False, "alive": True
        },
        {
            "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
            "col": 1, "row": 12, "cur_hp": 4, "hp_max": 4,
            "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
            "is_ranged": False, "is_melee": True, "alive": True
        },
        {
            "id": 3, "unit_type": "Intercessor", "player": 1,
            "col": 0, "row": 5, "cur_hp": 3, "hp_max": 3,
            "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
            "is_ranged": True, "is_melee": False, "alive": True
        },
        {
            "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
            "col": 22, "row": 3, "cur_hp": 4, "hp_max": 4,
            "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
            "is_ranged": False, "is_melee": True, "alive": True
        }
    ]
    
    os.makedirs("ai", exist_ok=True)
    with open("ai/scenario.json", "w", encoding="utf-8") as f:
        json.dump(scenario_data, f, indent=2)
    print("[OK] Created default scenario.json")

def main():
    print("W40K AI Training - Bypass Version")
    print("=" * 40)
    
    # Create scenario directly
    if not os.path.exists("ai/scenario.json"):
        print("Creating default scenario...")
        create_default_scenario()
    else:
        print("[OK] Scenario file already exists")
    
    # Create environment
    print("Creating environment...")
    env = W40KEnv()
    
    # Check environment
    print("Checking environment...")
    try:
        check_env(env)
        print("[OK] Environment validation passed")
    except Exception as e:
        print(f"[WARN] Environment check warning: {e}")
    
    print(f"Environment info:")
    print(f"  Units: {len(env.units)}")
    print(f"  Observation space: {env.observation_space}")
    print(f"  Action space: {env.action_space}")
    
    # Training configuration
    total_timesteps = 10_000  # Start small
    
    if "--normal" in sys.argv:
        total_timesteps = 100_000
    elif "--full" in sys.argv:
        total_timesteps = 1_000_000
    
    print(f"Training for {total_timesteps:,} timesteps...")
    
    # Create model
    model_path = "ai/model.zip"
    
    if os.path.exists(model_path) and "--resume" in sys.argv:
        print("Loading existing model...")
        model = DQN.load(model_path, env=env)
    else:
        print("Creating new model...")
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            buffer_size=50_000,
            learning_rate=1e-3,
            learning_starts=1000,
            batch_size=64,
            train_freq=4,
            target_update_interval=1000,
            exploration_fraction=0.3,
            exploration_final_eps=0.05,
            tensorboard_log="./tensorboard/"
        )
    
    # Train
    try:
        model.learn(total_timesteps=total_timesteps)
        print("[OK] Training completed!")
    except KeyboardInterrupt:
        print("[STOP] Training interrupted")
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Save
    model.save(model_path)
    print(f"[OK] Model saved to {model_path}")
    
    env.close()
    print("\\nTraining completed! Use 'python test_ai.py' to test the model.")
    return True

if __name__ == "__main__":
    main()
'''
    
    with open("train_ai_bypass.py", "w", encoding="utf-8") as f:
        f.write(bypass_script)
    print("[OK] Created bypass training script")

def main():
    """Main function to fix scenario generation issues."""
    print("Fixing scenario generation issues...")
    print("=" * 40)
    
    # Option 1: Create scenario.json directly
    print("1. Creating scenario.json directly...")
    create_scenario_from_existing_data()
    
    # Option 2: Create fixed generate_scenario.py
    print("\\n2. Creating fixed generate_scenario.py...")
    create_fixed_generate_scenario()
    
    # Option 3: Create bypass training script
    print("\\n3. Creating bypass training script...")
    create_bypass_training_script()
    
    print("\\n" + "=" * 40)
    print("Scenario fixes completed!")
    print("\\nNow you can:")
    print("  * python train_ai_bypass.py       (training with built-in scenario)")
    print("  * python train_ai.py              (training with generated scenario)")
    print("  * python generate_scenario.py     (generate scenario manually)")
    print("\\nThe bypass version should work immediately!")

if __name__ == "__main__":
    main()