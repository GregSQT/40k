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

def calculate_save_target(armor_save: int, invul_save: int, armor_penetration: int) -> int:
    """Calculate save target accounting for AP and invulnerable saves (EXACT from frontend)."""
    modified_armor = armor_save + armor_penetration
    
    # Use invulnerable save if it's better than modified armor save (and invul > 0)
    if invul_save > 0 and invul_save < modified_armor:
        return invul_save
    
    return modified_armor

# === SHOOTING SYSTEM (EXACT from frontend implementation) ===

def execute_shooting_sequence(shooter: Dict[str, Any], target: Dict[str, Any], target_in_cover: bool = False) -> Dict[str, Any]:
    """Execute complete shooting sequence (EXACT from frontend logic)."""
    
    # Validate required shooter stats
    if "rng_nb" not in shooter:
        raise ValueError("shooter.rng_nb is required")
    if "rng_atk" not in shooter:
        raise ValueError("shooter.rng_atk is required")
    if "rng_str" not in shooter:
        raise ValueError("shooter.rng_str is required")
    if "rng_ap" not in shooter:
        raise ValueError("shooter.rng_ap is required")
    if "rng_dmg" not in shooter:
        raise ValueError("shooter.rng_dmg is required")
    
    # Validate required target stats
    if "t" not in target:
        raise ValueError("target.t is required")
    if "armor_save" not in target:
        raise ValueError("target.armor_save is required")
    if "invul_save" not in target:
        raise ValueError("target.invul_save is required")
    
    number_of_shots = shooter["rng_nb"]
    total_damage = 0
    hits = 0
    wounds = 0
    failed_saves = 0
    
    # Process each shot
    for shot in range(1, number_of_shots + 1):
        # Hit roll
        hit_roll = roll_d6()
        hit_target = shooter["rng_atk"]
        did_hit = hit_roll >= hit_target
        
        if not did_hit:
            continue  # Miss - next shot
        hits += 1
        
        # Wound roll
        wound_roll = roll_d6()
        wound_target = calculate_wound_target(shooter["rng_str"], target["t"])
        did_wound = wound_roll >= wound_target
        
        if not did_wound:
            continue  # Failed to wound - next shot
        wounds += 1
        
        # Save roll
        save_roll = roll_d6()
        save_target = calculate_save_target(target["armor_save"], target["invul_save"], shooter["rng_ap"])
        saved_wound = save_roll >= save_target
        
        if saved_wound:
            continue  # Save successful - next shot
        failed_saves += 1
        
        # Inflict damage
        total_damage += shooter["rng_dmg"]
    
    return {
        "totalDamage": total_damage,
        "summary": {
            "totalShots": number_of_shots,
            "hits": hits,
            "wounds": wounds,
            "failedSaves": failed_saves
        }
    }
    # Step 1: Number of shots
    if "rng_nb" not in shooter:
        raise ValueError("shooter.rng_nb is required")
    number_of_shots = shooter["rng_nb"]

    total_damage = 0
    hits = 0
    wounds = 0
    failed_saves = 0

    # Process each shot
    for shot in range(1, number_of_shots + 1):
        # Step 3: Hit roll
        hit_roll = roll_d6()
        if "rng_atk" not in shooter:
            raise ValueError("shooter.rng_atk is required")
        hit_target = shooter["rng_atk"]
        did_hit = hit_roll >= hit_target
        
        if not did_hit:
            continue  # Miss - next shot
        hits += 1
        
        # Step 4: Wound roll  
        wound_roll = roll_d6()
        if "rng_str" not in shooter:
            raise ValueError("shooter.rng_str is required")
        if "t" not in target:
            raise ValueError("target.t is required")
        wound_target = calculate_wound_target(shooter["rng_str"], target["t"])
        did_wound = wound_roll >= wound_target
        
        if not did_wound:
            continue  # Failed to wound - next shot
        wounds += 1
        
        # Step 5: Armor save (with cover bonus)
        save_roll = roll_d6()
        base_armor_save = target["armor_save"]
        invul_save = target.get("invul_save", 0)
        armor_penetration = shooter["rng_ap"]
        
        # Apply cover bonus - +1 to armor save (better save)
        if target_in_cover:
            base_armor_save = max(2, base_armor_save - 1)  # Improve armor save by 1, minimum 2+
            # Note: Invulnerable saves are not affected by cover
        
        save_target = calculate_save_target(base_armor_save, invul_save, armor_penetration)
        saved_wound = save_roll >= save_target
        
        if saved_wound:
            continue  # Save successful - next shot
        failed_saves += 1
        
        # Step 6: Inflict damage
        if "rng_dmg" not in shooter:
            raise ValueError("shooter.rng_dmg is required")
        total_damage += shooter["rng_dmg"]

    return {
        "totalDamage": total_damage,
        "summary": {
            "totalShots": number_of_shots,
            "hits": hits,
            "wounds": wounds,
            "failedSaves": failed_saves
        }
    }

# === COMBAT SYSTEM (EXACT from frontend implementation) ===

def execute_combat_sequence(attacker: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """Execute combat sequence (EXACT from frontend logic)."""
    # Step 1: Number of attacks
    if "cc_nb" not in attacker:
        raise ValueError("attacker.cc_nb is required")
    number_of_attacks = attacker["cc_nb"]

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
        if "cc_atk" not in attacker:
            raise ValueError("attacker.cc_atk is required")
        hit_target = attacker["cc_atk"]
        did_hit = hit_roll >= hit_target
        attack_result["hit_success"] = did_hit
        
        if not did_hit:
            attack_details.append(attack_result)
            continue  # Miss - next attack
        hits += 1
        
        # Step 3: Wound roll  
        wound_roll = roll_d6()
        attack_result["wound_roll"] = wound_roll
        if "cc_str" not in attacker:
            raise ValueError("attacker.cc_str is required")
        if "t" not in target:
            raise ValueError("target.t is required")
        wound_target = calculate_wound_target(attacker["cc_str"], target["t"])
        did_wound = wound_roll >= wound_target
        attack_result["wound_success"] = did_wound
        
        if not did_wound:
            attack_details.append(attack_result)
            continue  # Failed to wound - next attack
        wounds += 1
        
        # Step 4: Armor save
        save_roll = roll_d6()
        attack_result["save_roll"] = save_roll
        base_armor_save = target["armor_save"]
        invul_save = target.get("invul_save", 0)
        armor_penetration = attacker["cc_ap"]
        
        save_target = calculate_save_target(base_armor_save, invul_save, armor_penetration)
        saved_wound = save_roll >= save_target
        attack_result["save_success"] = saved_wound
        
        if saved_wound:
            attack_details.append(attack_result)
            continue  # Save successful - next attack
        failed_saves += 1
        
        # Step 5: Inflict damage
        if "cc_dmg" not in attacker:
            raise ValueError("attacker.cc_dmg is required")
        damage = attacker["cc_dmg"]
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
    # Get number of attacks
    if "cc_nb" not in attacker:
        raise ValueError("attacker.cc_nb is required")
    number_of_attacks = attacker["cc_nb"]

    total_damage = 0
    hits = 0
    wounds = 0
    failed_saves = 0

    # Process each attack
    for attack in range(1, number_of_attacks + 1):
        # Hit roll
        hit_roll = roll_d6()
        if "cc_atk" not in attacker:
            raise ValueError("attacker.cc_atk is required")
        hit_target = attacker["cc_atk"]
        did_hit = hit_roll >= hit_target
        
        if not did_hit:
            continue  # Miss - next attack
        hits += 1
        
        # Wound roll
        wound_roll = roll_d6()
        if "cc_str" not in attacker:
            raise ValueError("attacker.cc_str is required")
        if "t" not in target:
            raise ValueError("target.t is required")
        wound_target = calculate_wound_target(attacker["cc_str"], target["t"])
        did_wound = wound_roll >= wound_target
        
        if not did_wound:
            continue  # Failed to wound - next attack
        wounds += 1
        
        # Save roll
        save_roll = roll_d6()
        if "armor_save" not in target:
            raise ValueError("target.armor_save is required")
        if "cc_ap" not in attacker:
            raise ValueError("attacker.cc_ap is required")
        save_target = calculate_save_target(
            target["armor_save"], 
            target.get("invul_save", 0), 
            attacker["cc_ap"]
        )
        saved_wound = save_roll >= save_target
        
        if saved_wound:
            continue  # Save successful - next attack
        failed_saves += 1
        
        # Inflict damage
        if "cc_dmg" not in attacker:
            raise ValueError("attacker.cc_dmg is required")
        total_damage += attacker["cc_dmg"]

    return {
        "totalDamage": total_damage,
        "summary": {
            "totalShots": number_of_attacks,  # Reuse same interface
            "hits": hits,
            "wounds": wounds,
            "failedSaves": failed_saves
        }
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
        get_hex_distance(unit, enemy) > 1
        for enemy in enemy_units
    )
    
    return has_enemies_within_12_hexes

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