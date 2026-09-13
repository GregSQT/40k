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

BALAYAGE λ APPAIRÉ (`--gae-lambdas`, 2026-09-13). Le λ du modèle est toujours balayé (c'est
l'ancre des différences appairées) ; `--gae-lambdas` liste les λ SUPPLÉMENTAIRES. Sur CHAQUE
rollout collecté, avantages et retours GAE sont recalculés a posteriori par SB3 lui-même
(`gae_advantages` : `RolloutBuffer.compute_returns_and_advantage` sur un buffer jetable, vérifié
au 1e-6 contre le buffer du rollout au λ du modèle) depuis les copies NON aplaties de rewards /
values / episode_starts, `last_values` recalculé sur `model._last_obs` et
`last_dones = model._last_episode_starts`. Les pertes policy des autres λ sont prises dans la
MÊME passe avant que les quatre termes, mini-lot par mini-lot (mêmes ratios, seuls les avantages
changent) ; f_B, ‖G‖² et intervalles jackknife sont rendus par λ, ainsi que les DIFFÉRENCES
APPAIRÉES entre λ (jackknife de f_a − f_b sur les mêmes rollouts). γ n'est pas balayé : le critic
est entraîné à γ = 0,99, un autre γ mesurerait un critic qui n'existe pas. λ = 0 rend
δ_t = r_t + γV(s_{t+1}) − V(s_t).

DÉCOMPOSITION DE Var(δ_t) sur les mêmes buffers : Var(r_t) + Var(ΔV_t) + 2 Cov(r_t, ΔV_t) avec
ΔV_t = γ(1 − d_{t+1})V(s_{t+1}) − V(s_t), globalement et par famille d'action
(`engine.macro_intents.action_family` sur l'action jouée, phase lue dans le one-hot `global_bin`
de l'observation du pas, `setting_up` lu comme le moteur : `info["action"] == "ingress_move"`).
Les parts sont DESCRIPTIVES : Var(r)/Var(δ) n'est pas la part qu'une récompense en espérance
retirerait — celle-ci vaut Var(ε) + 2 Cov(ε, ΔV) avec ε = r − E[r|s,a], inaccessible sans
l'espérance ; avec Cov(r, ΔV) < 0 le rapport Var(r)/Var(δ) dépasse même 1 sans rien dire.

CONTRÔLE POSITIF (`--model`) : une autre politique est sondée dans le MÊME environnement P1
(pool, rampe, offset d'épisodes inchangés), avec SES stats VecNormalize : le pkl compagnon du zip,
toujours (contrat compagnon par modèle), jamais celui du canonique ni un autre — une politique
sous les stats d'un autre instantané ne mesure rien. Le canonique lui-même est refusé en
`--model` (il se sonde sans l'option). Chemins comparés RÉSOLUS (`ai/models` est un lien
symbolique dans les worktrees). L'acceptation « reproduit P1 » n'a pas de sens pour un modèle de
contrôle : elle est remplacée par le seul contrôle de plomberie — part d'épisodes contre le pool
dans les bornes. Ses `vf_coef` / `ent_coef` sont les siens (refus d'hyperparamètres limité à
n_steps / batch_size / gamma / gae_lambda) et sont RAPPORTÉS (`model_hyperparams`, en-têtes des
termes value / entropie) : les termes value et entropie de deux modèles ne se comparent qu'à
coefficients égaux. `--random-init SEED`
réinitialise en mémoire les poids du modèle chargé (contrôle positif FORT : le gradient d'une
politique aléatoire est certainement grand ; mesuré le 2026-09-13, f_8160 = 0,43 [0,27, 0,59] à
λ = 0,95 avec K = 12, là où le modèle `entnorm_20260913-040721` rendait 0,006 comme P1).

`--opponent-deterministic` : pose `self_play_deterministic = true` dans le bloc `opponent_mix`
que `_install_stage_config_overrides` installe (la clé que `curriculum.opponent.deterministic`
alimente) — seconde collecte, NON appairée avec la première. L'adversaire n'est plus celui du run
de référence : l'acceptation est celle de la plomberie, comme pour un modèle de contrôle.

TRONCATURES. Le moteur ne rend jamais un épisode sans vainqueur (la limite anti-runaway de pas
pose `winner = DRAW_WINNER`, `win_method = "step_limit"`, `truncated = True`) ; le signal gym
`info["TimeLimit.truncated"]` (posé par les VecEnv, lu comme `ai/training_callbacks`) est le
seul discriminant. Un épisode tronqué n'est pas une partie : son issue est un faux nul, et le
collecteur a replié γ·V(s_terminal) dans la récompense de son dernier pas (bootstrap SB3), ce qui
fausserait Var(r). Toute troncature, sur n'importe quel rollout, ARRÊTE la sonde avec le
diagnostic du moteur (`truncation_debug`).

LECTURE SEULE. Ni modèle, ni config, ni state, ni `optimizer.step`. Refuse de démarrer si un
`ai/train.py` tourne (les évaluations relisent les JSON à chaud), et vérifie en sortie que ni le
zip ni le pkl ni les JSON de l'agent n'ont bougé.

Usage :
    python3 scripts/grad_signal_probe.py --agent ArmageddonAgent_x1 --etape P1 \\
        --training-config x1_lineage --rollouts 24 --gae-lambdas 0.8,0.5,0.2,0 \\
        --out /tmp/grad_signal_p1.json
    # contrôle positif (autre politique, ou poids réinitialisés) :
    python3 scripts/grad_signal_probe.py ... --model ai/models/<clé>/<zip>
    python3 scripts/grad_signal_probe.py ... --random-init 20260913 --rollouts 12
    # adversaire déterministe (seconde collecte, non appairée) :
    python3 scripts/grad_signal_probe.py ... --opponent-deterministic
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
#: λ SUPPLÉMENTAIRES balayés par défaut, en plus du λ du modèle ; γ n'est jamais balayé (critic
#: entraîné à γ = 0,99).
DEFAULT_GAE_LAMBDAS = "0.8,0.5,0.2,0"
#: Tolérance de la vérification « GAE recalculé = buffer du rollout » au λ du modèle (même
#: récurrence float32 : écart mesuré 0 sur 84 rollouts).
GAE_ATOL = 1e-6
#: Var(δ) sous cette fraction de Var(r) + Var(ΔV) est un résidu d'arrondi de la décomposition
#: (δ constant sur la famille) : les parts n'existent pas, rendues nan.
VAR_DELTA_REL_FLOOR = 1e-9
#: Clés d'hyperparamètres dont le checkpoint doit porter les valeurs du profil : toutes pour le
#: canonique (la mesure doit être celle du run), les seules qui définissent le lot pour un
#: modèle de contrôle (une autre politique a légitimement d'autres coefficients de loss).
HP_KEYS_CANONICAL = ("n_steps", "batch_size", "vf_coef", "ent_coef", "gamma", "gae_lambda", "normalize_advantage")
HP_KEYS_CONTROL = ("n_steps", "batch_size", "gamma", "gae_lambda")

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


def _ratio(num: float, den: float) -> float:
    return num / den if den > 0 else float("nan")


def true_sq_of(gram: np.ndarray, keep: np.ndarray) -> float:
    """‖G‖² sans biais sur le sous-ensemble `keep` de rollouts d'une matrice de Gram."""
    return off_diagonal_mean(_sub(gram, keep))


def rollout_sq_of(gram: np.ndarray, keep: np.ndarray) -> float:
    """E‖G_k‖² sur le sous-ensemble `keep`."""
    return diagonal_mean(_sub(gram, keep))


def f_batch_of(gram: np.ndarray, keep: np.ndarray) -> float:
    """f_B = ‖G‖² sans biais / E‖G_k‖² sur `keep` ; nan si le dénominateur n'est pas > 0."""
    return _ratio(true_sq_of(gram, keep), rollout_sq_of(gram, keep))


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
        return true_sq_of(gram, keep)

    def rollout_sq(keep: np.ndarray) -> float:
        return rollout_sq_of(gram, keep)

    def mb_sq(keep: np.ndarray) -> float:
        return float(mb[keep].mean())

    def f_batch(keep: np.ndarray) -> float:
        return f_batch_of(gram, keep)

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
    _check_gamma(gamma)
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


def _check_gamma(gamma: float) -> None:
    if not 0.0 < gamma <= 1.0:
        raise ValueError(f"gamma doit être dans ]0, 1], reçu {gamma}")


def gae_advantages(rewards: np.ndarray, values: np.ndarray, episode_starts: np.ndarray,
                   last_values: np.ndarray, last_dones: np.ndarray, gamma: float,
                   gae_lambda: float) -> Tuple[np.ndarray, np.ndarray]:
    """Avantages GAE(λ) et retours TD(λ) par SB3 LUI-MÊME : `RolloutBuffer.compute_returns_and_advantage`
    sur un buffer jetable portant ces tableaux (une seule source de vérité, float32 comme le run).

    Tableaux (T, N) non aplatis. `last_values` : V(s_T) par env ; `last_dones` : le pas T−1
    fermait-il un épisode. Retourne (advantages, returns) avec returns = advantages + values.
    """
    import torch as th
    from gymnasium import spaces
    from stable_baselines3.common.buffers import RolloutBuffer

    r = np.asarray(rewards, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)
    starts = np.asarray(episode_starts, dtype=np.float32)
    lv = np.asarray(last_values, dtype=np.float32).reshape(-1)
    ld = np.asarray(last_dones, dtype=bool).reshape(-1)
    if not (r.shape == v.shape == starts.shape) or r.ndim != 2:
        raise ValueError(
            f"rewards, values, episode_starts doivent être (T, N) : {r.shape}, {v.shape}, {starts.shape}"
        )
    n_steps, n_envs = r.shape
    if lv.shape != (n_envs,) or ld.shape != (n_envs,):
        raise ValueError(f"last_values / last_dones doivent être (N={n_envs},) : {lv.shape}, {ld.shape}")
    if not 0.0 <= gae_lambda <= 1.0:
        raise ValueError(f"gae_lambda doit être dans [0, 1], reçu {gae_lambda}")
    _check_gamma(gamma)
    buf = RolloutBuffer(n_steps, spaces.Box(-1.0, 1.0, (1,)), spaces.Discrete(1), device="cpu",
                        gamma=gamma, gae_lambda=gae_lambda, n_envs=n_envs)
    buf.rewards, buf.values, buf.episode_starts = r, v, starts
    buf.compute_returns_and_advantage(th.as_tensor(lv).reshape(n_envs, 1), ld)
    return buf.advantages.copy(), buf.returns.copy()


def bootstrap_value_change(values: np.ndarray, episode_starts: np.ndarray, last_values: np.ndarray,
                           last_dones: np.ndarray, gamma: float) -> np.ndarray:
    """ΔV_t = γ(1 − d_{t+1})V(s_{t+1}) − V(s_t), (T, N) — la part de δ_t qui ne vient pas de r_t.

    C'est δ_t à récompense nulle : GAE(λ = 0) de SB3 sur des rewards à zéro, donc exactement
    r_t + ΔV_t = avantage GAE à λ = 0 (verrouillé par test).
    """
    v = np.asarray(values, dtype=np.float32)
    return gae_advantages(np.zeros_like(v), v, episode_starts, last_values, last_dones, gamma, 0.0)[0]


class DeltaVarianceAccumulator:
    """Var(δ) = Var(r) + Var(ΔV) + 2 Cov(r, ΔV), globalement et par famille, sur K rollouts.

    Moments cumulés (n, Σr, Σr², ΣΔV, ΣΔV², Σr·ΔV) : la variance rendue est la variance de
    POPULATION de la concaténation des rollouts, identique à celle du tableau complet. Les parts
    (`share_*`) sont descriptives — cf. docstring du module : `share_reward` n'est pas la part
    qu'une récompense en espérance retirerait.
    """

    def __init__(self) -> None:
        self._moments: Dict[str, np.ndarray] = {}

    def add(self, rewards: np.ndarray, delta_v: np.ndarray, families: Any) -> None:
        r = np.asarray(rewards, dtype=np.float64).reshape(-1)
        d = np.asarray(delta_v, dtype=np.float64).reshape(-1)
        fam = np.asarray(families).astype(str).reshape(-1)
        if not (r.shape == d.shape == fam.shape):
            raise ValueError(f"rewards, delta_v, families de tailles différentes : {r.shape}, {d.shape}, {fam.shape}")
        if r.size == 0:
            raise ValueError("rollout vide : rien à accumuler")
        for name in ("all", *np.unique(fam)):
            mask = np.ones(r.shape, dtype=bool) if name == "all" else (fam == name)
            rr, dd = r[mask], d[mask]
            moments = np.array([rr.size, rr.sum(), (rr * rr).sum(), dd.sum(), (dd * dd).sum(), (rr * dd).sum()])
            self._moments[str(name)] = self._moments.get(str(name), np.zeros(6)) + moments

    @staticmethod
    def _decompose(m: np.ndarray) -> Dict[str, float]:
        n, sr, srr, sd, sdd, srd = m
        mean_r, mean_d = sr / n, sd / n
        if n < 2:
            # Famille vue une fois sur tout le run : sa variance n'existe pas. Rapportée en nan,
            # pas levée — lever ici jetterait K rollouts de collecte pour une ligne auxiliaire.
            var_r = var_d = cov = var_delta = float("nan")
        else:
            var_r = srr / n - mean_r ** 2
            var_d = sdd / n - mean_d ** 2
            cov = srd / n - mean_r * mean_d
            var_delta = var_r + var_d + 2.0 * cov
        # δ constant sur la famille (récompense déterministe, critic exact) laisse un résidu
        # d'arrondi positif de l'ordre de 1e-16 × (Var(r) + Var(ΔV)) : diviser par lui rendrait
        # des parts de 1e11. Plancher RELATIF, pas « > 0 » (faux aussi sur nan : n < 2).
        shares_defined = var_delta > VAR_DELTA_REL_FLOOR * (var_r + var_d)

        def share(x: float) -> float:
            return x / var_delta if shares_defined else float("nan")

        return {
            "n": int(n), "mean_reward": float(mean_r), "mean_delta_v": float(mean_d),
            "mean_delta": float(mean_r + mean_d),
            "var_reward": float(var_r), "var_delta_v": float(var_d), "cov": float(cov),
            "var_delta": float(var_delta),
            "share_reward": float(share(var_r)), "share_delta_v": float(share(var_d)),
            "share_cov": float(share(2.0 * cov)),
        }

    def result(self) -> Dict[str, Any]:
        if "all" not in self._moments:
            raise ValueError("aucun pas accumulé")
        out: Dict[str, Any] = {"all": self._decompose(self._moments["all"]), "by_family": {}}
        for name, m in sorted(self._moments.items()):
            if name != "all":
                out["by_family"][name] = self._decompose(m)
        return out


def phases_from_global_bin(global_bin: np.ndarray) -> np.ndarray:
    """Phase de chaque pas depuis le one-hot `phase_*` de `global_bin` (T, N, S) → (T, N) str.

    `global_bin` n'est pas normalisé par VecNormalize (`ai/train._vec_norm_obs_keys`), le one-hot
    y est intact ; un pas sans exactement un bit levé LÈVE.
    """
    from engine.observation_entities import OBS_PHASE_IDS, global_bin_index

    g = np.asarray(global_bin)
    if g.ndim != 3:
        raise ValueError(f"global_bin doit être (T, N, S), reçu {g.shape}")
    idx = [global_bin_index(f"phase_{phase}") for phase in OBS_PHASE_IDS]
    one_hot = g[:, :, idx]
    hits = (one_hot == 1.0).sum(axis=2)
    if not np.all(hits == 1):
        bad = tuple(np.argwhere(hits != 1)[0])
        raise ValueError(f"one-hot de phase invalide au pas {bad} : {one_hot[bad]}")
    return np.asarray(OBS_PHASE_IDS, dtype=object)[one_hot.argmax(axis=2)]


def step_families(actions: np.ndarray, phases: np.ndarray, setting_up: np.ndarray) -> np.ndarray:
    """Famille de l'action jouée à chaque pas (T, N), comme `w40k_core` la compte."""
    from engine.macro_intents import action_family

    a = np.asarray(actions).reshape(phases.shape)
    su = np.asarray(setting_up, dtype=bool).reshape(phases.shape)
    out = np.empty(phases.shape, dtype=object)
    for t in range(phases.shape[0]):
        for n in range(phases.shape[1]):
            out[t, n] = action_family(int(a[t, n]), str(phases[t, n]), setting_up=bool(su[t, n]))
    return out


def parse_gae_lambdas(text: str) -> List[float]:
    """`--gae-lambdas` : liste de λ dans [0, 1], sans doublon, dans l'ordre donné."""
    lambdas: List[float] = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        lam = float(piece)
        if not 0.0 <= lam <= 1.0:
            raise ValueError(f"λ hors [0, 1] : {lam}")
        if lam in lambdas:
            raise ValueError(f"λ en double : {lam}")
        lambdas.append(lam)
    if not lambdas:
        raise ValueError("--gae-lambdas vide")
    return lambdas


def resolve_probe_model(canonical_path: str, model_path: Optional[str]) -> Tuple[str, str, bool]:
    """(zip sondé, pkl VecNormalize, is_control) — chaque zip avec SON pkl compagnon, toujours.

    Sans `--model` : le canonique. Avec `--model` : ce zip, qui doit être un AUTRE fichier que le
    canonique — comparé par chemin RÉSOLU (`ai/models` est un lien symbolique dans les
    worktrees : le canonique orthographié par son realpath, comme `ai/train.py` le journalise,
    serait sinon pris pour un contrôle et sondé sans acceptation ni refus d'hyperparamètres).
    Le pkl du canonique n'est de ce fait JAMAIS servi à un modèle de contrôle.
    """
    from ai.vec_normalize_utils import get_vec_normalize_path

    if model_path is None:
        return canonical_path, get_vec_normalize_path(canonical_path), False
    model_abs = os.path.abspath(model_path)
    if not os.path.exists(model_abs):
        raise FileNotFoundError(f"--model absent : {model_abs}")
    if os.path.realpath(model_abs) == os.path.realpath(canonical_path):
        raise ValueError(f"--model désigne le canonique ({model_abs}) : il se sonde sans --model.")
    pkl = get_vec_normalize_path(model_abs)
    if not os.path.exists(pkl):
        raise FileNotFoundError(f"stats VecNormalize du modèle de contrôle absentes : {pkl}")
    if os.path.realpath(pkl) == os.path.realpath(get_vec_normalize_path(canonical_path)):
        raise ValueError("un modèle de contrôle ne se sonde jamais avec le pkl du canonique.")
    return model_abs, pkl, True


def reset_policy_parameters(policy: Any, seed: int) -> int:
    """Réinitialise CHAQUE module de la policy (`reset_parameters`), graine fixée ; rend le nombre
    de modules réinitialisés et LÈVE si des paramètres sont restés intacts.

    Contrôle positif FORT : une politique aléatoire a un gradient de politique certainement grand
    dans l'environnement, quel que soit l'état du canonique. Les hyperparamètres et l'architecture
    restent ceux du zip chargé ; rien n'est écrit sur disque.
    """
    import torch as th

    th.manual_seed(seed)
    before = th.cat([p.detach().flatten().clone() for p in policy.parameters()])
    n_reset = 0
    for module in policy.modules():
        if hasattr(module, "reset_parameters"):
            module.reset_parameters()
            n_reset += 1
    after = th.cat([p.detach().flatten() for p in policy.parameters()])
    untouched = int((before == after).sum().item())
    # Une égalité isolée est possible (biais nul avant comme après) ; une part notable ne l'est
    # pas : un module sans `reset_parameters` aurait gardé ses poids entraînés.
    if untouched > 0.01 * before.numel():
        raise RuntimeError(f"réinitialisation incomplète : {untouched} paramètres inchangés sur {before.numel()}")
    return n_reset


def lambda_sweep_stats(grams: Dict[float, Dict[str, np.ndarray]],
                       minibatch_sq_norms: Dict[float, Dict[str, np.ndarray]],
                       batch_steps: int) -> Dict[str, Any]:
    """f_B, ‖G‖² par λ et par groupe, différences APPAIRÉES entre λ (jackknife de f_a − f_b,
    mêmes rollouts) sur le groupe « all ».

    `grams[λ][groupe]` : (K, K) produits scalaires des gradients policy recalculés à λ, sur le
    groupe de paramètres ; `minibatch_sq_norms[λ][groupe]` : (K, M). Toutes les matrices portent
    les MÊMES K rollouts dans le même ordre, ce qui rend la différence appairée légitime. Les
    groupes disent OÙ le gradient d'un λ court devient lisible (mesuré : `activate_query_net`
    f = 0,28 à λ = 0 quand « all » vaut 0,05).
    """
    lambdas = list(grams)
    if set(minibatch_sq_norms) != set(lambdas):
        raise ValueError("grams et minibatch_sq_norms doivent porter les mêmes λ")
    for lam in lambdas:
        if set(grams[lam]) != set(minibatch_sq_norms[lam]) or "all" not in grams[lam]:
            raise ValueError(f"λ={lam} : groupes {sorted(grams[lam])} ≠ {sorted(minibatch_sq_norms[lam])}, « all » requis")
    k = grams[lambdas[0]]["all"].shape[0]
    per_lambda = {}
    for lam in lambdas:
        for gname, gram in grams[lam].items():
            if gram.shape != (k, k):
                raise ValueError(f"λ={lam} groupe {gname} : gram {gram.shape} ≠ ({k}, {k})")
        per_lambda[lam] = {
            gname: signal_stats(grams[lam][gname], minibatch_sq_norms[lam][gname], batch_steps)
            for gname in grams[lam]
        }

    pairs = []
    for i, lam_a in enumerate(lambdas):
        for lam_b in lambdas[i + 1:]:
            ga, gb = grams[lam_a]["all"], grams[lam_b]["all"]
            f_diff = jackknife(lambda keep, ga=ga, gb=gb: f_batch_of(ga, keep) - f_batch_of(gb, keep), k)
            g_diff = jackknife(lambda keep, ga=ga, gb=gb: true_sq_of(ga, keep) - true_sq_of(gb, keep), k)
            pairs.append({
                "lambda_a": lam_a, "lambda_b": lam_b, "f_batch_diff": f_diff, "true_sq_diff": g_diff,
                "f_batch_diff_excludes_zero": bool(
                    np.isfinite(f_diff["low"]) and (f_diff["low"] > 0.0 or f_diff["high"] < 0.0)
                ),
            })
    return {"lambdas": lambdas, "per_lambda": per_lambda, "pairs": pairs}


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


def minibatch_term_losses(model: Any, rollout_data: Any, outcome_adv: Any, outcome_valid: Any,
                          sweep_advantages: Optional[Dict[float, Any]] = None) -> Dict[str, Any]:
    """Les termes de la loss PPO d'un mini-lot, comme `PatchedMaskablePPO.train` les calcule.

    `outcome_adv` / `outcome_valid` : avantage d'issue standardisé sur les pas valides du
    mini-lot et masque des pas valides, alignés sur `rollout_data`. Le terme d'issue est un
    REINFORCE clipé de même forme que le terme policy, moyenné sur les seuls pas valides.
    `sweep_advantages` : avantages recalculés à d'autres λ, alignés sur `rollout_data` ; leur
    terme policy (mêmes ratios, même normalisation par mini-lot) est rendu sous `policy_sweep[λ]`.
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

    ratio = th.exp(log_prob - rollout_data.old_log_prob)
    clipped = th.clamp(ratio, 1 - clip_range, 1 + clip_range)

    def policy_loss_of(advantages: Any) -> Any:
        if model.normalize_advantage:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
        return -th.min(advantages * ratio, advantages * clipped).mean()

    policy_loss = policy_loss_of(rollout_data.advantages)

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
        "policy_sweep": {lam: policy_loss_of(adv) for lam, adv in (sweep_advantages or {}).items()},
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
                        device: str, log: Callable[[str], None], model_path: Optional[str] = None,
                        opponent_deterministic: bool = False,
                        random_init_seed: Optional[int] = None) -> Dict[str, Any]:
    """L'environnement EXACT de l'étape, par les briques d'ai/train.py, et le modèle sondé.

    Même ordre que `main()` → `_prepare_curriculum_stage` → `train_with_scenario_rotation`,
    sans les effets de bord d'un run : ni `prepare_run_artifacts` (contrat, archivage, run-meta),
    ni `attach_run_logger` (dossier TensorBoard), ni callbacks d'entraînement.
    `model_path` : un modèle de CONTRÔLE sondé dans cet environnement avec son pkl compagnon
    (cf. `resolve_probe_model`) ; l'offset d'épisodes, le pool et la rampe restent ceux du
    canonique. `opponent_deterministic` : `self_play_deterministic` posé à vrai dans le bloc
    `opponent_mix` de l'étape. `random_init_seed` : le modèle chargé (canonique ou `--model`)
    est réinitialisé en mémoire (`reset_policy_parameters`) — contrôle positif fort, traité
    comme un modèle de contrôle. `plumbing_only` dans le contexte rendu : l'acceptation se
    limite à la plomberie (contrôle ou adversaire déterministe — le run de référence n'est plus
    ce que la collecte reproduit).
    """
    from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX, get_config_loader

    os.environ["W40K_BOARD_PATH"] = BOARD_DIR_BY_INCHES_TO_SUBHEX[resolution]

    import ai.train as T
    from ai.curriculum import (
        get_stage_hp_overrides, load_curriculum, require_stage, stage_init_source,
    )
    from ai.training_utils import get_scenario_list_for_phase, make_training_env, setup_imports
    from ai.unit_registry import UnitRegistry
    from ai.vec_normalize_utils import get_vec_normalize_path
    from engine.episode_schedule import episodes_per_env
    from shared.data_validation import require_key, require_present
    from stable_baselines3.common.vec_env import VecNormalize

    config = get_config_loader()
    curriculum = load_curriculum(agent)
    stage = require_stage(curriculum, stage_name)
    canonical_path = T.build_agent_model_path(config.get_models_root(), agent)
    if not os.path.exists(canonical_path):
        raise FileNotFoundError(f"modèle canonique absent : {canonical_path}")
    probe_model_path, probe_vec_path, is_control = resolve_probe_model(canonical_path, model_path)
    canonical_vec_path = get_vec_normalize_path(canonical_path)
    is_control = is_control or random_init_seed is not None
    warm_start = stage_init_source(stage) is not None
    if not warm_start:
        raise ValueError(f"étape {stage_name} : init 'new', rien à reprendre — la sonde mesure une reprise.")
    opponent_mix = T._stage_opponent_mix(curriculum, stage, canonical_path)
    if opponent_mix is None:
        raise ValueError(f"étape {stage_name} sans pool : la sonde mesure une étape reprise contre son pool.")
    if opponent_deterministic:
        opponent_mix["self_play_deterministic"] = True
    T._install_stage_config_overrides(
        config, agent, opponent_mix, get_stage_hp_overrides(stage), warm_start, stage_label=stage_name,
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
    # Stats du modèle sondé (son pkl compagnon), FIGÉES (training=False)
    # comme `load_vec_normalize` ; ce dernier force aussi norm_reward=False, qui fausserait
    # l'échelle des retours — le run normalise les récompenses (cf. `_apply_vec_normalize`).
    vec_env = VecNormalize.load(probe_vec_path, env)
    vec_env.training = False
    vec_env.norm_reward = bool(require_key(vec_norm_cfg, "norm_reward"))

    model_params = dict(require_key(training_config, "model_params"))
    T.apply_rollout_n_steps(model_params, n_envs, vec_env.observation_space, log=log)
    model_params = T._model_params_with_ent_coef_frozen(model_params, log=log)
    model = T._load_checkpoint(probe_model_path, vec_env, device)
    if random_init_seed is not None:
        n_reset = reset_policy_parameters(model.policy, random_init_seed)
        log(f"🎲 poids RÉINITIALISÉS en mémoire (graine {random_init_seed}, {n_reset} modules) : contrôle positif aléatoire")
    # Le checkpoint est mesuré TEL QUEL ; il doit porter les hyperparamètres du profil, sinon la
    # mesure ne serait pas celle du run (refus explicite, jamais une réécriture silencieuse). Un
    # modèle de contrôle n'a à partager que la définition du lot.
    mismatches = []
    for key in HP_KEYS_CONTROL if is_control else HP_KEYS_CANONICAL:
        expected = model_params[key]
        actual = getattr(model, key)
        if actual != expected:
            mismatches.append(f"{key}: checkpoint={actual!r} profil={expected!r}")
    if mismatches:
        raise RuntimeError("hyperparamètres du checkpoint ≠ profil " + training_config_name + " : " + "; ".join(mismatches))
    # Les hyperparamètres RÉELS de la mesure — ceux du checkpoint. Pour un contrôle, vf_coef et
    # ent_coef échelonnent les termes value / entropie et ne sont pas ceux du profil.
    model_hyperparams = {key: getattr(model, key) for key in HP_KEYS_CANONICAL}
    if model.rollout_buffer.buffer_size != model.n_steps or model.rollout_buffer.n_envs != n_envs:
        raise RuntimeError(
            f"rollout buffer {model.rollout_buffer.buffer_size}×{model.rollout_buffer.n_envs} ≠ "
            f"n_steps {model.n_steps} × n_envs {n_envs}"
        )
    return {
        "config": config,
        "training_config": training_config,
        "canonical_path": canonical_path,
        "canonical_vec_normalize_path": canonical_vec_path,
        "model_path": probe_model_path,
        "vec_normalize_path": probe_vec_path,
        "is_control": is_control,
        "plumbing_only": bool(is_control or opponent_deterministic),
        "model_hyperparams": model_hyperparams,
        "random_init_seed": random_init_seed,
        "opponent_deterministic": bool(opponent_deterministic),
        "scenario_list": scenario_list,
        "n_envs": n_envs,
        "episode_offset": episode_offset,
        "episode_start_index": episode_start_index,
        "env": vec_env,
        "model": model,
        "pool_labels": [m["label"] for m in require_key(opponents["opponent_mix_config"], "pool")],
    }


#: Clés du diagnostic moteur d'une troncature, reprises telles quelles si présentes (une
#: troncature venue d'un wrapper gym n'en porterait aucune).
TRUNCATION_INFO_KEYS = ("truncation_reason", "win_method", "truncation_debug")


def make_recorder(n_envs: int) -> Any:
    """Callback SB3 minimal : `dones`, l'issue de chaque épisode fini et les troncatures, pas par pas.

    Une troncature (`info["TimeLimit.truncated"]`, le signal gym que les VecEnv posent) est
    enregistrée avec le diagnostic du moteur ; c'est `measure` qui s'arrête dessus. Construit ici
    et non au niveau du module pour ne pas importer SB3 au chargement (les tests des
    statistiques n'en ont pas besoin).
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
            self.setting_up: List[np.ndarray] = []
            self.episodes_total = 0
            self.episodes_pool = 0
            self.truncations: List[Dict[str, Any]] = []
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
                if require_key(info, "TimeLimit.truncated"):
                    self.truncations.append({
                        "env": int(env_idx), "step": len(self.dones),
                        **{key: info[key] for key in TRUNCATION_INFO_KEYS if key in info},
                    })
                winner = require_key(info, "winner")
                controlled = int(require_key(info, "controlled_player"))
                if winner is None:
                    raise RuntimeError(f"épisode fini sans vainqueur (env {env_idx}) : le moteur en pose toujours un")
                if int(winner) == DRAW_WINNER:
                    outcome[env_idx] = 0.0
                elif int(winner) == controlled:
                    outcome[env_idx] = OUTCOME_REWARD
                else:
                    outcome[env_idx] = -OUTCOME_REWARD
            # `setting_up` lu comme `w40k_core` : `ingress_move` est la seule sémantique d'une
            # mise en place depuis les réserves ; `get` légitime, clé d'action absente ailleurs.
            self.setting_up.append(np.array(
                [infos[i].get("action") == "ingress_move" for i in range(n_envs)], dtype=bool
            ))
            self.dones.append(dones)
            self.outcomes.append(outcome)
            return True

        def arrays(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
            return np.stack(self.dones), np.stack(self.outcomes), np.stack(self.setting_up)

    return _Recorder()


def check_acceptance(observed: Dict[str, Any], keys: Sequence[str] = tuple(ACCEPTANCE_BOUNDS)) -> List[str]:
    """Écarts au run de référence sur le premier rollout, sur les clés `keys` de
    `ACCEPTANCE_BOUNDS` ; vide = plomberie acceptée."""
    failures = []
    for key in keys:
        low, high = ACCEPTANCE_BOUNDS[key]
        value = observed[key]
        if not (np.isfinite(value) and low <= value <= high):
            failures.append(f"{key} = {value:.4g} hors [{low}, {high}]")
    return failures


def check_plumbing_acceptance(observed: Dict[str, Any]) -> List[str]:
    """Contrôle de PLOMBERIE seul : part d'épisodes contre le pool dans les bornes du run de
    référence. Pour un modèle de contrôle ou un adversaire déterministe, « reproduit P1 » n'a pas
    de sens (autre politique, ou autre adversaire) ; les troncatures sont exclues en amont, sur
    chaque rollout, par `measure`."""
    return check_acceptance(observed, keys=("pool_episode_share",))


def sweep_lambdas(model_lambda: float, extra: Sequence[float]) -> List[float]:
    """λ balayés : celui du modèle d'abord (ancre des différences appairées), puis les autres."""
    return [model_lambda, *[lam for lam in extra if lam != model_lambda]]


def measure(ctx: Dict[str, Any], rollouts: int, log: Callable[[str], None],
            permutation_seed: int, extra_gae_lambdas: Sequence[float]) -> Dict[str, Any]:
    """K rollouts à politique figée, gradients par terme et par mini-lot, puis statistiques.

    Par rollout : GAE recalculé par SB3 au λ du modèle (vérifié = buffer du rollout) et à chaque
    λ de `extra_gae_lambdas` ; dans la même passe avant que les quatre termes, le gradient policy
    de chaque λ supplémentaire, mini-lot par mini-lot ; décomposition de Var(δ) sur le même buffer.
    """
    import torch as th
    from stable_baselines3.common.logger import configure as configure_sb3_logger
    from stable_baselines3.common.utils import explained_variance, obs_as_tensor

    model = ctx["model"]
    env = ctx["env"]
    n_envs = int(ctx["n_envs"])
    n_steps = int(model.n_steps)
    batch_steps = n_steps * n_envs
    batch_size = int(model.batch_size)
    if batch_steps % batch_size != 0:
        raise ValueError(f"{batch_steps} pas ne se découpent pas en mini-lots de {batch_size}")
    n_minibatches = batch_steps // batch_size
    gamma = float(model.gamma)
    model_lambda = float(model.gae_lambda)
    extra_lambdas = sweep_lambdas(model_lambda, extra_gae_lambdas)[1:]
    plumbing_only = bool(ctx["plumbing_only"])

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
    # Balayage λ : gradient policy (K, D) et carrés de norme des mini-lots (K, M) par λ
    # supplémentaire ; au λ du modèle ce sont `rollout_grads["policy"]` / `mb_sq["policy"]["all"]`.
    sweep_grads = {lam: np.zeros((rollouts, n_params), dtype=np.float32) for lam in extra_lambdas}
    sweep_mb_sq = {lam: {g: np.zeros((rollouts, n_minibatches)) for g in group_names} for lam in extra_lambdas}
    delta_var = DeltaVarianceAccumulator()
    rollout_log: List[Dict[str, Any]] = []
    acceptance: Dict[str, Any] = {}

    for k in range(rollouts):
        t0 = time.perf_counter()
        ok = model.collect_rollouts(env, callback, model.rollout_buffer, n_rollout_steps=n_steps)
        if not ok:
            raise RuntimeError("collect_rollouts a rendu False")
        buf = model.rollout_buffer
        t_collect = time.perf_counter() - t0
        if recorder.truncations:
            raise RuntimeError(
                f"rollout {k} : {len(recorder.truncations)} épisode(s) TRONQUÉ(S) — pas une partie "
                f"(faux nul, bootstrap replié dans la récompense) ; diagnostic moteur : {recorder.truncations}"
            )

        dones, outcome_at_done, setting_up = recorder.arrays()
        if dones.shape != (n_steps, n_envs):
            raise RuntimeError(f"recorder : {dones.shape} ≠ ({n_steps}, {n_envs})")
        # Copies NON aplaties, avant le premier `get()` qui aplatit le buffer en place.
        episode_starts = np.asarray(buf.episode_starts, dtype=bool).reshape(n_steps, n_envs).copy()
        rewards_tn = np.asarray(buf.rewards, dtype=np.float32).reshape(n_steps, n_envs).copy()
        values_tn = np.asarray(buf.values, dtype=np.float32).reshape(n_steps, n_envs).copy()
        actions_tn = np.asarray(buf.actions).reshape(n_steps, n_envs).copy()
        phases_tn = phases_from_global_bin(np.asarray(buf.observations["global_bin"]).reshape(n_steps, n_envs, -1))
        last_dones = np.asarray(model._last_episode_starts, dtype=bool).reshape(n_envs).copy()
        if not np.array_equal(last_dones, dones[-1]):
            raise RuntimeError(f"rollout {k} : model._last_episode_starts ≠ dones du dernier pas du recorder")
        with th.no_grad():
            last_values = model.policy.predict_values(obs_as_tensor(model._last_obs, model.device)).cpu().numpy().reshape(n_envs)
        # Le GAE recalculé (last_values / last_dones reconstruits) doit reproduire le buffer de
        # CE rollout au λ du modèle, sinon rien du balayage ne vaut.
        adv_check, ret_check = gae_advantages(rewards_tn, values_tn, episode_starts, last_values, last_dones, gamma, model_lambda)
        gae_gap = float(np.max(np.abs(adv_check - np.asarray(buf.advantages).reshape(n_steps, n_envs))))
        ret_gap = float(np.max(np.abs(ret_check - np.asarray(buf.returns).reshape(n_steps, n_envs))))
        if gae_gap > GAE_ATOL or ret_gap > GAE_ATOL:
            raise RuntimeError(
                f"rollout {k} : GAE recalculé ≠ buffer à λ = {model_lambda} (écart max avantages {gae_gap:.3g}, "
                f"retours {ret_gap:.3g} > {GAE_ATOL})"
            )
        # Avantages des λ supplémentaires, aplatis comme le buffer, indexés par la même permutation.
        sweep_adv_flat = {
            lam: swap_and_flatten(gae_advantages(rewards_tn, values_tn, episode_starts, last_values, last_dones, gamma, lam)[0])
            for lam in extra_lambdas
        }
        returns_tn, valid_tn = outcome_returns(episode_starts, dones, outcome_at_done, gamma)
        returns_flat = swap_and_flatten(returns_tn)
        valid_flat = swap_and_flatten(valid_tn)
        ev = float(explained_variance(buf.values.flatten(), buf.returns.flatten()))
        returns_mean = float(buf.returns.mean())
        ep_len_mean = float(np.mean(recorder.episode_lengths)) if recorder.episode_lengths else float("nan")
        pool_share = recorder.episodes_pool / recorder.episodes_total if recorder.episodes_total else float("nan")

        # Décomposition de Var(δ) sur ce buffer, par famille de l'action jouée.
        delta_v_tn = bootstrap_value_change(values_tn, episode_starts, last_values, last_dones, gamma)
        families_tn = step_families(actions_tn, phases_tn, setting_up)
        delta_var.add(rewards_tn, delta_v_tn, families_tn)

        # Même permutation que `get()` : le générateur global numpy est réensemencé juste avant
        # l'appel, et l'alignement est VÉRIFIÉ mini-lot par mini-lot sur les avantages.
        seed_k = permutation_seed + k
        perm = np.random.RandomState(seed_k).permutation(batch_steps)
        np.random.seed(seed_k)
        model.policy.set_training_mode(True)
        acc = {term: th.zeros(n_params, device=model.device, dtype=th.float32) for term in TERMS}
        acc_sweep = {lam: th.zeros(n_params, device=model.device, dtype=th.float32) for lam in extra_lambdas}
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
            sweep_adv_mb = {lam: th.as_tensor(adv[idx], device=model.device) for lam, adv in sweep_adv_flat.items()}
            losses = minibatch_term_losses(model, rollout_data, outcome_adv, valid, sweep_adv_mb)
            # Une seule passe avant, un backward par terme puis par λ supplémentaire.
            backward = [(term, losses[term]) for term in TERMS] + list(losses["policy_sweep"].items())
            for b_i, (key, loss) in enumerate(backward):
                g = flat_grad(loss, params, retain_graph=b_i < len(backward) - 1)
                norms = group_sq_norms(g, groups)
                if key in acc_sweep:
                    acc_sweep[key] += g
                    target_mb_sq = sweep_mb_sq[key]
                else:
                    acc[key] += g
                    target_mb_sq = mb_sq[key]
                    if m == 0:
                        mb0_norms[key] = float(np.sqrt(norms["all"]))
                for gname in group_names:
                    target_mb_sq[gname][k, m] = norms[gname]
        for term in TERMS:
            rollout_grads[term][k] = (acc[term] / n_minibatches).cpu().numpy()
        for lam in extra_lambdas:
            sweep_grads[lam][k] = (acc_sweep[lam] / n_minibatches).cpu().numpy()
        del acc, acc_sweep
        model.policy.set_training_mode(False)
        t_grad = time.perf_counter() - t1

        entry = {
            "rollout": k,
            "collect_s": t_collect,
            "grad_s": t_grad,
            "episodes": recorder.episodes_total,
            "episodes_pool": recorder.episodes_pool,
            "valid_outcome_steps": int(valid_tn.sum()),
            "gae_max_gap": gae_gap,
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
            f"{recorder.episodes_total} épisodes ({recorder.episodes_pool} vs pool, 0 tronqué), "
            f"mb0 policy {mb0_norms['policy']:.3f} "
            f"value {mb0_norms['value']:.3f} entropy {mb0_norms['entropy']:.4f} outcome "
            f"{mb0_norms['outcome']:.3f}, EV {ev:.3f}, ep_len {ep_len_mean:.1f}, returns {returns_mean:.3f}, "
            f"part pool {pool_share:.2f}, écart GAE {gae_gap:.2g}"
        )
        if k == 0:
            failures = check_plumbing_acceptance(entry) if plumbing_only else check_acceptance(entry)
            acceptance = {
                "passed": not failures, "failures": failures, "observed": entry,
                "mode": "plumbing" if plumbing_only else "reference",
            }
            if failures:
                log("⛔ ACCEPTATION REFUSÉE — plomberie à corriger avant toute lecture :\n  " + "\n  ".join(failures))
                return {
                    "acceptance": acceptance, "rollouts": rollout_log, "terms": {}, "cosines": {},
                    "lambda_sweep": {}, "delta_variance": {}, "verdict": None,
                    "model_hyperparams": ctx["model_hyperparams"],
                }
            log("✅ acceptation : " + ("plomberie en règle (contrôle ou adversaire déterministe : le run de "
                                       "référence n'est pas ce que la collecte reproduit)" if plumbing_only
                                       else "le premier rollout reproduit le run de référence"))

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
    sweep_grams = {
        lam: {"all": gram_matrix(sweep_grads[lam]),
              **{g: gram_matrix(sweep_grads[lam][:, s:e]) for g, (s, e) in groups.items()}}
        for lam in extra_lambdas
    }
    lambda_sweep = lambda_sweep_stats(
        {model_lambda: grams["policy"], **sweep_grams}, {model_lambda: mb_sq["policy"], **sweep_mb_sq}, batch_steps,
    )
    lambda_sweep["model_lambda"] = model_lambda
    return {
        "acceptance": acceptance,
        "rollouts": rollout_log,
        "n_params": n_params,
        "groups": {g: list(s) for g, s in groups.items()},
        "batch_steps": batch_steps,
        "batch_size": batch_size,
        "terms": terms_out,
        "cosines": cosines,
        "lambda_sweep": lambda_sweep,
        "delta_variance": delta_var.result(),
        "verdict": verdict,
        "model_hyperparams": ctx["model_hyperparams"],
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
    hp = result["model_hyperparams"]
    # Les termes value / entropie portent le coefficient du checkpoint mesuré : deux modèles ne
    # se comparent sur ces termes qu'à coefficients égaux.
    term_scale = {"value": f" (× vf_coef {hp['vf_coef']:g})", "entropy": f" (× ent_coef {hp['ent_coef']:g})"}
    for term in TERMS:
        lines.append(f"\n== terme {term}{term_scale.get(term, '')} ==")
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
    sweep = result["lambda_sweep"]
    lines.append(f"\n== balayage λ (terme policy ; λ du modèle {sweep['model_lambda']}) ==")
    lines.append(f"{'λ / groupe':28s} {'‖G‖² sans biais':>28s} {'f_' + str(b):>26s} {'f_' + str(result['batch_size']):>26s} {'signal':>8s}")
    for lam, by_group in sweep["per_lambda"].items():
        for gname, st in by_group.items():
            label = f"λ = {float(lam):.2f}" if gname == "all" else f"    {gname}"
            lines.append(
                f"{label:28s} {_fmt(st['true_sq']):>28s} {_fmt(st['f_batch']):>26s} "
                f"{_fmt(st['f_minibatch']):>26s} {'oui' if st['signal_detected'] else 'non':>8s}"
            )
    lines.append(f"{'paire (a − b)':>14s} {'Δf_' + str(b) + ' appairé':>28s} {'Δ‖G‖² appairé':>28s}")
    for pair in sweep["pairs"]:
        tag = "  ← exclut 0" if pair["f_batch_diff_excludes_zero"] else ""
        lines.append(
            f"{pair['lambda_a']:5.2f} − {pair['lambda_b']:4.2f}  {_fmt(pair['f_batch_diff']):>28s} "
            f"{_fmt(pair['true_sq_diff']):>28s}{tag}"
        )
    dv = result["delta_variance"]
    lines.append("\n== Var(δ) = Var(r) + Var(ΔV) + 2 Cov (parts de Var(δ)) ==")
    lines.append(f"{'famille':24s} {'n':>8s} {'Var(δ)':>10s} {'part r':>8s} {'part ΔV':>8s} {'part 2Cov':>10s}")
    for name, d in [("all", dv["all"]), *sorted(dv["by_family"].items(), key=lambda kv: -kv[1]["n"])]:
        lines.append(
            f"{name:24s} {d['n']:8d} {d['var_delta']:10.4g} {d['share_reward']:8.3f} "
            f"{d['share_delta_v']:8.3f} {d['share_cov']:10.3f}"
        )
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
    parser.add_argument("--gae-lambdas", default=DEFAULT_GAE_LAMBDAS,
                        help="λ SUPPLÉMENTAIRES recalculés a posteriori sur chaque rollout (appairés), "
                             "en plus du λ du modèle ; γ n'est pas balayé")
    parser.add_argument("--model", default=None,
                        help="zip d'un modèle de CONTRÔLE sondé dans le même env, avec son pkl compagnon")
    parser.add_argument("--opponent-deterministic", action="store_true",
                        help="self_play_deterministic=true dans le bloc opponent_mix de l'étape")
    parser.add_argument("--random-init", type=int, default=None, metavar="SEED",
                        help="réinitialise les poids du modèle chargé en mémoire (contrôle positif fort)")
    args = parser.parse_args(argv)
    if args.rollouts < 3:
        parser.error("--rollouts ≥ 3 (jackknife)")
    extra_gae_lambdas = parse_gae_lambdas(args.gae_lambdas)

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

    ctx = build_probe_context(
        args.agent, args.etape, args.training_config, args.resolution, args.device, log,
        model_path=args.model,
        opponent_deterministic=args.opponent_deterministic, random_init_seed=args.random_init,
    )
    ctx["workdir"] = workdir
    gae_lambdas = sweep_lambdas(float(ctx["model"].gae_lambda), extra_gae_lambdas)
    guarded = [
        *dict.fromkeys(Path(ctx[key]) for key in (
            "canonical_path", "canonical_vec_normalize_path", "model_path", "vec_normalize_path",
        )),
        *sorted((PROJECT_ROOT / "config" / "agents" / args.agent).glob("*.json")),
    ]
    before = snapshot_mtimes(guarded)
    log(
        f"🔬 {args.etape} / {args.training_config} : {ctx['n_envs']} envs, {len(ctx['scenario_list'])} entrées "
        f"de scénario, reprise à {ctx['episode_offset']} épisodes ({ctx['episode_start_index']} par env), "
        f"pool {ctx['pool_labels']}" + (" DÉTERMINISTE" if ctx["opponent_deterministic"] else "") + ", "
        f"modèle {'de CONTRÔLE ' if ctx['is_control'] else ''}{ctx['model_path']}"
        + (f" RÉINITIALISÉ (graine {ctx['random_init_seed']})" if ctx["random_init_seed"] is not None else "")
        + f" (stats {ctx['vec_normalize_path']}), hyperparamètres {ctx['model_hyperparams']}, "
        f"λ balayés {gae_lambdas}, acceptation {'plomberie' if ctx['plumbing_only'] else 'référence'}"
    )
    try:
        result = measure(ctx, args.rollouts, log, args.permutation_seed, extra_gae_lambdas)
    finally:
        T.close_training_env(ctx["env"], "fin de sonde", log)
        T._cleanup_wall_override_temp_dir()
    after = snapshot_mtimes(guarded)
    changed = sorted(p for p in before if before[p] != after.get(p))
    if changed:
        raise RuntimeError("fichiers protégés modifiés pendant la sonde : " + ", ".join(changed))
    result["context"] = {
        "agent": args.agent, "etape": args.etape, "training_config": args.training_config,
        "canonical_path": ctx["canonical_path"], "model_path": ctx["model_path"],
        "vec_normalize_path": ctx["vec_normalize_path"], "is_control": ctx["is_control"],
        "plumbing_only": ctx["plumbing_only"], "model_hyperparams": ctx["model_hyperparams"],
        "random_init_seed": ctx["random_init_seed"],
        "opponent_deterministic": ctx["opponent_deterministic"], "gae_lambdas": gae_lambdas,
        "episode_offset": ctx["episode_offset"],
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
