"""Tests unitaires — W40KEngine.reset().

Vérifie que reset() remet correctement à zéro le game_state entre deux épisodes :
- turn=1, game_over=False, phase="move" (après cascade command→move)
- Sets de tracking vidés (units_moved, units_fled, units_shot, etc.)
- HP des unités restauré à HP_MAX
- Positions remises aux valeurs de la config
- episode_number incrémenté
- Pools d'activation vidés

Stratégie : créer un engine réel avec config minimale + 2 unités,
simuler un état mi-partie, puis appeler reset() et vérifier l'état.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.w40k_core import W40KEngine


@pytest.fixture(autouse=True)
def mock_build_obs(monkeypatch):
    """Mocke _build_observation pour tous les tests — on ne teste pas l'obs builder ici."""
    monkeypatch.setattr(W40KEngine, "_build_observation", lambda self: np.zeros(50))


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale avec 2 unités
# ─────────────────────────────────────────────────────────────────────────────

def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    """Config minimale d'unité pour W40KEngine.__init__."""
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "unitType": "TestUnit",
        "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3,
        "HP_MAX": 3,
        "MOVE": 6,
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 0,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [],
        "LD": 7,
        "OC": 1,
        "VALUE": 100,
        "ICON": "test",
        "ICON_SCALE": 1.0,
        "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round",
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
    }


def _minimal_config_with_units() -> Dict[str, Any]:
    """Config minimale valide avec 2 unités pour tester reset()."""
    obs_params = {
        "perception_radius": 25,
        "max_nearby_units": 10,
        "max_valid_targets": 5,
        "obs_size": 50,
        "action_space_size": 31,
    }
    return {
        "board": {
            "default": {
                "cols": 15,
                "rows": 13,
                "hex_radius": 1.0,
                "margin": 0.0,
                "wall_hexes": [],
                "objectives": [
                    {"id": "test_obj_1", "name": "Alpha", "hexes": [[5, 5]]}
                ],
                "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1,
            "engagement_zone_vertical": 5,
            "max_base_size_hex": 35,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {
            "observation_params": obs_params,
        },
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


def _make_engine() -> W40KEngine:
    """Crée un engine réel avec config minimale."""
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        return W40KEngine(config=_minimal_config_with_units())


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineResetBasicState:

    def test_reset_increments_episode_number(self):
        """reset_episode : episode_number incrémenté après reset()."""
        engine = _make_engine()
        episode_before = engine.episode_number

        engine.reset()

        assert engine.episode_number == episode_before + 1

    def test_reset_episode_number_reflected_in_game_state(self):
        """reset_episode_gs : game_state['episode_number'] == engine.episode_number après reset()."""
        engine = _make_engine()

        engine.reset()

        assert engine.game_state["episode_number"] == engine.episode_number

    def test_reset_clears_game_over_flag(self):
        """reset_game_over : game_over remis à False après reset()."""
        engine = _make_engine()
        engine.game_state["game_over"] = True
        engine.game_state["winner"] = 1

        engine.reset()

        assert engine.game_state["game_over"] is False

    def test_reset_clears_winner(self):
        """reset_winner : winner remis à None après reset()."""
        engine = _make_engine()
        engine.game_state["winner"] = 2

        engine.reset()

        assert engine.game_state["winner"] is None

    def test_reset_sets_turn_to_1(self):
        """reset_turn : turn remis à 1 après reset()."""
        engine = _make_engine()
        engine.game_state["turn"] = 5

        engine.reset()

        assert engine.game_state["turn"] == 1

    def test_reset_sets_current_player_to_1(self):
        """reset_player : current_player remis à 1 après reset()."""
        engine = _make_engine()
        engine.game_state["current_player"] = 2

        engine.reset()

        assert engine.game_state["current_player"] == 1


class TestEngineResetTrackingSets:

    def test_reset_clears_units_moved(self):
        """reset_units_moved : units_moved vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_moved"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_moved"] == set()

    def test_reset_clears_units_fled(self):
        """reset_units_fled : units_fled vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_fled"] = {"1"}

        engine.reset()

        assert engine.game_state["units_fled"] == set()

    def test_reset_clears_units_shot(self):
        """reset_units_shot : units_shot vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_shot"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_shot"] == set()

    def test_reset_clears_units_charged(self):
        """reset_units_charged : units_charged vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_charged"] = {"1"}

        engine.reset()

        assert engine.game_state["units_charged"] == set()

    def test_reset_clears_units_fought(self):
        """reset_units_fought : units_fought vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_fought"] = {"1", "2"}

        engine.reset()

        assert engine.game_state["units_fought"] == set()

    def test_reset_clears_units_advanced(self):
        """reset_units_advanced : units_advanced vidé après reset()."""
        engine = _make_engine()
        engine.game_state["units_advanced"] = {"1"}

        engine.reset()

        assert engine.game_state["units_advanced"] == set()


class TestEngineResetUnitState:

    def test_reset_restores_unit_hp_to_max(self):
        """reset_hp : HP_CUR de chaque unité restauré à HP_MAX."""
        engine = _make_engine()
        # Simuler dégâts
        for unit in engine.game_state["units"]:
            unit["HP_CUR"] = 1

        engine.reset()

        for unit in engine.game_state["units"]:
            assert unit["HP_CUR"] == unit["HP_MAX"]

    def test_reset_restores_unit_positions(self):
        """reset_pos : positions des unités remises aux valeurs de la config."""
        engine = _make_engine()
        # Simuler mouvement
        for unit in engine.game_state["units"]:
            unit["col"] = 1
            unit["row"] = 1

        engine.reset()

        # Les unités doivent retrouver leurs positions d'origine (config)
        cfg_positions = {str(u["id"]): (u["col"], u["row"]) for u in _minimal_config_with_units()["units"]}
        for unit in engine.game_state["units"]:
            uid = str(unit["id"])
            orig_col, orig_row = cfg_positions[uid]
            assert unit["col"] == orig_col
            assert unit["row"] == orig_row

    def test_reset_rebuilds_units_cache(self):
        """reset_cache : units_cache reconstruit après reset()."""
        engine = _make_engine()
        # Vider le cache manuellement
        engine.game_state["units_cache"] = {}

        engine.reset()

        # Cache doit être reconstruit avec les 2 unités
        assert len(engine.game_state["units_cache"]) == 2

    def test_reset_preserves_unit_list(self):
        """reset_units : la liste des unités est préservée après reset()."""
        engine = _make_engine()
        unit_ids_before = {str(u["id"]) for u in engine.game_state["units"]}

        engine.reset()

        unit_ids_after = {str(u["id"]) for u in engine.game_state["units"]}
        assert unit_ids_before == unit_ids_after


class TestEngineResetPools:

    def test_reset_clears_fight_subphase(self):
        """reset_fight_subphase : fight_subphase remis à None après reset()."""
        engine = _make_engine()
        engine.game_state["fight_subphase"] = "alternating_active"

        engine.reset()

        assert engine.game_state["fight_subphase"] is None

    def test_reset_clears_action_logs(self):
        """reset_action_logs : action_logs vidé après reset()."""
        engine = _make_engine()
        engine.game_state["action_logs"] = [{"type": "move", "message": "test"}]

        engine.reset()

        assert engine.game_state["action_logs"] == []
