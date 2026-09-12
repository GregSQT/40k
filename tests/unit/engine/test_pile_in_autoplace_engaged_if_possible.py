"""Auto-placement du pile-in (``pile_in_autoplace_plan``) face à la clause « engaged with it if
possible » (12.03 WHILE) désormais appliquée par le validateur (``_fight_pile_in_preview_plan``).

L'ILP ne pose que des figurines qui engagent le FOCUS ; les autres passent par le repli. Ce repli
choisissait la case la plus proche du focus parmi les cases « closer » : une figurine qui pouvait
finir engagée avec le palier le plus proche pouvait s'arrêter une case avant — plan que le
validateur refuse maintenant. Le repli prend donc une case engagée-avec-le-palier FAISABLE
(cohésion + engagements de départ, `_fight_model_destination_feasible`, même prédicat que le
validateur) quand il en existe une, puis un point fixe remonte les figurines repliées « closer »
qu'une pose ultérieure a rendues « possibles » — le validateur juge la configuration FINALE.

Géométries MESURÉES (règles réelles : EZ = 2, cohésion 2, ``inches_to_subhex`` = 1) :

  - MONO-CIBLE : S#0 (10,6), S#1 (10,5), S#2 (10,4), E (10,10) = focus = palier. L'ILP pose S#0 et
    S#1 sur des cases engagées ; S#2 (à 6, budget 3) n'a AUCUNE case engagée atteignable → repli
    « closer ». Le plan doit rester validable. (En mono-cible, un repli engagé-faisable n'existe
    que si l'ILP est sous-optimal : tout candidat engagé-faisable du repli est une arête ILP.)

  - MULTI-CIBLES : S#0 (10,6), S#1 (10,5), T (10,10) = palier le plus proche, F (10,0) = focus
    (dans les 5″, mais s'en approcher éloigne de T → aucune arête ILP). Passe séquentielle : S#0
    n'a pas de case engagée cohérente avec S#1 encore en (10,5) → « closer » ; S#1 → (10,8)
    engagée. Point fixe : S#0 a maintenant (9,8)/(11,8) engagées et cohérentes → remontée. Sans le
    point fixe, ``per_model[S#0]`` serait False sur la configuration finale.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.phase_handlers.fight_handlers import (
    _fight_pile_in_closest_tier_ids,
    _fight_pile_in_model_plan_state,
    _fight_pile_in_preview_plan,
    _fight_v11_pile_in_targets,
    pile_in_autoplace_plan,
)
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

Cell = Tuple[int, int]


def _gs(squad: Sequence[Cell], enemies: Sequence[Cell]) -> Dict[str, Any]:
    units = [synthetic_unit("1", 1, [{"col": c, "row": r} for c, r in squad])]
    for i, (c, r) in enumerate(enemies):
        units.append(synthetic_unit(str(2 + i), 2, [{"col": c, "row": r}]))
    # ``fight_subphase`` : étape 12.02 (le plan_state pile-in la relit pour distinguer l'overrun 12.06).
    return synthetic_state(
        units, phase="fight", game_rules={}, inches_to_subhex=1, board_cols=44, board_rows=60,
        fight_subphase="pile_in",
    )


def _autoplace_and_preview(
    gs: Dict[str, Any], focus: str, mode: str
) -> Tuple[List[List[Any]], Dict[str, Any], List[str]]:
    unit = gs["unit_by_id"]["1"]
    targets = _fight_v11_pile_in_targets(gs, unit)
    tier = _fight_pile_in_closest_tier_ids(gs, unit, targets)
    plan = pile_in_autoplace_plan(gs, "1", focus, mode=mode)["plan"]
    preview = _fight_pile_in_preview_plan(gs, "1", [tuple(e) for e in plan], tier)
    return plan, preview, tier


def _engaged_models(gs: Dict[str, Any], plan: List[List[Any]]) -> List[str]:
    """Figurines dont la case du plan est ≤ EZ d'une cible pile-in, d'après le plan_state."""
    st = _fight_pile_in_model_plan_state(
        gs, gs["unit_by_id"]["1"],
        provisional_plan={str(m): (int(c), int(r), int(lv)) for m, c, r, lv in plan},
    )
    return sorted(st["engaged_models"])


MONO_SQUAD: List[Cell] = [(10, 6), (10, 5), (10, 4)]
MONO_ENEMY: Cell = (10, 10)


@pytest.mark.parametrize("mode", ["offensive", "defensive"])
def test_mono_target_plan_stays_valid_under_if_possible(mode: str):
    gs = _gs(MONO_SQUAD, [MONO_ENEMY])
    plan, preview, tier = _autoplace_and_preview(gs, "2", mode)
    assert tier == ["2"]
    assert preview["per_model"] == {"1#0": True, "1#1": True, "1#2": True}
    assert preview["can_validate"] is True
    # VERT VACANT : les deux figurines qui peuvent engager le font ; S#2 est bien repliée « closer »
    # (elle a bougé) sans case engagée atteignable.
    assert _engaged_models(gs, plan) == ["1#0", "1#1"]
    s2 = next(e for e in plan if e[0] == "1#2")
    assert (int(s2[1]), int(s2[2])) != MONO_SQUAD[2]


MULTI_SQUAD: List[Cell] = [(10, 6), (10, 5)]
TIER_ENEMY: Cell = (10, 10)
FOCUS_ENEMY: Cell = (10, 0)


@pytest.mark.parametrize("mode", ["offensive", "defensive"])
def test_multi_target_fallback_takes_a_feasible_engaged_cell(mode: str):
    gs = _gs(MULTI_SQUAD, [TIER_ENEMY, FOCUS_ENEMY])
    unit = gs["unit_by_id"]["1"]
    assert sorted(_fight_v11_pile_in_targets(gs, unit)) == ["2", "3"], "précondition : F est une cible"
    plan, preview, tier = _autoplace_and_preview(gs, "3", mode)
    assert tier == ["2"], "précondition : T est le palier, pas le focus"
    # Les deux figurines finissent engagées avec T — dont S#0, remontée par le point fixe.
    assert _engaged_models(gs, plan) == ["1#0", "1#1"]
    assert preview["per_model"] == {"1#0": True, "1#1": True}
    assert preview["can_validate"] is True
