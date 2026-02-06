#!/usr/bin/env python3
"""
ai/step_logger.py - Step-by-step action logging

Contains:
- StepLogger: Logs all actions that increment steps

Extracted from ai/train.py during refactoring (2025-01-21)
"""

import time
import builtins
import json

from shared.data_validation import require_key

__all__ = ['StepLogger']

class StepLogger:
    """
    Step-by-step action logger for training debugging.
    Captures ALL actions that generate step increments per AI_TURN.md.
    """
    
    def __init__(self, output_file: str = "step.log", enabled: bool = False, buffer_size: int = None, debug_mode: bool = False):
        self.output_file = output_file
        self.enabled = enabled
        self.debug_mode = debug_mode  # LOG TEMPORAIRE: timings/logs to debug.log only when --debug
        self.step_count = 0
        self.action_count = 0
        # Per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0
        self.episode_number = 0  # Track episode number for logging
        self._last_step_wall = None  # Wall-clock of last step end (for STEP_TIMING → analyzer "Step Durations")
        # PERFORMANCE: Buffer logs to reduce I/O (buffer_size from training_config step_log_buffer_size)
        # Obligatoire si enabled ; si disabled, buffer_size peut être None (non utilisé).
        if enabled and buffer_size is None:
            raise ValueError("buffer_size is required when step logging is enabled (from training_config step_log_buffer_size)")
        self.log_buffer = []
        self.buffer_size = buffer_size if buffer_size is not None else 0
        
        if self.enabled:
            # Clear existing log file
            with open(self.output_file, 'w') as f:
                f.write("=== STEP-BY-STEP ACTION LOG ===\n")
                f.write("AI_TURN.md COMPLIANCE: Actions that increment episode_steps are logged\n")
                f.write("INCREMENTED ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)\n")
                f.write("NON-INCREMENTED: auto-skip ineligible units, phase transitions\n")
                f.write("FAILED ACTIONS: Still increment steps - unit consumed time/effort\n")
                f.write("=" * 80 + "\n\n")
            print(f"📝 Step logging enabled: {self.output_file}")
    
    def log_action(self, unit_id, action_type, phase, player, success, step_increment, action_details=None, step_calls_since_last=None):
        """Log action with step increment information using clear format.
        step_calls_since_last: LOG TEMPORAIRE -- number of step() calls since last step_increment (--debug).
        """
        # LOG TEMPORAIRE: Log when log_action is called for move actions (only if --debug)
        import time
        call_id = f"{time.time():.6f}_{id(self)}_{self.action_count}"
        if self.debug_mode and action_type == "move" and action_details:
            try:
                with open("debug.log", "a") as f:
                    f.write(f"[STEP_LOGGER log_action CALLED] ID={call_id} Unit {unit_id}: enabled={self.enabled} unit_with_coords={action_details.get('unit_with_coords')} end_pos={action_details.get('end_pos')} col={action_details.get('col')} row={action_details.get('row')}\n")
            except Exception:
                pass
        
        if not self.enabled:
            return
            
        self.action_count += 1
        self.episode_action_count += 1
        if step_increment:
            self.step_count += 1
            self.episode_step_count += 1
            # LOG TEMPORAIRE: STEP_TIMING → debug.log for analyzer "Step Durations" (only if --debug).
            # step_index = episode_step_count so it matches WRAPPER_STEP_TIMING (wrapper reads episode_steps after return).
            now = time.time()
            duration_s = (now - self._last_step_wall) if self._last_step_wall is not None else 0.0
            step_index = self.episode_step_count
            if self.debug_mode:
                try:
                    with open("debug.log", "a") as f_db:
                        suffix = f" step_calls={step_calls_since_last}" if step_calls_since_last is not None else ""
                        f_db.write(f"STEP_TIMING episode={self.episode_number} step_index={step_index} duration_s={duration_s:.6f}{suffix}\n")
                except Exception:
                    pass
            self._last_step_wall = now

        try:
            timestamp = time.strftime("%H:%M:%S", time.localtime())

            # Format message using gameLogUtils.ts style
            message = self._format_replay_style_message(unit_id, action_type, action_details)
            
            
            # Standard format: [timestamp] TX PX PHASE : Message [SUCCESS/FAILED]
            success_status = "SUCCESS" if success else "FAILED"
            phase_upper = phase.upper()
            
            # Get turn and episode from SINGLE SOURCE OF TRUTH
            if action_details is None:
                raise ValueError("action_details is required to log current_turn")
            turn_number = require_key(action_details, 'current_turn')
            # Use self.episode_number which is updated in log_episode_start()
            episode_number = self.episode_number
            # Include episode in log line: [timestamp] E{episode} T{turn} P{player} PHASE : Message
            log_line = f"[{timestamp}] E{episode_number} T{turn_number} P{player} {phase_upper} : {message} [{success_status}]\n"
            # PERFORMANCE: Buffer logs and flush periodically to reduce I/O overhead
            self.log_buffer.append(log_line)
            if len(self.log_buffer) >= self.buffer_size:
                self._flush_buffer()
            
            # LOG TEMPORAIRE: Log what was actually written to step.log (only if --debug)
            if self.debug_mode and action_type == "move":
                try:
                    with open("debug.log", "a") as f_debug:
                        f_debug.write(f"[STEP_LOGGER AFTER WRITE] ID={call_id} Unit {unit_id}: log_line written={log_line.strip()}\n")
                except Exception:
                    pass
                
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def _flush_buffer(self):
        """Flush buffered logs to file"""
        if not self.enabled or not self.log_buffer:
            return
        try:
            # CRITICAL: Use builtins.open to ensure availability even if open is shadowed
            with builtins.open(self.output_file, 'a') as f:
                f.writelines(self.log_buffer)
            self.log_buffer = []
        except Exception as e:
            print(f"⚠️ Step logging flush error: {e}")
    
    def log_episode_start(self, units_data, scenario_info=None, bot_name=None, walls=None, objectives=None, primary_objective_config=None):
        """Log episode start with all unit starting positions, walls, and objectives"""
        if not self.enabled:
            return

        # PERFORMANCE: Flush any remaining buffered logs before episode start
        self._flush_buffer()

        self._episode_start_wall = time.perf_counter()
        self._last_step_wall = time.perf_counter()  # First step duration = time since episode start

        # Increment episode number
        self.episode_number += 1
        
        # Reset per-episode counters
        self.episode_step_count = 0
        self.episode_action_count = 0

        # Use bot_name parameter or fall back to current_bot_name attribute
        effective_bot_name = bot_name or getattr(self, 'current_bot_name', None)

        try:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            episode_marker = f"\n[{timestamp}] === EPISODE {self.episode_number} START ===\n"
            
            # Write to step.log: validate first (inside with open), then write so we never emit a partial header
            with open(self.output_file, 'a') as f:
                units_list = list(units_data)
                for unit in units_list:
                    if "id" not in unit:
                        raise KeyError("Unit missing required 'id' field")
                    if "col" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'col' field")
                    if "row" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'row' field")
                    if "player" not in unit:
                        raise KeyError(f"Unit {unit['id']} missing required 'player' field")

                f.write(episode_marker)

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

                # Log objectives for replay - format: name:(col,row);(col,row)|name2:(col,row);...
                if objectives:
                    obj_strs = []
                    for obj in objectives:
                        if "name" in obj:
                            name = obj["name"]
                        else:
                            name = f"Obj{require_key(obj, 'id')}"
                        hexes = require_key(obj, "hexes")
                        hex_coords = ";".join([f"({h[0]},{h[1]})" for h in hexes])
                        obj_strs.append(f"{name}:{hex_coords}")
                    f.write(f"[{timestamp}] Objectives: {'|'.join(obj_strs)}\n")
                else:
                    f.write(f"[{timestamp}] Objectives: none\n")

                rules_payload = {
                    "primary_objective": primary_objective_config
                }
                f.write(f"[{timestamp}] Rules: {json.dumps(rules_payload, separators=(',', ':'))}\n")

                # Log all unit starting positions (already validated above)
                for unit in units_list:
                    unit_type = require_key(unit, "unitType")
                    player_name = f"P{unit['player']}"
                    f.write(f"[{timestamp}] Unit {unit['id']} ({unit_type}) {player_name}: Starting position ({unit['col']},{unit['row']})\n")

                f.write(f"[{timestamp}] === ACTIONS START ===\n")
            
                
        except Exception as e:
            print(f"⚠️ Episode start logging error: {e}")
    
    def _format_replay_style_message(self, unit_id, action_type, details):
        """Format messages with detailed combat info - enhanced replay format"""
        # CRITICAL: Handle None details gracefully
        if details is None:
            details = {}
        
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
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                # LOG TEMPORAIRE: Log exact values in _format_replay_style_message to debug.log (only if --debug)
                if self.debug_mode:
                    try:
                        with open("debug.log", "a") as f:
                            f.write(f"[STEP_LOGGER DEBUG] Unit {unit_id}: unit_coords={unit_coords} start_pos=({start_col},{start_row}) end_pos=({end_col},{end_row}) unit_with_coords={details.get('unit_with_coords')} col={details.get('col')} row={details.get('row')}\n")
                    except Exception:
                        pass  # Don't fail if logging fails
                base_msg = f"Unit {unit_id}{unit_coords} MOVED from ({start_col},{start_row}) to ({end_col},{end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates from mirror_action
                base_msg = f"Unit {unit_id}{unit_coords} MOVED to ({details['col']},{details['row']})"
            else:
                raise KeyError("Move action missing required position data")

            # Add position reward if available (like shooting reward)
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "flee" and details:
            # FLEE: Unit flees from enemy (same format as move but indicates flee)
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                base_msg = f"Unit {unit_id}{unit_coords} FLED from ({start_col},{start_row}) to ({end_col},{end_row})"
            elif "col" in details and "row" in details:
                # Use destination coordinates
                base_msg = f"Unit {unit_id}{unit_coords} FLED to ({details['col']},{details['row']})"
            else:
                raise KeyError("Flee action missing required position data")

            # Add position reward if available
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "advance" and details:
            # ADVANCE_IMPLEMENTATION: Format advance action message
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                advance_range = details.get("advance_range")
                if advance_range is not None and advance_range > 0:
                    base_msg = f"Unit {unit_id}{unit_coords} ADVANCED from ({start_col},{start_row}) to ({end_col},{end_row}) [Roll: {advance_range}]"
                else:
                    base_msg = f"Unit {unit_id}{unit_coords} ADVANCED from ({start_col},{start_row}) to ({end_col},{end_row})"
            else:
                raise KeyError("Advance action missing required position data")

            # Add reward if available
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
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name
            weapon_name = details.get("weapon_name")
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            
            if weapon_name:
                base_msg = f"Unit {unit_id}{unit_coords} SHOT at Unit {target_id}{target_coords_str} with [{weapon_name}]"
            else:
                base_msg = f"Unit {unit_id}{unit_coords} SHOT at Unit {target_id}{target_coords_str}"
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
                
                target_coords = details.get("target_coords")
                target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
                base_msg = f"Unit {unit_id}{unit_coords} SHOT at Unit {target_id}{target_coords_str} (Shot {shot_num}/{total_shots})"
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
                target_coords = details.get("target_coords")
                target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
                return f"Unit {unit_id}{unit_coords} SHOT at Unit {target_id}{target_coords_str} (Shot {shot_num}/{total_shots}) - MISS"
                
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
            
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            return f"Unit {unit_id}{unit_coords} SHOOTING COMPLETE at Unit {target_id}{target_coords_str} - {total_shots} shots, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        elif action_type == "charge" and details:
            if "target_id" in details:
                target_id = details["target_id"]
                if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                    start_col, start_row = details["start_pos"]
                    end_col, end_row = details["end_pos"]
                    # Include target coordinates if available
                    target_coords = details.get("target_coords")
                    target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
                    # Include charge roll (2d6) if available
                    charge_roll = details.get("charge_roll")
                    if charge_roll is not None:
                        base_msg = f"Unit {unit_id}{unit_coords} CHARGED Unit {target_id}{target_coords_str} from ({start_col},{start_row}) to ({end_col},{end_row}) [Roll:{charge_roll}]"
                    else:
                        base_msg = f"Unit {unit_id}{unit_coords} CHARGED Unit {target_id}{target_coords_str} from ({start_col},{start_row}) to ({end_col},{end_row})"
                else:
                    base_msg = f"Unit {unit_id}{unit_coords} CHARGED Unit {target_id}"
            else:
                base_msg = f"Unit {unit_id}{unit_coords} CHARGED"

            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

        elif action_type == "charge_fail" and details:
            # Charge failed because roll was too low
            target_id = require_key(details, "target_id")
            charge_roll = details.get("charge_roll")
            charge_failed_reason = require_key(details, "charge_failed_reason")
            
            # Get start and end positions for format: "from (x,y) to (a,b)"
            if "start_pos" in details and details["start_pos"] is not None and "end_pos" in details and details["end_pos"] is not None:
                start_col, start_row = details["start_pos"]
                end_col, end_row = details["end_pos"]
                base_msg = f"Unit {unit_id}{unit_coords} FAILED CHARGE Unit {target_id} from ({start_col},{start_row}) to ({end_col},{end_row})"
            else:
                raise KeyError("Charge_fail action missing required position data")

            # Add reward if available (should be negative penalty)
            reward = details.get("reward")
            if reward is not None:
                base_msg += f" [R:{reward:+.1f}]"

            return base_msg

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
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name
            weapon_name = details.get("weapon_name")
            target_coords = details.get("target_coords")
            target_coords_str = f"({target_coords[0]},{target_coords[1]})" if target_coords else ""
            
            if weapon_name:
                base_msg = f"Unit {unit_id}{unit_coords} ATTACKED Unit {target_id}{target_coords_str} with [{weapon_name}]"
            else:
                base_msg = f"Unit {unit_id}{unit_coords} FOUGHT unit {target_id}{target_coords_str}"
            
            # Apply truncation logic like shooting phase - stop after first failure
            detail_parts = [f"Hit:{hit_target}+:{hit_roll}({hit_result})"]
            
            # Only show wound if hit succeeded
            if hit_result == "HIT":
                detail_parts.append(f"Wound:{wound_target}+:{wound_roll}({wound_result})")
                
                # Only show save if wound succeeded  
                if wound_result == "WOUND":
                    detail_parts.append(f"Save:{save_target}+:{save_roll}({save_result})")
                    
                    # Show damage if save failed (even if damage is 0, it should be logged)
                    if save_result == "FAIL":
                        detail_parts.append(f"Dmg:{damage}HP")
            
            detail_msg = f" - {' '.join(detail_parts)}"

            # Add reward if available
            reward = details.get("reward")
            if reward is not None:
                detail_msg += f" [R:{reward:+.1f}]"

            fight_subphase = require_key(details, "fight_subphase")
            if fight_subphase is None:
                raise ValueError(f"fight_subphase is None in combat log details for unit {unit_id}")
            charging_pool = require_key(details, "charging_activation_pool")
            active_pool = require_key(details, "active_alternating_activation_pool")
            non_active_pool = require_key(details, "non_active_alternating_activation_pool")
            if not isinstance(charging_pool, list):
                raise ValueError(f"charging_activation_pool must be a list in combat log details for unit {unit_id}")
            if not isinstance(active_pool, list):
                raise ValueError(f"active_alternating_activation_pool must be a list in combat log details for unit {unit_id}")
            if not isinstance(non_active_pool, list):
                raise ValueError(f"non_active_alternating_activation_pool must be a list in combat log details for unit {unit_id}")
            charging_pool_str = ",".join(str(uid) for uid in charging_pool)
            active_pool_str = ",".join(str(uid) for uid in active_pool)
            non_active_pool_str = ",".join(str(uid) for uid in non_active_pool)
            detail_msg += (
                f" [FIGHT_SUBPHASE:{fight_subphase}]"
                f" [FIGHT_POOLS:charging={charging_pool_str};active={active_pool_str};non_active={non_active_pool_str}]"
            )

            return base_msg + detail_msg

        elif action_type == "wait":
            return f"Unit {unit_id}{unit_coords} WAIT"

        elif action_type == "skip":
            reason = (details.get("skip_reason") or "").strip()
            if reason:
                return f"Unit {unit_id}{unit_coords} SKIP ({reason})"
            return f"Unit {unit_id}{unit_coords} SKIP"
            
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
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name
                weapon_name = details.get("weapon_name")
                if weapon_name:
                    base_msg = f"Unit {unit_id}{unit_coords} ATTACKED Unit {target_id} with [{weapon_name}] (Attack {attack_num}/{total_attacks})"
                else:
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
                weapon_name = details.get("weapon_name")
                if weapon_name:
                    return f"Unit {unit_id}{unit_coords} ATTACKED Unit {target_id} with [{weapon_name}] (Attack {attack_num}/{total_attacks}) - MISS"
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
            
            return f"Unit {unit_id}{unit_coords} COMBAT COMPLETE at Unit {target_id} - {total_attacks} attacks, {hits} hits, {wounds} wounds, {failed_saves} failed saves, {total_damage} total damage"
            
        else:
            raise ValueError(f"Unknown action_type '{action_type}'")
    
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
    
    def log_episode_end(self, total_episodes_steps, winner, win_method, objective_control):
        """Log episode completion summary using replay-style format

        Args:
            total_episodes_steps: Total steps across all episodes
            winner: 0, 1, or -1 (draw)
            win_method: "elimination", "objectives", "value_tiebreaker", or "draw"
            objective_control: Dict of objective_id -> control data (OC totals + controller)
        """
        if not self.enabled:
            return

        # PERFORMANCE: Flush any remaining buffered logs before episode end
        self._flush_buffer()

        try:
            duration_s = time.perf_counter() - getattr(self, '_episode_start_wall', time.perf_counter())
            with open(self.output_file, 'a') as f:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                method_str = f", Method={win_method}" if win_method else ""
                f.write(f"[{timestamp}] EPISODE END: Winner={winner}{method_str}, Actions={self.episode_action_count}, Steps={self.episode_step_count}, Total={total_episodes_steps}, Duration={duration_s:.3f}s\n")
                if objective_control:
                    objective_entries = []
                    for obj_id, data in objective_control.items():
                        player_1_oc = require_key(data, "player_1_oc")
                        player_2_oc = require_key(data, "player_2_oc")
                        controller = require_key(data, "controller")
                        objective_entries.append(
                            f"Obj{obj_id}:P1_OC={player_1_oc},P2_OC={player_2_oc},Ctrl={controller}"
                        )
                    f.write(f"[{timestamp}] OBJECTIVE CONTROL: {' | '.join(objective_entries)}\n")
                f.write("=" * 80 + "\n")
        except Exception as e:
            print(f"⚠️ Step logging error: {e}")
    
    def __del__(self):
        """Ensure buffer is flushed when logger is destroyed"""
        try:
            if hasattr(self, 'log_buffer') and self.log_buffer:
                self._flush_buffer()
        except (NameError, AttributeError):
            # Ignore errors during interpreter shutdown (open may not be available)
            pass


