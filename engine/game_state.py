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
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE",
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
                    "SHOOT_LEFT": shoot_left,
                    "ATTACK_LEFT": attack_left
                }
                
                enhanced_units.append(enhanced_unit)

            # Extract optional terrain data from scenario
            # If present in scenario, use it; otherwise return None for board config selection
            scenario_walls = None
            scenario_objectives = None

            if isinstance(scenario_data, dict):
                if "wall_hexes" in scenario_data:
                    scenario_walls = scenario_data["wall_hexes"]
                # Support new grouped objectives structure
                if "objectives" in scenario_data:
                    scenario_objectives = scenario_data["objectives"]
                # Legacy flat list support (deprecated)
                elif "objective_hexes" in scenario_data:
                    scenario_objectives = scenario_data["objective_hexes"]

            # Return dict with units and optional terrain
            return {
                "units": enhanced_units,
                "wall_hexes": scenario_walls,
                "objectives": scenario_objectives
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
        Calculate objective control for each objective with PERSISTENT control.

        Win condition: Control more objectives than opponent at end of turn 5.
        Control rules:
        - To CAPTURE an objective: Your OC sum must be > opponent's OC sum
        - Once controlled, you KEEP control until opponent captures it
        - Equal OC = current controller keeps control (or stays neutral if uncontrolled)

        Returns:
            Dict[objective_id, {
                'player_0_oc': int,  # Total OC for player 0
                'player_1_oc': int,  # Total OC for player 1
                'controller': int|None  # 0, 1, or None (contested/uncontrolled)
            }]
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {}

        # Get persistent control state (initialize if not present)
        if "objective_controllers" not in game_state:
            game_state["objective_controllers"] = {}

        result = {}

        for objective in objectives:
            obj_id = objective["id"]
            obj_hexes = objective["hexes"]

            # Convert hex list to set of tuples for fast lookup
            hex_set = set(tuple(h) for h in obj_hexes)

            # Calculate OC per player
            player_0_oc = 0
            player_1_oc = 0

            units_cache = require_key(game_state, "units_cache")
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            for unit_id, entry in units_cache.items():
                unit = unit_by_id.get(str(unit_id))
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")

                unit_pos = normalize_coordinates(entry["col"], entry["row"])
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    if unit["player"] == 0:
                        player_0_oc += oc
                    else:
                        player_1_oc += oc

            # Get current controller from persistent state; explicit init when first seeing this objective
            if str(obj_id) not in game_state["objective_controllers"]:
                game_state["objective_controllers"][str(obj_id)] = None
            current_controller = game_state["objective_controllers"][str(obj_id)]

            # Determine new controller with PERSISTENT control rules
            new_controller = current_controller  # Default: keep current control

            if player_0_oc > player_1_oc:
                # P0 has more OC - P0 captures/keeps
                new_controller = 0
            elif player_1_oc > player_0_oc:
                # P1 has more OC - P1 captures/keeps
                new_controller = 1
            # If equal OC: current controller keeps control (no change)
            # This includes 0-0 case where objective stays in its current state

            # Update persistent state
            game_state["objective_controllers"][obj_id] = new_controller

            result[obj_id] = {
                "player_0_oc": player_0_oc,
                "player_1_oc": player_1_oc,
                "controller": new_controller
            }

        return result

    def count_controlled_objectives(self, game_state: Dict[str, Any]) -> Dict[int, int]:
        """
        Count objectives controlled by each player.

        Returns:
            {0: count_for_player_0, 1: count_for_player_1}
        """
        control_data = self.calculate_objective_control(game_state)

        counts = {0: 0, 1: 0}
        for obj_id, data in control_data.items():
            if data["controller"] is not None:
                counts[data["controller"]] += 1

        return counts

    def check_game_over(self, game_state: Dict[str, Any]) -> bool:
        """
        Check if game is over.

        Game ends when:
        1. Turn 5 completes (objective-based victory)
        2. One player has no living units (elimination victory)
        3. Turn limit reached (training config override)
        """
        # Check training turn limit (for RL training - may differ from standard 5 turns)
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and game_state["turn"] > max_turns:
                return True

        # Standard W40K: Game ends after turn 5
        # Check if we've completed turn 5 (turn counter goes to 6)
        if game_state["turn"] > 5:
            return True

        # Check unit elimination - game over if any player has no living units
        living_units_by_player = {}
        dead_units_by_player = {}

        units_cache = require_key(game_state, "units_cache")
        for _unit_id, entry in units_cache.items():
            player = entry["player"]
            if player not in living_units_by_player:
                living_units_by_player[player] = 0
            living_units_by_player[player] += 1

        # Check if any player has no living units (elimination condition)
        players_with_no_living_units = [pid for pid, count in living_units_by_player.items() if count == 0]
        game_over_by_elimination = len(players_with_no_living_units) > 0

        # Game is over if any player has no living units
        return game_over_by_elimination
    
    def determine_winner(self, game_state: Dict[str, Any]) -> Optional[int]:
        """
        Determine winner based on objective control or elimination.

        Victory conditions (in order of priority):
        1. Elimination: If one player has no living units, opponent wins
        2. Objective control: At end of turn 5, player controlling more objectives wins
        3. Tiebreaker: If equal objectives, player with more cumulated VALUE wins
        4. Draw: If still tied, return -1

        Returns:
            0 = Player 0 wins
            1 = Player 1 wins
            -1 = Draw
            None = Game still ongoing
        """
        living_units_by_player = {}
        units_cache = require_key(game_state, "units_cache")
        for _unit_id, entry in units_cache.items():
            player = entry["player"]
            if player not in living_units_by_player:
                living_units_by_player[player] = 0
            living_units_by_player[player] += 1

        current_turn = game_state["turn"]
        max_turns = self.training_config.get("max_turns_per_episode") if hasattr(self, 'training_config') else 5

        if not self.quiet:
            print(f"\n🔍 WINNER DETERMINATION DEBUG:")
            print(f"   Current turn: {current_turn}")
            print(f"   Max turns: {max_turns}")
            print(f"   Living units: {living_units_by_player}")

        # Check elimination first (immediate win condition)
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            winner = living_players[0]
            if not self.quiet:
                print(f"   -> Winner: Player {winner} (elimination)")
            return winner
        elif len(living_players) == 0:
            if not self.quiet:
                print(f"   -> Draw: No survivors")
            return -1

        # Check if game ended due to turn limit (turn 5 end or training config)
        game_ended_by_turns = False
        if hasattr(self, 'training_config') and max_turns:
            game_ended_by_turns = current_turn > max_turns
        else:
            game_ended_by_turns = current_turn > 5

        if game_ended_by_turns:
            # OBJECTIVE-BASED VICTORY at turn limit
            obj_counts = self.count_controlled_objectives(game_state)

            if not self.quiet:
                print(f"   Objective control: P0={obj_counts[0]}, P1={obj_counts[1]}")

            if obj_counts[0] > obj_counts[1]:
                if not self.quiet:
                    print(f"   -> Winner: Player 0 ({obj_counts[0]} > {obj_counts[1]} objectives)")
                return 0
            elif obj_counts[1] > obj_counts[0]:
                if not self.quiet:
                    print(f"   -> Winner: Player 1 ({obj_counts[1]} > {obj_counts[0]} objectives)")
                return 1
            else:
                # Tiebreaker: More cumulated VALUE of living units wins
                units_cache = require_key(game_state, "units_cache")
                unit_by_id = {str(u["id"]): u for u in game_state["units"]}
                p0_value = 0
                p1_value = 0
                for unit_id, entry in units_cache.items():
                    unit = unit_by_id.get(str(unit_id))
                    if not unit:
                        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                    unit_value = unit.get("VALUE", 10)
                    if entry["player"] == 0:
                        p0_value += unit_value
                    else:
                        p1_value += unit_value
                if not self.quiet:
                    print(f"   Equal objectives ({obj_counts[0]}), tiebreaker by VALUE: P0={p0_value}, P1={p1_value}")

                if p0_value > p1_value:
                    if not self.quiet:
                        print(f"   -> Winner: Player 0 (tiebreaker: {p0_value} > {p1_value} VALUE)")
                    return 0
                elif p1_value > p0_value:
                    if not self.quiet:
                        print(f"   -> Winner: Player 1 (tiebreaker: {p1_value} > {p0_value} VALUE)")
                    return 1
                else:
                    if not self.quiet:
                        print(f"   -> Draw: Equal objectives and VALUE")
                    return -1

        # Game still ongoing
        if not self.quiet:
            print(f"   -> Game ongoing: turn {current_turn}, both players have units")
        return None

    def determine_winner_with_method(self, game_state: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
        """
        Determine winner AND the method of victory.

        Returns:
            Tuple of (winner, win_method):
            - winner: 0, 1, -1 (draw), or None (ongoing)
            - win_method: "elimination", "objectives", "value_tiebreaker", "draw", or None
        """
        living_units_by_player = {}
        units_cache = require_key(game_state, "units_cache")
        for _unit_id, entry in units_cache.items():
            player = entry["player"]
            if player not in living_units_by_player:
                living_units_by_player[player] = 0
            living_units_by_player[player] += 1

        current_turn = game_state["turn"]
        max_turns = self.training_config.get("max_turns_per_episode") if hasattr(self, 'training_config') else 5

        # Check elimination first (immediate win condition)
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            return living_players[0], "elimination"
        elif len(living_players) == 0:
            return -1, "draw"

        # Check if game ended due to turn limit
        # CRITICAL: Only check objectives if game ended by turn limit (not elimination)
        # This happens when P1 completes turn 5 and turn_limit_reached flag is set
        game_ended_by_turns = False
        if len(living_players) == 2:  # Both players still alive
            # Check if turn_limit_reached flag is set (set by fight_handlers when P1 completes turn 5)
            if require_key(game_state, "turn_limit_reached"):
                game_ended_by_turns = True
            # Note: We don't check turn number; only when flag is explicitly set

        if game_ended_by_turns:
            # OBJECTIVE-BASED VICTORY at turn limit
            obj_counts = self.count_controlled_objectives(game_state)

            if obj_counts[0] > obj_counts[1]:
                return 0, "objectives"
            elif obj_counts[1] > obj_counts[0]:
                return 1, "objectives"
            else:
                # Tiebreaker: More cumulated VALUE of living units wins
                units_cache = require_key(game_state, "units_cache")
                unit_by_id = {str(u["id"]): u for u in game_state["units"]}
                p0_value = 0
                p1_value = 0
                for unit_id, entry in units_cache.items():
                    unit = unit_by_id.get(str(unit_id))
                    if not unit:
                        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                    unit_value = require_key(unit, "VALUE")
                    if entry["player"] == 0:
                        p0_value += unit_value
                    else:
                        p1_value += unit_value

                if p0_value > p1_value:
                    return 0, "value_tiebreaker"
                elif p1_value > p0_value:
                    return 1, "value_tiebreaker"
                else:
                    return -1, "draw"

        # Game still ongoing
        # CRITICAL: If game_over is True, we should never reach here
        # This indicates a bug - log it but return None to indicate the issue
        if require_key(game_state, "game_over"):
            # BUG: Game is over but no winner determined
            # This should not happen - log error but don't crash
            import warnings
            warnings.warn(f"BUG: game_over=True but no winner determined. Turn={current_turn}, Living players={living_players}")
            # Return draw to prevent None win_method
            return -1, "draw"
        else:
            # Game still ongoing - this is normal
            return None, None
