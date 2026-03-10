// /home/greg/projects/40k/frontend/src/utils/blinkingHPBar.ts

import * as PIXI from "pixi.js";
import type { Unit } from "../types/game";
import { getPreferredRangedWeaponAgainstTarget } from "./probabilityCalculator";
import { getDiceAverage, getSelectedMeleeWeapon } from "./weaponHelpers";

// Types
export interface BlinkingHPBarConfig {
  unit: Unit;
  attacker: Unit | null;
  phase: "shoot" | "fight" | "charge";
  inCover: boolean;
  onTooltip?: (tooltip: { visible: boolean; text: string; x: number; y: number }) => void;
  app: PIXI.Application;
  centerX: number;
  finalBarX: number;
  finalBarY: number;
  finalBarWidth: number;
  finalBarHeight: number;
  sliceWidth: number;
  getCSSColor: (cssVar: string) => number;
}

export interface HPBlinkContainer extends PIXI.Container {
  unitId?: number;
  attackerId?: number | null;
  weaponSignature?: string | null;
  cleanupBlink?: () => void;
  blinkTicker?: () => void;
  background?: PIXI.Graphics;
}

export interface BlinkingHPBarResult {
  container: HPBlinkContainer;
  cleanup: () => void;
}

// Calculate wound probability for a unit
export function calculateWoundProbability(
  attacker: Unit,
  target: Unit,
  phase: "shoot" | "fight" | "charge",
  inCover: boolean = false
): number {
  if (phase === "shoot") {
    const preferred = getPreferredRangedWeaponAgainstTarget(attacker, target, inCover);
    return preferred ? preferred.overallProbability : 0;
  }

  // For charge/fight, use melee weapon
  const weapon = getSelectedMeleeWeapon(attacker);
  if (!weapon) return 0;

  const hitProb = Math.max(0, (7 - (weapon.ATK || 4)) / 6);
  const strength = weapon.STR || 4;
  const toughness = target.T || 4;
  let woundTarget = 4;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;
  const woundProb = Math.max(0, (7 - woundTarget) / 6);

  const saveTarget = Math.max(
    2,
    Math.min((target.ARMOR_SAVE || 5) - (weapon.AP || 0), target.INVUL_SAVE || 7)
  );
  const saveFailProb = Math.max(0, (saveTarget - 1) / 6);

  return hitProb * woundProb * saveFailProb;
}

// Calculate damage per attack
export function calculateDamagePerAttack(
  attacker: Unit,
  target: Unit,
  phase: "shoot" | "fight" | "charge",
  inCover: boolean = false
): number {
  if (phase === "shoot") {
    const preferred = getPreferredRangedWeaponAgainstTarget(attacker, target, inCover);
    return preferred ? preferred.potentialDamage : 0;
  }

  const weapon = getSelectedMeleeWeapon(attacker);
  if (!weapon) return 0;
  return getDiceAverage(weapon.DMG);
}

export function buildWeaponSignature(weapon: {
  display_name: string;
  ATK: number;
  STR: number;
  AP: number;
  DMG: number | "D3" | "D6" | "2D6" | "D6+1";
  NB: number | "D3" | "D6" | "2D6" | "D6+1";
}): string {
  return [weapon.display_name, weapon.ATK, weapon.STR, weapon.AP, weapon.DMG, weapon.NB].join("|");
}

// Create blinking HP bar container with animation
export function createBlinkingHPBar(config: BlinkingHPBarConfig): BlinkingHPBarResult {
  const {
    unit,
    attacker,
    phase,
    inCover,
    onTooltip,
    app,
    centerX,
    finalBarX,
    finalBarY,
    finalBarWidth,
    finalBarHeight,
    sliceWidth,
    getCSSColor,
  } = config;

  // Normalize unit.id to number
  const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;

  const attackerIdNum = attacker
    ? typeof attacker.id === "string"
      ? parseInt(attacker.id, 10)
      : attacker.id
    : null;

  let weaponSignature: string | null = null;
  if (attacker) {
    if (phase === "shoot") {
      const preferred = getPreferredRangedWeaponAgainstTarget(attacker, unit, inCover);
      if (preferred) {
        weaponSignature = buildWeaponSignature(preferred.weapon);
      }
    } else {
      const weapon = getSelectedMeleeWeapon(attacker);
      if (weapon) {
        weaponSignature = buildWeaponSignature(weapon);
      }
    }
  }

  // Check if container already exists
  const existingContainer = app.stage.children.find((child) => {
    if (child.name !== "hp-blink-container") return false;
    const container = child as HPBlinkContainer;
    if (!container.unitId) return false;
    const containerUnitIdNum =
      typeof container.unitId === "string" ? parseInt(container.unitId, 10) : container.unitId;
    return containerUnitIdNum === unitIdNum;
  }) as HPBlinkContainer | undefined;

  // If container exists and matches attacker/weapon, reuse it and update probability
  if (existingContainer?.blinkTicker) {
    const attackerMatches = existingContainer.attackerId === attackerIdNum;
    const weaponMatches = existingContainer.weaponSignature === weaponSignature;
    if (attackerMatches && weaponMatches) {
      updateProbabilityDisplay(existingContainer, attacker, unit, phase, inCover);
      return {
        container: existingContainer,
        cleanup: existingContainer.cleanupBlink || (() => {}),
      };
    }
  }

  // If container exists but ticker was removed or mismatch, clean it up and create a new one
  if (existingContainer) {
    if (existingContainer.cleanupBlink) {
      existingContainer.cleanupBlink();
    }
    if (existingContainer.parent) {
      existingContainer.parent.removeChild(existingContainer);
    }
    existingContainer.destroy({ children: true });
  }

  // Create container
  const hpContainer = new PIXI.Container() as HPBlinkContainer;
  hpContainer.name = "hp-blink-container";
  hpContainer.zIndex = 350;
  hpContainer.sortableChildren = true;
  hpContainer.unitId = unitIdNum;
  hpContainer.attackerId = attackerIdNum;
  hpContainer.weaponSignature = weaponSignature;

  // Create background
  const barBg = new PIXI.Graphics();
  barBg.beginFill(0x222222, 1);
  barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
  barBg.endFill();
  barBg.zIndex = 350;
  hpContainer.background = barBg;
  hpContainer.addChild(barBg);

  // Calculate damage
  const shooterDamage = attacker ? calculateDamagePerAttack(attacker, unit, phase, inCover) : 0;

  // Current HP
  const currentHP = Math.max(0, unit.HP_CUR ?? unit.HP_MAX);

  // Create HP slices
  const normalSlices: PIXI.Graphics[] = [];
  const highlightSlices: PIXI.Graphics[] = [];

  if (!unit.HP_MAX) return { container: hpContainer, cleanup: () => {} };

  for (let i = 0; i < unit.HP_MAX; i++) {
    // Normal HP slice
    const normalSlice = new PIXI.Graphics();
    const normalColor =
      i < currentHP
        ? unit.player === 1
          ? getCSSColor("--hp-bar-player1")
          : getCSSColor("--hp-bar-player2")
        : getCSSColor("--hp-bar-lost");
    normalSlice.beginFill(normalColor, 1);
    normalSlice.drawRoundedRect(
      finalBarX + i * sliceWidth + 1,
      finalBarY + 1,
      sliceWidth - 2,
      finalBarHeight - 2,
      2
    );
    normalSlice.endFill();
    normalSlice.zIndex = 360;
    normalSlices.push(normalSlice);
    hpContainer.addChild(normalSlice);

    // Highlight HP slice for damage preview
    const highlightSlice = new PIXI.Graphics();
    const wouldBeDamaged = i >= currentHP - shooterDamage && i < currentHP;
    const highlightColor = wouldBeDamaged
      ? getCSSColor("--hp-bar-damage-preview")
      : i < currentHP
        ? unit.player === 1
          ? getCSSColor("--hp-bar-player1")
          : getCSSColor("--hp-bar-player2")
        : getCSSColor("--hp-bar-lost");
    highlightSlice.beginFill(highlightColor, 1);
    highlightSlice.drawRoundedRect(
      finalBarX + i * sliceWidth + 1,
      finalBarY + 1,
      sliceWidth - 2,
      finalBarHeight - 2,
      2
    );
    highlightSlice.endFill();
    highlightSlice.visible = false; // Start hidden
    highlightSlice.zIndex = 360;
    highlightSlices.push(highlightSlice);
    hpContainer.addChild(highlightSlice);
  }

  // Create blinking animation
  let blinkState = false;
  let lastBlinkTime = performance.now();
  const BLINK_INTERVAL_MS = 500;

  const blinkTicker = () => {
    const now = performance.now();
    const elapsed = now - lastBlinkTime;

    if (elapsed >= BLINK_INTERVAL_MS) {
      lastBlinkTime = now;
      blinkState = !blinkState;

      // Update slice visibility
      normalSlices.forEach((slice) => {
        slice.visible = !blinkState;
      });
      highlightSlices.forEach((slice) => {
        slice.visible = blinkState;
      });
    }
  };

  // Start blinking immediately
  blinkState = true;
  normalSlices.forEach((slice) => {
    slice.visible = false;
  });
  highlightSlices.forEach((slice) => {
    slice.visible = true;
  });

  // Add to PIXI Ticker
  app.ticker.add(blinkTicker);
  hpContainer.blinkTicker = blinkTicker;

  // Calculate and display probability
  let displayProbability = 0;
  if (attacker) {
    displayProbability = calculateWoundProbability(attacker, unit, phase, inCover);
  }

  // Create probability display square
  const cellWidth = 30;
  const cellHeight = 24;
  const iconGap = 6;
  const iconAdvance = phase === "shoot" && inCover ? 24 : 0;
  const hasCoverIcon = phase === "shoot" && inCover;
  const groupWidth = cellWidth + (hasCoverIcon ? iconGap + iconAdvance : 0);
  const groupLeftX = centerX - groupWidth / 2;
  const percentageOffsetX = 2;
  const squareX = groupLeftX + percentageOffsetX;
  const squareY = finalBarY - cellHeight - 4;

  const probBg = new PIXI.Graphics();
  probBg.name = `prob-bg-${unit.id}`;
  probBg.beginFill(0x333333, 0.9);
  probBg.lineStyle(2, 0x00ff00, 1);
  probBg.drawRoundedRect(squareX, squareY, cellWidth, cellHeight, 3);
  probBg.endFill();
  probBg.zIndex = 400;
  probBg.eventMode = "static";
  probBg.cursor = "help";
  hpContainer.addChild(probBg);

  const probText = new PIXI.Text(`${Math.round(displayProbability * 100)}%`, {
    fontSize: 10,
    fill: 0xe6ffed,
    align: "center",
    fontWeight: "bold",
  });
  probText.name = `prob-text-${unit.id}`;
  probText.anchor.set(0.5);
  probText.position.set(squareX + cellWidth / 2, squareY + cellHeight / 2);
  probText.zIndex = 401;
  probText.eventMode = "static";
  probText.cursor = "help";
  hpContainer.addChild(probText);

  const probabilityTooltipText =
    "Probabilité estimée d'infliger des degats";
  const updateProbabilityTooltip = (event: PIXI.FederatedPointerEvent): void => {
    if (!onTooltip) {
      return;
    }
    const canvas = app.view as HTMLCanvasElement;
    const rect = canvas.getBoundingClientRect();
    onTooltip({
      visible: true,
      text: probabilityTooltipText,
      x: rect.left + event.global.x,
      y: rect.top + event.global.y,
    });
  };
  const hideProbabilityTooltip = (): void => {
    onTooltip?.({
      visible: false,
      text: probabilityTooltipText,
      x: 0,
      y: 0,
    });
  };
  probBg.on("pointerover", updateProbabilityTooltip);
  probBg.on("pointermove", updateProbabilityTooltip);
  probBg.on("pointerout", hideProbabilityTooltip);
  probText.on("pointerover", updateProbabilityTooltip);
  probText.on("pointermove", updateProbabilityTooltip);
  probText.on("pointerout", hideProbabilityTooltip);

  if (hasCoverIcon) {
    const coverIcon = new PIXI.Text("🛡️", {
      fontSize: 24,
      fill: 0xfbbf24,
      align: "center",
      fontWeight: "bold",
      stroke: 0x38bdf8,
      strokeThickness: 3,
    });
    coverIcon.name = `cover-icon-${unit.id}`;
    coverIcon.anchor.set(0.5);
    const iconCenterX = groupLeftX + cellWidth + iconGap + iconAdvance / 2;
    coverIcon.position.set(iconCenterX, squareY + cellHeight / 2);
    coverIcon.zIndex = 402;
    coverIcon.eventMode = "static";
    coverIcon.cursor = "help";
    coverIcon.on("pointerover", () => {
      coverIcon.style.fill = 0xfcd34d;
    });
    coverIcon.on("pointerout", () => {
      coverIcon.style.fill = 0xfbbf24;
    });
    const updateTooltipPosition = (event: PIXI.FederatedPointerEvent): void => {
      if (!onTooltip) {
        return;
      }
      const canvas = app.view as HTMLCanvasElement;
      const rect = canvas.getBoundingClientRect();
      onTooltip({
        visible: true,
        text: "COVER (+1 Save)",
        x: rect.left + event.global.x,
        y: rect.top + event.global.y,
      });
    };
    coverIcon.on("pointerover", (event: PIXI.FederatedPointerEvent) => {
      updateTooltipPosition(event);
    });
    coverIcon.on("pointermove", (event: PIXI.FederatedPointerEvent) => {
      updateTooltipPosition(event);
    });
    coverIcon.on("pointerout", () => {
      onTooltip?.({
        visible: false,
        text: "COVER (+1 Save)",
        x: 0,
        y: 0,
      });
    });
    hpContainer.addChild(coverIcon);
  }

  // Cleanup function
  const cleanup = () => {
    if (hpContainer.blinkTicker) {
      app.ticker.remove(hpContainer.blinkTicker);
    }
    if (hpContainer.parent) {
      hpContainer.parent.removeChild(hpContainer);
    }
    hpContainer.destroy({ children: true });
  };

  hpContainer.cleanupBlink = cleanup;

  // Add to stage
  app.stage.addChild(hpContainer);

  return {
    container: hpContainer,
    cleanup,
  };
}

// Update probability display for existing container
export function updateProbabilityDisplay(
  container: HPBlinkContainer,
  attacker: Unit | null,
  target: Unit,
  phase: "shoot" | "fight" | "charge",
  inCover: boolean = false
): void {
  const displayProbability = attacker ? calculateWoundProbability(attacker, target, phase, inCover) : 0;

  const existingProbText = container.children.find(
    (c: PIXI.DisplayObject) => c.name === `prob-text-${target.id}`
  ) as PIXI.Text | undefined;

  if (existingProbText && existingProbText instanceof PIXI.Text) {
    existingProbText.text = `${Math.round(displayProbability * 100)}%`;
  }
}
