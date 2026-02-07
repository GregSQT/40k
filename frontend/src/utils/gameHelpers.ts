// frontend/src/utils/gameHelpers.ts
import type { Unit, Position, UnitId } from '../types';
import { getSelectedRangedWeapon, getSelectedMeleeWeapon } from './weaponHelpers';

// Wall interface for collision detection
interface Wall {
  id: string;
  start: { col: number; row: number };
  end: { col: number; row: number };
  thickness?: number;
} 

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

// === WALL COLLISION SYSTEM ===

// Convert hex coordinates to pixel coordinates for line intersection
function hexToPixel(col: number, row: number, hexRadius: number): { x: number; y: number } {
  const hexWidth = 1.5 * hexRadius;
  const hexHeight = Math.sqrt(3) * hexRadius;
  
  const x = col * hexWidth;
  const y = row * hexHeight + ((col % 2) * hexHeight / 2);
  
  return { x, y };
}

// Check if a line passes through any part of a hex
function linePassesThroughHex(
  startPoint: { x: number; y: number },
  endPoint: { x: number; y: number },
  hexCol: number,
  hexRow: number,
  hexRadius: number
): boolean {
  const hexCenter = hexToPixel(hexCol, hexRow, hexRadius);
  
  // Create hex polygon points (6 corners)
  const hexPoints: { x: number; y: number }[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (i * Math.PI) / 3; // 60 degree increments for hex
    const x = hexCenter.x + hexRadius * Math.cos(angle);
    const y = hexCenter.y + hexRadius * Math.sin(angle);
    hexPoints.push({ x, y });
  }
  
  // Check if line intersects any edge of the hex polygon
  for (let i = 0; i < hexPoints.length; i++) {
    const p1 = hexPoints[i];
    const p2 = hexPoints[(i + 1) % hexPoints.length];
    
    if (lineSegmentsIntersect(startPoint, endPoint, p1, p2)) {
      return true;
    }
  }
  
  return false;
}

// Helper function to check if two line segments intersect
function lineSegmentsIntersect(
  line1Start: { x: number; y: number },
  line1End: { x: number; y: number },
  line2Start: { x: number; y: number },
  line2End: { x: number; y: number }
): boolean {
  const d1 = { x: line1End.x - line1Start.x, y: line1End.y - line1Start.y };
  const d2 = { x: line2End.x - line2Start.x, y: line2End.y - line2Start.y };
  const d3 = { x: line2Start.x - line1Start.x, y: line2Start.y - line1Start.y };
  
  const cross1 = d1.x * d2.y - d1.y * d2.x;
  const cross2 = d3.x * d2.y - d3.y * d2.x;
  const cross3 = d3.x * d1.y - d3.y * d1.x;
  
  if (Math.abs(cross1) < 0.0001) return false; // Parallel lines
  
  const t1 = cross2 / cross1;
  const t2 = cross3 / cross1;
  
  return t1 >= 0 && t1 <= 1 && t2 >= 0 && t2 <= 1;
}

// Check if a line segment from start to end intersects with a wall
function lineIntersectsWall(
  startCol: number, 
  startRow: number, 
  endCol: number, 
  endRow: number,
  wall: Wall,
  hexRadius: number = 21
): boolean {
  // Convert hex coordinates to pixel coordinates
  const lineStart = hexToPixel(startCol, startRow, hexRadius);
  const lineEnd = hexToPixel(endCol, endRow, hexRadius);
  const wallStart = hexToPixel(wall.start.col, wall.start.row, hexRadius);
  const wallEnd = hexToPixel(wall.end.col, wall.end.row, hexRadius);
  
  // Line segment intersection using cross products
  const lineDir = { x: lineEnd.x - lineStart.x, y: lineEnd.y - lineStart.y };
  const wallDir = { x: wallEnd.x - wallStart.x, y: wallEnd.y - wallStart.y };
  const toWallStart = { x: wallStart.x - lineStart.x, y: wallStart.y - lineStart.y };
  
  const lineCrossWall = lineDir.x * wallDir.y - lineDir.y * wallDir.x;
  const toCrossWall = toWallStart.x * wallDir.y - toWallStart.y * wallDir.x;
  const toCrossLine = toWallStart.x * lineDir.y - toWallStart.y * lineDir.x;
  
  // Lines are parallel
  if (Math.abs(lineCrossWall) < 0.0001) return false;
  
  const t = toCrossWall / lineCrossWall;
  const u = toCrossLine / lineCrossWall;
  
  // Intersection occurs within both line segments
  return t >= 0 && t <= 1 && u >= 0 && u <= 1;
}

// 9-Point Line of Sight System
export function hasLineOfSight(
  fromUnit: Unit | Position,
  toUnit: Unit | Position, 
  wallHexes: [number, number][]
): { canSee: boolean; inCover: boolean } {
  const fromPos = 'col' in fromUnit ? { col: fromUnit.col, row: fromUnit.row } : fromUnit;
  const toPos = 'col' in toUnit ? { col: toUnit.col, row: toUnit.row } : toUnit;
  
  if (!wallHexes || wallHexes.length === 0) {
    return { canSee: true, inCover: false };
  }
  
  // Convert hex coordinates to pixel coordinates for accurate line testing
  const fromPixel = hexToPixel(fromPos.col, fromPos.row, 21);
  const toPixel = hexToPixel(toPos.col, toPos.row, 21);
  
  // Define 9 points for each hex: center + 8 corners
  const getHexPoints = (centerX: number, centerY: number, radius: number) => {
    const points = [{ x: centerX, y: centerY }]; // Center point
    
    // 8 corner points around the hex (not actual hex corners, but distributed around)
    for (let i = 0; i < 8; i++) {
      const angle = (i * Math.PI) / 4; // 45 degree increments
      const x = centerX + radius * 0.8 * Math.cos(angle);
      const y = centerY + radius * 0.8 * Math.sin(angle);
      points.push({ x, y });
    }
    return points;
  };
  
  const shooterPoints = getHexPoints(fromPixel.x, fromPixel.y, 21);
  const targetPoints = getHexPoints(toPixel.x, toPixel.y, 21);
  
  // Check how many sight lines from shooter points can reach target points
  let clearSightLines = 0;
  
  for (const shooterPoint of shooterPoints) {
    let shooterPointHasClearLine = false;
    
    for (const targetPoint of targetPoints) {
      // Check if this line is blocked by any wall hex
      let lineBlocked = false;
      
      for (const [wallCol, wallRow] of wallHexes) {
        if (linePassesThroughHex(shooterPoint, targetPoint, wallCol, wallRow, 21)) {
          lineBlocked = true;
          break;
        }
      }
      
      if (!lineBlocked) {
        shooterPointHasClearLine = true;
        break; // This shooter point has at least one clear line to any target point
      }
    }
    
    if (shooterPointHasClearLine) {
      clearSightLines++;
    }
  }
  
  // Apply your rules: 0 = blocked, 1-2 = cover, 3+ = clear
  if (clearSightLines === 0) {
    return { canSee: false, inCover: false };
  } else if (clearSightLines <= 2) {
    return { canSee: true, inCover: true };
  } else {
    return { canSee: true, inCover: false };
  }
}

// Simple straight-line algorithm for hex grids using linear interpolation
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

// Round cube coordinates to nearest valid hex
function roundCube(cube: { x: number; y: number; z: number }): { x: number; y: number; z: number } {
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

// Check if movement from one hex to another is blocked by walls
export function isMovementBlocked(
  fromCol: number,
  fromRow: number,
  toCol: number,
  toRow: number,
  walls: Wall[]
): boolean {
  if (walls.length === 0) return false;
  
  // Check if direct movement line intersects any wall
  for (const wall of walls) {
    if (lineIntersectsWall(fromCol, fromRow, toCol, toRow, wall)) {
      return true;
    }
  }
  
  return false;
}

// Check if a charge path is blocked by walls
export function isChargeBlocked(
  charger: Unit,
  target: Unit,
  walls: Wall[]
): boolean {
  return isMovementBlocked(charger.col, charger.row, target.col, target.row, walls);
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
    const newCol = col + dcol;
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

// Fight utility functions
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
  const player1Units = getPlayerUnits(units, 1);
  const player2Units = getPlayerUnits(units, 2);
  
  if (player1Units.length === 0) {
    return { gameOver: true, winner: 2 };
  }
  
  if (player2Units.length === 0) {
    return { gameOver: true, winner: 1 };
  }
  
  return { gameOver: false };
}

// Health utility functions
export function calculateDamage(attacker: Unit, _target: Unit, damageType: 'ranged' | 'melee'): number {
  // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get damage from selected weapon
  const selectedWeapon = damageType === 'ranged' 
    ? getSelectedRangedWeapon(attacker)
    : getSelectedMeleeWeapon(attacker);
  const baseDamage = selectedWeapon?.DMG || 0;
  
  // You can add more complex damage calculations here
  // e.g., armor saves, weapon effectiveness, etc.
  
  return baseDamage;
}

export function applyDamage(unit: Unit, damage: number): Unit {
  const currentHP = unit.HP_CUR ?? unit.HP_MAX;
  const newHP = Math.max(0, currentHP - damage);
  
  return {
    ...unit,
    HP_CUR: newHP,
  };
}

export function isUnitAlive(unit: Unit): boolean {
  const currentHP = unit.HP_CUR ?? unit.HP_MAX;
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
export function logGameState(units: Unit[], phase: string, current_player: number): void {
  if (typeof window !== 'undefined' && import.meta.env?.DEV) {
    console.group(`Game State - Phase: ${phase}, Player: ${current_player}`);
    units.forEach(unit => {
      const hp = unit.HP_CUR ?? unit.HP_MAX;
      console.log(`${unit.name} (P${unit.player}): ${hp}/${unit.HP_MAX} HP at (${unit.col}, ${unit.row})`);
    });
    console.groupEnd();
  }
}