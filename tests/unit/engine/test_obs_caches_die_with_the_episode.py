"""Verrou : AUCUN cache d'observation ne survit a un rechargement de scenario.

`game_state` est le MEME objet d'un reset a l'autre (affectation unique a l'init de W40KEngine)
et `_reload_scenario` en remplace le contenu : terrain, murs, objectifs, unites. Tout ce que
l'observation memoise doit donc mourir dans le bloc de purges d'episode, sinon l'agent decrit
le terrain de l'episode PRECEDENT — corruption silencieuse, exactement le motif des regressions
V11 §0.18 et §0.26 (un cache clef sur un tampon qui coincide par hasard).

Ce test est un INVENTAIRE : il enumere les cles memoisees par le pipeline d'observation squad et
verifie qu'aucune ne traverse un reset. Ajouter un cache d'observation sans l'ajouter ici (et
donc sans le purger) fait rougir ce fichier.

Trouve en ecrivant ce verrou (2026-07-28) : `_obs_solid_terrain_areas` — les zones contenant un
mur dense (Solid 13.11), lues par le drapeau « gone to ground pret » — n'etait purgee NULLE
PART. Les tests d'observation la retiraient a la main dans leurs fixtures, ce qui montrait que
le besoin etait connu ; la purge manquait dans le moteur.
"""

from __future__ import annotations

import os

from ai.unit_registry import UnitRegistry
from engine.observation_builder import ObservationBuilder
from engine.action_decoder import DEPLOY_SLOT_CANDIDATES_CACHE_KEY, ActionDecoder
from engine.observation_entities import WEAPON_PROFILE_CACHE_KEY
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json",
)

#: Cles memoisees par le pipeline d'observation squad (obs vectorielle + grille), avec ce
#: qu'elles derivent. Toutes doivent tomber a chaque episode.
OBS_CACHE_KEYS = {
    WEAPON_PROFILE_CACHE_KEY: "profils d'armes par (escouade, figurines vivantes)",
    ObservationBuilder.OBJECTIVE_HEX_ARRAYS_KEY: "hexes de chaque objectif (distances/directions)",
    "_grid_static_hex_arrays": "murs / objectifs / couvert rasterises pour la grille",
    "_grid_deployment_zone_anchor": "ancre de grille des escouades pas encore posees (§0.40)",
    "_obs_solid_terrain_areas": "zones contenant un mur dense (Solid 13.11, gone to ground)",
    "_unit_los_pair_cache": "LoS et couvert par paire (tireur, cible)",
    ActionDecoder.DEPLOYMENT_SCORING_CACHE_KEY: (
        "scoring du deploiement (expositions LoS par hexe, allies par colonne) — LU par le bloc "
        "candidat de l'observation, donc sa peremption deviendrait une observation fausse"
    ),
    DEPLOY_SLOT_CANDIDATES_CACHE_KEY: (
        "hexe + plan que chaque slot 4-8 poserait (§0.40 point 3) — son tampon est l'etat des "
        "unites posees, qui recommence IDENTIQUE d'un episode a l'autre"
    ),
}


def _make_env() -> W40KEngine:
    return W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )


def test_no_observation_cache_survives_a_reset():
    """Chaque cache d'observation est EMPOISONNE puis doit avoir disparu apres le reset.

    L'empoisonnement est la seule preuve valable : verifier « le cache est vide apres reset »
    echouerait a tort, puisque le reset reconstruit legitimement une observation en fin de
    course et repeuple donc les caches avec les donnees du NOUVEL episode. Ce qui doit
    disparaitre, c'est l'entree de l'ANCIEN.
    """
    env = _make_env()
    env.reset()
    gs = env.game_state

    poison = {}
    for key in OBS_CACHE_KEYS:
        sentinel = {"__poison__": key} if key != "_grid_static_hex_arrays" else {"walls": "poison"}
        gs[key] = sentinel
        poison[key] = sentinel

    env.reset()

    assert env.game_state is gs, "game_state doit etre le MEME objet (sinon ce test ne prouve rien)"
    survivors = [
        f"{key} ({OBS_CACHE_KEYS[key]})"
        for key, sentinel in poison.items()
        if gs.get(key) is sentinel
    ]
    assert not survivors, "cache(s) d'observation survivant au reset : " + ", ".join(survivors)


def test_solid_terrain_areas_are_recomputed_for_the_new_terrain():
    """Le cas concret derriere la purge de `_obs_solid_terrain_areas`.

    Ce cache derive de `terrain_areas` ET `dense_wall_hexes`, tous deux remplaces par un
    rechargement de scenario. Servi tel quel, il ferait repondre le drapeau « gone to ground
    pret » (13.5) sur les zones Solid du terrain PRECEDENT.
    """
    env = _make_env()
    env.reset()
    gs = env.game_state

    # Force le calcul du cache par le vrai chemin (drapeaux terrain de l'unite active).
    sid = next(iter(gs["units_cache"].keys()))
    env.obs_builder.build_squad_observation(gs, sid)

    # Terrain incompatible avec le suivant : une zone unique, arbitraire.
    gs["_obs_solid_terrain_areas"] = [{"id": "zone-de-l-episode-precedent", "hexes": [[0, 0]]}]

    env.reset()
    after = gs.get("_obs_solid_terrain_areas")
    assert after is None or all(
        a.get("id") != "zone-de-l-episode-precedent" for a in after
    ), "les zones Solid de l'episode precedent sont encore servies"
