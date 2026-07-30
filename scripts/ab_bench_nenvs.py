#!/usr/bin/env python3
"""A/B ENTRELACE sur `n_envs` : combien d'episodes par seconde, vraiment.

POURQUOI CET OUTIL PLUTOT QUE LIRE `s/ep` DANS LA BARRE DE PROGRESSION
----------------------------------------------------------------------
`s/ep` (ai/training_callbacks.py) est la duree wall-clock d'UN episode SUR UN SLOT d'env,
mesuree entre deux `done` du meme slot. Elle inclut toute l'attente de synchronisation des
autres envs a chaque step. C'est une LATENCE, et elle croit mecaniquement avec `n_envs` :
mesure reelle, 2,24 s/ep a n_envs=6 contre 2,61 a n_envs=8 — alors que le run a 8 etait le
plus RAPIDE des deux (37 s contre 42 s pour 100 episodes). Comparer `s/ep` entre deux valeurs
de `n_envs` conclut donc systematiquement a l'envers. Ce qui se compare est le DEBIT : episodes
termines par seconde de wall-clock, ce que mesure cet outil.

Le bloc `PERF TIMING` (engine/perf_timing.py) ne repond pas non plus a la question : c'est une
moyenne ms/appel sur des fonctions moteur, intrinsequement independante du nombre d'envs.

CE QUE CET OUTIL IMPOSE
-----------------------
1. ENTRELACEMENT A,B,A,B. Sur cette machine deux executions du MEME code peuvent differer d'un
   facteur 2. Seuls les deux membres d'une meme paire, lances coup sur coup, sont comparables.
   La premiere paire est jetee (remplissage des caches disque et allocateur).
2. WALL, pas CPU. Avec SubprocVecEnv, augmenter `n_envs` augmente le CPU total consomme meme
   quand le wall baisse : le CPU mesure le travail, pas la vitesse. Il est affiche a titre
   indicatif, jamais utilise pour le verdict.
3. LE DEMARRAGE EST COMPTE. Le `[MM:SS<...]` de la barre est retro-date au premier episode
   (training_callbacks.py, `start_time = time.time() - total_episode_duration`) : il exclut les
   imports torch, le fork des N sous-processus et le chargement du modele. Ce cout est reel et
   croit avec `n_envs`. L'outil chronometre le process entier et affiche a cote la part
   "demarrage" (wall total moins la duree de boucle annoncee par la barre).
4. NOMBRE D'EPISODES DIVISIBLE PAR LES DEUX `n_envs`. Sinon le run s'arrete en laissant des
   episodes a moitie joues sur certains slots, et le cote qui en laisse le plus est avantage.
5. EXECUTION DANS UN ARBRE DE TRAVAIL SECONDAIRE, jamais dans le depot principal : un
   entrainement ecrit `ai/models/<agent>/model_<agent>.zip`, fichier protege. `models_root` est
   resolu relativement au dossier de `config_loader.py`, donc lancer depuis le worktree ecrit
   dans le worktree. L'outil refuse de demarrer ailleurs.

CONTROLE ANTI-CONFUSION
-----------------------
Chaque run reimprime le `n_envs` que train.py a reellement construit ("Creating K parallel
environments"). Un ecart avec la valeur demandee arrete la mesure : sans ce garde-fou, une
surcharge de config silencieuse ferait mesurer deux fois la meme configuration.

USAGE
-----
    git worktree add /tmp/40k-bench HEAD        # une fois
    python3 scripts/ab_bench_nenvs.py --a 6 --b 8 --episodes 96 --paires 3
    git worktree remove /tmp/40k-bench          # a la fin
"""

from __future__ import annotations

import argparse
import math
import os
import re
import resource
import statistics
import subprocess
import sys
import time

_ELAPSED_RE = re.compile(r"\[(\d+):(\d\d)(?::(\d\d))?<")
_NENVS_RE = re.compile(r"Creating (\d+) parallel environments")


def _parse_loop_seconds(output: str) -> float:
    """Duree de boucle annoncee par la barre de progression (dernier `[MM:SS<` vu)."""
    matches = _ELAPSED_RE.findall(output)
    if not matches:
        raise SystemExit(
            "aucun compteur de progression `[MM:SS<` dans la sortie : la barre a-t-elle change "
            "de format, ou le run s'est-il arrete avant le premier episode ?"
        )
    first, second, third = matches[-1]
    if third:
        return int(first) * 3600 + int(second) * 60 + int(third)
    return int(first) * 60 + int(second)


def _run(repo: str, agent: str, scenario: str, episodes: int, n_envs: int) -> dict:
    """Un entrainement complet ; rend wall, cpu, duree de boucle et n_envs reellement construit."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable, "ai/train.py",
            "--agent", agent,
            "--scenario", scenario,
            "--new",
            "--total-episodes", str(episodes),
            "--param", "n_envs", str(n_envs),
        ],
        cwd=repo, capture_output=True, text=True,
    )
    wall = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    if proc.returncode != 0:
        raise SystemExit(f"echec (n_envs={n_envs}) :\n{proc.stdout[-3000:]}{proc.stderr[-3000:]}")
    output = proc.stdout + proc.stderr
    built = _NENVS_RE.search(output)
    if built is None:
        raise SystemExit(
            f"train.py n'a pas annonce d'environnements paralleles pour n_envs={n_envs} : "
            f"soit la vectorisation est desactivee (--step ? --replay ?), soit le message a change."
        )
    if int(built.group(1)) != n_envs:
        raise SystemExit(
            f"n_envs demande {n_envs}, n_envs construit {built.group(1)} : une surcharge de "
            f"configuration ecrase --param, la mesure comparerait deux fois la meme chose."
        )
    loop = _parse_loop_seconds(output)
    return {"wall": wall, "cpu": cpu, "loop": loop, "startup": wall - loop}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/40k-bench", help="arbre de travail secondaire")
    parser.add_argument("--a", type=int, default=6, help="n_envs du cote A")
    parser.add_argument("--b", type=int, default=8, help="n_envs du cote B")
    parser.add_argument("--episodes", type=int, default=96)
    parser.add_argument("--paires", type=int, default=3)
    parser.add_argument("--agent", default="ArmageddonAgent")
    parser.add_argument("--scenario", default="bot")
    args = parser.parse_args()

    main_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = os.path.abspath(args.repo)
    if repo == main_repo:
        raise SystemExit(
            "refus de mesurer dans le depot principal : chaque run ecrit "
            f"ai/models/{args.agent}/model_{args.agent}.zip, fichier protege.\n"
            f"    git -C {main_repo} worktree add {args.repo} HEAD"
        )
    if not os.path.isdir(repo):
        raise SystemExit(
            f"arbre de travail absent. Le creer une fois :\n"
            f"    git -C {main_repo} worktree add {args.repo} HEAD"
        )
    if args.a == args.b:
        raise SystemExit("--a et --b identiques : rien a comparer.")
    if args.paires < 2:
        raise SystemExit("au moins 2 paires : la premiere est jetee (remplissage des caches).")
    lcm = args.a * args.b // math.gcd(args.a, args.b)
    if args.episodes % args.a or args.episodes % args.b:
        raise SystemExit(
            f"--episodes {args.episodes} n'est pas divisible par {args.a} ET {args.b} : le run "
            f"laisserait des episodes a moitie joues, inegalement des deux cotes. "
            f"Prendre un multiple de {lcm} (ex. {lcm * max(1, args.episodes // lcm)})."
        )

    ratios = []
    for index in range(1, args.paires + 1):
        run_a = _run(repo, args.agent, args.scenario, args.episodes, args.a)
        run_b = _run(repo, args.agent, args.scenario, args.episodes, args.b)
        ratio = run_b["wall"] / run_a["wall"]
        print(
            f"paire {index}{' (jetee)' if index == 1 else ''}\n"
            f"  A(n_envs={args.a}) wall={run_a['wall']:6.1f}s  boucle={run_a['loop']:5.0f}s  "
            f"demarrage={run_a['startup']:5.1f}s  cpu={run_a['cpu']:7.1f}s  "
            f"debit={args.episodes / run_a['wall']:.2f} ep/s\n"
            f"  B(n_envs={args.b}) wall={run_b['wall']:6.1f}s  boucle={run_b['loop']:5.0f}s  "
            f"demarrage={run_b['startup']:5.1f}s  cpu={run_b['cpu']:7.1f}s  "
            f"debit={args.episodes / run_b['wall']:.2f} ep/s\n"
            f"  ratio wall B/A = {ratio:.3f}",
            flush=True,
        )
        if index > 1:
            ratios.append(ratio)

    median = statistics.median(ratios)
    print(
        f"\nratios retenus : {[round(r, 3) for r in ratios]}\n"
        f"MEDIANE = {median:.3f}  ->  n_envs={args.b} est "
        f"{'PLUS RAPIDE' if median < 1 else 'PLUS LENT'} que n_envs={args.a} de "
        f"{abs(1 - median) * 100:.1f} % de wall-clock\n"
        f"etendue {min(ratios):.3f}-{max(ratios):.3f}"
    )
    if min(ratios) < 1.0 < max(ratios):
        print(
            "L'ETENDUE ENJAMBE 1.000 : cette mesure ne tranche pas. Augmenter --episodes et "
            "--paires avant d'en conclure quoi que ce soit, dans un sens comme dans l'autre."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
