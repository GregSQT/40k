from itertools import chain, repeat
from types import SimpleNamespace

import numpy as np
import pytest

import ai.bot_evaluation as be


class _DummyCfgLoader:
    def __init__(self, cfg):
        self._cfg = cfg

    def load_agent_training_config(self, agent_key, training_config_name):
        _ = agent_key, training_config_name
        return self._cfg


def test_load_bot_eval_params_valid_and_invalid_sum() -> None:
    cfg = {
        "callback_params": {
            "bot_eval_weights": {"random": 0.2, "greedy": 0.3, "defensive": 0.5},
            "bot_eval_randomness": {"greedy": 0.1, "defensive": 0.2},
        }
    }
    out = be._load_bot_eval_params(_DummyCfgLoader(cfg), "CoreAgent", "default")
    assert out["weights"]["defensive"] == 0.5
    assert out["randomness"]["greedy"] == 0.1

    bad_cfg = {
        "callback_params": {
            "bot_eval_weights": {"random": 0.2, "greedy": 0.2, "defensive": 0.2},
            "bot_eval_randomness": {"greedy": 0.1, "defensive": 0.2},
        }
    }
    with pytest.raises(ValueError, match=r"must sum to 1.0"):
        be._load_bot_eval_params(_DummyCfgLoader(bad_cfg), "CoreAgent", "default")


def test_scenario_name_and_metric_slug_helpers() -> None:
    name = be._scenario_name_from_file("CoreAgent", "/x/holdout_hard/CoreAgent_scenario_bot-3.json")
    assert name == "holdout_hard_bot-3"
    assert be._scenario_name_from_file("CoreAgent", "/x/training/scenario_alpha.json") == "alpha"
    assert be._scenario_metric_slug("Holdout hard bot-3") == "holdout_hard_bot_3"
    with pytest.raises(ValueError, match=r"Invalid scenario name"):
        be._scenario_metric_slug("   ")


def test_scenario_split_keys_and_scores() -> None:
    assert be._scenario_split_metric_key("training_bot-2") == "training_bot_2"
    assert be._scenario_split_metric_key("holdout_hard_bot-1") == "hard_bot_1"
    assert be._scenario_split_metric_key("holdout_regular_bot-5") == "regular_bot_5"
    assert be._scenario_split_metric_key("unknown") is None

    scores = be._compute_scenario_split_scores(
        {
            "training_bot-2": {"combined": 0.7},
            "holdout_hard_bot-1": {"combined": 0.4},
            "other": {"combined": 0.9},
        }
    )
    assert scores == {"training_bot_2": 0.7, "hard_bot_1": 0.4}


def test_filter_scenarios_from_config() -> None:
    scenario_list = [
        "/tmp/training/CoreAgent_scenario_bot-1.json",
        "/tmp/training/CoreAgent_scenario_bot-2.json",
    ]
    cfg_none = {"callback_params": {}}
    assert be._filter_scenarios_from_config(cfg_none, scenario_list, "CoreAgent") == scenario_list

    cfg_sel = {"callback_params": {"bot_eval_scenarios": ["bot-2", "bot-1"]}}
    filtered = be._filter_scenarios_from_config(cfg_sel, scenario_list, "CoreAgent")
    assert filtered[0].endswith("bot-2.json")
    assert filtered[1].endswith("bot-1.json")

    with pytest.raises(KeyError, match=r"Unknown scenario"):
        be._filter_scenarios_from_config({"callback_params": {"bot_eval_scenarios": ["missing"]}}, scenario_list, "CoreAgent")


def test_compute_holdout_split_metrics() -> None:
    training_cfg = {
        "callback_params": {
            "holdout_regular_scenarios": ["holdout_regular_bot-1"],
            "holdout_hard_scenarios": ["holdout_hard_bot-1"],
        }
    }
    scenario_scores = {
        "holdout_regular_bot-1": {"combined": 0.6},
        "holdout_hard_bot-1": {"combined": 0.4},
    }
    out = be._compute_holdout_split_metrics(training_cfg, scenario_scores, "holdout")
    assert out["holdout_regular_mean"] == 0.6
    assert out["holdout_hard_mean"] == 0.4
    assert out["holdout_overall_mean"] == 0.5
    assert be._compute_holdout_split_metrics(training_cfg, scenario_scores, "training") == {}


def test_format_elapsed_and_episode_seed_are_deterministic() -> None:
    assert be._format_elapsed(61) == "01:01"
    assert be._format_elapsed(3661) == "1:01:01"
    s1 = be._episode_seed(123, "random", 1, 2)
    s2 = be._episode_seed(123, "random", 1, 2)
    assert s1 == s2


def test_get_result_with_timeout_handles_success_timeout_and_error() -> None:
    class FutureOK:
        def result(self, timeout=None):
            _ = timeout
            return {"wins": 1}

    class FutureTimeout:
        def result(self, timeout=None):
            _ = timeout
            raise TimeoutError("x")

    class FutureErr:
        def result(self, timeout=None):
            _ = timeout
            raise RuntimeError("boom")

    task = {"bot_name": "random", "scenario_file": "/tmp/s1.json", "n_episodes": 3}
    assert be._get_result_with_timeout(FutureOK(), task)["wins"] == 1
    assert be._get_result_with_timeout(FutureTimeout(), task)["timeout"] is True
    assert "error" in be._get_result_with_timeout(FutureErr(), task)


def test_build_eval_obs_normalizer_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    model_no_env = SimpleNamespace(get_env=lambda: None)
    assert be._build_eval_obs_normalizer(model_no_env, vec_normalize_enabled=False, vec_model_path=None) is None

    # vec enabled but no live vec and no path -> explicit runtime error
    with pytest.raises(RuntimeError, match=r"VecNormalize is enabled"):
        be._build_eval_obs_normalizer(model_no_env, vec_normalize_enabled=True, vec_model_path=None)

    # worker helper: disabled flags -> none; missing path -> runtime error
    assert be._build_eval_obs_normalizer_for_worker(None, None, False, True) is None
    with pytest.raises(RuntimeError, match=r"vec_model_path not provided"):
        be._build_eval_obs_normalizer_for_worker(None, None, True, True)


def test_build_eval_obs_normalizer_uses_saved_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai.vec_normalize_utils.normalize_observation_for_inference",
        lambda obs, path: np.asarray(obs, dtype=np.float32) + 10.0,
    )
    model_no_env = SimpleNamespace(get_env=lambda: None)
    normalizer = be._build_eval_obs_normalizer(
        model_no_env,
        vec_normalize_enabled=True,
        vec_model_path="/tmp/vec.pkl",
    )
    out = normalizer(np.array([1.0, 2.0], dtype=np.float32))
    assert np.allclose(out, np.array([11.0, 12.0], dtype=np.float32))


def test_build_eval_obs_normalizer_for_worker_normalizes_and_squeezes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai.vec_normalize_utils.normalize_observation_for_inference",
        lambda obs, path: np.asarray(obs, dtype=np.float32) * 2.0,
    )
    normalizer = be._build_eval_obs_normalizer_for_worker(
        model=None,
        vec_model_path="/tmp/vec.pkl",
        vec_normalize_enabled=True,
        vec_eval_enabled=True,
    )
    out = normalizer(np.array([3.0, 4.0], dtype=np.float32))
    assert np.allclose(out, np.array([6.0, 8.0], dtype=np.float32))


def test_eval_worker_init_loads_model_and_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_model = object()
    monkeypatch.setattr("sb3_contrib.MaskablePPO.load", lambda model_path, device=None: loaded_model)
    monkeypatch.setattr(
        be,
        "_build_eval_obs_normalizer_for_worker",
        lambda model, vec_model_path, vec_normalize_enabled, vec_eval_enabled: (
            lambda obs: np.asarray(obs, dtype=np.float32)
        ),
    )

    be._eval_worker_init(
        model_path="/tmp/model.zip",
        worker_model_device="cpu",
        vec_model_path="/tmp/vec.pkl",
        vec_normalize_enabled=True,
        vec_eval_enabled=True,
        training_config_name="suite",
        rewards_config_name="CoreAgent",
        controlled_agent="CoreAgent",
        base_agent_key="CoreAgent",
    )
    assert be._worker_model is loaded_model
    assert callable(be._worker_obs_normalizer)


def test_eval_worker_task_counts_outcomes_and_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyModel:
        def predict(self, obs, action_masks=None, deterministic=True):
            _ = obs, action_masks, deterministic
            return np.array([1], dtype=np.int64), None

    class _DummyEnv:
        def __init__(self):
            self.engine = SimpleNamespace(get_action_mask=lambda: [True, False])
            self._episode = -1
            self._closed = False
            self._winners = [0, -1, 1]

        def reset(self, seed=None):
            _ = seed
            self._episode += 1
            return np.array([0.0, 1.0], dtype=np.float32), {}

        def step(self, action):
            _ = action
            return (
                np.array([0.5, 0.5], dtype=np.float32),
                0.0,
                True,
                False,
                {"winner": self._winners[self._episode], "controlled_player": 0},
            )

        def get_shoot_stats(self):
            return {"acc": 0.5}

        def close(self):
            self._closed = True

    be._worker_model = _DummyModel()
    be._worker_obs_normalizer = lambda obs: np.asarray(obs, dtype=np.float32)
    monkeypatch.setattr(be, "_create_eval_env", lambda **kwargs: _DummyEnv())

    progress = {"n": 0}
    task = {
        "bot_name": "random",
        "bot_type": "random",
        "randomness_config": {},
        "scenario_file": "/tmp/scenario.json",
        "scenario_name": "training_bot-1",
        "n_episodes": 3,
        "base_seed": 123,
        "scenario_index": 0,
        "config_params": {
            "training_config_name": "suite",
            "rewards_config_name": "CoreAgent",
            "controlled_agent": "CoreAgent",
            "base_agent_key": "CoreAgent",
            "debug_mode": False,
            "agent_seat_mode": "fixed",
            "agent_seat_seed": 42,
        },
    }
    result = be._eval_worker_task(task, progress_callback=lambda: progress.__setitem__("n", progress["n"] + 1))
    assert result["wins"] == 1
    assert result["draws"] == 1
    assert result["losses"] == 1
    assert result["shoot_stats"]["acc"] == 0.5
    assert progress["n"] == 3


def test_eval_worker_task_requires_worker_init() -> None:
    be._worker_model = None
    with pytest.raises(RuntimeError, match=r"Worker not initialized"):
        be._eval_worker_task({"config_params": {}})


def test_create_eval_env_wires_random_and_greedy_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {"engine_kwargs": None, "bot_randomness": None, "random_bot": 0, "greedy_bot": 0}

    class _DummyEngine:
        def __init__(self, **kwargs):
            created["engine_kwargs"] = kwargs

    class _DummyRandomBot:
        def __init__(self):
            created["random_bot"] += 1

    class _DummyGreedyBot:
        def __init__(self, randomness):
            created["greedy_bot"] += 1
            created["bot_randomness"] = randomness

    class _DummyDefensiveBot:
        def __init__(self, randomness):
            _ = randomness

    class _DummyBotControlledEnv:
        def __init__(self, masked_env, bot, unit_registry, agent_seat_mode, global_seed, env_rank):
            self.masked_env = masked_env
            self.bot = bot
            self.unit_registry = unit_registry
            self.agent_seat_mode = agent_seat_mode
            self.global_seed = global_seed
            self.env_rank = env_rank

    monkeypatch.setattr("ai.evaluation_bots.RandomBot", _DummyRandomBot)
    monkeypatch.setattr("ai.evaluation_bots.GreedyBot", _DummyGreedyBot)
    monkeypatch.setattr("ai.evaluation_bots.DefensiveBot", _DummyDefensiveBot)
    monkeypatch.setattr("ai.training_utils.setup_imports", lambda: (_DummyEngine, None))
    monkeypatch.setattr("ai.env_wrappers.BotControlledEnv", _DummyBotControlledEnv)
    monkeypatch.setattr("sb3_contrib.common.wrappers.ActionMasker", lambda env, fn: ("masked", env, fn))
    monkeypatch.setattr("ai.unit_registry.UnitRegistry", lambda: "registry")

    env_random = be._create_eval_env(
        bot_name="random",
        bot_type="random",
        randomness_config={"greedy": 0.3},
        scenario_file="/tmp/scenario.json",
        training_config_name="suite",
        rewards_config_name="CoreAgent",
        controlled_agent="CoreAgent",
        base_agent_key="CoreAgent",
        debug_mode=False,
        agent_seat_mode="fixed",
        agent_seat_seed=7,
    )
    assert created["random_bot"] == 1
    assert env_random.agent_seat_mode == "fixed"

    be._create_eval_env(
        bot_name="greedy",
        bot_type="greedy",
        randomness_config={"greedy": 0.42},
        scenario_file="/tmp/scenario.json",
        training_config_name="suite",
        rewards_config_name="CoreAgent",
        controlled_agent="CoreAgent",
        base_agent_key="CoreAgent",
        debug_mode=False,
        agent_seat_mode="fixed",
        agent_seat_seed=7,
    )
    assert created["greedy_bot"] == 1
    assert abs(created["bot_randomness"] - 0.42) < 1e-9
    assert created["engine_kwargs"]["scenario_file"] == "/tmp/scenario.json"


def test_eval_worker_task_attaches_step_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyModel:
        def predict(self, obs, action_masks=None, deterministic=True):
            _ = obs, action_masks, deterministic
            return np.array([0], dtype=np.int64), None

    class _DummyEnv:
        def __init__(self):
            self.engine = SimpleNamespace(get_action_mask=lambda: [True], step_logger=None)

        def reset(self, seed=None):
            _ = seed
            return np.array([0.0], dtype=np.float32), {}

        def step(self, action):
            _ = action
            return np.array([0.0], dtype=np.float32), 0.0, True, False, {"winner": 0, "controlled_player": 0}

        def close(self):
            return None

    env = _DummyEnv()
    be._worker_model = _DummyModel()
    be._worker_obs_normalizer = None
    monkeypatch.setattr(be, "_create_eval_env", lambda **kwargs: env)
    marker_logger = object()
    result = be._eval_worker_task(
        {
            "bot_name": "random",
            "bot_type": "random",
            "randomness_config": {},
            "scenario_file": "/tmp/scenario.json",
            "scenario_name": "training_bot-1",
            "n_episodes": 1,
            "base_seed": 1,
            "scenario_index": 0,
            "config_params": {
                "training_config_name": "suite",
                "rewards_config_name": "CoreAgent",
                "controlled_agent": "CoreAgent",
                "base_agent_key": "CoreAgent",
                "debug_mode": False,
                "agent_seat_mode": "fixed",
                "agent_seat_seed": 7,
                "step_logger": marker_logger,
            },
        }
    )
    assert env.engine.step_logger is marker_logger
    assert result["wins"] == 1


def test_collect_parallel_results_with_timeouts_aborts_pool_on_hung_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FutureDone:
        def result(self, timeout=None):
            _ = timeout
            return {
                "wins": 1,
                "losses": 0,
                "draws": 0,
                "failed_episodes": 0,
                "bot_name": "random",
                "scenario_name": "training_bot-1",
            }

    class _FutureHung:
        pass

    done_future = _FutureDone()
    hung_future = _FutureHung()

    wait_calls = {"n": 0}

    def _fake_wait(pending, timeout=None, return_when=None):
        _ = timeout, return_when
        wait_calls["n"] += 1
        if wait_calls["n"] == 1:
            return {done_future}, {hung_future}
        return set(), {hung_future}

    monotonic_values = chain([0.0, 2.0], repeat(2.0))  # keep returning timed-out clock value
    monkeypatch.setattr(be, "wait", _fake_wait)
    monkeypatch.setattr(be.time, "monotonic", lambda: next(monotonic_values))

    force_called = {"v": False}
    monkeypatch.setattr(be, "_force_terminate_process_pool", lambda pool: force_called.__setitem__("v", True))

    task_map = {
        done_future: {"bot_name": "random", "scenario_name": "training_bot-1", "scenario_file": "/tmp/a.json", "n_episodes": 1},
        hung_future: {"bot_name": "greedy", "scenario_file": "/tmp/hung.json", "n_episodes": 3},
    }

    out = be._collect_parallel_results_with_timeouts(
        pool=object(),
        future_to_task=task_map,
        task_timeout_seconds=1,
    )

    assert force_called["v"] is True
    assert any(r.get("bot_name") == "random" and r.get("wins") == 1 for r in out)
    timed_out = [r for r in out if r.get("bot_name") == "greedy" and r.get("timeout") is True]
    assert len(timed_out) == 1
    assert timed_out[0]["failed_episodes"] == 3


def test_collect_parallel_results_with_timeouts_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match=r"must be > 0"):
        be._collect_parallel_results_with_timeouts(
            pool=object(),
            future_to_task={},
            task_timeout_seconds=0,
        )
