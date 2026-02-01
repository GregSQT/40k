#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import Dict, List, Tuple, Set, Optional, Any, Union

from shared.data_validation import require_key
from engine.combat_utils import get_unit_coordinates, normalize_coordinates, calculate_hex_distance, get_hex_neighbors

# end_activation / _handle_shooting_end_activation argument constants (AI_TURN.md)
ACTION = "ACTION"
WAIT = "WAIT"
NO = "NO"
PASS = "PASS"
ERROR = "ERROR"
MOVE = "MOVE"
SHOOTING = "SHOOTING"
CHARGE = "CHARGE"
FIGHT = "FIGHT"
FLED = "FLED"
ADVANCE = "ADVANCE"
NOT_REMOVED = "NOT_REMOVED"


# =============================================================================
# UNITS_CACHE - Single source of truth for position, HP, player of living units
# =============================================================================

def build_units_cache(game_state: Dict[str, Any]) -> None:
    """
    Build units_cache from game_state["units"].
    
    Creates game_state["units_cache"]: Dict[str, Dict] mapping unit_id (str) to
    {"col": int, "row": int, "HP_CUR": int, "player": int} for all units in game_state["units"].
    During gameplay, dead units are removed from cache (update_units_cache_hp calls remove_from_units_cache when HP <= 0).
    
    Called ONCE at reset() after units are initialized. Not called at phase start.
    
    Args:
        game_state: Game state with "units" list
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units" not in game_state:
        raise KeyError("game_state must have 'units' field to build units_cache")
    
    units_cache: Dict[str, Dict[str, Any]] = {}
    
    for unit in game_state["units"]:
        hp_cur_raw = require_key(unit, "HP_CUR")
        try:
            hp_cur = max(0, int(float(hp_cur_raw)))
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit.get('id')} has invalid HP_CUR: {hp_cur_raw!r}") from None
        
        unit_id = str(require_key(unit, "id"))
        col, row = get_unit_coordinates(unit)  # Already normalizes
        player_raw = require_key(unit, "player")
        try:
            player = int(player_raw)
        except (ValueError, TypeError):
            raise ValueError(f"Unit {unit_id} has invalid player: {player_raw!r}") from None
        
        units_cache[unit_id] = {
            "col": col,
            "row": row,
            "HP_CUR": hp_cur,
            "player": player
        }
    
    game_state["units_cache"] = units_cache


def update_units_cache_unit(
    game_state: Dict[str, Any],
    unit_id: str,
    col: int,
    row: int,
    hp_cur: int,
    player: int
) -> None:
    """
    Update or insert a unit entry in units_cache.
    
    If hp_cur <= 0, removes the entry (unit dead; single source of truth).
    Coordinates are normalized before storage.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: Column coordinate
        row: Row coordinate
        hp_cur: Current HP (0 for dead)
        player: Player number (1 or 2)
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before updating (call build_units_cache at reset)")
    
    # Normalize coordinates
    norm_col, norm_row = normalize_coordinates(col, row)
    effective_hp = max(0, int(hp_cur))
    
    # Update or insert (if hp_cur <= 0, remove instead)
    if effective_hp <= 0:
        remove_from_units_cache(game_state, unit_id)
        return
    game_state["units_cache"][unit_id] = {
        "col": norm_col,
        "row": norm_row,
        "HP_CUR": effective_hp,
        "player": player
    }


def _remove_unit_from_all_activation_pools(game_state: Dict[str, Any], unit_id_str: str) -> None:
    """
    Remove a unit from all activation pools (move, shoot, charge, fight).
    Called when unit dies so pools never contain dead units (single source of truth).
    """
    for pool_key in (
        "move_activation_pool",
        "shoot_activation_pool",
        "charge_activation_pool",
        "charging_activation_pool",
        "active_alternating_activation_pool",
        "non_active_alternating_activation_pool",
    ):
        if pool_key in game_state and game_state[pool_key] is not None:
            game_state[pool_key] = [uid for uid in game_state[pool_key] if str(uid) != unit_id_str]


def remove_from_units_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Remove a unit from units_cache (e.g. when unit dies: HP_CUR -> 0).
    
    Dead = absent from cache (single source of truth). Call from update_units_cache_hp when HP <= 0.
    Also removes the unit from all activation pools so pools never contain dead units.
    No-op if unit_id is not in cache.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str) to remove
        
    Returns:
        None (updates game_state["units_cache"] and activation pools)
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist before removing (call build_units_cache at reset)")
    
    game_state["units_cache"].pop(unit_id, None)
    _remove_unit_from_all_activation_pools(game_state, str(unit_id))


def get_unit_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get unit entry from units_cache.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        Dict with {"col", "row", "HP_CUR", "player"} if unit is in cache, None otherwise.
        Dead units are removed from cache (absent).
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id)


def is_unit_alive(unit_id: str, game_state: Dict[str, Any]) -> bool:
    """
    Check if a unit is alive (present in units_cache).
    
    units_cache contains ONLY living units; dead units are removed at end of action.
    
    Args:
        unit_id: Unit ID (str)
        game_state: Game state with "units_cache"
        
    Returns:
        True if unit is in cache, False otherwise
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    return game_state["units_cache"].get(unit_id) is not None


def _get_unit_position_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """
    Internal: get unit position from units_cache by unit_id.
    Use get_unit_position() for the public API.
    """
    entry = get_unit_from_cache(unit_id, game_state)
    if entry is None:
        return None
    return (entry["col"], entry["row"])


def get_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Optional[Tuple[int, int]]:
    """
    Get current position of a unit from units_cache (single source of truth).
    Use this for any game logic that needs unit position when game_state is available.

    Args:
        unit_or_id: Unit ID (str or int) or unit dict (must have "id").
        game_state: Game state with "units_cache".

    Returns:
        (col, row) if unit is in cache, None if unit not in cache (e.g. dead/removed).

    Raises:
        ValueError: If unit_or_id is a dict without "id" (e.g. units_cache entry passed by mistake).
    """
    if isinstance(unit_or_id, dict):
        if "id" not in unit_or_id:
            raise ValueError(
                "get_unit_position received a dict without 'id' (possibly a units_cache entry). "
                "Pass a unit dict with 'id' or a unit ID (str/int)."
            )
        unit_id = str(require_key(unit_or_id, "id"))
    else:
        unit_id = str(unit_or_id)
    return _get_unit_position_from_cache(unit_id, game_state)


def require_unit_position(
    unit_or_id: Union[str, int, Dict[str, Any]], game_state: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Get current position of a unit from units_cache; raises if unit not in cache.
    Use when the unit is required to be present (e.g. shooter, active unit).

    Returns:
        (col, row)

    Raises:
        ValueError: If unit not in units_cache (dead/absent).
    """
    pos = get_unit_position(unit_or_id, game_state)
    if pos is None:
        uid = str(unit_or_id.get("id", unit_or_id)) if isinstance(unit_or_id, dict) else str(unit_or_id)
        raise ValueError(f"Unit {uid} not in units_cache (dead or absent); cannot read position")
    return pos


def update_units_cache_position(game_state: Dict[str, Any], unit_id: str, col: int, row: int) -> None:
    """
    Update only the position of a unit in units_cache.
    
    Convenience function for use after set_unit_coordinates.
    Retrieves HP_CUR and player from existing entry.
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        col: New column coordinate
        row: New row coordinate
        
    Returns:
        None (updates game_state["units_cache"])
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    entry = game_state["units_cache"].get(unit_id)
    if entry is None:
        # Unit not in cache - no-op
        return
    
    # Normalize coordinates
    norm_col, norm_row = normalize_coordinates(col, row)
    
    entry["col"] = norm_col
    entry["row"] = norm_row


def get_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> Optional[int]:
    """
    Get current HP of a unit from units_cache (Phase 2: single source of truth for HP_CUR).
    
    units_cache contains ONLY living units; dead units are removed. Returns None if unit not in cache.
    
    Returns:
        HP value if unit is in cache, None if unit not in cache (dead or absent).
    """
    entry = get_unit_from_cache(str(unit_id), game_state)
    if entry is None:
        return None
    return require_key(entry, "HP_CUR")


def require_hp_from_cache(unit_id: str, game_state: Dict[str, Any]) -> int:
    """
    Return current HP for a unit that must be alive (in units_cache).
    Raises ValueError if unit is dead or absent.
    """
    hp = get_hp_from_cache(str(unit_id), game_state)
    if hp is None:
        raise ValueError(f"Unit {unit_id} not in units_cache (dead or absent); cannot read HP_CUR")
    return hp


def update_units_cache_hp(game_state: Dict[str, Any], unit_id: str, new_hp_cur: int) -> None:
    """
    Single write path for HP_CUR during gameplay: updates units_cache only (Phase 2).
    
    Use this as the ONLY write path for HP_CUR during gameplay (shooting, fight).
    At reset, HP_CUR is initialised from definitions; build_units_cache reads from units.
    
    units_cache contains ONLY living units. If new_hp_cur <= 0, unit is removed from cache
    immediately (end of action).
    
    Args:
        game_state: Game state with "units_cache"
        unit_id: Unit ID (str)
        new_hp_cur: New HP value (will be clamped to >= 0)
        
    Returns:
        None (updates game_state["units_cache"] only)
    """
    require_key(game_state, "units_cache")
    
    effective_hp = max(0, int(new_hp_cur))
    unit_id_str = str(unit_id)
    
    entry = game_state["units_cache"].get(unit_id_str)
    if entry is None:
        return
    if effective_hp <= 0:
        remove_from_units_cache(game_state, unit_id_str)
    else:
        entry["HP_CUR"] = effective_hp


def check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Check if any friendly melee unit can charge this target."""
    current_player = game_state["current_player"]
    
    units_cache = require_key(game_state, "units_cache")
    unit_by_id = {str(u["id"]): u for u in game_state["units"]}
    for unit_id, entry in units_cache.items():
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if entry["player"] == current_player:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            from engine.utils.weapon_helpers import get_selected_melee_weapon
            has_melee = False
            if unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                melee_weapon = get_selected_melee_weapon(unit)
                if melee_weapon and require_key(melee_weapon, "DMG") > 0:
                    has_melee = True
            if has_melee:  # Has melee capability
                unit_pos = get_unit_position(unit, game_state)
                target_pos = get_unit_position(target, game_state)
                if unit_pos is None or target_pos is None:
                    continue
                # Estimate charge range (unit move + average 2d6)
                distance = calculate_hex_distance(*unit_pos, *target_pos)
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                config = require_key(game_state, "config")
                game_rules = require_key(config, "game_rules")
                avg_charge_roll = require_key(game_rules, "avg_charge_roll")
                max_charge = unit["MOVE"] + avg_charge_roll
                if distance <= max_charge:
                    return True
    
    return False


def calculate_target_priority_score(unit: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """Calculate target priority score using AI_GAME_OVERVIEW.md logic.
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_DMG/CC_DMG
    """
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max DMG from all weapons
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Calculate max threat from target's weapons
    target_rng_weapon = get_selected_ranged_weapon(target)
    target_cc_weapon = get_selected_melee_weapon(target)
    target_rng_dmg = require_key(target_rng_weapon, "DMG") if target_rng_weapon else 0
    target_cc_dmg = require_key(target_cc_weapon, "DMG") if target_cc_weapon else 0
    # Also check all weapons for max threat
    if target.get("RNG_WEAPONS"):
        target_rng_dmg = max(target_rng_dmg, max(require_key(w, "DMG") for w in target["RNG_WEAPONS"]))
    if target.get("CC_WEAPONS"):
        target_cc_dmg = max(target_cc_dmg, max(require_key(w, "DMG") for w in target["CC_WEAPONS"]))
    
    threat_level = max(target_rng_dmg, target_cc_dmg)
    
    # Phase 2: HP from cache only
    target_hp = require_hp_from_cache(str(target["id"]), game_state)
    
    # Calculate if unit can kill target in 1 phase (use selected weapon or first weapon)
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    if not unit_rng_weapon and unit.get("RNG_WEAPONS"):
        unit_rng_weapon = unit["RNG_WEAPONS"][0]
    unit_rng_dmg = require_key(unit_rng_weapon, "DMG") if unit_rng_weapon else 0
    can_kill_1_phase = target_hp <= unit_rng_dmg
    
    # Priority 1: High threat that melee can charge but won't kill (score: 1000)
    if threat_level >= 3:  # High threat threshold
        melee_can_charge = check_if_melee_can_charge(target, game_state)
        if melee_can_charge and target_hp > 2:  # Won't die to melee in 1 phase
            return 1000 + threat_level
    
    # Priority 2: High threat that can be killed in 1 shooting phase (score: 800) 
    if can_kill_1_phase and threat_level >= 3:
        return 800 + threat_level
    
    # Priority 3: High threat, lowest HP that can be killed (score: 600)
    if can_kill_1_phase and threat_level >= 2:
        return 600 + threat_level + (10 - target_hp)  # Prefer lower HP
    
    # Default: threat level only
    return threat_level


def enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich unit data for reward mapper compatibility (matches engine format).
    Unit must be alive (in units_cache). For dead targets use a stub with cur_hp=0 from caller.
    """
    if not unit:
        return {}
    
    # Direct field access with validation
    if "agent_mapping" not in game_state:
        agent_mapping = {}
    else:
        agent_mapping = game_state["agent_mapping"]
    
    unit_id_key = str(require_key(unit, "id"))
    if unit_id_key in agent_mapping:
        controlled_agent = agent_mapping[unit_id_key]
    elif "unitType" in unit:
        controlled_agent = unit["unitType"]
    elif "unit_type" in unit:
        controlled_agent = unit["unit_type"]
    else:
        controlled_agent = "default"
    
    enriched = unit.copy()
    
    # Phase 2: HP from cache only; unit must be alive (in cache)
    cur_hp = require_hp_from_cache(unit_id_key, game_state)
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of CC_DMG/RNG_DMG
    from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
    
    # Get max DMG from weapons
    unit_rng_weapon = get_selected_ranged_weapon(unit)
    unit_cc_weapon = get_selected_melee_weapon(unit)
    rng_dmg = require_key(unit_rng_weapon, "DMG") if unit_rng_weapon else 0
    cc_dmg = require_key(unit_cc_weapon, "DMG") if unit_cc_weapon else 0
    # Also check all weapons for max DMG
    if unit.get("RNG_WEAPONS"):
        rng_dmg = max(rng_dmg, max(require_key(w, "DMG") for w in unit["RNG_WEAPONS"]))
    if unit.get("CC_WEAPONS"):
        cc_dmg = max(cc_dmg, max(require_key(w, "DMG") for w in unit["CC_WEAPONS"]))
    
    enriched.update({
        "controlled_agent": controlled_agent,
        "unitType": controlled_agent,  # Use controlled_agent as unitType
        "name": unit["name"] if "name" in unit else f"Unit_{unit['id']}",
        "cc_dmg": cc_dmg,
        "rng_dmg": rng_dmg,
        "CUR_HP": cur_hp
    })
    
    return enriched


def build_enemy_adjacent_hexes(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """
    Pre-compute all hexes adjacent to enemy units.

    Returns a set of (col, row) tuples that are adjacent to at least one enemy.
    This allows O(1) adjacency checks instead of O(n) iteration per hex.

    Calculates once per phase and stores in game_state cache.
    Call this function at phase start, then use game_state[f"enemy_adjacent_hexes_player_{player}"] directly.

    Uses units_cache as source of truth for living enemy positions.

    Args:
        game_state: Game state with units_cache
        player: The player checking adjacency (enemies are units with different player)

    Returns:
        Set of hex coordinates adjacent to any living enemy unit
    """
    # Require units_cache to exist
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (call build_units_cache at reset)")
    
    enemy_adjacent_hexes = set()
    alive_enemy_count = 0  # For debug summary only
    player_int = int(player) if player is not None else None

    # Iterate over units_cache (only living enemies: HP_CUR > 0)
    for unit_id, entry in game_state["units_cache"].items():
        if require_key(entry, "HP_CUR") <= 0:
            continue  # Skip dead units
        enemy_player = entry["player"]
        
        if enemy_player == player_int:
            continue  # Skip friendly units
        
        alive_enemy_count += 1
        enemy_col = entry["col"]
        enemy_row = entry["row"]
        
        # Add all 6 neighbors of this enemy to the set
        # CRITICAL: Only add neighbors that are within board bounds
        neighbors = get_hex_neighbors(enemy_col, enemy_row)
        for neighbor_col, neighbor_row in neighbors:
            if (neighbor_col >= 0 and neighbor_row >= 0 and
                neighbor_col < game_state.get("board_cols", 999999) and
                neighbor_row < game_state.get("board_rows", 999999)):
                enemy_adjacent_hexes.add((neighbor_col, neighbor_row))

    # Store result in game_state cache for reuse during phase
    cache_key = f"enemy_adjacent_hexes_player_{player}"
    game_state[cache_key] = enemy_adjacent_hexes
    
    return enemy_adjacent_hexes
