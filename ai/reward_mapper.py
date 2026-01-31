# ai/reward_mapper.py
"""
Reward mapping system that implements AI_GAME_OVERVIEW.md specifications
using existing parameter unitTypes from rewards_config.json
"""

from typing import Dict, List, Any, Tuple
from engine.utils.weapon_helpers import get_max_ranged_damage, get_max_melee_damage, get_selected_ranged_weapon, get_selected_melee_weapon
from engine.phase_handlers.shared_utils import get_hp_from_cache
from shared.data_validation import require_key

class RewardMapper:
    """Maps AI_GAME_OVERVIEW.md tactical priorities to existing reward parameters."""
    
    def __init__(self, rewards_config):
        self.rewards_config = rewards_config
    
    def _get_unit_threat(self, unit: Dict[str, Any]) -> float:
        """
        Calculate unit threat score (max of ranged and melee damage potential).
        MULTIPLE_WEAPONS_IMPLEMENTATION.md: Replaces old RNG_DMG/CC_DMG fields.
        """
        rng_dmg = get_max_ranged_damage(unit)
        cc_dmg = get_max_melee_damage(unit)
        return max(rng_dmg, cc_dmg)
    
    def _get_target_hp(self, target: Dict[str, Any], game_state: Dict[str, Any]) -> int:
        """HP of target: from units_cache if alive, else 0 (dead = not in cache)."""
        hp = get_hp_from_cache(str(target["id"]), game_state)
        return hp if hp is not None else 0
    
    def _can_unit_kill_target_in_one_phase(self, unit: Dict[str, Any], target: Dict[str, Any], is_ranged: bool, game_state: Dict[str, Any]) -> bool:
        """
        Check if unit can kill target in one phase.
        MULTIPLE_WEAPONS_IMPLEMENTATION.md: Uses weapon arrays instead of single damage fields.
        Phase 2: HP from _get_target_hp (enriched cur_hp or cache).
        """
        target_hp = self._get_target_hp(target, game_state)
        if target_hp <= 0:
            return True
        
        if is_ranged:
            weapon = get_selected_ranged_weapon(unit)
            if not weapon:
                return False
            max_damage = require_key(weapon, "NB") * require_key(weapon, "DMG")
        else:
            weapon = get_selected_melee_weapon(unit)
            if not weapon:
                return False
            max_damage = require_key(weapon, "NB") * require_key(weapon, "DMG")
        
        return target_hp <= max_damage
    
    def get_shooting_priority_reward(self, unit, target, all_targets, can_melee_charge_target, game_state: Dict[str, Any]):
        """
        Calculate shooting reward based on AI_GAME_OVERVIEW.md priority system:
        
        1. Enemy unit at ranged range:
           - with highest threat score (max of ranged/melee damage)
           - that one or more of our melee units can charge
           - would not kill in 1 melee phase
        
        2. Enemy unit at ranged range:
           - with highest threat score (max of ranged/melee damage)
           - can be killed by active unit in 1 shooting phase
        
        3. Enemy unit at ranged range:
           - with highest threat score (max of ranged/melee damage)
           - having the less HP
           - can be killed by active unit in 1 shooting phase
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = require_key(unit_rewards, "base_actions")
        if "ranged_attack" not in base_actions:
            raise ValueError("ranged_attack reward not found in unit rewards config")
        base_reward = base_actions["ranged_attack"]
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate target threat using weapon arrays
        target_threat = self._get_unit_threat(target)
        can_kill_1_phase = self._can_unit_kill_target_in_one_phase(unit, target, is_ranged=True, game_state=game_state)
        
        # Priority 1: High threat target that melee can charge but won't kill in 1 melee phase
        if can_melee_charge_target:
            melee_damage = self._get_max_melee_damage_vs_target(target)
            target_hp = self._get_target_hp(target, game_state)
            if target_hp > melee_damage:  # Won't be killed by melee in 1 phase
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
        if can_kill_1_phase and self._is_lowest_hp_high_threat(target, all_targets, game_state):
            if "shoot_priority_3" not in unit_rewards:
                raise ValueError("shoot_priority_3 reward not found in unit rewards config")
            return base_reward + unit_rewards["shoot_priority_3"]
        
        # Standard shooting reward
        return base_reward
    
    def get_charge_priority_reward(self, unit, target, all_targets, game_state: Dict[str, Any]):
        """
        Calculate charge reward based on AI_GAME_OVERVIEW.md priority system:
        
        For melee units:
        1. Enemy with highest threat score that can be killed in 1 melee phase
        2. Enemy with highest threat score, less current HP, HP >= unit's melee damage
        3. Enemy with highest threat score and less current HP
        
        For ranged units:
        1. Enemy with highest threat score, highest current HP, can be killed in 1 melee phase
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = require_key(unit_rewards, "base_actions")
        if "charge_success" not in base_actions:
            raise ValueError("charge_success reward not found in unit rewards config")
        base_reward = base_actions["charge_success"]

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate target threat using weapon arrays
        target_threat = self._get_unit_threat(target)
        can_kill_1_phase = self._can_unit_kill_target_in_one_phase(unit, target, is_ranged=False, game_state=game_state)
        
        if "is_melee" not in unit:
            raise ValueError(f"unit.is_melee is required for unit {unit.get('unitType', 'unknown')}")
        if unit["is_melee"]:  # Melee unit charge priorities
            # Priority 1: Can kill in 1 melee phase
            if can_kill_1_phase and self._is_highest_threat_in_range(target, all_targets):
                return base_reward + require_key(unit_rewards, "charge_priority_1")

            # Priority 2: High threat, low HP, HP >= unit's damage
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use melee weapon damage
            melee_weapon = get_selected_melee_weapon(unit)
            if not melee_weapon:
                raise ValueError("Selected melee weapon is required for melee charge priority calculation")
            unit_melee_dmg = require_key(melee_weapon, "NB") * require_key(melee_weapon, "DMG")
            target_hp = self._get_target_hp(target, game_state)
            if (target_hp >= unit_melee_dmg and
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets, game_state)):
                return base_reward + require_key(unit_rewards, "charge_priority_2")

            # Priority 3: High threat, lowest HP
            if (self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets, game_state)):
                return base_reward + require_key(unit_rewards, "charge_priority_3")

        else:  # Ranged unit charge priorities (different logic)
            if (can_kill_1_phase and
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_highest_hp_among_threats(target, all_targets, game_state)):
                return base_reward + require_key(unit_rewards, "charge_priority_1")

        return base_reward
    
    def get_combat_priority_reward(self, unit, target, all_targets, game_state: Dict[str, Any]):
        """
        Calculate combat reward based on AI_GAME_OVERVIEW.md priority system:
        
        1. Enemy with highest threat score that can be killed in 1 melee phase
        2. Enemy with highest threat score, if multiple then lowest current HP
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = require_key(unit_rewards, "base_actions")
        if "melee_attack" not in base_actions:
            raise ValueError("melee_attack reward not found in unit rewards config")
        base_reward = base_actions["melee_attack"]

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use melee weapon damage
        can_kill_1_phase = self._can_unit_kill_target_in_one_phase(unit, target, is_ranged=False, game_state=game_state)

        # Priority 1: Can kill in 1 melee phase with highest threat
        if can_kill_1_phase and self._is_highest_threat_adjacent(target, all_targets):
            priority_bonus = require_key(unit_rewards, "attack_priority_1")
            return base_reward + priority_bonus

        # Priority 2: Highest threat, lowest HP if multiple high threats
        if (self._is_highest_threat_adjacent(target, all_targets) and
            self._is_lowest_hp_among_adjacent_threats(target, all_targets, game_state)):
            priority_bonus = require_key(unit_rewards, "attack_priority_2")
            return base_reward + priority_bonus

        return base_reward
    
    def get_kill_bonus_reward(self, unit, target, damage_dealt, game_state: Dict[str, Any]):
        """Calculate kill bonus rewards using existing parameter unitTypes. Phase 2: HP from _get_target_hp."""
        unit_rewards = self._get_unit_rewards(unit)
        target_hp = self._get_target_hp(target, game_state)
        
        if target_hp - damage_dealt <= 0:  # Target will be killed
            phase = self._get_current_phase()
            
            result_bonuses = require_key(unit_rewards, "result_bonuses")
            if phase == "shoot":
                if "kill_target" not in result_bonuses:
                    raise ValueError("kill_target reward not found in unit rewards config")
                base_kill = result_bonuses["kill_target"]
            else:  # melee combat
                if "kill_target" not in result_bonuses:
                    raise ValueError("kill_target reward not found in unit rewards config")
                base_kill = result_bonuses["kill_target"]
            
            # No overkill bonus
            if target_hp == damage_dealt:
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
            if self._was_lowest_hp_target(target, game_state):
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
    
    def get_advance_reward(self, unit, old_pos, new_pos, tactical_context):
        """
        ADVANCE_IMPLEMENTATION: Calculate advance rewards during shooting phase.
        
        Advance is a trade-off:
        - Gives up shooting this turn (unless Assault weapon)
        - But allows repositioning (closer to enemies, better cover, etc.)
        
        Returns:
            tuple: (reward_value, action_name) where action_name is the reward config key
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = require_key(unit_rewards, "base_actions")
        
        # Base advance reward (required in rewards_config.json)
        base_reward = require_key(base_actions, "advance")
        action_name = "advance"
        
        total_reward = base_reward
        
        # Tactical bonuses for advance
        tactical_bonuses = require_key(unit_rewards, "tactical_bonuses")
        
        # Bonus: Advanced closer to enemies (aggressive positioning)
        if tactical_context.get("moved_closer"):
            total_reward += require_key(tactical_bonuses, "advanced_closer")
        
        # Bonus: Advanced to better cover position
        if tactical_context.get("moved_to_cover"):
            total_reward += require_key(tactical_bonuses, "advanced_to_cover")
        
        # Penalty: Advanced away from enemies (usually suboptimal)
        if tactical_context.get("moved_away"):
            total_reward -= 0.05  # Small penalty for retreating during shooting phase
        
        return (total_reward, action_name)
    
    def get_movement_reward(self, unit, old_pos, new_pos, tactical_context):
        """Calculate movement rewards using existing rewards_config.json structure.
        
        Returns:
            tuple: (reward_value, action_name) where action_name is the reward config key
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_actions = unit_rewards["base_actions"]
        tactical_bonuses = require_key(unit_rewards, "tactical_bonuses")
        
        if unit.get("is_ranged", False):
            # CHANGE 3: Base movement reward (unchanged)
            if tactical_context.get("moved_to_optimal_range"):
                base_reward = base_actions["move_to_los"]
                action_name = "move_to_los"
            elif tactical_context.get("moved_away"):
                base_reward = base_actions["move_away"]
                action_name = "move_away"
            elif tactical_context.get("moved_closer"):
                base_reward = base_actions["move_close"]
                action_name = "move_close"
            elif tactical_context.get("moved_to_safety"):
                base_reward = base_actions["move_away"]
                action_name = "move_away"
            elif tactical_context.get("moved_to_charge_range"):
                base_reward = base_actions["move_close"]
                action_name = "move_close"
            else:
                raise ValueError("No valid ranged unit movement context found in tactical_context")
            
            # CHANGE 3: Stack tactical bonuses on top of base reward
            total_reward = base_reward
            
            # Bonus 1: Gained LoS on priority target (+0.2)
            if tactical_context.get("gained_los_on_priority_target"):
                total_reward += require_key(tactical_bonuses, "gained_los_on_target")
            
            # Bonus 2: Moved to cover from enemies (+0.15)
            if tactical_context.get("moved_to_cover_from_enemies"):
                total_reward += require_key(tactical_bonuses, "moved_to_cover")
            
            # Bonus 3: Safe from enemy charges (+0.1)
            if tactical_context.get("safe_from_enemy_charges"):
                total_reward += require_key(tactical_bonuses, "safe_from_charges")
            
            # Bonus 4: Safe from enemy ranged (+0.05 - secondary benefit)
            if tactical_context.get("safe_from_enemy_ranged"):
                total_reward += require_key(tactical_bonuses, "safe_from_ranged")
            
            return (total_reward, action_name)
        else:
            # Melee unit movement priorities using existing config keys
            if tactical_context.get("moved_to_charge_range"):
                return (base_actions["move_to_charge"], "move_to_charge")
            elif tactical_context.get("moved_closer"):
                return (base_actions["move_close"], "move_close")
            elif tactical_context.get("moved_away"):
                return (base_actions["move_away"], "move_away")
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
        """Parse unit type into components: Faction_Movement_PowerLevel_AttackPreference
        Also handles phase-specific suffixes like _phase1, _phase2, etc."""
        parts = unit_type.split("_")
        
        # Strip phase suffix if present (e.g., "phase1", "phase2", "phase3")
        if len(parts) > 4 and parts[-1].startswith("phase"):
            parts = parts[:-1]
        
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
        target_bonuses = require_key(unit_rewards, "target_type_bonuses")
        
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
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon arrays for threat calculation
        target_threat = self._get_unit_threat(target)
        for other in all_targets:
            if other != target:
                other_threat = self._get_unit_threat(other)
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_highest_threat_adjacent(self, target, adjacent_targets):
        """Check if target has highest threat score among adjacent targets."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon arrays for threat calculation
        target_threat = self._get_unit_threat(target)
        for other in adjacent_targets:
            if other != target:
                other_threat = self._get_unit_threat(other)
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_lowest_hp_high_threat(self, target, all_targets, game_state: Dict[str, Any]):
        """Check if target has lowest HP among high threat targets. Phase 2: HP from _get_target_hp."""
        target_threat = self._get_unit_threat(target)
        max_threat = max(self._get_unit_threat(t) for t in all_targets)
        target_hp = self._get_target_hp(target, game_state)
        if target_threat == max_threat:
            for other in all_targets:
                other_threat = self._get_unit_threat(other)
                other_hp = self._get_target_hp(other, game_state)
                if other_threat == max_threat and other_hp < target_hp:
                    return False
            return True
        return False
    
    def _is_lowest_hp_among_threats(self, target, all_targets, game_state: Dict[str, Any]):
        """Check if target has lowest HP among targets of same threat level. Phase 2: HP from _get_target_hp."""
        target_threat = self._get_unit_threat(target)
        target_hp = self._get_target_hp(target, game_state)
        for other in all_targets:
            other_threat = self._get_unit_threat(other)
            other_hp = self._get_target_hp(other, game_state)
            if other_threat == target_threat and other_hp < target_hp:
                return False
        return True
    
    def _is_highest_hp_among_threats(self, target, all_targets, game_state: Dict[str, Any]):
        """Check if target has highest HP among targets of same threat level. Phase 2: HP from _get_target_hp."""
        target_threat = self._get_unit_threat(target)
        target_hp = self._get_target_hp(target, game_state)
        for other in all_targets:
            other_threat = self._get_unit_threat(other)
            other_hp = self._get_target_hp(other, game_state)
            if other_threat == target_threat and other_hp > target_hp:
                return False
        return True
    
    def _is_lowest_hp_among_adjacent_threats(self, target, adjacent_targets, game_state: Dict[str, Any]):
        """Check if target has lowest HP among adjacent targets of same threat level. Phase 2: HP from _get_target_hp."""
        target_threat = self._get_unit_threat(target)
        target_hp = self._get_target_hp(target, game_state)
        for other in adjacent_targets:
            if other != target:
                other_threat = self._get_unit_threat(other)
                other_hp = self._get_target_hp(other, game_state)
                if other_threat == target_threat and other_hp < target_hp:
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
    
    def _was_lowest_hp_target(self, target, game_state: Dict[str, Any]):
        """Check if this was the lowest HP target when action was taken. Phase 2: HP from get_hp_from_cache."""
        # get_kill_bonus_reward does not receive all_targets; cannot compare. No bonus to avoid over-reward.
        return False
