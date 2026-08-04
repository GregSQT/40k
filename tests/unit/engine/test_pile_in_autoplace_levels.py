"""Auto-placement du pile-in (12.03) sur une escouade à cheval sur deux étages (§13.06).

Le plan d'auto-placement est consommé par ``commit_pile_in_plan``, qui donne à toute entrée
sans niveau le niveau de VUE (``_prov_from_action``). Un plan muet sur les étages a donc deux
effets, tous deux faux :

1. la validation recalcule le pool des figurines d'étage AU SOL — elles n'y sont pas, le commit
   est refusé et l'escouade reste indéfiniment dans le pool de pile-in ;
2. si les cases proposées se trouvent être légales au sol, le commit les accepte et fait
   DESCENDRE les figurines d'un étage, sans coût de descente ni contrôle de plancher.

Géométrie : ``inches_to_subhex = 1``, EZ = 1, budget pile-in = 3. Un plancher de niveau 1
(hauteur 3") couvre les colonnes 9..13 ; l'ennemi est au sol en (14, 20), hors plancher. Les
deux figurines visent la même colonne d'arrivée : l'une au sol, l'autre sur le plancher —
superposition inter-étage, légale, que seule une géométrie par niveau autorise.
"""

from __future__ import annotations

from typing import Any, Dict, List

from engine.phase_handlers.fight_handlers import (
    _fight_pile_in_closest_tier_ids,
    _fight_pile_in_preview_plan,
    pile_in_autoplace_plan,
)
from tests._state_invariants import turn_state_invariants, unit_invariants

FLOOR_HEIGHT_INCHES = 3.0
GROUND_START = (11, 20)
UPPER_START = (10, 20)
ENEMY = (14, 20)
INFANTRY = [{"keywordId": "INFANTRY"}]


def _model(squad_id: str, col: int, row: int, player: int, level: int) -> Dict[str, Any]:
    return {
        "squad_id": squad_id, "col": col, "row": row, "level": level, "player": player,
        "HP_CUR": 1, "HP_MAX": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "orientation": 0, "MODEL_HEIGHT": 2.5,
    }


def _gs() -> Dict[str, Any]:
    unit1 = {**unit_invariants(),
        "id": 1, "player": 1, "col": GROUND_START[0], "row": GROUND_START[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": INFANTRY,
        "MODEL_HEIGHT": 2.5, "level": 0, "orientation": 0,
    }
    unit2 = {**unit_invariants(),
        "id": 2, "player": 2, "col": ENEMY[0], "row": ENEMY[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": INFANTRY,
        "MODEL_HEIGHT": 2.5, "level": 0, "orientation": 0,
    }
    # Le plancher est décrit des DEUX façons que lit le moteur : par hexes (méthode hex) et par
    # polygone (confinement euclidien des socles ronds, 13.06) — les deux doivent coïncider.
    floor_hexes = [[c, r] for c in range(9, 14) for r in range(18, 23)]
    floor_polygon = [[9, 18], [13, 18], [13, 22], [9, 22]]
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": _model("1", *GROUND_START, player=1, level=0),
            "1#1": _model("1", *UPPER_START, player=1, level=1),
            "2#0": _model("2", *ENEMY, player=2, level=0),
        },
        "squad_models": {"1": ["1#0", "1#1"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": GROUND_START[0], "row": GROUND_START[1], "player": 1, "level": 0,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5,
                  "occupied_hexes": {GROUND_START, UPPER_START},
                  "occupied_hexes_by_model": {"1#0": GROUND_START, "1#1": UPPER_START},
                  # HAUTEUR et NIVEAU vont ensemble : `1#1` est à l'étage 1, donc à
                  # FLOOR_HEIGHT_INCHES du sol — c'est la hauteur, pas le niveau, que compare le
                  # gate vertical de l'engagement (§03.04).
                  "level_by_model": {"1#0": 0, "1#1": 1},
                  "floor_height_by_model": {"1#0": 0.0, "1#1": FLOOR_HEIGHT_INCHES}},
            "2": {"col": ENEMY[0], "row": ENEMY[1], "player": 2, "level": 0,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5, "occupied_hexes": {ENEMY},
                  "occupied_hexes_by_model": {"2#0": ENEMY}, "level_by_model": {"2#0": 0}, "floor_height_by_model": {"2#0": 0.0}},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "unit_model_cohesion_range": 2,
                           "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1,
                           "pile_in_target_range": 5},
        },
        "phase": "fight",
        "inches_to_subhex": 1,
        "current_player": 1,
        "terrain_areas": [
            {"floors": [{"level": 1, "height_inches": FLOOR_HEIGHT_INCHES,
                         "hexes": floor_hexes, "polygon_vertices": floor_polygon}]},
        ],
    }


def _plan_of(gs: Dict[str, Any]) -> List[List[Any]]:
    return pile_in_autoplace_plan(gs, "1", "2", mode="offensive")["plan"]


def test_the_plan_states_the_floor_each_figurine_ends_on():
    """Chaque entrée porte le niveau EFFECTIF de sa figurine — celle de l'étage y reste."""
    plan = _plan_of(_gs())
    levels = {str(e[0]): e[3] for e in plan}
    assert all(len(e) == 4 for e in plan), f"entrées sans niveau : {plan}"
    assert levels == {"1#0": 0, "1#1": 1}, levels


def test_both_figurines_close_in_on_their_own_floor():
    """Les deux figurines se rapprochent, chacune sur son plancher, jusqu'à la même colonne.

    Superposition inter-étage (§13.06) : la figurine du sol et celle de l'étage peuvent finir
    l'une au-dessus de l'autre. Une géométrie à plat les mettrait en conflit et en bloquerait une.
    """
    gs = _gs()
    plan = _plan_of(gs)
    pos = {str(e[0]): (int(e[1]), int(e[2])) for e in plan}
    assert pos["1#0"] != GROUND_START, "la figurine du sol n'a pas pilé"
    assert pos["1#1"] != UPPER_START, "la figurine de l'étage n'a pas pilé"
    for mid, (col, _row) in pos.items():
        assert col <= 13, f"{mid} sort du plancher / dépasse l'ennemi : {pos[mid]}"


def test_the_plan_is_accepted_only_because_it_carries_its_levels():
    """Verrou : le MÊME plan, aplati au niveau de vue (0), est refusé par la validation.

    C'est exactement ce que produisait un plan à trois éléments : ``commit_pile_in_plan``
    complétait au niveau de vue, et la figurine d'étage se voyait évaluée au sol — où sa
    destination est hors budget, la descente (3") consommant tout le pile-in.
    """
    gs = _gs()
    plan = _plan_of(gs)
    closest = _fight_pile_in_closest_tier_ids(gs, gs["unit_by_id"]["1"], ["2"])

    with_levels = [(str(e[0]), int(e[1]), int(e[2]), int(e[3])) for e in plan]
    assert _fight_pile_in_preview_plan(gs, "1", with_levels, closest)["can_validate"] is True

    flattened = [(mid, c, r, 0) for mid, c, r, _lv in with_levels]
    checked = _fight_pile_in_preview_plan(gs, "1", flattened, closest)
    assert checked["can_validate"] is False
    assert checked["per_model"]["1#1"] is False, checked["per_model"]
