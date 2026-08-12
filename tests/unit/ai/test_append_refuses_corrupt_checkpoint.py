"""Un checkpoint illisible ARRETE le run — il ne se transforme pas en modele neuf.

Les trois sites de chargement de `ai/train.py` entouraient `MaskablePPO.load` d'un
`except Exception` qui construisait un modele NEUF et poursuivait l'entrainement. Consequence
sur un `--append` dont le .zip est corrompu, tronque ou absent : des heures d'entrainement depuis
des poids aleatoires, un code de sortie 0, et pour seul signal deux lignes « Failed to load
model / Creating new model instead » noyees dans le log. Le desastre ne se voyait qu'au win-rate
du run suivant.
"""

import ast
import zipfile
from pathlib import Path

import pytest

import ai.train as train

from .test_train_helpers import _function_code

TRAIN_PY = Path(__file__).resolve().parents[3] / "ai" / "train.py"


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


def test_load_checkpoint_diagnoses_an_observation_space_mismatch(monkeypatch) -> None:
    """Mode d'echec DOMINANT apres un changement d'obs_size (199 -> 1011, GRID_CHANNELS 7 -> 9) :
    le .zip est intact, c'est l'environnement qui a change. Un message unique « verifier
    l'integrite du .zip » envoie chercher un probleme de fichier qui n'existe pas.
    """
    def _refuse(*_args, **_kwargs):
        raise ValueError(
            "Observation spaces do not match: Box(-1.0, 1.0, (199,), float32) "
            "!= Box(-1.0, 1.0, (1011,), float32)"
        )

    monkeypatch.setattr(train.MaskablePPO, "load", staticmethod(_refuse))

    with pytest.raises(RuntimeError) as excinfo:
        train._load_checkpoint("ai/models/CoreAgent/model_CoreAgent.zip", env=None, device="cpu")

    message = str(excinfo.value)
    assert "incompatible" in message, "le desaccord d'espace doit avoir son propre diagnostic"
    assert "integrite du .zip" not in message, (
        "un fichier intact ne doit pas etre presente comme corrompu"
    )
    assert "--new" in message


def test_no_recovery_message_names_a_flag_that_does_not_exist() -> None:
    """Les messages de recuperation apres echec de chargement proposent une COMMANDE. `--new-model`
    n'existe pas dans l'argparse de ce module : la commande copiee sortait en erreur d'argument.
    """
    source = TRAIN_PY.read_text(encoding="utf-8")
    assert "--new-model" not in source, "flag inexistant propose dans un message d'aide"
    assert '"--new"' in source, "VERT VACANT : le flag reellement declare doit etre trouve ici"

    # La doc porte les MEMES commandes, copiees-collees telles quelles, et le meme flag mort y
    # avait survecu a sa correction dans le code : un fichier de distance 1 que la sentinelle ne
    # regardait pas.
    doc = TRAIN_PY.parent.parent / "Documentation" / "AI_TRAINING.md"
    assert doc.exists(), "VERT VACANT : la doc d'entrainement doit etre trouvee"
    assert "--new-model" not in doc.read_text(encoding="utf-8"), (
        "flag inexistant propose dans Documentation/AI_TRAINING.md"
    )


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


def test_no_load_site_at_all_rebuilds_a_model_on_failure() -> None:
    """Meme interdit, mais sur TOUT le module et sans liste de fonctions a tenir a jour.

    Le test ci-dessus nomme les deux points d'entree connus : un TROISIEME site de chargement,
    ajoute demain, y echapperait en silence — et c'est exactement l'histoire de ce repli, qui a
    survecu a la suppression de ses jumeaux. Celui-ci n'interroge plus des noms mais le MOTIF :
    un `except` qui enveloppe un chargement et y reconstruit un `MaskablePPO`.
    """
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    essais_de_chargement = 0
    fautifs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # `MaskablePPO.load` / `VecNormalize.load`, jamais `json.load` : mesure du 2026-08-12, la
        # sentinelle comptait quatre `json.load` et restait donc verte apres suppression de TOUS
        # les chargements de modele — elle ne pouvait plus voir ce pour quoi elle existe.
        charge = any(
            isinstance(n, ast.Attribute) and n.attr == "load"
            and isinstance(n.value, ast.Name) and n.value.id in ("MaskablePPO", "VecNormalize")
            for corps in node.body for n in ast.walk(corps)
        )
        if not charge:
            continue
        essais_de_chargement += 1
        for handler in node.handlers:
            if any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "MaskablePPO"
                for n in ast.walk(handler)
            ):
                fautifs.append(f"ai/train.py:{handler.lineno}")
    # VERT VACANT : sans ce compte, la suppression du dernier `try` autour d'un chargement rendrait
    # ce test vert en ne regardant plus rien.
    assert essais_de_chargement >= 1, "aucun chargement sous `try` trouve : le test regarde le vide"
    assert not fautifs, (
        f"un `except` autour d'un chargement reconstruit un MaskablePPO : {fautifs}. "
        "Un --append dont le checkpoint est illisible doit s'arreter, pas s'entrainer des heures "
        "depuis des poids aleatoires en sortant en code 0."
    )
