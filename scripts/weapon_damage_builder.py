#!/usr/bin/env python3
"""
weapon_damage_builder.py - Pre-compute expected damage for all weapon × target profile combinations.

Generates config/weapon_damage_table.json used by engine/weapon_damage_cache.py
to eliminate all runtime weapon probability calculations.

Usage:
    python scripts/weapon_damage_builder.py

Output:
    config/weapon_damage_table.json

Architecture:
    - Parses all faction armories via engine/weapons/parser.py
    - Extracts unique offensive profiles: (ATK, STR, expected_NB, expected_DMG, AP)
    - Enumerates all realistic defensive profiles: (T, ARMOR_SAVE, INVUL_SAVE)
    - Computes expected_damage_per_activation for each (offensive, defensive) pair
    - Runtime: TTK = HP_CUR / expected_damage, kill_prob = min(1.0, expected_damage / HP_CUR)
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Set, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Direct file-level imports to avoid engine/__init__.py (which imports torch via w40k_core)
import importlib.util as _ilu

def _load_module(name: str, path: str):
    spec = _ilu.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_combat_utils = _load_module("engine.combat_utils", str(PROJECT_ROOT / "engine" / "combat_utils.py"))
expected_dice_value = _combat_utils.expected_dice_value

# weapons/parser needs weapons/rules → load rules first
_weapons_rules = _load_module("engine.weapons.rules", str(PROJECT_ROOT / "engine" / "weapons" / "rules.py"))
_weapons_parser = _load_module("engine.weapons.parser", str(PROJECT_ROOT / "engine" / "weapons" / "parser.py"))
get_armory_parser = _weapons_parser.get_armory_parser

FACTIONS = ["spaceMarine", "tyranid", "aeldari", "adeptusCustodes", "chaos"]

T_RANGE = range(2, 13)
ARMOR_SAVE_RANGE = range(2, 8)
INVUL_SAVE_RANGE = range(2, 8)


def _compute_expected_damage(
    atk: int, strength: int, exp_nb: float, exp_dmg: float, ap: int,
    toughness: int, armor_save: int, invul_save: int,
) -> float:
    """
    W40K expected damage formula (same as calculate_kill_probability / calculate_ttk_with_weapon).

    Returns expected_damage_per_activation (float). Zero if weapon cannot damage.
    """
    p_hit = max(0.0, min(1.0, (7 - atk) / 6.0))

    if strength >= toughness * 2:
        p_wound = 5.0 / 6.0
    elif strength > toughness:
        p_wound = 4.0 / 6.0
    elif strength == toughness:
        p_wound = 3.0 / 6.0
    elif strength * 2 <= toughness:
        p_wound = 1.0 / 6.0
    else:
        p_wound = 2.0 / 6.0

    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))

    return exp_nb * p_hit * p_wound * p_fail_save * exp_dmg


def _extract_offensive_profiles(parser) -> Dict[Tuple, str]:
    """Extract all unique offensive profiles from all faction armories.

    Returns mapping: (ATK, STR, exp_NB, exp_DMG, AP) -> first weapon name (for logging).
    """
    profiles: Dict[Tuple, str] = {}

    for faction in FACTIONS:
        try:
            armory = parser.get_armory(faction)
        except FileNotFoundError:
            print(f"  WARNING: No armory found for faction {faction}, skipping")
            continue

        for weapon_code, weapon in armory.items():
            atk = weapon.get("ATK")
            strength = weapon.get("STR")
            nb_raw = weapon.get("NB")
            dmg_raw = weapon.get("DMG")
            ap = weapon.get("AP")

            if any(v is None for v in (atk, strength, nb_raw, dmg_raw, ap)):
                print(f"  WARNING: Weapon {weapon_code} in {faction} missing stats, skipping")
                continue

            exp_nb = expected_dice_value(nb_raw, f"builder_{weapon_code}_nb")
            exp_dmg = expected_dice_value(dmg_raw, f"builder_{weapon_code}_dmg")

            off_key = (int(atk), int(strength), float(exp_nb), float(exp_dmg), int(ap))
            if off_key not in profiles:
                display = weapon.get("display_name", weapon_code)
                profiles[off_key] = f"{faction}/{display}"

    return profiles


def build_weapon_damage_table() -> Dict[str, Any]:
    """Build the complete weapon damage table."""
    parser = get_armory_parser()

    print("Extracting offensive profiles from all armories...")
    offensive_profiles = _extract_offensive_profiles(parser)
    print(f"  Found {len(offensive_profiles)} unique offensive profiles")

    defensive_count = len(T_RANGE) * len(ARMOR_SAVE_RANGE) * len(INVUL_SAVE_RANGE)
    print(f"  Defensive profiles: T={T_RANGE.start}-{T_RANGE.stop - 1}, "
          f"ARMOR={ARMOR_SAVE_RANGE.start}-{ARMOR_SAVE_RANGE.stop - 1}, "
          f"INVUL={INVUL_SAVE_RANGE.start}-{INVUL_SAVE_RANGE.stop - 1} "
          f"= {defensive_count} profiles")

    total = len(offensive_profiles) * defensive_count
    print(f"  Computing {total} expected_damage values...")

    entries = []
    for off_key in sorted(offensive_profiles.keys()):
        atk, strength, exp_nb, exp_dmg, ap = off_key
        off_list = [atk, strength, exp_nb, exp_dmg, ap]

        for t in T_RANGE:
            for armor in ARMOR_SAVE_RANGE:
                for invul in INVUL_SAVE_RANGE:
                    dmg = _compute_expected_damage(
                        atk, strength, exp_nb, exp_dmg, ap,
                        t, armor, invul,
                    )
                    if dmg > 0.0:
                        entries.append([off_list, [t, armor, invul], round(dmg, 6)])

    nonzero = len(entries)
    print(f"  Non-zero entries: {nonzero} / {total} ({100 * nonzero / total:.1f}%)")

    table = {
        "version": 1,
        "description": "Pre-computed expected_damage for weapon×target profile combinations",
        "usage": "TTK = HP_CUR / expected_damage, kill_prob = min(1.0, expected_damage / HP_CUR)",
        "offensive_key_format": "[ATK, STR, expected_NB, expected_DMG, AP]",
        "defensive_key_format": "[T, ARMOR_SAVE, INVUL_SAVE]",
        "offensive_profile_count": len(offensive_profiles),
        "defensive_profile_count": defensive_count,
        "nonzero_entry_count": nonzero,
        "entries": entries,
    }
    return table


def main():
    print("=== Weapon Damage Table Builder ===\n")
    table = build_weapon_damage_table()

    output_path = PROJECT_ROOT / "config" / "weapon_damage_table.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(table, f, separators=(",", ":"))

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n  Written: {output_path}")
    print(f"  Size: {size_kb:.1f} KB")
    print("  Done!")


if __name__ == "__main__":
    main()
