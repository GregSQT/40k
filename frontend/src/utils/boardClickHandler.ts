// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;
let globalHexClickHandler: ((e: Event) => void) | null = null;

export function setupBoardClickHandler(callbacks: {
  onSelectUnit(unitId: number | null): void;
  onSkipUnit?(unitId: UnitId): void;
  onSkipShoot?(unitId: UnitId): void;
  onStartAttackPreview(shooterId: UnitId): void;
  onShoot(shooterId: UnitId, targetId: UnitId): void;
  onFightAttack(attackerId: UnitId, targetId: UnitId | null): void;
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

  const unitClickHandler = (e: Event) => {
    const { unitId, phase, mode, selectedUnitId, clickType } = (e as CustomEvent<{
      unitId: number;
      phase: string;
      mode: string;
      selectedUnitId: number | null;
      clickType?: 'left' | 'right';
    }>).detail;

    if (phase === 'move' && mode === 'select') {
      // AI_TURN.md MOVEMENT PHASE COMPLIANCE
      if (selectedUnitId === unitId) {
        if (clickType === 'right') {
          // Right click on active unit → Move cancelled (skip unit)
          callbacks.onSkipUnit?.(unitId);
        } else {
          // Left click on active unit → Move postponed (deselect)
          callbacks.onSelectUnit(null);
        }
      } else {
        // Click on different unit → Switch activation
        callbacks.onSelectUnit(unitId);
      }
    } else if (phase === 'shoot' && mode === 'select') {
      callbacks.onSelectUnit(unitId);
      callbacks.onStartAttackPreview(unitId);
    } else if (phase === 'shoot' && mode === 'attackPreview' && selectedUnitId != null) {
      if (selectedUnitId !== unitId) {
        callbacks.onShoot(selectedUnitId, unitId);
      } else {
        callbacks.onSelectUnit(null);
      }
    } else if (mode === 'movePreview') {
      callbacks.onConfirmMove();
    } else if (phase === 'fight' && selectedUnitId != null && selectedUnitId !== unitId) {
      callbacks.onFightAttack(selectedUnitId, unitId);
    } else if (phase === 'fight' && selectedUnitId === unitId) {
      callbacks.onFightAttack(selectedUnitId, null);
    } else {
      callbacks.onSelectUnit(unitId);
    }
  };

  globalClickHandler = unitClickHandler;
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
  
  const skipShootHandler = (e: Event) => {
    const { unitId } = (e as CustomEvent<{ unitId: number }>).detail;
    callbacks.onSkipShoot?.(unitId);
  };
  
  window.addEventListener('boardSkipShoot', skipShootHandler);
  
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
      // In Movement Phase, clicking green hex should directly move the unit
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
