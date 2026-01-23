#!/usr/bin/env python3
"""
engine/phase_handlers/shared_utils.py - Shared utility functions for phase handlers
Functions used across multiple phase handlers to avoid duplication.
"""

from typing import Dict, List, Tuple, Set, Optional, Any
from engine.combat_utils import get_unit_coordinates, calculate_hex_distance, get_hex_neighbors


def check_if_melee_can_charge(target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
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
                distance = calculate_hex_distance(*get_unit_coordinates(unit), *get_unit_coordinates(target))
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge = unit["MOVE"] + 7  # Average 2d6 = 7
            
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
        melee_can_charge = check_if_melee_can_charge(target, game_state)
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


def enrich_unit_for_reward_mapper(unit: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
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


def build_enemy_adjacent_hexes(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    """
    Pre-compute all hexes adjacent to enemy units.

    Returns a set of (col, row) tuples that are adjacent to at least one enemy.
    This allows O(1) adjacency checks instead of O(n) iteration per hex.

    Calculates once per phase and stores in game_state cache.
    Call this function at phase start, then use game_state[f"enemy_adjacent_hexes_player_{player}"] directly.

    Args:
        game_state: Game state with units
        player: The player checking adjacency (enemies are units with different player)

    Returns:
        Set of hex coordinates adjacent to any living enemy unit
    """
    # Only log in debug mode to avoid performance impact during training
    debug_mode_val = game_state.get("debug_mode", False)
    if debug_mode_val:
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        test_log = f"[DEBUG TEST] build_enemy_adjacent_hexes called: debug_mode={debug_mode_val}, episode={episode}, turn={turn}, phase={phase}, player={player}"
        game_state["console_logs"].append(test_log)
    
    enemy_adjacent_hexes = set()
    enemies_processed = []  # Track enemies for debugging
    all_units_info = []  # Track all units for debugging

    enemies_detailed = []  # Track detailed enemy info for debugging
    for enemy in game_state["units"]:
        # Log all units for debugging
        unit_info = f"Unit {enemy['id']} player={enemy['player']} HP={enemy.get('HP_CUR', 0)} at ({int(enemy['col'])},{int(enemy['row'])})"
        all_units_info.append(unit_info)
        
        # Convert player to int for consistent comparison
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        player_int = int(player) if player is not None else None
        
        # Build detailed enemy info for debugging
        hp_cur_raw = enemy.get("HP_CUR", 0)
        # Ensure hp_cur is always an int (handle None and string cases)
        try:
            hp_cur = int(float(hp_cur_raw)) if hp_cur_raw is not None else 0
        except (ValueError, TypeError):
            hp_cur = 0
        hp_max = enemy.get("HP_MAX", "?")
        # Normalize coordinates to int - raises error if invalid
        enemy_col, enemy_row = get_unit_coordinates(enemy)
        is_dead = hp_cur <= 0
        is_friendly = enemy_player == player_int
        
        if is_friendly:
            status = "FRIENDLY"
        elif is_dead:
            status = "DEAD"
        else:
            status = "ALIVE_ENEMY"
        
        enemy_detail = f"Unit {enemy['id']} player={enemy_player} HP_CUR={hp_cur} HP_MAX={hp_max} at ({enemy_col},{enemy_row}) status={status}"
        enemies_detailed.append(enemy_detail)
        
        # Debug: Log why units are skipped
        if enemy_player == player_int:
            continue  # Skip friendly units
        if hp_cur <= 0:
            continue  # Skip dead units
        
        # Convert coordinates to int before calculating neighbors
        # Normalize coordinates to int - raises error if invalid
        enemy_col, enemy_row = get_unit_coordinates(enemy)
        
        # Debug: Log Unit 5 position specifically (only in debug mode)
        if game_state.get("debug_mode", False) and str(enemy["id"]) == "5":
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            phase = game_state.get("phase", "?")
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes: Unit 5 position check - get_unit_coordinates() returned ({enemy_col},{enemy_row}), unit['col']={enemy.get('col')}, unit['row']={enemy.get('row')}"
            from engine.game_utils import add_console_log, safe_print
            add_console_log(game_state, log_message)
            safe_print(game_state, log_message)
        
        enemies_processed.append(f"Unit {enemy['id']} at ({enemy_col},{enemy_row})")
        # Add all 6 neighbors of this enemy to the set
        # CRITICAL: Only add neighbors that are within board bounds
        # Neighbors outside bounds are not valid destinations anyway
        neighbors = get_hex_neighbors(enemy_col, enemy_row)
        for neighbor_col, neighbor_row in neighbors:
            # Filter out neighbors outside board bounds
            if (neighbor_col >= 0 and neighbor_row >= 0 and
                neighbor_col < game_state.get("board_cols", 999999) and
                neighbor_row < game_state.get("board_rows", 999999)):
                enemy_adjacent_hexes.add((neighbor_col, neighbor_row))

    # Log enemy adjacent hexes result (only in debug mode to avoid performance impact)
    # Always log for P1 to debug the (4,8) issue
    should_log = game_state.get("debug_mode", False)  # Only log in debug mode
    if should_log:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "?")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        # Convert set to sorted list for readable output
        sorted_hexes = sorted(enemy_adjacent_hexes)
        # Log the complete list of hexes in enemy_adjacent_hexes
        hexes_list_str = str(sorted_hexes) if len(sorted_hexes) <= 100 else str(sorted_hexes[:100]) + f"... (total {len(sorted_hexes)})"
        log_message = f"[MOVE DEBUG] E{episode} T{turn} {phase} build_enemy_adjacent_hexes player={player}: enemy_adjacent_hexes count={len(enemy_adjacent_hexes)} enemies={enemies_processed} enemies_detailed={enemies_detailed} all_units={all_units_info} hexes={hexes_list_str}"
        from engine.game_utils import add_console_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)  # Also print to console for immediate visibility

    # Store result in game_state cache for reuse during phase
    cache_key = f"enemy_adjacent_hexes_player_{player}"
    game_state[cache_key] = enemy_adjacent_hexes
    
    return enemy_adjacent_hexes
