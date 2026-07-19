"""V11 T4 — Peuplement du deploy-pool depuis les deployment_zones du terrain.

Le fix T4 peuple `pool_set` depuis `deploy_pools` sans exiger le NOM legacy `deployment_zone`
(nécessaire pour le déploiement `random`/`active` de la banque, dont les zones viennent du terrain).

Deux verrous complémentaires :
- **Fix** : un scénario à zones-terrain + `deployment_type: random` obtient bien un pool
  (plus de `ValueError "No deployment pool for player ..."`).
- **Neutralité PvP (miroir strict)** : un scénario à zones-terrain + placement FIXE dont les
  unités sont posées HORS polygone se charge SANS erreur — le placement fixe n'est confiné qu'à
  la voie legacy nommée (config/deployment/<board>/<zone>). Régression du 2026-07-15 : le
  peuplement du pool avait activé à tort la validation de zone sur le flux PvP fixe.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BOARD_SCEN_DIR = PROJECT_ROOT / "config" / "board" / "44x60x5" / "scenario"
BANK_DIR = PROJECT_ROOT / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"


def _load(scenario_file: str):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=0)
    return eng


@pytest.mark.parametrize("scen", ["scenario_pvp_test.json", "scenario_pvp_test_fight.json"])
def test_pvp_fixed_placement_terrain_zones_loads(scen):
    """PvP : placement fixe hors zone terrain → chargement OK (neutralité, pas de durcissement)."""
    eng = _load(str(BOARD_SCEN_DIR / scen))
    assert eng.game_state["units"], "aucune unité chargée"


def test_terrain_zone_random_deployment_gets_pool():
    """Banque : deployment_type random + zones terrain → pool peuplé, reset sans erreur."""
    eng = _load(str(BANK_DIR / "scenario_training_armageddon.json"))
    pools = eng.config.get("deployment_pools")
    assert isinstance(pools, dict) and sorted(pools.keys()) == [1, 2]
