#!/usr/bin/env python3
"""
scripts/roster_matchup_stats.py - Collect roster matchup statistics

Runs P1 (trained agent) vs P2 (GreedyBot) for each (p1_roster, p2_roster) pair,
collects win/loss/draw stats, and writes to config/agents/<agent>/rosters/<scale>/matchups/.

Output files:
  - P1 benchmark: <p1_roster_id>_matchups.json
  - P2 benchmark: <p2_roster_id>_matchups.json
  - Full matrix: <split>_matchups.json

Modes:
  - Full matrix (default): all P1 × P2 combinations
  - P1 benchmark: --p1-benchmark p1_roster-01  → one P1, evaluate all P2 rosters
  - P2 benchmark: --p2-benchmark p2_training_roster-01   → one P2, evaluate all P1 rosters
  - All splits: --all-splits  → run training, holdout_regular, holdout_hard

Usage:
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm [--scale 100pts] [--episodes 30]
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --p1-benchmark p1_training_roster-01
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --all-splits --episodes 100
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _collect_p1_rosters(agent_key: str, scale: str, split: str) -> List[Tuple[str, str]]:
    """Return [(ref, roster_id), ...] for P1 rosters in split."""
    base = PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / split
    if not base.exists():
        return []
    refs: List[Tuple[str, str]] = []
    if split == "training":
        pattern = "p1_training_roster-*.json"
    else:
        pattern = f"p1_{split}_roster-*.json"
    for p in sorted(base.glob(pattern)):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        roster_id = data.get("roster_id", p.stem)
        ref = f"{split}/{p.name}"
        refs.append((ref, roster_id))
    return refs


def _collect_p2_rosters(scale: str, split: str) -> List[Tuple[str, str]]:
    """Return [(ref, roster_id), ...] for P2 rosters in split."""
    base = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / split
    if not base.exists():
        return []
    refs: List[Tuple[str, str]] = []
    for p in sorted(base.glob("p2_*_roster-*.json")):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        roster_id = data.get("roster_id", p.stem)
        ref = f"{split}/{p.name}"
        refs.append((ref, roster_id))
    return refs


def _build_scenario_template(scale: str, split: str) -> Dict[str, Any]:
    """Base scenario template for matchup scenarios."""
    return {
        "deployment_zone": "hammer",
        "deployment_type": "active",
        "scale": scale,
        "p1_roster_seed": 42,
        "wall_ref": "walls-01.json",
        "primary_objectives": ["objectives_control"],
        "objectives_ref": "objectives-01.json",
    }


def _run_matchup_episodes(
    scenario_file: str,
    agent_key: str,
    model_path: str,
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int,
    obs_normalizer=None,
    seed: int = 42,
) -> Tuple[int, int, int]:
    """Run n_episodes with model vs bot, return (wins, losses, draws)."""
    import numpy as np
    from sb3_contrib import MaskablePPO
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from ai.evaluation_bots import GreedyBot
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()
    bot = GreedyBot(randomness=0.15)

    def mask_fn(env):
        return env.get_action_mask()

    base_env = W40KEngine(
        rewards_config=rewards_config_name,
        training_config_name=training_config_name,
        controlled_agent=agent_key,
        active_agents=None,
        scenario_file=scenario_file,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=False,
    )
    masked_env = ActionMasker(base_env, mask_fn)
    env = BotControlledEnv(masked_env, bot, unit_registry)

    model = MaskablePPO.load(model_path, env=env)
    wins, losses, draws = 0, 0, 0
    for ep in range(n_episodes):
        ep_seed = (seed + ep * 1000) % (2**31)
        random.seed(ep_seed)
        obs, info = env.reset(seed=ep_seed)
        done = False
        while not done:
            model_obs = obs_normalizer(obs) if obs_normalizer is not None else obs
            model_obs = np.asarray(model_obs, dtype=np.float32)
            if model_obs.ndim == 1:
                model_obs = model_obs.reshape(1, -1)
            action_masks, _ = env.engine.action_decoder.get_action_mask_and_eligible_units(env.engine.game_state)
            action, _ = model.predict(model_obs, action_masks=action_masks, deterministic=True)
            action_scalar = int(np.asarray(action).flat[0])
            obs, _, terminated, truncated, info = env.step(action_scalar)
            done = bool(terminated or truncated)
        winner = info.get("winner")
        if winner == 1:
            wins += 1
        elif winner == -1:
            draws += 1
        else:
            losses += 1
    env.close()
    return wins, losses, draws


def _build_obs_normalizer(agent_key: str, training_config_name: str, model_path: str):
    """Build observation normalizer if VecNormalize is enabled."""
    import numpy as np
    from shared.data_validation import require_key
    from ai.vec_normalize_utils import normalize_observation_for_inference

    config = __import__("config_loader", fromlist=["get_config_loader"]).get_config_loader()
    training_cfg = config.load_agent_training_config(agent_key, training_config_name)
    vec_cfg = require_key(training_cfg, "vec_normalize")
    vec_eval_cfg = require_key(training_cfg, "vec_normalize_eval")
    if not vec_cfg.get("enabled") or not vec_eval_cfg.get("enabled"):
        return None

    def _normalize(obs):
        obs_arr = np.asarray(obs, dtype=np.float32)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(1, -1)
        return normalize_observation_for_inference(obs_arr, model_path).squeeze()

    return _normalize


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect roster matchup statistics")
    parser.add_argument("--agent", required=True, help="Agent key (e.g. Infantry_Troop_RangedSwarm)")
    parser.add_argument("--scale", default="100pts", help="Roster scale")
    parser.add_argument("--episodes", type=int, default=30, help="Episodes per matchup")
    parser.add_argument("--split", nargs="?", default="training", const="training",
                    help="Roster split: training (default), holdout_regular, holdout_hard")
    parser.add_argument("--training-config", default="default", help="Training config name")
    parser.add_argument("--rewards-config", default=None, help="Rewards config (default: same as agent)")
    parser.add_argument("--p1-benchmark", metavar="ROSTER_ID", default=None,
                    help="Use single P1 roster as benchmark; evaluate all P2 rosters vs it (e.g. p1_roster-01)")
    parser.add_argument("--p1-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P1 benchmark from (e.g. holdout_regular). Default: same as --split")
    parser.add_argument("--p2-benchmark", metavar="ROSTER_ID", default=None,
                    help="Use single P2 roster as benchmark; evaluate all P1 rosters vs it (e.g. p2_roster-01)")
    parser.add_argument("--p2-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P2 benchmark from (e.g. holdout). Default: same as --split")
    parser.add_argument("--all-splits", action="store_true",
                    help="Run for training, holdout_regular, and holdout_hard (output: <split>_matchups.json each)")
    args = parser.parse_args()

    if args.p1_benchmark and args.p2_benchmark:
        print("❌ Cannot use both --p1-benchmark and --p2-benchmark")
        sys.exit(1)
    if args.all_splits and (args.p1_benchmark or args.p2_benchmark):
        print("❌ --all-splits cannot be used with --p1-benchmark or --p2-benchmark")
        sys.exit(1)
    rewards_config = args.rewards_config or args.agent

    config = __import__("config_loader", fromlist=["get_config_loader"]).get_config_loader()
    models_root = config.get_models_root()
    model_path = os.path.join(models_root, args.agent, f"model_{args.agent}.zip")
    if not os.path.exists(model_path):
        print(f"❌ Model not found: {model_path}")
        sys.exit(1)

    splits_to_run: List[str] = (
        ["training", "holdout_regular", "holdout_hard"] if args.all_splits else [args.split]
    )

    for current_split in splits_to_run:
        if args.all_splits:
            print(f"\n{'='*60}\n📌 Split: {current_split}\n{'='*60}")
        _run_one_split(args, current_split, model_path, rewards_config)


def _run_one_split(
    args: argparse.Namespace,
    current_split: str,
    model_path: str,
    rewards_config: str,
) -> None:
    """Run matchup stats for one split (training, holdout_regular, or holdout_hard)."""
    p1_split = args.p1_benchmark_split if args.p1_benchmark and args.p1_benchmark_split else current_split
    p2_split_base = args.p2_benchmark_split if args.p2_benchmark and args.p2_benchmark_split else current_split
    p2_split = "holdout" if p2_split_base.startswith("holdout") else p2_split_base

    p1_rosters = _collect_p1_rosters(args.agent, args.scale, p1_split)
    p2_rosters = _collect_p2_rosters(args.scale, p2_split)
    if not p2_rosters and p2_split != p2_split_base:
        p2_rosters = _collect_p2_rosters(args.scale, p2_split_base)
    if not p1_rosters:
        print(f"❌ No P1 rosters in {args.agent}/rosters/{args.scale}/{p1_split}/")
        return
    if not p2_rosters:
        print(f"❌ No P2 rosters in _p2_rosters/{args.scale}/{p2_split}/")
        return

    if args.p1_benchmark:
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid == args.p1_benchmark]
        if not p1_rosters:
            print(f"❌ P1 benchmark '{args.p1_benchmark}' not found in {p1_split}")
            return
        print(f"📌 P1 benchmark: {args.p1_benchmark} (from {p1_split}, evaluating {len(p2_rosters)} P2 rosters from {p2_split})")
    if args.p2_benchmark:
        p2_rosters = [(ref, rid) for ref, rid in p2_rosters if rid == args.p2_benchmark]
        if not p2_rosters:
            print(f"❌ P2 benchmark '{args.p2_benchmark}' not found in {p2_split}")
            return
        print(f"📌 P2 benchmark: {args.p2_benchmark} (from {p2_split}, evaluating {len(p1_rosters)} P1 rosters from {p1_split})")

    scenario_subdir = "holdout_regular" if current_split == "holdout_regular" else "holdout_hard" if current_split == "holdout_hard" else "training"
    scenario_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "scenarios" / scenario_subdir
    matchup_dir = scenario_dir / "matchups"
    matchup_dir.mkdir(parents=True, exist_ok=True)
    template = _build_scenario_template(args.scale, current_split)
    obs_normalizer = _build_obs_normalizer(args.agent, args.training_config, model_path)

    matchups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    total_matchups = len(p1_rosters) * len(p2_rosters)
    current = 0
    for p1_ref, p1_id in p1_rosters:
        matchups[p1_id] = {}
        for p2_ref, p2_id in p2_rosters:
            current += 1
            scenario_data = {**template, "p1_roster_ref": p1_ref, "p2_roster_ref": p2_ref}
            scenario_file = matchup_dir / f"matchup_{p1_id}_{p2_id}.json"
            with open(scenario_file, "w", encoding="utf-8") as f:
                json.dump(scenario_data, f, indent=2)
            scenario_path = str(scenario_file)
            print(f"[{current}/{total_matchups}] {p1_id} vs {p2_id}...", end=" ", flush=True)
            wins, losses, draws = _run_matchup_episodes(
                scenario_path,
                args.agent,
                model_path,
                args.training_config,
                rewards_config,
                args.episodes,
                obs_normalizer=obs_normalizer,
            )
            total = wins + losses + draws
            win_rate = wins / total if total > 0 else 0.0
            matchups[p1_id][p2_id] = {
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "win_rate": round(win_rate, 4),
            }
            print(f"WR={win_rate:.2%} ({wins}W-{losses}L-{draws}D)")
            try:
                scenario_file.unlink()
            except OSError:
                pass

    overall_wr = sum(
        m["win_rate"] for p1_data in matchups.values() for m in p1_data.values()
    ) / max(1, total_matchups)
    p1_summaries: List[Dict[str, Any]] = []
    for p1_id, p2_data in matchups.items():
        rates = [m["win_rate"] for m in p2_data.values()]
        avg_wr = sum(rates) / len(rates) if rates else 0
        best = max(p2_data.items(), key=lambda x: x[1]["win_rate"])
        worst = min(p2_data.items(), key=lambda x: x[1]["win_rate"])
        p1_summaries.append({
            "p1_roster_id": p1_id,
            "overall_win_rate": round(avg_wr, 4),
            "vs_best": best[0],
            "vs_worst": worst[0],
            "sur_performant": avg_wr > overall_wr + 0.05,
            "sous_performant": avg_wr < overall_wr - 0.05,
        })
    p2_summaries: List[Dict[str, Any]] = []
    for _p2_ref, p2_id in p2_rosters:
        rates = [matchups[p1_id][p2_id]["win_rate"] for p1_id in matchups if p2_id in matchups[p1_id]]
        if not rates:
            continue
        avg_wr = sum(rates) / len(rates)
        p2_summaries.append({
            "p2_roster_id": p2_id,
            "p1_win_rate_vs_this_p2": round(avg_wr, 4),
            "sur_performant_p2": avg_wr < overall_wr - 0.05,
            "sous_performant_p2": avg_wr > overall_wr + 0.05,
        })

    matchups_out_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "rosters" / args.scale / "matchups"
    matchups_out_dir.mkdir(parents=True, exist_ok=True)
    if args.p1_benchmark:
        out_filename = f"{p1_rosters[0][1]}_matchups.json"
    elif args.p2_benchmark:
        out_filename = f"{p2_rosters[0][1]}_matchups.json"
    else:
        out_filename = f"{current_split}_matchups.json"
    out_path = matchups_out_dir / out_filename
    output = {
        "agent_key": args.agent,
        "scale": args.scale,
        "split": current_split,
        "model_path": model_path,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episodes_per_matchup": args.episodes,
        "p1_benchmark": args.p1_benchmark,
        "p1_benchmark_split": args.p1_benchmark_split,
        "p2_benchmark": args.p2_benchmark,
        "p2_benchmark_split": args.p2_benchmark_split,
        "overall_win_rate": round(overall_wr, 4),
        "matchups": matchups,
        "p1_summaries": sorted(p1_summaries, key=lambda x: -x["overall_win_rate"]),
        "p2_summaries": sorted(p2_summaries, key=lambda x: x["p1_win_rate_vs_this_p2"]),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Wrote {out_path}")


if __name__ == "__main__":
    main()
