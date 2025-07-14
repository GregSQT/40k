// src/hooks/useGameActions.ts
import { useCallback } from 'react';
import { GameState, UnitId, MovePreview, AttackPreview, Unit } from '../types/game';
import { shootingSequenceManager, ShootingSequenceState } from '../utils/ShootingSequenceManager';

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
  shootingSequenceState: ShootingSequenceState | null;
  setShootingSequenceState: (state: ShootingSequenceState | null) => void;
}

export const useGameActions = ({
  gameState,
  movePreview,
  attackPreview,
  actions,
  shootingSequenceState,
  setShootingSequenceState,
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
    // Prevent unit selection during shooting sequence
    if (shootingSequenceState?.isActive) {
      console.log("Cannot select units during shooting sequence");
      return;
    }

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

  // === DICE-BASED SHOOTING SYSTEM ===

interface ShootingResult {
  totalDamage: number;
  summary: {
    totalShots: number;
    hits: number;
    wounds: number;
    failedSaves: number;
  };
}

// Dice rolling function
const rollD6 = (): number => Math.floor(Math.random() * 6) + 1;

// Calculate wound target based on strength vs toughness
const calculateWoundTarget = (strength: number, toughness: number): number => {
  if (strength * 2 <= toughness) return 6;      // S*2 <= T: wound on 6+
  if (strength < toughness) return 5;           // S < T: wound on 5+
  if (strength === toughness) return 4;         // S = T: wound on 4+
  if (strength > toughness) return 3;           // S > T: wound on 3+
  if (strength * 2 >= toughness) return 2;     // S*2 >= T: wound on 2+
  return 6; // fallback
};

// Calculate save target accounting for AP and invulnerable saves
const calculateSaveTarget = (armorSave: number, invulSave: number, armorPenetration: number): number => {
  const modifiedArmor = armorSave + armorPenetration;
  
  // Use invulnerable save if it's better than modified armor save (and invul > 0)
  if (invulSave > 0 && invulSave < modifiedArmor) {
    return invulSave;
  }
  
  return modifiedArmor;
};

// Execute complete shooting sequence
const executeShootingSequence = (shooter: any, target: any): ShootingResult => {
  // Step 1: Number of shots
  const numberOfShots = shooter.RNG_NB || 1;
  
  let totalDamage = 0;
  let hits = 0;
  let wounds = 0;
  let failedSaves = 0;

  // Process each shot
  for (let shot = 1; shot <= numberOfShots; shot++) {
    // Step 2: Range check (already validated before calling)
    
    // Step 3: Hit roll
    const hitRoll = rollD6();
    const hitTarget = shooter.RNG_ATK || 4;
    const didHit = hitRoll >= hitTarget;
    
    if (!didHit) continue; // Miss - next shot
    hits++;
    
    // Step 4: Wound roll  
    const woundRoll = rollD6();
    const woundTarget = calculateWoundTarget(shooter.RNG_STR || 4, target.T || 4);
    const didWound = woundRoll >= woundTarget;
    
    if (!didWound) continue; // Failed to wound - next shot
    wounds++;
    
    // Step 5: Armor save
    const saveRoll = rollD6();
    const saveTarget = calculateSaveTarget(
      target.ARMOR_SAVE || 5, 
      target.INVUL_SAVE || 0, 
      shooter.RNG_AP || 0
    );
    const savedWound = saveRoll >= saveTarget;
    
    if (savedWound) continue; // Save successful - next shot
    failedSaves++;
    
    // Step 6: Inflict damage
    totalDamage += shooter.RNG_DMG || 1;
  }

  return {
    totalDamage,
    summary: {
      totalShots: numberOfShots,
      hits,
      wounds,
      failedSaves
    }
  };
};

  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    const shooter = findUnit(shooterId);
    const target = findUnit(targetId);
    if (!shooter || !target) return;

    console.log(`🎯 Starting visual dice-based shooting: ${shooter.name || `Unit ${shooterId}`} -> ${target.name || `Unit ${targetId}`}`);

    // Start the visual dice-based shooting sequence
    shootingSequenceManager.startSequence(
      shooter,
      target,
      // On state change callback
      (newState) => {
        setShootingSequenceState(newState);
      },
      // On sequence complete callback  
      (finalDamage) => {
        console.log(`💥 Shooting complete! Final damage: ${finalDamage}`);
        
        // Apply the calculated damage
        const currentHP = target.CUR_HP ?? target.HP_MAX;
        const newHP = Math.max(0, currentHP - finalDamage);
        
        if (newHP <= 0) {
          console.log(`💀 ${target.name || `Unit ${targetId}`} destroyed!`);
          actions.removeUnit(targetId);
        } else {
          console.log(`🩹 ${target.name || `Unit ${targetId}`} takes ${finalDamage} damage (${newHP}/${target.HP_MAX} HP remaining)`);
          actions.updateUnit(targetId, { CUR_HP: newHP });
        }

        // Mark shooter as having shot and reset UI state
        actions.addMovedUnit(shooterId);
        actions.setAttackPreview(null);
        actions.setSelectedUnitId(null);
        actions.setMode("select");
        
        // Clear shooting sequence state
        setShootingSequenceState(null);
      }
    );
  }, [findUnit, actions, setShootingSequenceState]);

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

  const handleShootingStepComplete = useCallback(() => {
    if (shootingSequenceState?.isActive) {
      shootingSequenceManager.nextStep();
    }
  }, [shootingSequenceState]);

  const cancelShootingSequence = useCallback(() => {
    shootingSequenceManager.cancelSequence();
    setShootingSequenceState(null);
  }, [setShootingSequenceState]);

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
    handleShootingStepComplete,
    cancelShootingSequence,
  };
};