# ai/reward_mapper.py
"""
Reward mapping system that implements AI_GAME_OVERVIEW.md specifications
using existing parameter names from rewards_config.json
"""

from typing import Dict, List, Any, Tuple

class RewardMapper:
    """Maps AI_GAME_OVERVIEW.md tactical priorities to existing reward parameters."""
    
    def __init__(self, rewards_config):
        self.rewards_config = rewards_config
    
    def get_shooting_priority_reward(self, unit, target, all_targets, can_melee_charge_target):
        """
        Calculate shooting reward based on AI_GAME_OVERVIEW.md priority system:
        
        1. Enemy unit at RNG_RNG range:
           - with highest RNG_DMG or CC_DMG score
           - that one or more of our melee units can charge
           - would not kill in 1 melee phase
        
        2. Enemy unit at RNG_RNG range:
           - with highest RNG_DMG or CC_DMG score
           - can be killed by active unit in 1 shooting phase
        
        3. Enemy unit at RNG_RNG range:
           - with highest RNG_DMG or CC_DMG score
           - having the less HP
           - can be killed by active unit in 1 shooting phase
        """
        unit_rewards = self._get_unit_rewards(unit)
        if "ranged_attack" not in unit_rewards:
            raise ValueError("ranged_attack reward not found in unit rewards config")
        base_reward = unit_rewards["ranged_attack"]
        
        # Calculate target threat score (highest RNG_DMG or CC_DMG)
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        if "rng_dmg" not in unit:
            raise ValueError(f"unit.rng_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["CUR_HP"] <= unit["rng_dmg"]
        
        # Priority 1: High threat target that melee can charge but won't kill in 1 melee phase
        if can_melee_charge_target:
            melee_damage = self._get_max_melee_damage_vs_target(target)
            if target["CUR_HP"] > melee_damage:  # Won't be killed by melee in 1 phase
                if self._is_highest_threat_in_range(target, all_targets):
                    if "shoot_priority_1" not in unit_rewards:
                        raise ValueError("shoot_priority_1 reward not found in unit rewards config")
                    return base_reward + unit_rewards["shoot_priority_1"]
        
        # Priority 2: High threat target that can be killed in 1 shooting phase
        if can_kill_1_phase and self._is_highest_threat_in_range(target, all_targets):
            if "shoot_priority_2" not in unit_rewards:
                raise ValueError("shoot_priority_2 reward not found in unit rewards config")
            return base_reward + unit_rewards["shoot_priority_2"]
        
        # Priority 3: High threat, lowest HP target that can be killed in 1 phase
        if can_kill_1_phase and self._is_lowest_hp_high_threat(target, all_targets):
            if "shoot_priority_3" not in unit_rewards:
                raise ValueError("shoot_priority_3 reward not found in unit rewards config")
            return base_reward + unit_rewards["shoot_priority_3"]
        
        # Standard shooting reward
        return base_reward
    
    def get_charge_priority_reward(self, unit, target, all_targets):
        """
        Calculate charge reward based on AI_GAME_OVERVIEW.md priority system:
        
        For melee units:
        1. Enemy with highest threat score that can be killed in 1 melee phase
        2. Enemy with highest threat score, less current HP, HP >= unit's CC_DMG
        3. Enemy with highest threat score and less current HP
        
        For ranged units:
        1. Enemy with highest threat score, highest current HP, can be killed in 1 melee phase
        """
        unit_rewards = self._get_unit_rewards(unit)
        if "charge_success" not in unit_rewards:
            raise ValueError("charge_success reward not found in unit rewards config")
        base_reward = unit_rewards["charge_success"]

        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        if "cc_dmg" not in unit:
            raise ValueError(f"unit.cc_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["CUR_HP"] <= unit["cc_dmg"]
        
        if "is_melee" not in unit:
            raise ValueError(f"unit.is_melee is required for unit {unit.get('name', 'unknown')}")
        if unit["is_melee"]:  # Melee unit charge priorities
            # Priority 1: Can kill in 1 melee phase
            if can_kill_1_phase and self._is_highest_threat_in_range(target, all_targets):
                if "charge_priority_1" not in unit_rewards:
                    raise ValueError("charge_priority_1 reward not found in unit rewards config")
                return base_reward + unit_rewards["charge_priority_1"]
            
            # Priority 2: High threat, low HP, HP >= unit's damage
            if (target["CUR_HP"] >= unit["cc_dmg"] and 
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets)):
                if "charge_priority_2" not in unit_rewards:
                    raise ValueError("charge_priority_2 reward not found in unit rewards config")
                return base_reward + unit_rewards["charge_priority_2"]
            
            # Priority 3: High threat, lowest HP
            if (self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets)):
                if "charge_priority_3" not in unit_rewards:
                    raise ValueError("charge_priority_3 reward not found in unit rewards config")
                return base_reward + unit_rewards["charge_priority_3"]
        
        else:  # Ranged unit charge priorities (different logic)
            if (can_kill_1_phase and 
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_highest_hp_among_threats(target, all_targets)):
                if "charge_priority_1" not in unit_rewards:
                    raise ValueError("charge_priority_1 reward not found in unit rewards config")
                return base_reward + unit_rewards["charge_priority_1"]
        
        return base_reward
    
    def get_combat_priority_reward(self, unit, target, all_targets):
        """
        Calculate combat reward based on AI_GAME_OVERVIEW.md priority system:
        
        1. Enemy with highest threat score that can be killed in 1 melee phase
        2. Enemy with highest threat score, if multiple then lowest current HP
        """
        unit_rewards = self._get_unit_rewards(unit)
        if "attack" not in unit_rewards:
            raise ValueError("attack reward not found in unit rewards config")
        base_reward = unit_rewards["attack"]

        if "cc_dmg" not in unit:
            raise ValueError(f"unit.cc_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["CUR_HP"] <= unit["cc_dmg"]

        # Priority 1: Can kill in 1 melee phase with highest threat
        if can_kill_1_phase and self._is_highest_threat_adjacent(target, all_targets):
            if "attack_priority_1" not in unit_rewards:
                raise ValueError("attack_priority_1 reward not found in unit rewards config")
            return base_reward + unit_rewards["attack_priority_1"]
        
        # Priority 2: Highest threat, lowest HP if multiple high threats
        if (self._is_highest_threat_adjacent(target, all_targets) and
            self._is_lowest_hp_among_adjacent_threats(target, all_targets)):
            if "attack_priority_2" not in unit_rewards:
                raise ValueError("attack_priority_2 reward not found in unit rewards config")
            return base_reward + unit_rewards["attack_priority_2"]
        
        return base_reward
    
    def get_kill_bonus_reward(self, unit, target, damage_dealt):
        """Calculate kill bonus rewards using existing parameter names."""
        unit_rewards = self._get_unit_rewards(unit)
        
        if target["CUR_HP"] - damage_dealt <= 0:  # Target will be killed
            phase = self._get_current_phase()
            
            if phase == "shoot":
                if "enemy_killed_r" not in unit_rewards:
                    raise ValueError("enemy_killed_r reward not found in unit rewards config")
                base_kill = unit_rewards["enemy_killed_r"]
            else:  # melee combat
                if "enemy_killed_m" not in unit_rewards:
                    raise ValueError("enemy_killed_m reward not found in unit rewards config")
                base_kill = unit_rewards["enemy_killed_m"]
            
            # No overkill bonus
            if target["CUR_HP"] == damage_dealt:
                if phase == "shoot":
                    if "enemy_killed_no_overkill_r" not in unit_rewards:
                        raise ValueError("enemy_killed_no_overkill_r reward not found in unit rewards config")
                    if "enemy_killed_r" not in unit_rewards:
                        raise ValueError("enemy_killed_r reward not found in unit rewards config")
                    base_kill += unit_rewards["enemy_killed_no_overkill_r"] - unit_rewards["enemy_killed_r"]
                else:
                    if "enemy_killed_no_overkill_m" not in unit_rewards:
                        raise ValueError("enemy_killed_no_overkill_m reward not found in unit rewards config")
                    if "enemy_killed_m" not in unit_rewards:
                        raise ValueError("enemy_killed_m reward not found in unit rewards config")
                    base_kill += unit_rewards["enemy_killed_no_overkill_m"] - unit_rewards["enemy_killed_m"]
            
            # Lowest HP target bonus
            if self._was_lowest_hp_target(target):
                if phase == "shoot":
                    if "enemy_killed_lowests_hp_r" not in unit_rewards:
                        raise ValueError("enemy_killed_lowests_hp_r reward not found in unit rewards config")
                    if "enemy_killed_r" not in unit_rewards:
                        raise ValueError("enemy_killed_r reward not found in unit rewards config")
                    base_kill += unit_rewards["enemy_killed_lowests_hp_r"] - unit_rewards["enemy_killed_r"]
                else:
                    if "enemy_killed_lowests_hp_m" not in unit_rewards:
                        raise ValueError("enemy_killed_lowests_hp_m reward not found in unit rewards config")
                    if "enemy_killed_m" not in unit_rewards:
                        raise ValueError("enemy_killed_m reward not found in unit rewards config")
                    base_kill += unit_rewards["enemy_killed_lowests_hp_m"] - unit_rewards["enemy_killed_m"]
            
            return base_kill
        
        raise ValueError("Target was not killed - no kill bonus applicable")
    
    def get_movement_reward(self, unit, old_pos, new_pos, tactical_context):
        """Calculate movement rewards using existing rewards_config.json structure."""
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = unit_rewards["base_actions"]
        
        if unit.get("is_ranged", False):
            # Ranged unit movement priorities using existing config keys
            if tactical_context.get("moved_to_optimal_range"):
                return base_actions["move_to_los"]  # Line of sight positioning
            elif tactical_context.get("moved_away"):
                return base_actions["move_away"]    # Kiting behavior
            elif tactical_context.get("moved_closer"):
                return base_actions["move_close"]   # Aggressive positioning
            elif tactical_context.get("moved_to_safety"):
                return base_actions["move_away"]    # Use move_away for safety
            elif tactical_context.get("moved_to_charge_range"):
                return base_actions["move_close"]   # Ranged units moving to charge range = aggressive positioning
            else:
                raise ValueError("No valid ranged unit movement context found in tactical_context")
        else:
            # Melee unit movement priorities using existing config keys
            if tactical_context.get("moved_to_charge_range"):
                return base_actions["move_to_charge"]  # Charge setup
            elif tactical_context.get("moved_closer"):
                return base_actions["move_close"]      # Aggressive closing
            elif tactical_context.get("moved_away"):
                return base_actions["move_away"]       # Tactical withdrawal
            else:
                raise ValueError("No valid melee unit movement context found in tactical_context")
    
    def _get_unit_rewards(self, unit):
        """Get reward configuration using unit naming convention."""
        unit_type = unit.get("unitType", "unknown")
        
        # Direct lookup using exact unit type from rewards_config.json
        if unit_type in self.rewards_config:
            return self.rewards_config[unit_type]
        
        # If exact match not found, raise error with available keys for debugging
        available_keys = list(self.rewards_config.keys())
        raise ValueError(f"Unit type '{unit_type}' not found in rewards_config. Available keys: {available_keys}")
    
    def _parse_unit_type(self, unit_type: str) -> Dict[str, str]:
        """Parse unit type into components: Faction_Movement_PowerLevel_AttackPreference"""
        parts = unit_type.split("_")
        if len(parts) != 4:
            raise ValueError(f"Invalid unit type format: {unit_type}. Expected: Faction_Movement_PowerLevel_AttackPreference")
        
        return {
            "faction": parts[0],      # SpaceMarine, Tyranid
            "movement": parts[1],     # Infantry, Vehicle
            "power_level": parts[2],  # Swarm, Troop, Elite, Leader
            "attack_pref": parts[3]   # RangedSwarm, MeleeElite, etc.
        }
    
    def _get_target_type_bonus(self, unit: Dict[str, Any], target: Dict[str, Any]) -> float:
        """Calculate target type bonus based on unit's attack preference vs target's characteristics."""
        unit_rewards = self._get_unit_rewards(unit)
        target_bonuses = unit_rewards.get("target_type_bonuses", {})
        
        # Parse both unit and target types
        unit_parsed = self._parse_unit_type(unit.get("unitType", ""))
        target_parsed = self._parse_unit_type(target.get("unitType", ""))
        
        total_bonus = 0.0
        
        # Attack preference vs target power level match
        attack_pref = unit_parsed["attack_pref"]
        target_power = target_parsed["power_level"]
        
        # Extract preferred target type from attack preference
        if "Swarm" in attack_pref:
            preferred_target = "swarm"
        elif "Troop" in attack_pref:
            preferred_target = "troop"
        elif "Elite" in attack_pref:
            preferred_target = "elite"
        elif "Leader" in attack_pref:
            preferred_target = "leader"
        else:
            preferred_target = "troop"  # Default
        
        # Calculate penalty for targeting non-preferred types
        target_power_lower = target_power.lower()
        if f"vs_{target_power_lower}" in target_bonuses:
            total_bonus += target_bonuses[f"vs_{target_power_lower}"]
        
        # Attack type vs target type
        if "Ranged" in attack_pref:
            if f"vs_ranged" in target_bonuses:
                total_bonus += target_bonuses["vs_ranged"]
        elif "Melee" in attack_pref:
            if f"vs_melee" in target_bonuses:
                total_bonus += target_bonuses["vs_melee"]
        
        return total_bonus
    
    def _is_highest_threat_in_range(self, target, all_targets):
        """Check if target has highest threat score among all targets in range."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other['name']}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_highest_threat_adjacent(self, target, adjacent_targets):
        """Check if target has highest threat score among adjacent targets."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in adjacent_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other['name']}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_lowest_hp_high_threat(self, target, all_targets):
        """Check if target has lowest HP among high threat targets."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        max_threat = max(max(t["rng_dmg"], t["cc_dmg"]) for t in all_targets 
                        if "rng_dmg" in t and "cc_dmg" in t)
        
        if target_threat == max_threat:
            for other in all_targets:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other['name']}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat == max_threat and other["CUR_HP"] < target["CUR_HP"]:
                    return False
            return True
        return False
    
    def _is_lowest_hp_among_threats(self, target, all_targets):
        """Check if target has lowest HP among targets of same threat level.""" 
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if "rng_dmg" not in other or "cc_dmg" not in other:
                raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
            other_threat = max(other["rng_dmg"], other["cc_dmg"])
            if other_threat == target_threat and other["CUR_HP"] < target["CUR_HP"]:
                return False
        return True
    
    def _is_highest_hp_among_threats(self, target, all_targets):
        """Check if target has highest HP among targets of same threat level."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if "rng_dmg" not in other or "cc_dmg" not in other:
                raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
            other_threat = max(other["rng_dmg"], other["cc_dmg"])
            if other_threat == target_threat and other["CUR_HP"] > target["CUR_HP"]:
                return False
        return True
    
    def _is_lowest_hp_among_adjacent_threats(self, target, adjacent_targets):
        """Check if target has lowest HP among adjacent targets of same threat level."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target['name']}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target['name']}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in adjacent_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other['name']}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat == target_threat and other["CUR_HP"] < target["CUR_HP"]:
                    return False
        return True
    
    def _get_max_melee_damage_vs_target(self, target):
        """Get maximum melee damage our units can do to target.""" 
        # This would need access to friendly units list
        # Throw error instead of using default - no fallbacks allowed
        raise NotImplementedError("_get_max_melee_damage_vs_target requires access to friendly units list - no fallback defaults allowed")
    
    def _get_current_phase(self):
        """Get current game phase."""
        # This would need access to game state
        raise NotImplementedError("_get_current_phase requires access to game state - no fallback defaults allowed")
    
    def _was_lowest_hp_target(self, target):
        """Check if this was the lowest HP target when action was taken."""
        # This would need access to game state at time of action
        raise NotImplementedError("_was_lowest_hp_target requires access to game state at action time - no fallback defaults allowed")