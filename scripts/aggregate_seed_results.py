#!/usr/bin/env python3
"""
Aggregate PPO seed results from TensorBoard event files.

Expected layout (recommended):
  tensorboard_<batch>/<seed>/

Example:
  python scripts/aggregate_seed_results.py \
    --runs-root ./tensorboard_b001 \
    --seeds 32345 42345 52345 62345 72345 \
    --run-pattern "{seed}" \
    --min-evals 5 \
    --out-prefix ./reports/b001_coreagent
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator


@dataclass
class ScalarPoint:
    step: int
    wall_time: float
    value: float


@dataclass
class SeedSummary:
    seed: str
    run_dir: str
    valid: bool
    reason: str
    robust_points: int
    robust_best: Optional[float]
    robust_last: Optional[float]
    combined_best: Optional[float]
    combined_last: Optional[float]
    worst_bot_min: Optional[float]
    holdout_hard_min: Optional[float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate TensorBoard metrics across seeds for PPO robustness analysis."
    )
    parser.add_argument(
        "--runs-root",
        required=True,
        help="Root directory for one batch (ex: tensorboard_b001).",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        required=True,
        help="Seed list (ex: 32345 42345 52345 62345 72345).",
    )
    parser.add_argument(
        "--run-pattern",
        default="{seed}",
        help='Subdirectory pattern under runs-root (default: "{seed}").',
    )
    parser.add_argument(
        "--tag-robust",
        default="0_critical/n_robust_current_score",
        help="TensorBoard tag for robust current score.",
    )
    parser.add_argument(
        "--tag-combined",
        default="0_critical/a_bot_eval_combined",
        help="TensorBoard tag for combined score.",
    )
    parser.add_argument(
        "--tag-worst-bot",
        default="0_critical/b_worst_bot_score",
        help="TensorBoard tag for worst bot score.",
    )
    parser.add_argument(
        "--tag-holdout-hard",
        default="0_critical/c_holdout_hard_mean",
        help="TensorBoard tag for holdout hard mean.",
    )
    parser.add_argument(
        "--min-evals",
        type=int,
        default=5,
        help="Minimum robust points required for a seed to be valid.",
    )
    parser.add_argument(
        "--out-prefix",
        default=None,
        help="Output prefix for JSON/CSV files (without extension).",
    )
    return parser.parse_args()


def collect_event_files(run_dir: Path) -> List[Path]:
    return sorted(run_dir.rglob("events.out.tfevents.*"))


def read_scalar_points(event_files: List[Path], tag: str) -> List[ScalarPoint]:
    merged: Dict[Tuple[int, float], ScalarPoint] = {}
    for event_file in event_files:
        accumulator = EventAccumulator(str(event_file), size_guidance={"scalars": 0})
        try:
            accumulator.Reload()
        except Exception as exc:
            raise RuntimeError(f"Cannot read event file: {event_file} ({exc})") from exc
        scalar_tags = accumulator.Tags().get("scalars", [])
        if tag not in scalar_tags:
            continue
        for scalar in accumulator.Scalars(tag):
            step = int(scalar.step)
            wall_time = float(scalar.wall_time)
            key = (step, wall_time)
            merged[key] = ScalarPoint(step=step, wall_time=wall_time, value=float(scalar.value))
    points = list(merged.values())
    points.sort(key=lambda p: (p.step, p.wall_time))
    return points


def best_value(points: List[ScalarPoint]) -> Optional[float]:
    if not points:
        return None
    return float(max(p.value for p in points))


def last_value(points: List[ScalarPoint]) -> Optional[float]:
    if not points:
        return None
    return float(points[-1].value)


def min_value(points: List[ScalarPoint]) -> Optional[float]:
    if not points:
        return None
    return float(min(p.value for p in points))


def summarize_seed(
    seed: str,
    run_dir: Path,
    event_files: List[Path],
    tag_robust: str,
    tag_combined: str,
    tag_worst_bot: str,
    tag_holdout_hard: str,
    min_evals: int,
) -> SeedSummary:
    robust_points = read_scalar_points(event_files, tag_robust)
    combined_points = read_scalar_points(event_files, tag_combined)
    worst_bot_points = read_scalar_points(event_files, tag_worst_bot)
    holdout_hard_points = read_scalar_points(event_files, tag_holdout_hard)

    valid = len(robust_points) >= min_evals
    reason = "ok" if valid else f"insufficient_robust_points({len(robust_points)}<{min_evals})"

    return SeedSummary(
        seed=str(seed),
        run_dir=str(run_dir),
        valid=valid,
        reason=reason,
        robust_points=len(robust_points),
        robust_best=best_value(robust_points),
        robust_last=last_value(robust_points),
        combined_best=best_value(combined_points),
        combined_last=last_value(combined_points),
        worst_bot_min=min_value(worst_bot_points),
        holdout_hard_min=min_value(holdout_hard_points),
    )


def compute_aggregate(seed_rows: List[SeedSummary]) -> Dict[str, object]:
    valid_rows = [row for row in seed_rows if row.valid and row.robust_best is not None]
    robust_values = [float(row.robust_best) for row in valid_rows]

    aggregate: Dict[str, object] = {
        "seeds_total": len(seed_rows),
        "seeds_valid": len(valid_rows),
        "valid_rate": (len(valid_rows) / len(seed_rows)) if seed_rows else 0.0,
        "median_best_robust": None,
        "q1_best_robust": None,
        "q3_best_robust": None,
        "iqr_best_robust": None,
        "min_best_robust": None,
        "max_best_robust": None,
    }

    if robust_values:
        q1 = float(np.percentile(robust_values, 25))
        q3 = float(np.percentile(robust_values, 75))
        aggregate.update(
            {
                "median_best_robust": float(np.median(robust_values)),
                "q1_best_robust": q1,
                "q3_best_robust": q3,
                "iqr_best_robust": float(q3 - q1),
                "min_best_robust": float(min(robust_values)),
                "max_best_robust": float(max(robust_values)),
            }
        )
    return aggregate


def print_console_report(seed_rows: List[SeedSummary], aggregate: Dict[str, object]) -> None:
    print("\n=== Seed summary ===")
    print(
        "seed    valid  robust_pts  robust_best  robust_last  combined_last  "
        "worst_bot_min  holdout_hard_min"
    )
    for row in sorted(seed_rows, key=lambda r: int(r.seed)):
        def fmt(value: Optional[float]) -> str:
            return "NA" if value is None else f"{value:.4f}"

        print(
            f"{row.seed:<7} {str(row.valid):<5} {row.robust_points:<11} "
            f"{fmt(row.robust_best):<12} {fmt(row.robust_last):<11} {fmt(row.combined_last):<13} "
            f"{fmt(row.worst_bot_min):<13} {fmt(row.holdout_hard_min)}"
        )
        if not row.valid:
            print(f"  -> reason: {row.reason}")

    print("\n=== Aggregate ===")
    for key in (
        "seeds_total",
        "seeds_valid",
        "valid_rate",
        "median_best_robust",
        "q1_best_robust",
        "q3_best_robust",
        "iqr_best_robust",
        "min_best_robust",
        "max_best_robust",
    ):
        value = aggregate.get(key)
        if isinstance(value, float):
            print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")


def write_outputs(
    out_prefix: Path,
    seed_rows: List[SeedSummary],
    aggregate: Dict[str, object],
    args: argparse.Namespace,
) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    json_path = out_prefix.with_suffix(".json")
    csv_path = out_prefix.with_suffix(".csv")

    payload = {
        "config": {
            "runs_root": str(Path(args.runs_root).resolve()),
            "seeds": list(args.seeds),
            "run_pattern": args.run_pattern,
            "tag_robust": args.tag_robust,
            "tag_combined": args.tag_combined,
            "tag_worst_bot": args.tag_worst_bot,
            "tag_holdout_hard": args.tag_holdout_hard,
            "min_evals": args.min_evals,
        },
        "aggregate": aggregate,
        "seeds": [asdict(row) for row in seed_rows],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "seed",
                "run_dir",
                "valid",
                "reason",
                "robust_points",
                "robust_best",
                "robust_last",
                "combined_best",
                "combined_last",
                "worst_bot_min",
                "holdout_hard_min",
            ],
        )
        writer.writeheader()
        for row in seed_rows:
            writer.writerow(asdict(row))

    print(f"\nWrote JSON: {json_path}")
    print(f"Wrote CSV : {csv_path}")


def main() -> int:
    args = parse_args()

    if args.min_evals <= 0:
        raise ValueError(f"--min-evals must be > 0 (got {args.min_evals})")

    runs_root = Path(args.runs_root).resolve()
    if not runs_root.exists():
        raise FileNotFoundError(f"--runs-root does not exist: {runs_root}")
    if not runs_root.is_dir():
        raise NotADirectoryError(f"--runs-root must be a directory: {runs_root}")

    seed_rows: List[SeedSummary] = []

    for seed in args.seeds:
        run_dir = runs_root / args.run_pattern.format(seed=seed)
        if not run_dir.exists():
            raise FileNotFoundError(
                f"Run directory not found for seed={seed}: {run_dir} "
                f"(check --run-pattern and --runs-root)"
            )
        if not run_dir.is_dir():
            raise NotADirectoryError(f"Run path is not a directory for seed={seed}: {run_dir}")
        event_files = collect_event_files(run_dir)
        if not event_files:
            raise FileNotFoundError(f"No TensorBoard event files found in: {run_dir}")

        summary = summarize_seed(
            seed=str(seed),
            run_dir=run_dir,
            event_files=event_files,
            tag_robust=args.tag_robust,
            tag_combined=args.tag_combined,
            tag_worst_bot=args.tag_worst_bot,
            tag_holdout_hard=args.tag_holdout_hard,
            min_evals=args.min_evals,
        )
        seed_rows.append(summary)

    aggregate = compute_aggregate(seed_rows)
    print_console_report(seed_rows, aggregate)

    default_prefix = runs_root / "seed_aggregate"
    out_prefix = Path(args.out_prefix).resolve() if args.out_prefix else default_prefix
    write_outputs(out_prefix, seed_rows, aggregate, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
