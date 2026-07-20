"""Pile In (PDF 12.02) — le plan ne doit JAMAIS superposer deux figurines de l'escouade.

Règle : chaque figurine se déplace jusqu'à 3" pour finir bord-à-bord avec un ennemi. Rien
dans 12.02 n'autorise deux figurines à occuper le même hex — l'invariant d'occupation du
moteur s'applique au pile-in comme au reste.

Contexte (V11 §0.18) : le crash `collision intra-plan` du move démontre statiquement qu'un
état de départ superposé existe. `fight_pile_in_plan` est le seul écrivain par-figurine qui
ne passe pas par `validate_move_plan` (`commit_move` ne re-valide pas, par contrat).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from engine.phase_handlers.shared_utils import fight_pile_in_plan, squad_consolidate_plan


def _real_game_rules() -> Dict[str, Any]:
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    with open(os.path.join(root, "config", "game_config.json"), encoding="utf-8") as fh:
        return json.load(fh)["game_rules"]


def _model(squad_id: str, col: int, row: int, player: int = 1) -> Dict[str, Any]:
    # `player` est porté par chaque entrée models_cache en jeu réel (shared_utils.py:661).
    return {
        "squad_id": squad_id, "col": col, "row": row, "level": 0, "player": player,
        "HP_CUR": 1, "HP_MAX": 1, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        "orientation": 0, "MODEL_HEIGHT": 2.5,
    }


def _make_gs(
    squads: Dict[str, Tuple[int, List[Tuple[int, int]]]],
    walls: Any = None,
) -> Dict[str, Any]:
    """squads : {squad_id: (player, [(col, row), ...])}. Plateau nu, 1" = 1 subhex."""
    models_cache: Dict[str, Any] = {}
    squad_models: Dict[str, List[str]] = {}
    units_cache: Dict[str, Any] = {}
    for sid, (player, positions) in squads.items():
        mids: List[str] = []
        for idx, (col, row) in enumerate(positions):
            mid = f"{sid}#{idx}"
            models_cache[mid] = _model(sid, col, row, player)
            mids.append(mid)
        squad_models[sid] = mids
        units_cache[sid] = {
            "col": positions[0][0], "row": positions[0][1], "player": player,
            "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
            "MODEL_HEIGHT": 2.5, "HP_CUR": 1,
            "occupied_hexes": {p for p in positions},
        }
    return {
        "inches_to_subhex": 1, "board_cols": 40, "board_rows": 40,
        "wall_hexes": set(walls or ()), "models_cache": models_cache,
        "squad_models": squad_models, "units_cache": units_cache,
        # game_rules RÉELLES du jeu — ne pas recopier de constantes ici : un seuil de test
        # divergeant du jeu ferait passer (ou échouer) le test pour la mauvaise raison.
        "config": {"game_rules": _real_game_rules()},
        "units": [], "objectives": [],
    }


class TestPileInNeverSuperposesOwnSquad:
    def test_stationary_b2b_figurine_cell_is_not_stolen(self):
        """S#0 ne doit pas se voir attribuer la cellule de S#1, qui y reste (déjà B2B).

        S#1 est bord-à-bord avec l'ennemi : la règle la laisse sur place. S#0, à 2 hex de
        l'ennemi, cherche une case B2B — la plus proche de son origine est justement celle
        de S#1. Rien ne doit lui permettre de la prendre.
        """
        gs = _make_gs({
            "S": (1, [(10, 8), (10, 9)]),   # S#0 non-B2B (dist 2), S#1 déjà B2B (dist 1)
            "E": (2, [(10, 10)]),
        })
        plan = fight_pile_in_plan(gs, "S")
        assert plan is not None, "le plan doit exister (pile-in légal ici)"
        cells = [(c, r) for _mid, c, r in plan]
        assert len(set(cells)) == len(cells), (
            f"deux figurines de l'escouade sur le même hex : {plan}"
        )


class TestPvpPileInStillBlocksTeammates:
    """VERROU du chemin PvP — il est sain, rien ne le vérifiait (V11 §0.18).

    Le pile-in existe en DEUX exemplaires : `fight_pile_in_plan` (gym, corrigé ici) et
    `_fight_pile_in_build_model_pool` (PvP, order-independent par construction). Le PvP est sain
    parce que son BFS bloque sur les socles des coéquipières, à leur position provisoire. Aucun
    test ne le verrouillait : une « harmonisation » du PvP sur le gym serait passée en vert.
    """

    def test_teammate_cell_is_absent_from_pvp_pool(self):
        from engine.phase_handlers.fight_handlers import _fight_pile_in_build_model_pool

        gs = _make_gs({
            "S": (1, [(10, 8), (10, 9)]),   # S#1 occupe (10,9)
            "E": (2, [(10, 10)]),
        })
        gs["units"] = [
            {"id": "S", "player": 1, "col": 10, "row": 8, "BASE_SHAPE": "round",
             "BASE_SIZE": 1, "orientation": 0, "UNIT_KEYWORDS": [], "level": 0,
             "MODEL_HEIGHT": 2.5},
            {"id": "E", "player": 2, "col": 10, "row": 10, "BASE_SHAPE": "round",
             "BASE_SIZE": 1, "orientation": 0, "UNIT_KEYWORDS": [], "level": 0,
             "MODEL_HEIGHT": 2.5},
        ]
        # unit_by_id : index {id: unit} que le moteur construit au reset (w40k_core.py:6119).
        gs["unit_by_id"] = {str(u["id"]): u for u in gs["units"]}
        gs["terrain_areas"] = []
        pool = _fight_pile_in_build_model_pool(gs, "S#0", ["E"])
        closer = {(int(c), int(r)) for c, r in pool["closer"]}
        assert (10, 9) not in closer, (
            "la cellule occupée par la coéquipière S#1 ne doit jamais entrer dans le pool PvP"
        )


class TestPileInMaximisesEngagedModels:
    """12.03 WHILE MOVING : « engaged with it **if possible** » ; encart 12 : « units will pile
    in to **maximise** the number of models that are engaged ».

    Un parcours glouton dans l'ordre des index ne maximise pas : S#0, servie en premier, prend
    la case la plus proche d'elle — qui se trouve être la SEULE que S#1 peut atteindre. Le
    couplage maximum donne à S#0 une autre case B2B, également légale, et engage les DEUX.
    """

    def test_greedy_order_does_not_cost_an_engagement(self):
        # Ennemi en (10,10). S#0 en (8,10) atteint 6 cases B2B, la plus proche étant (9,9).
        # S#1 en (6,8) n'atteint QUE (9,9) — vérifié par calcul de distances, pas supposé.
        gs = _make_gs({
            "S": (1, [(8, 10), (6, 8)]),
            "E": (2, [(10, 10)]),
        })
        plan = fight_pile_in_plan(gs, "S")
        assert plan is not None, "le plan doit exister"
        from engine.phase_handlers.shared_utils import (
            BASE_TO_BASE_SUBHEX, calculate_hex_distance,
        )
        engaged = [
            mid for mid, c, r in plan
            if calculate_hex_distance(c, r, 10, 10) == BASE_TO_BASE_SUBHEX
        ]
        assert len(engaged) == 2, (
            f"les deux figurines pouvaient finir bord-à-bord, seules {len(engaged)} "
            f"l'ont fait : {plan}"
        )


class TestConsolidationNeverSuperposesOwnSquad:
    """Même défaut, second consommateur (`squad_consolidate_plan`) — cf. V11 §0.18.

    Ici aucune figurine n'est « immobile par la règle » : la collision naît de la branche
    « rien de mieux → reste sur place ». Il faut donc priver S#1 de toute alternative, sinon
    le test passerait déjà sans le correctif (il choisirait un autre hex) et vérifierait le
    contraire de ce qu'il prétend.
    """

    def test_figurine_staying_put_keeps_its_cell(self):
        # Voisins réels de l'ennemi (10,10) : (9,9) (9,10) (10,9) (10,11) (11,9) (11,10).
        # Tous murés sauf (10,9), la cellule de S#1 → S#0 n'a aucune autre case B2B, et S#1
        # n'a aucune case strictement plus proche : elle reste sur place.
        walls = {(9, 9), (9, 10), (10, 11), (11, 9), (11, 10)}
        gs = _make_gs(
            {"S": (1, [(10, 7), (10, 9)]), "E": (2, [(10, 10)])},
            walls=walls,
        )
        plan = squad_consolidate_plan(gs, "S")
        assert plan is not None, "le plan doit exister (consolidation légale ici)"
        cells = [(c, r) for _mid, c, r in plan]
        assert len(set(cells)) == len(cells), (
            f"deux figurines de l'escouade sur le même hex : {plan}"
        )
