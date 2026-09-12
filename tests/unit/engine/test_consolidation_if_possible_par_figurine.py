"""Consolidation 12.08 WHILE MOVING, clause « if possible », PAR FIGURINE et PAR MODE :

  - Ongoing / Engaging : « each model that is moved must end its move closer to the closest
    selected enemy unit, **and engaged with it if possible** » ;
  - Objective : « each model that is moved must end its move **within range of the selected
    objective if possible**, or closer to it if not ».

``_fight_consolidation_preview_plan`` (``per_model``) ne jugeait que « closer » : la clé
``engaged`` de ``_fight_consolidation_build_model_pool`` (≤ EZ du palier ; pour l'Objective,
empreinte dans la zone) n'avait aucun consommateur. Même définition de « possible » que le pile-in
(``test_pile_in_engaged_if_possible.py``) : cohésion 03.03 de la configuration finale + engagements
de départ de la figurine ; source unique ``_fight_model_legal_destinations``.

JUMEAU du fichier pile-in : deux preview_plan, un seul helper — couvrir les trois modes ici est
délibéré, c'est la moitié qu'une correction du pile-in laisse tomber.

Géométries MESURÉES (règles réelles : EZ = 2, cohésion 2, ``inches_to_subhex`` = 1) :
  - Ongoing   : S#0 (10,6), S#1 (10,9) en base-contact de E (10,10) → unité engagée. Engagées de
                S#0 = (9,8) (10,8) (11,8) ; (10,7) seulement « closer ».
  - Engaging  : S#0 (10,6), S#1 (10,7), E (10,10) à 3 → unité non engagée. Plan S#1 → (10,8) ;
                engagées de S#0 (S#1 en (10,8)) = (9,8) (10,9) (11,8) ; (10,7) seulement « closer ».
  - Objective : S#0 (10,7), S#1 (10,6), zone = rayon 1 autour de (10,10), aucun ennemi à portée.
                Plan S#1 → (10,9) ; within-range de S#0 = (9,9) (10,10) (11,9) ; (10,8) seulement
                « closer ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.fight_handlers import (
    _fight_consolidation_build_model_pool,
    _fight_consolidation_model_plan_state,
    _fight_consolidation_preview_plan,
)
from tests.unit.engine._state_builders import (
    Cell,
    fight_squad_vs_enemies_state as _gs,
    ground_plan as _plan,
)
ENEMY: Cell = (10, 10)
FAR_ENEMY: Cell = (30, 30)
OBJECTIVE_CENTER: Cell = (10, 10)


def _zone() -> Set[Cell]:
    return {
        (c, r) for c in range(5, 16) for r in range(5, 16)
        if calculate_hex_distance(c, r, *OBJECTIVE_CENTER) <= 1
    }


def _preview_enemy(gs: Dict[str, Any], plan, *, mode: str) -> Dict[str, Any]:
    return _fight_consolidation_preview_plan(
        gs, "1", plan, mode=mode, tier_kind="enemy", tier=["2"],
        closest_tier_ids=["2"], lock_base_contact=(mode == "ongoing"),
    )


def _preview_objective(gs: Dict[str, Any], plan) -> Dict[str, Any]:
    return _fight_consolidation_preview_plan(
        gs, "1", plan, mode="objective", tier_kind="zone", tier=_zone(),
        closest_tier_ids=[], lock_base_contact=False,
    )


# --- Ongoing -------------------------------------------------------------------------------------
ONGOING_SQUAD: List[Cell] = [(10, 6), (10, 9)]


def test_ongoing_a_model_that_could_engage_may_not_stop_short():
    gs = _gs(ONGOING_SQUAD, [ENEMY])
    pool = _fight_consolidation_build_model_pool(
        gs, "1#0", tier_kind="enemy", tier=["2"], lock_base_contact=True,
        provisional_plan={"1#1": (10, 9, 0)},
    )
    assert sorted(map(tuple, pool["engaged"])) == [(9, 8), (10, 8), (11, 8)], "précondition"
    out = _preview_enemy(gs, _plan(("1#0", (10, 7)), ("1#1", (10, 9))), mode="ongoing")
    assert out["coherency_ok"] and out["kept_engagements"], "précondition : seul le WHILE refuse"
    assert out["per_model"]["1#0"] is False
    assert out["can_validate"] is False


def test_ongoing_ending_engaged_is_accepted():
    out = _preview_enemy(
        _gs(ONGOING_SQUAD, [ENEMY]), _plan(("1#0", (10, 8)), ("1#1", (10, 9))), mode="ongoing"
    )
    assert out["per_model"] == {"1#0": True, "1#1": True}
    assert out["can_validate"] is True


def test_ongoing_plan_state_pool_only_lists_legal_destinations():
    """Cascade réelle (unité engagée → Ongoing) : le pool exposé pour S#0 = ses 3 cases engagées."""
    gs = _gs(ONGOING_SQUAD, [ENEMY])
    st = _fight_consolidation_model_plan_state(gs, gs["unit_by_id"]["1"], selected_model="1#0")
    assert st["consolidation_mode"] == "ongoing"
    assert sorted(map(tuple, st["pool"])) == [(9, 8), (10, 8), (11, 8)]
    assert st["eligible_models"] == ["1#0"]  # S#1 en base-contact : verrouillée (12.08 WHILE)


# --- Engaging ------------------------------------------------------------------------------------
ENGAGING_SQUAD: List[Cell] = [(10, 6), (10, 7)]


def test_engaging_a_model_that_could_engage_may_not_stop_short():
    gs = _gs(ENGAGING_SQUAD, [ENEMY])
    pool = _fight_consolidation_build_model_pool(
        gs, "1#0", tier_kind="enemy", tier=["2"], lock_base_contact=False,
        provisional_plan={"1#1": (10, 8, 0)},
    )
    assert sorted(map(tuple, pool["engaged"])) == [(9, 8), (10, 9), (11, 8)], "précondition"
    out = _preview_enemy(gs, _plan(("1#0", (10, 7)), ("1#1", (10, 8))), mode="engaging")
    assert out["coherency_ok"] and out["engaged_with_all_selected"], "précondition : seul le WHILE refuse"
    assert out["per_model"]["1#0"] is False
    assert out["can_validate"] is False


def test_engaging_ending_engaged_is_accepted():
    out = _preview_enemy(
        _gs(ENGAGING_SQUAD, [ENEMY]), _plan(("1#0", (9, 8)), ("1#1", (10, 8))), mode="engaging"
    )
    assert out["per_model"] == {"1#0": True, "1#1": True}
    assert out["can_validate"] is True


# --- Objective -----------------------------------------------------------------------------------
OBJECTIVE_SQUAD: List[Cell] = [(10, 7), (10, 6)]


def test_objective_a_model_that_could_be_within_range_may_not_only_get_closer():
    gs = _gs(OBJECTIVE_SQUAD, [FAR_ENEMY])
    pool = _fight_consolidation_build_model_pool(
        gs, "1#0", tier_kind="zone", tier=_zone(), lock_base_contact=False,
        provisional_plan={"1#1": (10, 9, 0)},
    )
    assert sorted(map(tuple, pool["engaged"])) == [(9, 9), (10, 10), (11, 9)], "précondition"
    assert [10, 8] in pool["closer"] and [10, 8] not in pool["engaged"], "précondition"
    out = _preview_objective(gs, _plan(("1#0", (10, 8)), ("1#1", (10, 9))))
    assert out["coherency_ok"] and out["within_objective_range"], "précondition : seul le WHILE refuse"
    assert out["per_model"]["1#0"] is False
    assert out["can_validate"] is False


def test_objective_ending_within_range_is_accepted():
    out = _preview_objective(
        _gs(OBJECTIVE_SQUAD, [FAR_ENEMY]), _plan(("1#0", (10, 10)), ("1#1", (10, 9)))
    )
    assert out["per_model"] == {"1#0": True, "1#1": True}
    assert out["can_validate"] is True
