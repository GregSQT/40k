from collections import defaultdict
from pathlib import Path

import pytest

from ai.scenario_manager import ScenarioManager, ScenarioTemplate


def _manager_stub() -> ScenarioManager:
    manager = ScenarioManager.__new__(ScenarioManager)
    manager.available_agents = []
    manager.scenario_templates = {}
    manager.training_history = defaultdict(list)
    manager.matchup_statistics = defaultdict(dict)
    manager.current_training_cycle = 0
    manager.config = type("Cfg", (), {"config_dir": "/tmp"})()
    return manager


def test_select_scenario_template_cross_and_same_faction() -> None:
    manager = _manager_stub()
    manager.scenario_templates = {
        "cross_spacemarinea_vs_tyranidb": ScenarioTemplate(
            name="cross_spacemarinea_vs_tyranidb",
            description="x",
            board_size=(20, 20),
            agent_compositions={},
            unit_counts={},
            deployment_zones={0: [], 1: []},
            difficulty="m",
            training_focus="cross_faction",
        ),
        "mixed_balanced": ScenarioTemplate(
            name="mixed_balanced",
            description="m",
            board_size=(20, 20),
            agent_compositions={},
            unit_counts={},
            deployment_zones={0: [], 1: []},
            difficulty="m",
            training_focus="balanced",
        ),
    }
    assert manager._select_scenario_template("SpaceMarineA", "TyranidB") == "cross_spacemarinea_vs_tyranidb"
    assert manager._select_scenario_template("SpaceMarine_A", "SpaceMarine_B") == "mixed_balanced"


def test_select_scenario_template_raises_when_missing() -> None:
    manager = _manager_stub()
    manager.scenario_templates = {}
    with pytest.raises(ValueError, match=r"No cross-faction template"):
        manager._select_scenario_template("SpaceMarineA", "TyranidB")


def test_calculate_training_priority_with_history_and_cross_bonus() -> None:
    manager = _manager_stub()
    # New matchup: 1.0 + 2.0 + 0.5 cross-faction
    assert abs(manager._calculate_training_priority("SpaceMarine_A", "Tyranid_B") - 3.5) < 1e-9

    manager.training_history[("SpaceMarine_A", "Tyranid_B")] = [{"episodes": 1}] * 4
    manager.training_history[("Tyranid_B", "SpaceMarine_A")] = [{"episodes": 1}] * 1
    # total=5 => + (1 - 0.5)=0.5 then +0.5 cross-faction
    assert abs(manager._calculate_training_priority("SpaceMarine_A", "Tyranid_B") - 2.0) < 1e-9


def test_update_history_and_progress_report_and_balance() -> None:
    manager = _manager_stub()
    manager.available_agents = ["SpaceMarine_A", "Tyranid_B"]
    manager.update_training_history("SpaceMarine_A", "Tyranid_B", episodes_completed=10, win_rate=0.6, avg_reward=5.0)
    manager.update_training_history("SpaceMarine_A", "Tyranid_B", episodes_completed=20, win_rate=0.4, avg_reward=7.0)

    stats = manager.matchup_statistics[("SpaceMarine_A", "Tyranid_B")]
    assert stats["total_episodes"] == 30
    assert stats["total_sessions"] == 2
    assert abs(stats["avg_win_rate"] - 0.5) < 1e-9
    assert abs(stats["avg_reward"] - 6.0) < 1e-9

    report = manager.get_training_progress_report()
    assert report["overview"]["available_agents"] == 2
    assert "SpaceMarine_A" in report["agent_progress"]
    assert "faction_balance" in report["balance_analysis"]


def test_phase_based_training_rotation_solo_cross_full() -> None:
    manager = _manager_stub()
    manager.available_agents = ["CoreAgent", "EnemyAgent"]
    manager.scenario_templates = {
        "solo_coreagent": ScenarioTemplate(
            name="solo_coreagent",
            description="s",
            board_size=(20, 20),
            agent_compositions={"CoreAgent": ["Intercessor"], "EnemyAgent": ["Termagant"]},
            unit_counts={},
            deployment_zones={0: [(1, 1), (2, 1)], 1: [(10, 10), (11, 10)]},
            difficulty="e",
            training_focus="solo",
        ),
        "cross_1": ScenarioTemplate(
            name="cross_1",
            description="c",
            board_size=(20, 20),
            agent_compositions={"CoreAgent": ["Intercessor"], "EnemyAgent": ["Termagant"]},
            unit_counts={},
            deployment_zones={0: [(1, 1), (2, 1)], 1: [(10, 10), (11, 10)]},
            difficulty="m",
            training_focus="cross_faction",
        ),
        "new_composition_alpha": ScenarioTemplate(
            name="new_composition_alpha",
            description="f",
            board_size=(20, 20),
            agent_compositions={"CoreAgent": ["Intercessor"], "EnemyAgent": ["Termagant"]},
            unit_counts={},
            deployment_zones={0: [(1, 1), (2, 1)], 1: [(10, 10), (11, 10)]},
            difficulty="h",
            training_focus="balanced",
        ),
    }
    assert len(manager.get_phase_based_training_rotation(100, "solo")) == 1
    assert len(manager.get_phase_based_training_rotation(100, "cross_faction")) >= 1
    assert len(manager.get_phase_based_training_rotation(100, "full_composition")) >= 1


def test_generate_training_scenario_success_and_conflicts() -> None:
    manager = _manager_stub()
    manager.scenario_templates = {
        "tpl": ScenarioTemplate(
            name="tpl",
            description="d",
            board_size=(20, 20),
            agent_compositions={"A": ["Intercessor"], "B": ["Termagant"]},
            unit_counts={},
            deployment_zones={0: [(1, 1), (2, 1)], 1: [(10, 10), (11, 10)]},
            difficulty="m",
            training_focus="mixed",
        )
    }
    manager._get_timestamp = lambda: "20260101_120000"
    scenario = manager.generate_training_scenario("tpl", "A", "B")
    assert scenario["metadata"]["template"] == "tpl"
    assert scenario["metadata"]["units_generated"] == 4
    assert len(scenario["units"]) == 4

    manager.scenario_templates["tpl_conflict"] = ScenarioTemplate(
        name="tpl_conflict",
        description="d",
        board_size=(20, 20),
        agent_compositions={"A": ["Intercessor"], "B": ["Termagant"]},
        unit_counts={},
        deployment_zones={0: [(1, 1), (1, 1)], 1: [(10, 10), (11, 10)]},
        difficulty="m",
        training_focus="mixed",
    )
    with pytest.raises(ValueError, match=r"duplicate deployment positions"):
        manager.generate_training_scenario("tpl_conflict", "A", "B")


def test_generate_training_scenario_requires_template_and_agents() -> None:
    manager = _manager_stub()
    manager.scenario_templates = {
        "tpl": ScenarioTemplate(
            name="tpl",
            description="d",
            board_size=(20, 20),
            agent_compositions={"A": ["Intercessor"]},
            unit_counts={},
            deployment_zones={0: [(1, 1), (2, 1)], 1: [(10, 10), (11, 10)]},
            difficulty="m",
            training_focus="mixed",
        )
    }
    with pytest.raises(ValueError, match=r"Unknown scenario template"):
        manager.generate_training_scenario("missing", "A", "B")
    with pytest.raises(ValueError, match=r"Agent 'B' not found"):
        manager.generate_training_scenario("tpl", "A", "B")


def test_save_scenario_to_file_uses_default_path_when_missing(tmp_path: Path) -> None:
    manager = _manager_stub()
    manager.config = type("Cfg", (), {"config_dir": str(tmp_path / "config")})()
    manager._get_timestamp = lambda: "20260101_120000"
    scenario = {"metadata": {"template": "x"}, "units": []}
    out = manager.save_scenario_to_file(scenario, filepath=None)
    assert out.endswith("scenario_generated_20260101_120000.json")
    assert Path(out).exists()


def test_get_available_templates_and_template_info() -> None:
    manager = _manager_stub()
    template = ScenarioTemplate(
        name="tpl",
        description="d",
        board_size=(20, 20),
        agent_compositions={},
        unit_counts={},
        deployment_zones={0: [], 1: []},
        difficulty="m",
        training_focus="mixed",
    )
    manager.scenario_templates = {"tpl": template}
    assert manager.get_available_templates() == ["tpl"]
    assert manager.get_template_info("tpl") is template
    assert manager.get_template_info("none") is None
