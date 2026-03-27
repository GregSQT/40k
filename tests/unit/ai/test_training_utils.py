import os
from pathlib import Path

import pytest

from ai import training_utils


class DummyConfig:
    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir


def _scenario_root(tmp_path: Path, agent_key: str = "AgentX") -> Path:
    root = tmp_path / "config" / "agents" / agent_key / "scenarios"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_check_gpu_availability_returns_false_when_cuda_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(training_utils.torch.cuda, "is_available", lambda: False)
    assert training_utils.check_gpu_availability() is False


def test_check_gpu_availability_returns_true_when_cuda_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Props:
        total_memory = 8 * 1024**3

    monkeypatch.setattr(training_utils.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(training_utils.torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(training_utils.torch.cuda, "current_device", lambda: 0)
    monkeypatch.setattr(training_utils.torch.cuda, "get_device_name", lambda idx: "DummyGPU")
    monkeypatch.setattr(training_utils.torch.cuda, "get_device_properties", lambda idx: _Props())
    monkeypatch.setattr(training_utils.torch.cuda, "set_device", lambda idx: None)
    monkeypatch.setattr(training_utils.torch.version, "cuda", "12.1")
    assert training_utils.check_gpu_availability() is True


def test_benchmark_device_speed_returns_cpu_when_cuda_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(training_utils.torch.cuda, "is_available", lambda: False)
    assert training_utils.benchmark_device_speed(obs_size=8, net_arch=[32]) == ("cpu", False)


def test_benchmark_device_speed_returns_none_when_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(training_utils.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(training_utils.torch, "randn", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert training_utils.benchmark_device_speed(obs_size=8, net_arch=[32]) is None


def test_setup_imports_returns_engine_and_register_function() -> None:
    engine_cls, register_environment = training_utils.setup_imports()
    assert engine_cls.__name__ == "W40KEngine"
    assert callable(register_environment)
    assert register_environment() is None


def test_get_scenario_list_for_phase_prefers_training_dir_and_phase_patterns(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    training_dir = scenarios_root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    (training_dir / "scenario_phase1.json").write_text("{}", encoding="utf-8")
    (training_dir / "scenario_phase1-bot1.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phase1.json").write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    results = training_utils.get_scenario_list_for_phase(config, "AgentX", "phase1")

    # training/ should be preferred when present
    assert all("/training/" in path for path in results)
    assert len(results) == 2


def test_get_scenario_list_for_phase_holdout_dirs_are_used(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    holdout_regular = scenarios_root / "holdout_regular"
    holdout_hard = scenarios_root / "holdout_hard"
    holdout_regular.mkdir(parents=True, exist_ok=True)
    holdout_hard.mkdir(parents=True, exist_ok=True)
    (holdout_regular / "scenario_holdout-bot-1.json").write_text("{}", encoding="utf-8")
    (holdout_hard / "scenario_holdout-bot-2.json").write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    results = training_utils.get_scenario_list_for_phase(
        config, "AgentX", "phase_holdout", scenario_type="holdout"
    )
    assert len(results) == 2


def test_get_scenario_list_for_phase_subtype_marker_filtering(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    (scenarios_root / "scenario_phasex-bot-1.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phasex-bot-2.json").write_text("{}", encoding="utf-8")
    config = DummyConfig(str(tmp_path / "config"))

    results = training_utils.get_scenario_list_for_phase(
        config, "AgentX", "phasex", scenario_type="bot-1"
    )
    assert len(results) == 1
    assert results[0].endswith("scenario_phasex-bot-1.json")


def test_get_scenario_list_for_phase_bot_and_self_filters(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    (scenarios_root / "scenario_bot_alpha.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_self_alpha.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phasez.json").write_text("{}", encoding="utf-8")
    config = DummyConfig(str(tmp_path / "config"))

    bot_results = training_utils.get_scenario_list_for_phase(
        config, "AgentX", "phasez", scenario_type="bot"
    )
    self_results = training_utils.get_scenario_list_for_phase(
        config, "AgentX", "phasez", scenario_type="self"
    )
    assert len(bot_results) == 1 and bot_results[0].endswith("scenario_bot_alpha.json")
    assert len(self_results) == 1 and self_results[0].endswith("scenario_self_alpha.json")


def test_get_scenario_list_for_phase_returns_empty_when_agent_missing(tmp_path: Path) -> None:
    config = DummyConfig(str(tmp_path / "config"))
    assert training_utils.get_scenario_list_for_phase(config, "", "phase1") == []


def test_get_scenario_list_for_phase_training_type_uses_training_dir_only(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    training_dir = scenarios_root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    (training_dir / "scenario_phase1.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phase1-root.json").write_text("{}", encoding="utf-8")
    config = DummyConfig(str(tmp_path / "config"))

    results = training_utils.get_scenario_list_for_phase(
        config, "AgentX", "phase1", scenario_type="training"
    )
    assert len(results) == 1
    assert "/training/" in results[0]


def test_get_agent_scenario_file_exact_phase_match(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    training_dir = scenarios_root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    expected = training_dir / "scenario_phase2.json"
    expected.write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    selected = training_utils.get_agent_scenario_file(config, "AgentX", "phase2")
    assert selected == str(expected)


def test_get_agent_scenario_file_with_explicit_override(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    target = scenarios_root / "scenario_bot-3.json"
    target.write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    selected = training_utils.get_agent_scenario_file(
        config, "AgentX", "phase2", scenario_override="bot-3"
    )
    assert selected == str(target)


def test_get_agent_scenario_file_override_all_falls_back_to_phase_resolution(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    target = scenarios_root / "scenario_phase5.json"
    target.write_text("{}", encoding="utf-8")
    config = DummyConfig(str(tmp_path / "config"))
    selected = training_utils.get_agent_scenario_file(
        config, "AgentX", "phase5", scenario_override="all"
    )
    assert selected == str(target)


def test_get_agent_scenario_file_raises_on_ambiguous_exact_match(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    training_dir = scenarios_root / "training"
    training_dir.mkdir(parents=True, exist_ok=True)
    (training_dir / "scenario_phase3.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phase3.json").write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    with pytest.raises(FileNotFoundError, match=r"Ambiguous exact scenario"):
        training_utils.get_agent_scenario_file(config, "AgentX", "phase3")


def test_get_agent_scenario_file_raises_when_multiple_variants_without_override(tmp_path: Path) -> None:
    scenarios_root = _scenario_root(tmp_path)
    (scenarios_root / "scenario_phase4-bot-1.json").write_text("{}", encoding="utf-8")
    (scenarios_root / "scenario_phase4-bot-2.json").write_text("{}", encoding="utf-8")

    config = DummyConfig(str(tmp_path / "config"))
    with pytest.raises(FileNotFoundError, match=r"Multiple scenario variants found"):
        training_utils.get_agent_scenario_file(config, "AgentX", "phase4")


def test_get_agent_scenario_file_raises_when_no_file_found(tmp_path: Path) -> None:
    _scenario_root(tmp_path)
    config = DummyConfig(str(tmp_path / "config"))
    with pytest.raises(FileNotFoundError, match=r"No scenario file found"):
        training_utils.get_agent_scenario_file(config, "AgentX", "phase9")


def test_ensure_scenario_raises_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_file = tmp_path / "ai" / "training_utils.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(training_utils, "__file__", str(fake_file))

    with pytest.raises(FileNotFoundError, match=r"Missing required scenario.json file"):
        training_utils.ensure_scenario()


def test_ensure_scenario_passes_when_file_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_file = tmp_path / "ai" / "training_utils.py"
    scenario = tmp_path / "config" / "scenario.json"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    scenario.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("# stub", encoding="utf-8")
    scenario.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(training_utils, "__file__", str(fake_file))

    # no exception expected
    training_utils.ensure_scenario()
