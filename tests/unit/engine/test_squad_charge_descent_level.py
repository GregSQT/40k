"""Charge depuis un étage — mêmes facettes que §0.34, reproduites sur la CHARGE.

Une charge est un move (11.04 EFFECT « moves as described in Moving (03) ») :

1. **Budget** — la distance verticale descendue s'ajoute au jet (13.06 Moving Vertically).
   `charge_build_valid_plan` mesurait le budget au jet BRUT : une escouade à l'étage chargeait
   comme si la descente était gratuite.
2. **Niveau de destination** — le plan n'émettait que des 3-uplets, et « pas de niveau »
   signifie pour `commit_move` « garder le niveau courant » : une figurine partie de l'étage
   restait marquée à l'étage sur une case de sol sans plancher → `floor_height_at` levait à la
   mise à jour du cache (facette n°2 de §0.34, restée ouverte sur la charge).

Géométrie : `inches_to_subhex = 1`, figurine sur un plancher de niveau 1 haut de 3" →
descente = 3 subhex. Ennemi à 4 hexes : le B2B le plus proche est à 3 hexes.
"""

from typing import Any, Dict

from engine.phase_handlers.shared_utils import (
    SQUAD_RIGID_MOVE_DESTINATION_LEVEL,
    charge_build_valid_plan,
)
from tests._state_invariants import turn_state_invariants

FLOOR_HEIGHT_INCHES = 3.0
START = (10, 20)
ENEMY = (14, 20)


def _gs(*, level: int) -> Dict[str, Any]:
    """`game_state` minimal pour le plan de charge : chargeur (squad 1), cible (squad 2)."""
    unit1 = {
        "id": 1, "player": 1, "col": START[0], "row": START[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
        "level": level,
    }
    unit2 = {
        "id": 2, "player": 2, "col": ENEMY[0], "row": ENEMY[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
        "level": 0,
    }
    floor_hexes = [[START[0] + dc, START[1] + dr] for dc in (-1, 0, 1) for dr in (-1, 0, 1)]
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": START[0], "row": START[1], "level": level, "player": 1,
                    "squad_id": "1", "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
                    "orientation": 0},
            "2#0": {"col": ENEMY[0], "row": ENEMY[1], "level": 0, "player": 2,
                    "squad_id": "2", "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
                    "orientation": 0},
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": START[0], "row": START[1], "player": 1,
                  "occupied_hexes": {START}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "2": {"col": ENEMY[0], "row": ENEMY[1], "player": 2,
                  "occupied_hexes": {ENEMY}, "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1, "unit_model_cohesion_range": 2,
                           "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
        },
        "phase": "charge",
        "gym_training_mode": True,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "current_player": 1,
        "terrain_areas": [
            {"floors": [{"level": 1, "height_inches": FLOOR_HEIGHT_INCHES,
                         "hexes": floor_hexes}]},
        ],
    }


def test_descent_is_deducted_from_the_charge_roll():
    """13.06 : le jet qui suffit AU SOL ne suffit plus depuis l'étage (descente = 3 subhex).

    B2B le plus proche à 3 hexes : jet 4 → budget sol 4 (charge OK), budget étage 4-3=1
    (aucun B2B atteignable, aucune cellule engagée) → None.
    """
    assert charge_build_valid_plan(_gs(level=0), "1", ["2"], 4) is not None
    assert charge_build_valid_plan(_gs(level=1), "1", ["2"], 4) is None


def test_descending_charge_still_possible_with_a_big_enough_roll():
    """Contre-épreuve : jet 6 → budget étage 3, le B2B à 3 hexes redevient atteignable."""
    assert charge_build_valid_plan(_gs(level=1), "1", ["2"], 6) is not None


def test_charge_plan_lands_on_the_ground_level():
    """Le plan PORTE le niveau d'arrivée (sol). Sans lui, `commit_move` garde le niveau
    d'origine et la figurine restait marquée à l'étage hors empreinte de plancher —
    `floor_height_at` levait à la mise à jour du cache."""
    plan = charge_build_valid_plan(_gs(level=1), "1", ["2"], 6)
    assert plan is not None
    for entry in plan:
        assert len(entry) == 4 and entry[3] == SQUAD_RIGID_MOVE_DESTINATION_LEVEL


def test_ground_charge_is_unchanged():
    """Contre-épreuve : au sol, la descente vaut 0 — aucun changement de budget, et le plan
    porte le même niveau d'arrivée (sol) que le move rigide."""
    plan = charge_build_valid_plan(_gs(level=0), "1", ["2"], 3)
    assert plan is not None
    assert all(entry[3] == SQUAD_RIGID_MOVE_DESTINATION_LEVEL for entry in plan)
