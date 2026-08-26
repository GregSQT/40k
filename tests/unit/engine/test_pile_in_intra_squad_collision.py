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
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_move_rules


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
            # Cartes PAR FIGURINE : l'engagement est 3D (§03.04, 2" horizontal ET 5" vertical) et
            # la primitive EXIGE les trois (centres, hauteurs, MODEL_HEIGHT) plutôt que de
            # supposer une altitude. Plateau plat ici → 0.0 partout, donc verdict identique au 2D.
            "occupied_hexes_by_model": {f"{sid}#{i}": p for i, p in enumerate(positions)},
            "floor_height_by_model": {f"{sid}#{i}": 0.0 for i, _ in enumerate(positions)},
        }
    return {**turn_state_invariants(),
        "inches_to_subhex": 1, "board_cols": 40, "board_rows": 40,
        "wall_hexes": set(walls or ()), "models_cache": models_cache,
        "squad_models": squad_models, "units_cache": units_cache,
        # game_rules RÉELLES du jeu — ne pas recopier de constantes ici : un seuil de test
        # divergeant du jeu ferait passer (ou échouer) le test pour la mauvaise raison.
        # `move` : mêmes toggles réels. Le pile-in / la consolidation bornent désormais chaque
        # figurine par son TRAJET (12.03 / 12.08 EFFECT « moves as described in Moving (03) »),
        # ils lisent donc la traversée au même endroit que le move.
        "config": {"game_rules": _real_game_rules(), "move": build_move_rules()},
        # Index {id: unit} que le moteur construit au reset : `move_plan_distance_mode` le lit
        # pour savoir si le vol est déclaré (21.03).
        "units": [],
        "unit_by_id": {sid: {"id": sid, "player": p, "UNIT_RULES": []} for sid, (p, _) in squads.items()},
        "objectives": [],
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
        cells = [(c, r) for _mid, c, r, _lv in plan]  # entree de plan = (mid, col, row, ETAGE)
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
            mid for mid, c, r, _lv in plan
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
        cells = [(c, r) for _mid, c, r, _lv in plan]  # entree de plan = (mid, col, row, ETAGE)
        assert len(set(cells)) == len(cells), (
            f"deux figurines de l'escouade sur le même hex : {plan}"
        )


class TestConsolidationModes:
    """12.08 cascade ongoing→engaging→objective — les trois branches sont desormais implementees.

    Avant P3-5, `squad_consolidate_plan` retournait None des que l'escouade n'avait pas d'ennemi
    present (mode Ongoing seul). Les modes Engaging et Objective etaient entierement absents.
    """

    def test_engaging_mode_moves_toward_nearby_enemy(self):
        """12.08 Engaging : une fig non engagee se deplace vers un ennemi a ≤3"."""
        # S a (10,10), E a (10,13) — distance 3 = trigger range exact.
        gs = _make_gs({
            "S": (1, [(10, 10)]),
            "E": (2, [(10, 13)]),
        })
        plan = squad_consolidate_plan(gs, "S")
        assert plan is not None, "l'ennemi est dans le trigger range (≤3\") → Engaging doit produire un plan"
        from engine.combat_utils import calculate_hex_distance
        _mid, c, r, _lv = plan[0]
        assert calculate_hex_distance(c, r, 10, 13) < calculate_hex_distance(10, 10, 10, 13), (
            f"la fig doit se rapprocher de l'ennemi : {plan}"
        )

    def test_objective_mode_consolidates_into_zone_when_no_enemies(self):
        """12.08 Objective : la fig rejoint la zone de l'objectif quand aucun ennemi n'est present."""
        # Zone large pour que les hexes B2B soient eux-memes dans la zone.
        gs = _make_gs({"S": (1, [(10, 10)])})
        gs["objectives"] = [{"id": "O1", "hexes": [[10, 11], [10, 12], [10, 13]]}]
        plan = squad_consolidate_plan(gs, "S")
        assert plan is not None, "objectif a ≤3\" → Objective doit produire un plan"
        obj_zone = {(10, 11), (10, 12), (10, 13)}
        assert any((c, r) in obj_zone for _, c, r, _ in plan), (
            f"au moins 1 fig doit finir dans la zone de l'objectif : {plan}"
        )

    def test_none_mode_returns_none(self):
        """12.08 None : aucun ennemi ni objectif a portee → pas de consolidation."""
        gs = _make_gs({
            "S": (1, [(10, 10)]),
            "E": (2, [(10, 20)]),  # distance 10, hors trigger range (3")
        })
        plan = squad_consolidate_plan(gs, "S")
        assert plan is None, "aucune branche applicable → doit retourner None"


class TestPileInTargetRestriction12_03:
    """12.03 BEFORE MOVING — restriction des cibles de pile-in selon le statut d'engagement.

    P3-5 : `fight_pile_in_plan` utilise desormais `pile_in_select_targets_12_03` pour
    restreindre les cibles aux ennemis engages (si engagee) ou dans les 5" (si non engagee).
    """

    def test_unengaged_unit_piles_in_to_enemy_within_target_range(self):
        """Unite non engagee : pile-in vers un ennemi dans pile_in_target_range (5")."""
        # S a (10,10), E_close a (10,14) (distance 4 ≤ 5"), E_far a (10,25).
        gs = _make_gs({
            "S": (1, [(10, 10)]),
            "E_close": (2, [(10, 14)]),
            "E_far": (2, [(10, 25)]),
        })
        plan = fight_pile_in_plan(gs, "S")
        assert plan is not None, "E_close est dans 5\" → le pile-in doit etre possible"
        # La fig doit se deplacer vers E_close (seule cible dans 5")
        from engine.combat_utils import calculate_hex_distance
        _mid, c, r, _lv = plan[0]
        assert calculate_hex_distance(c, r, 10, 14) < calculate_hex_distance(10, 10, 10, 14), (
            f"la fig doit se rapprocher de E_close : {plan}"
        )

    def test_unengaged_unit_no_enemies_in_range_returns_none(self):
        """Unite non engagee sans ennemi dans pile_in_target_range (5") → None (12.03)."""
        gs = _make_gs({
            "S": (1, [(10, 10)]),
            "E": (2, [(10, 16)]),  # distance 6 > 5" → hors target range
        })
        plan = fight_pile_in_plan(gs, "S")
        assert plan is None, "aucun ennemi dans 5\" → pas de pile-in (12.03)"
