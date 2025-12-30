// /home/greg/projects/40k/frontend/src/utils/blinkingHPBar.ts

import * as PIXI from 'pixi.js';
import { getSelectedRangedWeapon, getSelectedMeleeWeapon } from './weaponHelpers';
import type { Unit } from '../types/game';

// Types
export interface BlinkingHPBarConfig {
    unit: Unit;
    attacker: Unit | null;
    phase: "shoot" | "fight";
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
  phase: "shoot" | "fight"
): number {
  let weapon;
  if (phase === "shoot") {
    weapon = getSelectedRangedWeapon(attacker);
  } else {
    weapon = getSelectedMeleeWeapon(attacker);
  }

  if (!weapon) return 0;

  // Hit probability
  const hitProb = Math.max(0, (7 - (weapon.ATK || 4)) / 6);

  // Wound probability
  const strength = weapon.STR || 4;
  const toughness = target.T || 4;
  let woundTarget = 4;
  if (strength >= toughness * 2) woundTarget = 2;
  else if (strength > toughness) woundTarget = 3;
  else if (strength === toughness) woundTarget = 4;
  else if (strength < toughness) woundTarget = 5;
  else woundTarget = 6;
  const woundProb = Math.max(0, (7 - woundTarget) / 6);

  // Save fail probability
  const saveTarget = Math.max(
    2,
    Math.min(
      (target.ARMOR_SAVE || 5) - (weapon.AP || 0),
      target.INVUL_SAVE || 7
    )
  );
  const saveFailProb = Math.max(0, (saveTarget - 1) / 6);

  return hitProb * woundProb * saveFailProb;
}

// Calculate damage per attack
export function calculateDamagePerAttack(
  attacker: Unit,
  phase: "shoot" | "fight"
): number {
  let weapon;
  if (phase === "shoot") {
    weapon = getSelectedRangedWeapon(attacker);
  } else {
    weapon = getSelectedMeleeWeapon(attacker);
  }
  return weapon?.DMG || 0;
}

// Create blinking HP bar container with animation
export function createBlinkingHPBar(
  config: BlinkingHPBarConfig
): BlinkingHPBarResult {
    const {
        unit,
        attacker,
        phase,
        app,
        centerX,
        finalBarX,
        finalBarY,
        finalBarWidth,
        finalBarHeight,
        sliceWidth,
        getCSSColor
      } = config;

  // Normalize unit.id to number
  const unitIdNum = typeof unit.id === 'string' ? parseInt(unit.id) : unit.id;

  // Check if container already exists
  const existingContainer = app.stage.children.find(
    child => {
      if (child.name !== 'hp-blink-container') return false;
      const container = child as HPBlinkContainer;
      if (!container.unitId) return false;
      const containerUnitIdNum = typeof container.unitId === 'string' 
        ? parseInt(container.unitId) 
        : container.unitId;
      return containerUnitIdNum === unitIdNum;
    }
  ) as HPBlinkContainer | undefined;

  // If container exists and is still blinking, reuse it
  if (existingContainer && existingContainer.blinkTicker) {
    return {
      container: existingContainer,
      cleanup: existingContainer.cleanupBlink || (() => {})
    };
  }

  // Create container
  const hpContainer = new PIXI.Container() as HPBlinkContainer;
  hpContainer.name = 'hp-blink-container';
  hpContainer.zIndex = 350;
  hpContainer.sortableChildren = true;
  hpContainer.unitId = unitIdNum;

  // Create background
  const barBg = new PIXI.Graphics();
  barBg.beginFill(0x222222, 1);
  barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
  barBg.endFill();
  barBg.zIndex = 350;
  hpContainer.background = barBg;
  hpContainer.addChild(barBg);

  // Calculate damage
  const shooterDamage = attacker 
    ? calculateDamagePerAttack(attacker, phase)
    : 0;

  // Current HP
  const currentHP = Math.max(0, unit.HP_CUR ?? unit.HP_MAX);

  // Create HP slices
  const normalSlices: PIXI.Graphics[] = [];
  const highlightSlices: PIXI.Graphics[] = [];

  if (!unit.HP_MAX) return { container: hpContainer, cleanup: () => {} };

  for (let i = 0; i < unit.HP_MAX; i++) {
    // Normal HP slice
    const normalSlice = new PIXI.Graphics();
    const normalColor = i < currentHP
      ? (unit.player === 0 
          ? getCSSColor('--hp-bar-player0') 
          : getCSSColor('--hp-bar-player1'))
      : getCSSColor('--hp-bar-lost');
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
    const wouldBeDamaged = i >= (currentHP - shooterDamage) && i < currentHP;
    const highlightColor = wouldBeDamaged
      ? getCSSColor('--hp-bar-damage-preview')
      : (i < currentHP
          ? (unit.player === 0
              ? getCSSColor('--hp-bar-player0')
              : getCSSColor('--hp-bar-player1'))
          : getCSSColor('--hp-bar-lost'));
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
      normalSlices.forEach(slice => {
        slice.visible = !blinkState;
      });
      highlightSlices.forEach(slice => {
        slice.visible = blinkState;
      });
    }
  };

  // Start blinking immediately
  blinkState = true;
  normalSlices.forEach(slice => {
    slice.visible = false;
  });
  highlightSlices.forEach(slice => {
    slice.visible = true;
  });

  // Add to PIXI Ticker
  app.ticker.add(blinkTicker);
  hpContainer.blinkTicker = blinkTicker;

  // Calculate and display probability
  let displayProbability = 0;
  if (attacker) {
    displayProbability = calculateWoundProbability(attacker, unit, phase);
  }

  // Create probability display square
  const squareSize = 35;
  const squareX = centerX - squareSize / 2;
  const squareY = finalBarY - squareSize - 8;

  const probBg = new PIXI.Graphics();
  probBg.name = `prob-bg-${unit.id}`;
  probBg.beginFill(0x333333, 0.9);
  probBg.lineStyle(2, 0x00ff00, 1);
  probBg.drawRoundedRect(squareX, squareY, squareSize, squareSize, 3);
  probBg.endFill();
  probBg.zIndex = 400;
  hpContainer.addChild(probBg);

  const probText = new PIXI.Text(`${Math.round(displayProbability * 100)}%`, {
    fontSize: 12,
    fill: 0x00ff00,
    align: "center",
    fontWeight: "bold"
  });
  probText.name = `prob-text-${unit.id}`;
  probText.anchor.set(0.5);
  probText.position.set(squareX + squareSize / 2, squareY + squareSize / 2);
  probText.zIndex = 401;
  hpContainer.addChild(probText);

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
    cleanup
  };
}

// Update probability display for existing container
export function updateProbabilityDisplay(
  container: HPBlinkContainer,
  attacker: Unit | null,
  target: Unit,
  phase: "shoot" | "fight"
): void {
  const displayProbability = attacker
    ? calculateWoundProbability(attacker, target, phase)
    : 0;

  const existingProbText = container.children.find(
    (c: PIXI.DisplayObject) => c.name === `prob-text-${target.id}`
  ) as PIXI.Text | undefined;

  if (existingProbText && existingProbText instanceof PIXI.Text) {
    existingProbText.text = `${Math.round(displayProbability * 100)}%`;
  }
}