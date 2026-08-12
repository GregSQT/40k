"""V11 §0.36 — `--new` archive les artefacts CANONIQUES du run précédent.

Deux dégâts constatés en production, tous deux silencieux :

1. `model_<agent>_robust_meta.json` est lu par `BotEvaluationCallback` comme un **seuil** : le
   modèle canonique n'est mis à jour que si le nouveau score robuste dépasse celui qui y est
   écrit. Un run `--new` héritait donc du score d'un run précédent — mesuré sur un autre modèle,
   parfois sur un run avorté (constaté : `0.457372` hérité d'un run mort au marqueur 24 000).
2. `model_<agent>.zip` et `best_model.zip` étaient **écrasés** par le run neuf : l'agent
   précédent disparaissait sans trace.

Ce fichier verrouille l'archivage horodaté et, surtout, ce qui NE doit PAS être archivé : les
modèles nommés avec leur score sont l'historique, leur nom est unique, ils restent en place.
"""

import json
import os

import pytest

from ai.train import archive_canonical_artifacts_for_new_run, canonical_run_artifacts


def _populate(model_dir) -> str:
    model_path = str(model_dir / "model_TestAgent.zip")
    (model_dir / "model_TestAgent.zip").write_bytes(b"zip")
    (model_dir / "model_TestAgent_vec_normalize.pkl").write_bytes(b"pkl")
    (model_dir / "model_TestAgent_robust_meta.json").write_text(json.dumps({"robust_score": 0.45}))
    (model_dir / "best_model.zip").write_bytes(b"best")
    # Historique : nom UNIQUE, doit survivre.
    (model_dir / "TestAgent_12345_robust_0.4574.zip").write_bytes(b"scored")
    (model_dir / "ppo_checkpoint_1680000_steps.zip").write_bytes(b"ckpt")
    return model_path


def test_canonical_artifacts_are_the_fixed_name_ones(tmp_path) -> None:
    model_path = str(tmp_path / "model_TestAgent.zip")
    names = {os.path.basename(p) for p in canonical_run_artifacts(model_path)}
    assert names == {
        "model_TestAgent.zip",
        "model_TestAgent_vec_normalize.pkl",
        # Le compte d'episodes deja joues suit le modele : laisse en place, il ferait reprendre
        # les rampes du run NEUF au compteur du run precedent (V11 §0.58).
        "model_TestAgent_run_state.json",
        "model_TestAgent_robust_meta.json",
        "best_model.zip",
        # Le best_model est sauve AVEC ses stats (`_save_model_with_vecnormalize`) : les laisser
        # en place pendant que leur zip part a l'archive, c'est les faire ecraser par le run
        # suivant et rendre le best_model archive inexploitable (V11 §0.35).
        "best_model_vec_normalize.pkl",
        # La sauvegarde d'urgence du Ctrl-C porte elle aussi un nom FIXE : laissée en place, le
        # premier accident du run suivant l'écrase et les poids du run précédent sont perdus.
        "model_TestAgent_interrupted.zip",
        "model_TestAgent_interrupted_vec_normalize.pkl",
        "model_TestAgent_interrupted_run_state.json",
    }


def test_new_run_archives_the_threshold_and_the_agent(tmp_path) -> None:
    model_path = _populate(tmp_path)

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    assert len(moved) == 4
    for original in ("model_TestAgent.zip", "model_TestAgent_robust_meta.json", "best_model.zip"):
        assert not (tmp_path / original).exists(), f"{original} aurait été écrasé par le run neuf"
    # Le meta archivé garde son contenu : c'est une sauvegarde, pas une suppression.
    # Selection par NOM et non « le seul .json » : `_run_state.json` et le sidecar en sont aussi.
    archived_meta = [p for p in moved if "robust_meta" in os.path.basename(p)][0]
    assert json.loads(open(archived_meta).read())["robust_score"] == 0.45


def test_the_archived_model_stays_a_RESUMABLE_model(tmp_path) -> None:
    """Les compagnons prennent le nom derive du modele ARCHIVE, pas un suffixe a plat.

    `model_A_<stamp>.zip` a cote de `model_A_vec_normalize_<stamp>.pkl` : `companion_path` ne
    resout pas ce second nom, donc l'archive etait un zip sans stats ni compte d'episodes. C'est
    pourtant exactement ce que l'utilisateur ira rechercher pour revenir a son agent precedent —
    l'archivage promet de ne rien perdre, il doit rendre un modele entier.
    """
    from ai.run_state import get_run_state_path
    from ai.vec_normalize_utils import get_vec_normalize_path

    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent_run_state.json").write_text(json.dumps({"episodes_trained": 7}))

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    archived_model = [p for p in moved if os.path.basename(p).startswith("model_TestAgent_2")][0]
    assert os.path.exists(get_vec_normalize_path(archived_model)), (
        "le modele archive n'a plus ses stats sous un nom resolvable : il est irreprenable"
    )
    assert os.path.exists(get_run_state_path(archived_model))


def test_the_archived_best_model_keeps_its_own_stats(tmp_path) -> None:
    """`best_model.zip` est sauve avec ses stats : elles partent avec lui, sous son nom."""
    from ai.vec_normalize_utils import get_vec_normalize_path

    model_path = _populate(tmp_path)
    (tmp_path / "best_model_vec_normalize.pkl").write_bytes(b"best_pkl")

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    archived_best = [p for p in moved if os.path.basename(p).startswith("best_model_2")][0]
    assert not (tmp_path / "best_model_vec_normalize.pkl").exists(), (
        "les stats du best_model sont restees : le run suivant va les ecraser"
    )
    assert open(get_vec_normalize_path(archived_best), "rb").read() == b"best_pkl"


def test_the_tensorboard_sidecar_follows_the_archived_model(tmp_path) -> None:
    """Sans cela, le run neuf ECRASE le sidecar et le modele archive perd ses courbes."""
    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent.zip.tb_run.json").write_text(json.dumps({"run_dir": "/tb/run_A"}))

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    archived_model = [p for p in moved if os.path.basename(p).startswith("model_TestAgent_2")][0]
    assert not (tmp_path / "model_TestAgent.zip.tb_run.json").exists()
    assert json.loads(open(f"{archived_model}.tb_run.json").read())["run_dir"] == "/tb/run_A"


def test_new_run_leaves_an_EMPTY_sidecar_behind_the_archived_one(tmp_path, monkeypatch) -> None:
    """Le sidecar part a l'archive, mais un sidecar VIDE le remplace aussitot.

    Ne rien laisser ferait mourir le `--append` suivant dans `_read_tensorboard_run_meta` en
    conseillant un `--new` qui vient d'etre fait ; laisser l'ancien ferait ecrire le modele NEUF
    dans le run du modele archive, dont les steps sont plus avances.
    """
    from ai.train import prepare_run_artifacts

    class _Loader:
        def _resolve_agent_config_key(self, agent_key: str) -> str:
            return agent_key

    monkeypatch.setattr("ai.train.get_config_loader", lambda: _Loader())
    models_root = tmp_path / "models"
    (models_root / "TestAgent").mkdir(parents=True)
    model_path = _populate(models_root / "TestAgent")
    (models_root / "TestAgent" / "model_TestAgent.zip.tb_run.json").write_text(
        json.dumps({"run_dir": "/tb/run_A"})
    )

    prepare_run_artifacts(str(models_root), "TestAgent", new_model=True, append_training=False,
                          n_envs=1, log_fn=lambda _m: None)

    assert json.loads(open(f"{model_path}.tb_run.json").read())["run_dir"] == ""

    # Et ce sidecar VIDE ne bloque pas le `--new` suivant : il ne porte rien a sauver, donc rien
    # a ecarter. L'archiver quand meme faisait lever `FileExistsError` a deux `--new` dans la
    # meme minute — un run relance apres 20 s sur une config fausse.
    assert archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None) == []


def test_two_new_runs_one_second_apart_are_both_archivable(tmp_path, monkeypatch) -> None:
    """Un `--new` relancé aussitôt ne doit pas buter sur l'archive du précédent.

    Le premier run ouvre son run TensorBoard : le sidecar porte alors un `run_dir` RÉEL, donc il
    s'écarte comme les autres. À l'horodatage à la minute, le second `--new` visait exactement les
    mêmes noms d'archive et était refusé — pour un run mort en quelques secondes sur une config
    fausse, c'était une minute d'attente imposée.
    """
    import time

    # `ai.train.time` EST le module partagé : capturer le vrai `strftime` avant de le remplacer,
    # sinon le faux s'appelle lui-même.
    real_strftime = time.strftime
    moments = iter([time.localtime(1767225600), time.localtime(1767225601)])
    monkeypatch.setattr("ai.train.time.strftime", lambda fmt: real_strftime(fmt, next(moments)))

    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent.zip.tb_run.json").write_text(json.dumps({"run_dir": "/tb/run_A"}))
    archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    # Le run suivant recrée les mêmes noms canoniques, une seconde plus tard.
    _populate(tmp_path)
    (tmp_path / "model_TestAgent.zip.tb_run.json").write_text(json.dumps({"run_dir": "/tb/run_B"}))

    assert len(archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)) == 5


def test_a_corrupt_sidecar_does_not_block_the_archiving(tmp_path) -> None:
    """`--new` est la reparation recommandee quand ce sidecar ment : elle ne peut pas en dependre.

    L'ecriture du sidecar n'est pas atomique ; interrompue, elle laisse un JSON tronque. Lever
    dessus rendait `--new` impossible — l'agent devenait inarchivable et donc irremplacable.
    """
    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent.zip.tb_run.json").write_text('{"run_dir": "/tb/run_A"')  # tronque

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    # Conserve, pas supprime : il reste inspectable sous son nom horodate.
    assert any(p.endswith(".tb_run.json") for p in moved)
    assert not (tmp_path / "model_TestAgent.zip.tb_run.json").exists()


def test_an_unreadable_sidecar_does_not_block_the_archiving(tmp_path, monkeypatch) -> None:
    """Illisible par le SYSTÈME (droits, EIO) et pas seulement mal formé : même verrou.

    Ne rattraper que le JSON tronqué laissait une `OSError` interdire `--new` — l'agent devenait
    inarchivable pour une raison qui n'a rien à voir avec lui.
    """
    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent.zip.tb_run.json").write_text(json.dumps({"run_dir": "/tb/run_A"}))

    real_open = open

    def _refuse(path, *args, **kwargs):
        if str(path).endswith(".tb_run.json"):
            raise PermissionError("lecture refusee")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _refuse)
    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)
    monkeypatch.undo()

    # Conserve, pas supprime : il reste inspectable sous son nom horodate.
    assert any(p.endswith(".tb_run.json") for p in moved)
    assert not (tmp_path / "model_TestAgent.zip.tb_run.json").exists()


def test_the_interrupted_save_of_the_previous_run_is_archived_with_its_companions(tmp_path) -> None:
    """`--new` écarte la sauvegarde du Ctrl-C précédent : le prochain Ctrl-C l'écraserait."""
    from ai.run_state import get_run_state_path
    from ai.vec_normalize_utils import get_vec_normalize_path

    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent_interrupted.zip").write_bytes(b"interrompu")
    (tmp_path / "model_TestAgent_interrupted_vec_normalize.pkl").write_bytes(b"pkl")
    (tmp_path / "model_TestAgent_interrupted_run_state.json").write_text(json.dumps({"episodes_trained": 42}))

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    assert not (tmp_path / "model_TestAgent_interrupted.zip").exists()
    archived = [p for p in moved if os.path.basename(p).startswith("model_TestAgent_interrupted_2")][0]
    assert open(archived, "rb").read() == b"interrompu"
    # Et l'archive reste reprenable : ses compagnons portent le nom dérivé d'ELLE.
    assert os.path.exists(get_vec_normalize_path(archived))
    assert json.loads(open(get_run_state_path(archived)).read())["episodes_trained"] == 42


def test_scored_and_checkpoint_models_are_NOT_archived(tmp_path) -> None:
    """L'historique reste en place : son nom est unique, rien ne l'écrase."""
    model_path = _populate(tmp_path)

    archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    assert (tmp_path / "TestAgent_12345_robust_0.4574.zip").exists()
    assert (tmp_path / "ppo_checkpoint_1680000_steps.zip").exists()


def test_archiving_is_idempotent_and_tolerates_a_virgin_directory(tmp_path) -> None:
    """Un dossier vide n'est pas une erreur, et un second appel ne fait rien."""
    model_path = str(tmp_path / "model_TestAgent.zip")
    assert archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None) == []

    _populate(tmp_path)
    assert len(archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)) == 4
    assert archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None) == []


def test_archiving_never_overwrites_an_existing_archive(tmp_path, monkeypatch) -> None:
    """Deux `--new` au MÊME horodatage : lever, jamais écraser une sauvegarde.

    Horodatage figé : le lire ici et le relire dans l'archivage laissait le test rater dès qu'une
    frontière de temps tombait entre les deux — il ne construisait plus la collision qu'il observe.
    """
    monkeypatch.setattr("ai.train.time.strftime", lambda _fmt: "20260101-000000")

    model_path = _populate(tmp_path)
    (tmp_path / "model_TestAgent_20260101-000000.zip").write_bytes(b"deja la")

    with pytest.raises(FileExistsError):
        archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)
