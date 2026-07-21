#!/usr/bin/env python3
"""Mesure |reach| vs board et |obstacles| pour trancher les leviers V11 move_build.

N'ALTÈRE PAS le moteur : monkeypatch d'un wrapper autour de _build_multi_hex_vectorized
qui capture ses kwargs, calcule les cardinalités via la fonction Minkowski DÉJÀ prouvée
équivalente à _placement_bad (compute_footprint_placement_mask), puis délègue à l'original.
|reach| est recalculé par un BFS fidèle (arêtes poids 1, mêmes voisinages parité) sur
~traverse_bad, exactement comme le moteur.
"""
from __future__ import annotations
import os, sys, argparse
from collections import deque

_ROOT = "/home/greg/40k"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import engine.phase_handlers.movement_handlers as mh
from engine.hex_utils import compute_footprint_placement_mask
from scripts.profile_move_pool import _build_game_state
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool

_captured = {}
_orig = mh._build_multi_hex_vectorized

_NB_EVEN = ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1))
_NB_ODD  = ((0, -1), (1, 0),  (1, 1), (0, 1), (-1, 1), (-1, 0))


def _bfs_reach(start_col, start_row, move_range, bcols, brows, tb_flat):
    """Reproduit exactement le BFS moteur (l.1770-1791) : renvoie le nombre de cases atteintes."""
    vis = bytearray(bcols * brows)
    vis[start_col + start_row * bcols] = 1
    q = deque([(start_col, start_row, 0)])
    reached = 1
    while q:
        cc, cr, cd = q.popleft()
        if cd >= move_range:
            continue
        nd = cd + 1
        nbs = _NB_EVEN if (cc & 1) == 0 else _NB_ODD
        for dc, dr in nbs:
            nc, nr = cc + dc, cr + dr
            if nc < 0 or nr < 0 or nc >= bcols or nr >= brows:
                continue
            vidx = nc + nr * bcols
            if vis[vidx] or tb_flat[vidx]:
                continue
            vis[vidx] = 1
            reached += 1
            q.append((nc, nr, nd))
    return reached


def _wrapper(**kw):
    bcols, brows = kw["board_cols"], kw["board_rows"]
    walls = kw["walls_set"]; occ = kw["occupied_set"]; en_occ = kw["enemy_occupied_set"]
    off_e, off_o = kw["off_even"], kw["off_odd"]
    thru_enemy, thru_friendly = kw["thru_enemy"], kw["thru_friendly"]
    thru_ez = kw["thru_ez"]

    obstacles_dest = set(walls) | set(occ)
    obstacles_traverse = set(walls)
    if not thru_enemy:
        obstacles_traverse |= set(en_occ)
    if not thru_friendly:
        obstacles_traverse |= (set(occ) - set(en_occ))

    # traverse_bad via Minkowski (prouvé équivalent à _placement_bad) → BFS fidèle → |reach|
    tb = compute_footprint_placement_mask(bcols, brows, off_e, off_o, obstacles_traverse)
    reach = _bfs_reach(kw["start_col"], kw["start_row"], kw["move_range"], bcols, brows, tb)

    res = _orig(**kw)
    pool = res[0]
    _captured.update(
        board=bcols * brows, bcols=bcols, brows=brows,
        move_range=kw["move_range"], ez=kw["ez"],
        n_offsets_even=len(off_e), n_offsets_odd=len(off_o),
        walls=len(walls), occupied=len(occ), enemy_occ=len(en_occ),
        obstacles_dest=len(obstacles_dest), obstacles_traverse=len(obstacles_traverse),
        reach=reach, pool=len(pool),
    )
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--board-cols", type=int, default=220)
    p.add_argument("--board-rows", type=int, default=300)
    p.add_argument("--move", type=int, default=30)
    p.add_argument("--base-size", type=int, default=6)
    p.add_argument("--ez", type=int, default=10)
    p.add_argument("--resolution", type=int, default=5)
    p.add_argument("--oval", action="store_true", help="Mover ovale [20,14] au lieu de rond.")
    args = p.parse_args()

    gs = _build_game_state(
        args.board_cols, args.board_rows, args.move, args.base_size, args.ez,
        set(), args.resolution, perf_timing=False, perf_profile=False,
    )
    if args.oval:
        u = gs["unit_by_id"]["1"]
        u["BASE_SHAPE"] = "oval"; u["BASE_SIZE"] = [20, 14]; u["orientation"] = 0
    mh._build_multi_hex_vectorized = _wrapper
    try:
        movement_build_valid_destinations_pool(gs, "1")
    finally:
        mh._build_multi_hex_vectorized = _orig

    c = _captured
    if not c:
        print("!! _build_multi_hex_vectorized non atteint (chemin single-hex ou euclidean ?)")
        return
    print(f"board            = {c['bcols']}x{c['brows']} = {c['board']} cases")
    print(f"move_range       = {c['move_range']} (subhex)   ez={c['ez']}")
    print(f"offsets (footpr) = even {c['n_offsets_even']} / odd {c['n_offsets_odd']}")
    print(f"walls            = {c['walls']}")
    print(f"occupied         = {c['occupied']}  (dont ennemis {c['enemy_occ']})")
    print(f"obstacles_dest   = {c['obstacles_dest']}")
    print(f"obstacles_trav   = {c['obstacles_traverse']}")
    print(f"reach            = {c['reach']}   ({100.0*c['reach']/c['board']:.1f}% du board)")
    print(f"pool (dest.)     = {c['pool']}")
    print("--- ratios décisifs ---")
    print(f"reach / board            = {c['reach']/c['board']:.4f}   (levier 'calcul sur reach')")
    print(f"obstacles_dest / board   = {c['obstacles_dest']/c['board']:.4f}   (levier Minkowski)")
    approx_off = (c['n_offsets_even'] + c['n_offsets_odd']) / 2
    print(f"|offsets|~                = {approx_off:.0f}")
    print(f"dilate dense   ~ |off|*board  = {approx_off*c['board']:.3e}")
    print(f"Minkowski      ~ |obst|*|off| = {c['obstacles_dest']*approx_off:.3e}")
    print(f"test/reach     ~ |reach|*|off|= {c['reach']*approx_off:.3e}")


if __name__ == "__main__":
    main()
