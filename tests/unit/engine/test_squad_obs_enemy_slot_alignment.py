"""D1 — alignement des slots ennemis observation <-> action, et flag FALL BACK (obs[19]).

Audit V11 (Documentation/Implementation/V11_audit_observation.md §5bis.2 D1) : l observation
rangeait les 5 slots ennemis par ordre alphabetique de squad_id, alors que l action tir/charge
les range par menace HP*OC (`get_enemy_slot_mapping`). Consequence : « tirer slot i » visait un
AUTRE ennemi que celui decrit par obs-slot-i -> choix de cible brouille.

Le fixture est construit pour que l ordre par menace DIFFERE de l ordre alphabetique (contre-
epreuve integree : sous l ancien code trie par str(sid), l assertion d alignement rougit).
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engine.phase_handlers.shared_utils import get_enemy_slot_mapping
from engine.w40k_core import W40KEngine


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int, hp: int, oc: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": hp, "HP_MAX": hp, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": oc, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


# Ennemis concus pour que ordre-menace (HP*OC) != ordre-alphabetique(str id) :
#   id "2"  : HP 3, OC 1 -> menace 3
#   id "10" : HP 9, OC 2 -> menace 18   (HP distinct = 0.3 en obs)
#   id "3"  : HP 6, OC 1 -> menace 6
# str(sid) trie : ["10","2","3"]           -> [10, 2, 3]
# menace desc   : 18(10) > 6(3) > 3(2)     -> [10, 3, 2]   (DIFFERE au slot 1 et 2)
def _config() -> Dict[str, Any]:
    obs_params = {
        "perception_radius": 25, "max_nearby_units": 10, "max_valid_targets": 5,
        "obs_size": 108, "action_space_size": 1047,
    }
    return {
        "board": {
            "default": {
                "cols": 80, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "objectives": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, 20, 20, hp=3, oc=1),   # escouade active (joueur 1)
            _unit_cfg(2, 2, 30, 20, hp=3, oc=1),
            _unit_cfg(10, 2, 34, 20, hp=9, oc=2),
            _unit_cfg(3, 2, 38, 20, hp=6, oc=1),
        ],
    }


@pytest.fixture
def engine():
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=_config())
    eng.reset()
    return eng


def _enemy_slot_hp(obs, slot_i: int) -> float:
    # obs[base+1] = min(1, HP_total/30) ; base = 63 + slot*9
    return float(obs[63 + slot_i * 9 + 1])


def test_fixture_threat_order_differs_from_alpha_order(engine):
    """Garantit que le test MORD : ordre-menace != ordre-alphabetique dans ce fixture."""
    gs = engine.game_state
    mapping = get_enemy_slot_mapping(gs, 1)
    alpha = sorted(
        (sid for sid, e in gs["units_cache"].items() if int(e["player"]) != 1),
        key=lambda s: str(s),
    )
    assert [m for m in mapping if m is not None] != alpha


def test_obs_enemy_slots_follow_action_mapping(engine):
    """D1 : chaque slot ennemi de l obs decrit l ennemi du MEME slot d action."""
    gs = engine.game_state
    mapping = get_enemy_slot_mapping(gs, 1)
    obs = engine.obs_builder.build_squad_observation(gs, "1")
    units_cache = gs["units_cache"]
    for i, esid in enumerate(mapping):
        if esid is None:
            assert obs[63 + i * 9 + 5] == 0.0  # slot_mask vide
            continue
        expected_hp = min(1.0, int(units_cache[esid]["HP_CUR"]) / 30.0)
        assert _enemy_slot_hp(obs, i) == pytest.approx(expected_hp), (
            f"slot {i} desaligne : obs decrit HP {_enemy_slot_hp(obs, i)*30:.0f}, "
            f"mapping attend {esid} (HP {units_cache[esid]['HP_CUR']})"
        )


def test_fall_back_flag_obs19(engine):
    """obs[19] = flag FALL BACK (ex-doublon HP%), source `units_fled`."""
    gs = engine.game_state
    gs.setdefault("units_fled", set()).discard("1")
    obs_no = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs_no[19] == 0.0

    gs.setdefault("units_fled", set()).add("1")
    obs_yes = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs_yes[19] == 1.0
    # obs[19] suit desormais `units_fled` (0->1 selon le repli), plus HP% : les deux
    # assertions ci-dessus le prouvent (la valeur ne depend plus des PV).
