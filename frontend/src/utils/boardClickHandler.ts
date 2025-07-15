// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;

export function setupBoardClickHandler(callbacks: {
  onSelectUnit(unitId: number | null): void;
  onStartAttackPreview(shooterId: UnitId): void;
  onShoot(shooterId: UnitId, targetId: UnitId): void;
  onCombatAttack(attackerId: UnitId, targetId: UnitId | null): void;
}) {

  if (globalClickHandler) {
    window.removeEventListener('boardUnitClick', globalClickHandler);
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
    } else {
      callbacks.onSelectUnit(unitId);
    }
  };

  window.addEventListener('boardUnitClick', globalClickHandler);
}

;(window as any).setupBoardClickHandler = setupBoardClickHandler;
