"""T3 — decodage cellule -> destination -> execution (move_action_space_spatial_rework §7 T3).

Verrouille le contrat de bout en bout : le masque autorise une cellule, le decoder la traduit en
destination du POOL, le moteur l'execute. Aucune divergence possible : les deux couches lisent la
MEME carte (`store/read_squad_move_cell_map`).
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.shared_utils import (
    SQUAD_ACTION_MOVE_CELL_BASE,
    build_enemy_adjacent_hexes,
    build_squad_move_cell_map,
    clear_squad_move_cell_map,
    get_squad_move_budget,
    read_squad_move_cell_map,
    store_squad_move_cell_map,
)
from engine.w40k_core import W40KEngine

ANCHOR = (25, 25)


def _weapon_cfg() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _make_engine() -> W40KEngine:
    obs_params = {"perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
                  "obs_size": 108, "action_space_size": 1047}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "objectives": [], "inches_to_subhex": 1}},
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [_unit_cfg(1, 1, *ANCHOR), _unit_cfg(2, 2, 55, 55)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=config)
    eng.reset()
    eng.game_state["phase"] = "move"
    for p in (1, 2):
        build_enemy_adjacent_hexes(eng.game_state, p)
    return eng


@pytest.fixture
def engine():
    return _make_engine()


def _prime_mask(engine):
    """Simule le contrat : le masque est construit avant tout decodage."""
    return engine.action_decoder.get_squad_action_mask_and_eligible_units(engine.game_state)


# ---------------------------------------------------------------------------
# Cache de la carte : integrite
# ---------------------------------------------------------------------------

def test_mask_build_stores_the_cell_map(engine):
    _prime_mask(engine)
    assert read_squad_move_cell_map(engine.game_state, "1")


def test_decode_without_mask_raises_instead_of_rebuilding(engine):
    """Aucun fallback : reconstruire ici masquerait une rupture du contrat masque->decodage.

    Teste sur l'escouade adverse : le masque n'est construit que pour l'escouade ACTIVE, donc
    « 2 » n'a jamais de carte. (« 1 » en a une des le `reset()`, qui construit deja le masque —
    c'est precisement ce qui garantit le contrat masque->decodage dans la boucle gym.)
    """
    with pytest.raises(ValueError, match="aucune carte de cellules"):
        read_squad_move_cell_map(engine.game_state, "2")


def test_reset_primes_the_map_for_the_active_squad(engine):
    """Le contrat « masque avant decodage » est tenu par la boucle gym elle-meme."""
    assert read_squad_move_cell_map(engine.game_state, "1")


def test_stale_map_raises_instead_of_being_used(engine):
    """Carte construite depuis une autre ancre = mismatch masque/execution -> erreur explicite."""
    gs = engine.game_state
    _prime_mask(engine)
    # L'escouade bouge sans reconstruction du masque -> la carte designe d'autres hexes.
    gs["units_cache"]["1"]["col"] = ANCHOR[0] + 3
    with pytest.raises(ValueError, match="perimee"):
        read_squad_move_cell_map(gs, "1")


def test_stale_map_raises_on_phase_change(engine):
    gs = engine.game_state
    _prime_mask(engine)
    gs["phase"] = "shoot"
    with pytest.raises(ValueError, match="perimee"):
        read_squad_move_cell_map(gs, "1")


def test_clear_removes_the_map(engine):
    _prime_mask(engine)
    clear_squad_move_cell_map(engine.game_state, "1")
    with pytest.raises(ValueError, match="aucune carte"):
        read_squad_move_cell_map(engine.game_state, "1")


def test_reset_purges_the_cell_maps(engine):
    """`game_state` est le MEME objet d'un reset a l'autre : sans purge, une carte survit.

    Le tampon (ancre, phase) NE protege PAS entre episodes : l'escouade peut se redeployer sur la
    meme ancre en phase move, le tampon coincide, et une carte calculee sur les murs d'un AUTRE
    scenario passerait le controle. Meme piege que le cache de terrain de T1.

    Teste sur « 2 » : `reset()` reconstruit le masque de l'escouade ACTIVE, donc sa carte a elle
    est legitimement recreee (fraiche) — c'est la carte d'une escouade NON re-masquee qui
    survivrait en silence.
    """
    gs = engine.game_state
    _prime_mask(engine)
    gs["_squad_move_cell_maps"]["2"] = {"anchor": (0, 0), "phase": "move", "map": {}}
    engine.reset()
    assert "2" not in engine.game_state.get("_squad_move_cell_maps", {}), "carte non purgee au reset"


def test_reset_purges_the_prerolled_advance_rolls(engine):
    """Un jet survivant ne serait JAMAIS re-tire : le decoder ne roule que si la cle est absente.

    Un episode interrompu (turn limit avec une activation en cours) laisserait donc l'escouade
    trainer le jet de l'episode precedent (09.06 : un jet par Advance).
    """
    gs = engine.game_state
    _prime_mask(engine)
    gs["_squad_advance_rolls"]["2"] = 6
    engine.reset()
    assert "2" not in engine.game_state.get("_squad_advance_rolls", {}), "jet non purge au reset"


# ---------------------------------------------------------------------------
# Decodage
# ---------------------------------------------------------------------------

def test_decode_cell_yields_a_pool_destination_not_a_direction(engine):
    """La destination vient du POOL. L'ancien decodeur renvoyait `direction` (hex adjacent)."""
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    cell_idx = sorted(cell_map.keys())[len(cell_map) // 2]
    expected_dest, _cost = cell_map[cell_idx]

    semantic = engine.action_decoder.convert_squad_action(
        SQUAD_ACTION_MOVE_CELL_BASE + cell_idx, gs
    )
    assert "direction" not in semantic, "le decodeur ne doit plus produire de direction"
    assert (semantic["destCol"], semantic["destRow"]) == expected_dest


def test_decode_infers_move_type_from_cost(engine):
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")

    seen = set()
    for cell_idx, (_dest, cost) in cell_map.items():
        semantic = engine.action_decoder.convert_squad_action(
            SQUAD_ACTION_MOVE_CELL_BASE + cell_idx, gs
        )
        expected = "squad_normal_move" if cost <= normal_budget else "squad_advance"
        assert semantic["action"] == expected
        seen.add(semantic["action"])
    assert seen == {"squad_normal_move", "squad_advance"}, "les 2 regimes doivent apparaitre"


def test_decoded_advance_carries_the_prerolled_roll(engine):
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")
    adv_cell = next(i for i, (_d, c) in cell_map.items() if c > normal_budget)

    semantic = engine.action_decoder.convert_squad_action(SQUAD_ACTION_MOVE_CELL_BASE + adv_cell, gs)
    assert semantic["action"] == "squad_advance"
    assert semantic["advance_roll"] == gs["_squad_advance_rolls"]["1"]


def test_decode_unmasked_cell_raises(engine):
    """Une cellule hors masque n'a pas de destination : erreur explicite, pas de repli."""
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    unplayable = next(i for i in range(1024) if i not in cell_map)
    with pytest.raises(ValueError, match="injouable"):
        engine.action_decoder.convert_squad_action(SQUAD_ACTION_MOVE_CELL_BASE + unplayable, gs)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def test_execute_moves_the_squad_to_the_pool_destination(engine):
    """LE test de la refonte : l'escouade parcourt vraiment la distance visee (root cause §3)."""
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    # La cellule la plus lointaine jouable.
    cell_idx = max(cell_map, key=lambda i: calculate_hex_distance(*ANCHOR, *cell_map[i][0]))
    dest, _cost = cell_map[cell_idx]
    distance = calculate_hex_distance(*ANCHOR, *dest)
    assert distance > 1, "fixture : il faut une destination lointaine"

    success, _result = engine._process_squad_action(
        engine.action_decoder.convert_squad_action(SQUAD_ACTION_MOVE_CELL_BASE + cell_idx, gs)
    )
    assert success
    from engine.phase_handlers.shared_utils import require_unit_position
    assert require_unit_position("1", gs) == dest
    # Avant la refonte, l'escouade n'aurait bouge que d'1 subhex.
    assert calculate_hex_distance(*ANCHOR, *require_unit_position("1", gs)) == distance


def test_execute_clears_the_map_and_the_roll(engine):
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    cell_idx = sorted(cell_map.keys())[0]
    engine._process_squad_action(
        engine.action_decoder.convert_squad_action(SQUAD_ACTION_MOVE_CELL_BASE + cell_idx, gs)
    )
    assert "1" not in gs.get("_squad_advance_rolls", {})
    with pytest.raises(ValueError, match="aucune carte"):
        read_squad_move_cell_map(gs, "1")


def test_executed_advance_records_the_authoritative_roll(engine):
    """§4.3 de bout en bout : un advance decode+execute alimente `advance_rolls`."""
    gs = engine.game_state
    _prime_mask(engine)
    cell_map = read_squad_move_cell_map(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")
    adv_cell = next(i for i, (_d, c) in cell_map.items() if c > normal_budget)
    roll = gs["_squad_advance_rolls"]["1"]

    engine._process_squad_action(
        engine.action_decoder.convert_squad_action(SQUAD_ACTION_MOVE_CELL_BASE + adv_cell, gs)
    )
    assert "1" in gs["units_advanced"]
    assert gs["advance_rolls"]["1"] == roll
