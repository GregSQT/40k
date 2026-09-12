"""Pile-in 12.03 WHILE MOVING : « each model that is moved must end its move closer to the closest
pile-in target, **and engaged with it if possible** ».

La validation PvP par figurine (``_fight_pile_in_preview_plan``, ``per_model``) ne jugeait que
l'appartenance au pool « closer » : une figurine qui POUVAIT finir engagée avec le palier le plus
proche pouvait s'arrêter une case avant. La clé ``engaged`` rendue par
``_fight_pile_in_build_model_pool`` n'avait aucun consommateur.

Définition retenue de « possible » (lecture du PDF 12, qui ne le définit pas ; cohésion jugée « at
the end of the move », PDF 03) : il existe une case engagée qui, les AUTRES figurines aux positions
du plan, respecte la cohésion 03.03 ET conserve les engagements de départ de CETTE figurine. Si oui,
seules ces cases sont légales ; sinon « closer » suffit. Une figurine immobile n'est pas soumise au
WHILE. Source unique : ``_fight_model_legal_destinations``.

Géométrie MESURÉE (règles réelles : EZ = 2, cohésion 2, ``inches_to_subhex`` = 1) — S#0 (10,6),
S#1 (10,9), E (10,10). Pool « closer » de S#0 = (8,8) (9,7) (9,8) (10,7) (10,8) (11,7) (11,8) (12,8) ;
engagées = (9,8) (10,8) (11,8), toutes cohérentes avec S#1 en (10,9).
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from engine.phase_handlers.fight_handlers import (
    _fight_pile_in_build_model_pool,
    _fight_pile_in_closest_tier_ids,
    _fight_pile_in_model_plan_state,
    _fight_pile_in_preview_plan,
)
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

Cell = Tuple[int, int]

SQUAD: List[Cell] = [(10, 6), (10, 9)]
ENEMY: Cell = (10, 10)
CLOSER_ONLY: Cell = (10, 7)   # plus proche de E (3), pas engagée (EZ 2)
ENGAGED: Cell = (10, 8)       # engagée avec E (2), cohérente avec S#1 (10,9)


def _gs(squad: Sequence[Cell], enemies: Sequence[Cell]) -> Dict[str, Any]:
    units = [synthetic_unit("1", 1, [{"col": c, "row": r} for c, r in squad])]
    for i, (c, r) in enumerate(enemies):
        units.append(synthetic_unit(str(2 + i), 2, [{"col": c, "row": r}]))
    # ``fight_subphase`` : étape 12.02 (le plan_state pile-in la relit pour distinguer l'overrun 12.06).
    return synthetic_state(
        units, phase="fight", game_rules={}, inches_to_subhex=1, board_cols=44, board_rows=60,
        fight_subphase="pile_in",
    )


def _plan(*entries: Tuple[str, Cell]) -> List[Tuple[str, int, int, int]]:
    return [(mid, c, r, 0) for mid, (c, r) in entries]


def test_geometry_precondition_engaged_cells_exist():
    """VERT VACANT : le pool de S#0 contient bien des cases engagées ET des cases seulement
    « closer » — sans quoi les deux tests suivants ne discrimineraient rien."""
    gs = _gs(SQUAD, [ENEMY])
    pool = _fight_pile_in_build_model_pool(gs, "1#0", ["2"], provisional_plan={"1#1": (10, 9, 0)})
    assert sorted(map(tuple, pool["engaged"])) == [(9, 8), (10, 8), (11, 8)]
    assert list(CLOSER_ONLY) in pool["closer"] and list(CLOSER_ONLY) not in pool["engaged"]


def test_a_model_that_could_engage_may_not_stop_short():
    """S#0 → (10,7) alors que (10,8) est engagée et faisable : REFUSÉ (per_model False)."""
    out = _fight_pile_in_preview_plan(
        _gs(SQUAD, [ENEMY]), "1", _plan(("1#0", CLOSER_ONLY), ("1#1", SQUAD[1])), ["2"]
    )
    assert out["coherency_ok"] and out["unit_engaged"] and out["kept_engagements"], (
        "précondition : seule la clause « if possible » doit refuser ce plan"
    )
    assert out["per_model"]["1#0"] is False
    assert out["can_validate"] is False


def test_ending_engaged_is_accepted():
    """Contre-épreuve : S#0 → (10,8) engagée — ACCEPTÉ."""
    out = _fight_pile_in_preview_plan(
        _gs(SQUAD, [ENEMY]), "1", _plan(("1#0", ENGAGED), ("1#1", SQUAD[1])), ["2"]
    )
    assert out["per_model"] == {"1#0": True, "1#1": True}
    assert out["can_validate"] is True


def test_plan_state_pool_only_lists_legal_destinations():
    """Le pool exposé au front pour la figurine sélectionnée = ses destinations LÉGALES (les 3 cases
    engagées, sans les 5 cases seulement « closer ») ; ``eligible_models`` reste « closer non vide »."""
    gs = _gs(SQUAD, [ENEMY])
    st = _fight_pile_in_model_plan_state(gs, gs["unit_by_id"]["1"], selected_model="1#0")
    assert sorted(map(tuple, st["pool"])) == [(9, 8), (10, 8), (11, 8)]
    assert st["eligible_models"] == ["1#0"]  # S#1 en base-contact : aucune case « closer »


# --- Contre-épreuve de la règle NAÏVE « engaged non vide ⇒ obligatoire » ----------------------
# S#0 (10,8) engagée avec A (10,10) ; S#1 (12,7) ; S#2 (14,8) ; B (15,8) = palier le plus proche
# de l'unité (S#2 à distance 1). Cases engagées-avec-B de S#0 = (13,7) (13,8) (13,9) : toutes
# font PERDRE l'engagement de départ avec A (kept_engagements False) → aucune n'est « possible »,
# donc S#0 → (11,8), seulement plus proche de B, reste légal.

WIDE_SQUAD: List[Cell] = [(10, 8), (12, 7), (14, 8)]
ENEMY_A: Cell = (10, 10)
ENEMY_B: Cell = (15, 8)
CLOSER_TO_B: Cell = (11, 8)


def test_engaged_cells_that_break_a_starting_engagement_are_not_possible():
    gs = _gs(WIDE_SQUAD, [ENEMY_A, ENEMY_B])
    unit = gs["unit_by_id"]["1"]
    tier = _fight_pile_in_closest_tier_ids(gs, unit, ["2", "3"])
    assert tier == ["3"], "précondition : B est le palier le plus proche"
    others = {"1#1": (12, 7, 0), "1#2": (14, 8, 0)}
    pool = _fight_pile_in_build_model_pool(gs, "1#0", tier, provisional_plan=others)
    assert sorted(map(tuple, pool["engaged"])) == [(13, 7), (13, 8), (13, 9)], "précondition"
    for cell in pool["engaged"]:
        broken = _fight_pile_in_preview_plan(
            gs, "1", _plan(("1#0", (cell[0], cell[1])), ("1#1", WIDE_SQUAD[1]), ("1#2", WIDE_SQUAD[2])), tier
        )
        assert broken["kept_engagements"] is False, f"précondition : {cell} perd A"

    out = _fight_pile_in_preview_plan(
        gs, "1", _plan(("1#0", CLOSER_TO_B), ("1#1", WIDE_SQUAD[1]), ("1#2", WIDE_SQUAD[2])), tier
    )
    assert out["per_model"]["1#0"] is True
    assert out["can_validate"] is True
