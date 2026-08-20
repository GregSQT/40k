"""Verrou L24 — producteur skip dans step.log.

Le formateur StepLogger.skip existait déjà ; c'est l'entrée type="skip" dans action_logs
qui manquait, si bien que la ligne n'atteignait jamais step.log et que le contrôle #52
(§2.1 Dead unit skipping) restait inatteignable.

Chaîne exercée :
  _handle_skip_action(had_valid_destinations=False)   [movement / charge]
  → append_action_log(type="skip")
  → _flush_squad_action_logs_to_step_logger  (consommateur, pas retesté ici)

Cycle rouge→vert : commenter le bloc `append_action_log(game_state, {"type": "skip", ...})`
dans `engine/phase_handlers/movement_handlers._handle_skip_action` fait passer
`test_skip_move_producer_adds_action_log_entry` en rouge.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.movement_handlers import _handle_skip_action as _move_skip
from engine.phase_handlers.charge_handlers import _handle_skip_action as _charge_skip
from engine.phase_handlers.shared_utils import PASS, SHOOTING
from engine.phase_handlers.shooting_handlers import _handle_shooting_end_activation as _shoot_skip


def _minimal_gs(phase: str = "move") -> Dict[str, Any]:
    return {
        "turn": 1,
        "phase": phase,
        "action_logs": [],
        "action_log_seq": 0,
        "units_cache": {"42": {"col": 5, "row": 7}},
        "move_activation_pool": ["42"],
        "charge_activation_pool": ["42"],
        "charge_activation_pool_all": ["42"],
        # charge_phase_end (appelé quand le pool se vide) lit units_charged en require_key.
        "units_charged": set(),
        "units_moved": set(),
        "units_fled": set(),
    }


def _unit() -> Dict[str, Any]:
    return {"id": "42", "player": 1, "col": 5, "row": 7}


# ── move ─────────────────────────────────────────────────────────────────────


def test_skip_move_producer_adds_action_log_entry() -> None:
    """_handle_skip_action(had_valid_destinations=False) doit ajouter type='skip' à action_logs."""
    gs = _minimal_gs("move")
    _move_skip(gs, _unit(), had_valid_destinations=False)
    assert any(e.get("type") == "skip" for e in gs["action_logs"]), (
        "Aucune entrée type='skip' dans action_logs après _handle_skip_action (move, no valid dest)"
    )


def test_skip_move_entry_has_skip_reason() -> None:
    gs = _minimal_gs("move")
    _move_skip(gs, _unit(), had_valid_destinations=False)
    skip_entries = [e for e in gs["action_logs"] if e.get("type") == "skip"]
    assert len(skip_entries) == 1
    assert skip_entries[0]["skipReason"] == "no_valid_move_destinations"


def test_skip_move_entry_has_unit_coords() -> None:
    gs = _minimal_gs("move")
    _move_skip(gs, _unit(), had_valid_destinations=False)
    entry = next(e for e in gs["action_logs"] if e.get("type") == "skip")
    assert entry["col"] == 5
    assert entry["row"] == 7


def test_skip_move_wait_does_not_add_skip_entry() -> None:
    """had_valid_destinations=True doit produire un 'wait', pas un 'skip'."""
    gs = _minimal_gs("move")
    _move_skip(gs, _unit(), had_valid_destinations=True)
    assert not any(e.get("type") == "skip" for e in gs["action_logs"])


# ── charge ────────────────────────────────────────────────────────────────────


def test_skip_charge_producer_adds_action_log_entry() -> None:
    gs = _minimal_gs("charge")
    # charge_phase_end is called if pool becomes empty; we pre-clear potential side-effects
    # by leaving the pool with just our unit.
    _charge_skip(gs, _unit(), had_valid_destinations=False)
    assert any(e.get("type") == "skip" for e in gs["action_logs"]), (
        "Aucune entrée type='skip' dans action_logs après _handle_skip_action (charge, no valid dest)"
    )


def test_skip_charge_entry_has_skip_reason() -> None:
    gs = _minimal_gs("charge")
    _charge_skip(gs, _unit(), had_valid_destinations=False)
    skip_entries = [e for e in gs["action_logs"] if e.get("type") == "skip"]
    assert len(skip_entries) == 1
    assert skip_entries[0]["skipReason"] == "no_valid_charge_destinations"


# ── shoot ─────────────────────────────────────────────────────────────────────


def _minimal_shoot_gs() -> Dict[str, Any]:
    return {
        "turn": 1,
        "phase": "shoot",
        "action_logs": [],
        "action_log_seq": 0,
        "shoot_activation_pool": ["42"],
        "units_cache": {"42": {"col": 3, "row": 4}},
        "units_shot": set(),
    }


def _shoot_unit() -> Dict[str, Any]:
    return {"id": "42", "player": 1}


def test_skip_shoot_entry_has_skip_reason_no_valid_actions() -> None:
    """_handle_shooting_end_activation(skip_reason='no_valid_actions') → skipReason dans action_logs.

    Cycle rouge→vert : supprimer le paramètre `skip_reason` de `_handle_shooting_end_activation`
    ou retirer le bloc `if skip_reason is not None` fait passer ce test en rouge.
    """
    gs = _minimal_shoot_gs()
    _shoot_skip(gs, _shoot_unit(), PASS, 1, PASS, SHOOTING, 1, action_type="skip", skip_reason="no_valid_actions")
    skip_entries = [e for e in gs["action_logs"] if e.get("type") == "skip"]
    assert len(skip_entries) == 1
    assert skip_entries[0]["skipReason"] == "no_valid_actions"


def test_skip_shoot_entry_has_skip_reason_no_usable_weapons() -> None:
    """_handle_shooting_end_activation(skip_reason='no_usable_weapons') → skipReason dans action_logs."""
    gs = _minimal_shoot_gs()
    _shoot_skip(gs, _shoot_unit(), PASS, 1, PASS, SHOOTING, 1, action_type="skip", skip_reason="no_usable_weapons")
    skip_entries = [e for e in gs["action_logs"] if e.get("type") == "skip"]
    assert len(skip_entries) == 1
    assert skip_entries[0]["skipReason"] == "no_usable_weapons"


def test_skip_shoot_without_reason_has_no_skip_reason_key() -> None:
    """Sans skip_reason → pas de clé skipReason dans l'entrée action_log."""
    gs = _minimal_shoot_gs()
    _shoot_skip(gs, _shoot_unit(), PASS, 1, PASS, SHOOTING, 1, action_type="skip")
    skip_entries = [e for e in gs["action_logs"] if e.get("type") == "skip"]
    assert len(skip_entries) == 1
    assert "skipReason" not in skip_entries[0]
