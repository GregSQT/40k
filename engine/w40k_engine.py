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
                unit_registry=None, quiet=False, **kwargs):
        """Initialize W40K engine with AI_TURN.md compliance - training system compatible."""
        
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
            
            self.config = {
                "board": board_config,
                "units": self._load_units_from_scenario(scenario_file, unit_registry),
                "rewards_config": rewards_config,
                "training_config_name": training_config_name,
                "training_config": self.training_config,
                "controlled_agent": controlled_agent,
                "active_agents": active_agents,
                "quiet": quiet
            }
        else:
            # Use provided config directly
            self.config = config
        
        # Store training system compatibility parameters
        self.quiet = quiet
        self.unit_registry = unit_registry
        self.step_logger = None  # Will be set by training system if enabled
        
        # Detect training context to suppress debug logs
        self.is_training = training_config_name in ["debug", "default", "conservative", "aggressive"]
        
        # PvE mode configuration
        self.is_pve_mode = config.get("pve_mode", False) if isinstance(config, dict) else False
        self._ai_model = None
        
        # CRITICAL: Initialize game_state FIRST before any other operations
        self.game_state = {
            # Core game state
            "units": [],
            "current_player": 0,
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
        self.action_space = gym.spaces.Discrete(8)  # Base action space
        self._current_valid_actions = list(range(8))  # Will be masked dynamically
        
        # Observation space: match training system expectations (26 features)
        # Old system used: 2 units * 11 features + 4 global = 26 total
        obs_size = 26  # Fixed size for compatibility with existing models
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
        )
        
        # Load AI model for PvE mode
        if self.is_pve_mode:
            self._load_ai_model_for_pve()
    
    def _load_ai_model_for_pve(self):
        """Load trained AI model for PvE Player 2."""
        try:
            from stable_baselines3 import DQN
            
            # Determine AI model path
            ai_model_key = "SpaceMarine"  # Default AI opponent
            if self.unit_registry:
                # Get model key for player 1 units
                player1_units = [u for u in self.game_state["units"] if u["player"] == 1]
                if player1_units:
                    ai_model_key = self.unit_registry.get_model_key(player1_units[0]["unitType"])
            
            model_path = f"ai/models/default_model_{ai_model_key}.zip"
            
            if os.path.exists(model_path):
                self._ai_model = DQN.load(model_path)
                print(f"PvE: Loaded AI model for Player 2: {ai_model_key}")
            else:
                print(f"PvE: No AI model found at {model_path} - using fallback AI")
                
        except Exception as e:
            print(f"PvE: Failed to load AI model: {e}")
            self._ai_model = None
    
    def _initialize_units(self):
        """Initialize units with UPPERCASE field validation."""
        unit_configs = self.config.get("units", [])
        
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
            "unitType": config.get("unitType", "default"),
            
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
            # print(f"TERMINATION DEBUG: Turn {self.game_state['turn']}, max_turns={max_turns}, has_training_config=True")
            if max_turns and self.game_state["turn"] > max_turns:
                # Turn limit exceeded - return terminated episode immediately
                observation = self._build_observation()
                info = {"turn_limit_exceeded": True, "winner": self._determine_winner()}
                return observation, 0.0, True, False, info
        # else:
        #     print(f"TERMINATION DEBUG: Turn {self.game_state['turn']}, has_training_config=False")
        
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
        # print(f"STEP LOGGER DETECTION: has_step_logger={hasattr(self, 'step_logger')}, step_logger={getattr(self, 'step_logger', 'None')}")
        if hasattr(self, 'step_logger') and self.step_logger and self.step_logger.enabled:
            unit_id = semantic_action.get("unitId")
            print(f"STEP LOGGER ACTIVE: Processing unit {unit_id}")
            if unit_id:
                pre_unit = self._get_unit_by_id(str(unit_id))
                if pre_unit:
                    pre_action_positions[str(unit_id)] = (pre_unit["col"], pre_unit["row"])
                    print(f"STEP LOGGER DEBUG: Captured pre-action position for unit {unit_id}: {(pre_unit['col'], pre_unit['row'])}")
        
        # Log action ONLY if it's a real agent action with valid unit
        if (self.step_logger and self.step_logger.enabled and success):
            
            action_type = semantic_action.get("action")
            unit_id = semantic_action.get("unitId")
            
            # Filter out system actions and invalid entries
            if (action_type in ["move", "shoot", "charge", "combat"] and
                unit_id != "none" and unit_id != "SYSTEM"):
                
                # Get unit coordinates AFTER action execution using semantic action unitId
                updated_unit = self._get_unit_by_id(str(unit_id)) if unit_id else None
                if updated_unit:
                    # Build complete action details for step logger with CURRENT coordinates
                    action_details = {
                        "current_turn": self.game_state["turn"],
                        "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']}, {updated_unit['row']})",
                        "semantic_action": semantic_action
                    }
                
                    # Add specific data for different action types
                    if semantic_action.get("action") == "move":
                        # Use captured pre-action position for accurate start_pos
                        start_pos = pre_action_positions.get(str(unit_id), (updated_unit["col"], updated_unit["row"]))
                        end_pos = (updated_unit["col"], updated_unit["row"])  # Use unit's actual final position
                        print(f"STEP LOGGER FIX: Unit {unit_id}, pre_positions={pre_action_positions}, start_pos={start_pos}, end_pos={end_pos}")
                        action_details.update({
                            "start_pos": start_pos,
                            "end_pos": end_pos,
                            "col": updated_unit["col"],  # Use actual final position
                            "row": updated_unit["row"]   # Use actual final position
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
            
        return observation, reward, terminated, truncated, info
    
    def execute_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute semantic actions directly from frontend.
        Public interface for human player actions.
        """
        return self._process_semantic_action(action)
    
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
        unit_configs = self.config.get("units", [])
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
        
        # CRITICAL: Reject invalid actions immediately for proper training
        if action.get("action") == "invalid":
            return False, {"error": action.get("error", "invalid_action"), "phase": current_phase}
        
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
        
        # First call to phase? → movement_phase_start(game_state)
        if not hasattr(self, '_movement_phase_initialized') or not self._movement_phase_initialized:
            movement_handlers.movement_phase_start(self.game_state)
            self._movement_phase_initialized = True
        
        # **FULL DELEGATION**: movement_handlers.execute_action(game_state, None, action, config)
        success, result = movement_handlers.execute_action(self.game_state, None, action, self.config)
        
        # DEBUG: Check if unit position actually changed
        if success and action.get("action") == "move":
            unit_id = action.get("unitId")
            if unit_id:
                unit = self._get_unit_by_id(unit_id)
                if unit:
                    print(f"DEBUG: Unit {unit_id} actual position after movement: ({unit['col']}, {unit['row']})")
                    expected_col = action.get("destCol", "unknown")
                    expected_row = action.get("destRow", "unknown") 
                    print(f"DEBUG: Expected position: ({expected_col}, {expected_row})")
                    # Check if unit moved to its destination (this should always be true for valid moves)
                    if expected_col == unit["col"] and expected_row == unit["row"]:
                        # This is actually CORRECT behavior - unit reached its destination
                        pass
                    else:
                        print(f"DEBUG: ERROR - Unit {unit_id} failed to reach destination: expected ({expected_col}, {expected_row}) but at ({unit['col']}, {unit['row']})")
        
        # CRITICAL FIX: Handle failed actions to prevent infinite loops
        if not success and result.get("error") == "invalid_destination":
            # Force unit to skip/wait when movement fails
            print(f"DEBUG: Movement failed, forcing unit to skip")
            skip_result = movement_handlers.execute_action(self.game_state, None, {"action": "skip", "unitId": action.get("unitId")}, self.config)
            print(f"DEBUG: Skip action result: {skip_result}")
            if isinstance(skip_result, tuple):
                success, result = skip_result
            else:
                success, result = True, skip_result
        
        # Check response for phase_complete flag
        if result.get("phase_complete"):
            print(f"DEBUG: Phase completion detected, transitioning to shoot phase")
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
        shooting_handlers.shooting_phase_start(self.game_state)
    
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
            print(f"🔍 ENGINE DEBUG: Handler returned non-tuple: {type(handler_response)}, value: {handler_response}")
        
        # Handle phase transitions signaled by handler
        print(f"DEBUG ENGINE: Checking phase transition - phase_complete={result.get('phase_complete')}, phase_transition={result.get('phase_transition')}")
        if result.get("phase_complete") or result.get("phase_transition"):
            next_phase = result.get("next_phase")
            print(f"DEBUG ENGINE: Phase transition triggered - next_phase={next_phase}")
            if next_phase == "move":
                print(f"DEBUG ENGINE: Calling _movement_phase_init()")
                self._movement_phase_init()
            else:
                print(f"DEBUG ENGINE: Next phase is not 'move', ignoring transition")
        else:
            print(f"DEBUG ENGINE: No phase transition flags found in result")
        
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
        
        # Phase progression logic
        if self.game_state["phase"] == "move":
            self._shooting_phase_init()
        elif self.game_state["phase"] == "shoot":
            self._charge_phase_init()
        elif self.game_state["phase"] == "charge":
            self._fight_phase_init()
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
        """Execute semantic shooting action with AI_TURN.md restrictions."""
        
        action_type = action.get("action")
        
        if action_type == "shoot":
            target_id = action.get("targetId")
            if not target_id:
                return False, {"error": "missing_target", "action": action}
            
            target = self._get_unit_by_id(str(target_id))
            if not target:
                return False, {"error": "target_not_found", "targetId": target_id}
            
            return self._attempt_shooting(unit, target)
            
        elif action_type == "skip":
            self.game_state["units_shot"].add(unit["id"])
            return True, {"action": "skip", "unitId": unit["id"]}
            
        elif action_type == "advance_phase":
            # Handle empty pool phase advancement
            if action.get("phase") == "shoot":
                return True, shooting_handlers._shooting_phase_complete(self.game_state)
                
        else:
            return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}
    
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
        """Build observation vector matching old system format (26 elements)."""
        obs = np.zeros(26, dtype=np.float32)
        
        # Minimal logging only for training issues
        pass
        
        # Global features (4 elements) - normalized to 0-1 range
        obs[0] = self.game_state["current_player"]  # 0 or 1
        obs[1] = {"move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}[self.game_state["phase"]]
        obs[2] = min(1.0, self.game_state["turn"] / 10.0)  # Normalize turn
        obs[3] = min(1.0, self.game_state["episode_steps"] / 100.0)  # Normalize steps
        
        # Get units and separate by player
        all_units = [u for u in self.game_state["units"] if u["HP_CUR"] > 0]
        ai_units = [u for u in all_units if u["player"] == 1][:2]  # Max 2 AI units
        enemy_units = [u for u in all_units if u["player"] == 0][:2]  # Max 2 enemy units
        
        # AI units (2 units * 11 features = 22 elements, positions 4-25)
        board_width = self.game_state.get("board_cols")
        board_height = self.game_state.get("board_rows")
        
        if board_width is None:
            raise RuntimeError("board_cols is None - config loading failed, check config/board_config.json")
        if board_height is None:
            raise RuntimeError("board_rows is None - config loading failed, check config/board_config.json")
        
        for i in range(2):
            base_idx = 4 + i * 11
            if i < len(ai_units):
                unit = ai_units[i]
                obs[base_idx] = unit["col"] / board_width  # Normalized position
                obs[base_idx + 1] = unit["row"] / board_height
                obs[base_idx + 2] = unit["HP_CUR"] / unit["HP_MAX"]  # Health ratio
                obs[base_idx + 3] = 1.0 if unit["id"] in self.game_state["units_moved"] else 0.0
                obs[base_idx + 4] = 1.0 if unit["id"] in self.game_state["units_shot"] else 0.0
                obs[base_idx + 5] = 1.0 if unit["id"] in self.game_state["units_charged"] else 0.0
                obs[base_idx + 6] = 1.0 if unit["id"] in self.game_state["units_attacked"] else 0.0
                obs[base_idx + 7] = min(1.0, unit.get("RNG_RNG", 0) / 24.0)  # Normalized range
                obs[base_idx + 8] = min(1.0, unit.get("RNG_DMG", 0) / 5.0)  # Normalized damage
                obs[base_idx + 9] = min(1.0, unit.get("CC_DMG", 0) / 5.0)  # Normalized melee damage
                obs[base_idx + 10] = 1.0  # Alive flag
        
        return obs
    
    def _calculate_reward(self, success: bool, result: Dict[str, Any]) -> float:
        """Calculate reward using actual acting unit with reward mapper integration."""
        if not success:
            if isinstance(result, dict) and "forbidden_in" in result.get("error", ""):
                return -0.5  # Heavy penalty for phase violations
            else:
                return -0.1  # Small penalty for other invalid actions
        
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
            original_type = acting_unit.get('unitType', 'unknown')
            agent_type = enriched_unit.get('unitType', 'unknown')
            controlled_agent = self.config.get('controlled_agent', 'none') if self.config else 'none'
            print(f"DEBUG: Unit {acting_unit['id']} ({original_type}) -> Using agent rewards: {agent_type} (controlled_agent: {controlled_agent})")
        
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
            
            if not self.quiet:
                print(f"DEBUG: Shooting reward - Base: {base_reward}, Target bonus: {target_bonus}, Result: {result_bonus}, Final: {final_reward}")
            
            return final_reward
        elif action_type == "move":
            old_pos = (result.get("fromCol", 0), result.get("fromRow", 0))
            new_pos = (result.get("toCol", 0), result.get("toRow", 0))
            tactical_context = self._build_tactical_context(acting_unit, result)
            return reward_mapper.get_movement_reward(enriched_unit, old_pos, new_pos, tactical_context)
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
            modifiers = unit_rewards.get("situational_modifiers", {})
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
    
    def _convert_gym_action(self, action: int) -> Dict[str, Any]:
        """Convert gym integer action to semantic action - AI selects units dynamically."""
        action_int = int(action.item()) if hasattr(action, 'item') else int(action)
        current_phase = self.game_state["phase"]
        
        # Get eligible units for current phase - AI_TURN.md sequential activation
        eligible_units = self._get_eligible_units_for_current_phase()
        
        if not eligible_units:
            return {"action": "invalid", "error": "no_eligible_units"}
        
        if current_phase == "move":
            if action_int == 0:  # Move action
                selected_unit = self._ai_select_unit(eligible_units, "move")
                try:
                    destination = self._ai_select_movement_destination(selected_unit)
                    return {
                        "action": "move", 
                        "unitId": selected_unit, 
                        "destCol": destination[0], 
                        "destRow": destination[1]
                    }
                except ValueError:
                    # No valid moves - convert to WAIT action
                    if not self.quiet:
                        print(f"DEBUG: Converting move to wait for unit {selected_unit} - no valid destinations")
                    return {"action": "wait", "unitId": selected_unit}
            elif action_int == 7:  # WAIT - agent chooses not to move
                selected_unit = self._ai_select_unit(eligible_units, "wait")
                return {"action": "wait", "unitId": selected_unit}
        elif current_phase == "shoot":
            if action_int == 4:  # Shoot action
                selected_unit = self._ai_select_unit(eligible_units, "shoot")
                return {
                    "action": "shoot", 
                    "unitId": selected_unit
                    # Handler will build target pool and select target per AI_TURN.md
                }
            elif action_int == 7:  # WAIT - agent chooses not to shoot
                selected_unit = self._ai_select_unit(eligible_units, "wait")
                return {"action": "wait", "unitId": selected_unit}
        elif current_phase == "charge":
            if action_int == 5:  # Charge action
                selected_unit = self._ai_select_unit(eligible_units, "charge")
                target = self._ai_select_charge_target(selected_unit)
                return {
                    "action": "charge", 
                    "unitId": selected_unit, 
                    "targetId": target
                }
            elif action_int == 7:  # WAIT - agent chooses not to charge
                selected_unit = self._ai_select_unit(eligible_units, "wait")
                return {"action": "wait", "unitId": selected_unit}
        elif current_phase == "fight":
            if action_int == 6:  # Fight action - NO WAIT option in fight phase
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
        """Get valid action types for current phase with correct WAIT vs FIGHT semantics."""
        if phase == "move":
            return [0, 7]  # Move + wait
        elif phase == "shoot":
            return [4, 7]  # Shoot + wait
        elif phase == "charge":
            return [5, 7]  # Charge + wait
        elif phase == "fight":
            return [6]  # Fight only - NO WAIT in fight phase
        else:
            return [7]  # Only wait for unknown phases
    
    def _get_eligible_units_for_current_phase(self) -> List[Dict[str, Any]]:
        """Get eligible units for current phase using handler delegation."""
        current_phase = self.game_state["phase"]
        
        if current_phase == "move":
            eligible_unit_ids = movement_handlers.get_eligible_units(self.game_state)
            return [self._get_unit_by_id(uid) for uid in eligible_unit_ids if self._get_unit_by_id(uid)]
        elif current_phase == "shoot":
            # CRITICAL: Use existing cleaned pool, don't rebuild and overwrite handler cleanup
            eligible_unit_ids = self.game_state.get("shoot_activation_pool", [])
            return [self._get_unit_by_id(uid) for uid in eligible_unit_ids if self._get_unit_by_id(uid)]
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
            print(f"AI model error: {e}")
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
                print(f"AI ACTION: Unit {unit_id} moved from {current_pos} to {best_move} (targeting enemy at {enemy_pos})")
                self._logged_moves.add(move_key)
            
            return best_move
        else:
            # No enemies - just take first available move
            selected = actual_moves[0]
            print(f"AI ACTION: Unit {unit_id} moved from {current_pos} to {selected}")
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
            old_col = result.get("fromCol", unit["col"])
            old_row = result.get("fromRow", unit["row"])
            new_col = result.get("toCol", unit["col"])
            new_row = result.get("toRow", unit["row"])
            
            # Calculate movement context
            moved_closer = self._moved_closer_to_enemies(unit, (old_col, old_row), (new_col, new_row))
            moved_away = self._moved_away_from_enemies(unit, (old_col, old_row), (new_col, new_row))
            moved_to_optimal_range = self._moved_to_optimal_range(unit, (new_col, new_row))
            moved_to_charge_range = self._moved_to_charge_range(unit, (new_col, new_row))
            moved_to_safety = self._moved_to_safety(unit, (new_col, new_row))
            
            context = {
                "moved_closer": moved_closer,
                "moved_away": moved_away,
                "moved_to_optimal_range": moved_to_optimal_range,
                "moved_to_charge_range": moved_to_charge_range,
                "moved_to_safety": moved_to_safety
            }
            
            # Debug tactical context
            if not self.quiet:
                print(f"DEBUG: Tactical context for unit {unit['id']}: {context}")
                print(f"DEBUG: Movement from ({old_col}, {old_row}) to ({new_col}, {new_row})")
            
            # Handle same-position movement (no actual movement)
            if old_col == new_col and old_row == new_row:
                # Unit didn't actually move - this should be treated as a wait action
                context = {"moved_to_safety": True}  # Conservative choice for no movement
                if not self.quiet:
                    print(f"DEBUG: No actual movement detected, setting moved_to_safety=True")
            elif not any(context.values()):
                # If unit moved but no tactical benefit detected, default to moved_closer
                context["moved_closer"] = True
                if not self.quiet:
                    print(f"DEBUG: Movement detected but no tactical context, defaulting to moved_closer=True")
            
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
                unit.get("CC_DMG", 0) > 0):  # Has melee capability
                
                # Simple charge range check (2d6 movement + unit MOVE)
                distance = abs(unit["col"] - target["col"]) + abs(unit["row"] - target["row"])
                max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                
                if distance <= max_charge_range:
                    return True
        
        return False
    
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
        if unit.get("RNG_RNG", 0) <= 0:
            return False
        
        max_range = unit["RNG_RNG"]
        min_range = unit.get("CC_RNG", 1)  # Minimum engagement distance
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
            # Enemy is threatening if it has ranged or melee weapons
            if enemy.get("RNG_DMG", 0) > 0 or enemy.get("CC_DMG", 0) > 0:
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
        if unit.get("CC_DMG", 0) <= 0:
            return False
        
        enemies = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u["HP_CUR"] > 0]
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
            enemy_threat_range = max(enemy.get("RNG_RNG", 0), enemy.get("CC_RNG", 1))
            
            if distance > enemy_threat_range:
                return True
        
        return False
    
    def _get_reward_mapper_unit_rewards(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Get unit-specific rewards config for reward_mapper."""
        enriched_unit = self._enrich_unit_for_reward_mapper(unit)
        reward_mapper = self._get_reward_mapper()
        return reward_mapper._get_unit_rewards(enriched_unit)

    def _enrich_unit_for_reward_mapper(self, unit: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich unit data with tactical flags required by reward_mapper."""
        enriched = unit.copy()
        
        # Remove debug spam
        pass
        
        # Use the training agent key directly from config
        # The controlled_agent parameter specifies which agent reward config to use
        if self.config and self.config.get("controlled_agent"):
            agent_key = self.config["controlled_agent"]
        elif hasattr(self, 'unit_registry') and self.unit_registry:
            # Get agent key from unit registry as fallback
            scenario_unit_type = unit.get("unitType", "unknown")
            try:
                agent_key = self.unit_registry.get_model_key(scenario_unit_type)
            except (ValueError, AttributeError):
                # Final fallback based on unit stats
                is_ranged = unit.get("RNG_RNG", 0) > unit.get("CC_RNG", 1)
                agent_key = "SpaceMarine_Infantry_Troop_RangedSwarm" if is_ranged else "SpaceMarine_Infantry_Troop_MeleeTroop"
        else:
            # Emergency fallback
            is_ranged = unit.get("RNG_RNG", 0) > unit.get("CC_RNG", 1)
            agent_key = "SpaceMarine_Infantry_Troop_RangedSwarm" if is_ranged else "SpaceMarine_Infantry_Troop_MeleeTroop"
        
        # CRITICAL: Set the agent type as unitType for reward config lookup
        enriched["unitType"] = agent_key
        
        # Add required tactical flags based on unit stats
        enriched["is_ranged"] = unit.get("RNG_RNG", 0) > unit.get("CC_RNG", 1)
        enriched["is_melee"] = not enriched["is_ranged"]
        
        # Map UPPERCASE fields to lowercase for reward_mapper compatibility
        enriched["name"] = unit.get("unitType", f"Unit_{unit['id']}")
        enriched["rng_dmg"] = unit.get("RNG_DMG", 0)
        enriched["cc_dmg"] = unit.get("CC_DMG", 0)
        
        return enriched
    
    def _get_reward_config_key_for_unit(self, unit: Dict[str, Any]) -> str:
        """Map unit type to reward config key using unit registry."""
        unit_type = unit.get("unitType", "unknown")
        
        # Use unit registry to get agent key (matches rewards config)
        try:
            agent_key = self.unit_registry.get_model_key(unit_type)
            return agent_key
        except ValueError:
            # Fallback: determine from unit stats
            is_ranged = unit.get("RNG_RNG", 0) > unit.get("CC_RNG", 1)
            return "SpaceMarineRanged" if is_ranged else "SpaceMarineMelee"

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
    #print(f"After movement - Success: {info['success']}, Phase: {info['phase']}")