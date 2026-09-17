"""Pool par-figurine (PvP, `movement_build_model_destinations_pool`) en métrique HEX — 13.06.

Le bloc multi-niveaux du pool par-figurine ne s'appliquait qu'en métrique euclidienne (garde
`_mm_use_euclidean and not has_fly`). En métrique hex (x1), le BFS planaire taguait « étage »
toute case dont l'empreinte tenait sur le plancher, sans mot-clé 13.06 ni coût vertical, et la
validation (`model_reach_predicate` → `ascent_field_for_model`) refusait ensuite ces cases :
masque ⊄ exécutable. Mesuré sur la checklist PvP x1 : 23 cases d'étage offertes à un Intercessor
avec M − 3" = 3, 24 cases offertes à un Dreadnought (VEHICLE).

Scène partagée avec ``test_ascent_field_hex_ground.py`` : x5 sous ``gym_distance_metric: hex``
— la branche du pool est choisie par la MÉTRIQUE, pas par la résolution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers import shared_utils as su
from tests.unit.engine.test_ascent_field_hex_ground import _BUDGET, _FLOOR_HEXES, _START, _make_gs, _unit
from tests.unit.engine.test_ascent_field_reuses_euclidean_field import _model


def _pool(gs: Dict[str, Any], level: int) -> List[Tuple[int, int, int]]:
    out = mh.movement_build_model_destinations_pool(gs, "1#0", level=level)
    return [(int(c), int(r), int(lv)) for c, r, lv in out["destinations"]]


#: Budget SERRÉ : le plancher commence à 6 colonnes et la montée coûte 5 sous-hexes — à 16, le
#: BFS planaire atteint des cases d'étage (distance ≤ 16) que la montée facturée refuse
#: (distance + 5 > 16). À 30, tout l'étage tient dans les deux comptes et le test ne verrait rien.
_TIGHT_BUDGET = 16


def _infantry_gs(move: int = _BUDGET) -> Dict[str, Any]:
    return _make_gs([_unit("1", 1, [_START], move=move), _unit("2", 2, [(23, 40)])])


def test_en_hex_les_cases_d_etage_du_pool_sont_celles_que_la_validation_accepte():
    gs = _infantry_gs(move=_TIGHT_BUDGET)
    assert mh._move_distance_metric(gs) == "hex", "prémisse : métrique hex"
    floor = [d for d in _pool(gs, 1) if d[2] == 1]
    assert floor, "aucune case d'étage offerte à l'INFANTRY"
    assert {(c, r) for c, r, _ in floor} <= set(_FLOOR_HEXES)
    # Masque ⊆ exécutable : CHAQUE case d'étage offerte passe le prédicat de la validation.
    predicate = su.model_reach_predicate(gs, "1", 1, _model(gs), _TIGHT_BUDGET, 1)
    refused = [(c, r) for c, r, _ in floor if not predicate(c, r)]
    assert refused == [], refused
    # Et le coût vertical est facturé : le fond de l'étage (au-delà de budget − montée) n'y est pas.
    climb = su.ascent_field_for_model(gs, "1", 1, _model(gs), 1, _TIGHT_BUDGET)
    assert {(c, r) for c, r, _ in floor} == {cell for cell, cost in climb.items() if cost <= _TIGHT_BUDGET}


def test_en_hex_le_sol_du_pool_reste_le_bfs_planaire_et_chaque_case_a_un_seul_niveau():
    """Le sol n'est pas touché par la branche : en vue étage, les cases au niveau 0 sont celles de
    la vue sol moins le plancher (praticable en surface en vue sol, à l'étage en vue 1) — et
    aucune case n'est offerte deux fois (bord d'étage : sol par le tag planaire, étage par la
    montée)."""
    gs = _infantry_gs()
    ground_view0 = {(c, r) for c, r, lv in _pool(gs, 0) if lv == 0}
    view1 = _pool(gs, 1)
    ground_view1 = {(c, r) for c, r, lv in view1 if lv == 0}
    assert ground_view1 and ground_view1 == ground_view0 - set(_FLOOR_HEXES)
    assert len(view1) == len({(c, r) for c, r, _ in view1}), "une case offerte à deux niveaux"


def test_en_hex_un_vehicle_ne_recoit_aucune_case_d_etage():
    """13.06 : sans INFANTRY/BEASTS/SWARM/FLY/MONSTER, aucune case d'étage — le commit les refuse."""
    from tests.unit.engine._state_builders import synthetic_unit

    vehicle = synthetic_unit(
        "1", 1, [{"col": _START[0], "row": _START[1], "orientation": 0}],
        BASE_SIZE=3, MOVE=_BUDGET, UNIT_KEYWORDS=[{"keywordId": "VEHICLE"}],
    )
    gs = _make_gs([vehicle, _unit("2", 2, [(23, 40)])])
    assert [d for d in _pool(gs, 1) if d[2] == 1] == []
    assert [d for d in _pool(gs, 0) if d[2] == 0], "le sol reste offert"
