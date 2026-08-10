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

import os
from pathlib import Path

import pytest

from tests.unit.engine._config_helpers import bank_training_scenarios

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BOARD_SCEN_DIR = PROJECT_ROOT / "config" / "board" / "44x60x5" / "scenario"


def _load(scenario_file: str):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug", controlled_agent="ArmageddonAgent",
        scenario_file=scenario_file, unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    eng.reset(seed=0)
    return eng


# `scenario_pvp_test_fight.json` a été supprimé le 2026-08-06 avec les autres variantes PvP ;
# `..._sm_tyranids.json` reprend son rôle ici — le grand roster à placement fixe, en regard du
# petit `scenario_pvp_test.json`. Les deux couvrent bien deux tailles de scénario.
@pytest.mark.parametrize(
    "scen", ["scenario_pvp_test.json", "scenario_pvp_test_sm_tyranids.json"]
)
def test_pvp_fixed_placement_terrain_zones_loads(scen):
    """PvP : placement fixe hors zone terrain → chargement OK (neutralité, pas de durcissement)."""
    eng = _load(str(BOARD_SCEN_DIR / scen))
    assert eng.game_state["units"], "aucune unité chargée"


# TOUS les scénarios de la banque : le pool de déploiement SORT des zones du terrain, donc chaque
# terrain est un cas distinct — et ils sont DÉCOUVERTS, pas listés (cf. `bank_training_scenarios`).
@pytest.mark.parametrize("scen", bank_training_scenarios(), ids=os.path.basename)
def test_terrain_zone_random_deployment_gets_pool(scen):
    """Banque : deployment_type random + zones terrain → pool peuplé, reset sans erreur."""
    eng = _load(scen)
    pools = eng.config.get("deployment_pools")
    assert isinstance(pools, dict) and sorted(pools.keys()) == [1, 2]


def _pinned_mode_pools(eng, active_ratio: float):
    """Rejoue un reset avec le mode de mise en place ÉPINGLÉ, rend (mode, zones par joueur)."""
    assert eng.training_config is not None
    eng.training_config = dict(eng.training_config)
    eng.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    eng.reset(seed=0)
    gs = eng.game_state
    pools = gs["deployment_pools"]
    return str(gs["deployment_mode_schedule_mode"]), {
        p: {(int(c), int(r)) for c, r in pools.get(p, pools.get(str(p)))} for p in (1, 2)
    }


def test_deployment_zones_are_identical_in_auto_and_active_mode():
    """Les zones ne dépendent PAS du mode de mise en place — et ne contiennent aucun mur.

    VERROU DU DÉFAUT MESURÉ LE 2026-08-05. La soustraction des murs
    (``engine/game_state.py``) n'était faite que si un joueur déployait en `random`/`active`.
    Sans effet tant que les zones ne servaient qu'à la phase de déploiement ; mais depuis que le
    reset les publie hors phase (``game_state["deployment_pools"]``), deux lecteurs les consomment
    en mode `auto` : ``squad_grid_anchor``, dont l'ancre est le BARYCENTRE du pool, et la clause
    20.04 sur la zone adverse. Mesuré avant correctif : 0 mur en `active`, 149 et 151 en placement non-agent
    — la même unité sur le même plateau recevait un centrage de grille différent selon le tirage.

    Le test compare les DEUX modes plutôt que de compter les murs d'un seul : c'est l'identité
    qui est le contrat, le comptage n'en est qu'un symptôme.
    """
    eng = _load(bank_training_scenarios()[0])
    walls = {(int(c), int(r)) for c, r in eng.game_state["wall_hexes"]}
    assert walls, "scénario sans mur : ce test ne prouverait rien (vert vacant)"

    mode_active, pools_active = _pinned_mode_pools(eng, 1.0)
    mode_auto, pools_auto = _pinned_mode_pools(eng, 0.0)
    assert mode_active == "active" and mode_auto == "auto", (
        f"modes non imposés : actif={mode_active!r}, auto={mode_auto!r}"
    )

    for player in (1, 2):
        assert pools_auto[player], f"joueur {player} : zone vide en mode auto"
        assert pools_auto[player] == pools_active[player], (
            f"joueur {player} : la zone de déploiement dépend du mode de mise en place "
            f"({len(pools_auto[player])} hexes en auto contre "
            f"{len(pools_active[player])} en active) — même plateau, même scénario"
        )
        intruders = pools_auto[player] & walls
        assert not intruders, (
            f"joueur {player} : {len(intruders)} hexes de MUR dans la zone de déploiement — "
            "un mur n'est une case de déploiement légale dans aucun mode"
        )
