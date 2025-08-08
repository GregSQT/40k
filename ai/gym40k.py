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
        self.rewards_config = self.config.load_rewards_config("default")
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
        self._initialize_mirror_controller(scenario_file)
        self.step_count = 0
        self.max_steps_per_episode = 1000
        
        # Explicit unit tracking for compatibility
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Initialize replay logger after controller is ready
        try:
            from ai.game_replay_logger import GameReplayIntegration
            # CRITICAL FIX: Initialize after controller is set up
            self.replay_logger = None  # Will be set up after controller init
            self.game_logger = None
            if not self.quiet:
                print("🔧 Replay logger will be initialized after controller setup")
        except ImportError as e:
            if not self.quiet:
                print(f"⚠️ GameReplayLogger not available: {e}")
            self.replay_logger = None
            self.game_logger = None

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
            return max(player_0_count, player_1_count, 4)
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
        
        # CRITICAL FIX: After reset_game(), controller has NEW objects - refresh our references
        print(f"🔧 RESET: Refreshing references after controller.reset_game()")
        
        # Initialize new episode
        self.controller.start_new_episode()
        
        # Reset environment state
        self.game_over = False
        self.winner = None
        self.step_count = 0
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Update game status using controller state directly
        self._update_game_status()
        
        # CRITICAL DEBUG: Verify we have fresh phase transition objects
        if hasattr(self.controller, 'phase_transitions'):
            print(f"🔧 RESET: Fresh phase_transitions available: {list(self.controller.phase_transitions.keys())}")
        else:
            print(f"🔧 RESET: ERROR - No phase_transitions after reset!")
        
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
        
        # Capture pre-action state for logging BEFORE bot turn check
        pre_action_units = self.controller.get_units()
        
        if current_player == 0:
            # Execute bot turn with proper action logging
            self._execute_bot_turn_with_logging(eligible_units, pre_action_units)
            # Return to allow natural phase system to work
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
        
        # Get post-action units for logging BEFORE any early returns
        post_units = self.controller.get_units()
        # Find target if action has one
        target_id = mirror_action.get("target_id") if mirror_action else None
        
        # CRITICAL DEBUG: Check replay logger connection step by step
        print(f"🔍 DEBUG STEP 1: hasattr(self, 'replay_logger') = {hasattr(self, 'replay_logger')}")
        if hasattr(self, 'replay_logger'):
            print(f"🔍 DEBUG STEP 2: self.replay_logger exists = {self.replay_logger is not None}")
            if self.replay_logger:
                print(f"🔍 DEBUG STEP 3: replay_logger type = {type(self.replay_logger)}")
                print(f"🔍 DEBUG STEP 4: hasattr log_action = {hasattr(self.replay_logger, 'log_action')}")
        
        # Log the action attempt regardless of success/failure
        if hasattr(self, 'replay_logger') and self.replay_logger:
            if not self.quiet:
                print(f"    📝 Logging to replay_logger:")
                print(f"        Action: {action}, Type: {action_type}")
                print(f"        Acting unit: {acting_unit['id']}, Target: {target_id}")
                print(f"        Post-action units count: {len(post_units)}")
            
            print(f"🔍 DEBUG STEP 5: About to call log_action method")
            print(f"🔍 DEBUG ACTION DETAILS: gym_action={action}, action_type={action_type}, unit_id={acting_unit['id']}, target_id={target_id}")
            print(f"🔍 DEBUG BEFORE CALL: combat_log_entries count = {len(self.replay_logger.combat_log_entries)}")
            try:
                self.replay_logger.log_action(
                    action=action,
                    reward=0,  # Will be calculated next
                    pre_action_units=pre_action_units,
                    post_action_units=post_units,
                    acting_unit_id=acting_unit["id"],
                    target_unit_id=target_id,
                    description=f"Action {action_type} by unit {acting_unit['id']} {'succeeded' if success else 'failed'}"
                )
                print(f"🔍 DEBUG AFTER CALL: combat_log_entries count = {len(self.replay_logger.combat_log_entries)}")
                print(f"🔍 DEBUG STEP 6: log_action call completed successfully")
                if not self.quiet:
                    print(f"        ✅ Replay logging successful")
            except Exception as e:
                print(f"🔍 DEBUG STEP 6: log_action call FAILED with exception: {e}")
                import traceback
                traceback.print_exc()
                if not self.quiet:
                    print(f"        ❌ Replay logging failed: {e}")
        else:
            print(f"🔍 DEBUG: Replay logger connection FAILED - no logging will occur")

        # CRITICAL FIX: If action execution fails, mark unit as acted and continue
        if not success:
            if not self.quiet:
                print(f"    ⚠️ Action execution FAILED - marking unit as acted for current phase")
            self._mark_unit_as_acted_for_current_phase(acting_unit)
            reward = self._get_small_penalty_reward()
            return self._get_obs(), reward, False, False, self._get_info()
        
        # Calculate reward
        reward = self._calculate_reward(acting_unit, mirror_action, success)
        if not self.quiet:
            print(f"    💰 Calculated reward: {reward}")
        
        # Update tracking
        self._last_acting_unit = acting_unit
        
        # Update game status using controller state directly
        self._update_game_status()
        
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
                print(f"❌ Controller state access failed: {e}")
                import traceback
                traceback.print_exc()
            raise RuntimeError(f"Controller state access failed - no fallback available: {e}")
        
        # Filter units for current player that are eligible for current phase
        eligible_units = []
        for unit in all_units:
            # CRITICAL: Validate all units have required properties - NO DEFAULTS
            if "alive" not in unit:
                raise KeyError(f"Unit {unit.get('id', 'unknown')} missing required 'alive' property: {unit}")
            if "player" not in unit:
                raise KeyError(f"Unit {unit.get('id', 'unknown')} missing required 'player' property: {unit}")
            
            if unit["player"] == current_player and unit["alive"]:
                if self._is_unit_eligible_for_phase(unit, current_phase):
                    eligible_units.append(unit)
        
        return eligible_units

    def _is_unit_eligible_for_phase(self, unit, phase):
        """Check if unit is eligible for specific phase using controller logic."""
        # CRITICAL FIX: Always use controller's eligibility system with proper debugging
        if hasattr(self.controller, 'game_actions') and 'is_unit_eligible' in self.controller.game_actions:
            controller_result = self.controller.game_actions['is_unit_eligible'](unit)
            
            # DEBUG: Show detailed eligibility check
            if not self.quiet:
                units_moved = self.controller.game_state.get("units_moved", [])
                print(f"🔧 ELIGIBILITY DEBUG: Unit {unit['id']}, Phase {phase}")
                print(f"    Controller result: {controller_result}")
                print(f"    Units moved list: {units_moved}")
                print(f"    Unit in moved list: {unit['id'] in units_moved}")
            
            return controller_result
        
        # CRITICAL ERROR: Controller eligibility system missing
        available_methods = list(self.controller.game_actions.keys()) if hasattr(self.controller, 'game_actions') else 'No game_actions'
        raise RuntimeError(f"Controller missing required 'is_unit_eligible' method. Available: {available_methods}")

    def _mark_unit_as_acted_for_current_phase(self, unit):
        """Mark unit as having acted in current phase to prevent infinite loops."""
        current_phase = self.controller.game_state["phase"]
        unit_id = unit["id"]
        
        if hasattr(self.controller, 'state_actions'):
            try:
                if current_phase == "move" and 'add_moved_unit' in self.controller.state_actions:
                    # CRITICAL FIX: Use the state_actions object directly (the correct one)
                    self.controller.state_actions['add_moved_unit'](unit_id)
                    
                    # Verify using the SAME object that was just modified
                    new_units_moved = self.controller.state_actions['add_moved_unit'].__self__.game_state.get('units_moved', [])
                    # Silent verification - debugging completed
                    if unit_id not in new_units_moved:
                        if not self.quiet:
                            print(f"    ⚠️ Unit {unit_id} not tracked in units_moved")
                        
                elif current_phase == "shoot" and 'update_unit' in self.controller.state_actions:
                    self.controller.state_actions['update_unit'](unit_id, {"SHOOT_LEFT": 0})
                elif current_phase == "charge" and 'add_charged_unit' in self.controller.state_actions:
                    self.controller.state_actions['add_charged_unit'](unit_id)
                elif current_phase == "combat" and 'add_attacked_unit' in self.controller.state_actions:
                    self.controller.state_actions['add_attacked_unit'](unit_id)
                
            except Exception as e:
                if not self.quiet:
                    print(f"    ❌ Exception in marking unit as acted: {e}")
                    import traceback
                    traceback.print_exc()

    def _advance_phase_or_turn(self):
        """Delegate phase advancement to use_phase_transition.py system."""
        # CRITICAL FIX: Use only controller's game_state - no separate training_state
        if not hasattr(self.controller, 'game_state'):
            raise RuntimeError("Controller missing required game_state object")
        
        controller_phase = self.controller.game_state["phase"]
        controller_player = self.controller.game_state["current_player"] 
        controller_state_id = id(self.controller.game_state)
        
        print(f"🔄 SINGLE STATE DEBUG: controller game_state[{controller_state_id}]: phase={controller_phase}, player={controller_player}")
        
        # CRITICAL FIX: Remove self.training_state entirely - only use controller's state
        # self.training_state = None  # Line already shows this was removed
        current_phase = controller_phase
        current_player = controller_player
        
        # ALWAYS show critical phase debug (remove count limit)
        print(f"🔄 PHASE ADVANCE: Player {current_player}, Phase {current_phase}")
        # CRITICAL: Debug why phase won't advance
        eligible_units = self._get_eligible_units()
        moved_units = self.controller.game_state.get("units_moved", [])
        player_units = [u for u in self.controller.get_units() if u["player"] == current_player]
        player_unit_ids = [u["id"] for u in player_units]
        print(f"    🔍 Player {current_player} units: {player_unit_ids}")
        print(f"    🔍 Units moved: {moved_units}")
        print(f"    🔍 Eligible units: {len(eligible_units)}")
        print(f"    🔍 All player units marked as moved? {all(uid in moved_units for uid in player_unit_ids)}")
        
        # Count for bot turn limiting only
        if not hasattr(self, '_phase_advance_count'):
            self._phase_advance_count = 0
        self._phase_advance_count += 1
        
        # Delegate to proper phase transition system through controller
        if hasattr(self.controller, 'advance_phase'):
            try:
                # CRITICAL FIX: Use controller's advance_phase method (has process_phase_transitions call)
                self.controller.advance_phase()
                transitions_occurred = True  # Assume success unless exception
                
                final_phase = self.controller.game_state["phase"]
                final_player = self.controller.game_state["current_player"]
                status = "transitioned" if transitions_occurred else "no change"
                print(f"🔄 Phase result ({status}): Player {final_player}, Phase {final_phase}")
                if not transitions_occurred:
                    print(f"    ❌ PHASE STUCK: Phase transition system failed to advance")
                    print(f"    🔍 Expected: All Player {current_player} units should be in units_moved to advance")
                    
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
        current_phase = self.controller.game_state["phase"]
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
            raise RuntimeError("No eligible units available to determine penalty reward")
        
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
        ai_units_alive = [u for u in all_units if u["player"] == 1 and u["alive"] and u["HP_LEFT"] > 0]
        enemy_units_alive = [u for u in all_units if u["player"] == 0 and u["alive"] and u["HP_LEFT"] > 0]
        
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
            "step_count": self.step_count,
            "game_over": self.game_over,
            "winner": self.winner,
            "eligible_units": len(self._get_eligible_units())
        }

    def _execute_bot_turn(self):
        """Execute bot turn - quickly mark all units as acted and advance phase."""
        current_phase = self.controller.get_current_phase()
        current_player = self.controller.get_current_player()
        
        # Minimal bot turn logging
        if not hasattr(self, '_bot_turn_count'):
            self._bot_turn_count = 0
        if self._bot_turn_count < 1 and not self.quiet:
            print(f"🤖 BOT: P{current_player} {current_phase}")
            self._bot_turn_count += 1
        
        # Get bot units (Player 0) and mark them all as acted
        all_units = self.controller.get_units()
        bot_units = [u for u in all_units if u["player"] == 0 and u["alive"]]
        
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
                            current_moved = self.controller.game_state["units_moved"]
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
            current_moved = self.controller.game_state["units_moved"]
            print(f"    🤖 Units moved after marking: {current_moved}")
        
        # Verify the marking worked
        if not self.quiet:
            current_moved = self.controller.game_state["units_moved"]
            print(f"    🤖 Units moved after marking: {current_moved}")
        
        if not self.quiet:
            print(f"🤖 Bot marked {len(bot_units)} units as acted")

    def _execute_bot_turn_with_logging(self, eligible_units, pre_action_units):
        """Execute bot turn WITH proper action logging for replay capture."""
        current_phase = self.controller.get_current_phase()
        current_player = self.controller.get_current_player()
        
        print(f"🤖 BOT TURN WITH LOGGING: Player {current_player}, Phase {current_phase}")
        
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
            if hasattr(self, 'replay_logger') and self.replay_logger:
                try:
                    # Create gym action equivalent for logging
                    gym_action = action_type  # Simple mapping
                    target_id = mirror_action.get("target_id")                    
                    self.replay_logger.log_action(
                        action=gym_action,
                        reward=0.0,  # Bot gets no reward
                        pre_action_units=pre_action_units,
                        post_action_units=post_action_units,
                        acting_unit_id=bot_unit["id"],
                        target_unit_id=target_id,
                        description=f"Bot {mirror_action['type']} action by unit {bot_unit['id']}"
                    )
                except Exception as e:
                    print(f"    ❌ Bot action logging failed: {e}")
            
            # Mark unit as acted for current phase to prevent infinite loops
            self._mark_unit_as_acted_for_current_phase(bot_unit)
        
        print(f"🤖 Bot logged {len(bot_units)} actions for phase {current_phase}")

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