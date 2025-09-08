// hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId, CombatSubPhase } from '../types/game';
import { areUnitsAdjacent, isUnitInRange, hasLineOfSight } from '../utils/gameHelpers';

interface UsePhaseTransitionParams {
  gameState: GameState;
  boardConfig: any;
  isUnitEligible: (unit: Unit) => boolean; // Add the authoritative eligibility function
  actions: {
    setPhase: (phase: GameState['phase']) => void;
    setCurrentPlayer: (player: PlayerId) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMode: (mode: GameState['mode']) => void;
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    resetFledUnits: () => void;
    initializeCombatPhase: () => void;
    setCurrentTurn: (turn: number) => void;
    setCombatSubPhase: (subPhase: CombatSubPhase | undefined) => void;
    setCombatActivePlayer: (player: PlayerId | undefined) => void;
    setUnits: (units: Unit[]) => void;
  };
}

export const usePhaseTransition = ({
  gameState,
  boardConfig,
  isUnitEligible,
  actions,
}: UsePhaseTransitionParams) => {
  const { units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked, unitsFled, combatSubPhase, combatActivePlayer } = gameState;

  // Helper to check if charged units phase should transition to alternating phase
  // Helper to ensure all units have hasChargedThisTurn property set
  const ensureChargedThisTurnDefaults = useCallback(() => {
    const unitsNeedingDefaults = units.some(unit => unit.hasChargedThisTurn === undefined);
    if (unitsNeedingDefaults) {
      const updatedUnits = units.map(unit => ({
        ...unit,
        hasChargedThisTurn: unit.hasChargedThisTurn ?? false
      }));
      actions.setUnits(updatedUnits);
    }
  }, [units, actions]);

  const shouldTransitionFromChargedUnitsPhase = useCallback((): boolean => {
    if (phase !== "combat" || combatSubPhase !== "charged_units") return false;
    
    const activePlayerUnits = units.filter(u => u.player === currentPlayer);
    // Use the authoritative isUnitEligible function instead of duplicate logic
    const eligibleChargedUnits = activePlayerUnits.filter(unit => isUnitEligible(unit));
    
    const shouldTransition = eligibleChargedUnits.length === 0;
    
    return shouldTransition;
  }, [units, currentPlayer, phase, combatSubPhase, unitsAttacked]);

  // Helper to check if alternating combat phase should end
  const shouldEndAlternatingCombat = useCallback((): boolean => {
    if (phase !== "combat" || combatSubPhase !== "alternating_combat") return false;
    
    // Check if any player has eligible units
    const allPlayers = [0, 1] as PlayerId[];
    
    for (const player of allPlayers) {
      const playerUnits = units.filter(u => u.player === player);
      // Use the authoritative isUnitEligible function instead of duplicate logic
      const eligibleUnits = playerUnits.filter(unit => isUnitEligible(unit));
      
      if (eligibleUnits.length > 0) return false; // Still has eligible units
    }
    
    return true; // No eligible units for any player
  }, [units, phase, combatSubPhase, unitsAttacked]);

  // Helper to get current player's units
  const getCurrentPlayerUnits = useCallback((): Unit[] => {
    return units.filter(u => u.player === currentPlayer);
  }, [units, currentPlayer]);

  // Helper to get enemy units
  const getEnemyUnits = useCallback((): Unit[] => {
    return units.filter(u => u.player !== currentPlayer);
  }, [units, currentPlayer]);

  // Use imported helper functions from gameHelpers - DO NOT redefine locally

  // Check if move phase should transition to shoot phase
  const shouldTransitionFromMove = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    return playerUnits.every(unit => {
      if (unitsMoved.includes(unit.id)) return true;
      // Units adjacent to enemies can still move (flee), but if they don't move, phase continues
      return false;
    });
  }, [getCurrentPlayerUnits, unitsMoved]);

  // Check if shoot phase should transition to charge phase
  const shouldTransitionFromShoot = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) return true;

    // Find units that can still shoot
    const shootableUnits = playerUnits.filter(unit => {
      // Check if unit already shot this phase (tracked in unitsMoved during shoot phase)
      if (unitsMoved.includes(unit.id)) return false;
      
      // NEW RULE: Units that fled cannot shoot
      if (unitsFled.includes(unit.id)) return false;
      
      // CRITICAL: Check if unit has shots remaining
      if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT <= 0) return false;
      
      // Can't shoot if adjacent to enemy (engaged in combat)
      const hasAdjacentEnemy = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
      if (hasAdjacentEnemy) return false;
      
      // Must have enemy within shooting range AND line of sight
      return enemyUnits.some(enemy => {
        if (!isUnitInRange(unit, enemy, unit.RNG_RNG)) return false;
        
        // Check line of sight using boardConfig
        if (boardConfig && boardConfig.wall_hexes) {
          const lineOfSight = hasLineOfSight(
            { col: unit.col, row: unit.row },
            { col: enemy.col, row: enemy.row },
            boardConfig.wall_hexes
          );
          if (!lineOfSight.canSee) return false;
        }
        
        return true;
      });
    });

    return shootableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsFled, unitsMoved, isUnitInRange, areUnitsAdjacent, currentPlayer, boardConfig]);

  // Check if charge phase should transition to combat phase
  const shouldTransitionFromCharge = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    
    if (playerUnits.length === 0) return true;

    // Use the authoritative isUnitEligible function - no duplicate logic!
    const chargeableUnits = playerUnits.filter(unit => isUnitEligible(unit));

    return chargeableUnits.length === 0;
  }, [getCurrentPlayerUnits, isUnitEligible]);

  // Check if combat phase should end turn
  const shouldEndTurn = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) {
      return true;
    }

    // Find units that can still attack in combat
    const attackableUnits = playerUnits.filter(unit => {
      if (unitsAttacked.includes(unit.id)) return false;
      if (unit.CC_RNG === undefined) {
        throw new Error('unit.CC_RNG is required');
      }
      const combatRange = unit.CC_RNG;
      const canAttack = enemyUnits.some(enemy => isUnitInRange(unit, enemy, combatRange));
      
      return canAttack;
    });

    const shouldEnd = attackableUnits.length === 0;
    return shouldEnd;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsAttacked, isUnitInRange, currentPlayer]);

  // Transition from move to shoot phase
  const transitionToShoot = useCallback(() => {
    setTimeout(() => {
      actions.setPhase("shoot");
      actions.resetMovedUnits();
      actions.setSelectedUnitId(null);
    }, 300);
  }, [actions]);

  // Transition from shoot to charge phase
  const transitionToCharge = useCallback(() => {
    setTimeout(() => {
      actions.setPhase("charge");
      actions.resetMovedUnits();  // Reset unitsMoved when entering charge phase
      actions.resetChargedUnits();
      actions.setSelectedUnitId(null);
    }, 300);
  }, [actions]);

  // Transition from charge to combat phase
  const transitionToCombat = useCallback(() => {
    setTimeout(() => {
      actions.setPhase("combat");
      actions.initializeCombatPhase();
      actions.setSelectedUnitId(null);
      actions.resetAttackedUnits();
      actions.setMode("select");
    }, 300);
  }, [actions]);

  // End turn and switch to next player
  const endTurn = useCallback(() => {
    setTimeout(() => {
      const newPlayer = currentPlayer === 0 ? 1 : 0;
      actions.setCurrentPlayer(newPlayer);
      
      // Increment turn when player 0 starts their turn (beginning of new turn)
      if (newPlayer === 0) {
        actions.setCurrentTurn(gameState.currentTurn + 1);
      }
      
      actions.setPhase("move");
      actions.resetMovedUnits();
      actions.resetChargedUnits();
      actions.resetAttackedUnits();
      actions.resetFledUnits();  // NEW
      
      // Reset hasChargedThisTurn for all units at end of turn
      const updatedUnits = gameState.units.map(unit => ({
        ...unit,
        hasChargedThisTurn: false
      }));
      actions.setUnits(updatedUnits);
      
      actions.setSelectedUnitId(null);
      
      // Reset combat sub-phase for next turn
      actions.setCombatSubPhase(undefined);
      actions.setCombatActivePlayer(undefined);
    }, 300);
  }, [actions, currentPlayer, gameState.currentTurn, gameState.units]);

  // Main phase transition effect
  useEffect(() => {
    switch (phase) {
      case "move":
        if (shouldTransitionFromMove()) {
          transitionToShoot();
        }
        break;
        
      case "shoot":
        if (shouldTransitionFromShoot()) {
          transitionToCharge();
        }
        break;
        
      case "charge":
        if (shouldTransitionFromCharge()) {
          transitionToCombat();
        }
        break;
        
      case "combat":
        // Handle combat sub-phase transitions
        if (combatSubPhase === "charged_units" && shouldTransitionFromChargedUnitsPhase()) {
          // Transition from charged units phase to alternating combat
          // Use setState updates with immediate re-render
          const nextCombatPlayer = currentPlayer === 0 ? 1 : 0;
          
          // Batch all state updates together
          actions.setCombatSubPhase("alternating_combat");
          actions.setCombatActivePlayer(nextCombatPlayer);
          actions.setSelectedUnitId(null);
          
          // Force immediate state propagation by triggering a re-render
          setTimeout(() => {
            // Trigger a dummy update to force re-render
            actions.setSelectedUnitId(null);
            actions.setMode("select");
          }, 100);
        } else if (combatSubPhase === "alternating_combat" && shouldEndAlternatingCombat()) {
          // End combat phase entirely
          endTurn();
        } else if (!combatSubPhase) {
          // Initialize combat phase with charged units sub-phase
          ensureChargedThisTurnDefaults();
          actions.setCombatSubPhase("charged_units");
          actions.setSelectedUnitId(null);
        }
        break;
    }
  }, [
    phase,
    shouldTransitionFromMove,
    shouldTransitionFromShoot,
    shouldTransitionFromCharge,
    shouldEndTurn,
    shouldTransitionFromChargedUnitsPhase,
    shouldEndAlternatingCombat,
    transitionToShoot,
    transitionToCharge,
    transitionToCombat,
    endTurn,
    combatSubPhase,
    combatActivePlayer,
    shouldTransitionFromChargedUnitsPhase,
    shouldEndAlternatingCombat,
    unitsAttacked, // This should trigger re-evaluation when units finish attacking
  ]);

  // Handle alternating player switching in combat - ONLY when a unit actually attacks
  useEffect(() => {
    if (phase === "combat" && combatSubPhase === "alternating_combat" && combatActivePlayer !== undefined) {
      // Only check for player switching when unitsAttacked changes (not continuously)
      // This prevents interference with unit selection
      const currentCombatPlayerUnits = units.filter(u => u.player === combatActivePlayer);
      // Use the authoritative isUnitEligible function instead of duplicate logic
      const hasEligibleUnits = currentCombatPlayerUnits.some(unit => isUnitEligible(unit));
      
      if (!hasEligibleUnits) {
        // Switch to other player immediately (no delay that interferes with selection)
        const otherPlayer = combatActivePlayer === 0 ? 1 : 0;
        actions.setCombatActivePlayer(otherPlayer);
        actions.setSelectedUnitId(null);
      }
    }
  }, [phase, combatSubPhase, combatActivePlayer, unitsAttacked, actions, isUnitEligible]); // Include isUnitEligible dependency

  return {
    // Expose transition functions for manual control if needed
    transitionToShoot,
    transitionToCharge,
    transitionToCombat,
    endTurn,
    
    // Expose check functions for external use
    shouldTransitionFromMove,
    shouldTransitionFromShoot,
    shouldTransitionFromCharge,
    shouldEndTurn,
  };
};