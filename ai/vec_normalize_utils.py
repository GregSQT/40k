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
from ai.companion_paths import companion_path
from typing import Callable, Optional, Any

VEC_NORMALIZE_SUFFIX = "_vec_normalize.pkl"


def get_vec_normalize_path(model_path: str) -> str:
    """Chemin des stats VecNormalize d'UN modele : `<dir>/<nom_du_zip>_vec_normalize.pkl`.

    ⚠️ Ce chemin depend du NOM du modele, et ce n'est pas cosmetique (V11 §0.35).

    Il a longtemps valu `<dir>/vec_normalize.pkl` — un fichier UNIQUE partage par tous les
    modeles d'un meme dossier : le snapshot d'evaluation, les checkpoints, le meilleur modele
    robuste et le modele canonique ecrivaient et supprimaient tous LE MEME fichier. Or
    `BotEvaluationCallback` evalue en ASYNCHRONE : il sauve un snapshot (donc les stats), lance
    des workers qui chargent le pkl PARESSEUSEMENT au premier pas, puis consomme le resultat de
    l'evaluation PRECEDENTE — et cette consommation appelle `remove_model_with_companions`, qui
    supprimait les stats que les workers de l'evaluation EN COURS n'avaient pas encore lues.
    Resultat mesure : 600/600 episodes d'evaluation en erreur en 7 s au marqueur 24 000, et le
    garde-fou strict a arrete un run de 5 h 30.

    Un nom par modele rend la suppression correcte PAR CONSTRUCTION : retirer les artefacts d'un
    modele ne peut plus detruire les stats d'un autre. Aucun repli sur l'ancien nom partage :
    servir les stats d'un AUTRE modele est exactement le bug qu'on ferme.
    """
    return companion_path(model_path, VEC_NORMALIZE_SUFFIX)


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


class _NormalizedFrozenModel:
    """Modele fige + son propre VecNormalize — interface predict() identique a MaskablePPO.

    Intercept predict() pour appliquer la normalisation du snapshot (jamais celle du
    modele courant). Substitut drop-in dans BotControlledEnv._frozen_model.
    """

    def __init__(self, model: Any, normalizer: Optional[Callable[[Any], Any]]) -> None:
        self._model = model
        self._normalizer = normalizer

    def predict(self, obs: Any, **kwargs: Any) -> Any:
        if self._normalizer is not None:
            obs = self._normalizer(obs)
        return self._model.predict(obs, **kwargs)


def build_snapshot_normalizer(
    snapshot_path: str,
    vec_normalize_enabled: bool,
    vec_normalize_eval_enabled: bool,
) -> Optional[Callable[[Any], Any]]:
    """Construit un callable de normalisation pour un snapshot de self-play.

    Renvoie None si vec_normalize ou vec_normalize_eval est desactive.
    Erreur explicite si le .pkl est absent alors que la normalisation est activee (V11 §0.35).
    La closure charge le pkl une seule fois (lazy) et est independante par instance — aucun
    partage entre envs workers (chaque BotControlledEnv possede sa propre instance).
    """
    if not vec_normalize_enabled or not vec_normalize_eval_enabled:
        return None

    pkl_path = get_vec_normalize_path(snapshot_path)
    if not os.path.exists(pkl_path):
        raise FileNotFoundError(
            f"VecNormalize: stats absentes pour le snapshot de self-play : {pkl_path}. "
            "Le snapshot doit etre publie avec ses stats (V11 §0.35)."
        )

    _cache: dict = {"obj": None}

    def _normalize(obs: Any) -> Any:
        if _cache["obj"] is None:
            import pickle
            with open(pkl_path, "rb") as f:
                vn = pickle.load(f)
            vn.training = False
            vn.norm_reward = False
            _cache["obj"] = vn
        vn = _cache["obj"]
        if isinstance(obs, dict):
            return vn.normalize_obs(obs)
        obs_arr = np.asarray(obs, dtype=np.float32)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr.reshape(1, -1)
        normalized = vn.normalize_obs(obs_arr)
        return np.asarray(normalized, dtype=np.float32).squeeze()

    return _normalize


def normalize_observation_for_inference(obs: np.ndarray, model_path: str) -> np.ndarray:
    """
    Normalize a single observation for inference (PvE, evaluation).

    Use when model was trained with VecNormalize but inference runs outside
    the training env (e.g. PvE controller with raw obs from engine).

    N'appeler QUE si la normalisation est requise pour ce modele : un pkl absent ou sans stats
    est une ERREUR explicite, jamais un retour d'obs brute. Retourner l'obs brute en silence
    faisait jouer un modele normalise sur des obs brutes (decalage de distribution muet) —
    exactement la classe de bug fermee par V11 §0.35. Le seul retour brut legitime est
    `norm_obs=False` : des stats existent mais la normalisation d'obs a ete DESACTIVEE a
    l'entrainement (choix de config, pas une absence).
    """
    import pickle

    save_path = get_vec_normalize_path(model_path)
    if not os.path.exists(save_path):
        raise FileNotFoundError(
            f"VecNormalize: stats absentes pour le modele evalue : {save_path}. "
            f"Normaliser sans elles servirait des obs brutes a un modele entraine "
            f"normalise (V11 §0.35)."
        )

    with open(save_path, "rb") as f:
        vec_normalize = pickle.load(f)

    if not hasattr(vec_normalize, "obs_rms") or vec_normalize.obs_rms is None:
        raise ValueError(
            f"VecNormalize: {save_path} ne contient pas de stats d'observation (obs_rms) — "
            f"fichier corrompu ou d'une autre version."
        )

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
