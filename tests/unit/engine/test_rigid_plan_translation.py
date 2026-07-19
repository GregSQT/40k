"""V11 T6-h — `build_rigid_plan` doit être une translation RIGIDE à toutes les parités de dx.

Rupture corrigée (2026-07-19) : la translation était appliquée en coordonnées OFFSET
(`col + dx`, `row + dy`). En grille hexagonale odd-q, un `dx` impair change la parité de
colonne de chaque figurine : ce n'est PAS une translation hexagonale et le bloc se déforme
(mesuré : deux figurines à distance interne 2 se retrouvaient à distance 1).

Conséquences : cohésion et collisions intra-plan faussées, distances per-model non uniformes,
et invalidation de toute optimisation supposant des offsets de bloc constants (dont l'érosion
morphologique du pool de move, T6-g).

Le fix translate en coordonnées CUBE, miroir de
`deployment_build_squad_destinations_pool` (deployment_handlers).
"""

import pytest

from engine.hex_utils import hex_distance
from engine.phase_handlers.shared_utils import build_rigid_plan


def _game_state(positions):
    """game_state minimal : uniquement ce que `build_rigid_plan` lit."""
    models_cache = {
        mid: {"col": col, "row": row, "squad_id": "1", "player": 1}
        for mid, (col, row) in positions.items()
    }
    return {
        "models_cache": models_cache,
        "squad_models": {"1": list(positions.keys())},
    }


# Bloc de 4 figurines, colonnes paires ET impaires, distances internes variées.
BLOCK = {
    "1#0": (10, 10),
    "1#1": (12, 10),
    "1#2": (11, 12),
    "1#3": (13, 11),
}


@pytest.mark.parametrize("dest", [
    (10, 10),   # dx = 0
    (12, 10),   # dx pair
    (11, 10),   # dx impair  <-- rouge avant le fix
    (13, 14),   # dx impair + dy
    (7, 8),     # dx impair négatif
    (4, 10),    # dx pair négatif
])
def test_rigid_plan_preserves_internal_distances(dest):
    """Toutes les distances internes du bloc sont préservées par la translation."""
    gs = _game_state(BLOCK)
    plan = build_rigid_plan(dest[0], dest[1], "1", gs)
    assert plan is not None
    new_pos = {mid: (col, row) for mid, col, row in plan}
    assert set(new_pos) == set(BLOCK)

    mids = sorted(BLOCK)
    for i, a in enumerate(mids):
        for b in mids[i + 1:]:
            before = hex_distance(*BLOCK[a], *BLOCK[b])
            after = hex_distance(*new_pos[a], *new_pos[b])
            assert after == before, (
                f"translation vers {dest} : distance {a}-{b} passée de {before} à {after} — "
                f"le bloc se déforme (bug de parité hex, V11 T6-h)"
            )


@pytest.mark.parametrize("dest", [(11, 10), (13, 14), (7, 8), (12, 10)])
def test_rigid_plan_anchor_lands_on_destination(dest):
    """L'ancre (figurine d'index minimal) atterrit EXACTEMENT sur la destination demandée."""
    gs = _game_state(BLOCK)
    plan = build_rigid_plan(dest[0], dest[1], "1", gs)
    assert plan is not None
    anchor_mid, anchor_col, anchor_row = plan[0]
    assert anchor_mid == "1#0"
    assert (anchor_col, anchor_row) == dest
