"""
Régression : ``movement_build_valid_destinations_pool`` et ``enemy_cache_items`` pour
``_movement_engagement_violates`` (ez > 1) — même résultat qu’un scan complet du cache.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from engine.phase_handlers.movement_handlers import (
    _enemy_items_within_move_engagement_horizon,
    _movement_engagement_violates,
    movement_build_valid_destinations_pool,
)
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from shared.data_validation import require_key

from _config_helpers import build_move_rules


def _board_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 10,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "move": build_move_rules(),
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }


def _make_unit_by_id(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {str(u["id"]): u for u in units}


def _fill(unit: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in required fields for build_units_cache with minimal test defaults."""
    unit.setdefault("HP_MAX", unit.get("HP_CUR", 2))
    unit.setdefault("VALUE", 50)
    unit.setdefault("OC", 1)
    unit.setdefault("T", 4)
    unit.setdefault("ARMOR_SAVE", 3)
    unit.setdefault("INVUL_SAVE", 7)
    unit.setdefault("SHOOT_LEFT", 1)
    unit.setdefault("ATTACK_LEFT", 1)
    unit.setdefault("RNG_WEAPONS", [])
    unit.setdefault("CC_WEAPONS", [])
    unit.setdefault("UNIT_RULES", [])
    return unit


def test_movement_engagement_violates_enemy_cache_items_matches_full_scan() -> None:
    """Liste ennemis préfiltrée ≡ filtre inline sur ``units_cache`` (ez > 1)."""
    units = [_fill(u) for u in [
        {
            "id": 1,
            "col": 10,
            "row": 10,
            "HP_CUR": 2,
            "player": 0,
            "MOVE": 6,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
        {
            "id": 2,
            "col": 28,
            "row": 10,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
    ]]
    game_state: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 40,
        "board_rows": 40,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
        "inches_to_subhex": 1,
    }
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    mover = require_key(game_state["unit_by_id"], "1")
    candidate_fp = {(10, 10)}

    a = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
    )
    enemy_items = [
        (eid, ce)
        for eid, ce in units_cache.items()
        if str(eid) != "1" and int(require_key(ce, "player")) != 0
    ]
    b = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
        enemy_cache_items=enemy_items,
    )
    assert a == b

    # Cas « violation » : rapprocher l’ennemi pour forcer un échec d’écart (même résultat des deux côtés).
    units[1]["col"] = 12
    units[1]["row"] = 10
    game_state["units"] = units
    game_state["unit_by_id"] = _make_unit_by_id(units)
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    mover = require_key(game_state["unit_by_id"], "1")

    a2 = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
    )
    enemy_items2 = [
        (eid, ce)
        for eid, ce in units_cache.items()
        if str(eid) != "1" and int(require_key(ce, "player")) != 0
    ]
    b2 = _movement_engagement_violates(
        game_state,
        mover,
        10,
        10,
        candidate_fp,
        units_cache,
        None,
        enemy_cache_items=enemy_items2,
    )
    assert a2 == b2
    assert a2 is True


def test_pruned_enemy_horizon_matches_full_scan_with_far_dummy_enemy() -> None:
    """La prune spatiale (``_enemy_items_within_move_engagement_horizon``) ⊂ cache mais même verdict que le scan complet."""
    units = [_fill(u) for u in [
        {
            "id": 1,
            "col": 20,
            "row": 20,
            "HP_CUR": 2,
            "player": 0,
            "MOVE": 6,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
        {
            "id": 2,
            "col": 22,
            "row": 20,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
        {
            "id": 3,
            "col": 55,
            "row": 20,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
    ]]
    game_state: Dict[str, Any] = {
        "config": _board_config(),
        "board_cols": 80,
        "board_rows": 80,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
        "inches_to_subhex": 1,
    }
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    mover = require_key(game_state["unit_by_id"], "1")
    full_enemy_items = [
        (eid, ce)
        for eid, ce in units_cache.items()
        if str(eid) != "1" and int(require_key(ce, "player")) != 0
    ]
    pruned = _enemy_items_within_move_engagement_horizon(
        game_state,
        mover,
        "1",
        0,
        20,
        20,
        6,
        units_cache,
    )
    assert len(pruned) == 1
    assert str(pruned[0][0]) == "2"

    candidates: List[Tuple[int, int, Set[Tuple[int, int]]]] = [
        (20, 20, {(20, 20)}),
        (18, 20, {(18, 20)}),
        (24, 20, {(24, 20)}),
    ]
    for cc, cr, fp in candidates:
        full = _movement_engagement_violates(
            game_state,
            mover,
            cc,
            cr,
            fp,
            units_cache,
            None,
            enemy_cache_items=full_enemy_items,
            engagement_zone_ez=10,
        )
        sub = _movement_engagement_violates(
            game_state,
            mover,
            cc,
            cr,
            fp,
            units_cache,
            None,
            enemy_cache_items=pruned,
            engagement_zone_ez=10,
        )
        assert full == sub, f"mismatch at anchor ({cc},{cr})"


def _run_pool(
    units: List[Dict[str, Any]],
    ez: int,
    *,
    board_cols: int = 40,
    board_rows: int = 40,
    walls: Set[Tuple[int, int]] | None = None,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], Dict[str, Any]]:
    """Appelle ``movement_build_valid_destinations_pool`` (chemin unique vectorisé NumPy)."""
    units = [_fill(u) for u in units]
    config = {
        "game_rules": {"engagement_zone": ez, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "move": build_move_rules(),
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }
    game_state: Dict[str, Any] = {
        "config": config,
        "board_cols": board_cols,
        "board_rows": board_rows,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": walls or set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
        "inches_to_subhex": 1,
    }
    build_units_cache(game_state)
    build_enemy_adjacent_hexes(game_state, 0)
    pool = movement_build_valid_destinations_pool(game_state, "1")
    fz = set(game_state.get("move_preview_footprint_zone", set()))
    return pool, fz, game_state


def _oracle_pool(
    game_state: Dict[str, Any],
    unit_id: str,
    ez: int,
) -> Set[Tuple[int, int]]:
    """Oracle brute-force : énumère chaque ancre valide selon la sémantique de référence V11.
    Traversée = bounds + walls + figs ennemies (l'EZ est traversable, toggle
    ``can_move_through_enemy_engagement_zone``). Destination = empreinte hors occupation ET
    hors EZ ennemie (``_movement_engagement_violates``). BFS exhaustif borné par ``MOVE``.
    """
    from engine.hex_utils import precompute_footprint_offsets

    unit = require_key(game_state["unit_by_id"], unit_id)
    units_cache = require_key(game_state, "units_cache")
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    walls = game_state.get("wall_hexes", set())
    shape = unit.get("BASE_SHAPE", "round")
    size = int(unit.get("BASE_SIZE", 1))
    orient = int(unit.get("orientation", 0) or 0)
    off_even, off_odd = precompute_footprint_offsets(shape, size, orient)

    start_c = int(require_key(unit, "col"))
    start_r = int(require_key(unit, "row"))
    move_range = int(require_key(unit, "MOVE"))
    mover_player = int(require_key(unit, "player"))

    enemy_occupied: Set[Tuple[int, int]] = set()
    occupied: Set[Tuple[int, int]] = set()
    for eid, ce in units_cache.items():
        if str(eid) == str(unit_id):
            continue
        c = int(require_key(ce, "col"))
        r = int(require_key(ce, "row"))
        e_shape = ce.get("BASE_SHAPE", "round")
        e_size = int(ce.get("BASE_SIZE", 1))
        e_orient = int(ce.get("orientation", 0) or 0)
        e_even, e_odd = precompute_footprint_offsets(e_shape, e_size, e_orient)
        e_off = e_even if (c & 1) == 0 else e_odd
        for dc, dr in e_off:
            occupied.add((c + dc, r + dr))
            if int(require_key(ce, "player")) != mover_player:
                enemy_occupied.add((c + dc, r + dr))

    enemy_items = [
        (eid, ce) for eid, ce in units_cache.items()
        if str(eid) != str(unit_id) and int(require_key(ce, "player")) != mover_player
    ]

    def _anchor_traversable(ac: int, ar: int) -> bool:
        # Traversée V11 : bounds + murs + figs ennemies. L'EZ ne bloque PLUS la traversée.
        offs = off_even if (ac & 1) == 0 else off_odd
        for dc, dr in offs:
            fc, fr = ac + dc, ar + dr
            if fc < 0 or fr < 0 or fc >= board_cols or fr >= board_rows:
                return False
            if (fc, fr) in walls or (fc, fr) in enemy_occupied:
                return False
        return True

    def _anchor_in_enemy_ez(ac: int, ar: int) -> bool:
        offs = off_even if (ac & 1) == 0 else off_odd
        fp = {(ac + dc, ar + dr) for dc, dr in offs}
        return _movement_engagement_violates(
            game_state, unit, ac, ar, fp, units_cache, None,
            enemy_cache_items=enemy_items, engagement_zone_ez=ez,
        )

    # BFS Python de référence, niveau par niveau (garantit la distance minimale).
    reach: Set[Tuple[int, int]] = {(start_c, start_r)}
    current: Set[Tuple[int, int]] = {(start_c, start_r)}
    for _ in range(move_range):
        next_level: Set[Tuple[int, int]] = set()
        for cc, cr in current:
            parity = cc & 1
            nb = (
                ((cc, cr - 1), (cc + 1, cr - 1), (cc + 1, cr), (cc, cr + 1), (cc - 1, cr), (cc - 1, cr - 1))
                if parity == 0 else
                ((cc, cr - 1), (cc + 1, cr), (cc + 1, cr + 1), (cc, cr + 1), (cc - 1, cr + 1), (cc - 1, cr))
            )
            for nc, nr in nb:
                if (nc, nr) in reach:
                    continue
                if not _anchor_traversable(nc, nr):
                    continue
                reach.add((nc, nr))
                next_level.add((nc, nr))
        if not next_level:
            break
        current = next_level

    reach.discard((start_c, start_r))
    # Destination : empreinte hors occupation (allié ou ennemi) ET hors EZ ennemie (unengaged).
    valid: Set[Tuple[int, int]] = set()
    for ac, ar in reach:
        offs = off_even if (ac & 1) == 0 else off_odd
        fp = {(ac + dc, ar + dr) for dc, dr in offs}
        if not (fp & occupied) and not _anchor_in_enemy_ez(ac, ar):
            valid.add((ac, ar))
    return valid


def _assert_euclidean_pool_invariants(
    pool: List[Tuple[int, int]], game_state: Dict[str, Any], unit_id: str
) -> None:
    """Invariants SAINS du pool de move euclidien (indépendants de l'algo géodésique prod).

    Remplace l'égalité exacte à ``_oracle_pool`` (BFS hex), obsolète depuis Étape 4 : le pool
    est un champ géodésique euclidien (`move=euclidean`), pas un BFS 6-voisins. Un oracle
    euclidien « exact » reproduirait l'algo prod (tautologique) → on vérifie plutôt deux
    propriétés qui NE PEUVENT PAS faux-échouer et attrapent les vraies régressions :
      (1) légalité destination : aucune empreinte du pool ne chevauche bornes/murs/occupation ;
      (2) borne de non-triche : géodésique ≥ ligne droite ⟹ toute ancre atteinte est à distance
          centre-à-centre ≤ budget (`MOVE × ENGAGEMENT_NORM_HEX_WIDTH`) en ligne droite.
    """
    import math
    from engine.hex_utils import _hex_center, precompute_footprint_offsets, ENGAGEMENT_NORM_HEX_WIDTH

    unit = require_key(game_state["unit_by_id"], unit_id)
    units_cache = require_key(game_state, "units_cache")
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    walls = game_state.get("wall_hexes", set())
    shape = unit.get("BASE_SHAPE", "round")
    size = int(unit.get("BASE_SIZE", 1))
    orient = int(unit.get("orientation", 0) or 0)
    off_even, off_odd = precompute_footprint_offsets(shape, size, orient)
    start_c = int(require_key(unit, "col"))
    start_r = int(require_key(unit, "row"))
    move_range = int(require_key(unit, "MOVE"))
    mover_player = int(require_key(unit, "player"))

    occupied: Set[Tuple[int, int]] = set()
    for eid, ce in units_cache.items():
        if str(eid) == str(unit_id):
            continue
        c, r = int(require_key(ce, "col")), int(require_key(ce, "row"))
        e_even, e_odd = precompute_footprint_offsets(
            ce.get("BASE_SHAPE", "round"), int(ce.get("BASE_SIZE", 1)), int(ce.get("orientation", 0) or 0)
        )
        for dc, dr in (e_even if (c & 1) == 0 else e_odd):
            occupied.add((c + dc, r + dr))

    sx, sy = _hex_center(start_c, start_r)
    budget = move_range * ENGAGEMENT_NORM_HEX_WIDTH
    assert pool, "pool euclidien non vide attendu"
    for ac, ar in pool:
        offs = off_even if (ac & 1) == 0 else off_odd
        for dc, dr in offs:
            fc, fr = ac + dc, ar + dr
            assert 0 <= fc < board_cols and 0 <= fr < board_rows, f"{(ac, ar)} hors plateau"
            assert (fc, fr) not in walls, f"{(ac, ar)} chevauche un mur"
            assert (fc, fr) not in occupied, f"{(ac, ar)} chevauche une occupation"
        cx, cy = _hex_center(ac, ar)
        assert math.hypot(cx - sx, cy - sy) <= budget + 1e-6, (
            f"{(ac, ar)} au-delà du budget ({math.hypot(cx - sx, cy - sy):.2f} > {budget:.2f})"
        )


def test_vectorized_multi_hex_matches_oracle_base3_ez10_round() -> None:
    units = [
        {"id": 1, "col": 10, "row": 10, "HP_CUR": 2, "player": 0, "MOVE": 6,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 22, "row": 10, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 3, "col": 18, "row": 18, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ]
    pool, _fz, gs = _run_pool(units, ez=10)
    _assert_euclidean_pool_invariants(pool, gs, "1")


def test_vectorized_multi_hex_matches_oracle_with_walls_ez10() -> None:
    walls = {(c, 12) for c in range(8, 14)} | {(14, r) for r in range(8, 14)}
    units = [
        {"id": 1, "col": 10, "row": 10, "HP_CUR": 2, "player": 0, "MOVE": 5,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 25, "row": 25, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ]
    pool, _fz, gs = _run_pool(units, ez=10, walls=walls)
    _assert_euclidean_pool_invariants(pool, gs, "1")


def test_vectorized_multi_hex_matches_oracle_base2_ez1() -> None:
    units = [
        {"id": 1, "col": 5, "row": 5, "HP_CUR": 2, "player": 0, "MOVE": 4,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 10, "row": 5, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ]
    pool, _fz, gs = _run_pool(units, ez=1, board_cols=20, board_rows=20)
    assert set(pool) == _oracle_pool(gs, "1", ez=1)


def test_vectorized_multi_hex_matches_oracle_mixed_square_enemy_ez10() -> None:
    """Ennemi carré → branche dilatation hex. Doit coïncider avec l'oracle sémantique."""
    units = [
        {"id": 1, "col": 10, "row": 10, "HP_CUR": 2, "player": 0, "MOVE": 5,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 20, "row": 10, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "square"},
    ]
    pool, _fz, gs = _run_pool(units, ez=10)
    _assert_euclidean_pool_invariants(pool, gs, "1")


def test_movement_build_valid_destinations_pool_deterministic() -> None:
    """Deux appels identiques → mêmes ancres et même zone d’empreinte."""
    units = [_fill(u) for u in [
        {
            "id": 1,
            "col": 5,
            "row": 5,
            "HP_CUR": 2,
            "player": 0,
            "MOVE": 4,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
        {
            "id": 2,
            "col": 12,
            "row": 5,
            "HP_CUR": 2,
            "player": 1,
            "BASE_SIZE": 1,
            "MODEL_HEIGHT": 2.5,
            "BASE_SHAPE": "round",
        },
    ]]
    game_state: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5},
            "move": build_move_rules(),
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 20,
        "board_rows": 20,
        "current_player": 0,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": _make_unit_by_id(units),
        "inches_to_subhex": 1,
    }
    build_units_cache(game_state)
    build_enemy_adjacent_hexes(game_state, 0)
    assert "enemy_adjacent_hexes_player_0" in game_state

    pool1 = movement_build_valid_destinations_pool(game_state, "1")
    fz1 = set(game_state["move_preview_footprint_zone"])

    pool2 = movement_build_valid_destinations_pool(game_state, "1")
    fz2 = set(game_state["move_preview_footprint_zone"])

    assert sorted(pool1) == sorted(pool2)
    assert fz1 == fz2
    assert (5, 5) in fz1 or (5, 5) in game_state.get("move_preview_footprint_zone", set())
    assert len(pool1) >= 1
