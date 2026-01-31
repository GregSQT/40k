#!/usr/bin/env python3
"""
ai/training/orchestrator.py - AI_TURN.md Compliant Training Orchestration

ARCHITECTURE: Pure delegation to W40KEngine via minimal gym interface
COMPLIANCE: Zero wrapper patterns, single game_state, built-in step counting
"""

import os
import sys
import json
from typing import Dict, List, Optional, Tuple
from shared.data_validation import require_key
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env

# Fix import paths for your project structure
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
sys.path.insert(0, project_root)

from ai.training.gym_interface import W40KGymEnv
from main import load_config

class TrainingOrchestrator:
    """AI_TURN.md compliant training orchestration - pure delegation only."""
    
    def __init__(self, config_path: str = None):
        self.config = load_config(config_path)
        self.models_dir = "models"
        os.makedirs(self.models_dir, exist_ok=True)
    
    def create_environment(self, scenario_config: Dict = None) -> W40KGymEnv:
        """Create compliant gym environment - direct engine delegation."""
        
        # Merge scenario config into main config if provided
        env_config = self.config.copy()
        if scenario_config:
            env_config.update(scenario_config)
        
        # Direct delegation to compliant engine
        env = W40KGymEnv(env_config)
        
        # Validate gym interface compliance
        check_env(env)
        
        return env
    
    def train_single_agent(self, 
                          agent_name: str,
                          total_timesteps: int = 50000,
                          scenario_config: Dict = None) -> str:
        """Train single agent with AI_TURN.md compliance verification."""
        
        print(f"Training agent: {agent_name}")
        print(f"Total timesteps: {total_timesteps:,}")
        
        # Create compliant environment
        env = self.create_environment(scenario_config)
        
        # AI_TURN.md COMPLIANCE CHECK
        self._verify_engine_compliance(env)
        
        # Create model with direct delegation
        model = DQN(
            "MlpPolicy",
            env,
            verbose=1,
            learning_rate=0.001,
            buffer_size=10000,
            learning_starts=1000,
            target_update_interval=500,
            train_freq=4,
            exploration_fraction=0.1,
            exploration_initial_eps=1.0,
            exploration_final_eps=0.05
        )
        
        # Execute training
        model.learn(total_timesteps=total_timesteps)
        
        # Save model
        model_path = os.path.join(self.models_dir, f"{agent_name}_model")
        model.save(model_path)
        
        env.close()
        return f"{model_path}.zip"
    
    def train_multi_agent_sequential(self, 
                                   agents: List[str],
                                   episodes_per_agent: int = 1000) -> Dict[str, str]:
        """Sequential multi-agent training - one agent at a time."""
        
        print(f"Sequential training: {len(agents)} agents")
        print(f"Episodes per agent: {episodes_per_agent}")
        
        trained_models = {}
        
        for agent_name in agents:
            print(f"\n--- Training Agent: {agent_name} ---")
            
            # Calculate timesteps from episodes
            # Episodes are primary metric, steps are derived
            max_steps_per_episode = self._estimate_max_steps_per_episode()
            total_timesteps = episodes_per_agent * max_steps_per_episode
            
            model_path = self.train_single_agent(
                agent_name=agent_name,
                total_timesteps=total_timesteps
            )
            
            trained_models[agent_name] = model_path
            print(f"Agent {agent_name} trained: {model_path}")
        
        return trained_models
    
    def _verify_engine_compliance(self, env: W40KGymEnv) -> None:
        """Verify AI_TURN.md compliance in engine."""
        
        print("🔍 AI_TURN.md COMPLIANCE VERIFICATION")
        
        # Check 1: Sequential activation
        obs, info = env.reset()
        active_units = env._get_active_unit()
        if active_units and isinstance(active_units, list):
            raise ValueError("VIOLATION: Multiple active units detected - must be sequential")
        print("✅ Sequential activation: ONE unit per step")
        
        # Check 2: Built-in step counting
        if not hasattr(env.engine, 'episode_steps'):
            raise ValueError("VIOLATION: Step counting not built into engine")
        print("✅ Built-in step counting: Engine-native implementation")
        
        # Check 3: Single game_state
        if hasattr(env.engine, '_state_copies') or hasattr(env, '_wrapped_states'):
            raise ValueError("VIOLATION: Multiple game state objects detected")
        print("✅ Single game_state: No wrapper patterns")
        
        # Check 4: UPPERCASE fields
        game_state = env.engine.game_state
        if 'units' in game_state:
            for unit in game_state['units'][:3]:  # Check first 3 units
                if any(field.islower() for field in unit.keys() if field.startswith(('hp', 'max', 'cur'))):
                    raise ValueError("VIOLATION: Lowercase stat fields detected")
        print("✅ UPPERCASE fields: Proper naming convention")
        
        # Check 5: Eligibility-based phases
        if not hasattr(env.engine, '_get_eligible_units'):
            raise ValueError("VIOLATION: Eligibility-based phase logic missing")
        print("✅ Eligibility-based phases: Phase completion logic present")
        
        print("🎯 All AI_TURN.md compliance checks PASSED")
    
    def _estimate_max_steps_per_episode(self) -> int:
        """Estimate maximum steps per episode from config."""
        
        # Extract from game rules
        game_rules = require_key(self.config, 'game_rules')
        max_turns = require_key(game_rules, 'max_turns')
        max_units = len(require_key(self.config, 'units'))
        phases_per_turn = 4  # movement, shooting, charge, combat
        
        # Conservative estimate: each unit acts once per phase
        max_steps = max_turns * max_units * phases_per_turn
        
        return max_steps