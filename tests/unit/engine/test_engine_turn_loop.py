"""Orchestration de tour W40KEngine — _check_game_over, _advance_to_next_player, determine_winner."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.w40k_core import W40KEngine
from engine.game_state import GameStateManager
from engine.phase_handlers.shared_utils import build_units_cache


# ─────────────────────────────────────────────────────────────────────────────
# Helpers : créer une instance minimale de W40KEngine sans appeler __init__
# ─────────────────────────────────────────────────────────────────────────────

def _bare_engine(game_state: Dict[str, Any]) -> W40KEngine:
    """Instancie W40KEngine sans __init__ et injecte un game_state minimal."""
    engine = object.__new__(W40KEngine)
    engine.game_state = game_state
    engine._shooting_phase_initialized = False
    return engine


def _minimal_gs(
    current_player: int = 1,
    phase: str = "fight",
    turn: int = 1,
) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": phase,
        "turn": turn,
        "turn_limit_reached": False,
        "game_over": False,
        "wall_hexes": set(),
        "units": [],
        "unit_by_id": {},
        "units_reacted_this_enemy_turn": set(),
        "reactive_macro_order_current_window": [],
        "reaction_window_active": False,
        "reactive_decision_payload": {},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "units_moved": set(),
        "units_fled": set(),
        "units_cannot_charge": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_attacked": set(),
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "hex_los_cache": {},
        "los_cache": {},
        "gym_training_mode": True,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# _check_game_over
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckGameOver:

    def test_no_training_config_and_flag_false_returns_false(self):
        """game_over_false : pas de training_config + turn_limit_reached=False → False."""
        gs = _minimal_gs(turn=1)
        engine = _bare_engine(gs)
        assert engine._check_game_over() is False

    def test_turn_below_limit_returns_false(self):
        """game_over_below_limit : turn=3, max_turns=5 → False."""
        gs = _minimal_gs(turn=3)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 5}
        assert engine._check_game_over() is False

    def test_turn_equals_limit_not_over(self):
        """game_over_eq_limit : turn=5, max_turns=5 → False (condition strictement supérieur)."""
        gs = _minimal_gs(turn=5)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 5}
        assert engine._check_game_over() is False

    def test_turn_exceeds_limit_returns_true(self):
        """game_over_exceeded : turn=6 > max_turns=5 → True et turn_limit_reached mis à True."""
        gs = _minimal_gs(turn=6)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 5}
        result = engine._check_game_over()
        assert result is True
        assert gs["turn_limit_reached"] is True

    def test_turn_limit_reached_flag_forces_game_over(self):
        """game_over_flag : turn_limit_reached=True → True même sans training_config."""
        gs = _minimal_gs(turn=1)
        gs["turn_limit_reached"] = True
        engine = _bare_engine(gs)
        assert engine._check_game_over() is True


# ─────────────────────────────────────────────────────────────────────────────
# _advance_to_next_player
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvanceToNextPlayer:

    def test_player1_switches_to_player2(self):
        """advance_p1_to_p2 : current_player=1 → 2 après _advance_to_next_player."""
        gs = _minimal_gs(current_player=1, phase="fight")
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["current_player"] == 2

    def test_player2_switches_to_player1_and_increments_turn(self):
        """advance_p2_to_p1 : current_player=2 → 1, turn incrémenté."""
        gs = _minimal_gs(current_player=2, phase="fight", turn=1)
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["current_player"] == 1
        assert gs["turn"] == 2

    def test_reactive_state_reset_after_switch(self):
        """advance_reactive_reset : units_reacted_this_enemy_turn vidé après switch."""
        gs = _minimal_gs(current_player=1, phase="fight")
        gs["units_reacted_this_enemy_turn"] = {"5", "6"}
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["units_reacted_this_enemy_turn"] == set()

    def test_player2_turn_limit_reached_sets_game_over(self):
        """advance_turn_limit : p2→p1 dépasse max_turns → game_over=True."""
        gs = _minimal_gs(current_player=2, phase="fight", turn=5)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 5}
        engine._advance_to_next_player()
        # turn devient 6 > max_turns=5 → game_over
        assert gs["game_over"] is True


# ─────────────────────────────────────────────────────────────────────────────
# GameStateManager.determine_winner
# ─────────────────────────────────────────────────────────────────────────────

def _unit_entry(uid: int, player: int, hp: int = 3, value: int = 100) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": 5,
        "row": 5,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": value,
        "OC": 1,
        "BASE_SIZE": 1,
        "MODEL_HEIGHT": 2.5,
        "BASE_SHAPE": "round",
        "MOVE": 6,
        "UNIT_RULES": [],
        "T": 4,
        "ARMOR_SAVE": 4,
        "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1,
        "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [],
        "CC_WEAPONS": [],
    }


def _make_gs_for_winner(
    p1_vp: int = 0,
    p2_vp: int = 0,
    p1_units: int = 1,
    p2_units: int = 1,
    p1_unit_value: int = 100,
    p2_unit_value: int = 100,
    turn_limit_reached: bool = True,
) -> Dict[str, Any]:
    config = {
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
    }
    units = []
    uid = 1
    for _ in range(p1_units):
        units.append(_unit_entry(uid, 1, value=p1_unit_value))
        uid += 1
    for _ in range(p2_units):
        units.append(_unit_entry(uid, 2, value=p2_unit_value))
        uid += 1

    gs: Dict[str, Any] = {
        "config": config,
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "turn_limit_reached": turn_limit_reached,
        "victory_points": {1: p1_vp, 2: p2_vp},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 5,
    }
    build_units_cache(gs)
    return gs


class TestDetermineWinner:

    def _mgr(self) -> GameStateManager:
        return GameStateManager(config={
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        })

    def test_game_not_over_returns_none(self):
        """winner_ongoing : turn_limit_reached=False → None (partie en cours)."""
        gs = _make_gs_for_winner(p1_vp=5, p2_vp=3, turn_limit_reached=False)
        assert self._mgr().determine_winner(gs) is None

    def test_p1_more_vp_wins(self):
        """winner_p1_vp : p1 a plus de VP → gagnant=1."""
        gs = _make_gs_for_winner(p1_vp=5, p2_vp=3)
        assert self._mgr().determine_winner(gs) == 1

    def test_p2_more_vp_wins(self):
        """winner_p2_vp : p2 a plus de VP → gagnant=2."""
        gs = _make_gs_for_winner(p1_vp=2, p2_vp=4)
        assert self._mgr().determine_winner(gs) == 2

    def test_tie_vp_p1_more_value_wins(self):
        """winner_tiebreak_value : VP égaux, p1 a plus de valeur unités → gagnant=1."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_unit_value=200, p2_unit_value=100)
        assert self._mgr().determine_winner(gs) == 1

    def test_tie_vp_p2_more_value_wins(self):
        """winner_tiebreak_p2 : VP égaux, p2 a plus de valeur unités → gagnant=2."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_unit_value=100, p2_unit_value=200)
        assert self._mgr().determine_winner(gs) == 2

    def test_equal_vp_equal_value_draw(self):
        """winner_draw : VP et valeur identiques → draw=-1."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_unit_value=100, p2_unit_value=100)
        assert self._mgr().determine_winner(gs) == -1


# ─────────────────────────────────────────────────────────────────────────────
# GameStateManager.determine_winner_with_method
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinnerWithMethod:

    def _mgr(self) -> GameStateManager:
        return GameStateManager(config={
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        })

    def test_game_not_over_returns_none_none(self):
        """winner_method_ongoing : partie en cours → (None, None)."""
        gs = _make_gs_for_winner(p1_vp=5, p2_vp=3, turn_limit_reached=False)
        winner, method = self._mgr().determine_winner_with_method(gs)
        assert winner is None
        assert method is None

    def test_p1_wins_by_objectives(self):
        """winner_method_objectives : p1 plus de VP → method='objectives'."""
        gs = _make_gs_for_winner(p1_vp=5, p2_vp=3)
        winner, method = self._mgr().determine_winner_with_method(gs)
        assert winner == 1
        assert method == "objectives"

    def test_p2_wins_by_objectives(self):
        """winner_method_p2_objectives : p2 plus de VP → gagnant=2, method='objectives'."""
        gs = _make_gs_for_winner(p1_vp=1, p2_vp=3)
        winner, method = self._mgr().determine_winner_with_method(gs)
        assert winner == 2
        assert method == "objectives"

    def test_tiebreak_by_value_method(self):
        """winner_method_value : VP égaux, p1 plus de valeur → method='value_tiebreaker'."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_unit_value=200, p2_unit_value=100)
        winner, method = self._mgr().determine_winner_with_method(gs)
        assert winner == 1
        assert method == "value_tiebreaker"

    def test_draw_method(self):
        """winner_method_draw : égalité parfaite → method='draw'."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_unit_value=100, p2_unit_value=100)
        winner, method = self._mgr().determine_winner_with_method(gs)
        assert winner == -1
        assert method == "draw"


# ─────────────────────────────────────────────────────────────────────────────
# _check_game_over — cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckGameOverEdgeCases:

    def test_training_config_no_max_turns_key_not_over(self):
        """game_over_no_max_key : training_config sans max_turns_per_episode → False."""
        gs = _minimal_gs(turn=100)
        engine = _bare_engine(gs)
        engine.training_config = {}  # pas de max_turns_per_episode
        assert engine._check_game_over() is False

    def test_training_config_max_turns_zero_not_over(self):
        """game_over_max_zero : max_turns=0 (falsy) → False (condition `if max_turns`)."""
        gs = _minimal_gs(turn=10)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 0}
        assert engine._check_game_over() is False

    def test_sets_turn_limit_reached_in_state(self):
        """game_over_sets_flag : _check_game_over() met turn_limit_reached=True dans game_state."""
        gs = _minimal_gs(turn=6)
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 5}
        engine._check_game_over()
        assert gs["turn_limit_reached"] is True


# ─────────────────────────────────────────────────────────────────────────────
# _advance_to_next_player — cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvanceToNextPlayerEdgeCases:

    def test_reaction_window_reset_to_false(self):
        """advance_reaction_window : reaction_window_active remis à False."""
        gs = _minimal_gs(current_player=1, phase="fight")
        gs["reaction_window_active"] = True
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["reaction_window_active"] is False

    def test_reactive_payload_cleared(self):
        """advance_payload_cleared : reactive_decision_payload vidé."""
        gs = _minimal_gs(current_player=1, phase="fight")
        gs["reactive_decision_payload"] = {"unit_1": {"action": "reactive_move"}}
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["reactive_decision_payload"] == {}

    def test_turn_not_incremented_when_p1_to_p2(self):
        """advance_turn_no_increment : p1→p2 n'incrémente pas le tour."""
        gs = _minimal_gs(current_player=1, phase="fight", turn=3)
        engine = _bare_engine(gs)
        engine._advance_to_next_player()
        assert gs["turn"] == 3  # inchangé

    def test_shooting_phase_initialized_reset(self):
        """advance_shoot_init_reset : _shooting_phase_initialized remis à False."""
        gs = _minimal_gs(current_player=1, phase="fight")
        engine = _bare_engine(gs)
        engine._shooting_phase_initialized = True
        engine._advance_to_next_player()
        assert engine._shooting_phase_initialized is False


# ─────────────────────────────────────────────────────────────────────────────
# GameStateManager — _check_game_over avec turn_limit_reached déjà True
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckGameOverFlagInteractions:

    def test_flag_already_true_ignores_training_config(self):
        """game_over_flag_priority : turn_limit_reached=True écrase training_config."""
        gs = _minimal_gs(turn=1)
        gs["turn_limit_reached"] = True
        engine = _bare_engine(gs)
        engine.training_config = {"max_turns_per_episode": 100}  # turn bien en dessous
        # La flag force game_over même si turn < max_turns
        assert engine._check_game_over() is True

    def test_no_training_config_attribute_but_flag_false_returns_false(self):
        """game_over_no_attr : pas d'attribut training_config + flag=False → False."""
        gs = _minimal_gs(turn=50)
        engine = _bare_engine(gs)
        # Pas de training_config → hasattr returns False → vérifie turn_limit_reached
        assert not hasattr(engine, "training_config")
        assert engine._check_game_over() is False


# ─────────────────────────────────────────────────────────────────────────────
# GameStateManager.determine_winner — cas avec 0 unités
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinnerZeroUnits:

    def _mgr(self) -> GameStateManager:
        return GameStateManager(config={
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        })

    def test_no_units_equal_vp_draw(self):
        """winner_no_units_draw : aucune unité, VP égaux → draw=-1."""
        gs = _make_gs_for_winner(p1_vp=0, p2_vp=0, p1_units=0, p2_units=0)
        assert self._mgr().determine_winner(gs) == -1

    def test_no_units_p1_more_vp_wins(self):
        """winner_no_units_p1_vp : aucune unité, p1 plus de VP → p1 gagne."""
        gs = _make_gs_for_winner(p1_vp=2, p2_vp=0, p1_units=0, p2_units=0)
        assert self._mgr().determine_winner(gs) == 1

    def test_p1_no_units_p2_has_units_equal_vp_p2_wins(self):
        """winner_p1_no_units : VP égaux, p1 0 unités, p2 a une unité → p2 gagne (plus de valeur)."""
        gs = _make_gs_for_winner(p1_vp=3, p2_vp=3, p1_units=0, p2_units=1, p2_unit_value=100)
        assert self._mgr().determine_winner(gs) == 2
