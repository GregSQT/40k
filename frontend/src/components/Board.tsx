// src/components/Board.tsx - Version mise à jour compatible avec les nouveaux types
import { useEffect, useRef } from "react";
import * as PIXI from "pixi.js";
import type { Unit } from "../types/game";
import React from "react";

const BOARD_COLS = 24;
const BOARD_ROWS = 18;
const HEX_RADIUS = 24;
const MARGIN = 32;
const HEX_WIDTH = 1.5 * HEX_RADIUS;
const HEX_HEIGHT = Math.sqrt(3) * HEX_RADIUS;
const HEX_HORIZ_SPACING = HEX_WIDTH;
const HEX_VERT_SPACING = HEX_HEIGHT;
const HIGHLIGHT_COLOR = 0x80ff80; // Green
const ATTACK_COLOR = 0xff4444;    // Red

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
      backgroundColor: 0x000000,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });
    containerRef.current.appendChild(app.view as unknown as HTMLCanvasElement);
    if (app.view && app.view.style) {
      app.view.style.width = `${width}px`;
      app.view.style.height = `${height}px`;
    }

    // Right click cancels move/attack preview
    app.view.addEventListener("contextmenu", (e) => {
      if (mode === "movePreview" || mode === "attackPreview") {
        e.preventDefault();
        onCancelMove();
      }
    });

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

        // Fill: green for move, red for attack preview, ORANGE for charge preview, black otherwise
        if ((mode === "movePreview" || mode === "attackPreview") && attackCells.some(c => c.col === col && c.row === row)) {
          cell.beginFill(ATTACK_COLOR, 0.35);
        } else if (phase === "charge" && mode === "chargePreview" && chargeCells.some(c => c.col === col && c.row === row)) {
          cell.beginFill(0xff9900, 0.5); // Orange
        } else if (mode === "select" && availableCells.some(c => c.col === col && c.row === row)) {
          cell.beginFill(HIGHLIGHT_COLOR, 0.55);
        } else {
          cell.beginFill(0x002200, 1);
        }
        cell.lineStyle(2, 0xffffff, 1);
        cell.drawPolygon(points);
        cell.endFill();

        cell.eventMode = "static";
        (cell as any).buttonMode = true;

        // CHARGE PHASE: clickable orange cells
        if (phase === "charge" && mode === "chargePreview") {
          const orange = chargeCells.find(c => c.col === col && c.row === row);
          if (orange && selectedUnit) {
            cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0 && typeof onMoveCharger === "function") {
                onMoveCharger(selectedUnit.id, col, row);
              }
            });
          }
        }

        if (mode === "movePreview" && movePreview) {
          if (col === movePreview.destCol && row === movePreview.destRow) {
            cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) onConfirmMove();
              if (e.button === 2) onCancelMove();
            });
          }
        } else if (mode === "attackPreview" && attackPreview) {
          if (col === attackPreview.col && row === attackPreview.row) {
            cell.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) onConfirmMove();
              if (e.button === 2) onCancelMove();
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
          const color = i < hp ? 0x36e36b : 0x444444;
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
          const isAdjacent = enemies.some(eu => cubeDistance(offsetToCube(unit.col, unit.row), offsetToCube(eu.col, eu.row)) === 1);
          isEligible = isAdjacent;
        }
      }

      // Red outline for enemy units in range if shooter selected (shooting phase)
      if (phase === "shoot" && selectedUnitId !== null) {
        const shooter = units.find(u => u.id === selectedUnitId);
        if (shooter && shooter.player === currentPlayer && !unitsMoved.includes(Number(shooter.id))) {
          const c1 = offsetToCube(shooter.col, shooter.row);
          const c2 = offsetToCube(unit.col, unit.row);
          const inRange = shooter.RNG_RNG && shooter.player !== unit.player && cubeDistance(c1, c2) <= shooter.RNG_RNG;
          if (inRange) {
            const attackOutline = new PIXI.Graphics();
            const hexPoints = getHexPolygonPoints(centerX, centerY, HEX_RADIUS * 0.85);
            attackOutline.lineStyle(4, 0xff2222, 0.95);
            attackOutline.drawPolygon(hexPoints);
            attackOutline.endFill();
            app.stage.addChild(attackOutline);
          }
        }
      }

      // COMBAT PHASE: highlight adjacent enemy units in red when a friendly unit is selected
      if (phase === "combat" && selectedUnitId !== null) {
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
      unitCircle.lineStyle(selectedUnitId === unit.id ? 4 : 2, selectedUnitId === unit.id ? 0xffd700 : 0xffffff, 1);
      unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.7);
      unitCircle.endFill();
      unitCircle.eventMode = "static";
      (unitCircle as any).buttonMode = true;

      // Event handlers for unit interactions
      unitCircle.on("pointerdown", (e: any) => {
        e.stopPropagation();

        // Handle various phase-specific interactions
        if (phase === "charge" && mode === "chargePreview" && selectedUnitId === unit.id) {
          if (e.button === 2) {
            if (typeof onCancelCharge === "function") onCancelCharge();
            return;
          }
          if (e.button === 0) {
            if (typeof onValidateCharge === "function") onValidateCharge(unit.id);
            return;
          }
        }

        if (mode === "movePreview" && movePreview && unit.id === movePreview.unitId) {
          if (e.button === 0) onConfirmMove();
          if (e.button === 2) onCancelMove();
          return;
        }

        if (mode === "attackPreview" && attackPreview && unit.player !== currentPlayer) {
          const shooter = units.find(u => u.id === attackPreview.unitId);
          if (shooter && !unitsMoved.includes(Number(shooter.id))) {
            const c1 = offsetToCube(shooter.col, shooter.row);
            const c2 = offsetToCube(unit.col, unit.row);
            if (cubeDistance(c1, c2) <= shooter.RNG_RNG) {
              if (typeof onShoot === "function") onShoot(shooter.id, unit.id);
            }
          }
          return;
        }

        if (phase === "charge" && mode === "chargePreview" && selectedUnitId !== null && unit.player !== currentPlayer) {
          const charger = units.find(u => u.id === selectedUnitId);
          if (charger && cubeDistance(offsetToCube(charger.col, charger.row), offsetToCube(unit.col, unit.row)) <= charger.MOVE) {
            if (typeof onCharge === "function") onCharge(charger.id, unit.id);
          }
          return;
        }

        if (phase === "combat") {
          if (
            unit.player === currentPlayer &&
            !(unitsAttacked || []).includes(Number(unit.id)) &&
            e.button === 0
          ) {
            if (selectedUnitId === unit.id) {
              if (typeof onCombatAttack === "function") {
                onCombatAttack(unit.id, null);
              }
              return;
            } else {
              onSelectUnit(Number(unit.id));
              return;
            }
          }
          
          if (
            selectedUnitId !== null &&
            unit.player !== currentPlayer &&
            e.button === 0
          ) {
            const attacker = units.find(u => u.id === selectedUnitId);
            if (attacker) {
              const dist = Math.max(Math.abs(attacker.col - unit.col), Math.abs(attacker.row - unit.row));
              if (dist === 1 && typeof onCombatAttack === "function") {
                onCombatAttack(attacker.id, unit.id);
              }
            }
          }
          
          if (
            selectedUnitId !== null &&
            unit.id === selectedUnitId &&
            e.button === 2
          ) {
            if (typeof onSelectUnit === "function") onSelectUnit(null);
          }
          return;
        }

        // Fallback selection logic
        let canSelect = false;
        if (phase === "move") {
          canSelect = unit.player === currentPlayer && !unitsMoved.includes(Number(unit.id));
        } else if (phase === "shoot") {
          if (unit.player === currentPlayer && !unitsMoved.includes(Number(unit.id))) {
            const enemies = units.filter(u2 => u2.player !== currentPlayer);
            canSelect = enemies.some(eu => {
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
            canSelect = !isAdjacent && inRange;
          }
        }
        if (canSelect && e.button === 0) {
          onSelectUnit(Number(unit.id));
        }
      });
      
      app.stage.addChild(unitCircle);

      if (unit.ICON) {
        const ICON_SIZE = HEX_RADIUS * 1.5;
        const iconSprite = PIXI.Sprite.from(unit.ICON);
        iconSprite.x = centerX - ICON_SIZE / 2;
        iconSprite.y = centerY - ICON_SIZE / 2;
        iconSprite.width = ICON_SIZE;
        iconSprite.height = ICON_SIZE;
        app.stage.addChild(iconSprite);
      } else {
        const label = new PIXI.Text(unit.name, {
          fontFamily: "Arial",
          fontWeight: "bold",
          fontSize: 18,
          fill: 0xffffff,
          align: "center",
        });
        label.anchor.set(0.5);
        label.x = centerX;
        label.y = centerY;
        app.stage.addChild(label);
      }
    }

    // Draw previewed unit at its temporary destination (if any)
    if ((mode === "movePreview" && movePreview && previewUnit) ||
        (mode === "attackPreview" && attackPreview && previewUnit)) {
      const prev = mode === "movePreview" && movePreview
        ? { col: movePreview.destCol, row: movePreview.destRow, name: previewUnit.name, color: previewUnit.color, ICON: previewUnit.ICON }
        : (attackPreview && previewUnit
          ? { col: attackPreview.col, row: attackPreview.row, name: previewUnit.name, color: previewUnit.color, ICON: previewUnit.ICON }
          : null);
      if (prev) {
        const centerX = prev.col * HEX_HORIZ_SPACING + HEX_WIDTH / 2 + MARGIN;
        const centerY = prev.row * HEX_VERT_SPACING + ((prev.col % 2) * HEX_VERT_SPACING / 2) + HEX_HEIGHT / 2 + MARGIN;
        const unitCircle = new PIXI.Graphics();
        unitCircle.beginFill(prev.color);
        unitCircle.lineStyle(4, 0xffd700, 1);
        unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * 0.7);
        unitCircle.endFill();
        unitCircle.eventMode = "static";
        (unitCircle as any).buttonMode = true;
        unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
          if (e.button === 0) onConfirmMove();
          if (e.button === 2) onCancelMove();
        });
        app.stage.addChild(unitCircle);

        if (prev.ICON) {
          const ICON_SIZE = HEX_RADIUS * 1.5;
          const iconSprite = PIXI.Sprite.from(prev.ICON);
          iconSprite.x = centerX - ICON_SIZE / 2;
          iconSprite.y = centerY - ICON_SIZE / 2;
          iconSprite.width = ICON_SIZE;
          iconSprite.height = ICON_SIZE;
          app.stage.addChild(iconSprite);
        } else {
          const label = new PIXI.Text(prev.name, {
            fontFamily: "Arial",
            fontWeight: "bold",
            fontSize: 18,
            fill: 0xffffff,
            align: "center",
          });
          label.anchor.set(0.5);
          label.x = centerX;
          label.y = centerY;
          app.stage.addChild(label);
        }
      }
    }

    return () => {
      app.destroy(true, { children: true });
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, [
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
    unitsCharged,
    phase
  ]);

  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", justifyContent: "center", alignItems: "center"
    }}>
      <div ref={containerRef} />
    </div>
  );
}