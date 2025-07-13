# ai/multi_agent_trainer.py
#!/usr/bin/env python3
"""
ai/multi_agent_trainer.py - Multi-Agent Training Orchestration & Load Balancing
Following AI_INSTRUCTIONS.md requirements - uses config_loader, supports unlimited agents
"""

import os
import sys
import json
import time
import threading
import queue
import glob
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, Future
from collections import defaultdict
import multiprocessing as mp

# Fix import paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from ai.unit_registry import UnitRegistry
from ai.scenario_manager import ScenarioManager, TrainingMatchup
from config_loader import get_config_loader

# Import training components
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
import gymnasium as gym

class ReplaySavingWrapper(gym.Wrapper):
    """Wrapper to handle replay saving for Monitor-wrapped environments."""
    
    def __init__(self, monitor_env):
        # Initialize as proper Gymnasium wrapper
        super().__init__(monitor_env)
        self.monitor_env = monitor_env
        # Access the base environment through Monitor.unwrapped
        self.base_env = monitor_env.unwrapped
    
    def save_web_compatible_replay(self, filename=None):
        """Save replay using the base environment's method."""
        if hasattr(self.base_env, 'save_web_compatible_replay'):
            return self.base_env.save_web_compatible_replay(filename)
        else:
            print("⚠️ Base environment doesn't support replay saving")
            return None
    
    def get_replay_data(self):
        """Get replay data from base environment."""
        if hasattr(self.base_env, 'replay_data'):
            return self.base_env.replay_data
        return []
    
    def reset(self, **kwargs):
        """Reset environment."""
        return self.env.reset(**kwargs)
    
    def step(self, action):
        """Step environment."""
        return self.env.step(action)
    
    def close(self):
        """Close the environment."""
        return self.env.close()

@dataclass
class TrainingSession:
    """Represents an active training session."""
    session_id: str
    agent_key: str
    opponent_agent: str
    scenario_template: str
    target_episodes: int
    completed_episodes: int
    current_reward: float
    win_rate: float
    start_time: float
    status: str  # 'running', 'completed', 'failed', 'paused'
    model_path: str
    
@dataclass
class AgentTrainingState:
    """Tracks training state for individual agent."""
    agent_key: str
    total_episodes: int
    total_training_time: float
    current_session: Optional[str]
    model_version: int
    last_checkpoint: str
    performance_metrics: Dict[str, float]
    training_history: List[Dict[str, Any]]

class MultiAgentTrainer:
    """
    Multi-Agent Training Orchestration System.
    Manages simultaneous training of multiple agents with load balancing and progress tracking.
    """
    
    def __init__(self, config_loader=None, max_concurrent_sessions=None):
        """Initialize multi-agent trainer."""
        self.config = config_loader or get_config_loader()
        self.unit_registry = UnitRegistry()
        self.scenario_manager = ScenarioManager(self.config)
        
        # Determine optimal concurrent sessions
        if max_concurrent_sessions is None:
            cpu_count = mp.cpu_count()
            # Use 50% of available CPUs for training, minimum 1, maximum 4
            self.max_concurrent_sessions = max(1, min(4, cpu_count // 2))
        else:
            self.max_concurrent_sessions = max_concurrent_sessions
        
        # Training state
        self.active_sessions: Dict[str, TrainingSession] = {}
        self.agent_states: Dict[str, AgentTrainingState] = {}
        self.session_counter = 0
        self.training_executor = ThreadPoolExecutor(max_workers=self.max_concurrent_sessions)
        self.session_futures: Dict[str, Future] = {}
        
        # Progress tracking
        self.training_log = []
        self.performance_history = defaultdict(list)
        
        # Load training configuration
        self.training_config = self.config.load_training_config("default")
        self.rewards_config = self.config.load_rewards_config("default")
        
        # Initialize agent states
        self._initialize_agent_states()
        
        print(f"🤖 Multi-Agent Trainer initialized")
        print(f"🔧 Max concurrent sessions: {self.max_concurrent_sessions}")
        print(f"📋 Available agents: {len(self.unit_registry.get_all_model_keys())}")
        print(f"🎯 Scenario templates: {len(self.scenario_manager.get_available_templates())}")

    def _initialize_agent_states(self):
        """Initialize training states for all available agents."""
        available_agents = self.unit_registry.get_all_model_keys()
        
        for agent_key in available_agents:
            self.agent_states[agent_key] = AgentTrainingState(
                agent_key=agent_key,
                total_episodes=0,
                total_training_time=0.0,
                current_session=None,
                model_version=0,
                last_checkpoint="",
                performance_metrics={
                    "win_rate": 0.0,
                    "avg_reward": 0.0,
                    "training_efficiency": 0.0
                },
                training_history=[]
            )

    def start_balanced_training(self, total_episodes: int, training_config_name: str = "default",
                               rewards_config_name: str = "default") -> Dict[str, Any]:
        """
        Start balanced multi-agent training following scenario manager rotation.
        Returns training orchestration summary.
        """
        print(f"🚀 Starting balanced multi-agent training")
        print(f"📊 Total episodes: {total_episodes}")
        print(f"⚙️ Training config: {training_config_name}")
        print(f"🎯 Rewards config: {rewards_config_name}")
        
        # Clean up previous session scenarios
        self._cleanup_previous_session_scenarios()
        
        # Generate balanced training rotation
        training_rotation = self.scenario_manager.get_balanced_training_rotation(total_episodes)
        
        if not training_rotation:
            raise ValueError("No training rotation generated - need at least 2 agents")
        
        # Execute training rotation
        orchestration_results = {
            "total_matchups": len(training_rotation),
            "total_episodes": total_episodes,
            "training_config": training_config_name,
            "rewards_config": rewards_config_name,
            "session_results": [],
            "start_time": time.time()
        }
        
        print(f"🔄 Executing {len(training_rotation)} training matchups...")
        
        # Process training rotation in batches to respect concurrent session limits
        completed_sessions = 0
        for i in range(0, len(training_rotation), self.max_concurrent_sessions):
            batch = training_rotation[i:i + self.max_concurrent_sessions]
            
            # Start batch of training sessions
            batch_futures = []
            for matchup in batch:
                session_id = self._generate_session_id()
                
                # Create training session
                session = TrainingSession(
                    session_id=session_id,
                    agent_key=matchup.player_1_agent,  # AI agent
                    opponent_agent=matchup.player_0_agent,  # Opponent/bot
                    scenario_template=matchup.scenario_template,
                    target_episodes=matchup.expected_duration,
                    completed_episodes=0,
                    current_reward=0.0,
                    win_rate=0.0,
                    start_time=time.time(),
                    status='running',
                    model_path=self._get_agent_model_path(matchup.player_1_agent)
                )
                
                # Submit training session
                future = self.training_executor.submit(
                    self._execute_training_session,
                    session, training_config_name, rewards_config_name
                )
                
                self.active_sessions[session_id] = session
                self.session_futures[session_id] = future
                batch_futures.append((session_id, future))
                
                print(f"🎮 Started session {session_id}: {matchup.player_1_agent} vs {matchup.player_0_agent}")
            
            # Wait for batch completion
            for session_id, future in batch_futures:
                try:
                    result = future.result(timeout=3600)  # 1 hour timeout per session
                    orchestration_results["session_results"].append(result)
                    completed_sessions += 1
                    
                    # Update scenario manager with results
                    if result["status"] == "completed":
                        self.scenario_manager.update_training_history(
                            result["agent_key"],
                            result["opponent_agent"],
                            result["completed_episodes"],
                            result["final_win_rate"],
                            result["final_avg_reward"]
                        )
                    
                    print(f"✅ Session {session_id} completed: {result['status']}")
                    
                except Exception as e:
                    print(f"❌ Session {session_id} failed: {e}")
                    orchestration_results["session_results"].append({
                        "session_id": session_id,
                        "status": "failed",
                        "error": str(e)
                    })
                finally:
                    # Cleanup
                    if session_id in self.active_sessions:
                        del self.active_sessions[session_id]
                    if session_id in self.session_futures:
                        del self.session_futures[session_id]
            
            print(f"🔄 Batch completed: {completed_sessions}/{len(training_rotation)} sessions")
        
        orchestration_results["end_time"] = time.time()
        orchestration_results["total_duration"] = orchestration_results["end_time"] - orchestration_results["start_time"]
        
        # Generate final progress report
        progress_report = self.scenario_manager.get_training_progress_report()
        orchestration_results["progress_report"] = progress_report
        
        print(f"🎉 Balanced training completed!")
        print(f"⏱️ Total duration: {orchestration_results['total_duration']:.2f} seconds")
        print(f"📊 Successful sessions: {len([r for r in orchestration_results['session_results'] if r.get('status') == 'completed'])}")
        
        # Save orchestration results
        self._save_orchestration_results(orchestration_results)
        
        return orchestration_results

    def _execute_training_session(self, session: TrainingSession, training_config_name: str,
                                 rewards_config_name: str) -> Dict[str, Any]:
        """Execute individual training session for specific agent matchup."""
        try:
            print(f"🏃 Executing session {session.session_id}: {session.agent_key} vs {session.opponent_agent}")
            
            # Generate scenario for this matchup
            scenario = self.scenario_manager.generate_training_scenario(
                session.scenario_template,
                session.opponent_agent,  # Player 0 (bot)
                session.agent_key       # Player 1 (AI)
            )
            
            # Save scenario to temporary file
            scenario_path = self._save_session_scenario(session.session_id, scenario)
            
            # Create/load model for this agent
            model, env = self._create_agent_model(
                session.agent_key, 
                training_config_name, 
                rewards_config_name,
                scenario_path
            )
            
            # Setup callbacks for this session
            callbacks = self._setup_session_callbacks(session, model)
            
            # Execute training
            start_time = time.time()
            
            model.learn(
                total_timesteps=session.target_episodes * 200,  # Approximate timesteps per episode
                callback=callbacks,
                log_interval=100,
                progress_bar=False  # Disable for multi-threading
            )
            
            training_duration = time.time() - start_time
            
            # Test trained model
            test_results = self._test_trained_model(model, env, num_episodes=10)
            
            # Save final model
            final_model_path = session.model_path.replace('.zip', f'_session_{session.session_id}.zip')
            model.save(final_model_path)

            # Save descriptive replay file with proper error handling
            replay_file_saved = None
            try:
                timestamp = time.strftime("%Y%m%d_%H%M%S") 
                #descriptive_filename = f"ai/event_log/training_{session.agent_key}_vs_{session.opponent_agent}_{timestamp}.json"
                descriptive_filename = f"ai/event_log/training_{session.agent_key}_vs_{session.opponent_agent}.json"
                
                # Access base environment through Monitor for replay saving
                if hasattr(env, 'base_env') and hasattr(env.base_env, 'save_web_compatible_replay'):
                    replay_file_saved = env.base_env.save_web_compatible_replay(descriptive_filename)
                elif hasattr(env.unwrapped, 'save_web_compatible_replay'):
                    replay_file_saved = env.unwrapped.save_web_compatible_replay(descriptive_filename)
                else:
                    print(f"⚠️ No replay saving method available for session {session.session_id}")
                
                if replay_file_saved:
                    print(f"💾 Replay saved: {replay_file_saved}")
                else:
                    print(f"⚠️ No replay data to save for session {session.session_id}")
            except Exception as replay_error:
                print(f"⚠️ Failed to save replay for session {session.session_id}: {replay_error}")
            
            # Update session status
            session.status = 'completed'
            session.completed_episodes = session.target_episodes
            session.current_reward = test_results["avg_reward"]
            session.win_rate = test_results["win_rate"]
            
            # Update agent state
            self._update_agent_state(session, training_duration, test_results)
            
            # Cleanup
            env.close()
            if os.path.exists(scenario_path):  # Check before removing
                os.remove(scenario_path)  # Clean up temporary scenario file
            
            result = {
                "session_id": session.session_id,
                "agent_key": session.agent_key,
                "opponent_agent": session.opponent_agent,
                "scenario_template": session.scenario_template,
                "status": "completed",
                "completed_episodes": session.completed_episodes,
                "training_duration": training_duration,
                "final_win_rate": test_results["win_rate"],
                "final_avg_reward": test_results["avg_reward"],
                "model_path": final_model_path,
                "replay_file": replay_file_saved
            }
            
            print(f"✅ Session {session.session_id} completed successfully")
            return result
            
        except Exception as e:
            print(f"❌ Session {session.session_id} failed: {e}")
            session.status = 'failed'
            
            # Try to save replay even on failure
            replay_file_saved = None
            try:
                if 'env' in locals() and env:
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    #failed_replay_filename = f"ai/event_log/failed_training_{session.agent_key}_vs_{session.opponent_agent}_{timestamp}.json"
                    failed_replay_filename = f"ai/event_log/failed_training_{session.agent_key}_vs_{session.opponent_agent}.json"
                    
                    # Access base environment through Monitor for replay saving
                    if hasattr(env, 'base_env') and hasattr(env.base_env, 'save_web_compatible_replay'):
                        replay_file_saved = env.base_env.save_web_compatible_replay(failed_replay_filename)
                    elif hasattr(env.unwrapped, 'save_web_compatible_replay'):
                        replay_file_saved = env.unwrapped.save_web_compatible_replay(failed_replay_filename)
                    
                    if replay_file_saved:
                        print(f"💾 Failed session replay saved: {replay_file_saved}")
            except Exception as replay_error:
                print(f"⚠️ Failed to save replay for failed session {session.session_id}: {replay_error}")
            
            return {
                "session_id": session.session_id,
                "agent_key": session.agent_key,
                "opponent_agent": session.opponent_agent,
                "status": "failed", 
                "error": str(e),
                "completed_episodes": session.completed_episodes,
                "replay_file": replay_file_saved
            }

    def _cleanup_previous_session_scenarios(self):
        """Clean up all previous session scenario files before starting new training."""
        session_scenarios_dir = os.path.join(self.config.config_dir, "session_scenarios")
        
        if not os.path.exists(session_scenarios_dir):
            print("📁 No session scenarios directory found - nothing to clean")
            return
        
        # Find all scenario_*.json files
        pattern = os.path.join(session_scenarios_dir, "scenario_*.json")
        session_files = glob.glob(pattern)
        
        if not session_files:
            print("📁 No previous session scenarios found - starting clean")
            return
        
        # Delete all found session scenario files
        deleted_count = 0
        for file_path in session_files:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                print(f"⚠️ Failed to delete {file_path}: {e}")
        
        print(f"🗑️ Cleaned up {deleted_count} previous session scenario files")

    def _create_agent_model(self, agent_key: str, training_config_name: str,
                           rewards_config_name: str, scenario_path: str) -> Tuple[DQN, Any]:
        """Create or load DQN model for specific agent."""
        # Import environment here to avoid circular imports
        try:
            from gym40k import W40KEnv
        except ImportError:
            from ai.gym40k import W40KEnv
        
        # Load training configuration
        training_config = self.config.load_training_config(training_config_name)
        model_params = training_config["model_params"]
        
        # Create agent-specific environment with generated scenario
        base_env = W40KEnv(
            rewards_config=rewards_config_name,
            training_config_name=training_config_name,
            controlled_agent=agent_key,
            scenario_file=scenario_path
        )
        monitor_env = Monitor(base_env)
        
        # Wrap for replay saving access - now properly inherits from gym.Wrapper
        env = ReplaySavingWrapper(monitor_env)
        
        # Agent-specific model path
        model_path = self._get_agent_model_path(agent_key)
        
        # Create or load model
        if os.path.exists(model_path):
            print(f"📁 Loading existing model for {agent_key}: {model_path}")
            model = DQN.load(model_path, env=env)
            # Update model parameters for continued training
            model.tensorboard_log = model_params.get("tensorboard_log", "./tensorboard/")
        else:
            print(f"🆕 Creating new model for {agent_key}")
            model = DQN(env=env, **model_params)
        
        return model, env

    def _setup_session_callbacks(self, session: TrainingSession, model) -> List:
        """Setup training callbacks for session monitoring."""
        callbacks = []
        
        # Create session-specific directories
        session_dir = os.path.join(self.config.get_models_dir(), "sessions", session.session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Evaluation callback
        try:
            from gym40k import W40KEnv
        except ImportError:
            from ai.gym40k import W40KEnv
            
        # Use the same scenario file for evaluation as training
        # Generate the scenario filename based on agent names and session ID
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        session_scenario_path = os.path.join(
            self.config.config_dir, 
            "session_scenarios", 
            f"scenario_{session.agent_key}_vs_{session.opponent_agent}_{timestamp}.json"
        )
        base_eval_env = W40KEnv(controlled_agent=session.agent_key, scenario_file=session_scenario_path)
        monitor_eval_env = Monitor(base_eval_env)
        eval_env = ReplaySavingWrapper(monitor_eval_env)
        
        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path=session_dir,
            log_path=session_dir,
            eval_freq=max(1000, session.target_episodes * 20),  # Evaluate periodically
            deterministic=True,
            render=False,
            n_eval_episodes=3  # Quick evaluation
        )
        callbacks.append(eval_callback)
        
        # Checkpoint callback
        checkpoint_callback = CheckpointCallback(
            save_freq=max(2000, session.target_episodes * 40),
            save_path=session_dir,
            name_prefix=f"{session.agent_key}_checkpoint"
        )
        callbacks.append(checkpoint_callback)
        
        return callbacks

    def _test_trained_model(self, model, env, num_episodes: int = 10) -> Dict[str, float]:
        """Test trained model and return performance metrics."""
        wins = 0
        total_rewards = []
        
        for episode in range(num_episodes):
            obs, info = env.reset()
            episode_reward = 0
            done = False
            step_count = 0
            
            while not done and step_count < 500:  # Prevent infinite episodes
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                episode_reward += reward
                done = terminated or truncated
                step_count += 1
            
            total_rewards.append(episode_reward)
            
            # Check win condition
            if info.get('winner') == 1:  # AI won
                wins += 1
        
        win_rate = wins / num_episodes
        avg_reward = sum(total_rewards) / len(total_rewards)
        
        return {
            "win_rate": win_rate,
            "avg_reward": avg_reward,
            "total_episodes": num_episodes
        }

    def _update_agent_state(self, session: TrainingSession, training_duration: float,
                           test_results: Dict[str, float]):
        """Update agent training state with session results."""
        agent_state = self.agent_states[session.agent_key]
        
        # Update totals
        agent_state.total_episodes += session.completed_episodes
        agent_state.total_training_time += training_duration
        agent_state.model_version += 1
        agent_state.current_session = None
        agent_state.last_checkpoint = session.model_path
        
        # Update performance metrics
        agent_state.performance_metrics.update({
            "win_rate": test_results["win_rate"],
            "avg_reward": test_results["avg_reward"],
            "training_efficiency": session.completed_episodes / training_duration if training_duration > 0 else 0
        })
        
        # Add to training history
        history_entry = {
            "timestamp": time.time(),
            "session_id": session.session_id,
            "opponent": session.opponent_agent,
            "episodes": session.completed_episodes,
            "duration": training_duration,
            "win_rate": test_results["win_rate"],
            "avg_reward": test_results["avg_reward"]
        }
        agent_state.training_history.append(history_entry)

    def _save_session_scenario(self, session_id: str, scenario: Dict[str, Any]) -> str:
        """Save scenario for training session."""
        # Extract agent names from scenario metadata
        player_0_agent = scenario["metadata"]["player_0_agent"]
        player_1_agent = scenario["metadata"]["player_1_agent"]
        timestamp = scenario["metadata"]["generated_timestamp"]
        
        session_scenario_path = os.path.join(
            self.config.config_dir, 
            "session_scenarios", 
            f"scenario_{player_1_agent}_vs_{player_0_agent}_{timestamp}.json"
        )
        
        os.makedirs(os.path.dirname(session_scenario_path), exist_ok=True)
        
        with open(session_scenario_path, 'w') as f:
            json.dump(scenario, f, indent=2)
        
        return session_scenario_path

    def _save_orchestration_results(self, results: Dict[str, Any]):
        """Save training orchestration results."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        results_path = os.path.join(
            self.config.get_models_dir(),
            f"orchestration_results_{timestamp}.json"
        )
        
        os.makedirs(os.path.dirname(results_path), exist_ok=True)
        
        # Convert tuple keys to strings for JSON serialization
        def convert_keys(obj):
            if isinstance(obj, dict):
                return {str(k): convert_keys(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_keys(v) for v in obj]
            else:
                return obj
        
        serializable_results = convert_keys(results)
        
        with open(results_path, 'w') as f:
            json.dump(serializable_results, f, indent=2, default=str)
        
        print(f"📊 Orchestration results saved: {results_path}")

    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        self.session_counter += 1
        timestamp = int(time.time())
        return f"session_{timestamp}_{self.session_counter}"

    def _get_agent_model_path(self, agent_key: str) -> str:
        """Get model file path for specific agent."""
        base_path = self.config.get_model_path()
        return base_path.replace('.zip', f'_{agent_key}.zip')

    def get_training_status(self) -> Dict[str, Any]:
        """Get current training status across all agents."""
        status = {
            "active_sessions": len(self.active_sessions),
            "max_concurrent_sessions": self.max_concurrent_sessions,
            "agent_states": {k: asdict(v) for k, v in self.agent_states.items()},
            "current_sessions": {}
        }
        
        for session_id, session in self.active_sessions.items():
            status["current_sessions"][session_id] = {
                "agent_key": session.agent_key,
                "opponent_agent": session.opponent_agent,
                "status": session.status,
                "progress": session.completed_episodes / session.target_episodes if session.target_episodes > 0 else 0,
                "current_reward": session.current_reward
            }
        
        return status

    def stop_all_training(self):
        """Stop all active training sessions."""
        print("🛑 Stopping all training sessions...")
        
        # Cancel all futures
        for session_id, future in self.session_futures.items():
            future.cancel()
        
        # Update session statuses
        for session in self.active_sessions.values():
            session.status = 'stopped'
        
        # Shutdown executor
        self.training_executor.shutdown(wait=True)
        
        print("✅ All training sessions stopped")

    def save_training_state(self) -> str:
        """Save complete training state to file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        state_path = os.path.join(
            self.config.get_models_dir(),
            f"training_state_{timestamp}.json"
        )
        
        training_state = {
            "agent_states": {k: asdict(v) for k, v in self.agent_states.items()},
            "scenario_manager_history": dict(self.scenario_manager.training_history),
            "performance_history": dict(self.performance_history),
            "training_log": self.training_log,
            "save_timestamp": timestamp
        }
        
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        
        with open(state_path, 'w') as f:
            json.dump(training_state, f, indent=2, default=str)
        
        print(f"💾 Training state saved: {state_path}")
        return state_path

# Test and validation functions
def test_multi_agent_trainer():
    """Test multi-agent trainer functionality."""
    print("🧪 Testing Multi-Agent Trainer")
    print("=" * 50)
    
    try:
        # Initialize trainer
        trainer = MultiAgentTrainer(max_concurrent_sessions=1)  # Use 1 for testing
        
        # Test status
        status = trainer.get_training_status()
        print(f"✅ Training status: {len(status['agent_states'])} agents tracked")
        
        # Test small training run (would need actual environment)
        print("⚠️ Skipping actual training test (requires full environment)")
        
        # Test state saving
        state_path = trainer.save_training_state()
        print(f"✅ Training state saved: {os.path.exists(state_path)}")
        
        print("🎉 Multi-agent trainer tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_multi_agent_trainer()