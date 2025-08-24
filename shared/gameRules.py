# shared/gameRulesPython.py - Python version of shared rules (EXACT same mechanics)

import random
import math
from typing import Dict, List, Tuple, Optional, Any

# === HEX GEOMETRY (EXACT from frontend implementation) ===

def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
    """Convert offset coordinates to cube coordinates (EXACT from frontend)."""
    x = col
    z = row - ((col - (col & 1)) >> 1)
    y = -x - z
    return x, y, z

def cube_distance(cube1: Tuple[int, int, int], cube2: Tuple[int, int, int]) -> int:
    """Calculate cube distance (EXACT from frontend)."""
    return max(
        abs(cube1[0] - cube2[0]),
        abs(cube1[1] - cube2[1]),
        abs(cube1[2] - cube2[2])
    )

def get_hex_distance(unit1: Dict[str, Any], unit2: Dict[str, Any]) -> int:
    """Calculate proper hex grid distance (EXACT from frontend logic)."""
    cube1 = offset_to_cube(unit1["col"], unit1["row"])
    cube2 = offset_to_cube(unit2["col"], unit2["row"])
    return cube_distance(cube1, cube2)

def are_units_adjacent(unit1: Dict[str, Any], unit2: Dict[str, Any]) -> bool:
    """Check if two units are adjacent (EXACT from frontend)."""
    return get_hex_distance(unit1, unit2) == 1

def is_unit_in_range(attacker: Dict[str, Any], target: Dict[str, Any], range_value: int) -> bool:
    """Check if target is within specified range (EXACT from frontend)."""
    return get_hex_distance(attacker, target) <= range_value

# === DICE SYSTEM (EXACT from frontend implementation) ===

def roll_d6() -> int:
    """Roll a 6-sided die (EXACT from frontend)."""
    return random.randint(1, 6)

def roll_2d6() -> int:
    """Roll 2d6 for charge distance (EXACT from frontend)."""
    return roll_d6() + roll_d6()

def calculate_wound_target(strength: int, toughness: int) -> int:
    """Calculate wound target based on strength vs toughness (EXACT from frontend)."""
    if strength * 2 <= toughness:
        return 6  # S*2 <= T: wound on 6+
    elif strength >= toughness * 2:
        return 2  # S >= 2*T: wound on 2+
    elif strength > toughness:
        return 3  # S > T: wound on 3+
    elif strength == toughness:
        return 4  # S = T: wound on 4+
    else:  # strength < toughness
        return 5  # S < T: wound on 5+

def calculate_save_target(ARMOR_SAVE: int, invul_save: int, armor_penetration: int) -> int:
    """Calculate save target accounting for AP and invulnerable saves (EXACT from frontend)."""
    modified_armor = ARMOR_SAVE + armor_penetration
    
    # Use invulnerable save if it's better than modified armor save (and invul > 0)
    if invul_save > 0 and invul_save < modified_armor:
        return invul_save
    
    return modified_armor

# === LINE OF SIGHT SYSTEM (EXACT from frontend implementation) ===

def hex_to_pixel(col: int, row: int, hex_radius: int = 21) -> Dict[str, float]:
    """Convert hex coordinates to pixel coordinates for line intersection (EXACT from frontend)."""
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3) * hex_radius
    
    x = col * hex_width
    y = row * hex_height + ((col % 2) * hex_height / 2)
    
    return {"x": x, "y": y}

def line_segments_intersect(line1_start: Dict[str, float], line1_end: Dict[str, float],
                           line2_start: Dict[str, float], line2_end: Dict[str, float]) -> bool:
    """Check if two line segments intersect (EXACT from frontend)."""
    d1 = {"x": line1_end["x"] - line1_start["x"], "y": line1_end["y"] - line1_start["y"]}
    d2 = {"x": line2_end["x"] - line2_start["x"], "y": line2_end["y"] - line2_start["y"]}
    d3 = {"x": line2_start["x"] - line1_start["x"], "y": line2_start["y"] - line1_start["y"]}
    
    cross1 = d1["x"] * d2["y"] - d1["y"] * d2["x"]
    cross2 = d3["x"] * d2["y"] - d3["y"] * d2["x"]
    cross3 = d3["x"] * d1["y"] - d3["y"] * d1["x"]
    
    if abs(cross1) < 0.0001:
        return False  # Parallel lines
    
    t1 = cross2 / cross1
    t2 = cross3 / cross1
    
    return t1 >= 0 and t1 <= 1 and t2 >= 0 and t2 <= 1

def line_passes_through_hex(start_point: Dict[str, float], end_point: Dict[str, float],
                           hex_col: int, hex_row: int, hex_radius: int = 21) -> bool:
    """Check if a line passes through any part of a hex (EXACT from frontend)."""
    hex_center = hex_to_pixel(hex_col, hex_row, hex_radius)
    
    # Create hex polygon points (6 corners)
    hex_points = []
    for i in range(6):
        angle = (i * math.pi) / 3  # 60 degree increments for hex
        x = hex_center["x"] + hex_radius * math.cos(angle)
        y = hex_center["y"] + hex_radius * math.sin(angle)
        hex_points.append({"x": x, "y": y})
    
    # Check if line intersects any edge of the hex polygon
    for i in range(len(hex_points)):
        p1 = hex_points[i]
        p2 = hex_points[(i + 1) % len(hex_points)]
        
        if line_segments_intersect(start_point, end_point, p1, p2):
            return True
    
    return False

def has_line_of_sight(from_unit: Dict[str, Any], to_unit: Dict[str, Any], 
                     wall_hexes: List[List[int]]) -> Dict[str, bool]:
    """
    9-Point Line of Sight System (EXACT from frontend implementation).
    
    Args:
        from_unit: Unit or position dict with 'col' and 'row' keys
        to_unit: Unit or position dict with 'col' and 'row' keys  
        wall_hexes: List of [col, row] wall hex coordinates
        
    Returns:
        Dict with 'canSee' and 'inCover' boolean values
    """
    from_pos = {"col": from_unit["col"], "row": from_unit["row"]}
    to_pos = {"col": to_unit["col"], "row": to_unit["row"]}
    
    if not wall_hexes or len(wall_hexes) == 0:
        return {"canSee": True, "inCover": False}
    
    # Convert hex coordinates to pixel coordinates for accurate line testing
    from_pixel = hex_to_pixel(from_pos["col"], from_pos["row"], 21)
    to_pixel = hex_to_pixel(to_pos["col"], to_pos["row"], 21)
    
    # Define 9 points for each hex: center + 8 corners
    def get_hex_points(center_x: float, center_y: float, radius: int = 21) -> List[Dict[str, float]]:
        points = [{"x": center_x, "y": center_y}]  # Center point
        
        # 8 corner points around the hex (not actual hex corners, but distributed around)
        for i in range(8):
            angle = (i * math.pi) / 4  # 45 degree increments
            x = center_x + radius * 0.8 * math.cos(angle)
            y = center_y + radius * 0.8 * math.sin(angle)
            points.append({"x": x, "y": y})
        return points
    
    shooter_points = get_hex_points(from_pixel["x"], from_pixel["y"], 21)
    target_points = get_hex_points(to_pixel["x"], to_pixel["y"], 21)
    
    # Check how many sight lines from shooter points can reach target points
    clear_sight_lines = 0
    
    for shooter_point in shooter_points:
        shooter_point_has_clear_line = False
        
        for target_point in target_points:
            # Check if this line is blocked by any wall hex
            line_blocked = False
            
            for wall_col, wall_row in wall_hexes:
                if line_passes_through_hex(shooter_point, target_point, wall_col, wall_row, 21):
                    line_blocked = True
                    break
            
            if not line_blocked:
                shooter_point_has_clear_line = True
                break  # This shooter point has at least one clear line to any target point
        
        if shooter_point_has_clear_line:
            clear_sight_lines += 1
    
    # Apply your rules: 0 = blocked, 1-2 = cover, 3+ = clear (EXACT from frontend)
    if clear_sight_lines == 0:
        return {"canSee": False, "inCover": False}
    elif clear_sight_lines <= 2:
        return {"canSee": True, "inCover": True}
    else:
        return {"canSee": True, "inCover": False}

# === SHOOTING SYSTEM (EXACT from frontend implementation) ===

def execute_shooting_sequence(shooter: Dict[str, Any], all_targets: List[Dict[str, Any]], target_in_cover: bool = False) -> Dict[str, Any]:
    """Execute complete shooting sequence with dynamic retargeting and slaughter handling."""
    
    # Validate required shooter stats
    if "RNG_NB" not in shooter:
        raise ValueError("shooter.RNG_NB is required")
    if "RNG_ATK" not in shooter:
        raise ValueError("shooter.RNG_ATK is required")
    if "RNG_STR" not in shooter:
        raise ValueError("shooter.RNG_STR is required")
    if "RNG_AP" not in shooter:
        raise ValueError("shooter.RNG_AP is required")
    if "RNG_DMG" not in shooter:
        raise ValueError("shooter.RNG_DMG is required")
    
    number_of_shots = shooter["RNG_NB"]
    total_damage = 0
    hits = 0
    wounds = 0
    failed_saves = 0
    shot_details = []
    
    # AI_TURN.md: Build valid targets pool (all living enemies)
    valid_targets = []
    for target in all_targets:
        if (target["player"] != shooter["player"] and 
            target.get("CUR_HP", 0) > 0 and 
            target.get("alive", True)):
            # Validate required target stats
            if "T" not in target:
                raise ValueError(f"target.T is required for unit {target.get('id', 'unknown')}")
            if "ARMOR_SAVE" not in target:
                raise ValueError(f"target.ARMOR_SAVE is required for unit {target.get('id', 'unknown')}")
            if "INVUL_SAVE" not in target:
                raise ValueError(f"target.INVUL_SAVE is required for unit {target.get('id', 'unknown')}")
            valid_targets.append(target)
    
    # Process each shot with dynamic retargeting
    for shot in range(1, number_of_shots + 1):
        # AI_TURN.md: Check if valid targets still available (slaughter handling)
        valid_targets = [t for t in valid_targets if t.get("CUR_HP", 0) > 0 and t.get("alive", True)]
        
        if not valid_targets:
            break  # No more valid targets - implement slaughter handling (cancel remaining shots)
        
        # Select target from available pool (use first available for now)
        current_target = valid_targets[0]
        
        # Hit roll
        hit_roll = roll_d6()
        hit_target = shooter["RNG_ATK"]
        did_hit = hit_roll >= hit_target
        
        # Initialize shot record with target info
        shot_record = {
            "hit_roll": hit_roll,
            "hit_target": hit_target,
            "hit": did_hit,
            "wound_roll": 0,
            "wound_target": 0,
            "wound": False,
            "save_roll": 0,
            "save_target": 0,
            "save_success": False,
            "damage": 0,
            "target_id": current_target.get("id", "unknown")
        }
        
        if not did_hit:
            shot_details.append(shot_record)
            continue  # Miss - next shot
        hits += 1
        
        # Wound roll
        wound_roll = roll_d6()
        wound_target = calculate_wound_target(shooter["RNG_STR"], current_target["T"])
        did_wound = wound_roll >= wound_target
        
        shot_record.update({
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound": did_wound
        })
        
        if not did_wound:
            shot_details.append(shot_record)
            continue  # Failed to wound - next shot
        wounds += 1
        
        # Save roll
        save_roll = roll_d6()
        save_target = calculate_save_target(current_target["ARMOR_SAVE"], current_target["INVUL_SAVE"], shooter["RNG_AP"])
        saved_wound = save_roll >= save_target
        
        shot_record.update({
            "save_roll": save_roll,
            "save_target": save_target,
            "save_success": saved_wound
        })
        
        if saved_wound:
            shot_details.append(shot_record)
            continue  # Save successful - next shot
        failed_saves += 1
        
        # Inflict damage
        damage_dealt = shooter["RNG_DMG"]
        total_damage += damage_dealt
        shot_record["damage"] = damage_dealt
        
        # AI_TURN.md: Update target HP immediately after damage for next iteration
        new_hp = max(0, current_target.get("CUR_HP") - damage_dealt)
        current_target["CUR_HP"] = new_hp
        if new_hp <= 0:
            current_target["alive"] = False
            # Target will be removed from valid_targets in next iteration
        
        shot_details.append(shot_record)
    
    return {
        "totalDamage": total_damage,
        "summary": {
            "totalShots": len(shot_details),  # Actual shots fired (may be less than RNG_NB due to slaughter)
            "hits": hits,
            "wounds": wounds,
            "failedSaves": failed_saves
        },
        "shots": shot_details  # Individual shot details for logging
    }

# === COMBAT SYSTEM (EXACT from frontend implementation) ===

def execute_combat_sequence(attacker: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """Execute combat sequence (EXACT from frontend logic)."""
    # Step 1: Number of attacks
    if "CC_NB" not in attacker:
        raise ValueError("attacker.CC_NB is required")
    number_of_attacks = attacker["CC_NB"]

    total_damage = 0
    hits = 0
    wounds = 0
    failed_saves = 0
    
    # Detailed attack tracking for replay
    attack_details = []

    # Process each attack
    for attack in range(1, number_of_attacks + 1):
        attack_result = {
            "attack_number": attack,
            "hit_roll": 0,
            "hit_success": False,
            "wound_roll": 0,
            "wound_success": False,
            "save_roll": 0,
            "save_success": False,
            "damage_dealt": 0
        }
        
        # Step 2: Hit roll
        hit_roll = roll_d6()
        attack_result["hit_roll"] = hit_roll
        if "CC_ATK" not in attacker:
            raise ValueError("attacker.CC_ATK is required")
        hit_target = attacker["CC_ATK"]
        did_hit = hit_roll >= hit_target
        attack_result["hit_success"] = did_hit
        
        if not did_hit:
            attack_details.append(attack_result)
            continue  # Miss - next attack
        hits += 1
        
        # Step 3: Wound roll  
        wound_roll = roll_d6()
        attack_result["wound_roll"] = wound_roll
        if "CC_STR" not in attacker:
            raise ValueError("attacker.CC_STR is required")
        if "T" not in target:
            raise ValueError("target.T is required")
        wound_target = calculate_wound_target(attacker["CC_STR"], target["T"])
        did_wound = wound_roll >= wound_target
        attack_result["wound_success"] = did_wound
        
        if not did_wound:
            attack_details.append(attack_result)
            continue  # Failed to wound - next attack
        wounds += 1
        
        # Step 4: Armor save
        save_roll = roll_d6()
        attack_result["save_roll"] = save_roll
        base_ARMOR_SAVE = target["ARMOR_SAVE"]
        invul_save = target.get("INVUL_SAVE")
        armor_penetration = attacker["CC_AP"]
        
        save_target = calculate_save_target(base_ARMOR_SAVE, invul_save, armor_penetration)
        saved_wound = save_roll >= save_target
        attack_result["save_success"] = saved_wound
        
        if saved_wound:
            attack_details.append(attack_result)
            continue  # Save successful - next attack
        failed_saves += 1
        
        # Step 5: Inflict damage
        if "CC_DMG" not in attacker:
            raise ValueError("attacker.CC_DMG is required")
        damage = attacker["CC_DMG"]
        total_damage += damage
        attack_result["damage_dealt"] = damage
        
        attack_details.append(attack_result)

    return {
        "totalDamage": total_damage,
        "summary": {
            "totalAttacks": number_of_attacks,
            "hits": hits,
            "wounds": wounds,
            "failedSaves": failed_saves
        },
        "attackDetails": attack_details  # NEW: Detailed dice roll information
    }

# === CHARGE SYSTEM (EXACT from frontend implementation) ===

CHARGE_MAX_DISTANCE = 12  # Fixed 12-hex charge limit

def can_unit_charge_basic(unit: Dict[str, Any], enemy_units: List[Dict[str, Any]], 
                         units_fled: List[int], units_charged: List[int]) -> bool:
    """Check if unit can charge (EXACT from frontend logic)."""
    # Basic eligibility checks
    if unit["id"] in units_charged:
        return False  # Already charged
    if unit["id"] in units_fled:
        return False  # Fled units can't charge
    
    # Check if adjacent to any enemy (already in combat)
    is_adjacent = any(
        enemy.get("alive", True) and are_units_adjacent(unit, enemy) 
        for enemy in enemy_units 
        if enemy["player"] != unit["player"]
    )
    if is_adjacent:
        return False
    
    # Check if any enemies within 12-hex charge range (EXACT from frontend)
    has_enemies_within_12_hexes = any(
        enemy["player"] != unit["player"] and 
        enemy.get("alive", True) and
        get_hex_distance(unit, enemy) <= CHARGE_MAX_DISTANCE and
        get_hex_distance(unit, enemy) > 1  # CRITICAL: Must be more than 1 hex away
        for enemy in enemy_units
    )
    
    return has_enemies_within_12_hexes

def validate_charge_destination(unit: Dict[str, Any], dest_col: int, dest_row: int, 
                              target: Dict[str, Any], charge_roll: int) -> bool:
    """Validate that charge destination is valid."""
    # Destination must be adjacent to target
    dest_to_target_distance = get_hex_distance(
        {"col": dest_col, "row": dest_row}, 
        target
    )
    if dest_to_target_distance != 1:
        return False
    
    # Charge distance must be achievable  
    unit_to_dest_distance = get_hex_distance(
        unit, 
        {"col": dest_col, "row": dest_row}
    )
    if unit_to_dest_distance > charge_roll or unit_to_dest_distance > CHARGE_MAX_DISTANCE:
        return False
        
    return True

def get_valid_charge_targets(unit: Dict[str, Any], enemy_units: List[Dict[str, Any]], charge_roll: int) -> List[Dict[str, Any]]:
    """Get valid charge targets within rolled distance (EXACT from frontend logic)."""
    valid_targets = []
    
    for enemy in enemy_units:
        if not enemy.get("alive", True):
            continue
        if enemy["player"] == unit["player"]:
            continue
            
        distance = get_hex_distance(unit, enemy)
        if distance > 1 and distance <= min(charge_roll, CHARGE_MAX_DISTANCE):
            valid_targets.append(enemy)
    
    return valid_targets

# === UTILITY FUNCTIONS (EXACT from frontend implementation) ===

def get_player_units(units: List[Dict[str, Any]], player_id: int) -> List[Dict[str, Any]]:
    """Get units for specific player (EXACT from frontend)."""
    return [unit for unit in units if unit["player"] == player_id]

def get_enemy_units(units: List[Dict[str, Any]], player_id: int) -> List[Dict[str, Any]]:
    """Get enemy units for specific player (EXACT from frontend)."""
    return [unit for unit in units if unit["player"] != player_id]

def remove_unit_from_lists(unit_to_remove: Dict[str, Any], 
                          units: List[Dict[str, Any]], 
                          ai_units: List[Dict[str, Any]], 
                          enemy_units: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Centralized unit removal function (following frontend removeUnit pattern).
    
    Args:
        unit_to_remove: Unit to remove from all lists
        units: Main units list
        ai_units: AI player units list
        enemy_units: Enemy player units list
    
    Returns:
        Tuple of (updated_units, updated_ai_units, updated_enemy_units)
    """
    unit_id = unit_to_remove["id"]
    
    # Remove from all lists by ID
    updated_units = [u for u in units if u["id"] != unit_id]
    updated_ai_units = [u for u in ai_units if u["id"] != unit_id]
    updated_enemy_units = [u for u in enemy_units if u["id"] != unit_id]
    
    # Mark unit as dead for any remaining references
    unit_to_remove["alive"] = False
    unit_to_remove["cur_hp"] = 0
    
    return updated_units, updated_ai_units, updated_enemy_units