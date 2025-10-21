#!/usr/bin/env python3
"""
w40k_engine.py - AI_TURN.md Compliant W40K Game Engine with Gym Interface
ZERO TOLERANCE for architectural violations

Core Principles:
- Sequential activation (ONE unit per gym step)
- Built-in step counting (NOT retrofitted)
- Phase completion by eligibility ONLY
- UPPERCASE field validation enforced
- Single source of truth (one game_state object)
"""

import os
import torch
import json
import random
import gymnasium as gym
import numpy as np
from typing import Dict, List, Tuple, Set, Optional, Any

# AI_IMPLEMENTATION.md: Import phase handlers for delegation pattern
from .phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers

# Import combat calculation utilities from shooting_handlers (single source of truth)
from .phase_handlers.shooting_handlers import _calculate_save_target, _calculate_wound_target


class W40KEngine(gym.Env):
    """
    AI_TURN.md compliant W40K game engine with gym.Env interface.
    
    ARCHITECTURAL COMPLIANCE:
    - Single source of truth: Only one game_state object exists
    - Built-in step counting: episode_steps incremented in ONE location only
    - Sequential activation: ONE unit processed per gym step
    - Phase completion: Based on eligibility, NOT arbitrary step counts
    - UPPERCASE fields: All unit stats use proper naming convention
    - Gym interface: Compatible with stable-baselines3 without architectural violations
    """
    
    def __init__(self, config=None, rewards_config=None, training_config_name=None, 
                controlled_agent=None, active_agents=None, scenario_file=None, 
                unit_registry=None, quiet=False, gym_training_mode=False, **kwargs):
        """Initialize W40K engine with AI_TURN.md compliance - training system compatible."""
        
        # Store gym training mode for handler access
        self.gym_training_mode = gym_training_mode
        
        # Handle both new engine format (single config) and old training system format
        if config is None:
            # Build config from training system parameters
            from config_loader import get_config_loader
            config_loader = get_config_loader()
            
            # Load rewards configuration like gym40k.py
            self.rewards_config = config_loader.load_rewards_config(rewards_config)
            if not self.rewards_config:
                raise RuntimeError("Failed to load rewards configuration from config_loader - check config/rewards_config.json")
            
            # Load training configuration for turn limits
            self.training_config = config_loader.load_training_config(training_config_name)
            if not self.training_config:
                raise RuntimeError(f"Failed to load training configuration: {training_config_name}")
            
            # Load base configuration
            board_config = config_loader.get_board_config()
            
            # CRITICAL FIX: Initialize PvE mode BEFORE config creation
            # Training mode: no PvE mode needed
            # PvE mode: will be set later in constructor
            pve_mode_value = False  # Default for training
            
            self.config = {
                "board": board_config,
                "units": self._load_units_from_scenario(scenario_file, unit_registry),
                "rewards_config": rewards_config,
                "training_config_name": training_config_name,
                "training_config": self.training_config,
                "controlled_agent": controlled_agent,
                "active_agents": active_agents,
                "quiet": quiet,
                "gym_training_mode": gym_training_mode,  # CRITICAL: Pass flag to handlers
                "pve_mode": pve_mode_value  # CRITICAL: Add PvE mode for handler detection
            }
        else:
            # Use provided config directly and add gym_training_mode
            self.config = config.copy()
            self.config["gym_training_mode"] = gym_training_mode
            # CRITICAL: Ensure pve_mode is in config for handler delegation
            if "pve_mode" not in self.config:
                self.config["pve_mode"] = config.get("pve_mode", False)
        
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
            
            # Board state - handle both config formats
            "board_cols": self.config["board"]["default"]["cols"] if "default" in self.config["board"] else self.config["board"]["cols"],
            "board_rows": self.config["board"]["default"]["rows"] if "default" in self.config["board"] else self.config["board"]["rows"],
            "wall_hexes": set(map(tuple, self.config["board"]["default"]["wall_hexes"] if "default" in self.config["board"] else self.config["board"]["wall_hexes"]))
        }
        
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
        
        # Load AI model for PvE mode
        if self.is_pve_mode:
            self._load_ai_model_for_pve()
    
    def _load_ai_model_for_pve(self):
        """Load trained AI model for PvE Player 2 - with diagnostic logging."""
        # Only show debug output in debug training mode
        debug_mode = hasattr(self, 'training_config') and self.training_config and \
                     self.config.get('training_config_name') == 'debug'
        
        if debug_mode:
            print(f"DEBUG: _load_ai_model_for_pve called")
        
        try:
            from sb3_contrib import MaskablePPO
            from sb3_contrib.common.wrappers import ActionMasker
            if debug_mode:
                print(f"DEBUG: MaskablePPO import successful")
            
            # Get AI model key from unit registry
            ai_model_key = "SpaceMarine_Infantry_Troop_RangedSwarm"  # Default
            if debug_mode:
                print(f"DEBUG: Default AI model key: {ai_model_key}")
            
            if self.unit_registry:
                player1_units = [u for u in self.game_state["units"] if u["player"] == 1]
                if player1_units:
                    unit_type = player1_units[0]["unitType"]
                    ai_model_key = self.unit_registry.get_model_key(unit_type)
            
            model_path = f"ai/models/current/model_{ai_model_key}.zip"
            if debug_mode:
                print(f"DEBUG: Model path: {model_path}")
                print(f"DEBUG: Model exists: {os.path.exists(model_path)}")
            
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"AI model required for PvE mode not found: {model_path}")
            
            # Wrap self with ActionMasker for MaskablePPO compatibility
            def mask_fn(env):
                return env.get_action_mask()
            
            masked_self = ActionMasker(self, mask_fn)
            
            # Load model with masked environment
            self._ai_model = MaskablePPO.load(model_path, env=masked_self)
            print(f"DEBUG: AI model loaded successfully")
            if not self.quiet:
                print(f"PvE: Loaded AI model: {ai_model_key}")
                
        except Exception as e:
            print(f"DEBUG: _load_ai_model_for_pve exception: {e}")
            print(f"DEBUG: Exception type: {type(e).__name__}")
            # Set _ai_model to None on any failure
            self._ai_model = None
            raise  # Re-raise to see the full error
    
    def _initialize_units(self):
        """Initialize units with UPPERCASE field validation."""
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field")
        unit_configs = self.config["units"]
        
        for unit_config in unit_configs:
            unit = self._create_unit(unit_config)
            self._validate_uppercase_fields(unit)
            self.game_state["units"].append(unit)
    
    def _create_unit(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create unit with AI_TURN.md compliant fields."""
        return {
            # Identity
            "id": config["id"],
            "player": config["player"],
            "unitType": config["unitType"],  # AI_TURN.md: NO DEFAULTS - must be provided
            
            # Position
            "col": config["col"],
            "row": config["row"],
            
            # UPPERCASE STATS (AI_TURN.md requirement) - NO DEFAULTS
            "HP_CUR": config["HP_CUR"],
            "HP_MAX": config["HP_MAX"],
            "MOVE": config["MOVE"],
            "T": config["T"],
            "ARMOR_SAVE": config["ARMOR_SAVE"],
            "INVUL_SAVE": config["INVUL_SAVE"],
            
            # Ranged fight stats - NO DEFAULTS
            "RNG_NB": config["RNG_NB"],
            "RNG_RNG": config["RNG_RNG"],
            "RNG_ATK": config["RNG_ATK"],
            "RNG_STR": config["RNG_STR"],
            "RNG_DMG": config["RNG_DMG"],
            "RNG_AP": config["RNG_AP"],
            
            # Close fight stats - NO DEFAULTS
            "CC_NB": config["CC_NB"],
            "CC_RNG": config["CC_RNG"],
            "CC_ATK": config["CC_ATK"],
            "CC_STR": config["CC_STR"],
            "CC_DMG": config["CC_DMG"],
            "CC_AP": config["CC_AP"],
            
            # Required stats - NO DEFAULTS
            "LD": config["LD"],
            "OC": config["OC"],
            "VALUE": config["VALUE"],
            "ICON": config["ICON"],
            "ICON_SCALE": config["ICON_SCALE"],
            
            # AI_TURN.md action tracking fields
            "SHOOT_LEFT": config["SHOOT_LEFT"],
            "ATTACK_LEFT": config["ATTACK_LEFT"]
        }
    
    def _validate_uppercase_fields(self, unit: Dict[str, Any]):
        """Validate unit uses UPPERCASE field naming convention."""
        required_uppercase = {
            "HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
            "RNG_NB", "RNG_RNG", "RNG_ATK", "RNG_STR", "RNG_DMG", "RNG_AP",
            "CC_NB", "CC_RNG", "CC_ATK", "CC_STR", "CC_DMG", "CC_AP",
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE",
            "SHOOT_LEFT", "ATTACK_LEFT"
        }
        
        for field in required_uppercase:
            if field not in unit:
                raise ValueError(f"Unit {unit['id']} missing required UPPERCASE field: {field}")
    
    # ===== CORE ENGINE METHODS (Gym Interface) =====
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Execute gym action with built-in step counting - gym.Env interface.
        """
        # CRITICAL: Check turn limit BEFORE processing any action
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and self.game_state["turn"] > max_turns:
                # Turn limit exceeded - return terminated episode immediately
                observation = self._build_observation()
                info = {"turn_limit_exceeded": True, "winner": self._determine_winner()}
                return observation, 0.0, True, False, info
        
        # Check for game termination before action
        self.game_state["game_over"] = self._check_game_over()
        
        # Convert gym integer action to semantic action
        semantic_action = self._convert_gym_action(action)
        
        # Process semantic action with AI_TURN.md compliance
        action_result = self._process_semantic_action(semantic_action)
        if isinstance(action_result, tuple) and len(action_result) == 2:
            success, result = action_result
        else:
            success, result = True, action_result
        
        # BUILT-IN STEP COUNTING - AFTER validation, only for successful actions
        if success:
            self.game_state["episode_steps"] += 1
        if isinstance(action_result, tuple) and len(action_result) == 2:
            success, result = action_result
        else:
            success, result = True, action_result
        
        # Capture unit position BEFORE action execution for accurate logging
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
        
        # Log action ONLY if it's a real agent action with valid unit
        if (self.step_logger and self.step_logger.enabled and success):
           
            # AI_TURN.md COMPLIANCE: Direct field access
            action_type = semantic_action["action"] if "action" in semantic_action else None
            unit_id = semantic_action["unitId"] if "unitId" in semantic_action else None
           
            # Filter out system actions and invalid entries
            if (action_type in ["move", "shoot", "charge", "combat"] and
                unit_id != "none" and unit_id != "SYSTEM"):
               
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
                    if semantic_action.get("action") == "move":
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
                    elif semantic_action.get("action") == "shoot":
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
                    
                    # Capture phase AFTER action execution for accurate logging
                    post_action_phase = self._get_action_phase_for_logging(semantic_action.get("action"))
                    
                    self.step_logger.log_action(
                        unit_id=updated_unit["id"],
                        action_type=semantic_action.get("action"), 
                        phase=post_action_phase,
                        player=self.game_state["current_player"],
                        success=success,
                        step_increment=True,
                        action_details=action_details
                    )
        
        # Convert to gym format
        observation = self._build_observation()
        reward = self._calculate_reward(success, result)
        terminated = self.game_state["game_over"]
        truncated = False
        info = result.copy() if isinstance(result, dict) else {}
        info["success"] = success
        
        # Add winner info when game ends
        if terminated:
            info["winner"] = self._determine_winner()
        else:
            info["winner"] = None
        
        # Update position cache for movement_direction feature
        for unit in self.game_state["units"]:
            if "id" not in unit:
                raise KeyError(f"Unit missing required 'id' field: {unit}")
            if "col" not in unit or "row" not in unit:
                raise KeyError(f"Unit missing required position fields: {unit}")
            unit_id = str(unit["id"])
            self.last_unit_positions[unit_id] = (unit["col"], unit["row"])
            
        return observation, reward, terminated, truncated, info
    
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
            ai_semantic_action = self._make_ai_decision()
            
            # Execute through SAME path as humans
            return self._process_semantic_action(ai_semantic_action)
            
        except Exception as e:
            return False, {"error": "ai_decision_failed", "message": str(e)}
    
    
    
    def _make_ai_decision(self) -> Dict[str, Any]:
        """
        AI decision logic - replaces human clicks with model predictions.
        Uses SAME handler paths as humans after decision is made.
        """
        # Get observation for AI model
        obs = self._build_observation()
        
        # CRITICAL DEBUG: Check action mask
        action_mask = self.get_action_mask()
        valid_actions = [i for i in range(12) if action_mask[i]]
        
        # Get AI model prediction WITH action mask
        prediction_result = self._ai_model.predict(obs, action_masks=action_mask, deterministic=True)
        
        if isinstance(prediction_result, tuple) and len(prediction_result) >= 1:
            action_int = prediction_result[0]
        elif hasattr(prediction_result, 'item'):
            action_int = prediction_result.item()
        else:
            action_int = int(prediction_result)
        
        # CRITICAL DEBUG: Log AI decision
        current_phase = self.game_state["phase"]
        
        # Convert to semantic action using existing method
        semantic_action = self._convert_gym_action(action_int)
        
        # Ensure AI player context
        current_player = self.game_state["current_player"]
        if current_player == 1:  # AI player
            # Get eligible units from current phase pool
            current_phase = self.game_state["phase"]
            if current_phase == "move":
                if "move_activation_pool" not in self.game_state:
                    raise KeyError("game_state missing required 'move_activation_pool' field")
                eligible_pool = self.game_state["move_activation_pool"]
            elif current_phase == "shoot":
                if "shoot_activation_pool" not in self.game_state:
                    raise KeyError("game_state missing required 'shoot_activation_pool' field")
                eligible_pool = self.game_state["shoot_activation_pool"]
            else:
                eligible_pool = []
            
            # Find AI unit in pool
            ai_unit_id = None
            for unit_id in eligible_pool:
                unit = self._get_unit_by_id(str(unit_id))
                if unit and unit["player"] == 1:
                    ai_unit_id = str(unit_id)
                    break
            
            if ai_unit_id:
                semantic_action["unitId"] = ai_unit_id
            
        return semantic_action
    
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
            "charge_range_rolls": {}
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
        
        observation = self._build_observation()
        info = {"phase": self.game_state["phase"]}
        
        return observation, info
    
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action with detailed execution debugging.
        """
        current_phase = self.game_state["phase"]
                
        # Route to phase handlers with detailed logging
        if current_phase == "move":
            success, result = self._process_movement_phase(action)
            return success, result
        elif current_phase == "shoot":
            success, result = self._process_shooting_phase(action)
            return success, result
        elif current_phase == "charge":
            return self._process_charge_phase(action)
        elif current_phase == "fight":
            return self._process_fight_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}
    
    # ===== MOVEMENT PHASE IMPLEMENTATION =====
    
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
    
    # AI_IMPLEMENTATION.md: Movement logic delegated to movement_handlers.py
    # All movement validation and execution now handled by pure functions
    
    # ===== PHASE TRANSITION LOGIC =====
    
    def _shooting_phase_init(self):
        """AI_SHOOT.md EXACT: Pure delegation to handler"""
        # Handler manages everything including phase setting and pool building
        result = shooting_handlers.shooting_phase_start(self.game_state)
        
        # Check if phase should complete immediately (empty pool)
        if result.get("phase_complete"):
            self._advance_to_next_player()
    
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
    
    def _charge_phase_init(self):
        """Initialize charge phase per AI_TURN.md progression."""
        self.game_state["phase"] = "charge"
        self._phase_initialized = False  # Reset for charge phase
        # Clear previous phase activation pool
        self.game_state["shoot_activation_pool"] = []
    
    def _process_charge_phase(self, action: int) -> Tuple[bool, Dict[str, Any]]:
        """Placeholder for charge phase - implements AI_TURN.md decision tree."""
        # TODO: Implement charge phase logic
        self._advance_to_fight_phase()
        return self._process_fight_phase(action)
    
    def _advance_to_fight_phase(self):
        """Advance to fight phase per AI_TURN.md progression."""
        self.game_state["phase"] = "fight"
        self.game_state["fight_subphase"] = "charging_units"
    
    def _process_fight_phase(self, action: int) -> Tuple[bool, Dict[str, Any]]:
        """Placeholder for fight phase - implements AI_TURN.md sub-phases."""
        # TODO: Implement fight phase logic
        self._advance_to_next_player()
        return True, {"type": "phase_complete", "next_player": self.game_state["current_player"]}
    
    def _advance_to_next_player(self):
        """Advance to next player per AI_TURN.md turn progression."""
        # Player switching logic
        if self.game_state["current_player"] == 0:
            self.game_state["current_player"] = 1
        elif self.game_state["current_player"] == 1:
            self.game_state["current_player"] = 0
            self.game_state["turn"] += 1
        
        # Phase progression logic - simplified to move -> shoot -> move
        if self.game_state["phase"] == "move":
            self._shooting_phase_init()
        elif self.game_state["phase"] == "shoot":
            self._movement_phase_init()
        elif self.game_state["phase"] == "charge":
            self._movement_phase_init()
        elif self.game_state["phase"] == "fight":
            self._movement_phase_init()
    
    def _movement_phase_init(self):
        """Initialize movement phase using AI_MOVE.md delegation."""
        # AI_MOVE.md: Handler manages phase initialization
        movement_handlers.movement_phase_start(self.game_state)  
    
    def _tracking_cleanup(self):
        """Clear tracking sets at the VERY BEGINNING of movement phase."""
        self.game_state["units_moved"] = set()
        self.game_state["units_fled"] = set()
        self.game_state["units_shot"] = set()
        self.game_state["units_charged"] = set()
        self.game_state["units_attacked"] = set()
        self.game_state["move_activation_pool"] = []
    
    # ===== SHOOTING PHASE IMPLEMENTATION =====
    
    def _shooting_build_activation_pool_old(self):
        """Pure delegation to shooting_handlers for pool building."""
        eligible_units = shooting_handlers.shooting_build_activation_pool(self.game_state)
        
        # Add console log for web browser visibility only in non-training mode
        if not (self.is_training or self.quiet):
            self.game_state["console_logs"] = [
                f"SHOOT POOL BUILT: Player {self.game_state['current_player']} → Units: {eligible_units}"
            ]
        else:
            # Silent mode: update without console logs but use same eligibility rules
            if "console_logs" not in self.game_state:
                self.game_state["console_logs"] = []
        
        return eligible_units
        
    def _has_valid_shooting_targets(self, unit: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
        for enemy in self.game_state["units"]:
            if (enemy["player"] != unit["player"] and 
                enemy["HP_CUR"] > 0 and
                self._is_valid_shooting_target(unit, enemy)):
                return True
        return False
    
    def _is_valid_shooting_target(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
        """REMOVED: Redundant with handler. Use shooting_handlers._is_valid_shooting_target exclusively."""
        # AI_IMPLEMENTATION.md: Complete delegation to handler for consistency
        return shooting_handlers._is_valid_shooting_target(self.game_state, shooter, target)
    
    def _has_line_of_sight(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
        """Check line of sight between shooter and target using handler delegation."""
        # AI_IMPLEMENTATION.md: Delegate to shooting_handlers for consistency
        return shooting_handlers._has_line_of_sight(self.game_state, shooter, target)
    
    def _get_hex_line(self, start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
        """Get hex line using handler delegation."""
        # AI_IMPLEMENTATION.md: Delegate to shooting_handlers for consistency
        return shooting_handlers._get_accurate_hex_line(start_col, start_row, end_col, end_row)
    
    def _execute_shooting_action(self, unit: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """DEPRECATED: Use _process_shooting_phase instead for full handler delegation."""
        # Redirect to proper shooting phase handler
        return self._process_shooting_phase(action)
    
    def _attempt_shooting(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Attempt shooting with AI_TURN.md damage resolution."""
        
        # Validate target
        if not self._is_valid_shooting_target(shooter, target):
            return False, {"error": "invalid_target", "targetId": target["id"]}
        
        # Execute shots (RNG_NB shots per activation)
        total_damage = 0
        shots_fired = shooter["RNG_NB"]
        
        for shot in range(shots_fired):
            # Hit roll
            hit_roll = random.randint(1, 6)
            hit_target = 7 - shooter["RNG_ATK"]  # Convert attack stat to target number
            
            if hit_roll >= hit_target:
                # Wound roll
                wound_roll = random.randint(1, 6)
                wound_target = self._calculate_wound_target(shooter["RNG_STR"], target["T"])
                
                if wound_roll >= wound_target:
                    # Save roll
                    save_roll = random.randint(1, 6)
                    save_target = target["ARMOR_SAVE"] - shooter["RNG_AP"]
                    
                    # Check invulnerable save
                    if target["INVUL_SAVE"] < save_target:
                        save_target = target["INVUL_SAVE"]
                    
                    if save_roll < save_target:
                        # Damage dealt
                        damage = shooter["RNG_DMG"]
                        total_damage += damage
                        target["HP_CUR"] -= damage
                        
                        # Check if target dies
                        if target["HP_CUR"] <= 0:
                            target["HP_CUR"] = 0
                            break  # Stop shooting at dead target
        
        # Apply tracking
        self.game_state["units_shot"].add(shooter["id"])
        
        return True, {
            "action": "shoot",
            "shooterId": shooter["id"],
            "targetId": target["id"],
            "shotsFired": shots_fired,
            "totalDamage": total_damage,
            "targetHP": target["HP_CUR"]
        }
    
    def _calculate_wound_target(self, strength: int, toughness: int) -> int:
        """Calculate wound target number per W40K rules."""
        if strength >= toughness * 2:
            return 2
        elif strength > toughness:
            return 3
        elif strength == toughness:
            return 4
        elif strength * 2 <= toughness:
            return 6
        else:
            return 5
    
    # ===== UTILITY METHODS =====
    
    def _get_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state."""
        for unit in self.game_state["units"]:
            if unit["id"] == unit_id:
                return unit
        return None
    
    def _build_observation(self) -> np.ndarray:
        """
        Build asymmetric egocentric observation vector with R=25 perception radius.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.
        
        Structure (295 floats):
        - [0:10]    Global context (10 floats)
        - [10:18]   Active unit capabilities (8 floats)
        - [18:50]   Directional terrain (32 floats: 8 directions × 4 features)
        - [50:122]  Allied units (72 floats: 6 units × 12 features)
        - [122:260] Enemy units (138 floats: 6 units × 23 features)
        - [260:295] Valid targets (35 floats: 5 targets × 7 features)
        
        Asymmetric design: More complete information about enemies than allies.
        Agent discovers optimal tactical combinations through training.
        """
        obs = np.zeros(295, dtype=np.float32)
        
        # Get active unit (agent's current unit)
        active_unit = self._get_active_unit_for_observation()
        if not active_unit:
            # No active unit - return zero observation
            return obs
        
        # === SECTION 1: Global Context (10 floats) ===
        obs[0] = float(self.game_state["current_player"])
        obs[1] = {"move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}[self.game_state["phase"]]
        obs[2] = min(1.0, self.game_state["turn"] / 10.0)
        obs[3] = min(1.0, self.game_state["episode_steps"] / 100.0)
        obs[4] = active_unit["HP_CUR"] / active_unit["HP_MAX"]
        obs[5] = 1.0 if active_unit["id"] in self.game_state["units_moved"] else 0.0
        obs[6] = 1.0 if active_unit["id"] in self.game_state["units_shot"] else 0.0
        obs[7] = 1.0 if active_unit["id"] in self.game_state["units_attacked"] else 0.0
        
        # Count alive units for strategic awareness
        alive_friendlies = sum(1 for u in self.game_state["units"] 
                              if u["player"] == active_unit["player"] and u["HP_CUR"] > 0)
        alive_enemies = sum(1 for u in self.game_state["units"] 
                           if u["player"] != active_unit["player"] and u["HP_CUR"] > 0)
        obs[8] = alive_friendlies / max(1, self.max_nearby_units)
        obs[9] = alive_enemies / max(1, self.max_nearby_units)
        
        # === SECTION 2: Active Unit Capabilities (8 floats) ===
        obs[10] = active_unit["MOVE"] / 12.0  # Normalize by max expected (bikes)
        obs[11] = active_unit["RNG_RNG"] / 24.0
        obs[12] = active_unit["RNG_DMG"] / 5.0
        obs[13] = active_unit["RNG_NB"] / 10.0
        obs[14] = active_unit["CC_RNG"] / 6.0
        obs[15] = active_unit["CC_DMG"] / 5.0
        obs[16] = active_unit["T"] / 10.0
        obs[17] = active_unit["ARMOR_SAVE"] / 6.0
        
        # === SECTION 3: Directional Terrain Awareness (32 floats) ===
        self._encode_directional_terrain(obs, active_unit, base_idx=18)
        
        # === SECTION 4: Allied Units (72 floats) ===
        self._encode_allied_units(obs, active_unit, base_idx=50)
        
        # === SECTION 5: Enemy Units (138 floats) ===
        self._encode_enemy_units(obs, active_unit, base_idx=122)
        
        # === SECTION 6: Valid Targets (35 floats) ===
        self._encode_valid_targets(obs, active_unit, base_idx=260)
        
        return obs
    
    def _get_active_unit_for_observation(self) -> Optional[Dict[str, Any]]:
        """
        Get the active unit for observation encoding.
        AI_TURN.md COMPLIANCE: Uses activation pools (single source of truth).
        """
        current_phase = self.game_state["phase"]
        current_player = self.game_state["current_player"]
        
        # Get first eligible unit from current phase pool
        if current_phase == "move":
            pool = self.game_state.get("move_activation_pool", [])
        elif current_phase == "shoot":
            pool = self.game_state.get("shoot_activation_pool", [])
        elif current_phase == "charge":
            pool = self.game_state.get("charge_activation_pool", [])
        elif current_phase == "fight":
            pool = self.game_state.get("charging_activation_pool", [])
        else:
            pool = []
        
        # Get first unit from pool that belongs to current player
        for unit_id in pool:
            unit = self._get_unit_by_id(str(unit_id))
            if unit and unit["player"] == current_player:
                return unit
        
        # Fallback: return any alive unit from current player
        for unit in self.game_state["units"]:
            if unit["player"] == current_player and unit["HP_CUR"] > 0:
                return unit
        
        return None
    
    def _encode_directional_terrain(self, obs: np.ndarray, active_unit: Dict[str, Any], base_idx: int):
        """
        Encode terrain awareness in 8 cardinal directions.
        32 floats = 8 directions × 4 features per direction.
        """
        # 8 directions: N, NE, E, SE, S, SW, W, NW
        directions = [
            (0, -1),   # N
            (1, -1),   # NE
            (1, 0),    # E
            (1, 1),    # SE
            (0, 1),    # S
            (-1, 1),   # SW
            (-1, 0),   # W
            (-1, -1)   # NW
        ]
        
        for dir_idx, (dx, dy) in enumerate(directions):
            feature_base = base_idx + dir_idx * 4
            
            # Find nearest wall, friendly, enemy, and edge in this direction
            wall_dist = self._find_nearest_in_direction(active_unit, dx, dy, "wall")
            friendly_dist = self._find_nearest_in_direction(active_unit, dx, dy, "friendly")
            enemy_dist = self._find_nearest_in_direction(active_unit, dx, dy, "enemy")
            edge_dist = self._find_edge_distance(active_unit, dx, dy)
            
            # Normalize by perception radius
            obs[feature_base + 0] = min(1.0, wall_dist / self.perception_radius)
            obs[feature_base + 1] = min(1.0, friendly_dist / self.perception_radius)
            obs[feature_base + 2] = min(1.0, enemy_dist / self.perception_radius)
            obs[feature_base + 3] = min(1.0, edge_dist / self.perception_radius)
    
    def _find_nearest_in_direction(self, unit: Dict[str, Any], dx: int, dy: int, 
                                   search_type: str) -> float:
        """Find nearest object (wall/friendly/enemy) in given direction."""
        min_distance = 999.0
        
        if search_type == "wall":
            # Search walls in direction
            for wall_col, wall_row in self.game_state["wall_hexes"]:
                if self._is_in_direction(unit, wall_col, wall_row, dx, dy):
                    dist = self._calculate_hex_distance(unit["col"], unit["row"], wall_col, wall_row)
                    if dist < min_distance and dist <= self.perception_radius:
                        min_distance = dist
        
        elif search_type in ["friendly", "enemy"]:
            target_player = unit["player"] if search_type == "friendly" else 1 - unit["player"]
            for other_unit in self.game_state["units"]:
                if other_unit["HP_CUR"] <= 0:
                    continue
                if other_unit["player"] != target_player:
                    continue
                if other_unit["id"] == unit["id"]:
                    continue
                    
                if self._is_in_direction(unit, other_unit["col"], other_unit["row"], dx, dy):
                    dist = self._calculate_hex_distance(unit["col"], unit["row"], 
                                                        other_unit["col"], other_unit["row"])
                    if dist < min_distance and dist <= self.perception_radius:
                        min_distance = dist
        
        return min_distance if min_distance < 999.0 else self.perception_radius
    
    def _is_in_direction(self, unit: Dict[str, Any], target_col: int, target_row: int,
                        dx: int, dy: int) -> bool:
        """Check if target is roughly in the specified direction from unit."""
        delta_col = target_col - unit["col"]
        delta_row = target_row - unit["row"]
        
        # Rough directional check (within 45-degree cone)
        if dx == 0:  # North/South
            return abs(delta_col) <= abs(delta_row) and (delta_row * dy > 0)
        elif dy == 0:  # East/West
            return abs(delta_row) <= abs(delta_col) and (delta_col * dx > 0)
        else:  # Diagonal
            return (delta_col * dx > 0) and (delta_row * dy > 0)
    
    def _find_edge_distance(self, unit: Dict[str, Any], dx: int, dy: int) -> float:
        """Calculate distance to board edge in given direction."""
        if dx > 0:  # East
            edge_dist = self.game_state["board_cols"] - unit["col"] - 1
        elif dx < 0:  # West
            edge_dist = unit["col"]
        else:
            edge_dist = self.perception_radius
        
        if dy > 0:  # South
            edge_dist = min(edge_dist, self.game_state["board_rows"] - unit["row"] - 1)
        elif dy < 0:  # North
            edge_dist = min(edge_dist, unit["row"])
        
        return float(edge_dist)
    
    def _encode_allied_units(self, obs: np.ndarray, active_unit: Dict[str, Any], base_idx: int):
        """
        Encode up to 6 allied units within perception radius.
        72 floats = 6 units × 12 features per unit.
        
        Features per ally (12 floats):
        0. relative_col, 1. relative_row (egocentric position)
        2. hp_ratio (HP_CUR / HP_MAX)
        3. hp_capacity (HP_MAX normalized)
        4. has_moved (1.0 if unit moved this turn)
        5. movement_direction (0.0-1.0: fled far → charged at me)
        6. distance_normalized (distance / perception_radius)
        7. combat_mix_score (0.1-0.9: melee → ranged specialist)
        8. ranged_favorite_target (0.0-1.0: swarm → monster)
        9. melee_favorite_target (0.0-1.0: swarm → monster)
        10. can_shoot_my_target (1.0 if ally can shoot my current target)
        11. danger_level (0.0-1.0: threat to my survival)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.
        """
        # Get all allied units within perception radius
        allies = []
        for other_unit in self.game_state["units"]:
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            if "player" not in other_unit:
                raise KeyError(f"Unit missing required 'player' field: {other_unit}")
            if other_unit["player"] != active_unit["player"]:
                continue  # Skip enemies
            
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            distance = self._calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
            )
            
            if distance <= self.perception_radius:
                allies.append((distance, other_unit))
        
        # Sort by priority: closer > wounded > can_still_act
        def ally_priority(item):
            distance, unit = item
            hp_ratio = unit["HP_CUR"] / max(1, unit["HP_MAX"])
            has_acted = 1.0 if unit["id"] in self.game_state.get("units_moved", set()) else 0.0
            
            # Priority: closer units (higher), wounded (higher), not acted (higher)
            return (
                -distance * 10,  # Closer = higher priority
                -(1.0 - hp_ratio) * 5,  # More wounded = higher priority
                -has_acted  # Not acted = higher priority
            )
        
        allies.sort(key=ally_priority, reverse=True)
        
        # Encode up to 6 allies
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 12
            
            if i < len(allies):
                distance, ally = allies[i]
                
                # Feature 0-1: Relative position (egocentric)
                rel_col = (ally["col"] - active_unit["col"]) / 24.0
                rel_row = (ally["row"] - active_unit["row"]) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                
                # Feature 2-3: Health status
                obs[feature_base + 2] = ally["HP_CUR"] / max(1, ally["HP_MAX"])
                obs[feature_base + 3] = ally["HP_MAX"] / 10.0
                
                # Feature 4: Has moved
                obs[feature_base + 4] = 1.0 if ally["id"] in self.game_state.get("units_moved", set()) else 0.0
                
                # Feature 5: Movement direction (temporal behavior)
                obs[feature_base + 5] = self._calculate_movement_direction(ally, active_unit)
                
                # Feature 6: Distance normalized
                obs[feature_base + 6] = distance / self.perception_radius
                
                # Feature 7: Combat mix score
                obs[feature_base + 7] = self._calculate_combat_mix_score(ally)
                
                # Feature 8-9: Favorite targets
                obs[feature_base + 8] = self._calculate_favorite_target(ally)
                obs[feature_base + 9] = self._calculate_favorite_target(ally)  # Same for both modes
                
                # Feature 10: Can shoot my target (placeholder - requires current target context)
                obs[feature_base + 10] = 0.0
                
                # Feature 11: Danger level (threat to my survival)
                danger = self._calculate_danger_probability(active_unit, ally)
                obs[feature_base + 11] = danger
            else:
                # Padding for empty slots
                for j in range(12):
                    obs[feature_base + j] = 0.0
    
    def _encode_enemy_units(self, obs: np.ndarray, active_unit: Dict[str, Any], base_idx: int):
        """
        Encode up to 6 enemy units within perception radius.
        138 floats = 6 units × 23 features per unit.
        
        Asymmetric design: MORE complete information about enemies for tactical decisions.
        
        Features per enemy (23 floats):
        0. relative_col, 1. relative_row (egocentric position)
        2. distance_normalized (distance / perception_radius)
        3. hp_ratio (HP_CUR / HP_MAX)
        4. hp_capacity (HP_MAX normalized)
        5. has_moved, 6. movement_direction (temporal behavior)
        7. has_shot, 8. has_charged, 9. has_attacked
        10. is_valid_target (1.0 if can be shot/attacked now)
        11. kill_probability (0.0-1.0: chance I kill them this turn)
        12. danger_to_me (0.0-1.0: chance they kill ME next turn)
        13. visibility_to_allies (how many allies can see this enemy)
        14. combined_friendly_threat (total threat from all allies to this enemy)
        15. can_be_charged_by_melee (1.0 if friendly melee can reach)
        16. target_type_match (0.0-1.0: matchup quality)
        17. can_be_meleed (1.0 if I can melee them now)
        18. is_adjacent (1.0 if within melee range)
        19. is_in_range (1.0 if within my weapon range)
        20. combat_mix_score (enemy's ranged/melee preference)
        21. ranged_favorite_target (enemy's preferred ranged target)
        22. melee_favorite_target (enemy's preferred melee target)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.
        """
        # Get all enemy units within perception radius
        enemies = []
        for other_unit in self.game_state["units"]:
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if "player" not in other_unit:
                raise KeyError(f"Unit missing required 'player' field: {other_unit}")
            if other_unit["player"] == active_unit["player"]:
                continue  # Skip allies
            
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            distance = self._calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
            )
            
            if distance <= self.perception_radius:
                enemies.append((distance, other_unit))
        
        # Sort by priority: closer > can_attack_me > wounded
        def enemy_priority(item):
            distance, unit = item
            hp_ratio = unit["HP_CUR"] / max(1, unit["HP_MAX"])
            
            # Check if enemy can attack me
            can_attack = 0.0
            if "RNG_RNG" in unit and distance <= unit["RNG_RNG"]:
                can_attack = 1.0
            elif "CC_RNG" in unit and distance <= unit["CC_RNG"]:
                can_attack = 1.0
            
            # Priority: enemies (always), closer (higher), can attack (higher), wounded (higher)
            return (
                1000,  # Enemy weight
                -distance * 10,  # Closer = higher priority
                can_attack * 100,  # Can attack me = much higher priority
                -(1.0 - hp_ratio) * 5  # More wounded = higher priority
            )
        
        enemies.sort(key=enemy_priority, reverse=True)
        
        # Encode up to 6 enemies
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 23
            
            if i < len(enemies):
                distance, enemy = enemies[i]
                
                # Feature 0-2: Position and distance
                rel_col = (enemy["col"] - active_unit["col"]) / 24.0
                rel_row = (enemy["row"] - active_unit["row"]) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = distance / self.perception_radius
                
                # Feature 3-4: Health status
                obs[feature_base + 3] = enemy["HP_CUR"] / max(1, enemy["HP_MAX"])
                obs[feature_base + 4] = enemy["HP_MAX"] / 10.0
                
                # Feature 5-6: Movement tracking
                obs[feature_base + 5] = 1.0 if enemy["id"] in self.game_state.get("units_moved", set()) else 0.0
                obs[feature_base + 6] = self._calculate_movement_direction(enemy, active_unit)
                
                # Feature 7-9: Action tracking
                obs[feature_base + 7] = 1.0 if enemy["id"] in self.game_state.get("units_shot", set()) else 0.0
                obs[feature_base + 8] = 1.0 if enemy["id"] in self.game_state.get("units_charged", set()) else 0.0
                obs[feature_base + 9] = 1.0 if enemy["id"] in self.game_state.get("units_attacked", set()) else 0.0
                
                # Feature 10: Is valid target (basic check)
                current_phase = self.game_state["phase"]
                is_valid = 0.0
                if current_phase == "shoot" and "RNG_RNG" in active_unit:
                    is_valid = 1.0 if distance <= active_unit["RNG_RNG"] else 0.0
                elif current_phase == "fight" and "CC_RNG" in active_unit:
                    is_valid = 1.0 if distance <= active_unit["CC_RNG"] else 0.0
                obs[feature_base + 10] = is_valid
                
                # Feature 11-12: Kill probability and danger
                obs[feature_base + 11] = self._calculate_kill_probability(active_unit, enemy)
                obs[feature_base + 12] = self._calculate_danger_probability(active_unit, enemy)
                
                # Feature 13-14: Allied coordination
                visibility = 0.0
                combined_threat = 0.0
                for ally in self.game_state["units"]:
                    if ally["player"] == active_unit["player"] and ally["HP_CUR"] > 0:
                        if self._check_los_cached(ally, enemy) > 0.5:
                            visibility += 1.0
                        combined_threat += self._calculate_danger_probability(enemy, ally)
                obs[feature_base + 13] = min(1.0, visibility / 6.0)
                obs[feature_base + 14] = min(1.0, combined_threat / 5.0)
                
                # Feature 15-19: Tactical flags
                obs[feature_base + 15] = 1.0 if self._can_melee_units_charge_target(enemy) else 0.0
                obs[feature_base + 16] = self._calculate_target_type_match(active_unit, enemy)
                obs[feature_base + 17] = 1.0 if ("CC_RNG" in active_unit and distance <= active_unit["CC_RNG"]) else 0.0
                obs[feature_base + 18] = 1.0 if distance <= 1 else 0.0
                
                in_range = 0.0
                if "RNG_RNG" in active_unit and distance <= active_unit["RNG_RNG"]:
                    in_range = 1.0
                elif "CC_RNG" in active_unit and distance <= active_unit["CC_RNG"]:
                    in_range = 1.0
                obs[feature_base + 19] = in_range
                
                # Feature 20-22: Enemy capabilities
                obs[feature_base + 20] = self._calculate_combat_mix_score(enemy)
                obs[feature_base + 21] = self._calculate_favorite_target(enemy)
                obs[feature_base + 22] = self._calculate_favorite_target(enemy)
            else:
                # Padding for empty slots
                for j in range(23):
                    obs[feature_base + j] = 0.0
        # Get all units within perception radius
        nearby_units = []
        for other_unit in self.game_state["units"]:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            
            # AI_TURN.md COMPLIANCE: Direct field access
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            distance = self._calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
            )
            
            if distance <= self.perception_radius:
                nearby_units.append((distance, other_unit))
        
        # Sort by distance (prioritize closer units)
        nearby_units.sort(key=lambda x: x[0])
        
        # Encode up to max_nearby_units (default 10, but use 7 for 70 floats)
        max_encoded = 7  # 7 units × 10 features = 70 floats
        for i in range(max_encoded):
            feature_base = base_idx + i * 10
            
            if i < len(nearby_units):
                distance, unit = nearby_units[i]
                
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access with validation
                if "col" not in unit:
                    raise KeyError(f"Nearby unit missing required 'col' field: {unit}")
                if "row" not in unit:
                    raise KeyError(f"Nearby unit missing required 'row' field: {unit}")
                if "HP_CUR" not in unit:
                    raise KeyError(f"Nearby unit missing required 'HP_CUR' field: {unit}")
                if "HP_MAX" not in unit:
                    raise KeyError(f"Nearby unit missing required 'HP_MAX' field: {unit}")
                if "player" not in unit:
                    raise KeyError(f"Nearby unit missing required 'player' field: {unit}")
                
                # Relative position (egocentric)
                rel_col = (unit["col"] - active_unit["col"]) / 24.0
                rel_row = (unit["row"] - active_unit["row"]) / 24.0
                dist_norm = distance / self.perception_radius
                hp_ratio = unit["HP_CUR"] / unit["HP_MAX"]
                is_enemy = 1.0 if unit["player"] != active_unit["player"] else 0.0
                
                # Threat calculation (potential damage to active unit)
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
                if "RNG_DMG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'RNG_DMG' field: {unit}")
                if "CC_DMG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'CC_DMG' field: {unit}")
                
                if is_enemy > 0.5:
                    threat = max(unit["RNG_DMG"], unit["CC_DMG"]) / 5.0
                else:
                    threat = 0.0
                
                # Defensive type encoding (Swarm=0.25, Troop=0.5, Elite=0.75, Leader=1.0)
                defensive_type = self._encode_defensive_type(unit)
                
                # Offensive type encoding (Melee=0.0, Ranged=1.0)
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
                if "RNG_RNG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'RNG_RNG' field: {unit}")
                if "CC_RNG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'CC_RNG' field: {unit}")
                
                offensive_type = 1.0 if unit["RNG_RNG"] > unit["CC_RNG"] else 0.0
                
                # LoS check using cache
                has_los = self._check_los_cached(active_unit, unit)
                
                # Target preference match (placeholder - will enhance with unit registry)
                target_match = 0.5
                
                # Store encoded features
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = dist_norm
                obs[feature_base + 3] = hp_ratio
                obs[feature_base + 4] = is_enemy
                obs[feature_base + 5] = threat
                obs[feature_base + 6] = defensive_type
                obs[feature_base + 7] = offensive_type
                obs[feature_base + 8] = has_los
                obs[feature_base + 9] = target_match
            else:
                # Padding for empty slots
                for j in range(10):
                    obs[feature_base + j] = 0.0
    
    def _encode_defensive_type(self, unit: Dict[str, Any]) -> float:
        """
        Encode defensive type based on HP_MAX.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access.
        
        Returns:
        - 0.25 = Swarm (HP_MAX <= 1)
        - 0.5  = Troop (HP_MAX 2-3)
        - 0.75 = Elite (HP_MAX 4-6)
        - 1.0  = Leader (HP_MAX >= 7)
        """
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "HP_MAX" not in unit:
            raise KeyError(f"Unit missing required 'HP_MAX' field: {unit}")
        
        hp_max = unit["HP_MAX"]
        if hp_max <= 1:
            return 0.25  # Swarm
        elif hp_max <= 3:
            return 0.5   # Troop
        elif hp_max <= 6:
            return 0.75  # Elite
        else:
            return 1.0   # Leader
        
    def _encode_defensive_type_detailed(self, unit: Dict[str, Any]) -> float:
        """
        Encode defensive type with 4-tier granularity for target selection.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access.
        
        Returns:
        - 0.0  = Swarm (HP_MAX <= 1)
        - 0.33 = Troop (HP_MAX 2-3)
        - 0.66 = Elite (HP_MAX 4-6)
        - 1.0  = Leader (HP_MAX >= 7)
        """
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "HP_MAX" not in unit:
            raise KeyError(f"Unit missing required 'HP_MAX' field: {unit}")
        
        hp_max = unit["HP_MAX"]
        if hp_max <= 1:
            return 0.0  # Swarm
        elif hp_max <= 3:
            return 0.33  # Troop
        elif hp_max <= 6:
            return 0.66  # Elite
        else:
            return 1.0   # Leader
    
    def _calculate_combat_mix_score(self, unit: Dict[str, Any]) -> float:
        """
        Calculate unit's combat preference based on ACTUAL expected damage
        against their favorite target types (from unitType).
        
        Returns 0.1-0.9:
        - 0.1-0.3: Melee specialist (CC damage >> RNG damage)
        - 0.4-0.6: Balanced combatant
        - 0.7-0.9: Ranged specialist (RNG damage >> CC damage)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Determine favorite target stats based on specialization
        if "Swarm" in unit_type:
            target_T = 3
            target_save = 5
            target_invul = 7  # No invul (7+ = impossible)
        elif "Troop" in unit_type:
            target_T = 4
            target_save = 3
            target_invul = 7  # No invul
        elif "Elite" in unit_type:
            target_T = 5
            target_save = 2
            target_invul = 4  # 4+ invulnerable
        else:  # Monster/Leader
            target_T = 6
            target_save = 3
            target_invul = 7  # No invul
        
        # Validate required UPPERCASE fields
        required_fields = ["RNG_NB", "RNG_ATK", "RNG_STR", "RNG_AP", "RNG_DMG",
                          "CC_NB", "CC_ATK", "CC_STR", "CC_AP", "CC_DMG"]
        for field in required_fields:
            if field not in unit:
                raise KeyError(f"Unit missing required '{field}' field: {unit}")
        
        # Calculate EXPECTED ranged damage per turn
        ranged_expected = self._calculate_expected_damage(
            num_attacks=unit["RNG_NB"],
            to_hit_stat=unit["RNG_ATK"],
            strength=unit["RNG_STR"],
            target_toughness=target_T,
            ap=unit["RNG_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["RNG_DMG"]
        )
        
        # Calculate EXPECTED melee damage per turn
        melee_expected = self._calculate_expected_damage(
            num_attacks=unit["CC_NB"],
            to_hit_stat=unit["CC_ATK"],
            strength=unit["CC_STR"],
            target_toughness=target_T,
            ap=unit["CC_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["CC_DMG"]
        )
        
        total_expected = ranged_expected + melee_expected
        
        if total_expected == 0:
            return 0.5  # Neutral (no combat power)
        
        # Scale to 0.1-0.9 range
        raw_ratio = ranged_expected / total_expected
        return 0.1 + (raw_ratio * 0.8)
    
    def _calculate_expected_damage(self, num_attacks: int, to_hit_stat: int, 
                                   strength: int, target_toughness: int, ap: int, 
                                   target_save: int, target_invul: int, 
                                   damage_per_wound: int) -> float:
        """
        Calculate expected damage using W40K dice mechanics with invulnerable saves.
        
        Expected damage = Attacks × P(hit) × P(wound) × P(fail_save) × Damage
        """
        # Hit probability
        p_hit = max(0.0, min(1.0, (7 - to_hit_stat) / 6.0))
        
        # Wound probability
        wound_target = self._calculate_wound_target_basic(strength, target_toughness)
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (use better of armor or invul)
        modified_armor_save = target_save - ap
        best_save = min(modified_armor_save, target_invul)
        
        if best_save > 6:
            p_fail_save = 1.0  # Impossible to save
        else:
            p_fail_save = max(0.0, min(1.0, (best_save - 1) / 6.0))
        
        # Expected damage per turn
        expected = num_attacks * p_hit * p_wound * p_fail_save * damage_per_wound
        
        return expected
    
    def _calculate_wound_target_basic(self, strength: int, toughness: int) -> int:
        """W40K wound chart - basic calculation without external dependencies"""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+
    
    def _calculate_favorite_target(self, unit: Dict[str, Any]) -> float:
        """
        Extract favorite target type from unitType name.
        
        unitType format: "Faction_Movement_PowerLevel_AttackPreference"
        Example: "SpaceMarine_Infantry_Troop_RangedSwarm"
                                              ^^^^^^^^^^^^
                                              Ranged + Swarm
        
        Returns 0.0-1.0 encoding:
        - 0.0 = Swarm specialist (vs HP_MAX ≤ 1)
        - 0.33 = Troop specialist (vs HP_MAX 2-3)
        - 0.66 = Elite specialist (vs HP_MAX 4-6)
        - 1.0 = Monster specialist (vs HP_MAX ≥ 7)
        
        AI_TURN.md COMPLIANCE: Direct field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Parse attack preference component (last part after final underscore)
        parts = unit_type.split("_")
        if len(parts) < 4:
            return 0.5  # Default neutral if format unexpected
        
        attack_pref = parts[3]  # e.g., "RangedSwarm", "MeleeElite"
        
        # Extract target preference from attack_pref
        if "Swarm" in attack_pref:
            return 0.0
        elif "Troop" in attack_pref:
            return 0.33
        elif "Elite" in attack_pref:
            return 0.66
        elif "Monster" in attack_pref or "Leader" in attack_pref:
            return 1.0
        else:
            return 0.5  # Default neutral
    
    def _calculate_movement_direction(self, unit: Dict[str, Any], 
                                     active_unit: Dict[str, Any]) -> float:
        """
        Encode temporal behavior in single float - replaces frame stacking.
        
        Detects unit's movement pattern relative to active unit:
        - 0.00-0.24: Fled far from me (>50% MOVE away)
        - 0.25-0.49: Moved away slightly (<50% MOVE away)
        - 0.50-0.74: Advanced slightly (<50% MOVE toward)
        - 0.75-1.00: Charged at me (>50% MOVE toward)
        
        Critical for detecting threats before they strike!
        AI_TURN.md COMPLIANCE: Direct field access
        """
        # Get last known position from cache
        if not hasattr(self, 'last_unit_positions') or not self.last_unit_positions:
            return 0.5  # Unknown/first turn
        
        if "id" not in unit:
            raise KeyError(f"Unit missing required 'id' field: {unit}")
        
        unit_id = str(unit["id"])
        if unit_id not in self.last_unit_positions:
            return 0.5  # No previous position data
        
        # Validate required position fields
        if "col" not in unit or "row" not in unit:
            raise KeyError(f"Unit missing required position fields: {unit}")
        if "col" not in active_unit or "row" not in active_unit:
            raise KeyError(f"Active unit missing required position fields: {active_unit}")
        
        prev_col, prev_row = self.last_unit_positions[unit_id]
        curr_col, curr_row = unit["col"], unit["row"]
        
        # Calculate movement toward/away from active unit
        prev_dist = self._calculate_hex_distance(
            prev_col, prev_row, 
            active_unit["col"], active_unit["row"]
        )
        curr_dist = self._calculate_hex_distance(
            curr_col, curr_row,
            active_unit["col"], active_unit["row"]
        )
        
        move_distance = self._calculate_hex_distance(prev_col, prev_row, curr_col, curr_row)
        
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_move = unit["MOVE"]
        
        if move_distance == 0:
            return 0.5  # No movement
        
        delta_dist = prev_dist - curr_dist  # Positive = moved closer
        move_ratio = abs(delta_dist) / max(1, max_move)  # Prevent division by zero
        
        if delta_dist < 0:  # Moved away
            if move_ratio > 0.5:
                return 0.12  # Fled far (>50% MOVE away)
            else:
                return 0.37  # Moved away slightly
        else:  # Moved closer
            if move_ratio > 0.5:
                return 0.87  # Charged (>50% MOVE toward)
            else:
                return 0.62  # Advanced slightly
    
    def _check_los_cached(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> float:
        """
        Check LoS using cache if available, fallback to calculation.
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # Use LoS cache if available (Phase 1 implementation)
        if "los_cache" in self.game_state and self.game_state["los_cache"]:
            cache_key = (shooter["id"], target["id"])
            if cache_key in self.game_state["los_cache"]:
                return 1.0 if self.game_state["los_cache"][cache_key] else 0.0
        
        # Fallback: calculate LoS (happens if cache not built yet)
        from .phase_handlers import shooting_handlers
        has_los = shooting_handlers._has_line_of_sight(self.game_state, shooter, target)
        return 1.0 if has_los else 0.0
    
    def _encode_valid_targets(self, obs: np.ndarray, active_unit: Dict[str, Any], base_idx: int):
        """
        Encode valid targets with EXPLICIT action-target correspondence and W40K probabilities.
        35 floats = 5 actions × 7 features per action
        
        SIMPLIFIED from 9 to 7 features (removed redundant features with enemy section).
        
        CRITICAL DESIGN: obs[260 + action_offset*7] directly corresponds to action (4 + action_offset)
        Example: 
        - obs[260:267] = features for what happens if agent presses action 4
        - obs[267:274] = features for what happens if agent presses action 5
        
        This creates DIRECT causal relationship for RL learning:
        "When obs[261]=1.0 (high kill_probability), pressing action 4 gives high reward"
        
        Features per action slot (7 floats) - CORE TACTICAL ESSENTIALS:
        0. is_valid (1.0 = target exists, 0.0 = no target in this slot)
        1. kill_probability (0.0-1.0, probability to kill target this turn considering dice)
        2. danger_to_me (0.0-1.0, probability target kills ME next turn)
        3. enemy_index (0-5: which enemy in obs[122:260] this action targets)
        4. distance_normalized (hex_distance / perception_radius)
        5. is_priority_target (1.0 if moved toward me, high threat)
        6. coordination_bonus (1.0 if friendly melee can charge after I shoot)
        """
        # Get valid targets based on current phase
        valid_targets = []
        current_phase = self.game_state["phase"]
        
        if current_phase == "shoot":
            # Get valid shooting targets using shooting handler
            from .phase_handlers import shooting_handlers
            
            # Build target pool using handler's validation
            target_ids = shooting_handlers.shooting_build_valid_target_pool(
                self.game_state, active_unit["id"]
            )
            
            valid_targets = [
                self._get_unit_by_id(tid) 
                for tid in target_ids 
                if self._get_unit_by_id(tid)
            ]
            
        elif current_phase == "charge":
            # Get valid charge targets (enemies within charge range)
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "MOVE" not in active_unit:
                raise KeyError(f"Active unit missing required 'MOVE' field: {active_unit}")
            
            for enemy in self.game_state["units"]:
                # AI_TURN.md COMPLIANCE: Direct field access with validation
                if "player" not in enemy:
                    raise KeyError(f"Enemy unit missing required 'player' field: {enemy}")
                if "HP_CUR" not in enemy:
                    raise KeyError(f"Enemy unit missing required 'HP_CUR' field: {enemy}")
                
                if enemy["player"] != active_unit["player"] and enemy["HP_CUR"] > 0:
                    if "col" not in enemy or "row" not in enemy:
                        raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                    
                    distance = self._calculate_hex_distance(
                        active_unit["col"], active_unit["row"],
                        enemy["col"], enemy["row"]
                    )
                    
                    # Max charge = MOVE + 12 (maximum 2d6 roll)
                    max_charge = active_unit["MOVE"] + 12
                    if distance <= max_charge:
                        valid_targets.append(enemy)
        
        elif current_phase == "fight":
            # Get valid melee targets (enemies within CC_RNG)
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "CC_RNG" not in active_unit:
                raise KeyError(f"Active unit missing required 'CC_RNG' field: {active_unit}")
            
            for enemy in self.game_state["units"]:
                if "player" not in enemy or "HP_CUR" not in enemy:
                    raise KeyError(f"Enemy unit missing required fields: {enemy}")
                
                if enemy["player"] != active_unit["player"] and enemy["HP_CUR"] > 0:
                    if "col" not in enemy or "row" not in enemy:
                        raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                    
                    distance = self._calculate_hex_distance(
                        active_unit["col"], active_unit["row"],
                        enemy["col"], enemy["row"]
                    )
                    
                    if distance <= active_unit["CC_RNG"]:
                        valid_targets.append(enemy)
        
        # Sort by distance (prioritize closer targets)
        valid_targets.sort(key=lambda t: self._calculate_hex_distance(
            active_unit["col"], active_unit["row"], t["col"], t["row"]
        ))
        
        # Build enemy index map for reference
        enemy_index_map = {}
        enemy_list = [u for u in self.game_state["units"] 
                     if u["player"] != active_unit["player"] and u["HP_CUR"] > 0]
        enemy_list.sort(key=lambda e: self._calculate_hex_distance(
            active_unit["col"], active_unit["row"], e["col"], e["row"]
        ))
        for idx, enemy in enumerate(enemy_list[:6]):
            enemy_index_map[enemy["id"]] = idx
        
        # Encode up to max_valid_targets (5 targets × 7 features = 35 floats)
        max_encoded = 5
        for i in range(max_encoded):
            feature_base = base_idx + i * 7
            
            if i < len(valid_targets):
                target = valid_targets[i]
                
                # Feature 0: Action validity (CRITICAL - tells agent this action works)
                obs[feature_base + 0] = 1.0
                
                # Feature 1: Kill probability (W40K dice mechanics)
                kill_prob = self._calculate_kill_probability(active_unit, target)
                obs[feature_base + 1] = kill_prob
                
                # Feature 2: Danger to me (probability target kills ME next turn)
                danger_prob = self._calculate_danger_probability(active_unit, target)
                obs[feature_base + 2] = danger_prob
                
                # Feature 3: Enemy index (reference to obs[122:260])
                enemy_idx = enemy_index_map.get(target["id"], 0)
                obs[feature_base + 3] = enemy_idx / 5.0
                
                # Feature 4: Distance (accessibility)
                distance = self._calculate_hex_distance(
                    active_unit["col"], active_unit["row"],
                    target["col"], target["row"]
                )
                obs[feature_base + 4] = distance / self.perception_radius
                
                # Feature 5: Is priority target (moved toward me + high threat)
                movement_dir = self._calculate_movement_direction(target, active_unit)
                is_approaching = 1.0 if movement_dir > 0.75 else 0.0
                danger = self._calculate_danger_probability(active_unit, target)
                is_priority = 1.0 if (is_approaching > 0.5 and danger > 0.5) else 0.0
                obs[feature_base + 5] = is_priority
                
                # Feature 6: Coordination bonus (can friendly melee charge after I shoot)
                can_be_charged = 1.0 if self._can_melee_units_charge_target(target) else 0.0
                obs[feature_base + 6] = can_be_charged
            else:
                # Padding for empty slots
                for j in range(7):
                    obs[feature_base + j] = 0.0
    
    def _calculate_kill_probability(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> float:
        """
        Calculate actual probability to kill target this turn considering W40K dice mechanics.
        
        Considers:
        - Hit probability (RNG_ATK vs d6)
        - Wound probability (RNG_STR vs target T)
        - Save failure probability (target saves vs RNG_AP)
        - Number of shots (RNG_NB)
        - Damage per successful wound (RNG_DMG)
        
        Returns: 0.0-1.0 probability
        """
        current_phase = self.game_state["phase"]
        
        if current_phase == "shoot":
            if "RNG_ATK" not in shooter or "RNG_STR" not in shooter or "RNG_DMG" not in shooter:
                raise KeyError(f"Shooter missing required ranged stats: {shooter}")
            if "RNG_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'RNG_NB' field: {shooter}")
            
            hit_target = shooter["RNG_ATK"]
            strength = shooter["RNG_STR"]
            damage = shooter["RNG_DMG"]
            num_attacks = shooter["RNG_NB"]
            ap = shooter.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in shooter or "CC_STR" not in shooter or "CC_DMG" not in shooter:
                raise KeyError(f"Shooter missing required melee stats: {shooter}")
            if "CC_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'CC_NB' field: {shooter}")
            
            hit_target = shooter["CC_ATK"]
            strength = shooter["CC_STR"]
            damage = shooter["CC_DMG"]
            num_attacks = shooter["CC_NB"]
            ap = shooter.get("CC_AP", 0)
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        wound_target = self._calculate_wound_target(strength, target["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (uses imported function from shooting_handlers)
        save_target = _calculate_save_target(target, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        if expected_damage >= target["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / target["HP_CUR"])
    
    def _calculate_danger_probability(self, defender: Dict[str, Any], attacker: Dict[str, Any]) -> float:
        """
        Calculate probability that attacker will kill defender on its next turn.
        Works for ANY unit pair (active unit vs enemy, VIP vs enemy, etc.)
        
        Considers:
        - Distance (can they reach?)
        - Hit/wound/save probabilities
        - Number of attacks
        - Damage output
        
        Returns: 0.0-1.0 probability
        """
        distance = self._calculate_hex_distance(
            defender["col"], defender["row"],
            attacker["col"], attacker["row"]
        )
        
        can_use_ranged = distance <= attacker.get("RNG_RNG", 0)
        can_use_melee = distance <= attacker.get("CC_RNG", 0)
        
        if not can_use_ranged and not can_use_melee:
            return 0.0
        
        if can_use_ranged and not can_use_melee:
            if "RNG_ATK" not in attacker or "RNG_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["RNG_ATK"]
            strength = attacker["RNG_STR"]
            damage = attacker["RNG_DMG"]
            num_attacks = attacker.get("RNG_NB", 0)
            ap = attacker.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in attacker or "CC_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["CC_ATK"]
            strength = attacker["CC_STR"]
            damage = attacker["CC_DMG"]
            num_attacks = attacker.get("CC_NB", 0)
            ap = attacker.get("CC_AP", 0)
        
        if num_attacks == 0:
            return 0.0
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in defender:
            return 0.0
        wound_target = self._calculate_wound_target(strength, defender["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        save_target = _calculate_save_target(defender, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        if expected_damage >= defender["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / defender["HP_CUR"])
    
    def _calculate_army_weighted_threat(self, target: Dict[str, Any], valid_targets: List[Dict[str, Any]]) -> float:
        """
        Calculate army-wide weighted threat score considering all friendly units by VALUE.
        
        This is the STRATEGIC PRIORITY feature that teaches the agent to:
        - Protect high-VALUE units (Leaders, Elites)
        - Consider threats to the entire team, not just personal survival
        - Make sacrifices when strategically necessary
        
        Logic:
        1. For each friendly unit, calculate danger from this target
        2. Weight that danger by the friendly unit's VALUE (1-200)
        3. Sum all weighted dangers
        4. Normalize to 0.0-1.0 based on highest threat among all targets
        
        Returns: 0.0-1.0 (1.0 = highest strategic threat among all targets)
        """
        my_player = self.game_state["current_player"]
        friendly_units = [
            u for u in self.game_state["units"]
            if u["player"] == my_player and u["HP_CUR"] > 0
        ]
        
        if not friendly_units:
            return 0.0
        
        total_weighted_threat = 0.0
        for friendly in friendly_units:
            danger = self._calculate_danger_probability(friendly, target)
            unit_value = friendly.get("VALUE", 10.0)
            weighted_threat = danger * unit_value
            total_weighted_threat += weighted_threat
        
        all_weighted_threats = []
        for t in valid_targets:
            t_total = 0.0
            for friendly in friendly_units:
                danger = self._calculate_danger_probability(friendly, t)
                unit_value = friendly.get("VALUE", 10.0)
                t_total += danger * unit_value
            all_weighted_threats.append(t_total)
        
        max_weighted_threat = max(all_weighted_threats) if all_weighted_threats else 1.0
        
        if max_weighted_threat > 0:
            return min(1.0, total_weighted_threat / max_weighted_threat)
        else:
            return 0.0
    
    def _calculate_target_type_match(self, active_unit: Dict[str, Any], 
                                    target: Dict[str, Any]) -> float:
        """
        Calculate unit_registry-based type compatibility (0.0-1.0).
        Higher = this unit is specialized against this target type.
        
        Example: RangedSwarm unit gets 1.0 against Swarm targets, 0.3 against others
        """
        try:
            if not hasattr(self, 'unit_registry') or not self.unit_registry:
                return 0.5
            
            unit_type = active_unit.get("unitType", "")
            
            if "Swarm" in unit_type:
                preferred = "swarm"
            elif "Troop" in unit_type:
                preferred = "troop"
            elif "Elite" in unit_type:
                preferred = "elite"
            elif "Leader" in unit_type:
                preferred = "leader"
            else:
                return 0.5
            
            target_hp = target.get("HP_MAX", 1)
            if target_hp <= 1:
                target_type = "swarm"
            elif target_hp <= 3:
                target_type = "troop"
            elif target_hp <= 6:
                target_type = "elite"
            else:
                target_type = "leader"
            
            return 1.0 if preferred == target_type else 0.3
            
        except Exception:
            return 0.5
    
    def _calculate_hex_distance(self, col1: int, row1: int, col2: int, row2: int) -> int:
        """Calculate hex distance using cube coordinates (matching handlers)."""
        # Convert offset to cube
        x1 = col1
        z1 = row1 - ((col1 - (col1 & 1)) >> 1)
        y1 = -x1 - z1
        
        x2 = col2
        z2 = row2 - ((col2 - (col2 & 1)) >> 1)
        y2 = -x2 - z2
        
        # Cube distance
        return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
    
    def _calculate_reward(self, success: bool, result: Dict[str, Any]) -> float:
        """Calculate reward using actual acting unit with reward mapper integration."""
        # PRIORITY CHECK: Invalid action penalty (from handlers)
        if isinstance(result, dict) and result.get("invalid_action_penalty"):
            return -0.9  # Training penalty for wrong phase actions
        
        if not success:
            if isinstance(result, dict):
                error_msg = result.get("error", "")
                if "forbidden_in" in error_msg or "masked_in" in error_msg:
                    return -1.0  # Heavy penalty for phase violations to train proper behavior
                else:
                    return -0.1  # Small penalty for other invalid actions
            else:
                return -0.1  # Default penalty for failures
        
        # Handle system responses (no unit-specific rewards)
        system_response_indicators = [
            "phase_complete", "phase_transition", "while_loop_active", 
            "context", "blinking_units", "start_blinking", "validTargets",
            "type", "next_phase", "current_player", "new_turn", "episode_complete"
        ]
        
        if any(indicator in result for indicator in system_response_indicators):
            # System responses are not unit actions - no reward needed
            return 0.0
        
        # Get ACTUAL acting unit from result, not pool[0]
        acting_unit_id = result.get("unitId") or result.get("shooterId") or result.get("unit_id")
        if not acting_unit_id:
            raise ValueError(f"Action result missing acting unit ID: {result}")
        
        acting_unit = self._get_unit_by_id(str(acting_unit_id))
        if not acting_unit:
            raise ValueError(f"Acting unit not found: {acting_unit_id}")
        
        # Get action type from result
        action_type = result.get("action", "unknown") if isinstance(result, dict) else "unknown"
        
        # Full reward mapper integration - use unit registry for proper config mapping
        reward_mapper = self._get_reward_mapper()
        
        # Enrich unit data with tactical flags required by reward_mapper
        enriched_unit = self._enrich_unit_for_reward_mapper(acting_unit)
        
        # Debug: Log agent assignment for rewards
        if not self.quiet:
            # AI_TURN.md COMPLIANCE: Direct field access
            if 'unitType' not in acting_unit:
                raise KeyError(f"Acting unit missing required 'unitType' field: {acting_unit}")
            if 'unitType' not in enriched_unit:
                raise KeyError(f"Enriched unit missing required 'unitType' field: {enriched_unit}")
            original_type = acting_unit['unitType']
            agent_type = enriched_unit['unitType']
            controlled_agent = self.config['controlled_agent'] if self.config and 'controlled_agent' in self.config else None
            if controlled_agent is None:
                raise ValueError("Missing controlled_agent in config - required for reward calculation")
        
        if action_type == "shoot" and "targetId" in result:
            target = self._get_unit_by_id(str(result["targetId"]))
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            
            # Get base shooting reward
            unit_rewards = reward_mapper._get_unit_rewards(enriched_unit)
            base_reward = unit_rewards["base_actions"]["ranged_attack"]
            
            # Add target type bonus/penalty
            target_bonus = reward_mapper._get_target_type_bonus(enriched_unit, enriched_target)
            
            # Add result bonuses if target was killed/wounded
            result_bonus = 0.0
            if result.get("target_died", False):
                result_bonus += unit_rewards["result_bonuses"]["kill_target"]
            
            final_reward = base_reward + target_bonus + result_bonus
            return final_reward
        
        elif action_type == "move":
            # AI_TURN.md COMPLIANCE: Direct access - movement results must provide coordinates
            if "fromCol" not in result or "fromRow" not in result:
                raise KeyError(f"Movement result missing required position fields: {result}")
            if "toCol" not in result or "toRow" not in result:
                raise KeyError(f"Movement result missing required destination fields: {result}")
            old_pos = (result["fromCol"], result["fromRow"])
            new_pos = (result["toCol"], result["toRow"])
            tactical_context = self._build_tactical_context(acting_unit, result)
            
            # CRITICAL FIX: Unpack tuple returned by get_movement_reward
            reward_result = reward_mapper.get_movement_reward(enriched_unit, old_pos, new_pos, tactical_context)
            if isinstance(reward_result, tuple) and len(reward_result) == 2:
                movement_reward, _ = reward_result  # Unpack: (reward_value, action_name)
                return movement_reward
            else:
                return reward_result  # Backward compatibility: scalar return
        elif action_type == "skip":
            # SKIP: Agent CANNOT perform action - use wait penalty
            return self._calculate_reward_from_config(acting_unit, {"type": "wait"}, success)
        elif action_type == "charge" and "targetId" in result:
            target = self._get_unit_by_id(str(result["targetId"]))
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit)]
            return reward_mapper.get_charge_priority_reward(enriched_unit, enriched_target, all_targets)
        elif action_type == "fight" and "targetId" in result:
            target = self._get_unit_by_id(str(result["targetId"]))
            enriched_target = self._enrich_unit_for_reward_mapper(target)
            all_targets = [self._enrich_unit_for_reward_mapper(t) for t in self._get_all_valid_targets(acting_unit)]
            return reward_mapper.get_combat_priority_reward(enriched_unit, enriched_target, all_targets)
        elif action_type == "wait":
            # Use base wait penalty from config
            return self._calculate_reward_from_config(acting_unit, {"type": "wait"}, success)
        
        # Use standard config-based reward for other actions
        return self._calculate_reward_from_config(acting_unit, {"type": action_type}, success)
        
        # Use standard config-based reward calculation
        action = {"type": action_type}
        return self._calculate_reward_from_config(acting_unit, action, success)
    
    def _calculate_reward_from_config(self, acting_unit: Dict[str, Any], action: Dict[str, Any], success: bool) -> float:
        """Exact reproduction of gym40k.py reward calculation."""
        unit_rewards = self._get_unit_reward_config(acting_unit)
        base_reward = 0.0
        
        # Validate required reward structure
        if "base_actions" not in unit_rewards:
            raise KeyError(f"Unit rewards missing required 'base_actions' section")
        
        base_actions = unit_rewards["base_actions"]
        
        # Base action rewards - exact gym40k.py logic
        action_type = action["type"]
        if action_type == "shoot":
            if success:
                if "ranged_attack" not in base_actions:
                    raise KeyError(f"Base actions missing required 'ranged_attack' reward")
                base_reward = base_actions["ranged_attack"]  # 0.5 for RangedSwarm
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]  # -0.3 penalty
        elif action_type == "move":
            if success:
                move_key = "move_close" if "move_close" in base_actions else "wait"
                if move_key not in base_actions:
                    raise KeyError(f"Base actions missing required '{move_key}' reward")
                base_reward = base_actions[move_key]
            else:
                if "wait" not in base_actions:
                    raise KeyError(f"Base actions missing required 'wait' reward")
                base_reward = base_actions["wait"]
        elif action_type == "skip":
            if "wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'wait' reward")
            base_reward = base_actions["wait"]  # -0.3 penalty for skipping
        else:
            if "wait" not in base_actions:
                raise KeyError(f"Base actions missing required 'wait' reward")
            base_reward = base_actions["wait"]
        
        # Add win/lose bonuses from situational_modifiers
        if self.game_state["game_over"]:
            # AI_TURN.md COMPLIANCE: Direct access with validation
            if "situational_modifiers" not in unit_rewards:
                raise KeyError("Unit rewards missing required 'situational_modifiers' section")
            modifiers = unit_rewards["situational_modifiers"]
            winner = self._determine_winner()
            
            if winner == 1:  # AI wins
                if "win" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'win' reward")
                base_reward += modifiers["win"]
            elif winner == 0:  # AI loses
                if "lose" not in modifiers:
                    raise KeyError(f"Situational modifiers missing required 'lose' reward")
                base_reward += modifiers["lose"]
        
        return base_reward
    
    def _get_unit_reward_config(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Exact reproduction of gym40k.py unit reward config method."""
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        unit_type = unit["unitType"]
        
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
            raise ValueError(f"Failed to get reward config for unit type '{unit['unitType']}': {e}")
    
    # ===== VALIDATION METHODS =====
    
    def _determine_winner(self) -> Optional[int]:
        """Determine winner based on remaining living units or turn limit."""
        living_units_by_player = {}
        
        for unit in self.game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # Check if game ended due to turn limit
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and self.game_state["turn"] > max_turns:
                # Turn limit reached - determine winner by remaining units
                living_players = list(living_units_by_player.keys())
                if len(living_players) == 1:
                    return living_players[0]
                elif len(living_players) == 2:
                    # Both players have units - compare counts
                    if living_units_by_player[0] > living_units_by_player[1]:
                        return 0
                    elif living_units_by_player[1] > living_units_by_player[0]:
                        return 1
                    else:
                        return None  # Draw - equal units
                else:
                    return None  # Draw - no units or other scenario
        
        # Normal elimination rules
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            return living_players[0]
        elif len(living_players) == 0:
            return None  # Draw/no winner
        else:
            return None  # Game still ongoing
    
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
    
    def _get_action_phase_for_logging(self, action_type: str) -> str:
        """Map action types to their logical phases for step logging."""
        action_phase_map = {
            "move": "move",
            "shoot": "shoot", 
            "charge": "charge",
            "combat": "fight",
            "fight": "fight",
            "skip": self.game_state["phase"]  # Use current phase for skip
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

# ===== GYM INTERFACE HELPER METHODS =====
    
    def get_action_mask(self) -> np.ndarray:
        """Return action mask with dynamic target slot masking - True = valid action."""
        mask = np.zeros(12, dtype=bool)
        current_phase = self.game_state["phase"]
        eligible_units = self._get_eligible_units_for_current_phase()
        
        if not eligible_units:
            # No units can act - only system actions allowed (handled internally)
            return mask  # All False - no valid actions
        
        if current_phase == "move":
            # Movement phase: actions 0-3 (movement types) + 11 (wait)
            mask[[0, 1, 2, 3, 11]] = True
        elif current_phase == "shoot":
            # Shooting phase: actions 4-8 (target slots 0-4) + 11 (wait)
            # CRITICAL FIX: Dynamically enable based on ACTUAL available targets
            active_unit = eligible_units[0] if eligible_units else None
            if active_unit:
                from .phase_handlers import shooting_handlers
                valid_targets = shooting_handlers.shooting_build_valid_target_pool(
                    self.game_state, active_unit["id"]
                )
                num_targets = len(valid_targets)
                
                # CRITICAL: Only enable target slots if targets exist
                if num_targets > 0:
                    # Enable shoot actions for available targets only (up to 5 slots)
                    for i in range(min(5, num_targets)):
                        mask[4 + i] = True
            
            mask[11] = True  # Wait always valid (can choose not to shoot)
        elif current_phase == "charge":
            # Charge phase: action 9 (charge) + 11 (wait)
            mask[[9, 11]] = True
        elif current_phase == "fight":
            # Fight phase: action 10 (fight) only - no wait in fight
            mask[10] = True
        
        return mask
    
    def _convert_gym_action(self, action: int) -> Dict[str, Any]:
        """Convert gym integer action to semantic action with target selection support."""
        action_int = int(action.item()) if hasattr(action, 'item') else int(action)
        current_phase = self.game_state["phase"]
        
        # Validate action against mask - convert invalid actions to SKIP
        action_mask = self.get_action_mask()        
        if not action_mask[action_int]:
            # Return invalid action for training penalty and proper pool management
            eligible_units = self._get_eligible_units_for_current_phase()
            if eligible_units:
                selected_unit_id = eligible_units[0]["id"]
                return {
                    "action": "invalid", 
                    "error": f"forbidden_in_{current_phase}_phase", 
                    "unitId": selected_unit_id,
                    "attempted_action": action_int,
                    "end_activation_required": True
                }
            else:
                return {"action": "advance_phase", "from": current_phase, "reason": "no_eligible_units"}
        
        # Get eligible units for current phase - AI_TURN.md sequential activation
        eligible_units = self._get_eligible_units_for_current_phase()
        
        if not eligible_units:
            current_phase = self.game_state["phase"]
            if current_phase == "move":
                self._shooting_phase_init()
                return {"action": "advance_phase", "from": "move", "to": "shoot"}
            elif current_phase == "shoot":
                self._advance_to_next_player()
                return {"action": "advance_phase", "from": "shoot", "to": "move"}
            else:
                return {"action": "invalid", "error": "no_eligible_units", "unitId": "SYSTEM"}
        
        # GUARANTEED UNIT SELECTION - use first eligible unit directly
        selected_unit_id = eligible_units[0]["id"]
        
        if current_phase == "move":
            if action_int in [0, 1, 2, 3]:  # Move actions
                return {
                    "action": "activate_unit", 
                    "unitId": selected_unit_id
                }
            elif action_int == 11:  # WAIT - agent chooses not to move
                return {"action": "skip", "unitId": selected_unit_id}
                
        elif current_phase == "shoot":
            if action_int in [4, 5, 6, 7, 8]:  # Shoot target slots 0-4
                target_slot = action_int - 4  # Convert to slot index (0-4)
                
                # Get valid targets for this unit
                from .phase_handlers import shooting_handlers
                valid_targets = shooting_handlers.shooting_build_valid_target_pool(
                    self.game_state, selected_unit_id
                )
                
                # CRITICAL: Validate target slot is within valid range
                if target_slot < len(valid_targets):
                    target_id = valid_targets[target_slot]
                    
                    # Debug: Log first few target selections
                    if self.game_state["turn"] == 1 and not hasattr(self, '_target_logged'):
                        self._target_logged = True
                    
                    return {
                        "action": "shoot",
                        "unitId": selected_unit_id,
                        "targetId": target_id
                    }
                else:
                    return {
                        "action": "wait",
                        "unitId": selected_unit_id,
                        "invalid_action_penalty": True,
                        "attempted_action": action_int
                    }
                    
            elif action_int == 11:  # WAIT - agent chooses not to shoot
                return {"action": "wait", "unitId": selected_unit_id}
                
        elif current_phase == "charge":
            if action_int == 9:  # Charge action
                target = self._ai_select_charge_target(selected_unit_id)
                return {
                    "action": "charge", 
                    "unitId": selected_unit_id, 
                    "targetId": target
                }
            elif action_int == 11:  # WAIT - agent chooses not to charge
                return {"action": "wait", "unitId": selected_unit_id}
                
        elif current_phase == "fight":
            if action_int == 10:  # Fight action - NO WAIT option in fight phase
                selected_unit = self._ai_select_unit(eligible_units, "fight")
                target = self._ai_select_combat_target(selected_unit)
                return {
                    "action": "fight", 
                    "unitId": selected_unit, 
                    "targetId": target
                }
        
        valid_actions = self._get_valid_actions_for_phase(current_phase)
        if action_int not in valid_actions:
            return {"action": "invalid", "error": f"action_{action_int}_forbidden_in_{current_phase}_phase"}
        
        # SKIP is system response when no valid actions possible (not agent choice)
        return {"action": "skip", "reason": "no_valid_action_found"}
    
    def _get_valid_actions_for_phase(self, phase: str) -> List[int]:
        """Get valid action types for current phase with target selection support."""
        if phase == "move":
            return [0, 1, 2, 3, 11]  # Move directions + wait
        elif phase == "shoot":
            return [4, 5, 6, 7, 8, 11]  # Target slots 0-4 + wait
        elif phase == "charge":
            return [9, 11]  # Charge + wait
        elif phase == "fight":
            return [10]  # Fight only - NO WAIT in fight phase
        else:
            return [11]  # Only wait for unknown phases
    
    def _get_eligible_units_for_current_phase(self) -> List[Dict[str, Any]]:
        """Get eligible units for current phase using handler's authoritative pools."""
        current_phase = self.game_state["phase"]
        
        if current_phase == "move":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "move_activation_pool" not in self.game_state:
                raise KeyError("game_state missing required 'move_activation_pool' field")
            pool_unit_ids = self.game_state["move_activation_pool"]
            return [self._get_unit_by_id(uid) for uid in pool_unit_ids if self._get_unit_by_id(uid)]
        elif current_phase == "shoot":
            # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
            if "shoot_activation_pool" not in self.game_state:
                raise KeyError("game_state missing required 'shoot_activation_pool' field")
            pool_unit_ids = self.game_state["shoot_activation_pool"]
            return [self._get_unit_by_id(uid) for uid in pool_unit_ids if self._get_unit_by_id(uid)]
        else:
            return []
    
    def _ai_select_unit(self, eligible_units: List[Dict[str, Any]], action_type: str) -> str:
        """AI selects which unit to activate - NO MODEL CALLS to prevent recursion."""
        if not eligible_units:
            raise ValueError("No eligible units available for selection")
        
        # CRITICAL: Never call AI model from here - causes recursion
        # Model prediction happens at api_server.py level, this just selects from eligible units
        
        # For AI_TURN.md compliance: select first eligible unit deterministically
        # The AI model determines the ACTION, not which unit to select
        return eligible_units[0]["id"]
    
    def _ai_select_unit_with_model(self, eligible_units: List[Dict[str, Any]], action_type: str) -> str:
        """Use trained DQN model to select best unit for AI player."""
        if not hasattr(self, '_ai_model') or not self._ai_model:
            # Fallback to round-robin if no model loaded
            return eligible_units[0]["id"]
        
        # Get current observation
        obs = self._build_observation()
        
        # Get AI action from trained model
        try:
            action, _ = self._ai_model.predict(obs, deterministic=True)
            semantic_action = self._convert_gym_action(action)
            
            # Extract unit selection from semantic action
            suggested_unit_id = semantic_action.get("unitId")
            
            # Validate AI's unit choice is in eligible list
            eligible_ids = [str(unit["id"]) for unit in eligible_units]
            if suggested_unit_id in eligible_ids:
                return suggested_unit_id
            else:
                # AI suggested invalid unit - use first eligible
                return eligible_units[0]["id"]
                
        except Exception as e:
            return eligible_units[0]["id"]
    
    def _ai_select_movement_destination(self, unit_id: str) -> Tuple[int, int]:
        """AI selects movement destination that actually moves the unit."""
        unit = self._get_unit_by_id(unit_id)
        if not unit:
            raise ValueError(f"Unit not found: {unit_id}")
        
        current_pos = (unit["col"], unit["row"])
        
        # Use movement handler to get valid destinations
        valid_destinations = movement_handlers.movement_build_valid_destinations_pool(self.game_state, unit_id)
        
        # CRITICAL: Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # CRITICAL: Filter out current position to force actual movement
        actual_moves = [dest for dest in valid_destinations if dest != current_pos]
        
        # AI_TURN.md COMPLIANCE: No actual moves available → unit must WAIT, not attempt invalid move
        if not actual_moves:
            raise ValueError(f"No valid movement destinations for unit {unit_id} - should use WAIT action")
        
        # Strategy: Move toward nearest enemy for aggressive positioning
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        if enemies:
            # Find nearest enemy
            nearest_enemy = min(enemies, key=lambda e: abs(e["col"] - unit["col"]) + abs(e["row"] - unit["row"]))
            enemy_pos = (nearest_enemy["col"], nearest_enemy["row"])
            
            # Select move that gets closest to nearest enemy
            best_move = min(actual_moves, 
                           key=lambda dest: abs(dest[0] - enemy_pos[0]) + abs(dest[1] - enemy_pos[1]))
            
            # Only log once per movement action
            if not hasattr(self, '_logged_moves'):
                self._logged_moves = set()
            
            move_key = f"{unit_id}_{current_pos}_{best_move}"
            if move_key not in self._logged_moves:
                self._logged_moves.add(move_key)
            
            return best_move
        else:
            # No enemies - just take first available move
            selected = actual_moves[0]
            return selected
    
    def _ai_select_shooting_target(self, unit_id: str) -> str:
        """REMOVED: Engine bypassed handler decision tree. Use handler's complete AI_TURN.md flow."""
        raise NotImplementedError("AI shooting should use handler's decision tree, not engine shortcuts")
    
    def _ai_select_charge_target(self, unit_id: str) -> str:
        """AI selects charge target - placeholder implementation."""
        # TODO: Implement charge target selection
        raise NotImplementedError("Charge target selection not implemented")
    
    def _ai_select_combat_target(self, unit_id: str) -> str:
        """AI selects combat target - placeholder implementation."""
        # TODO: Implement combat target selection
        raise NotImplementedError("Combat target selection not implemented")
    
    def _get_reward_mapper(self):
        """Get reward mapper instance with current rewards config."""
        from ai.reward_mapper import RewardMapper
        return RewardMapper(self.rewards_config)
    
    def _build_tactical_context(self, unit: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Build tactical context for reward mapper."""
        action_type = result.get("action")
        
        if action_type == "move":
            # AI_TURN.md COMPLIANCE: Direct access - movement context must provide coordinates
            if "fromCol" not in result:
                raise KeyError(f"Movement context missing required 'fromCol' field: {result}")
            if "fromRow" not in result:
                raise KeyError(f"Movement context missing required 'fromRow' field: {result}")
            if "toCol" not in result:
                raise KeyError(f"Movement context missing required 'toCol' field: {result}")
            if "toRow" not in result:
                raise KeyError(f"Movement context missing required 'toRow' field: {result}")
            old_col = result["fromCol"]
            old_row = result["fromRow"]
            new_col = result["toCol"]
            new_row = result["toRow"]
            
            # Calculate movement context
            moved_closer = self._moved_closer_to_enemies(unit, (old_col, old_row), (new_col, new_row))
            moved_away = self._moved_away_from_enemies(unit, (old_col, old_row), (new_col, new_row))
            moved_to_optimal_range = self._moved_to_optimal_range(unit, (new_col, new_row))
            moved_to_charge_range = self._moved_to_charge_range(unit, (new_col, new_row))
            moved_to_safety = self._moved_to_safety(unit, (new_col, new_row))
            
            # CHANGE 1: Add advanced tactical movement flags
            gained_los_on_priority_target = self._gained_los_on_priority_target(unit, (old_col, old_row), (new_col, new_row))
            moved_to_cover_from_enemies = self._moved_to_cover_from_enemies(unit, (new_col, new_row))
            safe_from_enemy_charges = self._safe_from_enemy_charges(unit, (new_col, new_row))
            safe_from_enemy_ranged = self._safe_from_enemy_ranged(unit, (new_col, new_row))
            
            context = {
                "moved_closer": moved_closer,
                "moved_away": moved_away,
                "moved_to_optimal_range": moved_to_optimal_range,
                "moved_to_charge_range": moved_to_charge_range,
                "moved_to_safety": moved_to_safety,
                "gained_los_on_priority_target": gained_los_on_priority_target,
                "moved_to_cover_from_enemies": moved_to_cover_from_enemies,
                "safe_from_enemy_charges": safe_from_enemy_charges,
                "safe_from_enemy_ranged": safe_from_enemy_ranged
            }
            
            # Handle same-position movement (no actual movement) - REMOVE DEBUG THAT TRIGGERS DOUBLE PROCESSING
            if old_col == new_col and old_row == new_row:
                # Unit didn't actually move - this should be treated as a wait action
                context = {"moved_to_safety": True}  # Conservative choice for no movement
            elif not any(context.values()):
                # If unit moved but no tactical benefit detected, default to moved_closer
                context["moved_closer"] = True
            
            return context
        
        return {}
    
    def _get_all_valid_targets(self, unit: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get all valid targets for unit based on current phase."""
        targets = []
        for enemy in self.game_state["units"]:
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                targets.append(enemy)
        return targets
    
    def _can_melee_units_charge_target(self, target: Dict[str, Any]) -> bool:
        """Check if any friendly melee units can charge this target."""
        current_player = self.game_state["current_player"]
        
        for unit in self.game_state["units"]:
            if (unit["player"] == current_player and 
                unit["HP_CUR"] > 0 and
                unit["CC_DMG"] > 0):  # AI_TURN.md: Direct field access
                
                # Simple charge range check (2d6 movement + unit MOVE)
                distance = abs(unit["col"] - target["col"]) + abs(unit["row"] - target["row"])
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                
                if distance <= max_charge_range:
                    return True
        
        return False
    
    def _moved_to_cover_from_enemies(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit is hidden from enemy RANGED units (melee LoS irrelevant)."""
        enemies = [u for u in self.game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        if not enemies:
            return False
        
        # Count how many RANGED enemies have LoS to this position
        ranged_enemies_with_los = 0
        new_unit_state = unit.copy()
        new_unit_state["col"] = new_pos[0]
        new_unit_state["row"] = new_pos[1]
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            
            # CRITICAL: Use same logic as observation encoding
            # Ranged unit = RNG_RNG > CC_RNG (matches offensive_type calculation)
            is_ranged_unit = enemy["RNG_RNG"] > enemy["CC_RNG"]
            
            if is_ranged_unit and enemy["RNG_RNG"] > 0:
                distance = self._calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Enemy in shooting range and has LoS?
                if distance <= enemy["RNG_RNG"]:
                    if self._check_los_cached(enemy, new_unit_state):
                        ranged_enemies_with_los += 1
        
        # Good cover from ranged = 0 or 1 ranged enemy can see you
        return ranged_enemies_with_los <= 1
    
    def _moved_closer_to_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved closer to enemies."""
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False
        
        old_min_distance = min(abs(old_pos[0] - e["col"]) + abs(old_pos[1] - e["row"]) for e in enemies)
        new_min_distance = min(abs(new_pos[0] - e["col"]) + abs(new_pos[1] - e["row"]) for e in enemies)
        
        return new_min_distance < old_min_distance
    
    def _moved_away_from_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved away from enemies."""
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False
        
        old_min_distance = min(abs(old_pos[0] - e["col"]) + abs(old_pos[1] - e["row"]) for e in enemies)
        new_min_distance = min(abs(new_pos[0] - e["col"]) + abs(new_pos[1] - e["row"]) for e in enemies)
        
        return new_min_distance > old_min_distance
    
    def _moved_to_optimal_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved to optimal shooting range per W40K shooting rules."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if unit["RNG_RNG"] <= 0:
            return False
        
        max_range = unit["RNG_RNG"]
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
        min_range = unit["CC_RNG"]  # Minimum engagement distance
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            # Optimal range: can shoot but not in melee (min_range < distance <= max_range)
            if min_range < distance <= max_range:
                return True
        
        return False
    
    def _moved_closer_to_enemies(self, unit: Dict[str, Any], old_pos: Tuple[int, int], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved closer to the nearest threatening enemy."""
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if not enemies:
            return False
        
        # Find the nearest threatening enemy (has weapons that can harm this unit)
        threatening_enemies = []
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_DMG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'RNG_DMG' field: {enemy}")
            if "CC_DMG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'CC_DMG' field: {enemy}")
            # Enemy is threatening if it has ranged or melee weapons
            if enemy["RNG_DMG"] > 0 or enemy["CC_DMG"] > 0:
                old_distance = abs(old_pos[0] - enemy["col"]) + abs(old_pos[1] - enemy["row"])
                new_distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
                threatening_enemies.append((enemy, old_distance, new_distance))
        
        if not threatening_enemies:
            return False
        
        # Check if moved closer to the nearest threatening enemy
        nearest_enemy = min(threatening_enemies, key=lambda x: x[1])  # Nearest by old distance
        old_distance, new_distance = nearest_enemy[1], nearest_enemy[2]
        
        return new_distance < old_distance
    
    def _moved_to_charge_range(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved to charge range of enemies."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "CC_DMG" not in unit:
            raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
        if unit["CC_DMG"] <= 0:
            return False
        
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_charge_range = unit["MOVE"] + 12  # Average 2d6 charge distance
        
        for enemy in enemies:
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            if distance <= max_charge_range:
                return True
        
        return False
    
    def _moved_to_safety(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit moved to safety from enemy threats."""
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            # Check if moved out of enemy threat range
            distance = abs(new_pos[0] - enemy["col"]) + abs(new_pos[1] - enemy["row"])
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy unit missing required 'CC_RNG' field: {enemy}")
            enemy_threat_range = max(enemy["RNG_RNG"], enemy["CC_RNG"])
            
            if distance > enemy_threat_range:
                return True
        
        return False
    
    def _gained_los_on_priority_target(self, unit: Dict[str, Any], old_pos: Tuple[int, int], 
                                       new_pos: Tuple[int, int]) -> bool:
        """Check if unit gained LoS on its highest-priority target."""
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if unit["RNG_RNG"] <= 0:
            return False
        
        # Get all enemies in shooting range
        enemies_in_range = []
        for enemy in self.game_state["units"]:
            if "player" not in enemy or "HP_CUR" not in enemy:
                raise KeyError(f"Enemy unit missing required fields: {enemy}")
            
            if enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0:
                if "col" not in enemy or "row" not in enemy:
                    raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                
                distance = self._calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                if distance <= unit["RNG_RNG"]:
                    enemies_in_range.append(enemy)
        
        if not enemies_in_range:
            return False
        
        # Find priority target (lowest HP for RangedSwarm units)
        priority_target = min(enemies_in_range, key=lambda e: e.get("HP_CUR", 999))
        
        # Check LoS at old position
        old_unit_state = unit.copy()
        old_unit_state["col"] = old_pos[0]
        old_unit_state["row"] = old_pos[1]
        had_los_before = self._check_los_cached(old_unit_state, priority_target)
        
        # Check LoS at new position
        new_unit_state = unit.copy()
        new_unit_state["col"] = new_pos[0]
        new_unit_state["row"] = new_pos[1]
        has_los_now = self._check_los_cached(new_unit_state, priority_target)
        
        # Gained LoS if didn't have before but have now
        return (not had_los_before) and has_los_now
    
    def _safe_from_enemy_charges(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit is safe from enemy MELEE charges (ranged proximity irrelevant)."""
        enemies = [u for u in self.game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            if "MOVE" not in enemy:
                raise KeyError(f"Enemy missing required 'MOVE' field: {enemy}")
            if "CC_DMG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_DMG' field: {enemy}")
            
            # CRITICAL: Use same logic as observation encoding
            # Melee unit = RNG_RNG <= CC_RNG (opposite of ranged)
            is_melee_unit = enemy["RNG_RNG"] <= enemy["CC_RNG"]
            
            if is_melee_unit and enemy["CC_DMG"] > 0:
                distance = self._calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Max charge distance = MOVE + 9 (2d6 average charge roll)
                max_charge_distance = enemy["MOVE"] + 9
                
                # Unsafe if any melee enemy can charge us
                if distance <= max_charge_distance:
                    return False
        
        # Safe - no melee enemies in charge range
        return True
    
    def _safe_from_enemy_ranged(self, unit: Dict[str, Any], new_pos: Tuple[int, int]) -> bool:
        """Check if unit is beyond range of enemy RANGED units."""
        enemies = [u for u in self.game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        safe_distance_count = 0
        total_ranged_enemies = 0
        
        for enemy in enemies:
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "RNG_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'RNG_RNG' field: {enemy}")
            if "CC_RNG" not in enemy:
                raise KeyError(f"Enemy missing required 'CC_RNG' field: {enemy}")
            
            # Only consider ranged units (matches observation encoding)
            is_ranged_unit = enemy["RNG_RNG"] > enemy["CC_RNG"]
            
            if is_ranged_unit and enemy["RNG_RNG"] > 0:
                total_ranged_enemies += 1
                distance = self._calculate_hex_distance(new_pos[0], new_pos[1], enemy["col"], enemy["row"])
                
                # Safe if beyond their shooting range
                if distance > enemy["RNG_RNG"]:
                    safe_distance_count += 1
        
        if total_ranged_enemies == 0:
            return False  # No bonus if no ranged enemies
        
        # Consider safe if beyond range of 50%+ of ranged enemies
        return safe_distance_count >= (total_ranged_enemies / 2.0)
    
    def _get_reward_mapper_unit_rewards(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Get unit-specific rewards config for reward_mapper."""
        enriched_unit = self._enrich_unit_for_reward_mapper(unit)
        reward_mapper = self._get_reward_mapper()
        return reward_mapper._get_unit_rewards(enriched_unit)

    def _enrich_unit_for_reward_mapper(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich unit data with tactical flags required by reward_mapper."""
        enriched = unit.copy()
        
        # AI_TURN.md COMPLIANCE: NO FALLBACKS - proper error handling
        if self.config and self.config.get("controlled_agent"):
            agent_key = self.config["controlled_agent"]
        elif hasattr(self, 'unit_registry') and self.unit_registry:
            # AI_TURN.md: Direct access - NO DEFAULTS allowed
            if "unitType" not in unit:
                raise KeyError(f"Unit missing required 'unitType' field: {unit}")
            scenario_unit_type = unit["unitType"]
            # Let unit_registry.get_model_key() raise ValueError if unit type not found
            agent_key = self.unit_registry.get_model_key(scenario_unit_type)
        else:
            raise ValueError("Missing both controlled_agent config and unit_registry - cannot determine agent key")
        
        # CRITICAL: Set the agent type as unitType for reward config lookup
        enriched["unitType"] = agent_key
        
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access - NO DEFAULTS
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit}")
        
        # Add required tactical flags based on unit stats
        enriched["is_ranged"] = unit["RNG_RNG"] > unit["CC_RNG"]
        enriched["is_melee"] = not enriched["is_ranged"]
        
        # AI_TURN.md COMPLIANCE: Direct field access for required fields
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        if "RNG_DMG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_DMG' field: {unit}")
        if "CC_DMG" not in unit:
            raise KeyError(f"Unit missing required 'CC_DMG' field: {unit}")
        
        # Map UPPERCASE fields to lowercase for reward_mapper compatibility
        enriched["name"] = unit["unitType"]
        enriched["rng_dmg"] = unit["RNG_DMG"]
        enriched["cc_dmg"] = unit["CC_DMG"]
        
        return enriched
    
    def _get_reward_config_key_for_unit(self, unit: Dict[str, Any]) -> str:
        """Map unit type to reward config key using unit registry."""
        # AI_TURN.md COMPLIANCE: Direct field access required
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        unit_type = unit["unitType"]
        
        # Use unit registry to get agent key (matches rewards config)
        try:
            agent_key = self.unit_registry.get_model_key(unit_type)
            return agent_key
        except ValueError as e:
            # AI_TURN.md COMPLIANCE: NO FALLBACKS - propagate the error
            raise ValueError(f"Failed to get reward config key for unit type '{unit_type}': {e}")

    def _load_units_from_scenario(self, scenario_file, unit_registry):
            """Load units from scenario file - NO FALLBACKS ALLOWED."""
            if not scenario_file:
                raise ValueError("scenario_file is required - no fallbacks allowed")
            if not unit_registry:
                raise ValueError("unit_registry is required - no fallbacks allowed")
            
            import json
            import os
            
            if not os.path.exists(scenario_file):
                raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
            
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
            except Exception as e:
                raise ValueError(f"Failed to parse scenario file {scenario_file}: {e}")
            
            if isinstance(scenario_data, list):
                basic_units = scenario_data
            elif isinstance(scenario_data, dict) and "units" in scenario_data:
                basic_units = scenario_data["units"]
            else:
                raise ValueError(f"Invalid scenario format in {scenario_file}: must have 'units' array")
            
            if not basic_units:
                raise ValueError(f"Scenario file {scenario_file} contains no units")
            
            enhanced_units = []
            for unit_data in basic_units:
                if "unit_type" not in unit_data:
                    raise KeyError(f"Unit missing required 'unit_type' field: {unit_data}")
                
                unit_type = unit_data["unit_type"]
                
                try:
                    full_unit_data = unit_registry.get_unit_data(unit_type)
                except Exception as e:
                    raise ValueError(f"Failed to get unit data for '{unit_type}': {e}")
                
                required_fields = ["id", "player", "col", "row"]
                for field in required_fields:
                    if field not in unit_data:
                        raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                
                enhanced_unit = {
                    "id": str(unit_data["id"]),
                    "player": unit_data["player"],
                    "unitType": unit_type,
                    "col": unit_data["col"],
                    "row": unit_data["row"],
                    "HP_CUR": full_unit_data["HP_MAX"],
                    "HP_MAX": full_unit_data["HP_MAX"],
                    "MOVE": full_unit_data["MOVE"],
                    "T": full_unit_data["T"],
                    "ARMOR_SAVE": full_unit_data["ARMOR_SAVE"],
                    "INVUL_SAVE": full_unit_data["INVUL_SAVE"],
                    "RNG_NB": full_unit_data["RNG_NB"],
                    "RNG_RNG": full_unit_data["RNG_RNG"],
                    "RNG_ATK": full_unit_data["RNG_ATK"],
                    "RNG_STR": full_unit_data["RNG_STR"],
                    "RNG_DMG": full_unit_data["RNG_DMG"],
                    "RNG_AP": full_unit_data["RNG_AP"],
                    "CC_NB": full_unit_data["CC_NB"],
                    "CC_RNG": full_unit_data["CC_RNG"],
                    "CC_ATK": full_unit_data["CC_ATK"],
                    "CC_STR": full_unit_data["CC_STR"],
                    "CC_DMG": full_unit_data["CC_DMG"],
                    "CC_AP": full_unit_data["CC_AP"],
                    "LD": full_unit_data["LD"],
                    "OC": full_unit_data["OC"],
                    "VALUE": full_unit_data["VALUE"],
                    "ICON": full_unit_data["ICON"],
                    "ICON_SCALE": full_unit_data["ICON_SCALE"],
                    "SHOOT_LEFT": full_unit_data["RNG_NB"],
                    "ATTACK_LEFT": full_unit_data["CC_NB"]
                }
                
                enhanced_units.append(enhanced_unit)
            
            return enhanced_units


if __name__ == "__main__":
    print("W40K Engine requires proper config from training system - no standalone execution")