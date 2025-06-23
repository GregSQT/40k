#!/usr/bin/env python3
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
        for line in content.split('\n'):
            line = line.strip()
            if 'static MOVE =' in line:
                match = re.search(r'static MOVE\s*=\s*(\d+)', line)
                if match:
                    stats["move"] = int(match.group(1))
            elif 'static HP_MAX =' in line:
                match = re.search(r'static HP_MAX\s*=\s*(\d+)', line)
                if match:
                    stats["hp_max"] = int(match.group(1))
            elif 'static RNG_RNG =' in line:
                match = re.search(r'static RNG_RNG\s*=\s*(\d+)', line)
                if match:
                    stats["rng_rng"] = int(match.group(1))
            elif 'static RNG_DMG =' in line:
                match = re.search(r'static RNG_DMG\s*=\s*(\d+)', line)
                if match:
                    stats["rng_dmg"] = int(match.group(1))
            elif 'static CC_DMG =' in line:
                match = re.search(r'static CC_DMG\s*=\s*(\d+)', line)
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
                lines = content.split('\n')
                current_unit = None
                
                for line in lines:
                    line = line.strip()
                    if line.startswith('{') and ('id:' in line or 'name:' in line or 'type:' in line):
                        current_unit = {}
                    elif current_unit is not None:
                        if 'id:' in line:
                            match = re.search(r'id:\s*(\d+)', line)
                            if match:
                                current_unit['id'] = int(match.group(1))
                        elif 'type:' in line:
                            match = re.search(r'type:\s*["\'](.*?)["\'']', line)
                            if match:
                                current_unit['unit_type'] = match.group(1).replace(' ', '')
                        elif 'player:' in line:
                            match = re.search(r'player:\s*(\d+)', line)
                            if match:
                                current_unit['player'] = int(match.group(1))
                        elif 'col:' in line:
                            match = re.search(r'col:\s*(\d+)', line)
                            if match:
                                current_unit['col'] = int(match.group(1))
                        elif 'row:' in line:
                            match = re.search(r'row:\s*(\d+)', line)
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
