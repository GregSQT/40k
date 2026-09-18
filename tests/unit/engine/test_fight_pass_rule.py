"""A5 — passe de l'étape FIGHT (PDF 25, « ELIGIBLE TO FIGHT, BUT UNABLE TO FIGHT »).

« During the Fight sequence, when the sequence returns to a player to select a unit to fight, if
all of that player's units that are eligible to fight are more than 5" from all enemy units, that
player can instead choose to pass and return the sequence to their opponent to select a unit. If
both players pass in succession, or if one player passes when their opponent has no remaining
units that are eligible to fight, the Fight step ends. »

CE QUE CE FICHIER EMPÊCHE. Jusqu'au 2026-09-18, une unité éligible sans cible n'avait qu'une
action, le combat à vide (`SQUAD_ACTION_FIGHT_NO_TARGET` → `squad_fight`), qui la marquait
« selected to fight » : elle ne pouvait plus combattre comme New Foe (12.08 AFTER) si une
consolidation adverse l'engageait ensuite. Mesuré sur l'agent P0′ : 0,08 % des steps, ~0,26 par
épisode.

Scénario réel (x5, config par défaut) : deux unités mono-figurine « chargeuses » (11.04 AFTER :
`units_charged`, donc éligibles 12.04) à 10" l'une de l'autre — aucune à ≤ 5" d'un ennemi.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from engine.phase_handlers.shared_utils import SQUAD_ACTION_FIGHT_NO_TARGET


def _scenario(p2_col: int = 150) -> Dict[str, Any]:
    return {
        "primary_objectives": ["objectives_control"],
        "uses_codex_detachment": {"1": True, "2": True},
        "army_faction": {"1": "ORKS", "2": "ADEPTUS ASTARTES"},
        "board_ref": "44x60x5",
        "terrain_ref": "terrain-mc1.json",
        "deployment_type": "fixed",
        "units": [
            {"id": "1", "player": 1, "unit_type": "Boyz", "col": 100, "row": 100,
             "models": [{"col": 100, "row": 100}]},
            {"id": "2", "player": 2, "unit_type": "Intercessor", "col": p2_col, "row": 100,
             "models": [{"col": p2_col, "row": 100}]},
        ],
    }


@pytest.fixture()
def engine_factory(tmp_path: Path):
    def _make(p2_col: int = 150, charged: Optional[List[str]] = None):
        from ai.unit_registry import UnitRegistry
        from engine.agent_decision import PENDING_DECISION_KEY
        from engine.phase_handlers import fight_handlers
        from engine.w40k_core import W40KEngine

        path = tmp_path / f"pass_{p2_col}.json"
        path.write_text(json.dumps(_scenario(p2_col)))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent_x1", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent_x1", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        )
        eng.reset(seed=1)
        gs = eng.game_state
        gs.pop(PENDING_DECISION_KEY, None)  # appel de Waaagh! du reset, sans objet ici
        gs["phase"] = "fight"
        gs["current_player"] = 1
        gs["units_fought"] = set()
        gs["units_charged"] = set(charged if charged is not None else ["1", "2"])
        res = fight_handlers.fight_phase_start(gs)
        eng._fight_v11_gym_after_phase_start(res)
        assert gs["fight_subphase"] == "fight", gs["fight_subphase"]
        return eng
    return _make


def _decoded_no_target(eng, squad_id: str) -> Dict[str, Any]:
    gs = eng.game_state
    mask, eligible = eng.action_decoder.get_squad_action_mask_and_eligible_units(gs)
    assert eligible and str(eligible[0]["id"]) == squad_id, [u["id"] for u in eligible]
    assert bool(mask[SQUAD_ACTION_FIGHT_NO_TARGET]), "le slot sans cible doit être ouvert"
    return eng.action_decoder.convert_squad_action(SQUAD_ACTION_FIGHT_NO_TARGET, gs)


def test_pass_leaves_the_unit_unselected_so_it_can_still_be_a_new_foe(engine_factory):
    """P1 passe : son unité n'est PAS « selected to fight », la main est à P2, et si un ennemi
    vient l'engager par consolidation elle est un New Foe (12.08 AFTER).

    ROUGE avant A5 : le slot décodait `squad_fight` (combat à vide) et marquait l'unité.
    """
    from engine.phase_handlers.fight_handlers import (
        FIGHT_PASS_STREAK_KEY,
        fight_v11_engaging_triggered_unit_ids,
        fight_v11_expected_seat,
    )
    from engine.phase_handlers.shared_utils import place_model_at_effective_level

    eng = engine_factory()
    gs = eng.game_state
    semantic = _decoded_no_target(eng, "1")
    assert semantic == {"action": "squad_fight_pass", "squad_id": "1"}, semantic

    ok, result = eng._process_squad_action(semantic)

    assert ok is True and result["action"] == "squad_fight_pass", result
    assert result["fight_step_ended"] is False, "P2 a une unité éligible : la main lui revient"
    assert "1" not in gs["units_selected_to_fight"]
    assert gs[FIGHT_PASS_STREAK_KEY] == 1
    assert fight_v11_expected_seat(gs) == 2
    assert gs["fight_subphase"] == "fight"
    assert any(l.get("type") == "fight_pass" and l["unitId"] == "1" for l in gs["action_logs"])
    # L'ennemi vient au contact (comme le ferait sa consolidation engaging) : l'unité 1, jamais
    # sélectionnée, est bien un New Foe à faire combattre.
    place_model_at_effective_level(gs, "2#0", 108, 100, 0)
    assert fight_v11_engaging_triggered_unit_ids(gs, gs["unit_by_id"]["2"]) == ["1"]


def test_two_passes_in_succession_end_the_fight_step(engine_factory):
    """P1 passe, P2 passe : l'étape FIGHT se termine (sous-phase consolidate) sans qu'aucune
    unité soit sélectionnée ; les deux unités, « eligible to fight this phase », consolident."""
    from engine.phase_handlers.fight_handlers import (
        FIGHT_STEP_PASSED_KEY,
        fight_v11_fight_selection_pool,
        fight_v11_is_consolidation_eligible,
    )

    eng = engine_factory()
    gs = eng.game_state
    ok, result = eng._process_squad_action(_decoded_no_target(eng, "1"))
    assert ok and result["fight_step_ended"] is False
    semantic = _decoded_no_target(eng, "2")
    assert semantic["action"] == "squad_fight_pass"

    ok, result = eng._process_squad_action(semantic)

    assert ok and result["fight_step_ended"] is True, result
    assert gs[FIGHT_STEP_PASSED_KEY] is True
    assert gs["units_selected_to_fight"] == set()
    assert fight_v11_fight_selection_pool(gs) == []
    # Le driver a enchaîné : l'étape FIGHT est close, la consolidation (12.07) a été déroulée
    # pour les deux unités éligibles (mode objective ou aucune : ni engagée ni ennemi à 3").
    assert gs["fight_subphase"] == "consolidate", gs["fight_subphase"]
    for uid in ("1", "2"):
        assert fight_v11_is_consolidation_eligible(gs, gs["unit_by_id"][uid]), uid
        assert uid in gs["consolidation_done"]


def test_pass_when_opponent_has_no_eligible_unit_ends_the_step(engine_factory):
    """Une seule unité éligible (P1), l'adversaire n'en a aucune : la passe termine l'étape."""
    from engine.phase_handlers.fight_handlers import FIGHT_STEP_PASSED_KEY

    eng = engine_factory(charged=["1"])
    gs = eng.game_state

    ok, result = eng._process_squad_action(_decoded_no_target(eng, "1"))

    assert ok and result["fight_step_ended"] is True
    assert gs[FIGHT_STEP_PASSED_KEY] is True and gs["units_selected_to_fight"] == set()


def test_unit_within_5_inches_without_target_must_fight_empty(engine_factory, monkeypatch):
    """Une unité éligible à ≤ 5" d'un ennemi sans cible atteignable ne peut PAS passer : le slot
    sans cible reste le combat à vide (12.04), qui la marque « selected to fight »."""
    from engine.phase_handlers import fight_handlers as fh
    from engine.phase_handlers import shared_utils as su

    eng = engine_factory(charged=["1"])
    gs = eng.game_state
    # Ennemi « à ≤ 5" » (12.03 BEFORE MOVING) mais qu'aucun pile-in n'atteint : la cible existe
    # pour la règle de passe, pas pour le combat.
    monkeypatch.setattr(fh, "pile_in_targets_within_range", lambda _gs, _u: ["2"])
    monkeypatch.setattr(su, "fight_pile_in_plan", lambda _gs, _sid, target_ids=None: None)

    semantic = _decoded_no_target(eng, "1")
    assert semantic == {"action": "squad_fight", "squad_id": "1"}, semantic
    ok, result = eng._process_squad_action(semantic)

    assert ok and result["action"] == "squad_fight" and "fight_result" in result, result
    assert "1" in gs["units_selected_to_fight"]


def test_pass_line_is_journaled_and_read_by_the_analyzer(tmp_path: Path):
    """step.log : « Unit 1(c,r) PASSED FIGHT » ; l'analyzer la classe `fight_pass` et ne
    produit ni ligne `other` ni erreur d'alternance."""
    from ai.step_logger import StepLogger

    log = tmp_path / "step.log"
    logger = StepLogger(output_file=str(log), enabled=True, buffer_size=10)
    logger.log_action(
        unit_id="1", action_type="fight_pass", phase="fight", player=1, success=True,
        step_increment=True,
        action_details={"current_turn": 1, "reward": 0.0, "unit_with_coords": "1(100,100)"},
    )
    logger._flush_buffer()
    content = log.read_text(encoding="utf-8")
    assert "Unit 1(100,100) PASSED FIGHT" in content, content


def test_analyzer_counts_the_pass_without_alternation_error(tmp_path: Path):
    """L'analyzer range `PASSED FIGHT` en `fight_pass` — pas dans `other`, sans erreur de
    parse ; et une passe suivie d'un combat adverse ne produit aucune violation d'alternance."""
    import ai.analyzer as an
    from tests.unit.ai._fabriques import entete_step_log

    units = (
        "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
        "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
        "[10:00:00] Unit 102 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
    )
    body = (
        "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(100,100) DEPLOYED from (-1,-1) to (100,100)"
        " [R:+0.0] [MODELS: 1#0@(100,100,z0)] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(150,100) DEPLOYED from (-1,-1) to (150,100)"
        " [R:+0.0] [MODELS: 101#0@(150,100,z0)] [SUCCESS]\n"
        "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 102(158,100) DEPLOYED from (-1,-1) to (158,100)"
        " [R:+0.0] [MODELS: 102#0@(158,100,z0)] [SUCCESS]\n"
        "[10:00:02] E1 T1 P1 CHARGE : Unit 1(100,100) CHARGED Unit 101(150,100) from (100,120) to (100,100)"
        " [Roll: 8] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [MODELS: 1#0@(100,100,z0)] [SUCCESS]\n"
        "[10:00:03] E1 T1 P1 FIGHT : Unit 1(100,100) PASSED FIGHT [R:+0.0] [SUCCESS]\n"
        "[10:00:04] E1 T1 P2 FIGHT : Unit 102(158,100) FOUGHT Unit 101(150,100) with [Close Combat Weapon]"
        " - Hit 3(3+) - Wound 2(4+) - Save 1(3+) - Dmg:1HP [R:+0.0]"
        " [FIGHT_SUBPHASE:fight] [MODELS: 102#0@(158,100,z0)] [SHOOTER_MODELS: 102#0]"
        " [ALLOC_MODEL: 101#0] [SUCCESS]\n"
    )
    log = tmp_path / "step.log"
    log.write_text(entete_step_log(body, units=units))
    stats = an.parse_step_log(str(log))

    assert stats["actions_by_type"]["fight_pass"] == 1
    assert stats["actions_by_type"].get("other", 0) == 0
    assert stats["parse_errors"] == [], stats["parse_errors"]
    assert stats["fight_alternation_violations"][2] == 0


def test_human_seat_passes_through_the_manual_machine():
    """Siège humain (machine manuelle du PvP) : l'état d'attente expose `can_pass`, l'action
    `fight_pass` fait passer la main sans marquer d'unité, et elle est REFUSÉE (état rendu tel
    quel) quand une unité éligible est à ≤ 5" d'un ennemi."""
    from engine.phase_handlers.fight_handlers import (
        FIGHT_PASS_STREAK_KEY,
        fight_v11_enter_fight_step,
        fight_v11_expected_seat,
        fight_v11_start,
    )
    from tests.unit.engine._config_helpers import (
        _fall_back_base_config as _base_config,
        _fall_back_make_engine as _make_engine,
        _fall_back_unit_cfg as _unit_cfg,
    )

    def _human_engine(p2_col: int):
        # x1 : 1 case = 1" ; l'ennemi à `p2_col - 20` cases est à 20" (> 5") ou 4 (≤ 5").
        eng = _make_engine(_base_config([_unit_cfg(1, 1, 20, 20), _unit_cfg(2, 2, p2_col, 20)]))
        gs = eng.game_state
        gs["gym_training_mode"] = False
        eng.gym_training_mode = False
        gs["player_types"] = {"1": "human", "2": "human"}
        gs["current_player"] = 1
        gs["phase"] = "fight"
        gs["units_charged"] = {"1", "2"}
        fight_v11_start(gs)
        fight_v11_enter_fight_step(gs)
        return eng

    eng = _human_engine(40)
    gs = eng.game_state
    # Action sans effet (l'unité 2 n'est pas dans le pool de P1) : la machine rend son état.
    ok, state = eng.execute_semantic_action({"action": "activate_unit", "unitId": "2"})
    assert ok and state["fight_eligible_units"] == ["1"] and state["can_pass"] is True, state
    assert gs["fight_can_pass"] is True

    ok, state = eng.execute_semantic_action({"action": "fight_pass"})

    assert ok, state
    assert "1" not in gs["units_selected_to_fight"]
    assert gs[FIGHT_PASS_STREAK_KEY] == 1 and fight_v11_expected_seat(gs) == 2
    assert state["fight_eligible_units"] == ["2"] and state["can_pass"] is True
    assert any(l.get("type") == "fight_pass" and l["player"] == 1 for l in gs["action_logs"])

    # Ennemi à 4 cases (≤ 5") : la passe est refusée, l'état est rendu inchangé.
    eng = _human_engine(24)
    gs = eng.game_state
    ok, state = eng.execute_semantic_action({"action": "activate_unit", "unitId": "2"})
    assert ok and state["can_pass"] is False, state
    ok, state = eng.execute_semantic_action({"action": "fight_pass"})
    assert ok and gs[FIGHT_PASS_STREAK_KEY] == 0 and fight_v11_expected_seat(gs) == 1
    assert state["fight_eligible_units"] == ["1"]
