"""Plan rigide et formation SUPERPOSÉE sur deux étages — le cas créé par le PILE-IN (12.03).

Deux figurines d'une même escouade peuvent occuper la même case sur deux étages : le pile-in
par-figurine filtre les collisions PAR ÉTAGE (`_fight_fig_effective_level`, superposition
inter-étage §13.06), donc il pose légalement une figurine au SOL sous une sœur restée à l'ÉTAGE.
Le move d'escouade suivant est RIGIDE (`build_rigid_plan`) : tant qu'il aplatissait toute la
formation au niveau 0, la paire retombait sur la même (case, niveau) sur TOUTE destination, et
le masque — qui supposait la collision intra-plan invariante par translation — l'offrait quand
même : `ValueError: execute_squad_move a échoué … collision intra-plan` (gate de P1, 2026-09-17,
le même état créé là par un socle rendu REVIVED).

Verrou : le pile-in OFFRE bien la case sous la sœur (l'état n'est pas hypothétique), et après
l'avoir committé, le masque de move rigide est non vide et chaque cellule offerte est exécutable,
la sœur gardant son étage là où il continue (`model_rigid_level_map`).

Géométrie x10 (métrique EUCLIDIENNE) : c'est la branche any-angle de l'érosion qui est éprouvée
ici, la branche hex l'étant par `test_squad_move_descent_frontier.py::_gs_stacked`.
"""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.fight_handlers import (
    _fight_pile_in_build_model_pool, _fight_pile_in_commit_plan,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes, build_rigid_plan, build_squad_move_cell_map,
    explain_move_plan_rejection, infer_squad_move_type, resolve_squad_move_constraints,
)
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

ISH = 10
FLOOR_HEIGHT_INCHES = 3.0
_ETAGE_COLS = range(110, 121)
_ETAGE_ROWS = range(90, 111)
_ETAGE_HEXES = [[c, r] for c in _ETAGE_COLS for r in _ETAGE_ROWS]
_C0, _C1 = _ETAGE_COLS.start, _ETAGE_COLS.stop - 1
_R0, _R1 = _ETAGE_ROWS.start, _ETAGE_ROWS.stop - 1
_ETAGE_POLY = [[_C0, _R0], [_C1, _R0], [_C1, _R1], [_C0, _R1]]

#: Figurine au sol, à 1,5" du couloir ; sa sœur à l'ÉTAGE au cœur du plancher ; l'ennemi de
#: l'autre côté, pour que traverser rapproche (12.03 : chaque figurine finit plus près).
GROUND_START = (100, 100)
UPPER = (115, 100)
ENEMY = (140, 100)


def _state() -> Dict[str, Any]:
    unit_kw = {
        "UNIT_KEYWORDS": [{"keywordId": "infantry"}],
        "MODEL_HEIGHT": 2.0,
        # 6" : la descente (3") laisse 3" de budget au move rigide ; à 3" le régime serait
        # impossible (pool vide par construction, `movement_build_valid_destinations_pool`).
        "MOVE": 6 * ISH,
    }
    state = synthetic_state(
        [
            synthetic_unit("S", 1, [
                {"col": GROUND_START[0], "row": GROUND_START[1], "level": 0},
                {"col": UPPER[0], "row": UPPER[1], "level": 1},
            ], **unit_kw),
            synthetic_unit("E", 2, [{"col": ENEMY[0], "row": ENEMY[1]}], **unit_kw),
        ],
        inches_to_subhex=ISH,
        board_cols=200, board_rows=200,
        terrain_areas=[{
            "id": "ruine",
            "polygon_vertices": _ETAGE_POLY,
            "hexes": _ETAGE_HEXES,
            "floors": [{
                "level": 1, "height_inches": FLOOR_HEIGHT_INCHES,
                "hexes": _ETAGE_HEXES, "polygon_vertices": _ETAGE_POLY,
            }],
        }],
        game_rules={"engagement_zone": 2 * ISH, "unit_model_cohesion_range": 20 * ISH},
        phase="fight",
        units_took_to_skies=set(),
    )
    build_enemy_adjacent_hexes(state, 1)
    return state


def test_pile_in_offers_the_cell_under_the_sister_on_the_floor_then_the_squad_can_still_move():
    gs = _state()
    assert int(gs["models_cache"]["S#1"]["level"]) == 1, "la sœur n'est pas à l'étage"

    # 1. Le pile-in OFFRE la case sous la sœur : superposition inter-étage légale (13.06).
    pool = _fight_pile_in_build_model_pool(gs, "S#0", ["E"], None, view_level=0)["closer"]
    under_sister = [d for d in pool if (int(d[0]), int(d[1])) == UPPER]
    assert under_sister, "le pool de pile-in n'offre pas la case sous la sœur : rien à créer"
    assert all((int(d[2]) if len(d) > 2 else 0) == 0 for d in under_sister)

    # 2. Commit par le chemin réel du pile-in.
    _fight_pile_in_commit_plan(gs, gs["unit_by_id"]["S"], [("S#0", UPPER[0], UPPER[1], 0)])
    s0, s1 = gs["models_cache"]["S#0"], gs["models_cache"]["S#1"]
    assert (int(s0["col"]), int(s0["row"]), int(s0["level"])) == (UPPER[0], UPPER[1], 0)
    assert (int(s1["col"]), int(s1["row"]), int(s1["level"])) == (UPPER[0], UPPER[1], 1)

    # 3. Move rigide suivant : masque non vide, chaque cellule exécutable, paire sur deux étages.
    gs["phase"] = "move"
    gs["current_player"] = 1
    build_enemy_adjacent_hexes(gs, 1)
    cell_map = build_squad_move_cell_map(gs, "S", None)
    assert cell_map, "masque vide : la paire superposée est clouée au sol"
    floor_cells = {(c, r) for c, r in _ETAGE_HEXES}
    for (cell, cost) in cell_map.values():
        plan = build_rigid_plan(cell[0], cell[1], "S", gs)
        assert plan is not None
        by_mid = {entry[0]: entry for entry in plan}
        assert by_mid["S#1"][3] == 1 and by_mid["S#0"][3] == 0, (cell, plan)
        assert (by_mid["S#1"][1], by_mid["S#1"][2]) in floor_cells
        move_type = infer_squad_move_type(gs, "S", cost)
        constraints = resolve_squad_move_constraints("S", gs, move_type, None)
        reason = explain_move_plan_rejection(plan, gs, constraints)
        assert reason is None, (cell, reason)
