"""Verrou L15 — compte d'armes HAZARDOUS et jets dans step.log.

Débloque le contrôle analyzer 24.15.

Format attendu :
  SUFFERS N Mortal Wounds [HAZARDOUS:3] Roll:4,1,6 [ALLOC_MODEL: ...]
  SUFFERS 0 Mortal Wounds [HAZARDOUS:2] Roll:3,5 [NO ALLOC]

Cycle rouge→vert : supprimer le bloc `# L15` dans `step_logger._format_replay_style_message`
(branche "hazardous") fait passer `test_l15_hazardous_count_tag` et `test_l15_hazardous_dice`
en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _hazard_details(
    mortal_wounds: int = 2,
    hazard_context: str = "Hazardous",
    weapon_count: Optional[int] = None,
    dice_rolls: Optional[List[int]] = None,
    alloc_model_id: Optional[str] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "current_turn": 1,
        "reward": 0.0,
        "unit_with_coords": "10(2,3)",
        "hazardous_mortal_wounds": mortal_wounds,
        "hazard_context": hazard_context,
    }
    if weapon_count is not None:
        d["hazardous_weapon_count"] = weapon_count
    if dice_rolls is not None:
        d["hazardous_dice_rolls"] = dice_rolls
    if mortal_wounds > 0:
        d["target_model_id"] = alloc_model_id or "model-1"
    return d


def _log(logger: StepLogger, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="10",
        action_type="hazardous",
        phase="shoot",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── L15 : compte d'armes ──────────────────────────────────────────────────────


def test_l15_hazardous_count_tag(tmp_path: Path) -> None:
    """hazardous_weapon_count=3 → [HAZARDOUS:3] dans la ligne SUFFERS."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _hazard_details(weapon_count=3, dice_rolls=[4, 1, 6]))
    content = _read(log)
    assert "[HAZARDOUS:3]" in content, f"Token [HAZARDOUS:3] absent : {content}"


def test_l15_hazardous_dice(tmp_path: Path) -> None:
    """dice_rolls=[4,1,6] → Roll:4,1,6 dans la ligne SUFFERS."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _hazard_details(weapon_count=3, dice_rolls=[4, 1, 6]))
    content = _read(log)
    assert "Roll:4,1,6" in content, f"Token Roll:4,1,6 absent : {content}"


def test_l15_no_count_fallback(tmp_path: Path) -> None:
    """Sans weapon_count → [HAZARDOUS] générique (compatibilité anciens logs)."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _hazard_details())
    content = _read(log)
    assert "[HAZARDOUS]" in content, f"Token [HAZARDOUS] absent : {content}"
    assert "Roll:" not in content


def test_l15_no_alloc_zero_wounds(tmp_path: Path) -> None:
    """0 mortal wounds + weapon_count → [HAZARDOUS:2] Roll:3,5 [NO ALLOC]."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _hazard_details(mortal_wounds=0, weapon_count=2, dice_rolls=[3, 5]))
    content = _read(log)
    assert "[HAZARDOUS:2]" in content, f"Token [HAZARDOUS:2] absent : {content}"
    assert "Roll:3,5" in content, f"Token Roll:3,5 absent : {content}"
    assert "[NO ALLOC]" in content


def test_l15_desperate_escape_no_count(tmp_path: Path) -> None:
    """Desperate Escape → [DESPERATE ESCAPE] et pas de Roll: ni [HAZARDOUS:]."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log(logger, _hazard_details(hazard_context="Desperate Escape"))
    content = _read(log)
    assert "[DESPERATE ESCAPE]" in content, f"Token [DESPERATE ESCAPE] absent : {content}"
    assert "[HAZARDOUS" not in content
    assert "Roll:" not in content
