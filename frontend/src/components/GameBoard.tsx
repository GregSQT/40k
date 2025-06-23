// src/components/GameBoard.tsx
import React from 'react';
import Board from './Board';
import { Unit, GameState, MovePreview, AttackPreview, UnitId } from '../types/game';

interface GameBoardProps {
  units: Unit[];
  selectedUnitId: UnitId | null;
  phase: GameState['phase'];
  mode: GameState['mode'];
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  currentPlayer: GameState['currentPlayer'];
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  onSelectUnit: (id: UnitId | null) => void;
  onStartMovePreview: (unitId: UnitId, col: number, row: number) => void;
  onStartAttackPreview: (unitId: UnitId, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: UnitId, targetId: UnitId) => void;
  onCombatAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
  onCharge: (chargerId: UnitId, targetId: UnitId) => void;
  onMoveCharger: (chargerId: UnitId, destCol: number, destRow: number) => void;
  onCancelCharge: () => void;
  onValidateCharge: (chargerId: UnitId) => void;
}

export const GameBoard: React.FC<GameBoardProps> = (props) => {
  // Type-safe wrapper for Board component
  // Convert string/number IDs to proper number type for Board component
  
  const handleSelectUnit = (id: number | string | null) => {
    if (typeof id === 'string') {
      const numId = parseInt(id, 10);
      props.onSelectUnit(isNaN(numId) ? null : numId);
    } else {
      props.onSelectUnit(id);
    }
  };
  
  const handleStartMovePreview = (unitId: number | string, col: number | string, row: number | string) => {
    const numUnitId = typeof unitId === 'string' ? parseInt(unitId, 10) : unitId;
    const numCol = typeof col === 'string' ? parseInt(col, 10) : col;
    const numRow = typeof row === 'string' ? parseInt(row, 10) : row;
    
    if (!isNaN(numUnitId) && !isNaN(numCol) && !isNaN(numRow)) {
      props.onStartMovePreview(numUnitId, numCol, numRow);
    }
  };
  
  return (
    <div className="game-board">
      <Board
        units={props.units}
        selectedUnitId={props.selectedUnitId}
        phase={props.phase}
        mode={props.mode}
        movePreview={props.movePreview}
        attackPreview={props.attackPreview}
        currentPlayer={props.currentPlayer}
        unitsMoved={props.unitsMoved}
        unitsCharged={props.unitsCharged}
        unitsAttacked={props.unitsAttacked}
        onSelectUnit={handleSelectUnit}
        onStartMovePreview={handleStartMovePreview}
        onStartAttackPreview={props.onStartAttackPreview}
        onConfirmMove={props.onConfirmMove}
        onCancelMove={props.onCancelMove}
        onShoot={props.onShoot}
        onCombatAttack={props.onCombatAttack}
        onCharge={props.onCharge}
        onMoveCharger={props.onMoveCharger}
        onCancelCharge={props.onCancelCharge}
        onValidateCharge={props.onValidateCharge}
      />
    </div>
  );
};
