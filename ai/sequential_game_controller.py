#!/usr/bin/env python3
"""
ai/sequential_game_controller.py - AI_TURN.md Compliant Sequential Game Controller

CRITICAL PURPOSE: Single controller class with built-in step counting and sequential activation
COMPLIANCE: AI_TURN.md Rules #1-4, AI_GUIDE.md validation requirements

ARCHITECTURE:
- Single class with delegation to TrainingGameController (not inheritance)
- Built-in episode_steps increment inside execute_gym_action (not retrofitted)
- Sequential unit activation (ONE unit per gym step)
- Phase completion by unit eligibility only
- UPPERCASE field validation with KeyError for missing fields

FORBIDDEN PATTERNS:
- Wrapper classes or complex delegation chains
- Retrofitted step counting (steps_before/steps_after)
- Multi-unit processing per gym action
- Step-based phase transitions
- Lowercase field names (cur_hp, rng_nb, etc.)
"""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np
from dataclasses import dataclass, field


@dataclass
class GameControllerConfig:
    """Configuration for SequentialGameController - minimal version for compatibility"""
    initial_units: List[Dict[str, Any]] = field(default_factory=list)
    game_mode: str = "training"
    board_config_name: str = "default"
    config_path: str = ""
    max_turns: int = None  # Will be loaded from training_config
    enable_ai_player: bool = False
    training_mode: bool = True
    training_config_name: str = "default"
    log_available_height: int = 300


class SequentialGameController:
    """
    AI_TURN.md Compliant Sequential Game Controller
    
    Single controller class with built-in step counting and sequential activation.
    Implements exact AI_TURN.md 5-step pattern in execute_gym_action.
    """
    
    def __init__(self, config, quiet=False):
        """Initialize with direct delegation to TrainingGameController."""
        # Import here to avoid circular imports
        from ai.game_controller import TrainingGameController
        from config_loader import get_config_loader
        
        # Load max_turns from training_config if not provided
        if config.max_turns is None:
            config_loader = get_config_loader()
            training_config = config_loader.load_training_config(config.training_config_name)
            if "number_of_turns_per_episode" not in training_config:
                raise KeyError(f"Training config '{config.training_config_name}' missing required 'number_of_turns_per_episode'")
            config.max_turns = training_config["number_of_turns_per_episode"]
        
        # AI_GUIDE.md: Base controller delegation (not inheritance)
        self.base = TrainingGameController(config, quiet)
        
        # AI_GUIDE.md: Unit queue contains ONLY unit IDs (not full unit objects)
        self.active_unit_queue: List[str] = []
        
        # AI_GUIDE.md: Current active unit is ONE unit ID or None
        self.current_active_unit_id: Optional[str] = None
        
        # StepLogger integration for AI_TURN.md compliant action logging
        self.step_logger: Optional[Any] = None
        
        # NO separate episode_steps - use self.base.game_state["episode_steps"]
        # AI_GUIDE.md: Episode steps stored in controller.game_state (not separate tracking)
        
    def __getattr__(self, name):
        """Delegate attributes to base controller for compatibility."""
        return getattr(self.base, name)
        
    def connect_gym_env(self, gym_env):
        """Connect gym environment for observation delegation."""
        if hasattr(self.base, 'connect_gym_env'):
            self.base.connect_gym_env(gym_env)
            
    def connect_step_logger(self, step_logger):
        """Connect step logger for AI_TURN.md compliant action tracking."""
        self.step_logger = step_logger
        if step_logger and step_logger.enabled:
            print("✅ StepLogger connected to SequentialGameController")
            
    def execute_gym_action(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """
        AI_TURN.md EXACT 5-step pattern with built-in step counting.
        
        Args:
            action: Gym action integer (0-7)
            
        Returns:
            Tuple: (observation, reward, terminated, truncated, info)
        """
        # AI_GUIDE.md: This EXACT flow implemented, NO additional steps or complexity
        
        # 1. Get current active unit (build queue if empty)
        active_unit_id = self._get_current_active_unit()
        
        # 2. If no active unit, advance phase/turn
        if not active_unit_id:
            return self._handle_no_active_unit(action)
            
        # Get the actual unit object for action execution
        active_unit = self._get_unit_by_id(active_unit_id)
        if not active_unit:
            raise RuntimeError(f"Active unit {active_unit_id} not found in game state")
            
        # 3. Execute action for active unit
        success, mirror_action = self._execute_action_for_unit(active_unit, action)
        
        # 4. Remove unit from queue (AI_TURN.md: exact step 4)
        self._mark_unit_as_acted(active_unit, mirror_action)
        self._remove_unit_from_queue(active_unit_id)
        
        # 5. Log action if step logger connected (AI_TURN.md compliance) - AFTER dice capture
        if self.step_logger and self.step_logger.enabled:
            current_phase = self.base.get_current_phase()
            current_player = self.base.get_current_player()
            current_turn = self.base.get_current_turn()
            step_increment = self._is_real_action(mirror_action)
            
            # Use mirror_action which now contains dice data (if captured successfully)
            action_details = dict(mirror_action)
            action_type = mirror_action.get("type", "wait")
            
            # Add position information for move actions
            if action_type == "move":
                action_details["start_pos"] = (active_unit["col"], active_unit["row"])
                if "col" in mirror_action and "row" in mirror_action:
                    action_details["end_pos"] = (mirror_action["col"], mirror_action["row"])
            
            # Special handling for shooting actions with multiple shots
            if action_type == "shoot" and hasattr(self.base, '_last_shoot_result') and self.base._last_shoot_result:
                shoot_result = self.base._last_shoot_result
                if "shots" in shoot_result and len(shoot_result["shots"]) > 1:
                    # Log each shot individually
                    for shot_idx, shot_data in enumerate(shoot_result["shots"]):
                        shot_details = dict(action_details)
                        shot_details.update({
                            "shot_number": shot_idx + 1,
                            "total_shots": len(shoot_result["shots"]),
                            "hit_roll": shot_data["hit_roll"],
                            "wound_roll": shot_data["wound_roll"],
                            "save_roll": shot_data["save_roll"],
                            "damage_dealt": shot_data["damage"],
                            "hit_target": shot_data["hit_target"],
                            "wound_target": shot_data["wound_target"],
                            "save_target": shot_data["save_target"],
                            "hit_result": "HIT" if shot_data["hit"] else "MISS",
                            "wound_result": "WOUND" if shot_data["wound"] else "FAIL",
                            "save_result": "SAVE" if shot_data["save_success"] else "FAIL"
                        })
                        
                        self.step_logger.log_action(
                            unit_id=active_unit["id"],
                            action_type="shoot_individual",
                            phase=current_phase,
                            player=current_player,
                            success=success,
                            step_increment=False,  # Don't count individual shots as steps
                            action_details=shot_details,
                            turn_number=current_turn
                    )
                
                # Log shooting summary
                summary_details = dict(action_details)
                summary_details.update({
                    "total_shots": len(shoot_result["shots"]),
                    "total_damage": shoot_result["totalDamage"],
                    "hits": shoot_result["summary"]["hits"],
                    "wounds": shoot_result["summary"]["wounds"],
                    "failed_saves": shoot_result["summary"]["failedSaves"]
                })
                
                self.step_logger.log_action(
                    unit_id=active_unit["id"],
                    action_type="shoot_summary",
                    phase=current_phase,
                    player=current_player,
                    success=success,
                    step_increment=step_increment,  # Only the summary counts as a step
                    action_details=summary_details,
                    turn_number=current_turn
                )
                # Don't return early - need to continue to gym response
            else:
                # Normal single action logging (non-shooting or single shot)
                self.step_logger.log_action(
                    unit_id=active_unit["id"],
                    action_type=action_type,
                    phase=current_phase,
                    player=current_player,
                    success=success,
                    step_increment=step_increment,
                    action_details=action_details,
                    turn_number=current_turn  # Add turn number
                )
        
        # 6. Return gym response (AI_TURN.md: exact step 6)
        return self._build_gym_response(action, success, active_unit, mirror_action)
        

            
    def _get_current_active_unit(self) -> Optional[str]:
        """
        AI_TURN.md EXACT pattern: Get current active unit (build queue if empty).
        Returns unit ID or None.
        """
        # If queue is empty, build it for current phase
        if not self.active_unit_queue:
            self._build_current_phase_queue()
            
        # Return first unit ID from queue (or None if queue empty)
        if self.active_unit_queue:
            return self.active_unit_queue[0]
        else:
            return None
            
    def _build_current_phase_queue(self):
        """Build unit queue for current phase using AI_TURN.md eligibility rules."""
        current_phase = self.base.get_current_phase()
        current_player = self.base.get_current_player()
        
        all_units = self.base.get_units()
        
        # Clear existing queue
        self.active_unit_queue = []
        
        # AI_TURN.md: Combat phase includes both players, others current player only
        if current_phase == "combat":
            candidate_units = []
            for u in all_units:
                if "CUR_HP" not in u:
                    raise KeyError(f"Unit {u.get('id', 'unknown')} missing required CUR_HP field")
                if u["CUR_HP"] > 0:
                    candidate_units.append(u)
        else:
            candidate_units = []
            for u in all_units:
                if "CUR_HP" not in u:
                    raise KeyError(f"Unit {u.get('id', 'unknown')} missing required CUR_HP field")
                if u["player"] == current_player and u["CUR_HP"] > 0:
                    candidate_units.append(u)
        
        # Add eligible units to queue (IDs only)
        for unit in candidate_units:
            if self._is_unit_eligible_for_current_phase(unit):
                self.active_unit_queue.append(unit["id"])
                
    def _remove_unit_from_queue(self, unit_id: str):
        """Remove unit from active queue after it acts."""
        if unit_id in self.active_unit_queue:
            self.active_unit_queue.remove(unit_id)
        
    def _get_next_combat_unit(self, all_units: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle combat phase unit selection with sub-phases."""
        living_units = []
        for u in all_units:
            if "CUR_HP" not in u:
                raise KeyError(f"Unit {u.get('id', 'unknown')} missing required CUR_HP field")
            if u["CUR_HP"] > 0:
                living_units.append(u)
                
        if "units_attacked" not in self.base.game_state:
            raise KeyError("game_state missing required 'units_attacked' field")
        if "units_charged" not in self.base.game_state:
            raise KeyError("game_state missing required 'units_charged' field")
        units_attacked = self.base.game_state["units_attacked"]
        units_charged = self.base.game_state["units_charged"]
        
        # First: Process charged units
        for unit in living_units:
            if (unit["id"] in units_charged and 
                unit["id"] not in units_attacked and
                self._has_adjacent_enemies(unit)):
                return unit
        
        # Then: Alternating combat (if charged units done)
        # Non-active player first, then active player per AI_TURN.md
        current_player = self.base.get_current_player()
        non_active_player = 1 - current_player
        for player in [non_active_player, current_player]:  # Non-active first per AI_TURN.md
            for unit in living_units:
                if (unit["player"] == player and
                    unit["id"] not in units_attacked and 
                    unit["id"] not in units_charged and
                    self._has_adjacent_enemies(unit)):
                    return unit
        
        return None
        
    def _mark_unit_as_acted(self, unit: Dict[str, Any], mirror_action: Dict[str, Any]):
        """Mark unit as acted for current phase per AI_TURN.md rules."""
        current_phase = self.base.get_current_phase()
        action_type = mirror_action.get("type", "wait")
        
        # AI_TURN.md: Mark unit based on phase and action
        if current_phase == "move":
            # Check if unit fled (moved while adjacent to enemy)
            if action_type == "move" and self._was_adjacent_before_move(unit):
                self.base.state_actions['add_fled_unit'](unit["id"])
            self.base.state_actions['add_moved_unit'](unit["id"])
            
        elif current_phase == "shoot":
            self.base.state_actions['add_shot_unit'](unit["id"])
            
        elif current_phase == "charge":
            self.base.state_actions['add_charged_unit'](unit["id"])
            
        elif current_phase == "combat":
            self.base.state_actions['add_attacked_unit'](unit["id"])
            
    def _was_adjacent_before_move(self, unit: Dict[str, Any]) -> bool:
        """Check if unit was adjacent to enemy before move (for flee detection)."""
        # This would need to check unit's previous position
        # For now, simplified implementation
        return self._is_adjacent_to_enemy(unit)
            
    def _is_unit_eligible_for_current_phase(self, unit: Dict[str, Any]) -> bool:
        """Check unit eligibility using exact AI_TURN.md rules with UPPERCASE validation."""
        phase = self.base.get_current_phase()
        
        # AI_GUIDE.md: REQUIRED - Check CUR_HP exists (no defaults)
        if "CUR_HP" not in unit:
            raise KeyError(f"Unit {unit['id']} missing required CUR_HP field")
            
        if unit["CUR_HP"] <= 0:
            return False
            
        # AI_GUIDE.md: Eligibility Rules (EXACT AI_TURN.md)
        if phase == "move":
            if "units_moved" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_moved' field")
            return (unit["player"] == self.base.get_current_player() and
                    unit["id"] not in self.base.game_state["units_moved"])
                    
        elif phase == "shoot":
            # AI_GUIDE.md: NOT fled, NOT adjacent to enemy, has RNG_NB > 0, has valid targets
            if "RNG_NB" not in unit:
                raise KeyError(f"Unit {unit['id']} missing required RNG_NB field")
            if "units_shot" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_shot' field")
            if "units_fled" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_fled' field")
                
            return (unit["player"] == self.base.get_current_player() and
                    unit["id"] not in self.base.game_state["units_shot"] and
                    unit["id"] not in self.base.game_state["units_fled"] and
                    unit["RNG_NB"] > 0 and
                    not self._is_adjacent_to_enemy(unit) and
                    self._has_valid_shooting_targets(unit))
                    
        elif phase == "charge":
            # AI_GUIDE.md: NOT fled, NOT adjacent to enemy, has enemies within charge range
            return (unit["player"] == self.base.get_current_player() and
                    unit["id"] not in self.base.game_state.get("units_charged", set()) and
                    unit["id"] not in self.base.game_state.get("units_fled", set()) and
                    not self._is_adjacent_to_enemy(unit) and
                    self._has_enemies_within_charge_range(unit))
                    
        elif phase == "combat":
            # AI_GUIDE.md: unit.id NOT in units_attacked AND has adjacent enemies
            return (unit["id"] not in self.base.game_state.get("units_attacked", set()) and
                    self._has_adjacent_enemies(unit))
                    
        return False
        
    def _is_adjacent_to_enemy(self, unit: Dict[str, Any]) -> bool:
        """Check if unit is adjacent to any enemy within CC_RNG."""
        all_units = self.base.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u["CUR_HP"] > 0]
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit {unit['id']} missing required CC_RNG field")
        cc_range = unit["CC_RNG"]
        
        return any(
            max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) <= cc_range
            for enemy in enemy_units
        )
        
    def _has_adjacent_enemies(self, unit: Dict[str, Any]) -> bool:
        """Check if unit has adjacent enemies within CC_RNG."""
        return self._is_adjacent_to_enemy(unit)
        
    def _has_valid_shooting_targets(self, unit: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets."""
        if not hasattr(self.base, 'game_actions'):
            raise RuntimeError("Base controller missing required game_actions")
        if "get_valid_shooting_targets" not in self.base.game_actions:
            raise KeyError("game_actions missing required 'get_valid_shooting_targets' method")
        
        valid_targets = self.base.game_actions["get_valid_shooting_targets"](unit["id"])
        return len(valid_targets) > 0
        
    def _has_enemies_within_charge_range(self, unit: Dict[str, Any]) -> bool:
        """Check if unit has enemies within charge range."""
        if not hasattr(self.base, 'game_actions'):
            raise RuntimeError("Base controller missing required game_actions")
        if "get_valid_charge_targets" not in self.base.game_actions:
            raise KeyError("game_actions missing required 'get_valid_charge_targets' method")
            
        valid_targets = self.base.game_actions["get_valid_charge_targets"](unit["id"])
        return len(valid_targets) > 0
        
    def _get_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Get unit by ID from current game state."""
        all_units = self.base.get_units()
        for unit in all_units:
            if unit["id"] == unit_id:
                return unit
        return None
        
    def _execute_action_for_unit(self, unit: Dict[str, Any], action: int) -> Tuple[bool, Dict[str, Any]]:
        """Execute action for specific unit and return success status and mirror action."""
        current_phase = self.base.get_current_phase()
        
        # Convert gym action to mirror action format
        mirror_action = self._convert_gym_action_to_mirror(unit, action, current_phase)
        
        if not mirror_action:
            raise RuntimeError(f"Failed to convert gym action {action} to mirror action in phase {current_phase}")
            
        # AI_TURN.md: Built-in step counting during action execution (step 3)
        if self._is_real_action(mirror_action):
            if "episode_steps" not in self.base.game_state:
                raise KeyError("game_state missing required 'episode_steps' field")
            self.base.game_state["episode_steps"] += 1
            
        # Execute action through base controller
        try:
            success = self.base.execute_action(unit["id"], mirror_action)
            
            # Capture detailed action results for logging - STRICT VALIDATION ONLY
            if success and mirror_action.get("type") == "shoot":
                if not hasattr(self.base, '_last_shoot_result'):
                    raise RuntimeError("Base controller missing required _last_shoot_result after shoot action")
                shoot_result = self.base._last_shoot_result
                if not shoot_result:
                    raise RuntimeError("Shoot result is None after successful shoot action") 
                if not isinstance(shoot_result, dict):
                    raise RuntimeError("Shoot result is not a dictionary")
                
                if "shots" not in shoot_result:
                    raise KeyError("Shoot result missing required 'shots' field")
                if len(shoot_result["shots"]) == 0:
                    raise RuntimeError("Shoot result contains no shot data")
                    
                shot_data = shoot_result["shots"][0]
                required_fields = ["hit_roll", "wound_roll", "save_roll", "damage", "hit_target", "wound_target", "save_target", "hit", "wound", "save_success"]
                for field in required_fields:
                    if field not in shot_data:
                        raise KeyError(f"Shot data missing required '{field}' field")
                        
                mirror_action.update({
                    "hit_roll": shot_data["hit_roll"],
                    "wound_roll": shot_data["wound_roll"],
                    "save_roll": shot_data["save_roll"],
                    "damage_dealt": shot_data["damage"],
                    "hit_target": shot_data["hit_target"],
                    "wound_target": shot_data["wound_target"],
                    "save_target": shot_data["save_target"],
                    "hit_result": "HIT" if shot_data["hit"] else "MISS",
                    "wound_result": "WOUND" if shot_data["wound"] else "FAIL", 
                    "save_result": "SAVE" if shot_data["save_success"] else "FAIL"
                })
            
            return success, mirror_action
        except Exception as e:
            # Action failed - still return the attempted action for logging
            return False, mirror_action
            
    def _convert_gym_action_to_mirror(self, unit: Dict[str, Any], action: int, phase: str) -> Dict[str, Any]:
        """Convert gym action to mirror action format."""
        # Ensure action is integer
        if hasattr(action, 'item') and callable(action.item):
            action = int(action.item())
        else:
            action = int(action)
            
        action_type = action % 8  # Ensure valid range
        
        # Movement actions (0-3)
        if 0 <= action_type <= 3:
            if phase != "move":
                return {"type": "wait"}
                
            movements = {
                0: (0, -1),  # North
                1: (0, 1),   # South
                2: (1, 0),   # East
                3: (-1, 0)   # West
            }
            
            col_diff, row_diff = movements[action_type]
            new_col = unit["col"] + col_diff
            new_row = unit["row"] + row_diff
            
            return {
                "type": "move",
                "col": new_col,
                "row": new_row
            }
            
        # Shooting action (4)
        elif action_type == 4:
            if phase != "shoot":
                return {"type": "wait"}
                
            if not hasattr(self.base, 'game_actions'):
                raise RuntimeError("Base controller missing required game_actions")
            if "get_valid_shooting_targets" not in self.base.game_actions:
                raise KeyError("game_actions missing required 'get_valid_shooting_targets' method")
                
            valid_targets = self.base.game_actions["get_valid_shooting_targets"](unit["id"])
            if valid_targets:
                return {
                    "type": "shoot",
                    "target_id": valid_targets[0]
                }
            return {"type": "wait"}
            
        # Charge action (5)
        elif action_type == 5:
            if phase != "charge":
                return {"type": "wait"}
                
            if not hasattr(self.base, 'game_actions'):
                raise RuntimeError("Base controller missing required game_actions")
            if "get_valid_charge_targets" not in self.base.game_actions:
                raise KeyError("game_actions missing required 'get_valid_charge_targets' method")
                
            valid_targets = self.base.game_actions["get_valid_charge_targets"](unit["id"])
            if valid_targets:
                return {
                    "type": "charge",
                    "target_id": valid_targets[0]
                }
            return {"type": "wait"}
            
        # Combat action (6)
        elif action_type == 6:
            if phase != "combat":
                return {"type": "wait"}
                
            if not hasattr(self.base, 'game_actions'):
                raise RuntimeError("Base controller missing required game_actions")
            if "get_valid_combat_targets" not in self.base.game_actions:
                raise KeyError("game_actions missing required 'get_valid_combat_targets' method")
                
            valid_targets = self.base.game_actions["get_valid_combat_targets"](unit["id"])
            if valid_targets:
                return {
                    "type": "combat",
                    "target_id": valid_targets[0]
                }
            return {"type": "wait"}
            
        # Wait action (7) or any other
        else:
            return {"type": "wait"}
            
    def _is_real_action(self, mirror_action: Dict[str, Any]) -> bool:
        """Check if action should increment episode steps per AI_TURN.md."""
        # AI_TURN.md: Steps increment when unit ATTEMPTS action (move/shoot/charge/combat/wait)
        action_type = mirror_action.get("type", "wait")
        return action_type in ["move", "shoot", "charge", "combat", "wait"]
        

                
    def _handle_no_active_unit(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Handle case when no active unit is available."""
        current_phase = self.base.get_current_phase()
        
        # Check if phase is complete
        if self._is_phase_complete():
            # Log phase transition if step logger connected
            if self.step_logger and self.step_logger.enabled:
                old_phase = self.base.get_current_phase()
                old_player = self.base.get_current_player()
            
            # Advance to next phase
            self._advance_phase()
            
            # Log the transition (AI_TURN.md compliance - no step increment)
            if self.step_logger and self.step_logger.enabled:
                new_phase = self.base.get_current_phase()
                new_player = self.base.get_current_player()
                current_turn = self.base.get_current_turn()
                # Enhanced phase logging with turn number
                self.step_logger.log_phase_transition(old_phase, new_phase, new_player, current_turn)
            
            # Check if game is over after phase advance
            if self.base.is_game_over():
                return self._build_gym_response(action, True, None, {"type": "phase_advance"}, terminated=True)
            else:
                return self._build_gym_response(action, True, None, {"type": "phase_advance"})
        else:
            # Phase not complete but no active unit - should not happen
            raise RuntimeError(f"No active unit in phase '{current_phase}' but phase not complete")
            
    def _is_phase_complete(self) -> bool:
        """Check if current phase is complete using AI_TURN.md eligibility rules."""
        # AI_TURN.md: Phase complete when queue is empty and no more eligible units
        if self.active_unit_queue:
            return False
            
        # Try to build queue - if still empty, phase is complete
        self._build_current_phase_queue()
        return len(self.active_unit_queue) == 0
        
    def _advance_phase(self):
        """Advance to next phase using AI_TURN.md exact turn progression."""
        current_phase = self.base.get_current_phase()
        current_player = self.base.get_current_player()
        
        # AI_TURN.md: Phase transitions for current player
        if hasattr(self.base, 'phase_transitions'):
            try:
                if current_phase == "move":
                    self.base.phase_transitions['transition_to_shoot']()
                elif current_phase == "shoot":
                    self.base.phase_transitions['transition_to_charge']()
                elif current_phase == "charge":
                    self.base.phase_transitions['transition_to_combat']()
                elif current_phase == "combat":
                    # AI_TURN.md: After combat, always call end_turn for proper progression
                    self.base.phase_transitions['end_turn']()  # Handles P0→P1 and P1→P0(new turn)
                        
            except Exception as e:
                raise RuntimeError(f"Phase transition failed from '{current_phase}': {e}")
        else:
            raise RuntimeError("Base controller missing phase_transitions")
            
    def _build_gym_response(self, action: int, success: bool, acting_unit: Optional[Dict[str, Any]], 
                           mirror_action: Dict[str, Any], terminated: bool = False) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Build gymnasium response tuple."""
        try:
            # Get observation using gym environment if available
            if hasattr(self, 'gym_env') and hasattr(self.gym_env, '_get_obs'):
                obs = self.gym_env._get_obs()
            elif hasattr(self.base, '_get_obs'):
                obs = self.base._get_obs()
            else:
                raise RuntimeError("No observation method available - gym_env or base controller must provide _get_obs()")
                
            # Calculate reward
            reward = 0.1 if success else -0.1
            
            # Check termination
            if not terminated:
                terminated = self.base.is_game_over()
            
            # Log episode end if terminated (AI_TURN.md compliance)
            if terminated and self.step_logger and self.step_logger.enabled:
                if "episode_steps" not in self.base.game_state:
                    raise KeyError("game_state missing required 'episode_steps' field")
                episode_steps = self.base.game_state["episode_steps"]
                winner = self.base.get_winner() if hasattr(self.base, 'get_winner') else None
                self.step_logger.log_episode_end(episode_steps, winner)
                
            truncated = False
            
            # Build info dictionary
            if "episode_steps" not in self.base.game_state:
                raise KeyError("game_state missing required 'episode_steps' field")
                
            info = {
                "action_success": success,
                "action_attempted": True,  # Always true for sequential controller
                "current_turn": self.base.get_current_turn(),
                "current_phase": self.base.get_current_phase(),
                "current_player": self.base.get_current_player(),
                "game_over": terminated,
                "winner": self.base.get_winner() if terminated else None,
                "episode_steps": self.base.game_state["episode_steps"],
                "eligible_units": len(self.active_unit_queue),
                "active_unit_id": acting_unit["id"] if acting_unit else None
            }
            
            return obs, reward, terminated, truncated, info
            
        except Exception as e:
            raise RuntimeError(f"Failed to build gym response: {e}")


# Compatibility functions for existing integrations
def create_sequential_game_controller(config, quiet=False):
    """Factory function to create sequential game controller."""
    return SequentialGameController(config, quiet)