// src/components/GameController.tsx
import React, { useState } from "react";
import { ErrorBoundary } from "./ErrorBoundary";
import { UnitSelector } from "./UnitSelector";
import { GameBoard } from "./GameBoard";
import { GameStatus } from "./GameStatus";
import { useGameState } from "../hooks/useGameState";
import { useGameActions } from "../hooks/useGameActions";
import { useAIPlayer } from "../hooks/useAIPlayer";
import { usePhaseTransition } from "../hooks/usePhaseTransition";
import { Unit } from "../types/game";
import { ShootingSequenceState, shootingSequenceManager } from "../utils/ShootingSequenceManager";

interface GameControllerProps {
  initialUnits: Unit[];
  className?: string;
}

export const GameController: React.FC<GameControllerProps> = ({
  initialUnits,
  className = "",
}) => {
  // Initialize game state with custom hook
  const { gameState, movePreview, attackPreview, actions } = useGameState(initialUnits);
  
  // Shooting sequence state management
  const [shootingSequenceState, setShootingSequenceState] = useState<ShootingSequenceState | null>(null);
  
  // Set up game actions
  const gameActions = useGameActions({
    gameState,
    movePreview,
    attackPreview,
    actions,
    shootingSequenceState,
    setShootingSequenceState,
  });

  // Handle AI player behavior
  useAIPlayer({
    gameState,
    gameActions,
    enabled: gameState.currentPlayer === 1,
  });

  // Manage phase transitions
  usePhaseTransition({
    gameState,
    actions,
  });

  // Shooting sequence handlers
  const handleShootingStepComplete = () => {
    if (shootingSequenceState?.isActive) {
      console.log("🎲 Advancing to next shooting step");
      shootingSequenceManager.nextStep();
    }
  };
  
  const handleCancelShootingSequence = () => {
    setShootingSequenceState(null);
  };

  return (
    <div className={`game-controller ${className}`}>
      <aside className="sidebar">
        <ErrorBoundary fallback={<div>Failed to load unit selector</div>}>
          <UnitSelector
            units={gameState.units}
            currentPlayer={gameState.currentPlayer}
            selectedUnitId={gameState.selectedUnitId}
            onSelect={gameState.phase === "charge" ? gameActions.selectCharger : gameActions.selectUnit}
            unitsMoved={gameState.unitsMoved}
            unitsCharged={gameState.unitsCharged}
            unitsAttacked={gameState.unitsAttacked}
            phase={gameState.phase}
          />
        </ErrorBoundary>
      </aside>

      <main className="main-content">
        <header className="game-header">
          <h1>WH40K Tactics RL Demo</h1>
        </header>

        <div className="game-area">
          <ErrorBoundary fallback={<div>Failed to load game board</div>}>
            <GameBoard
              units={gameState.units}
              selectedUnitId={gameState.selectedUnitId}
              phase={gameState.phase}
              mode={gameState.mode}
              movePreview={movePreview}
              attackPreview={attackPreview}
              currentPlayer={gameState.currentPlayer}
              unitsMoved={gameState.unitsMoved}
              unitsCharged={gameState.unitsCharged}
              unitsAttacked={gameState.unitsAttacked}
              onSelectUnit={gameState.phase === "charge" ? gameActions.selectCharger : gameActions.selectUnit}
              onStartMovePreview={gameActions.startMovePreview}
              onStartAttackPreview={gameActions.startAttackPreview}
              onConfirmMove={gameActions.confirmMove}
              onCancelMove={gameActions.cancelMove}
              onShoot={gameActions.handleShoot}
              onCombatAttack={gameActions.handleCombatAttack}
              onCharge={gameActions.handleCharge}
              onMoveCharger={gameActions.moveCharger}
              onCancelCharge={gameActions.cancelCharge}
              onValidateCharge={gameActions.validateCharge}
              shootingSequenceState={shootingSequenceState}
              onShootingStepComplete={handleShootingStepComplete}
              onCancelShootingSequence={handleCancelShootingSequence}
            />
          </ErrorBoundary>
        </div>

        <footer className="game-footer">
          <GameStatus
            currentPlayer={gameState.currentPlayer}
            phase={gameState.phase}
            units={gameState.units}
            unitsMoved={gameState.unitsMoved}
            unitsCharged={gameState.unitsCharged}
            unitsAttacked={gameState.unitsAttacked}
          />
        </footer>
      </main>
    </div>
  );
};