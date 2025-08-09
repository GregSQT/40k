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
        # Use shared structure for creating log entry
        log_entry = create_training_log_entry(
            entry_type=entry_type,
            acting_unit=acting_unit,
            target_unit=target_unit,
            reward=reward,
            action_name=action_name,
            turn_number=turn_number or self.env.controller.game_state["current_turn"],
            phase=phase or self.env.controller.game_state["phase"],
            start_hex=start_hex,
            end_hex=end_hex,
            shoot_details=shoot_details
        )
        
        # Convert to dict and add to combat log
        entry_dict = log_entry.to_dict()
        entry_dict["id"] = self.next_event_id  # Add sequential ID
        self.combat_log_entries.append(entry_dict)
        self.next_event_id += 1
                
        return entry_dict
    
    def log_game_start(self):
        """Log game start."""
        # Use environment's actual current turn for game start
        start_turn = self.env.controller.game_state["current_turn"]
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
        # Use space after comma to match frontend expectation: "(col, row)"
        start_hex = f"({start_col}, {start_row})"
        end_hex = f"({end_col}, {end_row})"
        
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
    
    def log_charge(self, charger: Dict, target: Dict, start_col: int, start_row: int,
                   end_col: int, end_row: int, turn_number: int, 
                   reward: float, action_int: int, charge_roll: int = None, 
                   die1: int = None, die2: int = None, charge_succeeded: bool = None):
        """Log charge action with dice roll details."""
        # Create charge details with dice information
        charge_details = []
        if charge_roll is not None and die1 is not None and die2 is not None:
            distance_needed = max(abs(start_col - target["col"]), abs(start_row - target["row"]))
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
            start_hex=f"({start_col},{start_row})",
            end_hex=f"({end_col},{end_row})",
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
        from shared.gameRules import calculate_wound_target, calculate_save_target
        
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
        save_target = calculate_save_target(target_armor, target_invul, shooter_ap)
        
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
                    save_target = calculate_save_target(
                        target["ARMOR_SAVE"], 
                        target["INVUL_SAVE"], 
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
        
        # Legacy fallback if shots data missing
        summary = shoot_result.get("summary")
        if not summary:
            print(f"⚠️ WARNING: No shoot_result summary data - cannot create shooting details")
            return None
            
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
            raise ValueError(f"execute_shooting_sequence() returned None for totalShots - Unit: {shooter.get('unit_type', 'unknown') if shooter else 'None'} vs Target: {target.get('unit_type', 'unknown') if target else 'None'}")
        
        if any(x is None for x in [hits, wounds, failed_saves]):
            print(f"⚠️ WARNING: Missing shooting summary data - hits:{hits}, wounds:{wounds}, failedSaves:{failed_saves}")
            return None
        
        # Create fallback shot entries with calculated targets
        shoot_details = []
        for shot_num in range(total_shots):
            hit_result = "HIT" if shot_num < hits else "MISS"
            wound_result = "SUCCESS" if shot_num < wounds and hit_result == "HIT" else "FAILED"
            save_failed = shot_num < failed_saves and wound_result == "SUCCESS"
            
            # Generate realistic dice values that match the results
            attack_roll = hit_target + 1 if hit_result == "HIT" else hit_target - 1
            strength_roll = wound_target + 1 if wound_result == "SUCCESS" else wound_target - 1  
            save_roll = save_target - 1 if save_failed else save_target + 1
            
            # Clamp dice rolls to valid range [1-6]
            attack_roll = max(1, min(6, attack_roll))
            strength_roll = max(1, min(6, strength_roll))
            save_roll = max(1, min(6, save_roll))
            
            shoot_details.append({
                "shotNumber": shot_num + 1,
                "attackRoll": attack_roll,
                "strengthRoll": strength_roll,
                "hitResult": hit_result,
                "strengthResult": wound_result,
                "hitTarget": hit_target,       # Real calculated target
                "woundTarget": wound_target,   # Real calculated target
                "saveTarget": save_target,     # Real calculated target
                "saveRoll": save_roll,
                "saveSuccess": not save_failed,
                "damageDealt": 1 if save_failed else 0
            })
        
        return shoot_details

    def _convert_combat_details(self, combat_result, attacker=None, target=None):
        """Convert gym combat result to detailed dice roll format - preserved from game_replay_logger.py"""
        if not combat_result:
            return None
        
        # Combat results have 'totalAttacks' not 'totalShots' - convert the format
        if "summary" in combat_result and "totalAttacks" in combat_result["summary"]:
            # Create a shooting-compatible format
            modified_result = {
                "totalDamage": combat_result["totalDamage"],
                "summary": {
                    "totalShots": combat_result["summary"]["totalAttacks"],  # Convert totalAttacks to totalShots
                    "hits": combat_result["summary"]["hits"],
                    "wounds": combat_result["summary"]["wounds"], 
                    "failedSaves": combat_result["summary"]["failedSaves"]
                }
            }
            # Add shots data if available (convert from attackDetails)
            if "attackDetails" in combat_result:
                modified_result["shots"] = []
                for i, attack in enumerate(combat_result["attackDetails"]):
                    if not attacker or not target:
                        raise ValueError("Combat details conversion requires attacker and target unit data")
                    
                    # Calculate real target numbers using same rules as combat
                    from shared.gameRules import calculate_wound_target, calculate_save_target
                    
                    # Validate required combat stats exist - no defaults allowed
                    if "cc_atk" not in attacker:
                        raise ValueError("attacker.cc_atk is required for combat details conversion")
                    if "cc_str" not in attacker:
                        raise ValueError("attacker.cc_str is required for combat details conversion")
                    if "cc_ap" not in attacker:
                        raise ValueError("attacker.cc_ap is required for combat details conversion")
                    if "t" not in target:
                        raise ValueError("target.t is required for combat details conversion")
                    if "armor_save" not in target:
                        raise ValueError("target.armor_save is required for combat details conversion")
                    if "invul_save" not in target:
                        raise ValueError("target.invul_save is required for combat details conversion")
                    
                    hit_target = attacker["cc_atk"]
                    wound_target = calculate_wound_target(attacker["cc_str"], target["t"])
                    save_target = calculate_save_target(target["armor_save"], target["invul_save"], attacker["cc_ap"])
                    
                    # Validate all required combat attack data exists
                    if "hit_roll" not in attack:
                        raise ValueError("Combat attack missing required hit_roll")
                    if "hit_success" not in attack:
                        raise ValueError("Combat attack missing required hit_success")
                    if "wound_roll" not in attack:
                        raise ValueError("Combat attack missing required wound_roll")
                    if "wound_success" not in attack:
                        raise ValueError("Combat attack missing required wound_success")
                    if "save_roll" not in attack:
                        raise ValueError("Combat attack missing required save_roll")
                    if "save_success" not in attack:
                        raise ValueError("Combat attack missing required save_success")
                    if "damage_dealt" not in attack:
                        raise ValueError("Combat attack missing required damage_dealt")
                    
                    shot = {
                        "hit_roll": attack["hit_roll"],
                        "hit_target": hit_target,
                        "hit": attack["hit_success"],
                        "wound_roll": attack["wound_roll"],
                        "wound_target": wound_target,
                        "wound": attack["wound_success"],
                        "save_roll": attack["save_roll"],
                        "save_target": save_target,
                        "save_success": attack["save_success"],
                        "damage": attack["damage_dealt"]
                    }
                    modified_result["shots"].append(shot)
            
            return self._convert_shoot_details(modified_result, attacker, target)
        else:
            return self._convert_shoot_details(combat_result, attacker, target)
    
    def _get_board_size_from_env(self):
        """Get board size from environment - NO DEFAULTS ALLOWED."""
        # First try direct board_size attribute
        if hasattr(self.env, 'board_size') and self.env.board_size:
            board_size = self.env.board_size
            # Validate board_size format
            if isinstance(board_size, (list, tuple)) and len(board_size) == 2:
                return list(board_size)
            elif isinstance(board_size, int):
                return [board_size, board_size]  # Square board
            else:
                raise ValueError(f"Invalid board_size format in environment: {board_size}")
        
        # Try config loader if environment has it
        if hasattr(self.env, 'config_loader'):
            try:
                board_config = self.env.config_loader.load_board_config("default")
                if "cols" in board_config and "rows" in board_config:
                    return [board_config["cols"], board_config["rows"]]
            except Exception as e:
                raise ValueError(f"Failed to load board config from environment: {e}")
        
        # Try to import and use config_loader directly
        try:
            from config_loader import get_config_loader
            config = get_config_loader()
            board_config = config.load_board_config("default")
            if "cols" in board_config and "rows" in board_config:
                return [board_config["cols"], board_config["rows"]]
            else:
                raise ValueError("Board config missing required 'cols' and 'rows' properties")
        except ImportError:
            raise ValueError("Cannot import config_loader and environment has no board_size")
        except Exception as e:
            raise ValueError(f"Failed to load board config: {e}")
    
    def capture_initial_state(self):
        """Capture initial game state - compatibility method for GameReplayLogger interface."""
        self.log_game_start()
        
        # CRITICAL: Save initial units NOW when capture is called
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
                        "col": unit["col"],
                        "row": unit["row"],
                        "HP_MAX": unit["HP_MAX"],
                        "move": unit["MOVE"],
                        "rng_rng": unit["RNG_RNG"],
                        "rng_dmg": unit["RNG_DMG"],
                        "cc_dmg": unit["CC_DMG"],
                        "is_ranged": unit["RNG_RNG"] > 0,
                        "is_melee": unit["CC_RNG"] > 0,
                        "alive": True
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
        
        # FIRST: Check if we have initial_game_state that was set in start_new_episode
        if hasattr(self, 'initial_game_state') and self.initial_game_state and 'units' in self.initial_game_state:
            initial_units = self.initial_game_state['units']
            print(f"💾 Using stored initial_game_state with {len(initial_units)} units")
        # SECOND: Try to get from controller if available
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
                        "col": unit["col"],
                        "row": unit["row"],
                        "CUR_HP": unit["CUR_HP"],
                        "HP_MAX": unit["HP_MAX"],
                        "move": unit["MOVE"],
                        "rng_rng": unit["RNG_RNG"],
                        "rng_dmg": unit["RNG_DMG"],
                        "cc_dmg": unit["CC_DMG"],
                        "is_ranged": unit["RNG_RNG"] > 0,
                        "is_melee": unit["CC_RNG"] > 0
                    })
                print(f"💾 Using controller's units with {len(initial_units)} units")
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
                        "col": unit["col"],
                        "row": unit["row"],
                        "HP_MAX": unit_stats["HP_MAX"],
                        "HP_MAX": unit_stats["HP_MAX"],
                        "move": unit_stats["move"],
                        "rng_rng": unit_stats["rng_rng"],
                        "rng_dmg": unit_stats["rng_dmg"],
                        "cc_dmg": unit_stats["cc_dmg"],
                        "is_ranged": unit_stats["is_ranged"],
                        "is_melee": unit_stats["is_melee"]
                    })
        
        # Enhanced replay data structure compatible with frontend
        replay_data = {
            "game_info": {
                "scenario": "training_episode",
                "ai_behavior": "phase_based",
                "total_turns": self.env.controller.game_state["current_turn"],
                "winner": None,  # Can be set by caller
            },
            "metadata": {
                "total_combat_log_entries": len(self.combat_log_entries),
                "final_turn": self.env.controller.game_state["current_turn"],
                "episode_reward": episode_reward,
                "format_version": "2.0",
                "replay_type": "training_enhanced"
            },
            "initial_state": {
                "units": initial_units,
                "board_size": self._get_board_size_from_env()
            },
            "combat_log": self.combat_log_entries,
            "game_states": self.game_states,
            "episode_steps": len(self.combat_log_entries),
            "episode_reward": episode_reward
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Save to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        if not self.quiet:
            print(f"💾 Saved enhanced replay: {filename}")
            print(f"   📊 {len(self.combat_log_entries)} combat log entries")
            print(f"   🎮 {self.env.controller.game_state['current_turn']} turns")
            print(f"   💯 Reward: {episode_reward:.2f}")
            print(f"   ⚔️ Enhanced format with dice roll details")
        
        return filename
    
    def clear(self):
        """Clear all logged data for new episode."""
        # CRITICAL: Only clear if we have no logged actions yet
        # This prevents clearing mid-episode and losing action logs
        if len(self.combat_log_entries) <= 1:  # Only "game_start" entry
            self.combat_log_entries = []
            self.game_states = []
            self.next_event_id = 1
            if not self.quiet:
                print("🔄 GameLogger cleared for new episode")
        else:
            if not self.quiet:
                print(f"🔄 GameLogger NOT cleared - preserving {len(self.combat_log_entries)} entries")
    
    def log_turn_change(self, turn_number: int):
        """Log turn change event."""
        self.add_entry(
            entry_type="turn_change",
            turn_number=turn_number,
            reward=0.0,
            action_name="turn_change"
        )
    
    def log_phase_change(self, phase: str, player: int, turn_number: int):
        """Log phase change event."""
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
        
        if action_type in [0, 1, 2, 3]:  # Movement actions
            # Find position change
            acting_unit_post = None
            for unit in post_action_units:
                if unit.get('id') == acting_unit_id:
                    acting_unit_post = unit
                    break
            
            if acting_unit_post:
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_move(
                    acting_unit, 
                    acting_unit.get('col', 0), acting_unit.get('row', 0),
                    acting_unit_post.get('col', 0), acting_unit_post.get('row', 0),
                    current_turn, reward, action_type
                )
            else:
                # No movement occurred, log as no-move
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_move(
                    acting_unit,
                    acting_unit.get('col', 0), acting_unit.get('row', 0),
                    acting_unit.get('col', 0), acting_unit.get('row', 0),
                    current_turn, reward, action_type
                )
                
        elif action_type == 4:  # Shooting
            if target_unit:
                # Create minimal shoot_details for logging compatibility
                shoot_details = {"summary": {"totalShots": 1, "hits": 1, "wounds": 1, "failedSaves": 1}}
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_shoot(acting_unit, target_unit, shoot_details, 
                             current_turn, reward, action_type)
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
                        acting_unit.get('col', 0), acting_unit.get('row', 0),
                        acting_unit_post.get('col', 0), acting_unit_post.get('row', 0),
                        current_turn, reward, action_type
                    )
                    
        elif action_type == 6:  # Wait
            # Log as move with no position change
            current_turn = self.env.controller.game_state["current_turn"]
            self.log_move(
                acting_unit,
                acting_unit.get('col', 0), acting_unit.get('row', 0),
                acting_unit.get('col', 0), acting_unit.get('row', 0),
                current_turn, reward, action_type
            )
                               
        elif action_type == 7:  # Attack adjacent (Combat)
            if target_unit:
                # Create minimal combat_details for logging compatibility
                combat_details = {"summary": {"totalAttacks": 1, "hits": 1, "wounds": 1, "failedSaves": 1}}
                current_turn = self.env.controller.game_state["current_turn"]
                self.log_combat(acting_unit, target_unit, combat_details,
                               current_turn, reward, action_type)
        
        else:
            if not self.quiet:
                print(f"⚠️ log_action: Unknown action type {action_type}")


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
            
            if not env.replay_logger.quiet:
                print("✅ GameReplayLogger (as replay_logger) attached to environment")
            
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

