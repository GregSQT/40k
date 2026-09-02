#!/usr/bin/env python3
"""Ou le masque d'action est-il construit, combien de fois, et pour quel cout ?

POURQUOI CET OUTIL
------------------
`scripts/refactor_fingerprint.py` repond a « combien de constructions au total ». Il ne dit pas
LESQUELLES sont redondantes : un total qui baisse ne designe aucun site, et un total qui stagne
ne dit pas si le travail a change de place. Optimiser demande la repartition PAR SITE D'APPEL.

Ce module intercepte `ActionDecoder.get_squad_action_mask_and_eligible_units` et attribue chaque
construction au fichier:ligne de son APPELANT, avec le temps passe dedans. La sortie est un
classement : c'est lui qui dit ou il reste quelque chose a prendre, et surtout ou il ne reste
rien — un site a 3 appels par episode ne merite aucun risque.

Les DUREES dependent de la charge machine et ne se comparent pas d'une session a l'autre. Les
COMPTES, eux, sont deterministes a graine fixee : ce sont eux qui prouvent qu'une optimisation a
retire ce qu'elle pretend retirer. Pour un verdict de temps, cf. `scripts/ab_bench.py`.

USAGE
-----
    python3 scripts/mask_call_sites.py                    # 4 episodes
    python3 scripts/mask_call_sites.py --episodes 8

VERIFIER QUE L'OUTIL DISCRIMINE
-------------------------------
Un profil ne se lit pas comme une verite revelee : il ne voit que le chemin joue. La politique du
banc est un tirage uniforme parmi les actions masquees — elle n'appelle donc jamais un modele, et
les branches propres au self-play ou au PvE n'apparaissent PAS dans le classement. Un site absent
de la sortie n'est pas un site mort, c'est un site non couvert par ce scenario.

Controle de non-vacuite integre : si un site attendu du chemin d'entrainement (`w40k_core.step`)
n'apparait pas, l'interception ne mesure plus le vrai chemin et l'outil leve au lieu d'afficher un
classement rassurant.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

os.environ.setdefault("W40K_BOARD_PATH", "board/44x60x1")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "scripts")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="ArmageddonAgent_x1")
    parser.add_argument("--training-config", default="x1_debug")
    parser.add_argument("--episodes", type=int, default=4)
    parser.add_argument("--seed-base", type=int, default=1000)
    args = parser.parse_args()

    import refactor_fingerprint as fp
    from engine.action_decoder import ActionDecoder

    counts: dict[str, int] = defaultdict(int)
    seconds: dict[str, float] = defaultdict(float)

    # Les compteurs du banc enveloppent DEJA cette methode : on s'installe APRES eux, donc en
    # position la plus externe, seule d'ou le cadre appelant est le vrai appelant. Installee
    # avant, cette sonde attribuait 100 % des constructions au wrapper du banc — la garde de
    # non-vacuite plus bas l'a signale au premier essai.
    counters = fp._install_work_counters()
    build_mask = ActionDecoder.get_squad_action_mask_and_eligible_units

    def attributed(self, game_state):
        frame = sys._getframe(1)
        site = f"{os.path.relpath(frame.f_code.co_filename, _ROOT)}:{frame.f_lineno}"
        start = time.perf_counter()
        try:
            return build_mask(self, game_state)
        finally:
            counts[site] += 1
            seconds[site] += time.perf_counter() - start

    ActionDecoder.get_squad_action_mask_and_eligible_units = attributed

    env = fp._build_env(args.agent, args.training_config)
    try:
        fp._play(env, args.episodes, args.seed_base, counters)
    finally:
        env.close()

    total_calls = sum(counts.values())
    total_seconds = sum(seconds.values())
    if not any(site.startswith("engine/w40k_core.py") for site in counts):
        raise RuntimeError(
            "aucune construction attribuee a `engine/w40k_core.py` : l'interception ne voit plus "
            "le chemin d'entrainement (methode renommee ou deplacee). Corriger avant de lire quoi "
            "que ce soit de ce classement."
        )

    print(f"\n{args.episodes} episodes — {total_calls} constructions, {total_seconds:.2f} s cumulees\n")
    print(f"{'site appelant':<52} {'appels':>8} {'/ep':>7} {'ms/appel':>9} {'ms/ep':>8}")
    print("-" * 88)
    for site, calls in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(
            f"{site:<52} {calls:>8} {calls / args.episodes:>7.1f} "
            f"{seconds[site] / calls * 1000:>9.3f} {seconds[site] / args.episodes * 1000:>8.1f}"
        )
    print(
        "\nRAPPEL : la politique du banc est un tirage aleatoire masque. Les branches self-play "
        "et PvE ne sont PAS couvertes — leur absence ici ne prouve rien a leur sujet."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
