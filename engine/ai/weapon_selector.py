"""
Weapon Selector - AI weapon selection based on kill probability

MULTIPLE_WEAPONS_IMPLEMENTATION.md: Automatic weapon selection for AI
"""

from typing import Dict, List, Any, Tuple, Optional
from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance


def calculate_kill_probability(unit: Dict[str, Any], weapon: Dict[str, Any], 
                                target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """
    Calculate kill probability for a specific weapon against a target.
    Simple, standalone function - pas de dépendance complexe.
    
    AI_IMPLEMENTATION.md COMPLIANCE: No defaults - raise error if required data missing.
    """
    # Extraire stats de l'arme - NO DEFAULT, raise error si manquant
    hit_target = require_key(weapon, "ATK")
    strength = require_key(weapon, "STR")
    damage = require_key(weapon, "DMG")
    num_attacks = require_key(weapon, "NB")
    ap = require_key(weapon, "AP")
    
    # Calculs W40K standard
    p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
    
    # Wound probability - NO DEFAULT, raise error si T manquant
    toughness = require_key(target, "T")
    if strength >= toughness * 2:
        p_wound = 5/6
    elif strength > toughness:
        p_wound = 4/6
    elif strength == toughness:
        p_wound = 3/6
    else:
        p_wound = 2/6
    
    # Save probability
    # ARMOR_SAVE et INVUL_SAVE peuvent être optionnels (certaines unités n'ont pas d'invul save)
    # Utiliser .get() avec default raisonnable pour ces champs optionnels
    armor_save = target.get("ARMOR_SAVE", 7)  # Default 7 = pas de save
    invul_save = target.get("INVUL_SAVE", 7)  # Default 7 = pas d'invul save
    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
    
    # Expected damage
    p_damage_per_attack = p_hit * p_wound * p_fail_save
    expected_damage = num_attacks * p_damage_per_attack * damage
    
    # Kill probability - NO DEFAULT, raise error si HP_CUR manquant
    hp_cur = require_key(target, "HP_CUR")
    if expected_damage >= hp_cur:
        return 1.0
    else:
        return min(1.0, expected_damage / hp_cur)


def _get_cache_key(unit_id: str, weapon_index: int, target_id: str, hp_cur: int) -> Tuple[str, int, str, int]:
    """Generate cache key for kill probability."""
    return (unit_id, weapon_index, target_id, hp_cur)


def _get_kill_prob_from_cache(cache: Dict[Tuple[str, int, str, int], float],
                               unit_id: str, weapon_index: int, target_id: str, hp_cur: int) -> Optional[float]:
    """Get kill probability from cache if available."""
    cache_key = _get_cache_key(unit_id, weapon_index, target_id, hp_cur)
    return cache.get(cache_key)


def _store_kill_prob_in_cache(cache: Dict[Tuple[str, int, str, int], float],
                               unit_id: str, weapon_index: int, target_id: str, hp_cur: int, kill_prob: float):
    """Store kill probability in cache."""
    cache_key = _get_cache_key(unit_id, weapon_index, target_id, hp_cur)
    cache[cache_key] = kill_prob


def select_best_ranged_weapon(unit: Dict[str, Any], target: Dict[str, Any], 
                               game_state: Dict[str, Any]) -> int:
    """
    Select best ranged weapon for target based on kill probability.
    
    Args:
        unit: Attacking unit with RNG_WEAPONS
        target: Target unit
        game_state: Game state (for cache access)
        
    Returns:
        Index of best weapon, or -1 if no weapons available
        
    Raises:
        KeyError: If RNG_WEAPONS missing or empty
    """
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing RNG_WEAPONS: {unit}")
    
    rng_weapons = unit.get("RNG_WEAPONS", [])
    if not rng_weapons:
        return -1
    
    # Get cache if available
    cache = game_state.get("kill_probability_cache", {})
    
    best_index = -1
    best_kill_prob = -1.0
    
    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = target.get("HP_CUR", target.get("HP_MAX", 1))
    
    for weapon_index, weapon in enumerate(rng_weapons):
        # Check cache first
        cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
        
        if cached_prob is not None:
            kill_prob = cached_prob
        else:
            # Calculate kill probability
            kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
            # Store in cache
            _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
        
        # Tie-breaking: index le plus bas en cas d'égalité
        if kill_prob > best_kill_prob or (kill_prob == best_kill_prob and best_index == -1):
            best_kill_prob = kill_prob
            best_index = weapon_index
    
    return best_index


def select_best_melee_weapon(unit: Dict[str, Any], target: Dict[str, Any], 
                              game_state: Dict[str, Any]) -> int:
    """
    Select best melee weapon for target based on kill probability.
    
    Args:
        unit: Attacking unit with CC_WEAPONS
        target: Target unit
        game_state: Game state (for cache access)
        
    Returns:
        Index of best weapon, or -1 if no weapons available
        
    Raises:
        KeyError: If CC_WEAPONS missing or empty
    """
    if "CC_WEAPONS" not in unit:
        raise KeyError(f"Unit missing CC_WEAPONS: {unit}")
    
    cc_weapons = unit.get("CC_WEAPONS", [])
    if not cc_weapons:
        return -1
    
    # Get cache if available
    cache = game_state.get("kill_probability_cache", {})
    
    best_index = -1
    best_kill_prob = -1.0
    
    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = target.get("HP_CUR", target.get("HP_MAX", 1))
    
    for weapon_index, weapon in enumerate(cc_weapons):
        # Check cache first
        cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
        
        if cached_prob is not None:
            kill_prob = cached_prob
        else:
            # Calculate kill probability
            kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
            # Store in cache
            _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
        
        # Tie-breaking: index le plus bas en cas d'égalité
        if kill_prob > best_kill_prob or (kill_prob == best_kill_prob and best_index == -1):
            best_kill_prob = kill_prob
            best_index = weapon_index
    
    return best_index


def get_best_weapon_for_target(unit: Dict[str, Any], target: Dict[str, Any], 
                                game_state: Dict[str, Any], is_ranged: bool) -> Tuple[int, float]:
    """
    Get best weapon for target and its kill probability.
    Used for observation space.
    
    Args:
        unit: Attacking unit
        target: Target unit
        game_state: Game state (for cache access)
        is_ranged: True for ranged weapons, False for melee
        
    Returns:
        Tuple of (weapon_index, kill_probability)
        Returns (-1, 0.0) if no weapons available
    """
    if is_ranged:
        weapon_index = select_best_ranged_weapon(unit, target, game_state)
    else:
        weapon_index = select_best_melee_weapon(unit, target, game_state)
    
    if weapon_index < 0:
        return (-1, 0.0)
    
    # Get kill probability from cache or calculate
    cache = game_state.get("kill_probability_cache", {})
    unit_id = str(unit["id"])
    target_id = str(target["id"])
    hp_cur = target.get("HP_CUR", target.get("HP_MAX", 1))
    
    if is_ranged:
        weapons = unit.get("RNG_WEAPONS", [])
    else:
        weapons = unit.get("CC_WEAPONS", [])
    
    if weapon_index >= len(weapons):
        return (-1, 0.0)
    
    weapon = weapons[weapon_index]
    
    # Check cache first
    cached_prob = _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur)
    if cached_prob is not None:
        return (weapon_index, cached_prob)
    
    # Calculate if not in cache
    kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
    _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)
    
    return (weapon_index, kill_prob)


def precompute_kill_probability_cache(game_state: Dict[str, Any], phase: str):
    """
    Pre-compute kill probability cache for all active units × all targets × all weapons.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Called in shooting_phase_start() and fight_phase_start()
    after activation pools are created.
    
    Args:
        game_state: Game state with units
        phase: "shoot" or "fight"
    """
    if "units" not in game_state:
        return
    
    # Initialize cache if not exists
    if "kill_probability_cache" not in game_state:
        game_state["kill_probability_cache"] = {}
    
    cache = game_state["kill_probability_cache"]
    current_player = game_state.get("current_player", 1)
    
    # Get active units (current player's units)
    active_units = [u for u in game_state["units"] if u.get("player") == current_player and u.get("HP_CUR", 0) > 0]
    
    # Get all enemy units as targets
    enemy_units = [u for u in game_state["units"] if u.get("player") != current_player and u.get("HP_CUR", 0) > 0]
    
    for unit in active_units:
        unit_id = str(unit["id"])
        
        # Get weapons based on phase
        if phase == "shoot":
            weapons = unit.get("RNG_WEAPONS", [])
        elif phase == "fight":
            weapons = unit.get("CC_WEAPONS", [])
        else:
            continue
        
        if not weapons:
            continue
        
        for weapon_index, weapon in enumerate(weapons):
            for target in enemy_units:
                target_id = str(target["id"])
                hp_cur = target.get("HP_CUR", target.get("HP_MAX", 1))
                
                # Calculate and cache
                kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
                _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)


def invalidate_cache_for_target(cache: Dict[Tuple[str, int, str, int], float], target_id: str):
    """
    Invalidate all cache entries for a specific target.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Called after damage is dealt to a unit.
    
    Args:
        cache: Kill probability cache
        target_id: ID of target unit (as string)
    """
    keys_to_remove = [key for key in cache.keys() if key[2] == target_id]
    for key in keys_to_remove:
        del cache[key]


def invalidate_cache_for_unit(cache: Dict[Tuple[str, int, str, int], float], unit_id: str):
    """
    Invalidate all cache entries for a specific unit (unit died, can't attack anymore).
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Called when unit dies.
    
    Args:
        cache: Kill probability cache
        unit_id: ID of unit (as string)
    """
    keys_to_remove = [key for key in cache.keys() if key[0] == unit_id]
    for key in keys_to_remove:
        del cache[key]


def recompute_cache_for_new_units_in_range(game_state: Dict[str, Any]):
    """
    Recompute cache for units that entered perception_radius after movement.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Called in movement_phase_end()
    
    Args:
        game_state: Game state with units
    """
    if "units" not in game_state:
        return
    
    perception_radius = game_state.get("perception_radius", 25)
    current_player = game_state.get("current_player", 1)
    
    # Get active units
    active_units = [u for u in game_state["units"] if u.get("player") == current_player and u.get("HP_CUR", 0) > 0]
    
    # Get all enemy units
    enemy_units = [u for u in game_state["units"] if u.get("player") != current_player and u.get("HP_CUR", 0) > 0]
    
    cache = game_state.get("kill_probability_cache", {})
    
    for unit in active_units:
        unit_id = str(unit["id"])
        # CRITICAL: No default values - require explicit coordinates
        if "col" not in unit or "row" not in unit:
            raise ValueError(f"Unit {unit_id} missing coordinates: has_col={'col' in unit}, has_row={'row' in unit}")
        unit_col = int(unit["col"])
        unit_row = int(unit["row"])
        
        rng_weapons = unit.get("RNG_WEAPONS", [])
        
        for weapon_index, weapon in enumerate(rng_weapons):
            weapon_range = weapon.get("RNG", 0)
            
            for target in enemy_units:
                target_id = str(target["id"])
                # CRITICAL: No default values - require explicit coordinates
                if "col" not in target or "row" not in target:
                    raise ValueError(f"Target {target_id} missing coordinates: has_col={'col' in target}, has_row={'row' in target}")
                target_col = int(target["col"])
                target_row = int(target["row"])
                
                # Check if target is in range
                distance = calculate_hex_distance(unit_col, unit_row, target_col, target_row)
                
                if distance <= perception_radius and distance <= weapon_range:
                    hp_cur = target.get("HP_CUR", target.get("HP_MAX", 1))
                    
                    # Check if already cached
                    if _get_kill_prob_from_cache(cache, unit_id, weapon_index, target_id, hp_cur) is None:
                        # Calculate and cache
                        kill_prob = calculate_kill_probability(unit, weapon, target, game_state)
                        _store_kill_prob_in_cache(cache, unit_id, weapon_index, target_id, hp_cur, kill_prob)


def calculate_ttk_with_weapon(unit: Dict[str, Any], weapon: Dict[str, Any],
                              target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """
    Calculate Time-To-Kill (turns) for a specific weapon against a target.
    Returns: Number of turns (activations) needed to kill target, or 100.0 if can't kill.
    
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Helper function for Features 16-17 improvements.
    """
    # Calculer expected_damage avec cette arme
    hit_target = require_key(weapon, "ATK")
    strength = require_key(weapon, "STR")
    damage = require_key(weapon, "DMG")
    num_attacks = require_key(weapon, "NB")
    ap = require_key(weapon, "AP")
    
    # Calculs W40K standard
    p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
    
    toughness = require_key(target, "T")
    if strength >= toughness * 2:
        p_wound = 5/6
    elif strength > toughness:
        p_wound = 4/6
    elif strength == toughness:
        p_wound = 3/6
    else:
        p_wound = 2/6
    
    armor_save = target.get("ARMOR_SAVE", 7)
    invul_save = target.get("INVUL_SAVE", 7)
    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
    
    # Expected damage
    p_damage_per_attack = p_hit * p_wound * p_fail_save
    expected_damage = num_attacks * p_damage_per_attack * damage
    
    if expected_damage <= 0:
        return 100.0  # Can't kill
    
    hp_cur = require_key(target, "HP_CUR")
    return hp_cur / expected_damage
