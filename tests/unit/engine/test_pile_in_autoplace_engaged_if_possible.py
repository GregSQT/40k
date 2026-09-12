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

  - REPLI « CLOSER » ET ENGAGEMENT DE DÉPART (12.03 AFTER « each model that started this move
    engaged with an enemy unit must still be engaged with that enemy unit ») : la branche « closer »
    du repli ne retient que les cases où la figurine CONSERVE ses engagements de départ (même filtre
    que les arêtes ILP et la branche engagée) ; aucune → elle reste sur place.
      · S#0 (10,8) engagée avec A (10,10), S#1 (12,7), S#2 (14,8) au contact de B (15,8) = palier =
        focus. S#0 n'a aucune case engagée-avec-B qui garde A → « closer » ; les cases « closer »
        (12,9)/(12,10) gardent A, (13,7)/(13,8) la perdent. Avant le filtre : (13,7) →
        ``kept_engagements`` False.
      · S#0 (11,8) engagée avec A (9,8), S#1 (13,8) au contact de B (14,8) : AUCUNE case « closer »
        ne garde A → S#0 reste en (11,8), plan validable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.hex_utils import hex_distance
from engine.phase_handlers.fight_handlers import (
    _fight_model_start_engaged_entries,
    _fight_pile_in_closest_tier_ids,
    _fight_pile_in_model_plan_state,
    _fight_pile_in_preview_plan,
    _fight_v11_pile_in_targets,
    _synth_model_entry,
    pile_in_autoplace_plan,
)
from engine.phase_handlers.shared_utils import get_engagement_zone
from engine.spatial_relations import engagement_distance_metric, unit_entries_within_engagement_zone
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


def _plan_cell(plan: List[List[Any]], mid: str) -> Cell:
    e = next(e for e in plan if e[0] == mid)
    return int(e[1]), int(e[2])


def _keeps_start_engagements(gs: Dict[str, Any], mid: str, cell: Cell) -> bool:
    """La figurine ``mid`` posée en ``cell`` reste ≤ EZ de CHAQUE ennemi avec lequel elle est
    engagée au départ (mesure du validateur, ``kept_engagements``)."""
    m = gs["models_cache"][mid]
    start = _fight_model_start_engaged_entries(gs, "1", m)
    assert start, f"précondition : {mid} est engagée au départ"
    ez = int(get_engagement_zone(gs))
    metric = engagement_distance_metric(gs)
    synth = _synth_model_entry(gs, "1", m, cell[0], cell[1], level=int(m["level"]))
    return all(unit_entries_within_engagement_zone(synth, ce, ez, metric=metric) for ce in start)


def _closer_cells_keeping_engagements(gs: Dict[str, Any], mid: str, tier_cell: Cell) -> List[Cell]:
    """Cases à ≤ 3 du départ, strictement plus proches de ``tier_cell`` (WHILE) et qui gardent les
    engagements de départ (AFTER) — énumération indépendante du repli, pour la précondition."""
    m = gs["models_cache"][mid]
    sc, sr = int(m["col"]), int(m["row"])
    sm = hex_distance(sc, sr, *tier_cell)
    return [
        (c, r)
        for c in range(sc - 3, sc + 4)
        for r in range(sr - 3, sr + 4)
        if (c, r) != (sc, sr)
        and hex_distance(sc, sr, c, r) <= 3
        and hex_distance(c, r, *tier_cell) < sm
        and _keeps_start_engagements(gs, mid, (c, r))
    ]


KEEP_SQUAD: List[Cell] = [(10, 8), (12, 7), (14, 8)]
KEEP_A: Cell = (10, 10)
KEEP_B: Cell = (15, 8)


@pytest.mark.parametrize("mode", ["offensive", "defensive"])
def test_closer_fallback_keeps_start_engagement(mode: str):
    gs = _gs(KEEP_SQUAD, [KEEP_A, KEEP_B])
    keeping = _closer_cells_keeping_engagements(gs, "1#0", KEEP_B)
    assert keeping, "précondition : S#0 a des cases « closer » qui gardent A"
    plan, preview, tier = _autoplace_and_preview(gs, "3", mode)
    assert tier == ["3"], "précondition : B est le palier (S#2 au contact)"
    s0 = _plan_cell(plan, "1#0")
    # S#0 bouge (repli « closer »), vers une case qui garde A — jamais (13,7)/(13,8) qui la perdent.
    assert s0 != KEEP_SQUAD[0]
    assert s0 in keeping
    assert _keeps_start_engagements(gs, "1#0", s0)
    assert preview["kept_engagements"] is True
    assert preview["can_validate"] is True


STAY_SQUAD: List[Cell] = [(11, 8), (13, 8)]
STAY_A: Cell = (9, 8)
STAY_B: Cell = (14, 8)


@pytest.mark.parametrize("mode", ["offensive", "defensive"])
def test_closer_fallback_stays_put_when_no_cell_keeps_engagement(mode: str):
    gs = _gs(STAY_SQUAD, [STAY_A, STAY_B])
    assert _closer_cells_keeping_engagements(gs, "1#0", STAY_B) == [], (
        "précondition : aucune case « closer » de S#0 ne garde A"
    )
    plan, preview, tier = _autoplace_and_preview(gs, "3", mode)
    assert tier == ["3"], "précondition : B est le palier (S#1 au contact)"
    # S#0 reste sur place plutôt que de perdre A ; S#1 est figée (base-contact).
    assert _plan_cell(plan, "1#0") == STAY_SQUAD[0]
    assert _plan_cell(plan, "1#1") == STAY_SQUAD[1]
    assert preview["kept_engagements"] is True


# FOCUS HORS PALIER, SLOTS FOCUS ATTEIGNABLES : S#0 (10,6), T (10,10) = palier (dist 4),
# F = focus à 5 (cible pile-in ≤ 5″). L'ILP ne posait que sur des slots engageant F : quand un tel
# slot est strictement plus proche de T sans l'engager, le validateur (« engaged with it if
# possible ») refusait le plan, S#0 ayant des cases engagées-avec-T atteignables.
#   - F (14,9) : aucun slot n'engage T et F à la fois → mesuré avant correction : (12,8), dT 3,
#     dF 2, ``per_model`` False. Attendu : case engagée avec T (dT ≤ 2), départage par le mode.
#   - F (7,9) : (9,8) engage T ET F → l'ILP doit la choisir (le Focus reste maximisé SOUS la règle).
FAR_FOCUS: Cell = (14, 9)
NEAR_FOCUS: Cell = (7, 9)


@pytest.mark.parametrize(
    ("focus", "mode", "focus_engaged"),
    [
        (FAR_FOCUS, "offensive", False),
        (FAR_FOCUS, "defensive", False),
        (NEAR_FOCUS, "offensive", True),
        (NEAR_FOCUS, "defensive", True),
    ],
)
def test_focus_outside_tier_ilp_only_takes_tier_engaged_slots(
    focus: Cell, mode: str, focus_engaged: bool
):
    gs = _gs([(10, 6)], [TIER_ENEMY, focus])
    unit = gs["unit_by_id"]["1"]
    assert sorted(_fight_v11_pile_in_targets(gs, unit)) == ["2", "3"], "précondition : F est une cible"
    plan, preview, tier = _autoplace_and_preview(gs, "3", mode)
    assert tier == ["2"], "précondition : T est le palier, pas le focus"
    dest = (int(plan[0][1]), int(plan[0][2]))
    assert dest != (10, 6), "VERT VACANT : la figurine a bougé"
    assert hex_distance(*dest, *TIER_ENEMY) <= 2, f"{dest} n'engage pas le palier T"
    assert (hex_distance(*dest, *focus) <= 2) is focus_engaged, dest
    assert preview["per_model"] == {"1#0": True}
    assert preview["can_validate"] is True
