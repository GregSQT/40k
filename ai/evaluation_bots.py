#!/usr/bin/env python3
"""
ai/evaluation_bots.py - Simple tactical bots for measuring agent performance
"""

import random
from typing import Dict, List, Tuple, Any, Optional


class RandomBot:
    """Picks random valid actions"""
    
    def select_action(self, valid_actions: List[int]) -> int:
        return random.choice(valid_actions) if valid_actions else 7
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]]) -> Tuple[int, int]:
        return random.choice(valid_destinations) if valid_destinations else (unit["col"], unit["row"])
    
    def select_shooting_target(self, valid_targets: List[str]) -> str:
        return random.choice(valid_targets) if valid_targets else ""


class GreedyBot:
    """Shoots nearest enemy, moves toward closest target"""

    def __init__(self, randomness: float = 0.0):
        """
        Initialize GreedyBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of greedy choice.
                       0.0 = pure greedy, 0.15 = 15% random actions (recommended for training)
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]

    def select_action(self, valid_actions: List[int]) -> int:
        # Add randomness to prevent overfitting
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions) if valid_actions else 7

        # Prefer shoot > move > wait
        if 4 in valid_actions:  # Shoot
            return 4
        elif 0 in valid_actions:  # Move
            return 0
        else:
            return valid_actions[0] if valid_actions else 7
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]]) -> Tuple[int, int]:
        if not valid_destinations:
            return (unit["col"], unit["row"])

        # Add randomness to movement
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        # Move toward nearest enemy (simplified - just pick first destination)
        return valid_destinations[0]
    
    def select_shooting_target(self, valid_targets: List[str], game_state=None) -> str:
        """
        Greedy target selection: prioritize low HP enemies.
        If game_state provided, actually check HP. Otherwise use first target.
        """
        if not valid_targets:
            return ""

        # Add randomness to target selection
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if game_state:
            min_hp = float('inf')
            best_target = valid_targets[0]

            for target_id in valid_targets:
                target = self._get_unit_by_id(game_state, target_id)
                if target and target.get('HP_CUR', float('inf')) < min_hp:
                    min_hp = target['HP_CUR']
                    best_target = target_id

            return best_target

        return valid_targets[0]
    
    def _get_unit_by_id(self, game_state, unit_id: str):
        """Helper to find unit by ID."""
        for unit in game_state.get('units', []):
            if str(unit['id']) == str(unit_id):
                return unit
        return None


class DefensiveBot:
    """Prioritizes survival, maintains distance"""

    def __init__(self, randomness: float = 0.0):
        """
        Initialize DefensiveBot with optional randomness.

        Args:
            randomness: Probability [0.0-1.0] of making a random move instead of defensive choice.
                       0.0 = pure defensive, 0.15 = 15% random actions (recommended for training)
        """
        self.randomness = max(0.0, min(1.0, randomness))  # Clamp to [0, 1]

    def select_action(self, valid_actions: List[int]) -> int:
        # Add randomness to prevent overfitting
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions) if valid_actions else 7

        # Conservative: shoot when possible, otherwise wait
        if 4 in valid_actions:  # Shoot
            return 4
        elif 7 in valid_actions:  # Wait
            return 7
        else:
            return valid_actions[0] if valid_actions else 7
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]]) -> Tuple[int, int]:
        if not valid_destinations:
            return (unit["col"], unit["row"])

        # Add randomness to movement
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        # Pick last destination (tends to move away)
        return valid_destinations[-1]
    
    def select_shooting_target(self, valid_targets: List[str]) -> str:
        if not valid_targets:
            return ""

        # Add randomness to target selection
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        # Shoot first available target
        return valid_targets[0]
    
    def select_action_with_state(self, valid_actions: List[int], game_state) -> int:
        """
        Enhanced defensive logic with threat awareness.
        Prioritize shooting threats, move away from danger zones.
        """
        current_player = game_state.get('current_player', 1)
        
        active_unit = None
        for unit in game_state.get('units', []):
            if unit['player'] == current_player and unit['HP_CUR'] > 0:
                active_unit = unit
                break
        
        if not active_unit:
            return valid_actions[0] if valid_actions else 7
        
        nearby_threats = self._count_nearby_threats(active_unit, game_state)
        
        if nearby_threats > 0 and 4 in valid_actions:
            return 4
        
        if nearby_threats > 1 and 0 in valid_actions:
            return 0
        
        return self.select_action(valid_actions)
    
    def _count_nearby_threats(self, unit, game_state) -> int:
        """Count enemy units within threatening range."""
        threat_count = 0
        threat_range = 12
        
        for enemy in game_state.get('units', []):
            if enemy['player'] != unit['player'] and enemy['HP_CUR'] > 0:
                distance = abs(enemy['col'] - unit['col']) + abs(enemy['row'] - unit['row'])
                if distance <= threat_range:
                    threat_count += 1
        
        return threat_count