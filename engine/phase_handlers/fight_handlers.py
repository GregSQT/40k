#!/usr/bin/env python3
"""
engine/phase_handlers/fight_handlers.py - AI_TURN.md Fight Phase Implementation
Pure stateless functions implementing AI_TURN.md fight specification

References: AI_TURN.md Section ⚔️ FIGHT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from .generic_handlers import end_activation
from . import shooting_handlers

# Import functions from shooting_handlers for cross-phase functionality
_cache_size_limit = shooting_handlers._cache_size_limit
_shooting_phase_complete = shooting_handlers._shooting_phase_complete
_ai_select_shooting_target = shooting_handlers._ai_select_shooting_target
_invalidate_los_cache_for_unit = shooting_handlers._invalidate_los_cache_for_unit
shooting_build_activation_pool = shooting_handlers.shooting_build_activation_pool


def fight_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_TURN.md: Initialize fight phase and build activation pools.

    CRITICAL: Fight phase has THREE sub-phases:
    1. Charging units (units in units_charged) attack first
    2. Alternating activation between players (remaining units adjacent to enemies)
    3. Cleanup (process remaining pool if any)
    """
    # Set phase
    game_state["phase"] = "fight"

    # AI_TURN.md: Build ALL fight pools (charging + alternating for both players)
    # NOTE: ATTACK_LEFT is NOT set at phase start - it's set per unit activation
    fight_build_activation_pools(game_state)
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Pre-compute kill probability cache
    from engine.ai.weapon_selector import precompute_kill_probability_cache
    precompute_kill_probability_cache(game_state, "fight")

    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("FIGHT PHASE START")

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

    # AI_TURN.md COMPLIANCE: Set initial fight_subphase based on which pools have units
    if charging_pool:
        game_state["fight_subphase"] = "charging"
    elif non_active_alternating or active_alternating:
        # AI_TURN.md: Non-active player goes FIRST in alternating phase
        game_state["fight_subphase"] = "alternating_non_active"
    else:
        game_state["fight_subphase"] = None

    if not charging_pool and not active_alternating and not non_active_alternating:
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
    AI_TURN.md: Build all 3 fight phase activation pools.

    Sub-Phase 1: charging_activation_pool (current player's charging units)
    Sub-Phase 2: active_alternating_activation_pool + non_active_alternating_activation_pool
    Sub-Phase 3: Cleanup (handled by sub-phase 2 logic when one pool empty)

    CRITICAL: Non-active player goes first in alternating phase per AI_TURN.md.
    """
    current_player = game_state["current_player"]
    non_active_player = 1 - current_player

    # AI_TURN.md COMPLIANCE: Ensure units_fought exists before any checks
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()

    # AI_TURN.md COMPLIANCE: units_charged must exist (set by charge phase)
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field - charge phase must run before fight phase")

    # Sub-Phase 1: Charging units (current player only, units in units_charged AND adjacent)
    charging_activation_pool = []
    if "console_logs" not in game_state:
        game_state["console_logs"] = []

    game_state["console_logs"].append(f"FIGHT POOL BUILD: Building charging pool for player {current_player}")
    for unit in game_state["units"]:
        if unit["HP_CUR"] > 0:
            if unit["player"] == current_player:
                if unit["id"] in game_state["units_charged"]:
                    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                    is_not_fought = unit["id"] not in game_state["units_fought"]
                    if is_adjacent and is_not_fought:
                        charging_activation_pool.append(unit["id"])
                        game_state["console_logs"].append(f"ADDED TO CHARGING POOL: Unit {unit['id']}")

    game_state["charging_activation_pool"] = charging_activation_pool
    game_state["console_logs"].append(f"CHARGING POOL SIZE: {len(charging_activation_pool)}")

    # Sub-Phase 2: Alternating activation (units NOT in units_charged, adjacent to enemies)
    active_alternating = []
    non_active_alternating = []

    game_state["console_logs"].append(f"FIGHT POOL BUILD: Building alternating pools")
    for unit in game_state["units"]:
        if unit["HP_CUR"] > 0:
            if unit["id"] not in game_state["units_charged"] and unit["id"] not in game_state["units_fought"]:
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                if is_adjacent:
                    if unit["player"] == current_player:
                        active_alternating.append(unit["id"])
                        game_state["console_logs"].append(f"ADDED TO ACTIVE ALTERNATING: Unit {unit['id']} (player {unit['player']})")
                    else:
                        non_active_alternating.append(unit["id"])
                        game_state["console_logs"].append(f"ADDED TO NON-ACTIVE ALTERNATING: Unit {unit['id']} (player {unit['player']})")

    game_state["active_alternating_activation_pool"] = active_alternating
    game_state["non_active_alternating_activation_pool"] = non_active_alternating
    game_state["console_logs"].append(f"ALTERNATING POOLS: active={len(active_alternating)}, non_active={len(non_active_alternating)}")


def _remove_dead_unit_from_fight_pools(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    CRITICAL: Immediately remove a dead unit from all fight activation pools.
    
    This must be called as soon as a unit dies to prevent it from being activated
    in subsequent sub-phases of the same fight phase.
    """
    # Remove from charging pool
    if "charging_activation_pool" in game_state and unit_id in game_state["charging_activation_pool"]:
        game_state["charging_activation_pool"].remove(unit_id)
    
    # Remove from active alternating pool
    if "active_alternating_activation_pool" in game_state and unit_id in game_state["active_alternating_activation_pool"]:
        game_state["active_alternating_activation_pool"].remove(unit_id)
    
    # Remove from non-active alternating pool
    if "non_active_alternating_activation_pool" in game_state and unit_id in game_state["non_active_alternating_activation_pool"]:
        game_state["non_active_alternating_activation_pool"].remove(unit_id)

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    AI_TURN.md: Check if unit is adjacent to at least one enemy within melee range.

    Used for fight phase eligibility - unit must be within melee range of an enemy.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    unit_col, unit_row = unit["col"], unit["row"]

    if "console_logs" not in game_state:
        game_state["console_logs"] = []

    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit_col, unit_row, enemy["col"], enemy["row"])
            game_state["console_logs"].append(f"FIGHT CHECK: Unit {unit['id']} @ ({unit_col},{unit_row}) melee_range={cc_range} | Enemy {enemy['id']} @ ({enemy['col']},{enemy['row']}) distance={distance}")
            if distance <= cc_range:
                game_state["console_logs"].append(f"FIGHT ELIGIBLE: Unit {unit['id']} can fight enemy {enemy['id']} (dist {distance} <= melee_range {cc_range})")
                return True

    game_state["console_logs"].append(f"FIGHT NOT ELIGIBLE: Unit {unit['id']} has no enemies within melee_range {cc_range}")
    return False


def _ai_select_fight_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """
    AI target selection for fight phase using RewardMapper system.

    Fight priority (same as shooting): lowest HP, highest threat.
    """
    if not valid_targets:
        return ""

    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return valid_targets[0]
    
    try:
        from ai.reward_mapper import RewardMapper

        reward_configs = game_state.get("reward_configs", {})
        if not reward_configs:
            return valid_targets[0]

        # Get unit type for config lookup
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        fighter_unit_type = unit["unitType"]
        fighter_agent_key = unit_registry.get_model_key(fighter_unit_type)

        # Get unit-specific config or fallback to default
        unit_reward_config = reward_configs.get(fighter_agent_key)
        if not unit_reward_config:
            raise ValueError(f"No reward config found for unit type '{fighter_agent_key}' in reward_configs")

        reward_mapper = RewardMapper(unit_reward_config)

        # Build target list for reward mapper
        all_targets = [_get_unit_by_id(game_state, tid) for tid in valid_targets if _get_unit_by_id(game_state, tid)]

        best_target = valid_targets[0]
        best_reward = -999999

        for target_id in valid_targets:
            target = _get_unit_by_id(game_state, target_id)
            if not target:
                continue

            # Fight phase uses same priority logic as shooting
            # RewardMapper handles both via target priority calculation
            reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, False)

            if reward > best_reward:
                best_reward = reward
                best_target = target_id

        return best_target

    except Exception:
        return valid_targets[0]

def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    EXACT COPY from w40k_engine_save.py _has_valid_shooting_targets logic
    WITH ALWAYS-ON DEBUG LOGGING
    """
    # FIXED: Disable debug output completely during training
    debug_mode = False  # Set to True only for manual debugging
    
    if debug_mode:
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers for debug
        from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_max_ranged_range, get_melee_range
        selected_rng = get_selected_ranged_weapon(unit)
        rng_nb_debug = selected_rng.get('NB', 0) if selected_rng else 0
        max_rng_debug = get_max_ranged_range(unit)
        melee_range_debug = get_melee_range()
        print(f"\n🔍 ELIGIBILITY CHECK: Unit {unit['id']} @ ({unit['col']}, {unit['row']})")
        print(f"   Player: {unit['player']}, Current Player: {current_player}")
        print(f"   HP: {unit['HP_CUR']}/{unit['HP_MAX']}")
        print(f"   RNG_NB: {rng_nb_debug}, RNG_RNG: {max_rng_debug}")
        print(f"   CC_RNG: {melee_range_debug}")
    
    # unit.HP_CUR > 0?
    if unit["HP_CUR"] <= 0:
        if debug_mode:
            print(f"   ❌ BLOCKED: Unit is dead (HP_CUR={unit['HP_CUR']})")
        return False
        
    # unit.player === current_player?
    if unit["player"] != current_player:
        if debug_mode:
            print(f"   ❌ BLOCKED: Wrong player (unit.player={unit['player']} != current_player={current_player})")
        return False
        
    # units_fled.includes(unit.id)?
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "units_fled" not in game_state:
        raise KeyError("game_state missing required 'units_fled' field")
    if unit["id"] in game_state["units_fled"]:
        if debug_mode:
            print(f"   ❌ BLOCKED: Unit has fled")
        return False
    
    # CRITICAL FIX: Add missing adjacency check - units in melee cannot shoot
    # This matches the frontend logic: hasAdjacentEnemyShoot check
    if debug_mode:
        print(f"   Checking for adjacent enemies (CC_RNG={unit.get('CC_RNG', 'MISSING')})...")
    
    adjacent_enemies = []
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if "CC_RNG" not in unit:
                raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_RNG
            from engine.utils.weapon_helpers import get_melee_range
            melee_range = get_melee_range()  # Always 1
            
            if debug_mode:
                print(f"      Enemy {enemy['id']} @ ({enemy['col']}, {enemy['row']}): distance={distance}, melee_range={melee_range}")
            
            if distance <= melee_range:
                adjacent_enemies.append(f"{enemy['id']}@dist={distance}")
                if debug_mode:
                    print(f"         ⚠️ Enemy {enemy['id']} IS ADJACENT (distance={distance} <= CC_RNG={unit['CC_RNG']})")
    
    if adjacent_enemies:
        if debug_mode:
            print(f"   ❌ BLOCKED: Adjacent enemies found: {adjacent_enemies}")
            print(f"   RESULT: Unit {unit['id']} CANNOT SHOOT (W40K rule: engaged in melee)")
        return False
    
    if debug_mode:
        print(f"   ✅ No adjacent enemies found")
        
    # unit.RNG_NB > 0?
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_NB
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    selected_weapon = get_selected_ranged_weapon(unit)
    if not selected_weapon:
        if debug_mode:
            print(f"   ❌ BLOCKED: No ranged weapons")
        return False
    rng_nb = selected_weapon.get("NB", 0)
    if rng_nb <= 0:
        if debug_mode:
            print(f"   ❌ BLOCKED: No ranged attacks (RNG_NB={rng_nb})")
        return False
    
    if debug_mode:
        print(f"   ✅ Unit has ranged attacks (RNG_NB={unit['RNG_NB']})")
        print(f"   Checking for valid ranged targets (RNG_RNG={unit.get('RNG_RNG', 0)})...")
    
    # Check for valid targets with detailed debugging
    valid_targets_found = []
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            is_valid = _is_valid_shooting_target(game_state, unit, enemy)
            
            if debug_mode:
                print(f"      Enemy {enemy['id']} @ ({enemy['col']}, {enemy['row']}): dist={distance}, RNG_RNG={unit.get('RNG_RNG', 0)}, valid={is_valid}")
                if not is_valid:
                    if distance > unit.get('RNG_RNG', 0):
                        print(f"         ❌ OUT OF RANGE")
                    elif distance <= unit.get('CC_RNG', 1):
                        print(f"         ❌ TOO CLOSE (melee range)")
                    else:
                        print(f"         ❌ NO LINE OF SIGHT")
            
            if is_valid:
                valid_targets_found.append(enemy["id"])
                if debug_mode:
                    print(f"         ✅ VALID TARGET")
    
    if debug_mode:
        if len(valid_targets_found) > 0:
            print(f"   ✅ RESULT: {len(valid_targets_found)} valid targets found: {valid_targets_found}")
        else:
            print(f"   ❌ RESULT: NO valid targets found")
    
    return len(valid_targets_found) > 0


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine_save.py working validation with proper LoS
    PERFORMANCE: Uses LoS cache for instant lookups (0.001ms vs 5-10ms)
    """
    # Disable debug prints entirely for training performance
    debug_mode = False
    
    # Range check using proper hex distance
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_RNG" not in shooter:
        raise KeyError(f"Shooter missing required 'RNG_RNG' field: {shooter}")
    if distance > shooter["RNG_RNG"]:
        if debug_mode:
            print(f"         ❌ Out of range: dist={distance} > RNG_RNG={shooter['RNG_RNG']}")
        return False
        
    # Dead target check
    if target["HP_CUR"] <= 0:
        if debug_mode:
            print(f"         ❌ Target is dead: HP_CUR={target['HP_CUR']}")
        return False
        
    # Friendly fire check
    if target["player"] == shooter["player"]:
        if debug_mode:
            print(f"         ❌ Friendly fire: target.player={target['player']} == shooter.player={shooter['player']}")
        return False
    
    # Adjacent check - can't shoot at adjacent enemies (melee range)
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    from engine.utils.weapon_helpers import get_melee_range
    melee_range = get_melee_range()  # Always 1
    if distance <= melee_range:
        if debug_mode:
            print(f"         ❌ Too close: dist={distance} <= melee_range={melee_range}")
        return False
    
    # PERFORMANCE: Use LoS cache if available (instant lookup)
    # Fallback to calculation if cache missing (phase not started yet)
    has_los = False
    if "los_cache" in game_state and game_state["los_cache"]:
        cache_key = (shooter["id"], target["id"])
        if cache_key in game_state["los_cache"]:
            # Cache hit: instant lookup (0.001ms)
            has_los = game_state["los_cache"][cache_key]
        else:
            # Cache miss: calculate and store (first-time lookup)
            has_los = _has_line_of_sight(game_state, shooter, target)
            game_state["los_cache"][cache_key] = has_los
    else:
        # No cache: fall back to direct calculation (pre-phase-start calls)
        has_los = _has_line_of_sight(game_state, shooter, target)
    
    if debug_mode:
        if has_los:
            print(f"         ✅ VALID TARGET: dist={distance}, LoS=clear")
        else:
            print(f"         ❌ No LoS: blocked by terrain")
    
    return has_los

def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: Start unit activation from shoot_activation_pool
    Clear valid_target_pool, clear TOTAL_ACTION_LOG, SHOOT_LEFT = RNG_NB
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found", "unitId": unit_id}
    
    # REMOVED: Line 335 was clearing action_logs between unit activations, destroying cross-phase data
    # action_logs must accumulate for entire episode, only cleared in __init__ and reset()
    
    # AI_TURN.md initialization
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    rng_weapons = unit.get("RNG_WEAPONS", [])
    if rng_weapons:
        selected_idx = unit.get("selectedRngWeaponIndex", 0)
        if selected_idx < 0 or selected_idx >= len(rng_weapons):
            raise IndexError(f"Invalid selectedRngWeaponIndex {selected_idx} for unit {unit['id']}")
        weapon = rng_weapons[selected_idx]
        unit["SHOOT_LEFT"] = weapon["NB"]
    else:
        unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    unit["selected_target_id"] = None  # For two-click confirmation
    
    # CRITICAL: Capture unit's current location for shooting phase tracking
    unit["activation_position"] = {"col": unit["col"], "row": unit["row"]}
    
    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id
    
    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"], 
            "position": {"col": unit["col"], "row": unit["row"]}}


def shooting_build_valid_target_pool(game_state: Dict[str, Any], unit_id: str) -> List[str]:
    """
    Build valid_target_pool and always send blinking data to frontend.
    All enemies within range AND in Line of Sight AND having HP_CUR > 0

    PERFORMANCE: Caches target pool per (unit_id, col, row) to avoid repeated
    distance/LoS calculations during a unit's shooting activation.
    Cache invalidates automatically when unit changes or moves.
    """
    global _target_pool_cache

    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    # Create cache key from unit identity and position
    cache_key = (unit_id, unit["col"], unit["row"])

    # Check cache
    if cache_key in _target_pool_cache:
        # Cache hit: Fast path - only filter dead targets
        cached_pool = _target_pool_cache[cache_key]

        # Filter out units that died since cache was built
        alive_targets = []
        for target_id in cached_pool:
            target = _get_unit_by_id(game_state, target_id)
            if target and target["HP_CUR"] > 0:
                alive_targets.append(target_id)

        # Update unit's target pool
        unit["valid_target_pool"] = alive_targets

        return alive_targets

    # Cache miss: Build target pool from scratch (expensive)
    valid_target_pool = []

    for enemy in game_state["units"]:
        if (enemy["player"] != unit["player"] and
            enemy["HP_CUR"] > 0):

            # Check if target is valid with detailed logging for training debug
            is_valid = _is_valid_shooting_target(game_state, unit, enemy)
            if not is_valid:
                # Add specific failure reason debugging
                distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            else:
                valid_target_pool.append(enemy["id"])

    # PERFORMANCE: Pre-calculate priorities for all targets ONCE before sorting
    # This reduces from O(n log n) priority calculations to O(n) calculations
    # Priority: tactical efficiency > type match > distance

    # Pre-validate unit stats ONCE (not inside loop)
    if "T" not in unit:
        raise KeyError(f"Unit missing required 'T' field: {unit}")
    if "ARMOR_SAVE" not in unit:
        raise KeyError(f"Unit missing required 'ARMOR_SAVE' field: {unit}")
    if "unitType" not in unit:
        raise KeyError(f"Unit missing required 'unitType' field: {unit}")

    # Cache unit stats for priority calculations
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or first weapon
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    selected_weapon = get_selected_ranged_weapon(unit)
    if not selected_weapon and unit.get("RNG_WEAPONS"):
        selected_weapon = unit["RNG_WEAPONS"][0]  # Fallback to first weapon
    
    unit_t = unit["T"]
    unit_save = unit["ARMOR_SAVE"]
    unit_attacks = selected_weapon.get("NB", 0) if selected_weapon else 0
    unit_bs = selected_weapon.get("ATK", 0) if selected_weapon else 0
    unit_s = selected_weapon.get("STR", 0) if selected_weapon else 0
    unit_ap = selected_weapon.get("AP", 0) if selected_weapon else 0
    unit_type = unit["unitType"]

    # Determine preferred target type from unit name (ONCE)
    if "Swarm" in unit_type:
        preferred = "swarm"
    elif "Troop" in unit_type:
        preferred = "troop"
    elif "Elite" in unit_type:
        preferred = "elite"
    else:
        preferred = "troop"  # Default

    # Calculate our hit probability (ONCE - unit stats don't change per target)
    our_hit_prob = (7 - unit_bs) / 6.0

    # Pre-calculate priorities for all targets
    target_priorities = []  # [(target_id, priority_tuple)]

    for target_id in valid_target_pool:
        target = _get_unit_by_id(game_state, target_id)
        if not target:
            target_priorities.append((target_id, (999, 0, 999)))
            continue

        distance = _calculate_hex_distance(unit["col"], unit["row"], target["col"], target["row"])

        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access - no defaults
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_* fields
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        from shared.data_validation import require_key
        
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        if "ARMOR_SAVE" not in target:
            raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
        if "HP_CUR" not in target:
            raise KeyError(f"Target missing required 'HP_CUR' field: {target}")
        if "HP_MAX" not in target:
            raise KeyError(f"Target missing required 'HP_MAX' field: {target}")

        # Step 1: Calculate target's threat to us (probability to wound per turn)
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected ranged weapon or best weapon
        target_rng_weapon = get_selected_ranged_weapon(target)
        if not target_rng_weapon and target.get("RNG_WEAPONS"):
            target_rng_weapon = target["RNG_WEAPONS"][0]  # Fallback to first weapon
        
        if not target_rng_weapon:
            # Target has no ranged weapons, use default values (threat = 0)
            target_attacks = 0
            target_bs = 7  # Can't hit
            target_s = 0
            target_ap = 0
        else:
            target_attacks = require_key(target_rng_weapon, "NB")
            target_bs = require_key(target_rng_weapon, "ATK")
            target_s = require_key(target_rng_weapon, "STR")
            target_ap = require_key(target_rng_weapon, "AP")

        # Hit probability
        hit_prob = (7 - target_bs) / 6.0

        # Wound probability (S vs T)
        if target_s >= unit_t * 2:
            wound_prob = 5/6  # 2+
        elif target_s > unit_t:
            wound_prob = 4/6  # 3+
        elif target_s == unit_t:
            wound_prob = 3/6  # 4+
        elif target_s * 2 <= unit_t:
            wound_prob = 1/6  # 6+
        else:
            wound_prob = 2/6  # 5+

        # Failed save probability (AP is negative, subtract to worsen save)
        modified_save = unit_save - target_ap
        if modified_save > 6:
            failed_save_prob = 1.0
        else:
            failed_save_prob = (modified_save - 1) / 6.0

        # Threat per attack
        threat_per_attack = hit_prob * wound_prob * failed_save_prob
        threat_per_turn = target_attacks * threat_per_attack

        # Step 2: Calculate our kill difficulty (expected activations to kill target)
        target_t = target["T"]
        target_save = target["ARMOR_SAVE"]
        target_hp = target["HP_CUR"]

        # Our wound probability
        if unit_s >= target_t * 2:
            our_wound_prob = 5/6
        elif unit_s > target_t:
            our_wound_prob = 4/6
        elif unit_s == target_t:
            our_wound_prob = 3/6
        elif unit_s * 2 <= target_t:
            our_wound_prob = 1/6
        else:
            our_wound_prob = 2/6

        # Target's failed save (AP is negative, subtract to worsen save)
        target_modified_save = target_save - unit_ap
        if target_modified_save > 6:
            target_failed_save = 1.0
        else:
            target_failed_save = (target_modified_save - 1) / 6.0

        # Expected damage per activation
        damage_per_attack = our_hit_prob * our_wound_prob * target_failed_save
        expected_damage_per_activation = unit_attacks * damage_per_attack

        # Expected activations to kill
        if expected_damage_per_activation > 0:
            activations_to_kill = target_hp / expected_damage_per_activation
        else:
            activations_to_kill = 100  # Very hard to kill

        # Step 3: Tactical efficiency = expected damage target deals before death
        tactical_efficiency = threat_per_turn * activations_to_kill

        # Calculate target type match
        target_max_hp = target["HP_MAX"]

        # Determine target type from HP
        if target_max_hp <= 1:
            target_type = "swarm"
        elif target_max_hp <= 3:
            target_type = "troop"
        elif target_max_hp <= 6:
            target_type = "elite"
        else:
            target_type = "leader"

        type_match = 1.0 if preferred == target_type else 0.3

        # Priority scoring (lower = higher priority)
        priority = (
            -tactical_efficiency * 100,  # Higher efficiency = lower score = first
            -(type_match * 70),          # Favorite type = -70 bonus
            distance                     # Closer = lower score
        )
        target_priorities.append((target_id, priority))

    # Sort by pre-calculated priority (O(n log n) comparisons, O(1) per comparison)
    target_priorities.sort(key=lambda x: x[1])

    # Extract sorted target IDs
    valid_target_pool = [tp[0] for tp in target_priorities]

    # Store in cache
    _target_pool_cache[cache_key] = valid_target_pool

    # Prevent memory leak: Clear cache if it grows too large
    if len(_target_pool_cache) > _cache_size_limit:
        _target_pool_cache.clear()

    # Update unit's target pool
    unit["valid_target_pool"] = valid_target_pool

    return valid_target_pool

def _has_line_of_sight(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    AI_TURN.md EXACT: Line of sight check with proper hex pathfinding.
    Fixed to get wall data from multiple possible sources.
    """
    start_col, start_row = shooter["col"], shooter["row"]
    end_col, end_row = target["col"], target["row"]
    
    # Try multiple sources for wall hexes
    wall_hexes_data = []
    
    # Source 1: Direct in game_state
    if "wall_hexes" in game_state:
        wall_hexes_data = game_state["wall_hexes"]
    
    # Source 2: In board configuration within game_state
    elif "board" in game_state and "wall_hexes" in game_state["board"]:
        wall_hexes_data = game_state["board"]["wall_hexes"]
    
    # Source 3: Check if walls exist in board config
    # AI_TURN.md COMPLIANCE: Direct field access chain
    elif "board_config" in game_state and "wall_hexes" in game_state["board_config"]:
        wall_hexes_data = game_state["board_config"]["wall_hexes"]
    
    else:
        # CHANGE 8: NO FALLBACK - raise error if wall data not found in any source
        raise KeyError("wall_hexes not found in game_state['wall_hexes'], game_state['board']['wall_hexes'], or game_state['board_config']['wall_hexes']")
    
    if not wall_hexes_data:
        # print(f"LOS DEBUG: No wall data found - allowing shot")
        return True
    
    # Convert wall_hexes to set for fast lookup
    wall_hexes = set()
    for wall_hex in wall_hexes_data:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            wall_hexes.add((wall_hex[0], wall_hex[1]))
        # else:
            # print(f"LOS DEBUG: Invalid wall hex format: {wall_hex}")
    
    try:
        hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
        
        # Check if any hex in path is a wall (excluding start and end)
        blocked = False
        blocking_hex = None
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            if (col, row) in wall_hexes:
                blocked = True
                blocking_hex = (col, row)
                break
        
        return not blocked
        
    except Exception as e:
        # print(f"            LoS calculation error: {e}")
        return False
    
    if not game_state["wall_hexes"]:
        return True
    
    hex_path = _get_accurate_hex_line(start_col, start_row, end_col, end_row)
    
    # Check if any hex in path is a wall (excluding start and end)
    for col, row in hex_path[1:-1]:
        if (col, row) in game_state["wall_hexes"]:
            return False
    
    return True

def _get_accurate_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Accurate hex line using cube coordinates."""
    start_cube = _offset_to_cube(start_col, start_row)
    end_cube = _offset_to_cube(end_col, end_row)
    
    distance = max(abs(start_cube.x - end_cube.x), abs(start_cube.y - end_cube.y), abs(start_cube.z - end_cube.z))
    path = []
    
    for i in range(distance + 1):
        t = i / distance if distance > 0 else 0
        
        cube_x = start_cube.x + t * (end_cube.x - start_cube.x)
        cube_y = start_cube.y + t * (end_cube.y - start_cube.y)
        cube_z = start_cube.z + t * (end_cube.z - start_cube.z)
        
        rounded_cube = _cube_round(cube_x, cube_y, cube_z)
        offset_col, offset_row = _cube_to_offset(rounded_cube)
        path.append((offset_col, offset_row))
    
    return path

class CubeCoordinate:
    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z


def _offset_to_cube(col: int, row: int) -> CubeCoordinate:
    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    return CubeCoordinate(x, y, z)


def _cube_to_offset(cube: CubeCoordinate) -> Tuple[int, int]:
    col = cube.x
    row = cube.z + (cube.x - (cube.x & 1)) // 2
    return col, row


def _cube_round(x: float, y: float, z: float) -> CubeCoordinate:
    rx = round(x)
    ry = round(y)
    rz = round(z)
    
    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)
    
    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    
    return CubeCoordinate(rx, ry, rz)

def _fight_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_TURN.md: Complete fight phase with player progression and turn management.

    CRITICAL: Fight is the LAST phase. After fight:
    - P0 → P1 movement phase
    - P1 → increment turn, P0 movement phase
    """
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
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("FIGHT PHASE COMPLETE")

    # AI_TURN.md: Player progression logic
    if game_state["current_player"] == 0:
        # Player 0 complete → Player 1 movement phase
        game_state["current_player"] = 1
        game_state["phase"] = "move"  # AI_TURN.md: Actually transition phase

        # AI_TURN.md: Initialize movement phase pools for P1
        # CRITICAL: movement_phase_start() resets ALL tracking sets (units_fought, units_charged, etc.)
        # This ensures P1 starts with clean state, allowing units that fought in P0's fight phase
        # to fight again in P1's fight phase if they remain adjacent
        from engine.phase_handlers import movement_handlers
        movement_handlers.movement_phase_start(game_state)

        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "move",
            "current_player": 1,
            "units_processed": len(game_state.get("units_fought", set())),
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 1:
        # Player 1 complete → Check if incrementing turn would exceed limit
        max_turns = game_state.get("config", {}).get("training_config", {}).get("max_turns_per_episode")
        if max_turns and (game_state["turn"] + 1) > max_turns:
            # Incrementing would exceed turn limit - end game without incrementing
            game_state["game_over"] = True
            return {
                "phase_complete": True,
                "game_over": True,
                "turn_limit_reached": True,
                "units_processed": len(game_state.get("units_fought", set())),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
        else:
            # Safe to increment turn and continue to P0's movement phase
            game_state["turn"] += 1
            game_state["current_player"] = 0
            game_state["phase"] = "move"  # AI_TURN.md: Actually transition phase

            # AI_TURN.md: Initialize movement phase pools for P0
            # CRITICAL: movement_phase_start() resets ALL tracking sets (units_fought, units_charged, etc.)
            # This ensures P0 starts with clean state at the beginning of each turn
            from engine.phase_handlers import movement_handlers
            movement_handlers.movement_phase_start(game_state)

            return {
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "move",
                "current_player": 0,
                "new_turn": game_state["turn"],
                "units_processed": len(game_state.get("units_fought", set())),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }

def fight_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """AI_TURN.md: Fight phase end - redirects to complete function"""
    return _fight_phase_complete(game_state)

def _get_shooting_context(game_state: Dict[str, Any], unit: Dict[str, Any]) -> str:
    """Determine current shooting context for nested behavior."""
    # AI_TURN.md COMPLIANCE: Direct field access
    if "selected_target_id" in unit and unit["selected_target_id"]:
        return "target_selected"
    else:
        return "no_target_selected"

def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: shooting_activation_end procedure with exact arguments
    shooting_activation_end(Arg1, Arg2, Arg3, Arg4, Arg5)
    """
    
    # Arg2 step increment
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if arg2 == 1:
        if "episode_steps" not in game_state:
            game_state["episode_steps"] = 0
        game_state["episode_steps"] += 1
    
    # Arg3 tracking
    if arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit["id"])
    # arg3 == "PASS" → no tracking update
    
    # Arg4 pool removal
    if arg4 == "SHOOTING":
        # AI_TURN.md COMPLIANCE: Direct field access
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        pool_before = game_state["shoot_activation_pool"].copy()
        if "shoot_activation_pool" in game_state and unit["id"] in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].remove(unit["id"])
            pool_after = game_state["shoot_activation_pool"]
        else:
            current_pool = game_state["shoot_activation_pool"] if "shoot_activation_pool" in game_state else []
            # print(f"🔴 END_ACTIVATION DEBUG: Unit {unit['id']} not found in pool {current_pool}")
    
    # Clean up unit activation state including position tracking
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]  # Clear position tracking
    unit["SHOOT_LEFT"] = 0
    
    # Clear active unit
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]
    
    # Check if shooting pool is now empty after removing this unit
    # AI_TURN.md COMPLIANCE: Direct field access
    if "shoot_activation_pool" not in game_state:
        pool_empty = True
    else:
        pool_empty = len(game_state["shoot_activation_pool"]) == 0
    
    response = {
        "activation_ended": True,
        "endType": arg1,
        "action": "skip" if arg1 == "PASS" else ("wait" if arg1 == "SKIP" else "shoot"),
        "unitId": unit["id"],
        "clear_blinking_gentle": True,
        "reset_mode": "select",
        "clear_selected_unit": True
    }
    
    # Signal phase completion if pool is empty - delegate to proper phase end function
    if pool_empty:
        # Don't just set a flag - call the complete phase transition function
        return _shooting_phase_complete(game_state)
    
    return response

def _shooting_unit_execution_loop(game_state: Dict[str, Any], unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md EXACT: Execute While SHOOT_LEFT > 0 loop automatically
    """
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # AI_TURN.md: While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        return True, result  # Ensure consistent (bool, dict) format
    
    # AI_TURN.md: Build valid_target_pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    # AI_TURN.md: valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if SHOOT_LEFT equals selected weapon NB
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        selected_nb = selected_weapon.get("NB", 0) if selected_weapon else 0
        if unit["SHOOT_LEFT"] == selected_nb:
            # No targets at activation
            result = _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
            return True, result
        else:
            # Shot last target available
            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
            return True, result
    
    # CLEAN FLAG DETECTION: Use config parameter
    unit = _get_unit_by_id(game_state, unit_id)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 1
    
    # CHANGE 1: Add gym_training_mode detection
    # Gym agents have already made shoot/skip decisions via action selection (actions 4-8 or 11)
    # The execution loop reaches here when SHOOT_LEFT > 0 after a shot, so we need to auto-execute
    is_gym_training = config.get("gym_training_mode", False) and unit and unit["player"] == 1
    
    # CHANGE 2: Auto-execute for BOTH PvE AI and gym training
    if (is_pve_ai or is_gym_training) and valid_targets:
        # AUTO-SHOOT: PvE AI and gym training
        target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly and return result
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    # Only humans get waiting_for_player response
    response = {
        "while_loop_active": True,
        "validTargets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True,
        "waiting_for_player": True
    }
    return True, response

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Fight phase handler action routing with 3 sub-phases.

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

    # AI_TURN.md: Check which sub-phase we're in
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
        current_player = game_state.get("current_player", 0)

        if current_turn == "non_active" and non_active_alternating:
            current_sub_phase = "alternating_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            # Check if there are units for the non-active player (opposite of current_player)
            opposite_player = 1 - current_player
            eligible_units = [uid for uid in current_pool 
                            if _get_unit_by_id(game_state, uid) 
                            and _get_unit_by_id(game_state, uid).get("player") == opposite_player]
            if not eligible_units and active_alternating:
                # Non-active player has no units, but active pool has units → switch to active
                current_sub_phase = "alternating_active"
                current_pool = active_alternating
            elif not eligible_units:
                # Neither player has units → end phase
                return True, fight_phase_end(game_state)
        elif current_turn == "active" and active_alternating:
            current_sub_phase = "alternating_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = [uid for uid in current_pool 
                            if _get_unit_by_id(game_state, uid) 
                            and _get_unit_by_id(game_state, uid).get("player") == current_player]
            if not eligible_units and non_active_alternating:
                # Active player has no units, but non_active pool has units → switch to non_active
                current_sub_phase = "alternating_non_active"
                current_pool = non_active_alternating
            elif not eligible_units:
                # Neither player has units → end phase
                return True, fight_phase_end(game_state)
        elif non_active_alternating:
            # Active pool empty but non_active has units → Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_non_active"
            current_pool = non_active_alternating
            # CRITICAL: non_active pool contains units of OPPOSITE player
            opposite_player = 1 - current_player
            eligible_units = [uid for uid in current_pool 
                            if _get_unit_by_id(game_state, uid) 
                            and _get_unit_by_id(game_state, uid).get("player") == opposite_player]
            if not eligible_units:
                # Non-active player has no units in cleanup pool → end phase
                return True, fight_phase_end(game_state)
        elif active_alternating:
            # Non-active pool empty but active has units → Sub-phase 3 (cleanup)
            current_sub_phase = "cleanup_active"
            current_pool = active_alternating
            # CRITICAL: active pool contains units of CURRENT player
            eligible_units = [uid for uid in current_pool 
                            if _get_unit_by_id(game_state, uid) 
                            and _get_unit_by_id(game_state, uid).get("player") == current_player]
            if not eligible_units:
                # Active player has no units in cleanup pool → end phase
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
            # Auto-select first unit from current pool for gym training
            # CRITICAL: Filter out dead units from pool before selection
            alive_units_in_pool = [uid for uid in current_pool if _get_unit_by_id(game_state, uid) and _get_unit_by_id(game_state, uid)["HP_CUR"] > 0]
            if alive_units_in_pool:
                unit_id = alive_units_in_pool[0]
                unit = _get_unit_by_id(game_state, unit_id)
                if not unit:
                    return False, {"error": "unit_not_found", "unitId": unit_id}
                # Remove dead units from pool
                for dead_unit_id in set(current_pool) - set(alive_units_in_pool):
                    _remove_dead_unit_from_fight_pools(game_state, dead_unit_id)
            else:
                return True, fight_phase_end(game_state)
        else:
            unit_id = str(action["unitId"])
            unit = _get_unit_by_id(game_state, unit_id)
            if not unit:
                return False, {"error": "unit_not_found", "unitId": unit_id}
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
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 1
    
    print(f"🔍 [FIGHT_HANDLER] execute_action: action={action.get('action')}, unit={unit['id'] if unit else None}, is_gym_training={is_gym_training}, is_pve_ai={is_pve_ai}")

    # GYM TRAINING / PvE AI: Auto-activate unit if not already active
    active_fight_unit = game_state.get("active_fight_unit")
    if (is_gym_training or is_pve_ai) and not active_fight_unit and action_type == "fight":
        print(f"🔍 [FIGHT_HANDLER] Auto-activating unit {unit['id']}")
        activation_result = _handle_fight_unit_activation(game_state, unit, config)
        print(f"🔍 [FIGHT_HANDLER] Activation result: success={activation_result[0]}")
        if not activation_result[0]:
            return activation_result  # Activation failed
        # Check if activation ended (no targets → end_activation was called)
        # This happens when unit has no valid targets and was auto-skipped
        if activation_result[1].get("activation_ended") or activation_result[1].get("phase_complete"):
            return activation_result
        # Continue with fight action - targets should now be populated

    # NOTE: AI_TURN.md line 667 specifies invalid actions should call end_activation (ERROR, 0, PASS, FIGHT)
    # We follow this rule strictly - invalid actions are not converted to valid actions

    # AI_TURN.md: Fight phase action routing
    if action_type == "activate_unit":
        return _handle_fight_unit_activation(game_state, unit, config)

    elif action_type == "fight":
        print(f"🔍 [FIGHT_HANDLER] Processing 'fight' action")
        # AI_TURN.md: Fight action with target selection
        # GYM TRAINING / PvE AI: Auto-select target if not provided
        if "targetId" not in action:
            if is_gym_training or is_pve_ai:
                print(f"🔍 [FIGHT_HANDLER] Auto-select enabled for {'gym_training' if is_gym_training else 'pve_ai'}")
                valid_targets = game_state.get("valid_fight_targets", [])
                print(f"🔍 [FIGHT_HANDLER] Valid targets: {valid_targets}")
                if valid_targets:
                    if is_pve_ai:
                        # Use AI target selection for PvE AI
                        print(f"🔍 [FIGHT_HANDLER] Using AI target selection for PvE AI")
                        target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets)
                        print(f"🔍 [FIGHT_HANDLER] AI selected target: {target_id}")
                        if target_id:
                            action["targetId"] = target_id
                        else:
                            # Fallback to first target if AI selection failed
                            first_target = valid_targets[0]
                            action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
                    else:
                        # Gym training: select first target
                        first_target = valid_targets[0]
                        action["targetId"] = first_target["id"] if isinstance(first_target, dict) else first_target
                else:
                    print(f"⚠️ [FIGHT_HANDLER] No valid targets available")
                    # No targets - skip this unit
                    result = end_activation(
                        game_state, unit,
                        "PASS", 1, "PASS", "FIGHT", 0
                    )
                    # CRITICAL: Clear active_fight_unit so next unit can be activated
                    game_state["active_fight_unit"] = None
                    game_state["valid_fight_targets"] = []

                    if result.get("phase_complete"):
                        result.update(_fight_phase_complete(game_state))
                    else:
                        _toggle_fight_alternation(game_state)
                        _update_fight_subphase(game_state)
                    return True, result
            else:
                print(f"❌ [FIGHT_HANDLER] Fight action missing targetId and not gym/pve mode!")
                raise KeyError(f"Fight action missing required 'targetId' field: {action}")
        else:
            print(f"🔍 [FIGHT_HANDLER] Action already has targetId: {action.get('targetId')}")
        
        target_id = action["targetId"]
        print(f"🔍 [FIGHT_HANDLER] Executing fight attack: unit={unit['id']}, target={target_id}")
        return _handle_fight_attack(game_state, unit, target_id, config)

    elif action_type == "postpone":
        # AI_TURN.md: Postpone action (only valid if ATTACK_LEFT = CC_NB)
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
        # AI_TURN.md: Right click = postpone (if ATTACK_LEFT = CC_NB)
        return _handle_fight_postpone(game_state, unit)

    elif action_type == "invalid":
        # AI_TURN.md line 667: INVALID ACTION ERROR → end_activation (ERROR, 0, PASS, FIGHT)
        # We follow AI_TURN.md strictly. The _rebuild_alternating_pools_for_fight call in end_activation
        # is skipped for this case to prevent the unit from being re-added to the pool.
        result = end_activation(
            game_state, unit,
            "ERROR",       # Arg1: ERROR logging (per AI_TURN.md line 667)
            0,             # Arg2: NO step increment (per AI_TURN.md line 667)
            "PASS",        # Arg3: PASS tracking (per AI_TURN.md line 667)
            "FIGHT",       # Arg4: Remove from fight pool
            1              # Arg5: Error logging
        )
        result["invalid_action_penalty"] = True
        # AI_TURN.md COMPLIANCE: Direct field access
        if "attempted_action" not in action:
            result["attempted_action"] = "unknown"
        else:
            result["attempted_action"] = action["attempted_action"]

        # AI_TURN.md: Check if ALL pools are empty → phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result

    else:
        # AI_TURN.md: Only valid actions are fight, postpone
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "fight"}


def _handle_fight_unit_activation(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Handle fight unit activation start.

    Initialize unit for fighting:
    - Set ATTACK_LEFT = CC_NB
    - Build valid target pool (enemies adjacent within CC_RNG)
    - Return waiting_for_player if targets exist
    """
    unit_id = unit["id"]

    # AI_TURN.md: Set ATTACK_LEFT = CC_NB at activation start
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    cc_weapons = unit.get("CC_WEAPONS", [])
    if cc_weapons:
        selected_idx = unit.get("selectedCcWeaponIndex", 0)
        if selected_idx < 0 or selected_idx >= len(cc_weapons):
            raise IndexError(f"Invalid selectedCcWeaponIndex {selected_idx} for unit {unit['id']}")
        weapon = cc_weapons[selected_idx]
        unit["ATTACK_LEFT"] = weapon["NB"]
    else:
        unit["ATTACK_LEFT"] = 0  # Pas d'armes melee

    # Build valid target pool (enemies adjacent within CC_RNG)
    valid_targets = _fight_build_valid_target_pool(game_state, unit)

    if not valid_targets:
        # No targets - end activation with PASS
        # AI_TURN.md: ATTACK_LEFT = CC_NB? YES → no attack → end_activation (PASS, 1, PASS, FIGHT)
        result = end_activation(
            game_state, unit,
            "PASS",        # Arg1: Pass logging
            1,             # Arg2: +1 step increment
            "PASS",        # Arg3: No tracking (no attack made)
            "FIGHT",       # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []

        # AI_TURN.md: Check if ALL pools are empty → phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result

    # Check for PvE AI auto-execution (similar to shooting phase)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 1
    
    if is_pve_ai and valid_targets:
        # AUTO-FIGHT: PvE AI auto-selects target and executes attack
        target_id = _ai_select_fight_target(game_state, unit_id, valid_targets)
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
        "waiting_for_player": True
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
    # If BOTH pools have units → continue alternating (toggle)
    # If ONE pool empty → exit loop to cleanup phase (don't toggle)
    if active_pool and non_active_pool:
        # Both pools have units → toggle
        current_turn = game_state["fight_alternating_turn"]
        if current_turn == "non_active":
            game_state["fight_alternating_turn"] = "active"
        else:
            game_state["fight_alternating_turn"] = "non_active"
    # else: One pool empty → cleanup phase, don't toggle


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
    AI_TURN.md: Build valid fight target pool.

    Valid targets:
    - Enemy units
    - HP_CUR > 0
    - Adjacent to attacker (within melee range distance)

    NO LINE OF SIGHT CHECK (fight doesn't need LoS)
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    unit_col, unit_row = unit["col"], unit["row"]
    unit_player = unit["player"]

    valid_targets = []

    for target in game_state["units"]:
        # AI_TURN.md: Enemy check
        if target["player"] == unit_player:
            continue

        # AI_TURN.md: Alive check
        if target["HP_CUR"] <= 0:
            continue

        # AI_TURN.md: Adjacent check (within melee range)
        distance = _calculate_hex_distance(unit_col, unit_row, target["col"], target["row"])
        if distance > cc_range:
            continue

        # Valid target
        valid_targets.append(target["id"])

    return valid_targets


def _handle_fight_attack(game_state: Dict[str, Any], unit: Dict[str, Any], target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Handle fight attack execution.

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
        return False, {"error": "no_attacks_remaining", "unitId": unit_id}

    # Validate target is valid
    valid_targets = _fight_build_valid_target_pool(game_state, unit)
    if target_id not in valid_targets:
        return False, {"error": "invalid_target", "targetId": target_id, "valid_targets": valid_targets}
    
    # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cette cible ===
    target = _get_unit_by_id(game_state, target_id)
    if not target:
        return False, {"error": "target_not_found", "targetId": target_id}
    
    from engine.ai.weapon_selector import select_best_melee_weapon
    best_weapon_idx = select_best_melee_weapon(unit, target, game_state)
    
    if best_weapon_idx >= 0:
        unit["selectedCcWeaponIndex"] = best_weapon_idx
        # Mettre à jour ATTACK_LEFT avec la nouvelle arme (si pas déjà initialisé ou si arme change)
        weapon = unit["CC_WEAPONS"][best_weapon_idx]
        current_attack_left = unit.get("ATTACK_LEFT", 0)
        # Si ATTACK_LEFT n'est pas encore initialisé, réinitialiser
        if current_attack_left == 0:
            unit["ATTACK_LEFT"] = weapon["NB"]
    else:
        # Pas d'armes disponibles
        unit["ATTACK_LEFT"] = 0
        return False, {"error": "no_weapons_available", "unitId": unit["id"]}
    # === FIN NOUVEAU ===

    # Initialize accumulated attack results list for this unit's activation
    # This stores ALL attacks made during the weapon NB attack loop
    if "fight_attack_results" not in game_state:
        game_state["fight_attack_results"] = []

    # Execute attack sequence using selected weapon
    attack_result = _execute_fight_attack_sequence(game_state, unit, target_id)

    # Store this attack result with metadata for step logging
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(unit)
    total_attacks = selected_weapon["NB"] if selected_weapon else 0
    
    attack_result["attackerId"] = unit_id
    attack_result["targetId"] = target_id
    attack_result["attack_number"] = total_attacks - unit["ATTACK_LEFT"]  # 1-indexed (before decrement)
    attack_result["total_attacks"] = total_attacks
    game_state["fight_attack_results"].append(attack_result)

    # Decrement ATTACK_LEFT
    unit["ATTACK_LEFT"] -= 1

    # Check if more attacks remain
    if unit["ATTACK_LEFT"] > 0:
        # Rebuild target pool (target may have died)
        valid_targets_after = _fight_build_valid_target_pool(game_state, unit)

        if valid_targets_after:
            # More attacks and targets available
            # AI_TURN.md COMPLIANCE: Check if gym training mode or PvE AI - auto-continue attack loop
            is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
            is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 1

            if is_gym_training or is_pve_ai:
                # GYM TRAINING / PvE AI: Auto-continue attack loop until ATTACK_LEFT = 0 or no targets
                # Select next target (use AI selection logic)
                next_target_id = _ai_select_fight_target(game_state, unit["id"], valid_targets_after)
                if next_target_id:
                    # Recursively call to continue the attack loop
                    return _handle_fight_attack(game_state, unit, next_target_id, config)
                # No valid target selected - fall through to end activation

            else:
                # HUMAN PLAYER: Return waiting_for_player for manual target selection
                return True, {
                    "attack_executed": True,
                    "attack_result": attack_result,
                    "unitId": unit["id"],
                    "ATTACK_LEFT": unit["ATTACK_LEFT"],
                    "valid_targets": valid_targets_after,
                    "waiting_for_player": True
                }
        # No more targets or no valid target selected - fall through to end activation

        # No more targets - end activation
        # AI_TURN.md: ATTACK_LEFT > 0 but no targets → end_activation (ACTION, 1, FIGHT, FIGHT)
        result = end_activation(
            game_state, unit,
            "ACTION",      # Arg1: Log action
            1,             # Arg2: +1 step
            "FIGHT",       # Arg3: FIGHT tracking
            "FIGHT",       # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []

        result["action"] = "combat"  # Must be "combat" for step_logger (not "fight")
        result["phase"] = "fight"  # For metrics tracking
        result["unitId"] = unit_id  # For step_logger
        result["targetId"] = target_id  # For reward calculator
        result["attack_result"] = attack_result
        result["target_died"] = attack_result.get("target_died", False)  # For metrics tracking
        result["reason"] = "no_more_targets"

        # Include ALL attack results from this activation for step logging
        result["all_attack_results"] = game_state.get("fight_attack_results", [attack_result])
        # Clear accumulated results for next unit
        game_state["fight_attack_results"] = []

        # AI_TURN.md: Check if ALL pools are empty → phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result
    else:
        # ATTACK_LEFT = 0 - end activation
        # AI_TURN.md: end_activation (ACTION, 1, FIGHT, FIGHT)
        result = end_activation(
            game_state, unit,
            "ACTION",      # Arg1: Log action
            1,             # Arg2: +1 step
            "FIGHT",       # Arg3: FIGHT tracking
            "FIGHT",       # Arg4: Remove from fight pool
            0              # Arg5: No error logging
        )
        # CRITICAL: Clear active_fight_unit so next unit can be activated
        game_state["active_fight_unit"] = None
        game_state["valid_fight_targets"] = []

        result["action"] = "combat"  # Must be "combat" for step_logger (not "fight")
        result["phase"] = "fight"  # For metrics tracking
        result["unitId"] = unit_id  # For step_logger
        result["targetId"] = target_id  # For reward calculator
        result["attack_result"] = attack_result
        result["target_died"] = attack_result.get("target_died", False)  # For metrics tracking
        result["reason"] = "attacks_complete"

        # Include ALL attack results from this activation for step logging
        result["all_attack_results"] = game_state.get("fight_attack_results", [attack_result])
        # Clear accumulated results for next unit
        game_state["fight_attack_results"] = []

        # AI_TURN.md: Check if ALL pools are empty → phase complete
        if result.get("phase_complete"):
            # All fight pools empty - transition to next phase
            phase_result = _fight_phase_complete(game_state)
            # Merge phase transition info into result
            result.update(phase_result)
        else:
            # More units to activate - toggle alternation and update subphase
            # AI_TURN.md Lines 762-764, 844-846: Toggle alternation after activation completes
            _toggle_fight_alternation(game_state)
            # CRITICAL: Recalculate fight_subphase after pool changes
            _update_fight_subphase(game_state)

        return True, result


def _handle_fight_postpone(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Handle postpone action.

    CRITICAL: Can ONLY postpone if ATTACK_LEFT = CC_NB (no attacks made yet)
    If unit has already attacked, must complete activation.
    """
    unit_id = unit["id"]

    # AI_TURN.md: Check ATTACK_LEFT = weapon NB?
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    if "ATTACK_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'ATTACK_LEFT' field: {unit}")
    
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(unit)
    if not selected_weapon:
        return False, {"error": "no_melee_weapon", "unitId": unit["id"]}
    
    if unit["ATTACK_LEFT"] == selected_weapon["NB"]:
        # AI_TURN.md: YES → Postpone allowed
        # Do NOT call end_activation - just return postpone signal
        # Unit stays in pool for later activation
        return True, {
            "action": "postpone",
            "unitId": unit_id,
            "postpone_allowed": True
        }
    else:
        # AI_TURN.md: NO → Must complete activation
        return False, {
            "error": "postpone_not_allowed",
            "reason": "unit_has_already_attacked",
            "ATTACK_LEFT": unit["ATTACK_LEFT"],
            "CC_NB": unit["CC_NB"]
        }


def _handle_fight_unit_switch(game_state: Dict[str, Any], current_unit: Dict[str, Any], new_unit_id: str) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_TURN.md: Handle unit switching during fight phase.

    Can only switch if current unit has ATTACK_LEFT = CC_NB (hasn't attacked yet).
    Otherwise must complete current unit's activation.
    """
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if postpone is allowed using selected weapon
    from engine.utils.weapon_helpers import get_selected_melee_weapon
    selected_weapon = get_selected_melee_weapon(current_unit)
    if not selected_weapon:
        postpone_allowed = False
    else:
        postpone_allowed = (current_unit["ATTACK_LEFT"] == selected_weapon["NB"])

    if postpone_allowed:
        # Switch to new unit
        new_unit = _get_unit_by_id(game_state, new_unit_id)
        if not new_unit:
            return False, {"error": "unit_not_found", "unitId": new_unit_id}

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

    target = _get_unit_by_id(game_state, target_id)
    if not target:
        raise ValueError(f"Target unit not found: {target_id}")

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
    
    # Hit roll → hit_roll >= weapon.ATK
    hit_roll = random.randint(1, 6)
    hit_target = weapon["ATK"]
    hit_success = hit_roll >= hit_target

    if not hit_success:
        # MISS case
        attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) : MISSED !"
    else:
        # HIT → Continue to wound roll
        wound_roll = random.randint(1, 6)
        wound_target = _calculate_wound_target(weapon["STR"], target["T"])
        wound_success = wound_roll >= wound_target

        if not wound_success:
            # FAIL TO WOUND case
            attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) : FAILED !"
        else:
            # WOUND → Continue to save roll
            save_roll = random.randint(1, 6)
            save_target = _calculate_save_target(target, weapon["AP"])
            save_success = save_roll >= save_target

            if save_success:
                # SAVED case
                attack_log = f"Unit {attacker_id} ATTACKED Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) : SAVED !"
            else:
                # DAMAGE case - apply damage
                damage_dealt = weapon["DMG"]
                target["HP_CUR"] = max(0, target["HP_CUR"] - damage_dealt)
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate kill probability cache for target
                from engine.ai.weapon_selector import invalidate_cache_for_target
                cache = game_state.get("kill_probability_cache", {})
                invalidate_cache_for_target(cache, str(target["id"]))
                
                target_died = target["HP_CUR"] <= 0

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
        "attack_log": attack_log
    }


def shooting_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Route click actions to appropriate handlers
    """
    # AI_TURN.md COMPLIANCE: Direct field access
    if "targetId" not in action:
        target_id = None
    else:
        target_id = action["targetId"]
    
    if "clickTarget" not in action:
        click_target = "target"
    else:
        click_target = action["clickTarget"]
    
    if click_target in ["target", "enemy"] and target_id:
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    elif click_target == "friendly_unit" and target_id:
        # Left click on another unit in pool - switch units
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if target_id in game_state["shoot_activation_pool"]:
            return _handle_unit_switch_with_context(game_state, unit_id, target_id, config)
        return False, {"error": "unit_not_in_pool", "targetId": target_id}
    
    elif click_target == "active_unit":
        # Left click on active unit - no effect or show targets again
        return _shooting_unit_execution_loop(game_state, unit_id, config)
    
    else:
        # Left click elsewhere - continue selection
        return True, {"action": "continue_selection", "context": "elsewhere_clicked"}


def shooting_target_selection_handler(game_state: Dict[str, Any], unit_id: str, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle target selection and shooting execution.
    Supports both agent-selected targetId and auto-selection fallback for humans.
    """    
    unit = _get_unit_by_id(game_state, unit_id)
    
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # CRITICAL: Validate unit has shots remaining
    if "SHOOT_LEFT" not in unit:
        raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
    if unit["SHOOT_LEFT"] <= 0:
        return False, {"error": "no_shots_remaining", "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"]}
    
    # Build valid target pool
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    if not valid_targets:
        return False, {"error": "no_valid_targets", "unitId": unit_id}
    
    # Handle target selection: agent-provided or auto-select
    if target_id and target_id in valid_targets:
        # Agent provided valid target
        selected_target_id = target_id
    elif target_id:
        # Agent provided invalid target
        return False, {"error": "target_not_valid", "targetId": target_id}
    else:
        # No target provided - auto-select first valid target (human player fallback)
        selected_target_id = valid_targets[0]
    
    target = _get_unit_by_id(game_state, selected_target_id)
    if not target:
        return False, {"error": "target_not_found", "targetId": selected_target_id}
    
    # Execute shooting attack
    attack_result = shooting_attack_controller(game_state, unit_id, selected_target_id)
    
    # Update SHOOT_LEFT and continue loop per AI_TURN.md
    unit["SHOOT_LEFT"] -= 1
    
    # Continue execution loop to check for more shots or end activation
    result = _shooting_unit_execution_loop(game_state, unit_id, config)
    return result


def shooting_attack_controller(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(RNG) implementation with proper logging
    """
    shooter = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not shooter or not target:
        return {"error": "unit_or_target_not_found"}
    
    # FOCUS FIRE: Store target's HP before damage for reward calculation
    target_hp_before_damage = target["HP_CUR"]

    # Execute single attack_sequence(RNG) per AI_TURN.md
    attack_result = _attack_sequence_rng(shooter, target)

    # Apply damage immediately per AI_TURN.md
    if attack_result["damage"] > 0:
        target["HP_CUR"] = max(0, target["HP_CUR"] - attack_result["damage"])
        # Check if target died
        if target["HP_CUR"] <= 0:
            attack_result["target_died"] = True
            # PERFORMANCE: Invalidate LoS cache for dead unit (partial invalidation)
            _invalidate_los_cache_for_unit(game_state, target["id"])

    # Store pre-damage HP in attack_result for reward calculation
    attack_result["target_hp_before_damage"] = target_hp_before_damage
    
    # CRITICAL: Store detailed log for frontend display with location data
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # Enhanced message format including shooter position per movement phase integration
    enhanced_message = f"Unit {unit_id} ({shooter['col']}, {shooter['row']}) SHOT Unit {target_id} ({target['col']}, {target['row']}) : {attack_result['attack_log'].split(' : ', 1)[1] if ' : ' in attack_result['attack_log'] else attack_result['attack_log']}"

    # CRITICAL FIX: Append action_log BEFORE reward calculation
    # This ensures the log exists even if reward calculation fails
    action_reward = 0.0
    action_name = "ranged_attack"

    game_state["action_logs"].append({
        "type": "shoot",
        "message": enhanced_message,
        "turn": game_state["turn"],
        "phase": "shoot",
        "shooterId": unit_id,
        "targetId": target_id,
        "player": shooter["player"],
        "shooterCol": shooter["col"],
        "shooterRow": shooter["row"],
        "targetCol": target["col"],
        "targetRow": target["row"],
        "damage": attack_result["damage"],
        "target_died": attack_result.get("target_died", False),
        "hitRoll": attack_result.get("hit_roll"),
        "woundRoll": attack_result.get("wound_roll"),
        "saveRoll": attack_result.get("save_roll"),
        "saveTarget": attack_result.get("save_target"),
        "timestamp": "server_time",
        "action_name": action_name,
        "reward": 0.0,  # Will be updated after reward calculation
        "is_ai_action": shooter["player"] == 1
    })

    # Calculate reward for this action using progressive bonus system
    # OPTIMIZATION: Only calculate rewards for controlled player's units
    # Bot units don't need rewards since they don't learn
    config = game_state.get("config", {})
    controlled_player = config.get("controlled_player", 0)

    # Skip reward calculation for bot units (not the controlled player)
    if shooter["player"] != controlled_player:
        action_reward = 0.0
        # Continue without calculating detailed rewards
    else:
   
        try:
            from ai.reward_mapper import RewardMapper
            rewards_configs = game_state.get("rewards_configs")
            if not rewards_configs:
                raise ValueError(f"rewards_configs is missing from game_state for shooter {shooter.get('id', 'unknown')}")

        # CRITICAL FIX: Use controlled_agent for reward config lookup (includes phase suffix)
            config = game_state.get("config", {})
            controlled_agent = config.get("controlled_agent")

            if not controlled_agent:
                # Fallback: use unit_registry mapping if no controlled_agent
                from ai.unit_registry import UnitRegistry
                unit_registry = UnitRegistry()
                shooter_unit_type = shooter["unitType"]
                reward_config_key = unit_registry.get_model_key(shooter_unit_type)
            else:
                # Training mode: use controlled_agent which includes phase suffix
                reward_config_key = controlled_agent

        # Get unit-specific config - RAISE ERROR if not found
            unit_reward_config = rewards_configs.get(reward_config_key)
            if not unit_reward_config:
                raise ValueError(f"No reward config found for unit type '{reward_config_key}' in rewards_configs. Available: {list(rewards_configs.keys())}")

            reward_mapper = RewardMapper(unit_reward_config)

        # Get unit_registry for mapping scenario types
            from ai.unit_registry import UnitRegistry
            unit_registry = UnitRegistry()
        
        # Get the shooter's actual scenario unit type
            shooter_scenario_type = shooter["unitType"]
        
            try:
            # Map scenario type to reward config key using unit_registry
                shooter_reward_key = unit_registry.get_model_key(shooter_scenario_type)
            except ValueError:
            # Unit type not found in registry
                shooter_reward_key = None
        
        # CHANGE 5: Use controlled_agent for ALL units when in training mode
        # This ensures consistent reward scaling across both players (e.g., phase4 rewards for all)
            if controlled_agent and shooter_reward_key:
            # Training mode - use controlled_agent for ALL units (includes phase suffix)
                enriched_shooter = shooter.copy()
                enriched_shooter["unitType"] = controlled_agent  # CHANGE 5: Removed player check - all units use phase1
            elif shooter_reward_key:
            # No controlled_agent or not in training - use registry mapping
                enriched_shooter = shooter.copy()
                enriched_shooter["unitType"] = shooter_reward_key
            else:
            # CHANGE 7: NO FALLBACK - raise error if no valid config found
                raise ValueError(f"Cannot determine reward config for shooter {shooter.get('id', 'unknown')}: controlled_agent={controlled_agent}, shooter_reward_key={shooter_reward_key if 'shooter_reward_key' in locals() else 'not_set'}")
       
        # Get unit rewards config
            unit_rewards = reward_mapper._get_unit_rewards(enriched_shooter)
            base_actions = unit_rewards.get("base_actions", {})
            result_bonuses = unit_rewards.get("result_bonuses", {})
       
            if "ranged_attack" not in base_actions:
                raise KeyError(f"Missing 'ranged_attack' in base_actions for unit {shooter['id']} (enriched_unitType={enriched_shooter.get('unitType')}): base_actions={base_actions}")
        
            base_ranged_reward = base_actions["ranged_attack"]
        
        # Base shooting reward (always given for taking the shot)
            action_reward = base_ranged_reward
       
        # Progressive bonuses based on attack sequence results
            if attack_result.get("hit_success", False):
                if "hit_target" in result_bonuses:
                    action_reward += result_bonuses["hit_target"]
                    action_name = "hit_target"
       
            if attack_result.get("wound_success", False):
                if "wound_target" in result_bonuses:
                    action_reward += result_bonuses["wound_target"]
                    action_name = "wound_target"
       
            if attack_result.get("damage", 0) > 0:
                if "damage_target" in result_bonuses:
                    action_reward += result_bonuses["damage_target"]
                    action_name = "damage_target"
       
            if attack_result.get("target_died", False):
                if "kill_target" in result_bonuses:
                    action_reward += result_bonuses["kill_target"]
                    action_name = "kill_target"

            # No overkill bonus (exact kill)
                if target["HP_CUR"] == attack_result.get("damage", 0):
                    if "no_overkill" in result_bonuses:
                        action_reward += result_bonuses["no_overkill"]

            # FOCUS FIRE BONUS: Check if shooter targeted the lowest HP enemy
            if "target_lowest_hp" in result_bonuses:
                try:
                    # Get all valid targets this shooter could have shot AT THE TIME OF SHOOTING
                    valid_target_ids = shooting_build_valid_target_pool(game_state, shooter["id"])

                    if len(valid_target_ids) > 1:  # Only apply if there was a choice
                        # Get the target's HP before this shot (from attack_result)
                        target_hp_before = attack_result.get("target_hp_before_damage")
                        if target_hp_before is None:
                            # Fallback to current HP if not stored (shouldn't happen)
                            target_hp_before = target["HP_CUR"]

                        # Find the lowest HP among all valid targets AT THE TIME OF SHOOTING
                        lowest_hp = float('inf')
                        for target_id in valid_target_ids:
                            candidate = _get_unit_by_id(game_state, target_id)
                            if not candidate:
                                continue

                            # Get candidate's current HP
                            # If this is the target we just shot, use pre-damage HP
                            if candidate["id"] == target["id"]:
                                candidate_hp = target_hp_before
                            else:
                                candidate_hp = candidate.get("HP_CUR", 0)

                            # Only consider alive targets
                            if candidate_hp > 0:
                                lowest_hp = min(lowest_hp, candidate_hp)

                        # Check if the actual target had the lowest HP (or tied for lowest)
                        if target_hp_before > 0 and target_hp_before <= lowest_hp:
                            action_reward += result_bonuses["target_lowest_hp"]
                            # Don't override action_name - keep kill_target/damage_target as primary
                except Exception as focus_fire_error:
                    # Don't crash training if focus fire bonus fails
                    import traceback
                    print(f"⚠️  Focus fire bonus calc failed: {focus_fire_error}")
                    print(f"   Traceback: {traceback.format_exc()}")
                    pass

        except Exception as e:
            print(f"🚨 REWARD CALC FAILED for {shooter.get('id', 'unknown')} (P{shooter.get('player', '?')}): {e}")
            print(f"   shooter_scenario_type={shooter.get('unitType', 'missing')}")
            if 'shooter_reward_key' in locals():
                print(f"   shooter_reward_key={shooter_reward_key}")
            if 'controlled_agent' in locals():
                print(f"   controlled_agent={controlled_agent}")
            if 'config' in locals():
                print(f"   controlled_player={config.get('controlled_player', 'not_set')}")
            raise

    # Update the action_log entry with calculated reward and action_name
    logged_reward = round(action_reward, 2)

    if game_state["action_logs"]:
        last_log = game_state["action_logs"][-1]
        if last_log.get("shooterId") == unit_id and last_log.get("type") == "shoot":
            last_log["reward"] = logged_reward
            last_log["action_name"] = action_name
    
    # Store attack result for engine access
    game_state["last_attack_result"] = attack_result
    game_state["last_target_id"] = target_id
    
    if "calculated_rewards" not in game_state:
        game_state["calculated_rewards"] = {}
    game_state["calculated_rewards"][unit_id] = logged_reward
    game_state["last_calculated_reward"] = logged_reward
    
    return {
        "action": "shot_executed",
        "shooterId": unit_id,
        "targetId": target_id,
        "attack_result": attack_result,
        "target_hp_remaining": target["HP_CUR"],
        "target_died": target["HP_CUR"] <= 0,
        "calculated_reward": logged_reward
    }


def _attack_sequence_rng(attacker: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_TURN.md EXACT: attack_sequence(RNG) with proper <OFF> replacement
    """
    import random
    
    attacker_id = attacker["id"] 
    target_id = target["id"]
    
    # Hit roll → hit_roll >= attacker.RNG_ATK
    hit_roll = random.randint(1, 6)
    hit_target = attacker["RNG_ATK"]
    hit_success = hit_roll >= hit_target
    
    if not hit_success:
        # MISS case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) : MISSED !"
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "hit_success": False,
            "wound_roll": 0,
            "wound_target": 0,
            "wound_success": False,
            "save_roll": 0,
            "save_target": 0,
            "save_success": False,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # HIT → Continue to wound roll
    wound_roll = random.randint(1, 6)
    wound_target = _calculate_wound_target(attacker["RNG_STR"], target["T"])
    wound_success = wound_roll >= wound_target
    
    if not wound_success:
        # FAIL case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) : FAILED !"
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "hit_success": True,  # Hit succeeded to reach wound roll
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": False,
            "save_roll": 0,
            "save_target": 0,
            "save_success": False,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # WOUND → Continue to save roll
    save_roll = random.randint(1, 6)
    save_target = _calculate_save_target(target, attacker["RNG_AP"])
    save_success = save_roll >= save_target
    
    if save_success:
        # SAVE case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) : SAVED !"
        return {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "hit_success": True,  # Hit succeeded
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": True,  # Wound succeeded
            "save_roll": save_roll,
            "save_target": save_target,
            "save_success": True,
            "damage": 0,
            "attack_log": attack_log
        }
    
    # FAIL → Continue to damage
    damage_dealt = attacker["RNG_DMG"]
    new_hp = max(0, target["HP_CUR"] - damage_dealt)
    
    if new_hp <= 0:
        # Target dies
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} delt : Unit {target_id} DIED !"
    else:
        # Target survives
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} DAMAGE DELT !"
    
    return {
        "hit_roll": hit_roll,
        "hit_target": hit_target,
        "hit_success": True,  # Hit succeeded
        "wound_roll": wound_roll,
        "wound_target": wound_target,
        "wound_success": True,  # Wound succeeded
        "save_roll": save_roll,
        "save_target": save_target,
        "save_success": False,  # Save failed
        "damage": damage_dealt,
        "attack_log": attack_log
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


def _handle_unit_switch_with_context(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle switching between units in activation pool
    """
    # End current unit activation
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if current_unit:
        _shooting_activation_end(game_state, current_unit, "WAIT", 1, "PASS", "SHOOTING")
    
    # Start new unit activation
    new_unit = _get_unit_by_id(game_state, new_unit_id)
    if new_unit:
        result = shooting_unit_activation_start(game_state, new_unit_id)
        if result.get("success"):
            return _shooting_unit_execution_loop(game_state, new_unit_id, config)
    
    return False, {"error": "unit_switch_failed"}


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
    
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= rng_rng:
                return True  # Simplified - assume clear LoS for now
    
    return False

def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state.

    CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
    """
    for unit in game_state["units"]:
        if str(unit["id"]) == str(unit_id):
            return unit
    return None

def _calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Calculate hex distance using consistent cube coordinates."""
    # Use same calculation across all handlers
    def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
        x = col
        z = row - (col - (col & 1)) // 2
        y = -x - z
        return (x, y, z)
    
    def cube_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> int:
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
    
    cube1 = offset_to_cube(col1, row1)
    cube2 = offset_to_cube(col2, row2)
    return cube_distance(cube1, cube2)


# Legacy compatibility
def get_eligible_units(game_state: Dict[str, Any]) -> List[str]:
    """Legacy compatibility - use shooting_build_activation_pool instead"""
    pool = shooting_build_activation_pool(game_state)
    return pool

def _calculate_target_priority_score(unit: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_DMG/CC_DMG
    """
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max DMG from all weapons
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Calculate max threat from target's weapons
    target_rng_weapon = get_selected_ranged_weapon(target)
    target_cc_weapon = get_selected_melee_weapon(target)
    target_rng_dmg = target_rng_weapon.get("DMG", 0) if target_rng_weapon else 0
    target_cc_dmg = target_cc_weapon.get("DMG", 0) if target_cc_weapon else 0
    # Also check all weapons for max threat
    if target.get("RNG_WEAPONS"):
        target_rng_dmg = max(target_rng_dmg, max(w.get("DMG", 0) for w in target["RNG_WEAPONS"]))
    if target.get("CC_WEAPONS"):
        target_cc_dmg = max(target_cc_dmg, max(w.get("DMG", 0) for w in target["CC_WEAPONS"]))
    
    threat_level = max(target_rng_dmg, target_cc_dmg)
    
    # Calculate if unit can kill target in 1 phase (use selected weapon or first weapon)
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    if not unit_rng_weapon and unit.get("RNG_WEAPONS"):
        unit_rng_weapon = unit["RNG_WEAPONS"][0]
    unit_rng_dmg = unit_rng_weapon.get("DMG", 0) if unit_rng_weapon else 0
    can_kill_1_phase = target["HP_CUR"] <= unit_rng_dmg
    
    # Priority 1: High threat that melee can charge but won't kill (score: 1000)
    if threat_level >= 3:  # High threat threshold
        melee_can_charge = _check_if_melee_can_charge(target, game_state)
        if melee_can_charge and target["HP_CUR"] > 2:  # Won't die to melee in 1 phase
            return 1000 + threat_level
    
    # Priority 2: High threat that can be killed in 1 shooting phase (score: 800) 
    if can_kill_1_phase and threat_level >= 3:
        return 800 + threat_level
    
    # Priority 3: High threat, lowest HP that can be killed (score: 600)
    if can_kill_1_phase and threat_level >= 2:
        return 600 + threat_level + (10 - target["HP_CUR"])  # Prefer lower HP
    
    # Default: threat level only
    return threat_level

def _enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich unit data for reward mapper compatibility (matches engine format)."""
    if not unit:
        return {}
    
    # AI_TURN.md COMPLIANCE: Direct field access with validation
    if "agent_mapping" not in game_state:
        agent_mapping = {}
    else:
        agent_mapping = game_state["agent_mapping"]
    
    unit_id_key = str(unit["id"])
    if unit_id_key in agent_mapping:
        controlled_agent = agent_mapping[unit_id_key]
    elif "unitType" in unit:
        controlled_agent = unit["unitType"]
    elif "unit_type" in unit:
        controlled_agent = unit["unit_type"]
    else:
        controlled_agent = "default"
    
    enriched = unit.copy()
    
    # AI_TURN.md COMPLIANCE: All required fields must be present
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_DMG/RNG_DMG
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    if "HP_CUR" not in unit:
        raise KeyError(f"Unit missing required 'HP_CUR' field: {unit}")
    
    # Get max DMG from weapons
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    unit_cc_weapon = get_selected_melee_weapon(unit)
    rng_dmg = unit_rng_weapon.get("DMG", 0) if unit_rng_weapon else 0
    cc_dmg = unit_cc_weapon.get("DMG", 0) if unit_cc_weapon else 0
    # Also check all weapons for max DMG
    if unit.get("RNG_WEAPONS"):
        rng_dmg = max(rng_dmg, max(w.get("DMG", 0) for w in unit["RNG_WEAPONS"]))
    if unit.get("CC_WEAPONS"):
        cc_dmg = max(cc_dmg, max(w.get("DMG", 0) for w in unit["CC_WEAPONS"]))
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": cc_dmg,
        "rng_dmg": rng_dmg,
        "CUR_HP": unit["HP_CUR"]
    })
    
    return enriched

def _check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        if (unit["player"] == current_player and 
            unit["HP_CUR"] > 0):
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            from engine.utils.weapon_helpers import get_selected_melee_weapon
            has_melee = False
            if unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                melee_weapon = get_selected_melee_weapon(unit)
                if melee_weapon and melee_weapon.get("DMG", 0) > 0:
                    has_melee = True
            if has_melee:  # Has melee capability
                
                # Estimate charge range (unit move + average 2d6)
                distance = _calculate_hex_distance(unit["col"], unit["row"], target["col"], target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge = unit["MOVE"] + 7  # Average 2d6 = 7
            
            if distance <= max_charge:
                return True
    
    return False