"""T-E — correction de la TÊTE POINTEUR sous MaskablePPO (cas jouet, avant tout run).

`V11_entity_encoder_pointer.md` §5.1 : « Tête pointeur : `log_prob`/entropie/masquage incorrects
sous MaskablePPO — **échoue silencieusement** (le training tourne, il apprend mal) ⇒ tests de
correction contre une tête dense de référence, sur cas jouet, AVANT tout run long. »

C'est exactement ce que fait ce fichier. La référence n'est pas « le même code appelé deux
fois » : les logits attendus sont recalculés à la main (`base` pour les actions non-tir,
`q · e_i / sqrt(d)` pour les slots), et une **couche dense équivalente** est construite —
`W_dense = E · W_q / sqrt(d)` — pour vérifier que le pointeur produit bien ce qu'une tête dense
produirait sur les mêmes embeddings. On compare ensuite `log_prob`, l'entropie et l'effet du
masque des deux côtés.
"""

from __future__ import annotations

from typing import Dict

import gymnasium as gym
import numpy as np
import pytest
import torch
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.distributions import MaskableCategorical

from ai.pointer_policy import PointerMaskablePolicy
from ai.spatial_extractor import SpatialCombinedExtractor
from engine.macro_intents import SHOOT_SLOT_BASE, SHOOT_SLOT_COUNT, TOTAL_ACTION_SIZE
from engine.observation_builder import ObservationBuilder
from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE


def _space() -> gym.spaces.Dict:
    spaces = {}
    for key, shape in ObservationBuilder.squad_obs_shapes().items():
        low, high = (-1.0, 1.0) if key.endswith("_bin") else (-np.inf, np.inf)
        spaces[key] = gym.spaces.Box(low=low, high=high, shape=shape, dtype=np.float32)
    spaces["grid"] = gym.spaces.Box(
        low=0.0, high=1.0, shape=(GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32
    )
    return gym.spaces.Dict(spaces)


class _ToyEnv(gym.Env):
    """Env jouet : l'espace d'observation réel, des transitions sans contenu."""

    observation_space = _space()
    action_space = gym.spaces.Discrete(TOTAL_ACTION_SIZE)

    def reset(self, *, seed=None, options=None):
        return _zero_obs(1), {}

    def step(self, action):
        return _zero_obs(1), 0.0, False, False, {}

    def action_masks(self):
        return np.ones(TOTAL_ACTION_SIZE, dtype=bool)


def _zero_obs(batch: int = 2) -> Dict[str, np.ndarray]:
    obs: Dict[str, np.ndarray] = {}
    for key, sp in _space().spaces.items():
        shape = sp.shape
        assert shape is not None
        obs[key] = np.zeros((batch,) + tuple(int(d) for d in shape), dtype=np.float32)
    obs["allies_bin"][:, 0, 0] = 1.0        # unité active présente
    obs["enemies_bin"][:, :3, 0] = 1.0      # trois ennemis présents
    obs["enemies_cont"][:, :3, 0] = 5.0
    return obs


def _tensors(obs: Dict[str, np.ndarray]) -> Dict[str, torch.Tensor]:
    return {k: torch.as_tensor(v) for k, v in obs.items()}


@pytest.fixture
def model() -> MaskablePPO:
    torch.manual_seed(7)
    return MaskablePPO(
        PointerMaskablePolicy, _ToyEnv(), n_steps=16, batch_size=8, device="cpu", verbose=0,
        policy_kwargs={
            "net_arch": [16, 16],
            "features_extractor_class": SpatialCombinedExtractor,
            "features_extractor_kwargs": {"cnn_features": 8},
        },
    )


def _manual_logits(policy, obs: Dict[str, torch.Tensor]):
    """Recalcul indépendant : (logits attendus, logits du pointeur seul, latent_pi)."""
    trunk, embeddings = policy._split_features(obs)
    latent_pi = policy.mlp_extractor.forward_actor(trunk)
    base = policy.action_net(latent_pi)
    query = policy.query_net(latent_pi)
    pointer = torch.einsum("bd,bkd->bk", query, embeddings) / (policy.entity_dim ** 0.5)
    end = SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
    expected = torch.cat([base[:, :SHOOT_SLOT_BASE], pointer, base[:, end:]], dim=1)
    return expected, pointer, latent_pi


def test_shoot_logits_come_from_the_dot_product(model):
    """Les logits de tir SONT `q · e_i / sqrt(d)`, et le reste sort de `action_net` inchangé."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    with torch.no_grad():
        expected, _pointer, latent_pi = _manual_logits(policy, obs)
        trunk, embeddings = policy._split_features(obs)
        produced = policy._action_logits(policy.mlp_extractor.forward_actor(trunk), embeddings)
    assert torch.allclose(produced, expected, atol=1e-6)
    # Le segment hors tir n'a pas été touché.
    with torch.no_grad():
        base = policy.action_net(latent_pi)
    assert torch.allclose(produced[:, :SHOOT_SLOT_BASE], base[:, :SHOOT_SLOT_BASE], atol=1e-6)


def test_pointer_matches_a_dense_reference_head(model):
    """Contre-épreuve « tête dense de référence » : W_dense = E · W_q / sqrt(d).

    Sur des embeddings donnés, le pointeur doit produire EXACTEMENT ce que produirait une
    couche dense de ces poids — et donner les mêmes `log_prob` et la même entropie.
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        trunk, embeddings = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(trunk)
        pointer = policy._action_logits(latent_pi, embeddings)[
            :, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT
        ]

        dense = torch.nn.Linear(latent_pi.shape[1], SHOOT_SLOT_COUNT, bias=True)
        w_q = policy.query_net.weight            # (d, latent)
        b_q = policy.query_net.bias              # (d,)
        e = embeddings[0]                        # (K, d)
        scale = policy.entity_dim ** 0.5
        dense.weight.copy_(e @ w_q / scale)
        dense.bias.copy_(e @ b_q / scale)
        dense_out = dense(latent_pi)
    assert torch.allclose(pointer, dense_out, atol=1e-5)

    # … et les grandeurs que PPO consomme sont identiques des deux côtés.
    masks = np.ones((1, TOTAL_ACTION_SIZE), dtype=bool)
    with torch.no_grad():
        full = policy._action_logits(latent_pi, embeddings)
        reference = torch.cat(
            [
                full[:, :SHOOT_SLOT_BASE],
                dense_out,
                full[:, SHOOT_SLOT_BASE + SHOOT_SLOT_COUNT:],
            ],
            dim=1,
        )
        dist_pointer = policy._distribution_from(latent_pi, embeddings, masks)
        ref_dist = MaskableCategorical(logits=reference, masks=masks)
        actions = torch.arange(TOTAL_ACTION_SIZE)
        for a in (0, SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + 2, TOTAL_ACTION_SIZE - 1):
            assert dist_pointer.log_prob(actions[a:a + 1]).item() == pytest.approx(
                ref_dist.log_prob(actions[a:a + 1]).item(), abs=1e-5
            )
        assert dist_pointer.entropy().item() == pytest.approx(ref_dist.entropy().item(), abs=1e-5)


def test_masking_removes_a_shoot_slot_from_the_distribution(model):
    """Un slot masqué a une probabilité NULLE et ne contribue plus à l'entropie."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    masks = np.zeros((1, TOTAL_ACTION_SIZE), dtype=bool)
    masks[0, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + 3] = True
    with torch.no_grad():
        dist = policy.get_distribution(obs, action_masks=masks)
        probs = dist.distribution.probs
    assert probs is not None
    assert float(probs[0, SHOOT_SLOT_BASE:SHOOT_SLOT_BASE + 3].sum()) == pytest.approx(1.0, abs=1e-5)
    assert float(probs[0, :SHOOT_SLOT_BASE].sum()) == pytest.approx(0.0, abs=1e-6)
    assert float(probs[0, SHOOT_SLOT_BASE + 3:].sum()) == pytest.approx(0.0, abs=1e-6)
    # Trois actions équiprobables au plus : l'entropie est bornée par ln 3.
    entropy = dist.entropy()
    assert entropy is not None
    assert float(entropy) <= float(np.log(3.0)) + 1e-5


def test_pointer_logit_is_slot_local(model):
    """À tronc FIXÉ, l'embedding du slot 1 ne déplace QUE le logit du slot 1.

    C'est la propriété qui rend le nombre de slots gratuit : chaque logit de tir ne dépend que
    de son propre ennemi. (Le tronc, lui, voit l'agrégation des ennemis en CONTEXTE — c'est
    voulu : changer un ennemi change aussi le contexte, donc les autres logits. On isole donc
    ici la tête pointeur, à latent constant.)
    """
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs(batch=1))
    with torch.no_grad():
        trunk, embeddings = policy._split_features(obs)
        latent_pi = policy.mlp_extractor.forward_actor(trunk)
        before = policy._action_logits(latent_pi, embeddings)
        perturbed = embeddings.clone()
        perturbed[:, 1] += 1.0
        after = policy._action_logits(latent_pi, perturbed)
    diff = (after - before).abs()[0]
    changed = torch.nonzero(diff > 1e-6).flatten().tolist()
    assert changed == [SHOOT_SLOT_BASE + 1], f"logits deplaces : {changed[:5]}"


def test_evaluate_actions_returns_values_log_prob_entropy(model):
    """Ordre de retour SB3 : (values, log_prob, entropy). L'inverser sabote PPO en silence."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    masks = np.ones((2, TOTAL_ACTION_SIZE), dtype=bool)
    actions = torch.tensor([SHOOT_SLOT_BASE, SHOOT_SLOT_BASE + 1])
    with torch.no_grad():
        values, log_prob, entropy = policy.evaluate_actions(obs, actions, action_masks=masks)
        dist = policy.get_distribution(obs, action_masks=masks)
        predicted_values = policy.predict_values(obs)
    assert values.shape == (2, 1)
    assert log_prob.shape == (2,)
    assert entropy is not None and entropy.shape == (2,)
    assert torch.allclose(values, predicted_values, atol=1e-6)
    assert torch.allclose(log_prob, dist.log_prob(actions), atol=1e-6)


def test_forward_log_prob_matches_the_distribution(model):
    """`forward` renvoie le `log_prob` de l'action qu'il a effectivement tirée."""
    policy = model.policy
    policy.set_training_mode(False)
    obs = _tensors(_zero_obs())
    masks = np.ones((2, TOTAL_ACTION_SIZE), dtype=bool)
    with torch.no_grad():
        actions, values, log_prob = policy(obs, deterministic=True, action_masks=masks)
        dist = policy.get_distribution(obs, action_masks=masks)
    assert torch.allclose(log_prob, dist.log_prob(actions), atol=1e-6)
    assert torch.isfinite(values).all()


def test_learning_step_runs_end_to_end(model):
    """Un cycle rollout + optimisation complet passe (gradients finis, aucune NaN)."""
    model.learn(total_timesteps=32)
    grads = [p.grad for p in model.policy.parameters() if p.grad is not None]
    assert grads, "aucun gradient : la tete pointeur n'est pas dans le graphe"
    assert all(torch.isfinite(g).all() for g in grads)
    assert model.policy.query_net.weight.grad is not None, (
        "la matrice de requete du pointeur ne recoit PAS de gradient"
    )


def test_pointer_requires_the_entity_extractor():
    """Sans les embeddings d'entités, la tête pointeur n'a pas de sens : ça doit LEVER."""
    from stable_baselines3.common.torch_layers import CombinedExtractor

    with pytest.raises(TypeError, match="SpatialCombinedExtractor"):
        MaskablePPO(
            PointerMaskablePolicy, _ToyEnv(), device="cpu", verbose=0,
            policy_kwargs={"net_arch": [8], "features_extractor_class": CombinedExtractor},
        )
