#!/usr/bin/env python3
"""
extract_lost_games.py - Extract complete games where agent LOST (Winner=1)
Usage: python extract_lost_games.py train_step.log
Output: Creates lost_game_1.txt, lost_game_2.txt, etc.
"""

import sys
import re
import os

def extract_lost_games(filepath, output_dir="lost_games"):
    """Parse train_step.log and extract complete games where agent lost."""
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    current_episode = []
    lost_game_count = 0
    total_loss_count = 0
    
    print(f"Analyzing {filepath}...")
    print(f"Output directory: {output_dir}/")
    print("-" * 80)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            # Skip header lines
            if line.startswith('===') or line.startswith('AI_TURN') or line.startswith('STEP') or line.startswith('NO STEP') or line.startswith('FAILED'):
                continue
            
            # Episode start - reset current episode
            if '=== EPISODE START ===' in line:
                current_episode = [line.strip()]
                continue
            
            # Episode end - check if it's a loss
            if 'EPISODE END' in line:
                current_episode.append(line.strip())
                
                # Extract winner
                winner_match = re.search(r'Winner=(-?\d+)', line)
                if winner_match:
                    winner = int(winner_match.group(1))
                    
                    # Check if agent lost (Winner=1 means Player 1 won, agent is Player 0)
                    if winner == 1:
                        total_loss_count += 1
                        lost_game_count += 1
                        
                        # Save complete game to file
                        output_file = os.path.join(output_dir, f"lost_game_{lost_game_count}.txt")
                        with open(output_file, 'w', encoding='utf-8') as out:
                            out.write('\n'.join(current_episode))
                        
                        print(f"✓ Saved: lost_game_{lost_game_count}.txt ({len(current_episode)} lines)")
                
                # Reset for next episode
                current_episode = []
                continue
            
            # Accumulate episode lines
            if current_episode and line.strip():
                current_episode.append(line.strip())
    
    print("-" * 80)
    print(f"\n📊 SUMMARY:")
    print(f"   Total agent losses found: {total_loss_count}")
    print(f"   Games saved to {output_dir}/: {lost_game_count}")
    print(f"\n💡 Next steps:")
    print(f"   1. Review files in {output_dir}/ directory")
    print(f"   2. Look for patterns in agent behavior")
    print(f"   3. Compare target selection between games")
    
    return lost_game_count

def print_game_summary(game_file):
    """Print a quick summary of a lost game."""
    print(f"\n{'='*80}")
    print(f"SUMMARY: {os.path.basename(game_file)}")
    print(f"{'='*80}")
    
    with open(game_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Count actions by player
    agent_shoots = 0
    bot_shoots = 0
    agent_kills = 0
    bot_kills = 0
    max_turn = 0
    
    for line in lines:
        # Parse action line: [timestamp] TX PX PHASE : Action [SUCCESS] [STEP: YES]
        match = re.match(r'\[.*?\] T(\d+) P(\d+) (\w+) : (.*?) \[(SUCCESS|FAILED)\] \[STEP: (YES|NO)\]', line)
        if match:
            turn = int(match.group(1))
            player = int(match.group(2))
            action_desc = match.group(4)
            
            max_turn = max(max_turn, turn)
            
            if 'SHOT' in action_desc.upper():
                if player == 0:
                    agent_shoots += 1
                    if 'KILLED' in action_desc or 'Dmg:2HP' in action_desc:
                        agent_kills += 1
                else:
                    bot_shoots += 1
                    if 'KILLED' in action_desc or 'Dmg:2HP' in action_desc:
                        bot_kills += 1
    
    print(f"\nGame lasted: {max_turn} turns")
    print(f"\nAgent (P0):")
    print(f"  Shots fired: {agent_shoots}")
    print(f"  Kills:       {agent_kills}")
    print(f"\nBot (P1):")
    print(f"  Shots fired: {bot_shoots}")
    print(f"  Kills:       {bot_kills}")
    
    # Show last 10 actions
    print(f"\nLast 10 actions:")
    print("-" * 80)
    action_lines = [l for l in lines if re.match(r'\[.*?\] T\d+ P\d+ \w+ :', l)]
    for line in action_lines[-10:]:
        print(line.strip())

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_lost_games.py train_step.log [--summary]")
        print("\nOptions:")
        print("  --summary    Show quick summary of each extracted game")
        sys.exit(1)
    
    log_file = sys.argv[1]
    show_summary = '--summary' in sys.argv
    
    try:
        count = extract_lost_games(log_file)
        
        # If summary requested and games were found, show summaries
        if show_summary and count > 0:
            for i in range(1, count + 1):
                game_file = f"lost_games/lost_game_{i}.txt"
                if os.path.exists(game_file):
                    print_game_summary(game_file)
        
    except FileNotFoundError:
        print(f"Error: File '{log_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)