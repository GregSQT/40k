"""Auto-placement de charge (11.04) et étages (§13.06) — le plan doit dire à quelle hauteur il pose.

Deux facettes, exercées sur le même terrain :

1. **Le plan porte son niveau.** L'auto-placement ne produisait que des triplets, en plaçant
   implicitement tout au sol. Les deux consommateurs complètent alors différemment — le commit de
   charge par 0, celui de la consolidation « engaging » par le niveau de VUE — donc l'un ramène au
   sol une arrivée d'étage, l'autre fait monter d'un cran un placement au sol.

2. **Le niveau de départ est facturé.** Le contrôle de légalité par-figurine
   (``_charge_model_pos_is_closer``) reconstruisait son champ d'atteignabilité depuis le SOL : une
   figurine déjà en hauteur payait une montée déjà consentie, et sa descente ne coûtait rien. Le pool
   de l'UI, lui, part du niveau effectif — les deux se contredisaient.

Géométrie : board ×10 — obligatoire ici. À ``inches_to_subhex = 1`` la géométrie est hexagonale
(``geometry_is_hex``), la charge y mesure en hex et n'emprunte jamais le champ multi-niveaux : un test
à cette échelle validerait un chemin de code qui ne s'exécute pas. Plancher de niveau 1 haut de 3" sur
les colonnes 90..130, figurine en (100, 200) dessus, cible au sol en (140, 200) — soit 3" de trajet
horizontal jusqu'au bord du plancher, et 3" de descente à payer en plus.
"""

from __future__ import annotations

from typing import Any, Dict

from engine.phase_handlers.charge_handlers import (
    _charge_model_pos_is_closer,
    charge_autoplace_plan,
)
from tests._state_invariants import turn_state_invariants

FLOOR_HEIGHT_INCHES = 3.0
UPPER_START = (100, 200)
TARGET = (140, 200)
INFANTRY = [{"keywordId": "INFANTRY"}]


def _gs(*, roll: int) -> Dict[str, Any]:
    unit1 = {
        "id": 1, "player": 1, "col": UPPER_START[0], "row": UPPER_START[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": INFANTRY,
        "MODEL_HEIGHT": 2.5, "level": 1, "orientation": 0,
    }
    unit2 = {
        "id": 2, "player": 2, "col": TARGET[0], "row": TARGET[1], "MOVE": 6,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": INFANTRY,
        "MODEL_HEIGHT": 2.5, "level": 0, "orientation": 0,
    }
    floor_hexes = [[c, r] for c in range(90, 131) for r in range(180, 221)]
    floor_polygon = [[90, 180], [130, 180], [130, 220], [90, 220]]
    return {**turn_state_invariants(),
        "models_cache": {
            "1#0": {"col": UPPER_START[0], "row": UPPER_START[1], "level": 1, "player": 1,
                    "squad_id": "1", "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
                    "orientation": 0, "MODEL_HEIGHT": 2.5},
            "2#0": {"col": TARGET[0], "row": TARGET[1], "level": 0, "player": 2,
                    "squad_id": "2", "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
                    "orientation": 0, "MODEL_HEIGHT": 2.5},
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": UPPER_START[0], "row": UPPER_START[1], "player": 1, "level": 1,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5, "occupied_hexes": {UPPER_START},
                  "occupied_hexes_by_model": {"1#0": UPPER_START}, "level_by_model": {"1#0": 1},
                  # Hauteur du plancher sous chaque figurine (pouces) : l'engagement 3D (03.04) la
                  # compare au seuil vertical ; sans elle le moteur refuse de mesurer.
                  "floor_height_by_model": {"1#0": FLOOR_HEIGHT_INCHES}},
            "2": {"col": TARGET[0], "row": TARGET[1], "player": 2, "level": 0,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0, "HP_CUR": 1,
                  "MODEL_HEIGHT": 2.5, "occupied_hexes": {TARGET},
                  "occupied_hexes_by_model": {"2#0": TARGET}, "level_by_model": {"2#0": 0},
                  "floor_height_by_model": {"2#0": 0.0}},
        },
        "units": [unit1, unit2],
        "unit_by_id": {"1": unit1, "2": unit2},
        "board_cols": 440, "board_rows": 600,
        "wall_hexes": set(),
        "config": {
            # ``engagement_zone_vertical`` : seuil vertical de l'engagement 3D (03.04), en POUCES,
            # valeur réelle du jeu — un seuil de test divergeant validerait la mauvaise géométrie.
            "game_rules": {"engagement_zone": 2, "engagement_zone_vertical": 5,
                           "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                           "cohesion_distance_mode": "euclidean", "squad_min_neighbors": 1},
        },
        "phase": "charge",
        "inches_to_subhex": 10,
        "current_player": 1,
        "units_took_to_skies": set(),
        "charge_target_selections": {"1": ["2"]},
        "charge_roll_values": {"1": roll},
        "terrain_areas": [
            {"floors": [{"level": 1, "height_inches": FLOOR_HEIGHT_INCHES,
                         "hexes": floor_hexes, "polygon_vertices": floor_polygon}]},
        ],
    }


def test_the_plan_states_the_level_of_each_placement():
    """Chaque entrée du plan porte un niveau explicite, jamais laissé à deviner au consommateur."""
    plan = charge_autoplace_plan(_gs(roll=12), "1", mode="offensive")["plan"]
    assert plan, "aucun placement produit"
    for entry in plan:
        assert len(entry) == 4, f"entrée sans niveau : {entry}"
        assert entry[3] in (0, 1), entry


def test_the_placement_is_legal_for_the_validator():
    """Le placement produit passe le contrôle par-figurine — au niveau que le plan annonce.

    C'est l'invariant qui manquait : un auto-placement dont le commit refuse le résultat laisse
    l'unité bloquée, exactement comme le pile-in le faisait sur une escouade à cheval sur deux étages.
    """
    gs = _gs(roll=12)
    plan = charge_autoplace_plan(gs, "1", mode="offensive")["plan"]
    for mid, col, row, level in plan:
        assert _charge_model_pos_is_closer(
            gs, gs["unit_by_id"]["1"], str(mid), int(col), int(row), ["2"], 120,
            provisional_plan={}, dest_level=int(level),
        ), f"{mid} placé en ({col},{row},lvl{level}) — refusé par le contrôle de légalité"


def test_the_descent_is_charged_against_the_roll():
    """Verrou du niveau de départ : la descente (3") se paie, donc un petit jet ne suffit plus.

    La case (130, 200) est au sol, à 3" du départ ; la descente en coûte 3 de plus, donc il faut 6"
    de budget. Mesuré depuis le sol — l'erreur corrigée — 3" auraient suffi.
    """
    gs_small = _gs(roll=3)
    assert not _charge_model_pos_is_closer(
        gs_small, gs_small["unit_by_id"]["1"], "1#0", 130, 200, ["2"], 30,
        provisional_plan={}, dest_level=0,
    )
    gs_big = _gs(roll=6)
    assert _charge_model_pos_is_closer(
        gs_big, gs_big["unit_by_id"]["1"], "1#0", 130, 200, ["2"], 60,
        provisional_plan={}, dest_level=0,
    )
