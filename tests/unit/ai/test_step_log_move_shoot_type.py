"""Verrou L10 — suffixe [MOVE_TYPE:…] et [SHOOT_TYPE:…] dans step.log.

Débloque les contrôles analyzer 09.02, 09.04, 09.07, 10.02, 10.04–10.07,
12.05, 12.06, 21.02, 24.32.

Les tokens sont produits explicitement :
  - [MOVE_TYPE:normal|advance|fall_back] sur les lignes MOVED / ADVANCED / FLED
  - [SHOOT_TYPE:normal|assault|close_quarters|indirect] sur les lignes SHOT

Cycle rouge→vert : supprimer le bloc `if _move_type is not None: base_msg +=` dans
les branches "move"/"flee"/"advance" de `ai/step_logger._format_replay_style_message`
fait passer les tests move en rouge ; supprimer le bloc `if _shoot_type is not None`
fait passer les tests shoot en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from ai.step_logger import StepLogger
from tests._state_invariants import unit_invariants


# ── helpers ───────────────────────────────────────────────────────────────────

def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _base_details(current_turn: int = 1) -> Dict[str, Any]:
    return {
        "current_turn": current_turn,
        "reward": 0.0,
        "start_pos": (2, 3),
        "end_pos": (4, 5),
        "is_fly_move": False,
        "unit_with_coords": "42(4,5)",
    }


def _log_action(logger: StepLogger, action_type: str, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="42",
        action_type=action_type,
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── move type ─────────────────────────────────────────────────────────────────


def test_l10_move_normal_suffix(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = {**_base_details(), "move_type": "normal"}
    _log_action(logger, "move", details)
    assert "[MOVE_TYPE:normal]" in _read(log), "Suffixe [MOVE_TYPE:normal] absent sur MOVED"


def test_l10_advance_suffix(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = {**_base_details(), "move_type": "advance", "advance_range": 3}
    _log_action(logger, "advance", details)
    content = _read(log)
    assert "[MOVE_TYPE:advance]" in content, f"Suffixe [MOVE_TYPE:advance] absent : {content}"


def test_l10_flee_suffix(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = {**_base_details(), "move_type": "fall_back"}
    _log_action(logger, "flee", details)
    content = _read(log)
    assert "[MOVE_TYPE:fall_back]" in content, f"Suffixe [MOVE_TYPE:fall_back] absent : {content}"


def test_l10_move_no_suffix_when_no_move_type(tmp_path: Path) -> None:
    """Sans move_type dans details, aucun token [MOVE_TYPE:…] ne doit apparaître."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_action(logger, "move", _base_details())
    assert "[MOVE_TYPE:" not in _read(log)


# ── shoot type ────────────────────────────────────────────────────────────────


def _shoot_details(shoot_type: str = "normal") -> Dict[str, Any]:
    """Details minimaux pour un log_action de type 'shoot'."""
    return {
        "current_turn": 1,
        "reward": 0.0,
        "unit_with_coords": "1(2,3)",
        "target_id": "2",
        "target_coords": (5, 6),
        "weapon_name": "Bolt Rifle",
        # champs par-jet exigés par le formateur (voir required_fields dans step_logger.py)
        "hit_roll": 4,
        "hit_result": "HIT",
        "hit_target": 3,
        "wound_roll": 5,
        "wound_result": "WOUND",
        "wound_target": 4,
        "save_roll": 2,
        "save_result": "FAIL",
        "save_target": 3,
        "damage_dealt": 1,
        "shoot_type": shoot_type,
    }


def _log_shoot(logger: StepLogger, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="1",
        action_type="shoot",
        phase="shoot",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def test_l10_shoot_type_normal(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_details("normal"))
    content = _read(log)
    assert "[SHOOT_TYPE:normal]" in content, f"Suffixe [SHOOT_TYPE:normal] absent : {content}"


def test_l10_shoot_type_indirect(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_details("indirect"))
    content = _read(log)
    assert "[SHOOT_TYPE:indirect]" in content, f"Suffixe [SHOOT_TYPE:indirect] absent : {content}"


def test_l10_shoot_type_assault(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_details("assault"))
    content = _read(log)
    assert "[SHOOT_TYPE:assault]" in content, f"Suffixe [SHOOT_TYPE:assault] absent : {content}"


def test_l10_shoot_no_suffix_without_shoot_type(tmp_path: Path) -> None:
    """Sans shoot_type dans details, aucun token [SHOOT_TYPE:…] ne doit apparaître."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = _shoot_details()
    del details["shoot_type"]
    _log_shoot(logger, details)
    assert "[SHOOT_TYPE:" not in _read(log)
