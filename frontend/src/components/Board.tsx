// frontend/src/components/Board.tsx - Updated to use config system while preserving ALL functionality
import React, { useEffect, useRef } from "react";
import * as PIXI from "pixi.js-legacy";
import type { Unit } from "../types/game";
import { useGameConfig } from '../hooks/useGameConfig';
import boardConfig from "@config/board_config.json";



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
  const containerRef = useRef<HTMLDivElement>(null);
  const { boardConfig, loading, error } = useGameConfig();

  // Early return if config not loaded
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 bg-gray-800 rounded-lg">
        <div className="text-white">Loading board configuration...</div>
      </div>
    );
  }

  if (error || !boardConfig) {
    return (
      <div className="flex items-center justify-center h-64 bg-red-900 rounded-lg">
        <div className="text-red-200">Error loading board: {error}</div>
      </div>
    );
  }

  // Extract board configuration values - REPLACE HARDCODED VALUES
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

  const HIGHLIGHT_COLOR = parseColor(boardConfig.colors.highlight); // Green
  const ATTACK_COLOR = 0xff4444;    // Red

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";

    const gridWidth = (BOARD_COLS - 1) * HEX_HORIZ_SPACING + HEX_WIDTH;
    const gridHeight = (BOARD_ROWS - 1) * HEX_VERT_SPACING + HEX_HEIGHT;
    const width = gridWidth + 2 * MARGIN;
    const height = gridHeight + 2 * MARGIN;

    const app = new PIXI.Application({
      width,
      height,
      backgroundColor: parseColor(boardConfig.colors.background),
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
      forceCanvas: true, // 🔥 FORCE Canvas mode - NO WebGL!
    });

    containerRef.current.appendChild(app.view as unknown as HTMLCanvasElement);
    if (app.view && app.view.style) {
      app.view.style.width = `${width}px`;
      app.view.style.height = `${height}px`;
    }

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
    if (selectedUnit && mode === "select") {
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
          cell.beginFill(0xff9900, 0.5); // Orange for charge
        } else if (isAttackable) {
          cell.beginFill(ATTACK_COLOR, 0.5); // Red for attack
        } else if (isAvailable) {
          cell.beginFill(HIGHLIGHT_COLOR, 0.5); // Green for move
        } else {
          cell.beginFill(0x001100, 0.2); // Dark transparent
        }

        cell.lineStyle(1, 0x444444, 0.8);
        cell.drawPolygon(points);
        cell.endFill();

        // Make interactive
        cell.interactive = true;
        cell.cursor = "pointer";

        // Click handlers
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

    // Draw units (normal and previewed)
    for (const unit of units) {
      // In movePreview, do not draw the moving unit at its old spot
      if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) continue;
      // In attackPreview, do not draw the unit at its old spot if it's attackPreview
      if (mode === "attackPreview" && attackPreview && unit.id === attackPreview.unitId) continue;

      const centerX = unit.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
      const centerY = unit.row * HEX_VERT_SPACING + ((unit.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

      // Green HP bar above the unit
      if (unit.HP_MAX) {
        const HP_BAR_WIDTH = HEX_RADIUS * 1.4;
        const HP_BAR_HEIGHT = 7;
        const HP_BAR_Y_OFFSET = HEX_RADIUS * 0.85;

        const barX = centerX - HP_BAR_WIDTH / 2;
        const barY = centerY - HP_BAR_Y_OFFSET - HP_BAR_HEIGHT;

        // Draw background (gray)
        const barBg = new PIXI.Graphics();
        barBg.beginFill(0x222222, 1);
        barBg.drawRoundedRect(barX, barY, HP_BAR_WIDTH, HP_BAR_HEIGHT, 3);
        barBg.endFill();
        app.stage.addChild(barBg);

        // Draw slices (green for HP, darker for lost HP)
        const hp = Math.max(0, unit.CUR_HP ?? unit.HP_MAX);
        for (let i = 0; i < unit.HP_MAX; i++) {
          const sliceWidth = (HP_BAR_WIDTH - (unit.HP_MAX - 1)) / unit.HP_MAX;
          const sliceX = barX + i * (sliceWidth + 1);
          const color = i < hp ? parseColor(boardConfig.colors.hp_full) : parseColor(boardConfig.colors.hp_damaged);
          const slice = new PIXI.Graphics();
          slice.beginFill(color, 1);
          slice.drawRoundedRect(sliceX, barY + 1, sliceWidth, HP_BAR_HEIGHT - 2, 2);
          slice.endFill();
          app.stage.addChild(slice);
        }
      }

      // Draw green hex outline ONLY for currentPlayer's units eligible for current phase
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

      // Red outline for adjacent enemy units in combat phase
      if (phase === "combat" && selectedUnitId) {
        const attacker = units.find(u => u.id === selectedUnitId);
        if (
          attacker &&
          unit.player !== currentPlayer &&
          Math.max(Math.abs(attacker.col - unit.col), Math.abs(attacker.row - unit.row)) === 1
        ) {
          const attackOutline = new PIXI.Graphics();
          const hexPoints = getHexPolygonPoints(centerX, centerY, HEX_RADIUS * 0.85);
          attackOutline.lineStyle(4, 0xff2222, 0.95);
          attackOutline.drawPolygon(hexPoints);
          attackOutline.endFill();
          app.stage.addChild(attackOutline);
        }
      }
      
      // Red outline for enemy units in charge preview
      if (phase === "charge" && mode === "chargePreview" && chargeTargets.some(eu => eu.col === unit.col && eu.row === unit.row)) {
        const attackOutline = new PIXI.Graphics();
        const hexPoints = getHexPolygonPoints(centerX, centerY, HEX_RADIUS * 0.85);
        attackOutline.lineStyle(4, 0xff2222, 0.95);
        attackOutline.drawPolygon(hexPoints);
        attackOutline.endFill();
        app.stage.addChild(attackOutline);
      }
      
      if (isEligible) {
        const outline = new PIXI.Graphics();
        const hexPoints = getHexPolygonPoints(centerX, centerY, HEX_RADIUS * 0.9);
        outline.lineStyle(4, 0x00ff00, 0.9);
        outline.drawPolygon(hexPoints);
        outline.endFill();
        app.stage.addChild(outline);
      }

      const unitCircle = new PIXI.Graphics();
      unitCircle.beginFill(unit.color);
      unitCircle.lineStyle(selectedUnitId === unit.id ? 4 : 2, selectedUnitId === unit.id ? parseColor(boardConfig.colors.current_unit) : 0xffffff, 1);
      unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.6);
      unitCircle.endFill();

      // Make unit interactive
      unitCircle.interactive = true;
      unitCircle.cursor = "pointer";
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        e.stopPropagation();
        if (e.button === 0) {
          if (mode === "chargePreview" && selectedUnitId && onCharge) {
            const targetUnit = units.find(u => u.col === unit.col && u.row === unit.row);
            if (targetUnit && targetUnit.player !== currentPlayer) {
              onCharge(Number(selectedUnitId), Number(targetUnit.id));
              return;
            }
          }
          if (phase === "shoot" && selectedUnitId && unit.player !== currentPlayer && onShoot) {
            const shooter = units.find(u => u.id === selectedUnitId);
            if (shooter) {
              const c1 = offsetToCube(shooter.col, shooter.row);
              const c2 = offsetToCube(unit.col, unit.row);
              const distance = cubeDistance(c1, c2);
              if (distance <= shooter.RNG_RNG) {
                onShoot(Number(selectedUnitId), Number(unit.id));
                return;
              }
            }
          }
          if (phase === "combat" && selectedUnitId && unit.player !== currentPlayer && onCombatAttack) {
            const attacker = units.find(u => u.id === selectedUnitId);
            if (attacker) {
              const distance = Math.max(Math.abs(attacker.col - unit.col), Math.abs(attacker.row - unit.row));
              if (distance === 1) {
                onCombatAttack(Number(selectedUnitId), Number(unit.id));
                return;
              }
            }
          }
          onSelectUnit(unit.id);
        }
      });

      app.stage.addChild(unitCircle);

      // Unit name text
      const unitText = new PIXI.Text(unit.name || `U${unit.id}`, {
        fontSize: 11,
        fill: 0xffffff,
        align: "center",
        fontWeight: "bold",
      });
      unitText.anchor.set(0.5);
      unitText.position.set(centerX, centerY + HEX_RADIUS * 0.55);
      app.stage.addChild(unitText);
    }

    // Draw preview unit (in movePreview or attackPreview)
    if (mode === "movePreview" && movePreview) {
      const previewUnit = units.find(u => u.id === movePreview.unitId);
      if (previewUnit) {
        const centerX = movePreview.destCol * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = movePreview.destRow * HEX_VERT_SPACING + ((movePreview.destCol % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;

        const previewCircle = new PIXI.Graphics();
        previewCircle.beginFill(previewUnit.color, 0.7);
        previewCircle.lineStyle(3, 0xffffff, 0.8);
        previewCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.6);
        previewCircle.endFill();
        app.stage.addChild(previewCircle);

        const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
          fontSize: 11,
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
        previewCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.6);
        previewCircle.endFill();
        app.stage.addChild(previewCircle);

        const previewText = new PIXI.Text(previewUnit.name || `U${previewUnit.id}`, {
          fontSize: 11,
          fill: 0xffffff,
          align: "center",
          fontWeight: "bold",
        });
        previewText.anchor.set(0.5);
        previewText.position.set(centerX, centerY + HEX_RADIUS * 0.55);
        app.stage.addChild(previewText);
      }
    }

    return () => {
      app.destroy(true);
    };
  }, [
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
    BOARD_COLS,
    BOARD_ROWS,
    HEX_RADIUS,
    MARGIN,
    HEX_WIDTH,
    HEX_HEIGHT,
    HEX_HORIZ_SPACING,
    HEX_VERT_SPACING,
    HIGHLIGHT_COLOR,
    ATTACK_COLOR
  ]);

  return <div ref={containerRef} />;
}