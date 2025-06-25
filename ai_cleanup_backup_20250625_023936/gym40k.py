#!/usr/bin/env python3
"""
ai/gym40k.py - Improved W40K environment with proper game logic
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
import json
import os
import random

class W40KEnv(gym.Env):
    """Improved W40K environment with proper win conditions and combat."""
    
    def __init__(self):
        super().__init__()
        
        # Load scenario
        scenario_path = os.path.join(os.path.dirname(__file__), "scenario.json")
        if os.path.exists(scenario_path):
            with open(scenario_path, 'r') as f:
                scenario_units = json.load(f)
        else:
            # Default scenario
            scenario_units = [
                {"id": 1, "unit_type": "Intercessor", "player": 0, "col": 23, "row": 12, "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1, "is_ranged": True, "is_melee": False, "alive": True},
                {"id": 2, "unit_type": "AssaultIntercessor", "player": 0, "col": 1, "row": 12, "cur_hp": 4, "hp_max": 4, "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2, "is_ranged": False, "is_melee": True, "alive": True},
                {"id": 3, "unit_type": "Intercessor", "player": 1, "col": 0, "row": 5, "cur_hp": 3, "hp_max": 3, "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1, "is_ranged": True, "is_melee": False, "alive": True},
                {"id": 4, "unit_type": "AssaultIntercessor", "player": 1, "col": 22, "row": 3, "cur_hp": 4, "hp_max": 4, "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2, "is_ranged": False, "is_melee": True, "alive": True}
            ]
        
        # Initialize units
        self.initial_units = scenario_units
        self.units = []
        self.reset_units()
        
        # Game settings
        self.board_size = (24, 18)
        self.max_turns = 100  # Increased from 52
        self.current_turn = 0
        self.current_player = 1  # AI is player 1
        self.game_over = False
        self.winner = None
        
        # RL spaces
        # Observation: 4 units * 7 features each = 28 features
        # Features: [player, col, row, cur_hp, alive, can_shoot, can_move]
        self.observation_space = spaces.Box(
            low=0, high=max(self.board_size[0], self.board_size[1], 10), 
            shape=(28,), dtype=np.float32
        )
        
        # Actions: 0=move_closer, 1=move_away, 2=move_safe, 3=shoot_closest, 
        #          4=shoot_weakest, 5=charge_closest, 6=wait, 7=attack_adjacent
        self.action_space = spaces.Discrete(8)
        
        # Episode tracking
        self.episode_logs = []
        self.current_log = []
        
    def reset_units(self):
        """Reset units to initial state."""
        self.units = []
        for unit_data in self.initial_units:
            unit = {
                "id": unit_data["id"],
                "player": unit_data["player"],
                "col": unit_data["col"],
                "row": unit_data["row"],
                "cur_hp": unit_data["hp_max"],
                "hp_max": unit_data["hp_max"],
                "move": unit_data.get("move", 6),
                "rng_rng": unit_data.get("rng_rng", 8),
                "rng_dmg": unit_data.get("rng_dmg", 2),
                "cc_dmg": unit_data.get("cc_dmg", 1),
                "is_ranged": unit_data.get("is_ranged", True),
                "is_melee": unit_data.get("is_melee", False),
                "alive": True,
                "unit_type": unit_data.get("unit_type", "Unknown")
            }
            self.units.append(unit)
    
    def reset(self, *, seed=None, options=None):
        """Reset the environment."""
        super().reset(seed=seed)
        
        self.reset_units()
        self.current_turn = 0
        self.current_player = 1  # AI goes first
        self.game_over = False
        self.winner = None
        
        # Save previous episode log
        if self.current_log:
            total_reward = sum(step.get('reward', 0) for step in self.current_log)
            self.episode_logs.append((self.current_log.copy(), total_reward))
            # Keep only last 10 episodes
            if len(self.episode_logs) > 10:
                self.episode_logs = self.episode_logs[-10:]
        
        self.current_log = []
        
        obs = self._get_obs()
        return obs, {}
    
    def _get_obs(self):
        """Get observation vector."""
        obs = []
        for unit in self.units:
            obs.extend([
                unit["player"],
                unit["col"],
                unit["row"], 
                unit["cur_hp"],
                1.0 if unit["alive"] else 0.0,
                1.0 if self._can_shoot(unit) else 0.0,
                1.0 if self._can_move(unit) else 0.0
            ])
        # Pad to 28 features if needed
        while len(obs) < 28:
            obs.append(0.0)
        return np.array(obs[:28], dtype=np.float32)
    
    def _can_shoot(self, unit):
        """Check if unit can shoot at enemies."""
        if not unit["alive"] or not unit["is_ranged"]:
            return False
        enemies = [u for u in self.units if u["player"] != unit["player"] and u["alive"]]
        for enemy in enemies:
            dist = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if dist <= unit["rng_rng"]:
                return True
        return False
    
    def _can_move(self, unit):
        """Check if unit can move."""
        return unit["alive"]
    
    def _get_distance(self, unit1, unit2):
        """Get Chebyshev distance between units."""
        return max(abs(unit1["col"] - unit2["col"]), abs(unit1["row"] - unit2["row"]))
    
    def _get_enemies(self, player):
        """Get alive enemy units."""
        return [u for u in self.units if u["player"] != player and u["alive"]]
    
    def _get_allies(self, player):
        """Get alive ally units."""
        return [u for u in self.units if u["player"] == player and u["alive"]]
    
    def _move_toward_target(self, unit, target):
        """Move unit toward target."""
        if not unit["alive"]:
            return
        
        # Simple movement logic
        dx = 0
        dy = 0
        if target["col"] > unit["col"]:
            dx = 1
        elif target["col"] < unit["col"]:
            dx = -1
            
        if target["row"] > unit["row"]:
            dy = 1
        elif target["row"] < unit["row"]:
            dy = -1
        
        # Check bounds and collision
        new_col = max(0, min(self.board_size[0] - 1, unit["col"] + dx))
        new_row = max(0, min(self.board_size[1] - 1, unit["row"] + dy))
        
        # Check if position is occupied
        occupied = any(u["col"] == new_col and u["row"] == new_row and u["alive"] and u["id"] != unit["id"] 
                      for u in self.units)
        
        if not occupied:
            unit["col"] = new_col
            unit["row"] = new_row
    
    def _move_away_from_enemies(self, unit):
        """Move unit away from enemies."""
        if not unit["alive"]:
            return
            
        enemies = self._get_enemies(unit["player"])
        if not enemies:
            return
        
        # Find direction away from closest enemy
        closest_enemy = min(enemies, key=lambda e: self._get_distance(unit, e))
        
        dx = 0
        dy = 0
        if closest_enemy["col"] > unit["col"]:
            dx = -1
        elif closest_enemy["col"] < unit["col"]:
            dx = 1
            
        if closest_enemy["row"] > unit["row"]:
            dy = -1
        elif closest_enemy["row"] < unit["row"]:
            dy = 1
        
        # Apply movement
        new_col = max(0, min(self.board_size[0] - 1, unit["col"] + dx))
        new_row = max(0, min(self.board_size[1] - 1, unit["row"] + dy))
        
        occupied = any(u["col"] == new_col and u["row"] == new_row and u["alive"] and u["id"] != unit["id"] 
                      for u in self.units)
        
        if not occupied:
            unit["col"] = new_col
            unit["row"] = new_row
    
    def _shoot_at_target(self, unit, target):
        """Unit shoots at target."""
        if not unit["alive"] or not target["alive"]:
            return 0
        
        dist = self._get_distance(unit, target)
        if dist > unit["rng_rng"]:
            return 0  # Out of range
        
        # Apply damage
        damage = unit["rng_dmg"]
        target["cur_hp"] -= damage
        
        if target["cur_hp"] <= 0:
            target["cur_hp"] = 0
            target["alive"] = False
            return damage + 1.0  # Bonus for kill
        
        return damage * 0.5  # Partial reward for damage
    
    def _attack_adjacent(self, unit):
        """Attack adjacent enemy."""
        if not unit["alive"]:
            return 0
        
        enemies = self._get_enemies(unit["player"])
        adjacent_enemies = [e for e in enemies if self._get_distance(unit, e) == 1]
        
        if not adjacent_enemies:
            return -0.1  # Penalty for invalid action
        
        # Attack weakest adjacent enemy
        target = min(adjacent_enemies, key=lambda e: e["cur_hp"])
        damage = unit["cc_dmg"]
        target["cur_hp"] -= damage
        
        if target["cur_hp"] <= 0:
            target["cur_hp"] = 0
            target["alive"] = False
            return damage + 1.0  # Bonus for kill
        
        return damage * 0.5  # Partial reward for damage
    
    def step(self, action):
        """Execute one step."""
        if self.game_over:
            return self._get_obs(), 0, True, False, {"winner": self.winner}
        
        # Get AI unit (player 1)
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        if not ai_units:
            self.game_over = True
            self.winner = 0
            return self._get_obs(), -10.0, True, False, {"winner": self.winner}
        
        # Pick first alive AI unit for simplicity
        ai_unit = ai_units[0]
        enemies = self._get_enemies(1)
        
        reward = 0.0
        
        # Execute action
        if action == 0:  # move_closer
            if enemies:
                closest = min(enemies, key=lambda e: self._get_distance(ai_unit, e))
                self._move_toward_target(ai_unit, closest)
                reward = 0.1
            else:
                reward = -0.1
                
        elif action == 1:  # move_away
            self._move_away_from_enemies(ai_unit)
            reward = -0.05  # Generally not a good strategy
            
        elif action == 2:  # move_safe (random movement)
            # Simple safe movement - random direction
            dx = random.choice([-1, 0, 1])
            dy = random.choice([-1, 0, 1])
            new_col = max(0, min(self.board_size[0] - 1, ai_unit["col"] + dx))
            new_row = max(0, min(self.board_size[1] - 1, ai_unit["row"] + dy))
            
            occupied = any(u["col"] == new_col and u["row"] == new_row and u["alive"] and u["id"] != ai_unit["id"] 
                          for u in self.units)
            if not occupied:
                ai_unit["col"] = new_col
                ai_unit["row"] = new_row
            reward = 0.05
            
        elif action == 3:  # shoot_closest
            if enemies and ai_unit["is_ranged"]:
                closest = min(enemies, key=lambda e: self._get_distance(ai_unit, e))
                reward = self._shoot_at_target(ai_unit, closest)
            else:
                reward = -0.2  # Penalty for invalid action
                
        elif action == 4:  # shoot_weakest
            if enemies and ai_unit["is_ranged"]:
                weakest = min(enemies, key=lambda e: e["cur_hp"])
                reward = self._shoot_at_target(ai_unit, weakest)
            else:
                reward = -0.2
                
        elif action == 5:  # charge_closest (move toward and attack if adjacent)
            if enemies:
                closest = min(enemies, key=lambda e: self._get_distance(ai_unit, e))
                self._move_toward_target(ai_unit, closest)
                if self._get_distance(ai_unit, closest) == 1:
                    reward = self._attack_adjacent(ai_unit)
                else:
                    reward = 0.1
            else:
                reward = -0.1
                
        elif action == 6:  # wait
            reward = -0.5  # Strong penalty for waiting
            
        elif action == 7:  # attack_adjacent
            reward = self._attack_adjacent(ai_unit)
        
        # Enemy turn (simple scripted behavior)
        self._enemy_turn()
        
        # Check win conditions
        ai_alive = len([u for u in self.units if u["player"] == 1 and u["alive"]])
        enemy_alive = len([u for u in self.units if u["player"] == 0 and u["alive"]])
        
        if ai_alive == 0:
            self.game_over = True
            self.winner = 0
            reward -= 5.0  # Big penalty for losing
        elif enemy_alive == 0:
            self.game_over = True
            self.winner = 1
            reward += 10.0  # Big reward for winning
        
        # Turn limit check
        self.current_turn += 1
        if self.current_turn >= self.max_turns:
            self.game_over = True
            self.winner = None  # Draw
            reward -= 1.0  # Penalty for not winning quickly
        
        # Log this step
        self.current_log.append({
            "turn": self.current_turn,
            "action": int(action),
            "reward": float(reward),
            "ai_units_alive": ai_alive,
            "enemy_units_alive": enemy_alive,
            "game_over": self.game_over
        })
        
        obs = self._get_obs()
        return obs, reward, self.game_over, False, {"winner": self.winner}
    
    def _enemy_turn(self):
        """Simple scripted enemy behavior."""
        enemy_units = [u for u in self.units if u["player"] == 0 and u["alive"]]
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        
        for enemy in enemy_units:
            if not ai_units:
                break
                
            # Simple AI: move toward closest AI unit and attack if possible
            closest_ai = min(ai_units, key=lambda u: self._get_distance(enemy, u))
            dist = self._get_distance(enemy, closest_ai)
            
            # Try to shoot if in range
            if enemy["is_ranged"] and dist <= enemy["rng_rng"]:
                damage = enemy["rng_dmg"]
                closest_ai["cur_hp"] -= damage
                if closest_ai["cur_hp"] <= 0:
                    closest_ai["cur_hp"] = 0
                    closest_ai["alive"] = False
                    ai_units.remove(closest_ai)
            # Try melee attack if adjacent
            elif dist == 1:
                damage = enemy["cc_dmg"]
                closest_ai["cur_hp"] -= damage
                if closest_ai["cur_hp"] <= 0:
                    closest_ai["cur_hp"] = 0
                    closest_ai["alive"] = False
                    ai_units.remove(closest_ai)
            # Otherwise move closer
            else:
                self._move_toward_target(enemy, closest_ai)
    
    def close(self):
        """Clean up."""
        pass
    
    def did_win(self):
        """Check if AI won."""
        return self.winner == 1

if __name__ == "__main__":
    print("Testing improved W40KEnv...")
    env = W40KEnv()
    obs, _ = env.reset()
    print(f"✓ Observation shape: {obs.shape}")
    print(f"✓ Action space: {env.action_space}")
    print(f"✓ Initial units: {len(env.units)}")
    
    # Test a few actions
    for i in range(10):
        action = env.action_space.sample()
        obs, reward, done, truncated, info = env.step(action)
        ai_alive = len([u for u in env.units if u["player"] == 1 and u["alive"]])
        enemy_alive = len([u for u in env.units if u["player"] == 0 and u["alive"]])
        print(f"Step {i+1}: Action {action}, Reward {reward:.2f}, AI: {ai_alive}, Enemy: {enemy_alive}, Done: {done}")
        if done:
            print(f"Game ended! Winner: {info['winner']}")
            break
    
    env.close()
    print("✓ Test completed successfully!")