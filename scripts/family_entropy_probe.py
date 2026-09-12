#!/usr/bin/env python3
"""Entropie et divergence de DEUX politiques, par FAMILLE d'action, sur les mêmes états.

QUESTION. `train/entropy_loss` est une moyenne sur tous les états du rollout, donc dominée par
les états de mouvement (~194 actions légales, ln n moyen 5,07) : une tête à deux ou trois
actions — charge, choix d'arme, pose — peut s'être entièrement effondrée sans que la courbe ne
bouge. Mesure du 2026-09-12 (6 épisodes, 1 301 décisions) : move_cell H = 2,23 nat, charge_slot
0,007 sur 0,86 possible, shoot_slot 0,23 / 1,58, deploy_slot 0,16 / 1,95. C'est la cause de
l'expérience « entropie normalisée par l'état » (ai/patched_ppo.py, `entropy_normalize_by_legal`)
et ce script en est l'instrument de lecture : il compare deux modèles finaux famille par famille.

MÉTHODE. Trajectoires ÉCHANTILLONNÉES par la politique A (les deux camps joués par A, tirage
selon ses probabilités). À chaque état à plus d'une action légale, les deux politiques sont
interrogées sur la MÊME observation et le MÊME masque : entropie H_A et H_B (nats), H_max =
ln(n légales), probabilité maximale, KL(A‖B) restreinte au support de A, et si leurs argmax
diffèrent. La famille est celle de l'action jouée (`engine.macro_intents.action_family`, avec le
drapeau `setting_up` lu dans le résultat du step pour ne pas compter une arrivée de réserves
comme un déplacement). Les états sont ceux que A visite : une famille rare sous A a peu de
lignes, et son `n` le dit.

PLANCHER. Un bras absent (`--model-a` ou `--model-b` omis) est remplacé par une politique
UNIFORME : la vraie architecture, non entraînée, dont les logits sont mis à zéro, donc
équiprobable sur les actions LÉGALES de chaque état. Son entropie vaut ln n sur CHAQUE famille
par construction ; que le tableau le retrouve valide l'instrument — masques lus au bon endroit,
probabilités indexées par id d'action, familles attribuées, ln n calculé sur le bon effectif.
La tolérance est EXPLICITE (`--floor-tol`, part de ln n en dessous de laquelle le plancher est
violé, 0,01 par défaut : la précision d'un softmax float32 sur ~200 actions) et le script sort en
code 2 si une famille la viole.

POURQUOI PAS SIMPLEMENT « non entraînée ». Mesuré le 2026-09-12 sur `PointerMaskablePolicy` à
poids aléatoires (2 épisodes) : move_cell 5,130 pour ln n = 5,131, mais deploy_slot 1,758 / 1,946,
shoot_weapon_sel_slot 1,038 / 1,386, shoot_slot 0,452 / 1,099. Les têtes POINTÉES sont des
produits scalaires de features à l'initialisation orthogonale, pas une couche à gain 0,01 : une
politique neuve n'est PAS uniforme dessus, et un plancher qui l'attendrait s'échouerait sur
l'initialisation, pas sur l'instrument.

La sonde n'écrit rien : ni config, ni modèle, ni state.

Usage :
    python3 scripts/family_entropy_probe.py --model-a ai/models/X/model_X.zip \\
                                            --model-b ai/models/Y/model_Y.zip --episodes 4
    python3 scripts/family_entropy_probe.py --model-a ai/models/X/model_X.zip     # B = UNIFORME
"""
from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.macro_intents import action_family
from scripts.obs_channel_audit import MAX_STEPS_PER_EPISODE, SCENARIOS, make_engine
from scripts.split_assigned_policy_probe import _Policy


class _UniformPolicy(_Policy):
    """La vraie architecture, non entraînée, logits mis à zéro : uniforme sur les actions légales.

    Le zéro est posé À LA SOURCE des logits (`_action_logits`), en amont du masquage : le chemin
    masque → distribution → probabilités par id reste celui de la production, et c'est lui que le
    plancher valide. Rendre directement `1/n` sur le masque ne validerait que l'arithmétique.
    """

    def __init__(self, eng: Any) -> None:
        super().__init__(None, eng)
        policy: Any = self.model.policy
        original = policy._action_logits
        torch = self.torch

        def zero_logits(*args: Any, **kwargs: Any) -> Any:
            return torch.zeros_like(original(*args, **kwargs))

        policy._action_logits = zero_logits


#: Colonnes du tableau, dans l'ordre d'affichage. `n` et `legal` d'abord : une moyenne se lit
#: avec son effectif et la largeur des masques qu'elle résume.
COLUMNS = ("n", "legal", "H_A", "H_B", "H_max", "pmax_A", "pmax_B", "KL(A|B)", "argmax≠")

#: Valeurs par famille accumulées sur un état — une liste par mesure.
Accumulator = Dict[str, Dict[str, List[float]]]


def entropy_nats(p: np.ndarray) -> float:
    """Entropie de Shannon en nats, sur le support (les zéros exacts du masque n'apportent rien)."""
    p = np.asarray(p, dtype=np.float64)
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def kl_nats(p: np.ndarray, q: np.ndarray, q_floor: float = 1e-12) -> float:
    """KL(p‖q) en nats sur le support de p ; q est plancheré pour rester fini.

    Le plancher est un choix de LECTURE et non un lissage : une action que A joue et que B
    exclut donne un terme fini très grand (p·ln(p/1e-12) ≈ 27,6·p), visible dans la moyenne
    plutôt qu'un `inf` qui l'effacerait.
    """
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    m = p > 0
    return float((p[m] * (np.log(p[m]) - np.log(np.maximum(q[m], q_floor)))).sum())


def family_of(action: int, phase: str, step_info: Dict[str, Any]) -> str:
    """Famille de l'action jouée, `setting_up` lu comme le moteur le fait (w40k_core.py)."""
    return action_family(
        int(action), str(phase),
        setting_up=step_info.get("action") == "ingress_move",  # get allowed : clé d'action
    )


def new_accumulator() -> Accumulator:
    return collections.defaultdict(lambda: collections.defaultdict(list))


def record_state(acc: Accumulator, family: str, p_a: np.ndarray, p_b: np.ndarray,
                 n_legal: int) -> None:
    """Une ligne de mesure pour `family` ; refuse un état sans décision (n_legal < 2)."""
    if n_legal < 2:
        raise ValueError(f"état sans décision (n_legal={n_legal}) : rien à mesurer")
    d = acc[family]
    d["legal"].append(float(n_legal))
    d["H_A"].append(entropy_nats(p_a))
    d["H_B"].append(entropy_nats(p_b))
    d["H_max"].append(float(np.log(n_legal)))
    d["pmax_A"].append(float(np.max(p_a)))
    d["pmax_B"].append(float(np.max(p_b)))
    d["KL(A|B)"].append(kl_nats(p_a, p_b))
    d["argmax≠"].append(float(int(np.argmax(p_a) != np.argmax(p_b))))


def summarize(acc: Accumulator) -> List[Dict[str, float | str]]:
    """Une ligne par famille (moyennes), triées par effectif décroissant."""
    rows: List[Dict[str, float | str]] = []
    for family in sorted(acc, key=lambda f: (-len(acc[f]["legal"]), f)):
        d = acc[family]
        row: Dict[str, float | str] = {"famille": family, "n": float(len(d["legal"]))}
        for col in COLUMNS[1:]:
            row[col] = float(np.mean(d[col]))
        rows.append(row)
    return rows


def render_table(rows: List[Dict[str, float | str]]) -> str:
    head = f"{'famille':22s} " + " ".join(f"{c:>8s}" for c in COLUMNS)
    lines = [head]
    for row in rows:
        cells = [f"{int(row['n']):8d}"] + [f"{float(row[c]):8.3f}" for c in COLUMNS[1:]]
        lines.append(f"{str(row['famille']):22s} " + " ".join(cells))
    return "\n".join(lines)


def floor_violations(rows: List[Dict[str, float | str]], column: str, tol: float) -> List[str]:
    """Familles où l'entropie `column` tombe sous (1 - tol) × H_max — plancher violé.

    Sur la politique UNIFORME, H = ln n famille par famille (et jamais au-dessus : ln n est le
    maximum) ; une famille qui s'en écarte au-delà de `tol` dénonce l'instrument (masque mal lu,
    probabilités mal indexées, famille mal attribuée), pas la politique.
    """
    if not 0.0 <= tol < 1.0:
        raise ValueError(f"--floor-tol doit être dans [0, 1) (got {tol})")
    return [
        str(row["famille"]) for row in rows
        if float(row[column]) < (1.0 - tol) * float(row["H_max"])
    ]


def collect(eng: Any, pol_a: _Policy, pol_b: _Policy, seed: int, acc: Accumulator) -> int:
    """Un épisode échantillonné par A ; retourne le nombre de pas joués."""
    obs, _info = eng.reset(seed=seed)
    rng = np.random.default_rng(seed)
    steps = 0
    while steps < MAX_STEPS_PER_EPISODE:
        gs = eng.game_state
        if gs.get("game_over"):  # get allowed : clé absente = partie en cours
            break
        mask = eng.get_action_mask()
        if not mask.any():
            break
        phase = str(gs.get("phase"))  # get allowed : lue pour la famille, comme le moteur
        p_a = pol_a.distribution(obs, mask)
        n_legal = int(mask.sum())
        p_b = pol_b.distribution(obs, mask) if n_legal > 1 else None
        action = int(rng.choice(len(p_a), p=p_a / p_a.sum()))
        obs, _r, term, trunc, info = eng.step(action)
        steps += 1
        # `step` ne rend `None` que sous `defer_observation`, jamais demandé ici : un `None`
        # interrogerait les politiques sur autre chose que l'état du moteur.
        if obs is None:
            raise RuntimeError(f"observation reportée (defer_observation) au step {steps}")
        if p_b is not None:
            record_state(acc, family_of(action, phase, info), p_a, p_b, n_legal)
        if term or trunc:
            break
    return steps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-a", default=None,
                    help="politique A (échantillonne les états) ; absent = UNIFORME (plancher)")
    ap.add_argument("--model-b", default=None,
                    help="politique B ; absent = UNIFORME (plancher)")
    ap.add_argument("--episodes", type=int, default=4, help="épisodes PAR scénario")
    ap.add_argument("--floor-tol", type=float, default=0.01,
                    help="part de ln n sous laquelle un bras UNIFORME viole le plancher")
    args = ap.parse_args()

    acc = new_accumulator()
    pol_a: Optional[_Policy] = None
    pol_b: Optional[_Policy] = None
    t0 = time.time()
    episode = 0
    for scenario in SCENARIOS:
        eng = make_engine(scenario)
        if pol_a is None or pol_b is None:
            pol_a = _Policy(args.model_a, eng) if args.model_a else _UniformPolicy(eng)
            pol_b = _Policy(args.model_b, eng) if args.model_b else _UniformPolicy(eng)
        for seed in range(1, args.episodes + 1):
            steps = collect(eng, pol_a, pol_b, 1000 + seed, acc)
            episode += 1
            print(f"ep {episode} {scenario} steps={steps} t={time.time() - t0:.0f}s",
                  file=sys.stderr, flush=True)

    rows = summarize(acc)
    if not rows:
        print("AUCUN état à plus d'une action légale — rien à mesurer.")
        return 1
    print(f"A = {args.model_a or 'UNIFORME'}\nB = {args.model_b or 'UNIFORME'}")
    print(render_table(rows))

    rc = 0
    for label, model, column in (("A", args.model_a, "H_A"), ("B", args.model_b, "H_B")):
        if model is not None:
            continue
        bad = floor_violations(rows, column, args.floor_tol)
        if bad:
            print(f"\n❌ PLANCHER violé pour {label} (UNIFORME) : {column} < "
                  f"{1 - args.floor_tol:.3f} × ln n sur {bad}. L'instrument est en cause, pas "
                  f"la politique : ne rien lire du tableau.")
            rc = 2
        else:
            print(f"\n✅ plancher {label} : {column} ≥ {1 - args.floor_tol:.3f} × ln n sur "
                  f"toutes les familles — les nombres de {label} ne disent RIEN d'une "
                  f"politique, seulement que l'instrument mesure juste.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
