#!/usr/bin/env python3
"""
Automate weak-roster boost round (B3 -> B7).

Reads weak opponent roster IDs from a text file, generates boosted candidate pools by type,
builds a replacement plan, and optionally applies replacements in-place.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_dynamic_rosters import (  # pylint: disable=wrong-import-position
    _build_unit_type_value_index_strict,
    _extract_matrix_unit_keys,
    _load_matrix,
    _load_unit_metadata_from_matrix,
    _validate_matrix_units_exist,
)


def _read_weak_ids(path: Path) -> List[str]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Weak IDs file not found: {path}")
    ids: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value:
            continue
        ids.append(value)
    if not ids:
        raise ValueError(f"Weak IDs file is empty: {path}")
    return ids


def _extract_type(roster_id: str) -> str:
    # Ordre : balanced avant swarm/troop/elite (évite ambiguïtés si un nom contenait plusieurs tokens).
    if "_balanced_" in roster_id:
        return "Balanced"
    if "_swarm_" in roster_id:
        return "Swarm"
    if "_troop_" in roster_id:
        return "Troop"
    if "_elite_" in roster_id:
        return "Elite"
    raise ValueError(f"Cannot infer roster type from id: {roster_id}")


def _load_points_index(matrix_path: Path) -> Dict[str, int]:
    matrix = _load_matrix(matrix_path)
    units_meta = _load_unit_metadata_from_matrix(matrix)
    keys = _extract_matrix_unit_keys(matrix)
    _validate_matrix_units_exist(keys, units_meta)
    return _build_unit_type_value_index_strict(keys, units_meta)


def _roster_points(payload: Dict[str, Any], points_index: Dict[str, int]) -> int:
    composition = payload.get("composition")
    if not isinstance(composition, list):
        raise TypeError("roster payload missing valid 'composition' list")
    total = 0
    for entry in composition:
        if not isinstance(entry, dict):
            raise TypeError(f"invalid composition entry type: {type(entry).__name__}")
        unit_type = entry.get("unit_type")
        count = entry.get("count")
        if not isinstance(unit_type, str) or unit_type not in points_index:
            raise KeyError(f"Unknown or invalid unit_type in composition: {unit_type!r}")
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"Invalid count for unit_type '{unit_type}': {count!r}")
        total += points_index[unit_type] * count
    return total


def _run_build_dynamic_rosters(
    roster_type: str,
    args: argparse.Namespace,
    output_dir: Path,
) -> None:
    seed_bonus = {"Swarm": 1, "Troop": 2, "Elite": 3, "Balanced": 4}[roster_type]

    if roster_type == "Balanced":
        cmd = [
            "python3",
            "scripts/build_dynamic_rosters.py",
            "--num-rosters",
            str(args.num_candidates_per_type),
            "--points-scale",
            str(args.base_opponent_points + args.boost_step),
            "--points-tolerance",
            str(args.points_tolerance),
            "--split",
            args.split,
            "--roster-prefix",
            f"opponent_{args.split}_boost_{args.round_label}_balanced",
            "--output-dir",
            str(output_dir),
            "--target-tanking-values",
            "Swarm,Troop,Elite",
            "--target-tanking-weights",
            "0.3333,0.3333,0.3334",
            "--balanced-mode",
            "--balanced-min-share",
            str(args.balanced_min_share),
            "--balanced-max-share",
            str(args.balanced_max_share),
            "--units-per-roster-values",
            args.balanced_units_per_roster_values,
            "--units-per-roster-weights",
            args.balanced_units_per_roster_weights,
            "--max-build-attempts",
            str(args.max_build_attempts),
            "--max-roster-resample-attempts",
            str(args.max_roster_resample_attempts),
            "--max-copies-per-unit",
            str(args.max_copies_per_unit),
            "--seed",
            str(args.seed_base + seed_bonus),
        ]
    else:
        cmd = [
            "python3",
            "scripts/build_dynamic_rosters.py",
            "--num-rosters",
            str(args.num_candidates_per_type),
            "--points-scale",
            str(args.base_opponent_points + args.boost_step),
            "--points-tolerance",
            str(args.points_tolerance),
            "--split",
            args.split,
            "--roster-prefix",
            f"opponent_{args.split}_boost_{args.round_label}_{roster_type.lower()}",
            "--output-dir",
            str(output_dir),
            "--target-tanking-values",
            roster_type,
            "--target-tanking-weights",
            "1.0",
            "--units-per-roster-values",
            args.units_per_roster_values,
            "--units-per-roster-weights",
            args.units_per_roster_weights,
            "--max-build-attempts",
            str(args.max_build_attempts),
            "--max-roster-resample-attempts",
            str(args.max_roster_resample_attempts),
            "--max-copies-per-unit",
            str(args.max_copies_per_unit),
            "--seed",
            str(args.seed_base + seed_bonus),
        ]
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)


def _load_roster_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_files_by_type(candidate_dir: Path) -> Dict[str, List[Path]]:
    grouped: Dict[str, List[Path]] = {"Balanced": [], "Swarm": [], "Troop": [], "Elite": []}
    for path in sorted(candidate_dir.glob("*.json")):
        if "_kpis" in path.name or "_matchups" in path.name:
            continue
        if "_balanced_" in path.name:
            grouped["Balanced"].append(path)
        elif "_swarm_" in path.name:
            grouped["Swarm"].append(path)
        elif "_troop_" in path.name:
            grouped["Troop"].append(path)
        elif "_elite_" in path.name:
            grouped["Elite"].append(path)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto boost weak opponent rosters (B3->B7)")
    parser.add_argument("--weak-ids-file", required=True, help="Path to weak roster IDs (one per line)")
    parser.add_argument("--agent", default="CoreAgent")
    parser.add_argument("--scale", default="150pts")
    parser.add_argument("--split", default="holdout_hard")
    parser.add_argument("--round-label", default="r1")
    parser.add_argument("--matrix", default="reports/unit_sampling_matrix.json")
    parser.add_argument("--base-opponent-points", type=int, default=165)
    parser.add_argument("--boost-step", type=int, default=5)
    parser.add_argument("--num-candidates-per-type", type=int, default=120)
    parser.add_argument("--points-tolerance", type=int, default=5)
    parser.add_argument("--units-per-roster-values", default="5,6,7,8,9,10,11,12")
    parser.add_argument("--units-per-roster-weights", default="0.06,0.12,0.18,0.22,0.20,0.14,0.06,0.02")
    parser.add_argument(
        "--balanced-units-per-roster-values",
        default="5,6,8,9,10,11,12",
        help="Mixed-mode units distribution for Balanced boost candidates",
    )
    parser.add_argument(
        "--balanced-units-per-roster-weights",
        default="0.08,0.15,0.25,0.24,0.18,0.07,0.03",
        help="Weights aligned with --balanced-units-per-roster-values",
    )
    parser.add_argument("--balanced-min-share", type=float, default=0.20)
    parser.add_argument("--balanced-max-share", type=float, default=0.40)
    parser.add_argument("--max-build-attempts", type=int, default=2000)
    parser.add_argument("--max-roster-resample-attempts", type=int, default=80)
    parser.add_argument("--max-copies-per-unit", type=int, default=3)
    parser.add_argument("--seed-base", type=int, default=41000)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    weak_ids_file = (PROJECT_ROOT / args.weak_ids_file).resolve() if not Path(args.weak_ids_file).is_absolute() else Path(args.weak_ids_file)
    weak_ids = _read_weak_ids(weak_ids_file)

    points_index = _load_points_index(PROJECT_ROOT / args.matrix)

    candidate_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / args.scale / f"{args.split}_boost_{args.round_label}"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    deprecated_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / args.scale / f"{args.split}_deprecated"
    deprecated_dir.mkdir(parents=True, exist_ok=True)
    alert_plus30_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / args.scale / f"{args.split}_alert_plus30"
    alert_plus40_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / args.scale / f"{args.split}_alert_plus40"
    alert_plus30_dir.mkdir(parents=True, exist_ok=True)
    alert_plus40_dir.mkdir(parents=True, exist_ok=True)

    roster_types = sorted({_extract_type(rid) for rid in weak_ids})
    for roster_type in roster_types:
        _run_build_dynamic_rosters(roster_type, args, candidate_dir)

    candidates = _candidate_files_by_type(candidate_dir)
    required_counts = {"Balanced": 0, "Swarm": 0, "Troop": 0, "Elite": 0}
    for rid in weak_ids:
        required_counts[_extract_type(rid)] += 1
    for roster_type, required in required_counts.items():
        if required == 0:
            continue
        if len(candidates[roster_type]) < required:
            raise RuntimeError(
                f"Not enough candidates for {roster_type}: need {required}, got {len(candidates[roster_type])}"
            )

    pool_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / args.scale / args.split
    report_dir = PROJECT_ROOT / "reports" / "boost_rounds"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_csv = report_dir / f"{args.round_label}_B5_replacements.csv"
    report_json = report_dir / f"{args.round_label}_summary.json"

    planned_rows: List[Dict[str, Any]] = []
    type_cursor = {"Balanced": 0, "Swarm": 0, "Troop": 0, "Elite": 0}
    for old_id in weak_ids:
        roster_type = _extract_type(old_id)
        candidate_path = candidates[roster_type][type_cursor[roster_type]]
        type_cursor[roster_type] += 1

        old_path = pool_dir / f"{old_id}.json"
        if not old_path.exists():
            raise FileNotFoundError(f"Old roster file not found: {old_path}")

        old_payload = _load_roster_json(old_path)
        candidate_payload = _load_roster_json(candidate_path)
        old_points = _roster_points(old_payload, points_index)
        new_points = _roster_points(candidate_payload, points_index)
        delta = new_points - old_points

        # Preserve old roster identity for downstream references.
        replaced_payload = {
            "roster_id": old_id,
            "composition": candidate_payload.get("composition"),
        }

        if args.apply:
            shutil.move(str(old_path), str(deprecated_dir / old_path.name))
            old_path.write_text(json.dumps(replaced_payload, indent=2), encoding="utf-8")
            if delta >= 30:
                shutil.copy2(str(old_path), str(alert_plus30_dir / old_path.name))
            if delta >= 40:
                shutil.copy2(str(old_path), str(alert_plus40_dir / old_path.name))

        planned_rows.append(
            {
                "old_roster_id": old_id,
                "type": roster_type.lower(),
                "base_points": old_points,
                "final_points": new_points,
                "delta_points": delta,
                "wr_greedy": "",
                "wr_defensive_smart": "",
                "wr_adaptive": "",
                "wr_weighted": "",
                "pass_1": "",
                "pass_2": "",
                "stable_2_passes": "",
                "decision": "replaced" if args.apply else "planned",
                "alert_bucket": "plus40" if delta >= 40 else ("plus30" if delta >= 30 else "none"),
                "new_roster_file": str(candidate_path.relative_to(PROJECT_ROOT)),
                "old_roster_file": str(old_path.relative_to(PROJECT_ROOT)),
            }
        )

    with report_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "old_roster_id",
                "type",
                "base_points",
                "final_points",
                "delta_points",
                "wr_greedy",
                "wr_defensive_smart",
                "wr_adaptive",
                "wr_weighted",
                "pass_1",
                "pass_2",
                "stable_2_passes",
                "decision",
                "alert_bucket",
                "new_roster_file",
                "old_roster_file",
            ],
        )
        writer.writeheader()
        writer.writerows(planned_rows)

    summary = {
        "round_label": args.round_label,
        "weak_ids_file": str(weak_ids_file),
        "apply": bool(args.apply),
        "candidate_dir": str(candidate_dir),
        "replacements_count": len(planned_rows),
        "by_type": required_counts,
        "csv_report": str(report_csv),
        "deprecated_dir": str(deprecated_dir),
        "alert_plus30_dir": str(alert_plus30_dir),
        "alert_plus40_dir": str(alert_plus40_dir),
    }
    report_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"✅ Round '{args.round_label}' completed. apply={args.apply}")
    print(f"   Replacements planned/applied: {len(planned_rows)}")
    print(f"   CSV report: {report_csv}")
    print(f"   Summary: {report_json}")


if __name__ == "__main__":
    main()

