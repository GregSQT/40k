# ai/gym40k.py
#!/usr/bin/env python3
"""
ai/gym40k.py - COMPLETE W40K environment that loads unit stats from TypeScript files
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
import json
import os
import re
import random
import copy
from datetime import datetime
import sys
from pathlib import Path

script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from config_loader import get_config_loader

class W40KEnv(gym.Env):
    """Complete W40K environment with full game mechanics and unit loading from TypeScript files."""

    def __init__(self):
        super().__init__()
        
        # Load unit definitions from TypeScript files
        self.unit_definitions = self._load_unit_definitions()
        
        # Load scenario - ONLY position and player data
        scenario_path = os.path.join(os.path.dirname(__file__), "scenario.json")
        if os.path.exists(scenario_path):
            try:
                with open(scenario_path, 'r') as f:
                    scenario_data = json.load(f)
                    
                # Handle different JSON structures
                if isinstance(scenario_data, list):
                    scenario_units = scenario_data
                elif isinstance(scenario_data, dict):
                    if "units" in scenario_data:
                        scenario_units = scenario_data["units"]
                    else:
                        scenario_units = list(scenario_data.values())
                else:
                    raise ValueError(f"Scenario data must be list or dict, got {type(scenario_data)}")
                    
                # Validate that we have units data
                if not scenario_units:
                    raise ValueError("No units found in scenario data")
                    
                # Validate ONLY position/player fields - stats come from unit files
                required_fields = ["id", "unit_type", "player", "col", "row"]
                
                for i, unit_data in enumerate(scenario_units):
                    if not isinstance(unit_data, dict):
                        raise ValueError(f"Unit {i} is not a dictionary: {type(unit_data)} - {unit_data}")
                        
                    # Check required position fields only
                    for field in required_fields:
                        if field not in unit_data:
                            raise ValueError(f"Unit {i} missing required field '{field}'. Position fields required: {required_fields}")
                
                # Combine scenario position data with unit stats from TypeScript files
                complete_units = []
                for unit_data in scenario_units:
                    unit_type = unit_data["unit_type"]
                    
                    if unit_type not in self.unit_definitions:
                        raise ValueError(f"Unknown unit type: {unit_type}. Available types: {list(self.unit_definitions.keys())}")
                    
                    unit_stats = self.unit_definitions[unit_type]
                    
                    # Combine position data with stats
                    complete_unit = {
                        "id": unit_data["id"],
                        "unit_type": unit_type,
                        "player": unit_data["player"],
                        "col": unit_data["col"],
                        "row": unit_data["row"],
                        # Stats from TypeScript files
                        "hp_max": unit_stats["HP_MAX"],
                        "cur_hp": unit_stats["HP_MAX"],  # Start at full health
                        "move": unit_stats["MOVE"],
                        "rng_rng": unit_stats["RNG_RNG"],
                        "rng_dmg": unit_stats["RNG_DMG"],
                        "cc_dmg": unit_stats["CC_DMG"],
                        "is_ranged": unit_stats.get("is_ranged", True),
                        "is_melee": unit_stats.get("is_melee", False),
                        "alive": True
                    }
                    complete_units.append(complete_unit)
                
                print(f"✅ Loaded scenario with {len(complete_units)} units")
                
            except (json.JSONDecodeError, ValueError) as e:
                raise RuntimeError(f"Error loading scenario from {scenario_path}: {e}")
        else:
            raise FileNotFoundError(f"Scenario file not found at {scenario_path}")
        
        # Initialize units
        self.initial_units = complete_units
        self.units = []
        self.reset_units()
        
        # Game settings
        self.board_size = (24, 18)
        self.max_turns = 100
        self.current_turn = 0
        self.current_player = 1  # AI is player 1
        self.game_over = False
        self.winner = None
        
        # RL spaces
        self.observation_space = spaces.Box(
            low=0, high=max(self.board_size[0], self.board_size[1], 10), 
            shape=(28,), dtype=np.float32
        )
        
        self.action_space = spaces.Discrete(8)
        
        # Episode tracking
        self.episode_logs = []
        self.current_log = []
        
        # Replay logging
        self.replay_logging_enabled = False
        self.replay_data = {}
        self.replay_file = None

    def _load_unit_definitions(self):
        """Load unit definitions from TypeScript files."""
        unit_definitions = {}
        
        # Define unit file paths
        unit_files = {
            "Intercessor": "frontend/src/roster/spaceMarine/Intercessor.ts",
            "AssaultIntercessor": "frontend/src/roster/spaceMarine/AssaultIntercessor.ts"
        }
        
        for unit_type, file_path in unit_files.items():
            # Get project root directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir)
            full_path = os.path.join(project_root, file_path)
            
            if os.path.exists(full_path):
                stats = self._extract_unit_stats_from_ts(full_path, unit_type)
                if stats:
                    unit_definitions[unit_type] = stats
                    print(f"✅ Loaded {unit_type} stats from {file_path}")
                else:
                    print(f"⚠️  Failed to parse {unit_type} from {file_path}")
            else:
                print(f"⚠️  Unit file not found: {full_path}")
        
        # Fallback definitions if files not found
        if not unit_definitions:
            print("⚠️  No unit files found, using fallback definitions")
            unit_definitions = {
                "Intercessor": {
                    "HP_MAX": 3, "MOVE": 4, "RNG_RNG": 8, "RNG_DMG": 2, "CC_DMG": 1,
                    "is_ranged": True, "is_melee": False
                },
                "AssaultIntercessor": {
                    "HP_MAX": 4, "MOVE": 6, "RNG_RNG": 4, "RNG_DMG": 1, "CC_DMG": 2,
                    "is_ranged": False, "is_melee": True
                }
            }
        
        return unit_definitions

    def _extract_unit_stats_from_ts(self, file_path, unit_type):
        """Extract unit stats from TypeScript file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            stats = {}
            
            # Extract static properties using regex
            patterns = {
                "HP_MAX": r'static\s+HP_MAX\s*=\s*(\d+)',
                "MOVE": r'static\s+MOVE\s*=\s*(\d+)',
                "RNG_RNG": r'static\s+RNG_RNG\s*=\s*(\d+)',
                "RNG_DMG": r'static\s+RNG_DMG\s*=\s*(\d+)',
                "CC_DMG": r'static\s+CC_DMG\s*=\s*(\d+)'
            }
            
            for stat_name, pattern in patterns.items():
                match = re.search(pattern, content)
                if match:
                    stats[stat_name] = int(match.group(1))
                else:
                    # Set defaults based on unit type
                    if unit_type == "Intercessor":
                        defaults = {"HP_MAX": 3, "MOVE": 4, "RNG_RNG": 8, "RNG_DMG": 2, "CC_DMG": 1}
                    elif unit_type == "AssaultIntercessor":
                        defaults = {"HP_MAX": 4, "MOVE": 6, "RNG_RNG": 4, "RNG_DMG": 1, "CC_DMG": 2}
                    else:
                        defaults = {"HP_MAX": 3, "MOVE": 4, "RNG_RNG": 6, "RNG_DMG": 1, "CC_DMG": 1}
                    
                    stats[stat_name] = defaults.get(stat_name, 1)
            
            # Determine unit capabilities based on parent class
            if "SpaceMarineRangedUnit" in content:
                stats["is_ranged"] = True
                stats["is_melee"] = False
            elif "SpaceMarineMeleeUnit" in content:
                stats["is_ranged"] = False
                stats["is_melee"] = True
            else:
                # Default based on unit type
                if unit_type == "Intercessor":
                    stats["is_ranged"] = True
                    stats["is_melee"] = False
                elif unit_type == "AssaultIntercessor":
                    stats["is_ranged"] = False
                    stats["is_melee"] = True
                else:
                    stats["is_ranged"] = True
                    stats["is_melee"] = False
            
            return stats
            
        except Exception as e:
            print(f"⚠️  Error parsing {file_path}: {e}")
            return None

    def reset_units(self):
        """Reset units to initial state."""
        self.units = []
        for unit_data in self.initial_units:
            unit = {
                "id": unit_data["id"],
                "player": unit_data["player"],
                "col": unit_data["col"],
                "row": unit_data["row"],
                "cur_hp": unit_data["hp_max"],  # Reset to full health
                "hp_max": unit_data["hp_max"],
                "move": unit_data["move"],
                "rng_rng": unit_data["rng_rng"],
                "rng_dmg": unit_data["rng_dmg"],
                "cc_dmg": unit_data["cc_dmg"],
                "is_ranged": unit_data["is_ranged"],
                "is_melee": unit_data["is_melee"],
                "alive": True,  # Reset all units to alive
                "unit_type": unit_data["unit_type"]
            }
            self.units.append(unit)
        
        print(f"✅ Reset {len(self.units)} units")
    
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
        
        # Reset replay data if logging enabled
        if self.replay_logging_enabled:
            self.replay_data = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "map_size": {"width": self.board_size[0], "height": self.board_size[1]},
                    "max_turns": self.max_turns
                },
                "initial_state": {
                    "units": copy.deepcopy(self.initial_units),
                    "turn": 0,
                    "current_player": 1
                },
                "actions": [],
                "states": []
            }
        
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
    
    def _get_observation(self):
        """Get current observation (alternative method name)."""
        obs = np.zeros(28, dtype=np.float32)
        
        # Current player and turn
        obs[0] = self.current_player
        obs[1] = self.current_turn
        
        # Board state (simplified)
        obs[2] = self.board_size[0]  # width
        obs[3] = self.board_size[1]  # height
        
        # Unit counts
        player_units = [u for u in self.units if u["player"] == self.current_player and u["alive"]]
        enemy_units = [u for u in self.units if u["player"] != self.current_player and u["alive"]]
        
        obs[4] = len(player_units)
        obs[5] = len(enemy_units)
        
        # First AI unit position and stats (if exists)
        if player_units:
            unit = player_units[0]
            obs[6] = unit["col"]
            obs[7] = unit["row"]
            obs[8] = unit["cur_hp"]
            obs[9] = unit["hp_max"]
            obs[10] = unit["move"]
            obs[11] = unit["rng_rng"]
            obs[12] = unit["rng_dmg"]
            obs[13] = unit["cc_dmg"]
        
        # Nearest enemy position and stats (if exists)
        if enemy_units and player_units:
            ai_unit = player_units[0]
            distances = []
            for enemy in enemy_units:
                dist = abs(ai_unit["col"] - enemy["col"]) + abs(ai_unit["row"] - enemy["row"])
                distances.append((dist, enemy))
            
            if distances:
                _, nearest_enemy = min(distances)
                obs[14] = nearest_enemy["col"]
                obs[15] = nearest_enemy["row"]
                obs[16] = nearest_enemy["cur_hp"]
                obs[17] = nearest_enemy["hp_max"]
                obs[18] = abs(ai_unit["col"] - nearest_enemy["col"])
                obs[19] = abs(ai_unit["row"] - nearest_enemy["row"])
        
        # Game state
        obs[20] = 1.0 if self.game_over else 0.0
        obs[21] = self.winner if self.winner is not None else -1
        
        return obs
    
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
        # Calculate direction
        col_diff = target["col"] - unit["col"]
        row_diff = target["row"] - unit["row"]
        
        # Normalize to movement of 1 tile
        if abs(col_diff) > abs(row_diff):
            new_col = unit["col"] + (1 if col_diff > 0 else -1)
            new_row = unit["row"]
        else:
            new_col = unit["col"]
            new_row = unit["row"] + (1 if row_diff > 0 else -1)
        
        # Validate bounds
        if 0 <= new_col < self.board_size[0] and 0 <= new_row < self.board_size[1]:
            unit["col"] = new_col
            unit["row"] = new_row
            return True
        return False
    
    def _attack_target(self, attacker, target):
        """Execute attack between units."""
        if not attacker["alive"] or not target["alive"]:
            return False
            
        distance = self._get_distance(attacker, target)
        damage = 0
        
        # Ranged attack
        if attacker["is_ranged"] and distance <= attacker["rng_rng"]:
            damage = attacker["rng_dmg"]
        # Melee attack (adjacent)
        elif attacker["is_melee"] and distance <= 1:
            damage = attacker["cc_dmg"]
        
        if damage > 0:
            target["cur_hp"] = max(0, target["cur_hp"] - damage)
            if target["cur_hp"] <= 0:
                target["alive"] = False
            return True
        return False
    
    def _move_unit_closer(self, unit, enemies):
        """Move unit closer to nearest enemy."""
        if not enemies:
            return 0.0
        
        # Find nearest enemy
        min_dist = float('inf')
        target = None
        for enemy in enemies:
            dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
            if dist < min_dist:
                min_dist = dist
                target = enemy
        
        if target:
            # Move towards target
            if unit["col"] < target["col"]:
                unit["col"] = min(unit["col"] + unit["move"], target["col"])
            elif unit["col"] > target["col"]:
                unit["col"] = max(unit["col"] - unit["move"], target["col"])
            
            if unit["row"] < target["row"]:
                unit["row"] = min(unit["row"] + unit["move"], target["row"])
            elif unit["row"] > target["row"]:
                unit["row"] = max(unit["row"] - unit["move"], target["row"])
            
            # Keep within board bounds
            unit["col"] = max(0, min(unit["col"], self.board_size[0] - 1))
            unit["row"] = max(0, min(unit["row"], self.board_size[1] - 1))
            
            return 0.1  # Small reward for moving closer
        
        return 0.0
    
    def _move_unit_away(self, unit, enemies):
        """Move unit away from nearest enemy."""
        if not enemies:
            return 0.0
        
        # Find nearest enemy
        min_dist = float('inf')
        target = None
        for enemy in enemies:
            dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
            if dist < min_dist:
                min_dist = dist
                target = enemy
        
        if target:
            # Move away from target
            if unit["col"] < target["col"]:
                unit["col"] = max(unit["col"] - unit["move"], 0)
            elif unit["col"] > target["col"]:
                unit["col"] = min(unit["col"] + unit["move"], self.board_size[0] - 1)
            
            if unit["row"] < target["row"]:
                unit["row"] = max(unit["row"] - unit["move"], 0)
            elif unit["row"] > target["row"]:
                unit["row"] = min(unit["row"] + unit["move"], self.board_size[1] - 1)
            
            return 0.05  # Small reward for tactical retreat
        
        return 0.0
    
    def _attack_nearest(self, unit, enemies):
        """Attack nearest enemy in range."""
        if not enemies:
            return 0.0
        
        # Find enemies in range
        targets = []
        for enemy in enemies:
            dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
            if dist <= unit["rng_rng"]:
                targets.append((dist, enemy))
        
        if targets:
            # Attack nearest
            _, target = min(targets)
            damage = unit["rng_dmg"]
            target["cur_hp"] -= damage
            
            reward = 1.0  # Base attack reward
            
            if target["cur_hp"] <= 0:
                target["alive"] = False
                reward += 5.0  # Bonus for kill
            
            return reward
        
        return -0.1  # Penalty for failed attack
    
    def _get_info(self):
        """Get environment info."""
        return {
            "turn": self.current_turn,
            "game_over": self.game_over,
            "winner": self.winner,
            "ai_units_alive": len([u for u in self.units if u["player"] == 1 and u["alive"]]),
            "enemy_units_alive": len([u for u in self.units if u["player"] == 0 and u["alive"]])
        }
    
    def step(self, action):
        """Execute one step in the environment."""
        reward = 0.0
        
        # Simple action space for now
        # 0: Move closer to enemy
        # 1: Move away from enemy  
        # 2: Attack nearest enemy
        # 3-7: Other actions
        
        if self.game_over:
            return self._get_obs(), reward, True, False, self._get_info()
        
        # Find AI units
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        enemy_units = [u for u in self.units if u["player"] == 0 and u["alive"]]
        
        if not ai_units or not enemy_units:
            self.game_over = True
            self.winner = 1 if enemy_units else 0 if ai_units else None
            reward = 10.0 if self.winner == 1 else -10.0 if self.winner == 0 else 0.0
            return self._get_obs(), reward, True, False, self._get_info()
        
        # Execute action with first AI unit
        if ai_units:
            ai_unit = ai_units[0]
            
            if action == 0:  # Move closer
                reward += self._move_unit_closer(ai_unit, enemy_units)
            elif action == 1:  # Move away
                reward += self._move_unit_away(ai_unit, enemy_units)
            elif action == 2:  # Attack
                reward += self._attack_nearest(ai_unit, enemy_units)
            elif action == 3:  # Ranged attack specific
                if ai_unit["is_ranged"] and enemy_units:
                    nearest_enemy = min(enemy_units, key=lambda e: self._get_distance(ai_unit, e))
                    if self._attack_target(ai_unit, nearest_enemy):
                        reward += 1.0
                        if not nearest_enemy["alive"]:
                            reward += 5.0
            elif action == 4:  # Melee attack specific
                if ai_unit["is_melee"] and enemy_units:
                    nearest_enemy = min(enemy_units, key=lambda e: self._get_distance(ai_unit, e))
                    if self._attack_target(ai_unit, nearest_enemy):
                        reward += 1.0
                        if not nearest_enemy["alive"]:
                            reward += 5.0
            elif action == 5:  # Move toward nearest enemy
                if enemy_units:
                    nearest_enemy = min(enemy_units, key=lambda e: self._get_distance(ai_unit, e))
                    if self._move_toward_target(ai_unit, nearest_enemy):
                        reward += 0.2
            elif action == 6:  # Defensive position
                reward += 0.05
            elif action == 7:  # Wait/do nothing
                reward -= 0.1
            else:  # Wait or other
                reward -= 0.1  # Small penalty for waiting
        
        # Enemy AI (simple)
        for enemy in enemy_units:
            if not enemy["alive"]:
                continue
                
            # Simple enemy behavior - move toward nearest AI unit
            if ai_units:
                nearest_ai = min(ai_units, key=lambda a: self._get_distance(enemy, a))
                distance = self._get_distance(enemy, nearest_ai)
                
                if distance <= 1 and enemy["is_melee"]:
                    # Melee attack
                    if self._attack_target(enemy, nearest_ai):
                        if not nearest_ai["alive"]:
                            reward -= 5.0
                elif distance <= enemy["rng_rng"] and enemy["is_ranged"]:
                    # Ranged attack
                    if self._attack_target(enemy, nearest_ai):
                        if not nearest_ai["alive"]:
                            reward -= 5.0
                else:
                    # Move toward target
                    self._move_toward_target(enemy, nearest_ai)
        
        # Check win conditions again
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        enemy_units = [u for u in self.units if u["player"] == 0 and u["alive"]]
        
        if not ai_units:
            self.game_over = True
            self.winner = 0
            reward -= 10
        elif not enemy_units:
            self.game_over = True
            self.winner = 1
            reward += 10
        
        # Turn limit
        self.current_turn += 1
        if self.current_turn >= self.max_turns:
            self.game_over = True
            if not self.winner:
                self.winner = 1 if len(ai_units) > len(enemy_units) else 0 if len(enemy_units) > len(ai_units) else None
            reward -= 1
        
        # Log step
        step_log = {
            "turn": self.current_turn,
            "action": action,
            "reward": reward,
            "ai_units_alive": len(ai_units),
            "enemy_units_alive": len(enemy_units),
            "game_over": self.game_over
        }
        self.current_log.append(step_log)
        
        # Log to replay if enabled
        self.log_step_to_replay(action, reward)
        
        info = self._get_info()
        return self._get_obs(), reward, self.game_over, False, info
    
    def render(self, mode='human'):
        """Render the environment (optional)."""
        if mode == 'human':
            # Simple text representation
            print(f"\nTurn {self.current_turn} - Player {self.current_player}")
            print("Board state:")
            for unit in self.units:
                if unit["alive"]:
                    player_symbol = "AI" if unit["player"] == 1 else "EN"
                    print(f"  {player_symbol}{unit['id']}: ({unit['col']}, {unit['row']}) HP:{unit['cur_hp']}/{unit['hp_max']}")
            print(f"Game over: {self.game_over}, Winner: {self.winner}")
        
        return None
    
    def close(self):
        """Clean up environment resources."""
        pass
    
    def save_episode_logs(self, filename=None):
        """Save episode logs to file."""
        if not filename:
            os.makedirs("ai/event_log", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ai/event_log/episode_log_{timestamp}.json"
        
        if self.episode_logs:
            import json
            with open(filename, 'w') as f:
                json.dump(self.episode_logs, f, indent=2)
            print(f"Episode logs saved to {filename}")
        
        return filename
    
    def get_episode_stats(self):
        """Get statistics from logged episodes."""
        if not self.episode_logs:
            return {}
        
        rewards = [ep[1] for ep in self.episode_logs]
        return {
            "episodes": len(self.episode_logs),
            "avg_reward": sum(rewards) / len(rewards),
            "best_reward": max(rewards),
            "worst_reward": min(rewards)
        }
    
    def get_best_worst_episodes(self):
        """Get best and worst episodes from logs."""
        if not self.episode_logs:
            return {}
        
        best_log, best_reward = max(self.episode_logs, key=lambda x: x[1])
        worst_log, worst_reward = min(self.episode_logs, key=lambda x: x[1])
        
        return {
            "best": {"log": best_log, "reward": best_reward},
            "worst": {"log": worst_log, "reward": worst_reward}
        }
    
    def enable_replay_logging(self, replay_file=None):
        """Enable replay logging for this episode."""
        try:
            from datetime import datetime
            import json
            
            if not replay_file:
                os.makedirs("ai/event_log", exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                replay_file = f"ai/event_log/game_replay_{timestamp}.json"
            
            self.replay_file = replay_file
            self.replay_data = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "total_timesteps": 0,
                    "episode_reward": 0,
                    "map_size": {"width": self.board_size[0], "height": self.board_size[1]},
                    "max_turns": self.max_turns
                },
                "events": [],
                "web_compatible": True,
                "features": ["unit_positions", "hp_tracking", "movement", "combat"],
                "initial_state": {
                    "units": copy.deepcopy(self.initial_units),
                    "turn": 0,
                    "current_player": 1
                }
            }
            
            # Log initial state
            initial_event = {
                "turn": 0,
                "action": None,
                "reward": 0,
                "ai_units_alive": len([u for u in self.units if u["player"] == 1 and u["alive"]]),
                "enemy_units_alive": len([u for u in self.units if u["player"] == 0 and u["alive"]]),
                "game_over": False,
                "units": [
                    {
                        "id": unit["id"],
                        "type": unit["unit_type"],
                        "player": unit["player"],
                        "col": unit["col"],
                        "row": unit["row"],
                        "HP_MAX": unit["hp_max"],
                        "CUR_HP": unit["cur_hp"],
                        "alive": unit["alive"]
                    }
                    for unit in self.units
                ]
            }
            self.replay_data["events"].append(initial_event)
            self.replay_logging_enabled = True
            
        except Exception as e:
            print(f"Warning: Could not enable replay logging: {e}")
            self.replay_logging_enabled = False
    
    def disable_replay_logging(self):
        """Disable replay logging."""
        self.replay_logging_enabled = False
        self.replay_data = {}
        self.replay_file = None
    
    def finalize_replay_logging(self):
        """Finalize and save replay data."""
        if not hasattr(self, 'replay_logging_enabled') or not self.replay_logging_enabled:
            return
        
        try:
            import json
            
            # Calculate final metadata
            if self.current_log:
                total_reward = sum(step.get('reward', 0) for step in self.current_log)
                self.replay_data["metadata"]["episode_reward"] = total_reward
                self.replay_data["metadata"]["total_timesteps"] = len(self.current_log)
                self.replay_data["metadata"]["final_turn"] = self.current_turn
                
                # Add game summary
                self.replay_data["game_summary"] = {
                    "final_reward": total_reward,
                    "total_turns": self.current_turn,
                    "game_result": "ai_win" if self.winner == 1 else "ai_lose" if self.winner == 0 else "draw",
                    "winner": self.winner
                }
            
            # Save to file
            with open(self.replay_file, 'w', encoding='utf-8') as f:
                json.dump(self.replay_data, f, indent=2)
            
            print(f"Replay data saved to {self.replay_file}")
            self.replay_logging_enabled = False
            
        except Exception as e:
            print(f"Warning: Could not save replay data: {e}")
    
    def log_step_to_replay(self, action, reward):
        """Log a step to the replay data."""
        if not hasattr(self, 'replay_logging_enabled') or not self.replay_logging_enabled:
            return
        
        try:
            step_event = {
                "turn": self.current_turn,
                "action": int(action) if action is not None else None,
                "reward": float(reward),
                "ai_units_alive": len([u for u in self.units if u["player"] == 1 and u["alive"]]),
                "enemy_units_alive": len([u for u in self.units if u["player"] == 0 and u["alive"]]),
                "game_over": self.game_over,
                "timestamp": datetime.now().isoformat(),
                "units": [
                    {
                        "id": unit["id"],
                        "type": unit["unit_type"],
                        "player": unit["player"],
                        "col": unit["col"],
                        "row": unit["row"],
                        "HP_MAX": unit["hp_max"],
                        "CUR_HP": unit["cur_hp"],
                        "alive": unit["alive"]
                    }
                    for unit in self.units
                ]
            }
            
            if self.game_over:
                step_event["winner"] = self.winner
            
            self.replay_data["events"].append(step_event)
            
        except Exception as e:
            print(f"Warning: Could not log replay step: {e}")
    
    def get_replay_data(self):
        """Get current replay data."""
        if hasattr(self, 'replay_data'):
            return copy.deepcopy(self.replay_data)
        return None
    
    def set_replay_file(self, filepath):
        """Set custom replay file path."""
        self.replay_file = filepath
    
    def is_replay_logging_enabled(self):
        """Check if replay logging is currently enabled."""
        return hasattr(self, 'replay_logging_enabled') and self.replay_logging_enabled
    
    def get_unit_by_id(self, unit_id):
        """Get unit by ID."""
        for unit in self.units:
            if unit["id"] == unit_id:
                return unit
        return None
    
    def get_units_by_player(self, player_id):
        """Get all units for a specific player."""
        return [unit for unit in self.units if unit["player"] == player_id]
    
    def get_alive_units(self):
        """Get all alive units."""
        return [unit for unit in self.units if unit["alive"]]
    
    def get_dead_units(self):
        """Get all dead units."""
        return [unit for unit in self.units if not unit["alive"]]
    
    def get_game_state_summary(self):
        """Get comprehensive game state summary."""
        ai_units = [u for u in self.units if u["player"] == 1]
        enemy_units = [u for u in self.units if u["player"] == 0]
        
        return {
            "turn": self.current_turn,
            "max_turns": self.max_turns,
            "current_player": self.current_player,
            "game_over": self.game_over,
            "winner": self.winner,
            "board_size": self.board_size,
            "units": {
                "ai": {
                    "total": len(ai_units),
                    "alive": len([u for u in ai_units if u["alive"]]),
                    "dead": len([u for u in ai_units if not u["alive"]]),
                    "total_hp": sum(u["cur_hp"] for u in ai_units if u["alive"]),
                    "max_hp": sum(u["hp_max"] for u in ai_units)
                },
                "enemy": {
                    "total": len(enemy_units),
                    "alive": len([u for u in enemy_units if u["alive"]]),
                    "dead": len([u for u in enemy_units if not u["alive"]]),
                    "total_hp": sum(u["cur_hp"] for u in enemy_units if u["alive"]),
                    "max_hp": sum(u["hp_max"] for u in enemy_units)
                }
            }
        }
    
    def validate_board_state(self):
        """Validate current board state for consistency."""
        errors = []
        
        # Check unit positions are within bounds
        for unit in self.units:
            if not (0 <= unit["col"] < self.board_size[0]):
                errors.append(f"Unit {unit['id']} col {unit['col']} out of bounds")
            if not (0 <= unit["row"] < self.board_size[1]):
                errors.append(f"Unit {unit['id']} row {unit['row']} out of bounds")
            
            # Check HP consistency
            if unit["cur_hp"] < 0:
                errors.append(f"Unit {unit['id']} has negative HP: {unit['cur_hp']}")
            if unit["cur_hp"] > unit["hp_max"]:
                errors.append(f"Unit {unit['id']} HP exceeds max: {unit['cur_hp']}/{unit['hp_max']}")
            
            # Check alive status consistency
            if unit["cur_hp"] <= 0 and unit["alive"]:
                errors.append(f"Unit {unit['id']} should be dead (HP: {unit['cur_hp']})")
        
        return errors
    
    def repair_board_state(self):
        """Repair any inconsistencies in board state."""
        repairs = []
        
        for unit in self.units:
            # Fix position bounds
            if unit["col"] < 0:
                unit["col"] = 0
                repairs.append(f"Fixed unit {unit['id']} col to 0")
            elif unit["col"] >= self.board_size[0]:
                unit["col"] = self.board_size[0] - 1
                repairs.append(f"Fixed unit {unit['id']} col to {unit['col']}")
            
            if unit["row"] < 0:
                unit["row"] = 0
                repairs.append(f"Fixed unit {unit['id']} row to 0")
            elif unit["row"] >= self.board_size[1]:
                unit["row"] = self.board_size[1] - 1
                repairs.append(f"Fixed unit {unit['id']} row to {unit['row']}")
            
            # Fix HP consistency
            if unit["cur_hp"] < 0:
                unit["cur_hp"] = 0
                repairs.append(f"Fixed unit {unit['id']} HP to 0")
            elif unit["cur_hp"] > unit["hp_max"]:
                unit["cur_hp"] = unit["hp_max"]
                repairs.append(f"Fixed unit {unit['id']} HP to max")
            
            # Fix alive status
            if unit["cur_hp"] <= 0 and unit["alive"]:
                unit["alive"] = False
                repairs.append(f"Marked unit {unit['id']} as dead")
            elif unit["cur_hp"] > 0 and not unit["alive"]:
                unit["alive"] = True
                repairs.append(f"Marked unit {unit['id']} as alive")
        
        return repairs
    
    def export_game_state(self, format="json"):
        """Export current game state in specified format."""
        state = {
            "game_info": self.get_game_state_summary(),
            "units": [
                {
                    "id": unit["id"],
                    "type": unit["unit_type"],
                    "player": unit["player"],
                    "position": {"col": unit["col"], "row": unit["row"]},
                    "health": {"current": unit["cur_hp"], "max": unit["hp_max"]},
                    "stats": {
                        "move": unit["move"],
                        "rng_rng": unit["rng_rng"],
                        "rng_dmg": unit["rng_dmg"],
                        "cc_dmg": unit["cc_dmg"]
                    },
                    "capabilities": {
                        "is_ranged": unit["is_ranged"],
                        "is_melee": unit["is_melee"]
                    },
                    "alive": unit["alive"]
                }
                for unit in self.units
            ],
            "board": {
                "width": self.board_size[0],
                "height": self.board_size[1]
            },
            "export_timestamp": datetime.now().isoformat()
        }
        
        if format.lower() == "json":
            return json.dumps(state, indent=2)
        elif format.lower() == "dict":
            return state
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def import_game_state(self, state_data, format="json"):
        """Import game state from specified format."""
        if format.lower() == "json":
            if isinstance(state_data, str):
                state = json.loads(state_data)
            else:
                state = state_data
        elif format.lower() == "dict":
            state = state_data
        else:
            raise ValueError(f"Unsupported import format: {format}")
        
        # Import game info
        if "game_info" in state:
            game_info = state["game_info"]
            self.current_turn = game_info.get("turn", 0)
            self.current_player = game_info.get("current_player", 1)
            self.game_over = game_info.get("game_over", False)
            self.winner = game_info.get("winner", None)
        
        # Import board size
        if "board" in state:
            board = state["board"]
            self.board_size = (board["width"], board["height"])
        
        # Import units
        if "units" in state:
            self.units = []
            for unit_data in state["units"]:
                unit = {
                    "id": unit_data["id"],
                    "unit_type": unit_data["type"],
                    "player": unit_data["player"],
                    "col": unit_data["position"]["col"],
                    "row": unit_data["position"]["row"],
                    "cur_hp": unit_data["health"]["current"],
                    "hp_max": unit_data["health"]["max"],
                    "move": unit_data["stats"]["move"],
                    "rng_rng": unit_data["stats"]["rng_rng"],
                    "rng_dmg": unit_data["stats"]["rng_dmg"],
                    "cc_dmg": unit_data["stats"]["cc_dmg"],
                    "is_ranged": unit_data["capabilities"]["is_ranged"],
                    "is_melee": unit_data["capabilities"]["is_melee"],
                    "alive": unit_data["alive"]
                }
                self.units.append(unit)
        
        return True