"""Verrou L9 — entête Deployment: P1=<rect> P2=<rect> dans step.log.

Débloque les contrôles analyzer 03.02, 20.04, 24.09, 24.20, 24.31, 24.32.
La boîte englobante est calculée depuis deployment_pools (dict {player: [[col,row],…]}).

Cycle rouge→vert : supprimer le bloc `if deployment_pools:` dans
`ai/step_logger.log_episode_start` fait passer `test_l9_deployment_header_written` en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from ai.step_logger import StepLogger
from tests._state_invariants import unit_invariants


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _minimal_units() -> list:
    return [
        {
            **unit_invariants(),
            "id": 1, "col": 0, "row": 0, "player": 1, "HP_MAX": 1,
            "DISPLAY_NAME": "U1", "BASE_SHAPE": "round", "BASE_SIZE": 1,
            "MODEL_HEIGHT": 1.0, "unitType": "TestUnit",
        }
    ]


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


_BOARD = {"cols": 10, "rows": 10, "hex_radius": 1.0, "margin": 0.0, "inches_to_subhex": 2.0}
_RULES = {
    "engagement_zone_subhex": 10, "metric.engagement": "hex",
    "metric.ranged": "euclidean", "move.thru_ez": True,
    "move.thru_enemy": False, "move.thru_friendly": True,
}

# zones : P1 = colonnes 0-2, lignes 0-4 ; P2 = colonnes 7-9, lignes 0-4
_POOLS = {
    1: [[c, r] for c in range(3) for r in range(5)],
    2: [[c, r] for c in range(7, 10) for r in range(5)],
}


def test_l9_deployment_header_written(tmp_path: Path) -> None:
    """La ligne Deployment: doit apparaître dans step.log quand deployment_pools est fourni."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    logger.log_episode_start(
        units_data=_minimal_units(),
        board_config=_BOARD,
        run_rules=_RULES,
        deployment_pools=_POOLS,
    )
    content = _read_text(log)
    assert "Deployment:" in content, "Ligne Deployment: absente du journal"
    assert "P1=" in content
    assert "P2=" in content


def test_l9_bounding_box_correct(tmp_path: Path) -> None:
    """La boîte englobante P1=(0,0)-(2,4) et P2=(7,0)-(9,4) doit être exacte."""
    log = tmp_path / "step.log"
    _logger(log).log_episode_start(
        units_data=_minimal_units(),
        board_config=_BOARD,
        run_rules=_RULES,
        deployment_pools=_POOLS,
    )
    content = _read_text(log)
    assert "P1=(0,0)-(2,4)" in content, f"Boîte P1 incorrecte dans : {content}"
    assert "P2=(7,0)-(9,4)" in content, f"Boîte P2 incorrecte dans : {content}"


def test_l9_no_deployment_no_header(tmp_path: Path) -> None:
    """Sans deployment_pools, aucune ligne Deployment: ne doit être écrite."""
    log = tmp_path / "step.log"
    _logger(log).log_episode_start(
        units_data=_minimal_units(),
        board_config=_BOARD,
        run_rules=_RULES,
    )
    content = _read_text(log)
    assert "Deployment:" not in content
