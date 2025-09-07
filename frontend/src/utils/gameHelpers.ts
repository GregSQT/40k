// frontend/src/utils/gameHelpers.ts

// Hex coordinate conversion utilities
export function offsetToCube(col: number, row: number) {
  const x = col - (row - (row & 1)) / 2;
  const z = row;
  const y = -x - z;
  return { x, y, z };
}

export function cubeToOffset(x: number, y: number, z: number) {
  const col = x + (z - (z & 1)) / 2;
  const row = z;
  return { col, row };
}

export function cubeDistance(a: {x: number, y: number, z: number}, b: {x: number, y: number, z: number}) {
  return (Math.abs(a.x - b.x) + Math.abs(a.y - b.y) + Math.abs(a.z - b.z)) / 2;
}

// Placeholder helper functions
export function calculateDistance(unit1: any, unit2: any): number {
  const cube1 = offsetToCube(unit1.col, unit1.row);
  const cube2 = offsetToCube(unit2.col, unit2.row);
  return cubeDistance(cube1, cube2);
}

export function isAdjacent(unit1: any, unit2: any): boolean {
  return calculateDistance(unit1, unit2) <= 1;
}

export function getAdjacentHexes(col: number, row: number) {
  // Even/odd row offset coordinates
  const isEvenRow = row % 2 === 0;
  const directions = isEvenRow 
    ? [[-1, -1], [0, -1], [-1, 0], [1, 0], [-1, 1], [0, 1]]
    : [[0, -1], [1, -1], [-1, 0], [1, 0], [0, 1], [1, 1]];
  
  return directions.map(([dcol, drow]) => ({
    col: col + dcol,
    row: row + drow
  }));
}