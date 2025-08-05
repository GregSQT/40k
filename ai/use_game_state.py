#!/usr/bin/env python3
"""
use_game_state.py
EXACT Python mirror of frontend/src/hooks/useGameState.ts
Central state management system - ALL features preserved.

This is the complete functional equivalent of the PvP useGameState hook system.
"""

from typing import Dict, List, Any, Optional, Callable, Set
import copy
import time

class ChargeRollPopup:
    """Mirror of ChargeRollPopup interface from TypeScript"""
    def __init__(self, unit_id: int, roll: int, too_low: bool, timestamp: float):
        self.unit_id = unit_id
        self.roll = roll
        self.too_low = too_low
        self.timestamp = timestamp

class UseGameState:
    """
    EXACT Python mirror of useGameState TypeScript hook.
    Central game state management system with ALL features preserved.
    """
    
    def __init__(self, initial_units: List[Dict[str, Any]]):
        """Initialize with same parameters as TypeScript useGameState"""
        
        # Initialize game state (EXACT from TypeScript)
        processed_units = []
        for unit in initial_units:
            if unit.get("RNG_NB") is None:
                raise ValueError("unit.RNG_NB is required")
            
            processed_unit = copy.deepcopy(unit)
            processed_unit["SHOOT_LEFT"] = unit["RNG_NB"]
            processed_units.append(processed_unit)
        
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
        self.unit_charge_rolls = {}
        self.charge_roll_popup = None
        self.move_preview = None
        self.attack_preview = None
        self.shooting_phase_state = {
            "active_shooters": [],
            "current_shooter": None,
            "single_shot_state": None,
        }

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

    # === PREVIEW SYSTEM MANAGEMENT (EXACT from TypeScript) ===

    def set_move_preview(self, preview: Optional[Dict[str, Any]]) -> None:
        """EXACT mirror of setMovePreview from TypeScript"""
        self.move_preview = copy.deepcopy(preview) if preview else None

    def set_attack_preview(self, preview: Optional[Dict[str, Any]]) -> None:
        """EXACT mirror of setAttackPreview from TypeScript"""
        self.attack_preview = copy.deepcopy(preview) if preview else None

    def set_target_preview(self, preview: Optional[Dict[str, Any]]) -> None:
        """EXACT mirror of setTargetPreview from TypeScript"""
        self.game_state["target_preview"] = copy.deepcopy(preview) if preview else None

    # === UNIT TRACKING SYSTEMS (EXACT from TypeScript) ===

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

    # === UNIT MANAGEMENT (EXACT from TypeScript) ===

    def update_unit(self, unit_id: int, updates: Dict[str, Any]) -> None:
        """
        EXACT mirror of updateUnit from TypeScript.
        Update unit properties while preserving all other data.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if unit["id"] == unit_id:
                # Create updated unit with preserved data (EXACT from TypeScript)
                updated_unit = copy.deepcopy(unit)
                updated_unit.update(updates)
                self.game_state["units"][i] = updated_unit
                break

    def remove_unit(self, unit_id: int) -> None:
        """EXACT mirror of removeUnit from TypeScript"""
        self.game_state["units"] = [
            unit for unit in self.game_state["units"] 
            if unit["id"] != unit_id
        ]

    # === PHASE INITIALIZATION (EXACT from TypeScript) ===

    def initialize_shooting_phase(self) -> None:
        """
        EXACT mirror of initializeShootingPhase from TypeScript.
        Set SHOOT_LEFT for all units based on their RNG_NB.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if unit.get("RNG_NB") is None:
                raise ValueError("unit.RNG_NB is required")
            
            updated_unit = copy.deepcopy(unit)
            updated_unit["SHOOT_LEFT"] = unit["RNG_NB"]
            self.game_state["units"][i] = updated_unit

    def initialize_combat_phase(self) -> None:
        """
        EXACT mirror of initializeCombatPhase from TypeScript.
        Set ATTACK_LEFT for all units based on their CC_NB.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if unit.get("CC_NB") is None:
                raise ValueError("unit.CC_NB is required")
            
            updated_unit = copy.deepcopy(unit)
            updated_unit["ATTACK_LEFT"] = unit["CC_NB"]
            self.game_state["units"][i] = updated_unit

    # === SHOOTING PHASE MANAGEMENT (EXACT from TypeScript) ===

    def update_shooting_phase_state(self, updates: Dict[str, Any]) -> None:
        """EXACT mirror of updateShootingPhaseState from TypeScript"""
        self.shooting_phase_state.update(updates)

    def decrement_shots_left(self, unit_id: int) -> None:
        """
        EXACT mirror of decrementShotsLeft from TypeScript.
        Decrease SHOOT_LEFT by 1 for specified unit.
        """
        for i, unit in enumerate(self.game_state["units"]):
            if unit["id"] == unit_id:
                if unit.get("SHOOT_LEFT") is None:
                    raise ValueError("unit.SHOOT_LEFT is required")
                
                updated_unit = copy.deepcopy(unit)
                updated_unit["SHOOT_LEFT"] = max(0, unit["SHOOT_LEFT"] - 1)
                self.game_state["units"][i] = updated_unit
                break

    # === CHARGE SYSTEM (EXACT from TypeScript) ===

    def set_unit_charge_roll(self, unit_id: int, roll: int) -> None:
        """EXACT mirror of setUnitChargeRoll from TypeScript"""
        self.game_state["unit_charge_rolls"][str(unit_id)] = roll
        self.unit_charge_rolls[unit_id] = roll

    def reset_unit_charge_roll(self, unit_id: int) -> None:
        """EXACT mirror of resetUnitChargeRoll from TypeScript"""
        unit_id_str = str(unit_id)
        if unit_id_str in self.game_state["unit_charge_rolls"]:
            del self.game_state["unit_charge_rolls"][unit_id_str]
        if unit_id in self.unit_charge_rolls:
            del self.unit_charge_rolls[unit_id]

    def show_charge_roll_popup(self, unit_id: int, roll: int, too_low: bool) -> None:
        """EXACT mirror of showChargeRollPopup from TypeScript"""
        self.charge_roll_popup = ChargeRollPopup(
            unit_id=unit_id,
            roll=roll,
            too_low=too_low,
            timestamp=time.time() * 1000  # Convert to milliseconds like JS
        )

    def reset_charge_rolls(self) -> None:
        """EXACT mirror of resetChargeRolls from TypeScript"""
        self.game_state["unit_charge_rolls"] = {}
        self.unit_charge_rolls = {}

    # === TURN MANAGEMENT (Additional methods for training) ===

    def reset_turn_state(self) -> None:
        """
        Reset all turn-based tracking for new turn.
        Combines multiple reset methods for convenience.
        """
        self.reset_moved_units()
        self.reset_charged_units()
        self.reset_attacked_units()
        self.reset_fled_units()
        
        # Reset unit-specific turn flags (EXACT from TypeScript pattern)
        for i, unit in enumerate(self.game_state["units"]):
            updated_unit = copy.deepcopy(unit)
            updated_unit["has_charged_this_turn"] = False
            self.game_state["units"][i] = updated_unit

    def ensure_unit_properties(self) -> None:
        """
        Ensure all units have required properties for current phase.
        Used by training system to maintain state consistency.
        """
        for i, unit in enumerate(self.game_state["units"]):
            updated_unit = copy.deepcopy(unit)
            
            # Ensure shooting properties
            if updated_unit.get("SHOOT_LEFT") is None and updated_unit.get("RNG_NB") is not None:
                updated_unit["SHOOT_LEFT"] = updated_unit["RNG_NB"]
            
            # Ensure combat properties
            if updated_unit.get("ATTACK_LEFT") is None and updated_unit.get("CC_NB") is not None:
                updated_unit["ATTACK_LEFT"] = updated_unit["CC_NB"]
            
            # Ensure charge tracking
            if updated_unit.get("has_charged_this_turn") is None:
                updated_unit["has_charged_this_turn"] = False
            
            self.game_state["units"][i] = updated_unit

    # === STATE ACCESS METHODS ===

    def get_game_state(self) -> Dict[str, Any]:
        """Get complete game state dictionary"""
        return copy.deepcopy(self.game_state)

    def get_move_preview(self) -> Optional[Dict[str, Any]]:
        """Get current move preview"""
        return copy.deepcopy(self.move_preview) if self.move_preview else None

    def get_attack_preview(self) -> Optional[Dict[str, Any]]:
        """Get current attack preview"""
        return copy.deepcopy(self.attack_preview) if self.attack_preview else None

    def get_shooting_phase_state(self) -> Dict[str, Any]:
        """Get current shooting phase state"""
        return copy.deepcopy(self.shooting_phase_state)

    def get_charge_roll_popup(self) -> Optional[ChargeRollPopup]:
        """Get current charge roll popup"""
        return self.charge_roll_popup

    # === ACTION DISPATCHER (EXACT mirror of TypeScript return object) ===

    def get_actions(self) -> Dict[str, Callable]:
        """
        Return all action methods (mirror of TypeScript useGameState return).
        This replaces the TypeScript hook's return statement.
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
            
            # Preview system
            "set_move_preview": self.set_move_preview,
            "set_attack_preview": self.set_attack_preview,
            "set_target_preview": self.set_target_preview,
            
            # Unit tracking
            "add_moved_unit": self.add_moved_unit,
            "add_charged_unit": self.add_charged_unit,
            "add_attacked_unit": self.add_attacked_unit,
            "add_fled_unit": self.add_fled_unit,
            "reset_moved_units": self.reset_moved_units,
            "reset_charged_units": self.reset_charged_units,
            "reset_attacked_units": self.reset_attacked_units,
            "reset_fled_units": self.reset_fled_units,
            
            # Unit management
            "update_unit": self.update_unit,
            "remove_unit": self.remove_unit,
            
            # Phase initialization
            "initialize_shooting_phase": self.initialize_shooting_phase,
            "initialize_combat_phase": self.initialize_combat_phase,
            
            # Shooting phase
            "update_shooting_phase_state": self.update_shooting_phase_state,
            "decrement_shots_left": self.decrement_shots_left,
            
            # Charge system
            "set_unit_charge_roll": self.set_unit_charge_roll,
            "reset_unit_charge_roll": self.reset_unit_charge_roll,
            "show_charge_roll_popup": self.show_charge_roll_popup,
            "reset_charge_rolls": self.reset_charge_rolls,
            
            # Training-specific helpers
            "reset_turn_state": self.reset_turn_state,
            "ensure_unit_properties": self.ensure_unit_properties,
        }

    # === TRAINING INTEGRATION HELPERS ===

    def get_current_player_units(self) -> List[Dict[str, Any]]:
        """Get units for current player"""
        return [
            unit for unit in self.game_state["units"] 
            if unit["player"] == self.game_state["current_player"]
        ]

    def get_enemy_units(self) -> List[Dict[str, Any]]:
        """Get enemy units (not current player)"""
        return [
            unit for unit in self.game_state["units"] 
            if unit["player"] != self.game_state["current_player"]
        ]

    def get_units_by_player(self, player: int) -> List[Dict[str, Any]]:
        """Get units for specific player"""
        return [
            unit for unit in self.game_state["units"] 
            if unit["player"] == player
        ]

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


# === FACTORY FUNCTION (Mirror of TypeScript hook usage) ===

def use_game_state(initial_units: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Factory function that mirrors the TypeScript useGameState hook.
    Returns the same structure that the TypeScript hook returns.
    """
    game_state_manager = UseGameState(initial_units)
    
    return {
        "game_state": game_state_manager.get_game_state(),
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
    
    def __init__(self, initial_units: List[Dict[str, Any]]):
        super().__init__(initial_units)
        self.turn_history = []  # Track state changes for replay generation
        
    def log_state_change(self, action: str, details: Dict[str, Any]) -> None:
        """Log state changes for training replay generation"""
        self.turn_history.append({
            "timestamp": time.time(),
            "action": action,
            "details": details,
            "turn": self.game_state["current_turn"],
            "phase": self.game_state["phase"],
            "current_player": self.game_state["current_player"]
        })
    
    def get_turn_history(self) -> List[Dict[str, Any]]:
        """Get complete turn history for replay generation"""
        return copy.deepcopy(self.turn_history)
    
    def reset_for_new_episode(self, new_units: List[Dict[str, Any]]) -> None:
        """Reset state for new training episode"""
        self.__init__(new_units)
        self.turn_history = []
    
    def get_state_vector(self) -> List[float]:
        """
        Convert game state to numerical vector for AI training.
        This can be customized based on AI model requirements.
        """
        # This is a basic implementation - can be extended based on AI needs
        state_vector = []
        
        # Add basic game state
        state_vector.append(float(self.game_state["current_player"]))
        state_vector.append(float(self.game_state["current_turn"]))
        
        # Add phase encoding
        phase_encoding = {
            "move": 0.0, "shoot": 1.0, "charge": 2.0, "combat": 3.0
        }
        state_vector.append(phase_encoding.get(self.game_state["phase"], 0.0))
        
        # Add unit states (simplified - can be expanded)
        for unit in self.game_state["units"]:
            state_vector.extend([
                float(unit["player"]),
                float(unit["col"]),
                float(unit["row"]),
                float(unit["wounds"]),
                float(unit.get("SHOOT_LEFT", 0)),
                float(unit.get("ATTACK_LEFT", 0)),
            ])
        
        return state_vector