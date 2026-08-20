"""Verrou : charge_commit_move_plan_handler pose is_pair=True dans l'action_log quand
len(target_ids) >= 2, et False (absent) pour une cible unique.

ROOT CAUSE du trou : `is_pair` était ajouté uniquement dans le chemin gym (w40k_core.py),
pas dans le chemin PvP (charge_commit_move_plan_handler). step_logger.py lit ce champ pour
émettre le token [PAIR] sur les deux chemins.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch, MagicMock


def _fake_gs(target_ids: List[str], charger_id: str = "1") -> Dict[str, Any]:
    target0 = target_ids[0] if target_ids else "2"
    unit = {
        "id": charger_id, "player": 1, "col": 5, "row": 5, "level": 0,
        "unitType": "TestUnit", "DISPLAY_NAME": "Unit 1",
        "HP_CUR": 2, "HP_MAX": 2, "VALUE": 100, "OC": 1,
        "UNIT_RULES": [], "UNIT_KEYWORDS": [],
    }
    targets_val = target_ids if len(target_ids) > 1 else target_ids[0]
    return {
        "charge_target_selections": {charger_id: targets_val},
        "charge_roll_values": {charger_id: 8},
        "_charge_initial_rolls": {},
        "squad_models": {charger_id: ["m1"]},
        "models_cache": {
            "m1": {"col": 5, "row": 5, "level": 0},
        },
        "units_cache": {
            charger_id: {"col": 5, "row": 5, "level": 0},
            target0: {"col": 6, "row": 5, "level": 0},
        },
        "unit_by_id": {charger_id: unit},
        "action_logs": [],
        "action_log_seq": 0,
        "console_logs": [],
        "turn": 1,
        "charge_activation_pool": ["999"],
    }


_HANDLERS = "engine.phase_handlers.charge_handlers"


def _call_handler(gs: Dict[str, Any], charger_id: str = "1"):
    from engine.phase_handlers.charge_handlers import charge_commit_move_plan_handler
    action = {"plan": [["m1", 6, 5, 0]]}
    with (
        patch(f"{_HANDLERS}.parse_model_plan", return_value=[("m1", 6, 5, 0)]),
        patch(f"{_HANDLERS}.get_unit_by_id", return_value=gs["unit_by_id"][charger_id]),
        patch(f"{_HANDLERS}.charge_preview_move_plan", return_value={
            "can_validate": True, "per_model": {}, "engaged_all": True, "missing_targets": [],
        }),
        patch(f"{_HANDLERS}.require_unit_position", return_value=(6, 5)),
        patch(f"{_HANDLERS}._charge_enabling_ability", return_value=(None, "", None)),
        patch(f"{_HANDLERS}._charge_fly_declared", return_value=False),
        patch(f"{_HANDLERS}.charge_record_outcome", return_value={}),
        patch(f"{_HANDLERS}._apply_charge_impact"),
        patch(f"{_HANDLERS}.charge_clear_preview"),
        patch(f"{_HANDLERS}.end_activation", return_value={"phase": "charge"}),
        patch(f"{_HANDLERS}.add_console_log"),
        patch("engine.phase_handlers.shared_utils.commit_move"),
        patch("engine.phase_handlers.shared_utils.set_unit_coordinates"),
        patch("engine.phase_handlers.movement_handlers._invalidate_all_destination_pools_after_movement"),
    ):
        return charge_commit_move_plan_handler(gs, charger_id, action)


def test_is_pair_true_for_two_targets():
    """Charge déclarée sur 2 cibles → is_pair=True dans l'action_log."""
    gs = _fake_gs(["2", "3"])
    ok, _ = _call_handler(gs)
    assert ok, "la charge doit réussir"
    last_log = gs["action_logs"][-1]
    assert last_log["is_pair"] is True, f"is_pair attendu True, got {last_log.get('is_pair')!r}"


def test_is_pair_false_for_single_target():
    """Charge déclarée sur 1 cible → is_pair absent ou False dans l'action_log."""
    gs = _fake_gs(["2"])
    ok, _ = _call_handler(gs)
    assert ok, "la charge doit réussir"
    last_log = gs["action_logs"][-1]
    assert last_log.get("is_pair") is not True, (
        f"is_pair ne doit pas être True pour une cible unique, got {last_log.get('is_pair')!r}"
    )
