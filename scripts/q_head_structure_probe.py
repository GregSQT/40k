#!/usr/bin/env python3
"""Structure de la tête Q (S14) : part OFFSET par état contre part CENTRÉE sous π.

QUESTION. La tête Q régresse `Q = V.detach() + A(s, a_t)` sur le retour λ, sans contrainte sur
`A` avant le centrage (plafonnement_p1.md §5.13.1) : rien ne distingue `V + A` de
`(V − c) + (A + c)`, et une constante par état `c(s) = Σ_a π(a|s)·A(s, a)` peut absorber le biais
de V. Pour l'acteur, `c(s)` est une baseline (gradient nul en espérance) qui, après
`normalize_advantage`, fixe l'écart-type du mini-lot et noie le signal entre actions. Ce script
mesure, sur un checkpoint `q_head`, ce que la SORTIE BRUTE `A` de la tête porte d'offset et de
structure, et ce que chaque part vaut contre le résidu du critic.

MÉTHODE. K rollouts à politique FIGÉE, collectés par le chemin de production
(`collect_rollouts`), jamais `optimizer.step`. Par pas : `R = retour λ − V(s)` (V recalculée,
comme `values.detach()` dans `train`), `A = A(s, a_t)` lu sur la sortie BRUTE de la tête
(`expected_advantages`, pas `evaluate_actions_q` qui centre depuis §5.13.1), `c = Σ_a π·A(s, ·)`
sur les probabilités masquées de la politique, `A_c = A − c`. Avec `q_loss = E[(R − A)²]` et
`value_loss = E[R²]` :
    q_loss − value_loss = E[A² − 2·A·R]
                        = E[c² − 2·c·R]      (part OFFSET)
                        + E[A_c² − 2·A_c·R]  (part CENTRÉE)
                        + 2·E[c·A_c]         (croisée ; nulle en espérance : a_t ~ π donc
                                              E_π[A_c | s] = 0, rapportée pour que la somme
                                              soit exacte)
Une part négative = cette composante prédit une part du résidu de V ; positive = elle n'en
prédit rien (bruit mémorisé) ou pire (sélection sur ses erreurs). Parts de variance :
Var(A) = Var(c) + Var(A_c) + 2·Cov — `offset_var_share = Var(c)/Var(A)` est le chiffre de l'audit
du 2026-09-15 (0,98 sur 978 états du run non centré). Dispersion ENTRE actions d'un même état :
`sd_within = sqrt(Σ_a π·(A − c)²)` moyennée sur les états.
Intervalles JACKKNIFE sur les K rollouts (± 1,96 erreur-type), comme `grad_signal_probe.py`.

LECTURE SEULE. Contexte de `grad_signal_probe.py::build_probe_context`, puis `require_q_head_model`
(miroir de `refuse_q_head_model` de la sonde de gradient : ici un checkpoint `gae` est refusé —
sa tête est vide). Refuse de démarrer si un `ai/train.py` tourne, vérifie en sortie que ni le
zip ni le pkl ni les JSON de l'agent n'ont bougé. Ne conditionne ni le code ni la relance de
S14 : instrument.

Usage :
    python3 scripts/q_head_structure_probe.py --agent ArmageddonAgent_x1_expl --etape E0 \\
        --training-config x1_lineage \\
        --model ai/models/ArmageddonAgent_x1_expl/ppo_checkpoint_20260915-134841_6007944_steps.zip \\
        --rollouts 6 --out /tmp/q_head_structure.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.grad_signal_probe import (  # noqa: E402  (dépend du sys.path ci-dessus)
    _ratio,
    build_probe_context,
    jackknife,
    make_recorder,
    refuse_if_training_runs,
    snapshot_mtimes,
)
from shared.json_atomic import json_draft  # noqa: E402

#: Statistiques par rollout, dans l'ordre des colonnes de `per_rollout`.
ROLLOUT_STATS = (
    "value_loss", "q_loss", "gap", "gap_offset", "gap_centered", "gap_cross",
    "var_a", "var_offset", "var_centered", "cov_offset_centered", "sd_within",
    "abs_a", "abs_offset", "abs_centered", "n_steps",
)


def require_q_head_model(model: Any) -> None:
    """Miroir de `grad_signal_probe.refuse_q_head_model` : un checkpoint `gae` n'a pas de tête
    entraînée (avantages nuls partout), la décomposition n'y mesure rien."""
    if getattr(model, "advantage_source", "gae") != "q_head":
        raise ValueError(
            "q_head_structure_probe : le checkpoint porte advantage_source="
            f"{getattr(model, 'advantage_source', 'gae')!r} ; la sonde de structure exige une tête Q "
            "entraînée (advantage_source='q_head')."
        )


def decompose(returns: np.ndarray, values: np.ndarray, adv_played: np.ndarray,
              offset: np.ndarray, sd_within: np.ndarray) -> Dict[str, float]:
    """Les statistiques d'UN rollout depuis ses vecteurs par pas (numpy pur, testable).

    `returns`, `values`, `adv_played` (A brut de l'action jouée), `offset` (Σ_a π·A), `sd_within`
    (dispersion sous π entre actions de l'état) : (N,). Les moyennes sont des moyennes par pas,
    comme les pertes MSE de `train`.
    """
    arrays = (returns, values, adv_played, offset, sd_within)
    shapes = {a.shape for a in arrays}
    if len(shapes) != 1 or any(a.ndim != 1 for a in arrays):
        raise ValueError(f"decompose : vecteurs (N,) attendus, formes {[a.shape for a in arrays]}")
    n = returns.shape[0]
    if n < 2:
        raise ValueError(f"decompose : au moins 2 pas attendus, reçu {n}")
    r = (returns - values).astype(np.float64)
    a = adv_played.astype(np.float64)
    c = offset.astype(np.float64)
    a_c = a - c
    value_loss = float(np.mean(r ** 2))
    q_loss = float(np.mean((r - a) ** 2))
    gap_offset = float(np.mean(c ** 2 - 2.0 * c * r))
    gap_centered = float(np.mean(a_c ** 2 - 2.0 * a_c * r))
    gap_cross = float(2.0 * np.mean(c * a_c))
    return {
        "value_loss": value_loss,
        "q_loss": q_loss,
        "gap": q_loss - value_loss,
        "gap_offset": gap_offset,
        "gap_centered": gap_centered,
        "gap_cross": gap_cross,
        "var_a": float(np.var(a)),
        "var_offset": float(np.var(c)),
        "var_centered": float(np.var(a_c)),
        "cov_offset_centered": float(np.mean((c - c.mean()) * (a_c - a_c.mean()))),
        "sd_within": float(np.mean(sd_within)),
        "abs_a": float(np.mean(np.abs(a))),
        "abs_offset": float(np.mean(np.abs(c))),
        "abs_centered": float(np.mean(np.abs(a_c))),
        "n_steps": float(n),
    }


def pooled(per_rollout: np.ndarray, keep: np.ndarray, column: str) -> float:
    """Moyenne pondérée par le nombre de pas de la colonne sur les rollouts `keep`."""
    n = per_rollout[keep, ROLLOUT_STATS.index("n_steps")]
    return float(np.sum(per_rollout[keep, ROLLOUT_STATS.index(column)] * n) / np.sum(n))


def summarize(per_rollout: np.ndarray) -> Dict[str, Any]:
    """Estimations poolées + intervalles jackknife sur les K rollouts ; parts dérivées."""
    if per_rollout.ndim != 2 or per_rollout.shape[1] != len(ROLLOUT_STATS):
        raise ValueError(f"summarize : ({len(ROLLOUT_STATS)}) colonnes attendues, forme {per_rollout.shape}")
    k = per_rollout.shape[0]
    out: Dict[str, Any] = {"rollouts": k}
    for column in ROLLOUT_STATS:
        if column == "n_steps":
            continue
        out[column] = jackknife(lambda keep, col=column: pooled(per_rollout, keep, col), k)

    def _share(keep: np.ndarray) -> float:
        return _ratio(pooled(per_rollout, keep, "var_offset"), pooled(per_rollout, keep, "var_a"))

    def _sd_ratio(keep: np.ndarray) -> float:
        sd_offset = float(np.sqrt(pooled(per_rollout, keep, "var_offset")))
        return _ratio(sd_offset, pooled(per_rollout, keep, "sd_within"))

    out["offset_var_share"] = jackknife(_share, k)
    out["sd_offset_over_sd_within"] = jackknife(_sd_ratio, k)
    out["n_steps_total"] = float(np.sum(per_rollout[:, ROLLOUT_STATS.index("n_steps")]))
    return out


def measure(ctx: Dict[str, Any], rollouts: int, log: Callable[[str], None]) -> Dict[str, Any]:
    """K rollouts à politique figée ; par mini-lot, A brut, offset sous π et dispersion intra-état."""
    import torch as th
    from stable_baselines3.common.logger import configure as configure_sb3_logger

    from ai.pointer_policy import PointerMaskablePolicy, center_under_policy, masked_probs

    model = ctx["model"]
    env = ctx["env"]
    n_envs = int(ctx["n_envs"])
    n_steps = int(model.n_steps)
    batch_size = int(model.batch_size)
    policy = model.policy
    if not isinstance(policy, PointerMaskablePolicy):
        raise TypeError(f"politique {type(policy).__name__} : la tête Q n'existe que sur PointerMaskablePolicy")
    if policy.adv_heads.is_untrained():
        raise ValueError("tête Q jamais entraînée (couches de sortie à zéro) : rien à décomposer")

    model.set_logger(configure_sb3_logger(ctx["workdir"], ["stdout"]))
    recorder = make_recorder(n_envs)
    _total, callback = model._setup_learn(rollouts * n_steps * n_envs, recorder)

    per_rollout = np.zeros((rollouts, len(ROLLOUT_STATS)), dtype=np.float64)
    rollout_log: List[Dict[str, Any]] = []
    for k in range(rollouts):
        t0 = time.perf_counter()
        ok = model.collect_rollouts(env, callback, model.rollout_buffer, n_rollout_steps=n_steps)
        if not ok:
            raise RuntimeError("collect_rollouts a rendu False")
        t_collect = time.perf_counter() - t0
        buf = model.rollout_buffer
        chunks: Dict[str, List[th.Tensor]] = {key: [] for key in ("returns", "values", "adv", "offset", "sd_within")}
        policy.set_training_mode(False)
        with th.no_grad():
            for rollout_data in buf.get(batch_size):
                actions = rollout_data.actions.long().flatten()
                feats = policy._split_features(rollout_data.observations)
                latent_pi, latent_vf = policy.mlp_extractor(feats.trunk)
                probs = masked_probs(policy._distribution_from(latent_pi, feats, rollout_data.action_masks))
                adv_all = policy.expected_advantages(latent_vf, feats)
                adv_centered, offset = center_under_policy(adv_all, probs)
                chunks["returns"].append(rollout_data.returns.flatten())
                chunks["values"].append(policy.value_net(latent_vf).flatten())
                chunks["adv"].append(adv_all.gather(1, actions.view(-1, 1)).squeeze(1))
                chunks["offset"].append(offset)
                chunks["sd_within"].append(th.sqrt((probs * adv_centered ** 2).sum(dim=1)))
        vectors = {key: th.cat(v).cpu().numpy() for key, v in chunks.items()}
        stats = decompose(vectors["returns"], vectors["values"], vectors["adv"], vectors["offset"], vectors["sd_within"])
        per_rollout[k] = [stats[name] for name in ROLLOUT_STATS]
        rollout_log.append({
            "rollout": k, "t_collect_s": round(t_collect, 1),
            "episodes": recorder.episodes_total, "episodes_pool": recorder.episodes_pool,
            **stats,
        })
        log(
            f"  rollout {k + 1}/{rollouts} ({t_collect:.0f} s, {recorder.episodes_total} épisodes) : "
            f"gap {stats['gap']:+.5f} = offset {stats['gap_offset']:+.5f} + centré {stats['gap_centered']:+.5f} "
            f"+ croisé {stats['gap_cross']:+.5f} ; sd(offset) {np.sqrt(stats['var_offset']):.4f}, "
            f"sd intra-état {stats['sd_within']:.4f}, part offset {_ratio(stats['var_offset'], stats['var_a']):.3f}"
        )
    return {"summary": summarize(per_rollout), "per_rollout": rollout_log}


def _fmt(stat: Dict[str, float], digits: int = 5) -> str:
    if not np.isfinite(stat.get("se", float("nan"))):
        return f"{stat['estimate']:.{digits}f} [non mesurable]"
    return f"{stat['estimate']:+.{digits}f} [{stat['low']:+.{digits}f}, {stat['high']:+.{digits}f}]"


def render_report(result: Dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "",
        f"═══ Structure de la tête Q — {s['rollouts']} rollouts, {int(s['n_steps_total'])} pas ═══",
        f"value_loss = E[R²]            : {_fmt(s['value_loss'])}",
        f"q_loss     = E[(R − A)²]      : {_fmt(s['q_loss'])}",
        f"gap        = q_loss − value   : {_fmt(s['gap'])}",
        f"  part OFFSET   E[c² − 2cR]   : {_fmt(s['gap_offset'])}",
        f"  part CENTRÉE  E[A_c² − 2A_cR]: {_fmt(s['gap_centered'])}",
        f"  croisée       2E[c·A_c]     : {_fmt(s['gap_cross'])}",
        f"sd(A jouée) {np.sqrt(max(s['var_a']['estimate'], 0.0)):.4f} ; sd(offset) "
        f"{np.sqrt(max(s['var_offset']['estimate'], 0.0)):.4f} ; sd(A_c jouée) "
        f"{np.sqrt(max(s['var_centered']['estimate'], 0.0)):.4f} ; sd intra-état sous π {s['sd_within']['estimate']:.4f}",
        f"part de Var(A) qui est l'offset : {_fmt(s['offset_var_share'], 3)} "
        f"(audit 2026-09-15 : 0,98) ; sd(offset)/sd intra-état : {_fmt(s['sd_offset_over_sd_within'], 2)}",
        f"E|A| {s['abs_a']['estimate']:.4f} (tag train/adv_q_abs_mean du run non centré) ; "
        f"E|offset| {s['abs_offset']['estimate']:.4f} (référence du tag train/adv_q_offset_abs_mean) ; "
        f"E|A_c| {s['abs_centered']['estimate']:.4f}",
        "Lecture : une part < 0 prédit une part du résidu de V ; ≥ 0 n'en prédit rien.",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", default="ArmageddonAgent_x1_expl")
    parser.add_argument("--etape", default="E0")
    parser.add_argument("--training-config", default="x1_lineage")
    parser.add_argument("--resolution", type=int, choices=[1, 5, 10], default=1)
    parser.add_argument("--rollouts", type=int, default=6, help="K rollouts (≥ 3, jackknife)")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--out", default=None, help="JSON de résultat (défaut : <workdir>/q_head_structure_probe.json)")
    parser.add_argument("--model", default=None, help="zip du checkpoint q_head sondé, avec son pkl compagnon (défaut : canonique)")
    parser.add_argument("--opponent-deterministic", action="store_true")
    args = parser.parse_args(argv)
    if args.rollouts < 3:
        parser.error("--rollouts ≥ 3 (jackknife)")

    def log(message: str) -> None:
        print(message, flush=True)

    refuse_if_training_runs()
    import torch as th

    if args.device.startswith("cuda") and not th.cuda.is_available():
        raise RuntimeError("--device cuda demandé mais CUDA indisponible")
    workdir = args.workdir or tempfile.mkdtemp(prefix="q_head_structure_probe_")
    os.makedirs(workdir, exist_ok=True)
    out_path = args.out or os.path.join(workdir, "q_head_structure_probe.json")

    import ai.train as T

    ctx = build_probe_context(
        args.agent, args.etape, args.training_config, args.resolution, args.device, log,
        model_path=args.model, opponent_deterministic=args.opponent_deterministic,
    )
    require_q_head_model(ctx["model"])
    ctx["workdir"] = workdir
    guarded = [
        *dict.fromkeys(Path(ctx[key]) for key in (
            "canonical_path", "canonical_vec_normalize_path", "model_path", "vec_normalize_path",
        )),
        *sorted((PROJECT_ROOT / "config" / "agents" / args.agent).glob("*.json")),
    ]
    before = snapshot_mtimes(guarded)
    log(
        f"🔬 {args.etape} / {args.training_config} : {ctx['n_envs']} envs, pool {ctx['pool_labels']}"
        + (" DÉTERMINISTE" if ctx["opponent_deterministic"] else "")
        + f", modèle {ctx['model_path']} (stats {ctx['vec_normalize_path']}), "
        f"advantage_source={ctx['model'].advantage_source} q_coef={ctx['model'].q_coef}"
    )
    try:
        result = measure(ctx, args.rollouts, log)
    finally:
        T.close_training_env(ctx["env"], "fin de sonde", log)
        T._cleanup_wall_override_temp_dir()
    after = snapshot_mtimes(guarded)
    changed = sorted(p for p in before if before[p] != after.get(p))
    if changed:
        raise RuntimeError("fichiers protégés modifiés pendant la sonde : " + ", ".join(changed))
    result["context"] = {
        "agent": args.agent, "etape": args.etape, "training_config": args.training_config,
        "model_path": ctx["model_path"], "vec_normalize_path": ctx["vec_normalize_path"],
        "opponent_deterministic": ctx["opponent_deterministic"], "n_envs": ctx["n_envs"],
        "episode_offset": ctx["episode_offset"], "guarded_files_unchanged": True,
    }
    with json_draft(out_path) as f:
        json.dump(result, f, indent=1, default=float)
    log(render_report(result))
    log(f"\n📄 résultat : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
