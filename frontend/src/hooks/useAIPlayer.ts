// frontend/src/hooks/useAIPlayer.ts
import { useEffect, useRef, useCallback } from 'react';
import { GameState, AIGameState, UnitId } from '../types/game';
import { aiService, AIServiceError } from '../services/aiService';

interface UseAIPlayerParams {
  gameState: GameState;
  gameActions: {
    handleShoot: (shooterId: UnitId, targetId: UnitId) => void;
    handleCombatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
    handleCharge: (chargerId: UnitId, targetId: UnitId) => void;
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
        CUR_HP: u.CUR_HP ?? u.HP_MAX,
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
          const combatRange = u.CC_RNG || 1;
          const canAttack = enemyUnits.some(enemy => {
            const distance = Math.max(Math.abs(u.col - enemy.col), Math.abs(u.row - enemy.row));
            return distance <= combatRange;
          });
          return canAttack;
        });
      default:
        return [];
    }
  }, [units, phase, unitsMoved, unitsCharged, unitsAttacked]);

  // Helper to update unit position
  const updateUnitPosition = useCallback((unitId: UnitId, destCol: number, destRow: number) => {
    // This would need to be connected to the game state actions
    console.log(`[AI] Moving unit ${unitId} to (${destCol}, ${destRow})`);
    // You'll need to expose this from useGameState or pass it through gameActions
  }, []);

  // Helper to mark unit as moved/charged/attacked
  const markUnitAction = useCallback((unitId: UnitId, actionType: 'moved' | 'charged' | 'attacked') => {
    console.log(`[AI] Marking unit ${unitId} as ${actionType}`);
    // This would need to be connected to the game state actions
  }, []);

  // Process a single AI action with error handling
  const processAIAction = useCallback(async (unit: any, retryCount = 0): Promise<boolean> => {
    try {
      const gameState = convertToAIGameState();
      const result = await aiService.fetchAiAction(gameState);

      // Validate that the action is for the expected unit
      if (result.unitId !== unit.id) {
        console.warn(`[AI] Action unitId mismatch: expected ${unit.id}, got ${result.unitId}`);
        return false;
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

      console.warn(`[AI] Unexpected action for phase ${phase}:`, result);
      return false;

    } catch (error) {
      if (error instanceof AIServiceError) {
        console.error(`[AI] Service error for unit ${unit.id}:`, error.message);
      } else {
        console.error(`[AI] Unexpected error for unit ${unit.id}:`, error);
      }

      // Retry logic
      if (retryCount < retryAttempts) {
        console.log(`[AI] Retrying action for unit ${unit.id} (attempt ${retryCount + 1}/${retryAttempts})`);
        await new Promise(resolve => setTimeout(resolve, 1000 * (retryCount + 1))); // Exponential backoff
        return processAIAction(unit, retryCount + 1);
      }

      // Fallback to skip if all retries failed
      if (fallbackToSkip) {
        console.log(`[AI] Falling back to skip for unit ${unit.id}`);
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
      console.log('[AI] Already processing, skipping duplicate request');
      return;
    }

    isProcessingRef.current = true;
    
    try {
      // Create abort controller for this AI turn
      abortControllerRef.current = new AbortController();
      
      const eligibleUnits = getEligibleAIUnits();
      console.log(`[AI] Processing ${eligibleUnits.length} units for phase: ${phase}`);

      for (const unit of eligibleUnits) {
        // Check if we should abort
        if (abortControllerRef.current.signal.aborted) {
          console.log('[AI] Turn processing aborted');
          break;
        }

        console.log(`[AI] Processing unit: ${unit.name} (${unit.id})`);
        
        const success = await processAIAction(unit);
        
        if (!success) {
          console.warn(`[AI] Failed to process action for unit ${unit.id}`);
        }

        // Add delay between actions to make it more visible
        if (actionDelay > 0) {
          await new Promise(resolve => setTimeout(resolve, actionDelay));
        }
      }

      console.log(`[AI] Completed processing for phase: ${phase}`);
      
    } catch (error) {
      console.error('[AI] Error during turn processing:', error);
    } finally {
      isProcessingRef.current = false;
      abortControllerRef.current = null;
    }
  }, [getEligibleAIUnits, phase, processAIAction, actionDelay]);

  // Cleanup function to abort ongoing AI processing
  const abortAIProcessing = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      console.log('[AI] Aborted ongoing AI processing');
    }
    isProcessingRef.current = false;
  }, []);

  // Main effect to trigger AI actions
  useEffect(() => {
    // Only process if AI is enabled and it's the AI player's turn
    if (!enabled || currentPlayer !== 1) {
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

      console.log(`[AI] Triggering AI turn for phase: ${phase}`);
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