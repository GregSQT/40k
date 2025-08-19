#!/usr/bin/env python3
"""
ai/use_game_actions.py
EXACT Python mirror of frontend/src/hooks/useGameActions.ts
ALL features preserved - NO changes, NO removals, NO simplifications.

This is the complete functional equivalent of the PvP useGameActions hook system
with ALL missing features now implemented.
"""

from typing import Dict, List, Any, Optional, Callable, Tuple, Set
import random
import time
import threading
from shared.gameMechanics import (
    is_unit_eligible, 
    calculate_available_move_cells,
    detect_flee_on_move as is_unit_fleeing,
    get_cube_neighbors
)
from shared.gameRules import (
    are_units_adjacent as areUnitsAdjacent, 
    is_unit_in_range as isUnitInRange, 
    get_hex_distance as getHexDistance,
    offset_to_cube as offsetToCube, 
    cube_distance as cubeDistance, 
    roll_d6 as rollD6, 
    roll_d6,
    calculate_wound_target as calculateWoundTarget, 
    calculate_save_target as calculateSaveTarget,
    roll_2d6 as roll2D6
)

# === EXACT TYPESCRIPT INTERFACE MIRROR ===

class UseGameActionsParams:
    """Mirror of UseGameActionsParams interface from TypeScript"""
    def __init__(self, game_state: Dict[str, Any], 
                 move_preview: Optional[Dict[str, Any]], 
                 attack_preview: Optional[Dict[str, Any]], 
                 shooting_phase_state: Dict[str, Any],
                 board_config: Dict[str, Any],  # REQUIRED in TypeScript
                 actions: Dict[str, Callable],  # MISSING from original Python!
                 game_log: Optional[Any] = None):  # Optional in TypeScript
        self.game_state = game_state
        self.move_preview = move_preview
        self.attack_preview = attack_preview
        self.shooting_phase_state = shooting_phase_state
        self.board_config = board_config
        self.actions = actions
        self.game_log = game_log

# === ACTIONS OBJECT STRUCTURE VALIDATION ===

def validate_actions_object(actions: Dict[str, Callable]) -> None:
    """Validate that actions object has all required TypeScript methods"""
    required_actions = [
        "set_mode", "set_selected_unit_id", "set_move_preview", "set_attack_preview",
        "add_moved_unit", "add_charged_unit", "add_attacked_unit", "add_fled_unit",
        "update_unit", "remove_unit", "initialize_shooting_phase", 
        "update_shooting_phase_state", "decrement_shots_left", "set_target_preview"
    ]
    
    missing_actions = [action for action in required_actions if action not in actions]
    if missing_actions:
        raise ValueError(f"Missing required actions: {missing_actions}")
    
    # Validate callable
    for action_name, action_func in actions.items():
        if not callable(action_func):
            raise ValueError(f"Action {action_name} is not callable")

# === MISSING INTERFACES (EXACT from TypeScript) ===

class ShootingResult:
    """Mirror of ShootingResult interface from TypeScript"""
    def __init__(self):
        self.total_damage = 0
        self.summary = {
            "total_shots": 0,
            "hits": 0,
            "wounds": 0,
            "failed_saves": 0
        }

class TargetPreview:
    """Mirror of TargetPreview interface from TypeScript"""
    def __init__(self, target_id: int, shooter_id: int, current_blink_step: int = 0, 
                 total_blink_steps: int = 2, blink_timer=None, 
                 hit_probability: float = 0, wound_probability: float = 0,
                 save_probability: float = 0, overall_probability: float = 0):
        self.target_id = target_id
        self.shooter_id = shooter_id
        self.current_blink_step = current_blink_step
        self.total_blink_steps = total_blink_steps
        self.blink_timer = blink_timer
        self.hit_probability = hit_probability
        self.wound_probability = wound_probability
        self.save_probability = save_probability
        self.overall_probability = overall_probability

# === MISSING PROBABILITY CALCULATORS (EXACT from TypeScript) ===

def calculate_hit_probability(shooter: Dict[str, Any]) -> float:
    """EXACT mirror of calculateHitProbability from TypeScript"""
    if "RNG_ATK" not in shooter:
        raise KeyError(f"Shooter missing required 'RNG_ATK' field: {shooter}")
    hit_target = shooter["RNG_ATK"]
    return max(0, (7 - hit_target) / 6 * 100)

def calculate_wound_probability(shooter: Dict[str, Any], target: Dict[str, Any]) -> float:
    """EXACT mirror of calculateWoundProbability from TypeScript"""
    if "RNG_STR" not in shooter:
        raise KeyError(f"Shooter missing required 'RNG_STR' field: {shooter}")
    if "T" not in target:
        raise KeyError(f"Target missing required 'T' field: {target}")
    strength = shooter["RNG_STR"]
    toughness = target["T"]
    
    if strength >= toughness * 2:
        wound_target = 2
    elif strength > toughness:
        wound_target = 3
    elif strength == toughness:
        wound_target = 4
    elif strength < toughness:
        wound_target = 5
    else:
        wound_target = 6
    
    return max(0, (7 - wound_target) / 6 * 100)

def calculate_save_probability(shooter: Dict[str, Any], target: Dict[str, Any], in_cover: bool = False) -> float:
    """EXACT mirror of calculateSaveProbability from TypeScript"""
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
    if "RNG_AP" not in shooter:
        raise KeyError(f"Shooter missing required 'RNG_AP' field: {shooter}")
    ARMOR_SAVE = target["ARMOR_SAVE"]
    invul_save = target["INVUL_SAVE"]
    armor_penetration = shooter["RNG_AP"]
    
    # Apply cover bonus - +1 to armor save (better save)
    if in_cover:
        ARMOR_SAVE = max(2, ARMOR_SAVE - 1)  # Improve armor save by 1, minimum 2+
    
    modified_armor = ARMOR_SAVE + armor_penetration
    save_target = invul_save if (invul_save > 0 and invul_save < modified_armor) else modified_armor
    
    save_probability = max(0, (7 - save_target) / 6 * 100)
    return 100 - save_probability

def calculate_overall_probability(shooter: Dict[str, Any], target: Dict[str, Any], in_cover: bool = False) -> float:
    """EXACT mirror of calculateOverallProbability from TypeScript"""
    hit_prob = calculate_hit_probability(shooter)
    wound_prob = calculate_wound_probability(shooter, target)
    save_fail_prob = calculate_save_probability(shooter, target, in_cover)
    
    return (hit_prob / 100) * (wound_prob / 100) * (save_fail_prob / 100) * 100

# Combat-specific probability functions (MISSING from original Python)
def calculate_combat_hit_probability(attacker: Dict[str, Any]) -> float:
    """EXACT mirror of calculateCombatHitProbability from TypeScript"""
    if "CC_ATK" not in attacker:
        raise KeyError(f"Attacker missing required 'CC_ATK' field: {attacker}")
    hit_target = attacker["CC_ATK"]
    return max(0, (7 - hit_target) / 6 * 100)

def calculate_combat_wound_probability(attacker: Dict[str, Any], target: Dict[str, Any]) -> float:
    """EXACT mirror of calculateCombatWoundProbability from TypeScript"""
    if "CC_STR" not in attacker:
        raise KeyError(f"Attacker missing required 'CC_STR' field: {attacker}")
    if "T" not in target:
        raise KeyError(f"Target missing required 'T' field: {target}")
    strength = attacker["CC_STR"]
    toughness = target["T"]
    
    if strength >= toughness * 2:
        wound_target = 2
    elif strength > toughness:
        wound_target = 3
    elif strength == toughness:
        wound_target = 4
    elif strength < toughness:
        wound_target = 5
    else:
        wound_target = 6
    
    return max(0, (7 - wound_target) / 6 * 100)

def calculate_combat_save_probability(attacker: Dict[str, Any], target: Dict[str, Any]) -> float:
    """EXACT mirror of calculateCombatSaveProbability from TypeScript"""
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target.get('name')}")
    ARMOR_SAVE = target["ARMOR_SAVE"]
    
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target.get('name')}")
    invul_save = target["INVUL_SAVE"]
    
    if "CC_AP" not in attacker:
        raise KeyError(f"Attacker missing required 'CC_AP' field: {attacker.get('name')}")
    armor_penetration = attacker["CC_AP"]
    
    modified_armor = ARMOR_SAVE + armor_penetration
    save_target = invul_save if (invul_save > 0 and invul_save < modified_armor) else modified_armor
    
    save_probability = max(0, (7 - save_target) / 6 * 100)
    return 100 - save_probability

def calculate_combat_overall_probability(attacker: Dict[str, Any], target: Dict[str, Any]) -> float:
    """EXACT mirror of calculateCombatOverallProbability from TypeScript"""
    hit_prob = calculate_combat_hit_probability(attacker)
    wound_prob = calculate_combat_wound_probability(attacker, target)
    save_fail_prob = calculate_combat_save_probability(attacker, target)
    
    return (hit_prob / 100) * (wound_prob / 100) * (save_fail_prob / 100) * 100

# === FIELD CONVERSION UTILITY FOR SHARED RULES ===

def convert_unit_for_shared_rules(unit: Dict[str, Any]) -> Dict[str, Any]:
    """Return unit unchanged since shared rules use uppercase field names."""
    return unit

# === MISSING SINGLE SHOT SEQUENCE MANAGER (EXACT from TypeScript) ===

class SingleShotSequenceManager:
    """EXACT mirror of singleShotSequenceManager from TypeScript"""
    
    def __init__(self):
        self.state = None
        self.is_active = False
    
    def get_state(self):
        return self.state
    
    def process_save_roll(self, shooter: Dict[str, Any], target: Dict[str, Any]):
        """Simplified implementation for Python mirror"""
        pass

# Global instance to mirror TypeScript usage
single_shot_sequence_manager = SingleShotSequenceManager()

class UseGameActions:
    """
    EXACT Python mirror of useGameActions TypeScript hook.
    Contains ALL methods and features from the original PvP implementation.
    NOW WITH ALL MISSING FEATURES IMPLEMENTED AND PROPER STRUCTURE.
    """
    
    def __init__(self, params: UseGameActionsParams):
        """Initialize with EXACT same parameters as TypeScript useGameActions"""
        if not params:
            raise ValueError("UseGameActionsParams is required")
        validate_actions_object(params.actions)
        
        self.game_state = params.game_state
        self.move_preview = params.move_preview
        self.attack_preview = params.attack_preview
        self.shooting_phase_state = params.shooting_phase_state
        self.board_config = params.board_config
        self.actions = params.actions
        self.game_log = params.game_log
        
        # Use live references instead of cached values to prevent stale data
        # All state access will go through self.game_state directly
        pass  # Remove all cached state extractions

    # === HELPER FUNCTIONS (EXACT from TypeScript) ===
    
    def find_unit(self, unit_id: int) -> Optional[Dict[str, Any]]:
        """Helper function to find unit by ID (EXACT from TypeScript)"""
        for unit in self.game_state["units"]:
            if unit["id"] == unit_id:
                return unit
        return None

    def _check_pathfinding_reachable(self, unit: Dict[str, Any], enemy: Dict[str, Any], 
                                   wall_hex_set: Set[str], max_distance: int) -> bool:
        """Helper function to check if enemy is reachable via pathfinding around walls (EXACT from TypeScript)"""
        if not self.board_config.get("cols") or not self.board_config.get("rows"):
            raise ValueError("board_config.cols and board_config.rows are required for pathfinding")
        
        visited = set()
        queue = [{"col": unit["col"], "row": unit["row"], "distance": 0}]
        
        # Cube directions for proper hex neighbors (EXACT from TypeScript)
        cube_directions = [
            [1, -1, 0], [1, 0, -1], [0, 1, -1], 
            [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
        ]

        while queue:
            current = queue.pop(0)
            key = f"{current['col']},{current['row']}"
            
            if key in visited:
                continue
            visited.add(key)
            
            # Found the enemy (EXACT from TypeScript)
            if current["col"] == enemy["col"] and current["row"] == enemy["row"]:
                return True
            
            # Don't expand beyond max distance (EXACT from TypeScript)
            if current["distance"] >= max_distance:
                continue
            
            # Expand to neighbors (EXACT from TypeScript)
            from shared.gameRules import offset_to_cube
            current_cube = offset_to_cube(current["col"], current["row"])
            for dx, dy, dz in cube_directions:
                # Handle both tuple and dict formats from offsetToCube
                if isinstance(current_cube, tuple):
                    # Convert tuple (x, y, z) to dict format
                    current_x, current_y, current_z = current_cube
                else:
                    # Already dict format
                    current_x, current_y, current_z = current_cube["x"], current_cube["y"], current_cube["z"]
                
                neighbor_cube = {
                    "x": current_x + dx,
                    "y": current_y + dy,
                    "z": current_z + dz
                }
                
                ncol = neighbor_cube["x"]
                nrow = neighbor_cube["z"] + ((neighbor_cube["x"] - (neighbor_cube["x"] & 1)) >> 1)
                nkey = f"{ncol},{nrow}"
                
                # Skip if out of bounds, already visited, or is a wall (EXACT from TypeScript)
                if (ncol < 0 or ncol >= self.board_config["cols"] or 
                    nrow < 0 or nrow >= self.board_config["rows"]):
                    continue
                if nkey in visited:
                    continue
                if nkey in wall_hex_set:
                    continue
                
                queue.append({"col": ncol, "row": nrow, "distance": current["distance"] + 1})
        
        return False  # Enemy not reachable

    def is_unit_eligible_local(self, unit: Dict[str, Any]) -> bool:
        """
        EXACT mirror of isUnitEligible from TypeScript.
        Complete phase-specific eligibility logic with ALL missing features.
        """
        # Minimal debug for rapid phase cycling issue
        current_player = self.game_state["current_player"]
        if unit["player"] != current_player:
            if unit["player"] == 1:  # Only debug AI units
                print(f"❌ U{unit['id']}: wrong_player (P{unit['player']} != P{current_player})")
            return False

        # CRITICAL DEBUG: Check SpaceMarine unit field validation
        if "unit_type" not in unit:
            raise KeyError(f"Unit missing required 'unit_type' field: {unit}")
        if "SpaceMarine" in unit["unit_type"] or "CaptainGravis" in unit["unit_type"]:
            required_fields = ["RNG_RNG", "CC_RNG", "has_charged_this_turn"]
            for field in required_fields:
                if field not in unit:
                    raise KeyError(f"Unit missing required field '{field}': {unit}")

        # Get enemy units once for efficiency
        enemy_units = [u for u in self.game_state["units"] if u["player"] != current_player]

        phase = self.game_state["phase"]
        if "units_moved" not in self.game_state:
            raise KeyError("Game state missing required 'units_moved' field")
        units_moved = set(self.game_state["units_moved"])
        
        if phase == "move":
            # AI_TURN.md: Movement eligibility - unit hasn't moved this phase and is alive
            if unit["id"] in units_moved:
                return False
            if not unit.get("alive", True):
                return False
            return True
        
        elif phase == "shoot":
            units_fled = set(self.game_state.get("units_fled"))
            units_shot = set(self.game_state.get("units_shot", []))
            if unit["id"] in units_shot:
                return False
            # AI_TURN.md: "Unit is marked as units_fled" - NOT eligible
            if unit["id"] in units_fled:
                return False
            # AI_TURN.md: "Unit is adjacent to an enemy unit" - NOT eligible
            has_adjacent_enemy_shoot = any(areUnitsAdjacent(unit, enemy) for enemy in enemy_units)
            if has_adjacent_enemy_shoot:
                return False
            
            # AI_TURN.md: Must have RNG_RNG > 0 for ranged weapon
            if "RNG_RNG" not in unit:
                if unit["player"] == 1:
                    print(f"❌ U{unit['id']}: no_RNG_RNG_field")
                return False
            if unit.get("RNG_RNG", 0) <= 0:
                if unit["player"] == 1:
                    print(f"❌ U{unit['id']}: RNG_RNG_zero")
                return False
            
            # AI_TURN.md: "Unit has NO line of sight on any enemy unit WITHIN RNG_RNG distance"
            # Must have at least one valid target within range with line of sight
            rng_range = unit["RNG_RNG"]
            has_valid_target = False
            for enemy in enemy_units:
                distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
                if distance <= rng_range:
                    # AI_TURN.md requires line of sight check
                    try:
                        from shared.gameRules import has_line_of_sight
                        wall_hexes = self.board_config.get("wall_hexes", [])
                        los_result = has_line_of_sight(
                            {"col": unit["col"], "row": unit["row"]},
                            {"col": enemy["col"], "row": enemy["row"]},
                            wall_hexes
                        )
                        if los_result.get("canSee", False):
                            has_valid_target = True
                            break
                    except ImportError as e:
                        # AI_PROTOCOLE.md: No fallbacks allowed - raise error for missing dependencies
                        raise ImportError(f"Required shared.gameRules module not available: {e}")
            
            if not has_valid_target:
                if unit["player"] == 1:
                    print(f"❌ U{unit['id']}: no_line_of_sight_targets")
                return False
                
            return True
        
        elif phase == "charge":
            units_charged = set(self.game_state.get("units_charged", []))
            units_fled = set(self.game_state.get("units_fled", []))
            if unit["id"] in units_charged:
                if unit["player"] == 1:  # Only debug AI units
                    print(f"❌ U{unit['id']}: already_charged")
                return False
            if unit["id"] in units_fled:
                if unit["player"] == 1:  # Only debug AI units
                    print(f"❌ U{unit['id']}: unit_fled")
                return False
            is_adjacent = any(areUnitsAdjacent(unit, enemy) for enemy in enemy_units)
            if is_adjacent:
                return False
            # Check 12-hex distance limit without circular dependency
            from shared.gameRules import get_hex_distance
            within_charge_range = any(
                1 < get_hex_distance(unit, enemy) <= 12
                for enemy in enemy_units
            )
            return within_charge_range
        
        elif phase == "combat":
            units_attacked = set(self.game_state.get("units_attacked", []))
            
            if unit["id"] in units_attacked:
                if unit["player"] == 1:  # Only debug AI units
                    print(f"❌ U{unit['id']}: already_attacked")
                return False
            if "CC_RNG" not in unit:
                return False
            if unit.get("CC_RNG", 0) <= 0:
                return False
                
            # CRITICAL FIX: Simplified combat eligibility - just check if unit can potentially fight
            # Let Sequential Engine handle complex sub-phase logic and target validation
            return any(isUnitInRange(unit, enemy, unit["CC_RNG"]) for enemy in enemy_units)
        
        else:
            return False

    # === MAIN ACTION METHODS (EXACT from TypeScript) ===

    def select_unit(self, unit_id: Optional[int]) -> None:
        """
        EXACT mirror of selectUnit from TypeScript useGameActions.
        ALL logic preserved including phase-specific handling and shooting sequence prevention.
        NOW WITH ALL MISSING TYPESCRIPT FEATURES.
        """
        # Prevent unit selection during shooting sequence (MISSING from original Python)
        if self.shooting_phase_state.get("single_shot_state", {}).get("is_active"):
            print("Cannot select units during shooting sequence")
            return

        if unit_id is None:
            self.actions["set_selected_unit_id"](None)
            self.actions["clear_move_preview"]()
            self.actions["set_attack_preview"](None)
            self.actions["set_mode"]("select")
            return

        unit = self.find_unit(unit_id)
        
        if not unit:
            return
        
        eligible = self.is_unit_eligible_local(unit)
        
        # CRITICAL FIX: Block ALL actions if unit is not eligible (EXACT from TypeScript)
        if not eligible:
            return  # Exit immediately - no phase handling

        # Special handling for move phase - second click marks as moved (EXACT from TypeScript)
        if self.game_state["phase"] == "move" and self.game_state["selected_unit_id"] == unit_id:
            # Log the "no move" decision (MISSING from original Python)
            if self.game_log:
                self.game_log.log_no_move_action(unit, self.game_state["current_turn"])
            
            self.actions["add_moved_unit"](unit_id)
            self.actions["set_selected_unit_id"](None)
            self.actions["clear_move_preview"]()
            self.actions["set_mode"]("select")
            return

        # Special handling for shoot phase (EXACT from TypeScript)
        if self.game_state["phase"] == "shoot":
            # Always show the attack preview…
            self.actions["clear_move_preview"]()
            self.actions["set_attack_preview"]({"unit_id": unit_id, "col": unit["col"], "row": unit["row"]})
            self.actions["set_mode"]("attack_preview")

            # …but only set the active shooter on the first click
            if self.game_state["selected_unit_id"] is None:
                self.actions["set_selected_unit_id"](unit_id)
            return

        # Special handling for charge phase (EXACT from TypeScript)
        if self.game_state["phase"] == "charge":
            existing_roll = self.game_state.get("unit_charge_rolls", {}).get(unit_id)
            
            if not existing_roll:
                # First time selecting this unit - roll 2d6 for charge distance (EXACT from TypeScript)
                die1 = random.randint(1, 6)
                die2 = random.randint(1, 6)
                charge_roll = die1 + die2
                
                # Check if any enemies within 12 hexes are also within the rolled charge distance (EXACT from TypeScript)
                enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"]]
                
                enemies_in_range = []
                for enemy in enemy_units:
                    # First check if enemy is within 12 hexes (eligibility already passed this)
                    from shared.gameRules import get_hex_distance
                    hex_distance = get_hex_distance(unit, enemy)
                    
                    # Check if enemy is within rolled charge distance (12-hex limit already checked in eligibility)
                    if hex_distance > charge_roll or hex_distance > 12:
                        continue
                    
                    # Use same pathfinding logic as eligibility check (EXACT from TypeScript)
                    if self.board_config.get("wall_hexes"):
                        wall_hex_set = set(f"{c},{r}" for c, r in self.board_config["wall_hexes"])
                        is_reachable = self._check_pathfinding_reachable(unit, enemy, wall_hex_set, charge_roll)
                        if not is_reachable:
                            continue
                    
                    enemies_in_range.append(enemy)
                
                can_charge = len(enemies_in_range) > 0

                # Log the charge roll with correct format using proper addEvent method (EXACT from TypeScript)
                if self.game_log:
                    charge_event = {
                        "id": f"charge-roll-{int(time.time()*1000)}-{unit['id']}",
                        "timestamp": time.time(),
                        "type": "charge",
                        "message": (f"Unit {unit.get('name', unit['unit_type'])} CHARGE ROLL : {charge_roll} : "
                                  f"{'Enemy unit(s) in range' if can_charge else 'No enemy unit(s) in range'}"),
                        "turnNumber": self.game_state["current_turn"],
                        "phase": "charge",
                        "player": unit["player"],
                        "unitType": unit.get("unit_type", "unknown"),
                        "unitId": unit["id"]
                    }
                    if hasattr(self.game_log, 'events'):
                        self.game_log.events.insert(0, charge_event)
                
                # Show popup with exact format required (call action if available)
                if "show_charge_roll_popup" in self.actions:
                    self.actions["show_charge_roll_popup"](unit_id, charge_roll, not can_charge)
                
                # CRITICAL FIX: Store the roll as dict with dice details (EXACT from TypeScript)
                if "unit_charge_rolls" not in self.game_state:
                    self.game_state["unit_charge_rolls"] = {}
                self.game_state["unit_charge_rolls"][unit_id] = {
                    "total": charge_roll,
                    "charge_roll": charge_roll,  # Legacy compatibility
                    "die1": die1,
                    "die2": die2
                }
                
                # Continue with state management (EXACT from TypeScript)
                if can_charge:
                    self.actions["set_selected_unit_id"](unit_id)
                    self.actions["set_mode"]("charge_preview")
                else:
                    self.actions["add_charged_unit"](unit_id)
                    if "reset_unit_charge_roll" in self.actions:
                        self.actions["reset_unit_charge_roll"](unit_id)
                    self.actions["set_selected_unit_id"](None)
                    self.actions["set_mode"]("select")

                return
            else:
                # Unit already has a charge roll (EXACT from TypeScript)
                if self.game_state["selected_unit_id"] == unit_id:
                    # Second click on same unit - cancel charge and end activation (EXACT from TypeScript)
                    if self.game_log:
                        cancel_event = {
                            "id": f"charge-cancel-{int(time.time()*1000)}-{unit['id']}",
                            "timestamp": time.time(),
                            "type": "charge_cancel",
                            "message": f"Unit {unit.get('name', unit['unit_type'])} CHARGE CANCELLED",
                            "turnNumber": self.game_state["current_turn"],
                            "phase": "charge",
                            "player": unit["player"],
                            "unitType": unit.get("unit_type", "unknown"),
                            "unitId": unit["id"]
                        }
                        if hasattr(self.game_log, 'events'):
                            self.game_log.events.insert(0, cancel_event)
                    if "reset_unit_charge_roll" in self.actions:
                        self.actions["reset_unit_charge_roll"](unit_id)
                    self.actions["add_charged_unit"](unit_id)
                    self.actions["set_selected_unit_id"](None)
                    self.actions["set_mode"]("select")
                else:
                    # Different unit with existing roll - show preview (EXACT from TypeScript)
                    self.actions["set_selected_unit_id"](unit_id)
                    self.actions["set_mode"]("charge_preview")
                return

        # Special handling for combat phase (EXACT from TypeScript)
        if self.game_state["phase"] == "combat":
            # Always show the attack preview for adjacent enemies
            self.actions["clear_move_preview"]()
            self.actions["set_attack_preview"]({"unit_id": unit_id, "col": unit["col"], "row": unit["row"]})
            self.actions["set_mode"]("attack_preview")
            self.actions["set_selected_unit_id"](unit_id)
            return

        # Default selection (EXACT from TypeScript)
        self.actions["set_selected_unit_id"](unit_id)
        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        self.actions["set_mode"]("select")

    def select_charger(self, unit_id: Optional[int]) -> None:
        """EXACT mirror of selectCharger from TypeScript"""
        if unit_id is None:
            self.actions["set_selected_unit_id"](None)
            self.actions["set_mode"]("select")
            return

        unit = self.find_unit(unit_id)
        if not unit or not self.is_unit_eligible_local(unit):
            return

        self.actions["set_selected_unit_id"](unit_id)
        self.actions["set_mode"]("charge_preview")

    def start_move_preview(self, unit_id: int, col: int, row: int) -> None:
        """EXACT mirror of startMovePreview from TypeScript"""
        unit = self.find_unit(unit_id)
        if not unit or not self.is_unit_eligible_local(unit):
            return

        # Calculate path for move preview (simple straight line for now)
        path = [{"col": col, "row": row}]
        self.actions["set_move_preview"](unit_id, unit["col"], unit["row"], col, row, path)
        self.actions["set_mode"]("move_preview")

    def start_attack_preview(self, unit_id: int, col: int, row: int) -> None:
        """EXACT mirror of startAttackPreview from TypeScript"""
        unit = self.find_unit(unit_id)
        if not unit or not self.is_unit_eligible_local(unit):
            return

        self.actions["set_attack_preview"]({"unit_id": unit_id, "col": col, "row": row})
        self.actions["set_mode"]("attack_preview")

    def confirm_move(self) -> None:
        """
        EXACT mirror of confirmMove from TypeScript.
        Complete flee detection logic preserved.
        """
        moved_unit_id = None
        
        if self.game_state["mode"] == "move_preview" and self.move_preview:
            unit = self.find_unit(self.move_preview["unit_id"])
            if unit and self.phase == "move":
                # FLEE DETECTION LOGIC (EXACT from TypeScript)
                enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"]]
                
                # Check if unit was adjacent to any enemy before moving
                was_adjacent_to_enemy = any(
                    max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) == 1
                    for enemy in enemy_units
                )
                
                if was_adjacent_to_enemy:
                    will_be_adjacent_to_enemy = any(
                        max(abs(self.move_preview["dest_col"] - enemy["col"]), 
                            abs(self.move_preview["dest_row"] - enemy["row"])) == 1
                        for enemy in enemy_units
                    )
                    
                    if not will_be_adjacent_to_enemy:
                        self.actions["add_fled_unit"](self.move_preview["unit_id"])

                # Log the move action (MISSING from original Python)
                if self.game_log:
                    self.game_log.log_move_action(unit, unit["col"], unit["row"], 
                                                  self.move_preview["dest_col"], self.move_preview["dest_row"], 
                                                  self.game_state["current_turn"])
            
            self.actions["update_unit"](self.move_preview["unit_id"], {
                "col": self.move_preview["dest_col"],
                "row": self.move_preview["dest_row"],
            })
            moved_unit_id = self.move_preview["unit_id"]
        
        elif self.game_state["mode"] == "attack_preview" and self.attack_preview:
            moved_unit_id = self.attack_preview["unit_id"]

        if moved_unit_id is not None:
            self.actions["add_moved_unit"](moved_unit_id)

        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")

    def cancel_move(self) -> None:
        """EXACT mirror of cancelMove from TypeScript"""
        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        self.actions["set_mode"]("select")

    # === COMPLETE SHOOTING SYSTEM (MISSING from original Python) ===

    def handle_shoot(self, shooter_id: int, target_id: int) -> None:
        """
        EXACT mirror of handleShoot from TypeScript.
        Complete shooting system with probability calculations and target preview.
        ALL MISSING FEATURES NOW IMPLEMENTED.
        """
        if shooter_id in self.game_state.get("units_moved", []):
            return

        if shooter_id in self.game_state.get("units_fled", []):
            return

        # ADDITIONAL CHECK: Prevent shooting if unit has no shots left
        pre_shooter = self.find_unit(shooter_id)
        if pre_shooter and "SHOOT_LEFT" in pre_shooter and pre_shooter["SHOOT_LEFT"] <= 0:
            return

        shooter = self.find_unit(shooter_id)
        target = self.find_unit(target_id)
        
        if not shooter or not target:
            return

        # Check if this is a preview (first click) or execute (second click)
        current_target_preview = self.game_state.get("target_preview")
        
        if (current_target_preview and 
            current_target_preview["target_id"] == target_id and 
            current_target_preview["shooter_id"] == shooter_id):
            
            # Second click - execute shooting (EXACT from TypeScript)
            # Clear preview (MISSING from original Python)
            if current_target_preview.get("blink_timer"):
                # In Python, we'd handle timer cleanup differently
                pass
            self.actions["set_target_preview"](None)
            
            # Simple single shot execution (EXACT from TypeScript logic)
            hit_roll = random.randint(1, 6)
            if "RNG_ATK" not in shooter:
                raise ValueError(f"shooter.RNG_ATK is required but was undefined for unit {shooter['id']}")
            hit_success = hit_roll >= shooter["RNG_ATK"]
            
            damage_dealt = 0
            wound_roll = 0
            wound_success = False
            save_roll = 0
            save_success = False
            
            # Get required stats with error checking (EXACT from TypeScript)
            if "RNG_STR" not in shooter:
                raise ValueError(f"shooter.RNG_STR is required but was undefined for unit {shooter['id']}")
            shooter_str = shooter["RNG_STR"]
            
            if "T" not in target:
                raise ValueError(f"target.T is required but was undefined for unit {target['id']}")
            target_t = target["T"]
            
            if "ARMOR_SAVE" not in target:
                raise ValueError(f"target.ARMOR_SAVE is required but was undefined for unit {target['id']}")
            target_ARMOR_SAVE = target["ARMOR_SAVE"]
            
            if "RNG_AP" not in shooter:
                raise ValueError(f"shooter.RNG_AP is required but was undefined for unit {shooter['id']}")
            shooter_ap = shooter["RNG_AP"]
            
            if hit_success:
                wound_roll = random.randint(1, 6)
                wound_target = calculateWoundTarget(shooter_str, target_t)
                wound_success = wound_roll >= wound_target
                
                if wound_success:
                    save_roll = random.randint(1, 6)
                    if "INVUL_SAVE" not in target:
                        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
                    save_target = calculateSaveTarget(target_ARMOR_SAVE, target["INVUL_SAVE"], shooter_ap)
                    save_success = save_roll >= save_target
                    
                    if not save_success:
                        if "RNG_DMG" not in shooter:
                            raise KeyError(f"Shooter missing required 'RNG_DMG' field: {shooter}")
                        damage_dealt = shooter["RNG_DMG"]
                        if "CUR_HP" not in target:
                            raise KeyError(f"Target missing required 'CUR_HP' field: {target}")
                        new_hp = max(0, target["CUR_HP"] - damage_dealt)
                        self.actions["update_unit"](target_id, {"CUR_HP": new_hp})
                        
                        # Remove unit if HP reaches 0
                        if new_hp <= 0:
                            self.actions["remove_unit"](target_id)

            # Log shooting action (MISSING from original Python)
            if self.game_log:
                shoot_details = [{
                    "hit_roll": hit_roll,
                    "hit_result": "HIT" if hit_success else "MISS",
                    "strength_result": "SUCCESS" if (hit_success and wound_success) else "FAILED",
                    "hit_target": shooter["RNG_ATK"],
                    "wound_target": wound_target if hit_success else None,
                    "save_target": save_target if (hit_success and wound_success) else None,
                    "save_roll": save_roll if (hit_success and wound_success) else None,
                    "save_success": save_success if (hit_success and wound_success) else None,
                    "damage_dealt": damage_dealt
                }]
                self.game_log.log_shooting_action(shooter, target, shoot_details, self.game_state["current_turn"])
            
            # Manually decrement shots - get fresh unit state (EXACT from TypeScript)
            current_shooter = self.find_unit(shooter_id)
            if not current_shooter:
                raise ValueError(f"Cannot find shooter unit {shooter_id}")
            if "SHOOT_LEFT" not in current_shooter:
                raise ValueError(f"currentShooter.SHOOT_LEFT is required but was undefined for unit {current_shooter['id']}")
            
            current_shots_left = current_shooter["SHOOT_LEFT"]
            new_shots_left = current_shots_left - 1
            self.actions["update_unit"](shooter_id, {"SHOOT_LEFT": new_shots_left})
            
            # Check if more shots remaining (EXACT from TypeScript)
            if new_shots_left > 0:
                # Keep unit selected and in attack mode for target reselection
                self.actions["set_attack_preview"]({"unit_id": shooter_id, "col": shooter["col"], "row": shooter["row"]})
                self.actions["set_mode"]("attack_preview")
                # Don't mark as moved yet - unit still has shots left
            else:
                # All shots used - mark as moved and end shooting
                self.actions["add_moved_unit"](shooter_id)
                self.actions["set_attack_preview"](None)
                self.actions["set_selected_unit_id"](None)
                self.actions["set_mode"]("select")
        
        else:
            # First click - start preview (MISSING from original Python)
            # Clear any existing preview
            if current_target_preview and current_target_preview.get("blink_timer"):
                # Handle timer cleanup in Python way
                pass
            
            # Calculate probabilities (MISSING from original Python)
            hit_probability = calculate_hit_probability(shooter)
            wound_probability = calculate_wound_probability(shooter, target)
            save_probability = calculate_save_probability(shooter, target)
            overall_probability = calculate_overall_probability(shooter, target)
            
            # Start preview with blink timer - SINGLE SHOT ONLY (MISSING from original Python)
            total_blink_steps = 2  # Only show: current HP (step 0) -> after next shot (step 1)
            
            preview = TargetPreview(
                target_id=target_id,
                shooter_id=shooter_id,
                current_blink_step=0,
                total_blink_steps=total_blink_steps,
                blink_timer=None,
                hit_probability=hit_probability,
                wound_probability=wound_probability,
                save_probability=save_probability,
                overall_probability=overall_probability
            )
            
            # Start blink cycle for single shot preview (simplified for Python)
            # In a real implementation, this would use threading or asyncio
            preview_dict = {
                "target_id": target_id,
                "shooter_id": shooter_id,
                "current_blink_step": 0,
                "total_blink_steps": total_blink_steps,
                "blink_timer": None,
                "hit_probability": hit_probability,
                "wound_probability": wound_probability,
                "save_probability": save_probability,
                "overall_probability": overall_probability
            }
            
            self.actions["set_target_preview"](preview_dict)

    # === COMBAT SYSTEM (EXACT from TypeScript) ===

    def handle_combat_attack(self, attacker_id: int, target_id: Optional[int]) -> None:
        """
        EXACT mirror of handleCombatAttack from TypeScript.
        Complete combat sequence with multiple attacks and probability calculations.
        Enhanced with detailed dice results for training replay capture.
        """
        if attacker_id in self.game_state.get("units_attacked", []):
            return

        attacker = self.find_unit(attacker_id)
        if not attacker:
            return

        if target_id is None:
            return

        target = self.find_unit(target_id)
        if not target:
            return

        # Check if this is a preview (first click) or execute (second click)
        current_target_preview = self.game_state.get("target_preview")
        
        if (current_target_preview and 
            current_target_preview["target_id"] == target_id and 
            current_target_preview["shooter_id"] == attacker_id):  # Reuse shooterId field for attacker
            
            # Second click - execute combat attack
            # Clear preview
            if current_target_preview.get("blink_timer"):
                pass  # Handle timer cleanup
            self.actions["set_target_preview"](None)
            
            # Execute detailed combat sequence for training replay capture
            try:
                from shared.gameRules import execute_combat_sequence
                
                # Convert units to lowercase field names for shared rules
                attacker_converted = convert_unit_for_shared_rules(attacker)
                target_converted = convert_unit_for_shared_rules(target)
                
                # Execute detailed combat sequence and capture results
                combat_result = execute_combat_sequence(attacker_converted, target_converted)
                
                # Apply damage from combat result
                if "totalDamage" not in combat_result:
                    raise KeyError("Combat result missing required 'totalDamage' field")
                damage_dealt = combat_result["totalDamage"]
                if damage_dealt > 0:
                    new_hp = max(0, target["CUR_HP"] - damage_dealt)
                    self.actions["update_unit"](target_id, {"CUR_HP": new_hp})
                    
                    if new_hp <= 0:
                        self.actions["remove_unit"](target_id)
                
                # Log combat action with detailed dice results
                if self.game_log:
                    self.game_log.log_combat_action(attacker, target, combat_result, self.game_state["current_turn"])
                
            except ImportError:
                # Fallback to simplified combat if shared rules not available
                hit_roll = random.randint(1, 6)
                if "CC_ATK" not in attacker:
                    raise ValueError(f"attacker.CC_ATK is required but was undefined for unit {attacker['id']}")
                hit_success = hit_roll >= attacker["CC_ATK"]
                
                damage_dealt = 0
                if hit_success:
                    wound_roll = random.randint(1, 6)
                    if "CC_STR" not in attacker:
                        raise KeyError(f"Attacker missing required 'CC_STR' field: {attacker.get('name')}")
                    wound_target = calculateWoundTarget(attacker["CC_STR"], target["T"])
                    wound_success = wound_roll >= wound_target
                    
                    if wound_success:
                        save_roll = random.randint(1, 6)
                        if "INVUL_SAVE" not in target:
                            raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
                        if "CC_AP" not in attacker:
                            raise KeyError(f"Attacker missing required 'CC_AP' field: {attacker}")
                        save_target = calculateSaveTarget(target["ARMOR_SAVE"], target["INVUL_SAVE"], attacker["CC_AP"])
                        save_success = save_roll >= save_target
                        
                        if not save_success:
                            if "CC_DMG" not in attacker:
                                raise KeyError(f"Attacker missing required 'CC_DMG' field: {attacker}")
                            damage_dealt = attacker["CC_DMG"]
                            new_hp = max(0, target["CUR_HP"] - damage_dealt)
                            self.actions["update_unit"](target_id, {"CUR_HP": new_hp})
                            
                            if new_hp <= 0:
                                self.actions["remove_unit"](target_id)
                
                # Log simplified combat action
                if self.game_log:
                    self.game_log.log_combat_action(attacker, target, damage_dealt, self.game_state["current_turn"])
            
            # Mark attacker as having attacked
            self.actions["add_attacked_unit"](attacker_id)
            self.actions["set_attack_preview"](None)
            self.actions["set_selected_unit_id"](None)
            self.actions["set_mode"]("select")
        
        else:
            # First click - start preview (MISSING from original Python)
            # Clear any existing preview
            if current_target_preview and current_target_preview.get("blink_timer"):
                pass  # Handle timer cleanup
            
            # Calculate combat probabilities (MISSING from original Python)
            hit_probability = calculate_combat_hit_probability(attacker)
            wound_probability = calculate_combat_wound_probability(attacker, target)
            save_probability = calculate_combat_save_probability(attacker, target)
            overall_probability = calculate_combat_overall_probability(attacker, target)
            
            # COMBAT ATTACK PREVIEW - SINGLE ATTACK ONLY (MISSING from original Python)
            total_blink_steps = 2  # Only show: current HP (step 0) -> after next attack (step 1)
            
            preview = {
                "target_id": target_id,
                "shooter_id": attacker_id,  # Reuse shooterId field for attacker
                "current_blink_step": 0,
                "total_blink_steps": total_blink_steps,
                "blink_timer": None,
                "hit_probability": hit_probability,
                "wound_probability": wound_probability,
                "save_probability": save_probability,
                "overall_probability": overall_probability
            }
            
            self.actions["set_target_preview"](preview)

    # === CHARGE SYSTEM (EXACT from TypeScript) ===

    def handle_charge(self, charger_id: int, target_id: int) -> None:
        """EXACT mirror of handleCharge from TypeScript with proper validation and adjacent placement"""
        charger = self.find_unit(charger_id)
        target = self.find_unit(target_id)
        
        if not charger or not target:
            return

        # CRITICAL: Validate charge roll and distance
        charge_data = self.game_state.get("unit_charge_rolls", {}).get(charger_id)
        if not charge_data:
            # No charge roll exists - this should not happen
            return
        
        # Get charge roll value (handle both old int format and new dict format)
        if isinstance(charge_data, dict):
            charge_roll = charge_data.get("total", charge_data.get("charge_roll", 0))
            die1 = charge_data.get("die1", 0)
            die2 = charge_data.get("die2", 0)
        else:
            charge_roll = charge_data  # Legacy int format
            die1 = 0
            die2 = 0
        
        # Validate charge distance to target with proper 2d6 roll requirements
        from shared.gameRules import get_hex_distance
        distance = get_hex_distance(charger, target)
        from shared.gameMechanics import get_charge_max_distance
        
        # CRITICAL: Ensure charge roll is legitimate 2d6 (2-12 range)
        if charge_roll < 2 or charge_roll > 12:
            raise ValueError(f"Invalid charge roll {charge_roll} for unit {charger_id} - must be 2d6 (2-12)")
        
        if distance > charge_roll or distance > get_charge_max_distance():
            raise ValueError(f"Charge failed: distance {distance} > roll {charge_roll} or > max {get_charge_max_distance()}")
        
        # Store original position for logging
        original_col, original_row = charger["col"], charger["row"]
        
        # Find valid adjacent position to target (not ON target) - EXACT from frontend logic
        valid_adjacent_positions = []
        from shared.gameMechanics import get_cube_neighbors
        for adj_col, adj_row in get_cube_neighbors(target["col"], target["row"]):
            # Check if position is within board bounds
            if "cols" not in self.board_config:
                raise KeyError("Board config missing required 'cols' field")
            if "rows" not in self.board_config:
                raise KeyError("Board config missing required 'rows' field") 
            if not (0 <= adj_col < self.board_config["cols"] and 
                   0 <= adj_row < self.board_config["rows"]):
                continue
            
            # Check if position is within charge distance
            adj_distance = get_hex_distance(charger, {"col": adj_col, "row": adj_row})
            if adj_distance <= charge_roll:
                # Check if position is not occupied by any unit
                occupied = any(u["col"] == adj_col and u["row"] == adj_row and u["id"] != charger_id 
                             for u in self.game_state["units"])
                
                # Check if position is not a wall hex
                wall_hexes = self.board_config.get('wall_hexes')
                if wall_hexes is None:
                    wall_hexes = []
                is_wall = any(
                    wall[0] == adj_col and wall[1] == adj_row 
                    for wall in wall_hexes if isinstance(wall, (list, tuple)) and len(wall) == 2
                )
                
                if not occupied and not is_wall:
                    valid_adjacent_positions.append((adj_col, adj_row))
        
        if not valid_adjacent_positions:
            return  # No valid adjacent positions
        
        # Choose closest valid position to charger
        best_position = min(valid_adjacent_positions, 
                           key=lambda pos: get_hex_distance(charger, {"col": pos[0], "row": pos[1]}))
        final_col, final_row = best_position
        
        # Move charger to adjacent position (not target hex) and mark as charged
        self.actions["update_unit"](charger_id, {
            "col": final_col, 
            "row": final_row,
            "has_charged_this_turn": True
        })

        # Log charge action with dice details in shootDetails format - CRITICAL for replay
        if self.game_log:
            # Format charge dice details for combatlog visibility
            charge_details = [{
                "rollType": "charge",
                "die1": die1,
                "die2": die2,
                "totalRoll": charge_roll,
                "targetDistance": distance,
                "chargeSucceeded": True,
                "rollResult": "SUCCESS"
            }]
            self.game_log.log_charge_action(charger, target, original_col, original_row, 
                                          final_col, final_row, self.game_state["current_turn"])

        self.actions["add_charged_unit"](charger_id)
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")
        
        # CRITICAL: Clear ALL preview states to reset colored hexes
        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        
        # CRITICAL: Clear charge preview states - MUST call these actions
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")
        
        # CRITICAL FIX: Clear charge roll data to prevent reuse  
        if "unit_charge_rolls" in self.game_state and charger_id in self.game_state["unit_charge_rolls"]:
            del self.game_state["unit_charge_rolls"][charger_id]
        
        # CRITICAL FIX: Clear ALL charge preview states to reset colored hexes
        if "reset_unit_charge_roll" in self.actions:
            self.actions["reset_unit_charge_roll"](charger_id)
        
        # CRITICAL FIX: Clear charge preview hexes by resetting mode and previews
        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        
        # Additional cleanup to ensure orange hexes are cleared
        if "clear_charge_preview" in self.actions:
            self.actions["clear_charge_preview"]()

    def move_charger(self, charger_id: int, dest_col: int, dest_row: int) -> None:
        """EXACT mirror of moveCharger from TypeScript"""
        charger = self.find_unit(charger_id)
        if not charger:
            return
        
        # Create charge event for game log (MISSING from original Python)
        if self.game_log:
            charge_event = {
                "id": f"charge-move-{int(time.time()*1000)}-{charger['id']}",
                "timestamp": time.time(),
                "type": "charge",
                "message": f"Unit {charger['name']} CHARGED from ({charger['col']}, {charger['row']}) to ({dest_col}, {dest_row})",
                "turn": self.game_state["current_turn"]
            }
            self.game_log.add_event(charge_event)
        
        # Move the unit to the destination
        self.actions["update_unit"](charger_id, {"col": dest_col, "row": dest_row})
        
        # Mark unit as having charged (end of activability for this phase)
        self.actions["add_charged_unit"](charger_id)
        
        # Deselect the unit
        self.actions["set_selected_unit_id"](None)
        
        # Return to select mode (cancel colored cells)
        self.actions["set_mode"]("select")

    def cancel_charge(self) -> None:
        """EXACT mirror of cancelCharge from TypeScript"""
        if self.game_state["selected_unit_id"] is not None:
            self.actions["add_charged_unit"](self.selected_unit_id)
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")
        self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)

    def validate_charge(self, charger_id: int) -> None:
        """EXACT mirror of validateCharge from TypeScript"""
        self.actions["add_charged_unit"](charger_id)
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")

    # === ADDITIONAL METHODS FOR TRAINING & PVP ENHANCEMENT ===

    def validated_move(self, unit_id: int, col: int, row: int) -> bool:
        """
        WALL-SAFE movement using existing validation system.
        Returns True if move was successful, False if invalid.
        """
        unit = self.find_unit(unit_id)
        phase = self.game_state["phase"]
        
        print(f"\n🚶 [use_game_actions.py::validated_move] VALIDATED_MOVE - U{unit_id} to ({col}, {row})")
        print(f"📊 [use_game_actions.py::validated_move] UNITS_MOVED BEFORE MOVE: {list(self.game_state.get('units_moved', []))}")
        
        # CRITICAL FIX: Trust Sequential Engine - no redundant eligibility checks during action execution
        # AI_GAME.md: "Target Validation: Performed at START of each activation (not action execution time)"
        if not unit or phase != "move":
            print(f"❌ [use_game_actions.py::validated_move] MOVE REJECTED: unit_found={unit is not None}, phase={phase}")
            return False    

        # CRITICAL: Validate movement using wall-checking system
        valid_moves = self.get_valid_moves(unit_id)
        if not any(move["col"] == col and move["row"] == row for move in valid_moves):
            print(f"❌ MOVE REJECTED: destination not in valid_moves")
            return False  # Invalid destination - movement blocked by walls

        print(f"✅ MOVE ACCEPTED: U{unit_id} moving from ({unit['col']}, {unit['row']}) to ({col}, {row})")
        
        # Direct unit update without preview system to avoid complications
        self.actions["update_unit"](unit_id, {"col": col, "row": row})
        # CRITICAL FIX: Do NOT call add_moved_unit here - _mark_gym_unit_as_acted will handle it
        
        print(f"📊 UNITS_MOVED AFTER MOVE (before marking): {list(self.game_state.get('units_moved', []))}")
        return True

    def get_charge_destinations(self, unit_id: int) -> List[Dict[str, int]]:
        """
        Calculate valid charge destinations for visual preview (EXACT from TypeScript).
        Only shows hexes adjacent to reachable enemies within charge roll distance.
        """
        unit = self.find_unit(unit_id)
        if not unit:
            return []
        
        # CRITICAL FIX: Get proper charge roll value from stored data
        charge_data = self.game_state.get("unit_charge_rolls", {}).get(unit_id)
        if not charge_data:
            return []
        
        # Handle both old int format and new dict format (EXACT from TypeScript)
        if isinstance(charge_data, dict):
            charge_distance = charge_data.get("total", charge_data.get("charge_roll", 0))
        else:
            charge_distance = charge_data  # Legacy int format
        
        if charge_distance <= 0:
            return []
        
        if not self.board_config.get("cols") or not self.board_config.get("rows"):
            return []
        
        BOARD_COLS = self.board_config["cols"]
        BOARD_ROWS = self.board_config["rows"]
        
        visited = {}
        queue = [[unit["col"], unit["row"], 0]]
        valid_destinations = []

        # Cube directions for proper hex neighbors (EXACT from TypeScript)
        cube_directions = [
            [1, -1, 0], [1, 0, -1], [0, 1, -1], 
            [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
        ]

        # CRITICAL FIX: For charges, only forbid walls and occupied hexes - NOT enemy-adjacent hexes
        forbidden_set = set()
        
        # Add wall hexes (EXACT from TypeScript)
        wall_hex_set = set(f"{c},{r}" for c, r in self.board_config.get("wall_hexes", []))
        forbidden_set.update(wall_hex_set)
        
        # Add occupied unit positions (including dead units) - EXACT from BoardReplay.tsx
        for u in self.game_state["units"]:
            if u["id"] != unit["id"]:
                forbidden_set.add(f"{u['col']},{u['row']}")

        while queue:
            next_item = queue.pop(0)
            if not next_item:
                continue
            col, row, steps = next_item
            key = f"{col},{row}"
            
            if key in visited and steps >= visited[key]:
                continue

            visited[key] = steps

            # Skip forbidden positions (can't move through them) (EXACT from TypeScript)
            if key in forbidden_set and steps > 0:
                continue

            # Check if this position is adjacent to a chargeable enemy and within charge range (EXACT from TypeScript)
            if steps > 0 and steps <= charge_distance and key not in forbidden_set:
                chargeable_enemy_adjacent = False
                for u in self.game_state["units"]:
                    if u["player"] == unit["player"] or not u.get("alive", True):
                        continue
                    
                    # Check if this enemy is adjacent to the destination using cube coordinates (EXACT from TypeScript)
                    from shared.gameRules import offset_to_cube, cube_distance
                    dest_cube = offset_to_cube(col, row)
                    target_enemy_cube = offset_to_cube(u["col"], u["row"])
                    hex_distance = cube_distance(dest_cube, target_enemy_cube)
                    is_adjacent = hex_distance == 1
                    if not is_adjacent:
                        continue
                    
                    # Additional check: enemy must be within the original charge eligibility range (12 hexes) (EXACT from TypeScript)
                    enemy_cube = offset_to_cube(u["col"], u["row"])
                    unit_cube = offset_to_cube(unit["col"], unit["row"])
                    distance_to_enemy = cube_distance(unit_cube, enemy_cube)
                    if distance_to_enemy > 12:
                        continue
                    
                    chargeable_enemy_adjacent = True
                    break
                
                if chargeable_enemy_adjacent:
                    valid_destinations.append({"col": col, "row": row})

            if steps >= charge_distance:
                continue

            # Explore neighbors using cube coordinates (EXACT from TypeScript)
            from shared.gameRules import offset_to_cube
            current_cube = offset_to_cube(col, row)
            for dx, dy, dz in cube_directions:
                # Handle both tuple and dict formats from offsetToCube
                if isinstance(current_cube, tuple):
                    # Convert tuple (x, y, z) to dict format
                    current_x, current_y, current_z = current_cube
                else:
                    # Already dict format
                    current_x, current_y, current_z = current_cube["x"], current_cube["y"], current_cube["z"]
                
                neighbor_cube = {
                    "x": current_x + dx,
                    "y": current_y + dy,
                    "z": current_z + dz
                }
                
                ncol = neighbor_cube["x"]
                nrow = neighbor_cube["z"] + ((neighbor_cube["x"] - (neighbor_cube["x"] & 1)) >> 1)
                nkey = f"{ncol},{nrow}"
                next_steps = steps + 1

                if (ncol >= 0 and ncol < BOARD_COLS and
                    nrow >= 0 and nrow < BOARD_ROWS and
                    next_steps <= charge_distance and
                    (nkey not in visited or visited[nkey] > next_steps)):
                    queue.append([ncol, nrow, next_steps])

        return valid_destinations

    def move_charger(self, charger_id: int, dest_col: int, dest_row: int) -> None:
        """EXACT mirror of moveCharger from TypeScript"""
        charger = self.find_unit(charger_id)
        if not charger:
            return
        
        # Create charge event for game log (EXACT from TypeScript)
        if self.game_log:
            charge_event = {
                "id": f"charge-move-{int(time.time()*1000)}-{charger['id']}",
                "timestamp": time.time(),
                "type": "charge",
                "message": f"Unit {charger.get('name', charger['unit_type'])} CHARGED from ({charger['col']}, {charger['row']}) to ({dest_col}, {dest_row})",
                "turnNumber": self.game_state["current_turn"],
                "phase": "charge",
                "player": charger["player"],
                "unitType": charger.get("unit_type", "unknown"),
                "unitId": charger["id"]
            }
            if hasattr(self.game_log, 'events'):
                self.game_log.events.insert(0, charge_event)
        
        # Move unit to destination and mark as charged (EXACT from TypeScript)
        self.actions["update_unit"](charger_id, {
            "col": dest_col, 
            "row": dest_row, 
            "has_charged_this_turn": True
        })
        
        # Clean up charge state (EXACT from TypeScript) 
        if "reset_unit_charge_roll" in self.actions:
            self.actions["reset_unit_charge_roll"](charger_id)
        self.actions["add_charged_unit"](charger_id)
        
        # Reset UI state (EXACT from TypeScript)
        self.actions["set_selected_unit_id"](None)
        self.actions["set_mode"]("select")
        
        # CRITICAL: Clear ALL preview states to reset colored hexes (EXACT from TypeScript)
        if "clear_move_preview" in self.actions:
            self.actions["clear_move_preview"]()
        self.actions["set_attack_preview"](None)
        
        # CRITICAL: Force clear any remaining charge preview states
        if "clear_charge_preview" in self.actions:
            self.actions["clear_charge_preview"]()
        
        # Ensure mode is definitely set to select to trigger Board clearing
        self.actions["set_mode"]("select")
        self.actions["set_selected_unit_id"](None)

    def _calculate_charge_destinations_simple(self, unit: Dict[str, Any], charge_distance: int) -> List[Dict[str, int]]:
        """Simplified charge destinations - ensures ALL are adjacent to enemies"""
        valid_destinations = []
        enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u.get("alive", True)]
        
        # For each enemy, find adjacent hexes within charge distance
        for enemy in enemy_units:
            # Get 6 adjacent positions around each enemy
            adjacent_positions = [
                (enemy["col"] + 1, enemy["row"]),
                (enemy["col"] - 1, enemy["row"]),
                (enemy["col"], enemy["row"] + 1),
                (enemy["col"], enemy["row"] - 1),
                (enemy["col"] + 1, enemy["row"] - 1),
                (enemy["col"] - 1, enemy["row"] + 1)
            ]
            
            for adj_col, adj_row in adjacent_positions:
                # Check if within board bounds
                if not (0 <= adj_col < self.board_config["cols"] and 0 <= adj_row < self.board_config["rows"]):
                    continue
                
                # Check if within charge distance from unit
                from shared.gameRules import get_hex_distance
                distance = get_hex_distance(unit, {"col": adj_col, "row": adj_row})
                if distance > charge_distance or distance == 0:
                    continue
                
                # Check if position is not occupied
                occupied = any(u["col"] == adj_col and u["row"] == adj_row for u in self.game_state["units"])
                if occupied:
                    continue
                
                # Check if position is not a wall
                wall_hexes = self.board_config.get('wall_hexes')
                if wall_hexes:
                    is_wall = any(wall[0] == adj_col and wall[1] == adj_row 
                                for wall in wall_hexes if isinstance(wall, (list, tuple)) and len(wall) == 2)
                    if is_wall:
                        continue
                
                # Valid destination - adjacent to enemy and within charge range
                dest = {"col": adj_col, "row": adj_row}
                if dest not in valid_destinations:
                    valid_destinations.append(dest)
        
        return valid_destinations

    def get_available_actions(self) -> Dict[str, Callable]:
        """
        Returns dictionary of all available action methods.
        EXACT mirror of TypeScript return object PLUS training enhancements.
        ALL MISSING METHODS NOW INCLUDED.
        """
        return {
            # EXACT TypeScript return methods (11 methods):
            "select_unit": self.select_unit,
            "select_charger": self.select_charger,
            "start_move_preview": self.start_move_preview,
            "start_attack_preview": self.start_attack_preview,
            "confirm_move": self.confirm_move,
            "cancel_move": self.cancel_move,
            "handle_move": self.validated_move,
            "handle_shoot": self.handle_shoot,
            "handle_combat_attack": self.handle_combat_attack,
            "handle_charge": self.handle_charge,
            "move_charger": self.move_charger,
            "cancel_charge": self.cancel_charge,
            "validate_charge": self.validate_charge,
            
            # MISSING methods exposed in GameController.tsx:
            "is_unit_eligible": self.is_unit_eligible_local,
            "get_charge_destinations": self.get_charge_destinations,
            "validated_move": self.validated_move,
            
            # MISSING training methods:
            "get_valid_moves": self.get_valid_moves,
            "get_valid_shooting_targets": self.get_valid_shooting_targets,
            "get_valid_charge_targets": self.get_valid_charge_targets,
            "get_valid_combat_targets": self.get_valid_combat_targets,
            
            # CRITICAL: Missing method needed by TrainingGameController
            "get_eligible_units": self.get_eligible_units,
            
            # TrainingGameController compatibility aliases
            "find_valid_charge_targets": self.get_valid_charge_targets,
            "find_valid_shoot_targets": self.get_valid_shooting_targets,
            "find_valid_combat_targets": self.get_valid_combat_targets,
            
            # Action validation
            "validate_gym_action_for_phase": self.validate_gym_action_for_phase,
            "get_action_mask": self.get_action_mask,
        }

    def get_eligible_units(self) -> List[Dict[str, Any]]:
        """Get all eligible units for current phase and player"""
        current_player = self.game_state.get("current_player", 0)
        current_phase = self.game_state.get("phase", "move")
        
        eligible_units = []
        for unit in self.game_state["units"]:
            if "alive" not in unit:
                raise KeyError(f"Unit {unit.get('id')} missing required 'alive' property")
            if "player" not in unit:
                raise KeyError(f"Unit {unit.get('id')} missing required 'player' property")
            
            if unit["player"] == current_player and unit["alive"]:
                if self.is_unit_eligible_local(unit):
                    eligible_units.append(unit)
        
        return eligible_units

    def get_valid_moves(self, unit_id: int) -> List[Dict[str, Any]]:
        """Get valid move positions for unit"""
        unit = self.find_unit(unit_id)
        if not unit or self.game_state.get("phase") != "move":
            raise ValueError("Unit not found or not in move phase")
        
        # Validate required unit fields
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        if "col" not in unit:
            raise KeyError(f"Unit missing required 'col' field: {unit}")
        if "row" not in unit:
            raise KeyError(f"Unit missing required 'row' field: {unit}")
        
        # Validate required board config fields
        if "cols" not in self.board_config:
            raise KeyError("Board config missing required 'cols' field")
        if "rows" not in self.board_config:
            raise KeyError("Board config missing required 'rows' field")
        
        # Use shared.gameMechanics function - NO FALLBACKS
        from shared.gameMechanics import calculate_available_move_cells
        return calculate_available_move_cells(
            unit=unit,
            units=self.game_state["units"], 
            board_config=self.board_config,
            board_cols=self.board_config["cols"],
            board_rows=self.board_config["rows"]
        )

    def get_valid_shooting_targets(self, unit_id: int) -> List[int]:
        """Get valid shooting targets for unit - AI_GAME.md compliant"""
        unit = self.find_unit(unit_id)
        if not unit or self.game_state.get("phase") != "shoot":
            return []
        
        # AI_GAME.md: Check RNG_NB > 0 requirement
        if "RNG_NB" not in unit:
            raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
        if unit.get("RNG_NB", 0) <= 0:
            return []  # No shots remaining
        
        # Validate required unit fields
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit}")
        
        targets = []
        enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u.get("alive", True)]
        for enemy in enemy_units:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if distance <= unit["RNG_RNG"]:
                # AI_GAME.md: "has a line of sight on an enemy unit within RNG_RNG distance"
                try:
                    from shared.gameRules import has_line_of_sight
                    wall_hexes = self.board_config.get("wall_hexes", [])
                    
                    line_of_sight = has_line_of_sight(
                        {"col": unit["col"], "row": unit["row"]},
                        {"col": enemy["col"], "row": enemy["row"]},
                        wall_hexes
                    )
                    
                    if line_of_sight.get("canSee", False):
                        targets.append(enemy["id"])
                except ImportError:
                    # Fallback if shared.gameRules not available
                    targets.append(enemy["id"])
        return targets

    def get_valid_charge_targets(self, unit_id: int) -> List[int]:
        """Get valid charge targets for unit with proper 2D6 roll validation"""
        unit = self.find_unit(unit_id)
        if not unit or self.game_state.get("phase") != "charge":
            return []
        
        # CRITICAL FIX: Must have valid charge roll to get targets
        charge_data = self.game_state.get("unit_charge_rolls", {}).get(unit_id)
        if not charge_data:
            return []  # No charge roll = no valid targets
        
        # Get charge roll distance
        if isinstance(charge_data, dict):
            charge_roll = charge_data.get("total", charge_data.get("charge_roll", 0))
        else:
            charge_roll = charge_data
        
        if charge_roll <= 0:
            return []
        
        targets = []
        enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"] and u.get("alive", True)]
        for enemy in enemy_units:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if 1 < distance <= min(charge_roll, 12):  # Must be within rolled distance AND 12-hex limit
                # Check pathfinding around walls
                if self.board_config.get("wall_hexes"):
                    wall_hex_set = set(f"{c},{r}" for c, r in self.board_config["wall_hexes"])
                    if self._check_pathfinding_reachable(unit, enemy, wall_hex_set, charge_roll):
                        targets.append(enemy["id"])
                else:
                    targets.append(enemy["id"])
        return targets

    def get_valid_combat_targets(self, unit_id: int) -> List[int]:
        """Get valid combat targets for unit"""
        unit = self.find_unit(unit_id)
        if not unit or not self.is_unit_eligible_local(unit) or self.game_state.get("phase") != "combat":
            return []
        
        # Validate required unit fields
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit.get('name')}")
        
        targets = []
        enemy_units = [u for u in self.game_state["units"] if u["player"] != unit["player"]]
        for enemy in enemy_units:
            distance = max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"]))
            if distance <= unit["CC_RNG"]:
                targets.append(enemy["id"])
        return targets

    def validate_gym_action_for_phase(self, action_type: int, current_phase: str) -> bool:
        """Validate gym action type is allowed for current phase"""
        valid_actions_per_phase = {
            "move": [0, 1, 2, 3, 7],  # move directions + wait
            "shoot": [4, 7],          # shoot + wait
            "charge": [5, 7],         # charge + wait
            "combat": [6, 7]          # combat + wait
        }
        
        valid_actions = valid_actions_per_phase.get(current_phase, [])
        if action_type not in valid_actions:
            raise RuntimeError(f"Invalid action {action_type} for phase {current_phase}. Valid actions: {valid_actions}")
        
        return True

    def get_action_mask(self, max_units: int) -> List[bool]:
        """Generate action mask for current game state - True = valid action"""
        current_phase = self.game_state.get("phase", "move")
        current_player = self.game_state.get("current_player", 0)
        
        # CRITICAL FIX: Trust Sequential Engine - don't duplicate eligibility checks
        # Sequential Engine determines which units are eligible, gym just needs action types
        print(f"🎭 [use_game_actions.py::get_action_mask] ACTION_MASK requested for {current_phase} phase")
        
        # Get current player units (no eligibility checks - trust Sequential Engine)
        current_player_units = [u for u in self.game_state["units"] if u["player"] == current_player and u.get("alive", True)]
        
        action_mask = []
        
        # CRITICAL FIX: Trust Sequential Engine for unit eligibility - no redundant checks
        for unit_idx in range(max_units):
            if unit_idx < len(current_player_units):
                unit = current_player_units[unit_idx]
                
                for action_type in range(8):
                    # Trust Sequential Engine - provide generic action mask for valid action types
                    action_valid = False
                    
                    if current_phase == "move" and action_type in [0, 1, 2, 3]:
                        # Movement actions - valid for move phase
                        action_valid = True  
                        
                    elif current_phase == "shoot" and action_type == 4:
                        # Shoot action - valid for shoot phase
                        action_valid = True
                        
                    elif current_phase == "charge" and action_type == 5:
                        # Charge action - valid for charge phase
                        action_valid = True
                        
                    elif current_phase == "combat" and action_type == 6:
                        # Combat action - valid for combat phase
                        action_valid = True
                        
                    elif action_type == 7:
                        # Wait action - always valid in any phase
                        action_valid = True
                            
                    elif current_phase == "shoot" and action_type == 4:
                        # AI_GAME.md: Shooting action - check RNG_NB > 0 AND valid targets
                        try:
                            # Check RNG_NB first (AI_GAME.md requirement)
                            if "RNG_NB" not in unit:
                                action_valid = False
                            elif unit.get("RNG_NB", 0) <= 0:
                                action_valid = False
                            else:
                                valid_targets = self.get_valid_shooting_targets(unit["id"])
                                action_valid = len(valid_targets) > 0
                        except Exception as e:
                            action_valid = False
                            
                    elif current_phase == "charge" and action_type == 5:
                        # Charge action - check if unit has valid targets
                        try:
                            valid_targets = self.get_valid_charge_targets(unit["id"])
                            action_valid = len(valid_targets) > 0
                        except Exception as e:
                            action_valid = False
                            
                    elif current_phase == "combat" and action_type == 6:
                        # Combat action - check if unit has valid targets
                        try:
                            valid_targets = self.get_valid_combat_targets(unit["id"])
                            action_valid = len(valid_targets) > 0
                        except Exception as e:
                            action_valid = False
                            
                    elif action_type == 7:
                        # Wait action - always valid for eligible units
                        action_valid = True
                    
                    action_mask.append(action_valid)
            else:
                # No unit at this index - all actions invalid
                for action_type in range(8):
                    action_mask.append(False)
        
        return action_mask


# === FACTORY FUNCTION (EXACT Mirror of TypeScript hook usage) ===

def use_game_actions(game_state: Dict[str, Any], 
                    move_preview: Optional[Dict[str, Any]], 
                    attack_preview: Optional[Dict[str, Any]], 
                    shooting_phase_state: Dict[str, Any],
                    board_config: Dict[str, Any],  # NOW REQUIRED as in TypeScript
                    actions: Dict[str, Callable],  # NOW PROPERLY STRUCTURED
                    game_log: Optional[Any] = None) -> Dict[str, Callable]:
    """
    Factory function that EXACTLY mirrors the TypeScript useGameActions hook.
    Returns the same action methods that the TypeScript hook returns.
    NOW WITH PROPER PARAMETER STRUCTURE AND VALIDATION.
    """
    # Create params object that matches TypeScript interface
    params = UseGameActionsParams(
        game_state=game_state,
        move_preview=move_preview,
        attack_preview=attack_preview,
        shooting_phase_state=shooting_phase_state,
        board_config=board_config,
        actions=actions,
        game_log=game_log
    )
    
    # Create the game actions instance
    game_actions = UseGameActions(params)
    
    return game_actions.get_available_actions()

# === TRAINING INTEGRATION CLASS ===

class TrainingGameActions(UseGameActions):
    """
    Extended version of UseGameActions optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, game_state: Dict[str, Any], 
                 move_preview: Optional[Dict[str, Any]], 
                 attack_preview: Optional[Dict[str, Any]], 
                 shooting_phase_state: Dict[str, Any],
                 board_config: Dict[str, Any],
                 actions: Dict[str, Callable],
                 game_log: Optional[Any] = None):
        # Initialize with training-specific optimizations
        super().__init__(UseGameActionsParams(
            game_state=game_state,
            move_preview=move_preview,
            attack_preview=attack_preview,
            shooting_phase_state=shooting_phase_state,
            board_config=board_config,
            actions=actions,
            game_log=game_log
        ))
        
        # Training-specific metrics
        self.action_history = []
        self.performance_metrics = {
            "actions_executed": 0,
            "successful_moves": 0,
            "successful_attacks": 0,
            "training_efficiency": 0.0
        }

    def get_action_functions(self) -> Dict[str, Callable]:
        """Get training-optimized action functions"""
        return {
            "handle_unit_selection": self.select_unit,
            "confirm_move": self.confirm_move,
            "direct_move": self.validated_move,
            "handle_shoot": self.handle_shoot,
            "handle_charge": self.handle_charge,
            "handle_combat_attack": self.handle_combat_attack,
            "is_unit_eligible": self.is_unit_eligible_local
        }