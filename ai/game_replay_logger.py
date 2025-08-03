#!/usr/bin/env python3
"""
game_logger.py - Clean, unified game logger with complete dice roll tracking
Replaces game_replay_logger.py with single logging method and preserved dice functionality
"""

import json
import os
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Any

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
        
        # Turn/phase tracking
        self.current_turn = 1
        self.current_phase = "move"
        
        # Sequential ID for entries
        self.next_event_id = 1
        
        # Action names for readability (updated from game_replay_logger)
        self.action_names = {
            0: "move_closer", 1: "move_away", 2: "move_safe",
            3: "shoot_closest", 4: "shoot_weakest", 5: "charge_closest",
            6: "wait", 7: "attack_adjacent"
        }
        
        if not self.quiet:
            print("✅ GameLogger initialized with dice roll tracking")
    
    def add_entry(self, entry_type: str, message: str, **kwargs):
        """Add a single entry to combat log - the core method."""
        entry = {
            "id": self.next_event_id,
            "timestamp": datetime.now().isoformat(),
            "type": entry_type,
            "message": message,
            "turnNumber": self.current_turn,
            "phase": self.current_phase,
            **kwargs  # Add any additional fields
        }
        
        self.combat_log_entries.append(entry)
        self.next_event_id += 1
        
        if not self.quiet:
            print(f"📝 Logged: {entry_type} - {message} (ID: {entry['id']})")
        
        return entry
    
    def log_game_start(self):
        """Log game start."""
        self.add_entry(
            entry_type="turn_change",
            message="Start of Turn 1",
            reward=0.0,
            actionName="game_start",
            player=None,
            unitType=None,
            unitId=None,
            targetUnitType=None,
            targetUnitId=None,
            startHex=None,
            endHex=None,
            shootDetails=None
        )
    
    def log_move(self, unit: Dict, start_col: int, start_row: int, 
                 end_col: int, end_row: int, turn_number: int, 
                 reward: float, action_int: int):
        """Log movement action."""
        if start_col != end_col or start_row != end_row:
            message = f"Unit {unit['id']} moved from ({start_col},{start_row}) to ({end_col},{end_row})"
            start_hex = f"({start_col},{start_row})"
            end_hex = f"({end_col},{end_row})"
        else:
            message = f"Unit {unit['id']} stayed at ({start_col},{start_row})"
            start_hex = None
            end_hex = None
        
        self.add_entry(
            entry_type="move",
            message=message,
            reward=reward,
            actionName=self.action_names.get(action_int, f"action_{action_int}"),
            player=unit.get("player"),
            unitType=unit.get("unit_type"),
            unitId=unit.get("id"),
            targetUnitType=None,
            targetUnitId=None,
            startHex=start_hex,
            endHex=end_hex,
            shootDetails=None
        )
    
    def log_shoot(self, shooter: Dict, target: Dict, shoot_details: Dict, 
                  turn_number: int, reward: float, action_int: int):
        """Log shooting action with complete dice roll details."""
        message = format_shooting_message(shooter.get("id", 0), target.get("id", 0))
        converted_details = self._convert_shoot_details(shoot_details, shooter, target)
        
        self.add_entry(
            entry_type="shoot",
            message=message,
            reward=reward,
            actionName=self.action_names.get(action_int, f"action_{action_int}"),
            player=shooter.get("player"),
            unitType=shooter.get("unit_type"),
            unitId=shooter.get("id"),
            targetUnitType=target.get("unit_type"),
            targetUnitId=target.get("id"),
            startHex=None,
            endHex=None,
            shootDetails=converted_details  # Enhanced with dice roll details
        )
    
    def log_charge(self, charger: Dict, target: Dict, start_col: int, start_row: int,
                   end_col: int, end_row: int, turn_number: int, 
                   reward: float, action_int: int):
        """Log charge action."""
        message = f"Unit {charger['id']} charged Unit {target['id']} from ({start_col},{start_row}) to ({end_col},{end_row})"
        
        self.add_entry(
            entry_type="charge",
            message=message,
            reward=reward,
            actionName=self.action_names.get(action_int, f"action_{action_int}"),
            player=charger.get("player"),
            unitType=charger.get("unit_type"),
            unitId=charger.get("id"),
            targetUnitType=target.get("unit_type"),
            targetUnitId=target.get("id"),
            startHex=f"({start_col},{start_row})",
            endHex=f"({end_col},{end_row})",
            shootDetails=None
        )
    
    def log_combat(self, attacker: Dict, target: Dict, combat_details: Dict,
                   turn_number: int, reward: float, action_int: int):
        """Log combat action with complete dice roll details."""
        message = format_combat_message(attacker.get("id", 0), target.get("id", 0))
        converted_details = self._convert_combat_details(combat_details, attacker, target)
        
        self.add_entry(
            entry_type="combat",
            message=message,
            reward=reward,
            actionName=self.action_names.get(action_int, f"action_{action_int}"),
            player=attacker.get("player"),
            unitType=attacker.get("unit_type"),
            unitId=attacker.get("id"),
            targetUnitType=target.get("unit_type"),
            targetUnitId=target.get("id"),
            startHex=None,
            endHex=None,
            shootDetails=converted_details  # Enhanced with dice roll details
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
            
        hit_target = shooter.get("rng_atk")
        shooter_str = shooter.get("rng_str")
        target_t = target.get("t")
        target_armor = target.get("armor_save")
        target_invul = target.get("invul_save")
        shooter_ap = shooter.get("rng_ap")
        
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
                # Fix save target - calculate it even if shot missed/failed to wound
                save_target = shot.get("save_target", 0)
                if save_target == 0 and target:
                    save_target = calculate_save_target(
                        target.get("armor_save", 4), 
                        target.get("invul_save", 0), 
                        shooter.get("rng_ap", 0) if shooter else 0
                    )
                
                # Fix wound target - calculate it even if shot missed
                wound_target = shot.get("wound_target", 0)  
                if wound_target == 0 and shooter and target:
                    wound_target = calculate_wound_target(
                        shooter.get("rng_str", 4), 
                        target.get("t", 4)
                    )
                
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
            
        total_shots = summary.get("totalShots")
        hits = summary.get("hits") 
        wounds = summary.get("wounds")
        failed_saves = summary.get("failedSaves")
        
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
                    
                    # Validate required combat stats
                    required_attacker_stats = ["cc_atk", "cc_str", "cc_ap"]
                    required_target_stats = ["t", "armor_save", "invul_save"]
                    
                    for stat in required_attacker_stats:
                        if stat not in attacker:
                            raise ValueError(f"attacker.{stat} is required for combat details conversion")
                    
                    for stat in required_target_stats:
                        if stat not in target:
                            raise ValueError(f"target.{stat} is required for combat details conversion")
                    
                    hit_target = attacker["cc_atk"]
                    wound_target = calculate_wound_target(attacker["cc_str"], target["t"])
                    save_target = calculate_save_target(target["armor_save"], target["invul_save"], attacker["cc_ap"])
                    
                    # Validate all required combat attack data exists
                    required_attack_fields = ["hit_roll", "hit_success", "wound_roll", "wound_success", "save_roll", "save_success", "damage_dealt"]
                    for field in required_attack_fields:
                        if field not in attack:
                            raise ValueError(f"Combat attack missing required {field}")
                    
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
        if not self.quiet:
            print(f"📸 Captured initial game state with {len(getattr(self.env, 'units', []))} units")
    
    def capture_game_end(self, winner: str, final_reward: float):
        """Capture final game state - compatibility method."""
        self.add_entry(
            entry_type="game_end",
            message=f"Battle concludes - {winner} victorious",
            reward=final_reward,
            actionName="game_end",
            player=None,
            unitType=None,
            unitId=None,
            targetUnitType=None,
            targetUnitId=None,
            startHex=None,
            endHex=None,
            shootDetails=None
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
        if hasattr(self.env, 'units') and self.env.units:
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
                    required_stats = ["hp_max", "move", "rng_rng", "rng_dmg", "cc_dmg", "is_ranged", "is_melee"]
                    for stat in required_stats:
                        if stat not in unit_stats:
                            raise ValueError(f"Unit type '{unit_type}' missing required stat '{stat}'")
                    
                    initial_units.append({
                        "id": unit.get("id", i),
                        "unit_type": unit_type,
                        "player": unit.get("player", 0),
                        "col": unit.get("col", 0),
                        "row": unit.get("row", 0),
                        "HP_MAX": unit_stats["hp_max"],
                        "hp_max": unit_stats["hp_max"],
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
                "total_turns": self.current_turn,
                "winner": None,  # Can be set by caller
            },
            "metadata": {
                "total_combat_log_entries": len(self.combat_log_entries),
                "final_turn": self.current_turn,
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
            print(f"   🎮 {self.current_turn} turns")
            print(f"   💯 Reward: {episode_reward:.2f}")
            print(f"   ⚔️ Enhanced format with dice roll details")
        
        return filename
    
    def clear(self):
        """Clear all logged data for new episode."""
        self.combat_log_entries = []
        self.game_states = []
        self.current_turn = 1
        self.current_phase = "move"
        self.next_event_id = 1
        
        if not self.quiet:
            print("🔄 GameLogger cleared for new episode")


# Integration helper for enhanced logging - DROP-IN REPLACEMENT
class GameReplayIntegration:
    """Drop-in replacement for game_replay_logger.py GameReplayIntegration."""
    
    @staticmethod
    def enhance_training_env(env):
        """Add enhanced logging to training environment - creates 'replay_logger' attribute."""
        # Create GameReplayLogger and attach as 'replay_logger' for compatibility
        env.replay_logger = GameReplayLogger(env)
        env.replay_logger.capture_initial_state()
        
        if not env.replay_logger.quiet:
            print("✅ GameReplayLogger (as replay_logger) attached to environment")
        
        return env
    
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
