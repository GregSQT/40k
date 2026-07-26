"""Verrou du scheduler par-épisode fixed↔active (`deployment_mode_schedule`).

Pilote le VRAI W40KEngine sur `scenario_fixed_brawl_sm_orks.json` et vérifie :
  - active_ratio 0.0/0.0  → tous les épisodes en 'fixed'  (pas de phase 'deployment') ;
  - active_ratio 1.0/1.0  → tous les épisodes en 'active' (phase 'deployment') ;
  - rampe 0.0→1.0         → part 'active' croissante entre 1re et 2e moitié du training.

Le scheduler lit `self.training_config` ; le test l'injecte après construction (`training_only:
false` pour isoler la logique du split de chemin). Chemin gym réel, pas de reconstruction offline.

Rapatrié de `scripts/deployment_mode_schedule_test.py` (2026-07-26) : ce fichier vivait hors de
`tests/` et son nom `*_test.py` ne correspondait pas à `python_files = test_*.py`, donc il n'était
jamais collecté par la suite.
"""

from __future__ import annotations

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCENARIO = os.path.join(PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json")


def _make_env(start: float, end: float, total_episodes: int, freeze: float = 1.0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
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


def _collect_modes(env, n: int) -> list[str]:
    """Rejoue `n` épisodes et renvoie le mode tiré, en vérifiant la cohérence mode ↔ phase moteur."""
    modes = []
    for _ in range(n):
        env.reset(seed=None)
        gs = env.game_state
        mode = gs["deployment_mode_schedule_mode"]
        phase = gs["phase"]
        if mode == "fixed":
            assert phase != "deployment", "mode 'fixed' mais phase 'deployment'"
        else:
            assert phase == "deployment", f"mode 'active' mais phase {phase!r}"
        modes.append(mode)
    return modes


def test_ratio_zero_always_fixed():
    """Borne basse : active_ratio 0.0 → 20/20 épisodes en placement manuel."""
    modes = _collect_modes(_make_env(0.0, 0.0, 100), 20)
    assert set(modes) == {"fixed"}, f"ratio 0.0 devrait ne donner que 'fixed', obtenu {set(modes)}"


def test_ratio_one_always_active():
    """Borne haute : active_ratio 1.0 → 20/20 épisodes avec phase de déploiement."""
    modes = _collect_modes(_make_env(1.0, 1.0, 100), 20)
    assert set(modes) == {"active"}, f"ratio 1.0 devrait ne donner que 'active', obtenu {set(modes)}"


def test_linear_ramp_increases_active_share():
    """Rampe 0→1 : la 2e moitié du training contient strictement plus d'épisodes 'active'."""
    modes = _collect_modes(_make_env(0.0, 1.0, 60), 60)
    first = sum(1 for m in modes[:30] if m == "active")
    second = sum(1 for m in modes[30:] if m == "active")
    assert second > first, f"rampe non croissante : 1re moitié={first} >= 2e moitié={second}"
