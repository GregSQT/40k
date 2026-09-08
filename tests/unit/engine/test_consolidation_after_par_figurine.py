"""Consolidation 12.08 AFTER (Ongoing) : la clause s'applique PAR FIGURINE, pas par unité.

« Each model that started engaged must still be engaged with THAT enemy unit. » Le préview de
consolidation (`_fight_consolidation_preview_plan`, mode ``ongoing``) rend DEUX verdicts qu'il
ne faut pas confondre :

  - ``unit_engaged`` — membre PAR UNITÉ : vrai dès qu'UNE figurine quelconque touche un ennemi ;
  - ``kept_engagements`` — membre PAR FIGURINE : faux dès qu'une figurine qui partait engagée
    avec une unité ennemie ne l'est plus avec CETTE unité à l'arrivée.

Sans ce fichier, seul le premier était couvert : un plan où la figurine qui tenait l'engagement
le perd pendant qu'une autre en gagne un passait tous les tests, alors que la règle l'interdit.

JUMEAU — ce fichier est le miroir strict de la paire ajoutée dans
``test_pile_in_after_unit_engaged.py`` pour le pile-in (12.03). Les deux boucles sont le même
contrôle écrit deux fois dans ``fight_handlers`` ; les couvrir séparément est délibéré : c'est
exactement le genre de moitié qu'une correction sur l'une laisse tomber sur l'autre.

CONTRE-ÉPREUVE OBLIGATOIRE — dans les deux scénarios ci-dessous ``unit_engaged`` vaut True.
Seul ``kept_engagements`` bascule. Un test qui ne le vérifierait que dans un sens passerait aussi
avec un contrôle qui répond toujours « non ».

Géométrie MESURÉE (ez=1, métrique hex, ennemi en (12,20)) — cases engagées : (11,19), (11,20),
(12,19), (12,20), (12,21), (13,19), (13,20). Donc 1#0 part ENGAGÉ de (11,20) et 1#1 part LIBRE
de (11,21). L'état de jeu est celui de ``test_pile_in_after_unit_engaged`` : même plateau, mêmes
socles, ce qui rend les deux fichiers directement comparables.
"""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.fight_handlers import _fight_consolidation_preview_plan
from tests._state_invariants import turn_state_invariants, unit_invariants

SQUAD = [(11, 20), (11, 21)]
ENEMY = (12, 20)

ENGAGED_START = (11, 20)   # 1#0 y est engagé avec l'ennemi
FREE_CELL = (11, 21)       # 1#1 y est libre — et 1#0 y perdrait son engagement
ENGAGED_OTHER = (12, 21)   # autre case engagée, où 1#1 peut en gagner un


def _model(squad_id: str, col: int, row: int, player: int) -> Dict[str, Any]:
    return {
        "squad_id": squad_id, "col": col, "row": row, "level": 0, "player": player,
        "HP_CUR": 1, "HP_MAX": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "orientation": 0, "MODEL_HEIGHT": 2.5,
    }


def _gs() -> Dict[str, Any]:
    unit1 = {**unit_invariants(),
        "id": 1, "player": 1, "col": SQUAD[0][0], "row": SQUAD[0][1], "MOVE": 6, "HP_CUR": 1,
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [], "MODEL_HEIGHT": 2.5,
        "level": 0, "orientation": 0,
    }
    unit2 = {**unit_invariants(),
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
                  "level_by_model": {"1#0": 0, "1#1": 0},
                  "floor_height_by_model": {"1#0": 0.0, "1#1": 0.0}},
            "2": {"col": ENEMY[0], "row": ENEMY[1], "player": 2, "level": 0,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5, "occupied_hexes": {ENEMY},
                  "occupied_hexes_by_model": {"2#0": ENEMY}, "level_by_model": {"2#0": 0},
                  "floor_height_by_model": {"2#0": 0.0}},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(),
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5,
                           "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1,
                           "pile_in_target_range": 5},
        },
        "phase": "fight", "inches_to_subhex": 1, "current_player": 1, "terrain_areas": [],
    }


def _preview(gs: Dict[str, Any], plan) -> Dict[str, Any]:
    return _fight_consolidation_preview_plan(
        gs, "1", plan, mode="ongoing", tier_kind="enemy", tier=["2"],
        closest_tier_ids=["2"], lock_base_contact=True,
    )


def test_a_model_that_started_engaged_may_not_break_off():
    """La figurine qui partait engagée perd son ennemi, une autre en gagne un : REFUSÉ.

    Cas discriminant : l'escouade reste engagée, donc un contrôle par-unité validerait ce plan.
    """
    out = _preview(_gs(), [("1#0", *FREE_CELL, 0), ("1#1", *ENGAGED_OTHER, 0)])
    assert out["unit_engaged"] is True, "précondition : le membre par-unité reste satisfait"
    assert out["kept_engagements"] is False
    assert out["can_validate"] is False


def test_keeping_the_starting_engagement_is_accepted():
    """Contre-épreuve : 1#0 conserve son engagement, 1#1 en gagne un — ACCEPTÉ."""
    out = _preview(_gs(), [("1#0", *ENGAGED_START, 0), ("1#1", *ENGAGED_OTHER, 0)])
    assert out["unit_engaged"] is True
    assert out["kept_engagements"] is True
    assert out["can_validate"] is True
