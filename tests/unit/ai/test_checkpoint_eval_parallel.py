"""Phase 4 / decision B — gate d'etape parallelise par unification des harnais d'eval.

`evaluate_against_checkpoints` ne joue plus d'episodes : elle construit des taches
`(archive x scenario x tranche)` executees par `_eval_worker_task`, la meme boucle d'episode que
l'evaluation contre les bots. Ces tests verrouillent ce que l'unification peut casser en silence.
"""

import os
import tempfile
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tests.unit.ai._fabriques import exploiter_probe_callback, pool_early_stopping_callback


# ── Graines : le decoupage en tranches doit reproduire la sequence sequentielle ──────────────


def test_episode_seed_partition_matches_sequential():
    """Toute partition de [0, N) rend exactement les graines de la boucle sequentielle.

    C'est la propriete qui autorise le decoupage : `_episode_seed` est une fonction pure de
    `(base_seed, bot_name, scenario_index, ep_idx)`. Une tranche doit donc porter l'index GLOBAL
    de son premier episode (`ep_offset`), jamais un index local reparti a zero.
    """
    from ai.bot_evaluation import _episode_seed

    sequential = [_episode_seed(42, "P0", 2, i) for i in range(300)]

    chunked: list = []
    offset = 0
    for size in (75, 75, 75, 75):
        chunked.extend(_episode_seed(42, "P0", 2, i) for i in range(offset, offset + size))
        offset += size

    assert chunked == sequential

    # PREUVE QUE LE TEST MORD : avec un index local (le defaut naif), les tranches 2 a 4 rejouent
    # les graines de la tranche 1 et la sequence diverge.
    naive: list = []
    for size in (75, 75, 75, 75):
        naive.extend(_episode_seed(42, "P0", 2, i) for i in range(size))
    assert naive != sequential


def test_task_builder_tiles_episode_offsets_without_gap_or_overlap(tmp_path):
    """Les tranches d'un scenario pavent [0, sc_eps) exactement, et partagent scenario_index."""
    tasks = _build_tasks(tmp_path, n_episodes=300, n_scenarios=4, n_workers=16)

    by_scenario: dict = {}
    for task in tasks:
        by_scenario.setdefault(task["scenario_index"], []).append(task)

    assert sorted(by_scenario) == [0, 1, 2, 3]
    total = 0
    for scenario_index, scenario_tasks in by_scenario.items():
        covered: list = []
        for task in scenario_tasks:
            start = int(task["ep_offset"])
            covered.extend(range(start, start + int(task["n_episodes"])))
            # Index GLOBAL du scenario, identique sur toutes les tranches : deux tranches du
            # meme scenario qui porteraient des index differents produiraient des graines
            # etrangeres a la sequence sequentielle.
            assert task["scenario_index"] == scenario_index
        assert covered == list(range(len(covered))), "trou, recouvrement ou ordre non monotone entre tranches"
        total += len(covered)
    assert total == 300


def test_task_builder_saturates_workers(tmp_path):
    """4 scenarios x 1 archive = 4 taches sans decoupage ; le decoupage doit saturer 16 workers."""
    tasks = _build_tasks(tmp_path, n_episodes=300, n_scenarios=4, n_workers=16)
    assert len(tasks) >= 16


def test_task_builder_serial_mode_does_not_chunk(tmp_path):
    """En serie, decouper multiplierait les constructions d'env sans aucun gain."""
    tasks = _build_tasks(
        tmp_path, n_episodes=300, n_scenarios=4, n_workers=1, use_subprocess=False
    )
    assert len(tasks) == 4


# ── Invariant 1 : injection de l'adversaire AVANT le premier reset ───────────────────────────


def test_frozen_model_injected_before_first_reset():
    """`_frozen_model` et son mtime sont poses avant le premier `reset()`.

    `_reload_self_play_snapshot_if_needed` est PARESSEUX (appele au reset) et ne rend la main que
    sur `self._self_play_snapshot_frozen and self._frozen_model is not None`. Injecter apres le
    premier reset, ou n'injecter que `_frozen_model` en laissant le mtime a None, laisserait l'env
    charger lui-meme l'archive en `MaskablePPO` NU : l'adversaire jouerait sur des observations
    normalisees par les stats du modele courant (violation R0b). Ca ne leve pas et ca ne crashe
    pas — ca rend un score faux. D'ou ce verrou.
    """
    from ai import bot_evaluation

    class _Stop(Exception):
        pass

    seen: dict = {}

    class _FakeEnv:
        def __init__(self):
            self._frozen_model = None
            self._frozen_model_mtime = None

        def reset(self, seed=None):
            seen["frozen_model"] = self._frozen_model
            seen["frozen_mtime"] = self._frozen_model_mtime
            raise _Stop

        def close(self) -> None:
            pass

    sentinel_model = object()

    with (
        patch.object(bot_evaluation, "_worker_model", MagicMock()),
        patch.object(bot_evaluation, "_eval_worker_load_model_if_needed"),
        patch.object(bot_evaluation, "_create_eval_env", return_value=_FakeEnv()),
        patch.object(
            bot_evaluation,
            "_worker_checkpoint_opponent",
            return_value=(sentinel_model, 123.0),
        ),
    ):
        with pytest.raises(_Stop):
            bot_evaluation._eval_worker_task(_checkpoint_task())

    assert seen["frozen_model"] is sentinel_model
    assert seen["frozen_mtime"] == 123.0


def test_worker_checkpoint_opponent_is_memoized_per_archive():
    """Un worker qui traite plusieurs tranches d'une meme archive ne recharge pas le zip."""
    from ai import bot_evaluation

    with (
        patch.dict(bot_evaluation._worker_ckpt_cache, {}, clear=True),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()) as load,
        patch.object(bot_evaluation, "_build_eval_obs_normalizer_for_worker", return_value=None),
        patch.object(bot_evaluation, "_NormalizedFrozenModel", side_effect=lambda m, n: m),
        patch("os.path.getmtime", return_value=1.0),
    ):
        first = bot_evaluation._worker_checkpoint_opponent("/tmp/a.zip", False, False, "cpu")
        second = bot_evaluation._worker_checkpoint_opponent("/tmp/a.zip", False, False, "cpu")
        bot_evaluation._worker_checkpoint_opponent("/tmp/b.zip", False, False, "cpu")

    assert first is second
    assert load.call_count == 2, "une archive distincte par chargement, pas une par appel"


# ── Invariant 3 : le compteur local d'episode suit la tranche ────────────────────────────────


def test_worker_task_forwards_ep_offset_as_episode_start_index():
    """Une tranche construit son env avec `episode_start_index = ep_offset`.

    `BotControlledEnv._episode_index` est LOCAL au wrapper et sert de materiau de graine a trois
    tirages : le siege joue quand `agent_seat_mode='random'` (le cas de x1_long), le self-play et
    le RNG du bot — tous batis sur `f"{global_seed}:{env_rank}:{episode_index}"`. Une tranche
    construite sans `episode_start_index` repart a 0 et rejoue le siege de l'episode 0, alors que
    ses graines d'episode, elles, sont correctes : la divergence est donc INVISIBLE cote graines.

    MESURE DU DEFAUT (2026-08-26, vrai chemin, model P1 vs archive P0, 8 episodes holdout) :
    3 victoires sur 8 en parallele contre 1 sur 8 en serie. Apres correction : 1 sur 8 des deux
    cotes. C'est ce que ce test verrouille.
    """
    from ai import bot_evaluation

    class _Stop(Exception):
        pass

    class _FakeEnv:
        def __init__(self):
            self._frozen_model = None
            self._frozen_model_mtime = None

        def reset(self, seed=None):
            raise _Stop

        def close(self) -> None:
            pass

    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return _FakeEnv()

    with (
        patch.object(bot_evaluation, "_worker_model", MagicMock()),
        patch.object(bot_evaluation, "_eval_worker_load_model_if_needed"),
        patch.object(bot_evaluation, "_create_eval_env", side_effect=_capture),
        patch.object(
            bot_evaluation, "_worker_checkpoint_opponent", return_value=(object(), 1.0)
        ),
    ):
        with pytest.raises(_Stop):
            bot_evaluation._eval_worker_task(_checkpoint_task(ep_offset=5, n_episodes=2))

    assert captured["episode_start_index"] == 5


def test_create_eval_env_forwards_episode_start_index():
    """`_create_eval_env` transmet `episode_start_index` a BotControlledEnv, sans le perdre."""
    from ai.bot_evaluation import _create_eval_env

    captured_kwargs: dict = {}

    class _FakeBotControlledEnv:
        def __init__(self, env, *args, **kwargs):
            captured_kwargs.update(kwargs)

    with (
        patch("ai.training_utils.setup_imports", return_value=(MagicMock(), None)),
        patch("ai.env_wrappers.BotControlledEnv", _FakeBotControlledEnv),
        patch("sb3_contrib.common.wrappers.ActionMasker", side_effect=lambda env, fn: env),
        patch("ai.unit_registry.UnitRegistry", return_value=MagicMock()),
    ):
        _create_eval_env(
            bot_name="P0",
            bot_type="P0",
            randomness_config={},
            scenario_file="scenario.json",
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            controlled_agent="ArmageddonAgent_x1",
            base_agent_key="ArmageddonAgent_x1",
            debug_mode=False,
            agent_seat_mode="p1",
            agent_seat_seed=None,
            checkpoint_zip="/tmp/ckpt.zip",
            checkpoint_label="P0",
            checkpoint_scenario_episodes=8,
            episode_start_index=5,
        )

    assert captured_kwargs.get("episode_start_index") == 5


# ── Invariant 2 : aucun mur de reference materialise sur le chemin checkpoint ────────────────


def test_checkpoint_tasks_consume_raw_scenario_files(tmp_path):
    """Le chemin checkpoint consomme les scenarios BRUTS, sans materialisation de murs.

    Le constructeur de taches des bots materialise des murs indexes par
    `(scenario_index + sum(ord(c) for c in bot_name)) % len(eval_wall_refs)`.
    Les appliquer ici changerait la valeur des scores du gate — donc leur comparabilite avec
    `curriculum.log` — et, `bot_name` valant l'etiquette d'etape, ferait dependre le terrain
    du nom de cette etiquette.
    """
    from ai import bot_evaluation

    with patch.object(bot_evaluation, "_materialize_eval_scenario_refs") as materialize:
        tasks = _build_tasks(tmp_path, n_episodes=8, n_scenarios=4, n_workers=4)

    materialize.assert_not_called()
    expected = {str(tmp_path / f"scenario_{i}.json") for i in range(4)}
    assert {task["scenario_file"] for task in tasks} == expected


# ── Archive incompatible : skip journalise, pas de crash de tache ────────────────────────────


def test_incompatible_archive_is_skipped_not_crashed(tmp_path):
    """Une archive §12.15 est ecartee dans le PARENT, avant construction des taches."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    good = tmp_path / "good.zip"
    bad = tmp_path / "bad.zip"
    good.touch()
    bad.touch()
    for i in range(2):
        (tmp_path / f"scenario_{i}.json").touch()

    def _load(path, device=None, **kwargs):
        if str(path) == str(bad):
            raise RuntimeError("Missing key policy.mlp_extractor.weight")
        return MagicMock()

    seen_tasks: list = []

    with (
        patch("config_loader.get_config_loader", return_value=_fake_config()),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / f"scenario_{i}.json") for i in range(2)],
        ),
        patch("sb3_contrib.MaskablePPO.load", side_effect=_load),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch(
            "ai.bot_evaluation._eval_worker_task",
            side_effect=lambda task, progress_callback=None: _canned_result(task),
        ) as worker_task,
    ):
        results = evaluate_against_checkpoints(
            model_path=str(good),
            checkpoint_archives=[(str(good), "P0"), (str(bad), "P1")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=4,
            controlled_agent="ArmageddonAgent_x1",
        )

    seen_tasks.extend(call.args[0] for call in worker_task.call_args_list)
    assert "P0" in results
    assert "P1" not in results, "l'archive incompatible ne doit produire aucun score"
    assert all(task["checkpoint_zip"] == str(good) for task in seen_tasks)


def test_non_missing_key_runtime_error_is_not_swallowed(tmp_path):
    """Seul « Missing key » vaut un skip §12.15 ; toute autre RuntimeError remonte."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    with (
        patch("config_loader.get_config_loader", return_value=_fake_config()),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / "scenario_0.json")],
        ),
        patch("sb3_contrib.MaskablePPO.load", side_effect=RuntimeError("disque illisible")),
    ):
        with pytest.raises(RuntimeError, match="disque illisible"):
            evaluate_against_checkpoints(
                model_path=str(archive),
                checkpoint_archives=[(str(archive), "P0")],
                training_config_name="x1_long",
                rewards_config_name="ArmageddonAgent_x1",
                n_episodes=2,
                controlled_agent="ArmageddonAgent_x1",
            )


# ── Denominateur : un episode non joue invalide la mesure, il ne la retrecit pas ─────────────


def test_failed_episodes_raise_instead_of_shrinking_denominator(tmp_path):
    """Un timeout de tache doit lever, jamais rendre un win-rate sur moins d'episodes.

    Le gate promeut ou refuse une etape sur ce chiffre : un denominateur tronque produirait un
    score d'allure normale calcule sur une fraction du budget demande.
    """
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    def _timeout_result(task, progress_callback=None):
        result = _canned_result(task)
        result["wins"] = 0
        result["failed_episodes"] = int(task["n_episodes"])
        result["timeout"] = True
        return result

    with (
        patch("config_loader.get_config_loader", return_value=_fake_config()),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / "scenario_0.json")],
        ),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation._eval_worker_task", side_effect=_timeout_result),
    ):
        with pytest.raises(RuntimeError, match="dénominateur tronqué"):
            evaluate_against_checkpoints(
                model_path=str(archive),
                checkpoint_archives=[(str(archive), "P0")],
                training_config_name="x1_long",
                rewards_config_name="ArmageddonAgent_x1",
                n_episodes=4,
                controlled_agent="ArmageddonAgent_x1",
            )


def test_capped_episode_counts_as_draw_and_keeps_win_rate(tmp_path):
    """Un episode plafonne devient un NUL trace, et le win-rate ne bouge pas.

    Ancien comportement : l'episode entrait dans `total` sans entrer dans aucun seau, et
    ressortait en `_timeouts`. Nouveau : il est compte en NUL avec une trace `eval_loop_cap`
    (V11 §0.61). `total` et `wins` sont identiques dans les deux formes, donc le RATIO est
    inchange — seule la ventilation D/T bouge, et `_timeouts` reste renseigne.
    """
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    def _one_win_one_cap(task, progress_callback=None):
        result = _canned_result(task)
        result["wins"] = 1
        result["losses"] = 0
        result["draws"] = 1
        result["truncations"] = [{"reason": "eval_loop_cap"}]
        return result

    with (
        patch("config_loader.get_config_loader", return_value=_fake_config()),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / "scenario_0.json")],
        ),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation._eval_worker_task", side_effect=_one_win_one_cap),
    ):
        results = evaluate_against_checkpoints(
            model_path=str(archive),
            checkpoint_archives=[(str(archive), "P0")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
        )

    assert results["P0_wins"] == 1
    assert results["P0_draws"] == 1
    assert results["P0_timeouts"] == 1
    # 1 victoire sur 2 episodes comptes : identique a ce que rendait la forme historique.
    assert results["P0"] == pytest.approx(0.5)


# ── Non-regression du chemin bot : ep_offset=0 ⇒ boucle inchangee ───────────────────────────


def test_bot_task_without_ep_offset_starts_at_zero():
    """Avec `ep_offset=0`, la boucle demarre a 0 — le chemin bot ne decoupe pas et ne bouge pas."""
    from ai import bot_evaluation

    class _Stop(Exception):
        pass

    seeds: list = []

    class _FakeEnv:
        def reset(self, seed=None):
            seeds.append(seed)
            raise _Stop

        def close(self) -> None:
            pass

    task = {
        "bot_name": "greedy",
        "bot_type": "greedy",
        "randomness_config": {},
        "scenario_file": "s.json",
        "scenario_name": "s",
        "n_episodes": 3,
        "base_seed": 42,
        "scenario_index": 1,
        "ep_offset": 0,
        "deterministic": True,
        "config_params": {},
        "max_steps_per_episode": 100,
    }

    with (
        patch.object(bot_evaluation, "_worker_model", MagicMock()),
        patch.object(bot_evaluation, "_eval_worker_load_model_if_needed"),
        patch.object(bot_evaluation, "_create_eval_env", return_value=_FakeEnv()),
    ):
        with pytest.raises(_Stop):
            bot_evaluation._eval_worker_task(task)

    assert seeds == [bot_evaluation._episode_seed(42, "greedy", 1, 0)]


def test_worker_task_seeds_from_ep_offset():
    """Une tranche demarrant a `ep_offset` rejoue les graines de CES episodes-la.

    C'est le verrou qui mord sur la boucle du worker : sans lui, un `range(n_episodes)` reparti
    a zero passerait tous les autres tests (le constructeur de taches pave correctement, et la
    tranche 0 est indiscernable), tout en faisant rejouer a chaque tranche les memes episodes.
    """
    from ai import bot_evaluation

    class _Stop(Exception):
        pass

    seeds: list = []

    class _FakeEnv:
        def __init__(self):
            self._frozen_model = None
            self._frozen_model_mtime = None

        def reset(self, seed=None):
            seeds.append(seed)
            raise _Stop

        def close(self) -> None:
            pass

    with (
        patch.object(bot_evaluation, "_worker_model", MagicMock()),
        patch.object(bot_evaluation, "_eval_worker_load_model_if_needed"),
        patch.object(bot_evaluation, "_create_eval_env", return_value=_FakeEnv()),
        patch.object(
            bot_evaluation, "_worker_checkpoint_opponent", return_value=(object(), 1.0)
        ),
    ):
        with pytest.raises(_Stop):
            bot_evaluation._eval_worker_task(
                _checkpoint_task(ep_offset=5, n_episodes=2, scenario_index=3)
            )

    assert seeds[0] == bot_evaluation._episode_seed(42, "P0", 3, 5)
    assert seeds[0] != bot_evaluation._episode_seed(42, "P0", 3, 0), (
        "une tranche a offset 5 ne doit pas rejouer l'episode 0"
    )


# ── Sonde exploiteur : elle evalue PENDANT l'entrainement, donc pas 16 workers ───────────────


def test_exploiter_probe_uses_intermediate_worker_count(tmp_path):
    """La sonde passe `bot_eval_n_workers_intermediate`, jamais le compte de l'eval finale.

    Avant la Phase 4, `evaluate_against_checkpoints` etait sequentielle : la sonde ne prenait
    aucun worker. Maintenant qu'elle parallelise, la laisser prendre `bot_eval_n_workers` (16)
    la ferait concourir avec les 24 workers de collecte du run — le regime documente par
    `validate_bot_eval_worker_params` : 47 Go de RSS et une evaluation 42 % PLUS LENTE qu'a 4.
    """
    archive = tmp_path / "target.zip"
    archive.touch()

    probe = exploiter_probe_callback(archive)

    with (
        patch(
            "ai.bot_evaluation.evaluate_against_checkpoints",
            return_value={"target": 0.5},
        ) as evaluate,
        # Le pool est desormais cree PARESSEUSEMENT par la sonde elle-meme : sans ce patch, ce
        # test unitaire construirait un vrai ProcessPoolExecutor.
        patch("ai.bot_evaluation.create_checkpoint_eval_pool", return_value=MagicMock()),
        patch("ai.vec_normalize_utils.save_vec_normalize"),
    ):
        probe._probe(n_episodes=10, label="cheap")

    assert evaluate.call_args.kwargs["n_workers_override"] == 4


def _mkstemp_spy(created: List[str]):
    """Espionne `tempfile.mkstemp` sans le neutraliser : le fichier reste réel, donc le
    `finally` de `_probe` a quelque chose à effacer et le test peut vérifier qu'il l'a fait."""
    real_mkstemp = tempfile.mkstemp

    def _spy(*args, **kwargs):
        fd, path = real_mkstemp(*args, **kwargs)
        created.append(path)
        return fd, path

    return _spy


def _assert_probe_closed_its_pool(probe, pool, created: List[str]) -> None:
    """Invariants communs aux deux sondes quand `evaluate_against_checkpoints` lève."""
    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert probe._eval_pool is None, "la référence au pool fermé doit être lâchée"
    assert len(created) == 1, "la sonde crée exactement un .zip temporaire"
    assert not os.path.exists(created[0]), (
        "le .zip temporaire doit être effacé même quand l'évaluation lève"
    )


def test_exploiter_probe_closes_its_pool_when_the_evaluation_raises(tmp_path):
    """Une évaluation qui lève ferme le pool avant de remonter, et efface le modèle temporaire.

    La fermeture de fin de boucle couvrirait ce chemin, mais trop tard — l'exception traverse
    d'abord `close_all_training_envs` et ses 30 s par VecEnv. Le `except` de `_probe` porte le
    motif complet ; ce test verrouille son effet.
    """
    archive = tmp_path / "target.zip"
    archive.touch()

    probe = exploiter_probe_callback(archive)
    pool = MagicMock()
    probe._eval_pool = pool
    created: List[str] = []

    with (
        patch(
            "ai.bot_evaluation.evaluate_against_checkpoints",
            side_effect=RuntimeError("épisodes non joués"),
        ),
        patch("ai.vec_normalize_utils.save_vec_normalize"),
        patch("tempfile.mkstemp", side_effect=_mkstemp_spy(created)),
    ):
        with pytest.raises(RuntimeError, match="épisodes non joués"):
            probe._probe(n_episodes=10, label="cheap")

    _assert_probe_closed_its_pool(probe, pool, created)


def test_pool_early_stopping_closes_its_pool_when_the_evaluation_raises(tmp_path):
    """Jumeau du test ci-dessus : `PoolEarlyStoppingCallback._probe` porte le même contrat.

    Ce callback est construit par `setup_callbacks` dès qu'une étape de curriculum non-exploiteur
    déclare `early_stop` avec un champion, et n'avait aucun test.
    """
    archive = tmp_path / "champion.zip"
    archive.touch()

    probe = pool_early_stopping_callback(archive)
    pool = MagicMock()
    probe._eval_pool = pool
    created: List[str] = []

    with (
        patch(
            "ai.bot_evaluation.evaluate_against_checkpoints",
            side_effect=RuntimeError("épisodes non joués"),
        ),
        patch("ai.vec_normalize_utils.save_vec_normalize"),
        patch("tempfile.mkstemp", side_effect=_mkstemp_spy(created)),
    ):
        with pytest.raises(RuntimeError, match="épisodes non joués"):
            probe._probe()

    _assert_probe_closed_its_pool(probe, pool, created)


# ── Helpers ─────────────────────────────────────────────────────────────────────────────────


def _fake_config(n_workers: int = 1, use_subprocess: bool = False):
    training_cfg = {
        "agent_seat_mode": "p1",
        "vec_normalize": {"enabled": False},
        "vec_normalize_eval": {"enabled": False},
        "callback_params": {
            "bot_eval_use_subprocess": use_subprocess,
            "bot_eval_task_timeout_seconds": 600,
            "bot_eval_n_workers": n_workers,
            "bot_eval_worker_device": "cpu",
        },
    }
    fake_config = MagicMock()
    fake_config.load_agent_training_config.return_value = training_cfg
    return fake_config


def _checkpoint_task(**overrides):
    """Tache checkpoint minimale, telle que la construit `evaluate_against_checkpoints`."""
    task = {
        "bot_name": "P0",
        "bot_type": "P0",
        "randomness_config": {},
        "scenario_file": "s.json",
        "scenario_name": "s",
        "n_episodes": 2,
        "ep_offset": 0,
        "base_seed": 42,
        "scenario_index": 0,
        "deterministic": True,
        "config_params": {"vec_normalize_enabled": False, "vec_eval_enabled": False},
        "max_steps_per_episode": 100,
        "checkpoint_zip": "/tmp/ckpt.zip",
        "checkpoint_label": "P0",
        "checkpoint_device": "cpu",
        "checkpoint_scenario_episodes": 2,
        # Jeton de version du modèle P1 (4.2) : champs obligatoires depuis la refonte lazy-load.
        "model_path": "/tmp/model.zip",
        "model_device": "cpu",
        "model_mtime": 1.0,
        "torch_compile_cpu": False,
    }
    task.update(overrides)
    return task


def _canned_result(task):
    return {
        "wins": int(task["n_episodes"]), "losses": 0, "draws": 0,
        "truncations": [], "failed_episodes": 0,
        "bot_name": task["bot_name"], "scenario_name": task["scenario_name"],
        "faction_stats": {}, "seat_stats": {},
        "roster_stats": {"agent": {}, "opponent": {}}, "behavior_stats": {},
    }


def _build_tasks(tmp_path, n_episodes, n_scenarios, n_workers, use_subprocess=True):
    """Fait tourner le constructeur de taches et rend les taches produites.

    Le pool est court-circuite : c'est le DECOUPAGE qu'on observe, pas l'execution. En laissant
    `use_subprocess=True` avec `_eval_worker_task` patche, le chemin parallele est neutralise par
    `n_workers > 1` seul — d'ou le passage en serie force ici via un `ProcessPoolExecutor` jamais
    atteint : `_build_tasks` patche l'executeur pour rester en process.
    """
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    scenarios = []
    for i in range(n_scenarios):
        p = tmp_path / f"scenario_{i}.json"
        p.touch()
        scenarios.append(str(p))

    seen: list = []

    def _record(task, progress_callback=None):
        seen.append(task)
        return _canned_result(task)

    def _serial_collect(pool, tasks, task_timeout_seconds, max_in_flight, on_result=None):
        return [_record(task) for task in tasks]

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_config(n_workers=n_workers, use_subprocess=use_subprocess)),
        patch("config_loader.get_max_turns", return_value=10),
        patch("ai.training_utils.get_scenario_list_for_phase", return_value=scenarios),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation._eval_worker_task", side_effect=_record),
        patch("ai.bot_evaluation.ProcessPoolExecutor", MagicMock()),
        patch("ai.bot_evaluation._collect_parallel_results_with_timeouts",
              side_effect=_serial_collect),
    ):
        evaluate_against_checkpoints(
            model_path=str(archive),
            checkpoint_archives=[(str(archive), "P0")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=n_episodes,
            controlled_agent="ArmageddonAgent_x1",
        )

    return seen


# ── 4.2 : jeton de version — le worker ne recharge que si le modèle a changé ───────────────


def test_worker_does_not_reload_when_version_unchanged():
    """Deux appels successifs avec le même (model_path, mtime) ne chargent qu'une fois."""
    from ai import bot_evaluation

    bot_evaluation._worker_model = None
    bot_evaluation._worker_model_version_key = None
    bot_evaluation._worker_vec_normalize_enabled = False
    bot_evaluation._worker_vec_eval_enabled = False

    _task = {"model_path": "/tmp/model.zip", "model_device": "cpu", "model_mtime": 1.0}
    with (
        patch("sb3_contrib.MaskablePPO") as mock_ppo_cls,
        patch.object(bot_evaluation, "_build_eval_obs_normalizer_for_worker", return_value=None),
    ):
        mock_ppo_cls.load.return_value = MagicMock()
        bot_evaluation._eval_worker_load_model_if_needed(_task)
        bot_evaluation._eval_worker_load_model_if_needed(_task)

    assert mock_ppo_cls.load.call_count == 1


def test_worker_reloads_when_mtime_changes():
    """Un mtime différent sur le même chemin déclenche un rechargement."""
    from ai import bot_evaluation

    bot_evaluation._worker_model = None
    bot_evaluation._worker_model_version_key = ("/tmp/model.zip", 1.0)
    bot_evaluation._worker_vec_normalize_enabled = False
    bot_evaluation._worker_vec_eval_enabled = False

    with (
        patch("sb3_contrib.MaskablePPO") as mock_ppo_cls,
        patch.object(
            bot_evaluation, "_build_eval_obs_normalizer_for_worker", return_value=None
        ) as mock_normalizer,
    ):
        mock_ppo_cls.load.return_value = MagicMock()
        bot_evaluation._eval_worker_load_model_if_needed(
            {"model_path": "/tmp/model.zip", "model_device": "cpu", "model_mtime": 2.0}
        )

    mock_ppo_cls.load.assert_called_once()
    mock_normalizer.assert_called_once()  # critère 2 : normalizer VecNormalize aussi rechargé
    assert bot_evaluation._worker_model_version_key == ("/tmp/model.zip", 2.0)


def test_task_dict_contains_model_version_token(tmp_path):
    """Chaque tâche construite par evaluate_against_checkpoints porte model_path et model_mtime."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    seen_tasks: list = []

    def _record(task, progress_callback=None):
        seen_tasks.append(task)
        return _canned_result(task)

    with (
        patch("config_loader.get_config_loader", return_value=_fake_config()),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / "scenario_0.json")],
        ),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation._eval_worker_task", side_effect=_record),
    ):
        evaluate_against_checkpoints(
            model_path=str(archive),
            checkpoint_archives=[(str(archive), "P0")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
        )

    assert seen_tasks, "aucune tâche produite"
    for task in seen_tasks:
        assert "model_path" in task
        assert "model_device" in task
        assert "model_mtime" in task
        assert isinstance(task["model_mtime"], float)


def test_external_pool_used_without_creating_new_pool(tmp_path):
    """Quand `pool` est fourni, aucun nouveau ProcessPoolExecutor n'est créé."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    fake_pool = MagicMock()

    def _serial_collect(pool, tasks, task_timeout_seconds, max_in_flight, on_result=None):
        return [_canned_result(t) for t in tasks]

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_config(n_workers=2, use_subprocess=True)),
        patch("config_loader.get_max_turns", return_value=10),
        patch(
            "ai.training_utils.get_scenario_list_for_phase",
            return_value=[str(tmp_path / "scenario_0.json")],
        ),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation._eval_worker_init"),
        patch("ai.bot_evaluation.ProcessPoolExecutor") as mock_ppe,
        patch(
            "ai.bot_evaluation._collect_parallel_results_with_timeouts",
            side_effect=_serial_collect,
        ),
    ):
        evaluate_against_checkpoints(
            model_path=str(archive),
            checkpoint_archives=[(str(archive), "P0")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
            pool=fake_pool,
        )

    mock_ppe.assert_not_called()


# ── Pool interne : shutdown garanti même sur exception ───────────────────────────────────────


def test_internal_pool_shutdown_called_on_success(tmp_path):
    """Le pool interne est fermé avec wait=False, cancel_futures=True sur le chemin nominal."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    mock_pool_instance = MagicMock()
    mock_pool_cls = MagicMock(return_value=mock_pool_instance)

    def _serial_collect(pool, tasks, task_timeout_seconds, max_in_flight, on_result=None):
        return [_canned_result(t) for t in tasks]

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_config(n_workers=2, use_subprocess=True)),
        patch("config_loader.get_max_turns", return_value=10),
        patch("ai.training_utils.get_scenario_list_for_phase",
              return_value=[str(tmp_path / "scenario_0.json")]),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation.ProcessPoolExecutor", mock_pool_cls),
        patch("ai.bot_evaluation._collect_parallel_results_with_timeouts",
              side_effect=_serial_collect),
    ):
        evaluate_against_checkpoints(
            model_path=str(archive),
            checkpoint_archives=[(str(archive), "P0")],
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
        )

    mock_pool_instance.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_internal_pool_shutdown_called_on_exception(tmp_path):
    """Le pool interne est fermé via finally même quand la collecte lève (KeyboardInterrupt)."""
    from ai.bot_evaluation import evaluate_against_checkpoints

    archive = tmp_path / "ckpt.zip"
    archive.touch()
    (tmp_path / "scenario_0.json").touch()

    mock_pool_instance = MagicMock()
    mock_pool_cls = MagicMock(return_value=mock_pool_instance)

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_config(n_workers=2, use_subprocess=True)),
        patch("config_loader.get_max_turns", return_value=10),
        patch("ai.training_utils.get_scenario_list_for_phase",
              return_value=[str(tmp_path / "scenario_0.json")]),
        patch("sb3_contrib.MaskablePPO.load", return_value=MagicMock()),
        patch("ai.bot_evaluation.ProcessPoolExecutor", mock_pool_cls),
        patch("ai.bot_evaluation._collect_parallel_results_with_timeouts",
              side_effect=KeyboardInterrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            evaluate_against_checkpoints(
                model_path=str(archive),
                checkpoint_archives=[(str(archive), "P0")],
                training_config_name="x1_long",
                rewards_config_name="ArmageddonAgent_x1",
                n_episodes=2,
                controlled_agent="ArmageddonAgent_x1",
            )

    mock_pool_instance.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


# ── evaluate_against_bots : shutdown garanti même sur exception ──────────────────────────────


def _fake_bot_eval_config(n_workers: int = 2, use_subprocess: bool = True):
    training_cfg = {
        "agent_seat_mode": "p1",
        "vec_normalize": {"enabled": False},
        "vec_normalize_eval": {"enabled": False, "training": False, "norm_reward": False},
        "callback_params": {
            "bot_eval_use_subprocess": use_subprocess,
            "bot_eval_task_timeout_seconds": 600,
            "bot_eval_n_workers": n_workers,
            "bot_eval_worker_device": "cpu",
        },
    }
    global_cfg = {"progress_bar": {"bot_eval_width": 20}}
    fake_config = MagicMock()
    fake_config.load_agent_training_config.return_value = training_cfg
    fake_config.load_config.return_value = global_cfg
    return fake_config


def test_bot_eval_internal_pool_shutdown_called_on_success(tmp_path):
    """Le pool interne de evaluate_against_bots est fermé avec wait=False, cancel_futures=True."""
    from ai.bot_evaluation import evaluate_against_bots

    archive = tmp_path / "model.zip"
    archive.touch()
    scenario = tmp_path / "scenario_0.json"
    scenario.touch()

    mock_pool_instance = MagicMock()
    mock_pool_cls = MagicMock(return_value=mock_pool_instance)

    def _serial_collect(pool, tasks, task_timeout_seconds, max_in_flight, on_result=None):
        return [_canned_result(t) for t in tasks]

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_bot_eval_config(n_workers=2, use_subprocess=True)),
        patch("config_loader.get_max_turns", return_value=10),
        patch("ai.training_utils.get_scenario_list_for_phase",
              return_value=[str(scenario)]),
        patch("ai.bot_evaluation._load_bot_eval_params",
              return_value={"weights": {"random": 1.0}, "randomness": {"random": 0.0}}),
        patch("ai.bot_evaluation._filter_scenarios_from_config", side_effect=lambda cfg, s, k: s),
        patch("os.path.getmtime", return_value=1.0),
        patch("ai.bot_evaluation.ProcessPoolExecutor", mock_pool_cls),
        patch("ai.bot_evaluation._collect_parallel_results_with_timeouts",
              side_effect=_serial_collect),
    ):
        evaluate_against_bots(
            model=MagicMock(),
            training_config_name="x1_long",
            rewards_config_name="ArmageddonAgent_x1",
            n_episodes=2,
            controlled_agent="ArmageddonAgent_x1",
            model_path=str(archive),
            show_summary=False,
        )

    mock_pool_instance.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_bot_eval_internal_pool_shutdown_called_on_exception(tmp_path):
    """Le pool interne de evaluate_against_bots est fermé via finally même sur KeyboardInterrupt."""
    from ai.bot_evaluation import evaluate_against_bots

    archive = tmp_path / "model.zip"
    archive.touch()
    scenario = tmp_path / "scenario_0.json"
    scenario.touch()

    mock_pool_instance = MagicMock()
    mock_pool_cls = MagicMock(return_value=mock_pool_instance)

    with (
        patch("config_loader.get_config_loader",
              return_value=_fake_bot_eval_config(n_workers=2, use_subprocess=True)),
        patch("config_loader.get_max_turns", return_value=10),
        patch("ai.training_utils.get_scenario_list_for_phase",
              return_value=[str(scenario)]),
        patch("ai.bot_evaluation._load_bot_eval_params",
              return_value={"weights": {"random": 1.0}, "randomness": {"random": 0.0}}),
        patch("ai.bot_evaluation._filter_scenarios_from_config", side_effect=lambda cfg, s, k: s),
        patch("os.path.getmtime", return_value=1.0),
        patch("ai.bot_evaluation.ProcessPoolExecutor", mock_pool_cls),
        patch("ai.bot_evaluation._collect_parallel_results_with_timeouts",
              side_effect=KeyboardInterrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            evaluate_against_bots(
                model=MagicMock(),
                training_config_name="x1_long",
                rewards_config_name="ArmageddonAgent_x1",
                n_episodes=2,
                controlled_agent="ArmageddonAgent_x1",
                model_path=str(archive),
                show_summary=False,
            )

    mock_pool_instance.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
