#!/usr/bin/env python3
"""Classement BOT CONTRE BOT — mesure la force relative des adversaires d'evaluation.

POURQUOI CET OUTIL EXISTE
    `evaluate_against_bots` exige un MODELE entraine comme joueur 1 : jusqu'ici, la seule facon
    de juger un bot etait de le faire affronter l'agent. Un bot faible et un agent fort donnent
    le meme chiffre qu'un bot fort et un agent faible — la mesure est circulaire.

    Consequence concrete (V11 §0.55) : le holdout d'evaluation `tactical` etait sature
    (`vs_tactical` 0.95 au run 4, 0.89 au run 200k — l'adversaire le plus FACILE des six).
    Le re-profiler sans pouvoir mesurer sa force reviendrait a remplacer un holdout trop
    faible par un holdout de force INCONNUE.

    Cet outil donne l'echelle manquante : chaque bot joue contre chaque autre, sans agent.

⚠️ FIXER LA RESOLUTION AVANT DE MESURER — ce script n'a PAS de drapeau pour ca
    Sans `W40K_BOARD_PATH`, le plateau vient de `config/config.json` -> `board/44x60x5`, alors
    que les evaluations de reference passent `--resolution 1` a `ai/train.py`. Les deux ne sont
    PAS comparables : sur x5, `tactical` sortait DEUXIEME des six a `w_objective 0.5`, contre
    DERNIER sur x1. Une campagne de reglage entiere a ete jetee pour cette raison (V11 §0.55).
        W40K_BOARD_PATH=board/44x60x1 python scripts/bot_ranking.py --bots ... --episodes 20
    Et toujours ecrire la resolution a cote du chiffre obtenu.

CE QU'IL A SERVI A ETABLIR (2026-08-04, §0.55) — a lire avant de rejouer un classement
    Sur x1, 2 400 episodes : `tactical` sortait DERNIER des six (0.357) a `w_objective 0.5`.
    Le holdout est desormais gele a `w_objective 2.0` et sort PREMIER (0.636, contre 0.526 au
    deuxieme) ; l'agent y tombe de 0.89 a 0.72.
    Ce classement a servi a DEPARTAGER, pas a decider : cote agent, toutes les valeurs au-dessus
    de 1.0 rendent le meme 0.72 (reponse en marche puis plateau), donc c'est le bot-contre-bot
    qui a designe le milieu du plateau. Justification complete et pieges de lecture :
    `config/bot_movement_weights.json`, entree `tactical`.

CE QU'IL NE FAIT PAS
    Aucun repli sur une donnee absente. `winner` et `controlled_player` sont lus par
    `require_key` : un episode qui n'aboutit pas leve au lieu d'etre compte en defaite.
    Aucune valeur par defaut de randomness : elle vient de `callback_params.bot_eval_randomness`.

    Le chemin de decision des bots est celui de la PRODUCTION
    (`BotControlledEnv._get_bot_action`, via `scripted_action_for_agent_side`) : le bot mesure
    ici est exactement le bot joue en evaluation. Une seconde implementation divergerait.

USAGE
    python scripts/bot_ranking.py --agent ArmageddonAgent --training-config x1 --episodes 20
    python scripts/bot_ranking.py --bots control,tactical --episodes 50
    python scripts/bot_ranking.py --scenario-pool training --csv /tmp/ranking.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.bot_evaluation import _create_eval_env, _load_bot_eval_params  # noqa: E402
from ai.training_utils import get_scenario_list_for_phase  # noqa: E402
from config_loader import get_config_loader  # noqa: E402
from shared.data_validation import require_key  # noqa: E402


def _episode_seed(base_seed: int, p1: str, p2: str, scenario_index: int, ep_idx: int) -> int:
    """Graine reproductible et DISTINCTE par (paire, scenario, episode).

    Sans le nom des DEUX bots dans la graine, deux appariements differents rejoueraient la meme
    sequence de tirages : les win-rates se compareraient alors sur des parties correlees.
    """
    # `hash()` de CPython est randomise par processus (PYTHONHASHSEED) : l'utiliser rendrait
    # la graine differente d'un lancement a l'autre, en contradiction directe avec ce docstring.
    # `crc32` est stable, c'est tout ce qu'on lui demande ici.
    pair_digest = zlib.crc32(f"{p1}|{p2}".encode("utf-8"))
    mixed = (base_seed * 1_000_003) ^ (pair_digest & 0x7FFFFFFF)
    return (mixed + scenario_index * 7919 + ep_idx) & 0x7FFFFFFF


def _play_match(
    *,
    p1_bot_type: str,
    p2_bot_type: str,
    scenario_file: str,
    scenario_index: int,
    n_episodes: int,
    base_seed: int,
    randomness: Dict[str, float],
    env_kwargs: Dict[str, Any],
    max_steps_per_episode: int,
) -> Dict[str, int]:
    """Joue `n_episodes` de `p1_bot_type` (siege agent) contre `p2_bot_type` (siege bot)."""
    import random

    import numpy as np

    # SOURCE UNIQUE de la table cle -> classe : `ai/bot_registry.py`. Ce bloc en portait une
    # COPIE, jumelle de celle de `ai/bot_evaluation.py` : brancher les six styles refondus dans
    # l'une laissait l'autre lever « Unknown bot type: 'racer' » (mesure du 2026-08-11).
    from ai.bot_registry import build_bot

    p1_bot = build_bot(p1_bot_type, randomness)

    env = _create_eval_env(
        bot_name=p2_bot_type,
        bot_type=p2_bot_type,
        randomness_config=randomness,
        scenario_file=scenario_file,
        **env_kwargs,
    )
    tally = {"wins": 0, "losses": 0, "draws": 0}
    try:
        for ep_idx in range(n_episodes):
            seed = _episode_seed(base_seed, p1_bot_type, p2_bot_type, scenario_index, ep_idx)
            random.seed(seed)
            np.random.seed(seed)
            _obs, info = env.reset(seed=seed)
            done = False
            steps = 0
            while not done and steps < max_steps_per_episode:
                action = env.scripted_action_for_agent_side(p1_bot)
                _obs, _reward, terminated, truncated, info = env.step(action)
                done = bool(terminated) or bool(truncated)
                steps += 1
            if not done:
                raise RuntimeError(
                    f"Episode non termine en {max_steps_per_episode} pas "
                    f"({p1_bot_type} vs {p2_bot_type}, {os.path.basename(scenario_file)}) — "
                    "le compter en defaite fausserait le classement."
                )
            winner = require_key(info, "winner")
            controlled_player = require_key(info, "controlled_player")
            if winner == controlled_player:
                tally["wins"] += 1
            elif winner == -1:
                tally["draws"] += 1
            else:
                tally["losses"] += 1
    finally:
        env.close()
    return tally


def main() -> int:
    parser = argparse.ArgumentParser(description="Classement bot contre bot (sans agent).")
    parser.add_argument("--agent", default="ArmageddonAgent")
    parser.add_argument("--training-config", default="x1")
    parser.add_argument("--scenario-pool", default="holdout", choices=["holdout", "training"])
    parser.add_argument("--episodes", type=int, default=20,
                        help="Episodes par appariement ET par scenario.")
    parser.add_argument("--bots", default=None,
                        help="Liste separee par des virgules. Defaut : les bots de bot_eval_weights.")
    parser.add_argument("--rewards-config", default=None,
                        help="Defaut : identique a --agent, comme ai/train.py.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=None,
                        help="Nombre de processus paralleles (defaut : cpu_count).")
    parser.add_argument("--csv", default=None, help="Chemin d'export CSV de la matrice.")
    args = parser.parse_args()

    if args.episodes <= 0:
        raise ValueError("--episodes doit etre > 0")

    config_loader = get_config_loader()
    eval_params = _load_bot_eval_params(config_loader, args.agent, args.training_config)
    randomness = require_key(eval_params, "randomness")
    weights = require_key(eval_params, "weights")

    if args.bots:
        bots = [b.strip() for b in args.bots.split(",") if b.strip()]
    else:
        bots = sorted(weights.keys())
    if len(bots) < 2:
        raise ValueError(f"Il faut au moins 2 bots pour un classement (recu {bots})")
    dupes = [b for b in set(bots) if bots.count(b) > 1]
    if dupes:
        raise ValueError(f"Noms de bots dupliques dans --bots : {dupes}")

    training_cfg = config_loader.load_agent_training_config(args.agent, args.training_config)
    scenarios = get_scenario_list_for_phase(
        config_loader, args.agent, args.training_config, args.scenario_pool
    )
    if not scenarios:
        raise RuntimeError(
            f"Aucun scenario pour agent={args.agent} pool={args.scenario_pool} — "
            "rien a mesurer."
        )

    game_rules = require_key(config_loader.get_game_config(), "game_rules")
    max_steps_per_episode = int(require_key(game_rules, "max_turns")) * 400
    env_kwargs = {
        "training_config_name": args.training_config,
        # Meme resolution que ai/train.py : le nom du fichier de rewards vaut celui de l'agent
        # sauf surcharge explicite. Ce n'est pas une cle du training config.
        "rewards_config_name": args.rewards_config or args.agent,
        "controlled_agent": args.agent,
        "base_agent_key": args.agent,
        "debug_mode": False,
        "agent_seat_mode": require_key(training_cfg, "agent_seat_mode"),
        "agent_seat_seed": args.seed,
    }

    pairs: List[Tuple[str, str]] = [
        (p1, p2) for p1, p2 in itertools.product(bots, bots) if p1 != p2
    ]
    total_matches = len(pairs) * len(scenarios)
    print(f"🤖 Classement bot-contre-bot — {len(bots)} bots, {len(scenarios)} scenario(s), "
          f"{args.episodes} ep./appariement/scenario = "
          f"{total_matches * args.episodes} episodes")
    print(f"   pool={args.scenario_pool} · agent_config={args.agent}/{args.training_config}")

    # Toutes les taches (paire × scenario) sont independantes : on les soumet toutes et on
    # collecte au fil de l'eau pour afficher la progression sans attendre la fin du lot.
    tasks: List[Tuple[str, str, int, str]] = [
        (p1, p2, si, sf)
        for p1, p2 in pairs
        for si, sf in enumerate(scenarios)
    ]

    raw: Dict[Tuple[str, str, int], Dict[str, int]] = {}
    workers = args.workers or os.cpu_count()
    done_matches = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_task = {
            pool.submit(
                _play_match,
                p1_bot_type=p1,
                p2_bot_type=p2,
                scenario_file=sf,
                scenario_index=si,
                n_episodes=args.episodes,
                base_seed=args.seed,
                randomness=randomness,
                env_kwargs=env_kwargs,
                max_steps_per_episode=max_steps_per_episode,
            ): (p1, p2, si, sf)
            for p1, p2, si, sf in tasks
        }
        for future in as_completed(future_to_task):
            p1, p2, si, sf = future_to_task[future]
            tally = future.result()  # propage les exceptions sans les avaler
            raw[(p1, p2, si)] = tally
            done_matches += 1
            print(f"   [{done_matches}/{total_matches}] {p1} vs {p2} "
                  f"({os.path.basename(sf)}) -> "
                  f"{tally['wins']}W-{tally['losses']}L-{tally['draws']}D",
                  flush=True)

    matrix: Dict[Tuple[str, str], Dict[str, int]] = {}
    for p1, p2 in pairs:
        agg = {"wins": 0, "losses": 0, "draws": 0}
        for si in range(len(scenarios)):
            for k in agg:
                agg[k] += raw[(p1, p2, si)][k]
        matrix[(p1, p2)] = agg

    print("\n📊 Matrice des win-rates (ligne = bot en siege AGENT, colonne = bot adverse)")
    header = "            " + "".join(f"{b[:11]:>12}" for b in bots)
    print(header)
    for p1 in bots:
        cells = []
        for p2 in bots:
            if p1 == p2:
                cells.append(f"{'—':>12}")
                continue
            agg = matrix[(p1, p2)]
            played = agg["wins"] + agg["losses"] + agg["draws"]
            cells.append(f"{agg['wins'] / played:>12.3f}")
        print(f"{p1[:11]:<12}" + "".join(cells))

    print("\n🏆 Classement (win-rate moyen sur tous les adversaires, les deux sieges confondus)")
    scores: List[Tuple[str, float, int]] = []
    for bot in bots:
        wins = played = 0
        for (p1, p2), agg in matrix.items():
            n = agg["wins"] + agg["losses"] + agg["draws"]
            if p1 == bot:
                wins += agg["wins"]
                played += n
            elif p2 == bot:
                wins += agg["losses"]  # une defaite du siege agent est une victoire de p2
                played += n
        scores.append((bot, wins / played, played))
    for rank, (bot, score, played) in enumerate(sorted(scores, key=lambda t: -t[1]), start=1):
        flag = "  ← holdout (poids 0)" if weights.get(bot) == 0.0 else ""
        print(f"  {rank}. {bot:<14} {score:.3f}   ({played} episodes){flag}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["p1_bot", "p2_bot", "wins", "losses", "draws", "p1_win_rate"])
            for (p1, p2), agg in sorted(matrix.items()):
                played = agg["wins"] + agg["losses"] + agg["draws"]
                writer.writerow([p1, p2, agg["wins"], agg["losses"], agg["draws"],
                                 f"{agg['wins'] / played:.4f}"])
        print(f"\n💾 Matrice ecrite dans {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
