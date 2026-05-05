#!/usr/bin/env python3
"""
Profile env.step latency on the 360x312 scenario map.

Usage (from repo root):
  ./.venv/bin/python scripts/profile_env_step_360x312.py
  ./.venv/bin/python scripts/profile_env_step_360x312.py --measured-steps 500 --warmup-steps 100
  ./.venv/bin/python scripts/profile_env_step_360x312.py --per-step --top-slow 0
  ./.venv/bin/python scripts/profile_env_step_360x312.py --no-progress   # JSON only (no bar on stderr)
  ./.venv/bin/python scripts/profile_env_step_360x312.py --profile-goulots  # + cProfile replay (2e passe, barre tqdm "cprofile-replay")

  # JSON dans un fichier tout en gardant les barres tqdm dans le terminal (bash) :
  #   ./.venv/bin/python scripts/profile_env_step_360x312.py ... > profile_result.json 2> >(tee profile_stderr.txt >&2)
  # Sans tee : rediriger 2> fichier envoie tqdm dans le fichier seulement (tail -f profile_stderr.txt dans un autre terminal).

Progress bar (tqdm) goes to stderr; JSON result stays on stdout for piping.

Project root is prepended to sys.path so imports resolve without PYTHONPATH.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import marshal
import os
import pstats
import sys
import time
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Sequence, Tuple

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import numpy as np
from tqdm import tqdm

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry
from shared.data_validation import require_key

# Quatre goulots identifiés sur scenario_pvp_test (rapport by_phase_action trié p95).
GOULOT_SPECS: Tuple[Tuple[str, int, str], ...] = (
    ("move", 3, "move_objective"),
    ("fight", 10, "fight"),
    ("charge", 9, "charge_activate"),
    ("move", 0, "move_aggressive"),
)

_MS_HIST_EDGES: Tuple[float, ...] = (0.0, 50.0, 200.0, 500.0, 1000.0, 5000.0, 20000.0, float("inf"))
_MS_HIST_LABELS: Tuple[str, ...] = (
    "0-50",
    "50-200",
    "200-500",
    "500-1k",
    "1k-5k",
    "5k-20k",
    "20k+",
)


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
    parser.add_argument(
        "--per-step",
        action="store_true",
        help="Include full list of {phase, action, label, ms} per measured step (large JSON).",
    )
    parser.add_argument(
        "--top-slow",
        type=int,
        default=20,
        metavar="N",
        help="Include N slowest steps (0 to disable). Default 20.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable tqdm progress bar (stderr).",
    )
    parser.add_argument(
        "--profile-goulots",
        action="store_true",
        help=(
            "After the timed run, replay the same action sequence once and accumulate cProfile "
            "per goulot (move:3, fight:10, charge:9, move:0). Does not change the engine; doubles work. "
            "Shows a second tqdm bar on stderr (desc=cprofile-replay) unless --no-progress."
        ),
    )
    parser.add_argument(
        "--goulot-cprofile-top",
        type=int,
        default=30,
        metavar="N",
        help="Number of Python functions to report per goulot (cumulative time). Default 30.",
    )
    parser.add_argument(
        "--goulot-slowest-in-bucket",
        type=int,
        default=8,
        metavar="N",
        help="Per goulot, keep N slowest samples from the measured phase. Default 8.",
    )
    return parser.parse_args()


def _pick_valid_action(env: Any, rng: np.random.Generator) -> int:
    mask = env.get_action_mask()
    valid = np.flatnonzero(mask)
    if valid.size == 0:
        raise ValueError("Action mask has no valid action")
    return int(rng.choice(valid))


def _action_label(phase: str, action: int, game_state: Dict[str, Any]) -> str:
    """
    Human-readable action label aligned with engine/action_decoder.py semantics.
    Charge indices 4–8 depend on pending_charge_targets vs valid_charge_destinations_pool.
    """
    if phase == "deployment" and 4 <= action <= 8:
        return f"deployment_hex_slot_{action - 4}"
    if phase == "command" and action == 11:
        return "command_wait"
    if phase == "move":
        if action == 0:
            return "move_aggressive"
        if action == 1:
            return "move_tactical"
        if action == 2:
            return "move_defensive"
        if action == 3:
            return "move_objective"
        if action == 11:
            return "move_wait"
    if phase == "shoot":
        if 4 <= action <= 8:
            return f"shoot_target_slot_{action - 4}"
        if action == 11:
            return "shoot_wait"
        if action == 12:
            return "shoot_advance"
    if phase == "charge":
        if action == 9:
            return "charge_activate"
        if action == 11:
            return "charge_wait"
        if 4 <= action <= 8:
            if game_state.get("pending_charge_targets"):
                return f"charge_target_slot_{action - 4}"
            if game_state.get("valid_charge_destinations_pool"):
                return f"charge_dest_slot_{action - 4}"
            return f"charge_slot_{action - 4}_ambiguous"
    if phase == "fight" and action == 10:
        return "fight"
    return f"{phase}_action_{action}"


def _bucket_stats(ms_values: List[float]) -> Dict[str, float]:
    arr = np.array(ms_values, dtype=np.float64)
    out: Dict[str, float] = {
        "mean_ms": float(arr.mean()),
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "max_ms": float(arr.max()),
        "min_ms": float(arr.min()),
    }
    if arr.size > 1:
        out["stdev_ms"] = float(arr.std(ddof=1))
        mean = float(arr.mean())
        out["cv"] = float(out["stdev_ms"] / mean) if mean > 0.0 else 0.0
    else:
        out["stdev_ms"] = 0.0
        out["cv"] = 0.0
    return out


def _histogram_ms(ms_values: Sequence[float]) -> Dict[str, int]:
    counts = {label: 0 for label in _MS_HIST_LABELS}
    for ms in ms_values:
        for i in range(len(_MS_HIST_EDGES) - 1):
            lo, hi = _MS_HIST_EDGES[i], _MS_HIST_EDGES[i + 1]
            if lo <= ms < hi:
                counts[_MS_HIST_LABELS[i]] += 1
                break
    return counts


def _top_cum_functions(profile: cProfile.Profile, limit: int) -> List[Dict[str, Any]]:
    # Fichier temporaire explicite ; Stats lit le marshal de dump_stats.
    # Si aucun échantillon (profil vide), marshal = {} et pstats lève un TypeError peu clair — on renvoie [].
    prof_path = os.path.join(
        _project_root,
        f"goulot_cprofile_{os.getpid()}_{time.time_ns()}.prof",
    )
    profile.dump_stats(prof_path)
    try:
        with open(prof_path, "rb") as f:
            loaded = marshal.load(f)
        if not loaded:
            return []
        stats = pstats.Stats(prof_path)
    finally:
        if os.path.isfile(prof_path):
            os.remove(prof_path)
    if not stats.stats:
        return []
    stats.strip_dirs()
    rows: List[Tuple[float, int, str]] = []
    for (fname, line, func), (_cc, nc, _tt, ct, _callers) in stats.stats.items():
        rows.append((float(ct), int(nc), f"{fname}:{line}:{func}"))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [{"cumtime_s": r[0], "ncalls": r[1], "where": r[2]} for r in rows[:limit]]


def _build_goulot_detail(
    per_step: List[Dict[str, Any]],
    total_measured_wall_ms: float,
    slowest_in_bucket: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for phase, action, expected_label in GOULOT_SPECS:
        key_id = f"{phase}:{action}"
        matching = [r for r in per_step if str(r["phase"]) == phase and int(r["action"]) == action]
        ms_list = [float(r["ms"]) for r in matching]
        share = (sum(ms_list) / total_measured_wall_ms) if total_measured_wall_ms > 0.0 else 0.0
        label_mismatch = sum(1 for r in matching if str(r["label"]) != expected_label)
        slow_in = sorted(matching, key=lambda r: float(r["ms"]), reverse=True)[:slowest_in_bucket]

        block: Dict[str, Any] = {
            "id": key_id,
            "expected_label": expected_label,
            "samples": len(ms_list),
            "label_mismatch_count": int(label_mismatch),
            "share_of_measured_wall_time": float(share),
            "histogram_ms": _histogram_ms(ms_list),
        }
        if ms_list:
            block["wall_ms"] = _bucket_stats(ms_list)
            block["slowest_in_bucket"] = [
                {"phase": r["phase"], "action": r["action"], "label": r["label"], "ms": float(r["ms"])}
                for r in slow_in
            ]
        else:
            block["wall_ms"] = None
            block["slowest_in_bucket"] = []

        out.append(block)
    return out


def _make_env(args: argparse.Namespace, W40KEngine: Any) -> Any:
    return W40KEngine(
        rewards_config=args.agent_key,
        training_config_name="default",
        controlled_agent=args.agent_key,
        scenario_file=args.scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )


def _replay_and_profile_goulots(
    args: argparse.Namespace,
    W40KEngine: Any,
    action_trail: List[int],
    warmup_steps: int,
    measured_steps: int,
    top_n: int,
) -> Dict[str, Any]:
    if len(action_trail) != warmup_steps + measured_steps:
        raise ValueError(
            f"action_trail length {len(action_trail)} != warmup_steps+measured_steps={warmup_steps + measured_steps}"
        )

    profiles: Dict[Tuple[str, int], cProfile.Profile] = {
        (p, a): cProfile.Profile() for p, a, _ in GOULOT_SPECS
    }

    env = _make_env(args, W40KEngine)
    env.reset(seed=args.seed)

    progress_disable = bool(args.no_progress)
    with tqdm(
        total=len(action_trail),
        desc="cprofile-replay",
        unit="step",
        file=sys.stderr,
        disable=progress_disable,
        mininterval=0.5,
    ) as pbar:
        for action in action_trail:
            gs = require_key(env.__dict__, "game_state")
            phase = require_key(gs, "phase")
            pair = (str(phase), int(action))
            prof = profiles.get(pair)
            if prof is not None:
                prof.enable()
            try:
                _obs, _r, terminated, truncated, _i = env.step(action)
            finally:
                if prof is not None:
                    prof.disable()
            if terminated or truncated:
                env.reset()
            pbar.update(1)

    report: Dict[str, Any] = {}
    for phase, action, _label in GOULOT_SPECS:
        kid = f"{phase}:{action}"
        prof = profiles[(phase, action)]
        report[kid] = {
            "cprofile_top_cumtime": _top_cum_functions(prof, top_n),
        }
    return report


def main() -> None:
    args = parse_args()
    if args.warmup_steps < 0:
        raise ValueError("warmup-steps must be >= 0")
    if args.measured_steps <= 0:
        raise ValueError("measured-steps must be > 0")
    if args.top_slow < 0:
        raise ValueError("top-slow must be >= 0")
    if args.goulot_cprofile_top < 1:
        raise ValueError("goulot-cprofile-top must be >= 1")
    if args.goulot_slowest_in_bucket < 0:
        raise ValueError("goulot-slowest-in-bucket must be >= 0")

    W40KEngine, _ = setup_imports()
    env = _make_env(args, W40KEngine)

    rng = np.random.default_rng(args.seed)
    obs, _ = env.reset(seed=args.seed)

    action_trail: List[int] = []

    progress_disable = bool(args.no_progress)
    total_steps = int(args.warmup_steps) + int(args.measured_steps)
    with tqdm(
        total=total_steps,
        desc="warmup",
        unit="step",
        file=sys.stderr,
        disable=progress_disable,
        mininterval=0.5,
    ) as pbar:
        for _ in range(args.warmup_steps):
            action = _pick_valid_action(env, rng)
            action_trail.append(action)
            obs, _reward, terminated, truncated, _info = env.step(action)
            if terminated or truncated:
                obs, _ = env.reset()
            pbar.update(1)

        pbar.set_description("measure", refresh=True)

        step_durations_ms: List[float] = []
        per_step: List[Dict[str, Any]] = []
        resets = 0
        for _ in range(args.measured_steps):
            game_state = require_key(env.__dict__, "game_state")
            phase = require_key(game_state, "phase")
            action = _pick_valid_action(env, rng)
            action_trail.append(action)
            label = _action_label(phase, action, game_state)
            t0 = time.perf_counter()
            obs, _reward, terminated, truncated, _info = env.step(action)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            step_durations_ms.append(dt_ms)
            per_step.append({"phase": phase, "action": action, "label": label, "ms": dt_ms})
            if terminated or truncated:
                resets += 1
                obs, _ = env.reset()
            pbar.update(1)

    arr = np.array(step_durations_ms, dtype=np.float64)
    game_state = require_key(env.__dict__, "game_state")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")

    bucket_lists: DefaultDict[Tuple[str, int, str], List[float]] = defaultdict(list)
    for row in per_step:
        key = (str(row["phase"]), int(row["action"]), str(row["label"]))
        bucket_lists[key].append(float(row["ms"]))

    buckets: List[Dict[str, Any]] = []
    for (phase, action, label), ms_list in bucket_lists.items():
        stats = _bucket_stats(ms_list)
        buckets.append(
            {
                "phase": phase,
                "action": action,
                "label": label,
                "count": len(ms_list),
                **stats,
            }
        )
    buckets.sort(key=lambda b: float(b["p95_ms"]), reverse=True)

    total_measured_wall_ms = float(sum(float(r["ms"]) for r in per_step))
    goulot_detail = _build_goulot_detail(
        per_step,
        total_measured_wall_ms,
        args.goulot_slowest_in_bucket,
    )

    result: Dict[str, Any] = {
        "scenario_file": args.scenario_file,
        "board_dims": [int(board_cols), int(board_rows)],
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
        "by_phase_action": buckets,
        "goulot_detail": goulot_detail,
        "goulot_specs": [{"phase": p, "action": a, "label": lbl} for p, a, lbl in GOULOT_SPECS],
        "goulot_metrics_note": (
            "wall_ms / histogram / share / slowest_in_bucket = uniquement les steps de la phase measured. "
            "cprofile_replay (--profile-goulots) rejoue warmup+measured : des entrées cprofile peuvent exister "
            "même si samples==0 pour une combinaison goulot (ex. action surtout au warmup)."
        ),
    }

    if args.top_slow > 0:
        slowest = sorted(per_step, key=lambda r: float(r["ms"]), reverse=True)[: args.top_slow]
        result["slowest_steps"] = slowest

    if args.per_step:
        result["steps"] = per_step

    if args.profile_goulots:
        cprof = _replay_and_profile_goulots(
            args,
            W40KEngine,
            action_trail,
            args.warmup_steps,
            args.measured_steps,
            args.goulot_cprofile_top,
        )
        for block in goulot_detail:
            kid = str(block["id"])
            block["cprofile_replay"] = cprof.get(kid, {"cprofile_top_cumtime": []})

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
