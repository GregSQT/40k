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
        
        # Mirror controller already initialized in __init__ to ensure training_state is available
        # (moved to prevent NoneType errors in external components)
        
        # Replay tracking - integrate with existing GameReplayLogger system
        self.replay_data = []
        self.save_replay = True
        
        # Store scenario metadata for compatibility
        self.scenario_metadata = None
        self._load_scenario_metadata(scenario_file)
        
        # Game state tracking for Gymnasium interface - use TrainingGameState
        self.training_state = None  # Will be initialized in _initialize_mirror_controller
        self.game_over = False
        self.winner = None
        
        # CRITICAL: Initialize mirror controller BEFORE other components try to access training_state
        self._initialize_mirror_controller(scenario_file)
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
        
        # Initialize TrainingGameController and start it
        self.controller = TrainingGameController(config, quiet=self.quiet)
        self.controller.start_game()  # CRITICAL: Start the controller
        
        # Initialize TrainingGameState for proper phase management
        self.training_state = TrainingGameState(initial_units)
        
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
        
        if not basic_units:
            raise ValueError("No basic units provided for enhancement")
        
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
                "ICON_SCALE": full_unit_data.get("ICON_SCALE", 1.0),
                
                # Game state properties
                "CUR_HP": full_unit_data["HP_MAX"],
                "HP_LEFT": full_unit_data["HP_MAX"],
                "alive": True,
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
        
        # Connect and initialize replay logger - SINGLE INSTANCE
        if hasattr(self, 'replay_logger') and self.replay_logger:
            # Give the SAME replay logger to controller
            if hasattr(self.controller, 'connect_replay_logger'):
                self.controller.connect_replay_logger(self.replay_logger)
            # Set replay logger env reference for backward compatibility
            if hasattr(self.replay_logger, 'env'):
                self.replay_logger.env = self
            # Capture initial state with enhanced unit data
            self.replay_logger.capture_initial_state()
        
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
        
        # Check if it's bot's turn (Player 0) - execute bot actions automatically
        current_player = self.controller.get_current_player()
        if not self.quiet:
            print(f"🎮 Step: current_player={current_player}, eligible_units={len(eligible_units)}")
        
        if current_player == 0:
            if not self.quiet:
                print(f"🤖 Executing bot turn for player {current_player}")
            self._execute_bot_turn()
            # Force phase advancement after bot turn to prevent loops
            if not self._get_eligible_units():
                self._advance_phase_or_turn()
            return self._get_obs(), 0.0, False, False, self._get_info()
        
        # Decode gym action to mirror action format
        unit_idx = action // 8
        action_type = action % 8
        
        if unit_idx >= len(eligible_units):
            # Invalid unit index - advance phase to prevent infinite loops
            self._advance_phase_or_turn()
            reward = self._get_small_penalty_reward()
            return self._get_obs(), reward, False, False, self._get_info()
        
        # Get the unit to act
        acting_unit = eligible_units[unit_idx]
        
        # Capture pre-action state for logging
        pre_action_units = self.controller.get_units()
       
        # Convert gym action to mirror action format
        mirror_action = self._convert_gym_action_to_mirror(acting_unit, action_type)
       
        # DETAILED ACTION EXECUTION LOGGING
        if not self.quiet:
            print(f"🎮 STEP {self.step_count}: Player {current_player}, Phase {self.controller.get_current_phase()}")
            print(f"    Eligible units: {len(eligible_units)}")
            print(f"    Acting unit: {acting_unit['id']} at ({acting_unit['col']},{acting_unit['row']})")
            print(f"    Gym action: {action} (unit_idx={unit_idx}, action_type={action_type})")
            print(f"    Mirror action: {mirror_action}")
            print(f"    Pre-action units count: {len(pre_action_units)}")
        
        # Execute action through controller with detailed logging
        try:
            success = self.controller.execute_action(acting_unit["id"], mirror_action)
            if not self.quiet:
                print(f"    ✅ Controller.execute_action returned: {success}")
        except Exception as e:
            if not self.quiet:
                print(f"    ❌ Controller execution error: {e}")
                import traceback
                traceback.print_exc()
            success = False
        
        # CRITICAL FIX: If action succeeds, ensure unit is marked as acted for current phase
        if success:
            if not self.quiet:
                print(f"    ✅ Action succeeded - ensuring unit is marked as acted")
            self._mark_unit_as_acted_for_current_phase(acting_unit)
        
        # CRITICAL FIX: If action execution fails, mark unit as acted and continue
        if not success:
            if not self.quiet:
                print(f"    ⚠️ Action execution FAILED - marking unit as acted for current phase")
            self._mark_unit_as_acted_for_current_phase(acting_unit)
            reward = self._get_small_penalty_reward()
            return self._get_obs(), reward, False, False, self._get_info()
            # Get post-action units for logging
            post_units = self.controller.get_units()
            # Find target if action has one
            target_id = mirror_action.get("target_id") if mirror_action else None
            
            if not self.quiet:
                print(f"    📝 Logging to replay_logger:")
                print(f"        Action: {action}, Type: {action_type}")
                print(f"        Acting unit: {acting_unit['id']}, Target: {target_id}")
                print(f"        Post-action units count: {len(post_units)}")
            
            try:
                self.replay_logger.log_action(
                    action=action,
                    reward=0,  # Will be calculated next
                    pre_action_units=pre_action_units,
                    post_action_units=post_units,
                    acting_unit_id=acting_unit["id"],
                    target_unit_id=target_id,
                    description=f"Action {action_type} by unit {acting_unit['id']}"
                )
                if not self.quiet:
                    print(f"        ✅ Replay logging successful")
            except Exception as e:
                if not self.quiet:
                    print(f"        ❌ Replay logging failed: {e}")
        
        # Calculate reward
        reward = self._calculate_reward(acting_unit, mirror_action, success)
        if not self.quiet:
            print(f"    💰 Calculated reward: {reward}")
        
        # Update tracking
        self._last_acting_unit = acting_unit
        
        # Sync state from controller and validate consistency
        self._sync_state_from_controller()
        
        # Periodically validate state consistency (every 10 steps)
        if self.step_count % 10 == 0:
            self._validate_state_consistency()
        
        # Let phase transition system handle automatic advancement
        remaining_eligible = self._get_eligible_units()
        if not self.quiet:
            if not remaining_eligible:
                print(f"    ⏭️ No eligible units remaining - phase system will auto-advance")
            else:
                print(f"    👥 {len(remaining_eligible)} eligible units remaining")
        
        # Check if game ended
        terminated = self.controller.is_game_over()
        if terminated:
            self.game_over = True
            self.winner = self.controller.get_winner()
        
        return self._get_obs(), reward, terminated, False, self._get_info()
    
    def _validate_state_consistency(self):
        """Validate that all components are using the same game_state object."""
        if not hasattr(self.controller, 'game_state'):
            if not self.quiet:
                print(f"⚠️ Controller missing game_state attribute")
            return False
            
        controller_game_state_id = id(self.controller.game_state)
        training_state_id = id(self.training_state.game_state)
        
        consistency_issues = []
        
        # Check training_state consistency
        if controller_game_state_id != training_state_id:
            consistency_issues.append(f"training_state game_state ID mismatch: {training_state_id} vs {controller_game_state_id}")
        
        # Check state_actions consistency
        if hasattr(self.controller, 'state_actions') and 'set_phase' in self.controller.state_actions:
            action_state_id = id(self.controller.state_actions['set_phase'].__self__.game_state)
            if action_state_id != controller_game_state_id:
                consistency_issues.append(f"state_actions game_state ID mismatch: {action_state_id} vs {controller_game_state_id}")
        
        # Check phase_manager consistency
        if hasattr(self.controller, 'phase_manager') and hasattr(self.controller.phase_manager, 'game_state'):
            phase_state_id = id(self.controller.phase_manager.game_state)
            if phase_state_id != controller_game_state_id:
                consistency_issues.append(f"phase_manager game_state ID mismatch: {phase_state_id} vs {controller_game_state_id}")
        
        if consistency_issues:
            if not self.quiet:
                print(f"❌ State consistency issues found:")
                for issue in consistency_issues:
                    print(f"    {issue}")
            return False
        
        if not self.quiet:
            print(f"✅ All components using consistent game_state object ID: {controller_game_state_id}")
        return True

    def _get_eligible_units(self):
        """Get units eligible for current phase using controller's consistent state."""
        # Use controller's game_state for consistency (delegates to same TrainingGameState)
        try:
            current_player = self.controller.get_current_player()
            current_phase = self.controller.get_current_phase()
            all_units = self.controller.get_units()
        except Exception as e:
            if not self.quiet:
                print(f"⚠️ Controller state access failed, falling back to training_state: {e}")
            # Fallback to direct training_state access
            all_units = self.training_state.game_state["units"]
            current_player = self.training_state.game_state["current_player"]
            current_phase = self.training_state.game_state["phase"]
        
        # Filter units for current player that are eligible for current phase
        eligible_units = []
        for unit in all_units:
            if unit["player"] == current_player and unit.get("alive", True):
                if self._is_unit_eligible_for_phase(unit, current_phase):
                    eligible_units.append(unit)
        
        # DEBUG: Show why no units are eligible
        if not self.quiet and not eligible_units:
            print(f"❌ NO ELIGIBLE UNITS FOUND:")
            print(f"    Current player: {current_player}, Phase: {current_phase}")
            print(f"    Total units: {len(all_units)}")
            player_units = [u for u in all_units if u["player"] == current_player]
            print(f"    Player {current_player} units: {len(player_units)}")
            for unit in player_units[:3]:  # Show first 3 units
                eligible = self._is_unit_eligible_for_phase(unit, current_phase)
                print(f"      Unit {unit['id']}: alive={unit.get('alive', True)}, eligible={eligible}")
                if current_phase == "move":
                    print(f"        has_moved={unit.get('has_moved', False)}")
        
        return eligible_units

    def _is_unit_eligible_for_phase(self, unit, phase):
        """Check if unit is eligible for specific phase using controller logic."""
        # Delegate to controller's proper eligibility logic
        if hasattr(self.controller, 'game_actions') and 'is_unit_eligible' in self.controller.game_actions:
            return self.controller.game_actions['is_unit_eligible'](unit)
        
        # Fallback logic if controller method not available
        units_moved = self.training_state.game_state.get("units_moved", [])
        units_charged = self.training_state.game_state.get("units_charged", [])
        units_attacked = self.training_state.game_state.get("units_attacked", [])
        
        if phase == "move":
            return unit["id"] not in units_moved
        elif phase == "shoot":
            return (unit["id"] not in units_moved and 
                    unit.get("SHOOT_LEFT", 0) > 0)
        elif phase == "charge":
            return unit["id"] not in units_charged
        elif phase == "combat":
            return unit["id"] not in units_attacked
        return False

    def _mark_unit_as_acted_for_current_phase(self, unit):
        """Mark unit as having acted in current phase to prevent infinite loops."""
        current_phase = self.training_state.game_state["phase"]
        unit_id = unit["id"]
        
        if not self.quiet:
            print(f"    🔧 Marking unit {unit_id} as acted for phase {current_phase}")
        
        if hasattr(self.controller, 'state_actions'):
            try:
                if current_phase == "move" and 'add_moved_unit' in self.controller.state_actions:
                    self.controller.state_actions['add_moved_unit'](unit_id)
                elif current_phase == "shoot" and 'update_unit' in self.controller.state_actions:
                    self.controller.state_actions['update_unit'](unit_id, {"SHOOT_LEFT": 0})
                elif current_phase == "charge" and 'add_charged_unit' in self.controller.state_actions:
                    self.controller.state_actions['add_charged_unit'](unit_id)
                elif current_phase == "combat" and 'add_attacked_unit' in self.controller.state_actions:
                    self.controller.state_actions['add_attacked_unit'](unit_id)
                
                if not self.quiet:
                    print(f"    ✅ Unit {unit_id} marked as acted for {current_phase}")
            except Exception as e:
                if not self.quiet:
                    print(f"    ❌ Failed to mark unit as acted: {e}")

    def _advance_phase_or_turn(self):
        """Delegate phase advancement to use_phase_transition.py system."""
        if not self.quiet:
            current_phase = self.training_state.game_state["phase"]
            current_player = self.training_state.game_state["current_player"]
            print(f"🔄 Delegating phase advance: Player {current_player}, Phase {current_phase}")
        
        # Delegate to proper phase transition system through controller
        if hasattr(self.controller, 'phase_transitions'):
            try:
                # Use automatic phase transition system
                transitions_occurred = self.controller.phase_transitions['auto_advance_phases']()
                
                if not self.quiet:
                    final_phase = self.training_state.game_state["phase"]
                    final_player = self.training_state.game_state["current_player"]
                    status = "transitioned" if transitions_occurred else "no change"
                    print(f"🔄 Phase delegation result ({status}): Player {final_player}, Phase {final_phase}")
                    
            except Exception as e:
                if not self.quiet:
                    print(f"❌ Phase transition delegation failed: {e}")
                # Fallback: do nothing - let the system handle it naturally
        else:
            if not self.quiet:
                print(f"⚠️ No phase_transitions available in controller - phase will advance naturally")

    def _convert_gym_action_to_mirror(self, unit, action_type):
        """Convert gym action type to mirror action format with phase validation."""
        # CRITICAL FIX: Always mark unit as acted for current phase regardless of action success
        current_phase = self.training_state.game_state["phase"]
        # Remove this line - unit should only be marked if action fails, not always
        
        # PHASE VALIDATION: Only allow actions appropriate for current phase
        if current_phase == "move":
            # Move phase: only movement and wait actions allowed
            if action_type == 0:  # move_north
                return {"type": "move", "col": unit["col"], "row": unit["row"] - 1}
            elif action_type == 1:  # move_south
                return {"type": "move", "col": unit["col"], "row": unit["row"] + 1}
            elif action_type == 2:  # move_east
                return {"type": "move", "col": unit["col"] + 1, "row": unit["row"]}
            elif action_type == 3:  # move_west
                return {"type": "move", "col": unit["col"] - 1, "row": unit["row"]}
            elif action_type == 7:  # wait
                return {"type": "wait"}
            else:
                # Invalid action for move phase - return wait
                return {"type": "wait"}
        
        elif current_phase == "shoot":
            # Shoot phase: only shooting and wait actions allowed
            if action_type == 4:  # shoot
                target = self._find_shoot_target(unit)
                if target:
                    return {"type": "shoot", "target_id": target["id"]}
                else:
                    return {"type": "wait"}
            elif action_type == 7:  # wait
                return {"type": "wait"}
            else:
                # Invalid action for shoot phase - return wait
                return {"type": "wait"}
        
        elif current_phase == "charge":
            # Charge phase: only charge and wait actions allowed
            if action_type == 5:  # charge
                target = self._find_charge_target(unit)
                if target:
                    return {"type": "charge", "target_id": target["id"]}
                else:
                    return {"type": "wait"}
            elif action_type == 7:  # wait
                return {"type": "wait"}
            else:
                # Invalid action for charge phase - return wait
                return {"type": "wait"}
        
        elif current_phase == "combat":
            # Combat phase: only combat and wait actions allowed
            if action_type == 6:  # attack
                target = self._find_combat_target(unit)
                if target:
                    return {"type": "combat", "target_id": target["id"]}
                else:
                    return {"type": "wait"}
            elif action_type == 7:  # wait
                return {"type": "wait"}
            else:
                # Invalid action for combat phase - return wait
                return {"type": "wait"}
        
        else:
            # Unknown phase - default to wait
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
        base_reward = 0.0
        
        # Validate required reward structure
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'base_actions' section")
        
        base_actions = unit_rewards["base_actions"]
        
        # Base action rewards
        action_type = action["type"]
        if action_type == "move":
            if success:
                if "move" not in base_actions:
                    raise KeyError(f"Base actions missing required 'move' reward")
                base_reward = base_actions["move"]
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
        
        # Add win/lose bonuses
        if self.game_over:
            if "outcomes" not in unit_rewards:
                raise KeyError(f"Unit rewards missing required 'outcomes' section")
            
            outcomes = unit_rewards["outcomes"]
            if self.winner == 1:  # AI wins
                if "win" not in outcomes:
                    raise KeyError(f"Outcomes missing required 'win' reward")
                base_reward += outcomes["win"]
            elif self.winner == 0:  # AI loses
                if "lose" not in outcomes:
                    raise KeyError(f"Outcomes missing required 'lose' reward")
                base_reward += outcomes["lose"]
            else:  # Draw
                if "draw" not in outcomes:
                    raise KeyError(f"Outcomes missing required 'draw' reward")
                base_reward += outcomes["draw"]
        
        return base_reward

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
        """Ensure gym environment references the exact same game_state object as controller."""
        # CRITICAL: Verify and sync game_state object references for perfect consistency
        if hasattr(self.controller, 'game_state'):
            controller_game_state = self.controller.game_state
            training_game_state = self.training_state.game_state
            
            # Verify both are referencing the same object
            if id(controller_game_state) != id(training_game_state):
                if not self.quiet:
                    print(f"⚠️ State object mismatch detected:")
                    print(f"    Controller game_state ID: {id(controller_game_state)}")
                    print(f"    Training_state game_state ID: {id(training_game_state)}")
                
                # Fix: Update training_state to reference the same object as controller
                self.training_state.game_state = controller_game_state
                
                if not self.quiet:
                    print(f"✅ Synchronized: training_state now references controller's game_state")
            
            # Verify state actions are using the correct game_state object
            if hasattr(self.controller, 'state_actions') and 'set_phase' in self.controller.state_actions:
                action_game_state = self.controller.state_actions['set_phase'].__self__.game_state
                if id(action_game_state) != id(controller_game_state):
                    if not self.quiet:
                        print(f"⚠️ State actions using different game_state object!")
                        print(f"    Action game_state ID: {id(action_game_state)}")
                        print(f"    Should be: {id(controller_game_state)}")
                        
        # Update game over status using consistent state
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
        current_phase = self.training_state.game_state["phase"]
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
        ai_units_alive = [u for u in all_units if u["player"] == 1 and u.get("alive", True) and u.get("HP_LEFT", u.get("CUR_HP", 1)) > 0]
        enemy_units_alive = [u for u in all_units if u["player"] == 0 and u.get("alive", True) and u.get("HP_LEFT", u.get("CUR_HP", 1)) > 0]
        
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
            "current_turn": self.training_state.game_state["current_turn"],
            "current_phase": self.training_state.game_state["phase"],
            "ai_units_alive": len(ai_units_alive),
            "enemy_units_alive": len(enemy_units_alive),
            "step_count": self.step_count,
            "game_over": self.game_over,
            "winner": self.winner,
            "eligible_units": len(self._get_eligible_units())
        }

    def _execute_bot_turn(self):
        """Execute bot turn - quickly mark all units as acted and advance phase."""
        current_phase = self.controller.get_current_phase()
        current_player = self.controller.get_current_player()
        
        if not self.quiet:
            print(f"🤖 Bot turn: Player {current_player}, Phase {current_phase} - auto-advancing")
        
        # Get bot units (Player 0) and mark them all as acted
        all_units = self.controller.get_units()
        bot_units = [u for u in all_units if u["player"] == 0 and u.get("alive", True)]
        
        # Mark all bot units as having acted in current phase with debugging
        marked_units = 0
        if hasattr(self.controller, 'state_actions'):
            for bot_unit in bot_units:
                if self._is_unit_eligible_for_phase(bot_unit, current_phase):
                    if current_phase == "move":
                        if 'add_moved_unit' in self.controller.state_actions:
                            try:
                                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
                                marked_units += 1
                                if not self.quiet:
                                    print(f"    🤖 Called add_moved_unit({bot_unit['id']})")
                            except Exception as e:
                                if not self.quiet:
                                    print(f"    ❌ add_moved_unit failed: {e}")
                        else:
                            if not self.quiet:
                                print(f"    ❌ add_moved_unit not found in state_actions")
                                print(f"        Available actions: {list(self.controller.state_actions.keys())}")
                        
                        # FALLBACK: Direct state manipulation if state_actions fails
                        if hasattr(self.controller, 'game_state'):
                            current_moved = self.controller.game_state.get("units_moved", [])
                            if bot_unit["id"] not in current_moved:
                                if isinstance(current_moved, list):
                                    current_moved.append(bot_unit["id"])
                                    if not self.quiet:
                                        print(f"    🔧 FALLBACK: Direct append unit {bot_unit['id']} to units_moved")
                                else:
                                    self.controller.game_state["units_moved"] = [bot_unit["id"]]
                                    if not self.quiet:
                                        print(f"    🔧 FALLBACK: Created units_moved list with unit {bot_unit['id']}")
                    elif current_phase == "shoot":
                        # Shooting phase - set SHOOT_LEFT to 0
                        if 'update_unit' in self.controller.state_actions:
                            self.controller.state_actions['update_unit'](bot_unit["id"], {"SHOOT_LEFT": 0})
                            marked_units += 1
                            if not self.quiet:
                                print(f"    🤖 Set unit {bot_unit['id']} SHOOT_LEFT to 0")
                    elif current_phase == "charge" and 'add_charged_unit' in self.controller.state_actions:
                        self.controller.state_actions['add_charged_unit'](bot_unit["id"])
                        marked_units += 1
                        if not self.quiet:
                            print(f"    🤖 Marked unit {bot_unit['id']} as charged")
                    elif current_phase == "combat" and 'add_attacked_unit' in self.controller.state_actions:
                        self.controller.state_actions['add_attacked_unit'](bot_unit["id"])
                        marked_units += 1
                        if not self.quiet:
                            print(f"    🤖 Marked unit {bot_unit['id']} as attacked")
        
        # Verify the marking worked
        if not self.quiet:
            current_moved = self.controller.game_state.get("units_moved", [])
            print(f"    🤖 Units moved after marking: {current_moved}")
        
        if not self.quiet:
            print(f"🤖 Bot marked {len(bot_units)} units as acted - advancing phase")
        
        # Always advance to next phase after bot turn
        self._advance_phase_or_turn()

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
        enemies = [u for u in all_units if u["player"] != bot_unit["player"] and u.get("alive", True)]
        
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
        
        if success and not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} moved from ({bot_unit['col']},{bot_unit['row']}) to ({new_col},{new_row})")
        elif not self.quiet:
            print(f"🤖 Unit {bot_unit['id']} move failed - marking as moved anyway")
            # Mark as moved even if action failed to prevent infinite loops
            if hasattr(self.controller, 'state_actions') and 'add_moved_unit' in self.controller.state_actions:
                self.controller.state_actions['add_moved_unit'](bot_unit["id"])
                success = True
        
        return success

    def _bot_simple_shoot(self, bot_unit):
        """Simple bot shooting at nearest enemy in range."""
        if bot_unit.get("RNG_RNG", 0) <= 0:
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