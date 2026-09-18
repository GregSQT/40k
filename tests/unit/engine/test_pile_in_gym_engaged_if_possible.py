"""Pile-in GYM 12.03 WHILE MOVING : « each model that is moved must end its move closer to the
closest pile-in target, **and engaged with it if possible** » — trois paliers (A1).

Miroir de ``test_pile_in_engaged_if_possible.py``, qui ne couvre que le chemin PvP
(``_fight_pile_in_preview_plan``). Le plan gym (``fight_pile_in_plan`` →
``_assign_cells_toward_enemies``) ne cherchait l'engagement qu'au CONTACT (couplage sur les
voisins des ennemis) puis, à défaut, sortait au premier anneau qui rapprochait : une figurine
dont les cases de contact étaient prises par ses camarades avançait d'UNE case et finissait à
3 cases, hors engagement, alors qu'une case engagée à 2 cases était libre et atteignable.
Mesuré bot contre bot (40 parties, moteur 5b2422dd5) : 100 figurines sur 762 hors engagement
après pile-in.

Géométrie RÉELLE (EZ 2, cohésion 2, ``inches_to_subhex`` = 1), plateau 44×60, ennemi E mono-figurine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from engine.combat_utils import calculate_hex_distance, get_hex_neighbors
from engine.phase_handlers.shared_utils import fight_pile_in_plan, get_fighting_models
from tests.unit.engine._state_builders import Cell, fight_squad_vs_enemies_state

ENEMY: Cell = (10, 10)


def _gs(squad: Sequence[Cell], enemies: Sequence[Cell]) -> Dict[str, Any]:
    return fight_squad_vs_enemies_state(squad, enemies, fight_subphase="pile_in")


def _dist_to_enemy(cell: Cell) -> int:
    return calculate_hex_distance(cell[0], cell[1], ENEMY[0], ENEMY[1])


def _plan_cells(plan: List, mid: str) -> Cell:
    return next((c, r) for m, c, r, _lv in plan if m == mid)


def test_contact_cells_taken_by_comrades_model_still_ends_engaged():
    """Palier 2 : les six cases de contact sont occupées par des camarades (immobiles, 12.03) ;
    la septième figurine, à 4 cases, finit à 2 cases — ENGAGÉE — et non à 3.

    ROUGE avant A1 : elle finissait à (10,7), distance 3, hors zone d'engagement.
    """
    contact_ring = [tuple(c) for c in get_hex_neighbors(*ENEMY)]
    assert len(contact_ring) == 6 and all(_dist_to_enemy(c) == 1 for c in contact_ring)
    far: Cell = (10, 6)
    assert _dist_to_enemy(far) == 4
    gs = _gs([*contact_ring, far], [ENEMY])
    far_mid = "1#6"
    assert (gs["models_cache"][far_mid]["col"], gs["models_cache"][far_mid]["row"]) == far

    plan = fight_pile_in_plan(gs, "1")

    assert plan is not None, "un pile-in est possible : la figurine du fond peut se rapprocher"
    for i, cell in enumerate(contact_ring):
        assert _plan_cells(plan, f"1#{i}") == cell, "12.03 : au contact, on ne bouge pas"
    dest = _plan_cells(plan, far_mid)
    assert _dist_to_enemy(dest) == 2, (
        f"12.03 « engaged with it if possible » : attendu une case à 2 (EZ), obtenu {dest} "
        f"à {_dist_to_enemy(dest)}"
    )


def test_engaged_cell_out_of_reach_model_goes_as_close_as_the_budget_allows():
    """Palier 3 : aucune case engagée atteignable en 3" → la figurine finit à la case la plus
    proche de la cible dans TOUT le budget, pas au premier anneau qui rapproche.

    S#0 au contact (immobile, il rend E cible 12.03) ; S#1 à 6 cases : le mieux atteignable est
    la distance 3. ROUGE avant A1 : S#1 s'arrêtait à 5 (anneau 1).
    """
    contact: Cell = (10, 9)
    far: Cell = (10, 4)
    assert _dist_to_enemy(contact) == 1 and _dist_to_enemy(far) == 6
    gs = _gs([contact, far], [ENEMY])
    assert get_fighting_models(gs, "1", "2") == ["1#0"], "précondition : S#0 seul engagé"

    plan = fight_pile_in_plan(gs, "1")

    assert plan is not None
    assert _plan_cells(plan, "1#0") == contact, "12.03 : au contact, on ne bouge pas"
    dest = _plan_cells(plan, "1#1")
    assert _dist_to_enemy(dest) == 3, f"tout le budget doit être utilisé : obtenu {dest}"
