"""Une zone déjà servie par les alliés repousse l'escouade suivante.

LE défaut que ce fichier verrouille, mesuré le 2026-08-12 sur 600 parties du panel refondu :
les bots empilent **2,6 à 3,0 escouades par zone** et n'en couvrent que 1,7 sur 5, quand l'agent
étale les siennes sur 2,9. Ils ne sont ni lents (92 % de l'armée est dans une zone dès le tour 3)
ni battus au décompte (ils contrôlent 1,66 des 1,92 zones où ils sont présents) : ils vont tous
au même endroit, parce que chaque escouade décide seule et calcule la même réponse.

C'est aussi ce qui rendait `w_contest` INERTE (aucun effet mesurable sur six win-rates) : rendre
une zone plus attirante quand personne ne se coordonne ne fait que déplacer le tas.

La pénalité porte sur le **surplus d'OC**, pas sur l'occupation : une zone disputée n'est pas
pénalisée — les renforts doivent y aller — mais une zone déjà gagnée large repousse la suivante.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

import ai.bot_doctrines as doc

#: Deux objectifs de même distance : seul l'encombrement peut les départager.
EGALE = np.full((3, 3), 5, dtype=np.int16)
ZONE_A = {(1, 1)}
ZONE_B = {(2, 2)}


@pytest.fixture(autouse=True)
def _deux_zones_equidistantes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: [EGALE.copy(), EGALE.copy()])
    monkeypatch.setattr(doc, "objective_hex_sets", lambda gs: [ZONE_A, ZONE_B])


def _state(figurines: List[Tuple[str, int, Tuple[int, int], int]]) -> Dict[str, Any]:
    """`figurines` = [(id_escouade, joueur, position, OC), …] — une figurine par escouade suffit."""
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, Any] = {}
    for squad_id, player, (col, row), oc in figurines:
        units_cache[squad_id] = {"player": player}
        model_id = f"{squad_id}#0"
        models_cache[model_id] = {"col": col, "row": row, "OC": oc}
        squad_models[squad_id] = [model_id]
    return {
        "objectives": [{"id": "A"}, {"id": "B"}],
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
    }


def _surplus(state: Dict[str, Any], me: int, sauf: str) -> List[float]:
    return doc._surplus_oc_by_zone(state, [ZONE_A, ZONE_B], me, sauf)


def test_an_uncontested_ally_creates_a_surplus() -> None:
    """Un allié seul sur la zone A : surplus de son OC, rien sur B."""
    state = _state([("1", 1, (1, 1), 4), ("2", 1, (9, 9), 4)])

    assert _surplus(state, me=1, sauf="2") == [4.0, 0.0]


def test_my_own_squad_never_counts_against_itself() -> None:
    """Verrou du piège inverse : sans l'exclusion, une escouade seule sur sa zone la fuirait.

    C'est le mode d'échec le plus coûteux de cette pénalité : le bot lâcherait les zones qu'il
    tient, ce qui est exactement ce qu'on cherche à empêcher.
    """
    state = _state([("1", 1, (1, 1), 4)])

    assert _surplus(state, me=1, sauf="1") == [0.0, 0.0]


def test_a_contested_zone_is_not_a_surplus() -> None:
    """OC allié 4 contre OC ennemi 4 : la zone n'est PAS servie, elle doit rester attirante."""
    state = _state([("1", 1, (1, 1), 4), ("101", 2, (1, 1), 4), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [0.0, 0.0]


def test_only_the_excess_over_the_enemy_counts() -> None:
    """OC allié 10 contre 4 : seuls les 6 de trop sont du gaspillage."""
    state = _state([("1", 1, (1, 1), 10), ("101", 2, (1, 1), 4), ("2", 1, (9, 9), 1)])

    assert _surplus(state, me=1, sauf="2") == [6.0, 0.0]


def test_the_surplus_is_counted_in_oc_not_in_squads() -> None:
    """DEUX escouades à 1 d'OC pèsent moins qu'UNE à 9.

    Compter les escouades serait le même proxy que le `max(NB × DMG)` que ce chantier a retiré :
    deux Gretchin et un Carnifex ne pèsent pas pareil sur une zone.
    """
    deux_faibles = _state([("1", 1, (1, 1), 1), ("2", 1, (1, 1), 1), ("3", 1, (9, 9), 1)])
    un_lourd = _state([("1", 1, (1, 1), 9), ("3", 1, (9, 9), 1)])

    assert _surplus(deux_faibles, me=1, sauf="3")[0] == 2.0
    assert _surplus(un_lourd, me=1, sauf="3")[0] == 9.0


def test_a_served_zone_moves_away_by_the_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNE seule zone, déjà servie : sa distance perçue augmente de `w_crowd × surplus`.

    Une seule zone, exprès. Avec deux, la carte rendue est leur MINIMUM : la zone libre masquerait
    la pénalité de l'autre et le test passerait sans rien observer.
    """
    monkeypatch.setattr(doc, "objective_distance_maps", lambda gs: [EGALE.copy()])
    monkeypatch.setattr(doc, "objective_hex_sets", lambda gs: [ZONE_A])
    state = _state([("1", 1, (1, 1), 6), ("2", 1, (9, 9), 3)])
    state["objectives"] = [{"id": "A"}]

    nu, _z = doc._objective_terms(state, me=1, w_crowd=0.0, escouade="2")
    penalise, _z = doc._objective_terms(state, me=1, w_crowd=2.0, escouade="2")
    assert nu is not None and penalise is not None, "aucune carte rendue : le test ne regarde rien"

    assert int(nu[2, 2]) == 5, "sans pénalité, la carte est la distance nue"
    assert int(penalise[2, 2]) == 5 + 2 * 6, "servie : elle doit s'éloigner de w_crowd × surplus"


def test_the_next_squad_prefers_the_free_zone_at_equal_distance() -> None:
    """LE verrou d'ensemble : à distance ÉGALE, la zone libre l'emporte sur la zone servie.

    Sans la pénalité, les deux valent 5 et rien ne les départage — c'est exactement l'état
    d'avant, où les cinq escouades convergeaient sur la même.
    """
    state = _state([("1", 1, (1, 1), 6), ("2", 1, (9, 9), 3)])
    surplus = _surplus(state, me=1, sauf="2")

    assert surplus[0] > 0.0 and surplus[1] == 0.0, "la zone A doit être la seule servie"
    # La carte combinée retient le minimum : la libre reste à 5, la servie part à 17.
    penalise, _z = doc._objective_terms(state, me=1, w_crowd=2.0, escouade="2")
    assert penalise is not None, "aucune carte rendue : le test ne regarde rien"
    assert int(penalise[2, 2]) == 5, "la zone LIBRE garde son prix, c'est elle qui sera choisie"
