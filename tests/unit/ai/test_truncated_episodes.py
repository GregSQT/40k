"""Verrou des épisodes TRONQUÉS — le garde anti-runaway ne doit plus être muet.

Une troncature n'est pas une fin de partie : c'est le symptôme d'une BOUCLE dans le moteur
(`w40k_core.step_with_mask`, garde `_episode_step_limit`). Le diagnostic complet était assemblé
puis jeté — `print` d'un worker noyé dans la console à `n_envs=48`, et `add_debug_log` muet hors
`debug_mode`. Le compteur d'épisodes, lui, divergeait : le run s'arrête sur la somme des `dones`
(troncatures comprises) alors que `metrics_tracker.episode_count` — celui qui part dans
`_run_state.json` — n'avançait que sur `terminated`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json"
)

TRUNCATION_DEBUG_KEYS = {
    "episode", "turn", "phase", "scenario", "scenario_path", "player", "fight_subphase",
    "active_unit_id", "active_unit_name", "steps", "step_limit",
    "move_pool", "shoot_pool", "charge_pool", "shoot_debug", "last_action_debug",
}


def test_the_engine_publishes_its_truncation_diagnostic() -> None:
    """Le moteur POSE le diagnostic dans `info` : c'est la seule sortie qui traverse le VecEnv.

    Le plafond est abaissé pour CONSTRUIRE la troncature — l'espérer d'une graine ou d'un bug
    réel ne serait pas un test. Ce qu'on observe, c'est le contrat de sortie du garde, pas la
    boucle qui l'a déclenché.
    """
    import numpy as np

    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent",
        scenario_file=SCENARIO,
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,  # UN environnement joue en serie (engine/episode_schedule.py)
    )
    eng.reset(seed=0)
    eng._episode_step_limit_cache = 5
    eng._get_episode_step_limit = lambda: 5  # type: ignore[method-assign]

    rng = np.random.default_rng(0)
    info = None
    for _ in range(200):
        mask = eng.get_action_mask()
        legal = np.flatnonzero(mask)
        assert legal.size > 0, "aucune action légale : le moteur est bloqué, pas tronqué"
        _obs, _r, terminated, truncated, info = eng.step(int(rng.choice(legal)))
        if truncated:
            break
        if terminated:
            eng.reset()
    assert info is not None and info.get("truncation_reason") == "episode_steps_limit", (
        "le garde anti-runaway n'a pas été atteint : le test n'observe rien"
    )

    debug = info["truncation_debug"]
    assert set(debug) == TRUNCATION_DEBUG_KEYS
    assert debug["step_limit"] == 5 and debug["steps"] > 5
    assert debug["scenario"] == os.path.basename(SCENARIO)
    assert debug["phase"] is not None


class _StubWriter:
    def __init__(self) -> None:
        self.scalars: list = []

    def add_scalar(self, tag, value, step):  # noqa: D102
        self.scalars.append((tag, value, step))

    def add_scalars(self, *_a, **_k):  # noqa: D102
        pass

    def add_custom_scalars(self, *_a, **_k):  # noqa: D102
        pass

    def flush(self):  # noqa: D102
        pass


def _stub_writer(tracker) -> _StubWriter:
    """Le writer double pose par `_tracker`, retrouve avec son vrai type."""
    writer = tracker.writer
    assert isinstance(writer, _StubWriter)
    return writer


def _tracker(tmp_path, initial: int = 0):
    from ai.metrics_tracker import W40KMetricsTracker

    tracker = W40KMetricsTracker(
        "ArmageddonAgent", str(tmp_path), perf_window=10, perf_window_fast=5,
        initial_episode_count=initial,
    )
    tracker.writer = _StubWriter()  # type: ignore[assignment]
    return tracker


def _journal_path(tracker) -> str:
    """Chemin du journal, EXIGE. `TruncationLog.path` est optionnel (mode sans dossier de run) ;
    ici on teste le mode nominal, donc son absence serait un defaut du test lui-meme."""
    path = tracker.truncation_log.path
    assert path is not None, "le tracker nominal a un dossier de run, donc un journal"
    return path


def _journal_rows(tracker) -> list:
    """Lignes du journal, deserialisees."""
    with open(_journal_path(tracker), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_a_truncated_episode_counts_and_leaves_a_trace(tmp_path) -> None:
    """Il COMPTE (c'est ce compteur qui est persisté) et il LAISSE une ligne exploitable."""
    tracker = _tracker(tmp_path, initial=1000)
    payload = {"phase": "shoot", "turn": 3, "steps": 900, "step_limit": 800}

    tracker.log_truncated_episode("episode_steps_limit", dict(payload))

    assert tracker.episode_count == 1001, (
        "le run s'arrête sur la somme des `dones` : un épisode tronqué en fait partie"
    )
    assert tracker.truncation_counts["training"] == {"episode_steps_limit": 1}
    [row] = _journal_rows(tracker)
    assert {k: row[k] for k in payload} == payload
    assert row["reason"] == "episode_steps_limit"
    assert row["run"] == tracker.truncation_log.run_tag, (
        "le journal traverse les runs : sans marqueur, deux entrainements sont indiscernables"
    )


def test_the_curve_exists_even_when_nothing_is_truncated(tmp_path) -> None:
    """VERT VACANT : une courbe « doit valoir 0 » qui n'a aucun point ne dit rien.

    Emise seulement AU MOMENT d'une troncature, elle était absente du cas nominal — donc
    indiscernable d'une métrique jamais branchée. Un tableau de bord qui n'affiche rien quand
    tout va bien ne permet pas de conclure que tout va bien.
    """
    tracker = _tracker(tmp_path)
    tracker.log_episode_end({
        "total_reward": 1.0, "winner": 1, "episode_length": 40,
        "controlled_player": 1, "deployment_mode": None,
    })

    points = [
        s for s in _stub_writer(tracker).scalars
        if s[0] == "00_critical/t_truncated_episodes"
    ]
    assert points == [("00_critical/t_truncated_episodes", 0, 1)], (
        "un episode NORMAL doit poser un point a 0 : sans lui la courbe n'existe pas"
    )


def test_the_curve_counts_training_only_and_restarts_with_the_run(tmp_path) -> None:
    """Portée et remise à zéro de la courbe — les deux décisions actées, verrouillées.

    L'abscisse est `episode_count`, qui ne compte que les épisodes d'ENTRAÎNEMENT : une
    troncature d'éval n'a pas de place sur cet axe, elle vit dans le bilan de fin de run.
    Et le cumul est celui de CE run : sur un `--append`, `episode_count` repart de l'offset
    mais le compte repart de 0 — l'historique inter-runs est dans `truncations.jsonl`.
    """
    tracker = _tracker(tmp_path, initial=200_000)
    tracker.log_eval_truncations([{"reason": "episode_steps_limit", "bot_name": "tactical"}])
    tracker.log_truncated_episode("episode_steps_limit", {"phase": "move"})

    points = [
        s for s in _stub_writer(tracker).scalars
        if s[0] == "00_critical/t_truncated_episodes"
    ]
    assert points == [("00_critical/t_truncated_episodes", 1, 200_001)], (
        "l'eval ne doit pas peser sur la courbe, et le cumul repart de 0 a l'offset repris"
    )


def test_counting_survives_a_mode_without_a_run_directory(tmp_path) -> None:
    """Mode « éval seule » : pas de dossier de run, donc pas de journal — mais un COMPTE.

    C'est le silence le plus coûteux de la famille : le moteur pose `winner = -1` sur une
    troncature, donc sans ce compte elle entre en NUL dans le score PUBLIÉ. Le bilan annonce
    l'absence de journal au lieu de la taire.
    """
    from ai.truncation_log import TruncationLog

    log = TruncationLog(None)
    log.record_eval_batch([
        {"reason": "episode_steps_limit", "bot_name": "tactical"},
        {"reason": "episode_steps_limit", "bot_name": "control"},
    ])

    assert log.counts["eval"] == {"episode_steps_limit": 2}
    assert log.dropped == 0, "rien n'est « perdu » : il n'y a simplement pas de journal a ecrire"
    text = "\n".join(log.summary_lines())
    assert "2 episode(s)" in text
    assert "Aucun journal ecrit" in text, (
        "l'absence de journal doit etre ANNONCEE, sinon le bilan laisse croire a une trace"
    )


def test_a_truncated_episode_stays_out_of_the_reward_curves(tmp_path) -> None:
    """Il n'a ni reward ni longueur exploitables : il ne doit alimenter aucune courbe de jeu."""
    tracker = _tracker(tmp_path)
    tracker.log_truncated_episode("episode_steps_limit", {"phase": "move"})

    assert tracker.all_episode_rewards == []
    assert tracker.all_episode_lengths == []
    assert tracker.all_episode_wins == []
    tags = {tag for tag, _v, _s in _stub_writer(tracker).scalars}
    assert tags == {"00_critical/t_truncated_episodes"}


def test_the_callback_routes_a_truncated_info_to_the_tracker(tmp_path) -> None:
    """Câblage : `info` tronqué → `log_truncated_episode`, avec le diagnostic du moteur.

    C'est le point que le défaut occupait : `_on_step` ne réagissait qu'à `'episode' in info`,
    donc une troncature ne produisait RIEN côté process principal.
    """
    from ai.training_callbacks import MetricsCollectionCallback

    tracker = _tracker(tmp_path)

    class _FakeModel:
        num_timesteps = 4242

    cb = MetricsCollectionCallback(tracker, _FakeModel())
    info = {
        "truncation_reason": "episode_steps_limit",
        "truncation_debug": {"phase": "fight", "turn": 2},
    }
    cb._handle_truncated_episode(info, env_index=7)

    [row] = _journal_rows(tracker)
    assert {k: v for k, v in row.items() if k != "run"} == {
        "scope": "training",
        "reason": "episode_steps_limit",
        "phase": "fight", "turn": 2,
        "env_index": 7, "num_timesteps": 4242,
    }
    assert tracker.episode_count == 1


def test_monitor_stamps_episode_on_truncation_too() -> None:
    """Le fait qui gouverne l'ordre des branches, relevé sur le VRAI `Monitor` de SB3.

    Il pose `info["episode"]` sur `terminated OR truncated`. Tout le chemin d'entraînement est
    Monitor-wrappé : tester `'episode' in info` en premier rend la branche des troncatures
    inatteignable. Vérifié en exécutant Monitor, pas déduit de sa documentation.
    """
    import gymnasium as gym
    import numpy as np
    from stable_baselines3.common.monitor import Monitor

    class _AlwaysTruncates(gym.Env):
        observation_space = gym.spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32)
        action_space = gym.spaces.Discrete(1)

        def reset(self, *, seed=None, options=None):
            return np.zeros(1, dtype=np.float32), {}

        def step(self, action):
            return (
                np.zeros(1, dtype=np.float32), 0.0, False, True,
                {"truncation_reason": "episode_steps_limit"},
            )

    env = Monitor(_AlwaysTruncates())
    env.reset()
    *_, info = env.step(0)
    assert "episode" in info, (
        "si Monitor cessait de le poser sur une troncature, l'ordre des branches de `_on_step` "
        "n'aurait plus de raison d'être — c'est ce fait qui le justifie"
    )


def test_on_step_routes_a_truncation_even_when_monitor_stamped_it(tmp_path) -> None:
    """Le VRAI point d'entrée du callback, avec un `info` de la FORME que la production produit.

    Motif d'échec récurrent de ce dépôt : du code corrigé et testé que le chemin de production
    n'appelle jamais. Ici il l'était deux fois — la branche était morte derrière `'episode' in
    info`, et la première version de ce test fabriquait un `info` SANS la clé du Monitor, donc
    elle ne pouvait pas le voir (vert vacant). L'`info` porte les deux clés, comme en vrai.
    """
    from ai.training_callbacks import MetricsCollectionCallback

    tracker = _tracker(tmp_path)

    class _FakeModel:
        num_timesteps = 11

    cb = MetricsCollectionCallback(tracker, _FakeModel())
    cb.locals = {  # type: ignore[assignment]
        "infos": [{
            "episode": {"r": -1.5, "l": 900, "t": 12.0},  # pose par Monitor, troncature comprise
            "TimeLimit.truncated": True,                  # pose par les VecEnv de SB3
            "truncation_reason": "episode_steps_limit",
            "truncation_debug": {"phase": "shoot"},
        }],
    }
    cb._on_step()

    assert sum(tracker.truncation_counts["training"].values()) == 1, (
        "`_on_step` n'a pas routé la troncature : la branche est occultée par `'episode' in info`"
    )
    assert tracker.all_episode_rewards == [], (
        "l'épisode tronqué est parti dans `_handle_episode_end` : ses r/l entrent dans les courbes"
    )


def test_a_truncation_without_its_diagnostic_is_a_wiring_defect(tmp_path) -> None:
    """Le moteur pose les deux clés ensemble : une trace sans diagnostic ne dirait rien d'utile."""
    from shared.data_validation import ConfigurationError
    from ai.training_callbacks import MetricsCollectionCallback

    class _FakeModel:
        num_timesteps = 1

    cb = MetricsCollectionCallback(_tracker(tmp_path), _FakeModel())
    with pytest.raises((ConfigurationError, KeyError)):
        cb._handle_truncated_episode({"truncation_reason": "episode_steps_limit"}, env_index=0)


def test_an_eval_truncation_is_counted_and_traced_without_touching_episode_count(tmp_path) -> None:
    """Les troncatures d'EVAL remontent aussi — sinon le bilan ment.

    Le moteur pose `winner = -1` sur une troncature : côté éval elle se comptait en NUL et
    n'existait nulle part. Une boucle qui ne se reproduit qu'en éval (`deterministic=True`,
    rosters du holdout) faisait donc terminer le run sur « ✅ Troncatures : 0 ».

    `episode_count` ne bouge PAS : un épisode d'éval n'est pas un épisode d'entraînement, et ce
    compteur est celui qui est persisté dans `_run_state.json`.
    """
    tracker = _tracker(tmp_path, initial=500)

    tracker.log_eval_truncations([
        {"reason": "episode_steps_limit", "bot_name": "tactical", "phase": "shoot"},
        {"reason": "episode_steps_limit", "bot_name": "control", "phase": "fight"},
    ])

    assert tracker.episode_count == 500, (
        "un episode d'eval n'est pas un episode joue par le modele en apprentissage"
    )
    assert tracker.truncation_counts["eval"] == {"episode_steps_limit": 2}
    assert tracker.truncation_counts["training"] == {}
    rows = _journal_rows(tracker)
    assert [r["scope"] for r in rows] == ["eval", "eval"]
    assert [r["bot_name"] for r in rows] == ["tactical", "control"]


#: Les deux facons de router des troncatures d'eval. `main` (`--test-only`) n'a PAS de tracker :
#: il ne produit aucune courbe. Il compte quand meme, directement sur un `TruncationLog` — sinon
#: ses troncatures sortent en NUL dans le score PUBLIE, le plus visible des trois silences.
#: Aucune exemption : produire des resultats d'eval sans les compter n'a pas de justification.
EVAL_TRUNCATION_ROUTES = {"log_eval_truncations", "record_eval_batch"}


def test_concurrent_truncations_respect_the_journal_bound(tmp_path) -> None:
    """L'eval de gating tourne sur le thread `bot-eval`, l'entrainement sur le thread principal.

    L'etat VRAIMENT partage n'est pas les compteurs — les deux portees ont des cles disjointes,
    elles ne se marchent pas dessus — mais le JOURNAL : `written`, `dropped`, et le fichier.
    `if written >= max_lines` puis `written += 1` est un lire-modifier-ecrire ; entrelace, deux
    threads franchissent tous deux le garde et la borne est depassee. Une premiere version de ce
    test observait les compteurs et restait donc VERTE sans verrou : elle ne regardait pas la
    bonne chose (c'est le defaut « controle qui regarde le mauvais objet », deja vecu ici).

    La fenetre est CONSTRUITE : la serialisation d'une ligne cede la main, exactement entre le
    garde et l'incrementation.
    """
    import threading
    import time

    class _SlowToSerialize:
        def __str__(self) -> str:
            time.sleep(0.005)
            return "slow"

    tracker = _tracker(tmp_path)
    log = tracker.truncation_log
    per_thread = 10
    log.max_lines = per_thread  # la moitie des lignes doit etre refusee

    def _train() -> None:
        for _ in range(per_thread):
            tracker.log_truncated_episode(
                "episode_steps_limit", {"phase": "move", "slow": _SlowToSerialize()}
            )

    def _eval() -> None:
        for _ in range(per_thread):
            tracker.log_eval_truncations([
                {"reason": "episode_steps_limit", "phase": "shoot", "slow": _SlowToSerialize()},
            ])

    threads = [threading.Thread(target=_train), threading.Thread(target=_eval)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert log.counts["training"]["episode_steps_limit"] == per_thread
    assert log.counts["eval"]["episode_steps_limit"] == per_thread
    assert len(_journal_rows(tracker)) == log.max_lines, (
        "la borne du journal a ete franchie par deux threads a la fois"
    )
    assert log.written == log.max_lines
    assert log.dropped == per_thread, "les lignes refusees doivent etre comptees, pas perdues"


def test_one_gym_step_is_at_least_one_engine_step() -> None:
    """La relation qui rend le backstop incapable de preempter le garde moteur — MESUREE.

    Un step gym vaut PLUSIEURS steps moteur (tour du bot, WAIT forces — cf.
    `BotControlledEnv.step`). Le compteur du moteur avance donc au moins aussi vite que celui de
    la boucle d'eval : il atteint SON plafond en premier, quelle que soit la taille du roster.

    Une version precedente de ce fichier verrouillait l'inverse — « la boucle preempte le
    moteur » — et son test passait parce que sa doublure avancait 1:1. Les deux compteurs n'ont
    pas la meme unite ; c'est ce qu'il fallait etablir, sur le vrai wrapper, pas sur une doublure.
    """
    import numpy as np
    from sb3_contrib.common.maskable.utils import get_action_masks

    from ai.bot_evaluation import _create_eval_env

    env = _create_eval_env(
        bot_name="greedy", bot_type="greedy", randomness_config={"greedy": 0.15},
        scenario_file=SCENARIO,
        training_config_name="x1_debug", rewards_config_name="ArmageddonAgent",
        controlled_agent="ArmageddonAgent", base_agent_key="ArmageddonAgent",
        debug_mode=False, agent_seat_mode="p1", agent_seat_seed=0,
    )
    rng = np.random.default_rng(0)
    env.reset(seed=0)
    gym_steps, done = 0, False
    while not done and gym_steps < 2000:
        legal = np.flatnonzero(np.asarray(get_action_masks(env), dtype=bool))
        assert legal.size > 0, "aucune action legale : le moteur est bloque"
        _obs, _r, terminated, truncated, _info = env.step(int(rng.choice(legal)))
        gym_steps += 1
        done = terminated or truncated

    engine_calls = env.engine._episode_step_calls
    assert gym_steps > 0, "l'episode n'a joue aucun step : le test n'observe rien"
    assert engine_calls >= gym_steps, (
        f"un step gym vaut au moins un step moteur ({engine_calls} < {gym_steps}) : sans cette "
        f"relation, la boucle d'eval pourrait preempter le garde anti-runaway du moteur"
    )


def test_the_backstop_records_instead_of_scoring_a_silent_loss(monkeypatch) -> None:
    """Quand le backstop tire vraiment (le moteur n'a pas de plafond — durée illimitée), il TRACE.

    Sans ça, `winner is None` tombait dans le `else` du comptage : une partie qui n'a pas fini
    était portée au débit du modèle, et l'incident n'existait nulle part.
    """
    import ai.bot_evaluation as be

    class _Engine:
        game_state = {"units": []}
        # `_eval_worker_task` ventile le win-rate par roster et lit cet attribut en acces DIRECT.
        # `None` = scenario sans roster declare : la doublure porte le contrat, elle ne le contourne pas.
        _scenario_roster_info = None

        def _get_episode_step_limit(self):
            return None  # Endless Duty : pas de plafond d'episode cote moteur

    class _NeverEndsEnv:
        engine = _Engine()

        def reset(self, seed=None):
            # `controlled_player` : le siege de l'episode, publie par `BotControlledEnv` a chaque
            # reset et lu par la tache d'evaluation pour sa ventilation par siege. La doublure
            # porte le contrat, elle ne le contourne pas.
            return _obs(), {"controlled_player": 1}

        def action_masks(self):
            return _mask()

        def get_wrapper_attr(self, name):
            return getattr(self, name)

        def step(self, _action):
            return _obs(), 0.0, False, False, {"winner": None, "controlled_player": 0}

        def get_shoot_stats(self):
            return {}

        def close(self):
            pass

    _install_worker(monkeypatch, be, _NeverEndsEnv())
    result = be._eval_worker_task(_task(max_steps_per_episode=7))

    [entry] = result["truncations"]
    assert entry["reason"] == "eval_loop_cap"
    assert entry["gym_steps"] == 7 and entry["gym_step_limit"] == 7
    assert "steps" not in entry and "step_limit" not in entry, (
        "ces deux cles portent des steps MOTEUR dans les lignes `episode_steps_limit` du "
        "meme journal : un step gym en vaut plusieurs, les melanger rend les lignes "
        "incomparables"
    )
    assert entry["engine_step_limit"] is None
    assert result["draws"] == 1, "une partie qui n'a pas fini n'est pas une defaite du modele"
    assert result["losses"] == 0


def test_the_journal_creates_its_own_directory(tmp_path) -> None:
    """Le journal possède son dossier — il ne peut pas dépendre du writer TensorBoard.

    Le mode « éval seule » construit un `TruncationLog` SANS writer, depuis le `tensorboard_log`
    du modèle : dossier purgé, ou jamais créé pour un modèle copié d'ailleurs. La première
    troncature levait `FileNotFoundError` au milieu de `record_eval_batch` et faisait échouer
    l'évaluation avant l'impression du score — perdre la mesure à cause de sa trace.
    """
    from ai.truncation_log import TruncationLog

    absent = tmp_path / "tensorboard" / "x1_ArmageddonAgent" / "ArmageddonAgent"
    assert not absent.exists()

    log = TruncationLog(str(absent))
    log.record_eval_batch([{"reason": "episode_steps_limit", "phase": "shoot"}])

    assert log.path is not None and os.path.exists(log.path)
    assert log.counts["eval"]["episode_steps_limit"] == 1


def test_a_write_error_loses_the_line_not_the_evaluation(tmp_path, monkeypatch) -> None:
    """Disque plein, droits, montage disparu : la LIGNE est perdue, pas la mesure.

    Le score qu'on vient d'obtenir coûte des heures ; la trace de l'incident non. Une `OSError`
    remontait de `record_eval_batch` et tuait l'éval AVANT l'impression du score — exactement la
    faute que ce journal existe pour éviter, commise par le journal lui-même.

    Ce n'est pas un repli silencieux : le COMPTE reste juste (il est pris avant l'écriture) et le
    bilan ANNONCE les lignes perdues avec la cause.
    """
    import builtins

    from ai.truncation_log import TruncationLog

    log = TruncationLog(str(tmp_path / "run"))
    real_open = builtins.open

    def _refuse(path, *a, **k):
        if str(path) == log.path:
            raise OSError(28, "No space left on device")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", _refuse)
    log.record_eval_batch([{"reason": "episode_steps_limit", "phase": "shoot"}])
    monkeypatch.undo()

    assert log.counts["eval"]["episode_steps_limit"] == 1, "le compte doit survivre a l'ecriture"
    assert log.failed == 1 and log.written == 0
    text = "\n".join(log.summary_lines())
    assert "PERDUE" in text and "No space left" in text, (
        "un journal qui n'a pas pu ecrire doit le DIRE : son silence se lirait comme un zero"
    )


def test_every_eval_producer_routes_its_truncations() -> None:
    """Verrou de MIROIR : le même oubli s'est produit TROIS fois sur ce lot.

    Il y a quatre producteurs de résultats d'éval (`_evaluate_against_bots` et
    `_run_final_bot_eval` dans le callback, l'éval finale de `train_with_scenario_rotation`, et
    le chemin `--test-only`). Chacun doit router ses troncatures, sans quoi une boucle rencontrée
    là se compte en NUL (`winner = -1`) et le run finit sur « ✅ Troncatures : 0 ».

    Vérifié sur la source : jouer une éval réelle demanderait un modèle entraîné et des minutes.
    Ce que ce test attrape, c'est précisément ce qu'une revue humaine a laissé passer deux fois —
    un producteur ajouté sans sa ligne de routage.
    """
    import ast

    for rel in ("ai/train.py", "ai/training_callbacks.py"):
        with open(os.path.join(PROJECT_ROOT, rel), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = {
                sub.func.id if isinstance(sub.func, ast.Name) else getattr(sub.func, "attr", "")
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
            }
            if "evaluate_against_bots" not in called:
                continue
            assert called & EVAL_TRUNCATION_ROUTES, (
                f"{rel}::{node.name} produit des resultats d'eval sans router ses troncatures : "
                f"une boucle rencontree la sortira comptee en NUL et le bilan affichera 0"
            )


def _obs():
    import numpy as np
    return np.zeros(4, dtype=np.float32)


def _mask():
    import numpy as np
    return np.ones(3, dtype=bool)


def _task(**overrides) -> dict:
    """Tache d'eval minimale, aux cles reellement lues par `_eval_worker_task`."""
    task = {
        "bot_name": "tactical",
        "bot_type": "tactical",
        "randomness_config": {},
        "scenario_file": "/tmp/scenario_holdout.json",
        "scenario_name": "scenario_holdout",
        "n_episodes": 1,
        "base_seed": 0,
        "scenario_index": 0,
        "max_steps_per_episode": 10,
        "deterministic": True,
        "config_params": {},
    }
    task.update(overrides)
    return task


def _install_worker(monkeypatch, be, env) -> None:
    """Branche l'env double et un modele muet dans le worker d'eval."""
    import numpy as np

    class _FakeModel:
        def predict(self, _obs, action_masks=None, deterministic=True):
            return np.array([0]), None

    monkeypatch.setattr(be, "_create_eval_env", lambda **_k: env)
    monkeypatch.setattr(be, "_worker_model", _FakeModel(), raising=False)
    monkeypatch.setattr(be, "_worker_obs_normalizer", None, raising=False)
    monkeypatch.setattr(be, "_agent_faction_from_engine", lambda _e: "SpaceMarine")


def test_the_eval_worker_records_the_truncation_it_meets(monkeypatch) -> None:
    """La COLLECTE côté worker, pas seulement son routage.

    Le worker tourne dans un process séparé : son résultat est le seul canal. Sans cette
    collecte, le moteur posant `winner = -1`, une troncature d'éval se comptait en NUL et
    disparaissait — et un test qui ne vérifie que le routage reste vert (constaté).
    """
    import numpy as np

    import ai.bot_evaluation as be

    class _FakeEngine:
        game_state = {"units": []}
        # Idem `_Engine` ci-dessus : ventilation par roster, acces direct, `None` = sans roster.
        _scenario_roster_info = None

        def _get_episode_step_limit(self):
            # Le worker aligne son backstop dessus : la doublure porte le contrat, elle ne
            # le contourne pas.
            return 500

    class _TruncatingEnv:
        engine = _FakeEngine()

        def reset(self, seed=None):
            # Cf. `_NeverEndsEnv` plus haut : le siege de l'episode est publie au reset.
            return np.zeros(4, dtype=np.float32), {"controlled_player": 1}

        def action_masks(self):
            return np.ones(3, dtype=bool)

        def get_wrapper_attr(self, name):
            # `get_action_masks` de sb3_contrib passe par la : la doublure porte le contrat
            # gymnasium reellement emprunte, elle ne le contourne pas.
            return getattr(self, name)

        def step(self, _action):
            return (
                np.zeros(4, dtype=np.float32), 0.0, False, True,
                {
                    "winner": -1,
                    "controlled_player": 0,
                    "truncation_reason": "episode_steps_limit",
                    "truncation_debug": {"phase": "shoot", "turn": 4},
                },
            )

        def get_shoot_stats(self):
            return {}

        def close(self):
            pass

    class _FakeModel:
        def predict(self, _obs, action_masks=None, deterministic=True):
            return np.array([0]), None

    monkeypatch.setattr(be, "_create_eval_env", lambda **_k: _TruncatingEnv())
    monkeypatch.setattr(be, "_worker_model", _FakeModel(), raising=False)
    monkeypatch.setattr(be, "_worker_obs_normalizer", None, raising=False)
    monkeypatch.setattr(be, "_agent_faction_from_engine", lambda _e: "SpaceMarine")

    result = be._eval_worker_task({
        "bot_name": "tactical",
        "bot_type": "tactical",
        "randomness_config": {},
        "scenario_file": "/tmp/scenario_holdout.json",
        "scenario_name": "scenario_holdout",
        "n_episodes": 1,
        "base_seed": 0,
        "scenario_index": 0,
        "max_steps_per_episode": 10,
        "deterministic": True,
        "config_params": {},
    })

    assert result["draws"] == 1, "le moteur pose winner=-1 : l'episode reste compte en nul"
    [entry] = result["truncations"]
    assert entry["reason"] == "episode_steps_limit"
    assert entry["bot_name"] == "tactical"
    assert entry["phase"] == "shoot" and entry["turn"] == 4, "le diagnostic moteur doit suivre"
    assert entry["deterministic"] is True, (
        "une boucle qui ne se reproduit qu'en deterministe doit etre identifiable comme telle"
    )


def test_the_eval_path_routes_its_truncations_to_the_tracker(tmp_path, monkeypatch) -> None:
    """Câblage de la portée ÉVAL, sur le VRAI producteur de résultats.

    Le routage vit dans `_evaluate_against_bots` (où les résultats sont produits), pas dans
    `_apply_eval_results` (qui décide du gating) : ce dernier est appelé directement par les
    tests de gating, dont les doublures n'ont aucune raison de porter une route de
    journalisation. Motif « code testé mais jamais appelé » : sans ce test, supprimer la ligne
    de routage ne casserait rien.
    """
    import ai.training_callbacks as tc

    tracker = _tracker(tmp_path)
    from typing import Any, cast

    cb = tc.BotEvaluationCallback.__new__(tc.BotEvaluationCallback)
    cb.metrics_tracker = tracker
    cb.model = cast(Any, object())
    cb.training_config_name = "x1_debug"
    cb.rewards_config_name = "ArmageddonAgent"
    cb.n_eval_episodes = 1
    cb.eval_deterministic = True
    cb.show_eval_progress = False
    cb.async_eval_enabled = False
    cb.gate_display_state = None
    cb.scenario_pool = "holdout"
    cb.eval_count = 0

    monkeypatch.setattr(
        tc, "evaluate_against_bots", None, raising=False
    )
    import ai.bot_evaluation as be
    monkeypatch.setattr(
        be, "evaluate_against_bots",
        lambda **_k: {"truncations": [
            {"reason": "episode_steps_limit", "bot_name": "tactical", "phase": "shoot"},
        ]},
    )

    cb._evaluate_against_bots(eval_marker=2000)

    assert tracker.truncation_counts["eval"] == {"episode_steps_limit": 1}, (
        "le chemin d'eval ne route pas ses troncatures : le bilan de fin de run mentira"
    )


def test_the_summary_separates_training_from_eval(tmp_path) -> None:
    """Les deux portées ne se cherchent pas au même endroit : un total unique le cacherait."""
    from ai.train import print_truncation_summary

    tracker = _tracker(tmp_path)
    tracker.log_truncated_episode("episode_steps_limit", {"phase": "move"})
    tracker.log_eval_truncations([{"reason": "episode_steps_limit", "phase": "shoot"}])

    lines: list = []
    print_truncation_summary(tracker, lines.append)
    text = "\n".join(lines)

    assert "2 episode" in text
    assert "entrainement" in text and "eval" in text


@pytest.mark.parametrize("count", [0, 3])
def test_the_end_of_run_summary_states_the_count_and_the_path(tmp_path, count: int) -> None:
    """Un ZÉRO s'affiche aussi : « aucune troncature » est le résultat qu'on veut pouvoir lire."""
    from ai.train import print_truncation_summary

    tracker = _tracker(tmp_path)
    for _ in range(count):
        tracker.log_truncated_episode("episode_steps_limit", {"phase": "move"})

    lines: list = []
    print_truncation_summary(tracker, lines.append)
    text = "\n".join(lines)

    assert str(count) in text
    if count:
        assert _journal_path(tracker) in text
    else:
        assert _journal_path(tracker) not in text


def test_new_and_append_are_refused_together() -> None:
    """`--new` crée un modèle neuf, `--append` continue l'existant : jamais les deux.

    Deux `store_true` indépendants ; le code choisissait `--new` en silence. Joué en sous-process
    sur le VRAI point d'entrée : c'est la ligne de commande qui est refusée, pas une fonction.
    """
    proc = subprocess.run(
        [sys.executable, "ai/train.py", "--agent", "ArmageddonAgent",
         "--training-config", "x1_debug", "--new", "--append"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert "--new et --append sont exclusifs" in proc.stdout + proc.stderr
