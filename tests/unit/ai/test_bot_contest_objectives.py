"""Un bot va DISPUTER les zones adverses, il ne se contente pas de la plus proche.

Trou n° 2 du §1 du chantier, resté ouvert par la refonte : `objective_controllers` n'était lu
**nulle part** dans `ai/bot_doctrines.py`, et `_objective_terms` réduisait les cartes de distance
par un `np.minimum.reduce` nu. Chaque escouade partait donc vers l'objectif le plus proche d'elle,
sans jamais savoir qu'une zone était tenue par l'adversaire — chaque camp s'asseyait sur son côté
de la table.

Mesuré le 2026-08-12 sur 600 parties : bot 27,2 VP de moyenne contre 53,8 à l'agent (≈ une zone
contre trois), **zéro victoire par élimination**, et 34,5 % des épisodes sans un seul mort.

La carte est désormais pondérée : un rabais en HEXES est retiré de la distance de chaque objectif,
double pour une zone adverse, simple pour une neutre, nul pour la sienne.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

import ai.bot_doctrines as doc

#: Deux objectifs : `obj1` est PROCHE (2 hexes partout), `obj2` est LOIN (6 hexes partout).
#: Des cartes constantes rendent le test lisible — seule compte la comparaison entre objectifs.
PROCHE = np.full((3, 3), 2, dtype=np.int16)
LOIN = np.full((3, 3), 6, dtype=np.int16)


@pytest.fixture(autouse=True)
def _carte_a_deux_objectifs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: [PROCHE, LOIN])
    monkeypatch.setattr(doc, "objective_hex_sets", lambda gs: [])


def _state(controllers: Dict[str, Any] | None) -> Dict[str, Any]:
    state: Dict[str, Any] = {"objectives": [{"id": "obj1"}, {"id": "obj2"}]}
    if controllers is not None:
        state["objective_controllers"] = controllers
    return state


def _pull(state: Dict[str, Any], me: int, w_contest: float) -> int:
    carte, _zones = doc._objective_terms(state, me=me, w_contest=w_contest)
    assert carte is not None, "aucune carte rendue : le test ne regarde rien"
    return int(carte[0, 0])


def test_without_the_weight_the_map_is_exactly_the_old_one() -> None:
    """`w_contest = 0` doit rendre la distance NUE — c'est ce qui rend le changement mesurable.

    Sans cette garantie, activer la pondération et régler les poids seraient le même geste, et
    aucune mesure ne pourrait attribuer un écart à l'un ou à l'autre.
    """
    assert _pull(_state({"obj1": 1, "obj2": 2}), me=1, w_contest=0.0) == 2


def test_an_enemy_held_objective_overtakes_the_nearest_one() -> None:
    """LE verrou. `obj2` est trois fois plus loin, mais l'adversaire le tient : il passe devant.

    Rabais double (2 × 3 = 6 hexes) sur une zone adverse : 6 − 6 = 0, contre 2 pour la mienne.
    Avec la réduction nue d'avant, la réponse était 2 et le bot n'allait jamais contester.
    """
    assert _pull(_state({"obj1": 1, "obj2": 2}), me=1, w_contest=3.0) == 0


def test_the_pull_is_symmetric_between_the_two_seats() -> None:
    """Vu du joueur 2, c'est `obj1` qui est adverse — et il est déjà le plus proche.

    Verrou de la comparaison de camp : `2` contre `"2"`, ou un `me` codé en dur, rendrait ce test
    identique au précédent. C'est le piège que ce dépôt a déjà payé dans l'énumération d'ennemis.
    """
    assert _pull(_state({"obj1": 1, "obj2": 2}), me=2, w_contest=3.0) == 2 - 6


def test_my_own_objective_earns_no_discount() -> None:
    """Une zone que je tiens déjà ne vaut pas un second déplacement : rabais nul.

    Les deux objectifs sont à moi, donc la carte doit valoir la distance nue malgré `w_contest`.
    """
    assert _pull(_state({"obj1": 1, "obj2": 1}), me=1, w_contest=3.0) == 2


def test_a_neutral_objective_earns_half_the_discount(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutre = rabais simple, adverse = double. Sinon les deux cas seraient confondus.

    ⚠️ `obj1` est mis HORS DE PORTÉE (20 hexes) exprès. La carte rendue est le MINIMUM sur les
    objectifs : avec un `obj1` à moi à 2 hexes, c'est lui qui gagnait dans les deux cas et le
    rabais d'`obj2` restait invisible — le test passait alors sans rien observer.
    """
    loin_a_moi = np.full((3, 3), 20, dtype=np.int16)
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: [loin_a_moi, LOIN])

    neutre = _pull(_state({"obj1": 1, "obj2": None}), me=1, w_contest=3.0)
    adverse = _pull(_state({"obj1": 1, "obj2": 2}), me=1, w_contest=3.0)

    assert neutre == 6 - 3, "une zone neutre doit recevoir un rabais SIMPLE"
    assert adverse == 6 - 6, "une zone adverse doit recevoir un rabais DOUBLE"
    assert adverse < neutre, "une zone adverse doit attirer davantage qu'une neutre"


def test_a_missing_controllers_dict_means_nobody_holds_anything() -> None:
    """Le dict est créé PARESSEUSEMENT par le moteur : absent = début de partie, pas une erreur.

    Les deux objectifs comptent alors comme neutres, donc le plus proche l'emporte : 2 − 3 = −1.
    """
    assert _pull(_state(None), me=1, w_contest=3.0) == 2 - 3


def test_the_weight_travels_with_the_others_so_a_mode_swap_carries_it() -> None:
    """`w_contest` est dans le MÊME tuple que les quatre autres poids.

    `EndgameBot` et `AttritionBot` échangent l'entrée de config entière selon leur mode : un poids
    chargé à part resterait sur la valeur du mode précédent. Le tuple les lie.
    """
    for key in ("racer", "endgame", "endgame_push", "attrition", "attrition_withdraw",
                "alpha", "decapitation", "scorer"):
        poids = doc.load_doctrine_weights(key)
        assert len(poids) == 5, f"{key} ne rend pas les CINQ poids : {poids}"
        assert all(isinstance(p, float) for p in poids)


def test_endgame_carries_a_stronger_pull_once_it_pushes() -> None:
    """Le mode `_push` d'`endgame` doit contester davantage — sinon le mode ne sert à rien."""
    _o, _e, _f, _r, attente = doc.load_doctrine_weights("endgame")
    _o, _e, _f, _r, poussee = doc.load_doctrine_weights("endgame_push")

    assert poussee > attente
