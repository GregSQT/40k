"""11.04 / 12.03 / 12.08 : un charge move et un pile-in sont des MOVES — donc bornes par le TRAJET.

Les trois regles disent mot pour mot « **Your unit moves as described in Moving (03)** ». Le
move normal, lui, borne chaque figurine par un champ geodesique qui contourne murs et figurines
(`explain_move_plan_rejection`). La charge (`charge_build_valid_plan`) et le pile-in /
consolidation (`_assign_cells_toward_enemies`) retenaient une cellule sur
`calculate_hex_distance(origine, cellule) <= budget` et ne validaient que la case d'ARRIVEE :
le trajet n'etait jamais regarde.

Mesure sur un run de 600 episodes : 43 charges et 28 consolidations au-dela du budget reel.
Cas type E301 — six socles franchissent la ligne de murs de la colonne 33 avec un jet de 8,
alors que leurs trajets legaux coutent 8, 9, 11, 11, 12 et 13.

Chaque test CONSTRUIT sa geometrie et verifie d'abord sa premisse (la ligne droite tient dans le
budget, le chemin non) : sans cette prémisse, un refus pour une autre raison passerait pour un
verrou.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.shared_utils import (
    build_units_cache,
    charge_build_valid_plan,
    geodesic_move_reach,
    squad_consolidate_plan,
)
from tests._state_invariants import turn_state_invariants


def _unit(uid: str, player: int, models: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    col, row = models[0]
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "HP_CUR": len(models), "HP_MAX": len(models), "VALUE": 100, "OC": 1, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round", "MOVE": 6, "UNIT_RULES": [], "UNIT_KEYWORDS": [],
        "models": [{"col": c, "row": r, "VALUE": 10} for c, r in models],
    }


def _gs(units: List[Dict[str, Any]], walls: Sequence[Tuple[int, int]], phase: str) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
                "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
            },
            "charge": {"charge_max_distance": 12},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            # Toggles reels de config/game_config.json : les murs bloquent le transit, les
            # figurines ennemies aussi. C'est ce que le move normal applique deja.
            "move": {
                "can_move_through_enemy_engagement_zone": True,
                "can_move_through_enemy_model": False,
                "can_move_through_friendly_model": True,
            },
        },
        "board_cols": 60, "board_rows": 60,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(walls),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "_unit_move_version": 0,
        "inches_to_subhex": 1,
        "charge_roll_values": {},
        "charge_target_selections": {},
        "charge_activation_pool": [],
        "action_logs": [], "action_log_seq": 0,
    }
    build_units_cache(gs)
    return gs


# Muraille verticale sans ouverture : la ligne droite (26,20)->(33,20) coute 7, le contournement
# legal en coute 11. Un jet de 8 ne doit donc PAS suffire, un jet de 12 doit suffire.
WALL = [(30, r) for r in range(17, 24)]
ATTACKER = (26, 20)
TARGET = (34, 20)


def _straight_and_path(start: Tuple[int, int], dest: Tuple[int, int], budget: int,
                       walls: Sequence[Tuple[int, int]]) -> Tuple[int, bool]:
    field = geodesic_move_reach(start[0], start[1], budget, set(walls), 60, 60)
    return calculate_hex_distance(*start, *dest), dest in field


# ─────────────────────────────────────────────────────────────────────────────
# CHARGE (11.04)
# ─────────────────────────────────────────────────────────────────────────────

def test_geometry_premise_the_wall_makes_the_path_longer_than_the_roll() -> None:
    """Sans cette premisse, un refus prouverait seulement que le jet est trop court."""
    contact = (33, 20)  # case au contact de la cible, cote ouest de la muraille... derriere le mur
    straight, reachable = _straight_and_path(ATTACKER, contact, 8, WALL)
    assert straight <= 8, straight
    assert reachable is False, "le contournement doit couter plus que le jet"


def test_a_charge_cannot_cross_a_wall_even_when_the_straight_line_fits() -> None:
    """11.04 EFFECT : le charge move est un move (03) — il contourne, il ne traverse pas."""
    gs = _gs([_unit("1", 1, [ATTACKER]), _unit("101", 2, [TARGET])], WALL, "charge")
    assert charge_build_valid_plan(gs, "1", ["101"], 8) is None


def test_the_same_charge_succeeds_without_the_wall() -> None:
    """Contre-epreuve : sans l'obstacle, le meme jet suffit. Sinon le test ne prouverait rien."""
    gs = _gs([_unit("1", 1, [ATTACKER]), _unit("101", 2, [TARGET])], [], "charge")
    plan = charge_build_valid_plan(gs, "1", ["101"], 8)
    assert plan is not None
    assert len(plan) == 1


def test_a_charge_that_goes_around_within_the_roll_is_allowed() -> None:
    """Le contournement n'est pas interdit : il est COMPTE. Jet suffisant -> charge legale."""
    gs = _gs([_unit("1", 1, [ATTACKER]), _unit("101", 2, [TARGET])], WALL, "charge")
    plan = charge_build_valid_plan(gs, "1", ["101"], 12)
    _, reachable = _straight_and_path(ATTACKER, (33, 20), 12, WALL)
    assert reachable is True, "premisse : 12 doit suffire au contournement"
    assert plan is not None


# ─────────────────────────────────────────────────────────────────────────────
# CONSOLIDATION (12.08) — jumeau du pile-in (12.03), meme helper
# ─────────────────────────────────────────────────────────────────────────────

# L'ennemi est a 3 cases a vol d'oiseau, mais un mur en L impose un detour de 5.
CONSO_WALL = [(21, 19), (21, 20), (21, 21), (21, 22), (20, 22), (19, 22)]
CONSO_ATTACKER = (19, 20)
CONSO_ENEMY = (23, 20)


def test_geometry_premise_the_consolidation_target_is_close_but_walled_off() -> None:
    straight, reachable = _straight_and_path(CONSO_ATTACKER, (22, 20), 3, CONSO_WALL)
    assert straight <= 3, straight
    assert reachable is False


def test_consolidation_does_not_walk_through_a_wall() -> None:
    """12.08 EFFECT : « moves as described in Moving (03) ». 3 pouces de TRAJET, pas de vol d'oiseau.

    Aucune cellule au contact n'etant joignable en 3 pas de trajet, le plan n'atteint jamais
    l'engagement exige et la consolidation est refusee — au lieu de traverser le mur.
    """
    gs = _gs(
        [_unit("1", 1, [CONSO_ATTACKER]), _unit("101", 2, [CONSO_ENEMY])], CONSO_WALL, "fight"
    )
    assert squad_consolidate_plan(gs, "1") is None


def test_consolidation_still_works_without_the_wall() -> None:
    """Contre-epreuve : meme geometrie, mur retire -> la figurine va bien au contact."""
    gs = _gs([_unit("1", 1, [CONSO_ATTACKER]), _unit("101", 2, [CONSO_ENEMY])], [], "fight")
    plan = squad_consolidate_plan(gs, "1")
    assert plan is not None
    assert plan[0][1:] == (22, 20), plan
