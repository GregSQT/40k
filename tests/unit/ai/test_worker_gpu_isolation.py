"""Un worker d'environnement ne doit réserver aucune VRAM.

Son forward de policy gelée et son adversaire (`snapshot_device: cpu`) sont tout CPU :
un contexte CUDA ouvert dans ces process ne sert à rien et prend la mémoire dont le
learner a besoin pour son buffer d'update.
"""
from __future__ import annotations

import os
from typing import Any, Tuple

import gymnasium as gym
import numpy as np

from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv


class _GpuProbeEnv(gym.Env):
    """Env minimal qui rapporte l'exposition GPU vue depuis SON process."""

    def __init__(self) -> None:
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(1,), dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(2)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        return np.zeros(1, dtype=np.float32), {}

    def step(self, action: Any):
        return np.zeros(1, dtype=np.float32), 0.0, False, False, {}

    def gpu_exposure(self) -> Tuple[str | None, bool]:
        import torch

        return os.environ.get("CUDA_VISIBLE_DEVICES"), bool(torch.cuda.is_available())


def test_env_worker_voit_aucun_gpu(monkeypatch) -> None:
    # Le parent expose explicitement un GPU : sans neutralisation le worker en hérite.
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    vec_env = MaskableSubprocVecEnv([lambda: _GpuProbeEnv() for _ in range(2)])
    try:
        exposures = vec_env.env_method("gpu_exposure")
    finally:
        vec_env.close()

    assert len(exposures) == 2
    for visible_devices, cuda_available in exposures:
        assert visible_devices == "", (
            "un worker d'environnement expose encore un GPU "
            f"(CUDA_VISIBLE_DEVICES={visible_devices!r})"
        )
        assert cuda_available is False


def test_blob_policy_envoye_aux_workers_ne_porte_pas_optimizer() -> None:
    """L'état Adam ne doit jamais voyager : `.cpu()` ne le déplace pas, il resterait sur cuda:0.

    Sans ce retrait, chaque worker ouvre un contexte CUDA en désérialisant le blob — et sous
    `CUDA_VISIBLE_DEVICES=""` la désérialisation lève au lieu de gaspiller.
    """
    import cloudpickle
    import torch

    from ai.patched_ppo import PatchedMaskablePPO
    from ai.pointer_policy import PointerMaskablePolicy
    from ai.spatial_extractor import SpatialCombinedExtractor
    from tests.unit.ai.test_pointer_head import _ToyEnv

    torch.manual_seed(42)
    model = PatchedMaskablePPO(
        PointerMaskablePolicy,
        _ToyEnv(),
        n_steps=16,
        batch_size=8,
        device="cpu",
        verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
    )

    # Matérialise l'état d'Adam : c'est lui qui porte les tenseurs restés sur le device d'origine.
    loss = sum(param.sum() for param in model.policy.parameters())
    loss.backward()
    model.policy.optimizer.step()
    assert model.policy.optimizer.state, "état Adam vide : le test ne prouverait rien"

    restored = cloudpickle.loads(model._serialize_policy_for_workers())

    assert not hasattr(restored, "optimizer"), (
        "le blob envoyé aux workers porte encore l'optimizer, donc son état Adam"
    )
    # Le learner, lui, garde le sien : le retrait est temporaire, pas destructif.
    assert model.policy.optimizer.state
