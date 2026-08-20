"""L28 — charge_roll_initial propagé dans step.log pour le chemin gym (finding 1) et purge
dans les chemins postpone (finding 2) et phase_start (finding 3).

ROOT CAUSE : `_charge_initial_rolls` est peuplé par `charge_roll_for_activation` quand une relance
a lieu, mais aucun des deux sites gym (`squad_charge` / charge_fail dans `_process_squad_action`)
ne l'inclut dans le dict qu'il passe à `append_action_log`. Le mapping L6237 existe mais ne fire
jamais : `[REROLLED:<n>]` est absent de tout step.log d'entraînement.

Deux bugs connexes :
 - postpone PvP (`charge_click_handler`, active_unit) : ne pop pas `_charge_initial_rolls` →
   entrée stale lue au tour suivant si une relance avait eu lieu.
 - `charge_phase_start` : ne remet pas `_charge_initial_rolls = {}` → mémoire inter-tours.

VERROUS :
 - finding 1 : action_log gym charge_fail contient charge_roll_initial + entrée purgée.
 - finding 2 : postpone purge _charge_initial_rolls.
 - finding 3 : charge_phase_start remet le dict à zéro.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.phase_handlers.charge_handlers import charge_click_handler, charge_phase_start
from engine.w40k_core import W40KEngine
from tests._state_invariants import turn_state_invariants, unit_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Finding 3 — charge_phase_start remet _charge_initial_rolls à zéro
# ─────────────────────────────────────────────────────────────────────────────

def _make_gs_charge_start(monkeypatch) -> Dict[str, Any]:
    """Game-state minimal pour charge_phase_start (pool mocké pour éviter le BFS complet)."""
    from tests.unit.engine._config_helpers import build_move_rules, NEUTRAL_TEST_ARMY_FACTION, NEUTRAL_TEST_FACTION
    units = [
        {**unit_invariants(), "id": "1", "player": 1, "col": 5, "row": 10,
         "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "OC": 1, "MOVE": 6,
         "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
         "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
         "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
         "FACTION_KEYWORDS": [NEUTRAL_TEST_FACTION], "UNIT_RULES": []},
        {**unit_invariants(), "id": "2", "player": 2, "col": 20, "row": 10,
         "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "OC": 1, "MOVE": 6,
         "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
         "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
         "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
         "FACTION_KEYWORDS": [NEUTRAL_TEST_FACTION], "UNIT_RULES": []},
    ]
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "charge": {"charge_max_distance": 12},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
            "army_faction": dict(NEUTRAL_TEST_ARMY_FACTION),
        },
        "board_cols": 25, "board_rows": 21,
        "current_player": 1,
        "phase": "shoot",
        "wall_hexes": set(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "inches_to_subhex": 1,
    }
    from engine.phase_handlers.shared_utils import build_units_cache, build_enemy_adjacent_hexes
    build_units_cache(gs)
    build_enemy_adjacent_hexes(gs, 1)
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers.charge_build_activation_pool",
        lambda g: None,
    )
    gs["charge_activation_pool"] = ["1"]
    return gs


def test_charge_phase_start_resets_initial_rolls(monkeypatch):
    """charge_start_initial_rolls : _charge_initial_rolls remis à {} en début de phase (finding 3).

    Avant le fix : la clé n'est pas réinitialisée → une entrée stale d'un tour précédent
    survit et sera lue en .pop() au tour suivant, injectant un faux [REROLLED] dans step.log.
    """
    gs = _make_gs_charge_start(monkeypatch)
    gs["_charge_initial_rolls"] = {"1": 3, "stale": 7}
    charge_phase_start(gs)
    assert gs["_charge_initial_rolls"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Finding 2 — postpone PvP purge _charge_initial_rolls
# ─────────────────────────────────────────────────────────────────────────────

def test_postpone_clears_charge_initial_rolls():
    """charge_postpone_initial_rolls : postpone PvP purge _charge_initial_rolls (finding 2).

    Avant le fix : l'entrée stale survive et sera .pop()-ée au tour suivant comme si une
    relance avait eu lieu lors de l'activation du tour suivant (faux [REROLLED] dans step.log).
    """
    gs: Dict[str, Any] = {
        "preview_hexes": [],
        "valid_charge_destinations_pool": [],
        "active_charge_unit": "u1",
        "charge_roll_values": {"u1": 7},
        "charge_target_selections": {"u1": "enemy2"},
        "_charge_initial_rolls": {"u1": 3},
        # Caches géodésiques effacés par charge_clear_preview (indirect via valid_charge_destinations_pool)
        "_charge_dest_bfs_cache": {},
        "_charge_fp_offset_pair_cache": {},
        "_has_valid_charge_cache": {},
        "_charge_reach_disk_cache": {},
        "_charge_model_field_cache": {},
        "pending_charge_targets": [],
        "pending_charge_unit_id": None,
    }
    charge_click_handler(gs, "u1", {"clickTarget": "active_unit"})
    assert gs.get("_charge_initial_rolls", {}).get("u1") is None


# ─────────────────────────────────────────────────────────────────────────────
# Finding 1 — chemin gym squad_charge inclut charge_roll_initial dans l'action_log
# ─────────────────────────────────────────────────────────────────────────────

def _bare_charge_engine(gs: Dict[str, Any]) -> W40KEngine:
    """Instance minimale de W40KEngine pour tester le chemin gym charge."""
    engine = object.__new__(W40KEngine)
    engine.game_state = gs
    engine.step_logger = None
    engine.gym_training_mode = False
    return engine


def _charge_gs() -> Dict[str, Any]:
    """Game-state minimal pour `_process_squad_action` → squad_charge (charge_fail path)."""
    from tests.unit.engine._config_helpers import NEUTRAL_TEST_FACTION
    unit1: Dict[str, Any] = {
        **unit_invariants(),
        "id": "1", "player": 1, "col": 5, "row": 10,
        "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "OC": 1,
        "FACTION_KEYWORDS": [NEUTRAL_TEST_FACTION], "UNIT_RULES": [],
        "MOVE": 6, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
        "SHOOT_LEFT": 1, "ATTACK_LEFT": 1, "RNG_WEAPONS": [], "CC_WEAPONS": [],
        "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5, "BASE_SHAPE": "round",
    }
    return {
        **turn_state_invariants(),
        "units_cache": {
            "1": {"id": "1", "player": 1, "col": 5, "row": 10,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "occupied_hexes": {(5, 10)}},
            "2": {"id": "2", "player": 2, "col": 7, "row": 10,
                  "BASE_SHAPE": "round", "BASE_SIZE": 1, "occupied_hexes": {(7, 10)}},
        },
        "units": [{"id": "1", "player": 1, "UNIT_RULES": [], "col": 5, "row": 10}],
        "unit_by_id": {"1": unit1},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "phase": "charge",
        "current_player": 1,
        "game_over": False,
        "turn_limit_reached": False,
        "charge_activation_pool": ["1"],
        "debug_logs": [],
        "config": {
            "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        },
        # _charge_initial_rolls : relance simulée à l'activation (masquage)
        "_charge_initial_rolls": {"1": 5},
    }


def test_gym_charge_fail_logs_initial_roll(monkeypatch):
    """gym_charge_fail_initial_roll : charge_roll_initial présent dans l'action_log gym (finding 1).

    Avant le fix : l'action_log ne contient pas la clé → le mapping step_log (L6237) ne fire
    jamais → [REROLLED:<n>] absent de tout step.log d'entraînement.
    Après le fix : la valeur 5 est bien dans l'action_log ET purgée de _charge_initial_rolls.
    """
    # Mocks pour isoler le test du plan de charge et des mesures de distance
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers.charge_roll_for_activation",
        lambda gs, sid: 3,  # jet faible → charge_fail
    )
    monkeypatch.setattr(
        "engine.phase_handlers.shared_utils.charge_check_eligibility",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "engine.phase_handlers.shared_utils.get_enemy_slot_mapping",
        lambda gs, player: ["2"] + [None] * 19,
    )
    monkeypatch.setattr(
        "engine.phase_handlers.shared_utils.charge_build_valid_plan",
        lambda *a, **k: None,  # force charge_fail
    )
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers.charge_record_target_choice",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "engine.phase_handlers.charge_handlers.charge_record_outcome",
        lambda *a, **k: {},
    )
    # Le game_state minimal n'a pas models_cache ; couper la cascade fight pour ne pas crasher.
    monkeypatch.setattr(
        "engine.phase_handlers.fight_handlers.fight_phase_start",
        lambda gs: {},
    )

    gs = _charge_gs()
    engine = _bare_charge_engine(gs)
    # Isole du post-processing game_over (config, objectifs)
    engine._check_game_over = lambda: False  # type: ignore[method-assign]
    # Isole des rule_choice candidates (iterent sur units["col"]/["row"] absents du stub)
    engine._emit_next_rule_choice_prompt_if_needed = lambda: None  # type: ignore[method-assign]
    engine._process_squad_action({"action": "squad_charge", "squad_id": "1", "target_slot": 0})

    assert len(gs["action_logs"]) == 1
    log_entry = gs["action_logs"][0]
    assert log_entry["type"] == "charge_fail"
    # Finding 1 : charge_roll_initial doit être dans l'action_log
    assert log_entry.get("charge_roll_initial") == 5
    # L'entrée doit avoir été purgée de _charge_initial_rolls (.pop)
    assert gs.get("_charge_initial_rolls", {}).get("1") is None
