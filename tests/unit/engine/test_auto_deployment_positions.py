"""Verrou : le déploiement `auto` pose tout le monde, DANS SA ZONE, sur n'importe quel terrain.

Pilote le VRAI W40KEngine sur les deux variantes du template de training
(`scenario_training_armageddon1/2.json`, une par terrain — `agent_roster_ref=training_random`,
`opponent_roster_ref=[SM, Orks]`, siège aléatoire) et vérifie :
  - mode 'auto'   : toutes les unités non réservées sont posées, chaque figurine DANS la zone de
    déploiement de son joueur, escouades cohérentes (03.03) ;
  - mode 'active' : phase de déploiement, unités en sentinelle tant qu'elles ne sont pas posées.

CE QUE CE FICHIER VÉRIFIAIT AVANT, et pourquoi ça a changé (2026-08-08). Il s'appelait
`test_roster_fixed_positions.py` et verrouillait les positions `top`/`bottom` par figurine
écrites dans les rosters : mode 'fixed', aucune phase de déploiement, joueur 1 en bande HAUTE,
joueur 2 en bande BASSE. Ces positions étaient générées hors ligne par `gen_roster_positions.py`
contre UN terrain, et deux mesures les ont condamnées :

  - sur `terrain-mc2`, 3 à 10 figurines par bande et par roster tombaient sur un mur — le loader
    lève `ValueError ... on wall hex`, donc l'entraînement CRASHE dès que la rotation tire ce
    terrain en mode fixe (70 % des épisodes en début de run, `active_ratio_start` 0.3) ;
  - même sur le terrain d'origine, 12 à 17 figurines sur 23-37 se posaient HORS de la zone de
    déploiement de leur joueur. Légal (le loader ne confine à la zone que la voie legacy nommée,
    cf. `game_state._load_units`), mais l'agent démarrait depuis des positions qu'aucune partie
    réelle ne produit.

La bande top/bottom n'est donc plus le sujet, et ne pouvait pas le rester : les zones viennent
maintenant du terrain, et sur `terrain-mc1` elles sont TRIANGULAIRES, pas des bandes. Le critère
est l'appartenance à `deployment_pools[player]` — plus strict que l'ancien, et vrai sur toute
carte présente ou future.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from engine.phase_handlers.shared_utils import validate_squad_coherency
from shared.data_validation import require_key

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BANK = os.path.join(PROJECT_ROOT, "config/agents/ArmageddonAgent_x1/scenarios/training")
# Une variante par terrain : ce test est de ceux dont le résultat DÉPEND du terrain (zones,
# murs), il tourne donc sur les deux — c'est exactement le défaut que `mc2` a révélé.
TEMPLATES = ["scenario_training_armageddon1.json", "scenario_training_armageddon2.json"]


def _make_env(active_ratio: float, scenario: str):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    env = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=os.path.join(BANK, scenario),
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    # Chemin training : la config de phase est chargée à l'init (le moteur lève sinon).
    assert env.training_config is not None
    env.training_config = dict(env.training_config)
    env.training_config["deployment_mode_schedule"] = {
        "enabled": True,
        "training_only": False,
        "active_ratio_start": active_ratio,
        "active_ratio_end": active_ratio,
        "schedule": "linear",
        "freeze_after_progress": 1.0,
    }
    return env


def _play_out_of_deployment(env, limit: int = 400) -> int:
    """Joue la 1re action légale tant que la phase est `deployment`. Rend le nb de steps."""
    gs = env.game_state
    steps = 0
    while steps < limit and str(gs["phase"]) == "deployment":
        mask = env.get_action_mask()
        legal = np.flatnonzero(mask)
        assert legal.size > 0, f"plus aucune action légale en déploiement après {steps} steps"
        env.step(int(legal[0]))
        steps += 1
    assert str(gs["phase"]) != "deployment", f"toujours en déploiement après {steps} steps"
    return steps


def _pools(gs) -> dict:
    return {int(p): {(int(c), int(r)) for c, r in hexes}
            for p, hexes in require_key(gs, "deployment_pools").items()}


@pytest.mark.parametrize("scenario", TEMPLATES)
def test_auto_mode_places_every_model_inside_its_zone(scenario):
    """Mode 'auto', 4 épisodes : tout le monde posé, dans sa zone, escouades cohérentes."""
    env = _make_env(0.0, scenario)
    placed_total = 0
    for _ep in range(4):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "auto", "scheduler n'a pas produit 'auto' à ratio 0.0"
        _play_out_of_deployment(env)

        pools = _pools(gs)
        models_cache = require_key(gs, "models_cache")
        squad_models = require_key(gs, "squad_models")
        for u in gs["units"]:
            player = int(u["player"])
            model_ids = squad_models[str(u["id"])]
            if require_key(u, "in_strategic_reserves"):
                # 20.01 — une réserve démarre HORS TABLE, quel que soit le mode de déploiement.
                for mid in model_ids:
                    assert int(models_cache[mid]["col"]) < 0, (
                        f"unité {u['id']} en réserves mais posée (col={models_cache[mid]['col']}) "
                        "— une réserve n'est pas sur la table avant son ingress (20.04)"
                    )
                continue
            for mid in model_ids:
                m = models_cache[mid]
                assert int(m["col"]) >= 0, f"mode auto : figurine {mid} non placée (unité {u['id']})"
                placed_total += 1
                assert (int(m["col"]), int(m["row"])) in pools[player], (
                    f"figurine {mid} (unité {u['id']}, joueur {player}) posée en "
                    f"({m['col']},{m['row']}), HORS de sa zone de déploiement — c'est précisément "
                    "ce que les positions pré-calculées ne garantissaient pas"
                )
            # Cohérence d'escouade via la SOURCE DE VÉRITÉ moteur (03.03) — pas de
            # réimplémentation : validate_squad_coherency lit models_cache et applique game_rules
            # (voisins, bord-à-bord, étalement 9").
            if len(model_ids) >= 2:
                assert validate_squad_coherency(gs, str(u["id"])), (
                    f"unité {u['id']} ({u['unitType']}) démarre NON-COHÉRENTE "
                    "(validate_squad_coherency, règle moteur 03.03)"
                )

    assert placed_total > 0, "aucune figurine inspectée — test sans valeur"


@pytest.mark.parametrize("scenario", TEMPLATES)
def test_auto_mode_leaves_declared_reserves_off_the_table(scenario):
    """Mode 'auto' + roster à réserves 20.01 : le reset PASSE, et la réserve reste hors table.

    VERROU DU DÉFAUT MESURÉ LE 2026-08-05, conservé : les zones de déploiement ne vivaient que
    dans ``game_state["deployment_state"]``, écrit uniquement quand un joueur déploie. Une unité
    en réserves étant hors table dès le reset, ``squad_grid_anchor`` et
    ``_opponent_deployment_zone_cells`` (clause « pas dans la zone adverse avant le 3e round »,
    20.04) levaient « Required key 'deployment_state' », et le reset entier avec.

    Ce test CONSTRUIT le cas au lieu de l'espérer d'un tirage : il épingle la fixture à réserves
    déclarées des deux côtés. La fixture existe en deux variantes de terrain, comme le template.
    """
    fixture = scenario.replace("scenario_training_armageddon", "reserves_full_episode_fixture")
    env = _make_env(0.0, fixture)
    env.reset(seed=0)
    gs = env.game_state

    assert gs["deployment_mode_schedule_mode"] == "auto", "le mode 'auto' n'a pas été produit"
    # Les zones sont lisibles dès le reset — c'est la correction du 2026-08-05 elle-même.
    assert "deployment_pools" in gs, (
        "les zones de déploiement ne sont pas publiées : la clause 20.04 et l'ancre de grille "
        "d'une unité hors table redeviennent invérifiables"
    )

    reserves = [u for u in gs["units"] if require_key(u, "in_strategic_reserves")]
    assert reserves, (
        "la fixture ne met aucune unité en réserves : ce test ne prouverait rien (vert vacant)"
    )
    players = {int(u["player"]) for u in reserves}
    assert players == {1, 2}, f"réserves sur les seuls joueurs {sorted(players)} — un côté manque"

    _play_out_of_deployment(env)

    models_cache = require_key(gs, "models_cache")
    squad_models = require_key(gs, "squad_models")
    for u in reserves:
        for mid in squad_models[str(u["id"])]:
            assert int(models_cache[mid]["col"]) < 0, (
                f"unité {u['id']} en réserves mais posée par le déploiement auto "
                f"(col={models_cache[mid]['col']})"
            )


@pytest.mark.parametrize("scenario", TEMPLATES)
def test_active_mode_keeps_units_at_sentinel(scenario):
    """Mode 'active' : 3 épisodes, phase 'deployment', unités encore hors table au reset."""
    env = _make_env(1.0, scenario)
    for _ep in range(3):
        env.reset(seed=None)
        gs = env.game_state
        assert gs["deployment_mode_schedule_mode"] == "active", "scheduler n'a pas produit 'active' à ratio 1.0"
        assert gs["phase"] == "deployment", f"mode active : phase attendue 'deployment', obtenue {gs['phase']!r}"
        assert any(u["col"] < 0 for u in gs["units"]), "mode active : aucune unité en sentinelle"
