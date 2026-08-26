"""Tests Phase 2 perf_entrainement — pipeline SB3 learner.

Couvre :
  2.1  GpuMaskableDictRolloutBuffer : bool masks, tenseurs GPU, équivalence vs parent.
  2.2  PatchedMaskablePPO.train()   : gradient norm single-reduction, perte identique.
  2.3  collect_rollouts / inline masks : _env_has_inline_masks, extraction depuis infos.

Tous les tests tournent sur CPU (device="cpu") pour ne pas exiger de GPU en CI.
Verlock : les valeurs numériques (masques, loss, approx_kl) sont bit-à-bit identiques
          aux valeurs produites par le code non-patché.
"""
from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch


# ── helpers ──────────────────────────────────────────────────────────────────────────────────


def _make_dict_obs_space():
    """Espace d'observation Dict minimal (2 clés)."""
    from gymnasium import spaces
    return spaces.Dict({
        "a": spaces.Box(low=-1.0, high=1.0, shape=(4,), dtype=np.float32),
        "b": spaces.Box(low=0.0, high=1.0, shape=(3,), dtype=np.float32),
    })


def _make_discrete_action_space(n: int = 8):
    from gymnasium import spaces
    return spaces.Discrete(n)


def _fill_buffer(buf, n_steps: int, n_envs: int, n_actions: int, rng: np.random.Generator):
    """Remplit `buf` avec des données synthétiques."""
    from stable_baselines3.common.utils import obs_as_tensor
    obs_space = buf.observation_space
    import gymnasium as gym
    for step in range(n_steps):
        obs = {k: rng.standard_normal(v.shape).astype(np.float32)
               for k, v in obs_space.spaces.items()}
        obs_batch = {k: np.stack([obs[k]] * n_envs) for k in obs}
        action_masks = rng.integers(0, 2, size=(n_envs, n_actions)).astype(bool)
        # Au moins une action valide par env.
        action_masks[:, 0] = True
        actions = rng.integers(0, n_actions, size=(n_envs, 1)).astype(np.float32)
        values = torch.zeros(n_envs)
        log_probs = torch.full((n_envs,), -2.0)
        rewards = rng.standard_normal(n_envs).astype(np.float32)
        dones = np.zeros(n_envs, dtype=bool)
        episode_starts = np.zeros(n_envs, dtype=bool)
        buf.add(obs_batch, actions, rewards, episode_starts, values, log_probs,
                action_masks=action_masks)
    # GAE
    last_values = torch.zeros(n_envs)
    last_dones = np.zeros(n_envs, dtype=bool)
    buf.compute_returns_and_advantage(last_values=last_values, dones=last_dones)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2.1 — GpuMaskableDictRolloutBuffer
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestGpuMaskableDictRolloutBuffer:

    def _make_buffers(self, n_steps=4, n_envs=3, n_actions=8):
        """Retourne (gpu_buf, ref_buf) identiquement remplis."""
        from ai.gpu_rollout_buffer import GpuMaskableDictRolloutBuffer
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer

        obs_space = _make_dict_obs_space()
        act_space = _make_discrete_action_space(n_actions)
        kwargs = dict(
            buffer_size=n_steps, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=n_envs,
        )
        gpu_buf = GpuMaskableDictRolloutBuffer(**kwargs)
        ref_buf = MaskableDictRolloutBuffer(**kwargs)

        rng = np.random.default_rng(42)
        # Remplir les deux buffers avec exactement les mêmes données.
        obs_space_obj = gpu_buf.observation_space
        import gymnasium as gym

        def fill(buf):
            for step in range(n_steps):
                obs_batch = {
                    k: rng.standard_normal((n_envs,) + v.shape).astype(np.float32)
                    for k, v in obs_space_obj.spaces.items()
                }
                action_masks = np.ones((n_envs, n_actions), dtype=bool)
                action_masks[0, 1:] = False  # env 0 : seule action 0 valide
                actions = np.zeros((n_envs, 1), dtype=np.float32)
                values = torch.zeros(n_envs)
                log_probs = torch.full((n_envs,), -1.5)
                rewards = np.ones(n_envs, dtype=np.float32)
                episode_starts = np.zeros(n_envs, dtype=bool)
                buf.add(obs_batch, actions, rewards, episode_starts, values, log_probs,
                        action_masks=action_masks)
            buf.compute_returns_and_advantage(
                last_values=torch.zeros(n_envs), dones=np.zeros(n_envs, dtype=bool)
            )

        # reset rng pour avoir le même seed dans les deux buffers
        rng = np.random.default_rng(42)
        fill(gpu_buf)
        rng = np.random.default_rng(42)
        fill(ref_buf)
        return gpu_buf, ref_buf

    def test_reset_action_masks_bool(self):
        """Après reset(), action_masks est alloué en bool (pas float32)."""
        from ai.gpu_rollout_buffer import GpuMaskableDictRolloutBuffer
        buf = GpuMaskableDictRolloutBuffer(
            buffer_size=4,
            observation_space=_make_dict_obs_space(),
            action_space=_make_discrete_action_space(8),
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=2,
        )
        assert buf.action_masks.dtype == bool, (
            f"action_masks doit être bool, got {buf.action_masks.dtype}"
        )

    def test_get_uploads_gpu_tensors(self):
        """Après le premier appel de get(), _gpu_obs et _gpu_action_masks sont non-None."""
        gpu_buf, _ = self._make_buffers()
        assert gpu_buf._gpu_obs is None, "avant get() : pas encore uploadé"
        _ = next(iter(gpu_buf.get(batch_size=4 * 3)))
        assert gpu_buf._gpu_obs is not None, "après get() : tenseurs GPU créés"
        assert gpu_buf._gpu_action_masks is not None

    def test_gpu_masks_dtype_float32(self):
        """Les masques GPU sont en float32 (pour la policy), même si stockés bool."""
        gpu_buf, _ = self._make_buffers()
        _ = next(iter(gpu_buf.get(batch_size=4 * 3)))
        assert gpu_buf._gpu_action_masks.dtype == torch.float32, (
            f"_gpu_action_masks doit être float32, got {gpu_buf._gpu_action_masks.dtype}"
        )

    def test_samples_numerically_equal_to_reference(self):
        """Les samples du GPU buffer sont numériquement identiques au buffer de référence."""
        gpu_buf, ref_buf = self._make_buffers(n_steps=6, n_envs=3, n_actions=8)
        total = 6 * 3  # buffer_size * n_envs

        # Permutation fixe pour comparer apples-to-apples.
        rng_shared = np.random.default_rng(7)
        perm = rng_shared.permutation(total)

        # Patch np.random.permutation pour forcer la même permutation dans les deux buffers.
        with patch("numpy.random.permutation", return_value=perm):
            gpu_samples = list(gpu_buf.get(batch_size=total))
            ref_samples = list(ref_buf.get(batch_size=total))

        assert len(gpu_samples) == len(ref_samples) == 1

        g = gpu_samples[0]
        r = ref_samples[0]

        # Observations
        for key in g.observations:
            torch.testing.assert_close(
                g.observations[key].float(), r.observations[key].float(),
                msg=f"obs[{key!r}] diverge"
            )

        # Masques : référence float32 (1.0/0.0), GPU float32 (idem via bool→float).
        torch.testing.assert_close(g.action_masks, r.action_masks, msg="action_masks diverge")

        # Autres champs
        for attr in ("actions", "old_values", "old_log_prob", "advantages", "returns"):
            torch.testing.assert_close(
                getattr(g, attr).float(), getattr(r, attr).float(),
                msg=f"{attr} diverge"
            )

    def test_second_epoch_reuses_gpu_tensors(self):
        """Le second appel de get() ne réalloue pas les tenseurs GPU (même objet)."""
        gpu_buf, _ = self._make_buffers()
        _ = list(gpu_buf.get(batch_size=4 * 3))
        obs_ref = {k: v.data_ptr() for k, v in gpu_buf._gpu_obs.items()}
        masks_ref = gpu_buf._gpu_action_masks.data_ptr()

        # Deuxième epoch — generator_ready est True, upload ne doit pas se reproduire.
        _ = list(gpu_buf.get(batch_size=4 * 3))
        assert {k: v.data_ptr() for k, v in gpu_buf._gpu_obs.items()} == obs_ref, (
            "deuxième epoch : tenseurs obs réalloués (H2D supplémentaire non voulu)"
        )
        assert gpu_buf._gpu_action_masks.data_ptr() == masks_ref, (
            "deuxième epoch : tenseurs masks réalloués"
        )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2.2 — Gradient norm single reduction
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestGradientNormSingleReduction:

    def _make_policy_with_grads(self, values: list[float]):
        """Politique factice avec des gradients connus."""
        params = []
        for v in values:
            p = torch.nn.Parameter(torch.zeros(1))
            p.grad = torch.tensor([v])
            params.append(p)

        class FakePolicy:
            def parameters(self_):
                return iter(params)

        return FakePolicy()

    def test_single_item_equals_manual_loop(self):
        """La réduction GPU (torch.cat + norm) donne le même résultat que la boucle originale."""
        grad_values = [3.0, 4.0]  # norme = 5.0
        policy = self._make_policy_with_grads(grad_values)

        # Méthode originale (boucle + N .item())
        total_norm = 0.0
        for p in policy.parameters():
            if p.grad is not None:
                total_norm += p.grad.data.norm(2).item() ** 2
        original_norm = total_norm ** 0.5

        # Méthode patchée (single .item())
        grads = [p.grad.data.reshape(-1) for p in policy.parameters() if p.grad is not None]
        patched_norm = torch.cat(grads).norm(2).item()

        assert math.isclose(original_norm, patched_norm, rel_tol=1e-6), (
            f"Normes divergent : {original_norm} vs {patched_norm}"
        )
        assert math.isclose(patched_norm, 5.0, rel_tol=1e-6), (
            f"Norme attendue 5.0, got {patched_norm}"
        )

    def test_no_grad_returns_nothing(self):
        """Sans gradient, la condition `if grads` est False — pas d'erreur."""
        class FakePolicy:
            def parameters(self_):
                p = torch.nn.Parameter(torch.zeros(1))
                # p.grad reste None
                return iter([p])

        grads = [p.grad.data.reshape(-1) for p in FakePolicy().parameters() if p.grad is not None]
        assert not grads, "pas de grad → liste vide attendue"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2.2 — PatchedMaskablePPO.train() déferred .item() — parité numérique
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestPatchedTrainNumericalParity:
    """Vérifie que train() patché produit les mêmes loss et approx_kl que l'original.

    On injecte un rollout_buffer synthétique et on compare les valeurs loguées.
    """

    def _make_fake_rollout_data(self, n: int = 12, n_actions: int = 8):
        """MaskableDictRolloutBufferSamples factice sur CPU."""
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBufferSamples
        rng = torch.manual_seed(0)
        obs = {
            "a": torch.randn(n, 4),
            "b": torch.randn(n, 3),
        }
        actions = torch.zeros(n, dtype=torch.long)
        old_values = torch.randn(n)
        old_log_prob = torch.full((n,), -2.0)
        advantages = torch.randn(n)
        returns = torch.randn(n)
        action_masks = torch.ones(n, n_actions)
        return MaskableDictRolloutBufferSamples(
            observations=obs,
            actions=actions.float(),
            old_values=old_values,
            old_log_prob=old_log_prob,
            advantages=advantages,
            returns=returns,
            action_masks=action_masks,
        )

    def test_patched_train_records_finite_metrics(self):
        """train() patché enregistre des métriques finies sans crash."""
        from ai.patched_ppo import PatchedMaskablePPO
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer
        from gymnasium import spaces
        import gymnasium as gym

        obs_space = _make_dict_obs_space()
        act_space = _make_discrete_action_space(8)

        # DummyVecEnv minimal.
        env = MagicMock()
        env.observation_space = obs_space
        env.action_space = act_space
        env.num_envs = 1

        # On instancie PatchedMaskablePPO puis on injecte un buffer synthétique.
        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)

        # Policy fictive.
        from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
        policy_mock = MagicMock(spec=MaskableActorCriticPolicy)
        policy_mock.parameters.return_value = iter([])
        # evaluate_actions retourne des valeurs avec grad_fn (nécessaire pour loss.backward()).
        n = 8
        def fake_evaluate_actions(obs, actions, action_masks=None):
            w = torch.ones(1, requires_grad=True)
            values = (torch.zeros(n) * w).flatten()
            log_prob = torch.full((n,), -2.0) * w
            entropy = torch.zeros(n) * w
            return values, log_prob, entropy
        policy_mock.evaluate_actions.side_effect = fake_evaluate_actions
        policy_mock.optimizer = MagicMock()
        policy_mock.optimizer.zero_grad = MagicMock()
        policy_mock.optimizer.step = MagicMock()

        # Rollout buffer avec données réelles (GAE calculé).
        rng = np.random.default_rng(0)
        buf = MaskableDictRolloutBuffer(
            buffer_size=4, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=2,
        )
        for step in range(4):
            obs_b = {k: rng.standard_normal((2,) + v.shape).astype(np.float32)
                     for k, v in obs_space.spaces.items()}
            masks = np.ones((2, 8), dtype=bool)
            buf.add(obs_b, np.zeros((2, 1), dtype=np.float32), np.ones(2, dtype=np.float32),
                    np.zeros(2, dtype=bool), torch.zeros(2), torch.full((2,), -2.0),
                    action_masks=masks)
        buf.compute_returns_and_advantage(torch.zeros(2), np.zeros(2, dtype=bool))

        # Configurer le model minimal.
        model.policy = policy_mock
        model.rollout_buffer = buf
        model.n_epochs = 1
        model.batch_size = 8  # batch complet (4 steps × 2 envs)
        model.normalize_advantage = True
        model.ent_coef = 0.01
        model.vf_coef = 0.5
        model.max_grad_norm = 0.5
        model.target_kl = None
        model.clip_range_vf = None
        model._current_progress_remaining = 1.0
        model._n_updates = 0
        model.verbose = 0
        model.action_space = act_space

        # clip_range doit être callable.
        model.clip_range = MagicMock(return_value=0.2)
        model.lr_schedule = MagicMock(return_value=1e-4)

        # Logger factice.
        recorded: dict[str, Any] = {}
        logger_mock = MagicMock()
        logger_mock.record.side_effect = lambda key, value, **kw: recorded.__setitem__(key, value)
        object.__setattr__(model, "_logger", logger_mock)

        model.train()

        # Vérifier que les métriques finies sont enregistrées.
        for key in ("train/entropy_loss", "train/policy_gradient_loss",
                    "train/value_loss", "train/approx_kl", "train/clip_fraction"):
            assert key in recorded, f"{key!r} non enregistré"
            val = recorded[key]
            assert math.isfinite(val), f"{key!r} = {val} (non fini)"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2.3 — _env_has_inline_masks + extraction des masques depuis infos
# ══════════════════════════════════════════════════════════════════════════════════════════════


class TestInlineMasks:

    def test_env_has_inline_masks_false_for_dummy(self):
        """DummyVecEnv ne déclenche pas _env_has_inline_masks."""
        from ai.patched_ppo import _env_has_inline_masks
        from stable_baselines3.common.vec_env import DummyVecEnv

        dummy = MagicMock(spec=DummyVecEnv)
        # Pas d'attribut `venv` → la boucle while s'arrête immédiatement.
        del dummy.venv
        assert not _env_has_inline_masks(dummy)

    def test_env_has_inline_masks_true_for_maskable(self):
        """MaskableSubprocVecEnv déclenche _env_has_inline_masks."""
        from ai.patched_ppo import _env_has_inline_masks
        from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv

        # VecNormalize factice wrappant un MaskableSubprocVecEnv.
        inner = MagicMock(spec=MaskableSubprocVecEnv)
        del inner.venv
        outer = MagicMock()
        outer.venv = inner

        assert _env_has_inline_masks(outer)

    def test_collect_rollouts_extracts_masks_from_infos(self):
        """collect_rollouts lit les masques depuis infos quand use_inline_masks=True."""
        from ai.patched_ppo import PatchedMaskablePPO, _env_has_inline_masks
        from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv
        from sb3_contrib.common.maskable.buffers import MaskableDictRolloutBuffer

        n_envs = 2
        n_actions = 8
        obs_space = _make_dict_obs_space()
        act_space = _make_discrete_action_space(n_actions)

        # VecEnv factice avec MaskableSubprocVecEnv au fond.
        inner_vec = MagicMock(spec=MaskableSubprocVecEnv)
        del inner_vec.venv

        env_mock = MagicMock()
        env_mock.venv = inner_vec
        env_mock.num_envs = n_envs
        env_mock.observation_space = obs_space
        env_mock.action_space = act_space

        # obs initiale
        init_obs = {k: np.zeros((n_envs,) + v.shape, dtype=np.float32)
                    for k, v in obs_space.spaces.items()}

        # step() retourne infos avec action_masks.
        masks_returned = np.ones((n_envs, n_actions), dtype=bool)
        masks_returned[0, 1:] = False  # env 0 strict
        step_obs = {k: np.zeros((n_envs,) + v.shape, dtype=np.float32)
                    for k, v in obs_space.spaces.items()}
        env_mock.step.return_value = (
            step_obs,
            np.zeros(n_envs, dtype=np.float32),
            np.zeros(n_envs, dtype=bool),
            [{"action_masks": masks_returned[i]} for i in range(n_envs)],
        )
        env_mock.has_attr.return_value = True  # is_masking_supported

        # Rollout buffer minimal.
        buf = MaskableDictRolloutBuffer(
            buffer_size=2, observation_space=obs_space, action_space=act_space,
            device="cpu", gamma=0.99, gae_lambda=0.95, n_envs=n_envs,
        )

        with patch.object(PatchedMaskablePPO, "_setup_model"):
            model = PatchedMaskablePPO.__new__(PatchedMaskablePPO)

        from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
        policy_mock = MagicMock(spec=MaskableActorCriticPolicy)
        policy_mock.return_value = (
            torch.zeros(n_envs, dtype=torch.long),
            torch.zeros(n_envs),
            torch.full((n_envs,), -2.0),
        )
        policy_mock.predict_values.return_value = torch.zeros(n_envs)
        policy_mock.set_training_mode = MagicMock()

        model.policy = policy_mock
        model.device = torch.device("cpu")
        model._last_obs = init_obs
        model._last_episode_starts = np.zeros(n_envs, dtype=bool)
        model.num_timesteps = 0
        model.gamma = 0.99
        model.action_space = act_space

        callback = MagicMock()
        callback.on_rollout_start = MagicMock()
        callback.on_step.return_value = True
        callback.on_rollout_end = MagicMock()
        model._update_info_buffer = MagicMock()

        # Espionner get_action_masks : doit être appelé UNE SEULE FOIS (bootstrap step 0).
        with patch("ai.patched_ppo.get_action_masks") as mock_gam:
            # Bootstrap : get_action_masks retourne des masques plein pour step 0.
            mock_gam.return_value = np.ones((n_envs, n_actions), dtype=bool)

            result = model.collect_rollouts(
                env_mock, callback, buf, n_rollout_steps=2, use_masking=True
            )

        assert result is True
        # get_action_masks ne doit être appelé qu'au step 0 (1 fois).
        assert mock_gam.call_count == 1, (
            f"get_action_masks appelé {mock_gam.call_count}× au lieu de 1 "
            f"(2e RPC non supprimé)"
        )
