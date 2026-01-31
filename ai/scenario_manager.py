# ai/scenario_manager.py
#!/usr/bin/env python3
"""
ai/scenario_manager.py - Dynamic Scenario Generation & Balancing for Multi-Agent Training
Following AI_INSTRUCTIONS.md requirements - zero hardcoding, config-driven design
"""

import os
import sys
import json
import random
import copy
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict

from shared.data_validation import require_key

units_per_player_setup = 2

# Fix import paths - Add both script dir and project root
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader

@dataclass
class ScenarioTemplate:
    """Represents a scenario template configuration."""
    name: str
    description: str
    board_size: Tuple[int, int]
    agent_compositions: Dict[str, List[str]]  # agent_key -> list of unit_types
    unit_counts: Dict[str, int]  # unit_type -> count
    deployment_zones: Dict[int, List[Tuple[int, int]]]  # player -> [(col, row), ...]
    difficulty: str
    training_focus: str  # 'solo', 'cross_faction', 'mixed', 'balanced'

@dataclass
class TrainingMatchup:
    """Represents a specific training matchup between agents."""
    player_0_agent: str
    player_1_agent: str
    scenario_template: str
    expected_duration: int  # estimated episodes
    priority: float  # training priority weight

class ScenarioManager:
    """
    Dynamic scenario generation and balancing for multi-agent training.
    Follows AI_INSTRUCTIONS.md: Zero hardcoding, config-driven, uses Unit Registry.
    """
    
    def __init__(self, config_loader=None, unit_registry=None):
        """Initialize scenario manager with dynamic agent discovery."""
        self.config = config_loader or get_config_loader()
        self.unit_registry = unit_registry or UnitRegistry()
        
        # Load scenario templates from config
        self.scenario_templates = self._load_scenario_templates()
        
        # Dynamic agent discovery
        self.available_agents = self.unit_registry.get_required_models()
        
        # Training state tracking
        self.training_history = defaultdict(list)  # agent -> [training_sessions]
        self.matchup_statistics = defaultdict(dict)  # (agent1, agent2) -> stats
        self.current_training_cycle = 0
        
        # Scenario Manager initialized

    def _load_scenario_templates(self) -> Dict[str, ScenarioTemplate]:
        """Load scenario templates from config file."""
        templates = {}
        
        # Load from config/scenario_templates.json
        template_file = os.path.join(self.config.config_dir, "scenario_templates.json")
        
        if os.path.exists(template_file):
            try:
                with open(template_file, 'r') as f:
                    template_data = json.load(f)
                
                # Get board size from board config as single source of truth
                board_size = self.config.get_board_size()
                
                for name, data in template_data.items():
                    # CRITICAL FIX: Normalize deployment_zones keys from JSON string keys to integer keys
                    if "deployment_zones" not in data:
                        raise KeyError(f"Template '{name}' missing required 'deployment_zones' field")
                    raw_deployment_zones = data["deployment_zones"]
                    normalized_deployment_zones = {}
                    for key, value in raw_deployment_zones.items():
                        # Convert string keys to integers (JSON saves player keys as strings)
                        int_key = int(key) if isinstance(key, str) and key.isdigit() else key
                        normalized_deployment_zones[int_key] = value
                    
                    templates[name] = ScenarioTemplate(
                        name=name,
                        description=data["description"],
                        board_size=board_size,
                        agent_compositions=data["agent_compositions"],
                        unit_counts=data["unit_counts"],
                        deployment_zones=normalized_deployment_zones,
                        difficulty=data["difficulty"],
                        training_focus=data["training_focus"]
                    )
                    
                # Templates loaded
                
            except Exception as e:
                raise RuntimeError(f"Failed to load scenario templates from {template_file}: {e}")
        else:
            raise FileNotFoundError(f"Scenario templates not found at {template_file}. No fallbacks allowed - file must exist.")
        
        return templates

    def _save_scenario_templates(self, templates: Dict[str, ScenarioTemplate], filepath: str):
        """Save scenario templates to config file."""
        try:
            # Convert templates to JSON-serializable format
            template_data = {}
            for name, template in templates.items():
                template_data[name] = {
                    "description": template.description,
                    # board_size removed - using board_config as single source of truth
                    "agent_compositions": template.agent_compositions,
                    "unit_counts": template.unit_counts,
                    "deployment_zones": {str(k): v for k, v in template.deployment_zones.items()},
                    "difficulty": template.difficulty,
                    "training_focus": template.training_focus
                }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            with open(filepath, 'w') as f:
                json.dump(template_data, f, indent=2)
            
            print(f"✅ Saved scenario templates to {filepath}")
            
        except Exception as e:
            print(f"❌ Failed to save scenario templates: {e}")

    def generate_training_scenario(self, template_name: str, player_0_agent: str, 
                                 player_1_agent: str) -> Dict[str, Any]:
        """
        Generate a specific training scenario from template.
        Returns scenario.json compatible format.
        """
        if template_name not in self.scenario_templates:
            raise ValueError(f"Unknown scenario template: {template_name}")
        
        template = self.scenario_templates[template_name]
        scenario_units = []
        unit_id = 1
        
        # Generate units for player 0 - Use template composition if specified
        if player_0_agent not in template.agent_compositions:
            raise ValueError(f"Agent '{player_0_agent}' not found in template '{template_name}' agent_compositions. Available: {list(template.agent_compositions.keys())}")
        
        agent_0_units = template.agent_compositions[player_0_agent]
        if not agent_0_units:
            raise ValueError(f"No units defined for agent '{player_0_agent}' in template '{template_name}'")
        
        # CRITICAL FIX: Handle string keys from JSON properly
        if 0 not in template.deployment_zones:
            raise KeyError(f"Template '{template_name}' missing required deployment_zones for player 0")
        deployment_0 = template.deployment_zones[0]
        units_per_player = units_per_player_setup  # Deploy 2 units per player for better battles
        
        # Validate enough deployment positions with detailed error
        if len(deployment_0) < units_per_player:
            raise ValueError(f"SCENARIO GENERATION ERROR: Template '{template_name}' has insufficient deployment positions for player 0: need {units_per_player}, got {len(deployment_0)}. Positions: {deployment_0}")
        
        # Validate positions are unique
        position_set = set(tuple(pos) for pos in deployment_0[:units_per_player])
        if len(position_set) != units_per_player:
            raise ValueError(f"SCENARIO GENERATION ERROR: Template '{template_name}' has duplicate deployment positions for player 0: {deployment_0[:units_per_player]}")
        
        for i in range(units_per_player):
            pos = deployment_0[i]  # Use unique positions - NO CYCLING
            # Additional validation: ensure position is valid
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                raise ValueError(f"SCENARIO GENERATION ERROR: Invalid position format in template '{template_name}': {pos}")
            unit_type = agent_0_units[i % len(agent_0_units)]  # Cycle through unit types
            scenario_units.append({
                "id": unit_id,
                "unit_type": unit_type,
                "player": 0,
                "col": pos[0],
                "row": pos[1]
            })
            unit_id += 1
        
        # Generate units for player 1 - Use template composition if specified
        if player_1_agent not in template.agent_compositions:
            raise ValueError(f"Agent '{player_1_agent}' not found in template '{template_name}' agent_compositions. Available: {list(template.agent_compositions.keys())}")
        
        agent_1_units = template.agent_compositions[player_1_agent]
        if not agent_1_units:
            raise ValueError(f"No units defined for agent '{player_1_agent}' in template '{template_name}'")
        
        # CRITICAL FIX: Handle string keys from JSON properly  
        if 1 not in template.deployment_zones:
            raise KeyError(f"Template '{template_name}' missing required deployment_zones for player 1")
        deployment_1 = template.deployment_zones[1]
        
        # Validate enough deployment positions with detailed error
        if len(deployment_1) < units_per_player:
            raise ValueError(f"SCENARIO GENERATION ERROR: Template '{template_name}' has insufficient deployment positions for player 1: need {units_per_player}, got {len(deployment_1)}. Positions: {deployment_1}")
        
        # Validate positions are unique
        position_set = set(tuple(pos) for pos in deployment_1[:units_per_player])
        if len(position_set) != units_per_player:
            raise ValueError(f"SCENARIO GENERATION ERROR: Template '{template_name}' has duplicate deployment positions for player 1: {deployment_1[:units_per_player]}")
        
        for i in range(units_per_player):
            pos = deployment_1[i]  # Use unique positions - NO CYCLING
            # Additional validation: ensure position is valid
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                raise ValueError(f"SCENARIO GENERATION ERROR: Invalid position format in template '{template_name}': {pos}")
            unit_type = agent_1_units[i % len(agent_1_units)]  # Cycle through unit types
            scenario_units.append({
                "id": unit_id,
                "unit_type": unit_type,
                "player": 1,
                "col": pos[0],
                "row": pos[1]
            })
            unit_id += 1
        
        # FINAL VALIDATION: Check for position conflicts in generated scenario
        position_conflicts = {}
        for unit in scenario_units:
            pos_key = f"{unit['col']},{unit['row']}"
            if pos_key not in position_conflicts:
                position_conflicts[pos_key] = []
            position_conflicts[pos_key].append(f"Unit_{unit['id']}_{unit['unit_type']}")
        
        # Report any conflicts
        conflicts_found = False
        for pos, units_at_pos in position_conflicts.items():
            if len(units_at_pos) > 1:
                conflicts_found = True
        
        if conflicts_found:
            raise ValueError(f"SCENARIO GENERATION FAILED: Unit position conflicts detected in template '{template_name}'. Check deployment zones.")
        
        # Create scenario metadata
        scenario = {
            "metadata": {
                "template": template_name,
                "player_0_agent": player_0_agent,
                "player_1_agent": player_1_agent,
                "board_size": list(template.board_size),
                "difficulty": template.difficulty,
                "training_focus": template.training_focus,
                "generated_timestamp": self._get_timestamp(),
                "units_generated": len(scenario_units),
                "validation_passed": True
            },
            "units": scenario_units
        }
        
        # Scenario generated successfully
        return scenario

    def get_balanced_training_rotation(self, total_episodes: int) -> List[TrainingMatchup]:
        """
        Generate balanced training rotation ensuring each agent gets equal experience.
        Returns list of training matchups with episode allocation.
        """
        matchups = []
        
        # Calculate balanced allocation
        num_agents = len(self.available_agents)
        if num_agents < 2:
            raise ValueError(f"Need at least 2 agents for training rotation, got {num_agents}")

    def get_phase_based_training_rotation(self, total_episodes: int, phase: str) -> List[TrainingMatchup]:
        """
        Generate phase-specific training rotation for 3-phase training plan.
        
        Phase 1 (solo): Solo scenarios only (same agent vs same agent)
        Phase 2 (cross_faction): Cross-faction and mixed scenarios  
        Phase 3 (full_composition): Full team composition scenarios
        
        Returns list of training matchups filtered by phase.
        """
        matchups = []
        
        if phase == "solo":
            # Phase 1: Individual Agent Specialization
            solo_scenarios = [name for name, template in self.scenario_templates.items() 
                            if template.training_focus == "solo"]
            
            episodes_per_agent = total_episodes // len(self.available_agents)
            
            for agent in self.available_agents:
                scenario_name = f"solo_{agent.lower()}"
                if scenario_name in solo_scenarios:
                    matchups.append(TrainingMatchup(
                        player_0_agent=agent,
                        player_1_agent=agent,  # Same agent training
                        scenario_template=scenario_name,
                        expected_duration=episodes_per_agent,
                        priority=2.0
                    ))
        
        elif phase == "cross_faction":
            # Phase 2: Cross-Faction Tactical Learning
            cross_scenarios = [name for name, template in self.scenario_templates.items() 
                             if template.training_focus in ["cross_faction", "mixed"]]
            
            episodes_per_matchup = total_episodes // len(cross_scenarios) if cross_scenarios else 0
            
            for scenario_name in cross_scenarios:
                template = self.scenario_templates[scenario_name]
                agent_keys = list(template.agent_compositions.keys())
                
                if len(agent_keys) >= 2:
                    matchups.append(TrainingMatchup(
                        player_0_agent=agent_keys[0],
                        player_1_agent=agent_keys[1],
                        scenario_template=scenario_name,
                        expected_duration=episodes_per_matchup,
                        priority=1.5
                    ))
        
        elif phase == "full_composition":
            # Phase 3: Full Composition Mastery
            full_scenarios = [name for name, template in self.scenario_templates.items() 
                            if "new_composition" in name or template.training_focus == "balanced"]
            
            episodes_per_scenario = total_episodes // len(full_scenarios) if full_scenarios else 0
            
            for scenario_name in full_scenarios:
                template = self.scenario_templates[scenario_name]
                agent_keys = list(template.agent_compositions.keys())
                
                if len(agent_keys) >= 2:
                    matchups.append(TrainingMatchup(
                        player_0_agent=agent_keys[0],
                        player_1_agent=agent_keys[1],
                        scenario_template=scenario_name,
                        expected_duration=episodes_per_scenario,
                        priority=1.0
                    ))
        
        # Phase matchups generated
        return matchups
        
        # Episodes per agent pair
        episodes_per_pair = total_episodes // (num_agents * (num_agents - 1))
        remaining_episodes = total_episodes % (num_agents * (num_agents - 1))
        
        # Generate all possible matchups
        for i, agent1 in enumerate(self.available_agents):
            for j, agent2 in enumerate(self.available_agents):
                if i != j:  # Don't match agent against itself
                    
                    # Select appropriate scenario template
                    template_name = self._select_scenario_template(agent1, agent2)
                    
                    # Calculate priority based on training history
                    priority = self._calculate_training_priority(agent1, agent2)
                    
                    # Allocate episodes
                    allocated_episodes = episodes_per_pair
                    if remaining_episodes > 0:
                        allocated_episodes += 1
                        remaining_episodes -= 1
                    
                    matchups.append(TrainingMatchup(
                        player_0_agent=agent1,
                        player_1_agent=agent2,
                        scenario_template=template_name,
                        expected_duration=allocated_episodes,
                        priority=priority
                    ))
        
        # Sort by priority (highest first)
        matchups.sort(key=lambda m: m.priority, reverse=True)
        
        print(f"🎯 Generated {len(matchups)} training matchups for {total_episodes} episodes")
        print(f"📊 Episodes per matchup: {episodes_per_pair}")
        
        return matchups

    def _select_scenario_template(self, agent1: str, agent2: str) -> str:
        """Select appropriate scenario template for agent matchup."""
        
        # Extract faction information
        faction1 = agent1.split('_')[0]
        faction2 = agent2.split('_')[0]
        
        # Cross-faction training
        if faction1 != faction2:
            cross_template = f"cross_{agent1.lower()}_vs_{agent2.lower()}"
            if cross_template in self.scenario_templates:
                return cross_template
            reverse_template = f"cross_{agent2.lower()}_vs_{agent1.lower()}"
            if reverse_template in self.scenario_templates:
                return reverse_template
            raise ValueError(f"No cross-faction template found for {agent1} vs {agent2}")
        
        # Same faction - use balanced template
        if "mixed_balanced" in self.scenario_templates:
            return "mixed_balanced"
        
        raise ValueError(f"No suitable template found for same-faction matchup {agent1} vs {agent2}")

    def _calculate_training_priority(self, agent1: str, agent2: str) -> float:
        """Calculate training priority for agent matchup based on history."""
        
        # Base priority
        priority = 1.0
        
        # Check training history balance
        history_key = (agent1, agent2)
        reverse_key = (agent2, agent1)
        
        history_count = len(self.training_history[history_key])
        reverse_count = len(self.training_history[reverse_key])
        total_history = history_count + reverse_count
        
        # Prioritize less-trained matchups
        if total_history == 0:
            priority += 2.0  # High priority for new matchups
        else:
            priority += max(0, 1.0 - (total_history / 10.0))  # Decrease as history grows
        
        # Cross-faction training gets slight priority
        faction1 = agent1.split('_')[0]
        faction2 = agent2.split('_')[0]
        if faction1 != faction2:
            priority += 0.5
        
        return priority

    def update_training_history(self, agent1: str, agent2: str, episodes_completed: int, 
                              win_rate: float, avg_reward: float):
        """Update training history for matchup."""
        history_entry = {
            "timestamp": self._get_timestamp(),
            "episodes": episodes_completed,
            "win_rate": win_rate,
            "avg_reward": avg_reward,
            "cycle": self.current_training_cycle
        }
        
        matchup_key = (agent1, agent2)
        self.training_history[matchup_key].append(history_entry)
        
        # Update statistics
        if matchup_key not in self.matchup_statistics:
            self.matchup_statistics[matchup_key] = {
                "total_episodes": 0,
                "total_sessions": 0,
                "avg_win_rate": 0.0,
                "avg_reward": 0.0
            }
        
        stats = self.matchup_statistics[matchup_key]
        stats["total_episodes"] += episodes_completed
        stats["total_sessions"] += 1
        
        # Update running averages
        sessions = stats["total_sessions"]
        stats["avg_win_rate"] = ((stats["avg_win_rate"] * (sessions - 1)) + win_rate) / sessions
        stats["avg_reward"] = ((stats["avg_reward"] * (sessions - 1)) + avg_reward) / sessions

    def get_training_progress_report(self) -> Dict[str, Any]:
        """Generate comprehensive training progress report."""
        
        report = {
            "overview": {
                "available_agents": len(self.available_agents),
                "scenario_templates": len(self.scenario_templates),
                "training_cycles": self.current_training_cycle,
                "total_matchups": len(self.matchup_statistics)
            },
            "agent_progress": {},
            "matchup_statistics": dict(self.matchup_statistics),
            "balance_analysis": self._analyze_training_balance()
        }
        
        # Individual agent progress
        for agent in self.available_agents:
            agent_stats = {
                "total_episodes": 0,
                "win_rate": 0.0,
                "avg_reward": 0.0,
                "matchups_trained": 0
            }
            
            # Aggregate stats for this agent
            matchup_count = 0
            total_win_rate = 0.0
            total_reward = 0.0
            
            for (a1, a2), stats in self.matchup_statistics.items():
                if a1 == agent or a2 == agent:
                    agent_stats["total_episodes"] += stats["total_episodes"]
                    total_win_rate += stats["avg_win_rate"] if a1 == agent else (1.0 - stats["avg_win_rate"])
                    total_reward += stats["avg_reward"]
                    matchup_count += 1
            
            if matchup_count > 0:
                agent_stats["win_rate"] = total_win_rate / matchup_count
                agent_stats["avg_reward"] = total_reward / matchup_count
                agent_stats["matchups_trained"] = matchup_count
            
            report["agent_progress"][agent] = agent_stats
        
        return report

    def _analyze_training_balance(self) -> Dict[str, Any]:
        """Analyze training balance across agents and factions."""
        
        balance_analysis = {
            "episode_distribution": {},
            "faction_balance": {},
            "recommendations": []
        }
        
        # Episode distribution per agent
        for agent in self.available_agents:
            total_episodes = 0
            for (a1, a2), stats in self.matchup_statistics.items():
                if a1 == agent or a2 == agent:
                    total_episodes += stats["total_episodes"]
            balance_analysis["episode_distribution"][agent] = total_episodes
        
        # Faction balance analysis
        faction_episodes = defaultdict(int)
        for agent in self.available_agents:
            faction = agent.split('_')[0]
            faction_episodes[faction] += require_key(balance_analysis["episode_distribution"], agent)
        
        balance_analysis["faction_balance"] = dict(faction_episodes)
        
        # Generate recommendations
        episode_values = list(balance_analysis["episode_distribution"].values())
        if episode_values:
            min_episodes = min(episode_values)
            max_episodes = max(episode_values)
            
            if max_episodes > min_episodes * 1.5:  # Imbalance threshold
                balance_analysis["recommendations"].append(
                    "Training imbalance detected - consider prioritizing under-trained agents"
                )
        
        return balance_analysis

    def save_scenario_to_file(self, scenario: Dict[str, Any], filepath: str = None) -> str:
        """Save generated scenario to file."""
        if filepath is None:
            timestamp = self._get_timestamp()
            # Move to ai/session_scenarios/ directory
            ai_scenarios_dir = os.path.join(os.path.dirname(self.config.config_dir), "ai", "session_scenarios")
            filepath = os.path.join(ai_scenarios_dir, f"scenario_generated_{timestamp}.json")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w') as f:
            json.dump(scenario, f, indent=2)
        
        print(f"✅ Scenario saved to {filepath}")
        return filepath

    def _get_timestamp(self) -> str:
        """Get current timestamp string."""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def get_available_templates(self) -> List[str]:
        """Get list of available scenario template names."""
        return list(self.scenario_templates.keys())

    def get_template_info(self, template_name: str) -> Optional[ScenarioTemplate]:
        """Get detailed information about a scenario template."""
        return self.scenario_templates.get(template_name)

# Test and validation functions
def test_scenario_manager():
    """Test scenario manager functionality."""
    print("🧪 Testing Scenario Manager")
    print("=" * 50)
    
    try:
        # Initialize manager
        manager = ScenarioManager()
        
        # Test template loading
        templates = manager.get_available_templates()
        print(f"✅ Templates loaded: {len(templates)}")
        
        # Test scenario generation
        if len(manager.available_agents) >= 2:
            agent1 = manager.available_agents[0]
            agent2 = manager.available_agents[1]
            
            scenario = manager.generate_training_scenario(
                templates[0], agent1, agent2
            )
            print(f"✅ Generated scenario with {len(scenario['units'])} units")
            
            # Test rotation generation
            rotation = manager.get_balanced_training_rotation(100)
            print(f"✅ Generated rotation with {len(rotation)} matchups")
            
            # Test progress tracking
            manager.update_training_history(agent1, agent2, 10, 0.6, 15.5)
            report = manager.get_training_progress_report()
            print(f"✅ Progress report generated: {len(report['agent_progress'])} agents")
        
        print("🎉 All scenario manager tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_scenario_manager()