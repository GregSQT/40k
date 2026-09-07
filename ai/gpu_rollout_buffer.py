"""Buffer rollout GPU-résident — Phase 2.1 du chantier perf_entrainement.

Deux deltas vs MaskableDictRolloutBuffer standard (sb3_contrib) :

1. action_masks allouées en bool (not float32) → ×4 bytes économisés en RAM.
   Converties float32 AU MOMENT de l'upload GPU (dans get()).

2. get() uploade UNE SEULE FOIS (premier appel, premier epoch) les champs COMPACTS —
   actions, values, log_probs, advantages, returns, action_masks. Les appels suivants
   (epochs 2-n) les réutilisent sans aucun transfert H2D. _get_samples_gpu() les indexe
   directement sur GPU.

LES OBSERVATIONS SONT EXCLUES DE CET UPLOAD, et c'est le point le plus contre-intuitif du
module : elles restent en RAM, et seul le minibatch part sur le device, à chaque minibatch de
chaque epoch. Elles portent pourtant l'essentiel du volume, donc c'est bien l'optimisation
d'origine qu'on annule là où elle payait le plus. RAISON, mesurée le 2026-09-07 sur l'étape P2
du curriculum : le profil de lignée `x1_lineage` porte n_steps 32640 (contre 8160 pour
`x1_long`) et une observation vaut 26 007 flottants (16 791 squad + 9x32x32 de grille), soit
104 Ko. Le bloc d'observations pèse donc 3,16 GiB — et il était résident DEUX fois, en RAM
numpy ET sur le GPU, `self.observations` n'étant jamais libéré après l'upload. Sur la RTX 4060
Laptop de la machine de référence (8 188 MiB, dont ~1 050 déjà pris au repos par l'hôte), ces
3,16 GiB à eux seuls prennent près de la moitié de ce qui reste, avant le modèle, l'optimiseur
et les activations. Sous WSL2 le débordement de VRAM ne lève pas d'OOM CUDA : le driver bascule
en mémoire système, la VM gonfle, swappe, et Windows la tue — ce qui est arrivé au run P2 du
2026-09-07 avant son premier update.

CE QUE ÇA COÛTE, et c'est assumé : les observations traversent le bus n_epochs fois par update
au lieu d'une seule. C'est le régime de SB3 standard, celui qui tournait avant la Phase 2.1.
Les champs compacts, eux, restent GPU-résidents parce qu'ils ne sont pas le problème : à 32 640
transitions les masques pèsent 181 Mo en float32 et tous les autres champs réunis restent sous
le mégaoctet — 18 fois moins que les observations, pour le même nombre de transferts évités.

Verlock parité bit-à-bit :
- bool→float32 : True→1.0, False→0.0 — identique aux 1.0/0.0 du buffer float32 original.
- Indexation : la même permutation numpy sert aux deux familles — observations indexées côté
  numpy, champs compacts convertis en tensor GPU par minibatch dans `_get_samples_gpu`.
"""
from __future__ import annotations

from typing import Generator

import numpy as np
import torch as th
from gymnasium import spaces
from stable_baselines3.common.vec_env import VecNormalize

from sb3_contrib.common.maskable.buffers import (
    MaskableDictRolloutBuffer,
    MaskableDictRolloutBufferSamples,
)


class GpuMaskableDictRolloutBuffer(MaskableDictRolloutBuffer):
    """MaskableDictRolloutBuffer dont les champs COMPACTS résident sur GPU pendant l'update.

    Les observations n'en font pas partie : cf. le docstring du module.
    """

    # Tenseurs GPU créés à la première itération de get() — None entre les rollouts.
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
        # UNE permutation numpy partagée : observations indexées côté numpy, champs compacts
        # convertis en tensor GPU par minibatch. Deux tirages indépendants apparieraient des
        # observations avec les avantages d'autres transitions — un mélange indétectable.
        indices = np.random.permutation(self.buffer_size * self.n_envs).astype(np.int64, copy=False)

        if not self.generator_ready:
            # Reshape (identique au parent).
            for key, obs in self.observations.items():
                self.observations[key] = self.swap_and_flatten(obs)
            for tensor_name in ["actions", "values", "log_probs", "advantages", "returns"]:
                self.__dict__[tensor_name] = self.swap_and_flatten(self.__dict__[tensor_name])  # type: ignore[index]
            self.action_masks = self.swap_and_flatten(self.action_masks)

            # Upload GPU des champs compacts — une seule fois pour les n_epochs epochs.
            dev = self.device
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
            batch = slice(start_idx, start_idx + batch_size)
            yield self._get_samples_gpu(indices[batch])
            start_idx += batch_size

    def _get_samples_gpu(
        self, batch_inds: np.ndarray
    ) -> MaskableDictRolloutBufferSamples:
        assert self._gpu_actions is not None, "get() doit être appelé avant _get_samples_gpu()"
        dev = self.device
        # Indexation numpy PUIS transfert : `v[batch_inds]` rend déjà un bloc contigu de la
        # taille du minibatch, donc seul ce bloc traverse le bus.
        batch_inds_gpu = th.as_tensor(batch_inds, device=dev)
        return MaskableDictRolloutBufferSamples(
            observations={
                k: th.as_tensor(v[batch_inds], device=dev)
                for k, v in self.observations.items()
            },
            actions=self._gpu_actions[batch_inds_gpu],
            old_values=self._gpu_values[batch_inds_gpu].flatten(),  # type: ignore[index]
            old_log_prob=self._gpu_log_probs[batch_inds_gpu].flatten(),  # type: ignore[index]
            advantages=self._gpu_advantages[batch_inds_gpu].flatten(),  # type: ignore[index]
            returns=self._gpu_returns[batch_inds_gpu].flatten(),  # type: ignore[index]
            action_masks=self._gpu_action_masks[batch_inds_gpu].reshape(-1, self.mask_dims),  # type: ignore[index]
        )

    # _get_samples() du parent n'est plus appelé via get() — laissé intact pour
    # l'éventuel usage direct (explain_variance, tests) qui passe par numpy.
