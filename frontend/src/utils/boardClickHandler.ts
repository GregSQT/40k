// frontend/src/utils/boardClickHandler.ts

import type { UnitId } from '../types/game';

let globalClickHandler: ((e: Event) => void) | null = null;
let globalHexClickHandler: ((e: Event) => void) | null = null;

export function setupBoardClickHandler(callbacks: {
  onSelectUnit(unitId: number | null): void;
  onSkipUnit?(unitId: UnitId): void;
  onSkipShoot?(unitId: UnitId): void;
  onStartAttackPreview(shooterId: UnitId): void;
  onStartTargetPreview?(shooterId: UnitId, targetId: UnitId): void;
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

  const unitClickHandler = (e: Event) => {
    const { unitId, phase, mode, selectedUnitId, clickType } = (e as CustomEvent<{
      unitId: number;
      phase: string;
      mode: string;
      selectedUnitId: number | null;
      clickType?: 'left' | 'right';
    }>).detail;

    console.log(`🔥 BOARD CLICK HANDLER | Unit : ${unitId} | Phase : ${phase} | Mode : ${mode} | Selected : ${selectedUnitId} | Click : ${clickType} |`);

    if (phase === 'move' && mode === 'select') {
      if (selectedUnitId === unitId) {
        if (clickType === 'right') {
          console.log("    - Right click on active unit → calling onSkipUnit");
          callbacks.onSkipUnit?.(unitId);
        } else {
          console.log("    - Left click on active unit → calling onSelectUnit(null)");
          callbacks.onSelectUnit(null);
        }
      } else {
        callbacks.onSelectUnit(unitId);
      }
    } else if (phase === 'shoot' && mode === 'select') {
      console.log("  ✅ SHOOTING SELECT LOGIC TRIGGERED");
      console.log("    - Calling onSelectUnit with unitId:", unitId);
      callbacks.onSelectUnit(unitId);
      console.log("    - Calling onStartAttackPreview with unitId:", unitId);
      callbacks.onStartAttackPreview(unitId);
    } else if (phase === 'shoot' && mode === 'attackPreview' && selectedUnitId != null) {
      console.log("  ✅ SHOOTING ATTACK PREVIEW LOGIC");
      if (selectedUnitId !== unitId) {
        console.log("    - First click on enemy target → calling onStartTargetPreview");
        if (callbacks.onStartTargetPreview) {
          callbacks.onStartTargetPreview(selectedUnitId, unitId);
        }
      } else {
        console.log("    - Left click on active unit → no effect");
        return;
      }
    } else if (phase === 'shoot' && mode === 'targetPreview' && selectedUnitId != null) {
      console.log("  ✅ SHOOTING TARGET PREVIEW LOGIC");
      console.log("    - Second click on target → calling onShoot");
      callbacks.onShoot(selectedUnitId, unitId);
    } else if (mode === 'movePreview') {
      console.log("  ✅ MOVE PREVIEW LOGIC → calling onConfirmMove");
      callbacks.onConfirmMove();
    } else if (phase === 'fight' && selectedUnitId != null && selectedUnitId !== unitId) {
      console.log("  ✅ FIGHT LOGIC (different unit) → calling onCombatAttack");
      callbacks.onCombatAttack(selectedUnitId, unitId);
    } else if (phase === 'fight' && selectedUnitId === unitId) {
      console.log("  ✅ FIGHT LOGIC (same unit) → calling onCombatAttack");
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
      console.log("🎯 MOVEMENT LOGIC TRIGGERED:", { mode, selectedUnitId, phase });
      console.log("🎯 onDirectMove callback exists:", !!callbacks.onDirectMove);
      
      if (callbacks.onDirectMove) {
        console.log("🎯 CALLING onDirectMove with:", selectedUnitId, col, row);
        callbacks.onDirectMove(selectedUnitId, col, row);
      } else if (callbacks.onStartMovePreview) {
        console.log("🎯 FALLBACK: Using onStartMovePreview");
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
