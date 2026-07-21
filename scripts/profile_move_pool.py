#!/usr/bin/env python3
"""
Profilage ciblé ``movement_build_valid_destinations_pool`` (lignes ``MOVE_POOL_BUILD`` et
``PERF_PROFILE`` dans ``perf_timing.log`` / ``perf_timing_profile.log``).

À lancer depuis la racine du dépôt (Python du venv recommandé)::

    python scripts/profile_move_pool.py
    python scripts/profile_move_pool.py --no-profile
    python scripts/profile_move_pool.py --board-cols 96 --board-rows 60 --move 12

Variables d'environnement reconnues par ``engine/perf_timing.py`` (prioritaires sur les
flags du script si définies) : ``W40K_PERF_TIMING``, ``W40K_PERF_PROFILE``,
``W40K_PERF_TIMING_LOG``, ``W40K_PERF_PROFILE_LOG``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Set, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from engine.perf_timing import (
    perf_profile_enabled,
    perf_profile_log_file_path,
    perf_timing_enabled,
    perf_timing_log_file_path,
)


def _make_unit_by_id(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(u["id"]): u for u in units}


def _stress_units(
    board_cols: int,
    board_rows: int,
    move: int,
    base_size: int,
) -> List[Dict[str, Any]]:
    """Scénario multi-hex + ez>1 : ancre centrale, ennemis dispersés (empreintes non triviales)."""
    cx = board_cols // 2
    cy = board_rows // 2
    u1 = {
        "id": 1,
        "col": cx,
        "row": cy,
        "HP_CUR": 4,
        "player": 0,
        "MOVE": move,
        "BASE_SIZE": base_size,
        "BASE_SHAPE": "round",
        "VALUE": 100,
    }
    # Quatre coins / côtés pour forcer dilatations engagement et un masque d’empreinte large.
    margin_x = max(6, board_cols // 8)
    margin_y = max(6, board_rows // 8)
    enemies: List[Dict[str, Any]] = [
        {
            "id": 2,
            "col": margin_x,
            "row": cy,
            "HP_CUR": 2,
            "player": 1,
            "VALUE": 50,
            "BASE_SIZE": 3,
            "BASE_SHAPE": "round",
        },
        {
            "id": 3,
            "col": board_cols - margin_x - 1,
            "row": cy,
            "HP_CUR": 2,
            "player": 1,
            "VALUE": 50,
            "BASE_SIZE": 2,
            "BASE_SHAPE": "round",
        },
        {
            "id": 4,
            "col": cx,
            "row": margin_y,
            "HP_CUR": 2,
            "player": 1,
            "VALUE": 50,
            "BASE_SIZE": 2,
            "BASE_SHAPE": "square",
        },
    ]
    # Champs de datasheet requis par build_units_cache/_build_models_for_unit depuis la
    # migration squad V11 (§0.12). Sans objet pour le BFS de move, mais require_key les exige.
    datasheet_defaults: Dict[str, Any] = {
        "HP_MAX": 4,
        "OC": 1,
        "T": 4,
        "ARMOR_SAVE": 3,
        "INVUL_SAVE": 0,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
    }
    units = [u1, *enemies]
    for u in units:
        for key, default in datasheet_defaults.items():
            u.setdefault(key, default)
        u.setdefault("HP_MAX", u["HP_CUR"])
        u.setdefault("move", u.get("MOVE", 0))
    return units


def _build_game_state(
    board_cols: int,
    board_rows: int,
    move: int,
    base_size: int,
    ez: int,
    walls: Set[Tuple[int, int]],
    resolution: int,
    *,
    perf_timing: bool,
    perf_profile: bool,
) -> Dict[str, Any]:
    units = _stress_units(board_cols, board_rows, move, base_size)
    config: Dict[str, Any] = {
        "game_rules": {"engagement_zone": ez, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        # Regles de traversee (pathfinding) — alignees sur config/game_config.json.
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
    }
    gs: Dict[str, Any] = {
        "config": config,
        "board_cols": board_cols,
        "board_rows": board_rows,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": walls,
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
        # Profiler le chemin d'ENTRAINEMENT (metrique move_gym = hex), qui est celui qui domine
        # le cout (MOVE_POOL_BUILD = 95,6% du temps de training).
        "gym_training_mode": True,
        # Resolution subhex : c'est le multiplicateur qui fait exploser le BFS (x5 = training).
        "inches_to_subhex": resolution,
    }
    if perf_timing:
        gs["perf_timing"] = True
    if perf_profile:
        gs["perf_profile"] = True
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 0)
    return gs


def main() -> None:
    p = argparse.ArgumentParser(description="Profilage movement_build_valid_destinations_pool.")
    p.add_argument("--board-cols", type=int, default=80, help="Largeur plateau (défaut: 80).")
    p.add_argument("--board-rows", type=int, default=50, help="Hauteur plateau (défaut: 50).")
    p.add_argument("--move", type=int, default=10, help="Portée MOVE de l’unité 1 (défaut: 10).")
    p.add_argument("--base-size", type=int, default=3, help="BASE_SIZE unité 1 (défaut: 3).")
    p.add_argument("--ez", type=int, default=10, help="engagement_zone (défaut: 10).")
    p.add_argument("--resolution", type=int, default=5, help="inches_to_subhex, x1..x5 (défaut: 5).")
    p.add_argument(
        "--no-profile",
        action="store_true",
        help="Désactive cProfile (garde les lignes wall-clock si perf_timing actif).",
    )
    p.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Nombre d’appels successifs (même état ; utile pour moyenne manuelle).",
    )
    args = p.parse_args()

    want_profile = not args.no_profile
    gs = _build_game_state(
        args.board_cols,
        args.board_rows,
        args.move,
        args.base_size,
        args.ez,
        set(),
        args.resolution,
        perf_timing=True,
        perf_profile=want_profile,
    )

    # Vérif cohérence avec perf_timing.py (env peut outrepasser game_state).
    gs_for_check: Dict[str, Any] = gs
    timing_on = perf_timing_enabled(gs_for_check)
    profile_on = perf_profile_enabled(gs_for_check)
    if not timing_on:
        print(
            "[profile_move_pool] perf_timing désactivé — définir W40K_PERF_TIMING=1 "
            "ou laisser le script activer game_state['perf_timing'].",
            file=sys.stderr,
        )
    if want_profile and not profile_on:
        print(
            "[profile_move_pool] perf_profile demandé mais désactivé — "
            "W40K_PERF_PROFILE=1 requis avec perf_timing, ou game_state['perf_profile'].",
            file=sys.stderr,
        )

    for k in range(args.repeat):
        pool = movement_build_valid_destinations_pool(gs, "1")
        tag = f"run={k + 1}/{args.repeat}"
        print(f"{tag} anchors={len(pool)}", flush=True)

    timing_path = perf_timing_log_file_path()
    profile_path = perf_profile_log_file_path()
    print(f"Fichiers perf (voir aussi stderr si échec d’écriture) :\n  {timing_path}\n  {profile_path}")


if __name__ == "__main__":
    main()
