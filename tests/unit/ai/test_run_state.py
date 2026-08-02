"""Verrou de l'état de run (`ai/run_state.py`) — les rampes reprennent, elles ne redémarrent pas.

Trois rampes se rapportent à un compteur d'épisodes : `learning_rate`, `ent_coef`, et le mode de
déploiement du moteur. Toutes repartaient de leur valeur de DÉPART à chaque `--append` : un modèle
déjà convergé revenait à son learning rate initial (catastrophic forgetting), et la part
d'épisodes joués en déploiement actif n'atteignait jamais `active_ratio_end` (V11 §0.58).
"""

from __future__ import annotations

import json
import os

import pytest

from shared.data_validation import ConfigurationError
from ai.run_state import (
    get_run_state_path,
    load_run_state,
    remove_run_state,
    save_run_state,
)


def test_run_state_path_is_derived_from_the_model_name(tmp_path) -> None:
    """Un fichier PAR modèle : supprimer les artefacts d'un modèle n'en détruit pas un autre."""
    a = get_run_state_path(str(tmp_path / "model_agent.zip"))
    b = get_run_state_path(str(tmp_path / "ppo_checkpoint_10_steps.zip"))
    assert a != b
    assert os.path.dirname(a) == str(tmp_path)


def test_save_then_load_roundtrip(tmp_path) -> None:
    model = str(tmp_path / "model_agent.zip")
    save_run_state(model, 78477)
    assert load_run_state(model) == 78477


def test_missing_state_raises_instead_of_assuming_zero(tmp_path) -> None:
    """LE point du mécanisme : supposer 0 relancerait les trois rampes sans rien signaler."""
    model = str(tmp_path / "model_agent.zip")
    with pytest.raises(FileNotFoundError, match="--new"):
        load_run_state(model)


def test_truncated_state_raises(tmp_path) -> None:
    """Un fichier corrompu ferait reprendre une rampe à une valeur arbitraire."""
    model = str(tmp_path / "model_agent.zip")
    with open(get_run_state_path(model), "w", encoding="utf-8") as handle:
        json.dump({"autre_cle": 12}, handle)
    with pytest.raises(ValueError, match="episodes_trained"):
        load_run_state(model)


@pytest.mark.parametrize("bad", [-1, 12.5, True, None, "10"])
def test_negative_or_non_integer_counts_are_refused(tmp_path, bad) -> None:
    """`True` inclus : `bool` hérite d'`int`, il passerait pour 1 sans exclusion explicite."""
    model = str(tmp_path / "model_agent.zip")
    with pytest.raises(ConfigurationError):
        save_run_state(model, bad)


def test_save_is_atomic_and_leaves_no_temporary(tmp_path) -> None:
    """Écriture tmp + `os.replace` : un fichier tronqué serait pire que pas de fichier."""
    model = str(tmp_path / "model_agent.zip")
    save_run_state(model, 10)
    save_run_state(model, 20)
    assert load_run_state(model) == 20
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_remove_is_idempotent(tmp_path) -> None:
    model = str(tmp_path / "model_agent.zip")
    save_run_state(model, 5)
    remove_run_state(model)
    remove_run_state(model)
    assert not os.path.exists(get_run_state_path(model))


def test_engine_ramp_resumes_from_the_start_index() -> None:
    """Bout en bout côté moteur : `training_episode_start_index` fait reprendre la rampe.

    Sans lui, un env reconstruit repart à l'index 0, donc à `active_ratio_start` — quel que soit
    ce que le modèle a déjà joué.
    """
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    scenario = os.path.join(
        project_root, "config/board/44x60x5/scenario/scenario_fixed_brawl_sm_orks.json"
    )

    def _p_active(start_index: int) -> float:
        env = W40KEngine(
            rewards_config="ArmageddonAgent",
            training_config_name="x5_new",
            controlled_agent="ArmageddonAgent",
            scenario_file=scenario,
            unit_registry=UnitRegistry(),
            quiet=True,
            gym_training_mode=True,
            training_n_envs=1,
            training_episode_start_index=start_index,
        )
        assert env.training_config is not None
        env.training_config = dict(env.training_config)
        env.training_config["total_episodes"] = 101
        env.training_config["n_envs"] = 1
        env.training_config["deployment_mode_schedule"] = {
            "enabled": True, "training_only": False, "active_ratio_start": 0.0,
            "active_ratio_end": 1.0, "schedule": "linear", "freeze_after_progress": 1.0,
        }
        env._configure_deployment_mode_for_episode()
        return float(env.game_state["deployment_mode_schedule_p_active"])

    assert _p_active(0) == pytest.approx(0.0), "un run neuf démarre bien au début de la rampe"
    assert _p_active(50) == pytest.approx(0.5), "une reprise à mi-parcours reprend à mi-rampe"
    assert _p_active(100) == pytest.approx(1.0)


def test_train_model_seeds_its_tracker_with_the_resume_offset(monkeypatch) -> None:
    """Le compteur du tracker est CUMULATIF, et c'est lui qui est persisté à chaque sauvegarde.

    Parti de zéro sur un `--append`, il écraserait le compte du modèle (200 000) par celui du
    seul run courant (10 000) : la reprise suivante relancerait les rampes presque au début —
    exactement ce que ce mécanisme existe pour empêcher.
    """
    import ai.metrics_tracker as metrics_tracker_module
    import ai.train as train

    captured: dict = {}

    class _SpyTracker:
        def __init__(self, agent_name, tensorboard_dir, **kwargs):
            captured.update(kwargs)
            raise _Stop()

    class _Stop(Exception):
        pass

    class _FakeModel:
        tensorboard_log = "./tensorboard/"

    monkeypatch.setattr(metrics_tracker_module, "W40KMetricsTracker", _SpyTracker)
    monkeypatch.setattr(metrics_tracker_module, "resolve_perf_windows", lambda cfg: (100, 10))

    with pytest.raises(_Stop):
        train.train_model(
            _FakeModel(), {"total_episodes": 10, "perf_window": 100}, [],
            "/tmp/model_TestAgent.zip", "x1", "TestAgent", episode_offset=200000,
        )

    assert captured.get("initial_episode_count") == 200000


def test_append_without_a_model_is_not_a_resume(tmp_path) -> None:
    """`--append` sur un agent sans modèle : les trois chemins créent un modèle NEUF.

    Exiger un état de run ici ferait échouer le premier entraînement d'un agent, avec un message
    qui accuse le mauvais coupable.
    """
    from ai.train import resume_episode_offset

    absent = str(tmp_path / "model_NewAgent.zip")
    assert resume_episode_offset(absent, append_training=True) == 0

    existing = str(tmp_path / "model_OldAgent.zip")
    open(existing, "wb").close()
    save_run_state(existing, 505000)
    assert resume_episode_offset(existing, append_training=True) == 505000
    assert resume_episode_offset(existing, append_training=False) == 0


def test_a_model_without_a_run_state_still_refuses_to_resume(tmp_path) -> None:
    """Le modèle EXISTE mais n'a pas d'état : c'est le cas que le mécanisme doit refuser."""
    from ai.train import resume_episode_offset

    existing = str(tmp_path / "model_OldAgent.zip")
    open(existing, "wb").close()
    with pytest.raises(FileNotFoundError, match="--new"):
        resume_episode_offset(existing, append_training=True)


def test_companion_path_refuses_a_directory(tmp_path) -> None:
    """Sans nom de fichier, tous les modèles du dossier partageraient LE MÊME compagnon."""
    from ai.companion_paths import companion_path

    with pytest.raises(ValueError, match="sans nom de fichier"):
        companion_path(str(tmp_path) + "/", "_run_state.json")


def test_progress_display_counts_the_resumed_episodes_on_both_sides() -> None:
    """Barre de progression : offset des DEUX côtés, sinon 1000 % et une ETA négative."""
    from ai.training_callbacks import EpisodeTerminationCallback

    callback = EpisodeTerminationCallback(max_episodes=1000, expected_timesteps=10_000, total_episodes=1000)
    callback.global_episode_offset = 505000
    callback.episode_count = 500

    count, total = callback.display_progress()
    assert (count, total) == (505500, 506000)
    assert count / total <= 1.0, "barre au-dela de 100 %"
    assert total - count > 0, "reste-a-faire negatif : ETA absurde"



def test_regime_ramps_start_from_this_run_not_from_the_model_lifetime() -> None:
    """Deux natures de rampe, deux origines (décision utilisateur du 2026-08-02).

    Une phase 2 est un profil INDÉPENDANT lancé en `--append` : son `learning_rate.initial` et
    son introduction progressive de self-play doivent s'appliquer. Comptées depuis la vie du
    modèle, ces deux rampes seraient saturées dès le premier épisode — LR collé à `final`,
    warmup de self-play sauté, ratio final d'entrée.
    """
    from test_env_wrappers import _DummyBot, _DummyEngine  # doubles du contrat moteur

    from ai.env_wrappers import BotControlledEnv
    from ai.training_callbacks import LearningRateScheduleCallback

    # Rampe de RÉGIME : elle part de 0, quel que soit le passé du modèle.
    lr = LearningRateScheduleCallback(
        start=0.002, end=0.0002, total_episodes=100_000, decay_fraction=1.0,
    )
    assert lr.episode_count == 0
    assert lr._current_value() == pytest.approx(0.002), "la phase 2 doit démarrer à SON initial"

    # Rampe de self-play : idem, l'index part de zéro pour ce run.
    wrapper = BotControlledEnv(
        _DummyEngine(), bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.0, self_play_ratio_end=0.5,
        self_play_total_episodes=100_000, self_play_warmup_episodes=5_000,
        self_play_n_envs=1, self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_refresh_episodes=1, self_play_snapshot_device="cpu",
    )
    assert wrapper._episode_index == 0
    assert wrapper._compute_self_play_ratio_for_episode() == pytest.approx(0.0), (
        "le warmup doit être devant, pas déjà consommé par un run précédent"
    )


def test_the_start_index_reaches_the_engine_and_not_the_self_play_wrapper() -> None:
    """Câblage : l'index repris va au MOTEUR, pas au wrapper (V11 §0.58).

    Vérifié sur la source de la fabrique et non sur un environnement construit : monter 48
    workers dans un test coûterait des minutes, et le défaut visé est un argument oublié — il se
    voit exactement là. Un test qui construit les deux objets à la main ne verrait rien.
    """
    import inspect

    from ai.training_utils import make_training_env

    source = inspect.getsource(make_training_env)
    engine_call = source.split("W40KEngine(")[1].split("\n        )")[0]
    wrapper_call = source.split("BotControlledEnv(")[1].split("\n        )")[0]

    assert "training_episode_start_index=episode_start_index" in engine_call, (
        "la rampe de déploiement est une compétence acquise : elle doit reprendre"
    )
    assert "episode_start_index" not in wrapper_call, (
        "la rampe de self-play appartient au régime de CE run : son warmup ne doit pas être "
        "déjà consommé par un run précédent"
    )
