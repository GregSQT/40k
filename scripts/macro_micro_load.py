#!/usr/bin/env python3
"""
scripts/macro_micro_load.py

Simulate macro/micro agent workload to benchmark CPU/RAM/Network.

Macro:
  - Selects which unit acts by reordering the activation pool.
Micro:
  - Executes one valid action from the action mask (random policy).

This script is intended for load testing and capacity planning.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import resource
import sys
import time
import tracemalloc
from typing import Dict, List, Optional, Tuple

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config_loader import get_config_loader
from shared.data_validation import require_key
from ai.unit_registry import UnitRegistry
from engine.w40k_core import W40KEngine


def _read_proc_self_io() -> Dict[str, int]:
    """Read per-process IO counters from /proc/self/io (Linux only)."""
    io_path = "/proc/self/io"
    data: Dict[str, int] = {}
    if not os.path.exists(io_path):
        return data
    with open(io_path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            value = parts[1].strip()
            if value.isdigit():
                data[key] = int(value)
    return data


def _read_proc_net_dev() -> Tuple[int, int]:
    """Read system-wide RX/TX bytes from /proc/net/dev (Linux only)."""
    net_path = "/proc/net/dev"
    if not os.path.exists(net_path):
        return 0, 0
    rx_total = 0
    tx_total = 0
    with open(net_path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in lines[2:]:
        if ":" not in line:
            continue
        _, data = line.split(":", 1)
        fields = data.split()
        if len(fields) < 10:
            continue
        rx_total += int(fields[0])
        tx_total += int(fields[8])
    return rx_total, tx_total


def _capture_metrics_snapshot() -> Dict[str, float]:
    """Capture a metrics snapshot for delta computation."""
    ru_self = resource.getrusage(resource.RUSAGE_SELF)
    io_data = _read_proc_self_io()
    rx_bytes, tx_bytes = _read_proc_net_dev()
    return {
        "wall_time": time.time(),
        "cpu_time": time.process_time(),
        "max_rss_kb": float(ru_self.ru_maxrss),
        "io_read_bytes": float(io_data.get("read_bytes", 0)),
        "io_write_bytes": float(io_data.get("write_bytes", 0)),
        "net_rx_bytes": float(rx_bytes),
        "net_tx_bytes": float(tx_bytes),
    }


def _delta_metrics(start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
    """Compute deltas between two snapshots."""
    return {
        "wall_time_sec": end["wall_time"] - start["wall_time"],
        "cpu_time_sec": end["cpu_time"] - start["cpu_time"],
        "max_rss_kb": end["max_rss_kb"],
        "io_read_bytes": end["io_read_bytes"] - start["io_read_bytes"],
        "io_write_bytes": end["io_write_bytes"] - start["io_write_bytes"],
        "net_rx_bytes": end["net_rx_bytes"] - start["net_rx_bytes"],
        "net_tx_bytes": end["net_tx_bytes"] - start["net_tx_bytes"],
    }


def _get_activation_pool(game_state: dict) -> List[str]:
    """
    Return the active activation pool based on the current phase/subphase.
    Raises if required data is missing to avoid silent fallbacks.
    """
    phase = require_key(game_state, "phase")
    if phase == "move":
        return require_key(game_state, "move_activation_pool")
    if phase == "shoot":
        return require_key(game_state, "shoot_activation_pool")
    if phase == "charge":
        return require_key(game_state, "charge_activation_pool")
    if phase == "fight":
        fight_subphase = require_key(game_state, "fight_subphase")
        if fight_subphase in ("charging",):
            return require_key(game_state, "charging_activation_pool")
        if fight_subphase in ("alternating_non_active", "cleanup_non_active"):
            return require_key(game_state, "non_active_alternating_activation_pool")
        if fight_subphase in ("alternating_active", "cleanup_active"):
            return require_key(game_state, "active_alternating_activation_pool")
        raise ValueError(f"Unsupported fight_subphase: {fight_subphase}")
    raise ValueError(f"Unsupported phase: {phase}")


def _prioritize_unit_in_pool(pool: List[str], unit_id: str) -> List[str]:
    """Move unit_id to the front of the pool (if present)."""
    if unit_id not in pool:
        return pool
    new_pool = [unit_id] + [u for u in pool if u != unit_id]
    return new_pool


def _select_random_action(mask) -> int:
    """Select a random valid action index from an action mask."""
    valid_indices = [i for i, allowed in enumerate(mask) if allowed]
    if not valid_indices:
        raise ValueError("No valid actions in action mask")
    return random.choice(valid_indices)


def run_episode(
    engine: W40KEngine,
    macro_player: int,
    macro_every_steps: int,
    max_steps_per_turn: Optional[int],
    macro_both: bool,
) -> int:
    """Run a single episode and return the step count."""
    engine.reset()
    steps = 0
    while True:
        game_state = require_key(engine.__dict__, "game_state")
        current_player = require_key(game_state, "current_player")
        if game_state.get("game_over"):
            break

        if max_steps_per_turn is not None and steps >= max_steps_per_turn:
            break

        should_apply_macro = (
            macro_both or current_player == macro_player
        ) and (steps % macro_every_steps == 0)

        if should_apply_macro:
            pool = _get_activation_pool(game_state)
            if pool:
                phase = require_key(game_state, "phase")
                if phase == "shoot" and game_state.get("active_shooting_unit") is not None:
                    active_unit = str(game_state["active_shooting_unit"])
                    updated_pool = _prioritize_unit_in_pool(pool, active_unit)
                else:
                    chosen_unit = random.choice(pool)
                    updated_pool = _prioritize_unit_in_pool(pool, chosen_unit)
                if phase == "move":
                    game_state["move_activation_pool"] = updated_pool
                elif phase == "shoot":
                    game_state["shoot_activation_pool"] = updated_pool
                elif phase == "charge":
                    game_state["charge_activation_pool"] = updated_pool
                elif phase == "fight":
                    fight_subphase = require_key(game_state, "fight_subphase")
                    if fight_subphase in ("charging",):
                        game_state["charging_activation_pool"] = updated_pool
                    elif fight_subphase in ("alternating_non_active", "cleanup_non_active"):
                        game_state["non_active_alternating_activation_pool"] = updated_pool
                    elif fight_subphase in ("alternating_active", "cleanup_active"):
                        game_state["active_alternating_activation_pool"] = updated_pool
                    else:
                        raise ValueError(f"Unsupported fight_subphase: {fight_subphase}")
                else:
                    raise ValueError(f"Unsupported phase: {phase}")

        mask = engine.get_action_mask()
        action = _select_random_action(mask)
        _, _, terminated, truncated, _ = engine.step(action)
        steps += 1
        if terminated or truncated:
            break
    return steps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Macro/Micro load simulation")
    parser.add_argument("--scenario-file", action="append", required=True, help="Scenario JSON file path (repeatable)")
    parser.add_argument("--rewards-config", required=True, help="Rewards config name")
    parser.add_argument("--training-config", required=True, help="Training config name")
    parser.add_argument("--controlled-agent", required=True, help="Controlled agent key")
    parser.add_argument("--episodes", type=int, required=True, help="Number of episodes to run")
    parser.add_argument("--macro-player", type=int, choices=[1, 2], required=True, help="Player controlled by macro")
    parser.add_argument("--macro-every-steps", type=int, required=True, help="Apply macro selection every N steps")
    parser.add_argument("--macro-both", action="store_true", help="Apply macro selection to both players")
    parser.add_argument("--max-steps-per-turn", type=int, help="Max steps per turn")
    parser.add_argument("--metrics-out", help="Write metrics summary to JSON file")
    parser.add_argument("--seed", type=int, help="Random seed")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.macro_every_steps <= 0:
        raise ValueError("macro-every-steps must be > 0")
    if args.seed is not None:
        random.seed(args.seed)

    registry = UnitRegistry()
    config_loader = get_config_loader()
    game_config = config_loader.get_game_config()
    game_rules = require_key(game_config, "game_rules")
    default_max_steps_per_turn = require_key(game_rules, "max_steps_per_turn")
    scenario_files = args.scenario_file
    scenario_file = scenario_files[0] if len(scenario_files) == 1 else None

    engine = W40KEngine(
        rewards_config=args.rewards_config,
        training_config_name=args.training_config,
        controlled_agent=args.controlled_agent,
        scenario_file=scenario_file,
        scenario_files=scenario_files if len(scenario_files) > 1 else None,
        unit_registry=registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=False,
    )

    total_steps = 0
    tracemalloc.start()
    metrics_start = _capture_metrics_snapshot()
    for ep in range(1, args.episodes + 1):
        steps = run_episode(
            engine=engine,
            macro_player=args.macro_player,
            macro_every_steps=args.macro_every_steps,
            max_steps_per_turn=(
                args.max_steps_per_turn if args.max_steps_per_turn is not None else default_max_steps_per_turn
            ),
            macro_both=args.macro_both,
        )
        total_steps += steps
        print(f"[episode {ep}] steps={steps}")
    metrics_end = _capture_metrics_snapshot()
    metrics_delta = _delta_metrics(metrics_start, metrics_end)
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if metrics_delta["wall_time_sec"] <= 0:
        raise ValueError("Elapsed time must be > 0")
    steps_per_sec = total_steps / metrics_delta["wall_time_sec"]
    max_rss_mb = metrics_delta["max_rss_kb"] / 1024
    py_peak_mb = peak_mem / (1024 * 1024)
    io_read_mb = metrics_delta["io_read_bytes"] / (1024 * 1024)
    io_write_mb = metrics_delta["io_write_bytes"] / (1024 * 1024)
    net_rx_mb = metrics_delta["net_rx_bytes"] / (1024 * 1024)
    net_tx_mb = metrics_delta["net_tx_bytes"] / (1024 * 1024)
    print("--------------------------")
    print(f"CPU time : {metrics_delta['cpu_time_sec']:.2f} seconds")
    print(f"RAM max : {max_rss_mb:.2f} Mb")
    print(f"Disk read : {io_read_mb:.2f} Mb")
    print(f"Disk write : {io_write_mb:.2f} Mb")
    print(f"Network download : {net_rx_mb:.2f} Mb")
    print(f"Network upload : {net_tx_mb:.2f} Mb")
    if args.metrics_out:
        payload = {
            "episodes": args.episodes,
            "total_steps": total_steps,
            "steps_per_sec": steps_per_sec,
            "metrics": metrics_delta,
            "python_memory_peak_kb": peak_mem / 1024,
        }
        with open(args.metrics_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


if __name__ == "__main__":
    main()
