#!/usr/bin/env python3
"""Génère (ou régénère) les emplacements `top`/`bottom` par figurine des rosters de training.

Mode strict (déploiement `fixed`) : le loader exige des positions par figurine dans le roster
(cf. `_expand_compact_roster_to_basic_units`). Ce script les calcule et réécrit les 4 rosters.

Garanties du placement :
  - **footprint réel** de chaque socle (tailles variables persos/véhicules), wall-aware (terrain-mc1),
    aucun chevauchement (le mode `fixed` valide les footprints à la charge) ;
  - **cohérence d'escouade** obtenue par un **réseau hexagonal** de pas `PITCH`=9 subhex : tout voisin
    de réseau est à 9 < 10 subhex (2\") → un amas compact garantit ≥2 voisins par figurine. NB : la
    règle moteur (game_config : `squad_min_neighbors`=1, distance bord-à-bord) n'exige qu'≥1 voisin ;
    on vise ≥2 centre-à-centre = borne CONSERVATRICE (superset), l'oracle reste
    `validate_squad_coherency` (asserté par `scripts/roster_fixed_positions_test.py`) ;
  - joueur 1 = bande HAUTE (top), joueur 2 = bande BASSE (bottom).

À relancer si une composition de roster change : python3 scripts/gen_roster_positions.py
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.unit_registry import UnitRegistry
from ai.training_utils import setup_imports
from engine.hex_utils import compute_occupied_hexes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISH = 5
PITCH = 9  # pas du réseau hex (subhex) : < 10 (cohérence) et >= socle+1 (pas de chevauchement, base<=8)
COH = 10.0

ROSTERS = [
    "config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_space_marines.json",
    "config/agents/ArmageddonAgent/rosters/500pts/training/agent_training_roster_orks.json",
    "config/agents/_p2_rosters/500pts/training/opponent_training_roster_space_marines.json",
    "config/agents/_p2_rosters/500pts/training/opponent_training_roster_orks.json",
]
# centres candidats d'escouade par bande (espacés pour que les amas ne se télescopent pas)
TOP_CENTERS = [(c, r) for r in range(55, 100, 22) for c in range(40, 190, 34)]
BOT_CENTERS = [(c, r) for r in range(210, 256, 22) for c in range(40, 190, 34)]


_INLINE_KEYS = {"unit_type", "top", "bottom", "col", "row", "level"}


def dump_roster(o, ind=0):
    """Sérialise un roster indenté (2 espaces), mais rend INLINE (une seule ligne) tout objet dont
    les clés sont ⊆ {unit_type, top, bottom, col, row, level} : chaque figurine tient donc sur une
    ligne (type + top + bottom), et les coords top/bottom des unités mono aussi. JSON valide."""
    pad = "  " * ind
    if isinstance(o, dict):
        if set(o.keys()) <= _INLINE_KEYS:
            return json.dumps(o, separators=(", ", ": "), ensure_ascii=False)
        inner = ",\n".join(
            f"{'  ' * (ind + 1)}{json.dumps(k, ensure_ascii=False)}: {dump_roster(v, ind + 1)}"
            for k, v in o.items()
        )
        return "{\n" + inner + "\n" + pad + "}"
    if isinstance(o, list):
        if not o:
            return "[]"
        inner = ",\n".join(f"{'  ' * (ind + 1)}{dump_roster(v, ind + 1)}" for v in o)
        return "[\n" + inner + "\n" + pad + "]"
    return json.dumps(o, ensure_ascii=False)


def base_of(ur, unit_type):
    d = ur.get_unit_data(unit_type)
    raw = d["BASE_SIZE"]
    size = ([max(1, round(s * ISH / 10)) for s in raw] if isinstance(raw, list)
            else max(1, round(raw * ISH / 10)))
    return d["BASE_SHAPE"], size


def footprint(ur, col, row, unit_type):
    shape, size = base_of(ur, unit_type)
    return set(compute_occupied_hexes(col, row, shape, size, 0))


_AX_DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def hex_lattice(cx, cy, n_needed):
    """Positions d'un réseau hex (pas PITCH) autour de (cx,cy), spirale par anneaux (voisins à PITCH)."""
    v1 = (PITCH, 0.0)
    v2 = (PITCH / 2.0, PITCH * math.sqrt(3) / 2.0)

    def to_board(q, r):
        col = cx + v1[0] * q + v2[0] * r
        row = cy + v1[1] * q + v2[1] * r
        return (int(round(col)), int(round(row)))

    out = [to_board(0, 0)]
    radius = 1
    while len(out) < n_needed * 3 + 8:
        # départ au coin (direction 4) puis parcours des 6 arêtes de l'anneau
        q = _AX_DIRS[4][0] * radius
        r = _AX_DIRS[4][1] * radius
        for i in range(6):
            for _ in range(radius):
                out.append(to_board(q, r))
                q += _AX_DIRS[i][0]
                r += _AX_DIRS[i][1]
        radius += 1
    return out


class Placer:
    def __init__(self, ur, walls, centers):
        self.ur = ur
        self.walls = walls
        self.centers = list(centers)
        self.used = set()
        self.ci = 0

    def _ok(self, col, row, unit_type):
        fp = footprint(self.ur, col, row, unit_type)
        if any(cc < 0 or cc >= 220 or rr < 0 or rr >= 300 for cc, rr in fp):
            return None
        if fp & self.walls or fp & self.used:
            return None
        return fp

    def place_squad(self, types):
        """Place toutes les figurines d'une escouade en amas hex cohérent ; retourne la liste de (col,row)."""
        for attempt in range(len(self.centers)):
            cx, cy = self.centers[(self.ci + attempt) % len(self.centers)]
            lattice = hex_lattice(cx, cy, len(types))
            chosen = []
            local_used = set()
            for ut in types:
                got = None
                for (col, row) in lattice:
                    if (col, row) in [(c, r) for c, r, _ in chosen]:
                        continue
                    fp = self._ok(col, row, ut)
                    if fp is None or fp & local_used:
                        continue
                    got = (col, row, fp)
                    break
                if got is None:
                    break
                chosen.append(got)
                local_used |= got[2]
            if len(chosen) == len(types):
                pts = [(c, r) for c, r, _ in chosen]
                need = 2 if len(types) >= 7 else 1
                # N'accepter un centre que si la formation obtenue est COHÉRENTE (sinon le socle a été
                # poussé sur un anneau lointain par l'encombrement → chercher un centre plus dégagé).
                if len(types) < 2 or coherency_ok(pts, need):
                    self.used |= local_used
                    self.ci = (self.ci + attempt + 1) % len(self.centers)
                    return pts
        raise SystemExit(f"placement cohérent impossible pour escouade {types} (bande saturée)")


def coherency_ok(points, need):
    for i, a in enumerate(points):
        nb = sum(1 for j, b in enumerate(points) if i != j and math.dist(a, b) <= COH)
        if nb < need:
            return False
    return True


def main():
    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    # Murs = ceux du terrain réel du training (terrain-mc1, via le template roster) — pas d'un
    # scénario ad-hoc, pour ne dépendre que de ce que le training charge vraiment.
    tpl = os.path.join(ROOT, "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json")
    env = W40KEngine(rewards_config="ArmageddonAgent", training_config_name="x5_new",
                     controlled_agent="ArmageddonAgent", scenario_file=tpl, unit_registry=ur,
                     quiet=True, gym_training_mode=True)
    env.reset(seed=1)
    walls = set((int(c), int(r)) for c, r in (env.game_state.get("wall_hexes") or set()))

    for path in ROSTERS:
        full = os.path.join(ROOT, path)
        d = json.load(open(full))
        top = Placer(ur, walls, TOP_CENTERS)
        bot = Placer(ur, walls, BOT_CENTERS)
        total = 0
        for comp in d["composition"]:
            if comp.get("count", 1) != 1:
                raise SystemExit(f"{path}: count!=1 non géré ({comp})")
            types = ([m if isinstance(m, str) else m["unit_type"] for m in comp["models"]]
                     if "models" in comp else [comp["unit_type"]])
            tpos = top.place_squad(types)
            bpos = bot.place_squad(types)
            need = 2 if len(types) >= 7 else 1
            if len(types) >= 2:
                assert coherency_ok(tpos, need), f"{path}: escouade non-cohérente (top) {types}"
                assert coherency_ok(bpos, need), f"{path}: escouade non-cohérente (bottom) {types}"
            if "models" in comp:
                comp["models"] = [
                    {"unit_type": t, "top": {"col": tc, "row": tr}, "bottom": {"col": bc, "row": br}}
                    for t, (tc, tr), (bc, br) in zip(types, tpos, bpos)
                ]
            else:
                comp["top"] = {"col": tpos[0][0], "row": tpos[0][1]}
                comp["bottom"] = {"col": bpos[0][0], "row": bpos[0][1]}
            total += len(types)
        with open(full, "w") as f:
            f.write(dump_roster(d) + "\n")
        print(f"écrit {os.path.basename(path):52s} figurines/unités={total} (cohérence vérifiée)")


if __name__ == "__main__":
    main()
