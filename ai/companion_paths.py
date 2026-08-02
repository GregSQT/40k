"""Derivation du chemin d'un fichier COMPAGNON d'un modele. Module feuille, sans dependance.

`<dir>/model_<agent>.zip` -> `<dir>/model_<agent><suffix>`.

Un nom PAR MODELE, jamais un fichier partage par le dossier : le fichier unique avait deja fait
supprimer les stats d'une evaluation en cours (V11 §0.35). La derivation etait recopiee dans
`vec_normalize_utils`, `run_state` et l'enumeration canonique de `train.py` ; elle vit ici.
"""

from __future__ import annotations

import os


def companion_path(model_path: str, suffix: str) -> str:
    """Chemin du compagnon `suffix` du modele `model_path`."""
    if not model_path:
        raise ValueError("companion_path: model_path vide")
    model_dir = os.path.dirname(model_path)
    stem = os.path.splitext(os.path.basename(model_path))[0]
    if not stem:
        # Sans nom de fichier, tous les modeles du dossier partageraient LE MEME compagnon —
        # exactement le defaut que la derivation par nom ferme (V11 §0.35).
        raise ValueError(f"companion_path: model_path sans nom de fichier : {model_path!r}")
    return os.path.join(model_dir, f"{stem}{suffix}")
