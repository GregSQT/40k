#!/usr/bin/env python3
"""A/B ENTRELACE sur N'IMPORTE QUEL hyperparametre — grandeur mesuree : le DEBIT (wall-clock).

CE BANC REPOND A UNE SEULE QUESTION : « cette valeur fait-elle tourner l'entrainement plus vite ? »
Il ne dit RIEN de ce qui est appris. Pour comparer deux valeurs sur la QUALITE de l'apprentissage
(batch_size, learning_rate, n_epochs...), c'est `ab_bench_perf.py` : grandeur, protocole et cout
y sont differents, et un verdict de debit sur ces parametres-la repondrait a cote de la question.

QUEL PARAMETRE RELEVE DE QUEL BANC
----------------------------------
- CE BANC (l'apprentissage change peu ou pas, seul le temps change) : `n_envs`.
- CE BANC AVEC PRECAUTION (le temps ET l'apprentissage changent : un gain de debit peut se payer
  en qualite, et ce banc-ci ne le verra pas) : `model_params.n_steps`, `model_params.n_epochs`,
  `model_params.batch_size`.
- L'AUTRE BANC (le temps ne bouge presque pas, tout se joue sur l'apprentissage) :
  `model_params.learning_rate`, `gamma`, `gae_lambda`, `ent_coef`, et `batch_size` des qu'on
  cherche mieux plutot que plus vite.

`batch_size` merite un mot, c'est la premiere idee qui vient : a `n_steps` fixe il ne change pas
le nombre d'echantillons traites, seulement le decoupage en minilots. Son effet sur le wall-clock
est faible ; son effet sur l'apprentissage ne l'est pas. Le mesurer ici n'est pas faux, c'est
inutile.

CE QUE CE BANC IMPOSE (identique a `ab_bench_nenvs.py`, dont il generalise le protocole)
-----------------------------------------------------------------------------------------
1. ENTRELACEMENT, ORDRE ALTERNE (A,B puis B,A...). Sur cette machine deux executions du MEME code
   peuvent differer d'un facteur 2. Seuls les deux membres d'une meme paire, lances coup sur
   coup, sont comparables ; l'ordre s'inverse d'une paire a l'autre pour qu'une derive monotone
   ne penalise pas toujours le meme cote. La premiere paire est jetee (caches disque, allocateur).
2. WALL, et rien que le wall — mais RAPPORTE AU NOMBRE D'EPISODES REELLEMENT JOUES, lu dans la
   cloture du run. Les `n_envs` slots ne terminent pas ensemble : un run depasse son budget d'un
   surplus qui depend de la configuration, et comparer deux walls bruts attribuerait ce surplus
   au parametre mesure. Pas de CPU : `getrusage(RUSAGE_CHILDREN)` ne compte pas les workers
   `SubprocVecEnv` arretes en fin de run (mesure : 33,7 s de CPU annoncees pour 530 s de wall a
   `n_envs=48`) ; un chiffre faux est plus nuisible qu'un chiffre absent.
3. LE DEMARRAGE EST COMPTE et n'est pas isolable — le compteur `[MM:SS<` de la barre est
   retro-date d'une somme de durees PAR SLOT et ne se compare a aucun wall-clock.
4. EXECUTION DANS UN ARBRE DE TRAVAIL SECONDAIRE : un entrainement ecrit
   `ai/models/<agent>/model_<agent>.zip`, fichier protege.
5. EVALUATION BOT DESACTIVEE sur ses deux chemins (periodique et finale). Elle lance ses propres
   sous-processus pendant le chronometre, pour un cout etranger au parametre compare, et son
   poids est ecrasant : 6 episodes d'entrainement = 21 s, evaluation finale > 13 min.
6. SCENARIO `bot`, `self` ou `all` UNIQUEMENT : les autres chemins de `train.py` ignorent
   `--total-episodes` (cf. `ab_train_common`), le banc mesurerait alors le budget de la config.
7. ENVIRONNEMENT PROPRE : `subprocess` herite du shell, et une variable `W40K_*` de verification
   ou d'instrumentation y ralentit chaque run sans laisser de trace dans la sortie. Le banc
   refuse de demarrer tant qu'une seule est armee (cf. `assert_clean_environment`).

CONTROLE ANTI-CONFUSION
-----------------------
Apres chaque run, la valeur EFFECTIVEMENT instanciee par PPO est relue dans le modele sauvegarde
et comparee a la valeur demandee (cf. `ab_train_common`). Un ecart arrete la campagne : sans ce
garde-fou, une surcharge de config silencieuse ferait mesurer deux fois la meme configuration.
Corollaire : ce banc n'accepte que les parametres dont la valeur effective est prouvable, et il
refuse les autres au lieu de les mesurer a l'aveugle.

DIFFERENCE AVEC `ab_bench_nenvs.py` : celui-ci reste l'outil de reference pour `n_envs` (sa preuve
passe par le message "Creating K parallel environments" et il porte les contre-mesures ecrites
pour ce parametre). Ce banc-ci couvre les autres, avec le meme protocole et une preuve aval.

USAGE
-----
    git worktree add /tmp/40k-bench HEAD        # une fois
    python3 scripts/ab_bench_param.py --param model_params.n_steps --a 8192 --b 4096 \\
        --episodes 96 --paires 5 --training-config x1
    git worktree remove /tmp/40k-bench          # a la fin

`--param` prend le CHEMIN COMPLET dans la config (`model_params.batch_size`), pas l'alias court
de `train.py --param`. `--training-config` doit etre la phase du run a optimiser : elle fixe
`n_steps`/`batch_size`, donc mesurer `x1` pour regler un run `x5_new` repond a une autre question.
"""

from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ab_bench import drift_cancelled, print_spread, validate_paires  # noqa: E402
from ab_train_common import (  # noqa: E402
    RunFailed,
    assert_effective,
    assert_clean_environment,
    assert_not_scheduled,
    assert_provable,
    assert_scenario_supported,
    assert_worktree,
    config_lookup,
    parse_value,
    read_phase_config,
    run_training,
)


def _planned_n_envs(phase_block: dict, param: str, value: str) -> int:
    """n_envs que ce cote va utiliser : la valeur comparee si c'est elle, sinon celle de la phase.

    Sert au controle de divisibilite des episodes. Une cle absente leve : deviner un n_envs
    reviendrait a valider un `--episodes` qui laisse des episodes a moitie joues.
    """
    if param == "n_envs":
        return int(value)
    try:
        n_envs = config_lookup(phase_block, "n_envs")
    except KeyError:
        raise SystemExit(
            "la config de phase ne declare pas n_envs : impossible de verifier que --episodes "
            "est divisible par le nombre d'environnements, donc impossible de garantir que les "
            "deux cotes terminent le meme nombre d'episodes."
        )
    if not isinstance(n_envs, int) or isinstance(n_envs, bool):
        raise SystemExit(f"n_envs de la config de phase n'est pas un entier : {n_envs!r}")
    return n_envs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/tmp/40k-bench", help="arbre de travail secondaire")
    parser.add_argument("--param", required=True, help="chemin complet, ex. model_params.n_steps")
    parser.add_argument("--a", required=True, help="valeur du cote A")
    parser.add_argument("--b", required=True, help="valeur du cote B")
    parser.add_argument("--episodes", type=int, default=96)
    # 5, pas 3 : a 3 paires il ne reste que 2 ratios, donc UN seul couple, et l'etendue affichee
    # en fin de campagne serait de largeur nulle — un echantillon unique presente comme un
    # resultat resserre. Le garde-fou "l'etendue enjambe 1.000" ne commence a exister qu'a 5.
    parser.add_argument("--paires", type=int, default=5)
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
    assert_clean_environment()
    repo = assert_worktree(args.repo, args.agent)
    assert_scenario_supported(args.scenario)
    assert_provable(args.param)
    validate_paires(args.paires)

    phase_block = read_phase_config(repo, args.agent, args.training_config)
    for value in (args.a, args.b):
        assert_not_scheduled(
            phase_block, args.param, value, args.autoriser_suppression_schedule
        )

    envs_a = _planned_n_envs(phase_block, args.param, args.a)
    envs_b = _planned_n_envs(phase_block, args.param, args.b)
    # Un run s'arrete au budget d'episodes ; si celui-ci n'est pas divisible par le nombre d'envs,
    # certains slots laissent un episode a moitie joue et le cote qui en laisse le plus est
    # avantage. Le controle vaut aussi quand n_envs n'est PAS le parametre compare : il vient
    # alors de la config, et rien ne garantit qu'il divise --episodes.
    if args.episodes % envs_a or args.episodes % envs_b:
        lcm = envs_a * envs_b // math.gcd(envs_a, envs_b)
        raise SystemExit(
            f"--episodes {args.episodes} n'est pas divisible par n_envs des deux cotes "
            f"({envs_a} et {envs_b}) : le run laisserait des episodes a moitie joues, "
            f"inegalement des deux cotes. Prendre un multiple de {lcm}."
        )

    wanted_a = parse_value(args.a)
    wanted_b = parse_value(args.b)

    def one(value: str, wanted) -> dict:
        result = run_training(
            repo, args.agent, args.scenario, args.training_config, args.episodes,
            overrides=[(args.param, value)], bot_eval_final=0, timeout=args.timeout,
        )
        assert_effective(result, args.param, wanted)
        return result

    ratios = []
    for index in range(1, args.paires + 1):
        b_first = index % 2 == 0
        # Ce banc compare DEUX configurations : perdre un run, c'est perdre la paire et donc toute
        # comparabilite. L'echec arrete la campagne.
        try:
            if b_first:
                run_b = one(args.b, wanted_b)
                run_a = one(args.a, wanted_a)
            else:
                run_a = one(args.a, wanted_a)
                run_b = one(args.b, wanted_b)
        except RunFailed as failure:
            raise SystemExit(str(failure))
        # Ratio de TEMPS PAR EPISODE, pas de wall brut : les `n_envs` slots ne terminent pas au
        # meme instant, donc un run depasse legerement son budget, d'un depassement qui depend de
        # la configuration mesuree. Comparer deux walls bruts attribuerait ce surplus de travail
        # au parametre. Le nombre d'episodes est lu dans la cloture du run, pas suppose.
        rate_a = run_a["wall"] / run_a["episodes_trained"]
        rate_b = run_b["wall"] / run_b["episodes_trained"]
        ratio = rate_b / rate_a
        print(
            f"paire {index} ({'B puis A' if b_first else 'A puis B'})"
            f"{' — jetee' if index == 1 else ''}\n"
            f"  A({args.param}={args.a}) wall={run_a['wall']:6.1f}s  "
            f"episodes={run_a['episodes_trained']}  debit={1 / rate_a:.3f} ep/s\n"
            f"  B({args.param}={args.b}) wall={run_b['wall']:6.1f}s  "
            f"episodes={run_b['episodes_trained']}  debit={1 / rate_b:.3f} ep/s\n"
            f"  ratio s/episode B/A = {ratio:.3f}",
            flush=True,
        )
        if index > 1:
            ratios.append(ratio)

    median, couples = drift_cancelled(ratios)
    print(
        f"\nratios retenus (BA,AB,...) : {[round(r, 3) for r in ratios]}\n"
        f"couples sans derive        : {[round(c, 3) for c in couples]}\n"
        f"VERDICT = {median:.3f}  ->  {args.param}={args.b} est "
        f"{'PLUS RAPIDE' if median < 1 else 'PLUS LENT'} que {args.a} de "
        f"{abs(1 - median) * 100:.1f} % de temps par episode"
    )
    print_spread(couples)
    print(
        "RAPPEL : verdict de DEBIT. Il ne dit rien de ce qui est appris — pour cela, "
        "scripts/ab_bench_perf.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
