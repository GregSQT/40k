#!/usr/bin/env python3
"""
ai/game_controller.py
EXACT Python mirror of frontend/src/components/GameController.tsx
Master orchestrator component - ALL features preserved.

This is the complete functional equivalent of the PvP GameController system.
"""

from typing import Dict, List, Any, Optional, Callable
import copy
import time
from dataclasses import dataclass

# Import all our Python mirrors
from use_game_state import use_game_state, TrainingGameState
from use_game_actions import use_game_actions, TrainingGameActions
from use_phase_transition import use_phase_transition, TrainingPhaseTransition
from use_game_log import use_game_log, TrainingGameLog
from use_game_config import use_game_config, TrainingGameConfig

@dataclass
class GameControllerConfig:
    """Configuration for GameController"""
    initial_units: Optional[List[Dict[str, Any]]] = None
    game_mode: str = "pvp"  # "pvp", "pve", "training"
    board_config_name: str = "default"
    config_path: str = "config"
    max_turns: int = 100
    enable_ai_player: bool = False
    training_mode: bool = False

class GameController:
    """
    EXACT Python mirror of GameController TypeScript component.
    Master orchestrator for entire game system with ALL features preserved.
    """
    
    def __init__(self, config: GameControllerConfig):
        """Initialize with same responsibilities as TypeScript GameController"""
        self.config = config
        
        # Initialize game units (EXACT from TypeScript)
        self.game_units = self._initialize_units()
        
        # Track UI state (mirrors TypeScript state)
        self.clicked_unit_id: Optional[int] = None
        self.player0_collapsed = False
        self.player1_collapsed = False
        self.log_available_height = 220
        
        # Initialize all hooks/managers (EXACT from TypeScript)
        self._initialize_hooks()
        
        # Game loop state
        self.is_running = False
        self.current_step = 0

    def _initialize_units(self) -> List[Dict[str, Any]]:
        """
        EXACT mirror of unit initialization from TypeScript.
        Generate default units if none provided.
        """
        if self.config.initial_units:
            return copy.deepcopy(self.config.initial_units)
        
        # Default units (EXACT from TypeScript GameController)
        default_units = [
            {
                "id": 0,
                "name": "P-I",
                "unit_type": "Intercessor",
                "player": 0,
                "col": 23,
                "row": 12,
                "color": 0x244488,
                "HP_MAX": 2,
                "HP_LEFT": 2,
                "MOVE": 6,
                "RNG_RNG": 24,
                "RNG_NB": 2,
                "RNG_DMG": 1,
                "CC_RNG": 1,
                "CC_NB": 1,
                "CC_DMG": 1,
                "ICON": "👨‍🚀",
                "SHOOT_LEFT": 2,
                "has_charged_this_turn": False
            },
            {
                "id": 1,
                "name": "P-A",
                "unit_type": "AssaultIntercessor",
                "player": 0,
                "col": 1,
                "row": 12,
                "color": 0xff3333,
                "HP_MAX": 2,
                "HP_LEFT": 2,
                "MOVE": 6,
                "RNG_RNG": 12,
                "RNG_NB": 1,
                "RNG_DMG": 1,
                "CC_RNG": 1,
                "CC_NB": 2,
                "CC_DMG": 1,
                "ICON": "⚔️",
                "SHOOT_LEFT": 1,
                "has_charged_this_turn": False
            },
            {
                "id": 2,
                "name": "A-T",
                "unit_type": "Termagant",
                "player": 1,
                "col": 0,
                "row": 5,
                "color": 0x882222,
                "HP_MAX": 1,
                "HP_LEFT": 1,
                "MOVE": 6,
                "RNG_RNG": 18,
                "RNG_NB": 1,
                "RNG_DMG": 1,
                "CC_RNG": 1,
                "CC_NB": 1,
                "CC_DMG": 1,
                "ICON": "🐛",
                "SHOOT_LEFT": 1,
                "has_charged_this_turn": False
            },
            {
                "id": 3,
                "name": "A-H",
                "unit_type": "Hormagaunt",
                "player": 1,
                "col": 22,
                "row": 3,
                "color": 0x6633cc,
                "HP_MAX": 1,
                "HP_LEFT": 1,
                "MOVE": 8,
                "RNG_RNG": 0,
                "RNG_NB": 0,
                "RNG_DMG": 0,
                "CC_RNG": 1,
                "CC_NB": 2,
                "CC_DMG": 1,
                "ICON": "🦂",
                "SHOOT_LEFT": 0,
                "has_charged_this_turn": False
            }
        ]
        
        return default_units

    def _initialize_hooks(self) -> None:
        """
        EXACT mirror of hooks initialization from TypeScript.
        Initialize all custom hooks with proper integration.
        """
        # Initialize game configuration (EXACT from TypeScript)
        config_data = use_game_config(
            board_config_name=self.config.board_config_name,
            config_path=self.config.config_path
        )
        self.board_config = config_data["board_config"]
        self.game_config = config_data["game_config"]
        self.config_loading = config_data["loading"]
        self.config_error = config_data["error"]
        
        # Initialize game state with custom hook (EXACT from TypeScript)
        game_state_data = use_game_state(self.game_units)
        self.game_state = game_state_data["game_state"]
        self.move_preview = game_state_data["move_preview"]
        self.attack_preview = game_state_data["attack_preview"]
        self.shooting_phase_state = game_state_data["shooting_phase_state"]
        self.charge_roll_popup = game_state_data["charge_roll_popup"]
        self.state_actions = game_state_data["actions"]
        self.state_manager = game_state_data["manager"]
        
        # Initialize game log hook (EXACT from TypeScript)
        log_data = use_game_log()
        self.game_log = log_data
        
        # Initialize replay logger integration for training
        self.replay_logger = None
        try:
            from ai.game_replay_logger import GameReplayLogger
            self.replay_logger = GameReplayLogger(self)
        except ImportError:
            if not hasattr(self, 'quiet') or not self.quiet:
                print("⚠️ GameReplayLogger not available for GameController")
        
        # Set up game actions with game log (EXACT from TypeScript)
        actions_data = use_game_actions(
            game_state=self.game_state,
            move_preview=self.move_preview,
            attack_preview=self.attack_preview,
            shooting_phase_state=self.shooting_phase_state,
            board_config=self.board_config,
            actions=self.state_actions,
            game_log=self.game_log
        )
        self.game_actions = actions_data
        
        # Initialize phase transition system (EXACT from TypeScript)
        phase_data = use_phase_transition(
            game_state=self.game_state,
            board_config=self.board_config,
            is_unit_eligible_func=self.game_actions["is_unit_eligible"],
            actions=self.state_actions
        )
        self.phase_transitions = phase_data

    # === CORE GAME METHODS (EXACT from TypeScript patterns) ===

    def start_game(self) -> None:
        """Start the game loop"""
        self.is_running = True
        self.current_step = 0
        
        # Log game start (EXACT from TypeScript)
        self.game_log["logTurnStart"](1)
        self.game_log["logPhaseChange"]("move", 0, 1)
        
        # Capture initial state for replay
        if self.replay_logger:
            self.replay_logger.capture_initial_state()

    def stop_game(self) -> None:
        """Stop the game loop"""
        self.is_running = False

    def connect_replay_logger(self, replay_logger) -> None:
        """Connect external replay logger (for gym integration)"""
        self.replay_logger = replay_logger
        if hasattr(replay_logger, 'capture_initial_state'):
            replay_logger.capture_initial_state()

    def step(self) -> bool:
        """
        Execute one game step.
        Returns True if game continues, False if game over.
        """
        if not self.is_running:
            return False
        
        # Update state from managers
        self._update_state()
        
        # Process automatic phase transitions (EXACT from TypeScript)
        self.phase_transitions["process_phase_transitions"]()
        self.phase_transitions["process_alternating_combat_player_switch"]()
        
        # Check for game over conditions
        if self._check_game_over():
            self.stop_game()
            return False
        
        self.current_step += 1
        return True

    def _update_state(self) -> None:
        """Update all state references from managers"""
        self.game_state = self.state_manager.get_game_state()
        self.move_preview = self.state_manager.get_move_preview()
        self.attack_preview = self.state_manager.get_attack_preview()
        self.shooting_phase_state = self.state_manager.get_shooting_phase_state()
        self.charge_roll_popup = self.state_manager.get_charge_roll_popup()

    def _check_game_over(self) -> bool:
        """Check if game is over"""
        return self.state_manager.is_game_over()

    # === UI STATE METHODS (EXACT from TypeScript) ===

    def set_clicked_unit_id(self, unit_id: Optional[int]) -> None:
        """EXACT mirror of setClickedUnitId from TypeScript"""
        self.clicked_unit_id = unit_id

    def set_player0_collapsed(self, collapsed: bool) -> None:
        """EXACT mirror of setPlayer0Collapsed from TypeScript"""
        self.player0_collapsed = collapsed

    def set_player1_collapsed(self, collapsed: bool) -> None:
        """EXACT mirror of setPlayer1Collapsed from TypeScript"""
        self.player1_collapsed = collapsed

    def set_log_available_height(self, height: int) -> None:
        """EXACT mirror of setLogAvailableHeight from TypeScript"""
        self.log_available_height = height

    # === GAME STATE ACCESSORS (EXACT from TypeScript patterns) ===

    def get_current_player(self) -> int:
        """Get current player"""
        return self.game_state["current_player"]

    def get_current_phase(self) -> str:
        """Get current phase"""
        return self.game_state["phase"]

    def get_current_turn(self) -> int:
        """Get current turn"""
        return self.game_state["current_turn"]

    def get_selected_unit_id(self) -> Optional[int]:
        """Get selected unit ID"""
        return self.game_state["selected_unit_id"]

    def get_units(self) -> List[Dict[str, Any]]:
        """Get all units"""
        return copy.deepcopy(self.game_state["units"])

    def get_current_player_units(self) -> List[Dict[str, Any]]:
        """Get current player's units"""
        return self.state_manager.get_current_player_units()

    def get_enemy_units(self) -> List[Dict[str, Any]]:
        """Get enemy units"""
        return self.state_manager.get_enemy_units()

    def get_winner(self) -> Optional[int]:
        """Get winner if game is over"""
        return self.state_manager.get_winner()

    # === ACTION FORWARDING METHODS (EXACT from TypeScript) ===

    def select_unit(self, unit_id: Optional[int]) -> bool:
        """Select a unit"""
        return self.game_actions["handle_unit_selection"](unit_id)

    def move_unit(self, unit_id: int, col: int, row: int) -> bool:
        """Move a unit"""
        return self.game_actions["direct_move"](unit_id, col, row)

    def shoot_unit(self, shooter_id: int, target_id: int) -> bool:
        """Shoot at target"""
        return self.game_actions["handle_shoot"](shooter_id, target_id)

    def charge_unit(self, charger_id: int, target_id: int) -> bool:
        """Charge at target"""
        return self.game_actions["handle_charge"](charger_id, target_id)

    def combat_attack(self, attacker_id: int, target_id: int) -> bool:
        """Attack in combat"""
        return self.game_actions["handle_combat_attack"](attacker_id, target_id)

    # === TRAINING INTEGRATION METHODS ===

    def get_valid_actions(self) -> List[Dict[str, Any]]:
        """Get all valid actions for current game state"""
        valid_actions = []
        
        current_player = self.get_current_player()
        current_phase = self.get_current_phase()
        
        # Get eligible units
        player_units = self.get_current_player_units()
        
        for unit in player_units:
            if self.game_actions["is_unit_eligible"](unit):
                unit_id = unit["id"]
                
                if current_phase == "move":
                    # Add movement actions
                    valid_moves = self.game_actions["get_valid_moves"](unit_id)
                    for move in valid_moves:
                        valid_actions.append({
                            "type": "move",
                            "unit_id": unit_id,
                            "col": move["col"],
                            "row": move["row"]
                        })
                
                elif current_phase == "shoot":
                    # Add shooting actions
                    valid_targets = self.game_actions["get_valid_shooting_targets"](unit_id)
                    for target_id in valid_targets:
                        valid_actions.append({
                            "type": "shoot",
                            "unit_id": unit_id,
                            "target_id": target_id
                        })
                
                elif current_phase == "charge":
                    # Add charge actions
                    valid_targets = self.game_actions["get_valid_charge_targets"](unit_id)
                    for target_id in valid_targets:
                        valid_actions.append({
                            "type": "charge",
                            "unit_id": unit_id,
                            "target_id": target_id
                        })
                
                elif current_phase == "combat":
                    # Add combat actions
                    valid_targets = self.game_actions["get_valid_combat_targets"](unit_id)
                    for target_id in valid_targets:
                        valid_actions.append({
                            "type": "combat",
                            "unit_id": unit_id,
                            "target_id": target_id
                        })
        
        return valid_actions

    def execute_action(self, unit_id: int, action: Dict[str, Any]) -> bool:
        """Execute a game action for specified unit"""
        action_type = action.get("type")
        
        if action_type == "move":
            return self.move_unit(unit_id, action["col"], action["row"])
        elif action_type == "shoot":
            return self.shoot_unit(unit_id, action["target_id"])
        elif action_type == "charge":
            return self.charge_unit(unit_id, action["target_id"])
        elif action_type == "combat":
            return self.combat_attack(unit_id, action["target_id"])
        else:
            return False

    def get_game_state_for_training(self) -> Dict[str, Any]:
        """Get compressed game state for training"""
        return {
            "units": self.get_units(),
            "current_player": self.get_current_player(),
            "phase": self.get_current_phase(),
            "turn": self.get_current_turn(),
            "selected_unit_id": self.get_selected_unit_id(),
            "units_moved": copy.copy(self.game_state["units_moved"]),
            "units_charged": copy.copy(self.game_state["units_charged"]),
            "units_attacked": copy.copy(self.game_state["units_attacked"]),
            "units_fled": copy.copy(self.game_state["units_fled"]),
            "combat_sub_phase": self.game_state.get("combat_sub_phase"),
            "combat_active_player": self.game_state.get("combat_active_player"),
            "is_game_over": self.is_game_over(),
            "winner": self.get_winner()
        }

    def is_game_over(self) -> bool:
        """Check if game is over"""
        return self._check_game_over()

    def reset_game(self, new_units: Optional[List[Dict[str, Any]]] = None) -> None:
        """Reset game to initial state"""
        if new_units:
            self.game_units = copy.deepcopy(new_units)
        else:
            self.game_units = self._initialize_units()
        
        # Reinitialize all hooks
        self._initialize_hooks()
        
        # Reset game state
        self.is_running = False
        self.current_step = 0
        self.clicked_unit_id = None


# === FACTORY FUNCTION (Mirror of TypeScript component usage) ===

def create_game_controller(config: GameControllerConfig) -> GameController:
    """
    Factory function that mirrors TypeScript GameController component instantiation.
    Returns a fully initialized GameController.
    """
    return GameController(config)


# === TRAINING INTEGRATION CLASS ===

class TrainingGameController(GameController):
    """
    Extended version of GameController optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, config: GameControllerConfig):
        # Force training mode
        config.training_mode = True
        super().__init__(config)
        
        # Training-specific state
        self.episode_count = 0
        self.total_steps = 0
        self.episode_rewards = []
        self.training_metrics = {
            "episodes_completed": 0,
            "total_actions": 0,
            "wins_by_player": {0: 0, 1: 0},
            "average_episode_length": 0.0
        }

    def _initialize_hooks(self) -> None:
        """Override to use training-optimized hooks"""
        # Use training versions of hooks for better performance
        
        # Initialize game configuration - use existing working config_loader
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        self.board_config = config_loader.get_board_config()
        self.game_config = config_loader.get_game_config()
        
        # Maintain compatibility with TrainingGameConfig cache
        self.config_manager = None  # Skip problematic TrainingGameConfig for now
        
        # Initialize training game state
        self.state_manager = TrainingGameState(self.game_units, max_history=50)
        game_state_data = {
            "game_state": self.state_manager.get_game_state(),
            "move_preview": self.state_manager.get_move_preview(),
            "attack_preview": self.state_manager.get_attack_preview(),
            "shooting_phase_state": self.state_manager.get_shooting_phase_state(),
            "charge_roll_popup": self.state_manager.get_charge_roll_popup(),
            "actions": self.state_manager.get_actions()
        }
        
        self.game_state = game_state_data["game_state"]
        self.move_preview = game_state_data["move_preview"]
        self.attack_preview = game_state_data["attack_preview"]
        self.shooting_phase_state = game_state_data["shooting_phase_state"]
        self.charge_roll_popup = game_state_data["charge_roll_popup"]
        self.state_actions = game_state_data["actions"]
        
        # Initialize training game log
        self.log_manager = TrainingGameLog(max_events=500)
        self.game_log = self.log_manager  # Pass the object, not the functions dict
        
        # Initialize replay logger for training
        try:
            from ai.game_replay_logger import GameReplayLogger
            self.replay_logger = GameReplayLogger(self)
        except ImportError:
            if not hasattr(self, 'quiet') or not self.quiet:
                print("⚠️ GameReplayLogger not available for training")
            self.replay_logger = None
        
        # Initialize training game actions
        self.actions_manager = TrainingGameActions(
            game_state=self.game_state,
            move_preview=self.move_preview,
            attack_preview=self.attack_preview,
            shooting_phase_state=self.shooting_phase_state,
            board_config=self.board_config,
            actions=self.state_actions,
            game_log=self.game_log
        )
        self.game_actions = self.actions_manager.get_action_functions()
        
        # Initialize training phase transitions
        self.phase_manager = TrainingPhaseTransition(
            game_state=self.game_state,
            board_config=self.board_config,
            is_unit_eligible_func=self.game_actions["is_unit_eligible"],
            actions=self.state_actions
        )
        self.phase_transitions = self.phase_manager.get_transition_functions()

        # Add phase property for training compatibility
        self._current_phase = self.game_state.get("phase", "move")

    def connect_replay_logger(self, replay_logger):
        """Connect replay logger for GameReplayIntegration compatibility."""
        self.replay_logger = replay_logger
        self.game_logger = replay_logger

    @property
    def units(self) -> List[Dict[str, Any]]:
        """Units property for replay logger compatibility"""
        return self.get_units()

    def save_replay(self, filename: str, episode_reward: float = 0.0):
        """Custom save_replay method for TrainingGameController"""
        print(f"🔧 Controller save_replay called: {filename}")
        
        initial_units = []
        
        # Get units from controller and format them for replay
        units = self.get_units()
        print(f"🔧 Found {len(units)} units to save")
        
        for unit in units:
            replay_unit = {
                "id": unit.get("id"),
                "unit_type": unit.get("unit_type"),
                "player": unit.get("player"),
                "col": unit.get("col"),
                "row": unit.get("row"),
                "HP_MAX": unit.get("HP_MAX"),
                "hp_max": unit.get("HP_MAX"),
                "move": unit.get("MOVE"),
                "rng_rng": unit.get("RNG_RNG"),
                "rng_dmg": unit.get("RNG_DMG"),
                "cc_dmg": unit.get("CC_DMG"),
                "is_ranged": unit.get("RNG_RNG", 0) > 0,
                "is_melee": unit.get("CC_RNG", 0) > 0,
                "alive": unit.get("alive", True),
                "name": unit.get("name", f"{unit.get('unit_type', 'Unit')}_{unit.get('id', 0)}")
            }
            initial_units.append(replay_unit)
        
        # Create replay data structure
        replay_data = {
            "game_info": {
                "scenario": "training_episode",
                "ai_behavior": "phase_based",
                "total_turns": self.get_current_turn(),
                "winner": self.get_winner(),
            },
            "metadata": {
                "final_turn": self.get_current_turn(),
                "episode_reward": episode_reward,
                "format_version": "2.0",
                "replay_type": "training_enhanced"
            },
            "initial_state": {
                "units": initial_units,
                "board_size": self._get_board_size_from_config()
            },
            "combat_log": getattr(self.replay_logger, 'combat_log_entries', []) if self.replay_logger else [],
            "game_states": [],
            "episode_steps": 500,  # Default
            "episode_reward": episode_reward
        }
        
        print(f"🔧 Saving replay with {len(initial_units)} units in initial_state")
        
        # Save to file
        import os
        import json
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"🔧 Replay saved successfully to {filename}")
        return filename

    def _get_board_size_from_config(self) -> List[int]:
        """Get board size from config - no hardcoded fallback"""
        try:
            from config_loader import get_config_loader
            config = get_config_loader()
            board_cols, board_rows = config.get_board_size()
            return [board_cols, board_rows]
        except Exception as e:
            raise ValueError(f"Failed to load board size from config: {e}")

    @property
    def current_phase(self) -> str:
        """Get current phase - required for training system compatibility"""
        return self.get_current_phase()

    @property  
    def current_player(self) -> int:
        """Get current player - required for training system compatibility"""
        return self.get_current_player()

    @property
    def current_turn(self) -> int:
        """Get current turn - required for training system compatibility"""
        return self.get_current_turn()

    def can_unit_shoot_target(self, unit_id: int, target_id: int) -> bool:
        """Check if unit can shoot target"""
        unit = self.find_unit(unit_id)
        target = self.find_unit(target_id)
        if not unit or not target:
            return False
        
        # Basic range check
        distance = max(abs(unit["col"] - target["col"]), abs(unit["row"] - target["row"]))
        if "RNG_RNG" not in unit:
            raise KeyError(f"Unit missing required 'RNG_RNG' field: {unit.get('name', 'unknown')}")
        return distance <= unit["RNG_RNG"]

    def can_unit_charge_target(self, unit_id: int, target_id: int) -> bool:
        """Check if unit can charge target"""
        unit = self.find_unit(unit_id)
        target = self.find_unit(target_id)
        if not unit or not target:
            return False
        
        # Basic range check (1-12 hex charge range)
        distance = max(abs(unit["col"] - target["col"]), abs(unit["row"] - target["row"]))
        return 1 < distance <= 12

    def can_unit_attack_target(self, unit_id: int, target_id: int) -> bool:
        """Check if unit can attack target in combat"""
        unit = self.find_unit(unit_id)
        target = self.find_unit(target_id)
        if not unit or not target:
            return False
        
        # Basic adjacency check for combat
        distance = max(abs(unit["col"] - target["col"]), abs(unit["row"] - target["row"]))
        if "CC_RNG" not in unit:
            raise KeyError(f"Unit missing required 'CC_RNG' field: {unit.get('name', 'unknown')}")
        return distance <= unit["CC_RNG"]

    def find_unit(self, unit_id: int) -> Optional[Dict[str, Any]]:
        """Find unit by ID"""
        units = self.get_units()
        for unit in units:
            if unit["id"] == unit_id:
                return unit
        return None

    def get_valid_moves(self, unit_id: int) -> List[Dict[str, Any]]:
        """Get valid move positions for unit"""
        return self.game_actions.get("get_valid_moves", lambda x: [])(unit_id)

    def get_valid_shooting_targets(self, unit_id: int) -> List[int]:
        """Get valid shooting targets for unit"""
        return self.game_actions.get("get_valid_shooting_targets", lambda x: [])(unit_id)

    def get_valid_charge_targets(self, unit_id: int) -> List[int]:
        """Get valid charge targets for unit"""
        return self.game_actions.get("get_valid_charge_targets", lambda x: [])(unit_id)

    def get_valid_combat_targets(self, unit_id: int) -> List[int]:
        """Get valid combat targets for unit"""
        return self.game_actions.get("get_valid_combat_targets", lambda x: [])(unit_id)

    def advance_phase(self) -> None:
        """Advance to next phase or turn"""
        self.phase_transitions.get("process_phase_transitions", lambda: None)()

    def start_new_episode(self, scenario_units: Optional[List[Dict[str, Any]]] = None) -> None:
        """Start a new training episode"""
        if scenario_units:
            self.reset_game(scenario_units)
        else:
            self.reset_game()
        
        self.episode_count += 1
        self.episode_start_time = time.time()
        self.episode_step_count = 0
        
        # Reset training-specific state
        if hasattr(self.state_manager, 'reset_for_new_episode'):
            self.state_manager.reset_for_new_episode(self.game_units)
        if hasattr(self.log_manager, 'reset_for_new_episode'):
            self.log_manager.reset_for_new_episode()
        if hasattr(self.actions_manager, 'reset_for_new_episode'):
            self.actions_manager.reset_for_new_episode()
        if hasattr(self.phase_manager, 'reset_for_new_episode'):
            self.phase_manager.reset_for_new_episode()
        
        # Reset replay logger for new episode
        if self.replay_logger:
            self.replay_logger.capture_initial_state()
            # Set initial_game_state for SelectiveEpisodeTracker compatibility
            units = self.get_units()
            formatted_units = []
            for unit in units:
                formatted_units.append({
                    "id": unit.get("id"),
                    "unit_type": unit.get("unit_type"),
                    "player": unit.get("player"),
                    "col": unit.get("col"),
                    "row": unit.get("row"),
                    "hp_max": unit.get("HP_MAX"),
                    "move": unit.get("MOVE"),
                    "rng_rng": unit.get("RNG_RNG"),
                    "rng_dmg": unit.get("RNG_DMG"),
                    "cc_dmg": unit.get("CC_DMG"),
                    "is_ranged": unit.get("RNG_RNG", 0) > 0,
                    "is_melee": unit.get("CC_RNG", 0) > 0,
                    "alive": unit.get("alive", True)
                })
            # Get board size from config instead of hardcoding
            try:
                from config_loader import get_config_loader
                config = get_config_loader()
                board_cols, board_rows = config.get_board_size()
                board_size = [board_cols, board_rows]
            except Exception as e:
                raise ValueError(f"Failed to load board size from config: {e}")
            
            initial_state_data = {
                "units": formatted_units,
                "board_size": board_size
            }
            
            # Set both attributes that SelectiveEpisodeTracker might access
            self.replay_logger.initial_game_state = initial_state_data
            self.replay_logger.initial_state = initial_state_data
            
            print(f"🔧 Set initial_game_state with {len(formatted_units)} units")
            print(f"🔧 First unit: {formatted_units[0] if formatted_units else 'None'}")

    def end_episode(self, final_reward: float = 0.0) -> Dict[str, Any]:
        """End current episode and return metrics"""
        episode_duration = time.time() - getattr(self, 'episode_start_time', time.time())
        winner = self.get_winner()
        
        # Update training metrics
        self.training_metrics["episodes_completed"] += 1
        self.training_metrics["total_actions"] += self.episode_step_count
        
        if winner is not None:
            self.training_metrics["wins_by_player"][winner] += 1
        
        # Calculate average episode length
        total_episodes = self.training_metrics["episodes_completed"]
        self.training_metrics["average_episode_length"] = (
            self.training_metrics["total_actions"] / max(1, total_episodes)
        )
        
        episode_metrics = {
            "episode": self.episode_count,
            "steps": self.episode_step_count,
            "duration": episode_duration,
            "winner": winner,
            "final_reward": final_reward,
            "units_remaining": {
                0: len([u for u in self.get_units() if u["player"] == 0]),
                1: len([u for u in self.get_units() if u["player"] == 1])
            }
        }
        
        self.episode_rewards.append(final_reward)
        return episode_metrics

    def get_training_state(self) -> Dict[str, Any]:
        """Get state optimized for training algorithms"""
        return self.state_manager.get_compressed_state()

    def get_training_metrics(self) -> Dict[str, Any]:
        """Get comprehensive training metrics"""
        base_metrics = copy.deepcopy(self.training_metrics)
        
        # Add metrics from managers
        if hasattr(self.state_manager, 'get_training_metrics'):
            base_metrics.update(self.state_manager.get_training_metrics())
        if hasattr(self.log_manager, 'get_training_metrics'):
            base_metrics.update(self.log_manager.get_training_metrics())
        if hasattr(self.actions_manager, 'get_training_metrics'):
            base_metrics.update(self.actions_manager.get_training_metrics())
        if hasattr(self.phase_manager, 'get_training_metrics'):
            base_metrics.update(self.phase_manager.get_training_metrics())
        
        return base_metrics

    def step(self) -> bool:
        """Override step to include training metrics"""
        result = super().step()
        self.episode_step_count += 1
        self.total_steps += 1
        
        # Update phase tracking for training compatibility
        self._current_phase = self.game_state.get("phase", "move")
        
        return result

    def _update_state(self) -> None:
        """Override to include phase tracking"""
        super()._update_state()
        # Keep phase property in sync
        self._current_phase = self.game_state.get("phase", "move")