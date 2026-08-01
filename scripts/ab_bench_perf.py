#!/usr/bin/env python3
"""A/B APPARIE PAR GRAINE sur un hyperparametre — grandeur mesuree : la QUALITE de l'apprentissage.

CE BANC REPOND A : « a budget d'episodes EGAL, laquelle des deux valeurs produit le meilleur
modele ? » La reponse est un ecart de win-rate contre les bots du holdout, pas un temps.

POURQUOI CE N'EST PAS UNE OPTION DE `ab_bench_param.py`
-------------------------------------------------------
Tout differe sauf le fait de lancer `train.py` deux fois :
- la GRANDEUR : win-rate final, pas wall-clock ;
- l'EVALUATION BOT, que le banc de debit eteint d'office parce qu'elle ecrase sa mesure, est ici
  la mesure elle-meme ;
- la SOURCE DE BRUIT : la machine ne fait plus rien au resultat (un modele est le meme qu'il ait
  ete entraine vite ou lentement). Le bruit vient de l'apprentissage — initialisation du reseau,
  ordre des lots, tirages du moteur. Il ne s'annule donc PAS en lancant les deux cotes coup sur
  coup, mais en REPETANT la comparaison sur plusieurs graines ;
- par consequent : pas de premiere paire jetee (aucun cache disque n'influence un win-rate), pas
  de moyenne geometrique de ratios (`drift_cancelled` annule une derive MACHINE, qui n'existe pas
  ici), pas de contrainte de divisibilite des episodes par `n_envs` — c'est le nombre d'episodes
  vus qui doit etre egal des deux cotes, et il l'est par `--total-episodes`.

CE QUE CE BANC IMPOSE
---------------------
1. APPARIEMENT PAR GRAINE. Chaque graine donne UN couple (A, B) entraine avec la meme graine des
   deux cotes ; le verdict porte sur les ecarts intra-couple. Comparer des win-rates de graines
   differentes, c'est mesurer la variance de l'initialisation.
2. ORDRE ALTERNE quand meme (A,B puis B,A...). Inutile pour la mesure, utile pour l'echec : si la
   campagne est interrompue, les runs perdus ne sont pas tous du meme cote.
3. MEME BUDGET D'EPISODES des deux cotes (`--episodes`), sinon on compare aussi la duree
   d'entrainement.
4. EVALUATION FINALE SEULE, sur le pool `holdout` (impose par `train.py`), deterministe. L'eval
   PERIODIQUE est repoussee hors de portee : elle ne sert a rien ici et coute des sous-processus.
5. ARBRE DE TRAVAIL SECONDAIRE : chaque run ecrit `ai/models/<agent>/model_<agent>.zip`, protege.
6. SCENARIO `bot`, `self` ou `all` UNIQUEMENT : les autres chemins de `train.py` ignorent
   `--total-episodes` (cf. `ab_train_common`), et « a budget d'episodes egal » serait faux.
7. COMBINED RECONSTITUE EN PLEINE PRECISION depuis les compteurs W/L/D et les poids d'evaluation,
   puis verifie contre le pourcentage affiche : l'arrondi a 0,1 point du bloc final fabriquerait
   des ex aequo, et un ex aequo suffit a faire jeter un resultat unanime a 5 graines.

CE QUE CE BANC NE FAIT PAS
--------------------------
- Il ne rend PAS le resultat reproductible. `model_params.seed` fixe l'initialisation et les
  tirages, mais un run a `n_envs` sous-processus asynchrones n'est pas deterministe bit-a-bit. La
  graine sert a ECHANTILLONNER la variance de facon appariee, pas a l'annuler.
- Il ne verifie pas la fiabilite interne de l'evaluation (`eval_reliable`,
  `total_failed_episodes`) : `train.py` calcule ces cles mais ne les imprime pas dans le bloc
  final, et ce banc ne lit que ce qui est imprime.
- Il ne dit rien du temps. Une valeur peut gagner 3 points de win-rate en doublant la duree du
  run : c'est `ab_bench_param.py` qui le mesure.

LE COUT EST LE POINT DUR
------------------------
Un couple = 2 entrainements COMPLETS + 2 evaluations finales. L'evaluation seule a ete mesuree a
plus de 13 min pour 100 episodes par bot. Cinq graines, c'est dix runs. Dimensionner `--episodes`
et `--eval-episodes` en consequence, et savoir que `--eval-episodes` trop bas rend le verdict
illisible : a 100 episodes par bot, l'ecart-type binomial d'un win-rate autour de 50 % est de
5 points — un ecart de 2 points ne veut alors rien dire. Le banc reimprime ce bruit a la fin.

USAGE
-----
    git worktree add /tmp/40k-bench HEAD
    python3 scripts/ab_bench_perf.py --param model_params.batch_size --a 1024 --b 2048 \\
        --episodes 2000 --graines 1,2,3,4,5 --eval-episodes 100 --training-config x1
    git worktree remove /tmp/40k-bench
"""

from __future__ import annotations

import argparse
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_train_common import (  # noqa: E402
    RunFailed,
    assert_effective,
    assert_not_scheduled,
    assert_provable,
    assert_scenario_supported,
    assert_worktree,
    config_lookup,
    parse_value,
    read_phase_config,
    run_training,
)

# "  vs control             :  45.0% (9W-11L-0D)" — les compteurs W/L/D sont la vraie donnee,
# le pourcentage n'en est qu'un arrondi d'affichage.
_BOT_RE = re.compile(r"^\s+vs (\S+)\s*:\s*([\d.]+)%\s*\((\d+)W-(\d+)L-(\d+)D\)", re.MULTILINE)
_COMBINED_RE = re.compile(r"Combined Score:\s*([\d.]+)%")


def _scores(output: str, weights: dict) -> dict:
    """Win-rates du bloc FINAL BOT EVALUATION, en PLEINE PRECISION.

    Le bloc final imprime les win-rates arrondis a 0,1 point (train.py:3368-3372). Cet arrondi
    fabrique des ex aequo qui n'existent pas : dans un test des signes, un ex aequo est ecarte, et
    a 5 graines — le plancher impose ici — un seul suffit a plafonner p a 0,125 et a faire jeter
    un resultat unanime.
    La meme ligne imprime les compteurs entiers (`9W-11L-0D`), d'ou se recalcule exactement ce que
    `bot_evaluation` a calcule : `win_rate = wins / (wins + losses + draws)` (bot_evaluation.py:
    1167) puis `combined = somme(poids * win_rate)` (:1208). Les poids viennent de
    `callback_params.bot_eval_weights` de la config resolue.
    La reconstitution est VERIFIEE contre le `Combined Score` affiche : si les deux divergent de
    plus que l'arrondi, la formule ou les poids ont bouge et le banc s'arrete au lieu de comparer
    une grandeur qui ne serait plus celle du projet.

    L'absence du bloc n'est pas une donnee manquante mais une mesure inexistante : sans lui, le
    run n'a pas ete evalue et il n'y a rien a comparer.
    """
    printed = _COMBINED_RE.search(output)
    if printed is None:
        raise SystemExit(
            "aucun 'Combined Score' dans la sortie : l'evaluation finale n'a pas tourne "
            "(bot_eval_final a 0 ?) ou le format du bloc a change."
        )
    rows = _BOT_RE.findall(output)
    if not rows:
        raise SystemExit(
            "'Combined Score' present mais aucune ligne 'vs <bot> : x% (nW-nL-nD)' : le bloc "
            "d'evaluation a change de format, les compteurs ne sont plus lisibles."
        )
    scores = {}
    for name, _percent, wins, losses, draws in rows:
        total = int(wins) + int(losses) + int(draws)
        if total == 0:
            raise SystemExit(f"bot {name} : 0 episode joue, le win-rate affiche n'est pas une mesure.")
        scores[name] = 100.0 * int(wins) / total
    missing = [name for name in weights if name not in scores]
    if missing:
        raise SystemExit(
            f"bots ponderes absents du bloc d'evaluation : {missing}. Le combined reconstitue ne "
            f"serait pas celui du projet."
        )
    combined = sum(weights[name] * scores[name] for name in weights)
    if abs(combined - float(printed.group(1))) > 0.06:
        raise SystemExit(
            f"combined reconstitue {combined:.3f} % contre {printed.group(1)} % affiche : l'ecart "
            f"depasse l'arrondi d'affichage. La formule (bot_evaluation.py:1208) ou les poids ont "
            f"change ; le banc ne comparerait plus la grandeur de selection du projet."
        )
    scores["combined"] = combined
    return scores


def _sign_test(deltas: list) -> tuple:
    """Test des signes exact sur les ecarts apparies. Rend (positifs, negatifs, p bilateral).

    Choisi plutot qu'un test de Student : avec 5 graines, l'hypothese de normalite n'est pas
    verifiable et le t donnerait une precision decorative. Le test des signes ne suppose rien
    d'autre que l'appariement, au prix d'une puissance faible — d'ou le plancher a 5 graines
    (tous les ecarts de meme signe donnent alors p = 0,0625, jamais moins).
    """
    positive = sum(1 for d in deltas if d > 0)
    negative = sum(1 for d in deltas if d < 0)
    trials = positive + negative
    if trials == 0:
        return positive, negative, 1.0
    smaller = min(positive, negative)
    tail = sum(math.comb(trials, k) for k in range(smaller + 1)) / (2 ** trials)
    return positive, negative, min(1.0, 2 * tail)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/40k-bench", help="arbre de travail secondaire")
    parser.add_argument("--param", required=True, help="chemin complet, ex. model_params.batch_size")
    parser.add_argument("--a", required=True, help="valeur du cote A")
    parser.add_argument("--b", required=True, help="valeur du cote B")
    parser.add_argument("--episodes", type=int, required=True, help="budget d'episodes par run")
    parser.add_argument("--graines", default="1,2,3,4,5", help="graines, separees par des virgules")
    parser.add_argument("--eval-episodes", type=int, default=100, help="episodes par bot, eval finale")
    parser.add_argument("--agent", default="ArmageddonAgent")
    parser.add_argument("--scenario", default="bot")
    parser.add_argument("--training-config", default="x1", help="phase de config d'entrainement")
    parser.add_argument("--timeout", type=float, default=None, help="delai par run, en secondes")
    parser.add_argument(
        "--autoriser-suppression-schedule", action="store_true",
        help="accepte de mesurer une cle declaree en schedule dans la config (le schedule est "
             "alors supprime des DEUX cotes : le verdict ne porte plus sur le regime de prod)",
    )
    args = parser.parse_args()

    if args.a == args.b:
        raise SystemExit("--a et --b identiques : rien a comparer.")
    if args.eval_episodes < 1:
        raise SystemExit("--eval-episodes doit etre >= 1 : sans evaluation finale, aucune mesure.")
    seeds = [int(s) for s in args.graines.split(",") if s.strip()]
    if len(seeds) < 5:
        raise SystemExit(
            f"{len(seeds)} graine(s) : insuffisant. Le test des signes ne peut pas descendre sous "
            f"p = 2 x 0,5^n, soit 0,25 a 3 graines et 0,125 a 4 : meme un resultat parfaitement "
            f"unanime serait alors ininterpretable. Minimum 5."
        )
    if len(set(seeds)) != len(seeds):
        raise SystemExit("graines dupliquees : deux couples identiques ne sont pas deux mesures.")
    if args.param in ("model_params.seed", "agent_seat_seed"):
        raise SystemExit(
            f"{args.param} est le bloc de repetition de ce banc, pas la variable comparee : il "
            f"est fixe par --graines des deux cotes."
        )

    repo = assert_worktree(args.repo, args.agent)
    assert_scenario_supported(args.scenario)
    assert_provable(args.param)
    phase_block = read_phase_config(repo, args.agent, args.training_config)
    for value in (args.a, args.b):
        assert_not_scheduled(phase_block, args.param, value, args.autoriser_suppression_schedule)
    try:
        weights = {
            name: float(w)
            for name, w in config_lookup(phase_block, "callback_params.bot_eval_weights").items()
        }
    except KeyError:
        raise SystemExit(
            "callback_params.bot_eval_weights absent de la config de phase resolue : le combined "
            "n'est pas reconstituable en pleine precision."
        )
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise SystemExit(
            f"bot_eval_weights ne somme pas a 1.0 ({sum(weights.values())}) : bot_evaluation "
            f"refuserait cette configuration (bot_evaluation.py:123)."
        )

    wanted = {"A": parse_value(args.a), "B": parse_value(args.b)}
    values = {"A": args.a, "B": args.b}

    def one(side: str, seed: int) -> dict:
        result = run_training(
            repo, args.agent, args.scenario, args.training_config, args.episodes,
            overrides=[
                (args.param, values[side]),
                # Deux graines distinctes, deux roles distincts : `model_params.seed` initialise
                # le reseau et les tirages PPO, `agent_seat_seed` fixe la repartition des sieges
                # et le tirage des adversaires (train.py:2458). Les faire varier ensemble
                # echantillonne les deux sources de variance ; n'en fixer qu'une laisserait
                # l'autre libre et gonflerait le bruit intra-couple.
                ("model_params.seed", str(seed)),
                ("agent_seat_seed", str(seed)),
            ],
            bot_eval_final=args.eval_episodes,
            timeout=args.timeout,
        )
        assert_effective(result, args.param, wanted[side])
        assert_effective(result, "model_params.seed", seed)
        # `agent_seat_seed` n'apparait pas dans le modele sauvegarde : la seule trace disponible
        # est la ligne d'override de train.py:1484. C'est une preuve AMONT (l'override a bien ete
        # applique a la config chargee), plus faible que celle du zip — elle ne dit pas qu'aucune
        # surcharge ulterieure ne l'a ecrasee.
        if f"Override: agent_seat_seed = {seed}" not in result["output"]:
            raise SystemExit(
                f"train.py n'a pas annonce l'override agent_seat_seed = {seed} : les deux cotes "
                f"du couple ne partagent peut-etre pas la meme graine de sieges."
            )
        return result

    rows = []
    for index, seed in enumerate(seeds, start=1):
        b_first = index % 2 == 0
        try:
            if b_first:
                run_b, run_a = one("B", seed), one("A", seed)
            else:
                run_a, run_b = one("A", seed), one("B", seed)
        except RunFailed as failure:
            # Un run perdu, c'est un couple perdu : l'appariement est tout ce qui rend l'ecart
            # interpretable. La campagne s'arrete, les couples deja obtenus restent affiches.
            print(f"\nCAMPAGNE INTERROMPUE a la graine {seed} : {failure}", flush=True)
            break
        score_a = _scores(run_a["output"], weights)
        score_b = _scores(run_b["output"], weights)
        # Deux ensembles de bots differents, ce sont deux grandeurs differentes : le `combined`
        # des deux cotes ne porterait pas sur la meme opposition, et l'ecart injecte dans le test
        # des signes serait un artefact. Le cas est possible — `active_bot_names` suit les poids
        # de la config, qu'un override pourrait toucher — donc il est verifie, pas suppose.
        if set(score_a) != set(score_b):
            raise SystemExit(
                f"graine {seed} : bots evalues differents entre A ({sorted(set(score_a))}) et B "
                f"({sorted(set(score_b))}). Les deux combined ne sont pas comparables."
            )
        delta = score_b["combined"] - score_a["combined"]
        rows.append({"seed": seed, "a": score_a, "b": score_b, "delta": delta})
        bots = sorted(k for k in score_a if k != "combined")
        print(
            f"graine {seed} ({'B puis A' if b_first else 'A puis B'})\n"
            f"  A({args.param}={args.a}) combined={score_a['combined']:6.2f}%  "
            + "  ".join(f"{b}={score_a[b]:.0f}" for b in bots) + "\n"
            f"  B({args.param}={args.b}) combined={score_b['combined']:6.2f}%  "
            + "  ".join(f"{b}={score_b[b]:.0f}" for b in bots) + "\n"
            f"  ecart B-A = {delta:+.2f} points",
            flush=True,
        )

    if len(rows) < 5:
        raise SystemExit(
            f"\n{len(rows)} couple(s) complet(s) : moins que les 5 exiges, aucun verdict rendu."
        )

    deltas = [row["delta"] for row in rows]
    positive, negative, p_value = _sign_test(deltas)
    # Bruit d'echantillonnage de l'evaluation, a ne pas confondre avec la variance d'apprentissage
    # que les graines echantillonnent : celui-ci vient du nombre fini de parties jouees PAR BOT.
    noise = 1.96 * math.sqrt(0.25 / args.eval_episodes) * 100
    print(
        f"\necarts B-A par graine : {[round(d, 2) for d in deltas]}\n"
        f"mediane               : {statistics.median(deltas):+.2f} points\n"
        f"signes                : {positive} en faveur de B, {negative} en faveur de A "
        f"(test des signes bilateral, p = {p_value:.3f})\n"
        f"bruit d'evaluation    : +/- {noise:.1f} points par bot a {args.eval_episodes} episodes "
        f"(IC 95 % autour de 50 %)"
    )
    if p_value > 0.10:
        print(
            "LES SIGNES NE TRANCHENT PAS : ajouter des graines. Un ecart median non nul sans "
            "unanimite des signes n'est pas un resultat."
        )
    else:
        better = args.b if statistics.median(deltas) > 0 else args.a
        print(f"VERDICT : {args.param}={better} l'emporte a budget d'episodes egal.")
    print(
        "RAPPEL : verdict de QUALITE a budget d'episodes egal. Il ne dit rien du temps passe — "
        "pour cela, scripts/ab_bench_param.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
