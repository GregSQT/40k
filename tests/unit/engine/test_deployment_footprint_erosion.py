#!/usr/bin/env python3
"""Equivalence STRICTE entre l'erosion morphologique de `_get_valid_deployment_hexes` et le
calcul direct (Nk, M, 2) d'origine.

Le masque de deploiement doit designer exactement les memes hexes que `deploy_unit` accepte :
un hex propose puis refuse par le commit produit un deadlock `deploy_footprint_occupied`. Les
deux implementations doivent donc coincider sur TOUS les cas, pas seulement en moyenne.

La reference ci-dessous est le calcul direct d'origine, recopie tel quel.
"""

import numpy as np
import pytest


def _reference_direct(pool_np, off_e_np, off_o_np, even_mask_np, pool_grid, obstacle_grid,
                      board_cols, board_rows):
    """Reference : implementation d'origine, inchangee."""
    valid_mask = np.zeros(len(pool_np), dtype=bool)
    for mask, off_arr in ((even_mask_np, off_e_np), (~even_mask_np, off_o_np)):
        if not np.any(mask):
            continue
        anchors = pool_np[mask]
        fp = anchors[:, None, :] + off_arr[None, :, :]
        fp_c = fp[:, :, 0]
        fp_r = fp[:, :, 1]
        in_bounds = (fp_c >= 0) & (fp_c < board_cols) & (fp_r >= 0) & (fp_r < board_rows)
        fc_s = np.where(in_bounds, fp_c, 0)
        fr_s = np.where(in_bounds, fp_r, 0)
        in_pool = in_bounds & pool_grid[fc_s, fr_s]
        no_obstacle = in_bounds & ~obstacle_grid[fc_s, fr_s]
        valid_mask[mask] = np.all(in_pool & no_obstacle, axis=1)
    return valid_mask


def _erosion(pool_np, off_e_np, off_o_np, even_mask_np, pool_grid, obstacle_grid,
             board_cols, board_rows):
    """Implementation en place dans `engine/action_decoder.py` (memes bornes, meme ordre)."""
    grid_cols, grid_rows = pool_grid.shape
    in_board = np.zeros_like(pool_grid)
    in_board[:board_cols, :board_rows] = True
    ok_grid = pool_grid & ~obstacle_grid & in_board

    valid_mask = np.zeros(len(pool_np), dtype=bool)
    for mask, off_arr in ((even_mask_np, off_e_np), (~even_mask_np, off_o_np)):
        if not np.any(mask):
            continue
        acc = np.ones_like(ok_grid)
        for _off in off_arr:
            dc = int(_off[0])
            dr = int(_off[1])
            shifted = np.zeros_like(ok_grid)
            c_lo = max(0, dc)
            c_hi = grid_cols - max(0, -dc)
            r_lo = max(0, dr)
            r_hi = grid_rows - max(0, -dr)
            if c_lo < c_hi and r_lo < r_hi:
                shifted[c_lo - dc:c_hi - dc, r_lo - dr:r_hi - dr] = ok_grid[c_lo:c_hi, r_lo:r_hi]
            acc &= shifted
            if not acc.any():
                break
        anchors = pool_np[mask]
        valid_mask[mask] = acc[anchors[:, 0], anchors[:, 1]]
    return valid_mask


def _make_case(rng, board_cols, board_rows, n_pool, m_off, wall_ratio, off_span=7):
    grid_cols, grid_rows = board_cols + 10, board_rows + 10
    cols = rng.integers(0, board_cols, size=n_pool)
    rows = rng.integers(0, board_rows, size=n_pool)
    pool_np = np.unique(np.stack([cols, rows], axis=1).astype(np.int32), axis=0)
    pool_grid = np.zeros((grid_cols, grid_rows), dtype=bool)
    pool_grid[pool_np[:, 0], pool_np[:, 1]] = True
    obstacle_grid = np.zeros((grid_cols, grid_rows), dtype=bool)
    if wall_ratio > 0:
        w = rng.random((grid_cols, grid_rows)) < wall_ratio
        obstacle_grid |= w
    off_e = rng.integers(-off_span, off_span + 1, size=(m_off, 2)).astype(np.int32)
    off_o = rng.integers(-off_span, off_span + 1, size=(m_off, 2)).astype(np.int32)
    even = pool_np[:, 0] % 2 == 0
    return pool_np, off_e, off_o, even, pool_grid, obstacle_grid


@pytest.mark.parametrize("n_pool,m_off,wall_ratio", [
    (2000, 19, 0.05), (2000, 211, 0.05), (500, 19, 0.0), (500, 211, 0.30),
    (50, 19, 0.10), (50, 211, 0.10), (5, 19, 0.0), (1, 211, 0.0),
    (3000, 19, 0.60), (3000, 19, 0.95),
])
def test_equivalence(n_pool, m_off, wall_ratio):
    rng = np.random.default_rng(4242 + n_pool + m_off)
    case = _make_case(rng, 60, 80, n_pool, m_off, wall_ratio)
    assert np.array_equal(_erosion(*case, 60, 80), _reference_direct(*case, 60, 80))


def test_equivalence_aleatoire_massif():
    """80 configurations tirees au sort : bornes, murs, parites et empreintes varient."""
    rng = np.random.default_rng(20260718)
    for _ in range(80):
        bc = int(rng.integers(12, 70))
        br = int(rng.integers(12, 70))
        case = _make_case(
            rng, bc, br,
            n_pool=int(rng.integers(1, 1500)),
            m_off=int(rng.integers(1, 60)),
            wall_ratio=float(rng.random()) * 0.8,
            off_span=int(rng.integers(1, 12)),
        )
        assert np.array_equal(_erosion(*case, bc, br), _reference_direct(*case, bc, br)), \
            f"divergence board={bc}x{br}"


def test_empreinte_debordant_le_plateau():
    """Une empreinte qui sort du plateau doit etre rejetee — cas limite du contrat `in_bounds`."""
    bc, br = 20, 20
    pool_np = np.array([[0, 0], [1, 1], [19, 19], [18, 18], [10, 10]], dtype=np.int32)
    pool_grid = np.zeros((bc + 10, br + 10), dtype=bool)
    pool_grid[pool_np[:, 0], pool_np[:, 1]] = True
    obstacle_grid = np.zeros((bc + 10, br + 10), dtype=bool)
    off = np.array([[0, 0], [5, 5], [-5, -5]], dtype=np.int32)
    even = pool_np[:, 0] % 2 == 0
    case = (pool_np, off, off, even, pool_grid, obstacle_grid)
    got = _erosion(*case, bc, br)
    assert np.array_equal(got, _reference_direct(*case, bc, br))
    assert not got.any(), "aucune ancre ne peut satisfaire une empreinte hors pool"


def test_pool_entierement_bloque():
    """Grille 100% murs : aucune ancre valide, et l'early-exit ne change pas le resultat."""
    bc, br = 30, 30
    rng = np.random.default_rng(9)
    case = _make_case(rng, bc, br, n_pool=800, m_off=40, wall_ratio=1.0)
    got = _erosion(*case, bc, br)
    assert np.array_equal(got, _reference_direct(*case, bc, br))
    assert not got.any()
