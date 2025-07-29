// frontend/src/components/BoardRenderer.tsx
import * as PIXI from 'pixi.js-legacy';

interface BoardConfig {
  cols: number;
  rows: number;
  hex_radius: number;
  margin: number;
  colors: {
    background: string;
    cell_even: string;
    cell_odd: string;
    cell_border: string;
    objective_zone: string;
    wall: string;
    [key: string]: string;
  };
  objective_hexes: [number, number][];
  wall_hexes: [number, number][];
}

// Helper to get hex polygon points
const getHexPolygonPoints = (centerX: number, centerY: number, radius: number): number[] => {
  const points: number[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i;
    points.push(centerX + radius * Math.cos(angle), centerY + radius * Math.sin(angle));
  }
  return points;
};

// Parse colors from config - same as Board.tsx
const parseColor = (colorStr: string): number => {
  return parseInt(colorStr.replace('0x', ''), 16);
};

/**
 * Shared board drawing utility extracted from Board.tsx
 * Ensures perfect consistency between PvP and Replay boards
 */
export const drawBoard = (app: PIXI.Application, boardConfig: BoardConfig): void => {
  if (!boardConfig || !app.stage) return;
  
  try {
    // Clear previous board drawings
    app.stage.children.filter(child => child.name === 'hex' || child.name === 'hex-label').forEach(hex => {
      app.stage.removeChild(hex);
    });
    
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;
    
    // Get objective zones, wall hexes and other config - EXACT as Board.tsx
    const objectiveHexes = boardConfig.objective_hexes || [];
    const wallHexes = boardConfig.wall_hexes || [];
    const OBJECTIVE_COLOR = parseColor(boardConfig.colors.objective || '0xFF8800'); // Use 'objective' not 'objective_zone'
    const WALL_COLOR = parseColor(boardConfig.colors.wall || '0x808080');
    
    // Pre-compute wallHexSet for performance - EXACT from Board.tsx
    const wallHexSet = new Set<string>(
      wallHexes.map(([c, r]: [number, number]) => `${c},${r}`)
    );

    // Pre-compute objectiveHexSet (base + adjacent) - EXACT logic from Board.tsx
    const objectiveHexSet = new Set<string>();
    const baseObjectives = objectiveHexes;

    // Cube direction vectors for adjacent hexes
    const cubeDirections = [
      [1, -1, 0], [1, 0, -1], [0, 1, -1],
      [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
    ];

    // Helper function from Board.tsx
    const offsetToCube = (col: number, row: number) => {
      const x = col;
      const z = row - ((col - (col & 1)) >> 1);
      const y = -x - z;
      return { x, y, z };
    };

    for (const [objCol, objRow] of baseObjectives) {
      objectiveHexSet.add(`${objCol},${objRow}`);

      const cube = offsetToCube(objCol, objRow);
      for (const [dx, dy, dz] of cubeDirections) {
        const neighborCube = {
          x: cube.x + dx,
          y: cube.y + dy,
          z: cube.z + dz
        };

        const adjCol = neighborCube.x;
        const adjRow = neighborCube.z + ((adjCol - (adjCol & 1)) >> 1);

        if (
          adjCol >= 0 && adjCol < boardConfig.cols &&
          adjRow >= 0 && adjRow < boardConfig.rows
        ) {
          objectiveHexSet.add(`${adjCol},${adjRow}`);
        }
      }
    }
    
    // Draw hex grid using EXACT positioning from Board.tsx
    for (let row = 0; row < boardConfig.rows; row++) {
      for (let col = 0; col < boardConfig.cols; col++) {
        // EXACT centerX/centerY calculation from Board.tsx
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
        
        // EXACT logic from Board.tsx - use pre-computed sets
        const isWallHex = wallHexSet.has(`${col},${row}`);
        const isObjectiveZone = objectiveHexSet.has(`${col},${row}`);

        // Create base hex - EXACT logic from Board.tsx
        const baseCell = new PIXI.Graphics();
        const isEven = (col + row) % 2 === 0;
        let cellColor = isEven ? parseColor(boardConfig.colors.cell_even) : parseColor(boardConfig.colors.cell_odd);
        
        // EXACT color priority from Board.tsx
        if (isWallHex) {
          cellColor = WALL_COLOR;
        } else if (isObjectiveZone) {
          cellColor = OBJECTIVE_COLOR; // Use OBJECTIVE_COLOR to match Board.tsx
        }

        baseCell.name = 'hex';
        
        baseCell.beginFill(cellColor);
        baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border));
        baseCell.drawPolygon(points);
        baseCell.endFill();
        
        app.stage.addChild(baseCell);
        
        // Add coordinate labels - use debug format like Board.tsx for now
        const coordText = new PIXI.Text(`${col},${row}`, {
          fontSize: 8,
          fill: 0xFFFFFF,
          align: 'center'
        });
        coordText.anchor.set(0.5);
        coordText.position.set(centerX, centerY);
        app.stage.addChild(coordText);
      }
    }
    
    console.log(`✅ Board drawn: ${boardConfig.rows}x${boardConfig.cols} hexes with coordinates, walls, and objectives`);
  } catch (error) {
    console.error('❌ Error drawing board:', error);
    throw error;
  }
};