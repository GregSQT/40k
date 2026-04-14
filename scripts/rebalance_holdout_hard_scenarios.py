#!/usr/bin/env python3
"""
Rebalance holdout_hard scenarios by reassigning opponent rosters from matchup matrix.

This script reads:
- Scenario files in config/agents/<agent>/scenarios/holdout_hard/scenario_bot-*.json
- Opponent matchup matrix in config/agents/<agent>/rosters/<scale>/matchups/holdout_hard_matchups.json

It then assigns opponent rosters to each scenario so projected P1 win rates are closer to a
target band, reducing "too easy / too hard" outliers.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _require_key(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Required key '{key}' is missing")
    return mapping[key]


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _collect_scenario_files(agent_key: str) -> List[Path]:
    scenario_dir = PROJECT_ROOT / "config" / "agents" / agent_key / "scenarios" / "holdout_hard"
    if not scenario_dir.exists():
        raise FileNotFoundError(f"Scenario directory not found: {scenario_dir}")
    files = sorted(scenario_dir.glob("scenario_bot-*.json"), key=lambda p: p.name)
    if len(files) == 0:
        raise FileNotFoundError(f"No scenario_bot-*.json found in {scenario_dir}")
    return files


def _collect_opponent_rosters_by_id(agent_key: str, scale: str) -> Dict[str, str]:
    roster_dir = PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / "holdout_hard"
    if not roster_dir.exists():
        raise FileNotFoundError(f"Opponent roster directory not found: {roster_dir}")
    mapping: Dict[str, str] = {}
    for roster_path in sorted(roster_dir.glob("opponent_holdout_hard_roster_*.json"), key=lambda p: p.name):
        if "_kpis" in roster_path.name or "_matchups" in roster_path.name:
            continue
        payload = _load_json(roster_path)
        roster_id_raw = _require_key(payload, "roster_id")
        if not isinstance(roster_id_raw, str):
            raise TypeError(f"roster_id must be string in {roster_path}")
        roster_id = str(roster_id_raw)
        if roster_id in mapping:
            raise ValueError(f"Duplicate roster_id '{roster_id}' in holdout_hard opponent rosters")
        mapping[roster_id] = roster_path.name
    if len(mapping) == 0:
        raise FileNotFoundError(f"No usable opponent rosters found in {roster_dir}")
    return mapping


def _resolve_roster_id_from_ref(agent_key: str, scale: str, roster_ref: str, roster_kind: str) -> str:
    if not isinstance(roster_ref, str):
        raise TypeError(f"{roster_kind} roster ref must be string (got {type(roster_ref).__name__})")
    normalized = roster_ref.strip().replace("\\", "/")
    if "/" not in normalized:
        raise ValueError(f"Invalid roster ref: {roster_ref!r}")
    split, _, filename = normalized.partition("/")
    if split != "holdout_hard":
        raise ValueError(f"Expected holdout_hard split in roster ref, got {roster_ref!r}")

    if roster_kind == "agent":
        roster_path = (
            PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / split / filename
        )
    elif roster_kind == "opponent":
        roster_path = (
            PROJECT_ROOT / "config" / "agents" / "_p2_rosters" / scale / split / filename
        )
    else:
        raise ValueError(f"Invalid roster_kind: {roster_kind!r}")

    if not roster_path.exists():
        raise FileNotFoundError(f"Roster path does not exist for ref {roster_ref!r}: {roster_path}")
    payload = _load_json(roster_path)
    roster_id = _require_key(payload, "roster_id")
    if not isinstance(roster_id, str):
        raise TypeError(f"roster_id must be string in {roster_path}")
    return roster_id


def _load_matchup_matrix(agent_key: str, scale: str, matchups_file: str) -> Dict[str, Dict[str, float]]:
    matchups_path = (
        PROJECT_ROOT / "config" / "agents" / agent_key / "rosters" / scale / "matchups" / matchups_file
    )
    if not matchups_path.exists():
        raise FileNotFoundError(f"Matchups file not found: {matchups_path}")
    payload = _load_json(matchups_path)
    matchups_raw = _require_key(payload, "matchups")
    if not isinstance(matchups_raw, dict):
        raise TypeError("matchups must be a dictionary")
    matrix: Dict[str, Dict[str, float]] = {}
    for p1_id, versus in matchups_raw.items():
        if not isinstance(p1_id, str):
            raise TypeError("matchups keys must be strings")
        if not isinstance(versus, dict):
            raise TypeError(f"matchups[{p1_id}] must be a dictionary")
        matrix[p1_id] = {}
        for p2_id, stats in versus.items():
            if not isinstance(p2_id, str):
                raise TypeError(f"matchups[{p1_id}] opponent key must be string")
            if not isinstance(stats, dict):
                raise TypeError(f"matchups[{p1_id}][{p2_id}] must be a dictionary")
            win_rate = _require_key(stats, "win_rate")
            if not isinstance(win_rate, (int, float)):
                raise TypeError(
                    f"matchups[{p1_id}][{p2_id}].win_rate must be numeric (got {type(win_rate).__name__})"
                )
            wr = float(win_rate)
            if wr < 0.0 or wr > 1.0:
                raise ValueError(f"Invalid win_rate {wr} for pair ({p1_id}, {p2_id})")
            matrix[p1_id][p2_id] = wr
    if len(matrix) == 0:
        raise ValueError("Matchup matrix is empty")
    return matrix


def _compute_mean_p1_win_rate_by_p2(matrix: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """Compute mean P1 win rate versus each P2 roster across all P1 rosters."""
    accum: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for p1_vs in matrix.values():
        for p2_id, wr in p1_vs.items():
            accum[p2_id] = accum.get(p2_id, 0.0) + float(wr)
            counts[p2_id] = counts.get(p2_id, 0) + 1
    means: Dict[str, float] = {}
    for p2_id, total in accum.items():
        n = counts.get(p2_id, 0)
        if n <= 0:
            raise ValueError(f"Invalid matchup count for p2_id={p2_id}")
        means[p2_id] = float(total) / float(n)
    return means


def _parse_csv_list(raw: str, flag_name: str) -> List[str]:
    values = [chunk.strip() for chunk in str(raw).split(",")]
    result = [v for v in values if v]
    if len(result) == 0:
        raise ValueError(f"{flag_name} must contain at least one non-empty value")
    return result


def _parse_csv_weights(raw: str, expected_len: int, flag_name: str) -> List[float]:
    chunks = [chunk.strip() for chunk in str(raw).split(",")]
    if len(chunks) != expected_len:
        raise ValueError(
            f"{flag_name} must have exactly {expected_len} values "
            f"(got {len(chunks)}: {chunks})"
        )
    weights: List[float] = []
    for idx, chunk in enumerate(chunks):
        try:
            value = float(chunk)
        except ValueError as exc:
            raise ValueError(
                f"{flag_name} contains non-numeric value at index {idx}: {chunk!r}"
            ) from exc
        if value < 0.0:
            raise ValueError(f"{flag_name} values must be >= 0 (got {value} at index {idx})")
        weights.append(value)
    total = sum(weights)
    if total <= 0.0:
        raise ValueError(f"{flag_name} total must be > 0")
    return [w / total for w in weights]


def _merge_weighted_matrices(
    matrices: List[Dict[str, Dict[str, float]]],
    weights: List[float],
) -> Dict[str, Dict[str, float]]:
    if len(matrices) == 0:
        raise ValueError("Cannot merge empty matrix list")
    if len(matrices) != len(weights):
        raise ValueError(f"Matrix count and weight count mismatch ({len(matrices)} != {len(weights)})")

    reference_p1_keys = set(matrices[0].keys())
    if len(reference_p1_keys) == 0:
        raise ValueError("Reference matrix has no p1 keys")

    for matrix in matrices[1:]:
        p1_keys = set(matrix.keys())
        if p1_keys != reference_p1_keys:
            raise ValueError("All matrices must share identical p1 roster key sets")

    merged: Dict[str, Dict[str, float]] = {}
    for p1_id in sorted(reference_p1_keys):
        reference_p2_keys = set(matrices[0][p1_id].keys())
        if len(reference_p2_keys) == 0:
            raise ValueError(f"Reference matrix has no p2 keys for p1_id={p1_id}")
        for matrix in matrices[1:]:
            p2_keys = set(matrix[p1_id].keys())
            if p2_keys != reference_p2_keys:
                raise ValueError(
                    f"All matrices must share identical p2 roster key sets for p1_id={p1_id}"
                )
        merged[p1_id] = {}
        for p2_id in sorted(reference_p2_keys):
            weighted_wr = 0.0
            for matrix, weight in zip(matrices, weights):
                weighted_wr += float(matrix[p1_id][p2_id]) * float(weight)
            merged[p1_id][p2_id] = float(weighted_wr)
    return merged


def _assignment_cost(
    win_rate: float,
    target: float,
    min_rate: float,
    max_rate: float,
    reuse_count: int,
    max_repeat: int,
) -> float:
    base_cost = abs(win_rate - target)
    out_of_band_penalty = 0.0
    if win_rate < min_rate:
        out_of_band_penalty += (min_rate - win_rate) * 5.0
    elif win_rate > max_rate:
        out_of_band_penalty += (win_rate - max_rate) * 5.0
    reuse_penalty = 0.0
    if reuse_count >= max_repeat:
        reuse_penalty = 10.0 + float(reuse_count - max_repeat + 1)
    return base_cost + out_of_band_penalty + reuse_penalty


def _rebalance(
    scenarios: List[Path],
    matrix: Dict[str, Dict[str, float]],
    opponent_roster_file_by_id: Dict[str, str],
    agent_key: str,
    scale: str,
    target: float,
    min_rate: float,
    max_rate: float,
    max_repeat: int,
    floor_win_rate: float,
    allowed_opponent_ids: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    if max_repeat <= 0:
        raise ValueError(f"max_repeat must be > 0 (got {max_repeat})")

    rows: List[Dict[str, Any]] = []
    for scenario_path in scenarios:
        scenario_payload = _load_json(scenario_path)
        agent_ref = _require_key(scenario_payload, "agent_roster_ref")
        opponent_ref = _require_key(scenario_payload, "opponent_roster_ref")

        p1_id = _resolve_roster_id_from_ref(agent_key, scale, str(agent_ref), "agent")
        current_p2_id = _resolve_roster_id_from_ref(agent_key, scale, str(opponent_ref), "opponent")
        if p1_id not in matrix:
            raise KeyError(f"Agent roster '{p1_id}' from {scenario_path.name} is missing in matchup matrix")

        row = {
            "scenario_path": scenario_path,
            "scenario_name": scenario_path.name,
            "payload": scenario_payload,
            "p1_id": p1_id,
            "current_p2_id": current_p2_id,
        }
        rows.append(row)

    rows.sort(
        key=lambda r: len(matrix[r["p1_id"]]),
    )

    usage_count: Dict[str, int] = {}
    for p2_id in opponent_roster_file_by_id:
        usage_count[p2_id] = 0

    assignments: List[Dict[str, Any]] = []
    for row in rows:
        p1_id = str(row["p1_id"])
        candidates = matrix[p1_id]
        viable_candidates = {p2_id: wr for p2_id, wr in candidates.items() if wr >= floor_win_rate}
        pool = viable_candidates if len(viable_candidates) > 0 else candidates
        best_p2_id: str | None = None
        best_cost = math.inf
        best_wr = -1.0

        for p2_id, wr in pool.items():
            if allowed_opponent_ids is not None and p2_id not in allowed_opponent_ids:
                continue
            if p2_id not in opponent_roster_file_by_id:
                continue
            cost = _assignment_cost(
                win_rate=wr,
                target=target,
                min_rate=min_rate,
                max_rate=max_rate,
                reuse_count=int(usage_count[p2_id]),
                max_repeat=max_repeat,
            )
            if cost < best_cost:
                best_cost = cost
                best_p2_id = p2_id
                best_wr = wr

        if best_p2_id is None:
            raise RuntimeError(
                f"No assignable opponent roster candidate found for scenario {row['scenario_name']} "
                f"(p1_id={p1_id})"
            )

        usage_count[best_p2_id] += 1
        assignments.append(
            {
                "scenario_path": row["scenario_path"],
                "scenario_name": row["scenario_name"],
                "payload": row["payload"],
                "p1_id": p1_id,
                "current_p2_id": row["current_p2_id"],
                "new_p2_id": best_p2_id,
                "predicted_win_rate": float(best_wr),
                "floor_enforced": len(viable_candidates) > 0,
                "floor_unavoidable": len(viable_candidates) == 0,
            }
        )

    assignments.sort(key=lambda a: a["scenario_name"])
    return assignments


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebalance holdout_hard scenarios by reassigning opponent roster refs."
    )
    parser.add_argument("--agent", default="CoreAgent")
    parser.add_argument("--scale", default="150pts")
    parser.add_argument(
        "--eval-mode",
        choices=["agent", "bot"],
        default="agent",
        help=(
            "agent: use single matchup matrix (e.g. agent-vs-agent matrix). "
            "bot: aggregate multiple bot matchup matrices with weights."
        ),
    )
    parser.add_argument("--matchups-file", default="holdout_hard_matchups.json")
    parser.add_argument(
        "--bot-matchups-files",
        default=(
            "holdout_hard_matchups_greedy.json,"
            "holdout_hard_matchups_defensive_smart.json,"
            "holdout_hard_matchups_adaptive.json"
        ),
        help="Comma-separated matchup files used when --eval-mode bot",
    )
    parser.add_argument(
        "--bot-matchups-weights",
        default="0.3333,0.3333,0.3334",
        help="Comma-separated weights aligned with --bot-matchups-files when --eval-mode bot",
    )
    parser.add_argument("--target-win-rate", type=float, default=0.60)
    parser.add_argument("--min-win-rate", type=float, default=0.45)
    parser.add_argument("--max-win-rate", type=float, default=0.75)
    parser.add_argument("--floor-win-rate", type=float, default=0.30)
    parser.add_argument(
        "--min-p1-win-rate-vs-p2",
        type=float,
        default=None,
        help="Optional lower bound for mean p1 win rate vs each p2 roster (filter opponent pool)",
    )
    parser.add_argument(
        "--max-p1-win-rate-vs-p2",
        type=float,
        default=None,
        help="Optional upper bound for mean p1 win rate vs each p2 roster (filter opponent pool)",
    )
    parser.add_argument("--max-repeat-per-opponent", type=int, default=2)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not (0.0 <= args.target_win_rate <= 1.0):
        raise ValueError(f"--target-win-rate must be in [0,1] (got {args.target_win_rate})")
    if not (0.0 <= args.min_win_rate <= 1.0):
        raise ValueError(f"--min-win-rate must be in [0,1] (got {args.min_win_rate})")
    if not (0.0 <= args.max_win_rate <= 1.0):
        raise ValueError(f"--max-win-rate must be in [0,1] (got {args.max_win_rate})")
    if not (0.0 <= args.floor_win_rate <= 1.0):
        raise ValueError(f"--floor-win-rate must be in [0,1] (got {args.floor_win_rate})")
    if args.min_win_rate > args.max_win_rate:
        raise ValueError("--min-win-rate must be <= --max-win-rate")
    if args.min_p1_win_rate_vs_p2 is not None:
        if not (0.0 <= float(args.min_p1_win_rate_vs_p2) <= 1.0):
            raise ValueError(
                f"--min-p1-win-rate-vs-p2 must be in [0,1] (got {args.min_p1_win_rate_vs_p2})"
            )
    if args.max_p1_win_rate_vs_p2 is not None:
        if not (0.0 <= float(args.max_p1_win_rate_vs_p2) <= 1.0):
            raise ValueError(
                f"--max-p1-win-rate-vs-p2 must be in [0,1] (got {args.max_p1_win_rate_vs_p2})"
            )
    if (
        args.min_p1_win_rate_vs_p2 is not None
        and args.max_p1_win_rate_vs_p2 is not None
        and float(args.min_p1_win_rate_vs_p2) > float(args.max_p1_win_rate_vs_p2)
    ):
        raise ValueError("--min-p1-win-rate-vs-p2 must be <= --max-p1-win-rate-vs-p2")

    scenarios = _collect_scenario_files(args.agent)
    if args.eval_mode == "agent":
        matrix = _load_matchup_matrix(args.agent, args.scale, args.matchups_file)
        matrix_source_label = f"mode=agent file={args.matchups_file}"
    else:
        bot_files = _parse_csv_list(args.bot_matchups_files, "--bot-matchups-files")
        bot_weights = _parse_csv_weights(args.bot_matchups_weights, len(bot_files), "--bot-matchups-weights")
        matrices = [
            _load_matchup_matrix(args.agent, args.scale, matchup_file)
            for matchup_file in bot_files
        ]
        matrix = _merge_weighted_matrices(matrices, bot_weights)
        source_details = ", ".join(
            f"{matchup_file}@{weight:.3f}" for matchup_file, weight in zip(bot_files, bot_weights)
        )
        matrix_source_label = f"mode=bot weighted=[{source_details}]"
    opponent_roster_file_by_id = _collect_opponent_rosters_by_id(args.agent, args.scale)

    allowed_opponent_ids: Optional[Set[str]] = None
    if args.min_p1_win_rate_vs_p2 is not None or args.max_p1_win_rate_vs_p2 is not None:
        min_allowed = float(args.min_p1_win_rate_vs_p2) if args.min_p1_win_rate_vs_p2 is not None else 0.0
        max_allowed = float(args.max_p1_win_rate_vs_p2) if args.max_p1_win_rate_vs_p2 is not None else 1.0
        mean_by_p2 = _compute_mean_p1_win_rate_by_p2(matrix)
        allowed: Set[str] = set()
        dropped: List[Tuple[str, float]] = []
        for p2_id, mean_wr in mean_by_p2.items():
            if mean_wr < min_allowed or mean_wr > max_allowed:
                dropped.append((p2_id, mean_wr))
            else:
                allowed.add(p2_id)
        if len(allowed) == 0:
            raise ValueError(
                "Opponent filter removed all p2 rosters. "
                f"Range=[{min_allowed:.3f},{max_allowed:.3f}], means={mean_by_p2}"
            )
        # Keep only rosters available in filesystem mapping.
        allowed = {p2_id for p2_id in allowed if p2_id in opponent_roster_file_by_id}
        if len(allowed) == 0:
            raise ValueError(
                "Opponent filter matched no roster ids present in holdout_hard roster files."
            )
        allowed_opponent_ids = allowed
        print(
            f"Opponent pool filter enabled: mean p1 win rate vs p2 in [{min_allowed:.3f},{max_allowed:.3f}] "
            f"-> kept {len(allowed_opponent_ids)} / {len(mean_by_p2)}"
        )
        if dropped:
            print("Dropped opponent rosters by mean p1 win rate:")
            for p2_id, mean_wr in sorted(dropped, key=lambda item: item[1]):
                print(f"  - {p2_id}: mean_p1_wr={mean_wr:.3f}")

    assignments = _rebalance(
        scenarios=scenarios,
        matrix=matrix,
        opponent_roster_file_by_id=opponent_roster_file_by_id,
        agent_key=args.agent,
        scale=args.scale,
        target=float(args.target_win_rate),
        min_rate=float(args.min_win_rate),
        max_rate=float(args.max_win_rate),
        max_repeat=int(args.max_repeat_per_opponent),
        floor_win_rate=float(args.floor_win_rate),
        allowed_opponent_ids=allowed_opponent_ids,
    )

    print(
        "Proposed holdout_hard opponent assignments "
        f"(target={args.target_win_rate:.3f}, band=[{args.min_win_rate:.3f},{args.max_win_rate:.3f}], "
        f"floor={args.floor_win_rate:.3f}):"
    )
    print(f"Matrix source: {matrix_source_label}")
    for item in assignments:
        change_marker = "==" if item["current_p2_id"] == item["new_p2_id"] else "->"
        floor_note = ""
        if item["floor_unavoidable"]:
            floor_note = " | floor_unavoidable"
        print(
            f"  {item['scenario_name']}: {item['p1_id']} | "
            f"{item['current_p2_id']} {change_marker} {item['new_p2_id']} | "
            f"pred_wr={item['predicted_win_rate']:.3f}{floor_note}"
        )

    if not args.apply:
        print("\nDry run only. Re-run with --apply to write scenario files.")
        return

    for item in assignments:
        payload = item["payload"]
        new_filename = _require_key(opponent_roster_file_by_id, item["new_p2_id"])
        payload["opponent_roster_ref"] = f"holdout_hard/{new_filename}"
        _write_json(item["scenario_path"], payload)

    print("\nApplied updates to holdout_hard scenario files.")


if __name__ == "__main__":
    main()
