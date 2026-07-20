"""V11 T6-g — Le pool de move doit valider le BLOC translaté, pas seulement l'ANCRE.

Rupture corrigée (2026-07-19) : `movement_build_valid_destinations_pool` raisonne sur l'ancre
de l'escouade, mais l'exécution passe par `build_rigid_plan`, qui translate TOUTES les figurines
du même vecteur. Une ancre parfaitement légale pouvait donc poser une sœur sur un mur ou sur une
autre escouade : `validate_move_plan` rejetait alors une destination offerte par le masque
(`ValueError: execute_squad_move a échoué : … incohérence masque/exécution`), tuant les workers
`SubprocVecEnv` du training.

Fix : érosion morphologique du pool par l'empreinte combinée de l'escouade
(`erode_move_pool_by_squad_block`), en coords CUBE (offsets de bloc invariants depuis T6-h).

Verrou : toute cellule conservée par l'érosion est exécutable — le bloc translaté ne pose
AUCUNE figurine hors plateau / sur un mur / sur une autre escouade / dans l'ER ennemie.
"""

from typing import Iterable, Tuple

import pytest

from engine.phase_handlers.shared_utils import erode_move_pool_by_squad_block


def _game_state(
    *,
    wall_hexes: Iterable[Tuple[int, int]] = (),
    enemy_er: Iterable[Tuple[int, int]] = (),
):
    """game_state minimal : uniquement ce que l'érosion lit.

    Escouade "1" en ligne horizontale : ancre (10,10), sœurs (11,10) et (12,10).
    """
    models_cache = {
        "1#0": {"col": 10, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1},
        "1#1": {"col": 11, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1},
        "1#2": {"col": 12, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1},
    }
    return {
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0", "1#1", "1#2"]},
        "units_cache": {"1": {"col": 10, "row": 10, "player": 1, "occupied_hexes": set()}},
        "board_cols": 44,
        "board_rows": 60,
        "wall_hexes": set(wall_hexes),
        "enemy_adjacent_hexes_player_1": set(enemy_er),
        # Empreintes mono-hex : engagement_zone <= 1 (cf. _compute_unit_occupied_hexes).
        "config": {"game_rules": {"engagement_zone": 1}},
    }


def _with_other_squad(gs, cells):
    """Ajoute une escouade adverse occupant `cells`.

    L'occupation PAR NIVEAU (`_occupied_hexes_at_level`) est lue depuis `models_cache` +
    `squad_models`, pas depuis `occupied_hexes` du units_cache (qui est l'union tous niveaux).
    """
    cells = list(cells)
    mids = []
    for i, (col, row) in enumerate(cells):
        mid = f"2#{i}"
        mids.append(mid)
        gs["models_cache"][mid] = {
            "col": col, "row": row, "level": 0, "player": 2, "squad_id": "2", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1,
        }
    gs["squad_models"]["2"] = mids
    gs["units_cache"]["2"] = {
        "col": cells[0][0], "row": cells[0][1], "player": 2, "occupied_hexes": set(cells),
    }
    return gs


# Pool d'ancre : la ligne de cellules à la même rangée, toutes légales POUR L'ANCRE.
POOL = {(c, 10): 1.0 for c in range(5, 20)}


def test_erosion_is_identity_when_nothing_blocks():
    """Sans obstacle, l'érosion ne retire rien (pas de sur-filtrage)."""
    gs = _game_state()
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert set(kept) == set(POOL)


def test_erosion_drops_anchor_whose_sister_lands_on_a_wall():
    """Un mur sous une SŒUR retire la cellule d'ancre, alors que l'ancre y est légale."""
    # Mur en (15,10). Ancre en (13,10) → sœurs en (14,10) et (15,10) → la 3e est dans le mur.
    gs = _game_state(wall_hexes={(15, 10)})
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert (13, 10) not in kept, (
        "ancre conservée alors que la figurine 1#2 atterrit sur un mur — le masque offrirait "
        "une destination que validate_move_plan rejette (V11 T6-g)"
    )
    assert (13, 10) in POOL, "le pool d'ancre offrait bien cette cellule : le test exerce l'érosion"
    # L'ancre elle-même sur le mur est retirée aussi.
    assert (15, 10) not in kept


def test_erosion_drops_anchor_whose_sister_lands_on_another_squad():
    """Une autre escouade sous une SŒUR retire la cellule d'ancre."""
    gs = _with_other_squad(_game_state(), {(16, 10)})
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert (14, 10) not in kept, "1#2 atterrirait sur l'escouade adverse (V11 T6-g)"


def test_erosion_drops_anchor_whose_sister_lands_in_enemy_er():
    """L'ER ennemie sous une SŒUR retire la cellule d'ancre (forbid_enemy_er par défaut)."""
    gs = _game_state(enemy_er={(9, 10)})
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert (7, 10) not in kept, "1#2 atterrirait dans l'ER ennemie (V11 T6-g)"


def test_erosion_drops_anchor_whose_block_leaves_the_board():
    """Le bloc qui déborde du plateau est retiré, même si l'ancre est dans les bornes."""
    gs = _game_state()
    pool = {(c, 10): 1.0 for c in range(40, 44)}
    kept = erode_move_pool_by_squad_block(gs, "1", pool)
    assert (43, 10) not in kept, "1#1/1#2 sortiraient du plateau (board_cols=44)"
    assert (42, 10) not in kept
    assert (41, 10) in kept, "sur-filtrage : le bloc tient encore entièrement sur le plateau"


def test_single_model_squad_pool_untouched():
    """Escouade mono-figurine : l'ancre EST le bloc, le pool d'ancre est déjà exact."""
    gs = _game_state(wall_hexes={(15, 10)})
    gs["squad_models"]["1"] = ["1#0"]
    kept = erode_move_pool_by_squad_block(gs, "1", dict(POOL))
    assert kept is not None and set(kept) == set(POOL)
