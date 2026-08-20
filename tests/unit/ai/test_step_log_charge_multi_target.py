"""Verrou L16 — cibles de charge multiples dans step.log.

Débloque le contrôle analyzer 11.04.

Format attendu : "CHARGED Unit M(c1,r1),Unit K(c2,r2) from … [Roll: N]"
quand all_target_ids contient plusieurs entrées.

Cycle rouge→vert : supprimer le bloc `if all_target_ids and len(all_target_ids) > 1`
dans `ai/step_logger._format_replay_style_message` (branche "charge") fait passer
`test_l16_charged_two_targets_in_log` en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _charge_details(
    all_target_ids: List[str],
    all_target_coords: List[List[int]],
) -> Dict[str, Any]:
    return {
        "current_turn": 1,
        "reward": 0.0,
        "start_pos": (0, 0),
        "end_pos": (1, 2),
        "is_fly_move": False,
        "unit_with_coords": "10(1,2)",
        # cible primaire (fallback si all_target_ids absent / mono)
        "target_id": all_target_ids[0],
        "target_coords": tuple(all_target_coords[0]),
        # L16
        "all_target_ids": all_target_ids,
        "all_target_coords": all_target_coords,
        "charge_roll": 8,
        "charge_failed_reason": None,
    }


def _log_charge(logger: StepLogger, details: Dict[str, Any]) -> None:
    logger.log_action(
        unit_id="10",
        action_type="charge",
        phase="charge",
        player=1,
        success=True,
        step_increment=True,
        action_details=details,
    )
    logger._flush_buffer()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── multi-cibles ──────────────────────────────────────────────────────────────


def test_l16_charged_two_targets_in_log(tmp_path: Path) -> None:
    """Deux cibles → la ligne CHARGED doit nommer les deux : Unit A(…),Unit B(…)."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_charge(logger, _charge_details(
        all_target_ids=["20", "30"],
        all_target_coords=[[5, 3], [7, 4]],
    ))
    content = _read(log)
    assert "Unit 20(5,3)" in content, f"Première cible absente : {content}"
    assert "Unit 30(7,4)" in content, f"Deuxième cible absente : {content}"
    assert "Unit 20(5,3),Unit 30(7,4)" in content, f"Format multi-cibles incorrect : {content}"


def test_l16_single_target_unchanged(tmp_path: Path) -> None:
    """Cible unique → le format habituel Unit M(c,r) est préservé."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_charge(logger, _charge_details(
        all_target_ids=["20"],
        all_target_coords=[[5, 3]],
    ))
    content = _read(log)
    assert "Unit 20(5,3)" in content
    # pas de virgule séparant deux cibles
    assert "Unit 20(5,3),Unit" not in content


def test_l16_no_all_target_ids_uses_primary(tmp_path: Path) -> None:
    """Sans all_target_ids, la ligne CHARGED doit utiliser target_id + target_coords."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = {
        "current_turn": 1,
        "reward": 0.0,
        "start_pos": (0, 0),
        "end_pos": (1, 2),
        "is_fly_move": False,
        "unit_with_coords": "10(1,2)",
        "target_id": "20",
        "target_coords": (5, 3),
        "charge_roll": 8,
    }
    _log_charge(logger, details)
    content = _read(log)
    assert "Unit 20(5,3)" in content
