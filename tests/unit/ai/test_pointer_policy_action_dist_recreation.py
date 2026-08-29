"""Vérifie que _distribution_from() recrée action_dist quand il est absent.

Contexte : patched_ppo.py (commit ca173e55) retire action_dist du __dict__ avant deepcopy
pour éviter des tenseurs non-leaf. Les workers Phase 3 reçoivent donc une policy sans
action_dist. Sans le fix de pointer_policy.py, _distribution_from() lève AttributeError.
"""

from __future__ import annotations

import numpy as np
import pytest
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.distributions import MaskableCategoricalDistribution

from ai.pointer_policy import PointerMaskablePolicy
from ai.spatial_extractor import SpatialCombinedExtractor
from tests.unit.ai.test_pointer_head import _ToyEnv, _zero_obs


@pytest.fixture
def policy(tmp_path) -> PointerMaskablePolicy:
    """Policy instanciée via MaskablePPO (chemin habituel du learner)."""
    import torch
    torch.manual_seed(42)
    model = MaskablePPO(
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
    assert isinstance(model.policy, PointerMaskablePolicy)
    return model.policy


def test_distribution_from_echoue_sans_action_dist(policy):
    """Sans le fix, AttributeError est levé quand action_dist est absent."""
    # Supprimer action_dist comme le fait patched_ppo.py avant deepcopy
    policy.__dict__.pop("action_dist", None)

    # Sans le fix, self.action_dist lèverait AttributeError
    # Avec le fix, hasattr(self, 'action_dist') est False → recréation
    import torch
    from engine.macro_intents import TOTAL_ACTION_SIZE
    obs_batch = _zero_obs(batch=1)
    obs_t = {k: torch.as_tensor(v) for k, v in obs_batch.items()}
    masks = np.ones(TOTAL_ACTION_SIZE, dtype=bool)

    # Doit réussir sans AttributeError
    feats = policy._split_features(obs_t)
    latent_pi, _ = policy.mlp_extractor(feats.trunk)
    dist = policy._distribution_from(latent_pi, feats, masks)

    # action_dist doit avoir été recréé sur l'objet
    assert hasattr(policy, "action_dist"), "action_dist doit être recréé après appel"
    assert isinstance(policy.action_dist, MaskableCategoricalDistribution)
    assert policy.action_dist.action_dim == TOTAL_ACTION_SIZE, (
        f"action_dim diverge : {policy.action_dist.action_dim} au lieu de {TOTAL_ACTION_SIZE}"
    )
    assert dist is not None
