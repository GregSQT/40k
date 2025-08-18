#!/usr/bin/env python3
"""
shared/gameLogStructure.py
Unified game log structure for both PvP and Replay systems
Based on replay log format as the standard
"""

from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import uuid

# Import existing message formatting functions
from .gameLogUtils import (
    format_shooting_message,
    format_move_message,
    format_combat_message,
    format_charge_message,
    format_death_message,
    format_move_cancel_message,
    format_charge_cancel_message,
    format_turn_start_message,
    format_phase_change_message
)

# Create LogEntryParams as TypedDict for Python mirror compatibility  
from typing import TypedDict

class LogEntryParams(TypedDict, total=False):
    """Parameters for creating log entries - Python mirror of TypeScript interface"""
    type: str
    actingUnit: Optional[Dict[str, Any]]
    targetUnit: Optional[Dict[str, Any]]
    turnNumber: Optional[int]
    phase: Optional[str]
    startHex: Optional[str]
    endHex: Optional[str]
    shootDetails: Optional[List[Dict]]
    reward: Optional[float]
    actionName: Optional[str]

class BaseLogEntry:
    """Base log entry structure - used by both PvP and Replay"""
    
    def __init__(self, 
                 entry_type: str,
                 message: str,
                 turn_number: Optional[int] = None,
                 phase: Optional[str] = None,
                 unit_type: Optional[str] = None,
                 unit_id: Optional[int] = None,
                 target_unit_type: Optional[str] = None,
                 target_unit_id: Optional[int] = None,
                 player: Optional[int] = None,
                 start_hex: Optional[str] = None,
                 end_hex: Optional[str] = None,
                 shoot_details: Optional[List[Dict]] = None):
        
        self.type = entry_type
        self.message = message
        self.turnNumber = turn_number
        self.phase = phase
        self.unitType = unit_type
        self.unitId = unit_id
        self.targetUnitType = target_unit_type
        self.targetUnitId = target_unit_id
        self.player = player
        self.startHex = start_hex
        self.endHex = end_hex
        self.shootDetails = shoot_details or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSON serialization"""
        result = {
            "type": self.type,
            "message": self.message
        }
        
        # Add optional fields only if they have values
        optional_fields = [
            "turnNumber", "phase", "unitType", "unitId", 
            "targetUnitType", "targetUnitId", "player", 
            "startHex", "endHex", "shootDetails"
        ]
        
        for field in optional_fields:
            value = getattr(self, field, None)
            if value is not None:
                result[field] = value
        
        return result

class TrainingLogEntry(BaseLogEntry):
    """Training-enhanced log entry - extends base with training-specific data"""
    
    def __init__(self, 
                 entry_type: str,
                 message: str,
                 reward: Optional[float] = None,
                 action_name: Optional[str] = None,
                 timestamp: Optional[str] = None,
                 entry_id: Optional[str] = None,
                 **kwargs):
        
        super().__init__(entry_type, message, **kwargs)
        self.reward = reward
        self.actionName = action_name
        self.timestamp = timestamp or datetime.now().isoformat()
        self.id = entry_id or str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format including training fields"""
        result = super().to_dict()
        
        # Add training-specific fields
        training_fields = ["reward", "actionName", "timestamp", "id"]
        for field in training_fields:
            value = getattr(self, field, None)
            if value is not None:
                result[field] = value
        
        return result

def create_log_entry(
    entry_type: str,
    acting_unit: Optional[Dict] = None,
    target_unit: Optional[Dict] = None,
    turn_number: Optional[int] = None,
    phase: Optional[str] = None,
    start_hex: Optional[str] = None,
    end_hex: Optional[str] = None,
    shoot_details: Optional[List[Dict]] = None,
    env: Optional[Any] = None,
    **kwargs
) -> BaseLogEntry:
    """
    Create standardized log entry using replay format as standard
    This function ensures both PvP and replay generate identical base structure
    """
    
    # PERFORMANCE FIX: Skip all processing during training
    if env and hasattr(env, 'replay_logger'):
        is_eval_mode = (
            getattr(env, 'is_evaluation_mode', False) or
            getattr(env.replay_logger, 'is_evaluation_mode', False) or
            getattr(env, '_force_evaluation_mode', False)
        )
        if not is_eval_mode:
            # Return minimal entry to avoid validation overhead during training
            return BaseLogEntry(entry_type=entry_type, message="training_skipped")
    
    # Generate message based on type using existing shared functions
    message = ""
    
    if entry_type == "shoot" and acting_unit and target_unit:
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        if "id" not in target_unit:
            raise KeyError("target_unit missing required 'id' field")
        message = format_shooting_message(
            acting_unit["id"], 
            target_unit["id"]
        )
    elif entry_type == "move" and acting_unit and start_hex and end_hex:
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        # Extract coordinates from hex strings - NO FALLBACKS
        start_coords = start_hex.strip('()').split(', ')
        end_coords = end_hex.strip('()').split(', ')
        if len(start_coords) != 2 or len(end_coords) != 2:
            raise ValueError(f"Invalid hex format: start_hex='{start_hex}', end_hex='{end_hex}'")
        start_col, start_row = int(start_coords[0]), int(start_coords[1])
        end_col, end_row = int(end_coords[0]), int(end_coords[1])
        message = format_move_message(
            acting_unit["id"],
            start_col, start_row, end_col, end_row
        )
    elif entry_type == "combat" and acting_unit and target_unit:
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        if "id" not in target_unit:
            raise KeyError("target_unit missing required 'id' field")
        message = format_combat_message(
            acting_unit["id"],
            target_unit["id"]
        )
    elif entry_type == "charge" and acting_unit and target_unit and start_hex and end_hex:
        # Validate required fields
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        if "id" not in target_unit:
            raise KeyError("target_unit missing required 'id' field")
        
        # Get unit types - check both formats, raise error if neither exists
        acting_unit_type = acting_unit.get("unitType") or acting_unit.get("unit_type")
        if not acting_unit_type:
            raise KeyError("acting_unit missing required 'unitType' or 'unit_type' field")
        
        target_unit_type = target_unit.get("unitType") or target_unit.get("unit_type")
        if not target_unit_type:
            raise KeyError("target_unit missing required 'unitType' or 'unit_type' field")
        
        # Extract coordinates - NO FALLBACKS
        start_coords = start_hex.strip('()').split(', ')
        end_coords = end_hex.strip('()').split(', ')
        if len(start_coords) != 2 or len(end_coords) != 2:
            raise ValueError(f"Invalid hex format: start_hex='{start_hex}', end_hex='{end_hex}'")
        start_col, start_row = int(start_coords[0]), int(start_coords[1])
        end_col, end_row = int(end_coords[0]), int(end_coords[1])
        
        message = format_charge_message(
            acting_unit_type,
            acting_unit["id"],
            target_unit_type,
            target_unit["id"],
            start_col, start_row, end_col, end_row
        )
    elif entry_type == "death" and (target_unit or acting_unit):
        unit = target_unit or acting_unit
        if "id" not in unit:
            raise KeyError("unit missing required 'id' field")
        
        unit_type = unit.get("unitType") or unit.get("unit_type")
        if not unit_type:
            raise KeyError("unit missing required 'unitType' or 'unit_type' field")
        
        message = format_death_message(unit["id"], unit_type)
    elif entry_type == "move_cancel" and acting_unit:
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        
        unit_type = acting_unit.get("unitType") or acting_unit.get("unit_type")
        if not unit_type:
            raise KeyError("acting_unit missing required 'unitType' or 'unit_type' field")
        
        message = format_move_cancel_message(unit_type, acting_unit["id"])
    elif entry_type == "charge_cancel" and acting_unit:
        if "id" not in acting_unit:
            raise KeyError("acting_unit missing required 'id' field")
        
        unit_type = acting_unit.get("unitType") or acting_unit.get("unit_type")
        if not unit_type:
            raise KeyError("acting_unit missing required 'unitType' or 'unit_type' field")
        
        message = format_charge_cancel_message(unit_type, acting_unit["id"])
    elif entry_type == "turn_change":
        if not turn_number or turn_number < 1:
            raise ValueError("turn_number is required and must be >= 1")
        message = format_turn_start_message(turn_number)
    elif entry_type == "phase_change" and acting_unit:
        if "player" not in acting_unit:
            raise KeyError("acting_unit missing required 'player' field")
        if not phase:
            raise ValueError("phase is required for phase_change entries")
        player_name = f"Player {acting_unit['player'] + 1}"
        message = format_phase_change_message(player_name, phase)
    else:
        raise ValueError(f"Unsupported entry_type '{entry_type}'. Valid types: shoot, move, combat, charge, death, move_cancel, charge_cancel, turn_change, phase_change")
    
    # Create base log entry
    return BaseLogEntry(
        entry_type=entry_type,
        message=message,
        turn_number=turn_number,
        phase=phase,
        unit_type=acting_unit.get("unit_type") if acting_unit else None,
        unit_id=acting_unit.get("id") if acting_unit else None,
        target_unit_type=target_unit.get("unit_type") if target_unit else None,
        target_unit_id=target_unit.get("id") if target_unit else None,
        player=acting_unit.get("player") if acting_unit else None,
        start_hex=start_hex,
        end_hex=end_hex,
        shoot_details=shoot_details
    )

def create_training_log_entry(
    entry_type: str,
    acting_unit: Optional[Dict] = None,
    target_unit: Optional[Dict] = None,
    reward: Optional[float] = None,
    action_name: Optional[str] = None,
    **kwargs
) -> TrainingLogEntry:
    """Create training-enhanced log entry (for replay systems only)"""
    
    # Create base entry first
    base_entry = create_log_entry(
        entry_type=entry_type,
        acting_unit=acting_unit,
        target_unit=target_unit,
        **kwargs
    )
    
    # Convert to training entry
    return TrainingLogEntry(
        entry_type=base_entry.type,
        message=base_entry.message,
        reward=reward,
        action_name=action_name,
        turn_number=base_entry.turnNumber,
        phase=base_entry.phase,
        unit_type=base_entry.unitType,
        unit_id=base_entry.unitId,
        target_unit_type=base_entry.targetUnitType,
        target_unit_id=base_entry.targetUnitId,
        player=base_entry.player,
        start_hex=base_entry.startHex,
        end_hex=base_entry.endHex,
        shoot_details=base_entry.shootDetails
    )

def convert_legacy_event(legacy_event: Dict) -> BaseLogEntry:
    """Convert any legacy event format to new standardized format"""
    return BaseLogEntry(
        entry_type=legacy_event.get("type", "unknown"),
        message=legacy_event.get("message", ""),
        turn_number=legacy_event.get("turnNumber"),
        phase=legacy_event.get("phase"),
        unit_type=legacy_event.get("unitType"),
        unit_id=legacy_event.get("unitId"),
        target_unit_type=legacy_event.get("targetUnitType"),
        target_unit_id=legacy_event.get("targetUnitId"),
        player=legacy_event.get("player"),
        start_hex=legacy_event.get("startHex"),
        end_hex=legacy_event.get("endHex"),
        shoot_details=legacy_event.get("shootDetails")
    )

# Utility functions for compatibility
def get_event_icon(event_type: str) -> str:
    """Get icon for event type (for display purposes)"""
    icons = {
        'turn_change': '🔄',
        'phase_change': '⏭️',
        'move': '👟',
        'shoot': '🎯',
        'charge': '⚡',
        'combat': '⚔️',
        'death': '💀',
        'move_cancel': '❌',
        'charge_cancel': '❌'
    }
    if event_type not in icons:
        raise ValueError(f"Unsupported event_type '{event_type}' for icon")
    return icons[event_type]

def get_event_type_class(event: Union[BaseLogEntry, Dict]) -> str:
    """Get CSS class for event type (for display purposes)"""
    event_type = event.type if hasattr(event, 'type') else event.get('type', '')
    message = event.message if hasattr(event, 'message') else event.get('message', '')
    
    if event_type == 'turn_change':
        return 'game-log-entry--turn'
    elif event_type == 'phase_change':
        return 'game-log-entry--phase'
    elif event_type == 'move':
        return 'game-log-entry--move'
    elif event_type == 'shoot':
        if 'HP' in message and '-' in message:
            return 'game-log-entry--shoot-damage'
        elif 'Saved!' in message or ('Success!' in message and 'Failed!' not in message):
            return 'game-log-entry--shoot-saved'
        return 'game-log-entry--shoot'
    elif event_type == 'charge':
        return 'game-log-entry--charge'
    elif event_type == 'combat':
        return 'game-log-entry--combat'
    elif event_type == 'death':
        return 'game-log-entry--death'
    elif event_type in ['move_cancel', 'charge_cancel']:
        return 'game-log-entry--cancel'
    else:
        raise ValueError(f"Unsupported event_type '{event_type}' for CSS class")

def log_unified_action(env, action_type: str, acting_unit: Dict, target_unit: Optional[Dict], 
                      reward: float, phase: str, turn_number: int) -> None:
    """
    Unified action logger for BOTH P0 and P1 - replaces direct replay_logger calls
    This ensures identical logging format regardless of player type, matching PvP mode
    """
    # STRICT VALIDATION: No defaults - all parameters required
    if not hasattr(env, 'replay_logger'):
        raise RuntimeError("Environment missing required replay_logger")
    if not env.replay_logger:
        raise RuntimeError("Environment replay_logger is None")
    if not action_type:
        raise ValueError("action_type is required")
    if not acting_unit:
        raise ValueError("acting_unit is required")
    if not phase:
        raise ValueError("phase is required")
    if turn_number < 1:
        raise ValueError("turn_number must be >= 1")
    
    # STRICT MAPPING: No defaults - raise error for unknown action types
    action_type_mapping = {
        "move": "move",
        "shoot": "shoot", 
        "charge": "charge",
        "combat": "combat",
        "wait": "wait"
    }
    
    if action_type not in action_type_mapping:
        raise ValueError(f"Unknown action_type '{action_type}'. Valid types: {list(action_type_mapping.keys())}")
    
    log_entry_type = action_type_mapping[action_type]
    
    # STRICT UNIT VALIDATION: Required fields must exist
    required_unit_fields = ["id", "col", "row"]
    for field in required_unit_fields:
        if field not in acting_unit:
            raise KeyError(f"acting_unit missing required field '{field}': {acting_unit}")
    
    if target_unit:
        for field in required_unit_fields:
            if field not in target_unit:
                raise KeyError(f"target_unit missing required field '{field}': {target_unit}")
    
    # Create standardized log entry using shared format - NO DEFAULTS
    log_entry = create_training_log_entry(
        entry_type=log_entry_type,
        acting_unit=acting_unit,
        target_unit=target_unit,
        reward=reward,
        action_name=action_type,
        turn_number=turn_number,
        phase=phase,
        start_hex=f"({acting_unit['col']}, {acting_unit['row']})",
        end_hex=f"({target_unit['col']}, {target_unit['row']})" if target_unit else None
    )
    
    # STRICT LOGGING: No fallbacks - must succeed or raise error
    if hasattr(env.replay_logger, 'add_entry'):
        env.replay_logger.add_entry(
            entry_type=log_entry.type,
            acting_unit=acting_unit,
            target_unit=target_unit,
            turn_number=log_entry.turnNumber,
            phase=log_entry.phase,
            reward=log_entry.reward,
            action_name=log_entry.actionName
        )
    elif hasattr(env.replay_logger, 'log_action'):
        # STRICT: Must provide required parameters - no defaults
        pre_action_units = [acting_unit]
        post_action_units = [acting_unit]
        
        env.replay_logger.log_action(
            action=action_type,
            reward=reward,
            pre_action_units=pre_action_units,
            post_action_units=post_action_units,
            acting_unit_id=acting_unit['id'],
            target_unit_id=target_unit['id'] if target_unit else None,
            description=f"Unified {action_type} action by unit {acting_unit['id']}"
        )
    else:
        raise RuntimeError("replay_logger missing required methods: add_entry or log_action")