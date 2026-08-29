"""PatchedMaskablePPO — sous-classe locale de MaskablePPO pour les Phases 2 et 3 perf_entrainement.

Quatre overrides, sans changer les maths :

2.1 — _setup_model() : GpuMaskableDictRolloutBuffer pour les espaces Dict (masques en bool,
      tenseurs résidents GPU — plus de H2D par epoch). Combiné avec recreate_rollout_buffer()
      dans train.py pour les modèles chargés.

2.2 — train() : accumule les losses comme tenseurs GPU et ne synchro (.item()) qu'une fois
      en fin d'update — supprime ~225 syncs GPU/CPU par cycle (5 epochs × 9 minibatches × 5
      métriques). Parité garantie : les valeurs de loss et approx_kl sont mathématiquement
      identiques ; seul l'ordre des transferts change.

2.3 — collect_rollouts() : collecte step-by-step, conservée comme chemin des VecEnv qui ne
      sont pas des MaskableSubprocVecEnv (DummyVecEnv, tests). La lecture des masques depuis
      infos["action_masks"] qui vivait ici est devenue sans objet en Phase 3 : le seul cas
      qu'elle servait — MaskableSubprocVecEnv — part désormais en collecte distribuée.

3 — collect_rollouts() (Phase 3 Option A) : détecte MaskableSubprocVecEnv et bascule sur
    _collect_rollouts_distributed(). Chaque worker reçoit une copie sérialisée des poids
    (cloudpickle) + snapshot VecNormalize, déroule ses n_steps steps en autonome, retourne
    sa trajectoire. Le learner agrège les trajectoires dans le buffer GPU sans lockstep.
    Écart sémantique VecNormalize documenté dans perf_entrainement.md §3 + verrou de test.
"""
from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, TypeVar

import numpy as np
import torch as th
from gymnasium import spaces
from stable_baselines3.common.buffers import RolloutBuffer
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.utils import explained_variance, obs_as_tensor
from stable_baselines3.common.vec_env import DummyVecEnv, VecEnv
from torch.nn import functional as F

from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.buffers import (
    MaskableDictRolloutBuffer,
    MaskableRolloutBuffer,
)
from sb3_contrib.common.maskable.utils import get_action_masks, is_masking_supported

from ai.gpu_rollout_buffer import GpuMaskableDictRolloutBuffer
from ai.vec_normalize_frozen import copy_obs_dict

SelfPatchedMaskablePPO = TypeVar("SelfPatchedMaskablePPO", bound="PatchedMaskablePPO")

class PatchedDummyVecEnv(DummyVecEnv):
    """DummyVecEnv qui corrige l'aliasing terminal_observation sur les envs scratch-buffer.

    SB3 DummyVecEnv.step_wait stocke `terminal_observation = obs` (référence au scratch
    moteur) AVANT d'appeler env.reset(), qui écrase ce même scratch. Le deepcopy final
    capture alors l'obs POST-reset, pas l'obs terminale. Fix : copie possédée avant reset.

    Réimplémentation nécessaire : le bug est dans le corps du loop SB3 ; il n'existe pas de
    hook propre pour intercepter la valeur avant reset() sans réécrire la boucle. Basé sur
    SB3 2.9.0 dummy_vec_env.py — vérifier à chaque upgrade SB3 que step_wait n'a pas changé.
    """

    def step_wait(self):  # type: ignore[override]
        for env_idx in range(self.num_envs):
            obs, self.buf_rews[env_idx], terminated, truncated, self.buf_infos[env_idx] = (
                self.envs[env_idx].step(self.actions[env_idx])
            )
            self.buf_dones[env_idx] = terminated or truncated
            self.buf_infos[env_idx]["TimeLimit.truncated"] = truncated and not terminated
            if self.buf_dones[env_idx]:
                # Copie AVANT reset : le scratch moteur sera écrasé par l'épisode suivant.
                self.buf_infos[env_idx]["terminal_observation"] = copy_obs_dict(obs)
                obs, self.reset_infos[env_idx] = self.envs[env_idx].reset()
            self._save_obs(env_idx, obs)
        return (
            self._obs_from_buf(),
            np.copy(self.buf_rews),
            np.copy(self.buf_dones),
            deepcopy(self.buf_infos),
        )


# Sentinelle pour détecter qu'aucune trajectoire n'a été collectée (ne peut pas être None).
_NO_OBS = object()


def _get_maskable_subproc_vec_env(env: VecEnv) -> "Any | None":
    """Retourne le MaskableSubprocVecEnv dans la chaîne de wrappers, ou None."""
    try:
        from ai.maskable_subproc_vec_env import MaskableSubprocVecEnv
    except ImportError:
        return None
    vec: Any = env
    while hasattr(vec, "venv"):
        if isinstance(vec, MaskableSubprocVecEnv):
            return vec
        vec = vec.venv
    if isinstance(vec, MaskableSubprocVecEnv):
        return vec
    return None


def _mean_item(tensors: list[th.Tensor]) -> float:
    return th.stack(tensors).mean().item() if tensors else float("nan")


class PatchedMaskablePPO(MaskablePPO):
    """MaskablePPO avec optimisations learner Phase 2 (GPU buffer, logging différé, single RPC)."""

    # ── 2.1 — GPU-resident buffer ─────────────────────────────────────────────────────────────

    def _setup_model(self) -> None:
        super()._setup_model()
        # Remplacer le buffer Dict par la version GPU-résidente.
        if isinstance(self.observation_space, spaces.Dict):
            self.rollout_buffer = GpuMaskableDictRolloutBuffer(  # type: ignore[assignment]
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
        # Diagnostic divergence GPU/CPU — à retirer après identification de la cause.
        # Capture uniquement le minibatch 0 d'epoch 0 : seul point vraiment pré-update.
        _diag_drift_norm_mb0: th.Tensor | None = None
        _diag_drift_mean_mb0: th.Tensor | None = None
        _diag_logprob_drift_mb0: th.Tensor | None = None
        _diag_ratio_mb0: th.Tensor | None = None
        continue_training = True
        loss: th.Tensor = th.tensor(float("nan"))

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

                # Diagnostic minibatch 0/epoch 0 : seul point vraiment pré-update.
                if epoch == 0 and _diag_drift_norm_mb0 is None:
                    with th.no_grad():
                        _drift = values - rollout_data.old_values
                        _diag_drift_norm_mb0 = _drift.norm()
                        _diag_drift_mean_mb0 = _drift.abs().mean()
                        _lp_drift = log_prob - rollout_data.old_log_prob
                        _diag_logprob_drift_mb0 = _lp_drift.abs().mean()
                        # exp(mean(Δlp)) = ratio géométrique moyen : vaut 1.0 à politique stable,
                        # insensible aux extrêmes individuels (pas de débordement float32 sur le mean).
                        _diag_ratio_mb0 = th.exp(_lp_drift.mean())

                advantages = rollout_data.advantages
                if self.normalize_advantage:
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

                log_ratio = log_prob - rollout_data.old_log_prob
                ratio = th.exp(log_ratio)

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
        self.logger.record("train/loss", loss.item())
        self.logger.record("train/explained_variance", explained_var)
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/clip_range", clip_range)
        if clip_range_vf is not None:
            self.logger.record("train/clip_range_vf", clip_range_vf)
        # Diagnostic divergence GPU/CPU — magnitudes de référence + drift pré-update.
        # value_drift_norm_mb0 ≫ 0 → worker values ≠ GPU learner values dès la collecte.
        # returns_mean vs old_values_mean → détecte un écart de scale (VecNormalize désynced).
        _nan = float("nan")
        self.logger.record(
            "diag/value_drift_norm_mb0",
            _diag_drift_norm_mb0.item() if _diag_drift_norm_mb0 is not None else _nan,
        )
        self.logger.record(
            "diag/value_drift_mean_abs_mb0",
            _diag_drift_mean_mb0.item() if _diag_drift_mean_mb0 is not None else _nan,
        )
        self.logger.record(
            "diag/logprob_drift_mean_abs_mb0",
            _diag_logprob_drift_mb0.item() if _diag_logprob_drift_mb0 is not None else _nan,
        )
        self.logger.record(
            "diag/ratio_mb0_mean",
            _diag_ratio_mb0.item() if _diag_ratio_mb0 is not None else _nan,
        )
        self.logger.record("diag/returns_mean", float(self.rollout_buffer.returns.mean()))
        self.logger.record("diag/old_values_mean", float(self.rollout_buffer.values.mean()))
        self.logger.record("diag/rewards_mean", float(self.rollout_buffer.rewards.mean()))
        # Bootstrap : last_values GPU vs last_value CPU (posés par _collect_rollouts_distributed).
        self.logger.record("diag/last_values_gpu_mean", getattr(self, "_diag_last_values_gpu_mean", _nan))
        self.logger.record("diag/last_values_cpu_mean", getattr(self, "_diag_last_values_cpu_mean", _nan))

    # ── 2.3 / 3 — collect_rollouts : step-by-step ou distribué ──────────────────────────────────

    def collect_rollouts(
        self,
        env: VecEnv,
        callback: BaseCallback,
        rollout_buffer: RolloutBuffer,
        n_rollout_steps: int,
        use_masking: bool = True,
    ) -> bool:
        """Collecte le rollout. Bascule sur la collecte distribuée (Phase 3) si disponible."""
        assert isinstance(
            rollout_buffer, (MaskableRolloutBuffer, MaskableDictRolloutBuffer)
        ), "RolloutBuffer doesn't support action masking"
        assert self._last_obs is not None

        subproc = _get_maskable_subproc_vec_env(env)
        if subproc is not None:
            return self._collect_rollouts_distributed(
                env, subproc, callback, rollout_buffer, n_rollout_steps, use_masking
            )
        return self._collect_rollouts_stepwise(
            env, callback, rollout_buffer, n_rollout_steps, use_masking
        )

    def _collect_rollouts_distributed(
        self,
        env: VecEnv,
        subproc: "Any",
        callback: BaseCallback,
        rollout_buffer: MaskableRolloutBuffer | MaskableDictRolloutBuffer,
        n_rollout_steps: int,
        use_masking: bool,
    ) -> bool:
        """Phase 3 — collecte sans lockstep.

        Chaque worker reçoit la policy gelée + snapshot VecNormalize, déroule ses n_steps
        steps en autonome, renvoie sa trajectoire. Le learner ne fait que l'update GPU.

        Sémantique garantie par rapport à collect_rollouts step-by-step :
        - Mêmes poids pendant tout le rollout (SB3 ne met pas à jour la policy pendant collect).
        - Bootstrap TimeLimit.truncated exactement comme SB3 (dans le worker).
        - VecNormalize stats gelées pendant le cycle, mises à jour en batch après (écart voulu,
          documenté dans perf_entrainement.md §3 et verrouillé par test_vec_normalize_stats_drift).
        - Callbacks rejoués step-by-step APRÈS collection avec les données réelles. Une
          callback retournant False arrête la boucle mais train() n'est jamais appelé dans ce
          cas, donc le buffer déjà rempli est ignoré — comportement acceptable.
        """
        import cloudpickle
        from copy import deepcopy
        from ai.vec_normalize_frozen import snapshot_vec_normalize, update_vec_normalize_from_trajectories, _unwrap_vec_normalize

        n_envs = subproc.num_envs
        self.policy.set_training_mode(False)
        rollout_buffer.reset()

        if use_masking and not is_masking_supported(env):
            raise ValueError(
                "Environment does not support action masking. Consider using ActionMasker wrapper"
            )

        # 1. Sérialiser la policy CPU (cloudpickle traverse les frontières de process).
        # Trois attributs d'instance bloquent deepcopy + cloudpickle :
        # - forward/_uncompiled_original_forward : closure capturant torch._dynamo.config
        #   (ConfigModuleInstance non-picklable) ; la classe fournit sa méthode à la place.
        # - action_dist : distribution laissée par le dernier evaluate_actions() de train(),
        #   ses tenseurs (logits, probs) restent attachés au graphe de calcul et Tensor.__deepcopy__
        #   refuse les non-leaf. Les workers recréent leur distribution dans _distribution_from()
        #   via make_masked_proba_distribution(action_space) si l'attribut est absent.
        _policy_attrs = vars(self.policy)
        _saved_instance_attrs: dict = {}
        for _k in ("forward", "_uncompiled_original_forward", "action_dist"):
            if _k in _policy_attrs:
                _saved_instance_attrs[_k] = _policy_attrs.pop(_k)
        policy_cpu = deepcopy(self.policy).cpu()
        _policy_attrs.update(_saved_instance_attrs)
        policy_bytes = cloudpickle.dumps(policy_cpu)

        # 2. Snapshot VecNormalize par worker.
        snapshots = [snapshot_vec_normalize(env, i) for i in range(n_envs)]

        # 3. Dispatch : tous les workers reçoivent COLLECT_TRAJECTORY simultanément.
        callback.on_rollout_start()
        assert self._last_episode_starts is not None
        initial_episode_starts = self._last_episode_starts.copy()
        trajectories = subproc.collect_trajectories(
            policy_bytes, n_rollout_steps, snapshots, initial_episode_starts
        )

        # 4. Remplir le buffer depuis les trajectoires.
        # Pré-empilement : (n_envs, n_steps, ...) par clé — remplace n_steps × n_keys np.stack par n_keys np.stack.
        obs_keys = list(trajectories[0]["norm_obs_seq"].keys())
        obs_all = {key: np.stack([traj["norm_obs_seq"][key] for traj in trajectories]) for key in obs_keys}
        # Pré-empilement raw rewards + bootstrap pour la normalisation correcte à l'étape 6.
        raw_rewards_all = np.stack([traj["raw_rewards_seq"] for traj in trajectories]).T  # (n_steps, n_envs)
        bootstrap_all = np.stack([traj["bootstrap_seq"] for traj in trajectories]).T       # (n_steps, n_envs)

        for step_idx in range(n_rollout_steps):
            obs_step = {key: obs_all[key][:, step_idx] for key in obs_keys}

            actions_step = np.array([traj["actions_seq"][step_idx] for traj in trajectories])
            # Le buffer est rempli avec les rewards brutes ; elles seront normalisées à l'étape 6
            # après la mise à jour de VecNormalize (ret_var correct disponible).
            raw_rewards_step = raw_rewards_all[step_idx]
            dones_step = np.array([traj["dones_seq"][step_idx] for traj in trajectories], dtype=bool)
            ep_starts_step = np.array([traj["episode_starts_seq"][step_idx] for traj in trajectories], dtype=bool)
            values_step = th.tensor([traj["values_seq"][step_idx] for traj in trajectories], dtype=th.float32)
            log_probs_step = th.tensor([traj["log_probs_seq"][step_idx] for traj in trajectories], dtype=th.float32)
            masks_step = np.stack([traj["masks_seq"][step_idx] for traj in trajectories])

            if isinstance(self.action_space, spaces.Discrete):
                actions_step = actions_step.reshape(-1, 1)

            rollout_buffer.add(
                obs_step,
                actions_step,
                raw_rewards_step,
                ep_starts_step,
                values_step,
                log_probs_step,
                action_masks=masks_step,
            )

        # 5. Bootstrap last_values (pas encore de GAE — rewards pas encore normalisées).
        last_obs: dict = {}
        for key in trajectories[0]["last_norm_obs"]:
            last_obs[key] = np.stack([traj["last_norm_obs"][key] for traj in trajectories])
        last_dones = np.array([traj["last_done"] for traj in trajectories], dtype=bool)

        with th.no_grad():
            last_values = self.policy.predict_values(obs_as_tensor(last_obs, self.device))  # type: ignore[arg-type]

        # Diagnostic bootstrap : comparer last_values GPU vs last_value CPU worker.
        self._diag_last_values_gpu_mean = last_values.mean().item()
        self._diag_last_values_cpu_mean = float(np.mean([traj["last_value"] for traj in trajectories]))

        # 6. Mettre à jour VecNormalize avec les données brutes, puis normaliser les rewards
        # du buffer avec le ret_var EXACT (post-update). Résout le bug cold-start : au rollout 1
        # (--new), ret_var=1.0 ferait clipper ±150 → ±10, puis _scale=0.0067 → ±0.067 au lieu
        # de ±1.0 dans le buffer. En normalisant APRÈS la mise à jour, clip(raw/√new_var) = ±1.0.
        raw_gc_batches = [traj["raw_global_cont"] for traj in trajectories]
        disc_ret_batches = [traj["discounted_returns"] for traj in trajectories]
        final_returns = [traj["final_discounted_return"] for traj in trajectories]
        update_vec_normalize_from_trajectories(env, raw_gc_batches, disc_ret_batches, final_returns)

        # Aucun re-scaling des sorties du critique (values, last_values, bootstrap). Il a existé
        # ici jusqu'au 2026-08-29 sous la forme d'un facteur sqrt(old_ret_var)/sqrt(new_ret_var),
        # qui suppose V proportionnel à 1/sqrt(ret_var) — vrai seulement à convergence. Au premier
        # rollout d'un run neuf, old_ret_var vaut 1.0 parce que RunningMeanStd vient d'être
        # initialisé, pas parce que le critique aurait appris à cette échelle : le facteur valait
        # 0.060 et écrasait ses prédictions de 17x, d'où value_loss 15.1 et explained_variance
        # -0.37 aux rollouts suivants. SB3 ne rescale jamais, et le chemin stepwise ci-dessous
        # non plus (`rewards[idx] += self.gamma * terminal_value`, brut).
        vn = _unwrap_vec_normalize(env)
        if vn is not None and vn.norm_reward:
            new_ret_var = float(vn.ret_rms.var)
            eps = float(vn.epsilon)
            clip_r = float(vn.clip_reward)
            rollout_buffer.rewards = (
                np.clip(raw_rewards_all / np.sqrt(new_ret_var + eps), -clip_r, clip_r)
                + bootstrap_all
            ).astype(np.float32)
        else:
            rollout_buffer.rewards = (raw_rewards_all + bootstrap_all).astype(np.float32)
        rollout_buffer.compute_returns_and_advantage(last_values=last_values, dones=last_dones)

        # 7. Mettre à jour l'état du learner.
        self._last_obs = last_obs  # type: ignore[assignment]
        self._last_episode_starts = last_dones

        # 8. Rejouer les callbacks step-by-step (mêmes données, même ordre).
        # num_timesteps est incrémenté ici step-by-step pour que les callbacks voient
        # la même progression que dans le chemin stepwise.
        for step_idx in range(n_rollout_steps):
            self.num_timesteps += n_envs
            step_dones = np.array([traj["dones_seq"][step_idx] for traj in trajectories], dtype=bool)
            step_infos = [traj["infos_seq"][step_idx] for traj in trajectories]
            step_actions = np.array([traj["actions_seq"][step_idx] for traj in trajectories])
            step_rewards = np.array([traj["rewards_seq"][step_idx] for traj in trajectories], dtype=np.float32)
            step_ep_wall_seconds = np.array(
                [traj["episode_wall_seconds_seq"][step_idx] for traj in trajectories], dtype=np.float64
            )
            callback.update_locals({
                "dones": step_dones,
                "infos": step_infos,
                "actions": step_actions,
                "rewards": step_rewards,
                "n_steps": step_idx + 1,
                "episode_wall_seconds": step_ep_wall_seconds,
            })
            self._update_info_buffer(step_infos, step_dones)
            if not callback.on_step():
                # Callback demande l'arrêt : buffer déjà rempli, train() ne sera pas appelé.
                return False

        callback.on_rollout_end()
        return True

    def _collect_rollouts_stepwise(
        self,
        env: VecEnv,
        callback: BaseCallback,
        rollout_buffer: MaskableRolloutBuffer | MaskableDictRolloutBuffer,
        n_rollout_steps: int,
        use_masking: bool,
    ) -> bool:
        """Phase 2.3 — collecte step-by-step (chemin des VecEnv non-MaskableSubproc)."""
        self.policy.set_training_mode(False)
        n_steps = 0
        action_masks = None
        rollout_buffer.reset()

        if use_masking and not is_masking_supported(env):
            raise ValueError(
                "Environment does not support action masking. Consider using ActionMasker wrapper"
            )

        callback.on_rollout_start()
        # Purger la clé injectée par le mode distribué (si un rollout précédent en avait posé
        # une). Sans cette purge, le callback lirait une valeur stale de l'ancien rollout.
        callback.update_locals({"episode_wall_seconds": None})

        while n_steps < n_rollout_steps:
            with th.no_grad():
                obs_tensor = obs_as_tensor(self._last_obs, self.device)  # type: ignore[arg-type]

                if use_masking:
                    action_masks = get_action_masks(env)

                actions, values, log_probs = self.policy(obs_tensor, action_masks=action_masks)

            actions = actions.cpu().numpy()
            new_obs, rewards, dones, infos = env.step(actions)

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

        rollout_buffer.compute_returns_and_advantage(last_values=values, dones=dones)  # type: ignore[possibly-unbound]
        callback.on_rollout_end()
        return True
