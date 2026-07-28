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
        "model_TestAgent_robust_meta.json",
        "best_model.zip",
    }


def test_new_run_archives_the_threshold_and_the_agent(tmp_path) -> None:
    model_path = _populate(tmp_path)

    moved = archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)

    assert len(moved) == 4
    for original in ("model_TestAgent.zip", "model_TestAgent_robust_meta.json", "best_model.zip"):
        assert not (tmp_path / original).exists(), f"{original} aurait été écrasé par le run neuf"
    # Le meta archivé garde son contenu : c'est une sauvegarde, pas une suppression.
    archived_meta = [p for p in moved if p.endswith(".json")][0]
    assert json.loads(open(archived_meta).read())["robust_score"] == 0.45


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


def test_archiving_never_overwrites_an_existing_archive(tmp_path) -> None:
    """Deux `--new` dans la MÊME minute : lever, jamais écraser une sauvegarde."""
    import time

    model_path = _populate(tmp_path)
    stamp = time.strftime("%Y%m%d-%H%M")
    (tmp_path / f"model_TestAgent_{stamp}.zip").write_bytes(b"deja la")

    with pytest.raises(FileExistsError):
        archive_canonical_artifacts_for_new_run(model_path, log_fn=lambda _m: None)
