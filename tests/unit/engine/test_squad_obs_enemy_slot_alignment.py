"""D1 — alignement des slots ennemis observation <-> action, et flag FALL BACK (obs[19]).

Audit V11 (Documentation/Archives/chantiers/V11_audit_observation.md §5bis.2 D1) : l observation
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

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import unit_bin_index, unit_cont_index
from engine.phase_handlers.shared_utils import get_enemy_slot_mapping
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
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
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
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
        eng = W40KEngine(config=build_engine_config(_config()))
    eng.reset()
    return eng


def _enemy_slot_hp(obs, slot_i: int) -> float:
    """PV totaux BRUTS du slot ennemi i (tenseur d'entites, lu par NOM de feature)."""
    return float(obs["enemies_cont"][slot_i][unit_cont_index("hp_total")])


def _enemy_slot_mask(obs, slot_i: int) -> float:
    return float(obs["enemies_bin"][slot_i][unit_bin_index("present")])


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
            assert _enemy_slot_mask(obs, i) == 0.0  # slot_mask vide
            continue
        expected_hp = float(int(units_cache[esid]["HP_CUR"]))
        assert _enemy_slot_hp(obs, i) == pytest.approx(expected_hp), (
            f"slot {i} desaligne : obs decrit HP {_enemy_slot_hp(obs, i):.0f}, "
            f"mapping attend {esid} (HP {units_cache[esid]['HP_CUR']})"
        )


_BIN_FALL_BACK = unit_bin_index("fled")


def test_fall_back_flag(engine):
    """Le flag FALL BACK de l'unite active suit `units_fled`, pas les PV."""
    gs = engine.game_state
    gs.setdefault("units_fled", set()).discard("1")
    obs_no = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs_no["allies_bin"][0][_BIN_FALL_BACK] == 0.0

    gs.setdefault("units_fled", set()).add("1")
    obs_yes = engine.obs_builder.build_squad_observation(gs, "1")
    assert obs_yes["allies_bin"][0][_BIN_FALL_BACK] == 1.0
    # La valeur ne depend plus des PV (0->1 a PV constants) : les deux assertions le prouvent.


def test_model_can_fight_target_returns_false_for_offbattlefield(engine):
    """_model_can_fight_target retourne False sans crasher pour une cible hors table.

    Regression : une escouade en reserves strategiques (col=-1) apparait dans le slot mapping
    ennemi (intentionnel, bit deploy_not_on_board). Lors du check fight eligibility post-overrun,
    _model_can_fight_target la recevait et appelait entries_in_engagement_zone avec la sentinelle
    (-1,-1), provoquant un ValueError.
    """
    from engine.phase_handlers.fight_handlers import _model_can_fight_target

    gs = engine.game_state
    # Mettre l'escouade "2" hors table (sentinelle = reserves strategiques)
    gs["units_cache"]["2"]["col"] = -1
    gs["units_cache"]["2"]["row"] = -1

    # Attaquant : premier modele de l'escouade "1"
    attacker_mid = gs["squad_models"]["1"][0]
    attacker_model = gs["models_cache"][attacker_mid]

    # Avant le fix : crash ValueError dans entries_in_engagement_zone
    result = _model_can_fight_target(gs, attacker_model, "1", "2")
    assert result is False, "une cible hors table ne peut pas etre engagee en melee"
