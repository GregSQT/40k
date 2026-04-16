// frontend/src/components/BoardDisplay.tsx
import type React from "react";
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
    background_image?: string;
    background_image_alpha?: number;
    background_overlay_alpha?: number;
    wall_texture?: string;
    wall_texture_alpha?: number;
    /** Chemin public (ex. /textures/obj1.webp). Teinte = couleur objectif / contrôle. */
    objective_texture?: string;
    objective_texture_alpha?: number;
    objective_smooth_contour?: boolean;
    objective_smooth_radius_ratio?: number;
    objective_smooth_alpha?: number;
  };
  objective_hexes: [number, number][];
  objective_zones?: Array<{
    id: string;
    hexes: Array<[number, number] | { col: number; row: number }>;
  }>;
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
  interactionPhase?: "deployment" | "command" | "move" | "shoot" | "charge" | "fight";
  selectedUnitId?: number | null;
  mode?: string;
  showHexCoordinates?: boolean;
  objectiveControl?: ObjectiveControlMap;
  moveDestPoolRef?: React.RefObject<Set<string>>;
  selectedUnitBaseSize?: number;
  /** Pre-built static board container (background + wall dots + objectives base). Reused across renders. */
  cachedStaticBoard?: PIXI.Container | null;
  /** Pre-built wall segments container. Reused across renders. */
  cachedWalls?: PIXI.Container | null;
  losDebugShowRatio?: boolean;
  losDebugRatioByHex?: Record<string, number>;
  losDebugCoverRatio?: number;
  losDebugVisibilityMinRatio?: number;
}

export interface DrawBoardResult {
  baseHexContainer: PIXI.Container;
  wallsContainer: PIXI.Container | null;
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

/** Remplissage objectif : texture teintée ou couleur unie (même pipeline que les murs). */
function beginObjectiveFill(
  g: PIXI.Graphics,
  texture: PIXI.Texture | null,
  fillColor: number,
  alpha: number
): void {
  if (texture) {
    g.beginTextureFill({
      texture,
      alpha,
      color: fillColor,
    });
  } else {
    g.beginFill(fillColor, alpha);
  }
}

/**
 * Pure visual board rendering - NO INTERACTIONS
 * Used by both BoardReplay (simple call) and Board.tsx (with highlights)
 */
export const drawBoard = (
  app: PIXI.Application,
  boardConfig: BoardConfig,
  options?: DrawBoardOptions
): DrawBoardResult | void => {
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
      interactionPhase = phase,
      selectedUnitId = null,
      mode = "select",
      showHexCoordinates = false,
      objectiveControl = {},
      moveDestPoolRef,
      selectedUnitBaseSize,
      losDebugShowRatio = false,
      losDebugRatioByHex = {},
      losDebugCoverRatio = 0,
      losDebugVisibilityMinRatio = 0,
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

    // Compute all objective hexes - use ONLY hexes from config, no expansion
    const objectiveHexSet = new Set<string>();
    let baseObjectives: Array<[number, number]> = boardConfig.objective_hexes || [];
    if (baseObjectives.length === 0 && Array.isArray(boardConfig.objective_zones)) {
      baseObjectives = boardConfig.objective_zones.flatMap(z =>
        (z.hexes || []).map(h =>
          Array.isArray(h) ? h as [number, number] : [h.col, h.row] as [number, number]
        )
      );
    }

    for (const [objCol, objRow] of baseObjectives) {
      objectiveHexSet.add(`${objCol},${objRow}`);
    }

    // Pre-compute wallHexSet
    const wallHexSet = new Set<string>(
      (boardConfig.wall_hexes || []).map(([c, r]: [number, number]) => `${c},${r}`)
    );

    const IS_LARGE_BOARD = BOARD_COLS * BOARD_ROWS > 10000;

    const cachedStaticBoard = options?.cachedStaticBoard ?? null;
    const reuseStatic = IS_LARGE_BOARD && cachedStaticBoard !== null;
    const baseHexContainer = reuseStatic ? cachedStaticBoard : new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    if (!reuseStatic) {
      baseHexContainer.name = "baseHexes";
    }
    highlightContainer.name = "highlights";
    const TOTAL_WIDTH = BOARD_COLS * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + 2 * MARGIN;
    const TOTAL_HEIGHT = BOARD_ROWS * HEX_VERT_SPACING + HEX_VERT_SPACING / 2 + 2 * MARGIN;
    const backgroundImagePath = boardConfig.display?.background_image?.trim();
    const backgroundImageAlpha =
      typeof boardConfig.display?.background_image_alpha === "number"
        ? boardConfig.display.background_image_alpha
        : 0.85;
    const backgroundOverlayAlpha =
      typeof boardConfig.display?.background_overlay_alpha === "number"
        ? boardConfig.display.background_overlay_alpha
        : 0.18;
    const objectiveSmoothContour = boardConfig.display?.objective_smooth_contour ?? true;
    const objectiveTexturePath = boardConfig.display?.objective_texture?.trim();
    const objectiveTexture =
      objectiveTexturePath && objectiveTexturePath.length > 0
        ? PIXI.Texture.from(objectiveTexturePath)
        : null;
    const objectiveTextureAlpha =
      typeof boardConfig.display?.objective_texture_alpha === "number"
        ? boardConfig.display.objective_texture_alpha
        : 0.85;

    if (IS_LARGE_BOARD) {
      if (!reuseStatic) {
        if (backgroundImagePath) {
          const bgSprite = PIXI.Sprite.from(backgroundImagePath);
          bgSprite.x = 0;
          bgSprite.y = 0;
          bgSprite.width = TOTAL_WIDTH;
          bgSprite.height = TOTAL_HEIGHT;
          bgSprite.alpha = backgroundImageAlpha;
          baseHexContainer.addChild(bgSprite);

          const bgOverlay = new PIXI.Graphics();
          bgOverlay.beginFill(parseColor(boardConfig.colors.cell_even), backgroundOverlayAlpha);
          bgOverlay.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
          bgOverlay.endFill();
          baseHexContainer.addChild(bgOverlay);
        } else {
          const bg = new PIXI.Graphics();
          bg.beginFill(parseColor(boardConfig.colors.cell_even), 1.0);
          bg.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
          bg.endFill();
          baseHexContainer.addChild(bg);
        }

        const wallDotRadius = HEX_RADIUS;
        const wallAltColor = (WALL_COLOR & 0xfefefe) + 0x101010;
        for (const [wc, wr] of boardConfig.wall_hexes || []) {
          const wx = wc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const wy = wr * HEX_VERT_SPACING + ((wc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          const wallDot = new PIXI.Graphics();
          const fill = wc % 2 === 0 ? WALL_COLOR : wallAltColor;
          wallDot.beginFill(fill, 1.0);
          wallDot.drawCircle(wx, wy, wallDotRadius);
          wallDot.endFill();
          baseHexContainer.addChild(wallDot);
        }

        if (objectiveSmoothContour && Array.isArray(boardConfig.objective_zones)) {
          for (const zone of boardConfig.objective_zones) {
            const zoneHexes = zone.hexes || [];
            if (!Array.isArray(zoneHexes) || zoneHexes.length === 0) continue;

            const centers: Array<[number, number]> = [];
            for (const h of zoneHexes) {
              const oc = Array.isArray(h) ? Number(h[0]) : Number((h as { col: number }).col);
              const or_ = Array.isArray(h) ? Number(h[1]) : Number((h as { row: number }).row);
              if (!Number.isFinite(oc) || !Number.isFinite(or_)) continue;
              const ox = oc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
              const oy = or_ * HEX_VERT_SPACING + ((oc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
              centers.push([ox, oy]);
            }
            if (centers.length === 0) continue;

            let sumX = 0, sumY = 0;
            for (const [x, y] of centers) { sumX += x; sumY += y; }
            const cx = sumX / centers.length;
            const cy = sumY / centers.length;

            let maxDist = 0;
            for (const [x, y] of centers) {
              const d = Math.sqrt((x - cx) ** 2 + (y - cy) ** 2);
              if (d > maxDist) maxDist = d;
            }

            const smoothZone = new PIXI.Graphics();
            beginObjectiveFill(
              smoothZone,
              objectiveTexture,
              OBJECTIVE_NEUTRAL_COLOR,
              objectiveTexture ? objectiveTextureAlpha : 0.8
            );
            smoothZone.drawCircle(cx, cy, maxDist + HEX_RADIUS);
            smoothZone.endFill();
            baseHexContainer.addChild(smoothZone);
          }
        }

        for (const [oc, or_] of baseObjectives) {
          const ox = oc * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const oy = or_ * HEX_VERT_SPACING + ((oc % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          const hexKey = `${oc},${or_}`;
          const controller = objectiveControl[hexKey];
          let objColor = OBJECTIVE_NEUTRAL_COLOR;
          if (controller === 1) objColor = OBJECTIVE_P0_COLOR;
          else if (controller === 2) objColor = OBJECTIVE_P1_COLOR;
          const objDot = new PIXI.Graphics();
          beginObjectiveFill(
            objDot,
            objectiveTexture,
            objColor,
            objectiveTexture ? objectiveTextureAlpha : 0.8
          );
          objDot.drawCircle(ox, oy, HEX_RADIUS);
          objDot.endFill();
          baseHexContainer.addChild(objDot);
        }
      }

      // Build clickable set for hit detection
      const clickableSet = new Set<string>();
      for (const c of availableCells) clickableSet.add(`${c.col},${c.row}`);
      for (const c of chargeCells) {
        const cc = Array.isArray(c) ? c[0] : (c as { col: number }).col;
        const cr = Array.isArray(c) ? c[1] : (c as { row: number }).row;
        clickableSet.add(`${cc},${cr}`);
      }
      for (const c of advanceCells) clickableSet.add(`${c.col},${c.row}`);

      // On large boards, only draw highlights for small pools (< 500 cells).
      // Large pools (movement range on ×10) would create a solid blob — skip visual,
      // rely on hover overlay for validation feedback.
      const LARGE_POOL_THRESHOLD = 500;

      const useAdvanceMovePoolLikeMove =
        interactionPhase === "shoot" && mode === "advancePreview";
      const useLargeBoardMoveDestPoolDraw =
        (interactionPhase === "move" || useAdvanceMovePoolLikeMove) &&
        selectedUnitBaseSize &&
        selectedUnitBaseSize > 1 &&
        moveDestPoolRef?.current &&
        moveDestPoolRef.current.size > 0;

      const drawGroup = (cells: Array<{ col: number; row: number }>, color: number, alpha: number, skipThreshold = true) => {
        if (cells.length === 0) return;
        if (skipThreshold && cells.length > LARGE_POOL_THRESHOLD) return;
        const batch = new PIXI.Graphics();
        batch.beginFill(color, alpha);
        for (const c of cells) {
          const hx = c.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy = c.row * HEX_VERT_SPACING + ((c.col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          batch.drawCircle(hx, hy, HEX_RADIUS);
        }
        batch.endFill();
        highlightContainer.addChild(batch);
      };

      if (useLargeBoardMoveDestPoolDraw) {
        // Draw icon-sized circles at valid CENTER positions only.
        // Each center was validated by BFS (full footprint clear of walls),
        // so the visual circles won't overlap walls.
        const footprintRadius = (selectedUnitBaseSize / 2) * HEX_HORIZ_SPACING;
        const gfx = new PIXI.Graphics();
        gfx.beginFill(HIGHLIGHT_COLOR, 1.0);
        for (const key of moveDestPoolRef.current) {
          const sep = key.indexOf(",");
          const c = Number(key.substring(0, sep));
          const r = Number(key.substring(sep + 1));
          const hx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const hy = r * HEX_VERT_SPACING + ((c % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN;
          gfx.drawCircle(hx, hy, footprintRadius);
        }
        gfx.endFill();
        const bounds = gfx.getBounds();
        if (bounds.width > 0 && bounds.height > 0) {
          const rt = PIXI.RenderTexture.create({ width: bounds.width, height: bounds.height });
          gfx.position.set(-bounds.x, -bounds.y);
          app.renderer.render(gfx, { renderTexture: rt });
          gfx.destroy();
          const sprite = new PIXI.Sprite(rt);
          sprite.position.set(bounds.x, bounds.y);
          sprite.alpha = 0.4;
          highlightContainer.addChild(sprite);
        } else {
          gfx.destroy();
        }
      } else {
        drawGroup(availableCells, HIGHLIGHT_COLOR, 0.4, false);
      }
      drawGroup(attackCells, ATTACK_COLOR, 0.4, false);
      drawGroup(
        chargeCells.map((c: any) => ({
          col: Array.isArray(c) ? c[0] : c.col,
          row: Array.isArray(c) ? c[1] : c.row,
        })),
        CHARGE_COLOR,
        0.4,
      );
      drawGroup(advanceCells, CHARGE_COLOR, 0.3);

      // Invisible interactive overlay for click detection (pixelToHex nearest-neighbor)
      const hasClickableContent = clickableSet.size > 0 ||
        ((interactionPhase === "move" || useAdvanceMovePoolLikeMove) &&
          moveDestPoolRef?.current &&
          moveDestPoolRef.current.size > 0);
      if (hasClickableContent) {
        const hitArea = new PIXI.Graphics();
        hitArea.beginFill(0, 0);
        hitArea.drawRect(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        hitArea.endFill();
        hitArea.hitArea = new PIXI.Rectangle(0, 0, TOTAL_WIDTH, TOTAL_HEIGHT);
        hitArea.eventMode = "static";
        hitArea.cursor = "pointer";

        const resolveHex = (pos: PIXI.IPointData): { col: number; row: number } => {
          const ux = pos.x - MARGIN;
          const uy = pos.y - MARGIN;
          const colApprox = (ux - HEX_WIDTH / 2) / HEX_HORIZ_SPACING;
          const c0 = Math.max(0, Math.floor(colApprox) - 2);
          const c1 = Math.min(BOARD_COLS - 1, Math.ceil(colApprox) + 2);
          let bestCol = 0, bestRow = 0, bestD = Infinity;
          for (let c = c0; c <= c1; c++) {
            const stagger = ((c % 2) * HEX_VERT_SPACING) / 2;
            const rowApprox = (uy - HEX_HEIGHT / 2 - stagger) / HEX_VERT_SPACING;
            const r0 = Math.max(0, Math.floor(rowApprox) - 2);
            const r1 = Math.min(BOARD_ROWS - 1, Math.ceil(rowApprox) + 2);
            for (let r = r0; r <= r1; r++) {
              const cx = c * HEX_HORIZ_SPACING + HEX_WIDTH / 2;
              const cy = r * HEX_VERT_SPACING + stagger + HEX_HEIGHT / 2;
              const d = (ux - cx) ** 2 + (uy - cy) ** 2;
              if (d < bestD) { bestD = d; bestCol = c; bestRow = r; }
            }
          }
          return { col: bestCol, row: bestRow };
        };

        hitArea.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
          if (e.button !== 0) return;
          const { col, row } = resolveHex(e.getLocalPosition(hitArea));
          const key = `${col},${row}`;
          const usePoolForPick =
            (interactionPhase === "move" || useAdvanceMovePoolLikeMove) &&
            moveDestPoolRef?.current &&
            moveDestPoolRef.current.size > 0;
          const isValid =
            clickableSet.has(key) || (usePoolForPick && moveDestPoolRef.current!.has(key));
          if (isValid) {
            let destCol = col, destRow = row;
            if (usePoolForPick && moveDestPoolRef?.current && !moveDestPoolRef.current.has(key)) {
              let bestDist = Infinity;
              for (const k of moveDestPoolRef.current) {
                const sep = k.indexOf(",");
                const cc = Number(k.substring(0, sep));
                const cr = Number(k.substring(sep + 1));
                const d = (cc - col) * (cc - col) + (cr - row) * (cr - row);
                if (d < bestDist) {
                  bestDist = d;
                  destCol = cc;
                  destRow = cr;
                }
              }
            }
            window.dispatchEvent(
              new CustomEvent("boardHexClick", {
                detail: { col: destCol, row: destRow, phase: interactionPhase, mode, selectedUnitId },
              })
            );
          }
        });

        let lastHoverCol = -1, lastHoverRow = -1;
        hitArea.on("pointermove", (e: PIXI.FederatedPointerEvent) => {
          const localPos = e.getLocalPosition(hitArea);
          const { col, row } = resolveHex(localPos);
          const hexChanged = col !== lastHoverCol || row !== lastHoverRow;
          if (hexChanged) {
            lastHoverCol = col;
            lastHoverRow = row;
          }
          window.dispatchEvent(
            new CustomEvent("boardHexHover", {
              detail: { col, row, pixelX: localPos.x, pixelY: localPos.y, hexChanged },
            })
          );
        });

        highlightContainer.addChild(hitArea);
      }
    } else {

    // Legacy small board: draw individual hex polygons
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

        const isObjectiveHex = objectiveHexSet.has(`${col},${row}`);
        if (objectiveTexture && isObjectiveHex) {
          beginObjectiveFill(baseCell, objectiveTexture, cellColor, objectiveTextureAlpha);
        } else {
          baseCell.beginFill(cellColor, 1.0);
        }
        baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border), 0.8);
        baseCell.drawPolygon(points);
        baseCell.endFill();
        baseHexContainer.addChild(baseCell);

        if (losDebugShowRatio) {
          const losRatioValue = losDebugRatioByHex[`${col},${row}`];
          if (losRatioValue !== undefined) {
            if (typeof losRatioValue !== "number" || Number.isNaN(losRatioValue)) {
              throw new Error(`Invalid LoS debug ratio at ${col},${row}`);
            }
            if (
              typeof losDebugCoverRatio !== "number" ||
              Number.isNaN(losDebugCoverRatio) ||
              typeof losDebugVisibilityMinRatio !== "number" ||
              Number.isNaN(losDebugVisibilityMinRatio)
            ) {
              throw new Error("Invalid LoS debug thresholds in drawBoard options");
            }
            const ratioPercent = Math.round(losRatioValue * 100);
            const ratioColor =
              losRatioValue < losDebugVisibilityMinRatio
                ? 0x9ca3af
                : losRatioValue < losDebugCoverRatio
                  ? 0xf59e0b
                  : 0x86efac;
            const losRatioText = new PIXI.Text(`${ratioPercent}%`, {
              fontSize: 8,
              fill: ratioColor,
              fontWeight: "bold",
              stroke: 0x000000,
              strokeThickness: 2,
              align: "center",
            });
            losRatioText.anchor.set(0.5);
            losRatioText.position.set(centerX, centerY + (showHexCoordinates ? 13 : 0));
            baseHexContainer.addChild(losRatioText);
          }
        }

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

          // Shooting preview palette: used in shoot phase and movePreview confirm step
          const useShootingPreviewPalette = phase === "shoot" || mode === "movePreview";
          if (useShootingPreviewPalette) {
            // In advancePreview mode, use light brown for availableCells
            if (mode === "advancePreview" && isAvailable) {
              // Light brown for advance destinations (0xD4A574 = light brown)
              highlightCell.beginFill(0xd4a574, 0.5);
            } else if (isAdvanceDestination) {
              // ADVANCE_IMPLEMENTATION_PLAN.md: Orange for advance destinations
              highlightCell.beginFill(0xff8c00, 0.5);
            } else if (isInCover) {
              // Vivid light blue for targets in cover
              highlightCell.beginFill(0x9ec5ff, 0.4);
            } else if (isAttackable) {
              // Vivid medium blue for clear line of sight (plus bleu, même luminosité)
              highlightCell.beginFill(0x4f8bff, 0.4);
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
            } else if (isInCover) {
              highlightCell.beginFill(CHARGE_COLOR, 0.5);
            } else if (isAttackable) {
              highlightCell.beginFill(ATTACK_COLOR, 0.5);
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
                    detail: { col, row, phase: interactionPhase, mode, selectedUnitId },
                  })
                );
              }
            });
          }

          highlightContainer.addChild(highlightCell);
        }
      }
    }
    } // end else (legacy small board)

    // Caller (BoardPvp) handles stage cleanup. drawBoard only adds containers.

    if (!reuseStatic) {
      app.stage.addChildAt(baseHexContainer, 0);
    }
    app.stage.addChild(highlightContainer);

    // Render wall segments as filled polygons.
    // Skip if reusing static layers (walls are already on stage).
    let wallsResult: PIXI.Container | null = null;
    if (!reuseStatic && boardConfig.walls && boardConfig.walls.length > 0) {
      const wallsContainer = new PIXI.Container();
      wallsContainer.name = "walls";

      const halfW = IS_LARGE_BOARD ? HEX_HEIGHT * 0.8 : 1.5;
      const wallTexturePath = boardConfig.display?.wall_texture?.trim() || "/textures/wall1.webp";
      const wallTextureAlpha =
        typeof boardConfig.display?.wall_texture_alpha === "number"
          ? boardConfig.display.wall_texture_alpha
          : 1.0;
      const wallTexture = PIXI.Texture.from(wallTexturePath);

      const toPixel = (col: number, row: number): [number, number] => [
        col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN,
        row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING) / 2 + HEX_HEIGHT / 2 + MARGIN,
      ];

      boardConfig.walls.forEach((wall) => {
        const [sx, sy] = toPixel(wall.start.col, wall.start.row);
        const [ex, ey] = toPixel(wall.end.col, wall.end.row);

        const dx = ex - sx, dy = ey - sy;
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len < 0.01) return;
        const nx = (-dy / len) * halfW;
        const ny = (dx / len) * halfW;

        const g = new PIXI.Graphics();
        g.beginTextureFill({
          texture: wallTexture,
          alpha: wallTextureAlpha,
        });
        g.drawCircle(sx, sy, halfW);
        g.drawCircle(ex, ey, halfW);
        g.drawPolygon([
          sx + nx, sy + ny,
          ex + nx, ey + ny,
          ex - nx, ey - ny,
          sx - nx, sy - ny,
        ]);
        g.endFill();
        wallsContainer.addChild(g);
      });

      app.stage.addChild(wallsContainer);
      wallsResult = wallsContainer;
    }

    return { baseHexContainer, wallsContainer: wallsResult };
  } catch (error) {
    console.error("❌ Error drawing board:", error);
    throw error;
  }
};
