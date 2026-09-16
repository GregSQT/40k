"""Champ de montée par-figurine (13.06) — réutilisation du champ euclidien déjà mémoïsé.

En métrique euclidienne, l'érosion du masque calcule d'abord le champ any-angle de plain-pied
de chaque figurine (``_euclidean_move_field_for_model``, mémoïsé dans ``_move_spatial_cache``
sous ``eucl``), puis son champ de montée (``ascent_field_for_model``), dont la passe de niveau 0
est le MÊME Dijkstra. ``ascent_field_for_model`` injecte donc le champ mémoïsé en
``precomputed_start_field`` de ``reachable_multilevel_field`` — UNIQUEMENT s'il est déjà en
cache, jamais calculé pour l'occasion (le pré-check de portée doit continuer d'éviter le calcul
aux figurines loin de tout étage).

Jumeau HEX : ``test_ascent_field_hex_ground.py`` — en métrique hex le sol injecté est le BFS hex
du gym, CALCULÉ sur place (~1 ms) et pas relu d'un cache, et le pré-check change de borne. Ce
fichier ne couvre que la métrique euclidienne.

Trois invariants verrouillés ici :

- ``geodesic_field`` (single-source, index d'obstacles élagué) et ``geodesic_field_multi_source``
  (sans élagage) rendent le MÊME champ pour une source unique, murs et figurine ennemie compris,
  avec et sans contact de socle — c'est ce qui rend le champ mémoïsé substituable à la passe ;
- le champ de montée est IDENTIQUE avec et sans réutilisation, et la réutilisation a bien lieu
  (aucune passe single-source au niveau de départ quand le champ est en cache) ;
- la case de départ n'est jamais un obstacle de sol du champ de montée (miroir de
  ``_euclidean_move_field_for_model`` et du pool par-figurine) : une figurine au contact, dont
  la case est dans la bande d'engagement ennemie, peut monter — avant, le Dijkstra multi-source
  ignorait la source « bloquée » et le champ était vide.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.hex_utils import (
    ENGAGEMENT_NORM_HEX_WIDTH, geodesic_field, geodesic_field_multi_source,
    obstacles_touching_disc, round_base_radius_norm,
)
from engine.phase_handlers import geodesic_move as gm
from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes, build_units_cache
from tests._state_invariants import turn_state_invariants, unit_invariants

_FLOOR_HEXES = [(c, r) for c in range(24, 30) for r in range(16, 26)]
_FLOOR_POLYGON = [[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]]
#: x5 : 5 sous-hexes par pouce ; étage à 1" → 5 sous-hexes de montée (7,5 unités-norme).
_INCHES_TO_SUBHEX = 5
_BUDGET = 30  # sous-hexes (6" à x5)
_START = (18, 20)  # 6 colonnes du plancher
_FAR = (3, 3)  # ~21 colonnes du plancher : hors de tout budget de 30
#: Mur en travers du chemin direct vers l'étage (colonne 21, lignes 17..23), contourné par le haut/bas.
_WALLS = {(21, r) for r in range(17, 24)}


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]],
          shape: str = "round", size: Any = 3) -> Dict[str, Any]:
    col, row = models[0]
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": size, "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": shape, "MOVE": 6, "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "models": [{"col": c, "row": r, "VALUE": 10, "orientation": 0} for c, r in models],
    }


def _make_gs(units: List[Dict[str, Any]], *, thru_ez: bool = True, ez: int = 5) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": ez, "engagement_zone_vertical": 5,
                "max_base_size_hex": 35, "unit_model_cohesion_range": 10,
                "unit_global_cohesion_range": 45, "squad_min_neighbors": 1,
                "cohesion_distance_mode": "euclidean",
            },
            "move": {"can_move_through_enemy_engagement_zone": thru_ez,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 60, "board_rows": 60,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(_WALLS),
        "terrain_areas": [{
            "id": "ruin", "polygon_vertices": _FLOOR_POLYGON, "hexes": _FLOOR_HEXES,
            "floors": [{"level": 1, "height_inches": 1.0, "hexes": _FLOOR_HEXES,
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
    return gs


def _model(gs: Dict[str, Any]) -> Dict[str, Any]:
    return gs["models_cache"]["1#0"]


def _count_start_passes(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    """Passes multi-source SEEDÉES DEPUIS LE DÉPART (une source, distance 0) : c'est la passe
    que la réutilisation doit supprimer. Les passes d'étage (seeds de portail) ne comptent pas."""
    calls = [0]
    real = gm._euclidean_move_field_multi

    def counted(starts: Dict[Tuple[int, int], float], *args: Any, **kwargs: Any) -> Any:
        if len(starts) == 1 and next(iter(starts.values())) == 0.0:
            calls[0] += 1
        return real(starts, *args, **kwargs)

    monkeypatch.setattr(gm, "_euclidean_move_field_multi", counted)
    return calls


def _count_single_source(monkeypatch: pytest.MonkeyPatch) -> List[int]:
    """Champs single-source (``_euclidean_move_field`` → ``geodesic_field``) : le champ de montée
    ne doit JAMAIS en déclencher — il lit le cache, il ne le remplit pas."""
    calls = [0]
    real = gm.geodesic_field

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(gm, "geodesic_field", counted)
    return calls


# ─────────────────── (d) geodesic_field ≡ geodesic_field_multi_source sur source unique ───────────────────

@pytest.mark.parametrize("enemy_cell", [(23, 20), (19, 20)], ids=["ennemi derriere le mur", "ennemi au contact"])
def test_single_source_field_matches_multi_source_with_walls_and_enemy(enemy_cell: Tuple[int, int]):
    radius = round_base_radius_norm(3)
    obstacles = set(_WALLS) | {enemy_cell}
    budget = _BUDGET * ENGAGEMENT_NORM_HEX_WIDTH
    contact = obstacles_touching_disc(obstacles, _START, radius)
    if enemy_cell == (19, 20):
        assert contact == {enemy_cell}, "prémisse : le socle chevauche l'ennemi adjacent"
    else:
        assert not contact

    single = geodesic_field(_START, 60, 60, obstacles, budget, radius, contact_obstacles=contact)
    multi = geodesic_field_multi_source(
        {_START: 0.0}, 60, 60, obstacles, budget, radius,
        contact_obstacles=contact, contact_start=_START,
    )
    assert single, "référence vacante : aucun champ single-source"
    assert single == multi
    # Vacuité : les obstacles ont bien façonné le champ (un mur traversé en ligne droite
    # rendrait le même champ qu'un plateau vide).
    free = geodesic_field(_START, 60, 60, set(), budget, radius)
    assert single != free
    assert all(cell not in single for cell in obstacles)


def test_single_source_field_matches_multi_source_for_oval_base():
    """Socle non rond : clairance nulle, obstacles dilatés par l'empreinte — même primitive."""
    from engine.hex_utils import precompute_footprint_offsets
    off_even, off_odd = precompute_footprint_offsets("oval", [4, 2], 0)
    obstacles = set(_WALLS) | {(23, 20)}
    budget = _BUDGET * ENGAGEMENT_NORM_HEX_WIDTH
    single = gm._euclidean_move_field(_START, "oval", [4, 2], off_even, off_odd, obstacles, 60, 60, budget)
    multi = gm._euclidean_move_field_multi({_START: 0.0}, "oval", [4, 2], off_even, off_odd, obstacles, 60, 60, budget)
    assert single
    assert single == multi


# ─────────────────── Réutilisation : même champ, passe de départ supprimée ───────────────────

def _ascent(gs: Dict[str, Any], budget: int = _BUDGET) -> Dict[Tuple[int, int], int]:
    return dict(su.ascent_field_for_model(gs, "1", 1, _model(gs), 1, budget))


def test_ascent_field_identical_with_and_without_cached_euclidean_field(monkeypatch: pytest.MonkeyPatch):
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])])
    assert su.move_plan_distance_mode(gs, "1") == "euclidean", "prémisse : métrique euclidienne à x5"

    starts = _count_start_passes(monkeypatch)
    singles = _count_single_source(monkeypatch)
    reference = _ascent(gs)
    assert reference, "prémisse : l'étage est atteignable"
    assert starts[0] == 1, "sans champ en cache, la passe de départ est calculée par le champ multi-niveaux"
    assert singles[0] == 0, "le champ de montée ne calcule jamais le champ euclidien lui-même"

    # Même état, cache vierge, puis le champ de plain-pied est mémoïsé AVANT le champ de montée —
    # l'ordre de l'érosion (`erode_move_pool_by_squad_block`).
    gs.pop("_move_spatial_cache")
    flat = su._euclidean_move_field_for_model(gs, "1", 1, _model(gs), 0, _BUDGET)
    assert flat and singles[0] == 1
    starts[0] = 0
    reused = _ascent(gs)
    assert reused == reference
    assert starts[0] == 0, "champ en cache : aucune passe de départ — c'est l'économie attendue"
    assert singles[0] == 1, "et toujours aucun champ euclidien calculé par le champ de montée"


def test_ascent_field_reads_the_cached_field_it_is_given(monkeypatch: pytest.MonkeyPatch):
    """Preuve que l'injection est VIVE : un champ mémoïsé tronqué change le champ de montée.
    (Jamais le cas en production — la clé mémoïse un champ complet — mais c'est ce qui prouve
    que le test précédent ne compare pas deux calculs indépendants.)"""
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(23, 20)])])
    reference = _ascent(gs)
    assert reference

    gs.pop("_move_spatial_cache")
    su._euclidean_move_field_for_model(gs, "1", 1, _model(gs), 0, _BUDGET)
    cache = su._move_spatial_cache(gs)["eucl"]
    (key,) = cache.keys()
    cache[key] = {_START: 0.0}  # champ réduit à la case de départ : aucun portail atteignable
    assert _ascent(gs) == {}


def test_ascent_field_does_not_compute_the_euclidean_field_when_absent(monkeypatch: pytest.MonkeyPatch):
    """Cache-only : figurine loin de tout étage, le pré-check de portée rend un champ vide sans
    aucun Dijkstra, ni multi-niveaux ni euclidien."""
    gs = _make_gs([_unit("1", 1, [_FAR]), _unit("2", 2, [(23, 20)])])
    starts = _count_start_passes(monkeypatch)
    singles = _count_single_source(monkeypatch)
    assert _ascent(gs) == {}
    assert starts[0] == 0 and singles[0] == 0
    assert not su._move_spatial_cache(gs)["eucl"], "rien n'a été mémoïsé côté euclidien"


def test_elevated_start_never_reuses_the_ground_field(monkeypatch: pytest.MonkeyPatch):
    """Départ à l'étage : le champ mémoïsé de niveau 0 ne décrit pas ce trajet — pas de réutilisation,
    même si un champ de plain-pied est en cache pour la même case."""
    upper = [(c, r) for c in range(24, 30) for r in range(30, 40)]
    gs = _make_gs([_unit("1", 1, [(26, 20)]), _unit("2", 2, [(23, 20)])])
    gs["terrain_areas"].append({
        "id": "ruin2", "polygon_vertices": _FLOOR_POLYGON, "hexes": upper,
        "floors": [{"level": 1, "height_inches": 1.0, "hexes": upper, "polygon_vertices": _FLOOR_POLYGON},
                   {"level": 2, "height_inches": 2.0, "hexes": upper, "polygon_vertices": _FLOOR_POLYGON}],
    })
    gs["terrain_areas"][0]["floors"].append(
        {"level": 2, "height_inches": 2.0, "hexes": _FLOOR_HEXES, "polygon_vertices": _FLOOR_POLYGON}
    )
    model = _model(gs)
    model["level"] = 1
    gs["unit_by_id"]["1"]["level"] = 1
    su._euclidean_move_field_for_model(gs, "1", 1, model, 0, _BUDGET)
    starts = _count_start_passes(monkeypatch)
    field = dict(su.ascent_field_for_model(gs, "1", 1, model, 2, _BUDGET))
    assert field, "prémisse : le niveau 2 est atteignable depuis le niveau 1"
    assert starts[0] == 1, "départ en hauteur : la passe de départ est calculée, jamais lue au sol"


# ─────────────────── (b) la case de départ n'est pas un obstacle de sol ───────────────────

def test_model_standing_in_enemy_engagement_band_can_still_climb():
    """Bande d'engagement infranchissable (`can_move_through_enemy_engagement_zone` faux — la config
    livrée la laisse franchissable, donc ce cas ne s'y produit pas) et zone d'un seul hex, pour
    qu'une figurine au contact ait des voisins HORS bande : le champ de plain-pied sort de sa case,
    le champ de montée doit en sortir aussi."""
    gs = _make_gs([_unit("1", 1, [_START]), _unit("2", 2, [(19, 20)], size=1)], thru_ez=False, ez=1)
    transit = su.build_move_transit_blocked(gs, "1", 1, 0)
    assert _START in transit, "prémisse : la case de départ est dans la bande d'engagement ennemie"
    flat = su._euclidean_move_field_for_model(gs, "1", 1, _model(gs), 0, _BUDGET)
    assert len(flat) > 1, "prémisse : le champ de plain-pied sort de la case de départ"

    gs.pop("_move_spatial_cache")
    climb = _ascent(gs)
    assert climb, "la figurine au contact peut monter : sa propre case n'est pas un obstacle"
    assert set(climb) <= set(_FLOOR_HEXES)
