"""Etat de run d'un modele — combien d'episodes il a DEJA joues.

POURQUOI (V11 §0.58).
Le mode de deploiement du moteur est une rampe pilotee par un
compteur d'episodes, et elle repartait de zero a chaque reprise (`--append`, `--resume-from`)
parce que rien ne survivait au processus : le `.zip` ne persiste que `num_timesteps`. Consequence
mesurable : la part d'episodes joues en deploiement actif n'atteignait jamais `active_ratio_end`,
donc l'agent etait note sur des parties a deployer apres un entrainement qui n'avait jamais
atteint le regime prevu.

CE COMPTEUR NE PILOTE PAS `learning_rate`, `ent_coef` NI LA RAMPE DE SELF-PLAY (decision
utilisateur du 2026-08-02, verrouillee par
`test_regime_ramps_start_from_this_run_not_from_the_model_lifetime`). Ce sont des rampes de
REGIME : une phase 2 est un profil INDEPENDANT lance en `--append`, son `learning_rate.initial`
et son warmup de self-play doivent s'appliquer. Comptees depuis la vie du modele, elles seraient
saturees des le premier episode. Le compteur sert donc a la rampe de deploiement et au compte
d'episodes persiste (axe TensorBoard, barre de progression, cible du resume final).

CE COMPTEUR N'EST PAS DERIVE DE `num_timesteps`. La longueur d'un episode varie du simple au
triple selon le scenario et l'issue : une conversion pas -> episodes produirait un chiffre invente
qui a l'air juste. Il est COMPTE (somme des `dones` du VecEnv, via le tracker de metriques) puis
ecrit ici a chaque sauvegarde du modele.

Fichier compagnon du `.zip`, meme patron que les stats VecNormalize
(`ai/vec_normalize_utils.get_vec_normalize_path`) : un nom par modele, donc supprimer les artefacts
d'un modele ne peut pas detruire l'etat d'un autre.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ai.companion_paths import companion_path
from shared.data_validation import require_non_negative_int

RUN_STATE_SUFFIX = "_run_state.json"


def get_run_state_path(model_path: str) -> str:
    """Chemin de l'etat de run d'UN modele : `<dir>/<nom_du_zip>_run_state.json`."""
    return companion_path(model_path, RUN_STATE_SUFFIX)


def save_run_state(model_path: str, episodes_trained: Any) -> str:
    """Ecrit l'etat de run a cote du modele. Ecriture ATOMIQUE (tmp + `os.replace`).

    Un fichier tronque par une interruption serait pire que pas de fichier : il ferait reprendre
    une rampe a une valeur arbitraire au lieu de lever.
    """
    require_non_negative_int(episodes_trained, "episodes_trained")
    path = get_run_state_path(model_path)
    tmp_path = f"{path}.tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"episodes_trained": int(episodes_trained)}, handle)
    os.replace(tmp_path, path)
    return path


def load_run_state(model_path: str) -> int:
    """Episodes deja joues par ce modele. LEVE si l'etat manque — aucune valeur par defaut.

    Un modele anterieur a ce mecanisme n'est pas reprenable : voir l'en-tete du module.
    """
    path = get_run_state_path(model_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Etat de run introuvable : {path}\n"
            f"Le modele '{os.path.basename(model_path)}' a ete entraine avant que le nombre "
            "d'episodes ne soit persiste, ou son fichier compagnon a ete perdu. Reprendre sans "
            "lui remettrait la rampe de deploiement a `active_ratio_start` et repartirait d'un "
            "compte d'episodes nul sur un modele deja entraine. Repartir avec `--new`."
        )
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "episodes_trained" not in payload:
        raise ValueError(f"Etat de run invalide (cle 'episodes_trained' absente) : {path}")
    episodes = payload["episodes_trained"]
    if not isinstance(episodes, int) or isinstance(episodes, bool) or episodes < 0:
        raise ValueError(f"Etat de run invalide (episodes_trained={episodes!r}) : {path}")
    return episodes


def remove_run_state(model_path: str) -> None:
    """Supprime l'etat de run d'un modele. Jumeau de la suppression des stats VecNormalize."""
    path = get_run_state_path(model_path)
    if os.path.exists(path):
        os.remove(path)
