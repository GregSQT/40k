"""Verrou L26 — modificateurs de touche généralisés dans step.log.

Débloque les contrôles analyzer 10.06 (M/V), 17.03, 22.05, 24.29, 15.09.

Format attendu : Hit R(<base>+->_<eff>+) [<cause>]
  - HEAVY  : Hit R(3+->2+) [HEAVY]
  - COVER  : Hit R(3+->4+) [COVER]
  - POINT-BLANK : Hit R(3+->4+) [POINT-BLANK]   ← L26

Cycle rouge→vert : remplacer `hit_rule_modifier is not None` par
`hit_rule_modifier in ("HEAVY", "COVER")` dans step_logger fait passer
`test_l26_point_blank_tag` et `test_l26_point_blank_base_display` en rouge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from ai.step_logger import StepLogger


def _logger(output_file: Path) -> StepLogger:
    return StepLogger(output_file=str(output_file), enabled=True, buffer_size=50)


def _shoot_details(
    hit_rule_modifier: Optional[str] = None,
    hit_target_base: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "current_turn": 1,
        "reward": 0.0,
        "unit_id": "10",
        "unit_with_coords": "10(2,3)",
        "target_id": "20",
        "target_coords": (5, 6),
        "hit_roll": 4,
        "wound_roll": 3,
        "save_roll": 5,
        "damage_dealt": 1,
        "hit_result": "HIT",
        "wound_result": "WOUND",
        "save_result": "SAVED",
        "hit_target": 4,  # seuil effectif (après modificateur)
        "hit_target_base": hit_target_base,
        "hit_rule_modifier": hit_rule_modifier,
        "wound_target": 4,
        "save_target": 3,
        "save_skipped": False,
    }


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


# ── POINT-BLANK (L26) ─────────────────────────────────────────────────────────


def test_l26_point_blank_tag(tmp_path: Path) -> None:
    """hit_rule_modifier=POINT-BLANK → token [POINT-BLANK] dans la ligne Hit."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_details(hit_rule_modifier="POINT-BLANK", hit_target_base=3))
    content = _read(log)
    assert "[POINT-BLANK]" in content, f"Token [POINT-BLANK] absent : {content}"


def test_l26_point_blank_base_display(tmp_path: Path) -> None:
    """POINT-BLANK + hit_target_base=3, hit_target=4 → '3+->4+' affiché."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = _shoot_details(hit_rule_modifier="POINT-BLANK", hit_target_base=3)
    details["hit_target"] = 4  # seuil dégradé par le malus
    _log_shoot(logger, details)
    content = _read(log)
    assert "3+->4+" in content, f"Affichage base->eff absent : {content}"


def test_l26_heavy_still_works(tmp_path: Path) -> None:
    """Régression : HEAVY continue à afficher [HEAVY] et base+->eff+."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = _shoot_details(hit_rule_modifier="HEAVY", hit_target_base=4)
    details["hit_target"] = 3  # seuil amélioré par HEAVY
    _log_shoot(logger, details)
    content = _read(log)
    assert "[HEAVY]" in content, f"Token [HEAVY] absent : {content}"
    assert "4+->3+" in content, f"Affichage base->eff absent : {content}"


def test_l26_cover_still_works(tmp_path: Path) -> None:
    """Régression : COVER continue à afficher [COVER] et base+->eff+."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    details = _shoot_details(hit_rule_modifier="COVER", hit_target_base=3)
    details["hit_target"] = 4
    _log_shoot(logger, details)
    content = _read(log)
    assert "[COVER]" in content, f"Token [COVER] absent : {content}"
    assert "3+->4+" in content, f"Affichage base->eff absent : {content}"


def test_l26_no_modifier_no_tag(tmp_path: Path) -> None:
    """Sans modificateur → pas de token [HEAVY]/[COVER]/[POINT-BLANK] et pas de ->."""
    log = tmp_path / "step.log"
    logger = _logger(log)
    _log_shoot(logger, _shoot_details())
    content = _read(log)
    assert "[HEAVY]" not in content
    assert "[COVER]" not in content
    assert "[POINT-BLANK]" not in content
    assert "->" not in content
