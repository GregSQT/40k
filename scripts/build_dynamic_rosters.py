#!/usr/bin/env python3
"""
Build dynamic roster files from unit sampling matrix (v21).

Consolidated version:
- strict matrix/unit validation and unit_type ambiguity guard,
- direct sampling on feasible cells only,
- budget-aware feasibility checks while building rosters,
- anti-repetition controls (global window + per-roster copy cap),
- matchup generation with configurable strict/medium/wide ratios,
- optional sign-balancing without swapping P1/P2 sides.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
class WeightedUnitChoice:
    unit_pick: UnitPick
    base_weight: float


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


def _load_matrix(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Matrix file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _require_key(data, "by_tanking")
    _require_key(data, "cells")
    if "unit_values" not in data:
        raise ValueError(
            "Matrix JSON is missing required key 'unit_values'. "
            "Rebuild it with: python scripts/unit_classifier.py --roster all"
        )
    return data


def _load_unit_metadata_from_matrix(matrix: Dict[str, Any]) -> Dict[str, UnitMeta]:
    unit_values = _require_key(matrix, "unit_values")
    if not isinstance(unit_values, dict):
        raise TypeError("matrix.unit_values must be a dictionary")
    if not unit_values:
        raise ValueError("matrix.unit_values is empty")

    units_by_key: Dict[str, UnitMeta] = {}
    for unit_key, raw_value in unit_values.items():
        if not isinstance(unit_key, str) or "::" not in unit_key:
            raise ValueError(
                f"Invalid unit key in matrix.unit_values: {unit_key!r}. "
                "Expected format 'roster::unit_type'."
            )
        faction, unit_type = unit_key.split("::", 1)
        if not faction or not unit_type:
            raise ValueError(f"Invalid unit key in matrix.unit_values: {unit_key!r}")
        value = int(raw_value)
        if value <= 0:
            raise ValueError(f"Non-positive VALUE for '{unit_key}': {value}")
        units_by_key[unit_key] = UnitMeta(faction=faction, unit_type=unit_type, value=value)
    return units_by_key


def _weighted_pick(keys: Sequence[Any], weights: Sequence[float], rng: random.Random) -> Any:
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


def _distribution_drift(observed_counts: Counter[str], target_weights: Dict[str, float]) -> Dict[str, Any]:
    observed_total = sum(observed_counts.values())
    if observed_total <= 0:
        raise ValueError("Observed distribution is empty")
    if not target_weights:
        raise ValueError("Target weight distribution is empty")
    target_total = sum(target_weights.values())
    if target_total <= 0:
        raise ValueError(f"Invalid target distribution: {target_weights}")

    keys = sorted(set(observed_counts.keys()) | set(target_weights.keys()))
    l1 = 0.0
    observed: Dict[str, float] = {}
    target: Dict[str, float] = {}
    for key in keys:
        observed_p = observed_counts.get(key, 0) / observed_total
        target_p = target_weights.get(key, 0.0) / target_total
        observed[key] = observed_p
        target[key] = target_p
        l1 += abs(observed_p - target_p)
    return {"l1": l1, "observed": observed, "target": target}


def _parse_csv_values(raw: str, arg_name: str) -> List[str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{arg_name} must be a non-empty comma-separated string")
    values = [token.strip() for token in raw.split(",")]
    cleaned = [token for token in values if token]
    if not cleaned:
        raise ValueError(f"{arg_name} must contain at least one value")
    return cleaned


def _parse_csv_float_weights(raw: str, arg_name: str) -> List[float]:
    values = _parse_csv_values(raw, arg_name)
    parsed: List[float] = []
    for token in values:
        weight = float(token)
        if weight < 0.0:
            raise ValueError(f"{arg_name} cannot contain negative weight: {token}")
        parsed.append(weight)
    if sum(parsed) <= 0.0:
        raise ValueError(f"{arg_name} must contain at least one positive weight")
    return parsed


def _parse_csv_positive_ints(raw: str, arg_name: str) -> List[int]:
    values = _parse_csv_values(raw, arg_name)
    parsed: List[int] = []
    for token in values:
        parsed_value = int(token)
        if parsed_value <= 0:
            raise ValueError(f"{arg_name} values must be > 0 (got {parsed_value})")
        parsed.append(parsed_value)
    return parsed


def _normalize_weight_map(keys: List[str], raw_weights: List[float], label: str) -> Dict[str, float]:
    if len(keys) != len(raw_weights):
        raise ValueError(
            f"{label}: values/weights length mismatch ({len(keys)} != {len(raw_weights)})"
        )
    total_weight = sum(raw_weights)
    if total_weight <= 0.0:
        raise ValueError(f"{label}: total weight must be > 0")
    normalized: Dict[str, float] = {}
    for idx, key in enumerate(keys):
        if key in normalized:
            raise ValueError(f"{label}: duplicate value '{key}' is not allowed")
        normalized[key] = float(raw_weights[idx]) / float(total_weight)
    return normalized


def _normalize_weight_map_int(keys: List[int], raw_weights: List[float], label: str) -> Dict[int, float]:
    if len(keys) != len(raw_weights):
        raise ValueError(
            f"{label}: values/weights length mismatch ({len(keys)} != {len(raw_weights)})"
        )
    total_weight = sum(raw_weights)
    if total_weight <= 0.0:
        raise ValueError(f"{label}: total weight must be > 0")
    normalized: Dict[int, float] = {}
    for idx, key in enumerate(keys):
        if key in normalized:
            raise ValueError(f"{label}: duplicate value '{key}' is not allowed")
        normalized[key] = float(raw_weights[idx]) / float(total_weight)
    return normalized


def _compose_weighted_target(targets: List[Tuple[Dict[str, float], float]], label: str) -> Dict[str, float]:
    if not targets:
        raise ValueError(f"{label}: no target distributions provided")
    combined_raw: Dict[str, float] = {}
    total_factor = 0.0
    for target_map, factor in targets:
        if factor < 0.0:
            raise ValueError(f"{label}: negative factor {factor}")
        if factor == 0.0:
            continue
        total_factor += factor
        for key, value in target_map.items():
            if value < 0.0:
                raise ValueError(f"{label}: negative target value for key '{key}'")
            combined_raw[key] = combined_raw.get(key, 0.0) + (float(value) * float(factor))
    if total_factor <= 0.0:
        raise ValueError(f"{label}: total factor must be > 0")
    combined_sum = sum(combined_raw.values())
    if combined_sum <= 0.0:
        raise ValueError(f"{label}: combined target distribution is empty")
    return {key: value / combined_sum for key, value in combined_raw.items()}


def _blend_inverse_sqrt_weights(cells_for_tanking: List[Dict[str, Any]]) -> Dict[str, float]:
    blend_counts: Counter[str] = Counter()
    for cell in cells_for_tanking:
        blend = str(_require_key(cell, "blend_group"))
        count = int(_require_key(cell, "count"))
        if count > 0:
            blend_counts[blend] += count
    if not blend_counts:
        raise ValueError("No positive blend counts available for selected tanking")

    raw = {blend: 1.0 / math.sqrt(float(count)) for blend, count in blend_counts.items()}
    total = sum(raw.values())
    if total <= 0:
        raise ValueError(f"Invalid blend raw weights: {raw}")
    return {k: v / total for k, v in raw.items()}


def _extract_matrix_unit_keys(matrix: Dict[str, Any]) -> List[str]:
    cells = _require_key(matrix, "cells")
    if not isinstance(cells, list):
        raise TypeError("matrix.cells must be a list")
    keys: List[str] = []
    for cell in cells:
        units = _require_key(cell, "units")
        if not isinstance(units, list):
            raise TypeError(f"Cell units must be list, got {type(units).__name__}")
        for unit_key in units:
            if not isinstance(unit_key, str):
                raise TypeError(f"Invalid unit key type in matrix: {unit_key!r}")
            keys.append(unit_key)
    return sorted(set(keys))


def _validate_matrix_units_exist(matrix_unit_keys: List[str], units_meta: Dict[str, UnitMeta]) -> None:
    missing = [key for key in matrix_unit_keys if key not in units_meta]
    if missing:
        raise KeyError(
            "Matrix references units not found in metadata. "
            f"Missing count={len(missing)}, examples={missing[:10]}"
        )


def _build_unit_type_value_index_strict(
    matrix_unit_keys: List[str],
    units_meta: Dict[str, UnitMeta],
) -> Dict[str, int]:
    by_type_to_keys: Dict[str, List[str]] = {}
    for unit_key in matrix_unit_keys:
        meta = units_meta[unit_key]
        by_type_to_keys.setdefault(meta.unit_type, []).append(unit_key)

    collisions = {unit_type: sorted(keys) for unit_type, keys in by_type_to_keys.items() if len(keys) > 1}
    if collisions:
        sample = list(collisions.items())[:10]
        raise ValueError(
            "Ambiguous unit_type across factions in matrix-selected units; "
            "cannot write unambiguous roster composition with unit_type only. "
            f"Examples: {sample}"
        )

    return {units_meta[key].unit_type: units_meta[key].value for key in matrix_unit_keys}


def _build_feasible_weighted_unit_choices(
    target_tanking: str,
    matrix: Dict[str, Any],
    units_meta: Dict[str, UnitMeta],
) -> Tuple[List[WeightedUnitChoice], Dict[str, float], Dict[str, float], Dict[str, float]]:
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

    weighted_choices: List[WeightedUnitChoice] = []
    for cell in cells_for_tanking:
        count = int(_require_key(cell, "count"))
        if count <= 0:
            continue
        blend = str(_require_key(cell, "blend_group"))
        mobility = str(_require_key(cell, "mobility_bucket"))
        weapon = str(_require_key(cell, "weapon_profile"))

        if blend not in blend_weights or mobility not in mobility_weights or weapon not in weapon_weights:
            continue

        cell_weight = float(count) * float(blend_weights[blend]) * float(mobility_weights[mobility]) * float(
            weapon_weights[weapon]
        )
        if cell_weight <= 0.0:
            continue

        units = _require_key(cell, "units")
        if not isinstance(units, list) or len(units) == 0:
            raise ValueError(f"Cell has invalid empty units list: {cell}")
        unit_weight = cell_weight / float(len(units))
        for unit_key in units:
            if not isinstance(unit_key, str):
                raise TypeError(f"Invalid unit key type in cell: {unit_key!r}")
            if unit_key not in units_meta:
                raise KeyError(f"Unit from matrix not found in metadata: '{unit_key}'")
            if units_meta[unit_key].value <= 0:
                raise ValueError(f"Non-positive VALUE for unit '{unit_key}': {units_meta[unit_key].value}")
            weighted_choices.append(
                WeightedUnitChoice(
                    unit_pick=UnitPick(
                        unit_key=unit_key,
                        blend_group=blend,
                        mobility_bucket=mobility,
                        weapon_profile=weapon,
                    ),
                    base_weight=unit_weight,
                )
            )

    if not weighted_choices:
        raise ValueError(f"No feasible weighted unit choices for tanking '{target_tanking}'")
    return weighted_choices, blend_weights, dict(mobility_weights), dict(weapon_weights)


def _is_budget_feasible(
    current_total: int,
    candidate_value: int,
    slots_left_after_pick: int,
    min_points: int,
    max_points: int,
    min_unit_value: int,
    max_unit_value: int,
) -> bool:
    new_total = current_total + candidate_value
    if new_total > max_points:
        return False
    min_possible = new_total + slots_left_after_pick * min_unit_value
    max_possible = new_total + slots_left_after_pick * max_unit_value
    return min_possible <= max_points and max_possible >= min_points


def _build_one_roster(
    weighted_choices: List[WeightedUnitChoice],
    units_meta: Dict[str, UnitMeta],
    target_points: int,
    points_tolerance: int,
    units_per_roster: int,
    max_attempts: int,
    max_copies_per_unit: int,
    anti_repeat_window: int,
    anti_repeat_penalty: float,
    recent_global_picks: Deque[str],
    rng: random.Random,
) -> RosterBuildResult:
    min_points = target_points - points_tolerance
    max_points = target_points + points_tolerance
    if min_points < 0:
        raise ValueError(f"Invalid points window: [{min_points}, {max_points}]")

    values = [units_meta[c.unit_pick.unit_key].value for c in weighted_choices]
    min_unit_value = min(values)
    max_unit_value = max(values)

    rejected_attempts = 0
    for _ in range(max_attempts):
        picked: List[UnitPick] = []
        picked_counter: Counter[str] = Counter()
        total_points = 0

        for slot_idx in range(units_per_roster):
            slots_left_after = units_per_roster - slot_idx - 1
            feasible_picks: List[UnitPick] = []
            feasible_weights: List[float] = []

            for choice in weighted_choices:
                pick = choice.unit_pick
                unit_key = pick.unit_key
                unit_value = units_meta[unit_key].value

                if picked_counter[unit_key] >= max_copies_per_unit:
                    continue
                if not _is_budget_feasible(
                    current_total=total_points,
                    candidate_value=unit_value,
                    slots_left_after_pick=slots_left_after,
                    min_points=min_points,
                    max_points=max_points,
                    min_unit_value=min_unit_value,
                    max_unit_value=max_unit_value,
                ):
                    continue

                weight = choice.base_weight
                if anti_repeat_window > 0 and unit_key in recent_global_picks:
                    weight *= anti_repeat_penalty
                if picked_counter[unit_key] > 0:
                    weight /= math.sqrt(float(picked_counter[unit_key] + 1))
                if weight <= 0:
                    continue

                feasible_picks.append(pick)
                feasible_weights.append(weight)

            if not feasible_picks:
                break

            selected_pick = _weighted_pick(feasible_picks, feasible_weights, rng)
            picked.append(selected_pick)
            picked_counter[selected_pick.unit_key] += 1
            total_points += units_meta[selected_pick.unit_key].value

        if len(picked) != units_per_roster:
            rejected_attempts += 1
            continue
        if total_points < min_points or total_points > max_points:
            rejected_attempts += 1
            continue

        composition_counter = Counter(units_meta[p.unit_key].unit_type for p in picked)
        composition = sorted(composition_counter.items(), key=lambda item: item[0])
        if anti_repeat_window > 0:
            for p in picked:
                recent_global_picks.append(p.unit_key)
        return RosterBuildResult(
            composition=composition,
            unit_picks=picked,
            roster_value=total_points,
            rejected_attempts=rejected_attempts,
            total_attempts=rejected_attempts + 1,
        )

    raise RuntimeError(
        f"Failed to build roster after {max_attempts} attempts "
        f"(points={target_points}±{points_tolerance}, units_per_roster={units_per_roster}, "
        f"max_copies_per_unit={max_copies_per_unit})"
    )


def _write_roster_file(output_dir: Path, roster_id: str, composition: List[Tuple[str, int]]) -> Path:
    payload = {
        "roster_id": roster_id,
        "composition": [{"unit_type": unit_type, "count": count} for unit_type, count in composition],
    }
    output_path = output_dir / f"{roster_id}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def _load_roster_value(roster_path: Path, unit_value_by_type: Dict[str, int]) -> Tuple[str, int]:
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


def _validate_bucket_feasibility(
    strict_tol: int,
    medium_tol: int,
    wide_tol: int,
    strict_ratio: float,
    medium_ratio: float,
    wide_ratio: float,
) -> None:
    if strict_tol < 0:
        raise ValueError(f"strict_tol must be >= 0 (got {strict_tol})")
    if medium_tol < strict_tol:
        raise ValueError(f"medium_tol must be >= strict_tol (got {medium_tol} < {strict_tol})")
    if wide_tol < medium_tol:
        raise ValueError(f"wide_tol must be >= medium_tol (got {wide_tol} < {medium_tol})")

    if strict_ratio < 0.0 or medium_ratio < 0.0 or wide_ratio < 0.0:
        raise ValueError("All matchup ratios must be >= 0")
    if strict_ratio + medium_ratio + wide_ratio <= 0.0:
        raise ValueError("At least one matchup ratio must be > 0")

    if medium_ratio > 0.0 and medium_tol <= strict_tol:
        raise ValueError(
            "Medium bucket requested but interval is empty. "
            f"Require medium_tol > strict_tol (got {medium_tol} <= {strict_tol})"
        )
    if wide_ratio > 0.0 and wide_tol <= medium_tol:
        raise ValueError(
            "Wide bucket requested but interval is empty. "
            f"Require wide_tol > medium_tol (got {wide_tol} <= {medium_tol})"
        )


def _build_bucket_plan(
    num_matchups: int,
    strict_ratio: float,
    medium_ratio: float,
    wide_ratio: float,
    rng: random.Random,
) -> List[str]:
    ratios = {"strict": strict_ratio, "medium": medium_ratio, "wide": wide_ratio}
    ratio_sum = sum(ratios.values())
    raw_counts = {name: num_matchups * (value / ratio_sum) for name, value in ratios.items()}
    bucket_counts = {name: int(raw_counts[name]) for name in ratios}
    remainder = num_matchups - sum(bucket_counts.values())

    if remainder > 0:
        sorted_by_fraction = sorted(
            ratios.keys(),
            key=lambda name: (raw_counts[name] - bucket_counts[name]),
            reverse=True,
        )
        idx = 0
        while remainder > 0:
            bucket_counts[sorted_by_fraction[idx % len(sorted_by_fraction)]] += 1
            remainder -= 1
            idx += 1

    plan: List[str] = []
    for name in ("strict", "medium", "wide"):
        plan.extend([name] * bucket_counts[name])
    rng.shuffle(plan)
    return plan


def _generate_sign_plan(num_items: int, rng: random.Random) -> List[int]:
    positive = num_items // 2
    negative = num_items // 2
    neutral = num_items - positive - negative
    signs = ([1] * positive) + ([-1] * negative) + ([0] * neutral)
    rng.shuffle(signs)
    return signs


def _generate_matchups(
    generated_roster_values: List[Tuple[str, int]],
    opponent_roster_values: List[Tuple[str, int]],
    num_matchups: int,
    strict_tol: int,
    medium_tol: int,
    wide_tol: int,
    max_attempts: int,
    strict_ratio: float,
    medium_ratio: float,
    wide_ratio: float,
    enforce_sign_balance: bool,
    rng: random.Random,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    if num_matchups <= 0:
        raise ValueError(f"num_matchups must be > 0 (got {num_matchups})")
    if max_attempts <= 0:
        raise ValueError(f"max_attempts must be > 0 (got {max_attempts})")
    if not generated_roster_values:
        raise ValueError("No generated rosters available for matchup generation")
    if not opponent_roster_values:
        raise ValueError("No opponent rosters available for matchup generation")

    _validate_bucket_feasibility(
        strict_tol=strict_tol,
        medium_tol=medium_tol,
        wide_tol=wide_tol,
        strict_ratio=strict_ratio,
        medium_ratio=medium_ratio,
        wide_ratio=wide_ratio,
    )

    bucket_plan = _build_bucket_plan(
        num_matchups=num_matchups,
        strict_ratio=strict_ratio,
        medium_ratio=medium_ratio,
        wide_ratio=wide_ratio,
        rng=rng,
    )
    sign_plan = _generate_sign_plan(len(bucket_plan), rng) if enforce_sign_balance else [0] * len(bucket_plan)

    matchups: List[Dict[str, Any]] = []
    rejections = 0
    total_attempts = 0
    sign_counter: Counter[int] = Counter()

    for idx, bucket in enumerate(bucket_plan):
        if bucket == "strict":
            min_gap, max_gap = 0, strict_tol
        elif bucket == "medium":
            min_gap, max_gap = strict_tol + 1, medium_tol
        elif bucket == "wide":
            min_gap, max_gap = medium_tol + 1, wide_tol
        else:
            raise ValueError(f"Unknown bucket: {bucket}")

        desired_sign = sign_plan[idx]
        built = False
        for _ in range(max_attempts):
            total_attempts += 1
            p1_id, p1_val = rng.choice(generated_roster_values)
            p2_id, p2_val = rng.choice(opponent_roster_values)
            value_gap = p1_val - p2_val
            gap_abs = abs(value_gap)
            if gap_abs < min_gap or gap_abs > max_gap:
                rejections += 1
                continue

            if desired_sign > 0 and value_gap <= 0:
                rejections += 1
                continue
            if desired_sign < 0 and value_gap >= 0:
                rejections += 1
                continue

            sign = 1 if value_gap > 0 else (-1 if value_gap < 0 else 0)
            sign_counter[sign] += 1
            matchups.append(
                {
                    "bucket": bucket,
                    "p1_roster_id": p1_id,
                    "p2_roster_id": p2_id,
                    "p1_value": p1_val,
                    "p2_value": p2_val,
                    "value_gap": value_gap,
                }
            )
            built = True
            break

        if not built:
            raise RuntimeError(f"Failed to build matchup in bucket '{bucket}' after {max_attempts} attempts")

    if total_attempts <= 0:
        raise RuntimeError("Internal error: total matchup attempts is zero")

    abs_gaps = [abs(int(m["value_gap"])) for m in matchups]
    bucket_counts = Counter(str(m["bucket"]) for m in matchups)
    non_zero_total = sign_counter.get(1, 0) + sign_counter.get(-1, 0)
    sign_imbalance_abs = abs(sign_counter.get(1, 0) - sign_counter.get(-1, 0)) / non_zero_total if non_zero_total else 0.0
    sign_mean = _mean([float(1 if m["value_gap"] > 0 else (-1 if m["value_gap"] < 0 else 0)) for m in matchups])

    kpis = {
        "matchup_value_gap_mean": _mean([float(v) for v in abs_gaps]),
        "matchup_value_gap_p95": _quantile([float(v) for v in abs_gaps], 0.95),
        "pct_matchups_in_strict_bucket": bucket_counts.get("strict", 0) / len(matchups),
        "pct_matchups_in_medium_bucket": bucket_counts.get("medium", 0) / len(matchups),
        "pct_matchups_in_wide_bucket": bucket_counts.get("wide", 0) / len(matchups),
        "rejection_rate_matchup_gap": rejections / total_attempts,
        "pct_positive_value_gap": sign_counter.get(1, 0) / len(matchups),
        "pct_negative_value_gap": sign_counter.get(-1, 0) / len(matchups),
        "pct_zero_value_gap": sign_counter.get(0, 0) / len(matchups),
        "value_gap_sign_mean": sign_mean,
        "value_gap_sign_imbalance_abs": sign_imbalance_abs,
    }
    return matchups, kpis


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dynamic rosters from sampling matrix (v21)")
    parser.add_argument("--matrix", default="reports/unit_sampling_matrix.json", help="Sampling matrix JSON path")
    parser.add_argument("--target-tanking", required=False, choices=["Swarm", "Troop", "Elite"], default=None)
    parser.add_argument("--target-tanking-values", default=None,
                        help="Comma-separated list of tanking profiles for mixed sampling (e.g. Swarm,Troop,Elite)")
    parser.add_argument("--target-tanking-weights", default=None,
                        help="Comma-separated weights aligned with --target-tanking-values")
    parser.add_argument("--points-scale", type=int, default=150)
    parser.add_argument("--points-tolerance", type=int, default=2)
    parser.add_argument("--num-rosters", type=int, required=True)
    parser.add_argument("--units-per-roster", type=int, required=False, default=None)
    parser.add_argument("--units-per-roster-values", default=None,
                        help="Comma-separated unit counts per roster for mixed sampling (e.g. 4,5,6,7,8,9)")
    parser.add_argument("--units-per-roster-weights", default=None,
                        help="Comma-separated weights aligned with --units-per-roster-values")
    parser.add_argument("--max-copies-per-unit", type=int, default=2)
    parser.add_argument("--anti-repeat-window", type=int, default=20)
    parser.add_argument("--anti-repeat-penalty", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--split", choices=["training", "training_hard", "holdout", "holdout_regular", "holdout_hard"], default="training")
    parser.add_argument("--roster-prefix", default="p2_dynamic")
    parser.add_argument("--max-build-attempts", type=int, default=200)
    parser.add_argument("--max-roster-resample-attempts", type=int, default=40)
    parser.add_argument("--opponent-roster-dir", default=None)
    parser.add_argument("--num-matchups", type=int, default=None)
    parser.add_argument("--matchup-tol-strict", type=int, default=3)
    parser.add_argument("--matchup-tol-medium", type=int, default=7)
    parser.add_argument("--matchup-tol-wide", type=int, default=12)
    parser.add_argument("--matchup-ratio-strict", type=float, default=0.70)
    parser.add_argument("--matchup-ratio-medium", type=float, default=0.20)
    parser.add_argument("--matchup-ratio-wide", type=float, default=0.10)
    parser.add_argument("--enforce-matchup-sign-balance", action="store_true")
    parser.add_argument("--max-matchup-build-attempts", type=int, default=300)
    args = parser.parse_args()

    if args.points_scale <= 0:
        raise ValueError(f"--points-scale must be > 0 (got {args.points_scale})")
    if args.points_tolerance < 0:
        raise ValueError(f"--points-tolerance must be >= 0 (got {args.points_tolerance})")
    if args.num_rosters <= 0:
        raise ValueError(f"--num-rosters must be > 0 (got {args.num_rosters})")
    if args.max_copies_per_unit <= 0:
        raise ValueError(f"--max-copies-per-unit must be > 0 (got {args.max_copies_per_unit})")
    if args.anti_repeat_window < 0:
        raise ValueError(f"--anti-repeat-window must be >= 0 (got {args.anti_repeat_window})")
    if args.anti_repeat_penalty <= 0.0 or args.anti_repeat_penalty > 1.0:
        raise ValueError(f"--anti-repeat-penalty must be in (0,1] (got {args.anti_repeat_penalty})")
    if args.max_build_attempts <= 0:
        raise ValueError(f"--max-build-attempts must be > 0 (got {args.max_build_attempts})")
    if args.max_roster_resample_attempts <= 0:
        raise ValueError(
            f"--max-roster-resample-attempts must be > 0 (got {args.max_roster_resample_attempts})"
        )
    if args.max_matchup_build_attempts <= 0:
        raise ValueError(f"--max-matchup-build-attempts must be > 0 (got {args.max_matchup_build_attempts})")

    mixed_mode_requested = any([
        args.target_tanking_values is not None,
        args.target_tanking_weights is not None,
        args.units_per_roster_values is not None,
        args.units_per_roster_weights is not None,
    ])

    if mixed_mode_requested:
        if args.target_tanking is not None or args.units_per_roster is not None:
            raise ValueError(
                "Mixed mode requires omitting --target-tanking and --units-per-roster. "
                "Use only --target-tanking-values/weights and --units-per-roster-values/weights."
            )
        required_mixed_args = [
            ("--target-tanking-values", args.target_tanking_values),
            ("--target-tanking-weights", args.target_tanking_weights),
            ("--units-per-roster-values", args.units_per_roster_values),
            ("--units-per-roster-weights", args.units_per_roster_weights),
        ]
        missing = [name for name, value in required_mixed_args if value is None]
        if missing:
            raise ValueError(f"Mixed mode requires all 4 args, missing: {missing}")

        tanking_values = _parse_csv_values(args.target_tanking_values, "--target-tanking-values")
        allowed_tanking = {"Swarm", "Troop", "Elite"}
        for tanking in tanking_values:
            if tanking not in allowed_tanking:
                raise ValueError(
                    f"Invalid tanking '{tanking}' in --target-tanking-values; allowed={sorted(allowed_tanking)}"
                )
        tanking_weights = _parse_csv_float_weights(args.target_tanking_weights, "--target-tanking-weights")
        tanking_distribution = _normalize_weight_map(
            keys=tanking_values,
            raw_weights=tanking_weights,
            label="target_tanking_distribution",
        )

        units_per_roster_values = _parse_csv_positive_ints(
            args.units_per_roster_values,
            "--units-per-roster-values",
        )
        units_per_roster_weights = _parse_csv_float_weights(
            args.units_per_roster_weights,
            "--units-per-roster-weights",
        )
        units_distribution = _normalize_weight_map_int(
            keys=units_per_roster_values,
            raw_weights=units_per_roster_weights,
            label="units_per_roster_distribution",
        )
    else:
        if args.target_tanking is None:
            raise ValueError("--target-tanking is required in single mode")
        if args.units_per_roster is None:
            raise ValueError("--units-per-roster is required in single mode")
        if args.units_per_roster <= 0:
            raise ValueError(f"--units-per-roster must be > 0 (got {args.units_per_roster})")
        tanking_distribution = {str(args.target_tanking): 1.0}
        units_distribution = {int(args.units_per_roster): 1.0}

    # Naming policy: dedicated roster prefix for training_hard split by default.
    if args.split == "training_hard" and args.roster_prefix == "p2_dynamic":
        args.roster_prefix = "p2_training_hard_roster"

    matrix = _load_matrix(Path(args.matrix))
    units_meta = _load_unit_metadata_from_matrix(matrix)
    matrix_unit_keys = _extract_matrix_unit_keys(matrix)
    _validate_matrix_units_exist(matrix_unit_keys, units_meta)
    unit_value_by_type = _build_unit_type_value_index_strict(matrix_unit_keys, units_meta)

    target_by_tanking: Dict[str, Tuple[List[WeightedUnitChoice], Dict[str, float], Dict[str, float], Dict[str, float]]] = {}
    for tanking_name in sorted(tanking_distribution.keys()):
        target_by_tanking[tanking_name] = _build_feasible_weighted_unit_choices(
            target_tanking=tanking_name,
            matrix=matrix,
            units_meta=units_meta,
        )

    if args.output_dir is None:
        output_dir = Path(f"config/agents/_p2_rosters/{args.points_scale}pts/{args.split}")
    else:
        output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    recent_global_picks: Deque[str] = deque(maxlen=max(args.anti_repeat_window, 1))
    written_paths: List[Path] = []
    roster_values: List[int] = []
    all_unit_picks: List[UnitPick] = []
    selected_tanking_counter: Counter[str] = Counter()
    selected_units_per_roster_counter: Counter[int] = Counter()
    selected_unit_count_by_tanking: Counter[str] = Counter()
    total_rejected_attempts = 0
    total_attempts = 0
    generated_roster_values: List[Tuple[str, int]] = []

    tanking_keys = sorted(tanking_distribution.keys())
    tanking_weights_for_sampling = [tanking_distribution[key] for key in tanking_keys]
    units_keys = sorted(units_distribution.keys())
    units_weights_for_sampling = [units_distribution[key] for key in units_keys]

    for idx in range(1, args.num_rosters + 1):
        selected_tanking: Optional[str] = None
        selected_units_per_roster: Optional[int] = None
        build_result: Optional[RosterBuildResult] = None
        last_resample_error: Optional[RuntimeError] = None

        for _ in range(args.max_roster_resample_attempts):
            sampled_tanking = str(_weighted_pick(tanking_keys, tanking_weights_for_sampling, rng))
            sampled_units_per_roster = int(_weighted_pick(units_keys, units_weights_for_sampling, rng))
            weighted_choices, _blend_target, _mobility_target, _weapon_target = target_by_tanking[sampled_tanking]
            try:
                sampled_result = _build_one_roster(
                    weighted_choices=weighted_choices,
                    units_meta=units_meta,
                    target_points=args.points_scale,
                    points_tolerance=args.points_tolerance,
                    units_per_roster=sampled_units_per_roster,
                    max_attempts=args.max_build_attempts,
                    max_copies_per_unit=args.max_copies_per_unit,
                    anti_repeat_window=args.anti_repeat_window,
                    anti_repeat_penalty=args.anti_repeat_penalty,
                    recent_global_picks=recent_global_picks,
                    rng=rng,
                )
            except RuntimeError as exc:
                last_resample_error = exc
                continue
            selected_tanking = sampled_tanking
            selected_units_per_roster = sampled_units_per_roster
            build_result = sampled_result
            break

        if build_result is None or selected_tanking is None or selected_units_per_roster is None:
            raise RuntimeError(
                "Failed to build roster after resampling tanking/units combinations. "
                f"max_roster_resample_attempts={args.max_roster_resample_attempts}. "
                f"Last error: {last_resample_error}"
            )

        selected_tanking_counter[selected_tanking] += 1
        selected_units_per_roster_counter[int(selected_units_per_roster)] += 1

        roster_id = f"{args.roster_prefix}_{selected_tanking.lower()}_{idx:02d}"
        written_paths.append(_write_roster_file(output_dir, roster_id, build_result.composition))
        roster_values.append(build_result.roster_value)
        total_rejected_attempts += build_result.rejected_attempts
        total_attempts += build_result.total_attempts
        all_unit_picks.extend(build_result.unit_picks)
        selected_unit_count_by_tanking[selected_tanking] += len(build_result.unit_picks)
        generated_roster_values.append((roster_id, build_result.roster_value))

    if not all_unit_picks:
        raise RuntimeError("No unit picks collected after generation")

    picked_units_counter = Counter(p.unit_key for p in all_unit_picks)
    picked_blend_counter = Counter(p.blend_group for p in all_unit_picks)
    picked_mobility_counter = Counter(p.mobility_bucket for p in all_unit_picks)
    picked_weapon_counter = Counter(p.weapon_profile for p in all_unit_picks)

    blend_target = _compose_weighted_target(
        [
            (target_by_tanking[tanking][1], float(selected_unit_count_by_tanking[tanking]))
            for tanking in sorted(selected_unit_count_by_tanking.keys())
        ],
        label="blend_target",
    )
    mobility_target = _compose_weighted_target(
        [
            (target_by_tanking[tanking][2], float(selected_unit_count_by_tanking[tanking]))
            for tanking in sorted(selected_unit_count_by_tanking.keys())
        ],
        label="mobility_target",
    )
    weapon_target = _compose_weighted_target(
        [
            (target_by_tanking[tanking][3], float(selected_unit_count_by_tanking[tanking]))
            for tanking in sorted(selected_unit_count_by_tanking.keys())
        ],
        label="weapon_target",
    )

    observed_tanking_distribution = {
        key: float(selected_tanking_counter[key]) / float(args.num_rosters)
        for key in sorted(selected_tanking_counter.keys())
    }
    observed_units_distribution = {
        str(key): float(selected_units_per_roster_counter[key]) / float(args.num_rosters)
        for key in sorted(selected_units_per_roster_counter.keys())
    }

    kpis: Dict[str, Any] = {
        "roster_value_mean": _mean([float(v) for v in roster_values]),
        "roster_value_std": _std([float(v) for v in roster_values]),
        "roster_value_p95": _quantile([float(v) for v in roster_values], 0.95),
        "rejection_rate_roster_budget": total_rejected_attempts / total_attempts if total_attempts > 0 else 0.0,
        "sampling_target_tanking_distribution": {
            key: float(value) for key, value in sorted(tanking_distribution.items(), key=lambda item: item[0])
        },
        "sampling_observed_tanking_distribution": observed_tanking_distribution,
        "sampling_target_units_per_roster_distribution": {
            str(key): float(value) for key, value in sorted(units_distribution.items(), key=lambda item: item[0])
        },
        "sampling_observed_units_per_roster_distribution": observed_units_distribution,
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
            strict_ratio=args.matchup_ratio_strict,
            medium_ratio=args.matchup_ratio_medium,
            wide_ratio=args.matchup_ratio_wide,
            enforce_sign_balance=args.enforce_matchup_sign_balance,
            rng=rng,
        )
        matchup_payload = {
            "target_tanking_distribution": {
                key: float(value) for key, value in sorted(tanking_distribution.items(), key=lambda item: item[0])
            },
            "num_matchups": len(matchups),
            "matchups": matchups,
        }
        matchup_tanking_label = (
            str(args.target_tanking).lower()
            if args.target_tanking is not None
            else "mixed"
        )
        matchup_path = output_dir / f"{args.roster_prefix}_{matchup_tanking_label}_matchups.json"
        matchup_path.write_text(json.dumps(matchup_payload, indent=2), encoding="utf-8")
        kpis.update(matchup_kpis)

    kpi_tanking_label = (
        str(args.target_tanking).lower()
        if args.target_tanking is not None
        else "mixed"
    )
    kpi_path = output_dir / f"{args.roster_prefix}_{kpi_tanking_label}_kpis_v21.json"
    kpi_path.write_text(json.dumps(kpis, indent=2), encoding="utf-8")

    print(f"Generated rosters: {len(written_paths)}")
    print(
        "Target tanking distribution: "
        f"{dict(sorted(tanking_distribution.items(), key=lambda item: item[0]))}"
    )
    print(f"Observed tanking distribution: {observed_tanking_distribution}")
    print(f"Points budget: {args.points_scale} +/- {args.points_tolerance}")
    print(
        "Target units-per-roster distribution: "
        f"{dict(sorted(((str(k), v) for k, v in units_distribution.items()), key=lambda item: item[0]))}"
    )
    print(f"Observed units-per-roster distribution: {observed_units_distribution}")
    print(f"Max copies per unit: {args.max_copies_per_unit}")
    print(f"Anti-repeat window: {args.anti_repeat_window}")
    print(f"Anti-repeat penalty: {args.anti_repeat_penalty}")
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

