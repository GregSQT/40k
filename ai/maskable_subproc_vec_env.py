"""MaskableSubprocVecEnv — Phase 2.3 du chantier perf_entrainement.

Variante de SubprocVecEnv qui inclut action_masks dans le dict info retourné par step().
Le masque est résolu dans le worker (process fils) SANS aller-retour supplémentaire :
il est déjà mis en cache dans _served_decision à la fin du step. Le learner lit
infos[i]["action_masks"] au lieu d'émettre un second env_method("action_masks") RPC.

Gain : ~340/341 RPCs économisés par rollout (seul le premier step appelle encore
get_action_masks() pour le bootstrap — géré dans PatchedMaskablePPO.collect_rollouts).
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


def _maskable_worker(
    remote: _MpConnection,
    parent_remote: _MpConnection,
    env_fn_wrapper: CloudpickleWrapper,
) -> None:
    """Worker identique à SubprocVecEnv._worker, sauf que step() inclut action_masks dans info.

    Le masque est le même que celui que MaskablePPO récupérerait via env_method("action_masks")
    juste après le step — bit-à-bit identique, zéro coût supplémentaire (cache _served_decision).
    """
    from stable_baselines3.common.env_util import is_wrapped

    parent_remote.close()
    env = _patch_env(env_fn_wrapper.var())
    reset_info: dict[str, Any] | None = {}

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
                # Masque du prochain état — déjà en cache, coût nul.
                try:
                    info["action_masks"] = env.get_wrapper_attr("action_masks")()
                except AttributeError:
                    pass  # env non maskable : pas de masque inline
                remote.send((observation, reward, done, info, reset_info))

            elif cmd == "reset":
                maybe_options = {"options": data[1]} if data[1] else {}
                observation, reset_info = env.reset(seed=data[0], **maybe_options)
                remote.send((observation, reset_info))

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
    """SubprocVecEnv dont le worker inclut action_masks dans les infos de step().

    Drop-in replacement de SubprocVecEnv pour le pipeline PPO maskable. Compatible avec
    VecNormalize et les autres wrappers SB3.
    """

    def __init__(
        self,
        env_fns: list[Callable[[], gym.Env]],
        start_method: str | None = None,
    ) -> None:
        # Réplique de SubprocVecEnv.__init__ avec target=_maskable_worker.
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
