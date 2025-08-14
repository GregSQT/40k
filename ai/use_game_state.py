#!/usr/bin/env python3
"""
ai/use_game_state.py
EXACT Python mirror of frontend/src/hooks/useGameState.ts
Central state management system - ALL features preserved.

This is the complete functional equivalent of the PvP useGameState hook system.
"""

from typing import Dict, List, Any, Optional, Callable, Set, Tuple, Union
import copy
import time

class ChargeRollPopup:
    """EXACT mirror of ChargeRollPopup interface from TypeScript"""
    def __init__(self, unit_id: int, roll: int, too_low: bool, timestamp: float):
        self.unit_id = unit_id
        self.roll = roll
        self.too_low = too_low
        self.timestamp = timestamp

class MovePreview:
    """EXACT mirror of MovePreview interface from TypeScript"""
    def __init__(self, unit_id: int, start_col: int, start_row: int, 
                 end_col: int, end_row: int, path: List[Dict[str, int]]):
        self.unit_id = unit_id
        self.start_col = start_col
        self.start_row = start_row
        self.end_col = end_col
        self.end_row = end_row
        self.path = path

class AttackPreview:
    """EXACT mirror of AttackPreview interface from TypeScript"""
    def __init__(self, attacker_id: int, target_id: int, attack_type: str):
        self.attacker_id = attacker_id
        self.target_id = target_id
        self.attack_type = attack_type  # "shoot" or "combat"
        self.col = None  # Support TypeScript interface
        self.row = None  # Support TypeScript interface

class ShootingPhaseState:
    """EXACT mirror of ShootingPhaseState interface from TypeScript"""
    def __init__(self):
        self.active_shooters: List[int] = []
        self.current_shooter: Optional[int] = None
        self.single_shot_state: Optional[Dict[str, Any]] = None

class UseGameState:
    """
    EXACT Python mirror of useGameState TypeScript hook.
    Central game state management system with ALL features preserved.
    """
    
    def __init__(self, initial_units: List[Dict[str, Any]]):
        """Initialize with same parameters as TypeScript useGameState"""
        if not initial_units:
            raise ValueError("initial_units is required and cannot be empty")
        
        # Validate and process initial units (EXACT from TypeScript)
        processed_units = []
        for unit in initial_units:
            if "RNG_NB" not in unit:
                raise ValueError(f"unit.RNG_NB is required for unit: {unit}")
            if "name" not in unit:
                raise ValueError(f"unit.name is required for unit: {unit}")
            if unit["RNG_NB"] is None:
                raise ValueError(f"unit.RNG_NB cannot be None for unit: {unit}")
            
            processed_unit = copy.deepcopy(unit)
            processed_unit["SHOOT_LEFT"] = unit["RNG_NB"]
            processed_units.append(processed_unit)
        
        # Initialize game state (EXACT from TypeScript)
        self.game_state = {
            "units": processed_units,
            "current_player": 0,
            "phase": "move",
            "mode": "select",
            "selected_unit_id": None,
            "units_moved": [],
            "units_charged": [],
            "units_attacked": [],
            "units_fled": [],
            "target_preview": None,
            "current_turn": 1,
            "combat_sub_phase": None,
            "combat_active_player": None,
            "unit_charge_rolls": {},
        }
        
        # Additional state objects (EXACT from TypeScript)
        self.unit_charge_rolls: Dict[int, int] = {}
        self.charge_roll_popup: Optional[ChargeRollPopup] = None
        self.move_preview: Optional[MovePreview] = None
        self.attack_preview: Optional[AttackPreview] = None
        self.shooting_phase_state = ShootingPhaseState()

    # === CORE STATE SETTERS (EXACT from TypeScript) ===

    def set_units(self, units: List[Dict[str, Any]]) -> None:
        """EXACT mirror of setUnits from TypeScript"""
        self.game_state["units"] = copy.deepcopy(units)

    def set_current_player(self, player: int) -> None:
        """EXACT mirror of setCurrentPlayer from TypeScript"""
        self.game_state["current_player"] = player

    def set_phase(self, phase: str) -> None:
        """EXACT mirror of setPhase from TypeScript"""
        self.game_state["phase"] = phase

    def set_mode(self, mode: str) -> None:
        """EXACT mirror of setMode from TypeScript"""
        self.game_state["mode"] = mode

    def set_selected_unit_id(self, unit_id: Optional[int]) -> None:
        """EXACT mirror of setSelectedUnitId from TypeScript"""
        self.game_state["selected_unit_id"] = unit_id

    def set_current_turn(self, turn: int) -> None:
        """EXACT mirror of setCurrentTurn from TypeScript"""
        self.game_state["current_turn"] = turn

    def set_combat_sub_phase(self, sub_phase: Optional[str]) -> None:
        """EXACT mirror of setCombatSubPhase from TypeScript"""
        self.game_state["combat_sub_phase"] = sub_phase

    def set_combat_active_player(self, player: Optional[int]) -> None:
        """EXACT mirror of setCombatActivePlayer from TypeScript"""
        self.game_state["combat_active_player"] = player

    # === UNIT TRACKING METHODS (EXACT from TypeScript) ===

    def add_moved_unit(self, unit_id: int) -> None:
        """EXACT mirror of addMovedUnit from TypeScript"""
        if unit_id not in self.game_state["units_moved"]:
            self.game_state["units_moved"].append(unit_id)

    def add_charged_unit(self, unit_id: int) -> None:
        """EXACT mirror of addChargedUnit from TypeScript"""
        if unit_id not in self.game_state["units_charged"]:
            self.game_state["units_charged"].append(unit_id)

    def add_attacked_unit(self, unit_id: int) -> None:
        """EXACT mirror of addAttackedUnit from TypeScript"""
        if unit_id not in self.game_state["units_attacked"]:
            self.game_state["units_attacked"].append(unit_id)

    def add_fled_unit(self, unit_id: int) -> None:
        """EXACT mirror of addFledUnit from TypeScript"""
        if unit_id not in self.game_state["units_fled"]:
            self.game_state["units_fled"].append(unit_id)

    def reset_moved_units(self) -> None:
        """EXACT mirror of resetMovedUnits from TypeScript"""
        before_count = len(self.game_state["units_moved"])
        self.game_state["units_moved"] = []

    def reset_charged_units(self) -> None:
        """EXACT mirror of resetChargedUnits from TypeScript"""
        self.game_state["units_charged"] = []

    def reset_attacked_units(self) -> None:
        """EXACT mirror of resetAttackedUnits from TypeScript"""
        self.game_state["units_attacked"] = []

    def reset_fled_units(self) -> None:
        """EXACT mirror of resetFledUnits from TypeScript"""
        self.game_state["units_fled"] = []

    # === UNIT UPDATE METHODS (EXACT from TypeScript) ===

    def update_unit(self, unit_id: int, updates: Dict[str, Any]) -> None:
        """EXACT mirror of updateUnit from TypeScript"""
        for i, unit in enumerate(self.game_state["units"]):
            if unit["id"] == unit_id:
                # Direct update without deepcopy to ensure changes persist
                for key, value in updates.items():
                    self.game_state["units"][i][key] = value
                break

    def remove_unit(self, unit_id: int) -> None:
        """EXACT mirror of removeUnit from TypeScript"""
        self.game_state["units"] = [
            unit for unit in self.game_state["units"] 
            if unit["id"] != unit_id
        ]

    def move_unit(self, unit_id: int, new_col: int, new_row: int) -> None:
        """EXACT mirror of moveUnit from TypeScript"""
        self.update_unit(unit_id, {"col": new_col, "row": new_row})

    # === PHASE-SPECIFIC INITIALIZATION (EXACT from TypeScript) ===

    def initialize_shooting_phase(self) -> None:
        """
        EXACT mirror of initializeShootingPhase from TypeScript.
        Reset SHOOT_LEFT for all units to RNG_NB.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if "RNG_NB" not in unit:
                raise ValueError(f"unit.RNG_NB is required for unit: {unit}")
            if unit["RNG_NB"] is None:
                raise ValueError(f"unit.RNG_NB cannot be None for unit: {unit}")
            
            # Direct update to maintain object references
            self.game_state["units"][i]["SHOOT_LEFT"] = unit["RNG_NB"]

    def initialize_combat_phase(self) -> None:
        """
        EXACT mirror of initializeCombatPhase from TypeScript.
        Reset ATTACK_LEFT for all units to CC_NB.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if "CC_NB" not in unit:
                raise ValueError(f"unit.CC_NB is required for unit: {unit}")
            if unit["CC_NB"] is None:
                raise ValueError(f"unit.CC_NB cannot be None for unit: {unit}")
            
            # Direct update to maintain object references
            self.game_state["units"][i]["ATTACK_LEFT"] = unit["CC_NB"]
        """
        EXACT mirror of initializeCombatPhase from TypeScript.
        Reset ATTACK_LEFT for all units to CC_NB.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if "CC_NB" not in unit:
                raise ValueError(f"unit.CC_NB is required for unit: {unit}")
            if unit["CC_NB"] is None:
                raise ValueError(f"unit.CC_NB cannot be None for unit: {unit}")
            
            # Direct update to maintain object references
            self.game_state["units"][i]["ATTACK_LEFT"] = unit["CC_NB"]

    # === SHOOTING PHASE STATE (EXACT from TypeScript) ===

    def update_shooting_phase_state(self, updates: Dict[str, Any]) -> None:
        """EXACT mirror of updateShootingPhaseState from TypeScript"""
        if "active_shooters" in updates:
            self.shooting_phase_state.active_shooters = updates["active_shooters"]
        if "current_shooter" in updates:
            self.shooting_phase_state.current_shooter = updates["current_shooter"]
        if "single_shot_state" in updates:
            self.shooting_phase_state.single_shot_state = updates["single_shot_state"]

    def decrement_shots_left(self, unit_id: int) -> None:
        """EXACT mirror of decrementShotsLeft from TypeScript"""
        for i, unit in enumerate(self.game_state["units"]):
            if unit["id"] == unit_id:
                if "SHOOT_LEFT" not in unit:
                    raise ValueError("unit.SHOOT_LEFT is required")
                if unit["SHOOT_LEFT"] is None:
                    raise ValueError("unit.SHOOT_LEFT is required")
                
                updated_unit = copy.deepcopy(unit)
                updated_unit["SHOOT_LEFT"] = max(0, unit["SHOOT_LEFT"] - 1)
                self.game_state["units"][i] = updated_unit
                break

    # === CHARGE ROLL METHODS (EXACT from TypeScript) ===

    def set_unit_charge_roll(self, unit_id: int, roll: int) -> None:
        """EXACT mirror of setUnitChargeRoll from TypeScript"""
        self.unit_charge_rolls[unit_id] = roll
        self.game_state["unit_charge_rolls"][unit_id] = roll

    def reset_unit_charge_roll(self, unit_id: int) -> None:
        """EXACT mirror of resetUnitChargeRoll from TypeScript"""
        if unit_id in self.unit_charge_rolls:
            del self.unit_charge_rolls[unit_id]
        if unit_id in self.game_state["unit_charge_rolls"]:
            del self.game_state["unit_charge_rolls"][unit_id]

    def show_charge_roll_popup(self, unit_id: int, roll: int, too_low: bool) -> None:
        """EXACT mirror of showChargeRollPopup from TypeScript"""
        self.charge_roll_popup = ChargeRollPopup(
            unit_id=unit_id,
            roll=roll,
            too_low=too_low,
            timestamp=time.time()
        )

    def reset_charge_rolls(self) -> None:
        """EXACT mirror of resetChargeRolls from TypeScript"""
        self.unit_charge_rolls = {}
        self.game_state["unit_charge_rolls"] = {}
        self.charge_roll_popup = None

    # === PREVIEW METHODS (EXACT from TypeScript patterns) ===

    def set_move_preview(self, unit_id: int, start_col: int, start_row: int,
                        end_col: int, end_row: int, path: List[Dict[str, int]]) -> None:
        """Set movement preview"""
        self.move_preview = MovePreview(
            unit_id=unit_id,
            start_col=start_col,
            start_row=start_row,
            end_col=end_col,
            end_row=end_row,
            path=path
        )

    def clear_move_preview(self) -> None:
        """Clear movement preview"""
        self.move_preview = None

    def set_attack_preview(self, preview_data: Optional[Dict[str, Any]]) -> None:
        """Set attack preview - EXACT mirror of TypeScript interface"""
        if preview_data is None:
            self.attack_preview = None
        else:
            # Handle both TypeScript camelCase and Python snake_case
            unit_id_key = "unit_id" if "unit_id" in preview_data else "unitId"
            if unit_id_key not in preview_data:
                raise KeyError(f"Attack preview missing unit ID. Available keys: {list(preview_data.keys())}")
            
            self.attack_preview = AttackPreview(
                attacker_id=preview_data[unit_id_key],
                target_id=None,  # Not provided in TypeScript interface
                attack_type="preview"  # Default for preview mode
            )
            # Store col/row for position-based preview
            self.attack_preview.col = preview_data.get("col")
            self.attack_preview.row = preview_data.get("row")

    def clear_attack_preview(self) -> None:
        """EXACT mirror of clearAttackPreview from TypeScript"""
        self.attack_preview = None

    def set_target_preview(self, target_preview: Optional[Dict[str, Any]]) -> None:
        """Set target preview for shooting system"""
        self.game_state["target_preview"] = target_preview

    # === EXPOSED ACTIONS (EXACT from TypeScript return) ===

    def get_game_state(self) -> Dict[str, Any]:
        """Get complete game state"""
        return copy.deepcopy(self.game_state)

    def get_unit_by_id(self, unit_id: int) -> Optional[Dict[str, Any]]:
        """Get unit by ID"""
        for unit in self.game_state["units"]:
            if unit["id"] == unit_id:
                return copy.deepcopy(unit)
        return None

    def get_selected_unit(self) -> Optional[Dict[str, Any]]:
        """Get currently selected unit"""
        if self.game_state["selected_unit_id"] is None:
            return None
        return self.get_unit_by_id(self.game_state["selected_unit_id"])

    def get_current_player_units(self) -> List[Dict[str, Any]]:
        """Get current player's units"""
        return [
            copy.deepcopy(unit) for unit in self.game_state["units"] 
            if unit["player"] == self.game_state["current_player"]
        ]

    def get_enemy_units(self) -> List[Dict[str, Any]]:
        """Get enemy units (not current player)"""
        return [
            copy.deepcopy(unit) for unit in self.game_state["units"] 
            if unit["player"] != self.game_state["current_player"]
        ]

    def get_units_by_player(self, player: int) -> List[Dict[str, Any]]:
        """Get units for specific player"""
        return [
            copy.deepcopy(unit) for unit in self.game_state["units"] 
            if unit["player"] == player
        ]

    def get_move_preview(self) -> Optional[Dict[str, Any]]:
        """Get movement preview data"""
        if self.move_preview is None:
            return None
        
        return {
            "unit_id": self.move_preview.unit_id,
            "start_col": self.move_preview.start_col,
            "start_row": self.move_preview.start_row,
            "end_col": self.move_preview.end_col,
            "end_row": self.move_preview.end_row,
            "path": copy.deepcopy(self.move_preview.path)
        }

    def get_attack_preview(self) -> Optional[Dict[str, Any]]:
        """Get attack preview data"""
        if self.attack_preview is None:
            return None
        
        return {
            "attacker_id": self.attack_preview.attacker_id,
            "target_id": self.attack_preview.target_id,
            "attack_type": self.attack_preview.attack_type
        }

    def get_shooting_phase_state(self) -> Dict[str, Any]:
        """Get shooting phase state"""
        return {
            "active_shooters": copy.deepcopy(self.shooting_phase_state.active_shooters),
            "current_shooter": self.shooting_phase_state.current_shooter,
            "single_shot_state": copy.deepcopy(self.shooting_phase_state.single_shot_state)
        }

    def get_charge_roll_popup(self) -> Optional[Dict[str, Any]]:
        """Get charge roll popup data"""
        if self.charge_roll_popup is None:
            return None
        
        return {
            "unit_id": self.charge_roll_popup.unit_id,
            "roll": self.charge_roll_popup.roll,
            "too_low": self.charge_roll_popup.too_low,
            "timestamp": self.charge_roll_popup.timestamp
        }

    # === GAME STATE QUERIES (EXACT from TypeScript patterns) ===

    def is_game_over(self) -> bool:
        """Check if game is over (one player has no units)"""
        players = set(unit["player"] for unit in self.game_state["units"])
        return len(players) < 2

    def get_winner(self) -> Optional[int]:
        """Get winner if game is over, None otherwise"""
        if not self.is_game_over():
            return None
        
        if len(self.game_state["units"]) == 0:
            return None  # Draw
        
        return self.game_state["units"][0]["player"]

    def is_unit_moved(self, unit_id: int) -> bool:
        """Check if unit has moved this phase"""
        return unit_id in self.game_state["units_moved"]

    def is_unit_charged(self, unit_id: int) -> bool:
        """Check if unit has charged this phase"""
        return unit_id in self.game_state["units_charged"]

    def is_unit_attacked(self, unit_id: int) -> bool:
        """Check if unit has attacked this phase"""
        return unit_id in self.game_state["units_attacked"]

    def is_unit_fled(self, unit_id: int) -> bool:
        """Check if unit has fled this turn"""
        return unit_id in self.game_state["units_fled"]

    # === EXPOSED ACTIONS (EXACT from TypeScript return) ===

    def get_actions(self) -> Dict[str, Callable]:
        """
        Return all action functions (mirror of TypeScript useGameState return).
        This replaces the TypeScript hook's return actions object.
        """
        return {
            # Core state setters
            "set_units": self.set_units,
            "set_current_player": self.set_current_player,
            "set_phase": self.set_phase,
            "set_mode": self.set_mode,
            "set_selected_unit_id": self.set_selected_unit_id,
            "set_current_turn": self.set_current_turn,
            "set_combat_sub_phase": self.set_combat_sub_phase,
            "set_combat_active_player": self.set_combat_active_player,
            
            # Unit tracking
            "add_moved_unit": self.add_moved_unit,
            "add_charged_unit": self.add_charged_unit,
            "add_attacked_unit": self.add_attacked_unit,
            "add_fled_unit": self.add_fled_unit,
            "reset_moved_units": self.reset_moved_units,
            "reset_charged_units": self.reset_charged_units,
            "reset_attacked_units": self.reset_attacked_units,
            "reset_fled_units": self.reset_fled_units,
            
            # Unit updates
            "update_unit": self.update_unit,
            "remove_unit": self.remove_unit,
            "move_unit": self.move_unit,
            
            # Phase initialization
            "initialize_shooting_phase": self.initialize_shooting_phase,
            "initialize_combat_phase": self.initialize_combat_phase,
            
            # Shooting phase
            "update_shooting_phase_state": self.update_shooting_phase_state,
            "decrement_shots_left": self.decrement_shots_left,
            
            # Charge rolls
            "set_unit_charge_roll": self.set_unit_charge_roll,
            "reset_unit_charge_roll": self.reset_unit_charge_roll,
            "show_charge_roll_popup": self.show_charge_roll_popup,
            "reset_charge_rolls": self.reset_charge_rolls,
            
            # Previews
            "set_move_preview": self.set_move_preview,
            "clear_move_preview": self.clear_move_preview,
            "set_attack_preview": self.set_attack_preview,
            "clear_attack_preview": self.clear_attack_preview,
            "set_target_preview": self.set_target_preview,
            
            # Episode step tracking for training
            "set_episode_step_count": self.set_episode_step_count,
            "increment_episode_step_count": self.increment_episode_step_count,
        }


# === FACTORY FUNCTION (Mirror of TypeScript hook usage) ===

def use_game_state(initial_units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Factory function that mirrors the TypeScript useGameState hook.
    Returns the same structure that the TypeScript hook returns.
    """
    game_state_manager = UseGameState(initial_units)
    
    return {
        "game_state": game_state_manager.game_state,
        "move_preview": game_state_manager.get_move_preview(),
        "attack_preview": game_state_manager.get_attack_preview(),
        "shooting_phase_state": game_state_manager.get_shooting_phase_state(),
        "charge_roll_popup": game_state_manager.get_charge_roll_popup(),
        "actions": game_state_manager.get_actions(),
        "manager": game_state_manager,  # Additional: Direct access to manager for training
    }


# === TRAINING INTEGRATION CLASS ===

class TrainingGameState(UseGameState):
    """
    Extended version of UseGameState optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, initial_units: List[Dict[str, Any]], max_history: int = 100):
        super().__init__(initial_units)
        self.max_history = max_history
        self.state_history: List[Dict[str, Any]] = []
        self.training_metrics = {
            "actions_taken": 0,
            "phases_completed": 0,
            "turns_completed": 0,
            "units_destroyed": 0
        }

    def save_state_snapshot(self) -> None:
        """Save current state for training analysis"""
        snapshot = {
            "timestamp": time.time(),
            "turn": self.game_state["current_turn"],
            "phase": self.game_state["phase"],
            "player": self.game_state["current_player"],
            "units_count": len(self.game_state["units"]),
            "units_alive": {
                0: len([u for u in self.game_state["units"] if u["player"] == 0]),
                1: len([u for u in self.game_state["units"] if u["player"] == 1])
            }
        }
        
        self.state_history.append(snapshot)
        
        # Limit history size for memory efficiency
        if len(self.state_history) > self.max_history:
            self.state_history = self.state_history[-self.max_history:]

    def update_training_metrics(self, action_type: str) -> None:
        """Update training metrics for analysis"""
        self.training_metrics["actions_taken"] += 1
        
        if action_type == "phase_change":
            self.training_metrics["phases_completed"] += 1
        elif action_type == "turn_change":
            self.training_metrics["turns_completed"] += 1
        elif action_type == "unit_death":
            self.training_metrics["units_destroyed"] += 1

    def get_training_metrics(self) -> Dict[str, Any]:
        """Get training-relevant metrics"""
        return copy.deepcopy(self.training_metrics)

    def get_state_history(self) -> List[Dict[str, Any]]:
        """Get state history for training analysis"""
        return copy.deepcopy(self.state_history)

    def set_episode_step_count(self, count: int) -> None:
        """Set episode step count in game state"""
        if "episode_step_count" not in self.game_state:
            self.game_state["episode_step_count"] = 0
        self.game_state["episode_step_count"] = count

    def increment_episode_step_count(self) -> None:
        """Increment episode step count in game state"""
        if "episode_step_count" not in self.game_state:
            self.game_state["episode_step_count"] = 0
        self.game_state["episode_step_count"] += 1

    def reset_for_new_episode(self, initial_units: List[Dict[str, Any]]) -> None:
        """Reset state for new training episode"""
        # DON'T create a new object - just reset the existing game_state
        processed_units = []
        for unit in initial_units:
            processed_unit = copy.deepcopy(unit)
            if "RNG_NB" not in unit:
                raise KeyError(f"Unit missing required 'RNG_NB' field: {unit}")
            processed_unit["SHOOT_LEFT"] = unit["RNG_NB"]
            processed_units.append(processed_unit)
        
        # Reset the EXISTING game_state object for new episode (per specification)
        self.game_state["units"] = processed_units
        self.game_state["current_player"] = 0  # Episode starts with player 0
        self.game_state["phase"] = "move"      # Episode starts with move phase
        self.game_state["current_turn"] = 1    # Turns start at 1 at episode beginning
        self.game_state["episode_step_count"] = 0  # CRITICAL: Reset step count for new episode
        self.game_state["units_moved"] = []
        self.game_state["units_charged"] = []
        self.game_state["units_attacked"] = []
        self.game_state["units_fled"] = []

    def _get_unit_CUR_HP(self, unit: Dict[str, Any]) -> int:
        """Get unit CUR_HP, validate required fields exist"""
        if "CUR_HP" not in unit:
            raise KeyError(f"Unit missing required 'CUR_HP' field: {unit}")
        return unit["CUR_HP"]

    def _get_unit_type(self, unit: Dict[str, Any]) -> str:
        """Get unit type, validate field exists"""
        if "unit_type" not in unit:
            raise KeyError(f"Unit missing required 'unit_type' field: {unit}")
        return unit["unit_type"]

    def get_compressed_state(self) -> Dict[str, Any]:
        """Get compressed state for training (remove unnecessary data)"""
        compressed = {
            "units": [
                {
                    "id": u["id"],
                    "player": u["player"],
                    "col": u["col"],
                    "row": u["row"],
                    "CUR_HP": self._get_unit_CUR_HP(u),
                    "unit_type": self._get_unit_type(u)
                }
                for u in self.game_state["units"]
            ],
            "current_player": self.game_state["current_player"],
            "phase": self.game_state["phase"],
            "current_turn": self.game_state["current_turn"],
            "units_moved": copy.copy(self.game_state["units_moved"]),
            "units_charged": copy.copy(self.game_state["units_charged"]),
            "units_attacked": copy.copy(self.game_state["units_attacked"]),
            "units_fled": copy.copy(self.game_state["units_fled"])
        }
        return compressed

    def apply_bulk_updates(self, updates: List[Dict[str, Any]]) -> None:
        """Apply multiple state updates efficiently"""
        for update in updates:
            update_type = update.get("type")
            
            if update_type == "unit_update":
                self.update_unit(update["unit_id"], update["data"])
            elif update_type == "unit_remove":
                self.remove_unit(update["unit_id"])
            elif update_type == "phase_change":
                self.set_phase(update["phase"])
            elif update_type == "player_change":
                self.set_current_player(update["player"])
            # Add more update types as needed

    def validate_state_consistency(self) -> bool:
        """Validate state consistency for training debugging"""
        # Check unit IDs are unique
        unit_ids = [u["id"] for u in self.game_state["units"]]
        if len(unit_ids) != len(set(unit_ids)):
            return False
        
        # Check all units have required properties
        required_props = ["id", "player", "col", "row"]
        for unit in self.game_state["units"]:
            for prop in required_props:
                if prop not in unit:
                    return False
        
        # Check player is valid
        if self.game_state["current_player"] not in [0, 1]:
            return False
        
        # Check phase is valid
        valid_phases = ["move", "shoot", "charge", "combat"]
        if self.game_state["phase"] not in valid_phases:
            return False
        
        return True