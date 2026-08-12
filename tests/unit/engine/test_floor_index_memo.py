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
