#!/usr/bin/env python3
"""Étalement du bot par tour — dépouillement step.log pour calibrer w_contest/w_crowd.

Usage:
    python3 scripts/bot_zone_check.py [step.log]

Sortie: pour chaque style du panel refondu, zones contrôlées (Ctrl=2) et VP cumulé
        du bot à chaque tour, moyennés sur tous les épisodes.

Pré-requis: lancer
    python3 ai/train.py --agent ArmageddonAgent --training-config x1_long
        --test-only --test-episodes 20 --resolution 1
Le step_logger activé force le mode sérial, ce qui écrit Opponent: <bot> par épisode.

Hypothèse: le bot joue toujours P2 (Ctrl=2) dans les scénarios holdout x1_long.
Vérifiable si nécessaire en comptant quel joueur a le VP le plus bas en moyenne.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_panel_reference import print_panel_reference  # noqa: E402  (dépend du sys.path ci-dessus)

RE_OPPONENT = re.compile(r"Opponent:\s+(.+)")
RE_TOBJ = re.compile(r"\bT(\d+) OBJECTIVE CONTROL:.*VP1=(\d+) VP2=(\d+).*ZONES=(.+)")


def parse(path: str) -> Dict[str, Dict[int, Dict[str, List[float]]]]:
    """Renvoie {bot: {tour: {"z": [zones_P2, ...], "vp": [VP_P2, ...]}}}."""
    out: Dict[str, Dict[int, Dict[str, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: {"z": [], "vp": []})
    )
    cur_bot: str | None = None
    cur_ep: Dict[int, Tuple[int, int]] = {}  # tour -> (dernier zones_P2, dernier VP_P2)

    def _flush() -> None:
        if cur_bot and cur_ep:
            for t, (z, v) in cur_ep.items():
                out[cur_bot][t]["z"].append(float(z))
                out[cur_bot][t]["vp"].append(float(v))

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            m = RE_OPPONENT.search(line)
            if m:
                _flush()
                cur_bot = m.group(1).strip()
                cur_ep = {}
                continue
            m = RE_TOBJ.search(line)
            if m and cur_bot:
                turn = int(m.group(1))
                vp2 = int(m.group(3))
                z_p2 = sum(1 for seg in m.group(4).split("|") if "Ctrl=2" in seg)
                cur_ep[turn] = (z_p2, vp2)  # écrase : on garde le dernier snapshot par tour

    _flush()
    return out


def _avg(lst: List[float]) -> str:
    return f"{sum(lst) / len(lst):.2f}" if lst else "  -  "


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "step.log"
    data = parse(path)
    if not data:
        print("Aucune donnée extraite. Lancer train.py --test-only en premier.")
        return

    turns = [1, 2, 3, 4, 5]
    cols = " | ".join(f"T{t}" for t in turns)
    print(f"\n{'Bot':<22} {'N':>4} | {cols} | VP fin")
    print("-" * (22 + 4 + 3 + 5 * 6 + 4 + 4 + 7))

    for bot, tdata in sorted(data.items()):
        last_t = max(tdata) if tdata else 0
        n = len(tdata.get(last_t, {}).get("z", []))
        if n == 0:
            continue
        cells = [_avg(tdata.get(t, {}).get("z", [])) for t in turns]
        vps = tdata.get(last_t, {}).get("vp", [])
        vp_str = f"{sum(vps) / len(vps):.1f}" if vps else " - "
        print(f"{bot:<22} {n:>4} | " + " | ".join(f"{c:>4}" for c in cells) + f" | {vp_str:>6}")

    print()
    print_panel_reference()


if __name__ == "__main__":
    main()
