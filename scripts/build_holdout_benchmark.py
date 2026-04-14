#!/usr/bin/env python3
"""
Build stable holdout benchmark assets for one agent.

Features:
1) Optionally mirror holdout_regular agent rosters to opponent rosters (common pool).
2) Generate fixed holdout scenarios with explicit roster refs (no *_random roster refs).
3) Optionally regenerate holdout_hard opponent rosters with points budget computed from
   callback_params.holdout_hard_opponent_budget_modifier in training config.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _require_key(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Required key '{key}' is missing")
    return mapping[key]


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _collect_rosters(base_dir: Path, prefix: str) -> List[Path]:
    if not base_dir.exists():
        raise FileNotFoundError(f"Roster directory not found: {base_dir}")
    rosters = [
        p for p in sorted(base_dir.glob(f"{prefix}*.json"), key=lambda p: p.name)
        if "_kpis" not in p.name and "_matchups" not in p.name
    ]
    if len(rosters) == 0:
        raise FileNotFoundError(f"No roster files found in {base_dir} for prefix '{prefix}'")
    return rosters


def _load_training_profile(training_config_path: Path, profile_name: str) -> Dict[str, Any]:
    if not training_config_path.exists():
        raise FileNotFoundError(f"Training config not found: {training_config_path}")
    root = _load_json(training_config_path)
    profile = root.get(profile_name)
    if not isinstance(profile, dict):
        raise KeyError(f"Profile '{profile_name}' not found in {training_config_path}")
    return profile


def _sync_regular_common_pool(agent_key: str, scale: str) -> None:
    agent_regular_dir = PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / "holdout_regular"
    opponent_regular_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / "holdout_regular"
    opponent_regular_dir.mkdir(parents=True, exist_ok=True)

    agent_rosters = _collect_rosters(agent_regular_dir, "agent_holdout_regular_roster_")

    for existing in sorted(opponent_regular_dir.glob("opponent_holdout_regular_roster_*.json"), key=lambda p: p.name):
        existing.unlink()

    for agent_roster in agent_rosters:
        data = _load_json(agent_roster)
        roster_id = data.get("roster_id")
        if not isinstance(roster_id, str):
            raise TypeError(f"roster_id must be string in {agent_roster}")
        data["roster_id"] = roster_id.replace("agent_", "opponent_", 1)
        new_name = agent_roster.name.replace("agent_", "opponent_", 1)
        _write_json(opponent_regular_dir / new_name, data)


def _build_scenarios(
    agent_key: str,
    scale: str,
    split: str,
    count: int,
    wall_ref: str,
    objectives_ref: str,
) -> None:
    if split not in {"holdout_regular", "holdout_hard"}:
        raise ValueError(f"Unsupported split: {split}")
    if count <= 0:
        raise ValueError(f"Scenario count for {split} must be > 0 (got {count})")

    scenario_dir = PROJECT_ROOT / "config" / "agents" / agent_key / "scenarios" / split
    scenario_dir.mkdir(parents=True, exist_ok=True)

    agent_roster_dir = PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / split
    opp_roster_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / split

    agent_rosters = _collect_rosters(agent_roster_dir, f"agent_{split}_roster_")
    opponent_rosters = _collect_rosters(opp_roster_dir, f"opponent_{split}_roster_")

    for idx in range(1, count + 1):
        agent_roster = agent_rosters[(idx - 1) % len(agent_rosters)]
        opponent_roster = opponent_rosters[(idx - 1) % len(opponent_rosters)]
        scenario_payload = {
            "deployment_zone": "hammer",
            "deployment_type": "active",
            "scale": scale,
            "agent_roster_seed": None,
            "agent_roster_ref": f"{split}/{agent_roster.name}",
            "opponent_roster_ref": f"{split}/{opponent_roster.name}",
            "wall_ref": wall_ref,
            "primary_objectives": ["objectives_control"],
            "objectives_ref": objectives_ref,
        }
        scenario_path = scenario_dir / f"scenario_bot-{idx:02d}.json"
        _write_json(scenario_path, scenario_payload)


def _resolve_hard_points_scale(
    profile: Dict[str, Any],
    base_points: int,
    modifier_override: float | None,
) -> int:
    callback_params = _require_key(profile, "callback_params")
    if not isinstance(callback_params, dict):
        raise TypeError("callback_params must be a dictionary")

    modifier_raw = (
        modifier_override
        if modifier_override is not None
        else callback_params.get("holdout_hard_opponent_budget_modifier")
    )
    if not isinstance(modifier_raw, (int, float)):
        raise TypeError(
            "holdout_hard_opponent_budget_modifier must be numeric "
            f"(got {type(modifier_raw).__name__})"
        )
    modifier = float(modifier_raw)
    if modifier <= 0.0:
        raise ValueError(f"holdout_hard_opponent_budget_modifier must be > 0 (got {modifier})")
    return int(round(float(base_points) * modifier))


def _run_hard_opponent_generation(
    hard_points_scale: int,
    hard_num_rosters: int,
    hard_seed: int,
    hard_points_tolerance: int,
    hard_target_tanking_values: str,
    hard_target_tanking_weights: str,
    hard_units_per_roster_values: str,
    hard_units_per_roster_weights: str,
    hard_max_build_attempts: int,
    hard_max_roster_resample_attempts: int,
    hard_max_copies_per_unit: int,
) -> None:
    cmd = [
        "python3",
        "scripts/build_dynamic_rosters.py",
        "--num-rosters", str(hard_num_rosters),
        "--points-scale", str(hard_points_scale),
        "--points-tolerance", str(hard_points_tolerance),
        "--split", "holdout_hard",
        "--roster-prefix", "opponent_holdout_hard_roster",
        "--target-tanking-values", hard_target_tanking_values,
        "--target-tanking-weights", hard_target_tanking_weights,
        "--units-per-roster-values", hard_units_per_roster_values,
        "--units-per-roster-weights", hard_units_per_roster_weights,
        "--max-build-attempts", str(hard_max_build_attempts),
        "--max-roster-resample-attempts", str(hard_max_roster_resample_attempts),
        "--max-copies-per-unit", str(hard_max_copies_per_unit),
        "--seed", str(hard_seed),
    ]
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build stable holdout benchmark assets: common regular pool, fixed scenarios, "
            "and optional hard-opponent roster generation with budget modifier."
        )
    )
    parser.add_argument("--agent", default="CoreAgent")
    parser.add_argument("--profile", default="default", help="Training profile key in training config JSON")
    parser.add_argument("--training-config-path", default=None, help="Path to agent training config JSON")
    parser.add_argument("--scale", default="150pts", help="Scale folder (e.g. 150pts)")
    parser.add_argument("--base-points", type=int, default=150, help="Base roster budget before hard modifier")
    parser.add_argument("--hard-modifier-override", type=float, default=None)

    parser.add_argument("--sync-regular-common-pool", action="store_true")
    parser.add_argument("--skip-scenario-build", action="store_true")
    parser.add_argument("--regular-scenario-count", type=int, default=10)
    parser.add_argument("--hard-scenario-count", type=int, default=10)
    parser.add_argument("--fixed-wall-ref", default="walls-11.json")
    parser.add_argument("--fixed-objectives-ref", default="objectives-51.json")

    parser.add_argument("--generate-hard-opponent-rosters", action="store_true")
    parser.add_argument("--hard-num-rosters", type=int, default=10)
    parser.add_argument("--hard-seed", type=int, default=12345)
    parser.add_argument("--hard-points-tolerance", type=int, default=5)
    parser.add_argument("--hard-target-tanking-values", default="Swarm,Troop,Elite")
    parser.add_argument("--hard-target-tanking-weights", default="0.48,0.32,0.20")
    parser.add_argument("--hard-units-per-roster-values", default="5,6,7,8,9,10,11,12")
    parser.add_argument("--hard-units-per-roster-weights", default="0.06,0.12,0.18,0.22,0.20,0.14,0.06,0.02")
    parser.add_argument("--hard-max-build-attempts", type=int, default=2000)
    parser.add_argument("--hard-max-roster-resample-attempts", type=int, default=80)
    parser.add_argument("--hard-max-copies-per-unit", type=int, default=3)

    args = parser.parse_args()

    training_config_path = (
        Path(args.training_config_path)
        if args.training_config_path is not None
        else PROJECT_ROOT / "config" / "agents" / args.agent / f"{args.agent}_training_config.json"
    )
    profile = _load_training_profile(training_config_path, args.profile)
    hard_points_scale = _resolve_hard_points_scale(
        profile=profile,
        base_points=int(args.base_points),
        modifier_override=args.hard_modifier_override,
    )

    print(
        f"Resolved holdout_hard opponent points scale: base={args.base_points}, "
        f"modifier={(args.hard_modifier_override if args.hard_modifier_override is not None else _require_key(_require_key(profile, 'callback_params'), 'holdout_hard_opponent_budget_modifier'))}, "
        f"points_scale={hard_points_scale}"
    )

    if args.sync_regular_common_pool:
        _sync_regular_common_pool(args.agent, args.scale)
        print("holdout_regular common pool synchronized (agent -> opponent).")

    if not args.skip_scenario_build:
        _build_scenarios(
            agent_key=args.agent,
            scale=args.scale,
            split="holdout_regular",
            count=int(args.regular_scenario_count),
            wall_ref=args.fixed_wall_ref,
            objectives_ref=args.fixed_objectives_ref,
        )
        _build_scenarios(
            agent_key=args.agent,
            scale=args.scale,
            split="holdout_hard",
            count=int(args.hard_scenario_count),
            wall_ref=args.fixed_wall_ref,
            objectives_ref=args.fixed_objectives_ref,
        )
        print(
            f"Scenarios generated: holdout_regular={args.regular_scenario_count}, "
            f"holdout_hard={args.hard_scenario_count}"
        )

    if args.generate_hard_opponent_rosters:
        _run_hard_opponent_generation(
            hard_points_scale=hard_points_scale,
            hard_num_rosters=int(args.hard_num_rosters),
            hard_seed=int(args.hard_seed),
            hard_points_tolerance=int(args.hard_points_tolerance),
            hard_target_tanking_values=args.hard_target_tanking_values,
            hard_target_tanking_weights=args.hard_target_tanking_weights,
            hard_units_per_roster_values=args.hard_units_per_roster_values,
            hard_units_per_roster_weights=args.hard_units_per_roster_weights,
            hard_max_build_attempts=int(args.hard_max_build_attempts),
            hard_max_roster_resample_attempts=int(args.hard_max_roster_resample_attempts),
            hard_max_copies_per_unit=int(args.hard_max_copies_per_unit),
        )
        print("holdout_hard opponent rosters regenerated.")


if __name__ == "__main__":
    main()
