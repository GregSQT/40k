// /home/greg/projects/40k/frontend/src/utils/blinkingHPBar.ts

import * as PIXI from "pixi.js";
import type { Unit } from "../types/game";
import { getPreferredRangedWeaponAgainstTarget } from "./probabilityCalculator";
import { getDiceAverage, getSelectedMeleeWeapon } from "./weaponHelpers";

/** Tooltip HTML (BoardPvp) : > tout z-index connu de l’app (ex. game-log 99999) ; opacité tests. */
export const DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX = 150_000;
export const DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY = 0.5;

export type HpBarHtmlTooltipPayload = {
  visible: boolean;
  text: string;
  x: number;
  y: number;
  zIndex?: number;
  opacity?: number;
};

// Types
export interface BlinkingHPBarConfig {
  unit: Unit;
  attacker: Unit | null;
  phase: "shoot" | "fight" | "charge";
  inCover: boolean;
  onTooltip?: (tooltip: HpBarHtmlTooltipPayload) => void;
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
  DMG: number | "D3" | "D6" | "2D6" | "D6+1" | "D6+2" | "D6+3";
  NB: number | "D3" | "D6" | "2D6" | "D6+1" | "D6+2" | "D6+3";
}): string {
  return [weapon.display_name, weapon.ATK, weapon.STR, weapon.AP, weapon.DMG, weapon.NB].join("|");
}

/** Aligne le texte PIXI sur `.rule-tooltip` / `App.css` (`--tooltip-font-*`). */
function readCssTooltipFontSizePx(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-font-size").trim();
  const m = raw.match(/^([\d.]+)px$/i);
  if (!m) {
    throw new Error(`CSS --tooltip-font-size must be a px length, got ${JSON.stringify(raw)}`);
  }
  return parseFloat(m[1]);
}

function readCssTooltipFontFamilyPrimary(): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-font-family").trim();
  if (!raw) {
    throw new Error("CSS --tooltip-font-family is missing or empty");
  }
  const first = raw.split(",")[0].trim().replace(/^["']|["']$/g, "");
  if (!first) {
    throw new Error("CSS --tooltip-font-family has no first family");
  }
  return first;
}

/** Poids aligné sur `--tooltip-font-weight` (PIXI.Text : surtout normal / bold). */
function readCssTooltipFontWeightForPixi(): "normal" | "bold" {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-font-weight").trim();
  if (raw === "normal") return "normal";
  if (raw === "bold") return "bold";
  const n = parseInt(raw, 10);
  if (!Number.isFinite(n)) {
    throw new Error(`Invalid CSS --tooltip-font-weight: ${JSON.stringify(raw)}`);
  }
  return n >= 600 ? "bold" : "normal";
}

/** `--tooltip-bg` (souvent rgba) → remplissage PIXI. */
function readCssTooltipBackgroundFill(): { color: number; alpha: number } {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-bg").trim();
  const rgba = raw.match(/^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/i);
  if (rgba) {
    const r = parseInt(rgba[1], 10);
    const g = parseInt(rgba[2], 10);
    const b = parseInt(rgba[3], 10);
    const a = parseFloat(rgba[4]);
    const color = (r << 16) | (g << 8) | b;
    return { color, alpha: a };
  }
  const rgb = raw.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i);
  if (rgb) {
    const r = parseInt(rgb[1], 10);
    const g = parseInt(rgb[2], 10);
    const b = parseInt(rgb[3], 10);
    return { color: (r << 16) | (g << 8) | b, alpha: 1 };
  }
  if (raw.startsWith("#")) {
    const hex = raw.replace("#", "");
    if (hex.length === 6) {
      return { color: parseInt(hex, 16), alpha: 1 };
    }
  }
  throw new Error(`Unsupported --tooltip-bg value: ${JSON.stringify(raw)}`);
}

function readCssTooltipPaddingPx(): { padX: number; padY: number } {
  const xRaw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-padding-x").trim();
  const yRaw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-padding-y").trim();
  const parsePx = (v: string, name: string): number => {
    const m = v.match(/^([\d.]+)px$/i);
    if (!m) {
      throw new Error(`${name} must be a px length, got ${JSON.stringify(v)}`);
    }
    return parseFloat(m[1]);
  };
  return { padX: parsePx(xRaw, "--tooltip-padding-x"), padY: parsePx(yRaw, "--tooltip-padding-y") };
}

function readCssTooltipBorderWidthPx(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-border-width").trim();
  const m = raw.match(/^([\d.]+)px$/i);
  if (!m) {
    throw new Error(`--tooltip-border-width must be a px length, got ${JSON.stringify(raw)}`);
  }
  return parseFloat(m[1]);
}

function readCssTooltipBorderRadiusPx(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--tooltip-border-radius").trim();
  const m = raw.match(/^([\d.]+)px$/i);
  if (!m) {
    throw new Error(`--tooltip-border-radius must be a px length, got ${JSON.stringify(raw)}`);
  }
  return parseFloat(m[1]);
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

  // Create background — scale decorative values with bar height
  const cornerR = Math.max(0.5, finalBarHeight * 0.3);
  const rawSlicePad = Math.max(0.3, finalBarHeight * 0.1);
  const slicePad = Math.min(rawSlicePad, sliceWidth * 0.15);
  const barBg = new PIXI.Graphics();
  barBg.beginFill(0x222222, 1);
  barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, cornerR);
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
      finalBarX + i * sliceWidth + slicePad,
      finalBarY + slicePad,
      sliceWidth - slicePad * 2,
      finalBarHeight - slicePad * 2,
      Math.max(0.5, cornerR * 0.7)
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
      finalBarX + i * sliceWidth + slicePad,
      finalBarY + slicePad,
      sliceWidth - slicePad * 2,
      finalBarHeight - slicePad * 2,
      Math.max(0.5, cornerR * 0.7)
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

  // Cadre % : aligné sur les design tokens `.rule-tooltip` (`App.css` : --tooltip-*).
  // Non reproduit ici : box-shadow (--tooltip-shadow), max-width, line-height multi-lignes.
  const scale = Math.max(1, finalBarHeight / 7);
  const hasCoverIcon = phase === "shoot" && inCover;

  const tooltipFontPx = readCssTooltipFontSizePx();
  const tooltipFontFamily = readCssTooltipFontFamilyPrimary();
  const tooltipFontWeight = readCssTooltipFontWeightForPixi();
  const tooltipPad = readCssTooltipPaddingPx();
  const probPadX = tooltipPad.padX + 1;
  const probPadY = tooltipPad.padY + 1;

  const probText = new PIXI.Text(`${Math.round(displayProbability * 100)}%`, {
    fontFamily: tooltipFontFamily,
    fontSize: tooltipFontPx,
    fill: getCSSColor("--tooltip-text-color"),
    align: "center",
    fontWeight: tooltipFontWeight,
  });
  /** Aligner la densité du glyphe sur le renderer (sinon texture 1× upscalée = flou vs texte HTML). */
  probText.resolution = app.renderer.resolution;
  probText.name = `prob-text-${unit.id}`;
  probText.anchor.set(0.5);
  probText.updateText(true);

  const borderW = readCssTooltipBorderWidthPx();
  const probStrokeW = Math.max(1, borderW);
  const probBoxCornerR = readCssTooltipBorderRadiusPx();
  const cellWidth = Math.ceil(probText.width) + probPadX * 2;
  const cellHeight = Math.ceil(probText.height) + probPadY * 2;

  const squareY = finalBarY - cellHeight - 4 * scale;

  /** Centre horizontal de la barre PV (identique à `centerX` quand la barre est centrée sur la figurine). */
  const barCenterX = finalBarX + finalBarWidth * 0.5;

  let coverIconPrebuilt: PIXI.Text | null = null;
  let coverIconLocalBoundsPre = new PIXI.Rectangle();
  let coverIconYPre = 0;

  if (hasCoverIcon) {
    const coverIconFontPx = Math.max(12, Math.round(tooltipFontPx * 1.45));
    coverIconPrebuilt = new PIXI.Text("🛡️", {
      fontFamily: tooltipFontFamily,
      fontSize: coverIconFontPx,
      fill: 0xfbbf24,
      align: "left",
      fontWeight: tooltipFontWeight,
      stroke: 0x38bdf8,
      strokeThickness: Math.max(1, 2 * scale),
    });
    coverIconPrebuilt.resolution = app.renderer.resolution;
    coverIconPrebuilt.name = `cover-icon-${unit.id}`;
    coverIconPrebuilt.anchor.set(0, 0.5);
    coverIconPrebuilt.updateText(true);
    coverIconLocalBoundsPre = coverIconPrebuilt.getLocalBounds();
    coverIconYPre = Math.round(squareY + cellHeight / 2);
  }

  /** Cadre % : toujours centré au-dessus de la barre (centre du rectangle = centre de la barre). */
  const squareX = Math.round(barCenterX - cellWidth * 0.5);

  /** Écart minimal après le bord droit du cadre % (bord extérieur du trait) pour ne pas chevaucher le bouclier. */
  const gapAfterProbBox = Math.max(3, Math.min(8, Math.round(scale * 2)));

  if (hasCoverIcon && coverIconPrebuilt) {
    const probRightOuter = squareX + cellWidth + probStrokeW;
    coverIconPrebuilt.position.set(
      Math.round(probRightOuter + gapAfterProbBox - coverIconLocalBoundsPre.x),
      coverIconYPre
    );
  }

  const probBg = new PIXI.Graphics();
  probBg.name = `prob-bg-${unit.id}`;
  const tooltipBgFill = readCssTooltipBackgroundFill();
  probBg.beginFill(tooltipBgFill.color, tooltipBgFill.alpha);
  probBg.lineStyle(Math.max(1, borderW), getCSSColor("--tooltip-border-color"), 1);
  probBg.drawRoundedRect(squareX, squareY, cellWidth, cellHeight, Math.max(1, probBoxCornerR));
  probBg.endFill();
  probBg.zIndex = 500;
  probBg.eventMode = "static";
  probBg.cursor = "help";
  hpContainer.addChild(probBg);

  probText.position.set(
    Math.round(squareX + cellWidth / 2),
    Math.round(squareY + cellHeight / 2)
  );
  probText.zIndex = 501;
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
      zIndex: DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX,
      opacity: DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY,
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
  probBg.on("pointerleave", hideProbabilityTooltip);
  probText.on("pointerover", updateProbabilityTooltip);
  probText.on("pointermove", updateProbabilityTooltip);
  probText.on("pointerout", hideProbabilityTooltip);
  probText.on("pointerleave", hideProbabilityTooltip);

  if (hasCoverIcon && coverIconPrebuilt) {
    const coverIcon = coverIconPrebuilt;
    coverIcon.zIndex = 502;
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
    const hideCoverTooltip = (): void => {
      onTooltip?.({
        visible: false,
        text: "COVER (+1 Save)",
        x: 0,
        y: 0,
      });
    };
    coverIcon.on("pointerout", hideCoverTooltip);
    coverIcon.on("pointerleave", hideCoverTooltip);
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
