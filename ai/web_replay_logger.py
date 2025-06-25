#!/usr/bin/env python3
"""
web_replay_logger.py - Direct Web-Compatible Replay Logger
Generates web-compatible replay files directly without simplified intermediates
"""

import json
import os
import copy
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime

class WebReplayLogger:
    def __init__(self, env):
        """Initialize with the W40K environment."""
        self.env = env
        self.web_events = []
        self.current_turn = 1
        self.current_phase = "move"
        self.game_metadata = {
            "board_size": env.board_size,
            "max_turns": env.max_turns,
            "scenario": "training_episode",
            "timestamp": datetime.now().isoformat(),
            "replay_format": "web_compatible_v1"
        }
        
        # Action name mapping
        self.action_names = {
            0: "move_closer",
            1: "move_away", 
            2: "move_to_safe",
            3: "shoot_closest",
            4: "shoot_weakest", 
            5: "charge_closest",
            6: "wait",
            7: "attack_adjacent"
        }
        
        # Phase mapping based on action types
        self.action_to_phase = {
            0: "move", 1: "move", 2: "move",  # Movement actions
            3: "shoot", 4: "shoot",           # Shooting actions
            5: "charge",                      # Charging
            7: "combat",                      # Combat
            6: "move"                         # Wait/end turn
        }
    
    def _normalize_action(self, action):
        """Convert action to integer if it's a numpy array."""
        if isinstance(action, np.ndarray):
            return int(action.item())
        elif hasattr(action, 'item'):
            return int(action.item())
        else:
            return int(action)
    
    def _convert_unit_to_web_format(self, unit_dict: Dict, unit_index: int) -> Dict[str, Any]:
        """Convert gym environment unit to web-compatible format."""
        return {
            "id": unit_index,
            "name": unit_dict.get("name", f"{unit_dict.get('unit_type', 'Unit')} {unit_index + 1}"),
            "type": unit_dict.get("unit_type", "Unknown"),
            "player": unit_dict.get("player", 0),
            "col": unit_dict.get("col", 0),
            "row": unit_dict.get("row", 0),
            "color": self._get_unit_color(unit_dict),
            "MOVE": unit_dict.get("move", 6),
            "HP_MAX": unit_dict.get("hp_max", unit_dict.get("cur_hp", 3)),
            "CUR_HP": unit_dict.get("cur_hp", unit_dict.get("hp_max", 3)),
            "RNG_RNG": unit_dict.get("rng_rng", 8),
            "RNG_DMG": unit_dict.get("rng_dmg", 2),
            "CC_DMG": unit_dict.get("cc_dmg", 1),
            "ICON": self._get_unit_icon(unit_dict),
            "alive": unit_dict.get("alive", True),
            "is_ranged": unit_dict.get("is_ranged", True),
            "is_melee": unit_dict.get("is_melee", True)
        }
    
    def _get_unit_color(self, unit_dict: Dict) -> int:
        """Get unit color based on type and player."""
        player = unit_dict.get("player", 0)
        unit_type = unit_dict.get("unit_type", "")
        
        if player == 0:  # Human player
            return 0x244488 if "Intercessor" in unit_type else 0xff3333
        else:  # AI player
            return 0x882222 if "Intercessor" in unit_type else 0x6633cc
    
    def _get_unit_icon(self, unit_dict: Dict) -> str:
        """Get unit icon path based on type."""
        unit_type = unit_dict.get("unit_type", "")
        if "Assault" in unit_type:
            return "/icons/AssaultIntercessor.webp"
        else:
            return "/icons/Intercessor.webp"
    
    def capture_initial_state(self):
        """Capture the initial game state."""
        initial_event = self._create_web_event(
            action=None,
            acting_unit_id=None,
            target_unit_id=None,
            phase="game_start",
            turn=0,
            reward=0.0
        )
        
        initial_event["event_flags"]["game_event"] = "battle_begins"
        initial_event["event_flags"]["description"] = "Initial deployment"
        
        self.web_events.append(initial_event)
        print(f"📸 Captured initial web-compatible state with {len(self.env.units)} units")
    
    def capture_action_state(self, action, reward: float, pre_action_units: List[Dict], 
                           post_action_units: List[Dict], acting_unit_id: Optional[int] = None,
                           target_unit_id: Optional[int] = None, description: str = ""):
        """Capture game state after an action in web-compatible format."""
        action_int = self._normalize_action(action)
        
        # Determine phase from action
        phase = self.action_to_phase.get(action_int, "move")
        
        # Determine acting unit if not provided
        if acting_unit_id is None:
            # Find the current player's first alive unit
            current_player = getattr(self.env, 'current_player', 1)
            for i, unit in enumerate(post_action_units):
                if unit.get("player", 0) == current_player and unit.get("alive", True):
                    acting_unit_id = i
                    break
        
        # Create web event
        web_event = self._create_web_event(
            action=action_int,
            acting_unit_id=acting_unit_id,
            target_unit_id=target_unit_id,
            phase=phase,
            turn=self.current_turn,
            reward=reward,
            units_data=post_action_units
        )
        
        # Add action-specific information
        web_event["event_flags"]["action_name"] = self.action_names.get(action_int, f"action_{action_int}")
        web_event["event_flags"]["action_id"] = action_int
        web_event["event_flags"]["reward"] = reward
        web_event["event_flags"]["description"] = description or f"AI performs {web_event['event_flags']['action_name']}"
        
        # Count alive units
        ai_units_alive = sum(1 for u in post_action_units if u.get("player", 0) == 1 and u.get("alive", True))
        enemy_units_alive = sum(1 for u in post_action_units if u.get("player", 0) == 0 and u.get("alive", True))
        
        web_event["event_flags"]["ai_units_alive"] = ai_units_alive
        web_event["event_flags"]["enemy_units_alive"] = enemy_units_alive
        
        # Detect changes
        changes = self._detect_unit_changes(pre_action_units, post_action_units)
        if changes:
            web_event["event_flags"]["changes"] = changes
        
        self.web_events.append(web_event)
        
        # Update turn counter for next action
        if action_int == 6:  # Wait action typically ends turn
            self.current_turn += 1
    
    def _create_web_event(self, action: Optional[int], acting_unit_id: Optional[int], 
                         target_unit_id: Optional[int], phase: str, turn: int, 
                         reward: float, units_data: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Create a web-compatible event structure."""
        
        # Convert units to web format
        if units_data is None:
            units_data = self.env.units
        
        web_units = []
        for i, unit in enumerate(units_data):
            web_unit = self._convert_unit_to_web_format(unit, i)
            web_units.append(web_unit)
        
        return {
            "turn": turn,
            "phase": phase,
            "acting_unit_idx": acting_unit_id,
            "target_unit_idx": target_unit_id,
            "event_flags": {
                "timestamp": datetime.now().isoformat(),
                "action_id": action,
                "reward": reward
            },
            "unit_stats": {},  # Can be populated with additional stats
            "units": web_units
        }
    
    def _detect_unit_changes(self, pre_units: List[Dict], post_units: List[Dict]) -> Dict[str, Any]:
        """Detect what changed between pre and post action states."""
        changes = {
            "movements": [],
            "damage": [],
            "deaths": [],
            "other": []
        }
        
        for i, (pre_unit, post_unit) in enumerate(zip(pre_units, post_units)):
            # Check for movement
            if (pre_unit.get("col") != post_unit.get("col") or 
                pre_unit.get("row") != post_unit.get("row")):
                changes["movements"].append({
                    "unit_id": i,
                    "from": {"col": pre_unit.get("col"), "row": pre_unit.get("row")},
                    "to": {"col": post_unit.get("col"), "row": post_unit.get("row")}
                })
            
            # Check for damage
            pre_hp = pre_unit.get("cur_hp", pre_unit.get("hp_max", 0))
            post_hp = post_unit.get("cur_hp", post_unit.get("hp_max", 0))
            if pre_hp > post_hp:
                changes["damage"].append({
                    "unit_id": i,
                    "damage": pre_hp - post_hp,
                    "hp_before": pre_hp,
                    "hp_after": post_hp
                })
            
            # Check for deaths
            if pre_unit.get("alive", True) and not post_unit.get("alive", True):
                changes["deaths"].append({
                    "unit_id": i,
                    "unit_name": post_unit.get("name", f"Unit {i}")
                })
        
        # Remove empty categories
        return {k: v for k, v in changes.items() if v}
    
    def capture_game_end(self, winner: str, final_reward: float):
        """Capture the game end state."""
        end_event = self._create_web_event(
            action=None,
            acting_unit_id=None,
            target_unit_id=None,
            phase="game_end",
            turn=self.current_turn,
            reward=final_reward
        )
        
        end_event["event_flags"]["game_event"] = "battle_concluded"
        end_event["event_flags"]["winner"] = winner
        end_event["event_flags"]["final_reward"] = final_reward
        end_event["event_flags"]["description"] = f"Battle concluded - {winner} wins!"
        
        self.web_events.append(end_event)
        print(f"🏁 Captured game end: {winner} wins with reward {final_reward}")
    
    def save_web_replay(self, filename: str, episode_reward: float):
        """Save the web-compatible replay to file."""
        web_replay_data = {
            "metadata": {
                **self.game_metadata,
                "episode_reward": episode_reward,
                "total_events": len(self.web_events),
                "final_turn": self.current_turn
            },
            "events": self.web_events
        }
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(web_replay_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved web-compatible replay: {filename}")
        print(f"   📊 {len(self.web_events)} events, reward: {episode_reward:.3f}")


class WebReplayIntegration:
    """Integration helper for adding web replay logging to environments."""
    
    @staticmethod
    def enhance_training_env(env):
        """Add web replay logging capability to training environment."""
        # Store original step method
        original_step = env.step
        
        # Create web replay logger
        env.web_replay_logger = WebReplayLogger(env)
        env.web_replay_logger.capture_initial_state()
        
        def enhanced_step(action):
            # Capture state before action
            pre_action_units = copy.deepcopy(env.units)
            
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
            action_int = env.web_replay_logger._normalize_action(action)
            
            # Log the action and its effects in web format
            env.web_replay_logger.capture_action_state(
                action=action_int,
                reward=reward,
                pre_action_units=pre_action_units,
                post_action_units=post_action_units,
                acting_unit_id=env.current_player,
                description=f"AI performs {env.web_replay_logger.action_names.get(action_int, 'unknown action')}"
            )
            
            # Check for game end
            if terminated or truncated:
                winner = "player" if env.winner == 0 else "ai" if env.winner == 1 else "draw"
                env.web_replay_logger.capture_game_end(winner, reward)
            
            # Return in the same format as received
            if len(step_result) == 5:
                return obs, reward, terminated, truncated, info
            else:
                return obs, reward, done, info
        
        # Replace step method
        env.step = enhanced_step
        return env
    
    @staticmethod
    def save_episode_replay(env, episode_reward: float, output_dir: str = "ai/event_log"):
        """Save the web-compatible replay for this episode."""
        if hasattr(env, 'web_replay_logger'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(output_dir, f"web_replay_{timestamp}.json")
            env.web_replay_logger.save_web_replay(filename, episode_reward)
            return filename
        return None
