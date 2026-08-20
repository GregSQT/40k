"""Verrou L12 — jets Feel No Pain dans step.log.

Débloque le contrôle analyzer 24.12.

Format attendu : Dmg:NHP [FNP:saves/seuil+ ×tentatives]
  ex : Dmg:3HP [FNP:2/5+ ×5] = 3 HP perdus, 2 saves sur 5+ tentés 5 fois.

Cycle rouge→vert : supprimer le bloc `# L12` dans `_save_segments`
fait passer `test_l12_fnp_tag_in_log` en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _shoot_fail_details(
    fnp_saves: Optional[int] = None,
    fnp_attempts: Optional[int] = None,
    fnp_threshold: Optional[int] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "current_turn": 1,
        "reward": 0.0,
        "unit_id": "10",
        "unit_with_coords": "10(2,3)",
        "target_id": "20",
        "target_coords": (5, 6),
        "hit_roll": 4,
        "wound_roll": 3,
        "save_roll": 2,
        "damage_dealt": 3,   # post-FNP
        "hit_result": "HIT",
        "wound_result": "WOUND",
        "save_result": "FAIL",
        "hit_target": 3,
        "hit_target_base": None,
        "hit_rule_modifier": None,
        "wound_target": 4,
        "save_target": 3,
        "save_skipped": False,
    }
    if fnp_saves is not None:
        d["fnp_saves"] = fnp_saves
        d["fnp_attempts"] = fnp_attempts
        d["fnp_threshold"] = fnp_threshold
    return d


def _log_shoot(logger: StepLogger, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="10",
        action_type="shoot",
        phase="shoot",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_l12_fnp_tag_in_log(tmp_path: Path) -> None:
    """FNP présent (2 saves sur 5, seuil 5+) → [FNP:2/5+ ×5] dans Dmg."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_fail_details(fnp_saves=2, fnp_attempts=5, fnp_threshold=5))
    content = _read(log)
    assert "[FNP:2/5+ ×5]" in content, f"Token FNP absent : {content}"


def test_l12_fnp_zero_saves(tmp_path: Path) -> None:
    """0 saves FNP → [FNP:0/6+ ×3] présent (information utile : 0 sur 6+)."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_fail_details(fnp_saves=0, fnp_attempts=3, fnp_threshold=6))
    content = _read(log)
    assert "[FNP:0/6+ ×3]" in content, f"Token FNP absent : {content}"


def test_l12_no_fnp_no_tag(tmp_path: Path) -> None:
    """Sans FNP → pas de token [FNP:] dans la ligne."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_fail_details())
    assert "[FNP:" not in _read(log)


def test_l12_fnp_zero_attempts_still_tagged(tmp_path: Path) -> None:
    """fnp_attempts=0 → le token [FNP:0/5+ ×0] doit quand même apparaître.

    Cycle rouge→vert : remplacer `fnp_attempts is not None` par `fnp_attempts`
    (garde truthiness) dans `_save_segments` fait passer ce test en rouge.
    """
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_fail_details(fnp_saves=0, fnp_attempts=0, fnp_threshold=5))
    content = _read(log)
    assert "[FNP:0/5+ ×0]" in content, f"Token FNP absent avec attempts=0 : {content}"


def test_l12_fnp_save_success_no_tag(tmp_path: Path) -> None:
    """Save réussie (SAVED) → pas de segment Dmg, donc pas de [FNP:]."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = _shoot_fail_details(fnp_saves=1, fnp_attempts=2, fnp_threshold=5)
    details["save_result"] = "SAVED"
    _log_shoot(logger, details)
    content = _read(log)
    assert "[FNP:" not in content
