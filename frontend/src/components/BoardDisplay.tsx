// frontend/src/components/BoardDisplay.tsx
import * as PIXI from 'pixi.js-legacy';
import { offsetToCube } from '../utils/gameHelpers';

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
    highlight: string;
    attack: string;
    charge: string;
    eligible: string;
    objective: string;
    objective_zone: string;
    wall: string;
    [key: string]: string;
  };
  display: {
    icon_scale: number;
    eligible_outline_width: number;
    eligible_outline_alpha: number;
    hp_bar_width_ratio: number;
    hp_bar_height: number;
    hp_bar_y_offset_ratio: number;
    unit_circle_radius_ratio: number;
    unit_text_size: number;
    selected_border_width: number;
    charge_target_border_width: number;
    default_border_width: number;
    canvas_border: string;
    antialias: boolean;
    autoDensity: boolean;
    resolution: number | "auto";
  };
  objective_hexes: [number, number][];
  wall_hexes: [number, number][];
  walls?: Array<{
    start: { col: number; row: number };
    end: { col: number; row: number };
    thickness?: number;
  }>;
}

interface HighlightCell {
  col: number;
  row: number;
}

interface DrawBoardOptions {
  availableCells?: HighlightCell[];
  attackCells?: HighlightCell[];
  coverCells?: HighlightCell[];
  chargeCells?: HighlightCell[];
  blockedTargets?: Set<string>;
  coverTargets?: Set<string>;
  phase?: "move" | "shoot" | "charge" | "fight";
  selectedUnitId?: number | null;
  mode?: string;
  showHexCoordinates?: boolean;
}

// Helper functions from Board.tsx
function hexCorner(cx: number, cy: number, size: number, i: number) {
  const angle_deg = 60 * i;
  const angle_rad = Math.PI / 180 * angle_deg;
  return [
    cx + size * Math.cos(angle_rad),
    cy + size * Math.sin(angle_rad),
  ];
}

function getHexPolygonPoints(cx: number, cy: number, size: number) {
  return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, size, i)).flat();
}

// Parse colors from config - same as Board.tsx
const parseColor = (colorStr: string): number => {
  return parseInt(colorStr.replace('0x', ''), 16);
};

/**
 * Pure visual board rendering - NO INTERACTIONS
 * Used by both BoardReplay (simple call) and Board.tsx (with highlights)
 */
export const drawBoard = (app: PIXI.Application, boardConfig: BoardConfig, options?: DrawBoardOptions): void => {
  if (!boardConfig || !app.stage) return;
  
  try {
    // Extract board configuration values - USE CONFIG VALUES
    const BOARD_COLS = boardConfig.cols;
    const BOARD_ROWS = boardConfig.rows;
    const HEX_RADIUS = boardConfig.hex_radius;
    const MARGIN = boardConfig.margin;
    const HEX_WIDTH = 1.5 * HEX_RADIUS;
    const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
    const HEX_HORIZ_SPACING = HEX_WIDTH;
    const HEX_VERT_SPACING = HEX_HEIGHT;

    // Parse colors from config
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack!);
    const CHARGE_COLOR = parseColor(boardConfig.colors.charge!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);

    // Extract options with defaults for replay viewer compatibility
    const { 
      availableCells = [], 
      attackCells = [], 
      coverCells = [], 
      chargeCells = [],
      blockedTargets = new Set<string>(),
      coverTargets = new Set<string>(),
      phase = "move",
      selectedUnitId = null,
      mode = "select",
      showHexCoordinates = false
    } = options || {};

    // ✅ OPTIMIZED: Create containers for hex batching - EXACT from Board.tsx
    const baseHexContainer = new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    baseHexContainer.name = 'baseHexes';
    highlightContainer.name = 'highlights';

    // New: Compute all objective hexes and their adjacent hexes - EXACT from Board.tsx
    const objectiveHexSet = new Set<string>();
    const baseObjectives = boardConfig.objective_hexes || [];

    const cubeDirections = [
      [1, -1, 0], [1, 0, -1], [0, 1, -1],
      [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
    ];

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
          adjCol >= 0 && adjCol < BOARD_COLS &&
          adjRow >= 0 && adjRow < BOARD_ROWS
        ) {
          objectiveHexSet.add(`${adjCol},${adjRow}`);
        }
      }
    }

    // Pre-compute wallHexSet
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
    );

    // Draw grid cells with container batching - EXACT from Board.tsx
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
        
        // Check highlight states
        const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some(cell => cell.col === col && cell.row === row);
        const isInCover = coverCells.some(cell => cell.col === col && cell.row === row);
        const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);

        // Check if this is a wall hex
        const isWallHex = wallHexSet.has(`${col},${row}`);

        // Create base hex (always present)
        const baseCell = new PIXI.Graphics();
        const isEven = (col + row) % 2 === 0;
        let cellColor = isEven ? parseColor(boardConfig.colors.cell_even) : parseColor(boardConfig.colors.cell_odd);

        // Override color for walls and objective zones
        if (isWallHex) {
          cellColor = WALL_COLOR;
        } else if (objectiveHexSet.has(`${col},${row}`)) {
          cellColor = parseColor(boardConfig.colors.objective);
        }
        
        baseCell.beginFill(cellColor, 1.0);
        baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border), 0.8);
        baseCell.drawPolygon(points);
        baseCell.endFill();
        baseHexContainer.addChild(baseCell);
        
        // Add coordinate text when toggle is enabled
        if (showHexCoordinates) {
          const coordText = new PIXI.Text(`${col},${row}`, {
            fontSize: 8,
            fill: 0xFFFFFF,
            align: 'center'
          });
          coordText.anchor.set(0.5);
          coordText.position.set(centerX, centerY);
          baseHexContainer.addChild(coordText);
        }

        // Create highlight hex (only if needed) - NO INTERACTIONS
        if (isChargeable || isAttackable || isInCover || isAvailable) {
          const highlightCell = new PIXI.Graphics();

          if (isChargeable) {
            highlightCell.beginFill(CHARGE_COLOR, 0.5);
          } else if (isAttackable) {
            highlightCell.beginFill(ATTACK_COLOR, 0.5); // Red for clear line of sight
          } else if (isInCover) {
            highlightCell.beginFill(CHARGE_COLOR, 0.5); // Orange for targets in cover (reuse CHARGE_COLOR)
          } else if (isAvailable) {
            highlightCell.beginFill(0x00FF00, 0.5);
          }
          
          highlightCell.drawPolygon(points);
          highlightCell.endFill();
          
          // Add click handlers for movement hexes
          if (isAvailable) {
            highlightCell.eventMode = 'static';
            highlightCell.cursor = 'pointer';
            highlightCell.on('pointerdown', (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) { // Left click only
                window.dispatchEvent(new CustomEvent('boardHexClick', {
                  detail: { col, row, phase, mode, selectedUnitId }
                }));
              }
            });
          }
          
          highlightContainer.addChild(highlightCell);
        }
      }
    }

    // ✅ AGGRESSIVE STAGE CLEANUP - Destroy everything first, then clear - EXACT from Board.tsx
    const childrenToDestroy = [...app.stage.children];
    app.stage.removeChildren();
    childrenToDestroy.forEach(child => {
      if (child.destroy) {
        child.destroy({ children: true, texture: false, baseTexture: false });
      }
    });

    // ✅ ADD CONTAINERS TO STAGE (2 objects instead of 432)
    app.stage.addChild(baseHexContainer);
    app.stage.addChild(highlightContainer);

    // ✅ RENDER LINE OF SIGHT INDICATORS - EXACT from Board.tsx
    if (phase === "shoot" && (blockedTargets.size > 0 || coverTargets.size > 0)) {
      const losContainer = new PIXI.Container();
      losContainer.name = 'line-of-sight-indicators';
      
      // Show blocked targets with red X
      blockedTargets.forEach(targetKey => {
        const [col, row] = targetKey.split(',').map(Number);
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        
        const blockedIndicator = new PIXI.Graphics();
        blockedIndicator.lineStyle(3, 0xFF0000, 1.0);
        // Draw X
        blockedIndicator.moveTo(centerX - HEX_RADIUS/2, centerY - HEX_RADIUS/2);
        blockedIndicator.lineTo(centerX + HEX_RADIUS/2, centerY + HEX_RADIUS/2);
        blockedIndicator.moveTo(centerX + HEX_RADIUS/2, centerY - HEX_RADIUS/2);
        blockedIndicator.lineTo(centerX - HEX_RADIUS/2, centerY + HEX_RADIUS/2);
        
        losContainer.addChild(blockedIndicator);
      });
      
      // Show targets in cover with yellow shield icon
      coverTargets.forEach(targetKey => {
        const [col, row] = targetKey.split(',').map(Number);
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        
        const coverIndicator = new PIXI.Graphics();
        coverIndicator.lineStyle(2, 0xFFFF00, 1.0);
        coverIndicator.beginFill(0xFFFF00, 0.3);
        // Draw shield shape
        coverIndicator.drawCircle(centerX, centerY - HEX_RADIUS/3, HEX_RADIUS/4);
        coverIndicator.endFill();
        
        losContainer.addChild(coverIndicator);
      });
      
      app.stage.addChild(losContainer);
    }
    
    // ✅ RENDER WALLS - EXACT from Board.tsx
    if (boardConfig.walls && boardConfig.walls.length > 0) {
      const wallsContainer = new PIXI.Container();
      wallsContainer.name = 'walls';
      
      boardConfig.walls.forEach(wall => {
        const wallGraphics = new PIXI.Graphics();
        
        // Calculate start and end positions
        const startX = wall.start.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const startY = wall.start.row * HEX_VERT_SPACING + ((wall.start.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const endX = wall.end.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const endY = wall.end.row * HEX_VERT_SPACING + ((wall.end.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        
        // Draw wall as thick line
        wallGraphics.lineStyle(wall.thickness || 3, WALL_COLOR, 1.0);
        wallGraphics.moveTo(startX, startY);
        wallGraphics.lineTo(endX, endY);
        
        wallsContainer.addChild(wallGraphics);
      });
      
      app.stage.addChild(wallsContainer);
    }

  } catch (error) {
    console.error('❌ Error drawing board:', error);
    throw error;
  }
};