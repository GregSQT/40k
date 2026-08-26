"""PatchedMaskablePPO — sous-classe locale de MaskablePPO pour la Phase 2 perf_entrainement.

Trois overrides, sans changer les maths :

2.1 — _setup_model() : GpuMaskableDictRolloutBuffer pour les espaces Dict (masques en bool,
      tenseurs résidents GPU — plus de H2D par epoch). Combiné avec recreate_rollout_buffer()
      dans train.py pour les modèles chargés.

2.2 — train() : accumule les losses comme tenseurs GPU et ne synchro (.item()) qu'une fois
      en fin d'update — supprime ~225 syncs GPU/CPU par cycle (5 epochs × 9 minibatches × 5
      métriques). Parité garantie : les valeurs de loss et approx_kl sont mathématiquement
      identiques ; seul l'ordre des transferts change.

2.3 — collect_rollouts() : lit action_masks depuis infos["action_masks"] (posé par
      MaskableSubprocVecEnv dans le même RPC que step) au lieu d'un second env_method RPC.
      Sauvegarde ~340/341 RPCs par rollout. Fallback automatique sur get_action_masks() si
      infos ne contiennent pas le masque (DummyVecEnv, tests).
"""
from __future__ import annotations

import time
from typing import Any, TypeVar

import numpy as np
import torch as th
from gymnasium import spaces
from stable_baselines3.common.buffers import RolloutBuffer
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.utils import explained_variance, obs_as_tensor
from stable_baselines3.common.vec_env import VecEnv
from torch.nn import functional as F

from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.buffers import (
    MaskableDictRolloutBuffer,
    MaskableRolloutBuffer,
)
from sb3_contrib.common.maskable.utils import get_action_masks, is_masking_supported

from ai.gpu_rollout_buffer import GpuMaskableDictRolloutBuffer

SelfPatchedMaskablePPO = TypeVar("SelfPatchedMaskablePPO", bound="PatchedMaskablePPO")


def _env_has_inline_masks(env: VecEnv) -> bool:
    """True si l'env est un MaskableSubprocVecEnv (masques dans infos de step)."""
    # Import local pour éviter la dépendance circulaire au niveau module.
    try:
        from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv
    except ImportError:
        return False
    # Remonter les wrappers VecEnv (VecNormalize, etc.)
    vec: Any = env
    while hasattr(vec, "venv"):
        vec = vec.venv
    return isinstance(vec, MaskableSubprocVecEnv)


class PatchedMaskablePPO(MaskablePPO):
    """MaskablePPO avec optimisations learner Phase 2 (GPU buffer, logging différé, single RPC)."""

    # ── 2.1 — GPU-resident buffer ─────────────────────────────────────────────────────────────

    def _setup_model(self) -> None:
        super()._setup_model()
        # Remplacer le buffer Dict par la version GPU-résidente.
        if isinstance(self.observation_space, spaces.Dict):
            self.rollout_buffer = GpuMaskableDictRolloutBuffer(
                self.n_steps,
                self.observation_space,
                self.action_space,
                self.device,
                gamma=self.gamma,
                gae_lambda=self.gae_lambda,
                n_envs=self.n_envs,
            )

    # ── 2.2 — Logging différé (~225 syncs → ~5 syncs par update) ─────────────────────────────

    def train(self) -> None:
        self.policy.set_training_mode(True)
        self._update_learning_rate(self.policy.optimizer)
        clip_range = self.clip_range(self._current_progress_remaining)  # type: ignore[operator]
        clip_range_vf: float | None = None
        if self.clip_range_vf is not None:
            clip_range_vf = self.clip_range_vf(self._current_progress_remaining)  # type: ignore[operator]

        # Tenseurs GPU accumulés sur tous les minibatches de tous les epochs.
        pg_losses_t: list[th.Tensor] = []
        value_losses_t: list[th.Tensor] = []
        entropy_losses_t: list[th.Tensor] = []
        clip_fractions_t: list[th.Tensor] = []
        # approx_kl : tenseurs si target_kl absent (pas de sync inter-minibatch) ;
        # floats si target_kl présent (early-stopping nécessite la valeur scalaire).
        approx_kl_divs_t: list[th.Tensor] = []
        approx_kl_divs: list[float] = []
        continue_training = True

        _t0_update = time.perf_counter()
        for epoch in range(self.n_epochs):
            for rollout_data in self.rollout_buffer.get(self.batch_size):
                actions = rollout_data.actions
                if isinstance(self.action_space, spaces.Discrete):
                    actions = rollout_data.actions.long().flatten()

                values, log_prob, entropy = self.policy.evaluate_actions(
                    rollout_data.observations,
                    actions,
                    action_masks=rollout_data.action_masks,
                )
                values = values.flatten()

                advantages = rollout_data.advantages
                if self.normalize_advantage:
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

                ratio = th.exp(log_prob - rollout_data.old_log_prob)

                policy_loss_1 = advantages * ratio
                policy_loss_2 = advantages * th.clamp(ratio, 1 - clip_range, 1 + clip_range)
                policy_loss = -th.min(policy_loss_1, policy_loss_2).mean()

                # Accumulation GPU — pas de .item() ici.
                pg_losses_t.append(policy_loss)
                clip_fractions_t.append(th.mean((th.abs(ratio - 1) > clip_range).float()))

                if clip_range_vf is None:
                    values_pred = values
                else:
                    values_pred = rollout_data.old_values + th.clamp(
                        values - rollout_data.old_values, -clip_range_vf, clip_range_vf
                    )
                value_loss = F.mse_loss(rollout_data.returns, values_pred)
                value_losses_t.append(value_loss)

                if entropy is None:
                    entropy_loss = -th.mean(-log_prob)
                else:
                    entropy_loss = -th.mean(entropy)
                entropy_losses_t.append(entropy_loss)

                loss = policy_loss + self.ent_coef * entropy_loss + self.vf_coef * value_loss

                with th.no_grad():
                    log_ratio = log_prob - rollout_data.old_log_prob
                    approx_kl_div_t = th.mean((th.exp(log_ratio) - 1) - log_ratio)

                if self.target_kl is not None:
                    # Early-stopping exige la valeur scalaire maintenant.
                    approx_kl_val = float(approx_kl_div_t.cpu().numpy())
                    approx_kl_divs.append(approx_kl_val)
                    if approx_kl_val > 1.5 * self.target_kl:
                        continue_training = False
                        if self.verbose >= 1:
                            print(
                                f"Early stopping at step {epoch} due to reaching max kl: "
                                f"{approx_kl_val:.2f}"
                            )
                        break
                else:
                    approx_kl_divs_t.append(approx_kl_div_t)

                self.policy.optimizer.zero_grad()
                loss.backward()
                th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
                self.policy.optimizer.step()

            if not continue_training:
                break

        self._n_updates += 1
        # Un seul .item() par métrique (5 syncs au lieu de ~225).
        def _mean_item(tensors: list[th.Tensor]) -> float:
            return th.stack(tensors).mean().item() if tensors else float("nan")

        pg_loss_mean = _mean_item(pg_losses_t)
        clip_frac_mean = _mean_item(clip_fractions_t)
        value_loss_mean = _mean_item(value_losses_t)
        entropy_loss_mean = _mean_item(entropy_losses_t)

        if approx_kl_divs_t:
            approx_kl_mean = _mean_item(approx_kl_divs_t)
        elif approx_kl_divs:
            approx_kl_mean = float(np.mean(approx_kl_divs))
        else:
            approx_kl_mean = float("nan")

        explained_var = explained_variance(
            self.rollout_buffer.values.flatten(),
            self.rollout_buffer.returns.flatten(),
        )

        self.logger.record("train/time_update", time.perf_counter() - _t0_update)
        self.logger.record("train/entropy_loss", entropy_loss_mean)
        self.logger.record("train/policy_gradient_loss", pg_loss_mean)
        self.logger.record("train/value_loss", value_loss_mean)
        self.logger.record("train/approx_kl", approx_kl_mean)
        self.logger.record("train/clip_fraction", clip_frac_mean)
        self.logger.record("train/loss", loss.item())  # noqa: F821 — dernier minibatch
        self.logger.record("train/explained_variance", explained_var)
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/clip_range", clip_range)
        if clip_range_vf is not None:
            self.logger.record("train/clip_range_vf", clip_range_vf)

    # ── 2.3 — Un seul RPC par step ───────────────────────────────────────────────────────────

    def collect_rollouts(
        self,
        env: VecEnv,
        callback: BaseCallback,
        rollout_buffer: RolloutBuffer,
        n_rollout_steps: int,
        use_masking: bool = True,
    ) -> bool:
        assert isinstance(
            rollout_buffer, (MaskableRolloutBuffer, MaskableDictRolloutBuffer)
        ), "RolloutBuffer doesn't support action masking"
        assert self._last_obs is not None

        self.policy.set_training_mode(False)
        n_steps = 0
        action_masks = None
        rollout_buffer.reset()

        if use_masking and not is_masking_supported(env):
            raise ValueError(
                "Environment does not support action masking. Consider using ActionMasker wrapper"
            )

        # Détecter si les masques voyagent dans infos (MaskableSubprocVecEnv, Phase 2.3).
        use_inline_masks = use_masking and _env_has_inline_masks(env)
        # Pour le premier step, on n'a pas encore de masques inline — on appelle get_action_masks.
        next_step_masks: np.ndarray | None = None

        callback.on_rollout_start()

        while n_steps < n_rollout_steps:
            with th.no_grad():
                obs_tensor = obs_as_tensor(self._last_obs, self.device)  # type: ignore[arg-type]

                if use_masking:
                    if use_inline_masks and next_step_masks is not None:
                        action_masks = next_step_masks
                    else:
                        action_masks = get_action_masks(env)

                actions, values, log_probs = self.policy(obs_tensor, action_masks=action_masks)

            actions = actions.cpu().numpy()
            new_obs, rewards, dones, infos = env.step(actions)

            # Extraire les masques du prochain step depuis infos (évite le 2e RPC).
            if use_inline_masks:
                try:
                    next_step_masks = np.stack([info["action_masks"] for info in infos])
                except (KeyError, TypeError):
                    next_step_masks = None

            self.num_timesteps += env.num_envs
            callback.update_locals(locals())
            if not callback.on_step():
                return False

            self._update_info_buffer(infos, dones)
            n_steps += 1

            if isinstance(self.action_space, spaces.Discrete):
                actions = actions.reshape(-1, 1)

            for idx, done in enumerate(dones):
                if (
                    done
                    and infos[idx].get("terminal_observation") is not None
                    and infos[idx].get("TimeLimit.truncated", False)
                ):
                    terminal_obs = self.policy.obs_to_tensor(infos[idx]["terminal_observation"])[0]
                    with th.no_grad():
                        terminal_value = self.policy.predict_values(terminal_obs)[0]
                    rewards[idx] += self.gamma * terminal_value

            rollout_buffer.add(
                self._last_obs,
                actions,
                rewards,
                self._last_episode_starts,
                values,
                log_probs,
                action_masks=action_masks,
            )
            self._last_obs = new_obs  # type: ignore[assignment]
            self._last_episode_starts = dones

        with th.no_grad():
            values = self.policy.predict_values(obs_as_tensor(new_obs, self.device))  # type: ignore[arg-type]

        rollout_buffer.compute_returns_and_advantage(last_values=values, dones=dones)
        callback.on_rollout_end()
        return True
