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

import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA version: {torch.version.cuda}")
if torch.cuda.is_available():
    print(f"GPU devices: {torch.cuda.device_count()}")
    print(f"Current device: {torch.cuda.current_device()}")
    print(f"Device name: {torch.cuda.get_device_name()}")



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
            
            # Load base configuration
            self.config = {
                "board": config_loader.get_board_config(),
                "units": self._load_units_from_scenario(scenario_file, unit_registry),
                "rewards_config": rewards_config,
                "training_config_name": training_config_name,
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
        
        # SINGLE SOURCE OF TRUTH - Only game_state object in entire system
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
            
            # Fight state
            "fight_subphase": None,
            "charge_range_rolls": {},
            
            # Board state
            "board_width": self.config.get("board", {}).get("cols", 10),
            "board_height": self.config.get("board", {}).get("rows", 10),
            "wall_hexes": set(map(tuple, self.config.get("board", {}).get("wall_hexes", [])))
        }
        
        # Initialize units from config
        self._initialize_units()
        
        # Gym interface properties - computed from config, no hardcoding
        self.action_space = gym.spaces.Discrete(8)  # 8 semantic actions
        
        # Observation space: match training system expectations (26 features)
        # Old system used: 2 units * 11 features + 4 global = 26 total
        obs_size = 26  # Fixed size for compatibility with existing models
        self.observation_space = gym.spaces.Box(
            low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
        )
    
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
        # BUILT-IN STEP COUNTING - Only location in entire system
        self.game_state["episode_steps"] += 1
        
        # Convert gym integer action to semantic action
        semantic_action = self._convert_gym_action(action)
        
        # Process semantic action with AI_TURN.md compliance
        success, result = self._process_semantic_action(semantic_action)
        
        # Log action ONLY if it's a real agent action (not skip) and successful
        if (self.step_logger and self.step_logger.enabled and 
            semantic_action.get("action") != "skip" and success):
            
            active_unit = self._get_active_unit()
            if active_unit:
                # Build complete action details for step logger
                action_details = {
                    "current_turn": self.game_state["turn"],
                    "unit_with_coords": f"{active_unit['id']}({active_unit['col']}, {active_unit['row']})",
                    "semantic_action": semantic_action
                }
                
                # Add specific data for different action types
                if semantic_action.get("action") == "move":
                    action_details.update({
                        "start_pos": (active_unit["col"], active_unit["row"]),
                        "end_pos": (semantic_action.get("destCol", active_unit["col"]), 
                                  semantic_action.get("destRow", active_unit["row"])),
                        "col": semantic_action.get("destCol", active_unit["col"]),
                        "row": semantic_action.get("destRow", active_unit["row"])
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
                
                self.step_logger.log_action(
                    unit_id=active_unit["id"],
                    action_type=semantic_action.get("action"),
                    phase=self.game_state["phase"],
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
            
            # Find original position from config
            original_config = next((cfg for cfg in unit_configs if cfg["id"] == unit["id"]), None)
            if original_config:
                unit["col"] = original_config["col"]
                unit["row"] = original_config["row"]
        
        # Initialize movement phase for game start
        self._movement_phase_init()
        
        observation = self._build_observation()
        info = {"phase": self.game_state["phase"]}
        
        return observation, info
    
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action using AI_TURN.md state machine.
        
        Phase sequence: move -> shoot -> charge -> fight -> next player
        Actions: {'action': 'move', 'unitId': 1, 'destCol': 5, 'destRow': 3}
        """
        current_phase = self.game_state["phase"]
        
        if current_phase == "move":
            return self._process_movement_phase(action)
        elif current_phase == "shoot":
            return self._process_shooting_phase(action)
        elif current_phase == "charge":
            return self._process_charge_phase(action)
        elif current_phase == "fight":
            return self._process_fight_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}
    
    # ===== MOVEMENT PHASE IMPLEMENTATION =====
    
    def _process_movement_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process movement phase with AI_TURN.md decision tree logic."""
        
        # AI_TURN.md LOOP: Check if phase should complete (empty pool means phase is done)
        if not self.game_state["move_activation_pool"]:
            self._phase_initialized = False
            self._shooting_phase_init()
            return True, {"type": "phase_complete", "next_phase": "shoot", "current_player": self.game_state["current_player"]}
        
        # AI_TURN.md COMPLIANCE: ONLY semantic actions with unitId
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        action_unit_id = str(action["unitId"])        
        active_unit = self._get_unit_by_id(action_unit_id)
        if not active_unit:
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        if active_unit["id"] not in self.game_state["move_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        # AI_IMPLEMENTATION.md: Delegate to pure function
        success, result = movement_handlers.execute_action(self.game_state, active_unit, action, self.config)
        
        # Remove unit from pool and log AFTER successful action
        if success:
            # Remove unit from activation pool
            if active_unit["id"] in self.game_state["move_activation_pool"]:
                pool_before = self.game_state["move_activation_pool"].copy()
                self.game_state["move_activation_pool"].remove(active_unit["id"])
                
                # Create temporary log for this action only
                if "console_logs" not in self.game_state:
                    self.game_state["console_logs"] = []
                
                # Clear any existing logs and add only current action log
                self.game_state["console_logs"] = [
                    f"UNIT REMOVED FROM MOVE POOL: {active_unit['id']} → Pool: {pool_before} → {self.game_state['move_activation_pool']}"
                ]
        
        # AI_TURN.md LOOP: After removing unit, check if pool is now empty (same check condition)
        if success and not self.game_state["move_activation_pool"]:
            self.game_state["console_logs"].append(
                f"PHASE TRANSITION: Pool empty → Moving to shooting phase"
            )
            self._shooting_phase_init()
            result["phase_transition"] = True
            result["next_phase"] = "shoot"
        else:
            # Debug why phase transition didn't happen
            self.game_state["console_logs"].append(
                f"NO PHASE TRANSITION: success={success}, pool_empty={not self.game_state['move_activation_pool']}, pool={self.game_state['move_activation_pool']}"
            )
       
        return success, result
    
    def _build_move_activation_pool(self):
        """Build movement activation pool using AI_IMPLEMENTATION.md delegation."""
        eligible_units = movement_handlers.get_eligible_units(self.game_state)
        self.game_state["move_activation_pool"] = eligible_units
        
        # Add console log for web browser visibility (replace any existing logs)
        self.game_state["console_logs"] = [
            f"MOVE POOL BUILT: Player {self.game_state['current_player']} → Units: {eligible_units}"
        ]
    
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
        AI_SHOOT.md: Engine validation + handler delegation (hybrid approach for unit selection)
        """
        
        # First call to phase? → shooting_phase_start(game_state)
        if not hasattr(self, '_shooting_phase_initialized') or not self._shooting_phase_initialized:
            shooting_handlers.shooting_phase_start(self.game_state)
            self._shooting_phase_initialized = True
        
        # Check phase completion
        if not self.game_state["shoot_activation_pool"]:
            self._shooting_phase_initialized = False
            self._charge_phase_init()
            return True, {"type": "phase_complete", "next_phase": "charge", "current_player": self.game_state["current_player"]}
        
        # Basic action validation (engine responsibility for unit selection)
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        active_unit = self._get_unit_by_id(str(action["unitId"]))
        if not active_unit:
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        if active_unit["id"] not in self.game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        # DELEGATION: Pass validated unit to handler
        success, result = shooting_handlers.execute_action(self.game_state, active_unit, action, self.config)
        
        # Engine handles pool removal after successful action (for now)
        if success and active_unit["id"] in self.game_state["shoot_activation_pool"]:
            self.game_state["shoot_activation_pool"].remove(active_unit["id"])
            
            # Check if pool now empty
            if not self.game_state["shoot_activation_pool"]:
                self._shooting_phase_initialized = False
                self._charge_phase_init()
                result["phase_transition"] = True
                result["next_phase"] = "charge"
        
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
        """Initialize movement phase and build activation pool."""
        self.game_state["phase"] = "move"
        
        # AI_TURN.md: Clear tracking sets at START OF PHASE
        self._tracking_cleanup()
        
        # AI_TURN.md: Build activation pool at START OF PHASE
        self._build_move_activation_pool()  
    
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
        """Validate shooting target using handler delegation."""
        # For training: use silent validation to avoid debug output
        if self.is_training or self.quiet:
            # Simple validation without debug calls
            if target["HP_CUR"] <= 0:
                return False
            if target["player"] == shooter["player"]:
                return False
            # Basic range check without debug
            distance = abs(shooter["col"] - target["col"]) + abs(shooter["row"] - target["row"])
            return distance <= shooter.get("RNG_RNG", 0)
        else:
            # For evaluation: use full handler with debug output
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
        board_width = self.game_state.get("board_width", 25)
        board_height = self.game_state.get("board_height", 25)
        
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
        """Calculate reward for gym interface."""
        if success:
            return 0.1  # Small positive reward for valid actions
        else:
            return -0.1  # Small penalty for invalid actions
    
    # ===== VALIDATION METHODS =====
    
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
        """Convert gym integer action to semantic action format."""
        # Get currently active unit from activation pool
        active_unit = self._get_active_unit()
        
        if not active_unit:
            return {"action": "skip", "unitId": "none"}
        
        # Convert gym action to semantic action
        action_map = {
            0: {"action": "move", "unitId": active_unit["id"], "destCol": active_unit["col"], "destRow": active_unit["row"] - 1},  # North
            1: {"action": "move", "unitId": active_unit["id"], "destCol": active_unit["col"], "destRow": active_unit["row"] + 1},  # South  
            2: {"action": "move", "unitId": active_unit["id"], "destCol": active_unit["col"] + 1, "destRow": active_unit["row"]},  # East
            3: {"action": "move", "unitId": active_unit["id"], "destCol": active_unit["col"] - 1, "destRow": active_unit["row"]},  # West
            4: {"action": "shoot", "unitId": active_unit["id"], "targetId": self._find_nearest_enemy(active_unit)},
            5: {"action": "charge", "unitId": active_unit["id"], "targetId": self._find_nearest_enemy(active_unit)},
            6: {"action": "combat", "unitId": active_unit["id"], "targetId": self._find_nearest_enemy(active_unit)},
            7: {"action": "skip", "unitId": active_unit["id"]}
        }
        
        return action_map.get(action, {"action": "skip", "unitId": active_unit["id"]})
    
    def _get_active_unit(self) -> Optional[Dict[str, Any]]:
        """Get currently active unit from appropriate activation pool."""
        current_phase = self.game_state["phase"]
        
        if current_phase == "move" and self.game_state["move_activation_pool"]:
            unit_id = self.game_state["move_activation_pool"][0]
            return self._get_unit_by_id(unit_id)
        elif current_phase == "shoot" and self.game_state["shoot_activation_pool"]:
            unit_id = self.game_state["shoot_activation_pool"][0]
            return self._get_unit_by_id(unit_id)
        
        # If no active unit in pool, return any eligible unit
        for unit in self.game_state["units"]:
            if unit["HP_CUR"] > 0:
                return unit
        
        return None
    
    def _find_nearest_enemy(self, unit: Dict[str, Any]) -> Optional[str]:
        """Find nearest enemy unit for targeting actions."""
        enemies = [u for u in self.game_state["units"] 
                  if u["player"] != unit["player"] and u["HP_CUR"] > 0]
        
        if not enemies:
            return None
        
        # Return ID of first enemy (simple targeting)
        return enemies[0]["id"]
    
    def _load_units_from_scenario(self, scenario_file, unit_registry):
        """Load units from scenario file for training system compatibility."""
        if not scenario_file or not unit_registry:
            # Return minimal test units if no scenario provided
            return [
                {
                    "id": "test_unit_1", "player": 0, "unitType": "TestUnit",
                    "col": 1, "row": 1, "HP_CUR": 2, "HP_MAX": 2, "MOVE": 6,
                    "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
                    "RNG_NB": 1, "RNG_RNG": 24, "RNG_ATK": 3, "RNG_STR": 4, "RNG_DMG": 1, "RNG_AP": 0,
                    "CC_NB": 1, "CC_RNG": 1, "CC_ATK": 3, "CC_STR": 4, "CC_DMG": 1, "CC_AP": 0,
                    "LD": 7, "OC": 1, "VALUE": 10, "ICON": "marine", "ICON_SCALE": 1,
                    "SHOOT_LEFT": 1, "ATTACK_LEFT": 1
                }
            ]
        
        import json
        import os
        
        # Load scenario file
        try:
            with open(scenario_file, 'r') as f:
                scenario_data = json.load(f)
            
            if isinstance(scenario_data, list):
                basic_units = scenario_data
            elif isinstance(scenario_data, dict) and "units" in scenario_data:
                basic_units = scenario_data["units"]
            else:
                raise ValueError("Invalid scenario format")
            
            # Enhance units with registry data
            enhanced_units = []
            for unit_data in basic_units:
                unit_type = unit_data["unit_type"]
                
                try:
                    full_unit_data = unit_registry.get_unit_data(unit_type)
                except:
                    # Fallback if unit registry fails
                    full_unit_data = {
                        "HP_MAX": 2, "MOVE": 6, "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
                        "RNG_NB": 1, "RNG_RNG": 24, "RNG_ATK": 3, "RNG_STR": 4, "RNG_DMG": 1, "RNG_AP": 0,
                        "CC_NB": 1, "CC_RNG": 1, "CC_ATK": 3, "CC_STR": 4, "CC_DMG": 1, "CC_AP": 0,
                        "LD": 7, "OC": 1, "VALUE": 10, "ICON": "default", "ICON_SCALE": 1
                    }
                
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
            
        except Exception as e:
            if not hasattr(self, 'quiet') or not self.quiet:
                print(f"Warning: Failed to load scenario {scenario_file}: {e}")
            
            # Return minimal test scenario
            # Return minimal test scenario
            return [
                {
                    "id": "fallback_unit", "player": 0, "unitType": "TestUnit",
                    "col": 1, "row": 1, "HP_CUR": 2, "HP_MAX": 2, "MOVE": 6,
                    "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
                    "RNG_NB": 1, "RNG_RNG": 24, "RNG_ATK": 3, "RNG_STR": 4, "RNG_DMG": 1, "RNG_AP": 0,
                    "CC_NB": 1, "CC_RNG": 1, "CC_ATK": 3, "CC_STR": 4, "CC_DMG": 1, "CC_AP": 0,
                    "LD": 7, "OC": 1, "VALUE": 10, "ICON": "default", "ICON_SCALE": 1,
                    "SHOOT_LEFT": 1, "ATTACK_LEFT": 1
                }
            ]


def create_test_config() -> Dict[str, Any]:
    """Create test configuration for validation."""
    return {
        "board": {
            "width": 10,
            "height": 10,
            "wall_hexes": [[2, 2], [3, 3]]
        },
        "units": [
            {
                "id": "marine_1",
                "player": 0,
                "unitType": "SpaceMarine_Infantry_Troop_RangedTroop",
                "col": 1,
                "row": 1,
                "HP_CUR": 2,
                "HP_MAX": 2,
                "MOVE": 6,
                "T": 4,
                "ARMOR_SAVE": 3,
                "INVUL_SAVE": 7,
                "RNG_NB": 1,
                "RNG_RNG": 24,
                "RNG_ATK": 3,
                "RNG_STR": 4,
                "RNG_DMG": 1,
                "RNG_AP": 0,
                "CC_NB": 1,
                "CC_RNG": 1,
                "CC_ATK": 3,
                "CC_STR": 4,
                "CC_DMG": 1,
                "CC_AP": 0
            },
            {
                "id": "ork_1",
                "player": 1,
                "unitType": "Ork_Infantry_Troop_MeleeTroop",
                "col": 8,
                "row": 8,
                "HP_CUR": 1,
                "HP_MAX": 1,
                "MOVE": 6,
                "T": 5,
                "ARMOR_SAVE": 6,
                "INVUL_SAVE": 7,
                "RNG_NB": 1,
                "RNG_RNG": 12,
                "RNG_ATK": 5,
                "RNG_STR": 4,
                "RNG_DMG": 1,
                "RNG_AP": 0,
                "CC_NB": 2,
                "CC_RNG": 1,
                "CC_ATK": 3,
                "CC_STR": 4,
                "CC_DMG": 1,
                "CC_AP": 0
            }
        ]
    }


if __name__ == "__main__":
    # Basic validation test
    config = create_test_config()
    engine = W40KEngine(config)
    
    print("W40K Engine initialized successfully!")
    print(f"Compliance violations: {engine.validate_compliance()}")
    
    # Test basic functionality
    obs, info = engine.reset()
    print(f"Initial observation size: {len(obs)}")
    print(f"Initial phase: {info['phase']}")
    
    # Test movement
    obs, reward, done, truncated, info = engine.step(2)  # Move East
    #print(f"After movement - Success: {info['success']}, Phase: {info['phase']}")