"""Tests de contrat — game_state produit par W40KEngine.__init__ réel.

Objectif : détecter les dérives entre les helpers manuels des tests
(_make_gs / _make_game_state) et le vrai game_state construit par __init__.
Si une clé obligatoire est ajoutée dans __init__ et que les helpers ne la
reproduisent pas, ces tests échouent.

Stratégie : instancier un W40KEngine avec config minimale réelle et vérifier
que les clés critiques sont présentes et du bon type dans game_state.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import numpy as np
import pytest

from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Config minimale réelle
# ─────────────────────────────────────────────────────────────────────────────

def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
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
        "RNG_WEAPONS": [_weapon_cfg()],
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
    }


def _minimal_config() -> Dict[str, Any]:
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
                "inches_to_subhex": 1,
            }
        },
        # Objectifs : source unique = terrains "objective": true, passés via 'scenario_objectives'
        # (canal config du nouveau système ; ex-board.objectives supprimé).
        "scenario_objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[5, 5]]}],
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "pve_mode": False,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [
            _unit_cfg(1, 1, 3, 3),
            _unit_cfg(2, 2, 10, 10),
        ],
    }


@pytest.fixture(scope="module")
def engine():
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}), \
         patch.object(W40KEngine, "_build_observation", return_value=np.zeros(50)):
        eng = W40KEngine(config=_minimal_config())
    return eng


# ─────────────────────────────────────────────────────────────────────────────
# Clés scalaires critiques
# ─────────────────────────────────────────────────────────────────────────────

class TestGameStateScalarKeys:

    def test_current_player_present_and_int(self, engine):
        """gs_current_player : current_player présent et entier."""
        gs = engine.game_state
        assert "current_player" in gs
        assert isinstance(gs["current_player"], int)

    def test_phase_present_and_str(self, engine):
        """gs_phase : phase présente et string."""
        gs = engine.game_state
        assert "phase" in gs
        assert isinstance(gs["phase"], str)

    def test_turn_present_and_int(self, engine):
        """gs_turn : turn présent et entier."""
        gs = engine.game_state
        assert "turn" in gs
        assert isinstance(gs["turn"], int)

    def test_game_over_present_and_bool(self, engine):
        """gs_game_over : game_over présent et bool."""
        gs = engine.game_state
        assert "game_over" in gs
        assert isinstance(gs["game_over"], bool)

    def test_winner_present_and_none_initially(self, engine):
        """gs_winner_none : winner est None au début de la partie."""
        assert engine.game_state.get("winner") is None

    def test_board_cols_rows_present(self, engine):
        """gs_board_dims : board_cols et board_rows présents et entiers."""
        gs = engine.game_state
        assert "board_cols" in gs and isinstance(gs["board_cols"], int)
        assert "board_rows" in gs and isinstance(gs["board_rows"], int)


# ─────────────────────────────────────────────────────────────────────────────
# Clés tracking sets
# ─────────────────────────────────────────────────────────────────────────────

class TestGameStateTrackingSets:

    _required_sets = [
        "units_moved",
        "units_fled",
        "units_cannot_charge",
        "units_shot",
        "units_charged",
        "units_attacked",
        "units_reacted_this_enemy_turn",
        "primary_objective_scored_turns",
    ]

    @pytest.mark.parametrize("key", _required_sets)
    def test_tracking_set_present_and_is_set(self, engine, key):
        """gs_tracking_set : clé de tracking est un set dans game_state."""
        assert key in engine.game_state, f"Clé manquante: {key}"
        assert isinstance(engine.game_state[key], set), (
            f"game_state['{key}'] attendu set, obtenu {type(engine.game_state[key]).__name__}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Clés pools d'activation
# ─────────────────────────────────────────────────────────────────────────────

class TestGameStateActivationPools:

    _required_pools = [
        "command_activation_pool",
        "move_activation_pool",
        "shoot_activation_pool",
        "charge_activation_pool",
        "charging_activation_pool",
        "active_alternating_activation_pool",
        "non_active_alternating_activation_pool",
    ]

    @pytest.mark.parametrize("key", _required_pools)
    def test_activation_pool_present_and_is_list(self, engine, key):
        """gs_activation_pool : pool d'activation est une liste dans game_state."""
        assert key in engine.game_state, f"Clé manquante: {key}"
        assert isinstance(engine.game_state[key], list), (
            f"game_state['{key}'] attendu list, obtenu {type(engine.game_state[key]).__name__}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Clés structures complexes
# ─────────────────────────────────────────────────────────────────────────────

class TestGameStateComplexKeys:

    def test_units_present_and_non_empty(self, engine):
        """gs_units : units présent et non-vide."""
        assert "units" in engine.game_state
        assert len(engine.game_state["units"]) > 0

    def test_victory_points_present_with_both_players(self, engine):
        """gs_vp : victory_points contient les joueurs 1 et 2."""
        vp = engine.game_state.get("victory_points")
        assert vp is not None
        assert 1 in vp and 2 in vp

    def test_objectives_present_and_non_empty(self, engine):
        """gs_objectives : objectives présent et non-vide."""
        objectives = engine.game_state.get("objectives")
        assert objectives is not None
        assert len(objectives) > 0

    def test_wall_hexes_present_and_is_set(self, engine):
        """gs_wall_hexes : wall_hexes présent et est un set."""
        assert "wall_hexes" in engine.game_state
        assert isinstance(engine.game_state["wall_hexes"], set)

    def test_units_cache_present_after_reset(self, engine, monkeypatch):
        """gs_units_cache : units_cache présent après reset()."""
        monkeypatch.setattr(engine, "_build_observation", lambda: np.zeros(50))
        from engine.reward_calculator import RewardCalculator
        monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
        engine.reset()
        assert "units_cache" in engine.game_state

    def test_config_embedded_in_game_state(self, engine):
        """gs_config_embedded : config embarqué dans game_state pour accès handlers."""
        assert "config" in engine.game_state
        assert isinstance(engine.game_state["config"], dict)

    def test_macro_target_objective_id_present(self, engine):
        """gs_macro_target : macro_target_objective_id initialisé depuis objectives[0]."""
        assert "macro_target_objective_id" in engine.game_state
        assert engine.game_state["macro_target_objective_id"] is not None
