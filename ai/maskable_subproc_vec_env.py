"""MaskableSubprocVecEnv — Phases 2.3 et 3 du chantier perf_entrainement.

Phase 2.3 : le worker inclut action_masks dans le dict info retourné par step().
  Le masque est résolu dans le worker (process fils) SANS aller-retour supplémentaire :
  il est déjà mis en cache dans _served_decision à la fin du step. Le learner lit
  infos[i]["action_masks"] au lieu d'émettre un second env_method("action_masks") RPC.
  Gain : ~340/341 RPCs économisés par rollout.

Phase 3 : message COLLECT_TRAJECTORY.
  Le learner sérialise la policy CPU + snapshot VecNormalize et envoie COLLECT_TRAJECTORY
  à chaque worker. Chaque worker déroule ses n_steps steps en autonome avec les poids gelés,
  retourne sa trajectoire complète. Le learner n'attend plus à chaque step — le lockstep
  (~73 % du budget de cycle) disparaît.

Sémantique garantie identique à SB3 :
- VecNormalize gelé pendant le cycle, mis à jour en batch au learner (écart documenté §3).
- Épisodes à cheval sur la frontière : tronqués à n_steps + bootstrap TimeLimit.truncated.
- Compteurs par-env (§0.57 rampe déploiement, opponent_mix) : déjà locaux aux workers.
"""
from __future__ import annotations

import multiprocessing as mp
from multiprocessing.connection import Connection as _MpConnection
from typing import Any, Callable

import gymnasium as gym
import numpy as np

from stable_baselines3.common.vec_env import VecEnv
from stable_baselines3.common.vec_env.base_vec_env import CloudpickleWrapper
from stable_baselines3.common.vec_env.patch_gym import _patch_env
from stable_baselines3.common.vec_env.subproc_vec_env import SubprocVecEnv


def _run_worker_trajectory(
    env: Any,
    last_raw_obs: dict,
    policy_bytes: bytes,
    n_steps: int,
    snapshot: Any,
    initial_episode_start: bool,
) -> dict:
    """Collecte n_steps steps dans le worker avec policy gelée.

    Réplique exacte de collect_rollouts pour UN env, avec policy CPU et stats VecNorm gelées.
    """
    import cloudpickle
    import torch
    from ai.vec_normalize_frozen import normalize_obs_with_snapshot

    frozen_policy = cloudpickle.loads(policy_bytes)
    frozen_policy.set_training_mode(False)

    import time as _time

    # Stockage de la trajectoire
    norm_obs_lists: dict[str, list] = {}   # accumulateur → converti en dict-of-arrays en fin
    raw_gc_seq: list[np.ndarray] = []     # seul global_cont est utilisé pour VecNormalize
    actions_seq: list[int] = []
    rewards_seq: list[float] = []      # reward normalisée (avec bootstrap)
    dones_seq: list[bool] = []
    episode_starts_seq: list[bool] = []
    values_seq: list[float] = []
    log_probs_seq: list[float] = []
    masks_seq: list[np.ndarray] = []
    infos_seq: list[dict] = []
    discounted_returns_seq: list[float] = []
    # Durée réelle de l'épisode terminé à ce step (>0), 0.0 si l'épisode continue,
    # ou -1.0 si l'épisode a commencé dans un rollout précédent (cross-trajectoire non chronométré).
    episode_wall_seconds_seq: list[float] = []

    current_raw_obs = last_raw_obs
    current_episode_start = initial_episode_start
    discounted_return = snapshot.initial_return
    # Si l'épisode était déjà en cours (initial_episode_start=False), le premier done de
    # ce rollout est cross-trajectoire : le timer ne couvre que la fraction dans ce rollout.
    # On marque ce cas avec _episode_cross_traj=True pour émettre -1.0 (sentinel).
    _episode_cross_traj = not initial_episode_start
    _episode_wall_start = _time.perf_counter()

    for _step in range(n_steps):
        norm_obs = normalize_obs_with_snapshot(current_raw_obs, snapshot)

        # Masque d'action
        mask = env.get_wrapper_attr("action_masks")()

        # Forward policy (CPU, pas de grad)
        with torch.no_grad():
            obs_t = {
                k: torch.as_tensor(v[np.newaxis], dtype=torch.float32)
                for k, v in norm_obs.items()
            }
            mask_t = torch.as_tensor(mask[np.newaxis], dtype=torch.float32)
            actions_t, values_t, log_probs_t = frozen_policy(obs_t, action_masks=mask_t)

        action = int(actions_t.cpu().numpy().flat[0])
        value = float(values_t.cpu().numpy().flat[0])
        log_prob = float(log_probs_t.cpu().numpy().flat[0])

        # Step env
        observation_raw, raw_reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        info["TimeLimit.truncated"] = truncated and not terminated
        raw_reward = float(raw_reward)

        if done:
            info["terminal_observation"] = observation_raw

        # Tracking VecNormalize.returns avec raw_reward (avant normalisation).
        discounted_return = snapshot.gamma * discounted_return + raw_reward
        discounted_returns_seq.append(discounted_return)
        if done:
            discounted_return = 0.0

        # Normalisation récompense — avant le bootstrap (sémantique SB3 exacte :
        # VecNormalize normalise dans step_wait, puis collect_rollouts ajoute le bootstrap).
        if snapshot.norm_reward:
            norm_reward = float(np.clip(
                raw_reward / np.sqrt(snapshot.ret_var + snapshot.epsilon),
                -snapshot.clip_reward,
                snapshot.clip_reward,
            ))
        else:
            norm_reward = raw_reward

        # Bootstrap TimeLimit.truncated — APRÈS normalisation, valeur brute ajoutée (SB3 §exact).
        if done:
            # Capturer le timestamp AVANT env.reset() pour exclure le coût de reset
            # (teardown + init de l'épisode suivant) de la durée de l'épisode courant.
            _episode_done_time = _time.perf_counter()
            if truncated and not terminated:
                norm_term = normalize_obs_with_snapshot(observation_raw, snapshot)
                with torch.no_grad():
                    obs_term = {
                        k: torch.as_tensor(v[np.newaxis], dtype=torch.float32)
                        for k, v in norm_term.items()
                    }
                    terminal_value = float(
                        frozen_policy.predict_values(obs_term).cpu().numpy().flat[0]
                    )
                norm_reward += snapshot.gamma * terminal_value
            observation_raw, _ = env.reset()

        # Inclure action_masks dans info (parité Phase 2.3)
        info["action_masks"] = mask

        for k, v in norm_obs.items():
            if k not in norm_obs_lists:
                norm_obs_lists[k] = []
            norm_obs_lists[k].append(v)
        gc = current_raw_obs.get("global_cont", np.zeros(snapshot.obs_mean.shape, dtype=np.float32))
        raw_gc_seq.append(gc.copy())
        actions_seq.append(action)
        rewards_seq.append(norm_reward)
        dones_seq.append(done)
        episode_starts_seq.append(current_episode_start)
        values_seq.append(value)
        log_probs_seq.append(log_prob)
        masks_seq.append(mask.copy())
        infos_seq.append(info)

        if done:
            if _episode_cross_traj:
                # Premier done d'un épisode commencé dans le rollout précédent :
                # la durée ne couvre qu'une fraction de l'épisode réel → sentinel -1.0.
                episode_wall_seconds_seq.append(-1.0)
            else:
                episode_wall_seconds_seq.append(_episode_done_time - _episode_wall_start)
            _episode_wall_start = _time.perf_counter()
            _episode_cross_traj = False
        else:
            episode_wall_seconds_seq.append(0.0)

        current_raw_obs = observation_raw
        current_episode_start = done

    # Dernière obs : raw (pour le prochain COLLECT_TRAJECTORY) et normalisée (pour le learner).
    last_raw_obs = {k: v.copy() for k, v in current_raw_obs.items()}
    norm_last = normalize_obs_with_snapshot(current_raw_obs, snapshot)
    with torch.no_grad():
        obs_last = {
            k: torch.as_tensor(v[np.newaxis], dtype=torch.float32)
            for k, v in norm_last.items()
        }
        last_value = float(frozen_policy.predict_values(obs_last).cpu().numpy().flat[0])

    # norm_obs_seq : dict-of-arrays (n_steps, ...) par clé — évite n_steps × n_keys np.stack côté learner.
    norm_obs_seq = {k: np.stack(v) for k, v in norm_obs_lists.items()}
    # raw_global_cont : seul global_cont brut, shape (n_steps, 13), pour mise à jour VecNormalize obs_rms.
    raw_global_cont = np.array(raw_gc_seq, dtype=np.float64)

    return {
        "norm_obs_seq": norm_obs_seq,
        "actions_seq": np.array(actions_seq, dtype=np.int64),
        "rewards_seq": np.array(rewards_seq, dtype=np.float32),
        "dones_seq": np.array(dones_seq, dtype=bool),
        "episode_starts_seq": np.array(episode_starts_seq, dtype=bool),
        "values_seq": np.array(values_seq, dtype=np.float32),
        "log_probs_seq": np.array(log_probs_seq, dtype=np.float32),
        "masks_seq": np.array(masks_seq, dtype=bool),
        "infos_seq": infos_seq,
        "last_raw_obs": last_raw_obs,   # obs BRUTES pour le prochain COLLECT_TRAJECTORY
        "last_norm_obs": norm_last,      # obs normalisées pour le learner (GAE)
        "last_done": bool(dones_seq[-1]) if dones_seq else False,
        "last_value": last_value,
        "raw_global_cont": raw_global_cont,
        "discounted_returns": np.array(discounted_returns_seq, dtype=np.float64),
        "final_discounted_return": discounted_return,
        "episode_wall_seconds_seq": np.array(episode_wall_seconds_seq, dtype=np.float64),
    }


def _maskable_worker(
    remote: _MpConnection,
    parent_remote: _MpConnection,
    env_fn_wrapper: CloudpickleWrapper,
) -> None:
    """Worker pour MaskableSubprocVecEnv.

    Étend le worker SB3 standard avec :
    - action_masks dans info (Phase 2.3) : zéro coût, masque déjà en cache.
    - COLLECT_TRAJECTORY (Phase 3) : collecte autonome avec policy gelée.
    - _worker_last_obs : état interne pour COLLECT_TRAJECTORY.
    """
    from stable_baselines3.common.env_util import is_wrapped

    parent_remote.close()
    env = _patch_env(env_fn_wrapper.var())
    reset_info: dict[str, Any] | None = {}
    _worker_last_obs: dict | None = None  # état courant pour COLLECT_TRAJECTORY

    while True:
        try:
            cmd, data = remote.recv()
            if cmd == "step":
                observation, reward, terminated, truncated, info = env.step(data)
                done = terminated or truncated
                info["TimeLimit.truncated"] = truncated and not terminated
                if done:
                    info["terminal_observation"] = observation
                    observation, reset_info = env.reset()
                info["action_masks"] = env.get_wrapper_attr("action_masks")()
                _worker_last_obs = observation
                remote.send((observation, reward, done, info, reset_info))

            elif cmd == "reset":
                maybe_options = {"options": data[1]} if data[1] else {}
                observation, reset_info = env.reset(seed=data[0], **maybe_options)
                _worker_last_obs = observation
                remote.send((observation, reset_info))

            elif cmd == "COLLECT_TRAJECTORY":
                policy_bytes, n_steps, snapshot, initial_episode_start = data
                if _worker_last_obs is None:
                    remote.send(RuntimeError(
                        "COLLECT_TRAJECTORY appelé avant le premier step/reset — "
                        "appeler reset() sur le VecEnv avant la première collecte."
                    ))
                    continue
                traj = _run_worker_trajectory(
                    env, _worker_last_obs, policy_bytes, n_steps, snapshot,
                    initial_episode_start,
                )
                # Stocker les obs BRUTES pour le prochain COLLECT_TRAJECTORY.
                # Jamais les obs normalisées : elles seraient re-normalisées au prochain cycle.
                _worker_last_obs = traj["last_raw_obs"]
                remote.send(traj)

            elif cmd == "render":
                remote.send(env.render())

            elif cmd == "close":
                env.close()
                remote.close()
                break

            elif cmd == "get_spaces":
                remote.send((env.observation_space, env.action_space))

            elif cmd == "env_method":
                method = env.get_wrapper_attr(data[0])
                remote.send(method(*data[1], **data[2]))

            elif cmd == "get_attr":
                remote.send(env.get_wrapper_attr(data))

            elif cmd == "has_attr":
                try:
                    env.get_wrapper_attr(data)
                    remote.send(True)
                except AttributeError:
                    remote.send(False)

            elif cmd == "set_attr":
                remote.send(setattr(env, data[0], data[1]))  # type: ignore[func-returns-value]

            elif cmd == "is_wrapped":
                remote.send(is_wrapped(env, data))

            else:
                raise NotImplementedError(f"`{cmd}` is not implemented in the worker")

        except EOFError:
            break
        except KeyboardInterrupt:
            break


class MaskableSubprocVecEnv(SubprocVecEnv):
    """SubprocVecEnv dont le worker inclut action_masks dans les infos de step() (Phase 2.3).

    Phase 3 : ajoute collect_trajectories() pour la collecte distribuée sans lockstep.
    Drop-in replacement de SubprocVecEnv pour le pipeline PPO maskable. Compatible avec
    VecNormalize et les autres wrappers SB3.
    """

    def __init__(
        self,
        env_fns: list[Callable[[], gym.Env]],
        start_method: str | None = None,
    ) -> None:
        self.waiting = False
        self.closed = False
        n_envs = len(env_fns)

        if start_method is None:
            forkserver_available = "forkserver" in mp.get_all_start_methods()
            start_method = "forkserver" if forkserver_available else "spawn"
        ctx = mp.get_context(start_method)

        self.remotes, self.work_remotes = zip(
            *[ctx.Pipe() for _ in range(n_envs)], strict=True
        )
        self.processes = []
        for work_remote, remote, env_fn in zip(
            self.work_remotes, self.remotes, env_fns, strict=True
        ):
            args = (work_remote, remote, CloudpickleWrapper(env_fn))
            process = ctx.Process(target=_maskable_worker, args=args, daemon=True)  # type: ignore[attr-defined]
            process.start()
            self.processes.append(process)
            work_remote.close()

        self.remotes[0].send(("get_spaces", None))
        observation_space, action_space = self.remotes[0].recv()

        VecEnv.__init__(self, len(env_fns), observation_space, action_space)

    def collect_trajectories(
        self,
        policy_bytes: bytes,
        n_steps: int,
        snapshots: list[Any],
        initial_episode_starts: np.ndarray,
    ) -> list[dict]:
        """Envoie COLLECT_TRAJECTORY à tous les workers et récupère les trajectoires.

        Chaque worker tourne indépendamment ses n_steps steps avec la policy gelée.
        Retourne une liste de trajectoires (une par worker), dans l'ordre des workers.
        """
        if self.waiting:
            raise RuntimeError(
                "collect_trajectories() appelé alors que le VecEnv attend des résultats step."
            )
        assert len(snapshots) == len(self.remotes), (
            f"Nombre de snapshots ({len(snapshots)}) ≠ nombre de workers ({len(self.remotes)})"
        )

        for i, remote in enumerate(self.remotes):
            remote.send(("COLLECT_TRAJECTORY", (
                policy_bytes,
                n_steps,
                snapshots[i],
                bool(initial_episode_starts[i]),
            )))

        trajectories = []
        for remote in self.remotes:
            result = remote.recv()
            if isinstance(result, Exception):
                raise result
            trajectories.append(result)

        return trajectories
