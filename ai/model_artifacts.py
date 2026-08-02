"""Les fichiers qui vont AVEC un modele — enumeration, copie, suppression. Source unique.

Un modele entraine n'est pas un fichier, c'en est TROIS :

    model_<agent>.zip                 les poids
    model_<agent>_vec_normalize.pkl   les stats de normalisation (V11 §0.35)
    model_<agent>_run_state.json      les episodes deja joues     (V11 §0.58)

Les deux compagnons sont indispensables pour REPRENDRE : sans le pkl la reprise leve, sans
l'etat de run elle relancerait toutes les rampes par-episode depuis leur valeur de depart.

Ce module existe parce que la liste etait recopiee a la main sur chaque site qui manipule un
modele — enumeration canonique, rotation des checkpoints, promotion `--resume-from`, copie du
meilleur modele robuste, suppression d'un modele perime — chacun avec sa propre politique sur
les fichiers absents. Ajouter le troisieme fichier a demande de retrouver les cinq. Il n'y a
plus qu'un endroit ou le faire.

Les chemins des compagnons se DERIVENT du nom du zip (`companion_path`), et ce n'est pas
cosmetique : un fichier partage par tous les modeles d'un dossier avait deja provoque la
destruction des stats d'une evaluation en cours (V11 §0.35).
"""

from __future__ import annotations

import os
import shutil
from typing import List

from ai.companion_paths import companion_path
from ai.run_state import RUN_STATE_SUFFIX, remove_run_state, save_run_state
from ai.vec_normalize_utils import VEC_NORMALIZE_SUFFIX, get_vec_normalize_path

__all__ = [
    "companion_path",
    "model_companion_paths",
    "copy_model_with_companions",
    "remove_model_with_companions",
    "COMPANION_SUFFIXES",
]

#: Suffixes des compagnons, dans l'ordre ou on les enumere.
COMPANION_SUFFIXES = (VEC_NORMALIZE_SUFFIX, RUN_STATE_SUFFIX)


def model_companion_paths(model_path: str) -> List[str]:
    """Les compagnons d'un modele (sans le `.zip` lui-meme), qu'ils existent ou non."""
    return [companion_path(model_path, suffix) for suffix in COMPANION_SUFFIXES]


def copy_model_with_companions(src_model_zip: str, dst_model_zip: str, episodes_trained: int) -> None:
    """Copie un modele et ses compagnons. L'etat de run est REECRIT, jamais devine.

    `episodes_trained` est le compte au moment de la copie : la source vient d'etre sauvee dans
    le meme tour, c'est le meme nombre — et l'ecrire ici evite de le persister pour tous les
    modeles intermediaires que personne ne reprendra.
    """
    if not os.path.exists(src_model_zip):
        raise FileNotFoundError(f"Source model zip not found: {src_model_zip}")
    shutil.copy2(src_model_zip, dst_model_zip)

    src_vec_path = get_vec_normalize_path(src_model_zip)
    if os.path.exists(src_vec_path):
        # Optionnel : VecNormalize peut etre desactive dans la config.
        shutil.copy2(src_vec_path, get_vec_normalize_path(dst_model_zip))

    save_run_state(dst_model_zip, episodes_trained)


def remove_model_with_companions(model_zip_path: str) -> None:
    """Supprime un modele ET ses compagnons. Idempotent.

    Un compagnon orphelin serait relu par un futur modele de meme nom : stats d'un autre
    entrainement (V11 §0.35), ou compte d'episodes etranger (V11 §0.58).
    """
    if os.path.exists(model_zip_path):
        os.remove(model_zip_path)
    vec_path = get_vec_normalize_path(model_zip_path)
    if os.path.exists(vec_path):
        os.remove(vec_path)
    remove_run_state(model_zip_path)
