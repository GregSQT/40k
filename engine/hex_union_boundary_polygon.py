"""
Contour de l’union d’hex (offset odd-q, flat-top) en coordonnées monde — aligné sur BoardDisplay / frontend.

Utilisé pour envoyer ``move_preview_footprint_mask_loops`` au lieu de milliers de couples (col,row)
dans le JSON (activate_unit).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set, Tuple

from shared.data_validation import require_key

Q = 1e4

# Sommets quantifiés en entiers (même sémantique que l’ancien _q + clés str, sans allocations str).
Vertex = Tuple[int, int]


def _vertex_ixy(x: float, y: float) -> Vertex:
    return (int(round(x * Q)), int(round(y * Q)))


def _q_float(n: float) -> float:
    """Identique à l’historique ``round(n * Q) / Q`` pour les points de boucle."""
    return round(n * Q) / Q


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
    corner_off: List[Tuple[float, float]] = []
    for vi in range(6):
        ang = (vi * math.pi) / 3.0
        corner_off.append((hex_radius * math.cos(ang), hex_radius * math.sin(ang)))

    edge_count: Dict[Tuple[Vertex, Vertex], int] = {}
    pos: Dict[Vertex, Tuple[float, float]] = {}
    for c, r in hex_cells:
        hx, hy = _hex_center_world(c, r, hex_radius, margin)
        for i in range(6):
            x0, y0 = hx + corner_off[i][0], hy + corner_off[i][1]
            j = (i + 1) % 6
            x1, y1 = hx + corner_off[j][0], hy + corner_off[j][1]
            k0 = _vertex_ixy(x0, y0)
            k1 = _vertex_ixy(x1, y1)
            if k0 not in pos:
                pos[k0] = (_q_float(x0), _q_float(y0))
            if k1 not in pos:
                pos[k1] = (_q_float(x1), _q_float(y1))
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
