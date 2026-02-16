#!/usr/bin/env python3
"""
CPU scaling benchmark for ai/train.py.

Goal:
- Compare multiple n_envs values on CPU
- Keep command/agent/config fixed
- Report episodes/sec and elapsed time
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


EP_S_REGEX = re.compile(r"([0-9]+(?:\.[0-9]+)?)ep/s")


@dataclass
class ScalingResult:
    n_envs: int
    returncode: int
    elapsed_seconds: float
    episodes: int
    avg_ep_per_sec: float
    last_reported_ep_per_sec: Optional[float]
    log_path: Path


def _read_models_root(repo_root: Path) -> Path:
    config_path = repo_root / "config" / "config.json"
    with config_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    paths = cfg.get("paths")
    if not isinstance(paths, dict) or "models_root" not in paths:
        raise KeyError("config/config.json missing required paths.models_root")
    return repo_root / str(paths["models_root"])


def _model_path(repo_root: Path, agent_key: str) -> Path:
    models_root = _read_models_root(repo_root)
    return models_root / agent_key / f"model_{agent_key}.zip"


def _extract_last_ep_per_sec(output_text: str) -> Optional[float]:
    matches = EP_S_REGEX.findall(output_text)
    if not matches:
        return None
    return float(matches[-1])


def _build_env(threads_one: bool) -> dict[str, str]:
    env = os.environ.copy()
    if threads_one:
        env["OMP_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["NUMEXPR_NUM_THREADS"] = "1"
    return env


def _run_one(
    repo_root: Path,
    python_exe: str,
    agent: str,
    training_config: str,
    rewards_config: str,
    scenario: str,
    episodes: int,
    n_envs: int,
    threads_one: bool,
    extra_params: list[tuple[str, str]],
) -> ScalingResult:
    cmd = [
        python_exe,
        "ai/train.py",
        "--agent",
        agent,
        "--training-config",
        training_config,
        "--rewards-config",
        rewards_config,
        "--scenario",
        scenario,
        "--new",
        "--total-episodes",
        str(episodes),
        "--mode",
        "CPU",
        "--param",
        "n_envs",
        str(n_envs),
    ]
    for key, value in extra_params:
        cmd.extend(["--param", key, value])

    print(f"\n=== n_envs={n_envs} ===")
    print(" ".join(cmd))

    log_path = repo_root / "scripts" / f"benchmark_cpu_nenvs_{n_envs}.log"
    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=_build_env(threads_one),
    )
    elapsed = time.time() - start
    log_path.write_text(proc.stdout, encoding="utf-8")

    avg_ep_per_sec = episodes / elapsed if elapsed > 0 else 0.0
    last_ep_s = _extract_last_ep_per_sec(proc.stdout)
    return ScalingResult(
        n_envs=n_envs,
        returncode=proc.returncode,
        elapsed_seconds=elapsed,
        episodes=episodes,
        avg_ep_per_sec=avg_ep_per_sec,
        last_reported_ep_per_sec=last_ep_s,
        log_path=log_path,
    )


def _print_summary(results: list[ScalingResult]) -> None:
    print("\n=== CPU scaling summary ===")
    print(
        f"{'n_envs':>7} | {'rc':>2} | {'elapsed(s)':>10} | {'avg_ep/s':>8} | {'last_ep/s':>9} | log"
    )
    print("-" * 90)
    for r in results:
        last_val = "n/a" if r.last_reported_ep_per_sec is None else f"{r.last_reported_ep_per_sec:.3f}"
        print(
            f"{r.n_envs:7d} | {r.returncode:2d} | {r.elapsed_seconds:10.2f} | "
            f"{r.avg_ep_per_sec:8.3f} | {last_val:>9} | {r.log_path}"
        )

    valid = [r for r in results if r.returncode == 0]
    if not valid:
        print("\nAll runs failed. Check logs.")
        return

    best = sorted(valid, key=lambda x: x.avg_ep_per_sec, reverse=True)[0]
    print(
        f"\nBest n_envs by avg episodes/s: {best.n_envs} "
        f"({best.avg_ep_per_sec:.3f} ep/s)"
    )


def _parse_nenvs_list(raw: str) -> list[int]:
    values: list[int] = []
    for item in raw.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        val = int(stripped)
        if val <= 0:
            raise ValueError(f"n_envs must be > 0 (got {val})")
        values.append(val)
    if not values:
        raise ValueError("No n_envs provided")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark CPU scaling by n_envs for ai/train.py")
    parser.add_argument("--agent", required=True, help="Agent key")
    parser.add_argument("--training-config", default="default", help="Training config name")
    parser.add_argument("--rewards-config", required=True, help="Rewards config name")
    parser.add_argument("--scenario", default="bot", help="Scenario option for ai/train.py")
    parser.add_argument("--episodes", type=int, default=200, help="Episodes per n_envs run")
    parser.add_argument(
        "--n-envs-list",
        default="8,16,24,32,40,48",
        help="Comma-separated n_envs values to benchmark",
    )
    parser.add_argument(
        "--threads-one",
        action="store_true",
        help="Force OMP/MKL/OPENBLAS/NUMEXPR threads to 1 during runs",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable")
    parser.add_argument(
        "--param",
        action="append",
        nargs=2,
        metavar=("KEY", "VALUE"),
        default=[],
        help="Additional --param key value passed to ai/train.py (repeatable)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    nenvs_values = _parse_nenvs_list(args.n_envs_list)

    model_file = _model_path(repo_root, args.agent)
    backup_path: Optional[Path] = None
    created_new_model = False
    if model_file.exists():
        fd, tmp_name = tempfile.mkstemp(prefix="model_backup_scale_", suffix=".zip")
        os.close(fd)
        backup_path = Path(tmp_name)
        shutil.copy2(model_file, backup_path)
        print(f"Backed up model to: {backup_path}")
    else:
        created_new_model = True

    results: list[ScalingResult] = []
    try:
        for n_envs in nenvs_values:
            result = _run_one(
                repo_root=repo_root,
                python_exe=args.python,
                agent=args.agent,
                training_config=args.training_config,
                rewards_config=args.rewards_config,
                scenario=args.scenario,
                episodes=args.episodes,
                n_envs=n_envs,
                threads_one=args.threads_one,
                extra_params=[(k, v) for k, v in args.param],
            )
            results.append(result)

        _print_summary(results)
        return 0 if all(r.returncode == 0 for r in results) else 1
    finally:
        if backup_path is not None and backup_path.exists():
            model_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, model_file)
            backup_path.unlink(missing_ok=True)
            print(f"Restored original model: {model_file}")
        elif created_new_model and model_file.exists():
            model_file.unlink()
            print(f"Removed benchmark-created model: {model_file}")


if __name__ == "__main__":
    raise SystemExit(main())
