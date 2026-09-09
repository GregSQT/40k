"""V11 Finding1 — Bug ascent depuis niveau > 0 : branche else utilisait le champ BFS du
niveau 0 au lieu du niveau d'arrivée effectif (_lv_eff).

Scénario : figurine déjà à l'étage 1 qui redéclare l'ascent. La candidate (7,5) est aussi à
l'étage 1. L'ennemi est en (6,5) — seul chemin entre (5,5) et (7,5) dans le budget 2, le mur en
(6,6) bloquant l'itinéraire diagonal. Le transit au bon niveau (1) bloque/non-bloque selon le
niveau de l'ennemi ; le bug utilisait le transit du niveau 0 qui voyait/ne voyait pas l'ennemi
à l'envers.

Rouge avant fix (shared_utils.py — branche else de la boucle BFS par-figurine) :
  - ennemi niveau 1 → (7,5) gardé  [BFS lvl-0 ne voit pas l'ennemi   → FAUX, doit exclure]
  - ennemi niveau 0 → (7,5) exclu  [BFS lvl-0 voit l'ennemi à tort   → FAUX, doit garder]
Vert après fix :
  - ennemi niveau 1 → (7,5) exclu  [BFS lvl-1 voit l'ennemi → (6,5) bloqué → (7,5) inatteignable]
  - ennemi niveau 0 → (7,5) gardé  [BFS lvl-1 ne voit pas l'ennemi lvl-0 → (6,5) libre → (7,5) ok]
"""

from engine.phase_handlers.shared_utils import erode_move_pool_by_squad_block
from tests._state_invariants import turn_state_invariants, unit_invariants

# Budget de l'escouade en subhex. Descent penalty = height_inches * inches_to_subhex = 1 * 1 = 1.
# _normal_exec = MOVE - descent = 3 - 1 = 2. Pool à 2 subhex → coût exécutable.
MOVE_SUBHEX = 3

# Terrain : plancher niveau 1, hauteur 1 pouce, couvrant un rectangle autour de (5,5)-(7,5).
# polygon_vertices en coordonnées hex → converties en espace pixel par floor_level_by_cell pour
# le test d'empreinte ronde (footprint_within_floor). Le polygone englobe (5,5), (6,5), (7,5),
# (6,6) avec au moins 0,75 unité de marge (rayon du socle round/1) par rapport à chaque arête.
_TERRAIN = [{
    "floors": [{
        "level": 1,
        "height_inches": 1.0,
        "hexes": [(col, row) for col in range(3, 10) for row in range(3, 9)],
        "polygon_vertices": [[3, 3], [9, 3], [9, 8], [3, 8]],
    }]
}]

# Seule destination du pool : à 2 sauts de l'origine (5,5), via (6,5) ou (6,6).
# (6,6) est un MUR → seul chemin direct est (5,5)→(6,5)→(7,5).
POOL = {(7, 5): 2.0}


def _gs(enemy_level: int) -> dict:
    """game_state minimal pour tester le bug de transit en ascent depuis niveau > 0.

    Escouade "1" : une figurine (ancre) en (5,5) au niveau 1, MOVE=3, mur en (6,6).
    Escouade "2" (adverse) : une figurine en (6,5) au niveau ``enemy_level``.
    """
    unit = {
        **unit_invariants(),
        "id": 1, "player": 1, "col": 5, "row": 5, "MOVE": MOVE_SUBHEX,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
    }
    return {
        **turn_state_invariants(),
        # Déclaration d'ascent pour l'escouade "1" (ASCENT_DECLARED_KEY = "units_declared_ascent").
        "units_declared_ascent": {"1"},
        "models_cache": {
            "1#0": {
                "col": 5, "row": 5, "level": 1, "player": 1, "squad_id": "1",
                "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
            "2#0": {
                "col": 6, "row": 5, "level": enemy_level, "player": 2, "squad_id": "2",
                "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            },
        },
        "squad_models": {"1": ["1#0"], "2": ["2#0"]},
        "units_cache": {
            "1": {"col": 5, "row": 5, "player": 1, "occupied_hexes": {(5, 5)},
                  "BASE_SHAPE": "round", "BASE_SIZE": 1},
            "2": {"col": 6, "row": 5, "player": 2, "occupied_hexes": {(6, 5)},
                  "BASE_SHAPE": "round", "BASE_SIZE": 1},
        },
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 20,
        "board_rows": 20,
        # Mur en (6,6) = itinéraire diagonal bloqué → seul chemin de (5,5) à (7,5) passe par (6,5).
        "wall_hexes": {(6, 6)},
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "phase": "move",
        "gym_training_mode": True,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": _TERRAIN,
    }


def test_ascent_depuis_niveau1_ennemi_niveau1_exclut_destination():
    """Bug : branche else utilisait BFS niveau 0 → ne voyait pas l'ennemi niveau 1 → gardait (7,5).

    Fix : BFS niveau 1 → ennemi en (6,5) bloque le transit → (7,5) inatteignable → exclu.
    """
    gs = _gs(enemy_level=1)
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert (7, 5) not in kept, (
        "ennemi niveau 1 en (6,5) doit bloquer le transit niveau 1 vers (7,5) — "
        "le BFS de la branche else doit utiliser _lv_eff=1, pas lvl=0"
    )


def test_ascent_depuis_niveau1_ennemi_niveau0_retient_destination():
    """Bug : branche else utilisait BFS niveau 0 → voyait l'ennemi niveau 0 → excluait (7,5).

    Fix : BFS niveau 1 → ennemi niveau 0 invisible au niveau 1 → (6,5) libre → (7,5) retenu.
    """
    gs = _gs(enemy_level=0)
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert (7, 5) in kept, (
        "ennemi niveau 0 en (6,5) ne doit pas bloquer le transit niveau 1 vers (7,5) — "
        "le BFS de la branche else doit utiliser _lv_eff=1 (ennemi lvl-0 absent du transit lvl-1)"
    )
