// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;
let globalHexClickHandler: ((e: Event) => void) | null = null;

export function setupBoardClickHandler(callbacks: {
  onSelectUnit(unitId: number | null): void;
  onStartAttackPreview(shooterId: UnitId): void;
  onShoot(shooterId: UnitId, targetId: UnitId): void;
  onCombatAttack(attackerId: UnitId, targetId: UnitId | null): void;
  onConfirmMove(): void;
  onCancelCharge?(): void;
  onValidateCharge?(chargerId: UnitId): void;
  onMoveCharger?(chargerId: UnitId, destCol: number, destRow: number): void;
  onStartMovePreview?(unitId: UnitId, col: number, row: number): void;
  onDirectMove?(unitId: UnitId, col: number, row: number): void;
}) {

  // Remove existing unit click handler
  if (globalClickHandler) {
    window.removeEventListener('boardUnitClick', globalClickHandler);
  }

  // Remove existing hex click handler
  if (globalHexClickHandler) {
    window.removeEventListener('boardHexClick', globalHexClickHandler);
  }

  globalClickHandler = (e: Event) => {
    const { unitId, phase, mode, selectedUnitId } = (e as CustomEvent<{
      unitId: number;
      phase: string;
      mode: string;
      selectedUnitId: number | null;
    }>).detail;

    if (phase === 'shoot' && mode === 'select') {
      callbacks.onSelectUnit(unitId);
      callbacks.onStartAttackPreview(unitId);
    } else if (phase === 'shoot' && mode === 'attackPreview' && selectedUnitId != null) {
      callbacks.onShoot(selectedUnitId, unitId);
    } else if (mode === 'movePreview') {
      // In movePreview mode, clicking any unit confirms the move
      callbacks.onConfirmMove();
    } else if (phase === 'combat' && selectedUnitId != null && selectedUnitId !== unitId) {
      // Combat phase: first unit selected, clicking on target (different unit)
      callbacks.onCombatAttack(selectedUnitId, unitId);
    } else if (phase === 'combat' && selectedUnitId === unitId) {
      // Combat phase: clicking on same unit cancels attack
      callbacks.onCombatAttack(selectedUnitId, null);
    } else {
      callbacks.onSelectUnit(unitId);
    }
  };

  window.addEventListener('boardUnitClick', globalClickHandler);
  
  // Remove existing charge cancel handler before adding new one
  const existingCancelHandler = (window as any).cancelChargeHandler;
  if (existingCancelHandler) {
    window.removeEventListener('boardCancelCharge', existingCancelHandler);
  }
  
  // Create new cancel handler and store reference
  const cancelChargeHandler = () => {
    callbacks.onCancelCharge?.();
  };
  (window as any).cancelChargeHandler = cancelChargeHandler;
  
  window.addEventListener('boardCancelCharge', cancelChargeHandler);
  
  globalHexClickHandler = (e: Event) => {
    const { col, row, phase, mode, selectedUnitId } = (e as CustomEvent<{
      col: number;
      row: number;
      phase: string;
      mode: string;
      selectedUnitId: number | null;
    }>).detail;

    if (mode === 'chargePreview' && selectedUnitId !== null) {
    if (callbacks.onMoveCharger) {
      try {
        callbacks.onMoveCharger(selectedUnitId, col, row);
      } catch (error) {
        console.error(`🟠 Error in onMoveCharger:`, error);
      }
    } else {
      console.error(`🟠 onMoveCharger callback is missing!`);
    }
    } else if (mode === 'select' && selectedUnitId !== null && phase === 'move') {
      // In move phase, clicking green hex should directly move the unit
      if (callbacks.onDirectMove) {
        callbacks.onDirectMove(selectedUnitId, col, row);
      } else if (callbacks.onStartMovePreview) {
        callbacks.onStartMovePreview(selectedUnitId, col, row);
        callbacks.onConfirmMove();
      }
    } else if (mode === 'movePreview') {
      callbacks.onConfirmMove();
    }
  };
  
  window.addEventListener('boardHexClick', globalHexClickHandler);
}

;(window as any).setupBoardClickHandler = setupBoardClickHandler;
