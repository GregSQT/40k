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

# Import shared message formatting functions (keeping all existing structure)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.gameLogUtils import (
    format_shooting_message,
    format_move_message, 
    format_no_move_message,
    format_combat_message,
    format_charge_message,
    format_move_cancel_message,
    format_charge_cancel_message,
    format_death_message,
    format_turn_start_message,
    format_phase_change_message
)

def format_game_log_message(event_type: str, acting_unit: Optional[Dict], target_unit: Optional[Dict], 
                           start_hex: Optional[str] = None, end_hex: Optional[str] = None) -> str:
    """Format game log messages using shared functions to match PvP exactly."""
    
    if event_type == "death" and target_unit:
        unit_type = target_unit.get('unit_type', 'unknown')
        return format_death_message(target_unit.get('id', 0), unit_type)
    
    if event_type == "shoot" and acting_unit and target_unit:
        return format_shooting_message(acting_unit.get('id', 0), target_unit.get('id', 0))
    
    if event_type == "combat" and acting_unit and target_unit:
        return format_combat_message(acting_unit.get('id', 0), target_unit.get('id', 0))
    
    if event_type == "charge" and acting_unit and target_unit and start_hex and end_hex:
        # Extract coordinates from hex string format "(x, y)"
        try:
            start_coords = start_hex.strip('()').split(', ')
            end_coords = end_hex.strip('()').split(', ')
            start_col, start_row = int(start_coords[0]), int(start_coords[1])
            end_col, end_row = int(end_coords[0]), int(end_coords[1])
            
            # Use unit_type as unit name for training (PvP has actual names)
            unit_name = acting_unit.get('unit_type', 'unknown')
            target_name = target_unit.get('unit_type', 'unknown')
            
            return format_charge_message(
                unit_name, acting_unit.get('id', 0),
                target_name, target_unit.get('id', 0),
                start_col, start_row, end_col, end_row
            )
        except:
            # Fallback if coordinate parsing fails
            return f"Unit {acting_unit.get('unit_type', 'unknown')} {acting_unit.get('id', '?')} CHARGED unit {target_unit.get('unit_type', 'unknown')} {target_unit.get('id', '?')} from {start_hex} to {end_hex}"
    
    if event_type == "move_cancel" and acting_unit:
        # Use unit_type as unit name for training (PvP has actual unit names)
        unit_name = acting_unit.get('unit_type', 'unknown')
        return format_move_cancel_message(unit_name, acting_unit.get('id', 0))
    
    if event_type == "charge_cancel" and acting_unit:
        # Use unit_type as unit name for training (PvP has actual unit names)
        unit_name = acting_unit.get('unit_type', 'unknown')
        return format_charge_cancel_message(unit_name, acting_unit.get('id', 0))
    
    if event_type == "move" and acting_unit:
        if start_hex and end_hex:
            # Extract coordinates from hex string format "(x, y)"
            try:
                start_coords = start_hex.strip('()').split(', ')
                end_coords = end_hex.strip('()').split(', ')
                start_col, start_row = int(start_coords[0]), int(start_coords[1])
                end_col, end_row = int(end_coords[0]), int(end_coords[1])
                return format_move_message(acting_unit.get('id', 0), start_col, start_row, end_col, end_row)
            except:
                # Fallback if coordinate parsing fails
                return f"Unit {acting_unit.get('id', '?')} MOVED from {start_hex} to {end_hex}"
        else:
            return format_no_move_message(acting_unit.get('id', 0))
    
    # Fallback for unknown event types (keep existing logic)
    return "Unknown action"

class GameReplayLogger:
    def __init__(self, env):
        """Initialize with the W40K environment."""
        self.quiet = getattr(env, 'quiet', False)  # Inherit quiet mode from environment
        self.env = env
        self.game_states = []
        self.combat_log_entries = []  # Initialize combat log immediately
        # Ensure it's always a list
        if not hasattr(self, 'combat_log_entries') or self.combat_log_entries is None:
            self.combat_log_entries = []
        self.current_turn = 1
        self.current_phase = "move"
        # Absolute turn counter that never resets across episodes
        self.absolute_turn = 1
        self.game_metadata = {
            "board_size": env.board_size,
            "max_turns": env.max_turns,
            "scenario": "training_episode",
            "timestamp": datetime.now().isoformat()
        }
        
        # Phase tracking
        self.phases = ["move", "shoot", "charge", "combat"]
        self.phase_index = 0
        
        # Sequential ID counter for proper chronological ordering
        self.next_event_id = 1
        
        # Action name mapping
        self.action_names = {
            0: "move_closer",
            1: "move_away", 
            2: "move_safe",
            3: "shoot_closest",
            4: "shoot_weakest", 
            5: "charge_closest",
            6: "wait",
            7: "attack_adjacent"
        }
    
    def _normalize_action(self, action):
        """Convert action to integer if it's a numpy array."""
        if isinstance(action, np.ndarray):
            return int(action.item())
        elif hasattr(action, 'item'):
            return int(action.item())
        else:
            return int(action)
    
    def capture_initial_state(self):
        # Capture the initial game state."""
        # Add initial combat log entry
        if not hasattr(self, 'combat_log_entries'):
            self.combat_log_entries = []
            
        # Add game start message using immediate event addition
        start_message = format_turn_start_message(1)
        self._add_event_immediate({
            "type": "turn_change",
            "message": start_message,
            "reward": 0.0,
            "turnNumber": 1,
            "phase": "move",
            "player": None,
            "unitType": None,
            "unitId": None,
            "targetUnitType": None,
            "targetUnitId": None,
            "startHex": None,
            "endHex": None,
            "actionName": "game_start",
            "shootDetails": None
        })
        
        initial_state = self._create_game_state_snapshot(
            action_taken=None,
            acting_unit_id=None,
            target_unit_id=None,
            phase="game_start",
            turn=0,
            reward=0.0
        )
        
        initial_state["event_flags"]["game_event"] = "battle_begins"
        initial_state["event_flags"]["description"] = "Initial deployment"
        
        self.game_states.append(initial_state)
        if not self.quiet:
            print(f"📸 Captured initial game state with {len(self.env.units)} units")
    
    def capture_action_state(self, action, reward: float, pre_action_units: List[Dict], 
                           post_action_units: List[Dict], acting_unit_id: Optional[int] = None,
                           target_unit_id: Optional[int] = None, description: str = ""):
        """Capture game state after an action with combat log format."""
        # Normalize action to integer
        action_int = self._normalize_action(action)
        
        # CRITICAL FIX: Update turn/phase BEFORE logging the event
        # so the event gets the correct turn/phase numbers
        self._update_turn_phase()
        
        # Generate combat log formatted entry (this now handles change detection internally)
        self._generate_combat_log_entry(action_int, reward, pre_action_units, post_action_units, 
                                      acting_unit_id, target_unit_id, description)
        
        # Create state snapshot
        state = self._create_game_state_snapshot(
            action_taken=action_int,
            acting_unit_id=acting_unit_id,
            target_unit_id=target_unit_id,
            phase=self.current_phase,
            turn=self.current_turn,
            reward=reward
        )
        
        # Combat log entry now handles all change detection centrally
        # No longer need separate change flags in state
        
        # Enhanced description
        if not description:
            action_name = self.action_names.get(action_int, f"action_{action_int}")
            description = f"AI performs {action_name}"
        
        state["event_flags"]["description"] = description
        
        self.game_states.append(state)
    
    def log_move_action(self, unit, start_col, start_row, end_col, end_row, turn_number):
        """Log move action exactly like PvP useGameLog.ts"""
        from shared.gameLogUtils import format_move_message, format_no_move_message
        
        if start_col != end_col or start_row != end_row:
            message = format_move_message(unit["id"], start_col, start_row, end_col, end_row)
            start_hex = f"({start_col}, {start_row})"
            end_hex = f"({end_col}, {end_row})"
        else:
            message = format_no_move_message(unit["id"])
            start_hex = None
            end_hex = None
        
        self._add_event_immediate({
            "type": "move",
            "message": message,
            "turnNumber": turn_number,
            "phase": self.current_phase,
            "unitType": unit.get("unit_type"),
            "unitId": unit.get("id"),
            "player": unit.get("player"),
            "startHex": start_hex,
            "endHex": end_hex
        })

    def log_shooting_action(self, shooter, target, shoot_details, turn_number):
        """Log shooting action exactly like PvP useGameLog.ts"""
        from shared.gameLogUtils import format_shooting_message
        
        print(f"🎯 log_shooting_action called:")
        print(f"   shoot_details received: {shoot_details}")
        print(f"   shooter stats: rng_atk={shooter.get('rng_atk')}, rng_str={shooter.get('rng_str')}, rng_ap={shooter.get('rng_ap')}")
        print(f"   target stats: t={target.get('t')}, armor_save={target.get('armor_save')}, invul_save={target.get('invul_save')}")
        
        message = format_shooting_message(shooter["id"], target["id"])
        
        converted_details = self._convert_shoot_details(shoot_details, shooter, target)
        print(f"   converted shootDetails: {converted_details}")
        
        self._add_event_immediate({
            "type": "shoot", 
            "message": message,
            "turnNumber": turn_number,
            "phase": self.current_phase,
            "unitType": shooter.get("unit_type"),
            "unitId": shooter.get("id"),
            "targetUnitType": target.get("unit_type"),
            "targetUnitId": target.get("id"),
            "player": shooter.get("player"),
            "shootDetails": converted_details
        })

    def log_charge_action(self, unit, target, start_col, start_row, end_col, end_row, turn_number):
        """Log charge action exactly like PvP useGameLog.ts"""
        from shared.gameLogUtils import format_charge_message
        
        unit_name = unit.get("unit_type", "Unit")
        target_name = target.get("unit_type", "Unit")
        message = format_charge_message(unit_name, unit["id"], target_name, target["id"], 
                                      start_col, start_row, end_col, end_row)
        start_hex = f"({start_col}, {start_row})"
        end_hex = f"({end_col}, {end_row})"
        
        self._add_event_immediate({
            "type": "charge",
            "message": message, 
            "turnNumber": turn_number,
            "phase": self.current_phase,
            "unitType": unit.get("unit_type"),
            "unitId": unit.get("id"),
            "targetUnitType": target.get("unit_type"),
            "targetUnitId": target.get("id"),
            "player": unit.get("player"),
            "startHex": start_hex,
            "endHex": end_hex
        })

    def log_combat_action(self, attacker, target, combat_details, turn_number):
        """Log combat action exactly like PvP useGameLog.ts"""
        from shared.gameLogUtils import format_combat_message
        
        message = format_combat_message(attacker["id"], target["id"])
        
        self._add_event_immediate({
            "type": "combat",
            "message": message,
            "turnNumber": turn_number, 
            "phase": self.current_phase,
            "unitType": attacker.get("unit_type"),
            "unitId": attacker.get("id"),
            "targetUnitType": target.get("unit_type"),
            "targetUnitId": target.get("id"),
            "player": attacker.get("player"),
            "shootDetails": self._convert_combat_details(combat_details, attacker, target)  # Pass unit data
        })

    def _add_event_immediate(self, event_data):
        """Add event immediately with sequential ID - called at exact moment event occurs"""
        import datetime
        
        # Assign ID immediately when event occurs
        event_id = self.next_event_id
        self.next_event_id += 1
        
        event = {
            "id": event_id,
            "timestamp": datetime.datetime.now().isoformat(),
            **event_data
        }
        
        self.combat_log_entries.append(event)
        
        # Debug: Print event immediately for verification
        if not self.quiet:
            print(f"📝 Event #{event_id}: {event.get('type', 'unknown')} - {event.get('message', '')[:50]}")

    def _convert_shoot_details(self, shoot_result, shooter=None, target=None):
        """Convert gym shooting result to PvP shootDetails format with actual dice rolls"""
        if not shoot_result:
            return None
        
        # Calculate real target numbers using the same rules as training
        from shared.gameRules import calculate_wound_target, calculate_save_target
        
        # Get actual target numbers from unit stats (same as training uses)
        hit_target = shooter.get("rng_atk", 4) if shooter else 4
        wound_target = calculate_wound_target(shooter.get("rng_str", 4), target.get("t", 4)) if shooter and target else 4
        save_target = calculate_save_target(target.get("armor_save", 4), target.get("invul_save", 0), shooter.get("rng_ap", 0)) if shooter and target else 4
        
        # Check if we have detailed shot-by-shot data (now always available after shared rules update)
        if "shots" in shoot_result and isinstance(shoot_result["shots"], list):
            # Use detailed individual shot data - NO MORE DEFAULTS!
            shoot_details = []
            for i, shot in enumerate(shoot_result["shots"]):
                # Fix save target - calculate it even if shot missed/failed to wound
                save_target = shot.get("save_target", 0)
                if save_target == 0 and target:
                    # Calculate save target manually since gym didn't set it
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
        
        # Legacy fallback if shots data somehow missing (should not happen after shared rules update)
        summary = shoot_result.get("summary", {})
        total_shots = summary.get("totalShots", 1)
        hits = summary.get("hits", 0)
        wounds = summary.get("wounds", 0)
        failed_saves = summary.get("failedSaves", 0)
        
        # Create fallback shot entries with calculated targets
        shoot_details = []
        for shot_num in range(max(1, total_shots)):
            hit_result = "HIT" if shot_num < hits else "MISS"
            wound_result = "SUCCESS" if shot_num < wounds and hit_result == "HIT" else "FAILED"
            save_failed = shot_num < failed_saves and wound_result == "SUCCESS"
            
            # Generate realistic dice values that match the results
            attack_roll = 5 if hit_result == "HIT" else 2  # Good hit vs clear miss
            strength_roll = 5 if wound_result == "SUCCESS" else 2  # Good wound vs clear fail
            save_roll = 2 if save_failed else 5  # Clear fail vs good save
            
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
        """Convert gym combat result to PvP shootDetails format (reused structure)"""
        return self._convert_shoot_details(combat_result, attacker, target)  # Same format with unit data
        
        # Print combat log entry for immediate visibility during training with action name
        # DISABLED for less verbose training
        # if not self.quiet:
        #     reward_str = f"+{reward:.2f}" if reward >= 0 else f"{reward:.2f}"
        #     player_str = f"P{combat_entry['player']}"
        #     action_name = self.action_names.get(action_int, f"action_{action_int}")
        #     print(f"🎯 [{player_str}] T{self.current_turn} {self.current_phase.upper()}: {combat_entry['message']} (R: {reward_str}) [{action_name}]")
    
    def _detect_acting_unit_from_changes(self, pre_action_units: List[Dict], post_action_units: List[Dict]) -> Optional[int]:
        """Simple fallback to detect which unit acted by looking for state changes."""
        # Look for units that moved (position changed)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get('id') == post_unit.get('id'):
                # Check position change
                if (pre_unit.get('col') != post_unit.get('col') or 
                    pre_unit.get('row') != post_unit.get('row')):
                    return post_unit.get('id')
                
                # Check status flag changes (has_moved, has_shot, has_charged, has_attacked)
                for flag in ['has_moved', 'has_shot', 'has_charged', 'has_attacked']:
                    if not pre_unit.get(flag, False) and post_unit.get(flag, False):
                        return post_unit.get('id')
        
        return None
    
    def capture_game_end(self, winner: str, final_reward: float):
        """Capture the final game state."""
        final_state = self._create_game_state_snapshot(
            action_taken=None,
            acting_unit_id=None,
            target_unit_id=None,
            phase="game_end",
            turn=self.current_turn,
            reward=final_reward
        )
        
        final_state["event_flags"].update({
            "game_event": "battle_ends",
            "winner": winner,
            "description": f"Battle concludes - {winner} victorious"
        })
        
        self.game_states.append(final_state)
    
    def _create_game_state_snapshot(self, action_taken, acting_unit_id, target_unit_id, 
                                  phase: str, turn: int, reward: float) -> Dict[str, Any]:
        """Create a complete game state snapshot."""
        # Convert units to the format expected by the web app
        units_data = []
        for i, unit in enumerate(self.env.units):
            unit_data = {
                "id": i,
                "name": unit.get("name", f"{unit.get('unit_type', 'Unit')} {i+1}"),
                "unit_type": unit.get("unit_type", "Unknown"),
                "player": unit.get("player", 0),
                "row": unit.get("row", 0),
                "col": unit.get("col", 0),
                "hp": unit.get("hp", unit.get("max_hp", 1)),
                "max_hp": unit.get("max_hp", 1),
                "alive": unit.get("alive", True),
                "movement": unit.get("movement", 6),
                "weapon_skill": unit.get("weapon_skill", 3),
                "ballistic_skill": unit.get("ballistic_skill", 3),
                "strength": unit.get("strength", 4),
                "toughness": unit.get("toughness", 4),
                "wounds": unit.get("wounds", 2),
                "attacks": unit.get("attacks", 1),
                "leadership": unit.get("leadership", 7),
                "save": unit.get("save", 3),
                "color": self._get_unit_color(unit),
                "icon": self._get_unit_icon(unit)
            }
            units_data.append(unit_data)
        
        # Create the state
        state = {
            "turn": turn,
            "phase": phase,
            "active_player": getattr(self.env, 'current_player', 0),
            "units": units_data,
            "board_state": {
                "width": self.env.board_size,
                "height": self.env.board_size,
                "terrain": []  # Add terrain if available
            },
            "event_flags": {
                "action_id": action_taken,
                "acting_unit_id": acting_unit_id,
                "target_unit_id": target_unit_id,
                "reward": reward,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        return state
    
    def _get_unit_color(self, unit: Dict) -> int:
        """Get color for unit based on player and type."""
        if unit["player"] == 0:  # Player units
            return 0x244488 if unit["unit_type"] == "Intercessor" else 0xff3333
        else:  # AI units
            return 0x882222 if unit["unit_type"] == "Intercessor" else 0x6633cc
    
    def _get_unit_icon(self, unit: Dict) -> str:
        """Get icon path for unit."""
        if unit["unit_type"] == "Intercessor":
            return "/icons/Intercessor.webp"
        else:
            return "/icons/AssaultIntercessor.webp"
    
    def _get_distance(self, unit1: Dict, unit2: Dict) -> int:
        """Calculate distance between units."""
        return max(abs(unit1["col"] - unit2["col"]), abs(unit1["row"] - unit2["row"]))
    
    def _update_turn_phase(self):
        """Update turn and phase tracking with absolute turn numbers that never reset."""
        # Get current state from the training environment
        current_player = getattr(self.env, 'current_player', self.current_player)
        env_current_phase = getattr(self.env, 'current_phase', self.current_phase) 
        env_current_turn = getattr(self.env, 'current_turn', self.current_turn)
        
        # Track changes in environment's turn (which resets per episode)
        old_env_turn = getattr(self, '_last_env_turn', env_current_turn)
        old_phase = self.current_phase
        
        # Update phase tracking from environment
        self.current_phase = env_current_phase
        
        # Increment absolute turn when environment's turn changes or resets
        if env_current_turn != old_env_turn:
            # If env turn went backwards (new episode), or increased normally
            if env_current_turn < old_env_turn or env_current_turn > old_env_turn:
                self.absolute_turn += 1
        
        # Store environment's turn for next comparison
        self._last_env_turn = env_current_turn
        
        # Only log phase changes when they actually happen
        if old_phase != env_current_phase:
            player_name = "Player 1" if current_player == 0 else "Player 2"
            phase_message = format_phase_change_message(player_name, env_current_phase)
            
            self._add_event_immediate({
                "type": "phase_change",
                "message": phase_message,
                "reward": 0.0,
                "turnNumber": self.absolute_turn,  # Use absolute turn
                "phase": env_current_phase,
                "player": current_player,
                "unitType": None,
                "unitId": None,
                "targetUnitType": None,
                "targetUnitId": None,
                "startHex": None,
                "endHex": None,
                "actionName": "phase_change",
                "shootDetails": None
            })
        
        # Only log turn changes when they actually happen (based on absolute turn)
        if env_current_turn != old_env_turn:
            turn_message = format_turn_start_message(current_turn)
            self._add_event_immediate({
                "type": "turn_change", 
                "message": turn_message,
                "reward": 0.0,
                "turnNumber": current_turn,
                "phase": current_phase,
                "player": None,
                "unitType": None,
                "unitId": None,
                "targetUnitType": None,
                "targetUnitId": None,
                "startHex": None,
                "endHex": None,
                "actionName": "turn_change",
                "shootDetails": None
            })
            
        # Print turn/phase changes for visibility during training
        # DISABLED for less verbose training
        # if not self.quiet:
        #     print(f"🔄 {phase_message}")
        # if self.phase_index == 0:
        #     if not self.quiet:
        #         print(f"🔄 {turn_message}")

    def set_training_context(self, timestep: int, episode_num: int, model_info: Dict[str, Any]):
        """Set current training context for this episode."""
        self.training_context = {
            "timestep": timestep,
            "episode_num": episode_num,
            "model_info": model_info,
            "start_time": datetime.now().isoformat()
        }

    def capture_training_decision(self, action: int, q_values: np.ndarray = None, 
                                epsilon: float = None, is_exploration: bool = False,
                                model_confidence: float = None):
        """Capture AI training decision context."""
        decision_data = {
            "timestep": getattr(self, 'training_context', {}).get('timestep', 0),
            "action_chosen": action,
            "is_exploration": is_exploration,
            "epsilon": epsilon,
            "model_confidence": model_confidence
        }
        
        if q_values is not None:
            decision_data["q_values"] = q_values.tolist() if hasattr(q_values, 'tolist') else list(q_values)
            decision_data["best_q_value"] = float(np.max(q_values))
            decision_data["action_q_value"] = float(q_values[action]) if action < len(q_values) else None
        
        # Add to current game state if exists
        if self.game_states and len(self.game_states) > 0:
            if "training_data" not in self.game_states[-1]:
                self.game_states[-1]["training_data"] = {}
            self.game_states[-1]["training_data"]["decision"] = decision_data
    
    def save_replay(self, filename: str, episode_reward: float = 0.0):
        """Save the complete game replay."""
        # Extract initial state from first game state
        initial_units = []
        if self.game_states and len(self.game_states) > 0:
            first_state = self.game_states[0]
            for unit in first_state.get("units", []):
                initial_units.append({
                    "id": unit.get("id", 0),
                    "unit_type": unit.get("unit_type", "Unknown"),
                    "player": unit.get("player", 0),
                    "col": unit.get("col", 0),
                    "row": unit.get("row", 0), 
                    "hp_max": unit.get("max_hp", 1),
                    "move": unit.get("movement", 6),
                    "rng_rng": 18,  # Default values for training
                    "rng_dmg": 1,
                    "cc_dmg": 1,
                    "is_ranged": unit.get("unit_type") in ["Intercessor", "Termagant"],
                    "is_melee": unit.get("unit_type") in ["AssaultIntercessor"]
                })
        
        # Actions generation removed - using combat_log only for unified format
        
        replay_data = {
            "game_info": {
                "scenario": self.game_metadata.get("scenario", "training_episode"),
                "ai_behavior": "phase_based_following_AI_GAME_OVERVIEW",
                "total_turns": self.current_turn,
                "winner": None,  # Set by capture_game_end if available
                "ai_units_final": 0,
                "enemy_units_final": 0
            },
            "metadata": {
                **self.game_metadata,
                "total_states": len(self.game_states),
                "final_turn": self.current_turn,
                "episode_reward": episode_reward,
                "format_version": "2.0",
                "replay_type": "training_enhanced",
                "total_combat_log_entries": len(getattr(self, 'combat_log_entries', []))
            },
            "initial_state": {
                "units": initial_units,
                "board_size": self.game_metadata.get("board_size", [24, 18])
            },
            "combat_log": getattr(self, 'combat_log_entries', []) or [],  # ✅ Ensure combat_log is always an array
            "game_states": self.game_states,
            "training_summary": self._generate_training_summary()
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"💾 Saved unified combat_log replay: {filename}")
        print(f"   📊 {len(self.game_states)} game states captured")
        print(f"   🎮 {self.current_turn} turns played")
        print(f"   💯 Final reward: {episode_reward:.2f}")
        print(f"   ⚔️ {len(getattr(self, 'combat_log_entries', []))} combat log entries (shared format)")

    # _generate_frontend_actions method removed - using combat_log only

    def _map_event_type_to_action(self, event_type: str) -> int:
        """Map combat_log event type back to action_type for compatibility."""
        type_map = {
            "move": 0,
            "shoot": 4,
            "charge": 5,
            "combat": 6,
            "wait": 7,
            "penalty": -1
        }
        return type_map.get(event_type, 0)

    def _get_event_type_from_action(self, action_int: int, pre_action_units: List[Dict], post_action_units: List[Dict]) -> str:
        """Determine event type based on action and unit changes."""
        # First, map action directly to type (more reliable than change detection)
        action_type_map = {
            0: "move",      # move_closer
            1: "move",      # move_away
            2: "move",      # move_safe
            3: "shoot",     # shoot_closest
            4: "shoot",     # shoot_weakest
            5: "charge",    # charge_closest
            6: "move",      # wait (often results in no movement)
            7: "combat"     # attack_adjacent
        }
        
        # Use direct action mapping as primary method
        event_type = action_type_map.get(action_int, "move")
        
        # Check for unit deaths (override other types)
        pre_alive = set(u.get("id") for u in pre_action_units if u.get("alive", True))
        post_alive = set(u.get("id") for u in post_action_units if u.get("alive", True))
        if len(post_alive) < len(pre_alive):
            return "death"
        
        return event_type
    
    def _format_combat_message(self, event_type: str, acting_unit: Optional[Dict], target_unit: Optional[Dict], 
                             action_int: int, start_hex: Optional[str] = None, end_hex: Optional[str] = None) -> str:
        """Format combat message using centralized formatting function."""
        # Use the centralized formatting function for standard messages
        return format_game_log_message(event_type, acting_unit, target_unit, start_hex, end_hex)
    
    def _extract_shooting_details(self, pre_action_units: List[Dict], post_action_units: List[Dict], 
                                acting_unit_id: Optional[int], target_unit_id: Optional[int]) -> Optional[List[Dict]]:
        """Extract shooting details if available (for compatibility with game format)."""
        if not acting_unit_id or not target_unit_id:
            return None
        
        # Find units
        pre_target = next((u for u in pre_action_units if u.get("id") == target_unit_id), None)
        post_target = next((u for u in post_action_units if u.get("id") == target_unit_id), None)
        
        if not pre_target or not post_target:
            return None
        
        # Calculate damage
        damage = pre_target.get("hp", 0) - post_target.get("hp", 0)
        if damage <= 0:
            return None
        
        # Create basic shooting detail (simplified for training)
        return [{
            "shotNumber": 1,
            "attackRoll": 6,  # Simplified - assume hit
            "strengthRoll": 6,  # Simplified - assume wound
            "hitResult": "HIT",
            "strengthResult": "SUCCESS",
            "hitTarget": 4,
            "woundTarget": 4,
            "saveTarget": 4,
            "saveRoll": 2,  # Simplified - assume failed save
            "saveSuccess": False,
            "damageDealt": damage
        }]

    def _generate_training_summary(self) -> Dict[str, Any]:
        """Generate summary of training data from this episode."""
        if not self.game_states:
            return {}
        
        training_decisions = []
        exploration_count = 0
        total_decisions = 0
        
        for state in self.game_states:
            if "training_data" in state and "decision" in state["training_data"]:
                decision = state["training_data"]["decision"]
                training_decisions.append(decision)
                total_decisions += 1
                if decision.get("is_exploration", False):
                    exploration_count += 1
        
        return {
            "total_decisions": total_decisions,
            "exploration_decisions": exploration_count,
            "exploitation_decisions": total_decisions - exploration_count,
            "exploration_rate": exploration_count / total_decisions if total_decisions > 0 else 0,
            "avg_model_confidence": np.mean([d.get("model_confidence", 0) for d in training_decisions if d.get("model_confidence") is not None]) if training_decisions else 0,
            "timestep_range": {
                "start": training_decisions[0].get("timestep", 0) if training_decisions else 0,
                "end": training_decisions[-1].get("timestep", 0) if training_decisions else 0
            }
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the captured replay."""
        if not self.game_states:
            return {"error": "No game states captured"}
        
        return {
            "total_states": len(self.game_states),
            "turns_played": self.current_turn,
            "units_at_start": len(self.game_states[0]["units"]) if self.game_states else 0,
            "units_at_end": len([u for u in self.game_states[-1]["units"] if u["alive"]]) if self.game_states else 0,
            "total_actions": len([s for s in self.game_states if s.get("event_flags", {}).get("action_id") is not None]),
            "board_size": self.game_metadata["board_size"]
        }

# Usage example in training/evaluation
class GameReplayIntegration:
    """Integration helper for adding replay logging to training/evaluation."""
    
    @staticmethod
    def enhance_training_env(env):
        """Add PvP-style direct logging to training environment."""
        # Create replay logger and attach to environment for direct logging
        env.replay_logger = GameReplayLogger(env)
        env.replay_logger.capture_initial_state()
        
        # Gym environment now logs directly during action execution
        # No need to wrap step() method - much simpler!
        return env
    
    @staticmethod
    def _get_actual_units_from_gym(env, action_int: int, pre_action_units: List[Dict], post_action_units: List[Dict]) -> tuple[Optional[int], Optional[int]]:
        """Get actual acting and target units PvP-style, using gym environment state instead of action decoding."""
        # Instead of decoding actions (which breaks with changing unit counts),
        # use the gym environment's internal state to find which units actually acted
        
        # Check if the gym environment tracks the last acting unit (ideal case)
        if hasattr(env, '_last_acting_unit') and env._last_acting_unit is not None:
            acting_unit_id = env._last_acting_unit.get('id')
            if hasattr(env, '_last_target_unit') and env._last_target_unit is not None:
                target_unit_id = env._last_target_unit.get('id')
            else:
                target_unit_id = None
            return acting_unit_id, target_unit_id
        
        # Fallback: Look for units that changed state (moved, lost HP, changed flags)
        acting_unit_id = None
        target_unit_id = None
        
        # Find unit that moved (position changed)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get('id') == post_unit.get('id'):
                # Check position change
                if (pre_unit.get('col') != post_unit.get('col') or 
                    pre_unit.get('row') != post_unit.get('row')):
                    acting_unit_id = post_unit.get('id')
                    break
                
                # Check status flag changes (has_moved, has_shot, has_charged, has_attacked)
                for flag in ['has_moved', 'has_shot', 'has_charged', 'has_attacked']:
                    if not pre_unit.get(flag, False) and post_unit.get(flag, False):
                        acting_unit_id = post_unit.get('id')
                        break
                if acting_unit_id:
                    break
        
        # Find target unit (took damage or died)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get('id') == post_unit.get('id'):
                # Check HP loss
                pre_hp = pre_unit.get('cur_hp', pre_unit.get('hp', 0))
                post_hp = post_unit.get('cur_hp', post_unit.get('hp', 0))
                if pre_hp > post_hp:
                    target_unit_id = post_unit.get('id')
                    break
                
                # Check if unit died
                if pre_unit.get('alive', True) and not post_unit.get('alive', True):
                    target_unit_id = post_unit.get('id')
                    break
        
        return acting_unit_id, target_unit_id
    
    @staticmethod
    def save_episode_replay(env, episode_reward: float, output_dir: str = "ai/event_log", is_best: bool = False):
        """Save the replay for this episode following AI_INSTRUCTIONS.md naming."""
        if hasattr(env, 'replay_logger'):
            if is_best:
                # Use required filename from AI_INSTRUCTIONS.md
                filename = os.path.join(output_dir, "train_best_game_replay.json")
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(output_dir, f"game_replay_{timestamp}.json")
            
            env.replay_logger.save_replay(filename, episode_reward)
            
            # Also save with legacy naming for compatibility
            if is_best:
                legacy_filename = os.path.join(output_dir, "train_best_event_log.json")
                env.replay_logger.save_replay(legacy_filename, episode_reward)
            
            return filename
        return None

# Example usage
if __name__ == "__main__":
    print("GameReplayLogger - Capture complete W40K game states")
    print("This module provides full game replay logging for training and evaluation.")
    print("Usage: Import and use GameReplayIntegration.enhance_training_env(env)")