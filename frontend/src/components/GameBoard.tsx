// src/components/GameBoard.tsx
import React from 'react';
import BoardPvp from './BoardPvp';
//import { BoardReplay } from './BoardReplay';
//import { TurnPhaseTracker } from './TurnPhaseTracker';
import type { Unit, GameState, MovePreview, AttackPreview, UnitId, ShootingPhaseState, TargetPreview, FightSubPhase, PlayerId } from '../types';
//import { setupBoardClickHandler } from '../utils/boardClickHandler';


interface GameBoardProps {
  units: Unit[];
  selectedUnitId: UnitId | null;
  eligibleUnitIds: number[];
  shootingActivationQueue?: Unit[];
  activeShootingUnit?: Unit | null;
  phase: GameState['phase'];
  mode: GameState['mode'];
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  currentPlayer: GameState['currentPlayer'];
  unitsMoved: UnitId[];
  unitsCharged: UnitId[];
  unitsAttacked: UnitId[];
  unitsFled: UnitId[];
  fightSubPhase?: FightSubPhase;
  fightActivePlayer?: PlayerId;
  currentTurn: number;
  gameState: GameState;
  maxTurns?: number;
  getChargeDestinations: (unitId: UnitId) => { col: number; row: number }[];
  onSelectUnit: (id: UnitId | null) => void;
  onStartMovePreview: (unitId: UnitId, col: number, row: number) => void;
  onDirectMove: (unitId: UnitId, col: number, row: number) => void;
  onStartAttackPreview: (unitId: UnitId, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: UnitId, targetId: UnitId) => void;
  onFightAttack: (attackerId: UnitId, targetId: UnitId | null) => void;
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
  
    // Remove problematic useEffect - setupBoardClickHandler will be handled by BoardPvp directly
  
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

  const handleDirectMove = (unitId: number | string, col: number | string, row: number | string) => {
    console.log("GameBoard handleDirectMove called:", { unitId, col, row });
    
    const numUnitId = typeof unitId === 'string' ? parseInt(unitId, 10) : unitId;
    const numCol = typeof col === 'string' ? parseInt(col, 10) : col;
    const numRow = typeof row === 'string' ? parseInt(row, 10) : row;
    
    console.log("GameBoard parsed values:", { numUnitId, numCol, numRow });
    console.log("GameBoard calling props.onDirectMove...");
    
    if (!isNaN(numUnitId) && !isNaN(numCol) && !isNaN(numRow)) {
      props.onDirectMove(numUnitId, numCol, numRow);
    } else {
      console.error("GameBoard: Invalid parsed values, not calling props.onDirectMove");
    }
  };

  const BoardComponent = BoardPvp;
  
  return (
    <div className="game-board w-full flex flex-col">
      <BoardComponent
        units={props.units}
        selectedUnitId={props.selectedUnitId}
        eligibleUnitIds={props.eligibleUnitIds}
        shootingActivationQueue={props.shootingActivationQueue}
        activeShootingUnit={props.activeShootingUnit}
        phase={props.phase}
        mode={props.mode || "select"}
        movePreview={props.movePreview}
        attackPreview={props.attackPreview}
        currentPlayer={props.currentPlayer || 0}
        unitsMoved={props.unitsMoved}
        unitsCharged={props.unitsCharged}
        unitsAttacked={props.unitsAttacked}
        unitsFled={props.unitsFled}
        fightSubPhase={props.fightSubPhase}
        fightActivePlayer={props.fightActivePlayer}
        gameState={props.gameState}
        onSelectUnit={handleSelectUnit}
        onStartMovePreview={handleStartMovePreview}
        onDirectMove={handleDirectMove}
        onStartAttackPreview={props.onStartAttackPreview}
        onConfirmMove={props.onConfirmMove}
        onCancelMove={props.onCancelMove}
        onShoot={props.onShoot}
        onFightAttack={props.onFightAttack}
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