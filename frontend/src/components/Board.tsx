// frontend/src/components/Board.tsx
import React, { useEffect, useRef } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';

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
}: BoardProps) {
  console.log("Board render", { phase, mode, selectedUnitId });
  
  // ✅ HOOK 1: useRef - ALWAYS called first
  const containerRef = useRef<HTMLDivElement>(null);
  
  // ✅ HOOK 2: useGameConfig - ALWAYS called second
  const { boardConfig, loading, error } = useGameConfig();
  // ✅ HOOK 2.5: Add shooting preview state management
  const animationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const shootingTargetRef = useRef<number | null>(null);
  const hpAnimationStateRef = useRef<boolean>(false); // false = current HP, true = future HP

  // ✅ HOOK 3: useEffect - ALWAYS called third, with ALL original logic
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

    // ✅ PIXI CONFIG FROM board_config.json WITH FALLBACKS
    const pixiConfig = {
      width,
      height,
      backgroundColor: parseColor(boardConfig.colors.background),
      antialias: displayConfig.antialias ?? true,
      resolution: displayConfig.resolution === "auto" ? (window.devicePixelRatio || 1) : (displayConfig.resolution ?? 1),
      autoDensity: displayConfig.autoDensity ?? true,
      forceCanvas: displayConfig.forceCanvas ?? true,
    };

    const app = new PIXI.Application(pixiConfig);

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
        if (mode === "movePreview" || mode === "attackPreview") {
          e.preventDefault();
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

    // ✅ SHOOTING PREVIEW: Identify selected shooting target
    let shootingTarget: Unit | null = null;
    if (phase === "shoot" && mode === "attackPreview" && selectedUnit && attackPreview) {
      const c1 = offsetToCube(selectedUnit.col, selectedUnit.row);
      
      // Find enemy units within shooting range
      const enemiesInRange = units.filter(u =>
        u.player !== selectedUnit.player &&
        cubeDistance(c1, offsetToCube(u.col, u.row)) <= selectedUnit.RNG_RNG
      );
      
      // For shooting, the target is at the attack preview position
      shootingTarget = enemiesInRange.find(u => 
        u.col === attackPreview.col && u.row === attackPreview.row
      ) || null;
      
      // Update animation target tracking
      if (shootingTarget && shootingTargetRef.current !== shootingTarget.id) {
        shootingTargetRef.current = shootingTarget.id;
        hpAnimationStateRef.current = false;
        
        // Clear existing animation
        if (animationIntervalRef.current) {
          clearInterval(animationIntervalRef.current);
        }
        
        // Start HP animation for shooting target
        animationIntervalRef.current = setInterval(() => {
          hpAnimationStateRef.current = !hpAnimationStateRef.current;
          // Re-render will happen automatically due to interval
        }, 1000);
      }
    } else {
      // Clear animation when not in shooting preview
      if (animationIntervalRef.current) {
        clearInterval(animationIntervalRef.current);
        animationIntervalRef.current = null;
      }
      shootingTargetRef.current = null;
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
      previewUnit = units.find(u => u.id === attackPreview.unitId);
      attackFromCol = attackPreview.col;
      attackFromRow = attackPreview.row;
    }

    if (previewUnit && attackFromCol !== null && attackFromRow !== null) {
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

    // Draw grid cells
    for (let col = 0; col < BOARD_COLS; col++) {
      for (let row = 0; row < BOARD_ROWS; row++) {
        const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const points = getHexPolygonPoints(centerX, centerY, HEX_RADIUS);
        const cell = new PIXI.Graphics();

        // Fill: green for move, red for attack, orange for charge, or transparent
        const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
        const isAttackable = attackCells.some(cell => cell.col === col && cell.row === row);
        const isChargeable = chargeCells.some(cell => cell.col === col && cell.row === row);

        if (isChargeable) {
          cell.beginFill(CHARGE_COLOR, 0.5); // Orange for charge from config
        } else if (isAttackable) {
          cell.beginFill(ATTACK_COLOR, 0.5); // Red for attack from config
        } else if (isAvailable) {
          cell.beginFill(HIGHLIGHT_COLOR, 0.5); // Green for move from config
        } else {
          cell.beginFill(0x001100, 0.2); // Dark transparent
        }

        cell.lineStyle(1, 0x444444, 0.8);
        cell.drawPolygon(points);
        cell.endFill();

        // Make interactive - FIXED: Use eventMode instead of deprecated interactive
        cell.eventMode = 'static';
        cell.cursor = "pointer";

        // ✅ ORIGINAL CLICK HANDLERS - Move confirmation logic preserved
        if (mode === "movePreview" || mode === "attackPreview") {
          cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0) onConfirmMove();
            if (e.button === 2) onCancelMove();
          });
        } else if (mode === "chargePreview") {
          if (isChargeable) {
            cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0 && selectedUnitId !== null) {
                onMoveCharger?.(Number(selectedUnitId), Number(col), Number(row));
              }
            });
          }
        } else if (mode === "select" && selectedUnitId !== null) {
          const isAvailable = availableCells.some(cell => cell.col === col && cell.row === row);
          cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0 && isAvailable) {
              onStartMovePreview(Number(selectedUnitId), Number(col), Number(row));
            }
          });
        }
        app.stage.addChild(cell);
      }
    }

    // ✅ ORIGINAL UNIT RENDERING - All features preserved
    for (const unit of units) {
      // In movePreview, do not draw the moving unit at its old spot
      if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) continue;
      // In attackPreview, do not draw the unit at its old spot if it's attackPreview
      if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

      // ✅ HP BAR USING CONFIG VALUES
      if (unit.HP_MAX) {
        const HP_BAR_WIDTH = HEX_RADIUS * HP_BAR_WIDTH_RATIO;
        const HP_BAR_Y_OFFSET = HEX_RADIUS * HP_BAR_Y_OFFSET_RATIO;

        const barX = centerX - HP_BAR_WIDTH / 2;
        const barY = centerY - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

        // Draw background (gray)
        const barBg = new PIXI.Graphics();
        barBg.beginFill(0x222222, 1);
        barBg.drawRoundedRect(barX, barY, HP_BAR_WIDTH, HP_BAR_HEIGHT, 3);
        barBg.endFill();
        app.stage.addChild(barBg);

        // ✅ ENHANCED HP BAR FOR SHOOTING TARGETS
        const isShootingTarget = shootingTarget && unit.id === shootingTarget.id;
        
        let displayHP = hp;
        let finalBarWidth = HP_BAR_WIDTH;
        let finalBarHeight = HP_BAR_HEIGHT;
        let finalBarX = barX;
        let finalBarY = barY;
        
        if (isShootingTarget && selectedUnit) {
          // Enhanced size and position for shooting targets
          finalBarWidth = HP_BAR_WIDTH * 1.8;
          finalBarHeight = HP_BAR_HEIGHT * 1.5;
          finalBarX = centerX - finalBarWidth / 2;
          finalBarY = centerY - HP_BAR_Y_OFFSET - finalBarHeight;
          
          // Alternate between current and future HP
          const futureHP = Math.max(0, (unit.CUR_HP ?? unit.HP_MAX) - selectedUnit.RNG_DMG);
          displayHP = hpAnimationStateRef.current ? futureHP : hp;
          
          // Enhanced background for shooting targets
          const enhancedBarBg = new PIXI.Graphics();
          enhancedBarBg.beginFill(0x222222, 1);
          enhancedBarBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
          enhancedBarBg.endFill();
          app.stage.addChild(enhancedBarBg);
        }
        
        // Draw HP slices with enhanced or normal size
        const sliceWidth = finalBarWidth / unit.HP_MAX;
        for (let i = 0; i < unit.HP_MAX; i++) {
          const slice = new PIXI.Graphics();
          const color = i < displayHP ? parseColor(boardConfig.colors.hp_full) : parseColor(boardConfig.colors.hp_damaged);
          slice.beginFill(color, 1);
          slice.drawRoundedRect(finalBarX + i * sliceWidth + 1, finalBarY + 1, sliceWidth - 2, finalBarHeight - 2, 2);
          slice.endFill();
          app.stage.addChild(slice);
        }
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

      // ✅ UNIT CLICK HANDLERS - FIXED SHOOT PHASE LOGIC
      unitCircle.eventMode = 'static'; // FIXED: Use eventMode instead of deprecated interactive
      unitCircle.cursor = "pointer";
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        if (e.button === 0) {
          if (mode === "attackPreview" && unit.player !== currentPlayer) {
            onShoot(Number(selectedUnitId), Number(unit.id));
          } else if (mode === "chargePreview" && unit.player !== currentPlayer && chargeTargets.some(target => target.id === unit.id)) {
            onCharge?.(Number(selectedUnitId), Number(unit.id));
          } else if (phase === "combat" && unit.player !== currentPlayer && selectedUnitId) {
            const selectedU = units.find(u => u.id === selectedUnitId);
            if (selectedU) {
              const distance = cubeDistance(
                offsetToCube(selectedU.col, selectedU.row),
                offsetToCube(unit.col, unit.row)
              );
              if (distance === 1) {
                onCombatAttack?.(Number(selectedUnitId), Number(unit.id));
                return;
              }
            }
          }
          
          // ✅ FIXED: Only allow selection of eligible units in current phase
          if (unit.player === currentPlayer) {
            if (phase === "shoot") {
              // Shoot phase: only allow units that haven't moved AND have enemies in range
              if (!unitsMoved.includes(unit.id)) {
                const enemies = units.filter(u2 => u2.player !== currentPlayer);
                const hasTargetInRange = enemies.some(eu => {
                  const c1 = offsetToCube(unit.col, unit.row);
                  const c2 = offsetToCube(eu.col, eu.row);
                  return cubeDistance(c1, c2) <= unit.RNG_RNG;
                });
                if (hasTargetInRange) {
                  onSelectUnit(unit.id);
                }
              }
            } else {
              // Other phases: allow selection if eligible (original logic)
              onSelectUnit(unit.id);
            }
          } else {
            onSelectUnit(unit.id);
          }
        }
      });

      app.stage.addChild(unitCircle);

      // ✅ ICON RENDERING FROM CONFIG - Better scaling and error handling
      if (unit.ICON) {
        try {
          const texture = PIXI.Texture.from(unit.ICON);
          const sprite = new PIXI.Sprite(texture);
          sprite.anchor.set(0.5);
          sprite.position.set(centerX, centerY);
          sprite.width = HEX_RADIUS * ICON_SCALE; // Icon size from config
          sprite.height = HEX_RADIUS * ICON_SCALE;
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

        const previewCircle = new PIXI.Graphics();
        previewCircle.beginFill(previewUnit.color, 0.7);
        previewCircle.lineStyle(3, 0xffffff, 0.8);
        previewCircle.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
        previewCircle.endFill();
        app.stage.addChild(previewCircle);

        const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
          fontSize: UNIT_TEXT_SIZE,
          fill: 0xffffff,
          align: "center",
          fontWeight: "bold",
        });
        previewText.anchor.set(0.5);
        previewText.position.set(centerX, centerY + HEX_RADIUS * 0.55);
        app.stage.addChild(previewText);
      }
    }

    if (mode === "attackPreview" && attackPreview) {
      const previewUnit = units.find(u => u.id === attackPreview.unitId);
      if (previewUnit) {
        const centerX = attackPreview.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = attackPreview.row * HEX_VERT_SPACING + ((attackPreview.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

        const previewCircle = new PIXI.Graphics();
        previewCircle.beginFill(previewUnit.color, 0.7);
        previewCircle.lineStyle(3, 0xffffff, 0.8);
        previewCircle.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
        previewCircle.endFill();
        app.stage.addChild(previewCircle);

        const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
          fontSize: UNIT_TEXT_SIZE,
          fill: 0xffffff,
          align: "center",
          fontWeight: "bold",
        });
        previewText.anchor.set(0.5);
        previewText.position.set(centerX, centerY + HEX_RADIUS * 0.55);
        app.stage.addChild(previewText);
      }
    }

    // Cleanup function
    return () => {
      // Clear animation interval
      if (animationIntervalRef.current) {
        clearInterval(animationIntervalRef.current);
        animationIntervalRef.current = null;
      }
      app.destroy(true);
    };
  }, [
    // ✅ ALL ORIGINAL DEPENDENCIES
    units,
    selectedUnitId,
    mode,
    movePreview,
    attackPreview,
    currentPlayer,
    unitsMoved,
    unitsCharged,
    unitsAttacked,
    phase,
    boardConfig,
    loading,
    error,
    onSelectUnit,
    onStartMovePreview,
    onStartAttackPreview,
    onConfirmMove,
    onCancelMove,
    onShoot,
    onCombatAttack,
    onCharge,
    onMoveCharger,
    onValidateCharge,
    // Add shooting preview dependencies  
    shootingTarget,
    hpAnimationStateRef.current
  ]);

  // Simple container return - loading/error handled inside useEffect
  return <div ref={containerRef} />;
}