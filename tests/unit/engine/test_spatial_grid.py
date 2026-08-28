#!/usr/bin/env python3
"""Geometrie de la grille egocentrique de mouvement (engine/spatial_grid.py).

Spec : Documentation/Reference/training/observation_et_actions.md §6.2/§10.2/§10.9.
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


def test_hex_centers_px_matches_hex_center_exactly():
    """`hex_centers_px` == `_hex_center`, hex par hex, sur les deux parites de colonne.

    Ce jumeau vectorise a DEUX appelants (`hex_arrays_to_cells` pour la rasterisation, et
    l'ancre de zone de deploiement de §0.40 point 2, qui projette ~16 000 hexes). Le test
    d'equivalence `hex_arrays_to_cells` == `hex_to_cell` ne couvre que le premier : sans ce
    verrou-ci, une derive de la formule ferait ancrer la grille ailleurs sans rien lever.
    """
    import numpy as np

    from engine.hex_utils import _hex_center
    from engine.spatial_grid import hex_centers_px

    cols, rows = [], []
    for col in range(0, 220, 7):
        for row in range(0, 300, 11):
            cols.append(col)
            rows.append(row)
    x, y = hex_centers_px(np.array(cols), np.array(rows))
    expected = np.array([_hex_center(c, r) for c, r in zip(cols, rows)], dtype=np.float64)
    assert np.array_equal(np.stack([x, y], axis=1), expected)


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


# ============================================================================
# V11 §0.32 T-K — encodage du cout de move (`normalize_move_costs`)
# ============================================================================


def test_normalize_move_costs_puts_the_frontier_on_the_same_constant_for_every_unit():
    """LE contrat : `cout == M` vaut le seuil, quels que soient le MOVE et l'echelle du board.

    C'est ce qui rend la frontiere normal/advance lisible par le CNN, qui ne recoit que la grille.
    """
    import numpy as np

    from engine.spatial_grid import MOVE_COST_ADVANCE_THRESHOLD, normalize_move_costs

    # (M, H) : MOVE 4" a 14" en x1 et en x5, H = M + 6" x inches_to_subhex.
    for normal, half in ((4, 10), (6, 12), (14, 20), (20, 50), (30, 60), (70, 100)):
        got = float(normalize_move_costs(np.array([normal]), normal, half, engaged=False)[0])
        assert got == pytest.approx(MOVE_COST_ADVANCE_THRESHOLD, abs=1e-6), (
            f"M={normal}, H={half} : frontiere a {got} au lieu de {MOVE_COST_ADVANCE_THRESHOLD}"
        )


def test_normalize_move_costs_spans_the_unit_interval_and_stays_monotonic():
    """0 -> 0, budget Advance maximal -> 1, strictement croissant entre les deux."""
    import numpy as np

    from engine.spatial_grid import normalize_move_costs

    normal, half = 30, 60
    costs = np.arange(0, half + 1, dtype=np.float64)
    out = normalize_move_costs(costs, normal, half, engaged=False)
    assert float(out[0]) == pytest.approx(0.0, abs=1e-6)
    assert float(out[-1]) == pytest.approx(1.0, abs=1e-6)
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0
    assert all(float(b) > float(a) for a, b in zip(out, out[1:]))


def test_normalize_move_costs_with_a_null_normal_budget_calls_everything_advance():
    """Budget normal NUL (Take to the skies) : rester sur place est le seul « normal ».

    Aucune division par zero masquee : le regime normal est vide et le dit.
    """
    import numpy as np

    from engine.spatial_grid import MOVE_COST_ADVANCE_THRESHOLD, normalize_move_costs

    out = normalize_move_costs(np.array([0.0, 1.0, 20.0]), 0, 20, engaged=False)
    assert float(out[0]) == pytest.approx(0.0, abs=1e-6)
    assert float(out[1]) > MOVE_COST_ADVANCE_THRESHOLD
    assert float(out[2]) == pytest.approx(1.0, abs=1e-6)


def test_normalize_move_costs_engaged_squad_is_encoded_above_the_threshold():
    """Escouade ENGAGEE : tout mouvement est un Fall Back (09.05) qui coute le tir et la charge.

    L'encoder sous le seuil disait « je garde mon tir » — FAUX : le CNN aurait du croiser avec
    le canal EZ pour le corriger, exactement le croisement que ce canal existe pour eviter. La
    semantique du seuil est uniforme : au-dessus = bouger ici coute le tir.
    """
    import numpy as np

    from engine.spatial_grid import MOVE_COST_ADVANCE_THRESHOLD, normalize_move_costs

    normal, half = 6, 12
    costs = np.array([0.0, 1.0, 3.0, 6.0])
    out = normalize_move_costs(costs, normal, half, engaged=True)
    # L'origine (rester sur place = pas de Fall Back) reste a 0, non peinte.
    assert float(out[0]) == pytest.approx(0.0, abs=1e-6)
    # Toute cellule de cout > 0 est au-dessus du seuil, monotone, < 1 (bornee par M < H).
    assert all(float(v) > MOVE_COST_ADVANCE_THRESHOLD for v in out[1:])
    assert all(float(b) > float(a) for a, b in zip(out[1:], out[2:]))
    assert float(out[-1]) < 1.0
    # Contre-epreuve : la meme escouade NON engagee garde ces couts sous le seuil.
    free = normalize_move_costs(costs, normal, half, engaged=False)
    assert all(float(v) <= MOVE_COST_ADVANCE_THRESHOLD for v in free)


def test_normalize_move_costs_absorbs_the_float_epsilon_at_the_exact_budget():
    """REGRESSION : une destination PILE au budget ressort a `H + 5e-15` du BFS.

    Les couts sont des sommes de pas de `2/sqrt(3)` : `12.000000000000005` pour un budget de 12.
    Une borne stricte levait la — sur le vrai board, donc en plein training. La tolerance ne
    masque rien : elle vaut 1e-6, quand une vraie incoherence pool/grille vaudrait au moins un
    pas hex (~1,15). Trouve par `test_spatial_move_decode_execute`, invisible en float32.
    """
    import numpy as np

    from engine.spatial_grid import normalize_move_costs

    out = normalize_move_costs(np.array([12.000000000000005]), 6, 12, engaged=False)
    assert float(out[0]) == pytest.approx(1.0, abs=1e-6)
    out = normalize_move_costs(np.array([-1e-15]), 6, 12, engaged=False)
    assert float(out[0]) == pytest.approx(0.0, abs=1e-6)


def test_normalize_move_costs_raises_instead_of_clipping():
    """Aucun repli : un cout hors bornes ou un budget incoherent LEVE."""
    import numpy as np

    from engine.spatial_grid import normalize_move_costs

    with pytest.raises(ValueError, match="cout hors de"):
        normalize_move_costs(np.array([61.0]), 30, 60, engaged=False)
    with pytest.raises(ValueError, match="cout hors de"):
        normalize_move_costs(np.array([60.001]), 30, 60, engaged=False)  # au-dela de la tolerance d'arrondi
    with pytest.raises(ValueError, match="cout hors de"):
        normalize_move_costs(np.array([-1.0]), 30, 60, engaged=False)
    with pytest.raises(ValueError, match="budget normal"):
        normalize_move_costs(np.array([10.0]), 60, 60, engaged=False)
    with pytest.raises(ValueError, match="demi-etendue invalide"):
        normalize_move_costs(np.array([0.0]), 0, 0, engaged=False)
