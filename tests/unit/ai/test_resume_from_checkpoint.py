#!/usr/bin/env python3
"""Reprise d'entrainement depuis un checkpoint periodique.

Verrouille les deux moities du contrat :
- le callback de checkpoint ecrit les stats VecNormalize A LA CONVENTION du projet
  (`<stem>_vec_normalize.pkl`), faute de quoi le zip est inexploitable pour reprendre, et une
  copie du contrat d'entrainement du run (`<stem>_training_contract.json`) ;
- `--resume-from` installe checkpoint + stats + contrat DU CHECKPOINT au chemin canonique,
  ecarte (sans ecraser) le modele precedent, et refuse un checkpoint sans stats plutot que de
  servir celles d'un autre modele (V11 §0.35) — meme refus sans contrat (test_training_contract) ;
- la promotion est TRANSACTIONNELLE : tant que l'entrainement n'a pas demarre, tout echec
  (checkpoint illisible, environnement inconstruisible, Ctrl-C) remet le modele precedent a
  sa place. Sans cela, un `--resume-from` rate laissait l'inexploitable au chemin canonique
  et le bon modele sous son seul nom `_pre_resume_*`, que la commande suivante ne lit pas.
"""

import json
import os
import shutil
from typing import Any, cast

import pytest
from types import SimpleNamespace

import ai.train
from ai.train import (
    RotatingCheckpointCallback,
    VecNormalizeCheckpointCallback,
    _commit_resume_promotion,
    _promote_checkpoint_for_resume,
    _rollback_resume_promotion_if_pending,
)
from ai.run_state import get_run_state_path, load_run_state
from ai.training_contract import contract_path
from ai.vec_normalize_utils import get_vec_normalize_path


class _FakeConfigLoader:
    """Expose uniquement ce que `_promote_checkpoint_for_resume` consomme."""

    def __init__(self, models_root: str):
        self._models_root = models_root

    def get_models_root(self) -> str:
        return self._models_root

    def _resolve_agent_config_key(self, agent_key: str) -> str:
        return agent_key

    def load_agent_training_config(self, agent_key: str, phase: str | None = None) -> dict:
        return {}


@pytest.fixture(autouse=True)
def _no_promotion_leak():
    """Aucun test ne demarre ni ne finit avec une transaction armee.

    Le global survit a l'appel qui l'arme : une promotion laissee en attente ferait restaurer,
    dans le test SUIVANT, un modele qui n'a rien a voir — et le ferait passer ou echouer pour
    la mauvaise raison.
    """
    ai.train._pending_resume_promotion = None
    yield
    ai.train._pending_resume_promotion = None


@pytest.fixture
def models_root(tmp_path, monkeypatch):
    root = tmp_path / "models"
    (root / "TestAgent").mkdir(parents=True)
    monkeypatch.setattr("ai.train.get_config_loader", lambda: _FakeConfigLoader(str(root)))
    return root


def _write_checkpoint(models_root, steps: int, with_stats: bool = True, with_run_state: bool = True):
    ckpt = models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps.zip"
    ckpt.write_bytes(b"CHECKPOINT")
    # Troisieme jumeau : le contrat sous lequel CE checkpoint a appris, celui que la promotion
    # installe (jamais celui du canonique ecarte).
    (models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps_training_contract.json").write_bytes(
        b"CHECKPOINT_CONTRACT"
    )
    if with_stats:
        # Le pkl jumeau porte le nom du zip : c'est ce chemin que la reprise exige.
        (models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps_vec_normalize.pkl").write_bytes(b"STATS")
    if with_run_state:
        # Second jumeau (V11 §0.58) : le compte d'episodes deja joues, sans lequel la reprise
        # relancerait la rampe de deploiement depuis `active_ratio_start`.
        (models_root / "TestAgent" / f"ppo_checkpoint_{steps}_steps_run_state.json").write_text(
            json.dumps({"episodes_trained": 12345}), encoding="utf-8"
        )
    return str(ckpt)


def test_promote_installs_checkpoint_and_its_stats(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    model_path = _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    assert model_path == str(models_root / "TestAgent" / "model_TestAgent.zip")
    assert open(model_path, "rb").read() == b"CHECKPOINT"
    assert open(get_vec_normalize_path(model_path), "rb").read() == b"STATS"
    assert load_run_state(model_path) == 12345, "l'etat de run suit le checkpoint promu"
    assert open(contract_path(model_path), "rb").read() == b"CHECKPOINT_CONTRACT", (
        "le contrat installe n'est pas celui du checkpoint promu"
    )
    # Le checkpoint source reste en place (copie, pas deplacement).
    assert os.path.exists(ckpt)


def test_promote_resets_tensorboard_run(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    model_path = _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    # run_dir vide => `_resolve_tensorboard_run_dir` ouvre un run neuf au lieu de prolonger
    # celui qui a produit le checkpoint (dont les steps sont PLUS AVANCES).
    with open(f"{model_path}.tb_run.json", encoding="utf-8") as f:
        assert json.load(f)["run_dir"] == ""


def test_promote_sets_aside_previous_canonical_model(models_root):
    ckpt = _write_checkpoint(models_root, 640000)
    previous = models_root / "TestAgent" / "model_TestAgent.zip"
    previous.write_bytes(b"PREVIOUS")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"PREVIOUS_STATS")
    (models_root / "TestAgent" / "model_TestAgent_run_state.json").write_text(
        json.dumps({"episodes_trained": 999}), encoding="utf-8"
    )

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    set_aside = sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*.zip"))
    assert len(set_aside) == 1
    assert set_aside[0].read_bytes() == b"PREVIOUS"
    assert get_vec_normalize_path(str(set_aside[0]))
    assert open(get_vec_normalize_path(str(set_aside[0])), "rb").read() == b"PREVIOUS_STATS"
    # L'etat de run du modele ecarte part avec lui : sinon il serait relu comme celui du nouveau.
    assert load_run_state(str(set_aside[0])) == 999
    assert load_run_state(str(models_root / "TestAgent" / "model_TestAgent.zip")) == 12345


def test_promote_rejects_checkpoint_without_stats(models_root):
    ckpt = _write_checkpoint(models_root, 480000, with_stats=False)

    with pytest.raises(FileNotFoundError, match="VecNormalize"):
        _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    # Rien n'a ete installe : pas de reprise silencieuse sur des stats etrangeres.
    assert not os.path.exists(models_root / "TestAgent" / "model_TestAgent.zip")


def test_promote_rejects_checkpoint_without_run_state(models_root):
    """Un checkpoint anterieur au mecanisme n'est pas reprenable : erreur, pas de reprise a zero.

    Le refus tombe AVANT toute modification du disque : le modele canonique existant reste en
    place. Un controle place apres la mise a l'ecart laissait l'agent sans `model_<agent>.zip`.
    """
    ckpt = _write_checkpoint(models_root, 480000, with_run_state=False)
    canonical = models_root / "TestAgent" / "model_TestAgent.zip"
    canonical.write_bytes(b"PREVIOUS")

    with pytest.raises(FileNotFoundError, match="etat de run"):
        _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    assert canonical.read_bytes() == b"PREVIOUS", "le modele canonique a ete ecarte malgre l'echec"
    assert not sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*.zip"))


def test_promote_rejects_missing_checkpoint(models_root):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        _promote_checkpoint_for_resume(
            str(models_root / "TestAgent" / "absent.zip"), "TestAgent",
            _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None,
        )


def test_promote_requires_agent(models_root):
    ckpt = _write_checkpoint(models_root, 640000)

    with pytest.raises(ValueError, match="--agent"):
        _promote_checkpoint_for_resume(ckpt, "", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)


class _FakeModel:
    """Modele minimal : le callback n'en consomme que la sauvegarde et l'env normalise ;
    `train_model` y ajoute un `learn()` qui n'apprend rien."""

    def __init__(self, env, logger):
        self.env = env
        self.logger = logger
        self.num_timesteps = 0

    def get_env(self):
        return self.env

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"MODEL")

    def learn(self, **kwargs):
        pass


def _make_vec_normalize_model():
    import gymnasium as gym
    import numpy as np
    from stable_baselines3.common.logger import Logger
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    class _TrivialEnv(gym.Env):
        observation_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(2,), dtype=np.float32)
        action_space = gym.spaces.Discrete(2)

        def reset(self, *, seed=None, options=None):
            return np.zeros(2, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(2, dtype=np.float32), 0.0, False, False, {}

    venv = VecNormalize(DummyVecEnv([lambda: _TrivialEnv()]))
    return _FakeModel(venv, Logger(folder=None, output_formats=[]))


def _run_checkpoint(callback, model, timesteps: int):
    model.num_timesteps = timesteps
    callback.on_step()


#: Horodatage de run fige : le nom d'un checkpoint le porte (`<prefix>_<run>_<pas>_steps.zip`).
RUN = "20260912-120000"


def _run_contract(tmp_path) -> str:
    """Le contrat du run, tel que le prologue le laisse a cote du modele canonique."""
    path = tmp_path / "model_TestAgent_training_contract.json"
    path.write_bytes(b"RUN_CONTRACT")
    return str(path)


def test_checkpoint_callback_writes_vec_normalize_stats(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = VecNormalizeCheckpointCallback(
        run_stamp=RUN, run_contract_path=_run_contract(tmp_path),
        save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint",
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=4242))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    _run_checkpoint(callback, model, 640000)

    zip_path = os.path.join(save_path, f"ppo_checkpoint_{RUN}_640000_steps.zip")
    assert os.path.exists(zip_path)
    # Le pkl doit porter EXACTEMENT le nom attendu par la reprise.
    assert os.path.exists(get_vec_normalize_path(zip_path))
    # Et le compte d'episodes, sans quoi le zip n'est pas reprenable (V11 §0.58).
    assert load_run_state(zip_path) == 4242
    # Et le contrat du run, sans quoi `--resume-from` ne saurait pas sur quoi il a appris.
    assert open(contract_path(zip_path), "rb").read() == b"RUN_CONTRACT"


def test_checkpoint_callback_refuses_to_save_without_the_run_contract(models_root, tmp_path):
    """Contrat du run absent = checkpoint irreprenable : on leve, on n'ecrit pas un zip muet."""
    callback = VecNormalizeCheckpointCallback(
        run_stamp=RUN, run_contract_path=str(tmp_path / "absent_training_contract.json"),
        save_freq=1, save_path=str(tmp_path / "ckpts"), name_prefix="ppo_checkpoint",
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=1))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    with pytest.raises(FileNotFoundError, match="Contrat du run absent"):
        _run_checkpoint(callback, model, 640000)


def test_checkpoint_callback_refuses_to_save_without_an_episode_counter(models_root, tmp_path):
    """Compteur non branche = checkpoint irreprenable : on leve au lieu d'ecrire un zip inutile."""
    callback = VecNormalizeCheckpointCallback(
        run_stamp=RUN, run_contract_path=_run_contract(tmp_path),
        save_freq=1, save_path=str(tmp_path / "ckpts"), name_prefix="ppo_checkpoint",
    )
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    with pytest.raises(RuntimeError, match="metrics_tracker"):
        _run_checkpoint(callback, model, 640000)


@pytest.mark.parametrize("run_stamp", ["", None, 20260912])
def test_checkpoint_callback_refuses_an_empty_run_stamp(tmp_path, run_stamp):
    """Sans horodatage de run, deux runs ecrivent les memes noms : refuse a la construction."""
    with pytest.raises(ValueError, match="run_stamp"):
        VecNormalizeCheckpointCallback(
            run_stamp=cast(Any, run_stamp), run_contract_path=_run_contract(tmp_path),
            save_freq=1, save_path=str(tmp_path), name_prefix="ppo_checkpoint",
        )


def test_two_runs_at_the_same_step_count_never_overwrite_each_other(models_root, tmp_path):
    """Un `--new` repart de 0, un `--resume-from` continue au compte du checkpoint promu : les
    deux atteignent les comptes du run precedent. Nomme par le seul nombre de pas, le checkpoint
    du run entrant ECRASAIT celui du run sortant — et son compte d'episodes avec (V11 §0.58)."""
    save_path = str(tmp_path / "ckpts")
    model = _make_vec_normalize_model()
    run_contract = _run_contract(tmp_path)

    for run_stamp, episodes in (("20260912-100000", 111), ("20260912-110000", 222)):
        callback = VecNormalizeCheckpointCallback(
            run_stamp=run_stamp, run_contract_path=run_contract,
            save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint",
        )
        callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=episodes))
        callback.init_callback(cast(Any, model))
        _run_checkpoint(callback, model, 50000)

    zips = sorted(p for p in os.listdir(save_path) if p.endswith(".zip"))
    assert zips == [
        "ppo_checkpoint_20260912-100000_50000_steps.zip",
        "ppo_checkpoint_20260912-110000_50000_steps.zip",
    ]
    # Le checkpoint du premier run est intact, compte d'episodes compris.
    assert load_run_state(os.path.join(save_path, zips[0])) == 111
    assert load_run_state(os.path.join(save_path, zips[1])) == 222


def test_rotating_callback_removes_stats_with_their_zip(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = RotatingCheckpointCallback(
        max_checkpoints=2, run_stamp=RUN, run_contract_path=_run_contract(tmp_path),
        save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint",
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=7))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    for steps in (100, 200, 300):
        _run_checkpoint(callback, model, steps)

    remaining = sorted(os.path.basename(p) for p in os.listdir(save_path))
    # Les QUATRE artefacts d'un checkpoint partent ensemble : un orphelin serait relu par un
    # futur checkpoint de meme nom.
    assert remaining == [
        f"ppo_checkpoint_{RUN}_200_steps.zip",
        f"ppo_checkpoint_{RUN}_200_steps_run_state.json",
        f"ppo_checkpoint_{RUN}_200_steps_training_contract.json",
        f"ppo_checkpoint_{RUN}_200_steps_vec_normalize.pkl",
        f"ppo_checkpoint_{RUN}_300_steps.zip",
        f"ppo_checkpoint_{RUN}_300_steps_run_state.json",
        f"ppo_checkpoint_{RUN}_300_steps_training_contract.json",
        f"ppo_checkpoint_{RUN}_300_steps_vec_normalize.pkl",
    ]


def _write_stale_checkpoint(save_path, steps: str) -> None:
    (save_path / f"ppo_checkpoint_{steps}_steps.zip").write_bytes(b"stale")
    (save_path / f"ppo_checkpoint_{steps}_steps_vec_normalize.pkl").write_bytes(b"stale")
    (save_path / f"ppo_checkpoint_{steps}_steps_run_state.json").write_text('{"episodes_trained": 1}')
    (save_path / f"ppo_checkpoint_{steps}_steps_training_contract.json").write_bytes(b"stale")


def test_rotating_callback_leaves_the_checkpoints_of_a_previous_run_in_place(models_root, tmp_path):
    """Reproduction du 2026-09-12 : trois checkpoints périmés à 24 M pas, un run `--new` qui repart
    de 0. La rotation triait TOUS les `<prefix>_*_steps.zip` du dossier par nombre de pas : les
    checkpoints du run neuf, toujours les plus « anciens en pas », partaient à chaque écriture et
    seuls les trois périmés survivaient — aucun checkpoint conservé pour aucun run depuis."""
    save_path = tmp_path / "ckpts"
    save_path.mkdir()
    for steps in ("24309576", "24549576", "24789576"):
        _write_stale_checkpoint(save_path, steps)
    callback = RotatingCheckpointCallback(
        max_checkpoints=3, run_stamp=RUN, run_contract_path=_run_contract(tmp_path),
        save_freq=1, save_path=str(save_path), name_prefix="ppo_checkpoint",
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=7))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    for steps in (10000, 20000, 30000, 40000):
        _run_checkpoint(callback, model, steps)

    remaining = sorted(p for p in os.listdir(save_path) if p.endswith(".zip"))
    # Le périmé reste en place (contrat `test_scored_and_checkpoint_models_are_NOT_archived`) ;
    # la rotation ne porte que sur ce que CE callback a écrit : 10000 part, les trois derniers restent.
    assert remaining == [
        f"ppo_checkpoint_{RUN}_20000_steps.zip",
        f"ppo_checkpoint_{RUN}_30000_steps.zip",
        f"ppo_checkpoint_{RUN}_40000_steps.zip",
        "ppo_checkpoint_24309576_steps.zip",
        "ppo_checkpoint_24549576_steps.zip",
        "ppo_checkpoint_24789576_steps.zip",
    ]
    # Et les compagnons du checkpoint tourné partent avec lui.
    assert not any(p.startswith(f"ppo_checkpoint_{RUN}_10000_steps") for p in os.listdir(save_path))


def test_train_model_keeps_the_checkpoints_of_the_run_after_publishing(
    models_root, tmp_path, monkeypatch
):
    """Joue le VRAI `train_model` (apprentissage a vide) : le run reussi publie le canonique et
    LAISSE ses checkpoints periodiques — ils sont l'historique reprenable, comme ceux d'un run
    precedent (decision du 2026-09-12, cf. `VecNormalizeCheckpointCallback`). Seul le
    `_interrupted` d'un Ctrl-C precedent part, avec ses compagnons. Avant : un balayage
    `ppo_*_steps.zip` du dossier emportait tout, perime compris, en laissant orphelin son compte
    d'episodes."""
    import ai.metrics_tracker as metrics_tracker_module

    model_dir = models_root / "TestAgent"
    model_path = str(model_dir / "model_TestAgent.zip")
    _write_stale_checkpoint(model_dir, "24789576")
    interrupted = ai.train._interrupted_model_path(model_path)
    open(interrupted, "wb").close()
    (model_dir / "model_TestAgent_interrupted_run_state.json").write_text('{"episodes_trained": 1}')

    class _FakeTracker:
        def __init__(self, agent_name, tensorboard_dir, **kwargs):
            self.episode_count = 7

        def truncation_summary_lines(self):
            return []

    class _NoLearnCallback:
        def __init__(self, *args, **kwargs):
            pass

        def print_final_training_summary(self, **kwargs):
            pass

    monkeypatch.setattr(metrics_tracker_module, "W40KMetricsTracker", _FakeTracker)
    monkeypatch.setattr(metrics_tracker_module, "resolve_perf_windows", lambda cfg: (100, 10))
    monkeypatch.setattr(ai.train, "MetricsCollectionCallback", _NoLearnCallback)

    model = _make_vec_normalize_model()
    model.logger = SimpleNamespace(get_dir=lambda: str(tmp_path / "tb"))
    callback = VecNormalizeCheckpointCallback(
        run_stamp=RUN, run_contract_path=_run_contract(model_dir),
        save_freq=1, save_path=str(model_dir), name_prefix="ppo_checkpoint",
    )
    callback.init_callback(cast(Any, model))
    # Le tracker n'est pose par `train_model` qu'AVANT `learn()` : pour ecrire les checkpoints
    # sans apprendre, on le pose ici et on joue le callback a la main.
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=7))
    for steps in (10000, 20000):
        _run_checkpoint(callback, model, steps)

    training_config = {"total_timesteps": 1, "callback_params": {"save_best_robust": False}}
    assert ai.train.train_model(model, training_config, [callback], model_path, "x1", "TestAgent") is True

    assert sorted(os.listdir(model_dir)) == [
        "model_TestAgent.zip",
        "model_TestAgent_run_state.json",
        "model_TestAgent_training_contract.json",
        "model_TestAgent_vec_normalize.pkl",
        f"ppo_checkpoint_{RUN}_10000_steps.zip",
        f"ppo_checkpoint_{RUN}_10000_steps_run_state.json",
        f"ppo_checkpoint_{RUN}_10000_steps_training_contract.json",
        f"ppo_checkpoint_{RUN}_10000_steps_vec_normalize.pkl",
        f"ppo_checkpoint_{RUN}_20000_steps.zip",
        f"ppo_checkpoint_{RUN}_20000_steps_run_state.json",
        f"ppo_checkpoint_{RUN}_20000_steps_training_contract.json",
        f"ppo_checkpoint_{RUN}_20000_steps_vec_normalize.pkl",
        "ppo_checkpoint_24789576_steps.zip",
        "ppo_checkpoint_24789576_steps_run_state.json",
        "ppo_checkpoint_24789576_steps_training_contract.json",
        "ppo_checkpoint_24789576_steps_vec_normalize.pkl",
    ]


def test_train_model_saves_the_interrupted_model_with_the_run_contract(
    models_root, tmp_path, monkeypatch
):
    """Le `_interrupted` du Ctrl-C est reprenable par `--resume-from` : il emporte le contrat.

    Sans lui, la promotion de cette sauvegarde d'urgence — le seul artefact d'un run interrompu —
    s'arreterait sur « contrat absent », ou reposerait celui du canonique en le supposant.
    """
    import ai.metrics_tracker as metrics_tracker_module

    model_dir = models_root / "TestAgent"
    model_path = str(model_dir / "model_TestAgent.zip")
    run_contract = _run_contract(model_dir)

    class _FakeTracker:
        def __init__(self, agent_name, tensorboard_dir, **kwargs):
            self.episode_count = 7

        def truncation_summary_lines(self):
            return []

    class _NoLearnCallback:
        def __init__(self, *args, **kwargs):
            pass

    class _InterruptedModel(_FakeModel):
        def learn(self, **kwargs):
            raise KeyboardInterrupt

    monkeypatch.setattr(metrics_tracker_module, "W40KMetricsTracker", _FakeTracker)
    monkeypatch.setattr(metrics_tracker_module, "resolve_perf_windows", lambda cfg: (100, 10))
    monkeypatch.setattr(ai.train, "MetricsCollectionCallback", _NoLearnCallback)

    base = _make_vec_normalize_model()
    model = _InterruptedModel(base.env, SimpleNamespace(get_dir=lambda: str(tmp_path / "tb")))
    training_config = {"total_timesteps": 1, "callback_params": {"save_best_robust": False}}

    assert ai.train.train_model(model, training_config, [], model_path, "x1", "TestAgent") is False

    interrupted = ai.train._interrupted_model_path(model_path)
    assert open(interrupted, "rb").read() == b"MODEL"
    assert load_run_state(interrupted) == 7
    assert open(contract_path(interrupted), "rb").read() == open(run_contract, "rb").read(), (
        "la sauvegarde d'urgence n'emporte pas le contrat du run : elle n'est pas reprenable"
    )


def _write_previous_canonical_model(models_root, run_dir: str = "/tb/run_20260101-000000"):
    """Un modele canonique complet : poids, trois compagnons, et son sidecar TensorBoard."""
    previous = models_root / "TestAgent" / "model_TestAgent.zip"
    previous.write_bytes(b"PREVIOUS")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"PREVIOUS_STATS")
    (models_root / "TestAgent" / "model_TestAgent_training_contract.json").write_bytes(b"PREVIOUS_CONTRACT")
    (models_root / "TestAgent" / "model_TestAgent_run_state.json").write_text(
        json.dumps({"episodes_trained": 999}), encoding="utf-8"
    )
    (models_root / "TestAgent" / "model_TestAgent.zip.tb_run.json").write_text(
        json.dumps({"run_dir": run_dir}), encoding="utf-8"
    )
    return previous


def test_promote_moves_tensorboard_sidecar_with_the_set_aside_model(models_root):
    """Le sidecar suit le modele ecarte, sinon la promotion l'ECRASE et le run est perdu.

    `_write_tensorboard_run_meta(model_path, "")` ecrit au meme chemin : laisse en place, le
    modele `_pre_resume_*` devenait definitivement detache de ses courbes, et sa restauration
    aurait rendu un modele sans run.
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    set_aside = sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*.zip"))[0]
    archived_meta = models_root / "TestAgent" / f"{set_aside.name}.tb_run.json"
    assert json.loads(archived_meta.read_text())["run_dir"] == "/tb/run_20260101-000000"


def test_rollback_restores_the_previous_model_with_all_its_artefacts(models_root):
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    _rollback_resume_promotion_if_pending()

    agent_dir = models_root / "TestAgent"
    model_path = agent_dir / "model_TestAgent.zip"
    assert model_path.read_bytes() == b"PREVIOUS", "le checkpoint promu est reste au chemin canonique"
    assert (agent_dir / "model_TestAgent_vec_normalize.pkl").read_bytes() == b"PREVIOUS_STATS"
    assert load_run_state(str(model_path)) == 999, "l'etat de run promu a survecu a l'annulation"
    assert json.loads((agent_dir / "model_TestAgent.zip.tb_run.json").read_text())["run_dir"] == (
        "/tb/run_20260101-000000"
    ), "le run TensorBoard du modele restaure n'est pas revenu"
    # Plus aucune trace de la promotion : un `_pre_resume_*` restant serait relu comme un
    # modele a part entiere par l'enumeration canonique.
    assert not sorted(agent_dir.glob("model_TestAgent_pre_resume_*"))
    # La source, elle, n'a jamais bouge : la promotion copie, elle ne deplace pas.
    assert os.path.exists(ckpt)


def test_rollback_removes_the_installed_checkpoint_when_there_was_no_previous_model(models_root):
    """Sans modele precedent, annuler = ne rien laisser derriere — pas meme un compagnon.

    Un `model_TestAgent_vec_normalize.pkl` orphelin serait relu par le PROCHAIN modele du meme
    nom, avec les stats de normalisation d'un autre entrainement (V11 §0.35).
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    _rollback_resume_promotion_if_pending()

    assert sorted(os.listdir(models_root / "TestAgent")) == [
        "ppo_checkpoint_640000_steps.zip",
        "ppo_checkpoint_640000_steps_run_state.json",
        "ppo_checkpoint_640000_steps_training_contract.json",
        "ppo_checkpoint_640000_steps_vec_normalize.pkl",
    ]


def test_commit_makes_the_promotion_final(models_root):
    """Passe le demarrage de l'entrainement, restaurer effacerait du travail reel."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    _commit_resume_promotion()
    _rollback_resume_promotion_if_pending()

    model_path = models_root / "TestAgent" / "model_TestAgent.zip"
    assert model_path.read_bytes() == b"CHECKPOINT", "l'entrainement a demarre, la promotion a ete defaite"
    assert load_run_state(str(model_path)) == 12345


def test_rollback_is_idempotent(models_root):
    """Le chemin d'exception de `main()` restaure, puis son `finally` repasse : sans idempotence,
    la seconde passe supprimerait le modele qui vient d'etre remis en place.

    Les DEUX niveaux sont verifies : le desarmement du global, et la garde interne — la seconde
    passe d'une restauration deja faite retirerait `model_<agent>.zip`, qui porte desormais le
    modele restaure, et le detruirait pour de bon.
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    promotion = ai.train._pending_resume_promotion
    assert promotion is not None, "la promotion n'a pas arme la transaction"

    _rollback_resume_promotion_if_pending()
    _rollback_resume_promotion_if_pending()
    promotion.rollback()

    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"


def _run_main_failing_after_promotion(monkeypatch, ckpt, exc):
    """Pilote le VRAI `main()` jusqu'a un echec place juste apres la promotion.

    `_require_training_config_phase` est le premier appel qui suit `_promote_checkpoint_for_resume`
    dans `main()`. Ces deux tests ne verifient pas la restauration elle-meme (les tests ci-dessus
    le font) mais qu'elle est REELLEMENT ATTEINTE depuis les sorties de `main()` : c'est
    exactement le motif « code teste mais jamais appele » qui a produit ce bug.
    """
    import sys

    monkeypatch.setattr(
        sys, "argv",
        ["train.py", "--agent", "TestAgent", "--training-config", "x1", "--resolution", "1", "--resume-from", ckpt],
    )

    def _fail(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(ai.train, "_require_training_config_phase", _fail)
    return ai.train.main()


def _assert_promotion_really_happened(capsys) -> None:
    """Sans cela, le test serait VERT A VIDE : un echec survenu AVANT la promotion laisse lui
    aussi le modele precedent intact, et prouverait donc une restauration qui n'a pas eu lieu."""
    out = capsys.readouterr().out
    assert "--resume-from : ppo_checkpoint_640000_steps.zip installe en" in out, (
        f"la promotion n'a jamais eu lieu, le test ne prouve rien :\n{out}"
    )
    assert "--resume-from annule" in out, f"aucune restauration n'a ete journalisee :\n{out}"


def test_main_rolls_back_when_training_setup_fails_after_promotion(models_root, monkeypatch, capsys):
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)

    exit_code = _run_main_failing_after_promotion(
        monkeypatch, ckpt, RuntimeError("phase de config introuvable")
    )

    assert exit_code == 1
    _assert_promotion_really_happened(capsys)
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS", (
        "main() a laisse le checkpoint promu au chemin canonique apres un echec"
    )
    assert not sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*"))


def test_main_rolls_back_on_keyboard_interrupt_before_training(models_root, monkeypatch, capsys):
    """Ctrl-C avant le premier pas : `KeyboardInterrupt` n'est pas une `Exception`, elle traverse
    le `except` de `main()` — seul le `finally` la voit."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)

    with pytest.raises(KeyboardInterrupt):
        _run_main_failing_after_promotion(monkeypatch, ckpt, KeyboardInterrupt())

    _assert_promotion_really_happened(capsys)
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"
    assert not sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*"))


def _write_robust_run_artifacts(models_root, score: float = 0.62):
    """Les deux autres artefacts CANONIQUES d'un run : le seuil de score robuste et best_model."""
    (models_root / "TestAgent" / "model_TestAgent_robust_meta.json").write_text(
        json.dumps({"robust_score": score}), encoding="utf-8"
    )
    (models_root / "TestAgent" / "best_model.zip").write_bytes(b"BEST")


def test_promote_sets_aside_the_robust_threshold_and_best_model(models_root):
    """Jumeau de `--new` : la promotion ecarte TOUS les artefacts canoniques, pas seulement trois.

    `model_<agent>_robust_meta.json` est lu comme un SEUIL par `BotEvaluationCallback` : laisse en
    place, il impose au run repris de battre le score du run abandonne — mesure bien plus loin
    dans l'entrainement. Le run entier tournerait sans jamais mettre a jour le modele canonique
    (V11 §0.36).
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _write_robust_run_artifacts(models_root)
    agent_dir = models_root / "TestAgent"

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    assert not (agent_dir / "model_TestAgent_robust_meta.json").exists(), (
        "le seuil de score robuste du run precedent s'applique encore au run repris"
    )
    assert not (agent_dir / "best_model.zip").exists()
    # Modele, trois compagnons, sidecar TensorBoard, seuil robuste, best_model.
    assert len(sorted(agent_dir.glob("*_pre_resume_*"))) == 7, sorted(
        p.name for p in agent_dir.glob("*_pre_resume_*")
    )


def test_rollback_restores_the_robust_threshold_and_best_model(models_root):
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _write_robust_run_artifacts(models_root)
    agent_dir = models_root / "TestAgent"

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    _rollback_resume_promotion_if_pending()

    assert json.loads((agent_dir / "model_TestAgent_robust_meta.json").read_text())["robust_score"] == 0.62
    assert (agent_dir / "best_model.zip").read_bytes() == b"BEST"
    assert not sorted(agent_dir.glob("*_pre_resume_*"))


def test_promote_refuses_to_overwrite_an_existing_set_aside(models_root, monkeypatch):
    """Deux mises a l'ecart au meme horodatage : lever, jamais ecraser la seule copie du modele."""
    # Horodatage FIGE : le lire deux fois (ici et dans la promotion) fabriquait un test qui rate
    # des qu'une frontiere de seconde tombe entre les deux — il ne construirait plus la collision
    # qu'il observe.
    monkeypatch.setattr("ai.train.time.strftime", lambda _fmt: "20260101-000000")

    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    collision = models_root / "TestAgent" / "model_TestAgent_pre_resume_20260101-000000.zip"
    collision.write_bytes(b"DEJA LA")

    with pytest.raises(FileExistsError):
        _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    assert collision.read_bytes() == b"DEJA LA"
    # Le refus tombe avant tout deplacement : le modele canonique est intact.
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"

    # Et le refus n'arme RIEN : un rollback declenche par cette levee (c'est ce que fait le
    # `finally` de `main()`) prendrait l'archive preexistante pour la sienne et la deplacerait
    # par-dessus le modele vivant — le garde detruirait ce qu'il protege.
    _rollback_resume_promotion_if_pending()
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"
    assert collision.read_bytes() == b"DEJA LA"


def test_rollback_refuses_to_report_success_when_an_artefact_vanished(models_root):
    """Un artefact ni a sa place ni sous son nom ecarte : erreur explicite, pas un agent ampute
    annonce comme restaure."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    set_aside = sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*.zip"))[0]
    set_aside.unlink()

    with pytest.raises(FileNotFoundError, match="introuvable sous son nom d'origine"):
        _rollback_resume_promotion_if_pending()

    # RIEN n'a ete touche : le refus tombe avant la premiere suppression. Retirer le checkpoint
    # installe puis constater le manquant laissait l'agent SANS aucun `model_<agent>.zip`, avec
    # les compagnons de l'ancien run en orphelins — pire que l'etat qu'on voulait defaire.
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"CHECKPOINT"
    assert load_run_state(str(models_root / "TestAgent" / "model_TestAgent.zip")) == 12345


def test_rollback_removes_an_interrupted_save_of_the_abandoned_lineage(models_root):
    """Un Ctrl-C pendant le premier `env.reset()` sauve un `_interrupted.zip` DEPUIS LE CHECKPOINT
    PROMU. Le laisser derriere la restauration, c'est laisser un artefact reprenable de la lignee
    abandonnee a cote du modele rendu — et rien ne dirait lequel est lequel.
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    agent_dir = models_root / "TestAgent"

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    # Ce que fait le gestionnaire de Ctrl-C de `train_model`.
    (agent_dir / "model_TestAgent_interrupted.zip").write_bytes(b"PROMOTED_WEIGHTS")
    (agent_dir / "model_TestAgent_interrupted_vec_normalize.pkl").write_bytes(b"STATS")

    _rollback_resume_promotion_if_pending()

    assert not (agent_dir / "model_TestAgent_interrupted.zip").exists()
    assert not (agent_dir / "model_TestAgent_interrupted_vec_normalize.pkl").exists()
    assert (agent_dir / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"


def test_rollback_leaves_an_interrupted_save_that_predates_the_command(models_root):
    """Celui du run PRECEDENT, lui, appartient a l'utilisateur : la restauration n'y touche pas."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    agent_dir = models_root / "TestAgent"
    (agent_dir / "model_TestAgent_interrupted.zip").write_bytes(b"RUN_PRECEDENT")

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    # Elle a ete ECARTEE par la promotion, comme les autres artefacts a nom fixe : rien ne porte
    # plus ce nom pendant le run, donc rien ne peut l'ecraser.
    assert not (agent_dir / "model_TestAgent_interrupted.zip").exists()

    _rollback_resume_promotion_if_pending()

    assert (agent_dir / "model_TestAgent_interrupted.zip").read_bytes() == b"RUN_PRECEDENT"


def test_rollback_rewrites_an_empty_sidecar_it_could_not_set_aside(models_root):
    """Un sidecar VIDE n'est pas ecarte : la restauration doit donc le REECRIRE, pas le laisser
    absent. Sinon le `--append` suivant meurt dans `_read_tensorboard_run_meta` en conseillant un
    `--new` — c'est-a-dire de jeter le modele que cette restauration vient de sauver."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root, run_dir="")
    meta = models_root / "TestAgent" / "model_TestAgent.zip.tb_run.json"

    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    _rollback_resume_promotion_if_pending()

    assert meta.exists(), "le sidecar a disparu : le prochain --append refusera de demarrer"
    assert json.loads(meta.read_text())["run_dir"] == ""


def test_rollback_restores_a_promotion_interrupted_before_the_first_copy(models_root):
    """Ctrl-C entre la mise a l'ecart et l'installation : l'agent n'a PLUS de modele du tout.

    C'est la fenetre la plus courte et la plus destructrice de la promotion. La transaction est
    donc armee avant le deplacement, et la restauration ne doit surtout pas commencer par retirer
    `model_<agent>.zip` — a cet instant, ce chemin est vide, et le seul exemplaire du modele porte
    le nom `_pre_resume_*`.
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    agent_dir = models_root / "TestAgent"

    # Capture AVANT le patch : `ai.train.shutil` est le module partage, pas une copie.
    real_move = shutil.move

    def _interrupt_after_set_aside(src, dst):
        # Le vrai deplacement a lieu, puis la commande est coupee : c'est exactement l'etat
        # intermediaire qu'aucun drapeau deduit des fichiers presents ne saurait reconnaitre.
        real_move(src, dst)
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(ai.train.shutil, "move", _interrupt_after_set_aside)
            _promote_checkpoint_for_resume(
                ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None
            )

    assert not (agent_dir / "model_TestAgent.zip").exists(), "l'etat intermediaire teste n'existe pas"

    _rollback_resume_promotion_if_pending()

    assert (agent_dir / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"
    # Les compagnons n'avaient pas encore bouge : ils doivent etre restes en place, pas supprimes.
    assert (agent_dir / "model_TestAgent_vec_normalize.pkl").read_bytes() == b"PREVIOUS_STATS"
    assert load_run_state(str(agent_dir / "model_TestAgent.zip")) == 999
    assert not sorted(agent_dir.glob("model_TestAgent_pre_resume_*"))


def test_rollback_failure_keeps_the_original_error_and_says_where_the_model_is(models_root, capsys):
    """Si la restauration echoue, elle s'AJOUTE au diagnostic en cours au lieu de le remplacer.

    Relancer l'erreur de menage depuis le `finally` de `main()` ecraserait l'erreur fatale (ou le
    Ctrl-C) qui se propage : l'utilisateur perdrait la cause reelle ET l'emplacement de son modele.
    """
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    def _refuse(*_args, **_kwargs):
        raise PermissionError("fichier verrouille")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai.train.shutil, "move", _refuse)
        try:
            raise RuntimeError("erreur fatale d'origine")
        except RuntimeError:
            # Reproduit le contexte d'appel reel : une exception se propage deja.
            _rollback_resume_promotion_if_pending()

    out = capsys.readouterr().out
    assert "RESTAURATION IMPOSSIBLE" in out
    assert "_pre_resume_" in out, "le message ne dit pas ou retrouver le modele"


def test_rollback_failure_raises_when_nothing_else_is_propagating(models_root):
    """Hors chemin d'erreur, en revanche, l'echec de restauration ne doit pas etre avale :
    ce serait un depot casse rendu en code 0."""
    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)

    def _refuse(*_args, **_kwargs):
        raise PermissionError("fichier verrouille")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ai.train.shutil, "move", _refuse)
        with pytest.raises(PermissionError):
            _rollback_resume_promotion_if_pending()


@pytest.mark.parametrize("flag", ["--test-only", "--replay", "--convert-steplog"])
def test_resume_from_is_refused_with_the_modes_that_do_not_train(models_root, monkeypatch, flag):
    """Promouvoir puis defaire pour un mode qui n'entraine pas serait un aller-retour pour rien.

    L'evaluation d'un checkpoint se fait en le nommant, pas en l'installant au chemin canonique.
    """
    import sys

    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    argv = ["train.py", "--agent", "TestAgent", "--training-config", "x1", "--resume-from", ckpt, flag]
    if flag == "--convert-steplog":
        argv.append("step.log")  # seul des trois a prendre une valeur
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(ValueError, match="n'entraine pas"):
        ai.train.main()

    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"PREVIOUS"
    assert not sorted((models_root / "TestAgent").glob("model_TestAgent_pre_resume_*"))


def test_the_commit_travels_with_the_callbacks_of_every_entry_point():
    """La validation est posee par `setup_callbacks`, source UNIQUE des DEUX points d'entree.

    Recopiee sur chaque site d'appel de `learn()`, elle finissait par diverger — et surtout elle
    tombait AVANT `_setup_learn`, donc avant le premier `env.reset()` de SB3 : un echec la
    validait sans qu'un seul pas ait tourne. Ce test verrouille le fait qu'elle est branchee au
    premier pas REEL, et par un seul chemin.
    """
    import ast
    from pathlib import Path

    from ai.train import ResumePromotionCommitCallback

    module = ast.parse(Path(cast(str, ai.train.__file__)).read_text(encoding="utf-8"))
    setup = [
        node for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup_callbacks"
    ]
    assert len(setup) == 1
    assert any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "ResumePromotionCommitCallback"
        for inner in ast.walk(setup[0])
    ), "setup_callbacks ne pose plus la validation : aucun run ne rendrait sa promotion definitive"

    # Et plus AUCUN autre site ne valide : une validation posee ailleurs retomberait avant le
    # premier pas, ce que ce chantier corrige.
    commit_sites = [
        node.lineno for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_commit_resume_promotion"
    ]
    assert len(commit_sites) == 1, f"validations de promotion hors du callback : lignes {commit_sites}"


def test_the_commit_callback_fires_on_the_first_real_step(models_root):
    """Le callback valide bien la promotion — sinon il serait un decor."""
    from ai.train import ResumePromotionCommitCallback

    ckpt = _write_checkpoint(models_root, 640000)
    _write_previous_canonical_model(models_root)
    _promote_checkpoint_for_resume(ckpt, "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
    assert ai.train._pending_resume_promotion is not None

    assert ResumePromotionCommitCallback()._on_step() is True
    assert ai.train._pending_resume_promotion is None

    _rollback_resume_promotion_if_pending()
    assert (models_root / "TestAgent" / "model_TestAgent.zip").read_bytes() == b"CHECKPOINT"


def test_promote_rejects_canonical_model_as_source(models_root):
    canonical = models_root / "TestAgent" / "model_TestAgent.zip"
    canonical.write_bytes(b"CANONICAL")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"STATS")
    (models_root / "TestAgent" / "model_TestAgent_run_state.json").write_text(
        json.dumps({"episodes_trained": 1}), encoding="utf-8"
    )
    (models_root / "TestAgent" / "model_TestAgent_training_contract.json").write_bytes(b"CONTRACT")

    with pytest.raises(ValueError, match="canonique"):
        _promote_checkpoint_for_resume(str(canonical), "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
