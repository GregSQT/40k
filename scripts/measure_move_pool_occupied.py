#!/usr/bin/env python3
"""|occupied| réel = somme des empreintes de tous les modèles des 2 rosters training,
à la résolution training (inches_to_subhex=5). Scaling BASE_SIZE identique au moteur
(game_state.py:848-850 : round(s * res / 10))."""
import json, sys
sys.path.insert(0, "/home/greg/40k")
from ai.unit_registry import UnitRegistry
from engine.hex_utils import precompute_footprint_offsets

RES = 5
r = UnitRegistry()


def scale(bs):
    if isinstance(bs, list):
        return [max(1, round(s * RES / 10)) for s in bs]
    return max(1, round(bs * RES / 10))


def footprint_cells(unit_type):
    d = r.get_unit_data(unit_type)
    shape = d["BASE_SHAPE"]
    bs = scale(d["BASE_SIZE"])
    orient = 0
    off_e, _ = precompute_footprint_offsets(shape, bs, orient)
    return len(off_e), shape, bs


def roster_models(path):
    d = json.load(open(path))
    models = []
    for entry in d["composition"]:
        ut = entry["unit_type"]
        if "models" in entry:
            models.extend(entry["models"])
        else:
            models.extend([ut] * int(entry.get("count", 1)))
    return models


ROSTERS = {
    "agent_SM": "config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_space_marines.json",
    "opp_Orks": "config/agents/_p2_rosters/500pts/training/opponent_training_roster_orks.json",
    "agent_Orks": "config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_orks.json",
    "opp_SM": "config/agents/_p2_rosters/500pts/training/opponent_training_roster_space_marines.json",
}

totals = {}
for name, path in ROSTERS.items():
    try:
        models = roster_models("/home/greg/40k/" + path)
    except Exception as e:
        print(f"{name}: SKIP ({e})")
        continue
    cells = 0
    per = []
    for m in models:
        try:
            n, shape, bs = footprint_cells(m)
        except Exception as e:
            print(f"  !! {m}: {e}")
            continue
        cells += n
        per.append((m, n, shape, bs))
    totals[name] = cells
    print(f"=== {name}: {len(models)} modèles, occupied={cells} cellules")
    for m, n, shape, bs in per:
        print(f"     {m:40s} {shape:6s} bs={str(bs):10s} -> {n} cells")

print("\n--- Combinaisons de partie (mover exclu ~1 unité) ---")
combos = [("agent_SM", "opp_Orks"), ("agent_Orks", "opp_SM")]
for a, b in combos:
    if a in totals and b in totals:
        tot = totals[a] + totals[b]
        print(f"{a} + {b} : |occupied| total board = {tot} cellules ({100*tot/66000:.2f}% du board)")
