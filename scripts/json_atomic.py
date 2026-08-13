#!/usr/bin/env python3
"""Écriture JSON atomique — forme UNIQUE du dépôt pour tout script qui produit un `.json`.

Le défaut que ce module supprime : `open(path, "w")` DÉTRUIT le fichier précédent à l'ouverture,
avant d'avoir écrit un octet. Une interruption (Ctrl-C, disque plein, exception à mi-parcours)
laisse alors un JSON tronqué À LA PLACE d'un relevé ou d'une config qui, eux, étaient valides.
Ici, tout passe par un brouillon `<path>.part` publié par `os.replace` — le fichier précédent
reste intact tant que le nouveau n'est pas complet, et la bascule est atomique.

Ce module existe parce que quatre scripts portaient chacun leur `_write_json` privé, tous
différents (`write_text` vs `open`, `ensure_ascii` dans les deux sens, `mkdir` implicite ici et
pas là). Le format d'écriture n'a donc AUCUN réglage ici : indentation 2, `ensure_ascii=False`,
retour à la ligne final. Un réglage rouvrirait la divergence qu'on ferme.

Trois contrôles à l'ouverture, aucun ne couvre les autres :
  - `path` ne doit pas être VIDE (`--json-out "$VAR"` avec `VAR` non définie : le `.part`
    atterrirait dans le cwd, et seul le `os.replace` final échouerait) ;
  - `path` ne doit pas être un DOSSIER — même échec, même moment : tout à la fin, quand le
    travail est déjà fait et perdu ;
  - le brouillon doit s'OUVRIR, ce qui prouve syscall à l'appui que le dossier existe et qu'il est
    inscriptible (un `isdir` laisserait passer un dossier en lecture seule).
Aucune création de dossier : un chemin faux se voit, il ne se répare pas en silence.

La FERMETURE appartient à l'écriture : c'est elle qui vide le tampon, donc c'est elle qui casse
sur un disque plein. Elle est dans le `try`, sinon un flush raté laisserait le brouillon derrière
lui sans rien publier — l'exact défaut que ce module existe pour supprimer. La PUBLICATION y est
aussi : quand elle rate, le brouillon part avec elle plutôt que de rester sous `config/`.

Durabilité : le brouillon est `fsync`é AVANT d'être publié, et le dossier APRÈS. Sans le premier,
le renommage peut devenir durable avant les données qu'il publie, et un crash hôte rend un fichier
VIDE là où une config valide tenait — la perte même que ce module nie. Sans le second, un crash
peut rendre l'ancien nom : le fichier reste valide, seule la publication est à refaire.
"""
from __future__ import annotations

import contextlib
import json
import os
from typing import Any, Iterator, Optional, TextIO

StrPath = str | os.PathLike[str]


def part_path(path: StrPath) -> str:
    """Chemin du brouillon. Public : les tests et les nettoyages ont besoin du MÊME nom."""
    return os.fspath(path) + ".part"


def dump_json(handle: TextIO, payload: Any) -> None:
    """Le format d'écriture du dépôt, en un seul endroit."""
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")


def _fsync_dir(directory: str) -> None:
    """Rend le RENOMMAGE durable. `os.replace` publie dans le cache du dossier ; sans ce fsync,
    un crash hôte peut rendre au redémarrage l'ANCIEN nom — jamais un fichier tronqué, donc
    l'invariant tient, mais la publication, elle, peut être à refaire sans qu'on le sache.
    """
    fd = os.open(directory or ".", os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _draft(path: StrPath) -> Iterator[TextIO]:
    if not os.fspath(path):
        raise ValueError("destination vide — variable de shell non définie ?")
    if os.path.isdir(path):
        raise IsADirectoryError(f"{os.fspath(path)} est un dossier : la destination doit être un fichier")
    handle = open(part_path(path), "w", encoding="utf-8")
    try:
        yield handle
        # Le flush APPARTIENT à l'écriture : s'il rate, on ne publie pas. Le fsync qui le suit
        # n'est pas du zèle — `os.replace` peut devenir durable AVANT les données qu'il publie,
        # et un crash hôte rendrait alors un fichier vide à la place d'une config valide, très
        # exactement la perte que ce module existe pour supprimer.
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        # DANS le `try` : une publication qui rate (destination devenue un dossier, droits
        # retirés pendant un run long) doit emporter le brouillon avec elle, pas le laisser
        # traîner sous `config/`.
        os.replace(part_path(path), path)
        _fsync_dir(os.path.dirname(os.fspath(path)))
    except BaseException:
        # Ménage best-effort, tout entier sous `suppress` : ce qui compte à cet instant, c'est
        # l'exception qui a tué le travail — une erreur de fermeture ou un brouillon déjà
        # disparu ne doivent pas prendre sa place. `path`, lui, n'a jamais été ouvert en
        # écriture : il porte encore sa version précédente, complète.
        with contextlib.suppress(OSError):
            handle.close()
        with contextlib.suppress(OSError):
            os.remove(part_path(path))
        raise


@contextlib.contextmanager
def json_out_draft(path: Optional[StrPath]) -> Iterator[Optional[TextIO]]:
    """Brouillon ouvert AVANT le travail, publié seulement si le travail va jusqu'au bout.

    Pour un producteur LONG (un run qui joue des épisodes) : tout ce qui peut rater sur la
    destination rate ici, en une seconde, pas après la partie quand les graines sont déjà perdues.
    `path is None` (drapeau absent) donne un handle `None` et ne touche à rien — c'est la forme
    qui évite un `if` autour de tout le corps de l'appelant.
    """
    if path is None:
        yield None
        return
    with _draft(path) as handle:
        yield handle


def write_json_atomic(path: StrPath, payload: Any) -> None:
    """Écrit un payload DÉJÀ construit. Le fichier précédent survit à toute erreur d'écriture."""
    with _draft(path) as handle:
        dump_json(handle, payload)
