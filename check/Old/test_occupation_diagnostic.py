#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run short training to capture validation diagnostics.

This will:
1. Run 50 episodes of training
2. Capture stderr (validation logs) and stdout (step logs)
3. Parse both to find discrepancies
"""

import subprocess
import sys
import os
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

print("=" * 80)
print("OCCUPATION BUG DIAGNOSTIC TEST")
print("=" * 80)
print()
print("Running 50 episodes of training with diagnostic logging...")
print("This will capture what validation sees vs what the log shows.")
print()

# Change to project root
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Run training with both stdout and stderr captured
cmd = [
    sys.executable,
    "ai/train.py",
    "--episodes", "50",
    "--scenario", "config/agents/SpaceMarine_Infantry_Troop_RangedSwarm/scenario.json"
]

print(f"Running: {' '.join(cmd)}")
print()

# Run and capture output
try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300  # 5 minute timeout
    )

    # Save outputs
    with open("check/validation_diagnostic.stderr", "w", encoding="utf-8") as f:
        f.write(result.stderr)

    with open("check/training_output.stdout", "w", encoding="utf-8") as f:
        f.write(result.stdout)

    print("✅ Training completed!")
    print(f"   Exit code: {result.returncode}")
    print(f"   Validation logs saved to: check/validation_diagnostic.stderr")
    print(f"   Training output saved to: check/training_output.stdout")
    print()

    # Quick analysis
    stderr_lines = result.stderr.count('\n')
    print(f"📊 Validation logs: {stderr_lines} lines")

    # Count PASSED validations
    passed_count = result.stderr.count("PASSED")
    print(f"   Validation PASSED: {passed_count} times")

    print()
    print("Next steps:")
    print("1. Run: python check/find_occupation_corruption.py")
    print("2. Compare bugs found with validation_diagnostic.stderr")
    print("3. Look for cases where validation PASSED but log shows occupation")

except subprocess.TimeoutExpired:
    print("❌ Training timed out after 5 minutes")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error running training: {e}")
    sys.exit(1)
