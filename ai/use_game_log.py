#!/usr/bin/env python3
"""
ai/use_game_log.py
EXACT Python mirror of frontend/src/hooks/useGameLog.ts
Game logging system - ALL features preserved.

This is the complete functional equivalent of the PvP useGameLog hook system.
"""

from typing import Dict, List, Any, Optional, Callable
import time
from datetime import datetime
import copy
from shared.gameLogStructure import create_log_entry, BaseLogEntry, LogEntryParams

class GameLogEvent(BaseLogEntry):
    """
    EXACT mirror of GameLogEvent interface from TypeScript.
    Extends BaseLogEntry with frontend-specific properties.
    """
    def __init__(self, base_entry: BaseLogEntry, event_id: str, timestamp: datetime):
        # Copy all properties from base entry
        for key, value in base_entry.items():
            setattr(self, key, value)
        
        # Add frontend-specific properties
        self.id = event_id
        self.timestamp = timestamp

class UseGameLog:
    """
    EXACT Python mirror of useGameLog TypeScript hook.
    Game logging system with ALL features preserved.
    """
    
    def __init__(self):
        """Initialize with same state as TypeScript useGameLog"""
        self.events: List[Dict[str, Any]] = []
        self.event_id_counter = 0
        self.game_start_time: Optional[datetime] = None

    def generate_event_id(self) -> str:
        """EXACT mirror of generateEventId from TypeScript"""
        self.event_id_counter += 1
        return f"event_{self.event_id_counter}_{int(time.time() * 1000)}"

    def add_event(self, base_entry: Dict[str, Any]) -> None:
        """
        EXACT mirror of addEvent from TypeScript.
        Add new event to the log with timestamp and ID.
        """
        current_time = datetime.now()
        
        # Set game start time on first event (EXACT from TypeScript)
        if self.game_start_time is None:
            self.game_start_time = current_time
        
        # Create new event with ID and timestamp (EXACT from TypeScript)
        new_event = copy.deepcopy(base_entry)
        new_event["id"] = self.generate_event_id()
        new_event["timestamp"] = current_time
        
        # Add to front of events list (EXACT from TypeScript)
        self.events.insert(0, new_event)

    # === LOG EVENT METHODS (EXACT from TypeScript) ===

    def log_turn_start(self, turn_number: int) -> None:
        """
        EXACT mirror of logTurnStart from TypeScript.
        Log turn change event.
        """
        log_params: LogEntryParams = {
            "type": "turn_change",
            "turnNumber": turn_number
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_phase_change(self, phase: str, player: int, turn_number: int) -> None:
        """
        EXACT mirror of logPhaseChange from TypeScript.
        Log phase change event.
        """
        log_params: LogEntryParams = {
            "type": "phase_change",
            "actingUnit": {
                "id": 0,
                "unitType": "",
                "player": player
            },
            "turnNumber": turn_number,
            "phase": phase
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_move_action(self, unit: Dict[str, Any], start_col: int, start_row: int, 
                       end_col: int, end_row: int, turn_number: int) -> None:
        """
        EXACT mirror of logMoveAction from TypeScript.
        Log movement action.
        """
        log_params: LogEntryParams = {
            "type": "move",
            "actingUnit": {
                "id": unit["id"],
                "unitType": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"]
            },
            "turnNumber": turn_number,
            "startHex": f"({start_col}, {start_row})",
            "endHex": f"({end_col}, {end_row})"
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_move_cancellation(self, unit: Dict[str, Any], turn_number: int) -> None:
        """
        EXACT mirror of logMoveCancellation from TypeScript.
        Log movement cancellation.
        """
        log_params: LogEntryParams = {
            "type": "move_cancel",
            "actingUnit": {
                "id": unit["id"],
                "unitType": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"]
            },
            "turnNumber": turn_number
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_no_move_action(self, unit: Dict[str, Any], turn_number: int) -> None:
        """
        EXACT mirror of logNoMoveAction from TypeScript.
        Log no move decision.
        """
        log_params: LogEntryParams = {
            "type": "move",
            "actingUnit": {
                "id": unit["id"],
                "unitType": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"]
            },
            "turnNumber": turn_number
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_shooting_action(self, shooter: Dict[str, Any], target: Dict[str, Any], 
                           shoot_details: List[Dict[str, Any]], turn_number: int) -> None:
        """
        EXACT mirror of logShootingAction from TypeScript.
        Log shooting action with details.
        """
        log_params: LogEntryParams = {
            "type": "shoot",
            "actingUnit": {
                "id": shooter["id"],
                "unitType": shooter["unit_type"],
                "player": shooter["player"],
                "col": shooter["col"],
                "row": shooter["row"]
            },
            "targetUnit": {
                "id": target["id"],
                "unitType": target["unit_type"],
                "player": target["player"],
                "col": target["col"],
                "row": target["row"]
            },
            "turnNumber": turn_number,
            "shootDetails": shoot_details
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_charge_action(self, charger: Dict[str, Any], target: Dict[str, Any], 
                         start_col: int, start_row: int, end_col: int, end_row: int, 
                         turn_number: int) -> None:
        """
        EXACT mirror of logChargeAction from TypeScript.
        Log charge action.
        """
        log_params: LogEntryParams = {
            "type": "charge",
            "actingUnit": {
                "id": charger["id"],
                "unitType": charger["unit_type"],
                "player": charger["player"],
                "col": charger["col"],
                "row": charger["row"]
            },
            "targetUnit": {
                "id": target["id"],
                "unitType": target["unit_type"],
                "player": target["player"],
                "col": target["col"],
                "row": target["row"]
            },
            "turnNumber": turn_number,
            "startHex": f"({start_col}, {start_row})",
            "endHex": f"({end_col}, {end_row})"
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_charge_cancellation(self, unit: Dict[str, Any], turn_number: int) -> None:
        """
        EXACT mirror of logChargeCancellation from TypeScript.
        Log charge cancellation.
        """
        log_params: LogEntryParams = {
            "type": "charge_cancel",
            "actingUnit": {
                "id": unit["id"],
                "unitType": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"]
            },
            "turnNumber": turn_number
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    def log_combat_action(self, attacker: Dict[str, Any], defender: Dict[str, Any], 
                         combat_details: List[Dict[str, Any]], turn_number: int) -> None:
        """
        EXACT mirror of logCombatAction from TypeScript.
        Log combat action with details.
        """
        log_params: LogEntryParams = {
            "type": "combat",
            "actingUnit": {
                "id": attacker["id"],
                "unitType": attacker["unit_type"],
                "player": attacker["player"],
                "col": attacker["col"],
                "row": attacker["row"]
            },
            "targetUnit": {
                "id": defender["id"],
                "unitType": defender["unit_type"],
                "player": defender["player"],
                "col": defender["col"],
                "row": defender["row"]
            },
            "turnNumber": turn_number,
            "shootDetails": combat_details  # Uses same structure as shootDetails
        }
        
        base_entry = create_log_entry(log_params)
        self.add_event(base_entry)

    # === EXPOSED FUNCTIONS (EXACT from TypeScript return) ===

    def clear_log(self) -> None:
        """EXACT mirror of clearLog from TypeScript - clear all events"""
        self.events = []
        self.event_id_counter = 0

    def get_events_by_type(self, event_type: str) -> List[Dict[str, Any]]:
        """Get all events of a specific type"""
        return [event for event in self.events if event.get("type") == event_type]

    def get_game_duration(self) -> float:
        """Get game duration in seconds"""
        if self.game_start_time is None or not self.events:
            return 0.0
        
        # Get timestamp of most recent event
        latest_event = self.events[0] if self.events else None
        if latest_event and "timestamp" in latest_event:
            end_time = latest_event["timestamp"]
            duration = (end_time - self.game_start_time).total_seconds()
            return duration
        
        return 0.0

    def get_log_functions(self) -> Dict[str, Callable]:
        """
        Return all logging functions (EXACT mirror of TypeScript useGameLog return).
        This replaces the TypeScript hook's return statement with EXACT same methods.
        """
        return {
            "logTurnStart": self.log_turn_start,
            "logPhaseChange": self.log_phase_change,
            "logMoveAction": self.log_move_action,
            "logMoveCancellation": self.log_move_cancellation,
            "logNoMoveAction": self.log_no_move_action,
            "logShootingAction": self.log_shooting_action,
            "logChargeAction": self.log_charge_action,
            "logChargeCancellation": self.log_charge_cancellation,
            "logCombatAction": self.log_combat_action
        }


# === FACTORY FUNCTION (Mirror of TypeScript hook usage) ===

def use_game_log() -> Dict[str, Callable]:
    """
    Factory function that mirrors the TypeScript useGameLog hook.
    Returns the same logging functions that the TypeScript hook returns.
    """
    game_log_manager = UseGameLog()
    return game_log_manager.get_log_functions()


# === TRAINING INTEGRATION CLASS ===

class TrainingGameLog(UseGameLog):
    """
    Extended version of UseGameLog optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, max_events: int = 1000):
        super().__init__()
        self.max_events = max_events  # Limit events for memory efficiency
        self.training_metrics = {
            "actions_logged": 0,
            "turns_completed": 0,
            "phases_completed": 0
        }

    def add_event(self, base_entry: Dict[str, Any]) -> None:
        """Override to add training metrics and memory management"""
        super().add_event(base_entry)
        
        # Update training metrics
        self.training_metrics["actions_logged"] += 1
        
        event_type = base_entry.get("type", "")
        if event_type == "turn_change":
            self.training_metrics["turns_completed"] += 1
        elif event_type == "phase_change":
            self.training_metrics["phases_completed"] += 1
        
        # Memory management: keep only recent events
        if len(self.events) > self.max_events:
            self.events = self.events[:self.max_events]

    def get_training_metrics(self) -> Dict[str, Any]:
        """Get training-relevant metrics about logged events"""
        return copy.deepcopy(self.training_metrics)

    def reset_for_new_episode(self) -> None:
        """Reset logging for new training episode"""
        self.clear_log()
        self.training_metrics = {
            "actions_logged": 0,
            "turns_completed": 0,
            "phases_completed": 0
        }

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics for training analysis"""
        move_events = len(self.get_events_by_type("move"))
        shoot_events = len(self.get_events_by_type("shoot"))
        combat_events = len(self.get_events_by_type("combat"))
        
        return {
            "total_events": len(self.events),
            "move_actions": move_events,
            "shoot_actions": shoot_events,
            "combat_actions": combat_events,
            "game_duration": self.get_game_duration(),
            "actions_per_turn": (
                self.training_metrics["actions_logged"] / 
                max(1, self.training_metrics["turns_completed"])
            )
        }

    def export_for_replay(self) -> List[Dict[str, Any]]:
        """Export events in replay-compatible format"""
        replay_events = []
        
        for event in reversed(self.events):  # Reverse to chronological order
            # Convert to replay format
            replay_event = {
                "type": event.get("type", "unknown"),
                "message": event.get("message", ""),
                "turnNumber": event.get("turnNumber"),
                "phase": event.get("phase"),
                "unitId": event.get("unitId"),
                "targetUnitId": event.get("targetUnitId"),
                "player": event.get("player"),
                "startHex": event.get("startHex"),
                "endHex": event.get("endHex"),
                "shootDetails": event.get("shootDetails", [])
            }
            
            # Remove None values
            replay_event = {k: v for k, v in replay_event.items() if v is not None}
            replay_events.append(replay_event)
        
        return replay_events