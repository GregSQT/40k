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
    --last-run-only \
    --min-evals 5 \
    --out-prefix ./reports/b001_coreagent
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    schedule_diagnostics: Dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate TensorBoard metrics across seeds for PPO robustness analysis."
    )
    parser.add_argument(
        "--runs-root",
        default="./tensorboard",
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
        "--last-run-only",
        action="store_true",
        help=(
            "V2 fast mode: read only one run directory per seed. "
            "Requires a clean seed folder with exactly one run_* directory."
        ),
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
        "--enable-schedule-diagnostics",
        action="store_true",
        help="Enable diagnostics for each decreasing schedule parameter.",
    )
    parser.add_argument(
        "--decaying-tags",
        nargs="+",
        default=[
            "training_diagnostic/learning_rate",
            "training_diagnostic/entropy_coef",
        ],
        help=(
            "TensorBoard scalar tags treated as decreasing schedule parameters "
            "(default: learning_rate, entropy_coef)."
        ),
    )
    parser.add_argument(
        "--diag-fast-consumption-at-40",
        type=float,
        default=0.65,
        help=(
            "If consumed decay fraction at 40%% is >= this threshold, "
            "schedule pace is classified TOO_FAST."
        ),
    )
    parser.add_argument(
        "--diag-slow-consumption-at-80",
        type=float,
        default=0.70,
        help=(
            "If consumed decay fraction at 80%% is <= this threshold, "
            "schedule pace is classified TOO_SLOW."
        ),
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
    parser.add_argument(
        "--archive-runs-root",
        action="store_true",
        help=(
            "After successful analysis, rename runs-root to next batch directory "
            "(ex: tensorboard -> tensorboard_b001) and recreate runs-root empty."
        ),
    )
    parser.add_argument(
        "--archive-prefix",
        default="tensorboard_b",
        help="Batch directory prefix used with --archive-runs-root (default: tensorboard_b).",
    )
    parser.add_argument(
        "--archive-width",
        type=int,
        default=3,
        help="Zero-padding width for batch index (default: 3 => b001, b002, ...).",
    )
    return parser.parse_args()


def collect_event_files(run_dir: Path) -> List[Path]:
    return sorted(run_dir.rglob("events.out.tfevents.*"))


def resolve_analysis_dir_for_seed(seed_dir: Path, last_run_only: bool) -> Path:
    """Return the directory to scan for event files for a seed."""
    if not last_run_only:
        return seed_dir

    if not seed_dir.exists():
        raise FileNotFoundError(f"Seed directory does not exist: {seed_dir}")
    if not seed_dir.is_dir():
        raise NotADirectoryError(f"Seed path is not a directory: {seed_dir}")

    run_dirs = sorted(
        [
            child
            for child in seed_dir.iterdir()
            if child.is_dir() and child.name.startswith("run_")
        ]
    )
    if len(run_dirs) != 1:
        raise RuntimeError(
            "Invalid seed folder for --last-run-only: expected exactly one run_* directory "
            f"in {seed_dir}, found {len(run_dirs)} ({[d.name for d in run_dirs]})"
        )
    return run_dirs[0]


def read_scalar_points_for_tags(
    event_files: List[Path], tags: List[str]
) -> Dict[str, List[ScalarPoint]]:
    requested_tags = {str(tag) for tag in tags}
    merged_by_tag: Dict[str, Dict[Tuple[int, float], ScalarPoint]] = {
        tag: {} for tag in requested_tags
    }

    for event_file in event_files:
        accumulator = EventAccumulator(str(event_file), size_guidance={"scalars": 0})
        try:
            accumulator.Reload()
        except Exception as exc:
            raise RuntimeError(f"Cannot read event file: {event_file} ({exc})") from exc
        available_scalar_tags = set(accumulator.Tags().get("scalars", []))
        tags_to_read = requested_tags.intersection(available_scalar_tags)
        for tag in tags_to_read:
            per_tag_merged = merged_by_tag[tag]
            for scalar in accumulator.Scalars(tag):
                step = int(scalar.step)
                wall_time = float(scalar.wall_time)
                key = (step, wall_time)
                per_tag_merged[key] = ScalarPoint(
                    step=step,
                    wall_time=wall_time,
                    value=float(scalar.value),
                )

    result: Dict[str, List[ScalarPoint]] = {}
    for tag in requested_tags:
        points = list(merged_by_tag[tag].values())
        points.sort(key=lambda p: (p.step, p.wall_time))
        result[tag] = points
    return result


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
    decaying_tags: List[str],
    enable_schedule_diagnostics: bool,
    diag_fast_consumption_at_40: float,
    diag_slow_consumption_at_80: float,
    min_evals: int,
) -> SeedSummary:
    points_by_tag = read_scalar_points_for_tags(
        event_files=event_files,
        tags=[tag_robust, tag_combined, tag_worst_bot, tag_holdout_hard] + decaying_tags,
    )
    robust_points = points_by_tag[tag_robust]
    combined_points = points_by_tag[tag_combined]
    worst_bot_points = points_by_tag[tag_worst_bot]
    holdout_hard_points = points_by_tag[tag_holdout_hard]

    valid = len(robust_points) >= min_evals
    reason = "ok" if valid else f"insufficient_robust_points({len(robust_points)}<{min_evals})"

    schedule_diagnostics: Dict[str, Any] = {}
    if enable_schedule_diagnostics:
        for decaying_tag in decaying_tags:
            schedule_diagnostics[decaying_tag] = compute_schedule_diagnostic(
                points=points_by_tag.get(decaying_tag, []),
                fast_consumption_at_40=diag_fast_consumption_at_40,
                slow_consumption_at_80=diag_slow_consumption_at_80,
            )

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
        schedule_diagnostics=schedule_diagnostics,
    )


def _value_at_progress(points: List[ScalarPoint], progress: float) -> Optional[float]:
    if not points:
        return None
    max_step = max(p.step for p in points)
    target_step = int(round(progress * max_step))
    for p in points:
        if p.step >= target_step:
            return float(p.value)
    return float(points[-1].value)


def compute_schedule_diagnostic(
    points: List[ScalarPoint],
    fast_consumption_at_40: float,
    slow_consumption_at_80: float,
) -> Dict[str, Any]:
    if not points:
        return {"status": "MISSING", "reason": "tag_not_found_or_no_points"}
    if len(points) < 5:
        return {"status": "INSUFFICIENT_DATA", "reason": f"points<{5}", "points": len(points)}

    checkpoints = {
        "p20": _value_at_progress(points, 0.20),
        "p40": _value_at_progress(points, 0.40),
        "p60": _value_at_progress(points, 0.60),
        "p80": _value_at_progress(points, 0.80),
        "p100": _value_at_progress(points, 1.00),
    }
    if any(v is None for v in checkpoints.values()):
        return {"status": "INSUFFICIENT_DATA", "reason": "checkpoint_resolution_failed"}

    start_value = float(points[0].value)
    end_value = float(points[-1].value)
    total_drop = start_value - end_value
    if total_drop <= 0.0:
        return {
            "status": "NOT_DECREASING",
            "reason": "non_decreasing_parameter",
            "start_value": start_value,
            "end_value": end_value,
            "checkpoints": checkpoints,
        }

    p40 = float(checkpoints["p40"])
    p80 = float(checkpoints["p80"])
    consumed_40 = (start_value - p40) / total_drop
    consumed_80 = (start_value - p80) / total_drop

    pace_status = "OK"
    if consumed_40 >= fast_consumption_at_40:
        pace_status = "TOO_FAST"
    elif consumed_80 <= slow_consumption_at_80:
        pace_status = "TOO_SLOW"

    return {
        "status": pace_status,
        "start_value": start_value,
        "end_value": end_value,
        "consumed_decay_fraction_at_40": float(consumed_40),
        "consumed_decay_fraction_at_80": float(consumed_80),
        "checkpoints": checkpoints,
        "points": len(points),
    }


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

    schedule_counts: Dict[str, Dict[str, int]] = {}
    for row in seed_rows:
        for tag_name, diag in row.schedule_diagnostics.items():
            if tag_name not in schedule_counts:
                schedule_counts[tag_name] = {
                    "OK": 0,
                    "TOO_FAST": 0,
                    "TOO_SLOW": 0,
                    "MISSING": 0,
                    "INSUFFICIENT_DATA": 0,
                    "NOT_DECREASING": 0,
                }
            status = str(diag.get("status", "MISSING"))
            if status not in schedule_counts[tag_name]:
                schedule_counts[tag_name][status] = 0
            schedule_counts[tag_name][status] += 1
    aggregate["schedule_diagnostics"] = schedule_counts
    aggregate["schedule_pacing_verdict"] = compute_schedule_pacing_verdict(schedule_counts)
    return aggregate


def _per_tag_pacing_verdict(counts: Dict[str, int]) -> str:
    missing = int(counts.get("MISSING", 0))
    insufficient = int(counts.get("INSUFFICIENT_DATA", 0))
    not_decreasing = int(counts.get("NOT_DECREASING", 0))
    too_fast = int(counts.get("TOO_FAST", 0))
    too_slow = int(counts.get("TOO_SLOW", 0))

    if missing > 0 or insufficient > 0:
        return "INCOMPLETE"
    if not_decreasing > 0:
        return "INVALID"
    if too_fast > 0 and too_slow > 0:
        return "MIXED"
    if too_fast > 0:
        return "TOO_FAST"
    if too_slow > 0:
        return "TOO_SLOW"
    return "OK"


def compute_schedule_pacing_verdict(
    schedule_counts: Dict[str, Dict[str, int]]
) -> Dict[str, Any]:
    if not schedule_counts:
        return {"global": "NOT_EVALUATED", "per_tag": {}}

    per_tag: Dict[str, str] = {}
    for tag_name, counts in schedule_counts.items():
        per_tag[tag_name] = _per_tag_pacing_verdict(counts)

    verdicts = set(per_tag.values())
    if "INVALID" in verdicts:
        global_verdict = "INVALID"
    elif "INCOMPLETE" in verdicts:
        global_verdict = "INCOMPLETE"
    elif "MIXED" in verdicts:
        global_verdict = "MIXED"
    elif "TOO_FAST" in verdicts and "TOO_SLOW" in verdicts:
        global_verdict = "MIXED"
    elif "TOO_FAST" in verdicts:
        global_verdict = "TOO_FAST"
    elif "TOO_SLOW" in verdicts:
        global_verdict = "TOO_SLOW"
    else:
        global_verdict = "OK"

    return {"global": global_verdict, "per_tag": per_tag}


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
        if row.schedule_diagnostics:
            for tag_name, diag in row.schedule_diagnostics.items():
                status = str(diag.get("status", "MISSING"))
                if status in ("TOO_FAST", "TOO_SLOW", "OK"):
                    c40 = diag.get("consumed_decay_fraction_at_40")
                    c80 = diag.get("consumed_decay_fraction_at_80")
                    if isinstance(c40, float) and isinstance(c80, float):
                        print(
                            f"  -> schedule {tag_name}: {status} "
                            f"(consumed@40={c40:.3f}, consumed@80={c80:.3f})"
                        )
                    else:
                        print(f"  -> schedule {tag_name}: {status}")
                else:
                    reason = diag.get("reason", "n/a")
                    print(f"  -> schedule {tag_name}: {status} ({reason})")

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
    schedule_diag = aggregate.get("schedule_diagnostics")
    if isinstance(schedule_diag, dict) and schedule_diag:
        print("schedule_diagnostics:")
        for tag_name, counts in schedule_diag.items():
            print(f"  - {tag_name}: {counts}")
    schedule_verdict = aggregate.get("schedule_pacing_verdict")
    if isinstance(schedule_verdict, dict) and schedule_verdict:
        print(f"schedule_pacing_verdict.global: {schedule_verdict.get('global')}")
        per_tag_verdict = schedule_verdict.get("per_tag")
        if isinstance(per_tag_verdict, dict):
            for tag_name, verdict in per_tag_verdict.items():
                print(f"  - {tag_name}: {verdict}")


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
            "last_run_only": bool(args.last_run_only),
            "tag_robust": args.tag_robust,
            "tag_combined": args.tag_combined,
            "tag_worst_bot": args.tag_worst_bot,
            "tag_holdout_hard": args.tag_holdout_hard,
            "enable_schedule_diagnostics": bool(args.enable_schedule_diagnostics),
            "decaying_tags": list(args.decaying_tags),
            "diag_fast_consumption_at_40": float(args.diag_fast_consumption_at_40),
            "diag_slow_consumption_at_80": float(args.diag_slow_consumption_at_80),
            "min_evals": args.min_evals,
            "archive_runs_root": bool(args.archive_runs_root),
            "archive_prefix": str(args.archive_prefix),
            "archive_width": int(args.archive_width),
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
                "schedule_diagnostics",
            ],
        )
        writer.writeheader()
        for row in seed_rows:
            writer.writerow(asdict(row))

    print(f"\nWrote JSON: {json_path}")
    print(f"Wrote CSV : {csv_path}")


def _next_batch_dir(parent_dir: Path, prefix: str, width: int) -> Path:
    if width <= 0:
        raise ValueError(f"--archive-width must be > 0 (got {width})")
    highest_idx = 0
    for candidate in parent_dir.iterdir():
        if not candidate.is_dir():
            continue
        name = candidate.name
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if suffix.isdigit():
            highest_idx = max(highest_idx, int(suffix))
    next_idx = highest_idx + 1
    return parent_dir / f"{prefix}{next_idx:0{width}d}"


def archive_runs_root(runs_root: Path, prefix: str, width: int) -> Path:
    parent_dir = runs_root.parent
    dst_dir = _next_batch_dir(parent_dir, prefix, width)
    return archive_runs_root_to(runs_root, dst_dir)


def archive_runs_root_to(runs_root: Path, dst_dir: Path) -> Path:
    if dst_dir.exists():
        raise FileExistsError(f"Batch destination already exists: {dst_dir}")
    runs_root.rename(dst_dir)
    runs_root.mkdir(parents=True, exist_ok=False)
    print(f"Archived runs-root: {dst_dir}")
    print(f"Recreated empty runs-root: {runs_root}")
    return dst_dir


def _extract_batch_token(batch_dir_name: str) -> str:
    match = re.search(r"(b\d+)$", batch_dir_name)
    if match:
        return str(match.group(1))
    return batch_dir_name


def main() -> int:
    args = parse_args()

    if args.min_evals <= 0:
        raise ValueError(f"--min-evals must be > 0 (got {args.min_evals})")
    if not (0.0 < float(args.diag_fast_consumption_at_40) <= 1.0):
        raise ValueError(
            "--diag-fast-consumption-at-40 must be in (0,1] "
            f"(got {args.diag_fast_consumption_at_40})"
        )
    if not (0.0 <= float(args.diag_slow_consumption_at_80) < 1.0):
        raise ValueError(
            "--diag-slow-consumption-at-80 must be in [0,1) "
            f"(got {args.diag_slow_consumption_at_80})"
        )

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
        analysis_dir = resolve_analysis_dir_for_seed(
            seed_dir=run_dir,
            last_run_only=bool(args.last_run_only),
        )
        event_files = collect_event_files(analysis_dir)
        if not event_files:
            raise FileNotFoundError(f"No TensorBoard event files found in: {analysis_dir}")

        summary = summarize_seed(
            seed=str(seed),
            run_dir=analysis_dir,
            event_files=event_files,
            tag_robust=args.tag_robust,
            tag_combined=args.tag_combined,
            tag_worst_bot=args.tag_worst_bot,
            tag_holdout_hard=args.tag_holdout_hard,
            decaying_tags=list(args.decaying_tags),
            enable_schedule_diagnostics=bool(args.enable_schedule_diagnostics),
            diag_fast_consumption_at_40=float(args.diag_fast_consumption_at_40),
            diag_slow_consumption_at_80=float(args.diag_slow_consumption_at_80),
            min_evals=args.min_evals,
        )
        seed_rows.append(summary)

    aggregate = compute_aggregate(seed_rows)
    print_console_report(seed_rows, aggregate)

    archive_target_dir: Optional[Path] = None
    if args.archive_runs_root:
        archive_target_dir = _next_batch_dir(
            parent_dir=runs_root.parent,
            prefix=str(args.archive_prefix),
            width=int(args.archive_width),
        )

    if args.out_prefix:
        out_prefix = Path(args.out_prefix).resolve()
    else:
        if archive_target_dir is not None:
            batch_token = _extract_batch_token(archive_target_dir.name)
            out_prefix = (runs_root.parent / "reports" / f"{batch_token}_coreagent").resolve()
        else:
            out_prefix = (runs_root / "seed_aggregate").resolve()

    write_outputs(out_prefix, seed_rows, aggregate, args)

    if args.archive_runs_root:
        if archive_target_dir is None:
            raise RuntimeError("archive target directory should not be None when archive is enabled")
        archive_runs_root_to(runs_root=runs_root, dst_dir=archive_target_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
