#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_Shooting_Phase.md Basic Implementation
Only pool building functionality - foundation for complete handler autonomy
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from engine.combat_utils import get_unit_coordinates, normalize_coordinates
from .shared_utils import (
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, WAIT, PASS, SHOOTING, ADVANCE, NOT_REMOVED,
)

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
        weapon_name = weapon.get("display_name", f"weapon_{idx}")
        
        # Check arg1 (weapon_rule)
        # arg1 = 0 -> No weapon rules checked/applied (continue to next check)
        # arg1 = 1 -> Weapon rules apply (continue to next check)
        
        # Check arg2 (advance_status)
        if advance_status == 1:
            # Unit DID advance
            if weapon_rule == 0:
                # arg1=0 AND arg2=1 -> ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot after advance (weapon_rule=0)"
            else:
                # arg1=1 AND arg2=1 -> ✅ Weapon MUST have ASSAULT rule (continue to next check)
                if not _weapon_has_assault_rule(weapon):
                    can_use = False
                    reason = "No ASSAULT rule (cannot shoot after advancing)"
        
        # Check arg3 (adjacent_status)
        if can_use and adjacent_status == 1:
            # Unit IS adjacent to enemy
            if weapon_rule == 0:
                # arg1=0 AND arg3=1 -> ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot when adjacent (weapon_rule=0)"
            else:
                # arg1=1 AND arg3=1 -> ✅ Weapon MUST have PISTOL rule (continue to next check)
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
        
        # Check PISTOL category mixing restriction
        # If unit has already fired with a weapon, can only use weapons of the same category
        if can_use and "_shooting_with_pistol" in unit and unit["_shooting_with_pistol"] is not None:
            weapon_is_pistol = _weapon_has_pistol_rule(weapon)
            
            if unit["_shooting_with_pistol"]:
                # Unit fired with PISTOL weapon, can only select other PISTOL weapons
                if not weapon_is_pistol:
                    can_use = False
                    reason = "Cannot mix PISTOL with non-PISTOL weapons"
            else:
                # Unit fired with non-PISTOL weapon, cannot select PISTOL weapons
                if weapon_is_pistol:
                    can_use = False
                    reason = "Cannot mix non-PISTOL with PISTOL weapons"
        
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
                    # CRITICAL: Normalize player values to int for consistent comparison
                    enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
                    unit_player = int(unit["player"]) if unit["player"] is not None else None
                    if enemy_player != unit_player and enemy["HP_CUR"] > 0:
                        # Check range
                        unit_col, unit_row = get_unit_coordinates(unit)
                        enemy_col, enemy_row = get_unit_coordinates(enemy)
                        distance = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
                        if distance > weapon_range:
                            continue
                        
                        # Check Line of Sight
                        temp_unit = dict(unit)
                        temp_unit["RNG_WEAPONS"] = [weapon]
                        temp_unit["selectedRngWeaponIndex"] = 0
                        
                        try:
                            is_valid = _is_valid_shooting_target(game_state, temp_unit, enemy)
                            if is_valid:
                                weapon_has_valid_target = True
                                break
                        except (KeyError, IndexError, AttributeError) as e:
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
    current_weapon_is_pistol: Optional[bool] = None,
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
            # CRITICAL: Normalize player values to int for consistent comparison
            enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
            unit_player = int(unit["player"]) if unit["player"] is not None else None
            if (enemy_player != unit_player and
                enemy["HP_CUR"] > 0):
                
                # Check range
                unit_col, unit_row = get_unit_coordinates(unit)
                enemy_col, enemy_row = get_unit_coordinates(enemy)
                distance = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
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
                # Initialize weapon selection using weapon_availability_check to ensure valid weapon
                # This ensures PISTOL weapons are selected when unit is adjacent to enemy
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in game_state.get("units_advanced", set())
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                weapon_rule = game_state.get("weapon_rule", 1)
                weapon_available_pool = weapon_availability_check(
                    game_state, unit, weapon_rule, advance_status, adjacent_status
                )
                usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                
                if usable_weapons:
                    # If adjacent, prioritize PISTOL weapons
                    if is_adjacent:
                        pistol_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w.get("weapon", {}))]
                        if pistol_weapons:
                            first_weapon = pistol_weapons[0]
                        else:
                            first_weapon = usable_weapons[0]
                    else:
                        first_weapon = usable_weapons[0]
                    
                    selected_idx = first_weapon["index"]
                    unit["selectedRngWeaponIndex"] = selected_idx
                    weapon = rng_weapons[selected_idx]
                    unit["SHOOT_LEFT"] = weapon["NB"]
                else:
                    # No usable weapons, default to first weapon (will be validated later)
                    selected_idx = unit.get("selectedRngWeaponIndex", 0)
                    if selected_idx < 0 or selected_idx >= len(rng_weapons):
                        selected_idx = 0
                    weapon = rng_weapons[selected_idx]
                    unit["SHOOT_LEFT"] = weapon["NB"]
            else:
                unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged

    # PERFORMANCE: Pre-compute enemy_adjacent_hexes once at phase start for current player
    # Cache will be reused throughout the phase for all units
    from .shared_utils import build_enemy_adjacent_hexes
    build_enemy_adjacent_hexes(game_state, current_player)
    
    # AI_TURN.md STEP 0: Build position_cache at phase start
    build_position_cache(game_state)
    
    # DEPRECATED: _build_shooting_los_cache() kept for backward compatibility
    # New code should use build_unit_los_cache() per unit (unit-local cache)
    _build_shooting_los_cache(game_state)
    
    # Build activation pool
    eligible_units = shooting_build_activation_pool(game_state)
    
    # Invariant: when in shoot with non-empty pool, active_shooting_unit = pool[0]
    # Required for convert_gym_action, get_action_mask, and any reader (e.g. debug log).
    if eligible_units:
        game_state["active_shooting_unit"] = eligible_units[0]
    else:
        if "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
    
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


def build_position_cache(game_state: Dict[str, Any]) -> None:
    """
    AI_TURN.md: Build snapshot of enemy positions at shooting phase start.
    Creates position_cache with enemy unit positions for efficient LoS calculations.
    
    Returns: void (updates game_state["position_cache"])
    """
    current_player = game_state.get("current_player")
    position_cache = {}
    
    for unit in game_state["units"]:
        # ELIGIBILITY CHECK: Skip dead units
        if unit["HP_CUR"] <= 0:
            continue
        
        # ELIGIBILITY CHECK: Skip friendly units
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        current_player_int = int(current_player) if current_player is not None else None
        if unit_player == current_player_int:
            continue
        
        # Add to position_cache
        unit_id = str(unit["id"])
        unit_col, unit_row = get_unit_coordinates(unit)
        position_cache[unit_id] = {
            "id": unit_id,
            "col": unit_col,
            "row": unit_row
        }
    
    game_state["position_cache"] = position_cache


def build_unit_los_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    AI_TURN.md: Calculate LoS cache for a specific unit.
    Uses position_cache and has_line_of_sight_coords() for performance.
    
    Returns: void (updates unit["los_cache"])
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return
    
    # Initialize cache
    unit["los_cache"] = {}
    
    # Get unit coordinates
    unit_col, unit_row = get_unit_coordinates(unit)
    
    # Get position_cache (must exist, built at phase start)
    if "position_cache" not in game_state:
        raise KeyError("position_cache must be built at phase start (call build_position_cache())")
    
    position_cache = game_state["position_cache"]
    
    # If position_cache is empty, los_cache remains empty (no enemies)
    if not position_cache:
        return
    
    # Import has_line_of_sight_coords for performance
    from engine.combat_utils import has_line_of_sight_coords
    
    # Calculate LoS for each target in position_cache
    for target_id, target_data in position_cache.items():
        target_col = target_data["col"]
        target_row = target_data["row"]
        
        # PERFORMANCE: Use has_line_of_sight_coords() instead of _get_unit_by_id() + _has_line_of_sight()
        # Uses hex_los_cache internally for additional performance
        has_los = has_line_of_sight_coords(unit_col, unit_row, target_col, target_row, game_state)
        
        # Store in unit's los_cache
        unit["los_cache"][target_id] = has_los


def _build_shooting_los_cache(game_state: Dict[str, Any]) -> None:
    """
    DEPRECATED: This function is kept for backward compatibility but should not be used.
    Use build_unit_los_cache() instead for unit-local cache (AI_TURN.md compliance).
    
    Build LoS cache for all unit pairs at shooting phase start.
    Pure function, stores in game_state, no copying.
    
    Performance: O(n²) calculation once per phase vs O(n²×m) per activation.
    Called once per shooting phase, massive speedup during unit activations.
    
    NOTE: Cache is invalidated when units move or die to prevent stale results.
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
            # CRITICAL: Always recalculate, don't rely on potentially stale cache
            # CRITICAL: Normalize IDs to string for consistent cache key comparison
            cache_key = (str(shooter["id"]), str(target["id"]))
            los_cache[cache_key] = _has_line_of_sight(game_state, shooter, target)
    
    # Store cache in game_state (single source of truth)
    game_state["los_cache"] = los_cache
    
    # Debug log cache size (optional, remove in production)
    # print(f"LoS CACHE: Built {len(los_cache)} entries for {len(alive_units)} units")

def update_los_cache_after_target_death(game_state: Dict[str, Any], dead_target_id: str) -> None:
    """
    AI_TURN.md: Update LoS cache after target death.
    Removes dead target from position_cache and active unit's los_cache.
    
    Returns: void (updates position_cache and unit["los_cache"])
    """
    # Remove from position_cache
    if "position_cache" in game_state:
        dead_target_id_str = str(dead_target_id)
        if dead_target_id_str in game_state["position_cache"]:
            del game_state["position_cache"][dead_target_id_str]
    
    # Update active unit's los_cache (only active unit has los_cache)
    active_unit_id = game_state.get("active_shooting_unit")
    if active_unit_id:
        active_unit = _get_unit_by_id(game_state, active_unit_id)
        if active_unit and "los_cache" in active_unit:
            dead_target_id_str = str(dead_target_id)
            if dead_target_id_str in active_unit["los_cache"]:
                del active_unit["los_cache"][dead_target_id_str]


def _invalidate_los_cache_for_unit(game_state: Dict[str, Any], dead_unit_id: str) -> None:
    """
    Partially invalidate LoS cache when unit dies.
    Direct field access, no state copying.
    
    Only removes entries involving dead unit (performance optimization).
    """
    if "los_cache" not in game_state:
        return
    
    # Remove all cache entries involving dead unit
    # CRITICAL: Normalize dead_unit_id to string for consistent comparison
    dead_unit_id_str = str(dead_unit_id)
    keys_to_remove = [
        key for key in game_state["los_cache"].keys()
        if str(key[0]) == dead_unit_id_str or str(key[1]) == dead_unit_id_str
    ]
    
    for key in keys_to_remove:
        del game_state["los_cache"][key]


def _remove_dead_unit_from_pools(game_state: Dict[str, Any], dead_unit_id: str) -> None:
    """
    Remove dead unit from all activation pools.
    Called when a unit dies to ensure it cannot act in any phase.
    PRINCIPLE: "Le Pool DOIT gérer les morts" - This function ensures dead units are removed immediately.
    """
    unit_id_str = str(dead_unit_id)
    
    # DEBUG: Log dead unit removal
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    unit = _get_unit_by_id(game_state, dead_unit_id)
    hp_cur = unit.get("HP_CUR", -1) if unit else -1
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: Removing dead Unit {unit_id_str} (HP_CUR={hp_cur})")
    
    # Remove from shooting activation pool
    if "shoot_activation_pool" in game_state:
        pool_before = len(game_state["shoot_activation_pool"])
        was_in_pool = unit_id_str in [str(uid) for uid in game_state["shoot_activation_pool"]]
        # Normalize pool to contain only strings (consistent with pool construction at line 641)
        game_state["shoot_activation_pool"] = [str(uid) for uid in game_state["shoot_activation_pool"] if str(uid) != unit_id_str]
        pool_after = len(game_state["shoot_activation_pool"])
        add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: shoot_activation_pool before={pool_before} after={pool_after} was_in_pool={was_in_pool}")
        # Verify removal worked (defense in depth)
        if pool_before == pool_after and unit_id_str in [str(uid) for uid in game_state["shoot_activation_pool"]]:
            # Unit was not removed - this is a bug, force removal
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: BUG - Unit {unit_id_str} still in pool after removal, forcing removal")
            # Normalize pool to contain only strings (consistent with pool construction at line 641)
            game_state["shoot_activation_pool"] = [str(uid) for uid in game_state["shoot_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from movement activation pool
    if "move_activation_pool" in game_state:
        game_state["move_activation_pool"] = [uid for uid in game_state["move_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from charge activation pool
    if "charge_activation_pool" in game_state:
        game_state["charge_activation_pool"] = [uid for uid in game_state["charge_activation_pool"] if str(uid) != unit_id_str]


def _rebuild_los_cache_for_unit(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Rebuild LoS cache for a specific unit after it moves (e.g., after advance).
    Recalculates LoS from this unit to all other alive units.
    
    CRITICAL: Called after unit moves to ensure cache is up-to-date with new position.
    This prevents "shoot through wall" bugs caused by stale cache.
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return
    
    # Initialize cache if it doesn't exist
    if "los_cache" not in game_state:
        game_state["los_cache"] = {}
    
    # Get all alive units (both players)
    alive_units = [u for u in game_state["units"] if u["HP_CUR"] > 0]
    
    # Recalculate LoS from this unit to all other units
    for target in alive_units:
        if target["id"] == unit_id:
            continue  # Skip self
        
        # Calculate LoS using current positions
        # CRITICAL: Normalize IDs to string for consistent cache key comparison
        cache_key = (str(unit_id), str(target["id"]))
        has_los = _has_line_of_sight(game_state, unit, target)
        game_state["los_cache"][cache_key] = has_los
        
        # Also update reverse direction (target -> unit)
        # CRITICAL: Normalize IDs to string for consistent cache key comparison
        reverse_key = (str(target["id"]), str(unit_id))
        game_state["los_cache"][reverse_key] = has_los


def _invalidate_los_cache_for_moved_unit(game_state: Dict[str, Any], moved_unit_id: str) -> None:
    """
    Invalidate LoS cache when unit moves.
    Direct field access, no state copying.
    
    When a unit moves, its position changes, so all LoS calculations involving
    that unit are now invalid. Remove all cache entries involving the moved unit.
    
    CRITICAL: This prevents "shoot through wall" bugs caused by stale cache
    when units move between positions.
    
    Invalidates BOTH caches:
    - los_cache: key = (shooter_id, target_id) - invalidate entries with moved_unit_id
    - hex_los_cache: key = ((from_col, from_row), (to_col, to_row)) - clear all entries
      (easier to clear all than to track which hexes involved the moved unit)
    """
    # Invalidate los_cache (unit ID-based cache)
    # CRITICAL: Normalize moved_unit_id to string for consistent comparison
    if "los_cache" in game_state:
        moved_unit_id_str = str(moved_unit_id)
        keys_to_remove = [
            key for key in game_state["los_cache"].keys()
            if str(key[0]) == moved_unit_id_str or str(key[1]) == moved_unit_id_str
        ]
        for key in keys_to_remove:
            del game_state["los_cache"][key]
    
    # CRITICAL: Also invalidate hex_los_cache (coordinate-based cache)
    # When a unit moves, any LoS calculation involving that unit's old or new position is invalid
    # It's simpler to clear the entire hex_los_cache than to track which entries involve the moved unit
    if "hex_los_cache" in game_state:
        game_state["hex_los_cache"] = {}


def shooting_build_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    Build activation pool with comprehensive debug logging
    """
    current_player = game_state["current_player"]
    shoot_activation_pool = []
    
    # DEBUG: Log pool building for dead unit detection
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: Building pool for player {current_player}")
    
    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["shoot_activation_pool"] = []
    
    for unit in game_state["units"]:
        unit_id = unit.get("id", "?")
        hp_cur = unit.get("HP_CUR", -1)
        unit_player = unit.get("player", -1)
        
        # CRITICAL: Only process units of current player
        if unit_player != current_player:
            continue  # Skip units of other players
        
        # PRINCIPLE: "Le Pool DOIT gérer les morts" - Only add alive units of current player
        # CRITICAL: Normalize unit ID to string when adding to pool to ensure consistent types
        if unit.get("HP_CUR", 0) > 0 and _has_valid_shooting_targets(game_state, unit, current_player):
            shoot_activation_pool.append(str(unit["id"]))
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: ADDED Unit {unit_id} (player={unit_player}, HP_CUR={hp_cur})")
        else:
            # Log why unit was NOT added (for debugging dead units in pool)
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: SKIPPED Unit {unit_id} (player={unit_player}, HP_CUR={hp_cur}, has_targets={_has_valid_shooting_targets(game_state, unit, current_player)})")
    
    # Update game_state pool
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - Pool is built correctly (only alive units of current player via _has_valid_shooting_targets)
    game_state["shoot_activation_pool"] = shoot_activation_pool
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: Pool built with {len(shoot_activation_pool)} units: {shoot_activation_pool}")
    
    return game_state["shoot_activation_pool"]

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
    # PISTOL rule: Initialize _shooting_with_pistol to None for eligibility check
    # This ensures each unit starts with no PISTOL category restriction
    unit["_shooting_with_pistol"] = None
    
    # unit.HP_CUR > 0?
    if unit["HP_CUR"] <= 0:
        return False
        
    # unit.player === current_player?
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    current_player_int = int(current_player) if current_player is not None else None
    if unit_player != current_player_int:
        return False
        
    # units_fled.includes(unit.id)?
    # Direct field access with validation
    # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
    if "units_fled" not in game_state:
        raise KeyError("game_state missing required 'units_fled' field")
    if str(unit["id"]) in game_state["units_fled"]:
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
        # weapon_availability_check(weapon_rule, 0, 1) -> Build weapon_available_pool
        advance_status = 0  # Not advanced yet (eligibility check)
        adjacent_status = 1  # Adjacent to enemy
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # weapon_available_pool NOT empty? -> CAN_SHOOT = true, else false
        can_shoot = len(usable_weapons) > 0
        # If CAN_SHOOT = false -> ❌ Skip (no valid actions)
        if not can_shoot:
            return False
    else:
        # NOT adjacent to enemy
        # CAN_ADVANCE = true -> Store unit.CAN_ADVANCE = true
        can_advance = True
        # weapon_availability_check(weapon_rule, 0, 0) -> Build weapon_available_pool
        advance_status = 0  # Not advanced yet (eligibility check)
        adjacent_status = 0  # Not adjacent to enemy
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # weapon_available_pool NOT empty? -> CAN_SHOOT = true, else false
        can_shoot = len(usable_weapons) > 0
        # (CAN_SHOOT OR CAN_ADVANCE)? -> YES -> Continue, NO -> ❌ Skip
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
    shooter_col, shooter_row = get_unit_coordinates(shooter)
    target_col, target_row = get_unit_coordinates(target)
    distance = _calculate_hex_distance(shooter_col, shooter_row, target_col, target_row)
    from engine.utils.weapon_helpers import get_max_ranged_range
    max_range = get_max_ranged_range(shooter)
    if distance > max_range:
        return False
        
    # Dead target check
    if target["HP_CUR"] <= 0:
        return False
        
    # Friendly fire check
    # CRITICAL: Normalize player values to int for consistent comparison
    target_player = int(target["player"]) if target["player"] is not None else None
    shooter_player = int(shooter["player"]) if shooter["player"] is not None else None
    if target_player == shooter_player:
        return False
    
    # CRITICAL: Check if enemy is adjacent to shooter (melee range)
    # EXCEPTION: PISTOL weapons can shoot at adjacent enemies
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
    from engine.utils.weapon_helpers import get_melee_range, get_selected_ranged_weapon
    melee_range = get_melee_range()
    enemy_adjacent_to_shooter = (distance <= melee_range)
    has_pistol_weapon = False
    
    if enemy_adjacent_to_shooter:
        # Enemy is adjacent to shooter - check if selected weapon has PISTOL rule
        selected_weapon = get_selected_ranged_weapon(shooter)
        if selected_weapon and _weapon_has_pistol_rule(selected_weapon):
            has_pistol_weapon = True
        else:
            # Non-PISTOL weapons cannot shoot at adjacent enemies
            return False
    
    # W40K RULE: Cannot shoot at enemy engaged in melee with friendly units
    # CRITICAL: This rule applies ONLY when enemy is NOT adjacent to shooter
    # If enemy is adjacent to shooter AND we have PISTOL weapon, we can shoot regardless of engagement
    # If enemy is NOT adjacent to shooter, normal rules apply: cannot shoot if enemy is engaged with friendly units
    if not enemy_adjacent_to_shooter:
        # Enemy is NOT adjacent to shooter - apply normal engaged enemy rule
        for friendly in game_state["units"]:
            # CRITICAL: Normalize player values to int for consistent comparison
            friendly_player = int(friendly["player"]) if friendly["player"] is not None else None
            shooter_player_int = int(shooter["player"]) if shooter["player"] is not None else None
            if friendly_player == shooter_player_int and friendly["HP_CUR"] > 0 and friendly["id"] != shooter["id"]:
                target_col, target_row = get_unit_coordinates(target)
                friendly_col, friendly_row = get_unit_coordinates(friendly)
                friendly_distance = _calculate_hex_distance(target_col, target_row, friendly_col, friendly_row)
                
                if friendly_distance <= melee_range:
                    # Enemy is engaged with friendly unit - cannot shoot
                    return False

    # PERFORMANCE: Use LoS cache if available (instant lookup)
    # Fallback to calculation if cache missing (edge cases: cache invalidated, tests, or other contexts)
    has_los = False
    if "los_cache" in game_state and game_state["los_cache"]:
        # CRITICAL: Normalize IDs to string for consistent cache key comparison
        cache_key = (str(shooter["id"]), str(target["id"]))
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

    # CRITICAL FIX (Episodes 49, 57, 94, 95, 99): Verify unit is in pool before activation
    # A unit that was removed from pool (e.g., after WAIT) should NEVER be reactivated
    # This prevents infinite WAIT loops where get_action_mask reactivates a unit that was removed
    # CRITICAL: Normalize all IDs to string for consistent comparison (pool stores strings)
    shoot_pool = game_state.get("shoot_activation_pool", [])
    unit_id_str = str(unit_id)
    pool_ids = [str(uid) for uid in shoot_pool]
    if unit_id_str not in pool_ids:
        # Unit not in pool - cannot activate
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        from engine.game_utils import add_debug_log
        add_debug_log(game_state, f"[ACTIVATION_START ERROR] E{episode} T{turn} shooting_unit_activation_start: Unit {unit_id_str} NOT in pool, cannot activate. Pool={shoot_pool}")
        return {"error": "unit_not_in_pool", "unitId": unit_id, "message": "Unit was removed from pool and cannot be reactivated"}

    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)

    # STEP 2: UNIT_ACTIVABLE_CHECK
    # Clear valid_target_pool, Clear TOTAL_ATTACK log
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    
    # CRITICAL: Clear shoot_attack_results at the start of each new unit activation
    # This ensures attacks from different units are not mixed together
    game_state["shoot_attack_results"] = []
    
    # AI_TURN.md STEP 2: Build unit's los_cache at activation
    # CRITICAL: Only build los_cache if unit has not fled (units that fled cannot shoot)
    unit_id_str = str(unit_id)
    if unit_id_str not in game_state.get("units_fled", set()):
        build_unit_los_cache(game_state, unit_id)
    else:
        # Unit has fled - cannot shoot, so no los_cache needed
        # Unit can still advance if not adjacent to enemy
        unit["los_cache"] = {}
    
    # Determine adjacency
    unit_is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    
    # PISTOL rule: Remove _shooting_with_pistol if it exists (unit hasn't fired yet in this activation)
    # This must be done BEFORE weapon_availability_check to avoid incorrect filtering
    if "_shooting_with_pistol" in unit:
        del unit["_shooting_with_pistol"]
    
    # Reset weapon.shot flags for this unit at activation start
    # Each unit should be able to use all its weapons at the start of its activation
    rng_weapons = unit.get("RNG_WEAPONS", [])
    for weapon in rng_weapons:
        weapon["shot"] = 0
    
    # weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0) -> Build weapon_available_pool
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    advance_status = 0  # STEP 2: Unit has NOT advanced yet
    adjacent_status = 1 if unit_is_adjacent else 0
    weapon_available_pool = weapon_availability_check(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    
    # CRITICAL: Use shooting_build_valid_target_pool for consistent pool building
    # This wrapper automatically determines context (advance_status, adjacent_status) and handles cache
    valid_target_pool = shooting_build_valid_target_pool(game_state, unit_id)
    
    # valid_target_pool NOT empty?
    if len(valid_target_pool) == 0:
        # STEP 6: EMPTY_TARGET_HANDLING
        # Mark unit as active BEFORE returning (required for frontend to show advance icon)
        game_state["active_shooting_unit"] = unit_id
        
        # unit.CAN_ADVANCE = true?
        can_advance = unit.get("_can_advance", False)
        if can_advance:
            # YES -> Only action available is advance
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
            # NO -> unit.CAN_ADVANCE = false -> No valid actions (SKIP: cannot act)
            _success, result = _handle_shooting_end_activation(
                game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
            )
            return result
    
    # YES -> SHOOTING ACTIONS AVAILABLE -> Go to STEP 3: ACTION_SELECTION
    unit["valid_target_pool"] = valid_target_pool
    
    # AI_TURN.md STEP 3: Pre-select first available weapon
    # If unit is adjacent to enemy, prioritize PISTOL weapons
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    if usable_weapons:
        if unit_is_adjacent:
            # Prioritize PISTOL weapons when adjacent to enemy
            pistol_weapons = []
            non_pistol_weapons = []
            for w in usable_weapons:
                weapon = w.get("weapon", {})
                if _weapon_has_pistol_rule(weapon):
                    pistol_weapons.append(w)
                else:
                    non_pistol_weapons.append(w)
            
            # Prefer PISTOL weapons, but fall back to non-PISTOL if no PISTOL available
            if pistol_weapons:
                first_weapon = pistol_weapons[0]
            else:
                first_weapon = usable_weapons[0]
        else:
            # Not adjacent, use first available weapon
            first_weapon = usable_weapons[0]
        
        first_weapon_idx = first_weapon["index"]
        unit["selectedRngWeaponIndex"] = first_weapon_idx
        selected_weapon = unit["RNG_WEAPONS"][first_weapon_idx]
        unit["SHOOT_LEFT"] = selected_weapon["NB"]
    else:
        unit["SHOOT_LEFT"] = 0
    
    unit["selected_target_id"] = None  # For two-click confirmation

    # Capture unit's current location for shooting phase tracking
    unit_col, unit_row = get_unit_coordinates(unit)
    unit["activation_position"] = {"col": unit_col, "row": unit_row}

    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id

    # Serialize available weapons for frontend (weapon_available_pool already contains serialized weapons)
    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in weapon_available_pool]

    unit_col, unit_row = get_unit_coordinates(unit)
    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"],
            "position": {"col": unit_col, "row": unit_row},
            "selectedRngWeaponIndex": unit.get("selectedRngWeaponIndex", 0),
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
    
    # Perform weapon_availability_check(arg1, arg2, arg3) -> Build weapon_available_pool
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
    
    # CRITICAL: Normalize unit ID once at the start for consistent comparison
    # This prevents bugs where unit["id"] might be int or string, and enemy["id"] might be different type
    unit_id_normalized = str(unit["id"])
    current_player_int = int(current_player) if current_player is not None else None
    
    # DEBUG: Log pool building start
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Unit {unit_id_normalized}({unit['col']},{unit['row']}) building pool (advance_status={advance_status}, adjacent_status={adjacent_status})")
    
    # AI_TURN.md: ASSERT unit["los_cache"] exists (must be created by build_unit_los_cache at activation)
    if "los_cache" not in unit:
        # Check if unit has fled (units that fled don't have los_cache but can advance)
        unit_id_str = str(unit["id"])
        if unit_id_str not in game_state.get("units_fled", set()):
            raise KeyError(f"Unit {unit_id_normalized} missing required 'los_cache' field. Must call build_unit_los_cache() at activation.")
        else:
            # Unit has fled - cannot shoot, return empty pool
            return []
    
    # AI_TURN.md: Filter los_cache to get only targets with LoS (optimization)
    # Filter los_cache: targets_with_los = {target_id: true for target_id, has_los in unit["los_cache"].items() if has_los == true}
    targets_with_los = {
        target_id: True 
        for target_id, has_los in unit["los_cache"].items() 
        if has_los == True
    }
    
    add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Found {len(targets_with_los)} targets with LoS out of {len(unit['los_cache'])} total targets")
    
    # For each target_id in targets_with_los.keys():
    for target_id_str in targets_with_los.keys():
        # Get enemy unit by ID
        enemy = _get_unit_by_id(game_state, target_id_str)
        if not enemy:
            # Target not found (may have died) - skip
            continue
        # DEBUG: Log all enemies being checked
        enemy_id_check = str(enemy.get("id", "?"))
        enemy_pos_check = (enemy.get("col", "?"), enemy.get("row", "?"))
        enemy_hp_check = enemy.get("HP_CUR", -1)
        enemy_player_check = enemy.get("player", "?")
        add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Checking Enemy {enemy_id_check}({enemy_pos_check[0]},{enemy_pos_check[1]}) HP={enemy_hp_check} player={enemy_player_check}")
        
        # unit.HP_CUR > 0? -> NO -> Skip enemy unit
        if enemy["HP_CUR"] <= 0:
            add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Enemy {enemy_id_check} EXCLUDED - HP_CUR <= 0")
            continue
        
        # CRITICAL: Normalize enemy ID for consistent comparison
        # This ensures we catch self-targeting even if IDs are different types (int vs string)
        enemy_id_normalized = str(enemy["id"])
        
        # CRITICAL: Skip the shooter unit itself (cannot shoot self)
        # Use normalized IDs to ensure we catch all cases regardless of type mismatch
        if enemy_id_normalized == unit_id_normalized:
            # Log this as a critical bug if it somehow happens
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log, add_debug_log
                log_msg = f"[SHOOT CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Unit {unit_id_normalized} attempted to add itself (enemy_id={enemy_id_normalized}, unit['id']={unit['id']}, enemy['id']={enemy['id']}) to valid_target_pool - BLOCKED"
                add_console_log(game_state, log_msg)
            continue
        
        # unit.player != current_player? -> NO -> Skip enemy unit
        # CRITICAL: Convert to int for consistent comparison (player can be int or string)
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        if enemy_player == current_player_int:
            # Log this as a bug if it somehow happens
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log, add_debug_log
                log_msg = f"[SHOOT CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Unit {unit_id_normalized} (player={current_player_int}) attempted to add friendly unit {enemy_id_normalized} (player={enemy_player}) to valid_target_pool - BLOCKED"
                add_console_log(game_state, log_msg)
            continue
        
        # CRITICAL: Check if enemy is adjacent to shooter (melee range)
        # EXCEPTION: PISTOL weapons can shoot at adjacent enemies
        # This check must be done BEFORE checking if enemy is engaged with other friendly units
        from engine.utils.weapon_helpers import get_melee_range
        melee_range = get_melee_range()
        unit_col, unit_row = get_unit_coordinates(unit)
        enemy_col, enemy_row = get_unit_coordinates(enemy)
        distance_to_enemy = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
        
        # Check if enemy is adjacent to shooter
        enemy_adjacent_to_shooter = (distance_to_enemy <= melee_range)
        has_pistol_weapon = False
        
        if enemy_adjacent_to_shooter:
            # Enemy is adjacent to shooter - check if any weapon has PISTOL rule
            for weapon_idx in usable_weapon_indices:
                if weapon_idx < len(rng_weapons):
                    weapon = rng_weapons[weapon_idx]
                    if _weapon_has_pistol_rule(weapon):
                        has_pistol_weapon = True
                        break
            
            # If no PISTOL weapon available, cannot shoot at adjacent enemy
            if not has_pistol_weapon:
                add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Enemy {enemy_id_normalized}({enemy['col']},{enemy['row']}) EXCLUDED - adjacent without PISTOL weapon")
                continue
        
        # Unit NOT adjacent to friendly unit (excluding active unit)? -> NO -> Skip enemy unit
        # CRITICAL: This rule applies ONLY when enemy is NOT adjacent to shooter
        # If enemy is adjacent to shooter AND we have PISTOL weapon, we can shoot regardless of engagement
        # If enemy is NOT adjacent to shooter, normal rules apply: cannot shoot if enemy is engaged with friendly units
        if not enemy_adjacent_to_shooter:
            # Enemy is NOT adjacent to shooter - apply normal engaged enemy rule
            enemy_adjacent_to_friendly = False
            for friendly in game_state["units"]:
                # CRITICAL: Convert to int for consistent comparison (player can be int or string)
                friendly_player = int(friendly["player"]) if friendly["player"] is not None else None
                if (friendly_player == current_player_int and 
                    friendly["HP_CUR"] > 0 and 
                    friendly["id"] != unit["id"]):
                    enemy_col, enemy_row = get_unit_coordinates(enemy)
                    friendly_col, friendly_row = get_unit_coordinates(friendly)
                    friendly_distance = _calculate_hex_distance(
                        enemy_col, enemy_row, friendly_col, friendly_row
                    )
                    if friendly_distance <= melee_range:
                        enemy_adjacent_to_friendly = True
                        break
            
            if enemy_adjacent_to_friendly:
                add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Enemy {enemy_id_normalized}({enemy['col']},{enemy['row']}) EXCLUDED - engaged with friendly unit")
                continue
        
        # AI_TURN.md: LoS check already done in build_unit_los_cache()
        # We filtered los_cache above to only include targets with has_los == True
        # So we can skip LoS check here (performance optimization)
        
        # Unit within range of AT LEAST 1 weapon from weapon_available_pool? -> NO -> Skip enemy unit
        # CRITICAL: Reuse distance already calculated above (distance_to_enemy)
        unit_within_range = False
        distance = distance_to_enemy
        
        for weapon_idx in usable_weapon_indices:
            if weapon_idx < len(rng_weapons):
                weapon = rng_weapons[weapon_idx]
                weapon_range = weapon.get("RNG", 0)
                if distance <= weapon_range:
                    unit_within_range = True
                    break
        
        # ALL conditions met -> ✅ Add unit to valid_target_pool
        # CRITICAL: Convert ID to string for consistent comparison (target_id is passed as str)
        # Note: Friendly units are already filtered out at line 949-960 above
        if unit_within_range:
            # CRITICAL: Double-check friendly status before adding (defense in depth)
            # This should never happen if line 1030 is correct, but adds safety
            if enemy_player == current_player_int:
                add_console_log(game_state, f"[CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Attempted to ADD friendly unit {enemy_id_normalized} (player={enemy_player}) to pool for Unit {unit_id_normalized} (player={current_player_int}) - BLOCKED")
                continue  # Skip friendly units
            valid_target_pool.append(str(enemy["id"]))
            add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Enemy {enemy_id_normalized}({enemy['col']},{enemy['row']}) ADDED to pool (distance={distance}, shooter_player={current_player_int}, target_player={enemy_player})")
        else:
            add_debug_log(game_state, f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: Enemy {enemy_id_normalized}({enemy['col']},{enemy['row']}) EXCLUDED - out of range (distance={distance}, max_range={max([w.get('RNG', 0) for w in rng_weapons] + [0])})")
    
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

    # Create cache key from unit identity, position, player, AND context (advance_status, adjacent_status)
    # Cache must include context to avoid wrong results after advance
    # CRITICAL: Include unit["player"] to ensure cache is invalidated when player changes
    unit_col, unit_row = get_unit_coordinates(unit)
    cache_key = (unit_id, unit_col, unit_row, advance_status, adjacent_status, unit["player"])

    # Check cache
    if cache_key in _target_pool_cache:
        # Cache hit: Fast path - filter dead targets only
        # AI_TURN.md: During shooting activation, friendly units cannot die or move
        # Only targets can die, which is already handled by HP_CUR > 0 filter
        # Context (advance_status, adjacent_status) is part of cache key, so cache is reliable
        cached_pool = _target_pool_cache[cache_key]

        # Filter out units that died (only change possible during activation)
        # CRITICAL: Also check that target is not a friendly unit (defense in depth)
        alive_targets = []
        current_player = unit["player"]
        # CRITICAL: Convert to int for consistent comparison (player can be int or string)
        current_player_int = int(current_player) if current_player is not None else None
        for target_id_str in cached_pool:  # Iterate over string IDs
            target = _get_unit_by_id(game_state, target_id_str)
            if target and target["HP_CUR"] > 0:
                # CRITICAL: First check - target must not be friendly (fast check)
                # This is the most important check - friendly units should NEVER be in the pool
                # CRITICAL: Convert to int for consistent comparison (player can be int or string)
                target_player = int(target["player"]) if target["player"] is not None else None
                if target_player == current_player_int:
                    # This is a bug - log it for debugging
                    from engine.game_utils import add_console_log, add_debug_log
                    add_console_log(game_state, f"[BUG] Cache contained friendly unit {target_id_str} (player {target['player']}) for shooter {unit_id} (player {current_player})")
                    continue  # Skip friendly units
                
                # AI_TURN.md: No re-validation needed - cache is reliable during activation
                # Only targets can die (filtered above), friendly units cannot move or die
                alive_targets.append(target_id_str)  # Ensure ID is string

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
    
    # CRITICAL: Ensure los_cache exists and is up-to-date before calling valid_target_pool_build
    # This can happen if shooting_build_valid_target_pool is called before shooting_unit_activation_start
    # OR if unit has advanced since los_cache was built
    unit_id_str = str(unit_id)
    has_advanced = unit_id_str in game_state.get("units_advanced", set())
    
    # Check if los_cache needs to be rebuilt (missing or unit has advanced)
    if "los_cache" not in unit or has_advanced:
        # position_cache must be built at phase start, not here.
        if "position_cache" not in game_state:
            raise KeyError("position_cache must exist before valid target pool (build at shooting_phase_start)")
        
        # Build los_cache for unit (rebuild if unit has advanced)
        if unit_id_str not in game_state.get("units_fled", set()):
            build_unit_los_cache(game_state, unit_id)
        else:
            # Unit has fled - cannot shoot, so no los_cache needed
            unit["los_cache"] = {}
    
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
    
    # CRITICAL: Filter out self and friendly units before priority calculation
    # This prevents friendly units from being included in priorities
    unit_id_str = str(unit["id"])
    current_player = unit["player"]
    filtered_targets = []
    for target_id in valid_target_pool:
        target = _get_unit_by_id(game_state, target_id)
        if target:
            # Skip self
            if str(target["id"]) == unit_id_str:
                continue
            # Skip friendly units
            if target["player"] == current_player:
                continue
            filtered_targets.append(target_id)
    
    # Use filtered targets for priority calculation
    for target_id in filtered_targets:
        target = _get_unit_by_id(game_state, target_id)
        if not target:
            target_priorities.append((target_id, (999, 0, 999)))
            continue

        distance = _calculate_hex_distance(*get_unit_coordinates(unit), *get_unit_coordinates(target))

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
    
    # CRITICAL: Final safety check - filter out any friendly units that might have slipped through
    # This should never happen if valid_target_pool_build is correct, but adds defense in depth
    current_player = unit["player"]
    # CRITICAL: Convert to int for consistent comparison (player can be int or string)
    current_player_int = int(current_player) if current_player is not None else None
    filtered_pool = []
    for target_id in valid_target_pool:
        target = _get_unit_by_id(game_state, target_id)
        if target:
            # CRITICAL: Convert to int for consistent comparison (player can be int or string)
            target_player = int(target["player"]) if target["player"] is not None else None
            if target_player != current_player_int:
                filtered_pool.append(target_id)
            else:
                # If target is friendly, it's a bug in valid_target_pool_build - log it
                from engine.game_utils import add_console_log, add_debug_log
                add_console_log(game_state, f"[BUG] valid_target_pool_build included friendly unit {target_id} for shooter {unit_id}")
    
    valid_target_pool = filtered_pool

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
    start_col, start_row = get_unit_coordinates(shooter)
    end_col, end_row = get_unit_coordinates(target)

    # Try multiple sources for wall hexes
    wall_hexes_data = []
    wall_source = None

    # Source 1: Direct in game_state
    if "wall_hexes" in game_state:
        wall_hexes_data = game_state["wall_hexes"]
        wall_source = "game_state['wall_hexes']"
    
    # Source 2: In board configuration within game_state
    elif "board" in game_state and "wall_hexes" in game_state["board"]:
        wall_hexes_data = game_state["board"]["wall_hexes"]
        wall_source = "game_state['board']['wall_hexes']"
    
    # Source 3: Check if walls exist in board config
    # Direct field access chain
    elif "board_config" in game_state and "wall_hexes" in game_state["board_config"]:
        wall_hexes_data = game_state["board_config"]["wall_hexes"]
        wall_source = "game_state['board_config']['wall_hexes']"
    
    else:
        # CHANGE 8: NO FALLBACK - raise error if wall data not found in any source
        raise KeyError("wall_hexes not found in game_state['wall_hexes'], game_state['board']['wall_hexes'], or game_state['board_config']['wall_hexes']")
    
    # DEBUG: Log wall data source and format (only in debug mode to avoid performance impact)
    debug_mode = game_state.get("debug_mode", False)
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    shooter_id = shooter.get("id", "?")
    target_id = target.get("id", "?")
    from engine.game_utils import add_console_log, add_debug_log
    if debug_mode:
        add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} _has_line_of_sight: Shooter {shooter_id}({start_col},{start_row}) -> Target {target_id}({end_col},{end_row})")
        add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} Wall source: {wall_source}, Type: {type(wall_hexes_data)}, Length: {len(wall_hexes_data) if hasattr(wall_hexes_data, '__len__') else 'N/A'}")
    
    if not wall_hexes_data:
        if debug_mode:
            add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} No wall data found - allowing shot")
        return True
    
    # Convert wall_hexes to set for fast lookup
    # CRITICAL: Convert coordinates to int for consistent comparison
    wall_hexes = set()
    invalid_walls = []
    for wall_hex in wall_hexes_data:
        if isinstance(wall_hex, (list, tuple)) and len(wall_hex) >= 2:
            # CRITICAL: Convert to int to ensure consistent comparison with hex_path coordinates
            col_int = int(wall_hex[0])
            row_int = int(wall_hex[1])
            wall_hexes.add((col_int, row_int))
        else:
            invalid_walls.append(str(wall_hex))
    
    if invalid_walls and debug_mode:
        add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} Invalid wall formats: {invalid_walls[:5]}")
    if debug_mode:
        add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} Converted {len(wall_hexes)} valid wall hexes")
    
    try:
        # CRITICAL: Convert coordinates to int to ensure consistent comparison
        start_col_int = int(start_col)
        start_row_int = int(start_row)
        end_col_int = int(end_col)
        end_row_int = int(end_row)
        hex_path = _get_accurate_hex_line(start_col_int, start_row_int, end_col_int, end_row_int)
        
        if debug_mode:
            add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} Hex path ({len(hex_path)} hexes): {hex_path[:3]}...{hex_path[-3:]}")
        
        # Check if any hex in path is a wall (excluding start and end)
        # CRITICAL: Must check all hexes in path, not just first wall found
        # Convert coordinates to int for consistent comparison
        blocking_walls = []
        for i, (col, row) in enumerate(hex_path):
            # Skip start and end hexes
            if i == 0 or i == len(hex_path) - 1:
                continue
            
            # CRITICAL: Convert to int for consistent comparison with wall_hexes set
            col_int = int(col)
            row_int = int(row)
            
            if (col_int, row_int) in wall_hexes:
                blocking_walls.append((col_int, row_int))
        
        if blocking_walls:
            if debug_mode:
                add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} LoS BLOCKED by walls: {blocking_walls}")
            return False
        
        # No walls blocking - line of sight is clear
        if debug_mode:
            add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} LoS CLEAR (no blocking walls)")
        return True
        
    except Exception as e:
        # On error, deny line of sight (fail-safe)
        if debug_mode:
            add_debug_log(game_state, f"[LOS DEBUG] E{episode} T{turn} LoS calculation ERROR: {str(e)} - denying LoS (fail-safe)")
        return False

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
    # CRITICAL: Include all_attack_results if attacks were executed before phase completion
    # This ensures attacks already executed are logged to step.log
    shoot_attack_results = game_state.get("shoot_attack_results", [])
    
    # Final cleanup
    game_state["shoot_activation_pool"] = []
    
    # PERFORMANCE: Clear LoS cache at phase end (will rebuild next shooting phase)
    if "los_cache" in game_state:
        game_state["los_cache"] = {}
    
    # Console log
    from engine.game_utils import add_console_log, add_debug_log
    add_console_log(game_state, "SHOOTING PHASE COMPLETE")
    
    # Base result with all_attack_results if present
    base_result = {}
    if shoot_attack_results:
        base_result["all_attack_results"] = list(shoot_attack_results)
    
    # Player progression logic
    if game_state["current_player"] == 1:
        # AI_TURN.md Line 105: P1 Move -> P1 Shoot -> P1 Charge -> P1 Fight
        # Player stays 1, advance to charge phase
        return {
            **base_result,
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
    elif game_state["current_player"] == 2:
        # Player 2 complete -> Check if incrementing turn would exceed limit
        max_turns = game_state.get("config", {}).get("training_config", {}).get("max_turns_per_episode")
        if max_turns and (game_state["turn"] + 1) > max_turns:
            # Incrementing would exceed turn limit - end game without incrementing
            game_state["game_over"] = True
            return {
                **base_result,
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
            # AI_TURN.md Line 105: P2 Move -> P2 Shoot -> P2 Charge -> P2 Fight
            # Player stays 2, advance to charge phase
            # Turn increment happens at P2 Fight end (fight_handlers.py:797)
            return {
                **base_result,
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "charge",
                "current_player": 2,
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

def shooting_clear_activation_state(game_state: Dict[str, Any], unit: Dict[str, Any]) -> None:
    """Clear shooting activation state (equivalent to movement_clear_preview in MOVE phase).
    
    This function clears:
    - active_shooting_unit
    - unit's valid_target_pool
    - unit's TOTAL_ATTACK_LOG
    - unit's selected_target_id
    - unit's activation_position
    - unit's _shooting_with_pistol
    - unit's SHOOT_LEFT (reset to 0)
    
    Called BEFORE end_activation to clean up state, exactly like movement_clear_preview in MOVE.
    
    CRITICAL: Only called when arg5=1 (actually ending activation).
    If arg5=0 (NOT_REMOVED), state is preserved to continue activation.
    """
    # Clear active unit
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]
    
    # Clear unit activation state
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    # AI_TURN.md: Clean up los_cache at end of activation
    if "los_cache" in unit:
        del unit["los_cache"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]
    if "_shooting_with_pistol" in unit:
        del unit["_shooting_with_pistol"]
    unit["SHOOT_LEFT"] = 0

def _get_shooting_context(game_state: Dict[str, Any], unit: Dict[str, Any]) -> str:
    """Determine current shooting context for nested behavior."""
    # Direct field access
    if "selected_target_id" in unit and unit["selected_target_id"]:
        return "target_selected"
    else:
        return "no_target_selected"

def _handle_shooting_end_activation(game_state: Dict[str, Any], unit: Dict[str, Any],
                                     arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1,
                                     action_type: str = None, include_attack_results: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """Handle shooting activation end using end_activation (aligned with MOVE phase).
    
    This function:
    1. Clears activation state BEFORE end_activation (like movement_clear_preview in MOVE)
    2. Calls end_activation (which removes from pool and checks if pool empty)
    3. Preserves all_attack_results if needed (for logging before phase transition)
    
    CRITICAL: phase_complete is now handled in _process_shooting_phase (like MOVE), not here.
    
    Args:
        arg1: ACTION/WAIT/PASS - logging behavior
        arg2: 1/0 - step increment
        arg3: SHOOTING/ADVANCE/PASS - tracking sets
        arg4: SHOOTING - pool removal phase
        arg5: 1/0 - error logging (1=remove from pool, 0=NOT_REMOVED)
        action_type: Optional action type for result dict (defaults to inferred from arg1)
        include_attack_results: Whether to include shoot_attack_results in response
    
    Returns:
        Tuple[bool, Dict] - (success, result) where result may contain phase_complete (but not next_phase)
    """
    from engine.phase_handlers.generic_handlers import end_activation
    
    # CRITICAL: Only clear state if actually ending activation (arg5=1)
    # If arg5=0 (NOT_REMOVED), we continue activation, so keep state intact
    if arg5 == 1:
        shooting_clear_activation_state(game_state, unit)
    
    # Call end_activation (exactly like MOVE phase)
    result = end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)
    
    # Invariant: when in shoot with non-empty pool, active_shooting_unit = pool[0]
    # Must hold after every end_activation (shoot/advance/wait/execution_loop), not only wait/skip.
    pool = game_state.get("shoot_activation_pool", [])
    if pool:
        game_state["active_shooting_unit"] = pool[0]
    
    # CRITICAL: Pool empty detection is handled in execute_action (like MOVE phase)
    # This prevents double call to _shooting_phase_complete (once here, once in _process_shooting_phase)
    # execute_action checks pool empty BEFORE processing action, so phase_complete is handled there
    
    # Determine action type for result
    if action_type is None:
        if arg1 == "PASS":
            action_type = "skip"
        elif arg1 == "WAIT":
            action_type = "wait"
        elif arg1 == "ACTION":
            if arg3 == "ADVANCE":
                action_type = "advance"
            elif arg3 == "SHOOTING":
                action_type = "shoot"
            else:
                action_type = "shoot"
        else:
            action_type = "shoot"
    
    # Update result with action type and activation_complete (like _handle_skip_action in MOVE)
    result.update({
        "action": action_type,
        "unitId": unit["id"],
        "activation_complete": True
    })
    
    # Include attack results if needed (for cases where attacks were executed before ending)
    # CRITICAL: This must be done BEFORE phase transition to ensure logging
    if include_attack_results:
        shoot_attack_results = game_state.get("shoot_attack_results", [])
        if shoot_attack_results:
            result["all_attack_results"] = list(shoot_attack_results)
    
    return True, result

# DEPRECATED: _shooting_activation_end is replaced by _handle_shooting_end_activation + end_activation
# This function is kept for backward compatibility but should not be used in new code
# All calls have been migrated to use end_activation directly (aligned with MOVE phase)
def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """
    DEPRECATED: Use _handle_shooting_end_activation instead (aligned with MOVE phase).
    
    This function is kept for backward compatibility but should not be used in new code.
    All calls have been migrated to use end_activation directly via _handle_shooting_end_activation.
    
    Migration path:
    - Replace all calls to _shooting_activation_end with _handle_shooting_end_activation
    - For arg5=0 (NOT_REMOVED), call end_activation directly instead
    """
    # Redirect to new implementation
    return _handle_shooting_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)

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
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                
                # Check if at least one weapon is usable (can_use: True)
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                if not usable_weapons:
                    # No usable weapons left, end activation
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                
                return True, {

                    "while_loop_active": True,
                    "valid_targets": valid_targets,
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
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # No weapon selected, end activation
            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
    
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
        is_pve_ai = config.get("pve_mode", False) and unit_check and unit_check["player"] == 2
        is_gym_training = config.get("gym_training_mode", False) and unit_check and unit_check["player"] == 2
        is_bot = unit_check and unit_check["player"] == 2 and not is_pve_ai
        
        # For AI/gym/bots: end activation as before
        if is_pve_ai or is_gym_training or is_bot:
            if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
                # No targets at activation
                return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)
            else:
                # Shot last target available
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        
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
            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
    
    # CLEAN FLAG DETECTION: Use config parameter
    unit = _get_unit_by_id(game_state, unit_id)
    is_pve_ai = config.get("pve_mode", False) and unit and unit["player"] == 2
    
    # CHANGE 1: Add gym_training_mode detection
    # Gym agents have already made shoot/skip decisions via action selection (actions 4-8 or 11)
    # The execution loop reaches here when SHOOT_LEFT > 0 after a shot, so we need to auto-execute
    is_gym_training = config.get("gym_training_mode", False) and unit and unit["player"] == 2
    # Bots (player 2) should also auto-continue attacks like gym training
    is_bot = unit and unit["player"] == 2 and not is_pve_ai
    
    # CHANGE 2: Auto-execute for BOTH PvE AI, gym training, and bots
    if (is_pve_ai or is_gym_training or is_bot) and valid_targets:
        # CRITICAL: Rebuild target pool just before execution to ensure it's up-to-date
        # Other units may have moved or died since the pool was first built
        # This prevents "shoot at engaged enemy" and "shoot after fled" errors
        valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
        unit["valid_target_pool"] = valid_targets
        
        if not valid_targets:
            # No valid targets after rebuild - end activation
            return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)
        
        # AUTO-SHOOT: PvE AI and gym training
        target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly and return result
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    # Only humans get waiting_for_player response
    # Get available weapons for frontend weapon menu
    has_advanced = unit_id in game_state.get("units_advanced", set())
    
    # Check if unit has already fired with a weapon to apply PISTOL category filter
    # Use _shooting_with_pistol if available (set after first shot), otherwise check if unit has fired
    current_weapon_is_pistol = None  # Default: no filter (unit hasn't fired yet)
    
    if "_shooting_with_pistol" in unit:
        # Unit has fired at least once, use stored category
        current_weapon_is_pistol = unit["_shooting_with_pistol"]
    else:
        # Fallback: Check if unit has fired by comparing SHOOT_LEFT
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        if selected_weapon and unit.get("SHOOT_LEFT", 0) < selected_weapon.get("NB", 0):
            # Unit has already fired (SHOOT_LEFT decreased), determine category from current weapon
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
    
    # CRITICAL: Include all_attack_results if attacks were executed before (in a loop)
    # This ensures attacks already executed are logged to step.log
    shoot_attack_results = game_state.get("shoot_attack_results", [])
    
    response = {
        "while_loop_active": True,
        "valid_targets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True,
        "waiting_for_player": True,
        "available_weapons": available_weapons,
        "action": "wait",  # CRITICAL: Set action for logging (waiting for target selection)
        "unitId": unit_id,
        "phase": "shoot"
    }
    
    # CRITICAL: Include all_attack_results if attacks were executed
    # This ensures attacks already executed are logged even when waiting_for_player=True
    if shoot_attack_results:
        response["all_attack_results"] = list(shoot_attack_results)
        # Change action to "shoot" if attacks were executed (not just waiting)
        response["action"] = "shoot"
    
    return True, response

def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md EXACT: Complete action routing with full phase lifecycle management
    """
    
    # Phase initialization on first call
    if "_shooting_phase_initialized" not in game_state or not game_state["_shooting_phase_initialized"]:
        shooting_phase_start(game_state)
        game_state["_shooting_phase_initialized"] = True
    
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    if "unitId" not in action:
        action_type = action["action"]
        unit_id = "none"  # Allow missing for some action types
    else:
        action_type = action["action"]
        unit_id = action["unitId"]
    # AI_TURN.md COMPLIANCE: Pool is built once at phase start (STEP 1: ELIGIBILITY CHECK)
    # Units are removed ONLY via:
    # 1. end_activation() with Arg4 = SHOOTING (when unit finishes activation)
    # 2. _remove_dead_unit_from_pools() (when unit dies)
    # No filtering or modification of pool in execute_action - this is not described in AI_TURN.md
    
    # Check if shooting phase should complete - read directly from game_state (not cached)
    # CRITICAL: Read pool directly to get current state (pool may have been modified by previous actions)
    current_pool = game_state.get("shoot_activation_pool", [])
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
    
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
    # CRITICAL: Normalize unit_id to string for consistent comparison with pool (which may contain int or string IDs)
    unit_id = str(unit["id"])
    
    # DEBUG: Log unit activation for dead unit detection
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    hp_cur = unit.get("HP_CUR", -1)
    # CRITICAL: Normalize unit_id to string for consistent comparison (pool stores strings)
    unit_id_str = str(unit_id)
    pool_ids = [str(uid) for uid in game_state.get("shoot_activation_pool", [])]
    in_pool = unit_id_str in pool_ids
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} execute_action: Unit {unit_id} (HP_CUR={hp_cur}, in_pool={in_pool})")
    
    # Direct field access
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    
    # CRITICAL FIX: Auto-activate unit if not already activated (aligned with MOVE phase)
    # This prevents get_action_mask from reactivating units before end_activation removes them from pool
    # Auto-activation is now done in execute_action (like MOVE) instead of get_action_mask
    active_shooting_unit = game_state.get("active_shooting_unit")
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
    current_player = game_state.get("current_player")
    is_learning_agent_turn = current_player == 1
    
    # Auto-activate unit if not already activated and action requires activation
    # CRITICAL: Do this BEFORE validation to ensure unit is activated before action routing
    # CRITICAL: "wait" and "skip" are end-of-activation actions, not actions that require activation
    # They should only be called when unit is already activated
    if not active_shooting_unit and action_type in ["shoot", "advance"] and is_gym_training and is_learning_agent_turn:
        # Verify unit is still in pool before activation (defense in depth)
        unit_id_str = str(unit_id)
        pool_ids = [str(uid) for uid in game_state.get("shoot_activation_pool", [])]
        if unit_id_str in pool_ids:
            from engine.game_utils import add_debug_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_log(game_state, f"[AUTO_ACTIVATION DEBUG] E{episode} T{turn} execute_action: Auto-activating unit {unit_id_str} for action {action_type}")
            activation_result = shooting_unit_activation_start(game_state, unit_id)
            if activation_result.get("error"):
                # Activation failed - return error
                from engine.game_utils import add_debug_log
                add_debug_log(game_state, f"[AUTO_ACTIVATION ERROR] E{episode} T{turn} execute_action: Auto-activation failed: {activation_result.get('error')}")
                return False, activation_result
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    current_player_int = int(game_state["current_player"]) if game_state["current_player"] is not None else None
    if unit_player != current_player_int:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
    # Pool always contains string IDs (normalized at creation), so direct comparison is safe
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    if action_type != "select_weapon" and unit_id not in game_state["shoot_activation_pool"]:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    # select_weapon can reactivate unit after weapon exhaustion (unit must have been eligible before)
    
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
        # If no success and no error handled above, return the result (may contain other errors)
        return False, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with optional targetId
        if "targetId" not in action:
            target_id = None
        else:
            target_id = action["targetId"]
        
        # Validate unit eligibility
        # Pool always contains string IDs (normalized at creation), so direct comparison is safe
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
            activation_result = shooting_unit_activation_start(game_state, unit_id)
        
        # Auto-select target if not provided (AI mode)
        if not target_id:
            valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            
            # Debug output only in debug training mode
            if not valid_targets:
                # No valid targets - end activation with wait
                return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)
            target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly without UI loops
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    elif action_type == "advance":
        # ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase
        return _handle_advance_action(game_state, unit, action, config)
    
    elif action_type == "select_weapon":
        # WEAPON_SELECTION: Handle weapon selection action
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
        unit_col, unit_row = get_unit_coordinates(unit)
        cache_key = (unit_id, unit_col, unit_row)
        if cache_key in _target_pool_cache:
            del _target_pool_cache[cache_key]

        # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
        # Update SHOOT_LEFT with the new weapon's NB
        weapon = rng_weapons[weapon_index]
        unit["SHOOT_LEFT"] = weapon["NB"]
        
        # AI_TURN.md COMPLIANCE: Unit must already be in pool (pool is built once at phase start)
        # If unit is not in pool, it was removed via end_activation and cannot be reactivated
        # CRITICAL: Normalize unit_id to string for consistent comparison (pool stores strings)
        unit_id_str = str(unit_id)
        pool_ids = [str(uid) for uid in game_state.get("shoot_activation_pool", [])]
        if unit_id_str not in pool_ids:
            # Unit not in pool - cannot select weapon (unit was removed via end_activation)
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_debug_log
            add_debug_log(game_state, f"[SELECT_WEAPON ERROR] E{episode} T{turn} select_weapon: Unit {unit_id_str} NOT in pool, cannot select weapon. Pool={pool_ids}")
            return False, {"error": "unit_not_in_pool", "unitId": unit_id, "message": "Unit was removed from pool and cannot select weapon"}
        
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
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        # EXACT COMPLIANCE: Same logic as right_click action (lines 2453-2468)
        has_shot = _unit_has_shot_with_any_weapon(unit)
        unit_id_str = str(unit["id"])
        if has_shot:
            # YES -> end_activation(ACTION, 1, SHOOTING, SHOOTING, 1)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # Check if unit has advanced (ADVANCED_SHOOTING_ACTION_SELECTION)
            has_advanced = unit_id_str in game_state.get("units_advanced", set())
            if has_advanced:
                # NO -> Unit has not shot yet (only advanced) -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1)
            else:
                # NO -> end_activation(WAIT, 1, 0, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # AI_TURN.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # AI_TURN.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to AI_TURN.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = game_state.get("shoot_activation_pool", [])
        if not pool_after_removal:
            # Pool is empty - phase is complete (AI_TURN.md LINE 794: "NO → End of shooting phase")
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        
        return success, result
    
    elif action_type == "left_click":
        target_id = action.get("targetId")
        return shooting_click_handler(game_state, unit_id, action, config)
    
    elif action_type == "right_click":
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        has_shot = _unit_has_shot_with_any_weapon(unit)
        unit_id_str = str(unit["id"])
        if has_shot:
            # YES -> end_activation(ACTION, 1, SHOOTING, SHOOTING, 1)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # Check if unit has advanced (ADVANCED_SHOOTING_ACTION_SELECTION)
            has_advanced = unit_id_str in game_state.get("units_advanced", set())
            if has_advanced:
                # NO -> Unit has not shot yet (only advanced) -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1)
            else:
                # NO -> end_activation(WAIT, 1, 0, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # AI_TURN.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # AI_TURN.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to AI_TURN.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = game_state.get("shoot_activation_pool", [])
        if not pool_after_removal:
            # Pool is empty - phase is complete (AI_TURN.md LINE 794: "NO → End of shooting phase")
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        
        return success, result
    
    elif action_type == "skip":
        # AI_TURN.md: Skip action - same as wait
        success, result = _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip")
        
        # AI_TURN.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # AI_TURN.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to AI_TURN.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = game_state.get("shoot_activation_pool", [])
        if not pool_after_removal:
            # Pool is empty - phase is complete (AI_TURN.md LINE 794: "NO → End of shooting phase")
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        
        return success, result
    
    elif action_type == "invalid":
        # Handle invalid actions with training penalty - treat as miss but continue shooting sequence
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        if unit_id in current_pool:
            # Initialize unit if not already activated (this was the missing piece)
            active_shooting_unit = game_state.get("active_shooting_unit")
            if active_shooting_unit != unit_id:
                activation_result = shooting_unit_activation_start(game_state, unit_id)
            
            # DO NOT decrement SHOOT_LEFT - invalid action doesn't consume a shot
            # Just continue execution loop which will handle auto-shooting for PvE AI
            result = _shooting_unit_execution_loop(game_state, unit_id, config)
            if isinstance(result, tuple) and len(result) >= 2:
                success, loop_result = result
                loop_result["invalid_action_penalty"] = True
                # CRITICAL: No default value - require explicit attempted_action
                attempted_action = action.get("attempted_action")
                if attempted_action is None:
                    raise ValueError(f"Action missing 'attempted_action' field: {action}")
                loop_result["attempted_action"] = attempted_action
                return success, loop_result
            else:
                # CRITICAL: No default value - require explicit attempted_action
                attempted_action = action.get("attempted_action")
                if attempted_action is None:
                    raise ValueError(f"Action missing 'attempted_action' field: {action}")
                return True, {"invalid_action_penalty": True, "attempted_action": attempted_action}
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
        # Left click on another unit in pool - switch units (only if current unit hasn't shot)
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if target_id in game_state["shoot_activation_pool"]:
            # Check if current unit has shot - if yes, block switch
            current_unit = _get_unit_by_id(game_state, unit_id)
            if current_unit:
                has_shot = _unit_has_shot_with_any_weapon(current_unit)
                if has_shot:
                    # Unit has already shot - cannot switch (must finish shooting)
                    return True, {"action": "no_effect", "unitId": unit_id, "error": "cannot_switch_after_shooting"}
            return _handle_unit_switch_with_context(game_state, unit_id, target_id, config)
        return False, {"error": "unit_not_in_pool", "targetId": target_id}
    
    elif click_target == "active_unit":
        # Left click on active unit - behavior depends on whether unit has shot
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
        has_shot = _unit_has_shot_with_any_weapon(unit)
        if has_shot:
            # Unit has already shot - no effect (must finish shooting)
            return True, {"action": "no_effect", "unitId": unit_id}
        else:
            # Unit has not shot yet - postpone (deselect, return to pool)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
            # Invariant: when in shoot with non-empty pool, active_shooting_unit = pool[0]
            pool = game_state.get("shoot_activation_pool", [])
            if pool:
                game_state["active_shooting_unit"] = pool[0]
            return True, {
                "action": "postpone",
                "unitId": unit_id,
                "activation_ended": False,
                "reset_mode": "select"
            }
    
    else:
        # STEP 5A/5B: Postpone/Click elsewhere (Human only)
        # Check if unit has shot with ANY weapon?
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
        has_shot = _unit_has_shot_with_any_weapon(unit)
        if not has_shot:
            # NO -> POSTPONE_ACTIVATION() -> UNIT_ACTIVABLE_CHECK
            # Unit is NOT removed from shoot_activation_pool (can be re-activated later)
            # Remove weapon selection icon from UI (handled by frontend)
            # Clear active unit
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
            # Invariant: when in shoot with non-empty pool, active_shooting_unit = pool[0]
            pool = game_state.get("shoot_activation_pool", [])
            if pool:
                game_state["active_shooting_unit"] = pool[0]
            # Return to UNIT_ACTIVABLE_CHECK step (by returning activation_ended=False)
            return True, {
                "action": "postpone",
                "unitId": unit_id,
                "activation_ended": False,
                "reset_mode": "select"
            }
        else:
            # YES -> Do not end activation automatically (allow user to click active unit to confirm)
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
        
        # CRITICAL: Check units_fled just before execution (may have changed during phase)
        # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
        if str(unit["id"]) in game_state.get("units_fled", set()):
            return False, {"error": "unit_has_fled", "unitId": unit_id}
        
        # ASSAULT RULE VALIDATION: Block shooting if unit advanced without ASSAULT weapon
        unit_id_str = str(unit["id"])
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if not selected_weapon or not _weapon_has_assault_rule(selected_weapon):
                return False, {"error": "cannot_shoot_after_advance_without_assault", "unitId": unit_id_str}
        
        # PISTOL RULE VALIDATION: Block shooting non-PISTOL weapons when adjacent to enemy
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        if is_adjacent:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if not selected_weapon or not _weapon_has_pistol_rule(selected_weapon):
                return False, {"error": "cannot_shoot_non_pistol_when_adjacent", "unitId": unit_id_str}
                
        # Validate unit has shots remaining
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        
        # Always check if current weapon is PISTOL to filter weapons correctly below
        # This is needed even when SHOOT_LEFT > 0 to maintain PISTOL category consistency
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        current_weapon_is_pistol = False
        if selected_weapon:
            current_weapon_is_pistol = _weapon_has_pistol_rule(selected_weapon)
        else:
            return False, {"error": "no_weapons_available", "unitId": unit_id}
        
        # Check if SHOOT_LEFT == 0 and handle weapon selection/switching
        if unit["SHOOT_LEFT"] <= 0:
            # SHOOT_LEFT is 0, need to switch to another weapon of the same category
            # current_weapon_is_pistol is already set above
            pass
        
        # CRITICAL: Use existing valid_target_pool from unit (rebuilt at activation, after advance, or after target death)
        # Do NOT rebuild here - pool is source of truth and is rebuilt only at specific moments
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found"}
        
        valid_targets = unit.get("valid_target_pool", [])
        
        # AI_TURN.md: If pool is empty, go to EMPTY_TARGET_HANDLING (advance or WAIT)
        # Pool should not be empty here if unit was properly activated, but if all targets died
        # between activation and this call, allow agent to choose advance or WAIT
        if len(valid_targets) == 0:
            # Mark unit as active for EMPTY_TARGET_HANDLING
            game_state["active_shooting_unit"] = unit_id
            unit["valid_target_pool"] = []
            
            # Check if unit can advance
            can_advance = unit.get("_can_advance", False)
            if can_advance:
                # Return signal to allow advance action (EMPTY_TARGET_HANDLING)
                return True, {
                    "success": True,
                    "unitId": unit_id,
                    "empty_target_pool": True,
                    "can_advance": True,
                    "allow_advance": True,
                    "waiting_for_player": False,  # Agent can choose immediately
                    "action": "empty_target_advance_available"
                }
            else:
                # Cannot advance - must WAIT
                return _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # Handle target selection: agent-provided or auto-select
        # NOTE: Friendly fire and LoS checks are already done in valid_target_pool_build().
        # No redundant checks here - trust the pool generation.
        # CRITICAL: Convert target_id to string for consistent comparison with valid_targets
        target_id_str = str(target_id) if target_id else None
        if target_id_str and target_id_str in valid_targets:
            # Agent provided valid target
            selected_target_id = target_id_str
            
            # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cette cible ===
            target = _get_unit_by_id(game_state, selected_target_id)
            if not target:
                return False, {"error": "target_not_found", "targetId": selected_target_id}
            
            # Only auto-select weapon if autoSelectWeapon is enabled
            config = game_state.get("config", {})
            auto_select = config.get("game_settings", {}).get("autoSelectWeapon", True)
            
            # If SHOOT_LEFT > 0, weapon is already selected and has remaining shots
            # Don't re-select weapon, just use the already selected one
            current_shoot_left = unit.get("SHOOT_LEFT", 0)
            if current_shoot_left > 0:
                # Weapon already selected, just verify it's still valid
                selected_weapon = get_selected_ranged_weapon(unit)
                if not selected_weapon:
                    return False, {"error": "no_weapons_available", "unitId": unit_id}
                # Use already selected weapon, no re-selection needed
            elif auto_select:
                # SHOOT_LEFT == 0, need to select a new weapon (same category if current weapon was used)
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
                    unit["SHOOT_LEFT"] = weapon["NB"]
                    
                    # PISTOL RULE VALIDATION: Re-validate after weapon selection
                    # This ensures the newly selected weapon is valid for current context
                    if is_adjacent:
                        if not _weapon_has_pistol_rule(weapon):
                            return False, {"error": "cannot_shoot_non_pistol_when_adjacent", "unitId": unit_id_str}
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
                            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                        
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
                                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                            
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
                            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        # === FIN NOUVEAU ===
        elif target_id:
            # Agent provided invalid target
            return False, {"error": "target_not_valid", "targetId": target_id}
        else:
            # No target provided - auto-select first valid target (human player fallback)
            selected_target_id = valid_targets[0]
            
            # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cible auto-sélectionnée ===
            target = _get_unit_by_id(game_state, selected_target_id)
            if not target:
                return False, {"error": "target_not_found", "targetId": selected_target_id}
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
            # CRITICAL: Convert target_id to string for consistent comparison with valid_targets
            target_id_str = str(target_id) if target_id else None
            if target_id_str and target_id_str in valid_targets:
                selected_target_id = target_id_str
            elif target_id_str:
                return False, {"error": "target_not_valid", "targetId": target_id_str, "valid_targets": valid_targets[:5]}
            else:
                selected_target_id = valid_targets[0]
        
        target = _get_unit_by_id(game_state, selected_target_id)
        if not target:
            return False, {"error": "target_not_found", "targetId": selected_target_id}
        
        # AI_TURN.md: Pool is source of truth - no redundant validation
        # Target is in valid_target_pool, so it's valid (pool is updated after advance and target death)
        
        # Execute shooting attack
        attack_result = shooting_attack_controller(game_state, unit_id, selected_target_id)
        
        # CRITICAL: Check if attack_result is an error before adding to shoot_attack_results
        # Error results don't have required fields like hit_roll, wound_roll, etc.
        if "error" in attack_result:
            return False, attack_result
        
        # CRITICAL: Add attack result to shoot_attack_results for logging
        # This ensures all attacks are logged even if waiting_for_player=True
        if "shoot_attack_results" not in game_state:
            game_state["shoot_attack_results"] = []
        # CRITICAL: Extract nested attack_result from wrapper (shooting_attack_controller returns wrapper)
        # The actual attack data is in attack_result["attack_result"]
        actual_attack_result = attack_result["attack_result"].copy()
        actual_attack_result["targetId"] = selected_target_id
        # CRITICAL: Include shooterId in actual_attack_result for correct logging
        # shooting_attack_controller returns shooterId in the wrapper, we need it in the attack_result for logging
        if "shooterId" in attack_result:
            actual_attack_result["shooterId"] = attack_result["shooterId"]
        else:
            # Fallback: use unit_id if shooterId not in wrapper (shouldn't happen but be safe)
            actual_attack_result["shooterId"] = unit_id
        # CRITICAL: Ensure target_died is always present (it's added in shooting_attack_controller but may be missing)
        if "target_died" not in actual_attack_result:
            actual_attack_result["target_died"] = attack_result.get("target_died", False)
        game_state["shoot_attack_results"].append(actual_attack_result)

        # Update SHOOT_LEFT and continue loop per AI_TURN.md
        unit["SHOOT_LEFT"] -= 1
        
        # PISTOL rule: Update _shooting_with_pistol after each shot to track weapon category
        # This ensures the filter persists even if unit switches weapons
        current_weapon_index = unit.get("selectedRngWeaponIndex", 0)
        rng_weapons = unit.get("RNG_WEAPONS", [])
        if current_weapon_index < len(rng_weapons):
            weapon = rng_weapons[current_weapon_index]
            weapon_rules = weapon.get("WEAPON_RULES", [])
            weapon_name = weapon.get("display_name", f"weapon_{current_weapon_index}")
            is_pistol = "PISTOL" in weapon_rules
            if is_pistol:
                unit["_shooting_with_pistol"] = True
            else:
                unit["_shooting_with_pistol"] = False

        # AI_TURN.md ligne 523-536: SHOOT_LEFT == 0 handling
        if unit["SHOOT_LEFT"] == 0:
            # Mark selected_weapon as used (set weapon.shot = 1)
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
                # YES -> Select next available weapon (AI/Human chooses)
                # For now, auto-select first usable weapon
                next_weapon = usable_weapons[0]
                unit["selectedRngWeaponIndex"] = next_weapon["index"]
                unit["SHOOT_LEFT"] = next_weapon["weapon"].get("NB", 0)
                
                # CRITICAL: Rebuild target pool using shooting_build_valid_target_pool for consistency
                # This wrapper automatically determines context (advance_status, adjacent_status)
                valid_target_pool = shooting_build_valid_target_pool(game_state, unit_id)
                unit["valid_target_pool"] = valid_target_pool
                
                # Continue to shooting action selection step (ADVANCED if arg2=1, else normal)
                # This is handled by _shooting_unit_execution_loop
                success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
                loop_result["phase"] = "shoot"
                loop_result["target_died"] = attack_result.get("target_died", False)
                loop_result["damage"] = attack_result.get("damage", 0)
                loop_result["target_hp_remaining"] = attack_result.get("target_hp_remaining", 0)
                # CRITICAL: Ensure action and unitId are set for logging
                if "action" not in loop_result:
                    loop_result["action"] = "shoot"
                if "unitId" not in loop_result:
                    loop_result["unitId"] = unit_id
                # CRITICAL: Include all_attack_results even when waiting_for_player
                # This ensures attacks already executed are logged to step.log
                shoot_attack_results = game_state.get("shoot_attack_results", [])
                if shoot_attack_results:
                    loop_result["all_attack_results"] = list(shoot_attack_results)
                return success, loop_result
            else:
                # NO -> All weapons exhausted -> End activation
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
        else:
            # NO -> Continue normally (SHOOT_LEFT > 0)
            # Handle target outcome (died/survived)
            target_died = attack_result.get("target_died", False)
            
            if target_died:
                # Remove from valid_target_pool
                valid_target_pool = unit.get("valid_target_pool", [])
                if selected_target_id in valid_target_pool:
                    valid_target_pool.remove(selected_target_id)
                    unit["valid_target_pool"] = valid_target_pool
                
                # valid_target_pool empty? -> YES -> End activation (Slaughter handling)
                if not unit.get("valid_target_pool"):
                    # CRITICAL: include_attack_results=True ensures all_attack_results is included
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
                # NO -> Continue to shooting action selection step
            # else: Target survives
            
            # Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            valid_targets = unit.get("valid_target_pool", [])
            if not valid_targets and unit["SHOOT_LEFT"] > 0:
                # YES -> End activation (Slaughter handling)
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
            # NO -> Continue to shooting action selection step
            
            # Continue to shooting action selection step
            success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            loop_result["phase"] = "shoot"
            loop_result["target_died"] = attack_result.get("target_died", False)
            loop_result["damage"] = attack_result.get("damage", 0)
            loop_result["target_hp_remaining"] = attack_result.get("target_hp_remaining", 0)
            # CRITICAL: Ensure action and unitId are set for logging
            if "action" not in loop_result:
                loop_result["action"] = "shoot"
            if "unitId" not in loop_result:
                loop_result["unitId"] = unit_id
            # CRITICAL: Include all_attack_results even when waiting_for_player
            # This ensures attacks already executed are logged to step.log
            shoot_attack_results = game_state.get("shoot_attack_results", [])
            if shoot_attack_results:
                loop_result["all_attack_results"] = list(shoot_attack_results)
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
    
    # CRITICAL: Validate unit_id matches shooter ID (detect ID mismatches)
    shooter_id_str = str(shooter["id"])
    unit_id_str = str(unit_id)
    if shooter_id_str != unit_id_str:
        # This should never happen if _get_unit_by_id works correctly
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        from engine.game_utils import add_console_log, add_debug_log, safe_print
        log_msg = f"[CRITICAL ID BUG] E{episode} T{turn} shooting_attack_controller: unit_id={unit_id_str} but shooter.id={shooter_id_str} - ID MISMATCH!"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
        import logging
        logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
        logging.info(log_msg)
    
    # CRITICAL DEBUG: Log unit details for weapon/type mismatch detection
    # This helps identify if the wrong unit is being retrieved
    shooter_unit_type = shooter.get("unitType", "Unknown")
    shooter_player = shooter.get("player", "?")
    shooter_weapons = [w.get("display_name", "unknown") for w in shooter.get("RNG_WEAPONS", [])]
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log, safe_print
    debug_msg = f"[SHOOT DEBUG] E{episode} T{turn} shooting_attack_controller: unit_id={unit_id_str} shooter.id={shooter_id_str} type={shooter_unit_type} player={shooter_player} weapons={shooter_weapons}"
    add_debug_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
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
            # DEBUG: Log target death
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_console_log, add_debug_log
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} target_died: Unit {target['id']} died (HP_CUR={target['HP_CUR']}), calling update_los_cache_after_target_death")
            
            # AI_TURN.md: Update los_cache after target death (remove entry, no recalculation)
            update_los_cache_after_target_death(game_state, target["id"])
            
            # PERFORMANCE: Invalidate LoS cache for dead unit (partial invalidation)
            # DEPRECATED: Keep for backward compatibility with global cache
            _invalidate_los_cache_for_unit(game_state, target["id"])
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate cache for dead unit (can't attack anymore)
            from engine.ai.weapon_selector import invalidate_cache_for_unit
            invalidate_cache_for_unit(cache, str(target["id"]))
            # CRITICAL: Remove dead unit from activation pools (prevents dead units from acting)
            _remove_dead_unit_from_pools(game_state, target["id"])
            
            # CRITICAL: Remove dead target from valid_target_pool for all active shooting units
            # Simply remove the dead target ID from each unit's pool (no need to rebuild)
            target_id_str = str(target["id"])
            if "shoot_activation_pool" in game_state:
                for active_unit_id in game_state["shoot_activation_pool"]:
                    active_unit = _get_unit_by_id(game_state, active_unit_id)
                    if active_unit and active_unit.get("HP_CUR", 0) > 0:
                        # Remove dead target from this unit's valid_target_pool
                        if "valid_target_pool" in active_unit:
                            pool_before = len(active_unit["valid_target_pool"])
                            active_unit["valid_target_pool"] = [
                                tid for tid in active_unit["valid_target_pool"] 
                                if str(tid) != target_id_str
                            ]
                            pool_after = len(active_unit["valid_target_pool"])
                            if pool_before != pool_after:
                                add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} target_died: Removed dead target {target_id_str} from Unit {active_unit_id} pool (before={pool_before}, after={pool_after})")

    # Store pre-damage HP in attack_result for reward calculation
    attack_result["target_hp_before_damage"] = target_hp_before_damage
    
    # Store detailed log for frontend display with location data
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get weapon_name before building message
    weapon_name = attack_result.get("weapon_name", "")
    weapon_suffix = f" with [{weapon_name}]" if weapon_name else ""
    
    # CRITICAL: Validate weapon matches unit type (detect unit type/weapon mismatches)
    # This detects cases where a Space Marine unit uses Tyranid weapons or vice versa
    if weapon_name:
        shooter_unit_type = shooter.get("unitType", "")
        # Check if weapon faction doesn't match unit faction
        tyranid_weapons = ['deathspitter', 'fleshborer', 'devourer', 'scything talons', 'bonesword', 'lash whip']
        space_marine_weapons = ['bolt rifle', 'bolt pistol', 'chainsword', 'power sword', 'power fist', 'stalker bolt rifle']
        
        weapon_name_lower = weapon_name.lower()
        weapon_is_tyranid = any(tyranid_wpn in weapon_name_lower for tyranid_wpn in tyranid_weapons)
        weapon_is_space_marine = any(sm_wpn in weapon_name_lower for sm_wpn in space_marine_weapons)
        
        unit_is_space_marine = 'intercessor' in shooter_unit_type.lower() or 'captain' in shooter_unit_type.lower() or 'spacemarine' in shooter_unit_type.lower()
        unit_is_tyranid = 'tyranid' in shooter_unit_type.lower() or 'genestealer' in shooter_unit_type.lower() or 'hormagaunt' in shooter_unit_type.lower() or 'termagant' in shooter_unit_type.lower()
        
        # If weapon faction doesn't match unit faction, log as critical bug
        if (weapon_is_tyranid and unit_is_space_marine) or (weapon_is_space_marine and unit_is_tyranid):
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_console_log, add_debug_log, safe_print
            log_msg = f"[CRITICAL WEAPON BUG] E{episode} T{turn} shooting_attack_controller: Unit {unit_id} (type={shooter_unit_type}, player={shooter.get('player')}) using weapon={weapon_name} - WEAPON/TYPE MISMATCH!"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            import logging
            logging.basicConfig(filename='step.log', level=logging.INFO, format='%(message)s')
            logging.info(log_msg)
    
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
        "shooterCol": get_unit_coordinates(shooter)[0],
        "shooterRow": get_unit_coordinates(shooter)[1],
        "targetCol": get_unit_coordinates(target)[0],
        "targetRow": get_unit_coordinates(target)[1],
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
    
    # DEBUG: Log shooting attack execution
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        damage = attack_result.get("damage", 0)
        target_died = attack_result.get("target_died", False)
        log_msg = f"[SHOOT DEBUG] E{episode} T{turn} shoot attack_executed: Unit {unit_id} -> Unit {target_id} damage={damage} target_died={target_died}"
        from engine.game_utils import add_console_log, add_debug_log
        from engine.game_utils import safe_print
        add_debug_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    # Calculate reward for this action using progressive bonus system
    # OPTIMIZATION: Only calculate rewards for controlled player's units
    # Bot units don't need rewards since they don't learn
    config = game_state.get("config", {})
    controlled_player = config.get("controlled_player", 1)

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
                    pass

        except Exception as e:
            pass
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
    
    # Hit roll -> hit_roll >= weapon.ATK
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
    
    # HIT -> Continue to wound roll
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
    
    # WOUND -> Continue to save roll
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
    
    # FAIL -> Continue to damage
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
    Postpone current unit (if hasn't shot) and activate new unit
    """
    # Postpone current unit activation (clear active unit, keep in pool)
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if current_unit:
        # Clear active unit but don't remove from pool
        if "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
    
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
    """
    Check if unit is adjacent to enemy within melee range.
    
    PERFORMANCE: Uses cached enemy_adjacent_hexes if available (O(1) lookup),
    otherwise falls back to iterating enemies (O(n)).
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers (melee range is always 1)
    """
    from engine.utils.weapon_helpers import get_melee_range
    cc_range = get_melee_range()  # Always 1
    
    # CRITICAL FIX: Check adjacency using current positions from game_state["units"]
    # The cache built at phase start may be stale if unit positions changed after movement.
    # Always use current positions for accurate adjacency checks.
    unit_col, unit_row = get_unit_coordinates(unit)
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    
    # Check if unit is adjacent to any enemy using current positions
    for enemy in game_state["units"]:
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        if enemy_player != unit_player and enemy["HP_CUR"] > 0:
            enemy_col, enemy_row = get_unit_coordinates(enemy)
            distance = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
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

    # CRITICAL: Normalize player value to int for consistent comparison
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    for enemy in game_state["units"]:
        # CRITICAL: Normalize player value to int for consistent comparison
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        if enemy_player != unit_player and enemy["HP_CUR"] > 0:
            unit_col, unit_row = get_unit_coordinates(unit)
            enemy_col, enemy_row = get_unit_coordinates(enemy)
            distance = _calculate_hex_distance(unit_col, unit_row, enemy_col, enemy_row)
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
    from engine.combat_utils import get_hex_neighbors, is_hex_adjacent_to_enemy
    from engine.phase_handlers.movement_handlers import (
        movement_build_valid_destinations_pool,
        _is_traversable_hex
    )
    from .shared_utils import build_enemy_adjacent_hexes
    
    unit_id = unit["id"]
    orig_col, orig_row = get_unit_coordinates(unit)
    
    # CRITICAL: Cannot advance if unit has already shot -> SKIP (agent cannot act)
    has_shot = _unit_has_shot_with_any_weapon(unit)
    if has_shot:
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["advance_rejected"] = True
        result["error"] = "cannot_advance_after_shooting"
        return success, result

    # CRITICAL: Cannot advance if unit is adjacent to enemy -> SKIP (agent cannot act)
    # Pool is source of truth: if can_advance is False, unit cannot advance
    can_advance = unit.get("_can_advance", None)
    if can_advance is False:
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["advance_rejected"] = True
        result["error"] = "cannot_advance_adjacent_to_enemy"
        return success, result
    
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
        # CRITICAL: Convert coordinates to int for consistent tuple comparison
        dest_col, dest_row = int(dest_col), int(dest_row)
        
        # Destination provided - validate and execute
        if (dest_col, dest_row) not in valid_destinations:
            return False, {"error": "invalid_advance_destination", "destination": (dest_col, dest_row)}
        
        # CRITICAL: Final occupation check IMMEDIATELY before position assignment
        # This prevents race conditions where multiple units select the same destination
        # before any of them have moved. Must check JUST before assignment, not earlier.
        dest_col_int, dest_row_int = int(dest_col), int(dest_row)
        
        # DEBUG: Log occupation check for debugging collisions
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "shoot")
        from engine.game_utils import conditional_debug_print
        conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Unit {unit['id']} checking advance destination ({dest_col_int},{dest_row_int})")
        
        # Check all units for occupation - CRITICAL: Use explicit int conversion for all comparisons
        for check_unit in game_state["units"]:
            # CRITICAL: Normalize coordinates for consistent comparison
            # This prevents type mismatch bugs (int vs float vs string)
            try:
                check_col, check_row = get_unit_coordinates(check_unit)
            except (ValueError, TypeError, KeyError):
                # Skip units with invalid positions (should not happen, but defensive)
                continue
            
            conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Checking Unit {check_unit['id']} at ({check_col},{check_row}) - HP={check_unit['HP_CUR']}")
            
            # CRITICAL: Compare as integers to avoid type mismatch
            if (check_unit["id"] != unit["id"] and
                check_unit["HP_CUR"] > 0 and
                check_col == dest_col_int and
                check_row == dest_row_int):
                # Another unit already occupies this destination - prevent collision
                if "console_logs" not in game_state:
                    game_state["console_logs"] = []
                log_msg = f"[ADVANCE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot advance to ({dest_col_int},{dest_row_int}) - occupied by Unit {check_unit['id']}"
                from engine.game_utils import add_console_log, add_debug_log
                from engine.game_utils import safe_print
                add_console_log(game_state, log_msg)
                safe_print(game_state, log_msg)
                return False, {
                    "error": "advance_destination_occupied",
                    "occupant_id": check_unit["id"],
                    "destination": (dest_col, dest_row)
                }
        
        conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Unit {unit['id']} advance destination ({dest_col_int},{dest_row_int}) is FREE - proceeding with advance")
        
        # Execute advance movement
        # CRITICAL: Log ALL position changes to detect unauthorized modifications
        # CRITICAL: Log ALL position changes to detect unauthorized modifications
        # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "shoot")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col},{dest_row}) via ADVANCE"
        from engine.game_utils import add_console_log, add_debug_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)
        
        # CRITICAL: Log BEFORE each assignment to catch any modification
        from engine.game_utils import conditional_debug_print
        dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
        from engine.combat_utils import set_unit_coordinates
        set_unit_coordinates(unit, dest_col_int, dest_row_int)
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")
        
        # Check if unit actually moved (for cache invalidation and logging)
        actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
        
        # CRITICAL: Invalidate LoS cache ONLY if unit actually moved
        # The unit's position changed, so LoS cache entries are now stale
        if actually_moved:
            # CRITICAL: Invalidate LoS cache when unit advances (moves)
            _invalidate_los_cache_for_moved_unit(game_state, unit["id"])
            
            # AI_TURN.md STEP 4: Rebuild unit's los_cache with new position after advance
            # CRITICAL: Rebuild unit-local cache (not global cache) with new position
            build_unit_los_cache(game_state, unit["id"])
            
            # CRITICAL: Invalidate all destination pools after advance movement
            # Positions have changed, so all pools (move, charge, shoot) are now stale
            from .movement_handlers import _invalidate_all_destination_pools_after_movement
            _invalidate_all_destination_pools_after_movement(game_state)
        
        # CRITICAL FIX: Mark unit as advanced REGARDLESS of whether it moved
        # Units must be marked as advanced even if they stay in place (for ASSAULT weapon rule)
        # AI_TURN.md ligne 666: Log: end_activation(ACTION, 1, ADVANCE, SHOOTING, 0)
        # This marks units_advanced (ligne 665 describes what this does)
        # arg5=0 means NOT_REMOVED (do not remove from pool, do not end activation)
        # We track the advance but continue to shooting, so we don't use the return value
        # CRITICAL: Call end_activation directly (not _handle_shooting_end_activation) because:
        # 1. arg5=0 means NOT_REMOVED - we don't want to clear activation state
        # 2. We don't want to trigger phase_complete check
        # 3. This is just a tracking/logging call, not an actual activation end
        from engine.phase_handlers.generic_handlers import end_activation
        end_activation(game_state, unit, ACTION, 1, ADVANCE, NOT_REMOVED, 0)
        
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
        
        # Clean up advance state AFTER logging
        if "advance_range" in unit:
            del unit["advance_range"]
        
        # AI_TURN.md STEP 4: ADVANCE_ACTION post-advance logic (lines 666-679)
        # Continue only if unit actually moved
        if not actually_moved:
            # Unit did not advance -> Go back to STEP 3: ACTION_SELECTION
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
        
        # CRITICAL: Call weapon_availability_check FIRST to get usable weapons
        # Then rebuild valid_target_pool using those usable weapons
        weapon_rule = game_state.get("weapon_rule", 0)
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status=1, adjacent_status=0
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        
        # CRITICAL: Rebuild valid_target_pool using shooting_build_valid_target_pool for consistency
        # This wrapper automatically determines context (advance_status=1 after advance, adjacent_status=0)
        # and handles cache correctly
        valid_target_pool = shooting_build_valid_target_pool(game_state, unit_id)
        unit["valid_target_pool"] = valid_target_pool
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
        
        # valid_target_pool NOT empty AND CAN_SHOOT = true?
        if valid_target_pool and can_shoot:
            # YES -> SHOOTING ACTIONS AVAILABLE (post-advance) -> Go to STEP 5: ADVANCED_SHOOTING_ACTION_SELECTION
            # Mark unit as currently active (required for frontend to show weapon icon)
            game_state["active_shooting_unit"] = unit_id
            # Return advance action so it gets logged as its own step
            return True, {
                "action": "advance",
                "unitId": unit_id,
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_range,
                "actually_moved": actually_moved
            }
        else:
            # NO -> Unit advanced but no valid targets -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
            # arg3="ADVANCE", arg4="SHOOTING", arg5=1 (remove from pool)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1, action_type="advance")
            result.update({
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_range,
                "actually_moved": actually_moved
            })
            return success, result
    else:
        # No destination - return valid destinations for player/AI to choose
        # For AI, auto-select best destination
        is_gym_training = config.get("gym_training_mode", False)
        is_pve_ai = config.get("pve_mode", False) and unit["player"] == 2
        
        if (is_gym_training or is_pve_ai) and valid_destinations:
            # Auto-select: move toward nearest enemy (aggressive strategy)
            enemies = [u for u in game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
            
            if enemies:
                unit_col, unit_row = get_unit_coordinates(unit)
                nearest_enemy = min(enemies, key=lambda e: _calculate_hex_distance(unit_col, unit_row, *get_unit_coordinates(e)))
                nearest_enemy_col, nearest_enemy_row = get_unit_coordinates(nearest_enemy)
                best_dest = min(valid_destinations, key=lambda d: _calculate_hex_distance(d[0], d[1], nearest_enemy_col, nearest_enemy_row))
            else:
                best_dest = valid_destinations[0] if valid_destinations else (orig_col, orig_row)
            
            # Recursively call with destination
            action["destCol"] = best_dest[0]
            action["destRow"] = best_dest[1]
            return _handle_advance_action(game_state, unit, action, config)
        
        # CRITICAL FIX: If no valid destinations in gym training, end activation to prevent infinite loop
        if (is_gym_training or is_pve_ai) and not valid_destinations:
            # No valid destinations - SKIP (cannot advance)
            success, result = _handle_shooting_end_activation(
                game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
            )
            result["advance_rejected"] = True
            result["error"] = "no_valid_advance_destinations"
            return success, result
        
        # Human player - return destinations for UI
        # ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Use advance_destinations and advance_roll names
        # to match frontend expectations in useEngineAPI.ts (lines ~330-340)
        return True, {
            "waiting_for_player": True,
            "action": "advance_select_destination",
            "unitId": unit_id,
            "advance_roll": advance_range,
            "advance_destinations": [{"col": (norm_coords := normalize_coordinates(d[0], d[1]))[0], "row": norm_coords[1]} for d in valid_destinations],
            "highlight_color": "orange"
        }
