// frontend/src/hooks/usePhaseTransition.ts
import { useEffect, useCallback } from 'react';
import type { GameState, Unit, UnitId, PlayerId, CombatSubPhase } from '../types/game';

interface UsePhaseTransitionParams {
  gameState: GameState;
  boardConfig: any;
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
    initializeCombatPhase: () => void;
    setCurrentTurn: (turn: number) => void;
    setCombatSubPhase: (subPhase: CombatSubPhase | undefined) => void;
    setCombatActivePlayer: (player: PlayerId | undefined) => void;
    setUnits: (units: Unit[]) => void;
  };
}

export const usePhaseTransition = ({
  gameState,
  boardConfig: _boardConfig,
  isUnitEligible,
  actions,
}: UsePhaseTransitionParams) => {
  // AI_TURN.md: Phase completion by eligibility (NOT step counts)
  const shouldTransitionPhase = useCallback((_phase: string): boolean => {
    const playerUnits = gameState.units.filter(u => u.player === gameState.currentPlayer);
    const eligibleUnits = playerUnits.filter(unit => isUnitEligible(unit));
    return eligibleUnits.length === 0;
  }, [gameState.units, gameState.currentPlayer, isUnitEligible]);

  // AI_TURN.md: Eligibility-based phase transitions (core principle)
  useEffect(() => {
    if (shouldTransitionPhase(gameState.phase)) {
      // Phase transitions based on unit eligibility only
      setTimeout(() => {
        switch (gameState.phase) {
          case "move":
            actions.setPhase("shoot");
            break;
          case "shoot":
            actions.setPhase("charge");
            break;
          case "charge":
            actions.setPhase("combat");
            break;
          case "combat":
            // End turn
            const newPlayer = gameState.currentPlayer === 0 ? 1 : 0;
            actions.setCurrentPlayer(newPlayer);
            actions.setPhase("move");
            if (newPlayer === 0) {
              actions.setCurrentTurn((gameState.currentTurn ?? 1) + 1);
            }
            break;
        }
      }, 300);
    }
  }, [gameState.phase, gameState.currentPlayer, shouldTransitionPhase, actions]);

  return {
    shouldTransitionPhase
  };
};