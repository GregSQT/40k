#!/usr/bin/env python3
"""
Unified unit classifier (tanking + offensive).

Sorting order:
1) Tanking category (Swarm -> Troop -> Elite)
2) Blend score (Blend_R)
3) Roster, unit id
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root import.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROSTER_ROOT = PROJECT_ROOT / "frontend" / "src" / "roster"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.weapons.parser import get_armory_parser


TARGET_MARGIN_FIXED = 1.1


@dataclass(frozen=True)
class WeaponProfile:
    name: str
    strength: int
    ap: int
    damage: int


@dataclass(frozen=True)
class TargetProfile:
    name: str
    toughness: int
    armor_save: int
    invul_save: int
    hp: int


@dataclass(frozen=True)
class UnitData:
    unit_id: str
    display_name: str
    rng_codes: Tuple[str, ...]
    cc_codes: Tuple[str, ...]
    declared_offense_type: Optional[str]
    declared_target_type: Optional[str]
    declared_tanking_level: Optional[str]
    toughness: int
    armor_save: int
    invul_save: int
    hp_max: int


WEAPON_PROFILES: Tuple[WeaponProfile, ...] = (
    WeaponProfile(name="light_F3_AP0_D1", strength=3, ap=0, damage=1),
    WeaponProfile(name="standard_F4_AP-1_D1", strength=4, ap=-1, damage=1),
    WeaponProfile(name="anti_elite_F7_AP-2_D2", strength=7, ap=-2, damage=2),
)

# Display-only benchmark targets (for TTK columns).
TARGETS: Tuple[TargetProfile, ...] = (
    TargetProfile(name="Swarm", toughness=3, armor_save=6, invul_save=7, hp=1),
    TargetProfile(name="Troop", toughness=4, armor_save=3, invul_save=7, hp=2),
    TargetProfile(name="Elite", toughness=6, armor_save=2, invul_save=7, hp=3),
)

ARCHETYPES: Dict[str, TargetProfile] = {
    "Swarm": TargetProfile(name="Swarm", toughness=3, armor_save=6, invul_save=7, hp=1),
    "Troop": TargetProfile(name="Troop", toughness=4, armor_save=3, invul_save=7, hp=2),
    "Elite": TargetProfile(name="Elite", toughness=5, armor_save=2, invul_save=4, hp=3),
}


def _parse_static_string(contents: str, field_name: str) -> str:
    match = re.search(rf"static\s+{re.escape(field_name)}\s*(?::[^=]+)?=\s*\"([^\"]+)\"", contents)
    if match is None:
        raise ValueError(f"Missing required static field '{field_name}'")
    return match.group(1)


def _parse_static_number(contents: str, field_name: str) -> int:
    match = re.search(rf"static\s+{re.escape(field_name)}\s*(?::[^=]+)?=\s*(-?\d+)", contents)
    if match is None:
        raise ValueError(f"Missing required static numeric field '{field_name}'")
    return int(match.group(1))


def _parse_static_string_array(contents: str, field_name: str) -> Tuple[str, ...]:
    match = re.search(
        rf"static\s+{re.escape(field_name)}\s*(?::[^=]+)?=\s*\[([^\]]*)\]",
        contents,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"Missing required static array field '{field_name}'")
    return tuple(re.findall(r"\"([^\"]+)\"", match.group(1)))


def _resolve_imported_class_file(unit_file: Path, unit_contents: str, class_name: str) -> Optional[Path]:
    pattern = rf"import\s+\{{[^}}]*\b{re.escape(class_name)}\b[^}}]*\}}\s+from\s+\"([^\"]+)\""
    match = re.search(pattern, unit_contents)
    if match is None:
        return None
    rel_import = match.group(1)
    resolved = (unit_file.parent / rel_import).resolve()
    if resolved.suffix == "":
        resolved = resolved.with_suffix(".ts")
    return resolved if resolved.exists() else None


def _parse_inherited_static_string(unit_file: Path, unit_contents: str, field_name: str) -> Optional[str]:
    extends_match = re.search(r"export\s+class\s+\w+\s+extends\s+(\w+)", unit_contents)
    if extends_match is None:
        return None
    parent_class_name = extends_match.group(1)
    parent_file = _resolve_imported_class_file(unit_file, unit_contents, parent_class_name)
    if parent_file is None:
        return None
    parent_contents = parent_file.read_text(encoding="utf-8")
    try:
        return _parse_static_string(parent_contents, field_name)
    except ValueError:
        return None


def _parse_unit_file(path: Path) -> UnitData:
    contents = path.read_text(encoding="utf-8")
    try:
        declared_offense_type = _parse_static_string(contents, "OFFENSE_TYPE")
    except ValueError:
        declared_offense_type = _parse_inherited_static_string(path, contents, "OFFENSE_TYPE")
    try:
        declared_target_type = _parse_static_string(contents, "TARGET_TYPE")
    except ValueError:
        declared_target_type = _parse_inherited_static_string(path, contents, "TARGET_TYPE")
    try:
        declared_tanking_level = _parse_static_string(contents, "TANKING_LEVEL")
    except ValueError:
        declared_tanking_level = _parse_inherited_static_string(path, contents, "TANKING_LEVEL")

    return UnitData(
        unit_id=_parse_static_string(contents, "NAME"),
        display_name=_parse_static_string(contents, "DISPLAY_NAME"),
        rng_codes=_parse_static_string_array(contents, "RNG_WEAPON_CODES"),
        cc_codes=_parse_static_string_array(contents, "CC_WEAPON_CODES"),
        declared_offense_type=declared_offense_type,
        declared_target_type=declared_target_type,
        declared_tanking_level=declared_tanking_level,
        toughness=_parse_static_number(contents, "T"),
        armor_save=_parse_static_number(contents, "ARMOR_SAVE"),
        invul_save=_parse_static_number(contents, "INVUL_SAVE"),
        hp_max=_parse_static_number(contents, "HP_MAX"),
    )


def _prob_success(target: int) -> float:
    if target <= 1:
        return 1.0
    if target >= 7:
        return 0.0
    return (7 - target) / 6.0


def _wound_target(strength: int, toughness: int) -> int:
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
    armor_after_ap = min(max(armor_save - ap, 2), 7)
    invul = min(max(invul_save, 2), 7)
    return min(armor_after_ap, invul)


def _expected_damage_per_shot(weapon: WeaponProfile, target: TargetProfile, attacker_bs: int) -> float:
    p_hit = _prob_success(attacker_bs)
    p_wound = _prob_success(_wound_target(weapon.strength, target.toughness))
    save_target = _effective_save_target(target.armor_save, target.invul_save, weapon.ap)
    p_fail_save = 1.0 - _prob_success(save_target)
    return p_hit * p_wound * p_fail_save * float(weapon.damage)


def _shots_to_kill(weapon: WeaponProfile, target: TargetProfile, attacker_bs: int) -> float:
    damage_per_shot = _expected_damage_per_shot(weapon, target, attacker_bs)
    if damage_per_shot <= 0.0:
        return float("inf")
    return target.hp / damage_per_shot


def _unit_as_target(unit: UnitData) -> TargetProfile:
    return TargetProfile(
        name=unit.unit_id,
        toughness=unit.toughness,
        armor_save=unit.armor_save,
        invul_save=unit.invul_save,
        hp=unit.hp_max,
    )


def _tanking_vector(target: TargetProfile, attacker_bs: int) -> List[float]:
    return [_shots_to_kill(weapon, target, attacker_bs) for weapon in WEAPON_PROFILES]


def _euclidean_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _classify_tanking(unit_vector: List[float], archetype_vectors: Dict[str, List[float]]) -> Tuple[str, Dict[str, float]]:
    distances = {name: _euclidean_distance(unit_vector, vec) for name, vec in archetype_vectors.items()}
    category = min(distances.items(), key=lambda item: item[1])[0]
    return category, distances


def _dice_expectation(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise TypeError(f"Unsupported dice value type: {type(value).__name__}")
    mapping = {"D3": 2.0, "D6": 3.5, "2D6": 7.0, "D6+1": 4.5}
    if value not in mapping:
        raise ValueError(f"Unsupported dice expression: {value}")
    return mapping[value]


def _extract_rule_value(weapon_rules: List[str], prefix: str) -> int:
    for rule in weapon_rules:
        if rule.startswith(prefix):
            _, _, raw = rule.partition(":")
            if not raw:
                raise ValueError(f"Rule '{rule}' requires numeric value")
            return int(raw)
    return 0


def _expected_hits_per_attack(weapon: Dict[str, Any], uptime_heavy: float) -> float:
    rules = weapon.get("WEAPON_RULES", [])
    if not isinstance(rules, list):
        raise TypeError(f"WEAPON_RULES must be list, got {type(rules).__name__}")
    if "TORRENT" in rules:
        return 1.0

    atk_target = int(weapon["ATK"])
    base_hit = _prob_success(atk_target)
    heavy_hit = _prob_success(max(2, atk_target - 1))
    p_hit = ((1.0 - uptime_heavy) * base_hit + uptime_heavy * heavy_hit) if "HEAVY" in rules else base_hit

    sustained_hits = _extract_rule_value(rules, "SUSTAINED_HITS:")
    p_crit_hit = 1.0 / 6.0
    return p_hit + p_crit_hit * sustained_hits


def _expected_wound_probabilities(weapon: Dict[str, Any], target: TargetProfile) -> Tuple[float, float]:
    rules = weapon.get("WEAPON_RULES", [])
    if not isinstance(rules, list):
        raise TypeError(f"WEAPON_RULES must be list, got {type(rules).__name__}")

    wound_tgt = _wound_target(int(weapon["STR"]), target.toughness)
    p_wound_base = _prob_success(wound_tgt)
    p_crit_base = 1.0 / 6.0 if wound_tgt <= 6 else 0.0

    if "TWIN_LINKED" in rules:
        p_fail = 1.0 - p_wound_base
        p_wound = p_wound_base + p_fail * p_wound_base
        p_crit = p_crit_base + p_fail * p_crit_base
    else:
        p_wound = p_wound_base
        p_crit = p_crit_base
    return p_crit, max(0.0, p_wound - p_crit)


def _expected_damage_per_turn(
    weapon: Dict[str, Any],
    target: TargetProfile,
    uptime_rapid: float,
    uptime_heavy: float,
    cap_damage_to_target_hp: bool = False,
) -> float:
    rules = weapon.get("WEAPON_RULES", [])
    if not isinstance(rules, list):
        raise TypeError(f"WEAPON_RULES must be list, got {type(rules).__name__}")

    n_attacks = _dice_expectation(weapon["NB"]) + uptime_rapid * _extract_rule_value(rules, "RAPID_FIRE:")
    expected_hits = _expected_hits_per_attack(weapon, uptime_heavy)
    p_crit_wound, p_non_crit_wound = _expected_wound_probabilities(weapon, target)

    dmg = _dice_expectation(weapon["DMG"])
    if cap_damage_to_target_hp:
        dmg = min(dmg, float(target.hp))

    save_target = _effective_save_target(target.armor_save, target.invul_save, int(weapon["AP"]))
    p_fail_save = 1.0 - _prob_success(save_target)

    if "DEVASTATING_WOUNDS" in rules:
        expected_damage_per_hit = (p_crit_wound * dmg) + (p_non_crit_wound * p_fail_save * dmg)
    else:
        expected_damage_per_hit = (p_crit_wound + p_non_crit_wound) * p_fail_save * dmg
    return n_attacks * expected_hits * expected_damage_per_hit


def _ttk(hp: int, dpr: float) -> float:
    if dpr <= 0:
        return float("inf")
    return hp / dpr


def _best_dpr_for_mode(
    armory: Dict[str, Dict[str, Any]],
    weapon_codes: Tuple[str, ...],
    target: TargetProfile,
    uptime_rapid: float,
    uptime_heavy: float,
    cap_damage_to_target_hp: bool = False,
) -> float:
    if len(weapon_codes) == 0:
        return 0.0
    best = 0.0
    for code in weapon_codes:
        if code not in armory:
            raise KeyError(f"Weapon code '{code}' not found in armory")
        dpr = _expected_damage_per_turn(
            armory[code],
            target=target,
            uptime_rapid=uptime_rapid,
            uptime_heavy=uptime_heavy,
            cap_damage_to_target_hp=cap_damage_to_target_hp,
        )
        if dpr > best:
            best = dpr
    return best


def _best_ttk_for_mode(
    armory: Dict[str, Dict[str, Any]],
    weapon_codes: Tuple[str, ...],
    target: TargetProfile,
    uptime_rapid: float,
    uptime_heavy: float,
) -> float:
    return _ttk(target.hp, _best_dpr_for_mode(armory, weapon_codes, target, uptime_rapid, uptime_heavy))


def _compute_blend_ranged(avg_ttk_range: float, avg_ttk_melee: float) -> float:
    if math.isinf(avg_ttk_range) and math.isinf(avg_ttk_melee):
        return 0.5
    if math.isinf(avg_ttk_range):
        return 0.0
    if math.isinf(avg_ttk_melee):
        return 1.0
    denom = avg_ttk_range + avg_ttk_melee
    if denom <= 0:
        return 0.5
    return avg_ttk_melee / denom


def _blend_category(blend_ranged: float) -> str:
    if blend_ranged < 0.31:
        return "MeleePure"
    if blend_ranged < 0.42:
        return "MeleeLean"
    if blend_ranged < 0.59:
        return "Balanced"
    if blend_ranged < 0.69:
        return "RangedLean"
    return "RangedPure"


def _offensive_category(ratio: float, ratio_threshold: float) -> str:
    if math.isinf(ratio):
        return "Melee"
    return "Ranged" if ratio <= ratio_threshold else "Melee"


def _compute_offense_check(predicted_category: str, declared_offense_type: Optional[str]) -> str:
    if declared_offense_type is None:
        return "MISSING"
    if declared_offense_type not in {"Ranged", "Melee"}:
        return "INVALID"
    return "OK" if declared_offense_type == predicted_category else "KO"


def _compute_tanking_check(predicted_category: str, declared_tanking_level: Optional[str]) -> str:
    if declared_tanking_level is None:
        return "MISSING"
    if declared_tanking_level not in {"Swarm", "Troop", "Elite"}:
        return "INVALID"
    return "OK" if declared_tanking_level == predicted_category else "KO"


def _map_tanking_level_to_target_label(tanking_level: Optional[str]) -> Optional[str]:
    if tanking_level is None:
        return None
    normalized = tanking_level.strip().lower()
    if "swarm" in normalized:
        return "Swarm"
    if "troop" in normalized:
        return "Troop"
    if "elite" in normalized:
        return "Elite"
    return None


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("Cannot compute median of empty values")
    mid = n // 2
    return ordered[mid] if n % 2 == 1 else 0.5 * (ordered[mid - 1] + ordered[mid])


def _geometric_mean(values: List[float]) -> float:
    if not values:
        raise ValueError("Cannot compute geometric mean of empty values")
    eps = 1e-12
    acc = 0.0
    for value in values:
        acc += math.log(max(value, eps))
    return math.exp(acc / len(values))


def _compute_target_preferences(perf_scores: Dict[str, float]) -> Dict[str, float]:
    gm = _geometric_mean([perf_scores["Swarm"], perf_scores["Troop"], perf_scores["Elite"]])
    if gm <= 0:
        return {"Swarm": 0.0, "Troop": 0.0, "Elite": 0.0}
    return {k: v / gm for k, v in perf_scores.items()}


def _target_rank(label: str) -> int:
    order = {"Swarm": 0, "Troop": 1, "Elite": 2}
    if label not in order:
        raise ValueError(f"Unknown target label rank: {label}")
    return order[label]


def _suggest_target_type_from_preferences(preferences: Dict[str, float], target_margin: float) -> str:
    ordered = sorted(preferences.items(), key=lambda item: item[1], reverse=True)
    best_name, best_score = ordered[0]
    second_name, second_score = ordered[1]
    if second_score > 0 and best_score < (second_score * target_margin):
        return best_name if _target_rank(best_name) >= _target_rank(second_name) else second_name
    return best_name


def _compute_target_check(predicted_target_type: str, declared_target_type: Optional[str]) -> str:
    if declared_target_type is None:
        return "MISSING"
    if declared_target_type not in {"Swarm", "Troop", "Elite"}:
        return "INVALID"
    return "OK" if declared_target_type == predicted_target_type else "KO"


def _format_float(value: float) -> str:
    return "inf" if math.isinf(value) else f"{value:.2f}"


def _resolve_roster_units_dirs(roster_arg: str) -> List[Tuple[str, Path]]:
    if not ROSTER_ROOT.exists() or not ROSTER_ROOT.is_dir():
        raise FileNotFoundError(f"Invalid roster root directory: {ROSTER_ROOT}")
    candidates: List[Tuple[str, Path]] = []
    for child in sorted(ROSTER_ROOT.iterdir()):
        units_dir = child / "units"
        if child.is_dir() and units_dir.is_dir():
            candidates.append((child.name, units_dir))
    if not candidates:
        raise FileNotFoundError(f"No roster directories with units found in {ROSTER_ROOT}")

    if roster_arg == "all":
        return candidates

    selected = [(name, units_dir) for name, units_dir in candidates if name == roster_arg]
    if not selected:
        known = ", ".join(name for name, _ in candidates)
        raise ValueError(f"Unknown roster '{roster_arg}'. Available values: {known}, all")
    return selected


def _tanking_sort_rank(label: str) -> int:
    order = {"Swarm": 0, "Troop": 1, "Elite": 2}
    if label not in order:
        raise ValueError(f"Unknown tanking category: {label}")
    return order[label]


def _offense_sort_rank(label: str) -> int:
    order = {"MeleePure": 0, "MeleeLean": 1, "Balanced": 2, "RangedLean": 3, "RangedPure": 4}
    if label not in order:
        raise ValueError(f"Unknown offense blend category: {label}")
    return order[label]


def _print_table(rows: List[Dict[str, str]], verbous: bool) -> None:
    if verbous:
        headers = [
            "Roster",
            "UniteID",
            "Tanking",
            "BlendCategory",
            "Blend_R",
            "Ratio_R_M",
            "TankDist_Swarm",
            "TankDist_Troop",
            "TankDist_Elite",
            "Shots_F3_AP0_D1",
            "Shots_F4_AP-1_D1",
            "Shots_F7_AP-2_D2",
            "TTK_R_Swarm",
            "TTK_R_Troop",
            "TTK_R_Elite",
            "TTK_M_Swarm",
            "TTK_M_Troop",
            "TTK_M_Elite",
            "TargetType",
            "Perf_Target_Swarm",
            "Perf_Target_Troop",
            "Perf_Target_Elite",
            "Pref_Target_Swarm",
            "Pref_Target_Troop",
            "Pref_Target_Elite",
            "TankCheck",
            "OffenseCheck",
            "TargetCheck",
        ]
    else:
        headers = [
            "Roster",
            "UniteID",
            "Tanking",
            "BlendCategory",
            "Blend_R",
            "Ratio_R_M",
            "TargetType",
        ]
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(row[h]))
    sep = "+-" + "-+-".join("-" * widths[h] for h in headers) + "-+"
    print(sep)
    print("| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |")
    print(sep)
    for row in rows:
        print("| " + " | ".join(row[h].ljust(widths[h]) for h in headers) + " |")
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify units by tanking and offensive profile")
    parser.add_argument(
        "--roster",
        required=True,
        help="Roster name (e.g. spaceMarine, tyranid) or 'all' for every roster",
    )
    parser.add_argument("--attacker-bs", type=int, default=3, help="Attacker BS for tanking benchmark (2..6)")
    parser.add_argument("--uptime-rapid", type=float, default=0.5, help="Rapid Fire uptime in [0,1]")
    parser.add_argument("--uptime-heavy", type=float, default=0.5, help="Heavy uptime in [0,1]")
    parser.add_argument("--ratio-threshold", type=float, default=1.2, help="Ranged/Melee ratio threshold")
    parser.add_argument(
        "--verbous",
        action="store_true",
        help="Show detailed table with tanking/offense/target scores and checks.",
    )
    parser.add_argument(
        "--target-margin",
        type=float,
        default=TARGET_MARGIN_FIXED,
        help="Deprecated: fixed internally to 1.1; kept for backward-compatible CLI.",
    )
    parser.add_argument("--output-csv", default="reports/unit_classification.csv", help="Output CSV")
    args = parser.parse_args()

    if args.attacker_bs < 2 or args.attacker_bs > 6:
        raise ValueError(f"--attacker-bs must be between 2 and 6 (got {args.attacker_bs})")
    for label, value in (("uptime-rapid", args.uptime_rapid), ("uptime-heavy", args.uptime_heavy)):
        if value < 0.0 or value > 1.0:
            raise ValueError(f"--{label} must be in [0,1] (got {value})")
    if args.ratio_threshold <= 0:
        raise ValueError(f"--ratio-threshold must be > 0 (got {args.ratio_threshold})")
    if abs(args.target_margin - TARGET_MARGIN_FIXED) > 1e-9:
        raise ValueError(
            f"--target-margin is fixed to {TARGET_MARGIN_FIXED:.1f} in this version (got {args.target_margin})."
        )

    rows: List[Dict[str, str]] = []
    csv_rows: List[Dict[str, str]] = []
    roster_units = _resolve_roster_units_dirs(args.roster)
    roster_stats: List[Tuple[str, int]] = []

    for roster_name, units_dir in roster_units:
        unit_files = sorted(units_dir.glob("*.ts"))
        if not unit_files:
            raise FileNotFoundError(f"No .ts files found in {units_dir}")
        armory = get_armory_parser().get_armory(roster_name)
        units = [_parse_unit_file(path) for path in unit_files]
        roster_stats.append((roster_name, len(units)))

        archetype_vectors = {name: _tanking_vector(profile, args.attacker_bs) for name, profile in ARCHETYPES.items()}

        defender_pools: Dict[str, List[UnitData]] = {"Swarm": [], "Troop": [], "Elite": []}
        for unit in units:
            pool_label = _map_tanking_level_to_target_label(unit.declared_tanking_level)
            if pool_label is None:
                raise ValueError(
                    f"Unit '{unit.unit_id}' missing mappable TANKING_LEVEL: {unit.declared_tanking_level!r}"
                )
            defender_pools[pool_label].append(unit)
        for label, pool in defender_pools.items():
            if not pool:
                raise ValueError(f"Roster '{roster_name}' has empty defender pool for target category {label}")

        unit_metrics: List[Dict[str, Any]] = []
        for unit in units:
            # Tanking
            unit_target_profile = _unit_as_target(unit)
            tank_vector = _tanking_vector(unit_target_profile, args.attacker_bs)
            tank_category, tank_distances = _classify_tanking(tank_vector, archetype_vectors)
            tank_check = _compute_tanking_check(tank_category, unit.declared_tanking_level)

            # Offensive
            r_ttks: List[float] = []
            m_ttks: List[float] = []
            for target in TARGETS:
                r_ttks.append(_best_ttk_for_mode(armory, unit.rng_codes, target, args.uptime_rapid, args.uptime_heavy))
                m_ttks.append(_best_ttk_for_mode(armory, unit.cc_codes, target, args.uptime_rapid, args.uptime_heavy))
            avg_r = float("inf") if any(math.isinf(x) for x in r_ttks) else sum(r_ttks) / len(r_ttks)
            avg_m = float("inf") if any(math.isinf(x) for x in m_ttks) else sum(m_ttks) / len(m_ttks)
            ratio = float("inf")
            if avg_m > 0 and not math.isinf(avg_r) and not math.isinf(avg_m):
                ratio = avg_r / avg_m
            blend_ranged = _compute_blend_ranged(avg_r, avg_m)
            blend_category = _blend_category(blend_ranged)
            offense_category = _offensive_category(ratio, args.ratio_threshold)
            offense_check = _compute_offense_check(offense_category, unit.declared_offense_type)

            pool_ttk_by_target: Dict[str, float] = {}
            for target_label, defenders in defender_pools.items():
                defender_ttks: List[float] = []
                for defender in defenders:
                    defender_profile = _unit_as_target(defender)
                    best_ranged_dps = _best_dpr_for_mode(
                        armory,
                        unit.rng_codes,
                        defender_profile,
                        args.uptime_rapid,
                        args.uptime_heavy,
                        cap_damage_to_target_hp=True,
                    )
                    best_melee_dps = _best_dpr_for_mode(
                        armory,
                        unit.cc_codes,
                        defender_profile,
                        args.uptime_rapid,
                        args.uptime_heavy,
                        cap_damage_to_target_hp=True,
                    )
                    preferred_dps = best_ranged_dps if offense_category == "Ranged" else best_melee_dps
                    defender_ttks.append(_ttk(defender_profile.hp, preferred_dps))
                finite_ttks = [x for x in defender_ttks if not math.isinf(x)]
                pool_ttk_by_target[target_label] = float("inf") if not finite_ttks else _median(finite_ttks)

            unit_metrics.append(
                {
                    "unit": unit,
                    "tank_vector": tank_vector,
                    "tank_category": tank_category,
                    "tank_distances": tank_distances,
                    "tank_check": tank_check,
                    "r_ttks": r_ttks,
                    "m_ttks": m_ttks,
                    "ratio": ratio,
                    "blend_ranged": blend_ranged,
                    "blend_category": blend_category,
                    "offense_category": offense_category,
                    "offense_check": offense_check,
                    "pool_ttk_by_target": pool_ttk_by_target,
                }
            )

        baseline_ttk_by_target: Dict[str, float] = {}
        for target_label in ("Swarm", "Troop", "Elite"):
            values = [
                metric["pool_ttk_by_target"][target_label]
                for metric in unit_metrics
                if not math.isinf(metric["pool_ttk_by_target"][target_label])
            ]
            if not values:
                raise ValueError(f"Cannot compute baseline TTK for roster '{roster_name}' target category {target_label}")
            baseline_ttk_by_target[target_label] = _median(values)

        for metric in unit_metrics:
            unit = metric["unit"]
            target_perf_scores: Dict[str, float] = {}
            for target_label in ("Swarm", "Troop", "Elite"):
                unit_ttk = metric["pool_ttk_by_target"][target_label]
                baseline_ttk = baseline_ttk_by_target[target_label]
                target_perf_scores[target_label] = 0.0 if math.isinf(unit_ttk) or unit_ttk <= 0 else baseline_ttk / unit_ttk

            target_preferences = _compute_target_preferences(target_perf_scores)
            target_type = _suggest_target_type_from_preferences(target_preferences, TARGET_MARGIN_FIXED)
            target_check = _compute_target_check(target_type, unit.declared_target_type)

            row = {
                "Roster": roster_name,
                "UniteID": unit.unit_id,
                "Tanking": metric["tank_category"],
                "BlendCategory": metric["blend_category"],
                "Blend_R": f"{metric['blend_ranged']:.3f}",
                "Ratio_R_M": _format_float(metric["ratio"]),
                "TargetType": target_type,
                "TankDist_Swarm": _format_float(metric["tank_distances"]["Swarm"]),
                "TankDist_Troop": _format_float(metric["tank_distances"]["Troop"]),
                "TankDist_Elite": _format_float(metric["tank_distances"]["Elite"]),
                "Shots_F3_AP0_D1": _format_float(metric["tank_vector"][0]),
                "Shots_F4_AP-1_D1": _format_float(metric["tank_vector"][1]),
                "Shots_F7_AP-2_D2": _format_float(metric["tank_vector"][2]),
                "TTK_R_Swarm": _format_float(metric["r_ttks"][0]),
                "TTK_R_Troop": _format_float(metric["r_ttks"][1]),
                "TTK_R_Elite": _format_float(metric["r_ttks"][2]),
                "TTK_M_Swarm": _format_float(metric["m_ttks"][0]),
                "TTK_M_Troop": _format_float(metric["m_ttks"][1]),
                "TTK_M_Elite": _format_float(metric["m_ttks"][2]),
                "Perf_Target_Swarm": f"{target_perf_scores['Swarm']:.4f}",
                "Perf_Target_Troop": f"{target_perf_scores['Troop']:.4f}",
                "Perf_Target_Elite": f"{target_perf_scores['Elite']:.4f}",
                "Pref_Target_Swarm": f"{target_preferences['Swarm']:.4f}",
                "Pref_Target_Troop": f"{target_preferences['Troop']:.4f}",
                "Pref_Target_Elite": f"{target_preferences['Elite']:.4f}",
                "TankCheck": metric["tank_check"],
                "OffenseCheck": metric["offense_check"],
                "TargetCheck": target_check,
            }
            rows.append(row)
            csv_rows.append(
                {
                    **row,
                    "DisplayName": unit.display_name,
                    "Declared_TANKING_LEVEL": unit.declared_tanking_level if unit.declared_tanking_level is not None else "",
                    "Declared_OFFENSE_TYPE": unit.declared_offense_type if unit.declared_offense_type is not None else "",
                    "Declared_TARGET_TYPE": unit.declared_target_type if unit.declared_target_type is not None else "",
                    "TankDist_Swarm": _format_float(metric["tank_distances"]["Swarm"]),
                    "TankDist_Troop": _format_float(metric["tank_distances"]["Troop"]),
                    "TankDist_Elite": _format_float(metric["tank_distances"]["Elite"]),
                    "Shots_F3_AP0_D1": _format_float(metric["tank_vector"][0]),
                    "Shots_F4_AP-1_D1": _format_float(metric["tank_vector"][1]),
                    "Shots_F7_AP-2_D2": _format_float(metric["tank_vector"][2]),
                    "TTK_R_Swarm": _format_float(metric["r_ttks"][0]),
                    "TTK_R_Troop": _format_float(metric["r_ttks"][1]),
                    "TTK_R_Elite": _format_float(metric["r_ttks"][2]),
                    "TTK_M_Swarm": _format_float(metric["m_ttks"][0]),
                    "TTK_M_Troop": _format_float(metric["m_ttks"][1]),
                    "TTK_M_Elite": _format_float(metric["m_ttks"][2]),
                    "Perf_Target_Swarm": f"{target_perf_scores['Swarm']:.4f}",
                    "Perf_Target_Troop": f"{target_perf_scores['Troop']:.4f}",
                    "Perf_Target_Elite": f"{target_perf_scores['Elite']:.4f}",
                    "Pref_Target_Swarm": f"{target_preferences['Swarm']:.4f}",
                    "Pref_Target_Troop": f"{target_preferences['Troop']:.4f}",
                    "Pref_Target_Elite": f"{target_preferences['Elite']:.4f}",
                }
            )

    rows.sort(key=lambda x: (_tanking_sort_rank(x["Tanking"]), float(x["Blend_R"]), x["Roster"], x["UniteID"]))
    csv_rows.sort(key=lambda x: (_tanking_sort_rank(x["Tanking"]), float(x["Blend_R"]), x["Roster"], x["UniteID"]))

    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Roster",
        "UniteID",
        "DisplayName",
        "Tanking",
        "BlendCategory",
        "Blend_R",
        "Ratio_R_M",
        "TargetType",
        "TankCheck",
        "OffenseCheck",
        "TargetCheck",
        "Declared_TANKING_LEVEL",
        "Declared_OFFENSE_TYPE",
        "Declared_TARGET_TYPE",
        "TankDist_Swarm",
        "TankDist_Troop",
        "TankDist_Elite",
        "Shots_F3_AP0_D1",
        "Shots_F4_AP-1_D1",
        "Shots_F7_AP-2_D2",
        "TTK_R_Swarm",
        "TTK_R_Troop",
        "TTK_R_Elite",
        "TTK_M_Swarm",
        "TTK_M_Troop",
        "TTK_M_Elite",
        "Perf_Target_Swarm",
        "Perf_Target_Troop",
        "Perf_Target_Elite",
        "Pref_Target_Swarm",
        "Pref_Target_Troop",
        "Pref_Target_Elite",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"Rosters parsed: {', '.join(name for name, _ in roster_stats)}")
    print(f"Units parsed: {sum(count for _, count in roster_stats)}")
    print(f"Attacker BS assumption (tanking): {args.attacker_bs}+")
    print(f"Rapid Fire uptime: {args.uptime_rapid:.2f}")
    print(f"Heavy uptime: {args.uptime_heavy:.2f}")
    print(f"Ranged/Melee ratio threshold: {args.ratio_threshold:.2f}")
    print(f"Target specialization margin: {TARGET_MARGIN_FIXED:.2f} (fixed)")
    print("Sort order: Tanking -> Blend_R -> Roster -> UniteID")
    print(f"Table mode: {'verbous' if args.verbous else 'compact'}")
    print(f"CSV exported: {output}")
    print()
    _print_table(rows, verbous=args.verbous)


if __name__ == "__main__":
    main()
