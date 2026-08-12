"""Un checkpoint illisible ARRETE le run — il ne se transforme pas en modele neuf.

Les trois sites de chargement de `ai/train.py` entouraient `MaskablePPO.load` d'un
`except Exception` qui construisait un modele NEUF et poursuivait l'entrainement. Consequence
sur un `--append` dont le .zip est corrompu, tronque ou absent : des heures d'entrainement depuis
des poids aleatoires, un code de sortie 0, et pour seul signal deux lignes « Failed to load
model / Creating new model instead » noyees dans le log. Le desastre ne se voyait qu'au win-rate
du run suivant.
"""

import zipfile
from pathlib import Path

import pytest

import ai.train as train

from .test_train_helpers import _function_code


def test_load_checkpoint_raises_on_a_corrupt_zip(tmp_path: Path) -> None:
    """Le cas vecu : le .zip existe, donc `os.path.exists` est vrai et la branche --append est
    prise, mais son contenu n'est pas un checkpoint."""
    corrupt = tmp_path / "model_CoreAgent.zip"
    corrupt.write_bytes(b"ce n'est pas une archive zip")

    with pytest.raises(RuntimeError) as excinfo:
        train._load_checkpoint(str(corrupt), env=None, device="cpu")

    message = str(excinfo.value)
    assert str(corrupt) in message, "le message doit NOMMER le chemin du modele illisible"
    assert "--new" in message, "le message doit rappeler l'option pour repartir de zero"


def test_load_checkpoint_raises_on_a_valid_zip_that_is_not_a_checkpoint(tmp_path: Path) -> None:
    """VERT VACANT : un fichier non-zip echoue des le premier octet lu. Une archive VALIDE mais
    sans les entrees attendues par SB3 fait echouer `load` plus loin (KeyError / pickle), et c'est
    ce chemin-la que l'`except Exception` supprime aussi."""
    archive = tmp_path / "model_CoreAgent.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "archive valide, checkpoint absent")
    assert zipfile.is_zipfile(archive), "l'echantillon doit vraiment etre une archive lisible"

    with pytest.raises(RuntimeError, match="Checkpoint illisible"):
        train._load_checkpoint(str(archive), env=None, device="cpu")


def test_load_checkpoint_raises_on_a_missing_path(tmp_path: Path) -> None:
    absent = tmp_path / "jamais_ecrit.zip"
    with pytest.raises(RuntimeError, match="Checkpoint illisible"):
        train._load_checkpoint(str(absent), env=None, device="cpu")


def test_load_checkpoint_chains_the_original_cause(tmp_path: Path) -> None:
    """`raise ... from exc` : sans la cause chainee, la traceback ne dit plus POURQUOI le zip est
    illisible (tronque ? mauvais pickle ? droits ?) et le diagnostic repart de zero."""
    corrupt = tmp_path / "model.zip"
    corrupt.write_bytes(b"\x00\x01\x02")

    with pytest.raises(RuntimeError) as excinfo:
        train._load_checkpoint(str(corrupt), env=None, device="cpu")

    assert excinfo.value.__cause__ is not None, "la cause d'origine doit rester chainee"


@pytest.mark.parametrize(
    "func_name", ["create_multi_agent_model", "train_with_scenario_rotation"]
)
def test_no_training_entry_point_rebuilds_a_model_when_the_load_fails(func_name: str) -> None:
    """JUMEAU — le motif du repli existait en TROIS exemplaires deja divergents (deux `print`,
    un `chunk_log`, un emoji casse) : c'est ainsi qu'un repli survit a la suppression de son
    jumeau. Les deux points d'entree d'entrainement doivent passer par `_load_checkpoint` et ne
    plus rattraper son echec.
    """
    code = _function_code(getattr(train, func_name))

    assert "_load_checkpoint(" in code, (
        f"{func_name} ne charge plus le checkpoint par le helper qui leve"
    )
    # Cible `model_path` et pas tout `MaskablePPO.load(` : `train_with_scenario_rotation` en garde
    # un usage LEGITIME, la relecture du snapshot de self-play qu'il vient d'ecrire lui-meme.
    assert "MaskablePPO.load(model_path" not in code, (
        f"{func_name} recharge le checkpoint en direct : le repli peut y etre revenu"
    )
    assert "Creating new model instead" not in code, (
        f"{func_name} reconstruit un modele neuf sur echec de chargement"
    )
