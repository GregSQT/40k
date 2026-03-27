import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

# Some legacy imports in ai.train may be absent in current single-agent architecture.
if "ai.multi_agent_trainer" not in sys.modules:
    _stub = types.ModuleType("ai.multi_agent_trainer")
    _stub.MultiAgentTrainer = object
    sys.modules["ai.multi_agent_trainer"] = _stub

if "ai.macro_training_env" not in sys.modules:
    _stub_macro = types.ModuleType("ai.macro_training_env")
    _stub_macro.MacroTrainingWrapper = object
    _stub_macro.MacroVsBotWrapper = object
    sys.modules["ai.macro_training_env"] = _stub_macro

import ai.train as train


def test_build_training_bots_from_config() -> None:
    cfg = {
        "bot_training": {
            "ratios": {"random": 0.2, "greedy": 0.4, "defensive": 0.4},
            "greedy_randomness": 0.11,
            "defensive_randomness": 0.22,
        }
    }
    bots = train._build_training_bots_from_config(cfg)
    assert len(bots) >= 3


def test_make_learning_rate_schedule() -> None:
    const_fn = train._make_learning_rate_schedule(0.001)
    assert const_fn(1.0) == pytest.approx(0.001)

    sched = train._make_learning_rate_schedule({"initial": 0.002, "final": 0.001})
    assert sched(1.0) == pytest.approx(0.002)
    assert sched(0.0) == pytest.approx(0.001)
    with pytest.raises(ValueError, match=r"learning_rate must be float or dict"):
        train._make_learning_rate_schedule(["bad"])


def test_load_configured_unit_rule_ids(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "unit_rules.json").write_text(
        json.dumps({"a": {"id": "R_A"}, "b": {"id": "R_B"}}), encoding="utf-8"
    )
    ids = train._load_configured_unit_rule_ids(str(tmp_path))
    assert ids == {"R_A", "R_B"}


def test_scenario_has_forced_controlled_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Gsm:
        def __init__(self, game_state, unit_registry):
            _ = game_state, unit_registry

        @staticmethod
        def load_units_from_scenario(scenario_file, unit_registry):
            _ = scenario_file, unit_registry
            return {
                "units": [
                    {"id": "u1", "player": 1, "UNIT_RULES": [{"ruleId": "R_X"}]},
                    {"id": "u2", "player": 2, "UNIT_RULES": [{"ruleId": "R_Y"}]},
                ]
            }

    monkeypatch.setattr("engine.game_state.GameStateManager", _Gsm)
    assert train._scenario_has_forced_controlled_unit("s.json", object(), {"R_X"}, "p1") is True
    assert train._scenario_has_forced_controlled_unit("s.json", object(), {"R_Z"}, "p1") is False
    with pytest.raises(ValueError, match=r"controlled_player_mode must be one of"):
        train._scenario_has_forced_controlled_unit("s.json", object(), {"R_X"}, "bad")


def test_apply_unit_rule_forcing_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(train, "_load_configured_unit_rule_ids", lambda _: {"R_X"})
    monkeypatch.setattr(
        train,
        "_scenario_has_forced_controlled_unit",
        lambda scenario_path, unit_registry, configured_rule_ids, controlled_player_mode: scenario_path.endswith("forced.json"),
    )
    scenario_list = ["a_forced.json", "b.json", "b.json"]
    cfg = {
        "unit_rule_forcing": {
            "enabled": True,
            "target_controlled_episode_ratio": 0.6,
            "max_scenario_weight": 4,
        }
    }
    weighted = train._apply_unit_rule_forcing_weights(scenario_list, cfg, object(), "p1")
    assert weighted.count("a_forced.json") >= 2


def test_normalize_and_training_hard_weights() -> None:
    assert train._normalize_scenario_name("/x/scenario_alpha.json") == "alpha"
    with pytest.raises(ValueError, match=r"Scenario path must end with .json"):
        train._normalize_scenario_name("/x/alpha.txt")

    scenarios = ["scenario_alpha.json", "scenario_beta.json", "scenario_beta.json"]
    cfg = {
        "training_hard": {
            "enabled": True,
            "target_episode_ratio": 0.6,
            "max_scenario_weight": 4,
            "scenario_names": ["alpha"],
        }
    }
    weighted = train._apply_training_hard_weights(scenarios, cfg)
    assert weighted.count("scenario_alpha.json") >= 2


def test_load_rule_checker_scenarios(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "config" / "rule_checker"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    s1.write_text("{}", encoding="utf-8")
    s2.write_text("{}", encoding="utf-8")
    (manifest_dir / "manifest.json").write_text(
        json.dumps({"scenario_paths": [str(s1), str(s2)]}), encoding="utf-8"
    )
    loaded = train._load_rule_checker_scenarios(str(tmp_path))
    assert loaded == sorted([str(s1), str(s2)])


def test_build_agent_model_path_and_progress_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        train,
        "get_config_loader",
        lambda: SimpleNamespace(
            _resolve_agent_config_key=lambda key: f"{key}_resolved",
            load_config=lambda *_args, **_kwargs: {
                "progress_bar": {
                    "training_width": 10,
                    "bot_eval_width": 11,
                    "curriculum_phase_width": 12,
                    "macro_eval_width": 13,
                }
            },
        ),
    )
    path = train.build_agent_model_path("/models", "CoreAgent")
    assert path.endswith("CoreAgent_resolved/model_CoreAgent_resolved.zip")
    train._progress_bar_width_cache = None
    assert train._get_progress_bar_width("training_width") == 10


def test_tensorboard_meta_read_write_and_resolve(tmp_path: Path) -> None:
    model_path = str(tmp_path / "models" / "m.zip")
    run_dir = str(tmp_path / "tb" / "run_1")
    Path(run_dir).mkdir(parents=True, exist_ok=True)

    train._write_tensorboard_run_meta(model_path, run_dir)
    assert train._read_tensorboard_run_meta(model_path)["run_dir"] == run_dir

    exp_dir, resolved_run = train._resolve_tensorboard_run_dir(
        base_log_root=str(tmp_path / "tb"),
        training_config_name="cfg",
        agent_key="CoreAgent",
        model_path=model_path,
        new_model=False,
        append_training=True,
    )
    assert "cfg_CoreAgent" in exp_dir
    assert resolved_run == run_dir


def test_apply_torch_compile_and_param_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Policy:
        def forward(self, obs, deterministic=False, action_masks=None):
            _ = obs, deterministic, action_masks
            return "ok"

    model = SimpleNamespace(policy=_Policy(), device="cpu")
    monkeypatch.setattr(train.torch, "compile", lambda fn, mode=None: fn)
    train._apply_torch_compile(model)
    assert model.policy.forward(obs=[1], deterministic=True, action_masks=[1]) == "ok"

    assert train._parse_param_value("12") == 12
    assert train._parse_param_value("1.5") == 1.5
    assert train._parse_param_value("true") is True
    assert train._parse_param_value("abc") == "abc"

    cfg = {}
    train._apply_param_overrides(cfg, [("n_steps", "64"), ("model_params.gamma", "0.95")], log_overrides=False)
    assert cfg["model_params"]["n_steps"] == 64
    assert cfg["model_params"]["gamma"] == pytest.approx(0.95)


def test_device_benchmark_cache_and_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_file = tmp_path / "config" / ".device_benchmark.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "agent": "CoreAgent",
                "training_config": "cfg",
                "rewards_config": "rew",
                "recommendation": "GPU",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(train, "project_root", str(tmp_path))
    cached = train._read_device_benchmark_cache("CoreAgent", "cfg", "rew")
    assert cached == ("cuda", True)

    monkeypatch.setattr(train, "benchmark_device_speed", lambda obs_size, net_arch: ("cpu", False))
    assert train.resolve_device_mode(None, True, 5000, 128, [64, 64], None) == ("cpu", False)
    assert train.resolve_device_mode("CPU", True, 1) == ("cpu", False)
    with pytest.raises(ValueError, match=r"Invalid --mode value"):
        train.resolve_device_mode("BAD", True, 1)
