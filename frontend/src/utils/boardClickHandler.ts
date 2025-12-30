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
  onCombatAttack(attackerId: UnitId, targetId: UnitId | null): void;
  onConfirmMove(): void;
  onCancelCharge?(): void;
  onCancelAdvance?(): void;
  onActivateCharge?(chargerId: UnitId): void;
  onActivateFight?(fighterId: UnitId): void;
  onValidateCharge?(chargerId: UnitId): void;
  onMoveCharger?(chargerId: UnitId, destCol: number, destRow: number): void;
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
      callbacks.onSelectUnit(unitId);
      // Don't call onStartAttackPreview here - wait for backend response
      // Backend will return blinking_units (attackPreview) or allow_advance (advancePreview)
    } else if (phase === 'shoot' && mode === 'attackPreview' && selectedUnitId != null) {
      if (selectedUnitId !== unitId) {
        callbacks.onShoot(selectedUnitId, unitId);  // Execute immediately
      } else {
        return;
      }
    } else if (phase === 'charge' && mode === 'select') {
      console.log("  ✅ CHARGE SELECT LOGIC TRIGGERED");
      if (selectedUnitId === unitId && clickType === 'right') {
        console.log("    - Right click on selected unit → skip charge");
        callbacks.onSkipUnit?.(unitId);
      } else {
        console.log("    - Activating charge unit:", unitId);
        console.log("    - onActivateCharge callback exists?", !!callbacks.onActivateCharge);
        callbacks.onSelectUnit(unitId);
        if (callbacks.onActivateCharge) {
          console.log("    - Calling onActivateCharge with unitId:", unitId);
          callbacks.onActivateCharge(unitId);
          console.log("    - onActivateCharge call completed");
        } else {
          console.error("    - ERROR: onActivateCharge callback is undefined!");
        }
      }
    } else if (mode === 'movePreview') {
      console.log("  ✅ MOVE PREVIEW LOGIC → calling onConfirmMove");
      callbacks.onConfirmMove();
    } else if (phase === 'fight' && mode === 'select') {
      // Fight phase select mode - selecting a unit to activate
      console.log("  ✅ FIGHT SELECT LOGIC → calling onSelectUnit and onActivateFight");
      callbacks.onSelectUnit(unitId);
      if (callbacks.onActivateFight) {
        console.log("    - Calling onActivateFight with unitId:", unitId);
        callbacks.onActivateFight(unitId);
      } else {
        console.error("    - ERROR: onActivateFight callback is undefined!");
      }
    } else if (phase === 'fight' && mode === 'attackPreview' && selectedUnitId != null && selectedUnitId !== unitId) {
      // Fight phase attack preview - clicking on enemy to attack
      console.log("  ✅ FIGHT ATTACK LOGIC (different unit) → calling onCombatAttack");
      callbacks.onCombatAttack(selectedUnitId, unitId);
    } else if (phase === 'fight' && mode === 'attackPreview' && selectedUnitId === unitId) {
      // Fight phase attack preview - clicking on self (no-op or cancel)
      console.log("  ✅ FIGHT ATTACK LOGIC (same unit) → calling onCombatAttack");
      callbacks.onCombatAttack(selectedUnitId, null);
    } else {
      console.log("  ✅ DEFAULT LOGIC → calling onSelectUnit");
      console.log("    - No specific condition matched");
      console.log("    - Expected for shooting: phase='shoot' && mode='select'");
      console.log("    - Actual: phase='" + phase + "' && mode='" + mode + "'");
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
    console.log("  ✅ ADVANCE MOVE LOGIC → calling onAdvanceMove");
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
