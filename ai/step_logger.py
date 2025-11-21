#!/usr/bin/env python3
"""
ai/step_logger.py - Step-by-step action logging

Step-by-step action logger for training debugging.
Captures ALL actions that generate step increments per AI_TURN.md.

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import time
import os
from typing import Dict, Any, Optional

__all__ = ['StepLogger']


class StepLogger:
    """
    Step-by-step action logger for training debugging.
    Captures ALL actions that generate step increments per AI_TURN.md.
    """

    def __init__(self, output_file="train_step.log", enabled=False):
        self.output_file = output_file
        self.enabled = enabled
        self.step_count = 0
        self.action_count = 0
        # Per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0

        if self.enabled:
            # Clear existing log file
            with open(self.output_file, 'w') as f:
                f.write("=== STEP-BY-STEP ACTION LOG ===\n")
                f.write("AI_TURN.md COMPLIANCE: Actions that increment episode_steps are logged\n")
                f.write("STEP INCREMENT ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)\n")
                f.write("NO STEP INCREMENT: auto-skip ineligible units, phase transitions\n")
                f.write("FAILED ACTIONS: Still increment steps - unit consumed time/effort\n")
                f.write("=" * 80 + "\n\n")
            print(f"📝 Step logging enabled: {self.output_file}")

    def log_action(self, unit_id, action_type, phase, player, success, step_increment, action_details=None):
        """Log action with step increment information using clear format"""
        if not self.enabled:
            return

        self.action_count += 1
        self.episode_action_count += 1
        if step_increment:
            self.step_count += 1
            self.episode_step_count += 1

        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())

                # Enhanced format: [timestamp] TX(col, row) PX PHASE : Message [SUCCESS/FAILED] [STEP: YES/NO]
                step_status = "STEP: YES" if step_increment else "STEP: NO"
                success_status = "SUCCESS" if success else "FAILED"
                phase_upper = phase.upper()

                # Format message using gameLogUtils.ts style
                if action_type in ["move", "shoot", "charge", "fight", "wait"]:
                    message = f"Agent P{player} {action_type}"
                    if action_details:
                        if isinstance(action_details, dict):
                            details_str = " ".join([f"{k}={v}" for k, v in action_details.items()])
                            message += f" ({details_str})"
                        else:
                            message += f" ({action_details})"

                    f.write(f"[{timestamp}] T{unit_id} P{player} {phase_upper} : {message} [{success_status}] [{step_status}]\n")
                else:
                    f.write(f"[{timestamp}] T{unit_id} P{player} {phase_upper} : {action_type} [{success_status}] [{step_status}]\n")

        except Exception as e:
            print(f"⚠️ Step logging error: {e}")

    def log_turn_start(self, turn_number, player):
        """Log the start of a new turn"""
        if not self.enabled:
            return

        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                f.write(f"\n[{timestamp}] === TURN {turn_number} START (Player {player}) ===\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")

    def log_phase_start(self, turn_number, player, to_phase):
        """Log phase transitions"""
        if not self.enabled:
            return

        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                # Clearer format: [timestamp] TX PX PHASE phase Start
                phase_upper = to_phase.upper()
                f.write(f"[{timestamp}] T{turn_number} P{player} {phase_upper} phase Start\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")

    def log_episode_end(self, total_episodes_steps, winner):
        """Log episode completion summary using replay-style format"""
        if not self.enabled:
            return

        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                f.write(f"[{timestamp}] EPISODE END: Winner={winner}, Actions={self.episode_action_count}, Steps={self.episode_step_count}, Total={total_episodes_steps}\n")
                f.write("=" * 80 + "\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")

    def reset_episode_counters(self):
        """Reset per-episode counters at episode start"""
        self.episode_step_count = 0
        self.episode_action_count = 0
