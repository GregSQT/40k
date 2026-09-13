#!/usr/bin/env python3
"""Fraction de SIGNAL des updates PPO de P1 — bruit de gradient mesuré, politique figée.

QUESTION. P1 (reprise de P0, régime `x1_lineage`, `n_steps` 8160 / `batch_size` 1020) a plafonné
contre P0 (0,547 → 0,601 entre 60 000 et 120 000 épisodes cumulés, seuil 0,65 ; run
`run_20260912-065925`, arrêté à 70 000 épisodes d'étape). Trois explications ne se distinguent
pas sur les courbes : (1) il n'y a plus de signal à récupérer — le gradient vrai est nul, le
plateau est celui de l'objectif ; (2) le signal existe mais chaque update est dominée par le bruit
d'échantillonnage, et il faut des lots plus grands ; (3) le signal est propre et le plateau vient
d'ailleurs (KL, LR, capacité). Ce script sépare les trois en mesurant, à politique FIGÉE, ce que
vaut un gradient d'update par rapport au gradient vrai.

MÉTHODE. K rollouts de la taille exacte d'une update (n_steps × n_envs, 8160 en P1), collectés
par le chemin de production (`collect_rollouts` → `_collect_rollouts_distributed`) sans jamais
appeler `optimizer.step`. Pour chaque rollout, les mini-lots de `batch_size` sont tirés par
`rollout_buffer.get(batch_size)` comme `train()`, avantages normalisés PAR mini-lot, ratio calculé
comme `train()` (≈ 1, la politique ne bouge pas), et le gradient de chaque TERME de la loss —
policy, `vf_coef` × value, `ent_coef` × entropie — est pris séparément (même décomposition que
`_diag_grad_norms_mb0` dans `ai/patched_ppo.py`). G_rollout = moyenne des gradients de mini-lots,
ce qui est exactement le pas que PPO applique à l'epoch 0.

STATISTIQUES. Avec G le gradient vrai et G_k les K gradients de rollouts indépendants :
  E‖G_k‖² = ‖G‖² + tr(Σ)/B  (B = pas par rollout), donc
  ‖G‖² SANS BIAIS = moyenne des produits scalaires ⟨G_i, G_j⟩ sur les paires i ≠ j ;
  f_B   = ‖G‖² / E‖G_rollout‖²   (part du carré de norme d'une update qui est du signal) ;
  f_mb  = ‖G‖² / E‖g_minibatch‖² (même chose pour un mini-lot) ;
  B_noise = (E‖G_rollout‖² − ‖G‖²) · B / ‖G‖² = tr(Σ)/‖G‖² (échelle de bruit du gradient,
  McCandlish et al. 2018) : le lot au-delà duquel doubler le lot n'apporte plus grand-chose.
Intervalles JACKKNIFE sur les K rollouts (± 1,96 erreur-type). Tout est donné par terme et par
groupe de paramètres (préfixe de `named_parameters()`, qui dédoublonne déjà les alias
`pi_features_extractor` / `vf_features_extractor` du features_extractor partagé).
Deux cosinus, sans biais par produits croisés entre rollouts distincts : (policy, value) sur le
features_extractor — les deux têtes tirent-elles la même représentation dans le même sens — et
(gradient façonné, gradient d'ISSUE) : le gradient d'issue est le gradient REINFORCE de ±150 sur
les seuls épisodes COMPLETS du rollout (départ et fin dans le rollout, vainqueur connu), retour
Monte-Carlo actualisé au `gamma` du modèle, avantages standardisés par mini-lot comme les autres.
Un intervalle qui contient 0 se rapporte « non mesurable à K rollouts ».

ACCEPTATION avant toute lecture : le premier rollout doit reproduire les grandeurs du run de
référence (`diag/grad_norm_*_mb0`, `train/explained_variance`, `rollout/ep_len_mean`,
`diag/returns_mean`, part d'épisodes contre le pool). Sinon le script s'arrête en code 3 : la
plomberie est fausse, les nombres qui suivraient ne mesureraient rien.

RÈGLE, écrite avant lecture :
  (1) ‖G‖² non distinguable de 0 (intervalle jackknife contenant 0) → aucun signal à récupérer
      par la taille de lot ; la branche est objectif/récompense ; lire les cosinus.
  (2) ‖G‖² > 0 et f_B < 0,1 → l'update est du bruit ; levier `batch_size` ET `n_steps`
      multipliés ensemble par le facteur que B_noise donne, `target_kl` inchangé, jugé sur
      `03_selfplay/P0`.
  (3) f_B > 0,5 → signal propre, le plateau est ailleurs.
  (4) entre les deux → rapporter les nombres.

LECTURE SEULE. Ni modèle, ni config, ni state, ni `optimizer.step`. Refuse de démarrer si un
`ai/train.py` tourne (les évaluations relisent les JSON à chaud), et vérifie en sortie que ni le
zip ni le pkl ni les JSON de l'agent n'ont bougé.

Usage :
    python3 scripts/grad_signal_probe.py --agent ArmageddonAgent_x1 --etape P1 \\
        --training-config x1_lineage --rollouts 24 --out /tmp/grad_signal_p1.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: Récompense d'issue du profil de récompenses (`situational_modifiers.win` / `lose`) ; la
#: valeur exacte est sans effet sur le cosinus (avantages standardisés), elle est gardée pour
#: que le retour affiché soit lisible dans l'échelle de la config.
OUTCOME_REWARD = 150.0
#: Quantile normal pour les intervalles jackknife.
Z_95 = 1.96
#: Seuils de la règle, fixés avant lecture.
RULE_F_NOISE = 0.1
RULE_F_CLEAN = 0.5

#: Fenêtre du run de référence `run_20260912-065925`, 253 updates dans les trois heures
#: précédant l'instantané 0,9078 (moyenne ± écart-type, min–max) : policy 0,354 ± 0,052
#: (0,25–0,59), value 0,218 ± 0,108 (0,08–0,67), entropie 0,0046 ± 0,0004, explained_variance
#: 0,889 ± 0,018 (0,82–0,93), ep_len 111,9 ± 2,2 (106–119, lissée sur 100 épisodes),
#: returns_mean 1,644 ± 0,130 (1,33–1,95). Un rollout unique de ~70 épisodes est plus dispersé
#: que la courbe lissée : les bornes ci-dessous sont les min–max de la fenêtre, élargis d'un
#: écart-type. La part contre le pool vaut 0,70 par config (ratio_start = ratio_end) ; sur ~70
#: épisodes son écart-type binomial est 0,055.
ACCEPTANCE_BOUNDS: Dict[str, Tuple[float, float]] = {
    "grad_norm_policy_mb0": (0.20, 0.65),
    "grad_norm_value_mb0": (0.06, 0.80),
    "grad_norm_entropy_mb0": (0.003, 0.007),
    "explained_variance": (0.78, 0.95),
    "ep_len_mean": (95.0, 130.0),
    "returns_mean": (1.20, 2.10),
    "pool_episode_share": (0.50, 0.90),
}


# ── Statistiques pures (numpy) ───────────────────────────────────────────────────────────────


def gram_matrix(grads: np.ndarray) -> np.ndarray:
    """Produits scalaires ⟨G_i, G_j⟩ en float64 pour K gradients (K, D)."""
    g = np.asarray(grads, dtype=np.float64)
    if g.ndim != 2:
        raise ValueError(f"grads doit être (K, D), reçu {g.shape}")
    return g @ g.T


def cross_gram_matrix(grads_a: np.ndarray, grads_b: np.ndarray) -> np.ndarray:
    """⟨A_i, B_j⟩ en float64 pour deux familles de K gradients (K, D)."""
    a = np.asarray(grads_a, dtype=np.float64)
    b = np.asarray(grads_b, dtype=np.float64)
    if a.shape != b.shape or a.ndim != 2:
        raise ValueError(f"formes incompatibles : {a.shape} vs {b.shape}")
    return a @ b.T


def off_diagonal_mean(matrix: np.ndarray) -> float:
    """Moyenne des termes i ≠ j : l'estimateur SANS BIAIS de ‖G‖² (ou de ⟨A, B⟩)."""
    m = np.asarray(matrix, dtype=np.float64)
    k = m.shape[0]
    if m.shape != (k, k) or k < 2:
        raise ValueError(f"matrice K×K avec K ≥ 2 attendue, reçu {m.shape}")
    return float((m.sum() - np.trace(m)) / (k * (k - 1)))


def diagonal_mean(matrix: np.ndarray) -> float:
    """E‖G_k‖² : moyenne des carrés de norme des rollouts."""
    m = np.asarray(matrix, dtype=np.float64)
    return float(np.trace(m) / m.shape[0])


def jackknife(stat: Callable[[np.ndarray], float], k: int) -> Dict[str, float]:
    """Estimation sur les K rollouts + intervalle jackknife (± Z_95 erreur-type).

    `stat(keep)` calcule la statistique sur le sous-ensemble d'indices `keep`. `nan` sur un
    sous-ensemble (ratio indéfini) rend un intervalle `nan`, que les lecteurs rapportent comme
    « non mesurable ».
    """
    if k < 3:
        raise ValueError(f"jackknife exige K ≥ 3 rollouts (reçu {k})")
    full_idx = np.arange(k)
    estimate = float(stat(full_idx))
    leave_one_out = np.array(
        [stat(np.delete(full_idx, i)) for i in range(k)], dtype=np.float64
    )
    if not np.all(np.isfinite(leave_one_out)) or not np.isfinite(estimate):
        return {"estimate": estimate, "se": float("nan"), "low": float("nan"), "high": float("nan")}
    se = float(np.sqrt((k - 1) / k * np.sum((leave_one_out - leave_one_out.mean()) ** 2)))
    return {"estimate": estimate, "se": se, "low": estimate - Z_95 * se, "high": estimate + Z_95 * se}


def _sub(matrix: np.ndarray, keep: np.ndarray) -> np.ndarray:
    return matrix[np.ix_(keep, keep)]


def signal_stats(gram: np.ndarray, minibatch_sq_norms: np.ndarray, batch_steps: int) -> Dict[str, Any]:
    """Toutes les grandeurs de signal d'un (terme, groupe), avec intervalles jackknife.

    `gram` : (K, K) produits scalaires des gradients de rollouts.
    `minibatch_sq_norms` : (K, M) carrés de norme des M gradients de mini-lots de chaque rollout.
    `batch_steps` : pas par rollout (B), pour B_noise.
    """
    gram = np.asarray(gram, dtype=np.float64)
    mb = np.asarray(minibatch_sq_norms, dtype=np.float64)
    k = gram.shape[0]
    if mb.shape[0] != k:
        raise ValueError(f"minibatch_sq_norms doit avoir K={k} lignes, reçu {mb.shape}")
    if batch_steps <= 0:
        raise ValueError(f"batch_steps doit être > 0, reçu {batch_steps}")

    def true_sq(keep: np.ndarray) -> float:
        return off_diagonal_mean(_sub(gram, keep))

    def rollout_sq(keep: np.ndarray) -> float:
        return diagonal_mean(_sub(gram, keep))

    def mb_sq(keep: np.ndarray) -> float:
        return float(mb[keep].mean())

    def _ratio(num: float, den: float) -> float:
        return num / den if den > 0 else float("nan")

    def f_batch(keep: np.ndarray) -> float:
        return _ratio(true_sq(keep), rollout_sq(keep))

    def f_mb(keep: np.ndarray) -> float:
        return _ratio(true_sq(keep), mb_sq(keep))

    def b_noise(keep: np.ndarray) -> float:
        t = true_sq(keep)
        return (rollout_sq(keep) - t) * batch_steps / t if t > 0 else float("nan")

    true = jackknife(true_sq, k)
    # « distinguable de 0 » = borne basse de l'intervalle jackknife strictement positive.
    signal_detected = bool(np.isfinite(true["low"]) and true["low"] > 0.0)
    return {
        "rollouts": int(k),
        "batch_steps": int(batch_steps),
        "true_sq": true,
        "rollout_sq": jackknife(rollout_sq, k),
        "minibatch_sq": jackknife(mb_sq, k),
        "f_batch": jackknife(f_batch, k),
        "f_minibatch": jackknife(f_mb, k),
        "b_noise": jackknife(b_noise, k),
        "signal_detected": signal_detected,
    }


def cosine_stats(cross_gram: np.ndarray, gram_a: np.ndarray, gram_b: np.ndarray) -> Dict[str, Any]:
    """Cosinus SANS BIAIS entre deux familles de gradients, par produits croisés i ≠ j.

    cos = mean_{i≠j}⟨A_i, B_j⟩ / sqrt(‖A‖²_unb · ‖B‖²_unb). Une norme sans biais ≤ 0 rend `nan`
    (non mesurable) ; `measurable` est faux dès que l'intervalle contient 0 ou n'existe pas.
    """
    cross = np.asarray(cross_gram, dtype=np.float64)
    ga = np.asarray(gram_a, dtype=np.float64)
    gb = np.asarray(gram_b, dtype=np.float64)
    k = cross.shape[0]
    if cross.shape != (k, k) or ga.shape != (k, k) or gb.shape != (k, k):
        raise ValueError("cross_gram, gram_a, gram_b doivent être trois matrices K×K")

    def cos(keep: np.ndarray) -> float:
        a = off_diagonal_mean(_sub(ga, keep))
        b = off_diagonal_mean(_sub(gb, keep))
        if a <= 0 or b <= 0:
            return float("nan")
        return off_diagonal_mean(_sub(cross, keep)) / float(np.sqrt(a * b))

    est = jackknife(cos, k)
    # Un quotient de quantités SANS BIAIS n'est pas borné : un intervalle qui sort de [-1, 1]
    # dit que les normes sous-jacentes sont trop bruitées pour que le cosinus veuille dire
    # quelque chose.
    measurable = bool(
        np.isfinite(est["low"]) and np.isfinite(est["high"])
        and -1.0 <= est["low"] and est["high"] <= 1.0
        and (est["low"] > 0 or est["high"] < 0)
    )
    return {"rollouts": int(k), "cosine": est, "measurable": measurable}


def apply_rule(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Applique la règle écrite avant lecture au terme policy global. Rend {branch, text, factor}."""
    true = stats["true_sq"]
    f_b = stats["f_batch"]
    b_noise = stats["b_noise"]
    batch_steps = int(stats["batch_steps"])
    if not stats["signal_detected"]:
        return {
            "branch": 1,
            "text": (
                "‖G‖² non distinguable de 0 (intervalle jackknife "
                f"[{true['low']:.3g}, {true['high']:.3g}]) : aucun signal à récupérer par la "
                "taille de lot ; branche objectif/récompense ; lire les cosinus."
            ),
            "factor": None,
        }
    if f_b["estimate"] < RULE_F_NOISE:
        factor = b_noise["estimate"] / batch_steps
        return {
            "branch": 2,
            "text": (
                f"‖G‖² > 0 et f_{batch_steps} = {f_b['estimate']:.3f} < {RULE_F_NOISE} : l'update "
                f"est du bruit. B_noise = {b_noise['estimate']:.0f} pas → batch_size ET n_steps "
                f"× {factor:.1f} ensemble, target_kl inchangé, jugé sur 03_selfplay/P0."
            ),
            "factor": float(factor),
        }
    if f_b["estimate"] > RULE_F_CLEAN:
        return {
            "branch": 3,
            "text": (
                f"f_{batch_steps} = {f_b['estimate']:.3f} > {RULE_F_CLEAN} : signal propre, le "
                "plateau est ailleurs (KL, LR, capacité, objectif)."
            ),
            "factor": None,
        }
    return {
        "branch": 4,
        "text": (
            f"f_{batch_steps} = {f_b['estimate']:.3f} entre {RULE_F_NOISE} et {RULE_F_CLEAN} : "
            f"rapporter les nombres (B_noise = {b_noise['estimate']:.0f} pas, "
            f"f_mb = {stats['f_minibatch']['estimate']:.3f})."
        ),
        "factor": None,
    }


def outcome_returns(
    episode_starts: np.ndarray, dones: np.ndarray, outcome_at_done: np.ndarray, gamma: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Retour Monte-Carlo d'issue par pas, sur les seuls épisodes COMPLETS du rollout.

    Tableaux (T, N), disposition du rollout buffer SB3 : `episode_starts[t]` dit que le pas t
    ouvre un épisode, `dones[t]` qu'il le ferme, `outcome_at_done[t]` vaut ±OUTCOME_REWARD (ou 0,
    nul) au pas de fin et 0 ailleurs. Un épisode est complet s'il commence ET finit dans le
    rollout ; les autres pas (queue d'un épisode ouvert avant, tête d'un épisode non fini) sont
    marqués invalides. Retour au pas t d'un épisode fini en t_end : outcome · gamma^(t_end − t).
    """
    starts = np.asarray(episode_starts, dtype=bool)
    ends = np.asarray(dones, dtype=bool)
    outcome = np.asarray(outcome_at_done, dtype=np.float64)
    if not (starts.shape == ends.shape == outcome.shape) or starts.ndim != 2:
        raise ValueError(f"trois tableaux (T, N) attendus : {starts.shape}, {ends.shape}, {outcome.shape}")
    if not 0.0 < gamma <= 1.0:
        raise ValueError(f"gamma doit être dans ]0, 1], reçu {gamma}")
    n_steps, n_envs = starts.shape
    returns = np.zeros((n_steps, n_envs), dtype=np.float64)
    valid = np.zeros((n_steps, n_envs), dtype=bool)
    for env in range(n_envs):
        t = 0
        while t < n_steps:
            if not starts[t, env]:
                # Queue d'un épisode ouvert avant le rollout : invalide jusqu'à sa fin.
                t += 1
                continue
            t_start = t
            t_end = -1
            while t < n_steps:
                if ends[t, env]:
                    t_end = t
                    t += 1
                    break
                t += 1
            if t_end < 0:
                break  # épisode non fini dans le rollout : ses pas restent invalides
            span = np.arange(t_start, t_end + 1)
            returns[span, env] = outcome[t_end, env] * gamma ** (t_end - span)
            valid[span, env] = True
    return returns, valid


def swap_and_flatten(arr: np.ndarray) -> np.ndarray:
    """(T, N, ...) → (T·N, ...), même disposition que `RolloutBuffer.swap_and_flatten`."""
    shape = arr.shape
    return arr.swapaxes(0, 1).reshape(shape[0] * shape[1], *shape[2:])


# ── Groupes de paramètres et gradients (torch) ───────────────────────────────────────────────


def parameter_groups(named_params: Sequence[Tuple[str, Any]]) -> Tuple[List[Any], Dict[str, Tuple[int, int]], int]:
    """Paramètres dans l'ordre de `named_parameters()` et tranches [début, fin) du vecteur plat.

    Un groupe = premier segment du nom (`features_extractor`, `mlp_extractor`, `*_query_net`,
    `charge_pair_net`, `move_*_net`, `action_net`, `value_net`, …). `named_parameters()` ne rend
    chaque tenseur qu'une fois, donc les alias (`pi_features_extractor`, `vf_features_extractor`)
    ne sont pas comptés ; un groupe ne peut pas être scindé (les paramètres d'un module sont
    contigus dans l'énumération), ce qui est vérifié.
    """
    params: List[Any] = []
    groups: Dict[str, Tuple[int, int]] = {}
    seen_ids: set = set()
    offset = 0
    last_group: Optional[str] = None
    for name, tensor in named_params:
        if id(tensor) in seen_ids:
            raise ValueError(f"paramètre en double dans l'énumération : {name}")
        seen_ids.add(id(tensor))
        group = name.split(".", 1)[0]
        n = int(tensor.numel())
        if group in groups:
            if last_group != group:
                raise ValueError(f"groupe {group} non contigu dans named_parameters()")
            start, _ = groups[group]
            groups[group] = (start, offset + n)
        else:
            groups[group] = (offset, offset + n)
        last_group = group
        params.append(tensor)
        offset += n
    return params, groups, offset


def flat_grad(loss: Any, params: Sequence[Any], retain_graph: bool) -> Any:
    """Gradient de `loss` par rapport à `params`, aplati en un vecteur (zéros pour les inutilisés)."""
    import torch as th

    grads = th.autograd.grad(loss, list(params), retain_graph=retain_graph, allow_unused=True)
    pieces = []
    for p, g in zip(params, grads, strict=True):
        pieces.append(th.zeros_like(p).reshape(-1) if g is None else g.reshape(-1))
    return th.cat(pieces)


def group_sq_norms(flat: Any, groups: Dict[str, Tuple[int, int]]) -> Dict[str, float]:
    """Carré de norme par groupe d'un gradient plat (+ « all »)."""
    out = {"all": float(flat.double().pow(2).sum().item())}
    for name, (start, end) in groups.items():
        out[name] = float(flat[start:end].double().pow(2).sum().item())
    return out


def minibatch_term_losses(model: Any, rollout_data: Any, outcome_adv: Any, outcome_valid: Any) -> Dict[str, Any]:
    """Les termes de la loss PPO d'un mini-lot, comme `PatchedMaskablePPO.train` les calcule.

    `outcome_adv` / `outcome_valid` : avantage d'issue standardisé sur les pas valides du
    mini-lot et masque des pas valides, alignés sur `rollout_data`. Le terme d'issue est un
    REINFORCE clipé de même forme que le terme policy, moyenné sur les seuls pas valides.
    """
    import torch as th
    import torch.nn.functional as F
    from gymnasium import spaces

    from ai.patched_ppo import entropy_loss_normalized_by_legal

    actions = rollout_data.actions
    if isinstance(model.action_space, spaces.Discrete):
        actions = rollout_data.actions.long().flatten()
    values, log_prob, entropy = model.policy.evaluate_actions(
        rollout_data.observations, actions, action_masks=rollout_data.action_masks
    )
    values = values.flatten()
    clip_range = model.clip_range(model._current_progress_remaining)

    advantages = rollout_data.advantages
    if model.normalize_advantage:
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
    ratio = th.exp(log_prob - rollout_data.old_log_prob)
    clipped = th.clamp(ratio, 1 - clip_range, 1 + clip_range)
    policy_loss = -th.min(advantages * ratio, advantages * clipped).mean()

    if model.clip_range_vf is None:
        values_pred = values
    else:
        clip_vf = model.clip_range_vf(model._current_progress_remaining)
        values_pred = rollout_data.old_values + th.clamp(
            values - rollout_data.old_values, -clip_vf, clip_vf
        )
    value_loss = F.mse_loss(rollout_data.returns, values_pred)

    if entropy is None:
        raise RuntimeError("evaluate_actions a rendu une entropie None : rien à décomposer.")
    entropy_loss = -th.mean(entropy)
    entropy_term = (
        entropy_loss_normalized_by_legal(entropy, rollout_data.action_masks)
        if model.entropy_normalize_by_legal
        else entropy_loss
    )

    n_valid = outcome_valid.sum().clamp(min=1)
    outcome_loss = -(outcome_valid * th.min(outcome_adv * ratio, outcome_adv * clipped)).sum() / n_valid
    return {
        "policy": policy_loss,
        "value": model.vf_coef * value_loss,
        "entropy": model.ent_coef * entropy_term,
        "outcome": outcome_loss,
    }


TERMS = ("policy", "value", "entropy", "outcome")


# ── Plomberie P1 (briques d'ai/train.py) ─────────────────────────────────────────────────────


def refuse_if_training_runs() -> None:
    """Un `ai/train.py` en cours relit les JSON de config à chaud : on ne charge rien à côté."""
    result = subprocess.run(["pgrep", "-af", "ai/train.py"], capture_output=True, text=True, check=False)
    lines = [ln for ln in result.stdout.splitlines() if "pgrep" not in ln]
    if lines:
        raise RuntimeError("un entraînement tourne (`pgrep -af ai/train.py`) :\n" + "\n".join(lines))


def snapshot_mtimes(paths: Sequence[Path]) -> Dict[str, float]:
    return {str(p): p.stat().st_mtime_ns for p in paths if p.exists()}


def build_probe_context(agent: str, stage_name: str, training_config_name: str, resolution: int,
                        device: str, log: Callable[[str], None]) -> Dict[str, Any]:
    """L'environnement et le modèle EXACTS de l'étape, par les briques d'ai/train.py.

    Même ordre que `main()` → `_prepare_curriculum_stage` → `train_with_scenario_rotation`,
    sans les effets de bord d'un run : ni `prepare_run_artifacts` (contrat, archivage, run-meta),
    ni `attach_run_logger` (dossier TensorBoard), ni callbacks d'entraînement.
    """
    from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX, get_config_loader

    os.environ["W40K_BOARD_PATH"] = BOARD_DIR_BY_INCHES_TO_SUBHEX[resolution]

    import ai.train as T
    from ai.curriculum import (
        get_stage_hp_overrides, load_curriculum, require_stage, stage_init_source,
    )
    from ai.training_utils import get_scenario_list_for_phase, make_training_env, setup_imports
    from ai.unit_registry import UnitRegistry
    from ai.vec_normalize_utils import get_vec_normalize_path, load_vec_normalize
    from engine.episode_schedule import episodes_per_env
    from shared.data_validation import require_key, require_present

    config = get_config_loader()
    curriculum = load_curriculum(agent)
    stage = require_stage(curriculum, stage_name)
    canonical_path = T.build_agent_model_path(config.get_models_root(), agent)
    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"modèle canonique absent : {canonical_path}")
    warm_start = stage_init_source(stage) is not None
    if not warm_start:
        raise ValueError(f"étape {stage_name} : init 'new', rien à reprendre — la sonde mesure une reprise.")
    T._install_stage_config_overrides(
        config, agent, T._stage_opponent_mix(curriculum, stage, canonical_path),
        get_stage_hp_overrides(stage), warm_start, stage_label=stage_name,
    )
    training_config = config.load_agent_training_config(agent, training_config_name)

    scenario_list = get_scenario_list_for_phase(config, agent, training_config_name, scenario_type="bot")
    if not scenario_list:
        raise FileNotFoundError(f"aucun scénario bot pour {agent}/{training_config_name}")
    unit_registry = UnitRegistry()
    scenario_list = T._apply_wall_ref_weighting(scenario_list=scenario_list, training_config=training_config)
    scenario_list = T._apply_training_hard_weights(scenario_list=scenario_list, training_config=training_config)
    seat_mode = require_key(training_config, "agent_seat_mode")
    scenario_list = T._apply_unit_rule_forcing_weights(
        scenario_list=scenario_list, training_config=training_config,
        unit_registry=unit_registry, controlled_player_mode=seat_mode,
    )
    n_envs = T._resolve_n_envs_for_step_logging(require_key(training_config, "n_envs"), log=log)
    total_episodes = require_key(training_config, "total_episodes")
    training_config = T.resolve_run_budget(training_config, n_envs, total_episodes)
    T.resolve_turn_step_limit(scenario_list, training_config, True, log)
    episode_offset = T.resume_episode_offset(canonical_path, True)
    if episode_offset <= 0:
        raise ValueError(f"run_state sans épisodes joués pour {canonical_path}")
    episode_start_index = episodes_per_env(episode_offset, n_envs)

    _W40KEngine, register_environment = setup_imports()
    register_environment()
    opponents = T.build_training_opponents(training_config, True, total_episodes, log)
    if opponents["opponent_mix_config"] is None:
        raise ValueError(f"étape {stage_name} sans pool : la sonde mesure une étape reprise contre son pool.")
    vec_norm_cfg = require_key(training_config, "vec_normalize")
    if require_key(vec_norm_cfg, "enabled") is not True:
        raise ValueError("vec_normalize.enabled doit être vrai : la sonde reproduit un run normalisé.")
    vec_norm_eval_enabled = bool(require_key(require_key(training_config, "vec_normalize_eval"), "enabled"))
    env = T.register_vec_env(T.MaskableSubprocVecEnv([
        make_training_env(
            rank=i,
            scenario_file=scenario_list[0],
            rewards_config_name=agent,
            training_config_name=training_config_name,
            controlled_agent_key=agent,
            unit_registry=unit_registry,
            step_logger_enabled=False,
            scenario_files=scenario_list,
            debug_mode=False,
            use_bots=True,
            training_bots=opponents["training_bots"],
            agent_seat_mode=require_present(opponents["agent_seat_mode"], "agent_seat_mode"),
            agent_seat_p2_ratio=opponents["agent_seat_p2_ratio"],
            global_seed=opponents["agent_seat_seed"],
            opponent_mix_config=opponents["opponent_mix_config"],
            n_envs=n_envs,
            episode_start_index=episode_start_index,
            vec_normalize_enabled=True,
            vec_normalize_eval_enabled=vec_norm_eval_enabled,
            deploy_active_ratio_start=T.parent_deploy_active_ratio_start(training_config),
            total_episodes=T.parent_total_episodes(training_config),
        )
        for i in range(n_envs)
    ]))
    # Stats du checkpoint, FIGÉES (training=False) : `load_vec_normalize` force aussi
    # norm_reward=False, qui fausserait l'échelle des retours ; le run normalise les récompenses
    # (cf. `_apply_vec_normalize`), on le rétablit.
    vec_env = load_vec_normalize(env, canonical_path)
    if vec_env is None:
        raise FileNotFoundError(f"stats VecNormalize absentes : {get_vec_normalize_path(canonical_path)}")
    vec_env.norm_reward = bool(require_key(vec_norm_cfg, "norm_reward"))
    if vec_env.training:
        raise RuntimeError("VecNormalize.training doit rester faux : la sonde ne met à jour aucune statistique.")

    model_params = dict(require_key(training_config, "model_params"))
    T.apply_rollout_n_steps(model_params, n_envs, vec_env.observation_space, log=log)
    model_params = T._model_params_with_ent_coef_frozen(model_params, log=log)
    model = T._load_checkpoint(canonical_path, vec_env, device)
    # Le checkpoint est mesuré TEL QUEL ; il doit porter les hyperparamètres du profil, sinon la
    # mesure ne serait pas celle du run (refus explicite, jamais une réécriture silencieuse).
    mismatches = []
    for key in ("n_steps", "batch_size", "vf_coef", "ent_coef", "gamma", "gae_lambda", "normalize_advantage"):
        expected = model_params[key]
        actual = getattr(model, key)
        if actual != expected:
            mismatches.append(f"{key}: checkpoint={actual!r} profil={expected!r}")
    if mismatches:
        raise RuntimeError("hyperparamètres du checkpoint ≠ profil " + training_config_name + " : " + "; ".join(mismatches))
    if model.rollout_buffer.buffer_size != model.n_steps or model.rollout_buffer.n_envs != n_envs:
        raise RuntimeError(
            f"rollout buffer {model.rollout_buffer.buffer_size}×{model.rollout_buffer.n_envs} ≠ "
            f"n_steps {model.n_steps} × n_envs {n_envs}"
        )
    return {
        "config": config,
        "training_config": training_config,
        "canonical_path": canonical_path,
        "vec_normalize_path": get_vec_normalize_path(canonical_path),
        "scenario_list": scenario_list,
        "n_envs": n_envs,
        "episode_offset": episode_offset,
        "episode_start_index": episode_start_index,
        "env": vec_env,
        "model": model,
        "pool_labels": [m["label"] for m in require_key(opponents["opponent_mix_config"], "pool")],
    }


def make_recorder(n_envs: int) -> Any:
    """Callback SB3 minimal : `dones` et l'issue de chaque épisode fini, pas par pas.

    Construit ici et non au niveau du module pour ne pas importer SB3 au chargement (les tests
    des statistiques n'en ont pas besoin).
    """
    from stable_baselines3.common.callbacks import BaseCallback

    from engine.constants import DRAW_WINNER
    from shared.data_validation import require_key

    class _Recorder(BaseCallback):
        def __init__(self) -> None:
            super().__init__(verbose=0)
            self.reset_rollout()

        def reset_rollout(self) -> None:
            self.dones: List[np.ndarray] = []
            self.outcomes: List[np.ndarray] = []
            self.episodes_total = 0
            self.episodes_pool = 0
            self.episodes_no_winner = 0
            self.episode_lengths: List[int] = []

        def _on_rollout_start(self) -> None:
            self.reset_rollout()

        def _on_step(self) -> bool:
            dones = np.asarray(self.locals["dones"], dtype=bool)
            infos = self.locals["infos"]
            if dones.shape != (n_envs,):
                raise ValueError(f"dones de forme {dones.shape}, {n_envs} envs attendus")
            outcome = np.zeros(n_envs, dtype=np.float64)
            for env_idx in np.flatnonzero(dones):
                info = infos[env_idx]
                self.episodes_total += 1
                if require_key(info, "opponent_mode") == "self_play":
                    self.episodes_pool += 1
                self.episode_lengths.append(int(require_key(info, "episode")["l"]))
                winner = require_key(info, "winner")
                controlled = int(require_key(info, "controlled_player"))
                if winner is None:
                    self.episodes_no_winner += 1
                elif int(winner) == DRAW_WINNER:
                    outcome[env_idx] = 0.0
                elif int(winner) == controlled:
                    outcome[env_idx] = OUTCOME_REWARD
                else:
                    outcome[env_idx] = -OUTCOME_REWARD
            self.dones.append(dones)
            self.outcomes.append(outcome)
            return True

        def arrays(self) -> Tuple[np.ndarray, np.ndarray]:
            return np.stack(self.dones), np.stack(self.outcomes)

    return _Recorder()


def check_acceptance(observed: Dict[str, float]) -> List[str]:
    """Écarts au run de référence sur le premier rollout ; vide = plomberie acceptée."""
    failures = []
    for key, (low, high) in ACCEPTANCE_BOUNDS.items():
        value = observed[key]
        if not (np.isfinite(value) and low <= value <= high):
            failures.append(f"{key} = {value:.4g} hors [{low}, {high}]")
    return failures


def measure(ctx: Dict[str, Any], rollouts: int, log: Callable[[str], None],
            permutation_seed: int) -> Dict[str, Any]:
    """K rollouts à politique figée, gradients par terme et par mini-lot, puis statistiques."""
    import torch as th
    from stable_baselines3.common.logger import configure as configure_sb3_logger
    from stable_baselines3.common.utils import explained_variance

    model = ctx["model"]
    env = ctx["env"]
    n_envs = int(ctx["n_envs"])
    n_steps = int(model.n_steps)
    batch_steps = n_steps * n_envs
    batch_size = int(model.batch_size)
    if batch_steps % batch_size != 0:
        raise ValueError(f"{batch_steps} pas ne se découpent pas en mini-lots de {batch_size}")
    n_minibatches = batch_steps // batch_size

    model.set_logger(configure_sb3_logger(ctx["workdir"], ["stdout"]))
    recorder = make_recorder(n_envs)
    _total, callback = model._setup_learn(rollouts * batch_steps, recorder)

    params, groups, n_params = parameter_groups(list(model.policy.named_parameters()))
    log(f"📐 {n_params:,} paramètres uniques en {len(groups)} groupes : {', '.join(groups)}")
    group_names = ["all", *groups]
    fe_slice = groups.get("features_extractor")
    if fe_slice is None:
        raise KeyError("groupe features_extractor absent de named_parameters()")

    # Gradients de rollouts (moyenne des mini-lots), sur CPU : (K, D) par terme.
    rollout_grads = {term: np.zeros((rollouts, n_params), dtype=np.float32) for term in TERMS}
    # Carrés de norme des gradients de mini-lots : (K, M) par terme et par groupe.
    mb_sq = {term: {g: np.zeros((rollouts, n_minibatches)) for g in group_names} for term in TERMS}
    rollout_log: List[Dict[str, Any]] = []
    acceptance: Dict[str, Any] = {}

    for k in range(rollouts):
        t0 = time.perf_counter()
        ok = model.collect_rollouts(env, callback, model.rollout_buffer, n_rollout_steps=n_steps)
        if not ok:
            raise RuntimeError("collect_rollouts a rendu False")
        buf = model.rollout_buffer
        t_collect = time.perf_counter() - t0

        dones, outcome_at_done = recorder.arrays()
        if dones.shape != (n_steps, n_envs):
            raise RuntimeError(f"recorder : {dones.shape} ≠ ({n_steps}, {n_envs})")
        episode_starts = np.asarray(buf.episode_starts, dtype=bool).reshape(n_steps, n_envs).copy()
        returns_tn, valid_tn = outcome_returns(episode_starts, dones, outcome_at_done, float(model.gamma))
        returns_flat = swap_and_flatten(returns_tn)
        valid_flat = swap_and_flatten(valid_tn)
        ev = float(explained_variance(buf.values.flatten(), buf.returns.flatten()))
        returns_mean = float(buf.returns.mean())
        ep_len_mean = float(np.mean(recorder.episode_lengths)) if recorder.episode_lengths else float("nan")
        pool_share = recorder.episodes_pool / recorder.episodes_total if recorder.episodes_total else float("nan")

        # Même permutation que `get()` : le générateur global numpy est réensemencé juste avant
        # l'appel, et l'alignement est VÉRIFIÉ mini-lot par mini-lot sur les avantages.
        seed_k = permutation_seed + k
        perm = np.random.RandomState(seed_k).permutation(batch_steps)
        np.random.seed(seed_k)
        model.policy.set_training_mode(True)
        acc = {term: th.zeros(n_params, device=model.device, dtype=th.float32) for term in TERMS}
        mb0_norms: Dict[str, float] = {}
        t1 = time.perf_counter()
        for m, rollout_data in enumerate(buf.get(batch_size)):
            idx = perm[m * batch_size:(m + 1) * batch_size]
            expected_adv = buf.to_torch(buf.advantages[idx].flatten())
            if not th.equal(rollout_data.advantages, expected_adv):
                raise RuntimeError(f"rollout {k} mini-lot {m} : permutation de get() non reproduite")
            valid = th.as_tensor(valid_flat[idx], device=model.device, dtype=th.float32)
            raw = th.as_tensor(returns_flat[idx], device=model.device, dtype=th.float32)
            n_valid = valid.sum()
            if n_valid > 1:
                mean = (raw * valid).sum() / n_valid
                std = th.sqrt((((raw - mean) ** 2) * valid).sum() / n_valid)
                outcome_adv = (raw - mean) / (std + 1e-8) * valid
            else:
                outcome_adv = th.zeros_like(raw)
            losses = minibatch_term_losses(model, rollout_data, outcome_adv, valid)
            for t_i, term in enumerate(TERMS):
                g = flat_grad(losses[term], params, retain_graph=t_i < len(TERMS) - 1)
                acc[term] += g
                norms = group_sq_norms(g, groups)
                for gname in group_names:
                    mb_sq[term][gname][k, m] = norms[gname]
                if m == 0:
                    mb0_norms[term] = float(np.sqrt(norms["all"]))
        model.policy.set_training_mode(False)
        for term in TERMS:
            rollout_grads[term][k] = (acc[term] / n_minibatches).cpu().numpy()
        del acc
        t_grad = time.perf_counter() - t1

        entry = {
            "rollout": k,
            "collect_s": t_collect,
            "grad_s": t_grad,
            "episodes": recorder.episodes_total,
            "episodes_pool": recorder.episodes_pool,
            "episodes_no_winner": recorder.episodes_no_winner,
            "valid_outcome_steps": int(valid_tn.sum()),
            "grad_norm_policy_mb0": mb0_norms["policy"],
            "grad_norm_value_mb0": mb0_norms["value"],
            "grad_norm_entropy_mb0": mb0_norms["entropy"],
            "grad_norm_outcome_mb0": mb0_norms["outcome"],
            "explained_variance": ev,
            "ep_len_mean": ep_len_mean,
            "returns_mean": returns_mean,
            "pool_episode_share": pool_share,
        }
        rollout_log.append(entry)
        log(
            f"🎲 rollout {k + 1}/{rollouts} : collecte {t_collect:.0f}s, gradients {t_grad:.0f}s, "
            f"{recorder.episodes_total} épisodes ({recorder.episodes_pool} vs pool, "
            f"{recorder.episodes_no_winner} sans vainqueur), mb0 policy {mb0_norms['policy']:.3f} "
            f"value {mb0_norms['value']:.3f} entropy {mb0_norms['entropy']:.4f} outcome "
            f"{mb0_norms['outcome']:.3f}, EV {ev:.3f}, ep_len {ep_len_mean:.1f}, returns {returns_mean:.3f}, "
            f"part pool {pool_share:.2f}"
        )
        if k == 0:
            failures = check_acceptance(entry)
            acceptance = {"passed": not failures, "failures": failures, "observed": entry}
            if failures:
                log("⛔ ACCEPTATION REFUSÉE — plomberie à corriger avant toute lecture :\n  " + "\n  ".join(failures))
                return {"acceptance": acceptance, "rollouts": rollout_log, "terms": {}, "cosines": {}, "verdict": None}
            log("✅ acceptation : le premier rollout reproduit le run de référence")

    # Statistiques par terme et par groupe.
    grams: Dict[str, Dict[str, np.ndarray]] = {}
    terms_out: Dict[str, Any] = {}
    for term in TERMS:
        grams[term] = {"all": gram_matrix(rollout_grads[term])}
        for gname, (start, end) in groups.items():
            grams[term][gname] = gram_matrix(rollout_grads[term][:, start:end])
        terms_out[term] = {
            gname: signal_stats(grams[term][gname], mb_sq[term][gname], batch_steps) for gname in group_names
        }
    start, end = fe_slice
    cosines = {
        "policy_value_features_extractor": cosine_stats(
            cross_gram_matrix(rollout_grads["policy"][:, start:end], rollout_grads["value"][:, start:end]),
            grams["policy"]["features_extractor"], grams["value"]["features_extractor"],
        ),
        "policy_outcome_all": cosine_stats(
            cross_gram_matrix(rollout_grads["policy"], rollout_grads["outcome"]),
            grams["policy"]["all"], grams["outcome"]["all"],
        ),
    }
    for gname, (start, end) in groups.items():
        cosines[f"policy_outcome_{gname}"] = cosine_stats(
            cross_gram_matrix(rollout_grads["policy"][:, start:end], rollout_grads["outcome"][:, start:end]),
            grams["policy"][gname], grams["outcome"][gname],
        )
    verdict = apply_rule(terms_out["policy"]["all"])
    return {
        "acceptance": acceptance,
        "rollouts": rollout_log,
        "n_params": n_params,
        "groups": {g: list(s) for g, s in groups.items()},
        "batch_steps": batch_steps,
        "batch_size": batch_size,
        "terms": terms_out,
        "cosines": cosines,
        "verdict": verdict,
    }


def _fmt(stat: Dict[str, float], digits: int = 3) -> str:
    e = stat["estimate"]
    if not np.isfinite(e):
        return "n/a"
    if not np.isfinite(stat["low"]):
        return f"{e:.{digits}g} [n/a]"
    return f"{e:.{digits}g} [{stat['low']:.{digits}g}, {stat['high']:.{digits}g}]"


def render_report(result: Dict[str, Any]) -> str:
    """Tableau lisible : par terme, ligne globale puis groupes ; cosinus ; verdict."""
    lines: List[str] = []
    if not result["terms"]:
        return "acceptation refusée : " + "; ".join(result["acceptance"]["failures"])
    b = result["batch_steps"]
    for term in TERMS:
        lines.append(f"\n== terme {term} ==")
        lines.append(f"{'groupe':28s} {'‖G‖² sans biais':>28s} {'f_' + str(b):>26s} {'f_' + str(result['batch_size']):>26s} {'B_noise':>28s}")
        for gname, st in result["terms"][term].items():
            lines.append(
                f"{gname:28s} {_fmt(st['true_sq']):>28s} {_fmt(st['f_batch']):>26s} "
                f"{_fmt(st['f_minibatch']):>26s} {_fmt(st['b_noise'], 4):>28s}"
            )
    lines.append("\n== cosinus (sans biais, produits croisés) ==")
    for name, c in result["cosines"].items():
        tag = "" if c["measurable"] else f"  ← non mesurable à K={c['rollouts']}"
        lines.append(f"{name:40s} {_fmt(c['cosine'])}{tag}")
    v = result["verdict"]
    lines.append(f"\n== verdict : branche ({v['branch']}) ==\n{v['text']}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", default="ArmageddonAgent_x1")
    parser.add_argument("--etape", default="P1")
    parser.add_argument("--training-config", default="x1_lineage")
    parser.add_argument("--resolution", type=int, choices=[1, 5, 10], default=1)
    parser.add_argument("--rollouts", type=int, default=24, help="K rollouts (≥ 3)")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--permutation-seed", type=int, default=20260913)
    parser.add_argument("--workdir", default=None, help="dossier de travail (logger SB3) ; temporaire sinon")
    parser.add_argument("--out", default=None, help="JSON de résultat (défaut : <workdir>/grad_signal_probe.json)")
    args = parser.parse_args(argv)
    if args.rollouts < 3:
        parser.error("--rollouts ≥ 3 (jackknife)")

    def log(message: str) -> None:
        print(message, flush=True)

    refuse_if_training_runs()
    import torch as th

    if args.device.startswith("cuda") and not th.cuda.is_available():
        raise RuntimeError("--device cuda demandé mais CUDA indisponible")
    workdir = args.workdir or tempfile.mkdtemp(prefix="grad_signal_probe_")
    os.makedirs(workdir, exist_ok=True)
    out_path = args.out or os.path.join(workdir, "grad_signal_probe.json")

    import ai.train as T

    ctx = build_probe_context(args.agent, args.etape, args.training_config, args.resolution, args.device, log)
    ctx["workdir"] = workdir
    guarded = [
        Path(ctx["canonical_path"]), Path(ctx["vec_normalize_path"]),
        *sorted((PROJECT_ROOT / "config" / "agents" / args.agent).glob("*.json")),
    ]
    before = snapshot_mtimes(guarded)
    log(
        f"🔬 {args.etape} / {args.training_config} : {ctx['n_envs']} envs, {len(ctx['scenario_list'])} entrées "
        f"de scénario, reprise à {ctx['episode_offset']} épisodes ({ctx['episode_start_index']} par env), "
        f"pool {ctx['pool_labels']}, modèle {ctx['canonical_path']}"
    )
    try:
        result = measure(ctx, args.rollouts, log, args.permutation_seed)
    finally:
        T.close_training_env(ctx["env"], "fin de sonde", log)
        T._cleanup_wall_override_temp_dir()
    after = snapshot_mtimes(guarded)
    changed = sorted(p for p in before if before[p] != after.get(p))
    if changed:
        raise RuntimeError("fichiers protégés modifiés pendant la sonde : " + ", ".join(changed))
    result["context"] = {
        "agent": args.agent, "etape": args.etape, "training_config": args.training_config,
        "canonical_path": ctx["canonical_path"], "episode_offset": ctx["episode_offset"],
        "n_envs": ctx["n_envs"], "scenario_entries": len(ctx["scenario_list"]),
        "guarded_files_unchanged": True,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=float)
    log(render_report(result))
    log(f"\n📄 résultat : {out_path}")
    return 3 if not result["acceptance"]["passed"] else 0


if __name__ == "__main__":
    sys.exit(main())
