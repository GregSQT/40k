#!/usr/bin/env python3
"""
w40k_core.py - Slim W40K Game Engine Core
Delegates to specialized modules, orchestrates game flow.
"""

import os
import torch
import json
import random
import gymnasium as gym
import numpy as np
from typing import Dict, List, Tuple, Set, Optional, Any

# Import shared utilities
from engine.combat_utils import calculate_hex_distance

# Phase handlers (existing - keep these)
from engine.phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers

# Import shared utilities FIRST (no circular dependencies)
from engine.game_utils import get_unit_by_id

# Import NEW extracted modules
from engine.observation_builder import ObservationBuilder
from engine.action_decoder import ActionDecoder
from engine.reward_calculator import RewardCalculator
from engine.game_state import GameStateManager
from engine.pve_controller import PvEController


class W40KEngine(gym.Env):
    """
    Slim W40K game engine - delegates to specialized modules.
    Core responsibilities: Gym interface, phase orchestration, episode management.
    """
    
    # ============================================================================
    # INITIALIZATION (KEEP FROM LINES 42-214)
    # ============================================================================
    
    def __init__(self, config=None, rewards_config=None, training_config_name=None, 
                controlled_agent=None, active_agents=None, scenario_file=None, 
                unit_registry=None, quiet=True, gym_training_mode=False, **kwargs):
        """Initialize W40K engine with AI_TURN.md compliance - training system compatible."""
        
        # Store gym training mode for handler access
        self.gym_training_mode = gym_training_mode
        
        # Handle both new engine format (single config) and old training system format
        if config is None:
            # Build config from training system parameters
            from config_loader import get_config_loader
            config_loader = get_config_loader()
            
            # Load agent-specific rewards configuration
            if not controlled_agent:
                raise ValueError("controlled_agent parameter required when config is None - cannot load agent-specific rewards")

            # CRITICAL FIX: Extract base agent key for file loading (strip phase suffix)
            # controlled_agent may be "Agent_phase1", but file is at "config/agents/Agent/Agent_rewards_config.json"
            base_agent_key = controlled_agent
            for phase_suffix in ['_phase1', '_phase2', '_phase3', '_phase4']:
                if controlled_agent.endswith(phase_suffix):
                    base_agent_key = controlled_agent[:-len(phase_suffix)]
                    break

            self.rewards_config = config_loader.load_agent_rewards_config(base_agent_key)
            if not self.rewards_config:
                raise RuntimeError(f"Failed to load rewards configuration for agent: {base_agent_key}")

            # Store the agent-specific config name for reference
            self.rewards_config_name = rewards_config
            if not self.rewards_config_name:
                raise ValueError("rewards_config parameter required - specifies which reward section to use")

            # Load agent-specific training configuration for turn limits
            if not training_config_name:
                raise ValueError("training_config_name parameter required when config is None - cannot load agent-specific training config")

            self.training_config = config_loader.load_agent_training_config(base_agent_key, training_config_name)
            if not self.training_config:
                raise RuntimeError(f"Failed to load training configuration for agent {controlled_agent}, phase {training_config_name}")
            
            # Load base configuration
            board_config = config_loader.get_board_config()

            # CRITICAL FIX: Initialize PvE mode BEFORE config creation
            # Training mode: pve_mode=False (SelfPlayWrapper handles Player 1)
            # PvE mode in API: pve_mode=True (load AI model for Player 1)
            pve_mode_value = False  # Training uses SelfPlayWrapper, not pve_mode

            # Extract observation_params for module access - NO FALLBACKS
            if "observation_params" not in self.training_config:
                raise KeyError(f"observation_params missing from {controlled_agent} training config phase {training_config_name}")
            obs_params = self.training_config["observation_params"]

            # Load scenario data (units + optional terrain)
            scenario_result = self._load_units_from_scenario(scenario_file, unit_registry)
            scenario_units = scenario_result["units"]

            # Determine wall_hexes: use scenario if provided, otherwise fallback to board config
            if scenario_result.get("wall_hexes") is not None:
                scenario_wall_hexes = scenario_result["wall_hexes"]
            else:
                # Fallback to board config
                if "default" in board_config:
                    scenario_wall_hexes = board_config["default"].get("wall_hexes", [])
                else:
                    scenario_wall_hexes = board_config.get("wall_hexes", [])

            # Determine objective_hexes: use scenario if provided, otherwise fallback to board config
            if scenario_result.get("objective_hexes") is not None:
                scenario_objective_hexes = scenario_result["objective_hexes"]
            else:
                # Fallback to board config
                if "default" in board_config:
                    scenario_objective_hexes = board_config["default"].get("objective_hexes", [])
                else:
                    scenario_objective_hexes = board_config.get("objective_hexes", [])

            # Store scenario terrain for game_state initialization
            self._scenario_wall_hexes = scenario_wall_hexes
            self._scenario_objective_hexes = scenario_objective_hexes

            # Extract scenario name from file path for logging
            scenario_name = scenario_file if scenario_file else "Unknown Scenario"
            if scenario_name and "/" in scenario_name:
                scenario_name = scenario_name.split("/")[-1].replace(".json", "")
            elif scenario_name and "\\" in scenario_name:
                scenario_name = scenario_name.split("\\")[-1].replace(".json", "")

            self.config = {
                "board": board_config,
                "units": scenario_units,
                "name": scenario_name,  # Store scenario name for logging
                "rewards_config_name": self.rewards_config_name,
                "training_config_name": training_config_name,
                "training_config": self.training_config,
                "observation_params": obs_params,  # ✓ CHANGE 1: Add to config root for ObservationBuilder
                "controlled_agent": controlled_agent,
                "active_agents": active_agents,
                "quiet": quiet,
                "gym_training_mode": gym_training_mode,  # CRITICAL: Pass flag to handlers
                "pve_mode": pve_mode_value,  # CRITICAL: Add PvE mode for handler detection
                "controlled_player": 0  # FIXED: Agent controls player 0 (matches scenario setup)
            }
        else:
            # Use provided config directly and add gym_training_mode
            self.config = config.copy()
            self.config["gym_training_mode"] = gym_training_mode
            # CRITICAL: Ensure pve_mode is in config for handler delegation
            if "pve_mode" not in self.config:
                self.config["pve_mode"] = config.get("pve_mode", False)
            # CHANGE 5: Ensure controlled_player is set
            if "controlled_player" not in self.config:
                self.config["controlled_player"] = 0  # FIXED: Agent controls player 0 (matches scenario setup)

            # CRITICAL: Extract rewards_config from config dict for module initialization
            self.rewards_config = config.get("rewards_config", {})

            # No scenario loaded - use board config for terrain (set to None for fallback logic)
            self._scenario_wall_hexes = None
            self._scenario_objective_hexes = None
        
        # Store training system compatibility parameters
        self.quiet = quiet
        self.unit_registry = unit_registry
        self.step_logger = None  # Will be set by training system if enabled
        
        # Detect training context to suppress debug logs
        self.is_training = training_config_name in ["debug", "default", "conservative", "aggressive"]
        
        # PvE mode configuration
        # AI_TURN.md COMPLIANCE: Direct access with validation
        if isinstance(config, dict) and "pve_mode" in config:
            self.is_pve_mode = config["pve_mode"]
        else:
            self.is_pve_mode = False
        
        # CRITICAL FIX: Update config with actual PvE mode value
        self.config["pve_mode"] = self.is_pve_mode
        self._ai_model = None
        
        # CRITICAL: Ensure PvE mode is properly propagated to handlers
        if self.is_pve_mode:
            self.config["pve_mode"] = True
        
        # CRITICAL: Initialize game_state FIRST before any other operations
        self.game_state = {
            # Core game state
            "units": [],
            "current_player": 0,
            "gym_training_mode": self.config["gym_training_mode"],  # Embed for handler access
            "training_config_name": training_config_name if training_config_name else "",  # NEW: For debug mode detection
            "phase": "move",
            "turn": 1,
            "episode_steps": 0,
            "game_over": False,
            "winner": None,
            
            # AI_TURN.md required tracking sets
            "units_moved": set(),
            "units_fled": set(),
            "units_shot": set(),
            "units_charged": set(),
            "units_attacked": set(),
            
            # Phase management
            "move_activation_pool": [],
            "shoot_activation_pool": [],
            "charge_activation_pool": [],
            "charging_activation_pool": [],
            "active_alternating_activation_pool": [],
            "non_active_alternating_activation_pool": [],
            
            # AI_MOVE.md movement preview state
            "valid_move_destinations_pool": [],
            "preview_hexes": [],
            "active_movement_unit": None,
            
            # Fight state
            "fight_subphase": None,
            "charge_range_rolls": {},
            
            # Metrics tracking
            "action_logs": [],  # CRITICAL: For metrics collection - tracks all actions per episode

            # PERFORMANCE: Hex-coordinate LoS cache (walls static within episode)
            "hex_los_cache": {},

            # CHANGE 11: Add rewards_configs (plural) to game_state for handler access
            "rewards_configs": {
                self.config.get("controlled_agent", "default"): self.rewards_config
            },
            "config": self.config,
            
            # Board state - handle both config formats
            "board_cols": self.config["board"]["default"]["cols"] if "default" in self.config["board"] else self.config["board"]["cols"],
            "board_rows": self.config["board"]["default"]["rows"] if "default" in self.config["board"] else self.config["board"]["rows"],
            # Use scenario terrain if loaded, otherwise fallback to board config
            "wall_hexes": set(map(tuple, self._scenario_wall_hexes)) if self._scenario_wall_hexes is not None else set(map(tuple, self.config["board"]["default"]["wall_hexes"] if "default" in self.config["board"] else self.config["board"].get("wall_hexes", []))),
            "objective_hexes": set(map(tuple, self._scenario_objective_hexes)) if self._scenario_objective_hexes is not None else set(map(tuple, self.config["board"]["default"].get("objective_hexes", []) if "default" in self.config["board"] else self.config["board"].get("objective_hexes", [])))
        }

        # CRITICAL: Instantiate all module managers BEFORE using them
        self.state_manager = GameStateManager(self.config, self.unit_registry)
        self.obs_builder = ObservationBuilder(self.config)
        self.action_decoder = ActionDecoder(self.config)
        # Use rewards_config from config dict if not already loaded
        rewards_cfg = getattr(self, 'rewards_config', self.config.get("rewards_config", {}))
        self.reward_calculator = RewardCalculator(self.config, self.rewards_config, self.unit_registry)
        self.pve_controller = PvEController(self.config)
        
        # Initialize units from config AFTER game_state exists
        self._initialize_units()
        
        # CRITICAL: Initialize Gym spaces BEFORE any other operations
        # Gym interface properties - dynamic action space based on phase
        self.action_space = gym.spaces.Discrete(12)  # Expanded: 4 move + 5 shoot + charge + fight + wait
        self._current_valid_actions = list(range(12))  # Will be masked dynamically
        
        # Observation space: Asymmetric egocentric perception with R=25 radius
        # 295 floats = 10 global + 8 unit + 32 terrain + 72 allies + 138 enemies + 35 targets
        # Asymmetric design: More complete information about enemies than allies
        # Covers MOVE(12) + MAX_CHARGE(12) + ENEMY_OFFSET(1) = 25 hex strategic reach
        obs_size = 295  # Asymmetric observation - rich enemy intel for tactical decisions
        
        # Load perception parameters from training config if available
        if hasattr(self, 'training_config') and self.training_config:
            obs_params = self.training_config.get("observation_params", {})
            self.perception_radius = obs_params.get("perception_radius", 25)
            self.max_nearby_units = obs_params.get("max_nearby_units", 10)
            self.max_valid_targets = obs_params.get("max_valid_targets", 5)
        else:
            self.perception_radius = 25
            self.max_nearby_units = 10
            self.max_valid_targets = 5
        
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
        )
        
        # Initialize position caching for movement_direction feature
        self.last_unit_positions = {}  # {unit_id: (col, row)}
        
        # Episode-level metrics accumulation for MetricsCollectionCallback
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        self.episode_tactical_data = {
            'shots_fired': 0,
            'hits': 0,
            'damage_dealt': 0,
            'damage_received': 0,
            'units_killed': 0,
            'units_lost': 0,
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_enemies': 0
        }
        
        # Load AI model for PvE mode
        if self.is_pve_mode:
            self.pve_controller.load_ai_model_for_pve(self.game_state, self)
        
        # ✓ CHANGE 2: Removed duplicate module instantiations (already done at line 181-187)
        
        if self.is_pve_mode:
            self.pve_controller = PvEController(self.config, self.unit_registry)
            self.pve_controller.load_ai_model_for_pve(self.game_state, self)
        # ==================================================    
    
    # ============================================================================
    # GYM INTERFACE - KEEP THESE CORE METHODS
    # ============================================================================
    
    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[np.ndarray, Dict]:
        """Reset game state for new episode - gym.Env interface."""
        
        # Call parent reset for gym compliance
        super().reset(seed=seed)
        
        if seed is not None:
            random.seed(seed)
        
        # Reset game state
        self.game_state.update({
            "current_player": 0,
            "phase": "move",
            "turn": 1,
            "episode_steps": 0,
            "game_over": False,
            "winner": None,
            "units_moved": set(),
            "units_fled": set(),
            "units_shot": set(),
            "units_charged": set(),
            "units_attacked": set(),
            "move_activation_pool": [],
            "fight_subphase": None,
            "charge_range_rolls": {},
            "action_logs": [],  # CRITICAL: Reset action logs for new episode metrics
            "gym_training_mode": self.gym_training_mode,  # ADDED: For handler access
            "hex_los_cache": {}  # PERFORMANCE: Clear hex-coordinate LoS cache for new episode
        })
        
        # Reset unit health and positions to original scenario values
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field during reset")
        unit_configs = self.config["units"]
        for unit in self.game_state["units"]:
            unit["HP_CUR"] = unit["HP_MAX"]
            
            # CRITICAL: Reset shooting state per episode
            unit["SHOOT_LEFT"] = unit["RNG_NB"]
            unit["ATTACK_LEFT"] = unit["CC_NB"]
            
            # Find original position from config - match by string conversion
            unit_id_str = str(unit["id"])
            original_config = None
            for cfg in unit_configs:
                if str(cfg["id"]) == unit_id_str:
                    original_config = cfg
                    break
            
            if original_config:
                unit["col"] = original_config["col"]
                unit["row"] = original_config["row"]
            else:
                raise ValueError(f"Unit {unit['id']} not found in scenario config during reset")
        
        # Initialize movement phase for game start using handler delegation
        movement_handlers.movement_phase_start(self.game_state)
        
        # Reset episode-level metric accumulators
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        self.episode_tactical_data = {
            'shots_fired': 0,
            'hits': 0,
            'damage_dealt': 0,
            'damage_received': 0,
            'units_killed': 0,
            'units_lost': 0,
            'valid_actions': 0,
            'invalid_actions': 0,
            'wait_actions': 0,
            'total_enemies': 0
        }
        
        # Log episode start with all unit positions and walls
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            scenario_name = self.config.get("name", "Unknown Scenario")
            # Use _scenario_wall_hexes (set during scenario loading) - convert to step_logger format
            raw_walls = self._scenario_wall_hexes if self._scenario_wall_hexes is not None else []
            walls = [{"col": w[0], "row": w[1]} for w in raw_walls] if raw_walls else []
            self.step_logger.log_episode_start(self.game_state["units"], scenario_name, walls=walls)
        
        observation = self.obs_builder.build_observation(self.game_state)
        info = {"phase": self.game_state["phase"]}
        
        return observation, info    
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Execute gym action with built-in step counting - gym.Env interface.
        """
        # CRITICAL: Check turn limit BEFORE processing any action
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and self.game_state["turn"] > max_turns:
                # Turn limit exceeded - return terminated episode immediately
                observation = self.obs_builder.build_observation(self.game_state)
                info = {"turn_limit_exceeded": True, "winner": self._determine_winner()}
                return observation, 0.0, True, False, info
        
        # Check for game termination before action
        self.game_state["game_over"] = self._check_game_over()
        
        # Convert gym integer action to semantic action
        semantic_action = self.action_decoder.convert_gym_action(action, self.game_state)
        
        # CRITICAL: Capture phase, player, and positions BEFORE action execution for accurate logging
        pre_action_phase = self.game_state["phase"]
        pre_action_player = self.game_state["current_player"]
        pre_action_positions = {}
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            # AI_TURN.md COMPLIANCE: Direct field access for semantic actions
            if "unitId" not in semantic_action:
                unit_id = None
            else:
                unit_id = semantic_action["unitId"]
            if unit_id:
                pre_unit = self._get_unit_by_id(str(unit_id))
                if pre_unit:
                    pre_action_positions[str(unit_id)] = (pre_unit["col"], pre_unit["row"])
        
        # Process semantic action with AI_TURN.md compliance
        action_result = self._process_semantic_action(semantic_action)
        if isinstance(action_result, tuple) and len(action_result) == 2:
            success, result = action_result
        else:
            success, result = True, action_result
        
        # BUILT-IN STEP COUNTING - AFTER validation, only for successful actions
        if success:
            self.game_state["episode_steps"] += 1

            # NEW: AI_TURN.md compliance tracking - verify ONE unit per step
            compliance_data = {
                'units_activated_this_step': 1,  # Should always be 1 per AI_TURN.md
                'phase_end_reason': 'unknown',
                'duplicate_activation_attempts': 0,
                'pool_corruption_detected': 0
            }

            # Validate sequential activation (ONE unit per step)
            if hasattr(self, '_units_activated_this_step'):
                if self._units_activated_this_step > 1:
                    compliance_data['units_activated_this_step'] = self._units_activated_this_step

            # Store compliance data for metrics callback
            self.game_state['last_compliance_data'] = compliance_data

            # Reset per-step counter
            self._units_activated_this_step = 0
        
        if isinstance(action_result, tuple) and len(action_result) == 2:
            success, result = action_result
        else:
            success, result = True, action_result
        
        # Log action ONLY if it's a real agent action with valid unit
        if (self.step_logger and self.step_logger.enabled and success):
           
            # CHANGE 1: Read action from result dict FIRST (handlers populate actual executed action)
            # Diagnostic proved: result.get('action')='move' but semantic_action.get('action')='activate_unit'
            action_type = result.get("action") if isinstance(result, dict) else None
            if not action_type:
                # Fall back to semantic_action only if result has no action
                action_type = semantic_action.get("action") if isinstance(semantic_action, dict) else None
            
            # CHANGE 2: Get unitId from result first (handlers populate this field)
            unit_id = result.get("unitId") if isinstance(result, dict) else None
            if not unit_id:
                unit_id = semantic_action.get("unitId") if isinstance(semantic_action, dict) else None
           
            # CHANGE 3: STRICT validation - only log if action_type in StepLogger whitelist
            # Prevents "Unknown action_type 'activate_unit'" errors
            valid_action_types = ["move", "shoot", "charge", "combat", "wait"]
            if (action_type in valid_action_types and
                unit_id and unit_id != "none" and unit_id != "SYSTEM"):
               
                # Get unit coordinates AFTER action execution using semantic action unitId
                updated_unit = self._get_unit_by_id(str(unit_id)) if unit_id else None
                if updated_unit:
                    # Use PRE-ACTION position from captured data for movement logging
                    if str(unit_id) in pre_action_positions and action_type == "move":
                        orig_col, orig_row = pre_action_positions[str(unit_id)]
                        action_details = {
                            "current_turn": self.game_state["turn"],
                            "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']}, {updated_unit['row']})",
                            "semantic_action": semantic_action,
                            "start_pos": (orig_col, orig_row),
                            "end_pos": (updated_unit["col"], updated_unit["row"])
                        }
                    else:
                        # Build complete action details for step logger with CURRENT coordinates
                        action_details = {
                            "current_turn": self.game_state["turn"],
                            "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']}, {updated_unit['row']})",
                            "semantic_action": semantic_action
                        }
                
                    # Add specific data for different action types
                    if action_type == "move":  # CHANGE 5: Use action_type variable instead of semantic_action
                        # Use semantic action coordinates for accurate logging
                        start_pos = pre_action_positions.get(str(unit_id), (updated_unit["col"], updated_unit["row"]))
                        # CRITICAL: Use semantic action destination, not unit's current position
                        dest_col = semantic_action.get("destCol", updated_unit["col"])
                        dest_row = semantic_action.get("destRow", updated_unit["row"])
                        end_pos = (dest_col, dest_row)
                        action_details.update({
                            "start_pos": start_pos,
                            "end_pos": end_pos,
                            "col": dest_col,  # Use semantic action destination
                            "row": dest_row   # Use semantic action destination
                        })
                    elif action_type == "shoot":  # CHANGE 6: Use action_type variable instead of semantic_action
                        # Add shooting-specific data with correct field names
                        action_details.update({
                            "target_id": semantic_action.get("targetId"),  # StepLogger expects target_id
                            "hit_roll": 0,  # Will be filled by actual shooting execution
                            "wound_roll": 0,
                            "save_roll": 0,
                            "damage_dealt": 0,
                            "hit_result": "PENDING",
                            "wound_result": "PENDING", 
                            "save_result": "PENDING",
                            "hit_target": 4,  # Default values
                            "wound_target": 4,
                            "save_target": 4
                        })
                        
                        # CRITICAL FIX: Populate with actual attack results from game_state
                        if "last_attack_result" in self.game_state and self.game_state["last_attack_result"]:
                            attack_result = self.game_state["last_attack_result"]
                            action_details.update({
                                "hit_roll": attack_result.get("hit_roll", 0),
                                "wound_roll": attack_result.get("wound_roll", 0),
                                "save_roll": attack_result.get("save_roll", 0),
                                "damage_dealt": attack_result.get("damage", 0),
                                "hit_result": "HIT" if attack_result.get("hit_success") else "MISS",
                                "wound_result": "WOUND" if attack_result.get("wound_success") else "FAIL",
                                "save_result": "SAVED" if attack_result.get("save_success") else "FAIL",
                                "hit_target": attack_result.get("hit_target", 4),
                                "wound_target": attack_result.get("wound_target", 4),
                                "save_target": attack_result.get("save_target", 4)
                            })
                    
                    # Use pre-captured phase for accurate logging (phase may have changed during action)
                    # Don't use _get_action_phase_for_logging() as it reads current phase which may be wrong
                    
                    # CHANGE 37: For shoot actions, read reward from the action_log entry just created
                    if semantic_action.get("action") == "shoot":
                        # Find the most recent shoot log for this unit
                        action_logs = self.game_state.get("action_logs", [])
                        step_reward = 0.0
                        for log in reversed(action_logs):
                            if (log.get("type") == "shoot" and 
                                log.get("shooterId") == str(unit_id) and 
                                "reward" in log):
                                step_reward = log["reward"]
                                break
                        action_details["reward"] = step_reward
                    else:
                        # For non-shoot actions, calculate normally
                        step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
                        action_details["reward"] = step_reward
                    
                    self.step_logger.log_action(
                        unit_id=updated_unit["id"],
                        action_type=action_type,  # CHANGE 4: Use validated action_type variable from line 406
                        phase=pre_action_phase,  # Use phase captured before action executed
                        player=pre_action_player,  # Use player captured before action executed
                        success=success,
                        step_increment=True,
                        action_details=action_details
                    )
        
        # Convert to gym format
        observation = self.obs_builder.build_observation(self.game_state)
        # Calculate reward (independent of step_logger)
        reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
        terminated = self.game_state["game_over"]
        truncated = False
        info = result.copy() if isinstance(result, dict) else {}
        info["success"] = success
        
        # Accumulate episode-level metrics
        self.episode_reward_accumulator += reward
        self.episode_length_accumulator += 1
        
        # Track action validity
        if success:
            self.episode_tactical_data['valid_actions'] += 1
        else:
            self.episode_tactical_data['invalid_actions'] += 1
        
        # Add winner info when game ends
        if terminated:
            winner = self._determine_winner()
            info["winner"] = winner
            
            # CRITICAL: Populate info["episode"] for Stable-Baselines3 MetricsCollectionCallback
            info["episode"] = {
                "r": float(self.episode_reward_accumulator),
                "l": int(self.episode_length_accumulator),
                "t": int(self.episode_length_accumulator),
            }
            
            # Calculate units killed/lost
            # Controlled agent is always player 0 in training
            controlled_player = 0
            
            surviving_ally_units = sum(1 for u in self.game_state["units"] 
                                      if u["player"] == controlled_player and u["HP_CUR"] > 0)
            surviving_enemy_units = sum(1 for u in self.game_state["units"] 
                                       if u["player"] != controlled_player and u["HP_CUR"] > 0)
            
            total_ally_units = sum(1 for u in self.game_state["units"] 
                                  if u["player"] == controlled_player)
            total_enemy_units = sum(1 for u in self.game_state["units"] 
                                   if u["player"] != controlled_player)
            
            self.episode_tactical_data['units_lost'] = total_ally_units - surviving_ally_units
            self.episode_tactical_data['units_killed'] = total_enemy_units - surviving_enemy_units
            self.episode_tactical_data['total_enemies'] = total_enemy_units
            
            # Add tactical data to info
            info["tactical_data"] = self.episode_tactical_data.copy()
            
            # Log episode end with final stats
            if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                self.step_logger.log_episode_end(self.game_state["episode_steps"], winner)
        else:
            info["winner"] = None
        
        # CRITICAL: Add action_logs to info dict so metrics can access it
        # This must happen BEFORE reset clears action_logs
        info["action_logs"] = self.game_state.get("action_logs", []).copy()
        
        # Update position cache for movement_direction feature
        for unit in self.game_state["units"]:
            if "id" not in unit:
                raise KeyError(f"Unit missing required 'id' field: {unit}")
            if "col" not in unit or "row" not in unit:
                raise KeyError(f"Unit missing required position fields: {unit}")
            unit_id = str(unit["id"])
            self.last_unit_positions[unit_id] = (unit["col"], unit["row"])
            
        return observation, reward, terminated, truncated, info
    
    
    # ============================================================================
    # ACTION EXECUTION - KEEP THESE (They delegate to phase_handlers)
    # ============================================================================
    
    def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute semantic actions directly from frontend.
        Public interface for human player actions.
        """
        return self._process_semantic_action(action)
    
    
    def execute_ai_turn(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute AI turn using same decision tree as humans.
        AI_TURN.md compliant - only decision-making logic differs from humans.
        """
        # Validate PvE mode and AI player turn
        if not self.is_pve_mode:
            return False, {"error": "not_pve_mode"}
        
        current_player = self.game_state["current_player"]
        if current_player != 1:  # AI is player 1
            return False, {"error": "not_ai_player_turn", "current_player": current_player}
        
        current_phase = self.game_state["phase"]
        
        # Check AI model availability
        if not hasattr(self, '_ai_model') or not self._ai_model:
            return False, {"error": "ai_model_not_loaded"}
        
        # Make AI decision - replaces human click
        try:
            ai_semantic_action = self.pve_controller.make_ai_decision(self.game_state, self)
            
            # Execute through SAME path as humans
            return self._process_semantic_action(ai_semantic_action)
            
        except Exception as e:
            return False, {"error": "ai_decision_failed", "message": str(e)}
    
    
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action with detailed execution debugging.
        """
        current_phase = self.game_state["phase"]
                
        # Route to phase handlers with detailed logging
        if current_phase == "move":
            success, result = self._process_movement_phase(action)
        elif current_phase == "shoot":
            success, result = self._process_shooting_phase(action)
        elif current_phase == "charge":
            success, result = self._process_charge_phase(action)
        elif current_phase == "fight":
            success, result = self._process_fight_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}

        # AI_TURN.md: Auto-advance to next phase when current phase completes
        # Loop to handle cascading empty phases (e.g., charge → fight → move if all empty)
        max_cascade = 10  # Prevent infinite loops
        cascade_count = 0
        while success and result.get("phase_complete") and result.get("next_phase") and cascade_count < max_cascade:
            next_phase = result["next_phase"]
            cascade_count += 1

            if "console_logs" not in self.game_state:
                self.game_state["console_logs"] = []
            self.game_state["console_logs"].append(f"🔄 PHASE TRANSITION: {current_phase} → {next_phase} (cascade #{cascade_count})")

            # Initialize next phase using phase handlers
            phase_init_result = None
            if next_phase == "shoot":
                phase_init_result = shooting_handlers.shooting_phase_start(self.game_state)
            elif next_phase == "charge":
                phase_init_result = charge_handlers.charge_phase_start(self.game_state)
            elif next_phase == "fight":
                phase_init_result = fight_handlers.fight_phase_start(self.game_state)
            elif next_phase == "move":
                phase_init_result = movement_handlers.movement_phase_start(self.game_state)

            self.game_state["console_logs"].append(f"🔄 PHASE NOW: {self.game_state.get('phase', 'UNKNOWN')}")

            # If phase_start returns phase_complete, cascade to next phase
            if phase_init_result and phase_init_result.get("phase_complete") and phase_init_result.get("next_phase"):
                result = phase_init_result  # Update result for next iteration
            else:
                break  # Phase has eligible units, stop cascading

        return success, result
    
    
    # ============================================================================
    # PHASE PROCESSING - KEEP THESE (They delegate to phase_handlers)
    # ============================================================================
    
    def _process_movement_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_MOVE.md EXACT: Pure engine orchestration - handler manages everything"""
        
        # Get current unit for handler (handler expects unit parameter)
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)
        
        # **FULL DELEGATION**: movement_handlers.execute_action(game_state, unit, action, config)
        success, result = movement_handlers.execute_action(self.game_state, current_unit, action, self.config)
        
        # DEBUG: Check if unit position actually changed
        if success and action.get("action") == "move":
            unit_id = action.get("unitId")
            if unit_id:
                unit = self._get_unit_by_id(unit_id)
                if unit:
                    expected_col = action.get("destCol", "unknown")
                    expected_row = action.get("destRow", "unknown") 
                    if expected_col == unit["col"] and expected_row == unit["row"]:
                        pass
        
        # CRITICAL FIX: Handle failed actions to prevent infinite loops
        if not success and result.get("error") == "invalid_destination":
            skip_unit = self._get_unit_by_id(action.get("unitId")) if action.get("unitId") else None
            skip_result = movement_handlers.execute_action(self.game_state, skip_unit, {"action": "skip", "unitId": action.get("unitId")}, self.config)
            if isinstance(skip_result, tuple):
                success, result = skip_result
            else:
                success, result = True, skip_result
        
        # Check response for phase_complete flag
        if result.get("phase_complete"):
            self._movement_phase_initialized = False
            self._shooting_phase_init()
            result["phase_transition"] = True
            result["next_phase"] = "shoot"
        
        return success, result
    
    
    def _process_shooting_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        AI_TURN.md EXACT: Pure delegation - handler manages complete phase lifecycle
        """
        # Pure delegation - handler manages initialization, player progression, everything
        handler_response = shooting_handlers.execute_action(self.game_state, None, action, self.config)
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
        else:
            # Handler returned non-tuple or wrong tuple length
            success = True
            result = handler_response if isinstance(handler_response, dict) else {"error": "invalid_handler_response"}
        
        # Handle phase transitions signaled by handler
        if result.get("phase_complete") or result.get("phase_transition"):
            next_phase = result.get("next_phase")
            if next_phase == "move":
                self._movement_phase_init()
        return success, result
    
    
    def _process_charge_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_TURN.md EXACT: Pure delegation - handler manages complete charge phase."""
        # Get current unit for handler
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        # Full delegation to charge_handlers
        handler_response = charge_handlers.execute_action(self.game_state, current_unit, action, self.config)
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
            return success, result
        else:
            return True, handler_response

    def _process_fight_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """AI_TURN.md EXACT: Pure delegation - handler manages complete fight phase."""
        # Get current unit for handler
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)

        # Full delegation to fight_handlers
        handler_response = fight_handlers.execute_action(self.game_state, current_unit, action, self.config)
        if isinstance(handler_response, tuple) and len(handler_response) == 2:
            success, result = handler_response
            return success, result
        else:
            return True, handler_response
    
    # ============================================================================
    # PHASE INITIALIZATION - KEEP THESE (Handler delegation)
    # ============================================================================
    
    def _movement_phase_init(self):
        """Initialize movement phase using AI_MOVE.md delegation."""
        # AI_MOVE.md: Handler manages phase initialization
        movement_handlers.movement_phase_start(self.game_state)
    
    def _shooting_phase_init(self):
        """AI_SHOOT.md EXACT: Pure delegation to handler"""
        # Handler manages everything including phase setting and pool building
        result = shooting_handlers.shooting_phase_start(self.game_state)
    
    
    def _charge_phase_init(self):
        """Initialize charge phase and build activation pool."""
        self.game_state["phase"] = "charge"
        # TODO: Build charge activation pool
    
    
    def _fight_phase_init(self):
        """Initialize fight phase and build activation pool."""
        self.game_state["phase"] = "fight"
        # TODO: Build fight activation pool
        # If no units eligible for shooting, advance immediately to charge
        if not self.game_state["shoot_activation_pool"]:
            self._charge_phase_init()
    
    
    def _advance_to_next_player(self):
        """Advance to next player per AI_TURN.md turn progression."""
        # Player switching logic
        if self.game_state["current_player"] == 0:
            self.game_state["current_player"] = 1
        elif self.game_state["current_player"] == 1:
            self.game_state["current_player"] = 0
            self.game_state["turn"] += 1
            
            # Check turn limit immediately after P1 completes turn
            if hasattr(self, 'training_config'):
                max_turns = self.training_config.get("max_turns_per_episode")
                if max_turns and self.game_state["turn"] > max_turns:
                    # Turn limit reached - mark game over and stop phase progression
                    self.game_state["game_over"] = True
                    return
        
        # Phase progression logic - simplified to move -> shoot -> move
        if self.game_state["phase"] == "move":
            self._shooting_phase_init()
        elif self.game_state["phase"] == "shoot":
            self._movement_phase_init()
        elif self.game_state["phase"] == "charge":
            self._movement_phase_init()
        elif self.game_state["phase"] == "fight":
            self._movement_phase_init()
    
    
    def _tracking_cleanup(self):
        """Clear tracking sets at the VERY BEGINNING of movement phase."""
        self.game_state["units_moved"] = set()
        self.game_state["units_fled"] = set()
        self.game_state["units_shot"] = set()
        self.game_state["units_charged"] = set()
        self.game_state["units_attacked"] = set()
        self.game_state["move_activation_pool"] = []
    
    
    # ============================================================================
    # HELPER METHODS - KEEP THESE SIMPLE ONES
    # ============================================================================
    
    def _get_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state - delegates to module utility."""
        return get_unit_by_id(unit_id, self.game_state)
    
    
    def _check_game_over(self) -> bool:
        """Check if game is over - unit elimination OR turn limit reached."""
        # Check turn limit first
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and self.game_state["turn"] > max_turns:
                return True
        
        # Check unit elimination
        living_units_by_player = {}
        
        for unit in self.game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # Game is over if any player has no living units
        return len(living_units_by_player) <= 1
    
    
    def _determine_winner(self) -> Optional[int]:
        """Determine winner based on remaining living units or turn limit. Returns -1 for draw."""
        living_units_by_player = {}
        
        for unit in self.game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # DEBUG: Log winner determination details
        current_turn = self.game_state["turn"]
        max_turns = self.training_config.get("max_turns_per_episode") if hasattr(self, 'training_config') else None
        
        if not self.quiet:
            print(f"\n🔍 WINNER DETERMINATION DEBUG:")
            print(f"   Current turn: {current_turn}")
            print(f"   Max turns: {max_turns}")
            print(f"   Game over: {self.game_state.get('game_over')}")
            print(f"   Living units: {living_units_by_player}")
            print(f"   Has training_config: {hasattr(self, 'training_config')}")
        
        # PRIORITY CHECK: If game_over is True and we're at turn limit, determine winner
        if self.game_state.get("game_over"):
            if hasattr(self, 'training_config'):
                max_turns = self.training_config.get("max_turns_per_episode")
                if max_turns and self.game_state["turn"] == max_turns:
                    # Game ended at exactly turn limit
                    living_players = list(living_units_by_player.keys())
                    if len(living_players) == 2:
                        # Both players alive at turn limit - DRAW
                        if not self.quiet:
                            print(f"   → Draw: Turn limit reached with both players alive (P0: {living_units_by_player.get(0, 0)} units, P1: {living_units_by_player.get(1, 0)} units)")
                        return -1
                    elif len(living_players) == 1:
                        # One player eliminated at turn limit
                        if not self.quiet:
                            print(f"   → Winner: Player {living_players[0]} (elimination at turn limit)")
                        return living_players[0]
                    else:
                        # No survivors at turn limit
                        if not self.quiet:
                            print(f"   → Draw: No survivors at turn limit")
                        return -1
        
        # Normal elimination rules
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            if not self.quiet:
                print(f"   → Winner: Player {living_players[0]} (elimination)")
            return living_players[0]
        elif len(living_players) == 0:
            if not self.quiet:
                print(f"   → Draw: No survivors - returning -1")
            return -1  # Draw/no winner
        else:
            if not self.quiet:
                print(f"   → Game ongoing: {len(living_players)} players with units")
            return None  # Game still ongoing
    
    
    def _get_action_phase_for_logging(self, action_type: str) -> str:
        """Map action types to their logical phases for step logging."""
        action_phase_map = {
            "move": "move",
            "shoot": "shoot", 
            "charge": "charge",
            "combat": "fight",
            "fight": "fight",
            "wait": "move",  # CHANGE 10: Wait actions happen during move phase
            "skip": self.game_state["phase"]  # Use current phase for skip (legacy)
        }
        return action_phase_map.get(action_type, self.game_state["phase"])
    
    
    def validate_compliance(self) -> List[str]:
        """Validate AI_TURN.md compliance - returns list of violations."""
        violations = []
        
        # Check single source of truth
        if not hasattr(self, 'game_state'):
            violations.append("Missing single game_state object")
        
        # Check UPPERCASE fields
        for unit in self.game_state["units"]:
            if "HP_CUR" not in unit or "RNG_ATK" not in unit:
                violations.append(f"Unit {unit['id']} missing UPPERCASE fields")
        
        # Check tracking sets are sets
        tracking_fields = ["units_moved", "units_fled", "units_shot", "units_charged", "units_attacked"]
        for field in tracking_fields:
            if not isinstance(self.game_state[field], set):
                violations.append(f"{field} must be set type, got {type(self.game_state[field])}")
        
        return violations
    
    
    # ============================================================================
    # DELEGATED METHODS - NOW CALL MODULE METHODS
    # ============================================================================
    
    def get_action_mask(self) -> np.ndarray:
        """Get valid action mask - delegates to action_decoder."""
        return self.action_decoder.get_action_mask(self.game_state)
    
    
    def _build_observation(self) -> np.ndarray:
        """Build observation - delegates to observation_builder."""
        return self.obs_builder.build_observation(self.game_state)
    
    
    def _calculate_reward(self, success: bool, result: Dict[str, Any]) -> float:
        """Calculate reward - delegates to reward_calculator."""
        return self.reward_calculator.calculate_reward(success, result, self.game_state)
    
    
    def _convert_gym_action(self, action: int) -> Dict[str, Any]:
        """Convert gym action - delegates to action_decoder."""
        return self.action_decoder.convert_gym_action(action, self.game_state)
    
    
    def _initialize_units(self):
        """Initialize units - delegates to state_manager."""
        self.state_manager.initialize_units(self.game_state)
    
    
    def _load_units_from_scenario(self, scenario_file, unit_registry):
        """Load units from scenario - delegates to state_manager."""
        # Create temporary state_manager just for loading during init
        temp_manager = GameStateManager({"board": {}}, unit_registry)
        return temp_manager.load_units_from_scenario(scenario_file, unit_registry)


# ============================================================================
# KEEP AT END OF FILE
# ============================================================================

if __name__ == "__main__":
    print("W40K Engine requires proper config from training system - no standalone execution")