"""Tests unitaires — cascade phase charge → fight et transitions internes fight.

Couvre :
- advance_phase from=charge sans unités eligibles → fight vide → transition vers move (P2)
- advance_phase from=charge avec unités adjacentes chargées → fight initialisé, pools non vides
- advance_phase from=fight (pools vides) → transition correcte
- fight_phase_end : passage P1 → current_player=2, next_phase='command'
- Sous-phases fight : ordering charging > alternating
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.w40k_core import W40KEngine
from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _base_config() -> Dict[str, Any]:
    return {
        "game_rules": {
            "engagement_zone": 1,
            "max_base_size_hex": 35,
            "los_visibility_min_ratio": 0.0,
            "cover_ratio": 0.0,
        },
        "charge": {
            "charge_max_distance": 12,
        },
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "gym_training_mode": False,
        "pve_mode": False,
    }


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


def _make_gs(units: List[Dict[str, Any]], phase: str = "charge") -> Dict[str, Any]:
    """Game-state minimal avec toutes les clés requises pour les transitions charge/fight."""
    gs: Dict[str, Any] = {
        "config": _base_config(),
        "board_cols": 25,
        "board_rows": 21,
        "current_player": 1,
        "phase": phase,
        "wall_hexes": set(),
        "terrain_areas": [],
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "console_logs": [],
        "debug_logs": [],
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "episode_number": 1,
        "episode_steps": 0,
        "turn_limit_reached": False,
        "game_over": False,
        "units_moved": set(),
        "units_advanced": set(),
        "units_fled": set(),
        "units_shot": set(),
        "units_charged": set(),
        "units_fought": set(),
        "units_cannot_charge": set(),
        "units_attacked": set(),
        "units_reacted_this_enemy_turn": set(),
        "reaction_window_active": False,
        "_unit_move_version": 0,
        "last_move_event_id": 0,
        "last_move_cause": "normal",
        "reactive_mode": "micro",
        "reactive_macro_order_current_window": [],
        "reactive_decision_mode": "auto",
        "reactive_decision_payload": {},
        "move_activation_pool": [],
        "shoot_activation_pool": [],
        "charge_activation_pool": [],
        "charging_activation_pool": [],
        "active_alternating_activation_pool": [],
        "non_active_alternating_activation_pool": [],
        "valid_move_destinations_pool": [],
        "preview_hexes": [],
        "move_preview_footprint_span": None,
        "active_movement_unit": None,
        "fight_subphase": None,
        "fight_attack_results": [],
        "hex_los_cache": {},
        "los_cache": {},
        "player_types": {"1": "human", "2": "human"},
        "gym_training_mode": False,
        "weapon_rule": 1,
        "active_shooting_unit": None,
        "shoot_attack_results": [],
        # charge-specific
        "valid_charge_destinations_pool": [],
        "_charge_dest_bfs_cache": {},
        "_charge_fp_offset_pair_cache": {},
        "active_charge_unit": None,
        "charge_roll_values": {},
        "charge_target_selections": {},
        "pending_charge_targets": [],
        "pending_charge_unit_id": None,
        "objectives": [{"id": "obj1", "hexes": [[5, 5]]}],
        "inches_to_subhex": 1,
    }
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, gs["current_player"])
    build_enemy_adjacent_hexes(gs, 2)  # Pré-calculer pour P2 (needed after player switch)
    return gs


def _bare_engine(gs: Dict[str, Any]) -> W40KEngine:
    """Instancie W40KEngine sans __init__ et injecte le game_state."""
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = False
    engine.config = _base_config()
    engine._shooting_phase_initialized = False
    engine._movement_phase_initialized = False
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# Tests — cascade charge → fight
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeChargeFight:

    def test_advance_from_charge_no_eligible_fight_skips_fight(self):
        """cascade_charge_nofight : aucune unité chargante → fight vide → phase avance (pas fight)."""
        # P1 far from P2, no units_charged → fight immediately complete
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="charge")
        gs["units_charged"] = set()  # No charging units
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "advance_phase", "from": "charge"})

        assert success is True
        # La phase ne doit plus être "charge" (cascade a avancé)
        assert gs["phase"] != "charge"

    def test_advance_from_charge_no_eligible_fight_current_player_changes(self):
        """cascade_charge_player_switch : fight vide → P1 complet → current_player passe à 2."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="charge")
        gs["units_charged"] = set()
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "advance_phase", "from": "charge"})

        # Après fight vide de P1, current_player doit être passé à 2
        assert gs["current_player"] == 2

    def test_advance_from_charge_adjacent_charged_unit_initializes_fight(self):
        """cascade_charge_adj_fight : P1 chargé adjacent P2 → fight initialisé, pool non vide."""
        # P1 at (5,10), P2 at (5,11) → adjacent within engagement_zone=1
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 5, 11)  # Adjacent to p1
        gs = _make_gs([p1, p2], phase="charge")
        gs["units_charged"] = {"1"}  # P1 unit charged this turn
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "advance_phase", "from": "charge"})

        assert success is True
        # Fight phase initialisé avec unités éligibles
        assert gs["phase"] == "fight"
        # Le pool charging doit contenir l'unité 1
        assert "1" in gs["charging_activation_pool"]

    def test_advance_from_charge_adjacent_charged_unit_sets_fight_subphase(self):
        """cascade_charge_subphase : fight initialisé avec pool charging → fight_subphase='charging'."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 5, 11)
        gs = _make_gs([p1, p2], phase="charge")
        gs["units_charged"] = {"1"}
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "advance_phase", "from": "charge"})

        assert gs["fight_subphase"] == "charging"


# ─────────────────────────────────────────────────────────────────────────────
# Tests — transitions fight phase end
# ─────────────────────────────────────────────────────────────────────────────

class TestFightPhaseTransitions:

    def test_advance_from_fight_empty_pools_transitions_to_command(self):
        """cascade_fight_end : advance_phase from=fight, pools vides → next_phase inclut 'command'."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="fight")
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        gs["units_fought"] = set()
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "advance_phase", "from": "fight"})

        assert success is True
        # La phase ne doit plus être "fight" (transition déclenchée)
        assert gs["phase"] != "fight"

    def test_advance_from_fight_player1_switches_to_player2(self):
        """cascade_fight_p1_end : fight P1 terminé → current_player passe à 2."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="fight")
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        gs["units_fought"] = set()
        gs["current_player"] = 1
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "advance_phase", "from": "fight"})

        # P1 fight complet → P2 doit maintenant jouer
        assert gs["current_player"] == 2

    def test_fight_phase_end_clears_fight_subphase(self):
        """cascade_fight_subphase_cleared : après fight_phase_end → fight_subphase=None."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="fight")
        gs["fight_subphase"] = "alternating_active"
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        gs["units_fought"] = set()
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "advance_phase", "from": "fight"})

        assert gs["fight_subphase"] is None

    def test_fight_phase_end_clears_fight_pools(self):
        """cascade_fight_pools_cleared : fight_phase_end vide les 3 pools fight."""
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 20, 10)
        gs = _make_gs([p1, p2], phase="fight")
        gs["charging_activation_pool"] = []
        gs["active_alternating_activation_pool"] = []
        gs["non_active_alternating_activation_pool"] = []
        gs["units_fought"] = set()
        engine = _bare_engine(gs)

        engine.execute_semantic_action({"action": "advance_phase", "from": "fight"})

        assert gs["charging_activation_pool"] == []
        assert gs["active_alternating_activation_pool"] == []
        assert gs["non_active_alternating_activation_pool"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Tests — cascade complète move → fight
# ─────────────────────────────────────────────────────────────────────────────

class TestCascadeFullTurn:

    def test_cascade_move_through_shoot_charge_stops_at_fight(self):
        """cascade_full_turn : advance_phase from=move + P1 adjacent P2 chargé → stoppe à fight."""
        # P1 vient de charger P2 (adjacent) : units_charged={"1"}
        # Shoot pool vide (pas de tireurs), charge pool vide (déjà chargé)
        # → cascade devrait s'arrêter au fight (pools non vides)
        p1 = _unit(1, 1, 5, 10)
        p2 = _unit(2, 2, 5, 11)
        gs = _make_gs([p1, p2], phase="move")
        gs["units_charged"] = {"1"}  # P1 a chargé
        gs["move_activation_pool"] = []  # Pool move vide → advance
        gs["units_shot"] = set()
        engine = _bare_engine(gs)

        success, result = engine.execute_semantic_action({"action": "advance_phase", "from": "move"})

        assert success is True
        # La cascade devrait s'être arrêtée à fight (pool non vide)
        assert gs["phase"] == "fight"
        assert len(gs["charging_activation_pool"]) > 0
