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
    **kwargs
) -> BaseLogEntry:
    """
    Create standardized log entry using replay format as standard
    This function ensures both PvP and replay generate identical base structure
    """
    
    # Generate message based on type using existing shared functions
    message = ""
    
    if entry_type == "shoot" and acting_unit and target_unit:
        message = format_shooting_message(
            acting_unit.get("id", 0), 
            target_unit.get("id", 0)
        )
    elif entry_type == "move" and acting_unit and start_hex and end_hex:
        # Extract coordinates from hex strings
        try:
            start_coords = start_hex.strip('()').split(', ')
            end_coords = end_hex.strip('()').split(', ')
            start_col, start_row = int(start_coords[0]), int(start_coords[1])
            end_col, end_row = int(end_coords[0]), int(end_coords[1])
            message = format_move_message(
                acting_unit.get("id", 0),
                start_col, start_row, end_col, end_row
            )
        except:
            message = f"Unit {acting_unit.get('id', 0)} MOVED from {start_hex} to {end_hex}"
    elif entry_type == "combat" and acting_unit and target_unit:
        message = format_combat_message(
            acting_unit.get("id", 0),
            target_unit.get("id", 0)
        )
    elif entry_type == "charge" and acting_unit and target_unit and start_hex and end_hex:
        try:
            start_coords = start_hex.strip('()').split(', ')
            end_coords = end_hex.strip('()').split(', ')
            start_col, start_row = int(start_coords[0]), int(start_coords[1])
            end_col, end_row = int(end_coords[0]), int(end_coords[1])
            
            message = format_charge_message(
                acting_unit.get("unit_type", "unknown"),
                acting_unit.get("id", 0),
                target_unit.get("unit_type", "unknown"),
                target_unit.get("id", 0),
                start_col, start_row, end_col, end_row
            )
        except:
            message = f"Unit {acting_unit.get('unit_type', 'unknown')} {acting_unit.get('id', 0)} CHARGED unit {target_unit.get('unit_type', 'unknown')} {target_unit.get('id', 0)}"
    elif entry_type == "death" and (target_unit or acting_unit):
        unit = target_unit or acting_unit
        message = format_death_message(
            unit.get("id", 0),
            unit.get("unit_type", "unknown")
        )
    elif entry_type == "move_cancel" and acting_unit:
        message = format_move_cancel_message(
            acting_unit.get("unit_type", "unknown"),
            acting_unit.get("id", 0)
        )
    elif entry_type == "charge_cancel" and acting_unit:
        message = format_charge_cancel_message(
            acting_unit.get("unit_type", "unknown"),
            acting_unit.get("id", 0)
        )
    elif entry_type == "turn_change":
        message = format_turn_start_message(turn_number or 1)
    elif entry_type == "phase_change" and acting_unit:
        player_name = f"Player {acting_unit.get('player', 0) + 1}"
        message = format_phase_change_message(player_name, phase or "unknown")
    else:
        message = f"Unknown action: {entry_type}"
    
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
    return icons.get(event_type, '📝')

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
        return 'game-log-entry--default'