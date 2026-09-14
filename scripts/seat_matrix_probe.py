"""S27 — mesure statique d'un modèle contre une archive figée, lecture seule.

Dossier `Documentation/Chantiers/backlog/plafonnement_p1.md` §9.5 : avant tout run, dire quelle
part du score contre P0 est structurelle (siège, dés). Le script ne fait qu'appeler
`evaluate_against_checkpoints` — la sonde de curriculum elle-même (agent argmax, archive
argmax, siège tiré selon le profil d'entraînement) — et écrire son résultat COMPLET en JSON,
avec les grandeurs de lecture (win-rate, effectifs) résumées sur stdout.

Usage :
    python3 scripts/seat_matrix_probe.py --model <zip> --archive <zip> --label P0 \
        --agent ArmageddonAgent_x1 --training-config x1_lineage --episodes 300 \
        --workers 8 --out <json>

Le profil d'entraînement décide du siège (`agent_seat_mode`, `agent_seat_p2_ratio`) : un
profil à `agent_seat_mode: p1` ou `p2` mesure UN siège. Aucun fichier de `config/` ni de
`ai/models/` n'est écrit. Le résultat d'`evaluate_against_checkpoints` ne ventile PAS par
siège (label, `_wins/_losses/_draws/_timeouts` seulement) : un siège se mesure par un profil
qui le force.

PLATEAU : `W40K_BOARD_PATH` est posé AVANT tout import du moteur, depuis le suffixe `_x<N>`
de l'agent (`board_path_for_agent`) — sans lui `config/config.json` impose le plateau x5 et
la grille d'observation, à taille fixe, ne refuse rien : des modèles x1 joueraient à x5 en
silence (même règle que `ai/train.py` et `scripts/grad_signal_probe.py`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def board_path_for_agent(agent: str) -> str:
    """Répertoire de plateau déduit du suffixe `_x<N>` de la clé d'agent ; lève sans suffixe."""
    from config_loader import BOARD_DIR_BY_INCHES_TO_SUBHEX

    match = re.search(r"_x(\d+)", agent)
    if match is None:
        raise ValueError(
            f"Impossible de déduire la résolution depuis le nom d'agent '{agent}' "
            "(suffixe _x1 / _x5 attendu)."
        )
    resolution = int(match.group(1))
    if resolution not in BOARD_DIR_BY_INCHES_TO_SUBHEX:
        raise ValueError(
            f"Résolution {resolution} inconnue pour '{agent}' : "
            f"{sorted(BOARD_DIR_BY_INCHES_TO_SUBHEX)} attendues."
        )
    return BOARD_DIR_BY_INCHES_TO_SUBHEX[resolution]


def summarize(result: Dict[str, Any], label: str) -> Dict[str, Any]:
    """Grandeurs de lecture d'un résultat d'`evaluate_against_checkpoints` pour UNE archive.

    Ne recalcule rien : reprend le win-rate publié sous le label de l'archive et ses effectifs
    (`<label>_wins/_losses/_draws`). Lève si le label est absent — un résultat sans le score
    demandé n'est pas un résultat (`filter_compatible_archives` écarte une archive incompatible
    sans lever).
    """
    if label not in result:
        raise KeyError(f"Résultat sans score pour l'archive '{label}' : clés {sorted(result)}")
    summary: Dict[str, Any] = {"label": label, "win_rate": result[label]}
    for key in ("wins", "losses", "draws"):
        full = f"{label}_{key}"
        if full in result:
            summary[key] = result[full]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="S27 — mesure statique d'un modèle contre une archive figée, lecture seule."
    )
    parser.add_argument("--model", required=True, help="zip du modèle évalué (argmax)")
    parser.add_argument("--archive", required=True, help="zip de l'archive adverse figée (argmax)")
    parser.add_argument("--label", required=True, help="étiquette de l'archive (ex. P0)")
    parser.add_argument("--agent", required=True, help="clé d'agent (config et récompense)")
    parser.add_argument("--training-config", required=True, help="profil d'entraînement (siège)")
    parser.add_argument("--episodes", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--out", required=True, help="JSON complet du résultat")
    args = parser.parse_args()

    os.environ["W40K_BOARD_PATH"] = board_path_for_agent(args.agent)
    from ai.bot_evaluation import evaluate_against_checkpoints

    started = time.time()
    result = evaluate_against_checkpoints(
        model_path=args.model,
        checkpoint_archives=[(args.archive, args.label)],
        training_config_name=args.training_config,
        rewards_config_name=args.agent,
        n_episodes=args.episodes,
        controlled_agent=args.agent,
        scenario_pool="holdout",
        device="cpu",
        n_workers_override=args.workers,
    )
    payload = {
        "model": args.model,
        "archive": args.archive,
        "label": args.label,
        "training_config": args.training_config,
        "episodes": args.episodes,
        "duration_s": round(time.time() - started, 1),
        "summary": summarize(result, args.label),
        "result": result,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(payload["summary"], indent=1, ensure_ascii=False, default=str))
    print(f"durée {payload['duration_s']} s — JSON : {args.out}")


if __name__ == "__main__":
    main()
