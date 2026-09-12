"""Champs multi-niveaux par-figurine (13.06) — pré-check de portée et portails mémoïsés.

Deux économies qui ne doivent RIEN changer au champ rendu :

- ``multilevel_target_within_straight_bound`` : borne inférieure « ligne droite + dénivelé ». Si
  aucune cellule d'aucun niveau cible ne tient dans le budget même ainsi, le champ serait vide
  sur ces niveaux, et ``_model_multilevel_reachable_field`` (move) comme
  ``_charge_model_multilevel_reachable_cells`` (charge) le rendent SANS lancer le Dijkstra.
  Le verrou : la version avec pré-check et la version forcée (borne court-circuitée à True)
  rendent le même dict — figurine loin (couches vides) comme figurine proche (couches pleines).
- ``_build_level_transitions`` : portails statiques par terrain, mémoïsés par VALEUR des entrées.
  Deux appels aux entrées égales mais distinctes ne calculent qu'une fois ; une hauteur ou le
  flag FLY différents recalculent.

Les compteurs sont posés sur les MODULES (``geodesic_move``), seul point d'interception valable
quel que soit l'appelant ; leur non-vacuité côté « champ calculé » garantit qu'un vert n'est pas
vacant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH
from engine.phase_handlers import charge_handlers as ch
from engine.phase_handlers import geodesic_move as gm
from engine.phase_handlers import movement_handlers as mh
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants

#: Bloc d'étage 5 × 7 : le socle oval [4, 2] non pivoté (7 hexes en ligne) y tient entier.
_FLOOR_HEXES = [(c, r) for c in range(19, 24) for r in range(17, 24)]
_FLOOR_POLYGON = [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]]
_BUDGET = 10  # sous-hexes (inches_to_subhex = 1) ; étage à 3" → 4,5 unités-norme de montée
_FAR = (5, 5)  # ~14 colonnes du plancher (≈ 21 unités-norme) : hors de tout budget de 10 (15)
_NEAR = (16, 20)  # 3 colonnes du plancher


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    col, row = models[0]
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": [4, 2], "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "oval", "MOVE": _BUDGET, "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "models": [{"col": c, "row": r, "VALUE": 10, "orientation": 0} for c, r in models],
    }


def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5,
                "max_base_size_hex": 35, "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9, "squad_min_neighbors": 1,
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
        "wall_hexes": set(),
        "terrain_areas": [{
            "id": "ruin", "polygon_vertices": _FLOOR_POLYGON, "hexes": _FLOOR_HEXES,
            "floors": [{"level": 1, "height_inches": 3.0, "hexes": _FLOOR_HEXES,
                        "polygon_vertices": _FLOOR_POLYGON}],
        }],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(), "units_fled": set(), "units_advanced": set(),
        "units_moved": set(),
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "action_logs": [], "action_log_seq": 0, "current_turn": 1,
        "enemy_adjacent_hexes_player_1": set(), "enemy_adjacent_hexes_player_2": set(),
    }
    build_units_cache(gs)
    return gs


def _count_multi_source(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    """Compteur des passes Dijkstra multi-source (une par niveau développé)."""
    calls = [0]
    real = gm.geodesic_field_multi_source

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(gm, "geodesic_field_multi_source", counted)
    return calls


def _force_full_compute(monkeypatch: pytest.MonkeyPatch) -> None:
    """Court-circuite la borne : le champ est TOUJOURS calculé (référence sans pré-check).
    Le move importe le symbole au niveau module, la charge à l'appel : les deux sont patchés."""
    monkeypatch.setattr(gm, "multilevel_target_within_straight_bound", lambda *a, **k: True)
    monkeypatch.setattr(mh, "multilevel_target_within_straight_bound", lambda *a, **k: True)


def _move_field(gs: Dict[str, Any], start: Tuple[int, int]) -> Dict[int, Dict[Tuple[int, int], int]]:
    unit = gs["unit_by_id"]["1"]
    return mh._model_multilevel_reachable_field(
        gs, unit, "1", gs["models_cache"]["1#0"], start, _BUDGET, {1}, set(), gs["terrain_areas"],
        start_level=0,
    )


def _charge_field(gs: Dict[str, Any], start: Tuple[int, int]) -> Dict[int, Dict[Tuple[int, int], int]]:
    unit = gs["unit_by_id"]["1"]
    return ch._charge_model_multilevel_reachable_cells(
        gs, unit, "1", gs["models_cache"]["1#0"], start, _BUDGET, {1}, set(), gs["terrain_areas"],
        start_level=0,
    )


# ─────────────────────────── Pré-check : move ───────────────────────────

def test_move_far_model_skips_dijkstra_and_returns_empty_layers(monkeypatch: pytest.MonkeyPatch):
    gs = _make_gs([_unit("1", 1, [_FAR])])
    calls = _count_multi_source(monkeypatch)
    out = _move_field(gs, _FAR)
    assert out == {1: {}}
    assert calls[0] == 0, "figurine hors de toute portée : aucune passe Dijkstra attendue"


def test_move_field_identical_with_and_without_precheck(monkeypatch: pytest.MonkeyPatch):
    gs_near = _make_gs([_unit("1", 1, [_NEAR])])
    gs_far = _make_gs([_unit("1", 1, [_FAR])])
    with_precheck_near = _move_field(gs_near, _NEAR)
    with_precheck_far = _move_field(gs_far, _FAR)
    assert with_precheck_near[1], "prémisse : la figurine proche atteint l'étage"

    calls = _count_multi_source(monkeypatch)
    _force_full_compute(monkeypatch)
    assert _move_field(gs_near, _NEAR) == with_precheck_near
    assert _move_field(gs_far, _FAR) == with_precheck_far
    assert calls[0] >= 2, "référence vacante : le champ forcé n'a lancé aucune passe"


def test_move_ground_target_is_never_skipped(monkeypatch: pytest.MonkeyPatch):
    """Le sol parmi les cibles n'a pas de borne : le champ est calculé même loin de tout étage."""
    gs = _make_gs([_unit("1", 1, [_FAR])])
    calls = _count_multi_source(monkeypatch)
    out = mh._model_multilevel_reachable_field(
        gs, gs["unit_by_id"]["1"], "1", gs["models_cache"]["1#0"], _FAR, _BUDGET, {0, 1}, set(),
        gs["terrain_areas"], start_level=0,
    )
    assert calls[0] >= 1
    assert out[0], "les cases du sol atteignables doivent être rendues"
    assert out[1] == {}


# ─────────────────────────── Pré-check : charge (jumeau) ───────────────────────────

def test_charge_far_model_skips_dijkstra_and_returns_empty_layers(monkeypatch: pytest.MonkeyPatch):
    gs = _make_gs([_unit("1", 1, [_FAR])])
    calls = _count_multi_source(monkeypatch)
    out = _charge_field(gs, _FAR)
    assert out == {1: {}}
    assert calls[0] == 0


def test_charge_field_identical_with_and_without_precheck(monkeypatch: pytest.MonkeyPatch):
    gs_near = _make_gs([_unit("1", 1, [_NEAR])])
    gs_far = _make_gs([_unit("1", 1, [_FAR])])
    with_precheck_near = _charge_field(gs_near, _NEAR)
    with_precheck_far = _charge_field(gs_far, _FAR)
    assert with_precheck_near[1], "prémisse : la figurine proche atteint l'étage"

    calls = _count_multi_source(monkeypatch)
    _force_full_compute(monkeypatch)
    assert _charge_field(gs_near, _NEAR) == with_precheck_near
    assert _charge_field(gs_far, _FAR) == with_precheck_far
    assert calls[0] >= 2


# ─────────────────────────── Borne : niveau de départ ───────────────────────────

def test_bound_uses_height_difference_from_start_level():
    """Une figurine DÉJÀ au niveau 1 visant le niveau 2 ne paie que |h2 − h1|, pas h2."""
    floors = {1: frozenset({(20, 20)}), 2: frozenset({(20, 21)})}
    heights = {0: 0.0, 1: 3.0 * ENGAGEMENT_NORM_HEX_WIDTH, 2: 5.0 * ENGAGEMENT_NORM_HEX_WIDTH}
    # Budget 4 (6 unités-norme) ; voisin sud à ≈ 1,73 unité-norme. Depuis le sol : 7,5 + 1,73 →
    # hors borne ; depuis le niveau 1 : 3,0 + 1,73 → dans la borne.
    budget = 4.0 * ENGAGEMENT_NORM_HEX_WIDTH
    assert gm.multilevel_target_within_straight_bound((20, 20), 0, {2}, floors, heights, budget) is False
    assert gm.multilevel_target_within_straight_bound((20, 20), 1, {2}, floors, heights, budget) is True
    assert gm.multilevel_target_within_straight_bound((20, 20), 0, {0, 2}, floors, heights, budget) is True


# ─────────────────────────── Portails mémoïsés ───────────────────────────

def _count_compute(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    calls = [0]
    real = gm._compute_level_transitions

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(gm, "_compute_level_transitions", counted)
    monkeypatch.setattr(gm, "_LEVEL_TRANSITIONS_CACHE", {})
    return calls


def test_level_transitions_memoized_by_value(monkeypatch: pytest.MonkeyPatch):
    calls = _count_compute(monkeypatch)
    floors_a = {1: frozenset(_FLOOR_HEXES)}
    floors_b = {1: set(_FLOOR_HEXES)}  # entrée égale, objet distinct, non frozen
    heights_a = {0: 0.0, 1: 3.0 * ENGAGEMENT_NORM_HEX_WIDTH}
    heights_b = dict(heights_a)

    first = gm._build_level_transitions(floors_a, heights_a, 60, 60, False)
    second = gm._build_level_transitions(floors_b, heights_b, 60, 60, False)
    assert first, "référence vacante : aucun portail construit"
    assert second is first
    assert calls[0] == 1

    taller = gm._build_level_transitions(floors_a, {0: 0.0, 1: 4.0 * ENGAGEMENT_NORM_HEX_WIDTH}, 60, 60, False)
    assert calls[0] == 2
    assert taller != first
    gm._build_level_transitions(floors_a, heights_a, 60, 60, True)
    assert calls[0] == 3, "ignore_vertical_cost fait partie de la clé"
    gm._build_level_transitions(floors_a, heights_a, 60, 60, False)
    assert calls[0] == 3, "entrée déjà vue : pas de recalcul"
