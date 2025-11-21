#!/usr/bin/env python3
"""
ai/replay_converter.py - Steplog to replay conversion functions

Contains:
- extract_scenario_name_for_replay: Extract scenario name for replay filename
- convert_steplog_to_replay: Convert existing steplog file to replay JSON
- generate_steplog_and_replay: Generate steplog and replay from training run
- parse_steplog_file: Parse steplog file into structured data
- parse_action_message: Parse action message from steplog
- calculate_episode_reward_from_actions: Calculate episode reward from actions
- convert_to_replay_format: Convert steplog data to replay JSON format

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

__all__ = [
    'extract_scenario_name_for_replay',
    'convert_steplog_to_replay',
    'generate_steplog_and_replay',
    'parse_steplog_file',
    'parse_action_message',
    'calculate_episode_reward_from_actions',
    'convert_to_replay_format'
]

def extract_scenario_name_for_replay():
    """Extract scenario name for replay filename from scenario template name."""
    # Check if generate_steplog_and_replay stored template name
    if hasattr(extract_scenario_name_for_replay, '_current_template_name') and extract_scenario_name_for_replay._current_template_name:
        return extract_scenario_name_for_replay._current_template_name
    
    # Check if convert_to_replay_format detected template name
    if hasattr(convert_to_replay_format, '_detected_template_name') and convert_to_replay_format._detected_template_name:
        return convert_to_replay_format._detected_template_name
    
    # Fallback: use scenario from filename if template not available
    return "scenario"   

def convert_steplog_to_replay(steplog_path):
    """Convert existing steplog file to replay JSON format."""
    import re
    from datetime import datetime
    
    if not os.path.exists(steplog_path):
        raise FileNotFoundError(f"Steplog file not found: {steplog_path}")
    
    print(f"🔄 Converting steplog: {steplog_path}")
    
    # Parse steplog file
    steplog_data = parse_steplog_file(steplog_path)
    
    # Convert to replay format
    replay_data = convert_to_replay_format(steplog_data)
    
    # Generate output filename with scenario name
    scenario_name = extract_scenario_name_for_replay()
    output_file = f"ai/event_log/replay_{scenario_name}.json"
    
    # Ensure output directory exists
    os.makedirs("ai/event_log", exist_ok=True)
    
    # Save replay file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(replay_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Conversion complete: {output_file}")
    print(f"   📊 {len(replay_data.get('combat_log', []))} combat log entries")
    print(f"   🎯 {len(replay_data.get('game_states', []))} game state snapshots")
    print(f"   🎮 {replay_data.get('game_info', {}).get('total_turns', 0)} turns")
    
    return True

def generate_steplog_and_replay(config, args):
    """Generate steplog AND convert to replay in one command - the perfect workflow!"""
    from datetime import datetime
    
    print("🎮 W40K Replay Generator - One-Shot Workflow")
    print("=" * 50)
    
    try:
        # Step 1: Enable step logging temporarily
        temp_steplog = "temp_steplog_for_replay.log"
        temp_step_logger = StepLogger(temp_steplog, enabled=True)
        original_step_logger = globals().get('step_logger')
        globals()['step_logger'] = temp_step_logger
        
        # Step 2: Load model for testing
        print("🎯 Loading model for steplog generation...")
        
        # Use explicit model path if provided, otherwise use config default
        if args.model:
            model_path = args.model
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Specified model not found: {model_path}")
        else:
            model_path = config.get_model_path()
            if not os.path.exists(model_path):
                # List available models for user guidance
                models_dir = os.path.dirname(model_path)
                if os.path.exists(models_dir):
                    available_models = [f for f in os.listdir(models_dir) if f.endswith('.zip')]
                    if available_models:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nAvailable models in {models_dir}: {available_models}\nUse --model to specify a model file")
                    else:
                        raise FileNotFoundError(f"Default model not found: {model_path}\nNo models found in {models_dir}")
                else:
                    raise FileNotFoundError(f"Default model not found: {model_path}\nModels directory does not exist: {models_dir}")
        
        W40KEngine, _ = setup_imports()
        from ai.unit_registry import UnitRegistry
        from ai.scenario_manager import ScenarioManager
        unit_registry = UnitRegistry()
        
        # Generate dynamic scenario using ScenarioManager
        scenario_manager = ScenarioManager(config, unit_registry)
        available_templates = scenario_manager.get_available_templates()
        
        if not available_templates:
            raise RuntimeError("No scenario templates available")
        
        # Select template from argument or find compatible one
        if hasattr(args, 'scenario_template') and args.scenario_template:
            if args.scenario_template not in available_templates:
                raise ValueError(f"Scenario template '{args.scenario_template}' not found. Available templates: {available_templates}")
            template_name = args.scenario_template
        else:
            # Extract agent from model filename for template matching
            agent_name = "Bot"
            if args.model:
                model_filename = os.path.basename(args.model)
                if model_filename.startswith('model_') and model_filename.endswith('.zip'):
                    agent_name = model_filename[6:-4]  # SpaceMarine_Infantry_Troop_RangedSwar
            
            # Find compatible template for this agent
            compatible_template = None
            for template in available_templates:
                try:
                    template_info = scenario_manager.get_template_info(template)
                    if agent_name in template_info.agent_compositions:
                        compatible_template = template
                        break
                except:
                    continue
            
            if compatible_template:
                template_name = compatible_template
                print(f"Found compatible template: {template_name} for agent: {agent_name}")
            else:
                # Try partial matching - look for similar agent patterns
                agent_parts = agent_name.lower().split('_')
                for template in available_templates:
                    template_lower = template.lower()
                    # Check if template contains key parts of agent name
                    if any(part in template_lower for part in agent_parts[-3:]):  # Last 3 parts: Troop_RangedSwar
                        template_name = template
                        print(f"Using similar template: {template_name} for agent: {agent_name}")
                        break
                else:
                    # Final fallback: use first template and warn user
                    template_name = available_templates[0]
                    print(f"WARNING: No compatible template found for agent {agent_name}")
                    print(f"Using fallback template: {template_name}")
                    print(f"Available templates: {available_templates}")
        
        # Agent name already extracted in template selection above
        
        # For solo scenarios, use same agent for both players
        # For cross scenarios, use agent vs different agent
        if "solo_" in template_name.lower():
            player_1_agent = agent_name  # Same agent for solo scenarios
        else:
            # For cross scenarios, try to find a different agent
            template_info = scenario_manager.get_template_info(template_name)
            available_agents = list(template_info.agent_compositions.keys())
            if len(available_agents) > 1:
                # Use a different agent from the template
                player_1_agent = [a for a in available_agents if a != agent_name][0]
            else:
                player_1_agent = agent_name  # Fallback to same agent

        # Store template name for filename generation
        extract_scenario_name_for_replay._current_template_name = template_name
        
        # Generate scenario with descriptive name
        scenario_data = scenario_manager.generate_training_scenario(
            template_name, agent_name, player_1_agent
        )
        
        # Save temporary scenario file
        temp_scenario_file = f"temp_{template_name}_scenario.json"
        with open(temp_scenario_file, 'w') as f:
            json.dump(scenario_data, f, indent=2)
        
        # Load training config to override max_turns for this environment
        # Test-only mode requires agent parameter
        if not args.agent:
            raise ValueError("--agent parameter required for test-only mode")
        training_config = config.load_agent_training_config(args.agent, args.training_config)
        if "max_turns_per_episode" not in training_config:
            raise KeyError(f"max_turns_per_episode missing from {args.agent} training config phase {args.training_config}")
        max_turns_override = training_config["max_turns_per_episode"]
        print(f"🎯 Using max_turns_per_episode: {max_turns_override} from config '{args.training_config}'")
        
        # Temporarily override game_config max_turns for this environment
        original_max_turns = config.get_max_turns()
        config._cache['game_config']['game_rules']['max_turns'] = max_turns_override
        
        try:
            env = W40KEngine(
                rewards_config=args.rewards_config,
                training_config_name=args.training_config,
                controlled_agent=None,
                active_agents=None,
                scenario_file=temp_scenario_file,
                unit_registry=unit_registry,
                quiet=True
            )
        finally:
            # Restore original max_turns after environment creation
            config._cache['game_config']['game_rules']['max_turns'] = original_max_turns
        
        # Connect step logger
        env.controller.connect_step_logger(temp_step_logger)
        model = PPO.load(model_path, env=env)
        
        # Step 3: Run test episodes with step logging
        if not hasattr(args, 'test_episodes') or args.test_episodes is None:
            raise ValueError("--test-episodes required for replay generation - no default episodes allowed")
        episodes = args.test_episodes
        print(f"🎲 Running {episodes} episodes with step logging...")
        
        for episode in range(episodes):
            print(f"   Episode {episode + 1}/{episodes}")
            obs, info = env.reset()
            done = False
            step_count = 0
            
            while not done and step_count < 1000:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                done = terminated or truncated
                step_count += 1
        
        env.close()
        
        # Step 4: Convert steplog to replay
        print("🔄 Converting steplog to replay format...")
        
        success = convert_steplog_to_replay(temp_steplog)
        
        # Step 5: Cleanup temporary files
        if os.path.exists(temp_steplog):
            os.remove(temp_steplog)
            print("🧹 Cleaned up temporary steplog file")
        
        # Clean up temporary scenario file
        if 'temp_scenario_file' in locals() and os.path.exists(temp_scenario_file):
            os.remove(temp_scenario_file)
        
        # Clean up template name context
        if hasattr(extract_scenario_name_for_replay, '_current_template_name'):
            delattr(extract_scenario_name_for_replay, '_current_template_name')
        
        # Restore original step logger
        globals()['step_logger'] = original_step_logger
        
        if success:
            print("✅ One-shot replay generation complete!")
            return True
        else:
            print("❌ Replay conversion failed")
            return False
            
    except Exception as e:
        print(f"❌ One-shot workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def parse_steplog_file(steplog_path):
    """Parse steplog file and extract structured data."""
    import re
    
    print(f"📖 Parsing steplog file...")
    
    with open(steplog_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.strip().split('\n')
    
    # Skip header lines (everything before first action)
    action_lines = []
    in_actions = False
    
    for line in lines:
        if line.startswith('[') and '] T' in line:
            in_actions = True
        if in_actions:
            action_lines.append(line)
    
    # Parse action entries
    actions = []
    max_turn = 1
    units_positions = {}
    
    # Regex patterns for parsing
    action_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) : (.+?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]'
    phase_pattern = r'\[([^\]]+)\] T(\d+) P(\d+) (\w+) phase Start'
    
    for line in action_lines:
        # Try to match action pattern
        action_match = re.match(action_pattern, line)
        if action_match:
            timestamp, turn, player, phase, message, success, step_increment = action_match.groups()
            
            # Parse action details from message
            action_data = parse_action_message(message, {
                'timestamp': timestamp,
                'turn': int(turn),
                'player': int(player), 
                'phase': phase.lower(),
                'success': success == 'SUCCESS',
                'step_increment': step_increment == 'YES'
            })
            
            if action_data:
                actions.append(action_data)
                max_turn = max(max_turn, int(turn))
                
                # Update unit positions from ALL actions (move, shoot, combat, charge, wait)
                unit_id = action_data.get('unitId')
                if unit_id:
                    # Try to extract position from action message if available
                    position_extracted = False
                    
                    if action_data['type'] == 'move' and 'startHex' in action_data and 'endHex' in action_data:
                        # Parse coordinates from "(col, row)" format
                        import re
                        end_match = re.match(r'\((\d+),\s*(\d+)\)', action_data['endHex'])
                        if end_match:
                            end_col, end_row = end_match.groups()
                            units_positions[unit_id] = {
                                'col': int(end_col),
                                'row': int(end_row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
                    
                    # For non-move actions, try to extract position from message format
                    if not position_extracted and 'message' in action_data:
                        import re
                        # Look for "Unit X(col, row)" pattern in any message
                        pos_match = re.search(r'Unit \d+\((\d+), (\d+)\)', action_data['message'])
                        if pos_match:
                            col, row = pos_match.groups()
                            units_positions[unit_id] = {
                                'col': int(col),
                                'row': int(row),
                                'last_seen_turn': int(turn)
                            }
                            position_extracted = True
        
        # Try to match phase change pattern  
        phase_match = re.match(phase_pattern, line)
        if phase_match:
            timestamp, turn, player, phase = phase_match.groups()
            
            phase_data = {
                'type': 'phase_change',
                'message': f'{phase.capitalize()} phase Start',
                'turnNumber': int(turn),
                'phase': phase.lower(),
                'player': int(player),
                'timestamp': timestamp
            }
            actions.append(phase_data)
    
    print(f"   📝 Parsed {len(actions)} action entries")
    print(f"   🎮 {max_turn} total turns detected")
    print(f"   👥 {len(units_positions)} units tracked")
    
    return {
        'actions': actions,
        'max_turn': max_turn,
        'units_positions': units_positions
    }

def parse_action_message(message, context):
    """Parse action message and extract details."""
    import re
    
    action_type = None
    details = {
        'turnNumber': context['turn'],
        'phase': context['phase'],
        'player': context['player'],
        'timestamp': context['timestamp']
    }
    
    # Parse different action types based on message content
    if "MOVED from" in message:
        # Unit X(col, row) MOVED from (start_col, start_row) to (end_col, end_row)
        move_match = re.match(r'Unit (\d+)\((\d+), (\d+)\) MOVED from \((\d+), (\d+)\) to \((\d+), (\d+)\)', message)
        if move_match:
            unit_id, _, _, start_col, start_row, end_col, end_row = move_match.groups()
            action_type = 'move'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'startHex': f"({start_col}, {start_row})",
                'endHex': f"({end_col}, {end_row})"
            })
    
    elif "SHOT at" in message:
        # Unit X(col, row) SHOT at unit Y - details...
        shoot_match = re.match(r'Unit (\d+)\([^)]+\) SHOT at unit (\d+)', message)
        if shoot_match:
            unit_id, target_id = shoot_match.groups()
            action_type = 'shoot'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "FOUGHT" in message:
        # Unit X(col, row) FOUGHT unit Y - details...
        combat_match = re.match(r'Unit (\d+)\([^)]+\) FOUGHT unit (\d+)', message)
        if combat_match:
            unit_id, target_id = combat_match.groups()
            action_type = 'combat'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "CHARGED" in message:
        # Unit X(col, row) CHARGED unit Y from (start) to (end)
        charge_match = re.match(r'Unit (\d+)\([^)]+\) CHARGED unit (\d+)', message)
        if charge_match:
            unit_id, target_id = charge_match.groups()
            action_type = 'charge'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'targetUnitId': int(target_id)
            })
    
    elif "WAIT" in message:
        # Unit X(col, row) WAIT
        wait_match = re.match(r'Unit (\d+)\([^)]+\) WAIT', message)
        if wait_match:
            unit_id = wait_match.groups()[0]
            action_type = 'wait'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id)
            })
    
    return details if action_type else None

def calculate_episode_reward_from_actions(actions, winner):
    """Calculate episode reward from action log and winner."""
    # Simple reward calculation based on winner and action count
    if winner is None:
        return 0.0
    
    # Basic reward: winner gets positive, loser gets negative
    base_reward = 10.0 if winner == 0 else -10.0
    
    # Add small bonus/penalty based on action efficiency
    action_count = len([a for a in actions if a.get('type') != 'phase_change'])
    efficiency_bonus = max(-5.0, min(5.0, (50 - action_count) * 0.1))
    
    return base_reward + efficiency_bonus

def convert_to_replay_format(steplog_data):
    """Convert parsed steplog data to frontend-compatible replay format."""
    from datetime import datetime
    from ai.unit_registry import UnitRegistry
    
    print(f"🔄 Converting to replay format...")
    
    # Store agent info for filename generation
    convert_to_replay_format._detected_agents = None
    
    actions = steplog_data['actions']
    max_turn = steplog_data['max_turn']
    
    # Load unit registry for complete unit data
    unit_registry = UnitRegistry()
    
    # Load config for board size and other settings
    config = get_config_loader()
    
    # Get board size from board_config.json (single source of truth)
    board_cols, board_rows = config.get_board_size()
    board_size = [board_cols, board_rows]
    
    # Load scenario for units data
    scenario_file = os.path.join(config.config_dir, "scenario.json")
    if not os.path.exists(scenario_file):
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
    
    with open(scenario_file, 'r') as f:
        scenario_data = json.load(f)
    
    # Determine winner from final actions
    winner = None
    for action in reversed(actions):
        if action.get('type') == 'phase_change' and 'winner' in action:
            winner = action['winner']
            break
    
    # Build initial state using actual unit registry data
    initial_units = []
    if not steplog_data['units_positions']:
        raise ValueError("No unit position data found in steplog - cannot generate replay without unit data")
    
    # Get initial scenario units for complete unit data
    if 'units' not in scenario_data:
        raise KeyError("Scenario missing required 'units' field")
    
    scenario_units = {unit['id']: unit for unit in scenario_data['units']}
    
    # No need to detect scenario name - handled by filename extraction
    
    # Use ALL units from scenario, not just those tracked in steplog
    for unit_id, scenario_unit in scenario_units.items():
        if 'col' not in scenario_unit or 'row' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required position data (col/row) in scenario")
        
        # Get unit statistics from unit registry
        if 'unit_type' not in scenario_unit:
            raise KeyError(f"Unit {unit_id} missing required 'unit_type' field")
        
        try:
            unit_stats = unit_registry.get_unit_data(scenario_unit['unit_type'])
        except ValueError as e:
            raise ValueError(f"Failed to get unit data for '{scenario_unit['unit_type']}': {e}")
        
        # Get final position from steplog tracking or use initial position
        if unit_id in steplog_data['units_positions']:
            final_col = steplog_data['units_positions'][unit_id]['col']
            final_row = steplog_data['units_positions'][unit_id]['row']
        else:
            final_col = scenario_unit['col']
            final_row = scenario_unit['row']
        
        # Build complete unit data with FINAL positions from steplog tracking
        unit_data = {
            'id': unit_id,
            'unit_type': scenario_unit['unit_type'],
            'player': scenario_unit.get('player', 0),
            'col': final_col,  # Use FINAL position from steplog tracking
            'row': final_row   # Use FINAL position from steplog tracking
        }
        
        # Copy all unit statistics from registry (preserves UPPERCASE field names)
        for field_name, field_value in unit_stats.items():
            if field_name.isupper():  # Only copy UPPERCASE fields per AI_TURN.md
                unit_data[field_name] = field_value
        
        # Ensure CUR_HP is set to HP_MAX initially
        if 'HP_MAX' in unit_stats:
            unit_data['CUR_HP'] = unit_stats['HP_MAX']
        
        initial_units.append(unit_data)
    
    # Game states require actual game state snapshots from steplog - not generated defaults
    game_states = []
    # Note: Real implementation would need to capture actual game states during steplog generation
    
    # Build replay data structure matching frontend expectations
    replay_data = {
        'game_info': {
            'scenario': 'steplog_conversion',
            'ai_behavior': 'sequential_activation',
            'total_turns': max_turn,
            'winner': winner
        },
        'metadata': {
            'total_combat_log_entries': len(actions),
            'final_turn': max_turn,
            'episode_reward': 0.0,
            'format_version': '2.0',
            'replay_type': 'steplog_converted',
            'conversion_timestamp': datetime.now().isoformat(),
            'source_file': 'steplog'
        },
        'initial_state': {
            'units': initial_units,
            'board_size': board_size
        },
        'combat_log': actions,
        'game_states': game_states,
        'episode_steps': len([a for a in actions if a.get('type') != 'phase_change']),
        'episode_reward': calculate_episode_reward_from_actions(actions, winner)
    }
    
    return replay_data


