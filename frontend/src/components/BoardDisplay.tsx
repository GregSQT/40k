// frontend/src/components/BoardDisplay.tsx
import * as PIXI from "pixi.js-legacy";

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

// Objective control info - which player controls each hex
interface ObjectiveControlMap {
  [hexKey: string]: number | null; // "col,row" -> 0 (P0), 1 (P1), or null (contested/uncontrolled)
}

interface DrawBoardOptions {
  availableCells?: HighlightCell[];
  attackCells?: HighlightCell[];
  coverCells?: HighlightCell[];
  chargeCells?: HighlightCell[];
  advanceCells?: HighlightCell[]; // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Orange hexes
  blockedTargets?: Set<string>;
  coverTargets?: Set<string>;
  phase?: "move" | "shoot" | "charge" | "fight";
  selectedUnitId?: number | null;
  mode?: string;
  showHexCoordinates?: boolean;
  objectiveControl?: ObjectiveControlMap; // NEW: Control status for each objective hex
}

// Helper functions from Board.tsx
function hexCorner(cx: number, cy: number, size: number, i: number) {
  const angle_deg = 60 * i;
  const angle_rad = (Math.PI / 180) * angle_deg;
  return [cx + size * Math.cos(angle_rad), cy + size * Math.sin(angle_rad)];
}

function getHexPolygonPoints(cx: number, cy: number, size: number) {
  return Array.from({ length: 6 }, (_, i) => hexCorner(cx, cy, size, i)).flat();
}

// Parse colors from config - same as Board.tsx
const parseColor = (colorStr: string): number => {
  return parseInt(colorStr.replace("0x", ""), 16);
};

/**
 * Pure visual board rendering - NO INTERACTIONS
 * Used by both BoardReplay (simple call) and Board.tsx (with highlights)
 */
export const drawBoard = (
  app: PIXI.Application,
  boardConfig: BoardConfig,
  options?: DrawBoardOptions
): void => {
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
    const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight!);
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack!);
    const CHARGE_COLOR = parseColor(boardConfig.colors.charge!);
    const WALL_COLOR = parseColor(boardConfig.colors.wall!);

    // Extract options with defaults for replay viewer compatibility
    const {
      availableCells = [],
      attackCells = [],
      coverCells = [],
      chargeCells = [],
      advanceCells = [], // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4
      phase = "move",
      selectedUnitId = null,
      mode = "select",
      showHexCoordinates = false,
      objectiveControl = {},
    } = options || {};

    // Parse objective control colors - use same colors as player units
    if (!boardConfig.colors.player_1) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_1");
    }
    if (!boardConfig.colors.player_2) {
      throw new Error("Missing required configuration value: boardConfig.colors.player_2");
    }
    if (!boardConfig.colors.objective) {
      throw new Error("Missing required configuration value: boardConfig.colors.objective");
    }
    const OBJECTIVE_P0_COLOR = parseColor(boardConfig.colors.player_1);
    const OBJECTIVE_P1_COLOR = parseColor(boardConfig.colors.player_2);
    const OBJECTIVE_NEUTRAL_COLOR = parseColor(boardConfig.colors.objective);

    // ✅ OPTIMIZED: Create containers for hex batching - EXACT from Board.tsx
    const baseHexContainer = new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    baseHexContainer.name = "baseHexes";
    highlightContainer.name = "highlights";

    // Compute all objective hexes - use ONLY hexes from config, no expansion
    const objectiveHexSet = new Set<string>();
    const baseObjectives = boardConfig.objective_hexes || [];

    for (const [objCol, objRow] of baseObjectives) {
      objectiveHexSet.add(`${objCol},${objRow}`);
    }

    // Pre-compute wallHexSet
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
    );

    // Draw grid cells with container batching - EXACT from Board.tsx
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        if (row === BOARD_ROWS - 1 && col % 2 === 1) {
          continue;
        }
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY =
          row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);

        // Check highlight states
        const isAvailable = availableCells.some((cell) => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some((cell) => cell.col === col && cell.row === row);
        const isInCover = coverCells.some((cell) => cell.col === col && cell.row === row);
        // chargeCells come as [col, row] arrays from backend, not {col, row} objects
        const isChargeable = chargeCells.some((cell) => {
          if (Array.isArray(cell)) {
            return cell[0] === col && cell[1] === row;
          }
          return cell.col === col && cell.row === row;
        });

        // ADVANCE_IMPLEMENTATION_PLAN.md Phase 4: Advance destinations (orange)
        const isAdvanceDestination = advanceCells.some(
          (cell) => cell.col === col && cell.row === row
        );

        // Check if this is a wall hex
        const isWallHex = wallHexSet.has(`${col},${row}`);

        // Create base hex (always present)
        const baseCell = new PIXI.Graphics();
        const isEven = (col + row) % 2 === 0;
        let cellColor = isEven
          ? parseColor(boardConfig.colors.cell_even)
          : parseColor(boardConfig.colors.cell_odd);

        // Override color for walls and objective zones
        if (isWallHex) {
          cellColor = WALL_COLOR;
        } else if (objectiveHexSet.has(`${col},${row}`)) {
          // Check if this objective hex is controlled by a player
          const hexKey = `${col},${row}`;
          const controller = objectiveControl[hexKey];
          if (controller === 1) {
            cellColor = OBJECTIVE_P0_COLOR; // Blue for Player 1
          } else if (controller === 2) {
            cellColor = OBJECTIVE_P1_COLOR; // Red for Player 2
          } else {
            cellColor = OBJECTIVE_NEUTRAL_COLOR; // Yellow/Orange for neutral/contested
          }
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
            fill: 0xffffff,
            align: "center",
          });
          coordText.anchor.set(0.5);
          coordText.position.set(centerX, centerY);
          baseHexContainer.addChild(coordText);
        }

        // Create highlight hex (only if needed) - NO INTERACTIONS
        if (isAdvanceDestination || isChargeable || isAttackable || isInCover || isAvailable) {
          const highlightCell = new PIXI.Graphics();

          // Shooting phase: use unified vivid blue tones for attack preview
          if (phase === "shoot") {
            // In advancePreview mode, use light brown for availableCells
            if (mode === "advancePreview" && isAvailable) {
              // Light brown for advance destinations (0xD4A574 = light brown)
              highlightCell.beginFill(0xd4a574, 0.5);
            } else if (isAdvanceDestination) {
              // ADVANCE_IMPLEMENTATION_PLAN.md: Orange for advance destinations
              highlightCell.beginFill(0xff8c00, 0.5);
            } else if (isAttackable) {
              // Vivid medium blue for clear line of sight (plus bleu, même luminosité)
              highlightCell.beginFill(0x4f8bff, 0.4);
            } else if (isInCover) {
              // Vivid light blue for targets in cover
              highlightCell.beginFill(0x9ec5ff, 0.4);
            } else if (isChargeable) {
              // Charge destinations: use violet
              highlightCell.beginFill(0x9f7aea, 0.4);
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.4);
            }
          } else {
            // Other phases keep existing colors
            if (isChargeable) {
              // Charge destinations: use violet
              highlightCell.beginFill(0x9f7aea, 0.5);
            } else if (isAttackable) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5);
            } else if (isInCover) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5);
            } else if (isAvailable) {
              highlightCell.beginFill(HIGHLIGHT_COLOR, 0.5);
            }
          }

          highlightCell.drawPolygon(points);
          highlightCell.endFill();

          // Add click handlers for movement, charge, and advance hexes
          if (isAvailable || isChargeable || isAdvanceDestination) {
            highlightCell.eventMode = "static";
            highlightCell.cursor = "pointer";
            highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) {
                // Left click only
                window.dispatchEvent(
                  new CustomEvent("boardHexClick", {
                    detail: { col, row, phase, mode, selectedUnitId },
                  })
                );
              }
            });
          }

          highlightContainer.addChild(highlightCell);
        }
      }
    }

    // ✅ AGGRESSIVE STAGE CLEANUP - Destroy everything first, then clear - EXACT from Board.tsx
    // BUT: Preserve the UI elements container (target logos, charge badges) - it's never cleaned up
    // AND: Preserve hp-blink-container (blinking HP bars) - they need to persist for animation
    const childrenToDestroy: PIXI.DisplayObject[] = [];

    // Identify which children to destroy (skip the UI elements container and blink containers)
    for (const child of app.stage.children) {
      // NEVER destroy the UI elements container - it persists across all renders
      if (child.name === "ui-elements-container") {
        continue; // Skip the UI container
      }
      // NEVER destroy hp-blink-container - they persist for blinking animation
      if (child.name === "hp-blink-container") {
        continue; // Skip the blink container
      }
      childrenToDestroy.push(child);
    }

    // Remove and destroy only the children to destroy
    childrenToDestroy.forEach((child) => {
      app.stage.removeChild(child);
      if (child.destroy) {
        child.destroy({ children: true, texture: false, baseTexture: false });
      }
    });

    // ✅ ADD CONTAINERS TO STAGE (2 objects instead of 432)
    app.stage.addChild(baseHexContainer);
    app.stage.addChild(highlightContainer);

    // ✅ RENDER WALLS - EXACT from Board.tsx
    if (boardConfig.walls && boardConfig.walls.length > 0) {
      const wallsContainer = new PIXI.Container();
      wallsContainer.name = "walls";

      boardConfig.walls.forEach((wall) => {
        const wallGraphics = new PIXI.Graphics();

        // Calculate start and end positions
        const startX = wall.start.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const startY =
          wall.start.row * HEX_VERT_SPACING +
          ((wall.start.col % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;
        const endX = wall.end.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const endY =
          wall.end.row * HEX_VERT_SPACING +
          ((wall.end.col % 2) * HEX_VERT_SPACING) / 2 +
          HEX_HEIGHT / 2 +
          MARGIN;

        // Draw wall as thick line
        wallGraphics.lineStyle(wall.thickness || 3, WALL_COLOR, 1.0);
        wallGraphics.moveTo(startX, startY);
        wallGraphics.lineTo(endX, endY);

        wallsContainer.addChild(wallGraphics);
      });

      app.stage.addChild(wallsContainer);
    }
  } catch (error) {
    console.error("❌ Error drawing board:", error);
    throw error;
  }
};
