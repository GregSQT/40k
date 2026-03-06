#!/usr/bin/env python3
"""
shared/gameLogUtils.py
Shared game log message formatting functions ONLY
Extracted from PvP useGameLog.ts - preserves exact format

These functions produce SHORT messages (no coords, no dice details).
Used by: gameLogStructure.py (build_entry_message), game_replay_logger.py.

Example SHORT format (this module):
  format_shooting_message(1, 11)  -> "Unit 1 SHOT Unit 11"
  format_combat_message(1, 11)     -> "Unit 1 FOUGHT Unit 11"

Example DETAILED format (engine action_logs / step.log, NOT this module):
  "Unit 1(9,6) SHOT Unit 11(11,6) with [Heavy Bolter] - Hit 4(3+) - Wound 5(5+) - Save 4(5+) - Dmg:1HP"
  "Unit 1(9,6) FOUGHT Unit 11(11,6) with [Astartes Chainsword] - Hit 4(3+) - Wound 5(5+) - Save 4(5+) - Dmg:1HP"

DO NOT modify the short format - it must match the PvP reference exactly.
"""

def format_shooting_message(shooter_id: int, target_id: int) -> str:
    """Format shooting message exactly like PvP (short: no coords, no weapon/dice)."""
    return f"Unit {shooter_id} SHOT Unit {target_id}"

def format_move_message(unit_id: int, start_col: int, start_row: int, end_col: int, end_row: int) -> str:
    """Format move message exactly like PvP"""
    start_hex = f"({start_col}, {start_row})"
    end_hex = f"({end_col}, {end_row})"
    return f"Unit {unit_id} MOVED from {start_hex} to {end_hex}"

def format_no_move_message(unit_id: int) -> str:
    """Format no move message exactly like PvP"""
    return f"Unit {unit_id} NO MOVE"

def format_combat_message(attacker_id: int, target_id: int) -> str:
    """Format combat message exactly like PvP (short: no coords, no weapon/dice)."""
    return f"Unit {attacker_id} FOUGHT Unit {target_id}"

def format_charge_message(unit_name: str, unit_id: int, target_name: str, target_id: int, 
                         start_col: int, start_row: int, end_col: int, end_row: int) -> str:
    """Format charge message exactly like PvP"""
    start_hex = f"({start_col}, {start_row})"
    end_hex = f"({end_col}, {end_row})"
    return f"Unit {unit_name} {unit_id} CHARGED Unit {target_name} {target_id} from {start_hex} to {end_hex}"

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