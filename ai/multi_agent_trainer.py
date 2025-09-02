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
    total_reward: float
    replay_data: Dict[str, Any]
    
    def __hash__(self):
        """Make EpisodeMetrics hashable for use in sets - exclude replay_data."""
        return hash((self.episode_num, float(self.total_reward)))
    
    def __eq__(self, other):
        """Define equality for EpisodeMetrics - exclude replay_data."""
        if not isinstance(other, EpisodeMetrics):
            return False
        return (self.episode_num == other.episode_num and 
                abs(self.total_reward - other.total_reward) < 1e-6)

class SelectiveEpisodeTracker:
    """Track best/worst/shortest episodes during training for selective replay saving."""
    
    def __init__(self, agent_key: str, enemy_key: str, max_candidates: int):
        if max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        self.agent_key = agent_key
        self.enemy_key = enemy_key
        self.max_candidates = max_candidates
        self.episode_candidates: List[EpisodeMetrics] = []
        self.current_episode = 0
        self.shortest_episode: Optional[EpisodeMetrics] = None
        self.best_reward_episode: Optional[EpisodeMetrics] = None
        self.worst_reward_episode: Optional[EpisodeMetrics] = None
    
    def update_episode(self, total_reward: float, replay_data: Dict[str, Any]):
        """Update tracking with new training episode data."""
        self.current_episode += 1
        episode = EpisodeMetrics(self.current_episode, total_reward, replay_data)
        
        # Add to candidates
        self.episode_candidates.append(episode)
        
        # Update current bests for comparison
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
        sorted_by_reward = sorted(self.episode_candidates, key=lambda x: x.total_reward, reverse=True)
        sorted_by_worst = sorted(self.episode_candidates, key=lambda x: x.total_reward)
        
        # Use config values for episode pruning
        config_loader = get_config_loader()
        full_config = config_loader.get_training_config()
        training_config = full_config["default"]
        shared_config = full_config["shared_parameters"]
        keep_count = shared_config["episode_tracker"]["keep_per_category"]
        keep_episodes = set()
        keep_episodes.update(sorted_by_reward[:keep_count])  # Best rewards
        keep_episodes.update(sorted_by_worst[:keep_count])   # Worst rewards
        keep_episodes.update(self.episode_candidates[-keep_count:])  # Recent episodes
        
        self.episode_candidates = list(keep_episodes)
    
    def save_selective_replays(self, output_dir: str):
        """Save the 3 selective replays from training episodes."""
        saved_files = []
        
        # Determine enemy name for filename
        enemy_name = self.enemy_key if self.enemy_key in self.agent_key else "Bot"
        
        episodes_to_save = [
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
                    config_loader = get_config_loader()
                    full_config = get_config_loader().get_training_config()
                    shared_config = full_config["shared_parameters"]
                    indent_size = shared_config["json_output"]["indent_size"]
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(serializable_data, f, indent=indent_size)
                    
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
MASKABLE_DQN_AVAILABLE = False

from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback, BaseCallback
from stable_baselines3.common.monitor import Monitor
import gymnasium as gym

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
        
        # Get concurrent sessions from config - no fallbacks allowed
        if max_concurrent_sessions is None:
            training_config = self.config.load_training_config("default")
            if "max_concurrent_sessions" not in training_config:
                raise ValueError("Training config missing required 'max_concurrent_sessions'")
            self.max_concurrent_sessions = training_config["max_concurrent_sessions"]
        else:
            if max_concurrent_sessions <= 0:
                raise ValueError("max_concurrent_sessions must be positive")
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
        self.evaluation_progress = {}  # Track evaluation progress of each active session
        self.progress_lock = threading.Lock()
        self.eval_pbar = None  # Shared evaluation progress bar
        
        # Load training configuration
        full_config = self.config.get_training_config()
        self.training_config = full_config
        self.shared_config = full_config["shared_parameters"]
        
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
        # Load training config to get total_episodes if specified
        training_config = self.config.load_training_config(training_config_name)
        if "total_episodes" in training_config:
            config_total_episodes = training_config["total_episodes"]
            print(f"🚀 Starting multi-agent training | Episodes: {config_total_episodes} (from config) | Config: {training_config_name} | Phase: {training_phase or 'balanced'}")
            total_episodes = config_total_episodes  # Use config value instead of parameter
        else:
            print(f"🚀 Starting multi-agent training | Episodes: {total_episodes} (from parameter) | Config: {training_config_name} | Phase: {training_phase or 'balanced'}")
        
        # Clean up previous session scenarios
        self._cleanup_previous_session_scenarios()
        
        # Generate phase-specific training rotation first to get actual matchup count
        if training_phase:
            training_rotation = self.scenario_manager.get_phase_based_training_rotation(
                total_episodes, training_phase
            )
        else:
            training_rotation = self.scenario_manager.get_balanced_training_rotation(total_episodes)
        
        if not training_rotation:
            raise ValueError("No training rotation generated - need at least 2 agents")
        
        # Calculate episodes per matchup using ACTUAL matchup count
        episodes_per_pair = total_episodes // len(training_rotation)
        print(f"📊 Training matchups: {len(training_rotation)} | Episodes per matchup: {episodes_per_pair}")
        
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
        
        # Recalculate episodes per matchup using actual rotation count
        episodes_per_pair = total_episodes // len(training_rotation) if len(training_rotation) > 0 else 0
        print(f"🔄 Executing {len(training_rotation)} training matchups...")
        print(f"📊 Episodes per matchup: {episodes_per_pair}")
        
        # Progress tracking with slowest agent monitoring
        self.total_sessions = len(training_rotation)
        self.completed_sessions = 0
        self.session_progress = {}
        
        # Create progress bar showing matchup completion
        progress_config = self.shared_config["progress_bar"]
        self.overall_pbar = tqdm(
            total=len(training_rotation),
            desc="Training Matchups",
            unit="matchups",
            leave=progress_config["leave"],
            ncols=progress_config["ncols"]
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
            
            # Wait for batch completion with proper progress bar updates
            for session_id, future in batch_futures:
                try:
                    shared_config = self.config.get_training_config()["shared_parameters"]
                    timeout_seconds = shared_config["session_timeout_seconds"]
                    result = future.result(timeout=timeout_seconds)
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
                    
                    # Update progress tracking
                    with self.progress_lock:
                        self._update_slowest_progress()
                    
                    #print(f"✅ Session {self.completed_sessions}/{self.total_sessions}: {result['agent_key']} vs {result['opponent_agent']} | "
                    #      f"WR:{result.get('final_win_rate', 0):.0%} R:{result.get('final_avg_reward', 0):.1f}")
                    
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
        
        print(f"🏋️ Training time: {orchestration_results['total_training_time']:.2f} seconds")
        print(f"🧪 Evaluation time: {orchestration_results['total_evaluation_time']:.2f} seconds")
        print(f"⏱️ Total duration: {orchestration_results['total_duration']:.2f} seconds")
        print(f"📊 Successful sessions: {len([r for r in orchestration_results['session_results'] if r.get('status') == 'completed'])}")
        
        # Save orchestration results
        self._save_orchestration_results(orchestration_results)
        
        return orchestration_results

    def _execute_training_session(self, session: TrainingSession, training_config_name: str,
                                 rewards_config_name: str) -> Dict[str, Any]:
        """Execute individual training session for specific agent matchup."""
        try:
            # Load training configuration at start of method
            training_config = self.config.load_training_config(training_config_name)
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
            shared_config = self.config.get_training_config()["shared_parameters"]
            timeout_seconds = shared_config["session_timeout_seconds"]
            thread.join(timeout=timeout_seconds)
            
            if thread.is_alive():
                raise TimeoutError(f"Scenario generation timeout ({timeout_seconds} seconds)")
            if scenario_error[0]:
                print(f"❌ Scenario generation error: {scenario_error[0]}")
                raise scenario_error[0]
            if scenario_result[0] is None:
                raise RuntimeError("Scenario generation failed without error")
                
            scenario = scenario_result[0]
            
            # CRITICAL: Validate scenario structure before proceeding
            if not isinstance(scenario, dict):
                raise TypeError(f"Generated scenario must be dict, got {type(scenario)}")
            if "metadata" not in scenario:
                raise KeyError(f"Generated scenario missing metadata: {list(scenario.keys())}")
            if not isinstance(scenario["metadata"], dict):
                raise TypeError(f"Scenario metadata must be dict, got {type(scenario['metadata'])}")
            
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
            
            # Initialize selective replay tracking with config
            full_config = self.config.get_training_config()
            shared_config = full_config["shared_parameters"]
            max_candidates = shared_config["episode_tracker"]["max_candidates"]
            episode_tracker = SelectiveEpisodeTracker(session.agent_key, session.opponent_agent, max_candidates)
            
            # Setup callbacks for this session (simplified - no evaluation callback)
            callbacks = self._setup_session_callbacks(session, model, episode_tracker, training_config_name)
            
            # Execute training
            session_start_time = time.time()
            current_training_config = self.config.load_training_config(training_config_name)
            
            # AI_TURN COMPLIANCE: Use episode-based training, not timesteps
            if "total_episodes" in current_training_config:
                total_episodes = current_training_config["total_episodes"]
                # Calculate reasonable timesteps per episode based on max_turns
                max_turns_per_episode = current_training_config.get("max_turns_per_episode", 10)
                max_steps_per_turn = current_training_config.get("max_steps_per_turn", 50)
                total_timesteps = total_episodes * max_turns_per_episode * max_steps_per_turn
            elif "total_timesteps" in current_training_config:
                total_timesteps = current_training_config["total_timesteps"]
            else:
                raise ValueError(f"Training config '{training_config_name}' must have either 'total_timesteps' or 'total_episodes'")
            
            all_callbacks = callbacks if callbacks else []
            
            # Execute training - track progress for slowest agent monitoring
            with self.progress_lock:
                self.session_progress[session.session_id] = {
                    'current_step': 0,
                    'total_steps': total_timesteps,
                    'session_id': session.session_id
                }
            
            # Execute training with progress tracking - prevent rich display conflicts
            show_individual_progress = (
                self.shared_config["progress_bar"].get("show_progress_bar", True) and 
                self.max_concurrent_sessions == 1
            )
            # Execute training with progress tracking - show only slowest agent
            show_individual_progress = (
                self.shared_config["progress_bar"].get("show_progress_bar", True) and 
                session.session_id == self._get_slowest_session_id()
            )
            model.learn(
                total_timesteps=total_timesteps,
                callback=all_callbacks,
                log_interval=training_config["log_interval"],
                progress_bar=show_individual_progress
            )
            
            # Record pure training time
            pure_training_time = time.time() - session_start_time
            
            # Set current session ID for evaluation progress bar identification
            self._current_session_id = session.session_id
            
            # Get number of evaluation episodes from config
            eval_episodes = training_config.get("eval_episodes")
            if eval_episodes is None or eval_episodes <= 0:
                raise ValueError(f"Training config '{training_config_name}' missing or invalid 'eval_episodes': {eval_episodes}")
            
            # Test the trained model using SAME environment as training (has fixes applied)
            evaluation_start = time.time()
            test_results = self._test_trained_model(model, env, eval_episodes, episode_tracker)
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
                    output_dir = shared_config["episode_tracker"]["output_dir"]
                    replay_files_saved = episode_tracker.save_selective_replays(output_dir)
            except Exception as replay_error:
                    raise RuntimeError(f"Replay saving failed: {replay_error}")
            
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
            import traceback
            print(f"Full traceback:")
            traceback.print_exc()
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
        try:
            # Import environment here to avoid circular imports
            try:
                from gym40k import W40KEnv
            except ImportError:
                try:
                    from ai.gym40k import W40KEnv
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
                base_env = W40KEnv(
                    rewards_config=rewards_config_name,
                    training_config_name=training_config_name,
                    controlled_agent=agent_key,
                    active_agents=[self.unit_registry.get_all_model_keys()],
                    scenario_file=scenario_path,
                    unit_registry=self.unit_registry,
                    quiet=True
                )
                
                # Connect agent-specific step logger to session environment  
                try:
                    import sys
                    train_module = sys.modules.get('ai.train') or sys.modules.get('__main__')
                    if train_module and hasattr(train_module, 'step_logger') and train_module.step_logger and train_module.step_logger.enabled:
                        agent_log_file = f"train_step_{agent_key}.log"
                        from ai.train import StepLogger
                        agent_step_logger = StepLogger(agent_log_file, enabled=True)
                        base_env.controller.connect_step_logger(agent_step_logger)
                        print(f"✅ StepLogger connected for agent {agent_key}: {agent_log_file}")
                except Exception as log_error:
                    print(f"⚠️ Failed to connect step logger for {agent_key}: {log_error}")
                    
            except Exception as env_error:
                print(f"❌ W40KEnv creation failed for {agent_key}: {env_error}")
                raise RuntimeError(f"Failed to create W40KEnv for agent {agent_key}: {env_error}")
            
            # Enhance environment with clean game logger
            from ai.game_replay_logger import GameReplayIntegration
            enhanced_env = GameReplayIntegration.enhance_training_env(base_env)
            
            # CRITICAL FIX: DISABLE replay logging during training - only enable for evaluation
            if hasattr(enhanced_env, 'replay_logger'):
                enhanced_env.replay_logger.is_evaluation_mode = False  # Disable during training
                enhanced_env.game_logger = enhanced_env.replay_logger
            
            env = Monitor(enhanced_env, allow_early_resets=True)
            
            # Agent-specific model path
            model_path = self._get_agent_model_path(agent_key)
            
            # Create or load model (reduced verbosity)
            if os.path.exists(model_path):
                model = DQN.load(model_path, env=env)
                # Update model parameters for continued training
                model.tensorboard_log = model_params["tensorboard_log"]
            else:
                print("✅ Using DQN with manual action masking in gym environment")
                model = DQN(env=env, **model_params)
            return model, env
            
        except Exception as create_error:
            raise RuntimeError(f"_create_agent_model failed for {agent_key}: {create_error}")

    def _update_slowest_progress(self):
        """Update progress bar to show training progress."""
        # Simple increment for completed sessions
        self.overall_pbar.n = self.completed_sessions
        self.overall_pbar.refresh()
    
    def _get_slowest_session_id(self):
        """Get the session ID of the slowest training session."""
        if not self.session_progress:
            return None
        
        slowest_session = None
        slowest_progress = 1.0
        
        for session_id, progress in self.session_progress.items():
            if progress['total_steps'] > 0:
                completion = progress['current_step'] / progress['total_steps']
                if completion < slowest_progress:
                    slowest_progress = completion
                    slowest_session = session_id
        
        return slowest_session
    
    def _get_slowest_evaluation_session_id(self):
        """Get the session ID of the slowest evaluation session."""
        if not self.evaluation_progress:
            return None
        
        slowest_session = None
        slowest_progress = 1.0
        
        for session_id, progress in self.evaluation_progress.items():
            if progress['total'] > 0:
                completion = progress['episodes'] / progress['total']
                if completion < slowest_progress:
                    slowest_progress = completion
                    slowest_session = session_id
        
        return slowest_session

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
        
        # Create environment with same fixes as training environment
        base_eval_env = W40KEnv(
            controlled_agent=session.agent_key,
            scenario_file=temp_scenario_path,
            unit_registry=self.unit_registry,
            quiet=True
        )

        # Skip problematic replay logging during evaluation to prevent hangs
        # evaluation environments should use the same controller fixes as training
        from stable_baselines3.common.monitor import Monitor
        eval_env = Monitor(base_eval_env, allow_early_resets=True)
        pass
        
        return eval_env

    def _test_trained_model(self, model, env, num_episodes: int, episode_tracker: SelectiveEpisodeTracker = None) -> Dict[str, float]:
        """Test trained model with optimized single progress bar"""
        # AI_TURN.md COMPLIANCE: No default values - validate input
        if num_episodes <= 0:
            raise ValueError(f"num_episodes must be positive, got {num_episodes}")
            
        wins = 0
        total_rewards = []
        session_id = getattr(self, '_current_session_id', 'unknown')
        
        # Create single clean evaluation progress bar
        with self.progress_lock:
            # Track this session's evaluation progress 
            self.evaluation_progress[session_id] = {
                'episodes': 0,
                'total': num_episodes,
                'agent': session_id[:8],
                'wins': 0,
                'total_reward': 0.0
            }
            
            # Create single shared eval bar - simplified config
            if not hasattr(self, 'eval_pbar') or self.eval_pbar is None:
                self.eval_pbar = tqdm(
                    total=num_episodes, 
                    desc="🧪 Eval slowest",
                    leave=False, 
                    ncols=120, 
                    position=1
                )
        
        for episode in range(num_episodes):
            obs, info = env.reset()
            episode_reward = 0
            done = False
           
            # CRITICAL FIX: Enable replay logging for evaluation episode
            if episode_tracker:
                try:
                    # Set evaluation mode flags at ALL levels
                    env.is_evaluation_mode = True
                    
                    # Find actual environment through wrappers
                    actual_env = env
                    while hasattr(actual_env, 'env'):
                        actual_env.is_evaluation_mode = True
                        actual_env._force_evaluation_mode = True
                        actual_env = actual_env.env
                    
                    # Enable on unwrapped environment
                    if hasattr(actual_env, 'unwrapped'):
                        actual_env.unwrapped.is_evaluation_mode = True
                        actual_env.unwrapped._force_evaluation_mode = True
                    
                    # Enable on replay logger directly
                    if hasattr(actual_env, 'replay_logger') and actual_env.replay_logger:
                        actual_env.replay_logger.is_evaluation_mode = True
                        actual_env.replay_logger.env.is_evaluation_mode = True
                        actual_env.replay_logger.env._force_evaluation_mode = True
                        actual_env.replay_logger.clear()
                except Exception as e:
                    print(f"⚠️ Failed to enable replay logging: {e}")
           
            # Add step counter to prevent infinite loops
            step_count = 0
            debug_config = self.config.load_training_config("debug")
            max_steps = debug_config["max_turns_per_episode"] * debug_config["max_steps_per_turn"]
            while not done and step_count < max_steps:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                step_count += 1
                
                # CRITICAL FIX: Check game over conditions properly
                if not done:
                    current_turn = info.get('current_turn')
                    eligible_units = info.get('eligible_units')
                    ai_units_alive = info.get('ai_units_alive')
                    enemy_units_alive = info.get('enemy_units_alive')
                    
                    # Check if game should end naturally
                    if ai_units_alive == 0 or enemy_units_alive == 0:
                        print(f"🏁 Episode {episode + 1} ended: AI={ai_units_alive}, Enemy={enemy_units_alive}")
                        done = True
                    # Use config-based max_turns from game_config.json
                    elif current_turn > self.config.get_max_turns():
                        config_max_turns = self.config.get_max_turns()
                        print(f"⚠️ Episode {episode + 1} auto-terminated due to turn limit (turn {current_turn}, max: {config_max_turns})")
                        done = True
                    elif eligible_units == 0:
                        # Force phase advancement when stuck
                        if hasattr(env, 'controller') and hasattr(env.controller, '_advance_gym_phase_or_turn'):
                            try:
                                env.controller._advance_gym_phase_or_turn()
                                # Re-check after phase advancement
                                obs = env._get_obs()
                                info = env._get_info()
                            except Exception:
                                pass  # Continue if phase advancement fails
            
            # Debug infinite loop detection
            if step_count >= max_steps:
                # Force game over for stuck episodes
                done = True
                episode_reward += reward  # Add final reward
            
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
                        # Force replay logger to capture data by directly calling log methods
                        current_turn = info.get('current_turn', 1)
                        
                        # CRITICAL FIX: Enable the disabled logging line in controller
                        actual_env = env
                        while hasattr(actual_env, 'env'):
                            actual_env = actual_env.env
                        
                        if hasattr(actual_env, 'controller'):
                            # Get the controller's execute_gym_action method source and patch it
                            import types
                            controller = actual_env.controller
                            
                            # Create new method with logging enabled
                            def patched_execute_gym_action(self, action: int):
                                try:
                                    eligible_units = self._get_gym_eligible_units()
                                    controlled_eligible_units = [u for u in eligible_units if u["player"] == 1]
                                    
                                    if not controlled_eligible_units:
                                        return self._get_gym_obs(), self._get_gym_penalty_reward(), False, False, self._get_gym_info()
                                    
                                    unit_idx = action // 8
                                    action_type = action % 8
                                except Exception as e:
                                    raise
                                
                                if unit_idx >= len(controlled_eligible_units):
                                    return self._get_gym_obs(), self._get_gym_penalty_reward(), False, False, self._get_gym_info()
                                
                                acting_unit = controlled_eligible_units[unit_idx]
                                mirror_action = self._convert_gym_action_to_mirror(acting_unit, action_type)
                                
                                success = self.execute_action(acting_unit["id"], mirror_action)
                                reward = self._calculate_gym_reward(acting_unit, mirror_action, success)
                                
                                # ENABLE LOGGING FOR EVALUATION
                                self._log_gym_action(acting_unit, mirror_action, reward)
                                
                                self._mark_gym_unit_as_acted(acting_unit)
                                self._advance_gym_phase_or_turn()
                                terminated = self.is_game_over()
                                
                                return self._get_gym_obs(), reward, terminated, False, self._get_gym_info()
                            
                            # Replace the method and verify it worked
                            original_method = controller.execute_gym_action
                            controller.execute_gym_action = types.MethodType(patched_execute_gym_action, controller)
                        
                        # Now get the data
                        game_states = getattr(replay_logger, 'game_states', [])
                        combat_log_entries = getattr(replay_logger, 'combat_log_entries', [])
                        initial_state = getattr(replay_logger, 'initial_game_state', {})
                        
                        replay_data = {
                            "episode_reward": episode_reward,
                            "game_states": game_states.copy() if game_states else [],
                            "combat_log": combat_log_entries.copy() if combat_log_entries else [],
                            "initial_state": initial_state.copy() if initial_state else {},
                            "game_info": {
                                "scenario": "evaluation_episode", 
                                "total_turns": max(1, current_turn),
                                "winner": info.get('winner', None)
                            }
                        }
                        
                        episode_tracker.update_episode(episode_reward, replay_data)
                    else:
                        raise ValueError(f"No replay logger found for episode {episode+1}")
                        
                except Exception as replay_error:
                    raise ValueError(f"No replay data captured for episode {episode+1}: {replay_error}")
            # Check win condition
            if info.get('winner') == 1:  # AI won
                wins += 1
           
            # Update shared evaluation progress tracking
            with self.progress_lock:
                if session_id in self.evaluation_progress:
                    self.evaluation_progress[session_id]['episodes'] = episode + 1
                    self.evaluation_progress[session_id]['wins'] = wins
                    self.evaluation_progress[session_id]['total_reward'] = sum(total_rewards) / len(total_rewards)
                    self._update_slowest_evaluation_progress()
       
        # Clean up evaluation progress tracking for this session with error handling
        with self.progress_lock:
            if session_id in self.evaluation_progress:
                del self.evaluation_progress[session_id]
            # Close shared evaluation progress bar when no more evaluations - with error handling
            if not self.evaluation_progress and hasattr(self, 'eval_pbar') and self.eval_pbar:
                try:
                    self.eval_pbar.close()
                except Exception:
                    pass  # Ignore rich display errors during cleanup
                self.eval_pbar = None
       
        win_rate = wins / num_episodes
        avg_reward = sum(total_rewards) / len(total_rewards)
        
        return {
            "win_rate": win_rate,
            "avg_reward": avg_reward,
            "total_episodes": num_episodes
        }

    def _update_slowest_evaluation_progress(self):
        """Update shared evaluation progress bar to show the slowest evaluation."""
        if not self.evaluation_progress or not hasattr(self, 'eval_pbar') or not self.eval_pbar:
            return
        
        # Find the session with the lowest evaluation completion percentage
        slowest_eval = None
        slowest_progress = 1.0
        
        for session_id, progress in self.evaluation_progress.items():
            if progress['total'] > 0:
                completion = progress['episodes'] / progress['total']
                if completion < slowest_progress:
                    slowest_progress = completion
                    slowest_eval = progress
        
        if slowest_eval:
            # Update shared evaluation progress bar to show slowest evaluation
            self.eval_pbar.n = slowest_eval['episodes']
            if self.eval_pbar.total != slowest_eval['total']:
                self.eval_pbar.total = slowest_eval['total']
            current_wr = slowest_eval['wins'] / max(1, slowest_eval['episodes'])
            self.eval_pbar.set_description(f"🧪 Eval {slowest_eval['agent']}")
            self.eval_pbar.set_postfix({'WR': f'{current_wr:.1%}', 'Reward': f'{slowest_eval["total_reward"]:.1f}'})
            self.eval_pbar.refresh()

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
        # Extract agent names from scenario metadata - validate structure
        if "metadata" not in scenario:
            raise KeyError(f"Scenario missing required 'metadata' field: {type(scenario)}")
        
        metadata = scenario["metadata"]
        if not isinstance(metadata, dict):
            raise TypeError(f"Scenario metadata must be dict, got {type(metadata)}: {metadata}")
        
        if "player_0_agent" not in metadata:
            raise KeyError(f"Scenario metadata missing 'player_0_agent': {list(metadata.keys())}")
        if "player_1_agent" not in metadata:
            raise KeyError(f"Scenario metadata missing 'player_1_agent': {list(metadata.keys())}")
        if "generated_timestamp" not in metadata:
            raise KeyError(f"Scenario metadata missing 'generated_timestamp': {list(metadata.keys())}")
        
        player_0_agent = metadata["player_0_agent"]
        player_1_agent = metadata["player_1_agent"]
        timestamp = metadata["generated_timestamp"]
        
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
        
        # Test small training run (would need actual environment)
        print("⚠️ Skipping actual training test (requires full environment)")
        
        # Test state saving
        state_path = trainer.save_training_state()
        
        print("🎉 Multi-agent trainer tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_multi_agent_trainer()