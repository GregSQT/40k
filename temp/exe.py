#!/usr/bin/env python3
"""
Enhanced gym40k.py with modified self-play support
Based on your existing implementation with self-play additions
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
import json
import os
import copy
import random

REWARDS_PATH = os.path.join(os.path.dirname(__file__), "rewards_master.json")
SCENARIO_PATH = os.path.join(os.path.dirname(__file__), "scenario.json") 

# Load rewards configuration
if os.path.exists(REWARDS_PATH):
    with open(REWARDS_PATH, "r") as f:
        REWARDS_MASTER = json.load(f)
else:
    # Default rewards if file doesn't exist
    REWARDS_MASTER = {
        "SpaceMarineRanged": {"win": 1, "lose": -1, "wait": -0.1},
        "SpaceMarineMelee": {"win": 1, "lose": -1, "wait": -0.1}
    }

class W40KEnv(gym.Env):
    def __init__(self, n_units=4, board_size=(24, 18), 
                 opponent_model=None, self_play_mode=False, 
                 scripted_opponent=False, training_player=1):
        """
        Enhanced W40K Environment with self-play support.
        
        Args:
            n_units: Number of units (legacy, determined by scenario)
            board_size: Board dimensions
            opponent_model: Pre-trained model to use as opponent (for self-play)
            self_play_mode: If True, use opponent_model instead of scripted bot
            scripted_opponent: Legacy parameter for compatibility
            training_player: Which player is being trained (0 or 1)
        """
        super().__init__()
        self.board_size = board_size
        self.opponent_model = opponent_model
        self.self_play_mode = self_play_mode
        self.training_player = training_player
        self.scripted_opponent = scripted_opponent

        # Load scenario from JSON
        if os.path.exists(SCENARIO_PATH):
            with open(SCENARIO_PATH, "r") as f:
                self.base_scenario = json.load(f)
        else:
            self.base_scenario = self._create_default_scenario()
            
        self.n_units = len(self.base_scenario)
        
        # Define spaces
        self.observation_space = spaces.Box(
            low=0, high=100, 
            shape=(self.n_units * 7,), 
            dtype=np.float32
        )
        self.action_space = spaces.Discrete(8)
        
        # Initialize
        self.reset()
        self.episode_logs = []
        self.episode_rewards = []

    def set_opponent_model(self, opponent_model):
        """Update the opponent model (for self-play training)."""
        self.opponent_model = opponent_model
        print(f"[Self-Play] Updated opponent model")

    def _create_default_scenario(self):
        """Create a default scenario if scenario.json doesn't exist."""
        return [
            {
                "id": 1, "unit_type": "Intercessor", "player": 0,
                "col": 23, "row": 12, "cur_hp": 3, "hp_max": 3,
                "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                "is_ranged": True, "is_melee": False, "alive": True
            },
            {
                "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
                "col": 1, "row": 12, "cur_hp": 4, "hp_max": 4,
                "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                "is_ranged": False, "is_melee": True, "alive": True
            },
            {
                "id": 3, "unit_type": "Intercessor", "player": 1,
                "col": 0, "row": 5, "cur_hp": 3, "hp_max": 3,
                "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                "is_ranged": True, "is_melee": False, "alive": True
            },
            {
                "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
                "col": 22, "row": 3, "cur_hp": 4, "hp_max": 4,
                "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                "is_ranged": False, "is_melee": True, "alive": True
            }
        ]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        
        # Deep copy units from base scenario
        self.units = copy.deepcopy(self.base_scenario)
        
        # Initialize additional fields
        for u in self.units:
            u.setdefault("has_acted_this_phase", False)
            u.setdefault("damage_dealt", 0)
            u.setdefault("attacks_made", 0)
            u.setdefault("shots_fired", 0)
            u.setdefault("kills", 0)
            u.setdefault("_last_kills", 0)
        
        # Create observation
        self.state = self._get_obs()
        
        # Reset game state
        self.turn = 0
        self.game_over = False
        self.event_log = []
        self.winner = None
        self.episode_reward = 0
        self.current_player = self.training_player  # Training player starts
        
        return self.state.copy(), {}

    def _get_obs(self):
        """Create observation from current game state."""
        obs = []
        for u in self.units:
            obs.extend([
                u["player"], u["col"], u["row"], u["cur_hp"], 
                u["rng_rng"], u["rng_dmg"], u["cc_dmg"]
            ])
        return np.array(obs, dtype=np.float32)

    def _get_obs_for_player(self, player):
        """Get observation from specific player's perspective."""
        obs = []
        for u in self.units:
            # Flip perspective if needed
            if player != self.training_player:
                # For opponent, flip player IDs so they see themselves as "player 1"
                obs.extend([
                    1 - u["player"],  # Flip player perspective
                    u["col"], u["row"], u["cur_hp"], 
                    u["rng_rng"], u["rng_dmg"], u["cc_dmg"]
                ])
            else:
                # Normal perspective for training player
                obs.extend([
                    u["player"], u["col"], u["row"], u["cur_hp"], 
                    u["rng_rng"], u["rng_dmg"], u["cc_dmg"]
                ])
        return np.array(obs, dtype=np.float32)

    def step(self, action):
        """Execute one step in the environment."""
        
        # Convert action to int if it's a numpy array
        if isinstance(action, np.ndarray):
            action = int(action.item())
        elif not isinstance(action, int):
            action = int(action)
        
        # Get current active training player units
        training_units = [u for u in self.units if u["player"] == self.training_player and u["alive"]]
        if not training_units:
            self.game_over = True
            self.winner = 1 - self.training_player
            
        # Select acting unit (first available training unit)
        acting_unit = None
        for u in training_units:
            if not u.get("has_acted_this_phase", False):
                acting_unit = u
                break
                
        if acting_unit is None:
            # All training units have acted, opponent's turn
            self._execute_opponent_turn()
            self._reset_phase_flags()
            self.turn += 1
            
        if acting_unit:
            # Execute training player's action
            self._execute_action(acting_unit, action)
            acting_unit["has_acted_this_phase"] = True
        
        # Check if all training units have acted
        training_units_acted = all(u.get("has_acted_this_phase", False) for u in training_units)
        if training_units_acted:
            # Execute opponent turn
            self._execute_opponent_turn()
            self._reset_phase_flags()
            self.turn += 1
        
        # Check win condition
        self._check_win_condition()
        
        # Calculate reward
        reward = self._calculate_reward(acting_unit if acting_unit else training_units[0] if training_units else None, action)
        self.episode_reward += reward
        
        # Get new observation
        obs = self._get_obs()
        
        # Check termination
        terminated = self.game_over
        truncated = self.turn > 50
        
        info = {
            "turn": self.turn,
            "winner": self.winner,
            "acting_unit": acting_unit["id"] if acting_unit else None,
            "self_play_mode": self.self_play_mode
        }
        
        # Save episode log at end
        if terminated or truncated:
            self.episode_logs.append((list(self.event_log), self.episode_reward))
        
        return obs, reward, terminated, truncated, info

    def _execute_opponent_turn(self):
        """Execute opponent turn - either AI or scripted."""
        if self.self_play_mode and self.opponent_model:
            self._execute_ai_opponent_turn()
        else:
            self._execute_scripted_opponent_turn()

    def _execute_ai_opponent_turn(self):
        """Execute AI opponent turn using the opponent model."""
        opponent_player = 1 - self.training_player
        opponent_units = [u for u in self.units if u["player"] == opponent_player and u["alive"]]
        
        for unit in opponent_units:
            if not opponent_units:  # Check if any units left
                break
                
            try:
                # Get observation from opponent's perspective
                obs = self._get_obs_for_player(opponent_player)
                
                # Use opponent model to choose action
                action, _ = self.opponent_model.predict(obs, deterministic=False)
                
                # Convert action to int
                if isinstance(action, np.ndarray):
                    action = int(action.item())
                elif not isinstance(action, int):
                    action = int(action)
                
                # Execute the action
                self._execute_action(unit, action)
                
                # Log opponent action
                self.event_log.append({
                    "turn": self.turn,
                    "unit_id": unit["id"],
                    "action": action,
                    "position": (unit["col"], unit["row"]),
                    "hp": unit["cur_hp"],
                    "player": "opponent_ai"
                })
                
            except Exception as e:
                print(f"[WARNING] AI opponent action failed: {e}")
                # Fallback to waiting
                pass

    def _execute_scripted_opponent_turn(self):
        """Execute scripted opponent turn (your original implementation)."""
        opponent_player = 1 - self.training_player
        opponent_units = [u for u in self.units if u["player"] == opponent_player and u["alive"]]
        training_units = [u for u in self.units if u["player"] == self.training_player and u["alive"]]
        
        for unit in opponent_units:
            if not training_units:
                break
                
            # Simple scripted behavior (your original code)
            if unit["is_ranged"]:
                # Try to attack if in range
                targets_in_range = [
                    e for e in training_units 
                    if max(abs(unit["col"] - e["col"]), abs(unit["row"] - e["row"])) <= unit["rng_rng"]
                ]
                if targets_in_range:
                    target = min(targets_in_range, key=lambda e: e["cur_hp"])
                    damage = unit["rng_dmg"]
                    target["cur_hp"] -= damage
                    if target["cur_hp"] <= 0:
                        target["cur_hp"] = 0
                        target["alive"] = False
                        training_units.remove(target)
                else:
                    # Move towards nearest training unit
                    if training_units:
                        nearest = min(training_units, 
                                    key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
                        self._move_towards_enemy(unit, [nearest])
            
            elif unit["is_melee"]:
                # Try to attack adjacent enemies
                adjacent_enemies = [
                    e for e in training_units
                    if max(abs(unit["col"] - e["col"]), abs(unit["row"] - e["row"])) <= 1
                ]
                if adjacent_enemies:
                    target = min(adjacent_enemies, key=lambda e: e["cur_hp"])
                    damage = unit["cc_dmg"]
                    target["cur_hp"] -= damage
                    if target["cur_hp"] <= 0:
                        target["cur_hp"] = 0
                        target["alive"] = False
                        training_units.remove(target)
                else:
                    # Move towards nearest training unit
                    if training_units:
                        nearest = min(training_units, 
                                    key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
                        self._move_towards_enemy(unit, [nearest])

    def _execute_action(self, unit, action):
        """Execute the given action for the unit."""
        enemy_units = [u for u in self.units if u["player"] != unit["player"] and u["alive"]]
        
        if action == 0:  # Move close
            self._move_towards_enemy(unit, enemy_units)
        elif action == 1:  # Move away
            self._move_away_from_enemy(unit, enemy_units)
        elif action == 2:  # Move to safe
            self._move_to_safe_position(unit, enemy_units)
        elif action == 3:  # Move to range
            self._move_to_range(unit, enemy_units)
        elif action == 4:  # Move to charge
            self._move_to_charge_range(unit, enemy_units)
        elif action == 5:  # Shoot/Attack
            self._attack_enemy(unit, enemy_units)
        elif action == 6:  # Charge
            self._charge_enemy(unit, enemy_units)
        elif action == 7:  # Wait
            pass  # Do nothing
        
        # Log the action
        self.event_log.append({
            "turn": self.turn,
            "unit_id": unit["id"],
            "action": action,
            "position": (unit["col"], unit["row"]),
            "hp": unit["cur_hp"]
        })

    def _move_towards_enemy(self, unit, enemy_units):
        """Move unit towards nearest enemy."""
        if not enemy_units:
            return
            
        nearest_enemy = min(enemy_units, 
                          key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
        
        # Simple movement towards enemy
        if unit["col"] < nearest_enemy["col"]:
            unit["col"] = min(unit["col"] + unit["move"], self.board_size[0] - 1)
        elif unit["col"] > nearest_enemy["col"]:
            unit["col"] = max(unit["col"] - unit["move"], 0)
            
        if unit["row"] < nearest_enemy["row"]:
            unit["row"] = min(unit["row"] + unit["move"], self.board_size[1] - 1)
        elif unit["row"] > nearest_enemy["row"]:
            unit["row"] = max(unit["row"] - unit["move"], 0)

    def _move_away_from_enemy(self, unit, enemy_units):
        """Move unit away from nearest enemy."""
        if not enemy_units:
            return
            
        nearest_enemy = min(enemy_units, 
                          key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
        
        # Move away from enemy
        if unit["col"] < nearest_enemy["col"]:
            unit["col"] = max(unit["col"] - unit["move"], 0)
        elif unit["col"] > nearest_enemy["col"]:
            unit["col"] = min(unit["col"] + unit["move"], self.board_size[0] - 1)
            
        if unit["row"] < nearest_enemy["row"]:
            unit["row"] = max(unit["row"] - unit["move"], 0)
        elif unit["row"] > nearest_enemy["row"]:
            unit["row"] = min(unit["row"] + unit["move"], self.board_size[1] - 1)

    def _move_to_safe_position(self, unit, enemy_units):
        """Move to a safer position."""
        # Simple: move to corner
        corner_col = 0 if unit["col"] < self.board_size[0] // 2 else self.board_size[0] - 1
        corner_row = 0 if unit["row"] < self.board_size[1] // 2 else self.board_size[1] - 1
        
        if abs(unit["col"] - corner_col) > abs(unit["row"] - corner_row):
            if unit["col"] < corner_col:
                unit["col"] = min(unit["col"] + unit["move"], corner_col)
            else:
                unit["col"] = max(unit["col"] - unit["move"], corner_col)
        else:
            if unit["row"] < corner_row:
                unit["row"] = min(unit["row"] + unit["move"], corner_row)
            else:
                unit["row"] = max(unit["row"] - unit["move"], corner_row)

    def _move_to_range(self, unit, enemy_units):
        """Move to optimal range for ranged attack."""
        if not unit["is_ranged"] or not enemy_units:
            return
            
        target = min(enemy_units, 
                    key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
        
        distance = max(abs(unit["col"] - target["col"]), abs(unit["row"] - target["row"]))
        optimal_range = unit["rng_rng"] - 1
        
        if distance > optimal_range:
            self._move_towards_enemy(unit, [target])
        elif distance < optimal_range // 2:
            self._move_away_from_enemy(unit, [target])

    def _move_to_charge_range(self, unit, enemy_units):
        """Move to charge range."""
        if not unit["is_melee"] or not enemy_units:
            return
            
        target = min(enemy_units, 
                    key=lambda e: abs(unit["col"] - e["col"]) + abs(unit["row"] - e["row"]))
        
        # Move to within charge range (adjacent)
        self._move_towards_enemy(unit, [target])

    def _attack_enemy(self, unit, enemy_units):
        """Attack an enemy unit."""
        if not enemy_units:
            return
            
        # Find targets in range
        targets_in_range = []
        for enemy in enemy_units:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            
            if unit["is_ranged"] and distance <= unit["rng_rng"]:
                targets_in_range.append(enemy)
            elif unit["is_melee"] and distance <= 1:
                targets_in_range.append(enemy)
        
        if targets_in_range:
            # Attack lowest HP target
            target = min(targets_in_range, key=lambda e: e["cur_hp"])
            
            if unit["is_ranged"]:
                damage = unit["rng_dmg"]
                unit["shots_fired"] += 1
            else:
                damage = unit["cc_dmg"]
                unit["attacks_made"] += 1
            
            old_hp = target["cur_hp"]
            target["cur_hp"] -= damage
            unit["damage_dealt"] += min(damage, old_hp)
            
            if target["cur_hp"] <= 0:
                target["cur_hp"] = 0
                target["alive"] = False
                unit["kills"] += 1

    def _charge_enemy(self, unit, enemy_units):
        """Charge an enemy unit."""
        if not unit["is_melee"] or not enemy_units:
            return
            
        # Find chargeable targets
        chargeable = []
        for enemy in enemy_units:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if distance <= unit["move"] and distance > 1:
                chargeable.append(enemy)
        
        if chargeable:
            target = min(chargeable, key=lambda e: e["cur_hp"])
            
            # Move adjacent to target
            if unit["col"] < target["col"]:
                unit["col"] = target["col"] - 1
            elif unit["col"] > target["col"]:
                unit["col"] = target["col"] + 1
            else:
                if unit["row"] < target["row"]:
                    unit["row"] = target["row"] - 1
                else:
                    unit["row"] = target["row"] + 1
            
            # Attack after charge
            self._attack_enemy(unit, [target])

    def _reset_phase_flags(self):
        """Reset phase action flags for all units."""
        for unit in self.units:
            unit["has_acted_this_phase"] = False

    def _check_win_condition(self):
        """Check if game is over and determine winner."""
        training_alive = any(u["alive"] and u["player"] == self.training_player for u in self.units)
        opponent_alive = any(u["alive"] and u["player"] == (1 - self.training_player) for u in self.units)
        
        if not training_alive:
            self.game_over = True
            self.winner = 1 - self.training_player  # Opponent wins
        elif not opponent_alive:
            self.game_over = True
            self.winner = self.training_player  # Training player wins

    def _calculate_reward(self, unit, action):
        """Calculate reward for the action taken."""
        if unit is None:
            return 0.0
            
        unit_type = "SpaceMarineRanged" if unit["is_ranged"] else "SpaceMarineMelee"
        rewards = REWARDS_MASTER.get(unit_type, {})
        
        if self.game_over:
            if self.winner == self.training_player:  # Training player wins
                return rewards.get("win", 1.0)
            else:  # Training player loses
                return rewards.get("lose", -1.0)
        
        # Action-based rewards
        action_rewards = {
            0: rewards.get("move_close", 0.1),
            1: rewards.get("move_away", 0.1),
            2: rewards.get("move_to_safe", 0.1),
            3: rewards.get("move_to_rng", 0.2),
            4: rewards.get("move_to_charge", 0.2),
            5: rewards.get("ranged_attack", 0.3) if unit["is_ranged"] else rewards.get("attack", 0.3),
            6: rewards.get("charge_success", 0.4),
            7: rewards.get("wait", -0.1)
        }
        
        base_reward = action_rewards.get(action, 0.0)
        
        # Bonus for killing enemies
        current_kills = unit.get("kills", 0)
        last_kills = unit.get("_last_kills", 0)
        if current_kills > last_kills:
            unit["_last_kills"] = current_kills
            kill_bonus = rewards.get("enemy_killed_r" if unit["is_ranged"] else "enemy_killed_m", 0.5)
            base_reward += kill_bonus
        
        return base_reward

    def did_win(self):
        """Check if training player won the game."""
        return getattr(self, "winner", None) == self.training_player

    def close(self):
        """Clean up the environment."""
        pass


# Test the enhanced environment
def test_enhanced_environment():
    """Test the enhanced environment."""
    print("Testing Enhanced W40K Environment...")
    
    # Test scripted mode
    env = W40KEnv(self_play_mode=False)
    print(f"[OK] Scripted mode: {len(env.units)} units")
    
    obs, info = env.reset()
    print(f"[OK] Reset successful, observation shape: {obs.shape}")
    
    # Test a few steps
    for i in range(5):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        print(f"     Step {i+1}: action={action}, reward={reward:.3f}, done={terminated or truncated}")
        
        if terminated or truncated:
            print(f"     Game ended. Winner: {info.get('winner', 'None')}")
            break
    
    env.close()
    print("[OK] Enhanced environment test completed successfully!")

if __name__ == "__main__":
    test_enhanced_environment()