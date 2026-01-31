#!/usr/bin/env python3
"""
ai/evaluation_bots.py - Tactical bots for measuring agent performance

Bot Hierarchy (easiest to hardest):
1. RandomBot - Random actions (baseline)
2. GreedyBot - Shoots first, moves toward enemies
3. DefensiveBot - Shoots first, maintains distance
4. TacticalBot - Full phase awareness, optimal decisions (hardest)

All bots implement all 4 phases: MOVE, SHOOT, CHARGE, FIGHT
"""

import random
from typing import Dict, List, Tuple, Any, Optional
from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, get_unit_coordinates
from engine.phase_handlers.shared_utils import (
    is_unit_alive, get_hp_from_cache,
    get_unit_position, require_unit_position,
)


class RandomBot:
    """Picks random valid actions, but prioritizes shooting when available"""

    def select_action(self, valid_actions: List[int]) -> int:
        # CRITICAL FIX: Prioritize shooting in shoot phase (like all other bots)
        # Without this, RandomBot has only 33% shoot rate vs 90%+ for other bots
        if 4 in valid_actions:  # Shoot action
            return 4
        # For other phases, pick randomly
        return random.choice(valid_actions) if valid_actions else 7

    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        if valid_destinations:
            return random.choice(valid_destinations)
        if game_state is not None:
            return require_unit_position(unit, game_state)
        return get_unit_coordinates(unit)

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
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

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
                if target and is_unit_alive(str(target["id"]), game_state):
                    hp = get_hp_from_cache(str(target["id"]), game_state)
                    if hp is not None and hp < min_hp:
                        min_hp = hp
                        best_target = target_id

            return best_target

        return valid_targets[0]
    
    def _get_unit_by_id(self, game_state, unit_id: str):
        """Helper to find unit by ID."""
        for unit in require_key(game_state, 'units'):
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
    
    def select_movement_destination(self, unit, valid_destinations: List[Tuple[int, int]], game_state=None) -> Tuple[int, int]:
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

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
        current_player = require_key(game_state, 'current_player')
        
        active_unit = None
        for unit in require_key(game_state, 'units'):
            if unit['player'] == current_player and is_unit_alive(str(unit["id"]), game_state):
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

        for enemy in require_key(game_state, 'units'):
            if enemy['player'] != unit['player'] and is_unit_alive(str(enemy["id"]), game_state):
                distance = calculate_hex_distance(unit['col'], unit['row'], enemy['col'], enemy['row'])
                if distance <= threat_range:
                    threat_count += 1

        return threat_count


class TacticalBot:
    """
    Advanced tactical bot that properly uses all 4 game phases.

    This is the hardest bot to beat - it makes optimal decisions in each phase:
    - MOVE: Advances toward enemies if out of range, retreats if wounded
    - SHOOT: Always shoots if targets available, prioritizes wounded enemies
    - CHARGE: Charges if melee is advantageous (high CC_DMG vs target HP)
    - FIGHT: Always fights when in melee, prioritizes killing wounded enemies

    Use this bot to test if agents learn proper multi-phase coordination.
    """

    def __init__(self, randomness: float = 0.1):
        """
        Initialize TacticalBot.

        Args:
            randomness: Probability [0.0-1.0] of making suboptimal choice.
                       0.1 = 10% random (recommended for training diversity)
        """
        self.randomness = max(0.0, min(1.0, randomness))

    def select_action(self, valid_actions: List[int], game_state: Dict = None, phase: str = None) -> int:
        """
        Select action based on current phase and game state.

        Args:
            valid_actions: List of valid action indices
            game_state: Current game state (required for smart decisions)
            phase: Current phase ('move', 'shoot', 'charge', 'fight')
        """
        if not valid_actions:
            return 7  # Wait

        # Random action for diversity
        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_actions)

        # Phase-specific logic
        if phase == 'move':
            return self._select_move_action(valid_actions, game_state)
        elif phase == 'shoot':
            return self._select_shoot_action(valid_actions, game_state)
        elif phase == 'charge':
            return self._select_charge_action(valid_actions, game_state)
        elif phase == 'fight':
            return self._select_fight_action(valid_actions, game_state)
        else:
            # Fallback: prefer combat actions
            if 4 in valid_actions:  # Shoot
                return 4
            if 5 in valid_actions:  # Charge
                return 5
            if 6 in valid_actions:  # Fight
                return 6
            if 0 in valid_actions:  # Move
                return 0
            return valid_actions[0]

    def _select_move_action(self, valid_actions: List[int], game_state: Dict) -> int:
        """Movement phase: advance if out of range, reposition for LoS."""
        # Always prefer moving if we can improve position
        if 0 in valid_actions:
            return 0
        if 7 in valid_actions:  # Wait
            return 7
        return valid_actions[0] if valid_actions else 7

    def _select_shoot_action(self, valid_actions: List[int], game_state: Dict) -> int:
        """Shooting phase: always shoot if targets available."""
        if 4 in valid_actions:  # Shoot
            return 4
        if 7 in valid_actions:  # Wait/Skip
            return 7
        return valid_actions[0] if valid_actions else 7

    def _select_charge_action(self, valid_actions: List[int], game_state: Dict) -> int:
        """Charge phase: charge if melee is advantageous."""
        # Check if charging is beneficial
        if game_state and 5 in valid_actions:
            active_unit = self._get_active_unit(game_state)
            if active_unit:
                # Charge if unit has good melee damage
                cc_dmg = require_key(active_unit, 'CC_DMG')
                if cc_dmg >= 2:  # Worth charging
                    return 5

        # Skip charge if not beneficial
        if 7 in valid_actions:
            return 7
        return valid_actions[0] if valid_actions else 7

    def _select_fight_action(self, valid_actions: List[int], game_state: Dict) -> int:
        """Fight phase: always fight when in melee."""
        if 6 in valid_actions:  # Fight
            return 6
        if 7 in valid_actions:  # Wait
            return 7
        return valid_actions[0] if valid_actions else 7

    def select_movement_destination(self, unit: Dict, valid_destinations: List[Tuple[int, int]],
                                     game_state: Dict = None) -> Tuple[int, int]:
        """
        Select best movement destination.

        Strategy:
        - If no enemies in range: move toward nearest enemy
        - If enemies in range: move to position with best LoS
        - If wounded: move away from melee threats
        """
        if not valid_destinations:
            if game_state is not None:
                return require_unit_position(unit, game_state)
            return get_unit_coordinates(unit)

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_destinations)

        if not game_state:
            return valid_destinations[0]

        # Find nearest enemy
        nearest_enemy = self._find_nearest_enemy(unit, game_state)
        if not nearest_enemy:
            return valid_destinations[0]

        # If wounded (< 50% HP), move away from melee units. Skip if unit dead (not in cache).
        hp_cur = get_hp_from_cache(str(unit["id"]), game_state)
        if hp_cur is None:
            return valid_destinations[0]
        hp_max = require_key(unit, "HP_MAX")
        if hp_max <= 0 or hp_cur < hp_max * 0.5:
            return self._find_safest_position(unit, valid_destinations, game_state)

        # Otherwise, move toward optimal shooting range
        return self._find_best_offensive_position(unit, valid_destinations, nearest_enemy, game_state)

    def select_shooting_target(self, valid_targets: List[str], game_state: Dict = None) -> str:
        """
        Select best shooting target.

        Priority:
        1. Target that can be killed this turn (HP <= our damage)
        2. Lowest HP target (focus fire)
        3. Highest threat target (highest damage output)
        """
        if not valid_targets:
            return ""

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if not game_state:
            return valid_targets[0]

        active_unit = self._get_active_unit(game_state)
        if not active_unit:
            return valid_targets[0]

        our_damage = require_key(active_unit, 'RNG_DMG')
        best_target = valid_targets[0]
        best_score = -float('inf')

        for target_id in valid_targets:
            target = self._get_unit_by_id(game_state, target_id)
            if not target or not is_unit_alive(str(target["id"]), game_state):
                continue

            hp = get_hp_from_cache(str(target["id"]), game_state)
            if hp is None:
                continue
            threat = max(require_key(target, 'RNG_DMG'), require_key(target, 'CC_DMG'))

            # Scoring: killable > low HP > high threat
            score = 0
            if hp <= our_damage:
                score += 1000  # Can kill
            score += (10 - hp) * 10  # Lower HP = higher score
            score += threat * 5  # Higher threat = higher score

            if score > best_score:
                best_score = score
                best_target = target_id

        return best_target

    def select_charge_target(self, valid_targets: List[str], game_state: Dict = None) -> str:
        """
        Select best charge target.

        Priority:
        1. Target that can be killed in melee
        2. Highest threat ranged unit (silence their guns)
        """
        if not valid_targets:
            return ""

        if self.randomness > 0 and random.random() < self.randomness:
            return random.choice(valid_targets)

        if not game_state:
            return valid_targets[0]

        active_unit = self._get_active_unit(game_state)
        if not active_unit:
            return valid_targets[0]

        our_melee_damage = require_key(active_unit, 'CC_DMG')
        best_target = valid_targets[0]
        best_score = -float('inf')

        for target_id in valid_targets:
            target = self._get_unit_by_id(game_state, target_id)
            if not target or not is_unit_alive(str(target["id"]), game_state):
                continue

            hp = get_hp_from_cache(str(target["id"]), game_state)
            if hp is None:
                continue
            ranged_threat = require_key(target, 'RNG_DMG')

            # Scoring: killable > high ranged threat
            score = 0
            if hp <= our_melee_damage:
                score += 1000  # Can kill in melee
            score += ranged_threat * 20  # Prioritize silencing ranged units

            if score > best_score:
                best_score = score
                best_target = target_id

        return best_target

    def select_fight_target(self, valid_targets: List[str], game_state: Dict = None) -> str:
        """Select best melee target - same logic as shooting but for melee."""
        return self.select_shooting_target(valid_targets, game_state)

    # Helper methods

    def _get_active_unit(self, game_state: Dict) -> Optional[Dict]:
        """Get the currently active unit."""
        current_player = require_key(game_state, 'current_player')
        for unit in require_key(game_state, 'units'):
            if unit.get('player') == current_player and is_unit_alive(str(unit.get("id")), game_state):
                return unit
        return None

    def _get_unit_by_id(self, game_state: Dict, unit_id: str) -> Optional[Dict]:
        """Find unit by ID."""
        for unit in require_key(game_state, 'units'):
            if str(unit.get('id')) == str(unit_id):
                return unit
        return None

    def _find_nearest_enemy(self, unit: Dict, game_state: Dict) -> Optional[Dict]:
        """Find nearest enemy unit."""
        nearest = None
        min_dist = float('inf')

        for enemy in require_key(game_state, 'units'):
            if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                dist = calculate_hex_distance(
                    unit['col'], unit['row'],
                    enemy['col'], enemy['row']
                )
                if dist < min_dist:
                    min_dist = dist
                    nearest = enemy

        return nearest

    def _find_safest_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                               game_state: Dict) -> Tuple[int, int]:
        """Find position furthest from melee threats."""
        best_pos = destinations[0]
        max_min_dist = -1

        for col, row in destinations:
            min_enemy_dist = float('inf')
            for enemy in require_key(game_state, 'units'):
                if enemy.get('player') != unit.get('player') and is_unit_alive(str(enemy.get("id")), game_state):
                    # Only consider melee threats
                    if require_key(enemy, 'CC_DMG') > require_key(enemy, 'RNG_DMG'):
                        dist = calculate_hex_distance(col, row, enemy['col'], enemy['row'])
                        min_enemy_dist = min(min_enemy_dist, dist)

            if min_enemy_dist > max_min_dist:
                max_min_dist = min_enemy_dist
                best_pos = (col, row)

        return best_pos

    def _find_best_offensive_position(self, unit: Dict, destinations: List[Tuple[int, int]],
                                       target: Dict, game_state: Dict) -> Tuple[int, int]:
        """Find position closest to target but within shooting range."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
        from engine.utils.weapon_helpers import get_max_ranged_range
        rng_weapons = require_key(unit, 'RNG_WEAPONS')
        rng_rng = get_max_ranged_range(unit) if rng_weapons else 0
        best_pos = destinations[0]
        best_dist = float('inf')

        for col, row in destinations:
            dist = calculate_hex_distance(col, row, target['col'], target['row'])
            # Prefer positions within shooting range
            if dist <= rng_rng and dist < best_dist:
                best_dist = dist
                best_pos = (col, row)

        # If no position in range, get closest
        if best_dist == float('inf'):
            for col, row in destinations:
                dist = calculate_hex_distance(col, row, target['col'], target['row'])
                if dist < best_dist:
                    best_dist = dist
                    best_pos = (col, row)

        return best_pos