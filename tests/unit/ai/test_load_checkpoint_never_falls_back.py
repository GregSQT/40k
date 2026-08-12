"""`--append` sur un checkpoint illisible doit LEVER, jamais repartir de poids aléatoires.

Les trois sites de chargement de `ai/train.py` entouraient `MaskablePPO.load` d'un
`except Exception` qui construisait un modèle NEUF et poursuivait : un `--append` dont le .zip
était corrompu, tronqué ou remplacé s'entraînait des heures depuis des poids aléatoires, sortait
en code 0, et n'en disait que deux lignes noyées dans le log. Le seul signal était le win-rate du
run suivant. Décision du 2026-08-12 : l'échec de lecture n'a aucune reprise métier valide.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import ai.train as train

TRAIN_PY = Path(__file__).resolve().parents[3] / "ai" / "train.py"


def test_unreadable_checkpoint_raises(tmp_path: Path) -> None:
    """Un .zip qui n'en est pas un doit produire une erreur qui NOMME le fichier et dit quoi faire."""
    faux = tmp_path / "model_ArmageddonAgent.zip"
    faux.write_bytes(b"ceci n'est pas une archive")

    with pytest.raises(RuntimeError) as exc:
        train._load_checkpoint(str(faux), env=None, device="cpu")

    message = str(exc.value)
    assert str(faux) in message, "l'erreur doit nommer le checkpoint fautif"
    assert "--new" in message, "l'erreur doit dire par quoi repartir volontairement de zero"


def test_missing_checkpoint_raises(tmp_path: Path) -> None:
    """Meme exigence sur un chemin absent : c'est le cas d'un --append mal oriente."""
    with pytest.raises(RuntimeError):
        train._load_checkpoint(str(tmp_path / "absent.zip"), env=None, device="cpu")


def test_no_load_site_rebuilds_a_model_on_failure() -> None:
    """Aucun `except` autour d'un chargement ne doit reconstruire un `MaskablePPO`.

    Verrou STRUCTUREL, et c'est le seul possible : le repli vivait sur TROIS sites, avec trois
    messages differents. Supprimer les trois sans interdire le motif laisse le quatrieme le
    reintroduire silencieusement — c'est precisement ainsi que ce repli a survecu jusqu'ici.
    """
    tree = ast.parse(TRAIN_PY.read_text(encoding="utf-8"))
    fautifs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        charge = any(
            isinstance(n, ast.Attribute) and n.attr == "load"
            for corps in node.body for n in ast.walk(corps)
        )
        if not charge:
            continue
        for handler in node.handlers:
            reconstruit = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "MaskablePPO"
                for n in ast.walk(handler)
            )
            if reconstruit:
                fautifs.append(f"ligne {handler.lineno}")
    assert not fautifs, (
        f"un `except` autour d'un chargement reconstruit un MaskablePPO : {fautifs}. "
        "Un --append dont le checkpoint est illisible doit s'arreter, pas s'entrainer des heures "
        "depuis des poids aleatoires en sortant en code 0."
    )
