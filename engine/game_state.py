#!/usr/bin/env python3
"""
game_state.py - Game state initialization and management
"""

from typing import Dict, List, Any, Optional, Tuple
import json

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
    
    def validate_uppercase_fields(self, unit: Dict[str, Any]):
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
    
    def load_units_from_scenario(self, scenario_file, unit_registry):
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

            # Extract optional terrain data from scenario
            # If present in scenario, use it; if not, return None to signal fallback to board config
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
        objectives = game_state.get("objectives", [])
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

            for unit in game_state["units"]:
                if unit["HP_CUR"] <= 0:
                    continue  # Dead units don't control

                unit_pos = (unit["col"], unit["row"])
                if unit_pos in hex_set:
                    oc = unit.get("OC", 1)  # Default OC=1 if not specified
                    if unit["player"] == 0:
                        player_0_oc += oc
                    else:
                        player_1_oc += oc

            # Get current controller from persistent state
            current_controller = game_state["objective_controllers"].get(obj_id, None)

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

        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1

        # Game is over if any player has no living units
        return len(living_units_by_player) <= 1
    
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

        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
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
                print(f"   → Winner: Player {winner} (elimination)")
            return winner
        elif len(living_players) == 0:
            if not self.quiet:
                print(f"   → Draw: No survivors")
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
                    print(f"   → Winner: Player 0 ({obj_counts[0]} > {obj_counts[1]} objectives)")
                return 0
            elif obj_counts[1] > obj_counts[0]:
                if not self.quiet:
                    print(f"   → Winner: Player 1 ({obj_counts[1]} > {obj_counts[0]} objectives)")
                return 1
            else:
                # Tiebreaker: More cumulated VALUE of living units wins
                p0_value = sum(u.get("VALUE", 10) for u in game_state["units"]
                              if u["player"] == 0 and u["HP_CUR"] > 0)
                p1_value = sum(u.get("VALUE", 10) for u in game_state["units"]
                              if u["player"] == 1 and u["HP_CUR"] > 0)
                if not self.quiet:
                    print(f"   Equal objectives ({obj_counts[0]}), tiebreaker by VALUE: P0={p0_value}, P1={p1_value}")

                if p0_value > p1_value:
                    if not self.quiet:
                        print(f"   → Winner: Player 0 (tiebreaker: {p0_value} > {p1_value} VALUE)")
                    return 0
                elif p1_value > p0_value:
                    if not self.quiet:
                        print(f"   → Winner: Player 1 (tiebreaker: {p1_value} > {p0_value} VALUE)")
                    return 1
                else:
                    if not self.quiet:
                        print(f"   → Draw: Equal objectives and VALUE")
                    return -1

        # Game still ongoing
        if not self.quiet:
            print(f"   → Game ongoing: turn {current_turn}, both players have units")
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

        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
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
        game_ended_by_turns = False
        if hasattr(self, 'training_config') and max_turns:
            game_ended_by_turns = current_turn > max_turns
        else:
            game_ended_by_turns = current_turn > 5

        if game_ended_by_turns:
            # OBJECTIVE-BASED VICTORY at turn limit
            obj_counts = self.count_controlled_objectives(game_state)

            if obj_counts[0] > obj_counts[1]:
                return 0, "objectives"
            elif obj_counts[1] > obj_counts[0]:
                return 1, "objectives"
            else:
                # Tiebreaker: More cumulated VALUE of living units wins
                p0_value = sum(u.get("VALUE", 10) for u in game_state["units"]
                              if u["player"] == 0 and u["HP_CUR"] > 0)
                p1_value = sum(u.get("VALUE", 10) for u in game_state["units"]
                              if u["player"] == 1 and u["HP_CUR"] > 0)

                if p0_value > p1_value:
                    return 0, "value_tiebreaker"
                elif p1_value > p0_value:
                    return 1, "value_tiebreaker"
                else:
                    return -1, "draw"

        # Game still ongoing
        return None, None