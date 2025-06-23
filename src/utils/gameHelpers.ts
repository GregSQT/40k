// src/utils/gameHelpers.ts
import { Unit, Position, UnitId } from '../types/game';

// Distance calculations for hex grid
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

// Unit utility functions
export function findUnitById(units: Unit[], id: UnitId): Unit | undefined {
  return units.find(unit => unit.id === id);
}

export function getUnitsAtPosition(units: Unit[], position: Position): Unit[] {
  return units.filter(unit => unit.col === position.col && unit.row === position.row);
}

export function isPositionOccupied(units: Unit[], position: Position, excludeId?: UnitId): boolean {
  return units.some(unit => 
    unit.id !== excludeId && 
    unit.col === position.col && 
    unit.row === position.row
  );
}

export function getAdjacentPositions(position: Position, boardCols: number, boardRows: number): Position[] {
  const { col, row } = position;
  const adjacent: Position[] = [];
  
  // Hex grid adjacent positions (flat-topped, even-q offset)
  const directions = [
    [1, 0], [-1, 0], // East, West
    [0, -1], [0, 1], // Northeast, Southeast (for even cols)
    [-1, -1], [1, -1] // Northwest, Southwest (for even cols)
  ];
  
  for (const [dcol, drow] of directions) {
    let newCol = col + dcol;
    let newRow = row + drow;
    
    // Adjust for odd columns in hex grid
    if (col % 2 === 1 && (dcol === 0)) {
      newRow += 1;
    }
    
    if (newCol >= 0 && newCol < boardCols && newRow >= 0 && newRow < boardRows) {
      adjacent.push({ col: newCol, row: newRow });
    }
  }
  
  return adjacent;
}

// Combat utility functions
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

export function getUnitsInRange(units: Unit[], center: Unit, range: number): Unit[] {
  return units.filter(unit => 
    unit.id !== center.id && 
    isUnitInRange(center, unit, range)
  );
}

export function getEnemiesInRange(units: Unit[], attacker: Unit, range: number): Unit[] {
  return getUnitsInRange(units, attacker, range).filter(
    unit => unit.player !== attacker.player
  );
}

// Movement utility functions
export function getValidMovePositions(
  unit: Unit, 
  units: Unit[], 
  boardCols: number, 
  boardRows: number
): Position[] {
  const validPositions: Position[] = [];
  const centerCube = offsetToCube(unit.col, unit.row);
  
  for (let col = 0; col < boardCols; col++) {
    for (let row = 0; row < boardRows; row++) {
      const targetCube = offsetToCube(col, row);
      const distance = cubeDistance(centerCube, targetCube);
      
      // Within move range and not occupied by another unit
      if (
        distance > 0 && 
        distance <= unit.MOVE && 
        !isPositionOccupied(units, { col, row }, unit.id)
      ) {
        validPositions.push({ col, row });
      }
    }
  }
  
  return validPositions;
}

// Game state utility functions
export function getPlayerUnits(units: Unit[], playerId: number): Unit[] {
  return units.filter(unit => unit.player === playerId);
}

export function getEnemyUnits(units: Unit[], playerId: number): Unit[] {
  return units.filter(unit => unit.player !== playerId);
}

export function isGameOver(units: Unit[]): { gameOver: boolean; winner?: number } {
  const player0Units = getPlayerUnits(units, 0);
  const player1Units = getPlayerUnits(units, 1);
  
  if (player0Units.length === 0) {
    return { gameOver: true, winner: 1 };
  }
  
  if (player1Units.length === 0) {
    return { gameOver: true, winner: 0 };
  }
  
  return { gameOver: false };
}

// Health utility functions
export function calculateDamage(attacker: Unit, target: Unit, damageType: 'ranged' | 'melee'): number {
  const baseDamage = damageType === 'ranged' ? attacker.RNG_DMG : attacker.CC_DMG;
  
  // You can add more complex damage calculations here
  // e.g., armor saves, weapon effectiveness, etc.
  
  return baseDamage;
}

export function applyDamage(unit: Unit, damage: number): Unit {
  const currentHP = unit.CUR_HP ?? unit.HP_MAX;
  const newHP = Math.max(0, currentHP - damage);
  
  return {
    ...unit,
    CUR_HP: newHP,
  };
}

export function isUnitAlive(unit: Unit): boolean {
  const currentHP = unit.CUR_HP ?? unit.HP_MAX;
  return currentHP > 0;
}

// Validation functions
export function isValidPosition(position: Position, boardCols: number, boardRows: number): boolean {
  return (
    position.col >= 0 && 
    position.col < boardCols && 
    position.row >= 0 && 
    position.row < boardRows
  );
}

export function isValidMove(
  unit: Unit, 
  targetPosition: Position, 
  units: Unit[], 
  boardCols: number, 
  boardRows: number
): boolean {
  if (!isValidPosition(targetPosition, boardCols, boardRows)) {
    return false;
  }
  
  if (isPositionOccupied(units, targetPosition, unit.id)) {
    return false;
  }
  
  const distance = getHexDistance(
    { col: unit.col, row: unit.row },
    targetPosition
  );
  
  return distance <= unit.MOVE;
}

// Debugging utilities
export function logGameState(units: Unit[], phase: string, currentPlayer: number): void {
  if (process.env.NODE_ENV === 'development') {
    console.group(`Game State - Phase: ${phase}, Player: ${currentPlayer}`);
    units.forEach(unit => {
      const hp = unit.CUR_HP ?? unit.HP_MAX;
      console.log(`${unit.name} (P${unit.player}): ${hp}/${unit.HP_MAX} HP at (${unit.col}, ${unit.row})`);
    });
    console.groupEnd();
  }
}