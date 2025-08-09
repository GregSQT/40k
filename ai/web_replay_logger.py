#!/usr/bin/env python3
"""
web_replay_logger.py - Direct Web-Compatible Replay Logger
"""

import json
import os
import copy
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime

class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)

class WebReplayLogger:
    def __init__(self, env):
        """Initialize with the W40K environment."""
        self.env = env
        self.web_events = []
        self.current_turn = 1
        self.game_metadata = {
            "board_size": getattr(env, 'board_size'),
            "max_turns": getattr(env, 'max_turns'),
            "scenario": "training_episode",
            "timestamp": datetime.now().isoformat(),
            "replay_format": "web_compatible_v1"
        }
        
        # Action name mapping
        self.action_names = {
            0: "move_closer", 1: "move_away", 2: "move_to_safe",
            3: "shoot_closest", 4: "shoot_weakest", 5: "charge_closest",
            6: "wait", 7: "attack_adjacent"
        }
        
        # Phase mapping
        self.action_to_phase = {
            0: "move", 1: "move", 2: "move", 3: "shoot", 4: "shoot",
            5: "charge", 7: "combat", 6: "move"
        }
    
    
    def _convert_numpy_data(self, data):
        """Recursively convert numpy arrays to lists."""
        if isinstance(data, np.ndarray):
            return data.tolist()
        elif isinstance(data, np.integer):
            return int(data)
        elif isinstance(data, np.floating):
            return float(data)
        elif isinstance(data, np.bool_):
            return bool(data)
        elif isinstance(data, dict):
            return {key: self._convert_numpy_data(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._convert_numpy_data(item) for item in data]
        else:
            return data

    def _normalize_action(self, action):
        """Convert action to integer."""
        if isinstance(action, np.ndarray):
            return int(action.item())
        elif hasattr(action, 'item'):
            return int(action.item())
        else:
            return int(action)
    
    def _convert_unit_to_web_format(self, unit_dict: Dict, unit_index: int) -> Dict[str, Any]:
        """Convert gym environment unit to web format."""
        cur_hp = unit_dict.get("cur_hp", unit_dict.get("hp_max", 3))
        is_alive = unit_dict.get("alive", True) and cur_hp > 0
        
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
            "CUR_HP": cur_hp,
            "RNG_RNG": unit_dict.get("rng_rng", 8),
            "RNG_DMG": unit_dict.get("rng_dmg", 2),
            "CC_DMG": unit_dict.get("cc_dmg", 1),
            "ICON": self._get_unit_icon(unit_dict),
            "alive": is_alive
        }
    
    def _get_unit_color(self, unit_dict: Dict) -> int:
        """Get unit color."""
        player = unit_dict.get("player", 0)
        unit_type = unit_dict.get("unit_type", "")
        if player == 0:
            return 0x244488 if "Intercessor" in unit_type else 0xff3333
        else:
            return 0x882222 if "Intercessor" in unit_type else 0x6633cc
    
    def _get_unit_icon(self, unit_dict: Dict) -> str:
        """Get unit icon."""
        unit_type = unit_dict.get("unit_type", "")
        if "Assault" in unit_type:
            return "/icons/AssaultIntercessor.webp"
        else:
            return "/icons/Intercessor.webp"
    
    def capture_initial_state(self):
        """Capture initial state."""
        initial_event = self._create_web_event(None, None, None, "game_start", 0, 0.0)
        initial_event["event_flags"]["description"] = "Initial deployment"
        self.web_events.append(initial_event)
        print(f"📸 Captured initial web state with {len(getattr(self.env, 'units', []))} units")
    
    def capture_action_state(self, action, reward, pre_action_units, post_action_units, 
                           acting_unit_id=None, target_unit_id=None, description=""):
        """Capture action state."""
        action_int = self._normalize_action(action)
        phase = self.action_to_phase.get(action_int, "move")
        
        if acting_unit_id is None:
            current_player = getattr(self.env, 'current_player', 1)
            for i, unit in enumerate(post_action_units):
                if unit.get("player", 0) == current_player and unit.get("alive", True):
                    acting_unit_id = i
                    break
        
        web_event = self._create_web_event(action_int, acting_unit_id, target_unit_id, 
                                         phase, self.current_turn, reward, post_action_units)
        
        web_event["event_flags"]["action_name"] = self.action_names.get(action_int, f"action_{action_int}")
        web_event["event_flags"]["action_id"] = action_int
        web_event["event_flags"]["reward"] = reward
        web_event["event_flags"]["description"] = description
        
        # Enhanced: Add detailed action data if available
        if hasattr(self.env, 'detailed_action_log') and self.env.detailed_action_log:
            latest_action = self.env.detailed_action_log[-1]
            web_event["detailed_action_data"] = latest_action
        
        ai_units_alive = sum(1 for u in post_action_units if u.get("player", 0) == 1 and u.get("alive", True))
        enemy_units_alive = sum(1 for u in post_action_units if u.get("player", 0) == 0 and u.get("alive", True))
        
        web_event["event_flags"]["ai_units_alive"] = ai_units_alive
        web_event["event_flags"]["enemy_units_alive"] = enemy_units_alive
        
        self.web_events.append(web_event)
        
        if action_int == 6:
            self.current_turn += 1
    
    def _create_web_event(self, action, acting_unit_id, target_unit_id, phase, turn, reward, units_data=None):
        """Create web event."""
        if units_data is None:
            units_data = getattr(self.env, 'units', [])
        
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
            "unit_stats": {},
            "units": web_units
        }
    
    def capture_game_end(self, winner, final_reward):
        """Capture game end."""
        end_event = self._create_web_event(None, None, None, "game_end", self.current_turn, final_reward)
        end_event["event_flags"]["winner"] = winner
        end_event["event_flags"]["description"] = f"Battle concluded - {winner} wins!"
        self.web_events.append(end_event)
        print(f"🏁 Game end: {winner} wins with reward {final_reward}")
    
    def save_web_replay(self, filename, episode_reward):
        """Save web replay."""
        web_replay_data = {
            "metadata": {
                **self.game_metadata,
                "episode_reward": episode_reward,
                "total_events": len(self.web_events),
                "final_turn": self.current_turn,
                "format_version": "2.0",
                "replay_type": "web_enhanced",
                "training_context": getattr(self, 'training_context', {}),
                "web_compatible": True
            },
            "events": self.web_events,
            "training_summary": self._generate_training_summary()
        }
        
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(web_replay_data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        print(f"💾 Saved web replay: {filename} ({len(self.web_events)} events)")


class WebReplayIntegration:
    def set_training_context(self, timestep: int, episode_num: int, model_info: Dict[str, Any]):
        """Set current training context for this episode."""
        self.training_context = {
            "timestep": timestep,
            "episode_num": episode_num,
            "model_info": model_info,
            "start_time": datetime.now().isoformat()
        }

    def _generate_training_summary(self) -> Dict[str, Any]:
        """Generate training summary from web events."""
        exploration_count = 0
        total_decisions = 0
        
        for event in self.web_events:
            if event.get("event_flags", {}).get("action_id") is not None:
                total_decisions += 1
                if event.get("training_data", {}).get("is_exploration", False):
                    exploration_count += 1
        
        return {
            "total_decisions": total_decisions,
            "exploration_decisions": exploration_count,
            "exploitation_decisions": total_decisions - exploration_count,
            "exploration_rate": exploration_count / total_decisions if total_decisions > 0 else 0,
            "timestep_range": getattr(self, 'training_context', {})
        }
    
    @staticmethod
    def enhance_training_env(env):
        """Add web replay logging to environment."""
        original_step = env.step
        env.web_replay_logger = WebReplayLogger(env)
        env.web_replay_logger.capture_initial_state()
        
        def enhanced_step(action):
            pre_action_units = copy.deepcopy(getattr(env, 'units', []))
            step_result = original_step(action)
            
            if len(step_result) == 5:
                obs, reward, terminated, truncated, info = step_result
                done = terminated or truncated
            else:
                obs, reward, done, info = step_result
                terminated = done
                truncated = False
            
            post_action_units = copy.deepcopy(getattr(env, 'units', []))
            action_int = env.web_replay_logger._normalize_action(action)
            
            env.web_replay_logger.capture_action_state(
                action=action_int, reward=reward,
                pre_action_units=pre_action_units,
                post_action_units=post_action_units,
                acting_unit_id=getattr(env, 'current_player', 1),
                description=f"AI performs {env.web_replay_logger.action_names.get(action_int, 'unknown action')}"
            )
            
            if terminated or truncated:
                winner = "player" if getattr(env, 'winner', None) == 0 else "ai" if getattr(env, 'winner', None) == 1 else "draw"
                env.web_replay_logger.capture_game_end(winner, reward)
            
            if len(step_result) == 5:
                return obs, reward, terminated, truncated, info
            else:
                return obs, reward, done, info
        
        env.step = enhanced_step
        return env
    
    @staticmethod
    def save_episode_replay(env, episode_reward, output_dir="ai/event_log"):
        """Save episode replay."""
        if hasattr(env, 'web_replay_logger'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(output_dir, f"web_replay_{timestamp}.json")
            env.web_replay_logger.save_web_replay(filename, episode_reward)
            return filename
        return None
