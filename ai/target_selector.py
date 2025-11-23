#!/usr/bin/env python3
"""
ai/target_selector.py - Tactical Target Selection System

Separates target selection (forward decision) from reward calculation (backward feedback).
Used by PvE AI to select targets using tactical heuristics, not rewards.
"""

from typing import Dict, List, Any
from engine.combat_utils import calculate_hex_distance


class TargetSelector:
    """
    Tactical target selection using heuristics, not rewards.
    
    Design: Reward mapper is for TRAINING FEEDBACK (backward).
            Target selector is for ACTION SELECTION (forward).
    """
    
    def __init__(self, tactical_weights: Dict[str, float]):
        """
        Initialize with tactical weights (not rewards).
        
        Example weights:
        {
            "kill_probability": 2.0,  # Prefer targets we can kill
            "threat_level": 1.5,      # Prefer dangerous targets
            "hp_ratio": 1.0,          # Prefer wounded targets
            "army_threat": 1.2        # Consider team-wide danger
        }
        """
        self.weights = tactical_weights
    
    def select_best_target(self, shooter: Dict[str, Any], 
                          valid_targets: List[str],
                          game_state: Dict[str, Any]) -> str:
        """
        Select best target using tactical scoring.
        
        Args:
            shooter: Unit selecting target
            valid_targets: List of valid target IDs
            game_state: Current game state
        
        Returns:
            Best target ID
        """
        if not valid_targets:
            return ""
        
        best_target = valid_targets[0]
        best_score = -999999.0
        
        for target_id in valid_targets:
            target = self._get_unit_by_id(game_state, target_id)
            if not target:
                continue
            
            # Calculate tactical score (NOT reward)
            score = self._calculate_tactical_score(shooter, target, game_state)
            
            if score > best_score:
                best_score = score
                best_target = target_id
        
        return best_target
    
    def _calculate_tactical_score(self, shooter: Dict[str, Any],
                                  target: Dict[str, Any],
                                  game_state: Dict[str, Any]) -> float:
        """
        Calculate tactical priority score using heuristics.
        
        Components:
        1. Kill probability (can we kill this turn?)
        2. Threat level (how dangerous is target?)
        3. HP ratio (finish wounded targets)
        4. Army-weighted threat (protect high-value units)
        """
        score = 0.0
        
        # Component 1: Kill probability
        kill_prob = self._estimate_kill_probability(shooter, target)
        score += self.weights.get("kill_probability", 2.0) * kill_prob
        
        # Component 2: Threat level
        threat = max(target.get("RNG_DMG", 0), target.get("CC_DMG", 0)) / 5.0
        score += self.weights.get("threat_level", 1.5) * threat
        
        # Component 3: HP ratio (prefer wounded)
        hp_ratio = target["HP_CUR"] / max(1, target["HP_MAX"])
        score += self.weights.get("hp_ratio", 1.0) * (1.0 - hp_ratio)
        
        # Component 4: Army-weighted threat
        army_threat = self._calculate_army_threat(target, game_state)
        score += self.weights.get("army_threat", 1.2) * army_threat
        
        return score
    
    def _estimate_kill_probability(self, shooter: Dict[str, Any],
                                   target: Dict[str, Any]) -> float:
        """Estimate probability of killing target (simplified W40K math)."""
        # Hit probability
        hit_target = shooter.get("RNG_ATK", 4)
        p_hit = max(0.0, (7 - hit_target) / 6.0)
        
        # Wound probability (simplified)
        strength = shooter.get("RNG_STR", 4)
        toughness = target.get("T", 4)
        if strength >= toughness * 2:
            p_wound = 5/6
        elif strength > toughness:
            p_wound = 4/6
        else:
            p_wound = 3/6
        
        # Expected damage
        num_attacks = shooter.get("RNG_NB", 1)
        damage_per_hit = shooter.get("RNG_DMG", 1)
        expected_damage = num_attacks * p_hit * p_wound * damage_per_hit
        
        # Kill probability
        if expected_damage >= target["HP_CUR"]:
            return 1.0
        else:
            return expected_damage / target["HP_CUR"]
    
    def _calculate_army_threat(self, target: Dict[str, Any],
                               game_state: Dict[str, Any]) -> float:
        """Calculate threat to entire friendly army."""
        my_player = game_state["current_player"]
        friendly_units = [u for u in game_state["units"] 
                         if u["player"] == my_player and u["HP_CUR"] > 0]
        
        if not friendly_units:
            return 0.0
        
        total_threat = 0.0
        for friendly in friendly_units:
            # Distance check
            distance = calculate_hex_distance(friendly["col"], friendly["row"], target["col"], target["row"])
            
            # Threat only if in range
            if distance <= target.get("RNG_RNG", 0):
                unit_value = friendly.get("VALUE", 10.0)
                threat_factor = max(target.get("RNG_DMG", 0), target.get("CC_DMG", 0)) / 5.0
                total_threat += unit_value * threat_factor / max(1, distance)
        
        return min(1.0, total_threat / 100.0)  # Normalize to 0-1
    
    @staticmethod
    def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
        """Helper to get unit by ID."""
        for unit in game_state["units"]:
            if unit["id"] == unit_id:
                return unit
        return None