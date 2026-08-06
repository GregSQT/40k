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


def test_rule_checker_cache_hit_still_refreshes_manifest_audit_and_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un jeu de scenarios reconnu ne dispense PAS de reecrire ce qui decrit l'appel.

    Deux pannes silencieuses tenaient dans le meme retour anticipe. (1) `params.json` : generer
    100pts, puis 500pts, puis 100pts rendait le dossier 100pts sans le reecrire, donc il annoncait
    encore 500pts et `train.py --rule-checker` entrainait sur l'autre plateau. (2) manifeste et
    audit : ils derivent de `select_units`, dont les DETAILS bougent sans changer la liste des
    types retenus (une regle qui passe de 2 a 1 sur une fiche qui en garde une autre) — meme cle,
    meme nombre de fichiers, donc des artefacts perimes rendus tels quels.
    """
    from shared import rule_checker_scenarios

    detail_v1 = {"unit_type": "Intercessor", "file": "f.ts", "implemented_rules": ["A", "B"]}
    rejet_v1 = [{"unit_type": "Boyz", "file": "b.ts", "reason": "RULES_STATUS missing"}]
    monkeypatch.setattr(
        rule_checker_scenarios, "select_units",
        lambda root: (["Intercessor"], [detail_v1], rejet_v1),
    )
    cible = rule_checker_scenarios.generate(tmp_path, agent_key="CoreAgent")
    horodatage = Path(cible[0]).stat().st_mtime_ns

    rule_checker_scenarios.generate(
        tmp_path, agent_key="CoreAgent",
        params=rule_checker_scenarios.GenerationParams(
            scale="500pts", board_ref="44x60x10", terrain_ref="terrain-train-02.json"
        ),
    )

    detail_v2 = {"unit_type": "Intercessor", "file": "f.ts", "implemented_rules": ["A"]}
    rejet_v2 = [{"unit_type": "Boyz", "file": "b.ts", "reason": "RULES_STATUS has no value == 2"}]
    monkeypatch.setattr(
        rule_checker_scenarios, "select_units",
        lambda root: (["Intercessor"], [detail_v2], rejet_v2),
    )
    retour = rule_checker_scenarios.generate(tmp_path, agent_key="CoreAgent")

    assert retour == cible, "meme selection + memes parametres doivent rendre le meme jeu"
    assert Path(cible[0]).stat().st_mtime_ns == horodatage, "jeu identique reecrit inutilement"

    dossier = Path(cible[0]).parent
    params_ecrits = json.loads(
        (tmp_path / "config" / "rule_checker" / "params.json").read_text(encoding="utf-8")
    )
    assert params_ecrits["scale"] == rule_checker_scenarios.DEFAULT_SCALE, (
        "`params.json` reste sur la generation intermediaire : le training reprendra 500pts"
    )
    manifeste = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    assert manifeste["selected_details"] == [detail_v2], "manifeste perime sur cache-hit"
    audit = json.loads((dossier / "audit_rejected.json").read_text(encoding="utf-8"))
    assert audit == rejet_v2, "audit des rejetes perime sur cache-hit"


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


def _function_code(func) -> str:
    """Source d'une fonction SANS sa docstring : celles de ce module citent les bugs verrouilles,
    un scan naif du texte brut se satisferait de la citation."""
    import ast
    import inspect

    node = ast.parse(inspect.getsource(func)).body[0]
    assert isinstance(node, ast.FunctionDef)
    body = node.body[1:] if ast.get_docstring(node) else node.body
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_the_final_eval_is_measured_on_the_holdout() -> None:
    """Le win-rate « Test Results » ne se mesure pas sur les scenarios d'ENTRAINEMENT.

    `test_trained_model` a d'abord charge `config/scenario.json` (absent du depot), puis
    `scenario_type="bot"` — le pool qui venait de servir a entrainer, et qui cassait en prime
    un run `--scenario self`. Le chemin `--test-only` refuse deja `--scenario bot` et impose
    le holdout : meme regle des deux cotes.
    """
    code = _function_code(train.resolve_final_eval_scenarios)
    assert 'scenario_type="holdout"' in code or "scenario_type='holdout'" in code, (
        "l'eval post-entrainement doit resoudre un scenario de HOLDOUT"
    )
    for pool in ('"bot"', "'bot'", '"self"', "'self'"):
        assert pool not in code, f"pool d'entrainement {pool} dans le resolveur d'eval"

    # `test_trained_model` ne resout plus rien : le scenario lui est donne.
    evaluated = _function_code(train.test_trained_model)
    assert "get_scenario_list_for_phase(" not in evaluated
    assert "scenario.json" not in evaluated


def test_the_final_eval_scenario_is_resolved_between_the_early_returns_and_the_training() -> None:
    """La resolution du holdout est prise en TENAILLE, et les deux bornes comptent.

    TROP TARD (a l'heure de l'eval) : un holdout manquant levait APRES un entrainement reussi,
    `main()` sortait en code 1 — des heures perdues pour un dossier absent.

    TROP TOT (en tete de `main`) : elle s'appliquait aussi a `--convert-steplog`, `--replay` et
    `--test-only`, qui retournent avant tout entrainement et n'utilisent jamais
    `final_eval_scenarios`. Deux d'entre eux contournent le holdout par construction
    (`--test-only --rule-checker`, `--test-only --scenario foo.json`) : exiger un dossier
    holdout les cassait, alors qu'ils marchaient avant.
    """
    main_code = _function_code(train.main)

    # L'ancre est l'AFFECTATION, pas l'appel : `--test-only` appelle le meme resolveur plus
    # haut (resolveur unique, cf. test_the_two_holdout_paths_share_one_resolver), donc
    # chercher `resolve_final_eval_scenarios(` trouverait CE site-la et mesurerait un ordre faux.
    assert "final_eval_scenarios = " in main_code, (
        "main() doit resoudre le scenario d'eval en amont"
    )
    resolution = main_code.index("final_eval_scenarios = ")

    def _position(marker: str) -> int:
        assert marker in main_code, (
            f"marqueur '{marker}' absent de main() : le test ne verrouille plus rien "
            f"(renomme ? deplace ?)"
        )
        return main_code.index(marker)

    # Borne BASSE : apres chaque branche a retour anticipe. `--test-only` compris — c'est celle
    # que la docstring nomme et que rien ne verifiait : remonter la resolution au-dessus d'elle
    # laissait ce test VERT tout en cassant exactement ce qu'il pretend proteger.
    for early_return in (
        "convert_steplog_to_replay(",
        "generate_steplog_and_replay(",
        "if args.test_only:",
    ):
        assert _position(early_return) < resolution, (
            f"{early_return} est evalue APRES la resolution du holdout : ce chemin n'en veut pas"
        )

    # Borne HAUTE : avant le premier episode d'entrainement.
    for training_entry in ("train_with_scenario_rotation(", "create_multi_agent_model("):
        assert _position(training_entry) > resolution, (
            f"{training_entry} demarre avant la resolution du scenario d'eval"
        )


def test_every_final_eval_call_site_passes_the_rewards_key_and_the_scenarios() -> None:
    """Les sites d'appel avaient DIVERGE : deux passaient la cle de recompenses, le troisieme
    ni elle ni l'agent — le modele etait evalue avec `controlled_agent=None` et les recompenses
    "default", en silence. Motif jumeau du depot a l'etat pur.

    `--agent` n'est PLUS passe : la cle qui compte est celle des recompenses (elle porte le
    suffixe de phase), et c'est celle qu'utilisent les deux jumeaux `train_model` et l'eval
    `--test-only`.
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
        assert "args.agent" not in rendered, (
            f"site d'appel qui passe encore --agent comme cle d'eval : {rendered}"
        )
        assert "args.rewards_config" in rendered, f"site d'appel sans rewards : {rendered}"
        assert "final_eval_scenarios" in rendered, f"site d'appel sans scenario : {rendered}"


def _agent_scenarios_tree(tmp_path: Path, agent: str, **splits: bool) -> SimpleNamespace:
    """Arborescence `config/agents/<agent>/scenarios/<split>/` avec un scenario par split demande."""
    scenarios = tmp_path / "agents" / agent / "scenarios"
    for split, wanted in splits.items():
        if not wanted:
            continue
        directory = scenarios / split
        directory.mkdir(parents=True, exist_ok=True)
        # Nommage EXPLICITE `<dossier>_scenario_<phase>.json` : c'est le motif que
        # `_gather_scenario_files_in_dir` reconnait pour ces dossiers. Un nom quelconque ne
        # serait ramasse que par le glob de repli, et le test verrouillerait ce repli.
        (directory / f"{split}_scenario_x1.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(config_dir=str(tmp_path))


def test_the_final_eval_keeps_every_holdout_scenario(tmp_path: Path) -> None:
    """AUCUN scenario de holdout n'est ecarte, et le choix ne depend pas du tri des dossiers.

    `get_scenario_list_for_phase` rend `sorted(set(...))` sur des chemins complets, et
    `holdout_hard` trie AVANT `holdout_regular`. Un `[0]` nu ne mesurait qu'un scenario sur
    quatre, et basculait du regular vers le hard le jour ou l'agent gagnait un dossier
    `holdout_hard/` : le win-rate baissait sans aucun changement de code, et se lisait comme
    une regression du modele.
    """
    config = _agent_scenarios_tree(tmp_path, "AgentX", holdout_regular=True, holdout_hard=True)

    resolved = train.resolve_final_eval_scenarios(config, "AgentX", "x1")

    assert len(resolved) == 2, f"un split a ete ecarte : {resolved}"
    assert any("holdout_regular" in path for path in resolved)
    assert any("holdout_hard" in path for path in resolved)


def test_the_final_eval_accepts_hard_alone(tmp_path: Path) -> None:
    """`holdout_hard` seul reste un holdout : le mesurer vaut mieux que refuser d'evaluer."""
    config = _agent_scenarios_tree(tmp_path, "AgentX", holdout_hard=True)

    resolved = train.resolve_final_eval_scenarios(config, "AgentX", "x1")

    assert len(resolved) == 1 and "holdout_hard" in resolved[0]


def test_the_final_eval_refuses_to_run_without_any_holdout(tmp_path: Path) -> None:
    """Le fail-fast lui-meme : sans dossier holdout, l'erreur tombe AVANT l'entrainement.

    C'est la moitie de la valeur du deplacement dans `main()` — un run de plusieurs heures ne
    doit pas se terminer en code 1 sur un dossier absent.
    """
    config = _agent_scenarios_tree(tmp_path, "AgentX", training=True)

    with pytest.raises(FileNotFoundError, match="holdout_regular"):
        train.resolve_final_eval_scenarios(config, "AgentX", "x1")


def test_the_two_holdout_paths_share_one_resolver() -> None:
    """`--test-only` et `--test-episodes` repondent la MEME chose a « quel holdout ? ».

    Le bloc `--test-only` open-codait sa propre resolution : meme appel, meme `[0]`, mais son
    propre message d'erreur — deux reponses selon la porte d'entree, et le `[0]` nu du split
    dur reproduit a deux endroits.
    """
    main_code = _function_code(train.main)
    assert main_code.count("resolve_final_eval_scenarios(") >= 2, (
        "le bloc --test-only doit passer par le resolveur commun"
    )
    assert "scenario_type='holdout'" not in main_code and 'scenario_type="holdout"' not in main_code, (
        "main() resout encore un holdout a la main au lieu d'appeler le resolveur"
    )


def test_the_agent_argument_is_stripped_not_just_checked() -> None:
    """`--agent " CoreAgent"` : la validation regardait `value.strip()` mais rendait `value`.

    L'espace se propageait dans `config/agents/ CoreAgent/` et `ai/models/ CoreAgent/` — deux
    chemins qui n'existent pas, ou pire, deux dossiers crees a cote des vrais.
    """
    import argparse

    assert train._non_empty_agent("  CoreAgent  ") == "CoreAgent"
    for blank in ("", "   ", "\t"):
        with pytest.raises(argparse.ArgumentTypeError, match="ne peut pas etre vide"):
            train._non_empty_agent(blank)


def test_the_final_eval_uses_the_rewards_key_as_controlled_agent() -> None:
    """`controlled_agent` de l'eval finale = cle de RECOMPENSES, comme ses deux jumeaux.

    `train_model` et l'eval `--test-only` passent tous deux `args.rewards_config` (elle porte
    le suffixe de phase). L'eval post-entrainement passait `--agent` : sur un
    `--agent A --rewards-config B`, l'« Average Reward » final etait calcule sous la table de A
    alors que l'entrainement l'avait optimisee sous celle de B. Deux chiffres incomparables
    sous le meme libelle.
    """
    code = _function_code(train.test_trained_model)
    assert "controlled_agent=rewards_config_name" in code, (
        "l'eval finale doit prendre la cle de recompenses comme agent controle"
    )
    assert "agent_key" not in code, "l'eval finale ne doit plus connaitre --agent"


def test_the_final_eval_spends_its_episodes_on_every_holdout_scenario() -> None:
    """Les episodes sont REPARTIS sur tous les scenarios rendus, pas verses au premier.

    Verifie sur le comportement, pas sur le texte : un faux moteur compte les `reset()` par
    scenario. Avec 5 episodes sur 2 scenarios, on attend 3 + 2 — et zero episode perdu.
    """
    resets: list[str] = []

    class _FakeEnv:
        def __init__(self, **kwargs):
            self._scenario = kwargs["scenario_file"]
            assert kwargs["controlled_agent"] == "RewardsKey"

        def reset(self):
            resets.append(self._scenario)
            return object(), {"winner": 0}

        def step(self, _action):
            return object(), 1.0, True, False, {"winner": 0}

        def close(self):
            pass

    class _FakeModel:
        @staticmethod
        def predict(_obs, deterministic=True):
            _ = deterministic
            return 0, None

    import ai.train as train_mod

    original_setup, original_registry = train_mod.setup_imports, None
    train_mod.setup_imports = lambda: (_FakeEnv, None)
    import ai.unit_registry as unit_registry_mod
    original_registry = unit_registry_mod.UnitRegistry
    unit_registry_mod.UnitRegistry = lambda: object()
    try:
        win_rate, _avg = train_mod.test_trained_model(
            _FakeModel(), 5, "x1", "RewardsKey", ["/h/a.json", "/h/b.json"],
        )
    finally:
        train_mod.setup_imports = original_setup
        unit_registry_mod.UnitRegistry = original_registry

    assert len(resets) == 5, f"episodes perdus ou dupliques : {resets}"
    assert resets.count("/h/a.json") == 3 and resets.count("/h/b.json") == 2, resets
    assert win_rate == 1.0


def test_both_config_key_arguments_are_stripped() -> None:
    """JUMEAU : `--agent` ET `--rewards-config` nomment un dossier `config/agents/<cle>/`.

    Ne nettoyer que le premier laissait `--rewards-config " CoreAgent"` atteindre exactement
    les memes chemins — la faille que le strip etait cense fermer.
    """
    import argparse

    for flag in ("--agent", "--rewards-config"):
        parse = train._non_empty_key(flag)
        assert parse("  CoreAgent  ") == "CoreAgent", flag
        for blank in ("", "   ", "\t"):
            with pytest.raises(argparse.ArgumentTypeError, match="ne peut pas etre vide"):
                parse(blank)

    parser_source = _function_code(train.main)
    rewards_decl = parser_source[parser_source.index("'--rewards-config'"):][:400]
    assert "_non_empty_key" in rewards_decl, (
        "--rewards-config declare sans validateur : le jumeau de --agent est reste ouvert"
    )
