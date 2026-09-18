"""Consolidation GYM 12.08 — sélection engaging RÉELLE (A3) et objective « closer if not » (A4).

Miroir de ``test_consolidation_if_possible_par_figurine.py`` (chemin PvP). Le plan gym
(``squad_consolidate_plan_with_targets``) :

  - Engaging (12.08 AFTER MOVING « Your unit must be engaged with all of the selected enemy
    units ») : la sélection est le sous-ensemble des ennemis à 3" que le plan engage réellement,
    par point fixe ; aucun engagé = pas de consolidation. Avant A3, TOUS les ennemis à 3" étaient
    « sélectionnés » et le plan validé dès qu'UNE figurine en engageait un — la sélection annoncée
    (log, New Foes) n'était pas celle que le plan honorait.
  - Objective (12.08 WHILE MOVING « within range of the selected objective if possible, or closer
    to it if not ») : une figurine qui ne peut pas atteindre la zone finit STRICTEMENT plus près
    d'elle dans son budget. Avant A4, elle restait sur place.

Géométrie RÉELLE (EZ 2, cohésion 2, trigger 3", ``inches_to_subhex`` = 1), plateau 44×60.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.shared_utils import (
    squad_consolidate_plan,
    squad_consolidate_plan_with_targets,
)
from tests.unit.engine._state_builders import Cell, fight_squad_vs_enemies_state


def _gs(squad: Sequence[Cell], enemies: Sequence[Cell]) -> Dict[str, Any]:
    return fight_squad_vs_enemies_state(squad, enemies)


def _cell(plan: List, mid: str) -> Cell:
    return next((c, r) for m, c, r, _lv in plan if m == mid)


def _d(a: Cell, b: Cell) -> int:
    return calculate_hex_distance(a[0], a[1], b[0], b[1])


# ── Engaging : sélection = ce que le plan engage ────────────────────────────


def test_engaging_selection_keeps_only_the_enemy_the_plan_engages():
    """S (mono-figurine) à 3 cases de E1 et E2 placés à l'opposé l'un de l'autre : un seul est
    atteignable en 3" — la sélection rendue ne contient QUE celui-là.

    ROUGE avant A3 : la sélection valait ["2", "3"] (tous les ennemis à 3") alors que le plan
    n'en engageait qu'un.
    """
    squad: List[Cell] = [(10, 10)]
    e1: Cell = (10, 13)
    e2: Cell = (10, 7)
    assert _d(squad[0], e1) == 3 and _d(squad[0], e2) == 3
    gs = _gs(squad, [e1, e2])

    plan, targets = squad_consolidate_plan_with_targets(gs, "1")

    assert plan is not None
    dest = _cell(plan, "1#0")
    engaged_with = [tid for tid, pos in (("2", e1), ("3", e2)) if _d(dest, pos) <= 2]
    assert len(engaged_with) == 1, f"géométrie : une seule des deux est engageable, obtenu {dest}"
    assert targets == engaged_with, (targets, engaged_with)


def test_engaging_selection_keeps_both_when_the_plan_engages_both():
    """Deux ennemis du même côté, tous deux engagés par le plan → les deux sont sélectionnés."""
    squad: List[Cell] = [(10, 10)]
    e1: Cell = (10, 13)
    e2: Cell = (11, 12)
    assert _d(squad[0], e1) == 3 and _d(squad[0], e2) == 3 and _d(e1, e2) == 1
    gs = _gs(squad, [e1, e2])

    plan, targets = squad_consolidate_plan_with_targets(gs, "1")

    assert plan is not None
    dest = _cell(plan, "1#0")
    assert _d(dest, e1) <= 2 and _d(dest, e2) <= 2, dest
    assert sorted(targets) == ["2", "3"]


def test_engaging_without_any_reachable_engagement_is_no_consolidation():
    """Ennemi à 3" derrière un mur qui impose un détour : personne ne finit engagé → (None, [])."""
    squad: List[Cell] = [(10, 10)]
    e1: Cell = (10, 13)
    gs = _gs(squad, [e1])
    # Anneau de murs autour de E, sauf la case de E : aucune case engagée (≤ 2) n'est atteignable.
    gs["wall_hexes"] = {
        (c, r) for c in range(6, 15) for r in range(9, 18)
        if 1 <= _d((c, r), e1) <= 2
    }

    assert squad_consolidate_plan_with_targets(gs, "1") == (None, [])
    assert squad_consolidate_plan(gs, "1") is None


# ── Objective : « closer to it if not » ──────────────────────────────────────


def test_objective_model_that_cannot_reach_the_zone_ends_closer():
    """S#0 à 1 case de la zone (l'atteint et satisfait l'AFTER), S#1 à 5 cases avec un budget
    de 3 : S#1 finit à 2 cases de la zone, pas sur place.

    ROUGE avant A4 : S#1 restait à 5 cases (`chosen_obj[mid] = (oc, or_)`).
    """
    zone = {(10, 11), (10, 12), (10, 13)}
    near: Cell = (10, 10)
    far: Cell = (10, 6)
    gs = _gs([near, far], [])
    gs["objectives"] = [{"id": "O1", "hexes": [list(h) for h in sorted(zone)]}]

    def zone_dist(cell: Cell) -> int:
        return min(_d(cell, h) for h in zone)

    assert zone_dist(near) == 1 and zone_dist(far) == 5

    plan, targets = squad_consolidate_plan_with_targets(gs, "1")

    assert plan is not None and targets == []
    assert _cell(plan, "1#0") in zone, "12.08 AFTER : au moins une figurine dans la zone"
    dest_far = _cell(plan, "1#1")
    assert zone_dist(dest_far) == 2, (
        f"« or closer to it if not » : attendu à 2 de la zone (budget 3 depuis 5), obtenu "
        f"{dest_far} à {zone_dist(dest_far)}"
    )
