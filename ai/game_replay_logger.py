#!/usr/bin/env python3
"""
game_replay_logger.py - Capture full game state for visual replay
"""

import json
import os
import copy
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime

# Import shared structure
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.gameLogStructure import create_training_log_entry, TrainingLogEntry

# Import shared message formatting functions
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.gameLogUtils import (
    format_shooting_message,
    format_move_message, 
    format_no_move_message,
    format_combat_message,
    format_charge_message,
    format_death_message,
    format_turn_start_message,
    format_phase_change_message
)
from engine.combat_utils import get_unit_coordinates


class GameReplayLogger:
    """Simple, clean game action logger for W40K training replays with complete dice tracking."""
    
    def __init__(self, env):
        """Initialize with minimal setup."""
        self.env = env
        self.quiet = getattr(env, 'quiet', False)
        
        # Simple data storage
        self.combat_log_entries = []
        self.game_states = []
        
        # Sequential ID for entries
        self.next_event_id = 1
        
        # Action names for readability (updated from game_replay_logger)
        self.action_names = {
            0: "move_closer", 1: "move_away", 2: "move_safe",
            3: "shoot_closest", 4: "shoot_weakest", 5: "charge_closest",
            6: "wait", 7: "attack_adjacent"
        }
    
    def add_entry(self, entry_type: str, acting_unit: Dict = None, target_unit: Dict = None,
                  reward: float = 0.0, action_name: str = "", turn_number: int = None,
                  phase: str = None, start_hex: str = None, end_hex: str = None, 
                  shoot_details: List = None):
        """Add entry to combat log using shared structure."""
        # Enhanced evaluation mode detection
        env_eval = getattr(self.env, 'is_evaluation_mode', False)
        env_force = getattr(self.env, '_force_evaluation_mode', False)
        unwrapped_eval = hasattr(self.env, 'unwrapped') and getattr(self.env.unwrapped, 'is_evaluation_mode', False)
        
        is_eval_mode = env_eval or env_force or unwrapped_eval
                
        if not is_eval_mode:
            return None
            
        # Use shared structure for creating log entry
        current_turn = turn_number or self.env.controller.game_state["current_turn"]
        current_phase = phase or self.env.controller.game_state["phase"]
        
        log_entry = create_training_log_entry(
            entry_type=entry_type,
            acting_unit=acting_unit,
            target_unit=target_unit,
            reward=reward,
            action_name=action_name,
            turn_number=current_turn,
            phase=current_phase,
            start_hex=start_hex,
            end_hex=end_hex,
            shoot_details=shoot_details
        )
        
        # Convert to dict and add to combat log
        entry_dict = log_entry.to_dict()
        entry_dict["id"] = self.next_event_id  # Add sequential ID
        self.combat_log_entries.append(entry_dict)
        self.next_event_id += 1
        
        # CRITICAL FIX: Capture game state after each significant action
        if entry_type in ["move", "shoot", "charge", "combat", "wait"]:
            self._capture_game_state_snapshot()
                
        return entry_dict
    
    def log_game_start(self):
        """Log game start - episode starts at beginning of first Player 0 turn."""
        # CRITICAL: Episode always starts at Turn 1, Player 0 movement phase per specification
        start_turn = 1  # Force Turn 1 for episode start consistency
        self.add_entry(
            entry_type="turn_change", 
            reward=0.0,
            action_name="game_start",
            turn_number=start_turn
        )
    
    def log_move(self, unit: Dict, start_col: int, start_row: int, 
                 end_col: int, end_row: int, turn_number: int, 
                 reward: float, action_int: int):
        """Log movement action."""
        # Always provide hex coordinates, even for no-move actions
        # Format coordinates without space after comma: "(col,row)"
        start_hex = f"({start_col},{start_row})"
        end_hex = f"({end_col},{end_row})"
        
        self.add_entry(
            entry_type="move",
            acting_unit=unit,
            reward=reward,
            action_name=self.action_names.get(action_int, f"action_{action_int}"),
            turn_number=turn_number,
            start_hex=start_hex,
            end_hex=end_hex
        )
    
    def log_shoot(self, shooter: Dict, target: Dict, shoot_details: Dict, 
                  turn_number: int, reward: float, action_int: int):
        """Log shooting action with complete dice roll details."""
        converted_details = self._convert_shoot_details(shoot_details, shooter, target)
        
        self.add_entry(
            entry_type="shoot",
            acting_unit=shooter,
            target_unit=target,
            reward=reward,
            action_name=self.action_names.get(action_int, f"action_{action_int}"),
            turn_number=turn_number,
            shoot_details=converted_details
        )
    
    def log_wait(self, unit: Dict, turn_number: int, phase: str, reward: float, action_int: int):
        """Log wait action with correct phase information."""
        self.add_entry(
            entry_type="wait",
            acting_unit=unit,
            reward=reward,
            action_name=self.action_names.get(action_int, f"action_{action_int}"),
            turn_number=turn_number,
            phase=phase,
            start_hex=f"({unit['col']},{unit['row']})",
            end_hex=f"({unit['col']},{unit['row']})"
        )
    
    def log_charge(self, charger: Dict, target: Dict, start_col: int, start_row: int,
                   end_col: int, end_row: int, turn_number: int, 
                   reward: float, action_int: int, charge_roll: int = None, 
                   die1: int = None, die2: int = None, charge_succeeded: bool = None):
        """Log charge action with dice roll details."""
        # Create charge details with dice information
        charge_details = []
        if charge_roll is not None and die1 is not None and die2 is not None:
            # Use proper hex distance calculation for charge validation
            from engine.combat_utils import calculate_hex_distance
            from engine.combat_utils import get_unit_coordinates
            charger_col, charger_row = get_unit_coordinates(charger)
            target_col, target_row = get_unit_coordinates(target)
            distance_needed = calculate_hex_distance(charger_col, charger_row, target_col, target_row)
            charge_details.append({
                "rollType": "charge",
                "die1": die1,
                "die2": die2,
                "totalRoll": charge_roll,
                "targetDistance": distance_needed,
                "chargeSucceeded": charge_succeeded,
                "rollResult": "SUCCESS" if charge_succeeded else "FAILED"
            })
        else:
            # Generate missing charge roll data for logging consistency
            import random
            from engine.combat_utils import calculate_hex_distance
            die1 = random.randint(1, 6)
            die2 = random.randint(1, 6)
            charge_roll = die1 + die2
            from engine.combat_utils import get_unit_coordinates
            charger_col, charger_row = get_unit_coordinates(charger)
            target_col, target_row = get_unit_coordinates(target)
            distance_needed = calculate_hex_distance(charger_col, charger_row, target_col, target_row)
            # Use config value instead of hardcoded 12
            from config_loader import get_config_loader
            config = get_config_loader()
            game_config = config.get_game_config()
            charge_max_distance = game_config["game_rules"]["charge_max_distance"]
            charge_succeeded = distance_needed <= charge_roll and distance_needed <= charge_max_distance
            charge_details.append({
                "rollType": "charge",
                "die1": die1,
                "die2": die2,
                "totalRoll": charge_roll,
                "targetDistance": distance_needed,
                "chargeSucceeded": charge_succeeded,
                "rollResult": "SUCCESS" if charge_succeeded else "FAILED"
            })
        
        self.add_entry(
            entry_type="charge",
            acting_unit=charger,
            target_unit=target,
            reward=reward,
            action_name=self.action_names.get(action_int, f"action_{action_int}"),
            turn_number=turn_number,
            start_hex=f"({start_col}, {start_row})",
            end_hex=f"({end_col}, {end_row})",
            shoot_details=charge_details  # Reuse shoot_details field for charge roll info
        )
    
    def log_combat(self, attacker: Dict, target: Dict, combat_details: Dict,
                   turn_number: int, reward: float, action_int: int):
        """Log combat action with complete dice roll details."""
        converted_details = self._convert_combat_details(combat_details, attacker, target)
        
        self.add_entry(
            entry_type="combat",
            acting_unit=attacker,
            target_unit=target,
            reward=reward,
            action_name=self.action_names.get(action_int, f"action_{action_int}"),
            turn_number=turn_number,
            shoot_details=converted_details
        )
    
    def _convert_shoot_details(self, shoot_result, shooter=None, target=None):
        """Convert gym shooting result to detailed dice roll format - preserved from game_replay_logger.py"""
        if not shoot_result:
            return None
        
        # Calculate real target numbers using the same rules as training
        from engine.combat_utils import calculate_wound_target
        from engine.phase_handlers.shooting_handlers import _calculate_save_target
        
        # Get actual target numbers from unit stats - NO DEFAULTS!
        if not shooter or not target:
            print(f"⚠️ WARNING: Missing shooter or target data for shooting details")
            return None
            
        # Try both lowercase and uppercase field names for compatibility
        # Validate required fields exist - no fallbacks allowed
        if "RNG_ATK" not in shooter:
            raise ValueError(f"Shooter missing required 'RNG_ATK' field: {shooter}")
        if "RNG_STR" not in shooter:
            raise ValueError(f"Shooter missing required 'RNG_STR' field: {shooter}")
        if "T" not in target:
            raise ValueError(f"Target missing required 'T' field: {target}")
        if "ARMOR_SAVE" not in target:
            raise ValueError(f"Target missing required 'ARMOR_SAVE' field: {target}")
        if "INVUL_SAVE" not in target:
            raise ValueError(f"Target missing required 'INVUL_SAVE' field: {target}")
        if "RNG_AP" not in shooter:
            raise ValueError(f"Shooter missing required 'RNG_AP' field: {shooter}")
        
        hit_target = shooter["RNG_ATK"]
        shooter_str = shooter["RNG_STR"]
        target_t = target["T"]
        target_armor = target["ARMOR_SAVE"]
        target_invul = target["INVUL_SAVE"]
        shooter_ap = shooter["RNG_AP"]
        
        # Validate all required stats exist - no defaults allowed
        if any(x is None for x in [hit_target, shooter_str, target_t, target_armor, target_invul, shooter_ap]):
            raise ValueError(f"Missing unit stats - hit_target:{hit_target}, str:{shooter_str}, t:{target_t}, armor:{target_armor}, invul:{target_invul}, ap:{shooter_ap}")
        
        wound_target = calculate_wound_target(shooter_str, target_t)
        # Create temporary target dict for _calculate_save_target
        temp_target = {"ARMOR_SAVE": target_armor, "INVUL_SAVE": target_invul}
        save_target = _calculate_save_target(temp_target, shooter_ap)
        
        # Check if we have detailed shot-by-shot data
        if "shots" in shoot_result and isinstance(shoot_result["shots"], list):
            # Use detailed individual shot data - NO MORE DEFAULTS!
            shoot_details = []
            for i, shot in enumerate(shoot_result["shots"]):
                # Validate save target exists or calculate it properly
                if "save_target" not in shot:
                    if not target or "ARMOR_SAVE" not in target or "INVUL_SAVE" not in target:
                        raise ValueError("Cannot calculate save_target: missing target data")
                    if not shooter or "RNG_AP" not in shooter:
                        raise ValueError("Cannot calculate save_target: missing shooter data")
                    save_target = _calculate_save_target(
                        target, 
                        shooter["RNG_AP"]
                    )
                else:
                    save_target = shot["save_target"]
                
                # Validate wound target exists or calculate it properly
                if "wound_target" not in shot:
                    if not shooter or "RNG_STR" not in shooter:
                        raise ValueError("Cannot calculate wound_target: missing shooter data")
                    if not target or "T" not in target:
                        raise ValueError("Cannot calculate wound_target: missing target data")
                    wound_target = calculate_wound_target(
                        shooter["RNG_STR"], 
                        target["T"]
                    )
                else:
                    wound_target = shot["wound_target"] 
                
                shoot_details.append({
                    "shotNumber": i + 1,
                    "attackRoll": shot["hit_roll"],        # Real dice roll
                    "strengthRoll": shot["wound_roll"],    # Real dice roll  
                    "hitResult": "HIT" if shot["hit"] else "MISS",
                    "strengthResult": "SUCCESS" if shot["wound"] else "FAILED",
                    "hitTarget": shot["hit_target"],       # Real target number
                    "woundTarget": wound_target,           # Fixed target number
                    "saveTarget": save_target,             # Fixed target number
                    "saveRoll": shot["save_roll"],         # Real dice roll
                    "saveSuccess": shot["save_success"],
                    "damageDealt": shot["damage"]
                })
            return shoot_details
        
        # REQUIRE complete shot data - no fallbacks allowed
        summary = shoot_result.get("summary")
        if not summary:
            raise ValueError("Shooting result missing required 'summary' section")
            
        if "totalShots" not in summary:
            raise ValueError("Summary missing required 'totalShots' field")
        if "hits" not in summary:
            raise ValueError("Summary missing required 'hits' field")
        if "wounds" not in summary:
            raise ValueError("Summary missing required 'wounds' field")
        if "failedSaves" not in summary:
            raise ValueError("Summary missing required 'failedSaves' field")
        
        total_shots = summary["totalShots"]
        hits = summary["hits"]
        wounds = summary["wounds"]
        failed_saves = summary["failedSaves"]
        
        if total_shots is None:
            raise ValueError(f"execute_shooting_sequence() returned None for totalShots")
        
        if any(x is None for x in [hits, wounds, failed_saves]):
            raise ValueError(f"Missing shooting summary data - hits:{hits}, wounds:{wounds}, failedSaves:{failed_saves}")
        
        # Use individual shot data if available, otherwise error
        if "shots" in shoot_result and isinstance(shoot_result["shots"], list):
            # Use detailed individual shot data - same as before Change #8
            shoot_details = []
            for i, shot in enumerate(shoot_result["shots"]):
                shoot_details.append({
                    "shotNumber": i + 1,
                    "attackRoll": shot["hit_roll"],
                    "strengthRoll": shot["wound_roll"],
                    "hitResult": "HIT" if shot["hit"] else "MISS",
                    "strengthResult": "SUCCESS" if shot["wound"] else "FAILED",
                    "hitTarget": shot["hit_target"],
                    "woundTarget": wound_target,
                    "saveTarget": save_target,
                    "saveRoll": shot["save_roll"],
                    "saveSuccess": shot["save_success"],
                    "damageDealt": shot["damage"]
                })
            return shoot_details
        else:
            raise ValueError("Shooting result missing required individual shot data with dice rolls")
    
    def _get_board_size_from_env(self):
        """Get board size from environment - REQUIRE explicit config."""
        # REQUIRE board_size attribute in environment
        if not hasattr(self.env, 'board_size') or not self.env.board_size:
            raise ValueError("Environment missing required 'board_size' attribute")
        
        board_size = self.env.board_size
        if not isinstance(board_size, (list, tuple)) or len(board_size) != 2:
            raise ValueError(f"Environment board_size must be [cols, rows] format, got: {board_size}")
        
        if not all(isinstance(x, int) and x > 0 for x in board_size):
            raise ValueError(f"Board size values must be positive integers: {board_size}")
        
        return list(board_size)
    
    def capture_initial_state(self):
        """Capture initial game state - compatibility method for GameReplayLogger interface."""
        # Enhanced evaluation mode detection for initial state capture
        env_eval = getattr(self.env, 'is_evaluation_mode', False)
        self_eval = getattr(self, 'is_evaluation_mode', False)
        env_force = getattr(self.env, '_force_evaluation_mode', False)
        
        is_eval_mode = env_eval or self_eval or env_force
        if not is_eval_mode:
            return
            
        self.log_game_start()
        
        # CRITICAL FIX: Capture TRUE initial positions from scenario config, not current state
        if hasattr(self.env, 'config') and hasattr(self.env.config, 'initial_units'):
            # Use scenario config initial_units - the TRUE starting positions
            config_units = self.env.config.initial_units
            if config_units:
                formatted_units = []
                for unit in config_units:
                    # Validate ALL required fields - NO DEFAULTS
                    required_fields = ["id", "unit_type", "player", "col", "row",
                                 "CUR_HP", "HP_MAX", "MOVE", "RNG_RNG", "RNG_DMG", "CC_DMG", "CC_RNG"]
                    for field in required_fields:
                        if field not in unit:
                            raise ValueError(f"Unit missing required field '{field}': {unit}")
                    
                    formatted_units.append({
                        "id": unit["id"],
                        "unit_type": unit["unit_type"],
                        "player": unit["player"],
                        "col": get_unit_coordinates(unit)[0],
                        "row": get_unit_coordinates(unit)[1],
                        "CUR_HP": unit["CUR_HP"],
                        "HP_MAX": unit["HP_MAX"],
                        "MOVE": unit["MOVE"],
                        "RNG_RNG": unit["RNG_RNG"],
                        "RNG_DMG": unit["RNG_DMG"],
                        "CC_DMG": unit["CC_DMG"],
                        "CC_RNG": unit["CC_RNG"]
                    })
                
                # Store TRUE initial state from scenario config
                self.initial_game_state = {"units": formatted_units}
                return
        
        # FALLBACK: Use controller units only if no config available
        if hasattr(self.env, 'controller'):
            units = self.env.controller.get_units()
            if units:
                formatted_units = []
                for unit in units:
                    # Validate ALL required fields - NO DEFAULTS
                    required_fields = ["id", "unit_type", "player", "col", "row",
                                 "CUR_HP", "HP_MAX", "MOVE", "RNG_RNG", "RNG_DMG", "CC_DMG", "CC_RNG"]
                    for field in required_fields:
                        if field not in unit:
                            raise ValueError(f"Unit missing required field '{field}': {unit}")
                    
                    formatted_units.append({
                        "id": unit["id"],
                        "unit_type": unit["unit_type"],
                        "player": unit["player"],
                        "col": get_unit_coordinates(unit)[0],
                        "row": get_unit_coordinates(unit)[1],
                        "CUR_HP": unit["CUR_HP"],
                        "HP_MAX": unit["HP_MAX"],
                        "MOVE": unit["MOVE"],
                        "RNG_RNG": unit["RNG_RNG"],
                        "RNG_DMG": unit["RNG_DMG"],
                        "CC_DMG": unit["CC_DMG"],
                        "CC_RNG": unit["CC_RNG"]
                    })
                
                # Store for later use in save_replay
                self.initial_game_state = {"units": formatted_units}
    
    def capture_game_end(self, winner: str, final_reward: float):
        """Capture final game state - compatibility method."""
        self.add_entry(
            entry_type="game_end",
            reward=final_reward,
            action_name="game_end"
        )
        
        if not self.quiet:
            print(f"🏁 Game ended - Winner: {winner}, Final reward: {final_reward:.2f}")
    
    def get_combat_log_count(self):
        """Get current number of combat log entries."""
        return len(self.combat_log_entries)
    
    def save_replay(self, filename: str, episode_reward: float = 0.0):
        """Save replay to file with enhanced structure compatible with frontend."""
        # Extract initial state from environment if available
        initial_units = []
        
        # CRITICAL FIX: Capture final game state before saving
        self._capture_game_state_snapshot()
        
        # FIRST: Check if we have initial_game_state that was set in capture_initial_state
        if hasattr(self, 'initial_game_state') and self.initial_game_state and 'units' in self.initial_game_state:
            initial_units = self.initial_game_state['units']
        # SECOND: Try scenario config if initial_game_state missing
        elif hasattr(self.env, 'config') and hasattr(self.env.config, 'initial_units') and self.env.config.initial_units:
            config_units = self.env.config.initial_units
            for unit in config_units:
                # Validate ALL required fields - NO DEFAULTS
                required_fields = ["id", "unit_type", "player", "col", "row", 
                                 "CUR_HP", "HP_MAX", "MOVE", "RNG_RNG", "RNG_DMG", "CC_DMG", "CC_RNG"]
                for field in required_fields:
                    if field not in unit:
                        raise ValueError(f"Unit missing required field '{field}': {unit}")
                
                initial_units.append({
                    "id": unit["id"],
                    "unit_type": unit["unit_type"],
                    "player": unit["player"],
                    "col": get_unit_coordinates(unit)[0],
                    "row": get_unit_coordinates(unit)[1],
                    "CUR_HP": unit["CUR_HP"],
                    "HP_MAX": unit["HP_MAX"],
                    "MOVE": unit["MOVE"],
                    "RNG_RNG": unit["RNG_RNG"],
                    "RNG_DMG": unit["RNG_DMG"],
                    "CC_DMG": unit["CC_DMG"],
                    "CC_RNG": unit["CC_RNG"]
                })
        # THIRD: Try to get from controller if available
        elif hasattr(self.env, 'controller'):
            # The controller and env share the SAME replay_logger instance
            # So check if controller has units directly
            controller_units = self.env.controller.get_units()
            if controller_units:
                for unit in controller_units:
                    # Validate ALL required fields - NO DEFAULTS
                    required_fields = ["id", "unit_type", "player", "col", "row", 
                                     "CUR_HP", "HP_MAX", "MOVE", "RNG_RNG", "RNG_DMG", "CC_DMG", "CC_RNG"]
                    for field in required_fields:
                        if field not in unit:
                            raise ValueError(f"Unit missing required field '{field}': {unit}")
                    
                    initial_units.append({
                        "id": unit["id"],
                        "unit_type": unit["unit_type"],
                        "player": unit["player"],
                        "col": get_unit_coordinates(unit)[0],
                        "row": get_unit_coordinates(unit)[1],
                        "CUR_HP": unit["CUR_HP"],
                        "HP_MAX": unit["HP_MAX"],
                        "MOVE": unit["MOVE"],
                        "RNG_RNG": unit["RNG_RNG"],
                        "RNG_DMG": unit["RNG_DMG"],
                        "CC_DMG": unit["CC_DMG"],
                        "RNG_RNG": unit["RNG_RNG"],
                        "CC_RNG": unit["CC_RNG"]
                    })
        # THIRD: Try direct environment units
        elif hasattr(self.env, 'units') and self.env.units:
            for i, unit in enumerate(self.env.units):
                if unit and unit.get('alive', True):
                    # Get unit stats from environment unit definitions - NO DEFAULTS
                    unit_type = unit.get("unit_type")
                    if not unit_type:
                        raise ValueError(f"Unit {i} missing required unit_type")
                    
                    unit_definitions = getattr(self.env, 'unit_definitions', None)
                    if not unit_definitions:
                        raise ValueError("Environment missing required unit_definitions")
                    
                    unit_stats = unit_definitions.get(unit_type)
                    if not unit_stats:
                        raise ValueError(f"Unit type '{unit_type}' not found in unit_definitions")
                    
                    # Validate all required stats exist - NO DEFAULTS
                    required_stats = ["HP_MAX", "move", "rng_rng", "rng_dmg", "cc_dmg", "is_ranged", "is_melee"]
                    for stat in required_stats:
                        if stat not in unit_stats:
                            raise ValueError(f"Unit type '{unit_type}' missing required stat '{stat}'")
                    
                    if "id" not in unit:
                        raise ValueError(f"Unit {i} missing required 'id' field")
                    if "player" not in unit:
                        raise ValueError(f"Unit {i} missing required 'player' field") 
                    if "col" not in unit:
                        raise ValueError(f"Unit {i} missing required 'col' field")
                    if "row" not in unit:
                        raise ValueError(f"Unit {i} missing required 'row' field")
                    
                    initial_units.append({
                        "id": unit["id"],
                        "unit_type": unit_type,
                        "player": unit["player"],
                        "col": get_unit_coordinates(unit)[0],
                        "row": get_unit_coordinates(unit)[1],
                        "HP_MAX": unit_stats["HP_MAX"],
                        "MOVE": unit_stats["MOVE"],
                        "RNG_RNG": unit_stats["RNG_RNG"],
                        "RNG_DMG": unit_stats["RNG_DMG"],
                        "CC_DMG": unit_stats["CC_DMG"],
                        "CC_RNG": unit_stats["CC_RNG"],
                        "is_ranged": unit_stats["is_ranged"],
                        "is_melee": unit_stats["is_melee"]
                    })
        
        # Enhanced replay data structure compatible with frontend
        replay_data = {
            "game_info": {
                "scenario": "evaluation_episode",  # Mark as evaluation replay
                "ai_behavior": "phase_based",
                "total_turns": self.env.controller.game_state["current_turn"],
                "winner": self._determine_winner(),
            },
            "metadata": {
                "total_combat_log_entries": len(self.combat_log_entries),
                "final_turn": self.env.controller.game_state["current_turn"],
                "episode_reward": episode_reward,
                "format_version": "2.0",
                "replay_type": "training_enhanced"
            },
            "initial_state": {
                "units": initial_units if initial_units else [],
                "board_size": self._get_board_size_from_env()
            },
            "combat_log": self.combat_log_entries,
            "game_states": self.game_states,
            "episode_steps": len(self.combat_log_entries),
            "episode_reward": episode_reward
        }
        
        # CRITICAL FIX: If initial_state is still empty, populate it from current units
        if not replay_data["initial_state"]["units"] and hasattr(self.env, 'controller'):
            current_units = self.env.controller.get_units()
            if current_units:
                replay_data["initial_state"]["units"] = [{
                    "id": unit.get("id"),
                    "unit_type": unit.get("unit_type"),
                    "player": unit.get("player"),
                    "col": get_unit_coordinates(unit)[0] if "col" in unit else None,
                    "row": get_unit_coordinates(unit)[1] if "row" in unit else None,
                    "HP_MAX": unit.get("HP_MAX"),
                    "alive": unit.get("alive", True)
                } for unit in current_units]
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Save to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        if not self.quiet:
            print(f"💾 Saved enhanced replay: {filename}")
            print(f"   📊 {len(self.combat_log_entries)} combat log entries")
            print(f"   🎯 {len(self.game_states)} game state snapshots")
            print(f"   🎮 {self.env.controller.game_state['current_turn']} turns")
            print(f"   💯 Reward: {episode_reward:.2f}")
        
        return filename
    
    def _capture_game_state_snapshot(self):
        """Capture current game state for replay timeline."""
        if not hasattr(self.env, 'controller'):
            raise ValueError("Environment missing controller")
            
        units = self.env.controller.get_units()
        if not units:
            raise ValueError("No units available for capture")
        
        current_units = []
        for unit in units:
            if "id" not in unit:
                raise ValueError("Unit missing required 'id' field")
            if "CUR_HP" not in unit:
                raise ValueError("Unit missing required 'CUR_HP' field")
            if "HP_MAX" not in unit:
                raise ValueError("Unit missing required 'HP_MAX' field")
            
            current_units.append({
                "id": unit["id"],
                "unit_type": unit["unit_type"],
                "player": unit["player"],
                "col": get_unit_coordinates(unit)[0],
                "row": get_unit_coordinates(unit)[1],
                "CUR_HP": unit["CUR_HP"],
                "HP_MAX": unit["HP_MAX"],
                "alive": unit["alive"]
            })
        
        game_state_snapshot = {
            "turn": self.env.controller.game_state["current_turn"],
            "phase": self.env.controller.game_state["phase"],
            "player": self.env.controller.game_state["current_player"],
            "units": current_units,
            "timestamp": datetime.now().isoformat()
        }
        
        self.game_states.append(game_state_snapshot)
    
    def capture_turn_state(self):
        """Public method to capture state at turn transitions."""
        self._capture_game_state_snapshot()
    
    def clear(self):
        """Clear all logged data for new episode."""
        # Always clear for new episode - prevents stale data
        self.combat_log_entries = []
        self.game_states = []
        self.next_event_id = 1
        
        # Clear initial state to force fresh capture
        if hasattr(self, 'initial_game_state'):
            delattr(self, 'initial_game_state')
    
    def log_turn_change(self, turn_number: int):
        """Log turn change event."""
        self.add_entry(
            entry_type="turn_change",
            turn_number=turn_number,
            reward=0.0,
            action_name="turn_change"
        )
    
    def _determine_winner(self):
        """Determine game winner based on remaining units."""
        if not hasattr(self.env, 'controller'):
            return None
            
        units = self.env.controller.get_units()
        if not units:
            return None
            
        # Count alive units by player - be more specific about alive status
        player_0_alive = 0
        player_1_alive = 0
        
        for unit in units:
            if unit.get("player") == 0 and unit.get("alive", True) and unit.get("CUR_HP", 1) > 0:
                player_0_alive += 1
            elif unit.get("player") == 1 and unit.get("alive", True) and unit.get("CUR_HP", 1) > 0:
                player_1_alive += 1
        
        if player_0_alive > 0 and player_1_alive == 0:
            return 0
        elif player_1_alive > 0 and player_0_alive == 0:
            return 1
        elif player_0_alive == 0 and player_1_alive == 0:
            return "draw"
        else:
            return None  # Game still ongoing
    
    def log_phase_change(self, phase: str, player: int, turn_number: int):
        """Log phase change event."""
        # Capture game state at phase changes
        self._capture_game_state_snapshot()
        
        acting_unit = {
            "id": 0,
            "unitType": "",
            "player": player
        }
        self.add_entry(
            entry_type="phase_change",
            acting_unit=acting_unit,
            turn_number=turn_number,
            phase=phase,
            reward=0.0,
            action_name="phase_change"
        )
    
    def log_action(self, action: int, reward: float, pre_action_units: list, post_action_units: list,
                   acting_unit_id: int, target_unit_id: int = None, description: str = ""):
        """Generic action logger that routes to specific log methods based on action type."""        
        # Find acting unit and target unit from the unit lists
        acting_unit = None
        target_unit = None
        
        # Find acting unit in pre-action state
        for unit in pre_action_units:
            if unit.get('id') == acting_unit_id:
                acting_unit = unit
                break
        
        # Find target unit in pre-action state if target_unit_id provided
        if target_unit_id is not None:
            for unit in pre_action_units:
                if unit.get('id') == target_unit_id:
                    target_unit = unit
                    break
        
        if not acting_unit:
            if not self.quiet:
                print(f"⚠️ log_action: Could not find acting unit {acting_unit_id}")
            return
        
        # Determine action type and route to appropriate method
        action_type = action % 8 if isinstance(action, int) else action
        
        # Route based on intended action type, not just state changes
        if action_type in [0, 1, 2, 3]:  # Movement actions
            acting_unit_post = None
            for unit in post_action_units:
                if unit.get('id') == acting_unit_id:
                    acting_unit_post = unit
                    break
            
            if not acting_unit_post:
                raise ValueError(f"Move action requires post-action unit state for unit {acting_unit_id}")
            
            current_turn = self.env.controller.game_state["current_turn"]
            self.log_move(
                acting_unit, 
                *get_unit_coordinates(acting_unit),
                *get_unit_coordinates(acting_unit_post),
                current_turn, reward, action
            )
                
        elif action_type == 4:  # Shooting
            if target_unit:
                # Create shoot_details for logging
                shoot_details = {"summary": {"totalShots": 1, "hits": 1, "wounds": 1, "failedSaves": 1}}
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_shoot(acting_unit, target_unit, shoot_details, 
                             current_turn, reward, action)
            else:
                if not self.quiet:
                    print(f"⚠️ log_action: Shooting action without target")
                    
        elif action_type == 5:  # Charge
            if target_unit:
                acting_unit_post = None
                for unit in post_action_units:
                    if unit.get('id') == acting_unit_id:
                        acting_unit_post = unit
                        break
                
                if acting_unit_post:
                    current_turn = self.env.controller.game_state["current_turn"]
                    self.log_charge(
                        acting_unit, target_unit,
                        *get_unit_coordinates(acting_unit),
                        *get_unit_coordinates(acting_unit_post),
                        current_turn, reward, action
                    )
                    
        elif action_type == 6:  # Wait action
            current_turn = self.env.controller.game_state["current_turn"]
            current_phase = self.env.controller.game_state["phase"]
            self.log_wait(acting_unit, current_turn, current_phase, reward, action)
                               
        elif action_type == 7:  # Attack adjacent (Combat)
            if target_unit:
                # Create combat_details for logging
                combat_details = {"summary": {"totalAttacks": 1, "hits": 1, "wounds": 1, "failedSaves": 1}}
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_combat(acting_unit, target_unit, combat_details,
                               current_turn, reward, action)
        
        else:
            raise ValueError(f"Unknown action type: {action_type}")
    


# Integration helper for enhanced logging - DROP-IN REPLACEMENT
class GameReplayIntegration:
    """Drop-in replacement for game_replay_logger.py GameReplayIntegration."""
    
    @staticmethod
    def enhance_training_env(env):
        """Add enhanced logging to training environment - creates 'replay_logger' attribute."""
        # ABSOLUTELY UNAVOIDABLE DEBUG - Will print regardless of quiet mode
        import sys
        sys.stdout.flush()
        
        try:
            # Create GameReplayLogger and attach as 'replay_logger' for compatibility
            env.replay_logger = GameReplayLogger(env)
            env.replay_logger.capture_initial_state()
            
            return env
        except Exception as e:
            raise
    
    @staticmethod
    def save_episode_replay(env, episode_reward: float, output_dir: str = "ai/event_log", is_best: bool = False):
        """Save episode replay with proper naming convention."""
        if hasattr(env, 'replay_logger') and env.replay_logger:
            if is_best:
                filename = os.path.join(output_dir, "train_best_game_replay.json")
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(output_dir, f"game_replay_{timestamp}.json")
            
            return env.replay_logger.save_replay(filename, episode_reward)
        return None

