#!/usr/bin/env python3
"""
game_state.py - Game state initialization and management
"""

from typing import Dict, List, Any, Optional, Tuple
import json
from shared.data_validation import require_key
from engine.combat_utils import normalize_coordinates, get_unit_coordinates, resolve_dice_value
from engine.phase_handlers.shared_utils import is_unit_alive

class GameStateManager:
    """Manages game state."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.unit_registry = unit_registry
    
    # ============================================================================
    # UNIT MANAGEMENT
    # ============================================================================
    
    def initialize_units(self, game_state: Dict[str, Any]):
        """Initialize units with UPPERCASE field validation."""
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field")
        unit_configs = self.config["units"]
        
        for unit_config in unit_configs:
            unit = self.create_unit(unit_config)
            self.validate_uppercase_fields(unit)
            game_state["units"].append(unit)
    
    def create_unit(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create unit with AI_TURN.md compliant fields."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
        rng_weapons = require_key(config, "RNG_WEAPONS")
        cc_weapons = require_key(config, "CC_WEAPONS")
        
        if not rng_weapons and not cc_weapons:
            raise ValueError(f"Unit {config.get('id', 'unknown')} must have at least RNG_WEAPONS or CC_WEAPONS")
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
        selected_rng_weapon_index = 0 if rng_weapons else None
        selected_cc_weapon_index = 0 if cc_weapons else None
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
        shoot_left = 0
        if rng_weapons and selected_rng_weapon_index is not None:
            selected_weapon = rng_weapons[selected_rng_weapon_index]
            shoot_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_shoot_left",
            )
        
        attack_left = 0
        if cc_weapons and selected_cc_weapon_index is not None:
            selected_weapon = cc_weapons[selected_cc_weapon_index]
            attack_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_attack_left",
            )
        
        unit_rules = config["UNIT_RULES"] if "UNIT_RULES" in config else []
        return {
            # Identity
            "id": config["id"],
            "player": config["player"],
            "unitType": config["unitType"],  # NO DEFAULTS - must be provided
            
            # Position
            "col": normalize_coordinates(config["col"], config["row"])[0],
            "row": normalize_coordinates(config["col"], config["row"])[1],
            
            # UPPERCASE STATS (AI_TURN.md requirement) - NO DEFAULTS
            "HP_CUR": config["HP_CUR"],
            "HP_MAX": config["HP_MAX"],
            "MOVE": config["MOVE"],
            "T": config["T"],
            "ARMOR_SAVE": config["ARMOR_SAVE"],
            "INVUL_SAVE": config["INVUL_SAVE"],
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
            "RNG_WEAPONS": rng_weapons,
            "CC_WEAPONS": cc_weapons,
            "selectedRngWeaponIndex": selected_rng_weapon_index,
            "selectedCcWeaponIndex": selected_cc_weapon_index,
            
            # Required stats - NO DEFAULTS
            "LD": config["LD"],
            "OC": config["OC"],
            "VALUE": config["VALUE"],
            "ICON": config["ICON"],
            "ICON_SCALE": config["ICON_SCALE"],
            "UNIT_RULES": unit_rules,
            
            # AI_TURN.md action tracking fields
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left
        }
    
    def validate_uppercase_fields(self, unit: Dict[str, Any]):
        """Validate unit uses UPPERCASE field naming convention."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons instead of individual weapon fields
        required_uppercase = {
            "HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
            "RNG_WEAPONS", "CC_WEAPONS",
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE", "UNIT_RULES",
            "SHOOT_LEFT", "ATTACK_LEFT"
        }
        
        for field in required_uppercase:
            if field not in unit:
                raise ValueError(f"Unit {unit['id']} missing required UPPERCASE field: {field}")
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        cc_weapons = require_key(unit, "CC_WEAPONS")
        if not rng_weapons and not cc_weapons:
            raise ValueError(f"Unit {unit['id']} must have at least RNG_WEAPONS or CC_WEAPONS")
    
    def load_units_from_scenario(self, scenario_file, unit_registry):
            """Load units from scenario file - NO FALLBACKS ALLOWED."""
            if not scenario_file:
                raise ValueError("scenario_file is required - no fallbacks allowed")
            if not unit_registry:
                raise ValueError("unit_registry is required - no fallbacks allowed")
            
            import json
            import os
            import random
            
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

            deployment_zone = None
            deployment_type = "fixed"
            if isinstance(scenario_data, dict):
                has_deployment_zone = "deployment_zone" in scenario_data
                has_deployment_type = "deployment_type" in scenario_data
                if has_deployment_zone or has_deployment_type:
                    if not has_deployment_zone or not has_deployment_type:
                        raise KeyError(
                            f"Scenario file {scenario_file} requires both 'deployment_zone' and 'deployment_type'"
                        )
                    deployment_zone = require_key(scenario_data, "deployment_zone")
                    deployment_type = require_key(scenario_data, "deployment_type")
                if deployment_type not in ("random", "fixed"):
                    raise ValueError(
                        f"Invalid deployment_type '{deployment_type}' in {scenario_file} (expected 'random' or 'fixed')"
                    )
            
            wall_hex_set = set()
            if isinstance(scenario_data, dict) and "wall_hexes" in scenario_data:
                wall_hexes = require_key(scenario_data, "wall_hexes")
                wall_hex_set = {(int(col), int(row)) for col, row in wall_hexes}
            
            from config_loader import get_config_loader
            config_loader = get_config_loader()
            board_config = config_loader.get_board_config()
            board_spec = board_config["default"] if "default" in board_config else board_config
            board_cols = require_key(board_spec, "cols")
            board_rows = require_key(board_spec, "rows")
            if board_cols <= 0 or board_rows <= 0:
                raise ValueError(f"Invalid board dimensions: cols={board_cols}, rows={board_rows}")

            def _is_valid_deploy_hex(col: int, row: int) -> bool:
                if col < 0 or col >= board_cols or row < 0 or row >= board_rows:
                    return False
                if row == board_rows - 1 and (col % 2) == 1:
                    return False
                return True

            deploy_pools = {}
            if deployment_zone:
                if deployment_zone != "hammer":
                    raise ValueError(
                        f"Unsupported deployment_zone '{deployment_zone}' in {scenario_file}"
                    )
                project_root = os.path.dirname(os.path.dirname(__file__))
                deployment_path = os.path.join(project_root, "config", "deployment", "hammer.json")
                if not os.path.exists(deployment_path):
                    raise FileNotFoundError(f"Deployment file not found: {deployment_path}")
                try:
                    with open(deployment_path, "r") as f:
                        deployment_data = json.load(f)
                except Exception as e:
                    raise ValueError(f"Failed to parse deployment file {deployment_path}: {e}")
                if "p1" not in deployment_data or "p2" not in deployment_data:
                    raise KeyError(f"Deployment file {deployment_path} missing required p1/p2 zones")
                
                def _build_deploy_pool(zone: Dict[str, Any]) -> set[tuple[int, int]]:
                    col_min = require_key(zone, "col_min")
                    col_max = require_key(zone, "col_max")
                    row_min = require_key(zone, "row_min")
                    row_max = require_key(zone, "row_max")
                    if col_min > col_max or row_min > row_max:
                        raise ValueError(
                            f"Invalid deploy bounds: col=({col_min},{col_max}) row=({row_min},{row_max})"
                        )
                    pool = {
                        (col, row)
                        for col in range(col_min, col_max + 1)
                        for row in range(row_min, row_max + 1)
                        if _is_valid_deploy_hex(col, row)
                    }
                    return pool
                
                deploy_pools = {
                    1: _build_deploy_pool(deployment_data["p1"]),
                    2: _build_deploy_pool(deployment_data["p2"]),
                }
                if deployment_type == "random":
                    if not wall_hex_set:
                        raise KeyError(
                            f"Scenario file {scenario_file} missing required 'wall_hexes' for random deployment"
                        )
                    deploy_pools = {
                        1: deploy_pools[1] - wall_hex_set,
                        2: deploy_pools[2] - wall_hex_set,
                    }
            used_hexes = set()
            
            enhanced_units = []
            for unit_data in basic_units:
                if "unit_type" not in unit_data:
                    raise KeyError(f"Unit missing required 'unit_type' field: {unit_data}")
                
                unit_type = unit_data["unit_type"]
                unit_player = require_key(unit_data, "player")
                if deployment_type == "random":
                    if unit_player not in deploy_pools:
                        raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                    available_hexes = list(deploy_pools[unit_player] - used_hexes)
                    if not available_hexes:
                        raise ValueError(
                            f"No available deployment hexes for player {unit_player} "
                            f"(units={len([u for u in basic_units if require_key(u, 'player') == unit_player])})"
                        )
                    chosen_col, chosen_row = random.choice(available_hexes)
                    used_hexes.add((chosen_col, chosen_row))
                else:
                    required_fields = ["id", "player", "col", "row"]
                    for field in required_fields:
                        if field not in unit_data:
                            raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                    chosen_col, chosen_row = normalize_coordinates(unit_data["col"], unit_data["row"])
                    if deployment_zone:
                        if unit_player not in deploy_pools:
                            raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                        if (chosen_col, chosen_row) not in deploy_pools[unit_player]:
                            raise ValueError(
                                f"Unit {unit_data.get('id')} outside deployment zone '{deployment_zone}' "
                                f"for player {unit_player}: ({chosen_col},{chosen_row})"
                            )
                    if deployment_zone and not _is_valid_deploy_hex(chosen_col, chosen_row):
                        raise ValueError(
                            f"Unit {unit_data.get('id')} on invalid deploy hex: ({chosen_col},{chosen_row})"
                        )
                    if wall_hex_set and (chosen_col, chosen_row) in wall_hex_set:
                        raise ValueError(
                            f"Unit {unit_data.get('id')} placed on wall hex: ({chosen_col},{chosen_row})"
                        )
                    if (chosen_col, chosen_row) in used_hexes:
                        raise ValueError(
                            f"Duplicate unit position: ({chosen_col},{chosen_row})"
                        )
                    used_hexes.add((chosen_col, chosen_row))
                
                try:
                    full_unit_data = unit_registry.get_unit_data(unit_type)
                except Exception as e:
                    raise ValueError(f"Failed to get unit data for '{unit_type}': {e}")
                
                required_fields = ["id", "player"]
                for field in required_fields:
                    if field not in unit_data:
                        raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract RNG_WEAPONS and CC_WEAPONS
                rng_weapons = require_key(full_unit_data, "RNG_WEAPONS")
                cc_weapons = require_key(full_unit_data, "CC_WEAPONS")
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
                if not rng_weapons and not cc_weapons:
                    raise ValueError(f"Unit {unit_type} must have at least RNG_WEAPONS or CC_WEAPONS")
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
                selected_rng_weapon_index = 0 if rng_weapons else None
                selected_cc_weapon_index = 0 if cc_weapons else None
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
                shoot_left = 0
                if rng_weapons and selected_rng_weapon_index is not None:
                    selected_weapon = rng_weapons[selected_rng_weapon_index]
                    if isinstance(selected_weapon, dict):
                        shoot_left = resolve_dice_value(
                            require_key(selected_weapon, "NB"),
                            "scenario_init_shoot_left",
                        )
                    else:
                        raise TypeError(f"Unit {unit_type}: RNG_WEAPONS[{selected_rng_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")
                
                attack_left = 0
                if cc_weapons and selected_cc_weapon_index is not None:
                    selected_weapon = cc_weapons[selected_cc_weapon_index]
                    if isinstance(selected_weapon, dict):
                        attack_left = resolve_dice_value(
                            require_key(selected_weapon, "NB"),
                            "scenario_init_attack_left",
                        )
                    else:
                        raise TypeError(f"Unit {unit_type}: CC_WEAPONS[{selected_cc_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")
                
                enhanced_unit = {
                    "id": str(unit_data["id"]),
                    "player": unit_player,
                    "unitType": unit_type,
                    "col": normalize_coordinates(chosen_col, chosen_row)[0],
                    "row": normalize_coordinates(chosen_col, chosen_row)[1],
                    "HP_CUR": full_unit_data["HP_MAX"],
                    "HP_MAX": full_unit_data["HP_MAX"],
                    "MOVE": full_unit_data["MOVE"],
                    "T": full_unit_data["T"],
                    "ARMOR_SAVE": full_unit_data["ARMOR_SAVE"],
                    "INVUL_SAVE": full_unit_data["INVUL_SAVE"],
                    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
                    "RNG_WEAPONS": rng_weapons,
                    "CC_WEAPONS": cc_weapons,
                    "selectedRngWeaponIndex": selected_rng_weapon_index,
                    "selectedCcWeaponIndex": selected_cc_weapon_index,
                    "LD": full_unit_data["LD"],
                    "OC": full_unit_data["OC"],
                    "VALUE": full_unit_data["VALUE"],
                    "ICON": full_unit_data["ICON"],
                    "ICON_SCALE": full_unit_data["ICON_SCALE"],
                    "UNIT_RULES": require_key(full_unit_data, "UNIT_RULES"),
                    "SHOOT_LEFT": shoot_left,
                    "ATTACK_LEFT": attack_left
                }
                
                enhanced_units.append(enhanced_unit)

            # Extract optional terrain data from scenario
            # If present in scenario, use it; otherwise return None for board config selection
            scenario_walls = None
            scenario_objectives = None
            scenario_primary_objective = None

            if isinstance(scenario_data, dict):
                if "wall_hexes" in scenario_data:
                    scenario_walls = scenario_data["wall_hexes"]
                # Support new grouped objectives structure
                if "objectives" in scenario_data:
                    scenario_objectives = scenario_data["objectives"]
                # Legacy flat list support (deprecated)
                elif "objective_hexes" in scenario_data:
                    scenario_objectives = scenario_data["objective_hexes"]
                if "primary_objectives" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objectives"]
                elif "primary_objective" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objective"]

            scenario_primary_objectives = (
                scenario_primary_objective
                if isinstance(scenario_primary_objective, list)
                else None
            )
            scenario_primary_objective_single = (
                scenario_primary_objective
                if scenario_primary_objective is not None and not isinstance(scenario_primary_objective, list)
                else None
            )

            # Return dict with units and optional terrain
            return {
                "units": enhanced_units,
                "wall_hexes": scenario_walls,
                "objectives": scenario_objectives,
                "primary_objectives": scenario_primary_objectives,
                "primary_objective": scenario_primary_objective_single
            }
    
    # ============================================================================
    # UTILITIES
    # ============================================================================

    def get_unit_by_id(self, unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state.

        CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
        """
        for unit in game_state["units"]:
            if str(unit["id"]) == str(unit_id):
                return unit
        return None

    # ============================================================================
    # OBJECTIVE CONTROL SYSTEM
    # ============================================================================

    def calculate_objective_control(self, game_state: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        """
        Calculate objective control for each objective with configured control method.

        Win condition: Control more objectives than opponent at end of turn 5.
        Control rules:
        - To CAPTURE an objective: Your OC sum must be > opponent's OC sum
        - control_method == "sticky": keep control until opponent captures
        - control_method == "occupy": control only if currently occupied with greater OC
        - Equal OC = current controller keeps control (sticky) or stays neutral (occupy)

        Returns:
            Dict[objective_id, {
                'player_1_oc': int,  # Total OC for player 1
                'player_2_oc': int,  # Total OC for player 2
                'controller': int|None  # 1, 2, or None (contested/uncontrolled)
            }]
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {}

        primary_objective = require_key(game_state, "primary_objective")
        if primary_objective is None:
            raise ValueError("primary_objective is required to calculate objective control")
        if isinstance(primary_objective, list):
            if not primary_objective:
                raise ValueError("primary_objective list cannot be empty for objective control")
            primary_configs = primary_objective
        else:
            primary_configs = [primary_objective]

        control_method: Optional[str] = None
        for objective_cfg in primary_configs:
            if not isinstance(objective_cfg, dict):
                raise TypeError("primary_objective entry must be a dict for objective control")
            control_cfg = require_key(objective_cfg, "control")
            method = require_key(control_cfg, "method")
            if method != "oc_sum_greater":
                raise ValueError(f"Unsupported primary objective control method: {method}")
            current_control_method = require_key(control_cfg, "control_method")
            if current_control_method not in ("sticky", "occupy"):
                raise ValueError(f"Unsupported control_method: {current_control_method}")
            tie_behavior = require_key(control_cfg, "tie_behavior")
            if tie_behavior != "no_control":
                raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")
            if control_method is None:
                control_method = current_control_method
            elif control_method != current_control_method:
                raise ValueError("primary_objective control_method must be consistent across configs")

        if control_method is None:
            raise ValueError("control_method is required to calculate objective control")

        # Get persistent control state (initialize if not present)
        if "objective_controllers" not in game_state:
            game_state["objective_controllers"] = {}

        result = {}

        for objective in objectives:
            obj_id = objective["id"]
            obj_hexes = objective["hexes"]
            obj_id_key = str(obj_id)

            # Convert hex list to set of tuples for fast lookup
            hex_set = set(tuple(h) for h in obj_hexes)

            # Calculate OC per player
            player_1_oc = 0
            player_2_oc = 0

            units_cache = require_key(game_state, "units_cache")
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            for unit_id, entry in units_cache.items():
                unit = unit_by_id.get(str(unit_id))
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")

                unit_pos = normalize_coordinates(entry["col"], entry["row"])
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    unit_player = require_key(unit, "player")
                    if unit_player == 1:
                        player_1_oc += oc
                    elif unit_player == 2:
                        player_2_oc += oc
                    else:
                        raise ValueError(f"Unexpected unit player id: {unit_player}")

            # Get current controller from persistent state; explicit init when first seeing this objective
            if obj_id_key not in game_state["objective_controllers"]:
                game_state["objective_controllers"][obj_id_key] = None
            current_controller = game_state["objective_controllers"][obj_id_key]

            if control_method == "sticky":
                # Determine new controller with PERSISTENT control rules
                new_controller = current_controller  # Default: keep current control

                if player_1_oc > player_2_oc:
                    # P1 has more OC - P1 captures/keeps
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    # P2 has more OC - P2 captures/keeps
                    new_controller = 2
                # If equal OC: current controller keeps control (no change)
                # This includes 0-0 case where objective stays in its current state
            elif control_method == "occupy":
                new_controller = None
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
            else:
                raise ValueError(f"Unsupported control_method: {control_method}")

            # Update persistent state
            game_state["objective_controllers"][obj_id_key] = new_controller

            result[obj_id] = {
                "player_1_oc": player_1_oc,
                "player_2_oc": player_2_oc,
                "controller": new_controller
            }

        return result

    def count_controlled_objectives(self, game_state: Dict[str, Any]) -> Dict[int, int]:
        """
        Count objectives controlled by each player.

        Returns:
            {1: count_for_player_1, 2: count_for_player_2}
        """
        control_data = self.calculate_objective_control(game_state)

        counts = {1: 0, 2: 0}
        for obj_id, data in control_data.items():
            if data["controller"] is not None:
                controller = data["controller"]
                if controller not in counts:
                    raise ValueError(f"Unexpected objective controller: {controller}")
                counts[controller] += 1

        return counts

    def _calculate_primary_objective_control_counts(
        self,
        game_state: Dict[str, Any],
        primary_objective: Dict[str, Any]
    ) -> Dict[int, int]:
        """
        Calculate objective control counts for primary objective scoring.

        Uses primary objective control rules (method + tie behavior) to count
        objectives controlled by each player for scoring purposes.
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {1: 0, 2: 0}

        objective_controllers = require_key(game_state, "objective_controllers")

        control_cfg = require_key(primary_objective, "control")
        method = require_key(control_cfg, "method")
        control_method = require_key(control_cfg, "control_method")
        tie_behavior = require_key(control_cfg, "tie_behavior")

        if method != "oc_sum_greater":
            raise ValueError(f"Unsupported primary objective control method: {method}")
        if control_method not in ("sticky", "occupy"):
            raise ValueError(f"Unsupported control_method: {control_method}")
        if tie_behavior != "no_control":
            raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}

        counts = {1: 0, 2: 0}

        for objective in objectives:
            obj_id = require_key(objective, "id")
            obj_id_key = str(obj_id)
            obj_hexes = require_key(objective, "hexes")
            hex_set = {normalize_coordinates(h[0], h[1]) for h in obj_hexes}
            player_1_oc = 0
            player_2_oc = 0

            for unit_id, entry in units_cache.items():
                unit = unit_by_id.get(str(unit_id))
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                unit_pos = normalize_coordinates(entry["col"], entry["row"])
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    unit_player = require_key(entry, "player")
                    unit_player_int = int(unit_player)
                    if unit_player_int == 1:
                        player_1_oc += oc
                    elif unit_player_int == 2:
                        player_2_oc += oc
                    else:
                        raise ValueError(f"Unexpected unit player id: {unit_player}")

            if obj_id_key not in objective_controllers:
                objective_controllers[obj_id_key] = None
            current_controller = objective_controllers[obj_id_key]
            if control_method == "sticky":
                new_controller = current_controller
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
                # If equal OC: current controller keeps control (sticky)
            elif control_method == "occupy":
                new_controller = None
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
            else:
                raise ValueError(f"Unsupported control_method: {control_method}")

            objective_controllers[obj_id_key] = new_controller
            if new_controller is not None:
                counts[new_controller] += 1

        return counts

    def apply_primary_objective_scoring(self, game_state: Dict[str, Any], scoring_phase: str) -> None:
        """
        Apply primary objective scoring for the current turn and player.
        
        scoring_phase: "command" or "fight"
        """
        primary_objective = game_state.get("primary_objective")
        if primary_objective is None:
            return
        if isinstance(primary_objective, list):
            for objective in primary_objective:
                if not isinstance(objective, dict):
                    raise TypeError(f"primary_objective list entry is {type(objective).__name__}, expected dict")
                self._apply_primary_objective_scoring_single(game_state, scoring_phase, objective)
            return
        if not isinstance(primary_objective, dict):
            raise TypeError(f"primary_objective is {type(primary_objective).__name__}, expected dict")
        self._apply_primary_objective_scoring_single(game_state, scoring_phase, primary_objective)

    def _apply_primary_objective_scoring_single(
        self,
        game_state: Dict[str, Any],
        scoring_phase: str,
        primary_objective: Dict[str, Any]
    ) -> None:
        """
        Apply primary objective scoring for a single objective config.
        """

        scoring_cfg = require_key(primary_objective, "scoring")
        timing_cfg = require_key(primary_objective, "timing")
        start_turn = require_key(scoring_cfg, "start_turn")
        max_points_per_turn = require_key(scoring_cfg, "max_points_per_turn")
        rules = require_key(scoring_cfg, "rules")
        default_phase = require_key(timing_cfg, "default_phase")
        round5_second_player_phase = require_key(timing_cfg, "round5_second_player_phase")

        current_turn = require_key(game_state, "turn")
        current_player = require_key(game_state, "current_player")
        current_player_int = int(current_player)

        if current_turn < start_turn:
            return

        if current_turn == 5 and current_player_int == 2:
            expected_phase = round5_second_player_phase
        else:
            expected_phase = default_phase

        if scoring_phase != expected_phase:
            return

        objective_id = require_key(primary_objective, "id")
        scored_turns = require_key(game_state, "primary_objective_scored_turns")
        score_key = (objective_id, current_turn, current_player_int)
        if score_key in scored_turns:
            return

        counts = self._calculate_primary_objective_control_counts(game_state, primary_objective)
        opponent_player = 1 if current_player_int == 2 else 2

        total_points = 0
        for rule in rules:
            condition = require_key(rule, "condition")
            points = require_key(rule, "points")
            if condition == "control_at_least_one":
                if counts[current_player_int] >= 1:
                    total_points += points
            elif condition == "control_at_least_two":
                if counts[current_player_int] >= 2:
                    total_points += points
            elif condition == "control_more_than_opponent":
                if counts[current_player_int] > counts[opponent_player]:
                    total_points += points
            else:
                raise ValueError(f"Unsupported primary objective condition: {condition}")

        if total_points > max_points_per_turn:
            total_points = max_points_per_turn

        victory_points = require_key(game_state, "victory_points")
        if current_player_int not in victory_points:
            raise KeyError(f"victory_points missing player {current_player_int}")
        victory_points[current_player_int] += total_points
        scored_turns.add(score_key)

    def check_game_over(self, game_state: Dict[str, Any]) -> bool:
        """
        Check if game is over.

        Game ends when:
        1. Turn limit reached (training config override)
        """
        # Check training turn limit (for RL training - may differ from standard 5 turns)
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and game_state["turn"] > max_turns:
                return True

        if require_key(game_state, "turn_limit_reached"):
            return True

        return False
    
    def determine_winner(self, game_state: Dict[str, Any]) -> Optional[int]:
        """
        Determine winner based on primary objective victory points.

        Victory conditions:
        1. More victory points at end of game
        2. Tiebreaker: More total VALUE of living units
        3. Draw if still tied

        Returns:
            1 = Player 1 wins
            2 = Player 2 wins
            -1 = Draw
            None = Game still ongoing
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1
        if p2_points > p1_points:
            return 2

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        p1_value = 0
        p2_value = 0
        for unit_id, entry in units_cache.items():
            unit = unit_by_id.get(str(unit_id))
            if not unit:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if entry["player"] == 1:
                p1_value += unit_value
            elif entry["player"] == 2:
                p2_value += unit_value
            else:
                raise ValueError(f"Unexpected unit player id: {entry['player']}")

        if p1_value > p2_value:
            return 1
        if p2_value > p1_value:
            return 2
        return -1

    def determine_winner_with_method(self, game_state: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
        """
        Determine winner AND the method of victory.

        Returns:
            Tuple of (winner, win_method):
            - winner: 1, 2, -1 (draw), or None (ongoing)
            - win_method: "objectives", "value_tiebreaker", "draw", or None
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None, None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1, "objectives"
        if p2_points > p1_points:
            return 2, "objectives"

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        p1_value = 0
        p2_value = 0
        for unit_id, entry in units_cache.items():
            unit = unit_by_id.get(str(unit_id))
            if not unit:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if entry["player"] == 1:
                p1_value += unit_value
            elif entry["player"] == 2:
                p2_value += unit_value
            else:
                raise ValueError(f"Unexpected unit player id: {entry['player']}")

        if p1_value > p2_value:
            return 1, "value_tiebreaker"
        if p2_value > p1_value:
            return 2, "value_tiebreaker"
        return -1, "draw"
