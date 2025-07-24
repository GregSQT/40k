// hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import { GameState, Unit, UnitId, PlayerId, CombatSubPhase } from '../types/game';
import { areUnitsAdjacent, isUnitInRange, hasLineOfSight } from '../utils/gameHelpers';

interface UsePhaseTransitionParams {
  gameState: GameState;
  boardConfig: any; // Add boardConfig parameter
  actions: {
    setPhase: (phase: GameState['phase']) => void;
    setCurrentPlayer: (player: PlayerId) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMode: (mode: GameState['mode']) => void;
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    resetFledUnits: () => void;  // NEW
    initializeCombatPhase: () => void;  // NEW
    setCurrentTurn: (turn: number) => void;  // NEW
    setCombatSubPhase: (subPhase: CombatSubPhase | undefined) => void; // NEW
    setCombatActivePlayer: (player: PlayerId | undefined) => void; // NEW
    setUnits: (units: Unit[]) => void; // NEW
  };
}

export const usePhaseTransition = ({
  gameState,
  boardConfig,
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
    const eligibleChargedUnits = activePlayerUnits.filter(unit => {
      if (unitsAttacked.includes(unit.id)) return false;
      if (!unit.hasChargedThisTurn) return false;
      // Check if unit has enemies in combat range
      const enemyUnits = units.filter(u => u.player !== currentPlayer);
      const combatRange = unit.CC_RNG || 1;
      return enemyUnits.some(enemy => {
        const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
        return distance <= combatRange;
      });
    });
    
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
      const eligibleUnits = playerUnits.filter(unit => {
        if (unitsAttacked.includes(unit.id)) return false;
        if (unit.hasChargedThisTurn) return false; // Non-charged units only in alternating phase
        // Check if unit has enemies in combat range
        const enemyUnits = units.filter(u => u.player !== player);
        const combatRange = unit.CC_RNG || 1;
        return enemyUnits.some(enemy => {
          const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
          return distance <= combatRange;
        });
      });
      
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
      
      return inRange;
    });

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
          
          console.log("✅ Set alternating combat phase, active combat player:", nextCombatPlayer);
          
          // Force immediate state propagation by triggering a re-render
          setTimeout(() => {
            console.log("🔄 Forcing UI update - should see alternating_combat phase now");
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

  // Handle alternating player switching in combat
  useEffect(() => {
    if (phase === "combat" && combatSubPhase === "alternating_combat" && combatActivePlayer !== undefined) {
      // Check if current combat player has no eligible units
      const currentCombatPlayerUnits = units.filter(u => u.player === combatActivePlayer);
      const hasEligibleUnits = currentCombatPlayerUnits.some(unit => {
        if (unitsAttacked.includes(unit.id)) return false;
        if (unit.hasChargedThisTurn) return false; // Non-charged units only
        
        const enemyUnits = units.filter(u => u.player !== combatActivePlayer);
        const combatRange = unit.CC_RNG || 1;
        return enemyUnits.some(enemy => {
          const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
          return distance <= combatRange;
        });
      });
      
      if (!hasEligibleUnits) {
        // Switch to other player
        const otherPlayer = combatActivePlayer === 0 ? 1 : 0;
        setTimeout(() => {
          actions.setCombatActivePlayer(otherPlayer);
          actions.setSelectedUnitId(null);
        }, 500);
      }
    }
  }, [phase, combatSubPhase, combatActivePlayer, units, unitsAttacked, actions]);

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