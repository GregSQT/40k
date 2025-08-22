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
            pass  # StepLogger connected silently
            
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
            # Unit died - remove from queue and get next unit
            self._remove_unit_from_queue(active_unit_id)
            return self.execute_gym_action(action)  # Try again with next unit
            
        # AI_TURN.md: CHARGE ROLL TIMING - Roll 2d6 immediately when unit becomes active
        current_phase = self.base.get_current_phase()
        if current_phase == "charge":
            if "unit_charge_rolls" not in self.base.game_state:
                self.base.game_state["unit_charge_rolls"] = {}
                
            # Check if unit already has a charge roll for this activation
            if active_unit_id not in self.base.game_state["unit_charge_rolls"]:
                import random
                die1 = random.randint(1, 6)
                die2 = random.randint(1, 6)
                charge_total = die1 + die2
                
                # Store charge roll data (AI_TURN.md format)
                self.base.game_state["unit_charge_rolls"][active_unit_id] = {
                    "die1": die1,
                    "die2": die2,
                    "total": charge_total
                }
            
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
           
            # Enhanced unit references with coordinates for ALL action types
            # Acting unit always includes coordinates
            action_details["unit_with_coords"] = f"{active_unit['id']}({active_unit['col']}, {active_unit['row']})"
            
            # Add position information for move actions
            if action_type == "move":
                action_details["start_pos"] = (active_unit["col"], active_unit["row"])
                if "col" in mirror_action and "row" in mirror_action:
                    action_details["end_pos"] = (mirror_action["col"], mirror_action["row"])
            
            # Add position and target information for charge actions
            elif action_type == "charge":
                action_details["start_pos"] = (active_unit["col"], active_unit["row"])
                if "destination_col" in mirror_action and "destination_row" in mirror_action:
                    action_details["end_pos"] = (mirror_action["destination_col"], mirror_action["destination_row"])
                if "target_id" in mirror_action:
                    target_unit = self._get_unit_by_id(mirror_action["target_id"])
                    if target_unit:
                        action_details["target_pos"] = (target_unit["col"], target_unit["row"])
                        # Enhanced target format with coordinates
                        action_details["target_with_coords"] = f"{target_unit['id']}({target_unit['col']}, {target_unit['row']})"
                        # Override target_id for step logger
                        action_details["target_id"] = f"{target_unit['id']}({target_unit['col']}, {target_unit['row']})"
            
            # Add target information for shoot and combat actions
            elif action_type in ["shoot", "combat"]:
                if "target_id" in mirror_action:
                    target_unit = self._get_unit_by_id(mirror_action["target_id"])
                    if target_unit:
                        action_details["target_with_coords"] = f"{target_unit['id']}({target_unit['col']}, {target_unit['row']})"
                        # Override target_id for step logger
                        action_details["target_id"] = f"{target_unit['id']}({target_unit['col']}, {target_unit['row']})"
           
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
        # If queue is empty, try to build it for current phase
        if not self.active_unit_queue:
            self._build_current_phase_queue()
            
            # AI_TURN.md: If still empty after building, phase is complete
            if not self.active_unit_queue:
                return None
            
        # Return first unit ID from queue
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
        # Add eligible units to queue (IDs only) - debug why ALL units fail
        eligible_count = 0
        for unit in candidate_units:
            print(f"🔍 Checking U{unit['id']} P{unit['player']} for {current_phase} eligibility...")
            if self._is_unit_eligible_for_current_phase(unit):
                self.active_unit_queue.append(unit["id"])
                eligible_count += 1
                print(f"✅ U{unit['id']} P{unit['player']} ELIGIBLE for {current_phase}")
            else:
                print(f"💀 U{unit['id']} P{unit['player']} FAILED {current_phase} eligibility")
        
        if eligible_count == 0:
            print(f"💀 NO UNITS ELIGIBLE for P{current_player} {current_phase} - checking WHY")
                
    def _remove_unit_from_queue(self, unit_id: str):
        """Remove unit from active queue after it acts."""
        if unit_id in self.active_unit_queue:
            self.active_unit_queue.remove(unit_id)
            
        # AI_TURN.md: Discard charge roll at end of activation (regardless of success/failure)
        self._cleanup_charge_roll(unit_id)
        
    def _cleanup_charge_roll(self, unit_id: str):
        """AI_TURN.md: Clean up charge roll at end of unit activation."""
        current_phase = self.base.get_current_phase()
        if current_phase == "charge":
            if "unit_charge_rolls" in self.base.game_state:
                if unit_id in self.base.game_state["unit_charge_rolls"]:
                    discarded_roll = self.base.game_state["unit_charge_rolls"].pop(unit_id)
                    roll_value = discarded_roll.get("total", discarded_roll) if isinstance(discarded_roll, dict) else discarded_roll
        
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
                print(f"🏃 U{unit['id']} FLED")
            self.base.state_actions['add_moved_unit'](unit["id"])
            
            # Clear stored move start position after flee detection
            if hasattr(self, '_current_move_start_pos'):
                delattr(self, '_current_move_start_pos')
            
        elif current_phase == "shoot":
            self.base.state_actions['add_shot_unit'](unit["id"])
            print(f"🎯 U{unit['id']} added to units_shot set")
            
        elif current_phase == "charge":
            self.base.state_actions['add_charged_unit'](unit["id"])
            print(f"⚡ U{unit['id']} added to units_charged set")
            
        elif current_phase == "combat":
            self.base.state_actions['add_attacked_unit'](unit["id"])
            print(f"⚔️ U{unit['id']} added to units_attacked set")
            
    def _was_adjacent_before_move(self, unit: Dict[str, Any]) -> bool:
        """Check if unit was adjacent to enemy before move (for flee detection)."""
        # AI_TURN.md: Unit flees if it STARTS adjacent to enemy and ENDS not adjacent
        # We need to check the unit's position BEFORE the move action was executed
        
        # Get the mirror action that was just executed to find the starting position
        if not hasattr(self, '_current_move_start_pos'):
            # No move start position stored - cannot determine flee status
            return False
        
        start_col, start_row = self._current_move_start_pos
        
        # Check if unit was adjacent to any enemy at START position
        all_units = self.base.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u["CUR_HP"] > 0]
        
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit {unit['id']} missing required CC_RNG field")
        cc_range = unit["CC_RNG"]
        
        # Check adjacency at starting position
        was_adjacent_at_start = any(
            max(abs(start_col - enemy["col"]), abs(start_row - enemy["row"])) <= cc_range
            for enemy in enemy_units
        )
        
        # Check if unit is currently adjacent to any enemy (at END position)
        is_adjacent_now = self._is_adjacent_to_enemy(unit)
        
        # AI_TURN.md: Flee = started adjacent AND ended not adjacent
        fled = was_adjacent_at_start and not is_adjacent_now
        
        if fled:
            print(f"🏃 U{unit['id']} FLED: was adjacent at ({start_col},{start_row}), now not adjacent at ({unit['col']},{unit['row']})")
        
        return fled
            
    def _is_unit_eligible_for_current_phase(self, unit: Dict[str, Any]) -> bool:
        """Check unit eligibility using exact AI_TURN.md rules with UPPERCASE validation."""
        phase = self.base.get_current_phase()
        
        # AI_GUIDE.md: REQUIRED - Check CUR_HP exists (no defaults)
        if "CUR_HP" not in unit:
            raise KeyError(f"Unit {unit['id']} missing required CUR_HP field")
            
        if unit["CUR_HP"] <= 0:
            print(f"💀 U{unit['id']} DEAD: CUR_HP={unit['CUR_HP']}")
            return False
        
        print(f"🔍 U{unit['id']} P{unit['player']} alive (CUR_HP={unit['CUR_HP']}) checking {phase} rules...")
            
        # AI_GUIDE.md: Eligibility Rules (EXACT AI_TURN.md)
        # COMBAT PHASE: Both players' units can be eligible, skip player check
        if phase == "combat":
            # Skip the current_player check for combat phase - will be handled in combat-specific logic below
            pass
        elif phase == "move":
            if "units_moved" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_moved' field")
            current_player = self.base.get_current_player()
            units_moved = self.base.game_state["units_moved"]
            
            if unit["player"] != current_player:
                print(f"🚫 U{unit['id']} move fail: wrong player P{unit['player']} != P{current_player}")
                return False
            if unit["id"] in units_moved:
                print(f"🚫 U{unit['id']} move fail: already moved (units_moved={units_moved})")
                return False
            print(f"✅ U{unit['id']} move ELIGIBLE: P{unit['player']} not in {units_moved}")
            return True
                    
        elif phase == "shoot":
            # AI_TURN.md STRICT COMPLIANCE: Check each requirement individually with debug
            current_player = self.base.get_current_player()
            
            # Requirement 1: Correct player
            if unit["player"] != current_player:
                print(f"🔫 U{unit['id']} shoot fail: wrong player P{unit['player']} != P{current_player}")
                return False
                
            # Requirement 2: Has ranged weapons
            if "RNG_NB" not in unit:
                raise KeyError(f"Unit {unit['id']} missing required RNG_NB field")
            if unit["RNG_NB"] <= 0:
                print(f"🔫 U{unit['id']} shoot fail: no ranged weapons (RNG_NB={unit['RNG_NB']})")
                return False
                
            # Requirement 3: Not already shot
            if "units_shot" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_shot' field")
            shot_set = self.base.game_state["units_shot"]
            if unit["id"] in shot_set:
                print(f"🔫 U{unit['id']} shoot fail: already shot (units_shot={shot_set})")
                return False
                
            # Requirement 4: Not fled
            if "units_fled" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_fled' field")
            if unit["id"] in self.base.game_state["units_fled"]:
                print(f"🔫 U{unit['id']} shoot fail: unit fled (units_fled={self.base.game_state['units_fled']})")
                return False
                
            # Requirement 5: Not adjacent to enemy (in combat)
            if self._is_adjacent_to_enemy(unit):
                print(f"🔫 U{unit['id']} shoot fail: adjacent to enemy (in combat)")
                return False
                
            # Requirement 6: Has valid shooting targets
            if not self._has_valid_shooting_targets(unit):
                print(f"🔫 U{unit['id']} shoot fail: no valid targets")
                return False
                
            # All AI_TURN.md requirements met
            print(f"✅ U{unit['id']} shoot ELIGIBLE: all requirements met")
            return True
                    
        elif phase == "charge":
            # AI_TURN.md: Charge phase validation with proper KeyError handling
            unit_id = unit["id"]
            current_player = self.base.get_current_player()
            
            # Check 1: Correct player
            if unit["player"] != current_player:
                return False
                
            # Check 2: Required tracking sets exist
            if "units_charged" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_charged' field")
            if "units_fled" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_fled' field")
                
            # Check 3: Already charged
            charged_set = self.base.game_state["units_charged"]
            if unit_id in charged_set:
                print(f"⚡ U{unit_id} charge fail: already charged this phase (units_charged={charged_set})")
                return False
                
            # Check 4: Fled units
            if unit_id in self.base.game_state["units_fled"]:
                return False
                
            # Check 5: Adjacent to enemy
            is_adjacent = self._is_adjacent_to_enemy(unit)
            if is_adjacent:
                return False
                
            # Check 6: Enemies within charge range
            has_charge_targets = self._has_enemies_within_charge_range(unit)
            if not has_charge_targets:
                return False
            return True
                    
        elif phase == "combat":
            # AI_TURN.md: Combat phase allows BOTH players - no current_player check needed
            # But still need CUR_HP check (done at function start) and tracking validation
            if "units_attacked" not in self.base.game_state:
                raise KeyError("game_state missing required 'units_attacked' field")
            attacked_set = self.base.game_state["units_attacked"]
            if unit["id"] in attacked_set:
                print(f"⚔️ U{unit['id']} combat fail: already attacked this phase (units_attacked={attacked_set})")
                return False
            if not self._has_adjacent_enemies(unit):
                print(f"⚔️ U{unit['id']} combat fail: no adjacent enemies")
                return False
            print(f"⚔️ U{unit['id']} P{unit['player']} ELIGIBLE for combat")
            return True
                    
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
        """Check if unit has enemies within charge range with precise distance measurements."""
        try:
            from shared.gameMechanics import get_charge_max_distance
            from shared.gameRules import get_hex_distance
            charge_max_distance = get_charge_max_distance()
        except Exception as e:
            raise RuntimeError(f"Failed to load charge mechanics: {e}")
            
        all_units = self.base.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("CUR_HP") > 0]
        
        # Check if unit has a charge roll - determines which distance check to use
        charge_data = self.base.game_state.get("unit_charge_rolls", {}).get(unit["id"])
        
        if not charge_data:
            # PRE-ROLL ELIGIBILITY: Check if ANY enemies within charge_max_distance (13)
            # FROM: unit position TO: enemy position (direct hex distance)
            
            for enemy in enemy_units:
                # Use proper hex distance calculation (cube coordinates)
                direct_distance = get_hex_distance(unit, enemy)
                
                # Must not be adjacent already (distance > 1) and within max range
                if 1 < direct_distance <= charge_max_distance:
                    return True
            return False
            
        else:
            # POST-ROLL CAPABILITY: Check if can reach adjacent hex to any enemy
            # FROM: unit position TO: empty hex adjacent to enemy (pathfinding distance)
            if isinstance(charge_data, dict):
                charge_roll = charge_data.get("total", charge_data.get("charge_roll"))
            else:
                charge_roll = charge_data
            
            for enemy in enemy_units:
                # First check: enemy must be within max range for eligibility
                direct_distance = get_hex_distance(unit, enemy)
                if direct_distance > charge_max_distance:
                    continue
                    
                # Second check: can we reach an adjacent hex to this enemy?
                # Adjacent hex is at distance (enemy_distance - 1) via pathfinding
                adjacent_hex_distance = max(1, direct_distance - 1)
                
                if adjacent_hex_distance <= charge_roll:
                    return True
            return False
    
    def _get_valid_charge_destinations(self, unit: Dict[str, Any], charge_roll: int) -> List[Dict[str, int]]:
        """AI_TURN.md: Build valid_charge_destinations pool using BFS pathfinding."""
        from shared.gameRules import get_hex_distance
        
        valid_destinations = []
        all_units = self.base.get_units()
        enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("CUR_HP") > 0]
        
        # BFS to find all reachable hexes within charge_roll distance
        visited = set()
        queue = [(unit["col"], unit["row"], 0)]
        
        while queue:
            col, row, distance = queue.pop(0)
            hex_key = f"{col},{row}"
            
            if hex_key in visited or distance > charge_roll:
                continue
                
            visited.add(hex_key)
            
            # Check if this position is adjacent to any enemy within charge range
            if distance > 0:  # Don't include starting position
                for enemy in enemy_units:
                    # Must be within original charge eligibility range
                    enemy_distance = get_hex_distance(unit, enemy)
                    from shared.gameMechanics import get_charge_max_distance
                    if enemy_distance > get_charge_max_distance():
                        continue
                            
                    # Check if current position is adjacent to this enemy
                    adj_distance = max(abs(col - enemy["col"]), abs(row - enemy["row"]))
                    if adj_distance == 1:
                        # Check if position is not occupied by another unit
                        occupied = any(u["col"] == col and u["row"] == row and u["id"] != unit["id"] 
                                     for u in all_units if u.get("CUR_HP") > 0)
                        if not occupied:
                            valid_destinations.append({"col": col, "row": row})
                            break
            
            # Add neighbors for further exploration
            if distance < charge_roll:
                # Use proper hex neighbor calculation instead of hardcoded offsets
                from shared.gameMechanics import get_cube_neighbors
                neighbors = get_cube_neighbors(col, row)
                for ncol, nrow in neighbors:
                    nkey = f"{ncol},{nrow}"
                    if nkey not in visited:
                        queue.append((ncol, nrow, distance + 1))
        
        return valid_destinations
        
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
            
            # Capture combat dice results for logging - only when valid data available
            elif success and mirror_action.get("type") == "combat":
                if (hasattr(self.base, '_last_combat_result') and self.base._last_combat_result and
                    isinstance(self.base._last_combat_result, dict) and 
                    "attacks" in self.base._last_combat_result and 
                    len(self.base._last_combat_result["attacks"]) > 0):
                    
                    attack_data = self.base._last_combat_result["attacks"][0]
                    # Only add dice data if all required fields are present and valid
                    required_fields = ["hit_roll", "wound_roll", "save_roll", "damage", "hit_target", "wound_target", "save_target", "hit", "wound", "save_success"]
                    if all(field in attack_data for field in required_fields):
                        mirror_action.update({
                            "hit_roll": attack_data["hit_roll"],
                            "wound_roll": attack_data["wound_roll"],
                            "save_roll": attack_data["save_roll"],
                            "damage_dealt": attack_data["damage"],
                            "hit_target": attack_data["hit_target"],
                            "wound_target": attack_data["wound_target"],
                            "save_target": attack_data["save_target"],
                            "hit_result": "HIT" if attack_data["hit"] else "MISS",
                            "wound_result": "WOUND" if attack_data["wound"] else "FAIL",
                            "save_result": "SAVE" if attack_data["save_success"] else "FAIL"
                        })
                # No else clause - let step logger handle missing dice data with its built-in "N/A" system
            
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
            
            # Store starting position for flee detection
            self._current_move_start_pos = (unit["col"], unit["row"])
            
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
                
            # AI_TURN.md: Must validate against unit's specific 2d6 roll
            charge_data = self.base.game_state.get("unit_charge_rolls", {}).get(unit["id"])
            if not charge_data:
                # No charge roll available - should not happen for eligible units
                return {"type": "wait"}
                
            charge_roll = charge_data.get("total") if isinstance(charge_data, dict) else charge_data
            if charge_roll <= 0:
                return {"type": "wait"}
                
            # AI_TURN.md: Build valid_charge_destinations pool using pathfinding with roll distance
            valid_destinations = self._get_valid_charge_destinations(unit, charge_roll)
            if valid_destinations:
                # Find enemy target adjacent to the first valid destination
                all_units = self.base.get_units()
                enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("CUR_HP") > 0]
                
                destination = valid_destinations[0]
                for enemy in enemy_units:
                    # Check if destination is adjacent to this enemy
                    dest_distance = max(abs(destination["col"] - enemy["col"]), abs(destination["row"] - enemy["row"]))
                    if dest_distance == 1:  # Adjacent
                        return {
                            "type": "charge",
                            "target_id": enemy["id"],
                            "destination_col": destination["col"],
                            "destination_row": destination["row"]
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
        # AI_TURN.md: Steps increment when unit ATTEMPTS action, NOT for auto-skip scenarios
        action_type = mirror_action.get("type", "wait")
        
        # Auto-skip scenarios (no step increment):
        if action_type == "auto_skip":
            return False
        if action_type == "wait" and mirror_action.get("reason") == "no_targets":
            return False
            
        # Real action attempts (step increment):
        return action_type in ["move", "shoot", "charge", "combat", "wait"]
        

                
    def _handle_no_active_unit(self, action: int) -> Tuple[Any, float, bool, bool, Dict[str, Any]]:
        """Handle case when no active unit is available."""
        current_phase = self.base.get_current_phase()
        current_player = self.base.get_current_player()
        
        print(f"🔄 No active unit for P{current_player} {current_phase} - checking phase completion")
        
        # AI_TURN.md: Phase is complete when no more eligible units remain
        is_complete = self._is_phase_complete()
        print(f"🔄 Phase complete: {is_complete}")
        
        if is_complete:            
            print(f"🔄 ADVANCING from P{current_player} {current_phase}")
            
            # Log phase transition if step logger connected
            if self.step_logger and self.step_logger.enabled:
                old_phase = self.base.get_current_phase()
                old_player = self.base.get_current_player()
            
            # Advance to next phase
            self._advance_phase()
            
            new_phase = self.base.get_current_phase()
            new_player = self.base.get_current_player()
            print(f"🔄 ADVANCED to P{new_player} {new_phase}")
            
            # Log the transition (AI_TURN.md compliance - no step increment)
            if self.step_logger and self.step_logger.enabled:
                current_turn = self.base.get_current_turn()
                # Enhanced phase logging with turn number
                self.step_logger.log_phase_transition(old_phase, new_phase, new_player, current_turn)
            
            # Check if game is over after phase advance
            if self.base.is_game_over():
                return self._build_gym_response(action, True, None, {"type": "phase_advance"}, terminated=True)
            else:
                return self._build_gym_response(action, True, None, {"type": "phase_advance"})
        else:
            # AI_TURN.md VIOLATION: This should never happen if eligibility rules are correct
            print(f"💥 CRITICAL ERROR: No active unit but phase not complete for P{current_player} {current_phase}")
            raise RuntimeError(f"AI_TURN.md violation: No active unit in phase '{current_phase}' but phase not complete")
            
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
                    # AI_TURN.md: Verify units_shot set is reset (base controller should handle this)
                    if len(self.base.game_state.get("units_shot", [])) > 0:
                        print(f"🔄 FORCED RESET: units_shot was not properly reset by base controller")
                        self.base.state_actions['reset_shot_units']()
                elif current_phase == "shoot":
                    self.base.phase_transitions['transition_to_charge']()
                    # AI_TURN.md: Verify units_charged set is reset (base controller should handle this)
                    if len(self.base.game_state.get("units_charged", [])) > 0:
                        print(f"🔄 FORCED RESET: units_charged was not properly reset by base controller")
                        self.base.state_actions['reset_charged_units']()
                elif current_phase == "charge":
                    self.base.phase_transitions['transition_to_combat']()
                    # AI_TURN.md: Verify units_attacked set is reset (base controller should handle this)
                    if len(self.base.game_state.get("units_attacked", [])) > 0:
                        print(f"🔄 FORCED RESET: units_attacked was not properly reset by base controller")
                        self.base.state_actions['reset_attacked_units']()
                elif current_phase == "combat":
                    # AI_TURN.md: After combat, always call end_turn for proper progression
                    self.base.phase_transitions['end_turn']()  # Handles P0→P1 and P1→P0(new turn)
                    # AI_TURN.md: After turn transition, verify units_moved is reset for new player
                    new_phase = self.base.get_current_phase()
                    new_player = self.base.get_current_player()
                    print(f"🔄 Turn transition: {current_player} {current_phase} → {new_player} {new_phase}")
                    if new_phase == "move":
                        units_moved = self.base.game_state.get("units_moved", [])
                        if len(units_moved) > 0:
                            print(f"🔄 FORCED RESET: units_moved was not properly reset by base controller (was {units_moved})")
                            self.base.state_actions['reset_moved_units']()
                        else:
                            print(f"✅ units_moved properly reset for new movement phase")
                        
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
                
            # Calculate reward - handle case where acting_unit is None (phase transitions)
            if acting_unit is None:
                # Phase transition - MUST get penalty reward from gym_env (no fallbacks)
                if hasattr(self.gym_env, '_get_small_penalty_reward'):
                    reward = self.gym_env._get_small_penalty_reward()
                else:
                    raise RuntimeError("Cannot calculate phase transition reward - gym_env missing _get_small_penalty_reward method")
            elif hasattr(self, 'gym_env') and hasattr(self.gym_env, '_calculate_reward'):
                reward = self.gym_env._calculate_reward(acting_unit, mirror_action, success)
            else:
                raise RuntimeError("Cannot access reward calculation - gym_env missing _calculate_reward method")
            
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