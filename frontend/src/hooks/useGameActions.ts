// src/hooks/useGameActions.ts
import React, { useCallback, useState } from 'react';
import { GameState, UnitId, MovePreview, AttackPreview, Unit, ShootingPhaseState, TargetPreview, CombatSubPhase, PlayerId } from '../types/game';
import { calculateHitProbability, calculateWoundProbability, calculateSaveProbability, calculateOverallProbability, calculateCombatHitProbability, calculateCombatWoundProbability, calculateCombatSaveProbability, calculateCombatOverallProbability } from '../utils/probabilityCalculator';
import { areUnitsAdjacent, isUnitInRange, hasLineOfSight, offsetToCube, cubeDistance, getHexLine } from '../utils/gameHelpers';
import { singleShotSequenceManager } from '../utils/ShootingSequenceManager';
import { rollD6, calculateWoundTarget, calculateSaveTarget } from '../../../shared/gameRules';

interface UseGameActionsParams {
  gameState: GameState;
  movePreview: MovePreview | null;
  attackPreview: AttackPreview | null;
  shootingPhaseState: ShootingPhaseState;
  boardConfig: any; // Add board configuration for line of sight checks
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
    setCombatSubPhase: (subPhase: CombatSubPhase | undefined) => void; // NEW
    setCombatActivePlayer: (player: PlayerId | undefined) => void; // NEW
    setUnitChargeRoll: (unitId: UnitId, roll: number) => void;
    resetUnitChargeRoll: (unitId: UnitId) => void;
    showChargeRollPopup: (unitId: UnitId, roll: number, tooLow: boolean) => void;
    resetChargeRolls: () => void;
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
  const { 
    units, 
    currentPlayer, 
    phase, 
    selectedUnitId, 
    unitsMoved, 
    unitsCharged, 
    unitsAttacked, 
    unitsFled,
    combatSubPhase,
    combatActivePlayer
  } = gameState;

  // AI_TURN.md: State machine variables for shooting phase
  const [shootingActivationQueue, setShootingActivationQueue] = useState<Unit[]>([]);
  const [activeShootingUnit, setActiveShootingUnit] = useState<Unit | null>(null);
  const [selectedShootingTarget, setSelectedShootingTarget] = useState<Unit | null>(null);
  const [shootLeft, setShootLeft] = useState<number | undefined>(undefined);
  const [activationShotLog, setActivationShotLog] = useState<any[]>([]);
  const [validTargetsPool, setValidTargetsPool] = useState<Unit[]>([]);
  const [shootingState, setShootingState] = useState<'WAITING_FOR_ACTIVATION' | 'WAITING_FOR_ACTION' | 'TARGET_PREVIEWING'>('WAITING_FOR_ACTIVATION');

  // Helper function to find unit by ID
  const findUnit = useCallback((unitId: UnitId) => {
    return units.find(u => u.id === unitId);
  }, [units]);

  // Helper function to check if enemy is reachable via pathfinding around walls
  const checkPathfindingReachable = useCallback((unit: Unit, enemy: Unit, wallHexSet: Set<string>, maxDistance: number): boolean => {
    if (!boardConfig) {
    throw new Error('boardConfig is required for pathfinding but was not provided');
  }
  if (!boardConfig.cols || !boardConfig.rows) {
      throw new Error('boardConfig.cols and boardConfig.rows are required for pathfinding');
    }
    
    const visited = new Set<string>();
    const queue: Array<{col: number, row: number, distance: number}> = [{col: unit.col, row: unit.row, distance: 0}];
    
    const cubeDirections = [
      [1, -1, 0], [1, 0, -1], [0, 1, -1], 
      [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
    ];

    while (queue.length > 0) {
      const current = queue.shift()!;
      const key = `${current.col},${current.row}`;
      
      if (visited.has(key)) continue;
      visited.add(key);
      
      // Found the enemy
      if (current.col === enemy.col && current.row === enemy.row) {
        return true;
      }
      
      // Don't expand beyond max distance
      if (current.distance >= maxDistance) continue;
      
      // Expand to neighbors
      const currentCube = offsetToCube(current.col, current.row);
      for (const [dx, dy, dz] of cubeDirections) {
        const neighborCube = {
          x: currentCube.x + dx,
          y: currentCube.y + dy,
          z: currentCube.z + dz
        };
        
        const ncol = neighborCube.x;
        const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);
        const nkey = `${ncol},${nrow}`;
        
        // Skip if out of bounds, already visited, or is a wall
        if (ncol < 0 || ncol >= boardConfig.cols || nrow < 0 || nrow >= boardConfig.rows) continue;
        if (visited.has(nkey)) continue;
        if (wallHexSet.has(nkey)) continue;
        
        queue.push({col: ncol, row: nrow, distance: current.distance + 1});
      }
    }
    
    return false; // Enemy not reachable
  }, [boardConfig]);

  // Helper function to check if unit is eligible for selection
  const isUnitEligible = useCallback((unit: Unit) => {
    if (phase !== "combat" && unit.player !== currentPlayer) {
      return false;
    }

    // Get enemy units once for efficiency
    const enemyUnits = units.filter(u => u.player !== currentPlayer);

    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot":
        // AI_TURN.md: "units_fled.includes(unit.id)? → YES → ❌ Fled unit (Skip, no log)"
        if (unitsFled.includes(unit.id)) return false;
        // AI_TURN.md: "Adjacent to enemy unit within CC_RNG? → YES → ❌ In combat (Skip, no log)"
        const hasAdjacentEnemyShoot = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
        if (hasAdjacentEnemyShoot) return false;
        // AI_TURN.md: "unit.RNG_NB > 0? → NO → ❌ No ranged weapon (Skip, no log)"
        if (unit.RNG_NB === undefined || unit.RNG_NB <= 0) return false;
        // AI_TURN.md: "Has LOS to enemies within RNG_RNG? → NO → ❌ No valid targets (Skip, no log)"
        const friendlyUnits = units.filter(u => u.player === unit.player && u.id !== unit.id);
        return enemyUnits.some(enemy => {
          if (enemy.player === unit.player) return false;
          if (!isUnitInRange(unit, enemy, unit.RNG_RNG)) return false;
          const isEnemyAdjacentToFriendly = friendlyUnits.some(friendly =>
            Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
          );
          if (isEnemyAdjacentToFriendly) return false;
         
          if (!boardConfig) {
            throw new Error('boardConfig is required for shooting phase eligibility check but was not provided');
          }
          if (!boardConfig.wall_hexes) {
            throw new Error('boardConfig.wall_hexes is required for shooting phase eligibility check but was undefined');
          }
          
          const lineOfSight = hasLineOfSight(
            { col: unit.col, row: unit.row },
            { col: enemy.col, row: enemy.row },
            boardConfig.wall_hexes
          );
          if (!lineOfSight.canSee) return false;
         
          return true;
        });
      case "charge":
        if (unitsCharged.includes(unit.id)) return false;
        if (unitsFled.includes(unit.id)) return false;
        const isAdjacent = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
        
        // Check if any enemies are within 12 hexes using pathfinding (respecting walls like in movement)
        const hasEnemiesWithin12Hexes = enemyUnits.some(enemy => {
          const cube1 = offsetToCube(unit.col, unit.row);
          const cube2 = offsetToCube(enemy.col, enemy.row);
          const hexDistance = cubeDistance(cube1, cube2);
          
          if (hexDistance > 12) return false;
          
          // Check pathfinding around walls/obstacles (same as move phase)
          if (boardConfig && boardConfig.wall_hexes) {
            const wallHexSet = new Set((boardConfig.wall_hexes as [number, number][]).map(([c, r]) => `${c},${r}`));
            const isReachable = checkPathfindingReachable(unit, enemy, wallHexSet, 12);
            return isReachable;
          }
          
          return true;
        });
        
        return !isAdjacent && hasEnemiesWithin12Hexes;
      case "combat":
        if (unitsAttacked.includes(unit.id)) return false;
        
        if (gameState.combatSubPhase === "charged_units") {
          if (unit.player !== currentPlayer) return false;
          if (!unit.hasChargedThisTurn) return false;
        } else if (gameState.combatSubPhase === "alternating_combat") {
          // CRITICAL FIX: Check combatActivePlayer correctly
          if (gameState.combatActivePlayer === undefined) return false;
          if (unit.player !== gameState.combatActivePlayer) return false;
          if (unit.hasChargedThisTurn) return false;
        } else {
          if (unit.player !== currentPlayer) {
            return false;
          }
        }
        
        // CRITICAL FIX: Filter enemies correctly based on the unit's player, not currentPlayer
        const actualEnemyUnits = units.filter(u => u.player !== unit.player);
        
        if (unit.CC_RNG === undefined) {
          throw new Error('unit.CC_RNG is required');
        }
        const combatRange = unit.CC_RNG;
        // CRITICAL FIX: Only units adjacent to enemies should be eligible for combat
        // For CC_RNG = 1, units must be exactly distance 1 (adjacent) to enemies
        const hasAdjacentEnemy = actualEnemyUnits.some(enemy => {
          const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
          return distance === combatRange; // Must be exactly at combat range (adjacent for CC_RNG=1)
        });
        return hasAdjacentEnemy;
      default:
        return false;
    }
  }, [units, currentPlayer, phase, unitsMoved, unitsCharged, unitsAttacked, unitsFled, combatSubPhase, combatActivePlayer, boardConfig, gameState]);

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
          const willBeAdjacentToEnemy = enemyUnits.some(enemy => 
            Math.max(Math.abs(movePreview.destCol - enemy.col), Math.abs(movePreview.destRow - enemy.row)) === 1
          );
          
          if (!willBeAdjacentToEnemy) {
            actions.addFledUnit(movePreview.unitId);
          }
        }

        // Log the move action
        if (gameLog) {
          gameLog.logMoveAction(unit, unit.col, unit.row, movePreview.destCol, movePreview.destRow, gameState.currentTurn);
        }
        // AI_TURN.md: Built-in step counting (+1 step)
        if (gameState.episode_steps === undefined) {
          throw new Error('gameState.episode_steps is required but was undefined');
        }
        gameState.episode_steps = gameState.episode_steps + 1;
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

  // AI_TURN.md: Component 7 - Target Preview Cleanup
  const clearTargetPreview = useCallback(() => {
    const currentPreview = gameState.targetPreview;
    if (currentPreview && currentPreview.blinkTimer) {
      clearInterval(currentPreview.blinkTimer);
    }
    actions.setTargetPreview(null);
  }, [gameState.targetPreview, actions]);

  // AI_TURN.md: Component 6 - State Machine Lifecycle Management
  const initializeShootingPhase = useCallback(() => {
    // Clear all state variables on entry
    setActivationShotLog([]);
    setActiveShootingUnit(null);
    setSelectedShootingTarget(null);
    setShootLeft(undefined);
    setValidTargetsPool([]);
    clearTargetPreview();
    
    // Build eligibility queue
    const eligibleUnits: Unit[] = [];
    
    units.forEach(unit => {
      // AI_TURN.md: ELIGIBILITY CHECK (Queue Building Phase)
      if (unit.CUR_HP === undefined || unit.CUR_HP <= 0) return; // Dead unit (Skip, no log)
      if (unit.player !== currentPlayer) return; // Wrong player (Skip, no log)
      if (unitsFled.includes(unit.id)) return; // Fled unit (Skip, no log)
      
      // Adjacent to enemy unit within CC_RNG?
      const enemyUnits = units.filter(u => u.player !== unit.player);
      const hasAdjacentEnemyShoot = enemyUnits.some(enemy => areUnitsAdjacent(unit, enemy));
      if (hasAdjacentEnemyShoot) return; // In combat (Skip, no log)
      
      // unit.RNG_NB > 0?
      if (unit.RNG_NB === undefined || unit.RNG_NB <= 0) return; // No ranged weapon (Skip, no log)
      
      // Has LOS to enemies within RNG_RNG?
      const friendlyUnits = units.filter(u => u.player === unit.player && u.id !== unit.id);
      const hasValidTargets = enemyUnits.some(enemy => {
        if (enemy.player === unit.player) return false;
        if (!isUnitInRange(unit, enemy, unit.RNG_RNG)) return false;
        const isEnemyAdjacentToFriendly = friendlyUnits.some(friendly =>
          Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
        );
        if (isEnemyAdjacentToFriendly) return false;
       
        if (!boardConfig) {
          throw new Error('boardConfig is required for shooting phase eligibility check but was not provided');
        }
        if (!boardConfig.wall_hexes) {
          throw new Error('boardConfig.wall_hexes is required for shooting phase eligibility check but was undefined');
        }
        
        const lineOfSight = hasLineOfSight(
          { col: unit.col, row: unit.row },
          { col: enemy.col, row: enemy.row },
          boardConfig.wall_hexes
        );
        if (!lineOfSight.canSee) return false;
       
        return true;
      });
      
      if (!hasValidTargets) return; // No valid targets (Skip, no log)
      
      // ALL conditions met → Add to activation queue → Highlight the unit with a green circle around its icon
      eligibleUnits.push(unit);
    });
    
    setShootingActivationQueue(eligibleUnits);
    setShootingState('WAITING_FOR_ACTIVATION');
    return eligibleUnits.length > 0;
  }, [units, currentPlayer, unitsFled, areUnitsAdjacent, isUnitInRange, hasLineOfSight, boardConfig, clearTargetPreview]);

  const cleanupShootingPhase = useCallback(() => {
    // ATOMIC: Clear preview first to prevent timer leaks
    clearTargetPreview();
    
    // ATOMIC: Reset all shooting state variables together
    setShootingActivationQueue([]);
    setActivationShotLog([]);
    setActiveShootingUnit(null);
    setSelectedShootingTarget(null);
    setShootLeft(undefined);
    setValidTargetsPool([]);
    setShootingState('WAITING_FOR_ACTIVATION');
    
    // ATOMIC: Synchronize UI state in single batch to prevent race conditions
    requestAnimationFrame(() => {
      actions.setAttackPreview(null);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
    });
  }, [clearTargetPreview, actions]);

  // AI_TURN.md: Component 2 - Active Unit Click Handler
  const handleActiveUnitClick = useCallback((unitId: UnitId) => {
    if (!activeShootingUnit || unitId !== activeShootingUnit.id) return;
    
    if (shootingState === 'WAITING_FOR_ACTION') {
      // leftClick(activeUnit) → No effect
      return;
    } else if (shootingState === 'TARGET_PREVIEWING') {
      // leftClick(activeUnit) → Clear target preview and return to WAITING_FOR_ACTION
      clearTargetPreview();
      setSelectedShootingTarget(null);
      setShootingState('WAITING_FOR_ACTION');
    }
  }, [activeShootingUnit, shootingState, clearTargetPreview]);

  // AI_TURN.md: Component 3 - Empty Board Click Handler
  const handleEmptyBoardClick = useCallback(() => {
    if (shootingState === 'WAITING_FOR_ACTION') {
      // left OR Right click anywhere else on the board → STAY
      return;
    } else if (shootingState === 'TARGET_PREVIEWING') {
      // otherClick() → Clear target preview and return to WAITING_FOR_ACTION
      clearTargetPreview();
      setSelectedShootingTarget(null);
      setShootingState('WAITING_FOR_ACTION');
    }
  }, [shootingState, clearTargetPreview]);

  // AI_TURN.md: Component 5 - Postponement Validation Feedback
  const handlePostponementAttempt = useCallback((unitId: UnitId) => {
    if (!activeShootingUnit || shootLeft === undefined) return false;
    
    if (shootLeft !== activeShootingUnit.RNG_NB) {
      // Postponement forbidden - provide user feedback
      console.warn(`Unit ${activeShootingUnit.name || activeShootingUnit.id} must complete its activation - cannot postpone after shooting has started`);
      // Could also trigger a UI notification here
      return false;
    }
    return true;
  }, [activeShootingUnit, shootLeft]);

  // AI_TURN.md: Enhanced handleShootingUnitClick with proper postponement
  const handleShootingUnitClick = useCallback((unitId: UnitId) => {
    if (shootingState === 'WAITING_FOR_ACTIVATION') {
      // leftClick(unitInActivationQueue) - handle async queue state
      let clickedUnit = shootingActivationQueue.find(u => u.id === unitId);
      if (!clickedUnit) {
        // CRITICAL FIX: Use fresh unit lookup when queue is still updating
        clickedUnit = units.find(u => u.id === unitId);
        if (!clickedUnit || !isUnitEligible(clickedUnit)) return;
      }
      
      setActiveShootingUnit(clickedUnit);
      if (clickedUnit.RNG_NB === undefined) {
        throw new Error(`clickedUnit.RNG_NB is required but was undefined for unit ${clickedUnit.id}`);
      }
      setShootLeft(clickedUnit.RNG_NB);
      
      // Build valid_targets pool
      const enemyUnits = units.filter(u => u.player !== clickedUnit.player);
      const friendlyUnits = units.filter(u => u.player === clickedUnit.player && u.id !== clickedUnit.id);
      
      const validTargets = enemyUnits.filter(enemy => {
        if (enemy.CUR_HP === undefined || enemy.CUR_HP <= 0) return false;
        if (!isUnitInRange(clickedUnit, enemy, clickedUnit.RNG_RNG)) return false;
        
        const isEnemyAdjacentToFriendly = friendlyUnits.some(friendly => 
          Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
        );
        if (isEnemyAdjacentToFriendly) return false;
        
        if (!boardConfig) {
          throw new Error('boardConfig is required for valid targets pool but was not provided');
        }
        if (!boardConfig.wall_hexes) {
          throw new Error('boardConfig.wall_hexes is required for valid targets pool but was undefined');
        }
        
        const lineOfSight = hasLineOfSight(
          { col: clickedUnit.col, row: clickedUnit.row },
          { col: enemy.col, row: enemy.row },
          boardConfig.wall_hexes
        );
        if (!lineOfSight.canSee) return false;
        
        return true;
      });
      
      setValidTargetsPool(validTargets);
      setShootingState('WAITING_FOR_ACTION');
      
      // Show shooting preview
      actions.setAttackPreview({ unitId, col: clickedUnit.col, row: clickedUnit.row });
      actions.setSelectedUnitId(unitId);
      actions.setMode("attackPreview");
      
    } else if (shootingState === 'WAITING_FOR_ACTION' || shootingState === 'TARGET_PREVIEWING') {
      // leftClick(otherUnitInActivationQueue) - postponement logic
      if (activeShootingUnit && shootLeft !== undefined && shootLeft === activeShootingUnit.RNG_NB) {
        // Clear any existing target preview
        clearTargetPreview();
        
        // Postpone current unit activation
        setActivationShotLog([]); // Clear stale data
        const clickedUnit = shootingActivationQueue.find(u => u.id === unitId);
        if (!clickedUnit) return;
        
        setActiveShootingUnit(clickedUnit);
        if (clickedUnit.RNG_NB === undefined) {
          throw new Error(`clickedUnit.RNG_NB is required but was undefined for unit ${clickedUnit.id}`);
        }
        setShootLeft(clickedUnit.RNG_NB);
        
        // Build fresh valid_targets pool
        const enemyUnits = units.filter(u => u.player !== clickedUnit.player);
        const friendlyUnits = units.filter(u => u.player === clickedUnit.player && u.id !== clickedUnit.id);
        
        const validTargets = enemyUnits.filter(enemy => {
          if (enemy.CUR_HP === undefined || enemy.CUR_HP <= 0) return false;
          if (!isUnitInRange(clickedUnit, enemy, clickedUnit.RNG_RNG)) return false;
          
          const isEnemyAdjacentToFriendly = friendlyUnits.some(friendly => 
            Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
          );
          if (isEnemyAdjacentToFriendly) return false;
          
          if (!boardConfig) {
            throw new Error('boardConfig is required for postponed valid targets pool but was not provided');
          }
          if (!boardConfig.wall_hexes) {
            throw new Error('boardConfig.wall_hexes is required for postponed valid targets pool but was undefined');
          }
          
          const lineOfSight = hasLineOfSight(
            { col: clickedUnit.col, row: clickedUnit.row },
            { col: enemy.col, row: enemy.row },
            boardConfig.wall_hexes
          );
          if (!lineOfSight.canSee) return false;
          
          return true;
        });
        
        setValidTargetsPool(validTargets);
        setSelectedShootingTarget(null);
        setShootingState('WAITING_FOR_ACTION');
        
        // Update UI
        actions.setAttackPreview({ unitId, col: clickedUnit.col, row: clickedUnit.row });
        actions.setSelectedUnitId(unitId);
      }
      // else: Unit must complete its activation when started (cannot postpone)
    }
  }, [shootingState, shootingActivationQueue, activeShootingUnit, shootLeft, units, isUnitInRange, hasLineOfSight, boardConfig, actions, clearTargetPreview]);

  // AI_TURN.md: Enhanced handleShootingTargetClick with proper cleanup
  const handleShootingTargetClick = useCallback((targetId: UnitId) => {
    if (shootingState === 'WAITING_FOR_ACTION') {
      if (!activeShootingUnit) {
        setShootingState('WAITING_FOR_ACTIVATION');
        return;
      }
      
      // Check for slaughter handling
      if (validTargetsPool.length === 0) {
        // SLAUGHTER HANDLING
        if (shootLeft === undefined) {
          throw new Error('shootLeft is required but was undefined');
        }
        if (shootLeft === activeShootingUnit.RNG_NB) {
          // Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue
          if (gameState.episode_steps === undefined) {
            throw new Error('gameState.episode_steps is required but was undefined');
          }
          gameState.episode_steps = gameState.episode_steps + 1;
          if (gameLog) {
            gameLog.logNoMoveAction(activeShootingUnit, gameState.currentTurn);
          }
        } else {
          // Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue
          if (gameState.episode_steps === undefined) {
            throw new Error('gameState.episode_steps is required but was undefined');
          }
          gameState.episode_steps = gameState.episode_steps + 1;
          actions.addMovedUnit(activeShootingUnit.id);
        }
        
        // Clear activation state and remove green circle
        setShootingActivationQueue(prev => prev.filter(u => u.id !== activeShootingUnit.id));
        setActivationShotLog([]);
        setActiveShootingUnit(null);
        setSelectedShootingTarget(null);
        setShootLeft(undefined);
        setValidTargetsPool([]);
        setShootingState('WAITING_FOR_ACTIVATION');
        
        // Clear UI state
        clearTargetPreview();
        actions.setAttackPreview(null);
        actions.setSelectedUnitId(null);
        actions.setMode("select");
        return;
      }
      
      // leftClick(validTarget)
      const clickedTarget = validTargetsPool.find(u => u.id === targetId);
      if (!clickedTarget) return;
      
      setSelectedShootingTarget(clickedTarget);
      setShootingState('TARGET_PREVIEWING');
      
      // Show target preview with blinking
      const hitProbability = calculateHitProbability(activeShootingUnit);
      const woundProbability = calculateWoundProbability(activeShootingUnit, clickedTarget);
      if (!boardConfig) {
        throw new Error('boardConfig is required for target preview but was not provided');
      }
      if (!boardConfig.wall_hexes) {
        throw new Error('boardConfig.wall_hexes is required for target preview but was undefined');
      }
      const lineOfSight = hasLineOfSight(
        { col: activeShootingUnit.col, row: activeShootingUnit.row },
        { col: clickedTarget.col, row: clickedTarget.row },
        boardConfig.wall_hexes
      );
      const targetInCover = lineOfSight.canSee && lineOfSight.inCover;
      const saveProbability = calculateSaveProbability(activeShootingUnit, clickedTarget, targetInCover);
      const overallProbability = calculateOverallProbability(activeShootingUnit, clickedTarget, targetInCover);
      
      const preview: TargetPreview = {
        targetId,
        shooterId: activeShootingUnit.id,
        currentBlinkStep: 0,
        totalBlinkSteps: 2,
        blinkTimer: null,
        hitProbability,
        woundProbability,
        saveProbability,
        overallProbability
      };
      
      preview.blinkTimer = setInterval(() => {
        preview.currentBlinkStep = (preview.currentBlinkStep + 1) % 2;
        actions.setTargetPreview({ ...preview });
      }, 500);
      
      actions.setTargetPreview(preview);
    } else if (shootingState === 'TARGET_PREVIEWING') {
      if (!activeShootingUnit || !selectedShootingTarget) {
        setShootingState('WAITING_FOR_ACTION');
        return;
      }
      
      // leftClick(sameTarget) - Execute shot
      if (targetId === selectedShootingTarget.id) {
        // Clear preview with proper cleanup
        clearTargetPreview();
        
        // Execute shot with hit/wound/save/damage sequence
        const hitRoll = Math.floor(Math.random() * 6) + 1;
        if (activeShootingUnit.RNG_ATK === undefined) {
          throw new Error(`activeShootingUnit.RNG_ATK is required but was undefined for unit ${activeShootingUnit.id}`);
        }
        const hitSuccess = hitRoll >= activeShootingUnit.RNG_ATK;
        
        let damageDealt = 0;
        let woundRoll = 0;
        let woundSuccess = false;
        let saveRoll = 0;
        let saveSuccess = false;
        let woundTarget = 0;
        let saveTarget = 0;
        
        if (hitSuccess) {
          woundRoll = Math.floor(Math.random() * 6) + 1;
          if (activeShootingUnit.RNG_STR === undefined) {
            throw new Error(`activeShootingUnit.RNG_STR is required but was undefined for unit ${activeShootingUnit.id}`);
          }
          if (selectedShootingTarget.T === undefined) {
            throw new Error(`selectedShootingTarget.T is required but was undefined for unit ${selectedShootingTarget.id}`);
          }
          
          const shooterStr = activeShootingUnit.RNG_STR;
          const targetT = selectedShootingTarget.T;
          woundTarget = shooterStr >= targetT * 2 ? 2 : 
                       shooterStr > targetT ? 3 : 
                       shooterStr === targetT ? 4 : 
                       shooterStr < targetT ? 5 : 6;
          woundSuccess = woundRoll >= woundTarget;
          
          if (woundSuccess) {
            saveRoll = Math.floor(Math.random() * 6) + 1;
            if (selectedShootingTarget.ARMOR_SAVE === undefined) {
              throw new Error(`selectedShootingTarget.ARMOR_SAVE is required but was undefined for unit ${selectedShootingTarget.id}`);
            }
            if (activeShootingUnit.RNG_AP === undefined) {
              throw new Error(`activeShootingUnit.RNG_AP is required but was undefined for unit ${activeShootingUnit.id}`);
            }
            
            const modifiedArmor = selectedShootingTarget.ARMOR_SAVE + activeShootingUnit.RNG_AP;
            if (selectedShootingTarget.INVUL_SAVE === undefined) {
              throw new Error(`selectedShootingTarget.INVUL_SAVE is required but was undefined for unit ${selectedShootingTarget.id}`);
            }
            const invulSave = selectedShootingTarget.INVUL_SAVE;
            saveTarget = (invulSave > 0 && invulSave < modifiedArmor) ? invulSave : modifiedArmor;
            saveSuccess = saveRoll >= saveTarget;
            
            if (!saveSuccess) {
              if (activeShootingUnit.RNG_DMG === undefined) {
                throw new Error(`activeShootingUnit.RNG_DMG is required but was undefined for unit ${activeShootingUnit.id}`);
              }
              damageDealt = activeShootingUnit.RNG_DMG;
            }
          }
        }
        
        // Apply damage and track killed units
        let killedUnitIds: number[] = [];
        if (damageDealt > 0) {
          if (selectedShootingTarget.CUR_HP === undefined) {
            throw new Error('selectedShootingTarget.CUR_HP is required');
          }
          const newHP = selectedShootingTarget.CUR_HP - damageDealt;
          
          if (newHP <= 0) {
            killedUnitIds.push(selectedShootingTarget.id);
            if (gameLog) {
              gameLog.logUnitDeath(selectedShootingTarget, gameState.currentTurn);
            }
            actions.removeUnit(selectedShootingTarget.id);
          } else {
            actions.updateUnit(selectedShootingTarget.id, { CUR_HP: newHP });
          }
        }
        
        // Log individual shot immediately (AI_TURN.md requirement)
        if (gameLog) {
          const shotDetails = [{
            shotNumber: activationShotLog.length + 1,
            attackRoll: hitRoll,
            strengthRoll: woundRoll,
            hitResult: hitSuccess ? 'HIT' : 'MISS' as 'HIT' | 'MISS',
            strengthResult: (hitSuccess && woundSuccess) ? 'SUCCESS' : 'FAILED' as 'SUCCESS' | 'FAILED',
            hitTarget: activeShootingUnit.RNG_ATK,
            woundTarget: hitSuccess ? woundTarget : undefined,
            saveTarget: (hitSuccess && woundSuccess) ? saveTarget : undefined,
            saveRoll: (hitSuccess && woundSuccess) ? saveRoll : undefined,
            saveSuccess: (hitSuccess && woundSuccess) ? saveSuccess : undefined,
            damageDealt: damageDealt
          }];
          gameLog.logShootingAction(activeShootingUnit, selectedShootingTarget, shotDetails, gameState.currentTurn);
        }
        
        // Store shot result
        const shotResult = {
          targetId: selectedShootingTarget.id,
          hitRoll,
          woundRoll,
          saveRoll,
          hitSuccess,
          woundSuccess,
          saveSuccess,
          damageDealt
        };
        setActivationShotLog(prev => [...prev, shotResult]);
        
        // SHOOT_LEFT -= 1
        if (shootLeft === undefined) {
          throw new Error('shootLeft is required but was undefined');
        }
        const newShotsLeft = shootLeft - 1;
        setShootLeft(newShotsLeft);
        actions.updateUnit(activeShootingUnit.id, { SHOOT_LEFT: newShotsLeft });
        
        // selectedTarget = null
        setSelectedShootingTarget(null);
        
        // updateValidTargets() - SLAUGHTER HANDLING after shot
        // CRITICAL FIX: Exclude units killed in this shot from valid targets
        const currentUnits = gameState.units;
        const updatedEnemyUnits = currentUnits.filter(u => 
          u.player !== activeShootingUnit.player && 
          !killedUnitIds.includes(u.id)
        );
        const updatedFriendlyUnits = currentUnits.filter(u => u.player === activeShootingUnit.player && u.id !== activeShootingUnit.id);
        
        const updatedValidTargets = updatedEnemyUnits.filter(enemy => {
          if (enemy.CUR_HP === undefined || enemy.CUR_HP <= 0) return false;
          if (!isUnitInRange(activeShootingUnit, enemy, activeShootingUnit.RNG_RNG)) return false;
          
          const isEnemyAdjacentToFriendly = updatedFriendlyUnits.some(friendly => 
            Math.max(Math.abs(friendly.col - enemy.col), Math.abs(friendly.row - enemy.row)) === 1
          );
          if (isEnemyAdjacentToFriendly) return false;
          
          if (!boardConfig) {
            throw new Error('boardConfig is required for slaughter check but was not provided');
          }
          if (!boardConfig.wall_hexes) {
            throw new Error('boardConfig.wall_hexes is required for slaughter check but was undefined');
          }
          
          const lineOfSight = hasLineOfSight(
            { col: activeShootingUnit.col, row: activeShootingUnit.row },
            { col: enemy.col, row: enemy.row },
            boardConfig.wall_hexes
          );
          if (!lineOfSight.canSee) return false;
          
          return true;
        });
        
        setValidTargetsPool(updatedValidTargets);
        
        // if (shootLeft > 0 AND validTargets.length > 0): GOTO: WAITING_FOR_ACTION
        if (newShotsLeft > 0 && updatedValidTargets.length > 0) {
          setShootingState('WAITING_FOR_ACTION');
        } else {
          // SLAUGHTER HANDLING: No shots left OR no valid targets remain
          // removeFromQueue(activeUnit) + endActivation("shot")
          if (gameState.episode_steps === undefined) {
            throw new Error('gameState.episode_steps is required but was undefined');
          }
          gameState.episode_steps = gameState.episode_steps + 1;
          actions.addMovedUnit(activeShootingUnit.id);
          
          // Clear activation state and remove green circle
          setShootingActivationQueue(prev => prev.filter(u => u.id !== activeShootingUnit.id));
          setActivationShotLog([]);
          setActiveShootingUnit(null);
          setSelectedShootingTarget(null);
          setShootLeft(undefined);
          setValidTargetsPool([]);
          setShootingState('WAITING_FOR_ACTIVATION');
          
          // Clear UI state
          actions.setAttackPreview(null);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
        }
      }
    }
  }, [shootingState, activeShootingUnit, selectedShootingTarget, shootLeft, validTargetsPool, activationShotLog, units, isUnitInRange, hasLineOfSight, boardConfig, gameState, gameLog, actions, calculateHitProbability, calculateWoundProbability, calculateSaveProbability, calculateOverallProbability, clearTargetPreview]);

  // AI_TURN.md: Enhanced handleShootingRightClick with proper cleanup
  const handleShootingRightClick = useCallback((unitId: UnitId) => {
    if ((shootingState === 'WAITING_FOR_ACTION' || shootingState === 'TARGET_PREVIEWING') && 
        activeShootingUnit && unitId === activeShootingUnit.id) {
      // rightClick(activeUnit)
      clearTargetPreview();
      setSelectedShootingTarget(null);
      
      if (shootLeft === undefined) {
        throw new Error('shootLeft is required but was undefined');
      }
      if (shootLeft === activeShootingUnit.RNG_NB) {
        // Result: +1 step, Wait action logged, no Mark → Unit removed from activation queue
        if (gameState.episode_steps === undefined) {
          throw new Error('gameState.episode_steps is required but was undefined');
        }
        gameState.episode_steps = gameState.episode_steps + 1;
        if (gameLog) {
          gameLog.logNoMoveAction(activeShootingUnit, gameState.currentTurn);
        }
      } else {
        // Result: +1 step, Shooting sequence logged, Mark as units_shot → Unit removed from activation queue
        if (gameState.episode_steps === undefined) {
          throw new Error('gameState.episode_steps is required but was undefined');
        }
        gameState.episode_steps = gameState.episode_steps + 1;
        actions.addMovedUnit(activeShootingUnit.id);
      }
      
      // Clear activation state and remove green circle
      setShootingActivationQueue(prev => prev.filter(u => u.id !== activeShootingUnit.id));
      setActivationShotLog([]);
      setActiveShootingUnit(null);
      setSelectedShootingTarget(null);
      setShootLeft(undefined);
      setValidTargetsPool([]);
      setShootingState('WAITING_FOR_ACTIVATION');
      
      // Clear UI state
      actions.setAttackPreview(null);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
    }
  }, [shootingState, activeShootingUnit, shootLeft, gameState, gameLog, actions, clearTargetPreview]);

  // AI_TURN.md: State Validation and Recovery
  const validateShootingState = useCallback(() => {
    try {
      // Validate critical state consistency
      if (shootingState === 'WAITING_FOR_ACTION' && !activeShootingUnit) {
        console.warn('Shooting state machine corrupted: WAITING_FOR_ACTION without active unit');
        setShootingState('WAITING_FOR_ACTIVATION');
        setActiveShootingUnit(null);
        return false;
      }
      
      if (shootingState === 'TARGET_PREVIEWING' && (!activeShootingUnit || !selectedShootingTarget)) {
        console.warn('Shooting state machine corrupted: TARGET_PREVIEWING without required units');
        clearTargetPreview();
        setSelectedShootingTarget(null);
        setShootingState('WAITING_FOR_ACTION');
        return false;
      }
      
      if (activeShootingUnit && shootLeft === undefined) {
        console.warn('Shooting state machine corrupted: active unit without shootLeft');
        if (activeShootingUnit.RNG_NB === undefined) {
          throw new Error(`activeShootingUnit.RNG_NB is required but was undefined for unit ${activeShootingUnit.id}`);
        }
        setShootLeft(activeShootingUnit.RNG_NB);
        return false;
      }
      
      return true;
    } catch (error) {
      console.error('Critical shooting state validation error:', error);
      cleanupShootingPhase();
      return false;
    }
  }, [shootingState, activeShootingUnit, selectedShootingTarget, shootLeft, clearTargetPreview, cleanupShootingPhase]);

  // AI_TURN.md: Component 1 - Universal Event Router
  const handleShootingEvent = useCallback((eventType: 'left_click' | 'right_click', targetType: 'unit' | 'target' | 'board', targetId?: UnitId) => {
    // Handle edge case: empty activation queue mid-phase
    if (shootingActivationQueue.length === 0) {
      cleanupShootingPhase();
      return;
    }
    
    if (eventType === 'right_click') {
      if (targetType === 'unit' && targetId && activeShootingUnit && targetId === activeShootingUnit.id) {
        handleShootingRightClick(targetId);
      }
      return;
    }
    
    // Handle left clicks
    if (eventType === 'left_click') {
      if (targetType === 'unit' && targetId) {
        // Determine if this is an activation queue unit or active unit
        if (shootingActivationQueue.some(u => u.id === targetId)) {
          if (activeShootingUnit && targetId === activeShootingUnit.id) {
            // Click on current active unit
            handleActiveUnitClick(targetId);
          } else {
            // Click on different unit in activation queue - check postponement
            if (activeShootingUnit && !handlePostponementAttempt(targetId)) {
              return; // Postponement forbidden
            }
            handleShootingUnitClick(targetId);
          }
        }
      } else if (targetType === 'target' && targetId) {
        // Click on valid target
        if (validTargetsPool.some(u => u.id === targetId)) {
          handleShootingTargetClick(targetId);
        }
      } else if (targetType === 'board') {
        // Click on empty board
        handleEmptyBoardClick();
      }
    }
  }, [shootingActivationQueue, activeShootingUnit, validTargetsPool, cleanupShootingPhase, handleShootingRightClick, handleActiveUnitClick, handlePostponementAttempt, handleShootingUnitClick, handleShootingTargetClick, handleEmptyBoardClick]);

  // AI_TURN.md: Phase Lifecycle Management
  const enterShootingPhase = useCallback(() => {
    const hasEligibleUnits = initializeShootingPhase();
    if (!hasEligibleUnits) {
      cleanupShootingPhase();
      return false;
    }
    return true;
  }, [initializeShootingPhase, cleanupShootingPhase]);

  const exitShootingPhase = useCallback(() => {
    cleanupShootingPhase();
  }, [cleanupShootingPhase]);

  // AI_TURN.md: Complete UI Integration Layer
  const handleShootingPhaseEvent = useCallback((eventType: 'left_click' | 'right_click', targetType: 'unit' | 'target' | 'board', targetId?: UnitId) => {
    // State validation before processing any event
    if (!validateShootingState()) {
      return;
    }
    
    // Route to universal event handler
    handleShootingEvent(eventType, targetType, targetId);
  }, [validateShootingState, handleShootingEvent]);

  // AI_TURN.md: Override selectUnit during shooting phase
  const selectUnit = useCallback((unitId: UnitId | null) => {
    
    // CRITICAL: Auto-initialize shooting phase on first interaction
    if (phase === "shoot") {
      // Auto-trigger phase entry if not initialized
      if (shootingActivationQueue.length === 0 && shootingState === 'WAITING_FOR_ACTIVATION') {
        const hasEligibleUnits = enterShootingPhase();
        if (!hasEligibleUnits) {
          return; // Phase will auto-advance
        }
      }
      
      if (unitId === null) {
        handleShootingPhaseEvent('left_click', 'board');
        return;
      }
      
      // CRITICAL FIX: Direct target click during shooting phase
      if (activeShootingUnit && shootingState === 'WAITING_FOR_ACTION') {
        const clickedUnit = units.find(u => u.id === unitId);
        if (clickedUnit && clickedUnit.player !== activeShootingUnit.player) {
          handleShootingTargetClick(unitId);
          return;
        }
      }
      
      // CRITICAL FIX: Use fresh state from enterShootingPhase result instead of stale queue state
      const clickedUnit = units.find(u => u.id === unitId);
      if (clickedUnit && isUnitEligible(clickedUnit) && shootingState === 'WAITING_FOR_ACTIVATION') {
        handleShootingUnitClick(unitId);
        return;
      }
      
      // Route other clicks through shooting state machine
      handleShootingPhaseEvent('left_click', 'unit', unitId);
      return;
    }

    // Prevent unit selection during shooting sequence
    if (shootingPhaseState.singleShotState?.isActive) {
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
    
    if (!unit) {
      return;
    }
    
    const eligible = isUnitEligible(unit);
    
    if (!eligible) {
      // Call it again to see the debug logs
      isUnitEligible(unit);
    }
    
    if (!eligible) {
      return;
    }

    // Special handling for move phase - second click marks as moved (or chose not to move)
    if (phase === "move" && selectedUnitId === unitId) {
      // Log the "no move" decision
      if (gameLog) {
        gameLog.logNoMoveAction(unit, gameState.currentTurn);
      }
      // AI_TURN.md: Built-in step counting (+1 step for wait)
      if (gameState.episode_steps === undefined) {
        throw new Error('gameState.episode_steps is required but was undefined');
      }
      gameState.episode_steps = gameState.episode_steps + 1;
      
      actions.addMovedUnit(unitId);
      actions.setSelectedUnitId(null);
      actions.setMovePreview(null);
      actions.setMode("select");
      return;
    }

    // Special handling for charge phase
    if (phase === "charge") {
      if (!gameState.unitChargeRolls) {
        throw new Error('gameState.unitChargeRolls is required but was undefined');
      }
      const existingRoll = gameState.unitChargeRolls[unitId];
      
      if (!existingRoll) {
        // First time selecting this unit - roll 2d6 for charge distance
        const die1 = Math.floor(Math.random() * 6) + 1;
        const die2 = Math.floor(Math.random() * 6) + 1;
        const chargeRoll = die1 + die2;
        
        // Check if any enemies within 12 hexes are also within the rolled charge distance
        const enemyUnits = units.filter(u => u.player !== unit.player);
        
        const enemiesInRange = enemyUnits.filter(enemy => {
          // First check if enemy is within 12 hexes (eligibility already passed this)
          const cube1 = offsetToCube(unit.col, unit.row);
          const cube2 = offsetToCube(enemy.col, enemy.row);
          const hexDistance = cubeDistance(cube1, cube2);
          
          // Check if enemy is within rolled charge distance (12-hex limit already checked in eligibility)
          if (hexDistance > chargeRoll) return false;
          if (hexDistance > 12) return false;
          
          // Use same pathfinding logic as eligibility check
          if (boardConfig && boardConfig.wall_hexes) {
            const wallHexSet = new Set((boardConfig.wall_hexes as [number, number][]).map(([c, r]) => `${c},${r}`));
            const isReachable = checkPathfindingReachable(unit, enemy, wallHexSet, chargeRoll);
            if (!isReachable) return false;
          }
          
          return true;
        });
        
        const canCharge = enemiesInRange.length > 0;

        // Log the charge roll with correct format using proper addEvent method
        if (gameLog) {
          // Use the internal addEvent method to ensure proper ordering (newest first)
          const chargeEvent = {
            id: `charge-roll-${Date.now()}-${unit.id}`,
            timestamp: new Date(),
            type: 'charge' as const,
            message: canCharge 
              ? `Unit ${unit.name} CHARGE ROLL : ${chargeRoll} : Enemy unit(s) in range`
              : `Unit ${unit.name} CHARGE ROLL : ${chargeRoll} : No enemy unit(s) in range`,
            turnNumber: gameState.currentTurn,
            phase: 'charge',
            player: unit.player,
            unitType: unit.type,
            unitId: unit.id
          };
          gameLog.events.unshift(chargeEvent);
        }
        
        // Show popup with exact format required
        actions.showChargeRollPopup(unitId, chargeRoll, !canCharge);
        
        // Store the roll and handle game logic
        actions.setUnitChargeRoll(unitId, chargeRoll);
        
        // Continue with state management
        if (canCharge) {
          actions.setSelectedUnitId(unitId);
          actions.setMode("chargePreview");
        } else {
          actions.addChargedUnit(unitId);
          actions.resetUnitChargeRoll(unitId);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
        }

        return;
      } else {
        // Unit already has a charge roll
        if (selectedUnitId === unitId) {
          // Second click on same unit - cancel charge and end activation
          if (gameLog) {
            const cancelEvent = {
              id: `charge-cancel-${Date.now()}-${unit.id}`,
              timestamp: new Date(),
              type: 'charge_cancel' as const,
              message: `Unit ${unit.name} CHARGE CANCELLED`,
              turnNumber: gameState.currentTurn,
              phase: 'charge',
              player: unit.player,
              unitType: unit.type,
              unitId: unit.id
            };
            gameLog.events.unshift(cancelEvent);
          }
          actions.resetUnitChargeRoll(unitId);
          actions.addChargedUnit(unitId);
          actions.setSelectedUnitId(null);
          actions.setMode("select");
        } else {
          // Different unit with existing roll - show preview
          actions.setSelectedUnitId(unitId);
          actions.setMode("chargePreview");
        }
        return;
      }
    }

    // Special handling for combat phase
    if (phase === "combat") {
      // Check if unit has valid targets in combat range
      const enemies = units.filter(u => u.player !== unit.player);
      if (unit.CC_RNG === undefined) {
        throw new Error(`unit.CC_RNG is required but was undefined for unit ${unit.id}`);
      }
      const combatRange = unit.CC_RNG;
      const hasValidTargets = enemies.some(enemy => {
        const distance = Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row));
        return distance === combatRange;
      });
      
      if (!hasValidTargets) {
        // No targets in range - end activation immediately
        actions.addAttackedUnit(unitId);
        actions.setSelectedUnitId(null);
        actions.setMode("select");
        return;
      }
      
      // Has valid targets - show attack preview for adjacent enemies
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
  }, [phase, findUnit, isUnitEligible, selectedUnitId, actions, currentPlayer, unitsMoved, unitsCharged, unitsAttacked, unitsFled, combatSubPhase, combatActivePlayer, handleShootingPhaseEvent, shootingPhaseState, gameLog, gameState, units, checkPathfindingReachable, boardConfig]);

  // AI_TURN.md: Right-click handler for UI integration
  const handleRightClick = useCallback((unitId: UnitId) => {
    if (phase === "shoot") {
      handleShootingPhaseEvent('right_click', 'unit', unitId);
    }
  }, [phase, handleShootingPhaseEvent]);

  // AI_TURN.md: Board click handler for UI integration  
  const handleBoardClick = useCallback(() => {
    if (phase === "shoot") {
      handleShootingPhaseEvent('left_click', 'board');
    }
  }, [phase, handleShootingPhaseEvent]);

  // AI_TURN.md: Complete UI integration - handleShoot with auto-initialization
  const handleShoot = useCallback((shooterId: UnitId, targetId: UnitId) => {
    
    // Auto-initialize shooting phase if needed
    if (shootingActivationQueue.length === 0 && shootingState === 'WAITING_FOR_ACTIVATION') {
      const hasEligibleUnits = enterShootingPhase();
      if (!hasEligibleUnits) {
        return; // No eligible units, phase will advance
      }
    }
    
    // Determine event type and route appropriately
    if (validTargetsPool.some(u => u.id === targetId)) {
      handleShootingPhaseEvent('left_click', 'target', targetId);
    } else if (shootingActivationQueue.some(u => u.id === shooterId)) {
      handleShootingPhaseEvent('left_click', 'unit', shooterId);
      handleShootingPhaseEvent('left_click', 'target', targetId);
    } else {
      handleShootingPhaseEvent('left_click', 'board');
    }
  }, [shootingActivationQueue, validTargetsPool, handleShootingPhaseEvent, shootingState, enterShootingPhase]);

  const handleCombatAttack = useCallback((attackerId: UnitId, targetId: UnitId | null) => {
    if (targetId === null) {
      // Skip attack but mark as attacked
      actions.addAttackedUnit(attackerId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    const attacker = findUnit(attackerId);
    const initialTarget = findUnit(targetId);
    
    if (!attacker || !initialTarget) {
      return;
    }

    // PREVENT FRIENDLY FIRE: Cannot attack friendly units
    if (initialTarget.player === attacker.player) {
      return;
    }

    // Check if units are within combat range
    const distance = Math.max(
      Math.abs(attacker.col - initialTarget.col),
      Math.abs(attacker.row - initialTarget.row)
    );
    if (attacker.CC_RNG === undefined) {
      throw new Error(`attacker.CC_RNG is required but was undefined for unit ${attacker.id}`);
    }
    const combatRange = attacker.CC_RNG;
    if (distance > combatRange) {
      return;
    }

    // Initialize ATTACK_LEFT if not set
    if (attacker.ATTACK_LEFT === undefined) {
      actions.updateUnit(attackerId, { ATTACK_LEFT: attacker.CC_NB });
      return; // Return to let state update, then continue
    }

    if (attacker.ATTACK_LEFT <= 0) {
      actions.addAttackedUnit(attackerId);
      actions.setSelectedUnitId(null);
      actions.setMode("select");
      return;
    }

    // AI_TURN.md: Execute ALL CC_NB attacks in one activation
    let currentAttacksLeft = attacker.ATTACK_LEFT;
    let attackNumber = 1;
    
    // ATTACK LOOP: Execute all remaining attacks until exhausted or no valid targets
    while (currentAttacksLeft > 0) {
      // Get fresh attacker state
      const currentAttacker = findUnit(attackerId);
      if (!currentAttacker) break;
      
      // AI_TURN.md: Build valid_targets pool FRESH each attack iteration
      const validTargets = units.filter(enemy => {
        if (enemy.player === currentAttacker.player) return false;
        if (enemy.CUR_HP === undefined || enemy.CUR_HP <= 0) return false; // CRITICAL: Exclude dead units
        const dist = Math.max(Math.abs(currentAttacker.col - enemy.col), Math.abs(currentAttacker.row - enemy.row));
        return dist === combatRange;
      });
      
      if (validTargets.length === 0) {
        // AI_TURN.md: Slaughter handling - no valid targets remain
        break;
      }
      
      // AI_TURN.md: Select first available living target (dynamic targeting)
      let currentTarget = validTargets[0];
      
      // If no valid targets found, break (slaughter handling)
      if (!currentTarget) {
        break;
      }
      
      // AI_TURN.md: Execute single attack (Hit → Wound → Save → Damage)
      const hitRoll = Math.floor(Math.random() * 6) + 1;
      if (currentAttacker.CC_ATK === undefined) {
        throw new Error(`currentAttacker.CC_ATK is required but was undefined for unit ${currentAttacker.id}`);
      }
      const hitSuccess = hitRoll >= currentAttacker.CC_ATK;

      let damageDealt = 0;
      let woundRoll = 0;
      let woundSuccess = false;
      let saveRoll = 0;
      let saveSuccess = false;
      let woundTarget = 0;
      let saveTarget = 0;

      if (hitSuccess) {
        // Hit - proceed to wound roll
        woundRoll = Math.floor(Math.random() * 6) + 1;
        if (currentAttacker.CC_STR === undefined) {
          throw new Error(`currentAttacker.CC_STR is required but was undefined for unit ${currentAttacker.id}`);
        }
        if (currentTarget.T === undefined) {
          throw new Error(`currentTarget.T is required but was undefined for unit ${currentTarget.id}`);
        }
        
        const attackerStr = currentAttacker.CC_STR;
        const targetT = currentTarget.T;
        woundTarget = attackerStr >= targetT * 2 ? 2 : 
                     attackerStr > targetT ? 3 : 
                     attackerStr === targetT ? 4 : 
                     attackerStr < targetT ? 5 : 6;
        woundSuccess = woundRoll >= woundTarget;

        if (woundSuccess) {
          // Wound successful - proceed to save roll
          saveRoll = Math.floor(Math.random() * 6) + 1;
          if (currentTarget.ARMOR_SAVE === undefined) {
            throw new Error(`currentTarget.ARMOR_SAVE is required but was undefined for unit ${currentTarget.id}`);
          }
          if (currentAttacker.CC_AP === undefined) {
            throw new Error(`currentAttacker.CC_AP is required but was undefined for unit ${currentAttacker.id}`);
          }
          
          const modifiedArmor = currentTarget.ARMOR_SAVE + currentAttacker.CC_AP;
          if (currentTarget.INVUL_SAVE === undefined) {
            throw new Error(`currentTarget.INVUL_SAVE is required but was undefined for unit ${currentTarget.id}`);
          }
          const invulSave = currentTarget.INVUL_SAVE;
          saveTarget = (invulSave > 0 && invulSave < modifiedArmor) ? invulSave : modifiedArmor;
          saveSuccess = saveRoll >= saveTarget;

          if (!saveSuccess) {
            if (currentAttacker.CC_DMG === undefined) {
              throw new Error(`currentAttacker.CC_DMG is required but was undefined for unit ${currentAttacker.id}`);
            }
            damageDealt = currentAttacker.CC_DMG;
          }
        }
      }

      // Log the combat action
      if (gameLog) {
        const combatDetails = [{
          shotNumber: attackNumber,
          attackRoll: hitRoll,
          strengthRoll: woundRoll,
          hitResult: hitSuccess ? 'HIT' : 'MISS' as 'HIT' | 'MISS',
          strengthResult: (hitSuccess && woundSuccess) ? 'SUCCESS' : 'FAILED' as 'SUCCESS' | 'FAILED',
          hitTarget: currentAttacker.CC_ATK,
          woundTarget: hitSuccess ? woundTarget : undefined,
          saveTarget: (hitSuccess && woundSuccess) ? saveTarget : undefined,
          saveRoll: (hitSuccess && woundSuccess) ? saveRoll : undefined,
          saveSuccess: (hitSuccess && woundSuccess) ? saveSuccess : undefined,
          damageDealt: damageDealt
        }];
        gameLog.logCombatAction(currentAttacker, currentTarget, combatDetails, gameState.currentTurn);
      }

      // Apply damage
      if (damageDealt > 0) {
        if (currentTarget.CUR_HP === undefined) {
          throw new Error('currentTarget.CUR_HP is required');
        }
        const newHP = currentTarget.CUR_HP - damageDealt;

        if (newHP <= 0) {
          // Log unit death AFTER the attack that killed it
          if (gameLog) {
            gameLog.logUnitDeath(currentTarget, gameState.currentTurn);
          }
          actions.removeUnit(currentTarget.id);
          // Target is dead - continue to next attack with fresh target selection
        } else {
          actions.updateUnit(currentTarget.id, { CUR_HP: newHP });
        }
      }

      // Decrement attacks and update attacker
      currentAttacksLeft -= 1;
      attackNumber += 1;
    }

    // AI_TURN.md: Built-in step counting (+1 step for combat)
    if (gameState.episode_steps === undefined) {
      throw new Error('gameState.episode_steps is required but was undefined');
    }
    gameState.episode_steps = gameState.episode_steps + 1;

    // Update final ATTACK_LEFT state
    actions.updateUnit(attackerId, { ATTACK_LEFT: currentAttacksLeft });

    // AI_TURN.md: Only mark as attacked if NO adjacent enemies remain (slaughter handling)
    const finalAttacker = findUnit(attackerId);
    if (finalAttacker) {
      // Get FRESH unit state after the combat loop completed
      const currentUnits = gameState.units;
      const remainingEnemies = currentUnits.filter(enemy => {
        if (enemy.player === finalAttacker.player) return false;
        if (enemy.CUR_HP === undefined || enemy.CUR_HP <= 0) return false;
        const dist = Math.max(Math.abs(finalAttacker.col - enemy.col), Math.abs(finalAttacker.row - enemy.row));
        return dist === combatRange;
      });
      
      if (remainingEnemies.length === 0) {
        // No adjacent enemies - mark as attacked (slaughter handling)
        actions.addAttackedUnit(attackerId);
      }
      // If adjacent enemies exist, unit remains eligible for future activations
    }

    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [findUnit, actions, gameState.currentTurn, gameLog, units]);

  const handleCharge = useCallback((chargerId: UnitId, targetId: UnitId) => {
    const charger = findUnit(chargerId);
    const target = findUnit(targetId);
    if (!charger) {
      return;
    }
    if (!target) {
      return;
    }

    if (gameLog) {
      gameLog.logChargeAction(charger, target, charger.col, charger.row, target.col, target.row, gameState.currentTurn);
    }

    actions.updateUnit(chargerId, { hasChargedThisTurn: true });
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit, gameLog, gameState.currentTurn]);

  const moveCharger = useCallback((chargerId: number, destCol: number, destRow: number) => {
    const charger = findUnit(chargerId);
    if (!charger) {
      return;
    }
    
    // Create charge event for game log
    if (gameLog) {
      const chargeEvent = {
        id: `charge-move-${Date.now()}-${charger.id}`,
        timestamp: new Date(),
        type: 'charge' as const,
        message: `Unit ${charger.name} CHARGED from (${charger.col}, ${charger.row}) to (${destCol}, ${destRow})`,
        turnNumber: gameState.currentTurn,
        phase: 'charge',
        player: charger.player,
        unitType: charger.type,
        unitId: charger.id
      };
      gameLog.events.unshift(chargeEvent);
    }
    
    // AI_TURN.md: Built-in step counting (+1 step for charge)
    if (gameState.episode_steps === undefined) {
      throw new Error('gameState.episode_steps is required but was undefined');
    }
    gameState.episode_steps = gameState.episode_steps + 1;

    // Move unit to destination
    actions.updateUnit(chargerId, { col: destCol, row: destRow, hasChargedThisTurn: true });
    
    // Clean up charge state
    actions.resetUnitChargeRoll(chargerId);
    actions.addChargedUnit(chargerId);
    
    // Reset UI state
    actions.setSelectedUnitId(null);
    actions.setMode("select");
    actions.updateUnit(chargerId, { col: destCol, row: destRow, hasChargedThisTurn: true });
    actions.resetUnitChargeRoll(chargerId);
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
    setTimeout(() => {
    }, 16);
  }, [actions, findUnit, gameLog, gameState.currentTurn]);

  const cancelCharge = useCallback(() => {
    if (selectedUnitId !== null) {
      const unit = findUnit(selectedUnitId);
      if (!unit) {
        // Handle error silently
      } else {
        if (unitsCharged.includes(selectedUnitId)) {
          // Already charged, skip
        } else {
          if (gameLog) {
            gameLog.logChargeCancellation(unit, gameState.currentTurn);
          }
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
    const charger = findUnit(chargerId);
    if (!charger) {
      return;
    }

    if (gameLog) {
      const enemyUnits = units.filter(u => u.player !== charger.player);
      const target = enemyUnits.find(enemy => 
        Math.max(Math.abs(charger.col - enemy.col), Math.abs(charger.row - enemy.row)) <= 1
      );
      if (target) {
        gameLog.logChargeAction(charger, target, charger.col, charger.row, charger.col, charger.row, gameState.currentTurn);
      }
    }

    actions.updateUnit(chargerId, { hasChargedThisTurn: true });
    actions.addChargedUnit(chargerId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [actions, findUnit, gameLog, gameState.currentTurn, units]);

  const directMove = useCallback((unitId: UnitId, col: number, row: number) => {
    const unit = findUnit(unitId);
    if (!unit || !isUnitEligible(unit) || phase !== "move") return;

    // Check if unit is fleeing (was adjacent to enemy at start of move, ends move not adjacent)
    const enemyUnits = units.filter(u => u.player !== unit.player);
    const wasAdjacentToEnemy = enemyUnits.some(enemy => 
      Math.max(Math.abs(unit.col - enemy.col), Math.abs(unit.row - enemy.row)) === 1
    );
    
    if (wasAdjacentToEnemy) {
      const willBeAdjacentToEnemy = enemyUnits.some(enemy => 
        Math.max(Math.abs(col - enemy.col), Math.abs(row - enemy.row)) === 1
      );
      
      if (!willBeAdjacentToEnemy) {
        actions.addFledUnit(unitId);
      }
    }

    // Log the move action
    if (gameLog) {
      gameLog.logMoveAction(unit, unit.col, unit.row, col, row, gameState.currentTurn);
    }

    // Move the unit directly
    actions.updateUnit(unitId, { col, row });
    actions.addMovedUnit(unitId);
    actions.setSelectedUnitId(null);
    actions.setMode("select");
  }, [findUnit, isUnitEligible, phase, units, actions, gameLog, gameState.currentTurn]);

  // Calculate valid charge destinations for a unit (used by Board.tsx)
  const getChargeDestinations = useCallback((unitId: UnitId): { col: number; row: number }[] => {
    const unit = findUnit(unitId);
    if (!unit) return [];
    
    const chargeDistance = gameState.unitChargeRolls?.[unitId];
    if (!chargeDistance) return [];
    
    if (!boardConfig) {
      throw new Error('boardConfig is required for charge destinations but was not provided');
    }
    if (!boardConfig.cols || !boardConfig.rows) {
      throw new Error('boardConfig.cols and boardConfig.rows are required for charge destinations but were undefined');
    }
    
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    
    const visited = new Map<string, number>();
    const queue: [number, number, number][] = [[unit.col, unit.row, 0]];
    const validDestinations: { col: number; row: number }[] = [];

    // Cube directions for proper hex neighbors
    const cubeDirections = [
      [1, -1, 0], [1, 0, -1], [0, 1, -1], 
      [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
    ];

    // Collect forbidden hexes (walls + other units)
    const forbiddenSet = new Set<string>();
    
    // Add wall hexes
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes as [number, number][]).map(([c, r]: [number, number]) => `${c},${r}`)
    );
    wallHexSet.forEach(wallHex => forbiddenSet.add(wallHex));
    
    // Add other units (but not the charging unit itself)
    units.forEach(u => {
      if (u.id !== unit.id) {
        forbiddenSet.add(`${u.col},${u.row}`);
      }
    });

    while (queue.length > 0) {
      const next = queue.shift();
      if (!next) continue;
      const [col, row, steps] = next;
      const key = `${col},${row}`;
      
      if (visited.has(key) && steps >= visited.get(key)!) {
        continue;
      }

      visited.set(key, steps);

      // Skip forbidden positions (can't move through them)
      if (forbiddenSet.has(key) && steps > 0) {
        continue;
      }

      // Check if this position is adjacent to a chargeable enemy and within charge range
      if (steps > 0 && steps <= chargeDistance && !forbiddenSet.has(key)) {
        const chargeableEnemyAdjacent = units.some(u => {
          if (u.player === unit.player) return false;
          
          // Check if this enemy is adjacent to the destination using cube coordinates for proper hex adjacency
          const destCube = offsetToCube(col, row);
          const targetEnemyCube = offsetToCube(u.col, u.row);
          const hexDistance = cubeDistance(destCube, targetEnemyCube);
          const isAdjacent = hexDistance === 1;
          if (!isAdjacent) return false;
          
          // Additional check: enemy must be within the original charge eligibility range (12 hexes)
          const enemyCube = offsetToCube(u.col, u.row);
          const unitCube = offsetToCube(unit.col, unit.row);
          const distanceToEnemy = cubeDistance(unitCube, enemyCube);
          if (distanceToEnemy > 12) return false;
          
          return true;
        });
        
        if (chargeableEnemyAdjacent) {
          validDestinations.push({ col, row });
        }
      }

      if (steps >= chargeDistance) {
        continue;
      }

      // Explore neighbors using cube coordinates
      const currentCube = offsetToCube(col, row);
      for (const [dx, dy, dz] of cubeDirections) {
        const neighborCube = {
          x: currentCube.x + dx,
          y: currentCube.y + dy,
          z: currentCube.z + dz
        };
        
        const ncol = neighborCube.x;
        const nrow = neighborCube.z + ((neighborCube.x - (neighborCube.x & 1)) >> 1);
        const nkey = `${ncol},${nrow}`;
        const nextSteps = steps + 1;

        if (
          ncol >= 0 && ncol < BOARD_COLS &&
          nrow >= 0 && nrow < BOARD_ROWS &&
          nextSteps <= chargeDistance &&
          (!visited.has(nkey) || visited.get(nkey)! > nextSteps)
        ) {
          queue.push([ncol, nrow, nextSteps]);
        }
      }
    }

    return validDestinations;
  }, [findUnit, gameState.unitChargeRolls, boardConfig, units, checkPathfindingReachable]);

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
    isUnitEligible, // Expose the eligibility function
    getChargeDestinations, // Expose the charge destinations function
    directMove, // Expose the direct move function
    // AI_TURN.md: New integration functions for UI layer
    handleRightClick,
    handleBoardClick,
    enterShootingPhase,
    exitShootingPhase,
    validateShootingState,
    handleShootingPhaseEvent,
    // rollD6 removed - now using shared gameRules import
  };
};