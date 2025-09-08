// frontend/src/hooks/useAITurn.ts
import { useCallback, useRef, useState, useEffect } from 'react';
import type { Unit, GameState, PlayerId } from '../types/game';

interface GameActions {
  confirmMove: (unitId: number, destCol: number, destRow: number) => void;
  handleShoot: (shooterId: number, targetId: number) => void;
  handleCharge: (unitId: number, targetId: number) => void;
  handleCombatAttack: (attackerId: number, targetId: number) => void;
  addMovedUnit: (unitId: number) => void;
  addChargedUnit: (unitId: number) => void;
  addAttackedUnit: (unitId: number) => void;
}

interface AIActionResponse {
  success: boolean;
  action: string;
  unitId: number;
  targetId?: number;
  destinationCol?: number;
  destinationRow?: number;
  error?: string;
}

interface UseAITurnParams {
  gameState: GameState;
  gameActions: GameActions;
  currentPlayer: PlayerId;
  phase: string;
  units: Unit[];
}

interface UseAITurnReturn {
  isAIProcessing: boolean;
  processAITurn: () => Promise<void>;
  aiError: string | null;
  clearAIError: () => void;
}

export function useAITurn({
  gameState,
  gameActions,
  currentPlayer,
  phase,
  units
}: UseAITurnParams): UseAITurnReturn {
  const [isAIProcessing, setIsAIProcessing] = useState(false);
  const [aiError, setAIError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const processingRef = useRef(false);

  // AI_TURN.md: Convert to backend format with UPPERCASE fields
  const convertToAIGameState = useCallback(() => {
    return {
      units: units.map(u => ({
        id: u.id,
        player: u.player,
        col: u.col,
        row: u.row,
        // AI_TURN.md: UPPERCASE field compliance
        HP_MAX: u.HP_MAX,
        HP_CUR: u.HP_CUR ?? u.HP_MAX,
        MOVE: u.MOVE,
        RNG_RNG: u.RNG_RNG,
        RNG_ATK: u.RNG_ATK,
        RNG_STR: u.RNG_STR,
        RNG_DMG: u.RNG_DMG,
        CC_RNG: u.CC_RNG,
        CC_ATK: u.CC_ATK,
        CC_STR: u.CC_STR,
        CC_DMG: u.CC_DMG,
        ARMOR_SAVE: u.ARMOR_SAVE,
        T: u.T,
        unitType: u.type,
        name: u.name,
        isAIControlled: u.player === 1
      })),
      currentPlayer,
      phase,
      turn: gameState.currentTurn,
      unitsMoved: gameState.unitsMoved ?? [],
      unitsCharged: gameState.unitsCharged ?? [],
      unitsAttacked: gameState.unitsAttacked ?? [],
      episode_steps: gameState.episode_steps, // AI_TURN.md: Built-in step counting
      gameOver: false
    };
  }, [units, currentPlayer, phase, gameState]);

  // AI_TURN.md: Sequential activation - get ONE eligible unit at a time
  const getEligibleAIUnits = useCallback((): Unit[] => {
    const aiUnits = units.filter(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    
    switch (phase) {
      case "move":
        return aiUnits.filter(u => !(gameState.unitsMoved ?? []).includes(u.id));
      case "shoot":
        return aiUnits.filter(u => 
          !(gameState.unitsMoved ?? []).includes(u.id) && 
          (u.RNG_RNG ?? 0) > 0 && 
          (u.RNG_ATK ?? 0) > 0
        );
      case "charge":
        return aiUnits.filter(u => !(gameState.unitsCharged ?? []).includes(u.id));
      case "combat":
        return aiUnits.filter(u => {
          if ((gameState.unitsAttacked ?? []).includes(u.id)) return false;
          const enemyUnits = units.filter(enemy => enemy.player === 0 && (enemy.HP_CUR ?? enemy.HP_MAX) > 0);
          return enemyUnits.some(enemy => {
            const distance = Math.max(
              Math.abs(u.col - enemy.col),
              Math.abs(u.row - enemy.row)
            );
            return distance <= (u.CC_RNG ?? 1);
          });
        });
      default:
        return [];
    }
  }, [units, phase, gameState]);

  const callAIAPI = useCallback(async (aiGameState: any, unitId: number): Promise<AIActionResponse> => {
    // Stub implementation - return skip action for now
    return { success: true, action: 'skip', unitId };
  }, [phase]);

  // AI_TURN.md: Process ONE unit action at a time (sequential activation)
  const processAIUnitAction = useCallback(async (unit: Unit): Promise<boolean> => {
    try {
      const response = await callAIAPI(convertToAIGameState(), unit.id);

      if (!response.success) {
        console.warn(`AI action failed for unit ${unit.id}:`, response.error);
        return false;
      }

      // Execute ONE action per unit (AI_TURN.md compliance)
      switch (phase) {
        case "move":
          if (response.action === "move" && response.destinationCol !== undefined && response.destinationRow !== undefined) {
            gameActions.confirmMove(unit.id, response.destinationCol, response.destinationRow);
            return true;
          } else if (response.action === "skip") {
            gameActions.addMovedUnit(unit.id);
            return true;
          }
          break;

        case "shoot":
          if (response.action === "shoot" && response.targetId !== undefined) {
            gameActions.handleShoot(unit.id, response.targetId);
            return true;
          } else if (response.action === "skip") {
            gameActions.addMovedUnit(unit.id);
            return true;
          }
          break;

        case "charge":
          if (response.action === "charge" && response.targetId !== undefined) {
            gameActions.handleCharge(unit.id, response.targetId);
            return true;
          } else if (response.action === "skip") {
            gameActions.addChargedUnit(unit.id);
            return true;
          }
          break;

        case "combat":
          if (response.action === "attack" && response.targetId !== undefined) {
            gameActions.handleCombatAttack(unit.id, response.targetId);
            return true;
          } else if (response.action === "skip") {
            gameActions.addAttackedUnit(unit.id);
            return true;
          }
          break;
      }

      return false;
    } catch (error) {
      console.error(`AI processing error for unit ${unit.id}:`, error);
      setAIError(`AI decision failed: ${(error as Error).message}`);
      return false;
    }
  }, [convertToAIGameState, callAIAPI, phase, gameActions]);

  // AI_TURN.md: Sequential processing of units (ONE per gym step)
  const processAITurn = useCallback(async (): Promise<void> => {
    if (processingRef.current || currentPlayer !== 1) {
      return;
    }

    processingRef.current = true;
    setIsAIProcessing(true);
    setAIError(null);

    try {
      const eligibleUnits = getEligibleAIUnits();
      
      if (eligibleUnits.length === 0) {
        return;
      }

      // AI_TURN.md: Process each unit sequentially
      for (const unit of eligibleUnits) {
        if (abortControllerRef.current?.signal.aborted) {
          break;
        }

        const success = await processAIUnitAction(unit);
        
        if (!success) {
          // Fallback: skip unit to prevent infinite loops
          switch (phase) {
            case "move":
            case "shoot":
              gameActions.addMovedUnit(unit.id);
              break;
            case "charge":
              gameActions.addChargedUnit(unit.id);
              break;
            case "combat":
              gameActions.addAttackedUnit(unit.id);
              break;
          }
        }

        await new Promise(resolve => setTimeout(resolve, 500));
      }

    } catch (error) {
      console.error('AI turn processing error:', error);
      setAIError(`AI turn failed: ${(error as Error).message}`);
    } finally {
      processingRef.current = false;
      setIsAIProcessing(false);
    }
  }, [currentPlayer, getEligibleAIUnits, processAIUnitAction, gameActions, phase]);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const clearAIError = useCallback(() => {
    setAIError(null);
  }, []);

  return {
    isAIProcessing,
    processAITurn,
    aiError,
    clearAIError
  };
}