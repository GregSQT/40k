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
        self.game_metadata = {
            "board_size": env.board_size,
            "max_turns": env.max_turns,
            "scenario": "training_episode",
            "timestamp": datetime.now().isoformat()
        }
        
        # Phase tracking
        self.phases = ["move", "shoot", "charge", "combat"]
        self.phase_index = 0
        
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
            
        # Add game start message
        start_message = format_turn_start_message(1)
        start_entry = {
            "id": 1,
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
        }
        self.combat_log_entries.append(start_entry)
        
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
        self._update_turn_phase()
    
    def _generate_combat_log_entry(self, action_int: int, reward: float, pre_action_units: List[Dict], 
                                 post_action_units: List[Dict], acting_unit_id: Optional[int] = None,
                                 target_unit_id: Optional[int] = None, description: str = ""):
        """Generate combat log entry EXACTLY like PvP useGameLog.ts does."""
        if not hasattr(self, 'combat_log_entries'):
            self.combat_log_entries = []
        
        # FORCE find acting unit - never allow None
        acting_unit = None
        if acting_unit_id is not None:
            acting_unit = next((u for u in post_action_units if u.get("id") == acting_unit_id), None)
            if not acting_unit:
                acting_unit = next((u for u in pre_action_units if u.get("id") == acting_unit_id), None)
        
        # CRITICAL: Acting unit MUST be found - if not, this is a bug in our detection logic
        if not acting_unit:
            available_ids = [u.get('id') for u in post_action_units]
            raise RuntimeError(f"CRITICAL ERROR: No acting unit found for action {action_int}, acting_unit_id={acting_unit_id}. Available unit IDs: {available_ids}. This indicates a bug in _determine_acting_unit_id method.")
        
        # Find target unit for shooting/combat actions
        target_unit = None
        if target_unit_id is not None:
            target_unit = next((u for u in post_action_units if u.get("id") == target_unit_id), None)
            if not target_unit:
                target_unit = next((u for u in pre_action_units if u.get("id") == target_unit_id), None)
        
        # Decode action and create log entry
        max_actions_per_unit = 8
        action_type = action_int % max_actions_per_unit
        event_type = "move"
        message = ""
        start_hex = None
        end_hex = None
        
        # Movement actions (0,1,2,6)
        if action_type in [0, 1, 2, 6]:
            event_type = "move"
            pre_unit = next((u for u in pre_action_units if u.get("id") == acting_unit_id), None)
            if not pre_unit:
                raise RuntimeError(f"CRITICAL ERROR: No pre-action unit data found for movement action {action_int}, unit_id={acting_unit_id}. Cannot determine movement path.")
            
            start_col, start_row = pre_unit.get('col', 0), pre_unit.get('row', 0)
            end_col, end_row = acting_unit.get('col', 0), acting_unit.get('row', 0)
            
            if start_col != end_col or start_row != end_row:
                message = format_move_message(acting_unit['id'], start_col, start_row, end_col, end_row)
                start_hex = f"({start_col}, {start_row})"
                end_hex = f"({end_col}, {end_row})"
            else:
                message = format_no_move_message(acting_unit['id'])
        
        # Shooting actions (3,4) - REQUIRE target unit
        elif action_type in [3, 4]:
            if not target_unit:
                raise RuntimeError(f"CRITICAL ERROR: No target unit found for shooting action {action_int} (action_type={action_type}), target_unit_id={target_unit_id}. Shooting actions MUST have a target. This indicates a bug in _determine_target_unit_id method.")
            event_type = "shoot"
            message = format_shooting_message(acting_unit['id'], target_unit['id'])
        
        # Combat action (7) - REQUIRE target unit  
        elif action_type == 7:
            if not target_unit:
                raise RuntimeError(f"CRITICAL ERROR: No target unit found for combat action {action_int} (action_type=7), target_unit_id={target_unit_id}. Combat actions MUST have a target. This indicates a bug in _determine_target_unit_id method.")
            event_type = "combat"
            message = format_combat_message(acting_unit['id'], target_unit['id'])
        
        # Charge action (5) - REQUIRE target unit and movement
        elif action_type == 5:
            if not target_unit:
                raise RuntimeError(f"CRITICAL ERROR: No target unit found for charge action {action_int} (action_type=5), target_unit_id={target_unit_id}. Charge actions MUST have a target. This indicates a bug in _determine_target_unit_id method.")
            
            pre_unit = next((u for u in pre_action_units if u.get("id") == acting_unit_id), None)
            if not pre_unit:
                raise RuntimeError(f"CRITICAL ERROR: No pre-action unit data found for charge action {action_int}, unit_id={acting_unit_id}. Cannot determine charge path.")
            
            event_type = "charge"
            start_col, start_row = pre_unit.get('col', 0), pre_unit.get('row', 0)
            end_col, end_row = acting_unit.get('col', 0), acting_unit.get('row', 0)
            message = format_charge_message(
                acting_unit.get('unit_type', 'Unit'), acting_unit['id'],
                target_unit.get('unit_type', 'Unit'), target_unit['id'],
                start_col, start_row, end_col, end_row
            )
            start_hex = f"({start_col}, {start_row})"
            end_hex = f"({end_col}, {end_row})"
        
        else:
            raise RuntimeError(f"CRITICAL ERROR: Unknown action type {action_type} for action {action_int}. Valid action types are 0-7.")
        
        # Create PvP-compatible log entry
        event_id = f"event_{len(self.combat_log_entries) + 1}_{int(datetime.now().timestamp() * 1000)}"
        
        combat_entry = {
            "id": event_id,
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "message": message,
            "turnNumber": self.current_turn,
            "phase": self.current_phase,
            "player": acting_unit.get("player"),
            "unitType": acting_unit.get("unit_type"),
            "unitId": acting_unit.get("id"),
            "targetUnitType": target_unit.get("unit_type") if target_unit else None,
            "targetUnitId": target_unit.get("id") if target_unit else None,
            "startHex": start_hex,
            "endHex": end_hex,
            "shootDetails": self._extract_shooting_details(pre_action_units, post_action_units, acting_unit_id, target_unit_id),
            "reward": reward,
            "actionName": self.action_names.get(action_int, f"action_{action_int}")
        }
        
        self.combat_log_entries.append(combat_entry)
        
        # Print combat log entry for immediate visibility during training with action name
        # DISABLED for less verbose training
        # if not self.quiet:
        #     reward_str = f"+{reward:.2f}" if reward >= 0 else f"{reward:.2f}"
        #     player_str = f"P{combat_entry['player']}"
        #     action_name = self.action_names.get(action_int, f"action_{action_int}")
        #     print(f"🎯 [{player_str}] T{self.current_turn} {self.current_phase.upper()}: {combat_entry['message']} (R: {reward_str}) [{action_name}]")
    
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
        """Update turn and phase tracking with proper log entries."""
        # Get current player before phase change
        current_player = getattr(self.env, 'current_player', 0)
        
        # Simple phase progression - you can make this more sophisticated
        old_phase = self.current_phase
        self.phase_index = (self.phase_index + 1) % len(self.phases)
        self.current_phase = self.phases[self.phase_index]
        
        # Generate phase change log entry
        if not hasattr(self, 'combat_log_entries'):
            self.combat_log_entries = []
            
        player_name = "Player 1" if current_player == 0 else "Player 2"
        phase_message = format_phase_change_message(player_name, self.current_phase)
        
        phase_entry = {
            "id": len(self.combat_log_entries) + 1,
            "type": "phase_change",
            "message": phase_message,
            "reward": 0.0,
            "turnNumber": self.current_turn,
            "phase": self.current_phase,
            "player": current_player,
            "unitType": None,
            "unitId": None,
            "targetUnitType": None,
            "targetUnitId": None,
            "startHex": None,
            "endHex": None,
            "actionName": "phase_change",
            "shootDetails": None
        }
        
        self.combat_log_entries.append(phase_entry)
        
        # If back to move phase, increment turn and add turn start message
        if self.phase_index == 0:  
            self.current_turn += 1
            
            turn_message = format_turn_start_message(self.current_turn)
            turn_entry = {
                "id": len(self.combat_log_entries) + 1,
                "type": "turn_change", 
                "message": turn_message,
                "reward": 0.0,
                "turnNumber": self.current_turn,
                "phase": self.current_phase,
                "player": None,
                "unitType": None,
                "unitId": None,
                "targetUnitType": None,
                "targetUnitId": None,
                "startHex": None,
                "endHex": None,
                "actionName": "turn_change",
                "shootDetails": None
            }
            
            self.combat_log_entries.append(turn_entry)
            
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
        """Add replay logging capability to training environment."""
        # Store original step method
        original_step = env.step
        
        # Create replay logger
        env.replay_logger = GameReplayLogger(env)
        env.replay_logger.capture_initial_state()
        
        def enhanced_step(action):
            # Capture state before action
            pre_action_units = copy.deepcopy(env.units)
            
            # Capture training decision context if available
            if hasattr(env, '_last_training_info'):
                training_info = env._last_training_info
                env.replay_logger.capture_training_decision(
                    action=action,
                    q_values=training_info.get('q_values'),
                    epsilon=training_info.get('epsilon'),
                    is_exploration=training_info.get('is_exploration', False),
                    model_confidence=training_info.get('model_confidence')
                )
            
            # Execute original step
            step_result = original_step(action)
            
            # Handle both old and new Gym API
            if len(step_result) == 5:  # New Gym API
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:  # Old Gym API
                obs, reward, done, info = step_result
                terminated = done
                truncated = False
            
            # Capture state after action
            post_action_units = copy.deepcopy(env.units)
            
            # Normalize action for logging
            action_int = env.replay_logger._normalize_action(action)
            
            # CRITICAL FIX: Use PvP-style unit identification - get actual units from gym environment
            # instead of trying to decode from actions which fails when unit counts change
            acting_unit_id, target_unit_id = GameReplayIntegration._get_actual_units_from_gym(env, action_int, pre_action_units, post_action_units)
            
            # Log the action and its effects (PvP-style approach)
            env.replay_logger.capture_action_state(
                action=action_int,
                reward=reward,
                pre_action_units=pre_action_units,
                post_action_units=post_action_units,
                acting_unit_id=acting_unit_id,
                target_unit_id=target_unit_id,
                description=f"AI performs {env.replay_logger.action_names.get(action_int, 'unknown action')}"
            )
            
            # Check for game end
            if terminated or truncated:
                winner = "player" if env.winner == 0 else "ai" if env.winner == 1 else "draw"
                env.replay_logger.capture_game_end(winner, reward)
            
            # Return in the same format as received
            if len(step_result) == 5:
                return obs, reward, terminated, truncated, info
            else:
                return obs, reward, done, info
        
        # Replace step method
        env.step = enhanced_step
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
    def _determine_acting_unit_id(env, action_int: int, post_action_units: List[Dict], pre_action_units: List[Dict] = None) -> Optional[int]:
        """Determine which unit actually performed the action by decoding the gym action."""
        # Decode the action to get unit index
        max_actions_per_unit = 8  # gym40k uses 8 actions per unit
        unit_idx = action_int // max_actions_per_unit
        
        # Get current player
        current_player = getattr(env, 'current_player', 1)
        
        # CRITICAL FIX: Use pre-action units for action space calculation since gym calculates 
        # action space based on units available BEFORE the action executes
        if pre_action_units is not None:
            # Use pre-action units to match gym's action space calculation
            action_space_units = [u for u in pre_action_units 
                                if u.get('player') == current_player and u.get('alive', True)]
        else:
            # Fallback to post-action units if pre-action not available
            action_space_units = [u for u in post_action_units 
                                if u.get('player') == current_player and u.get('alive', True)]
        
        # Validate unit index against action space calculation
        if unit_idx >= len(action_space_units):
            available_unit_ids = [u.get('id') for u in post_action_units]
            current_player_unit_ids = [u.get('id') for u in action_space_units]
            raise RuntimeError(f"CRITICAL ERROR in _determine_acting_unit_id: Action {action_int} decoded to unit_idx={unit_idx}, but only {len(action_space_units)} units were available when action space was calculated for player {current_player}. "
                             f"Available unit IDs in post_action_units: {available_unit_ids}. "
                             f"Action space player {current_player} unit IDs: {current_player_unit_ids}. "
                             f"This indicates the gym action space was calculated with {unit_idx + 1} units but only {len(action_space_units)} existed.")
        
        # Return the actual unit ID that performed the action
        acting_unit_id = action_space_units[unit_idx].get('id')
        
        # Verify the acting unit still exists in post-action units (might be dead but still findable)
        post_acting_unit = next((u for u in post_action_units if u.get('id') == acting_unit_id), None)
        if not post_acting_unit:
            # Unit might have died, search in pre-action units as fallback
            if pre_action_units:
                pre_acting_unit = next((u for u in pre_action_units if u.get('id') == acting_unit_id), None)
                if not pre_acting_unit:
                    raise RuntimeError(f"CRITICAL ERROR in _determine_acting_unit_id: Acting unit {acting_unit_id} not found in either pre or post action units")
        
        return acting_unit_id
    
    @staticmethod
    def _determine_target_unit_id(env, action_int: int, pre_action_units: List[Dict], post_action_units: List[Dict]) -> Optional[int]:
        """Determine which unit was targeted by the action."""
        max_actions_per_unit = 8
        action_type = action_int % max_actions_per_unit
        
        # Actions that have targets: shooting (3,4), charge (5), combat (7)
        if action_type not in [3, 4, 5, 7]:
            return None
        
        # Method 1: Find units that took HP damage (for shooting/combat)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get('id') != post_unit.get('id'):
                continue
            
            # Check all HP field variations
            pre_hp = pre_unit.get('cur_hp', pre_unit.get('hp', pre_unit.get('CUR_HP', pre_unit.get('HP', 0))))
            post_hp = post_unit.get('cur_hp', post_unit.get('hp', post_unit.get('CUR_HP', post_unit.get('HP', 0))))
            
            if pre_hp > post_hp and post_hp >= 0:  # Unit took damage
                return post_unit.get('id')
        
        # Method 2: Find units that died (alive -> dead)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get('id') != post_unit.get('id'):
                continue
            if pre_unit.get('alive', True) and not post_unit.get('alive', True):
                return post_unit.get('id')
        
        # Method 3: For charge actions, find unit that is now adjacent to the acting unit
        if action_type == 5:  # charge_closest - NEVER causes damage, only moves adjacent
            acting_unit_id = GameReplayIntegration._determine_acting_unit_id(env, action_int, post_action_units, pre_action_units)
            if not acting_unit_id:
                raise RuntimeError(f"CRITICAL ERROR: Cannot determine acting unit for charge action {action_int}")
            
            acting_unit = next((u for u in post_action_units if u.get('id') == acting_unit_id), None)
            if not acting_unit:
                raise RuntimeError(f"CRITICAL ERROR: Cannot find acting unit {acting_unit_id} in post_action_units for charge action {action_int}")
            
            acting_player = acting_unit.get('player', 0)
            enemy_units = [u for u in post_action_units 
                         if u.get('player') != acting_player and u.get('alive', True)]
            
            if not enemy_units:
                raise RuntimeError(f"CRITICAL ERROR: Charge action {action_int} executed but no enemy units exist. This should not be possible.")
            
            # Find enemy that is now adjacent (distance = 1) to the acting unit after charge
            adjacent_enemies = []
            for enemy in enemy_units:
                dist = abs(acting_unit.get('col', 0) - enemy.get('col', 0)) + abs(acting_unit.get('row', 0) - enemy.get('row', 0))
                if dist == 1:  # Adjacent after charge
                    adjacent_enemies.append(enemy)
            
            if len(adjacent_enemies) == 1:
                return adjacent_enemies[0].get('id')
            elif len(adjacent_enemies) > 1:
                # Multiple adjacent enemies - find the closest one (tie-breaker)
                min_dist = float('inf')
                closest_enemy = None
                for enemy in adjacent_enemies:
                    # Use more precise distance calculation as tie-breaker
                    precise_dist = ((acting_unit.get('col', 0) - enemy.get('col', 0))**2 + 
                                  (acting_unit.get('row', 0) - enemy.get('row', 0))**2)**0.5
                    if precise_dist < min_dist:
                        min_dist = precise_dist
                        closest_enemy = enemy
                return closest_enemy.get('id') if closest_enemy else None
            else:
                # No adjacent enemies after charge - this is a failed charge attempt
                # Find the enemy the unit was trying to charge (closest enemy overall)
                min_dist = float('inf')
                target_enemy = None
                for enemy in enemy_units:
                    dist = abs(acting_unit.get('col', 0) - enemy.get('col', 0)) + abs(acting_unit.get('row', 0) - enemy.get('row', 0))
                    if dist < min_dist:
                        min_dist = dist
                        target_enemy = enemy
                
                if not target_enemy:
                    raise RuntimeError(f"CRITICAL ERROR: Charge action {action_int} failed to find any target enemy. Available enemies: {[e.get('id') for e in enemy_units]}")
                
                return target_enemy.get('id')
        
        # Method 4: Use gym environment's target selection logic based on action type
        acting_unit_id = GameReplayIntegration._determine_acting_unit_id(env, action_int, post_action_units, pre_action_units)
        if acting_unit_id:
            acting_unit = next((u for u in post_action_units if u.get('id') == acting_unit_id), None)
            if acting_unit:
                acting_player = acting_unit.get('player', 0)
                enemy_units = [u for u in post_action_units 
                             if u.get('player') != acting_player and u.get('alive', True)]
                
                if not enemy_units:
                    # No enemies available - this should raise an error
                    raise RuntimeError(f"CRITICAL ERROR in _determine_target_unit_id: Action {action_int} (action_type={action_type}) requires a target, but no enemy units are available. "
                                     f"Acting unit: {acting_unit_id}, Acting player: {acting_player}. "
                                     f"This indicates the gym environment executed a targeting action when no valid targets exist.")
                
                # For shoot_closest (3), charge_closest (5), or attack_adjacent (7): find closest enemy
                if action_type in [3, 5, 7]:
                    min_dist = float('inf')
                    closest_enemy = None
                    for enemy in enemy_units:
                        dist = abs(acting_unit.get('col', 0) - enemy.get('col', 0)) + abs(acting_unit.get('row', 0) - enemy.get('row', 0))
                        if dist < min_dist:
                            min_dist = dist
                            closest_enemy = enemy
                    
                    if not closest_enemy:
                        raise RuntimeError(f"CRITICAL ERROR in _determine_target_unit_id: Could not find closest enemy for action {action_int} (action_type={action_type}). "
                                         f"Enemy units exist but distance calculation failed.")
                    return closest_enemy.get('id')
                
                # For shoot_weakest (4): find enemy with lowest HP
                elif action_type == 4:
                    min_hp = float('inf')
                    weakest_enemy = None
                    for enemy in enemy_units:
                        enemy_hp = enemy.get('cur_hp', enemy.get('hp', enemy.get('CUR_HP', enemy.get('HP', 0))))
                        if enemy_hp < min_hp:
                            min_hp = enemy_hp
                            weakest_enemy = enemy
                    
                    if not weakest_enemy:
                        raise RuntimeError(f"CRITICAL ERROR in _determine_target_unit_id: Could not find weakest enemy for action {action_int} (action_type=4). "
                                         f"Enemy units exist but HP comparison failed.")
                    return weakest_enemy.get('id')
        
        # If we get here, target detection completely failed
        raise RuntimeError(f"CRITICAL ERROR in _determine_target_unit_id: All target detection methods failed for action {action_int} (action_type={action_type}). "
                         f"This indicates a fundamental bug in the target detection logic.")
    
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