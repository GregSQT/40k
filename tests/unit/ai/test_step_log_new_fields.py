"""Tests step.log L14/L19/L25/L27/L28 — champs manquants du chantier analyzer-step-log-fields.

L14 : [FIGHTS FIRST] sur ligne FOUGHT (fights_first dans details)
L19 : entête Attached: <lid>→<bid> dans log_episode_start
L25 : lignes COMMAND [WAAAGH!] et COMMAND [OATH OF MOMENT]
L27 : nom ability relance save en mêlée (save_ability_display_name)
L28 : [REROLLED:<jet initial>] sur ligne CHARGED (charge_roll_initial dans details)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from ai.step_logger import StepLogger
from tests._state_invariants import unit_invariants


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _base_combat_details(**extra: Any) -> Dict[str, Any]:
    base = {
        "unit_with_coords": "3(4,4)",
        "target_id": 8,
        "hit_roll": 5,
        "wound_roll": 4,
        "save_roll": 2,
        "damage_dealt": 1,
        "hit_result": "HIT",
        "wound_result": "WOUND",
        "save_result": "FAIL",
        "hit_target": 3,
        "wound_target": 4,
        "save_target": 3,
        "fight_subphase": "fight",
    }
    base.update(extra)
    return base


# ── L14 ─────────────────────────────────────────────────────────────────────


def test_l14_fights_first_appended_when_present() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "combat", _base_combat_details(fights_first=True)
    )
    assert "[FIGHTS FIRST]" in msg
    assert "FOUGHT" in msg


def test_l14_fights_first_absent_when_false() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "combat", _base_combat_details(fights_first=False)
    )
    assert "[FIGHTS FIRST]" not in msg


def test_l14_fights_first_absent_when_not_in_details() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(1, "combat", _base_combat_details())
    assert "[FIGHTS FIRST]" not in msg


def test_l14_fights_first_with_weapon() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "combat", _base_combat_details(fights_first=True, weapon_name="Chainsword")
    )
    assert "[FIGHTS FIRST]" in msg
    assert "Chainsword" in msg


# ── L19 ─────────────────────────────────────────────────────────────────────


def _minimal_units() -> list:
    return [
        {
            **unit_invariants(),
            "id": 1,
            "col": 0,
            "row": 0,
            "player": 1,
            "HP_MAX": 1,
            "DISPLAY_NAME": "U1",
            "BASE_SHAPE": "round",
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 1.0,
        }
    ]


def _base_log_kwargs(output_file: Path) -> dict:
    return dict(
        output_file=str(output_file),
        enabled=True,
        buffer_size=50,
    )


_BOARD_CONFIG = {
    "cols": 10, "rows": 10, "hex_radius": 1.0, "margin": 0.0, "inches_to_subhex": 2.0,
}

_RUN_RULES = {
    "engagement_zone_subhex": 10,
    "metric.engagement": "hex",
    "metric.ranged": "euclidean",
    "move.thru_ez": True,
    "move.thru_enemy": False,
    "move.thru_friendly": True,
}


def test_l19_attached_header_written(tmp_path: Path) -> None:
    logger = StepLogger(**_base_log_kwargs(tmp_path / "step.log"))
    logger.log_episode_start(
        units_data=_minimal_units(),
        attached_info={"10": "5"},
        board_config=_BOARD_CONFIG,
        run_rules=_RUN_RULES,
    )
    content = _read_text(tmp_path / "step.log")
    assert "Attached: 10→5" in content


def test_l19_multiple_attached_pairs_sorted(tmp_path: Path) -> None:
    logger = StepLogger(**_base_log_kwargs(tmp_path / "step.log"))
    logger.log_episode_start(
        units_data=_minimal_units(),
        attached_info={"20": "3", "10": "5"},
        board_config=_BOARD_CONFIG,
        run_rules=_RUN_RULES,
    )
    content = _read_text(tmp_path / "step.log")
    pos_10 = content.index("Attached: 10→5")
    pos_20 = content.index("Attached: 20→3")
    assert pos_10 < pos_20, "pairs doivent être triées par leader_id"


def test_l19_no_attached_no_header(tmp_path: Path) -> None:
    logger = StepLogger(**_base_log_kwargs(tmp_path / "step.log"))
    logger.log_episode_start(
        units_data=_minimal_units(), attached_info=None, board_config=_BOARD_CONFIG,
    )
    content = _read_text(tmp_path / "step.log")
    assert "Attached:" not in content


# ── L25 ─────────────────────────────────────────────────────────────────────


def test_l25_waaagh_call_format() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        "P1",
        "waaagh_call",
        {"current_turn": 1, "unit_with_coords": "P1"},
    )
    assert msg == "P1 COMMAND [WAAAGH!]"


def test_l25_oath_selection_format() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        "P1",
        "oath_selection",
        {"current_turn": 1, "unit_with_coords": "P1", "target_id": "7"},
    )
    assert msg == "P1 COMMAND [OATH OF MOMENT] → Unit 7"


def test_l25_oath_selection_missing_target_id_raises() -> None:
    logger = StepLogger(enabled=False)
    with pytest.raises((KeyError, Exception)):
        logger._format_replay_style_message(
            "P1",
            "oath_selection",
            {"current_turn": 1, "unit_with_coords": "P1"},
        )


# ── L27 ─────────────────────────────────────────────────────────────────────


def test_l27_save_reroll_ability_present_in_save_segment() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1,
        "combat",
        _base_combat_details(
            save_roll_initial=1,
            save_ability_display_name="Preservation Imperative",
        ),
    )
    assert "[PRESERVATION IMPERATIVE]" in msg
    assert "REROLLED:1" in msg


def test_l27_save_reroll_ability_absent_no_token() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "combat", _base_combat_details()
    )
    # Aucun token d'ability sur le segment Save si non renseigné
    assert "[PRESERVATION IMPERATIVE]" not in msg


def test_l27_save_reroll_ability_without_initial_roll() -> None:
    # L'ability est renseignée mais aucune relance effective (saveRollInitial absent)
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1,
        "combat",
        _base_combat_details(save_ability_display_name="Preservation Imperative"),
    )
    # _ability_token est présent mais _rerolled_token absent
    assert "[PRESERVATION IMPERATIVE]" in msg
    assert "REROLLED" not in msg


# ── L28 ─────────────────────────────────────────────────────────────────────


def _charge_details(**extra: Any) -> Dict[str, Any]:
    base = {
        "unit_with_coords": "2(3,3)",
        "target_id": 7,
        "target_coords": (6, 3),
        "charge_roll": 9,
        "start_pos": (3, 3),
        "end_pos": (5, 3),
    }
    base.update(extra)
    return base


def test_l28_rerolled_token_present_when_initial_roll_given() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "charge", _charge_details(charge_roll_initial=3)
    )
    assert "[Roll: 9]" in msg
    assert "[REROLLED:3]" in msg


def test_l28_rerolled_token_absent_when_no_initial_roll() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(1, "charge", _charge_details())
    assert "[Roll: 9]" in msg
    assert "REROLLED" not in msg


def test_l28_rerolled_token_absent_when_initial_roll_none() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "charge", _charge_details(charge_roll_initial=None)
    )
    assert "REROLLED" not in msg


def test_l28_rerolled_token_initial_roll_appears_in_token() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "charge", _charge_details(charge_roll=11, charge_roll_initial=5)
    )
    assert "[Roll: 11]" in msg
    assert "[REROLLED:5]" in msg


# ── ENGAGED_MODELS ───────────────────────────────────────────────────────────


def test_engaged_models_token_present_on_charged_line() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "charge", _charge_details(engaged_models_count=3, engaged_models_total=5)
    )
    assert "[ENGAGED_MODELS: 3/5]" in msg


def test_engaged_models_token_full_engagement() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1, "charge", _charge_details(engaged_models_count=5, engaged_models_total=5)
    )
    assert "[ENGAGED_MODELS: 5/5]" in msg


def test_engaged_models_token_absent_when_not_in_details() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(1, "charge", _charge_details())
    assert "ENGAGED_MODELS" not in msg


def test_engaged_models_token_after_distances_before_reward() -> None:
    logger = StepLogger(enabled=False)
    msg = logger._format_replay_style_message(
        1,
        "charge",
        _charge_details(
            engaged_models_count=2,
            engaged_models_total=4,
            reward=1.5,
        ),
    )
    eng_pos = msg.index("[ENGAGED_MODELS: 2/4]")
    reward_pos = msg.index("[R:")
    assert eng_pos < reward_pos
