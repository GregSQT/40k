"""PatchedMaskablePPO — sous-classe locale de MaskablePPO pour les Phases 2 et 3 perf_entrainement.

Quatre overrides, sans changer les maths :

2.1 — _setup_model() : GpuMaskableDictRolloutBuffer pour les espaces Dict (masques en bool,
      champs compacts résidents GPU — plus de H2D par epoch pour eux). Les OBSERVATIONS, elles,
      restent en RAM et ne partent sur le device que par minibatch depuis le 2026-09-07 : leur
      résidence coûtait 3,16 GiB de VRAM en double du numpy et faisait déborder le GPU en
      mémoire système sous WSL2 — voir le docstring d'ai/gpu_rollout_buffer.py. Combiné avec
      recreate_rollout_buffer() dans train.py pour les modèles chargés.

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

import cloudpickle

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


def check_entropy_normalize_by_legal(value: Any) -> bool:
    """La cle `model_params.entropy_normalize_by_legal`, ou TypeError si elle n'est pas un booleen.

    UN SEUL refus pour les deux chemins — `--new` (constructeur) et `--append`
    (`_apply_curriculum_model_params`, ai/train.py) : `"false"` (chaine) ou `1` seraient vrais
    sous `if`, et le meme profil activerait le terme normalise dans un cas et leverait dans l'autre.
    """
    if not isinstance(value, bool):
        raise TypeError(
            f"model_params.entropy_normalize_by_legal doit etre un booleen (got {value!r})"
        )
    return value


def entropy_loss_normalized_by_legal(entropy: th.Tensor, action_masks: th.Tensor) -> th.Tensor:
    """`-mean_i(H_i / ln n_i)` sur les echantillons a n_i > 1 ; n_i = nombre d'actions LEGALES.

    RAISON D'ETRE (sonde du 2026-09-12, 6 episodes, 1 301 decisions) : `-mean(H)` est une moyenne
    DOMINEE par les etats de mouvement (194 actions legales en moyenne, ln n moyen 5,07, H mesuree
    2,23) alors que les tetes courtes sont deja effondrees — charge_slot 0,007 nat sur 0,86
    possible, shoot_slot 0,23 / 1,58, deploy_slot 0,16 / 1,95. `ent_coef` n'y pesait que 1,3 % du
    gradient et n'agissait que sur le mouvement. Rapportee a son maximum ln n_i, l'entropie de chaque etat
    vaut dans [0, 1] quel que soit son nombre d'actions : le terme est borne dans [-1, 0] et
    chaque tete pese pour sa part d'effondrement, pas pour sa taille.

    n_i = 1 : aucune decision, H_i = 0 et ln 1 = 0 — exclu de la moyenne. Le quotient est calcule
    sur `clamp(n, 2)` puis ecarte par `where`, et non l'inverse : diviser d'abord fabriquerait
    un `nan` dont le gradient traverse `th.where` (0 x inf). Aucun n_i > 1 dans le mini-lot →
    terme nul mais RELIE au graphe (gradient nul), pour que le `backward` de diagnostic par terme
    reste possible.

    `action_masks` : bool ou float 0/1, une ligne par echantillon (forme du rollout buffer).
    """
    n_legal = action_masks.reshape(entropy.shape[0], -1).to(entropy.dtype).sum(dim=1)
    valid = n_legal > 1
    log_n = th.log(n_legal.clamp(min=2.0))
    ratio = th.where(valid, entropy / log_n, th.zeros_like(entropy))
    return -ratio.sum() / valid.sum().clamp(min=1)


def _grad_norm_stats(norms: list[th.Tensor], max_norm: float) -> tuple[float, float]:
    """Moyenne des normes BRUTES et part des minibatches ou l'ecretage a mordu.

    `norms` porte les valeurs RETOURNEES par `clip_grad_norm_`, mesurees avant ecretage.
    """
    if not norms:
        return float("nan"), float("nan")
    stacked = th.stack(norms)
    return stacked.mean().item(), (stacked >= max_norm).float().mean().item()


class PatchedMaskablePPO(MaskablePPO):
    """MaskablePPO avec optimisations learner Phase 2 (GPU buffer, logging différé, single RPC)."""

    def __init__(
        self,
        *args: Any,
        entropy_normalize_by_legal: bool = False,
        value_warmup_updates: int = 0,
        **kwargs: Any,
    ) -> None:
        """`entropy_normalize_by_legal` : cle `model_params`, voir `entropy_loss_normalized_by_legal`.

        Absente (False) : le terme d'entropie de la loss reste `-mean(H)`, strictement le
        comportement anterieur — seule la publication `train/entropy_loss_normalized` s'ajoute,
        calculee sans gradient. Attribut d'instance ordinaire : SB3 le serialise dans le `data` du
        zip et le restaure au chargement ; `_apply_curriculum_model_params` (ai/train.py) le
        reapplique depuis le profil en `--append`.

        `value_warmup_updates` (B6) : nombre d'updates du run pendant lesquelles seule la value
        loss est optimisee (voir `train`). Cycle de vie DIFFERENT de la cle ci-dessus : ni la
        cle ni le compteur `_vwu_done` ne sont serialises (`_excluded_save_params`). L'echauffement
        est un regime de RUN — un `--append` le joue si et seulement si SON profil porte la cle
        (`_apply_curriculum_model_params`, ai/train.py) ; un zip sauve apres un run echauffe ne
        le rejoue pas de lui-meme. Exclure le compteur seul ne suffisait pas : la cle restauree
        au `load` et laissee en place par un profil qui ne la porte pas rejouait N updates
        critic-only en silence.
        """
        self.entropy_normalize_by_legal = check_entropy_normalize_by_legal(
            entropy_normalize_by_legal
        )
        self.value_warmup_updates: int = int(value_warmup_updates)
        self._vwu_done: int = 0
        super().__init__(*args, **kwargs)

    def _excluded_save_params(self) -> list[str]:
        return super()._excluded_save_params() + ["value_warmup_updates", "_vwu_done"]

    def _critic_modules(self) -> tuple[th.nn.Module, th.nn.Module]:
        """Les modules que l'échauffement critic (B6) laisse apprendre — la SEULE partition.

        Le tronc critic de `MlpExtractor` et la tête de valeur : les deux seuls que
        `evaluate_actions` traverse SANS que la politique les lise. Tout le reste — extracteur
        de features PARTAGÉ, tronc pi, têtes pointeur et dense — est gelé pendant le warmup :
        paramètres sans gradient (`_critic_only_param_ids`, `grad = None` avant
        `optimizer.step()`) ET mode évaluation (statistiques d'`EntityRunningNorm` figées),
        voir `train`. `ActorCriticPolicy` garantit ces deux attributs ; `PointerMaskablePolicy`
        les construit elle-même (ai/pointer_policy.py).
        """
        return self.policy.mlp_extractor.value_net, self.policy.value_net

    def _critic_only_param_ids(self) -> frozenset[int]:
        """Identités des paramètres de `_critic_modules`."""
        return frozenset(
            id(p) for m in self._critic_modules() for p in m.parameters()
        )

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
        # Entropie rapportee a ln(n legales), publiee sur TOUS les runs : c'est la seule des deux
        # qui compare des tetes de tailles differentes, et un run temoin doit la porter aussi.
        entropy_losses_normalized_t: list[th.Tensor] = []
        clip_fractions_t: list[th.Tensor] = []
        # Norme du gradient AVANT ecretage, telle que `clip_grad_norm_` la retourne. Elle est
        # deja calculee par l'appel qui ecrete : la recuperer ne coute rien, la recalculer sur
        # `p.grad` apres coup ne peut donner que min(brute, max_grad_norm).
        grad_norms_t: list[th.Tensor] = []
        # approx_kl : tenseurs si target_kl absent (pas de sync inter-minibatch) ;
        # floats si target_kl présent (early-stopping nécessite la valeur scalaire).
        approx_kl_divs_t: list[th.Tensor] = []
        approx_kl_divs: list[float] = []
        # Pas de gradient REELLEMENT executes dans l'update : incremente apres chaque
        # `optimizer.step()`, donc jamais par le mini-lot qui declenche l'early-stop KL (il fait
        # `break` avant son backward). Vaut n_epochs x ceil(n_steps x n_envs / batch_size) quand
        # les epochs vont au bout, strictement moins des qu'une coupure a eu lieu. Publie parce
        # que `train/approx_kl_max` dit SI l'update a ete coupee, jamais OU : sur
        # run_20260912-065925, 761/761 updates coupees et `train/time_update` entre 1,46 et
        # 5,61 s — la fraction d'epochs reellement apprise n'etait qu'une deduction.
        n_minibatches_done = 0
        # Diagnostic divergence GPU/CPU — à retirer après identification de la cause.
        # Capture uniquement le minibatch 0 d'epoch 0 : seul point vraiment pré-update.
        _diag_drift_norm_mb0: th.Tensor | None = None
        _diag_drift_mean_mb0: th.Tensor | None = None
        _diag_logprob_drift_mb0: th.Tensor | None = None
        _diag_ratio_mb0: th.Tensor | None = None
        # Decomposition de la norme du gradient par terme de la loss (2026-09-06). INSTRUMENT
        # PERMANENT : c'est lui qui a regle vf_coef a 0.15, et toute nouvelle lignee (x5) devra
        # refaire ce reglage, qui depend de l'echelle des recompenses et de l'etat du critic.
        # Les VALEURS de loss ne repondent pas a la question : policy_loss vaut ~0.0001 parce que
        # normalize_advantage centre les avantages et que le ratio vaut 1 au premier minibatch,
        # ce qui ne dit rien de son gradient.
        # COUT : trois `backward(retain_graph=True)` supplementaires par UPDATE — minibatch 0 de
        # l'epoch 0 seulement, pas par minibatch — plus la retention du graphe de ce minibatch
        # jusqu'au backward reel.
        _diag_grad_norms_mb0: dict[str, float] | None = None
        continue_training = True
        loss: th.Tensor = th.tensor(float("nan"))
        # Échauffement critic (B6) : les paramètres que le warmup laisse apprendre, calculés une
        # fois par update et SEULEMENT pendant le régime (voir `_critic_only_param_ids`).
        _in_warmup: bool = self._vwu_done < self.value_warmup_updates
        critic_only_param_ids: frozenset[int] = (
            self._critic_only_param_ids() if _in_warmup else frozenset()
        )
        if _in_warmup:
            # Le gel des PARAMÈTRES (grad = None, plus bas) ne fige pas les BUFFERS : en
            # `set_training_mode(True)`, chaque forward d'`EntityRunningNorm` avance ses
            # `running_mean/var/count` (ai/spatial_extractor.py, `if self.training`), donc les
            # entrées normalisées de l'extracteur partagé — et les logits de la politique avec
            # elles — bougeaient à chaque minibatch (mesuré : 9 buffers sur 16 déplacés, Δprobs
            # 4,5e-4 après une update warmup). Règle générale, dérivée de la même partition que
            # les gradients : tout ce qui est gelé est en mode évaluation, figé comme pendant
            # les rollouts ; seuls les modules critic restent en mode entraînement. Rien à
            # rétablir en sortie — `set_training_mode` (False en tête de la collecte, True en
            # tête du prochain `train`) est récursif et réécrit l'état de tous les sous-modules.
            self.policy.eval()
            for _module in self._critic_modules():
                _module.train()

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
                    if self.entropy_normalize_by_legal:
                        # Sans entropie analytique, rien a rapporter a ln n : `-log_prob` est une
                        # estimation a un echantillon, pas l'entropie de l'etat. Lever, pas retomber.
                        raise RuntimeError(
                            "entropy_normalize_by_legal exige une entropie analytique de la "
                            "politique ; evaluate_actions a rendu None."
                        )
                    entropy_loss = -th.mean(-log_prob)
                    entropy_loss_normalized = th.full((), float("nan"), device=log_prob.device)
                else:
                    entropy_loss = -th.mean(entropy)
                    if self.entropy_normalize_by_legal:
                        entropy_loss_normalized = entropy_loss_normalized_by_legal(
                            entropy, rollout_data.action_masks
                        )
                    else:
                        with th.no_grad():
                            entropy_loss_normalized = entropy_loss_normalized_by_legal(
                                entropy, rollout_data.action_masks
                            )
                # `train/entropy_loss` reste la moyenne BRUTE quel que soit le terme optimise : ses
                # lecteurs (metrics_tracker, training_callbacks, metriques.md) la lisent en nats.
                entropy_losses_t.append(entropy_loss)
                entropy_losses_normalized_t.append(entropy_loss_normalized)
                entropy_term = (
                    entropy_loss_normalized if self.entropy_normalize_by_legal else entropy_loss
                )

                # ECHAUFFEMENT CRITIC (décision B) : pendant les `value_warmup_updates`
                # premières updates du run, seul le critic s'ajuste. La politique et l'entropie
                # sont annulées (pas seulement réduites) pour éviter tout déplacement de la
                # politique pendant que le critic recalibre sa cible. Annuler les termes ne
                # suffit PAS : l'extracteur de features est PARTAGÉ (`PointerMaskablePolicy`
                # exige `share_features_extractor=True`, et ses logits `q · e_i` lisent les
                # embeddings de l'extracteur), donc la value loss seule le déplacerait, et la
                # politique avec lui — sans clip ni early-stop KL. D'où le gel plus bas : seuls
                # les paramètres du critic (`mlp_extractor.value_net` + `value_net`) gardent un
                # gradient avant `optimizer.step()`, et les statistiques d'`EntityRunningNorm`
                # sont figées (voir le gel des buffers en tête de `train`). L'early-stop KL n'est
                # pas applicable : la politique est immobile, approx_kl ne mesure que l'écart
                # numérique entre le log_prob de collecte et celui de l'update.
                if _in_warmup:
                    loss = self.vf_coef * value_loss
                else:
                    loss = policy_loss + self.ent_coef * entropy_term + self.vf_coef * value_loss

                # Norme du gradient de CHAQUE terme, pondere comme dans la loss.
                # `clip_grad_norm_` avec max_norm=inf retourne la norme sans rien ecreter.
                # retain_graph=True : trois backward successifs sur le meme graphe, libere par le
                # backward reel plus bas. Minibatch 0 / epoch 0 seulement, comme les diagnostics
                # voisins — trois backward par UPDATE, pas par minibatch.
                if epoch == 0 and _diag_grad_norms_mb0 is None:
                    _diag_grad_norms_mb0 = {}
                    for _term_name, _term in (
                        ("policy", policy_loss),
                        ("value", self.vf_coef * value_loss),
                        ("entropy", self.ent_coef * entropy_term),
                    ):
                        self.policy.optimizer.zero_grad()
                        _term.backward(retain_graph=True)
                        _diag_grad_norms_mb0[_term_name] = float(
                            th.nn.utils.clip_grad_norm_(
                                self.policy.parameters(), float("inf")
                            )
                        )
                    self.policy.optimizer.zero_grad()

                with th.no_grad():
                    approx_kl_div_t = th.mean((th.exp(log_ratio) - 1) - log_ratio)

                if self.target_kl is not None and not _in_warmup:
                    # Early-stopping exige la valeur scalaire maintenant.
                    # Désactivé pendant le warmup critic : pas de gradient de politique,
                    # approx_kl ne mesure pas une divergence de politique réelle.
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
                if _in_warmup:
                    # Gel de tout ce qui n'est pas le critic : `grad = None` fait sauter le
                    # paramètre par Adam, donc l'extracteur partagé et les têtes de politique
                    # restent identiques au bit près. La norme clippée ci-dessous ne porte alors
                    # que sur le gradient du critic (clip_grad_norm_ ignore les grads None).
                    for _param in self.policy.parameters():
                        if id(_param) not in critic_only_param_ids:
                            _param.grad = None
                grad_norms_t.append(
                    th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
                )
                self.policy.optimizer.step()
                n_minibatches_done += 1

            if not continue_training:
                break

        self._n_updates += 1
        pg_loss_mean = _mean_item(pg_losses_t)
        clip_frac_mean = _mean_item(clip_fractions_t)
        value_loss_mean = _mean_item(value_losses_t)
        entropy_loss_mean = _mean_item(entropy_losses_t)
        entropy_loss_normalized_mean = _mean_item(entropy_losses_normalized_t)
        grad_norm_mean, grad_clip_fraction = _grad_norm_stats(grad_norms_t, self.max_grad_norm)

        if approx_kl_divs_t:
            approx_kl_mean = _mean_item(approx_kl_divs_t)
        elif approx_kl_divs:
            approx_kl_mean = float(np.mean(approx_kl_divs))
        else:
            approx_kl_mean = float("nan")

        # Publié uniquement si target_kl est actif (approx_kl_divs renseigné).
        # approx_kl_max > 1.5 × target_kl  ⟺  le break a été déclenché cet update.
        approx_kl_max = float(np.max(approx_kl_divs)) if approx_kl_divs else None

        explained_var = explained_variance(
            self.rollout_buffer.values.flatten(),
            self.rollout_buffer.returns.flatten(),
        )

        self.logger.record("train/time_update", time.perf_counter() - _t0_update)
        self.logger.record("train/entropy_loss", entropy_loss_mean)
        self.logger.record("train/entropy_loss_normalized", entropy_loss_normalized_mean)
        self.logger.record("train/policy_gradient_loss", pg_loss_mean)
        self.logger.record("train/value_loss", value_loss_mean)
        self.logger.record("train/approx_kl", approx_kl_mean)
        if approx_kl_max is not None:
            self.logger.record("train/approx_kl_max", approx_kl_max)
        self.logger.record("train/clip_fraction", clip_frac_mean)
        self.logger.record("train/n_minibatches_done", n_minibatches_done)
        # Norme BRUTE, moyennee sur les minibatches de l'update, et part de ces minibatches ou
        # elle depassait `max_grad_norm`. La norme APRES ecretage n'est pas republiee : elle vaut
        # min(brute, max_grad_norm), donc elle se deduit de ces deux scalaires et de la config.
        self.logger.record("train/gradient_norm", grad_norm_mean)
        self.logger.record("train/grad_clip_fraction", grad_clip_fraction)
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
        # Decomposition de la norme du gradient par terme (cf. _diag_grad_norms_mb0).
        for _term_name in ("policy", "value", "entropy"):
            self.logger.record(
                f"diag/grad_norm_{_term_name}_mb0",
                _diag_grad_norms_mb0[_term_name]
                if _diag_grad_norms_mb0 is not None
                else _nan,
            )
        # PART du gradient qui revient a la POLITIQUE — la seule des trois tetes qui joue les
        # parties, le critic n'etant appele qu'a l'entrainement. Publiee comme une part et non
        # comme un rapport policy/value : bornee a [0, 1], elle se lit directement en pourcentage.
        # Derivee des trois normes ci-dessus, donc aucun backward supplementaire.
        # MESUREE a 0.235 le 2026-09-06 (vf_coef 0.5) ; attendue vers 0.38 a vf_coef 0.25.
        # Somme nulle = aucun gradient sur les trois termes, cas ou la part n'est pas definie :
        # NaN, comme les diagnostics voisins quand leur capture n'a pas eu lieu.
        _grad_sum = sum(_diag_grad_norms_mb0.values()) if _diag_grad_norms_mb0 is not None else 0.0
        self.logger.record(
            "diag/grad_share_policy_mb0",
            _diag_grad_norms_mb0["policy"] / _grad_sum
            if _diag_grad_norms_mb0 is not None and _grad_sum > 0.0
            else _nan,
        )
        self.logger.record("diag/returns_mean", float(self.rollout_buffer.returns.mean()))
        self.logger.record("diag/old_values_mean", float(self.rollout_buffer.values.mean()))
        self.logger.record("diag/rewards_mean", float(self.rollout_buffer.rewards.mean()))
        # Bootstrap : last_values GPU vs last_value CPU (posés par _collect_rollouts_distributed).
        self.logger.record("diag/last_values_gpu_mean", getattr(self, "_diag_last_values_gpu_mean", _nan))
        self.logger.record("diag/last_values_cpu_mean", getattr(self, "_diag_last_values_cpu_mean", _nan))
        # Echauffement critic B6 : 1 pendant les N premières updates, 0 ensuite.
        self.logger.record("train/value_warmup_active", int(_in_warmup))
        if _in_warmup:
            self._vwu_done += 1

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

    def _serialize_policy_for_workers(self) -> bytes:
        """Blob de la policy CPU envoyé aux workers, sans attribut non-picklable ni tenseur CUDA.

        Quatre attributs d'instance sont retirés avant deepcopy + cloudpickle :
        - forward/_uncompiled_original_forward : closure capturant torch._dynamo.config
          (ConfigModuleInstance non-picklable) ; la classe fournit sa méthode à la place.
        - action_dist : distribution laissée par le dernier evaluate_actions() de train(),
          ses tenseurs (logits, probs) restent attachés au graphe de calcul et Tensor.__deepcopy__
          refuse les non-leaf. Les workers recréent leur distribution dans _distribution_from()
          via make_masked_proba_distribution(action_space) si l'attribut est absent.
        - optimizer : `.cpu()` ne déplace que paramètres et buffers, jamais `optimizer.state`.
          Dès le premier `step()` d'Adam, `exp_avg`/`exp_avg_sq` restent sur cuda:0 et voyagent
          dans le blob — chaque worker ouvrait alors un contexte CUDA rien qu'en le désérialisant,
          et prenait au learner la VRAM de son buffer d'update. Le worker n'optimise rien.
        """
        policy_attrs = vars(self.policy)
        saved = {k: policy_attrs.pop(k) for k in ("forward", "_uncompiled_original_forward", "action_dist", "optimizer") if k in policy_attrs}
        policy_cpu = deepcopy(self.policy).cpu()
        policy_attrs.update(saved)
        return cloudpickle.dumps(policy_cpu)

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
        from ai.vec_normalize_frozen import snapshot_vec_normalize, update_vec_normalize_from_trajectories, _unwrap_vec_normalize

        n_envs = subproc.num_envs
        self.policy.set_training_mode(False)
        rollout_buffer.reset()

        if use_masking and not is_masking_supported(env):
            raise ValueError(
                "Environment does not support action masking. Consider using ActionMasker wrapper"
            )

        # 1. Sérialiser la policy CPU (cloudpickle traverse les frontières de process).
        policy_bytes = self._serialize_policy_for_workers()

        # 2. Snapshot VecNormalize par worker.
        snapshots = [snapshot_vec_normalize(env, i) for i in range(n_envs)]

        # 3. Dispatch : tous les workers reçoivent COLLECT_TRAJECTORY simultanément.
        callback.on_rollout_start()
        assert self._last_episode_starts is not None
        initial_episode_starts = self._last_episode_starts.copy()
        # Les observations de chaque trajectoire sont copiées dans le buffer dès sa réception, puis
        # libérées : le learner ne tient jamais plus d'UNE trajectoire d'observations hors buffer.
        # Jusqu'au 2026-09-14 il recevait la liste complète puis l'empilait (obs_all) avant de
        # remplir le buffer pas à pas : trois exemplaires des observations (3 × 3,4 Go à 32 640
        # pas), ce qui a tué le run S23 à 2 Go de RAM disponible (mem_s23_12envs, 00:08).
        obs_keys = list(rollout_buffer.observations.keys())
        trajectories: list[dict] = []
        for env_idx, traj in subproc.iter_trajectories(
            policy_bytes, n_rollout_steps, snapshots, initial_episode_starts
        ):
            norm_obs_seq = traj.pop("norm_obs_seq")
            for key in obs_keys:
                seq = norm_obs_seq[key]
                if seq.shape[0] != n_rollout_steps:
                    raise ValueError(
                        f"trajectoire de l'env {env_idx} : {seq.shape[0]} observations pour "
                        f"'{key}', {n_rollout_steps} attendues (n_rollout_steps)"
                    )
                rollout_buffer.observations[key][:, env_idx] = seq
            trajectories.append(traj)

        # 4. Remplir le buffer depuis les trajectoires.
        # Pré-empilement raw rewards + bootstrap pour la normalisation correcte à l'étape 6.
        raw_rewards_all = np.stack([traj["raw_rewards_seq"] for traj in trajectories]).T  # (n_steps, n_envs)
        bootstrap_all = np.stack([traj["bootstrap_seq"] for traj in trajectories]).T       # (n_steps, n_envs)

        for step_idx in range(n_rollout_steps):
            # Les observations sont déjà à leur place : `add` les relit depuis le buffer (copie
            # d'une ligne de n_envs obs, puis réécriture au même index — identité).
            obs_step = {key: rollout_buffer.observations[key][step_idx] for key in obs_keys}

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
