#!/usr/bin/env python3
"""Cycle de vie du pool de workers des sondes (`_EvalPoolOwnerMixin`).

Le pool vivait dans `_on_training_start`/`_on_training_end`. SB3 appaire ces deux hooks autour
de CHAQUE `learn()` (`MaskablePPO.learn`, sb3-contrib) et la boucle budgétée
en épisodes de `train_with_scenario_rotation` en enchaîne un par tranche de quatre updates : le
pool était donc recréé et refermé une fois par tranche, et chaque sonde repayait le démarrage de
ses workers (spawn + import + chargement de l'archive adverse).

Ces tests verrouillent le contrat qui remplace ce couple :
- création PARESSEUSE, à la première sonde et une seule fois ;
- survie aux frontières de `learn()` ;
- fermeture par `shutdown_probe_eval_pools`, appelée par le `finally` de la boucle ;
- fermeture RÉELLE (pas un simple détachement) sur l'exception qui remonte de `_probe`, le seul
  chemin qui court-circuite la fermeture de fin de boucle.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from ai.training_callbacks import shutdown_probe_eval_pools  # noqa: E402
from shared.data_validation import ConfigurationError  # noqa: E402
from tests.unit.ai._fabriques import (  # noqa: E402
    PROBE_REWARDS_CONFIG as REWARDS_CONFIG,
    PROBE_TRAINING_CONFIG as TRAINING_CONFIG,
    exploiter_probe_callback as _make_exploiter_probe,
    pool_early_stopping_callback as _make_pool_early_stop,
)


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "champion.zip"
    path.touch()
    return path


def _patched_probe_environment(create_pool, results):
    """Neutralise tout ce que `_probe` fait hors du pool : sauvegarde, normalisation, nettoyage."""
    return (
        patch("ai.bot_evaluation.create_checkpoint_eval_pool", create_pool),
        patch("ai.bot_evaluation.evaluate_against_checkpoints", return_value=results),
        patch("ai.vec_normalize_utils.save_vec_normalize"),
        patch("ai.training_callbacks.remove_model_with_companions"),
    )


# ── Création paresseuse ─────────────────────────────────────────────────────────────────────


def test_no_pool_before_the_first_probe(archive):
    """Construire le callback ne crée aucun pool : le coût n'est payé qu'à la première sonde."""
    assert _make_exploiter_probe(archive)._eval_pool is None
    assert _make_pool_early_stop(archive)._eval_pool is None


def test_sb3_training_start_does_not_create_a_pool(archive):
    """`on_training_start` — appelé à CHAQUE `learn()` — ne doit plus rien créer.

    C'est le hook où le pool naissait, une fois par tranche de quatre updates.
    """
    probe = _make_exploiter_probe(archive)
    early_stop = _make_pool_early_stop(archive)

    with patch("ai.bot_evaluation.create_checkpoint_eval_pool") as create_pool:
        probe.on_training_start({}, {})
        early_stop.on_training_start({}, {})

    create_pool.assert_not_called()
    assert probe._eval_pool is None
    assert early_stop._eval_pool is None


@pytest.mark.parametrize("kind", ["exploiter", "early_stop"])
def test_pool_created_once_and_reused_across_probes(archive, kind):
    """Trois sondes, UN seul pool, passé tel quel à chaque évaluation."""
    pool = MagicMock()
    create_pool = MagicMock(return_value=pool)
    results = {"target": 0.5, "champion": 0.5}
    if kind == "exploiter":
        probe = _make_exploiter_probe(archive)
        run_probe = lambda: probe._probe(n_episodes=10, label="bon-marche")  # noqa: E731
    else:
        early_stop = _make_pool_early_stop(archive)
        run_probe = lambda: early_stop._probe()  # noqa: E731
    p_create, p_eval, p_vecnorm, p_remove = _patched_probe_environment(create_pool, results)

    with p_create, p_eval as evaluate, p_vecnorm, p_remove:
        for _ in range(3):
            run_probe()

    assert create_pool.call_count == 1, (
        "le pool doit être créé à la PREMIÈRE sonde seulement — une création par sonde fait "
        "repayer spawn, imports et chargement de l'archive adverse à chaque fois"
    )
    assert evaluate.call_count == 3
    assert [call.kwargs["pool"] for call in evaluate.call_args_list] == [pool, pool, pool]


def test_pool_is_created_with_the_config_of_the_agent(archive):
    """Les paramètres du pool sont ceux lus dans le profil d'entraînement de l'agent."""
    create_pool = MagicMock(return_value=MagicMock())
    probe = _make_exploiter_probe(archive)
    p_create, p_eval, p_vecnorm, p_remove = _patched_probe_environment(
        create_pool, {"target": 0.5}
    )

    with p_create, p_eval, p_vecnorm, p_remove:
        probe._probe(n_episodes=10, label="bon-marche")

    kwargs = create_pool.call_args.kwargs
    assert kwargs["n_workers"] == 4
    assert kwargs["training_config_name"] == TRAINING_CONFIG
    assert kwargs["rewards_config_name"] == REWARDS_CONFIG
    assert kwargs["controlled_agent"] == REWARDS_CONFIG
    assert kwargs["base_agent_key"] == REWARDS_CONFIG
    assert isinstance(kwargs["vec_normalize_enabled"], bool)
    assert isinstance(kwargs["vec_eval_enabled"], bool)


def test_single_worker_creates_no_pool(archive):
    """Un seul worker ne justifie pas un pool : l'évaluation reçoit `pool=None`."""
    create_pool = MagicMock()
    probe = _make_exploiter_probe(archive, n_workers=1)
    p_create, p_eval, p_vecnorm, p_remove = _patched_probe_environment(
        create_pool, {"target": 0.5}
    )

    with p_create, p_eval as evaluate, p_vecnorm, p_remove:
        probe._probe(n_episodes=10, label="bon-marche")

    create_pool.assert_not_called()
    assert evaluate.call_args.kwargs["pool"] is None


# ── Compte de workers : lu dans le profil, jamais choisi par le code ─────────────────────────


def _profile(**callback_params):
    """Patch du chargeur de config sur un profil réduit à ce que `_ensure_eval_pool` lit.

    SYNTHÉTIQUE, et non un profil réel dont la clé serait absente (`x1_debug`, `x5_debug`) :
    le test doit CONSTRUIRE l'absence, sinon le jour où quelqu'un ajoute la clé à ce profil il
    reste vert en n'exerçant plus rien.
    """
    loader = MagicMock()
    loader.load_agent_training_config.return_value = {
        "vec_normalize": {"enabled": True},
        "vec_normalize_eval": {"enabled": True},
        "callback_params": dict(callback_params),
    }
    return patch("ai.training_callbacks.get_config_loader", return_value=loader)


@pytest.mark.parametrize("make", [_make_exploiter_probe, _make_pool_early_stop])
def test_a_profile_without_the_worker_count_raises(archive, make):
    """Un profil qui ne déclare pas `bot_eval_n_workers_intermediate` arrête la sonde.

    Le code y retombait sur 4 workers de son cru — un chiffre que la config ne dit nulle part,
    et qui n'a aucune raison de valoir celui d'un `max_in_flight` dérivé, lui, de
    `bot_eval_n_workers`. Les autres lectures de la même fonction (`vec_normalize`,
    `vec_normalize_eval`) sont strictes ; celle-ci doit l'être aussi.
    """
    callback = make(archive, n_workers=None)
    create_pool = MagicMock()

    with _profile(), patch("ai.bot_evaluation.create_checkpoint_eval_pool", create_pool):
        with pytest.raises(ConfigurationError, match="bot_eval_n_workers_intermediate"):
            callback._ensure_eval_pool()

    create_pool.assert_not_called()
    assert callback._eval_pool is None


@pytest.mark.parametrize("make", [_make_exploiter_probe, _make_pool_early_stop])
def test_the_worker_count_declared_by_the_profile_sizes_the_pool(archive, make):
    """Déclarée, la valeur du profil est celle que reçoit `create_checkpoint_eval_pool`."""
    callback = make(archive, n_workers=None)
    create_pool = MagicMock(return_value=MagicMock())

    with _profile(bot_eval_n_workers_intermediate=6), patch(
        "ai.bot_evaluation.create_checkpoint_eval_pool", create_pool
    ):
        callback._ensure_eval_pool()

    assert create_pool.call_args.kwargs["n_workers"] == 6


@pytest.mark.parametrize("declared, expected", [(None, 6), (3, 3)])
def test_the_pool_size_is_the_max_in_flight_of_the_evaluation(archive, declared, expected):
    """Le pool et `max_in_flight` sortent du MÊME nombre, que la sonde le porte ou non.

    `evaluate_against_checkpoints` fait de `n_workers_override` son `max_in_flight`, et retombe
    sur `bot_eval_n_workers` — le compte de l'éval FINALE — quand il vaut None. Passer
    `intermediate_n_workers` brut au lieu du compte résolu par `_ensure_eval_pool` faisait donc
    dimensionner le pool sur une clé et `max_in_flight` sur une autre : un `max_in_flight`
    supérieur au nombre de workers laisse des tâches EN FILE alors que leur chronomètre de
    `bot_eval_task_timeout_seconds` court déjà (`_collect_parallel_results_with_timeouts`).
    """
    probe = _make_exploiter_probe(archive, n_workers=declared)
    create_pool = MagicMock(return_value=MagicMock())
    p_create, p_eval, p_vecnorm, p_remove = _patched_probe_environment(
        create_pool, {"target": 0.5}
    )

    with _profile(bot_eval_n_workers_intermediate=6), p_create, p_eval as evaluate, (
        p_vecnorm
    ), p_remove:
        probe._probe(n_episodes=10, label="bon-marche")

    assert create_pool.call_args.kwargs["n_workers"] == expected
    assert evaluate.call_args.kwargs["n_workers_override"] == expected


# ── Survie aux frontières de learn() ────────────────────────────────────────────────────────


def test_pool_survives_the_learn_chunk_boundary(archive):
    """Le pool traverse `on_training_end`/`on_training_start` : une tranche ne le détruit plus.

    Reproduit ce que fait la boucle budgétée en épisodes : sonde dans une tranche, frontière de
    `learn()`, sonde dans la suivante. Avant, la deuxième sonde repartait d'un pool neuf.
    """
    pool = MagicMock()
    create_pool = MagicMock(return_value=pool)
    probe = _make_exploiter_probe(archive)
    p_create, p_eval, p_vecnorm, p_remove = _patched_probe_environment(
        create_pool, {"target": 0.5}
    )

    with p_create, p_eval, p_vecnorm, p_remove:
        probe.on_training_start({}, {})
        probe._probe(n_episodes=10, label="tranche-1")
        probe.on_training_end()

        assert probe._eval_pool is pool, (
            "la fin d'une tranche de learn() ne doit plus fermer le pool — SB3 appelle "
            "on_training_end une fois par tranche de quatre updates"
        )
        pool.shutdown.assert_not_called()

        probe.on_training_start({}, {})
        probe._probe(n_episodes=10, label="tranche-2")
        probe.on_training_end()

    assert create_pool.call_count == 1
    pool.shutdown.assert_not_called()


# ── Fermeture ───────────────────────────────────────────────────────────────────────────────


def test_shutdown_probe_eval_pools_closes_every_owner(archive):
    """La fermeture de fin de boucle ferme les deux callbacks et ignore les autres."""
    probe = _make_exploiter_probe(archive)
    early_stop = _make_pool_early_stop(archive)
    probe_pool = MagicMock()
    early_stop_pool = MagicMock()
    probe._eval_pool = probe_pool
    early_stop._eval_pool = early_stop_pool
    foreign = MagicMock()  # un callback quelconque de la liste d'entraînement

    shutdown_probe_eval_pools([probe, foreign, early_stop])

    probe_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    early_stop_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert probe._eval_pool is None
    assert early_stop._eval_pool is None
    foreign._shutdown_eval_pool.assert_not_called()


def test_shutdown_probe_eval_pools_is_idempotent(archive):
    """Rappelée sur un pool déjà fermé, elle ne referme rien et ne lève pas.

    Le `finally` de la boucle peut la voir passer après une exception qui a déjà fermé le pool.
    """
    probe = _make_exploiter_probe(archive)
    pool = MagicMock()
    probe._eval_pool = pool

    shutdown_probe_eval_pools([probe])
    shutdown_probe_eval_pools([probe])

    pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


def test_shutdown_probe_eval_pools_accepts_a_never_probed_callback(archive):
    """Une étape qui n'a jamais sondé n'a pas de pool : la fermeture est un no-op."""
    shutdown_probe_eval_pools([_make_exploiter_probe(archive), _make_pool_early_stop(archive)])


def test_learn_loop_closes_the_pools_in_a_finally():
    """Le SEUL point de fermeture de production est bien câblé, et dans un `finally`.

    Les hooks SB3 ayant été retirés, `shutdown_probe_eval_pools` n'est plus appelé que là. Un test
    de comportement sur `train_with_scenario_rotation` demanderait un run complet (config, env,
    modèle) : le contrat est donc lu dans l'AST. Sans ce verrou, supprimer l'appel laisse toute la
    suite verte pendant que chaque run abandonne 4 workers, orphelins (PPID=1) au SIGTERM suivant.

    Le `finally` est la moitié qui compte : posé après la boucle, il serait sauté par l'exception
    et par le Ctrl-C, précisément les sorties où les workers survivent au parent.
    """
    tree = ast.parse((PROJECT_ROOT / "ai" / "train.py").read_text(encoding="utf-8"))
    # `train_with_scenario_rotation` est précédée de trois `@overload` : l'implémentation est la
    # DERNIÈRE définition du nom, les précédentes n'ont qu'un corps vide.
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "train_with_scenario_rotation"
    ]
    assert definitions, "`train_with_scenario_rotation` introuvable dans ai/train.py"
    rotation = definitions[-1]

    guarded_loops = [
        handler
        for handler in ast.walk(rotation)
        if isinstance(handler, ast.Try)
        and any(isinstance(stmt, ast.While) for stmt in ast.walk(ast.Module(handler.body, [])))
        and any(
            isinstance(call.func, ast.Name) and call.func.id == "shutdown_probe_eval_pools"
            for stmt in handler.finalbody
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
        )
    ]

    assert guarded_loops, (
        "aucun `try/finally` de `train_with_scenario_rotation` n'entoure une boucle `while` en "
        "appelant `shutdown_probe_eval_pools` dans son `finally` — le pool des sondes n'est "
        "fermé sur aucun chemin de sortie"
    )


def test_probe_after_a_broken_pool_creates_a_fresh_one(archive):
    """Après l'exception, la sonde suivante recrée un pool au lieu de retomber sur le cassé.

    Que l'exception FERME le pool est verrouillé par
    `test_exploiter_probe_closes_its_pool_when_the_evaluation_raises` et son jumeau, dans
    `test_checkpoint_eval_parallel.py`. Ce qui est propre à la création paresseuse, et vérifié
    ici, c'est la reprise : sans elle la sonde suivante partirait sans pool du tout.
    """
    pools = [MagicMock(), MagicMock()]
    create_pool = MagicMock(side_effect=pools)
    probe = _make_exploiter_probe(archive)

    with (
        patch("ai.bot_evaluation.create_checkpoint_eval_pool", create_pool),
        patch("ai.vec_normalize_utils.save_vec_normalize"),
        patch("ai.training_callbacks.remove_model_with_companions"),
    ):
        with patch(
            "ai.bot_evaluation.evaluate_against_checkpoints",
            side_effect=RuntimeError("BrokenProcessPool"),
        ):
            with pytest.raises(RuntimeError):
                probe._probe(n_episodes=10, label="cassee")
        with patch(
            "ai.bot_evaluation.evaluate_against_checkpoints",
            return_value={"target": 0.5},
        ) as evaluate:
            probe._probe(n_episodes=10, label="suivante")

    assert create_pool.call_count == 2
    assert evaluate.call_args.kwargs["pool"] is pools[1]
    pools[0].shutdown.assert_called_once_with(wait=False, cancel_futures=True)
