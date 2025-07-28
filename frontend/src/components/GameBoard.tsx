// src/components/GameBoard.tsx
import React from 'react';
import Board from './Board';
import { TurnPhaseTracker } from './TurnPhaseTracker';
import { Unit, GameState, MovePreview, AttackPreview, UnitId, ShootingPhaseState, TargetPreview, CombatSubPhase, PlayerId } from '../types/game';
import { setupBoardClickHandler } from '../utils/boardClickHandler';


interface GameBoardProps {
  units: Unit[];
  selectedUnitId: UnitId | null;
  eligibleUnitIds: number[];
  phase: GameState['phase'];
  mode: GameState['mode'];
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  currentPlayer: GameState['currentPlayer'];
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  unitsFled: UnitId[];
  combatSubPhase?: CombatSubPhase; // NEW
  combatActivePlayer?: PlayerId; // NEW
  currentTurn: number;
  gameState: GameState;
  maxTurns?: number;
  getChargeDestinations: (unitId: UnitId) => { col: number; row: number }[];
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
  shootingPhaseState: ShootingPhaseState;
  targetPreview: TargetPreview | null;
  onCancelTargetPreview: () => void;
  chargeRollPopup?: { unitId: number; roll: number; tooLow: boolean; timestamp: number } | null;
}

export const GameBoard: React.FC<GameBoardProps> = (props) => {
  // Type-safe wrapper for Board component
  // Convert string/number IDs to proper number type for Board component
  
    React.useEffect(() => {
      setupBoardClickHandler({
        onSelectUnit: props.onSelectUnit,
        onStartAttackPreview: (shooterId) => {
          const unit = props.units.find(u => u.id === shooterId);
          if (unit) {
            props.onStartAttackPreview(shooterId, unit.col, unit.row);
          }
        },
        onShoot:        props.onShoot,
        onCombatAttack: props.onCombatAttack,
        onConfirmMove:  props.onConfirmMove,
        onCancelCharge: props.onCancelCharge,
        onValidateCharge: props.onValidateCharge,
        onMoveCharger:    props.onMoveCharger
      });
    }, [
      props.onSelectUnit,
      props.onStartAttackPreview,
      props.onShoot,
      props.onCombatAttack,
      props.onConfirmMove,
      props.onCancelCharge,
      props.onValidateCharge,
      props.onMoveCharger,
      props.units
    ]);



  
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
    <div className="game-board w-full flex flex-col">
      <Board
        units={props.units}
        selectedUnitId={props.selectedUnitId}
        eligibleUnitIds={props.eligibleUnitIds}
        phase={props.phase}
        mode={props.mode}
        movePreview={props.movePreview}
        attackPreview={props.attackPreview}
        currentPlayer={props.currentPlayer}
        unitsMoved={props.unitsMoved}
        unitsCharged={props.unitsCharged}
        unitsAttacked={props.unitsAttacked}
        unitsFled={props.unitsFled}
        combatSubPhase={props.combatSubPhase}
        combatActivePlayer={props.combatActivePlayer}
        gameState={props.gameState}
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
        shootingPhaseState={props.shootingPhaseState}
        targetPreview={props.targetPreview}
        onCancelTargetPreview={props.onCancelTargetPreview}
        chargeRollPopup={props.chargeRollPopup}
        getChargeDestinations={props.getChargeDestinations}
      />
    </div>
  );
};
