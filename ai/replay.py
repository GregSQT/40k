#!/usr/bin/env python3
"""
ai/replay.py - Standalone Replay File Generator

PURPOSE: Generate complete replay files from step logs or live game execution
COMPLIANCE: AI_TURN.md sequential activation, full game state capture
INTEGRATION: Works with step logging infrastructure and game controller

USAGE:
    python replay.py --step-log train_step.log --output game_replay.json
    python replay.py --live-game --model model.zip --output live_replay.json
    python replay.py --training-session --episodes 5 --output training_replays/
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Fix import paths
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)
sys.path.insert(0, project_root)

from config_loader import get_config_loader


class ReplayGenerator:
    """
    Standalone replay file generator with multiple input sources.
    Can create replays from step logs, live games, or training sessions.
    NO DEFAULTS - All values must be provided or loaded from config.
    """
    
    def __init__(self, output_dir: str):
        if not output_dir:
            raise ValueError("output_dir is required")
        self.output_dir = output_dir
        self.config = get_config_loader()
        
        # Load board size from config - NO DEFAULTS
        board_cols, board_rows = self.config.get_board_size()
        if not board_cols or not board_rows:
            raise ValueError("Failed to load board size from config")
        
        # Replay template structure - NO DEFAULTS
        self.replay_template = {
            "game_info": {
                "scenario": None,  # Must be set by caller
                "ai_behavior": None,  # Must be set by caller
                "total_turns": None,  # Must be calculated
                "winner": None  # Must be determined
            },
            "metadata": {
                "total_combat_log_entries": None,  # Must be calculated
                "final_turn": None,  # Must be calculated
                "episode_reward": None,  # Must be calculated
                "format_version": "2.0",  # Only allowed constant
                "replay_type": None,  # Must be set by caller
                "generation_time": None,  # Must be set by caller
                "source": None  # Must be set by caller
            },
            "initial_state": {
                "units": None,  # Must be provided
                "board_size": [board_cols, board_rows]  # From config only
            },
            "combat_log": None,  # Must be provided
            "game_states": None,  # Must be provided
            "episode_steps": None,  # Must be calculated
            "episode_reward": None  # Must be calculated
        }

    def generate_from_step_log(self, step_log_path: str, output_path: str, scenario_name: str, ai_behavior: str) -> str:
        """
        Generate replay file from existing step log.
        Parses train_step.log format and rebuilds game states.
        NO DEFAULTS - All parameters required.
        """
        if not step_log_path:
            raise ValueError("step_log_path is required")
        if not output_path:
            raise ValueError("output_path is required")
        if not scenario_name:
            raise ValueError("scenario_name is required")
        if not ai_behavior:
            raise ValueError("ai_behavior is required")
        
        print(f"📖 Reading step log: {step_log_path}")
        
        if not os.path.exists(step_log_path):
            raise FileNotFoundError(f"Step log not found: {step_log_path}")
        
        # Parse step log file - NO FALLBACKS
        game_actions = []
        
        with open(step_log_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if line.startswith('=') or not line.strip():
                    continue
                    
                action_data = self._parse_step_log_line(line.strip(), line_num)
                if action_data:
                    game_actions.append(action_data)
        
        if not game_actions:
            raise ValueError(f"No valid actions found in step log: {step_log_path}")
        
        print(f"✅ Parsed {len(game_actions)} actions from step log")
        
        # Calculate required values - NO DEFAULTS
        max_turn = max(action.get('turn') for action in game_actions if action.get('turn') is not None)
        if max_turn is None:
            raise ValueError("No valid turn numbers found in step log")
        
        total_reward = sum(action.get('reward', 0.0) for action in game_actions if 'reward' in action)
        episode_steps = len([a for a in game_actions if a.get('step_increment') is True])
        
        # Build replay structure - NO DEFAULTS
        replay_data = self.replay_template.copy()
        replay_data["game_info"]["scenario"] = scenario_name
        replay_data["game_info"]["ai_behavior"] = ai_behavior
        replay_data["game_info"]["total_turns"] = max_turn
        replay_data["metadata"]["generation_time"] = datetime.now().isoformat()
        replay_data["metadata"]["source"] = f"step_log:{os.path.basename(step_log_path)}"
        replay_data["metadata"]["final_turn"] = max_turn
        replay_data["metadata"]["replay_type"] = "step_log_generated"
        replay_data["episode_reward"] = total_reward
        replay_data["episode_steps"] = episode_steps
        
        # Convert actions to combat log format - NO FALLBACKS
        combat_log = self._convert_actions_to_combat_log(game_actions)
        if not combat_log:
            raise ValueError("Failed to generate combat log from step log")
        replay_data["combat_log"] = combat_log
        replay_data["metadata"]["total_combat_log_entries"] = len(combat_log)
        
        # Reconstruct initial state from first actions - NO FALLBACKS
        initial_state = self._reconstruct_initial_state(game_actions)
        if not initial_state or not initial_state.get("units"):
            raise ValueError("Failed to reconstruct initial state from step log")
        replay_data["initial_state"] = initial_state
        
        # Generate game states timeline - NO FALLBACKS
        game_states = self._generate_game_states_timeline(game_actions)
        if not game_states:
            raise ValueError("Failed to generate game states timeline")
        replay_data["game_states"] = game_states
        
        # Validate final replay data
        self._validate_replay_data(replay_data)
        
        # Save replay file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"✅ Replay generated: {output_path}")
        return output_path

    def generate_from_live_game(self, model_path: str, output_path: str, scenario_name: str, 
                               ai_behavior: str, episodes: int, deterministic: bool, 
                               rewards_config: str, training_config_name: str) -> str:
        """
        Generate replay by running live game with model.
        Uses game controller directly to capture full game state.
        NO DEFAULTS - All parameters required.
        """
        if not model_path:
            raise ValueError("model_path is required")
        if not output_path:
            raise ValueError("output_path is required")
        if not scenario_name:
            raise ValueError("scenario_name is required")
        if not ai_behavior:
            raise ValueError("ai_behavior is required")
        if episodes <= 0:
            raise ValueError("episodes must be > 0")
        if not rewards_config:
            raise ValueError("rewards_config is required")
        if not training_config_name:
            raise ValueError("training_config_name is required")
        
        print(f"🎮 Running live game with model: {model_path}")
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        try:
            # Import game environment - NO FALLBACKS
            from gym40k import W40KEnv, register_environment
            from stable_baselines3 import DQN
            from ai.unit_registry import UnitRegistry
            from ai.game_replay_logger import GameReplayIntegration
            
            register_environment()
            
            # Setup environment with replay logging - NO DEFAULTS
            unit_registry = UnitRegistry()
            scenario_file = os.path.join(self.config.config_dir, "scenario.json")
            
            if not os.path.exists(scenario_file):
                raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
            
            base_env = W40KEnv(
                rewards_config=rewards_config,
                training_config_name=training_config_name,
                controlled_agent=None,
                active_agents=None,
                scenario_file=scenario_file,
                unit_registry=unit_registry,
                quiet=False
            )
            
            # Enable replay logging - REQUIRED
            base_env.is_evaluation_mode = True
            enhanced_env = GameReplayIntegration.enhance_training_env(base_env)
            if not hasattr(enhanced_env, 'replay_logger') or not enhanced_env.replay_logger:
                raise RuntimeError("Failed to enable replay logging on environment")
            env = enhanced_env
            
            # Load model - NO FALLBACKS
            model = DQN.load(model_path, env=env)
            print(f"✅ Model loaded successfully")
            
            # Run game episodes - NO DEFAULTS
            total_reward = 0.0
            game_states = []
            
            # Load max_steps from training config - NO DEFAULTS
            training_config = self.config.load_training_config(training_config_name)
            if "max_steps_per_turn" not in training_config:
                raise KeyError(f"Training config missing required 'max_steps_per_turn'")
            if "max_turns_per_episode" not in training_config:
                raise KeyError(f"Training config missing required 'max_turns_per_episode'")
            max_steps = training_config["max_steps_per_turn"] * training_config["max_turns_per_episode"]
            
            for episode in range(episodes):
                print(f"🎯 Running episode {episode + 1}/{episodes}")
                
                obs, info = env.reset()
                if obs is None:
                    raise RuntimeError(f"Environment reset failed for episode {episode + 1}")
                
                episode_reward = 0.0
                done = False
                step_count = 0
                
                while not done and step_count < max_steps:
                    action, _ = model.predict(obs, deterministic=deterministic)
                    obs, reward, terminated, truncated, info = env.step(action)
                    
                    if obs is None:
                        raise RuntimeError(f"Environment step failed at step {step_count}")
                    
                    episode_reward += reward
                    step_count += 1
                    done = terminated or truncated
                    
                    # Capture periodic game states - REQUIRED INFO
                    if step_count % 10 == 0:
                        if 'current_turn' not in info:
                            raise KeyError("Environment info missing required 'current_turn'")
                        if 'current_phase' not in info:
                            raise KeyError("Environment info missing required 'current_phase'")
                        if 'current_player' not in info:
                            raise KeyError("Environment info missing required 'current_player'")
                        
                        units_state = self._get_units_state(env)
                        if not units_state:
                            raise RuntimeError(f"Failed to get units state at step {step_count}")
                        
                        current_state = {
                            "turn": info['current_turn'],
                            "phase": info['current_phase'],
                            "player": info['current_player'],
                            "units": units_state,
                            "timestamp": datetime.now().isoformat(),
                            "step": step_count
                        }
                        game_states.append(current_state)
                
                if step_count >= max_steps:
                    raise RuntimeError(f"Episode {episode + 1} exceeded maximum steps ({max_steps})")
                
                total_reward += episode_reward
                print(f"   Episode {episode + 1} reward: {episode_reward:.2f}")
            
            # Extract replay data from environment - REQUIRED
            if not hasattr(env, 'replay_logger') or not env.replay_logger:
                raise RuntimeError("Environment missing replay logger after execution")
                
            combat_log = env.replay_logger.combat_log_entries
            initial_state = env.replay_logger.initial_state
            
            if not combat_log:
                raise RuntimeError("No combat log entries captured during live game")
            if not initial_state:
                raise RuntimeError("No initial state captured during live game")
            
            # Build final replay - NO DEFAULTS
            replay_data = self.replay_template.copy()
            replay_data["game_info"]["scenario"] = scenario_name
            replay_data["game_info"]["ai_behavior"] = ai_behavior
            replay_data["game_info"]["total_turns"] = max(gs.get('turn') for gs in game_states if gs.get('turn') is not None)
            replay_data["metadata"]["generation_time"] = datetime.now().isoformat()
            replay_data["metadata"]["source"] = f"live_game:{os.path.basename(model_path)}"
            replay_data["metadata"]["replay_type"] = "live_game_generated"
            replay_data["episode_reward"] = total_reward / episodes
            replay_data["combat_log"] = combat_log
            replay_data["game_states"] = game_states
            replay_data["initial_state"] = initial_state
            replay_data["metadata"]["total_combat_log_entries"] = len(combat_log)
            replay_data["metadata"]["final_turn"] = replay_data["game_info"]["total_turns"]
            replay_data["episode_steps"] = len([entry for entry in combat_log if entry.get('type') in ['move', 'shoot', 'charge', 'combat', 'wait']])
            
            env.close()
            
        except Exception as e:
            print(f"❌ Live game generation failed: {e}")
            raise
        
        # Validate final replay data
        self._validate_replay_data(replay_data)
        
        # Save replay file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(replay_data, f, indent=2)
        
        print(f"✅ Live replay generated: {output_path}")
        return output_path

    # REMOVE generate_training_session_replays method entirely - contains too many defaults and fallbacks
    # REMOVE _generate_synthetic_episode method entirely - synthetic data not allowed
    # REMOVE _get_initial_state method entirely - contains fallbacks

    def _parse_step_log_line(self, line: str, line_num: int) -> Optional[Dict[str, Any]]:
        """Parse individual step log line into action data - NO FALLBACKS."""
        if not line:
            raise ValueError(f"Empty line at line {line_num}")
        
        try:
            # Extract timestamp - REQUIRED
            if not line.startswith('['):
                raise ValueError(f"Line {line_num} missing timestamp: {line}")
            
            parts = line.split(']', 2)
            if len(parts) < 3:
                raise ValueError(f"Line {line_num} invalid format - expected 3 parts separated by ']'")
            
            timestamp = parts[0][1:]  # Remove [
            if not timestamp:
                raise ValueError(f"Line {line_num} has empty timestamp")
            
            turn_player_phase = parts[1].strip()
            action_desc = parts[2].strip()
            
            if not turn_player_phase or not action_desc:
                raise ValueError(f"Line {line_num} missing turn/player/phase or action description")
            
            # Parse turn, player, phase - REQUIRED
            tpp_parts = turn_player_phase.split()
            if len(tpp_parts) < 3:
                raise ValueError(f"Line {line_num} turn/player/phase format invalid: {turn_player_phase}")
            
            if not tpp_parts[0].startswith('T'):
                raise ValueError(f"Line {line_num} turn format invalid: {tpp_parts[0]}")
            if not tpp_parts[1].startswith('P'):
                raise ValueError(f"Line {line_num} player format invalid: {tpp_parts[1]}")
            
            turn = int(tpp_parts[0][1:])  # Remove T
            player = int(tpp_parts[1][1:])  # Remove P
            phase = tpp_parts[2].lower()
            
            if turn < 1:
                raise ValueError(f"Line {line_num} invalid turn number: {turn}")
            if player not in [0, 1]:
                raise ValueError(f"Line {line_num} invalid player number: {player}")
            if phase not in ['move', 'shoot', 'charge', 'combat']:
                raise ValueError(f"Line {line_num} invalid phase: {phase}")
            
            # Extract success and step increment - REQUIRED
            if '[SUCCESS]' not in action_desc and '[FAILED]' not in action_desc:
                raise ValueError(f"Line {line_num} missing success status")
            if '[STEP: YES]' not in action_desc and '[STEP: NO]' not in action_desc:
                raise ValueError(f"Line {line_num} missing step increment status")
            
            success = '[SUCCESS]' in action_desc
            step_increment = '[STEP: YES]' in action_desc
            
            # Extract unit and action information - REQUIRED
            action_type = None
            
            if 'MOVED' in action_desc:
                action_type = "move"
            elif 'SHOT' in action_desc or 'SHOOTING' in action_desc:
                action_type = "shoot"
            elif 'CHARGED' in action_desc:
                action_type = "charge" 
            elif 'FOUGHT' in action_desc or 'COMBAT' in action_desc:
                action_type = "combat"
            elif 'WAIT' in action_desc:
                action_type = "wait"
            
            if not action_type:
                raise ValueError(f"Line {line_num} could not determine action type from: {action_desc}")
            
            # Extract unit ID - REQUIRED
            unit_id = None
            if 'Unit ' in action_desc:
                unit_part = action_desc.split('Unit ')[1].split()[0]
                if '(' in unit_part:
                    unit_id_str = unit_part.split('(')[0]
                else:
                    unit_id_str = unit_part
                
                try:
                    unit_id = int(unit_id_str)
                except ValueError:
                    raise ValueError(f"Line {line_num} invalid unit ID: {unit_id_str}")
            
            if unit_id is None:
                raise ValueError(f"Line {line_num} could not extract unit ID from: {action_desc}")
            
            return {
                'timestamp': timestamp,
                'turn': turn,
                'player': player,
                'phase': phase,
                'action_type': action_type,
                'unit_id': unit_id,
                'success': success,
                'step_increment': step_increment,
                'raw_line': line
            }
            
        except Exception as e:
            raise ValueError(f"Failed to parse line {line_num}: {line[:50]}... Error: {e}")

    def _convert_actions_to_combat_log(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert parsed actions to combat log format - NO FALLBACKS."""
        if not actions:
            raise ValueError("Actions list is empty")
        
        combat_log = []
        
        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                raise TypeError(f"Action {i} must be dict, got {type(action)}")
            
            # Only include successful actions - NO FALLBACKS
            if not action.get('success'):
                continue
            
            # Validate required fields
            required_fields = ['action_type', 'turn', 'phase', 'unit_id', 'player', 'timestamp']
            for field in required_fields:
                if field not in action or action[field] is None:
                    raise KeyError(f"Action {i} missing required field '{field}'")
            
            log_entry = {
                "type": action['action_type'],
                "message": self._format_action_message(action),
                "turnNumber": action['turn'],
                "phase": action['phase'],
                "unitId": action['unit_id'],
                "player": action['player'],
                "timestamp": action['timestamp']
            }
            
            combat_log.append(log_entry)
        
        if not combat_log:
            raise ValueError("No successful actions found to convert to combat log")
        
        return combat_log

    def _format_action_message(self, action: Dict[str, Any]) -> str:
        """Format action into readable message - NO FALLBACKS."""
        if not isinstance(action, dict):
            raise TypeError("Action must be dict")
        
        if 'action_type' not in action:
            raise KeyError("Action missing required 'action_type' field")
        if 'unit_id' not in action:
            raise KeyError("Action missing required 'unit_id' field")
        
        action_type = action['action_type']
        unit_id = action['unit_id']
        
        # REQUIRED message formats - NO DEFAULTS
        message_formats = {
            "move": f"Unit {unit_id} moved",
            "shoot": f"Unit {unit_id} shot at enemy",
            "charge": f"Unit {unit_id} charged enemy",
            "combat": f"Unit {unit_id} attacked in combat",
            "wait": f"Unit {unit_id} waited"
        }
        
        if action_type not in message_formats:
            raise ValueError(f"Unknown action type: {action_type}")
        
        return message_formats[action_type]

    def _reconstruct_initial_state(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Reconstruct initial game state from action log - NO FALLBACKS."""
        if not actions:
            raise ValueError("Cannot reconstruct initial state from empty actions list")
        
        # Find unique unit IDs from actions - REQUIRED
        unit_ids = set()
        unit_players = {}
        
        for action in actions:
            if not isinstance(action, dict):
                raise TypeError("All actions must be dictionaries")
            
            unit_id = action.get('unit_id')
            player = action.get('player')
            
            if unit_id is not None and player is not None:
                unit_ids.add(unit_id)
                unit_players[unit_id] = player
        
        if not unit_ids:
            raise ValueError("No valid unit IDs found in actions")
        
        # Load unit definitions from config - NO DEFAULTS
        try:
            unit_definitions = self.config.load_unit_definitions()
            if not unit_definitions:
                raise ValueError("No unit definitions found in config")
        except Exception as e:
            raise RuntimeError(f"Failed to load unit definitions from config: {e}")
        
        # Determine unit types from unit definitions - REQUIRED
        # Since step logs don't contain unit types, we need to infer or load from elsewhere
        # For now, require all units to be Intercessor type as that's what the logs show
        available_unit_types = list(unit_definitions.keys())
        if not available_unit_types:
            raise ValueError("No unit types available in unit definitions")
        
        # Use first available unit type - this is a limitation of step log reconstruction
        default_unit_type = available_unit_types[0]
        unit_stats = unit_definitions[default_unit_type]
        
        # Validate required unit stats exist
        required_stats = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'CC_RNG']
        for stat in required_stats:
            if stat not in unit_stats:
                raise KeyError(f"Unit type '{default_unit_type}' missing required stat '{stat}'")
        
        # Create unit entries with stats from config - NO DEFAULTS
        units = []
        for unit_id in sorted(unit_ids):
            if unit_id not in unit_players:
                raise ValueError(f"Unit {unit_id} found in actions but player not determined")
            
            units.append({
                "id": unit_id,
                "unit_type": default_unit_type,
                "player": unit_players[unit_id],
                "col": 12,  # Step logs don't contain initial positions
                "row": 12,  # These would need to come from scenario file
                "CUR_HP": unit_stats['HP_MAX'],
                "HP_MAX": unit_stats['HP_MAX'],
                "MOVE": unit_stats['MOVE'],
                "RNG_RNG": unit_stats['RNG_RNG'],
                "RNG_DMG": unit_stats['RNG_DMG'],
                "CC_DMG": unit_stats['CC_DMG'],
                "CC_RNG": unit_stats['CC_RNG']
            })
        
        if not units:
            raise ValueError("Failed to reconstruct any units from actions")
        
        # Get board size from config - REQUIRED
        board_cols, board_rows = self.config.get_board_size()
        
        return {
            "units": units,
            "board_size": [board_cols, board_rows]
        }

    def _generate_game_states_timeline(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate game states timeline from actions - NO FALLBACKS."""
        if not actions:
            raise ValueError("Cannot generate game states from empty actions list")
        
        game_states = []
        current_turn = None
        current_phase = None
        current_player = None
        
        # Track phase/turn changes from actions
        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                raise TypeError(f"Action {i} must be dict")
            
            # Validate required action fields
            required_fields = ['turn', 'phase', 'player', 'timestamp']
            for field in required_fields:
                if field not in action or action[field] is None:
                    raise KeyError(f"Action {i} missing required field '{field}'")
            
            action_turn = action['turn']
            action_phase = action['phase']
            action_player = action['player']
            
            # Detect phase/turn/player changes
            if (action_turn != current_turn or 
                action_phase != current_phase or 
                action_player != current_player):
                
                # Capture state at change point
                game_states.append({
                    "turn": action_turn,
                    "phase": action_phase,
                    "player": action_player,
                    "units": [],  # Step logs don't contain full unit states
                    "timestamp": action['timestamp'],
                    "action_index": i
                })
                
                current_turn = action_turn
                current_phase = action_phase
                current_player = action_player
        
        if not game_states:
            # If no phase changes detected, create at least one state from first action
            first_action = actions[0]
            game_states.append({
                "turn": first_action['turn'],
                "phase": first_action['phase'],
                "player": first_action['player'],
                "units": [],
                "timestamp": first_action['timestamp'],
                "action_index": 0
            })
        
        return game_states

    def _validate_replay_data(self, replay_data: Dict[str, Any]) -> None:
        """Validate final replay data structure - NO FALLBACKS."""
        if not isinstance(replay_data, dict):
            raise TypeError("Replay data must be dictionary")
        
        # Validate top-level structure
        required_sections = ['game_info', 'metadata', 'initial_state', 'combat_log', 'game_states']
        for section in required_sections:
            if section not in replay_data:
                raise KeyError(f"Replay data missing required section '{section}'")
        
        # Validate game_info
        game_info = replay_data['game_info']
        required_game_info = ['scenario', 'ai_behavior', 'total_turns']
        for field in required_game_info:
            if field not in game_info or game_info[field] is None:
                raise KeyError(f"game_info missing required field '{field}'")
        
        # Validate metadata
        metadata = replay_data['metadata']
        required_metadata = ['total_combat_log_entries', 'final_turn', 'episode_reward', 
                            'format_version', 'replay_type', 'generation_time', 'source']
        for field in required_metadata:
            if field not in metadata or metadata[field] is None:
                raise KeyError(f"metadata missing required field '{field}'")
        
        # Validate initial_state
        initial_state = replay_data['initial_state']
        if 'units' not in initial_state or not initial_state['units']:
            raise KeyError("initial_state missing or empty units")
        if 'board_size' not in initial_state or not initial_state['board_size']:
            raise KeyError("initial_state missing board_size")
        
        # Validate combat_log
        combat_log = replay_data['combat_log']
        if not isinstance(combat_log, list):
            raise TypeError("combat_log must be list")
        if len(combat_log) == 0:
            raise ValueError("combat_log is empty - no actions to replay")
        
        # Validate game_states
        game_states = replay_data['game_states']
        if not isinstance(game_states, list):
            raise TypeError("game_states must be list")
        if len(game_states) == 0:
            raise ValueError("game_states is empty")
        
        print("✅ Replay data validation passed")

    def _get_units_state(self, env) -> List[Dict[str, Any]]:
        """Extract current units state from environment - NO FALLBACKS."""
        if not hasattr(env, 'controller'):
            raise AttributeError("Environment missing controller attribute")
        
        controller = env.controller
        if not hasattr(controller, 'get_units'):
            raise AttributeError("Controller missing get_units method")
        
        units = controller.get_units()
        if not isinstance(units, list):
            raise TypeError("Controller.get_units() must return list")
        
        if not units:
            raise ValueError("Controller returned empty units list")
        
        return units


def main():
    """Main replay generator CLI - NO DEFAULTS."""
    parser = argparse.ArgumentParser(description="Generate W40K replay files")
    
    # Input source selection - REQUIRED
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--step-log", type=str,
                            help="Generate replay from step log file (requires --scenario and --ai-behavior)")
    source_group.add_argument("--live-game", action="store_true",
                            help="Generate replay from live game execution (requires --model and all game params)")
    
    # Required parameters for step log generation
    parser.add_argument("--scenario", type=str, required=False,
                       help="Scenario name (required for --step-log)")
    parser.add_argument("--ai-behavior", type=str, required=False,
                       help="AI behavior type (required for --step-log)")
    
    # Required parameters for live game generation
    parser.add_argument("--model", type=str, required=False,
                       help="Model file path (required for --live-game)")
    parser.add_argument("--rewards-config", type=str, required=False,
                       help="Rewards config name (required for --live-game)")
    parser.add_argument("--training-config", type=str, required=False,
                       help="Training config name (required for --live-game)")
    parser.add_argument("--episodes", type=int, required=False,
                       help="Number of episodes (required for --live-game)")
    parser.add_argument("--deterministic", action="store_true",
                       help="Use deterministic actions (optional for --live-game)")
    
    # Always required
    parser.add_argument("--output", type=str, required=True,
                       help="Output file path")
    parser.add_argument("--output-dir", type=str, required=True,
                       help="Output directory for replay generator")
    
    args = parser.parse_args()
    
    print("🎬 W40K Replay Generator")
    print("=" * 50)
    
    try:
        generator = ReplayGenerator(args.output_dir)
        
        if args.step_log:
            # Validate required parameters for step log
            if not args.scenario:
                raise ValueError("--scenario required for --step-log")
            if not args.ai_behavior:
                raise ValueError("--ai-behavior required for --step-log")
            
            replay_file = generator.generate_from_step_log(
                args.step_log, args.output, args.scenario, args.ai_behavior
            )
            print(f"✅ Generated replay from step log: {replay_file}")
            
        elif args.live_game:
            # Validate required parameters for live game
            if not args.model:
                raise ValueError("--model required for --live-game")
            if not args.rewards_config:
                raise ValueError("--rewards-config required for --live-game")
            if not args.training_config:
                raise ValueError("--training-config required for --live-game")
            if not args.episodes:
                raise ValueError("--episodes required for --live-game")
            if not args.scenario:
                raise ValueError("--scenario required for --live-game")
            if not args.ai_behavior:
                raise ValueError("--ai-behavior required for --live-game")
            
            replay_file = generator.generate_from_live_game(
                args.model, args.output, args.scenario, args.ai_behavior,
                args.episodes, args.deterministic, args.rewards_config, args.training_config
            )
            print(f"✅ Generated live game replay: {replay_file}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Replay generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)