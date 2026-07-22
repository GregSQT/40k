#!/usr/bin/env python3
"""Verrou du scheduler par-épisode fixed↔active (deployment_mode_schedule).

Pilote le VRAI W40KEngine et vérifie, sur le scénario `scenario_fixed_brawl_sm_orks.json` :
  - active_ratio 0.0/0.0  → tous les épisodes en 'fixed'  (phase 'command', 0 sentinelle) ;
  - active_ratio 1.0/1.0  → tous les épisodes en 'active' (phase 'deployment', unités sentinelle) ;
  - rampe 0.0→1.0         → part 'active' croissante entre 1re et 2e moitié du training.

Le scheduler lit `self.training_config` ; le test l'injecte après construction (training_only:false
pour isoler la logique du split de chemin). Chemin gym réel, pas de reconstruction offline.

Lancement : python3 scripts/deployment_mode_schedule_test.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.training_utils import setup_imports
from ai.unit_registry import UnitRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")


def make_env(W40KEngine, ur, start, end, total_episodes, freeze=1.0):
    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    # Injection du contrat scheduler (training_only:false = on ne dépend pas du split de chemin).
    env.training_config = dict(env.training_config)
    env.training_config["total_episodes"] = total_episodes
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": start,
        "active_ratio_end": end,
        "schedule": "linear",
        "freeze_after_progress": freeze,
    }
    return env


def collect_modes(env, n):
    modes = []
    for _ in range(n):
        env.reset(seed=None)
        modes.append(env.game_state["deployment_mode_schedule_mode"])
        # cohérence mode ↔ phase du moteur
        ph = env.game_state["phase"]
        m = env.game_state["deployment_mode_schedule_mode"]
        if m == "fixed" and ph == "deployment":
            raise AssertionError("mode 'fixed' mais phase 'deployment'")
        if m == "active" and ph != "deployment":
            raise AssertionError(f"mode 'active' mais phase {ph!r}")
    return modes


def main() -> int:
    random.seed(123)
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()

    # Borne 0 : toujours fixed
    env = make_env(W40KEngine, ur, 0.0, 0.0, 100)
    modes = collect_modes(env, 20)
    if any(m != "fixed" for m in modes):
        raise AssertionError(f"ratio 0.0 devrait donner que 'fixed', obtenu {set(modes)}")
    print(f"✅ ratio 0.0/0.0 : 20/20 'fixed'")

    # Borne 1 : toujours active
    env = make_env(W40KEngine, ur, 1.0, 1.0, 100)
    modes = collect_modes(env, 20)
    if any(m != "active" for m in modes):
        raise AssertionError(f"ratio 1.0 devrait donner que 'active', obtenu {set(modes)}")
    print(f"✅ ratio 1.0/1.0 : 20/20 'active'")

    # Rampe 0→1 : la 2e moitié doit contenir strictement plus d'épisodes 'active' que la 1re.
    env = make_env(W40KEngine, ur, 0.0, 1.0, 60)
    modes = collect_modes(env, 60)
    first = sum(1 for m in modes[:30] if m == "active")
    second = sum(1 for m in modes[30:] if m == "active")
    print(f"   rampe 0→1 (60 ép.) : 'active' 1re moitié={first}, 2e moitié={second}")
    if not (second > first):
        raise AssertionError(f"rampe non croissante : 1re={first} >= 2e={second}")
    print(f"✅ rampe 0→1 : part 'active' croissante ({first} → {second})")

    print("\n✅ VERROU OK : scheduler par-épisode fixed↔active fonctionnel (bornes + rampe).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
