"""Budget de move en distance de CHEMIN (règle 03), pas à vol d'oiseau.

Bug corrigé : le moteur validait le budget par figurine avec ``calculate_hex_distance`` (ligne
droite cube). ``build_rigid_plan`` translatant tout le bloc du même vecteur, chaque figurine a la
même distance à vol d'oiseau que l'ancre — donc le check passait toujours. Mais une figurine
partant derrière un mur a un trajet LÉGAL (contournant le mur, règle 03) qui peut dépasser son
budget : elle était placée illégalement (analyzer : « Advance/Move path blocked (BFS) »).

Fix (deux côtés de l'invariant « masque ⊆ exécutable ») :
  - ``explain_move_plan_rejection`` borne chaque figurine non-FLY par un BFS géodésique (sol) ;
  - ``erode_move_pool_by_squad_block`` retire du masque les ancres où une sœur dépasse ce budget.

Géométrie : escouade "1" = ancre (5,10) + sœur (10,10). Mur vertical colonne 11, rangées 6..14.
Pour l'ancre en (7,10), la sœur translate en (12,10) : distance à vol d'oiseau = 2 (<= budget 3),
mais le seul trajet légal contourne le mur (> 3 pas). Le check ligne-droite historique passait ;
le check géodésique rejette.
"""

from typing import Any, Dict, Iterable, Tuple

from engine.phase_handlers.shared_utils import (
    build_rigid_plan,
    build_squad_move_cell_map,
    calculate_hex_distance,
    erode_move_pool_by_squad_block,
    explain_move_plan_rejection,
)

WALL = {(11, r) for r in range(6, 15)}
ANCHOR_DEST = (7, 10)
BUDGET = 3  # MOVE=3, inches_to_subhex=1 → budget subhex = 3


def _gs(wall: Iterable[Tuple[int, int]], *, fly: bool = False) -> Dict[str, Any]:
    keywords = [{"keywordId": "fly"}] if fly else []
    unit = {
        "id": 1, "player": 1, "col": 5, "row": 10, "MOVE": BUDGET,
        "HP_CUR": 1, "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": keywords,
    }
    models_cache = {
        "1#0": {"col": 5, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
        "1#1": {"col": 10, "row": 10, "level": 0, "player": 1, "squad_id": "1", "HP_CUR": 1,
                "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
    }
    return {
        "models_cache": models_cache,
        "squad_models": {"1": ["1#0", "1#1"]},
        "units_cache": {"1": {"col": 5, "row": 10, "player": 1, "occupied_hexes": set(),
                              "BASE_SHAPE": "round", "BASE_SIZE": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "wall_hexes": set(wall),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": True,  # → métrique hex (move_gym)
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
    }


def _sister_dest(gs: Dict[str, Any]) -> Tuple[int, int]:
    plan = build_rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], "1", gs)
    assert plan is not None
    sister = next(p for p in plan if p[0] == "1#1")
    return int(sister[1]), int(sister[2])


def _add_other_squad(gs: Dict[str, Any], cells) -> None:
    """Ajoute une escouade adverse '2' occupant `cells` (au niveau 0), lue par
    build_occupied_positions_set (models_cache + squad_models)."""
    cells = list(cells)
    mids = []
    for i, (col, row) in enumerate(cells):
        mid = f"2#{i}"
        mids.append(mid)
        gs["models_cache"][mid] = {
            "col": col, "row": row, "level": 0, "player": 2, "squad_id": "2", "HP_CUR": 1,
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
        }
    gs["squad_models"]["2"] = mids
    gs["units_cache"]["2"] = {
        "col": cells[0][0], "row": cells[0][1], "player": 2,
        "occupied_hexes": set(cells), "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }


def test_advance_block_overlapping_another_squad_is_eroded_not_crashed():
    """Régression §0.18 (crash « incohérence masque/exécution » sur un ADVANCE) : une ancre
    ADVANCE dont le BLOC rigide fait chevaucher une figurine avec une AUTRE escouade DOIT être
    retirée du pool par l'érosion — pas offerte au masque puis rejetée à l'exécution.

    Géométrie : escouade '1' = ancre (5,10) + sœur (10,10) (offset +5 col). Escouade adverse '2'
    en (18,10). Pour l'ancre candidate (13,10) — coût cube 8 > M=6 → régime ADVANCE — la sœur
    translate en (18,10), sur l'escouade '2'. L'érosion au budget advance doit dropper (13,10).
    """
    ADV_BUDGET = 12  # M=6 + jet 6 (subhex, inches_to_subhex=1)
    # Pool d'ancre = ligne row 10, coût = distance cube depuis l'ancre (5,10) — cellules advance incluses.
    pool = {(c, 10): float(abs(c - 5)) for c in range(5, 18) if abs(c - 5) <= ADV_BUDGET}

    gs_free = _gs(set())
    kept_free = erode_move_pool_by_squad_block(gs_free, "1", dict(pool), move_budget=ADV_BUDGET)
    assert (13, 10) in kept_free, "sans obstacle, l'ancre advance (13,10) est légale (sœur en (18,10))"

    gs_occ = _gs(set())
    _add_other_squad(gs_occ, [(18, 10)])
    kept_occ = erode_move_pool_by_squad_block(gs_occ, "1", dict(pool), move_budget=ADV_BUDGET)
    assert (13, 10) not in kept_occ, (
        "ancre advance (13,10) conservée alors que la sœur 1#1 chevauche l'escouade '2' en (18,10) "
        "— le masque l'offrirait puis execute_squad_move lèverait « incohérence masque/exécution »"
    )
    # Et l'invariant : toute ancre conservée produit un plan que validate_move_plan accepte.
    for (cc, rr) in kept_occ:
        plan = build_rigid_plan(cc, rr, "1", gs_occ)
        reason = explain_move_plan_rejection(
            plan, gs_occ, {"budget_per_model": ADV_BUDGET, "require_coherency": False},
        )
        assert reason is None, f"ancre {(cc, rr)} conservée mais rejetée : {reason}"


def test_straight_line_within_budget_but_path_exceeds_is_rejected():
    """La sœur a une distance à vol d'oiseau <= budget mais un trajet légal > budget → rejet."""
    gs = _gs(WALL)
    sc, sr = _sister_dest(gs)
    # Garantit qu'on exerce bien le bug : l'ancien check ligne-droite AURAIT accepté.
    assert calculate_hex_distance(10, 10, sc, sr) <= BUDGET
    plan = build_rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], "1", gs)
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
    )
    assert reason is not None and "injoignable en chemin" in reason, reason


def test_same_plan_without_wall_is_accepted():
    """Sans mur, le trajet == la ligne droite → le plan passe (pas de sur-rejet)."""
    gs = _gs(set())
    plan = build_rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], "1", gs)
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
    )
    assert reason is None, reason


def test_fly_squad_uses_straight_line_even_with_wall():
    """FLY (traversée libre 21.03) : le budget reste à vol d'oiseau, le mur n'ajoute rien."""
    gs = _gs(WALL, fly=True)
    plan = build_rigid_plan(ANCHOR_DEST[0], ANCHOR_DEST[1], "1", gs)
    # allow_walls pour que la sœur puisse finir sur/au-delà du mur (FLY franchit) : on isole le budget.
    reason = explain_move_plan_rejection(
        plan, gs, {"budget_per_model": BUDGET, "require_coherency": False, "allow_walls": True},
    )
    assert reason is None, reason


def test_erosion_drops_anchor_whose_sister_path_exceeds_budget():
    """L'érosion retire l'ancre (7,10) : la sœur ne peut pas atteindre (12,10) en <= budget pas."""
    pool = {(c, 10): float(BUDGET) for c in range(5, 12)}
    kept_wall = erode_move_pool_by_squad_block(_gs(WALL), "1", dict(pool))
    kept_open = erode_move_pool_by_squad_block(_gs(set()), "1", dict(pool))
    assert ANCHOR_DEST not in kept_wall, (
        "ancre conservée alors que la sœur dépasse son budget de chemin — le masque offrirait "
        "une destination que explain_move_plan_rejection rejette (incohérence masque/exécution)"
    )
    assert ANCHOR_DEST in kept_open, "sur-filtrage : sans mur cette ancre est parfaitement légale"


def test_erosion_and_validation_agree_on_every_pool_cell():
    """Invariant masque ⊆ exécutable : toute cellule conservée par l'érosion produit un plan
    accepté par la validation (au budget que l'exécution appliquera)."""
    gs = _gs(WALL)
    pool = {(c, 10): float(BUDGET) for c in range(4, 12)}
    kept = erode_move_pool_by_squad_block(gs, "1", dict(pool))
    for (cc, rr) in kept:
        plan = build_rigid_plan(cc, rr, "1", gs)
        reason = explain_move_plan_rejection(
            plan, gs, {"budget_per_model": BUDGET, "require_coherency": False}
        )
        assert reason is None, f"ancre {(cc, rr)} conservée mais rejetée : {reason}"


def _gym_state_for_cellmap() -> Dict[str, Any]:
    """État gym complet pour build_squad_move_cell_map : squad '1' mono-fig en (10,10), MOVE 3."""
    unit = {
        "id": 1, "player": 1, "col": 10, "row": 10, "MOVE": 3, "HP_CUR": 1,
        "BASE_SIZE": 1, "BASE_SHAPE": "round", "UNIT_KEYWORDS": [],
    }
    return {
        "models_cache": {
            "1#0": {"col": 10, "row": 10, "level": 0, "player": 1, "squad_id": "1",
                    "HP_CUR": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0},
        },
        "squad_models": {"1": ["1#0"]},
        "units_cache": {"1": {"col": 10, "row": 10, "player": 1, "HP_CUR": 1,
                              "occupied_hexes": set(), "BASE_SHAPE": "round", "BASE_SIZE": 1}},
        "units": [unit],
        "unit_by_id": {"1": unit},
        "board_cols": 44, "board_rows": 60,
        "current_player": 1,
        "wall_hexes": set(),
        "enemy_adjacent_hexes_player_1": set(),
        "config": {
            "game_rules": {"engagement_zone": 1},
            "move": {"can_move_through_enemy_engagement_zone": True,
                     "can_move_through_enemy_model": False,
                     "can_move_through_friendly_model": True},
        },
        "phase": "move",
        "gym_training_mode": True,
        "inches_to_subhex": 1,
        "units_took_to_skies": set(),
        "terrain_areas": [],
        "units_moved": set(),
        "_unit_move_version": 0,
    }


def _occupy_cell(gs: Dict[str, Any], col: int, row: int) -> None:
    """Pose une escouade adverse '2' en (col,row) SANS toucher `_unit_move_version` — reproduit
    le bypass qui a causé la régression §0.18 (occupation changée, compteur non bumpé)."""
    gs["models_cache"]["2#0"] = {
        "col": col, "row": row, "level": 0, "player": 2, "squad_id": "2", "HP_CUR": 1,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
    }
    gs["squad_models"]["2"] = ["2#0"]
    gs["units_cache"]["2"] = {
        "col": col, "row": row, "player": 2, "HP_CUR": 1,
        "occupied_hexes": {(col, row)}, "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }


def test_cell_map_cache_invalidates_on_occupation_change_without_version_bump():
    """RÉGRESSION §0.18 : le cache de build_squad_move_cell_map NE DOIT PAS servir une carte
    périmée quand l'occupation change, même si `_unit_move_version` n'est pas bumpé. Sinon le
    masque offre une cellule d'ancre déjà occupée → crash « incohérence masque/exécution ».

    La clé de cache étant un fingerprint LU de l'occupation réelle (pas le compteur), le simple
    ajout d'une escouade sur une cellule offerte invalide l'entrée."""
    gs = _gym_state_for_cellmap()
    first = build_squad_move_cell_map(gs, "1", advance_roll=None)
    offered = {cell for (cell, _cost) in first.values()}
    assert offered, "le pool devrait offrir des cellules"
    # Choisit une cellule offerte et l'occupe (sans bumper la version).
    target = sorted(offered)[0]
    _occupy_cell(gs, target[0], target[1])

    second = build_squad_move_cell_map(gs, "1", advance_roll=None)
    offered2 = {cell for (cell, _cost) in second.values()}
    assert target not in offered2, (
        f"cellule occupée {target} encore offerte après changement d'occupation — cache périmé "
        f"(la clé fingerprint doit capturer l'occupation, indépendamment de _unit_move_version)"
    )


def test_cell_map_cache_serves_identical_result_when_state_unchanged():
    """Non-régression perf : à état inchangé, le 2e appel renvoie l'objet mémoïsé (même identité)."""
    gs = _gym_state_for_cellmap()
    first = build_squad_move_cell_map(gs, "1", advance_roll=None)
    second = build_squad_move_cell_map(gs, "1", advance_roll=None)
    assert first is second, "état inchangé → la carte doit être servie depuis le cache (même objet)"
