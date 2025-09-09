// frontend/src/hooks/useAITurn.ts
import { useCallback, useRef, useState, useEffect } from 'react';
import { Unit, GameState, PlayerId } from '../types/game';

interface GameActions {
  confirmMove: (unitId: number, destCol: number, destRow: number) => void;
  handleShoot: (shooterId: number, targetId: number) => void;
  handleCharge: (unitId: number, targetId: number) => void;
  handleFightAttack: (attackerId: number, targetId: number) => void;
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

  // Convert game state to AI backend format
  const convertToAIGameState = useCallback(() => {
    return {
      units: units.map(u => ({
        id: u.id,
        player: u.player,
        col: u.col,
        row: u.row,
        // UPPERCASE field compliance
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
      unitsMoved: gameState.unitsMoved,
      unitsCharged: gameState.unitsCharged,
      unitsAttacked: gameState.unitsAttacked,
      gameOver: false // Simplified for now - actual game over logic in GameController
    };
  }, [units, currentPlayer, phase, gameState]);

  // Get eligible AI units for current phase
  const getEligibleAIUnits = useCallback((): Unit[] => {
    const aiUnits = units.filter(u => u.player === 1 && (u.HP_CUR ?? u.HP_MAX) > 0);
    
    switch (phase) {
      case "move":
        return aiUnits.filter(u => !gameState.unitsMoved.includes(u.id));
      case "shoot":
        return aiUnits.filter(u => 
          !gameState.unitsMoved.includes(u.id) && 
          (u.RNG_RNG ?? 0) > 0 && 
          (u.RNG_ATK ?? 0) > 0
        );
      case "charge":
        return aiUnits.filter(u => !gameState.unitsCharged.includes(u.id));
      case "combat":
        return aiUnits.filter(u => {
          if (gameState.unitsAttacked.includes(u.id)) return false;
          // Check if unit is in combat range
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

  // Call AI backend API
  const callAIAPI = useCallback(async (aiGameState: any, unitId: number): Promise<AIActionResponse> => {
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch('/ai/api/get_ai_action', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          game_state: aiGameState,
          unit_id: unitId,
          phase: phase
        }),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(`AI API error: ${response.status} ${response.statusText}`);
      }

      const result = await response.json();
      return result;

    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        return { success: false, action: 'skip', unitId, error: 'Request aborted' };
      }
      throw error;
    }
  }, [phase]);

  // Process a single AI unit action
  const processAIUnitAction = useCallback(async (unit: Unit): Promise<boolean> => {
    try {
      const aiGameState = convertToAIGameState();
      const response = await callAIAPI(aiGameState, unit.id);

      if (!response.success) {
        console.warn(`AI action failed for unit ${unit.id}:`, response.error);
        return false;
      }

      // Execute the AI action using existing game actions
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
            gameActions.handleFightAttack(unit.id, response.targetId);
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

  // Main AI turn processing function
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
        // No eligible units, phase should transition automatically
        return;
      }

      // Process each eligible AI unit sequentially (AI_TURN.md compliance)
      for (const unit of eligibleUnits) {
        if (abortControllerRef.current?.signal.aborted) {
          break;
        }

        const success = await processAIUnitAction(unit);
        
        if (!success) {
          // Fallback: skip this unit to prevent infinite loops
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

        // Small delay between actions for better UX
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

  // Cleanup on unmount
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