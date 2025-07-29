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

def format_game_log_message(event_type: str, acting_unit: Optional[Dict], target_unit: Optional[Dict], 
                           start_hex: Optional[str] = None, end_hex: Optional[str] = None) -> str:
    """Format game log messages exactly like useGameLog.ts frontend."""
    
    if event_type == "death" and target_unit:
        return f"Unit {target_unit.get('id', '?')} ({target_unit.get('unit_type', 'unknown')}) DIED !"
    
    if event_type == "shoot" and acting_unit and target_unit:
        return f"Unit {acting_unit.get('id', '?')} SHOT at unit {target_unit.get('id', '?')}"
    
    if event_type == "combat" and acting_unit and target_unit:
        return f"Unit {acting_unit.get('id', '?')} FOUGHT unit {target_unit.get('id', '?')}"
    
    if event_type == "charge" and acting_unit and target_unit:
        if start_hex and end_hex:
            return f"Unit {acting_unit.get('id', '?')} CHARGED unit {target_unit.get('id', '?')} from {start_hex} to {end_hex}"
        else:
            return f"Unit {acting_unit.get('id', '?')} CHARGED unit {target_unit.get('id', '?')}"
    
    if event_type == "move" and acting_unit:
        if start_hex and end_hex:
            return f"Unit {acting_unit.get('id', '?')} MOVED from {start_hex} to {end_hex}"
        else:
            return f"Unit {acting_unit.get('id', '?')} NO MOVE"
    
    # Fallback for unknown event types
    return "Unknown action"

class GameReplayLogger:
    def __init__(self, env):
        """Initialize with the W40K environment."""
        self.env = env
        self.game_states = []
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
        """Capture the initial game state."""
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
        """Generate combat log entry with same format as game frontend."""
        # Initialize combat log if not exists
        if not hasattr(self, 'combat_log_entries'):
            self.combat_log_entries = []
        
        # Determine event type based on action
        event_type = self._get_event_type_from_action(action_int, pre_action_units, post_action_units)
        
        # Find acting unit
        acting_unit = None
        if acting_unit_id is not None:
            acting_unit = next((u for u in post_action_units if u.get("id") == acting_unit_id), None)
        
        # Find target unit
        target_unit = None
        if target_unit_id is not None:
            target_unit = next((u for u in post_action_units if u.get("id") == target_unit_id), None)
        
        # Calculate position changes for movement actions (centralized position tracking)
        start_hex = None
        end_hex = None
        if acting_unit_id is not None:
            pre_unit = next((u for u in pre_action_units if u.get("id") == acting_unit_id), None)
            post_unit = next((u for u in post_action_units if u.get("id") == acting_unit_id), None)
            if pre_unit and post_unit:
                # Check if position actually changed
                if (pre_unit.get('col', 0) != post_unit.get('col', 0) or 
                    pre_unit.get('row', 0) != post_unit.get('row', 0)):
                    start_hex = f"({pre_unit.get('col', 0)}, {pre_unit.get('row', 0)})"
                    end_hex = f"({post_unit.get('col', 0)}, {post_unit.get('row', 0)})"
        
        # Create combat log entry with game format including position data
        combat_entry = {
            "id": len(self.combat_log_entries) + 1,
            "type": event_type,
            "message": self._format_combat_message(event_type, acting_unit, target_unit, action_int, start_hex, end_hex),
            "reward": reward,  # REPLACE timestamp with reward
            "turnNumber": self.current_turn,
            "phase": self.current_phase,
            "player": acting_unit.get("player", 1) if acting_unit else 1,
            "unitType": acting_unit.get("type", "unknown") if acting_unit else "unknown",
            "unitId": acting_unit.get("id") if acting_unit else None,
            "targetUnitType": target_unit.get("type") if target_unit else None,
            "targetUnitId": target_unit.get("id") if target_unit else None,
            "startHex": start_hex,  # Add position tracking
            "endHex": end_hex,      # Add position tracking
            "actionName": self.action_names.get(action_int, f"action_{action_int}"),
            "shootDetails": self._extract_shooting_details(pre_action_units, post_action_units, acting_unit_id, target_unit_id)
        }
        
        self.combat_log_entries.append(combat_entry)
        
        # Print combat log entry for immediate visibility during training with action name
        reward_str = f"+{reward:.2f}" if reward >= 0 else f"{reward:.2f}"
        player_str = f"P{combat_entry['player']}"
        action_name = self.action_names.get(action_int, f"action_{action_int}")
        print(f"🎯 [{player_str}] T{self.current_turn} {self.current_phase.upper()}: {combat_entry['message']} (R: {reward_str}) [{action_name}]")
    
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
        """Update turn and phase tracking."""
        # Simple phase progression - you can make this more sophisticated
        self.phase_index = (self.phase_index + 1) % len(self.phases)
        self.current_phase = self.phases[self.phase_index]
        
        if self.phase_index == 0:  # Back to move phase
            self.current_turn += 1

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
        replay_data = {
            "metadata": {
                **self.game_metadata,
                "total_states": len(self.game_states),
                "final_turn": self.current_turn,
                "episode_reward": episode_reward,
                "duration_minutes": len(self.game_states) * 0.1,
                "training_context": getattr(self, 'training_context', {}),
                "format_version": "2.0",
                "replay_type": "training_enhanced",
                "total_combat_log_entries": len(getattr(self, 'combat_log_entries', []))
            },
            "game_states": self.game_states,
            "combat_log": getattr(self, 'combat_log_entries', []),  # ADD: Include combat log
            "training_summary": self._generate_training_summary()
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"💾 Saved game replay: {filename}")
        print(f"   📊 {len(self.game_states)} game states captured")
        print(f"   🎮 {self.current_turn} turns played")
        print(f"   💯 Final reward: {episode_reward:.2f}")

    def _get_event_type_from_action(self, action_int: int, pre_action_units: List[Dict], post_action_units: List[Dict]) -> str:
        """Determine event type based on action and unit changes."""
        # Check for unit deaths first
        pre_alive = set(u.get("id") for u in pre_action_units if u.get("alive", True))
        post_alive = set(u.get("id") for u in post_action_units if u.get("alive", True))
        if len(post_alive) < len(pre_alive):
            return "death"
        
        # Check for HP changes (combat/shooting)
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if pre_unit.get("hp", 0) > post_unit.get("hp", 0):
                # Damage occurred - determine if shooting or combat
                if action_int in [3, 4]:  # shoot_closest, shoot_weakest
                    return "shoot"
                elif action_int in [7]:  # attack_adjacent
                    return "combat"
        
        # Check for movement
        for pre_unit, post_unit in zip(pre_action_units, post_action_units):
            if (pre_unit.get("col") != post_unit.get("col") or 
                pre_unit.get("row") != post_unit.get("row")):
                if action_int in [5]:  # charge_closest
                    return "charge"
                else:
                    return "move"
        
        # Check for phase changes
        if action_int == 6:  # wait action usually advances phase
            return "phase_change"
        
        # Default based on action type
        action_type_map = {
            0: "move",      # move_closer
            1: "move",      # move_away
            2: "move",      # move_safe
            3: "shoot",     # shoot_closest
            4: "shoot",     # shoot_weakest
            5: "charge",    # charge_closest
            6: "phase_change",  # wait
            7: "combat"     # attack_adjacent
        }
        return action_type_map.get(action_int, "default")
    
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
            
            # Log the action and its effects
            env.replay_logger.capture_action_state(
                action=action_int,
                reward=reward,
                pre_action_units=pre_action_units,
                post_action_units=post_action_units,
                acting_unit_id=env.current_player,  # Approximate
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