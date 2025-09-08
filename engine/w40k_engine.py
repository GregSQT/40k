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
            
            # Combat state
            "combat_subphase": None,
            "charge_range_rolls": {},
            
            # Board state
            "board_width": config["board"]["width"],
            "board_height": config["board"]["height"],
            "wall_hexes": set(map(tuple, config["board"]["wall_hexes"]))
        }
        
        # Initialize units from config
        self._initialize_units()
    
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
            
            # Ranged combat stats - NO DEFAULTS
            "RNG_NB": config["RNG_NB"],
            "RNG_RNG": config["RNG_RNG"],
            "RNG_ATK": config["RNG_ATK"],
            "RNG_STR": config["RNG_STR"],
            "RNG_DMG": config["RNG_DMG"],
            "RNG_AP": config["RNG_AP"],
            
            # Close combat stats - NO DEFAULTS
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
            "combat_subphase": None,
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
        
        # Build initial activation pool for starting player
        self._build_move_activation_pool()
        
        observation = self._build_observation()
        info = {"phase": self.game_state["phase"]}
        
        return observation, info
    
    def _process_semantic_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Process semantic action using AI_TURN.md state machine.
        
        Phase sequence: move -> shoot -> charge -> combat -> next player
        Actions: {'action': 'move', 'unitId': 1, 'destCol': 5, 'destRow': 3}
        """
        current_phase = self.game_state["phase"]
        
        if current_phase == "move":
            return self._process_movement_phase(action)
        elif current_phase == "shoot":
            return self._process_shooting_phase(action)
        elif current_phase == "charge":
            return self._process_charge_phase(action)
        elif current_phase == "combat":
            return self._process_combat_phase(action)
        else:
            return False, {"error": "invalid_phase", "phase": current_phase}
    
    # ===== MOVEMENT PHASE IMPLEMENTATION =====
    
    def _process_movement_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process movement phase with AI_TURN.md decision tree logic."""
        
        # VERY BEGINNING of movement phase - clean tracking and build pool
        if not hasattr(self, '_phase_initialized') or not self._phase_initialized:
            self._tracking_cleanup()
            self._build_move_activation_pool()
            self._phase_initialized = True
        
        # Check if phase should complete (empty pool means phase is done)
        if not self.game_state["move_activation_pool"]:
            self._phase_initialized = False  # Reset for next phase
            self._advance_to_shooting_phase()
            return True, {"type": "phase_complete", "next_player": self.game_state["current_player"]}
        
        # AI_TURN.md COMPLIANCE: ONLY semantic actions with unitId
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        active_unit = self._get_unit_by_id(str(action["unitId"]))
        if not active_unit:
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        if active_unit["id"] not in self.game_state["move_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        # Remove requested unit from pool
        self.game_state["move_activation_pool"].remove(active_unit["id"])
        
        # Execute movement action
        success, result = self._execute_movement_action(active_unit, action)
        
        return success, result
    
    def _build_move_activation_pool(self):
        """Build movement activation pool using AI_TURN.md eligibility logic."""
        self.game_state["move_activation_pool"] = []
        current_player = self.game_state["current_player"]
        
        for unit in self.game_state["units"]:
            # AI_TURN.md eligibility: alive + current_player only
            if (unit["HP_CUR"] > 0 and 
                unit["player"] == current_player):
                self.game_state["move_activation_pool"].append(unit["id"])
    
    def _execute_movement_action(self, unit: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Execute semantic movement action with AI_TURN.md restrictions."""
        
        action_type = action.get("action")
        
        if action_type == "move":
            dest_col = action.get("destCol")
            dest_row = action.get("destRow")
            
            if dest_col is None or dest_row is None:
                return False, {"error": "missing_destination", "action": action}
            
            return self._attempt_movement_to_destination(unit, dest_col, dest_row)
            
        elif action_type == "skip":
            self.game_state["units_moved"].add(unit["id"])
            # AI_TURN.md: Right-click skip must end activation by removing from pool
            if unit["id"] in self.game_state["move_activation_pool"]:
                self.game_state["move_activation_pool"].remove(unit["id"])
            return True, {"action": "skip", "unitId": unit["id"]}
            
        else:
            return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "move"}
    
    def _attempt_movement_to_destination(self, unit: Dict[str, Any], dest_col: int, dest_row: int) -> Tuple[bool, Dict[str, Any]]:
        """Attempt unit movement to specific destination with AI_TURN.md validation."""
        
        # Validate destination
        if not self._is_valid_destination(dest_col, dest_row, unit):
            return False, {"error": "invalid_destination", "target": (dest_col, dest_row)}
        
        # Check for flee (was adjacent to enemy before move)
        was_adjacent = self._is_adjacent_to_enemy(unit)
        
        # Store original position
        orig_col, orig_row = unit["col"], unit["row"]
        
        # Execute movement
        unit["col"] = dest_col
        unit["row"] = dest_row
        
        # Apply AI_TURN.md tracking
        self.game_state["units_moved"].add(unit["id"])
        if was_adjacent:
            self.game_state["units_fled"].add(unit["id"])
        
        return True, {
            "action": "flee" if was_adjacent else "move",
            "unitId": unit["id"],
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col,
            "toRow": dest_row
        }
    
    def _attempt_movement(self, unit: Dict[str, Any], col_diff: int, row_diff: int) -> Tuple[bool, Dict[str, Any]]:
        """Attempt unit movement with AI_TURN.md validation."""
        new_col = unit["col"] + col_diff
        new_row = unit["row"] + row_diff
        
        # Validate destination
        if not self._is_valid_destination(new_col, new_row, unit):
            return False, {"error": "invalid_destination", "target": (new_col, new_row)}
        
        # Check for flee (was adjacent to enemy before move)
        was_adjacent = self._is_adjacent_to_enemy(unit)
        
        # Execute movement
        unit["col"] = new_col
        unit["row"] = new_row
        
        # Apply AI_TURN.md tracking
        self.game_state["units_moved"].add(unit["id"])
        if was_adjacent:
            self.game_state["units_fled"].add(unit["id"])
        
        return True, {
            "type": "flee" if was_adjacent else "move",
            "unit_id": unit["id"],
            "from": (unit["col"] - col_diff, unit["row"] - row_diff),
            "to": (new_col, new_row)
        }
    
    def _is_valid_destination(self, col: int, row: int, unit: Dict[str, Any]) -> bool:
        """Validate movement destination per AI_TURN.md restrictions."""
        
        # Board bounds check
        if (col < 0 or row < 0 or 
            col >= self.game_state["board_width"] or 
            row >= self.game_state["board_height"]):
            return False
        
        # Wall collision check
        if (col, row) in self.game_state["wall_hexes"]:
            return False
        
        # Unit occupation check
        for other_unit in self.game_state["units"]:
            if (other_unit["id"] != unit["id"] and 
                other_unit["HP_CUR"] > 0 and
                other_unit["col"] == col and 
                other_unit["row"] == row):
                return False
        
        # AI_TURN.md: Cannot move TO hexes adjacent to enemies
        if self._is_hex_adjacent_to_enemy(col, row, unit["player"]):
            return False
        
        return True
    
    def _is_adjacent_to_enemy(self, unit: Dict[str, Any]) -> bool:
        """Check if unit is adjacent to enemy (AI_TURN.md flee detection)."""
        cc_range = unit["CC_RNG"]
        
        for enemy in self.game_state["units"]:
            if (enemy["player"] != unit["player"] and enemy["HP_CUR"] > 0):
                distance = max(abs(unit["col"] - enemy["col"]), 
                              abs(unit["row"] - enemy["row"]))
                if distance <= cc_range:
                    return True
        return False
    
    def _is_hex_adjacent_to_enemy(self, col: int, row: int, player: int) -> bool:
        """Check if hex position is adjacent to any enemy unit."""
        for enemy in self.game_state["units"]:
            if enemy["player"] != player and enemy["HP_CUR"] > 0:
                distance = max(abs(col - enemy["col"]), abs(row - enemy["row"]))
                if distance <= 1:  # Adjacent check
                    return True
        return False
    
    # ===== PHASE TRANSITION LOGIC =====
    
    def _advance_to_shooting_phase(self):
        """Advance to shooting phase per AI_TURN.md progression."""
        self.game_state["phase"] = "shoot"
        self._phase_initialized = False  # Reset for shooting phase
    
    def _process_shooting_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Process shooting phase with AI_TURN.md decision tree logic."""
        
        # VERY BEGINNING of shooting phase - build pool
        if not hasattr(self, '_phase_initialized') or not self._phase_initialized:
            self._build_shoot_activation_pool()
            self._phase_initialized = True
        
        # Check if phase should complete (empty pool means phase is done)
        if not self.game_state["shoot_activation_pool"]:
            self._phase_initialized = False  # Reset for next phase
            self._advance_to_charge_phase()
            return True, {"type": "phase_complete", "next_phase": "charge"}
        
        # AI_TURN.md COMPLIANCE: ONLY semantic actions with unitId
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        active_unit = self._get_unit_by_id(str(action["unitId"]))
        if not active_unit:
            return False, {"error": "unit_not_found", "unitId": action["unitId"]}
        
        if active_unit["id"] not in self.game_state["shoot_activation_pool"]:
            return False, {"error": "unit_not_eligible", "unitId": action["unitId"]}
        
        # Remove requested unit from pool
        self.game_state["shoot_activation_pool"].remove(active_unit["id"])
        
        # Execute shooting action
        success, result = self._execute_shooting_action(active_unit, action)
        
        return success, result
    
    def _advance_to_charge_phase(self):
        """Advance to charge phase per AI_TURN.md progression."""
        self.game_state["phase"] = "charge"
        self.game_state["charge_activation_pool"] = []
    
    def _process_charge_phase(self, action: int) -> Tuple[bool, Dict[str, Any]]:
        """Placeholder for charge phase - implements AI_TURN.md decision tree."""
        # TODO: Implement charge phase logic
        self._advance_to_combat_phase()
        return self._process_combat_phase(action)
    
    def _advance_to_combat_phase(self):
        """Advance to combat phase per AI_TURN.md progression."""
        self.game_state["phase"] = "combat"
        self.game_state["combat_subphase"] = "charging_units"
    
    def _process_combat_phase(self, action: int) -> Tuple[bool, Dict[str, Any]]:
        """Placeholder for combat phase - implements AI_TURN.md sub-phases."""
        # TODO: Implement combat phase logic
        self._advance_to_next_player()
        return True, {"type": "phase_complete", "next_player": self.game_state["current_player"]}
    
    def _advance_to_next_player(self):
        """Advance to next player per AI_TURN.md turn progression."""
        self.game_state["current_player"] = 1 - self.game_state["current_player"]
        
        if self.game_state["current_player"] == 0:
            self.game_state["turn"] += 1
        
        self.game_state["phase"] = "move"
    
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
        """Build shooting activation pool using AI_TURN.md eligibility logic."""
        self.game_state["shoot_activation_pool"] = []
        current_player = self.game_state["current_player"]
        
        for unit in self.game_state["units"]:
            # AI_TURN.md eligibility: alive + current_player + not fled + not adjacent + has weapon + has targets
            if (unit["HP_CUR"] > 0 and 
                unit["player"] == current_player and
                unit["id"] not in self.game_state["units_fled"] and
                not self._is_adjacent_to_enemy(unit) and
                unit["RNG_NB"] > 0 and
                self._has_valid_shooting_targets(unit)):
                
                self.game_state["shoot_activation_pool"].append(unit["id"])
    
    def _has_valid_shooting_targets(self, unit: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
        for enemy in self.game_state["units"]:
            if (enemy["player"] != unit["player"] and 
                enemy["HP_CUR"] > 0 and
                self._is_valid_shooting_target(unit, enemy)):
                return True
        return False
    
    def _is_valid_shooting_target(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
        """Validate shooting target per AI_TURN.md restrictions."""
        
        # Range check
        distance = max(abs(shooter["col"] - target["col"]), abs(shooter["row"] - target["row"]))
        if distance > shooter["RNG_RNG"]:
            return False
        
        # Combat exclusion: target NOT adjacent to shooter
        if distance <= shooter["CC_RNG"]:
            return False
        
        # Friendly fire prevention: target NOT adjacent to any friendly units
        for friendly in self.game_state["units"]:
            if (friendly["player"] == shooter["player"] and 
                friendly["HP_CUR"] > 0 and 
                friendly["id"] != shooter["id"]):
                
                friendly_distance = max(abs(friendly["col"] - target["col"]), 
                                      abs(friendly["row"] - target["row"]))
                if friendly_distance <= 1:  # Adjacent to friendly
                    return False
        
        # Line of sight check
        return self._has_line_of_sight(shooter, target)
    
    def _has_line_of_sight(self, shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
        """Check line of sight between shooter and target."""
        # Simple implementation: blocked by walls only
        start_col, start_row = shooter["col"], shooter["row"]
        end_col, end_row = target["col"], target["row"]
        
        # Bresenham line algorithm for hex path
        hex_path = self._get_hex_line(start_col, start_row, end_col, end_row)
        
        # Check if any hex in path is a wall (excluding start and end)
        for col, row in hex_path[1:-1]:  # Skip start and end positions
            if (col, row) in self.game_state["wall_hexes"]:
                return False
        
        return True
    
    def _get_hex_line(self, start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
        """Get hex line between two points (simplified implementation)."""
        path = []
        
        # Simple linear interpolation for now
        steps = max(abs(end_col - start_col), abs(end_row - start_row))
        if steps == 0:
            return [(start_col, start_row)]
        
        for i in range(steps + 1):
            t = i / steps
            col = round(start_col + t * (end_col - start_col))
            row = round(start_row + t * (end_row - start_row))
            path.append((col, row))
        
        return path
    
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
            {"move": 0, "shoot": 1, "charge": 2, "combat": 3}[self.game_state["phase"]],
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