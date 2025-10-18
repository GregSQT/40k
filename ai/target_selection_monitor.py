#!/usr/bin/env python3
"""
Target selection monitoring and analysis tool.
Tracks which targets agent selects and compares to optimal choices.
"""

import json
import numpy as np
from collections import defaultdict
from typing import Dict, List, Any

class TargetSelectionMonitor:
    """Monitor agent's target selection decisions during training."""
    
    def __init__(self, output_file="target_selection_analysis.json"):
        self.output_file = output_file
        self.episode_selections = []
        self.current_episode = {
            "selections": [],
            "optimal_count": 0,
            "total_count": 0
        }
    
    def log_selection(self, unit_id: str, selected_action: int, 
                     available_targets: List[Dict], observation: np.ndarray):
        """Log a single target selection decision."""
        
        action_offset = selected_action - 4
        obs_base = 120 + action_offset * 10
        
        selected_features = {
            "is_valid": float(observation[obs_base + 0]),
            "kill_probability": float(observation[obs_base + 1]),
            "danger_to_me": float(observation[obs_base + 2]),
            "hp_ratio": float(observation[obs_base + 3]),
            "distance": float(observation[obs_base + 4]),
            "is_lowest_hp": float(observation[obs_base + 5]),
            "army_weighted_threat": float(observation[obs_base + 6]),
            "can_be_charged": float(observation[obs_base + 7]),
            "optimal_score": float(observation[obs_base + 8]),
            "type_match": float(observation[obs_base + 9])
        }
        
        all_army_threats = []
        for i in range(5):
            obs_idx = 120 + i * 10
            if observation[obs_idx] > 0.5:
                all_army_threats.append((i, observation[obs_idx + 6]))
        
        is_optimal = False
        if all_army_threats:
            best_action_offset = max(all_army_threats, key=lambda x: x[1])[0]
            is_optimal = (action_offset == best_action_offset)
        
        self.current_episode["selections"].append({
            "unit_id": unit_id,
            "action": selected_action,
            "features": selected_features,
            "is_optimal": is_optimal
        })
        
        self.current_episode["total_count"] += 1
        if is_optimal:
            self.current_episode["optimal_count"] += 1
    
    def end_episode(self, episode_num: int, total_reward: float, winner: int):
        """Finalize current episode and calculate statistics."""
        
        optimal_rate = 0.0
        if self.current_episode["total_count"] > 0:
            optimal_rate = self.current_episode["optimal_count"] / self.current_episode["total_count"]
        
        self.episode_selections.append({
            "episode": episode_num,
            "total_reward": total_reward,
            "winner": winner,
            "selections": self.current_episode["selections"],
            "optimal_rate": optimal_rate,
            "selection_count": self.current_episode["total_count"]
        })
        
        self.current_episode = {
            "selections": [],
            "optimal_count": 0,
            "total_count": 0
        }
        
        if episode_num % 10 == 0:
            recent_rates = [ep["optimal_rate"] for ep in self.episode_selections[-10:]]
            avg_rate = sum(recent_rates) / len(recent_rates) if recent_rates else 0.0
            print(f"Episode {episode_num}: Optimal target selection rate: {avg_rate:.1%}")
    
    def save_analysis(self):
        """Save complete analysis to JSON file."""
        with open(self.output_file, 'w') as f:
            json.dump({
                "episodes": self.episode_selections,
                "summary": self._calculate_summary()
            }, f, indent=2)
    
    def _calculate_summary(self) -> Dict[str, Any]:
        """Calculate overall training summary statistics."""
        if not self.episode_selections:
            return {}
        
        all_rates = [ep["optimal_rate"] for ep in self.episode_selections]
        
        window_size = 50
        moving_avg = []
        for i in range(len(all_rates) - window_size + 1):
            window = all_rates[i:i+window_size]
            moving_avg.append(sum(window) / window_size)
        
        return {
            "total_episodes": len(self.episode_selections),
            "overall_optimal_rate": sum(all_rates) / len(all_rates),
            "final_50_episode_rate": sum(all_rates[-50:]) / min(50, len(all_rates)),
            "best_rate": max(all_rates),
            "worst_rate": min(all_rates),
            "improvement_trend": moving_avg[-1] - moving_avg[0] if len(moving_avg) > 0 else 0.0
        }