#!/usr/bin/env python3
"""
game_replay_logger.py - Capture full game state for visual replay
"""

import json
import os
import copy
from typing import List, Dict, Any, Optional
from datetime import datetime

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
    
    def capture_action_state(self, action: int, reward: float, pre_action_units: List[Dict], 
                           post_action_units: List[Dict], acting_unit_id: Optional[int] = None,
                           target_unit_id: Optional[int] = None, description: str = ""):
        """Capture game state after an action."""
        
        # Determine what happened by comparing before/after
        changes = self._analyze_changes(pre_action_units, post_action_units)
        
        # Create state snapshot
        state = self._create_game_state_snapshot(
            action_taken=action,
            acting_unit_id=acting_unit_id,
            target_unit_id=target_unit_id,
            phase=self.current_phase,
            turn=self.current_turn,
            reward=reward
        )
        
        # Add change analysis
        state["event_flags"].update(changes)
        state["event_flags"]["action_name"] = self.action_names.get(action, f"action_{action}")
        state["event_flags"]["description"] = description or self._generate_description(action, changes)
        
        self.game_states.append(state)
        
        # Check for turn/phase progression
        self._update_turn_phase()
    
    def capture_game_end(self, winner: Optional[str], final_reward: float):
        """Capture the final game state."""
        end_state = self._create_game_state_snapshot(
            action_taken=None,
            acting_unit_id=None,
            target_unit_id=None,
            phase="game_end",
            turn=self.current_turn,
            reward=final_reward
        )
        
        end_state["event_flags"]["game_event"] = "battle_ends"
        end_state["event_flags"]["winner"] = winner or "draw"
        end_state["event_flags"]["description"] = f"Battle concluded - {winner or 'Draw'}"
        
        self.game_states.append(end_state)
        print(f"🏁 Captured game end state - Winner: {winner or 'Draw'}")
    
    def _create_game_state_snapshot(self, action_taken: Optional[int], acting_unit_id: Optional[int],
                                  target_unit_id: Optional[int], phase: str, turn: int, 
                                  reward: float) -> Dict[str, Any]:
        """Create a complete snapshot of the current game state."""
        
        # Copy all units with full details
        units = []
        for unit in self.env.units:
            unit_copy = {
                "id": unit["id"],
                "name": self._get_unit_name(unit),
                "type": unit["unit_type"],
                "player": unit["player"],
                "col": unit["col"],
                "row": unit["row"],
                "color": self._get_unit_color(unit),
                "MOVE": unit["move"],
                "HP_MAX": unit["hp_max"],
                "CUR_HP": unit["cur_hp"],
                "RNG_RNG": unit["rng_rng"],
                "RNG_DMG": unit["rng_dmg"],
                "CC_DMG": unit["cc_dmg"],
                "ICON": self._get_unit_icon(unit),
                "alive": unit["alive"],
                "is_ranged": unit.get("is_ranged", True),
                "is_melee": unit.get("is_melee", False)
            }
            units.append(unit_copy)
        
        # Create the game state
        game_state = {
            "turn": turn,
            "phase": phase,
            "acting_unit_idx": acting_unit_id,
            "target_unit_idx": target_unit_id,
            "event_flags": {
                "action_id": action_taken,
                "reward": reward,
                "ai_units_alive": len([u for u in self.env.units if u["player"] == 1 and u["alive"]]),
                "enemy_units_alive": len([u for u in self.env.units if u["player"] == 0 and u["alive"]]),
                "step_number": len(self.game_states) + 1
            },
            "unit_stats": self._calculate_unit_stats(),
            "units": units,
            "board_state": self._create_board_representation()
        }
        
        return game_state
    
    def _analyze_changes(self, before_units: List[Dict], after_units: List[Dict]) -> Dict[str, Any]:
        """Analyze what changed between before and after states."""
        changes = {
            "units_moved": [],
            "units_damaged": [],
            "units_killed": [],
            "positions_changed": [],
            "combat_occurred": False,
            "shooting_occurred": False
        }
        
        # Create lookup maps
        before_map = {u["id"]: u for u in before_units}
        after_map = {u["id"]: u for u in after_units}
        
        for unit_id in before_map:
            before_unit = before_map[unit_id]
            after_unit = after_map.get(unit_id)
            
            if after_unit:
                # Check for movement
                if (before_unit["col"] != after_unit["col"] or 
                    before_unit["row"] != after_unit["row"]):
                    changes["units_moved"].append({
                        "unit_id": unit_id,
                        "from": {"col": before_unit["col"], "row": before_unit["row"]},
                        "to": {"col": after_unit["col"], "row": after_unit["row"]}
                    })
                    changes["positions_changed"].append(unit_id)
                
                # Check for damage
                if before_unit["cur_hp"] > after_unit["cur_hp"]:
                    damage = before_unit["cur_hp"] - after_unit["cur_hp"]
                    changes["units_damaged"].append({
                        "unit_id": unit_id,
                        "damage": damage,
                        "hp_before": before_unit["cur_hp"],
                        "hp_after": after_unit["cur_hp"]
                    })
                    
                    # Determine if it was shooting or combat
                    if any(self._get_distance(before_unit, other) > 1 
                          for other in before_units if other["player"] != before_unit["player"]):
                        changes["shooting_occurred"] = True
                    else:
                        changes["combat_occurred"] = True
                
                # Check for death
                if before_unit["alive"] and not after_unit["alive"]:
                    changes["units_killed"].append({
                        "unit_id": unit_id,
                        "unit_type": before_unit["unit_type"],
                        "player": before_unit["player"]
                    })
        
        return changes
    
    def _generate_description(self, action: int, changes: Dict[str, Any]) -> str:
        """Generate a human-readable description of what happened."""
        action_name = self.action_names.get(action, f"Action {action}")
        
        descriptions = []
        
        if changes["units_moved"]:
            unit_count = len(changes["units_moved"])
            descriptions.append(f"{unit_count} unit(s) moved")
        
        if changes["units_damaged"]:
            for damage_info in changes["units_damaged"]:
                descriptions.append(f"Unit {damage_info['unit_id']} takes {damage_info['damage']} damage")
        
        if changes["units_killed"]:
            for kill_info in changes["units_killed"]:
                descriptions.append(f"Unit {kill_info['unit_id']} eliminated")
        
        if changes["shooting_occurred"]:
            descriptions.append("Ranged combat")
        elif changes["combat_occurred"]:
            descriptions.append("Melee combat")
        
        if not descriptions:
            descriptions.append("Unit waits")
        
        return f"{action_name}: " + ", ".join(descriptions)
    
    def _calculate_unit_stats(self) -> Dict[str, Any]:
        """Calculate current battlefield statistics."""
        stats = {
            "total_units": len(self.env.units),
            "alive_units": len([u for u in self.env.units if u["alive"]]),
            "player_0_units": len([u for u in self.env.units if u["player"] == 0 and u["alive"]]),
            "player_1_units": len([u for u in self.env.units if u["player"] == 1 and u["alive"]]),
            "total_hp": sum(u["cur_hp"] for u in self.env.units if u["alive"]),
            "average_hp": 0
        }
        
        if stats["alive_units"] > 0:
            stats["average_hp"] = stats["total_hp"] / stats["alive_units"]
        
        return stats
    
    def _create_board_representation(self) -> List[List[Optional[int]]]:
        """Create a 2D representation of the board with unit IDs."""
        board = [[None for _ in range(self.env.board_size[1])] 
                for _ in range(self.env.board_size[0])]
        
        for unit in self.env.units:
            if unit["alive"] and 0 <= unit["col"] < self.env.board_size[0] and 0 <= unit["row"] < self.env.board_size[1]:
                board[unit["col"]][unit["row"]] = unit["id"]
        
        return board
    
    def _get_unit_name(self, unit: Dict) -> str:
        """Get display name for unit."""
        player_prefix = "P" if unit["player"] == 0 else "A"
        type_prefix = "I" if unit["unit_type"] == "Intercessor" else "A"
        return f"{player_prefix}-{type_prefix}"
    
    def _get_unit_color(self, unit: Dict) -> int:
        """Get color for unit based on type and player."""
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
    
    def save_replay(self, filename: str, episode_reward: float = 0.0):
        """Save the complete game replay."""
        replay_data = {
            "metadata": {
                **self.game_metadata,
                "total_states": len(self.game_states),
                "final_turn": self.current_turn,
                "episode_reward": episode_reward,
                "duration_minutes": len(self.game_states) * 0.1  # Rough estimate
            },
            "game_states": self.game_states
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"💾 Saved game replay: {filename}")
        print(f"   📊 {len(self.game_states)} game states captured")
        print(f"   🎮 {self.current_turn} turns played")
        print(f"   💯 Final reward: {episode_reward:.2f}")
    
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
            
            # Execute original step
            obs, reward, terminated, truncated, info = original_step(action)
            
            # Capture state after action
            post_action_units = copy.deepcopy(env.units)
            
            # Log the action and its effects
            env.replay_logger.capture_action_state(
                action=action,
                reward=reward,
                pre_action_units=pre_action_units,
                post_action_units=post_action_units,
                acting_unit_id=env.current_player,  # Approximate
                description=f"AI performs {env.replay_logger.action_names.get(action, 'unknown action')}"
            )
            
            # Check for game end
            if terminated or truncated:
                winner = "player" if env.winner == 0 else "ai" if env.winner == 1 else "draw"
                env.replay_logger.capture_game_end(winner, reward)
            
            return obs, reward, terminated, truncated, info
        
        # Replace step method
        env.step = enhanced_step
        return env
    
    @staticmethod
    def save_episode_replay(env, episode_reward: float, output_dir: str = "ai/event_log"):
        """Save the replay for this episode."""
        if hasattr(env, 'replay_logger'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(output_dir, f"game_replay_{timestamp}.json")
            env.replay_logger.save_replay(filename, episode_reward)
            return filename
        return None