#!/usr/bin/env python3
"""
Analyze train_step.log for charge bugs:
- Charges with targetId=None
- Charges with from==to (no movement)
- Charges from adjacent hexes
"""

import re
import sys

def analyze_log_file(log_path):
    """Analyze log file for charge bugs"""
    
    bugs_found = {
        'targetId_none': [],
        'from_equals_to': [],
        'from_adjacent': []
    }
    
    with open(log_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            # Detect charge lines
            if 'CHARGE' in line and 'CHARGED' in line:
                # Parse: "Unit X(col, row) CHARGED unit Y from (a, b) to (c, d)"
                charge_match = re.search(
                    r'Unit (\d+)\((\d+), (\d+)\) CHARGED unit (\d+|None) from \((\d+), (\d+)\) to \((\d+), (\d+)\)',
                    line
                )
                
                if charge_match:
                    unit_id = charge_match.group(1)
                    unit_col = int(charge_match.group(2))
                    unit_row = int(charge_match.group(3))
                    target_id = charge_match.group(4)
                    from_col = int(charge_match.group(5))
                    from_row = int(charge_match.group(6))
                    to_col = int(charge_match.group(7))
                    to_row = int(charge_match.group(8))
                    
                    # Bug 1: targetId=None
                    if target_id == 'None':
                        bugs_found['targetId_none'].append({
                            'line': line_num,
                            'unit_id': unit_id,
                            'from': (from_col, from_row),
                            'to': (to_col, to_row),
                            'line_text': line.strip()
                        })
                    
                    # Bug 2: from==to (no movement)
                    if from_col == to_col and from_row == to_row:
                        bugs_found['from_equals_to'].append({
                            'line': line_num,
                            'unit_id': unit_id,
                            'target_id': target_id,
                            'position': (from_col, from_row),
                            'line_text': line.strip()
                        })
                
                # Check for charges from adjacent (this might be valid in some cases)
                # We'll flag it for manual review
                if 'CHARGE' in line and ('adjacent' in line.lower() or '🚨' in line):
                    bugs_found['from_adjacent'].append({
                        'line': line_num,
                        'line_text': line.strip()
                    })
    
    return bugs_found

def print_results(bugs_found):
    """Print analysis results"""
    print("=" * 80)
    print("CHARGE BUG ANALYSIS RESULTS")
    print("=" * 80)
    
    # Bug 1: targetId=None
    if bugs_found['targetId_none']:
        print(f"\n❌ BUG 1: Found {len(bugs_found['targetId_none'])} charges with targetId=None")
        print("First 5 occurrences:")
        for bug in bugs_found['targetId_none'][:5]:
            print(f"  Line {bug['line']}: Unit {bug['unit_id']} from {bug['from']} to {bug['to']}")
            print(f"    {bug['line_text'][:100]}")
    else:
        print(f"\n✅ No charges with targetId=None found")
    
    # Bug 2: from==to
    if bugs_found['from_equals_to']:
        print(f"\n❌ BUG 2: Found {len(bugs_found['from_equals_to'])} charges with from==to")
        print("First 5 occurrences:")
        for bug in bugs_found['from_equals_to'][:5]:
            print(f"  Line {bug['line']}: Unit {bug['unit_id']} target={bug['target_id']} at {bug['position']}")
            print(f"    {bug['line_text'][:100]}")
    else:
        print(f"\n✅ No charges with from==to found")
    
    # Warnings: from adjacent
    if bugs_found['from_adjacent']:
        print(f"\n⚠️  WARNING: Found {len(bugs_found['from_adjacent'])} potential charges from adjacent hexes")
        print("First 5 occurrences:")
        for bug in bugs_found['from_adjacent'][:5]:
            print(f"  Line {bug['line']}: {bug['line_text'][:100]}")
    
    print("\n" + "=" * 80)
    
    # Summary
    total_bugs = len(bugs_found['targetId_none']) + len(bugs_found['from_equals_to'])
    if total_bugs == 0:
        print("✅ NO BUGS FOUND: All charges appear correct!")
    else:
        print(f"❌ TOTAL BUGS FOUND: {total_bugs}")
        print("Review the occurrences above and verify fixes are working.")
    print("=" * 80)

if __name__ == "__main__":
    log_path = "train_step.log"
    if len(sys.argv) > 1:
        log_path = sys.argv[1]
    
    print(f"Analyzing log file: {log_path}")
    bugs_found = analyze_log_file(log_path)
    print_results(bugs_found)