#!/usr/bin/env python3
"""
command_handlers.py - Command Phase Implementation
Pure stateless functions implementing command phase specification

The command phase handles all administrative tasks (reset marks, clear caches, etc.)
before the movement phase. In Phase 2, the agent may take zone intent free steps
(up to MAX_OBJECTIVES) before transitioning to move.
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from shared.data_validation import require_key
from engine.game_state import GameStateManager


def command_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize command phase - do all maintenance/resets, then either:
    - Stay in command if zone intent free steps are available (Phase 2), or
    - Auto-advance to move (no free steps or bot player).

    Phase 2 changes:
    - Initializes zone_intent_free_steps_remaining = MAX_OBJECTIVES
    - Populates unit_zone_assignments (one per alive friendly unit)
    - Returns without phase_complete if free steps > 0 (agent will issue zone intent actions)
    """
    from engine.macro_intents import INTENT_INVADE, MAX_OBJECTIVES, get_nearest_objective_zone

    # Set phase
    game_state["phase"] = "command"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} command units_cache={units_cache}")

    # Snapshot last turn's shooting BEFORE reset (rule 13.09 Hidden: "did not make ranged
    # attacks during this turn or during the previous turn"). Captured at each turn start so
    # it holds the previous player-turn's shots when evaluating enemy targets.
    game_state["units_shot_previous_turn"] = set(game_state.get("units_shot", set()))

    # Reset ALL tracking sets (moved from movement_phase_start)
    game_state["units_moved"] = set()
    game_state["units_fled"] = set()
    game_state["units_shot"] = set()
    game_state["units_charged"] = set()
    game_state["units_fought"] = set()
    game_state["units_attacked"] = set()
    game_state["units_advanced"] = set()
    game_state["units_reacted_this_enemy_turn"] = set()

    game_state["reactive_macro_order_current_window"] = []
    game_state["reaction_window_active"] = False
    game_state["reactive_decision_payload"] = {}

    # Clear movement preview state
    game_state["valid_move_destinations_pool"] = []
    game_state["preview_hexes"] = []
    game_state["move_preview_footprint_zone"] = set()
    game_state["move_preview_footprint_mask_loops"] = None
    game_state["move_preview_footprint_span"] = None
    game_state["active_movement_unit"] = None

    # Clear enemy reachable positions cache (enemy positions may have changed)
    # Used by RewardCalculator._get_enemy_reachable_positions for defensive threat calculation
    game_state["enemy_reachable_cache"] = {}

    # Battle-shock step (règle 08.03) — avant l'activation pool
    from engine.phase_handlers.shared_utils import is_unit_at_half_strength, roll_battle_shock, is_unit_alive
    current_player = require_key(game_state, "current_player")
    for unit in require_key(game_state, "units"):
        if unit.get("player") != current_player:
            continue
        unit_id = str(unit["id"])
        if not is_unit_alive(unit_id, game_state):
            continue
        needs_roll = unit.get("battle_shocked", False) or is_unit_at_half_strength(unit_id, game_state)
        if needs_roll:
            shocked = roll_battle_shock(unit_id, game_state)
            add_debug_file_log(
                game_state,
                f"[BATTLE-SHOCK] E{episode} T{turn} unit={unit_id} shocked={shocked} ld={unit.get('LD')}"
            )

    # Build activation pool (empty for now, structure ready for future)
    command_build_activation_pool(game_state)

    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} command command_activation_pool={command_pool}")

    # Console log
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE START")

    # Primary objective scoring (command phase)
    state_manager = GameStateManager(require_key(game_state, "config"))
    state_manager.apply_primary_objective_scoring(game_state, "command")

    # Phase 2: Initialize zone intent free steps
    # Only for the controlled agent player during gym training
    gym_training_mode = game_state.get("gym_training_mode", False)
    current_player = game_state.get("current_player")
    config = game_state["config"]
    controlled_player = config.get("controlled_player")

    is_agent_turn = (
        gym_training_mode
        and controlled_player is not None
        and current_player == controlled_player
    )

    # Populate unit_zone_assignments for ALL alive units (both players)
    from engine.phase_handlers.shared_utils import is_unit_alive
    assignments = {}
    for unit in game_state["units"]:
        if not is_unit_alive(str(unit["id"]), game_state):
            continue
        if unit.get("col", -1) >= 0 and unit.get("row", -1) >= 0:
            zone_idx = get_nearest_objective_zone(unit, game_state)
        else:
            zone_idx = 0
        assignments[str(unit["id"])] = zone_idx
    game_state["unit_zone_assignments"] = assignments

    if is_agent_turn:
        # Reset zone_intent_free_steps_remaining to MAX_OBJECTIVES
        game_state["zone_intent_free_steps_remaining"] = MAX_OBJECTIVES

        # Stay in command phase — agent will issue zone intent actions
        return {"phase_complete": False, "phase": "command"}

    # Bot player or non-training: skip free steps, auto-advance to move
    game_state["zone_intent_free_steps_remaining"] = 0
    return command_phase_end(game_state)


def command_build_activation_pool(game_state: Dict[str, Any]) -> None:
    """
    Build command activation pool (empty for now, structure ready for future).
    """
    game_state["command_activation_pool"] = []


def command_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    End command phase and transition to move phase.
    
    CRITICAL: Returns ONLY the dict, does NOT call movement_phase_start() directly.
    The cascade loop in w40k_core.py handles the transition automatically.
    """
    from engine.game_utils import add_console_log
    add_console_log(game_state, "COMMAND PHASE COMPLETE")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    command_pool = require_key(game_state, "command_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} command command_activation_pool={command_pool}")
    
    # Return only the dict - cascade loop will call movement_phase_start()
    return {
        "phase_complete": True,
        "next_phase": "move",
        "phase_transition": True,
        "clear_blinking_gentle": True
    }


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute action for command phase (structure ready for future).
    
    For now, no actions - phase auto-advances.
    Structure ready for future unit actions in command phase.
    """
    # For now, no actions - phase auto-advances
    # Structure ready for future unit actions in command phase
    return True, command_phase_end(game_state)




