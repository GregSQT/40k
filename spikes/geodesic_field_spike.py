"""Spike de dé-risquage — champ de distance géodésique any-angle (Étape 3).

Isolé du moteur : géométrie hex, murs et LoS réimplémentés localement (aucun
import engine/). But = valider AVANT tout branchement move/charge que :
  1. sans mur, la zone atteignable est un disque euclidien (pas une rosace hex) ;
  2. avec un mur concave, le champ le contourne sans traverser d'angle ;
  3. l'erreur aux coins reste négligeable vs un visibility graph exact de référence.

Algorithme : lazy Theta* en flood (Dijkstra sur les centres d'hex, avec
rattachement d'un nœud à l'ANCÊTRE de son voisin si la ligne de vue est dégagée
→ coût = vraie distance euclidienne, chemins à angle libre).

Primitive de visibilité : segment euclidien ↔ cellules-murs, avec règle de coin
(grazing bloqué : un segment qui touche la frontière d'un mur est bloqué → on ne
se faufile pas entre deux murs jointifs). C'est CETTE géométrie qui fera autorité
côté moteur Python ; le LoS WASM frontend s'y alignera en étapes 4-5.

RAPPEL Étape 3 (règle 03 Moving) : le budget doit à terme se mesurer sur le point
le plus éloigné du socle, pas sur son centre (arc plus long en serrant un coin).
Ici le champ est calculé depuis le centre ; `socle_radius` est exposé mais la
mesure fine de l'arc au coin reste étage 4/5 (voir NOTE_SOCLE plus bas).
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

# --- Géométrie hex flat-top, offset odd-q (convention voisins du projet) -------

SQRT3 = math.sqrt(3.0)


def hex_center(col: int, row: int, size: float = 1.0) -> Tuple[float, float]:
    """Centre pixel d'une cellule flat-top en offset odd-q (size = centre→sommet)."""
    x = 1.5 * size * col
    y = SQRT3 * size * (row + 0.5 * (col & 1))
    return x, y


def hex_corners(col: int, row: int, size: float = 1.0) -> List[Tuple[float, float]]:
    """Les 6 sommets d'une cellule flat-top (angles 0,60,...,300°)."""
    cx, cy = hex_center(col, row, size)
    return [
        (cx + size * math.cos(math.radians(60 * k)),
         cy + size * math.sin(math.radians(60 * k)))
        for k in range(6)
    ]


ODD_Q_NEIGHBORS_EVEN = [(+1, 0), (+1, -1), (0, -1), (-1, -1), (-1, 0), (0, +1)]
ODD_Q_NEIGHBORS_ODD = [(+1, +1), (+1, 0), (0, -1), (-1, 0), (-1, +1), (0, +1)]


def neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """6 voisins odd-q."""
    deltas = ODD_Q_NEIGHBORS_ODD if (col & 1) else ODD_Q_NEIGHBORS_EVEN
    return [(col + dc, row + dr) for dc, dr in deltas]


# --- Primitive de visibilité : segment euclidien ↔ cellules-murs ---------------

def _segment_hits_hex(ax: float, ay: float, bx: float, by: float,
                      col: int, row: int, size: float) -> bool:
    """True si le segment [A,B] traverse l'INTÉRIEUR de la cellule (longueur
    d'intersection > 0) — Cyrus-Beck sur l'hexagone convexe.

    Intérieur strict = la simple tangence à un sommet/arête ne bloque PAS : on
    peut donc serrer l'angle convexe d'un mur isolé (= le plus court chemin).
    La règle « deux murs jointifs bloqués » (grazing entre coins partagés) n'est
    PAS gérée ici — limite assumée du spike, à traiter au branchement moteur.
    """
    corners = hex_corners(col, row, size)
    cx, cy = hex_center(col, row, size)
    dx, dy = bx - ax, by - ay
    t_enter, t_exit = 0.0, 1.0
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        ex, ey = x2 - x1, y2 - y1
        # Normale sortante de l'arête (l'hexagone est à gauche en parcours CCW).
        nx, ny = ey, -ex
        # Oriente la normale vers l'extérieur (loin du centre).
        if (nx * (cx - x1) + ny * (cy - y1)) > 0:
            nx, ny = -nx, -ny
        denom = nx * dx + ny * dy
        num = nx * (ax - x1) + ny * (ay - y1)
        if abs(denom) < 1e-12:
            if num > 1e-12:
                return False  # parallèle et hors du demi-plan → pas d'intersection
            continue
        t = -num / denom
        if denom < 0:  # segment entre dans le demi-plan intérieur
            t_enter = max(t_enter, t)
        else:          # segment sort du demi-plan intérieur
            t_exit = min(t_exit, t)
        if t_enter > t_exit:
            return False
    # Bloqué seulement si le segment traverse l'intérieur (longueur > 0),
    # pas s'il est simplement tangent (t_exit ≈ t_enter).
    return (t_exit - t_enter) > 1e-9


def segment_clear_of_walls(ax: float, ay: float, bx: float, by: float,
                            walls: Set[Tuple[int, int]], size: float = 1.0) -> bool:
    """True si aucune cellule-mur ne coupe le segment [A,B]."""
    for (wc, wr) in walls:
        if _segment_hits_hex(ax, ay, bx, by, wc, wr, size):
            return False
    return True


# --- Champ géodésique : lazy Theta* en flood -----------------------------------

def geodesic_field(start: Tuple[int, int], cells: Set[Tuple[int, int]],
                   walls: Set[Tuple[int, int]], budget: float, size: float = 1.0
                   ) -> Dict[Tuple[int, int], float]:
    """Distance géodésique any-angle de `start` à chaque cellule atteignable
    dans `budget` (unités-norme). `cells` = domaine libre (hors murs).

    Retourne {cellule: distance}. Une seule passe (champ complet), pas point-à-point.
    """
    if start in walls:
        raise ValueError(f"start {start} est un mur")
    g: Dict[Tuple[int, int], float] = {start: 0.0}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {start: start}
    pq: List[Tuple[float, Tuple[int, int]]] = [(0.0, start)]
    closed: Set[Tuple[int, int]] = set()

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in closed:
            continue
        closed.add(cur)
        cx, cy = hex_center(*cur, size)
        par = parent[cur]
        px, py = hex_center(*par, size)
        for nb in neighbors(*cur):
            if nb in walls or nb not in cells or nb in closed:
                continue
            nx, ny = hex_center(*nb, size)
            # Rattachement à l'ancêtre si LoS dégagé (le cœur de Theta*).
            if segment_clear_of_walls(px, py, nx, ny, walls, size):
                anchor, ax_, ay_, base = par, px, py, g[par]
            else:
                anchor, ax_, ay_, base = cur, cx, cy, g[cur]
            cand = base + math.hypot(nx - ax_, ny - ay_)
            if cand <= budget + 1e-9 and cand < g.get(nb, math.inf):
                g[nb] = cand
                parent[nb] = anchor
                heapq.heappush(pq, (cand, nb))
    return g


# --- Référence exacte : visibility graph ---------------------------------------

def _point_in_hex(px: float, py: float, col: int, row: int, size: float) -> bool:
    """True si (px,py) est strictement à l'intérieur de la cellule flat-top."""
    corners = hex_corners(col, row, size)
    cx, cy = hex_center(col, row, size)
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        ex, ey = x2 - x1, y2 - y1
        nx, ny = ey, -ex  # normale, orientée vers l'intérieur (vers le centre)
        if nx * (cx - x1) + ny * (cy - y1) < 0:
            nx, ny = -nx, -ny
        if nx * (px - x1) + ny * (py - y1) <= 1e-9:
            return False
    return True


def reference_distances(start: Tuple[int, int], targets: List[Tuple[int, int]],
                        walls: Set[Tuple[int, int]], size: float = 1.0
                        ) -> Dict[Tuple[int, int], float]:
    """Plus court chemin any-angle EXACT via visibility graph. Nœuds = start +
    targets + sommets de murs DÉCALÉS vers l'extérieur (epsilon le long du rayon
    centre→coin) et filtrés : on jette les coins qui, décalés, tombent encore
    dans un mur (coins enterrés/concaves, inutiles). Sans ce décalage, une arête
    visant un coin rase les cellules-murs voisines et coupe leur intérieur →
    fausses coupures et détours absurdes.
    """
    eps = 1e-3 * size
    nodes: List[Tuple[float, float]] = [hex_center(*start, size)]
    node_key: List[object] = [start]
    for t in targets:
        nodes.append(hex_center(*t, size))
        node_key.append(t)
    for (wc, wr) in walls:
        cx, cy = hex_center(wc, wr, size)
        for corner in hex_corners(wc, wr, size):
            dx, dy = corner[0] - cx, corner[1] - cy
            length = math.hypot(dx, dy)
            ox = corner[0] + dx / length * eps
            oy = corner[1] + dy / length * eps
            if any(_point_in_hex(ox, oy, mc, mr, size) for (mc, mr) in walls):
                continue  # coin enterré → inutile
            nodes.append((ox, oy))
            node_key.append(("corner", (ox, oy)))

    n = len(nodes)
    adj: List[List[Tuple[int, float]]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            ax, ay = nodes[i]
            bx, by = nodes[j]
            if segment_clear_of_walls(ax, ay, bx, by, walls, size):
                w = math.hypot(bx - ax, by - ay)
                adj[i].append((j, w))
                adj[j].append((i, w))

    dist = [math.inf] * n
    dist[0] = 0.0
    pq = [(0.0, 0)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(pq, (dist[v], v))

    out: Dict[Tuple[int, int], float] = {}
    for idx, key in enumerate(node_key):
        if key in targets:
            out[key] = dist[idx]
    return out


# --- Checkpoints ---------------------------------------------------------------

# Résolution : la grille de jeu est en subhex ; les positions sont quantifiées
# au subhex, donc le seuil pertinent est en SUBHEX (< 1 subhex = sous la
# résolution). Conversions via inches_to_subhex (jamais un seuil en pouces
# absolu, cf. feedback projet).
NORM_PER_SUBHEX = 1.5           # = ENGAGEMENT_NORM_HEX_WIDTH (largeur d'un subhex)
MAX_ERR_SUBHEX = 1.0           # tolérance = 1 subhex (résolution de la grille)


def _verdict(tag: str, max_err_norm: float, inches_to_subhex: int) -> None:
    """Affiche l'erreur en subhex (invariant board) + en pouces (board courant)."""
    err_subhex = max_err_norm / NORM_PER_SUBHEX
    err_inch = err_subhex / inches_to_subhex
    ok = err_subhex < MAX_ERR_SUBHEX
    print(f"    erreur max = {max_err_norm:.4f} norme = {err_subhex:.3f} subhex "
          f"= {err_inch:.4f}\" (×{inches_to_subhex})")
    print(f"    -> {tag}: {'OK' if ok else 'ÉCHEC'} (seuil {MAX_ERR_SUBHEX} subhex)")


def _rect_domain(cols: int, rows: int, walls: Set[Tuple[int, int]]
                 ) -> Set[Tuple[int, int]]:
    return {(c, r) for c in range(cols) for r in range(rows) if (c, r) not in walls}


def checkpoint_disc(cols: int = 25, rows: int = 25, inches_to_subhex: int = 5) -> None:
    """Sans mur : le champ doit coller à la distance euclidienne (disque)."""
    start = (cols // 2, rows // 2)
    cells = _rect_domain(cols, rows, set())
    budget = 12.0
    g = geodesic_field(start, cells, set(), budget)
    sx, sy = hex_center(*start)
    max_err = 0.0
    for cell, dgeo in g.items():
        tx, ty = hex_center(*cell)
        eucl = math.hypot(tx - sx, ty - sy)
        max_err = max(max_err, abs(dgeo - eucl))
    print(f"[1] disque sans mur : {len(g)} cellules")
    _verdict("[1]", max_err, inches_to_subhex)


def _hline(row: int, c0: int, c1: int) -> Set[Tuple[int, int]]:
    return {(c, row) for c in range(c0, c1 + 1)}


def _vline(col: int, r0: int, r1: int) -> Set[Tuple[int, int]]:
    return {(col, r) for r in range(r0, r1 + 1)}


def _concave_scenarios() -> List[Dict[str, object]]:
    """Plusieurs formes concaves stressant différentes géométries de coin
    (doc §395 : quelques configs concaves). Cibles réparties derrière l'obstacle
    pour forcer le contournement."""
    return [
        {
            "name": "L",
            "start": (4, 12),
            "walls": _vline(12, 6, 18) | _hline(6, 12, 18),
            "targets": [(18, 15), (20, 12), (16, 18), (22, 20)],
        },
        {
            "name": "U (poche)",
            "start": (14, 26),
            "walls": _vline(9, 8, 20) | _vline(19, 8, 20) | _hline(8, 9, 19),
            "targets": [(14, 10), (11, 11), (17, 11), (14, 14)],
        },
        {
            "name": "couloir / chicane",
            "start": (4, 20),
            "walls": _vline(11, 0, 15) | _vline(17, 13, 28),
            "targets": [(26, 8), (26, 20), (14, 4), (20, 24)],
        },
        {
            "name": "angle serré",
            "start": (10, 26),
            "walls": _vline(15, 10, 22) | _hline(10, 15, 25),
            "targets": [(16, 8), (18, 9), (24, 8), (20, 12)],
        },
    ]


def checkpoint_wall(cols: int = 30, rows: int = 30, inches_to_subhex: int = 5) -> None:
    """Batterie de murs concaves : contournement propre (champ ≥ ref, pas de
    triche à travers le mur) + erreur aux coins vs référence exacte. Reporte le
    PIRE cas global."""
    budget = 80.0
    worst_err = 0.0
    worst_where = ""
    cheat = False
    for sc in _concave_scenarios():
        name = sc["name"]
        start = sc["start"]
        walls = sc["walls"]
        cells = _rect_domain(cols, rows, walls)
        g = geodesic_field(start, cells, walls, budget)
        targets = [t for t in sc["targets"] if t in g and t not in walls]
        ref = reference_distances(start, targets, walls)
        print(f"    [{name}] start={start} :")
        for t in targets:
            err = g[t] - ref[t]  # signé : négatif = champ plus court que l'optimal = TRICHE
            flag = "  <-- TRICHE (traverse le mur)" if err < -1e-6 else ""
            print(f"        cible {t}: champ={g[t]:.3f}  ref={ref[t]:.3f}  err={err:+.4f}{flag}")
            if err < -1e-6:
                cheat = True
            if abs(err) > worst_err:
                worst_err = abs(err)
                worst_where = f"{name} {t}"
    print(f"[2] contournement mur concave — pire cas : {worst_where}")
    if cheat:
        print("    -> [2]: ÉCHEC — le champ traverse un mur (champ < ref)")
    else:
        _verdict("[2]", worst_err, inches_to_subhex)


NOTE_SOCLE = (
    "[3] budget sur point le plus éloigné du socle : NON couvert par ce spike.\n"
    "    Le champ est mesuré depuis le centre ; en any-angle, le bord extérieur\n"
    "    parcourt un arc plus long en serrant un coin -> à traiter en étapes 4/5\n"
    "    (tester le budget sur le point le plus éloigné, pas le centre)."
)


if __name__ == "__main__":
    checkpoint_disc()
    print()
    checkpoint_wall()
    print()
    print(NOTE_SOCLE)
