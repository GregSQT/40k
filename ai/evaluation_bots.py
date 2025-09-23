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
    
    def select_action(self, valid_actions: List[int]) -> int:
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
        
        # Move toward nearest enemy (simplified - just pick first destination)
        return valid_destinations[0]
    
    def select_shooting_target(self, valid_targets: List[str]) -> str:
        # Shoot first available target
        return valid_targets[0] if valid_targets else ""


class DefensiveBot:
    """Prioritizes survival, maintains distance"""
    
    def select_action(self, valid_actions: List[int]) -> int:
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
        
        # Pick last destination (tends to move away)
        return valid_destinations[-1]
    
    def select_shooting_target(self, valid_targets: List[str]) -> str:
        # Shoot first available target
        return valid_targets[0] if valid_targets else ""