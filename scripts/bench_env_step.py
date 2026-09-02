#!/usr/bin/env python3
"""Bench offline ms/step — chemin exact de ai/train.py (config x1_long, scenario bot, resolution 1).

USAGE
-----
    source .venv/bin/activate
    python3 scripts/bench_env_step.py

    # Avec profiler cProfile :
    python3 scripts/bench_env_step.py --profile

    # Changer le nombre de steps :
    python3 scripts/bench_env_step.py --steps 300

POURQUOI CE SCRIPT
------------------
Aucune optimisation de la Phase 1 ne peut être validée sans une mesure avant/après sur le
CHEMIN EXACT du run d'entraînement. `time/fps` de SB3 est une moyenne cumulée depuis le début
du run, contaminée par les resets, la rampe self-play et la courbe d'apprentissage (parties plus
longues en fin de run). Ce banc isole la boucle `step()` sur UN seul env, seed fixe, sans
VecNormalize ni SubprocVecEnv, en reproduisant la même pile de wrappers que `train.py`.

CHEMIN REPRODUIT
----------------
W40KEngine (bot, armageddon, x1_long, résolution 1)
  └─ ActionMasker (sb3_contrib)
       └─ BotControlledEnv
            └─ Monitor (stable-baselines3)

Le masque est TIRÉ, une action valide choisie aléatoirement dans ce masque, puis exécutée —
exactement ce que MaskablePPO fait pendant le rollout (sans le forward GPU et les syncs SB3).

PIÈGE DE MESURE
---------------
Le run x1_long --etape P1 (PID 4198) tourne pendant ce bench — la ligne de base §6 est prise
avec CONTENTION CPU (workers du run + learner actif). Les ms/step du bench hors contention
seront légèrement meilleures. Inscrire systématiquement le contexte dans le journal §6.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import random
import sys
import time

import numpy as np
from sb3_contrib.common.maskable.utils import get_action_masks

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _seed_randomness(seed: int) -> None:
    """Ensemence le module random global pour rendre random.choice reproductible run-à-run.

    Les sources de non-déterminisme du bench sont toutes dans ce module :
    - engine/w40k_core.py: random.choice(self._scenario_files) à chaque reset
    - ai/evaluation_bots.py + env_wrappers.py:139 : random.choice(actions) pendant les tours bot
    Le numpy.random.Generator passé à _run_steps est déjà isolé ; seul le module global compte.
    """
    random.seed(seed)


def _get_current_scenario(env) -> str:
    """Retourne le basename du scénario actif depuis le stack de wrappers Monitor→…→W40KEngine."""
    scenario_file = getattr(env.unwrapped, "_current_scenario_file", None)
    if scenario_file is None:
        return "<unknown>"
    return os.path.basename(scenario_file)


def _build_env():
    """Construit la pile de wrappers identique à train.py (chemin single-env, n_envs=1)."""
    from config_loader import get_config_loader
    from ai.unit_registry import UnitRegistry
    from ai.training_utils import (
        get_scenario_list_for_phase,
        build_self_play_kwargs,
    )
    from ai.env_wrappers import BotControlledEnv
    from ai.train import _build_training_bots_from_config
    from stable_baselines3.common.monitor import Monitor
    from sb3_contrib import MaskablePPO  # noqa: F401 — force le chargement des dépendances
    from sb3_contrib.common.wrappers import ActionMasker
    from engine.w40k_core import W40KEngine

    AGENT_KEY = "ArmageddonAgent_x1"
    TRAINING_CONFIG_NAME = "x1_long"
    REWARDS_CONFIG_NAME = AGENT_KEY  # par défaut dans train.py: rewards_config = agent
    SCENARIO_TYPE = "bot"
    N_ENVS = 1

    config = get_config_loader()
    training_config = config.load_agent_training_config(AGENT_KEY, TRAINING_CONFIG_NAME)

    unit_registry = UnitRegistry()

    scenario_list = get_scenario_list_for_phase(
        config, AGENT_KEY, TRAINING_CONFIG_NAME, scenario_type=SCENARIO_TYPE
    )
    if not scenario_list:
        raise RuntimeError(
            f"Aucun scénario trouvé pour agent={AGENT_KEY}, config={TRAINING_CONFIG_NAME}, "
            f"type={SCENARIO_TYPE}. Vérifier config/agents/{AGENT_KEY}/scenarios/training/."
        )

    training_bots = _build_training_bots_from_config(training_config)

    base_env = W40KEngine(
        rewards_config=REWARDS_CONFIG_NAME,
        training_config_name=TRAINING_CONFIG_NAME,
        controlled_agent=REWARDS_CONFIG_NAME,
        active_agents=None,
        scenario_file=scenario_list[0],
        scenario_files=scenario_list,
        unit_registry=unit_registry,
        quiet=True,
        gym_training_mode=True,
        debug_mode=False,
        training_n_envs=N_ENVS,
        training_episode_start_index=0,
    )

    def mask_fn(env):
        return env.get_action_mask()

    masked_env = ActionMasker(base_env, mask_fn)

    opponent_mix_config = training_config.get("opponent_mix")  # get allowed: optionnel
    wrapped_env = BotControlledEnv(
        masked_env,
        bots=training_bots,
        unit_registry=unit_registry,
        agent_seat_mode=training_config["agent_seat_mode"],
        global_seed=training_config.get("seed"),  # get allowed: optionnel
        **build_self_play_kwargs(opponent_mix_config, env_rank=0),
    )

    return Monitor(wrapped_env)


def _run_steps(
    env,
    n_steps: int,
    rng: np.random.Generator,
    scenarios: list[str] | None = None,
) -> list[float]:
    """Exécute n_steps masqués aléatoires, retourne la liste des wall-times par step.

    L'env doit être dans un état valide (reset déjà appelé par l'appelant).
    Les resets inter-épisodes sont appelés mais PAS inclus dans les step_times.
    Si scenarios est fourni, le basename du scénario actif après chaque reset y est ajouté.
    """
    step_times: list[float] = []

    for _ in range(n_steps):
        t0 = time.perf_counter()
        mask = get_action_masks(env)
        valid = np.flatnonzero(mask)
        action = int(rng.choice(valid))
        obs, _reward, terminated, truncated, _info = env.step(action)
        step_times.append(time.perf_counter() - t0)

        if terminated or truncated:
            env.reset()
            if scenarios is not None:
                scenarios.append(_get_current_scenario(env))

    return step_times


def _bench_run(seed: int = 42, n_steps: int = 600) -> tuple[list[str], int, float]:
    """Construit l'env, exécute le bench, retourne (séquence_scénarios, n_resets, médiane_ms).

    Conçu pour les tests de déterminisme : deux appels avec le même seed doivent retourner
    la même séquence de scénarios et le même n_resets.
    """
    _seed_randomness(seed)
    env = _build_env()
    rng = np.random.default_rng(seed)

    # Chauffe (warm-up altère l'état de random ; on re-ensemence avant le bench réel)
    env.reset()
    _run_steps(env, 5, np.random.default_rng(0))

    _seed_randomness(seed)
    env.reset()

    scenarios: list[str] = [_get_current_scenario(env)]
    step_times = _run_steps(env, n_steps, rng, scenarios=scenarios)
    env.close()

    arr = np.array(step_times) * 1000.0
    n_resets = len(scenarios) - 1  # scénario initial + 1 entrée par reset
    return scenarios, n_resets, float(np.median(arr))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bench ms/step env — chemin exact train.py")
    parser.add_argument("--steps", type=int, default=600, help="Nombre de steps (défaut 600)")
    parser.add_argument("--profile", action="store_true", help="Activer cProfile")
    parser.add_argument("--top", type=int, default=20, help="Top N fonctions cProfile (défaut 20)")
    parser.add_argument("--seed", type=int, default=42, help="Graine aléatoire (défaut 42)")
    args = parser.parse_args()

    print(f"Bench env_step — {args.steps} steps, seed={args.seed}, profile={args.profile}")
    print("Construction de l'environnement…")
    env = _build_env()
    print("Environnement prêt.\n")

    rng = np.random.default_rng(args.seed)

    # Chauffe : reset + 5 steps pour initialiser les caches (JIT, LoS, etc.)
    env.reset()
    _run_steps(env, 5, np.random.default_rng(0))
    # Re-ensemencer random AVANT le reset qui démarre le bench : le warm-up altère l'état
    # de random.choice (sélection de scénarios, actions bot), donc sans ce re-seed la séquence
    # de scénarios varie d'un run à l'autre même à --seed identique.
    _seed_randomness(args.seed)
    env.reset()  # Remet l'env dans un état frais et répétable pour le bench réel

    pr: cProfile.Profile | None = None
    if args.profile:
        pr = cProfile.Profile()
        pr.enable()

    t_total = time.perf_counter()
    step_times = _run_steps(env, args.steps, rng)
    t_total = time.perf_counter() - t_total

    if pr is not None:
        pr.disable()

    # Statistiques
    arr = np.array(step_times) * 1000.0  # → ms
    print(f"{'─'*50}")
    print(f"Steps mesurés  : {len(arr)}")
    print(f"Wall total     : {t_total * 1000:.1f} ms")
    print(f"ms/step        : {arr.mean():.2f} ± {arr.std():.2f}")
    print(f"Médiane        : {np.median(arr):.2f} ms")
    print(f"P95            : {np.percentile(arr, 95):.2f} ms")
    print(f"P99            : {np.percentile(arr, 99):.2f} ms")
    print(f"FPS env        : {1000.0 / arr.mean():.0f} steps/s")
    print(f"{'─'*50}")

    if pr is not None:
        sio = io.StringIO()
        ps = pstats.Stats(pr, stream=sio).sort_stats(pstats.SortKey.CUMULATIVE)
        ps.print_stats(args.top)
        print("\ncProfile (cumtime) — top", args.top)
        print(sio.getvalue())

    env.close()


if __name__ == "__main__":
    main()
