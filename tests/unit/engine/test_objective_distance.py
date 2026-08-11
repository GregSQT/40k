"""Distance à l'AIRE d'un objectif (14.02), et non à son centre.

Un objectif est toute l'aire de terrain. Mesurée au centroïde, une unité posée sur le bord d'un
objectif de 3000 hexes ressortait à une trentaine d'hexes de « son » objectif — assez pour que
l'agent en vise un autre et que le scoring de déploiement préfère un hexe hors de toute aire.

Les tests d'exactitude comparent l'implémentation optimisée (segments par colonne, puis carte
mémoïsée) à une ÉNUMÉRATION NAÏVE de tous les hexes de l'aire. C'est le seul oracle qui ne
reprend pas l'optimisation qu'il doit valider.
"""

import numpy as np
import pytest

from engine import objective_distance

from engine.combat_utils import calculate_hex_distance
from engine.objective_distance import (
    _DISTANCE_MAP_CACHE,
    _IDENTITY_CACHE,
    _MAX_CACHED_BOARDS,
    _MAX_IDENTITY_ENTRIES,
    _zone_column_segments,
    distance_to_objective,
    distances_to_zone,
    nearest_objective_zone,
    objective_distance_maps,
)

from config_loader import get_board_size

BOARD_COLS, BOARD_ROWS = get_board_size()
#: Fenêtre balayée par les tests d'exactitude. La carte couvre tout le plateau, mais l'oracle
#: naïf est en O(hexes de l'aire) par hexe : le vérifier sur 66 000 hexes coûterait des minutes
#: sans rien prouver de plus qu'une fenêtre qui contient l'aire, ses bords et ses coins.
CHECK_COLS, CHECK_ROWS = 40, 40


def _rect_hexes(col_min, row_min, col_max, row_max):
    return [[c, r] for c in range(col_min, col_max + 1) for r in range(row_min, row_max + 1)]


def _game_state(objectives):
    return {"objectives": objectives}


def _naive_distance(col, row, hexes):
    """Oracle : minimum sur TOUS les hexes de l'aire, sans aucune optimisation."""
    return min(calculate_hex_distance(col, row, int(h[0]), int(h[1])) for h in hexes)


@pytest.fixture(autouse=True)
def _clear_cache():
    _DISTANCE_MAP_CACHE.clear()
    _IDENTITY_CACHE.clear()
    yield
    _DISTANCE_MAP_CACHE.clear()
    _IDENTITY_CACHE.clear()


# --------------------------------------------------------------------------------------------
# Exactitude
# --------------------------------------------------------------------------------------------


def test_matches_naive_enumeration_over_the_whole_board():
    hexes = _rect_hexes(10, 12, 20, 25)
    gs = _game_state([{"id": "o", "name": "o", "hexes": hexes}])
    distance_map = objective_distance_maps(gs)[0]
    for col in range(CHECK_COLS):
        for row in range(CHECK_ROWS):
            assert int(distance_map[col, row]) == _naive_distance(col, row, hexes), (
                f"hexe ({col},{row}) : carte {int(distance_map[col, row])} ≠ "
                f"énumération {_naive_distance(col, row, hexes)}"
            )


def test_matches_naive_enumeration_on_a_non_convex_area():
    """Aire en L : plusieurs segments dans une même colonne, aucune hypothèse de convexité."""
    hexes = _rect_hexes(10, 10, 20, 13) + _rect_hexes(10, 14, 13, 22)
    gs = _game_state([{"id": "o", "name": "o", "hexes": hexes}])
    distance_map = objective_distance_maps(gs)[0]
    for col in range(CHECK_COLS):
        for row in range(CHECK_ROWS):
            assert int(distance_map[col, row]) == _naive_distance(col, row, hexes)


def test_distance_is_zero_inside_the_area():
    """C'est tout l'objet du chantier : être DANS l'aire, c'est être à l'objectif (14.02)."""
    hexes = _rect_hexes(10, 10, 20, 25)
    gs = _game_state([{"id": "o", "name": "o", "hexes": hexes}])
    for col, row in [(10, 10), (20, 25), (15, 18), (10, 25), (20, 10)]:
        assert distance_to_objective(gs, 0, col, row) == 0


def test_border_of_a_large_area_beats_the_centroid():
    """Le cas qui motive le chantier, chiffré : bord d'une grande aire vs centre.

    Une unité sur le bord de l'aire est DEDANS (distance 0), alors que le centroïde la donnait
    à la moitié de la diagonale. Sans ça, l'objectif qu'elle occupe n'était pas « le plus
    proche » et l'agent pouvait en viser un autre.
    """
    big = _rect_hexes(0, 0, 24, 30)
    far = _rect_hexes(34, 34, 36, 36)
    gs = _game_state([
        {"id": "big", "name": "big", "hexes": big},
        {"id": "far", "name": "far", "hexes": far},
    ])
    border_col, border_row = 24, 30
    centroid = (sum(h[0] for h in big) // len(big), sum(h[1] for h in big) // len(big))
    assert distance_to_objective(gs, 0, border_col, border_row) == 0
    assert calculate_hex_distance(border_col, border_row, *centroid) > 10
    assert nearest_objective_zone(gs, border_col, border_row) == 0


# --------------------------------------------------------------------------------------------
# Structure et contrats
# --------------------------------------------------------------------------------------------


def test_segments_compress_the_area():
    hexes = {(c, r) for c in range(10, 30) for r in range(10, 60)}
    segments = _zone_column_segments(hexes)
    assert len(segments) == 20  # une par colonne, toutes contiguës
    assert len(segments) < len(hexes) / 20


def test_non_contiguous_column_yields_two_segments():
    hexes = {(5, 1), (5, 2), (5, 9), (5, 10)}
    assert sorted(_zone_column_segments(hexes)) == [(5, 1, 2), (5, 9, 10)]


def test_empty_area_raises_instead_of_scoring_flat():
    cols = np.array([1, 2])
    rows = np.array([1, 2])
    with pytest.raises(ValueError, match="aire d'objectif vide"):
        distances_to_zone(cols, rows, [])


def test_zone_index_out_of_range_raises():
    gs = _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(1, 1, 3, 3)}])
    with pytest.raises(IndexError):
        distance_to_objective(gs, 4, 0, 0)


def test_hex_outside_the_board_raises():
    gs = _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(1, 1, 3, 3)}])
    with pytest.raises(ValueError, match="hors plateau"):
        distance_to_objective(gs, 0, BOARD_COLS, 0)


def test_no_objective_yields_no_map_and_zone_zero():
    gs = _game_state([])
    assert objective_distance_maps(gs) == []
    assert nearest_objective_zone(gs, 5, 5) == 0


def test_nearest_zone_breaks_ties_on_the_lowest_index():
    """Un ordre stable : une décision d'agent ne doit pas dépendre d'un ordre de parcours."""
    gs = _game_state([
        {"id": "a", "name": "a", "hexes": _rect_hexes(10, 10, 11, 11)},
        {"id": "b", "name": "b", "hexes": _rect_hexes(14, 10, 15, 11)},
    ])
    assert nearest_objective_zone(gs, 12, 10) == 0
    assert nearest_objective_zone(gs, 13, 10) == 1


# --------------------------------------------------------------------------------------------
# Cache : c'est lui qui rend la carte utilisable en entraînement
# --------------------------------------------------------------------------------------------


def test_cache_is_keyed_by_content_not_by_state_identity():
    """Chaque `reset()` d'épisode reconstruit un game_state : un cache par identité repaierait
    la construction de la carte à chaque épisode et sur chaque environnement vectorisé."""
    hexes = _rect_hexes(10, 10, 20, 25)
    first = objective_distance_maps(_game_state([{"id": "o", "name": "o", "hexes": hexes}]))
    assert len(_DISTANCE_MAP_CACHE) == 1
    second = objective_distance_maps(
        _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(10, 10, 20, 25)}])
    )
    assert len(_DISTANCE_MAP_CACHE) == 1
    assert first[0] is second[0]


def test_different_areas_do_not_share_a_cache_entry():
    a = objective_distance_maps(
        _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(10, 10, 20, 25)}])
    )
    b = objective_distance_maps(
        _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(1, 1, 5, 5)}])
    )
    assert len(_DISTANCE_MAP_CACHE) == 2
    assert int(a[0][10, 10]) == 0
    assert int(b[0][10, 10]) > 0


def test_cache_is_bounded():
    """Un entraînement multi-scénarios ferait croître la mémoire sans borne."""
    for i in range(_MAX_CACHED_BOARDS + 3):
        objective_distance_maps(
            _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(1, 1, 2 + i, 3)}])
        )
    assert len(_DISTANCE_MAP_CACHE) == _MAX_CACHED_BOARDS


def test_identity_shortcut_avoids_rehashing_the_areas():
    """Le hachage des aires coûte 6 ms sur le scénario PvE, et cette fonction est appelée par
    unité et par décision de bot. Dans un épisode, `objectives` est le MÊME objet : la
    comparaison d'identité doit court-circuiter le cache de contenu."""
    objectives = [{"id": "o", "name": "o", "hexes": _rect_hexes(10, 10, 20, 25)}]
    gs = _game_state(objectives)
    first = objective_distance_maps(gs)
    assert len(_IDENTITY_CACHE) == 1
    calls = []
    original = objective_distance._cache_key
    def _spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    objective_distance._cache_key = _spy
    try:
        again = objective_distance_maps(gs)
    finally:
        objective_distance._cache_key = original
    assert again[0] is first[0]
    assert calls == [], "le raccourci d'identité n'a pas court-circuité le hachage du contenu"


def test_identity_cache_is_bounded():
    for i in range(_MAX_IDENTITY_ENTRIES + 5):
        objective_distance_maps(
            _game_state([{"id": "o", "name": "o", "hexes": _rect_hexes(1, 1, 3, 3)}])
        )
    assert len(_IDENTITY_CACHE) <= _MAX_IDENTITY_ENTRIES
