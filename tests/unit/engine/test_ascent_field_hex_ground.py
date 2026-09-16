"""Champ de montée par-figurine (13.06) en métrique HEX — le sol est le BFS hex du gym.

Jumeau hex de ``test_ascent_field_reuses_euclidean_field.py``. En métrique hex (gym x1, ou x5
sous ``gym_distance_metric: hex``), ``ascent_field_for_model`` injecte comme passe de départ le
BFS hex de plain-pied (``geodesic_move_reach`` sur le bitmap de niveau 0, coût × 1,5) au lieu de
laisser ``reachable_multilevel_field`` relancer la passe any-angle avec clairance au sol — la
passe la plus chère du step d'entraînement (8,8 s sur 39,8 s de 200 pas du banc x1).

Ce que cela CHANGE, et que ce fichier verrouille : le sol d'une montée est mesuré comme le move
à plat du gym (pas hex par cellule, sans clairance de socle) — jusqu'à 15 % de portée en plus
(√3 / 1,5 vers le sud) et des passages d'une case admis ; la passe d'ÉTAGE reste any-angle avec
clairance. Quatre invariants :

- la passe de départ n'est plus calculée en any-angle, et le champ rendu n'est pas vide ;
- le champ injecté est un SUR-ENSEMBLE du champ any-angle à budget égal (le sol hex ne coûte
  jamais plus que le sol any-angle avec clairance — vérifié sur 32 245 cases de 60 cartes
  aléatoires avant d'écrire ce verrou), strict quand un couloir d'une case est le seul accès, et
  aucune case d'étage ne sort du budget ni ne coûte moins que « distance hex + montée » ;
- le pré-check de portée (``multilevel_target_within_straight_bound``) est averti : la ligne
  droite euclidienne ne minore plus un sol hex, un plancher plein sud est atteignable à 15 pas là
  où la ligne droite en compte 17,3 — sans l'aiguillage, le champ rendait ``{}`` en silence ;
- parité masque / validation : toute montée offerte par ``erode_move_pool_by_squad_block`` est
  acceptée par ``model_reach_predicate`` au même budget, et toute montée érodée y est refusée.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.combat_utils import GYM_DISTANCE_METRIC_KEY
from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH, get_neighbors, hex_distance
from engine.phase_handlers import geodesic_move as gm
from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.movement_handlers import ASCENT_DECLARED_KEY
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants

_FLOOR_HEXES = [(c, r) for c in range(24, 30) for r in range(16, 26)]
_FLOOR_POLYGON = [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]]
#: x5 : 5 sous-hexes par pouce ; étage à 1" → 5 sous-hexes de montée (7,5 unités-norme).
_INCHES_TO_SUBHEX = 5
_CLIMB_SUBHEX = 5
_BUDGET = 30  # sous-hexes (6" à x5)
_START = (18, 20)  # 6 colonnes du plancher
#: Mur en travers du chemin direct vers l'étage (colonne 21, lignes 17..23), contourné par le haut/bas.
_WALLS = {(21, r) for r in range(17, 24)}
#: Muraille d'un bord à l'autre du budget (colonne 21, lignes 5..35) percée d'UNE case en (21,20) :
#: le BFS hex passe par la brèche, le socle any-angle (rayon 2,25 pour BASE_SIZE 3) ne peut ni
#: la franchir ni contourner la muraille dans le budget.
_LONG_WALL = {(21, r) for r in range(5, 36)} - {(21, 20)}


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]],
          shape: str = "round", size: Any = 3, move: int = _BUDGET) -> Dict[str, Any]:
    col, row = models[0]
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": size, "MODEL_HEIGHT": 2.5,
        # MOVE est en SOUS-HEXES dans le moteur (`game_state.py`, `config["MOVE"] * scale`) :
        # l'érosion en dérive son budget (`get_squad_move_budget`), pas d'un paramètre.
        "BASE_SHAPE": shape, "MOVE": int(move), "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "models": [{"col": c, "row": r, "VALUE": 10, "orientation": 0} for c, r in models],
    }


def _make_gs(units: List[Dict[str, Any]], *, walls: Any = _WALLS,
             floor_hexes: Sequence[Tuple[int, int]] = _FLOOR_HEXES) -> Dict[str, Any]:
    """État x5 en métrique HEX : ``gym_training_mode`` + ``gym_distance_metric: hex`` posés ICI,
    pour que le test ne dépende pas de la valeur ``move_gym`` de ``game_config.json``."""
    floor = list(floor_hexes)
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 5, "engagement_zone_vertical": 5,
                "max_base_size_hex": 35, "unit_model_cohesion_range": 10,
                "unit_global_cohesion_range": 45, "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 60, "board_rows": 60,
        "current_player": 1,
        "phase": "move",
        "gym_training_mode": True,
        GYM_DISTANCE_METRIC_KEY: "hex",
        "wall_hexes": set(walls),
        "terrain_areas": [{
            "id": "ruin", "polygon_vertices": _FLOOR_POLYGON, "hexes": floor,
            "floors": [{"level": 1, "height_inches": 1.0, "hexes": floor,
                        "polygon_vertices": _FLOOR_POLYGON}],
        }],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(), "units_advanced": set(),
        "units_moved": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": _INCHES_TO_SUBHEX,
        "action_logs": [], "action_log_seq": 0, "current_turn": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    build_enemy_adjacent_hexes(gs, 2)
    assert su.move_plan_distance_mode(gs, "1") == "geodesic", "prémisse : métrique hex au sol"
    return gs


def _model(gs: Dict[str, Any]) -> Dict[str, Any]:
    return gs["models_cache"]["1#0"]


def _ascent(gs: Dict[str, Any], budget: int = _BUDGET) -> Dict[Tuple[int, int], int]:
    return dict(su.ascent_field_for_model(gs, "1", 1, _model(gs), 1, budget))


def _any_angle_reference(gs: Dict[str, Any], budget: int = _BUDGET) -> Dict[Tuple[int, int], int]:
    """Le champ de montée SANS injection : sol any-angle avec clairance, comme avant 2026-09-16.
    Même obstacles de sol que ``ascent_field_for_model`` (bitmap de niveau 0, départ retiré)."""
    model = _model(gs)
    pairs, _bm = su.move_transit_blocked_forms(gs, "1", 1, 0)
    ground = set(pairs)
    ground.discard(_START)
    return dict(mh._model_multilevel_reachable_field(
        gs, gs["unit_by_id"]["1"], "1", model, _START, budget, {1},
        ground, gs["terrain_areas"], start_level=0,
    ).get(1, {}))


def _count_start_passes(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    """Passes multi-source SEEDÉES DEPUIS LE DÉPART (une source, distance 0) — la passe any-angle
    au sol que l'injection supprime. Les passes d'étage (seeds de portail) ne comptent pas."""
    calls = [0]
    real = gm._euclidean_move_field_multi

    def counted(starts: Dict[Tuple[int, int], float], *args: Any, **kwargs: Any) -> Any:
        if len(starts) == 1 and next(iter(starts.values())) == 0.0:
            calls[0] += 1
        return real(starts, *args, **kwargs)

    monkeypatch.setattr(gm, "_euclidean_move_field_multi", counted)
    return calls


def _count_hex_bfs(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    calls = [0]
    real = su.geodesic_move_reach

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(su, "geodesic_move_reach", counted)
    return calls


# ─────────────────── (1) la passe de départ est le BFS hex, jamais l'any-angle ───────────────────

def test_hex_ground_pass_is_the_hex_bfs_not_the_any_angle_field(monkeypatch: pytest.MonkeyPatch):
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])])
    starts = _count_start_passes(monkeypatch)
    bfs = _count_hex_bfs(monkeypatch)
    field = _ascent(gs)
    assert field, "prémisse : l'étage est atteignable"
    assert set(field) <= set(_FLOOR_HEXES)
    assert starts[0] == 0, "métrique hex : aucune passe any-angle seedée depuis le départ"
    assert bfs[0] == 1, "le sol est UN BFS hex, calculé ici (pas relu d'un cache absent)"
    # Mémoïsé sous `climb` : le second appel ne recalcule ni BFS ni champ.
    assert _ascent(gs) == field
    assert bfs[0] == 1


def test_hex_ascent_field_is_a_superset_of_the_any_angle_one_and_stays_in_budget():
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])])
    reference = _any_angle_reference(gs)
    assert reference, "prémisse : le champ any-angle atteint l'étage (mur contourné)"
    field = _ascent(gs)
    assert set(reference) <= set(field), sorted(set(reference) - set(field))[:5]
    for cell, cost in field.items():
        assert cost <= _BUDGET, (cell, cost)
        # Le sol hex coûte au moins la distance hex, le portail au moins 0, la montée exactement
        # 5 sous-hexes : aucune case d'étage sous « distance hex + montée ».
        assert cost >= hex_distance(_START[0], _START[1], cell[0], cell[1]) + _CLIMB_SUBHEX, (cell, cost)
        assert cost <= reference.get(cell, cost), (cell, cost, reference.get(cell))
    # Le budget borne réellement : à 16 sous-hexes, seules les premières cases de l'étage passent
    # (13 à 16), et le fond de l'étage reste hors de portée. État NEUF : le champ est mémoïsé sans
    # le budget dans sa clé (un champ large répond pour tout budget inférieur, l'appelant compare
    # le COÛT), donc relire `gs` rendrait le champ à 30.
    narrow = _ascent(_make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])]), 16)
    assert narrow and set(narrow) < set(field), sorted(narrow)
    assert (29, 25) not in narrow and all(cost <= 16 for cost in narrow.values())


def test_one_cell_corridor_is_open_to_the_hex_ground_and_closed_to_the_any_angle_one():
    """Sens du changement de métrique, au cas le plus visible : la brèche d'une case. Le BFS hex
    la traverse (pas de clairance), le socle any-angle de rayon 2,25 non — et la muraille est trop
    longue pour être contournée dans le budget. Avant l'injection, cette montée n'existait pas."""
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 30)])], walls=_LONG_WALL)
    assert _any_angle_reference(gs) == {}, "prémisse : la brèche est fermée au socle any-angle"
    field = _ascent(gs)
    assert field, "la brèche d'une case est ouverte au sol hex : la montée est offerte"
    assert all(cost <= _BUDGET for cost in field.values())


# ─────────────────── (2) le pré-check de portée connaît la métrique du sol ───────────────────

def _south_floor_scene() -> Tuple[Dict[str, Any], ...]:
    """Plancher 3 × 3 dont la première ligne est 10 lignes PLEIN SUD du départ (même colonne) :
    10 pas hex = 15 unités-norme, mais 17,32 en ligne droite (√3 par pas vers le sud)."""
    start = (20, 5)
    floor = frozenset((c, r) for c in range(19, 22) for r in range(15, 18))
    ring = {nb for cell in floor for nb in get_neighbors(cell[0], cell[1]) if nb not in floor}
    height = {0: 0.0, 1: _CLIMB_SUBHEX * ENGAGEMENT_NORM_HEX_WIDTH}
    return {"start": start, "floor": floor, "ring": ring, "height": height},


@pytest.mark.parametrize("budget_subhex, expected_cells", [(15, 1), (16, 4)])
def test_precheck_hex_bound_admits_a_floor_the_straight_line_rejects(budget_subhex: int, expected_cells: int):
    (scene,) = _south_floor_scene()
    start, floor, ring, height = scene["start"], scene["floor"], scene["ring"], scene["height"]
    budget_norm = budget_subhex * ENGAGEMENT_NORM_HEX_WIDTH
    table = su.hex_index_table(40, 40)
    hex_ground = {
        cell: steps * ENGAGEMENT_NORM_HEX_WIDTH
        for cell, steps in su.geodesic_move_reach(start[0], start[1], budget_subhex, table.bitmap_in_bounds(set())).items()
    }
    field = gm.reachable_multilevel_field(
        start, 0, "round", 1, (), (), 40, 40, {0: set(), 1: ring}, {1: floor}, height,
        budget_norm, precomputed_start_field=hex_ground,
    )
    on_floor = {k[:2] for k in field if k[2] == 1}
    assert len(on_floor) == expected_cells, sorted(on_floor)
    # Ligne droite : 17,32 + 7,5 > 22,5 (budget 15) et > 24 (budget 16) → « rien à atteindre ».
    assert not gm.multilevel_target_within_straight_bound(start, 0, {1}, {1: floor}, height, budget_norm)
    # Borne hex : 15 + 7,5 = 22,5 <= budget → le champ doit être calculé.
    assert gm.multilevel_target_within_straight_bound(
        start, 0, {1}, {1: floor}, height, budget_norm, ground_is_hex=True
    )


def test_precheck_hex_bound_keeps_the_dijkstra_tolerance():
    """La passe d'étage reste any-angle et admet à ``budget + _SEG_TOL`` : la borne hex garde la
    même tolérance, sinon une case rendue par le champ serait déclarée hors de portée."""
    from engine.hex_utils import _SEG_TOL
    (scene,) = _south_floor_scene()
    start, floor, height = scene["start"], scene["floor"], scene["height"]
    exact = 10 * ENGAGEMENT_NORM_HEX_WIDTH + height[1]  # 22,5 : la case (20, 15) au budget exact
    assert gm.multilevel_target_within_straight_bound(
        start, 0, {1}, {1: floor}, height, exact - _SEG_TOL / 2, ground_is_hex=True
    )
    assert not gm.multilevel_target_within_straight_bound(
        start, 0, {1}, {1: floor}, height, exact - 2 * _SEG_TOL, ground_is_hex=True
    )


def test_precheck_hex_bound_is_never_tighter_than_the_straight_line():
    """1,5 × distance hex <= distance euclidienne : tout ce que la ligne droite admet, la borne hex
    l'admet aussi (elle n'écarte que des champs que l'ancienne borne écartait déjà)."""
    floor = frozenset((c, r) for c in range(30, 33) for r in range(30, 33))
    height = {0: 0.0, 1: 7.5}
    for start in [(5, 5), (30, 5), (5, 31), (31, 5), (50, 50), (33, 34)]:
        for budget in range(0, 60, 3):
            straight = gm.multilevel_target_within_straight_bound(start, 0, {1}, {1: floor}, height, float(budget))
            hexb = gm.multilevel_target_within_straight_bound(start, 0, {1}, {1: floor}, height, float(budget), ground_is_hex=True)
            assert not (straight and not hexb), (start, budget)


def test_precheck_runs_on_the_production_path_with_the_hex_bound(monkeypatch: pytest.MonkeyPatch):
    """Preuve que ``ascent_field_for_model`` transmet l'aiguillage : sur la scène plein sud, le
    champ de PRODUCTION rend la case d'étage — sans ``ground_is_hex`` il rendait ``{}``."""
    start = (20, 5)
    floor = [(c, r) for c in range(19, 22) for r in range(15, 18)]
    gs = _make_gs([_unit("1", 1, [start]), _unit("2", 2, [(50, 50)])], walls=set(), floor_hexes=floor)
    seen: List[bool] = []
    real = gm.multilevel_target_within_straight_bound

    def spy(*args: Any, **kwargs: Any) -> bool:
        seen.append(bool(kwargs.get("ground_is_hex", False)))
        return real(*args, **kwargs)

    monkeypatch.setattr(mh, "multilevel_target_within_straight_bound", spy)
    field = dict(su.ascent_field_for_model(gs, "1", 1, _model(gs), 1, 15))
    assert seen == [True], "le pré-check a été appelé une fois, en borne hex"
    assert field == {(20, 15): 15}


def test_multilevel_field_refuses_hex_flag_without_a_field():
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])])
    with pytest.raises(ValueError, match="precomputed_start_is_hex"):
        mh._model_multilevel_reachable_field(
            gs, gs["unit_by_id"]["1"], "1", _model(gs), _START, _BUDGET, {1},
            set(), gs["terrain_areas"], precomputed_start_is_hex=True,
        )


# ─────────────────── (3) parité masque ⊆ exécutable ───────────────────

def test_every_ascent_the_mask_offers_is_accepted_by_the_reach_predicate():
    """Érosion (masque) et prédicat (validation) lisent le même champ : une montée offerte est
    acceptée, une montée érodée est refusée — au même budget, mono-figurine (ancre = figurine).

    Budget 16 (MOVE de l'unité, en sous-hexes : l'érosion le lit là, pas dans un paramètre) pour
    que le coût vertical érode réellement des cases du plancher (coûts de montée 13 à 25 sur ce
    plancher). Ennemi loin : sa zone d'engagement interdirait des destinations (09.05) que le
    prédicat de TRAJET, lui, ne juge pas — ce test ne mesure que la borne de trajet."""
    budget = 16
    gs = _make_gs([_unit("1", 1, [_START], move=budget), _unit("2", 2, [(50, 50)])])
    gs[ASCENT_DECLARED_KEY] = {"1"}
    model = _model(gs)
    level_map = mh.squad_floor_level_map(gs, model)
    assert set(_FLOOR_HEXES) <= set(level_map), "prémisse : le plancher est tenable par ce socle"
    # Pool d'ancre = BFS hex de plain-pied, comme le pool du gym en métrique hex.
    _pairs, bm = su.move_transit_blocked_forms(gs, "1", 1, 0)
    pool = {cell: float(steps) for cell, steps in su.geodesic_move_reach(_START[0], _START[1], budget, bm).items()}
    pool_floor = {cell for cell in pool if cell in level_map}
    assert len(pool_floor) > 1, "prémisse : le pool à plat pose des cellules sur le plancher"

    kept = su.erode_move_pool_by_squad_block(gs, "1", dict(pool), move_budget=budget)
    kept_floor = {cell for cell in kept if cell in level_map}
    eroded_floor = pool_floor - kept_floor
    assert kept_floor, "VERT VACANT : le masque doit offrir au moins une montée"
    assert eroded_floor, "VERT VACANT : la montée doit avoir érodé au moins une cellule (coût vertical)"

    reach = su.model_reach_predicate(gs, "1", 1, model, budget, 1)
    offered_but_refused = sorted(cell for cell in kept_floor if not reach(cell[0], cell[1]))
    assert not offered_but_refused, offered_but_refused[:5]
    eroded_but_accepted = sorted(cell for cell in eroded_floor if reach(cell[0], cell[1]))
    assert not eroded_but_accepted, eroded_but_accepted[:5]
    # Et c'est bien le champ injecté qui a tranché : offert ⇔ coût de montée <= budget.
    climb = _ascent(gs, budget)
    assert kept_floor == {cell for cell in pool_floor if climb.get(cell, budget + 1) <= budget}
