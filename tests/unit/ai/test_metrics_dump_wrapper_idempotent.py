"""Verrou — `MetricsCollectionCallback._on_training_start` n'enveloppe `logger.dump` QU'UNE FOIS.

SB3 appelle `_on_training_start` a chaque `learn()`, et `train_with_scenario_rotation` enchaine
un `learn()` par tranche de quatre updates (ai/train.py, boucle budgetee en episodes). Sur un run
NEUF, SB3 reconstruit son logger a chaque `learn()` — la garde `_custom_logger` de
`base_class._setup_learn` — donc chaque appel enveloppait un `dump` neuf et la couche restait
unique. Sur une REPRISE (`--resume-from`, donc toute etape de curriculum a `init: "from:..."`),
`ai/train.py` pose le logger lui-meme via `model.set_logger` : `_custom_logger` passe a True, SB3
ne reconstruit plus rien, et les enveloppes s'EMPILAIENT.

Consequence mesuree sur le run du 2026-09-03 (etape P1 reprise depuis P00) : 41 756 points ecrits
sur `training_critical/clip_fraction` pour 575 updates PPO reels, contre 1 063 points pour 1 063
updates sur un run neuf comparable. La fenetre de vingt valeurs de
`W40KMetricsTracker._calculate_smoothed_metric` ne couvrait alors plus vingt updates mais vingt
copies du dernier : les quatre courbes de sante PPO du dashboard `00_critical` (clip_fraction,
approx_kl, explained_variance, entropy_loss) n'etaient plus lissees du tout, et paraissaient
quatre a quatorze fois plus bruitees que celles d'un run neuf. Le meme empilement recalculait la
norme du gradient une fois par couche.

Ce fichier verifie l'invariant qui manquait : UNE capture par appel a `dump`, quel que soit le
nombre d'appels a `_on_training_start`.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


class _FakeLogger:
    """Logger SB3 double : `dump` compte ses appels, `name_to_value` porte un update PPO."""

    def __init__(self) -> None:
        self.original_dump_calls = 0
        self.name_to_value: Dict[str, Any] = {
            "train/clip_fraction": 0.074,
            "train/approx_kl": 0.0087,
            "train/explained_variance": 0.884,
            "train/entropy_loss": -1.34,
        }

    def dump(self, step: int = 0) -> None:
        self.original_dump_calls += 1


class _FakeModel:
    """Modele double SANS `policy` ni `ent_coef` : les deux branches optionnelles de la capture
    sont hors sujet ici, et les fournir imposerait un vrai reseau pour rien."""

    num_timesteps = 4_806_336

    def __init__(self) -> None:
        self.logger = _FakeLogger()


class _CountingTracker:
    """Tracker double : compte les captures et retient les statistiques recues."""

    writer = None

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.step_count = 0

    def log_training_metrics(self, model_stats: Dict[str, Any]) -> None:
        self.calls.append(dict(model_stats))


def _callback(model: _FakeModel, tracker: _CountingTracker) -> Any:
    from ai.training_callbacks import MetricsCollectionCallback

    return MetricsCollectionCallback(tracker, model)


def test_repeated_training_starts_capture_each_dump_once() -> None:
    """Trois `_on_training_start` puis un `dump` : UNE capture, pas trois.

    C'est la reprise en production : un `_on_training_start` par tranche de `learn()`, sur un
    logger qui survit d'une tranche a l'autre.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    for _ in range(3):
        callback._on_training_start()

    model.logger.dump(step=model.num_timesteps)

    assert len(tracker.calls) == 1, (
        f"{len(tracker.calls)} captures pour un seul dump : les enveloppes se sont empilees."
    )
    assert model.logger.original_dump_calls == 1, (
        f"{model.logger.original_dump_calls} appels au dump d'origine pour un seul dump demande."
    )
    assert tracker.calls[0]["train/clip_fraction"] == pytest.approx(0.074)
    assert tracker.step_count == model.num_timesteps


def test_capture_count_follows_dump_count_not_learn_count() -> None:
    """Le nombre de captures suit les `dump`, jamais les `_on_training_start`.

    Verifie la forme utile de l'invariant : c'est le compte d'updates PPO qui doit arriver au
    tracker, pas un multiple du nombre de tranches d'entrainement. Sans quoi la fenetre de
    lissage de vingt valeurs cesse de couvrir vingt updates.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    for _ in range(10):
        callback._on_training_start()
        for _ in range(4):  # quatre updates par tranche, comme `chunk_timesteps`
            model.logger.dump(step=model.num_timesteps)

    assert len(tracker.calls) == 40, (
        f"{len(tracker.calls)} captures pour 40 updates : le facteur de duplication vaut "
        f"{len(tracker.calls) / 40:.1f}."
    )


def test_a_fresh_logger_is_wrapped_again() -> None:
    """La garde d'idempotence ne doit pas rendre le callback aveugle a un logger NEUF.

    C'est le cas du run neuf, ou SB3 reconstruit son logger a chaque `learn()` : sans nouvelle
    enveloppe, plus aucune metrique PPO n'arriverait au tracker.
    """
    model = _FakeModel()
    tracker = _CountingTracker()
    callback = _callback(model, tracker)

    callback._on_training_start()
    model.logger = _FakeLogger()  # SB3 a reconstruit le logger
    callback._on_training_start()

    model.logger.dump(step=model.num_timesteps)

    assert len(tracker.calls) == 1
    assert model.logger.original_dump_calls == 1


def test_a_second_collector_on_the_same_logger_is_refused() -> None:
    """Deux collecteurs vivants sur un meme logger : etat invalide, erreur explicite.

    Enveloppe silencieusement, le second empilerait sa capture sur celle du premier et les deux
    trackers recevraient chaque update — le defaut que ce fichier verrouille, sous une autre
    forme. La production n'instancie qu'un `MetricsCollectionCallback` par modele
    (ai/train.py, chemin rotation et chemin standard).
    """
    model = _FakeModel()
    first = _callback(model, _CountingTracker())
    second = _callback(model, _CountingTracker())

    first._on_training_start()
    with pytest.raises(RuntimeError, match="AUTRE collecteur"):
        second._on_training_start()


# ── JUMEAUX : les deux callbacks de sonde, qui creent un pool de workers ────────────────────
#
# Meme cause, meme forme : `_on_training_start` est rappele par SB3 a chaque `learn()`, donc une
# fois par tranche de quatre updates. Sans garde, chaque tranche remplacait `_eval_pool` par un
# executeur NEUF sans fermer le precedent — le pool cessait d'etre persistant alors que c'est sa
# raison d'etre, et `_on_training_end` n'en fermait qu'un seul.


class _FakePool:
    """Executeur double : retient s'il a ete ferme, n'ouvre aucun processus."""

    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls += 1


def _count_pool_creations(monkeypatch) -> List[_FakePool]:
    """Remplace la fabrique de pool par un double qui compte ses appels.

    Les deux callbacks importent `create_checkpoint_eval_pool` DANS la methode : le patch doit
    donc porter sur le module d'origine, pas sur un nom deja lie.
    """
    import ai.bot_evaluation

    created: List[_FakePool] = []

    def _fake_factory(**_kwargs: Any) -> _FakePool:
        pool = _FakePool()
        created.append(pool)
        return pool

    monkeypatch.setattr(ai.bot_evaluation, "create_checkpoint_eval_pool", _fake_factory)
    return created


def _pool_early_stop_callback() -> Any:
    from ai.training_callbacks import PoolEarlyStoppingCallback

    return PoolEarlyStoppingCallback(
        pool_archives=[("/inexistant/model_P0.zip", "P0")],
        threshold=0.60,
        min_timesteps=50000,
        consecutive_evals=2,
        eval_freq_episodes=10000,
        n_eval_episodes=300,
        training_config_name="x1_long",
        rewards_config_name="ArmageddonAgent_x1",
        metrics_tracker=None,
        intermediate_n_workers=4,
    )


def _exploiter_probe_callback() -> Any:
    from ai.training_callbacks import ExploiterProbeCallback

    return ExploiterProbeCallback(
        target_archive_path="/inexistant/model_P3.zip",
        training_config_name="x1_long",
        rewards_config_name="ArmageddonAgent_x1",
        metrics_tracker=None,
        probe_every_episodes=2000,
        probe_cheap_n=100,
        probe_confirm_n=500,
        win_rate_target=0.70,
        budget_cap=200000,
        intermediate_n_workers=4,
    )


@pytest.mark.parametrize(
    "build_callback",
    [_pool_early_stop_callback, _exploiter_probe_callback],
    ids=["pool_early_stop", "exploiter_probe"],
)
def test_probe_pool_is_created_once_per_stage(build_callback, monkeypatch) -> None:
    """Dix tranches d'entrainement, UN seul pool de workers."""
    created = _count_pool_creations(monkeypatch)
    callback = build_callback()

    for _ in range(10):
        callback._on_training_start()

    assert len(created) == 1, (
        f"{len(created)} pools crees pour une etape : le pool n'est plus persistant et "
        f"{len(created) - 1} executeur(s) ont ete abandonnes sans shutdown."
    )
    assert created[0].shutdown_calls == 0, "le pool vivant ne doit pas etre ferme en cours d'etape"


@pytest.mark.parametrize(
    "build_callback",
    [_pool_early_stop_callback, _exploiter_probe_callback],
    ids=["pool_early_stop", "exploiter_probe"],
)
def test_probe_pool_is_rebuilt_after_an_incident(build_callback, monkeypatch) -> None:
    """La garde ne doit pas empecher la reconstruction apres un incident d'evaluation.

    `_probe` remet `_eval_pool` a None quand `evaluate_against_checkpoints` leve : c'est le seul
    etat ou un pool neuf est attendu, et une garde trop large laisserait l'etape sans pool
    jusqu'a la fin.
    """
    created = _count_pool_creations(monkeypatch)
    callback = build_callback()

    callback._on_training_start()
    callback._eval_pool = None  # ce que `_probe` fait quand une evaluation leve
    callback._on_training_start()

    assert len(created) == 2
