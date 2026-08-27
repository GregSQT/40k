from collections import deque
from concurrent.futures import ProcessPoolExecutor
from itertools import chain, repeat
from types import SimpleNamespace
from typing import Any, List, Optional, cast

import numpy as np
import pytest

import ai.bot_evaluation as be
from shared.data_validation import require_present


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

    with pytest.raises(ValueError, match=r"doublons"):
        be._filter_scenarios_from_config({"callback_params": {"bot_eval_scenarios": ["bot-1", "bot-1"]}}, scenario_list, "CoreAgent")


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


def test_build_eval_obs_normalizer_for_worker_branches() -> None:
    # worker helper: disabled flags -> none; missing path -> runtime error
    assert be._build_eval_obs_normalizer_for_worker(None, None, False, True) is None
    with pytest.raises(RuntimeError, match=r"model_path not provided"):
        be._build_eval_obs_normalizer_for_worker(None, None, True, True)


def test_build_eval_obs_normalizer_for_worker_normalizes_and_squeezes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai.vec_normalize_utils.build_snapshot_normalizer",
        lambda snapshot_path, vec_normalize_enabled, vec_normalize_eval_enabled: (
            lambda obs: np.asarray(obs, dtype=np.float32) * 2.0
        ),
    )
    normalizer = be._build_eval_obs_normalizer_for_worker(
        model=None,
        model_path="/tmp/model.zip",
        vec_normalize_enabled=True,
        vec_eval_enabled=True,
    )
    out = require_present(normalizer, "normalizer")(np.array([3.0, 4.0], dtype=np.float32))
    assert np.allclose(out, np.array([6.0, 8.0], dtype=np.float32))


def _patch_load_model_deps(monkeypatch: pytest.MonkeyPatch):
    """Patch commun pour les tests de _eval_worker_load_model_if_needed."""
    loaded_model = object()
    monkeypatch.setattr("sb3_contrib.MaskablePPO.load", lambda model_path, device=None: loaded_model)
    seen_paths: List[str] = []
    monkeypatch.setattr(
        be,
        "_build_eval_obs_normalizer_for_worker",
        lambda model, model_path, vec_normalize_enabled, vec_eval_enabled: (
            seen_paths.append(model_path) or (lambda obs: np.asarray(obs, dtype=np.float32))
        ),
    )
    return loaded_model, seen_paths


def test_eval_worker_init_clears_model_and_sets_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """_eval_worker_init réinitialise les globals sans charger le modèle (4.2 lazy load)."""
    be._worker_model = object()  # simule un modèle résiduel
    be._eval_worker_init(
        vec_normalize_enabled=True,
        vec_eval_enabled=False,
        training_config_name="suite",
        rewards_config_name="CoreAgent",
        controlled_agent="CoreAgent",
        base_agent_key="CoreAgent",
    )
    assert be._worker_model is None
    assert be._worker_model_version_key is None
    assert be._worker_vec_normalize_enabled is True
    assert be._worker_vec_eval_enabled is False


def test_load_model_if_needed_loads_model_and_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """_eval_worker_load_model_if_needed charge le modèle et le normalizer à la première tâche."""
    loaded_model, seen_paths = _patch_load_model_deps(monkeypatch)
    be._worker_model = None
    be._worker_model_version_key = None
    be._worker_vec_normalize_enabled = True
    be._worker_vec_eval_enabled = True

    be._eval_worker_load_model_if_needed(
        {"model_path": "/tmp/model.zip", "model_device": "cpu", "model_mtime": 1.0}
    )
    assert be._worker_model is loaded_model
    assert callable(be._worker_obs_normalizer)
    # V11 §0.35 : le normalizer est construit sur le zip que CE worker charge.
    assert seen_paths == ["/tmp/model.zip"]
    assert be._worker_model_version_key == ("/tmp/model.zip", 1.0)


def test_load_model_if_needed_torch_compile_cpu_calls_compile_and_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """torch_compile_cpu=True appelle _torch_compile_eval_extractor puis _warmup_eval_inference."""
    loaded_model, _ = _patch_load_model_deps(monkeypatch)
    compile_calls: List[Any] = []
    warmup_calls: List[Any] = []
    monkeypatch.setattr(be, "_torch_compile_eval_extractor", lambda m: compile_calls.append(m))
    monkeypatch.setattr(be, "_warmup_eval_inference", lambda m: warmup_calls.append(m))
    be._worker_model = None
    be._worker_model_version_key = None
    be._worker_vec_normalize_enabled = False
    be._worker_vec_eval_enabled = False

    be._eval_worker_load_model_if_needed(
        {"model_path": "/tmp/model.zip", "model_device": "cpu",
         "model_mtime": 1.0, "torch_compile_cpu": True}
    )
    assert compile_calls == [loaded_model], "compile doit être appelé avec le modèle chargé"
    assert warmup_calls == [loaded_model], "warmup doit être appelé après compile"


def test_load_model_if_needed_torch_compile_cpu_false_skips_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """torch_compile_cpu=False (défaut) ne touche pas l'extracteur."""
    _patch_load_model_deps(monkeypatch)
    compile_calls: List[Any] = []
    monkeypatch.setattr(be, "_torch_compile_eval_extractor", lambda m: compile_calls.append(m))
    be._worker_model = None
    be._worker_model_version_key = None
    be._worker_vec_normalize_enabled = False
    be._worker_vec_eval_enabled = False

    be._eval_worker_load_model_if_needed(
        {"model_path": "/tmp/model.zip", "model_device": "cpu", "model_mtime": 1.0}
    )
    assert compile_calls == [], "compile ne doit PAS être appelé quand torch_compile_cpu=False"


def test_eval_worker_task_counts_outcomes_and_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyModel:
        def predict(self, obs, action_masks=None, deterministic=True):
            _ = obs, action_masks, deterministic
            return np.array([1], dtype=np.int64), None

    class _DummyEnv:
        def __init__(self):
            # Le roster de l'agent CHANGE de faction au 3e episode : le worker doit relever la
            # faction a chaque reset, pas une fois par tache (roster tire au sort).
            self._rosters = [
                [{"player": 0, "unitType": "Intercessor"}, {"player": 1, "unitType": "Boyz"}],
                [{"player": 0, "unitType": "Intercessor"}, {"player": 1, "unitType": "Boyz"}],
                [{"player": 0, "unitType": "Boyz"}, {"player": 1, "unitType": "Intercessor"}],
            ]
            self.engine = SimpleNamespace(
                get_action_mask=lambda: [True, False],
                unit_registry=SimpleNamespace(
                    get_unit_data=lambda unit_type: {
                        "faction": {"Intercessor": "Spacemarine", "Boyz": "Ork"}[unit_type]
                    }
                ),
                config={"controlled_player": 0},
                game_state={"units": []},
                # Posé par le chargement de scénario sur le vrai moteur : la doublure porte le
                # contrat au lieu de le contourner. `None` = scénario sans roster_ref, cas légitime
                # que `_episode_roster_ids` range sous NO_ROSTER_REF.
                _scenario_roster_info=None,
                # Le worker aligne son backstop sur le plafond du MOTEUR (V11 §0.61) : la
                # doublure porte ce contrat au lieu de le contourner.
                _get_episode_step_limit=lambda: 500,
            )
            self._episode = -1
            self._closed = False
            self._winners = [0, -1, 1]
            # Le SIEGE change au 3e episode, comme la faction juste au-dessus et pour la meme
            # raison : `agent_seat_mode: "random"` le tire a chaque reset, donc le worker doit le
            # relever episode par episode et non une fois par tache.
            self._seats = [1, 1, 2]

        def get_wrapper_attr(self, name):
            # Chemin de PPO : `get_action_masks` resout `action_masks` par ce biais. L'appel
            # direct a `engine.get_action_mask()` a ete retire de la boucle d'evaluation — il
            # pouvait avancer la phase de combat entre deux `step()` et perimer le masque
            # transmis ensuite au moteur.
            return getattr(self, name)

        def action_masks(self):
            return [True, False]

        def reset(self, seed=None):
            _ = seed
            self._episode += 1
            self.engine.game_state["units"] = self._rosters[self._episode]
            # `controlled_player` : le siege de l'episode, publie par `BotControlledEnv` a chaque
            # reset (`agent_seat_mode: "random"` le tire episode par episode) et lu par la tache
            # d'evaluation pour sa ventilation par siege.
            return (
                np.array([0.0, 1.0], dtype=np.float32),
                {"controlled_player": self._seats[self._episode]},
            )

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
            return {
                "shoot_opportunities": 5, "shoot_actions": 3, "wait_actions": 2,
                "shoot_rate": 60.0, "wait_rate": 40.0,
                "ai_shoot_opportunities": 4, "ai_shoot_actions": 3,
                "ai_shoot_rate": 75.0, "ai_wait_rate": 25.0,
            }

        def close(self):
            self._closed = True

    monkeypatch.setattr(be, "_worker_model", _DummyModel())
    monkeypatch.setattr(be, "_worker_obs_normalizer", lambda obs: np.asarray(obs, dtype=np.float32))
    monkeypatch.setattr(be, "_create_eval_env", lambda **kwargs: _DummyEnv())
    monkeypatch.setattr(be, "_eval_worker_load_model_if_needed", lambda task: None)

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
        "ep_offset": 0,
        "max_steps_per_episode": 500,
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
    assert progress["n"] == 3
    # Episodes 1 (victoire) et 2 (nul) en Space Marines, episode 3 (defaite) en Orks.
    assert result["faction_stats"] == {
        "Spacemarine": {"wins": 1, "total": 2},
        "Ork": {"wins": 0, "total": 1},
    }
    # MEME releve pour le SIEGE, et c'est ce que l'evaluation ne faisait pas : son `combined`
    # melangeait les deux sieges, donc le score qui selectionne le modele livre etait aveugle a
    # l'ecart entre eux (12 points sur le run x1_long du 2026-08-12).
    assert result["seat_stats"] == {
        "p1": {"wins": 1, "total": 2},
        "p2": {"wins": 0, "total": 1},
    }
    # La ventilation par siege partitionne les episodes : ni un episode compte deux fois, ni un
    # episode perdu en route. Vrai par construction (un seul site d'ecriture), verrouille ici.
    assert sum(b["total"] for b in result["seat_stats"].values()) == task["n_episodes"]
    assert sum(b["wins"] for b in result["seat_stats"].values()) == result["wins"]


# La barre d'avancement de l'eval n'est plus ecrite ici : elle passe par le writer partage avec
# la barre d'entrainement (tests/unit/shared/test_progress_writer.py).


def test_eval_worker_task_requires_worker_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(be, "_worker_model", None)
    monkeypatch.setattr(be, "_eval_worker_load_model_if_needed", lambda task: None)
    with pytest.raises(RuntimeError, match=r"n'a pas charg"):
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
            self.engine = SimpleNamespace(
                get_action_mask=lambda: [True],
                step_logger=None,
                unit_registry=SimpleNamespace(
                    get_unit_data=lambda unit_type: {"faction": "Spacemarine"}
                ),
                config={"controlled_player": 0},
                game_state={"units": [{"player": 0, "unitType": "Intercessor"}]},
                _scenario_roster_info=None,
                # Le worker aligne son backstop sur le plafond du MOTEUR (V11 §0.61).
                _get_episode_step_limit=lambda: 500,
            )

        def get_wrapper_attr(self, name):
            # Chemin de PPO : `get_action_masks` resout `action_masks` par ce biais. L'appel
            # direct a `engine.get_action_mask()` a ete retire de la boucle d'evaluation — il
            # pouvait avancer la phase de combat entre deux `step()` et perimer le masque
            # transmis ensuite au moteur.
            return getattr(self, name)

        def action_masks(self):
            return [True]

        def reset(self, seed=None):
            _ = seed
            # Cf. l'autre faux env de ce fichier : le siege de l'episode est publie au reset.
            return np.array([0.0], dtype=np.float32), {"controlled_player": 1}

        def step(self, action):
            _ = action
            return np.array([0.0], dtype=np.float32), 0.0, True, False, {"winner": 0, "controlled_player": 0}

        def close(self):
            return None

    env = _DummyEnv()
    monkeypatch.setattr(be, "_worker_model", _DummyModel())
    monkeypatch.setattr(be, "_worker_obs_normalizer", None)
    monkeypatch.setattr(be, "_create_eval_env", lambda **kwargs: env)
    monkeypatch.setattr(be, "_eval_worker_load_model_if_needed", lambda task: None)

    class _MarkerLogger:
        """Doublure de journal. `object()` ne convient plus : depuis le 2026-08-11 la tache pose
        `current_bot_name` sur le journal — c'est le maillon qui manquait pour que l'en-tete
        nomme l'adversaire REELLEMENT affronte, au lieu de l'etiquette en dur « SelfPlay ».
        Un doublure sans attribut assignable ferait echouer cette pose, donc ce test la verifie
        aussi (assertion plus bas)."""

        # Annonce sans valeur : l'attribut n'existe qu'une fois POSE par la tache. Lui donner une
        # valeur initiale ferait passer l'assertion en cas de non-pose... par la valeur initiale.
        current_bot_name: str

    marker_logger = _MarkerLogger()
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
            "ep_offset": 0,
            "max_steps_per_episode": 500,
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
    # Le nom du bot de la TACHE atteint le journal : sans lui, l'en-tete ne nomme plus personne.
    assert marker_logger.current_bot_name == "random"
    assert result["wins"] == 1


class _FakeFuture:
    """Doublure de future. `wait` etant stubbe, la collecte n'appelle que `result()`."""

    def __init__(self, payload: Optional[dict] = None) -> None:
        self._payload = payload

    def result(self, timeout=None):
        _ = timeout
        if self._payload is None:
            raise AssertionError("un future jamais rendu 'done' ne doit pas etre lu")
        return self._payload


class _FakePool:
    """Pool qui rend les futures preparees, dans l'ordre de soumission.

    Un vrai `ProcessPoolExecutor` lancerait de vrais workers : ici la collecte SOUMET
    elle-meme, donc le pool doit etre une doublure pour que `submitted` soit observable —
    c'est lui qui prouve l'etranglement a `max_in_flight`.
    """

    def __init__(self, futures) -> None:
        self._futures = deque(futures)
        self.submitted: List[dict] = []

    def submit(self, fn, task):
        _ = fn
        self.submitted.append(task)
        return self._futures.popleft()


def _stub_collect(monkeypatch: pytest.MonkeyPatch, waits, clock) -> List[Any]:
    """Stubbe `wait` (une paire `(done, not_done)` par tour) et l'horloge de la collecte.

    `clock` est consommee dans l'ordre par TOUS les appels a `time.monotonic` : une valeur par
    soumission, puis une par tour de boucle ; la derniere se repete. L'iterateur est cree UNE
    fois — le recreer a chaque appel renverrait toujours la meme valeur, `elapsed` resterait nul
    et la boucle ne sortirait jamais.

    Retourne la liste, remplie au fil de l'eau, des pools force-termines.
    """
    turns = iter(waits)
    monkeypatch.setattr(be, "wait", lambda pending, timeout=None, return_when=None: next(turns))
    values = chain(clock[:-1], repeat(clock[-1]))
    monkeypatch.setattr(be.time, "monotonic", lambda: next(values))
    terminated: List[Any] = []
    monkeypatch.setattr(be, "_force_terminate_process_pool", terminated.append)
    return terminated


def _eval_task(bot_name: str, n_episodes: int) -> dict:
    return {
        "bot_name": bot_name,
        "scenario_name": "training_bot-1",
        "scenario_file": f"/tmp/{bot_name}.json",
        "n_episodes": n_episodes,
    }


def _done_payload(bot_name: str, wins: int) -> dict:
    """Resultat rendu par un worker qui a fini : la forme que la collecte fait suivre telle quelle."""
    return {
        "wins": wins, "losses": 0, "draws": 0, "failed_episodes": 0,
        "bot_name": bot_name, "scenario_name": "training_bot-1",
    }


def test_collect_parallel_results_with_timeouts_aborts_pool_on_hung_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done_future, hung_future = _FakeFuture(_done_payload("random", 1)), _FakeFuture()
    pool = _FakePool([done_future, hung_future])
    tasks = [_eval_task("random", 1), _eval_task("greedy", 3)]

    # 2 soumissions a t=0, tour 1 a t=0 (rien n'a expire), tour 2 a t=2 > timeout=1.
    terminated = _stub_collect(
        monkeypatch,
        waits=[({done_future}, {hung_future}), (set(), {hung_future})],
        clock=[0.0, 0.0, 0.0, 2.0],
    )
    out = be._collect_parallel_results_with_timeouts(
        pool=cast(ProcessPoolExecutor, pool), tasks=tasks, task_timeout_seconds=1, max_in_flight=2,
    )

    assert terminated == [pool]
    assert any(r.get("bot_name") == "random" and r.get("wins") == 1 for r in out)
    timed_out = [r for r in out if r.get("bot_name") == "greedy" and r.get("timeout") is True]
    assert len(timed_out) == 1
    assert timed_out[0]["failed_episodes"] == 3


def test_collect_parallel_results_arms_each_deadline_at_its_own_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Au plus `max_in_flight` tasks en vol, et le chrono de chacune part de SA soumission.

    Tout soumettre d'un coup faisait de `bot_eval_task_timeout_seconds` une deadline GLOBALE :
    a 24 tasks sur 4 workers, celles de la 6e vague avaient consomme 5 durees de task avant de
    commencer et se faisaient tuer sans avoir tourne — or UN seul timeout force-termine le pool,
    donc annule la mesure finale apres des heures d'entrainement. Ici la 2e task demarre a
    t=100 s avec un timeout de 1 s : elle n'expire que si son chrono est celui du pool.
    """
    payloads = [_done_payload(bot, 2) for bot in ("random", "greedy")]
    first, second = _FakeFuture(payloads[0]), _FakeFuture(payloads[1])
    pool = _FakePool([first, second])
    tasks = [_eval_task("random", 2), _eval_task("greedy", 2)]

    terminated = _stub_collect(
        monkeypatch,
        # Le tour 2 observe la 2e task ENCORE EN COURS : c'est le seul moment ou sa deadline
        # est evaluee, donc le seul ou ce test peut echouer. Sans lui, il ne verrouillerait
        # que l'ordre de soumission.
        waits=[({first}, set()), (set(), {second}), ({second}, set())],
        # soumission 1 a t=0, tour 1 a t=0.5, soumission 2 a t=100 (le pool tourne depuis
        # longtemps), tour 2 a t=100.2 : 0,2 s pour la 2e task, bien sous le timeout de 1 s.
        clock=[0.0, 0.5, 100.0, 100.2, 100.3],
    )
    out = be._collect_parallel_results_with_timeouts(
        pool=cast(ProcessPoolExecutor, pool), tasks=tasks, task_timeout_seconds=1, max_in_flight=1,
    )

    assert pool.submitted == tasks, "les tasks partent une par une, pas toutes d'un coup"
    assert terminated == [], "aucune task n'a depasse SON propre budget"
    assert out == payloads


def test_collect_parallel_results_reports_tasks_never_submitted_on_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'abandon du pool doit rendre compte AUSSI des tasks jamais soumises.

    Les taire donnerait un resultat calcule sur un denominateur tronque, donc un score publie
    plus flatteur que la realite, alors que l'appelant doit lever sur evaluation incomplete.
    """
    hung_future = _FakeFuture()
    pool = _FakePool([hung_future])
    tasks = [_eval_task("random", 3), _eval_task("greedy", 5)]

    terminated = _stub_collect(
        monkeypatch, waits=[(set(), {hung_future})], clock=[0.0, 2.0],
    )
    out = be._collect_parallel_results_with_timeouts(
        pool=cast(ProcessPoolExecutor, pool), tasks=tasks, task_timeout_seconds=1, max_in_flight=1,
    )

    assert terminated == [pool]
    assert pool.submitted == [tasks[0]], "la 2e task n'a jamais ete soumise"
    assert all(r["timeout"] is True for r in out)
    assert sum(r["failed_episodes"] for r in out) == 8, "les 3 + 5 episodes sont comptes perdus"


def test_collect_parallel_results_on_result_called_on_done_timeout_and_abandoned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """on_result est appelé exactement une fois par résultat sur chacun des 3 chemins.

    Chemins couverts, dans `_collect_parallel_results_with_timeouts` :
    - done      : boucle `for future in done`
    - timeout   : boucle `for future in not_done`, deadline depassee
    - abandoned : boucle sur `abandoned`, apres force-terminate du pool

    Un site oublie ne fait rougir aucun autre test : la barre d'avancement se contente alors de
    sous-compter, sans que ni le score ni le nombre d'episodes ne bougent.
    """
    done_future, hung_future = _FakeFuture(_done_payload("random", 1)), _FakeFuture()
    pool = _FakePool([done_future, hung_future])
    # 3 tasks : random (done), greedy (timeout), defensive (jamais soumise → abandoned).
    tasks = [_eval_task("random", 1), _eval_task("greedy", 3), _eval_task("defensive", 2)]

    collected: List[dict] = []
    _stub_collect(
        monkeypatch,
        # max_in_flight=1 : random soumis seul, done en tour 1 ; greedy soumis en tour 2,
        # expire (t=3 - t=1.5 = 1.5 > 1) ; defensive jamais soumise → abandoned.
        waits=[({done_future}, set()), (set(), {hung_future})],
        clock=[0.0, 0.5, 1.5, 3.0],
    )
    be._collect_parallel_results_with_timeouts(
        pool=cast(ProcessPoolExecutor, pool),
        tasks=tasks,
        task_timeout_seconds=1,
        max_in_flight=1,
        on_result=collected.append,
    )

    assert len(collected) == 3, "on_result doit être appelé pour chaque résultat"
    by_bot = {r["bot_name"]: r for r in collected}
    assert "random" in by_bot, "chemin done manquant"
    assert "greedy" in by_bot, "chemin timeout manquant"
    assert "defensive" in by_bot, "chemin abandoned manquant"
    assert by_bot["random"]["wins"] == 1
    assert by_bot["greedy"]["timeout"] is True
    assert by_bot["defensive"]["timeout"] is True


def test_collect_parallel_results_with_timeouts_rejects_invalid_bounds() -> None:
    pool = cast(ProcessPoolExecutor, _FakePool([]))
    with pytest.raises(ValueError, match=r"task_timeout_seconds must be > 0"):
        be._collect_parallel_results_with_timeouts(
            pool=pool, tasks=[], task_timeout_seconds=0, max_in_flight=1,
        )
    with pytest.raises(ValueError, match=r"max_in_flight must be > 0"):
        be._collect_parallel_results_with_timeouts(
            pool=pool, tasks=[], task_timeout_seconds=1, max_in_flight=0,
        )


def _faction_result(bot_name: str, faction_stats: dict) -> dict:
    return {"bot_name": bot_name, "faction_stats": faction_stats}


def _faction_scores(results_list: list, active: tuple, weights: dict) -> dict:
    """Chaine REELLE de `evaluate_against_bots` : un tally construit, puis pondere.

    Les tests passent par cet enchainement et non par le tally a la main, sinon ils
    verrouilleraient une composition qui n'est pas celle de la production.
    """
    return be._compute_faction_scores(be._faction_bot_tally(results_list, active), active, weights)


def _faction_cross(results_list: list, active: tuple) -> dict:
    """Jumeau de `_faction_scores` pour la ventilation brute : MEME tally en entree."""
    return be._compute_bot_win_rates(be._faction_bot_tally(results_list, active))


def test_compute_faction_scores_weights_bots_like_combined() -> None:
    """Le score par faction utilise les MEMES poids que `combined`, pas un win-rate brut."""
    weights = {"random": 0.75, "greedy": 0.25}
    results_list = [
        # Space Marines : 100% vs random (poids 0.75), 0% vs greedy -> 0.75
        _faction_result("random", {"Spacemarine": {"wins": 4, "total": 4}}),
        _faction_result("greedy", {"Spacemarine": {"wins": 0, "total": 4}}),
        # Orks : 50% vs random, 100% vs greedy -> 0.375 + 0.25 = 0.625
        _faction_result("random", {"Ork": {"wins": 2, "total": 4}}),
        _faction_result("greedy", {"Ork": {"wins": 4, "total": 4}}),
    ]
    scores = _faction_scores(results_list, ("random", "greedy"), weights)
    assert scores == {"Spacemarine": 0.75, "Ork": 0.625}
    # Un win-rate brut donnerait 0.5 pour SM et 0.75 pour Ork, soit un gap de signe OPPOSE.
    assert scores["Spacemarine"] > scores["Ork"]


def test_compute_faction_scores_drops_faction_missing_a_bot() -> None:
    """Une faction sans episode contre l'un des bots n'est pas sur la meme echelle : ecartee."""
    results_list = [
        _faction_result("random", {"Spacemarine": {"wins": 2, "total": 4}, "Ork": {"wins": 1, "total": 2}}),
        _faction_result("greedy", {"Spacemarine": {"wins": 1, "total": 4}}),
    ]
    scores = _faction_scores(results_list, ("random", "greedy"), {"random": 0.5, "greedy": 0.5})
    assert set(scores) == {"Spacemarine"}


def test_compute_faction_scores_ignores_failed_tasks() -> None:
    """Une tache en timeout/erreur porte `faction_stats` vide et ne fausse aucun total."""
    results_list = [
        _faction_result("random", {"Spacemarine": {"wins": 3, "total": 4}}),
        _faction_result("random", {}),
    ]
    scores = _faction_scores(results_list, ("random",), {"random": 1.0})
    assert scores == {"Spacemarine": 0.75}


def test_faction_bot_win_rates_come_from_the_same_tally_as_the_aggregate() -> None:
    """V11 §0.55 : le croisement derive du MEME comptage que `faction_scores`.

    Un second parcours de `results_list` divergerait au premier changement de filtre. Le
    controle porte sur ce qui les SEPARE : le poids nul du holdout l'efface de l'agregat
    pondere sans l'effacer du croisement, et une faction a couverture partielle — ecartee de
    l'agregat parce que son score n'y serait pas a la meme echelle — reste lisible cellule
    par cellule.
    """
    weights = {"control": 1.0, "tactical": 0.0}
    results_list = [
        _faction_result("control", {"Spacemarine": {"wins": 1, "total": 4},
                                    "Ork": {"wins": 2, "total": 4}}),
        _faction_result("tactical", {"Spacemarine": {"wins": 3, "total": 4}}),
    ]
    active = ("control", "tactical")
    scores = _faction_scores(results_list, active, weights)
    cross = _faction_cross(results_list, active)

    # Ork n'a aucun episode contre `tactical` : ecarte de l'agregat...
    assert set(scores) == {"Spacemarine"}
    # ...mais sa cellule vs_control existe et vaut son win-rate brut.
    assert cross["Ork"] == {"control": 0.5}
    # Le holdout pese 0.0 : invisible dans l'agregat (0.25 = celui de `control` seul),
    # visible dans le croisement.
    assert scores["Spacemarine"] == 0.25
    assert cross["Spacemarine"] == {"control": 0.25, "tactical": 0.75}


def test_faction_bot_win_rates_skip_cells_without_episodes() -> None:
    """Un couple (faction, bot) sans episode n'est pas publie : un 0.0 y serait invente."""
    results_list = [_faction_result("control", {"Ork": {"wins": 0, "total": 0}})]
    assert _faction_cross(results_list, ("control",)) == {"Ork": {}}


def test_roster_gap_faction_order_carries_the_curve_sign() -> None:
    """L'ordre de ROSTER_GAP_FACTIONS fixe le sens de 00_critical/0_gap_sm-ork."""
    assert be.ROSTER_GAP_FACTIONS == ("Spacemarine", "Ork")


def _seat_result(bot_name: str, seat_stats: dict) -> dict:
    return {"bot_name": bot_name, "seat_stats": seat_stats}


def _seat_scores(results_list: list, active: tuple, weights: dict) -> dict:
    """Chaine REELLE de `evaluate_against_bots`, jumelle de `_faction_scores`."""
    return be._compute_faction_scores(be._seat_bot_tally(results_list, active), active, weights)


def test_seat_scores_show_the_gap_that_combined_hides() -> None:
    """Ce que la ventilation par SIEGE apporte, et qu'aucune courbe d'evaluation ne donnait.

    Un agent a 100 % en jouant premier et 50 % en jouant second rend le MEME `combined` (0.75)
    qu'un agent a 75 % des deux cotes. C'est le cas mesure sur le run x1_long du 2026-08-12 :
    0.707 contre 0.586 en entrainement, 12 points, quand l'evaluation ne publiait qu'un chiffre
    unique — et c'est ce chiffre unique dont derive le score robuste qui SELECTIONNE le modele
    livre. Les deux situations doivent cesser d'etre indiscernables.

    Le score par siege est PONDERE par les memes poids que `combined` (`_compute_faction_scores`
    est agnostique a la cle du tally) : un win-rate brut melangerait des adversaires de
    difficultes differentes et ne serait pas comparable a `combined`.
    """
    weights = {"random": 0.75, "greedy": 0.25}
    results_list = [
        # Siege p1 : 100 % contre les deux bots -> 1.0
        _seat_result("random", {"p1": {"wins": 4, "total": 4}}),
        _seat_result("greedy", {"p1": {"wins": 4, "total": 4}}),
        # Siege p2 : 50 % contre les deux -> 0.5
        _seat_result("random", {"p2": {"wins": 2, "total": 4}}),
        _seat_result("greedy", {"p2": {"wins": 2, "total": 4}}),
    ]
    scores = _seat_scores(results_list, ("random", "greedy"), weights)
    assert scores == {"p1": 1.0, "p2": 0.5}
    # L'ECART est la grandeur publiee (`00_critical/0_gap_p1-p2`), et son signe vient de l'ordre
    # de SEAT_KEYS : positif = meilleur en jouant premier.
    assert be.SEAT_KEYS == ("p1", "p2")
    assert scores[be.SEAT_KEYS[0]] - scores[be.SEAT_KEYS[1]] == 0.5
    # Le combined global, lui, vaut 0.75 dans ce montage comme dans un montage parfaitement
    # symetrique : c'est exactement ce qu'il ne pouvait pas distinguer.
    assert sum(weights[bn] * 0.75 for bn in weights) == 0.75


def test_seat_scores_drop_a_seat_missing_a_bot() -> None:
    """Un siege sans episode contre l'un des bots n'est pas sur la meme echelle : ecarte.

    C'est ce qui rend la courbe muette — plutot que fausse — quand `agent_seat_mode` vaut "p1"
    ou "p2" : un seul siege est couvert, et l'ecart n'est alors pas publie du tout.
    """
    results_list = [
        _seat_result("random", {"p1": {"wins": 2, "total": 4}, "p2": {"wins": 1, "total": 2}}),
        _seat_result("greedy", {"p1": {"wins": 1, "total": 4}}),
    ]
    scores = _seat_scores(results_list, ("random", "greedy"), {"random": 0.5, "greedy": 0.5})
    assert set(scores) == {"p1"}
    assert not all(seat in scores for seat in be.SEAT_KEYS), (
        "un seul siege couvert : `evaluate_against_bots` ne doit pas publier `seat_gap`"
    )


def test_every_failed_task_result_carries_seat_stats() -> None:
    """Jumeau de `test_every_failed_task_result_carries_faction_stats` pour le siege.

    `_seat_bot_tally` lit `seat_stats` par require_key : une fabrique d'echec qui l'omettrait
    ferait sauter le run au premier timeout, exactement comme cela s'etait produit sur
    `roster_stats`.
    """
    task = {"bot_name": "random", "scenario_file": "/tmp/s1.json", "n_episodes": 3}
    for result in (
        be._failed_task_result(task, "training_bot-1", timeout=True),
        be._failed_task_result(task, "training_bot-1", error="boom"),
    ):
        assert result["seat_stats"] == {}
    assert _seat_scores(
        [be._failed_task_result(task, "training_bot-1", timeout=True)], ("random",), {"random": 1.0}
    ) == {}


def test_seat_key_refuses_anything_but_the_two_seats() -> None:
    """`_seat_key` ne connait que 1 et 2 : un autre siege est une rupture, pas un cas de jeu."""
    assert (be._seat_key(1), be._seat_key(2)) == ("p1", "p2")
    for bad in (0, 3, -1):
        with pytest.raises(ValueError, match=r"controlled_player"):
            be._seat_key(bad)


def test_every_failed_task_result_carries_faction_stats() -> None:
    """
    Un timeout ne doit JAMAIS tuer le training (V11 §0.27) — or `_compute_faction_scores`
    lit `faction_stats` par require_key. Les quatre sites d'echec passent par la meme
    fabrique : ce test verrouille le contrat de cette fabrique.
    """
    task = {"bot_name": "random", "scenario_file": "/tmp/s1.json", "n_episodes": 3}
    for result in (
        be._failed_task_result(task, "training_bot-1", timeout=True),
        be._failed_task_result(task, "training_bot-1", error="boom"),
    ):
        assert result["faction_stats"] == {}
        assert result["failed_episodes"] == 3
        assert result["wins"] == 0
    # Et l'agregation les traverse sans lever.
    scores = _faction_scores(
        [be._failed_task_result(task, "training_bot-1", timeout=True)], ("random",), {"random": 1.0}
    )
    assert scores == {}


def test_collected_timeout_results_are_aggregatable(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Verrou du jumeau : `_collect_parallel_results_with_timeouts` construit ses PROPRES
    dicts d'echec. Ils doivent traverser l'agregation comme ceux de _get_result_with_timeout.
    """
    hung_future = _FakeFuture()
    pool = _FakePool([hung_future])
    _stub_collect(monkeypatch, waits=[(set(), {hung_future})], clock=[0.0, 2.0])

    out = be._collect_parallel_results_with_timeouts(
        pool=cast(ProcessPoolExecutor, pool),
        tasks=[_eval_task("random", 3)],
        task_timeout_seconds=1,
        max_in_flight=1,
    )
    assert len(out) == 1 and out[0]["timeout"] is True
    # Le point du bug : sans `faction_stats`, cet appel levait ConfigurationError.
    assert _faction_scores(out, ("random",), {"random": 1.0}) == {}


def test_mixed_faction_roster_is_bucketed_not_fatal() -> None:
    """Un roster mixte est une donnee, pas un crash : cle composite, hors du gap."""
    engine = SimpleNamespace(
        unit_registry=SimpleNamespace(
            get_unit_data=lambda unit_type: {
                "faction": {"Intercessor": "Spacemarine", "Boyz": "Ork"}[unit_type]
            }
        ),
        config={"controlled_player": 0},
        game_state={
            "units": [
                {"player": 0, "unitType": "Intercessor"},
                {"player": 0, "unitType": "Boyz"},
            ]
        },
    )
    faction = be._agent_faction_from_engine(engine)
    assert faction == "Ork+Spacemarine"
    assert faction not in be.ROSTER_GAP_FACTIONS


def test_warmup_eval_inference_accepts_box_and_dict_obs_space() -> None:
    """_warmup_eval_inference ne crash pas sur un espace Box (AttributeError ancien bug)."""
    import gymnasium as gym

    predict_calls: List[Any] = []

    def _make_model(obs_space):
        return SimpleNamespace(
            observation_space=obs_space,
            action_space=SimpleNamespace(n=4),
            predict=lambda obs, **kw: predict_calls.append(obs) or (np.zeros(1), None),
        )

    # Box space — ancienne implémentation levait AttributeError
    box_model = _make_model(gym.spaces.Box(low=0.0, high=1.0, shape=(8,), dtype=np.float32))
    be._warmup_eval_inference(box_model)
    assert len(predict_calls) == 1
    assert isinstance(predict_calls[-1], np.ndarray)

    # Dict space — comportement attendu inchangé
    dict_model = _make_model(
        gym.spaces.Dict({"obs": gym.spaces.Box(low=0.0, high=1.0, shape=(8,), dtype=np.float32)})
    )
    be._warmup_eval_inference(dict_model)
    assert len(predict_calls) == 2
    assert isinstance(predict_calls[-1], dict)


def test_empty_controlled_roster_raises() -> None:
    """Aucune unite pour le joueur controle : anomalie d'environnement, pas un cas de jeu."""
    engine = SimpleNamespace(
        unit_registry=SimpleNamespace(get_unit_data=lambda unit_type: {"faction": "Ork"}),
        config={"controlled_player": 0},
        game_state={"units": [{"player": 1, "unitType": "Boyz"}]},
    )
    with pytest.raises(ValueError, match=r"No unit belongs to the controlled player 0"):
        be._agent_faction_from_engine(engine)
