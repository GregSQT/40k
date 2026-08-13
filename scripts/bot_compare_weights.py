#!/usr/bin/env python3
"""Compare deux relevés de bot_zone_direct.py : mesure l'effet d'un changement de poids.

Usage:
    python3 scripts/bot_compare_weights.py <ref.json> <var.json> [--bot decapitation]

Le bot cible varie entre ref et var (poids modifiés). Tous les autres bots (contrôles)
jouent les MÊMES parties dans les deux runs — même graine par index. Le script vérifie
cet invariant avant de calculer Δ_T5.

Appariement : par index dans la liste `episodes` filtrée par bot. Les graines sont dérivées
du nom du bot (pas des poids) → même index = même seed = même partie. Le script VÉRIFIE que
les deux listes ont la MÊME LONGUEUR et que ref[i].seed == var[i].seed pour le bot cible ;
si non : RuntimeError. La longueur ne se déduit pas des graines : elles viennent de
`_episode_seed(base_seed, bot, 0, i)` (bot_zone_direct.py:492), donc indexées — un run
interrompu à 12 épisodes sur 20 s'apparie parfaitement sur ses 12 premiers et ne rendrait
un `n` amputé qu'en silence.

Contrôles : tous les bots hors bot cible. Les deux fichiers doivent porter EXACTEMENT les
mêmes bots et le même nombre d'épisodes par bot ; pour chaque bot de contrôle et chaque
épisode i, le relevé doit être IDENTIQUE dans ref et var — le relevé ENTIER (graine, siège,
zones, distances, escouades), pas les seules zones : un écart sur n'importe lequel de ces
champs signale la même chose, une dérive de protocole (mauvais fichier, ordre des épisodes
perturbé, panel différent). Un run sans aucun bot de contrôle ne peut pas être validé, et
c'est une erreur, pas un run vert.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, List, Tuple

from scipy import stats

#: Tour de mesure. Une bataille dure cinq tours (`game_rules.max_turns` = 5), et c'est une
#: règle du jeu, pas un réglage — décision du 2026-08-13, prise contre l'idée de publier la
#: durée dans le relevé pour la relire ici.
#:
#: Un épisode SANS relevé à ce tour s'est terminé avant (annihilation) : bot_zone_direct.py
#: ne pose une clé que pour les tours réellement joués (l.531-534). Il est ÉCARTÉ, jamais
#: compté « 0 zone tenue » — ce défaut-là inversait la conclusion, une variante qui gagne au
#: T3 étant comptée −2. C'est aussi la lecture du producteur, dont la moyenne T5 ne porte que
#: sur les épisodes parvenus au T5 (`_turns_of`, l.269-275).
_MEASURE_TURN = "5"

#: Niveau de confiance de l'intervalle publié, et seul endroit où il est écrit.
_CONFIDENCE = 0.95


def _load(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _episodes_by_bot(episodes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_bot: Dict[str, List[Dict[str, Any]]] = {}
    for ep in episodes:
        by_bot.setdefault(ep["bot"], []).append(ep)
    return by_bot


def _check_controls(
    ref_by_bot: Dict[str, List[Dict[str, Any]]],
    var_by_bot: Dict[str, List[Dict[str, Any]]],
    target_bot: str,
) -> None:
    """Vérifie que tous les bots de contrôle ont des relevés identiques entre ref et var.

    Un écart signale une dérive de protocole : run à jeter. L'absence de contrôle à vérifier
    aussi — elle ne prouve rien, donc elle ne s'affiche pas en vert.
    """
    if set(ref_by_bot) != set(var_by_bot):
        manquants_var = sorted(set(ref_by_bot) - set(var_by_bot))
        manquants_ref = sorted(set(var_by_bot) - set(ref_by_bot))
        raise RuntimeError(
            f"panels différents — erreur de protocole, run à jeter\n"
            f"  absents de var : {manquants_var}\n"
            f"  absents de ref : {manquants_ref}"
        )

    control_bots = sorted(set(ref_by_bot) - {target_bot})
    if not control_bots:
        raise RuntimeError(
            f"aucun bot de contrôle hors {target_bot!r} : l'invariance de protocole n'est "
            f"vérifiable par rien, la comparaison n'est pas validée"
        )

    compares = 0
    for bot in control_bots:
        ref_eps = ref_by_bot[bot]
        var_eps = var_by_bot[bot]
        if len(ref_eps) != len(var_eps):
            raise RuntimeError(
                f"nombres d'épisodes différents — erreur de protocole, run à jeter\n"
                f"  bot={bot!r}  ref={len(ref_eps)} épisodes  var={len(var_eps)} épisodes"
            )
        for i, (r, v) in enumerate(zip(ref_eps, var_eps)):
            if r != v:
                raise RuntimeError(
                    f"drift non nul — erreur de protocole, run à jeter\n"
                    f"  bot={bot!r}  épisode={i}\n"
                    f"  ref: {r}\n"
                    f"  var: {v}"
                )
            compares += 1

    print(f"drift contrôles = 0.000 ✓  ({len(control_bots)} bots, {compares} épisodes comparés)")


def _compute_delta(
    ref_eps: List[Dict[str, Any]],
    var_eps: List[Dict[str, Any]],
) -> Tuple[List[float], int, int]:
    """Δ_T5 apparié épisode par épisode : var[i].zones_T5 − ref[i].zones_T5.

    Rend (deltas, épisodes ref écartés, épisodes var écartés). Une PAIRE est écartée dès qu'un
    de ses deux côtés s'est terminé avant le T5 : l'appariement est le fondement du test, un
    Δ calculé contre un tour manquant ne compare rien. Les deux compteurs sont rendus séparément
    parce que leur ASYMÉTRIE est le signal : « var écarte 8 épisodes contre 2 pour ref » dit que
    la variante finit ses parties plus tôt, ce qu'une moyenne sur les survivants ne dit pas.

    Lève RuntimeError si les longueurs diffèrent ou si ref[i].seed != var[i].seed.
    """
    if len(ref_eps) != len(var_eps):
        raise RuntimeError(
            f"nombres d'épisodes différents pour le bot cible, les runs ne sont pas comparables\n"
            f"  ref={len(ref_eps)} épisodes  var={len(var_eps)} épisodes"
        )

    deltas: List[float] = []
    courts_ref = 0
    courts_var = 0
    for i, (r, v) in enumerate(zip(ref_eps, var_eps)):
        if r["seed"] != v["seed"]:
            raise RuntimeError(
                f"graines désappariées, les runs ne sont pas comparables\n"
                f"  épisode={i}  ref.seed={r['seed']}  var.seed={v['seed']}"
            )
        ref_t5 = r["zones_by_turn"].get(_MEASURE_TURN)
        var_t5 = v["zones_by_turn"].get(_MEASURE_TURN)
        if ref_t5 is None:
            courts_ref += 1
        if var_t5 is None:
            courts_var += 1
        if ref_t5 is None or var_t5 is None:
            continue
        deltas.append(float(var_t5 - ref_t5))
    return deltas, courts_ref, courts_var


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare deux relevés bot_zone_direct.py (schema_version 3).",
    )
    parser.add_argument("ref", help="Fichier JSON de référence")
    parser.add_argument("var", help="Fichier JSON de la variante")
    parser.add_argument("--bot", default="decapitation", help="Bot cible (défaut: decapitation)")
    args = parser.parse_args()

    ref_data = _load(args.ref)
    var_data = _load(args.var)

    ref_by_bot = _episodes_by_bot(ref_data["episodes"])
    var_by_bot = _episodes_by_bot(var_data["episodes"])

    if args.bot not in ref_by_bot:
        print(f"Erreur : bot {args.bot!r} absent de {args.ref}", file=sys.stderr)
        sys.exit(1)
    if args.bot not in var_by_bot:
        print(f"Erreur : bot {args.bot!r} absent de {args.var}", file=sys.stderr)
        sys.exit(1)

    _check_controls(ref_by_bot, var_by_bot, args.bot)

    deltas, courts_ref, courts_var = _compute_delta(ref_by_bot[args.bot], var_by_bot[args.bot])
    n = len(deltas)

    print(f"\nBot cible : {args.bot}  (n={n})")
    print(f"  épisodes écartés (terminés avant le T{_MEASURE_TURN}) : ref {courts_ref}, var {courts_var}")
    # Le `n >= 1` que garantissaient les gardes de bot absent ci-dessus ne tient plus : elles
    # prouvent que le bot a des épisodes, pas qu'une paire atteint le T5. Tout écarter est un
    # résultat lisible (« les parties ne vont jamais au bout »), pas une division par zéro.
    if n == 0:
        print("  aucune paire d'épisodes ne parvient au T5 : rien à comparer", file=sys.stderr)
        sys.exit(1)

    mean = sum(deltas) / n
    print(f"  mean(Δ_T5) = {mean:+.3f}")

    # n=1 : la variance d'échantillon (n−1) n'existe pas. Un `std = 0.0` de repli affichait
    # « IC ± 0.000 », c'est-à-dire l'effet le plus significatif qu'on puisse lire, sur un
    # épisode unique.
    if n < 2:
        print("  std(Δ_T5)  =  non défini (n=1)")
        print(f"  IC {_CONFIDENCE * 100:.0f} %    = non défini (n=1)")
        return

    std = math.sqrt(sum((d - mean) ** 2 for d in deltas) / (n - 1))
    # Student, pas 1,96 : σ est ESTIMÉ sur l'échantillon, et le protocole tourne à n=60 ou
    # moins. Le quantile normal rétrécit l'intervalle (t(59)=2,001, t(3)=3,182), donc il déclare
    # significatif ce qui ne l'est pas — sur le seuil de décision du §12.12, qui est exactement
    # « l'IC ne contient pas 0 ».
    t_crit = float(stats.t.ppf(0.5 + _CONFIDENCE / 2, n - 1))
    ic = t_crit * std / math.sqrt(n)

    print(f"  std(Δ_T5)  =  {std:.3f}")
    print(
        f"  IC {_CONFIDENCE * 100:.0f} %    = {mean:+.3f} ± {ic:.3f}  "
        f"[{mean - ic:+.3f} ; {mean + ic:+.3f}]  (Student t={t_crit:.3f}, ddl={n - 1})"
    )


if __name__ == "__main__":
    main()
