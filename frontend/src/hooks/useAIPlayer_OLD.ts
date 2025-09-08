// frontend/src/hooks/useAIPlayer.ts
import { useEffect, useRef, useCallback } from 'react';
import { GameState, AIGameState, UnitId } from '../types/game';
import { aiService, AIServiceError } from '../services/aiService';
import { offsetToCube, cubeDistance } from '../utils/gameHelpers';

interface UseAIPlayerParams {
  gameState: GameState;
  gameActions: {
    handleShoot: (shooterId: UnitId, targetId: UnitId) => void;
    handleCombatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
    handleCharge: (chargerId: UnitId, targetId: UnitId) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    updateUnit: (unitId: UnitId, updates: Partial<any>) => void;
  };
  enabled: boolean;
  config?: {
    actionDelay?: number;
    retryAttempts?: number;
    fallbackToSkip?: boolean;
  };
}

export const useAIPlayer = ({
  gameState,
  gameActions,
  enabled,
  config = {},
}: UseAIPlayerParams) => {
  const {
    actionDelay = 180,
    retryAttempts = 1,
    fallbackToSkip = true,
  } = config;

  const { units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked } = gameState;
  
  // Use ref to track if AI is currently processing to prevent duplicate actions
  const isProcessingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Helper to convert game state to AI format
  const convertToAIGameState = useCallback((): AIGameState => {
    return {
      units: units.map(u => ({
        id: u.id,
        player: u.player,
        col: u.col,
        row: u.row,
        HP_CUR: u.HP_CUR ?? u.HP_MAX,
        MOVE: u.MOVE,
        RNG_RNG: u.RNG_RNG,
        RNG_DMG: u.RNG_DMG,
        CC_DMG: u.CC_DMG,
      })),
    };
  }, [units]);

  // Helper to get AI units for current phase
  const getEligibleAIUnits = useCallback(() => {
    const aiUnits = units.filter(u => u.player === 1);
    const enemyUnits = units.filter(u => u.player !== 1);
    
    switch (phase) {
      case "move":
        return aiUnits.filter(u => !unitsMoved.includes(u.id));
      case "shoot":
        return aiUnits.filter(u => !unitsMoved.includes(u.id));
      case "charge":
        return aiUnits.filter(u => !unitsCharged.includes(u.id));
      case "combat":
        return aiUnits.filter(u => {
          if (unitsAttacked.includes(u.id)) return false;
          if (u.CC_RNG === undefined) {
            throw new Error('u.CC_RNG is required');
          }
          const combatRange = u.CC_RNG;
          const canAttack = enemyUnits.some(enemy => {
            const cube1 = offsetToCube(u.col, u.row);
            const cube2 = offsetToCube(enemy.col, enemy.row);
            const distance = cubeDistance(cube1, cube2);
            return distance <= combatRange;
          });
          return canAttack;
        });
      default:
        return [];
    }
  }, [units, phase, unitsMoved, unitsCharged, unitsAttacked]);

  const updateUnitPosition = useCallback((unitId: UnitId, destCol: number, destRow: number) => {
    // This would need to be connected to the game state actions
  }, []);

  const markUnitAction = useCallback((unitId: UnitId, actionType: 'moved' | 'charged' | 'attacked') => {
    if (actionType === 'moved') {
      gameActions.addMovedUnit(unitId);
    } else if (actionType === 'charged') {
      gameActions.addChargedUnit(unitId);
    } else if (actionType === 'attacked') {
      gameActions.addAttackedUnit(unitId);
    }
  }, [gameActions]);

  // Process a single AI action with error handling
  const processAIAction = useCallback(async (unit: any, retryCount = 0): Promise<boolean> => {
    try {
      const gameState = convertToAIGameState();
      const result = await aiService.fetchAiAction(gameState, unit.id);

      if (result.unitId !== unit.id) {
        if (result.action === 'skip') {
          result.unitId = unit.id;
        } else {
          return false;
        }
      }

      // Process the action based on phase and action type
      switch (phase) {
        case "move":
          if (result.action === "move" && result.destCol !== undefined && result.destRow !== undefined) {
            updateUnitPosition(result.unitId, result.destCol, result.destRow);
            markUnitAction(result.unitId, 'moved');
            return true;
          } else if (result.action === "moveAwayToRngRng" && result.destCol !== undefined && result.destRow !== undefined) {
            updateUnitPosition(result.unitId, result.destCol, result.destRow);
            markUnitAction(result.unitId, 'moved');
            return true;
          } else if (result.action === "skip") {
            markUnitAction(result.unitId, 'moved');
            return true;
          }
          break;

        case "shoot":
          if (result.action === "shoot" && result.targetId !== undefined) {
            gameActions.handleShoot(result.unitId, result.targetId);
            return true;
          } else if (result.action === "skip") {
            markUnitAction(result.unitId, 'moved');
            return true;
          }
          break;

        case "charge":
          if (result.action === "charge" && result.targetId !== undefined) {
            gameActions.handleCharge(result.unitId, result.targetId);
            return true;
          } else if (result.action === "skip") {
            markUnitAction(result.unitId, 'charged');
            return true;
          }
          break;

        case "combat":
          if (result.action === "attack" && result.targetId !== undefined) {
            gameActions.handleCombatAttack(result.unitId, result.targetId);
            return true;
          } else if (result.action === "skip") {
            markUnitAction(result.unitId, 'attacked');
            return true;
          }
          break;
      }

      return false;

    } catch (error) {
      if (retryCount < retryAttempts) {
        await new Promise(resolve => setTimeout(resolve, 1000 * (retryCount + 1)));
        return processAIAction(unit, retryCount + 1);
      }

      if (fallbackToSkip) {
        switch (phase) {
          case "move":
          case "shoot":
            markUnitAction(unit.id, 'moved');
            break;
          case "charge":
            markUnitAction(unit.id, 'charged');
            break;
          case "combat":
            markUnitAction(unit.id, 'attacked');
            break;
        }
        return true;
      }

      return false;
    }
  }, [phase, convertToAIGameState, updateUnitPosition, markUnitAction, gameActions, retryAttempts, fallbackToSkip]);

  // Process all AI units for the current phase
  const processAITurn = useCallback(async () => {
    if (isProcessingRef.current) {
      return;
    }

    isProcessingRef.current = true;
    
    try {
      abortControllerRef.current = new AbortController();
      
      const eligibleUnits = getEligibleAIUnits();

      for (const unit of eligibleUnits) {
        if (abortControllerRef.current.signal.aborted) {
          break;
        }

        const success = await processAIAction(unit);

        if (actionDelay > 0) {
          await new Promise(resolve => setTimeout(resolve, actionDelay));
        }
      }
      
    } catch (error) {
      // Handle error silently or with minimal logging
    } finally {
      isProcessingRef.current = false;
      abortControllerRef.current = null;
    }
  }, [getEligibleAIUnits, phase, processAIAction, actionDelay]);

  // Cleanup function to abort ongoing AI processing
  const abortAIProcessing = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    isProcessingRef.current = false;
  }, []);

  // Main effect to trigger AI actions
  useEffect(() => {
    // Only process if AI is enabled and it's the AI player's turn
    if (!enabled || currentPlayer !== 1) {
      abortAIProcessing(); // Stop any ongoing AI processing
      return;
    }

    // Skip if already processing
    if (isProcessingRef.current) {
      return;
    }

    // ==================== PHASE STABILITY CHECK ====================
    // Add small delay to ensure phase is stable before processing
    const phaseStabilityDelay = setTimeout(() => {
      // Double-check if we should still process (phase might have changed)
      if (!enabled || currentPlayer !== 1 || isProcessingRef.current) {
        return;
      }

      // Check if there are eligible units for this phase
      const eligibleUnits = getEligibleAIUnits();
      if (eligibleUnits.length === 0) {
        return;
      }

      processAITurn();
    }, 25); // 25ms delay for phase stability

    // Cleanup function
    return () => {
      clearTimeout(phaseStabilityDelay);
      abortAIProcessing();
    };
    
  }, [enabled, currentPlayer, phase, units, unitsMoved, unitsCharged, unitsAttacked, processAITurn, getEligibleAIUnits, abortAIProcessing]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortAIProcessing();
    };
  }, [abortAIProcessing]);

  return {
    isProcessing: isProcessingRef.current,
    abortProcessing: abortAIProcessing,
    processAITurn: processAITurn,
    eligibleUnits: getEligibleAIUnits(),
  };
};