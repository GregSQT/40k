"""Impact de charge attribué par le défenseur HUMAIN sur la DERNIÈRE charge de la phase : la
reprise (`_resume_after_hazard`, origine `charge`) rend le résultat de charge gardé, qui porte
`phase_complete` / `next_phase = fight` — et cette transition doit être EXÉCUTÉE.

Les handlers hazard sortaient de `_process_semantic_action` avant la cascade de phases : le
résultat annonçait la fin de la phase de charge sans que le moteur la quitte, et le client
n'envoie pas d'`advance_phase` depuis la charge → partie figée en `charge`, pool vide.

Chemin exercé sur un MOTEUR RÉEL, par `execute_semantic_action` (point d'entrée du frontend) :
  queue_mortal_wounds (impact) → _settle_charge_mortal_wounds → attente du défenseur humain
  → squad_hazard_allocate_model → _resume_after_hazard → cascade → phase `fight`.
"""
from __future__ import annotations

from typing import Any, Dict

from engine.constants import (
    MORTAL_WOUND_QUEUE_KEY, PENDING_HAZARD_ALLOCATION_KEY, PENDING_HAZARD_RESUME_RESULT_KEY,
)
from engine.agent_decision import clear_pending_agent_decision
from engine.game_utils import require_unit_by_id
from engine.phase_handlers.charge_handlers import _settle_charge_mortal_wounds, charge_phase_end
from engine.phase_handlers.shared_utils import queue_mortal_wounds
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import (
    _fall_back_base_config as _base_config,
    _fall_back_make_engine as _make_engine,
    _fall_back_unit_cfg as _unit_cfg,
)


def _two_model_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    base = _unit_cfg(uid, player, col, row)
    base["HP_CUR"] = 3
    base["HP_MAX"] = 3
    base["models"] = [
        {"col": col, "row": row, "VALUE": 50},
        {"col": col + 1, "row": row, "VALUE": 50},
    ]
    return base


def _engine_pvp_charge() -> W40KEngine:
    """Chargeur 1 (P1) au contact de l'escouade 2 (P2 humain, deux figurines intactes → choix
    06.02 réel), en phase de charge, pool de charge vide (la charge vient d'être commise)."""
    eng = _make_engine(_base_config([
        _unit_cfg(1, 1, 20, 20),
        _two_model_cfg(2, 2, 21, 20),
    ]))
    gs = eng.game_state
    gs["gym_training_mode"] = False
    clear_pending_agent_decision(gs)
    gs["player_types"] = {"1": "human", "2": "human"}
    gs["current_mode_code"] = "pvp"
    eng.current_mode_code = "pvp"
    gs["current_player"] = 1
    gs["phase"] = "charge"
    gs["charge_activation_pool"] = []
    gs["units_charged"] = {"1"}
    return eng


def test_la_derniere_charge_attribuee_par_le_defenseur_humain_passe_en_phase_fight():
    eng = _engine_pvp_charge()
    gs = eng.game_state
    unit = require_unit_by_id(gs, "1")

    charge_result: Dict[str, Any] = {"action": "charge", "unitId": "1", "charge_succeeded": True}
    charge_result.update(charge_phase_end(gs))
    assert charge_result["phase_complete"] is True and charge_result["next_phase"] == "fight"
    queue_mortal_wounds(
        gs, "2", 1, {"type": "charge_impact", "chargeImpactDetails": []},
        details_key="chargeImpactDetails",
    )

    ok, wait = _settle_charge_mortal_wounds(gs, unit, charge_result)

    assert ok is True and wait["waiting_for_player"] is True
    assert wait["action"] == "squad_hazard_manual_alloc"
    assert gs["hazard_origin"] == "charge"
    assert gs[PENDING_HAZARD_RESUME_RESULT_KEY] is charge_result
    assert gs["phase"] == "charge"

    ok, result = eng.execute_semantic_action(
        {"action": "squad_hazard_allocate_model", "unitId": "2", "modelId": "2#0"}
    )

    assert ok is True, result
    assert gs["models_cache"]["2#0"]["HP_CUR"] == 2
    assert PENDING_HAZARD_ALLOCATION_KEY not in gs and MORTAL_WOUND_QUEUE_KEY not in gs
    assert "hazard_origin" not in gs and PENDING_HAZARD_RESUME_RESULT_KEY not in gs
    assert result["charge_succeeded"] is True and result["next_phase"] == "fight"
    assert gs["phase"] == "fight", (
        f"phase {gs['phase']!r} : la transition annoncée par le résultat de charge n'a pas été "
        "exécutée — le résultat de la reprise hazard n'a pas traversé la cascade"
    )
