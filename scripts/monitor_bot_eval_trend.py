#!/usr/bin/env python3
"""
Monitor bot_eval trend from TensorBoard event files and optionally stop training.

Example:
  python scripts/monitor_bot_eval_trend.py \
    --logdir ./tensorboard/default_SpaceMarine_Infantry_Troop_RangedSwarm \
    --pid 12345 \
    --kill-on-stop
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator


DEFAULT_TAG = "0_critical/a_bot_eval_combined"


@dataclass
class ScalarPoint:
    step: int
    value: float
    wall_time: float


def _collect_event_files(logdir: Path) -> List[Path]:
    return sorted(logdir.rglob("events.out.tfevents.*"))


def _read_tag_points(logdir: Path, tag: str) -> List[ScalarPoint]:
    files = _collect_event_files(logdir)
    merged: Dict[Tuple[int, float], ScalarPoint] = {}

    for event_file in files:
        try:
            accumulator = EventAccumulator(str(event_file), size_guidance={"scalars": 0})
            accumulator.Reload()
            tags = accumulator.Tags().get("scalars", [])
            if tag not in tags:
                continue
            scalars = accumulator.Scalars(tag)
            for s in scalars:
                key = (int(s.step), float(s.wall_time))
                merged[key] = ScalarPoint(step=int(s.step), value=float(s.value), wall_time=float(s.wall_time))
        except Exception:
            # Keep monitor alive despite partial/corrupted files.
            continue

    points = list(merged.values())
    points.sort(key=lambda p: (p.step, p.wall_time))
    return points


def _window_points(points: List[ScalarPoint], window_episodes: int) -> List[ScalarPoint]:
    if not points:
        return []
    last_step = points[-1].step
    # Add an adaptive slack equal to one median logging interval.
    # Reason: bot_eval points are often logged every ~500 episodes, and with
    # non-exact steps (e.g. 2501, 3002) a strict [last-window, last] can drop
    # one point unexpectedly and prevent min_points from being reached.
    positive_deltas = [
        points[i].step - points[i - 1].step
        for i in range(1, len(points))
        if points[i].step > points[i - 1].step
    ]
    interval_slack = int(np.median(positive_deltas)) if positive_deltas else 0
    min_step = max(0, last_step - window_episodes - interval_slack)
    return [p for p in points if p.step >= min_step]


def _compute_slope(points: List[ScalarPoint]) -> Optional[float]:
    if len(points) < 2:
        return None
    x = np.array([p.step for p in points], dtype=np.float64)
    y = np.array([p.value for p in points], dtype=np.float64)
    if np.allclose(x, x[0]):
        return None
    coeff = np.polyfit(x, y, 1)
    return float(coeff[0])


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_pid(pid: int, grace_seconds: int = 10) -> None:
    if not _is_pid_alive(pid):
        return
    print(f"🛑 Sending SIGTERM to PID {pid}")
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            print(f"✅ PID {pid} terminated gracefully")
            return
        time.sleep(0.5)
    if _is_pid_alive(pid):
        print(f"⚠️ PID {pid} still alive after {grace_seconds}s, sending SIGKILL")
        os.kill(pid, signal.SIGKILL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor bot_eval trend and optionally auto-stop training")
    parser.add_argument("--logdir", required=True, help="TensorBoard log directory to monitor")
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"Scalar tag to monitor (default: {DEFAULT_TAG})")
    parser.add_argument("--pid", type=int, default=None, help="Training process PID to terminate on stop condition")
    parser.add_argument("--kill-on-stop", action="store_true", help="Terminate --pid when stop condition is met")
    parser.add_argument("--window-episodes", type=int, default=2000, help="Sliding window width in episode-steps")
    parser.add_argument("--min-points", type=int, default=5, help="Minimum points required to compute trend")
    parser.add_argument("--slope-warn", type=float, default=-0.002, help="Warning threshold for slope")
    parser.add_argument("--slope-stop", type=float, default=-0.004, help="Stop threshold for slope")
    parser.add_argument("--consecutive-stop", type=int, default=3, help="Consecutive stop windows required")
    parser.add_argument("--min-episodes-before-check", type=int, default=8000, help="Ignore stop checks before this step")
    parser.add_argument("--poll-seconds", type=int, default=30, help="Polling interval in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logdir = Path(args.logdir).resolve()
    if not logdir.exists():
        raise FileNotFoundError(f"logdir does not exist: {logdir}")

    if args.kill_on_stop and args.pid is None:
        raise ValueError("--kill-on-stop requires --pid")

    print("📈 Bot eval trend monitor started")
    print(f"   logdir: {logdir}")
    print(f"   tag: {args.tag}")
    print(f"   window_episodes: {args.window_episodes}")
    print(f"   slope_warn: {args.slope_warn}")
    print(f"   slope_stop: {args.slope_stop}")
    print(f"   consecutive_stop: {args.consecutive_stop}")
    print(f"   min_episodes_before_check: {args.min_episodes_before_check}")
    if args.kill_on_stop:
        print(f"   auto-kill PID: {args.pid}")

    last_seen_step = -1
    consecutive_stop_hits = 0

    while True:
        points = _read_tag_points(logdir, args.tag)
        if not points:
            print("⏳ Waiting for metric points...")
            time.sleep(args.poll_seconds)
            continue

        latest = points[-1]
        if latest.step == last_seen_step:
            time.sleep(args.poll_seconds)
            continue
        last_seen_step = latest.step

        win_points = _window_points(points, args.window_episodes)
        slope = _compute_slope(win_points)
        if slope is None or len(win_points) < args.min_points:
            print(
                f"ℹ️ step={latest.step} value={latest.value:.4f} "
                f"(insufficient points: {len(win_points)}/{args.min_points})"
            )
            time.sleep(args.poll_seconds)
            continue

        status = "OK"
        if slope <= args.slope_stop and latest.step >= args.min_episodes_before_check:
            consecutive_stop_hits += 1
            status = f"STOP_CANDIDATE[{consecutive_stop_hits}/{args.consecutive_stop}]"
        else:
            if slope <= args.slope_warn:
                status = "WARN"
            consecutive_stop_hits = 0

        print(
            f"step={latest.step} value={latest.value:.4f} "
            f"slope={slope:.6f} points={len(win_points)} status={status}"
        )

        if consecutive_stop_hits >= args.consecutive_stop:
            print("🟥 Stop condition reached: persistent negative trend.")
            if args.kill_on_stop and args.pid is not None:
                _terminate_pid(args.pid)
            return 0

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
        raise SystemExit(130)
