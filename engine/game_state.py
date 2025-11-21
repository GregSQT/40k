#!/usr/bin/env python3
"""
game_state.py - Game state initialization and management
"""

from typing import Dict, List, Any, Optional
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
                if "objective_hexes" in scenario_data:
                    scenario_objectives = scenario_data["objective_hexes"]

            # Return dict with units and optional terrain
            return {
                "units": enhanced_units,
                "wall_hexes": scenario_walls,
                "objective_hexes": scenario_objectives
            }
    
    # ============================================================================
    # UTILITIES
    # ============================================================================
    
    def get_unit_by_id(self, unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state."""
        for unit in game_state["units"]:
            if unit["id"] == unit_id:
                return unit
        return None
    
    def check_game_over(self, game_state: Dict[str, Any]) -> bool:
        """Check if game is over - unit elimination OR turn limit reached."""
        # Check turn limit first
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and game_state["turn"] > max_turns:
                return True
        
        # Check unit elimination
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
        """Determine winner based on remaining living units or turn limit. Returns -1 for draw."""
        living_units_by_player = {}
        
        for unit in game_state["units"]:
            if unit["HP_CUR"] > 0:
                player = unit["player"]
                if player not in living_units_by_player:
                    living_units_by_player[player] = 0
                living_units_by_player[player] += 1
        
        # DEBUG: Log winner determination details
        current_turn = game_state["turn"]
        max_turns = self.training_config.get("max_turns_per_episode") if hasattr(self, 'training_config') else None
        
        if not self.quiet:
            print(f"\n🔍 WINNER DETERMINATION DEBUG:")
            print(f"   Current turn: {current_turn}")
            print(f"   Max turns: {max_turns}")
            print(f"   Living units: {living_units_by_player}")
            print(f"   Has training_config: {hasattr(self, 'training_config')}")
            if hasattr(self, 'training_config'):
                print(f"   Turn > max_turns? {current_turn > max_turns if max_turns else 'N/A'}")
        
        # Check if game ended due to turn limit
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and game_state["turn"] > max_turns:
                # Turn limit reached - determine winner by remaining units
                living_players = list(living_units_by_player.keys())
                if len(living_players) == 1:
                    if not self.quiet:
                        print(f"   → Winner: Player {living_players[0]} (elimination after turn limit)")
                    return living_players[0]
                elif len(living_players) == 2:
                    # Both players have units - compare counts
                    if living_units_by_player[0] > living_units_by_player[1]:
                        if not self.quiet:
                            print(f"   → Winner: Player 0 ({living_units_by_player[0]} > {living_units_by_player[1]} units)")
                        return 0
                    elif living_units_by_player[1] > living_units_by_player[0]:
                        if not self.quiet:
                            print(f"   → Winner: Player 1 ({living_units_by_player[1]} > {living_units_by_player[0]} units)")
                        return 1
                    else:
                        if not self.quiet:
                            print(f"   → Draw: Equal units ({living_units_by_player[0]} == {living_units_by_player[1]}) - returning -1")
                        return -1  # Draw - equal units (use -1 to distinguish from None/ongoing)
                else:
                    if not self.quiet:
                        print(f"   → Draw: Unexpected player count ({len(living_players)} players) - returning -1")
                    return -1  # Draw - no units or other scenario
        
        # Normal elimination rules
        living_players = list(living_units_by_player.keys())
        if len(living_players) == 1:
            if not self.quiet:
                print(f"   → Winner: Player {living_players[0]} (elimination)")
            return living_players[0]
        elif len(living_players) == 0:
            if not self.quiet:
                print(f"   → Draw: No survivors - returning -1")
            return -1  # Draw/no winner
        else:
            if not self.quiet:
                print(f"   → Game ongoing: {len(living_players)} players with units")
            return None  # Game still ongoing