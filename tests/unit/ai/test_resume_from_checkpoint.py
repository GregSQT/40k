#!/usr/bin/env python3
"""Reprise d'entrainement depuis un checkpoint periodique.

Verrouille les deux moities du contrat :
- le callback de checkpoint ecrit les stats VecNormalize A LA CONVENTION du projet
  (`<stem>_vec_normalize.pkl`), faute de quoi le zip est inexploitable pour reprendre ;
- `--resume-from` installe checkpoint + stats au chemin canonique, ecarte (sans ecraser)
  le modele precedent, et refuse un checkpoint sans stats plutot que de servir celles
  d'un autre modele (V11 §0.35) ;
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
    """Modele minimal : le callback n'en consomme que la sauvegarde et l'env normalise."""

    def __init__(self, env, logger):
        self.env = env
        self.logger = logger
        self.num_timesteps = 0

    def get_env(self):
        return self.env

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"MODEL")


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


def test_checkpoint_callback_writes_vec_normalize_stats(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = VecNormalizeCheckpointCallback(
        save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint"
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=4242))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    _run_checkpoint(callback, model, 640000)

    zip_path = os.path.join(save_path, "ppo_checkpoint_640000_steps.zip")
    assert os.path.exists(zip_path)
    # Le pkl doit porter EXACTEMENT le nom attendu par la reprise.
    assert os.path.exists(get_vec_normalize_path(zip_path))
    # Et le compte d'episodes, sans quoi le zip n'est pas reprenable (V11 §0.58).
    assert load_run_state(zip_path) == 4242


def test_checkpoint_callback_refuses_to_save_without_an_episode_counter(models_root, tmp_path):
    """Compteur non branche = checkpoint irreprenable : on leve au lieu d'ecrire un zip inutile."""
    callback = VecNormalizeCheckpointCallback(
        save_freq=1, save_path=str(tmp_path / "ckpts"), name_prefix="ppo_checkpoint"
    )
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    with pytest.raises(RuntimeError, match="metrics_tracker"):
        _run_checkpoint(callback, model, 640000)


def test_rotating_callback_removes_stats_with_their_zip(models_root, tmp_path):
    save_path = str(tmp_path / "ckpts")
    callback = RotatingCheckpointCallback(
        max_checkpoints=2, save_freq=1, save_path=save_path, name_prefix="ppo_checkpoint"
    )
    callback.metrics_tracker = cast(Any, SimpleNamespace(episode_count=7))
    model = _make_vec_normalize_model()
    callback.init_callback(cast(Any, model))

    for steps in (100, 200, 300):
        _run_checkpoint(callback, model, steps)

    remaining = sorted(os.path.basename(p) for p in os.listdir(save_path))
    # Les TROIS artefacts d'un checkpoint partent ensemble : un orphelin serait relu par un
    # futur checkpoint de meme nom.
    assert remaining == [
        "ppo_checkpoint_200_steps.zip",
        "ppo_checkpoint_200_steps_run_state.json",
        "ppo_checkpoint_200_steps_vec_normalize.pkl",
        "ppo_checkpoint_300_steps.zip",
        "ppo_checkpoint_300_steps_run_state.json",
        "ppo_checkpoint_300_steps_vec_normalize.pkl",
    ]


def _write_previous_canonical_model(models_root, run_dir: str = "/tb/run_20260101-000000"):
    """Un modele canonique complet : poids, deux compagnons, et son sidecar TensorBoard."""
    previous = models_root / "TestAgent" / "model_TestAgent.zip"
    previous.write_bytes(b"PREVIOUS")
    (models_root / "TestAgent" / "model_TestAgent_vec_normalize.pkl").write_bytes(b"PREVIOUS_STATS")
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
        ["train.py", "--agent", "TestAgent", "--training-config", "x1", "--resume-from", ckpt],
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
    assert len(sorted(agent_dir.glob("*_pre_resume_*"))) == 6, sorted(
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

    with pytest.raises(ValueError, match="canonique"):
        _promote_checkpoint_for_resume(str(canonical), "TestAgent", _FakeConfigLoader(str(models_root)), log_fn=lambda _m: None)
