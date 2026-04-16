"""Tests for focus_fire_valid_target_ids_for_reward (focus fire bonus pool reuse)."""

from unittest.mock import patch

from engine.phase_handlers.shooting_handlers import focus_fire_valid_target_ids_for_reward


def test_uses_valid_target_pool_list_without_calling_build() -> None:
    shooter = {"id": 99, "valid_target_pool": ["10", "20"]}
    game_state: dict = {}

    with patch(
        "engine.phase_handlers.shooting_handlers.shooting_build_valid_target_pool"
    ) as mock_build:
        out = focus_fire_valid_target_ids_for_reward(shooter, game_state)
        assert out == ["10", "20"]
        mock_build.assert_not_called()


def test_empty_list_does_not_call_build() -> None:
    shooter = {"id": 1, "valid_target_pool": []}
    game_state: dict = {}

    with patch(
        "engine.phase_handlers.shooting_handlers.shooting_build_valid_target_pool"
    ) as mock_build:
        out = focus_fire_valid_target_ids_for_reward(shooter, game_state)
        assert out == []
        mock_build.assert_not_called()


def test_fallback_when_pool_missing_calls_build() -> None:
    shooter = {"id": "u7"}
    game_state = {"k": "v"}

    with patch(
        "engine.phase_handlers.shooting_handlers.shooting_build_valid_target_pool"
    ) as mock_build:
        mock_build.return_value = ["a"]
        out = focus_fire_valid_target_ids_for_reward(shooter, game_state)
        assert out == ["a"]
        mock_build.assert_called_once_with(game_state, "u7")


def test_fallback_when_pool_not_list_calls_build() -> None:
    shooter = {"id": "u8", "valid_target_pool": "not-a-list"}
    game_state = {"x": 1}

    with patch(
        "engine.phase_handlers.shooting_handlers.shooting_build_valid_target_pool"
    ) as mock_build:
        mock_build.return_value = ["z"]
        out = focus_fire_valid_target_ids_for_reward(shooter, game_state)
        assert out == ["z"]
        mock_build.assert_called_once_with(game_state, "u8")
