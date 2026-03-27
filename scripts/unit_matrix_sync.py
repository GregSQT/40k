#!/usr/bin/env python3
"""
Create missing roster unit files from frontend/src/roster/unit_matrix.json.

Behavior:
- Verifies rows in unit_matrix.json.
- Detects entries that are not present in frontend/src/roster/*/units/*.ts.
- Creates missing unit files only when all required generation fields exist.

Required generation fields for missing entries:
- army
- unit_name
- base_class
- value
- melee_weapons (list[str])
- ranged_weapons (list[str])
- base_stats: {MOVE, T, ARMOR_SAVE, INVUL_SAVE, HP_MAX, LD, OC}

Optional fields:
- class_name (defaults to CamelCase(unit_name))
- display_name (defaults to unit_name)
- icon (defaults to /icons/<class_name>.webp)
- icon_scale (defaults to 1.5)
- unit_keywords (defaults to [])
- unit_rule_entries (list of {ruleId, displayName, grants_rule_ids?}, defaults to [])
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REQUIRED_BASE_STATS = ("MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE", "HP_MAX", "LD", "OC")
REQUIRED_ROW_FIELDS = (
    "army",
    "unit_name",
    "base_class",
    "value",
    "melee_weapons",
    "ranged_weapons",
    "base_stats",
)


def _to_camel_case(value: str) -> str:
    """Convert arbitrary text to CamelCase identifier."""
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        raise ValueError(f"Cannot derive class_name from empty/invalid value '{value}'")
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _normalize_army(army: str) -> tuple[str, str]:
    """Return (army_key, army_dir) pair."""
    mapping = {
        "SpaceMarine": ("SpaceMarine", "spaceMarine"),
        "Tyranid": ("Tyranid", "tyranid"),
        "Aeldari": ("Aeldari", "aeldari"),
        "AdeptusCustodes": ("AdeptusCustodes", "adeptusCustodes"),
        "Chaos": ("Chaos", "chaos"),
    }
    if army in mapping:
        return mapping[army]
    raise ValueError(
        f"Unsupported army '{army}'. Expected one of: {sorted(mapping.keys())}"
    )


def _list_existing_unit_names(roster_root: Path) -> set[tuple[str, str]]:
    """
    Build (army, unit_name) set from existing unit files using static NAME.
    """
    existing: set[tuple[str, str]] = set()
    unit_files = roster_root.glob("*/units/*.ts")
    for file_path in unit_files:
        content = file_path.read_text(encoding="utf-8")
        name_match = re.search(r'static\s+NAME\s*=\s*"([^"]+)"\s*;', content)
        if not name_match:
            raise ValueError(f"Missing static NAME in existing unit file: {file_path}")
        army_dir = file_path.parts[-3]
        if army_dir == "spaceMarine":
            army = "SpaceMarine"
        elif army_dir == "tyranid":
            army = "Tyranid"
        else:
            raise ValueError(f"Unsupported roster army directory '{army_dir}' in {file_path}")
        existing.add((army, name_match.group(1).strip()))
    return existing


def _validate_missing_row(row: dict[str, Any]) -> None:
    """Validate that a missing-row entry has all required generation fields."""
    for field in REQUIRED_ROW_FIELDS:
        if field not in row:
            raise KeyError(
                f"Missing required field '{field}' for unit '{row.get('unit_name', '<unknown>')}'. "
                "Cannot generate unit file."
            )

    base_stats = row["base_stats"]
    if not isinstance(base_stats, dict):
        raise ValueError(
            f"base_stats must be an object for unit '{row.get('unit_name', '<unknown>')}'."
        )
    for stat in REQUIRED_BASE_STATS:
        if stat not in base_stats:
            raise KeyError(
                f"Missing base_stats.{stat} for unit '{row.get('unit_name', '<unknown>')}'."
            )

    if not isinstance(row["melee_weapons"], list) or not isinstance(row["ranged_weapons"], list):
        raise ValueError(
            f"melee_weapons and ranged_weapons must be arrays for unit '{row.get('unit_name', '<unknown>')}'."
        )


def _render_rule_entries(rule_entries: list[dict[str, Any]]) -> str:
    """Render UNIT_RULES block entries."""
    rendered: list[str] = []
    for entry in rule_entries:
        if "ruleId" not in entry or "displayName" not in entry:
            raise KeyError(
                "Each unit_rule_entries item must contain ruleId and displayName."
            )
        grants = entry.get("grants_rule_ids", [])
        grants_text = ", ".join(f'"{rule_id}"' for rule_id in grants)
        rendered.append(
            "    {\n"
            f'      ruleId: "{entry["ruleId"]}",\n'
            f'      displayName: "{entry["displayName"]}",\n'
            f"      grants_rule_ids: [{grants_text}],\n"
            "    },"
        )
    return "\n".join(rendered)


def _create_unit_file(row: dict[str, Any], roster_root: Path) -> Path:
    """Create one missing unit file from row data."""
    army_key, army_dir = _normalize_army(str(row["army"]))
    class_name = str(row.get("class_name") or _to_camel_case(str(row["unit_name"])))
    display_name = str(row.get("display_name") or row["unit_name"])
    icon = str(row.get("icon") or f"/icons/{class_name}.webp")
    icon_scale = row.get("icon_scale", 1.5)
    if not isinstance(icon_scale, (int, float)):
        raise ValueError(f"icon_scale must be numeric for unit '{row['unit_name']}'.")

    base_stats = row["base_stats"]
    base_class = str(row["base_class"])
    value = row["value"]
    if not isinstance(value, int):
        raise ValueError(f"value must be int for unit '{row['unit_name']}'.")

    armory_import = "../armory"
    class_import = f"../classes/{base_class}"

    ranged_weapon_codes = row["ranged_weapons"]
    melee_weapon_codes = row["melee_weapons"]
    special_rule_entries = row.get("unit_rule_entries", [])
    if not isinstance(special_rule_entries, list):
        raise ValueError(
            f"unit_rule_entries must be a list for unit '{row['unit_name']}'."
        )
    unit_keywords = row.get("unit_keywords", [])
    if not isinstance(unit_keywords, list):
        raise ValueError(
            f"unit_keywords must be a list for unit '{row['unit_name']}'."
        )

    keywords_literal = ", ".join(f'{{ keywordId: "{kw}" }}' for kw in unit_keywords)
    ranged_literal = ", ".join(f'"{code}"' for code in ranged_weapon_codes)
    melee_literal = ", ".join(f'"{code}"' for code in melee_weapon_codes)
    unit_rules_literal = _render_rule_entries(special_rule_entries)

    if unit_rules_literal:
        unit_rules_block = f"""  static UNIT_RULES = [
{unit_rules_literal}
  ];
"""
    else:
        unit_rules_block = "  static UNIT_RULES = [];\n"

    unit_keywords_block = f"  static UNIT_KEYWORDS = [{keywords_literal}];" if keywords_literal else "  static UNIT_KEYWORDS = [];"

    unit_source = f"""// Auto-generated from frontend/src/roster/unit_matrix.json
import {{ getWeapons }} from "{armory_import}";
import {{ {base_class} }} from "{class_import}";

export class {class_name} extends {base_class} {{
  static NAME = "{row["unit_name"]}";
  static DISPLAY_NAME = "{display_name}";
  // BASE
  static MOVE = {base_stats["MOVE"]};
  static T = {base_stats["T"]};
  static ARMOR_SAVE = {base_stats["ARMOR_SAVE"]};
  static INVUL_SAVE = {base_stats["INVUL_SAVE"]};
  static HP_MAX = {base_stats["HP_MAX"]};
  static LD = {base_stats["LD"]};
  static OC = {base_stats["OC"]};
  static VALUE = {value};

  // WEAPONS
  static RNG_WEAPON_CODES = [{ranged_literal}];
  static RNG_WEAPONS = getWeapons({class_name}.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = [{melee_literal}];
  static CC_WEAPONS = getWeapons({class_name}.CC_WEAPON_CODES);

  // UNIT RULES
{unit_rules_block}
  // UNIT KEYWORDS
  {unit_keywords_block}

  static ICON = "{icon}";
  static ICON_SCALE = {icon_scale};

  constructor(name: string, startPos: [number, number]) {{
    super(name, {class_name}.HP_MAX, startPos);
  }}
}}
"""

    target_path = roster_root / army_dir / "units" / f"{class_name}.ts"
    if target_path.exists():
        raise FileExistsError(f"Target unit file already exists: {target_path}")
    target_path.write_text(unit_source, encoding="utf-8")
    return target_path


def main() -> int:
    """Entry point."""
    project_root = Path(__file__).resolve().parent.parent
    roster_root = project_root / "frontend" / "src" / "roster"
    matrix_path = roster_root / "unit_matrix.json"

    if not matrix_path.exists():
        raise FileNotFoundError(
            f"Missing matrix file: {matrix_path}. "
            "Expected frontend/src/roster/unit_matrix.json"
        )

    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("unit_matrix.json must contain a 'rows' array.")

    existing = _list_existing_unit_names(roster_root)
    missing = [row for row in rows if (row.get("army"), row.get("unit_name")) not in existing]

    if not missing:
        print("✅ No missing units. Roster already matches unit_matrix.json.")
        return 0

    print(f"🔎 Missing units detected: {len(missing)}")
    created_paths: list[Path] = []
    for row in missing:
        _validate_missing_row(row)
        created_path = _create_unit_file(row, roster_root)
        created_paths.append(created_path)
        print(f"➕ Created {created_path}")

    print(f"✅ Created {len(created_paths)} missing unit file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
