#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_Shooting_Phase.md Basic Implementation
Only pool building functionality - foundation for complete handler autonomy
"""

from typing import Dict, List, Tuple, Set, Optional, Any

# ============================================================================
# PERFORMANCE: Target pool caching (30-40% speedup)
# ============================================================================
# Cache valid target pools to avoid repeated distance/LoS calculations
# Cache key: (unit_id, col, row) - invalidates automatically when unit changes
_target_pool_cache = {}  # {(unit_id, col, row): [enemy_id, enemy_id, ...]}
_cache_size_limit = 100  # Prevent memory leak in long episodes


def shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Initialize shooting phase and build activation pool
    """
    global _target_pool_cache

    # Set phase
    game_state["phase"] = "shoot"

    # CRITICAL: Clear target pool cache at phase start - targets may have moved
    # The cache key only includes shooter position, not target positions
    # So stale cache entries could allow shooting blocked targets
    _target_pool_cache.clear()

    # AI_TURN.md COMPLIANCE: Reset SHOOT_LEFT for all units at phase start
    current_player = game_state["current_player"]
    for unit in game_state["units"]:
        if unit["player"] == current_player and unit["HP_CUR"] > 0:
            unit["SHOOT_LEFT"] = unit["RNG_NB"]

    # PERFORMANCE: Build LoS cache once at phase start (10-100x speedup)
    _build_shooting_los_cache(game_state)
    
    # Build activation pool
    eligible_units = shooting_build_activation_pool(game_state)
    
    # Silent pool building - no console logs during normal operation
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    
    return {
        "phase_initialized": True,
        "eligible_units": len(eligible_units),
        "phase_complete": len(eligible_units) == 0
    }


def _build_shooting_los_cache(game_state: Dict[str, Any]) -> None:
    """
    Build LoS cache for all unit pairs at shooting phase start.
    AI_TURN.md COMPLIANCE: Pure function, stores in game_state, no copying.
    
    Performance: O(n²) calculation once per phase vs O(n²×m) per activation.
    Called once per shooting phase, massive speedup during unit activations.
    """
    los_cache = {}
    
    # Get all alive units (both players)
    alive_units = [u for u in game_state["units"] if u["HP_CUR"] > 0]
    
    # Calculate LoS for every shooter-target pair
    for shooter in alive_units:
        for target in alive_units:
            # Skip same unit
            if shooter["id"] == target["id"]:
                continue
            
            # Calculate LoS using existing function (expensive but only once)
            cache_key = (shooter["id"], target["id"])
            los_cache[cache_key] = _has_line_of_sight(game_state, shooter, target)
    
    # Store cache in game_state (single source of truth)
    game_state["los_cache"] = los_cache
    
    # Debug log cache size (optional, remove in production)
    # print(f"LoS CACHE: Built {len(los_cache)} entries for {len(alive_units)} units")


def _invalidate_los_cache_for_unit(game_state: Dict[str, Any], dead_unit_id: str) -> None:
    """
    Partially invalidate LoS cache when unit dies.
    AI_TURN.md COMPLIANCE: Direct field access, no state copying.
    
    Only removes entries involving dead unit (performance optimization).
    """
    if "los_cache" not in game_state:
        return
    
    # Remove all cache entries involving dead unit
    keys_to_remove = [
        key for key in game_state["los_cache"].keys()
        if dead_unit_id in key
    ]
    
    for key in keys_to_remove:
        del game_state["los_cache"][key]


def shooting_build_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    AI_TURN.md: Build activation pool with comprehensive debug logging
    """
    current_player = game_state["current_player"]
    shoot_activation_pool = []
    
    for unit in game_state["units"]:
        if _has_valid_shooting_targets(game_state, unit, current_player):
            shoot_activation_pool.append(unit["id"])
    
    # Update game_state pool
    game_state["shoot_activation_pool"] = shoot_activation_pool
    return shoot_activation_pool

def _ai_select_shooting_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """AI target selection using RewardMapper system"""
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
        shooter_unit_type = unit["unitType"]
        shooter_agent_key = unit_registry.get_model_key(shooter_unit_type)
        
        # Get unit-specific config or fallback to default
        unit_reward_config = reward_configs.get(shooter_agent_key)
        if not unit_reward_config:
            raise ValueError(f"No reward config found for unit type '{shooter_agent_key}' in reward_configs")
        
        reward_mapper = RewardMapper(unit_reward_config)
        
        # Build target list for reward mapper
        all_targets = [_get_unit_by_id(game_state, tid) for tid in valid_targets if _get_unit_by_id(game_state, tid)]
        
        best_target = valid_targets[0]
        best_reward = -999999
        
        for target_id in valid_targets:
            target = _get_unit_by_id(game_state, target_id)
            if not target:
                continue
            
            can_melee_charge = False  # TODO: implement melee charge check
            
            reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, can_melee_charge)
            
            if reward > best_reward:
                best_reward = reward
                best_target = target_id
        
        # print(f"AI SHOOTING: Unit {unit_id} selected target {best_target} (reward: {best_reward})")
        return best_target
        
    except Exception as e:
        # print(f"AI target selection error: {e}")
        return valid_targets[0]

def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    EXACT COPY from w40k_engine_save.py _has_valid_shooting_targets logic
    WITH ALWAYS-ON DEBUG LOGGING
    """
    # FIXED: Disable debug output completely during training
    debug_mode = False  # Set to True only for manual debugging
    
    if debug_mode:
        print(f"\n🔍 ELIGIBILITY CHECK: Unit {unit['id']} @ ({unit['col']}, {unit['row']})")
        print(f"   Player: {unit['player']}, Current Player: {current_player}")
        print(f"   HP: {unit['HP_CUR']}/{unit['HP_MAX']}")
        print(f"   RNG_NB: {unit.get('RNG_NB', 'MISSING')}, RNG_RNG: {unit.get('RNG_RNG', 'MISSING')}")
        print(f"   CC_RNG: {unit.get('CC_RNG', 'MISSING')}")
    
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
            
            if debug_mode:
                print(f"      Enemy {enemy['id']} @ ({enemy['col']}, {enemy['row']}): distance={distance}, CC_RNG={unit['CC_RNG']}")
            
            if distance <= unit["CC_RNG"]:
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
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_NB" not in unit:
        raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
    if unit["RNG_NB"] <= 0:
        if debug_mode:
            print(f"   ❌ BLOCKED: No ranged attacks (RNG_NB={unit['RNG_NB']})")
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
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "CC_RNG" not in shooter:
        raise KeyError(f"Shooter missing required 'CC_RNG' field: {shooter}")
    if distance <= shooter["CC_RNG"]:
        if debug_mode:
            print(f"         ❌ Too close: dist={distance} <= CC_RNG={shooter['CC_RNG']}")
        return False

    # W40K RULE: Cannot shoot at enemy engaged in melee with friendly units
    # Check if target is adjacent to any friendly unit (same player as shooter)
    if "CC_RNG" not in target:
        raise KeyError(f"Target missing required 'CC_RNG' field: {target}")
    target_cc_range = target["CC_RNG"]

    for friendly in game_state["units"]:
        if friendly["player"] == shooter["player"] and friendly["HP_CUR"] > 0 and friendly["id"] != shooter["id"]:
            friendly_distance = _calculate_hex_distance(target["col"], target["row"], friendly["col"], friendly["row"])
            if friendly_distance <= target_cc_range:
                if debug_mode:
                    print(f"         ❌ Target engaged with friendly: {friendly['id']} at distance {friendly_distance}")
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
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_NB" not in unit:
        raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    unit["SHOOT_LEFT"] = unit["RNG_NB"]
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
    if "RNG_NB" not in unit:
        raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
    if "RNG_ATK" not in unit:
        raise KeyError(f"Unit missing required 'RNG_ATK' field: {unit}")
    if "RNG_STR" not in unit:
        raise KeyError(f"Unit missing required 'RNG_STR' field: {unit}")
    if "RNG_AP" not in unit:
        raise KeyError(f"Unit missing required 'RNG_AP' field: {unit}")
    if "unitType" not in unit:
        raise KeyError(f"Unit missing required 'unitType' field: {unit}")

    # Cache unit stats for priority calculations
    unit_t = unit["T"]
    unit_save = unit["ARMOR_SAVE"]
    unit_attacks = unit["RNG_NB"]
    unit_bs = unit["RNG_ATK"]
    unit_s = unit["RNG_STR"]
    unit_ap = unit["RNG_AP"]
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
        if "RNG_NB" not in target:
            raise KeyError(f"Target missing required 'RNG_NB' field: {target}")
        if "RNG_ATK" not in target:
            raise KeyError(f"Target missing required 'RNG_ATK' field: {target}")
        if "RNG_STR" not in target:
            raise KeyError(f"Target missing required 'RNG_STR' field: {target}")
        if "RNG_AP" not in target:
            raise KeyError(f"Target missing required 'RNG_AP' field: {target}")
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        if "ARMOR_SAVE" not in target:
            raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
        if "HP_CUR" not in target:
            raise KeyError(f"Target missing required 'HP_CUR' field: {target}")
        if "HP_MAX" not in target:
            raise KeyError(f"Target missing required 'HP_MAX' field: {target}")

        # Step 1: Calculate target's threat to us (probability to wound per turn)
        target_attacks = target["RNG_NB"]
        target_bs = target["RNG_ATK"]
        target_s = target["RNG_STR"]
        target_ap = target["RNG_AP"]

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

def _shooting_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete shooting phase with player progression and turn management
    """
    # Final cleanup
    game_state["shoot_activation_pool"] = []
    
    # PERFORMANCE: Clear LoS cache at phase end (will rebuild next shooting phase)
    if "los_cache" in game_state:
        game_state["los_cache"] = {}
    
    # Console log
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    game_state["console_logs"].append("SHOOTING PHASE COMPLETE")
    
    # AI_TURN.md: Player progression logic
    if game_state["current_player"] == 0:
        # AI_TURN.md Line 105: P0 Move → P0 Shoot → P0 Charge → P0 Fight
        # Player stays 0, advance to charge phase
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "charge",
            "current_player": 0,
            # AI_TURN.md COMPLIANCE: Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
            # CRITICAL: Add missing frontend cleanup signals
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
                "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
        else:
            # AI_TURN.md Line 105: P1 Move → P1 Shoot → P1 Charge → P1 Fight
            # Player stays 1, advance to charge phase
            # Turn increment happens at P1 Fight end (fight_handlers.py:797)
            return {
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "charge",
                "current_player": 1,
                # AI_TURN.md COMPLIANCE: Direct field access
                "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
                # CRITICAL: Add missing frontend cleanup signals
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }

def shooting_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy function - redirects to new complete function"""
    return _shooting_phase_complete(game_state)

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
        # SHOOT_LEFT = RNG_NB?
        if unit["SHOOT_LEFT"] == unit["RNG_NB"]:
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
    AI_SHOOT.md EXACT: Complete action routing with full phase lifecycle management
    """
    
    # Phase initialization on first call
    if "_shooting_phase_initialized" not in game_state or not game_state["_shooting_phase_initialized"]:
        shooting_phase_start(game_state)
        game_state["_shooting_phase_initialized"] = True
    
    # Clean execution logging
    if "shoot_activation_pool" not in game_state:
        current_pool = []
    else:
        current_pool = game_state["shoot_activation_pool"]
    
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = "none"  # Allow missing for some action types
    else:
        action_type = action["action"]
        unit_id = action["unitId"]
    if current_pool:
        # Remove units with no shots remaining
        updated_pool = []
        for pool_unit_id in current_pool:  # Changed: Use separate variable name
            unit_check = _get_unit_by_id(game_state, pool_unit_id)
            if unit_check and "SHOOT_LEFT" in unit_check:
                shots_left = unit_check["SHOOT_LEFT"]
            else:
                shots_left = 0
            if unit_check and shots_left > 0:
                updated_pool.append(pool_unit_id)  # Changed: Use pool_unit_id
        
        game_state["shoot_activation_pool"] = updated_pool
        current_pool = updated_pool
    
    # Check if shooting phase should complete after cleanup
    if not current_pool:
        game_state["_shooting_phase_initialized"] = False
        return True, _shooting_phase_complete(game_state)
    
    # Extract unit from action if not provided (engine passes None now)
    if unit is None:
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        unit_id = str(action["unitId"])
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # AI_TURN.md COMPLIANCE: Direct field access
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    unit_id = unit["id"]
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    if unit["player"] != game_state["current_player"]:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    if unit_id not in game_state["shoot_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # AI_SHOOT.md action routing
    if action_type == "activate_unit":
        result = shooting_unit_activation_start(game_state, unit_id)
        if result.get("success"):
            execution_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            return execution_result
        return True, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with optional targetId
        if "targetId" not in action:
            target_id = None
        else:
            target_id = action["targetId"]
        
        # CRITICAL: Validate unit eligibility
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if unit_id not in game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": unit_id}
        
        # Initialize unit for shooting if needed (only if not already activated)
        active_shooting_unit = game_state["active_shooting_unit"] if "active_shooting_unit" in game_state else None
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        if "RNG_NB" not in unit:
            raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
        
        if (active_shooting_unit != unit_id and unit["SHOOT_LEFT"] == unit["RNG_NB"]):
            # Only initialize if unit hasn't started shooting yet
            shooting_unit_activation_start(game_state, unit_id)
        
        # Auto-select target if not provided (AI mode)
        if not target_id:
            valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            
            # Debug output only in debug training mode
            debug_mode = config.get('training_config_name') == 'debug'
            if debug_mode:
                print(f"EXECUTE DEBUG: Auto-target selection found {len(valid_targets)} targets: {valid_targets}")
            
            if not valid_targets:
                # No valid targets - end activation with wait
                if debug_mode:
                    print(f"EXECUTE DEBUG: No valid targets found, ending activation with PASS")
                result = _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
                return True, result
            target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
            
            if debug_mode:
                print(f"EXECUTE DEBUG: AI selected target: {target_id}")
        
        # Execute shooting directly without UI loops
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    elif action_type == "wait" or action_type == "skip":
        # Handle gym wait/skip actions - unit chooses not to shoot
        
        # DIAGNOSTIC: Verify no cross-player contamination
        if unit["player"] != game_state["current_player"]:
            print(f"🚨 BUG DETECTED: Unit {unit_id} (player {unit['player']}) trying to wait during player {game_state['current_player']}'s turn!")
            print(f"   Current pool: {game_state.get('shoot_activation_pool', [])}")
            return False, {"error": "wrong_player_unit_wait", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
        
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        if unit_id in current_pool:
            result = _shooting_activation_end(game_state, unit, "SKIP", 1, "PASS", "SHOOTING")
            post_pool = game_state["shoot_activation_pool"] if "shoot_activation_pool" in game_state else []
            return result
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    elif action_type == "left_click":
        target_id = action.get("targetId")
        return shooting_click_handler(game_state, unit_id, action, config)
    
    elif action_type == "right_click":
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
    
    elif action_type == "skip":
        return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty - treat as miss but continue shooting sequence
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        if unit_id in current_pool:
            # Initialize unit if not already activated (this was the missing piece)
            active_shooting_unit = game_state.get("active_shooting_unit")
            if active_shooting_unit != unit_id:
                shooting_unit_activation_start(game_state, unit_id)
            
            # DO NOT decrement SHOOT_LEFT - invalid action doesn't consume a shot
            # Just continue execution loop which will handle auto-shooting for PvE AI
            result = _shooting_unit_execution_loop(game_state, unit_id, config)
            if isinstance(result, tuple) and len(result) >= 2:
                success, loop_result = result
                loop_result["invalid_action_penalty"] = True
                loop_result["attempted_action"] = action.get("attempted_action", "unknown")
                return success, loop_result
            else:
                return True, {"invalid_action_penalty": True, "attempted_action": action.get("attempted_action", "unknown")}
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


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
        "phase": "shoot",  # For metrics tracking
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

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate adjacency check"""
    if "CC_RNG" not in unit:
        raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
    cc_range = unit["CC_RNG"]
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate range check"""
    if "RNG_RNG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
    rng_rng = unit["RNG_RNG"]
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
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic."""
    
    # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
    if "RNG_DMG" not in target:
        raise KeyError(f"Target missing required 'RNG_DMG' field: {target}")
    if "CC_DMG" not in target:
        raise KeyError(f"Target missing required 'CC_DMG' field: {target}")
    if "RNG_DMG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
    
    threat_level = max(target["RNG_DMG"], target["CC_DMG"])
    can_kill_1_phase = target["HP_CUR"] <= unit["RNG_DMG"]
    
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
    if "CC_DMG" not in unit:
        raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
    if "RNG_DMG" not in unit:
        raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
    if "HP_CUR" not in unit:
        raise KeyError(f"Unit missing required 'HP_CUR' field: {unit}")
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": unit["CC_DMG"],
        "rng_dmg": unit["RNG_DMG"],
        "CUR_HP": unit["HP_CUR"]
    })
    
    return enriched

def _check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    for unit in game_state["units"]:
        if (unit["player"] == current_player and 
            unit["HP_CUR"] > 0):
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "CC_DMG" not in unit:
                raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
            if unit["CC_DMG"] > 0:  # Has melee capability
                
                # Estimate charge range (unit move + average 2d6)
                distance = _calculate_hex_distance(unit["col"], unit["row"], target["col"], target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge = unit["MOVE"] + 7  # Average 2d6 = 7
            
            if distance <= max_charge:
                return True
    
    return False