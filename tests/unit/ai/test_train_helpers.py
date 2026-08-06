import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai.train as train


def test_build_training_bots_from_config() -> None:
    cfg = {
        "bot_training": {
            "ratios": {"random": 0.2, "greedy": 0.4, "defensive": 0.4},
            # `randomness` est EXIGE pour chaque bot pondere (plus de defaut a 0.10 en silence).
            "randomness": {"greedy": 0.11, "defensive": 0.22},
        }
    }
    bots = train._build_training_bots_from_config(cfg)
    assert len(bots) >= 3


def test_build_training_bots_respects_the_configured_budget() -> None:
    """La FREQUENCE d'un bot doit etre son ratio : `BotControlledEnv` tire l'adversaire par un
    `random.choice` UNIFORME sur cette liste, donc frequence = count / len(bots).

    ROUGE sur le pool de 10 : `round(ratio * 10)` rendait 4/2/2/2/2/1 = 13 instances pour le
    panel a six bots, soit 0.31 pour control (au lieu de 0.35) et 0.077 pour random (au lieu
    de 0.05, +54 %). `len(bots) >= 3` ne regardait rien de tout cela.
    """
    from collections import Counter

    ratios = {
        "control": 0.35, "value_trade": 0.15, "adaptive": 0.15,
        "greedy": 0.15, "defensive": 0.15, "random": 0.05,
    }
    bots = train._build_training_bots_from_config({
        "bot_training": {
            "ratios": ratios,
            "randomness": {k: 0.05 for k in ratios if k != "random"},
        }
    })
    counts = Counter(type(b).__name__ for b in bots)
    by_name = {
        "control": "ControlBot", "value_trade": "ValueTradeBot", "adaptive": "AdaptiveBot",
        "greedy": "GreedyBot", "defensive": "DefensiveBot", "random": "RandomBot",
    }
    for name, ratio in ratios.items():
        assert counts[by_name[name]] / len(bots) == pytest.approx(ratio), name


def test_build_training_bots_rejects_a_budget_that_is_not_one() -> None:
    """Des ratios qui ne somment pas a 1.0 deplacent le budget en silence : erreur explicite,
    comme `bot_eval_weights` cote evaluation."""
    with pytest.raises(ValueError, match=r"must sum to 1\.0"):
        train._build_training_bots_from_config({
            "bot_training": {
                "ratios": {"random": 0.2, "greedy": 0.4},
                "randomness": {"greedy": 0.11},
            }
        })


def test_make_constant_lr_schedule() -> None:
    """Le callable rendu ici est CONSTANT, meme pour une config en rampe.

    Il n'alimente que la construction de l'optimizer (`lr=lr_schedule(1)`, policies.py:634).
    La decroissance est pilotee par `LearningRateScheduleCallback`, PAR EPISODE, qui remplace
    `model.lr_schedule` des `on_training_start` -- donc avant la premiere iteration de `learn()`
    et avant tout `train()`. Ce test attendait `sched(0.0) == final` : il verrouillait une rampe
    qui n'a jamais ete appliquee, et qui aurait ete FAUSSE si elle l'avait ete (`learn()` est
    appele par chunks, `progress_remaining` refait 1 -> 0 a chaque chunk, d'ou une dent de scie
    par chunk au lieu d'une decroissance sur le run). Cf. `test_schedule_decay_fraction.py`.
    """
    const_fn = train._make_constant_lr_schedule(0.001)
    assert const_fn(1.0) == pytest.approx(0.001)
    assert const_fn(0.0) == pytest.approx(0.001)

    sched = train._make_constant_lr_schedule(
        {"initial": 0.002, "final": 0.001, "decay_fraction": 0.4}
    )
    assert sched(1.0) == pytest.approx(0.002)
    assert sched(0.0) == pytest.approx(0.002), "l'optimizer doit partir de `initial`, pas de `final`"
    with pytest.raises(ValueError, match=r"learning_rate must be float or dict"):
        train._make_constant_lr_schedule(["bad"])


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


def test_load_rule_checker_scenarios_generates_instead_of_reading_a_committed_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--rule-checker` FABRIQUE ses scenarios ; il ne lit plus un dossier versionne.

    Les artefacts etaient commites et ont pourri : ils portaient encore `objectives_ref`, refuse
    par le moteur, longtemps apres la correction du generateur. La selection est doublee (2 types)
    pour que le test construise son echantillon au lieu de balayer les rosters reels.
    """
    from shared import rule_checker_scenarios

    monkeypatch.setattr(
        rule_checker_scenarios, "select_units",
        lambda root: (["Intercessor", "Termagant"], [], []),
    )
    loaded = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")

    # 2 types -> 2x2 matchups : le carre est la raison pour laquelle ils ne sont plus versionnes.
    assert len(loaded) == 4
    for path in loaded:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["board_ref"] == rule_checker_scenarios.DEFAULT_BOARD_REF
        assert payload["uses_codex_detachment"] == {"1": True, "2": True}
        assert "objectives_ref" not in payload, "cle legacy refusee par le moteur"

    manifeste = json.loads((Path(loaded[0]).parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifeste["scenario_count"] == 4
    assert manifeste["agent"] == "CoreAgent"


def test_rule_checker_regeneration_destroys_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerer pendant qu'un training rule-checker tourne ne doit RIEN effacer.

    Le moteur rouvre le fichier de scenario a chaque episode : supprimer les fichiers du run
    precedent tuait le run en cours en `FileNotFoundError`. Ici la selection RETRECIT — le cas qui
    laissait des orphelins et justifiait la purge — et les fichiers d'avant doivent survivre.
    """
    from shared import rule_checker_scenarios

    monkeypatch.setattr(
        rule_checker_scenarios, "select_units",
        lambda root: (["Intercessor", "Termagant", "Hormagaunt"], [], []),
    )
    avant = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")
    assert len(avant) == 9

    monkeypatch.setattr(
        rule_checker_scenarios, "select_units", lambda root: (["Intercessor"], [], [])
    )
    apres = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")
    assert len(apres) == 1
    assert set(avant).isdisjoint(apres), "les deux jeux doivent vivre dans des dossiers distincts"
    for path in avant:
        assert Path(path).is_file(), f"fichier detruit sous un lecteur potentiel : {path}"


def test_rule_checker_reuses_an_identical_set_without_rewriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meme selection + memes parametres = meme jeu : reconnu, rendu tel quel."""
    from shared import rule_checker_scenarios

    monkeypatch.setattr(
        rule_checker_scenarios, "select_units", lambda root: (["Intercessor"], [], [])
    )
    premier = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")
    horodatage = Path(premier[0]).stat().st_mtime_ns
    second = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")

    assert second == premier
    assert Path(premier[0]).stat().st_mtime_ns == horodatage, "jeu identique reecrit inutilement"


def test_rule_checker_keeps_the_parameters_of_the_last_explicit_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`train.py` ne reimpose pas ses defauts sur un jeu genere a d'autres parametres.

    Sans cela : generation a 500pts par le script, puis `--rule-checker` reecrit tout au board par
    defaut et l'entrainement tourne sur un autre plateau, sans un mot.
    """
    from shared import rule_checker_scenarios

    monkeypatch.setattr(
        rule_checker_scenarios, "select_units", lambda root: (["Intercessor"], [], [])
    )
    rule_checker_scenarios.generate(
        tmp_path, agent_key="CoreAgent",
        params=rule_checker_scenarios.GenerationParams(
            scale="500pts", board_ref="44x60x10", terrain_ref="terrain-train-02.json"
        ),
    )

    repris = train._load_rule_checker_scenarios(str(tmp_path), "CoreAgent")
    payload = json.loads(Path(repris[0]).read_text(encoding="utf-8"))
    assert payload["scale"] == "500pts"
    assert payload["board_ref"] == "44x60x10"
    assert payload["terrain_ref"] == "terrain-train-02.json"


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
    train._apply_param_overrides(cfg, [["n_steps", "64"], ["model_params.gamma", "0.95"]], log_overrides=False)
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


def test_apply_vec_normalize_resume_without_stats_raises(tmp_path: Path) -> None:
    """V11 §0.35 : reprendre un entraînement sans stats sur disque doit LEVER, pas créer des
    stats neuves en silence (le modèle continuerait sur une distribution recalée de zéro)."""
    import ai.train as train

    model_path = str(tmp_path / "model_X.zip")
    with pytest.raises(FileNotFoundError, match=r"model_X_vec_normalize\.pkl"):
        train._apply_vec_normalize(object(), model_path, {}, False, 2, lambda _m: None)


def test_apply_vec_normalize_resume_names_the_legacy_pkl(tmp_path: Path) -> None:
    """Si un `vec_normalize.pkl` LEGACY partagé traîne dans le dossier, l'erreur le nomme :
    il peut appartenir à un autre modèle, la migration doit être un geste explicite."""
    import ai.train as train

    (tmp_path / "vec_normalize.pkl").write_bytes(b"legacy")
    with pytest.raises(FileNotFoundError, match="LEGACY"):
        train._apply_vec_normalize(
            object(), str(tmp_path / "model_X.zip"), {}, False, 2, lambda _m: None
        )


def _train_source_tree():
    import ast
    import inspect

    return ast.parse(inspect.getsource(train))


def test_the_final_eval_resolves_its_scenario_from_the_agent() -> None:
    """`test_trained_model` chargeait `config/scenario.json`, un fichier absent du depot.

    `--test-episodes > 0` mourait donc au fond de `_load_units_from_scenario`, apres
    l'entrainement complet, sans qu'aucune ligne ne nomme l'exigence. La suppression du mode
    generique a emporte le dernier garde-fou qui la nommait encore (`ensure_scenario`).
    """
    import ast
    import inspect

    func = ast.parse(inspect.getsource(train.test_trained_model)).body[0]
    assert isinstance(func, ast.FunctionDef)
    body = func.body[1:] if ast.get_docstring(func) else func.body  # la docstring CITE le bug
    code = "\n".join(ast.unparse(stmt) for stmt in body)
    assert "scenario.json" not in code, (
        "test_trained_model code en dur un scenario au lieu de le resoudre depuis l'agent"
    )
    assert "get_scenario_list_for_phase(" in code


def test_every_final_eval_call_site_passes_the_agent_and_its_rewards() -> None:
    """Les sites d'appel avaient DIVERGE : deux passaient `args.agent`/`args.rewards_config`,
    le troisieme ni l'un ni l'autre — le modele etait evalue avec `controlled_agent=None` et
    les recompenses "default", en silence. Motif jumeau du depot a l'etat pur.
    """
    import ast

    calls = [
        node for node in ast.walk(_train_source_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "test_trained_model"
    ]
    assert calls, "aucun site d'appel trouve : le controle ne regarderait rien"
    for call in calls:
        passed = [ast.unparse(a) for a in call.args] + [
            f"{kw.arg}={ast.unparse(kw.value)}" for kw in call.keywords
        ]
        rendered = ", ".join(passed)
        assert "args.agent" in rendered, f"site d'appel sans agent : {rendered}"
        assert "args.rewards_config" in rendered, f"site d'appel sans rewards : {rendered}"
