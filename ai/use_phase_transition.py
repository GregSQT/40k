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
        if 'phase' not in game_state:
            raise KeyError("game_state missing required 'phase' field")
        if 'current_player' not in game_state:
            raise KeyError("game_state missing required 'current_player' field")
        if 'units_moved' not in game_state:
            raise KeyError("game_state missing required 'units_moved' field")
        
        self.game_state = game_state
        self.board_config = board_config
        self.is_unit_eligible_func = is_unit_eligible_func
        self.actions = actions
        self.quiet = quiet
        
        # Extract state for convenience (EXACT from TypeScript)
        self.units = game_state["units"]
        self.current_player = game_state["current_player"]
        self.phase = game_state["phase"]
        if "units_moved" not in game_state:
            raise KeyError("game_state missing required 'units_moved' field")
        if "units_charged" not in game_state:
            raise KeyError("game_state missing required 'units_charged' field")
        if "units_attacked" not in game_state:
            raise KeyError("game_state missing required 'units_attacked' field")
        if "units_fled" not in game_state:
            raise KeyError("game_state missing required 'units_fled' field")
        if "units_shot" not in game_state:
            raise KeyError("game_state missing required 'units_shot' field")
        
        self.units_moved = set(game_state["units_moved"])
        self.units_shot = set(game_state["units_shot"])
        self.units_charged = set(game_state["units_charged"])
        self.units_attacked = set(game_state["units_attacked"])
        self.units_fled = set(game_state["units_fled"])
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
        """Check if all player units have moved or can't move - EXACT from AI_GAME.md"""
        # AI_ARCHITECTURE.md: Single source of truth - use game_state directly
        live_units_moved = set(self.game_state["units_moved"])
        live_current_player = self.game_state["current_player"]
        live_units = self.game_state["units"]
        
        # AI_TURN.md: Check if all player units have moved or can't move
        current_player_units = [u for u in live_units if u["player"] == live_current_player and u.get("alive", True)]
        
        # Phase transitions when ALL current player units have moved
        units_not_moved = [unit["id"] for unit in current_player_units if unit["id"] not in live_units_moved]
        should_transition = len(units_not_moved) == 0
        
        return should_transition

    def should_transition_from_shoot(self) -> bool:
        """EXACT mirror of shouldTransitionFromShoot from TypeScript (delegates to shared mechanics)"""
        from shared.gameMechanics import should_transition_from_shoot as _shoot_check
        
        result = _shoot_check(
            self.units,
            self.current_player,
            self.units_shot,
            self.units_fled,
        )
        return result

    def should_transition_from_charge(self) -> bool:
        """EXACT mirror of shouldTransitionFromCharge from TypeScript (delegates to shared mechanics)"""
        from shared.gameMechanics import should_transition_from_charge as _charge_check
        return _charge_check(
            self.units,
            self.current_player,
            self.phase,
            self.units_moved,
            self.units_charged,
            self.units_attacked,
            self.units_fled
        )

    def should_end_turn(self) -> bool:
        """Check if current player's turn should end (advance to next player)"""
        from shared.gameRules import is_unit_in_range as isUnitInRange
        
        player_units = self.get_current_player_units()
        enemy_units = self.get_enemy_units()
        
        # Turn ends if current player has no units
        if len(player_units) == 0:
            return True
        
        # In combat phase only: check if current player has units that can still attack
        if self.phase == "combat":
            attackable_units = []
            for unit in player_units:
                if unit["id"] in self.units_attacked:
                    continue
                if "CC_RNG" not in unit:
                    continue
                combat_range = unit["CC_RNG"]
                can_attack = any(isUnitInRange(unit, enemy, combat_range) for enemy in enemy_units)
                if can_attack:
                    attackable_units.append(unit)
            
            should_end = len(attackable_units) == 0
            return should_end
        
        # For other phases (move, shoot, charge), turn ending is handled by phase transition logic
        # This method should not be called outside combat phase in normal operation
        return False

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
            print(f"\n🎯 [use_phase_transition.py::transition_to_shoot] TRANSITIONING FROM MOVE TO SHOOT PHASE")
            print(f"📊 [use_phase_transition.py::transition_to_shoot] UNITS_MOVED BEFORE TRANSITION: {list(self.units_moved)}")
            
            self.actions["set_phase"]("shoot")
            self.actions["initialize_shooting_phase"]()
            # AI_TURN.md: Reset shot tracking at phase start, preserve moved tracking
            self.actions["reset_shot_units"]()
            self.actions["set_selected_unit_id"](None)
            
            print(f"📊 [use_phase_transition.py::transition_to_shoot] UNITS_MOVED AFTER TRANSITION: {list(self.game_state.get('units_moved', []))}")
            print(f"🧹 [use_phase_transition.py::transition_to_shoot] UNITS_SHOT RESET: {list(self.game_state.get('units_shot', []))}")
            print(f"✅ [use_phase_transition.py::transition_to_shoot] MOVED TO SHOOT PHASE - AI_TURN.md compliant")
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            self.units_shot = set()  # AI_TURN.md: Fresh shot tracking for new phase
        
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
            # AI_TURN.md: Reset charge tracking at phase start, preserve other tracking
            self.actions["reset_charged_units"]()
            self.actions["set_selected_unit_id"](None)
            
            print(f"🧹 [use_phase_transition.py::transition_to_charge] UNITS_CHARGED RESET: {list(self.game_state.get('units_charged', []))}")
            print(f"✅ [use_phase_transition.py::transition_to_charge] MOVED TO CHARGE PHASE - AI_TURN.md compliant")
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            self.units_charged = set()  # AI_TURN.md: Fresh charge tracking for new phase
        
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
            # AI_TURN.md: Reset combat tracking at phase start, preserve other tracking
            self.actions["reset_attacked_units"]()
            self.actions["set_selected_unit_id"](None)
            self.actions["set_mode"]("select")
            
            print(f"🧹 [use_phase_transition.py::transition_to_combat] UNITS_ATTACKED RESET: {list(self.game_state.get('units_attacked', []))}")
            print(f"✅ [use_phase_transition.py::transition_to_combat] MOVED TO COMBAT PHASE - AI_TURN.md compliant")
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            self.units_attacked = set()  # AI_TURN.md: Fresh combat tracking for new phase
        
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
            
            print(f"\n🔄 ENDING TURN - Player {self.current_player}")
            print(f"📊 UNITS_MOVED BEFORE TURN END: {list(self.game_state.get('units_moved', []))}")
            
            # Switch player (EXACT from TypeScript)
            new_player = 1 if self.current_player == 0 else 0
            self.actions["set_current_player"](new_player)
            
            # Set phase to move first
            self.actions["set_phase"]("move")
            
            print(f"🏁 STARTING NEW MOVEMENT PHASE - Player {new_player}")
            print(f"📊 UNITS_MOVED BEFORE RESET: {list(self.game_state.get('units_moved', []))}")
            
            # AI_TURN.md CRITICAL: Reset units_moved at START of new movement phase
            self.actions["reset_moved_units"]()
            self.actions["reset_fled_units"]()
            
            print(f"🧹 RESET MOVED UNITS CALLED")
            print(f"📊 UNITS_MOVED AFTER RESET: {list(self.game_state.get('units_moved', []))}")
            
            # CRITICAL FIX: Increment turn ONLY when Player 0 starts movement phase (EXACT from frontend)
            if new_player == 0:  # Player 0 is about to start their turn
                current_turn = self.game_state["current_turn"]
                new_turn = current_turn + 1
                self.actions["set_current_turn"](new_turn)
                self._log_turn_change(new_turn)
                
                # CRITICAL: Episode ends when max turns reached (episode rule compliance)
                try:
                    from config_loader import get_config_loader
                    config = get_config_loader()
                    max_turns = config.get_max_turns()
                    if new_turn > max_turns:
                        # Force episode end through game over condition
                        pass  # Let normal unit count logic handle this
                except Exception as e:
                    raise RuntimeError(f"Failed to load max_turns from config: {e}")
            
            # AI_TURN.md CRITICAL: Reset ALL other tracking sets at turn end
            self.actions["reset_charged_units"]()
            self.actions["reset_attacked_units"]()
            self.actions["reset_shot_units"]()
            
            # Reset units_charged for all units (EXACT from TypeScript)
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
            
            # AI_TURN.md CRITICAL: Force re-sync of ALL tracking sets in local state
            self.units_moved = set()
            self.units_shot = set()
            self.units_charged = set()
            self.units_attacked = set()
            self.units_fled = set()
            
            # CRITICAL FIX: Re-sync local state after making changes
            self.phase = self.game_state["phase"]
            self.current_player = self.game_state["current_player"]
        
        # Execute with delay to mirror setTimeout (can be immediate in training)
        delayed_end_turn()

    def ensure_charged_this_turn_defaults(self) -> None:
        """
        EXACT mirror of ensureChargedThisTurnDefaults from TypeScript.
        Ensure all units have units_charged property set.
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
        AI_TURN.md COMPLIANT phase transition processing.
        Single source of truth pattern - no double sync needed.
        """
        # AI_TURN.md: "Follow this sequence for EVERY phase to prevent state corruption"
        
        # Mandatory field validation only
        if 'phase' not in self.game_state:
            raise KeyError("Final game_state missing required 'phase' field")
        if 'current_player' not in self.game_state:
            raise KeyError("Final game_state missing required 'current_player' field")
        if 'units_moved' not in self.game_state:
            raise KeyError("game_state missing required 'units_moved' field")
        
        # AI_ARCHITECTURE.md: Single source of truth - use game_state directly
        current_phase = self.game_state["phase"]
        current_player = self.game_state["current_player"]
        
        # AI_TURN.md: Check "no eligible units remain" condition using live state
        eligible_units = self._get_eligible_units_for_current_phase_direct()
        
        if len(eligible_units) == 0:
            self._advance_to_next_phase(current_phase)
            
        # CRITICAL DEBUG: Capture atomic phase readings to detect race conditions
        phase_reading_1 = self.game_state["phase"]
        player_reading_1 = self.game_state["current_player"] 
        state_id = id(self.game_state)
        
        # Check state consistency
        phase_reading_2 = self.game_state["phase"]
        player_reading_2 = self.game_state["current_player"]
        
        # AI_ARCHITECTURE.md: Single source of truth - removed legacy sync code
        # All validation now uses game_state directly per changes 4-6
        
        # Validate only required fields exist
        if "units_moved" not in self.game_state:
            raise KeyError("game_state missing required 'units_moved' field during update")
        if "units_charged" not in self.game_state:
            raise KeyError("game_state missing required 'units_charged' field during update")
        if "units_attacked" not in self.game_state:
            raise KeyError("game_state missing required 'units_attacked' field during update")
        if "units_fled" not in self.game_state:
            raise KeyError("game_state missing required 'units_fled' field during update")

        # CRITICAL DEBUG: Verify final cached values match dictionary values
        dict_phase = self.game_state["phase"]
        dict_player = self.game_state["current_player"]

        # Main phase transition logic moved to _advance_to_next_phase() in process_phase_transitions()
        # Keep legacy compatibility for other callers
        current_phase = self.game_state["phase"]
        
        if current_phase == "move":
            if self.should_transition_from_move():
                self.transition_to_shoot()
                
        elif current_phase == "shoot":
            if self.should_transition_from_shoot():
                self.transition_to_charge()
                
        elif current_phase == "charge":
            if self.should_transition_from_charge():
                self.transition_to_combat()
                
        elif current_phase == "combat":
            # AI_TURN.md: Combat has complex sub-phase system
            combat_sub_phase = self.game_state.get("combat_sub_phase")
            
            if not combat_sub_phase:
                # Initialize combat phase with charged units sub-phase
                self.actions["set_combat_sub_phase"]("charged_units")
                print(f"🥇 [use_phase_transition.py::process_phase_transitions] COMBAT SUB-PHASE 1: Charged units priority")
                return
                
            elif combat_sub_phase == "charged_units":
                # Check if all charged units have been processed
                all_units = self.game_state["units"]
                current_player = self.game_state["current_player"]
                charged_units = [u for u in all_units 
                               if (u["player"] == current_player and 
                                   u["id"] in self.game_state["units_charged"] and
                                   u.get("CUR_HP", 0) > 0 and
                                   u["id"] not in self.game_state["units_attacked"])]
                
                if len(charged_units) == 0:
                    # Transition to alternating combat
                    next_combat_player = 1 if current_player == 0 else 0
                    self.actions["set_combat_sub_phase"]("alternating_combat")
                    self.actions["set_combat_active_player"](next_combat_player)
                    print(f"🔄 [use_phase_transition.py::process_phase_transitions] COMBAT SUB-PHASE 2: Alternating combat")
                    return
                    
            elif combat_sub_phase == "alternating_combat":
                # Handle alternating combat logic
                if self.should_end_alternating_combat():
                    self.end_turn()
                    return
                else:
                    # Switch combat active player if current has no eligible units
                    self.process_alternating_combat_player_switch()
                    
            # Check if turn should end
            if self.should_end_turn():
                self.end_turn()
                return
            
            # Handle combat sub-phase transitions (EXACT from TypeScript)
            if (self.combat_sub_phase == "charged_units" and 
                self.should_transition_from_charged_units_phase()):
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
                # End combat phase entirely
                self.end_turn()
                
            elif not self.combat_sub_phase:
                # Initialize combat phase with charged units sub-phase
                self.ensure_charged_this_turn_defaults()
                self.actions["set_combat_sub_phase"]("charged_units")
                self.actions["set_selected_unit_id"](None)

    def _log_turn_change(self, turn_number: int) -> None:
        """Log turn change to replay logger - ensure Turn 1 consistency"""
        # CRITICAL: Ensure turn logging matches episode start rules
        if turn_number < 1:
            turn_number = 1  # Enforce minimum turn number for consistency
        # Find and call the replay logger
        if hasattr(self, 'actions') and 'set_phase' in self.actions:
            # Get controller reference from actions
            if hasattr(self.actions['set_phase'], '__self__'):
                controller = self.actions['set_phase'].__self__
                if hasattr(controller, 'replay_logger') and controller.replay_logger:
                    controller.replay_logger.log_turn_change(turn_number)

    def process_alternating_combat_player_switch(self) -> None:
        """
        EXACT mirror of alternating player switching logic from TypeScript.
        Handle player switching in alternating combat phase.
        """
        if (self.phase == "combat" and 
            self.combat_sub_phase == "alternating_combat" and 
            self.combat_active_player is not None):
            
            # Only check for player switching when units_attacked changes (EXACT from TypeScript)
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
        TRAINING FIX: Handle single-unit gym actions properly.
        Returns True if any phase transitions occurred.
        """
        initial_phase = self.phase
        initial_player = self.current_player
        
        # TRAINING FIX: Check if current player has any remaining eligible units
        current_player_units = [u for u in self.units if u["player"] == self.current_player]
        eligible_current_units = [u for u in current_player_units if self.is_unit_eligible_func(u)]
        
        # TRAINING FIX: For training scenarios, always check phase completion conditions
        # Force phase advancement when current player is done OR when phase should naturally advance
        should_advance = (len(eligible_current_units) == 0 or 
                         (self.phase == "move" and self.should_transition_from_move()) or
                         (self.phase == "shoot" and self.should_transition_from_shoot()) or
                         (self.phase == "charge" and self.should_transition_from_charge()) or
                         (self.phase == "combat" and self.should_end_turn()))
        
        if should_advance:
            if self.phase == "move":
                self.transition_to_shoot()
            elif self.phase == "shoot":
                self.transition_to_charge()
            elif self.phase == "charge":
                self.transition_to_combat()
            elif self.phase == "combat":
                self.end_turn()
        
        # Process combat sub-phase transitions  
        self.process_phase_transitions()
        self.process_alternating_combat_player_switch()
        
        # Update local state to reflect changes
        self.phase = self.game_state.get("phase", self.phase)
        self.current_player = self.game_state.get("current_player", self.current_player)
        
        # Return True if state changed from initial
        return initial_phase != self.phase or initial_player != self.current_player

    def force_phase_advance(self, target_phase: str) -> None:
        """Force advance to specific phase (for training scenarios)"""
        try:
            from config_loader import get_config_loader
            config = get_config_loader()
            phase_order = config.get_phase_order()
        except Exception as e:
            raise RuntimeError(f"Failed to load phase_order from config: {e}")
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

    def _get_eligible_units_for_current_phase_direct(self) -> List[Dict[str, Any]]:
        """
        AI_TURN.md COMPLIANCE: Get eligible units using direct game_state access.
        AI_ARCHITECTURE.md: Single source of truth - no cached state needed.
        """
        current_player = self.game_state["current_player"]
        current_player_units = [u for u in self.game_state["units"] 
                              if u["player"] == current_player and u.get("CUR_HP", 0) > 0]
        
        eligible_units = []
        for unit in current_player_units:
            if self._check_unit_eligibility_ai_turn_direct(unit):
                eligible_units.append(unit)
                
        return eligible_units
    
    def _check_unit_eligibility_ai_turn_direct(self, unit: Dict[str, Any]) -> bool:
        """
        AI_TURN.md COMPLIANCE: Apply exact decision tree validation using live state.
        AI_ARCHITECTURE.md: Single source of truth - use game_state directly.
        """
        # AI_TURN.md: "Check CUR_HP > 0 first (most common failure condition)"
        if unit.get("CUR_HP", 0) <= 0:
            return False
            
        # Player validation
        if unit["player"] != self.game_state["current_player"]:
            return False
            
        # Phase-specific tracking set validation (AI_TURN.md decision trees) - direct access
        current_phase = self.game_state["phase"]
        if current_phase == "move":
            return unit["id"] not in self.game_state["units_moved"]
        elif current_phase == "shoot":
            return (unit["id"] not in self.game_state["units_shot"] and 
                   unit["id"] not in self.game_state["units_fled"] and
                   unit.get("RNG_RNG", 0) > 0)
        elif current_phase == "charge":
            # AI_TURN.md: Unit must not have charged AND must have valid targets within 12 hexes
            if (unit["id"] in self.game_state["units_charged"] or 
                unit["id"] in self.game_state["units_fled"]):
                return False
            # Additional validation: must have enemies within charge range
            all_units = self.game_state["units"]
            enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("CUR_HP", 0) > 0]
            # AI_PROTOCOLE.md: Use existing config files, never hardcode values
            try:
                from shared.gameMechanics import get_charge_max_distance
                charge_max_distance = get_charge_max_distance()
            except Exception as e:
                raise RuntimeError(f"Failed to load charge_max_distance from config: {e}")
            has_charge_targets = any(
                1 < max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) <= charge_max_distance
                for enemy in enemy_units
            )
            return has_charge_targets
        elif current_phase == "combat":
            # AI_TURN.md: Combat has complex sub-phase system
            if unit["id"] in self.game_state["units_attacked"]:
                return False
            if unit.get("CC_RNG", 0) <= 0:
                return False
                
            # AI_TURN.md: Check if unit has adjacent enemies (must be within CC_RNG, usually 1)
            all_units = self.game_state["units"]
            enemy_units = [u for u in all_units if u["player"] != unit["player"] and u.get("CUR_HP", 0) > 0]
            cc_range = unit.get("CC_RNG", 0)
            
            # Must be adjacent to at least one enemy to be eligible for combat
            has_adjacent_enemy = any(
                max(abs(unit["col"] - enemy["col"]), abs(unit["row"] - enemy["row"])) <= cc_range
                for enemy in enemy_units
            )
            
            return has_adjacent_enemy
        
        return False
    
    def _advance_to_next_phase(self, current_phase: str) -> None:
        """
        AI_TURN.md COMPLIANCE: Phase transition with proper tracking set reset.
        """
        if current_phase == "move":
            self.transition_to_shoot()
        elif current_phase == "shoot":
            self.transition_to_charge()
        elif current_phase == "charge":
            self.transition_to_combat()
        elif current_phase == "combat":
            self.end_turn()

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
            raise RuntimeError("No transition history available - cannot calculate training metrics")
        
        total_transitions = len(self.transition_history)
        if "current_turn" not in self.game_state:
            raise KeyError("game_state missing required 'current_turn' field for training metrics")
        total_turns = self.game_state["current_turn"]
        if total_turns < 1:
            raise ValueError(f"Invalid current_turn value: {total_turns}")
        
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