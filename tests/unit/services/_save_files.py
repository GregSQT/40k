r"""Écriture d'un fichier de save DE TEST : en-tête au choix, cadre binaire de PRODUCTION.

POURQUOI ICI ET PAS DANS CHAQUE MODULE. Le cadre d'un enregistrement vient de `_pack_record`,
la fonction qu'utilise le serveur : un test qui le réécrit à la main reste vert le jour où le
cadre change, sur un fichier que le serveur n'écrit plus. Ce corps existait en DEUX exemplaires —
`test_save_format_key_contract` (refus des en-têtes périmés) et
`test_game_saves_restricted_unpickle` (relecture d'un fichier sain) —, donc la garantie ne tenait
que dans l'un des deux.

Un module `_xxx.py` importé, et non une fixture de `conftest.py` : c'est un appel de fonction, pas
un état à monter, et c'est la convention déjà en place dans ce dossier (`_auth_neutre.py`).

L'en-tête est un PARAMÈTRE et la row aussi, sans valeur par défaut : les deux modules appelants
mettent à l'épreuve des choses différentes — l'un l'octet d'en-tête, l'autre le contenu relu —,
et un défaut ferait qu'un appelant croie tester avec ce que l'autre a choisi.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from services.game_saves import SaveStore, _pack_record

#: Row valide dont le CONTENU ne prouve rien : elle sert aux tests qui n'éprouvent que l'en-tête.
ROW_MINIMALE: Dict[str, Any] = {
    "meta": {"id": "20260101-000000", "kind": "manual", "turn": 1},
    "state": {"game_state": {}, "engine_attrs": {}},
}


def ecrire_save_sous_magic(tmp_path: Any, magic: bytes, row: Dict[str, Any]) -> SaveStore:
    """Écrit une partie d'un seul enregistrement sous `magic`, et rend le store qui la porte.

    Le nom du fichier est dérivé de l'en-tête : il n'est asserté par personne, et le dériver
    évite qu'un appelant nomme « saine » une partie écrite sous une magic périmée.
    """
    store = SaveStore(str(tmp_path / "parties"))
    os.makedirs(store._dir, exist_ok=True)
    nom = f"partie_{magic.decode().lower()}"
    with open(os.path.join(store._dir, f"{nom}.pkl"), "wb") as f:
        f.write(magic)
        f.write(_pack_record(row))
    store.set_current(nom)
    return store
