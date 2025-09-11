#!/usr/bin/env python3
"""
shared/gameLogUtils.py
Shared game log message formatting functions ONLY
Extracted from PvP useGameLog.ts - preserves exact format

These functions provide identical message formatting for both PvP and training systems.
DO NOT modify these - they must match the PvP reference exactly.
"""

def format_shooting_message(shooter_id: int, target_id: int) -> str:
    """Format shooting message exactly like PvP"""
    return f"Unit {shooter_id} SHOT at unit {target_id}"

def format_move_message(unit_id: int, start_col: int, start_row: int, end_col: int, end_row: int) -> str:
    """Format move message exactly like PvP"""
    start_hex = f"({start_col}, {start_row})"
    end_hex = f"({end_col}, {end_row})"
    return f"Unit {unit_id} MOVED from {start_hex} to {end_hex}"

def format_no_move_message(unit_id: int) -> str:
    """Format no move message exactly like PvP"""
    return f"Unit {unit_id} NO MOVE"

def format_combat_message(attacker_id: int, target_id: int) -> str:
    """Format combat message exactly like PvP"""
    return f"Unit {attacker_id} FOUGHT unit {target_id}"

def format_charge_message(unit_name: str, unit_id: int, target_name: str, target_id: int, 
                         start_col: int, start_row: int, end_col: int, end_row: int) -> str:
    """Format charge message exactly like PvP"""
    start_hex = f"({start_col}, {start_row})"
    end_hex = f"({end_col}, {end_row})"
    return f"Unit {unit_name} {unit_id} CHARGED unit {target_name} {target_id} from {start_hex} to {end_hex}"

def format_death_message(unit_id: int, unit_type: str) -> str:
    """Format death message exactly like PvP"""
    return f"Unit {unit_id} ({unit_type}) DIED !"

def format_move_cancel_message(unit_name: str, unit_id: int) -> str:
    """Format move cancellation exactly like PvP"""
    return f"Unit {unit_name} {unit_id} cancelled its move action"

def format_charge_cancel_message(unit_name: str, unit_id: int) -> str:
    """Format charge cancellation exactly like PvP"""
    return f"Unit {unit_name} {unit_id} cancelled its charge action"

def format_turn_start_message(turn_number: int) -> str:
    """Format turn start exactly like PvP"""
    return f"Start of Turn {turn_number}"

def format_phase_change_message(player_name: str, phase: str) -> str:
    """Format phase change exactly like PvP"""
    return f"Start {player_name}'s {phase.upper()} phase"