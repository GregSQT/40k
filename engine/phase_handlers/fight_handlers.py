#!/usr/bin/env python3
"""
engine/phase_handlers/fight_handlers.py - AI_TURN.md Fight Phase Implementation
Pure stateless functions implementing AI_TURN.md fight specification

References: AI_TURN.md Section ⚔️ FIGHT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns

CRITICAL: On ne tire PAS en phase de fight. La règle PISTOL permet de tirer en phase
de SHOOTING même si l'unité est adjacente à une unité ennemie (exception au "engaged").
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from shared.data_validation import require_key
from engine.game_utils import add_console_log, safe_print
from engine.combat_utils import (
    normalize_coordinates,
    calculate_hex_distance,
    get_unit_by_id,
    get_unit_coordinates,
    resolve_dice_value
)
from engine.game_state import GameStateManager
from .shared_utils import (
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, PASS, ERROR, FIGHT,
    update_units_cache_hp, remove_from_units_cache,
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
)

def fight_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize fight phase and build activation pools.

    CRITICAL: Fight phase has THREE sub-phases:
    1. Charging units (units in units_charged) attack first
    2. Alternating activation between players (remaining units adjacent to enemies)
    3. Cleanup (process remaining pool if any)
    """
    # Set phase
    game_state["phase"] = "fight"

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} fight units_cache={units_cache}")

    # UNITS_CACHE: Verify units_cache exists (built at reset, not here - "reset only" policy)
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist at fight_phase_start (should be built at reset)")

    # Build ALL fight pools (charging + alternating for both players)
    # NOTE: ATTACK_LEFT is NOT set at phase start - it's set per unit activation
    fight_build_activation_pools(game_state)

    # Check if phase complete immediately (no eligible units)
    # AI_TURN.md COMPLIANCE: Direct field access - pools are set by fight_build_activation_pools()
    if "charging_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'charging_activation_pool' field after fight_build_activation_pools()")
    if "active_alternating_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'active_alternating_activation_pool' field after fight_build_activation_pools()")
    if "non_active_alternating_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'non_active_alternating_activation_pool' field after fight_build_activation_pools()")

    charging_pool = game_state["charging_activation_pool"]
    active_alternating = game_state["active_alternating_activation_pool"]
    non_active_alternating = game_state["non_active_alternating_activation_pool"]

    # Kill probability cache is built lazily on first use (select_best_melee_weapon) to avoid step spike.
    has_eligible = bool(charging_pool or active_alternating or non_active_alternating)

    # Console log
    add_console_log(game_state, "FIGHT PHASE START")

    # AI_TURN.md COMPLIANCE: Set initial fight_subphase based on which pools have units
    if charging_pool:
        game_state["fight_subphase"] = "charging"
    elif non_active_alternating or active_alternating:
        # Non-active player goes FIRST in alternating phase
        game_state["fight_subphase"] = "alternating_non_active"
    else:
        game_state["fight_subphase"] = None

    if not has_eligible:
        return fight_phase_end(game_state)

    return {
        "phase_initialized": True,
        "charging_units": len(charging_pool),
        "active_alternating": len(active_alternating),
        "non_active_alternating": len(non_active_alternating),
        "phase_complete": False
    }


def fight_build_activation_pools(game_state: Dict[str, Any]) -> None:
    """
    Build all 3 fight phase activation pools.

    Sub-Phase 1: charging_activation_pool (current player's charging units)
    Sub-Phase 2: active_alternating_activation_pool + non_active_alternating_activation_pool
    Sub-Phase 3: Cleanup (handled by sub-phase 2 logic when one pool empty)

    CRITICAL: Non-active player goes first in alternating phase per AI_TURN.md.
    """
    current_player = require_key(game_state, "current_player")
    try:
        current_player_int = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player_int not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player_int}")
    game_state["current_player"] = current_player_int

    non_active_player = 3 - game_state["current_player"]

    # AI_TURN.md COMPLIANCE: Ensure units_fought exists before any checks
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()

    # AI_TURN.md COMPLIANCE: units_charged must exist (set by charge phase)
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field - charge phase must run before fight phase")
    units_charged_set = {str(uid) for uid in game_state["units_charged"]}
    units_fought_set = {str(uid) for uid in game_state["units_fought"]}

    # Sub-Phase 1: Charging units (current player only, units in units_charged AND adjacent)
    # CRITICAL: Clear pools before rebuilding (defense in depth)
    game_state["charging_activation_pool"] = []
    game_state["active_alternating_activation_pool"] = []
    game_state["non_active_alternating_activation_pool"] = []
    charging_activation_pool = []
    add_console_log(game_state, f"FIGHT POOL BUILD: Building charging pool for player {current_player}")
    units_cache = require_key(game_state, "units_cache")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if cache_entry["player"] == current_player:
            if str(unit_id) in units_fought_set:
                continue
            if str(unit_id) in units_charged_set:
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
                if valid_targets:
                    charging_activation_pool.append(unit_id)
                    add_console_log(game_state, f"ADDED TO CHARGING POOL: Unit {unit_id}")

    game_state["charging_activation_pool"] = charging_activation_pool
    add_console_log(game_state, f"CHARGING POOL SIZE: {len(charging_activation_pool)}")
    
    # DEBUG: Log all units in charging pool
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        for unit_id in charging_activation_pool:
            unit = get_unit_by_id(game_state, unit_id)
            if unit:
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight build_pools: Unit {unit_id} (player {unit['player']}) ADDED to charging_pool"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)

    # Sub-Phase 2: Alternating activation (units NOT in units_charged, adjacent to enemies)
    active_alternating = []
    non_active_alternating = []

    add_console_log(game_state, f"FIGHT POOL BUILD: Building alternating pools")
    for unit_id, cache_entry in units_cache.items():
        unit = get_unit_by_id(game_state, unit_id)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if str(unit_id) in units_fought_set:
            continue
        if str(unit_id) not in units_charged_set:
            valid_targets = _fight_build_valid_target_pool(game_state, unit)
            if valid_targets:
                if cache_entry["player"] == current_player:
                    active_alternating.append(unit_id)
                    add_console_log(game_state, f"ADDED TO ACTIVE ALTERNATING: Unit {unit_id} (player {cache_entry['player']})")
                else:
                    non_active_alternating.append(unit_id)
                    add_console_log(game_state, f"ADDED TO NON-ACTIVE ALTERNATING: Unit {unit_id} (player {cache_entry['player']})")

    game_state["active_alternating_activation_pool"] = active_alternating
    game_state["non_active_alternating_activation_pool"] = non_active_alternating
    add_console_log(game_state, f"ALTERNATING POOLS: active={len(active_alternating)}, non_active={len(non_active_alternating)}")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    add_debug_file_log(
        game_state,
        f"[POOL BUILD] E{episode} T{turn} fight charging_activation_pool={charging_activation_pool} "
        f"active_alternating_activation_pool={active_alternating} "
        f"non_active_alternating_activation_pool={non_active_alternating}"
    )


def _remove_dead_unit_from_fight_pools(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    CRITICAL: Immediately remove a dead unit from all fight activation pools.
    
    This must be called as soon as a unit dies to prevent it from being activated
    in subsequent sub-phases of the same fight phase.
    """
    unit_id_str = str(unit_id)
    
    # Remove from charging pool
    if "charging_activation_pool" in game_state:
        game_state["charging_activation_pool"] = [uid for uid in game_state["charging_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from active alternating pool
    if "active_alternating_activation_pool" in game_state:
        game_state["active_alternating_activation_pool"] = [uid for uid in game_state["active_alternating_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from non-active alternating pool
    if "non_active_alternating_activation_pool" in game_state:
        game_state["non_active_alternating_activation_pool"] = [uid for uid in game_state["non_active_alternating_activation_pool"] if str(uid) != unit_id_str]
    
    # CRITICAL: Also remove from other phase pools (units can die in fight but be in other pools)
    # Import from shooting_handlers to reuse the function
    from .shooting_handlers import _remove_dead_unit_from_pools
    _remove_dead_unit_from_pools(game_state, unit_id)

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is adjacent to at least one enemy within melee range.

    Used for fight phase eligibility - unit must be within melee range of an enemy.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    unit_col, unit_row = require_unit_position(unit, game_state)

    if "console_logs" not in game_state:
        game_state["console_logs"] = []

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) != unit_player:
            enemy_col, enemy_row = require_unit_position(enemy_id, game_state)
            distance = calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
            add_console_log(game_state, f"FIGHT CHECK: Unit {unit['id']} @ ({unit_col},{unit_row}) melee_range={cc_range} | Enemy {enemy_id} @ ({enemy_col},{enemy_row}) distance={distance}")
            if distance <= cc_range:
                add_console_log(game_state, f"FIGHT ELIGIBLE: Unit {unit['id']} can fight enemy {enemy_id} (dist {distance} <= melee_range {cc_range})")
                return True

    add_console_log(game_state, f"FIGHT NOT ELIGIBLE: Unit {unit['id']} has no enemies within melee_range {cc_range}")
    return False


def _ai_select_fight_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """
    AI target selection for fight phase using RewardMapper system.

    Fight priority (same as shooting): lowest HP, highest threat.
    """
    if not valid_targets:
        return ""

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        raise ValueError(f"Unit not found for fight target selection: unit_id={unit_id}")
    
    try:
        from ai.reward_mapper import RewardMapper

        reward_configs = require_key(game_state, "reward_configs")

        # Get unit type for config lookup
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        fighter_unit_type = unit["unitType"]
        fighter_agent_key = unit_registry.get_model_key(fighter_unit_type)

        # Get unit-specific config (required)
        unit_reward_config = require_key(reward_configs, fighter_agent_key)

        reward_mapper = RewardMapper(unit_reward_config)

        # Build target list for reward mapper (single lookup per tid)
        all_targets = []
        for tid in valid_targets:
            t = get_unit_by_id(game_state, tid)
            if t:
                all_targets.append(t)

        best_target = valid_targets[0]
        best_reward = -999999

        for target_id in valid_targets:
            target = get_unit_by_id(game_state, target_id)
            if not target:
                continue

            # Fight phase uses same priority logic as shooting
            # RewardMapper handles both via target priority calculation
            reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, False, game_state)

            if reward > best_reward:
                best_reward = reward
                best_target = target_id

        return best_target

    except Exception as e:
        from engine.game_utils import add_console_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        unit_id_str = str(unit.get("id", "unknown"))
        add_console_log(game_state, f"[TARGET SELECTION ERROR] E{episode} T{turn} Unit {unit_id_str}: target selection failed: {str(e)} - returning first valid target")
        return valid_targets[0]


def _fight_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete fight phase with player progression and turn management.

    CRITICAL: Fight is the LAST phase. After fight:
    - P0 ->    P1 movement phase
    - P1 ->       increment turn, P0 movement phase
    """
    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    charging_pool = require_key(game_state, "charging_activation_pool")
    active_alt_pool = require_key(game_state, "active_alternating_activation_pool")
    non_active_alt_pool = require_key(game_state, "non_active_alternating_activation_pool")
    add_debug_file_log(
        game_state,
        f"[POOL PRE-TRANSITION] E{episode} T{turn} fight charging_activation_pool={charging_pool} "
        f"active_alternating_activation_pool={active_alt_pool} "
        f"non_active_alternating_activation_pool={non_active_alt_pool}"
    )

    # Final cleanup
    game_state["charging_activation_pool"] = []
    game_state["active_alternating_activation_pool"] = []
    game_state["non_active_alternating_activation_pool"] = []

    # Clear alternation tracking state
    if "fight_alternating_turn" in game_state:
        del game_state["fight_alternating_turn"]

    # AI_TURN.md COMPLIANCE: Clear fight sub-phase at phase end
    game_state["fight_subphase"] = None

    # Console log
    add_console_log(game_state, "FIGHT PHASE COMPLETE")

    # Normalize current_player for deterministic comparisons
    current_player = require_key(game_state, "current_player")
    try:
        current_player_int = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player_int not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player_int}")
    game_state["current_player"] = current_player_int

    # Player progression logic
    if game_state["current_player"] == 1:
        # Player 1 complete ->    Player 2 command phase
        game_state["current_player"] = 2

        # CRITICAL: Do NOT call command_phase_start() directly - cascade loop handles it
        # The cascade loop in w40k_core.py will call command_phase_start() automatically
        # when it sees next_phase="command"

        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "command",
            "current_player": 2,
            "units_processed": len(require_key(game_state, "units_fought")),
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 2:
        # Player 2 complete -> Check if incrementing turn would exceed limit
        cfg = game_state["config"] if "config" in game_state else None
        tc = cfg["training_config"] if cfg and "training_config" in cfg else None
        max_turns = tc["max_turns_per_episode"] if tc and "max_turns_per_episode" in tc else None
        if max_turns and (game_state["turn"] + 1) > max_turns:
            # Primary objective scoring for P2 on round 5 (fight phase)
            state_manager = GameStateManager(require_key(game_state, "config"))
            state_manager.apply_primary_objective_scoring(game_state, "fight")
            # Incrementing would exceed turn limit - end game without incrementing
            game_state["turn_limit_reached"] = True
            game_state["game_over"] = True
            return {
                "phase_complete": True,
                "game_over": True,
                "turn_limit_reached": True,
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
        else:
            # Safe to increment turn and continue to P1's command phase
            game_state["turn"] += 1
            game_state["current_player"] = 1

            # CRITICAL: Do NOT call command_phase_start() directly - cascade loop handles it
            # The cascade loop in w40k_core.py will call command_phase_start() automatically
            # when it sees next_phase="command"

            return {
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "command",
                "current_player": 1,
                "new_turn": game_state["turn"],
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }

def fight_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Fight phase end - redirects to complete function"""
    return _fight_phase_complete(game_state)

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Fight phase handler action routing with 3 sub-phases.

    Sub-Phase 1: Charging units (charging_activation_pool)
    Sub-Phase 2: Alternating activation (non-active player first)
    Sub-Phase 3: Cleanup (remaining pool)
    """

    # Phase initialization on first call
    # AI_TURN.md COMPLIANCE: Direct field access
    if "phase" not in game_state:
        current_phase = None
    else:
        current_phase = game_state["phase"]

    if current_phase != "fight":
        fight_phase_start(game_state)

    # Check which sub-phase we're in
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "charging_activation_pool" not in game_state:
        charging_pool = []
    else:
        charging_pool = game_state["charging_activation_pool"]

    if "active_alternating_activation_pool" not in game_state:
        active_alternating = []
    else:
        active_alternating = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_alternating = []
    else:
        non_active_alternating = game_state["non_active_alternating_activation_pool"]

    # Determine current sub-phase
    if charging_pool:
        # Sub-phase 1: Charging units
        current_sub_phase = "charging"
        current_pool = charging_pool
    elif non_active_alternating or active_alternating:
        # Sub-phase 2: Alternating activation
        # AI_TURN.md Lines 737-846: ALTERNATING LOOP between non-active and active pools

        # Initialize alternation tracker if not set
        if "fight_alternating_turn" not in game_state:
            # AI_TURN.md Line 738: "Non-active player turn" goes FIRST
            game_state["fight_alternating_turn"] = "non_active"

        # Determine which pool to use based on whose turn it is
        current_turn = game_state["fight_alternating_turn"]
        current_player = require_key(game_state, "current_player")

        if current_turn == "non_active" and non_active_alternating:
            current_sub_phase = "alternating_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            # Check if there are units for the non-active player (opposite of current_player)
            opposite_player = 3 - current_player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == opposite_player:
                    eligible_units.append(uid)
            if not eligible_units and active_alternating:
                # Non-active player has no units, but active pool has units ->  switch to active
                current_sub_phase = "alternating_active"
                current_pool = active_alternating
            elif not eligible_units:
                # Neither player has units -> end phase
                return True, fight_phase_end(game_state)
        elif current_turn == "active" and active_alternating:
            current_sub_phase = "alternating_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == current_player:
                    eligible_units.append(uid)
            if not eligible_units and non_active_alternating:
                # Active player has no units, but non_active pool has units -> switch to non_active
                current_sub_phase = "alternating_non_active"
                current_pool = non_active_alternating
            elif not eligible_units:
                # Neither player has units -> end phase
                return True, fight_phase_end(game_state)
        elif non_active_alternating:
            # Active pool empty but non_active has units -> Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            opposite_player = 3 - current_player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == opposite_player:
                    eligible_units.append(uid)
            if not eligible_units:
                # Non-active player has no units in cleanup pool -> end phase
                return True, fight_phase_end(game_state)
        elif active_alternating:
            # Non-active pool empty but active has units -> Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and u.get("player") == current_player:
                    eligible_units.append(uid)
            if not eligible_units:
                # Active player has no units in cleanup pool -> end phase
                return True, fight_phase_end(game_state)
        else:
            # Both pools empty
            return True, fight_phase_end(game_state)
    else:
        # No units left - phase complete
        return True, fight_phase_end(game_state)

    # AI_TURN.md COMPLIANCE: Store current sub-phase for frontend eligibility display
    game_state["fight_subphase"] = current_sub_phase

    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]

    # Extract unit if not provided
    if unit is None:
        if "unitId" not in action:
            is_gym_training = config.get("gym_training_mode", False)
            if not is_gym_training:
                return False, {
                    "error": "unit_id_required",
                    "action": action_type,
                    "message": "unitId is required for human-controlled fight activation"
                }
            # Auto-select first unit from current pool for gym training
            # CRITICAL: Filter out dead units from pool before selection
            alive_units_in_pool = []
            for uid in current_pool:
                u = get_unit_by_id(game_state, uid)
                if u and is_unit_alive(str(u["id"]), game_state):
                    alive_units_in_pool.append(uid)
            if alive_units_in_pool:
                unit_id = alive_units_in_pool[0]
                unit = get_unit_by_id(game_state, unit_id)
                if not unit:
                    return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}
                # Remove dead units from pool
                for dead_unit_id in set(current_pool) - set(alive_units_in_pool):
                    _remove_dead_unit_from_fight_pools(game_state, dead_unit_id)
            else:
                return True, fight_phase_end(game_state)
        else:
            unit_id = str(action["unitId"])
            unit = get_unit_by_id(game_state, unit_id)
            if not unit:
                return False, {"error": "unit_not_found", "unitId": unit_id, "action": action_type}
    else:
        unit_id = unit["id"]

    # Validate unit is in current pool
    if unit_id not in current_pool:
        return False, {
            "error": "unit_not_in_current_pool",
            "unitId": unit_id,
            "current_sub_phase": current_sub_phase,
            "current_pool": current_pool
        }

    # Check for gym training mode and PvE AI mode
    is_gym_training = config.get("gym_training_mode", False)
    is_pve_ai = config.get("pve_mode", False) and unit and unit.get("player") == 2

    # GYM TRAINING / PvE AI: Auto-activate unit if not already active
    active_fight_unit = game_state.get("active_fight_unit")
    if (is_gym_training or is_pve_ai) and not active_fight_unit and action_type == "fight":
        activation_result = _handle_fight_unit_activation(game_state, unit, config)
        if not activation_result[0]:
            return activation_result  # Activation failed
        # Check if activation ended (no targets -> end_activation was called)
        # This happens when unit has no valid targets and was auto-skipped
        if activation_result[1].get("activation_ended") or activation_result[1].get("phase_complete"):
            return activation_result
        # Continue with fight action - targets should now be populated

    # NOTE: AI_TURN.md line 667 specifies invalid actions should call end_activation (ERROR, 0, PASS, FIGHT)
    # We follow this rule strictly - invalid actions are not converted to valid actions

    # Fight phase action routing
    if action_type == "activate_unit":
        return _handle_fight_unit_activation(game_state, unit, config)

    elif action_type == "fight":
        # Fight action with target selection
        # Auto-select target if not provided (for all modes: gym training, PvE AI, bots, etc.)
        if "targetId" not in action:
            valid_targets = game_state["valid_fight_targets"] if "valid_fight_targets" in game_state else []
            if valid_targets:
                if is_pve_ai:
                    # Use AI target selection for PvE AI
                    target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets)
                    if target_id:
                        action["targetId"] = target_id
                    else:
                        raise ValueError(f"AI target selection failed for unit {unit_id}")
                else:
                    # Auto-select first target (gym training, bots, etc.)
                    first_target = valid_targets[0]
                    action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
            else:
                # CRITICAL: Rebuild valid_targets if empty - valid_fight_targets may have been cleared
                # But only if unit has attacks remaining
                if require_key(unit, "ATTACK_LEFT") <= 0:
                    # No attacks left - skip this unit (engine-determined, not agent choice)
                    result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
                    game_state["active_fight_unit"] = None
                    game_state["valid_fight_targets"] = []
                    result["action"] = "skip"
                    result["skip_reason"] = "no_valid_actions"
                    result["phase"] = "fight"
                    result["unitId"] = unit_id
                    if result.get("phase_complete"):
                        phase_result = _fight_phase_complete(game_state)
                        result.update(phase_result)
                    else:
                        _toggle_fight_alternation(game_state)
                        _update_fight_subphase(game_state)
                    return True, result
                
                # Unit has attacks - rebuild valid_targets if empty
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
                if valid_targets:
                    # Found targets - update game_state and continue with attack
                    game_state["valid_fight_targets"] = valid_targets
                    # Auto-select first target (gym training, bots, etc.)
                    first_target = valid_targets[0]
                    action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
                    # Continue to attack execution below (skip the PASS logic)
                else:
                    # DEBUG: Check if unit is adjacent to enemy but not attacking
                    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                    if "episode_number" in game_state and "turn" in game_state:
                        episode = game_state["episode_number"]
                        turn = game_state["turn"]
                        if "console_logs" not in game_state:
                            game_state["console_logs"] = []
                        if is_adjacent:
                            attack_left = require_key(unit, "ATTACK_LEFT")
                            log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight execute_action: Unit {unit_id} ADJACENT to enemy but NO TARGETS (ATTACK_LEFT={attack_left}) - skipping without attack"
                            add_console_log(game_state, log_msg)
                            safe_print(game_state, log_msg)
                    
                    # No targets - skip this unit (e.g. target died before activation)
                    result = end_activation(
                        game_state, unit,
                        PASS, 1, PASS, FIGHT, 0
                    )
                    # CRITICAL: Clear active_fight_unit so next unit can be activated
                    game_state["active_fight_unit"] = None
                    game_state["valid_fight_targets"] = []
                    
                    result["action"] = "skip"
                    result["skip_reason"] = "no_valid_actions"
                    result["phase"] = "fight"
                    result["unitId"] = unit_id

                    if result.get("phase_complete"):
                        # CRITICAL: Preserve action before merging phase transition
                        preserved_action = result.get("action")
                        preserved_unit_id = result.get("unitId")
                        
                        phase_result = _fight_phase_complete(game_state)
                        # Merge phase transition info into result
                        result.update(phase_result)
                        
                        # CRITICAL: Restore preserved action for logging
                        if preserved_action is not None:
                            result["action"] = preserved_action
                        elif "action" not in result:
                            result["action"] = "wait"
                        if preserved_unit_id:
                            result["unitId"] = preserved_unit_id
                    else:
                        _toggle_fight_alternation(game_state)
                        _update_fight_subphase(game_state)
                    return True, result
        
        # CRITICAL: Ensure targetId is set before attack execution
        if "targetId" not in action:
            # This should not happen if code above is correct, but add safety check
            valid_targets = game_state["valid_fight_targets"] if "valid_fight_targets" in game_state else []
            if not valid_targets:
                valid_targets = _fight_build_valid_target_pool(game_state, unit)
            if valid_targets:
                first_target = valid_targets[0]
                action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
            else:
                # No targets available - skip (e.g. target died before activation)
                result = end_activation(game_state, unit, PASS, 1, PASS, FIGHT, 0)
                game_state["active_fight_unit"] = None
                game_state["valid_fight_targets"] = []
                result["action"] = "skip"
                result["skip_reason"] = "no_valid_actions"
                result["phase"] = "fight"
                result["unitId"] = unit_id
                if result.get("phase_complete"):
                    phase_result = _fight_phase_complete(game_state)
                    result.update(phase_result)
                else:
                    _toggle_fight_alternation(game_state)
                    _update_fight_subphase(game_state)
                return True, result
        
        target_id = action["targetId"]
        return _handle_fight_attack(game_state, unit, target_id, config)

    elif action_type == "postpone":
        # Postpone action (only valid if ATTACK_LEFT = CC_NB)
        return _handle_fight_postpone(game_state, unit)

    elif action_type == "left_click":
        # Human player click handling
        if "clickTarget" not in action:
            click_target = "elsewhere"
        else:
            click_target = action["clickTarget"]

        if click_target == "target" and "targetId" in action:
            return _handle_fight_attack(game_state, unit, action["targetId"], config)
        elif click_target == "friendly_unit" and "targetId" in action:
            # Switch unit (only if ATTACK_LEFT = CC_NB for current unit)
            return _handle_fight_unit_switch(game_state, unit, action["targetId"])
        elif click_target == "active_unit":
            return True, {"action": "no_effect"}
        else:
            return True, {"action": "continue_selection"}

    elif action_type == "right_click":
        # Right click = postpone (if ATTACK_LEFT = CC_NB)
        return _handle_fight_postpone(game_state, unit)

    elif action_type == "invalid":
        # AI_TURN.md line 667: INVALID ACTION ERROR -> end_activation (ERROR, 0, PASS, FIGHT)
        # We follow AI_TURN.md strictly. The _rebuild_alternating_pools_for_fight call in end_activation
        # is skipped for this case to prevent the unit from being re-added to the pool.
        result = end_activation(
            game_state, unit,
            ERROR,         # Arg1: ERROR logging (per AI_TURN.md line 667)
            0,             # Arg2: NO step increment (per AI_TURN.md line 667)
            PASS,          # Arg3: PASS tracking (per AI_TURN.md line 667)
            FIGHT,         # Arg4: Remove from fight pool
            1              # Arg5: Error logging
        )
        result["invalid_action_penalty"] = True
        # CRITICAL: No default value - require explicit attempted_action
        attempted_action = action.get("attempted_action")
        if attempted_action is None:
            raise ValueError(f"Action missing 'attempted_action' field: {action}")
        result["attempted_action"] = attempted_action

        # Check if ALL pools are empty ->  phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            if preserved_action:
                result["action"] = preserved_action
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        # DEBUG: Log final result before return (ATTACK_LEFT > 0 case)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING (ATTACK_LEFT>0) - result['action']={result.get('action')} result['unitId']={result.get('unitId')} result_keys={list(result.keys())}"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)

        return True, result

    else:
        # Only valid actions are fight, postpone
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "fight"}


def _handle_fight_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle fight unit activation start.

    Initialize unit for fighting:
    - Set ATTACK_LEFT = CC_NB
    - Build valid target pool (enemies adjacent within CC_RNG)
    - Return waiting_for_player if targets exist
    """
    unit_id = unit["id"]

    # CRITICAL: Clear fight_attack_results at the start of each new unit activation
    # This ensures attacks from different units are not mixed together
    game_state["fight_attack_results"] = []

    # Set ATTACK_LEFT = CC_NB at activation start
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    cc_weapons = unit["CC_WEAPONS"] if "CC_WEAPONS" in unit else []
    if cc_weapons:
        selected_idx = unit["selectedCcWeaponIndex"] if "selectedCcWeaponIndex" in unit else 0
        if selected_idx < 0 or selected_idx >= len(cc_weapons):
            raise IndexError(f"Invalid selectedCcWeaponIndex {selected_idx} for unit {unit['id']}")
        weapon = cc_weapons[selected_idx]
        nb_roll = resolve_dice_value(require_key(weapon, "NB"), "fight_nb_init")
        unit["ATTACK_LEFT"] = nb_roll
        unit["_current_fight_nb"] = nb_roll
    else:
        unit["ATTACK_LEFT"] = 0  # Pas d'armes melee

    # DEBUG: Log unit activation
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight unit_activation: Unit {unit_id} ACTIVATED with ATTACK_LEFT={unit['ATTACK_LEFT']}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    # Build valid target pool (enemies adjacent within CC_RNG)
    valid_targets = _fight_build_valid_target_pool(game_state, unit)
    
    # DEBUG: Log valid targets
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight unit_activation: Unit {unit_id} valid_targets={valid_targets} count={len(valid_targets)}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    if not valid_targets:
        # DEBUG: Check if unit is adjacent to enemy but not attacking
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            if is_adjacent and unit["ATTACK_LEFT"] > 0:
                log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight unit_activation: Unit {unit_id} ADJACENT to enemy but NO VALID TARGETS (ATTACK_LEFT={unit['ATTACK_LEFT']}) - ending without attack"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        
        # No targets - end activation with PASS
        # ATTACK_LEFT = CC_NB? YES -> no attack -> end_activation (PASS, 1, PASS, FIGHT)
        result = end_activation(
            game_state, unit,
            PASS,          # Arg1: Pass logging
            1,             # Arg2: +1 step increment
            PASS,          # Arg3: No tracking (no attack made)
            FIGHT,         # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []
        
        # CRITICAL: Set action for logging (wait action since no attack was made)
        result["action"] = "wait"
        result["phase"] = "fight"
        result["unitId"] = unit_id

        # Check if ALL pools are empty -> phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            # Always restore action (even if None, to ensure it's not overwritten by phase_result)
            if preserved_action is not None:
                result["action"] = preserved_action
            elif "action" not in result:
                # If action was not preserved and phase_result doesn't have it, set default
                result["action"] = "wait"
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        # DEBUG: Log final result before return (ATTACK_LEFT = 0 case)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING (ATTACK_LEFT=0) - result['action']={result.get('action')} result['unitId']={result.get('unitId')} result_keys={list(result.keys())}"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)

        return True, result

    # Check for PvE AI or gym training auto-execution (similar to shooting phase)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 2
    is_gym_training = config.get("gym_training_mode", False) and unit and unit["player"] == 1
    
    if (is_pve_ai or is_gym_training) and valid_targets:
        # AUTO-FIGHT: PvE AI or gym training auto-selects target and executes attack
        if is_pve_ai:
            target_id = _ai_select_fight_target(game_state, unit_id, valid_targets)
        else:
            # Gym training: select first target
            target_id = valid_targets[0] if valid_targets else None
        if target_id:
            # Execute fight attack directly and return result
            return _handle_fight_attack(game_state, unit, target_id, config)
        # No valid target selected - fall through to waiting_for_player

    # Targets exist - return waiting_for_player (for human players or if AI selection failed)
    game_state["active_fight_unit"] = unit_id
    game_state["valid_fight_targets"] = valid_targets

    return True, {
        "unit_activated": True,
        "unitId": unit_id,
        "valid_targets": valid_targets,
        "ATTACK_LEFT": unit["ATTACK_LEFT"],
        "waiting_for_player": True,
        "action": "wait"  # CRITICAL: Set action for logging (waiting for target selection)
    }


def _toggle_fight_alternation(game_state: Dict[str, Any]) -> None:
    """
    AI_TURN.md Lines 762-764, 844-846: Toggle alternation turn after activation.

    After a unit completes its activation in alternating phase, switch to other player.
    Only toggles if BOTH pools have units (true alternation).
    If only one pool has units, don't toggle (cleanup phase).
    """
    # Check if we're in alternating phase
    if "fight_alternating_turn" not in game_state:
        return  # Not in alternating phase yet

    # AI_TURN.md COMPLIANCE: Direct field access
    if "active_alternating_activation_pool" not in game_state:
        active_pool = []
    else:
        active_pool = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_pool = []
    else:
        non_active_pool = game_state["non_active_alternating_activation_pool"]

    # AI_TURN.md Lines 762-764, 844-846: "Check: Either pool empty?"
    # If BOTH pools have units -> continue alternating (toggle)
    # If ONE pool empty ->  exit loop to cleanup phase (don't toggle)
    if active_pool and non_active_pool:
        # Both pools have units -> toggle
        current_turn = game_state["fight_alternating_turn"]
        if current_turn == "non_active":
            game_state["fight_alternating_turn"] = "active"
        else:
            game_state["fight_alternating_turn"] = "non_active"
    # else: One pool empty -> cleanup phase, don't toggle


def _update_fight_subphase(game_state: Dict[str, Any]) -> None:
    """
    Recalculate fight_subphase after pool changes.

    Called after end_activation to update subphase when pools become empty.
    """
    # AI_TURN.md COMPLIANCE: Direct field access
    if "charging_activation_pool" not in game_state:
        charging_pool = []
    else:
        charging_pool = game_state["charging_activation_pool"]

    if "active_alternating_activation_pool" not in game_state:
        active_alternating = []
    else:
        active_alternating = game_state["active_alternating_activation_pool"]

    if "non_active_alternating_activation_pool" not in game_state:
        non_active_alternating = []
    else:
        non_active_alternating = game_state["non_active_alternating_activation_pool"]

    # Determine current sub-phase based on which pools have units
    if charging_pool:
        game_state["fight_subphase"] = "charging"
    elif non_active_alternating or active_alternating:
        # Alternating phase - check whose turn
        if "fight_alternating_turn" not in game_state:
            # Initialize if not set (first time entering alternating)
            game_state["fight_alternating_turn"] = "non_active"

        current_turn = game_state["fight_alternating_turn"]

        if current_turn == "non_active" and non_active_alternating:
            game_state["fight_subphase"] = "alternating_non_active"
        elif current_turn == "active" and active_alternating:
            game_state["fight_subphase"] = "alternating_active"
        elif non_active_alternating:
            # Active pool empty, only non-active left
            game_state["fight_subphase"] = "cleanup_non_active"
        elif active_alternating:
            # Non-active pool empty, only active left
            game_state["fight_subphase"] = "cleanup_active"
        else:
            game_state["fight_subphase"] = None
    else:
        # All pools empty
        game_state["fight_subphase"] = None


def _fight_build_valid_target_pool(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """
    Build valid fight target pool.

    Valid targets:
    - Enemy units
    - Alive (in units_cache)
    - Adjacent to attacker (within melee range distance)

    NO LINE OF SIGHT CHECK (fight doesn't need LoS)
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_player = int(unit["player"]) if unit["player"] is not None else None

    valid_targets = []

    units_cache = require_key(game_state, "units_cache")
    for target_id, cache_entry in units_cache.items():
        # Enemy check
        if int(cache_entry["player"]) == unit_player:
            continue

        # Adjacent check (within melee range)
        target_col, target_row = require_unit_position(target_id, game_state)
        distance = calculate_hex_distance(unit_col, unit_row, target_col, target_row)
        if distance > cc_range:
            continue

        # Valid target
        valid_targets.append(target_id)

    return valid_targets


def _handle_fight_attack(game_state: Dict[str, Any], unit: Dict[str, Any], target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle fight attack execution.

    Execute attack_sequence(CC) using CC_* stats:
    - CC_ATK (to-hit roll)
    - CC_STR vs target TOUGH (wound roll)
    - CC_AP vs target SAVE (save roll)
    - CC_DMG (damage dealt)

    Decrement ATTACK_LEFT after each attack.
    Continue until ATTACK_LEFT = 0 or no valid targets remain.
    """
    unit_id = unit["id"]

    # Validate ATTACK_LEFT
    if "ATTACK_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'ATTACK_LEFT' field: {unit}")
    if unit["ATTACK_LEFT"] <= 0:
        return False, {"error": "no_attacks_remaining", "unitId": unit_id, "action": "combat"}

    # Validate target is valid
    valid_targets = _fight_build_valid_target_pool(game_state, unit)
    if target_id not in valid_targets:
        return False, {"error": "invalid_target", "targetId": target_id, "valid_targets": valid_targets, "action": "combat"}
    
    # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cette cible ===
    target = get_unit_by_id(game_state, target_id)
    if not target:
        return False, {"error": "target_not_found", "targetId": target_id, "action": "combat"}
    
    from engine.ai.weapon_selector import select_best_melee_weapon
    best_weapon_idx = select_best_melee_weapon(unit, target, game_state)
    
    if best_weapon_idx >= 0:
        unit["selectedCcWeaponIndex"] = best_weapon_idx
        # CRITICAL: Only initialize ATTACK_LEFT if it's 0 AND we're at the start of activation
        # Don't reset ATTACK_LEFT during attack execution (it should already be set)
        weapon = unit["CC_WEAPONS"][best_weapon_idx]
        current_attack_left = require_key(unit, "ATTACK_LEFT")
        # Only reset if ATTACK_LEFT is 0 and we haven't started attacking yet
        # This prevents infinite loops where ATTACK_LEFT is reset after being decremented
        far = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
        if current_attack_left == 0 and not far:
            nb_roll = resolve_dice_value(require_key(weapon, "NB"), "fight_nb_auto_select")
            unit["ATTACK_LEFT"] = nb_roll
            unit["_current_fight_nb"] = nb_roll
    else:
        # Pas d'armes disponibles
        unit["ATTACK_LEFT"] = 0
        return False, {"error": "no_weapons_available", "unitId": unit["id"], "action": "combat"}
    # === FIN NOUVEAU ===

    # Initialize accumulated attack results list for this unit's activation
    # This stores ALL attacks made during the weapon NB attack loop
    # CRITICAL: Only initialize if not already exists (don't clear on recursive calls)
    # fight_attack_results is cleared at the start of unit activation in _handle_fight_unit_activation
    if "fight_attack_results" not in game_state:
        game_state["fight_attack_results"] = []

    # Execute attack sequence using selected weapon
    attack_result = _execute_fight_attack_sequence(game_state, unit, target_id)

    # DEBUG: Log attack execution
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        damage = attack_result["damage"] if "damage" in attack_result else 0
        target_died = attack_result["target_died"] if "target_died" in attack_result else False
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight attack_executed: Unit {unit_id} -> Unit {target_id} damage={damage} target_died={target_died}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        # DEBUG: Verify log was added
        from engine.game_utils import conditional_debug_print
        conditional_debug_print(game_state, f"[DEBUG] Added attack_executed log to console_logs (count={len(game_state['console_logs'])})")
    else:
        # DEBUG: Log why condition failed
        missing_keys = []
        if "episode_number" not in game_state:
            missing_keys.append("episode_number")
        if "turn" not in game_state:
            missing_keys.append("turn")
        from engine.game_utils import conditional_debug_print
        conditional_debug_print(game_state, f"[DEBUG] attack_executed log NOT added - missing keys: {missing_keys}")

    # Store this attack result with metadata for step logging
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(unit)
    total_attacks = require_key(unit, "_current_fight_nb") if selected_weapon else 0
    
    attack_result["attackerId"] = unit_id
    attack_result["targetId"] = target_id
    attack_result["attack_number"] = total_attacks - unit["ATTACK_LEFT"]  # 1-indexed (before decrement)
    attack_result["total_attacks"] = total_attacks
    game_state["fight_attack_results"].append(attack_result)
    
    # DEBUG: Log accumulation in fight_attack_results
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        far_list = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
        total_results = len(far_list)
        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight attack_executed: Unit {unit_id} fight_attack_results count={total_results}"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    # Decrement ATTACK_LEFT
    unit["ATTACK_LEFT"] -= 1

    # Check if more attacks remain
    if unit["ATTACK_LEFT"] > 0:
        # Rebuild target pool (target may have died)
        valid_targets_after = _fight_build_valid_target_pool(game_state, unit)

        if valid_targets_after:
            # More attacks and targets available
            # Auto-continue attack loop for gym training, PvE AI, and bots (all non-human players)
            is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
            is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 2
            # Bots (player 2) should also auto-continue attacks like gym training
            is_bot = unit and unit["player"] == 2 and not is_pve_ai

            if is_gym_training or is_pve_ai or is_bot:
                # GYM TRAINING / PvE AI: Auto-continue attack loop until ATTACK_LEFT = 0 or no targets
                # Select next target (use AI selection logic)
                next_target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets_after)
                if next_target_id:
                    # CRITICAL: Capture fight_attack_results BEFORE recursive call
                    # The recursive call may clear fight_attack_results, so we need to preserve
                    # the attacks accumulated so far in this activation
                    far_snap = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
                    attacks_before_recursive = list(far_snap)
                    
                    # Recursively call to continue the attack loop
                    recursive_result = _handle_fight_attack(game_state, unit, next_target_id, config)
                    if isinstance(recursive_result, tuple) and len(recursive_result) == 2:
                        rec_success, rec_result = recursive_result
                        if rec_success and isinstance(rec_result, dict):
                            # CRITICAL: Ensure all_attack_results includes ALL accumulated attacks
                            # Merge attacks from before recursive call with recursive results
                            recursive_attack_results = rec_result["all_attack_results"] if "all_attack_results" in rec_result else []
                            
                            # Combine: attacks before recursive + recursive results
                            # Remove duplicates by checking targetId and attack_number
                            seen_attacks = {(ar.get("targetId"), ar.get("attack_number")) for ar in attacks_before_recursive}
                            combined_results = list(attacks_before_recursive)
                            for ar in recursive_attack_results:
                                # CRITICAL: Validate ar has all required fields before adding
                                required_fields = ["hit_roll", "wound_roll", "save_roll", "damage", "hit_success", "wound_success", "save_success", "hit_target", "wound_target", "save_target", "target_died", "weapon_name"]
                                missing_fields = [field for field in required_fields if field not in ar]
                                if missing_fields:
                                    raise KeyError(
                                        f"recursive_attack_results contains incomplete attack_result: missing {missing_fields}. "
                                        f"attack_result keys: {list(ar.keys())}. "
                                        f"unit_id={unit_id}, target_id={ar.get('targetId', 'unknown')}"
                                    )
                                
                                key = (ar.get("targetId"), ar.get("attack_number"))
                                if key not in seen_attacks:
                                    combined_results.append(ar)
                                    seen_attacks.add(key)
                            
                            # Update result with combined attack results
                            rec_result["all_attack_results"] = combined_results
                            
                            # CRITICAL: Ensure action is set to "combat" when there are attack results
                            # This ensures attacks are logged even if recursive result had different action
                            if combined_results:
                                rec_result["action"] = "combat"
                                rec_result["phase"] = "fight"
                                if "unitId" not in rec_result:
                                    rec_result["unitId"] = unit_id
                            
                            # DEBUG: Log the merge
                            if "episode_number" in game_state and "turn" in game_state:
                                episode = game_state["episode_number"]
                                turn = game_state["turn"]
                                if "console_logs" not in game_state:
                                    game_state["console_logs"] = []
                                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: MERGED recursive results - before={len(attacks_before_recursive)} recursive={len(recursive_attack_results)} combined={len(combined_results)}"
                                add_console_log(game_state, log_msg)
                                safe_print(game_state, log_msg)
                            else:
                                # CRITICAL: If recursive call failed, preserve attacks_before_recursive
                                # Restore fight_attack_results from attacks_before_recursive to ensure they're not lost
                                if attacks_before_recursive:
                                    game_state["fight_attack_results"] = list(attacks_before_recursive)
                                    # Ensure result includes all_attack_results even if recursive call failed
                                    if isinstance(rec_result, dict):
                                        rec_result["all_attack_results"] = list(attacks_before_recursive)
                                        # CRITICAL: Ensure action is set to "combat" when there are attack results
                                        if attacks_before_recursive:
                                            rec_result["action"] = "combat"
                                            rec_result["phase"] = "fight"
                                            if "unitId" not in rec_result:
                                                rec_result["unitId"] = unit_id
                    else:
                        # CRITICAL: If recursive_result is invalid, preserve attacks_before_recursive
                        # Restore fight_attack_results to ensure they're not lost
                        if attacks_before_recursive:
                            game_state["fight_attack_results"] = list(attacks_before_recursive)
                            # CRITICAL: If recursive_result is not a valid tuple, create a valid result with all_attack_results
                            if not isinstance(recursive_result, tuple) or len(recursive_result) != 2:
                                # Create a valid result structure with preserved attacks
                                recursive_result = (True, {
                                    "action": "combat",
                                    "unitId": unit_id,
                                    "all_attack_results": list(attacks_before_recursive),
                                    "error": "recursive_call_failed"
                                })
                            else:
                                # recursive_result is a tuple but rec_result might not have all_attack_results
                                rec_success, rec_result = recursive_result
                                if isinstance(rec_result, dict) and "all_attack_results" not in rec_result:
                                    rec_result["all_attack_results"] = list(attacks_before_recursive)
                                    recursive_result = (rec_success, rec_result)
                    
                    if isinstance(recursive_result, tuple) and len(recursive_result) == 2:
                        _, rec_result = recursive_result
                        if isinstance(rec_result, dict) and rec_result.get("all_attack_results"):
                            game_state["fight_attack_results"] = []
                    return recursive_result
                # No valid target selected - fall through to end activation

            else:
                # HUMAN PLAYER: Return waiting_for_player for manual target selection
                # CRITICAL: Include all_attack_results even when waiting_for_player
                # This ensures attacks already executed are logged to step.log
                # CRITICAL: Always get ALL attacks from fight_attack_results
                fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
                if not fight_attack_results and attack_result:
                    raise ValueError(
                        f"fight_attack_results is empty despite attack_result for unit {unit_id}"
                    )
                all_attack_results = fight_attack_results
                # CRITICAL ASSERTION: If we have attack_result, it MUST be in all_attack_results
                if attack_result and attack_result not in all_attack_results:
                    raise ValueError(
                        f"attack_result missing from all_attack_results for unit {unit_id}"
                    )
                # DEBUG: Log all_attack_results being returned with waiting_for_player
                if "episode_number" in game_state and "turn" in game_state:
                    episode = game_state["episode_number"]
                    turn = game_state["turn"]
                    if "console_logs" not in game_state:
                        game_state["console_logs"] = []
                    log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: RETURNING waiting_for_player=True with all_attack_results count={len(all_attack_results)} for Unit {unit_id}"
                    add_console_log(game_state, log_msg)
                    safe_print(game_state, log_msg)
                    for i, ar in enumerate(all_attack_results):
                        # CRITICAL: No default values - require explicit targetId and damage
                        target_id = ar.get("targetId")
                        if target_id is None:
                            raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
                        damage = ar.get("damage")
                        if damage is None:
                            raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
                        log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: waiting_for_player attack[{i}] -> Unit {target_id} damage={damage}"
                        add_console_log(game_state, log_msg)
                        safe_print(game_state, log_msg)
                if all_attack_results:
                    game_state["fight_attack_results"] = []
                return True, {
                    "attack_executed": True,
                    "attack_result": attack_result,
                    "unitId": unit["id"],
                    "ATTACK_LEFT": unit["ATTACK_LEFT"],
                    "valid_targets": valid_targets_after,
                    "waiting_for_player": True,
                    "action": "combat",  # CRITICAL: Must be "combat" for step_logger
                    "fight_subphase": require_key(game_state, "fight_subphase"),
                    "all_attack_results": list(all_attack_results) if all_attack_results else []  # Copie explicite pour sécurité
                }
        # No more targets or no valid target selected - fall through to end activation

        # DEBUG: Check if unit is adjacent to enemy but has no more targets
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            if is_adjacent and unit["ATTACK_LEFT"] > 0:
                log_msg = f"[FIGHT DEBUG] ⚠️ E{episode} T{turn} fight attack: Unit {unit_id} ADJACENT to enemy but NO MORE TARGETS (ATTACK_LEFT={unit['ATTACK_LEFT']}) - ending without completing all attacks"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        
        # No more targets - end activation
        # ATTACK_LEFT > 0 but no targets -> end_activation (ACTION, 1, FIGHT, FIGHT)
        result = end_activation(
            game_state, unit,
            ACTION,        # Arg1: Log action
            1,             # Arg2: +1 step
            FIGHT,         # Arg3: FIGHT tracking
            FIGHT,         # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []

        # CRITICAL: Set action BEFORE checking phase_complete to ensure it's preserved
        result["action"] = "combat"  # Must be "combat" for step_logger (not "fight")
        result["phase"] = "fight"  # For metrics tracking
        result["unitId"] = unit_id  # For step_logger
        result["waiting_for_player"] = False  # Combat resolved, no further input
        result["targetId"] = target_id  # For reward calculator
        result["attack_result"] = attack_result
        result["target_died"] = attack_result["target_died"] if "target_died" in attack_result else False  # For metrics tracking
        result["reason"] = "no_more_targets"
        result["fight_subphase"] = require_key(game_state, "fight_subphase")

        # Include ALL attack results from this activation for step logging
        # CRITICAL: Always use fight_attack_results - it should contain ALL attacks from this activation
        fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
        if not fight_attack_results and attack_result:
            raise ValueError(
                f"fight_attack_results is empty despite attack_result for unit {unit_id}"
            )
        result["all_attack_results"] = list(fight_attack_results)  # Copie explicite pour sécurité
        # DEBUG: Log all_attack_results being set in result (no_more_targets path)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: SETTING all_attack_results count={len(result['all_attack_results'])} for Unit {unit_id} (no_more_targets)"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            for i, ar in enumerate(result["all_attack_results"]):
                # CRITICAL: No default values - require explicit targetId and damage
                target_id = ar.get("targetId")
                if target_id is None:
                    raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
                damage = ar.get("damage")
                if damage is None:
                    raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: no_more_targets attack[{i}] -> Unit {target_id} damage={damage}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        # Clear accumulated results for next unit
        game_state["fight_attack_results"] = []

        # Check if ALL pools are empty -> phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            # action is already set above, so preserved_action will be "combat"
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            # DEBUG: Log preservation before phase transition
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state["episode_number"]
                turn = game_state["turn"]
                if "console_logs" not in game_state:
                    game_state["console_logs"] = []
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: BEFORE phase_complete - preserved_action={preserved_action} preserved_unit_id={preserved_unit_id} result_keys={list(result.keys())}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            # ALWAYS restore action, even if preserved_action is None (defensive)
            result["action"] = preserved_action if preserved_action else "combat"
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
            
            # DEBUG: Log restoration after phase transition
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state["episode_number"]
                turn = game_state["turn"]
                if "console_logs" not in game_state:
                    game_state["console_logs"] = []
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: AFTER phase_complete - result['action']={result.get('action')} result_keys={list(result.keys())}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result
    else:
        # ATTACK_LEFT = 0 - end activation
        # end_activation (ACTION, 1, FIGHT, FIGHT)
        result = end_activation(
            game_state, unit,
            ACTION,        # Arg1: Log action
            1,             # Arg2: +1 step
            FIGHT,         # Arg3: FIGHT tracking
            FIGHT,         # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []

        result["action"] = "combat"  # Must be "combat" for step_logger (not "fight")
        result["phase"] = "fight"  # For metrics tracking
        result["unitId"] = unit_id  # For step_logger
        result["waiting_for_player"] = False  # Combat resolved, no further input
        result["targetId"] = target_id  # For reward calculator
        result["attack_result"] = attack_result
        result["target_died"] = attack_result.get("target_died", False)  # For metrics tracking
        result["reason"] = "attacks_complete"
        result["fight_subphase"] = require_key(game_state, "fight_subphase")

        # Include ALL attack results from this activation for step logging
        # CRITICAL: fight_attack_results MUST contain all attacks from this activation
        # If it's empty, something is wrong - but we still need to return attack_result
        fight_attack_results = game_state["fight_attack_results"] if "fight_attack_results" in game_state else []
        if not fight_attack_results:
            # This should never happen - all attacks should be in fight_attack_results
            # But if it does, at least return the current attack_result
            if attack_result:
                fight_attack_results = [attack_result]
        result["all_attack_results"] = list(fight_attack_results)  # Copie explicite pour sécurité
        # DEBUG: Log all_attack_results being set in result (attacks_complete path)
        if "episode_number" in game_state and "turn" in game_state:
            episode = game_state["episode_number"]
            turn = game_state["turn"]
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: SETTING all_attack_results count={len(result['all_attack_results'])} for Unit {unit_id} (attacks_complete)"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            for i, ar in enumerate(result["all_attack_results"]):
                # CRITICAL: No default values - require explicit targetId and damage
                target_id = ar.get("targetId")
                if target_id is None:
                    raise ValueError(f"attack_result[{i}] missing 'targetId' field: {ar}")
                damage = ar.get("damage")
                if damage is None:
                    raise ValueError(f"attack_result[{i}] missing 'damage' field: {ar}")
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: attacks_complete attack[{i}] -> Unit {target_id} damage={damage}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        # Clear accumulated results for next unit
        game_state["fight_attack_results"] = []

        # Check if ALL pools are empty -> phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            # CRITICAL: Preserve action and all_attack_results before merging phase transition
            preserved_action = result.get("action")
            preserved_attack_results = result.get("all_attack_results")
            preserved_unit_id = result.get("unitId")
            
            # DEBUG: Log preservation before phase transition
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state["episode_number"]
                turn = game_state["turn"]
                if "console_logs" not in game_state:
                    game_state["console_logs"] = []
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: BEFORE phase_complete (ATTACK_LEFT=0) - preserved_action={preserved_action} preserved_unit_id={preserved_unit_id} result_keys={list(result.keys())}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
            
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
            
            # CRITICAL: Restore preserved combat data for logging
            # ALWAYS restore action, even if preserved_action is None (defensive)
            result["action"] = preserved_action if preserved_action else "combat"
            if preserved_attack_results:
                result["all_attack_results"] = preserved_attack_results
            if preserved_unit_id:
                result["unitId"] = preserved_unit_id
            
            # DEBUG: Log restoration after phase transition
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state["episode_number"]
                turn = game_state["turn"]
                if "console_logs" not in game_state:
                    game_state["console_logs"] = []
                log_msg = f"[FIGHT DEBUG] E{episode} T{turn} fight _handle_fight_attack: AFTER phase_complete (ATTACK_LEFT=0) - result['action']={result.get('action')} result_keys={list(result.keys())}"
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result


def _handle_fight_postpone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle postpone action.

    CRITICAL: Can ONLY postpone if ATTACK_LEFT = CC_NB (no attacks made yet)
    If unit has already attacked, must complete activation.
    """
    unit_id = unit["id"]

    # Check ATTACK_LEFT = weapon NB?
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    if "ATTACK_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'ATTACK_LEFT' field: {unit}")
    
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(unit)
    if not selected_weapon:
        return False, {"error": "no_melee_weapon", "unitId": unit["id"], "action": "combat"}
    
    if unit["ATTACK_LEFT"] == require_key(unit, "_current_fight_nb"):
        # YES -> Postpone allowed
        # Do NOT call end_activation - just return postpone signal
        # Unit stays in pool for later activation
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "postpone_allowed": True
        }
    else:
        # NO -> Must complete activation
        return False, {
            "error": "postpone_not_allowed",
            "reason": "unit_has_already_attacked",
            "ATTACK_LEFT": unit["ATTACK_LEFT"],
            "CC_NB": unit["CC_NB"]
        }


def _handle_fight_unit_switch(game_state: Dict[str, Any], current_unit: Dict[str, Any], new_unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Handle unit switching during fight phase.

    Can only switch if current unit has ATTACK_LEFT = CC_NB (hasn't attacked yet).
    Otherwise must complete current unit's activation.
    """
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if postpone is allowed using selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(current_unit)
    if not selected_weapon:
        postpone_allowed = False
    else:
        postpone_allowed = (current_unit["ATTACK_LEFT"] == require_key(current_unit, "_current_fight_nb"))

    if postpone_allowed:
        # Switch to new unit
        new_unit = get_unit_by_id(game_state, new_unit_id)
        if not new_unit:
            return False, {"error": "unit_not_found", "unitId": new_unit_id, "action": "combat"}

        return _handle_fight_unit_activation(game_state, new_unit, {})
    else:
        # Must complete current unit
        return False, {
            "error": "must_complete_current_unit",
            "current_unit": current_unit["id"],
            "ATTACK_LEFT": current_unit["ATTACK_LEFT"]
        }


def _execute_fight_attack_sequence(game_state: Dict[str, Any], attacker: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(CC) using close combat stats.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    """
    import random
    from engine.utils.weapon_helpers import get_selected_melee_weapon

    target = get_unit_by_id(game_state, target_id)
    if not target:
        raise ValueError(f"Target unit not found: {target_id}")
    target_coords = get_unit_coordinates(target)

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get selected weapon
    weapon = get_selected_melee_weapon(attacker)
    if not weapon:
        raise ValueError(f"Attacker {attacker['id']} has no selected melee weapon")

    attacker_id = attacker["id"]

    # Initialize result variables
    wound_roll = 0
    wound_target = 0
    wound_success = False
    save_roll = 0
    save_target = 0
    save_success = False
    damage_dealt = 0
    target_died = False

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name in attack_log
    weapon_name = weapon.get("display_name", "")
    weapon_prefix = f" with [{weapon_name}]" if weapon_name else ""
    
    # Hit roll -> hit_roll >= weapon.ATK
    hit_roll = random.randint(1, 6)
    hit_target = weapon["ATK"]
    hit_success = hit_roll >= hit_target

    if not hit_success:
        # MISS case
        attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) : MISSED !"
    else:
        # HIT -> Continue to wound roll
        wound_roll = random.randint(1, 6)
        wound_target = _calculate_wound_target(weapon["STR"], target["T"])
        wound_success = wound_roll >= wound_target

        if not wound_success:
            # FAIL TO WOUND case
            attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) : FAILED !"
        else:
            # WOUND -> Continue to save roll
            save_roll = random.randint(1, 6)
            save_target = _calculate_save_target(target, weapon["AP"])
            save_success = save_roll >= save_target

            if save_success:
                # SAVED case
                attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) : SAVED !"
            else:
                # DAMAGE case - apply damage. HP_CUR single write path: update_units_cache_hp only (Phase 2: from cache)
                damage_dealt = resolve_dice_value(require_key(weapon, "DMG"), "fight_damage")
                target_hp = require_hp_from_cache(str(target["id"]), game_state)
                new_hp = max(0, target_hp - damage_dealt)
                update_units_cache_hp(game_state, str(target["id"]), new_hp)
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate kill probability cache for target
                from engine.ai.weapon_selector import invalidate_cache_for_target
                cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
                invalidate_cache_for_target(cache, str(target["id"]))
                
                target_died = not is_unit_alive(str(target["id"]), game_state)

                if target_died:
                    # CRITICAL: Immediately remove dead unit from fight activation pools
                    _remove_dead_unit_from_fight_pools(game_state, target_id)
                    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate cache for dead unit
                    from engine.ai.weapon_selector import invalidate_cache_for_unit
                    invalidate_cache_for_unit(cache, str(target["id"]))
                    attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} dealt : Unit {target_id} DIED !"
                else:
                    attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} DAMAGE DEALT !"

    # AI_TURN.md COMPLIANCE: Log ALL attacks to action_logs (not just damage)
    if "action_logs" not in game_state:
        game_state["action_logs"] = []

    # AI_TURN.md COMPLIANCE: Direct field access for required 'turn' field
    if "turn" not in game_state:
        raise KeyError("game_state missing required 'turn' field")

    # AI_TURN.md COMPLIANCE: shootDetails array matches frontend gameLogStructure.ts ShootDetail interface
    # Fields: targetDied, damageDealt, saveSuccess (camelCase to match frontend)
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon_name in action_logs
    game_state["action_logs"].append({
        "type": "combat",  # Must match frontend gameLogStructure.ts type
        "weaponName": weapon_name if weapon_name else None,
        "message": attack_log,
        "turn": game_state["turn"],
        "phase": "fight",
        "attackerId": attacker_id,
        "targetId": target_id,
        "player": attacker["player"],
        "shootDetails": [{
            "shotNumber": 1,
            "attackRoll": hit_roll,
            "hitTarget": hit_target,
            "hitResult": "HIT" if hit_success else "MISS",
            "strengthRoll": wound_roll,
            "woundTarget": wound_target,
            "strengthResult": "SUCCESS" if wound_success else "FAILED",
            "saveRoll": save_roll,
            "saveTarget": save_target,
            "saveSuccess": save_success,
            "damageDealt": damage_dealt,
            "targetDied": target_died
        }],
        "timestamp": "server_time"
    })

    # Add separate death log event if target was killed
    if target_died:
        game_state["action_logs"].append({
            "type": "death",
            "message": f"Unit {target_id} was destroyed",
            "turn": game_state["turn"],
            "phase": "fight",
            "targetId": target_id,
            "unitId": target_id,
            "player": target["player"],
            "timestamp": "server_time"
        })

    return {
        "hit_roll": hit_roll,
        "hit_target": hit_target,
        "hit_success": hit_success,
        "wound_roll": wound_roll,
        "wound_target": wound_target,
        "wound_success": wound_success,
        "save_roll": save_roll,
        "save_target": save_target,
        "save_success": save_success,
        "damage": damage_dealt,
        "target_died": target_died,
        "attack_log": attack_log,
        "weapon_name": weapon_name,  # MULTIPLE_WEAPONS_IMPLEMENTATION.md
        "target_coords": target_coords
    }




def _calculate_save_target(target: Dict[str, Any], ap: int) -> int:
    """Calculate save target with AP modifier and invulnerable save"""
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
    armor_save = target["ARMOR_SAVE"]
    invul_save = target["INVUL_SAVE"]
    
    # Apply AP to armor save (AP is negative, subtract to worsen save: 3+ with -1 AP = 4+)
    modified_armor_save = armor_save - ap
    
    # Handle invulnerable saves: 0 means no invul save, use 7 (impossible)
    effective_invul = invul_save if invul_save > 0 else 7
    
    # Use best available save (lower target number is better)
    best_save = min(modified_armor_save, effective_invul)
    
    # Cap impossible saves at 7, minimum save is 2+
    return max(2, min(best_save, 6))


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """EXACT COPY from 40k_OLD w40k_engine.py wound calculation"""
    if strength >= toughness * 2:
        return 2
    elif strength > toughness:
        return 3
    elif strength == toughness:
        return 4
    elif strength * 2 <= toughness:
        return 6
    else:
        return 5


# === HELPER FUNCTIONS (Minimal Implementation) ===

# Note: _is_adjacent_to_enemy_within_cc_range is defined at top of file


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate range check
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_RNG
    """
    from engine.utils.weapon_helpers import get_max_ranged_range
    rng_rng = get_max_ranged_range(unit)
    if rng_rng <= 0:
        return False
    
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) != unit_player:
            distance = calculate_hex_distance(*require_unit_position(unit, game_state), *require_unit_position(enemy_id, game_state))
            if distance <= rng_rng:
                return True  # Simplified - assume clear LoS for now
    
    return False