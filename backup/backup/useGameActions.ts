// src/hooks/useGameActions.ts
import { useCallback } from 'react';
import { GameState, UnitId, MovePreview, AttackPreview, Unit } from '../types/game';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  actions: {
    setMode: (mode: GameState['mode']) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMovePreview: (preview: MovePreview | null) => void;
    setAttackPreview: (preview: AttackPreview | null) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
  };
}

export const useGameActions = ({
  gameState,
  movePreview,
  attackPreview,
  actions,
}: UseGameActionsParams) => {
  const { units, currentPlayer, phase, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked } = gameState;

  // Helper function to find unit by ID
  const findUnit = useCallback((unitId: UnitId) => {
    return units.find(u => u.id === unitId);
  }, [units]);

  // Helper function to check if unit is eligible for selection
  const isUnitEligible = useCallback((unit: Unit) => {
    if (unit.player !== currentPlayer) return false;

    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot":
        if (unitsMoved.includes(unit.id)) return false;
        const enemies = units.filter(u => u.player !== currentPlayer);
        return enemies.some(enemy => 
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) <= unit.RNG_RNG
        );
      case "charge":
        if (unitsCharged.includes(unit.id)) return false;
        const enemyUnits = units.filter(u => u.player !== currentPlayer);
        const isAdjacent = enemyUnits.some(enemy =>
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) === 1
        );
        const inRange = enemyUnits.some(enemy =>
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) <= unit.MOVE
        );
        return !isAdjacent && inRange;
      case "combat":
        if (unitsAttacked.includes(unit.id)) return false;
        const adjacentEnemies = units.filter(u => u.player !== currentPlayer);
        return adjacentEnemies.some(enemy =>
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) === 1
        );
      default:
        return false;
    }
  }, [units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked]);

  const selectUnit = useCallback((unitId: UnitId | null) => {
    if (unitId === null) {
      actions.setSelectedUnitId(null);
      actions.setMovePreview(null);
      actions.setAttackPreview(null);
      actions.setMode("select");
      return;
    }

    const unit = findUnit(unitId);
    console.log(`[useGameActions] Found unit:`, unit);
    
    if (!unit) {
      console.log(`[useGameActions] Unit ${unitId} not found in units array`);
      return;
    }
    
    const eligible = isUnitEligible(unit);
    console.log(`[useGameActions] Unit ${unitId} eligibility check:`, {
      eligible,
      phase,
      currentPlayer,
      unitPlayer: unit.player,
      unitsMoved,
      unitsCharged,
      unitsAttacked
    });
    
    // ⚠️ TEMPORARILY ALLOW ALL SELECTIONS FOR DEBUGGING
    if (!eligible) {
      console.log(`[useGameActions] Unit ${unitId} not eligible, but ALLOWING for debug`);
      // Don't return early - allow selection anyway for debugging
    }

    // Special handling for move phase - second click marks as moved
    if (phase === "move" && selectedUnitId === unitId) {
      actions.addMovedUnit(unitId);
      actions.setSelectedUnitId(null);
      actions.setMovePreview(null);
      actions.setMode("select");
      return;
    }

    // Special handling for shoot phase
    if (phase === "shoot") {
      // Always show the attack preview…
      actions.setMovePreview(null);
      actions.setAttackPreview({ unitId, col: unit.col, row: unit.row });
      actions.setMode("attackPreview");

      // …but only set the active shooter on the first click
      if (selectedUnitId === null) {
        actions.setSelectedUnitId(unitId);
      }
      return;
    }

    // Default selection
    actions.setSelectedUnitId(unitId);
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setMode("select");
  }, [findUnit, isUnitEligible, phase, selectedUnitId, actions, currentPlayer, unitsMoved, unitsCharged, unitsAttacked]);

  const selectCharger = useCallback((unitId: UnitId | null) => {
    if (unitId === null) {
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const unit = findUnit(unitId);
    if (!unit || !isUnitEligible(unit)) return;

    actions.setSelectedUnitId(unitId);
    actions.setMode("chargePreview");
  }, [findUnit, isUnitEligible, actions]);

  const startMovePreview = useCallback((unitId: UnitId, col: number, row: number) => {
    const unit = findUnit(unitId);
    if (!unit || !isUnitEligible(unit)) return;

    actions.setMovePreview({ unitId, destCol: col, destRow: row });
    actions.setMode("movePreview");
    actions.setAttackPreview(null);
  }, [findUnit, isUnitEligible, actions]);

  const startAttackPreview = useCallback((unitId: UnitId, col: number, row: number) => {
    actions.setAttackPreview({ unitId, col, row });
    actions.setMode("attackPreview");
    actions.setMovePreview(null);
  }, [actions]);

  const confirmMove = useCallback(() => {
    let movedUnitId: UnitId | null = null;

    if (gameState.mode === "movePreview" && movePreview) {
      actions.updateUnit(movePreview.unitId, {
        col: movePreview.destCol,
        row: movePreview.destRow,
      });
      movedUnitId = movePreview.unitId;
    } else if (gameState.mode === "attackPreview" && attackPreview) {
      movedUnitId = attackPreview.unitId;
    }

    if (movedUnitId !== null) {
      actions.addMovedUnit(movedUnitId);
    }

    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [gameState.mode, movePreview, attackPreview, actions]);

  const cancelMove = useCallback(() => {
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
    actions.setMode("select");
  }, [actions]);

  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    const shooter = findUnit(shooterId);
    const target = findUnit(targetId);
    if (!shooter || !target) return;

    // Calculate damage and apply it
    const newHP = (target.CUR_HP ?? target.HP_MAX) - (shooter.RNG_DMG ?? 1);
    
    if (newHP <= 0) {
      actions.removeUnit(targetId);
    } else {
      actions.updateUnit(targetId, { CUR_HP: newHP });
    }

    // Mark shooter as having shot
    actions.addMovedUnit(shooterId);
    actions.setAttackPreview(null);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [findUnit, actions]);

  const handleCombatAttack = useCallback((attackerId: UnitId, targetId: UnitId | null) => {
    if (targetId === null) {
      // Skip attack but mark as attacked
      actions.addAttackedUnit(attackerId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const attacker = findUnit(attackerId);
    const target = findUnit(targetId);
    if (!attacker || !target) return;

    // Check if units are adjacent
    const distance = Math.max(
      Math.abs(attacker.col - target.col),
      Math.abs(attacker.row - target.row)
    );
    if (distance !== 1) return;

    // Apply close combat damage
    const newHP = (target.CUR_HP ?? target.HP_MAX) - (attacker.CC_DMG ?? 1);
    
    if (newHP <= 0) {
      actions.removeUnit(targetId);
    } else {
      actions.updateUnit(targetId, { CUR_HP: newHP });
    }

    actions.addAttackedUnit(attackerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [findUnit, actions]);

  const handleCharge = useCallback((chargerId: UnitId, targetId: UnitId) => {
    console.log(`Charge! Unit ${chargerId} charges unit ${targetId}`);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions]);

  const moveCharger = useCallback((chargerId: UnitId, destCol: number, destRow: number) => {
    actions.updateUnit(chargerId, { col: destCol, row: destRow });
    actions.setMode("chargePreview");
  }, [actions]);

  const cancelCharge = useCallback(() => {
    actions.setMode("select");
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
  }, [actions]);

  const validateCharge = useCallback((chargerId: UnitId) => {
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions]);

  return {
    selectUnit,
    selectCharger,
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
  };
};