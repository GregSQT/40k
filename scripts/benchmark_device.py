#!/usr/bin/env python3
"""
Benchmark CPU vs GPU training speed for ai/train.py.

This script runs two short training jobs with identical arguments except
`--mode CPU` and `--mode GPU`, then prints a compact comparison.
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
class RunResult:
    mode: str
    command: list[str]
    returncode: int
    elapsed_seconds: float
    episodes: int
    avg_ep_per_sec: float
    last_reported_ep_per_sec: Optional[float]
    output_path: Path


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


def _run_benchmark_mode(
    repo_root: Path,
    python_exe: str,
    mode: str,
    agent: str,
    training_config: str,
    rewards_config: str,
    scenario: str,
    episodes: int,
    extra_args: list[str],
) -> RunResult:
    command = [
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
        mode,
    ]
    command.extend(extra_args)

    print(f"\n=== {mode} benchmark ===")
    print(" ".join(command))

    output_file = repo_root / "scripts" / f"benchmark_{mode.lower()}.log"
    start = time.time()
    proc = subprocess.run(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed = time.time() - start
    output_file.write_text(proc.stdout, encoding="utf-8")

    avg_ep_per_sec = episodes / elapsed if elapsed > 0 else 0.0
    reported_ep_s = _extract_last_ep_per_sec(proc.stdout)
    return RunResult(
        mode=mode,
        command=command,
        returncode=proc.returncode,
        elapsed_seconds=elapsed,
        episodes=episodes,
        avg_ep_per_sec=avg_ep_per_sec,
        last_reported_ep_per_sec=reported_ep_s,
        output_path=output_file,
    )


def _print_summary(cpu: RunResult, gpu: RunResult) -> None:
    print("\n=== Benchmark summary ===")
    print(f"CPU return code: {cpu.returncode}")
    print(f"GPU return code: {gpu.returncode}")
    print(f"CPU elapsed: {cpu.elapsed_seconds:.2f}s")
    print(f"GPU elapsed: {gpu.elapsed_seconds:.2f}s")
    print(f"CPU avg episodes/s: {cpu.avg_ep_per_sec:.3f}")
    print(f"GPU avg episodes/s: {gpu.avg_ep_per_sec:.3f}")
    print(
        "CPU last reported ep/s: "
        + ("n/a" if cpu.last_reported_ep_per_sec is None else f"{cpu.last_reported_ep_per_sec:.3f}")
    )
    print(
        "GPU last reported ep/s: "
        + ("n/a" if gpu.last_reported_ep_per_sec is None else f"{gpu.last_reported_ep_per_sec:.3f}")
    )
    print(f"CPU log: {cpu.output_path}")
    print(f"GPU log: {gpu.output_path}")

    if cpu.returncode != 0 or gpu.returncode != 0:
        print("\nAt least one run failed. Check logs before drawing conclusions.")
        return

    faster = "CPU" if cpu.avg_ep_per_sec >= gpu.avg_ep_per_sec else "GPU"
    speedup = (
        (cpu.avg_ep_per_sec / gpu.avg_ep_per_sec) if faster == "CPU" else (gpu.avg_ep_per_sec / cpu.avg_ep_per_sec)
    )
    print(f"\nRecommended device for this workload: {faster} (x{speedup:.2f} faster by avg episodes/s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark CPU vs GPU for ai/train.py")
    parser.add_argument("--agent", required=True, help="Agent key")
    parser.add_argument("--training-config", default="default", help="Training config name")
    parser.add_argument("--rewards-config", required=True, help="Rewards config name")
    parser.add_argument("--scenario", default="bot", help="Scenario option for ai/train.py")
    parser.add_argument("--episodes", type=int, default=300, help="Episodes per device run")
    parser.add_argument("--python", default=sys.executable, help="Python executable")
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Additional argument passed to ai/train.py (repeatable)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    # Optional model backup/restore to avoid losing current trained model.
    model_file = _model_path(repo_root, args.agent)
    backup_path: Optional[Path] = None
    created_new_model = False
    if model_file.exists():
        fd, tmp_name = tempfile.mkstemp(prefix="model_backup_", suffix=".zip")
        os.close(fd)
        backup_path = Path(tmp_name)
        shutil.copy2(model_file, backup_path)
        print(f"Backed up model to: {backup_path}")
    else:
        created_new_model = True

    try:
        cpu_result = _run_benchmark_mode(
            repo_root=repo_root,
            python_exe=args.python,
            mode="CPU",
            agent=args.agent,
            training_config=args.training_config,
            rewards_config=args.rewards_config,
            scenario=args.scenario,
            episodes=args.episodes,
            extra_args=args.extra_arg,
        )
        gpu_result = _run_benchmark_mode(
            repo_root=repo_root,
            python_exe=args.python,
            mode="GPU",
            agent=args.agent,
            training_config=args.training_config,
            rewards_config=args.rewards_config,
            scenario=args.scenario,
            episodes=args.episodes,
            extra_args=args.extra_arg,
        )
        _print_summary(cpu_result, gpu_result)
        return 0 if cpu_result.returncode == 0 and gpu_result.returncode == 0 else 1
    finally:
        # Restore original model if one existed before benchmark.
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
