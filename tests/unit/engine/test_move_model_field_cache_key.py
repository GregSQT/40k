"""Le cache du champ géodésique de move est indexé sur TOUT ce dont le champ dépend.

`movement_build_model_destinations_pool` mémorise le champ euclidien par-figurine dans
``game_state["_move_model_field_cache"]``. Sa clé portait ``(model, col, row, budget,
orientation)`` — pas le NIVEAU DE VUE, alors que les obstacles de traversée en dépendent :
``enemy_occupied`` est construit au niveau de vue et entre dans le champ dès que
``can_move_through_enemy_model`` est faux (valeur de production).

Le niveau de vue est un paramètre PAR REQUÊTE de l'UI (``move_model_destinations``), et rien
n'invalide le cache entre deux previews sans commit : un joueur qui bascule l'affichage d'étage
pendant qu'une figurine est activée relisait donc le champ de l'autre niveau. Dans un sens le
preview est amputé (ennemis du sol traités en murs à l'étage) ; dans l'autre il OFFRE des cases
qui exigent de traverser des figurines ennemies, que la validation refuse — la classe
« masque ⊄ exécutable » de §0.34.

Géométrie : board x5 (``inches_to_subhex = 5`` → géométrie non-hex, métrique ``move`` euclidienne
de `config/game_config.json`, donc le chemin qui utilise le cache), mur d'ennemis AU SOL en
colonne 12 barrant tout l'horizon du mover. Aucun plancher : au niveau de vue 1 il n'y a donc
personne, et le champ doit s'étendre au-delà du mur.
"""

from typing import Any, Dict, List, Tuple

from engine.phase_handlers.movement_handlers import movement_build_model_destinations_pool
from tests._state_invariants import turn_state_invariants, unit_invariants

START = (8, 20)
WALL_COL = 12
WALL_ROWS = range(12, 29)
MOVE_SUBHEX = 8


def _unit(uid: str, player: int, col: int, row: int) -> Dict[str, Any]:
    return {**unit_invariants(),
        "id": uid, "player": player, "col": col, "row": row, "MOVE": MOVE_SUBHEX,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
        "MODEL_HEIGHT": 2.0, "level": 0,
    }


def _gs() -> Dict[str, Any]:
    mover = _unit("1", 1, *START)
    models_cache: Dict[str, Dict[str, Any]] = {
        "1#0": {"col": START[0], "row": START[1], "level": 0, "player": 1, "squad_id": "1",
                "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
    }
    units_cache: Dict[str, Dict[str, Any]] = {
        "1": {"col": START[0], "row": START[1], "player": 1, "occupied_hexes": {START},
              "BASE_SHAPE": "round", "BASE_SIZE": 1},
    }
    squad_models: Dict[str, List[str]] = {"1": ["1#0"]}
    units = [mover]
    # Mur d'ennemis AU SOL (level 0) : une escouade mono-figurine par case de la colonne 12.
    for i, r in enumerate(WALL_ROWS):
        uid = f"9{i}"
        enemy = _unit(uid, 2, WALL_COL, r)
        units.append(enemy)
        models_cache[f"{uid}#0"] = {
            "col": WALL_COL, "row": r, "level": 0, "player": 2, "squad_id": uid,
            "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
        units_cache[uid] = {"col": WALL_COL, "row": r, "player": 2,
                            "occupied_hexes": {(WALL_COL, r)},
                            "BASE_SHAPE": "round", "BASE_SIZE": 1}
        squad_models[uid] = [f"{uid}#0"]
    return {**turn_state_invariants(),
        "models_cache": models_cache,
        "squad_models": squad_models,
        "units_cache": units_cache,
        "units": units,
        "unit_by_id": {u["id"]: u for u in units},
        "board_cols": 30, "board_rows": 40,
        "wall_hexes": set(),
        # Vide DÉLIBÉRÉMENT : la dilatation d'EZ legacy interdirait les mêmes cases aux deux
        # niveaux de vue et masquerait l'effet mesuré ici (elle ne dépend pas du niveau).
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {
                "engagement_zone": 1, "unit_model_cohesion_range": 2,
                "unit_global_cohesion_range": 9, "cohesion_distance_mode": "euclidean",
                "squad_min_neighbors": 1,
            },
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
            # Lu par les contours d'aperçu (`compute_move_preview_mask_loops_world`) que le pool
            # par-figurine renvoie avec ses destinations.
            "board": {"hex_radius": 20.0, "margin": 10.0},
        },
        "phase": "move",
        "inches_to_subhex": 5,  # > 1 → géométrie non-hex → métrique `move` = euclidean
        "current_player": 1,
        "terrain_areas": [],
    }


def _anchors_beyond_wall(gs: Dict[str, Any], level: int) -> List[Tuple[int, int]]:
    pool = movement_build_model_destinations_pool(gs, "1#0", level=level)
    return [(c, r) for c, r, _lv in pool["destinations"] if c > WALL_COL]


def test_ground_enemies_block_the_field_at_view_level_zero():
    """Témoin : au sol, le mur d'ennemis borne le champ — rien au-delà de la colonne 12."""
    assert _anchors_beyond_wall(_gs(), 0) == []


def test_switching_view_level_does_not_reuse_the_other_level_s_field():
    """LE verrou : le même appel au niveau de vue 1 ne doit PAS relire le champ du sol.

    Les ennemis sont tous au niveau 0 : au niveau de vue 1 ils ne barrent plus la traversée, donc
    des ancres au-delà du mur existent. Avec la clé incomplète, le second appel tombait sur
    l'entrée du premier et rendait le champ du SOL.
    """
    gs = _gs()
    assert _anchors_beyond_wall(gs, 0) == [], "témoin sol cassé : la fixture n'exerce rien"
    assert _anchors_beyond_wall(gs, 1), (
        "le champ du niveau de vue 0 a été réutilisé au niveau 1 — la clé du cache ne porte pas "
        "le niveau de vue"
    )


def test_the_two_view_levels_hold_two_distinct_cache_entries():
    """Verrou de CÂBLAGE : deux entrées, et le niveau de vue les distingue.

    Sans lui, un futur appelant pourrait rétablir la collision en normalisant la clé ; et un
    cache resté VIDE (chemin hex au lieu d'euclidien) rendrait les deux tests ci-dessus vacants.
    """
    gs = _gs()
    movement_build_model_destinations_pool(gs, "1#0", level=0)
    movement_build_model_destinations_pool(gs, "1#0", level=1)
    keys = list(gs["_move_model_field_cache"].keys())
    assert len(keys) == 2, f"champ non mémorisé ou clés confondues : {keys}"
    # Même figurine, même départ, même budget, même orientation : seul le niveau les sépare.
    assert keys[0][:5] == keys[1][:5]
    assert {k[5] for k in keys} == {0, 1}
