#!/usr/bin/env python3
"""A/B ENTRELACE : le meme travail, dans deux versions du code, chronometre honnetement.

POURQUOI CET OUTIL
------------------
Sur cette machine, deux executions du MEME code peuvent differer d'un facteur 2 (mesure : 7,84 s
puis 6,00 s). Un « avant/apres » lance a dix minutes d'intervalle ne mesure donc rien. Trois
regles rendent le chiffre exploitable, et cet outil les impose :

1. DEUX REPERTOIRES, pas de `git stash`. La version de reference vit dans un arbre de travail git
   secondaire. Rien n'est deplace pendant la mesure, chaque version garde son propre
   `__pycache__` — le piege du bytecode perime (un mtime restaure a la seconde pres apres un
   `stash pop`) disparait par construction.
2. ENTRELACEMENT, ORDRE ALTERNE (A,B puis B,A puis A,B...), et on ne compare QUE les deux membres
   d'une meme paire, executes coup sur coup : la machine est alors dans le meme etat pour les
   deux. Un ratio intra-paire est interpretable, un absolu inter-paire ne l'est pas. L'ordre
   s'inverse d'une paire a l'autre pour qu'une derive monotone (temperature, charge de fond) ne
   penalise pas toujours le meme cote. La premiere paire est jetee (remplissage des caches
   disque et allocateur).
3. TEMPS CPU (user+sys), pas wall : il ne compte pas les instants ou un autre processus occupe le
   coeur. Le wall est affiche a cote, a titre indicatif.

CONTROLE ANTI-CONFUSION
-----------------------
Chaque run reimprime le compteur `action_mask` de l'empreinte. Il n'existe que depuis le chantier
de deduplication du masque : un `-` cote A et un nombre cote B prouvent qu'on a bien chronometre
les deux cotes annonces. Sans ce garde-fou, une erreur de repertoire fait mesurer deux fois la
meme version et produit des ratios erratiques qu'on impute a tort a la machine — c'est arrive.

USAGE
-----
    git worktree add /tmp/40k-avant HEAD      # une fois ; ou <commit> au lieu de HEAD
    python3 scripts/ab_bench.py --episodes 24 --paires 5
    git worktree remove /tmp/40k-avant        # a la fin

Prendre au moins 24 episodes : le demarrage (imports torch, chargement des configs) coute ~3 s
fixes, qui diluent le signal a 8 episodes (mesure : 8,3 % a 8 episodes contre 11,3 % a 24 pour le
meme changement).

CE QUE CET OUTIL NE MESURE PAS
------------------------------
Le banc joue une politique aleatoire masquee : ni passe avant du modele, ni backprop. Un gain
mesure ici est un gain sur le MOTEUR, pas sur un entrainement reel, ou PPO ajoute un cout fixe
que ce chiffre ignore (mesure : -11 % ici contre -5 % de s/ep sur un vrai run de 100 episodes).
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


# Variables d'environnement qui changent la VITESSE d'un run (verifications supplementaires,
# instrumentation, traces) ou son OBJET (le plateau mesure). `subprocess` herite de
# l'environnement du banc : une seule d'entre elles exportee dans le shell fausse silencieusement
# toute une campagne — `W40K_MASK_VERIFY` a ete mesuree a x4,7 au niveau 1 et x17 au niveau 2
# (commit 0839ea21). Le ralentissement s'applique aux deux cotes, donc le RATIO survit peut-etre ;
# mais les durees absolues, le dimensionnement de `--timeout` et toute comparaison avec une
# campagne precedente, non. Et rien dans la sortie ne l'indiquerait.
_MEASUREMENT_ALTERING_ENV = (
    "W40K_MASK_VERIFY",
    "W40K_PERF_TIMING",
    "W40K_PERF_TIMING_LOG",
    "W40K_PERF_TIMING_MIN_EPISODE",
    "W40K_PERF_TIMING_FLUSH_EVERY",
    "W40K_PERF_PROFILE",
    "W40K_PERF_PROFILE_LOG",
    "W40K_CHARGE_DEBUG",
    "W40K_FIGHT_DEBUG",
    "W40K_CASCADE_DEBUG_FILE",
    "W40K_FOCUS_FIRE_POOL_AUDIT",
    # Lue sur le chemin CHAUD du tir (shooting_handlers : trois sites, dont la boucle de
    # verification de ligne de vue), avec une trace par controle. Deux autres variables du
    # moteur ont ete ecartees de cette liste a dessein : W40K_DEBUG et
    # W40K_PERF_PAYLOAD_BREAKDOWN ne sont lues que par services/api_server.py, donc elles ne
    # ralentissent aucun run de banc — les refuser bloquerait une session PvP voisine sans
    # rien proteger.
    "W40K_LOS_DEBUG",
    # Pas un ralentisseur : un CHANGEMENT DE CE QUI EST MESURE. `config_loader.py:86` la fait
    # primer sur `paths.board` de config.json, aucun banc ne passe `--resolution` (defaut None,
    # train.py:4725) et `refactor_fingerprint.py:74` la pose en `setdefault`, donc la valeur du
    # shell gagne partout. Un `board/44x60x5` exporte et oublie ferait mesurer un plateau 25 fois
    # plus grand — un resultat parfaitement coherent, mais qui ne repond pas a la question posee.
    "W40K_BOARD_PATH",
)

# Valeurs qui DESARMENT une de ces variables : la laisser a "0" ne ralentit rien, refuser dans ce
# cas rendrait le banc penible sans rien proteger. Alignees sur le parseur strict de
# W40K_MASK_VERIFY (off/n/false/0).
_DISARMED_VALUES = {"", "0", "off", "false", "no", "n"}

def assert_clean_environment() -> None:
    """Refuse de mesurer si une variable d'environnement ralentissante est armee.

    Appelee a chaque run plutot qu'une fois au demarrage : c'est le seul endroit par lequel les
    deux bancs passent obligatoirement, donc le seul qui ne puisse pas etre oublie par un banc
    futur. Le cout est nul.
    """
    armed = [
        f"{name}={os.environ[name]!r}"
        for name in _MEASUREMENT_ALTERING_ENV
        if name in os.environ and os.environ[name].strip().lower() not in _DISARMED_VALUES
    ]
    if armed:
        raise SystemExit(
            "refus de mesurer : des variables d'environnement qui changent la vitesse d'un run, "
            "ou le plateau sur lequel il tourne, sont armees et seraient heritees par chaque "
            "run —\n    "
            + "\n    ".join(armed)
            + "\nLes desarmer avant la campagne (`unset " + " ".join(a.split("=")[0] for a in armed)
            + "`). W40K_MASK_VERIFY a ete mesuree a x4,7 (niveau 1) et x17 (niveau 2) : une "
            "campagne lancee avec ne mesure pas ce qu'elle annonce, et rien dans la sortie ne le "
            "signalerait."
        )


# La barre de progression de `training_callbacks.py` porte les grandeurs que les bancs
# d'entrainement lisent : le compteur d'episodes, le chronometre `[MM:SS<` (origine : debut de
# `learn()`), et `moy` = secondes d'entrainement par episode produit, hors evaluation bot.
# Le format est celui d'un affichage destine a l'oeil ; il a change deux fois entre le 2026-08-01
# et le 2026-08-02. C'est assume : les bancs ARRETENT la campagne quand ils ne trouvent plus ces
# motifs, au lieu de retomber sur une grandeur approchante. Une ligne de cloture machine-lisible
# cote train.py supprimerait ce risque.
# Les deux captures viennent du MEME rafraichissement : lire le compteur et `moy` par deux regex
# separees les apparierait au petit bonheur.
# `, k/N slots` : segment d'AMORCAGE, present tant que les `n_envs` slots n'ont pas tous rendu
# un episode (training_callbacks.py, `slots_note`). Optionnel dans le motif, sinon ces
# rafraichissements-la ne matchent plus du tout et disparaissent de `points` en silence — un
# format non reconnu doit ARRETER la campagne, jamais retirer discretement des mesures.
_PROGRESS_RE = re.compile(
    r"(\d+)/\d+ \[[\d:]+<[\d:]+\] \[s/ep \((\d+) env(?:, \d+/\d+ slots)?\): "
    r"cur [\d.]+, moy ([\d.]+)"
)
_LOOP_ELAPSED_RE = re.compile(r"\[(\d+):(\d\d)(?::(\d\d))?<")


def read_steady_rate(output: str) -> tuple:
    """Rend (secondes par episode en REGIME ETABLI, n_envs, episodes de la fenetre de mesure).

    POURQUOI PAS `moy` DIRECTEMENT — c'est un rapport CUMULE, donc une moyenne sur TOUT le run,
    demarrage compris (caches froids, premieres mises a jour PPO). Un banc A/B compare des regimes
    ETABLIS : c'est la derivee qu'on veut, pas l'integrale, et la difference entre deux
    rafraichissements la rend directement.

    Le stock d'episodes EN VOL, lui, n'entre plus dans le calcul : `moy` retranche desormais a son
    numerateur le temps deja investi dans les episodes non termines (training_callbacks.py). Il
    gonflait auparavant d'environ `n_envs / episodes` — 33 % a n_envs=48 sur 144 episodes contre
    4 % a n_envs=6 — un biais qui suivait l'axe classe et fabriquait une pente sur les campagnes
    qui balaient `n_envs`. La difference l'annulait deja par construction (un stock constant
    disparait dans une soustraction) et continue de le faire pour son residu de fluctuation.

    Elimine aussi la phase de remplissage initiale (aucun episode termine tant que le premier
    slot n'a pas fini) : les affichages anterieurs a `n_envs` episodes sont ecartes.

    `elapsed` est reconstitue par `moy x episodes` plutot que lu dans `[MM:SS<` : `moy` a trois
    decimales, le chronometre affiche la seconde. Sur une fenetre de 27 s, la seconde vaut 3,7 %.
    """
    points = [
        (int(episodes), int(n_envs), float(rate))
        for episodes, n_envs, rate in _PROGRESS_RE.findall(output)
    ]
    if len(points) < 2:
        raise SystemExit(
            f"{len(points)} rafraichissement(s) de barre exploitable(s) dans la sortie : il en "
            f"faut au moins deux pour mesurer un regime etabli. Le run s'est-il arrete tot, ou le "
            f"format de la barre a-t-il change (training_callbacks.py) ?"
        )
    n_envs = points[-1][1]
    if any(point[1] != n_envs for point in points):
        raise SystemExit(
            f"`n_envs` change en cours de run dans la barre ({sorted({p[1] for p in points})}) : "
            f"les rafraichissements ne decrivent pas la meme configuration."
        )
    # Avant que chaque slot ait termine un episode, le parallelisme n'est pas etabli : ces
    # rafraichissements-la decrivent le remplissage, pas le regime.
    usable = [point for point in points if point[0] >= n_envs]
    if len(usable) < 2:
        raise SystemExit(
            f"aucune fenetre exploitable : la barre n'a rendu que {len(usable)} rafraichissement(s) "
            f"au-dela de {n_envs} episodes. Le run est trop court devant `n_envs` — prendre "
            f"--episodes >= {4 * n_envs} pour que le regime etabli existe."
        )
    first_episodes, _, first_rate = usable[0]
    last_episodes, _, last_rate = usable[-1]
    span = last_episodes - first_episodes
    if span < n_envs:
        raise SystemExit(
            f"fenetre de mesure de {span} episodes pour n_envs={n_envs} : trop courte pour que "
            f"la difference soit stable (il faut au moins une vague complete de slots). "
            f"Augmenter --episodes."
        )
    rate = (last_rate * last_episodes - first_rate * first_episodes) / span
    if rate <= 0.0:
        raise SystemExit(
            f"regime etabli calcule a {rate:.6f} s/ep : les deux rafraichissements retenus "
            f"({first_episodes} et {last_episodes} episodes) sont incoherents."
        )
    # `moy` est arrondi a 3 decimales : l'erreur sur la difference vaut 0,0005 x (ep1 + ep2) / span.
    quantisation = 0.0005 * (first_episodes + last_episodes) / span / rate
    if quantisation > 0.01:
        print(
            f"AVERTISSEMENT : l'arrondi de `moy` represente {quantisation * 100:.1f} % du regime "
            f"mesure (fenetre {first_episodes}->{last_episodes} episodes). Un ecart plus fin que "
            f"cela n'est pas mesurable ; allonger --episodes.",
            flush=True,
        )
    return rate, n_envs, (first_episodes, last_episodes)


def read_loop_elapsed(output: str) -> float:
    """Secondes ecoulees dans la boucle au dernier rafraichissement, lues dans `[MM:SS<`.

    Sert a AFFICHER la part de demarrage (`wall du process - cette valeur`), jamais au verdict :
    la resolution est la seconde. Le verdict passe par `read_steady_rate`, plus fin.
    Sa presence prouve aussi que la boucle a tourne : sans elle, le process s'est arrete avant le
    premier episode et son wall-clock ne mesure pas un entrainement.
    """
    matches = _LOOP_ELAPSED_RE.findall(output)
    if not matches:
        raise SystemExit(
            "aucun compteur de progression `[MM:SS<` dans la sortie : la barre a-t-elle change "
            "de format, ou le run s'est-il arrete avant le premier episode ?"
        )
    hours_or_minutes, minutes_or_seconds, seconds = matches[-1]
    if seconds:
        return int(hours_or_minutes) * 3600 + int(minutes_or_seconds) * 60 + int(seconds)
    return int(hours_or_minutes) * 60 + int(minutes_or_seconds)


def validate_paires(paires: int) -> None:
    """Impose un nombre de paires permettant d'annuler la derive (cf. `drift_cancelled`)."""
    if paires < 3 or paires % 2 == 0:
        raise SystemExit(
            "--paires doit etre impair et >= 3 : la premiere paire est jetee (remplissage des "
            "caches), et les ratios retenus doivent etre en nombre PAIR pour former des couples "
            "d'ordres opposes (BA,AB) — c'est le couple, pas la mediane, qui annule la derive."
        )


def drift_cancelled(ratios: list) -> tuple[float, list]:
    """Rend (estimation finale, estimations par couple) a partir des ratios retenus.

    Les ratios retenus alternent d'ordre d'execution : BA, AB, BA, AB... Une derive monotone de
    la machine multiplie le second run de chaque paire par un facteur k ; elle biaise donc le
    ratio B/A de k dans un sens quand B passe en second, et de 1/k dans l'autre. La MOYENNE
    GEOMETRIQUE d'un couple (BA, AB) annule ce facteur — c'est la seule operation qui le fait.

    Une mediane sur l'ensemble des ratios ne l'annule PAS : elle trie par valeur, pas par ordre
    d'execution, et peut donc selectionner deux mesures du meme ordre. D'ou le decoupage en
    couples d'abord, mediane des couples ensuite (robustesse a une paire aberrante).
    """
    couples = [math.sqrt(ratios[i] * ratios[i + 1]) for i in range(0, len(ratios), 2)]
    return statistics.median(couples), couples


def print_spread(couples: list) -> None:
    """Affiche l'etendue des couples, ou dit pourquoi il n'y en a pas. Partage par les 3 bancs.

    Une "etendue" calculee sur UN couple vaut exactement zero et se lit comme une mesure
    resserree, alors qu'elle ne dit rien : c'est le meme echantillon repete deux fois par min() et
    max(). Le garde-fou "l'etendue enjambe 1.000" n'existe donc qu'a partir de deux couples,
    c'est-a-dire 5 paires (la premiere est jetee, et les ratios retenus vont par couples
    d'ordres opposes).
    """
    if len(couples) < 2:
        print(
            "UN SEUL COUPLE : mesure NON REPLIQUEE, aucune etendue calculable. Ce chiffre n'est "
            "pas verifiable — relancer avec --paires 5 au minimum."
        )
        return
    print(f"etendue des couples {min(couples):.3f}-{max(couples):.3f}")
    if min(couples) < 1.0 < max(couples):
        print(
            "L'ETENDUE ENJAMBE 1.000 : cette mesure ne tranche pas. Augmenter --episodes et "
            "--paires avant d'en conclure quoi que ce soit, dans un sens comme dans l'autre."
        )


def _run(cwd: str, episodes: int) -> tuple[float, float, str]:
    """Un run complet ; rend (wall, cpu, compteur de masques)."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "scripts/refactor_fingerprint.py", "--episodes", str(episodes)],
        cwd=cwd, capture_output=True, text=True,
    )
    wall = time.perf_counter() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    if proc.returncode != 0:
        raise SystemExit(f"echec dans {cwd} :\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
    masks = re.search(r'"action_mask": (\d+)', proc.stdout)
    return wall, cpu, masks.group(1) if masks else "-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--avant", default="/tmp/40k-avant", help="arbre de travail de reference")
    parser.add_argument("--apres", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--episodes", type=int, default=24)
    # 5, pas 3 : a 3 paires il ne reste que 2 ratios, donc UN couple, et l'etendue affichee est
    # de largeur nulle (cf. `print_spread`). Le verdict median existe des 3 paires, mais rien ne
    # permet alors de savoir s'il est stable.
    parser.add_argument("--paires", type=int, default=5)
    args = parser.parse_args()

    assert_clean_environment()

    if not os.path.isdir(args.avant):
        raise SystemExit(
            f"arbre de reference absent. Le creer une fois :\n"
            f"    git -C {args.apres} worktree add {args.avant} HEAD"
        )
    validate_paires(args.paires)

    ratios = []
    for index in range(1, args.paires + 1):
        # Ordre alterne A,B puis B,A : lance toujours dans le meme ordre, une derive monotone de
        # la machine (temperature, charge de fond qui s'installe) penalise systematiquement le
        # second des deux, et le biais est alors de meme signe dans toutes les paires. Les deux
        # ordres sont ensuite apparies par `drift_cancelled` : c'est la que le biais s'annule.
        b_first = index % 2 == 0
        if b_first:
            wall_b, cpu_b, masks_b = _run(args.apres, args.episodes)
            wall_a, cpu_a, masks_a = _run(args.avant, args.episodes)
        else:
            wall_a, cpu_a, masks_a = _run(args.avant, args.episodes)
            wall_b, cpu_b, masks_b = _run(args.apres, args.episodes)
        ratio = cpu_b / cpu_a
        print(
            f"paire {index} ({'B puis A' if b_first else 'A puis B'})"
            f"{' — jetee' if index == 1 else ''}\n"
            f"  A(avant) cpu={cpu_a:6.2f}s  wall={wall_a:6.2f}s  masques={masks_a}\n"
            f"  B(apres) cpu={cpu_b:6.2f}s  wall={wall_b:6.2f}s  masques={masks_b}\n"
            f"  ratio CPU B/A = {ratio:.3f}",
            flush=True,
        )
        if index > 1:
            ratios.append(ratio)

    median, couples = drift_cancelled(ratios)
    print(
        f"\nratios retenus (BA,AB,...) : {[round(r, 3) for r in ratios]}\n"
        f"couples sans derive        : {[round(c, 3) for c in couples]}\n"
        f"VERDICT = {median:.3f}  ->  {'gain' if median < 1 else 'PERTE'} de "
        f"{abs(1 - median) * 100:.1f} % de temps CPU"
    )
    print_spread(couples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
