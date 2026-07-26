"""Endless duty : le remplacement des unités d'UN joueur ne réécrit pas la référence de l'autre.

`value_at_start` (VALUE totale de départ par joueur) est la référence de la « force d'usure »
observée par l'agent (V11 §9.8). Elle est capturée par `build_units_cache`, que
`_replace_units_for_player` rappelle à chaque vague — pour LES DEUX joueurs.

Sans correctif, remplacer les unités du joueur 2 remettait aussi la référence du joueur 1 à sa
valeur *courante* : ses pertes déjà subies disparaissaient de l'observation (ratio d'usure
revenant à 1.0 sans qu'il ait rien regagné). Ce test est la contre-épreuve.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from engine.phase_handlers.shared_utils import build_units_cache, destroy_model
from services.endless_duty_runtime import _replace_units_for_player

_GAME_RULES = {
    "engagement_zone": 1,
    "engagement_zone_vertical": 5,
    "max_base_size_hex": 35,
    "unit_model_cohesion_range": 2,
    "unit_global_cohesion_range": 9,
    "squad_min_neighbors": 1,
    "cohesion_distance_mode": "euclidean",
}


def _unit(uid: int, player: int, positions: List[Tuple[int, int]], value: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(positions), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0, "OC": 1, "VALUE": value * len(positions),
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        "models": [
            {"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": value} for c, r in positions
        ],
    }


def _gs() -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {"game_rules": _GAME_RULES, "board": {"default": {"hex_radius": 1.0, "margin": 0.0}}},
        "board_cols": 80, "board_rows": 80, "wall_hexes": set(), "terrain_areas": [],
        "objectives": [], "inches_to_subhex": 1, "_unit_move_version": 0,
        "units": [
            _unit(1, 1, [(10, 10), (12, 10), (14, 10)], value=10),   # 30 pts
            _unit(2, 2, [(40, 10), (42, 10)], value=20),             # 40 pts
        ],
    }
    gs["unit_by_id"] = {str(u["id"]): u for u in gs["units"]}
    build_units_cache(gs)
    return gs


def test_value_at_start_is_captured_at_build():
    gs = _gs()
    assert gs["value_at_start"] == {1: 30, 2: 40}


def test_replacing_one_player_keeps_the_other_baseline():
    gs = _gs()
    destroy_model(gs, "1#0", reason="combat")  # le joueur 1 a perdu 10 pts

    _replace_units_for_player(gs, 2, [_unit(3, 2, [(50, 10)], value=25)])

    # Joueur 2 : nouvelle vague -> nouvelle reference.
    assert gs["value_at_start"][2] == 25
    # Joueur 1 : reference INCHANGEE (sinon ses pertes seraient effacees de l'observation).
    assert gs["value_at_start"][1] == 30
