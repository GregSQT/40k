"""B2 — la consolidation ENGAGING (12.08) est une décision de l'agent, pas une heuristique.

12.07 : « Both players make consolidation moves with all of their eligible units they CHOOSE to
move » ; encart New Foes to Face : « think carefully about how aggressively you want to move
your unit using this mode ». Le driver gym (`_fight_v11_gym_settle`) consolidait TOUJOURS —
mesuré bot contre bot : 1 engaging sur 33 consolidations, 1 New Foes sur 8 parties.

Verrouillé ici, sur le VRAI driver (même scénario que `test_squad_fight_v11_state.py`, section
New Foes) :
  - la décision `consolidation_engaging` n'est armée qu'en mode engaging (ongoing et objective
    restent automatiques) ;
  - `CHOICE_1` (« Rester ») : aucun move, aucun New Foe, consolidation consommée ;
  - `CHOICE_0` (« Consolider ») : move commité, New Foes gelés pour l'adversaire ;
  - le bot de référence répond `CHOICE_0` (comportement d'avant B2, baseline inchangée).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.unit.engine._melee_scenario import MELEE_SCENARIO
from tests.unit.engine.test_squad_fight_v11_state import (
    _NEW_FOE_COL,
    _NEW_FOE_ROW,
    _engine_in_fight_phase,
)


@pytest.fixture()
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _engine_at_consolidation(scenario_file: str, *, foe_row: int = _NEW_FOE_ROW):
    """Unité 1 sélectionnée, cible détruite, ennemi E (unité 4) posé en (59, foe_row) ; le settle
    déroule jusqu'à la consolidation de 1 (mode selon `foe_row` : 223-228 engaging, ≥ 229 hors
    des 3" — mesuré dans `test_squad_fight_v11_state.py`)."""
    from engine.phase_handlers.fight_handlers import _fight_v11_register_selection
    from engine.phase_handlers.shared_utils import destroy_model, place_model_at_effective_level

    eng = _engine_in_fight_phase(scenario_file)
    gs = eng.game_state
    destroy_model(gs, "2#0", "combat")
    _fight_v11_register_selection(gs, "1")
    place_model_at_effective_level(gs, "4#0", _NEW_FOE_COL, foe_row, int(gs["models_cache"]["4#0"]["level"]))
    eng._fight_v11_gym_settle()
    return eng


def _positions(gs, squad_id: str):
    return {m: (gs["models_cache"][m]["col"], gs["models_cache"][m]["row"]) for m in gs["squad_models"][squad_id] if m in gs["models_cache"]}


def test_decision_is_armed_only_in_engaging_mode(melee_scenario_file):
    """Engaging → décision armée (propriétaire = joueur de l'unité, deux candidats, `declines`
    sur « Rester »), consolidation NON jouée tant que l'agent n'a pas répondu.

    ROUGE avant B2 : le settle consolidait d'office (`consolidation_done` contenait 1, aucune
    décision)."""
    from engine.agent_decision import read_pending_agent_decision
    from engine.observation_entities import AGENT_DECISION_TYPE_IDS

    assert AGENT_DECISION_TYPE_IDS[-1] == "consolidation_engaging", "ajouté en FIN, jamais inséré"

    eng = _engine_at_consolidation(melee_scenario_file)
    gs = eng.game_state
    decision = read_pending_agent_decision(gs)
    assert decision is not None and decision["type"] == "consolidation_engaging", decision
    assert decision["unit_id"] == "1" and decision["player"] == 1
    assert [o["declines"] for o in decision["options"]] == [False, True]
    assert [o["payload"]["consolidate"] for o in decision["options"]] == [True, False]
    assert gs["fight_subphase"] == "consolidate"
    assert "1" not in gs["consolidation_done"], "rien n'est joué tant que l'agent n'a pas répondu"
    assert not [e for e in gs["action_logs"] if e.get("type") == "consolidation"]
    # Masque exclusif : CHOICE_0 et CHOICE_1 seulement.
    from engine.macro_intents import CHOICE_BASE

    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert eligible == [] and {i for i, v in enumerate(mask) if v} == {CHOICE_BASE, CHOICE_BASE + 1}

    # Contre-épreuve : hors engaging, aucune question — `test_squad_fight_v11_state.py`
    # (consolidations ongoing du scénario mêlée) et `test_consolidation_gym_if_possible.py`
    # (objective) jouent ces modes sans décision.


def test_choice_1_stays_no_move_no_new_foes(melee_scenario_file):
    from engine.agent_decision import read_pending_agent_decision

    eng = _engine_at_consolidation(melee_scenario_file)
    gs = eng.game_state
    before = _positions(gs, "1")

    ok, result = eng._process_squad_action({"action": "agent_decision", "option_index": 1})

    assert ok is True and result["consolidate"] is False, result
    assert read_pending_agent_decision(gs) is None
    assert _positions(gs, "1") == before, "« Rester » : aucune figurine ne bouge"
    assert "1" in gs["consolidation_done"]
    assert "consolidation_new_foes_pending" not in gs
    assert not [e for e in gs["action_logs"] if e.get("type") == "consolidation"]
    assert gs["consolidation_engaging_answers"] == {"1": False}


def test_choice_0_consolidates_and_freezes_new_foes(melee_scenario_file):
    from engine.agent_decision import read_pending_agent_decision
    from engine.phase_handlers.fight_handlers import fight_v11_current_pool

    eng = _engine_at_consolidation(melee_scenario_file)
    gs = eng.game_state
    before = _positions(gs, "1")

    ok, result = eng._process_squad_action({"action": "agent_decision", "option_index": 0})

    assert ok is True and result["consolidate"] is True, result
    assert read_pending_agent_decision(gs) is None
    assert _positions(gs, "1") != before, "« Consolider » : l'unité bouge"
    logs = [e for e in gs["action_logs"] if e.get("type") == "consolidation" and str(e["unitId"]) == "1"]
    assert len(logs) == 1 and logs[0]["consolidationMode"] == "engaging" and logs[0]["consolidationTargetIds"] == ["4"]
    assert "1" in gs["consolidation_done"]
    # 12.08 AFTER : New Foes to Face gelés pour l'adversaire, qui les sélectionne.
    assert gs["consolidation_new_foes_pending"] == ["4"]
    assert gs["consolidation_new_foes_selector"] == 2
    assert [str(x) for x in fight_v11_current_pool(gs)] == ["4"]


def test_decision_cannot_be_applied_outside_the_consolidate_step(melee_scenario_file):
    from engine.phase_handlers.fight_handlers import apply_consolidation_engaging_decision

    eng = _engine_at_consolidation(melee_scenario_file)
    gs = eng.game_state
    gs["fight_subphase"] = "fight"
    with pytest.raises(RuntimeError, match="CONSOLIDATE"):
        apply_consolidation_engaging_decision(gs, "1", True)


def test_reference_bot_answers_consolidate_to_keep_its_baseline(melee_scenario_file):
    """Le bot répondait déjà « consolider » (le driver le faisait pour lui) : `CHOICE_0`."""
    from ai.env_wrappers import bot_action_for_pending_choice
    from engine.macro_intents import CHOICE_BASE

    eng = _engine_at_consolidation(melee_scenario_file)
    gs = eng.game_state
    mask, _eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert bot_action_for_pending_choice(gs, mask, "test") == CHOICE_BASE


# ---------------------------------------------------------------------------
# La question n'est posée que si consolider est POSSIBLE (12.07 « they CHOOSE to move »)
# ---------------------------------------------------------------------------


def test_engaging_mode_can_have_no_plan_at_all():
    """Géométrie réelle : mode `engaging` constaté, et pourtant AUCUN plan de consolidation.

    L'ennemi « 2 » est à 3" de l'escouade « 1 » (donc dans `consolidation_trigger_range`), mais
    une unité AMIE occupe les 18 cases à distance ≤ 2 de lui : aucune figurine de « 1 » ne peut
    finir engagée, et `squad_consolidate_plan_with_targets` rend `(None, [])`.
    """
    from engine.combat_utils import calculate_hex_distance
    from engine.phase_handlers.fight_handlers import fight_v11_consolidation_mode
    from engine.phase_handlers.shared_utils import squad_consolidate_plan_with_targets
    from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

    enemy = (10, 13)
    blockers = [
        (c, r)
        for c in range(4, 17)
        for r in range(7, 20)
        if calculate_hex_distance(c, r, *enemy) <= 2 and (c, r) != enemy
    ]
    assert len(blockers) == 18, blockers
    gs = synthetic_state(
        [
            synthetic_unit("1", 1, [{"col": 10, "row": 10}]),
            synthetic_unit("2", 2, [{"col": enemy[0], "row": enemy[1]}]),
            synthetic_unit("3", 1, [{"col": c, "row": r} for c, r in blockers]),
        ],
        phase="fight", game_rules={}, inches_to_subhex=1,
        board_cols=44, board_rows=60, fight_subphase="consolidate",
    )

    assert fight_v11_consolidation_mode(gs, {"id": "1", "player": 1}) == "engaging"
    assert squad_consolidate_plan_with_targets(gs, "1", mode="engaging") == (None, [])


def test_no_decision_is_armed_when_the_engaging_plan_is_impossible(melee_scenario_file):
    """Mode engaging mais plan impossible → aucune décision armée, consolidation consommée.

    ROUGE avant le fix : le settle armait `consolidation_engaging` AVANT de calculer le plan,
    et l'agent répondait à une question dont les deux réponses produisent le même état (aucun
    commit, aucun New Foe, `consolidation_done` posée).
    """
    import engine.phase_handlers.shared_utils as su_module
    from engine.agent_decision import read_pending_agent_decision

    orig = su_module.squad_consolidate_plan_with_targets
    su_module.squad_consolidate_plan_with_targets = lambda gs, sid, *, mode=None: (None, [])
    try:
        eng = _engine_at_consolidation(melee_scenario_file)
    finally:
        su_module.squad_consolidate_plan_with_targets = orig
    gs = eng.game_state

    assert read_pending_agent_decision(gs) is None, "aucune question quand consolider est impossible"
    assert "1" in gs["consolidation_done"], "la consolidation 12.07 est consommee"
    assert gs["consolidation_engaging_answers"] == {}
    assert not [e for e in gs["action_logs"] if e.get("type") == "consolidation"]
    assert "consolidation_new_foes_pending" not in gs
