# ai/game_logger.py
"""
Clean, simple game logger - Only the essential working parts
No complex wrappers, no dual systems, just direct action logging
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Any


class GameLogger:
    """Simple, clean game action logger for W40K training replays."""
    
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
        
        # Action names for readability
        self.action_names = {
            0: "move_north", 1: "move_south", 2: "move_east", 3: "move_west",
            4: "shoot", 5: "charge", 6: "attack", 7: "wait"
        }
        
        if not self.quiet:
            print("✅ Clean GameLogger initialized")
    
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
        """Log shooting action."""
        total_damage = shoot_details.get("totalDamage", 0)
        message = f"Unit {shooter['id']} shot Unit {target['id']} for {total_damage} damage"
        
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
            shootDetails=shoot_details  # Include the full shooting results
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
        """Log combat action."""
        total_damage = combat_details.get("totalDamage", 0)
        message = f"Unit {attacker['id']} attacked Unit {target['id']} for {total_damage} damage"
        
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
            shootDetails=None  # Combat details could go here if needed
        )
    
    def get_combat_log_count(self):
        """Get current number of combat log entries."""
        return len(self.combat_log_entries)
    
    def save_replay(self, filename: str, episode_reward: float = 0.0):
        """Save replay to file with simplified structure."""
        # Basic replay data structure
        replay_data = {
            "game_info": {
                "scenario": "training_episode",
                "total_turns": self.current_turn,
                "winner": None,  # Can be set by caller
            },
            "combat_log": self.combat_log_entries,
            "game_states": self.game_states,  # Can be populated by caller
            "initial_state": {},
            "episode_steps": 0,  # Can be set by caller
            "episode_reward": episode_reward
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # Save to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        if not self.quiet:
            print(f"💾 Saved replay: {filename}")
            print(f"   📊 {len(self.combat_log_entries)} combat log entries")
            print(f"   🎮 {self.current_turn} turns")
            print(f"   💯 Reward: {episode_reward:.2f}")
        
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


# Simple integration helper
class CleanGameReplayIntegration:
    """Clean integration helper for adding logging to training environment."""
    
    @staticmethod
    def enhance_training_env(env):
        """Add clean logging to training environment."""
        env.game_logger = GameLogger(env)
        env.game_logger.log_game_start()
        
        if not env.game_logger.quiet:
            print("✅ Clean GameLogger attached to environment")
        
        return env
    
    @staticmethod
    def save_episode_replay(env, episode_reward, output_dir="ai/event_log"):
        """Save episode replay using clean logger."""
        if hasattr(env, 'game_logger') and env.game_logger:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(output_dir, f"clean_game_replay_{timestamp}.json")
            return env.game_logger.save_replay(filename, episode_reward)
        return None