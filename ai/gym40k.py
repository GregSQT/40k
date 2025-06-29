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
        
        # Load configuration
        self.config = get_config_loader()
        
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
        
        # Game settings from config
        board_size = self.config.get_board_size()
        self.board_size = board_size
        self.max_turns = self.config.get_max_turns()
        self.turn_limit_penalty = self.config.get_turn_limit_penalty()
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
        for unit in self.initial_units:
            new_unit = copy.deepcopy(unit)
            new_unit["cur_hp"] = unit["hp_max"]
            new_unit["alive"] = True
            self.units.append(new_unit)

    def reset(self, *, seed=None, options=None):
        """Reset the environment."""
        super().reset(seed=seed)
        
        self.current_turn = 0
        self.current_player = 1  # AI goes first
        self.game_over = False
        self.winner = None
        
        # Reset units
        self.reset_units()
        
        # Reset episode tracking
        self.current_log = []
        
        # Enable replay logging for training
        self.enable_replay_logging("ai/episode_replay.json")
        
        return self._get_obs(), self._get_info()

    def _get_obs(self):
        """Get current observation."""
        obs = np.zeros(28, dtype=np.float32)
        
        # Normalize board positions
        max_pos = max(self.board_size)
        
        # AI unit observations (first 14 values)
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        for i, unit in enumerate(ai_units[:2]):  # Max 2 AI units
            base_idx = i * 7
            obs[base_idx] = unit["col"] / max_pos
            obs[base_idx + 1] = unit["row"] / max_pos
            obs[base_idx + 2] = unit["cur_hp"] / unit["hp_max"]
            obs[base_idx + 3] = unit["move"] / 10.0
            obs[base_idx + 4] = unit["rng_rng"] / 12.0
            obs[base_idx + 5] = unit["rng_dmg"] / 5.0
            obs[base_idx + 6] = unit["cc_dmg"] / 5.0
        
        # Enemy unit observations (next 14 values)
        enemy_units = [u for u in self.units if u["player"] == 0 and u["alive"]]
        for i, unit in enumerate(enemy_units[:2]):  # Max 2 enemy units
            base_idx = 14 + i * 7
            obs[base_idx] = unit["col"] / max_pos
            obs[base_idx + 1] = unit["row"] / max_pos
            obs[base_idx + 2] = unit["cur_hp"] / unit["hp_max"]
            obs[base_idx + 3] = unit["move"] / 10.0
            obs[base_idx + 4] = unit["rng_rng"] / 12.0
            obs[base_idx + 5] = unit["rng_dmg"] / 5.0
            obs[base_idx + 6] = unit["cc_dmg"] / 5.0
        
        return obs

    def _move_toward_target(self, unit, target):
        """Move unit toward target."""
        if not target or not target["alive"]:
            return
        
        # Calculate direction
        dx = target["col"] - unit["col"]
        dy = target["row"] - unit["row"]
        
        # Normalize and apply movement
        dist = max(abs(dx), abs(dy), 1)
        move_x = min(unit["move"], abs(dx)) * (1 if dx > 0 else -1 if dx < 0 else 0)
        move_y = min(unit["move"], abs(dy)) * (1 if dy > 0 else -1 if dy < 0 else 0)
        
        # Update position with bounds checking
        new_col = max(0, min(self.board_size[0] - 1, unit["col"] + move_x))
        new_row = max(0, min(self.board_size[1] - 1, unit["row"] + move_y))
        
        unit["col"] = new_col
        unit["row"] = new_row

    def _attack_target(self, attacker, target):
        """Attack target with ranged weapon - FIXED to prevent overkill."""
        if not target or not target["alive"]:
            return 0.0
        
        # Calculate distance
        dist = abs(attacker["col"] - target["col"]) + abs(attacker["row"] - target["row"])
        weapon_range = attacker.get("rng_rng", 4)
        
        # Check if target is in range
        if dist <= weapon_range:
            base_damage = attacker.get("rng_dmg", 1)
            # CRITICAL FIX: Prevent overkill damage
            actual_damage = min(base_damage, target["cur_hp"])
            target["cur_hp"] -= actual_damage
            
            reward = 1.0  # Base attack reward
            
            if target["cur_hp"] <= 0:
                target["cur_hp"] = 0  # Ensure HP doesn't go negative
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
        print(f"🎮 TURN {self.current_turn}: AI takes action {action}")
        
        # Debug: Show unit status BEFORE action
        ai_units_before = [u for u in self.units if u["player"] == 1 and u["alive"]]
        enemy_units_before = [u for u in self.units if u["player"] == 0 and u["alive"]]
        print(f"   BEFORE: AI units: {len(ai_units_before)}, Enemy units: {len(enemy_units_before)}")
        
        # DEBUG: Log what action is being taken
        ACTION_NAMES = {
            0: "Move Closer", 1: "Move Away", 2: "Move to Safety",
            3: "Shoot Closest", 4: "Shoot Weakest", 5: "Charge Closest",
            6: "Wait", 7: "Attack Adjacent"
        }
        action_int = int(action) if hasattr(action, 'item') else action
        print(f"   ACTION: {ACTION_NAMES.get(action_int, f'Unknown({action_int})')}")
        
        if self.game_over:
            return self._get_obs(), 0.0, True, False, self._get_info()
        
        reward = 0.0
        
        # Get AI units
        ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        enemies = [u for u in self.units if u["player"] == 0 and u["alive"]]
        
        if not ai_units:
            self.game_over = True
            self.winner = 0
            return self._get_obs(), -10.0, True, False, self._get_info()
        
        if not enemies:
            self.game_over = True
            self.winner = 1
            return self._get_obs(), 10.0, True, False, self._get_info()
        
        # Execute action for first AI unit
        if ai_units:
            unit = ai_units[0]
            nearest_enemy = min(enemies, key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
            
            if action == 0:  # Move closer
                self._move_toward_target(unit, nearest_enemy)
                reward += 0.1
            elif action == 1:  # Move away
                # Move in opposite direction
                if nearest_enemy:
                    dx = unit["col"] - nearest_enemy["col"]
                    dy = unit["row"] - nearest_enemy["row"]
                    move_x = min(unit["move"], 2) * (1 if dx > 0 else -1)
                    move_y = min(unit["move"], 2) * (1 if dy > 0 else -1)
                    unit["col"] = max(0, min(self.board_size[0] - 1, unit["col"] + move_x))
                    unit["row"] = max(0, min(self.board_size[1] - 1, unit["row"] + move_y))
                reward -= 0.1
            elif action == 2:  # Move to safe position
                # Move to corner
                target_col = 0 if unit["col"] < self.board_size[0] // 2 else self.board_size[0] - 1
                target_row = 0 if unit["row"] < self.board_size[1] // 2 else self.board_size[1] - 1
                dx = target_col - unit["col"]
                dy = target_row - unit["row"]
                move_x = min(unit["move"], abs(dx)) * (1 if dx > 0 else -1 if dx < 0 else 0)
                move_y = min(unit["move"], abs(dy)) * (1 if dy > 0 else -1 if dy < 0 else 0)
                unit["col"] = max(0, min(self.board_size[0] - 1, unit["col"] + move_x))
                unit["row"] = max(0, min(self.board_size[1] - 1, unit["row"] + move_y))
            elif action == 3:  # Shoot closest
                reward += self._attack_target(unit, nearest_enemy)
            elif action == 4:  # Shoot weakest
                weakest = min(enemies, key=lambda e: e["cur_hp"])
                reward += self._attack_target(unit, weakest)
            elif action == 5:  # Charge closest
                if nearest_enemy:
                    self._move_toward_target(unit, nearest_enemy)
                    # Check if in melee range
                    dist = abs(unit["col"] - nearest_enemy["col"]) + abs(unit["row"] - nearest_enemy["row"])
                    if dist <= 1:
                        # Melee attack
                        damage = unit["cc_dmg"]
                        nearest_enemy["cur_hp"] -= damage
                        reward += 1.0
                        if nearest_enemy["cur_hp"] <= 0:
                            nearest_enemy["alive"] = False
                            reward += 5.0
            elif action == 6:  # Wait
                reward -= 0.05
            elif action == 7:  # Attack adjacent
                # Find adjacent enemies
                adjacent_enemies = []
                for enemy in enemies:
                    dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
                    if dist <= 1:
                        adjacent_enemies.append(enemy)
                
                if adjacent_enemies:
                    target = adjacent_enemies[0]
                    damage = unit["cc_dmg"]
                    target["cur_hp"] -= damage
                    reward += 1.0
                    if target["cur_hp"] <= 0:
                        target["alive"] = False
                        reward += 5.0
                else:
                    reward -= 0.1
        
        # Enemy AI - BALANCED behavior (max 1 enemy action per turn)
        enemy_actions_this_turn = 0
        max_enemy_actions = 1  # CRITICAL: Limit to 1 enemy action per turn
        
        for enemy in enemies:
            if not enemy["alive"] or enemy_actions_this_turn >= max_enemy_actions:
                continue
                
            if not ai_units:  # No AI units left
                break
                
            nearest_ai = min(ai_units, key=lambda u: abs(enemy["col"] - u["col"]) + abs(enemy["row"] - u["row"]) if u["alive"] else float('inf'))
            
            if nearest_ai and nearest_ai["alive"]:
                dist = abs(enemy["col"] - nearest_ai["col"]) + abs(enemy["row"] - nearest_ai["row"])
                
                # FIXED: Limit enemy range and damage
                enemy_range = min(enemy.get("rng_rng", 4), 6)  # Max range 6
                enemy_damage = min(enemy.get("rng_dmg", 1), 2)  # Max damage 2
                
                if dist <= enemy_range and enemy.get("is_ranged", True):
                    # Ranged attack with damage limits
                    actual_damage = min(enemy_damage, nearest_ai["cur_hp"])
                    nearest_ai["cur_hp"] -= actual_damage
                    
                    if nearest_ai["cur_hp"] <= 0:
                        nearest_ai["cur_hp"] = 0
                        nearest_ai["alive"] = False
                        reward -= 2.0  # Reduced penalty
                    
                    enemy_actions_this_turn += 1
                    # Debug: print(f"Enemy {enemy.get('id', '?')} shoots AI {nearest_ai.get('id', '?')} for {actual_damage}")
                    
                elif dist > 1:  # Move closer if not adjacent
                    self._move_toward_target(enemy, nearest_ai)
                    enemy_actions_this_turn += 1
                    
                else:  # Melee attack if adjacent
                    melee_damage = min(enemy.get("cc_dmg", 1), 1)  # Max melee damage 1
                    actual_damage = min(melee_damage, nearest_ai["cur_hp"])
                    nearest_ai["cur_hp"] -= actual_damage
                    
                    if nearest_ai["cur_hp"] <= 0:
                        nearest_ai["cur_hp"] = 0
                        nearest_ai["alive"] = False
                        reward -= 2.0
                    
                    enemy_actions_this_turn += 1
        
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
            reward += self.turn_limit_penalty
        
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
        
        # Debug: Show unit status AFTER action
        ai_units_after = [u for u in self.units if u["player"] == 1 and u["alive"]]
        enemy_units_after = [u for u in self.units if u["player"] == 0 and u["alive"]]
        print(f"   AFTER:  AI units: {len(ai_units_after)}, Enemy units: {len(enemy_units_after)}")
        
        # DEBUG: If units died, show which ones
        if len(ai_units_before) != len(ai_units_after):
            dead_ai = [u for u in ai_units_before if not u["alive"]]
            print(f"   💀 AI UNITS DIED: {[u.get('id', '?') for u in dead_ai]}")
        
        if len(enemy_units_before) != len(enemy_units_after):
            dead_enemies = [u for u in enemy_units_before if not u["alive"]]
            print(f"   💀 ENEMY UNITS DIED: {[u.get('id', '?') for u in dead_enemies]}")
        
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
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ai/episode_log_{timestamp}.json"
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        episode_data = {
            "timestamp": datetime.now().isoformat(),
            "total_turns": self.current_turn,
            "winner": self.winner,
            "final_reward": sum(log["reward"] for log in self.current_log),
            "events": self.current_log
        }
        
        with open(filename, 'w') as f:
            json.dump(episode_data, f, indent=2)
        
        print(f"Episode logs saved to {filename}")
        return filename

    def enable_replay_logging(self, filename):
        """Enable replay logging to specified file."""
        self.replay_logging_enabled = True
        self.replay_file = filename
        self.replay_data = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "board_size": self.board_size,
                "max_turns": self.max_turns,
                "initial_units": len(self.initial_units)
            },
            "events": []
        }

    def log_step_to_replay(self, action, reward):
        """Log current step to replay data."""
        if not self.replay_logging_enabled:
            return
        
        step_data = {
            "turn": self.current_turn,
            "action": action,
            "reward": reward,
            "units": [
                {
                    "id": unit["id"],
                    "type": unit["unit_type"],
                    "player": unit["player"],
                    "col": unit["col"],
                    "row": unit["row"],
                    "cur_hp": unit["cur_hp"],
                    "hp_max": unit["hp_max"],
                    "alive": unit["alive"]
                }
                for unit in self.units
            ],
            "game_over": self.game_over,
            "winner": self.winner
        }
        
        self.replay_data["events"].append(step_data)
    
    def save_replay(self):
        """Save replay data to file."""
        if not self.replay_logging_enabled or not self.replay_file:
            return
        
        # Add final metadata
        self.replay_data["metadata"]["total_turns"] = self.current_turn
        self.replay_data["metadata"]["winner"] = self.winner
        self.replay_data["metadata"]["total_reward"] = sum(
            event["reward"] for event in self.replay_data["events"]
        )
        
        os.makedirs(os.path.dirname(self.replay_file), exist_ok=True)
        
        with open(self.replay_file, 'w') as f:
            json.dump(self.replay_data, f, indent=2)
        
        print(f"Replay saved to {self.replay_file}")

    def export_state(self, format="json"):
        """Export current game state in specified format."""
        state = {
            "game_info": {
                "turn": self.current_turn,
                "current_player": self.current_player,
                "game_over": self.game_over,
                "winner": self.winner,
                "max_turns": self.max_turns
            },
            "board": {
                "width": self.board_size[0],
                "height": self.board_size[1]
            },
            "units": []
        }
        
        for unit in self.units:
            unit_data = {
                "id": unit["id"],
                "type": unit["unit_type"],
                "player": unit["player"],
                "position": {
                    "col": unit["col"],
                    "row": unit["row"]
                },
                "health": {
                    "current": unit["cur_hp"],
                    "max": unit["hp_max"]
                },
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
            state["units"].append(unit_data)
        
        if format.lower() == "json":
            return json.dumps(state, indent=2)
        elif format.lower() == "dict":
            return state
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def import_state(self, state_data, format="json"):
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

    def get_scenario_json_state(self):
        """Get current state as scenario.json format for frontend compatibility."""
        scenario_state = {
            "board": {
                "cols": self.board_size[0],
                "rows": self.board_size[1],
                "hex_radius": 24,
                "margin": 32
            },
            "colors": {
                "background": "0x002200",
                "cell_even": "0x002200",
                "cell_odd": "0x001a00",
                "cell_border": "0x00ff00",
                "player_0": "0x244488",
                "player_1": "0x882222",
                "hp_full": "0x36e36b",
                "hp_damaged": "0x444444",
                "highlight": "0x80ff80",
                "current_unit": "0xffd700"
            },
            "units": []
        }
        
        for unit in self.units:
            unit_state = {
                "id": unit["id"],
                "unit_type": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"],
                "alive": unit["alive"],
                "current_hp": unit["cur_hp"],
                "max_hp": unit["hp_max"]
            }
            scenario_state["units"].append(unit_state)
        
        return scenario_state

    def create_web_replay_event(self, action, reward):
        """Create web-compatible replay event for frontend consumption."""
        # Determine phase based on action
        phase_mapping = {
            0: "move", 1: "move", 2: "move",  # Movement actions
            3: "shoot", 4: "shoot",           # Shooting actions
            5: "charge",                      # Charging
            7: "combat",                      # Combat
            6: "move"                         # Wait/end turn
        }
        
        phase = phase_mapping.get(action, "move")
        
        # Action names for display
        action_names = {
            0: "move_closer",
            1: "move_away", 
            2: "move_to_safe",
            3: "shoot_closest",
            4: "shoot_weakest",
            5: "charge_closest",
            6: "wait",
            7: "attack_adjacent"
        }
        
        # Create web format event
        web_event = {
            "turn": self.current_turn,
            "phase": phase,
            "acting_unit_idx": 0,  # Assume first AI unit for simplicity
            "target_unit_idx": None,
            "event_flags": {
                "action_name": action_names.get(action, f"action_{action}"),
                "action_id": action,
                "reward": reward,
                "ai_units_alive": len([u for u in self.units if u["player"] == 1 and u["alive"]]),
                "enemy_units_alive": len([u for u in self.units if u["player"] == 0 and u["alive"]])
            },
            "unit_stats": {},
            "units": []
        }
        
        # Add unit data in web format
        for unit in self.units:
            web_unit = {
                "id": unit["id"],
                "name": f"{'P' if unit['player'] == 0 else 'A'}-{unit['unit_type'][0]}",
                "type": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"],
                "color": 0x244488 if unit["player"] == 0 else 0x882222,
                "CUR_HP": unit["cur_hp"],
                "HP_MAX": unit["hp_max"],
                "MOVE": unit["move"],
                "RNG_RNG": unit["rng_rng"],
                "RNG_DMG": unit["rng_dmg"],
                "CC_DMG": unit["cc_dmg"],
                "ICON": unit["unit_type"][0],
                "alive": unit["alive"]
            }
            web_event["units"].append(web_unit)
        
        return web_event

    def save_web_compatible_replay(self, filename=None):
        """Save replay in web-compatible format for frontend consumption."""
        if filename is None:
            filename = "ai/event_log/train_best_game_replay.json"
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Convert replay events to web format
        web_events = []
        
        for i, event in enumerate(self.replay_data.get("events", [])):
            web_event = self.create_web_replay_event(
                event.get("action", 0),
                event.get("reward", 0)
            )
            web_events.append(web_event)
        
        # Create web-compatible replay structure
        web_replay = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_reward": sum(event.get("reward", 0) for event in self.replay_data.get("events", [])),
                "total_turns": self.current_turn,
                "episode_reward": sum(event.get("reward", 0) for event in self.replay_data.get("events", [])),
                "final_turn": self.current_turn
            },
            "game_summary": {
                "final_reward": sum(event.get("reward", 0) for event in self.replay_data.get("events", [])),
                "total_turns": self.current_turn,
                "game_result": "win" if self.winner == 1 else "loss" if self.winner == 0 else "draw"
            },
            "events": web_events,
            "web_compatible": True,
            "features": ["unit_movement", "combat", "rewards"]
        }
        
        with open(filename, 'w') as f:
            json.dump(web_replay, f, indent=2)
        
        print(f"Web-compatible replay saved to {filename}")
        return filename

    def get_action_space_info(self):
        """Get information about the action space for documentation."""
        return {
            "action_count": 8,
            "actions": {
                0: {"name": "move_closer", "description": "Move toward nearest enemy"},
                1: {"name": "move_away", "description": "Move away from nearest enemy"},
                2: {"name": "move_to_safe", "description": "Move to safe position (corner)"},
                3: {"name": "shoot_closest", "description": "Shoot at closest enemy"},
                4: {"name": "shoot_weakest", "description": "Shoot at weakest enemy"},
                5: {"name": "charge_closest", "description": "Charge and melee attack closest enemy"},
                6: {"name": "wait", "description": "Do nothing (small penalty)"},
                7: {"name": "attack_adjacent", "description": "Melee attack adjacent enemy"}
            }
        }

    def get_observation_space_info(self):
        """Get information about the observation space for documentation."""
        return {
            "observation_size": 28,
            "structure": {
                "ai_units": {
                    "range": "0-13",
                    "description": "AI unit data (2 units × 7 values each)",
                    "values": ["col_normalized", "row_normalized", "hp_ratio", "move_normalized", "range_normalized", "ranged_damage_normalized", "melee_damage_normalized"]
                },
                "enemy_units": {
                    "range": "14-27", 
                    "description": "Enemy unit data (2 units × 7 values each)",
                    "values": ["col_normalized", "row_normalized", "hp_ratio", "move_normalized", "range_normalized", "ranged_damage_normalized", "melee_damage_normalized"]
                }
            },
            "normalization": {
                "positions": "divided by max(board_width, board_height)",
                "hp": "current_hp / max_hp",
                "stats": "divided by reasonable max values (move/10, range/12, damage/5)"
            }
        }

    def get_environment_info(self):
        """Get comprehensive environment information for debugging."""
        return {
            "environment": "W40K Tactical Combat",
            "version": "1.0",
            "config_source": "config/game_config.json",
            "board_size": self.board_size,
            "max_turns": self.max_turns,
            "turn_penalty": self.turn_limit_penalty,
            "unit_count": len(self.units),
            "ai_units": len([u for u in self.units if u["player"] == 1]),
            "enemy_units": len([u for u in self.units if u["player"] == 0]),
            "current_turn": self.current_turn,
            "game_over": self.game_over,
            "winner": self.winner,
            "action_space": self.get_action_space_info(),
            "observation_space": self.get_observation_space_info(),
            "unit_types": list(self.unit_definitions.keys())
        }

# Register environment with gymnasium
def register_environment():
    """Register the W40K environment with gymnasium."""
    try:
        import gymnasium as gym
        gym.register(
            id='W40K-v0',
            entry_point='ai.gym40k:W40KEnv',
        )
        print("✅ W40K environment registered with gymnasium")
    except Exception as e:
        print(f"⚠️  Failed to register environment: {e}")

if __name__ == "__main__":
    # Test environment creation and basic functionality
    print("🎮 Testing W40K Environment")
    print("=" * 40)
    
    try:
        # Create environment
        env = W40KEnv()
        print("✅ Environment created successfully")
        
        # Print environment info
        info = env.get_environment_info()
        print(f"📊 Environment Info:")
        print(f"   Board size: {info['board_size']}")
        print(f"   Max turns: {info['max_turns']}")
        print(f"   Turn penalty: {info['turn_penalty']}")
        print(f"   Units: {info['unit_count']} ({info['ai_units']} AI, {info['enemy_units']} enemy)")
        print(f"   Unit types: {info['unit_types']}")
        
        # Test reset
        obs, info = env.reset()
        print(f"✅ Environment reset - observation shape: {obs.shape}")
        
        # Test a few steps
        print("🎯 Testing actions...")
        for action in range(3):
            obs, reward, done, truncated, info = env.step(action)
            print(f"   Action {action}: reward={reward:.2f}, done={done}, units_alive={info['ai_units_alive']}")
            if done:
                break
        
        # Test replay saving
        env.save_web_compatible_replay("ai/test_replay.json")
        print("✅ Test replay saved")
        
        print("🎉 All tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()