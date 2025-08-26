#!/usr/bin/env python3
"""
scripts/generate_replay.py - W40K Steplog to Replay Converter

USAGE:
    # Generate new steplog and convert to replay
    python scripts/generate_replay.py --generate --model model.zip --episodes 3 --rewards-config default

    # Convert existing steplog file to replay
    python scripts/generate_replay.py --convert train_step.log

PURPOSE: Convert detailed steplog files (from train.py --step) into frontend-compatible replay JSON files
"""

import subprocess
import os
import sys
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def main():
    """Main entry point for replay generation script."""
    parser = argparse.ArgumentParser(
        description="Generate W40K replay files from steplogs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate new replay from model
  python scripts/generate_replay.py --generate --model model_RangedSwarm.zip --episodes 3 --rewards-config default

  # Convert existing steplog
  python scripts/generate_replay.py --convert train_step.log
        """
    )
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--generate", action="store_true", 
                           help="Generate new steplog using train.py --step --test-only, then convert to replay")
    mode_group.add_argument("--convert", type=str, metavar="STEPLOG_FILE",
                           help="Convert existing steplog file to replay JSON format")
    
    # Generation options (only used with --generate)
    gen_group = parser.add_argument_group("generation options", "Used with --generate mode")
    gen_group.add_argument("--model", help="Model file path (required for --generate)")
    gen_group.add_argument("--episodes", type=int, default=3, help="Number of test episodes (default: 3)")
    gen_group.add_argument("--rewards-config", help="Rewards configuration name (required for --generate)")
    gen_group.add_argument("--deterministic", action="store_true", help="Use deterministic actions")
    gen_group.add_argument("--training-config", default="default", help="Training configuration name (default: default)")
    
    args = parser.parse_args()
    
    try:
        if args.generate:
            if not args.model or not args.rewards_config:
                parser.error("--generate mode requires --model and --rewards-config arguments")
            generate_and_convert(args)
        elif args.convert:
            convert_steplog_to_replay(args.convert)
            
    except KeyboardInterrupt:
        print("\n⏹️ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def generate_and_convert(args):
    """Full workflow: generate steplog using train.py, then convert to replay."""
    print("🎮 W40K Replay Generator - Full Workflow")
    print("=" * 50)
    
    try:
        # Step 1: Generate steplog using train.py --step --test-only
        print(f"🎯 Generating steplog with {args.episodes} episodes...")
        print(f"   Model: {args.model}")
        print(f"   Rewards: {args.rewards_config}")
        print(f"   Deterministic: {args.deterministic}")
        
        cmd = [
            "python", "ai/train.py", 
            "--step", "--test-only",
            "--model", args.model,
            "--test-episodes", str(args.episodes),
            "--rewards-config", args.rewards_config,
            "--training-config", args.training_config
        ]
        
        if args.deterministic:
            cmd.append("--deterministic")
            
        print(f"🔧 Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # Check if steplog was generated
        steplog_path = "train_step.log"
        if not os.path.exists(steplog_path):
            raise FileNotFoundError(f"Expected steplog file '{steplog_path}' was not generated")
            
        # Step 2: Convert steplog to replay format
        print("🔄 Converting steplog to replay format...")
        output_file = convert_steplog_to_replay(steplog_path)
        
        # Step 3: Cleanup temporary steplog
        print("🧹 Cleaning up temporary files...")
        os.remove(steplog_path)
        
        print(f"✅ Replay generation complete!")
        print(f"📁 Output: {output_file}")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ train.py execution failed:")
        print(f"   Return code: {e.returncode}")
        if e.stdout:
            print(f"   Output: {e.stdout}")
        if e.stderr:
            print(f"   Error: {e.stderr}")
        raise
    except Exception as e:
        print(f"❌ Generation workflow failed: {e}")
        raise

def convert_steplog_to_replay(steplog_path):
    """Convert steplog file to frontend-compatible replay JSON format."""
    if not os.path.exists(steplog_path):
        raise FileNotFoundError(f"Steplog file not found: {steplog_path}")
    
    print(f"🔄 Converting steplog: {steplog_path}")
    
    # Parse steplog file
    steplog_data = parse_steplog_file(steplog_path)
    
    # Convert to replay format
    replay_data = convert_to_replay_format(steplog_data)
    
    # Generate output filename
    base_name = os.path.splitext(os.path.basename(steplog_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"ai/event_log/replay_{base_name}_converted_{timestamp}.json"
    
    # Ensure output directory exists
    os.makedirs("ai/event_log", exist_ok=True)
    
    # Save replay file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(replay_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Conversion complete: {output_file}")
    print(f"   📊 {len(replay_data.get('combat_log', []))} combat log entries")
    print(f"   🎯 {len(replay_data.get('game_states', []))} game state snapshots")
    print(f"   🎮 {replay_data.get('game_info', {}).get('total_turns', 0)} turns")
    
    return output_file

def parse_steplog_file(steplog_path):
    """Parse steplog file and extract structured data."""
    print(f"🔍 Parsing steplog file...")
    
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
    game_states = []
    current_turn = 1
    max_turn = 1
    units_positions = {}  # Track unit positions: {unit_id: {"col": x, "row": y, "last_seen_turn": t}}
    
    # Regex pattern for action entries
    # [timestamp] TX PY PHASE : Message [SUCCESS/FAILED] [STEP: YES/NO]
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
                
                # Update unit positions from moves
                if action_data['type'] == 'move' and 'startHex' in action_data and 'endHex' in action_data:
                    unit_id = action_data.get('unitId')
                    if unit_id:
                        end_pos = action_data['endHex'].split(',')
                        if len(end_pos) == 2:
                            units_positions[unit_id] = {
                                'col': int(end_pos[0]),
                                'row': int(end_pos[1]),
                                'last_seen_turn': int(turn)
                            }
        
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
        'game_states': game_states,
        'max_turn': max_turn,
        'units_positions': units_positions
    }

def parse_action_message(message, context):
    """Parse action message and extract details."""
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
            unit_id, cur_col, cur_row, start_col, start_row, end_col, end_row = move_match.groups()
            action_type = 'move'
            details.update({
                'type': action_type,
                'message': message,
                'unitId': int(unit_id),
                'startHex': f"{start_col},{start_row}",
                'endHex': f"{end_col},{end_row}"
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

def convert_to_replay_format(steplog_data):
    """Convert parsed steplog data to frontend-compatible replay format."""
    print(f"🔄 Converting to replay format...")
    
    actions = steplog_data['actions']
    max_turn = steplog_data['max_turn']
    
    # Determine winner (simplified - no clear winner in most test cases)
    winner = None  # Could be enhanced to detect actual winner
    
    # Build initial state (simplified - would need unit registry for complete data)
    initial_units = []
    for unit_id, pos_data in steplog_data['units_positions'].items():
        initial_units.append({
            'id': unit_id,
            'unit_type': 'Intercessor',  # Simplified - could be extracted from messages
            'player': 0 if unit_id in [1, 2] else 1,  # Simplified logic
            'col': pos_data['col'],
            'row': pos_data['row'],
            'CUR_HP': 2,  # Default values - would need unit registry
            'HP_MAX': 2,
            'MOVE': 6,
            'RNG_RNG': 24,
            'RNG_DMG': 1,
            'CC_DMG': 1,
            'CC_RNG': 1
        })
    
    # Create game states snapshots (one per turn)
    game_states = []
    for turn in range(1, max_turn + 1):
        game_state = {
            'turn': turn,
            'phase': 'move',  # Simplified
            'player': 0,
            'units': [unit.copy() for unit in initial_units],  # Simplified
            'timestamp': datetime.now().isoformat()
        }
        game_states.append(game_state)
    
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
            'episode_reward': 0.0,  # Not available in steplog
            'format_version': '2.0',
            'replay_type': 'steplog_converted',
            'conversion_timestamp': datetime.now().isoformat(),
            'source_file': 'steplog'
        },
        'initial_state': {
            'units': initial_units,
            'board_size': [25, 21]  # Standard board size
        },
        'combat_log': actions,
        'game_states': game_states,
        'episode_steps': len([a for a in actions if a.get('type') != 'phase_change']),
        'episode_reward': 0.0
    }
    
    return replay_data

if __name__ == "__main__":
    main()