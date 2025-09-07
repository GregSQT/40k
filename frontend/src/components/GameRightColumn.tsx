// frontend/src/components/GameRightColumn.tsx
import React from 'react';
import { ErrorBoundary } from './ErrorBoundary';
import { UnitStatusTable } from './UnitStatusTable';
import { GameLog } from './GameLog';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { Unit } from '../types/game';

interface GameRightColumnProps {
  gameState: {
    units: Unit[];
    selectedUnitId: number | null;
    currentTurn: number;
    phase: string;
  };
  clickedUnitId: number | null;
  onSelectUnit: (unitId: number) => void;
  gameLog: {
    events: any[];
    getElapsedTime: (timestamp: Date) => string;
  };
}

export const GameRightColumn: React.FC<GameRightColumnProps> = ({
  gameState,
  clickedUnitId,
  onSelectUnit,
  gameLog
}) => {
  return (
    <>
      <TurnPhaseTracker 
        currentTurn={gameState.currentTurn} 
        currentPhase={gameState.phase}
        className="turn-phase-tracker-right"
      />
      <ErrorBoundary fallback={<div>Failed to load player 0 status</div>}>
        <UnitStatusTable
          units={gameState.units}
          player={0}
          selectedUnitId={gameState.selectedUnitId}
          clickedUnitId={clickedUnitId}
          onSelectUnit={onSelectUnit}
        />
      </ErrorBoundary>

      <ErrorBoundary fallback={<div>Failed to load player 1 status</div>}>
        <UnitStatusTable
          units={gameState.units}
          player={1}
          selectedUnitId={gameState.selectedUnitId}
          clickedUnitId={clickedUnitId}
          onSelectUnit={onSelectUnit}
        />
      </ErrorBoundary>

      {/* Game Log Component */}
      <ErrorBoundary fallback={<div>Failed to load game log</div>}>
        <GameLog 
          events={gameLog.events}
          getElapsedTime={gameLog.getElapsedTime}
        />
      </ErrorBoundary>
    </>
  );
};