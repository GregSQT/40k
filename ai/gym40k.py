#!/usr/bin/env python3
"""
ai/gym40k.py - Complete replacement for gym40k.py using Python mirror architecture
EXACT Python mirror of PvP frontend game logic with Gymnasium interface preservation
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from typing import List, Dict, Tuple, Optional, Any
import json
import os
import copy
import sys
from pathlib import Path

# Add project root to path for imports
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Import Python mirror architecture  
try:
    from ai.game_controller import TrainingGameController, GameControllerConfig
    from ai.use_game_state import TrainingGameState
    from ai.use_game_actions import TrainingGameActions
    from ai.use_phase_transition import TrainingPhaseTransition
    from ai.use_game_log import TrainingGameLog
    from ai.use_game_config import TrainingGameConfig
except ImportError as e:
    print(f"⚠️ Python mirror dependencies missing: {e}")
    print("🔧 Creating minimal W40KEnv without full mirror architecture...")
    # Fallback to basic environment without mirrors
    TrainingGameController = None
    GameControllerConfig = None

# Import existing components for compatibility
from ai.unit_registry import UnitRegistry
try:
    from config_loader import get_config_loader
except ImportError:
    sys.path.append(str(project_root))
    from config_loader import get_config_loader

class W40KEnv(gym.Env):
    """
    Complete replacement for gym40k.py using Python mirror architecture.
    Maintains EXACT Gymnasium interface while using Python mirrors for ALL game logic.
    """

    def __init__(self, rewards_config=None, training_config_name="default", 
                 controlled_agent=None, active_agents=None, scenario_file=None, 
                 unit_registry=None, quiet=False):
        super().__init__()
        
        self.quiet = quiet
        
        # Multi-agent support - reuse shared registry if provided
        self.unit_registry = unit_registry if unit_registry is not None else UnitRegistry()
        self.controlled_agent = controlled_agent
        self.active_agents = active_agents or []
        
        # Load configuration
        self.config = get_config_loader()
        
        # Load rewards configuration
        self.rewards_config = self.config.load_rewards_config()
        if not self.rewards_config:
            raise RuntimeError("Failed to load rewards configuration from config_loader - check config/rewards_config.json")
        
        # Calculate max_units for action/observation space
        self.max_units = self._calculate_max_units_from_scenario(scenario_file)
        
        # Define action space: unit_idx * 8 + action_type
        # Actions per unit: [move_north, move_south, move_east, move_west, shoot, charge, attack, wait]
        self.action_space = spaces.Discrete(self.max_units * 8)
        
        # Define observation space: Fixed size based on max_units * 11 + 4
        # AI units (max_units * 7) + Enemy units (max_units * 4) + Phase encoding (4)
        obs_size = self.max_units * 11 + 4
        self.observation_space = spaces.Box(low=0, high=1, shape=(obs_size,), dtype=np.float32)
        
        # Initialize Python mirror game controller
        self._initialize_mirror_controller(scenario_file)
        
        # Replay tracking - integrate with existing GameReplayLogger system
        self.replay_data = []
        self.save_replay = True
        
        # Store scenario metadata for compatibility
        self.scenario_metadata = None
        self._load_scenario_metadata(scenario_file)
        
        # Game state tracking for Gymnasium interface
        self.game_over = False
        self.winner = None
        self.current_turn = 1
        self.current_phase = "move"
        self.step_count = 0
        self.max_steps_per_episode = 1000
        
        # Explicit unit tracking for compatibility
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Initialize replay logger with existing system
        try:
            from ai.game_replay_logger import GameReplayIntegration
            self.replay_logger = GameReplayIntegration.enhance_training_env(self)
            self.game_logger = self.replay_logger
            if not self.quiet:
                print("✅ GameReplayLogger integrated with gym environment")
        except ImportError as e:
            if not self.quiet:
                print(f"⚠️ GameReplayLogger not available: {e}")
            self.replay_logger = None
            self.game_logger = None

    def _calculate_max_units_from_scenario(self, scenario_file=None):
        """Calculate max_units dynamically from scenario file for action space."""
        if scenario_file and os.path.exists(scenario_file):
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                
                if isinstance(scenario_data, list):
                    units = scenario_data
                elif isinstance(scenario_data, dict) and "units" in scenario_data:
                    units = scenario_data["units"]
                else:
                    units = list(scenario_data.values()) if isinstance(scenario_data, dict) else []
                
                # Count units per player
                player_0_count = sum(1 for unit in units if unit.get("player") == 0)
                player_1_count = sum(1 for unit in units if unit.get("player") == 1)
                return max(player_0_count, player_1_count, 4)
            except Exception as e:
                raise RuntimeError(f"Failed to load scenario file {scenario_file}: {e}")
        
        # Raise error instead of fallback
        raise FileNotFoundError(f"No valid scenario file found at {scenario_file}")

    def _load_scenario_metadata(self, scenario_file):
        """Load scenario metadata for replay compatibility."""
        if scenario_file and os.path.exists(scenario_file):
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                if isinstance(scenario_data, dict) and "metadata" in scenario_data:
                    self.scenario_metadata = scenario_data["metadata"]
            except Exception:
                pass

    def _initialize_mirror_controller(self, scenario_file):
        """Initialize TrainingGameController with scenario data."""
        # Load initial units from scenario
        initial_units = self._load_scenario_units(scenario_file)
        
        # Create controller configuration
        config = GameControllerConfig(
            initial_units=initial_units,
            game_mode="training",
            board_config_name="default",
            config_path="config",
            max_turns=100,
            enable_ai_player=False,
            training_mode=True
        )
        
        # Initialize TrainingGameController
        self.controller = TrainingGameController(config)
        
        # Cache board size for observations - use existing config_loader system
        from config_loader import get_board_size
        cols, rows = get_board_size()
        self.board_size = [cols, rows]

    def _load_scenario_units(self, scenario_file):
        """Load units from scenario file or create default scenario."""
        if scenario_file and os.path.exists(scenario_file):
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                
                if isinstance(scenario_data, list):
                    basic_units = scenario_data
                elif isinstance(scenario_data, dict) and "units" in scenario_data:
                    basic_units = scenario_data["units"]
                elif isinstance(scenario_data, dict):
                    basic_units = list(scenario_data.values())
                else:
                    basic_units = self._create_default_units()
                
                # Enhance units with full properties from unit registry
                return self._enhance_units_with_properties(basic_units)
            except Exception as e:
                if not self.quiet:
                    print(f"Failed to load scenario file {scenario_file}: {e}")
        
        # Create default scenario
        basic_units = self._create_default_units()
        return self._enhance_units_with_properties(basic_units)

    def _create_default_units(self):
        """Create default units for training."""
        default_units = [
            # Player 1 (AI) units
            {"id": 1, "player": 1, "unit_type": "Intercessor", "col": 2, "row": 2},
            {"id": 2, "player": 1, "unit_type": "Intercessor", "col": 4, "row": 2},
            {"id": 3, "player": 1, "unit_type": "AssaultIntercessor", "col": 6, "row": 2},
            {"id": 4, "player": 1, "unit_type": "AssaultIntercessor", "col": 8, "row": 2},
            
            # Player 0 (Enemy) units
            {"id": 11, "player": 0, "unit_type": "Termagant", "col": 2, "row": 15},
            {"id": 12, "player": 0, "unit_type": "Termagant", "col": 4, "row": 15},
            {"id": 13, "player": 0, "unit_type": "Hormagaunt", "col": 6, "row": 15},
            {"id": 14, "player": 0, "unit_type": "Hormagaunt", "col": 8, "row": 15},
        ]
        return default_units

    def _enhance_units_with_properties(self, basic_units):
        """Enhance basic unit data with all required properties from unit registry."""
        enhanced_units = []
        
        for unit_data in basic_units:
            # Get unit type and validate it exists
            unit_type = unit_data.get("unit_type")
            if not unit_type:
                raise ValueError(f"Unit missing unit_type: {unit_data}")
            
            # Get full unit data from registry
            try:
                full_unit_data = self.unit_registry.get_unit_data(unit_type)
            except ValueError as e:
                raise ValueError(f"Unknown unit type '{unit_type}' in scenario: {e}")
            
            # Create enhanced unit with all properties
            enhanced_unit = {
                # Basic scenario properties
                "id": unit_data["id"],
                "player": unit_data["player"],
                "unit_type": unit_type,
                "col": unit_data["col"],
                "row": unit_data["row"],
                
                # Add all TypeScript unit class properties
                "MOVE": full_unit_data["MOVE"],
                "T": full_unit_data["T"],
                "ARMOR_SAVE": full_unit_data["ARMOR_SAVE"],
                "INVUL_SAVE": full_unit_data["INVUL_SAVE"],
                "HP_MAX": full_unit_data["HP_MAX"],
                "LD": full_unit_data["LD"],
                "OC": full_unit_data["OC"],
                "VALUE": full_unit_data["VALUE"],
                
                # Ranged weapon properties
                "RNG_RNG": full_unit_data["RNG_RNG"],
                "RNG_NB": full_unit_data["RNG_NB"],
                "RNG_ATK": full_unit_data["RNG_ATK"],
                "RNG_STR": full_unit_data["RNG_STR"],
                "RNG_AP": full_unit_data["RNG_AP"],
                "RNG_DMG": full_unit_data["RNG_DMG"],
                
                # Close combat properties
                "CC_NB": full_unit_data["CC_NB"],
                "CC_RNG": full_unit_data["CC_RNG"],
                "CC_ATK": full_unit_data["CC_ATK"],
                "CC_STR": full_unit_data["CC_STR"],
                "CC_AP": full_unit_data["CC_AP"],
                "CC_DMG": full_unit_data["CC_DMG"],
                
                # Visual properties
                "ICON": full_unit_data["ICON"],
                "ICON_SCALE": full_unit_data.get("ICON_SCALE", 1.0),
                
                # Game state properties
                "CUR_HP": full_unit_data["HP_MAX"],
                "alive": True,
            }
            
            enhanced_units.append(enhanced_unit)
        
        return enhanced_units

    def reset(self, seed=None, options=None):
        """Reset environment using mirror controller."""
        super().reset(seed=seed)
        
        # Reset mirror controller
        self.controller.reset_game()
        
        # Initialize new episode
        self.controller.start_new_episode()
        
        # Reset environment state
        self.game_over = False
        self.winner = None
        self.step_count = 0
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Sync state from controller
        self._sync_state_from_controller()
        
        # Reset replay data and ensure proper initial state capture
        self.replay_data = []
        
        # Connect and initialize replay logger
        if hasattr(self, 'replay_logger') and self.replay_logger:
            # Capture initial state with enhanced unit data
            self.replay_logger.capture_initial_state()
            # Connect to controller if it supports replay logging
            if hasattr(self.controller, 'connect_replay_logger'):
                self.controller.connect_replay_logger(self.replay_logger)
        
        return self._get_obs(), self._get_info()

    def step(self, action):
        """Execute action using mirror controller."""
        # Check game over conditions
        if self.game_over:
            return self._get_obs(), 0.0, True, False, self._get_info()
        
        # Check step limit
        self.step_count += 1
        if self.step_count >= self.max_steps_per_episode:
            self.game_over = True
            self.winner = None
            return self._get_obs(), 0.0, True, False, self._get_info()
        
        # Get eligible units for current phase
        eligible_units = self._get_eligible_units()
        
        if not eligible_units:
            # No eligible units, advance phase/turn
            self._advance_phase_or_turn()
            return self._get_obs(), 0.0, False, False, self._get_info()
        
        # Decode gym action to mirror action format
        unit_idx = action // 8
        action_type = action % 8
        
        if unit_idx >= len(eligible_units):
            # Invalid unit index, return small penalty
            reward = self._get_small_penalty_reward()
            return self._get_obs(), reward, False, False, self._get_info()
        
        # Get the unit to act
        acting_unit = eligible_units[unit_idx]
        
        # Convert gym action to mirror action format
        mirror_action = self._convert_gym_action_to_mirror(acting_unit, action_type)
        
        # Execute action through controller
        success = self.controller.execute_action(acting_unit["id"], mirror_action)
        
        # Calculate reward
        reward = self._calculate_reward(acting_unit, mirror_action, success)
        
        # Update tracking
        self._last_acting_unit = acting_unit
        
        # Sync state from controller
        self._sync_state_from_controller()
        
        # Check if game ended
        terminated = self.controller.is_game_over()
        if terminated:
            self.game_over = True
            self.winner = self.controller.get_winner()
        
        return self._get_obs(), reward, terminated, False, self._get_info()

    def _get_eligible_units(self):
        """Get units eligible for current phase using controller."""
        all_units = self.controller.get_units()
        current_player = self.controller.get_current_player()
        current_phase = self.controller.get_current_phase()
        
        # Filter units for current player that are eligible for current phase
        eligible_units = []
        for unit in all_units:
            if unit["player"] == current_player and unit.get("alive", True):
                if self._is_unit_eligible_for_phase(unit, current_phase):
                    eligible_units.append(unit)
        
        return eligible_units

    def _is_unit_eligible_for_phase(self, unit, phase):
        """Check if unit is eligible for specific phase using controller logic."""
        # Use controller's phase eligibility logic
        if phase == "move":
            return not unit.get("has_moved", False)
        elif phase == "shoot":
            return not unit.get("has_shot", False)
        elif phase == "charge":
            return not unit.get("has_charged", False)
        elif phase == "combat":
            return not unit.get("has_attacked", False)
        return False

    def _advance_phase_or_turn(self):
        """Advance to next phase or turn using controller."""
        self.controller.advance_phase()
        self._sync_state_from_controller()

    def _convert_gym_action_to_mirror(self, unit, action_type):
        """Convert gym action type to mirror action format."""
        # Map gym action types to mirror actions
        if action_type == 0:  # move_north
            return {"type": "move", "col": unit["col"], "row": unit["row"] - 1}
        elif action_type == 1:  # move_south
            return {"type": "move", "col": unit["col"], "row": unit["row"] + 1}
        elif action_type == 2:  # move_east
            return {"type": "move", "col": unit["col"] + 1, "row": unit["row"]}
        elif action_type == 3:  # move_west
            return {"type": "move", "col": unit["col"] - 1, "row": unit["row"]}
        elif action_type == 4:  # shoot
            target = self._find_shoot_target(unit)
            if target:
                return {"type": "shoot", "target_id": target["id"]}
            else:
                return {"type": "wait"}
        elif action_type == 5:  # charge
            target = self._find_charge_target(unit)
            if target:
                return {"type": "charge", "target_id": target["id"]}
            else:
                return {"type": "wait"}
        elif action_type == 6:  # attack
            target = self._find_combat_target(unit)
            if target:
                return {"type": "combat", "target_id": target["id"]}
            else:
                return {"type": "wait"}
        elif action_type == 7:  # wait
            return {"type": "wait"}
        else:
            return {"type": "wait"}

    def _find_shoot_target(self, unit):
        """Find valid shooting target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("alive", True)]
        
        # Use controller's shooting logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_shoot_target(unit["id"], target["id"]):
                return target
        return None

    def _find_charge_target(self, unit):
        """Find valid charge target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("alive", True)]
        
        # Use controller's charge logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_charge_target(unit["id"], target["id"]):
                return target
        return None

    def _find_combat_target(self, unit):
        """Find valid combat target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("alive", True)]
        
        # Use controller's combat logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_attack_target(unit["id"], target["id"]):
                return target
        return None

    def _calculate_reward(self, acting_unit, action, success):
        """Calculate reward using existing rewards config."""
        unit_rewards = self._get_unit_reward_config(acting_unit)
        
        # Base action rewards
        action_type = action["type"]
        if action_type == "move":
            if success:
                return unit_rewards.get("base_actions", {}).get("move", 0.1)
            else:
                return unit_rewards.get("base_actions", {}).get("wait", 0.0)
        elif action_type == "shoot":
            if success:
                return unit_rewards.get("base_actions", {}).get("ranged_attack", 0.2)
            else:
                return unit_rewards.get("base_actions", {}).get("wait", 0.0)
        elif action_type == "charge":
            if success:
                return unit_rewards.get("base_actions", {}).get("charge", 0.3)
            else:
                return unit_rewards.get("base_actions", {}).get("wait", 0.0)
        elif action_type == "combat":
            if success:
                return unit_rewards.get("base_actions", {}).get("melee_attack", 0.2)
            else:
                return unit_rewards.get("base_actions", {}).get("wait", 0.0)
        elif action_type == "wait":
            return unit_rewards.get("base_actions", {}).get("wait", 0.0)
        else:
            return unit_rewards.get("base_actions", {}).get("wait", 0.0)

    def _get_unit_reward_config(self, unit):
        """Get reward configuration for unit type."""
        unit_type = unit.get("unit_type", "unknown")
        
        try:
            agent_key = self.unit_registry.get_model_key(unit_type)
            if agent_key not in self.rewards_config:
                available_keys = list(self.rewards_config.keys())
                raise KeyError(f"Agent key '{agent_key}' not found in rewards config. Available keys: {available_keys}")
            
            unit_reward_config = self.rewards_config[agent_key]
            if "base_actions" not in unit_reward_config:
                raise KeyError(f"Missing 'base_actions' section in rewards config for agent key '{agent_key}'")
            
            return unit_reward_config
        except ValueError as e:
            # Raise error instead of using fallback values
            raise ValueError(f"Failed to get reward config for unit type '{unit_type}': {e}")

    def _get_small_penalty_reward(self):
        """Get small penalty reward for invalid actions."""
        # Use first available unit's reward config
        eligible_units = self._get_eligible_units()
        if not eligible_units:
            raise RuntimeError("No eligible units available to determine penalty reward")
        
        unit_rewards = self._get_unit_reward_config(eligible_units[0])
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Missing 'base_actions' in reward config for unit")
        if "wait" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'wait' action in base_actions reward config")
        
        return unit_rewards["base_actions"]["wait"]

    def _sync_state_from_controller(self):
        """Sync environment state from controller."""
        self.current_turn = self.controller.get_current_turn()
        self.current_phase = self.controller.get_current_phase()
        
        # Update game over status
        if self.controller.is_game_over():
            self.game_over = True
            self.winner = self.controller.get_winner()

    def _get_obs(self):
        """Get observation in gym format using controller state."""
        obs_size = self.max_units * 11 + 4
        obs = np.zeros(obs_size, dtype=np.float32)
        
        # Get units from controller
        all_units = self.controller.get_units()
        
        # AI units (first max_units * 7 elements)
        ai_units = [u for u in all_units if u["player"] == 1 and u.get("alive", True)]
        for i in range(self.max_units):
            if i < len(ai_units):
                unit = ai_units[i]
                base_idx = i * 7
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit.get("cur_hp", unit.get("hp_max", 1)) / unit.get("hp_max", 1)
                obs[base_idx + 3] = 1.0 if unit.get("has_moved", False) else 0.0
                obs[base_idx + 4] = 1.0 if unit.get("has_shot", False) else 0.0
                obs[base_idx + 5] = 1.0 if unit.get("has_charged", False) else 0.0
                obs[base_idx + 6] = 1.0 if unit.get("has_attacked", False) else 0.0
        
        # Enemy units (next max_units * 4 elements)
        enemy_units = [u for u in all_units if u["player"] == 0 and u.get("alive", True)]
        for i in range(self.max_units):
            if i < len(enemy_units):
                unit = enemy_units[i]
                base_idx = self.max_units * 7 + i * 4
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit.get("cur_hp", unit.get("hp_max", 1)) / unit.get("hp_max", 1)
                obs[base_idx + 3] = 1.0  # alive flag
        
        # Phase encoding (last 4 elements)
        phase_idx = self.max_units * 11
        current_phase = self.controller.get_current_phase()
        if current_phase == "move":
            obs[phase_idx] = 1.0
        elif current_phase == "shoot":
            obs[phase_idx + 1] = 1.0
        elif current_phase == "charge":
            obs[phase_idx + 2] = 1.0
        elif current_phase == "combat":
            obs[phase_idx + 3] = 1.0
        
        return obs

    def _get_info(self):
        """Get info dictionary for Gymnasium interface."""
        all_units = self.controller.get_units()
        ai_units_alive = [u for u in all_units if u["player"] == 1 and u.get("alive", True)]
        enemy_units_alive = [u for u in all_units if u["player"] == 0 and u.get("alive", True)]
        
        return {
            "current_turn": self.current_turn,
            "current_phase": self.current_phase,
            "ai_units_alive": len(ai_units_alive),
            "enemy_units_alive": len(enemy_units_alive),
            "step_count": self.step_count,
            "game_over": self.game_over,
            "winner": self.winner,
            "eligible_units": len(self._get_eligible_units())
        }

    # === COMPATIBILITY METHODS ===

    def save_web_compatible_replay(self, filename):
        """Save replay in web-compatible format (compatibility method)."""
        if hasattr(self.controller, 'get_replay_data'):
            replay_data = self.controller.get_replay_data()
            with open(filename, 'w') as f:
                json.dump(replay_data, f, indent=2)

    def close(self):
        """Close environment."""
        if hasattr(self, 'controller'):
            if hasattr(self.controller, 'cleanup'):
                self.controller.cleanup()

    # === REPLAY INTEGRATION COMPATIBILITY ===

    def connect_replay_logger(self, replay_logger):
        """Connect replay logger for GameReplayIntegration compatibility."""
        self.replay_logger = replay_logger
        self.game_logger = replay_logger
        if hasattr(self, 'controller'):
            self.controller.connect_replay_logger(replay_logger)

# === REGISTRATION ===

def register_environment():
    """Register the phase-based W40K environment with gymnasium."""
    try:
        import gymnasium as gym
        gym.register(
            id='W40K-Phases-v0',
            entry_point='ai.gym40k_mirror:W40KEnv',
        )
        print("✅ W40K Phase-based environment (mirror) registered with gymnasium")
    except Exception as e:
        print(f"⚠️  Failed to register phase-based mirror environment: {e}")

if __name__ == "__main__":
    # Test environment creation and basic functionality
    print("🎮 Testing W40K Phase-Based Mirror Environment")
    print("=" * 50)
    
    try:
        # Create environment
        env = W40KEnv()
        print("✅ Phase-based mirror environment created successfully")
        
        # Test reset
        obs, info = env.reset()
        print(f"✅ Environment reset - observation shape: {obs.shape}")
        print(f"   Game info: Turn {info['current_turn']}, Phase {info['current_phase']}")
        print(f"   Units: {info['ai_units_alive']} AI, {info['enemy_units_alive']} enemy")
        print(f"   Eligible units: {info['eligible_units']}")
        
        # Test a few steps
        print("\n🎯 Testing mirror-based actions...")
        for step in range(5):
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"   Step {step}: Phase {info['current_phase']}, Reward {reward:.2f}, Eligible {info['eligible_units']}")
            
            if done:
                print(f"   Game ended! Winner: {info['winner']}")
                break
        
        env.close()
        print("🎉 All mirror-based tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()