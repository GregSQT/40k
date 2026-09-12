"""Overrun 12.06 sur le chemin gym — second cas d'éligibilité (devenue engagée pendant la phase).

Règle (`12 Fights phase.pdf` p.3) : OVERRUN FIGHT « ELIGIBLE IF: Your unit is unengaged, or was
unengaged at the start of the Fight step but became engaged during the Fight phase. EFFECT: Your
unit can make one additional pile-in move, then fights ». 12.03 BEFORE MOVING : « If your unit is
engaged, select every enemy unit it is engaged with ».

Chemin de production : `W40KEngine._continue_squad_fight_after_selection` (siège programmatique :
politique en gym, bot en PvE). Il ne faisait le pile-in additionnel que si l'unité était NON
engagée maintenant ; une unité de l'agent engagée pendant l'étape FIGHT par le pile-in overrun
d'un ennemi (non engagée au snapshot 12.04, donc sans pile-in 12.02) restait où l'adversaire
l'avait mise, alors que le siège manuel (`fight_v11_can_overrun_pile_in`) lui offre le move.

Verrou ROUGE/VERT : avec l'ancienne condition `not _fight_v11_engaged_now`, `eng.moves` reste
vide dans le premier test (unité engagée) — ROUGE. Miroir masque : `build_squad_action_mask`
reflète le pool POST-pile-in dans ce cas (parité masque/commit).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import engine.w40k_core as wcore
from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.fight_handlers import OVERRUN_PILE_IN_DONE_KEY
from engine.phase_handlers.shared_utils import (
    SQUAD_ACTION_FIGHT_SLOT_BASE,
    build_squad_action_mask,
    commit_move,
    get_enemy_slot_mapping,
    init_enemy_slot_mapping,
)

from tests.unit.engine._state_builders import squad_model_cells, synthetic_state, synthetic_unit


_OURS = "1"
_FOE = "2"
_FOE_CELL = (10, 12)


class _FakeEngine:
    """Moteur minimal : la continuation réelle, le commit réel (`commit_move`) tracé, la
    résolution du combat stubbée (hors sujet : seule la cible retenue compte)."""

    _continue_squad_fight_after_selection = (
        wcore.W40KEngine._continue_squad_fight_after_selection
    )
    _fight_target_after_designated_death = (
        wcore.W40KEngine._fight_target_after_designated_death
    )

    def __init__(self, gs: Dict[str, Any]) -> None:
        self.game_state = gs
        self.moves: List[Tuple[str, str, List[Tuple[str, int, int, int]]]] = []
        self.resolved: List[Tuple[str, Optional[str]]] = []

    def _gym_commit_fight_move(self, gs, squad_id, plan, reason):  # noqa: ANN001
        self.moves.append((str(squad_id), reason, list(plan)))
        commit_move(plan, gs, reason)

    def _fight_resolve_with_target(self, squad_id, best_target_id):  # noqa: ANN001
        self.resolved.append((str(squad_id), best_target_id))
        return True, {"target_squad_id": best_target_id}


def _gs(*, engaged_at_start: bool, extra_foes: Tuple[Dict[str, Any], ...] = ()) -> Dict[str, Any]:
    """x1 (hex, EZ=2, pile-in 3, cibles ≤5) : fig a à 2 de l'ennemi (engagée, pas au contact),
    fig b à 4 (hors EZ, mais ≤3 d'une case engagée). Unité 1 non chargée ; son statut au snapshot
    12.04 est le seul paramètre : False = devenue engagée pendant la phase (second cas 12.06)."""
    ours = synthetic_unit(_OURS, 1, [{"col": 10, "row": 10}, {"col": 10, "row": 8}])
    foe = synthetic_unit(_FOE, 2, [{"col": _FOE_CELL[0], "row": _FOE_CELL[1]}])
    gs = synthetic_state(
        [ours, foe, *extra_foes],
        phase="fight",
        game_rules={},
        fight_subphase="fight",
        current_player=1,
        fight_step="remaining",
        fight_selector=1,
        engaged_at_fight_step_start={
            _OURS: engaged_at_start, _FOE: True, **{str(u["id"]): True for u in extra_foes}
        },
        units_charged=set(),
        units_selected_to_fight=set(),
        units_fought=set(),
        pile_in_done=set(),
        consolidation_done=set(),
    )
    gs[OVERRUN_PILE_IN_DONE_KEY] = set()
    init_enemy_slot_mapping(gs, 1)
    return gs


def _dist_to_foe(cell: Tuple[int, int]) -> int:
    return calculate_hex_distance(cell[0], cell[1], _FOE_CELL[0], _FOE_CELL[1])


def test_unit_engaged_during_phase_gets_additional_pile_in():
    """Second cas 12.06 : engagée maintenant, non engagée au snapshot → pile-in additionnel."""
    gs = _gs(engaged_at_start=False)
    before = squad_model_cells(gs, _OURS)
    assert any(_dist_to_foe(c) > 2 for c in before.values()), "VERT VACANT : une fig doit être hors EZ"
    slot = get_enemy_slot_mapping(gs, 1).index(_FOE)
    eng = _FakeEngine(gs)

    ok, _res = eng._continue_squad_fight_after_selection(_OURS, target_slot=slot)

    assert ok is True
    assert [(sid, kind) for sid, kind, _p in eng.moves] == [(_OURS, "overrun_pile_in")]
    after = squad_model_cells(gs, _OURS)
    assert after != before, "le plan commité doit avoir déplacé au moins une figurine"
    assert all(_dist_to_foe(after[m]) <= _dist_to_foe(before[m]) for m in before)
    assert all(_dist_to_foe(c) <= 2 for c in after.values()), (
        "12.03 WHILE MOVING « engaged with it if possible » : les deux figs finissent en EZ"
    )
    assert _OURS in gs[OVERRUN_PILE_IN_DONE_KEY], "garde « one additional pile-in move » posée"
    assert eng.resolved == [(_OURS, _FOE)], "l'unité frappe la cible désignée après le move"


def test_unit_engaged_at_step_start_makes_normal_fight():
    """Contrôle : engagée au snapshot → NORMAL fight 12.05, aucun pile-in additionnel."""
    gs = _gs(engaged_at_start=True)
    before = squad_model_cells(gs, _OURS)
    slot = get_enemy_slot_mapping(gs, 1).index(_FOE)
    eng = _FakeEngine(gs)

    ok, _res = eng._continue_squad_fight_after_selection(_OURS, target_slot=slot)

    assert ok is True
    assert eng.moves == []
    assert squad_model_cells(gs, _OURS) == before
    assert _OURS not in gs[OVERRUN_PILE_IN_DONE_KEY]
    assert eng.resolved == [(_OURS, _FOE)]


def test_mask_reflects_post_pile_in_pool_when_engaged_during_phase():
    """Parité masque/commit : dans le second cas, le masque projette le plan (pool POST-move).

    Ennemi F2 hors EZ de l'unité mais voisin de F1 (la seule cible 12.03, engagée). Le commit
    pile d'abord puis frappe depuis l'arrivée, où F2 est devenu frappable ; le masque doit ouvrir
    F1 ET F2 — exactement les cibles que le commit trouverait. ROUGE si le masque n'ouvre que le
    pool pré-move (F1 seul).
    """
    from engine.game_utils import require_unit_by_id
    from engine.phase_handlers.fight_handlers import (
        _fight_build_valid_target_pool,
        _model_can_fight_target,
    )
    from engine.phase_handlers.shared_utils import fight_pile_in_plan

    foe2 = synthetic_unit("3", 2, [{"col": 12, "row": 12}])
    gs = _gs(engaged_at_start=False, extra_foes=(foe2,))
    slots = get_enemy_slot_mapping(gs, 1)
    assert "3" in slots
    pre = set(_fight_build_valid_target_pool(gs, require_unit_by_id(gs, _OURS)))
    assert pre == {_FOE}, "VERT VACANT : F2 ne doit pas être frappable AVANT le move"

    plan = fight_pile_in_plan(gs, _OURS)
    assert plan is not None, "VERT VACANT : le plan doit exister (fig b à ≤3 d'une case engagée)"
    mask = build_squad_action_mask(gs, _OURS, enemy_slot_ids=slots)

    # Cibles que le commit trouverait APRÈS le move (branche `_did_overrun`).
    commit_move(plan, gs, "overrun_pile_in")
    mc = gs["models_cache"]
    expected = {
        esid
        for esid in slots
        if esid is not None
        and any(_model_can_fight_target(gs, mc[m], _OURS, esid) for m in gs["squad_models"][_OURS])
    }
    assert expected == {_FOE, "3"}, "VERT VACANT : F2 doit être frappable APRÈS le move"
    opened = {esid for i, esid in enumerate(slots) if esid is not None and mask[SQUAD_ACTION_FIGHT_SLOT_BASE + i] == 1}
    assert opened == expected
