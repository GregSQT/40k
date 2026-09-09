"""Verrous de l'index d'étages mémoïsé (`engine.terrain_utils._floor_index`).

Deux invariants que la mémoïsation a failli emporter :

1. Les accesseurs qui n'ont JAMAIS lu ``polygon_vertices`` ne doivent pas se mettre à l'exiger.
   Cette clé ne sert qu'au confinement euclidien des socles ronds (13.06) ; ``floor_levels_present``,
   ``floor_hexes_at_level``, ``floor_height_at`` et ``low_clearance_ground_hexes`` répondent sans.
2. Un terrain muté EN PLACE ne doit pas continuer à servir l'index de son état précédent.
"""
from typing import Any, Dict, List

import pytest

from shared.data_validation import ConfigurationError
from engine.terrain_utils import (
    _floor_index,
    floor_height_at,
    floor_hexes_at_level,
    floor_levels_present,
    floor_polys_at_level,
)


def _terrain_without_polys() -> List[Dict[str, Any]]:
    """Étage décrit par ses seuls hexes — forme utilisée par les fixtures moteur."""
    return [{"floors": [{"level": 1, "height_inches": 3.0, "hexes": [[10, 10], [11, 10]]}]}]


def _terrain_with_polys() -> List[Dict[str, Any]]:
    return [{
        "floors": [{
            "level": 1, "height_inches": 3.0, "hexes": [[10, 10], [11, 10]],
            "polygon_vertices": [[10, 10], [12, 10], [12, 12], [10, 12]],
        }],
    }]


def test_floor_accessors_do_not_require_polygon_vertices():
    terrain = _terrain_without_polys()

    assert floor_levels_present(terrain) == (1,)
    assert floor_hexes_at_level(terrain, 1) == frozenset({(10, 10), (11, 10)})
    assert floor_height_at(terrain, 10, 10, 1) == pytest.approx(3.0)
    # `_floor_index(...).low_clearance(hauteur)` et non `low_clearance_ground_hexes` : la
    # fonction publique exige la FIGURINE et son escouade (§13.06), là où ce test ne parle que
    # de l'index et de ses accesseurs. Lui fabriquer deux entrées ne prouverait rien de plus.
    assert _floor_index(terrain).low_clearance(5.0) == {(10, 10), (11, 10)}

    # Contre-épreuve : la clé reste EXIGÉE par le seul accesseur qui la lit — pas d'assouplissement
    # du schéma, juste la fin d'une exigence parasite. L'exception est TYPÉE et son message vérifié :
    # un `pytest.raises(Exception)` resterait vert sur une faute de frappe d'import.
    with pytest.raises(ConfigurationError, match="polygon_vertices"):
        floor_polys_at_level(terrain, 1)


def test_overlapping_floors_with_conflicting_heights_are_refused():
    """Deux planchers superposés au même niveau à des hauteurs différentes = état incohérent.

    Ni « le premier » ni « le dernier » n'est la bonne hauteur de cette case : le seul verdict
    juste est le refus explicite.
    """
    terrain = [
        {"floors": [{"level": 1, "height_inches": 3.0, "hexes": [[10, 10]]}]},
        {"floors": [{"level": 1, "height_inches": 9.0, "hexes": [[10, 10]]}]},
    ]
    with pytest.raises(ValueError, match="conflicting height_inches"):
        floor_height_at(terrain, 10, 10, 1)

    # Même recouvrement, MÊME hauteur : deux ruines mitoyennes, aucune incohérence.
    coherent = [
        {"floors": [{"level": 1, "height_inches": 3.0, "hexes": [[10, 10]]}]},
        {"floors": [{"level": 1, "height_inches": 3.0, "hexes": [[10, 10], [11, 10]]}]},
    ]
    assert floor_height_at(coherent, 10, 10, 1) == pytest.approx(3.0)


def test_floor_polys_are_served_when_declared():
    assert len(floor_polys_at_level(_terrain_with_polys(), 1)) == 1


def test_in_place_terrain_mutation_invalidates_the_memo():
    """La mémoïsation est clé-par-identité : sans validation, l'index d'avant survivrait."""
    terrain = _terrain_without_polys()
    assert floor_hexes_at_level(terrain, 1) == frozenset({(10, 10), (11, 10)})  # index construit

    terrain[0]["floors"][0]["hexes"].append([12, 10])
    assert floor_hexes_at_level(terrain, 1) == frozenset({(10, 10), (11, 10), (12, 10)}), (
        "l'index mémoïsé décrit un terrain qui n'existe plus"
    )
    assert floor_height_at(terrain, 12, 10, 1) == pytest.approx(3.0)

    # Un étage AJOUTÉ à une aire déjà indexée compte aussi.
    terrain[0]["floors"].append({"level": 2, "height_inches": 7.0, "hexes": [[10, 10]]})
    assert floor_levels_present(terrain) == (1, 2)


def test_the_level_by_cell_memo_keeps_its_terrain_alive():
    """`floor_level_by_cell` garde une référence forte au terrain qu'il indexe.

    Le mémo est clé par `id(terrain_areas)`, comme son jumeau `_floor_index`. Une clé d'adresse
    n'est sûre que si l'entrée EMPÊCHE la liste d'être libérée : sinon une liste morte rend son
    adresse à une autre, et la signature de forme (`_floor_signature`, qui ne compte que niveau,
    hauteur et nombre d'hexes) ne suffit pas à les distinguer — la carte de niveaux d'un terrain
    serait servie pour un autre, en silence et sans qu'aucun contrôle ne bouge.

    C'est le seul mode de défaillance de ce cache, et il est invisible par construction : on
    vérifie donc la référence elle-même, pas un symptôme qui n'apparaîtrait qu'au recyclage
    d'adresse.
    """
    from engine.terrain_utils import _FLOOR_LEVEL_BY_CELL_CACHE, floor_level_by_cell

    # Terrain AVEC polygones : un socle rond est confiné par le bord continu de l'étage (13.06),
    # donc `floor_level_by_cell` en a besoin — c'est la forme que le chargeur produit toujours.
    terrain = _terrain_with_polys()
    mapping = floor_level_by_cell(terrain, "round", 1, 0)
    assert mapping, "aucune cellule d'étage résolue : le test ne prouverait rien"

    entries = [v for v in _FLOOR_LEVEL_BY_CELL_CACHE.values() if v[1] is mapping]
    assert entries, "la carte rendue n'est pas celle qui a été mémoïsée"
    assert entries[0][0] is terrain, (
        "l'entrée du mémo ne retient pas la liste `terrain_areas` : sa clé d'adresse peut "
        "désigner un autre terrain après recyclage"
    )
    assert floor_level_by_cell(terrain, "round", 1, 0) is mapping, "second appel non mémoïsé"


def test_the_level_by_cell_memo_follows_an_in_place_mutation():
    """Muté en place, le terrain ne doit pas continuer à servir la carte de son état précédent.

    Même invariant que son jumeau `_floor_index` ci-dessus, et pour la même raison : la signature
    de forme est relue à CHAQUE accès, donc un étage ajouté change la clé.
    """
    from engine.terrain_utils import floor_level_by_cell

    terrain = _terrain_with_polys()
    before = dict(floor_level_by_cell(terrain, "round", 1, 0))
    assert set(before.values()) == {1}, "l'état de départ ne porte pas le seul niveau 1"
    # Un étage AJOUTÉ au-dessus : les mêmes cellules appartiennent désormais au niveau le plus
    # haut où le socle tient (13.06 ne connaît pas de position intermédiaire).
    terrain[0]["floors"].append({
        "level": 2, "height_inches": 7.0, "hexes": [[10, 10], [11, 10]],
        "polygon_vertices": [[10, 10], [12, 10], [12, 12], [10, 12]],
    })
    after = floor_level_by_cell(terrain, "round", 1, 0)
    assert set(after.values()) == {2}, (
        f"la carte mémoïsée décrit un terrain qui n'existe plus : {dict(after)}"
    )
