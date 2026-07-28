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
    return eng


def _play_until(eng, phases: set[str], limit: int = 400) -> int:
    """Joue la 1re action légale jusqu'à avoir traversé toutes les `phases`. Rend le nb de steps."""
    import numpy as np

    seen = set()
    steps = 0
    while steps < limit and not phases.issubset(seen):
        seen.add(str(eng.game_state.get("phase")))
        mask = eng.get_action_mask()
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            break
        eng.step(int(legal[0]))
        steps += 1
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
    steps = 0
    while steps < 220:
        for sid in list(gs["units_cache"].keys()):
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


def test_a_failure_of_get_fighting_models_now_propagates(monkeypatch):
    """Contre-épreuve : une levée doit REMONTER, plus être traduite en « personne ne combat ».

    C'est le verrou de la dette elle-même. Avec l'`except Exception`, ce test passait sans rien
    lever et l'observation rendait `n_fight_eligible = 0` — un état de jeu faux, indiscernable
    d'un état légitime. La panne doit être bruyante.
    """
    from engine import observation_builder

    eng = _load()
    gs = eng.game_state
    _, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    # Pendant le déploiement l'escouade active n'est pas sur le champ de bataille (§0.40 point 5)
    # et le site est court-circuité par sa garde : on sort d'abord de la phase.
    _play_until(eng, {"deployment", "command", "move"})
    assert str(gs.get("phase")) != "deployment", "le test doit sortir du déploiement"

    sid = str(next(iter(gs["units_cache"].keys())))

    def _boom(_game_state, _squad_id):
        raise RuntimeError("cache de figurines corrompu")

    monkeypatch.setattr(observation_builder, "get_fighting_models", _boom)

    with pytest.raises(RuntimeError, match="cache de figurines corrompu"):
        eng.obs_builder.build_squad_observation(gs, sid)
