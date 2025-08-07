#!/usr/bin/env python3
"""
use_phase_transition.py
EXACT Python mirror of frontend/src/hooks/usePhaseTransition.ts
Automatic phase advancement system - ALL features preserved.

This is the complete functional equivalent of the PvP usePhaseTransition hook system.
"""

from typing import Dict, List, Any, Optional, Callable, Set
import time
import copy
from shared.gameMechanics import (
    is_unit_eligible,
    should_transition_from_move,
    should_transition_from_shoot, 
    should_transition_from_charge,
    should_transition_from_charged_units_phase,
    should_end_alternating_combat,
    should_end_turn,
    ensure_charged_this_turn_defaults
)

class UsePhaseTransition:
    """
    EXACT Python mirror of usePhaseTransition TypeScript hook.
    Automatic phase advancement system with ALL features preserved.
    """
    
    def __init__(self, game_state: Dict[str, Any], 
                 board_config: Dict[str, Any],
                 is_unit_eligible_func: Callable,
                 actions: Dict[str, Callable],
                 quiet: bool = False):
        """Initialize with same parameters as TypeScript usePhaseTransition"""
        # CRITICAL DEBUG: Validate required fields and track initialization state
        if 'phase' not in game_state:
            raise KeyError("game_state missing required 'phase' field")
        if 'current_player' not in game_state:
            raise KeyError("game_state missing required 'current_player' field")
        if 'units_moved' not in game_state:
            raise KeyError("game_state missing required 'units_moved' field")
            
        if not quiet:
            print(f"🔧 UsePhaseTransition initialized: phase={game_state['phase']}, player={game_state['current_player']}")
        else:
            raise KeyError("actions missing required 'set_phase' function")
        
        self.game_state = game_state
        self.board_config = board_config
        self.is_unit_eligible_func = is_unit_eligible_func
        self.actions = actions
        self.quiet = quiet
        
        # Extract state for convenience (EXACT from TypeScript)
        self.units = game_state["units"]
        self.current_player = game_state["current_player"]
        self.phase = game_state["phase"]
        self.units_moved = set(game_state.get("units_moved", []))
        self.units_charged = set(game_state.get("units_charged", []))
        self.units_attacked = set(game_state.get("units_attacked", []))
        self.units_fled = set(game_state.get("units_fled", []))
        self.combat_sub_phase = game_state.get("combat_sub_phase")
        self.combat_active_player = game_state.get("combat_active_player")

    # === HELPER METHODS (EXACT from TypeScript) ===

    def get_current_player_units(self) -> List[Dict[str, Any]]:
        """EXACT mirror of getCurrentPlayerUnits from TypeScript"""
        return [u for u in self.units if u["player"] == self.current_player]

    def get_enemy_units(self) -> List[Dict[str, Any]]:
        """EXACT mirror of getEnemyUnits from TypeScript"""
        return [u for u in self.units if u["player"] != self.current_player]

    # === PHASE TRANSITION CHECKS (EXACT from TypeScript) ===

    def should_transition_from_move(self) -> bool:
        """EXACT mirror of shouldTransitionFromMove from TypeScript"""
        return should_transition_from_move(self.units, self.current_player, self.units_moved)

    def should_transition_from_shoot(self) -> bool:
        """EXACT mirror of shouldTransitionFromShoot from TypeScript"""
        result = should_transition_from_shoot(
            self.units, self.current_player, self.phase, 
            self.units_moved, self.units_charged, self.units_attacked, self.units_fled
        )
        # DEBUG: Uncomment for phase transition debugging
        # print(f"🔧 should_transition_from_shoot: result={result}, phase={self.phase}, player={self.current_player}")
        # print(f"🔧   units_moved={list(self.units_moved)}, units_charged={list(self.units_charged)}")
        # print(f"🔧   units_attacked={list(self.units_attacked)}, units_fled={list(self.units_fled)}")
        # current_player_units = [u for u in self.units if u["player"] == self.current_player]
        # print(f"🔧   current_player_units: {[(u['id'], u.get('SHOOT_LEFT', 'N/A')) for u in current_player_units]}")
        return result

    def should_transition_from_charge(self) -> bool:
        """EXACT mirror of shouldTransitionFromCharge from TypeScript"""
        return should_transition_from_charge(
            self.units, self.current_player, self.phase,
            self.units_moved, self.units_charged, self.units_attacked, self.units_fled
        )

    def should_end_turn(self) -> bool:
        """EXACT mirror of shouldEndTurn from TypeScript"""
        return should_end_turn(self.units)

    def should_transition_from_charged_units_phase(self) -> bool:
        """EXACT mirror of shouldTransitionFromChargedUnitsPhase from TypeScript"""
        return should_transition_from_charged_units_phase(
            self.units, self.current_player, self.phase, self.combat_sub_phase,
            self.units_moved, self.units_charged, self.units_attacked, self.units_fled
        )

    def should_end_alternating_combat(self) -> bool:
        """EXACT mirror of shouldEndAlternatingCombat from TypeScript"""
        return should_end_alternating_combat(
            self.units, self.phase, self.combat_sub_phase,
            self.units_moved, self.units_charged, self.units_attacked, self.units_fled
        )

    # === PHASE TRANSITION ACTIONS (EXACT from TypeScript) ===

    def transition_to_shoot(self) -> None:
        """
        EXACT mirror of transitionToShoot from TypeScript.
        Transition from move to shoot phase with delay.
        """
        def delayed_transition():
            """Mirror setTimeout behavior from TypeScript"""
            # DEBUG: Uncomment for phase transition debugging
            # print(f"🔧 BEFORE set_phase: calling set_phase('shoot')")
            
            # CRITICAL FIX: Use the SAME game_state object that set_phase modifies
            set_phase_func = self.actions['set_phase']
            correct_game_state = set_phase_func.__self__.game_state
            # print(f"🔧 Switching to correct game_state object: {id(correct_game_state)}")
            
            # Update self.game_state to point to the correct object
            self.game_state = correct_game_state
            # print(f"🔧 Updated UsePhaseTransition.game_state to correct object")
            
            self.actions["set_phase"]("shoot")
            
            # DEBUG: Uncomment for phase transition debugging
            # print(f"🔧 AFTER set_phase call:")
            # print(f"🔧   UsePhaseTransition.game_state['phase']: {self.game_state.get('phase', 'unknown')}")
            # print(f"🔧   set_phase.__self__.game_state['phase']: {set_phase_func.__self__.game_state.get('phase', 'unknown')}")
            # print(f"🔧   Are they the same object? {id(self.game_state) == id(set_phase_func.__self__.game_state)}")
            
            self.actions["initialize_shooting_phase"]()  # MISSING FEATURE ADDED
            self.actions["reset_moved_units"]()
            self.actions["set_selected_unit_id"](None)
            
            # CRITICAL FIX: Add all current player units to units_moved for shoot phase tracking
            current_player_units = [u for u in self.game_state["units"] if u["player"] == self.game_state["current_player"]]
            for unit in current_player_units:
                if unit.get("RNG_RNG", 0) > 0:  # Only ranged units need to be tracked for shooting
                    self.actions["add_moved_unit"](unit["id"])
                    # print(f"🔧 Added ranged unit {unit['id']} to units_moved for shoot phase")
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            # print(f"🔧 transition_to_shoot: phase updated to {self.phase}")
        
        # Execute with 300ms delay equivalent (can be immediate in training)
        delayed_transition()

    def transition_to_charge(self) -> None:
        """
        EXACT mirror of transitionToCharge from TypeScript.
        Transition from shoot to charge phase with delay.
        """
        def delayed_transition():
            """Mirror setTimeout behavior from TypeScript"""
            self.actions["set_phase"]("charge")
            self.actions["reset_moved_units"]()  # Reset unitsMoved when entering charge phase
            self.actions["reset_charged_units"]()
            self.actions["set_selected_unit_id"](None)
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            # DEBUG: Uncomment for phase transition debugging
            # print(f"🔧 transition_to_charge: phase updated to {self.phase}")
        
        # Execute with 300ms delay equivalent
        delayed_transition()

    def transition_to_combat(self) -> None:
        """
        EXACT mirror of transitionToCombat from TypeScript.
        Transition from charge to combat phase with delay.
        """
        def delayed_transition():
            """Mirror setTimeout behavior from TypeScript"""
            # CRITICAL FIX: Use the SAME game_state object that set_phase modifies
            set_phase_func = self.actions['set_phase']
            correct_game_state = set_phase_func.__self__.game_state
            self.game_state = correct_game_state
            
            self.actions["set_phase"]("combat")
            self.actions["initialize_combat_phase"]()
            self.actions["set_selected_unit_id"](None)
            self.actions["reset_attacked_units"]()
            self.actions["set_mode"]("select")
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            # DEBUG: Uncomment for phase transition debugging
            # print(f"🔧 transition_to_combat: phase updated to {self.phase}")
        
        # Execute with 300ms delay equivalent
        delayed_transition()

    def end_turn(self) -> None:
        """
        EXACT mirror of endTurn from TypeScript.
        End current turn and switch to next player or new turn.
        """
        def delayed_end_turn():
            """Delayed execution to mirror setTimeout(300) behavior"""
            # CRITICAL FIX: Use the SAME game_state object that set_phase modifies
            set_phase_func = self.actions['set_phase']
            correct_game_state = set_phase_func.__self__.game_state
            self.game_state = correct_game_state
            
            # Switch player (EXACT from TypeScript)
            new_player = 1 if self.current_player == 0 else 0
            self.actions["set_current_player"](new_player)
            
            # Increment turn when player 0 starts their turn (EXACT from TypeScript)
            if new_player == 0:
                self.actions["set_current_turn"](self.game_state["current_turn"] + 1)
            
            self.actions["set_phase"]("move")
            self.actions["reset_moved_units"]()
            self.actions["reset_charged_units"]()
            self.actions["reset_attacked_units"]()
            self.actions["reset_fled_units"]()
            
            # Reset hasChargedThisTurn for all units (EXACT from TypeScript)
            updated_units = []
            for unit in self.game_state["units"]:
                updated_unit = copy.deepcopy(unit)
                updated_unit["has_charged_this_turn"] = False
                updated_units.append(updated_unit)
            self.actions["set_units"](updated_units)
            
            self.actions["set_selected_unit_id"](None)
            
            # Reset combat sub-phase for next turn (EXACT from TypeScript)
            self.actions["set_combat_sub_phase"](None)
            self.actions["set_combat_active_player"](None)
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            self.current_player = self.game_state["current_player"]
            print(f"🔧 end_turn: phase={self.phase}, player={self.current_player}")
        
        # Execute with delay to mirror setTimeout (can be immediate in training)
        delayed_end_turn()

    def ensure_charged_this_turn_defaults(self) -> None:
        """
        EXACT mirror of ensureChargedThisTurnDefaults from TypeScript.
        Ensure all units have hasChargedThisTurn property set.
        """
        units_needing_defaults = any(
            unit.get("has_charged_this_turn") is None for unit in self.units
        )
        
        if units_needing_defaults:
            updated_units = []
            for unit in self.units:
                updated_unit = copy.deepcopy(unit)
                if updated_unit.get("has_charged_this_turn") is None:
                    updated_unit["has_charged_this_turn"] = False
                updated_units.append(updated_unit)
            self.actions["set_units"](updated_units)

    # === MAIN PHASE TRANSITION LOGIC (EXACT from TypeScript) ===

    def process_phase_transitions(self) -> None:
        """
        EXACT mirror of the main useEffect logic from TypeScript.
        Process all phase transitions based on current game state.
        """
        # CRITICAL FIX: ALWAYS get the freshest game_state reference from multiple sources
        fresh_game_state = None
        
        # Try multiple sources to find the current active game_state
        if 'set_phase' in self.actions:
            try:
                candidate_state = self.actions['set_phase'].__self__.game_state
                if candidate_state and isinstance(candidate_state, dict):
                    fresh_game_state = candidate_state
            except (AttributeError, TypeError):
                pass
        
        if 'add_moved_unit' in self.actions and not fresh_game_state:
            try:
                candidate_state = self.actions['add_moved_unit'].__self__.game_state
                if candidate_state and isinstance(candidate_state, dict):
                    fresh_game_state = candidate_state
            except (AttributeError, TypeError):
                pass
        
        # CRITICAL DEBUG: Show ALL object IDs before sync
        print(f"🔧 PRE-SYNC DEBUG:")
        print(f"    UsePhaseTransition.game_state ID: {id(self.game_state)}")
        print(f"    Fresh candidate game_state ID: {id(fresh_game_state) if fresh_game_state else 'None'}")
        if fresh_game_state:
            print(f"    Current phase: {self.game_state.get('phase', 'missing')}")
            print(f"    Fresh phase: {fresh_game_state.get('phase', 'missing')}")
        
        # Force update to freshest available state
        if fresh_game_state and id(fresh_game_state) != id(self.game_state):
            # Validate required fields exist in both states - NO DEFAULTS
            if 'phase' not in self.game_state:
                raise KeyError("Current game_state missing required 'phase' field")
            if 'phase' not in fresh_game_state:
                raise KeyError("Fresh game_state missing required 'phase' field")
            
            print(f"🔧 STATE SYNC: Forced update from stale {id(self.game_state)} to fresh {id(fresh_game_state)}")
            print(f"🔧   Old phase: {self.game_state['phase']}, New phase: {fresh_game_state['phase']}")
            self.game_state = fresh_game_state
            print(f"🔧 SYNC COMPLETE: UsePhaseTransition now uses game_state {id(self.game_state)}")
        elif fresh_game_state:
            print(f"🔧 STATE CONSISTENT: Using same game_state {id(self.game_state)}")
        else:
            raise RuntimeError("Could not find fresh game_state reference from any action source")
        
        # Validate final state has required fields
        if 'phase' not in self.game_state:
            raise KeyError("Final game_state missing required 'phase' field")
        if 'current_player' not in self.game_state:
            raise KeyError("Final game_state missing required 'current_player' field")
            
        # CRITICAL DEBUG: Capture atomic phase readings to detect race conditions
        phase_reading_1 = self.game_state["phase"]
        player_reading_1 = self.game_state["current_player"] 
        state_id = id(self.game_state)
        
        print(f"🔧 ATOMIC DEBUG: game_state[{state_id}] phase={phase_reading_1}, player={player_reading_1}")
        
        # Re-read immediately to detect changes
        phase_reading_2 = self.game_state["phase"]
        player_reading_2 = self.game_state["current_player"]
        
        if phase_reading_1 != phase_reading_2:
            print(f"🚨 RACE CONDITION DETECTED: phase changed from {phase_reading_1} to {phase_reading_2} during same method!")
        if player_reading_1 != player_reading_2:
            print(f"🚨 RACE CONDITION DETECTED: player changed from {player_reading_1} to {player_reading_2} during same method!")
        
        print(f"🔧 process_phase_transitions: phase={phase_reading_2}, player={player_reading_2}")
        
        # Update local state references from synchronized game_state
        self.units = self.game_state["units"]
        self.current_player = self.game_state["current_player"]
        self.phase = self.game_state["phase"]
        self.units_moved = set(self.game_state.get("units_moved", []))
        self.units_charged = set(self.game_state.get("units_charged", []))
        self.units_attacked = set(self.game_state.get("units_attacked", []))
        self.units_fled = set(self.game_state.get("units_fled", []))
        self.combat_sub_phase = self.game_state.get("combat_sub_phase")
        self.combat_active_player = self.game_state.get("combat_active_player")

        # CRITICAL DEBUG: Verify final cached values match dictionary values
        dict_phase = self.game_state["phase"]
        dict_player = self.game_state["current_player"]
        if self.phase != dict_phase:
            print(f"🚨 CACHE MISMATCH: self.phase={self.phase} != game_state['phase']={dict_phase}")
        if self.current_player != dict_player:
            print(f"🚨 CACHE MISMATCH: self.current_player={self.current_player} != game_state['current_player']={dict_player}")

        print(f"🔧 Synced state: phase={self.phase}, player={self.current_player}, units_moved={list(self.units_moved)}")

        # Main phase transition logic (EXACT from TypeScript)
        if self.phase == "move":
            print(f"🔧 In move phase, checking should_transition_from_move()")
            if self.should_transition_from_move():
                print(f"🔧 should_transition_from_move returned True - transitioning to shoot")
                self.transition_to_shoot()
            else:
                print(f"🔧 should_transition_from_move returned False - no transition")
                
        elif self.phase == "shoot":
            if self.should_transition_from_shoot():
                self.transition_to_charge()
                
        elif self.phase == "charge":
            if self.should_transition_from_charge():
                self.transition_to_combat()
                
        elif self.phase == "combat":
            # CRITICAL DEBUG: Track combat phase progression
            if not hasattr(self, '_combat_debug_count'):
                self._combat_debug_count = 0
            if self._combat_debug_count < 5:
                print(f"🔍 COMBAT DEBUG #{self._combat_debug_count + 1}: combat_sub_phase={self.combat_sub_phase}")
                print(f"    should_transition_from_charged_units={self.should_transition_from_charged_units_phase() if self.combat_sub_phase == 'charged_units' else 'N/A'}")
                print(f"    should_end_alternating_combat={self.should_end_alternating_combat() if self.combat_sub_phase == 'alternating_combat' else 'N/A'}")
                self._combat_debug_count += 1
            
            # Handle combat sub-phase transitions (EXACT from TypeScript)
            if (self.combat_sub_phase == "charged_units" and 
                self.should_transition_from_charged_units_phase()):
                print(f"🔍 COMBAT TRANSITION: charged_units -> alternating_combat")
                # Transition from charged units phase to alternating combat
                next_combat_player = 1 if self.current_player == 0 else 0
                
                # Batch all state updates together (EXACT from TypeScript)
                self.actions["set_combat_sub_phase"]("alternating_combat")
                self.actions["set_combat_active_player"](next_combat_player)
                self.actions["set_selected_unit_id"](None)
                
                # Force immediate state propagation (Python equivalent of setTimeout(100))
                def force_state_update():
                    self.actions["set_selected_unit_id"](None)
                    self.actions["set_mode"]("select")
                force_state_update()
                
            elif (self.combat_sub_phase == "alternating_combat" and 
                  self.should_end_alternating_combat()):
                print(f"🔍 COMBAT TRANSITION: alternating_combat -> end_turn")
                # End combat phase entirely
                self.end_turn()
                
            elif not self.combat_sub_phase:
                # Initialize combat phase with charged units sub-phase
                self.ensure_charged_this_turn_defaults()
                self.actions["set_combat_sub_phase"]("charged_units")
                self.actions["set_selected_unit_id"](None)

    def process_alternating_combat_player_switch(self) -> None:
        """
        EXACT mirror of alternating player switching logic from TypeScript.
        Handle player switching in alternating combat phase.
        """
        if (self.phase == "combat" and 
            self.combat_sub_phase == "alternating_combat" and 
            self.combat_active_player is not None):
            
            # Only check for player switching when unitsAttacked changes (EXACT from TypeScript)
            current_combat_player_units = [
                u for u in self.units if u["player"] == self.combat_active_player
            ]
            
            # Use the authoritative isUnitEligible function (EXACT from TypeScript)
            has_eligible_units = any(
                self.is_unit_eligible_func(unit) for unit in current_combat_player_units
            )
            
            if not has_eligible_units:
                # Switch to other player immediately (EXACT from TypeScript)
                other_player = 1 if self.combat_active_player == 0 else 0
                self.actions["set_combat_active_player"](other_player)
                self.actions["set_selected_unit_id"](None)

    # === TRAINING INTEGRATION METHODS ===

    def auto_advance_phases(self) -> bool:
        """
        Automatically advance phases until player input is needed.
        Returns True if any phase transitions occurred.
        """
        initial_phase = self.phase
        initial_player = self.current_player
        
        # Process transitions
        self.process_phase_transitions()
        self.process_alternating_combat_player_switch()
        
        # Update state after potential changes
        final_phase = self.game_state.get("phase", self.phase)
        final_player = self.game_state.get("current_player", self.current_player)
        
        # Return True if state changed
        return initial_phase != final_phase or initial_player != final_player

    def force_phase_advance(self, target_phase: str) -> None:
        """Force advance to specific phase (for training scenarios)"""
        phase_order = ["move", "shoot", "charge", "combat"]
        current_idx = phase_order.index(self.phase)
        target_idx = phase_order.index(target_phase)
        
        while current_idx < target_idx:
            if self.phase == "move":
                self.transition_to_shoot()
            elif self.phase == "shoot":
                self.transition_to_charge()
            elif self.phase == "charge":
                self.transition_to_combat()
            current_idx += 1
            self.phase = self.game_state["phase"]

    def get_phase_info(self) -> Dict[str, Any]:
        """Get complete phase information for training analysis"""
        return {
            "phase": self.phase,
            "current_player": self.current_player,
            "combat_sub_phase": self.combat_sub_phase,
            "combat_active_player": self.combat_active_player,
            "can_transition": {
                "from_move": self.should_transition_from_move(),
                "from_shoot": self.should_transition_from_shoot(),
                "from_charge": self.should_transition_from_charge(),
                "from_charged_units": self.should_transition_from_charged_units_phase(),
                "end_alternating_combat": self.should_end_alternating_combat(),
                "end_turn": self.should_end_turn(),
            },
            "units_status": {
                "moved": list(self.units_moved),
                "charged": list(self.units_charged),
                "attacked": list(self.units_attacked),
                "fled": list(self.units_fled),
            }
        }

    # === EXPOSED TRANSITION FUNCTIONS (EXACT from TypeScript return) ===

    def get_transition_functions(self) -> Dict[str, Callable]:
        """
        Return all transition functions (mirror of TypeScript usePhaseTransition return).
        This replaces the TypeScript hook's return statement.
        """
        return {
            # Transition functions for manual control
            "transition_to_shoot": self.transition_to_shoot,
            "transition_to_charge": self.transition_to_charge,
            "transition_to_combat": self.transition_to_combat,
            "end_turn": self.end_turn,
            
            # Check functions for external use
            "should_transition_from_move": self.should_transition_from_move,
            "should_transition_from_shoot": self.should_transition_from_shoot,
            "should_transition_from_charge": self.should_transition_from_charge,
            "should_end_turn": self.should_end_turn,
            
            # Process functions
            "process_phase_transitions": self.process_phase_transitions,
            "process_alternating_combat_player_switch": self.process_alternating_combat_player_switch,
            
            # Training-specific functions
            "auto_advance_phases": self.auto_advance_phases,
            "force_phase_advance": self.force_phase_advance,
            "get_phase_info": self.get_phase_info,
        }


# === FACTORY FUNCTION (Mirror of TypeScript hook usage) ===

def use_phase_transition(game_state: Dict[str, Any], 
                        board_config: Dict[str, Any],
                        is_unit_eligible_func: Callable,
                        actions: Dict[str, Callable]) -> Dict[str, Callable]:
    """
    Factory function that mirrors the TypeScript usePhaseTransition hook.
    Returns the same transition functions that the TypeScript hook returns.
    """
    phase_transition_manager = UsePhaseTransition(
        game_state, 
        board_config, 
        is_unit_eligible_func,
        actions
    )
    
    return phase_transition_manager.get_transition_functions()


# === TRAINING INTEGRATION CLASS ===

class TrainingPhaseTransition(UsePhaseTransition):
    """
    Extended version of UsePhaseTransition optimized for AI training.
    Adds performance optimizations and training-specific methods.
    """
    
    def __init__(self, game_state: Dict[str, Any], 
                 board_config: Dict[str, Any],
                 is_unit_eligible_func: Callable,
                 actions: Dict[str, Callable]):
        super().__init__(game_state, board_config, is_unit_eligible_func, actions)
        self.transition_history = []  # Track phase transitions for analysis
        
    def log_transition(self, from_phase: str, to_phase: str, details: Dict[str, Any]) -> None:
        """Log phase transitions for training analysis"""
        self.transition_history.append({
            "timestamp": time.time(),
            "from_phase": from_phase,
            "to_phase": to_phase,
            "current_player": self.current_player,
            "turn": self.game_state.get("current_turn", 1),
            "details": details
        })
    
    def get_transition_history(self) -> List[Dict[str, Any]]:
        """Get complete transition history for training analysis"""
        return copy.deepcopy(self.transition_history)
    
    def reset_for_new_episode(self) -> None:
        """Reset transition tracking for new training episode"""
        self.transition_history = []
    
    def get_training_metrics(self) -> Dict[str, Any]:
        """Get training-relevant metrics about phase transitions"""
        if not self.transition_history:
            return {"total_transitions": 0, "phases_per_turn": 0}
        
        total_transitions = len(self.transition_history)
        total_turns = max(1, self.game_state.get("current_turn", 1))
        
        return {
            "total_transitions": total_transitions,
            "phases_per_turn": total_transitions / total_turns,
            "current_phase": self.phase,
            "current_player": self.current_player,
            "combat_sub_phase": self.combat_sub_phase,
        }

    # Override transition methods to add logging
    def transition_to_shoot(self) -> None:
        self.log_transition("move", "shoot", {"player": self.current_player})
        super().transition_to_shoot()
    
    def transition_to_charge(self) -> None:
        self.log_transition("shoot", "charge", {"player": self.current_player})
        super().transition_to_charge()
    
    def transition_to_combat(self) -> None:
        self.log_transition("charge", "combat", {"player": self.current_player})
        super().transition_to_combat()
    
    def end_turn(self) -> None:
        new_player = 1 if self.current_player == 0 else 0
        self.log_transition("combat", "move", {
            "old_player": self.current_player,
            "new_player": new_player,
            "turn_ended": True
        })
        super().end_turn()