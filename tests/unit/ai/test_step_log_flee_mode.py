"""Verrou L11 — mode de fall-back et jets de hazard dans step.log.

Débloque les contrôles analyzer 09.07, 06.03.

Format attendu :
  FLED … [DESPERATE ESCAPE] Hazard:3,1,4
  FLED … [ORDERED RETREAT]

Cycle rouge→vert : supprimer le bloc `# L11` dans
`ai/step_logger._format_replay_style_message` (branche "flee") fait passer les tests en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _flee_details(
    flee_mode: Optional[str] = None,
    desperate_escape_rolls: Optional[List[int]] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "current_turn": 1,
        "reward": 0.0,
        "start_pos": (2, 3),
        "end_pos": (4, 5),
        "move_type": "fall_back",
        "unit_with_coords": "10(4,5)",
    }
    if flee_mode is not None:
        d["flee_mode"] = flee_mode
    if desperate_escape_rolls is not None:
        d["desperate_escape_rolls"] = desperate_escape_rolls
    return d


def _log(logger: StepLogger, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="10",
        action_type="flee",
        phase="move",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── desperate escape ──────────────────────────────────────────────────────────


def test_l11_desperate_escape_tag(tmp_path: Path) -> None:
    """flee_mode=desperate_escape → [DESPERATE ESCAPE] dans la ligne FLED."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details(flee_mode="desperate_escape"))
    content = _read(log)
    assert "[DESPERATE ESCAPE]" in content, f"Token absent : {content}"


def test_l11_desperate_escape_hazard_rolls(tmp_path: Path) -> None:
    """Jets présents → Hazard:3,1,4 dans la ligne FLED."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details(flee_mode="desperate_escape", desperate_escape_rolls=[3, 1, 4]))
    content = _read(log)
    assert "Hazard:3,1,4" in content, f"Token Hazard absent : {content}"


def test_l11_no_rolls_no_hazard_token(tmp_path: Path) -> None:
    """desperate_escape sans rolls → pas de token Hazard."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details(flee_mode="desperate_escape"))
    assert "Hazard:" not in _read(log)


# ── ordered retreat ───────────────────────────────────────────────────────────


def test_l11_ordered_retreat_tag(tmp_path: Path) -> None:
    """flee_mode=ordered_retreat → [ORDERED RETREAT] dans la ligne FLED."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details(flee_mode="ordered_retreat"))
    content = _read(log)
    assert "[ORDERED RETREAT]" in content, f"Token absent : {content}"


def test_l11_ordered_retreat_no_hazard_token(tmp_path: Path) -> None:
    """ordered_retreat → pas de token Hazard."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details(flee_mode="ordered_retreat"))
    assert "Hazard:" not in _read(log)


def test_l11_no_flee_mode_no_tokens(tmp_path: Path) -> None:
    """Sans flee_mode → ni [DESPERATE ESCAPE] ni [ORDERED RETREAT]."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _flee_details())
    content = _read(log)
    assert "[DESPERATE ESCAPE]" not in content
    assert "[ORDERED RETREAT]" not in content
