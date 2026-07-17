"""Masque spatial de la phase de move (§7 T2) — remplace les 18 dry-runs directionnels.

Spec : Documentation/Implementation/A_faire/move_action_space_spatial_rework.md §3 / §6.2 / §7 T2.

Root cause §3 : une action de move designait l'hex ADJACENT (direction 0-5), donc l'escouade
avancait d'1 subhex par phase = 1/25e de son budget sur un board x5. Ces tests verrouillent le
fait que l'agent vise desormais tout le disque atteignable.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine.combat_utils import calculate_hex_distance
from engine.phase_handlers.shared_utils import (
    SQUAD_ACTION_MOVE_CELL_BASE,
    SQUAD_ACTION_MOVE_CELL_COUNT,
    SQUAD_ACTION_SIZE,
    SQUAD_ACTION_WAIT,
    build_enemy_adjacent_hexes,
    build_squad_action_mask,
    build_squad_move_cell_map,
    get_squad_move_budget,
    infer_squad_move_type,
)
from engine.w40k_core import W40KEngine

ANCHOR = (25, 25)
ADVANCE_ROLL = 4


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


def _make_engine(enemy_at=(55, 55), walls=None) -> W40KEngine:
    obs_params = {"perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
                  "obs_size": 108, "action_space_size": 1047}
    config = {
        "board": {"default": {"cols": 60, "rows": 60, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": walls or [], "objectives": [], "inches_to_subhex": 1}},
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
        "units": [_unit_cfg(1, 1, *ANCHOR), _unit_cfg(2, 2, *enemy_at)],
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


def test_mask_has_the_spatial_size(engine):
    mask = build_squad_action_mask(engine.game_state, "1", None, ADVANCE_ROLL)
    assert len(mask) == SQUAD_ACTION_SIZE == 1032


def test_root_cause_is_dead_agent_reaches_far_beyond_one_subhex(engine):
    """LE test de la refonte : l'agent vise tout son budget, plus 1 subhex (root cause §3)."""
    gs = engine.game_state
    cell_map = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)
    assert cell_map, "aucune destination jouable"

    distances = [calculate_hex_distance(*ANCHOR, d[0], d[1]) for d, _ in cell_map.values()]
    normal_budget = get_squad_move_budget("1", gs, "normal")

    assert max(distances) > 1, "l'escouade ne peut toujours atteindre que l'hex adjacent"
    assert max(distances) >= normal_budget, (
        f"portee max {max(distances)} < budget normal {normal_budget} : "
        f"l'agent n'exploite pas son budget"
    )
    # Avant la refonte : 6 destinations, toutes a distance 1.
    assert len(cell_map) > 6


def test_mask_bits_match_the_cell_map_exactly(engine):
    """Masque et decodage lisent la MEME source : aucun mismatch possible (§7 T2)."""
    gs = engine.game_state
    mask = build_squad_action_mask(gs, "1", None, ADVANCE_ROLL)
    cell_map = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)

    masked = {i for i in range(SQUAD_ACTION_MOVE_CELL_COUNT)
              if mask[SQUAD_ACTION_MOVE_CELL_BASE + i]}
    assert masked == set(cell_map.keys())


def test_wait_is_always_available_in_move_phase(engine):
    """09.04 Remain Stationary reste couvert par WAIT (§4.6)."""
    mask = build_squad_action_mask(engine.game_state, "1", None, ADVANCE_ROLL)
    assert mask[SQUAD_ACTION_WAIT] == 1


def test_advance_roll_none_yields_only_normal_cells(engine):
    """Sans jet, le budget Advance est inconnu -> aucune cellule Advance (semantique d'origine)."""
    gs = engine.game_state
    normal_budget = get_squad_move_budget("1", gs, "normal")
    cell_map = build_squad_move_cell_map(gs, "1", None)
    assert cell_map
    for _dest, cost in cell_map.values():
        assert cost <= normal_budget


def test_advance_roll_widens_the_playable_cells(engine):
    gs = engine.game_state
    without = build_squad_move_cell_map(gs, "1", None)
    with_roll = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)
    assert len(with_roll) > len(without)


def test_already_moved_squad_has_no_move_cell(engine):
    gs = engine.game_state
    gs.setdefault("units_moved", set()).add("1")
    mask = build_squad_action_mask(gs, "1", None, ADVANCE_ROLL)
    assert sum(mask[SQUAD_ACTION_MOVE_CELL_BASE:SQUAD_ACTION_MOVE_CELL_COUNT]) == 0
    assert mask[SQUAD_ACTION_WAIT] == 1


def test_advanced_squad_keeps_normal_cells_but_loses_advance_cells(engine):
    """Miroir EXACT des gardes d'origine : has_advanced fermait Advance, PAS le Normal."""
    gs = engine.game_state
    normal_budget = get_squad_move_budget("1", gs, "normal")
    gs.setdefault("units_advanced", set()).add("1")

    mask = build_squad_action_mask(gs, "1", None, ADVANCE_ROLL)
    cell_map_full = build_squad_move_cell_map(gs, "1", ADVANCE_ROLL)
    masked = {i for i in range(SQUAD_ACTION_MOVE_CELL_COUNT)
              if mask[SQUAD_ACTION_MOVE_CELL_BASE + i]}
    assert masked, "le Normal doit rester jouable"
    for idx in masked:
        assert cell_map_full[idx][1] <= normal_budget, "une cellule Advance a survecu"


# ---------------------------------------------------------------------------
# Inference du type de move (§6.2)
# ---------------------------------------------------------------------------

def test_move_type_inferred_from_geodesic_cost(engine):
    gs = engine.game_state
    normal_budget = get_squad_move_budget("1", gs, "normal")
    assert infer_squad_move_type(gs, "1", 1.0) == "normal"
    assert infer_squad_move_type(gs, "1", float(normal_budget)) == "normal"
    assert infer_squad_move_type(gs, "1", normal_budget + 1.0) == "advance"


def test_engaged_squad_infers_fall_back():
    """09.05 : Normal exige unengaged -> engagee, seul le Fall Back existe."""
    eng = _make_engine(enemy_at=(26, 25))  # ennemi adjacent -> engagement
    gs = eng.game_state
    from engine.phase_handlers.shared_utils import _squad_is_in_enemy_er
    assert _squad_is_in_enemy_er(gs, "1"), "fixture : l'escouade doit etre engagee"
    assert infer_squad_move_type(gs, "1", 1.0) == "fall_back"
    assert infer_squad_move_type(gs, "1", 999.0) == "fall_back"


def test_every_masked_cell_infers_a_move_type(engine):
    """Aucune cellule jouable ne doit rester sans type executable."""
    gs = engine.game_state
    for _dest, cost in build_squad_move_cell_map(gs, "1", ADVANCE_ROLL).values():
        assert infer_squad_move_type(gs, "1", cost) in ("normal", "advance", "fall_back")


def test_pure_rule_and_context_resolver_never_diverge(engine):
    """`infer_squad_move_type` n'est qu'un resolveur de contexte au-dessus de la regle pure.

    La regle est extraite pour que le masque puisse hisser ses invariants hors de la boucle des
    ~1000 cellules (48% du cout du masque sinon). Ce test garantit que l'extraction n'a pas cree
    une 2e implementation qui pourrait deriver de la premiere.
    """
    from engine.phase_handlers.shared_utils import _squad_is_in_enemy_er, classify_squad_move_type

    gs = engine.game_state
    in_er = _squad_is_in_enemy_er(gs, "1")
    normal_budget = get_squad_move_budget("1", gs, "normal")

    for cost in (0.5, 1.0, normal_budget - 1, normal_budget, normal_budget + 0.001,
                 normal_budget + 1, normal_budget * 3):
        assert classify_squad_move_type(in_er, normal_budget, cost) == infer_squad_move_type(gs, "1", cost)


def test_pure_rule_boundaries(engine):
    """La borne est INCLUSIVE : un move d'exactement M reste un Normal (09.05 : max = M)."""
    from engine.phase_handlers.shared_utils import classify_squad_move_type

    assert classify_squad_move_type(False, 30, 30.0) == "normal"
    assert classify_squad_move_type(False, 30, 30.0001) == "advance"
    # Engagee : le cout n'entre plus en jeu, seul le Fall Back existe (09.05).
    assert classify_squad_move_type(True, 30, 1.0) == "fall_back"
    assert classify_squad_move_type(True, 30, 999.0) == "fall_back"
