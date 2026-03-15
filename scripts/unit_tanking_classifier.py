#!/usr/bin/env python3
"""
Classify infantry units by tanking profile using fixed weapon benchmarks.

Usage example:
  python scripts/unit_tanking_classifier.py \
    --units-dir frontend/src/roster/spaceMarine/units \
    --output-csv reports/space_marine_tanking.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class WeaponProfile:
    name: str
    strength: int
    ap: int
    damage: int


@dataclass(frozen=True)
class UnitProfile:
    unit_id: str
    display_name: str
    toughness: int
    armor_save: int
    invul_save: int
    hp_max: int
    declared_tanking_level: str | None = None


WEAPON_PROFILES: Tuple[WeaponProfile, ...] = (
    WeaponProfile(name="light_F3_AP0_D1", strength=3, ap=0, damage=1),
    WeaponProfile(name="standard_F4_AP-1_D1", strength=4, ap=-1, damage=1),
    WeaponProfile(name="anti_elite_F7_AP-2_D2", strength=7, ap=-2, damage=2),
)

ARCHETYPES: Dict[str, UnitProfile] = {
    "Swarm": UnitProfile(unit_id="Swarm", display_name="Swarm", toughness=3, armor_save=6, invul_save=7, hp_max=1),
    "Troop": UnitProfile(unit_id="Troop", display_name="Troop", toughness=4, armor_save=3, invul_save=7, hp_max=2),
    "Elite": UnitProfile(unit_id="Elite", display_name="Elite", toughness=5, armor_save=2, invul_save=4, hp_max=3),
}


def _probability_roll_success(target: int) -> float:
    """Return probability to succeed a D6 roll with threshold target (2+..6+)."""
    if target <= 1:
        return 1.0
    if target >= 7:
        return 0.0
    return (7 - target) / 6.0


def _wound_target(strength: int, toughness: int) -> int:
    """Compute wound roll threshold from 40K strength vs toughness rule."""
    if strength >= 2 * toughness:
        return 2
    if strength > toughness:
        return 3
    if strength == toughness:
        return 4
    if 2 * strength <= toughness:
        return 6
    return 5


def _effective_save_target(armor_save: int, invul_save: int, ap: int) -> int:
    """
    Compute best available save target.

    AP uses signed value (example: -1, -2).
    """
    armor_after_ap = armor_save - ap
    armor_after_ap = min(max(armor_after_ap, 2), 7)
    invul_target = min(max(invul_save, 2), 7)
    return min(armor_after_ap, invul_target)


def _expected_damage_per_shot(
    weapon: WeaponProfile,
    target: UnitProfile,
    attacker_bs: int,
) -> float:
    """Expected damage dealt by one shot against target profile."""
    p_hit = _probability_roll_success(attacker_bs)
    p_wound = _probability_roll_success(_wound_target(weapon.strength, target.toughness))
    save_target = _effective_save_target(target.armor_save, target.invul_save, weapon.ap)
    p_fail_save = 1.0 - _probability_roll_success(save_target)
    return p_hit * p_wound * p_fail_save * float(weapon.damage)


def _shots_to_kill(weapon: WeaponProfile, target: UnitProfile, attacker_bs: int) -> float:
    """Expected number of shots required to deplete target HP."""
    damage_per_shot = _expected_damage_per_shot(weapon, target, attacker_bs)
    if damage_per_shot <= 0.0:
        return float("inf")
    return target.hp_max / damage_per_shot


def _parse_static_number(contents: str, field_name: str) -> int:
    pattern = rf"static\s+{re.escape(field_name)}\s*=\s*(-?\d+)"
    match = re.search(pattern, contents)
    if match is None:
        raise ValueError(f"Missing required static field '{field_name}'")
    return int(match.group(1))


def _parse_static_string(contents: str, field_name: str) -> str:
    pattern = rf"static\s+{re.escape(field_name)}\s*=\s*\"([^\"]+)\""
    match = re.search(pattern, contents)
    if match is None:
        raise ValueError(f"Missing required static field '{field_name}'")
    return match.group(1)


def _load_unit_profile_from_ts(path: Path) -> UnitProfile:
    contents = path.read_text(encoding="utf-8")
    unit_id = _parse_static_string(contents, "NAME")
    display_name = _parse_static_string(contents, "DISPLAY_NAME")
    toughness = _parse_static_number(contents, "T")
    armor_save = _parse_static_number(contents, "ARMOR_SAVE")
    invul_save = _parse_static_number(contents, "INVUL_SAVE")
    hp_max = _parse_static_number(contents, "HP_MAX")
    declared_tanking_level: str | None = None
    try:
        declared_tanking_level = _parse_static_string(contents, "TANKING_LEVEL")
    except ValueError:
        declared_tanking_level = None
    return UnitProfile(
        unit_id=unit_id,
        display_name=display_name,
        toughness=toughness,
        armor_save=armor_save,
        invul_save=invul_save,
        hp_max=hp_max,
        declared_tanking_level=declared_tanking_level,
    )


def _tanking_vector(unit: UnitProfile, attacker_bs: int) -> List[float]:
    return [_shots_to_kill(weapon, unit, attacker_bs) for weapon in WEAPON_PROFILES]


def _euclidean_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _classify_unit(
    unit_vector: List[float],
    archetype_vectors: Dict[str, List[float]],
) -> Tuple[str, Dict[str, float]]:
    distances = {name: _euclidean_distance(unit_vector, vec) for name, vec in archetype_vectors.items()}
    category = min(distances.items(), key=lambda item: item[1])[0]
    return category, distances


def _format_float(value: float) -> str:
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def _print_table(rows: List[Dict[str, str]], include_check: bool) -> None:
    headers = ["UniteID", "Swarm", "Troop", "Elite", "Categorie"]
    if include_check:
        headers.append("Check")
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(str(row[header])))

    def _line() -> str:
        return "+-" + "-+-".join("-" * widths[h] for h in headers) + "-+"

    print(_line())
    print("| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |")
    print(_line())
    for row in rows:
        print("| " + " | ".join(str(row[h]).ljust(widths[h]) for h in headers) + " |")
    print(_line())


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify unit tanking profile from faction unit files")
    parser.add_argument(
        "--units-dir",
        required=True,
        help="Directory containing unit TypeScript files (example: frontend/src/roster/spaceMarine/units)",
    )
    parser.add_argument(
        "--attacker-bs",
        type=int,
        default=3,
        help="Attacker ballistic skill threshold used for shots-to-kill expectation (default: 3 for 3+).",
    )
    parser.add_argument(
        "--output-csv",
        default="reports/unit_tanking_classification.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare predicted category with unit static TANKING_LEVEL and add Check column.",
    )
    args = parser.parse_args()

    units_dir = Path(args.units_dir)
    if not units_dir.exists() or not units_dir.is_dir():
        raise FileNotFoundError(f"Invalid units directory: {units_dir}")
    if args.attacker_bs < 2 or args.attacker_bs > 6:
        raise ValueError(f"--attacker-bs must be between 2 and 6 (got {args.attacker_bs})")

    unit_files = sorted(units_dir.glob("*.ts"))
    if not unit_files:
        raise FileNotFoundError(f"No .ts unit files found in {units_dir}")

    archetype_vectors = {name: _tanking_vector(profile, args.attacker_bs) for name, profile in ARCHETYPES.items()}
    parsed_units = [_load_unit_profile_from_ts(path) for path in unit_files]

    table_rows: List[Dict[str, str]] = []
    csv_rows: List[Dict[str, str]] = []

    for unit in parsed_units:
        vector = _tanking_vector(unit, args.attacker_bs)
        category, distances = _classify_unit(vector, archetype_vectors)
        check_value = "N/A"
        if args.check:
            if unit.declared_tanking_level is None:
                check_value = "MISSING"
            elif unit.declared_tanking_level == category:
                check_value = "OK"
            else:
                check_value = "KO"
        row = {
            "UniteID": unit.unit_id,
            "Swarm": _format_float(distances["Swarm"]),
            "Troop": _format_float(distances["Troop"]),
            "Elite": _format_float(distances["Elite"]),
            "Categorie": category,
            "Check": check_value,
        }
        table_rows.append(row)
        csv_rows.append(
            {
                **row,
                "DisplayName": unit.display_name,
                "Declared_TANKING_LEVEL": unit.declared_tanking_level if unit.declared_tanking_level is not None else "",
                WEAPON_PROFILES[0].name: _format_float(vector[0]),
                WEAPON_PROFILES[1].name: _format_float(vector[1]),
                WEAPON_PROFILES[2].name: _format_float(vector[2]),
                "T": str(unit.toughness),
                "ARMOR_SAVE": str(unit.armor_save),
                "INVUL_SAVE": str(unit.invul_save),
                "HP_MAX": str(unit.hp_max),
            }
        )

    table_rows.sort(key=lambda x: (x["Categorie"], x["UniteID"]))
    csv_rows.sort(key=lambda x: (x["Categorie"], x["UniteID"]))

    output_csv_path = Path(args.output_csv)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "UniteID",
        "DisplayName",
        "Swarm",
        "Troop",
        "Elite",
        "Categorie",
        "Check",
        "Declared_TANKING_LEVEL",
        WEAPON_PROFILES[0].name,
        WEAPON_PROFILES[1].name,
        WEAPON_PROFILES[2].name,
        "T",
        "ARMOR_SAVE",
        "INVUL_SAVE",
        "HP_MAX",
    ]
    with output_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Units parsed: {len(parsed_units)}")
    print(f"Weapons used for tanking score: {[w.name for w in WEAPON_PROFILES]}")
    print(f"Attacker BS assumption: {args.attacker_bs}+")
    if args.check:
        print("Check mode: enabled (predicted category vs static TANKING_LEVEL)")
    print(f"CSV exported: {output_csv_path}")
    print()
    _print_table(table_rows, include_check=args.check)


if __name__ == "__main__":
    main()
