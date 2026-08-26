"""Buffer rollout GPU-résident — Phase 2.1 du chantier perf_entrainement.

Deux deltas vs MaskableDictRolloutBuffer standard (sb3_contrib) :

1. action_masks allouées en bool (not float32) → ×4 bytes économisés en RAM.
   Converties float32 AU MOMENT de l'upload GPU (dans get()).

2. get() uploade l'intégralité des tenseurs sur GPU UNE SEULE FOIS (premier appel,
   premier epoch). Les appels suivants (epochs 2-5) réutilisent les GPU tensors sans
   aucun transfert H2D. _get_samples_gpu() indexe directement sur GPU.

Résultat : les ~4-5 Go de re-transferts H2D par epoch disparaissent.

Verlock parité bit-à-bit :
- bool→float32 : True→1.0, False→0.0 — identique aux 1.0/0.0 du buffer float32 original.
- Indexation GPU : th.as_tensor(bool_arr, dtype=th.float32)[idx] == to_torch(float32_arr)[idx].
"""
from __future__ import annotations

from typing import Generator

import numpy as np
import torch as th
from gymnasium import spaces
from stable_baselines3.common.type_aliases import TensorDict
from stable_baselines3.common.vec_env import VecNormalize

from sb3_contrib.common.maskable.buffers import (
    MaskableDictRolloutBuffer,
    MaskableDictRolloutBufferSamples,
)


class GpuMaskableDictRolloutBuffer(MaskableDictRolloutBuffer):
    """MaskableDictRolloutBuffer avec tenseurs résidents GPU pendant la phase d'update."""

    # Tenseurs GPU créés à la première itération de get() — None entre les rollouts.
    _gpu_obs: TensorDict | None
    _gpu_actions: th.Tensor | None
    _gpu_values: th.Tensor | None
    _gpu_log_probs: th.Tensor | None
    _gpu_advantages: th.Tensor | None
    _gpu_returns: th.Tensor | None
    _gpu_action_masks: th.Tensor | None

    def reset(self) -> None:
        super().reset()
        # super() alloue action_masks en float32 — on remplace par bool (×4 moins de RAM).
        self.action_masks = np.ones(
            (self.buffer_size, self.n_envs, self.mask_dims), dtype=bool
        )
        self._gpu_obs = None
        self._gpu_actions = None
        self._gpu_values = None
        self._gpu_log_probs = None
        self._gpu_advantages = None
        self._gpu_returns = None
        self._gpu_action_masks = None

    def get(
        self, batch_size: int | None = None
    ) -> Generator[MaskableDictRolloutBufferSamples, None, None]:
        assert self.full
        # Conversion GPU immédiate : évite n_batches conversions H→D dans _get_samples_gpu.
        indices = th.from_numpy(
            np.random.permutation(self.buffer_size * self.n_envs).astype(np.int64)
        ).to(device=self.device)

        if not self.generator_ready:
            # Reshape (identique au parent).
            for key, obs in self.observations.items():
                self.observations[key] = self.swap_and_flatten(obs)
            for tensor_name in ["actions", "values", "log_probs", "advantages", "returns"]:
                self.__dict__[tensor_name] = self.swap_and_flatten(self.__dict__[tensor_name])  # type: ignore[index]
            self.action_masks = self.swap_and_flatten(self.action_masks)

            # Upload GPU — une seule fois pour les n_epochs epochs.
            dev = self.device
            self._gpu_obs = {
                k: th.as_tensor(v, device=dev) for k, v in self.observations.items()
            }
            self._gpu_actions = th.as_tensor(self.actions, device=dev)
            self._gpu_values = th.as_tensor(self.values, device=dev)
            self._gpu_log_probs = th.as_tensor(self.log_probs, device=dev)
            self._gpu_advantages = th.as_tensor(self.advantages, device=dev)
            self._gpu_returns = th.as_tensor(self.returns, device=dev)
            # bool → float32 pour la policy (logits masquage additionnel).
            self._gpu_action_masks = th.as_tensor(
                self.action_masks, device=dev, dtype=th.float32
            )
            self.generator_ready = True

        if batch_size is None:
            batch_size = self.buffer_size * self.n_envs

        start_idx = 0
        while start_idx < self.buffer_size * self.n_envs:
            yield self._get_samples_gpu(indices[start_idx : start_idx + batch_size])
            start_idx += batch_size

    def _get_samples_gpu(
        self, batch_inds: th.Tensor
    ) -> MaskableDictRolloutBufferSamples:
        assert self._gpu_obs is not None, "get() doit être appelé avant _get_samples_gpu()"
        return MaskableDictRolloutBufferSamples(
            observations={k: v[batch_inds] for k, v in self._gpu_obs.items()},
            actions=self._gpu_actions[batch_inds],  # type: ignore[index]
            old_values=self._gpu_values[batch_inds].flatten(),  # type: ignore[index]
            old_log_prob=self._gpu_log_probs[batch_inds].flatten(),  # type: ignore[index]
            advantages=self._gpu_advantages[batch_inds].flatten(),  # type: ignore[index]
            returns=self._gpu_returns[batch_inds].flatten(),  # type: ignore[index]
            action_masks=self._gpu_action_masks[batch_inds].reshape(-1, self.mask_dims),  # type: ignore[index]
        )

    # _get_samples() du parent n'est plus appelé via get() — laissé intact pour
    # l'éventuel usage direct (explain_variance, tests) qui passe par numpy.
