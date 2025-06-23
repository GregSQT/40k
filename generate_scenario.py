# generate_scenario.py

import re
import json
import os

# === Paths ===
BASE_DIR = os.path.dirname(__file__)
SCENARIO_TS = os.path.join(BASE_DIR, "ts", "Scenario.ts")
UNIT_FILES = {
    "Intercessor": os.path.join(BASE_DIR, "ts", "Intercessor.ts"),
    "AssaultIntercessor": os.path.join(BASE_DIR, "ts", "AssaultIntercessor.ts")
}
OUTPUT_JSON = os.path.join(BASE_DIR, "ai", "scenario.json")

# === Extract unit stats ===
def parse_unit_stats(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
    stats = {}
    for field in ["hp", "move", "rng_rng", "rng_dmg", "cc_dmg", "is_ranged", "is_melee"]:
        match = re.search(rf'\b{field}\s*=?\s*([^\n;]+)', text)
        if match:
            value = match.group(1).strip()
            if value.lower() in ["true", "false"]:
                stats[field] = value.lower() == "true"
            else:
                try:
                    stats[field] = int(value)
                except ValueError:
                    stats[field] = 0
        else:
            stats[field] = 0
    stats["hp_max"] = stats["hp"]
    return stats

unit_stats = {name: parse_unit_stats(path) for name, path in UNIT_FILES.items()}

# === Extract units from Scenario.ts ===
with open(SCENARIO_TS, "r", encoding="utf-8") as f:
    scenario_code = f.read()

# Match new UnitType(x, y, 0) and new UnitType(x, y, 1)
unit_matches = re.findall(r'new (\w+)\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(0|1)\s*\)', scenario_code)

units = []
for idx, (unit_type, col, row, player) in enumerate(unit_matches):
    stats = unit_stats.get(unit_type, {})
    units.append({
        "id": idx + 1,
        "unit_type": unit_type,
        "player": int(player),
        "col": int(col),
        "row": int(row),
        "cur_hp": stats["hp_max"],
        "hp_max": stats["hp_max"],
        "move": stats["move"],
        "rng_rng": stats["rng_rng"],
        "rng_dmg": stats["rng_dmg"],
        "cc_dmg": stats["cc_dmg"],
        "is_ranged": stats["is_ranged"],
        "is_melee": stats["is_melee"],
        "alive": True
    })

# === Write scenario.json ===
os.makedirs(os.path.join(BASE_DIR, "ai"), exist_ok=True)
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(units, f, indent=2)

print(f"✅ scenario.json generated with {len(units)} units at: {OUTPUT_JSON}")
