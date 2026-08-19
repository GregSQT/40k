"""Dette fermée : `get_fighting_models` n'est plus enveloppé d'un `except Exception` dans l'obs.

**Ce qui était écrit** (`engine/observation_builder.py`, introduit le 2026-05-27 par `fb7e83b6`,
dès la 1re version du bloc figurines — aucun commit ne l'a jamais justifié) :

    try:
        fighting_set = set(get_fighting_models(game_state, active_squad_id))
    except Exception:
        fighting_set = set()

Un `except Exception` nu traduisait TOUTE erreur — cache corrompu, escouade absente, config de
métrique invalide — en « aucune figurine de cette escouade ne peut combattre ». Ce n'est pas une
dégradation gracieuse : c'est un ÉTAT DE JEU INVENTÉ, servi à l'agent sans aucune trace.
`n_fight_eligible` tombait à 0 et les bits `fight_eligible` de chaque figurine avec lui, donc
l'agent apprenait à ne pas frapper là où le moteur, lui, aurait résolu des attaques.

**Ce qui a été vérifié avant de le supprimer.** Toutes les levées atteignables depuis
`get_fighting_models` sur ce chemin viennent de `require_key(game_state, "models_cache")`,
`require_key(game_state, "squad_models")`, `get_engagement_zone`, `_synth_model_entry` et de la
primitive EZ (`unit_entries_within_engagement_zone`). Or `build_squad_observation` appelle
CHACUNE d'elles SANS garde, sur les MÊMES données, avant et après ce site. Le `try/except` ne
protégeait donc aucun cas que l'observation ne rencontrait pas déjà : il ne pouvait que masquer
une donnée corrompue une fois qu'elle était là. Aucune condition NOMMÉE et légitime n'existe à
rattraper — le try/except est supprimé, pas rétréci.

Les deux verrous ci-dessous sont complémentaires : le premier prouve que le chemin ne lève pas en
conditions réelles (donc que la suppression ne casse rien), le second prouve que si jamais il
levait, l'erreur REMONTE au lieu d'être maquillée en zéro.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon1.json"
)


def _load(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    eng.reset(seed=seed)
    return eng


def _is_on_battlefield(gs, squad_id: str) -> bool:
    """La garde du site d'observation (§0.40 point 5), énoncée UNE fois pour les deux tests.

    `observation_builder` n'appelle `get_fighting_models` que sur une escouade posée. Une escouade
    hors table est à la sentinelle (-1,-1) et la primitive d'engagement REFUSE de la mesurer — un
    garde-fou voulu. Les deux tests doivent donc se placer du MÊME côté de cette garde : le premier
    pour ne pas exercer un chemin que la production ne prend pas, le second pour que le site soit
    réellement atteint.
    """
    from engine.game_utils import get_unit_by_id

    unit = get_unit_by_id(gs, str(squad_id))
    return unit is not None and unit["deployed_on_turn"] is not None


def _a_squad_on_the_battlefield(gs) -> str:
    """Une escouade que le site d'observation traite VRAIMENT, pas la première venue.

    `next(iter(units_cache))` ne convient pas : au tour 1 la première clé est l'escouade en
    réserves (mesuré sur `scenario_training_armageddon`, seed 0 — 1 hors table sur 10, et c'est
    elle). Le site serait court-circuité par sa garde, `get_fighting_models` ne serait jamais
    appelé, et la contre-épreuve ne prouverait rien.
    """
    sid = next((str(s) for s in gs["units_cache"] if _is_on_battlefield(gs, str(s))), None)
    if sid is None:
        raise AssertionError(
            "aucune escouade sur le champ de bataille : le site d'observation serait court-circuité "
            "et la contre-épreuve ne mesurerait rien"
        )
    return sid


def _play_out_of_deployment(eng, limit: int = 400) -> int:
    """Joue la 1re action légale tant que la phase est `deployment`. Rend le nb de steps.

    LÈVE si la phase ne se termine pas. Le prédécesseur (`_play_until`, jusqu'au 2026-08-06)
    demandait de traverser `{"deployment", "command", "move"}` et se contentait de `break` quand il
    n'y arrivait pas. Or `deployment` n'apparaît JAMAIS dans ce scénario (unités pré-placées,
    mesuré) : la condition n'était donc jamais satisfaite et l'helper jouait l'ÉPISODE ENTIER —
    119 steps, ~36 s — avant de rendre la main sur épuisement des actions légales. Un repli
    silencieux qui coûtait le prix d'une partie complète pour une précondition déjà vraie au step 0.
    """
    import numpy as np

    steps = 0
    while steps < limit and str(eng.game_state.get("phase")) == "deployment":
        mask = eng.get_action_mask()
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            raise AssertionError(f"plus aucune action légale en phase deployment après {steps} steps")
        eng.step(int(legal[0]))
        steps += 1
    phase = str(eng.game_state.get("phase"))
    if phase == "deployment":
        raise AssertionError(f"toujours en phase deployment après {steps} steps (limite {limit})")
    return steps


def test_get_fighting_models_does_not_raise_on_the_observation_path():
    """Sur une partie réelle, l'appel du site d'observation ne lève JAMAIS.

    C'est la preuve demandée par la suppression : l'appel est rejoué, à chaque step et pour
    CHAQUE escouade vivante, sur le `game_state` exact que l'observation consomme. Si une seule
    condition légitime de levée existait sur ce chemin, elle sortirait ici.
    """
    import numpy as np

    from engine.phase_handlers.shared_utils import get_fighting_models

    eng = _load()
    gs = eng.game_state
    calls = 0
    skipped_off_table = 0
    steps = 0
    # 220 est un garde-fou, pas la durée visée : l'épisode s'épuise de lui-même en 119 steps
    # (mesuré). Ne PAS raccourcir cette borne pour gagner du temps — la charge n'est atteinte
    # qu'au step 46 et la phase de fight au step 59, alors que le seuil `calls >= 400` ci-dessous
    # tombe dès le step 42. Tronquer sur le seuil retirerait au test la phase de combat, c'est-à-dire
    # son sujet même. Le coût (~36 s) est celui d'une vraie partie, pas d'un gaspillage.
    while steps < 220:
        for sid in list(gs["units_cache"].keys()):
            # LE CHEMIN D'OBSERVATION, PAS UN SURENSEMBLE : on se place du même côté que la garde
            # de production (cf. `_is_on_battlefield`). Ce test appelait sans le filtre : il
            # exerçait un chemin que la production ne prend pas, et restait vert seulement tant
            # qu'aucune unité n'était hors table hors déploiement. Une unité en réserves 20.01
            # l'est tout l'épisode.
            if not _is_on_battlefield(gs, str(sid)):
                skipped_off_table += 1
                continue
            # Aucun `pytest.raises` : c'est l'ABSENCE de levée qui est affirmée. Une exception
            # ici fait échouer le test avec sa propre trace, ce qui est exactement le signal
            # voulu — on saurait quelle précondition manque.
            get_fighting_models(gs, str(sid))
            calls += 1
        mask = eng.get_action_mask()
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            break
        eng.step(int(legal[0]))
        steps += 1

    assert calls >= 400, f"trop peu d'appels exercés ({calls}) pour conclure"
    # VERT VACANT : si le filtre ne sautait jamais rien, ce test ne dirait rien du cas hors
    # table. Le scénario d'entraînement tire des rosters à réserves ET traverse une phase de
    # déploiement : les deux produisent des escouades hors table.
    assert skipped_off_table > 0, (
        "aucune escouade hors table rencontrée : le filtre du chemin d'observation n'est pas "
        "exercé, ce test ne prouve rien sur ce cas"
    )


def test_a_failure_of_get_fighting_models_now_propagates(monkeypatch):
    """Contre-épreuve : une levée doit REMONTER, plus être traduite en « personne ne combat ».

    C'est le verrou de la dette elle-même. Avec l'`except Exception`, ce test passait sans rien
    lever et l'observation rendait `n_fight_eligible = 0` — un état de jeu faux, indiscernable
    d'un état légitime. La panne doit être bruyante.
    """
    from engine import observation_builder

    eng = _load()
    gs = eng.game_state
    # Pendant le déploiement l'escouade active n'est pas sur le champ de bataille (§0.40 point 5)
    # et le site est court-circuité par sa garde : on sort d'abord de la phase. Sur ce scénario
    # elle n'est jamais active (unités pré-placées), donc zéro step joué — mais la garde reste,
    # elle protège des scénarios à déploiement actif.
    _play_out_of_deployment(eng)
    assert str(gs.get("phase")) != "deployment", "le test doit sortir du déploiement"

    # L'escouade DOIT être posée, sinon le site n'est pas atteint et `pytest.raises` échouerait
    # pour une raison qui n'a rien à voir avec la dette mesurée ici.
    sid = _a_squad_on_the_battlefield(gs)

    def _boom(_game_state, _squad_id):
        raise RuntimeError("cache de figurines corrompu")

    monkeypatch.setattr(observation_builder, "get_fighting_models", _boom)

    with pytest.raises(RuntimeError, match="cache de figurines corrompu"):
        eng.obs_builder.build_squad_observation(gs, sid)
