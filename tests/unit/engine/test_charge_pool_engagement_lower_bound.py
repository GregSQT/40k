"""Verrou : la prune O(1) de `charge_build_valid_destinations_pool` majore le prédicat qu'elle
prétend majorer, dans LES DEUX géométries.

`_charge_impossible_by_primary_to_enemy_hex_lower_bound` déclare une charge impossible sans
lancer le BFS. Une borne trop ÉTROITE y vide `valid_charge_destinations_pool` sur une charge
LÉGALE, et le verdict vide est ensuite mémoïsé pour le step : l'action charge n'est jamais
proposée, ni au modèle ni au joueur. Rien ne crashe, rien ne le signale.

La borne s'écrivait `ez + rayon d'empreinte DISCRET du chargeur`, alors qu'à x5 le prédicat
(`unit_entries_within_engagement_zone`, métrique `euclidean`) soustrait les rayons CONTINUS des
socles — un subhex de plus PAR SOCLE. Mesuré le 2026-09-19 sur les socles réels du dépôt, à
ez = 10 : 126 configurations où l'engagement porte un hex plus loin que la borne. Deux familles,
une par test ci-dessous :

- chargeur OVAL aux orientations impaires (WarTrakk, Land Speeder — `config/armies/
  armageddon_orks.json`, roster Armageddon SM), dont le rayon d'empreinte tombe à 9 quand
  l'engagement porte à 20 ;
- chargeur ROND face à des ennemis TOUS ovales, cas que le garde-fou `round↔round` (supprimé
  avec la borne qui le motivait) ne couvrait pas.

Les deux fixtures sont posées sur l'axe des COLONNES : c'est là que le pas hexagonal coûte le
moins (1,5 unité `_hex_center`), donc là que la distance hex d'engagement est maximale et que
l'écart entre les deux géométries se lit sans ambiguïté.

Les tests de refus vérifient l'autre moitié du contrat : une borne qui ne prune plus rien serait
verte ici sans rien prouver.
"""

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from engine.hex_utils import compute_occupied_hexes, hex_distance
from engine.phase_handlers.charge_handlers import (
    _charge_impossible_by_primary_to_enemy_hex_lower_bound,
    charge_build_valid_destinations_pool,
)
from engine.phase_handlers.shared_utils import (
    _charge_engage_reach,
    build_units_cache,
    get_engagement_zone,
)
from engine.spatial_relations import (
    engagement_distance_metric,
    entry_footprint,
    unit_entries_within_engagement_zone,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

ISH = 5
#: `engagement_zone` est lu DÉJÀ converti en subhex (2" x ISH), comme w40k_core le pré-scale.
EZ_SUBHEX = 2 * ISH
ENEMY = (160, 80)
#: Jet de charge en subhex (6" x ISH). Il fixe `bfs_max_distance` : sans cible déclarée, la borne
#: BFS EST le jet (`_charge_bfs_max_distance`).
ROLL_SUBHEX = 30


def _unit(
    uid: int,
    player: int,
    col: int,
    row: int,
    base_shape: str,
    base_size: Any,
    orientation: int = 0,
    models: Optional[List[Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    unit: Dict[str, Any] = {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models) if models else 4, "HP_MAX": len(models) if models else 4,
        "VALUE": 100, "OC": 1, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SHAPE": base_shape, "BASE_SIZE": base_size, "orientation": orientation,
        "MODEL_HEIGHT": 2.5, "MOVE": 6, "UNIT_RULES": [], "UNIT_KEYWORDS": [], "level": 0,
    }
    if models:
        unit["models"] = [
            {"col": c, "row": r, "VALUE": 100, "HP_MAX": 1, "HP_CUR": 1} for c, r in models
        ]
    return unit


def _gs(units: List[Dict[str, Any]], ish: int, ez_subhex: int) -> Dict[str, Any]:
    gs: Dict[str, Any] = {**turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": ez_subhex,
                "engagement_zone_vertical": 5,
                "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2 * ish,
                "unit_global_cohesion_range": 9 * ish,
                "cohesion_distance_mode": "euclidean",
                "squad_min_neighbors": 1,
            },
            "charge": {"charge_max_distance": 12 * ish},
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 200, "board_rows": 160,
        "current_player": 1,
        "phase": "charge",
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "units_charged": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_advanced": set(),
        "console_logs": [],
        "_unit_move_version": 0,
        "gym_training_mode": True,
        "inches_to_subhex": ish,
    }
    build_units_cache(gs)
    return gs


def _indexed(gs: Dict[str, Any], enemy_ids: Sequence[str]) -> List[Tuple[Any, Dict[str, Any]]]:
    return [(eid, gs["units_cache"][eid]) for eid in enemy_ids]


def _prune(gs: Dict[str, Any], unit_id: str, enemy_ids: Sequence[str], roll: int) -> bool:
    entry = gs["units_cache"][unit_id]
    return _charge_impossible_by_primary_to_enemy_hex_lower_bound(
        gs,
        unit_id_str=unit_id,
        start_col=int(entry["col"]),
        start_row=int(entry["row"]),
        indexed_enemy_engagement=_indexed(gs, enemy_ids),
        bfs_max_distance=roll,
    )


def _footprint_bound_verdict(
    gs: Dict[str, Any], unit_id: str, enemy_ids: Sequence[str], roll: int
) -> bool:
    """Verdict de l'ANCIENNE borne : `m > D + rayon d'empreinte discret + ez`, `m` mesuré aux
    cases d'empreinte ennemies. Recopiée ici — et non importée — pour que ces tests restent la
    description du défaut le jour où elle disparaît du moteur."""
    entry = gs["units_cache"][unit_id]
    start = (int(entry["col"]), int(entry["row"]))
    s_charger = max(
        hex_distance(start[0], start[1], int(c), int(r)) for c, r in entry_footprint(entry)
    )
    m = min(
        hex_distance(start[0], start[1], int(c), int(r))
        for eid in enemy_ids
        for c, r in entry_footprint(gs["units_cache"][eid])
    )
    return m > roll + s_charger + int(get_engagement_zone(gs))


def _engaging_anchors(
    gs: Dict[str, Any], unit_id: str, enemy_id: str, budget: int
) -> Set[Tuple[int, int]]:
    """Ancres, dans le budget, d'où l'escouade finit engagée — mesuré par le CONTRAT (03.04) et
    non par le prédicat de trajet du pool. L'entrée candidate est construite comme le pool la
    construit : un socle unique à l'ancre (cf. `_charge_synthetic_charger_cache_entry`)."""
    entry = gs["units_cache"][unit_id]
    start = (int(entry["col"]), int(entry["row"]))
    enemy_entry = gs["units_cache"][enemy_id]
    ez = get_engagement_zone(gs)
    out: Set[Tuple[int, int]] = set()
    for col in range(start[0] - budget, start[0] + budget + 1):
        for row in range(start[1] - budget, start[1] + budget + 1):
            if hex_distance(start[0], start[1], col, row) > budget:
                continue
            candidate = {
                **entry, "col": col, "row": row,
                "occupied_hexes": set(compute_occupied_hexes(
                    col, row, entry["BASE_SHAPE"], entry["BASE_SIZE"],
                    int(entry["orientation"]),
                )),
            }
            candidate.pop("occupied_hexes_by_model", None)
            candidate.pop("floor_height_by_model", None)
            if unit_entries_within_engagement_zone(candidate, enemy_entry, ez):
                out.add((col, row))
    return out


# ── Garde de configuration (motif §0.11) ───────────────────────────────────────

def test_the_fixture_really_measures_engagement_in_the_euclidean_metric():
    """Sans cette garde, tout ce fichier pourrait tourner en métrique `hex` et ne rien prouver :
    c'est précisément l'écart hex/euclidien qui est en cause."""
    gs = _gs([
        _unit(1, 1, 108, 80, "oval", [20, 14], orientation=1),
        _unit(2, 2, ENEMY[0], ENEMY[1], "round", 6),
    ], ISH, EZ_SUBHEX)
    assert engagement_distance_metric(gs) == "euclidean"
    assert int(get_engagement_zone(gs)) == EZ_SUBHEX


# ── Défaut n°1 : chargeur OVAL ─────────────────────────────────────────────────

def test_oval_charger_keeps_the_charge_the_footprint_bound_refused():
    """WarTrakk (oval `[20,14]` à x5) orientation 1, rayon d'empreinte 9, engagement à 20."""
    gs = _gs([
        _unit(1, 1, 108, 80, "oval", [20, 14], orientation=1),
        _unit(2, 2, ENEMY[0], ENEMY[1], "round", 6),
    ], ISH, EZ_SUBHEX)

    engaging = _engaging_anchors(gs, "1", "2", ROLL_SUBHEX)
    assert engaging, "prémisse cassée : aucune ancre engageante dans le budget"
    assert _footprint_bound_verdict(gs, "1", ["2"], ROLL_SUBHEX), (
        "prémisse cassée : l'ancienne borne ne refusait pas cette charge, le test ne "
        "distinguerait plus les deux bornes"
    )

    assert not _prune(gs, "1", ["2"], ROLL_SUBHEX)
    pool = charge_build_valid_destinations_pool(gs, "1", ROLL_SUBHEX)
    assert pool, "charge légale refusée par la prune"
    assert set(pool) & engaging, (
        "le pool ne contient aucune ancre réellement engageante : il ne prouverait pas 11.04"
    )


# ── Défaut n°2 : chargeur ROND face à des ennemis tous OVALES ──────────────────

def test_round_charger_keeps_its_charge_against_an_oval_only_enemy():
    """Aucun ennemi rond indexé : le garde-fou `round↔round` ne mordait pas, la borne non plus."""
    gs = _gs([
        _unit(1, 1, 110, 80, "round", 6),
        _unit(2, 2, ENEMY[0], ENEMY[1], "oval", [20, 14], orientation=3),
    ], ISH, EZ_SUBHEX)

    engaging = _engaging_anchors(gs, "1", "2", ROLL_SUBHEX)
    assert engaging, "prémisse cassée : aucune ancre engageante dans le budget"
    assert _footprint_bound_verdict(gs, "1", ["2"], ROLL_SUBHEX), (
        "prémisse cassée : l'ancienne borne ne refusait pas cette charge"
    )

    assert not _prune(gs, "1", ["2"], ROLL_SUBHEX)
    pool = charge_build_valid_destinations_pool(gs, "1", ROLL_SUBHEX)
    assert pool, "charge légale refusée par la prune"
    assert set(pool) & engaging


# ── L'autre moitié du contrat : la borne doit encore refuser ───────────────────

def test_the_bound_still_refuses_a_charge_that_no_anchor_can_reach():
    """Une borne qui ne prune plus rien passerait les deux tests ci-dessus sans rien prouver."""
    gs = _gs([
        _unit(1, 1, 60, 80, "oval", [20, 14], orientation=1),
        _unit(2, 2, ENEMY[0], ENEMY[1], "round", 6),
    ], ISH, EZ_SUBHEX)

    assert not _engaging_anchors(gs, "1", "2", ROLL_SUBHEX), (
        "prémisse cassée : une ancre engageante existe, la prune DOIT laisser passer"
    )
    assert _prune(gs, "1", ["2"], ROLL_SUBHEX)
    assert charge_build_valid_destinations_pool(gs, "1", ROLL_SUBHEX) == []


def test_a_round_versus_round_pair_is_pruned_now_that_the_skip_is_gone():
    """Le garde-fou désactivait la prune pour rond↔rond, soit le cas le plus fréquent du jeu :
    ces charges-là repartaient TOUJOURS sur le BFS complet. La borne étant désormais écrite dans
    la métrique du prédicat, elle s'y applique — et elle doit rester juste."""
    gs = _gs([
        _unit(1, 1, 60, 80, "round", 6),
        _unit(2, 2, ENEMY[0], ENEMY[1], "round", 6),
    ], ISH, EZ_SUBHEX)

    assert not _engaging_anchors(gs, "1", "2", ROLL_SUBHEX)
    assert _prune(gs, "1", ["2"], ROLL_SUBHEX)


def test_the_bound_is_never_narrower_than_the_engagement_it_bounds():
    """Contrat de `_charge_engage_reach` lu sur la fixture : toute ancre engageante est à
    `reach` hex au plus d'une POSITION DE FIGURINE ennemie. C'est l'invariant exact dont la
    prune se sert ; le mesurer ici le rend faux dès qu'une borne repart en empreinte discrète."""
    gs = _gs([
        _unit(1, 1, 108, 80, "oval", [20, 14], orientation=1),
        _unit(2, 2, ENEMY[0], ENEMY[1], "round", 6),
    ], ISH, EZ_SUBHEX)
    charger = gs["units_cache"]["1"]
    enemy = gs["units_cache"]["2"]
    positions = [(int(c), int(r)) for c, r in enemy["occupied_hexes_by_model"].values()]
    reach = _charge_engage_reach(
        gs, "1", [charger], [enemy], positions, int(get_engagement_zone(gs))
    )
    for col, row in _engaging_anchors(gs, "1", "2", ROLL_SUBHEX):
        assert min(hex_distance(col, row, c, r) for c, r in positions) <= reach


# ── x1 : la borne ne doit plus payer l'étalement de l'escouade ─────────────────

def test_x1_bound_ignores_the_squad_spread_the_predicate_never_sees():
    """À x1 le pool teste UNE case à l'ancre (`_compute_unit_occupied_hexes`), jamais l'union de
    l'escouade. L'ancienne borne lisait pourtant `occupied_hexes`, qui à cette résolution EST
    l'étalement des figurines : elle accordait à la charge une portée que le prédicat ne lui
    donne pas. Le resserrement doit prendre, sans jamais refuser une charge atteignable."""
    ez_x1 = 2
    spread = [(20, 40), (20, 44), (20, 48)]
    gs = _gs([
        _unit(1, 1, spread[0][0], spread[0][1], "round", 1, models=spread),
        _unit(2, 2, 40, 40, "round", 1),
    ], 1, ez_x1)
    roll = 12

    assert int(get_engagement_zone(gs)) == ez_x1
    charger = gs["units_cache"]["1"]
    s_charger = max(
        hex_distance(spread[0][0], spread[0][1], c, r) for c, r in entry_footprint(charger)
    )
    assert s_charger > 0, "prémisse cassée : l'escouade n'est pas étalée, rien à resserrer"
    assert not _footprint_bound_verdict(gs, "1", ["2"], roll), (
        "prémisse cassée : l'ancienne borne refusait déjà cette charge"
    )
    assert not _engaging_anchors(gs, "1", "2", roll), (
        "prémisse cassée : une ancre engageante existe, la prune DOIT laisser passer"
    )
    assert _prune(gs, "1", ["2"], roll)


def test_x1_bound_still_lets_a_reachable_charge_through():
    """Contre-épreuve du resserrement ci-dessus, même escouade, cible à portée."""
    ez_x1 = 2
    spread = [(20, 40), (20, 44), (20, 48)]
    gs = _gs([
        _unit(1, 1, spread[0][0], spread[0][1], "round", 1, models=spread),
        _unit(2, 2, 33, 40, "round", 1),
    ], 1, ez_x1)
    roll = 12

    assert _engaging_anchors(gs, "1", "2", roll), "prémisse cassée : charge hors d'atteinte"
    assert not _prune(gs, "1", ["2"], roll)
