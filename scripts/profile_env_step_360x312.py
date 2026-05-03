#!/usr/bin/env python3
"""
Profile env.step latency on the 360x312 scenario map.

Usage:
  ./.venv/bin/python scripts/profile_env_step_360x312.py
  ./.venv/bin/python scripts/profile_env_step_360x312.py --measured-steps 1500 --warmup-steps 100
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

import numpy as np

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry
from shared.data_validation import require_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure env.step latency (p50/p95/p99) on scenario_pvp_test (360x312)."
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--warmup-steps", type=int, default=50, help="Warmup steps before measurement")
    parser.add_argument("--measured-steps", type=int, default=300, help="Measured step count")
    parser.add_argument(
        "--scenario-file",
        type=str,
        default="config/scenario_pvp_test.json",
        help="Scenario JSON file path",
    )
    parser.add_argument("--agent-key", type=str, default="CoreAgent", help="Agent key for configs")
    return parser.parse_args()


def _pick_valid_action(env: Any, rng: np.random.Generator) -> int:
    mask = env.get_action_mask()
    valid = np.flatnonzero(mask)
    if valid.size == 0:
        raise ValueError("Action mask has no valid action")
    return int(rng.choice(valid))


def main() -> None:
    args = parse_args()
    if args.warmup_steps < 0:
        raise ValueError("warmup-steps must be >= 0")
    if args.measured_steps <= 0:
        raise ValueError("measured-steps must be > 0")

    W40KEngine, _ = setup_imports()
    env = W40KEngine(
        rewards_config=args.agent_key,
        training_config_name="default",
        controlled_agent=args.agent_key,
        scenario_file=args.scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )

    rng = np.random.default_rng(args.seed)
    obs, _ = env.reset(seed=args.seed)

    for _ in range(args.warmup_steps):
        action = _pick_valid_action(env, rng)
        obs, _reward, terminated, truncated, _info = env.step(action)
        if terminated or truncated:
            obs, _ = env.reset()

    step_durations_ms = []
    resets = 0
    for _ in range(args.measured_steps):
        action = _pick_valid_action(env, rng)
        t0 = time.perf_counter()
        obs, _reward, terminated, truncated, _info = env.step(action)
        step_durations_ms.append((time.perf_counter() - t0) * 1000.0)
        if terminated or truncated:
            resets += 1
            obs, _ = env.reset()

    arr = np.array(step_durations_ms, dtype=np.float64)
    game_state = require_key(env.__dict__, "game_state")
    cols = require_key(game_state, "cols")
    rows = require_key(game_state, "rows")

    result: Dict[str, Any] = {
        "scenario_file": args.scenario_file,
        "board_dims": [int(cols), int(rows)],
        "inches_to_subhex": game_state.get("inches_to_subhex"),
        "seed": args.seed,
        "warmup_steps": args.warmup_steps,
        "measured_steps": args.measured_steps,
        "episode_resets": resets,
        "step_ms": {
            "mean": float(arr.mean()),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(arr.max()),
            "min": float(arr.min()),
            "stdev": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        },
        "sps_step_only": float(1000.0 / arr.mean()),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
