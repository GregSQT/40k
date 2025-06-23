// src/components/GameBoard.tsx
import React from 'react';
import Board from './Board'; // Votre composant Board existant
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
  // Ce composant sert de wrapper pour votre composant Board existant
  // Il peut ajouter de la logique supplémentaire si nécessaire
  
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
        onSelectUnit={props.onSelectUnit}
        onStartMovePreview={props.onStartMovePreview}
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