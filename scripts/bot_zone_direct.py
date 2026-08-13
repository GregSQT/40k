#!/usr/bin/env python3
"""Mesure directe de l'étalement des bots (zones contrôlées par tour).

Joue des épisodes de bot eval sans passer par train.py ni step_logger.
Lit game_state["objective_controllers"] après chaque step pour compter les zones
contrôlées par le bot player (opponent_player).

⚠️ LE MODÈLE NE SE LIT PAS AU CHEMIN CANONIQUE PAR DÉFAUT (2026-08-13). Ce script visait
`model_ArmageddonAgent.zip`, partagé et volatil : tout `train.py --new` l'écrase, y compris
depuis une autre session (cf. §10.2 du chantier). `--model` pointe donc l'ARCHIVE nommée, que
rien n'écrase, et le md5 chargé est imprimé à côté du résultat.

CE SCRIPT EST REPRODUCTIBLE — VÉRIFIÉ, PAS SUPPOSÉ (2026-08-13). Deux exécutions consécutives
à graines identiques rendent des relevés par épisode IDENTIQUES AU BIT (`--json-out`, diff vide
hors l'étiquette). La politique est jouée en `deterministic=True` et `W40KEngine.reset` sème
`random` avec la graine d'épisode, ce qui couvre la part aléatoire des bots
(`bot_eval_randomness`). Conséquence directe pour la calibration : entre deux runs, la dérive
d'un bot NON MODIFIÉ est exactement nulle, donc tout écart sur un bot modifié lui est imputable.
Un écart observé sur un bot de contrôle n'est pas du bruit, c'est un défaut de protocole
(modèle, plateau ou graine changés en cours de route) — le chercher, ne pas le moyenner.

Les deux `seed()` par épisode ci-dessous DOUBLENT ce que fait déjà le moteur, et c'est
volontaire : ce sont les deux lignes que `ai/bot_evaluation.py` exécute avant son `reset`. Leur
retrait a été mesuré SANS effet sur les tableaux ; elles sont là pour que l'instrument et la
vraie boucle d'évaluation ne puissent pas diverger en silence le jour où un tirage passera par
`np.random`.

Usage:
    source .venv/bin/activate && W40K_BOARD_PATH=board/44x60x1 \\
        python3 scripts/bot_zone_direct.py --episodes 60 [--model CHEMIN] [--json-out FICHIER]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Modèle de référence de tout le §11 et le §12 du chantier. Archive NOMMÉE, pas le chemin
#: canonique partagé : cf. l'avertissement en tête de module.
_DEFAULT_MODEL = os.path.join(
    _PROJECT_ROOT, "ai", "models", "ArmageddonAgent", "ArmageddonAgent_12345_robust_0.8721.zip"
)


def _md5(path: str) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help="Chemin du .zip à jouer (son _vec_normalize.pkl apparié est déduit du même stem).",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Écrit les relevés PAR ÉPISODE (bot, tour, zones) pour recalcul hors ligne.",
    )
    parser.add_argument(
        "--label",
        default="",
        help="Étiquette du run, recopiée dans l'en-tête et dans --json-out.",
    )
    args = parser.parse_args()

    import numpy as np
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    from sb3_contrib.common.maskable.utils import get_action_masks
    from config_loader import get_config_loader
    from ai.unit_registry import UnitRegistry
    from ai.bot_registry import build_bot
    from ai.bot_doctrines import load_doctrine_weights, load_hold_bonus
    from ai.env_wrappers import BotControlledEnv
    from ai.training_utils import get_scenario_list_for_phase
    from ai.bot_evaluation import _build_eval_obs_normalizer_for_worker, _episode_seed
    from engine.w40k_core import W40KEngine

    config = get_config_loader()
    tc = config.load_agent_training_config("ArmageddonAgent", "x1_panel")
    cb = tc["callback_params"]

    model_path = os.path.abspath(args.model)
    if not os.path.isfile(model_path):
        raise RuntimeError(
            f"Modèle introuvable : {model_path}. Passer --model avec l'archive à jouer "
            "(le chemin canonique model_ArmageddonAgent.zip est écrasé par tout train.py --new)."
        )
    vec_norm_enabled = bool(tc.get("vec_normalize", {}).get("enabled", False))
    vec_eval_enabled = bool(tc.get("vec_normalize_eval", {}).get("enabled", False))

    model_md5 = _md5(model_path)
    board_path = os.environ.get("W40K_BOARD_PATH", "(défaut config/config.json)")
    if args.label:
        print(f"Run    : {args.label}")
    print(f"Modèle : {os.path.basename(model_path)}  md5={model_md5}")
    print(f"Plateau: {board_path}   épisodes/bot : {args.episodes}")
    model = MaskablePPO.load(model_path, device="cpu")
    normalize = _build_eval_obs_normalizer_for_worker(model, model_path, vec_norm_enabled, vec_eval_enabled)

    bot_weights: dict = cb.get("bot_eval_weights", {})
    bot_randomness: dict = cb.get("bot_eval_randomness", {})
    agent_seat_mode: str = tc.get("agent_seat_mode", "p1")
    if "seed" not in tc:
        raise RuntimeError("Clé 'seed' absente de la config d'entraînement ArmageddonAgent/x1_panel — run non reproductible")
    base_seed: int = int(tc["seed"])
    agent_seat_seed: Optional[int] = tc.get("agent_seat_seed", base_seed)
    print(f"Graine : base={base_seed}  siège={agent_seat_seed}  mode={agent_seat_mode}")

    scenarios = get_scenario_list_for_phase(config, "ArmageddonAgent", "x1_panel", scenario_type="holdout")
    if not scenarios:
        raise RuntimeError("Aucun scénario holdout trouvé pour ArmageddonAgent/x1_panel — vérifier config/agents/ArmageddonAgent/scenarios/")
    scenario_file = scenarios[0]

    results: Dict[str, Dict[int, List[int]]] = {}

    for bot_name in bot_weights:
        print(f"  {bot_name:<16}", end=" ", flush=True)
        bot = build_bot(bot_name, dict(bot_randomness))
        unit_registry = UnitRegistry()

        base_env = W40KEngine(
            rewards_config="ArmageddonAgent",
            training_config_name="x1_panel",
            controlled_agent="ArmageddonAgent",
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            gym_training_mode=True,
            training_n_envs=1,
        )

        masked = ActionMasker(base_env, lambda e: e.get_action_mask())
        env = BotControlledEnv(
            masked, bot, unit_registry,
            agent_seat_mode=agent_seat_mode,
            global_seed=agent_seat_seed,
            env_rank=0,
        )

        ep_zones: Dict[int, List[int]] = defaultdict(list)

        for ep_idx in range(args.episodes):
            ep_seed = _episode_seed(base_seed, bot_name, 0, ep_idx)
            # JUMEAU de `ai/bot_evaluation.py` (les deux lignes qui précèdent son `reset`).
            # Redondantes AUJOURD'HUI — mesuré : les retirer ne change aucun relevé, `reset`
            # sème déjà `random`. Cf. l'en-tête de module pour pourquoi elles restent.
            random.seed(ep_seed)
            np.random.seed(ep_seed)
            obs, info = env.reset(seed=ep_seed)
            bot_player: int = int(info.get("opponent_player", 2))
            done = False
            turn_snapshot: Dict[int, int] = {}

            while not done:
                model_obs = normalize(obs) if normalize else obs
                action_masks = np.asarray(get_action_masks(env), dtype=bool)
                if action_masks.ndim == 1:
                    action_masks = action_masks.reshape(1, -1)
                if isinstance(model_obs, dict):
                    model_input = model_obs
                else:
                    model_input = np.asarray(model_obs, dtype=np.float32)
                    if model_input.ndim == 1:
                        model_input = model_input.reshape(1, -1)
                action, _ = model.predict(model_input, action_masks=action_masks, deterministic=True)
                action_scalar = int(np.asarray(action).flat[0])
                obs, _, terminated, truncated, _ = env.step(action_scalar)
                done = bool(terminated or truncated)

                gs = env.engine.game_state
                cur_turn: int = int(gs.get("turn", 0))
                if cur_turn >= 1:
                    controllers: dict = gs.get("objective_controllers", {})
                    zones = sum(1 for v in controllers.values() if v == bot_player)
                    turn_snapshot[cur_turn] = zones

            for t, z in turn_snapshot.items():
                ep_zones[t].append(z)
            print(".", end="", flush=True)

        env.close()
        results[bot_name] = dict(ep_zones)
        last_t = max(ep_zones) if ep_zones else 0
        n = len(ep_zones.get(last_t, []))
        print(f" {n} ep")

    turns = [1, 2, 3, 4, 5]
    hdr = " | ".join(f"T{t}" for t in turns)
    print(f"\n{'Bot':<22} {'N':>4} | {hdr}")
    print("-" * (22 + 4 + 3 + len(turns) * 6 + 4))
    for bot, tdata in sorted(results.items()):
        last_t = max(tdata) if tdata else 0
        n = len(tdata.get(last_t, []))
        cells = []
        for t in turns:
            vals = tdata.get(t, [])
            cells.append(f"{sum(vals)/len(vals):.2f}" if vals else "  - ")
        print(f"{bot:<22} {n:>4} | " + " | ".join(f"{c:>4}" for c in cells))

    # Erreur-type de la moyenne : sans elle, deux tableaux se comparent à l'oeil et tout écart
    # ressemble à un effet. Elle borne ce qu'un run peut affirmer, elle ne remplace pas la
    # comparaison aux bots de contrôle.
    print(f"\n{'Bot':<22} {'N':>4} | {'T2 ± sem':>14} | {'T5 ± sem':>14}")
    print("-" * (22 + 4 + 3 + 2 * 17))
    for bot, tdata in sorted(results.items()):
        last_t = max(tdata) if tdata else 0
        n = len(tdata.get(last_t, []))
        cells = []
        for t in (2, 5):
            vals = tdata.get(t, [])
            if len(vals) >= 2:
                sem = statistics.stdev(vals) / (len(vals) ** 0.5)
                cells.append(f"{sum(vals)/len(vals):.2f} ± {sem:.2f}")
            elif vals:
                cells.append(f"{vals[0]:.2f} ±  n/a")
            else:
                cells.append("-")
        print(f"{bot:<22} {n:>4} | " + " | ".join(f"{c:>14}" for c in cells))

    if args.json_out:
        payload = {
            "label": args.label,
            "model": os.path.basename(model_path),
            "model_md5": model_md5,
            "board_path": board_path,
            "base_seed": base_seed,
            "episodes": args.episodes,
            # Les poids RÉELLEMENT consommés, relus par l'entrée publique — pas une copie du
            # fichier : c'est ce tuple-là qui a joué, et un relevé qui ne dit pas sous quels
            # poids il a été pris ne se compare à rien.
            "weights": {
                bot: dict(
                    zip(
                        ("w_objective", "w_enemy", "w_fire", "w_risk", "w_contest", "w_crowd"),
                        load_doctrine_weights(bot),
                    )
                )
                for bot in results
            },
            "hold_bonus": load_hold_bonus(),
            "zones_by_turn": {
                bot: {str(t): vals for t, vals in sorted(tdata.items())}
                for bot, tdata in results.items()
            },
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
        print(f"\nRelevés par épisode : {args.json_out}")


if __name__ == "__main__":
    main()
