#!/usr/bin/env python3
"""Equivalence STRICTE entre `project_pool_to_grid` (vectorise) et sa reference scalaire.

`project_pool_to_grid` est la source UNIQUE du masque (T2) et du decodage (T3) : si les deux
implementations divergent d'un seul hex, le masque autorise une cellule et le decoder y envoie
l'escouade ailleurs — exactement la classe de bug que la refonte spatiale supprime.

La reference ci-dessous est l'implementation scalaire d'origine, recopiee telle quelle. Elle vit
dans le test (et non en prod) pour ne pas laisser deux chemins executables diverger en silence.
"""

import random

import pytest

from engine.spatial_grid import (
    GRID_SIZE,
    cell_center_px,
    cell_index,
    hex_to_cell,
    project_pool_to_grid,
)
from engine.hex_utils import _hex_center


def _project_pool_to_grid_scalar(pool_costs, anchor_col, anchor_row, half_extent_subhex):
    """Reference : implementation scalaire d'origine, inchangee."""
    best = {}
    for (col, row), cost in pool_costs.items():
        cell = hex_to_cell(col, row, anchor_col, anchor_row, half_extent_subhex, clamp=True)
        if cell is None:
            continue
        idx = cell_index(*cell)
        cx, cy = cell_center_px(cell[0], cell[1], anchor_col, anchor_row, half_extent_subhex)
        hx, hy = _hex_center(col, row)
        d2 = (hx - cx) ** 2 + (hy - cy) ** 2
        current = best.get(idx)
        if current is None:
            best[idx] = (d2, (col, row), float(cost))
            continue
        cur_d2, cur_hex, _ = current
        if d2 < cur_d2 - 1e-12 or (abs(d2 - cur_d2) <= 1e-12 and (col, row) < cur_hex):
            best[idx] = (d2, (col, row), float(cost))
    return {idx: (hex_cr, cost) for idx, (_, hex_cr, cost) in best.items()}


def _disk_pool(anchor_col, anchor_row, budget):
    """Pool en disque autour de l'ancre, cout = distance de chemin approchee (comme le BFS)."""
    pool = {}
    for dc in range(-budget, budget + 1):
        for dr in range(-budget, budget + 1):
            col, row = anchor_col + dc, anchor_row + dr
            if col < 0 or row < 0:
                continue
            cost = float(max(abs(dc), abs(dr)))
            if cost <= budget:
                pool[(col, row)] = cost
    return pool


@pytest.mark.parametrize("anchor,budget", [
    ((10, 10), 3), ((10, 10), 12), ((0, 0), 8), ((43, 59), 10),
    ((21, 30), 25), ((5, 40), 60), ((30, 7), 1), ((17, 17), 44),
])
def test_equivalence_disque(anchor, budget):
    """Le dict renvoye est IDENTIQUE (cles, hexes, couts) sur des pools en disque."""
    pool = _disk_pool(anchor[0], anchor[1], budget)
    half = max(1, budget)
    got = project_pool_to_grid(pool, anchor[0], anchor[1], half)
    ref = _project_pool_to_grid_scalar(pool, anchor[0], anchor[1], half)
    assert got == ref, f"divergence pour anchor={anchor} budget={budget}"


def test_equivalence_pools_aleatoires():
    """Pools desordonnes : l'ordre d'insertion pilote le departage, il doit etre respecte."""
    rng = random.Random(20260718)
    for _ in range(200):
        anchor_col = rng.randrange(0, 44)
        anchor_row = rng.randrange(0, 60)
        half = rng.randrange(1, 61)
        hexes = [
            (rng.randrange(0, 44), rng.randrange(0, 60))
            for _ in range(rng.randrange(1, 400))
        ]
        pool = {h: float(rng.randrange(0, 60)) for h in hexes}
        got = project_pool_to_grid(pool, anchor_col, anchor_row, half)
        ref = _project_pool_to_grid_scalar(pool, anchor_col, anchor_row, half)
        assert got == ref, f"divergence anchor=({anchor_col},{anchor_row}) half={half}"


def test_equivalence_collisions_forcees():
    """Grille minuscule : beaucoup d'hexes par cellule, donc le departage est sollicite."""
    for half in (1, 2, 3):
        pool = _disk_pool(20, 20, 30)
        got = project_pool_to_grid(pool, 20, 20, half)
        ref = _project_pool_to_grid_scalar(pool, 20, 20, half)
        assert got == ref, f"divergence half={half}"
        assert len(got) <= GRID_SIZE * GRID_SIZE


def test_pool_vide():
    """Pool vide -> dict vide (et pas d'erreur numpy sur tableau de taille 0)."""
    assert project_pool_to_grid({}, 10, 10, 5) == {}
    assert project_pool_to_grid({}, 10, 10, 5) == _project_pool_to_grid_scalar({}, 10, 10, 5)


def test_cout_preserve_a_l_identique():
    """Le cout geodesique renvoye est bien celui du pool (il pilote normal vs advance)."""
    pool = {(10, 10): 0.0, (11, 10): 1.0, (12, 10): 2.5, (13, 10): 7.25}
    got = project_pool_to_grid(pool, 10, 10, 8)
    couts = sorted(cost for _hex, cost in got.values())
    assert couts == [0.0, 1.0, 2.5, 7.25]
