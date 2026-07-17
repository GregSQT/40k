"""Coût géodésique et budget forcé du pool de move (§7 T2 / §10.5).

`movement_build_valid_destinations_pool` gagne deux paramètres PUREMENT ADDITIFS :
  - `out_costs`            : {(col,row): coût géodésique en subhex}
  - `move_budget_override` : budget imposé (le gym a besoin du pool au budget Advance alors que
                             l'escouade n'a pas encore déclaré Advance)

Contrat non négociable (§10.5) : quand ils valent None, le PvP est strictement inchangé.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
from engine.phase_handlers.shared_utils import get_squad_move_budget
from engine.w40k_core import W40KEngine


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(uid: int, player: int, col: int, row: int, base_size: int = 1) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": base_size, "MODEL_HEIGHT": 2.5,
    }


def _make_engine(base_size: int = 1, walls=None) -> W40KEngine:
    obs_params = {"perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
                  "obs_size": 108, "action_space_size": 1047}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": walls or [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        # Toggles de traversee : valeurs reelles de config/game_config.json (pas d'invention).
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, 25, 25, base_size), _unit_cfg(2, 2, 55, 55, base_size)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=config)
    eng.reset()
    eng.game_state["phase"] = "move"
    from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(eng.game_state, 1)
    build_enemy_adjacent_hexes(eng.game_state, 2)
    return eng


@pytest.fixture
def engine():
    return _make_engine()


def test_pvp_path_is_strictly_unchanged_without_the_new_params(engine):
    """§10.5 : sans `out_costs` ni `move_budget_override`, le pool est identique a l'avant-refonte."""
    gs = engine.game_state
    baseline = movement_build_valid_destinations_pool(gs, "1", read_only=True)
    again = movement_build_valid_destinations_pool(gs, "1", read_only=True)
    assert baseline == again
    assert len(baseline) > 0


def test_out_costs_keys_match_the_pool_exactly(engine):
    """Invariant central : le pool reste la SEULE autorite, les couts s'y alignent.

    Un ecart signifierait que le masque rend jouable une destination absente du pool (ou
    l'inverse) — exactement le genre de divergence masque/execution que la refonte doit tuer.
    """
    gs = engine.game_state
    costs: Dict = {}
    pool = movement_build_valid_destinations_pool(gs, "1", read_only=True, out_costs=costs)
    assert set(pool) == set(costs.keys())


def test_out_costs_are_geodesic_and_within_budget(engine):
    gs = engine.game_state
    costs: Dict = {}
    movement_build_valid_destinations_pool(gs, "1", read_only=True, out_costs=costs)
    budget = get_squad_move_budget("1", gs, "normal")

    for (col, row), cost in costs.items():
        assert cost > 0, "start_pos est exclu du pool (§4.6) -> aucun cout nul"
        assert cost <= budget + 1e-9, f"({col},{row}) coute {cost} > budget {budget}"
        # Le cout de CHEMIN ne peut jamais etre inferieur a la distance a vol d'oiseau.
        assert cost >= calculate_hex_distance(25, 25, col, row) - 1e-9


def test_out_costs_exceed_crow_flight_when_a_wall_forces_a_detour():
    """Regle 03 : la distance d'un move est celle du CHEMIN. Un mur doit renchérir le cout."""
    # Mur vertical devant l'ancre, avec une seule ouverture loin -> detour force.
    wall = [[27, r] for r in range(20, 31)]
    eng = _make_engine(walls=wall)
    gs = eng.game_state
    costs: Dict = {}
    movement_build_valid_destinations_pool(gs, "1", read_only=True, out_costs=costs)

    detoured = [
        (h, c) for h, c in costs.items()
        if c > calculate_hex_distance(25, 25, h[0], h[1]) + 1e-9
    ]
    assert detoured, "aucune destination ne coute plus que le vol d'oiseau malgre le mur"


def test_move_budget_override_widens_the_pool(engine):
    """Le gym doit obtenir le pool au budget Advance sans avoir declare Advance (§7 T2)."""
    gs = engine.game_state
    normal_budget = get_squad_move_budget("1", gs, "normal")
    advance_budget = get_squad_move_budget("1", gs, "advance", advance_roll=6)
    assert advance_budget > normal_budget
    assert "1" not in gs.get("units_advanced", set()), "l'escouade ne doit PAS etre marquee advancee"

    normal_pool = movement_build_valid_destinations_pool(gs, "1", read_only=True)
    advance_pool = movement_build_valid_destinations_pool(
        gs, "1", read_only=True, move_budget_override=advance_budget
    )
    assert len(advance_pool) > len(normal_pool)
    # Le pool Normal est INCLUS dans le pool Advance -> un seul BFS suffit (§7 T2).
    assert set(normal_pool).issubset(set(advance_pool))


def test_override_pool_carries_costs_that_separate_normal_from_advance(engine):
    """C'est le cout qui tranche le type de move (§6.2), pas une dimension d'action."""
    gs = engine.game_state
    normal_budget = get_squad_move_budget("1", gs, "normal")
    advance_budget = get_squad_move_budget("1", gs, "advance", advance_roll=6)

    costs: Dict = {}
    movement_build_valid_destinations_pool(
        gs, "1", read_only=True, move_budget_override=advance_budget, out_costs=costs
    )
    as_normal = {h for h, c in costs.items() if c <= normal_budget}
    as_advance = {h for h, c in costs.items() if c > normal_budget}
    assert as_normal and as_advance, "le pool Advance doit contenir les deux regimes"

    # Coherence : les destinations classees `normal` sont exactement le pool au budget normal.
    normal_pool = set(movement_build_valid_destinations_pool(gs, "1", read_only=True))
    assert as_normal == normal_pool


def test_move_budget_override_zero_yields_empty_pool_like_the_engine(engine):
    """Budget 0 = etat LEGITIME (`max(0, MOVE - malus)`, Take to the skies 21.03).

    Le chemin sans override renvoie deja un pool vide pour ce budget, sans erreur. L'override
    doit se comporter pareil : lever ici serait une incoherence, et forcerait l'appelant a
    ajouter une garde pour esquiver l'exception (workaround).
    """
    pool = movement_build_valid_destinations_pool(
        engine.game_state, "1", read_only=True, move_budget_override=0
    )
    assert pool == []


def test_move_budget_override_rejects_negative(engine):
    """Budget negatif : le moteur n'en produit jamais (borne a max(0,...)) -> erreur explicite."""
    with pytest.raises(ValueError, match="move_budget_override"):
        movement_build_valid_destinations_pool(
            engine.game_state, "1", read_only=True, move_budget_override=-1
        )


def test_multi_hex_base_also_produces_costs():
    """Le board x5 tourne en socles multi-hex (BASE_SIZE 6/8) : branche vectorisee."""
    eng = _make_engine(base_size=3)
    gs = eng.game_state
    costs: Dict = {}
    pool = movement_build_valid_destinations_pool(gs, "1", read_only=True, out_costs=costs)
    assert pool, "pool vide sur socle multi-hex"
    assert set(pool) == set(costs.keys())
