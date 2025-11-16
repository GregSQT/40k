#!/usr/bin/env python3
"""Fix shooting_handlers.py to skip reward calculation for bot units."""

import sys

# Read the file
with open('engine/phase_handlers/shooting_handlers.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "Calculate reward for this action"
for i, line in enumerate(lines):
    if '# Calculate reward for this action using progressive bonus system' in line:
        # Insert the player check after line i+2 (after action_name = "ranged_attack")
        insert_pos = i + 3

        # Check if already patched
        if 'controlled_player' in ''.join(lines[insert_pos:insert_pos+10]):
            print("Already patched!")
            sys.exit(0)

        new_lines = [
            '\n',
            '    # OPTIMIZATION: Only calculate rewards for controlled player\'s units\n',
            '    # Bot units don\'t need rewards since they don\'t learn\n',
            '    config = game_state.get("config", {})\n',
            '    controlled_player = config.get("controlled_player", 0)\n',
            '\n',
            '    # Skip reward calculation for bot units (not the controlled player)\n',
            '    if shooter["player"] != controlled_player:\n',
            '        action_reward = 0.0\n',
            '        # Continue without calculating detailed rewards\n',
            '    else:\n',
        ]

        # Insert the new lines
        lines[insert_pos:insert_pos] = new_lines

        # Indent the try block (add 4 spaces to each line until the except)
        j = insert_pos + len(new_lines)
        indent_level = 0
        while j < len(lines):
            if lines[j].strip().startswith('except Exception'):
                break
            if lines[j].strip() and not lines[j].strip().startswith('#'):
                lines[j] = '    ' + lines[j]
            j += 1

        # Write back
        with open('engine/phase_handlers/shooting_handlers.py', 'w', encoding='utf-8') as f:
            f.writelines(lines)

        print(f"SUCCESS: Patched at line {insert_pos}")
        sys.exit(0)

print("ERROR: Could not find insertion point")
sys.exit(1)
