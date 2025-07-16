// frontend/src/components/Board.tsx
import React, { useEffect, useRef, useState } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
import { SingleShotDisplay } from './SingleShotDisplay';
import { setupBoardClickHandler } from '../utils/boardClickHandler';

// For flat-topped hex, even-q offset (col, row)
function offsetToCube(col: number, row: number) {
  const x = col;
  const z = row - ((col - (col & 1)) >> 1);
  const y = -x - z;
  return { x, y, z };
}

function cubeDistance(a: { x: number, y: number, z: number }, b: { x: number, y: number, z: number }) {
  return Math.max(
    Math.abs(a.x - b.x),
    Math.abs(a.y - b.y),
    Math.abs(a.z - b.z)
  );
}

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

type Mode = "select" | "movePreview" | "attackPreview" | "chargePreview";

type BoardProps = {
  units: Unit[];
  selectedUnitId: number | null;
  mode: Mode;
  movePreview: { unitId: number; destCol: number; destRow: number } | null;
  attackPreview: { unitId: number; col: number; row: number } | null;
  onSelectUnit: (id: number | string | null) => void;
  onStartMovePreview: (unitId: number | string, col: number | string, row: number | string) => void;
  onStartAttackPreview: (unitId: number, col: number, row: number) => void;
  onConfirmMove: () => void;
  onCancelMove: () => void;
  onShoot: (shooterId: number, targetId: number) => void;
  onCombatAttack?: (attackerId: number, targetId: number | null) => void;
  currentPlayer: 0 | 1;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  phase: "move" | "shoot" | "charge" | "combat";
  onCharge?: (chargerId: number, targetId: number) => void;
  onMoveCharger?: (chargerId: number, destCol: number, destRow: number) => void;
  onCancelCharge?: () => void;
  onValidateCharge?: (chargerId: number) => void;
  shootingPhaseState?: any;
  targetPreview?: TargetPreview | null;
  onCancelTargetPreview?: () => void;
};

export default function Board({
  units,
  selectedUnitId,
  mode,
  movePreview,
  attackPreview,
  onSelectUnit,
  onStartMovePreview,
  onStartAttackPreview,
  onConfirmMove,
  onCancelMove,
  currentPlayer,
  unitsMoved,
  phase,
  onShoot,
  onCombatAttack,
  onCharge,
  unitsCharged,
  unitsAttacked,
  onMoveCharger,
  onCancelCharge,
  onValidateCharge,
  shootingPhaseState,
  targetPreview,
  onCancelTargetPreview,
}: BoardProps) {
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);
  
  React.useEffect(() => {
  }, [phase, mode, selectedUnitId]);

  // ✅ HOOK 1: useRef - ALWAYS called first
  const containerRef = useRef<HTMLDivElement>(null);
  
  // ✅ HOOK 2: useGameConfig - ALWAYS called second
  const { boardConfig, loading, error } = useGameConfig();
  // ✅ STABLE CALLBACK REFS - Don't change on every render
  const stableCallbacks = useRef({
    onSelectUnit,
    onStartMovePreview,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onCombatAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge
  });

  // Update refs when props change but don't trigger re-render
  stableCallbacks.current = {
    onSelectUnit,
    onStartMovePreview,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onCombatAttack,
    onCharge,
    onMoveCharger,
    onCancelCharge,
    onValidateCharge
  };
  // ✅ HOOK 2.5: Add shooting preview state management with React state
  // ✅ REMOVE ALL ANIMATION STATE - This is causing the re-render loop
  // const [hpAnimationState, setHpAnimationState] = useState<boolean>(false);
  // const [currentShootingTarget, setCurrentShootingTarget] = useState<number | null>(null);
  // const [selectedShootingTarget, setSelectedShootingTarget] = useState<number | null>(null);
  // const animationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  // const [currentCombatTarget, setCurrentCombatTarget] = useState<number | null>(null);
  // const [selectedCombatTarget, setSelectedCombatTarget] = useState<number | null>(null);

  // ✅ HOOK 3: useEffect - MINIMAL DEPENDENCIES TO PREVENT RE-RENDER LOOPS
  useEffect(() => {
    // Early returns INSIDE useEffect to avoid hooks order violation
    if (!containerRef.current) return;

    if (loading) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#1f2937;border-radius:8px;color:white;">Loading board configuration...</div>`;
      return;
    }

    if (error) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Configuration Error: ${error}</div>`;
      return;
    }

    if (!boardConfig) {
      containerRef.current.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:400px;background:#7f1d1d;border-radius:8px;color:#fecaca;">Board configuration not loaded</div>`;
      return;
    }

    containerRef.current.innerHTML = "";

    // ✅ AGGRESSIVE TEXTURE CACHE CLEARING for movePreview units
    if (mode === "movePreview" && movePreview) {
      const previewUnit = units.find(u => u.id === movePreview.unitId);
      if (previewUnit?.ICON) {
        PIXI.Texture.removeFromCache(previewUnit.ICON);
        // Clear all cached textures to force fresh loading
        PIXI.utils.clearTextureCache();
      }
    }

    // ✅ CLEAR COMMON TEXTURE CACHE
    //PIXI.Texture.removeFromCache('/icons/AssaultIntercessor.webp');
    //PIXI.Texture.removeFromCache('/icons/AssaultIntercessor_red.webp');
    //PIXI.Texture.removeFromCache('/icons/Intercessor.webp');

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
    const parseColor = (colorStr: string): number => {
      return parseInt(colorStr.replace('0x', ''), 16);
    };

    // ✅ ALL COLORS FROM CONFIG WITH FALLBACKS
    const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight);
    const ATTACK_COLOR = parseColor(boardConfig.colors.attack || "0xff4444");
    const CHARGE_COLOR = parseColor(boardConfig.colors.charge || "0xff9900");
    const ELIGIBLE_COLOR = parseColor(boardConfig.colors.eligible || "0x00ff00");
    console.log('🎨 BOARD.TSX DEBUG - Board colors:', {
      background: parseColor(boardConfig.colors.background),
      cell_even: parseColor(boardConfig.colors.cell_even),
      cell_odd: parseColor(boardConfig.colors.cell_odd),
      highlight: HIGHLIGHT_COLOR,
      attack: ATTACK_COLOR
    });

    // ✅ ALL DISPLAY VALUES FROM CONFIG WITH FALLBACKS
    const displayConfig = boardConfig.display || {};
    const ICON_SCALE = displayConfig.icon_scale ?? 1.2;
    const ELIGIBLE_OUTLINE_WIDTH = displayConfig.eligible_outline_width ?? 3;
    const ELIGIBLE_OUTLINE_ALPHA = displayConfig.eligible_outline_alpha ?? 0.8;
    const HP_BAR_WIDTH_RATIO = displayConfig.hp_bar_width_ratio ?? 1.4;
    const HP_BAR_HEIGHT = displayConfig.hp_bar_height ?? 7;
    const HP_BAR_Y_OFFSET_RATIO = displayConfig.hp_bar_y_offset_ratio ?? 0.85;
    const UNIT_CIRCLE_RADIUS_RATIO = displayConfig.unit_circle_radius_ratio ?? 0.6;
    const UNIT_TEXT_SIZE = displayConfig.unit_text_size ?? 10;
    const SELECTED_BORDER_WIDTH = displayConfig.selected_border_width ?? 4;
    const CHARGE_TARGET_BORDER_WIDTH = displayConfig.charge_target_border_width ?? 3;
    const DEFAULT_BORDER_WIDTH = displayConfig.default_border_width ?? 2;
    const CANVAS_BORDER = displayConfig.canvas_border ?? "1px solid #333";

    const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
    const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
    const width = gridWidth + 2 * MARGIN;
    const height = gridHeight + 2 * MARGIN;

    // ✅ OPTIMIZED PIXI CONFIG - Allow WebGL for better performance
    const pixiConfig = {
      width,
      height,
      backgroundColor: parseColor(boardConfig.colors.background),
      antialias: displayConfig.antialias ?? true,
      powerPreference: "high-performance" as WebGLPowerPreference,
      resolution: displayConfig.resolution === "auto" ? (window.devicePixelRatio || 1) : (displayConfig.resolution ?? 1),
      autoDensity: displayConfig.autoDensity ?? true,
    };

    const app = new PIXI.Application(pixiConfig);
    app.stage.sortableChildren = true;

    // ✅ CANVAS STYLING FROM CONFIG
    const canvas = app.view as HTMLCanvasElement;
    canvas.style.display = 'block';
    canvas.style.maxWidth = '100%';
    canvas.style.height = 'auto';
    canvas.style.border = CANVAS_BORDER;
    
    containerRef.current.appendChild(canvas);

    // Right click cancels move/attack preview
    if (app.view && app.view.addEventListener) {
      app.view.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        
        if (phase === "shoot") {
          // During shooting phase, only cancel target preview if one exists
          if (targetPreview) {
            onCancelTargetPreview?.();
          }
          // If no target preview, do nothing (don't cancel the whole shooting)
        } else if (mode === "movePreview" || mode === "attackPreview") {
          onCancelMove?.();
        }
      });
    }

    // Logic for green (move) and red (attack) highlights
    let availableCells: { col: number; row: number }[] = [];
    const selectedUnit = units.find(u => u.id === selectedUnitId);

    // Charge preview: chargeCells & targets
    let chargeCells: { col: number; row: number }[] = [];
    let chargeTargets: Unit[] = [];

    // Combat preview: combatTargets for red outline on adjacent enemies
    let combatTargets: Unit[] = [];
    if (phase === "combat" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      
      // Red outline: all enemy units that are adjacent to the selected unit (distance = 1)
      combatTargets = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) === 1
      );
    }

    // ✅ SIMPLIFIED SHOOTING PREVIEW - No animations to prevent re-render loop
    let shootingTarget: Unit | null = null;
    if (phase === "shoot" && mode === "attackPreview" && selectedUnit && attackPreview) {
      // Simple target identification - no state changes here
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.RNG_RNG
      );
      
      // Use the first valid target or null
      shootingTarget = enemiesInRange[0] || null;
    }

    // ✅ SIMPLIFIED COMBAT PREVIEW - No animations to prevent re-render loop
    let combatTarget: Unit | null = null;
    if (phase === "combat" && selectedUnit) {
      // Simple target identification - no state changes here
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) === 1
      );
      
      // Use the first valid target or null
      combatTarget = enemiesInRange[0] || null;
    }

    if (phase === "charge" && mode === "chargePreview" && selectedUnit) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);

      // Orange cells: within MOVE, not blocked, AND adjacent to at least one enemy (within MOVE)
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          const c2 = offsetToCube(col, row);
          const dist = cubeDistance(c1, c2);
          const blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id);
          if (
            !blocked &&
            dist > 0 && dist <= selectedUnit.MOVE
          ) {
            // Only allow if adjacent to an enemy that is also within MOVE
            const adjEnemy = units.find(u =>
              u.player !== selectedUnit.player &&
              cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.MOVE &&
              cubeDistance(offsetToCube(col, row), offsetToCube(u.col, u.row)) === 1
            );
            if (adjEnemy) {
              chargeCells.push({ col, row });
            }
          }
        }
      }

      // Red outline: all enemy units within the selected unit's MOVE
      chargeTargets = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.MOVE
      );
    }

    // Green move cells (mode: 'select')
    if (selectedUnit && mode === "select" && phase !== "charge" && phase !== "combat") {
      const centerCol = selectedUnit.col;
      const centerRow = selectedUnit.row;
      const c1 = offsetToCube(centerCol, centerRow);
      for (let col = 0; col < BOARD_COLS; col++) {
        for (let row = 0; row < BOARD_ROWS; row++) {
          const c2 = offsetToCube(col, row);
          const distance = cubeDistance(c1, c2);
          const blocked = units.some(u => u.col === col && u.row === row && u.id !== selectedUnit.id);
          if (
            !blocked &&
            distance <= selectedUnit.MOVE &&
            !(col === centerCol && row === centerRow)
          ) {
            availableCells.push({ col, row });
          }
        }
      }
    }

    // Red attack cells: Either after move (movePreview) or attackPreview
    let attackCells: { col: number; row: number }[] = [];
    let previewUnit: Unit | undefined = undefined;
    let attackFromCol: number | null = null;
    let attackFromRow: number | null = null;

    if (mode === "movePreview" && movePreview) {
      previewUnit = units.find(u => u.id === movePreview.unitId);
      attackFromCol = movePreview.destCol;
      attackFromRow = movePreview.destRow;
    } else if (mode === "attackPreview" && attackPreview) {
        const clickedUnit = units.find(u => u.id === attackPreview.unitId);
        if (clickedUnit && clickedUnit.id === selectedUnitId) {
          previewUnit = clickedUnit;
          attackFromCol = clickedUnit.col;
          attackFromRow = clickedUnit.row;
        } else {
          previewUnit = undefined;
          attackFromCol = null;
          attackFromRow = null;
        }
      } else if (phase === "shoot" && selectedUnit?.SHOOT_LEFT !== undefined && selectedUnit.SHOOT_LEFT > 0) {
        previewUnit = selectedUnit;
        attackFromCol = selectedUnit.col;
        attackFromRow = selectedUnit.row;
      }

      if (
        previewUnit &&
        attackFromCol !== null &&
        attackFromRow !== null &&
        (
          mode === "movePreview" ||
          mode === "attackPreview" ||
          (phase === "shoot" && selectedUnit?.SHOOT_LEFT !== undefined && selectedUnit.SHOOT_LEFT > 0)
        )
      ) {
        const centerCube = offsetToCube(attackFromCol, attackFromRow);
        const range = previewUnit.RNG_RNG;
        for (let col = 0; col < BOARD_COLS; col++) {
          for (let row = 0; row < BOARD_ROWS; row++) {
            const targetCube = offsetToCube(col, row);
            const dist = cubeDistance(centerCube, targetCube);
            if (dist > 0 && dist <= range) {
              attackCells.push({ col, row });
            }
          }
        }
      }


    // ✅ OPTIMIZED: Create containers for hex batching
    const baseHexContainer = new PIXI.Container();
    const highlightContainer = new PIXI.Container();
    baseHexContainer.name = 'baseHexes';
    highlightContainer.name = 'highlights';

    // Draw grid cells with container batching
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
        
        // Check highlight states
        const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some(cell => cell.col === col && cell.row === row);
        const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);

        // Create base hex (always present)
        const baseCell = new PIXI.Graphics();
        const isEven = (col + row) % 2 === 0;
        const cellColor = isEven ? parseColor(boardConfig.colors.cell_even) : parseColor(boardConfig.colors.cell_odd);
        baseCell.beginFill(cellColor, 1.0);
        baseCell.lineStyle(1, parseColor(boardConfig.colors.cell_border), 0.8);
        baseCell.drawPolygon(points);
        baseCell.endFill();
        baseHexContainer.addChild(baseCell);

        // Create highlight hex (only if needed)
        if (isChargeable || isAttackable || isAvailable) {
          const highlightCell = new PIXI.Graphics();
          
          if (isChargeable) {
            highlightCell.beginFill(CHARGE_COLOR, 0.5);
          } else if (isAttackable) {
            highlightCell.beginFill(ATTACK_COLOR, 0.5);
          } else if (isAvailable) {
            highlightCell.beginFill(HIGHLIGHT_COLOR, 0.5);
          }
          
          highlightCell.drawPolygon(points);
          highlightCell.endFill();
          
          // Make interactive
          highlightCell.eventMode = 'static';
          highlightCell.cursor = "pointer";

          // Make base hex interactive for move confirmation
          baseCell.eventMode = 'static';
          baseCell.cursor = "pointer";
          
          // Add click handlers to base hexes
          if (mode === "movePreview" || mode === "attackPreview") {
            baseCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) onConfirmMove();
              if (e.button === 2) onCancelMove();
            });
          } else if (mode === "chargePreview" && isChargeable) {
            highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0 && selectedUnitId !== null) {
                onMoveCharger?.(Number(selectedUnitId), Number(col), Number(row));
              }
            });
          } else if (mode === "select" && selectedUnitId !== null && isAvailable) {
            highlightCell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) {
                onStartMovePreview(Number(selectedUnitId), Number(col), Number(row));
              }
            });
          }
          
          highlightContainer.addChild(highlightCell);
        }
      }
    }

    // ✅ AGGRESSIVE STAGE CLEANUP - Destroy everything first, then clear
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

    // ✅ ORIGINAL UNIT RENDERING - All features preserved
    for (const unit of units) {
      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

      // ✅ HP BAR USING CONFIG VALUES WITH PREVIEW SUPPORT
      if (unit.HP_MAX) {

      // In movePreview, do not draw the moving unit at its old spot
      if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) {
        continue;
      }
      // In attackPreview, do not draw the unit at its old spot if it's attackPreview
      if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) {
        continue;
      }
        const HP_BAR_WIDTH = HEX_RADIUS * HP_BAR_WIDTH_RATIO;
        const HP_BAR_Y_OFFSET = HEX_RADIUS * HP_BAR_Y_OFFSET_RATIO;

        const barX = centerX - HP_BAR_WIDTH / 2;
        const barY = centerY - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

        // Check if this unit is being previewed for shooting
        const isTargetPreviewed = targetPreview && targetPreview.targetId === unit.id;
        
        // Enhanced size for previewed targets
        const finalBarWidth = isTargetPreviewed ? HP_BAR_WIDTH * 2.5 : HP_BAR_WIDTH;
        const finalBarHeight = isTargetPreviewed ? HP_BAR_HEIGHT * 2.5 : HP_BAR_HEIGHT;
        const finalBarX = isTargetPreviewed ? centerX - finalBarWidth / 2 : barX;
        const finalBarY = isTargetPreviewed ? barY - (finalBarHeight - HP_BAR_HEIGHT) : barY;

        // Draw background (gray)
        const barBg = new PIXI.Graphics();
        barBg.beginFill(0x222222, 1);
        barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
        barBg.endFill();
        barBg.zIndex = 100;
        app.stage.addChild(barBg);
        
        // Calculate current HP and future HP for preview
        const currentHP = Math.max(0, unit.CUR_HP ?? unit.HP_MAX);
        let displayHP = currentHP;
        
        if (isTargetPreviewed && targetPreview) {
          const shooter = units.find(u => u.id === targetPreview.shooterId);
          if (shooter) {
            if (targetPreview.currentBlinkStep === 0) {
              // Step 0: Show current HP
              displayHP = currentHP;
            } else {
              // Steps 1+: Show HP after shot number (currentBlinkStep)
              const damagePerShot = shooter.RNG_DMG || 1;
              const totalDamage = targetPreview.currentBlinkStep * damagePerShot;
              displayHP = Math.max(0, currentHP - totalDamage);
            }
          }
        }
        
        // Draw HP slices
        const sliceWidth = finalBarWidth / unit.HP_MAX;
        for (let i = 0; i < unit.HP_MAX; i++) {
          const slice = new PIXI.Graphics();
          const color = i < displayHP ? parseColor(boardConfig.colors.hp_full) : parseColor(boardConfig.colors.hp_damaged);
          slice.beginFill(color, 1);
          slice.drawRoundedRect(finalBarX + i * sliceWidth + 1, finalBarY + 1, sliceWidth - 2, finalBarHeight - 2, 2);
          slice.endFill();
          slice.zIndex = 100;
          app.stage.addChild(slice);
        }
        
        // Show probability display for previewed targets
        if (isTargetPreviewed && targetPreview) {
          // Create square background
          const squareSize = 35;
          const squareX = centerX - squareSize/2; // Centered relative to HP bar
          const squareY = finalBarY - squareSize - 8; // Above the HP bar
          
          const probBg = new PIXI.Graphics();
          probBg.beginFill(0x333333, 0.9); // Dark grey background
          probBg.lineStyle(2, 0x00ff00, 1); // Green border
          probBg.drawRoundedRect(squareX, squareY, squareSize, squareSize, 3);
          probBg.endFill();
          app.stage.addChild(probBg);
          
          const probText = new PIXI.Text(
            `${Math.round(targetPreview.overallProbability)}%`,
            {
              fontSize: 12,
              fill: 0x00ff00, // Green text
              align: "center",
              fontWeight: "bold"
            }
          );
          probText.anchor.set(0.5);
          probText.position.set(squareX + squareSize/2, squareY + squareSize/2);
          app.stage.addChild(probText);
        }
      }

      // ✅ SHOOT_LEFT COUNTER - Show shots remaining during shoot phase
      if (phase === 'shoot' && unit.SHOOT_LEFT !== undefined && unit.SHOOT_LEFT > 0) {
        const shootText = new PIXI.Text(`${unit.SHOOT_LEFT}`, {
          fontSize: 14,
          fill: 0xffff00,
          align: "center",
          fontWeight: "bold",
          stroke: 0x000000,
          strokeThickness: 2
        });
        shootText.anchor.set(0.5);
        shootText.position.set(centerX + HEX_RADIUS * 0.7, centerY - HEX_RADIUS * 0.7);
        app.stage.addChild(shootText);
      }

      // ✅ GREEN ELIGIBILITY CIRCLES - Check if unit is eligible for current phase
      let isEligible = false;
      if (phase === "move") {
        isEligible = unit.player === currentPlayer && !unitsMoved.includes(Number(unit.id));
      } else if (phase === "shoot") {
        if (unit.player === currentPlayer && !unitsMoved.includes(Number(unit.id))) {
          const enemies = units.filter(u2 => u2.player !== currentPlayer);
          isEligible = enemies.some(eu => {
            const c1 = offsetToCube(unit.col, unit.row);
            const c2 = offsetToCube(eu.col, eu.row);
            return cubeDistance(c1, c2) <= unit.RNG_RNG;
          });
        }
      } else if (phase === "charge") {
        const unitsChargedArr = unitsCharged || [];
        if (unit.player === currentPlayer && !unitsChargedArr.includes(Number(unit.id))) {
          const enemies = units.filter(u2 => u2.player !== currentPlayer);
          const c1 = offsetToCube(unit.col, unit.row);
          const isAdjacent = enemies.some(eu => cubeDistance(c1, offsetToCube(eu.col, eu.row)) === 1);
          const inRange = enemies.some(eu => cubeDistance(c1, offsetToCube(eu.col, eu.row)) <= unit.MOVE);
          isEligible = !isAdjacent && inRange;
        }
      } else if (phase === "combat") {
        const unitsAttackedArr = unitsAttacked || [];
        if (unit.player === currentPlayer && !unitsAttackedArr.includes(Number(unit.id))) {
          const enemies = units.filter(u2 => u2.player !== currentPlayer);
          const c1 = offsetToCube(unit.col, unit.row);
          isEligible = enemies.some(eu => cubeDistance(c1, offsetToCube(eu.col, eu.row)) === 1);
        }
      }

      // ✅ USE ORIGINAL UNIT.COLOR - NOT CONFIG COLORS
      let unitColor = unit.color; // Use unit's own color property
      let borderColor = 0xffffff;
      let borderWidth = DEFAULT_BORDER_WIDTH;

      if (selectedUnitId === unit.id) {
        borderColor = parseColor(boardConfig.colors.current_unit); // Gold for selected
        borderWidth = SELECTED_BORDER_WIDTH;
      } else if (unitsMoved.includes(unit.id) || unitsCharged?.includes(unit.id) || unitsAttacked?.includes(unit.id)) {
        unitColor = 0x666666; // Dimmed for used units
      }
      
      // ==================== RED OUTLINE LOGIC ====================
      if (chargeTargets.some(target => target.id === unit.id)) {
        borderColor = 0xff0000;
        borderWidth = CHARGE_TARGET_BORDER_WIDTH;
      } else if (combatTargets.some(target => target.id === unit.id)) {
        borderColor = 0xff0000; // Red outline for combat targets per AI_GAME.md
        borderWidth = CHARGE_TARGET_BORDER_WIDTH;
      }
      // ==================== END RED OUTLINE LOGIC ====================

      const unitCircle = new PIXI.Graphics();
      unitCircle.beginFill(unitColor);
      unitCircle.lineStyle(borderWidth, borderColor);
      unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
      unitCircle.endFill();

      // ✅ GREEN ELIGIBILITY OUTLINE FROM CONFIG - Draw green hex outline for eligible units
      if (isEligible) {
        const eligibleOutline = new PIXI.Graphics();
        const hexPoints = getHexPolygonPoints(centerX, centerY, HEX_RADIUS * 0.9);
        eligibleOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA); // From config
        eligibleOutline.drawPolygon(hexPoints);
        app.stage.addChild(eligibleOutline);
      }

      // ✅ UNIT CLICK HANDLERS - STABLE REFERENCES
      unitCircle.eventMode = 'static';
      unitCircle.cursor = "pointer";
      
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        if (e.button === 0) {          
          // Store click data and dispatch simple event
          window.dispatchEvent(new CustomEvent('boardUnitClick', {
            detail: {
              unitId: unit.id,
              phase: phase,
              mode: mode,
              selectedUnitId: selectedUnitId
            }
          }));
        }
      });

      app.stage.addChild(unitCircle);

      // ✅ ICON RENDERING WITH PER-UNIT SCALING
      if (unit.ICON) {
        try {
          const texture = PIXI.Texture.from(unit.ICON);
          const sprite = new PIXI.Sprite(texture);
          sprite.anchor.set(0.5);
          sprite.position.set(centerX, centerY);
          
          // ✅ USE PER-UNIT ICON_SCALE OR FALLBACK TO CONFIG
          const unitIconScale = unit.ICON_SCALE || ICON_SCALE;
          sprite.width = HEX_RADIUS * unitIconScale;
          sprite.height = HEX_RADIUS * unitIconScale;
          
          app.stage.addChild(sprite);
        } catch (iconError) {
          console.warn(`Failed to load icon ${unit.ICON}:`, iconError);
          // Fallback to text if icon fails
          const unitText = new PIXI.Text(unit.name || `U${unit.id}`, {
            fontSize: UNIT_TEXT_SIZE,
            fill: 0xffffff,
            align: "center",
            fontWeight: "bold",
          });
          unitText.anchor.set(0.5);
          unitText.position.set(centerX, centerY);
          app.stage.addChild(unitText);
        }
      } else {
        // No icon - use text with config size
        const unitText = new PIXI.Text(unit.name || `U${unit.id}`, {
          fontSize: UNIT_TEXT_SIZE,
          fill: 0xffffff,
          align: "center",
          fontWeight: "bold",
        });
        unitText.anchor.set(0.5);
        unitText.position.set(centerX, centerY);
        app.stage.addChild(unitText);
      }
    }

      // ✅ ORIGINAL PREVIEW UNIT RENDERING
      if (mode === "movePreview" && movePreview) {
        const previewUnit = units.find(u => u.id === movePreview.unitId);
        if (previewUnit) {
          const centerX = movePreview.destCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = movePreview.destRow * HEX_VERT_SPACING + ((movePreview.destCol % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

          // ✅ ICON RENDERING FOR PREVIEW UNIT
          if (previewUnit.ICON) {
            try {
              // Force fresh texture - don't use cached version
              const texture = PIXI.Texture.from(previewUnit.ICON, { 
                resourceOptions: { crossorigin: 'anonymous' }
              });
              const sprite = new PIXI.Sprite(texture);
              sprite.anchor.set(0.5);
              sprite.position.set(centerX, centerY);
              const unitIconScale = previewUnit.ICON_SCALE || ICON_SCALE;
              sprite.width = HEX_RADIUS * unitIconScale;
              sprite.height = HEX_RADIUS * unitIconScale;
              sprite.alpha = 0.8; // Slightly transparent for preview
              sprite.tint = 0xffffff; // ✅ REMOVE COLOR TINTING

              // ▶️ Make preview sprite interactive for move-confirm
              sprite.eventMode = 'static';
              sprite.cursor = "pointer";
              sprite.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
                if (e.button === 0) {
                  onConfirmMove();
                }
              });

              app.stage.addChild(sprite);
              
              // ✅ DEBUG: Check what's actually on the stage
              app.stage.children.forEach((child, index) => {
                if (child.children) {
                }
              });
            } catch (iconError) {
              console.warn(`Failed to load preview icon ${previewUnit.ICON}:`, iconError);
              // Fallback to text if icon fails
              const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
                fontSize: UNIT_TEXT_SIZE,
                fill: 0xffffff,
                align: "center",
                fontWeight: "bold",
              });
              previewText.anchor.set(0.5);
              previewText.position.set(centerX, centerY);
              app.stage.addChild(previewText);
            }
          } else {
            // No icon - use text
            const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
              fontSize: UNIT_TEXT_SIZE,
              fill: 0xffffff,
              align: "center",
              fontWeight: "bold",
            });
            previewText.anchor.set(0.5);
            previewText.position.set(centerX, centerY);
            app.stage.addChild(previewText);
          }
        }
      }

        if (mode === "attackPreview" && attackPreview) {
        const previewUnit = units.find(u => u.id === attackPreview.unitId);
        if (previewUnit) {
          const centerX = attackPreview.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
          const centerY = attackPreview.row * HEX_VERT_SPACING + ((attackPreview.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

          if (attackPreview.unitId !== selectedUnitId) {
            const previewCircle = new PIXI.Graphics();
            previewCircle.beginFill(previewUnit.color, 0.7);
            previewCircle.lineStyle(3, 0xffffff, 0.8);
            previewCircle.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
            previewCircle.endFill();
            app.stage.addChild(previewCircle);
          }

          // ✅ ICON RENDERING FOR ATTACK PREVIEW UNIT
          if (previewUnit.ICON) {
            try {
              const texture = PIXI.Texture.from(previewUnit.ICON);
              const sprite = new PIXI.Sprite(texture);
              sprite.anchor.set(0.5);
              sprite.position.set(centerX, centerY);
              const unitIconScale = previewUnit.ICON_SCALE || ICON_SCALE;
              sprite.width = HEX_RADIUS * unitIconScale;
              sprite.height = HEX_RADIUS * unitIconScale;
              sprite.alpha = 0.8; // Slightly transparent for preview
              sprite.tint = 0xffffff; // ✅ REMOVE COLOR TINTING
              app.stage.addChild(sprite);
            } catch (iconError) {
              console.warn(`Failed to load attack preview icon ${previewUnit.ICON}:`, iconError);
              // Fallback to text if icon fails
              const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
                fontSize: UNIT_TEXT_SIZE,
                fill: 0xffffff,
                align: "center",
                fontWeight: "bold",
              });
              previewText.anchor.set(0.5);
              previewText.position.set(centerX, centerY);
              app.stage.addChild(previewText);
            }
          } else {
            // No icon - use text
            const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
              fontSize: UNIT_TEXT_SIZE,
              fill: 0xffffff,
              align: "center",
              fontWeight: "bold",
            });
            previewText.anchor.set(0.5);
            previewText.position.set(centerX, centerY);
            app.stage.addChild(previewText);
          }
        }
      }

      // Cleanup function
      return () => {
        if (app && app.stage) {
          // Destroy all sprites completely
          app.stage.children.forEach(child => {
            if (child.destroy) {
              child.destroy({ children: true, texture: true, baseTexture: true });
            }
          });
          app.stage.removeChildren();
        }
        app.destroy(true, { children: true, texture: true, baseTexture: true });
      };
    }, [
      // ✅ FIXED DEPENDENCIES - Prevent board re-render but allow HP animations
      units.length, // Only re-render when units count changes
      units.map(u => `${u.id}-${u.col}-${u.row}-${u.CUR_HP}`).join(','), // Only essential unit changes
      selectedUnitId,
      mode,
      phase,
      boardConfig?.cols, // Only re-render if board structure changes
      loading,
      error,
      movePreview?.unitId, // Add this to ensure preview changes trigger re-render
      movePreview?.destCol, // Add this too
      movePreview?.destRow,  // And this
      targetPreview // Keep full targetPreview for HP bar blinking
    ]);

    // Simple container return - loading/error handled inside useEffect
    return (
      <div>
        <div ref={containerRef} />
        {shootingPhaseState?.singleShotState && (
          <SingleShotDisplay
            singleShotState={shootingPhaseState.singleShotState}
            shooterName={
              units.find(u => u.id === shootingPhaseState.singleShotState?.shooterId)?.name || 
              `Unit ${shootingPhaseState.singleShotState?.shooterId}`
            }
            targetName={
              shootingPhaseState.singleShotState.targetId
                ? units.find(u => u.id === shootingPhaseState.singleShotState?.targetId)?.name || 
                  `Unit ${shootingPhaseState.singleShotState?.targetId}`
                : undefined
            }
          />
        )}
      </div>
    );
  }