// src/hooks/useGameActions.ts
import { useCallback } from 'react';
import { GameState, UnitId, MovePreview, AttackPreview, Unit, ShootingPhaseState, TargetPreview } from '../types/game';
import { calculateHitProbability, calculateWoundProbability, calculateSaveProbability, calculateOverallProbability, calculateCombatHitProbability, calculateCombatWoundProbability, calculateCombatSaveProbability, calculateCombatOverallProbability } from '../utils/probabilityCalculator';
import { areUnitsAdjacent, isUnitInRange } from '../utils/gameHelpers';
import { singleShotSequenceManager } from '../utils/ShootingSequenceManager';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
  gameLog?: any; // Add gameLog parameter as optional
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
  gameLog,
  actions,
}: UseGameActionsParams) => {
  const { units, currentPlayer, phase, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked, unitsFled } = gameState;

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

    // Special handling for charge phase
    if (phase === "charge") {
      actions.setSelectedUnitId(unitId);
      actions.setMode("chargePreview");
      actions.setMovePreview(null);
      actions.setAttackPreview(null);
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

        // Log the move action
        if (gameLog) {
          gameLog.logMoveAction(unit, unit.col, unit.row, movePreview.destCol, movePreview.destRow, gameState.currentTurn);
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
    // CRITICAL: Check if unit has already shot this phase (FIRST CHECK)
    if (unitsMoved.includes(shooterId)) {
      console.log(`❌ Unit already shot this phase - ignoring handleShoot call for ${shooterId}`);
      return;
    }

    // NEW: Check if unit fled this turn (SECOND CHECK)
    if (unitsFled.includes(shooterId)) {
      console.log(`❌ Unit fled this turn and cannot shoot - ignoring handleShoot call for ${shooterId}`);
      return;
    }

    // ADDITIONAL CHECK: Prevent shooting if unit has no shots left
    const preShooter = findUnit(shooterId);
    if (preShooter && preShooter.SHOOT_LEFT !== undefined && preShooter.SHOOT_LEFT <= 0) {
      return;
    }

    const shooter = findUnit(shooterId);
    const target = findUnit(targetId);
    if (!shooter || !target) {
      return;
    }

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

    // Add range check
    if (!isUnitInRange(shooter, target, shooter.RNG_RNG)) {
      return;
    }

    if (shooter.SHOOT_LEFT === undefined) {
      throw new Error('shooter.SHOOT_LEFT is required');
    }

    const shotsLeft = shooter.SHOOT_LEFT;
    
    if (shotsLeft <= 0) {
      return;
    }

    // Check if we're in single shot mode
    if (shootingPhaseState.singleShotState?.isActive) {
      // Handle target selection for current shot
      if (shootingPhaseState.singleShotState.currentStep === 'target_selection') {
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
      // Check if this is a preview (first click) or execute (second click)
      const currentTargetPreview = gameState.targetPreview;
      
      if (currentTargetPreview && 
          currentTargetPreview.targetId === targetId && 
          currentTargetPreview.shooterId === shooterId) {
        // Second click - execute shooting
        // NEW: IMMEDIATE PROTECTION - Only for single shot units (RNG_NB = 1)
        // Multi-shot units need to complete all shots before being marked as moved
        if (shooter.RNG_NB === 1) {
          actions.addMovedUnit(shooterId);
        }
        
        // Clear preview
        if (currentTargetPreview.blinkTimer) {
          clearInterval(currentTargetPreview.blinkTimer);
        }
        actions.setTargetPreview(null);

        // Simple single shot execution - no complex sequence manager
        // Roll dice directly
        const hitRoll = Math.floor(Math.random() * 6) + 1;
        if (!shooter.RNG_ATK) throw new Error(`shooter.RNG_ATK is undefined for unit ${shooter.name}`);
        const hitSuccess = hitRoll >= shooter.RNG_ATK;
        
        let damageDealt = 0;
        let woundRoll = 0;
        let woundSuccess = false;
        let saveRoll = 0;
        let saveSuccess = false;
        
        // Declare these at the top level for logging
        if (!shooter.RNG_STR) throw new Error(`shooter.RNG_STR is undefined for unit ${shooter.name}`);
        const shooterStr = shooter.RNG_STR;
        if (!target.T) throw new Error(`target.T is undefined for unit ${target.name}`);
        const targetT = target.T;
        if (!target.ARMOR_SAVE) throw new Error(`target.ARMOR_SAVE is undefined for unit ${target.name}`);
        const targetArmorSave = target.ARMOR_SAVE;
        if (!shooter.RNG_AP) throw new Error(`shooter.RNG_AP is undefined for unit ${shooter.name}`);
        const shooterAP = shooter.RNG_AP;
        
        if (hitSuccess) {
          woundRoll = Math.floor(Math.random() * 6) + 1;
          if (!shooter.RNG_STR) throw new Error(`shooter.RNG_STR is undefined for unit ${shooter.name}`);
          if (!target.T) throw new Error(`target.T is undefined for unit ${target.name}`);
          const woundTarget = shooterStr === targetT ? 4 : (shooterStr > target.T ? 3 : 5);
          woundSuccess = woundRoll >= woundTarget;
          
          if (woundSuccess) {
            saveRoll = Math.floor(Math.random() * 6) + 1;
            if (!target.ARMOR_SAVE) throw new Error(`target.ARMOR_SAVE is undefined for unit ${target.name}`);
            if (!shooter.RNG_AP) throw new Error(`shooter.RNG_AP is undefined for unit ${shooter.name}`);
            const saveTarget = target.ARMOR_SAVE + shooter.RNG_AP;
            saveSuccess = saveRoll >= saveTarget;
            
            if (!saveSuccess) {
              if (shooter.RNG_DMG === undefined) {
                throw new Error('shooter.RNG_DMG is required');
              }
              damageDealt = shooter.RNG_DMG;
            }
          }
        }
        
        // Apply damage
        if (damageDealt > 0) {
          if (target.CUR_HP === undefined) {
            throw new Error('target.CUR_HP is required');
          }
          const currentHP = target.CUR_HP;
          const newHP = Math.max(0, currentHP - damageDealt);
          
          if (newHP <= 0) {
            // Log unit death before removing it
            if (gameLog) {
              gameLog.logUnitDeath(target, gameState.currentTurn);
            }
            actions.removeUnit(targetId);
          } else {
            actions.updateUnit(targetId, { CUR_HP: newHP });
          }
        }

        // Log the shooting action
        if (gameLog) {
          const shootDetails = [{
            shotNumber: 1,
            attackRoll: hitRoll,
            strengthRoll: woundRoll,
            hitResult: hitSuccess ? 'HIT' : 'MISS' as 'HIT' | 'MISS',
            strengthResult: (hitSuccess && woundSuccess) ? 'SUCCESS' : 'FAILED' as 'SUCCESS' | 'FAILED',
            hitTarget: shooter.RNG_ATK,
            woundTarget: hitSuccess ? (shooterStr === targetT ? 4 : (shooterStr > targetT ? 3 : 5)) : undefined,
            saveTarget: (hitSuccess && woundSuccess) ? (targetArmorSave + shooterAP) : undefined,
            saveRoll: (hitSuccess && woundSuccess) ? saveRoll : undefined,
            saveSuccess: (hitSuccess && woundSuccess) ? saveSuccess : undefined,
            damageDealt: damageDealt
          }];
          gameLog.logShootingAction(shooter, target, shootDetails, gameState.currentTurn);
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
          // Stay in attack mode for target reselection
          actions.setAttackPreview({ unitId: shooterId, col: shooter.col, row: shooter.row });
          actions.setMode("attackPreview");
        } else {
          // Mark as moved and end shooting
          actions.addMovedUnit(shooterId);
          actions.setAttackPreview(null);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
          
          // CRITICAL FIX: Force immediate phase transition check
          // This prevents the React state timing issue
          setTimeout(() => {
            const playerUnits = units.filter(u => u.player === currentPlayer);
            const stillShootable = playerUnits.some(unit => {
              if (unit.id === shooterId) return false; // This unit just finished
              if (unit.SHOOT_LEFT !== undefined && unit.SHOOT_LEFT > 0) return true;
              return false;
            });
            
            if (!stillShootable) {
              // The usePhaseTransition hook will handle the actual transition
            }
          }, 100);
        }
      } else {
        // First click - start preview
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
    console.log(`🥊 COMBAT ATTACK CALLED: Attacker ${attackerId} -> Target ${targetId}`);
    
    if (targetId === null) {
      // Skip attack but mark as attacked
      actions.addAttackedUnit(attackerId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const attacker = findUnit(attackerId);
    const target = findUnit(targetId);
    console.log(`🥊 COMBAT: Found attacker:`, attacker?.name, attacker?.id);
    console.log(`🥊 COMBAT: Found target:`, target?.name, target?.id);
    
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
    if (!attacker.CC_RNG) throw new Error(`attacker.CC_RNG is undefined for unit ${attacker.name}`);
    const combatRange = attacker.CC_RNG;
    if (distance > combatRange) return;

    // Initialize ATTACK_LEFT if not set
    if (attacker.ATTACK_LEFT === undefined) {
      actions.updateUnit(attackerId, { ATTACK_LEFT: attacker.CC_NB });
      return; // Return to let state update, then continue
    }

    // Check if attacker has attacks remaining
    if (attacker.ATTACK_LEFT === undefined) throw new Error(`attacker.ATTACK_LEFT is undefined for unit ${attacker.name}`);
    if (attacker.ATTACK_LEFT <= 0) {
      console.log(`❌ No attacks remaining for ${attacker.name}`);
      actions.addAttackedUnit(attackerId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    console.log(`✅ ${attacker.name} has ${attacker.ATTACK_LEFT} attacks remaining - proceeding with attack`);

    // ✅ NEW: Combat Preview System (similar to shooting preview)
    const currentTargetPreview = gameState.targetPreview;
    const isConfirmingAttack = currentTargetPreview?.targetId === targetId && currentTargetPreview?.shooterId === attackerId;

    if (isConfirmingAttack) {
      // Second click - execute attack
      console.log(`🎯 Confirming combat attack for ${attacker.name} → ${target.name}`);
      
      // Clear the preview
      if (currentTargetPreview?.blinkTimer) {
        clearInterval(currentTargetPreview.blinkTimer);
      }
      actions.setTargetPreview(null);
      
      // Execute the actual combat attack (existing logic wrapped in setTimeout)
      setTimeout(() => {
        // Combat Sequence: Hit → Wound → Save → Damage
        console.log(`⚔️ ${attacker.name} attacks ${target.name}`);

        // Hit Roll
        const hitRoll = Math.floor(Math.random() * 6) + 1;
    if (!attacker.CC_ATK) throw new Error(`attacker.CC_ATK is undefined for unit ${attacker.name}`);
    const hitSuccess = hitRoll >= attacker.CC_ATK;

    console.log(`🎲 Hit roll: ${hitRoll} vs ${attacker.CC_ATK}+ = ${hitSuccess ? 'HIT' : 'MISS'}`);

    if (!hitSuccess) {
      // Log the miss
      if (gameLog) {
        const combatDetails = [{
          shotNumber: 1,
          attackRoll: hitRoll,
          strengthRoll: 0,
          hitResult: 'MISS' as 'HIT' | 'MISS',
          strengthResult: 'FAILED' as 'SUCCESS' | 'FAILED',
          hitTarget: attacker.CC_ATK,
          woundTarget: undefined,
          saveTarget: undefined,
          saveRoll: undefined,
          saveSuccess: undefined,
          damageDealt: 0
        }];
        gameLog.logCombatAction(attacker, target, combatDetails, gameState.currentTurn);
      }

      // Miss - decrease attacks and end
      if (attacker.ATTACK_LEFT === undefined) throw new Error(`attacker.ATTACK_LEFT is undefined for unit ${attacker.name}`);
      const currentAttacks = attacker.ATTACK_LEFT;
      actions.updateUnit(attackerId, { ATTACK_LEFT: currentAttacks - 1 });
      if (currentAttacks - 1 <= 0) {
        actions.addAttackedUnit(attackerId);
        actions.setSelectedUnitId(null);
        actions.setMode("select");
      }
      return;
    }

    // Wound Roll
    const woundRoll = Math.floor(Math.random() * 6) + 1;
    if (!attacker.CC_STR) throw new Error(`attacker.CC_STR is undefined for unit ${attacker.name}`);
    if (!target.T) throw new Error(`target.T is undefined for unit ${target.name}`);
    
    const attackerStr = attacker.CC_STR;
    const targetT = target.T;
    const woundTarget = attackerStr >= targetT * 2 ? 2 : 
                      attackerStr > targetT ? 3 : 
                      attackerStr === targetT ? 4 : 
                      attackerStr < targetT ? 5 : 6;
    const woundSuccess = woundRoll >= woundTarget;

    console.log(`🎲 Wound roll: ${woundRoll} vs ${woundTarget}+ = ${woundSuccess ? 'WOUND' : 'NO WOUND'}`);

    if (!woundSuccess) {
      // Log the failed wound
      if (gameLog) {
        const combatDetails = [{
          shotNumber: 1,
          attackRoll: hitRoll,
          strengthRoll: woundRoll,
          hitResult: 'HIT' as 'HIT' | 'MISS',
          strengthResult: 'FAILED' as 'SUCCESS' | 'FAILED',
          hitTarget: attacker.CC_ATK,
          woundTarget: woundTarget,
          saveTarget: undefined,
          saveRoll: undefined,
          saveSuccess: undefined,
          damageDealt: 0
        }];
        gameLog.logCombatAction(attacker, target, combatDetails, gameState.currentTurn);
      }

      // No wound - decrease attacks and end
      if (attacker.ATTACK_LEFT === undefined) throw new Error(`attacker.ATTACK_LEFT is undefined for unit ${attacker.name}`);
      const currentAttacks = attacker.ATTACK_LEFT;
      actions.updateUnit(attackerId, { ATTACK_LEFT: currentAttacks - 1 });
      if (currentAttacks - 1 <= 0) {
        actions.addAttackedUnit(attackerId);
        actions.setSelectedUnitId(null);
        actions.setMode("select");
      }
      return;
    }

    console.log(`🎲 Proceeding to armor save...`);

    // Armor Save
    const saveRoll = Math.floor(Math.random() * 6) + 1;
    if (target.ARMOR_SAVE === undefined) throw new Error(`target.ARMOR_SAVE is undefined for unit ${target.name}`);
    if (attacker.CC_AP === undefined) throw new Error(`attacker.CC_AP is undefined for unit ${attacker.name}`);
    
    const modifiedArmor = target.ARMOR_SAVE + attacker.CC_AP;
    if (target.INVUL_SAVE === undefined) throw new Error(`target.INVUL_SAVE is undefined for unit ${target.name}`);
    const invulSave = target.INVUL_SAVE;
    const saveTarget = (invulSave > 0 && invulSave < modifiedArmor) ? invulSave : modifiedArmor;
    const saveSuccess = saveRoll >= saveTarget;

    console.log(`🎲 Save roll: ${saveRoll} vs ${saveTarget}+ = ${saveSuccess ? 'SAVED' : 'FAILED'}`);

    // Damage Application
    const damageDealt = saveSuccess ? 0 : (attacker.CC_DMG);
    console.log(`${saveSuccess ? 'Saved' : 'Wounded'} - ${damageDealt} damage`);

    if (attacker.ATTACK_LEFT === undefined) throw new Error(`attacker.ATTACK_LEFT is undefined for unit ${attacker.name}`);
    console.log(`💥 About to decrement ATTACK_LEFT from ${attacker.ATTACK_LEFT} to ${attacker.ATTACK_LEFT - 1}`);

    // Log the combat action FIRST (regardless of damage)
    if (gameLog) {
      const combatDetails = [{
        shotNumber: 1,
        attackRoll: hitRoll,
        strengthRoll: woundRoll,
        hitResult: hitSuccess ? 'HIT' : 'MISS' as 'HIT' | 'MISS',
        strengthResult: woundSuccess ? 'SUCCESS' : 'FAILED' as 'SUCCESS' | 'FAILED',
        hitTarget: attacker.CC_ATK,
        woundTarget: hitSuccess ? woundTarget : undefined,
        saveTarget: (hitSuccess && woundSuccess) ? saveTarget : undefined,
        saveRoll: (hitSuccess && woundSuccess) ? saveRoll : undefined,
        saveSuccess: (hitSuccess && woundSuccess) ? saveSuccess : undefined,
        damageDealt: damageDealt
      }];
      gameLog.logCombatAction(attacker, target, combatDetails, gameState.currentTurn);
    }

    if (damageDealt > 0) {
      if (target.CUR_HP === undefined) {
        throw new Error('target.CUR_HP is required');
      }
      const newHP = target.CUR_HP - damageDealt;

      if (newHP <= 0) {
        // Log unit death AFTER the attack that killed it
        if (gameLog) {
          gameLog.logUnitDeath(target, gameState.currentTurn);
        }
        actions.removeUnit(targetId);
      } else {
        actions.updateUnit(targetId, { CUR_HP: newHP });
      }
    }

    // Get fresh unit state and decrement attacks
    const currentAttacker = findUnit(attackerId);
    if (!currentAttacker) throw new Error(`Cannot find attacker unit ${attackerId}`);
    if (currentAttacker.ATTACK_LEFT === undefined) throw new Error(`currentAttacker.ATTACK_LEFT is undefined for unit ${currentAttacker.name}`);
    const currentAttacksLeft = currentAttacker.ATTACK_LEFT;
    const newAttacksLeft = currentAttacksLeft - 1;
    
    actions.updateUnit(attackerId, { ATTACK_LEFT: newAttacksLeft });

    console.log(`📉 Updated ${attacker.name} ATTACK_LEFT to ${newAttacksLeft}`);

    // Check if attacker is done
        if (newAttacksLeft <= 0) {
          actions.addAttackedUnit(attackerId);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
        }
      }, 100);
    } else {
      // First click - start preview
      console.log(`🎯 Starting combat preview for ${attacker.name} → ${target.name}`);
      
      // Clear any existing preview
      if (currentTargetPreview?.blinkTimer) {
        clearInterval(currentTargetPreview.blinkTimer);
      }
      
      // Calculate combat probabilities
      const hitProbability = calculateCombatHitProbability(attacker);
      const woundProbability = calculateCombatWoundProbability(attacker, target);
      const saveProbability = calculateCombatSaveProbability(attacker, target);
      const overallProbability = calculateCombatOverallProbability(attacker, target);
      
      // Start preview with blink timer - SINGLE ATTACK ONLY
      const totalBlinkSteps = 2; // Only show: current HP (step 0) -> after next attack (step 1)
      
      const preview: TargetPreview = {
        targetId,
        shooterId: attackerId, // Reuse shooterId field for attacker
        currentBlinkStep: 0,
        totalBlinkSteps,
        blinkTimer: null,
        hitProbability,
        woundProbability,
        saveProbability,
        overallProbability
      };
      
      // Start blink cycle for single attack preview
      preview.blinkTimer = setInterval(() => {
        preview.currentBlinkStep = (preview.currentBlinkStep + 1) % totalBlinkSteps;
        actions.setTargetPreview({ ...preview });
      }, 500);
      
      actions.setTargetPreview(preview);
    }
  }, [findUnit, actions, gameState.targetPreview, gameState.currentTurn, gameLog]);

  const handleCharge = useCallback((chargerId: UnitId, targetId: UnitId) => {
    console.log(`⚔️ CHARGE: Unit ${chargerId} charges unit ${targetId}`);
    const charger = findUnit(chargerId);
    const target = findUnit(targetId);
    if (!charger) {
      console.error(`❌ CHARGE ERROR: Charger unit ${chargerId} not found!`);
      return;
    }
    if (!target) {
      console.error(`❌ CHARGE ERROR: Target unit ${targetId} not found!`);
      return;
    }

    // Log the charge action
    if (gameLog) {
      gameLog.logChargeAction(charger, target, charger.col, charger.row, target.col, target.row, gameState.currentTurn);
    }

    console.log(`⚔️ Adding ${chargerId} to charged units`);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit, gameLog, gameState.currentTurn]);

  const moveCharger = useCallback((chargerId: UnitId, destCol: number, destRow: number) => {
    console.log(`🏃 MOVE CHARGER: Unit ${chargerId} moves to (${destCol}, ${destRow})`);
    const charger = findUnit(chargerId);
    if (!charger) {
      console.error(`❌ MOVE CHARGER ERROR: Unit ${chargerId} not found!`);
      return;
    }
    
    // Log the charge move
    if (gameLog) {
      // Find the nearest enemy unit (charge target)
      const enemyUnits = units.filter(u => u.player !== charger.player);
      const target = enemyUnits.find(enemy => {
        // Check if enemy is adjacent to the destination
        const distance = Math.max(Math.abs(destCol - enemy.col), Math.abs(destRow - enemy.row));
        return distance <= 1;
      });
      
      if (target) {
        gameLog.logChargeAction(charger, target, charger.col, charger.row, destCol, destRow, gameState.currentTurn);
      } else {
        // If no specific target found, log as a general charge move
        const dummyTarget = { id: -1, type: 'Enemy', name: 'Enemy' } as any;
        gameLog.logChargeAction(charger, dummyTarget, charger.col, charger.row, destCol, destRow, gameState.currentTurn);
      }
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
  }, [actions, findUnit, gameLog, gameState.currentTurn, units]);

  const cancelCharge = useCallback(() => {
    console.log(`❌ CANCEL CHARGE: selectedUnitId = ${selectedUnitId}`);
    if (selectedUnitId !== null) {
      const unit = findUnit(selectedUnitId);
      if (!unit) {
        console.error(`❌ CANCEL CHARGE ERROR: Unit ${selectedUnitId} not found!`);
      } else {
        // CRITICAL FIX: Check if unit is already charged to prevent duplicates
        if (unitsCharged.includes(selectedUnitId)) {
          console.log(`⚠️ Unit ${selectedUnitId} already charged - skipping cancelCharge`);
        } else {
          // Log charge cancellation
          if (gameLog) {
            gameLog.logChargeCancellation(unit, gameState.currentTurn);
          }
          console.log(`⚔️ Adding ${selectedUnitId} to charged units via cancelCharge`);
          actions.addChargedUnit(selectedUnitId);
        }
      }
    }
    actions.setSelectedUnitId(null);
    actions.setMode("select");
    actions.setMovePreview(null);
    actions.setAttackPreview(null);
  }, [actions, selectedUnitId, findUnit, unitsCharged, gameLog, gameState.currentTurn]);

  const validateCharge = useCallback((chargerId: UnitId) => {
    console.log(`✅ VALIDATE CHARGE: Unit ${chargerId}`);
    const charger = findUnit(chargerId);
    if (!charger) {
      console.error(`❌ VALIDATE CHARGE ERROR: Unit ${chargerId} not found!`);
      return;
    }

    // Log the charge validation
    if (gameLog) {
      // Find nearby enemy as target
      const enemyUnits = units.filter(u => u.player !== charger.player);
      const target = enemyUnits.find(enemy => 
        Math.max(Math.abs(charger.col - enemy.col), Math.abs(charger.row - enemy.row)) <= 1
      );
      if (target) {
        gameLog.logChargeAction(charger, target, charger.col, charger.row, charger.col, charger.row, gameState.currentTurn);
      }
    }

    console.log(`⚔️ Adding ${chargerId} to charged units via validateCharge`);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit, gameLog, gameState.currentTurn, units]);

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