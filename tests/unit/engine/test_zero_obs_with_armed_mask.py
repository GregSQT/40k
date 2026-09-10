"""L'observation ne peut pas etre NULLE quand le masque, lui, ouvre une action.

CE QUI A ETE MANQUE. `_build_observation_and_mask` avance la phase quand l'etat d'entree n'ouvre
rien (pool vide ET masque vide), puis RECONSTRUIT le couple masque/pool. Le test qui suivait cette
reconstruction ne regardait que le POOL : `if not eligible_units: return _zero_obs()`. Or une
cascade d'`advance_phase` peut ouvrir une phase de commandement qui arme un point d'arret
EXCLUSIF — la designation d'Oath : le masque n'ouvre que les `OATH_SLOT_i` et le pool reste vide
par construction. L'agent recevait alors un tenseur entierement nul tout en devant designer une
cible : le defaut §0.40 point 1 (« decrire A, jouer pour B »), en pire, puisqu'il ne decrivait
rien du tout.

Les deux branches qui suivent ce retour existent precisement pour ce cas (`armed_decision`, puis
le repli `_first_squad_on_board`), et leur commentaire nomme la designation d'Oath comme leur
utilisatrice — elles etaient hors d'atteinte par ce chemin.

CE QUE CE FICHIER VERROUILLE : masque arme + pool vide apres la transition -> l'observation
DECRIT une escouade ; et l'observation nulle reste la reponse quand plus rien n'est sur la table,
seul etat ou elle est correcte.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np

from engine.macro_intents import OATH_SLOT_BASE
from engine.w40k_core import W40KEngine
from tests.unit.engine.test_terminal_info_all_paths import _make_engine


def _empty_mask(engine: W40KEngine) -> np.ndarray:
    mask, _eligible = engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)
    return np.zeros(len(mask), dtype=bool)


def _armed_mask(engine: W40KEngine) -> np.ndarray:
    """Masque qui n'ouvre QU'UN slot d'Oath — la forme exacte du point d'arret exclusif."""
    mask = _empty_mask(engine)
    mask[OATH_SLOT_BASE] = True
    return mask


class _MaskScript:
    """Rend une suite de couples (masque, pool) preparee, dans l'ordre des appels."""

    def __init__(self, couples: List[Tuple[np.ndarray, list]]) -> None:
        self._couples = couples
        self.calls = 0

    def __call__(self, game_state):
        idx = min(self.calls, len(self._couples) - 1)
        self.calls += 1
        return self._couples[idx]


def _observe_after_transition(
    engine: W40KEngine, mask_after: np.ndarray
) -> Tuple[Any, _MaskScript]:
    """Construit l'observation depuis un etat d'entree MUET, la transition rendant `mask_after`.

    L'entree (pool vide, masque vide) est ce qui declenche l'`advance_phase` interne ; le couple
    suivant decrit l'etat d'arrivee. `_advance_phase_and_drain` est neutralise : ce test porte sur
    la LECTURE de l'etat d'arrivee, pas sur la transition elle-meme.
    """
    script = _MaskScript([(_empty_mask(engine), []), (mask_after, [])])
    with patch.object(
        engine.action_decoder, "get_squad_action_mask_and_eligible_units", script
    ), patch.object(engine, "_advance_phase_and_drain", lambda action: (True, {})):
        observation, _pair = engine._build_observation_and_mask()
    assert script.calls >= 2, (
        "la transition interne n'a pas ete declenchee : le test ne verifie pas le bon chemin"
    )
    return observation, script


def _is_all_zero(observation: Any) -> bool:
    if isinstance(observation, dict):
        return all(np.all(np.asarray(v) == 0) for v in observation.values())
    return bool(np.all(np.asarray(observation) == 0))


def test_armed_mask_after_transition_gets_a_real_observation():
    engine = _make_engine()

    observation, _script = _observe_after_transition(engine, _armed_mask(engine))

    assert observation is not None
    assert not _is_all_zero(observation), (
        "observation NULLE rendue alors que le masque ouvre un slot d'Oath : l'agent doit "
        "designer une cible sans rien voir de l'etat (defaut §0.40 point 1)"
    )


def test_armed_mask_observation_describes_a_squad_on_board():
    """VERT NON VACANT : l'observation n'est pas seulement « non nulle », elle DECRIT une escouade.

    Sans cette assertion, un tenseur rempli de bruit passerait le test precedent.
    """
    engine = _make_engine()

    observation, _script = _observe_after_transition(engine, _armed_mask(engine))
    reference = engine._build_observation_and_mask()[0]

    assert isinstance(observation, dict) and isinstance(reference, dict)
    assert set(observation.keys()) == set(reference.keys())
    # L'escouade decrite est celle du repli documente (`_first_squad_on_board`), donc la meme que
    # celle d'une construction ordinaire sur ce meme etat.
    assert np.array_equal(
        np.asarray(observation["global_cont"]), np.asarray(reference["global_cont"])
    ), "l'observation rendue ne decrit pas l'escouade attendue"


def test_empty_mask_after_transition_still_returns_zero_observation():
    """NON-REGRESSION : masque VIDE apres la transition -> l'observation nulle reste correcte.

    C'est la moitie du test qu'il fallait garder : sans elle, elargir la condition aurait pu
    faire tomber un etat reellement muet dans les replis du dessous.
    """
    engine = _make_engine()

    observation, _script = _observe_after_transition(engine, _empty_mask(engine))

    assert _is_all_zero(observation), (
        "un etat sans aucune action ouverte doit rendre l'observation nulle"
    )
