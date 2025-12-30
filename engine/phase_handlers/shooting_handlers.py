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


def _serialize_weapon_for_json(weapon: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert weapon dict to JSON-serializable format.
    Converts ParsedWeaponRule objects in WEAPON_RULES to strings.
    Recursively handles all fields to ensure complete serialization.
    """
    from engine.weapons.rules import ParsedWeaponRule
    
    serialized = {}
    
    # Recursively convert all fields
    for key, value in weapon.items():
        if isinstance(value, ParsedWeaponRule):
            # Convert ParsedWeaponRule to string
            if value.parameter is not None:
                serialized[key] = f"{value.rule}:{value.parameter}"
            else:
                serialized[key] = value.rule
        elif isinstance(value, list):
            # Convert list elements (e.g., WEAPON_RULES)
            serialized_list = []
            for item in value:
                if isinstance(item, ParsedWeaponRule):
                    if item.parameter is not None:
                        serialized_list.append(f"{item.rule}:{item.parameter}")
                    else:
                        serialized_list.append(item.rule)
                else:
                    serialized_list.append(item)
            serialized[key] = serialized_list
        else:
            # Copy other fields as-is
            serialized[key] = value
    
    return serialized


def _weapon_has_assault_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has ASSAULT rule allowing shooting after advance."""
    if not weapon:
        return False
    rules = weapon.get("WEAPON_RULES", [])
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, 'rule'):  # ParsedWeaponRule object
            if rule.rule == "ASSAULT":
                return True
        elif rule == "ASSAULT":  # String
            return True
    return False


def _weapon_has_pistol_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has PISTOL rule."""
    if not weapon:
        return False
    rules = weapon.get("WEAPON_RULES", [])
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, 'rule'):  # ParsedWeaponRule object
            if rule.rule == "PISTOL":
                return True
        elif rule == "PISTOL":  # String
            return True
    return False


def weapon_availability_check(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon_rule: int,
    advance_status: int,
    adjacent_status: int
) -> List[Dict[str, Any]]:
    """
    shoot_refactor.md EXACT: Filter weapons based on rules and context
    
    Args:
        game_state: Game state dictionary
        unit: Unit dictionary
        weapon_rule: 0 = no rules, 1 = rules apply
        advance_status: 0 = no advance, 1 = advanced
        adjacent_status: 0 = not adjacent, 1 = adjacent to enemy
    
    Returns:
        List of weapons that can be selected (weapon_available_pool)
        Each item has: index, weapon, can_use, reason
    """
    available_weapons = []
    rng_weapons = unit.get("RNG_WEAPONS", [])
    
    for idx, weapon in enumerate(rng_weapons):
        can_use = True
        reason = None
        
        # Check arg1 (weapon_rule)
        # arg1 = 0 → No weapon rules checked/applied (continue to next check)
        # arg1 = 1 → Weapon rules apply (continue to next check)
        
        # Check arg2 (advance_status)
        if advance_status == 1:
            # Unit DID advance
            if weapon_rule == 0:
                # arg1=0 AND arg2=1 → ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot after advance (weapon_rule=0)"
            else:
                # arg1=1 AND arg2=1 → ✅ Weapon MUST have ASSAULT rule (continue to next check)
                if not _weapon_has_assault_rule(weapon):
                    can_use = False
                    reason = "No ASSAULT rule (cannot shoot after advancing)"
        
        # Check arg3 (adjacent_status)
        if can_use and adjacent_status == 1:
            # Unit IS adjacent to enemy
            if weapon_rule == 0:
                # arg1=0 AND arg3=1 → ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot when adjacent (weapon_rule=0)"
            else:
                # arg1=1 AND arg3=1 → ✅ Weapon MUST have PISTOL rule (continue to next check)
                if not _weapon_has_pistol_rule(weapon):
                    can_use = False
                    reason = "No PISTOL rule (cannot shoot non-PISTOL when adjacent)"
        
        # Check weapon.shot flag
        if can_use:
            weapon_shot = weapon.get("shot", 0)
            if weapon_shot == 1:
                # ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Weapon already used (weapon.shot = 1)"
        
        # Check weapon.RNG and target availability
        if can_use:
            weapon_range = weapon.get("RNG", 0)
            if weapon_range <= 0:
                can_use = False
                reason = "Weapon has no range"
            else:
                # Check if at least ONE enemy unit meets ALL conditions
                weapon_has_valid_target = False
                for enemy in game_state["units"]:
                    if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                        # Check range
                        distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
                        if distance > weapon_range:
                            continue
                        
                        # Check Line of Sight
                        temp_unit = dict(unit)
                        temp_unit["RNG_WEAPONS"] = [weapon]
                        temp_unit["selectedRngWeaponIndex"] = 0
                        
                        try:
                            if _is_valid_shooting_target(game_state, temp_unit, enemy):
                                weapon_has_valid_target = True
                                break
                        except (KeyError, IndexError, AttributeError):
                            continue
                
                if not weapon_has_valid_target:
                    can_use = False
                    reason = "No valid targets in range or line of sight"
        
        available_weapons.append({
            "index": idx,
            "weapon": _serialize_weapon_for_json(weapon),
            "can_use": can_use,
            "reason": reason
        })
    
    return available_weapons

def _get_available_weapons_for_selection(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    current_weapon_is_pistol: Optional[bool] = False,
    exclude_used: bool = True,
    has_advanced: bool = False
) -> List[Dict[str, Any]]:
    """
    DEPRECATED: This function is kept for backward compatibility.
    Use weapon_availability_check() instead.
    
    Get list of available weapons for selection, filtered by:
    - Range: weapon must have at least one target in range
    - LoS: weapon must have at least one target with line of sight
    - ASSAULT rule: if unit advanced
    - PISTOL rule: category (PISTOL or non-PISTOL)
    - Used weapons: if exclude_used=True, exclude weapons with weapon.shot = 1
    
    Returns:
        List of dicts with keys: index, weapon, can_use, reason
    """
    available_weapons = []
    rng_weapons = unit.get("RNG_WEAPONS", [])
    
    # Build valid targets for range/LoS checking
    # We'll check each weapon individually
    unit_id = unit["id"]
    
    for idx, weapon in enumerate(rng_weapons):
        can_use = True
        reason = None
        
        # Check weapon.shot flag
        if exclude_used:
            weapon_shot = weapon.get("shot", 0)
            if weapon_shot == 1:
                can_use = False
                reason = "Weapon already used (weapon.shot = 1)"
                available_weapons.append({
                    "index": idx,
                    "weapon": _serialize_weapon_for_json(weapon),
                    "can_use": can_use,
                    "reason": reason
                })
                continue
        
        # Check ASSAULT rule if unit advanced
        if has_advanced:
            if not _weapon_has_assault_rule(weapon):
                can_use = False
                reason = "No ASSAULT rule (cannot shoot after advancing)"
                available_weapons.append({
                    "index": idx,
                    "weapon": _serialize_weapon_for_json(weapon),
                    "can_use": can_use,
                    "reason": reason
                })
                continue
        
        # Check PISTOL rule category
        # Only apply PISTOL filter if unit has already fired (current_weapon_is_pistol is not None)
        # If None, unit hasn't fired yet, so all weapons should be selectable
        weapon_rules = weapon.get("WEAPON_RULES", [])
        is_pistol = "PISTOL" in weapon_rules
        
        if current_weapon_is_pistol is not None:
            if current_weapon_is_pistol:
                # If current weapon is PISTOL, can only select other PISTOL weapons
                if not is_pistol:
                    can_use = False
                    reason = "Cannot mix PISTOL with non-PISTOL weapons"
                    available_weapons.append({
                        "index": idx,
                        "weapon": _serialize_weapon_for_json(weapon),
                        "can_use": can_use,
                        "reason": reason
                    })
                    continue
            else:
                # If current weapon is not PISTOL, exclude PISTOL weapons
                if is_pistol:
                    can_use = False
                    reason = "Cannot mix non-PISTOL with PISTOL weapons"
                    available_weapons.append({
                        "index": idx,
                        "weapon": _serialize_weapon_for_json(weapon),
                        "can_use": can_use,
                        "reason": reason
                    })
                    continue
        
        # Check if weapon has at least one valid target (range + LoS)
        weapon_has_valid_target = False
        weapon_range = weapon.get("RNG", 0)
        
        # Skip if weapon has no range
        if weapon_range <= 0:
            can_use = False
            reason = "Weapon has no range"
            available_weapons.append({
                "index": idx,
                "weapon": _serialize_weapon_for_json(weapon),
                "can_use": can_use,
                "reason": reason
            })
            continue
        
        for enemy in game_state["units"]:
            if (enemy["player"] != unit["player"] and
                enemy["HP_CUR"] > 0):
                
                # Check range
                distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
                if distance > weapon_range:
                    continue
                
                # Check if target is valid (LoS, melee, etc.)
                # Create temporary unit with only this weapon for validation
                # Use dict() constructor to create a proper copy
                temp_unit = dict(unit)
                temp_unit["RNG_WEAPONS"] = [weapon]
                temp_unit["selectedRngWeaponIndex"] = 0
                
                try:
                    if _is_valid_shooting_target(game_state, temp_unit, enemy):
                        weapon_has_valid_target = True
                        break
                except (KeyError, IndexError, AttributeError) as e:
                    # If validation fails, skip this weapon
                    can_use = False
                    reason = f"Validation error: {str(e)}"
                    break
        
        if not weapon_has_valid_target:
            can_use = False
            reason = "No valid targets in range or line of sight"
        
        available_weapons.append({
            "index": idx,
            "weapon": _serialize_weapon_for_json(weapon),
            "can_use": can_use,
            "reason": reason
        })
    
    return available_weapons

def shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Initialize shooting phase and build activation pool
    Initialize weapon_rule and weapon.shot flags
    """
    global _target_pool_cache

    # Set phase
    game_state["phase"] = "shoot"

    # Initialize weapon_rule (weapon rules activated = 1)
    # This is a global variable that determines if weapon rules are applied
    game_state["weapon_rule"] = 1

    # Clear target pool cache at phase start - targets may have moved
    # The cache key only includes shooter position, not target positions
    # So stale cache entries could allow shooting blocked targets
    _target_pool_cache.clear()

    # Initialize weapon.shot = 0 for all weapons in all units
    # Reset weapon.shot flag at phase start
    current_player = game_state["current_player"]
    for unit in game_state["units"]:
        if unit["player"] == current_player and unit["HP_CUR"] > 0:
            rng_weapons = unit.get("RNG_WEAPONS", [])
            for weapon in rng_weapons:
                weapon["shot"] = 0
            
            if rng_weapons:
                selected_idx = unit.get("selectedRngWeaponIndex", 0)
                if selected_idx < 0 or selected_idx >= len(rng_weapons):
                    # Default to first weapon if index invalid (phase start, pas encore de sélection)
                    selected_idx = 0
                weapon = rng_weapons[selected_idx]
                unit["SHOOT_LEFT"] = weapon["NB"]
            else:
                unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged

    _build_shooting_los_cache(game_state)
    
    # Build activation pool
    eligible_units = shooting_build_activation_pool(game_state)
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Pre-compute kill probability cache
    from engine.ai.weapon_selector import precompute_kill_probability_cache
    precompute_kill_probability_cache(game_state, "shoot")
    
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
    Pure function, stores in game_state, no copying.
    
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
    Direct field access, no state copying.
    
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
    Build activation pool with comprehensive debug logging
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

        return best_target
        
    except Exception as e:
        return valid_targets[0]

def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    ADVANCE_IMPLEMENTATION: Updated to support Advance action.
    Unit is eligible for shooting phase if it CAN_SHOOT OR CAN_ADVANCE.
    CAN_ADVANCE = alive AND correct player AND not fled AND not in melee.
    """
    # unit.HP_CUR > 0?
    if unit["HP_CUR"] <= 0:
        return False
        
    # unit.player === current_player?
    if unit["player"] != current_player:
        return False
        
    # units_fled.includes(unit.id)?
    # Direct field access with validation
    if "units_fled" not in game_state:
        raise KeyError("game_state missing required 'units_fled' field")
    if unit["id"] in game_state["units_fled"]:
        return False
    
    # STEP 1: ELIGIBILITY CHECK
    # Check if unit is adjacent to enemy (melee range)
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    
    # Determine CAN_ADVANCE and CAN_SHOOT using weapon_availability_check
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    
    if is_adjacent:
        # Adjacent to enemy
        # CAN_ADVANCE = false (cannot advance when adjacent)
        can_advance = False
        # weapon_availability_check(weapon_rule, 0, 1) → Build weapon_available_pool
        advance_status = 0  # Not advanced yet (eligibility check)
        adjacent_status = 1  # Adjacent to enemy
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # weapon_available_pool NOT empty? → CAN_SHOOT = true, else false
        can_shoot = len(usable_weapons) > 0
        # If CAN_SHOOT = false → ❌ Skip (no valid actions)
        if not can_shoot:
            return False
    else:
        # NOT adjacent to enemy
        # CAN_ADVANCE = true → Store unit.CAN_ADVANCE = true
        can_advance = True
        # weapon_availability_check(weapon_rule, 0, 0) → Build weapon_available_pool
        advance_status = 0  # Not advanced yet (eligibility check)
        adjacent_status = 0  # Not adjacent to enemy
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # weapon_available_pool NOT empty? → CAN_SHOOT = true, else false
        can_shoot = len(usable_weapons) > 0
        # (CAN_SHOOT OR CAN_ADVANCE)? → YES → Continue, NO → ❌ Skip
        if not (can_shoot or can_advance):
            return False
    
    # Store capability flags on unit for later use in action validation
    unit["_can_shoot"] = can_shoot
    unit["_can_advance"] = can_advance
    
    # Unit is eligible if CAN_SHOOT OR CAN_ADVANCE
    return can_shoot or can_advance


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine_save.py working validation with proper LoS
    PERFORMANCE: Uses LoS cache for instant lookups (0.001ms vs 5-10ms)
    """
    # Range check using proper hex distance
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from all ranged weapons
    distance = _calculate_hex_distance(shooter["col"], shooter["row"], target["col"], target["row"])
    from engine.utils.weapon_helpers import get_max_ranged_range
    max_range = get_max_ranged_range(shooter)
    if distance > max_range:
        return False
        
    # Dead target check
    if target["HP_CUR"] <= 0:
        return False
        
    # Friendly fire check
    if target["player"] == shooter["player"]:
        return False
    
    # Adjacent check - can't shoot at adjacent enemies (melee range)
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
    from engine.utils.weapon_helpers import get_melee_range
    melee_range = get_melee_range()
    if distance <= melee_range:
        return False

    # W40K RULE: Cannot shoot at enemy engaged in melee with friendly units
    # Check if target is adjacent to any friendly unit (same player as shooter)
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
    target_cc_range = get_melee_range()  # Always 1

    for friendly in game_state["units"]:
        if friendly["player"] == shooter["player"] and friendly["HP_CUR"] > 0 and friendly["id"] != shooter["id"]:
            friendly_distance = _calculate_hex_distance(target["col"], target["row"], friendly["col"], friendly["row"])
            
            if friendly_distance <= target_cc_range:
                return False

    # PERFORMANCE: Use LoS cache if available (instant lookup)
    # Fallback to calculation if cache missing (edge cases: cache invalidated, tests, or other contexts)
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
    
    return has_los

def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    Start unit activation from shoot_activation_pool
    Clear valid_target_pool, clear TOTAL_ACTION_LOG, SHOOT_LEFT = selected weapon NB
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found", "unitId": unit_id}

    # STEP 2: UNIT_ACTIVABLE_CHECK
    # Clear valid_target_pool, Clear TOTAL_ATTACK log
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    
    # Determine adjacency
    unit_is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    
    # weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0) → Build weapon_available_pool
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    advance_status = 0  # STEP 2: Unit has NOT advanced yet
    adjacent_status = 1 if unit_is_adjacent else 0
    weapon_available_pool = weapon_availability_check(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    
    # valid_target_pool_build(weapon_rule, arg2=0, arg3=unit_is_adjacent ? 1 : 0)
    valid_target_pool = valid_target_pool_build(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    
    # valid_target_pool NOT empty?
    if len(valid_target_pool) == 0:
        # STEP 6: EMPTY_TARGET_HANDLING
        # Mark unit as active BEFORE returning (required for frontend to show advance icon)
        game_state["active_shooting_unit"] = unit_id
        
        # unit.CAN_ADVANCE = true?
        can_advance = unit.get("_can_advance", False)
        if can_advance:
            # YES → Only action available is advance
            # Return signal to allow advance action (handled by frontend/action handler)
            unit["valid_target_pool"] = []
            return {
                "success": True,
                "unitId": unit_id,
                "empty_target_pool": True,
                "can_advance": True,
                "allow_advance": True,  # Signal frontend to use advancePreview mode (no shooting preview)
                "waiting_for_player": True,
                "action": "empty_target_advance_available",
                "available_weapons": []  # Explicitly return empty array to prevent frontend from using stale weapons
            }
        else:
            # NO → unit.CAN_ADVANCE = false → No valid actions available
            # end_activation(WAIT, 1, 0, SHOOTING, 1, 1) → UNIT_ACTIVABLE_CHECK
            unit["valid_target_pool"] = []
            result = _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
            return result
    
    # YES → SHOOTING ACTIONS AVAILABLE → Go to STEP 3: ACTION_SELECTION
    unit["valid_target_pool"] = valid_target_pool
    
    # AI_TURN.md STEP 3: Pre-select first available weapon
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    if usable_weapons:
        first_weapon_idx = usable_weapons[0]["index"]
        unit["selectedRngWeaponIndex"] = first_weapon_idx
        selected_weapon = unit["RNG_WEAPONS"][first_weapon_idx]
        unit["SHOOT_LEFT"] = selected_weapon["NB"]
    else:
        unit["SHOOT_LEFT"] = 0
    
    # PISTOL rule: Store if selected weapon is PISTOL to prevent shooting with other weapons
    if unit["SHOOT_LEFT"] > 0:
        selected_weapon = unit["RNG_WEAPONS"][unit["selectedRngWeaponIndex"]]
        weapon_rules = selected_weapon.get("WEAPON_RULES", [])
        if "PISTOL" in weapon_rules:
            unit["_shooting_with_pistol"] = True
        else:
            unit["_shooting_with_pistol"] = False
    else:
        unit["_shooting_with_pistol"] = False
    
    # weapon.shot flags are initialized at phase start, not here
    unit["selected_target_id"] = None  # For two-click confirmation

    # Capture unit's current location for shooting phase tracking
    unit["activation_position"] = {"col": unit["col"], "row": unit["row"]}

    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id

    # Serialize available weapons for frontend (weapon_available_pool already contains serialized weapons)
    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in weapon_available_pool]

    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"],
            "position": {"col": unit["col"], "row": unit["row"]},
            "available_weapons": available_weapons}


def valid_target_pool_build(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon_rule: int,
    advance_status: int,
    adjacent_status: int
) -> List[str]:
    """
    shoot_refactor.md EXACT: Build list of valid enemy targets
    
    Args:
        game_state: Game state dictionary
        unit: Unit dictionary
        weapon_rule: 0 = no rules, 1 = rules apply
        advance_status: 0 = no advance, 1 = advanced
        adjacent_status: 0 = not adjacent, 1 = adjacent to enemy
    
    Returns:
        List of enemy unit IDs that can be targeted (valid_target_pool)
    """
    current_player = unit["player"]
    
    # Perform weapon_availability_check(arg1, arg2, arg3) → Build weapon_available_pool
    weapon_available_pool = weapon_availability_check(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    
    # Get usable weapons (can_use = True)
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    
    if not usable_weapons:
        return []
    
    # Extract usable weapon indices and ranges
    usable_weapon_indices = [w["index"] for w in usable_weapons]
    rng_weapons = unit.get("RNG_WEAPONS", [])
    
    # For each enemy unit
    valid_target_pool = []
    
    for enemy in game_state["units"]:
        # unit.HP_CUR > 0? → NO → Skip enemy unit
        if enemy["HP_CUR"] <= 0:
            continue
        
        # unit.player != current_player? → NO → Skip enemy unit
        if enemy["player"] == current_player:
            continue
        
        # Unit NOT adjacent to friendly unit (excluding active unit)? → NO → Skip enemy unit
        from engine.utils.weapon_helpers import get_melee_range
        melee_range = get_melee_range()
        enemy_adjacent_to_friendly = False
        for friendly in game_state["units"]:
            if (friendly["player"] == current_player and 
                friendly["HP_CUR"] > 0 and 
                friendly["id"] != unit["id"]):
                friendly_distance = _calculate_hex_distance(
                    enemy["col"], enemy["row"], friendly["col"], friendly["row"]
                )
                if friendly_distance <= melee_range:
                    enemy_adjacent_to_friendly = True
                    break
        
        if enemy_adjacent_to_friendly:
            continue
        
        # Unit in Line of Sight? → NO → Skip enemy unit
        if not _has_line_of_sight(game_state, unit, enemy):
            continue
        
        # Unit within range of AT LEAST 1 weapon from weapon_available_pool? → NO → Skip enemy unit
        unit_within_range = False
        distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
        
        for weapon_idx in usable_weapon_indices:
            if weapon_idx < len(rng_weapons):
                weapon = rng_weapons[weapon_idx]
                weapon_range = weapon.get("RNG", 0)
                if distance <= weapon_range:
                    unit_within_range = True
                    break
        
        # ALL conditions met → ✅ Add unit to valid_target_pool
        if unit_within_range:
            valid_target_pool.append(enemy["id"])
    
    return valid_target_pool


def shooting_build_valid_target_pool(game_state: Dict[str, Any], unit_id: str) -> List[str]:
    """
    Build valid_target_pool and always send blinking data to frontend.
    All enemies within range AND in Line of Sight AND having HP_CUR > 0

    PERFORMANCE: Caches target pool per (unit_id, col, row) to avoid repeated
    distance/LoS calculations during a unit's shooting activation.
    Cache invalidates automatically when unit changes or moves.
    
    NOTE: This function is a wrapper that determines context and calls valid_target_pool_build.
    For direct calls, use valid_target_pool_build() with explicit parameters.
    
    Determines context (arg2, arg3) based on unit state:
    - arg2 = (unit.id in units_advanced) ? 1 : 0
    - arg3 = (unit adjacent to enemy?) ? 1 : 0
    """
    global _target_pool_cache

    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []

    # Determine context for valid_target_pool_build
    # arg2 = (unit.id in units_advanced) ? 1 : 0
    unit_id_str = str(unit_id)
    has_advanced = unit_id_str in game_state.get("units_advanced", set())
    advance_status = 1 if has_advanced else 0
    
    # arg3 = (unit adjacent to enemy?) ? 1 : 0
    # After advance, arg3 is ALWAYS 0 (advance restrictions prevent adjacent destinations)
    if has_advanced:
        adjacent_status = 0  # arg3=0 always after advance
    else:
        adjacent_status = 1 if _is_adjacent_to_enemy_within_cc_range(game_state, unit) else 0

    # Create cache key from unit identity, position, AND context (advance_status, adjacent_status)
    # Cache must include context to avoid wrong results after advance
    cache_key = (unit_id, unit["col"], unit["row"], advance_status, adjacent_status)

    # Check cache
    if cache_key in _target_pool_cache:
        # Cache hit: Fast path - filter dead targets AND re-validate melee status
        # Melee status can change when friendly units die, so we must re-validate
        # Context (advance_status, adjacent_status) is now part of cache key
        cached_pool = _target_pool_cache[cache_key]

        # Filter out units that died AND re-validate targets that might have changed melee status
        alive_targets = []
        for target_id in cached_pool:
            target = _get_unit_by_id(game_state, target_id)
            if target and target["HP_CUR"] > 0:
                # Re-validate target - melee status might have changed (friendly unit died)
                # This is necessary because cache only checks (unit_id, col, row), not surrounding units
                if _is_valid_shooting_target(game_state, unit, target):
                    alive_targets.append(target_id)

        # Update unit's target pool
        unit["valid_target_pool"] = alive_targets

        return alive_targets

    # Cache miss: Build target pool from scratch using valid_target_pool_build
    # Use context already determined above (lines 881-892)
    # Do NOT recalculate - use advance_status and adjacent_status already computed
    # which correctly implement "arg3=0 always after advance" rule
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    
    # Call valid_target_pool_build with context parameters
    # Use advance_status and adjacent_status already calculated above (lines 885, 890-892)
    valid_target_pool = valid_target_pool_build(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )

    # PERFORMANCE: Pre-calculate priorities for all targets ONCE before sorting
    # This reduces from O(n log n) priority calculations to O(n) calculations
    # Priority: tactical efficiency > type match > distance

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from all ranged weapons
    from engine.utils.weapon_helpers import get_max_ranged_range
    max_range = get_max_ranged_range(unit)
    
    # Pre-validate unit stats ONCE (not inside loop)
    if "T" not in unit:
        raise KeyError(f"Unit missing required 'T' field: {unit}")
    if "ARMOR_SAVE" not in unit:
        raise KeyError(f"Unit missing required 'ARMOR_SAVE' field: {unit}")
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing required 'RNG_WEAPONS' field: {unit}")
    if "unitType" not in unit:
        raise KeyError(f"Unit missing required 'unitType' field: {unit}")

    # Cache unit stats for priority calculations
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or first weapon for priority
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    selected_weapon = get_selected_ranged_weapon(unit)
    if not selected_weapon and unit.get("RNG_WEAPONS"):
        selected_weapon = unit["RNG_WEAPONS"][0]  # Fallback to first weapon
    
    unit_t = unit["T"]
    unit_save = unit["ARMOR_SAVE"]
    unit_attacks = selected_weapon["NB"] if selected_weapon else 0
    unit_bs = selected_weapon["ATK"] if selected_weapon else 0
    unit_s = selected_weapon["STR"] if selected_weapon else 0
    unit_ap = selected_weapon["AP"] if selected_weapon else 0
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

        # Direct UPPERCASE field access - no defaults
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
    Line of sight check with proper hex pathfinding.
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
    # Direct field access chain
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
    
    # Player progression logic
    if game_state["current_player"] == 0:
        # AI_TURN.md Line 105: P0 Move → P0 Shoot → P0 Charge → P0 Fight
        # Player stays 0, advance to charge phase
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "charge",
            "current_player": 0,
            # Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
            # Add missing frontend cleanup signals
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
                # Direct field access
                "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
                # Add missing frontend cleanup signals
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
    # Direct field access
    if "selected_target_id" in unit and unit["selected_target_id"]:
        return "target_selected"
    else:
        return "no_target_selected"

def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1) -> Dict[str, Any]:
    """
    shooting_activation_end procedure with exact arguments
    end_activation(result_type, step_count, action_type, phase, remove_from_pool, increment_step)
    arg1 = result_type, arg2 = step_count, arg3 = action_type, arg4 = phase, arg5 = remove_from_pool
    Note: increment_step is handled via arg2 (if arg2=1, increment episode_steps)
    """
    if arg2 == 1:
        if "episode_steps" not in game_state:
            game_state["episode_steps"] = 0
        game_state["episode_steps"] += 1
    
    # Arg3 tracking
    if arg3 == "SHOOTING":
        if "units_shot" not in game_state:
            game_state["units_shot"] = set()
        game_state["units_shot"].add(unit["id"])
    elif arg3 == "ADVANCE":
        # Mark as units_advanced
        if "units_advanced" not in game_state:
            game_state["units_advanced"] = set()
        game_state["units_advanced"].add(unit["id"])
    # arg3 == "PASS" → no tracking update
    
    # Arg4/Arg5 pool removal (arg4 = phase, arg5 = remove_from_pool)
    # remove_from_pool = 0 means NOT_REMOVED, 1 means remove
    remove_from_pool = arg5
    if remove_from_pool == 1:
        # Direct field access
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
    # Only clean up if actually ending activation (arg5=1)
    # If arg5=0 (NOT_REMOVED), we continue activation, so keep state intact
    if remove_from_pool == 1:
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
    # Direct field access
    if "shoot_activation_pool" not in game_state:
        pool_empty = True
    else:
        pool_empty = len(game_state["shoot_activation_pool"]) == 0
    
    # Only return activation_ended response if actually ending (arg5=1)
    # If arg5=0 (NOT_REMOVED), we continue activation, so return None or empty dict
    if remove_from_pool == 0:
        # NOT_REMOVED: This is just a log call, continue activation
        return {}
    
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
    Execute While SHOOT_LEFT > 0 loop automatically
    """
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        # Check if current weapon is PISTOL and find available weapons of same category
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        if selected_weapon:
            weapon_rules = selected_weapon.get("WEAPON_RULES", [])
            current_weapon_is_pistol = "PISTOL" in weapon_rules
            current_weapon_index = unit.get("selectedRngWeaponIndex", 0)
            
            # Find available weapons of the same category (PISTOL or non-PISTOL)
            rng_weapons = unit.get("RNG_WEAPONS", [])
            available_weapons_same_category = []
            for idx, weapon in enumerate(rng_weapons):
                if idx == current_weapon_index:
                    continue  # Skip current weapon
                weapon_rules = weapon.get("WEAPON_RULES", [])
                is_pistol = "PISTOL" in weapon_rules
                if current_weapon_is_pistol and is_pistol:
                    # Current is PISTOL, looking for other PISTOL weapons
                    available_weapons_same_category.append(idx)
                elif not current_weapon_is_pistol and not is_pistol:
                    # Current is non-PISTOL, looking for other non-PISTOL weapons
                    available_weapons_same_category.append(idx)
            
            # Build valid target pool to check if there are targets
            # BUG FIX: Check if ANY available weapon has valid targets
            # Not just the current (exhausted) weapon
            has_valid_targets_for_any_weapon = False
            valid_targets = []
            
            if available_weapons_same_category:
                # Store original weapon index to restore later
                original_weapon_index = unit.get("selectedRngWeaponIndex", 0)
                
                # Check each available weapon for valid targets
                for weapon_idx in available_weapons_same_category:
                    # Temporarily switch to this weapon for target pool calculation
                    unit["selectedRngWeaponIndex"] = weapon_idx
                    temp_valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
                    
                    if temp_valid_targets:
                        has_valid_targets_for_any_weapon = True
                        valid_targets = temp_valid_targets
                        # Restore original weapon index
                        unit["selectedRngWeaponIndex"] = original_weapon_index
                        break
                
                # Restore original weapon index if no targets found
                if not has_valid_targets_for_any_weapon:
                    unit["selectedRngWeaponIndex"] = original_weapon_index
            else:
                # No alternative weapons, use current weapon
                valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
                has_valid_targets_for_any_weapon = len(valid_targets) > 0
            
            if available_weapons_same_category and has_valid_targets_for_any_weapon:
                # There are other weapons of the same category and targets available
                # Allow weapon selection to continue shooting
                # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                if "weapon_rule" not in game_state:
                    raise KeyError("game_state missing required 'weapon_rule' field")
                weapon_rule = game_state["weapon_rule"]
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in game_state.get("units_advanced", set())
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                try:
                    weapon_available_pool = weapon_availability_check(
                        game_state, unit, weapon_rule, advance_status, adjacent_status
                    )
                    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                    # Filter by same category (PISTOL or non-PISTOL) if needed
                    if current_weapon_is_pistol:
                        usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                    else:
                        usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                    
                    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                    # CRITICAL FIX: Store on unit for frontend access (not in game_state global)
                    unit["available_weapons"] = available_weapons
                except Exception as e:
                    # If weapon selection fails, end activation
                    result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                    return True, result
                
                # Check if at least one weapon is usable (can_use: True)
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                if not usable_weapons:
                    # No usable weapons left, end activation
                    result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                    return True, result
                
                return True, {

                    "while_loop_active": True,
                    "validTargets": valid_targets,
                    "shootLeft": 0,
                    "weapon_selection_required": True,
                    "context": "weapon_selection_after_shots_exhausted",
                    "blinking_units": valid_targets,
                    "start_blinking": True,
                    "waiting_for_player": True,
                    "available_weapons": available_weapons
                }
            else:
                # No more weapons of the same category or no targets, end activation
                result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                return True, result
        else:
            # No weapon selected, end activation
            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
            return True, result
    
    # Build valid_target_pool
    # shooting_build_valid_target_pool() now correctly determines context
    # including arg2=1, arg3=0 if unit has advanced
    valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
    
    # valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # Check if a target died and rebuild valid_targets for all available weapons
        # This allows switching to another weapon if current weapon has no targets
        # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
        if "weapon_rule" not in game_state:
            raise KeyError("game_state missing required 'weapon_rule' field")
        weapon_rule = game_state["weapon_rule"]
        unit_id_str = str(unit["id"])
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        advance_status = 1 if has_advanced else 0
        adjacent_status = 1 if is_adjacent else 0
        
        try:
            weapon_available_pool = weapon_availability_check(
                game_state, unit, weapon_rule, advance_status, adjacent_status
            )
            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        except Exception as e:
            # If weapon selection fails, continue with normal flow (no targets)
            usable_weapons = []
        
        # Try to rebuild valid_targets for each usable weapon
        for weapon_info in usable_weapons:
            weapon = weapon_info["weapon"]
            # Create temporary unit with this weapon to check targets
            temp_unit = unit.copy()
            temp_unit["RNG_WEAPONS"] = [weapon]
            temp_unit["selectedRngWeaponIndex"] = 0
            temp_valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            if temp_valid_targets:
                # Found targets for this weapon, switch to it
                unit["selectedRngWeaponIndex"] = weapon_info["index"]
                unit["SHOOT_LEFT"] = weapon["NB"]
                valid_targets = temp_valid_targets
                break
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if SHOOT_LEFT equals selected weapon NB
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        
        # CLEAN FLAG DETECTION: Use config parameter
        unit_check = _get_unit_by_id(game_state, unit_id)
        is_pve_ai = config.get("pve_mode", False) and unit_check and unit_check["player"] == 1
        is_gym_training = config.get("gym_training_mode", False) and unit_check and unit_check["player"] == 1
        
        # For AI/gym: end activation as before
        if is_pve_ai or is_gym_training:
            if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
                # No targets at activation
                result = _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
                return True, result
            else:
                # Shot last target available
                result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                return True, result
        
        # For human players: allow advance mode instead of ending activation
        if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
            # No targets at activation - return signal to allow advance mode
            return True, {
                "waiting_for_player": True,
                "unitId": unit_id,
                "no_targets": True,
                "allow_advance": True,
                "context": "no_targets_advance_available"
            }
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
    # Get available weapons for frontend weapon menu
    has_advanced = unit_id in game_state.get("units_advanced", set())
    
    # Check if current weapon is PISTOL to filter correctly
    # Only apply PISTOL filter if unit has already fired at least once
    # If SHOOT_LEFT == selected_weapon["NB"], unit hasn't fired yet, so don't filter
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    selected_weapon = get_selected_ranged_weapon(unit)
    current_weapon_is_pistol = None  # Default: no filter (unit hasn't fired yet)
    
    if selected_weapon and unit.get("SHOOT_LEFT", 0) < selected_weapon.get("NB", 0):
        # Unit has already fired (SHOOT_LEFT decreased), apply PISTOL filter
        weapon_rules = selected_weapon.get("WEAPON_RULES", [])
        current_weapon_is_pistol = "PISTOL" in weapon_rules
        
    # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    unit_id_str = str(unit["id"])
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    advance_status = 1 if has_advanced else 0
    adjacent_status = 1 if is_adjacent else 0
    
    weapon_available_pool = weapon_availability_check(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    # Filter by category (PISTOL or non-PISTOL) if needed
    if current_weapon_is_pistol is not None:
        if current_weapon_is_pistol:
            usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
        else:
            usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
    
    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
    
    response = {
        "while_loop_active": True,
        "validTargets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True,
        "waiting_for_player": True,
        "available_weapons": available_weapons
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
    # Get action_type early to check if it's select_weapon
    action_type_early = action.get("action") if "action" in action else None
    
    if current_pool:
        # Remove units with no shots remaining
        # Don't remove unit if action is select_weapon (can reactivate with new weapon)
        updated_pool = []
        for pool_unit_id in current_pool:  # Changed: Use separate variable name
            unit_check = _get_unit_by_id(game_state, pool_unit_id)
            if unit_check and "SHOOT_LEFT" in unit_check:
                shots_left = unit_check["SHOOT_LEFT"]
            else:
                shots_left = 0
            # Keep unit in pool if it's the target of select_weapon action (can reactivate)
            if action_type_early == "select_weapon" and str(pool_unit_id) == str(action.get("unitId")):
                updated_pool.append(pool_unit_id)
            elif unit_check and shots_left > 0:
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
    
    # Direct field access
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    unit_id = unit["id"]
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    if unit["player"] != game_state["current_player"]:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions EXCEPT select_weapon
    # select_weapon can reactivate unit after weapon exhaustion
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    if action_type != "select_weapon" and unit_id not in game_state["shoot_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    # AI_SHOOT.md action routing
    if action_type == "activate_unit":
        result = shooting_unit_activation_start(game_state, unit_id)
        if result.get("success"):
            # Check if empty_target_pool with can_advance
            if result.get("empty_target_pool") and result.get("can_advance"):
                # STEP 6: EMPTY_TARGET_HANDLING - advance available
                # Return to allow advance action selection
                return True, result
            elif result.get("empty_target_pool"):
                # STEP 6: Already handled in shooting_unit_activation_start (WAIT)
                return True, result
            # Normal flow: valid targets available
            execution_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            return execution_result
        return True, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with optional targetId
        if "targetId" not in action:
            target_id = None
        else:
            target_id = action["targetId"]
        
        # Validate unit eligibility
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if unit_id not in game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": unit_id}
        
        # Initialize unit for shooting if needed (only if not already activated)
        active_shooting_unit = game_state["active_shooting_unit"] if "active_shooting_unit" in game_state else None
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if SHOOT_LEFT equals selected weapon NB
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        if selected_weapon and (active_shooting_unit != unit_id and unit["SHOOT_LEFT"] == selected_weapon["NB"]):
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
    
    elif action_type == "advance":
        # ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase
        return _handle_advance_action(game_state, unit, action, config)
    
    elif action_type == "select_weapon":
        # WEAPON_SELECTION: Handle weapon selection action
        print(f"🔫 SELECT_WEAPON called: unit_id={unit_id}, weaponIndex={action.get('weaponIndex')}")
        weapon_index = action.get("weaponIndex")
        if weapon_index is None:
            return False, {"error": "missing_weapon_index"}
        
        rng_weapons = unit.get("RNG_WEAPONS", [])
        if weapon_index < 0 or weapon_index >= len(rng_weapons):
            return False, {"error": "invalid_weapon_index", "weaponIndex": weapon_index}

        unit["selectedRngWeaponIndex"] = weapon_index

        # CRITICAL FIX: Invalidate target pool cache after weapon change
        # Cache key doesn't include selectedRngWeaponIndex, so we must clear it
        global _target_pool_cache
        cache_key = (unit_id, unit["col"], unit["row"])
        if cache_key in _target_pool_cache:
            del _target_pool_cache[cache_key]

        # Update SHOOT_LEFT with the new weapon's NB
        weapon = rng_weapons[weapon_index]
        unit["SHOOT_LEFT"] = weapon["NB"]
        
        # Reactivate unit in pool after weapon selection
        # This allows subsequent shooting actions (left_click, shoot) to proceed
        if unit_id not in game_state["shoot_activation_pool"]:
            game_state["shoot_activation_pool"].append(unit_id)
        
        # Store autoSelectWeapon in game_state if provided
        if "autoSelectWeapon" in action:
            if "config" not in game_state:
                game_state["config"] = {}
            if "game_settings" not in game_state["config"]:
                game_state["config"]["game_settings"] = {}
            game_state["config"]["game_settings"]["autoSelectWeapon"] = action["autoSelectWeapon"]

        result = _shooting_unit_execution_loop(game_state, unit_id, config)
        return result

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
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        has_shot = _unit_has_shot_with_any_weapon(unit)
        if has_shot:
            # YES → end_activation(ACTION, 1, SHOOTING, SHOOTING, 1, 1)
            return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
        else:
            # Check if unit has advanced (ADVANCED_SHOOTING_ACTION_SELECTION)
            unit_id_str = str(unit["id"])
            has_advanced = unit_id_str in game_state.get("units_advanced", set())
            if has_advanced:
                # NO → Unit has not shot yet (only advanced) → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1)
                return _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
            else:
                # NO → end_activation(WAIT, 1, 0, SHOOTING, 1, 1)
                return _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
    
    elif action_type == "skip":
        return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1)
    
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
    # Direct field access
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
        # STEP 5A/5B: Postpone/Click elsewhere (Human only)
        # Check if unit has shot with ANY weapon?
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
        has_shot = _unit_has_shot_with_any_weapon(unit)
        if not has_shot:
            # NO → POSTPONE_ACTIVATION() → UNIT_ACTIVABLE_CHECK
            # Unit is NOT removed from shoot_activation_pool (can be re-activated later)
            # Remove weapon selection icon from UI (handled by frontend)
            # Clear active unit
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
            # Return to UNIT_ACTIVABLE_CHECK step (by returning activation_ended=False)
            return True, {
                "action": "postpone",
                "unitId": unit_id,
                "activation_ended": False,
                "reset_mode": "select"
            }
        else:
            # YES → Do not end activation automatically (allow user to click active unit to confirm)
            return True, {"action": "continue_selection", "context": "elsewhere_clicked"}


def shooting_target_selection_handler(game_state: Dict[str, Any], unit_id: str, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle target selection and shooting execution.
    Supports both agent-selected targetId and auto-selection fallback for humans.
    """    
    try:
        unit = _get_unit_by_id(game_state, unit_id)
        
        if not unit:
            return False, {"error": "unit_not_found"}
        
        # ASSAULT RULE VALIDATION: Block shooting if unit advanced without ASSAULT weapon
        unit_id_str = str(unit["id"])
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if not selected_weapon or not _weapon_has_assault_rule(selected_weapon):
                return False, {"error": "cannot_shoot_after_advance_without_assault", "unitId": unit_id_str}
                
        # Validate unit has shots remaining
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        
        # Check if SHOOT_LEFT == 0 and handle weapon selection/switching
        # Store if current weapon is PISTOL to filter weapons correctly below
        current_weapon_is_pistol = False
        if unit["SHOOT_LEFT"] <= 0:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if selected_weapon:
                weapon_rules = selected_weapon.get("WEAPON_RULES", [])
                if "PISTOL" in weapon_rules:
                    # PISTOL rule: can only select another PISTOL weapon
                    current_weapon_is_pistol = True
                # Non-PISTOL weapon: will exclude PISTOL weapons below
            else:
                return False, {"error": "no_weapons_available", "unitId": unit_id}
        
        # Build valid target pool
        valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
        
        if not valid_targets:
            return False, {"error": "no_valid_targets", "unitId": unit_id}
        
        # Handle target selection: agent-provided or auto-select
        if target_id and target_id in valid_targets:
            # Agent provided valid target
            selected_target_id = target_id
            
            # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cette cible ===
            target = _get_unit_by_id(game_state, target_id)
            if not target:
                return False, {"error": "target_not_found", "targetId": target_id}
            
            # Only auto-select weapon if autoSelectWeapon is enabled
            config = game_state.get("config", {})
            auto_select = config.get("game_settings", {}).get("autoSelectWeapon", True)
            
            if auto_select:
                # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                if "weapon_rule" not in game_state:
                    raise KeyError("game_state missing required 'weapon_rule' field")
                weapon_rule = game_state["weapon_rule"]
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in game_state.get("units_advanced", set())
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                try:
                    weapon_available_pool = weapon_availability_check(
                        game_state, unit, weapon_rule, advance_status, adjacent_status
                    )
                    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                    # Filter by same category (PISTOL or non-PISTOL) if needed
                    if current_weapon_is_pistol:
                        usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                    else:
                        usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                    
                    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                except Exception as e:
                    # If weapon selection fails, return error
                    if current_weapon_is_pistol:
                        return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                    else:
                        return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                
                # Filter to only usable weapons
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                
                if not usable_weapons:
                    if current_weapon_is_pistol:
                        return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                    else:
                        return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                
                # Create temporary unit with filtered weapons for selection
                from engine.ai.weapon_selector import select_best_ranged_weapon
                filtered_weapons = [w["weapon"] for w in usable_weapons]
                filtered_indices = [w["index"] for w in usable_weapons]
                temp_unit = unit.copy()
                temp_unit["RNG_WEAPONS"] = filtered_weapons
                best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)
                
                if best_weapon_idx_in_filtered >= 0:
                    # Map back to original weapon index
                    best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                    unit["selectedRngWeaponIndex"] = best_weapon_idx
                    weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                    current_shoot_left = unit.get("SHOOT_LEFT", 0)
                    if current_shoot_left == 0:
                        unit["SHOOT_LEFT"] = weapon["NB"]
                else:
                    unit["SHOOT_LEFT"] = 0
                    return False, {"error": "no_weapons_available", "unitId": unit_id}
            else:
                # Manual mode: Use already selected weapon, just update SHOOT_LEFT if needed
                from engine.utils.weapon_helpers import get_selected_ranged_weapon
                selected_weapon = get_selected_ranged_weapon(unit)
                if selected_weapon:
                    current_shoot_left = unit.get("SHOOT_LEFT", 0)
                    active_shooting_unit = game_state.get("active_shooting_unit")
                    # Only initialize SHOOT_LEFT if it hasn't been initialized yet
                    # If SHOOT_LEFT == 0 after shooting, it means all shots from this weapon have been used
                    # Check if unit has started shooting (has active_shooting_unit set)
                    if current_shoot_left == 0 and active_shooting_unit != unit_id:
                        # Unit hasn't started shooting yet, initialize SHOOT_LEFT
                        unit["SHOOT_LEFT"] = selected_weapon["NB"]
                    elif current_shoot_left == 0 and active_shooting_unit == unit_id:
                        # Unit has already shot and SHOOT_LEFT is 0
                        # Need to select another weapon of the same category (PISTOL or non-PISTOL)
                        # Even in manual mode, auto-select the best weapon of same category to continue
                        weapon_rules = selected_weapon.get("WEAPON_RULES", [])
                        current_weapon_is_pistol = "PISTOL" in weapon_rules
                        
                        # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                        if "weapon_rule" not in game_state:
                            raise KeyError("game_state missing required 'weapon_rule' field")
                        weapon_rule = game_state["weapon_rule"]
                        unit_id_str = str(unit["id"])
                        has_advanced = unit_id_str in game_state.get("units_advanced", set())
                        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                        advance_status = 1 if has_advanced else 0
                        adjacent_status = 1 if is_adjacent else 0
                        
                        try:
                            weapon_available_pool = weapon_availability_check(
                                game_state, unit, weapon_rule, advance_status, adjacent_status
                            )
                            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                            # Filter by same category (PISTOL or non-PISTOL) if needed
                            if current_weapon_is_pistol:
                                usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                            else:
                                usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                            
                            available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                        except Exception as e:
                            # If weapon selection fails, end activation
                            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                            return True, result
                        
                        # Filter to only usable weapons
                        usable_weapons = [w for w in available_weapons if w["can_use"]]
                        
                        if usable_weapons:
                            # Auto-select best weapon of same category to continue shooting
                            from engine.ai.weapon_selector import select_best_ranged_weapon
                            filtered_weapons = [w["weapon"] for w in usable_weapons]
                            filtered_indices = [w["index"] for w in usable_weapons]
                            temp_unit = dict(unit)  # Use dict() for safer copy
                            temp_unit["RNG_WEAPONS"] = filtered_weapons
                            try:
                                best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)
                            except (KeyError, AttributeError, IndexError) as e:
                                # If weapon selection fails, end activation
                                result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                                return True, result
                            
                            if best_weapon_idx_in_filtered >= 0:
                                # Map back to original weapon index
                                best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                                unit["selectedRngWeaponIndex"] = best_weapon_idx
                                weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                                unit["SHOOT_LEFT"] = weapon["NB"]
                                # Continue with shooting
                            else:
                                return False, {"error": "no_weapons_available", "unitId": unit_id}
                        else:
                            # No more weapons of the same category available
                            # End activation since all weapons of this category have been used
                            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                            return True, result
        # === FIN NOUVEAU ===
        elif target_id:
            # Agent provided invalid target
            return False, {"error": "target_not_valid", "targetId": target_id}
        else:
            # No target provided - auto-select first valid target (human player fallback)
            selected_target_id = valid_targets[0]
            
            # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cible auto-sélectionnée ===
            target = _get_unit_by_id(game_state, selected_target_id)
            if target:
                # Only auto-select weapon if autoSelectWeapon is enabled
                config = game_state.get("config", {})
                auto_select = config.get("game_settings", {}).get("autoSelectWeapon", True)
                
                if auto_select:
                    # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                    if "weapon_rule" not in game_state:
                        raise KeyError("game_state missing required 'weapon_rule' field")
                    weapon_rule = game_state["weapon_rule"]
                    unit_id_str = str(unit["id"])
                    has_advanced = unit_id_str in game_state.get("units_advanced", set())
                    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                    advance_status = 1 if has_advanced else 0
                    adjacent_status = 1 if is_adjacent else 0
                    
                    try:
                        weapon_available_pool = weapon_availability_check(
                            game_state, unit, weapon_rule, advance_status, adjacent_status
                        )
                        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                        # Filter by same category (PISTOL or non-PISTOL) if needed
                        if current_weapon_is_pistol:
                            usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                        else:
                            usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                        
                        available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                    except Exception as e:
                        # If weapon selection fails, return error
                        if current_weapon_is_pistol:
                            return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                        else:
                            return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                    
                    # Filter to only usable weapons
                    usable_weapons = [w for w in available_weapons if w["can_use"]]
                    
                    if not usable_weapons:
                        if current_weapon_is_pistol:
                            return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                        else:
                            return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                    
                    # Create temporary unit with filtered weapons for selection
                    from engine.ai.weapon_selector import select_best_ranged_weapon
                    filtered_weapons = [w["weapon"] for w in usable_weapons]
                    filtered_indices = [w["index"] for w in usable_weapons]
                    temp_unit = unit.copy()
                    temp_unit["RNG_WEAPONS"] = filtered_weapons
                    best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)
                    
                    if best_weapon_idx_in_filtered >= 0:
                        # Map back to original weapon index
                        best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                        unit["selectedRngWeaponIndex"] = best_weapon_idx
                        weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                        current_shoot_left = unit.get("SHOOT_LEFT", 0)
                        if current_shoot_left == 0:
                            unit["SHOOT_LEFT"] = weapon["NB"]
                    else:
                        unit["SHOOT_LEFT"] = 0
                        return False, {"error": "no_weapons_available", "unitId": unit_id}
                else:
                    # Manual mode: Use already selected weapon, just update SHOOT_LEFT if needed
                    from engine.utils.weapon_helpers import get_selected_ranged_weapon
                    selected_weapon = get_selected_ranged_weapon(unit)
                    if selected_weapon:
                        current_shoot_left = unit.get("SHOOT_LEFT", 0)
                        # Only initialize SHOOT_LEFT if it hasn't been initialized yet
                        active_shooting_unit = game_state.get("active_shooting_unit")
                        if current_shoot_left == 0 and active_shooting_unit != unit_id:
                            # Unit hasn't started shooting yet, initialize SHOOT_LEFT
                            unit["SHOOT_LEFT"] = selected_weapon["NB"]
                        elif current_shoot_left == 0 and active_shooting_unit == unit_id:
                            # Unit has already shot and SHOOT_LEFT is 0
                            # This case is already handled at the beginning of the function
                            # If we reach here, it means the weapon is not PISTOL, so allow weapon selection
                            # Return error to force manual weapon selection
                            return False, {"error": "weapon_selection_required", "unitId": unit_id, "shootLeft": 0}
            # === FIN NOUVEAU ===
        
        # Determine selected_target_id if not already set (from if/elif blocks above)
        if 'selected_target_id' not in locals():
            if target_id and target_id in valid_targets:
                selected_target_id = target_id
            elif target_id:
                return False, {"error": "target_not_valid", "targetId": target_id}
            else:
                selected_target_id = valid_targets[0]
        
        target = _get_unit_by_id(game_state, selected_target_id)
        if not target:
            return False, {"error": "target_not_found", "targetId": selected_target_id}
        
        # Execute shooting attack
        attack_result = shooting_attack_controller(game_state, unit_id, selected_target_id)

        # Update SHOOT_LEFT and continue loop per AI_TURN.md
        unit["SHOOT_LEFT"] -= 1
        
        # AI_TURN.md ligne 523-536: SHOOT_LEFT == 0 handling
        if unit["SHOOT_LEFT"] == 0:
            # Mark selected_weapon as used (set weapon.shot = 1)
            current_weapon_index = unit.get("selectedRngWeaponIndex", 0)
            rng_weapons = unit.get("RNG_WEAPONS", [])
            if current_weapon_index < len(rng_weapons):
                weapon = rng_weapons[current_weapon_index]
                weapon["shot"] = 1
            
            # weapon_available_pool NOT empty? Check using weapon_availability_check
            if "weapon_rule" not in game_state:
                raise KeyError("game_state missing required 'weapon_rule' field")
            weapon_rule = game_state["weapon_rule"]
            unit_id_str = str(unit["id"])
            has_advanced = unit_id_str in game_state.get("units_advanced", set())
            is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
            advance_status = 1 if has_advanced else 0
            adjacent_status = 1 if is_adjacent else 0
            
            weapon_available_pool = weapon_availability_check(
                game_state, unit, weapon_rule, advance_status, adjacent_status
            )
            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
            
            if usable_weapons:
                # YES → Select next available weapon (AI/Human chooses)
                # For now, auto-select first usable weapon
                next_weapon = usable_weapons[0]
                unit["selectedRngWeaponIndex"] = next_weapon["index"]
                unit["SHOOT_LEFT"] = next_weapon["weapon"].get("NB", 0)
                
                # valid_target_pool_build(weapon_rule, arg2, arg3)
                valid_target_pool = valid_target_pool_build(
                    game_state, unit, weapon_rule, advance_status, adjacent_status
                )
                unit["valid_target_pool"] = valid_target_pool
                
                # Continue to shooting action selection step (ADVANCED if arg2=1, else normal)
                # This is handled by _shooting_unit_execution_loop
                success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
                loop_result["phase"] = "shoot"
                loop_result["target_died"] = attack_result.get("target_died", False)
                loop_result["damage"] = attack_result.get("damage", 0)
                loop_result["target_hp_remaining"] = attack_result.get("target_hp_remaining", 0)
                return success, loop_result
            else:
                # NO → All weapons exhausted → End activation
                result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                return True, result
        else:
            # NO → Continue normally (SHOOT_LEFT > 0)
            # Handle target outcome (died/survived)
            target_died = attack_result.get("target_died", False)
            
            if target_died:
                # Remove from valid_target_pool
                valid_target_pool = unit.get("valid_target_pool", [])
                if selected_target_id in valid_target_pool:
                    valid_target_pool.remove(selected_target_id)
                    unit["valid_target_pool"] = valid_target_pool
                
                # valid_target_pool empty? → YES → End activation (Slaughter handling)
                if not unit.get("valid_target_pool"):
                    result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                    return True, result
                # NO → Continue to shooting action selection step
            # else: Target survives
            
            # Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            valid_targets = unit.get("valid_target_pool", [])
            if not valid_targets and unit["SHOOT_LEFT"] > 0:
                # YES → End activation (Slaughter handling)
                result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                return True, result
            # NO → Continue to shooting action selection step
            
            # Continue to shooting action selection step
            success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            loop_result["phase"] = "shoot"
            loop_result["target_died"] = attack_result.get("target_died", False)
            loop_result["damage"] = attack_result.get("damage", 0)
            loop_result["target_hp_remaining"] = attack_result.get("target_hp_remaining", 0)
            return success, loop_result
    
    except Exception as e:
        import traceback
        raise  # Re-raise to see full error in server logs


def shooting_attack_controller(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    attack_sequence(RNG) implementation with proper logging
    """
    shooter = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not shooter or not target:
        return {"error": "unit_or_target_not_found"}
    
    # FOCUS FIRE: Store target's HP before damage for reward calculation
    target_hp_before_damage = target["HP_CUR"]

    # Execute single attack_sequence(RNG) per AI_TURN.md
    attack_result = _attack_sequence_rng(shooter, target)
    
    # AI_TURN.md ligne 521: Concatenate Return to TOTAL_ACTION log
    if "TOTAL_ATTACK_LOG" not in shooter:
        shooter["TOTAL_ATTACK_LOG"] = ""
    attack_log_message = attack_result.get("attack_log", "")
    if attack_log_message:
        if shooter["TOTAL_ATTACK_LOG"]:
            shooter["TOTAL_ATTACK_LOG"] += " / " + attack_log_message
        else:
            shooter["TOTAL_ATTACK_LOG"] = attack_log_message

    # Apply damage immediately per AI_TURN.md
    if attack_result["damage"] > 0:
        target["HP_CUR"] = max(0, target["HP_CUR"] - attack_result["damage"])
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate kill probability cache for target
        from engine.ai.weapon_selector import invalidate_cache_for_target
        cache = game_state.get("kill_probability_cache", {})
        invalidate_cache_for_target(cache, str(target["id"]))
        
        # Check if target died
        if target["HP_CUR"] <= 0:
            attack_result["target_died"] = True
            # PERFORMANCE: Invalidate LoS cache for dead unit (partial invalidation)
            _invalidate_los_cache_for_unit(game_state, target["id"])
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate cache for dead unit (can't attack anymore)
            from engine.ai.weapon_selector import invalidate_cache_for_unit
            invalidate_cache_for_unit(cache, str(target["id"]))

    # Store pre-damage HP in attack_result for reward calculation
    attack_result["target_hp_before_damage"] = target_hp_before_damage
    
    # Store detailed log for frontend display with location data
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get weapon_name before building message
    weapon_name = attack_result.get("weapon_name", "")
    weapon_suffix = f" with [{weapon_name}]" if weapon_name else ""
    
    # Enhanced message format including shooter position and weapon name per movement phase integration
    attack_log_part = attack_result['attack_log'].split(' : ', 1)[1] if ' : ' in attack_result['attack_log'] else attack_result['attack_log']
    enhanced_message = f"Unit {unit_id} ({shooter['col']}, {shooter['row']}) SHOT Unit {target_id} ({target['col']}, {target['row']}){weapon_suffix} : {attack_log_part}"

    # CRITICAL FIX: Append action_log BEFORE reward calculation
    # This ensures the log exists even if reward calculation fails
    action_reward = 0.0
    action_name = "ranged_attack"
    
    # Create shoot log entry (will be appended after reward calculation)
    shoot_log_entry = {
        "type": "shoot",
        "message": enhanced_message,
        "turn": game_state["turn"],
        "phase": "shoot",
        "shooterId": unit_id,
        "targetId": target_id,
        "weaponName": weapon_name if weapon_name else None,
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
    }
    
    # Append the shoot log entry immediately
    game_state["action_logs"].append(shoot_log_entry)

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

    # Update the shoot log entry with calculated reward and action_name
    logged_reward = round(action_reward, 2)
    shoot_log_entry["reward"] = logged_reward
    shoot_log_entry["action_name"] = action_name
    
    # Add separate death log event if target was killed (AFTER shoot log)
    if attack_result.get("target_died", False):
        game_state["action_logs"].append({
            "type": "death",
            "message": f"Unit {target_id} was destroyed",
            "turn": game_state["turn"],
            "phase": "shoot",
            "targetId": target_id,
            "unitId": target_id,
            "player": target["player"],
            "timestamp": "server_time"
        })
    
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
    attack_sequence(RNG) with proper <OFF> replacement
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    """
    import random
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    
    attacker_id = attacker["id"] 
    target_id = target["id"]
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get selected weapon
    weapon = get_selected_ranged_weapon(attacker)
    if not weapon:
        raise ValueError(f"Attacker {attacker_id} has no selected ranged weapon")
    
    # Hit roll → hit_roll >= weapon.ATK
    hit_roll = random.randint(1, 6)
    hit_target = weapon["ATK"]
    hit_success = hit_roll >= hit_target
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name in attack_log
    weapon_name = weapon.get("display_name", "")
    weapon_prefix = f" with [{weapon_name}]" if weapon_name else ""
    
    if not hit_success:
        # MISS case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) : MISSED !"
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
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # HIT → Continue to wound roll
    wound_roll = random.randint(1, 6)
    wound_target = _calculate_wound_target(weapon["STR"], target["T"])
    wound_success = wound_roll >= wound_target
    
    if not wound_success:
        # FAIL case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) : FAILED !"
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
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # WOUND → Continue to save roll
    save_roll = random.randint(1, 6)
    save_target = _calculate_save_target(target, weapon["AP"])
    save_success = save_roll >= save_target
    
    if save_success:
        # SAVE case
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) : SAVED !"
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
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # FAIL → Continue to damage
    damage_dealt = weapon["DMG"]
    new_hp = max(0, target["HP_CUR"] - damage_dealt)
    
    if new_hp <= 0:
        # Target dies
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} delt : Unit {target_id} DIED !"
    else:
        # Target survives
        attack_log = f"Unit {attacker_id} SHOT Unit {target_id}{weapon_prefix} : Hit {hit_roll}({hit_target}+) - Wound {wound_roll}({wound_target}+) - Save {save_roll}({save_target}+) - {damage_dealt} DAMAGE DELT !"
    
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
        "attack_log": attack_log,
        "weapon_name": weapon_name
    }


def _calculate_save_target(target: Dict[str, Any], ap: int) -> int:
    """Calculate save target with AP modifier and invulnerable save"""
    # Direct UPPERCASE field access
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
        _shooting_activation_end(game_state, current_unit, "WAIT", 1, "PASS", "SHOOTING", 1)
    
    # Start new unit activation
    new_unit = _get_unit_by_id(game_state, new_unit_id)
    if new_unit:
        result = shooting_unit_activation_start(game_state, new_unit_id)
        if result.get("success"):
            return _shooting_unit_execution_loop(game_state, new_unit_id, config)
    
    return False, {"error": "unit_switch_failed"}


# === HELPER FUNCTIONS (Minimal Implementation) ===

def _unit_has_shot_with_any_weapon(unit: Dict[str, Any]) -> bool:
    """
    Check if unit has shot with ANY weapon (any weapon.shot = 1)
    Returns True if at least one weapon has shot flag set to 1
    """
    rng_weapons = unit.get("RNG_WEAPONS", [])
    for weapon in rng_weapons:
        if weapon.get("shot", 0) == 1:
            return True
    return False

def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate adjacency check
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= cc_range:
                return True
    return False


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Cube coordinate range check"""
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from all ranged weapons
    from engine.utils.weapon_helpers import get_max_ranged_range
    max_range = get_max_ranged_range(unit)
    if max_range <= 0:
        return False

    for enemy in game_state["units"]:
        if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
            distance = _calculate_hex_distance(unit["col"], unit["row"], enemy["col"], enemy["row"])
            if distance <= max_range:
                return True  # Simplified - assume clear LoS for now

    return False

def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state.

    Compare both sides as strings to handle int/string ID mismatches.
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
    
    # Direct field access with validation
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
    
    # All required fields must be present
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


# ============================================================================
# ADVANCE_IMPLEMENTATION: Advance action handler
# ============================================================================

def _handle_advance_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase.
    
    Advance allows unit to move 1D6 hexes using movement pathfinding rules.
    After advance: cannot shoot (unless Assault weapon), cannot charge.
    Unit is only marked as "advanced" if it actually moved to a different hex.
    """
    import random
    from engine.phase_handlers.movement_handlers import (
        movement_build_valid_destinations_pool,
        _get_hex_neighbors,
        _is_traversable_hex,
        _is_hex_adjacent_to_enemy,
        _build_enemy_adjacent_hexes
    )
    
    unit_id = unit["id"]
    orig_col, orig_row = unit["col"], unit["row"]
    
    # Use existing advance_range if already rolled (to keep same roll for destination selection)
    # Otherwise roll new 1D6 for advance range (from config)
    if "advance_range" in unit and unit["advance_range"] is not None:
        advance_range = unit["advance_range"]
    else:
        advance_dice_max = config.get("game_rules", {}).get("advance_distance_range", 6)
        advance_range = random.randint(1, advance_dice_max)
        # Store advance range on unit for frontend display
        unit["advance_range"] = advance_range
    
    # Build valid destinations using BFS (same as movement phase)
    # Temporarily override unit MOVE attribute with advance_range
    original_move = unit["MOVE"]
    unit["MOVE"] = advance_range
    
    # Use movement pathfinding to get valid destinations
    valid_destinations = movement_build_valid_destinations_pool(game_state, unit_id)
    
    # Restore original MOVE
    unit["MOVE"] = original_move
    
    # Check if destination provided in action
    dest_col = action.get("destCol")
    dest_row = action.get("destRow")
    
    if dest_col is not None and dest_row is not None:
        # Destination provided - validate and execute
        if (dest_col, dest_row) not in valid_destinations:
            return False, {"error": "invalid_advance_destination", "destination": (dest_col, dest_row)}
        
        # Execute advance movement
        unit["col"] = dest_col
        unit["row"] = dest_row
        
        # Mark as advanced ONLY if actually moved
        actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
        if actually_moved:
            # AI_TURN.md ligne 666: Log: end_activation(ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)
            # This marks units_advanced (ligne 665 describes what this does)
            # arg5=0 means NOT_REMOVED (do not remove from pool, do not end activation)
            # We track the advance but continue to shooting, so we don't use the return value
            _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 0)
        
        # Clean up advance state
        if "advance_range" in unit:
            del unit["advance_range"]
        
        # Log the advance action
        if "action_logs" not in game_state:
            game_state["action_logs"] = []
        game_state["action_logs"].append({
            "type": "advance",
            "message": f"Unit {unit_id} ({orig_col}, {orig_row}) ADVANCED to ({dest_col}, {dest_row}) (Roll: {advance_range})",
            "turn": game_state.get("turn", 1),
            "phase": "shoot",
            "unitId": unit_id,
            "player": unit["player"],
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col,
            "toRow": dest_row,
            "advance_range": advance_range,
            "actually_moved": actually_moved,
            "timestamp": "server_time"
        })
        
        # AI_TURN.md STEP 4: ADVANCE_ACTION post-advance logic (lines 666-679)
        # Continue only if unit actually moved
        if not actually_moved:
            # Unit did not advance → Go back to STEP 3: ACTION_SELECTION
            return True, {
                "waiting_for_player": True,
                "action": "advance_cancelled",
                "unitId": unit_id
            }
        
        # Clear valid_target_pool
        if "valid_target_pool" in unit:
            del unit["valid_target_pool"]
        
        # Update capabilities
        # CAN_ADVANCE = false (unit has advanced, cannot advance again)
        unit["_can_advance"] = False
        
        # weapon_availability_check(weapon_rule, 1, 0) → Build weapon_available_pool (only Assault if weapon_rule=1)
        weapon_rule = game_state.get("weapon_rule", 0)
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status=1, adjacent_status=0
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # CAN_SHOOT = (weapon_available_pool NOT empty)
        can_shoot = len(usable_weapons) > 0
        unit["_can_shoot"] = can_shoot
        
        # Pre-select first available weapon
        if usable_weapons:
            first_weapon = usable_weapons[0]
            unit["selectedRngWeaponIndex"] = first_weapon["index"]
            selected_weapon = first_weapon["weapon"]
            unit["SHOOT_LEFT"] = selected_weapon.get("NB", 0)
        else:
            unit["SHOOT_LEFT"] = 0
        
        # valid_target_pool_build(weapon_rule, arg2=1, arg3=0) → Note: arg3=0 always after advance
        valid_target_pool = valid_target_pool_build(
            game_state, unit, weapon_rule, advance_status=1, adjacent_status=0
        )
        unit["valid_target_pool"] = valid_target_pool
        
        # valid_target_pool NOT empty AND CAN_SHOOT = true?
        if valid_target_pool and can_shoot:
            # YES → SHOOTING ACTIONS AVAILABLE (post-advance) → Go to STEP 5: ADVANCED_SHOOTING_ACTION_SELECTION
            # Mark unit as currently active (required for frontend to show weapon icon)
            game_state["active_shooting_unit"] = unit_id
            # Continue to shooting action selection (post-advance state)
            return _shooting_unit_execution_loop(game_state, unit_id, config)
        else:
            # NO → Unit advanced but no valid targets → end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1)
            # arg3="ADVANCE", arg4="SHOOTING", arg5=1 (remove from pool)
            result = _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
            result.update({
                "action": "advance",
                "unitId": unit_id,
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_range,
                "actually_moved": actually_moved
            })
            return result
    else:
        # No destination - return valid destinations for player/AI to choose
        # For AI, auto-select best destination
        is_gym_training = config.get("gym_training_mode", False)
        is_pve_ai = config.get("pve_mode", False) and unit["player"] == 1
        
        if (is_gym_training or is_pve_ai) and valid_destinations:
            # Auto-select: move toward nearest enemy (aggressive strategy)
            enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
            
            if enemies:
                nearest_enemy = min(enemies, key=lambda e: _calculate_hex_distance(unit["col"], unit["row"], e["col"], e["row"]))
                best_dest = min(valid_destinations, key=lambda d: _calculate_hex_distance(d[0], d[1], nearest_enemy["col"], nearest_enemy["row"]))
            else:
                best_dest = valid_destinations[0] if valid_destinations else (orig_col, orig_row)
            
            # Recursively call with destination
            action["destCol"] = best_dest[0]
            action["destRow"] = best_dest[1]
            return _handle_advance_action(game_state, unit, action, config)
        
        # Human player - return destinations for UI
        # ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Use advance_destinations and advance_roll names
        # to match frontend expectations in useEngineAPI.ts (lines ~330-340)
        return True, {
            "waiting_for_player": True,
            "action": "advance_select_destination",
            "unitId": unit_id,
            "advance_roll": advance_range,
            "advance_destinations": [{"col": d[0], "row": d[1]} for d in valid_destinations],
            "highlight_color": "orange"
        }
