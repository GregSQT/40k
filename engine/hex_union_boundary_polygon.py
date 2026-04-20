"""
Contour de l’union d’hex (offset odd-q, flat-top) en coordonnées monde — aligné sur BoardDisplay / frontend.

Utilisé pour envoyer ``move_preview_footprint_mask_loops`` au lieu de milliers de couples (col,row)
dans le JSON (activate_unit).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from shared.data_validation import require_key

Q = 1e4

# Sommets quantifiés en entiers (même sémantique que l’ancien _q + clés str, sans allocations str).
Vertex = Tuple[int, int]


def _canonical_edge(v0: Vertex, v1: Vertex) -> Tuple[Vertex, Vertex]:
    return (v0, v1) if v0 < v1 else (v1, v0)


def _hex_center_world(
    col: int, row: int, hex_radius: float, margin: float
) -> Tuple[float, float]:
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3) * hex_radius
    hx = col * hex_width + hex_width / 2 + margin
    hy = (
        row * hex_height
        + ((col % 2) * hex_height) / 2
        + hex_height / 2
        + margin
    )
    return hx, hy


def _board_hex_radius_margin(game_state: Dict[str, Any]) -> Tuple[float, float]:
    """Uniquement ``game_state['config']['board']`` — même source que le moteur (W40KEngine)."""
    cfg = require_key(game_state, "config")
    board = require_key(cfg, "board")
    if "default" in board:
        spec = require_key(board, "default")
    else:
        spec = board
    if not isinstance(spec, dict):
        raise TypeError("config.board.default ou config.board doit être un dict")
    hr = float(require_key(spec, "hex_radius"))
    margin = float(require_key(spec, "margin"))
    return hr, margin


def compute_move_preview_mask_loops_world(
    hex_cells: Set[Tuple[int, int]],
    game_state: Dict[str, Any],
) -> Optional[List[List[Tuple[float, float]]]]:
    """
    Retourne une liste de boucles [ (x,y), ... ] en coordonnées monde (comme le front),
    ou None si la topologie n’est pas exploitable (le client retombera sur move_preview_footprint_zone).
    """
    if not hex_cells:
        return None
    hex_radius, margin = _board_hex_radius_margin(game_state)
    # Pas de tri : le multi-ensemble d’arêtes ne dépend pas de l’ordre des hex.
    cells_list = list(hex_cells)
    cs = np.fromiter((c for c, _ in cells_list), dtype=np.int64, count=len(cells_list))
    rs = np.fromiter((r for _, r in cells_list), dtype=np.int64, count=len(cells_list))
    n = int(cs.shape[0])
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3) * hex_radius
    hx = cs.astype(np.float64) * hex_width + hex_width / 2.0 + margin
    parity = (cs & 1).astype(np.float64)
    hy = (
        rs.astype(np.float64) * hex_height
        + parity * (hex_height / 2.0)
        + hex_height / 2.0
        + margin
    )
    ang = (np.arange(6, dtype=np.float64) * math.pi) / 3.0
    corner_x = hex_radius * np.cos(ang)
    corner_y = hex_radius * np.sin(ang)
    cx = hx[:, None] + corner_x[None, :]
    cy = hy[:, None] + corner_y[None, :]
    x0 = cx
    y0 = cy
    x1 = np.roll(cx, -1, axis=1)
    y1 = np.roll(cy, -1, axis=1)
    n_edges = n * 6
    E = np.empty((n_edges, 4), dtype=np.float64)
    E[:, 0] = x0.ravel()
    E[:, 1] = y0.ravel()
    E[:, 2] = x1.ravel()
    E[:, 3] = y1.ravel()

    # Sommets quantifiés et coordonnées affichage : tout vectorisé — la boucle Python ne fait
    # plus d’appels ``float()`` / ``round()`` par arête (gain net sur ~52k arêtes).
    ix0 = np.rint(E[:, 0] * Q).astype(np.int64, copy=False)
    iy0 = np.rint(E[:, 1] * Q).astype(np.int64, copy=False)
    ix1 = np.rint(E[:, 2] * Q).astype(np.int64, copy=False)
    iy1 = np.rint(E[:, 3] * Q).astype(np.int64, copy=False)
    qfx0 = np.rint(E[:, 0] * Q) / Q
    qfy0 = np.rint(E[:, 1] * Q) / Q
    qfx1 = np.rint(E[:, 2] * Q) / Q
    qfy1 = np.rint(E[:, 3] * Q) / Q

    # Comptage des arêtes en O(n) par dict — ``np.unique`` (tri) était plus lent que l’historique
    # sur ~52k arêtes (régression perf observée en prod).
    edge_count: Dict[Tuple[Vertex, Vertex], int] = {}
    pos: Dict[Vertex, Tuple[float, float]] = {}
    for i in range(n_edges):
        a0x = int(ix0[i])
        a0y = int(iy0[i])
        a1x = int(ix1[i])
        a1y = int(iy1[i])
        k0 = (a0x, a0y)
        k1 = (a1x, a1y)
        if k0 not in pos:
            pos[k0] = (float(qfx0[i]), float(qfy0[i]))
        if k1 not in pos:
            pos[k1] = (float(qfx1[i]), float(qfy1[i]))
        ek = _canonical_edge(k0, k1)
        edge_count[ek] = edge_count.get(ek, 0) + 1

    boundary_edges: List[Tuple[Vertex, Vertex]] = []
    for ek, c in edge_count.items():
        if c == 1:
            boundary_edges.append(ek)
        elif c != 2:
            return None

    if not boundary_edges:
        return None

    adj: Dict[Vertex, List[Vertex]] = {}
    for va, vb in boundary_edges:
        adj.setdefault(va, []).append(vb)
        adj.setdefault(vb, []).append(va)

    for _vk, peers in adj.items():
        if len(peers) != 2:
            return None

    undirected_remaining: Set[Tuple[Vertex, Vertex]] = set(boundary_edges)

    loops: List[List[Tuple[float, float]]] = []

    def _remove_undirected(a: Vertex, b: Vertex) -> None:
        undirected_remaining.discard(_canonical_edge(a, b))

    while undirected_remaining:
        pick = next(iter(undirected_remaining))
        ka, kb = pick
        if kb not in adj.get(ka, []):
            return None

        start = ka
        prev = ka
        curr = kb
        ring_keys: List[Vertex] = [start]

        _remove_undirected(prev, curr)

        guard = 0
        max_guard = len(boundary_edges) * 4 + 64

        while curr != start:
            guard += 1
            if guard > max_guard:
                return None
            ring_keys.append(curr)
            peers = adj.get(curr)
            if not peers or len(peers) != 2:
                return None
            nxt = peers[1] if peers[0] == prev else peers[0]
            _remove_undirected(curr, nxt)
            prev, curr = curr, nxt

        if len(ring_keys) < 3:
            return None

        loop_pts: List[Tuple[float, float]] = []
        for vk in ring_keys:
            p = pos.get(vk)
            if p is None:
                return None
            loop_pts.append(p)
        loops.append(loop_pts)

    if undirected_remaining:
        return None

    return loops if loops else None
