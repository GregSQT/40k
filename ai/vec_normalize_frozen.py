"""Snapshot/restore VecNormalize stats pour la collecte distribuée (Phase 3 perf_entrainement).

Seul vrai écart sémantique de l'Option A : VecNormalize met normalement à jour ses stats
à chaque step de collecte. Avec la collecte distribuée, les stats sont GELÉES pendant le
cycle de collecte et mises à jour en batch au learner après retour des trajectoires.

Impact attesté négligeable sur global_cont (13 floats). Verrou : test_vec_normalize_stats_drift
(tests/unit/ai/test_phase3_distributed_rollout.py) mesure et documente la divergence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class VecNormalizeSnapshot:
    """État gelé d'un VecNormalize pour UN worker, valide pendant un cycle de collecte."""

    # obs_rms["global_cont"] — RunningMeanStd fields (seuls utilisés pour normaliser)
    obs_mean: np.ndarray   # (13,) float64
    obs_var: np.ndarray    # (13,) float64
    # ret_rms — seul ret_var est utilisé pour normaliser la récompense
    ret_var: float         # scalar float64
    # VecNormalize params
    gamma: float
    epsilon: float
    clip_obs: float
    clip_reward: float
    norm_obs: bool
    norm_reward: bool
    # État par-env : discounted return au début du cycle pour ce worker
    initial_return: float


def _unwrap_vec_normalize(vec_env: Any) -> "Any | None":
    """Remonte la chaîne de wrappers et retourne le VecNormalize, ou None."""
    from stable_baselines3.common.vec_env import VecNormalize

    vn = vec_env
    while not isinstance(vn, VecNormalize) and hasattr(vn, "venv"):
        vn = vn.venv
    return vn if isinstance(vn, VecNormalize) else None


def snapshot_vec_normalize(vec_env: Any, worker_idx: int) -> "VecNormalizeSnapshot":
    """Capture les stats gelées du VecNormalize pour le worker `worker_idx`.

    Remonte la chaîne de wrappers pour trouver le VecNormalize.
    Si aucun VecNormalize n'est trouvé, retourne un snapshot no-op (pas de normalisation).
    """
    vn = _unwrap_vec_normalize(vec_env)
    if vn is None:
        # Pas de VecNormalize — snapshot no-op
        return VecNormalizeSnapshot(
            obs_mean=np.zeros(1, dtype=np.float64),
            obs_var=np.ones(1, dtype=np.float64),
            ret_var=1.0,
            gamma=0.99,
            epsilon=1e-8,
            clip_obs=10.0,
            clip_reward=10.0,
            norm_obs=False,
            norm_reward=False,
            initial_return=0.0,
        )

    # obs_rms n'existe que si norm_obs=True (SB3 ne crée pas l'attribut sinon).
    if vn.norm_obs and hasattr(vn, "obs_rms"):
        obs_rms = vn.obs_rms
        rms = obs_rms["global_cont"] if isinstance(obs_rms, dict) else obs_rms
        snap_obs_mean = rms.mean.copy()
        snap_obs_var = rms.var.copy()
    else:
        snap_obs_mean = np.zeros(1, dtype=np.float64)
        snap_obs_var = np.ones(1, dtype=np.float64)
    # ret_rms n'existe que si norm_reward=True.
    snap_ret_var = float(vn.ret_rms.var) if vn.norm_reward and hasattr(vn, "ret_rms") else 1.0

    initial_return = 0.0
    if hasattr(vn, "returns") and vn.returns is not None and worker_idx < len(vn.returns):
        initial_return = float(vn.returns[worker_idx])

    return VecNormalizeSnapshot(
        obs_mean=snap_obs_mean,
        obs_var=snap_obs_var,
        ret_var=snap_ret_var,
        gamma=float(vn.gamma),
        epsilon=float(vn.epsilon),
        clip_obs=float(vn.clip_obs),
        clip_reward=float(vn.clip_reward),
        norm_obs=bool(vn.norm_obs),
        norm_reward=bool(vn.norm_reward),
        initial_return=initial_return,
    )


def normalize_obs_with_snapshot(obs_dict: dict, snapshot: "VecNormalizeSnapshot") -> dict:
    """Retourne une copie de obs_dict avec global_cont normalisé par stats gelées.

    Seule clé normalisée : "global_cont" (comportement identique au VecNormalize de production
    configuré avec norm_obs_keys=["global_cont"]).
    """
    if not snapshot.norm_obs or "global_cont" not in obs_dict:
        return dict(obs_dict)

    result = dict(obs_dict)
    # numpy upcast float32 → float64 implicitement lors de l'arithmétique avec obs_mean (float64)
    normalized = np.clip(
        (obs_dict["global_cont"] - snapshot.obs_mean) / np.sqrt(snapshot.obs_var + snapshot.epsilon),
        -snapshot.clip_obs,
        snapshot.clip_obs,
    ).astype(np.float32)
    result["global_cont"] = normalized
    return result


def update_vec_normalize_from_trajectories(
    vec_env: Any,
    raw_global_cont_batches: list[np.ndarray],
    discounted_returns_batches: list[np.ndarray],
    final_returns_per_worker: list[float],
) -> "float | None":
    """Met à jour les stats VecNormalize avec les données brutes collectées par les workers.

    Équivalent batch au passage step-by-step dans VecNormalize.step_wait() :
    - obs_rms["global_cont"] est mis à jour avec tous les obs bruts (N_envs × N_steps, 13)
    - ret_rms est mis à jour avec tous les discounted returns (N_envs × N_steps,)
    - VecNormalize.returns[i] est restauré avec l'état final du worker i

    Sémantique documentée : batch vs streaming. RunningMeanStd.update_from_moments() utilise
    l'algorithme parallèle de Welford, donc update(batch) ≠ N×update(step) numériquement mais
    converge vers la même valeur. C'est l'écart intentionnel documenté dans §3 de perf_entrainement.md.

    Retourne le facteur de re-scaling sqrt(old_ret_var+ε)/sqrt(new_ret_var+ε) si ret_rms.var a
    changé et que norm_reward est actif, None sinon. Le buffer appelant doit multiplier rewards,
    values et last_values par ce facteur avant de recalculer les avantages GAE.
    """
    vn = _unwrap_vec_normalize(vec_env)
    if vn is None:
        return None

    if vn.training and vn.norm_obs:
        obs_rms = vn.obs_rms
        if isinstance(obs_rms, dict) and "global_cont" in obs_rms and raw_global_cont_batches:
            all_raw = np.concatenate(raw_global_cont_batches, axis=0)  # (total_steps, 13)
            obs_rms["global_cont"].update(all_raw)

    scale: float | None = None
    if vn.training and vn.norm_reward and discounted_returns_batches:
        old_ret_var = float(vn.ret_rms.var)
        old_count = float(vn.ret_rms.count)
        eps = float(vn.epsilon)
        all_rets = np.concatenate(discounted_returns_batches, axis=0)
        vn.ret_rms.update(all_rets.reshape(-1))
        new_ret_var = float(vn.ret_rms.var)
        # Cold-start : count ≈ 1e-4 (valeur initiale SB3 RunningMeanStd).
        # old_ret_var=1.0 est l'initialisation, pas l'échelle apprise du critique ;
        # appliquer sqrt(1)/sqrt(new_var) aux values les écraserait de >10×.
        if old_count > 1.0 and abs(new_ret_var - old_ret_var) > 1e-6:
            scale = float(np.sqrt(old_ret_var + eps) / np.sqrt(new_ret_var + eps))

    if hasattr(vn, "returns") and vn.returns is not None:
        for i, fr in enumerate(final_returns_per_worker):
            if i < len(vn.returns):
                vn.returns[i] = fr

    return scale
