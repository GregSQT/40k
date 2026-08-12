"""INSTRUMENT TEMPORAIRE — à supprimer. Mesure la fenêtre « socles inconnus » de l'analyzer.

Ouverte quand une figurine meurt (le journal ne dit pas laquelle → tous les socles de l'escouade
sont oubliés), refermée par la première source qui redonne les socles :
  - `MODELS`        : l'escouade agit et reloggue ses socles ;
  - `TARGET_MODELS` : elle est reprise pour cible, segment de fin d'action ;
  - `STATE`         : l'instantané moteur de début de tour.
"""
from typing import Dict, List, Tuple

_open: Dict[str, Tuple[int, str, int, int]] = {}
closed: List[Dict[str, object]] = []
never_closed: List[str] = []


def opened(uid: str, line_number: int, phase: str, turn: int, episode: int) -> None:
    _open[str(uid)] = (int(line_number), str(phase), int(turn), int(episode))


def closed_by(uid: str, line_number: int, site: str, turn: int) -> None:
    entry = _open.pop(str(uid), None)
    if entry is None:
        return
    start, phase, start_turn, episode = entry
    closed.append({
        "uid": str(uid), "site": site, "lines": int(line_number) - start,
        "phase": phase, "turns": int(turn) - start_turn, "episode": episode,
    })


def report() -> None:
    from collections import Counter
    print(f"fenetres refermees : {len(closed)}  (encore ouvertes en fin de journal : {len(_open)})")
    print("  par source :", dict(Counter(str(c["site"]) for c in closed)))
    print("  meme tour  :", sum(1 for c in closed if c["turns"] == 0),
          " tour suivant ou plus :", sum(1 for c in closed if int(c["turns"]) > 0))  # type: ignore[call-overload]
    spans = sorted(int(c["lines"]) for c in closed)  # type: ignore[call-overload]
    if spans:
        n = len(spans)
        print(f"  longueur (lignes de journal) : mediane {spans[n // 2]}, "
              f"p90 {spans[int(n * 0.9)]}, max {spans[-1]}")
    print("  phase d'ouverture :", dict(Counter(str(c["phase"]) for c in closed)))
