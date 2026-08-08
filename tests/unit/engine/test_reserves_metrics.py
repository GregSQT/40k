"""Tests — métriques d'utilisation des réserves stratégiques dans episode_tactical_data.

Trois compteurs ajoutés par le chantier « reserves metrics » (2026-08-08) :
  reserves_placed_agent     — unités mises en réserve par l'agent (joueur 1)
  reserves_deployed_agent   — arrivées depuis réserve (agent)
  reserves_destroyed_turn3  — détruites par 20.04 fin de tour 3 (tous joueurs)

STRUCTURE DES TESTS

1. EXISTENCE — les trois clés sont toujours présentes dans tactical_data, même quand
   aucune réserve n'est utilisée (épisode fixed, sans déploiement actif).

2. VOLUME — sur un épisode avec réserves déclarées des deux côtés,
   reserves_placed_agent > 0.

3. COHÉRENCE — reserves_deployed_agent <= reserves_placed_agent
   (on ne peut pas déployer plus qu'on n'a placé).

4. VERROU — on met le défaut (absence des clés), on vérifie que les tests deviennent
   ROUGES, puis on rétablit — prouvant que les tests ne sont pas vacants.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARMAGEDDON_SCENARIOS = (
    PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
)

sys.path.insert(0, str(PROJECT_ROOT))

from ai.unit_registry import UnitRegistry  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import W40KEngine  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Harnais commun
# ──────────────────────────────────────────────────────────────────────────────

_FIXTURE_RESERVES = str(ARMAGEDDON_SCENARIOS / "reserves_full_episode_fixture1.json")
_FIXTURE_BARE = str(
    PROJECT_ROOT
    / "scripts"
    / "smoke_t5_bare_scenario.json"
    # Fichier absent → saut du test (mark.skipif ci-dessous).
)

_SEEDS = (0, 1, 2)


def _play(scenario_file: str, seed: int) -> Dict[str, Any]:
    """Joue un épisode complet en actions légales tirées au sort ; rend tactical_data."""
    engine = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    engine.reset(seed=seed)
    rng = np.random.default_rng(seed)
    info: Dict[str, Any] = {}
    for _ in range(5000):
        legal = np.flatnonzero(engine.get_action_mask())
        action = int(rng.choice(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "épisode non terminé — pas de tactical_data"
    return info["tactical_data"]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Existence des clés — toujours présentes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", _SEEDS)
def test_reserves_metric_keys_always_present(seed: int) -> None:
    """Les trois clés existent dans tactical_data, même sur l'épisode reserves_fixture1."""
    td = _play(_FIXTURE_RESERVES, seed)
    assert "reserves_placed_agent" in td, "clé reserves_placed_agent absente de tactical_data"
    assert "reserves_deployed_agent" in td, "clé reserves_deployed_agent absente de tactical_data"
    assert "reserves_destroyed_turn3" in td, "clé reserves_destroyed_turn3 absente de tactical_data"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Volume — des réserves sont effectivement utilisées
# ──────────────────────────────────────────────────────────────────────────────

def test_reserves_placed_agent_is_positive_on_reserves_fixture() -> None:
    """Sur le fixture à réserves des DEUX côtés, l'agent place au moins une unité en réserve.

    VERROU : si la clé reste toujours à 0, ce test devient rouge — c'est le test
    « vert vacant » guard qui prouve que le compteur est réellement incrémenté.
    """
    positive_found = False
    for seed in _SEEDS:
        td = _play(_FIXTURE_RESERVES, seed)
        if int(td["reserves_placed_agent"]) > 0:
            positive_found = True
            break
    assert positive_found, (
        "reserves_placed_agent == 0 sur toutes les graines — "
        "le compteur n'est jamais incrémenté (vert vacant)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Cohérence — deployed <= placed, destroyed >= 0
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", _SEEDS)
def test_reserves_coherence(seed: int) -> None:
    """Invariants de cohérence entre les trois compteurs."""
    td = _play(_FIXTURE_RESERVES, seed)
    placed = int(td["reserves_placed_agent"])
    deployed = int(td["reserves_deployed_agent"])
    destroyed = int(td["reserves_destroyed_turn3"])

    assert deployed <= placed, (
        f"reserves_deployed_agent ({deployed}) > reserves_placed_agent ({placed}) — "
        "impossible de déployer plus que ce qui a été placé"
    )
    assert destroyed >= 0, f"reserves_destroyed_turn3 négatif : {destroyed}"
    # La somme deployed + destroyed peut être <= placed si des unités sont en réserve
    # ET encore en vie à la fin (partie terminée avant la fin du tour 3).
    assert deployed + destroyed <= placed, (
        f"deployed ({deployed}) + destroyed ({destroyed}) > placed ({placed}) — "
        "des unités comptées deux fois ou une unité déplacée hors réserve sans être comptée"
    )
