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
}

;(window as any).setupBoardClickHandler = setupBoardClickHandler;
