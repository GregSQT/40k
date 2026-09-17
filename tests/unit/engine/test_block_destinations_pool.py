"""Sélection rectangle — pool d'un BLOC PARTIEL de figurines translaté rigidement (move + charge).

Le bloc suit le curseur comme le squad move rigide : il ne peut se poser que sur un pool d'ancres
calculé par le MOTEUR, jamais côté front. Ce fichier verrouille les deux propriétés qui font que ce
pool est « comme le squad mode » :

  1. INTERSECTION — une ancre n'est offerte que si CHAQUE figurine du bloc, translatée du même
     vecteur, tombe dans SON pool par-figurine (murs, budget géodésique depuis SON origine,
     conditions 11.04 par figurine en charge). Contre-épreuve : l'ancre est bien dans le pool de
     l'ancre seule — c'est la sœur qui la retire.
  2. SOULÈVEMENT — les figurines du bloc bougent ensemble : l'origine d'une sœur sélectionnée ne
     bloque pas la destination d'une autre (règle 03.01 : on traverse les figurines amies, et la
     sœur n'est plus là à l'arrivée). Contre-épreuve : sans soulèvement, le pool par-figurine
     refuse cette case.
  3. INVARIANT « masque ⊆ exécutable » — toute ancre offerte produit un plan que la validation
     d'exécution accepte figurine par figurine (``explain_move_plan_rejection`` /
     ``charge_preview_move_plan``). La cohésion reste jugée sur le plan complet à la pose (03.03 :
     fin de move), comme pour toute figurine posée une à une.

Règles : Documentation/40k_rules/03 Moving (03.01), 11 Charge phase (11.04).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.charge_handlers import (
    charge_block_destinations,
    charge_model_plan_state,
    charge_preview_move_plan,
)
from engine.phase_handlers.movement_handlers import (
    movement_build_block_destinations_pool,
    movement_build_model_destinations_pool,
)
from engine.phase_handlers.shared_utils import (
    build_enemy_adjacent_hexes,
    explain_move_plan_rejection,
)
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

Cell = Tuple[int, int]

#: Mur vertical entre l'escouade (colonnes 5..10) et la colonne 12 : la sœur S#2 en (10,10) ne
#: peut atteindre (12,10) qu'en le contournant (> 3 pas), alors que l'ancre S#0 va librement en (7,10).
WALL = {(11, r) for r in range(6, 15)}
S0, S1, S2 = (5, 10), (6, 10), (10, 10)
MOVE_BUDGET = 3


def _move_state() -> Dict[str, Any]:
    gs = synthetic_state(
        [
            synthetic_unit("S", 1, [{"col": c, "row": r} for c, r in (S0, S1, S2)], MOVE=MOVE_BUDGET),
            synthetic_unit("E", 2, [{"col": 30, "row": 30}]),
        ],
        phase="move",
        game_rules={},
        inches_to_subhex=1,
        board_cols=44,
        board_rows=60,
        wall_hexes=set(WALL),
    )
    build_enemy_adjacent_hexes(gs, 1)
    return gs


def _anchors(pool: List[Tuple[int, int, Dict[str, Tuple[int, int, int]]]]) -> Dict[Cell, Dict[str, Tuple[int, int, int]]]:
    return {(ac, ar): placements for ac, ar, placements in pool}


class TestMoveBlockPool:
    def test_une_ancre_legale_pour_l_ancre_seule_est_retiree_si_la_soeur_franchit_le_mur(self):
        gs = _move_state()
        solo = {(int(c), int(r)) for c, r, _ in movement_build_model_destinations_pool(gs, "S#0")["destinations"]}
        assert (7, 10) in solo, "prémisse : (7,10) est dans le pool de S#0 seule"

        block = _anchors(movement_build_block_destinations_pool(gs, ["S#0", "S#2"]))
        assert block, "le bloc doit garder des ancres (translation d'une case vers le bas, etc.)"
        assert (7, 10) not in block, "S#2 translatée en (12,10) contourne le mur : > budget"
        # Contre-épreuve positive : une ancre où la sœur reste de son côté du mur est offerte, avec
        # la destination de CHAQUE figurine (niveau inclus).
        assert (5, 11) in block
        assert block[(5, 11)] == {"S#0": (5, 11, 0), "S#2": (10, 11, 0)}

    def test_une_soeur_selectionnee_ne_bloque_plus_la_destination_de_l_autre(self):
        gs = _move_state()
        solo = {(int(c), int(r)) for c, r, _ in movement_build_model_destinations_pool(gs, "S#0")["destinations"]}
        assert S1 not in solo, "prémisse : S#1 à l'origine bloque (6,10) pour S#0 seule"

        block = _anchors(movement_build_block_destinations_pool(gs, ["S#0", "S#1"]))
        # Translation CUBE (5,10)→(6,10) appliquée à (6,10) : (7,9) en odd-q (parité de colonne).
        assert S1 in block, "S#1 est soulevée : S#0 peut prendre son origine, S#1 glisse en (7,9)"
        assert block[S1] == {"S#0": (6, 10, 0), "S#1": (7, 9, 0)}

    def test_toute_ancre_du_bloc_passe_la_validation_d_execution(self):
        gs = _move_state()
        pool = movement_build_block_destinations_pool(gs, ["S#0", "S#2"])
        assert pool, "vert vacant : aucun pool à valider"
        for ac, ar, placements in pool:
            plan = [(mid, c, r, lv) for mid, (c, r, lv) in placements.items()]
            plan.append(("S#1", S1[0], S1[1], 0))  # sœur non sélectionnée, à l'origine
            reason = explain_move_plan_rejection(plan, gs, {"require_coherency": False})
            assert reason is None, f"ancre ({ac},{ar}) offerte mais refusée : {reason}"

    def test_les_positions_provisoires_du_bloc_sont_ignorees_et_celles_des_autres_gardees(self):
        """S#1 déjà posée en (7,11) dans le plan = obstacle ; S#0 déjà posée ailleurs repart de l'origine."""
        gs = _move_state()
        prov = {"S#1": (7, 11, 0), "S#0": (5, 12, 0)}
        block = _anchors(movement_build_block_destinations_pool(gs, ["S#0", "S#2"], provisional_plan=prov))
        assert block
        assert all(p["S#0"][:2] != (7, 11) for p in block.values()), "la sœur posée reste un obstacle"
        # Le budget se compte depuis l'ORIGINE (5,10), pas depuis la pose provisoire (5,12).
        assert (5, 11) in block
        assert all(abs(p["S#0"][1] - 10) <= 4 for p in block.values())


#: Charge : deux figurines, une cible à 4 cases → jet 6 suffit, phase 11.04 « ≤1" » réalisable.
C0, C1 = (5, 10), (5, 11)
ENEMY = (9, 10)


def _charge_state() -> Dict[str, Any]:
    return synthetic_state(
        [
            synthetic_unit("S", 1, [{"col": c, "row": r} for c, r in (C0, C1)]),
            synthetic_unit("E", 2, [{"col": ENEMY[0], "row": ENEMY[1]}]),
        ],
        phase="charge",
        game_rules={},
        inches_to_subhex=1,
        board_cols=44,
        board_rows=60,
        charge_target_selections={"S": ["E"]},
        charge_roll_values={"S": 6},
        _unit_move_version=0,
    )


class TestChargeBlockPool:
    def test_toute_ancre_du_bloc_passe_la_validation_par_figurine(self):
        gs = _charge_state()
        state = charge_model_plan_state(gs, "S", {})
        assert set(state["eligible_models"]) == {"S#0", "S#1"}, "prémisse : les deux figs sont éligibles"
        pool = charge_block_destinations(gs, "S", ["S#0", "S#1"], {})
        assert pool, "vert vacant : aucune ancre de charge"
        for ac, ar, placements in pool:
            plan = [(mid, c, r, lv) for mid, (c, r, lv) in placements.items()]
            prev = charge_preview_move_plan(gs, "S", plan, ["E"])
            assert all(prev["per_model"].values()), f"ancre ({ac},{ar}) offerte mais refusée : {prev}"

    def test_l_intersection_retire_les_ancres_ou_la_soeur_ne_qualifie_pas(self):
        gs = _charge_state()
        solo = {(int(c), int(r)) for c, r, _ in charge_model_plan_state(gs, "S", {}, selected_model="S#0")["pool"]}
        block = _anchors(charge_block_destinations(gs, "S", ["S#0", "S#1"], {}))
        assert set(block) < solo, "le pool du bloc est un sous-ensemble STRICT du pool de l'ancre seule"
        # Contre-épreuve du soulèvement : S#0 peut prendre l'origine de S#1 (5,11) si S#1 qualifie plus bas.
        for placements in block.values():
            assert placements["S#0"][:2] != placements["S#1"][:2]

    def test_figurine_deja_posee_donc_non_eligible_refusee_explicitement(self):
        gs = _charge_state()
        with pytest.raises(ValueError, match="non éligibles"):
            charge_block_destinations(gs, "S", ["S#1"], {"S#1": (6, 10, 0)})


class TestBlockFootprintMaskLoops:
    """Zone d'atterrissage du bloc (contours monde) — ce que le squad move rigide affiche aussi."""

    def test_move_loops_cover_every_destination_of_every_model(self):
        from engine.phase_handlers.movement_handlers import movement_block_footprint_mask_loops
        from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world

        gs = _move_state()
        anchors = movement_build_block_destinations_pool(gs, ["S#0", "S#2"])
        loops = movement_block_footprint_mask_loops(gs, anchors)
        assert loops and all(len(loop) >= 3 for loop in loops)
        # Socles mono-hex : la zone est exactement l'union des destinations des deux figurines.
        cells = {(c, r) for _a, _b, pl in anchors for (c, r, _lv) in pl.values()}
        expected = compute_move_preview_mask_loops_world(cells, gs)
        assert expected is not None
        assert loops == [[(float(x), float(y)) for (x, y) in loop] for loop in expected]
        assert movement_block_footprint_mask_loops(gs, []) == []

    def test_charge_loops_non_empty_for_a_non_empty_block_pool(self):
        from engine.phase_handlers.charge_handlers import charge_block_footprint_mask_loops

        gs = _charge_state()
        anchors = charge_block_destinations(gs, "S", ["S#0", "S#1"], {})
        assert anchors, "vert vacant : aucune ancre"
        loops = charge_block_footprint_mask_loops(gs, "S", anchors, {})
        assert loops and all(len(loop) >= 3 for loop in loops)
        assert charge_block_footprint_mask_loops(gs, "S", [], {}) == []
