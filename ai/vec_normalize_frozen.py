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
    """Retourne une copie PROFONDE de obs_dict avec global_cont normalisé par stats gelées.

    Seule clé normalisée : "global_cont" (comportement identique au VecNormalize de production
    configuré avec norm_obs_keys=["global_cont"]).

    COPIE PROFONDE OBLIGATOIRE : le moteur sert ses observations dans des buffers scratch
    RÉUTILISÉS entre steps (engine/observation_builder._empty_squad_observation : « ne jamais
    stocker le dict retourné au-delà du step courant »), et env.step() les mute AVANT que la
    trajectoire distribuée ne les stocke. Une copie superficielle remplissait le rollout
    buffer de n_steps répliques de l'état final (root cause du non-apprentissage Phase 3,
    run_20260829-132022) ; une copie au site de stockage capturait l'état POST-step.
    Les tableaux retournés appartiennent donc à l'appelant.
    """
    result = {k: v.copy() for k, v in obs_dict.items()}
    if not snapshot.norm_obs or "global_cont" not in obs_dict:
        return result

    # numpy upcast float32 → float64 implicitement lors de l'arithmétique avec obs_mean (float64)
    result["global_cont"] = np.clip(
        (obs_dict["global_cont"] - snapshot.obs_mean) / np.sqrt(snapshot.obs_var + snapshot.epsilon),
        -snapshot.clip_obs,
        snapshot.clip_obs,
    ).astype(np.float32)
    return result


def update_vec_normalize_from_trajectories(
    vec_env: Any,
    raw_global_cont_batches: list[np.ndarray],
    discounted_returns_batches: list[np.ndarray],
    final_returns_per_worker: list[float],
) -> None:
    """Met à jour les stats VecNormalize avec les données brutes collectées par les workers.

    Équivalent batch au passage step-by-step dans VecNormalize.step_wait() :
    - obs_rms["global_cont"] est mis à jour avec tous les obs bruts (N_envs × N_steps, 13)
    - ret_rms est mis à jour avec tous les discounted returns (N_envs × N_steps,)
    - VecNormalize.returns[i] est restauré avec l'état final du worker i

    Sémantique documentée : batch vs streaming. RunningMeanStd.update_from_moments() utilise
    l'algorithme parallèle de Welford, donc update(batch) ≠ N×update(step) numériquement mais
    converge vers la même valeur. C'est l'écart intentionnel documenté dans §3 de perf_entrainement.md.

    Ne retourne AUCUN facteur de re-scaling, et l'appelant ne doit pas en appliquer un aux
    sorties du critique. Un tel facteur (sqrt(old_ret_var)/sqrt(new_ret_var)) supposerait que
    V est proportionnel à 1/sqrt(ret_var), ce qui n'est vrai qu'à convergence : au premier
    rollout d'un run neuf, old_ret_var vaut 1.0 parce que RunningMeanStd vient d'être initialisé
    et non parce que le critique aurait appris à cette échelle, et le facteur mesuré (0.060 sur
    le run du 2026-08-29) écrasait ses prédictions de 17x. SB3 ne rescale jamais les values ;
    le chemin stepwise non plus.
    """
    vn = _unwrap_vec_normalize(vec_env)
    if vn is None:
        return

    if vn.training and vn.norm_obs:
        obs_rms = vn.obs_rms
        if isinstance(obs_rms, dict) and "global_cont" in obs_rms and raw_global_cont_batches:
            all_raw = np.concatenate(raw_global_cont_batches, axis=0)  # (total_steps, 13)
            obs_rms["global_cont"].update(all_raw)

    if vn.training and vn.norm_reward and discounted_returns_batches:
        all_rets = np.concatenate(discounted_returns_batches, axis=0)
        vn.ret_rms.update(all_rets.reshape(-1))

    if hasattr(vn, "returns") and vn.returns is not None:
        for i, fr in enumerate(final_returns_per_worker):
            if i < len(vn.returns):
                vn.returns[i] = fr
