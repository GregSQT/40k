#!/usr/bin/env python3
"""Écriture JSON atomique — forme UNIQUE du dépôt pour tout code qui publie un `.json`.

Le défaut que ce module supprime : `open(path, "w")` DÉTRUIT le fichier précédent à l'ouverture,
avant d'avoir écrit un octet. Une interruption (Ctrl-C, disque plein, exception à mi-parcours)
laisse alors un JSON tronqué À LA PLACE d'un relevé ou d'une config qui, eux, étaient valides.
Ici, tout passe par un brouillon publié par `os.replace` — le fichier précédent reste intact tant
que le nouveau n'est pas complet, et la bascule est atomique.

DEUX RÈGLES, PAS UNE. L'ATOMICITÉ vaut pour toute publication d'un `.json`, sans exception : c'est
elle qui protège le fichier précédent. Le FORMAT unifié (`dump_json` : indentation 2,
`ensure_ascii=False`, retour à la ligne final) ne vaut que là où il ne change pas la sortie —
il existe parce que quatre scripts portaient chacun leur `_write_json` privé, tous différents.
Les deux s'obtiennent séparément :
  - `write_json_atomic(path, payload)` = atomicité + format du dépôt, le cas courant ;
  - `json_draft(path)` = atomicité SEULE, le producteur écrit ce qu'il veut dans le handle ;
  - `json_out_draft(path_ou_None)` = le même, pour un drapeau `--json-out` qui peut être absent.
Un site qui a besoin d'une autre forme (`default=str` pour un cache d'objets, `separators`
compacts pour une table lue par le moteur, `sort_keys` pour un diff stable) passe par `json_draft`
et garde son propre `json.dump`. C'est pour ça que `dump_json` n'a AUCUN réglage : le besoin
d'un réglage est le signe qu'on veut le brouillon nu, pas une option de plus.

Deux noms pour le brouillon, et non un seul optionnel : `json_draft` rend un handle, `json_out_draft`
rend un handle OU `None`. Fondre les deux obligerait tout appelant à drapeau non optionnel — la
majorité — à écarter un `None` qui ne peut pas arriver, ce que le typage exige et que la lecture
ne pardonne pas.

Trois contrôles à l'ouverture, aucun ne couvre les autres :
  - `path` ne doit pas être VIDE (`--json-out "$VAR"` avec `VAR` non définie : le brouillon
    atterrirait dans le cwd, et seul le `os.replace` final échouerait) ;
  - `path` ne doit pas être un DOSSIER — même échec, même moment : tout à la fin, quand le
    travail est déjà fait et perdu ;
  - le brouillon doit s'OUVRIR, ce qui prouve syscall à l'appui que le dossier existe et qu'il est
    inscriptible (un `isdir` laisserait passer un dossier en lecture seule).
Aucune création de dossier : un chemin faux se voit, il ne se répare pas en silence.

Un brouillon resté VIDE ne se publie pas : il n'est pas un JSON, et il détruirait le fichier
précédent aussi sûrement qu'une troncature. L'appelant qui sort de son bloc sans rien écrire lève
donc, plutôt que de le découvrir en relisant le fichier.

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
import threading
from typing import Any, Iterator, Optional, TextIO

StrPath = str | os.PathLike[str]


def part_path(path: StrPath) -> str:
    """Chemin du brouillon de CET appel. Public : les tests et les nettoyages ont besoin du nom.

    Le nom porte le processus ET le fil, parce que deux écrivains de la MÊME destination
    existent réellement dans ce dépôt : `services/api_server.py` publie `save_config.json`
    depuis deux routes Flask (`/save/persist`, `/autosave/config`), et le serveur de Flask sert
    ses requêtes en fils concurrents. Avec un `<path>.part` commun, le second écrivain TRONQUE
    le brouillon du premier, puis les deux publient — et le `os.remove` de la branche d'erreur
    lève un `FileNotFoundError` qui REMPLACE l'exception d'origine. Deux appels d'un même fil,
    eux, ne se chevauchent jamais : le couple (pid, fil) suffit, et il reste prévisible, ce
    qu'un nom tiré au hasard ne serait pas.
    """
    return f"{os.fspath(path)}.{os.getpid()}.{threading.get_ident()}.part"


def dump_json(handle: TextIO, payload: Any) -> None:
    """Le format d'écriture du dépôt, en un seul endroit. Sans réglage : voir l'en-tête."""
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
def json_draft(path: StrPath) -> Iterator[TextIO]:
    """Brouillon ouvert AVANT le travail, publié seulement si le travail va jusqu'au bout.

    Deux usages, tous deux couverts par la même garantie :
      - un producteur LONG (un run qui joue des épisodes) : tout ce qui peut rater sur la
        destination rate ici, en une seconde, pas après la partie quand les graines sont perdues ;
      - une sortie dont la FORME n'est pas celle du dépôt : l'appelant fait son propre
        `json.dump(payload, handle, ...)` dans le brouillon (cf. l'en-tête du module).
    """
    if not os.fspath(path):
        raise ValueError("destination vide — variable de shell non définie ?")
    if os.path.isdir(path):
        raise IsADirectoryError(f"{os.fspath(path)} est un dossier : la destination doit être un fichier")
    draft = part_path(path)
    handle = open(draft, "w", encoding="utf-8")
    try:
        yield handle
        # Le flush APPARTIENT à l'écriture : s'il rate, on ne publie pas. Le fsync qui le suit
        # n'est pas du zèle — `os.replace` peut devenir durable AVANT les données qu'il publie,
        # et un crash hôte rendrait alors un fichier vide à la place d'une config valide, très
        # exactement la perte que ce module existe pour supprimer.
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        # Un brouillon VIDE n'est pas un JSON : le publier remplacerait un fichier valide par
        # zéro octet, atomiquement — la perte que ce module refuse, obtenue par sa propre
        # publication. Le cas arrive quand un appelant sort du bloc sans rien écrire (`return`
        # anticipé, boucle qui ne tourne pas) ; c'est un défaut chez lui, il doit le voir plutôt
        # que le découvrir à la relecture du fichier.
        if os.path.getsize(draft) == 0:
            raise ValueError(f"rien n'a été écrit pour {os.fspath(path)} : un fichier vide ne se publie pas")
        # DANS le `try` : une publication qui rate (destination devenue un dossier, droits
        # retirés pendant un run long) doit emporter le brouillon avec elle, pas le laisser
        # traîner sous `config/`.
        os.replace(draft, path)
    except BaseException:
        # Ménage best-effort, tout entier sous `suppress` : ce qui compte à cet instant, c'est
        # l'exception qui a tué le travail — une erreur de fermeture ou un brouillon déjà
        # disparu ne doivent pas prendre sa place. `path`, lui, n'a jamais été ouvert en
        # écriture : il porte encore sa version précédente, complète.
        with contextlib.suppress(OSError):
            handle.close()
        with contextlib.suppress(OSError):
            os.remove(draft)
        raise
    # APRÈS le `try`, et sous `suppress` : à ce point la publication a RÉUSSI, le fichier est
    # complet et fsyncé sur le disque. Laisser une panne de fsync du dossier remonter dirait à
    # l'appelant « rien n'écrit » alors que tout l'est — il abandonnerait une banque à moitié
    # reconstruite (les anciens rosters sont déjà supprimés) sur un mount qui ne sait pas
    # fsyncer un dossier (FUSE, réseau, overlay : EINVAL). Ce qui se perd ici n'est pas la
    # donnée, c'est la garantie que le RENOMMAGE survive à un crash : au pire, on relit la
    # version précédente, valide et complète.
    with contextlib.suppress(OSError):
        _fsync_dir(os.path.dirname(os.fspath(path)))


@contextlib.contextmanager
def json_out_draft(path: Optional[StrPath]) -> Iterator[Optional[TextIO]]:
    """`json_draft` pour un drapeau qui peut être ABSENT (`--json-out`).

    `path is None` donne un handle `None` et ne touche à rien — c'est la forme qui évite un `if`
    autour de tout le corps de l'appelant.
    """
    if path is None:
        yield None
        return
    with json_draft(path) as handle:
        yield handle


def write_json_atomic(path: StrPath, payload: Any) -> None:
    """Écrit un payload DÉJÀ construit. Le fichier précédent survit à toute erreur d'écriture."""
    with json_draft(path) as handle:
        dump_json(handle, payload)
