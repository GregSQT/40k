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
from ai.game_controller import TrainingGameController, GameControllerConfig
from ai.use_game_state import TrainingGameState
from ai.use_game_actions import TrainingGameActions
from ai.use_phase_transition import TrainingPhaseTransition
from ai.use_game_log import TrainingGameLog
from ai.use_game_config import TrainingGameConfig

# Import existing components for compatibility
from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader

class W40KEnv(gym.Env):
    """
    Complete replacement for gym40k.py using Python mirror architecture.
    Maintains EXACT Gymnasium interface while using Python mirrors for ALL game logic.
    """

    def __init__(self, rewards_config, training_config_name, 
                 controlled_agent, active_agents, scenario_file, 
                 unit_registry, quiet):
        super().__init__()
        
        self.quiet = quiet
        
        # Multi-agent support - reuse shared registry if provided
        self.unit_registry = unit_registry
        self.controlled_agent = controlled_agent
        self.active_agents = active_agents
        
        # Load configuration
        self.config = get_config_loader()
        
        # Load rewards configuration
        self.rewards_config = self.config.load_rewards_config(rewards_config)
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
        
        # Mirror controller already initialized in __init__ to ensure training_state is available
        # (moved to prevent NoneType errors in external components)
        
        # Replay tracking - integrate with existing GameReplayLogger system
        self.replay_data = []
        self.save_replay = True
        
        # Store scenario metadata for compatibility
        self.scenario_metadata = None
        self._load_scenario_metadata(scenario_file)
        
        # Game state tracking for Gymnasium interface - use controller's state only
        # CRITICAL FIX: Remove training_state entirely - only use controller.game_state
        self.game_over = False
        self.winner = None
        
        # CRITICAL: Initialize mirror controller BEFORE other components try to access controller state
        self._initialize_mirror_controller(scenario_file, training_config_name)
        
        # Explicit unit tracking for compatibility
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Initialize replay logger after controller is ready
        try:
            from ai.game_replay_logger import GameReplayIntegration
            # CRITICAL FIX: Initialize after controller is set up
            self.replay_logger = None  # Will be set up after controller init
            self.game_logger = None
        except ImportError as e:
            self.replay_logger = None
            self.game_logger = None

        # CRITICAL: Connect gym environment to controller for delegation
        self.controller.connect_gym_env(self)

    def _get_eligible_units(self):
        """Delegate to controller for eligible units - compatibility method."""
        return self.controller._get_gym_eligible_units()

    def _calculate_max_units_from_scenario(self, scenario_file):
        """Calculate max_units dynamically from scenario file for action space."""
        if not scenario_file:
            raise ValueError("Scenario file path is required for max_units calculation")
        
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(f"Scenario file not found for max_units calculation: {scenario_file}")
        
        try:
            with open(scenario_file, 'r') as f:
                scenario_data = json.load(f)
            
            if isinstance(scenario_data, list):
                units = scenario_data
            elif isinstance(scenario_data, dict) and "units" in scenario_data:
                units = scenario_data["units"]
            elif isinstance(scenario_data, dict):
                units = list(scenario_data.values())
            else:
                raise ValueError(f"Invalid scenario data structure in {scenario_file}")
            
            # Count units per player - validate player field exists
            player_0_count = sum(1 for unit in units if unit["player"] == 0)
            player_1_count = sum(1 for unit in units if unit["player"] == 1)
            if player_0_count == 0 and player_1_count == 0:
                raise ValueError(f"No valid units found in scenario file {scenario_file}")
            return max(player_0_count, player_1_count)
        except Exception as e:
            raise RuntimeError(f"Failed to process scenario file {scenario_file} for max_units: {e}")

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

    def _initialize_mirror_controller(self, scenario_file, training_config_name):
        """Initialize TrainingGameController with scenario data."""
        # Load initial units from scenario
        initial_units = self._load_scenario_units(scenario_file)
        
        # Create controller configuration
        config = GameControllerConfig(
            initial_units=initial_units,
            game_mode="training",
            board_config_name="default",
            config_path=str(self.config.config_dir),
            max_turns=self.config.get_max_turns(),
            enable_ai_player=False,
            training_mode=True,
            training_config_name=training_config_name,
            log_available_height=self.config.get_log_available_height()
        )
        
        # Initialize TrainingGameController and start it
        self.controller = TrainingGameController(config, quiet=self.quiet)
        self.controller.start_game()  # CRITICAL: Start the controller
        
        # CRITICAL FIX: Use controller's game_state directly - no separate training_state
        self.training_state = None  # Remove separate state object
        
        # Cache board size for observations - use existing config_loader system
        from config_loader import get_board_size
        cols, rows = get_board_size()
        self.board_size = [cols, rows]

    def _load_scenario_units(self, scenario_file):
        """Load units from scenario file - raises error if missing."""
        if not scenario_file:
            raise ValueError("Scenario file path is required")
        
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
        
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
                raise ValueError(f"Invalid scenario data format in {scenario_file}")
            
            # Enhance units with full properties from unit registry
            return self._enhance_units_with_properties(basic_units)
        except Exception as e:
            raise RuntimeError(f"Failed to load scenario file {scenario_file}: {e}")

    def _enhance_units_with_properties(self, basic_units):
        """Enhance basic unit data with all required properties from unit registry."""
        enhanced_units = []
        
        if not basic_units:
            raise ValueError("No basic units provided for enhancement")
        
        for unit_data in basic_units:
            # Get unit type and validate it exists
            if "unit_type" not in unit_data:
                raise ValueError(f"Unit missing required 'unit_type' field: {unit_data}")
            unit_type = unit_data["unit_type"]
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
                "name": unit_data.get("name", f"{unit_type}_{unit_data['id']}"),
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
                "ICON_SCALE": full_unit_data["ICON_SCALE"],
                
                # Game state properties
                "CUR_HP": full_unit_data["HP_MAX"],
                "HP_LEFT": full_unit_data["HP_MAX"],
                "alive": True,
                "has_moved": False,
                "has_shot": False,
                "has_charged": False,
                "has_attacked": False,
                "has_charged_this_turn": False,
                "SHOOT_LEFT": full_unit_data["RNG_NB"],
            }
            
            enhanced_units.append(enhanced_unit)
        
        if not enhanced_units:
            raise ValueError("No enhanced units created - check unit registry and scenario data")
        
        return enhanced_units

    def reset(self, seed=None, options=None):
        """Reset environment using mirror controller."""
        super().reset(seed=seed)
        
        # Reset mirror controller - this creates NEW objects!
        self.controller.reset_game()
        
        # Initialize new episode
        self.controller.start_new_episode()
        
        # CRITICAL: Only enable replay logging during evaluation, not training
        self.is_evaluation_mode = getattr(self, '_force_evaluation_mode', False)
        if hasattr(self, 'replay_logger') and self.replay_logger:
            # Set evaluation mode on replay logger
            self.replay_logger.is_evaluation_mode = self.is_evaluation_mode
            # Only capture initial state during evaluation
            if self.is_evaluation_mode:
                self.replay_logger.capture_initial_state()
                # CRITICAL FIX: Force initial_game_state population
                units = self.controller.get_units()
                if units:
                    self.replay_logger.initial_game_state = {"units": [{
                        "id": unit["id"], "unit_type": unit["unit_type"], "player": unit["player"],
                        "col": unit["col"], "row": unit["row"], "HP_MAX": unit["HP_MAX"],
                        "MOVE": unit["MOVE"], "RNG_RNG": unit["RNG_RNG"], "RNG_DMG": unit["RNG_DMG"],
                        "CC_DMG": unit["CC_DMG"], "CC_RNG": unit["CC_RNG"], "alive": unit["alive"]
                    } for unit in units]}
        
        # Reset environment state
        self.game_over = False
        self.winner = None
        
        # CRITICAL: Episode starts at beginning of first Player 0 turn (movement phase) - Turn 1
        self.controller.game_state["current_turn"] = 1  # Always start at Turn 1 per specification
        self.controller.game_state["current_player"] = 0  # Episode starts with Player 0
        self.controller.game_state["phase"] = "move"
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Update game status using controller state directly
        self._update_game_status()
        
        # Reset replay data
        self.replay_data = []
        
        # CRITICAL FIX: Return observation and info as required by Gymnasium interface
        return self._get_obs(), self._get_info()
        
    def capture_initial_state(self):
        """Capture initial game state - compatibility method for GameReplayLogger interface."""
        # CRITICAL FIX: Only log game start if evaluation mode is active and no entries exist yet
        if hasattr(self, 'replay_logger') and self.replay_logger:
            if len(self.replay_logger.combat_log_entries) == 0:
                self.replay_logger.log_game_start()
        
        return self._get_obs(), self._get_info()

    def step(self, action):
        """Execute action using mirror controller - PURE DELEGATION."""
        # ARCHITECTURAL COMPLIANCE: Delegate everything to controller
        obs, reward, terminated, truncated, info = self.controller.execute_gym_action(action)
        
        # Update environment state from controller
        self.game_over = terminated
        self.winner = info.get('winner')
        
        return obs, reward, terminated, truncated, info
    
    def _mark_unit_as_acted_for_current_phase(self, unit):
        """Mark unit as acted for current phase to prevent infinite loops."""
        current_phase = self.controller.get_current_phase()
        unit_id = unit["id"]
        
        if current_phase == "move":
            self.controller.state_actions['add_moved_unit'](unit_id)
        elif current_phase == "shoot":
            self.controller.state_actions['add_moved_unit'](unit_id)  # Shooting uses moved units tracking
        elif current_phase == "charge":
            self.controller.state_actions['add_charged_unit'](unit_id)
        elif current_phase == "combat":
            self.controller.state_actions['add_attacked_unit'](unit_id)

    def _find_shoot_target(self, unit):
        """Find valid shooting target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u["alive"]]
        
        # Use controller's shooting logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_shoot_target(unit["id"], target["id"]):
                return target
        return None

    def _find_charge_target(self, unit):
        """Find valid charge target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u["alive"]]
        
        # Use controller's charge logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_charge_target(unit["id"], target["id"]):
                return target
        return None

    def _find_combat_target(self, unit):
        """Find valid combat target using controller logic."""
        all_units = self.controller.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u["alive"]]
        
        # Use controller's combat logic to find valid target
        for target in enemy_units:
            if self.controller.can_unit_attack_target(unit["id"], target["id"]):
                return target
        return None

    def _calculate_reward(self, acting_unit, action, success):
        """Calculate reward using existing rewards config."""
        unit_rewards = self._get_unit_reward_config(acting_unit)
        base_reward = 0.0
        
        # Validate required reward structure
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'base_actions' section")
        
        base_actions = unit_rewards["base_actions"]
        
        # Base action rewards
        action_type = action["type"]
        if action_type == "move":
            if success:
                # Use move_close as default move reward (PvP uses specific move types)
                move_key = "move_close" if "move_close" in base_actions else "wait"
                if move_key not in base_actions:
                    raise KeyError(f"Base actions missing required '{move_key}' reward")
                base_reward = base_actions[move_key]
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "shoot":
            if success:
                if "ranged_attack" not in base_actions:
                    raise KeyError(f"Base actions missing required 'ranged_attack' reward")
                base_reward = base_actions["ranged_attack"]
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "charge":
            if success:
                if "charge" not in base_actions:
                    raise KeyError(f"Base actions missing required 'charge' reward")
                base_reward = base_actions["charge"]
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "combat":
            if success:
                if "melee_attack" not in base_actions:
                    raise KeyError(f"Base actions missing required 'melee_attack' reward")
                base_reward = base_actions["melee_attack"]
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "wait":
            if "wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'wait' reward")
            base_reward = base_actions["wait"]
        else:
            if "wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'wait' reward")
            base_reward = base_actions["wait"]
        
        # Add win/lose bonuses from situational_modifiers
        if self.game_over:
            modifiers = unit_rewards.get("situational_modifiers", {})
            
            if self.winner == 1:  # AI wins
                if "win" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'win' reward")
                base_reward += modifiers["win"]
            elif self.winner == 0:  # AI loses
                if "lose" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'lose' reward")
                base_reward += modifiers["lose"]
            else:  # Draw
                if "draw" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'draw' reward")
                base_reward += modifiers["draw"]
        
        return base_reward

    def _get_unit_reward_config(self, unit):
        """Get reward configuration for unit type."""
        if "unit_type" not in unit:
            raise KeyError(f"Unit missing required 'unit_type' field: {unit}")
        unit_type = unit["unit_type"]
        
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
            # If no eligible units, use any AI unit to get the penalty value
            all_units = self.controller.get_units()
            ai_units = [u for u in all_units if u["player"] == 1]
            if ai_units:
                unit_rewards = self._get_unit_reward_config(ai_units[0])
                return unit_rewards.get("base_actions", {}).get("wait", -0.1)
            # Final fallback
            return -0.1
        
        unit_rewards = self._get_unit_reward_config(eligible_units[0])
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Missing 'base_actions' in reward config for unit")
        if "wait" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'wait' action in base_actions reward config")
        
        return unit_rewards["base_actions"]["wait"]

    def _update_game_status(self):
        """Update game over status using controller state directly."""
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
        ai_units = [u for u in all_units if u["player"] == 1 and u["alive"]]
        for i in range(self.max_units):
            if i < len(ai_units):
                unit = ai_units[i]
                base_idx = i * 7
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit["CUR_HP"] / unit["HP_MAX"]
                obs[base_idx + 3] = 1.0 if unit["has_moved"] else 0.0
                obs[base_idx + 4] = 1.0 if unit["has_shot"] else 0.0
                obs[base_idx + 5] = 1.0 if unit["has_charged"] else 0.0
                obs[base_idx + 6] = 1.0 if unit["has_attacked"] else 0.0
        
        # Enemy units (next max_units * 4 elements)
        enemy_units = [u for u in all_units if u["player"] == 0 and u["alive"]]
        for i in range(self.max_units):
            if i < len(enemy_units):
                unit = enemy_units[i]
                base_idx = self.max_units * 7 + i * 4
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit["CUR_HP"] / unit["HP_MAX"]
                obs[base_idx + 3] = 1.0  # alive flag
        
        # Phase encoding (last 4 elements)
        phase_idx = self.max_units * 11
        current_phase = self.controller.game_state["phase"]
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
        ai_units_alive = [u for u in all_units if u["player"] == 1 and u["alive"] and u["CUR_HP"] > 0]
        enemy_units_alive = [u for u in all_units if u["player"] == 0 and u["alive"] and u["CUR_HP"] > 0]
        
        # Check for game end conditions
        if len(ai_units_alive) == 0 and len(enemy_units_alive) > 0:
            self.winner = 0  # Enemy wins
            self.game_over = True
        elif len(enemy_units_alive) == 0 and len(ai_units_alive) > 0:
            self.winner = 1  # AI wins
            self.game_over = True
        elif len(ai_units_alive) == 0 and len(enemy_units_alive) == 0:
            self.winner = None  # Draw
            self.game_over = True
        
        return {
            "current_turn": self.controller.game_state["current_turn"],
            "current_phase": self.controller.game_state["phase"], 
            "ai_units_alive": len(ai_units_alive),
            "enemy_units_alive": len(enemy_units_alive),
            "game_over": self.game_over,
            "winner": self.winner,
            "eligible_units": len(self._get_eligible_units())
        }

    def _execute_full_bot_turn(self):
        """Execute complete bot turn through all phases with proper logging."""
        current_player = self.controller.get_current_player()
        
        # Execute bot actions for current phase with logging
        eligible_units = self._get_eligible_units()
        bot_units = [u for u in eligible_units if u["player"] == 0]
        
        for bot_unit in bot_units:
            # Execute simple bot action with unified logging
            current_phase = self.controller.get_current_phase()
            current_turn = self.controller.game_state["current_turn"]
            
            # Execute simple action based on phase
            if current_phase == "move":
                action_type = "move"
                mirror_action = {"type": "wait"}  # Simple wait for now
            elif current_phase == "shoot":
                action_type = "wait"  # Bot doesn't shoot in simple mode
                mirror_action = {"type": "wait"}
            elif current_phase == "charge":
                action_type = "wait"  # Bot doesn't charge in simple mode
                mirror_action = {"type": "wait"}
            elif current_phase == "combat":
                action_type = "wait"  # Bot doesn't attack in simple mode
                mirror_action = {"type": "wait"}
            else:
                action_type = "wait"
                mirror_action = {"type": "wait"}
            
            # Log bot action using unified system
            from shared.gameLogStructure import log_unified_action
            log_unified_action(
                env=self,
                action_type=action_type,
                acting_unit=bot_unit,
                target_unit=None,
                reward=0.0,
                phase=current_phase,
                turn_number=current_turn
            )
            
            # Mark unit as acted to advance phase
            self._mark_unit_as_acted_for_current_phase(bot_unit)

    def _execute_bot_turn_with_logging(self, eligible_units, pre_action_units):
        """Execute bot turn WITH proper action logging for replay capture."""
        current_phase = self.controller.get_current_phase()
        current_player = self.controller.get_current_player()
        
        # Get bot units (Player 0) and execute/log actual actions
        bot_units = [u for u in eligible_units if u["player"] == 0]
        
        for bot_unit in bot_units:
            # Create a realistic action for this bot unit
            action_type = 6  # Wait action as default
            mirror_action = {"type": "wait"}
            
            # Try to find a more interesting action based on phase
            if current_phase == "move":
                # Simple movement towards nearest enemy (like _bot_simple_move)
                all_units = self.controller.get_units()
                enemy_units = [u for u in all_units if u["player"] != bot_unit["player"] and u["alive"]]
                if enemy_units:
                    target = enemy_units[0]  # Move toward first enemy
                    dx = 1 if target["col"] > bot_unit["col"] else (-1 if target["col"] < bot_unit["col"] else 0)
                    dy = 1 if target["row"] > bot_unit["row"] else (-1 if target["row"] < bot_unit["row"] else 0)
                    new_col = max(0, min(self.board_size[0] - 1, bot_unit["col"] + dx))
                    new_row = max(0, min(self.board_size[1] - 1, bot_unit["row"] + dy))
                    mirror_action = {"type": "move", "col": new_col, "row": new_row}
                    action_type = 0  # Move action
            elif current_phase == "shoot":
                # Try to find shooting target
                target = self._find_shoot_target(bot_unit)
                if target:
                    mirror_action = {"type": "shoot", "target_id": target["id"]}
                    action_type = 4  # Shoot action
                else:
                    # No target found - use wait action
                    mirror_action = {"type": "wait"}
                    action_type = 7  # Wait action
            elif current_phase == "charge":
                # Try to find charge target  
                target = self._find_charge_target(bot_unit)
                if target:
                    mirror_action = {"type": "charge", "target_id": target["id"]}
                    action_type = 5  # Charge action
            elif current_phase == "combat":
                # Try to find combat target
                target = self._find_combat_target(bot_unit)
                if target:
                    mirror_action = {"type": "combat", "target_id": target["id"]}
                    action_type = 7  # Combat action
            
            # Execute the action through controller
            try:
                success = self.controller.execute_action(bot_unit["id"], mirror_action)
                # CRITICAL DEBUG: Check if units_moved was updated after successful move
                if success and mirror_action["type"] == "move":
                    current_moved = self.controller.game_state["units_moved"]
            except Exception as e:
                print(f"    ❌ Bot unit {bot_unit['id']} action failed: {e}")
                success = False
            
            # Get post-action units for logging
            post_action_units = self.controller.get_units()
            
            # CRITICAL: Log this bot action for replay capture
            # Use unified logging system for P0 (bot) actions
            from shared.gameLogStructure import log_unified_action
            
            # Get required parameters - no defaults allowed
            current_turn = self.controller.game_state["current_turn"]
            current_phase = self.controller.game_state["phase"]
            target_id = mirror_action.get("target_id")
            
            # Find target unit if target_id exists
            target_unit = None
            if target_id:
                all_units = self.controller.get_units()
                for unit in all_units:
                    if unit["id"] == target_id:
                        target_unit = unit
                        break
            
            log_unified_action(
                env=self,
                action_type=mirror_action["type"],
                acting_unit=bot_unit,
                target_unit=target_unit,
                reward=0.0,
                phase=current_phase,
                turn_number=current_turn
            )
            
            # Mark unit as acted for current phase to prevent infinite loops
            self._mark_unit_as_acted_for_current_phase(bot_unit)

    def _execute_simple_bot_action(self, bot_unit, current_phase):
        """Execute simple scripted action for bot unit."""
        try:
            if current_phase == "move":
                # Simple move towards nearest enemy
                return self._bot_simple_move(bot_unit)
            elif current_phase == "shoot":
                # Simple shooting at nearest enemy
                return self._bot_simple_shoot(bot_unit)
            elif current_phase == "charge":
                # Simple charge at nearest enemy
                return self._bot_simple_charge(bot_unit)
            elif current_phase == "combat":
                # Simple combat attack
                return self._bot_simple_combat(bot_unit)
            
            return False
        except Exception as e:
            if not self.quiet:
                print(f"🤖 Bot action failed for unit {bot_unit['id']}: {e}")
                import traceback
                traceback.print_exc()
            return False

    def _bot_simple_move(self, bot_unit):
        """Simple bot movement towards nearest enemy."""
        # Find nearest enemy
        all_units = self.controller.get_units()
        enemies = [u for u in all_units if u["player"] != bot_unit["player"] and u["alive"]]
        
        if not enemies:
            # No enemies - just mark as moved to advance phase
            if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
            return True
        
        # Move towards first enemy (simple AI)
        target = enemies[0]
        
        # Calculate simple direction
        dx = 1 if target["col"] > bot_unit["col"] else (-1 if target["col"] < bot_unit["col"] else 0)
        dy = 1 if target["row"] > bot_unit["row"] else (-1 if target["row"] < bot_unit["row"] else 0)
        
        new_col = max(0, min(23, bot_unit["col"] + dx))  # Clamp to board bounds
        new_row = max(0, min(26, bot_unit["row"] + dy))   # Clamp to board bounds
        
        # Execute move through controller
        mirror_action = {"type": "move", "col": new_col, "row": new_row}
        success = self.controller.execute_action(bot_unit["id"], mirror_action)
        # Mark as moved even if action failed to prevent infinite loops
        if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
            self.controller.state_actions['add_moved_unit'](bot_unit["id"])
            success = True
        
        return success

    def _bot_simple_shoot(self, bot_unit):
        """Simple bot shooting at nearest enemy in range."""
        if bot_unit["RNG_RNG"] <= 0:
            # No ranged weapon - mark as moved to advance phase
            if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
            return True
        
        target = self._find_shoot_target(bot_unit)
        if not target:
            # No target - mark as moved to advance phase
            if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
            return True
        
        mirror_action = {"type": "shoot", "target_id": target["id"]}
        success = self.controller.execute_action(bot_unit["id"], mirror_action)
        
        if success and not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} shot at unit {target['id']}")
        elif not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} shoot failed - marking as moved anyway")
            # Mark as moved even if action failed
            if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
                success = True
        
        return success

    def _bot_simple_charge(self, bot_unit):
        """Simple bot charge at nearest enemy."""
        target = self._find_charge_target(bot_unit)
        if not target:
            return False
        
        mirror_action = {"type": "charge", "target_id": target["id"]}
        success = self.controller.execute_action(bot_unit["id"], mirror_action)
        
        if success and not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} charged unit {target['id']}")
        
        return success

    def _bot_simple_combat(self, bot_unit):
        """Simple bot combat attack."""
        target = self._find_combat_target(bot_unit)
        if not target:
            return False
        
        mirror_action = {"type": "combat", "target_id": target["id"]}
        success = self.controller.execute_action(bot_unit["id"], mirror_action)
        
        if success and not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} attacked unit {target['id']}")
        
        return success
    
    def _get_action_name_from_type(self, action_type: int) -> str:
        """Convert gym action type to action name for unified logging"""
        action_mapping = {
            0: "move",  # move_north
            1: "move",  # move_south  
            2: "move",  # move_east
            3: "move",  # move_west
            4: "shoot",
            5: "charge", 
            6: "combat",
            7: "wait"
        }
        
        if action_type not in action_mapping:
            raise ValueError(f"Unknown action_type {action_type}. Valid types: {list(action_mapping.keys())}")
        
        return action_mapping[action_type]
    
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
        # Set evaluation mode when logger is connected
        self.is_evaluation_mode = True
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
        
        # Test a few actions
        print("\n🎯 Testing mirror-based actions...")
        for action_count in range(5):
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"   Action {action_count}: Phase {info['current_phase']}, Reward {reward:.2f}, Eligible {info['eligible_units']}")
            
            if done:
                print(f"   Game ended! Winner: {info['winner']}")
                break
        
        env.close()
        print("🎉 All mirror-based tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()