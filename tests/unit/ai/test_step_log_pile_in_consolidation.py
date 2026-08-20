"""Verrou L17 — cibles pile-in et mode consolidation dans step.log.

Débloque les contrôles analyzer 12.03, 12.08.

Format attendu :
  PILED IN … [targets: M,K]
  CONSOLIDATED … [ONGOING|ENGAGING|OBJECTIVE]

Cycle rouge→vert : supprimer le bloc `if action_type in ("pile_in", …)` dans
`ai/step_logger._format_replay_style_message` fait passer les tests en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _base_details(current_turn: int = 1) -> Dict[str, Any]:
    return {
        "current_turn": current_turn,
        "reward": 0.0,
        "start_pos": (2, 3),
        "end_pos": (4, 5),
        "unit_with_coords": "10(4,5)",
    }


def _log(logger: StepLogger, action_type: str, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="10",
        action_type=action_type,
        phase="fight",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── pile-in targets ───────────────────────────────────────────────────────────


def test_l17_pile_in_targets_in_log(tmp_path: Path) -> None:
    """Pile-in avec targets → [targets: 20,30] dans la ligne PILED IN."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "pile_in", {**_base_details(), "pile_in_target_ids": ["20", "30"]})
    content = _read(log)
    assert "[targets: 20,30]" in content, f"Token [targets:] absent : {content}"


def test_l17_pile_in_no_targets_no_token(tmp_path: Path) -> None:
    """Pile-in sans pile_in_target_ids → pas de token [targets:]."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "pile_in", _base_details())
    assert "[targets:" not in _read(log)


# ── consolidation mode ────────────────────────────────────────────────────────


def test_l17_consolidation_ongoing(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "consolidation", {**_base_details(), "consolidation_mode": "ongoing"})
    content = _read(log)
    assert "[ONGOING]" in content, f"Token [ONGOING] absent : {content}"


def test_l17_consolidation_engaging(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "consolidation", {**_base_details(), "consolidation_mode": "engaging"})
    content = _read(log)
    assert "[ENGAGING]" in content, f"Token [ENGAGING] absent : {content}"


def test_l17_consolidation_objective(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "consolidation", {**_base_details(), "consolidation_mode": "objective"})
    content = _read(log)
    assert "[OBJECTIVE]" in content, f"Token [OBJECTIVE] absent : {content}"


def test_l17_consolidation_no_mode_no_token(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, "consolidation", _base_details())
    content = _read(log)
    assert "[ONGOING]" not in content
    assert "[ENGAGING]" not in content
    assert "[OBJECTIVE]" not in content
