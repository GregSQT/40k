"""
Régression : ``movement_build_valid_destinations_pool`` et ``enemy_cache_items`` pour
``_movement_engagement_violates`` (ez > 1) — même résultat qu’un scan complet du cache.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

import pytest

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
    gym: bool = False,
) -> Tuple[List[Tuple[int, int]], Set[Tuple[int, int]], Dict[str, Any]]:
    """Appelle ``movement_build_valid_destinations_pool`` (chemin unique vectorisé NumPy).

    ``gym=True`` pose ``gym_training_mode`` → ``_move_distance_metric`` lit ``move_gym`` (=hex) et
    le chemin GROUND multi-hex passe par ``_build_multi_hex_vectorized`` (la cible du training x5),
    au lieu du chemin ``move``=euclidean du PvP. Défaut ``False`` = comportement historique.
    """
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
    if gym:
        game_state["gym_training_mode"] = True
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


# ── V11 §0.22 Étape 1 — égalité stricte du pool HEX multi-hex ez>1 (chemin `_build_multi_hex_
# vectorized`, 100 % du training x5) contre l'oracle. Le trou : les cas ez>1 ci-dessus tournent en
# `move`=euclidean (PvP) et n'imposent que des invariants ; personne ne verrouillait le pool hex
# réellement produit en gym. On force `gym=True` (→ move_gym=hex). Socles ronds/carrés seulement :
# `_oracle_pool` fait `int(BASE_SIZE)` et ne modélise pas les ovales `[20,14]` (couverts plus tard
# par le test A/B cache-vs-sans-cache, cf. V11_move_pool_optimization.md §7-§8).

_HEX_ORACLE_CASES = [
    ("base2_round_ez10", [
        {"id": 1, "col": 12, "row": 12, "HP_CUR": 2, "player": 0, "MOVE": 5,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 26, "row": 12, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 10, None),
    ("base3_round_ez10", [
        {"id": 1, "col": 12, "row": 12, "HP_CUR": 2, "player": 0, "MOVE": 6,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 24, "row": 12, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 10, None),
    ("base2_walls_ez5", [
        {"id": 1, "col": 12, "row": 12, "HP_CUR": 2, "player": 0, "MOVE": 5,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 28, "row": 28, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 5, {(c, 15) for c in range(9, 16)} | {(16, r) for r in range(9, 16)}),
]


@pytest.mark.parametrize(
    "name,units,ez,walls", _HEX_ORACLE_CASES, ids=[c[0] for c in _HEX_ORACLE_CASES]
)
def test_hex_multihex_pool_equals_oracle(name, units, ez, walls):
    """Le pool hex (gym) multi-hex ez>1 doit être STRICTEMENT égal à l'oracle BFS hex."""
    pool, _fz, gs = _run_pool(units, ez, walls=walls, gym=True)
    oracle = _oracle_pool(gs, "1", ez=ez)
    assert set(pool) == oracle, (
        f"[{name}] pool hex prod != oracle\n"
        f"  prod seul: {sorted(set(pool) - oracle)[:20]}\n"
        f"  oracle seul: {sorted(oracle - set(pool))[:20]}"
    )


def test_hex_oracle_test_actually_reaches_build_multi_hex_vectorized(monkeypatch):
    """GARDE D'ATTEINTE (motif §0.11) : sans elle, l'égalité ci-dessus pourrait tester un autre
    chemin (single-hex / euclidean) et ne rien couvrir de la cible."""
    import engine.phase_handlers.movement_handlers as mh

    calls = {"n": 0}
    orig = mh._build_multi_hex_vectorized

    def _spy(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(mh, "_build_multi_hex_vectorized", _spy)
    name, units, ez, walls = _HEX_ORACLE_CASES[0]
    _run_pool(units, ez, walls=walls, gym=True)
    assert calls["n"] >= 1, (
        "_build_multi_hex_vectorized JAMAIS appelé : l'égalité teste un autre chemin que la cible."
    )


# ── V11 §0.22 — SNAPSHOT golden pour les socles OVALES `[20,14]` (chemin hex/gym).
# `_oracle_pool` fait `int(BASE_SIZE)` et ne peut pas les modéliser (§7 du doc dédié) ; or c'est le
# 2ᵉ socle le plus fréquent du training (17,7 %). Ce golden fige le pool ET la footprint zone
# produits AUJOURD'HUI : tout refacto d'extraction (Étape 2) ou cache (Étape 3) doit les laisser
# STRICTEMENT inchangés. Valeurs capturées le 2026-07-21 sur le code de référence.
# Régénération (si le pool change LÉGITIMEMENT) : imprimer len + sha256[:16] de sorted(set(pool))
# et de sorted(fz), et reporter ici — jamais éditer à l'aveugle.
import hashlib

_OVAL_SNAPSHOT = {
    # orientation -> (pool_len, pool_sha16, fz_len, fz_sha16)
    0: (419, "9377c8dc50eef5d0", 1170, "9808806103a4b978"),
    1: (449, "0b2ab46bf3d879a6", 1208, "fb5e179a6998400b"),
}


@pytest.mark.parametrize("orient", [0, 1])
def test_oval_base_hex_pool_snapshot(orient):
    """Non-régression stricte du pool ovale hex/gym (socle non couvert par l'oracle)."""
    units = [
        {"id": 1, "col": 20, "row": 40, "HP_CUR": 2, "player": 0, "MOVE": 12,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": orient},
        {"id": 2, "col": 60, "row": 40, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": orient},
    ]
    pool, fz, _gs = _run_pool(units, ez=10, board_cols=80, board_rows=80, gym=True)
    pool_s = sorted(set(pool))
    fz_s = sorted(fz)
    exp_pool_len, exp_pool_h, exp_fz_len, exp_fz_h = _OVAL_SNAPSHOT[orient]
    got_pool_h = hashlib.sha256(repr(pool_s).encode()).hexdigest()[:16]
    got_fz_h = hashlib.sha256(repr(fz_s).encode()).hexdigest()[:16]
    assert (len(pool_s), got_pool_h) == (exp_pool_len, exp_pool_h), (
        f"pool ovale orient={orient} a changé : len {len(pool_s)} (attendu {exp_pool_len}), "
        f"hash {got_pool_h} (attendu {exp_pool_h}) — régression de pool ou changement légitime."
    )
    assert (len(fz_s), got_fz_h) == (exp_fz_len, exp_fz_h), (
        f"footprint zone ovale orient={orient} a changé : len {len(fz_s)} (attendu {exp_fz_len})."
    )


# ── V11 §0.22 L_bbox — A/B : le fenêtrage bbox des dilatations produit un pool ET une footprint
# zone STRICTEMENT identiques au plein-board. Garde-fou central du levier (cf.
# V11_move_pool_optimization.md §7). Contrairement à l'oracle, cet A/B couvre TOUTES les formes
# (ovales inclus) car il compare le MÊME code à lui-même, seule la fenêtre changeant.
# `out_costs` n'est PAS dans cet A/B : il est rempli par le BFS ground (`_dist_arr`), que L_bbox
# ne touche pas (seuls `_dilate`/`_spread` sont fenêtrés) → invariant par construction.
_LBBOX_AB_CASES = [
    ("round2_ez10", [
        {"id": 1, "col": 20, "row": 20, "HP_CUR": 2, "player": 0, "MOVE": 6,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 34, "row": 20, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 10, None, 60, 60),
    ("round3_walls_ez5", [
        {"id": 1, "col": 18, "row": 18, "HP_CUR": 2, "player": 0, "MOVE": 7,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 40, "row": 40, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 5, {(c, 24) for c in range(12, 26)} | {(25, r) for r in range(12, 26)}, 60, 60),
    ("round2_adjacent_enemy_ez1", [
        {"id": 1, "col": 20, "row": 20, "HP_CUR": 2, "player": 0, "MOVE": 5,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 24, "row": 20, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 1, None, 60, 60),
    ("square2_ez10", [
        {"id": 1, "col": 20, "row": 20, "HP_CUR": 2, "player": 0, "MOVE": 6,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "square", "orientation": 1},
        {"id": 2, "col": 34, "row": 20, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "square"},
    ], 10, None, 60, 60),
    ("oval_move12_orient0_ez10", [
        {"id": 1, "col": 20, "row": 40, "HP_CUR": 2, "player": 0, "MOVE": 12,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": 0},
        {"id": 2, "col": 60, "row": 40, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": 0},
    ], 10, None, 80, 80),
    ("oval_move12_orient1_ez10", [
        {"id": 1, "col": 20, "row": 40, "HP_CUR": 2, "player": 0, "MOVE": 12,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": 1},
        {"id": 2, "col": 60, "row": 40, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": [20, 14], "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "oval", "orientation": 1},
    ], 10, None, 80, 80),
    ("round_move12_edge_clamp", [
        {"id": 1, "col": 3, "row": 3, "HP_CUR": 2, "player": 0, "MOVE": 12,
         "BASE_SIZE": 3, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
        {"id": 2, "col": 50, "row": 50, "HP_CUR": 2, "player": 1,
         "BASE_SIZE": 2, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round"},
    ], 10, None, 60, 60),
]


@pytest.mark.parametrize(
    "name,units,ez,walls,bc,br", _LBBOX_AB_CASES, ids=[c[0] for c in _LBBOX_AB_CASES]
)
def test_bbox_window_equals_full_board(monkeypatch, name, units, ez, walls, bc, br):
    """Pool + footprint zone fenêtrés (prod) == plein-board (`_bbox_window=False`)."""
    import engine.phase_handlers.movement_handlers as mh

    # Fenêtré (défaut de prod).
    pool_win, fz_win, _gs = _run_pool(
        [dict(u) for u in units], ez, walls=walls, board_cols=bc, board_rows=br, gym=True
    )

    # Plein-board forcé via injection du kwarg additif.
    orig = mh._build_multi_hex_vectorized

    def _full_board(*a, **k):
        k["_bbox_window"] = False
        return orig(*a, **k)

    monkeypatch.setattr(mh, "_build_multi_hex_vectorized", _full_board)
    pool_full, fz_full, _gs2 = _run_pool(
        [dict(u) for u in units], ez, walls=walls, board_cols=bc, board_rows=br, gym=True
    )

    assert set(pool_win) == set(pool_full), (
        f"[{name}] pool fenêtré != plein-board\n"
        f"  fenêtré seul: {sorted(set(pool_win) - set(pool_full))[:20]}\n"
        f"  plein seul:   {sorted(set(pool_full) - set(pool_win))[:20]}"
    )
    assert fz_win == fz_full, (
        f"[{name}] footprint zone fenêtrée != plein-board "
        f"(Δ={len(fz_win ^ fz_full)} cellules)"
    )


def test_ground_bbox_window_narrows_and_clamps():
    """GARDE D'ATTEINTE : la fenêtre bbox est STRICTEMENT plus petite que le board (sinon l'A/B
    validerait un no-op), et englobe reach (start ± move_range) + empreintes (±max|offset|)."""
    import numpy as np
    from engine.hex_utils import precompute_footprint_offsets
    from engine.phase_handlers.movement_handlers import _ground_move_bbox_window

    off_e, off_o = precompute_footprint_offsets("round", 2, 0)
    oe = np.asarray(off_e, dtype=np.int64).reshape(-1, 2)
    oo = np.asarray(off_o, dtype=np.int64).reshape(-1, 2)
    max_off = int(max(np.abs(oe).max(), np.abs(oo).max()))

    # Board large, portée modeste, centre loin des bords → fenêtre strictement incluse.
    c_lo, c_hi, r_lo, r_hi = _ground_move_bbox_window(100, 150, 6, oe, oo, 220, 300)
    assert (c_hi - c_lo) < 220 and (r_hi - r_lo) < 300, "la fenêtre doit réduire le board"
    # Englobe reach + empreinte : au moins start ± (move_range) accessible dans la fenêtre.
    assert c_lo <= 100 - 6 and c_hi > 100 + 6
    assert r_lo <= 150 - 6 and r_hi > 150 + 6
    # Marge exacte = move_range + max|offset|.
    assert c_lo == 100 - (6 + max_off)
    assert c_hi == 100 + (6 + max_off) + 1

    # Bords : clamp au plateau, jamais hors bornes.
    c_lo2, c_hi2, r_lo2, r_hi2 = _ground_move_bbox_window(2, 2, 12, oe, oo, 60, 60)
    assert c_lo2 == 0 and r_lo2 == 0
    assert c_hi2 <= 60 and r_hi2 <= 60


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
