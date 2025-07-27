// shared/gameRules.ts - EXACT implementations from current frontend and AI code
// This file contains ZERO modifications to existing mechanics

export interface Unit {
  id: number;
  name: string;
  type: string;
  player: number;
  col: number;
  row: number;
  color: number;
  BASE: number;
  MOVE: number;
  HP_MAX: number;
  CUR_HP?: number;
  RNG_RNG: number;
  RNG_DMG: number;
  CC_DMG: number;
  CC_RNG?: number;
  ICON: string;
  ICON_SCALE?: number;
  // Dice system properties
  RNG_NB?: number;
  RNG_ATK?: number;
  RNG_STR?: number;
  RNG_AP?: number;
  CC_NB?: number;
  CC_ATK?: number;
  CC_STR?: number;
  CC_AP?: number;
  T?: number;
  ARMOR_SAVE?: number;
  INVUL_SAVE?: number;
  SHOOT_LEFT?: number;
  ATTACK_LEFT?: number;
  hasChargedThisTurn?: boolean;
}

export interface Position {
  col: number;
  row: number;
}

// === HEX GEOMETRY (EXACT from frontend/src/utils/gameHelpers.ts) ===

export function offsetToCube(col: number, row: number): { x: number; y: number; z: number } {
  const x = col;
  const z = row - ((col - (col & 1)) >> 1);
  const y = -x - z;
  return { x, y, z };
}

export function cubeDistance(
  a: { x: number; y: number; z: number },
  b: { x: number; y: number; z: number }
): number {
  return Math.max(
    Math.abs(a.x - b.x),
    Math.abs(a.y - b.y),
    Math.abs(a.z - b.z)
  );
}

export function getHexDistance(pos1: Position, pos2: Position): number {
  const cube1 = offsetToCube(pos1.col, pos1.row);
  const cube2 = offsetToCube(pos2.col, pos2.row);
  return cubeDistance(cube1, cube2);
}

export function areUnitsAdjacent(unit1: Unit, unit2: Unit): boolean {
  return getHexDistance(
    { col: unit1.col, row: unit1.row },
    { col: unit2.col, row: unit2.row }
  ) === 1;
}

export function isUnitInRange(attacker: Unit, target: Unit, range: number): boolean {
  return getHexDistance(
    { col: attacker.col, row: attacker.row },
    { col: target.col, row: target.row }
  ) <= range;
}

// === DICE SYSTEM (EXACT from frontend/src/hooks/useGameActions.ts) ===

export function rollD6(): number {
  return Math.floor(Math.random() * 6) + 1;
}

export function calculateWoundTarget(strength: number, toughness: number): number {
  if (strength * 2 <= toughness) return 6;      // S*2 <= T: wound on 6+
  if (strength < toughness) return 5;           // S < T: wound on 5+
  if (strength === toughness) return 4;         // S = T: wound on 4+
  if (strength > toughness) return 3;           // S > T: wound on 3+
  if (strength * 2 >= toughness) return 2;     // S*2 >= T: wound on 2+
  return 6; // fallback
}

export function calculateSaveTarget(armorSave: number, invulSave: number, armorPenetration: number): number {
  const modifiedArmor = armorSave + armorPenetration;
  
  // Use invulnerable save if it's better than modified armor save (and invul > 0)
  if (invulSave > 0 && invulSave < modifiedArmor) {
    return invulSave;
  }
  
  return modifiedArmor;
}

// === SHOOTING SYSTEM (EXACT from frontend/src/hooks/useGameActions.ts) ===

export interface ShootingResult {
  totalDamage: number;
  summary: {
    totalShots: number;
    hits: number;
    wounds: number;
    failedSaves: number;
  };
}

export function executeShootingSequence(shooter: any, target: any, targetInCover: boolean = false): ShootingResult {
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
    
    // Step 5: Armor save (with cover bonus)
    const saveRoll = rollD6();
    let baseArmorSave = target.ARMOR_SAVE;
    let invulSave = target.INVUL_SAVE;
    let armorPenetration = shooter.RNG_AP;
    
    // Apply cover bonus - +1 to armor save (better save)
    if (targetInCover) {
      baseArmorSave = Math.max(2, baseArmorSave - 1); // Improve armor save by 1, minimum 2+
      // Note: Invulnerable saves are not affected by cover
    }
    
    const saveTarget = calculateSaveTarget(
      baseArmorSave, 
      invulSave, 
      armorPenetration
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
}

// === COMBAT SYSTEM (EXACT from frontend/src/utils/CombatSequenceManager.ts) ===

export function executeCombatSequence(attacker: Unit, target: Unit): ShootingResult {
  // Get number of attacks
  if (attacker.CC_NB === undefined) {
    throw new Error('attacker.CC_NB is required');
  }
  const numberOfAttacks = attacker.CC_NB;

  let totalDamage = 0;
  let hits = 0;
  let wounds = 0;
  let failedSaves = 0;

  // Process each attack
  for (let attack = 1; attack <= numberOfAttacks; attack++) {
    // Hit roll
    const hitRoll = rollD6();
    if (attacker.CC_ATK === undefined) {
      throw new Error('attacker.CC_ATK is required');
    }
    const hitTarget = attacker.CC_ATK;
    const didHit = hitRoll >= hitTarget;
    
    if (!didHit) continue; // Miss - next attack
    hits++;
    
    // Wound roll
    const woundRoll = rollD6();
    if (attacker.CC_STR === undefined) {
      throw new Error('attacker.CC_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
    const woundTarget = calculateWoundTarget(attacker.CC_STR, target.T);
    const didWound = woundRoll >= woundTarget;
    
    if (!didWound) continue; // Failed to wound - next attack
    wounds++;
    
    // Save roll
    const saveRoll = rollD6();
    if (target.ARMOR_SAVE === undefined) {
      throw new Error('target.ARMOR_SAVE is required');
    }
    if (attacker.CC_AP === undefined) {
      throw new Error('attacker.CC_AP is required');
    }
    const saveTarget = calculateSaveTarget(
      target.ARMOR_SAVE, 
      target.INVUL_SAVE || 0, 
      attacker.CC_AP
    );
    const savedWound = saveRoll >= saveTarget;
    
    if (savedWound) continue; // Save successful - next attack
    failedSaves++;
    
    // Inflict damage
    if (attacker.CC_DMG === undefined) {
      throw new Error('attacker.CC_DMG is required');
    }
    totalDamage += attacker.CC_DMG;
  }

  return {
    totalDamage,
    summary: {
      totalShots: numberOfAttacks, // Reuse same interface
      hits,
      wounds,
      failedSaves
    }
  };
}

// === CHARGE SYSTEM (EXACT from frontend/src/hooks/useGameActions.ts) ===

export const CHARGE_MAX_DISTANCE = 12; // Fixed 12-hex charge limit

export function roll2D6(): number {
  return rollD6() + rollD6();
}

export function canUnitChargeBasic(unit: Unit, enemyUnits: Unit[], unitsFled: number[], unitsCharged: number[]): boolean {
  // Basic eligibility checks (EXACT from frontend isUnitEligible)
  if (unitsCharged.includes(unit.id)) return false; // Already charged
  if (unitsFled.includes(unit.id)) return false;    // Fled units can't charge
  
  // Check if adjacent to any enemy (already in combat)
  const isAdjacent = enemyUnits.some(enemy => enemy.player !== unit.player && areUnitsAdjacent(unit, enemy));
  if (isAdjacent) return false;
  
  // Check if any enemies within 12-hex charge range (EXACT from frontend)
  const hasEnemiesWithin12Hexes = enemyUnits.some(enemy => {
    if (enemy.player === unit.player) return false;
    const cube1 = offsetToCube(unit.col, unit.row);
    const cube2 = offsetToCube(enemy.col, enemy.row);
    const hexDistance = cubeDistance(cube1, cube2);
    
    if (hexDistance > 12) return false;
    
    // TODO: Add pathfinding logic here when walls implemented
    return true;
  });
  
  return hasEnemiesWithin12Hexes;
}

// === ROUND CUBE COORDINATES (EXACT from frontend/src/utils/gameHelpers.ts) ===

export function roundCube(cube: { x: number; y: number; z: number }): { x: number; y: number; z: number } {
  let rx = Math.round(cube.x);
  let ry = Math.round(cube.y);
  let rz = Math.round(cube.z);
  
  const xDiff = Math.abs(rx - cube.x);
  const yDiff = Math.abs(ry - cube.y);
  const zDiff = Math.abs(rz - cube.z);
  
  if (xDiff > yDiff && xDiff > zDiff) {
    rx = -ry - rz;
  } else if (yDiff > zDiff) {
    ry = -rx - rz;
  } else {
    rz = -rx - ry;
  }
  
  return { x: rx, y: ry, z: rz };
}

// === HEX LINE DRAWING (EXACT from frontend/src/utils/gameHelpers.ts) ===

export function getHexLine(startCol: number, startRow: number, endCol: number, endRow: number): Position[] {
  // Convert to cube coordinates for proper line drawing
  const startCube = offsetToCube(startCol, startRow);
  const endCube = offsetToCube(endCol, endRow);
  
  const distance = cubeDistance(startCube, endCube);
  if (distance === 0) {
    return [{ col: startCol, row: startRow }];
  }
  
  const hexes: Position[] = [];
  const steps = Math.max(distance * 3, 20); // Use many steps for accuracy
  
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    
    // Linear interpolation in cube coordinates
    const x = startCube.x + (endCube.x - startCube.x) * t;
    const y = startCube.y + (endCube.y - startCube.y) * t;
    const z = startCube.z + (endCube.z - startCube.z) * t;
    
    // Round to nearest hex
    const roundedCube = roundCube({ x, y, z });
    
    // Convert back to offset coordinates
    const col = roundedCube.x;
    const row = roundedCube.z + ((roundedCube.x - (roundedCube.x & 1)) >> 1);
    
    // Add hex if not already in list
    const hexKey = `${col},${row}`;
    if (!hexes.some(h => `${h.col},${h.row}` === hexKey)) {
      hexes.push({ col, row });
    }
  }
  
  return hexes;
}

// === UTILITY FUNCTIONS (EXACT from frontend/src/utils/gameHelpers.ts) ===

export function getPlayerUnits(units: Unit[], playerId: number): Unit[] {
  return units.filter(unit => unit.player === playerId);
}

export function getEnemyUnits(units: Unit[], playerId: number): Unit[] {
  return units.filter(unit => unit.player !== playerId);
}