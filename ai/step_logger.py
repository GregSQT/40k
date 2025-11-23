#!/usr/bin/env python3
"""
ai/step_logger.py - Step-by-step action logging

Contains:
- StepLogger: Logs all actions that increment steps

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import time

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
                message = self._format_replay_style_message(unit_id, action_type, action_details)
                
                # Standard format: [timestamp] TX PX PHASE : Message [SUCCESS/FAILED] [STEP: YES/NO]
                step_status = "STEP: YES" if step_increment else "STEP: NO"
                success_status = "SUCCESS" if success else "FAILED"
                phase_upper = phase.upper()
                
                # Get turn from SINGLE SOURCE OF TRUTH
                turn_number = action_details.get('current_turn', 1) if action_details else 1
                f.write(f"[{timestamp}] T{turn_number} P{player} {phase_upper} : {message} [{success_status}] [{step_status}]\n")
                
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def log_episode_start(self, units_data, scenario_info=None, bot_name=None, walls=None):
        """Log episode start with all unit starting positions and walls"""
        if not self.enabled:
            return

        # Reset per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0

        # Use bot_name parameter or fall back to current_bot_name attribute
        effective_bot_name = bot_name or getattr(self, 'current_bot_name', None)

        try:
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                f.write(f"\n[{timestamp}] === EPISODE START ===\n")

                if scenario_info:
                    f.write(f"[{timestamp}] Scenario: {scenario_info}\n")

                if effective_bot_name:
                    f.write(f"[{timestamp}] Opponent: {effective_bot_name.capitalize()}Bot\n")

                # Log walls/obstacles for replay
                if walls:
                    wall_coords = ";".join([f"({w['col']},{w['row']})" for w in walls])
                    f.write(f"[{timestamp}] Walls: {wall_coords}\n")
                else:
                    f.write(f"[{timestamp}] Walls: none\n")

                # Log all unit starting positions
                for unit in units_data:
                    if "id" not in unit:
                        raise KeyError("Unit missing required 'id' field")
                    if "col" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'col' field")
                    if "row" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'row' field")
                    if "player" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'player' field")

                    # Use unitType instead of name (name field doesn't exist)
                    unit_type = unit.get("unitType", "Unknown")
                    player_name = f"P{unit['player']}"
                    f.write(f"[{timestamp}] Unit {unit['id']} ({unit_type}) {player_name}: Starting position ({unit['col']}, {unit['row']})\n")

                f.write(f"[{timestamp}] === ACTIONS START ===\n")
                
        except Exception as e:
            print(f"⚠️ Episode start logging error: {e}")
    
    def _format_replay_style_message(self, unit_id, action_type, details):
        """Format messages with detailed combat info - enhanced replay format"""
        # Extract unit coordinates from action_details for consistent format
        unit_coords = ""
        if details and "unit_with_coords" in details:
            # Extract coordinates from format "3(12, 7)" -> "(12, 7)"
            coords_part = details["unit_with_coords"]
            if "(" in coords_part:
                coord_start = coords_part.find("(")
                unit_coords = coords_part[coord_start:]
        
        if action_type == "move" and details:
            # Extract position info for move message
            if "start_pos" in details and "end_pos" in details:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                base_msg = f"Unit {unit_id}{unit_coords} MOVED from ({start_col}, {start_row}) to ({end_col}, {end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates from mirror_action
                base_msg = f"Unit {unit_id}{unit_coords} MOVED to ({details['col']}, {details['row']})"
            else:
                raise KeyError("Move action missing required position data")

            # Add position reward if available (like shooting reward)
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg
                
        elif action_type == "shoot":
            if "target_id" not in details:
                raise KeyError("Shoot action missing required target_id")
            if "hit_roll" not in details:
                raise KeyError("Shoot action missing required hit_roll")
            if "wound_roll" not in details:
                raise KeyError("Shoot action missing required wound_roll")
            if "save_roll" not in details:
                raise KeyError("Shoot action missing required save_roll")
            if "damage_dealt" not in details:
                raise KeyError("Shoot action missing required damage_dealt")
            if "hit_result" not in details:
                raise KeyError("Shoot action missing required hit_result")
            if "wound_result" not in details:
                raise KeyError("Shoot action missing required wound_result")
            if "save_result" not in details:
                raise KeyError("Shoot action missing required save_result")
            if "hit_target" not in details:
                raise KeyError("Shoot action missing required hit_target")
            if "wound_target" not in details:
                raise KeyError("Shoot action missing required wound_target")
            if "save_target" not in details:
                raise KeyError("Shoot action missing required save_target")
            
            target_id = details["target_id"]
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            
            hit_target = details["hit_target"]
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            
            base_msg = f"Unit {unit_id}{unit_coords} SHOT at unit {target_id}"
            detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
            
            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                detail_msg += f" [R:{reward:+.1f}]"
            
            return base_msg + detail_msg
            
        elif action_type == "shoot_individual":
            # Individual shot within multi-shot sequence
            if "target_id" not in details:
                raise KeyError("Individual shot missing required target_id")
            if "shot_number" not in details or "total_shots" not in details:
                raise KeyError("Individual shot missing required shot_number or total_shots")
                
            target_id = details["target_id"]
            shot_num = details["shot_number"]
            total_shots = details["total_shots"]
            
            # Check if this shot actually fired (hit_roll > 0 means it was attempted)
            if details.get("hit_roll") > 0:
                hit_roll = details["hit_roll"]
                wound_roll = details["wound_roll"]
                save_roll = details["save_roll"]
                damage = details["damage_dealt"]
                hit_result = details["hit_result"]
                wound_result = details["wound_result"]
                save_result = details["save_result"]
                hit_target = details["hit_target"]
                wound_target = details["wound_target"]
                save_target = details["save_target"]
                
                base_msg = f"Unit {unit_id}{unit_coords} SHOT at unit {target_id} (Shot {shot_num}/{total_shots})"
                if hit_result == "MISS":
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}(MISS)"
                elif wound_result == "FAIL":
                    # Failed wound - stop progression, don't show save/damage
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}(FAIL)"
                else:
                    # Successful wound - show full progression
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
                return base_msg + detail_msg
            else:
                return f"Unit {unit_id}{unit_coords} SHOT at unit {target_id} (Shot {shot_num}/{total_shots}) - MISS"
                
        elif action_type == "shoot_summary":
            # Summary of multi-shot sequence
            if "target_id" not in details:
                raise KeyError("Shoot summary missing required target_id")
            if "total_shots" not in details or "total_damage" not in details:
                raise KeyError("Shoot summary missing required total_shots or total_damage")
                
            target_id = details["target_id"]
            total_shots = details["total_shots"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            return f"Unit {unit_id}{unit_coords} SHOOTING COMPLETE at unit {target_id} - {total_shots} shots, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        elif action_type == "charge" and details:
            if "target_id" in details:
                target_id = details["target_id"]
                if "start_pos" in details and "end_pos" in details:
                    start_col, start_row = details["start_pos"]
                    end_col, end_row = details["end_pos"]
                    # Remove unit names, keep only IDs per your request
                    return f"Unit {unit_id}{unit_coords} CHARGED unit {target_id} from ({start_col}, {start_row}) to ({end_col}, {end_row})"
                else:
                    return f"Unit {unit_id}{unit_coords} CHARGED unit {target_id}"
            else:
                return f"Unit {unit_id}{unit_coords} CHARGED"
                
        elif action_type == "combat":
            if "target_id" not in details:
                return f"Unit {unit_id}{unit_coords} FOUGHT (no target data)"
            
            target_id = details["target_id"]
            
            # Check if all required dice data is present - if not, return simple message
            required_fields = ["hit_roll", "wound_roll", "save_roll", "damage_dealt", "hit_result", "wound_result", "save_result", "hit_target", "wound_target", "save_target"]
            if not all(field in details for field in required_fields):
                return f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (dice data incomplete)"
            
            # All dice data present - format detailed message
            hit_roll = details["hit_roll"]
            wound_roll = details["wound_roll"]
            save_roll = details["save_roll"]
            damage = details["damage_dealt"]
            hit_result = details["hit_result"]
            wound_result = details["wound_result"]
            save_result = details["save_result"]
            hit_target = details["hit_target"]
            wound_target = details["wound_target"]
            save_target = details["save_target"]
            
            base_msg = f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id}"
            
            # Apply truncation logic like shooting phase - stop after first failure
            detail_parts = [f"Hit:{hit_target}+:{hit_roll}({hit_result})"]
            
            # Only show wound if hit succeeded
            if hit_result == "HIT":
                detail_parts.append(f"Wound:{wound_target}+:{wound_roll}({wound_result})")
                
                # Only show save if wound succeeded  
                if wound_result == "WOUND":
                    detail_parts.append(f"Save:{save_target}+:{save_roll}({save_result})")
                    
                    # Only show damage if save failed (damage > 0)
                    if damage > 0:
                        detail_parts.append(f"Dmg:{damage}HP")
            
            detail_msg = f" - {' '.join(detail_parts)}"
            return base_msg + detail_msg
            
        elif action_type == "wait":
            return f"Unit {unit_id}{unit_coords} WAIT"
            
        elif action_type == "combat_individual":
            # Individual attack within multi-attack sequence
            if "target_id" not in details:
                raise KeyError("Individual attack missing required target_id")
            if "attack_number" not in details or "total_attacks" not in details:
                raise KeyError("Individual attack missing required attack_number or total_attacks")
                
            target_id = details["target_id"]
            attack_num = details["attack_number"]
            total_attacks = details["total_attacks"]
            
            # Check if this attack actually happened (hit_roll > 0 means it was attempted)
            if details.get("hit_roll") > 0:
                hit_roll = details["hit_roll"]
                wound_roll = details["wound_roll"]
                save_roll = details["save_roll"]
                damage = details["damage_dealt"]
                hit_result = details["hit_result"]
                wound_result = details["wound_result"]
                save_result = details["save_result"]
                hit_target = details["hit_target"]
                wound_target = details["wound_target"]
                save_target = details["save_target"]
                
                base_msg = f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (Attack {attack_num}/{total_attacks})"
                if hit_result == "MISS":
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}(MISS)"
                elif wound_result == "FAIL":
                    # Failed wound - stop progression, don't show save/damage
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}(FAIL)"
                else:
                    # Successful wound - show full progression
                    detail_msg = f" - Hit:{hit_target}+:{hit_roll}({hit_result}) Wound:{wound_target}+:{wound_roll}({wound_result}) Save:{save_target}+:{save_roll}({save_result}) Dmg:{damage}HP"
                return base_msg + detail_msg
            else:
                return f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id} (Attack {attack_num}/{total_attacks}) - MISS"
                
        elif action_type == "combat_summary":
            # Summary of multi-attack sequence
            if "target_id" not in details:
                raise KeyError("Combat summary missing required target_id")
            if "total_attacks" not in details or "total_damage" not in details:
                raise KeyError("Combat summary missing required total_attacks or total_damage")
                
            target_id = details["target_id"]
            total_attacks = details["total_attacks"]
            total_damage = details["total_damage"]
            hits = details.get("hits")
            wounds = details.get("wounds")
            failed_saves = details.get("failed_saves")
            
            return f"Unit {unit_id}{unit_coords} COMBAT COMPLETE at unit {target_id} - {total_attacks} attacks, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        else:
            raise ValueError(f"Unknown action_type '{action_type}' - no fallback allowed")
    
    def log_phase_transition(self, from_phase, to_phase, player, turn_number=1):
        """Log phase transitions (no step increment) using simplified format"""
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


