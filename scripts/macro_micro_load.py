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
from shared.json_atomic import write_json_atomic
from ai.unit_registry import UnitRegistry
from engine.w40k_core import W40KEngine
from engine.phase_handlers.fight_handlers import fight_v11_current_pool


def _read_proc_self_io() -> Dict[str, int]:
    """
    Read per-process IO counters from /proc/self/io.

    Linux-only by construction (ce script importe deja `resource`, module Unix-only).
    L'absence du fichier ou d'un compteur est une ERREUR : rapporter 0 rendrait une
    metrique indisponible indistinguable d'une mesure a zero.
    """
    io_path = "/proc/self/io"
    if not os.path.exists(io_path):
        raise RuntimeError(
            f"{io_path} is required to measure per-process IO (Linux-only benchmark)"
        )
    data: Dict[str, int] = {}
    with open(io_path, "r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            data[parts[0].strip()] = int(parts[1].strip())
    return data


def _capture_metrics_snapshot() -> Dict[str, float]:
    """
    Capture a metrics snapshot for delta computation.

    Pas de compteur reseau : /proc/net/dev est SYSTEME (tout l'hote), donc non
    attribuable a ce process. Une charge purement locale y relevait plusieurs Mo de
    trafic appartenant a d'autres processus — une metrique de capacite fausse.

    `process_peak_rss_kb` = ru_maxrss, high-water mark du PROCESS ENTIER depuis son
    demarrage (interpreteur + imports torch/sb3 + moteur compris), monotone et non
    remise a zero. C'est VOLONTAIREMENT l'empreinte totale : pour du capacity planning
    on dimensionne la machine sur ce que le process occupe en pic, pas sur le delta de
    la seule boucle de charge. Ce n'est donc PAS un delta et n'est pas soustrait.
    """
    ru_self = resource.getrusage(resource.RUSAGE_SELF)
    io_data = _read_proc_self_io()
    return {
        "wall_time": time.time(),
        "cpu_time": time.process_time(),
        "process_peak_rss_kb": float(ru_self.ru_maxrss),
        "io_read_bytes": float(require_key(io_data, "read_bytes")),
        "io_write_bytes": float(require_key(io_data, "write_bytes")),
    }


def _delta_metrics(start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
    """
    Compute deltas between two snapshots.

    `process_peak_rss_kb` est un PIC absolu du process (imports compris), pas un delta :
    on prend la valeur finale telle quelle. Voir _capture_metrics_snapshot.
    """
    return {
        "wall_time_sec": end["wall_time"] - start["wall_time"],
        "cpu_time_sec": end["cpu_time"] - start["cpu_time"],
        "process_peak_rss_kb": end["process_peak_rss_kb"],
        "io_read_bytes": end["io_read_bytes"] - start["io_read_bytes"],
        "io_write_bytes": end["io_write_bytes"] - start["io_write_bytes"],
    }


def _deployable_units_slot(game_state: dict) -> Tuple[dict, object]:
    """
    Return (container, key) pointing at the deployable-unit list of the current deployer.
    `deployable_units` is keyed by player, int or str depending on the serialization path:
    the caller must write back on the very key it read, never on an invented one.
    """
    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = int(require_key(deployment_state, "current_deployer"))
    deployable_units = require_key(deployment_state, "deployable_units")
    for key in (current_deployer, str(current_deployer)):
        if key in deployable_units:
            return deployable_units, key
    raise KeyError(f"deployable_units missing player {current_deployer}")


def _get_activation_pool(game_state: dict) -> List[str]:
    """
    Return the active activation pool based on the current phase/subphase.
    Raises if required data is missing to avoid silent fallbacks.
    """
    phase = require_key(game_state, "phase")
    if phase == "deployment":
        # Le pool de deploiement est deployment_state["deployable_units"][current_deployer] :
        # action_decoder deploie eligible_units[0], donc son ORDRE pilote la selection.
        container, key = _deployable_units_slot(game_state)
        return [str(uid) for uid in container[key]]
    if phase == "command":
        return require_key(game_state, "command_activation_pool")
    if phase == "move":
        return require_key(game_state, "move_activation_pool")
    if phase == "shoot":
        return require_key(game_state, "shoot_activation_pool")
    if phase == "charge":
        return require_key(game_state, "charge_activation_pool")
    if phase == "fight":
        fight_subphase = require_key(game_state, "fight_subphase")
        if fight_subphase not in ("pile_in", "consolidate", "fight"):
            raise ValueError(f"Unsupported fight_subphase: {fight_subphase}")
        # V11 : aucun pool d'activation n'est stocke en phase fight. Le pool eligible est
        # derive a la volee (miroir lecture-seule des drivers fight_v11_*).
        return fight_v11_current_pool(game_state)
    raise ValueError(f"Unsupported phase: {phase}")


def _prioritize_unit_in_pool(pool: List[str], unit_id: str) -> List[str]:
    """
    Move unit_id to the front of the pool.

    L'unite DOIT appartenir au pool : l'appelant la tire du pool lu juste avant.
    Retourner le pool inchange masquerait une desynchronisation entre la lecture et
    la priorisation — donc erreur explicite.
    """
    if unit_id not in pool:
        raise ValueError(f"Unit {unit_id!r} is not in the activation pool: {pool}")
    return [unit_id] + [u for u in pool if u != unit_id]


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
    # Budget explicite de l'operateur (on ecourte volontairement la charge) VS garde
    # anti-runaway derivee du moteur : les deux se comptent par tour, mais un depassement
    # de la garde est un BUG (la production leve, cf. env_wrappers), pas une fin normale.
    operator_budget = max_steps_per_turn is not None
    if max_steps_per_turn is None:
        # Derive des figurines en jeu : n'existe qu'apres reset().
        max_steps_per_turn = engine.get_turn_step_limit()
    steps = 0
    turn_steps = 0
    turn_key: Optional[Tuple[int, int]] = None
    while True:
        game_state = engine.game_state
        current_player = require_key(game_state, "current_player")
        # Le budget porte sur les activations d'UN joueur sur UN tour (meme portee que
        # compute_turn_step_limit) : le compteur repart a chaque changement de main.
        current_turn_key = (int(require_key(game_state, "turn")), int(current_player))
        if current_turn_key != turn_key:
            turn_key = current_turn_key
            turn_steps = 0
        if game_state.get("game_over"):
            break

        if turn_steps >= max_steps_per_turn:
            if not operator_budget:
                raise RuntimeError(
                    f"Turn step budget exceeded: {turn_steps} steps for player "
                    f"{current_player} on turn {current_turn_key[0]} "
                    f"(limit {max_steps_per_turn}) — engine loop suspected"
                )
            break

        should_apply_macro = (
            macro_both or current_player == macro_player
        ) and (steps % macro_every_steps == 0)

        if should_apply_macro:
            pool = _get_activation_pool(game_state)
            phase = require_key(game_state, "phase")
            # V11 : le pool fight est derive read-only (fight_v11_current_pool), il n'existe
            # aucune cle d'etat a reordonner. La lecture ci-dessus exerce deja le cout de
            # derivation ; tirer un choix ne ferait que consommer le RNG sans effet.
            if pool and phase != "fight":
                if phase == "shoot" and game_state.get("active_shooting_unit") is not None:
                    # active_shooting_unit est TOUJOURS dans shoot_activation_pool par contrat
                    # moteur : elle n'y entre que si deja presente (shooting_unit_activation_start
                    # -> unit_not_in_pool), en sort en meme temps que le retrait du pool (fin
                    # d'activation -> reaffectee a pool[0] ou supprimee ; mort -> clear atomique).
                    # _prioritize_unit_in_pool ne peut donc pas lever ici.
                    active_unit = str(game_state["active_shooting_unit"])
                    updated_pool = _prioritize_unit_in_pool(pool, active_unit)
                else:
                    chosen_unit = random.choice(pool)
                    updated_pool = _prioritize_unit_in_pool(pool, chosen_unit)
                if phase == "deployment":
                    container, key = _deployable_units_slot(game_state)
                    container[key] = updated_pool
                elif phase == "command":
                    game_state["command_activation_pool"] = updated_pool
                elif phase == "move":
                    game_state["move_activation_pool"] = updated_pool
                elif phase == "shoot":
                    game_state["shoot_activation_pool"] = updated_pool
                elif phase == "charge":
                    game_state["charge_activation_pool"] = updated_pool
                else:
                    raise ValueError(f"Unsupported phase: {phase}")

        mask = engine.get_action_mask()
        action = _select_random_action(mask)
        _, _, terminated, truncated, _ = engine.step(action)
        steps += 1
        turn_steps += 1
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
    parser.add_argument(
        "--max-steps-per-turn",
        type=int,
        help="Operator budget of steps per player-turn (default: engine anti-runaway guard)",
    )
    parser.add_argument(
        "--trace-python-memory",
        action="store_true",
        help=(
            "Track Python allocations with tracemalloc. WARNING: measured ~9.6x CPU "
            "overhead — the reported CPU time then includes the tracing itself."
        ),
    )
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
        training_n_envs=1,  # UN environnement, joue en serie (engine/episode_schedule.py)
    )

    total_steps = 0
    # tracemalloc instrumente CHAQUE allocation : mesure ~9.6x le CPU sur ce bench. Il est
    # donc opt-in, sinon la metrique CPU rapportee serait surtout celle de l'instrument.
    if args.trace_python_memory:
        tracemalloc.start()
    metrics_start = _capture_metrics_snapshot()
    for ep in range(1, args.episodes + 1):
        steps = run_episode(
            engine=engine,
            macro_player=args.macro_player,
            macro_every_steps=args.macro_every_steps,
            # None = budget par tour du moteur lui-meme (derive des figurines en jeu, donc
            # resolu apres reset), pour exercer la meme borne que la production.
            max_steps_per_turn=args.max_steps_per_turn,
            macro_both=args.macro_both,
        )
        total_steps += steps
        print(f"[episode {ep}] steps={steps}")
    metrics_end = _capture_metrics_snapshot()
    metrics_delta = _delta_metrics(metrics_start, metrics_end)
    py_peak_kb: Optional[float] = None
    if args.trace_python_memory:
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        py_peak_kb = peak_mem / 1024
    if metrics_delta["wall_time_sec"] <= 0:
        raise ValueError("Elapsed time must be > 0")
    steps_per_sec = total_steps / metrics_delta["wall_time_sec"]
    process_peak_rss_mb = metrics_delta["process_peak_rss_kb"] / 1024
    io_read_mb = metrics_delta["io_read_bytes"] / (1024 * 1024)
    io_write_mb = metrics_delta["io_write_bytes"] / (1024 * 1024)
    print("--------------------------")
    print(f"Steps : {total_steps} ({steps_per_sec:.2f} steps/sec)")
    print(f"Wall time : {metrics_delta['wall_time_sec']:.2f} seconds")
    print(f"CPU time : {metrics_delta['cpu_time_sec']:.2f} seconds")
    print(f"Process RSS peak : {process_peak_rss_mb:.2f} Mb (whole process, imports included)")
    print(f"Disk read : {io_read_mb:.2f} Mb")
    print(f"Disk write : {io_write_mb:.2f} Mb")
    if py_peak_kb is not None:
        print(f"Python heap peak : {py_peak_kb / 1024:.2f} Mb (tracemalloc: CPU time inflated)")
    if args.metrics_out:
        payload = {
            "episodes": args.episodes,
            "total_steps": total_steps,
            "steps_per_sec": steps_per_sec,
            "metrics": metrics_delta,
        }
        # Absent du payload si non mesure : une cle a 0 se lirait comme une mesure.
        if py_peak_kb is not None:
            payload["python_memory_peak_kb"] = py_peak_kb
        write_json_atomic(args.metrics_out, payload)


if __name__ == "__main__":
    main()
