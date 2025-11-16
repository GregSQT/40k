#!/usr/bin/env python3
"""Fix the indentation of the except block in shooting_handlers.py"""

# Read the file
with open('engine/phase_handlers/shooting_handlers.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and fix the except block (around line 1180)
for i in range(len(lines)):
    if i >= 1179 and lines[i].strip().startswith('except Exception as e:'):
        # This line and the next 8 lines need to be indented by 4 more spaces
        for j in range(i, min(i + 9, len(lines))):
            if lines[j].strip():  # Only indent non-empty lines
                lines[j] = '    ' + lines[j]
        break

# Write back
with open('engine/phase_handlers/shooting_handlers.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("SUCCESS: Fixed indentation")
