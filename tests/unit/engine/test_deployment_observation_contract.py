"""V11 §0.40 point 1 — l'observation de la phase de déploiement décrit l'unité du masque.

**Point 1 — l'obs décrivait une AUTRE unité que celle sur laquelle le masque agit.**
`_build_observation` prenait `next(iter(units_cache.keys()))` : la 1re clé du cache d'unités,
tous joueurs confondus et unités déjà posées comprises. Le masque, lui, ouvre les slots 4-8 pour
`deployment_state["deployable_units"][current_deployer][0]`. Rien ne garantissait que les deux
désignent la même unité — l'agent décrivait A et posait B (même motif que le désalignement
obs ↔ action des slots ennemis, D1).

"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon.json"
)


def _load(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    assert eng.game_state.get("phase") == "deployment", (
        "le scénario doit démarrer en déploiement actif — sinon ce fichier ne teste rien"
    )
    return eng


def _first_deploy_action(mask) -> int:
    actions = [a for a in range(4, 9) if mask[a]]
    assert actions, "aucune action de déploiement dans le masque"
    return actions[0]


# ============================================================================
# POINT 1 — contrat obs ↔ masque
# ============================================================================


def test_deployment_observation_describes_the_unit_the_mask_acts_on():
    """À CHAQUE état de déploiement, l'unité décrite par l'obs == celle du masque.

    Le contrat est vérifié en espionnant l'argument `squad_id` que `_build_observation` passe au
    constructeur d'observation : c'est littéralement l'unité décrite, pas une reconstruction.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    described: list[str] = []
    original = eng.obs_builder.build_squad_observation

    def _spy(game_state, squad_id):
        described.append(str(squad_id))
        return original(game_state, squad_id)

    eng.obs_builder.build_squad_observation = _spy

    checked = 0
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        assert eligible, "pool de déploiement vide alors que la phase est 'deployment'"
        masked_unit_id = str(eligible[0]["id"])

        described.clear()
        eng._build_observation()
        assert described == [masked_unit_id], (
            f"step {steps} : l'observation décrit {described} alors que le masque agit sur "
            f"{masked_unit_id} — désalignement obs ↔ action (§0.40 point 1)"
        )

        # L'unité décrite doit appartenir au joueur qui déploie ET ne pas être déjà posée.
        entry = gs["units_cache"][masked_unit_id]
        assert int(entry["player"]) == dec._get_current_deployer(gs), (
            f"step {steps} : l'obs décrit une unité du joueur {entry['player']} alors que "
            f"{dec._get_current_deployer(gs)} déploie"
        )
        unit = next(u for u in gs["units"] if str(u["id"]) == masked_unit_id)
        assert unit["deployed_on_turn"] is None, (
            f"step {steps} : l'obs décrit une unité DÉJÀ posée pendant le déploiement"
        )
        checked += 1

        eng.step(_first_deploy_action(mask))
        steps += 1

    assert gs.get("phase") != "deployment", "déploiement non terminé (deadlock)"
    # Les deux joueurs doivent avoir déployé : c'est le passage au joueur 2 qui distingue la
    # source du masque de la 1re clé de `units_cache` (qui reste une unité du joueur 1).
    assert checked >= 4, f"trop peu d'états de déploiement observés ({checked})"


def test_deployment_active_unit_raises_on_empty_pool():
    """Pool vide en phase de déploiement = état incohérent → erreur explicite, pas d'obs nulle.

    Une obs de zéros décrirait un plateau vide à un agent à qui l'on demande quand même d'agir,
    et le masque correspondant serait tout-faux (injouable). L'erreur est le seul signal correct.
    """
    eng = _load()
    gs = eng.game_state
    deployer = eng.action_decoder._get_current_deployer(gs)
    gs["deployment_state"]["deployable_units"][deployer] = []

    with pytest.raises(ValueError, match="aucune unité déployable"):
        eng.action_decoder.get_deployment_active_unit(gs)
