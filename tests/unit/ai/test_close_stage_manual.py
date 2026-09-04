"""Verrou — `--close-stage` clot une etape dont le run a ete interrompu.

Un run tue au clavier ou mort en vol ne revient jamais de `train_with_scenario_rotation` :
`_close_curriculum_stage` n'est donc pas atteint, et l'etape reste sans gate, sans ligne de
`curriculum.log` et sans `model_<agent>_<etape>.zip`. L'etape SUIVANTE nomme celle-ci dans son
`init` (`from:P1`) et refuse alors de demarrer, sur un `FileNotFoundError` de
`_apply_stage_init`. Aucun point d'entree n'exposait la cloture : `promote_stage_model` n'avait
qu'un seul appelant, la cloture elle-meme.

Ce fichier verrouille la reconstruction de `run_info` depuis les artefacts du disque, qui est la
seule partie propre a ce chemin — la cloture, elle, est celle du run nominal, inchangee.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest


class _Args:
    """Le sous-ensemble de `argparse.Namespace` que lit `_run_info_from_disk`."""

    def __init__(self, agent: str) -> None:
        self.agent = agent


class _Config:
    """Loader double : ne sert qu'a designer la racine des modeles."""

    def __init__(self, models_root: str) -> None:
        self._models_root = models_root

    def get_models_root(self) -> str:
        return self._models_root


def _canonical_path(models_root: str, agent: str) -> str:
    from ai.train import build_agent_model_path

    return build_agent_model_path(models_root, agent)


def _write_run_artifacts(
    models_root: str, agent: str, *, episodes: Any = 50165, run_dir: str = "./tensorboard/x1/run_1",
    with_run_state: bool = True, with_tb_meta: bool = True, with_model: bool = True,
) -> str:
    """Pose sur disque ce qu'un run interrompu laisse derriere lui."""
    model_path = _canonical_path(models_root, agent)
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    if with_model:
        with open(model_path, "wb") as handle:
            handle.write(b"zip")
    if with_run_state:
        from ai.run_state import get_run_state_path

        with open(get_run_state_path(model_path), "w", encoding="utf-8") as handle:
            json.dump({"episodes_trained": episodes}, handle)
    if with_tb_meta:
        with open(f"{model_path}.tb_run.json", "w", encoding="utf-8") as handle:
            json.dump({"run_dir": run_dir}, handle)
    return model_path


def test_run_info_is_rebuilt_from_the_artifacts_on_disk(tmp_path) -> None:
    """Les deux clés que la cloture EXIGE sont lues, pas devinees."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, "ArmageddonAgent_x1", episodes=57_240,
                         run_dir="./tensorboard/x1_long/run_20260903-181906")

    run_info = _run_info_from_disk(_Args("ArmageddonAgent_x1"), _Config(models_root))

    assert run_info["episode_count_total"] == 57_240
    assert run_info["tensorboard_run_dir"] == "./tensorboard/x1_long/run_20260903-181906"
    assert run_info["episodes_trained"] == 57_240


def test_last_bot_eval_is_absent_rather_than_invented(tmp_path) -> None:
    """Aucun score bot n'est fabrique pour un run qui n'en a pas rendu.

    `_close_curriculum_stage` lit cette cle avec `.get` et n'ecrit alors rien dans le journal.
    La remplir depuis TensorBoard daterait le journal d'une mesure prise a un autre moment que le
    modele promu.
    """
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, "ArmageddonAgent_x1")

    run_info = _run_info_from_disk(_Args("ArmageddonAgent_x1"), _Config(models_root))

    assert "last_bot_eval" not in run_info


def test_a_missing_canonical_model_is_refused(tmp_path) -> None:
    """Sans modele canonique, il n'y a rien a clore : erreur explicite, pas une promotion vide."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, "ArmageddonAgent_x1", with_model=False)

    with pytest.raises(FileNotFoundError, match="modele canonique absent"):
        _run_info_from_disk(_Args("ArmageddonAgent_x1"), _Config(models_root))


def test_a_missing_run_state_is_refused(tmp_path) -> None:
    """Le compte d'episodes ne se devine pas : il date le modele promu et pilote l'offset de
    l'etape suivante."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, "ArmageddonAgent_x1", with_run_state=False)

    with pytest.raises((FileNotFoundError, KeyError, ValueError)):
        _run_info_from_disk(_Args("ArmageddonAgent_x1"), _Config(models_root))


def test_a_missing_tensorboard_sidecar_is_refused(tmp_path) -> None:
    """Le repertoire TensorBoard ne se devine pas non plus : `copy_tensorboard_run` en depend."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, "ArmageddonAgent_x1", with_tb_meta=False)

    with pytest.raises(FileNotFoundError):
        _run_info_from_disk(_Args("ArmageddonAgent_x1"), _Config(models_root))


def test_close_stage_without_etape_is_refused_by_the_real_cli() -> None:
    """`--close-stage` sans `--etape` est refuse par la VRAIE ligne de commande.

    Passe par un sous-processus et non par une inspection de la source : ce qui doit etre
    verrouille, c'est que le drapeau est bien declare (sans quoi argparse repondrait
    « unrecognized arguments ») ET que la garde se declenche avant tout effet de bord. Lire la
    source prouverait seulement que deux chaines y figurent.
    """
    import subprocess
    import sys

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    ))))
    result = subprocess.run(
        [sys.executable, "ai/train.py", "--close-stage",
         "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long"],
        cwd=project_root, capture_output=True, text=True, timeout=300,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "unrecognized arguments" not in combined, "le drapeau --close-stage n'est pas declare"
    assert "--close-stage exige --etape" in combined, combined[-2000:]
