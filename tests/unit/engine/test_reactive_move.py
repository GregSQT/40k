"""Mouvement réactif — maybe_resolve_reactive_move déclenchement/non-déclenchement."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers.shared_utils import (
    build_units_cache,
    maybe_resolve_reactive_move,
)


def _unit(uid: int, player: int, col: int, row: int, hp: int = 3) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "col": col,
        "row": row,
        "HP_CUR": hp,
        "HP_MAX": hp,
        "VALUE": 100,
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


def _unit_with_reactive(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    u = _unit(uid, player, col, row)
    u["UNIT_RULES"] = [{"ruleId": "reactive_move", "displayName": "SKULKING HORRORS"}]
    return u


def _make_game_state(units: List[Dict[str, Any]], current_player: int = 1) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        "board_cols": 25,
        "board_rows": 21,
        "current_player": current_player,
        "phase": "move",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "_unit_move_version": 0,
        # Reactive move required fields
        "reaction_window_active": False,
        "units_reacted_this_enemy_turn": set(),
        "last_move_event_id": 0,
        "reactive_mode": "micro",
        "reactive_decision_mode": "auto",
        "reactive_macro_order_current_window": [],
        "reactive_decision_payload": {},
        "last_move_cause": "normal",
        # Phase pools
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "units_moved": set(),
        "los_cache": {},
        "hex_los_cache": {},
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Non-déclenchement
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveNoTrigger:

    def test_move_cause_reactive_returns_not_triggered(self):
        """reactive_cause : move_cause='reactive_move' → retour immédiat, triggered=False."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 6, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "reactive_move")
        assert result["triggered"] is False
        assert result["reactive_moves_applied"] == 0
        assert result["reactive_moves_declined"] == 0

    def test_no_reactive_rule_no_trigger(self):
        """reactive_norule : aucune unité avec la règle reactive_move → triggered=False."""
        units = [_unit(1, 1, 5, 10), _unit(2, 2, 6, 10)]  # pas de règle reactive_move
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_unit_too_far_no_trigger(self):
        """reactive_toofar : unité éligible à plus de 9 hexes → triggered=False."""
        # unit 1 (player=1) moves to (5,10); unit 2 (player=2) is at (20,10) > 9 hexes away
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 20, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_same_player_no_trigger(self):
        """reactive_sameplayer : unité réactive du même joueur → non éligible → triggered=False."""
        # unit 1 (player=1) moves; unit 2 (player=1, same side) has reactive_move
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 1, 7, 10)]
        gs = _make_game_state(units)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False

    def test_reentrance_raises_runtime_error(self):
        """reactive_reentrant : reaction_window_active=True → RuntimeError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 6, 10)]
        gs = _make_game_state(units)
        gs["reaction_window_active"] = True
        with pytest.raises(RuntimeError, match="reentrance"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")


# ─────────────────────────────────────────────────────────────────────────────
# Déclenchement — unité éligible dans la zone
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveTriggered:

    def test_eligible_unit_moves_and_cache_updated(self, monkeypatch):
        """reactive_triggered : unité éligible dans la zone → triggered=True, cache mis à jour."""
        # unit 1 (player=1) moves from (4,10) to (5,10)
        # unit 2 (player=2, has reactive_move) is at (7,10) — 2 hexes from (5,10)
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)

        # D6 roll for reactive move range → 3 (resolve_dice_value uses random.randint)
        monkeypatch.setattr("random.randint", lambda a, b: 3)

        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is True
        assert result["reactive_moves_applied"] == 1
        assert result["reactive_moves_declined"] == 0

    def test_reactive_unit_position_updated_in_cache(self, monkeypatch):
        """reactive_cache : après déclenchement, units_cache reflète la nouvelle position."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        orig_pos = (gs["units_cache"]["2"]["col"], gs["units_cache"]["2"]["row"])

        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")

        new_pos = (gs["units_cache"]["2"]["col"], gs["units_cache"]["2"]["row"])
        # Unité a bougé — nouvelle position != ancienne
        assert new_pos != orig_pos

    def test_reaction_window_cleaned_up_after_trigger(self, monkeypatch):
        """reactive_cleanup : reaction_window_active remis à False après déclenchement."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert gs["reaction_window_active"] is False

    def test_reacted_unit_not_triggered_twice(self, monkeypatch):
        """reactive_onceperturn : unité déjà dans units_reacted_this_enemy_turn → non éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        gs["units_reacted_this_enemy_turn"] = {"2"}  # déjà réagi
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Cas limites supplémentaires
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeResolveReactiveMoveEdgeCases:

    def test_move_cause_advance_triggers(self, monkeypatch):
        """reactive_advance : move_kind='advance' autorisé → triggered possible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "advance", "normal")
        assert result["triggered"] is True

    def test_move_cause_flee_triggers(self, monkeypatch):
        """reactive_flee : move_kind='flee' → triggered possible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "flee", "normal")
        assert result["triggered"] is True

    def test_invalid_move_kind_raises_value_error(self):
        """reactive_invalid_kind : move_kind invalide → ValueError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        with pytest.raises(ValueError, match="Unsupported move_kind"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "teleport", "normal")

    def test_invalid_move_cause_raises_value_error(self):
        """reactive_invalid_cause : move_cause invalide → ValueError."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        with pytest.raises(ValueError, match="Unsupported move_cause"):
            maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "magic")

    def test_last_move_event_id_incremented(self, monkeypatch):
        """reactive_event_id : last_move_event_id incrémenté quand unité éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        gs["last_move_event_id"] = 5
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert gs["last_move_event_id"] == 6

    def test_action_log_entry_added_on_trigger(self, monkeypatch):
        """reactive_log_entry : déclenchement → entrée dans action_logs."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        initial_log_len = len(gs["action_logs"])
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert len(gs["action_logs"]) > initial_log_len

    def test_units_reacted_set_updated_on_trigger(self, monkeypatch):
        """reactive_reacted_set : unité réactive ajoutée à units_reacted_this_enemy_turn."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 7, 10)]
        gs = _make_game_state(units)
        assert "2" not in gs["units_reacted_this_enemy_turn"]
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert "2" in gs["units_reacted_this_enemy_turn"]

    def test_exactly_9_hexes_away_eligible(self, monkeypatch):
        """reactive_9hex_boundary : unité à exactement 9 hexes → éligible."""
        # Unité moved à (5,10), reactive unit à (14,10) = 9 hexes
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 14, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 5)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        # 9 hexes → eligible (distance <= 9)
        assert result["triggered"] is True

    def test_10_hexes_away_not_eligible(self, monkeypatch):
        """reactive_10hex_boundary : unité à 10 hexes → non éligible."""
        units = [_unit(1, 1, 5, 10), _unit_with_reactive(2, 2, 15, 10)]
        gs = _make_game_state(units)
        monkeypatch.setattr("random.randint", lambda a, b: 5)
        result = maybe_resolve_reactive_move(gs, "1", 4, 10, 5, 10, "move", "normal")
        assert result["triggered"] is False
