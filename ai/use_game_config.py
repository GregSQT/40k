#!/usr/bin/env python3
"""
ai/use_game_config.py
EXACT Python mirror of frontend/src/hooks/useGameConfig.ts
Configuration loading system - ALL features preserved.

This is the complete functional equivalent of the PvP useGameConfig hook system.
"""

from typing import Dict, List, Any, Optional, Tuple, Union
import json
import os
from dataclasses import dataclass, field
import copy

@dataclass
class DisplayConfig:
    """EXACT mirror of DisplayConfig interface from TypeScript"""
    resolution: Union[str, int]
    auto_density: bool
    antialias: bool
    force_canvas: bool
    icon_scale: float
    eligible_outline_width: float
    eligible_outline_alpha: float
    hp_bar_width_ratio: float
    hp_bar_height: float
    hp_bar_y_offset_ratio: float
    unit_circle_radius_ratio: float
    unit_text_size: float
    selected_border_width: float
    charge_target_border_width: float
    default_border_width: float
    canvas_border: str
    right_column_bottom_offset: float

@dataclass
class ObjectiveZone:
    """EXACT mirror of ObjectiveZone interface from TypeScript"""
    id: str
    hexes: List[Dict[str, int]]

@dataclass
class Wall:
    """EXACT mirror of Wall interface from TypeScript"""
    id: str
    start: Dict[str, int]
    end: Dict[str, int]
    thickness: Optional[float]

@dataclass
class BoardColors:
    """Board color configuration"""
    background: str
    cell_even: str
    cell_odd: str
    cell_border: str
    player_0: str
    player_1: str
    hp_full: str
    hp_damaged: str
    highlight: str
    current_unit: str
    eligible: Optional[str]
    attack: Optional[str]
    charge: Optional[str]
    objective_zone: Optional[str]
    wall: Optional[str]
    objective: str

@dataclass
class BoardConfig:
    """EXACT mirror of BoardConfig interface from TypeScript"""
    cols: int
    rows: int
    hex_radius: float
    margin: float
    wall_hexes: List[Tuple[int, int]]
    objective_hexes: List[Tuple[int, int]]
    colors: BoardColors
    objective_zones: Optional[List[ObjectiveZone]]
    walls: Optional[List[Wall]]
    display: Optional[DisplayConfig]

@dataclass
class GameRules:
    """EXACT mirror of GameRules interface from TypeScript"""
    max_turns: int
    turn_limit_penalty: float
    max_units_per_player: int
    board_size: Tuple[int, int]

@dataclass
class GameplayConfig:
    """Gameplay configuration"""
    phase_order: List[str]
    simultaneous_actions: bool
    auto_end_turn: bool

@dataclass
class AIBehaviorConfig:
    """AI behavior configuration"""
    timeout_ms: int
    retries: int
    fallback_action: str

@dataclass
class ScoringConfig:
    """Scoring configuration"""
    win_bonus: float
    lose_penalty: float
    survival_bonus_per_turn: float

@dataclass
class GameConfig:
    """EXACT mirror of GameConfig interface from TypeScript"""
    game_rules: GameRules
    gameplay: GameplayConfig
    ai_behavior: AIBehaviorConfig
    scoring: ScoringConfig

class UseGameConfig:
    """
    EXACT Python mirror of useGameConfig TypeScript hook.
    Configuration loading system with ALL features preserved.
    """
    
    def __init__(self, board_config_name: str, config_path: str):
        """Initialize with same parameters as TypeScript useGameConfig"""
        self.board_config_name = board_config_name
        self.config_path = config_path
        
        # State variables (EXACT from TypeScript)
        self.board_config: Optional[BoardConfig] = None
        self.game_config: Optional[GameConfig] = None
        self.loading = True
        self.error: Optional[str] = None
        
        # Load configurations
        self._load_configs()

    def _load_configs(self) -> None:
        """
        EXACT mirror of loadConfigs function from TypeScript.
        Load board and game configurations with error handling.
        """
        try:
            self.loading = True
            self.error = None

            # Load both config files (EXACT from TypeScript Promise.all pattern)
            board_config_path = os.path.join(self.config_path, "board_config.json")
            game_config_path = os.path.join(self.config_path, "game_config.json")

            # Check if files exist (mirror HTTP response checks)
            if not os.path.exists(game_config_path):
                raise Exception(f"Game config missing: {game_config_path}")
            
            if not os.path.exists(board_config_path):
                raise Exception(f"Board config missing: {board_config_path}")

            # Read file contents (mirror response.text()) - Handle UTF-8 BOM
            with open(board_config_path, 'r', encoding='utf-8-sig') as f:
                board_response_text = f.read()
            
            with open(game_config_path, 'r', encoding='utf-8-sig') as f:
                game_response_text = f.read()

            # Validate files are not empty (EXACT from TypeScript)
            if not board_response_text.strip():
                raise Exception("Board config file is empty")
            
            if not game_response_text.strip():
                raise Exception("Game config file is empty")

            # Parse JSON (EXACT from TypeScript)
            try:
                board_data = json.loads(board_response_text)
                game_data = json.loads(game_response_text)
            except json.JSONDecodeError as parse_error:
                raise Exception(f"Invalid JSON in config files: {parse_error}")

            # Validate board config name exists (EXACT from TypeScript)
            if self.board_config_name not in board_data:
                available_configs = list(board_data.keys())
                print(f"Board config '{self.board_config_name}' not found, available configs: {available_configs}")
                raise Exception(f"Board config '{self.board_config_name}' not found")

            config_data = board_data[self.board_config_name]

            # Validate required properties (EXACT from TypeScript)
            required_props = ["cols", "rows", "hex_radius"]
            for prop in required_props:
                if prop not in config_data:
                    raise Exception(f"Invalid board config: missing required property '{prop}'")

            # Build BoardConfig object
            self.board_config = self._build_board_config(config_data)
            self.game_config = self._build_game_config(game_data)

        except Exception as err:
            error_message = str(err) if isinstance(err, Exception) else "Failed to load configuration"
            self.error = error_message
            print(f"Game config loading error: {err}")
            
            # AI_INSTRUCTIONS.md: Never create default values or fallbacks - raise error instead
            raise Exception(f"Configuration loading failed: {err}")

        finally:
            self.loading = False

    def _build_board_config(self, config_data: Dict[str, Any]) -> BoardConfig:
        """Build BoardConfig object from JSON data"""
        # Parse colors - validate required section exists
        if "colors" not in config_data:
            raise KeyError("Board config missing required 'colors' section")
        colors_data = config_data["colors"]
        
        # Validate all required color fields
        required_colors = ["background", "cell_even", "cell_odd", "cell_border", 
                          "player_0", "player_1", "hp_full", "hp_damaged", 
                          "highlight", "current_unit", "objective"]
        
        for color_key in required_colors:
            if color_key not in colors_data:
                raise KeyError(f"Colors config missing required field '{color_key}'")
        
        colors = BoardColors(
            background=colors_data["background"],
            cell_even=colors_data["cell_even"],
            cell_odd=colors_data["cell_odd"],
            cell_border=colors_data["cell_border"],
            player_0=colors_data["player_0"],
            player_1=colors_data["player_1"],
            hp_full=colors_data["hp_full"],
            hp_damaged=colors_data["hp_damaged"],
            highlight=colors_data["highlight"],
            current_unit=colors_data["current_unit"],
            eligible=colors_data.get("eligible"),  # Optional fields keep .get()
            attack=colors_data.get("attack"),
            charge=colors_data.get("charge"),
            objective_zone=colors_data.get("objective_zone"),
            wall=colors_data.get("wall"),
            objective=colors_data["objective"]
        )

        # Parse objective zones - validate required section exists
        if "objective_zones" not in config_data:
            raise KeyError("Board config missing required 'objective_zones' section")
        objective_zones = []
        for zone_data in config_data["objective_zones"]:
            zone = ObjectiveZone(
                id=zone_data["id"],
                hexes=zone_data["hexes"]
            )
            objective_zones.append(zone)

        # Parse walls - validate required section exists
        if "walls" not in config_data:
            raise KeyError("Board config missing required 'walls' section")
        walls = []
        for wall_data in config_data["walls"]:
            wall = Wall(
                id=wall_data["id"],
                start=wall_data["start"],
                end=wall_data["end"],
                thickness=wall_data.get("thickness")
            )
            walls.append(wall)

        # Parse display config - validate required section exists
        if "display" not in config_data:
            raise KeyError("Board config missing required 'display' section")
        display_data = config_data["display"]
        
        # Validate all required display fields
        required_display = ["resolution", "autoDensity", "antialias", "forceCanvas", 
                           "icon_scale", "eligible_outline_width", "eligible_outline_alpha",
                           "hp_bar_width_ratio", "hp_bar_height", "hp_bar_y_offset_ratio",
                           "unit_circle_radius_ratio", "unit_text_size"]
        
        for display_key in required_display:
            if display_key not in display_data:
                raise KeyError(f"Display config missing required field '{display_key}'")
        
        display = DisplayConfig(
            resolution=display_data["resolution"],
            auto_density=display_data["autoDensity"],
            antialias=display_data["antialias"],
            force_canvas=display_data["forceCanvas"],
            icon_scale=display_data["icon_scale"],
            eligible_outline_width=display_data["eligible_outline_width"],
            eligible_outline_alpha=display_data["eligible_outline_alpha"],
            hp_bar_width_ratio=display_data["hp_bar_width_ratio"],
            hp_bar_height=display_data["hp_bar_height"],
            hp_bar_y_offset_ratio=display_data["hp_bar_y_offset_ratio"],
            unit_circle_radius_ratio=display_data["unit_circle_radius_ratio"],
            unit_text_size=display_data["unit_text_size"],
            selected_border_width=display_data["selected_border_width"],
            charge_target_border_width=display_data["charge_target_border_width"],
            default_border_width=display_data["default_border_width"],
            canvas_border=display_data["canvas_border"],
            right_column_bottom_offset=display_data["right_column_bottom_offset"]
        )

        return BoardConfig(
            cols=config_data["cols"],
            rows=config_data["rows"],
            hex_radius=config_data["hex_radius"],
            margin=config_data["margin"],
            wall_hexes=config_data["wall_hexes"],
            objective_hexes=config_data["objective_hexes"],
            colors=colors,
            objective_zones=objective_zones,
            walls=walls,
            display=display
        )

    def _build_game_config(self, game_data: Dict[str, Any]) -> GameConfig:
        """Build GameConfig object from JSON data"""
        # Parse game rules - validate required section
        if "game_rules" not in game_data:
            raise KeyError("Game config missing required 'game_rules' section")
        rules_data = game_data["game_rules"]
        
        # Validate required game rules fields
        required_rules = ["max_turns", "turn_limit_penalty", "max_units_per_player", "board_size"]
        for rule_key in required_rules:
            if rule_key not in rules_data:
                raise KeyError(f"Game rules missing required field '{rule_key}'")
        
        game_rules = GameRules(
            max_turns=rules_data["max_turns"],
            turn_limit_penalty=rules_data["turn_limit_penalty"],
            max_units_per_player=rules_data["max_units_per_player"],
            board_size=tuple(rules_data["board_size"])
        )

        # Parse gameplay config - validate required section
        if "gameplay" not in game_data:
            raise KeyError("Game config missing required 'gameplay' section")
        gameplay_data = game_data["gameplay"]
        
        required_gameplay = ["phase_order", "simultaneous_actions", "auto_end_turn"]
        for gameplay_key in required_gameplay:
            if gameplay_key not in gameplay_data:
                raise KeyError(f"Gameplay config missing required field '{gameplay_key}'")
        
        gameplay = GameplayConfig(
            phase_order=gameplay_data["phase_order"],
            simultaneous_actions=gameplay_data["simultaneous_actions"],
            auto_end_turn=gameplay_data["auto_end_turn"]
        )

        # Parse AI behavior config - validate required section
        if "ai_behavior" not in game_data:
            raise KeyError("Game config missing required 'ai_behavior' section")
        ai_data = game_data["ai_behavior"]
        
        required_ai = ["timeout_ms", "retries", "fallback_action"]
        for ai_key in required_ai:
            if ai_key not in ai_data:
                raise KeyError(f"AI behavior config missing required field '{ai_key}'")
        
        ai_behavior = AIBehaviorConfig(
            timeout_ms=ai_data["timeout_ms"],
            retries=ai_data["retries"],
            fallback_action=ai_data["fallback_action"]
        )

        # Parse scoring config - validate required section
        if "scoring" not in game_data:
            raise KeyError("Game config missing required 'scoring' section")
        scoring_data = game_data["scoring"]
        
        required_scoring = ["win_bonus", "lose_penalty", "survival_bonus_per_turn"]
        for scoring_key in required_scoring:
            if scoring_key not in scoring_data:
                raise KeyError(f"Scoring config missing required field '{scoring_key}'")
        
        scoring = ScoringConfig(
            win_bonus=scoring_data["win_bonus"],
            lose_penalty=scoring_data["lose_penalty"],
            survival_bonus_per_turn=scoring_data["survival_bonus_per_turn"]
        )

        return GameConfig(
            game_rules=game_rules,
            gameplay=gameplay,
            ai_behavior=ai_behavior,
            scoring=scoring
        )

    # === PROPERTY GETTERS (EXACT from TypeScript) ===

    @property
    def max_turns(self) -> int:
        """EXACT mirror of maxTurns getter from TypeScript"""
        if not self.game_config:
            raise RuntimeError("Game config not loaded - cannot access max_turns")
        return self.game_config.game_rules.max_turns

    @property
    def board_size(self) -> Tuple[int, int]:
        """EXACT mirror of boardSize getter from TypeScript"""
        if not self.game_config:
            raise RuntimeError("Game config not loaded - cannot access board_size")
        return self.game_config.game_rules.board_size

    @property
    def turn_penalty(self) -> float:
        """EXACT mirror of turnPenalty getter from TypeScript"""
        if not self.game_config:
            raise RuntimeError("Game config not loaded - cannot access turn_penalty")
        return self.game_config.game_rules.turn_limit_penalty

    # === UTILITY METHODS ===

    def reload_configs(self) -> None:
        """Reload configurations from disk"""
        self._load_configs()

    def get_hex_radius(self) -> float:
        """Get hex radius for calculations"""
        if not self.board_config:
            raise RuntimeError("Board config not loaded - cannot access hex_radius")
        return self.board_config.hex_radius

    def get_board_dimensions(self) -> Tuple[int, int]:
        """Get board dimensions (cols, rows)"""
        if not self.board_config:
            raise RuntimeError("Board config not loaded - cannot access board dimensions")
        return (self.board_config.cols, self.board_config.rows)

    def get_wall_hexes(self) -> List[Tuple[int, int]]:
        """Get wall hexes coordinates"""
        if not self.board_config:
            raise RuntimeError("Board config not loaded - cannot access wall_hexes")
        return self.board_config.wall_hexes

    def get_objective_hexes(self) -> List[Tuple[int, int]]:
        """Get objective hexes coordinates"""
        if not self.board_config:
            raise RuntimeError("Board config not loaded - cannot access objective_hexes")
        return self.board_config.objective_hexes

    def get_player_color(self, player: int) -> str:
        """Get color for specific player"""
        if not self.board_config:
            raise RuntimeError("Board config not loaded - cannot access player colors")
        
        return (self.board_config.colors.player_0 if player == 0 
                else self.board_config.colors.player_1)

    def is_valid_position(self, col: int, row: int) -> bool:
        """Check if position is within board bounds"""
        if not self.board_config:
            return False
        
        return (0 <= col < self.board_config.cols and 
                0 <= row < self.board_config.rows)

    def is_wall_hex(self, col: int, row: int) -> bool:
        """Check if position is a wall hex"""
        return (col, row) in self.get_wall_hexes()

    def is_objective_hex(self, col: int, row: int) -> bool:
        """Check if position is an objective hex"""
        return (col, row) in self.get_objective_hexes()

    # === EXPOSED FUNCTIONS (EXACT from TypeScript return) ===

    def get_config_data(self) -> Dict[str, Any]:
        """
        Return all configuration data (EXACT mirror of TypeScript useGameConfig return).
        This replaces the TypeScript hook's return statement with EXACT same properties.
        """
        return {
            "boardConfig": self.board_config,
            "gameConfig": self.game_config,
            "loading": self.loading,
            "error": self.error,
            "maxTurns": self.max_turns,
            "boardSize": self.board_size,
            "turnPenalty": self.turn_penalty
        }


# === FACTORY FUNCTION (Mirror of TypeScript hook usage) ===

def use_game_config(board_config_name: str, 
                   config_path: str) -> Dict[str, Any]:
    """
    Factory function that mirrors the TypeScript useGameConfig hook.
    Returns the same configuration data that the TypeScript hook returns.
    """
    config_manager = UseGameConfig(board_config_name, config_path)
    return config_manager.get_config_data()


# === TRAINING INTEGRATION CLASS ===

class TrainingGameConfig(UseGameConfig):
    """
    Extended version of UseGameConfig optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, board_config_name: str, 
                 config_path: str,
                 cache_configs: bool):
        self.cache_configs = cache_configs
        self._config_cache: Dict[str, Any] = {}
        
        super().__init__(board_config_name, config_path)

    def get_training_config(self) -> Dict[str, Any]:
        """Get configuration optimized for training"""
        if self.cache_configs and "training_config" in self._config_cache:
            return self._config_cache["training_config"]

        config = {
            "board_size": self.board_size,
            "max_turns": self.max_turns,
            "turn_penalty": self.turn_penalty,
            "hex_radius": self.get_hex_radius(),
            "wall_hexes": self.get_wall_hexes(),
            "objective_hexes": self.get_objective_hexes(),
            "valid_positions": self._get_all_valid_positions(),
            "colors": {
                "player_0": self.get_player_color(0),
                "player_1": self.get_player_color(1)
            }
        }

        if self.cache_configs:
            self._config_cache["training_config"] = config

        return config

    def _get_all_valid_positions(self) -> List[Tuple[int, int]]:
        """Get all valid board positions for training"""
        valid_positions = []
        cols, rows = self.get_board_dimensions()
        
        for col in range(cols):
            for row in range(rows):
                if (self.is_valid_position(col, row) and 
                    not self.is_wall_hex(col, row)):
                    valid_positions.append((col, row))
        
        return valid_positions

    def validate_training_scenario(self, scenario: Dict[str, Any]) -> bool:
        """Validate a training scenario against configuration"""
        # Check board size compatibility
        board_size = scenario.get("board", {}).get("size", self.board_size)
        if board_size != self.board_size:
            return False

        # Check unit positions are valid
        for unit in scenario.get("units", []):
            col, row = unit.get("col", -1), unit.get("row", -1)
            if not self.is_valid_position(col, row) or self.is_wall_hex(col, row):
                return False

        return True

    def clear_cache(self) -> None:
        """Clear configuration cache"""
        self._config_cache.clear()