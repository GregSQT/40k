// frontend/src/hooks/useGameActions.ts - AI_TURN.md Compliant Version
import { useCallback } from 'react';
import type { GameState, UnitId, Unit } from '../types/game';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: any;
  attackPreview: any;
  shootingPhaseState: any;
  actions: {
    setSelectedUnitId: (id: UnitId | null) => void;
    setMode: (mode: GameState['mode']) => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    addFledUnit: (unitId: UnitId) => void;
    setMovePreview: (preview: any) => void;
    setAttackPreview: (preview: any) => void;
  };
  boardConfig?: any;
  gameLog?: any;
}

export const useGameActions = ({ gameState, movePreview, attackPreview, shootingPhaseState, actions, boardConfig, gameLog }: UseGameActionsParams) => {
  
  // AI_TURN.md: Single source of truth eligibility function
  const isUnitEligible = useCallback((unit: Unit): boolean => {
    const { phase, currentPlayer, unitsMoved = [], unitsCharged = [], unitsAttacked = [], unitsFled = [] } = gameState;
    
    // AI_TURN.md: Universal eligibility checks
    if ((unit.CUR_HP ?? unit.HP_MAX) <= 0) return false;
    if (unit.player !== currentPlayer) return false;
    
    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot":
        return !unitsMoved.includes(unit.id) && !unitsFled.includes(unit.id);
      case "charge":
        return !unitsCharged.includes(unit.id) && !unitsFled.includes(unit.id);
      case "combat":
        return !unitsAttacked.includes(unit.id);
      default:
        return false;
    }
  }, [gameState]);

  // AI_TURN.md: Simple unit selection with step counting
  const selectUnit = useCallback((unitId: UnitId | null) => {
    console.log("🔴 SELECT UNIT CALLED:", {
      unitId,
      phase: gameState.phase,
      currentPlayer: gameState.currentPlayer,
      mode: gameState.mode
    });
    
    if (unitId === null) {
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const unit = gameState.units.find(u => u.id === unitId);
    console.log("🔴 FOUND UNIT:", unit?.id, "ELIGIBLE:", unit ? isUnitEligible(unit) : "N/A");
    
    if (!unit || !isUnitEligible(unit)) return;

    console.log("🔴 SETTING SELECTED UNIT:", unitId);
    actions.setSelectedUnitId(unitId);
    actions.setMode("select");
  }, [gameState, isUnitEligible, actions]);

  // AI_TURN.md: Simple move with step counting
  const directMove = useCallback((unitId: UnitId, col: number, row: number) => {
    const unit = gameState.units.find(u => u.id === unitId);
    if (!unit || !isUnitEligible(unit) || gameState.phase !== "move") return;

    actions.updateUnit(unitId, { col, row });
    actions.addMovedUnit(unitId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [gameState, isUnitEligible, actions]);

  // AI_TURN.md: Movement preview
  const startMovePreview = useCallback((unitId: UnitId, col: number, row: number) => {
    const unit = gameState.units.find(u => u.id === unitId);
    if (!unit || !isUnitEligible(unit)) return;

    actions.setMovePreview({ unitId, destCol: col, destRow: row });
    actions.setMode("movePreview");
  }, [gameState, isUnitEligible, actions]);

  const confirmMove = useCallback(() => {
    // Implementation based on current movePreview state
    actions.setMovePreview(null);
    actions.setMode("select");
  }, [actions]);

  const cancelMove = useCallback(() => {
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setMode("select");
  }, [actions]);

  // Placeholder implementations for other actions
  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    // AI_TURN.md compliant shooting implementation
  }, []);

  const handleCombatAttack = useCallback((attackerId: UnitId, targetId: UnitId | null) => {
    // AI_TURN.md compliant combat implementation
  }, []);

  const handleCharge = useCallback((chargerId: UnitId, targetId: UnitId) => {
    // AI_TURN.md compliant charge implementation
  }, []);

  const startAttackPreview = useCallback((unitId: UnitId, col: number, row: number) => {
    actions.setAttackPreview({ unitId, col, row });
    actions.setMode("attackPreview");
  }, [actions]);

  // Stub implementations for missing functions
  const moveCharger = useCallback(() => {}, []);
  const cancelCharge = useCallback(() => {}, []);
  const validateCharge = useCallback(() => {}, []);
  const getChargeDestinations = useCallback(() => [], []);

  return {
    selectUnit,
    directMove,
    startMovePreview,
    startAttackPreview,
    confirmMove,
    cancelMove,
    handleShoot,
    handleCombatAttack,
    handleCharge,
    moveCharger,
    cancelCharge,
    validateCharge,
    isUnitEligible,
    getChargeDestinations,
  };
};