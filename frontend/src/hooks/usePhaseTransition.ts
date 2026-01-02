// frontend/src/hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import type { GameState, Unit, UnitId, PlayerId, FightSubPhase } from '../types/game';

interface UsePhaseTransitionParams {
  gameState: GameState;
  boardConfig: Record<string, unknown> | null | undefined;
  isUnitEligible: (unit: Unit) => boolean;
  actions: {
    setPhase: (phase: GameState['phase']) => void;
    setCurrentPlayer: (player: PlayerId) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMode: (mode: GameState['mode']) => void;
    resetMovedUnits: () => void;
    resetChargedUnits: () => void;
    resetAttackedUnits: () => void;
    resetFledUnits: () => void;
    initializeFightPhase: () => void;
    setCurrentTurn: (turn: number) => void;
    setFightSubPhase: (subPhase: FightSubPhase | undefined) => void;
    setFightActivePlayer: (player: PlayerId | undefined) => void;
    setUnits: (units: Unit[]) => void;
  };
}

export const usePhaseTransition = ({
  gameState,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  boardConfig: _boardConfig,
  isUnitEligible,
  actions,
}: UsePhaseTransitionParams) => {
  // Phase completion by eligibility (NOT step counts)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const shouldTransitionPhase = useCallback((_phase: string): boolean => {
    const playerUnits = gameState.units.filter(u => u.player === gameState.currentPlayer);
    const eligibleUnits = playerUnits.filter(unit => isUnitEligible(unit));
    return eligibleUnits.length === 0;
  }, [gameState.units, gameState.currentPlayer, isUnitEligible]);

  // Eligibility-based phase transitions (core principle)
  useEffect(() => {
    if (shouldTransitionPhase(gameState.phase)) {
      // Phase transitions based on unit eligibility only
      setTimeout(() => {
        switch (gameState.phase) {
          case "command":
            actions.setPhase("move");
            break;
          case "move":
            actions.setPhase("shoot");
            break;
          case "shoot":
            actions.setPhase("charge");
            break;
          case "charge":
            actions.setPhase("fight");
            break;
          case "fight": {
            // End turn - transition to command phase (not move)
            const newPlayer = gameState.currentPlayer === 0 ? 1 : 0;
            actions.setCurrentPlayer(newPlayer);
            actions.setPhase("command");  // Au lieu de "move"
            // Note: Turn increment is handled by backend in fight_handlers
            break;
          }
        }
      }, 300);
    }
  }, [gameState.phase, gameState.currentPlayer, gameState.currentTurn, shouldTransitionPhase, actions]);

  return {
    shouldTransitionPhase
  };
};