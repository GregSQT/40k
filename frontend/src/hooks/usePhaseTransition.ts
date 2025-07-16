// hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId } from '../types/game';

interface UsePhaseTransitionParams {
  gameState: GameState;
  actions: {
    setPhase: (phase: GameState['phase']) => void;
    setCurrentPlayer: (player: PlayerId) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMode: (mode: GameState['mode']) => void;
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
  };
}

export const usePhaseTransition = ({
  gameState,
  actions,
}: UsePhaseTransitionParams) => {
  const { units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked } = gameState;

  // Helper to get current player's units
  const getCurrentPlayerUnits = useCallback((): Unit[] => {
    return units.filter(u => u.player === currentPlayer);
  }, [units, currentPlayer]);

  // Helper to get enemy units
  const getEnemyUnits = useCallback((): Unit[] => {
    return units.filter(u => u.player !== currentPlayer);
  }, [units, currentPlayer]);

  // Helper to check if units are adjacent
  const areUnitsAdjacent = useCallback((unit1: Unit, unit2: Unit): boolean => {
    return Math.max(
      Math.abs(unit1.col - unit2.col),
      Math.abs(unit1.row - unit2.row)
    ) === 1;
  }, []);

  // Helper to check if unit is in range of another unit
  const isUnitInRange = useCallback((attacker: Unit, target: Unit, range: number): boolean => {
    return Math.max(
      Math.abs(attacker.col - target.col),
      Math.abs(attacker.row - target.row)
    ) <= range;
  }, []);

  // Check if move phase should transition to shoot phase
  const shouldTransitionFromMove = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    if (playerUnits.length === 0) return true;
    
    // All units have moved
    return playerUnits.every(unit => unitsMoved.includes(unit.id));
  }, [getCurrentPlayerUnits, unitsMoved]);

  // Check if shoot phase should transition to charge phase
  const shouldTransitionFromShoot = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) return true;

    // Find units that can still shoot
    const shootableUnits = playerUnits.filter(unit => {
      if (unitsMoved.includes(unit.id)) return false;
      return enemyUnits.some(enemy => isUnitInRange(unit, enemy, unit.RNG_RNG));
    });

    return shootableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsMoved, isUnitInRange]);

  // Check if charge phase should transition to combat phase
  const shouldTransitionFromCharge = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) return true;

    // Find units that can still charge
    const chargeableUnits = playerUnits.filter(unit => {
      if (unitsCharged.includes(unit.id)) return false;
      
      // Can't charge if adjacent to enemy
      if (enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy))) return false;
      
      // Must have enemy within move range
      return enemyUnits.some(enemy => isUnitInRange(unit, enemy, unit.MOVE));
    });

    console.log(`[PhaseTransition] Charge check - Player ${currentPlayer} units: ${playerUnits.length}, chargeable: ${chargeableUnits.length}, charged: ${unitsCharged.length}`);
    
    return chargeableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsCharged, areUnitsAdjacent, isUnitInRange, currentPlayer]);

  // Check if combat phase should end turn
  const shouldEndTurn = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) return true;

    // Find units that can still attack in combat
    const attackableUnits = playerUnits.filter(unit => {
      if (unitsAttacked.includes(unit.id)) return false;
      const combatRange = unit.CC_RNG || 1; // Use CC_RNG instead of hardcoded adjacency
      return enemyUnits.some(enemy => isUnitInRange(unit, enemy, combatRange));
    });

    return attackableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsAttacked, isUnitInRange]);

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
      actions.resetChargedUnits();
      actions.setSelectedUnitId(null);
    }, 300);
  }, [actions]);

  // Transition from charge to combat phase
  const transitionToCombat = useCallback(() => {
    setTimeout(() => {
      actions.setPhase("combat");
      actions.setSelectedUnitId(null);
      actions.resetAttackedUnits();
      actions.setMode("select");
    }, 300);
  }, [actions]);

  // End turn and switch to next player
  const endTurn = useCallback(() => {
    setTimeout(() => {
      actions.setCurrentPlayer(currentPlayer === 0 ? 1 : 0);
      actions.setPhase("move");
      actions.resetMovedUnits();
      actions.resetChargedUnits();
      actions.resetAttackedUnits();
      actions.setSelectedUnitId(null);
    }, 300);
  }, [actions, currentPlayer]);

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
        if (shouldEndTurn()) {
          endTurn();
        }
        break;
    }
  }, [
    phase,
    shouldTransitionFromMove,
    shouldTransitionFromShoot,
    shouldTransitionFromCharge,
    shouldEndTurn,
    transitionToShoot,
    transitionToCharge,
    transitionToCombat,
    endTurn,
  ]);

  // Log phase transitions for debugging
  useEffect(() => {
    console.log(`[PhaseTransition] Current phase: ${phase}, Player: ${currentPlayer}`);
  }, [phase, currentPlayer]);

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