"""Verrou : mémoïsation des sous-tenseurs d'armes de l'observation squad.

Le bloc « profils d'armes » est émis pour les 16 entités à CHAQUE step alors que son contenu
vient des datasheets : seul le nombre de porteurs vivants bouge. Il est donc mémoïsé par
(escouade, figurines vivantes).

Ce que ces tests verrouillent — les trois façons dont un cache peut mentir :
  - il rend EXACTEMENT ce que rendrait le calcul (identité bit à bit, cache chaud vs froid) ;
  - il tombe quand une figurine MEURT (le compteur de porteurs doit décroître) ;
  - il tombe au RESET, sans quoi la rotation de rosters (SM ↔ Orks, même ids d'unités,
    armes différentes) ferait observer les armes de l'épisode précédent.

Le dernier point est le piège réel de ce chantier : `game_state` est muté d'un épisode à
l'autre et jamais recréé (w40k_core.py, affectation unique à l'init).
"""

from __future__ import annotations

import os

import numpy as np

from ai.unit_registry import UnitRegistry
from engine.observation_entities import WEAPON_PROFILE_CACHE_KEY
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon1.json",
)


def _make_env() -> W40KEngine:
    return W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x5_new",
        controlled_agent="ArmageddonAgent",
        scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )


def _any_squad(gs) -> str:
    return next(iter(gs["units_cache"].keys()))


def test_cache_hit_is_identical_to_cold_compute():
    """Cache chaud == calcul froid, bit à bit, sur toutes les escouades en jeu."""
    env = _make_env()
    env.reset()
    gs = env.game_state
    builder = env.obs_builder

    cold = {}
    for sid in list(gs["units_cache"].keys()):
        alive = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
        models = [gs["models_cache"][m] for m in alive]
        gs.pop(WEAPON_PROFILE_CACHE_KEY, None)  # force le calcul froid
        cold[sid] = builder._encode_entity_weapons(gs, sid, models, alive)

    # Cache chaud : une seule passe le remplit, la suivante doit rendre l'identique.
    gs.pop(WEAPON_PROFILE_CACHE_KEY, None)
    for sid in list(gs["units_cache"].keys()):
        alive = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
        models = [gs["models_cache"][m] for m in alive]
        builder._encode_entity_weapons(gs, sid, models, alive)  # remplit
        hot = builder._encode_entity_weapons(gs, sid, models, alive)  # relit
        assert np.array_equal(hot[0], cold[sid][0]), f"{sid}: cont diverge"
        assert np.array_equal(hot[1], cold[sid][1]), f"{sid}: bin diverge"

    assert gs[WEAPON_PROFILE_CACHE_KEY], "le cache doit etre peuple"


def test_cache_falls_when_a_model_dies():
    """Une perte change le nombre de porteurs : le cache DOIT etre invalide par la cle."""
    env = _make_env()
    env.reset()
    gs = env.game_state
    builder = env.obs_builder

    # Une escouade d'au moins 2 figurines vivantes.
    sid = next(
        s for s in gs["units_cache"]
        if len([m for m in gs["squad_models"][s] if m in gs["models_cache"]]) >= 2
    )
    alive = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
    models = [gs["models_cache"][m] for m in alive]
    before = builder._encode_entity_weapons(gs, sid, models, alive)
    carriers_before = float(before[0].sum())

    # Perte simulee au niveau des caches (le point que la cle doit observer).
    dead = alive[-1]
    del gs["models_cache"][dead]
    alive_after = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
    models_after = [gs["models_cache"][m] for m in alive_after]
    after = builder._encode_entity_weapons(gs, sid, models_after, alive_after)

    assert len(alive_after) == len(alive) - 1
    assert float(after[0].sum()) != carriers_before, (
        "le total des porteurs doit changer apres une perte — cache non invalide"
    )


def test_cache_is_dropped_when_caches_are_rebuilt():
    """`build_units_cache` est le point d'invalidation : il vide le cache d'armes."""
    from engine.phase_handlers.shared_utils import build_units_cache

    env = _make_env()
    env.reset()
    gs = env.game_state
    sid = _any_squad(gs)
    alive = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
    models = [gs["models_cache"][m] for m in alive]
    env.obs_builder._encode_entity_weapons(gs, sid, models, alive)
    assert gs[WEAPON_PROFILE_CACHE_KEY]

    build_units_cache(gs)
    assert not gs.get(WEAPON_PROFILE_CACHE_KEY), "cache survivant a la reconstruction des caches"


def test_poisoned_entry_does_not_survive_a_reset():
    """Aucune entree de l'episode precedent n'est servie apres un reset.

    `game_state` est MUTE d'un episode a l'autre et jamais recree : une entree indexee par des
    ids qui se repetent (memes unites, roster different apres rotation SM/Orks) serait servie
    telle quelle. On empoisonne donc une entree avec une valeur reconnaissable et on verifie
    qu'elle a disparu — c'est la contre-epreuve directe de l'invalidation.
    """
    env = _make_env()
    env.reset()
    gs = env.game_state
    sid = _any_squad(gs)
    alive = tuple(m for m in gs["squad_models"][sid] if m in gs["models_cache"])
    poison_cont = np.full(
        env.obs_builder._encode_entity_weapons(
            gs, sid, [gs["models_cache"][m] for m in alive], list(alive)
        )[0].shape,
        42.0,
        dtype=np.float32,
    )
    poison_bin = np.zeros_like(
        env.obs_builder._encode_entity_weapons(
            gs, sid, [gs["models_cache"][m] for m in alive], list(alive)
        )[1]
    )
    poison_rule_ids = np.zeros_like(
        env.obs_builder._encode_entity_weapons(
            gs, sid, [gs["models_cache"][m] for m in alive], list(alive)
        )[2]
    )
    # Meme ARITE que les entrees reelles : (cont, bin, ids de regles, troncatures rejouees).
    # Un n-uplet plus court ferait echouer le depaquetage de `_encode_entity_weapons` AVANT
    # l'assertion — le test planterait au lieu de constater la regression qu'il verrouille.
    gs[WEAPON_PROFILE_CACHE_KEY][(sid, alive)] = (poison_cont, poison_bin, poison_rule_ids, ())

    env.reset()
    served = gs.get(WEAPON_PROFILE_CACHE_KEY, {}).get((sid, alive))
    assert served is None or not np.array_equal(served[0], poison_cont), (
        "une entree de l'episode precedent est encore servie"
    )


def test_truncation_log_is_replayed_on_every_cache_hit():
    """La troncature est REJOUEE cache chaud : un garde-fou qui se tait n'en est plus un.

    Piege rencontre en ecrivant ce cache : memoiser les tenseurs sans memoiser le log rendait
    `test_profile_truncation_is_logged_never_silent` (et son jumeau ennemi) muets des le second
    step d'une composition — le test restait VERT en n'observant plus rien.
    """
    from unittest.mock import patch

    env = _make_env()
    env.reset()
    gs = env.game_state
    builder = env.obs_builder
    sid = _any_squad(gs)
    alive = [m for m in gs["squad_models"][sid] if m in gs["models_cache"]]
    models = [gs["models_cache"][m] for m in alive]

    # Troncature forcee : 0 slot d'armes rend tout profil excedentaire.
    with patch.object(type(builder), "K_WEAPONS_RANGED", 0), \
         patch.object(type(builder), "K_WEAPONS_MELEE", 0), \
         patch.object(type(builder), "K_WEAPONS", 0):
        gs.pop(WEAPON_PROFILE_CACHE_KEY, None)
        captured = []
        with patch("engine.game_utils.add_debug_file_log",
                   side_effect=lambda g, msg: captured.append(msg)):
            builder._encode_entity_weapons(gs, sid, models, alive)   # froid
            n_cold = len(captured)
            builder._encode_entity_weapons(gs, sid, models, alive)   # chaud
            n_hot = len(captured) - n_cold

    assert n_cold > 0, "aucune troncature loguee au calcul froid"
    assert n_hot == n_cold, (
        f"cache chaud : {n_hot} logs au lieu de {n_cold} — la troncature n'est plus tracee"
    )


def test_observation_is_unchanged_by_the_cache():
    """L'observation complete est identique avec et sans cache (aucun effet de bord)."""
    env = _make_env()
    obs_a, _ = env.reset()
    gs = env.game_state
    sid = _any_squad(gs)

    with_cache = env.obs_builder.build_squad_observation(gs, sid)
    gs.pop(WEAPON_PROFILE_CACHE_KEY, None)
    without_cache = env.obs_builder.build_squad_observation(gs, sid)

    for key in with_cache:
        assert np.array_equal(with_cache[key], without_cache[key]), f"cle {key} diverge"
