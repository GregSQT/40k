#!/usr/bin/env python3
"""
scripts/roster_matchup_stats.py - Collect roster matchup statistics

Runs P1 (trained agent) vs P2 (GreedyBot) for each (p1_roster, p2_roster) pair,
collects win/loss/draw stats, and writes to config/agents/<agent>/rosters/<scale>/matchups/.

Output files:
  - P1 benchmark: <p1_roster_id>_matchups_<eval_bot>.json
  - P2 benchmark: <p2_roster_id>_matchups_<eval_bot>.json
  - P1 subset: <split>_matchups_<eval_bot>_p1subset.json  (--p1-rosters id1,id2,...)
  - Full matrix: <split>_matchups_<eval_bot>.json

Modes:
  - Full matrix (default): all P1 × P2 combinations
  - P1 benchmark: --p1-benchmark p1_roster-01  → one P1, evaluate all P2 rosters
  - P1 subset: --p1-rosters id1,id2  → only these P1 vs all P2 (same episodes each matchup)
  - P1 exclude: --p1-exclude id1,id2  → all P1 in split except these; output: <split>_matchups_<bot>_p1exclude.json
  - Quantile: --quantile best25|worst25 avec --owner agent et/ou --owner opponent → sous-ensembles selon mean_agg
    (greedy + defensive_smart + adaptive). --merge-full-matrices (défaut si quantile) fusionne dans
    <split>_matchups_<eval_bot>.json.
  - P2 benchmark: --p2-benchmark p2_training_roster-01   → one P2, evaluate all P1 rosters
  - All splits: --all-splits  → run training, holdout_regular, holdout_hard

Usage:
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm [--scale 100pts] [--episodes 30]
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --p1-benchmark p1_training_roster-01
  python scripts/roster_matchup_stats.py --agent Infantry_Troop_RangedSwarm --all-splits --episodes 100
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _import_roster_aggregate() -> Any:
    import importlib.util

    path = PROJECT_ROOT / "scripts" / "roster_aggregate_rankings.py"
    spec = importlib.util.spec_from_file_location("roster_aggregate_rankings", path)
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    if loader is None:
        raise RuntimeError("importlib loader is None")
    loader.exec_module(mod)
    return mod


def _ranking_matrix_filenames(split: str) -> Tuple[str, str, str]:
    """Même trio que roster_aggregate_rankings (mean_agg de référence)."""
    return (
        f"{split}_matchups_greedy.json",
        f"{split}_matchups_defensive_smart.json",
        f"{split}_matchups_adaptive.json",
    )


def _quantile_ids_from_rows(
    rows: List[Dict[str, Any]], which: str, frac: float, key: str = "mean_agg"
) -> List[str]:
    """which: best25 = plus haut mean_agg en premier ; worst25 = quartile bas."""
    by_desc = sorted(rows, key=lambda r: float(r[key]), reverse=True)
    ids = [str(r["roster_id"]) for r in by_desc]
    n = len(ids)
    if n == 0:
        return []
    k = max(1, int(math.ceil(n * frac)))
    if which == "best25":
        return ids[:k]
    if which == "worst25":
        return ids[-k:]
    raise ValueError(f"Invalid quantile which: {which!r}")


def _resolve_p1_quantile_ids(
    matchup_out_dir: Path,
    current_split: str,
    which: str,
    frac: float,
) -> List[str]:
    agg = _import_roster_aggregate()
    names = _ranking_matrix_filenames(current_split)
    matrices: List[Dict[str, Dict[str, Any]]] = []
    for name in names:
        p = matchup_out_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"Classement quantile: fichier manquant {p} "
                f"(nécessite les 3 matrices {names} pour calculer mean_agg)."
            )
        matrices.append(agg.load_matchup_matrix(p))
    rows = agg.build_rows_p1(matrices, agg.BOT_WEIGHTS)
    return _quantile_ids_from_rows(rows, which, frac)


def _resolve_p2_quantile_ids(
    matchup_out_dir: Path,
    current_split: str,
    which: str,
    frac: float,
) -> List[str]:
    agg = _import_roster_aggregate()
    names = _ranking_matrix_filenames(current_split)
    matrices = []
    for name in names:
        p = matchup_out_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"Classement quantile P2: fichier manquant {p} "
                f"(nécessite les 3 matrices {names})."
            )
        matrices.append(agg.load_matchup_matrix(p))
    rows = agg.build_rows_p2(matrices, agg.BOT_WEIGHTS)
    return _quantile_ids_from_rows(rows, which, frac)


def _rebuild_summaries_from_matchups(
    matchups: Dict[str, Dict[str, Dict[str, Any]]],
    p1_order: Sequence[Tuple[str, str]],
    p2_order: Sequence[Tuple[str, str]],
) -> Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Recalcule overall_wr et résumés P1/P2 à partir d'une matrice complète (grille P1×P2)."""
    p1_ids = [rid for _r, rid in p1_order]
    p2_ids = [rid for _r, rid in p2_order]
    all_rates: List[float] = []
    for p1_id in p1_ids:
        for p2_id in p2_ids:
            if p1_id not in matchups:
                raise KeyError(f"Résumé: P1 {p1_id!r} absent de matchups")
            row = matchups[p1_id]
            if p2_id not in row:
                raise KeyError(f"Résumé: cellule manquante P1={p1_id!r} P2={p2_id!r}")
            all_rates.append(float(row[p2_id]["win_rate"]))
    overall_wr = sum(all_rates) / len(all_rates) if all_rates else 0.0

    p1_summaries: List[Dict[str, Any]] = []
    for p1_id in p1_ids:
        p2_data = matchups[p1_id]
        rates = [float(p2_data[p2_id]["win_rate"]) for p2_id in p2_ids]
        avg_wr = sum(rates) / len(rates)
        best = max(((p2_id, p2_data[p2_id]["win_rate"]) for p2_id in p2_ids), key=lambda x: x[1])
        worst = min(((p2_id, p2_data[p2_id]["win_rate"]) for p2_id in p2_ids), key=lambda x: x[1])
        p1_summaries.append(
            {
                "p1_roster_id": p1_id,
                "overall_win_rate": round(avg_wr, 4),
                "vs_best": best[0],
                "vs_worst": worst[0],
                "sur_performant": avg_wr > overall_wr + 0.05,
                "sous_performant": avg_wr < overall_wr - 0.05,
            }
        )

    p2_summaries: List[Dict[str, Any]] = []
    for p2_id in p2_ids:
        rates = [float(matchups[p1_id][p2_id]["win_rate"]) for p1_id in p1_ids]
        avg_wr = sum(rates) / len(rates)
        p2_summaries.append(
            {
                "p2_roster_id": p2_id,
                "p1_win_rate_vs_this_p2": round(avg_wr, 4),
                "sur_performant_p2": avg_wr < overall_wr - 0.05,
                "sous_performant_p2": avg_wr > overall_wr + 0.05,
            }
        )
    return overall_wr, p1_summaries, p2_summaries


def _merge_partial_into_full_json(
    full_path: Path,
    partial_matchups: Dict[str, Dict[str, Dict[str, Any]]],
    p1_order: Sequence[Tuple[str, str]],
    p2_order: Sequence[Tuple[str, str]],
    args: argparse.Namespace,
    model_path: str,
    eval_bot_name: str,
    current_split: str,
) -> None:
    """Fusionne les cellules rejouées dans la matrice complète et réécrit le JSON."""
    with full_path.open(encoding="utf-8") as f:
        doc = json.load(f)
    mm = doc.get("matchups")
    if not isinstance(mm, dict):
        raise KeyError(f"{full_path} : clé 'matchups' absente ou invalide")
    for p1, row in partial_matchups.items():
        if p1 not in mm:
            mm[p1] = {}
        for p2, cell in row.items():
            mm[p1][p2] = cell
    doc["matchups"] = mm
    overall_wr, p1_s, p2_s = _rebuild_summaries_from_matchups(mm, p1_order, p2_order)
    doc["overall_win_rate"] = round(overall_wr, 4)
    doc["episodes_per_matchup"] = args.episodes
    doc["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["model_path"] = model_path
    doc["eval_bot"] = eval_bot_name
    doc["eval_bot_randomness"] = float(args.eval_bot_randomness)
    doc["split"] = current_split
    doc["p1_summaries"] = sorted(p1_s, key=lambda x: -x["overall_win_rate"])
    doc["p2_summaries"] = sorted(p2_s, key=lambda x: x["p1_win_rate_vs_this_p2"])
    doc["quantile"] = getattr(args, "quantile", None)
    doc["quantile_owners"] = list(getattr(args, "quantile_owners", []) or [])
    doc["quantile_frac"] = float(args.quantile_frac)
    doc["matchup_merge_note"] = (
        "Fusion partielle depuis roster_matchup_stats.py (quantile) ; "
        "résumés recalculés sur la grille matchups complète."
    )
    with full_path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Fusion dans matrice complète: {full_path}")


def _collect_p1_rosters(agent_key: str, scale: str, split: str) -> List[Tuple[str, str]]:
    """Return [(ref, roster_id), ...] for P1 rosters in split."""
    base = PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / split
    if not base.exists():
        return []
    refs: List[Tuple[str, str]] = []
    patterns: List[str] = [
        # Current naming convention
        f"agent_{split}_roster_*.json",
        # Legacy naming conventions
        f"p1_{split}_roster-*.json",
    ]
    if split == "training":
        patterns.append("p1_training_roster-*.json")
    seen_paths = set()
    for pattern in patterns:
        for p in sorted(base.glob(pattern)):
            if p in seen_paths:
                continue
            if "_kpis" in p.name or "_matchups" in p.name:
                continue
            seen_paths.add(p)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "roster_id" not in data:
                continue
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
    patterns = [
        # Current naming convention
        f"opponent_{split}_roster_*.json",
        # Legacy naming convention
        "p2_*_roster-*.json",
    ]
    seen_paths = set()
    for pattern in patterns:
        for p in sorted(base.glob(pattern)):
            if p in seen_paths:
                continue
            if "_kpis" in p.name or "_matchups" in p.name:
                continue
            seen_paths.add(p)
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "roster_id" not in data:
                continue
            roster_id = data.get("roster_id", p.stem)
            ref = f"{split}/{p.name}"
            refs.append((ref, roster_id))
    return refs


def _build_scenario_template(scale: str, split: str, wall_ref: str, objectives_ref: str) -> Dict[str, Any]:
    """Base scenario template for matchup scenarios."""
    return {
        "deployment_zone": "hammer",
        "deployment_type": "active",
        "scale": scale,
        "p1_roster_seed": 42,
        "wall_ref": wall_ref,
        "primary_objectives": ["objectives_control"],
        "objectives_ref": objectives_ref,
    }


def _extract_rule_checker_units() -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Return unit_type names where RULES_STATUS has at least one entry == 2.

    Returns:
      - selected unit_type list
      - selected details rows
      - rejected audit rows
    """
    units_root = PROJECT_ROOT / "frontend" / "src" / "roster"
    if not units_root.exists():
        raise FileNotFoundError(f"Units directory not found: {units_root}")

    selected_units: List[str] = []
    selected_details: List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []
    class_pattern = re.compile(r"export\s+class\s+(\w+)")
    rules_status_pattern = re.compile(
        r"static\s+RULES_STATUS(?:\s*:\s*[^=]+)?\s*=\s*\{([\s\S]*?)\};",
        re.MULTILINE,
    )
    rules_status_entry_pattern = re.compile(r"([A-Za-z0-9_]+)\s*:\s*([0-9]+)")

    for ts_file in sorted(units_root.glob("**/units/*.ts")):
        content = ts_file.read_text(encoding="utf-8")
        class_match = class_pattern.search(content)
        unit_type = class_match.group(1) if class_match else ts_file.stem
        status_match = rules_status_pattern.search(content)
        rel_path = str(ts_file.relative_to(PROJECT_ROOT)).replace("\\", "/")

        if status_match is None:
            rejected_rows.append(
                {
                    "unit_type": unit_type,
                    "file": rel_path,
                    "reason": "RULES_STATUS missing",
                }
            )
            continue

        status_block = status_match.group(1)
        entries = rules_status_entry_pattern.findall(status_block)
        if len(entries) == 0:
            rejected_rows.append(
                {
                    "unit_type": unit_type,
                    "file": rel_path,
                    "reason": "RULES_STATUS empty or unparsable",
                }
            )
            continue

        implemented_rule_keys = sorted(
            [rule_key for rule_key, raw_value in entries if int(raw_value) == 2]
        )
        if len(implemented_rule_keys) > 0:
            selected_units.append(unit_type)
            selected_details.append(
                {
                    "unit_type": unit_type,
                    "file": rel_path,
                    "implemented_rules": implemented_rule_keys,
                }
            )
        else:
            rejected_rows.append(
                {
                    "unit_type": unit_type,
                    "file": rel_path,
                    "reason": "RULES_STATUS has no value == 2",
                }
            )

    selected_sorted = sorted(set(selected_units))
    if not selected_sorted:
        raise ValueError(
            "No unit found with at least one RULES_STATUS entry == 2 in frontend/src/roster/**/units/*.ts"
        )
    return selected_sorted, selected_details, rejected_rows


def _generate_rule_checker_artifacts(agent_key: str, scale: str) -> None:
    """
    Generate dedicated rule-checker scenarios + manifest in config/rule_checker.
    """
    from ai.unit_registry import UnitRegistry

    output_dir = PROJECT_ROOT / "config" / "rule_checker"
    scenarios_dir = output_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    selected_units, selected_details, rejected_rows = _extract_rule_checker_units()
    unit_registry = UnitRegistry()

    # Validate unit types exist in runtime registry.
    missing_in_registry = [u for u in selected_units if u not in unit_registry.units]
    if missing_in_registry:
        raise KeyError(
            f"Selected unit_type not found in UnitRegistry: {missing_in_registry}"
        )

    scenario_paths: List[str] = []
    scenario_index = 1
    for p1_unit in selected_units:
        for p2_unit in selected_units:
            scenario_name = f"scenario_rule_checker_bot-{scenario_index:03d}.json"
            scenario_path = scenarios_dir / scenario_name
            scenario_payload = {
                "deployment_zone": "hammer",
                "deployment_type": "active",
                "scale": scale,
                "wall_ref": "walls-01.json",
                "primary_objectives": ["objectives_control"],
                "objectives_ref": "objectives-01.json",
                "units": [
                    {"id": 1, "unit_type": p1_unit, "player": 1},
                    {"id": 2, "unit_type": p1_unit, "player": 1},
                    {"id": 101, "unit_type": p2_unit, "player": 2},
                    {"id": 102, "unit_type": p2_unit, "player": 2},
                ],
            }
            scenario_path.write_text(
                json.dumps(scenario_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            scenario_paths.append(str(scenario_path))
            scenario_index += 1

    manifest = {
        "mode": "rule_checker",
        "agent": agent_key,
        "scale": scale,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule_filter": {
            "mode": "any_rule_status_equals",
            "required_value": 2,
        },
        "selected_unit_types": selected_units,
        "selected_details": selected_details,
        "scenario_count": len(scenario_paths),
        "scenario_paths": scenario_paths,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    rejected_path = output_dir / "audit_rejected.json"
    rejected_path.write_text(
        json.dumps(rejected_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"✅ Rule-checker scenarios generated: {len(scenario_paths)}")
    print(f"📁 Output dir: {output_dir}")
    print(f"🧾 Manifest: {manifest_path}")
    print(f"🧾 Rejected audit: {rejected_path}")


def _run_matchup_episodes(
    scenario_file: str,
    agent_key: str,
    model_path: str,
    training_config_name: str,
    rewards_config_name: str,
    n_episodes: int,
    opponent_mode: str,
    eval_bot_name: str,
    eval_bot_randomness: float,
    agent_seat_mode: str,
    obs_normalizer=None,
    seed: int = 42,
) -> Tuple[int, int, int]:
    """Run n_episodes with model vs bot, return (wins, losses, draws)."""
    import numpy as np
    from sb3_contrib import MaskablePPO
    from ai.training_utils import setup_imports
    from ai.env_wrappers import BotControlledEnv
    from ai.evaluation_bots import (
        RandomBot, GreedyBot, DefensiveBot, ControlBot,
        AggressiveSmartBot, DefensiveSmartBot, AdaptiveBot,
    )
    from sb3_contrib.common.wrappers import ActionMasker
    from ai.unit_registry import UnitRegistry

    unit_registry = UnitRegistry()
    W40KEngine, _ = setup_imports()
    if opponent_mode not in {"bot", "agent"}:
        raise ValueError(f"opponent_mode must be 'bot' or 'agent' (got {opponent_mode!r})")
    if agent_seat_mode not in {"p1", "p2"}:
        raise ValueError(f"agent_seat_mode must be 'p1' or 'p2' (got {agent_seat_mode!r})")
    controlled_winner_id = 1 if agent_seat_mode == "p1" else 2

    BOT_CLASSES = {
        "random": RandomBot,
        "greedy": GreedyBot,
        "defensive": DefensiveBot,
        "control": ControlBot,
        "aggressive_smart": AggressiveSmartBot,
        "defensive_smart": DefensiveSmartBot,
        "adaptive": AdaptiveBot,
    }
    if opponent_mode == "bot" and eval_bot_name not in BOT_CLASSES:
        raise ValueError(f"Unknown eval bot: {eval_bot_name!r}")

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
    if opponent_mode == "bot":
        if eval_bot_name == "random":
            bot = RandomBot()
        else:
            bot = BOT_CLASSES[eval_bot_name](randomness=float(eval_bot_randomness))
        env = BotControlledEnv(masked_env, bot, unit_registry)
    else:
        # Force self-play opponent every episode (agent vs agent), snapshot taken from model_path.
        # A fallback bot list is required by BotControlledEnv signature, but ratio=1.0 ensures
        # self-play path is always selected.
        fallback_bot = GreedyBot(randomness=0.0)
        env = BotControlledEnv(
            masked_env,
            bots=[fallback_bot],
            unit_registry=unit_registry,
            agent_seat_mode=agent_seat_mode,
            self_play_opponent_enabled=True,
            self_play_ratio_start=1.0,
            self_play_ratio_end=1.0,
            self_play_total_episodes=max(1, int(n_episodes)),
            self_play_warmup_episodes=0,
            self_play_snapshot_path=model_path,
            self_play_snapshot_refresh_episodes=1,
            self_play_snapshot_device="cpu",
            self_play_deterministic=True,
        )

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
        if winner == controlled_winner_id:
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
    parser.add_argument(
        "--p1-rosters",
        metavar="ID_LIST",
        default=None,
        help=(
            "Comma-separated P1 roster ids to evaluate (vs all P2 in split). "
            "Mutually exclusive with --p1-benchmark. Output: <split>_matchups_<bot>_p1subset.json"
        ),
    )
    parser.add_argument(
        "--p1-exclude",
        metavar="ID_LIST",
        default=None,
        help=(
            "Comma-separated P1 roster ids to skip. Applied to the full split roster list, "
            "or to the set selected by --p1-rosters. Use to omit rosters already benchmarked."
        ),
    )
    parser.add_argument("--p1-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P1 benchmark from (e.g. holdout_regular). Default: same as --split")
    parser.add_argument("--p2-benchmark", metavar="ROSTER_ID", default=None,
                    help="Use single P2 roster as benchmark; evaluate all P1 rosters vs it (e.g. p2_roster-01)")
    parser.add_argument("--p2-benchmark-split", metavar="SPLIT", default=None,
                    help="Split to load P2 benchmark from (e.g. holdout). Default: same as --split")
    parser.add_argument("--all-splits", action="store_true",
                    help="Run for training, holdout_regular, and holdout_hard (output: <split>_matchups.json each)")
    parser.add_argument("--wall-ref", default="walls-11.json",
                    help="Wall ref for generated matchup scenarios")
    parser.add_argument("--objectives-ref", default="objectives-51.json",
                    help="Objectives ref for generated matchup scenarios")
    parser.add_argument(
        "--opponent-mode",
        choices=["bot", "agent"],
        default="bot",
        help="bot: evaluate model vs configured bot(s); agent: evaluate model vs agent self-play opponent",
    )
    parser.add_argument(
        "--eval-bot",
        default="greedy",
        choices=["random", "greedy", "defensive", "control", "aggressive_smart", "defensive_smart", "adaptive"],
        help="Single evaluation bot used for matchup generation",
    )
    parser.add_argument(
        "--eval-bots",
        default=None,
        help=(
            "Optional comma-separated list of eval bots to generate multiple matchup matrices in one run, "
            "e.g. greedy,defensive_smart,adaptive"
        ),
    )
    parser.add_argument(
        "--eval-bot-randomness",
        type=float,
        default=0.15,
        help="Randomness passed to non-random eval bots",
    )
    parser.add_argument(
        "--agent-seat-mode",
        choices=["p1", "p2"],
        default="p1",
        help="Seat used when --opponent-mode agent and bidirectional mode is disabled",
    )
    parser.add_argument(
        "--agent-seat-bidirectional",
        action="store_true",
        help="When --opponent-mode agent, evaluate both seats (p1 and p2) and aggregate results",
    )
    parser.add_argument(
        "--rule-checker",
        action="store_true",
        help="Generate dedicated rule-checker scenarios in config/rule_checker/ using units with at least one RULES_STATUS value == 2",
    )
    parser.add_argument(
        "--quantile",
        choices=["best25", "worst25"],
        default=None,
        help=(
            "Quartile par mean_agg agrégé (greedy + defensive_smart + adaptive). "
            "À combiner avec --owner agent et/ou --owner opponent."
        ),
    )
    parser.add_argument(
        "--owner",
        dest="quantile_owners",
        action="append",
        choices=["agent", "opponent"],
        metavar="WHO",
        help=(
            "Applique --quantile aux rosters de l'agent (P1) et/ou de l'adversaire (P2). "
            "Répéter pour les deux: --owner agent --owner opponent."
        ),
    )
    parser.add_argument(
        "--quantile-frac",
        type=float,
        default=0.25,
        help="Taille du quartile (défaut 0.25). k = ceil(n * frac), min 1.",
    )
    parser.add_argument(
        "--merge-full-matrices",
        dest="merge_full_matrices",
        action="store_const",
        const=True,
        default=None,
        help="Fusionner les cellules rejouées dans <split>_matchups_<eval_bot>.json (défaut: oui si quantile)",
    )
    parser.add_argument(
        "--no-merge-full-matrices",
        dest="merge_full_matrices",
        action="store_const",
        const=False,
        default=None,
        help="Écrire un JSON partiel au lieu de fusionner dans la matrice complète",
    )
    args = parser.parse_args()

    if args.rule_checker:
        _generate_rule_checker_artifacts(agent_key=args.agent, scale=args.scale)
        return

    owners_norm = list(dict.fromkeys(getattr(args, "quantile_owners", None) or []))
    args.quantile_owners = owners_norm
    args.quantile_p1 = "agent" in owners_norm
    args.quantile_p2 = "opponent" in owners_norm

    if args.p1_benchmark and args.p2_benchmark:
        print("❌ Cannot use both --p1-benchmark and --p2-benchmark")
        sys.exit(1)
    if args.p1_benchmark and args.p1_rosters:
        print("❌ Cannot use both --p1-benchmark and --p1-rosters")
        sys.exit(1)
    if args.p1_benchmark and args.p1_exclude:
        print("❌ Cannot use both --p1-benchmark and --p1-exclude")
        sys.exit(1)
    if args.all_splits and (args.p1_benchmark or args.p2_benchmark):
        print("❌ --all-splits cannot be used with --p1-benchmark or --p2-benchmark")
        sys.exit(1)
    if args.eval_bot_randomness < 0.0 or args.eval_bot_randomness > 1.0:
        print(f"❌ --eval-bot-randomness must be in [0,1], got {args.eval_bot_randomness}")
        sys.exit(1)
    if args.opponent_mode == "agent" and args.eval_bots is not None:
        print("❌ --eval-bots is not compatible with --opponent-mode agent")
        sys.exit(1)
    if args.opponent_mode == "bot" and args.agent_seat_bidirectional:
        print("❌ --agent-seat-bidirectional is only valid with --opponent-mode agent")
        sys.exit(1)
    if args.merge_full_matrices is None:
        args.merge_full_matrices = bool(args.quantile_p1 or args.quantile_p2)
    if (args.quantile_p1 or args.quantile_p2) and args.quantile is None:
        print("❌ Avec --owner, --quantile (best25|worst25) est requis")
        sys.exit(1)
    if args.quantile is not None and not (args.quantile_p1 or args.quantile_p2):
        print("❌ --quantile requiert au moins un --owner agent et/ou --owner opponent")
        sys.exit(1)
    if args.quantile_p1:
        if args.p1_benchmark or args.p1_rosters or args.p1_exclude:
            print(
                "❌ quantile côté agent (--owner agent) incompatible avec "
                "--p1-benchmark, --p1-rosters et --p1-exclude"
            )
            sys.exit(1)
    if args.quantile_p2 and args.p2_benchmark:
        print("❌ quantile côté adversaire (--owner opponent) incompatible avec --p2-benchmark")
        sys.exit(1)
    if (args.quantile_p1 or args.quantile_p2) and not (0.0 < args.quantile_frac <= 1.0):
        print(f"❌ --quantile-frac doit être dans ]0,1], obtenu: {args.quantile_frac}")
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
    if args.opponent_mode == "agent":
        eval_bot_names = ["agent"]
    elif args.eval_bots is None:
        eval_bot_names = [str(args.eval_bot)]
    else:
        eval_bot_names = [token.strip() for token in str(args.eval_bots).split(",") if token.strip()]
        if not eval_bot_names:
            print("❌ --eval-bots provided but empty after parsing")
            sys.exit(1)
        valid_bots = {"random", "greedy", "defensive", "control", "aggressive_smart", "defensive_smart", "adaptive"}
        invalid = [name for name in eval_bot_names if name not in valid_bots]
        if invalid:
            print(f"❌ Invalid bot(s) in --eval-bots: {invalid}. Valid: {sorted(valid_bots)}")
            sys.exit(1)

    for current_split in splits_to_run:
        for eval_bot_name in eval_bot_names:
            if args.all_splits or len(eval_bot_names) > 1:
                print(f"\n{'='*60}\n📌 Split: {current_split} | Eval bot: {eval_bot_name}\n{'='*60}")
            _run_one_split(args, current_split, model_path, rewards_config, eval_bot_name)


def _run_one_split(
    args: argparse.Namespace,
    current_split: str,
    model_path: str,
    rewards_config: str,
    eval_bot_name: str,
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

    matchups_out_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "rosters" / args.scale / "matchups"
    matchups_out_dir.mkdir(parents=True, exist_ok=True)

    p1_rosters_full: List[Tuple[str, str]] = []
    p2_rosters_full: List[Tuple[str, str]] = []
    if args.quantile_p1 or args.quantile_p2:
        if args.quantile is None:
            raise ValueError("--quantile est requis avec --owner agent et/ou --owner opponent")
        p1_rosters_full = list(p1_rosters)
        p2_rosters_full = list(p2_rosters)

    if args.quantile_p1:
        qids = set(
            _resolve_p1_quantile_ids(
                matchups_out_dir, current_split, str(args.quantile), float(args.quantile_frac)
            )
        )
        p1_rosters = [(r, rid) for r, rid in p1_rosters if rid in qids]
        print(
            f"📌 Quantile agent (P1) {args.quantile} (frac={args.quantile_frac}): "
            f"{len(p1_rosters)} roster(s) / {len(qids)} id(s) cible(s)"
        )
        if not p1_rosters:
            print("❌ Aucun P1 après filtre quantile")
            return
    if args.quantile_p2:
        qids = set(
            _resolve_p2_quantile_ids(
                matchups_out_dir, current_split, str(args.quantile), float(args.quantile_frac)
            )
        )
        p2_rosters = [(r, rid) for r, rid in p2_rosters if rid in qids]
        print(
            f"📌 Quantile adversaire (P2) {args.quantile} (frac={args.quantile_frac}): "
            f"{len(p2_rosters)} roster(s) / {len(qids)} id(s) cible(s)"
        )
        if not p2_rosters:
            print("❌ Aucun P2 après filtre quantile")
            return

    if args.p1_benchmark:
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid == args.p1_benchmark]
        if not p1_rosters:
            print(f"❌ P1 benchmark '{args.p1_benchmark}' not found in {p1_split}")
            return
        print(f"📌 P1 benchmark: {args.p1_benchmark} (from {p1_split}, evaluating {len(p2_rosters)} P2 rosters from {p2_split})")
    elif args.p1_rosters:
        allowed = {x.strip() for x in str(args.p1_rosters).split(",") if x.strip()}
        if not allowed:
            print("❌ --p1-rosters is empty")
            return
        found_ids = {rid for _, rid in p1_rosters}
        missing = sorted(allowed - found_ids)
        if missing:
            print(f"❌ P1 roster id(s) not found in {p1_split}: {missing}")
            return
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid in allowed]
        print(
            f"📌 P1 subset: {len(p1_rosters)} roster(s) vs {len(p2_rosters)} P2 "
            f"({current_split}, {args.episodes} ep/matchup)"
        )
    if args.p2_benchmark:
        p2_rosters = [(ref, rid) for ref, rid in p2_rosters if rid == args.p2_benchmark]
        if not p2_rosters:
            print(f"❌ P2 benchmark '{args.p2_benchmark}' not found in {p2_split}")
            return
        print(f"📌 P2 benchmark: {args.p2_benchmark} (from {p2_split}, evaluating {len(p1_rosters)} P1 rosters from {p1_split})")

    if args.p1_exclude:
        excl = {x.strip() for x in str(args.p1_exclude).split(",") if x.strip()}
        if not excl:
            print("❌ --p1-exclude is empty")
            return
        before_ids = {rid for _, rid in p1_rosters}
        unknown_excl = sorted(excl - before_ids)
        if unknown_excl:
            print(f"⚠️  --p1-exclude id(s) not in current P1 set (ignored): {unknown_excl}")
        before_n = len(p1_rosters)
        p1_rosters = [(ref, rid) for ref, rid in p1_rosters if rid not in excl]
        print(
            f"📌 P1 exclude: removed {before_n - len(p1_rosters)} roster(s), "
            f"{len(p1_rosters)} remaining ({current_split})"
        )
        if not p1_rosters:
            print("❌ No P1 rosters left after --p1-exclude")
            return

    scenario_subdir = "holdout_regular" if current_split == "holdout_regular" else "holdout_hard" if current_split == "holdout_hard" else "training"
    scenario_dir = PROJECT_ROOT / "config" / "agents" / args.agent / "scenarios" / scenario_subdir
    matchup_dir = scenario_dir / "matchups"
    matchup_dir.mkdir(parents=True, exist_ok=True)
    run_label_raw = str(eval_bot_name) if eval_bot_name else str(args.opponent_mode)
    run_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", run_label_raw)
    run_matchup_dir = matchup_dir / f"run_{current_split}_{run_label}_{os.getpid()}_{int(time.time() * 1000)}"
    run_matchup_dir.mkdir(parents=True, exist_ok=True)
    template = _build_scenario_template(
        args.scale,
        current_split,
        args.wall_ref,
        args.objectives_ref,
    )
    obs_normalizer = _build_obs_normalizer(args.agent, args.training_config, model_path)

    matchups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    total_matchups = len(p1_rosters) * len(p2_rosters)
    current = 0
    total_matchup_seconds = 0.0
    for p1_ref, p1_id in p1_rosters:
        matchups[p1_id] = {}
        for p2_ref, p2_id in p2_rosters:
            current += 1
            matchup_start = time.perf_counter()
            scenario_data = {
                **template,
                "agent_roster_ref": p1_ref,
                "opponent_roster_ref": p2_ref,
            }
            scenario_file = run_matchup_dir / f"matchup_{p1_id}_{p2_id}.json"
            with open(scenario_file, "w", encoding="utf-8") as f:
                json.dump(scenario_data, f, indent=2)
            scenario_path = str(scenario_file)
            print(f"[{current}/{total_matchups}] {p1_id} vs {p2_id}...", end=" ", flush=True)
            if args.opponent_mode == "agent" and bool(args.agent_seat_bidirectional):
                wins_p1, losses_p1, draws_p1 = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode="agent",
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode="p1",
                    obs_normalizer=obs_normalizer,
                )
                wins_p2, losses_p2, draws_p2 = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode="agent",
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode="p2",
                    obs_normalizer=obs_normalizer,
                )
                wins = wins_p1 + wins_p2
                losses = losses_p1 + losses_p2
                draws = draws_p1 + draws_p2
            else:
                wins, losses, draws = _run_matchup_episodes(
                    scenario_path,
                    args.agent,
                    model_path,
                    args.training_config,
                    rewards_config,
                    args.episodes,
                    opponent_mode=str(args.opponent_mode),
                    eval_bot_name=eval_bot_name,
                    eval_bot_randomness=float(args.eval_bot_randomness),
                    agent_seat_mode=str(args.agent_seat_mode),
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
            matchup_elapsed = time.perf_counter() - matchup_start
            total_matchup_seconds += matchup_elapsed
            avg_matchup_seconds = total_matchup_seconds / float(current)
            avg_matchup_text = f"{avg_matchup_seconds:.3f}".replace(".", ",")
            print(f"WR={win_rate:.2%} ({wins}W-{losses}L-{draws}D) | avg: {avg_matchup_text}s")
            try:
                scenario_file.unlink()
            except OSError:
                pass
    try:
        run_matchup_dir.rmdir()
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

    use_quantile_merge = bool(
        args.merge_full_matrices and (args.quantile_p1 or args.quantile_p2)
    )
    if use_quantile_merge:
        full_path = matchups_out_dir / f"{current_split}_matchups_{eval_bot_name}.json"
        _merge_partial_into_full_json(
            full_path,
            matchups,
            p1_rosters_full,
            p2_rosters_full,
            args,
            model_path,
            eval_bot_name,
            current_split,
        )
        return

    if args.p1_benchmark:
        out_filename = f"{p1_rosters[0][1]}_matchups_{eval_bot_name}.json"
    elif args.p2_benchmark:
        out_filename = f"{p2_rosters[0][1]}_matchups_{eval_bot_name}.json"
    elif args.p1_rosters:
        out_filename = f"{current_split}_matchups_{eval_bot_name}_p1subset.json"
    elif args.p1_exclude:
        # Ne pas écraser la matrice complète quand seul --p1-exclude réduit la liste P1
        out_filename = f"{current_split}_matchups_{eval_bot_name}_p1exclude.json"
    elif args.quantile_p1 or args.quantile_p2:
        parts = []
        if args.quantile_p1:
            parts.append(f"agent_{args.quantile}")
        if args.quantile_p2:
            parts.append(f"opponent_{args.quantile}")
        qrole = "_".join(parts)
        out_filename = f"{current_split}_matchups_{eval_bot_name}_quantile_{qrole}.json"
    else:
        out_filename = f"{current_split}_matchups_{eval_bot_name}.json"
    out_path = matchups_out_dir / out_filename
    output: Dict[str, Any] = {
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
        "quantile": args.quantile,
        "quantile_owners": list(args.quantile_owners),
        "quantile_frac": float(args.quantile_frac),
        "opponent_mode": str(args.opponent_mode),
        "agent_seat_mode": str(args.agent_seat_mode),
        "agent_seat_bidirectional": bool(args.agent_seat_bidirectional),
        "eval_bot": eval_bot_name,
        "eval_bot_randomness": float(args.eval_bot_randomness),
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
