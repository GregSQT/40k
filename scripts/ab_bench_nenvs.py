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
1. ENTRELACEMENT, ORDRE ALTERNE (A,B puis B,A puis A,B...). Sur cette machine deux executions du
   MEME code peuvent differer d'un facteur 2. Seuls les deux membres d'une meme paire, lances
   coup sur coup, sont comparables ; et l'ordre s'inverse d'une paire a l'autre pour qu'une
   derive monotone (temperature, charge de fond) ne penalise pas toujours le meme cote. La
   premiere paire est jetee (remplissage des caches disque et allocateur).
2. WALL, et RIEN QUE le wall. Le CPU etait affiche a titre indicatif ; il ne l'est plus, parce
   qu'il ne mesurait pas ce qu'il annoncait. `getrusage(RUSAGE_CHILDREN)` ne comptabilise que les
   descendants effectivement attendus ; les workers de SubprocVecEnv, arretes en fin de run, n'y
   entrent pas. Mesure du 2026-08-01 : 33,7 s de CPU annoncees pour 530 s de wall a n_envs=48, ce
   que 48 processus actifs rendent impossible. Un chiffre faux est plus nuisible qu'un chiffre
   absent : il aurait servi a "expliquer" un resultat de wall-clock surprenant.
3. LE DEMARRAGE EST COMPTE, et il n'est PAS isolable. L'outil chronometre le process entier :
   imports torch, fork des N sous-processus et chargement du modele sont dedans, et ce cout croit
   avec `n_envs`. En revanche il est impossible d'en afficher la part a partir de la barre de
   progression, et cet outil a longtemps pretendu le faire.
   POURQUOI C'EST FAUX : `total_episode_duration_seconds` additionne la duree de chaque episode
   de CHAQUE slot (training_callbacks.py:419, dans la boucle `for env_index`), puis la barre se
   retro-date de cette somme au premier lot d'episodes terminés (:432). La somme vaut donc environ
   `n_envs` fois le temps reellement ecoule, et le `[MM:SS<` part d'un passe fictif d'autant plus
   lointain que `n_envs` est grand. Mesure du 2026-08-01 : a n_envs=16, boucle annoncee 684 s pour
   un wall total de 664 s, soit un "demarrage" de -19,5 s. Une soustraction de deux grandeurs
   incomparables ne devient pas interpretable parce qu'elle tombe parfois positive.
   La barre reste lue, mais UNIQUEMENT comme preuve que la boucle a bien tourne.
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
    python3 scripts/ab_bench_nenvs.py --a 6 --b 8 --episodes 96 --paires 5 --training-config x1
    git worktree remove /tmp/40k-bench          # a la fin

`--training-config` est OBLIGATOIRE cote train.py (aucun defaut silencieux) ; le banc a le sien
(`x1`). Prendre la phase du run a optimiser : elle fixe `n_steps`/`batch_size`, donc mesurer `x1`
pour regler un run `x5_new` repond a une autre question que celle posee.

L'EVALUATION BOT EST DESACTIVEE D'OFFICE, SUR SES DEUX CHEMINS (periodique via `bot_eval_freq`
repousse hors de portee + `save_best_robust` a false ; FINALE via `bot_eval_final` a 0 — cf.
`_run`), des deux cotes et sans option pour la reactiver. Elle lance ses propres sous-processus
pendant le chronometre, pour un cout etranger a `n_envs`, et son poids est ecrasant : mesure
faite, 6 episodes d'entrainement = 21 s, l'evaluation finale qui suivait = plus de 13 minutes. Le
verdict porte donc sur la BOUCLE D'ENTRAINEMENT SEULE. Corollaire : ce banc ne dit rien du cout de
l'evaluation, qui se mesure separement.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import signal
import subprocess
import sys
import time

# Traitement statistique partage avec le banc A/B code (`ab_bench.py`) : appariement des ordres
# d'execution et garde sur --paires. Importe plutot que recopie — c'est exactement le genre de
# regle qu'on corrige d'un cote seulement.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_bench import drift_cancelled, print_spread, validate_paires  # noqa: E402

_ELAPSED_RE = re.compile(r"\[(\d+):(\d\d)(?::(\d\d))?<")
_NENVS_RE = re.compile(r"Creating (\d+) parallel environments")


def _assert_loop_ran(output: str) -> None:
    """Verifie que la boucle d'entrainement a tourne (barre de progression presente).

    Ne rend PAS de duree : le compteur `[MM:SS<` est retro-date d'une somme de durees par slot
    (cf. point 3 de l'en-tete) et ne se compare a aucun wall-clock. Seule sa PRESENCE est une
    information : sans elle, le process s'est arrete avant le premier episode et son wall-clock
    ne mesure pas un entrainement.
    """
    if not _ELAPSED_RE.search(output):
        raise SystemExit(
            "aucun compteur de progression `[MM:SS<` dans la sortie : la barre a-t-elle change "
            "de format, ou le run s'est-il arrete avant le premier episode ?"
        )


class RunFailed(RuntimeError):
    """L'entrainement lui-meme a echoue (code de retour non nul, ou depassement du delai).

    Distincte de `SystemExit` : une incoherence de CONFIGURATION (n_envs construit different de
    celui demande, barre de progression illisible) invalide toute la campagne et doit l'arreter,
    alors qu'un run qui echoue est une DONNEE — une valeur de `n_envs` qui sature la machine
    repond a la question posee. Au balayage de decider s'il continue sans cette configuration.
    """


def _run(
    repo: str,
    agent: str,
    scenario: str,
    training_config: str,
    episodes: int,
    n_envs: int,
    timeout: float | None = None,
) -> dict:
    """Un entrainement complet ; rend le wall-clock, apres controle du n_envs reellement construit.

    `timeout` (secondes) borne la duree du run. Le groupe de processus entier est tue, pas le
    seul fils : `train.py` fait tourner `n_envs` sous-processus qui survivraient a la mort de
    leur parent et continueraient a consommer la machine pendant toutes les mesures suivantes.
    """
    started = time.perf_counter()
    proc = subprocess.Popen(
        [
            sys.executable, "ai/train.py",
            "--agent", agent,
            "--scenario", scenario,
            "--training-config", training_config,
            "--new",
            "--total-episodes", str(episodes),
            "--param", "n_envs", str(n_envs),
            # L'evaluation bot est mise hors de portee : elle lance `bot_eval_n_workers`
            # sous-processus AU MILIEU du chronometre, pour un cout qui ne depend pas de
            # `n_envs`. La laisser se declencher (des que --episodes depasse bot_eval_freq)
            # ferait mesurer un melange entrainement + evaluation au lieu du debit annonce.
            "--param", "callback_params.bot_eval_freq", "1000000000",
            # Consequence obligatoire de la ligne precedente : `save_best_robust` exige au moins
            # `robust_window` evaluations et refuse la configuration sinon (train.py,
            # "Invalid robust-eval configuration"). Sans effet sur la vitesse mesuree.
            "--param", "callback_params.save_best_robust", "false",
            # L'evaluation FINALE est un autre chemin, que `bot_eval_freq` ne couvre pas : elle se
            # declenche apres l'entrainement, hors callback (train.py, `_bot_eval_final` et le
            # bloc curriculum). Mesure faite : 6 episodes d'entrainement = 21 s, l'evaluation
            # finale qui suit = plus de 13 minutes. Comptee dans le wall, elle noierait le signal
            # `n_envs` sous une charge qui n'en depend pas.
            "--param", "callback_params.bot_eval_final", "0",
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        stdout, stderr = proc.communicate()
        wall = time.perf_counter() - started
        raise RunFailed(
            f"n_envs={n_envs} : delai de {timeout:.0f}s depasse (tue a {wall:.0f}s). "
            f"Une configuration qui ne tient pas dans ce delai est perdante par construction."
        )
    wall = time.perf_counter() - started
    if proc.returncode != 0:
        raise RunFailed(
            f"n_envs={n_envs} : code de retour {proc.returncode}\n"
            f"{stdout[-3000:]}{stderr[-3000:]}"
        )
    output = stdout + stderr
    built = _NENVS_RE.search(output)
    # train.py n'annonce "Creating K parallel environments" que pour n_envs > 1 ; a 1 il prend la
    # branche mono-env, silencieuse. Le controle s'inverse donc : a 1 c'est l'ABSENCE du message
    # qui prouve la configuration, sa presence trahirait une surcharge de config.
    if n_envs == 1:
        if built is not None:
            raise SystemExit(
                f"n_envs demande 1, mais train.py a construit {built.group(1)} environnements "
                f"paralleles : une surcharge de configuration ecrase --param."
            )
    elif built is None:
        raise SystemExit(
            f"train.py n'a pas annonce d'environnements paralleles pour n_envs={n_envs} : "
            f"soit la vectorisation est desactivee (--step ? --replay ?), soit le message a change."
        )
    elif int(built.group(1)) != n_envs:
        raise SystemExit(
            f"n_envs demande {n_envs}, n_envs construit {built.group(1)} : une surcharge de "
            f"configuration ecrase --param, la mesure comparerait deux fois la meme chose."
        )
    _assert_loop_ran(output)
    return {"wall": wall}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/40k-bench", help="arbre de travail secondaire")
    parser.add_argument("--a", type=int, default=6, help="n_envs du cote A")
    parser.add_argument("--b", type=int, default=8, help="n_envs du cote B")
    parser.add_argument("--episodes", type=int, default=96)
    # 5, pas 3 : a 3 paires il ne reste que 2 ratios, donc UN couple, et l'etendue affichee est
    # de largeur nulle (cf. `print_spread` dans ab_bench.py).
    parser.add_argument("--paires", type=int, default=5)
    parser.add_argument("--agent", default="ArmageddonAgent")
    parser.add_argument("--scenario", default="bot")
    # train.py exige une phase explicite (R1, `_require_training_config_phase`). La phase fixe
    # `n_steps`/`batch_size`/... : elle doit etre celle du run de production a optimiser, sinon le
    # verdict porte sur une autre configuration que celle qu'on croit mesurer.
    parser.add_argument("--training-config", default="x1", help="phase de config d'entrainement")
    args = parser.parse_args()

    # realpath, pas abspath : un `--repo` qui est un lien symbolique vers le depot principal
    # passerait le controle ci-dessous et l'entrainement ecraserait le modele protege.
    main_repo = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo = os.path.realpath(args.repo)
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
    validate_paires(args.paires)
    lcm = args.a * args.b // math.gcd(args.a, args.b)
    if args.episodes % args.a or args.episodes % args.b:
        raise SystemExit(
            f"--episodes {args.episodes} n'est pas divisible par {args.a} ET {args.b} : le run "
            f"laisserait des episodes a moitie joues, inegalement des deux cotes. "
            f"Prendre un multiple de {lcm} (ex. {lcm * max(1, args.episodes // lcm)})."
        )

    ratios = []
    for index in range(1, args.paires + 1):
        # Ordre alterne A,B puis B,A : lance toujours dans le meme ordre, une derive monotone de
        # la machine (montee en temperature, charge de fond qui s'installe) penalise
        # systematiquement le second des deux. Le biais est alors de meme signe dans toutes les
        # paires et la mediane ne l'annule pas — elle le consacre.
        b_first = index % 2 == 0
        # Ce banc-ci compare DEUX configurations : perdre un run, c'est perdre la paire et donc
        # toute comparabilite. L'echec arrete la campagne (contrairement au balayage, qui peut
        # continuer sans la configuration fautive).
        try:
            if b_first:
                run_b = _run(repo, args.agent, args.scenario, args.training_config, args.episodes, args.b)
                run_a = _run(repo, args.agent, args.scenario, args.training_config, args.episodes, args.a)
            else:
                run_a = _run(repo, args.agent, args.scenario, args.training_config, args.episodes, args.a)
                run_b = _run(repo, args.agent, args.scenario, args.training_config, args.episodes, args.b)
        except RunFailed as failure:
            raise SystemExit(str(failure))
        ratio = run_b["wall"] / run_a["wall"]
        order = "B puis A" if b_first else "A puis B"
        print(
            f"paire {index} ({order}){' — jetee' if index == 1 else ''}\n"
            f"  A(n_envs={args.a}) wall={run_a['wall']:6.1f}s  "
            f"debit={args.episodes / run_a['wall']:.2f} ep/s\n"
            f"  B(n_envs={args.b}) wall={run_b['wall']:6.1f}s  "
            f"debit={args.episodes / run_b['wall']:.2f} ep/s\n"
            f"  ratio wall B/A = {ratio:.3f}",
            flush=True,
        )
        if index > 1:
            ratios.append(ratio)

    median, couples = drift_cancelled(ratios)
    print(
        f"\nratios retenus (BA,AB,...) : {[round(r, 3) for r in ratios]}\n"
        f"couples sans derive        : {[round(c, 3) for c in couples]}\n"
        f"VERDICT = {median:.3f}  ->  n_envs={args.b} est "
        f"{'PLUS RAPIDE' if median < 1 else 'PLUS LENT'} que n_envs={args.a} de "
        f"{abs(1 - median) * 100:.1f} % de wall-clock"
    )
    print_spread(couples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
