// src/hooks/useGameActions.ts
import { useCallback } from 'react';
import { GameState, UnitId, MovePreview, AttackPreview, Unit, ShootingPhaseState, TargetPreview } from '../types/game';
import { calculateHitProbability, calculateWoundProbability, calculateSaveProbability, calculateOverallProbability } from '../utils/probabilityCalculator';
import { areUnitsAdjacent, isUnitInRange } from '../utils/gameHelpers';
import { singleShotSequenceManager } from '../utils/ShootingSequenceManager';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
  actions: {
    setMode: (mode: GameState['mode']) => void;
    setSelectedUnitId: (id: UnitId | null) => void;
    setMovePreview: (preview: MovePreview | null) => void;
    setAttackPreview: (preview: AttackPreview | null) => void;
    addMovedUnit: (unitId: UnitId) => void;
    addChargedUnit: (unitId: UnitId) => void;
    addAttackedUnit: (unitId: UnitId) => void;
    addFledUnit: (unitId: UnitId) => void;  // NEW
    updateUnit: (unitId: UnitId, updates: Partial<Unit>) => void;
    removeUnit: (unitId: UnitId) => void;
    initializeShootingPhase: () => void;
    updateShootingPhaseState: (updates: Partial<ShootingPhaseState>) => void;
    decrementShotsLeft: (unitId: UnitId) => void;
    setTargetPreview: (preview: TargetPreview | null) => void;
  };
}

export const useGameActions = ({
  gameState,
  movePreview,
  attackPreview,
  shootingPhaseState,
  actions,
}: UseGameActionsParams) => {
  const { units, currentPlayer, phase, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled } = gameState;

  // DEBUG: Log fled units state
  console.log(`[DEBUG] Phase: ${phase}, Player: ${currentPlayer}, UnitsFled:`, unitsFled, 'UnitsMoved:', unitsMoved);

  // Helper function to find unit by ID
  const findUnit = useCallback((unitId: UnitId) => {
    return units.find(u => u.id === unitId);
  }, [units]);

  // Helper function to check if unit is eligible for selection
  const isUnitEligible = useCallback((unit: Unit) => {
    if (unit.player !== currentPlayer) return false;

    // Get enemy units once for efficiency
    const enemyUnits = units.filter(u => u.player !== currentPlayer);

    switch (phase) {
      case "move":
        const moveEligible = !unitsMoved.includes(unit.id);
        console.log(`🔍 Unit ${unit.name} (${unit.id}) move eligibility: ${moveEligible} (moved: ${unitsMoved.includes(unit.id)})`);
        return moveEligible;
      case "shoot":
        if (unitsMoved.includes(unit.id)) {
          console.log(`❌ Unit ${unit.name} (${unit.id}) ineligible - already moved this phase`);
          return false;
        }
        // NEW RULE: Units that fled cannot shoot
        if (unitsFled.includes(unit.id)) {
          console.log(`🏃 Unit ${unit.name} (${unit.id}) ineligible - fled this turn`);
          return false;
        }
        // Check if unit is adjacent to any enemy (engaged in combat)
        const hasAdjacentEnemyShoot = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
        if (hasAdjacentEnemyShoot) return false;
        // Check if unit has enemies in shooting range that are NOT adjacent to friendly units
        const friendlyUnits = units.filter(u => u.player === unit.player && u.id !== unit.id);
        return enemyUnits.some(enemy => {
          if (!isUnitInRange(unit, enemy, unit.RNG_RNG)) return false;
          // Rule 2: Cannot shoot enemy units adjacent to friendly units
          const isEnemyAdjacentToFriendly = friendlyUnits.some(friendly => 
            Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
          );
          return !isEnemyAdjacentToFriendly;
        });
      case "charge":
        if (unitsCharged.includes(unit.id)) {
          console.log(`❌ Unit ${unit.name} (${unit.id}) ineligible - already charged this phase`);
          return false;
        }
        // NEW RULE: Units that fled cannot charge
        if (unitsFled.includes(unit.id)) {
          console.log(`🏃 Unit ${unit.name} (${unit.id}) ineligible - fled this turn`);
          return false;
        }
        const isAdjacent = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
        const inRange = enemyUnits.some(enemy => isUnitInRange(unit, enemy, unit.MOVE));
        const chargeEligible = !isAdjacent && inRange;
        console.log(`⚔️ Unit ${unit.name} (${unit.id}) charge eligibility: ${chargeEligible} (adjacent: ${isAdjacent}, inRange: ${inRange})`);
        return chargeEligible;
      case "combat":
        if (unitsAttacked.includes(unit.id)) return false;
        if (unit.CC_RNG === undefined) {
          throw new Error('unit.CC_RNG is required');
        }
        const combatRange = unit.CC_RNG;
        return enemyUnits.some(enemy => isUnitInRange(unit, enemy, combatRange));
      default:
        return false;
    }
  }, [units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked, unitsFled]);

  const selectUnit = useCallback((unitId: UnitId | null) => {
    // Prevent unit selection during shooting sequence
    if (shootingPhaseState.singleShotState?.isActive) {
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
      unitsAttacked,
      unitsFled
    });
    
    // CRITICAL FIX: Block ALL actions if unit is not eligible
    if (!eligible) {
      console.log(`[useGameActions] Unit ${unitId} not eligible for phase ${phase} - selection completely blocked`);
      return; // Exit immediately - no phase handling
    }

    // Special handling for move phase - second click marks as moved (or chose not to move)
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

    // Special handling for combat phase
    if (phase === "combat") {
      // Always show the attack preview for adjacent enemies
      actions.setMovePreview(null);
      actions.setAttackPreview({ unitId, col: unit.col, row: unit.row });
      actions.setMode("attackPreview");
      actions.setSelectedUnitId(unitId);
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
      const unit = findUnit(movePreview.unitId);
      if (unit && phase === "move") {
        // Check if unit is fleeing (was adjacent to enemy at start of move, ends move not adjacent)
        const enemyUnits = units.filter(u => u.player !== unit.player);
        
        // FIXED: Check adjacency at ORIGINAL position before move
        const wasAdjacentToEnemy = enemyUnits.some(enemy => 
          Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) === 1
        );
        
        if (wasAdjacentToEnemy) {
          // Check if unit will still be adjacent after the move to DESTINATION
          const willBeAdjacentToEnemy = enemyUnits.some(enemy => 
            Math.max(Math.abs(movePreview.destCol - enemy.col), Math.abs(movePreview.destRow - enemy.row)) === 1
          );
          
          // Only mark as fled if unit was adjacent and will no longer be adjacent
          if (!willBeAdjacentToEnemy) {
            console.log(`🏃 Unit ${unit.name} (${unit.id}) FLED from (${unit.col},${unit.row}) to (${movePreview.destCol},${movePreview.destRow})`);
            actions.addFledUnit(movePreview.unitId);
          } else {
            console.log(`📍 Unit ${unit.name} (${unit.id}) moved but stayed adjacent - not fleeing`);
          }
        } else {
          console.log(`✅ Unit ${unit.name} (${unit.id}) moved but was not adjacent to enemies - normal move`);
        }
      }
      
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
  }, [gameState.mode, movePreview, attackPreview, actions, findUnit, phase, units]);

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
  if (shooter.RNG_NB === undefined) {
       throw new Error('shooter.RNG_NB is required');
     }
     const numberOfShots = shooter.RNG_NB;
  
  let totalDamage = 0;
  let hits = 0;
  let wounds = 0;
  let failedSaves = 0;

  // Process each shot
  for (let shot = 1; shot <= numberOfShots; shot++) {
    // Step 2: Range check (already validated before calling)
    
    // Step 3: Hit roll
    const hitRoll = rollD6();
    if (shooter.RNG_ATK === undefined) {
      throw new Error('shooter.RNG_ATK is required');
    }
    const hitTarget = shooter.RNG_ATK;
    const didHit = hitRoll >= hitTarget;
    
    if (!didHit) continue; // Miss - next shot
    hits++;
    
    // Step 4: Wound roll  
    const woundRoll = rollD6();
    if (shooter.RNG_STR === undefined) {
      throw new Error('shooter.RNG_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
   const woundTarget = calculateWoundTarget(shooter.RNG_STR, target.T);
    const didWound = woundRoll >= woundTarget;
    
    if (!didWound) continue; // Failed to wound - next shot
    wounds++;
    
    // Step 5: Armor save
    const saveRoll = rollD6();
    const saveTarget = calculateSaveTarget(
      target.ARMOR_SAVE, 
      target.INVUL_SAVE, 
      shooter.RNG_AP
    );
    const savedWound = saveRoll >= saveTarget;
    
    if (savedWound) continue; // Save successful - next shot
    failedSaves++;
    
    // Step 6: Inflict damage
    if (shooter.RNG_DMG === undefined) {
      throw new Error('shooter.RNG_DMG is required');
    }
    totalDamage += shooter.RNG_DMG;
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
  //
  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    const shooter = findUnit(shooterId);
    const target = findUnit(targetId);
    if (!shooter || !target) return;

    // PREVENT FRIENDLY FIRE: Cannot shoot friendly units
    if (target.player === shooter.player) {
      console.log(`❌ Cannot shoot friendly unit ${target.name || target.id}`);
      return;
    }

    // RULE 2: Cannot shoot enemy units adjacent to friendly units
    const friendlyUnits = units.filter(u => u.player === shooter.player && u.id !== shooter.id);
    const isTargetAdjacentToFriendly = friendlyUnits.some(friendly => 
      Math.max(Math.abs(friendly.col - target.col), Math.abs(friendly.row - target.row)) === 1
    );
    if (isTargetAdjacentToFriendly) {
      console.log(`❌ Cannot shoot ${target.name || target.id} - adjacent to friendly unit`);
      return;
    }

    // bail out if no shots remaining
    if (shooter.SHOOT_LEFT === undefined) {
      throw new Error('shooter.SHOOT_LEFT is required');
    }
    const shotsLeft = shooter.SHOOT_LEFT;
    if (shotsLeft <= 0) {
      console.log(`🎯 ${shooter.name} has no shots remaining`);
      return;
    }

    // Check if we're in single shot mode
    if (shootingPhaseState.singleShotState?.isActive) {
      // Handle target selection for current shot
      if (shootingPhaseState.singleShotState.currentStep === 'target_selection') {
        console.log(`🎯 Shot ${shootingPhaseState.singleShotState.currentShotNumber}: Selecting target ${targetId}`);
        singleShotSequenceManager.selectTarget(targetId);
        
        // Auto-process hit roll
        setTimeout(() => {
          singleShotSequenceManager.processHitRoll(shooter);
          
          // Auto-process wound roll if hit succeeded
          setTimeout(() => {
            const currentState = singleShotSequenceManager.getState();
            if (currentState?.stepResults.hitSuccess && target) {
              singleShotSequenceManager.processWoundRoll(shooter, target);
              
              // Auto-process save roll if wound succeeded
              setTimeout(() => {
                const updatedState = singleShotSequenceManager.getState();
                if (updatedState?.stepResults.woundSuccess && target) {
                  singleShotSequenceManager.processSaveRoll(shooter, target);
                }
              }, 50);
            }
          }, 50);
        }, 50);
        
        return;
      }
    } else {
      // CRITICAL: Check if unit has already shot this phase (FIRST CHECK)
      if (unitsMoved.includes(shooterId)) {
        console.log(`❌ Unit ${shooter.name} already shot this phase - ignoring click`);
        return;
      }
      
      // Check if this is a preview (first click) or execute (second click)
      const currentTargetPreview = gameState.targetPreview;
      
      if (currentTargetPreview && 
          currentTargetPreview.targetId === targetId && 
          currentTargetPreview.shooterId === shooterId) {
        // Second click - execute shooting
        console.log(`🎯 Executing shooting sequence for ${shooter.name}: ${shooter.SHOOT_LEFT} shots`);
        
        // Clear preview
        if (currentTargetPreview.blinkTimer) {
          clearInterval(currentTargetPreview.blinkTimer);
        }
        actions.setTargetPreview(null);
        
        // Keep track of shots fired locally to avoid React state timing issues
        let shotsFired = 0;
        const totalShots = shooter.SHOOT_LEFT;
        
        // Create a temporary shooter with only 1 shot to force single-shot behavior
        const singleShotShooter = {
          ...shooter,
          RNG_NB: 1,        // Force only 1 shot per sequence
          SHOOT_LEFT: 1     // Only 1 shot in this sequence
        };
        
        //////////////////////////////////////////
        // Simple single shot execution - no complex sequence manager
        console.log(`🎯 Executing single shot: ${shooter.name} → ${target.name}`);
        
        // Roll dice directly
        const hitRoll = Math.floor(Math.random() * 6) + 1;
        if (!shooter.RNG_ATK) throw new Error(`shooter.RNG_ATK is undefined for unit ${shooter.name}`);
        const hitSuccess = hitRoll >= shooter.RNG_ATK;
        
        let damageDealt = 0;
        
        if (hitSuccess) {
          const woundRoll = Math.floor(Math.random() * 6) + 1;
          if (!shooter.RNG_STR) throw new Error(`shooter.RNG_STR is undefined for unit ${shooter.name}`);
          if (!target.T) throw new Error(`target.T is undefined for unit ${target.name}`);
          const shooterStr = shooter.RNG_STR;
          const targetT = target.T;
          const woundTarget = shooterStr === targetT ? 4 : (shooterStr > targetT ? 3 : 5);
          const woundSuccess = woundRoll >= woundTarget;
          
          if (woundSuccess) {
            const saveRoll = Math.floor(Math.random() * 6) + 1;
            if (!target.ARMOR_SAVE) throw new Error(`target.ARMOR_SAVE is undefined for unit ${target.name}`);
            if (!shooter.RNG_AP) throw new Error(`shooter.RNG_AP is undefined for unit ${shooter.name}`);
            const saveTarget = target.ARMOR_SAVE + shooter.RNG_AP;
            const saveSuccess = saveRoll >= saveTarget;
            
            if (!saveSuccess) {
              if (shooter.RNG_DMG === undefined) {
                throw new Error('shooter.RNG_DMG is required');
              }
              damageDealt = shooter.RNG_DMG;
            }
          }
        }
        
        console.log(`🎲 Hit: ${hitRoll} (${hitSuccess}), Damage: ${damageDealt}`);
        
        // Apply damage
        if (damageDealt > 0) {
          if (target.CUR_HP === undefined) {
            throw new Error('target.CUR_HP is required');
          }
          const currentHP = target.CUR_HP;
          const newHP = Math.max(0, currentHP - damageDealt);
          
          if (newHP <= 0) {
            console.log(`💀 Target destroyed!`);
            actions.removeUnit(targetId);
          } else {
            console.log(`🩹 Target takes ${damageDealt} damage`);
            actions.updateUnit(targetId, { CUR_HP: newHP });
          }
        }
        
        // Manually decrement shots - get fresh unit state
        const currentShooter = findUnit(shooterId);
        if (!currentShooter) throw new Error(`Cannot find shooter unit ${shooterId}`);
        if (!currentShooter.SHOOT_LEFT) throw new Error(`currentShooter.SHOOT_LEFT is undefined for unit ${currentShooter.name}`);
        const currentShotsLeft = currentShooter.SHOOT_LEFT;
        const newShotsLeft = currentShotsLeft - 1;
        actions.updateUnit(shooterId, { SHOOT_LEFT: newShotsLeft });
        
        // Check if more shots remaining
        if (newShotsLeft > 0) {
          console.log(`🎯 ${shooter.name} has ${newShotsLeft} shots remaining`);
          // Stay in attack mode for target reselection
          actions.setAttackPreview({ unitId: shooterId, col: shooter.col, row: shooter.row });
          actions.setMode("attackPreview");
        } else {
          console.log(`🎯 ${shooter.name} finished shooting`);
          // Mark as moved and end shooting
          actions.addMovedUnit(shooterId);
          actions.setAttackPreview(null);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
        }
      } else {
        // First click - start preview
        console.log(`🎯 Starting shooting preview for ${shooter.name} → ${target.name}`);
        
        // Clear any existing preview
        if (currentTargetPreview?.blinkTimer) {
          clearInterval(currentTargetPreview.blinkTimer);
        }
        
        // Calculate probabilities
        const hitProbability = calculateHitProbability(shooter);
        const woundProbability = calculateWoundProbability(shooter, target);
        const saveProbability = calculateSaveProbability(shooter, target);
        const overallProbability = calculateOverallProbability(shooter, target);
        
        // Start preview with blink timer - SINGLE SHOT ONLY
        const totalBlinkSteps = 2; // Only show: current HP (step 0) -> after next shot (step 1)
        
        const preview: TargetPreview = {
          targetId,
          shooterId,
          currentBlinkStep: 0,
          totalBlinkSteps,
          blinkTimer: null,
          hitProbability,
          woundProbability,
          saveProbability,
          overallProbability
        };
        
        // Start blink cycle for single shot preview
        preview.blinkTimer = setInterval(() => {
          preview.currentBlinkStep = (preview.currentBlinkStep + 1) % totalBlinkSteps;
          actions.setTargetPreview({ ...preview });
        }, 500);
        
        actions.setTargetPreview(preview);
      }
    }
  }, [findUnit, actions, shootingPhaseState, gameState.targetPreview]);

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

    // PREVENT FRIENDLY FIRE: Cannot attack friendly units
    if (target.player === attacker.player) {
      console.log(`❌ Cannot attack friendly unit ${target.name || target.id}`);
      return;
    }

    // Check if units are within combat range
    const distance = Math.max(
      Math.abs(attacker.col - target.col),
      Math.abs(attacker.row - target.row)
    );
    const combatRange = attacker.CC_RNG || 1; // Use CC_RNG instead of hardcoded 1
    if (distance > combatRange) return;

    // Apply close combat damage
    if (target.CUR_HP === undefined) {
      throw new Error('target.CUR_HP is required');
    }
    if (attacker.CC_DMG === undefined) {
      throw new Error('attacker.CC_DMG is required');
    }
    const newHP = target.CUR_HP - attacker.CC_DMG;
    
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
    console.log(`⚔️ CHARGE: Unit ${chargerId} charges unit ${targetId}`);
    const charger = findUnit(chargerId);
    if (!charger) {
      console.error(`❌ CHARGE ERROR: Charger unit ${chargerId} not found!`);
      return;
    }
    console.log(`⚔️ Adding ${chargerId} to charged units`);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit]);

  const moveCharger = useCallback((chargerId: UnitId, destCol: number, destRow: number) => {
    console.log(`🏃 MOVE CHARGER: Unit ${chargerId} moves to (${destCol}, ${destRow})`);
    const charger = findUnit(chargerId);
    if (!charger) {
      console.error(`❌ MOVE CHARGER ERROR: Unit ${chargerId} not found!`);
      return;
    }
    
    // Move the unit to the destination
    actions.updateUnit(chargerId, { col: destCol, row: destRow });
    
    // Mark unit as having charged (end of activability for this phase)
    console.log(`⚔️ Adding ${chargerId} to charged units via moveCharger`);
    actions.addChargedUnit(chargerId);
    
    // Deselect the unit
    actions.setSelectedUnitId(null);
    
    // Return to select mode (cancel colored cells)
    actions.setMode("select");
  }, [actions, findUnit]);

  const cancelCharge = useCallback(() => {
    console.log(`❌ CANCEL CHARGE: selectedUnitId = ${selectedUnitId}`);
    if (selectedUnitId !== null) {
      const unit = findUnit(selectedUnitId);
      if (!unit) {
        console.error(`❌ CANCEL CHARGE ERROR: Unit ${selectedUnitId} not found!`);
      } else {
        console.log(`⚔️ Adding ${selectedUnitId} to charged units via cancelCharge`);
        actions.addChargedUnit(selectedUnitId);
      }
    }
    actions.setSelectedUnitId(null);
    actions.setMode("select");
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
  }, [actions, selectedUnitId, findUnit]);

  const validateCharge = useCallback((chargerId: UnitId) => {
    console.log(`✅ VALIDATE CHARGE: Unit ${chargerId}`);
    const charger = findUnit(chargerId);
    if (!charger) {
      console.error(`❌ VALIDATE CHARGE ERROR: Unit ${chargerId} not found!`);
      return;
    }
    console.log(`⚔️ Adding ${chargerId} to charged units via validateCharge`);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit]);

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