#!/usr/bin/env python3
"""
w40k_core.py - Slim W40K Game Engine Core
Delegates to specialized modules, orchestrates game flow.
"""

import os
import copy
import torch
import json
import random
import gymnasium as gym
import numpy as np
from typing import Dict, List, Tuple, Set, Optional, Any

# Import shared utilities
from engine.combat_utils import calculate_hex_distance

# Phase handlers (existing - keep these)
from engine.phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers, command_handlers

# Import shared utilities FIRST (no circular dependencies)
from engine.game_utils import get_unit_by_id

# Import NEW extracted modules
from engine.observation_builder import ObservationBuilder
from engine.action_decoder import ActionDecoder
from engine.reward_calculator import RewardCalculator
from engine.game_state import GameStateManager
from engine.pve_controller import PvEController

# Global flag to ensure debug.log is cleared only once per training session
_debug_log_cleared = False

def reset_debug_log_flag():
    """Reset the debug log cleared flag. Call this at the start of each training run."""
    global _debug_log_cleared
    _debug_log_cleared = False


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
                scenario_files=None,  # NEW: List of scenarios for random selection per episode
                unit_registry=None, quiet=True, gym_training_mode=False, debug_mode=False, **kwargs):
        """Initialize W40K engine with AI_TURN.md compliance - training system compatible.

        Args:
            scenario_file: Single scenario file path (used if scenario_files not provided)
            scenario_files: List of scenario file paths for random selection per episode
        """

        # Store gym training mode for handler access
        self.gym_training_mode = gym_training_mode
        self.debug_mode = debug_mode

        # Store scenario files list for random selection during reset
        # If scenario_files provided, use it; otherwise create single-item list from scenario_file
        if scenario_files and len(scenario_files) > 0:
            self._scenario_files = scenario_files
            self._random_scenario_mode = True
            # Use first scenario for initial setup
            scenario_file = scenario_files[0]
        else:
            self._scenario_files = [scenario_file] if scenario_file else []
            self._random_scenario_mode = False

        # Store current scenario file path for reference
        self._current_scenario_file = scenario_file
        
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

            # Determine objectives: use scenario if provided, otherwise fallback to board config
            # New format: grouped objectives with id, name, hexes
            if scenario_result.get("objectives") is not None:
                scenario_objectives = scenario_result["objectives"]
            else:
                # Fallback to board config (legacy flat list or new grouped format)
                if "default" in board_config:
                    scenario_objectives = board_config["default"].get("objectives", board_config["default"].get("objective_hexes", []))
                else:
                    scenario_objectives = board_config.get("objectives", board_config.get("objective_hexes", []))

            # Store scenario terrain for game_state initialization
            self._scenario_wall_hexes = scenario_wall_hexes
            self._scenario_objectives = scenario_objectives

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
                "debug_mode": debug_mode,  # CRITICAL: Pass debug flag to handlers
                "pve_mode": pve_mode_value,  # CRITICAL: Add PvE mode for handler detection
                "controlled_player": 1  # FIXED: Agent controls player 1 (matches scenario setup)
            }
        else:
            # Use provided config directly and add gym_training_mode
            self.config = config.copy()
            self.config["gym_training_mode"] = gym_training_mode
            self.config["debug_mode"] = debug_mode
            # CRITICAL: Ensure pve_mode is in config for handler delegation
            if "pve_mode" not in self.config:
                self.config["pve_mode"] = config.get("pve_mode", False)
            # CHANGE 5: Ensure controlled_player is set
            if "controlled_player" not in self.config:
                self.config["controlled_player"] = 1  # FIXED: Agent controls player 1 (matches scenario setup)

            # CRITICAL: Extract rewards_config from config dict for module initialization
            self.rewards_config = config.get("rewards_config", {})
            
            # CRITICAL: Extract training_config from config dict for observation_params access
            # API server provides training_configs dict with agent keys, or training_config_name to select phase
            if "training_configs" in config and training_config_name:
                # Multi-agent config: extract specific agent's training config
                first_agent = list(config.get("agent_keys", []))[0] if config.get("agent_keys") else None
                if first_agent and first_agent in config["training_configs"]:
                    full_training_config = config["training_configs"][first_agent]
                    # Extract the specific phase (e.g., "default")
                    self.training_config = full_training_config.get(training_config_name, {})
                    self.training_config_name = training_config_name
                else:
                    self.training_config = None
            elif "training_config" in config:
                # Direct training_config provided
                self.training_config = config["training_config"]
                self.training_config_name = training_config_name if training_config_name else "default"
            else:
                # Try to construct from observation_params if available
                if "observation_params" in config:
                    # Create minimal training_config structure for observation_params access
                    self.training_config = {
                        "observation_params": config["observation_params"]
                    }
                    self.training_config_name = training_config_name if training_config_name else "default"
                else:
                    self.training_config = None

            # No scenario loaded - use board config for terrain (set to None for fallback logic)
            self._scenario_wall_hexes = None
            self._scenario_objectives = None
        
        # Store training system compatibility parameters
        self.quiet = quiet
        self.unit_registry = unit_registry
        self.step_logger = None  # Will be set by training system if enabled
        self.replay_logger = None  # Will be set by training system for replay capture
        
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
            "current_player": 1,
            "gym_training_mode": self.config["gym_training_mode"],  # Embed for handler access
            "debug_mode": self.config.get("debug_mode", False),  # Embed for handler access
            "training_config_name": training_config_name if training_config_name else "",  # NEW: For debug mode detection
            "phase": "command",
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
            "command_activation_pool": [],
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
            # Objectives: grouped structure with id, name, hexes (for objective control calculation)
            "objectives": self._scenario_objectives if self._scenario_objectives is not None else (self.config["board"]["default"].get("objectives", []) if "default" in self.config["board"] else self.config["board"].get("objectives", []))
        }

        # CRITICAL: Instantiate all module managers BEFORE using them
        self.state_manager = GameStateManager(self.config, self.unit_registry)
        self.obs_builder = ObservationBuilder(self.config)
        self.action_decoder = ActionDecoder(self.config)
        # Use rewards_config from config dict if not already loaded
        rewards_cfg = getattr(self, 'rewards_config', self.config.get("rewards_config", {}))
        self.reward_calculator = RewardCalculator(self.config, self.rewards_config, self.unit_registry, self.state_manager)
        self.pve_controller = PvEController(self.config)
        
        # Initialize units from config AFTER game_state exists
        self._initialize_units()
        
        # CRITICAL: Initialize Gym spaces BEFORE any other operations
        # Gym interface properties - dynamic action space based on phase
        self.action_space = gym.spaces.Discrete(13)  # Expanded: 4 move + 5 shoot + charge + fight + wait + advance
        self._current_valid_actions = list(range(13))  # Will be masked dynamically
        
        # Observation space: Asymmetric egocentric perception with R=25 radius
        # Size is now configurable via training_config.json observation_params.obs_size
        # Default was 300 floats = 15 global (incl. objectives) + 8 unit + 32 terrain + 72 allies + 138 enemies + 35 targets
        # New size: 313 floats = 15 global + 22 unit capabilities + 32 terrain + 72 allies + 132 enemies + 40 targets
        
        # Load perception parameters from training config if available
        if hasattr(self, 'training_config') and self.training_config:
            obs_params = self.training_config.get("observation_params", {})
            
            # Validation stricte: obs_size DOIT être présent
            if "obs_size" not in obs_params:
                raise KeyError(
                    f"training_config missing required 'obs_size' in observation_params. "
                    f"Must be defined in training_config.json. "
                    f"Config: {self.training_config_name if hasattr(self, 'training_config_name') else 'unknown'}"
                )
            
            obs_size = obs_params["obs_size"]  # NO DEFAULT - raise error si manquant
            self.perception_radius = obs_params.get("perception_radius", 25)
            self.max_nearby_units = obs_params.get("max_nearby_units", 10)
            self.max_valid_targets = obs_params.get("max_valid_targets", 5)
        else:
            # Pas de config = erreur (pas de fallback)
            raise ValueError(
                "W40KEngine requires training_config with observation_params.obs_size. "
                "No default value allowed."
            )
        
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
        )
        
        # Initialize position caching for movement_direction feature
        self.last_unit_positions = {}  # {unit_id: (col, row)}
        
        # Episode-level metrics accumulation for MetricsCollectionCallback
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        self.episode_number = 0  # Track episode number for debug logging
        
        # Clear debug.log ONCE at the start of training (before first episode)
        # This ensures each training session starts with a clean log file
        # Use global flag to prevent clearing if multiple engine instances are created
        global _debug_log_cleared
        if not _debug_log_cleared:
            movement_debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
            try:
                with open(movement_debug_path, 'w', encoding='utf-8', errors='replace') as f:
                    f.write("=== MOVEMENT DEBUG LOG ===\n")
                    f.write("Cleared at training session start\n")
                    f.write("=" * 80 + "\n\n")
                    f.flush()
                _debug_log_cleared = True
            except Exception as e:
                print(f"⚠️ Failed to clear debug.log: {e}")
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

        # RANDOM SCENARIO SELECTION: Pick a random scenario for this episode
        if self._random_scenario_mode and len(self._scenario_files) > 1:
            self._current_scenario_file = random.choice(self._scenario_files)
            self._reload_scenario(self._current_scenario_file)

        # Reset episode-level metric accumulators
        self.episode_reward_accumulator = 0.0
        self.episode_length_accumulator = 0
        
        # Increment episode number (original logic - works fine for everything except debug.log)
        self.episode_number += 1
        
        # Reset game state
        self.game_state.update({
            "current_player": 1,
            "phase": "command",
            "turn": 1,
            "episode_steps": 0,
            "episode_number": self.episode_number,
            "game_over": False,
            "winner": None,
            "units_moved": set(),
            "units_fled": set(),
            "units_shot": set(),
            "units_charged": set(),
            "units_attacked": set(),
            "command_activation_pool": [],
            "move_activation_pool": [],
            "fight_subphase": None,
            "charge_range_rolls": {},
            "action_logs": [],  # CRITICAL: Reset action logs for new episode metrics
            "gym_training_mode": self.gym_training_mode,  # ADDED: For handler access
            "debug_mode": self.debug_mode,  # ADDED: For handler access
            "console_logs": [],  # CRITICAL: Initialize console_logs for debug logging across all episodes
            "hex_los_cache": {},  # PERFORMANCE: Clear hex-coordinate LoS cache for new episode
            "objective_controllers": {}  # RESET: Clear objective control for new episode
        })
        
        # DIAGNOSTIC: Log debug_mode status on reset (write to debug.log) - DISABLED TEMPORARILY
        # if self.debug_mode:
        #     movement_debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
        #     try:
        #         with open(movement_debug_path, 'a', encoding='utf-8', errors='replace') as f:
        #             f.write(f"[DIAGNOSTIC] DEBUG MODE ENABLED: gym_training_mode={self.gym_training_mode}, debug_mode={self.debug_mode}\n")
        #             f.flush()
        #     except Exception:
        #         pass

        # Reset unit health and positions to original scenario values
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field during reset")
        unit_configs = self.config["units"]
        for unit in self.game_state["units"]:
            unit["HP_CUR"] = unit["HP_MAX"]

            # CRITICAL: Reset shooting state per episode
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or first weapon
            from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
            
            # Initialize SHOOT_LEFT from selected ranged weapon
            selected_rng_weapon = get_selected_ranged_weapon(unit)
            if selected_rng_weapon:
                unit["SHOOT_LEFT"] = selected_rng_weapon["NB"]
            elif unit.get("RNG_WEAPONS") and len(unit["RNG_WEAPONS"]) > 0:
                unit["SHOOT_LEFT"] = unit["RNG_WEAPONS"][0]["NB"]
            else:
                unit["SHOOT_LEFT"] = 0
            
            # Initialize ATTACK_LEFT from selected melee weapon
            selected_cc_weapon = get_selected_melee_weapon(unit)
            if selected_cc_weapon:
                unit["ATTACK_LEFT"] = selected_cc_weapon["NB"]
            elif unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                unit["ATTACK_LEFT"] = unit["CC_WEAPONS"][0]["NB"]
            else:
                unit["ATTACK_LEFT"] = 0

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
        
        # Initialize command phase for game start using handler delegation
        # CRITICAL: reset() is not in the cascade loop, so we need to handle initialization differently
        # Call command_phase_start() to do the resets, then call movement_phase_start() directly
        command_handlers.command_phase_start(self.game_state)  # Does the resets
        movement_handlers.movement_phase_start(self.game_state)  # Initializes the move phase
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
        
        # Log episode start with all unit positions, walls, and objectives
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            # Extract scenario name: prefer config "name", fallback to filename pattern
            scenario_name = self.config.get("name")
            if not scenario_name or scenario_name == "Unknown Scenario":
                # Extract from filename: AgentName_scenario_phase1-bot3.json -> phase1-bot3
                if hasattr(self, '_current_scenario_file') and self._current_scenario_file:
                    filename = os.path.basename(self._current_scenario_file)
                    # Match pattern: *_scenario_*.json
                    import re
                    match = re.search(r'_scenario_(.+?)\.json$', filename)
                    if match:
                        scenario_name = match.group(1)
                    else:
                        # Fallback: use filename without extension
                        scenario_name = os.path.splitext(filename)[0]
                else:
                    scenario_name = "Unknown Scenario"
            
            # Determine bot_name for self-play (default to "SelfPlay" if not set)
            bot_name = None
            if hasattr(self.step_logger, 'current_bot_name') and self.step_logger.current_bot_name:
                bot_name = self.step_logger.current_bot_name
            else:
                # In self-play mode, use a default name
                bot_name = "SelfPlay"
            
            # Use _scenario_wall_hexes (set during scenario loading) - convert to step_logger format
            raw_walls = self._scenario_wall_hexes if self._scenario_wall_hexes is not None else []
            walls = [{"col": w[0], "row": w[1]} for w in raw_walls] if raw_walls else []
            # Use _scenario_objectives (set during scenario loading)
            objectives = self._scenario_objectives if hasattr(self, '_scenario_objectives') else None
            
            self.step_logger.log_episode_start(self.game_state["units"], scenario_name, bot_name=bot_name, walls=walls, objectives=objectives)
            
            # CRITICAL: Synchronize game_state["episode_number"] with step_logger.episode_number
            # This ensures debug.log uses the same episode number as step.log
            # step_logger.episode_number was incremented in log_episode_start()
            self.game_state["episode_number"] = self.step_logger.episode_number
        
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
                # CRITICAL: Set turn_limit_reached flag in game_state for winner determination
                self.game_state["turn_limit_reached"] = True
                observation = self.obs_builder.build_observation(self.game_state)
                winner, win_method = self._determine_winner_with_method()
                
                # CRITICAL: win_method should never be None when game is terminated
                if win_method is None:
                    import warnings
                    warnings.warn(f"BUG: win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}")
                    if winner == -1:
                        win_method = "draw"
                    else:
                        win_method = "elimination"  # Default fallback
                
                info = {"turn_limit_exceeded": True, "winner": winner, "win_method": win_method}
                
                # Log episode end if step_logger is enabled
                if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                    self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method)
                
                return observation, 0.0, True, False, info

        # Check for game termination before action
        self.game_state["game_over"] = self._check_game_over()

        # CRITICAL FIX: Auto-advance phase when no valid actions exist
        # This handles the case where fight phase pools are empty
        action_mask = self.get_action_mask()
        if not np.any(action_mask):
            # No valid actions - trigger phase transition
            current_phase = self.game_state["phase"]
            if current_phase == "fight":
                from engine.phase_handlers import fight_handlers
                result = fight_handlers.fight_phase_end(self.game_state)
            # After phase transition, get new observation
            observation = self.obs_builder.build_observation(self.game_state)
            # Check if game ended after phase transition
            self.game_state["game_over"] = self._check_game_over()
            
            # CRITICAL: Copy turn_limit_reached from result to game_state if present
            if isinstance(result, dict) and result.get("turn_limit_reached", False):
                self.game_state["turn_limit_reached"] = True
            
            terminated = self.game_state["game_over"]
            info = {"phase_auto_advanced": True, "previous_phase": current_phase}
            if terminated:
                winner, win_method = self._determine_winner_with_method()
                
                # CRITICAL: win_method should never be None when game is terminated
                if win_method is None:
                    import warnings
                    warnings.warn(f"BUG: win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}")
                    if winner == -1:
                        win_method = "draw"
                    else:
                        win_method = "elimination"  # Default fallback
                
                info["winner"] = winner
                info["win_method"] = win_method
                
                # Log episode end if step_logger is enabled
                if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                    self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method)
            
            return observation, 0.0, terminated, False, info
        
        # Convert gym integer action to semantic action
        semantic_action = self.action_decoder.convert_gym_action(action, self.game_state)
        
        # CRITICAL: Capture pre-action state for replay_logger BEFORE action execution
        # These are needed for replay logging (independent of step_logger)
        pre_action_phase = self.game_state.get("phase", "unknown")
        pre_action_positions = {}
        if "unitId" in semantic_action:
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
        # Note: pre_action_phase, pre_action_player, and pre_action_turn are already captured
        # at lines 598-600 BEFORE action execution
        
        # Log to replay_logger for replay file generation (independent of step_logger)
        # Log action for replay/debugging
        if hasattr(self, 'replay_logger') and self.replay_logger and success:
            # Get action_type and unit_id using same logic as step_logger
            # CRITICAL: No fallbacks - require explicit values in result
            if not isinstance(result, dict):
                raise TypeError(f"result must be a dict for replay logger, got {type(result).__name__}")
            
            action_type = result.get("action")
            if action_type is None:
                raise ValueError(f"result missing 'action' field for replay logger. result keys: {list(result.keys())}")
            
            unit_id = result.get("unitId")
            if unit_id is None:
                raise ValueError(f"result missing 'unitId' field for replay logger. result keys: {list(result.keys())}")

            valid_action_types = ["move", "shoot", "charge", "charge_fail", "combat", "wait"]
            if action_type in valid_action_types and unit_id and unit_id != "none" and unit_id != "SYSTEM":
                updated_unit = self._get_unit_by_id(str(unit_id)) if unit_id else None
                if updated_unit:
                    current_turn = self.game_state.get("current_turn", 1)
                    step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)

                    if action_type == "move":
                        # CRITICAL: No fallbacks - require explicit coordinates
                        if str(unit_id) not in pre_action_positions:
                            raise ValueError(f"Replay logger move missing start position in pre_action_positions: unit_id={unit_id}")
                        start_pos = pre_action_positions[str(unit_id)]
                        # Use result destination, then action, no fallback to updated_unit
                        if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
                            dest_col = result.get("toCol")
                            dest_row = result.get("toRow")
                        elif isinstance(semantic_action, dict) and semantic_action.get("destCol") is not None and semantic_action.get("destRow") is not None:
                            dest_col = semantic_action.get("destCol")
                            dest_row = semantic_action.get("destRow")
                        else:
                            raise ValueError(f"Replay logger move missing destination: result.toCol={result.get('toCol') if isinstance(result, dict) else None}, result.toRow={result.get('toRow') if isinstance(result, dict) else None}, action.destCol={semantic_action.get('destCol') if isinstance(semantic_action, dict) else None}, action.destRow={semantic_action.get('destRow') if isinstance(semantic_action, dict) else None}")
                        self.replay_logger.log_move(
                            updated_unit,
                            start_pos[0], start_pos[1],
                            dest_col, dest_row,
                            current_turn, step_reward, 0
                        )
                    elif action_type == "shoot":
                        # CRITICAL: No fallbacks - require explicit targetId in result
                        target_id = result.get("targetId")
                        if target_id is None:
                            raise ValueError(f"Replay logger shoot missing targetId: result keys: {list(result.keys())}")
                        target_unit = self._get_unit_by_id(str(target_id))
                        if target_unit:
                            # Build shoot_details from last_attack_result
                            attack_result = self.game_state.get("last_attack_result", {})
                            shoot_details = {
                                "summary": {
                                    "totalShots": 1,
                                    "hits": 1 if attack_result.get("hit_success") else 0,
                                    "wounds": 1 if attack_result.get("wound_success") else 0,
                                    "failedSaves": 1 if attack_result.get("damage", 0) > 0 else 0
                                },
                                "shots": [{
                                    "hit_roll": attack_result.get("hit_roll", 0),
                                    "wound_roll": attack_result.get("wound_roll", 0),
                                    "save_roll": attack_result.get("save_roll", 0),
                                    "damage": attack_result.get("damage", 0),
                                    "hit": attack_result.get("hit_success", False),
                                    "wound": attack_result.get("wound_success", False),
                                    "save_success": attack_result.get("save_success", False),
                                    "hit_target": attack_result.get("hit_target", 4),
                                    "wound_target": attack_result.get("wound_target", 4),
                                    "save_target": attack_result.get("save_target", 4)
                                }]
                            }
                            self.replay_logger.log_shoot(
                                updated_unit, target_unit, shoot_details,
                                current_turn, step_reward, 4
                            )
                    elif action_type == "charge":
                        target_id = result.get("targetId")
                        target_unit = self._get_unit_by_id(str(target_id)) if target_id else None
                        if target_unit:
                            # CRITICAL: No fallbacks - require explicit coordinates
                            if str(unit_id) not in pre_action_positions:
                                raise ValueError(f"Replay logger charge missing start position in pre_action_positions: unit_id={unit_id}")
                            start_pos = pre_action_positions[str(unit_id)]
                            # Use result destination, then action, no fallback to updated_unit
                            if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
                                dest_col = result.get("toCol")
                                dest_row = result.get("toRow")
                            elif isinstance(semantic_action, dict) and semantic_action.get("destCol") is not None and semantic_action.get("destRow") is not None:
                                dest_col = semantic_action.get("destCol")
                                dest_row = semantic_action.get("destRow")
                            else:
                                raise ValueError(f"Replay logger charge missing destination: result.toCol={result.get('toCol') if isinstance(result, dict) else None}, result.toRow={result.get('toRow') if isinstance(result, dict) else None}, action.destCol={semantic_action.get('destCol') if isinstance(semantic_action, dict) else None}, action.destRow={semantic_action.get('destRow') if isinstance(semantic_action, dict) else None}")
                            self.replay_logger.log_charge(
                                updated_unit, target_unit,
                                start_pos[0], start_pos[1],
                                dest_col, dest_row,
                                current_turn, step_reward, 5,
                                charge_roll=result.get("charge_roll"),
                                die1=None, die2=None,
                                charge_succeeded=result.get("charge_succeeded", True)
                            )
                    elif action_type == "combat":
                        target_id = result.get("targetId")
                        target_unit = self._get_unit_by_id(str(target_id)) if target_id else None
                        if target_unit:
                            # Build combat_details from last_attack_result
                            attack_result = self.game_state.get("last_attack_result", {})
                            combat_details = {
                                "summary": {
                                    "totalAttacks": 1,
                                    "hits": 1 if attack_result.get("hit_success") else 0,
                                    "wounds": 1 if attack_result.get("wound_success") else 0,
                                    "failedSaves": 1 if attack_result.get("damage_dealt", 0) > 0 else 0
                                }
                            }
                            self.replay_logger.log_combat(
                                updated_unit, target_unit, combat_details,
                                current_turn, step_reward, 7
                            )
                    elif action_type == "wait":
                        current_phase = self.game_state.get("phase", pre_action_phase)
                        self.replay_logger.log_wait(
                            updated_unit, current_turn, current_phase,
                            step_reward, 6
                        )

        # Convert to gym format
        observation = self.obs_builder.build_observation(self.game_state)
        # Calculate reward (independent of step_logger)
        reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
        terminated = self.game_state["game_over"]
        truncated = False
        info = result.copy() if isinstance(result, dict) else {}
        info["success"] = success
        
        # CRITICAL: Copy turn_limit_reached from result to game_state if present
        # This must happen BEFORE calling _determine_winner_with_method()
        if isinstance(result, dict) and result.get("turn_limit_reached", False):
            self.game_state["turn_limit_reached"] = True
        
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
            winner, win_method = self._determine_winner_with_method()
            
            # CRITICAL: win_method should never be None when game is terminated
            if win_method is None:
                import warnings
                warnings.warn(f"BUG: win_method is None but terminated=True. Winner={winner}, Turn={self.game_state.get('turn')}")
                if winner == -1:
                    win_method = "draw"
                else:
                    win_method = "elimination"  # Default fallback
            
            info["winner"] = winner
            info["win_method"] = win_method
            
            # CRITICAL: Populate info["episode"] for Stable-Baselines3 MetricsCollectionCallback
            info["episode"] = {
                "r": float(self.episode_reward_accumulator),
                "l": int(self.episode_length_accumulator),
                "t": int(self.episode_length_accumulator),
            }
            
            # Calculate units killed/lost
            # Controlled agent is always player 1 in training
            controlled_player = 1
            
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

            # Store turn number for metrics filtering (e.g., objectives only on turn 5+)
            self.episode_tactical_data['final_turn'] = self.game_state["turn"]

            # Count controlled objectives for Player 0 (learning agent)
            obj_counts = self.state_manager.count_controlled_objectives(self.game_state)
            self.episode_tactical_data['controlled_objectives'] = obj_counts.get(0, 0)

            # Add tactical data to info
            info["tactical_data"] = self.episode_tactical_data.copy()
            
            # Log episode end with final stats and win method
            if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
                self.step_logger.log_episode_end(self.game_state["episode_steps"], winner, win_method)
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
        
        # Write console_logs to debug.log (for hidden_action_finder.py)
        if "console_logs" in self.game_state and self.game_state["console_logs"]:
            movement_debug_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.log')
            log_count = len(self.game_state["console_logs"])
            step_logger_debug_count = sum(1 for log in self.game_state["console_logs"] if "[STEP LOGGER DEBUG]" in str(log))
            
            # DIAGNOSTIC: Log before writing (write to debug.log) - DISABLED TEMPORARILY
            # if step_logger_debug_count > 0:
            #     diagnostic_msg = f"[DIAGNOSTIC] Writing {log_count} console logs to debug.log ({step_logger_debug_count} STEP LOGGER DEBUG messages)"
            #     try:
            #         with open(movement_debug_path, 'a', encoding='utf-8', errors='replace') as f:
            #             f.write(diagnostic_msg + "\n")
            #             f.flush()
            #     except Exception:
            #         pass
            
            try:
                with open(movement_debug_path, 'a', encoding='utf-8', errors='replace') as f:
                    for log_msg in self.game_state["console_logs"]:
                        # Ensure log message is a string and encode safely
                        if not isinstance(log_msg, str):
                            log_msg = str(log_msg)
                        # Replace any problematic characters that might cause encoding issues
                        log_msg = log_msg.encode('utf-8', errors='replace').decode('utf-8')
                        f.write(log_msg + "\n")
                    f.flush()  # Force flush to ensure logs are written immediately
                
                # DIAGNOSTIC: Log after writing (write to debug.log) - DISABLED TEMPORARILY
                # if step_logger_debug_count > 0:
                #     diagnostic_msg = f"[DIAGNOSTIC] Successfully wrote {log_count} logs to debug.log"
                #     try:
                #         with open(movement_debug_path, 'a', encoding='utf-8', errors='replace') as f:
                #             f.write(diagnostic_msg + "\n")
                #             f.flush()
                #     except Exception:
                #         pass
                
                # Clear console_logs after writing to avoid duplicates
                self.game_state["console_logs"] = []
            except Exception as e:
                print(f"⚠️ Failed to write to debug.log: {e}")
                import traceback
                traceback.print_exc()
            
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
        current_phase = self.game_state["phase"]
        
        # CRITICAL: In fight phase, current_player can be 1 but AI can still act in alternating phase
        # Only check current_player for non-fight phases
        if current_phase != "fight" and current_player != 2:  # AI is player 2
            return False, {"error": "not_ai_player_turn", "current_player": current_player, "phase": current_phase}
        
        # For fight phase, check if AI has eligible units in the appropriate pool
        if current_phase == "fight":
            fight_subphase = self.game_state.get("fight_subphase")
            # Check if AI has eligible units in the current fight subphase pool
            has_eligible_ai = False
            pool_to_check = []
            
            if fight_subphase == "charging" and self.game_state.get("charging_activation_pool"):
                pool_to_check = self.game_state.get("charging_activation_pool", [])
            elif fight_subphase in ["alternating_non_active", "cleanup_non_active"] and self.game_state.get("non_active_alternating_activation_pool"):
                pool_to_check = list(self.game_state.get("non_active_alternating_activation_pool", []))  # Make a copy to avoid reference issues
            elif fight_subphase in ["alternating_active", "cleanup_active"] and self.game_state.get("active_alternating_activation_pool"):
                pool_to_check = self.game_state.get("active_alternating_activation_pool", [])
            
            # Check if any unit in the pool is an AI unit (player 2)
            for unit_id in pool_to_check:
                unit = self._get_unit_by_id(str(unit_id))
                if unit and unit.get("player") == 2:
                    has_eligible_ai = True
                    break
            
            if not has_eligible_ai:
                return False, {"error": "not_ai_player_turn", "current_player": current_player, "phase": current_phase, "fight_subphase": fight_subphase, "reason": "no_eligible_ai_units_in_pool", "pool_checked": pool_to_check}
        
        # Check AI model availability
        if not hasattr(self, '_ai_model') or not self._ai_model:
            return False, {"error": "ai_model_not_loaded"}
        
        # Make AI decision - replaces human click
        try:
            ai_semantic_action = self.pve_controller.make_ai_decision(self.game_state, self)
            
            # Execute through SAME path as humans
            result = self._process_semantic_action(ai_semantic_action)
            return result
            
        except Exception as e:
            pass
            import traceback
            traceback.print_exc()
            return False, {"error": "ai_decision_failed", "message": str(e)}
    
    
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action with detailed execution debugging.
        CRITICAL: This is the SINGLE POINT OF LOGGING for all actions (training, frontend, PvE).
        """
        current_phase = self.game_state["phase"]
        
        # CRITICAL: Capture phase, player, turn, episode, and positions BEFORE action execution for accurate logging
        # This must be done BEFORE any handler execution to capture the correct state
        pre_action_phase = self.game_state["phase"]
        pre_action_player = self.game_state["current_player"]
        pre_action_turn = self.game_state.get("turn", 1)
        pre_action_episode = self.game_state.get("episode_number", 1)  # CRITICAL: Capture episode BEFORE action execution
        pre_action_positions = {}
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            # AI_TURN.md COMPLIANCE: Direct field access for semantic actions
            if "unitId" not in action:
                unit_id = None
            else:
                unit_id = action["unitId"]
            if unit_id:
                pre_unit = self._get_unit_by_id(str(unit_id))
                if pre_unit:
                    pre_action_positions[str(unit_id)] = (pre_unit["col"], pre_unit["row"])

        # Handle special "advance_phase" action when pool is empty
        if action.get("action") == "advance_phase":
            # Pool is empty - trigger phase transition
            from_phase = action.get("from", current_phase)
            result = {"phase_complete": True, "reason": "pool_empty"}

            # Determine next phase based on current phase
            if from_phase == "move":
                result["next_phase"] = "shoot"
            elif from_phase == "shoot":
                result["next_phase"] = "charge"
            elif from_phase == "charge":
                result["next_phase"] = "fight"
            elif from_phase == "fight":
                result["next_phase"] = "command"
            elif from_phase == "command":
                result["next_phase"] = "move"
            else:
                result["next_phase"] = "move"

            # CRITICAL FIX: Don't return early - fall through to cascade loop
            # to actually execute the phase transition in game_state
            success = True
            # Fall through to cascade loop below

        # Route to phase handlers with detailed logging (only if not advance_phase)
        elif current_phase == "command":
            success, result = self._process_command_phase(action)
        elif current_phase == "move":
            success, result = self._process_movement_phase(action)
        elif current_phase == "shoot":
            success, result = self._process_shooting_phase(action)
        elif current_phase == "charge":
            success, result = self._process_charge_phase(action)
        elif current_phase == "fight":
            success, result = self._process_fight_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}

        # CRITICAL FIX: Log action BEFORE cascade to ensure action is logged even if phase completes
        # Log action with result (before cascade modifies it)
        if (self.step_logger and self.step_logger.enabled):
            try:
                
                # CHANGE 1: Read action from result dict FIRST (handlers populate actual executed action)
                # Diagnostic proved: result.get('action')='move' but action.get('action')='activate_unit'
                action_type = result.get("action") if isinstance(result, dict) else None
                
                # CRITICAL: No diagnostic logging - errors should be explicit, not masked
                
                # CRITICAL: action_type must be a string from result - no fallbacks, no workarounds
                if not isinstance(result, dict):
                    raise TypeError(f"result must be a dict, got {type(result).__name__}")
                
                action_type = result.get("action")
                if action_type is None:
                    # Check if this is a phase transition without action (system response, not an action)
                    if result.get("phase_complete") or result.get("phase_transition"):
                        # Phase transition without action - skip logging (will be handled by cascade loop)
                        action_type = None
                    else:
                        # No action in result and not a phase transition - this is an error
                        raise ValueError(f"result missing 'action' field and is not a phase transition. result keys: {list(result.keys())}")
                elif not isinstance(action_type, str):
                    raise TypeError(f"result['action'] must be a string, got {type(action_type).__name__}: {action_type}")
                elif action_type == "fight":
                    # "fight" is not a valid action_type - handlers must return "combat" or "wait"
                    raise ValueError(f"Invalid action_type 'fight' in result. Handlers must set proper action ('combat' or 'wait'). result keys: {list(result.keys())}")
                
                # Skip logging for system actions and intermediate actions
                skip_logging_action_types = [
                    "advance_phase",  # System action
                    "advance_select_destination",  # Intermediate action
                    "empty_target_advance_available",  # Intermediate action
                    "advance_cancelled",  # Intermediate action
                    "waiting_for_movement_choice"  # Intermediate action
                ]
                
                if action_type in skip_logging_action_types:
                    # System or intermediate action - skip logging
                    pass
                elif action_type is not None:
                    # CRITICAL: unitId must be in result - no fallbacks
                    unit_id = result.get("unitId")
                    if unit_id is None:
                        raise ValueError(f"result missing 'unitId' field for action_type '{action_type}'. result keys: {list(result.keys())}")
                    
                    # Check waiting_for_player state
                    # For combat/shoot: log attacks already executed even if waiting_for_player=True
                    # For other actions: skip logging if waiting_for_player=True (action not yet complete)
                    waiting_for_player = result.get("waiting_for_player", False)
                    
                    # Special case: combat or shoot with waiting_for_player but all_attack_results present
                    # These attacks were already executed and must be logged
                    all_attack_results = result.get("all_attack_results", [])
                    is_action_with_attacks = (
                        action_type in ["combat", "shoot"] and 
                        waiting_for_player and 
                        len(all_attack_results) > 0
                    )
                    
                    if waiting_for_player and not is_action_with_attacks:
                        # Skip logging - waiting for player input, action not yet complete
                        # Will be logged when the actual action completes (e.g., move after destination selection)
                        pass
                    else:
                        # Validation - action_type should already be validated above, but double-check
                        if not action_type:
                            raise ValueError(f"action_type is None or empty - cannot log action. result keys: {list(result.keys())}")

                        valid_action_types = ["move", "shoot", "charge", "charge_fail", "combat", "wait", "advance", "flee"]
                        if action_type not in valid_action_types:
                            raise ValueError(f"Invalid action_type '{action_type}'. Valid types: {valid_action_types}")

                        if not unit_id:
                            raise ValueError(f"unit_id is None or empty - cannot log action. action_type={action_type}")

                        if unit_id == "none" or unit_id == "SYSTEM":
                            raise ValueError(f"Invalid unit_id '{unit_id}' - cannot log system actions. action_type={action_type}")

                        # Get unit coordinates AFTER action execution using semantic action unitId
                        updated_unit = self._get_unit_by_id(str(unit_id)) if unit_id else None
                        
                        if updated_unit:
                            # Use PRE-ACTION position from captured data for movement logging
                            # CRITICAL FIX: Also use pre_action_positions for "flee" actions
                            if str(unit_id) in pre_action_positions and (action_type == "move" or action_type == "flee"):
                                orig_col, orig_row = pre_action_positions[str(unit_id)]
                                action_details = {
                                    "current_turn": pre_action_turn,  # Use turn captured BEFORE action execution
                                    "current_episode": pre_action_episode,  # CRITICAL: Use episode captured BEFORE action execution
                                    # unit_with_coords sera mis à jour plus bas avec result
                                    "action": action,
                                    "start_pos": (orig_col, orig_row)
                                    # end_pos et unit_with_coords seront définis dans action_details.update() avec result
                                }
                            else:
                                # Build complete action details for step logger
                                action_details = {
                                    "current_turn": pre_action_turn,  # Use turn captured BEFORE action execution
                                    "current_episode": pre_action_episode,  # CRITICAL: Use episode captured BEFORE action execution
                                    # unit_with_coords sera mis à jour plus bas avec result
                                    "action": action
                                }
                    
                        # Add specific data for different action types
                        # NOTE: move, shoot, wait use the common logging path below
                        # charge and combat have their own specialized logging
                        if action_type == "move" or action_type == "flee":
                            # Use semantic action coordinates for accurate logging
                            # CRITICAL FIX: Always use result for positions (populated by movement handler)
                            # This ensures correct positions even if pre_action_positions is missing
                            if action_type == "flee":
                                # CRITICAL: No fallbacks - require explicit coordinates from result or action
                                if not isinstance(result, dict):
                                    raise ValueError(f"Flee action missing result dict: unit_id={unit_id}")
                                if result.get("fromCol") is None or result.get("fromRow") is None:
                                    raise ValueError(f"Flee action missing fromCol/fromRow in result: unit_id={unit_id}, result keys={list(result.keys())}")
                                if result.get("toCol") is None or result.get("toRow") is None:
                                    # Try action as fallback
                                    if isinstance(action, dict) and action.get("destCol") is not None and action.get("destRow") is not None:
                                        dest_col = action.get("destCol")
                                        dest_row = action.get("destRow")
                                    else:
                                        raise ValueError(f"Flee action missing toCol/toRow: result.toCol={result.get('toCol')}, result.toRow={result.get('toRow')}, action.destCol={action.get('destCol') if isinstance(action, dict) else None}, action.destRow={action.get('destRow') if isinstance(action, dict) else None}")
                                else:
                                    dest_col = result.get("toCol")
                                    dest_row = result.get("toRow")
                                start_pos = (result.get("fromCol"), result.get("fromRow"))
                                end_pos = (dest_col, dest_row)
                            else:
                                # CRITICAL: No fallbacks - require explicit coordinates from result or pre_action_positions
                                if isinstance(result, dict) and result.get("fromCol") is not None and result.get("fromRow") is not None:
                                    start_pos = (result.get("fromCol"), result.get("fromRow"))
                                elif str(unit_id) in pre_action_positions:
                                    start_pos = pre_action_positions[str(unit_id)]
                                else:
                                    raise ValueError(f"Move action missing start position: unit_id={unit_id}, result.fromCol={result.get('fromCol') if isinstance(result, dict) else None}, result.fromRow={result.get('fromRow') if isinstance(result, dict) else None}, pre_action_positions has unit={str(unit_id) in pre_action_positions}")
                                # CRITICAL: Use semantic action destination from result (set by movement handler)
                                # NO FALLBACK to action - result must contain toCol/toRow (set by movement_destination_selection_handler)
                                if not isinstance(result, dict):
                                    raise TypeError(f"result must be a dict for move action, got {type(result).__name__}")
                                dest_col = result.get("toCol")
                                dest_row = result.get("toRow")
                                if dest_col is None or dest_row is None:
                                    raise ValueError(f"Move action missing destination in result: result.toCol={dest_col}, result.toRow={dest_row}, result keys={list(result.keys())}")
                                # CRITICAL DEBUG: Log exact values from result AND action
                                from engine.game_utils import add_console_log, safe_print
                                action_dest_col = action.get("destCol") if isinstance(action, dict) else None
                                action_dest_row = action.get("destRow") if isinstance(action, dict) else None
                                debug_msg = f"[W40K_CORE DEBUG] E{pre_action_episode} T{pre_action_turn} Unit {unit_id}: result.toCol={dest_col} result.toRow={dest_row} action.destCol={action_dest_col} action.destRow={action_dest_row} result keys={list(result.keys())}"
                                add_console_log(self.game_state, debug_msg)
                                safe_print(self.game_state, debug_msg)
                                end_pos = (dest_col, dest_row)
                            action_details.update({
                                "start_pos": start_pos,
                                "end_pos": end_pos,
                                "col": dest_col,  # Use semantic action destination
                                "row": dest_row,  # Use semantic action destination
                                "unit_with_coords": f"{unit_id}({dest_col},{dest_row})"  # CRITICAL FIX: Update with correct destination coordinates
                            })
                            

                        if action_type == "advance":
                            # ADVANCE_IMPLEMENTATION: Handle advance action logging (similar to move)
                            # CRITICAL: No fallbacks - require explicit coordinates
                            if str(unit_id) not in pre_action_positions:
                                raise ValueError(f"Advance action missing start position in pre_action_positions: unit_id={unit_id}")
                            start_pos = pre_action_positions[str(unit_id)]
                            # Use result destination (from advance handler) or action, no fallback to updated_unit
                            if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
                                dest_col = result.get("toCol")
                                dest_row = result.get("toRow")
                            elif isinstance(action, dict) and action.get("destCol") is not None and action.get("destRow") is not None:
                                dest_col = action.get("destCol")
                                dest_row = action.get("destRow")
                            else:
                                raise ValueError(f"Advance action missing destination: result.toCol={result.get('toCol') if isinstance(result, dict) else None}, result.toRow={result.get('toRow') if isinstance(result, dict) else None}, action.destCol={action.get('destCol') if isinstance(action, dict) else None}, action.destRow={action.get('destRow') if isinstance(action, dict) else None}")
                            end_pos = (dest_col, dest_row)
                            action_details.update({
                                "start_pos": start_pos,
                                "end_pos": end_pos,
                                "col": dest_col,
                                "row": dest_row,
                                "advance_range": result.get("advance_range"),  # Include advance roll
                                "unit_with_coords": f"{unit_id}({dest_col},{dest_row})"  # CRITICAL FIX: Update with correct destination coordinates
                            })

                        # shoot actions now use all_attack_results (like combat) - handled in specialized block above
                        # charge and combat have specialized logging with early return
                        if action_type == "charge":
                            # Add charge-specific data with position info for step logger
                            # CRITICAL: No fallbacks - require explicit coordinates
                            if str(unit_id) not in pre_action_positions:
                                raise ValueError(f"Charge action missing start position in pre_action_positions: unit_id={unit_id}")
                            start_pos = pre_action_positions[str(unit_id)]
                            # Get destination from result (populated by charge handler) or action, no fallback to updated_unit
                            if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
                                dest_col = result.get("toCol")
                                dest_row = result.get("toRow")
                            elif isinstance(action, dict) and action.get("destCol") is not None and action.get("destRow") is not None:
                                dest_col = action.get("destCol")
                                dest_row = action.get("destRow")
                            else:
                                raise ValueError(f"Charge action missing destination: result.toCol={result.get('toCol') if isinstance(result, dict) else None}, result.toRow={result.get('toRow') if isinstance(result, dict) else None}, action.destCol={action.get('destCol') if isinstance(action, dict) else None}, action.destRow={action.get('destRow') if isinstance(action, dict) else None}")
                            end_pos = (dest_col, dest_row)
                            target_id_from_result = result.get("targetId")
                            action_details.update({
                                "target_id": target_id_from_result,
                                "start_pos": start_pos,
                                "end_pos": end_pos,
                                "charge_roll": result.get("charge_roll"),  # Add the actual 2d6 roll
                                "unit_with_coords": f"{unit_id}({dest_col},{dest_row})"  # CRITICAL FIX: Update with correct destination coordinates
                            })

                            # Add reward and log for charge action
                            step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
                            action_details["reward"] = step_reward
                            
                            # CRITICAL FIX: Get target coordinates from game_state
                            # Target position should not change during charge execution
                            # Capture coordinates immediately after getting targetId from result
                            target_id = action_details.get("target_id")
                            if target_id:
                                target_unit = self._get_unit_by_id(str(target_id))
                                if target_unit:
                                    # Capture target coordinates - these should be stable (targets don't move during opponent's turn)
                                    action_details["target_coords"] = (int(target_unit["col"]), int(target_unit["row"]))

                            # Déterminer step_increment selon le type d'action et success
                            # Pour les actions qui incrémentent episode_steps (ligne 642), step_increment = success
                            step_increment = success
                            
                            self.step_logger.log_action(
                                unit_id=updated_unit["id"],
                                action_type=action_type,
                                phase=pre_action_phase,
                                player=pre_action_player,
                                success=success,
                                step_increment=step_increment,
                                action_details=action_details
                            )

                        elif action_type == "charge_fail":
                            # Add charge_fail-specific data for step logger
                            # CRITICAL: No fallbacks - require explicit coordinates
                            if str(unit_id) not in pre_action_positions:
                                raise ValueError(f"Charge_fail missing start position in pre_action_positions: unit_id={unit_id}")
                            start_pos = pre_action_positions[str(unit_id)]
                            # For failed charges, end_pos is the intended destination (from result, action, or error)
                            end_pos = result.get("end_pos")
                            if end_pos is None:
                                # Try action as fallback
                                if isinstance(action, dict) and action.get("destCol") is not None and action.get("destRow") is not None:
                                    end_pos = (action.get("destCol"), action.get("destRow"))
                                else:
                                    # Unit didn't move, so end_pos should equal start_pos, but we require explicit value
                                    raise ValueError(f"Charge_fail missing end_pos: result.end_pos={result.get('end_pos')}, action.destCol={action.get('destCol') if isinstance(action, dict) else None}, action.destRow={action.get('destRow') if isinstance(action, dict) else None}")
                            
                            # CRITICAL: No default values - require explicit charge_failed_reason
                            charge_failed_reason = result.get("charge_failed_reason")
                            if charge_failed_reason is None:
                                raise ValueError(f"Charge_fail missing charge_failed_reason: unit_id={unit_id}, result keys={list(result.keys())}")
                            
                            action_details.update({
                                "target_id": result.get("targetId"),
                                "charge_roll": result.get("charge_roll"),
                                "charge_failed_reason": charge_failed_reason,
                                "start_pos": start_pos,  # Position actuelle (from) - unit didn't move
                                "end_pos": end_pos,  # Destination prévue (to)
                                "unit_with_coords": f"{unit_id}({start_pos[0]},{start_pos[1]})"  # CRITICAL FIX: Unit didn't move, use start_pos
                            })

                            # Add reward and log for failed charge action
                            step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
                            action_details["reward"] = step_reward

                            # Déterminer step_increment selon le type d'action et success
                            # Pour charge_fail, step_increment = success (False car action échouée)
                            # Mais selon AI_TURN.md, les actions échouées n'incrémentent pas episode_steps (ligne 642)
                            step_increment = success
                            
                            self.step_logger.log_action(
                                unit_id=updated_unit["id"],
                                action_type=action_type,
                                phase=pre_action_phase,
                                player=pre_action_player,
                                success=success,
                                step_increment=step_increment,
                                action_details=action_details
                            )

                        elif action_type in ["combat", "shoot"]:
                            # Log combat or shoot action - handlers MUST return all_attack_results complete
                            all_attack_results = result.get("all_attack_results", [])
                            
                            if not all_attack_results:
                                # No attack results - check if waiting for player input
                                waiting_for_player = result.get("waiting_for_player", False)
                                if waiting_for_player:
                                    # Waiting for player to select target - no attacks executed yet
                                    # Skip logging for now, will be logged when target is selected
                                    pass
                                else:
                                    # This is an error - combat/shoot action should have attack results
                                    raise ValueError(
                                        f"{action_type} action missing all_attack_results - handlers must return complete data. "
                                        f"unit_id={unit_id}, result keys={list(result.keys())}"
                                    )
                            else:
                                # Log EACH attack individually for proper step log output
                                step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)

                                for i, attack_result in enumerate(all_attack_results):
                                    # CRITICAL: Validate attack_result has all required fields
                                    required_fields = ["hit_roll", "wound_roll", "save_roll", "damage", "hit_success", "wound_success", "save_success", "hit_target", "wound_target", "save_target", "target_died", "weapon_name"]
                                    missing_fields = [field for field in required_fields if field not in attack_result]
                                    if missing_fields:
                                        raise KeyError(
                                            f"attack_result[{i}] in all_attack_results missing required fields: {missing_fields}. "
                                            f"attack_result keys: {list(attack_result.keys())}. "
                                            f"action_type={action_type}, unit_id={unit_id}"
                                        )
                                    
                                    # CRITICAL: Use shooterId from attack_result if available, otherwise fallback to unit_id from result
                                    # This ensures we log the correct unit that actually performed the attack
                                    actual_shooter_id = attack_result.get("shooterId", unit_id)
                                    target_id = attack_result.get("targetId", result.get("targetId"))
                                    
                                    # Validate that actual_shooter_id matches the unit_id from result
                                    if str(actual_shooter_id) != str(unit_id):
                                        # Log warning but continue - this indicates a potential bug
                                        episode = self.game_state.get("episode_number", "?")
                                        turn = self.game_state.get("turn", "?")
                                        from engine.game_utils import add_console_log, safe_print
                                        warning_msg = f"[CRITICAL LOGGING BUG] E{episode} T{turn} shoot logging: attack_result.shooterId={actual_shooter_id} but result.unitId={unit_id} - using shooterId from attack_result"
                                        add_console_log(self.game_state, warning_msg)
                                        safe_print(self.game_state, warning_msg)
                                    
                                    # Get actual shooter unit for coordinates
                                    actual_shooter_unit = self._get_unit_by_id(str(actual_shooter_id)) if actual_shooter_id else updated_unit
                                    target_unit = self._get_unit_by_id(str(target_id)) if target_id else None
                                    target_coords = None
                                    if target_unit:
                                        target_coords = (target_unit["col"], target_unit["row"])
                                    
                                    # CRITICAL FIX: Use pre_action_positions for actual shooter (not unit_id from result)
                                    # This ensures consistent position logging and avoids using stale positions
                                    if str(actual_shooter_id) in pre_action_positions:
                                        unit_col, unit_row = pre_action_positions[str(actual_shooter_id)]
                                    elif actual_shooter_unit:
                                        # Fallback to actual_shooter_unit position
                                        unit_col, unit_row = actual_shooter_unit['col'], actual_shooter_unit['row']
                                    else:
                                        # Last resort: use updated_unit position
                                        unit_col, unit_row = updated_unit['col'], updated_unit['row']
                                    
                                    attack_details = {
                                        "current_turn": pre_action_turn,
                                        "current_episode": pre_action_episode,  # CRITICAL: Use episode captured BEFORE action execution
                                        "unit_with_coords": f"{actual_shooter_id}({unit_col},{unit_row})",
                                        "action": action,
                                        "target_id": target_id,
                                        "target_coords": target_coords,
                                        "hit_roll": attack_result["hit_roll"],
                                        "wound_roll": attack_result["wound_roll"],
                                        "save_roll": attack_result["save_roll"],
                                        "damage_dealt": attack_result["damage"],
                                        "hit_result": "HIT" if attack_result["hit_success"] else "MISS",
                                        "wound_result": "WOUND" if attack_result["wound_success"] else "FAIL",
                                        "save_result": "SAVED" if attack_result["save_success"] else "FAIL",
                                        "hit_target": attack_result["hit_target"],
                                        "wound_target": attack_result["wound_target"],
                                        "save_target": attack_result["save_target"],
                                        "target_died": attack_result["target_died"],
                                        "weapon_name": attack_result["weapon_name"],
                                        "reward": step_reward if i == 0 else 0.0
                                    }
                                    
                                    # Déterminer step_increment selon le type d'action et success
                                    # Pour combat/shoot, step_increment seulement pour la première attaque ET si success
                                    step_increment = (i == 0) and success
                                    
                                    self.step_logger.log_action(
                                        unit_id=actual_shooter_id,  # CRITICAL: Use actual shooter ID from attack_result
                                        action_type=action_type,
                                        phase=pre_action_phase,
                                        player=pre_action_player,
                                        success=success,
                                        step_increment=step_increment,
                                        action_details=attack_details
                                    )
                        else:
                            # Non-specialized actions (move, wait)
                            # charge, combat, and shoot have their own logging above with specialized multi-attack handling
                            # Use pre-captured phase for accurate logging (phase may have changed during action)

                            # CRITICAL FIX: For move actions, ensure unit_with_coords uses destination coordinates, not current unit position
                            if action_type == "move" and "end_pos" in action_details:
                                end_col, end_row = action_details["end_pos"]
                                # CRITICAL DEBUG: Log exact values being used
                                from engine.game_utils import add_console_log, safe_print
                                debug_msg = f"[W40K_CORE DEBUG] E{action_details.get('current_episode', '?')} T{action_details.get('current_turn', '?')} Unit {unit_id}: end_pos=({end_col},{end_row}) unit_with_coords before={action_details.get('unit_with_coords', 'N/A')}"
                                add_console_log(self.game_state, debug_msg)
                                safe_print(self.game_state, debug_msg)
                                action_details["unit_with_coords"] = f"{unit_id}({end_col},{end_row})"
                                debug_msg2 = f"[W40K_CORE DEBUG] E{action_details.get('current_episode', '?')} T{action_details.get('current_turn', '?')} Unit {unit_id}: unit_with_coords after={action_details['unit_with_coords']}"
                                add_console_log(self.game_state, debug_msg2)
                                safe_print(self.game_state, debug_msg2)

                            # Calculate reward normally
                            step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)
                            action_details["reward"] = step_reward

                            # Déterminer step_increment selon le type d'action et success
                            # Pour les autres actions, step_increment = success (cohérent avec ligne 642)
                            step_increment = success

                            # CRITICAL DEBUG: Log exact values just before log_action
                            if action_type == "move":
                                from engine.game_utils import add_console_log, safe_print
                                debug_msg = f"[W40K_CORE DEBUG] E{action_details.get('current_episode', '?')} T{action_details.get('current_turn', '?')} Unit {unit_id}: BEFORE log_action - unit_with_coords={action_details.get('unit_with_coords', 'N/A')} end_pos={action_details.get('end_pos', 'N/A')} col={action_details.get('col', 'N/A')} row={action_details.get('row', 'N/A')}"
                                add_console_log(self.game_state, debug_msg)
                                safe_print(self.game_state, debug_msg)

                            self.step_logger.log_action(
                                unit_id=updated_unit["id"],
                                action_type=action_type,
                                phase=pre_action_phase,
                                player=pre_action_player,
                                success=success,
                                step_increment=step_increment,
                                action_details=action_details
                            )
            except Exception as e:
                # CRITICAL: Logging errors must NOT interrupt action execution
                # Log the error but continue with action processing
                import traceback
                from engine.game_utils import add_console_log, safe_print
                episode = self.game_state.get("episode_number", "?")
                turn = self.game_state.get("turn", "?")
                phase = self.game_state.get("phase", "?")
                error_msg = f"[STEP LOGGER ERROR] E{episode} T{turn} {phase}: Logging failed but action continues - {type(e).__name__}: {str(e)}"
                add_console_log(self.game_state, error_msg)
                safe_print(self.game_state, error_msg)
                # Don't re-raise - let action execution continue
        
        # Auto-advance to next phase when current phase completes
        # Loop to handle cascading empty phases (e.g., charge -> fight -> move if all empty)
        # CRITICAL: This must happen AFTER logging to allow logging of actions before phase transitions
        max_cascade = 10  # Prevent infinite loops
        cascade_count = 0
        while success and result.get("phase_complete") and result.get("next_phase") and cascade_count < max_cascade:
            next_phase = result["next_phase"]
            cascade_count += 1

            from engine.game_utils import add_console_log
            add_console_log(self.game_state, f"🔄 PHASE TRANSITION: {current_phase} -> {next_phase} (cascade #{cascade_count})")

            # Initialize next phase using phase handlers
            phase_init_result = None
            if next_phase == "command":
                phase_init_result = command_handlers.command_phase_start(self.game_state)
            elif next_phase == "shoot":
                phase_init_result = shooting_handlers.shooting_phase_start(self.game_state)
            elif next_phase == "charge":
                phase_init_result = charge_handlers.charge_phase_start(self.game_state)
            elif next_phase == "fight":
                phase_init_result = fight_handlers.fight_phase_start(self.game_state)
            elif next_phase == "move":
                phase_init_result = movement_handlers.movement_phase_start(self.game_state)

            add_console_log(self.game_state, f"🔄 PHASE NOW: {self.game_state.get('phase', 'UNKNOWN')}")

            # If phase_start returns phase_complete, cascade to next phase
            if phase_init_result and phase_init_result.get("phase_complete") and phase_init_result.get("next_phase"):
                # CRITICAL: Preserve combat action data before replacing result
                # When fight phase completes and transitions to next phase, we must preserve
                # the combat action data (action, unitId, all_attack_results) for logging
                preserved_combat_data = {}
                combat_keys = ["action", "unitId", "all_attack_results", "targetId", "attack_result", "target_died", "reason", "phase"]
                for key in combat_keys:
                    if key in result:
                        preserved_combat_data[key] = result[key]
                
                result = phase_init_result  # Update result for next iteration
                
                # CRITICAL: Restore preserved combat data for logging
                for key, value in preserved_combat_data.items():
                    if value is not None:  # Only restore non-None values
                        result[key] = value
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
                    # CRITICAL: No default values - require explicit coordinates for debug check
                    if "destCol" in action and "destRow" in action:
                        expected_col = action["destCol"]
                        expected_row = action["destRow"]
                        if expected_col == unit["col"] and expected_row == unit["row"]:
                            pass
                    # If destCol/destRow missing, skip debug check (not an error, just incomplete debug data)
        
        # CRITICAL: No workaround for invalid_destination - let error propagate
        # If destination is invalid, the error should be raised, not masked by auto-skip
        # The agent should learn not to select invalid destinations
        
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

    def _process_command_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process command phase actions."""
        unit_id = action.get("unitId")
        current_unit = None
        if unit_id:
            current_unit = self._get_unit_by_id(unit_id)
        
        success, result = command_handlers.execute_action(self.game_state, current_unit, action, self.config)
        return success, result
    
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
        if self.game_state["current_player"] == 1:
            self.game_state["current_player"] = 2
        elif self.game_state["current_player"] == 2:
            self.game_state["current_player"] = 1
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
        dead_units_by_player = {}
        
        for unit in self.game_state["units"]:
            player = unit["player"]
            if player not in living_units_by_player:
                living_units_by_player[player] = 0
            if player not in dead_units_by_player:
                dead_units_by_player[player] = 0
            
            if unit["HP_CUR"] > 0:
                living_units_by_player[player] += 1
            else:
                dead_units_by_player[player] += 1
        
        # Check if any player has no living units (elimination condition)
        players_with_no_living_units = [pid for pid, count in living_units_by_player.items() if count == 0]
        game_over_by_elimination = len(players_with_no_living_units) > 0
        
        # Game is over if any player has no living units
        return game_over_by_elimination
    
    
    def _determine_winner(self) -> Optional[int]:
        """Determine winner - delegates to state_manager for full victory logic."""
        return self.state_manager.determine_winner(self.game_state)

    def _determine_winner_with_method(self) -> tuple:
        """Determine winner AND win method - delegates to state_manager."""
        return self.state_manager.determine_winner_with_method(self.game_state)
    
    
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

    def _reload_scenario(self, scenario_file: str):
        """Reload scenario data for random scenario selection during training.

        This method is called during reset() when random_scenario_mode is enabled.
        It reloads units, walls, and objectives from the selected scenario file.
        """
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()

        # Load scenario data (units + optional terrain)
        scenario_result = self._load_units_from_scenario(scenario_file, self.unit_registry)
        scenario_units = scenario_result["units"]

        # Determine wall_hexes: use scenario if provided, otherwise fallback to board config
        if scenario_result.get("wall_hexes") is not None:
            self._scenario_wall_hexes = scenario_result["wall_hexes"]
        else:
            if "default" in board_config:
                self._scenario_wall_hexes = board_config["default"].get("wall_hexes", [])
            else:
                self._scenario_wall_hexes = board_config.get("wall_hexes", [])

        # Determine objectives: use scenario if provided, otherwise fallback to board config
        if scenario_result.get("objectives") is not None:
            self._scenario_objectives = scenario_result["objectives"]
        else:
            if "default" in board_config:
                self._scenario_objectives = board_config["default"].get("objectives", board_config["default"].get("objective_hexes", []))
            else:
                self._scenario_objectives = board_config.get("objectives", board_config.get("objective_hexes", []))

        # Extract scenario name from file path for logging
        scenario_name = scenario_file
        if scenario_name and "/" in scenario_name:
            scenario_name = scenario_name.split("/")[-1].replace(".json", "")
        elif scenario_name and "\\" in scenario_name:
            scenario_name = scenario_name.split("\\")[-1].replace(".json", "")

        # Update config with new scenario data
        # CRITICAL: Store ORIGINAL positions in config as a deepcopy (immutable reference)
        # This prevents position corruption when game_state units are modified during gameplay
        self.config["units"] = copy.deepcopy(scenario_units)
        self.config["name"] = scenario_name

        # Reinitialize game_state units with a SEPARATE deepcopy
        # This ensures game_state["units"] is independent from config["units"]
        self.game_state["units"] = copy.deepcopy(scenario_units)

        # Update wall_hexes and objectives in game_state if present
        if "wall_hexes" in self.game_state:
            self.game_state["wall_hexes"] = self._scenario_wall_hexes
        if "objectives" in self.game_state:
            self.game_state["objectives"] = self._scenario_objectives


# ============================================================================
# KEEP AT END OF FILE
# ============================================================================

if __name__ == "__main__":
    print("W40K Engine requires proper config from training system - no standalone execution")