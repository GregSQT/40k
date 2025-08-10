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
import random
import glob
from tqdm import tqdm
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, Future
from collections import defaultdict
import multiprocessing as mp
import time
import json

# Fix import paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from ai.unit_registry import UnitRegistry
from ai.scenario_manager import ScenarioManager, TrainingMatchup
from config_loader import get_config_loader

@dataclass
class EpisodeMetrics:
    """Track metrics for a single episode."""
    episode_num: int
    step_count: int
    total_reward: float
    replay_data: Dict[str, Any]
    
    def __hash__(self):
        """Make EpisodeMetrics hashable for use in sets - exclude replay_data."""
        return hash((self.episode_num, self.step_count, float(self.total_reward)))
    
    def __eq__(self, other):
        """Define equality for EpisodeMetrics - exclude replay_data."""
        if not isinstance(other, EpisodeMetrics):
            return False
        return (self.episode_num == other.episode_num and 
                self.step_count == other.step_count and 
                abs(self.total_reward - other.total_reward) < 1e-6)

class SelectiveEpisodeTracker:
    """Track best/worst/shortest episodes during training for selective replay saving."""
    
    def __init__(self, agent_key: str, enemy_key: str, max_candidates: int = 20):
        self.agent_key = agent_key
        self.enemy_key = enemy_key
        self.max_candidates = max_candidates  # Memory management
        self.episode_candidates: List[EpisodeMetrics] = []
        self.current_episode = 0
        self.shortest_episode: Optional[EpisodeMetrics] = None
        self.best_reward_episode: Optional[EpisodeMetrics] = None
        self.worst_reward_episode: Optional[EpisodeMetrics] = None
    
    def update_episode(self, step_count: int, total_reward: float, replay_data: Dict[str, Any]):
        """Update tracking with new training episode data."""
        self.current_episode += 1
        episode = EpisodeMetrics(self.current_episode, step_count, total_reward, replay_data)
        
        # Add to candidates
        self.episode_candidates.append(episode)
        
        # Update current bests for comparison
        if self.shortest_episode is None or step_count < self.shortest_episode.step_count:
            self.shortest_episode = episode
        if self.best_reward_episode is None or total_reward > self.best_reward_episode.total_reward:
            self.best_reward_episode = episode
        if self.worst_reward_episode is None or total_reward < self.worst_reward_episode.total_reward:
            self.worst_reward_episode = episode
        
        # Memory management - keep only promising candidates
        if len(self.episode_candidates) > self.max_candidates:
            self._prune_candidates()
        pass
    
    def _prune_candidates(self):
        """Keep only the most promising episodes to manage memory."""
        # Sort by different criteria and keep top candidates
        sorted_by_steps = sorted(self.episode_candidates, key=lambda x: x.step_count)
        sorted_by_reward = sorted(self.episode_candidates, key=lambda x: x.total_reward, reverse=True)
        sorted_by_worst = sorted(self.episode_candidates, key=lambda x: x.total_reward)
        
        # Keep top 5 in each category + recent episodes
        keep_episodes = set()
        keep_episodes.update(sorted_by_steps[:5])  # Shortest
        keep_episodes.update(sorted_by_reward[:5])  # Best rewards
        keep_episodes.update(sorted_by_worst[:5])   # Worst rewards
        keep_episodes.update(self.episode_candidates[-5:])  # Recent episodes
        
        self.episode_candidates = list(keep_episodes)
    
    def save_selective_replays(self, output_dir: str = "ai/event_log"):
        """Save the 3 selective replays from training episodes."""
        saved_files = []
        
        # Determine enemy name for filename
        enemy_name = self.enemy_key if self.enemy_key in self.agent_key else "Bot"
        
        episodes_to_save = [
            (self.shortest_episode, "shortest"),
            (self.best_reward_episode, "best"),
            (self.worst_reward_episode, "worst")
        ]
        
        for episode, episode_type in episodes_to_save:
            if episode is not None:
                # Add unique timestamp to prevent overwrites
                filename = f"replay_{self.agent_key}_vs_{enemy_name}_{episode_type}.json"
                filepath = os.path.join(output_dir, filename)
                
                # Save replay data to file with JSON serialization fix
                os.makedirs(output_dir, exist_ok=True)
                try:
                    # Convert numpy arrays to lists for JSON serialization
                    serializable_data = self._make_json_serializable(episode.replay_data)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(serializable_data, f, indent=2)
                    
                    saved_files.append(filepath)
                except Exception as e:
                    pass  # Silent failure for replay saving
        
        return saved_files
    
    def _make_json_serializable(self, obj):
        """Convert numpy arrays and other non-serializable objects to JSON-compatible format."""
        import numpy as np
        
        if isinstance(obj, dict):
            return {key: self._make_json_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        else:
            return obj

# Import training components
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback
from stable_baselines3.common.monitor import Monitor
import gymnasium as gym

# Removed - using GameReplayIntegration instead

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
        self.scenario_manager = ScenarioManager(self.config, self.unit_registry)
        
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
        
        # Simple progress tracking with slowest agent monitoring
        self.total_sessions = 0
        self.completed_sessions = 0
        self.session_progress = {}  # Track progress of each active session
        self.progress_lock = threading.Lock()
        
        # Load training configuration
        self.training_config = self.config.load_training_config("default")
        
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
                               rewards_config_name: str = "default", training_phase: str = None) -> Dict[str, Any]:
        """
        Start balanced multi-agent training following scenario manager rotation.
        Supports 3-phase training plan: solo -> cross_faction -> full_composition
        Returns training orchestration summary.
        """
        print(f"🚀 Starting multi-agent training | Episodes: {total_episodes} | Config: {training_config_name} | Phase: {training_phase or 'balanced'}")
        
        # Clean up previous session scenarios
        self._cleanup_previous_session_scenarios()
        
        # Generate phase-specific training rotation
        if training_phase:
            training_rotation = self.scenario_manager.get_phase_based_training_rotation(
                total_episodes, training_phase
            )
        else:
            training_rotation = self.scenario_manager.get_balanced_training_rotation(total_episodes)
        
        if not training_rotation:
            raise ValueError("No training rotation generated - need at least 2 agents")
        
        # Calculate episodes per pair
        num_agents = len(self.unit_registry.get_all_model_keys())
        episodes_per_pair = total_episodes // (num_agents * (num_agents - 1))
        
        # Execute training rotation
        orchestration_results = {
            "total_matchups": len(training_rotation),
            "total_episodes": total_episodes,
            "training_config": training_config_name,
            "rewards_config": rewards_config_name,
            "session_results": [],
            "start_time": time.time(),
            "total_training_time": 0.0,
            "total_evaluation_time": 0.0
        }
        
        # Load training config
        self.training_config = self.config.load_training_config(training_config_name)
        training_config = self.config.load_training_config(training_config_name)
        timesteps_per_session = training_config["total_timesteps"]
        total_timesteps = len(training_rotation) * timesteps_per_session
        
        print(f"🔄 Executing {len(training_rotation)} training matchups...")
        print(f"📊 Episodes per matchup: {episodes_per_pair}")
        print(f"⏱️ Timesteps per session: {timesteps_per_session:,}")
        print(f"🔄 Total timesteps: {total_timesteps:,}")
        
        # Progress tracking with slowest agent monitoring
        self.total_sessions = len(training_rotation)
        self.completed_sessions = 0
        self.session_progress = {}
        
        print(f"🤖 Starting {self.total_sessions} training sessions...")
        
        # Create progress bar showing slowest agent
        self.overall_pbar = tqdm(
            total=timesteps_per_session,
            desc="🐌 Slowest Agent",
            unit="steps",
            leave=True,
            ncols=100
        )
        
        # Process training rotation in batches to respect concurrent session limits
        completed_sessions = 0
        for i in range(0, len(training_rotation), self.max_concurrent_sessions):
            batch = training_rotation[i:i + self.max_concurrent_sessions]
            
            # Start batch of training sessions silently
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
                
                # Initialize progress tracking for this session
                with self.progress_lock:
                    self.session_progress[session_id] = {
                        'steps': 0,
                        'total': timesteps_per_session,
                        'agent': session.agent_key,
                        'opponent': session.opponent_agent
                    }
            
            # Wait for batch completion with proper progress bar updates
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
                    
                    # Update progress tracking
                    self.completed_sessions += 1
                    
                    # Remove completed session from progress tracking
                    with self.progress_lock:
                        if session_id in self.session_progress:
                            del self.session_progress[session_id]
                        self._update_slowest_progress()
                    
                    print(f"✅ Session {self.completed_sessions}/{self.total_sessions}: {result['agent_key']} vs {result['opponent_agent']} | "
                          f"WR:{result.get('final_win_rate', 0):.0%} R:{result.get('final_avg_reward', 0):.1f}")
                    
                except Exception as e:
                    orchestration_results["session_results"].append({
                        "session_id": session_id,
                        "status": "failed",
                        "error": str(e)
                    })
                    self.completed_sessions += 1
                    with self.progress_lock:
                        if session_id in self.session_progress:
                            del self.session_progress[session_id]
                        self._update_slowest_progress()
                    print(f"❌ Session {self.completed_sessions}/{self.total_sessions}: {session_id} failed: {e}")
                finally:
                    # Cleanup
                    if session_id in self.active_sessions:
                        del self.active_sessions[session_id]
                    if session_id in self.session_futures:
                        del self.session_futures[session_id]
        
        # Close progress bar
        self.overall_pbar.close()
        print(f"🎉 All {self.total_sessions} training sessions completed!")
        
        orchestration_results["end_time"] = time.time()
        orchestration_results["total_duration"] = orchestration_results["end_time"] - orchestration_results["start_time"]
        
        # Calculate totals from session results
        for result in orchestration_results["session_results"]:
            if result.get("status") == "completed":
                orchestration_results["total_training_time"] += result.get("pure_training_time", 0.0)
                orchestration_results["total_evaluation_time"] += result.get("evaluation_time", 0.0)
        
        # Generate final progress report
        progress_report = self.scenario_manager.get_training_progress_report()
        orchestration_results["progress_report"] = progress_report
        
        print(f"🎉 Balanced training completed!")        
        print(f"🏋️ Training time: {orchestration_results['total_training_time']:.2f} seconds")
        print(f"🧪 Evaluation time: {orchestration_results['total_duration']:.2f} seconds")
        print(f"⏱️ Total duration: {orchestration_results['total_evaluation_time']:.2f} seconds")
        print(f"📊 Successful sessions: {len([r for r in orchestration_results['session_results'] if r.get('status') == 'completed'])}")
        
        # Save orchestration results
        self._save_orchestration_results(orchestration_results)
        
        return orchestration_results

    def _execute_training_session(self, session: TrainingSession, training_config_name: str,
                                 rewards_config_name: str) -> Dict[str, Any]:
        """Execute individual training session for specific agent matchup."""
        try:
            # Silent execution to prevent log spam
            
            # Generate scenario for this matchup (Windows-compatible timeout)
            import threading
            import time
            
            scenario_result = [None]
            scenario_error = [None]
            
            def generate_with_timeout():
                try:
                    scenario_result[0] = self.scenario_manager.generate_training_scenario(
                        session.scenario_template,
                        session.opponent_agent,  # Player 0 (bot)
                        session.agent_key       # Player 1 (AI)
                    )
                except Exception as e:
                    scenario_error[0] = e
            
            # Start scenario generation in separate thread
            thread = threading.Thread(target=generate_with_timeout)
            thread.daemon = True
            thread.start()
            thread.join(timeout=10)  # 10 second timeout
            
            if thread.is_alive():
                raise TimeoutError("Scenario generation timeout (10 seconds)")
            if scenario_error[0]:
                raise scenario_error[0]
            if scenario_result[0] is None:
                raise RuntimeError("Scenario generation failed without error")
                
            scenario = scenario_result[0]
            
            # Save scenario to temporary file
            scenario_path = self._save_session_scenario(session.session_id, scenario)
            
            # Create/load model for this agent - with explicit error handling
            try:
                model_result = self._create_agent_model(
                    session.agent_key, 
                    training_config_name, 
                    rewards_config_name,
                    scenario_path
                )
                if model_result is None:
                    raise ValueError(f"_create_agent_model returned None for agent {session.agent_key}")
                if not isinstance(model_result, tuple) or len(model_result) != 2:
                    raise ValueError(f"_create_agent_model returned invalid result: {type(model_result)}")
                model, env = model_result
            except Exception as model_error:
                raise RuntimeError(f"Model creation failed for {session.agent_key}: {model_error}")
            
            # Initialize selective replay tracking
            episode_tracker = SelectiveEpisodeTracker(session.agent_key, session.opponent_agent)
            
            # Setup callbacks for this session (simplified - no evaluation callback)
            callbacks = self._setup_session_callbacks(session, model, episode_tracker, training_config_name)
            
            # Execute training
            session_start_time = time.time()
            training_config = self.config.load_training_config(training_config_name)
            total_timesteps = training_config["total_timesteps"]
            
            # Add progress tracking callback
            class ProgressTracker(BaseCallback):
                def __init__(self, trainer, session_id, verbose=0):
                    super().__init__(verbose)
                    self.trainer = trainer
                    self.session_id = session_id
                    self.last_update = 0
                
                def _on_step(self) -> bool:
                    # Update every 10 steps for more responsive progress tracking
                    if self.num_timesteps - self.last_update >= 10:
                        with self.trainer.progress_lock:
                            if self.session_id in self.trainer.session_progress:
                                self.trainer.session_progress[self.session_id]['steps'] = self.num_timesteps
                                self.trainer._update_slowest_progress()
                        self.last_update = self.num_timesteps
                    return True
            
            progress_tracker = ProgressTracker(self, session.session_id)
            all_callbacks = callbacks + [progress_tracker] if callbacks else [progress_tracker]
            
            # Execute training with individual progress tracking
            model.learn(
                total_timesteps=total_timesteps,
                callback=all_callbacks,
                log_interval=1000,  # Reduce log frequency
                progress_bar=False  # Disable built-in progress bar
            )
            
            # Record pure training time
            pure_training_time = time.time() - session_start_time
            
            # Set current session ID for evaluation progress bar identification
            self._current_session_id = session.session_id
            
            # Get number of evaluation episodes from config
            eval_episodes = training_config.get("eval_episodes")
            
            # Test the trained model WITH episode tracker for selective replay capture
            evaluation_start = time.time()
            test_results = self._test_trained_model(model, env, eval_episodes, episode_tracker)  # Use configurable evaluation episodes
            evaluation_time = time.time() - evaluation_start
            
            # Calculate total session duration (training + evaluation + model saving)
            training_duration = time.time() - session_start_time
            
            # Save agent model (persistent learning)
            agent_model_path = self._get_agent_model_path(session.agent_key)
            model.save(agent_model_path)

            # Save selective replays using episode tracker
            replay_files_saved = []
            try:
                if episode_tracker:
                    replay_files_saved = episode_tracker.save_selective_replays()
            except Exception as replay_error:
                pass  # Silent failure for replay saving
            
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
                "pure_training_time": pure_training_time,
                "evaluation_time": evaluation_time,
                "final_win_rate": test_results["win_rate"],
                "final_avg_reward": test_results["avg_reward"],
                "model_path": agent_model_path,
                "selective_replay_files": replay_files_saved
            }
            
            # Reduced verbosity - session completion tracked by progress bar
            return result
            
        except Exception as e:
            print(f"❌ Session {session.session_id} failed: {e}")
            session.status = 'failed'
            
            # Calculate duration for failed session
            session_duration = time.time() - session_start_time if 'session_start_time' in locals() else 0.0
            
            # Try to save replay even on failure using GameReplayLogger
            replay_file_saved = None
            try:
                if 'env' in locals() and env:
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    failed_replay_filename = f"ai/event_log/failed_training_{session.agent_key}_vs_{session.opponent_agent}.json"
                    
                    # Use GameReplayLogger's save method
                    if hasattr(env.unwrapped, 'replay_logger'):
                        replay_file_saved = env.unwrapped.replay_logger.save_replay(failed_replay_filename)
            except Exception as replay_error:
                pass  # Silent failure for failed session replay saving
            
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
        session_scenarios_dir = os.path.join(os.path.dirname(self.config.config_dir), "ai", "session_scenarios")
        
        if not os.path.exists(session_scenarios_dir):
            return
        
        # Find all scenario_*.json files
        pattern = os.path.join(session_scenarios_dir, "scenario_*.json")
        session_files = glob.glob(pattern)
        
        if not session_files:
            return
        
        # Delete all found session scenario files
        deleted_count = 0
        for file_path in session_files:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                pass

    def _create_agent_model(self, agent_key: str, training_config_name: str,
                           rewards_config_name: str, scenario_path: str) -> Tuple[DQN, Any]:
        """Create or load DQN model for specific agent."""
        print(f"🔧 Creating model for agent: {agent_key}")
        try:
            # Import environment here to avoid circular imports
            try:
                from gym40k import W40KEnv
                print(f"✅ W40KEnv imported successfully from gym40k")
            except ImportError:
                try:
                    from ai.gym40k import W40KEnv
                    print(f"✅ W40KEnv imported successfully from ai.gym40k")
                except ImportError as e:
                    print(f"❌ Failed to import W40KEnv: {e}")
                    raise ImportError(f"Cannot import W40KEnv: {e}")
            
            # Load training configuration
            training_config = self.config.load_training_config(training_config_name)
            if not training_config:
                raise ValueError(f"Failed to load training config: {training_config_name}")
            model_params = training_config["model_params"].copy()  # Create copy to avoid modifying original
            
            # Override verbose setting from config for multi-agent training
            model_params["verbose"] = 0
            
            # Create agent-specific environment with generated scenario and shared registry
            try:
                print(f"🏗️ Creating W40KEnv for {agent_key} with scenario {scenario_path}")
                base_env = W40KEnv(
                    rewards_config=rewards_config_name,
                    training_config_name=training_config_name,
                    controlled_agent=agent_key,
                    active_agents=[self.unit_registry.get_all_model_keys()],  # CRITICAL FIX: All agents active for proper training
                    scenario_file=scenario_path,
                    unit_registry=self.unit_registry,  # Pass shared registry
                    quiet=True  # Enable quiet mode for training
                )
                print(f"✅ W40KEnv created successfully for {agent_key}")
            except Exception as env_error:
                print(f"❌ W40KEnv creation failed for {agent_key}: {env_error}")
                raise RuntimeError(f"Failed to create W40KEnv for agent {agent_key}: {env_error}")
            
            # Enhance environment with clean game logger
            from ai.game_replay_logger import GameReplayIntegration
            print(f"🔧 Enhancing environment for {agent_key}")
            enhanced_env = GameReplayIntegration.enhance_training_env(base_env)
            print(f"✅ Environment enhanced for {agent_key}")
            
            # CRITICAL FIX: Connect replay_logger to game_logger for actual logging
            if hasattr(enhanced_env, 'replay_logger'):
                enhanced_env.game_logger = enhanced_env.replay_logger
            
            env = Monitor(enhanced_env, allow_early_resets=True)
            print(f"✅ Monitor wrapper applied for {agent_key}")
            
            # Agent-specific model path
            model_path = self._get_agent_model_path(agent_key)
            print(f"🎯 Model path for {agent_key}: {model_path}")
            
            # Create or load model (reduced verbosity)
            print(f"🤖 Creating/loading DQN model for {agent_key}")
            if os.path.exists(model_path):
                print(f"📁 Loading existing model: {model_path}")
                model = DQN.load(model_path, env=env)
                # Update model parameters for continued training
                model.tensorboard_log = model_params["tensorboard_log"]
                print(f"✅ Model loaded successfully for {agent_key}")
            else:
                print(f"🆕 Creating new model for {agent_key}")
                model = DQN(env=env, **model_params)
                print(f"✅ Model created successfully for {agent_key}")
            
            print(f"🎯 Returning model and env for {agent_key}")
            return model, env
            
        except Exception as create_error:
            raise RuntimeError(f"_create_agent_model failed for {agent_key}: {create_error}")

    def _update_slowest_progress(self):
        """Update progress bar to show the slowest agent's progress."""
        if not self.session_progress:
            return
        
        # Find the session with the lowest completion percentage
        slowest_session = None
        slowest_progress = 1.0
        
        for session_id, progress in self.session_progress.items():
            if progress['total'] > 0:
                completion = progress['steps'] / progress['total']
                if completion < slowest_progress:
                    slowest_progress = completion
                    slowest_session = progress
        
        if slowest_session:
            # Update progress bar to show slowest agent
            self.overall_pbar.n = slowest_session['steps']
            # Ensure progress bar total matches what we're actually tracking
            if self.overall_pbar.total != slowest_session['total']:
                self.overall_pbar.total = slowest_session['total']
                self.overall_pbar.refresh()
            self.overall_pbar.set_description(f"🐌 {slowest_session['agent'][:8]} vs {slowest_session['opponent'][:8]}")
            self.overall_pbar.set_postfix_str(f"{slowest_progress:.1%}")
            self.overall_pbar.refresh()

    def _setup_session_callbacks(self, session: TrainingSession, model, episode_tracker: SelectiveEpisodeTracker, training_config_name: str = "default") -> List:
        """Setup training callbacks - simplified without evaluation callback."""
        callbacks = []
        return callbacks

    def _create_eval_env_for_session(self, session: TrainingSession):
        """Create evaluation environment for session callbacks."""
        # Import environment
        try:
            from gym40k import W40KEnv
        except ImportError:
            from ai.gym40k import W40KEnv
        
        # Create evaluation environment identical to training environment
        scenario = self.scenario_manager.generate_training_scenario(
            session.scenario_template,
            session.opponent_agent,
            session.agent_key
        )
        
        # Save temporary scenario for evaluation
        import tempfile
        import json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(scenario, f, indent=2)
            temp_scenario_path = f.name
        
        # Create environment
        base_eval_env = W40KEnv(
            controlled_agent=session.agent_key,
            scenario_file=temp_scenario_path,
            unit_registry=self.unit_registry,
            quiet=True
        )

        # Create enhanced evaluation environment with clean game logger
        from ai.game_replay_logger import GameReplayIntegration
        enhanced_eval_env = GameReplayIntegration.enhance_training_env(base_eval_env)
        
        # CRITICAL FIX: Connect replay_logger to game_logger for actual logging
        if hasattr(enhanced_eval_env, 'replay_logger'):
            enhanced_eval_env.game_logger = enhanced_eval_env.replay_logger
        
        # Wrap with Monitor for proper evaluation callback integration
        from stable_baselines3.common.monitor import Monitor
        eval_env = Monitor(enhanced_eval_env, allow_early_resets=True)
        pass
        
        return eval_env

    def _test_trained_model(self, model, env, num_episodes: int = 10, episode_tracker: SelectiveEpisodeTracker = None) -> Dict[str, float]:
        """Test trained model - episode_tracker should be None to prevent test episode capture"""
        wins = 0
        total_rewards = []
        
        # Add single evaluation progress bar per session (fixed to prevent concurrent display issues)
        session_id = getattr(self, '_current_session_id', 'unknown')
        eval_pbar = tqdm(total=num_episodes, desc=f"🧪 Eval {session_id[:8]}", 
                         bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} episodes',
                         leave=False, ncols=80, position=1)
        
        for episode in range(num_episodes):
            obs, info = env.reset()
            episode_reward = 0
            done = False
            step_count = 0
            
            # CRITICAL FIX: Clear replay logger for each evaluation episode to ensure single-episode replays
            if episode_tracker:
                try:
                    # Find and clear replay logger for new episode
                    actual_env = env
                    if hasattr(actual_env, 'env'):
                        actual_env = actual_env.env
                    
                    if hasattr(actual_env, 'replay_logger') and actual_env.replay_logger:
                        actual_env.replay_logger.clear()
                    elif hasattr(actual_env, 'unwrapped') and hasattr(actual_env.unwrapped, 'replay_logger'):
                        actual_env.unwrapped.replay_logger.clear()
                except Exception:
                    pass  # Silent failure for clearing
            
            while not done and step_count < 500:  # Prevent infinite episodes
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                episode_reward += reward
                done = terminated or truncated
                step_count += 1
            
            total_rewards.append(episode_reward)
            
            # Track episode for selective replay saving using direct access to replay logger
            if episode_tracker:
                try:
                    # Find replay logger in the environment hierarchy
                    replay_logger = None
                    actual_env = env
                    
                    # Check Monitor wrapper
                    if hasattr(actual_env, 'env'):
                        actual_env = actual_env.env
                    
                    # Check for replay logger
                    if hasattr(actual_env, 'replay_logger') and actual_env.replay_logger:
                        replay_logger = actual_env.replay_logger
                    elif hasattr(actual_env, 'unwrapped') and hasattr(actual_env.unwrapped, 'replay_logger'):
                        replay_logger = actual_env.unwrapped.replay_logger
                    
                    if replay_logger:
                        # Get data directly from replay logger like PvP mode
                        game_states = getattr(replay_logger, 'game_states', [])
                        combat_log_entries = getattr(replay_logger, 'combat_log_entries', [])
                        initial_state = getattr(replay_logger, 'initial_game_state', {})
                        current_turn = getattr(replay_logger, 'current_turn', 0)
                        
                        replay_data = {
                            "episode_steps": step_count,
                            "episode_reward": episode_reward,
                            "game_states": game_states.copy() if game_states else [],
                            "combat_log": combat_log_entries.copy() if combat_log_entries else [],
                            "initial_state": initial_state.copy() if initial_state else {},
                            "game_info": {
                                "scenario": "evaluation_episode",
                                "total_turns": current_turn,
                                "winner": getattr(actual_env, 'winner', None) if hasattr(actual_env, 'winner') else None
                            }
                        }
                        
                        episode_tracker.update_episode(step_count, episode_reward, replay_data)
                    else:
                        raise ValueError(f"No replay logger found in environment for episode {episode+1}")
                        
                except Exception as replay_error:
                    raise ValueError(f"No replay data captured for episode {episode+1}: {replay_error}")
            # Check win condition
            if info.get('winner') == 1:  # AI won
                wins += 1
           
            # Update progress bar with current stats
            eval_pbar.update(1)
            current_win_rate = wins / (episode + 1)
            current_avg_reward = sum(total_rewards) / len(total_rewards)
            eval_pbar.set_postfix({'WR': f'{current_win_rate:.1%}', 'Reward': f'{current_avg_reward:.1f}'})
       
        eval_pbar.close()
       
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
            os.path.dirname(self.config.config_dir), 
            "ai", 
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

    def _analyze_player_actions(self, replay_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze replay data to check P0 vs P1 action distribution."""
        if not replay_data or 'combat_log' not in replay_data:
            return {
                'total_actions': 0,
                'p0_actions': 0,
                'p1_actions': 0,
                'p0_percentage': 0.0,
                'p1_percentage': 0.0,
                'p1_action_types': []
            }
        
        combat_log = replay_data['combat_log']
        total_actions = 0
        p0_actions = 0
        p1_actions = 0
        p1_action_types = []
        
        for entry in combat_log:
            # Skip turn_change and phase_change entries
            if entry.get('type') in ['turn_change', 'phase_change']:
                continue
                
            # Count actual game actions
            if 'player' in entry:
                total_actions += 1
                if entry['player'] == 0:
                    p0_actions += 1
                elif entry['player'] == 1:
                    p1_actions += 1
                    action_type = entry.get('type', 'unknown')
                    if action_type not in p1_action_types:
                        p1_action_types.append(action_type)
        
        # Calculate percentages
        p0_percentage = (p0_actions / total_actions * 100) if total_actions > 0 else 0.0
        p1_percentage = (p1_actions / total_actions * 100) if total_actions > 0 else 0.0
        
        return {
            'total_actions': total_actions,
            'p0_actions': p0_actions,
            'p1_actions': p1_actions,
            'p0_percentage': p0_percentage,
            'p1_percentage': p1_percentage,
            'p1_action_types': p1_action_types
        }

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