"""Le contrôle d'objectif se décompose PAR ESCOUADE, et l'empreinte mono-hexe court-circuite.

Deux changements du 2026-08-12, verrouillés ici.

1. `objective_control_contributions` est devenue la source unique du comptage (14.02) ;
   `sum_objective_control_oc_multi` n'en est plus que l'addition. Un appelant qui a besoin d'une
   variante — « qui tiendrait quoi sans telle escouade ? », question que se pose le surplus
   d'encombrement des bots — la compose par arithmétique au lieu de recompter une présence, et
   au lieu de faire porter l'hypothèse à la fonction qui énonce la règle.

2. `iter_living_model_footprints` rend directement l'ancre quand le socle tient dans une case.
   C'est TOUJOURS le cas sur le plateau d'entraînement (`_scale_socle` normalise en `round`/1), et
   ce générateur pesait 83 % du temps du décompte à ne calculer que ça.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple

import pytest

from engine.game_state import (
    fold_control_contributions,
    iter_living_model_footprints,
    objective_control_contributions,
    objective_hex_sets,
    objective_hexes_union,
    sum_objective_control_oc_multi,
)
from engine.hex_utils import compute_occupied_hexes

Hexes = Set[Tuple[int, int]]

ZONE: Hexes = {(1, 1)}
LOIN: Hexes = {(20, 20)}


def _state(
    figurines: Sequence[Tuple[str, int, Tuple[int, int], int]],
    *,
    shocked: Sequence[str] = (),
    socle: Tuple[str, Any] = ("round", 1),
) -> Dict[str, Any]:
    """[(id_escouade, joueur, position, OC), …] — une figurine par escouade."""
    shape, size = socle
    units: List[Dict[str, Any]] = []
    units_cache: Dict[str, Any] = {}
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, Any] = {}
    for squad_id, player, (col, row), oc in figurines:
        units.append({
            "id": squad_id, "player": player, "OC": oc, "battle_shocked": squad_id in shocked,
        })
        units_cache[squad_id] = {"player": player, "col": col, "row": row, "orientation": 0}
        model_id = f"{squad_id}#0"
        squad_models[squad_id] = [model_id]
        models_cache[model_id] = {
            "col": col, "row": row, "HP_CUR": 6, "BASE_SHAPE": shape, "BASE_SIZE": size,
        }
    return {
        "units": units,
        "units_cache": units_cache,
        "models_cache": models_cache,
        "squad_models": squad_models,
    }


# ── Les contributions par escouade ─────────────────────────────────────────────────────────────


def test_the_sum_is_exactly_the_addition_of_the_contributions() -> None:
    """LE contrat de la décomposition : additionner les parts rend la somme, à l'unité près.

    Sans cette égalité, la décomposition serait un SECOND comptage — précisément ce qu'elle a été
    introduite pour supprimer.
    """
    state = _state([
        ("1", 1, (1, 1), 4), ("2", 1, (1, 1), 3), ("101", 2, (1, 1), 5), ("3", 1, (20, 20), 2),
    ])
    zones = [ZONE, LOIN]

    contributions = objective_control_contributions(state, zones)

    # Les parts sont assertées LITTÉRALEMENT, pas rejouées : replier ici la même boucle que la
    # production rendrait le test vert tant que les deux copies se trompent de la même façon.
    assert contributions == {
        "1": (1, [4, 0]), "2": (1, [3, 0]), "101": (2, [5, 0]), "3": (1, [0, 2]),
    }
    assert sum_objective_control_oc_multi(state, zones) == [(7, 5), (2, 0)]


def test_removing_one_squad_is_a_filter_on_the_contributions() -> None:
    """« Sans l'escouade 1 » se compose chez l'appelant : la part d'une escouade est récupérable.

    C'est le contrat dont dépend le surplus d'encombrement des bots — il doit lire ce que ses
    ALLIÉS tiennent sans se compter lui-même, donc la fonction de règle n'a pas à connaître cette
    hypothèse. La composition de bout en bout est exercée par `test_bot_crowding.py` ; ici on ne
    verrouille que ce que le moteur doit rendre pour la rendre possible.
    """
    state = _state([("1", 1, (1, 1), 4), ("2", 1, (1, 1), 3), ("101", 2, (1, 1), 5)])

    contributions = objective_control_contributions(state, [ZONE])

    assert contributions["1"] == (1, [4]), "la part d'une escouade doit être lisible seule"
    assert fold_control_contributions(
        (part for sid, part in contributions.items() if sid != "1"), 1
    ) == [(3, 5)], "sans l'escouade 1, il ne reste que l'escouade 2 côté joueur 1"


def test_the_union_prefilter_does_not_lose_control() -> None:
    """Le pré-filtre par union ne s'active QUE sur les zones de l'état — et il ne doit rien perdre.

    Ce test passe par `objective_hex_sets`, donc par les ensembles MÉMOÏSÉS : c'est la seule façon
    d'armer le pré-filtre. Les autres tests du fichier passent des zones littérales, pour
    lesquelles le filtre est volontairement désactivé (l'union mémoïsée ne les décrirait pas), et
    ils ne regarderaient donc rien ici.

    Deux escouades DANS la zone et une hors de tout : le filtre doit écarter la troisième et
    laisser les deux autres, sans quoi le décompte change.
    """
    state = _state([("1", 1, (1, 1), 4), ("101", 2, (1, 1), 3), ("loin", 1, (20, 20), 9)])
    state["objectives"] = [{"id": "A", "hexes": [[1, 1]]}]
    zones = objective_hex_sets(state)

    assert zones == [ZONE], "prémisse : les zones doivent venir de l'état, sinon rien n'est filtré"
    assert objective_hexes_union(state) == frozenset(ZONE)
    assert objective_control_contributions(state, zones) == {"1": (1, [4]), "101": (2, [3])}


def test_a_squad_that_holds_nothing_is_absent_from_the_contributions() -> None:
    """Ne rien apporter et ne pas figurer sont la même chose — trois façons de n'apporter rien."""
    state = _state(
        [("1", 1, (1, 1), 4), ("choquee", 1, (1, 1), 9), ("oc_nul", 1, (1, 1), 0),
         ("ailleurs", 1, next(iter(LOIN)), 3)],
        shocked=["choquee"],
    )

    contributions = objective_control_contributions(state, [ZONE])

    assert set(contributions) == {"1"}, (
        "battle-shockée (01.07), OC nul et hors zone n'apportent rien, donc ne figurent pas"
    )


# ── Le chemin rapide d'empreinte ───────────────────────────────────────────────────────────────


def test_the_single_hex_shortcut_returns_what_the_full_computation_returns() -> None:
    """VERROU du chemin rapide : sur un socle mono-hexe, il doit rendre l'empreinte EXACTE.

    Comparé au calcul général, pas à une valeur écrite à la main — sinon le test et le raccourci
    partageraient la même erreur.
    """
    state = _state([("1", 1, (3, 4), 2)], socle=("round", 1))

    empreintes = list(iter_living_model_footprints(state, "1"))

    assert empreintes == [compute_occupied_hexes(3, 4, "round", 1, 0)]
    assert empreintes == [{(3, 4)}], "un socle mono-hexe occupe son ancre, et rien d'autre"


@pytest.mark.parametrize("orientation", [0, 1, 2, 3, 4, 5])
def test_a_multi_hex_base_still_goes_through_the_full_computation(orientation: int) -> None:
    """Le raccourci ne doit PAS avaler les socles étalés : c'est là qu'il ferait perdre du contrôle.

    Socle OVALE, pas rond : mesuré, un rond rend la même empreinte aux six orientations, donc
    paramétrer là-dessus aurait été six fois le même test. L'ovale, lui, en rend six distinctes.

    L'orientation est posée SUR LA FIGURINE et diffère de celle de l'escouade : c'est l'état que
    produit le pivot à la molette par figurine, et c'est la lecture que le raccourci court-circuite.
    """
    state = _state([("1", 1, (3, 4), 2)], socle=("oval", [4, 2]))
    state["units_cache"]["1"]["orientation"] = (orientation + 3) % 6
    state["models_cache"]["1#0"]["orientation"] = orientation

    empreintes = list(iter_living_model_footprints(state, "1"))

    assert empreintes == [compute_occupied_hexes(3, 4, "oval", [4, 2], orientation)]
    assert len(empreintes[0]) > 1, "socle ovale 4x2 : l'empreinte doit être étalée"


def test_a_round_base_with_a_pair_size_still_raises() -> None:
    """L'ÉTAT CORROMPU DOIT LEVER — le raccourci ne doit surtout pas le rendre plausible.

    Le prédicat lui-même est verrouillé dans son fichier d'origine
    (`test_move_preview_oval_footprint.py`, avec les deux divergences précédentes du même motif) ;
    ce qui se joue ICI est l'aval : l'erreur doit ressortir au lieu d'être remplacée par `{ancre}`.
    """
    state = _state([("1", 1, (3, 4), 2)], socle=("round", [1, 1]))

    with pytest.raises(ValueError):
        list(iter_living_model_footprints(state, "1"))
