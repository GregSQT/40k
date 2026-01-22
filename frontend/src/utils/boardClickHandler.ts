// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;
let globalHexClickHandler: ((e: Event) => void) | null = null;

export function setupBoardClickHandler(callbacks: {
  onSelectUnit(unitId: number | null): void;
  onSkipUnit?(unitId: UnitId): void;
  onSkipShoot?(unitId: UnitId, actionType?: 'wait' | 'action'): void;
  onStartAttackPreview(shooterId: UnitId): void;
  onShoot(shooterId: UnitId, targetId: UnitId): void;
  onCombatAttack(attackerId: UnitId, targetId: UnitId | null): void;
  onConfirmMove(): void;
  onCancelCharge?(): void;
  onCancelAdvance?(): void;
  onActivateCharge?(chargerId: UnitId): void;
  onActivateFight?(fighterId: UnitId): void;
  onValidateCharge?(chargerId: UnitId): void;
  onMoveCharger?(chargerId: UnitId, destCol: number, destRow: number): void;
  onChargeEnemyUnit?(chargerId: UnitId, enemyUnitId: UnitId): void;
  onStartMovePreview?(unitId: UnitId, col: number, row: number): void;
  onDirectMove?(unitId: UnitId, col: number, row: number): void;
  // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance action callbacks
  onAdvanceMove?(unitId: UnitId, destCol: number, destRow: number): void;
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

    // Ignore unit clicks in advancePreview mode - hex clicks are handled by hex handler
    if (mode === 'advancePreview') {
      return;
    }

    // Validate player context before processing clicks
    // Note: Actual player validation happens in useGameActions.selectUnit
    
    if (phase === 'move' && mode === 'select') {
      if (selectedUnitId === unitId) {
        if (clickType === 'right') {
          callbacks.onSkipUnit?.(unitId);
        } else {
          callbacks.onSelectUnit(null);
        }
      } else {
        callbacks.onSelectUnit(unitId);
      }
    } else if (phase === 'shoot' && mode === 'select') {
      console.log("  🎯 SHOOT SELECT MODE:", { selectedUnitId, unitId, clickType, hasOnSkipShoot: !!callbacks.onSkipShoot });
      if (selectedUnitId === unitId) {
        if (clickType === 'right') {
          console.log("    -> Right click on selected unit -> calling onSkipShoot");
          callbacks.onSkipShoot?.(unitId, 'action');
        } else {
          console.log("    -> Left click on selected unit -> calling onSelectUnit(null)");
          callbacks.onSelectUnit(null);
        }
      } else if (clickType === 'right' && selectedUnitId === null) {
        // Handle right click on unit when nothing is selected
        // This allows canceling activation of a unit that was just activated but backend deselecte
        // (e.g., unit with no valid targets - backend responds and deselects before right click arrives)
        console.log("    -> Right click on unit (no selection) -> calling onSkipShoot to cancel activation");
        callbacks.onSkipShoot?.(unitId, 'action');
      } else {
        console.log("    -> Click on different unit -> calling onSelectUnit");
        callbacks.onSelectUnit(unitId);
      }
      // Don't call onStartAttackPreview here - wait for backend response
      // Backend will return blinking_units (attackPreview) or allow_advance (advancePreview)
    } else if (phase === 'shoot' && mode === 'attackPreview' && selectedUnitId != null) {
      if (selectedUnitId === unitId) {
        // Click on active unit
        if (clickType === 'right') {
          // Right click: cancel shooting (skip)
          callbacks.onSkipShoot?.(unitId, 'action');
        } else {
          // Left click: postpone if hasn't shot, no effect if has shot
          callbacks.onSelectUnit(null);
        }
      } else {
        // Click on different unit - let backend handle via onSelectUnit
        callbacks.onSelectUnit(unitId);
      }
      return;
    } else if (phase === 'charge' && mode === 'select') {
      if (selectedUnitId === unitId && clickType === 'right') {
        callbacks.onSkipUnit?.(unitId);
      } else {
        if (callbacks.onActivateCharge) {
          callbacks.onActivateCharge(unitId);
        }
      }
      return; // Prevent fallthrough to other handlers
    } else if (phase === 'charge' && mode === 'chargePreview' && selectedUnitId !== null) {
      if (selectedUnitId === unitId) {
        if (clickType === 'right') {
          callbacks.onSkipUnit?.(unitId);
        } else {
          callbacks.onSelectUnit(null);
        }
      } else {
        // Click on enemy unit -> find adjacent hex and move charger
        if (callbacks.onChargeEnemyUnit) {
          callbacks.onChargeEnemyUnit(selectedUnitId, unitId);
        }
      }
      return; // Prevent fallthrough to other handlers
    } else if (mode === 'movePreview') {
      callbacks.onConfirmMove();
    } else if (phase === 'fight' && mode === 'select') {
      // Fight phase select mode - selecting a unit to activate
      callbacks.onSelectUnit(unitId);
      if (callbacks.onActivateFight) {
        callbacks.onActivateFight(unitId);
      }
    } else if (phase === 'fight' && mode === 'attackPreview' && selectedUnitId != null && selectedUnitId !== unitId) {
      // Fight phase attack preview - clicking on enemy to attack
      callbacks.onCombatAttack(selectedUnitId, unitId);
    } else if (phase === 'fight' && mode === 'attackPreview' && selectedUnitId === unitId) {
      // Fight phase attack preview - clicking on self (no-op or cancel)
      callbacks.onCombatAttack(selectedUnitId, null);
    } else {
      callbacks.onSelectUnit(unitId);
    }
  };

  globalClickHandler = unitClickHandler;
  window.addEventListener('boardUnitClick', globalClickHandler);
  
  // Remove existing charge cancel handler before adding new one
  const existingCancelHandler = (window as unknown as Record<string, unknown>).cancelChargeHandler as (() => void) | undefined;
  if (existingCancelHandler) {
    window.removeEventListener('boardCancelCharge', existingCancelHandler);
  }
  
  // Create new cancel handler and store reference
  const cancelChargeHandler = () => {
    callbacks.onCancelCharge?.();
  };
  (window as unknown as Record<string, unknown>).cancelChargeHandler = cancelChargeHandler;
  
  window.addEventListener('boardCancelCharge', cancelChargeHandler);

  // Remove existing advance cancel handler before adding new one
  const existingCancelAdvanceHandler = (window as unknown as Record<string, unknown>).cancelAdvanceHandler as (() => void) | undefined;
  if (existingCancelAdvanceHandler) {
    window.removeEventListener('boardCancelAdvance', existingCancelAdvanceHandler);
  }
  
  // Create new cancel advance handler and store reference
  const cancelAdvanceHandler = () => {
    callbacks.onCancelAdvance?.();
  };
  (window as unknown as Record<string, unknown>).cancelAdvanceHandler = cancelAdvanceHandler;
  
  window.addEventListener('boardCancelAdvance', cancelAdvanceHandler);
  
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

    console.log("HEX CLICK HANDLER:", { col, row, phase, mode, selectedUnitId });

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
  } else if (mode === 'advancePreview' && selectedUnitId !== null && phase === 'shoot') {
    // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance mode - clicking orange hex moves the unit
    console.log("  ✅ ADVANCE MOVE LOGIC -> calling onAdvanceMove");
    if (callbacks.onAdvanceMove) {
      callbacks.onAdvanceMove(selectedUnitId, col, row);
    }
  } else if (mode === 'movePreview') {
    callbacks.onConfirmMove();
    }
  };
  
  window.addEventListener('boardHexClick', globalHexClickHandler);
}

;(window as unknown as Record<string, unknown>).setupBoardClickHandler = setupBoardClickHandler;
