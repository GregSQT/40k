import json
from pathlib import Path

import numpy as np
import pytest

_target_selection_monitor = pytest.importorskip("ai.target_selection_monitor")
TargetSelectionMonitor = _target_selection_monitor.TargetSelectionMonitor


def test_log_selection_marks_optimal_choice() -> None:
    monitor = TargetSelectionMonitor()
    obs = np.zeros(200, dtype=float)

    # Target slot 0 valid, threat 0.2
    obs[120 + 0] = 1.0
    obs[120 + 6] = 0.2
    # Target slot 1 valid, threat 0.9 (optimal)
    obs[130 + 0] = 1.0
    obs[130 + 6] = 0.9

    monitor.log_selection(unit_id="u1", selected_action=5, available_targets=[], observation=obs)

    assert monitor.current_episode["total_count"] == 1
    assert monitor.current_episode["optimal_count"] == 1
    selection = monitor.current_episode["selections"][0]
    assert selection["unit_id"] == "u1"
    assert selection["is_optimal"] is True
    assert selection["features"]["is_valid"] == 1.0


def test_log_selection_non_optimal_and_end_episode_resets_state() -> None:
    monitor = TargetSelectionMonitor()
    obs = np.zeros(200, dtype=float)
    obs[120 + 0] = 1.0
    obs[120 + 6] = 0.8
    obs[130 + 0] = 1.0
    obs[130 + 6] = 0.9

    # action=4 -> offset 0, non-optimal (best is offset 1)
    monitor.log_selection(unit_id="u2", selected_action=4, available_targets=[], observation=obs)
    monitor.end_episode(episode_num=1, total_reward=12.5, winner=1)

    assert len(monitor.episode_selections) == 1
    ep = monitor.episode_selections[0]
    assert ep["episode"] == 1
    assert ep["selection_count"] == 1
    assert ep["optimal_rate"] == 0.0
    assert monitor.current_episode == {"selections": [], "optimal_count": 0, "total_count": 0}


def test_calculate_summary_empty_and_non_empty() -> None:
    monitor = TargetSelectionMonitor()
    assert monitor._calculate_summary() == {}

    monitor.episode_selections = [
        {"optimal_rate": 0.2},
        {"optimal_rate": 0.6},
        {"optimal_rate": 1.0},
    ]
    summary = monitor._calculate_summary()
    assert summary["total_episodes"] == 3
    assert abs(summary["overall_optimal_rate"] - 0.6) < 1e-9
    assert summary["best_rate"] == 1.0
    assert summary["worst_rate"] == 0.2


def test_save_analysis_writes_json(tmp_path: Path) -> None:
    output_file = tmp_path / "target_selection_analysis.json"
    monitor = TargetSelectionMonitor(output_file=str(output_file))
    monitor.episode_selections = [{"episode": 1, "optimal_rate": 0.5, "selection_count": 2}]
    monitor.save_analysis()

    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["episodes"][0]["episode"] == 1
    assert "summary" in data
