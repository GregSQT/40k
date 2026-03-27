#!/usr/bin/env python3
"""
Generate unit-agent matrix from TypeScript roster unit files.

Output file:
  frontend/src/roster/unit_matrix.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedUnit:
    """Parsed metadata for a single unit TypeScript file."""

    army: str
    unit_name: str
    base_class: str
    value: int
    melee_weapons: list[str]
    ranged_weapons: list[str]
    special_rules: list[str]
    source_file: str


def _require_match(match: re.Match[str] | None, field_name: str, file_path: Path) -> re.Match[str]:
    """Return regex match or raise an explicit error."""
    if match is None:
        raise ValueError(f"Missing required field '{field_name}' in {file_path}")
    return match


def _parse_unit_file(file_path: Path) -> ParsedUnit:
    """Parse one TypeScript unit file into structured metadata."""
    content = file_path.read_text(encoding="utf-8")

    class_match = _require_match(
        re.search(r"export class\s+(\w+)\s+extends\s+(\w+)", content),
        "class declaration with base class",
        file_path,
    )
    class_name = class_match.group(1)
    base_class = class_match.group(2)

    name_match = _require_match(
        re.search(r'static\s+NAME\s*=\s*"([^"]+)"\s*;', content),
        "static NAME",
        file_path,
    )
    value_match = _require_match(
        re.search(r"static\s+VALUE\s*=\s*(-?\d+)\s*;", content),
        "static VALUE",
        file_path,
    )
    ranged_weapons_match = _require_match(
        re.search(
            r"static\s+RNG_WEAPON_CODES(?:\s*:\s*[^=]+)?\s*=\s*\[([\s\S]*?)\]\s*;",
            content,
            re.MULTILINE,
        ),
        "static RNG_WEAPON_CODES",
        file_path,
    )
    melee_weapons_match = _require_match(
        re.search(
            r"static\s+CC_WEAPON_CODES(?:\s*:\s*[^=]+)?\s*=\s*\[([\s\S]*?)\]\s*;",
            content,
            re.MULTILINE,
        ),
        "static CC_WEAPON_CODES",
        file_path,
    )

    army_dir = file_path.parts[-3]
    army_by_dir = {
        "spaceMarine": "SpaceMarine",
        "tyranid": "Tyranid",
        "aeldari": "Aeldari",
        "adeptusCustodes": "AdeptusCustodes",
        "chaos": "Chaos",
    }
    if army_dir not in army_by_dir:
        raise ValueError(f"Unknown army directory '{army_dir}' for file {file_path}")
    army = army_by_dir[army_dir]

    unit_name = name_match.group(1).strip()
    value = int(value_match.group(1))
    ranged_weapons = re.findall(r'["\']([^"\']+)["\']', ranged_weapons_match.group(1))
    melee_weapons = re.findall(r'["\']([^"\']+)["\']', melee_weapons_match.group(1))

    unit_rules_match = re.search(
        r"static\s+UNIT_RULES(?:\s*:\s*[^=]+)?\s*=\s*\[([\s\S]*?)\]\s*;",
        content,
        re.MULTILINE,
    )
    special_rules: list[str] = []
    if unit_rules_match:
        rules_block = unit_rules_match.group(1)
        display_names = re.findall(r'displayName\s*:\s*["\']([^"\']+)["\']', rules_block)
        rule_ids = re.findall(r'ruleId\s*:\s*["\']([^"\']+)["\']', rules_block)
        special_rules = display_names if display_names else rule_ids

    return ParsedUnit(
        army=army,
        unit_name=unit_name,
        base_class=base_class,
        value=value,
        melee_weapons=melee_weapons,
        ranged_weapons=ranged_weapons,
        special_rules=special_rules,
        source_file=str(file_path.as_posix()),
    )


def _build_agent_key(unit: ParsedUnit) -> str:
    """Build canonical single-agent key."""
    return "CoreAgent"


def generate_matrix(project_root: Path) -> dict[str, Any]:
    """Generate matrix payload from all roster unit files."""
    roster_root = project_root / "frontend" / "src" / "roster"
    unit_files = sorted(roster_root.glob("*/units/*.ts"))
    if not unit_files:
        raise FileNotFoundError(f"No unit files found under {roster_root}")

    parsed_units = [_parse_unit_file(path) for path in unit_files]
    parsed_units.sort(key=lambda u: (u.army, u.unit_name, u.source_file))

    rows: list[dict[str, Any]] = []
    for unit in parsed_units:
        rows.append(
            {
                "army": unit.army,
                "unit_name": unit.unit_name,
                "agent_key": _build_agent_key(unit),
                "base_class": unit.base_class,
                "value": unit.value,
                "melee_weapons": unit.melee_weapons,
                "ranged_weapons": unit.ranged_weapons,
                "special_rules": unit.special_rules,
            }
        )

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "frontend/src/roster/*/units/*.ts",
        "rows": rows,
    }


def _normalize_for_comparison(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize payload for stable equality checks."""
    normalized = dict(payload)
    normalized["generated_at"] = "<ignored>"
    return normalized


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Generate or check unit-agent matrix JSON.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: do not write file, fail if JSON is not up to date.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / "frontend" / "src" / "roster" / "unit_matrix.json"
    matrix = generate_matrix(project_root)

    if args.check:
        if not output_path.exists():
            print(
                "❌ Missing unit agent matrix file: "
                f"{output_path}\n"
                "Run: python scripts/generate_unit_agent_matrix.py"
            )
            return 1

        current_payload = json.loads(output_path.read_text(encoding="utf-8"))
        if _normalize_for_comparison(current_payload) != _normalize_for_comparison(matrix):
            print(
                "❌ unit_matrix.json is out of date.\n"
                "Run: python scripts/generate_unit_agent_matrix.py"
            )
            return 1
        print("✅ unit_matrix.json is up to date.")
        return 0

    output_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {output_path} with {len(matrix['rows'])} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
