#!/usr/bin/env python3
"""
ai/game_controller.py - Training Game Controller with mirror architecture
EXACT Python mirror of PvP frontend GameController component
"""

import copy
import time
import numpy as np
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, field

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
    training_config_name: str = "default"

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

    # === CORE GAME METHODS (EXACT from TypeScript patterns) ===

    def start_game(self) -> None:
        """Start the game loop"""
        self.is_running = True
        self.current_step = 0
        
        # Log game start (EXACT from TypeScript)
        if self.game_log and "logTurnStart" in self.game_log:
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
        """Update cached values - all state references are already consistent"""
        # All components use the same game_state object, no synchronization needed
        self._current_phase = self.game_state.get("phase", "move")

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
        phase = self.game_state["phase"]
        return phase

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
        try:
            # CRITICAL FIX: Use direct_move which includes add_moved_unit call
            if "direct_move" in self.game_actions:
                self.game_actions["direct_move"](unit_id, col, row)
                success = True
            else:
                action_func = self.game_actions.get("handle_move")
                if action_func:
                    result = action_func(unit_id, col, row)
                    success = True if result is None else bool(result)
                else:
                    success = False
            
            return success
        except Exception as e:
            if not self.quiet:
                print(f"❌ move_unit error: unit={unit_id}, {e}")
            return False

    def shoot_unit(self, shooter_id: int, target_id: int) -> bool:
        """Shoot at target"""
        result = self.game_actions["handle_shoot"](shooter_id, target_id)
        return result if result is not None else False

    def charge_unit(self, charger_id: int, target_id: int) -> bool:
        """Charge at target"""
        result = self.game_actions["handle_charge"](charger_id, target_id)
        return result if result is not None else False

    def combat_attack(self, attacker_id: int, target_id: int) -> bool:
        """Attack in combat"""
        result = self.game_actions["handle_combat_attack"](attacker_id, target_id)
        return result if result is not None else False

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
    
    def __init__(self, config: GameControllerConfig, quiet: bool = False):
        # Force training mode
        config.training_mode = True
        
        # Training-specific state - SET BEFORE super().__init__()
        self.quiet = quiet
        super().__init__(config)
        self.episode_count = 0
        self.total_steps = 0
        self.episode_rewards = []
        self.training_metrics = {
            "episodes_completed": 0,
            "total_actions": 0,
            "wins_by_player": {0: 0, 1: 0},
            "average_episode_length": 0.0
        }
        
        # Training-specific properties from config - NO HARDCODED VALUES
        if not hasattr(config, 'training_config_name'):
            raise ValueError("GameControllerConfig missing required training_config_name for max_steps_per_episode")
        
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        self.max_steps_per_episode = config_loader.get_max_steps_per_episode(config.training_config_name)
        
        # Step count managed by game state - NO SEPARATE TRACKING
        if not hasattr(self, 'game_state'):
            raise RuntimeError("TrainingGameController missing required game_state for step tracking")

    def _get_gym_eligible_units(self) -> List[Dict]:
        """Delegate to use_game_actions.py for unit eligibility"""
        if not hasattr(self, 'game_actions') or 'get_eligible_units' not in self.game_actions:
            raise RuntimeError("TrainingGameController missing required game_actions.get_eligible_units")
        eligible_units = self.game_actions['get_eligible_units']()
        
        return eligible_units

    def _advance_gym_phase_or_turn(self) -> None:
        """Delegate to use_phase_transition.py for phase advancement"""
        if not hasattr(self, 'phase_transitions') or 'process_phase_transitions' not in self.phase_transitions:
            raise RuntimeError("TrainingGameController missing required phase_transitions.process_phase_transitions")
        self.phase_transitions['process_phase_transitions']()

    def _execute_gym_bot_turn(self) -> None:
        """Execute bot turn with proper logging through mirror architecture"""
        eligible_units = self._get_gym_eligible_units()
        bot_units = [u for u in eligible_units if u["player"] == 0]
        
        for bot_unit in bot_units:
            # Execute simple wait action for bot
            mirror_action = {"type": "wait"}
            self.execute_action(bot_unit["id"], mirror_action)
            
            # Log bot action using unified logging
            self._log_gym_action(bot_unit, mirror_action, 0.0)
            self._mark_gym_unit_as_acted(bot_unit)

    def _mark_gym_unit_as_acted(self, unit: Dict) -> None:
        """Delegate to use_game_state.py for unit state tracking"""
        current_phase = self.get_current_phase()
        unit_id = unit["id"]
        
        if not hasattr(self, 'state_actions'):
            raise RuntimeError("TrainingGameController missing required state_actions")
        
        if current_phase == "move" and 'add_moved_unit' in self.state_actions:
            self.state_actions['add_moved_unit'](unit_id)
        elif current_phase == "shoot" and 'add_moved_unit' in self.state_actions:
            self.state_actions['add_moved_unit'](unit_id)
        elif current_phase == "charge" and 'add_charged_unit' in self.state_actions:
            self.state_actions['add_charged_unit'](unit_id)
        elif current_phase == "combat" and 'add_attacked_unit' in self.state_actions:
            self.state_actions['add_attacked_unit'](unit_id)

    def _convert_gym_action_to_mirror(self, unit: Dict, action_type: int) -> Dict:
        """Convert gym action to mirror action format with phase validation"""
        current_phase = self.get_current_phase()
        
        if current_phase == "move":
            if action_type == 0:  # move_north
                return {"type": "move", "col": unit["col"], "row": unit["row"] - 1}
            elif action_type == 1:  # move_south
                return {"type": "move", "col": unit["col"], "row": unit["row"] + 1}
            elif action_type == 2:  # move_east
                return {"type": "move", "col": unit["col"] + 1, "row": unit["row"]}
            elif action_type == 3:  # move_west
                return {"type": "move", "col": unit["col"] - 1, "row": unit["row"]}
            else:
                return {"type": "wait"}
        elif current_phase == "shoot":
            if action_type == 4:  # shoot
                target = self._find_gym_shoot_target(unit)
                return {"type": "shoot", "target_id": target["id"]} if target else {"type": "wait"}
            else:
                return {"type": "wait"}
        elif current_phase == "charge":
            if action_type == 5:  # charge
                target = self._find_gym_charge_target(unit)
                return {"type": "charge", "target_id": target["id"]} if target else {"type": "wait"}
            else:
                return {"type": "wait"}
        elif current_phase == "combat":
            if action_type == 6:  # attack
                target = self._find_gym_combat_target(unit)
                return {"type": "combat", "target_id": target["id"]} if target else {"type": "wait"}
            else:
                return {"type": "wait"}
        else:
            return {"type": "wait"}

    def _find_gym_shoot_target(self, unit: Dict) -> Optional[Dict]:
        """Delegate to use_game_actions.py for target finding"""
        if not hasattr(self, 'game_actions'):
            raise RuntimeError("TrainingGameController missing required game_actions")
        if 'find_valid_shoot_targets' not in self.game_actions:
            raise RuntimeError("game_actions missing required find_valid_shoot_targets method")
        target_ids = self.game_actions['find_valid_shoot_targets'](unit["id"])
        return self.find_unit(target_ids[0]) if target_ids else None

    def _find_gym_charge_target(self, unit: Dict) -> Optional[Dict]:
        """Delegate to use_game_actions.py for target finding"""
        if not hasattr(self, 'game_actions'):
            raise RuntimeError("TrainingGameController missing required game_actions")
        if 'find_valid_charge_targets' not in self.game_actions:
            raise RuntimeError("game_actions missing required find_valid_charge_targets method")
        target_ids = self.game_actions['find_valid_charge_targets'](unit["id"])
        return self.find_unit(target_ids[0]) if target_ids else None

    def _find_gym_combat_target(self, unit: Dict) -> Optional[Dict]:
        """Delegate to use_game_actions.py for target finding"""
        if not hasattr(self, 'game_actions'):
            raise RuntimeError("TrainingGameController missing required game_actions")
        if 'find_valid_combat_targets' not in self.game_actions:
            raise RuntimeError("game_actions missing required find_valid_combat_targets method")
        target_ids = self.game_actions['find_valid_combat_targets'](unit["id"])
        return self.find_unit(target_ids[0]) if target_ids else None

    def _log_gym_action(self, acting_unit: Dict, mirror_action: Dict, reward: float) -> None:
        """Log action using unified logging system"""
        try:
            from shared.gameLogStructure import log_unified_action
            current_turn = self.get_current_turn()
            current_phase = self.get_current_phase()
            
            # Find target unit if target_id exists
            target_unit = None
            target_id = mirror_action.get("target_id")
            if target_id:
                all_units = self.get_units()
                for unit in all_units:
                    if unit["id"] == target_id:
                        target_unit = unit
                        break
            
            # Use gym environment reference if available
            env = getattr(self, 'gym_env', self)
            
            log_unified_action(
                env=env,
                action_type=mirror_action["type"],
                acting_unit=acting_unit,
                target_unit=target_unit,
                reward=reward,
                phase=current_phase,
                turn_number=current_turn
            )
        except Exception as e:
            if not self.quiet:
                print(f"❌ Gym action logging failed: {e}")

    def _get_gym_obs(self) -> np.ndarray:
        """Get gymnasium observation - delegates to gym environment"""
        if not hasattr(self, 'gym_env'):
            raise RuntimeError("TrainingGameController not connected to gym environment")
        return self.gym_env._get_obs()

    def _get_gym_info(self) -> Dict:
        """Get gymnasium info - delegates to gym environment"""
        if not hasattr(self, 'gym_env'):
            raise RuntimeError("TrainingGameController not connected to gym environment")
        return self.gym_env._get_info()

    def _calculate_gym_reward(self, acting_unit: Dict, mirror_action: Dict, success: bool) -> float:
        """Calculate reward - delegates to gym environment"""
        if not hasattr(self, 'gym_env'):
            raise RuntimeError("TrainingGameController not connected to gym environment")
        return self.gym_env._calculate_reward(acting_unit, mirror_action, success)

    def _get_gym_penalty_reward(self) -> float:
        """Get penalty reward - delegates to gym environment"""
        if not hasattr(self, 'gym_env'):
            raise RuntimeError("TrainingGameController not connected to gym environment")
        return self.gym_env._get_small_penalty_reward()

    def connect_gym_env(self, gym_env) -> None:
        """Connect gym environment for observation/reward delegation"""
        self.gym_env = gym_env

    def _get_current_step_count(self) -> int:
        """Get current step count from game state - NO SEPARATE TRACKING"""
        if 'episode_step_count' not in self.game_state:
            # Initialize if not present
            if not hasattr(self, 'state_actions') or 'set_episode_step_count' not in self.state_actions:
                raise RuntimeError("state_actions missing required set_episode_step_count method")
            self.state_actions['set_episode_step_count'](0)
        return self.game_state['episode_step_count']

    def _increment_step_count(self) -> None:
        """Increment step count in game state - delegates to use_game_state.py"""
        if not hasattr(self, 'state_actions') or 'increment_episode_step_count' not in self.state_actions:
            raise RuntimeError("state_actions missing required increment_episode_step_count method")
        self.state_actions['increment_episode_step_count']()

    def execute_gym_action(self, action: int) -> tuple:
        """
        Execute gymnasium action and return (obs, reward, terminated, truncated, info).
        ARCHITECTURAL COMPLIANCE: All game logic delegated to use_*.py mirror files.
        """
        # Check game over conditions
        if self.is_game_over():
            return self._get_gym_obs(), 0.0, True, False, self._get_gym_info()
        
        # Check step limit using game state tracking - NO SEPARATE STEP COUNTER
        current_step = self._get_current_step_count()
        if current_step >= self.max_steps_per_episode:
            return self._get_gym_obs(), 0.0, True, False, self._get_gym_info()
        
        # Increment step count in game state
        self._increment_step_count()
        
        # Get eligible units using mirror architecture
        eligible_units = self._get_gym_eligible_units()
        current_player = self.get_current_player()
        
        if not eligible_units:
            # No eligible units, advance phase/turn using mirror architecture
            self._advance_gym_phase_or_turn()
            return self._get_gym_obs(), 0.0, False, False, self._get_gym_info()
        
       # Single-agent control: only P1 controlled through gym actions
        controlled_player = 1
        controlled_eligible_units = [u for u in eligible_units if u["player"] == controlled_player]

        # Always execute bot turn first when current player is P0 (bot starts episode/turn)
        if current_player == 0:
            self._execute_gym_bot_turn()
            # After bot turn, advance to controlled player (P1)
            self._advance_gym_phase_or_turn()
            return self._get_gym_obs(), 0.0, False, False, self._get_gym_info()
        
        # No controlled units eligible - advance until controlled player can act
        if not controlled_eligible_units:
            self._advance_gym_phase_or_turn()
            return self._get_gym_obs(), 0.0, False, False, self._get_gym_info()
        
        # Decode and execute P1 action
        unit_idx = action // 8
        action_type = action % 8
        
        if unit_idx >= len(controlled_eligible_units):
            self._advance_gym_phase_or_turn()
            reward = self._get_gym_penalty_reward()
            return self._get_gym_obs(), reward, False, False, self._get_gym_info()
        
        # Execute action through mirror architecture
        acting_unit = controlled_eligible_units[unit_idx]
        mirror_action = self._convert_gym_action_to_mirror(acting_unit, action_type)
        
        success = self.execute_action(acting_unit["id"], mirror_action)
        reward = self._calculate_gym_reward(acting_unit, mirror_action, success)
        
        # Log action using unified logging  
        if hasattr(self, '_log_gym_action'):
            self._log_gym_action(acting_unit, mirror_action, reward)
        
        # Mark unit as acted if successful
        if success:
            self._mark_gym_unit_as_acted(acting_unit)
        
        # Check if game ended
        terminated = self.is_game_over()
        
        return self._get_gym_obs(), reward, terminated, False, self._get_gym_info()

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
        
        # Initialize training game state - SINGLE SOURCE OF TRUTH
        self.state_manager = TrainingGameState(self.game_units, max_history=50)
        
        # CRITICAL: Store the SINGLE game_state object reference that ALL components will use
        self.game_state = self.state_manager.game_state
        self.state_actions = self.state_manager.get_actions()
        
        # Store other state references from the SAME manager
        self.move_preview = self.state_manager.move_preview
        self.attack_preview = self.state_manager.attack_preview  
        self.shooting_phase_state = self.state_manager.shooting_phase_state
        self.charge_roll_popup = self.state_manager.charge_roll_popup
        
        # Initialize training game log
        self.log_manager = TrainingGameLog(max_events=500)
        self.game_log = self.log_manager.get_log_functions()
        
        # Initialize replay logger for training - will be set by gym via connect_replay_logger
        self.replay_logger = None
        
        # Initialize training game actions - CRITICAL: Pass the SAME game_state object
        self.actions_manager = TrainingGameActions(
            game_state=self.game_state,  # Use controller's stored reference - ensures same object
            move_preview=self.move_preview,
            attack_preview=self.attack_preview,
            shooting_phase_state=self.shooting_phase_state,
            board_config=self.board_config,
            actions=self.state_actions,
            game_log=self.log_manager
        )
        self.game_actions = self.actions_manager.get_available_actions()
        
        # Initialize training phase transitions - CRITICAL: Pass controller's game_state directly
        self.phase_manager = TrainingPhaseTransition(
            game_state=self.game_state,  # Use controller's stored reference - ensures same object
            board_config=self.board_config,
            is_unit_eligible_func=self.game_actions["is_unit_eligible"],
            actions=self.state_actions
        )
        self.phase_transitions = self.phase_manager.get_transition_functions()
        
        # CRITICAL FIX: Ensure phase_manager always references the same object
        self.phase_manager.game_state = self.game_state  # Use controller's stored reference

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
        
        # If we have a replay_logger with captured initial state, use it
        if self.replay_logger and hasattr(self.replay_logger, 'save_replay'):
            # Ensure replay_logger has access to current controller state
            if hasattr(self.replay_logger, 'env'):
                self.replay_logger.env = self
            return self.replay_logger.save_replay(filename, episode_reward)
        
        # Fallback: manual save
        initial_units = []
        
        # Get units from controller and format them for replay
        units = self.get_units()
        
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
        
        # Save to file
        import os
        import json
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
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
        controller_id = id(self.game_state)
        phase_manager_id = id(self.phase_manager.game_state) 
        state_manager_id = id(self.state_manager.game_state)
        
        if controller_id != phase_manager_id or controller_id != state_manager_id:
            raise RuntimeError(f"OBJECT SYNC FAILED: Controller={controller_id}, Phase={phase_manager_id}, State={state_manager_id}")
        
        current_phase = self.get_current_phase()
        current_player = self.get_current_player()
        
        # Check if phase transition conditions are met
        if hasattr(self, 'phase_transitions'):
            phase_info = self.phase_transitions.get("get_phase_info", lambda: {})()
            try:
                self.phase_transitions.get("process_phase_transitions", lambda: None)()
            except Exception as e:
                pass
                
                # Force direct state change as fallback
                try:
                    print(f"    Testing FIXED state_actions call...")
                    old_phase = self.game_state.get("phase", "unknown")
                    self.state_actions["set_phase"]("shoot")
                    self.state_actions["reset_moved_units"]()
                    new_phase = self.game_state.get("phase", "unknown")
                    print(f"    FORCED call result: {old_phase} -> {new_phase}")
                        
                except Exception as e:
                    print(f"    EXCEPTION in forced transition: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Second test: Call transition_to_shoot
                try:
                    self.phase_transitions.get("transition_to_shoot", lambda: None)()
                    new_phase = self.get_current_phase()
                    print(f"    transition_to_shoot result: {new_phase}")
                except Exception as e:
                    print(f"    ERROR in forced transition: {e}")
        else:
            print(f"    ERROR: No phase_transitions available!")

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
