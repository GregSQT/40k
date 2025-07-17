// hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId } from '../types/game';
import { areUnitsAdjacent, isUnitInRange } from '../utils/gameHelpers';

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
    resetFledUnits: () => void;  // NEW
  };
}

export const usePhaseTransition = ({
  gameState,
  actions,
}: UsePhaseTransitionParams) => {
  const { units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked, unitsFled } = gameState;

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
      if (unitsMoved.includes(unit.id)) return false;
      
      // NEW RULE: Units that fled cannot shoot
      if (unitsFled.includes(unit.id)) return false;
      
      // Can't shoot if adjacent to enemy (engaged in combat)
      const hasAdjacentEnemy = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
      if (hasAdjacentEnemy) return false;
      
      // Must have enemy within shooting range
      return enemyUnits.some(enemy => isUnitInRange(unit, enemy, unit.RNG_RNG));
    });

    return shootableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsMoved, unitsFled, isUnitInRange, areUnitsAdjacent]);

  // Check if charge phase should transition to combat phase
  const shouldTransitionFromCharge = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) return true;

    // Find units that can still charge
    const chargeableUnits = playerUnits.filter(unit => {
      if (unitsCharged.includes(unit.id)) return false;
      
      // NEW RULE: Units that fled cannot charge
      if (unitsFled.includes(unit.id)) return false;
      
      // Can't charge if adjacent to enemy
      const isAdjacent = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
      if (isAdjacent) return false;
      
      // Must have enemy within move range
      const inRange = enemyUnits.some(enemy => isUnitInRange(unit, enemy, unit.MOVE));
      
      // Debug logging to match useGameActions format
      console.log(`[PhaseTransition] Unit ${unit.name} (${unit.id}) charge eligibility: ${!isAdjacent && inRange} (adjacent: ${isAdjacent}, inRange: ${inRange})`);
      
      return inRange;
    });

    console.log(`[PhaseTransition] Charge check - Player ${currentPlayer} units: ${playerUnits.length}, chargeable: ${chargeableUnits.length}, charged: ${unitsCharged.length}`);
    
    return chargeableUnits.length === 0;
  }, [getCurrentPlayerUnits, getEnemyUnits, unitsCharged, unitsFled, areUnitsAdjacent, isUnitInRange, currentPlayer]);

  // Check if combat phase should end turn
  const shouldEndTurn = useCallback((): boolean => {
    const playerUnits = getCurrentPlayerUnits();
    const enemyUnits = getEnemyUnits();
    
    if (playerUnits.length === 0) {
      console.log(`[PhaseTransition] Combat - No player units, ending turn`);
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
      
      // Debug logging for each unit
      if (!canAttack) {
        console.log(`[PhaseTransition] Unit ${unit.name} (${unit.id}) cannot attack - CC_RNG: ${unit.CC_RNG}, position: (${unit.col}, ${unit.row})`);
        enemyUnits.forEach(enemy => {
          const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
          console.log(`  - Enemy ${enemy.name} (${enemy.id}) at (${enemy.col}, ${enemy.row}) - distance: ${distance}, range: ${combatRange}`);
        });
      }
      
      return canAttack;
    });

    const shouldEnd = attackableUnits.length === 0;
    console.log(`[PhaseTransition] Combat check - Player ${currentPlayer} units: ${playerUnits.length}, attackable: ${attackableUnits.length}, attacked: ${unitsAttacked.length}, shouldEnd: ${shouldEnd}`);
    
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
      actions.resetFledUnits();  // NEW
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