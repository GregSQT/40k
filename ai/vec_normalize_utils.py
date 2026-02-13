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

VEC_NORMALIZE_FILENAME = "vec_normalize.pkl"


def get_vec_normalize_path(model_path: str) -> str:
    """Get path to vec_normalize.pkl for a model."""
    model_dir = os.path.dirname(model_path)
    return os.path.join(model_dir, VEC_NORMALIZE_FILENAME)


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
