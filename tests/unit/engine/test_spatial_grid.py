#!/usr/bin/env python3
"""Geometrie de la grille egocentrique de mouvement (engine/spatial_grid.py).

Spec : Documentation/Implementation/A_faire/move_action_space_spatial_rework.md §6.2/§10.2/§10.9.
Ces tests verrouillent le contrat partage entre obs (T1), masque (T2) et decoder (T3).
"""

import math

import pytest

from engine.combat_utils import calculate_hex_distance
from engine.spatial_grid import (
    GRID_CELL_COUNT,
    GRID_SIZE,
    HEX_STEP_PX,
    cell_center_px,
    cell_from_index,
    cell_index,
    hex_to_cell,
    project_pool_to_grid,
)


def test_hex_step_px_matches_engine_geometry():
    """Le pas hex vaut sqrt(3) dans l'espace `_hex_center`, sur les 6 voisins et les 2 parites."""
    from engine.hex_utils import _hex_center, get_neighbors

    for col, row in ((10, 10), (11, 10), (0, 0), (7, 12)):
        ax, ay = _hex_center(col, row)
        for nc, nr in get_neighbors(col, row):
            x, y = _hex_center(nc, nr)
            assert math.hypot(x - ax, y - ay) == pytest.approx(HEX_STEP_PX)


@pytest.mark.parametrize("anchor", [(50, 50), (51, 50), (50, 51), (51, 51)])
def test_anchor_maps_to_grid_center(anchor):
    """L'ancre tombe sur la cellule centrale, quelle que soit sa parite (grille egocentrique)."""
    col, row = anchor
    assert hex_to_cell(col, row, col, row, half_extent_subhex=60) == (GRID_SIZE // 2, GRID_SIZE // 2)


@pytest.mark.parametrize("half_extent", [20, 30, 50, 60, 100])
@pytest.mark.parametrize("anchor", [(80, 80), (81, 80)])
def test_every_reachable_hex_falls_inside_the_grid(half_extent, anchor):
    """Propriete CENTRALE : tout hex a distance-hex <= half_extent est representable.

    Garantie par le dimensionnement sur HEX_STEP_PX=sqrt(3) + la demi-marge de `_half_extent_px`.
    Mesure de reference : avec ENGAGEMENT_NORM_HEX_WIDTH=1.5 a la place, 272/10981 destinations
    (2.5%) sortent de la grille a half_extent=60, concentrees sur l'axe vertical. Elles sont
    LEGALES : les perdre bornerait l'agent.
    """
    acol, arow = anchor
    for col in range(acol - half_extent - 2, acol + half_extent + 3):
        for row in range(arow - half_extent - 2, arow + half_extent + 3):
            if calculate_hex_distance(acol, arow, col, row) > half_extent:
                continue
            cell = hex_to_cell(col, row, acol, arow, half_extent)
            assert cell is not None, (
                f"hex ({col},{row}) a distance "
                f"{calculate_hex_distance(acol, arow, col, row)} <= {half_extent} "
                f"tombe HORS de la grille"
            )


@pytest.mark.parametrize("half_extent", [12, 60, 90])
@pytest.mark.parametrize("anchor", [(80, 80), (81, 80)])
def test_vectorized_projection_matches_scalar_exactly(half_extent, anchor):
    """`hex_arrays_to_cells` == `hex_to_cell` (clamp=False), sur TOUTE la fenetre.

    Verrouille la propriete « source unique » : l'obs utilise le chemin vectorise, le masque
    et le decoder le chemin scalaire. Toute divergence ferait designer a une meme cellule deux
    hexes differents selon la couche.
    """
    import numpy as np

    from engine.spatial_grid import hex_arrays_to_cells

    acol, arow = anchor
    cols, rows = [], []
    for col in range(acol - half_extent - 3, acol + half_extent + 4):
        for row in range(arow - half_extent - 3, arow + half_extent + 4):
            cols.append(col)
            rows.append(row)

    gx, gy, valid = hex_arrays_to_cells(np.array(cols), np.array(rows), acol, arow, half_extent)
    for i, (col, row) in enumerate(zip(cols, rows)):
        scalar = hex_to_cell(col, row, acol, arow, half_extent)
        if scalar is None:
            assert not valid[i], f"hex ({col},{row}) : scalaire=hors grille, vectorise=dans la grille"
        else:
            assert valid[i], f"hex ({col},{row}) : scalaire={scalar}, vectorise=hors grille"
            assert (int(gx[i]), int(gy[i])) == scalar


def test_far_hexes_are_rejected_without_clamp():
    """Hors grille -> None. Sans clamp, aucun rabattement silencieux sur le bord."""
    assert hex_to_cell(80 + 400, 80, 80, 80, half_extent_subhex=30) is None
    assert hex_to_cell(80, 80 + 400, 80, 80, half_extent_subhex=30) is None


def test_clamp_rabat_sur_le_bord():
    cell = hex_to_cell(80 + 400, 80, 80, 80, half_extent_subhex=30, clamp=True)
    assert cell == (GRID_SIZE - 1, GRID_SIZE // 2)


def test_cell_index_roundtrip():
    for idx in (0, 1, GRID_SIZE, GRID_CELL_COUNT - 1):
        gx, gy = cell_from_index(idx)
        assert cell_index(gx, gy) == idx


def test_cell_index_rejects_out_of_grid():
    with pytest.raises(ValueError):
        cell_index(GRID_SIZE, 0)
    with pytest.raises(ValueError):
        cell_from_index(GRID_CELL_COUNT)


def test_cell_center_is_inside_its_own_cell():
    """Le centre geometrique d'une cellule reprojette sur cette meme cellule."""
    acol, arow, he = 80, 80, 60
    for gx in range(0, GRID_SIZE, 7):
        for gy in range(0, GRID_SIZE, 7):
            cx, cy = cell_center_px(gx, gy, acol, arow, he)
            # Reprojection analytique (meme formule que hex_to_cell, sans passer par un hex).
            from engine.hex_utils import _hex_center

            ax, ay = _hex_center(acol, arow)
            w = he * HEX_STEP_PX
            rgx = int(math.floor(((cx - ax) / w + 1.0) * 0.5 * GRID_SIZE))
            rgy = int(math.floor(((cy - ay) / w + 1.0) * 0.5 * GRID_SIZE))
            assert (rgx, rgy) == (gx, gy)


def test_project_pool_keeps_hex_nearest_to_cell_center():
    """Collision de cellule : l'hex retenu est le plus proche du centre geometrique (§10.3)."""
    acol, arow, he = 80, 80, 60
    # half_extent=60 -> cellule ~3.75 subhex : plusieurs hexes tombent dans la meme cellule.
    pool = {}
    for col in range(acol - 3, acol + 4):
        for row in range(arow - 3, arow + 4):
            if (col, row) == (acol, arow):
                continue
            pool[(col, row)] = calculate_hex_distance(acol, arow, col, row)

    projected = project_pool_to_grid(pool, acol, arow, he)
    assert projected, "projection vide"

    from engine.hex_utils import _hex_center

    for idx, (chosen, cost) in projected.items():
        gx, gy = cell_from_index(idx)
        cx, cy = cell_center_px(gx, gy, acol, arow, he)
        rivals = [
            h for h in pool
            if hex_to_cell(h[0], h[1], acol, arow, he, clamp=True) == (gx, gy)
        ]
        best_d2 = min((_hex_center(*h)[0] - cx) ** 2 + (_hex_center(*h)[1] - cy) ** 2 for h in rivals)
        chosen_d2 = (_hex_center(*chosen)[0] - cx) ** 2 + (_hex_center(*chosen)[1] - cy) ** 2
        assert chosen_d2 == pytest.approx(best_d2)
        assert cost == pool[chosen]


def test_project_pool_tie_break_is_deterministic_by_min_col_row():
    """Egalite de distance au centre -> (col,row) min. Ordre d'insertion sans effet (§10.3)."""
    acol, arow, he = 80, 80, 60
    pool = {(c, r): calculate_hex_distance(acol, arow, c, r)
            for c in range(acol - 4, acol + 5)
            for r in range(arow - 4, arow + 5)
            if (c, r) != (acol, arow)}

    forward = project_pool_to_grid(pool, acol, arow, he)
    reversed_pool = dict(reversed(list(pool.items())))
    backward = project_pool_to_grid(reversed_pool, acol, arow, he)
    assert forward == backward


def test_project_pool_carries_geodesic_cost_not_crow_flight():
    """Le cout transporte est bien celui fourni (chemin BFS), pas une distance recalculee."""
    acol, arow, he = 80, 80, 60
    # Cout volontairement incoherent avec la distance a vol d'oiseau : contournement d'un mur.
    pool = {(acol + 1, arow): 37}
    projected = project_pool_to_grid(pool, acol, arow, he)
    assert list(projected.values())[0] == ((acol + 1, arow), 37)
