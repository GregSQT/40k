"""Pile-in 12.03, AFTER MOVING : « Your unit must be engaged » doit juger la position D'ARRIVÉE.

L'entrée-cache synthétique qui porte la position candidate héritait de ``occupied_hexes_by_model``
de l'entrée réelle — les centres par-figurine d'AVANT le mouvement. La métrique d'engagement du jeu
étant euclidienne, ``socle_from_cache_entry`` mesure justement depuis ces centres : le contrôle
répondait donc sur l'état de départ, et déclarait « unité engagée » n'importe quel plan, y compris
un plan qui emmène toute l'escouade à l'autre bout du plateau.

Le contrôle par-figurine (``per_model``) restait juste, ce qui masquait le trou : aucun plan
réellement produit par l'UI ne l'exerçait. Un contrôle qui ne regarde rien affiche « tout va bien ».
"""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.fight_handlers import _fight_pile_in_preview_plan
from tests._state_invariants import turn_state_invariants

SQUAD = [(11, 20), (11, 21)]
ENEMY = (12, 20)
FAR_AWAY = [(3, 3), (3, 4)]


def _model(squad_id: str, col: int, row: int, player: int) -> Dict[str, Any]:
    return {
        "squad_id": squad_id, "col": col, "row": row, "level": 0, "player": player,
        "HP_CUR": 1, "HP_MAX": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "orientation": 0, "MODEL_HEIGHT": 2.5,
    }


def _gs() -> Dict[str, Any]:
    unit1 = {
        "id": 1, "player": 1, "col": SQUAD[0][0], "row": SQUAD[0][1], "MOVE": 6, "HP_CUR": 1,
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [], "MODEL_HEIGHT": 2.5,
        "level": 0, "orientation": 0,
    }
    unit2 = {
        "id": 2, "player": 2, "col": ENEMY[0], "row": ENEMY[1], "MOVE": 6, "HP_CUR": 1,
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [], "MODEL_HEIGHT": 2.5,
        "level": 0, "orientation": 0,
    }
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": _model("1", *SQUAD[0], player=1),
            "1#1": _model("1", *SQUAD[1], player=1),
            "2#0": _model("2", *ENEMY, player=2),
        },
        "squad_models": {"1": ["1#0", "1#1"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": SQUAD[0][0], "row": SQUAD[0][1], "player": 1, "level": 0,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5, "occupied_hexes": set(SQUAD),
                  "occupied_hexes_by_model": {"1#0": SQUAD[0], "1#1": SQUAD[1]},
                  "level_by_model": {"1#0": 0, "1#1": 0}, "floor_height_by_model": {"1#0": 0.0, "1#1": 0.0}},
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
        "phase": "fight", "inches_to_subhex": 1, "current_player": 1, "terrain_areas": [],
    }


def test_a_plan_that_walks_away_is_not_engaged():
    """Escouade projetée à l'autre bout du plateau : elle ne finit engagée avec personne."""
    gs = _gs()
    plan = [(mid, c, r, 0) for mid, (c, r) in zip(gs["squad_models"]["1"], FAR_AWAY)]
    assert _fight_pile_in_preview_plan(gs, "1", plan, ["2"])["unit_engaged"] is False


def test_staying_in_contact_is_engaged():
    """Contre-épreuve : l'escouade laissée au contact de l'ennemi est bien engagée.

    Sans elle, le test précédent passerait aussi avec un contrôle qui répond toujours « non ».
    """
    gs = _gs()
    plan = [(mid, c, r, 0) for mid, (c, r) in zip(gs["squad_models"]["1"], SQUAD)]
    assert _fight_pile_in_preview_plan(gs, "1", plan, ["2"])["unit_engaged"] is True
