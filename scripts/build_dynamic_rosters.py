#!/usr/bin/env python3
"""
Build dynamic roster files from unit sampling matrix.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROSTER_ROOT = PROJECT_ROOT / "frontend" / "src" / "roster"


@dataclass(frozen=True)
class UnitMeta:
    faction: str
    unit_type: str
    value: int


@dataclass(frozen=True)
class UnitPick:
    unit_key: str
    blend_group: str
    mobility_bucket: str
    weapon_profile: str


@dataclass(frozen=True)
class RosterBuildResult:
    composition: List[Tuple[str, int]]
    unit_picks: List[UnitPick]
    roster_value: int
    rejected_attempts: int
    total_attempts: int


def _require_key(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required key '{key}'")
    return mapping[key]


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


def _load_unit_metadata() -> Dict[str, UnitMeta]:
    if not ROSTER_ROOT.exists() or not ROSTER_ROOT.is_dir():
        raise FileNotFoundError(f"Invalid roster root: {ROSTER_ROOT}")

    units_by_key: Dict[str, UnitMeta] = {}
    unit_files = sorted(ROSTER_ROOT.glob("*/units/*.ts"))
    if not unit_files:
        raise FileNotFoundError(f"No unit files found under {ROSTER_ROOT}")

    for unit_file in unit_files:
        faction = unit_file.parent.parent.name
        contents = unit_file.read_text(encoding="utf-8")
        unit_type = _parse_static_string(contents, "NAME")
        value = _parse_static_number(contents, "VALUE")
        key = f"{faction}::{unit_type}"
        if key in units_by_key:
            raise ValueError(f"Duplicate unit key detected: {key}")
        units_by_key[key] = UnitMeta(faction=faction, unit_type=unit_type, value=value)
    return units_by_key


def _load_matrix(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Matrix file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _require_key(data, "by_tanking")
    _require_key(data, "cells")
    return data


def _weighted_pick(keys: Sequence[str], weights: Sequence[float], rng: random.Random) -> str:
    if len(keys) != len(weights):
        raise ValueError("weighted_pick received mismatched keys/weights lengths")
    if not keys:
        raise ValueError("weighted_pick received empty keys")
    if any(w < 0 for w in weights):
        raise ValueError(f"Negative weight encountered: {weights}")
    total = sum(weights)
    if total <= 0:
        raise ValueError(f"Invalid zero/negative total weight: {weights}")
    return rng.choices(list(keys), weights=list(weights), k=1)[0]


def _blend_inverse_sqrt_weights(cells_for_tanking: List[Dict[str, Any]]) -> Dict[str, float]:
    blend_counts: Counter[str] = Counter()
    for cell in cells_for_tanking:
        blend = _require_key(cell, "blend_group")
        count = int(_require_key(cell, "count"))
        if count <= 0:
            continue
        blend_counts[blend] += count
    if not blend_counts:
        raise ValueError("No positive blend counts available for selected tanking")

    raw_weights: Dict[str, float] = {}
    for blend, count in blend_counts.items():
        raw_weights[blend] = 1.0 / math.sqrt(float(count))

    total = sum(raw_weights.values())
    if total <= 0:
        raise ValueError(f"Invalid blend raw weights: {raw_weights}")
    return {k: v / total for k, v in raw_weights.items()}


def _sample_one_unit_key(
    target_tanking: str,
    cells_for_tanking: List[Dict[str, Any]],
    mobility_weights: Dict[str, float],
    weapon_weights: Dict[str, float],
    blend_weights: Dict[str, float],
    rng: random.Random,
    max_combo_attempts: int,
) -> UnitPick:
    for _ in range(max_combo_attempts):
        blend = _weighted_pick(list(blend_weights.keys()), list(blend_weights.values()), rng)
        mobility = _weighted_pick(list(mobility_weights.keys()), list(mobility_weights.values()), rng)
        weapon = _weighted_pick(list(weapon_weights.keys()), list(weapon_weights.values()), rng)

        matching = [
            cell
            for cell in cells_for_tanking
            if _require_key(cell, "tanking") == target_tanking
            and _require_key(cell, "blend_group") == blend
            and _require_key(cell, "mobility_bucket") == mobility
            and _require_key(cell, "weapon_profile") == weapon
            and int(_require_key(cell, "count")) > 0
        ]
        if not matching:
            continue

        # Cell-level pick weighted by cell count
        cell_weights = [int(_require_key(cell, "count")) for cell in matching]
        chosen_cell = rng.choices(matching, weights=cell_weights, k=1)[0]
        units = _require_key(chosen_cell, "units")
        if not isinstance(units, list) or len(units) == 0:
            raise ValueError(f"Sampled cell has empty units list: {chosen_cell}")
        chosen_unit = rng.choice(units)
        if not isinstance(chosen_unit, str):
            raise ValueError(f"Invalid unit key type in cell: {chosen_unit!r}")
        return UnitPick(
            unit_key=chosen_unit,
            blend_group=blend,
            mobility_bucket=mobility,
            weapon_profile=weapon,
        )

    raise ValueError(
        f"Failed to sample valid matrix combination after {max_combo_attempts} attempts "
        f"for tanking='{target_tanking}'"
    )


def _build_one_roster(
    target_tanking: str,
    matrix: Dict[str, Any],
    units_meta: Dict[str, UnitMeta],
    target_points: int,
    points_tolerance: int,
    units_per_roster: int,
    max_attempts: int,
    rng: random.Random,
) -> RosterBuildResult:
    by_tanking = _require_key(matrix, "by_tanking")
    if target_tanking not in by_tanking:
        raise KeyError(f"Tanking '{target_tanking}' not found in matrix.by_tanking")

    tank_section = by_tanking[target_tanking]
    weights = _require_key(tank_section, "weights")
    mobility_weights = _require_key(weights, "mobility_weights")
    weapon_weights = _require_key(weights, "weapon_profile_weights")
    if not mobility_weights:
        raise ValueError(f"Empty mobility_weights for tanking '{target_tanking}'")
    if not weapon_weights:
        raise ValueError(f"Empty weapon_profile_weights for tanking '{target_tanking}'")

    cells = _require_key(matrix, "cells")
    if not isinstance(cells, list):
        raise TypeError("matrix.cells must be a list")
    cells_for_tanking = [cell for cell in cells if _require_key(cell, "tanking") == target_tanking]
    if not cells_for_tanking:
        raise ValueError(f"No cells for tanking '{target_tanking}'")
    blend_weights = _blend_inverse_sqrt_weights(cells_for_tanking)

    min_points = target_points - points_tolerance
    max_points = target_points + points_tolerance
    if min_points < 0:
        raise ValueError(f"Invalid points window: [{min_points}, {max_points}]")

    rejected_attempts = 0
    for _attempt in range(1, max_attempts + 1):
        picked: List[UnitPick] = []
        total_points = 0
        local_attempts = 0
        while len(picked) < units_per_roster:
            local_attempts += 1
            if local_attempts > (max_attempts * units_per_roster):
                break
            unit_pick = _sample_one_unit_key(
                target_tanking=target_tanking,
                cells_for_tanking=cells_for_tanking,
                mobility_weights=mobility_weights,
                weapon_weights=weapon_weights,
                blend_weights=blend_weights,
                rng=rng,
                max_combo_attempts=max_attempts,
            )
            unit_key = unit_pick.unit_key
            if unit_key not in units_meta:
                raise KeyError(f"Unit from matrix not found in metadata: '{unit_key}'")
            candidate_value = units_meta[unit_key].value
            if candidate_value <= 0:
                raise ValueError(f"Non-positive VALUE for unit '{unit_key}': {candidate_value}")
            if total_points + candidate_value > max_points:
                continue
            picked.append(unit_pick)
            total_points += candidate_value

        if len(picked) != units_per_roster:
            rejected_attempts += 1
            continue
        if total_points < min_points or total_points > max_points:
            rejected_attempts += 1
            continue

        by_unit = Counter(units_meta[item.unit_key].unit_type for item in picked)
        composition = sorted(by_unit.items(), key=lambda item: item[0])
        return RosterBuildResult(
            composition=composition,
            unit_picks=picked,
            roster_value=total_points,
            rejected_attempts=rejected_attempts,
            total_attempts=rejected_attempts + 1,
        )

    raise RuntimeError(
        f"Failed to build roster after {max_attempts} attempts "
        f"for tanking='{target_tanking}', units_per_roster={units_per_roster}, "
        f"points={target_points}±{points_tolerance}"
    )


def _mean(values: List[float]) -> float:
    if not values:
        raise ValueError("Cannot compute mean of empty list")
    return float(sum(values) / len(values))


def _std(values: List[float]) -> float:
    if not values:
        raise ValueError("Cannot compute std of empty list")
    m = _mean(values)
    return float(math.sqrt(sum((v - m) ** 2 for v in values) / len(values)))


def _quantile(values: List[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot compute quantile of empty list")
    if q < 0.0 or q > 1.0:
        raise ValueError(f"Quantile must be in [0,1], got {q}")
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = q * (len(sorted_values) - 1)
    low = int(math.floor(idx))
    high = int(math.ceil(idx))
    if low == high:
        return float(sorted_values[low])
    frac = idx - low
    return float(sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac)


def _distribution_drift(
    observed_counts: Counter[str],
    target_weights: Dict[str, float],
) -> Dict[str, float]:
    observed_total = sum(observed_counts.values())
    if observed_total <= 0:
        raise ValueError("Observed distribution is empty")
    if not target_weights:
        raise ValueError("Target weight distribution is empty")
    normalized_target_total = sum(target_weights.values())
    if normalized_target_total <= 0:
        raise ValueError(f"Invalid target distribution: {target_weights}")

    keys = sorted(set(observed_counts.keys()) | set(target_weights.keys()))
    l1 = 0.0
    observed_dist: Dict[str, float] = {}
    target_dist: Dict[str, float] = {}
    for key in keys:
        observed_p = observed_counts.get(key, 0) / observed_total
        target_p = target_weights.get(key, 0.0) / normalized_target_total
        observed_dist[key] = observed_p
        target_dist[key] = target_p
        l1 += abs(observed_p - target_p)
    return {"l1": l1, "observed": observed_dist, "target": target_dist}


def _build_unit_type_value_index(units_meta: Dict[str, UnitMeta]) -> Dict[str, int]:
    by_unit_type: Dict[str, int] = {}
    for meta in units_meta.values():
        if meta.unit_type in by_unit_type and by_unit_type[meta.unit_type] != meta.value:
            raise ValueError(
                f"Conflicting VALUE for unit_type '{meta.unit_type}': "
                f"{by_unit_type[meta.unit_type]} vs {meta.value}"
            )
        by_unit_type[meta.unit_type] = meta.value
    return by_unit_type


def _load_roster_value(
    roster_path: Path,
    unit_value_by_type: Dict[str, int],
) -> Tuple[str, int]:
    payload = json.loads(roster_path.read_text(encoding="utf-8"))
    roster_id = _require_key(payload, "roster_id")
    composition = _require_key(payload, "composition")
    if not isinstance(composition, list):
        raise TypeError(f"Invalid composition in {roster_path}")
    total = 0
    for entry in composition:
        unit_type = _require_key(entry, "unit_type")
        count = int(_require_key(entry, "count"))
        if unit_type not in unit_value_by_type:
            raise KeyError(f"Unknown unit_type '{unit_type}' in roster '{roster_path}'")
        total += unit_value_by_type[unit_type] * count
    if not isinstance(roster_id, str):
        raise TypeError(f"Invalid roster_id in {roster_path}: {roster_id!r}")
    return roster_id, total


def _generate_matchups(
    generated_roster_values: List[Tuple[str, int]],
    opponent_roster_values: List[Tuple[str, int]],
    num_matchups: int,
    strict_tol: int,
    medium_tol: int,
    wide_tol: int,
    max_attempts: int,
    rng: random.Random,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    if strict_tol < 0 or medium_tol < strict_tol or wide_tol < medium_tol:
        raise ValueError(
            f"Invalid matchup tolerances: strict={strict_tol}, medium={medium_tol}, wide={wide_tol}"
        )
    if num_matchups <= 0:
        raise ValueError(f"num_matchups must be > 0 (got {num_matchups})")
    if not generated_roster_values:
        raise ValueError("No generated rosters available for matchup generation")
    if not opponent_roster_values:
        raise ValueError("No opponent rosters available for matchup generation")

    strict_count = int(round(num_matchups * 0.70))
    medium_count = int(round(num_matchups * 0.20))
    wide_count = num_matchups - strict_count - medium_count
    bucket_plan: List[str] = (["strict"] * strict_count) + (["medium"] * medium_count) + (["wide"] * wide_count)
    rng.shuffle(bucket_plan)

    matchups: List[Dict[str, Any]] = []
    rejections = 0
    total_attempts = 0

    for bucket in bucket_plan:
        if bucket == "strict":
            min_gap = 0
            max_gap = strict_tol
        elif bucket == "medium":
            min_gap = strict_tol + 1
            max_gap = medium_tol
        elif bucket == "wide":
            min_gap = medium_tol + 1
            max_gap = wide_tol
        else:
            raise ValueError(f"Unknown bucket: {bucket}")

        built = False
        for _ in range(max_attempts):
            total_attempts += 1
            p1_id, p1_val = rng.choice(generated_roster_values)
            p2_id, p2_val = rng.choice(opponent_roster_values)
            gap_abs = abs(p1_val - p2_val)
            if gap_abs < min_gap or gap_abs > max_gap:
                rejections += 1
                continue
            matchups.append(
                {
                    "bucket": bucket,
                    "p1_roster_id": p1_id,
                    "p2_roster_id": p2_id,
                    "p1_value": p1_val,
                    "p2_value": p2_val,
                    "value_gap": p1_val - p2_val,
                }
            )
            built = True
            break
        if not built:
            raise RuntimeError(
                f"Failed to build matchup in bucket '{bucket}' after {max_attempts} attempts"
            )

    if total_attempts <= 0:
        raise RuntimeError("Internal error: total matchup attempts is zero")

    abs_gaps = [abs(int(m["value_gap"])) for m in matchups]
    bucket_counts = Counter(str(m["bucket"]) for m in matchups)
    kpis = {
        "matchup_value_gap_mean": _mean([float(v) for v in abs_gaps]),
        "matchup_value_gap_p95": _quantile([float(v) for v in abs_gaps], 0.95),
        "pct_matchups_in_strict_bucket": bucket_counts.get("strict", 0) / len(matchups),
        "pct_matchups_in_medium_bucket": bucket_counts.get("medium", 0) / len(matchups),
        "pct_matchups_in_wide_bucket": bucket_counts.get("wide", 0) / len(matchups),
        "rejection_rate_matchup_gap": rejections / total_attempts,
    }
    return matchups, kpis


def _write_roster_file(output_dir: Path, roster_id: str, composition: List[Tuple[str, int]]) -> Path:
    payload = {
        "roster_id": roster_id,
        "composition": [{"unit_type": unit_type, "count": count} for unit_type, count in composition],
    }
    output_path = output_dir / f"{roster_id}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dynamic rosters from sampling matrix")
    parser.add_argument("--matrix", default="reports/unit_sampling_matrix.json", help="Sampling matrix JSON path")
    parser.add_argument(
        "--target-tanking",
        required=True,
        choices=["Swarm", "Troop", "Elite"],
        help="Target tanking category for generated rosters",
    )
    parser.add_argument("--points-scale", type=int, default=150, help="Target roster points budget")
    parser.add_argument("--points-tolerance", type=int, default=2, help="Allowed +/- tolerance around points-scale")
    parser.add_argument("--num-rosters", type=int, required=True, help="Number of rosters to generate")
    parser.add_argument("--units-per-roster", type=int, required=True, help="Number of unit entries per roster draw")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for generated roster files (overrides --split default path)",
    )
    parser.add_argument(
        "--split",
        choices=["training", "holdout"],
        default="training",
        help="Default split folder when --output-dir is not set",
    )
    parser.add_argument(
        "--roster-prefix",
        default="p2_dynamic",
        help="Roster id filename prefix (suffix -NN will be appended)",
    )
    parser.add_argument(
        "--max-build-attempts",
        type=int,
        default=200,
        help="Maximum attempts per roster before explicit failure",
    )
    parser.add_argument(
        "--opponent-roster-dir",
        default=None,
        help="Optional directory containing opponent roster JSON files for matchup KPI generation",
    )
    parser.add_argument(
        "--num-matchups",
        type=int,
        default=None,
        help="Number of matchups to generate when --opponent-roster-dir is set (default: num-rosters)",
    )
    parser.add_argument("--matchup-tol-strict", type=int, default=3, help="Strict matchup absolute gap tolerance")
    parser.add_argument("--matchup-tol-medium", type=int, default=7, help="Medium matchup absolute gap tolerance")
    parser.add_argument("--matchup-tol-wide", type=int, default=12, help="Wide matchup absolute gap tolerance")
    parser.add_argument(
        "--max-matchup-build-attempts",
        type=int,
        default=300,
        help="Maximum attempts for each matchup bucket sample",
    )
    args = parser.parse_args()

    if args.points_scale <= 0:
        raise ValueError(f"--points-scale must be > 0 (got {args.points_scale})")
    if args.points_tolerance < 0:
        raise ValueError(f"--points-tolerance must be >= 0 (got {args.points_tolerance})")
    if args.num_rosters <= 0:
        raise ValueError(f"--num-rosters must be > 0 (got {args.num_rosters})")
    if args.units_per_roster <= 0:
        raise ValueError(f"--units-per-roster must be > 0 (got {args.units_per_roster})")
    if args.max_build_attempts <= 0:
        raise ValueError(f"--max-build-attempts must be > 0 (got {args.max_build_attempts})")
    if args.max_matchup_build_attempts <= 0:
        raise ValueError(
            f"--max-matchup-build-attempts must be > 0 (got {args.max_matchup_build_attempts})"
        )
    if args.matchup_tol_strict < 0:
        raise ValueError(f"--matchup-tol-strict must be >= 0 (got {args.matchup_tol_strict})")
    if args.matchup_tol_medium < args.matchup_tol_strict:
        raise ValueError(
            "--matchup-tol-medium must be >= --matchup-tol-strict "
            f"(got {args.matchup_tol_medium} < {args.matchup_tol_strict})"
        )
    if args.matchup_tol_wide < args.matchup_tol_medium:
        raise ValueError(
            "--matchup-tol-wide must be >= --matchup-tol-medium "
            f"(got {args.matchup_tol_wide} < {args.matchup_tol_medium})"
        )

    matrix = _load_matrix(Path(args.matrix))
    units_meta = _load_unit_metadata()
    unit_value_by_type = _build_unit_type_value_index(units_meta)
    if args.output_dir is None:
        output_dir = Path(f"config/agents/_p2_rosters/{args.points_scale}pts/{args.split}")
    else:
        output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    by_tanking = _require_key(matrix, "by_tanking")
    tank_section = _require_key(by_tanking, args.target_tanking)
    tank_weights = _require_key(tank_section, "weights")
    mobility_target = _require_key(tank_weights, "mobility_weights")
    weapon_target = _require_key(tank_weights, "weapon_profile_weights")
    cells_for_tanking = [
        cell for cell in _require_key(matrix, "cells") if _require_key(cell, "tanking") == args.target_tanking
    ]
    blend_target = _blend_inverse_sqrt_weights(cells_for_tanking)

    written_paths: List[Path] = []
    roster_values: List[int] = []
    all_unit_picks: List[UnitPick] = []
    total_rejected_roster_attempts = 0
    total_roster_attempts = 0
    generated_roster_values: List[Tuple[str, int]] = []
    for idx in range(1, args.num_rosters + 1):
        build_result = _build_one_roster(
            target_tanking=args.target_tanking,
            matrix=matrix,
            units_meta=units_meta,
            target_points=args.points_scale,
            points_tolerance=args.points_tolerance,
            units_per_roster=args.units_per_roster,
            max_attempts=args.max_build_attempts,
            rng=rng,
        )
        roster_id = f"{args.roster_prefix}_{args.target_tanking.lower()}_{idx:02d}"
        written_paths.append(
            _write_roster_file(output_dir=output_dir, roster_id=roster_id, composition=build_result.composition)
        )
        roster_values.append(build_result.roster_value)
        total_rejected_roster_attempts += build_result.rejected_attempts
        total_roster_attempts += build_result.total_attempts
        all_unit_picks.extend(build_result.unit_picks)
        generated_roster_values.append((roster_id, build_result.roster_value))

    if not all_unit_picks:
        raise RuntimeError("No unit picks collected after generation")

    picked_units_counter = Counter(pick.unit_key for pick in all_unit_picks)
    picked_blend_counter = Counter(pick.blend_group for pick in all_unit_picks)
    picked_mobility_counter = Counter(pick.mobility_bucket for pick in all_unit_picks)
    picked_weapon_counter = Counter(pick.weapon_profile for pick in all_unit_picks)
    roster_budget_rejection_rate = (
        total_rejected_roster_attempts / total_roster_attempts if total_roster_attempts > 0 else 0.0
    )

    kpis: Dict[str, Any] = {
        "roster_value_mean": _mean([float(v) for v in roster_values]),
        "roster_value_std": _std([float(v) for v in roster_values]),
        "rejection_rate_roster_budget": roster_budget_rejection_rate,
        "unit_pick_frequency": dict(sorted(picked_units_counter.items(), key=lambda item: (-item[1], item[0]))),
        "distribution_drift_blend": _distribution_drift(picked_blend_counter, blend_target),
        "distribution_drift_mobility": _distribution_drift(picked_mobility_counter, mobility_target),
        "distribution_drift_weapon_profile": _distribution_drift(picked_weapon_counter, weapon_target),
    }

    matchup_path: Optional[Path] = None
    if args.opponent_roster_dir is not None:
        opponent_dir = Path(args.opponent_roster_dir)
        if not opponent_dir.exists() or not opponent_dir.is_dir():
            raise FileNotFoundError(f"Invalid --opponent-roster-dir: {opponent_dir}")
        opponent_paths = sorted(opponent_dir.glob("*.json"))
        if not opponent_paths:
            raise FileNotFoundError(f"No roster JSON files found in --opponent-roster-dir: {opponent_dir}")
        opponent_values = [_load_roster_value(path, unit_value_by_type) for path in opponent_paths]
        num_matchups = args.num_matchups if args.num_matchups is not None else args.num_rosters
        matchups, matchup_kpis = _generate_matchups(
            generated_roster_values=generated_roster_values,
            opponent_roster_values=opponent_values,
            num_matchups=num_matchups,
            strict_tol=args.matchup_tol_strict,
            medium_tol=args.matchup_tol_medium,
            wide_tol=args.matchup_tol_wide,
            max_attempts=args.max_matchup_build_attempts,
            rng=rng,
        )
        matchup_payload = {
            "target_tanking": args.target_tanking,
            "num_matchups": len(matchups),
            "matchups": matchups,
        }
        matchup_path = output_dir / f"{args.roster_prefix}_{args.target_tanking.lower()}_matchups.json"
        matchup_path.write_text(json.dumps(matchup_payload, indent=2), encoding="utf-8")
        kpis.update(matchup_kpis)

    kpi_path = output_dir / f"{args.roster_prefix}_{args.target_tanking.lower()}_kpis.json"
    kpi_path.write_text(json.dumps(kpis, indent=2), encoding="utf-8")

    print(f"Generated rosters: {len(written_paths)}")
    print(f"Target tanking: {args.target_tanking}")
    print(f"Points budget: {args.points_scale} +/- {args.points_tolerance}")
    print(f"Units per roster: {args.units_per_roster}")
    print(f"Output dir: {output_dir}")
    print(f"KPI file: {kpi_path}")
    if matchup_path is not None:
        print(f"Matchup file: {matchup_path}")
    for path in written_paths[:10]:
        print(f"- {path}")
    if len(written_paths) > 10:
        print(f"... {len(written_paths) - 10} more files")


if __name__ == "__main__":
    main()

