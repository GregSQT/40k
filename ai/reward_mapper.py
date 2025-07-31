# ai/reward_mapper.py
"""
Reward mapping system that implements AI_GAME_OVERVIEW.md specifications
using existing parameter names from rewards_config.json
"""

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
        base_reward = unit_rewards.get("ranged_attack", 1.0)
        
        # Calculate target threat score (highest RNG_DMG or CC_DMG)
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        if "rng_dmg" not in unit:
            raise ValueError(f"unit.rng_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["cur_hp"] <= unit["rng_dmg"]
        
        # Priority 1: High threat target that melee can charge but won't kill in 1 melee phase
        if can_melee_charge_target:
            melee_damage = self._get_max_melee_damage_vs_target(target)
            if target["cur_hp"] > melee_damage:  # Won't be killed by melee in 1 phase
                if self._is_highest_threat_in_range(target, all_targets):
                    return base_reward + unit_rewards.get("shoot_priority_1", 2.0)
        
        # Priority 2: High threat target that can be killed in 1 shooting phase
        if can_kill_1_phase and self._is_highest_threat_in_range(target, all_targets):
            return base_reward + unit_rewards.get("shoot_priority_2", 1.5)
        
        # Priority 3: High threat, lowest HP target that can be killed in 1 phase
        if can_kill_1_phase and self._is_lowest_hp_high_threat(target, all_targets):
            return base_reward + unit_rewards.get("shoot_priority_3", 1.0)
        
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
        base_reward = unit_rewards.get("charge_success", 1.5)

        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        if "cc_dmg" not in unit:
            raise ValueError(f"unit.cc_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["cur_hp"] <= unit["cc_dmg"]
        
        if unit.get("is_melee", True):  # Melee unit charge priorities
            # Priority 1: Can kill in 1 melee phase
            if can_kill_1_phase and self._is_highest_threat_in_range(target, all_targets):
                return base_reward + unit_rewards.get("charge_priority_1", 2.0)
            
            # Priority 2: High threat, low HP, HP >= unit's damage
            if (target["cur_hp"] >= unit["cc_dmg"] and 
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets)):
                return base_reward + unit_rewards.get("charge_priority_2", 1.5)
            
            # Priority 3: High threat, lowest HP
            if (self._is_highest_threat_in_range(target, all_targets) and
                self._is_lowest_hp_among_threats(target, all_targets)):
                return base_reward + unit_rewards.get("charge_priority_3", 1.0)
        
        else:  # Ranged unit charge priorities (different logic)
            if (can_kill_1_phase and 
                self._is_highest_threat_in_range(target, all_targets) and
                self._is_highest_hp_among_threats(target, all_targets)):
                return base_reward + unit_rewards.get("charge_priority_1", 2.0)
        
        return base_reward
    
    def get_combat_priority_reward(self, unit, target, all_targets):
        """
        Calculate combat reward based on AI_GAME_OVERVIEW.md priority system:
        
        1. Enemy with highest threat score that can be killed in 1 melee phase
        2. Enemy with highest threat score, if multiple then lowest current HP
        """
        unit_rewards = self._get_unit_rewards(unit)
        base_reward = unit_rewards.get("attack", 1.0)

        if "cc_dmg" not in unit:
            raise ValueError(f"unit.cc_dmg is required for unit {unit.get('name', 'unknown')}")
        can_kill_1_phase = target["cur_hp"] <= unit["cc_dmg"]

        # Priority 1: Can kill in 1 melee phase with highest threat
        if can_kill_1_phase and self._is_highest_threat_adjacent(target, all_targets):
            return base_reward + unit_rewards.get("attack_priority_1", 2.0)
        
        # Priority 2: Highest threat, lowest HP if multiple high threats
        if (self._is_highest_threat_adjacent(target, all_targets) and
            self._is_lowest_hp_among_adjacent_threats(target, all_targets)):
            return base_reward + unit_rewards.get("attack_priority_2", 1.5)
        
        return base_reward
    
    def get_kill_bonus_reward(self, unit, target, damage_dealt):
        """Calculate kill bonus rewards using existing parameter names."""
        unit_rewards = self._get_unit_rewards(unit)
        
        if target["cur_hp"] - damage_dealt <= 0:  # Target will be killed
            phase = self._get_current_phase()
            
            if phase == "shoot":
                base_kill = unit_rewards.get("enemy_killed_r", 5.0)
            else:  # melee combat
                base_kill = unit_rewards.get("enemy_killed_m", 5.0)
            
            # No overkill bonus
            if target["cur_hp"] == damage_dealt:
                if phase == "shoot":
                    base_kill += unit_rewards.get("enemy_killed_no_overkill_r", 7.0) - unit_rewards.get("enemy_killed_r", 5.0)
                else:
                    base_kill += unit_rewards.get("enemy_killed_no_overkill_m", 7.0) - unit_rewards.get("enemy_killed_m", 5.0)
            
            # Lowest HP target bonus
            if self._was_lowest_hp_target(target):
                if phase == "shoot":
                    base_kill += unit_rewards.get("enemy_killed_lowests_hp_r", 6.0) - unit_rewards.get("enemy_killed_r", 5.0)
                else:
                    base_kill += unit_rewards.get("enemy_killed_lowests_hp_m", 6.0) - unit_rewards.get("enemy_killed_m", 5.0)
            
            return base_kill
        
        return 0.0
    
    def get_movement_reward(self, unit, old_pos, new_pos, tactical_context):
        """Calculate movement rewards based on tactical positioning."""
        unit_rewards = self._get_unit_rewards(unit)
        
        if unit.get("is_ranged", False):
            # Ranged unit movement priorities
            if tactical_context.get("moved_to_optimal_range"):
                return unit_rewards.get("move_to_rng", 0.8)
            elif tactical_context.get("moved_closer"):
                return unit_rewards.get("move_close", 0.2)
            elif tactical_context.get("moved_away"):
                return unit_rewards.get("move_away", 0.1)
            elif tactical_context.get("moved_to_safety"):
                return unit_rewards.get("move_to_safe", 0.3)
        else:
            # Melee unit movement priorities
            if tactical_context.get("moved_to_charge_range"):
                return unit_rewards.get("move_to_charge", 0.8)
            elif tactical_context.get("moved_closer"):
                return unit_rewards.get("move_close", 0.3)
            elif tactical_context.get("moved_away"):
                return unit_rewards.get("move_away", -0.2)
        
        return 0.0
    
    def _get_unit_rewards(self, unit):
        """Get reward configuration for unit type."""
        if unit.get("is_ranged", False):
            return self.rewards_config.get("SpaceMarineRanged", {})
        else:
            return self.rewards_config.get("SpaceMarineMelee", {})
    
    def _is_highest_threat_in_range(self, target, all_targets):
        """Check if target has highest threat score among all targets in range."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_highest_threat_adjacent(self, target, adjacent_targets):
        """Check if target has highest threat score among adjacent targets."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in adjacent_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat > target_threat:
                    return False
        return True
    
    def _is_lowest_hp_high_threat(self, target, all_targets):
        """Check if target has lowest HP among high threat targets."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        max_threat = max(max(t["rng_dmg"], t["cc_dmg"]) for t in all_targets 
                        if "rng_dmg" in t and "cc_dmg" in t)
        
        if target_threat == max_threat:
            for other in all_targets:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat == max_threat and other["cur_hp"] < target["cur_hp"]:
                    return False
            return True
        return False
    
    def _is_lowest_hp_among_threats(self, target, all_targets):
        """Check if target has lowest HP among targets of same threat level.""" 
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if "rng_dmg" not in other or "cc_dmg" not in other:
                raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
            other_threat = max(other["rng_dmg"], other["cc_dmg"])
            if other_threat == target_threat and other["cur_hp"] < target["cur_hp"]:
                return False
        return True
    
    def _is_highest_hp_among_threats(self, target, all_targets):
        """Check if target has highest HP among targets of same threat level."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in all_targets:
            if "rng_dmg" not in other or "cc_dmg" not in other:
                raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
            other_threat = max(other["rng_dmg"], other["cc_dmg"])
            if other_threat == target_threat and other["cur_hp"] > target["cur_hp"]:
                return False
        return True
    
    def _is_lowest_hp_among_adjacent_threats(self, target, adjacent_targets):
        """Check if target has lowest HP among adjacent targets of same threat level."""
        if "rng_dmg" not in target:
            raise ValueError(f"target.rng_dmg is required for unit {target.get('name', 'unknown')}")
        if "cc_dmg" not in target:
            raise ValueError(f"target.cc_dmg is required for unit {target.get('name', 'unknown')}")
        target_threat = max(target["rng_dmg"], target["cc_dmg"])
        for other in adjacent_targets:
            if other != target:
                if "rng_dmg" not in other or "cc_dmg" not in other:
                    raise ValueError(f"other target missing required damage fields: {other.get('name', 'unknown')}")
                other_threat = max(other["rng_dmg"], other["cc_dmg"])
                if other_threat == target_threat and other["cur_hp"] < target["cur_hp"]:
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
        return "shoot"  # Default for now
    
    def _was_lowest_hp_target(self, target):
        """Check if this was the lowest HP target when action was taken."""
        # This would need access to game state at time of action
        return False  # Default for now