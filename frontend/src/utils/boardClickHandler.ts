// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;

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
}) {

  if (globalClickHandler) {
    window.removeEventListener('boardUnitClick', globalClickHandler);
  }

  globalClickHandler = (e: Event) => {
    console.log(`🖱️ boardClickHandler received event for unit:`, (e as CustomEvent).detail);
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
    console.log('🔥 boardCancelCharge event triggered');
    callbacks.onCancelCharge?.();
  };
  (window as any).cancelChargeHandler = cancelChargeHandler;
  
  window.addEventListener('boardCancelCharge', cancelChargeHandler);
  
  // Handle hex clicks
  const hexClickHandler = (e: Event) => {
    console.log(`🖱️ boardClickHandler received hex click:`, (e as CustomEvent).detail);
    const { col, row, phase, mode, selectedUnitId } = (e as CustomEvent<{
      col: number;
      row: number;
      phase: string;
      mode: string;
      selectedUnitId: number | null;
    }>).detail;

    if (mode === 'chargePreview' && selectedUnitId !== null) {
      console.log(`🟠 Calling onMoveCharger(${selectedUnitId}, ${col}, ${row}), callback exists: ${!!callbacks.onMoveCharger}`);
      if (callbacks.onMoveCharger) {
        callbacks.onMoveCharger(selectedUnitId, col, row);
        console.log(`🟠 onMoveCharger called successfully`);
      } else {
        console.error(`🟠 onMoveCharger callback is missing!`);
      }
    } else if (mode === 'select' && selectedUnitId !== null) {
      if (callbacks.onStartMovePreview) {
        callbacks.onStartMovePreview(selectedUnitId, col, row);
      }
    } else if (mode === 'movePreview') {
      callbacks.onConfirmMove();
    }
  };
  
  window.addEventListener('boardHexClick', hexClickHandler);
}

;(window as any).setupBoardClickHandler = setupBoardClickHandler;
