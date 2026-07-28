#!/usr/bin/env python3
"""
ai/vec_normalize_utils.py - VecNormalize save/load and inference normalization

Provides utilities for:
- Wrapping training envs with VecNormalize
- Saving/loading VecNormalize stats with model checkpoints
- Normalizing observations during inference (PvE, evaluation)
"""

import os
import numpy as np
from typing import Optional, Any

VEC_NORMALIZE_SUFFIX = "_vec_normalize.pkl"


def get_vec_normalize_path(model_path: str) -> str:
    """Chemin des stats VecNormalize d'UN modele : `<dir>/<nom_du_zip>_vec_normalize.pkl`.

    ⚠️ Ce chemin depend du NOM du modele, et ce n'est pas cosmetique (V11 §0.35).

    Il a longtemps valu `<dir>/vec_normalize.pkl` — un fichier UNIQUE partage par tous les
    modeles d'un meme dossier : le snapshot d'evaluation, les checkpoints, le meilleur modele
    robuste et le modele canonique ecrivaient et supprimaient tous LE MEME fichier. Or
    `BotEvaluationCallback` evalue en ASYNCHRONE : il sauve un snapshot (donc les stats), lance
    des workers qui chargent le pkl PARESSEUSEMENT au premier pas, puis consomme le resultat de
    l'evaluation PRECEDENTE — et cette consommation appelle `_remove_model_artifacts`, qui
    supprimait les stats que les workers de l'evaluation EN COURS n'avaient pas encore lues.
    Resultat mesure : 600/600 episodes d'evaluation en erreur en 7 s au marqueur 24 000, et le
    garde-fou strict a arrete un run de 5 h 30.

    Un nom par modele rend la suppression correcte PAR CONSTRUCTION : retirer les artefacts d'un
    modele ne peut plus detruire les stats d'un autre. Aucun repli sur l'ancien nom partage :
    servir les stats d'un AUTRE modele est exactement le bug qu'on ferme.
    """
    if not model_path:
        raise ValueError("get_vec_normalize_path: model_path vide")
    model_dir = os.path.dirname(model_path)
    stem = os.path.splitext(os.path.basename(model_path))[0]
    if not stem:
        raise ValueError(f"get_vec_normalize_path: model_path sans nom de fichier : {model_path!r}")
    return os.path.join(model_dir, f"{stem}{VEC_NORMALIZE_SUFFIX}")


def save_vec_normalize(env: Any, model_path: str) -> bool:
    """
    Save VecNormalize stats alongside model if env is wrapped with VecNormalize.

    Returns True if saved, False if env is not VecNormalize.
    """
    from stable_baselines3.common.vec_env import VecNormalize

    vec_env = env
    while vec_env is not None:
        if isinstance(vec_env, VecNormalize):
            save_path = get_vec_normalize_path(model_path)
            vec_env.save(save_path)
            return True
        if hasattr(vec_env, "venv"):
            vec_env = vec_env.venv
        else:
            break
    return False


def load_vec_normalize(venv: Any, model_path: str) -> Optional[Any]:
    """
    Load VecNormalize stats and wrap venv if vec_normalize.pkl exists.

    Returns VecNormalize-wrapped env, or original venv if no stats file.
    """
    from stable_baselines3.common.vec_env import VecNormalize

    save_path = get_vec_normalize_path(model_path)
    if not os.path.exists(save_path):
        return None

    vec_normalize = VecNormalize.load(save_path, venv)
    vec_normalize.training = False  # Don't update stats during eval
    vec_normalize.norm_reward = False  # Don't normalize rewards during eval
    return vec_normalize


def normalize_observation_for_inference(obs: np.ndarray, model_path: str) -> np.ndarray:
    """
    Normalize a single observation for inference (PvE, evaluation).

    Use when model was trained with VecNormalize but inference runs outside
    the training env (e.g. PvE controller with raw obs from engine).

    Returns normalized obs, or original if no vec_normalize.pkl found.
    """
    import pickle

    save_path = get_vec_normalize_path(model_path)
    if not os.path.exists(save_path):
        return obs

    with open(save_path, "rb") as f:
        vec_normalize = pickle.load(f)

    if not hasattr(vec_normalize, "obs_rms") or vec_normalize.obs_rms is None:
        return obs

    obs_arr = np.array(obs, dtype=np.float32)
    if obs_arr.ndim == 1:
        obs_arr = obs_arr.reshape(1, -1)

    mean = vec_normalize.obs_rms.mean
    var = vec_normalize.obs_rms.var
    epsilon = getattr(vec_normalize, "epsilon", 1e-8)
    clip_obs = getattr(vec_normalize, "clip_obs", 10.0)
    norm_obs = getattr(vec_normalize, "norm_obs", True)

    if not norm_obs:
        return obs_arr.squeeze()

    normalized = (obs_arr - mean) / np.sqrt(var + epsilon)
    normalized = np.clip(normalized, -clip_obs, clip_obs)
    return normalized.squeeze()
