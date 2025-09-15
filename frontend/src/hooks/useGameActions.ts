// frontend/src/hooks/useGameActions.ts - AI_TURN.md Compliant Version
import { useCallback } from 'react';
import type { GameState, UnitId, Unit } from '../types/game';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: any | null;
  attackPreview: any | null;
  shootingPhaseState: any;
  boardConfig?: any;
  gameLog?: any;
  actions: {
    setMode: (mode: GameState['mode']) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMovePreview: (preview: any | null) => void;
    setAttackPreview: (preview: any | null) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    addFledUnit: (unitId: UnitId) => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
    initializeShootingPhase: () => void;
    updateShootingPhaseState: (updates: any) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: any | null) => void;
    setFightSubPhase?: (subPhase: any) => void;
    setFightActivePlayer?: (player: any) => void;
    setUnitChargeRoll?: (unitId: UnitId, roll: number) => void;
    resetUnitChargeRoll?: (unitId: UnitId) => void;
    showChargeRollPopup?: (unitId: UnitId, roll: number, tooLow: boolean) => void;
    resetChargeRolls?: () => void;
  };
}

  export const useGameActions = ({
    gameState,
    movePreview,
    attackPreview,
    shootingPhaseState,
    boardConfig,
    gameLog,
    actions,
  }: UseGameActionsParams) => {
    
  // AI_TURN.md: Single source of truth eligibility function
  const isUnitEligible = useCallback((unit: Unit): boolean => {
    const { phase, currentPlayer, unitsMoved = [], unitsCharged = [], unitsAttacked = [], unitsFled = [] } = gameState;
    
    // AI_TURN.md: Universal eligibility checks
    if ((unit.HP_CUR ?? unit.HP_MAX) <= 0) return false;
    if (unit.player !== currentPlayer) return false;
    
    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot":
        return !unitsMoved.includes(unit.id) && !unitsFled.includes(unit.id);
      case "charge":
        return !unitsCharged.includes(unit.id) && !unitsFled.includes(unit.id);
      case "fight":
        return !unitsAttacked.includes(unit.id);
      default:
        return false;
    }
  }, [gameState]);

  // AI_TURN.md: Simple unit selection with step counting
  const selectUnit = useCallback((unitId: UnitId | null) => {    
    if (unitId === null) {
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const unit = gameState.units.find(u => u.id === unitId);
    
    // AI_TURN.md: Strict player validation - only current player units selectable
    if (!unit || unit.player !== gameState.currentPlayer || !isUnitEligible(unit)) {
      console.log(`[AI_TURN.md] Blocked selection of unit ${unitId}: player=${unit?.player}, currentPlayer=${gameState.currentPlayer}, eligible=${unit ? isUnitEligible(unit) : false}`);
      return;
    }
    
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
    let movedUnitId: UnitId | null = null;

    if (gameState.mode === "movePreview" && movePreview) {
      const unit = gameState.units.find(u => u.id === movePreview.unitId);
      if (unit && gameState.phase === "move") {
        // Check for flee detection
        const enemyUnits = gameState.units.filter(u => u.player !== unit.player);
        const wasAdjacentToEnemy = enemyUnits.some(enemy => 
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) === 1
        );
        
        if (wasAdjacentToEnemy) {
          const willBeAdjacentToEnemy = enemyUnits.some(enemy => 
            Math.max(Math.abs(movePreview.destCol - enemy.col), Math.abs(movePreview.destRow - enemy.row)) === 1
          );
          
          if (!willBeAdjacentToEnemy) {
            actions.addFledUnit(movePreview.unitId);
          }
        }
      }
      
      actions.updateUnit(movePreview.unitId, {
        col: movePreview.destCol,
        row: movePreview.destRow,
      });
      movedUnitId = movePreview.unitId;
    }

    if (movedUnitId !== null) {
      actions.addMovedUnit(movedUnitId);
    }

    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [gameState, movePreview, actions]);

  const cancelMove = useCallback(() => {
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setMode("select");
  }, [actions]);

  // Placeholder implementations for other actions
  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    // AI_TURN.md compliant shooting implementation
  }, []);

  const handleFightAttack = useCallback((attackerId: UnitId, targetId: UnitId | null) => {
    // AI_TURN.md compliant fight implementation
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
    handleFightAttack,
    handleCharge,
    moveCharger,
    cancelCharge,
    validateCharge,
    isUnitEligible,
    getChargeDestinations,
  };
};