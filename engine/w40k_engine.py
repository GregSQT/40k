#!/usr/bin/env python3
"""
w40k_engine.py - AI_TURN.md Compliant W40K Game Engine
ZERO TOLERANCE for architectural violations

Core Principles:
- Sequential activation (ONE unit per gym step)
- Built-in step counting (NOT retrofitted)
- Phase completion by eligibility ONLY
- UPPERCASE field validation enforced
- Single source of truth (one game_state object)
"""

import json
import random
from typing import Dict, List, Tuple, Set, Optional, Any

# AI_IMPLEMENTATION.md: Import phase handlers for delegation pattern
from .phase_handlers import movement_handlers, shooting_handlers, charge_handlers, fight_handlers


class W40KEngine:
    """
    AI_TURN.md compliant W40K game engine.
    
    ARCHITECTURAL COMPLIANCE:
    - Single source of truth: Only one game_state object exists
    - Built-in step counting: episode_steps incremented in ONE location only
    - Sequential activation: ONE unit processed per gym step
    - Phase completion: Based on eligibility, NOT arbitrary step counts
    - UPPERCASE fields: All unit stats use proper naming convention
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize W40K engine with AI_TURN.md compliance."""
        self.config = config
        
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
            "board_width": config["board"]["width"],
            "board_height": config["board"]["height"],
            "wall_hexes": set(map(tuple, config["board"]["wall_hexes"]))
        }
        
        # Initialize units from config
        self._initialize_units()
        
        # Debug log initial state
        self._add_debug_logs([
            f"🏗️ ENGINE CONSTRUCTOR COMPLETE:",
            f"  - Phase: {self.game_state['phase']}",
            f"  - Move pool: {self.game_state.get('move_activation_pool', [])}",
            f"  - Units count: {len(self.game_state['units'])}"
        ])
    
    def _add_debug_logs(self, logs: List[str]):
        """Add debug logs to game state for frontend console."""
        if "debug_logs" not in self.game_state:
            self.game_state["debug_logs"] = []
        self.game_state["debug_logs"].extend(logs)
    
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
    
    def step(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute semantic action with built-in step counting.
        
        AI_TURN.md COMPLIANCE:
        - ONLY step counting location in entire codebase
        - Sequential activation: ONE unit per step
        - Accepts semantic actions: {'action': 'move', 'unitId': 1, 'destCol': 5, 'destRow': 3}
        """
        # BUILT-IN STEP COUNTING - Only location in entire system
        self.game_state["episode_steps"] += 1
        
        # Process semantic action with AI_TURN.md compliance
        success, result = self._process_semantic_action(action)
        
        return success, result
    
    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[List[float], Dict]:
        """Reset game state for new episode."""
        import traceback
        call_stack = traceback.format_stack()
        debug_logs = [
            f"🔄 RESET CALLED",
            f"  - Called from: {call_stack[-2].strip() if len(call_stack) > 1 else 'unknown'}"
        ]
        self._add_debug_logs(debug_logs)
        
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
        
        # Debug incoming action
        debug_logs = [
            f"🚶 PROCESSING MOVEMENT ACTION:",
            f"  - Action received: {action}",
            f"  - Pool before processing: {self.game_state.get('move_activation_pool', [])}",
        ]
        
        # AI_TURN.md COMPLIANCE: Pool should already exist from phase initialization
        debug_logs.append(f"  - Current pool: {self.game_state.get('move_activation_pool', [])}")
        
        # Pool should NEVER be empty during action processing if phase was properly initialized
        if not self.game_state.get("move_activation_pool"):
            debug_logs.append("  - CRITICAL ERROR: Pool empty during action - phase initialization failed")
        
        # AI_TURN.md LOOP: Check if phase should complete (empty pool means phase is done)
        if not self.game_state["move_activation_pool"]:
            debug_logs.append("  - Pool empty, advancing to shooting phase")
            self._phase_initialized = False
            self._shooting_phase_init()
            return True, {"type": "phase_complete", "next_phase": "shoot", "current_player": self.game_state["current_player"]}
        
        # AI_TURN.md COMPLIANCE: ONLY semantic actions with unitId
        if "unitId" not in action:
            debug_logs.append(f"  - ERROR: Missing unitId in action")
            self._add_debug_logs(debug_logs)
            return False, {"error": "semantic_action_required", "action": action}
        
        # Add logs to game state
        self._add_debug_logs(debug_logs)
        
        action_unit_id = str(action["unitId"])
        debug_logs = [
            f"🚶 UNIT ACTION PROCESSING:",
            f"  - Target unit ID: {action_unit_id}",
            f"  - Action type: {action.get('action', 'unknown')}",
        ]
        
        active_unit = self._get_unit_by_id(action_unit_id)
        if not active_unit:
            debug_logs.append(f"  - ERROR: Unit {action_unit_id} not found")
            self._add_debug_logs(debug_logs)
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        debug_logs.append(f"  - Unit found: {active_unit['id']} at ({active_unit['col']}, {active_unit['row']})")
        debug_logs.append(f"  - Current pool: {self.game_state['move_activation_pool']}")
        debug_logs.append(f"  - Unit in pool: {active_unit['id'] in self.game_state['move_activation_pool']}")
        
        if active_unit["id"] not in self.game_state["move_activation_pool"]:
            debug_logs.append(f"  - ERROR: Unit {active_unit['id']} not eligible")
            self._add_debug_logs(debug_logs)
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        debug_logs.append(f"  - Executing action via movement_handlers")
        self._add_debug_logs(debug_logs)
        
        # AI_IMPLEMENTATION.md: Delegate to pure function
        success, result = movement_handlers.execute_action(self.game_state, active_unit, action, self.config)
        
        debug_logs = [f"🚶 ACTION RESULT: success={success}, result={result}"]
        self._add_debug_logs(debug_logs)
        
        # Remove unit from activation pool AFTER successful action
        debug_logs = [f"🚶 POST-ACTION PROCESSING: success={success}"]
        if success:
            debug_logs.append(f"🚶 REMOVING UNIT FROM MOVE POOL: {active_unit['id']}")
            debug_logs.append(f"  - Pool before removal: {self.game_state['move_activation_pool']}")
            if active_unit["id"] in self.game_state["move_activation_pool"]:
                self.game_state["move_activation_pool"].remove(active_unit["id"])
                debug_logs.append(f"  - Unit {active_unit['id']} successfully removed")
            else:
                debug_logs.append(f"⚠️ WARNING: Unit {active_unit['id']} already removed from move pool")
            debug_logs.append(f"  - Move pool after removal: {self.game_state['move_activation_pool']}")
        else:
            debug_logs.append(f"  - Action failed, no removal needed")
        
        self._add_debug_logs(debug_logs)
        
        # AI_TURN.md LOOP: After removing unit, check if pool is now empty (same check condition)
        if success and not self.game_state["move_activation_pool"]:
            debug_logs = [
                "📋 MOVE PHASE ENDS - All units processed",
                "🔄 Transitioning to next phase"
            ]
            self._add_debug_logs(debug_logs)
            self._shooting_phase_init()
            result["phase_transition"] = True
            result["next_phase"] = "shoot"
       
        return success, result
    
    def _build_move_activation_pool(self):
        """Build movement activation pool using AI_IMPLEMENTATION.md delegation."""
        # Add debug logs to game state for frontend console
        debug_logs = [
            f"🚶 BUILDING MOVE ACTIVATION POOL:",
            f"  - Current player: {self.game_state['current_player']}",
            f"  - Pool before build: {self.game_state.get('move_activation_pool', [])}",
        ]
        eligible_units = movement_handlers.get_eligible_units(self.game_state)
        self.game_state["move_activation_pool"] = eligible_units
        debug_logs.extend([
            f"  - Pool after build: {eligible_units}",
            f"  - Total eligible units: {len(eligible_units)}"
        ])
        # Store in game state for API response
        if "debug_logs" not in self.game_state:
            self.game_state["debug_logs"] = []
        self.game_state["debug_logs"].extend(debug_logs)
    
    # AI_IMPLEMENTATION.md: Movement logic delegated to movement_handlers.py
    # All movement validation and execution now handled by pure functions
    
    # ===== PHASE TRANSITION LOGIC =====
    
    def _shooting_phase_init(self):
        """Initialize shooting phase and build activation pool."""
        debug_logs = [f"🎯 SHOOTING PHASE INITIALIZED - Building activation pool"]
        self._add_debug_logs(debug_logs)
        self.game_state["phase"] = "shoot"
        self._build_shoot_activation_pool()
    
    def _charge_phase_init(self):
        """Initialize charge phase and build activation pool."""
        debug_logs = [f"⚡ CHARGE PHASE INITIALIZED"]
        self._add_debug_logs(debug_logs)
        self.game_state["phase"] = "charge"
        # TODO: Build charge activation pool
    
    def _fight_phase_init(self):
        """Initialize fight phase and build activation pool."""
        debug_logs = [f"⚔️ FIGHT PHASE INITIALIZED"]
        self._add_debug_logs(debug_logs)
        self.game_state["phase"] = "fight"
        # TODO: Build fight activation pool
        # If no units eligible for shooting, advance immediately to charge
        if not self.game_state["shoot_activation_pool"]:
            self._charge_phase_init()

    def _process_shooting_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process shooting phase with AI_TURN.md decision tree logic."""
        
        # VERY BEGINNING of shooting phase - build pool
        if not hasattr(self, '_phase_initialized') or not self._phase_initialized:
            self._build_shoot_activation_pool()
            self._phase_initialized = True
        
        # Check if phase should complete (empty pool means phase is done)
        if not self.game_state["shoot_activation_pool"]:
            self._phase_initialized = False
            self._advance_to_charge_phase()
            return True, {"type": "phase_complete", "next_phase": "charge", "current_player": self.game_state["current_player"]}
        
        # AI_TURN.md COMPLIANCE: ONLY semantic actions with unitId
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        active_unit = self._get_unit_by_id(str(action["unitId"]))
        if not active_unit:
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        if active_unit["id"] not in self.game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        # Use internal shooting implementation to avoid action format conflicts
        success, result = self._execute_shooting_action(active_unit, action)
        
        # Remove unit from activation pool AFTER successful action
        if success:
            debug_logs = [
                f"🎯 REMOVING UNIT FROM SHOOT POOL: {active_unit['id']}",
                f"  - Shoot pool after removal: {self.game_state['shoot_activation_pool']}"
            ]
            self.game_state["shoot_activation_pool"].remove(active_unit["id"])
            debug_logs.append(f"  - Pool after removal: {self.game_state['shoot_activation_pool']}")
            self._add_debug_logs(debug_logs)
            
            # AI_TURN.md LOOP: After removing unit, check if pool is now empty (same check condition)
            if not self.game_state["shoot_activation_pool"]:
                self._phase_initialized = False
                self._advance_to_charge_phase()
                result["phase_transition"] = True
                result["next_phase"] = "charge"
        
        return success, result
    
    def _advance_to_charge_phase(self):
        """Advance to charge phase per AI_TURN.md progression."""
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
        import traceback
        call_stack = traceback.format_stack()
        debug_logs = [
            f"🚶 MOVEMENT PHASE INIT CALLED",
            f"  - Call from: {call_stack[-2].strip() if len(call_stack) > 1 else 'unknown'}"
        ]
        self._add_debug_logs(debug_logs)
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
    
    def _build_shoot_activation_pool(self):
        """Build shooting activation pool using AI_IMPLEMENTATION.md delegation."""
        debug_logs = [
            "🎯 BUILDING SHOOT ACTIVATION POOL DEBUG:",
            f"  - Current player: {self.game_state['current_player']}",
            f"  - Phase: {self.game_state['phase']}",
            f"  - Units in game: {len(self.game_state['units'])}"
        ]
        
        for unit in self.game_state["units"]:
            debug_logs.append(f"    Unit {unit['id']}: player={unit['player']}, HP={unit['HP_CUR']}, RNG_NB={unit.get('RNG_NB', 'MISSING')}")
        
        eligible_units = shooting_handlers.get_eligible_units(self.game_state)
        debug_logs.extend([
            f"  - Eligible units returned: {eligible_units}",
            f"  - Final pool: {eligible_units}"
        ])
        self.game_state["shoot_activation_pool"] = eligible_units
        self._add_debug_logs(debug_logs)
    
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
        # AI_IMPLEMENTATION.md: Delegate to shooting_handlers for consistency
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
    
    def _build_observation(self) -> List[float]:
        """Build observation vector for gym interface."""
        obs = []
        
        # Game state info
        obs.extend([
            self.game_state["current_player"],
            {"move": 0, "shoot": 1, "charge": 2, "fight": 3}[self.game_state["phase"]],
            self.game_state["turn"],
            self.game_state["episode_steps"]
        ])
        
        # Unit states (simplified)
        max_units = 10
        for i in range(max_units):
            if i < len(self.game_state["units"]):
                unit = self.game_state["units"][i]
                obs.extend([
                    unit["col"], unit["row"],
                    unit["HP_CUR"], unit["HP_MAX"],
                    unit["player"],
                    1 if unit["id"] in self.game_state["units_moved"] else 0
                ])
            else:
                obs.extend([0] * 6)  # Padding
        
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