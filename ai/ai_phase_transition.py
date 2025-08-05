# ai/ai_phase_transition.py
#!/usr/bin/env python3
"""
Phase Transition Manager for AI Training
Mirrors frontend usePhaseTransition.ts logic for consistent turn/phase management
"""

from typing import Dict, List, Set, Any, Optional
from dataclasses import dataclass

@dataclass
class PhaseState:
    """Track phase transition state."""
    current_phase: str
    current_player: int
    current_turn: int
    moved_units: Set[int]
    shot_units: Set[int]
    charged_units: Set[int]
    attacked_units: Set[int]
    game_over: bool
    winner: Optional[int]

class PhaseTransitionManager:
    """
    Unified phase transition management following frontend usePhaseTransition.ts logic.
    Handles turn progression, phase advancement, and state reset for AI training.
    """
    
    def __init__(self, env):
        """Initialize with W40K environment reference."""
        self.env = env
        self.phase_order = env.phase_order
        self.quiet = getattr(env, 'quiet', False)
    
    def advance_phase(self):
        """
        Advance phase with proper turn increment logic.
        Mirrors frontend usePhaseTransition.ts behavior.
        """
        # Apply any phase-specific penalties before advancing
        self._apply_phase_penalties()
        
        current_phase_idx = self.phase_order.index(self.env.current_phase)
        
        if current_phase_idx < len(self.phase_order) - 1:
            # Move to next phase within same player's turn
            self.env.current_phase = self.phase_order[current_phase_idx + 1]
            self._log_phase_change()
        else:
            # End of all phases - handle player/turn transition
            self._handle_turn_transition()
        
        # Clear phase tracking for new phase
        self.env.phase_acted_units.clear()
    
    def _handle_turn_transition(self):
        """Handle end of phase cycle - switch players and potentially increment turn."""
        self.env.current_phase = self.phase_order[0]  # Reset to move phase
        old_player = self.env.current_player
        self.env.current_player = 1 - self.env.current_player
        
        # DEBUG: Force logging of player transitions
        if not self.quiet:
            print(f"🔄 Player transition: {old_player} -> {self.env.current_player}")
        
        # CRITICAL FIX: Turn increment when Player 1 starts move phase
        if self.env.current_player == 1 and self.env.current_phase == "move":
            # Player 1 starting move phase = new turn begins
            old_turn = self.env.current_turn
            self.env.current_turn += 1
            if not self.quiet:
                print(f"🔄 TURN INCREMENT: {old_turn} -> {self.env.current_turn}")
            self._reset_turn_state()
            self._log_turn_start()  # Log AFTER turn increment, while current_player is still 1
            
        elif self.env.current_player == 0:
            # Player 0 (enemy) starting their turn - execute enemy AI
            if not self.quiet:
                print(f"🤖 Enemy turn starting (turn {self.env.current_turn})")
            self._execute_enemy_turn()
        
        self._log_phase_change()
    
    def _reset_turn_state(self):
        """Reset all turn-based state when new turn begins."""
        # Clear tracking sets
        self.env.moved_units.clear()
        self.env.shot_units.clear()
        self.env.charged_units.clear()
        self.env.attacked_units.clear()
        
        # Reset unit flags for all units
        for unit in self.env.unit_manager.get_alive_units():
            unit["has_moved"] = False
            unit["has_shot"] = False
            unit["has_charged"] = False
            unit["has_attacked"] = False
    
    def _execute_enemy_turn(self):
        """Execute enemy AI turn - delegate to environment's enemy AI."""
        if hasattr(self.env, '_execute_enemy_turn'):
            if not self.quiet:
                print(f"🤖 PhaseTransitionManager executing enemy turn for turn {self.env.current_turn}")
            actions_taken = self.env._execute_enemy_turn()
            if not self.quiet:
                print(f"🤖 PhaseTransitionManager: Enemy turn completed with {actions_taken} actions")
        else:
            if not self.quiet:
                print(f"❌ PhaseTransitionManager: No _execute_enemy_turn method found")
    
    def _apply_phase_penalties(self):
        """Apply penalties for units that couldn't act in their optimal phase."""
        ai_units_alive = self.env.unit_manager.get_alive_ai_units()
        
        if self.env.current_phase == "shoot":
            # Penalty for ranged units that couldn't shoot
            for unit in ai_units_alive:
                if "is_ranged" not in unit:
                    raise KeyError("Unit missing required 'is_ranged' field")
                if (unit["is_ranged"] and 
                    unit["id"] not in self.env.shot_units and
                    not self.env._has_enemies_in_shooting_range(unit)):
                    
                    unit_rewards = self.env._get_unit_reward_config(unit)
                    if "situational_modifiers" not in unit_rewards or "no_targets_penalty" not in unit_rewards["situational_modifiers"]:
                        raise KeyError(f"Missing 'situational_modifiers.no_targets_penalty' in rewards config for unit type {unit['unit_type']}")
                    penalty = unit_rewards["situational_modifiers"]["no_targets_penalty"]
                    
                    # Record penalty action for replay
                    if self.env.save_replay:
                        self.env._record_penalty_action(unit, "no_shooting_targets", penalty)
        
        elif self.env.current_phase == "combat":
            # Penalty for melee units that couldn't fight
            for unit in ai_units_alive:
                if "is_ranged" not in unit:
                    raise KeyError("Unit missing required 'is_ranged' field")
                if (not unit["is_ranged"] and 
                    unit["id"] not in self.env.attacked_units and
                    not self.env._has_adjacent_enemies(unit)):
                    
                    unit_rewards = self.env._get_unit_reward_config(unit)
                    if "situational_modifiers" not in unit_rewards or "no_targets_penalty" not in unit_rewards["situational_modifiers"]:
                        raise KeyError(f"Missing 'situational_modifiers.no_targets_penalty' in rewards config for unit type {unit['unit_type']}")
                    penalty = unit_rewards["situational_modifiers"]["no_targets_penalty"]
                    
                    # Record penalty action for replay
                    if self.env.save_replay:
                        self.env._record_penalty_action(unit, "no_combat_targets", penalty)
    
    def _log_turn_start(self):
        """Log turn start for debugging and replay consistency."""
        if not self.quiet:
            print(f"🔄 Turn {self.env.current_turn} begins - AI player starts")
        
        # CRITICAL: Don't log turn start here - it causes wrong player attribution
        # Turn start will be logged by the first AI action in the turn
        pass
        
        # CRITICAL: Force replay logger synchronization to prevent turn jumps
        if hasattr(self.env, 'replay_logger') and self.env.replay_logger:
            # Ensure replay logger matches environment turn
            if hasattr(self.env.replay_logger, 'current_turn'):
                old_replay_turn = getattr(self.env.replay_logger, 'current_turn', 0)
                self.env.replay_logger.current_turn = self.env.current_turn
                if not self.quiet and old_replay_turn != self.env.current_turn:
                    print(f"🔄 Replay logger turn sync: {old_replay_turn} -> {self.env.current_turn}")
            
            # Force absolute turn tracking to prevent jumps
            if hasattr(self.env.replay_logger, 'absolute_turn'):
                self.env.replay_logger.absolute_turn = self.env.current_turn
    
    def _log_phase_change(self):
        """Log phase changes for debugging."""
        if not self.quiet:
            player_name = "AI" if self.env.current_player == 1 else "Enemy"
            print(f"📋 {player_name} - {self.env.current_phase.upper()} phase")