// /home/greg/projects/40k/frontend/src/utils/blinkingHPBar.ts

import * as PIXI from "pixi.js";
import type { Unit } from "../types/game";
import { getSelectedRangedWeaponAgainstTarget } from "./probabilityCalculator";
import { getDiceAverage, getSelectedMeleeWeapon } from "./weaponHelpers";

/** Tooltip HTML (BoardPvp) : > tout z-index connu de l’app (ex. game-log 99999) ; opacité tests. */
export const DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX = 150_000;
export const DAMAGE_PROBABILITY_TOOLTIP_HTML_OPACITY = 0.5;

/**
 * Z-index PIXI du conteneur `hp-blink-container` sur le stage.
 * Au-dessus de `unitsLayer` (2000), drag (9000), `uiElementsContainer` (10000), ligne de mesure (15000),
 * pour rester lisible comme le cadre % (HTML `DAMAGE_PROBABILITY_TOOLTIP_HTML_Z_INDEX`, au-dessus du canvas).
 */
export const HP_BLINK_STAGE_Z_INDEX = 20_000;

/** Ordre relatif à l’intérieur du conteneur blink (fond puis tranches). */
const HP_BLINK_INNER_BG_Z = 350;
const HP_BLINK_INNER_SLICES_Z = 360;

/** Texte d’aide sous le cadre % (hors overlay charge jet 2D6). */
export const DEFAULT_BLINK_PROBABILITY_HELP_TEXT = "Probabilité estimée d'infliger des degats";

/** Coordonnées plateau (stage) → pixels écran pour `position: fixed` (aligné sur le canvas). */
export function pixiStagePointToClientScreen(
  app: PIXI.Application,
  stageX: number,
  stageY: number
): { x: number; y: number } {
  if (typeof document === "undefined") {
    return { x: stageX, y: stageY };
  }
  const canvas = app.view as HTMLCanvasElement;
  const rect = canvas.getBoundingClientRect();
  const sw = app.renderer.screen.width;
  const sh = app.renderer.screen.height;
  if (sw <= 0 || sh <= 0) {
    return { x: rect.left + stageX, y: rect.top + stageY };
  }
  return {
    x: rect.left + (stageX / sw) * rect.width,
    y: rect.top + (stageY / sh) * rect.height,
  };
}

/** Overlay HTML au-dessus de la barre blink (`.rule-tooltip` dans BoardPvp). */
export type BlinkProbHtmlPayload =
  | {
      action: "show";
      unitId: number;
      /** Position fixe (px) : le conteneur est centré horizontalement avec `translateX(-50%)`. */
      left: number;
      top: number;
      label: string;
      showCoverShield: boolean;
      probabilityHelpText: string;
    }
  | { action: "hide"; unitId: number }
  | {
      action: "updateLabel";
      unitId: number;
      label: string;
      showCoverShield: boolean;
      probabilityHelpText: string;
    };

export type HpBarHtmlTooltipPayload = {
  visible: boolean;
  text: string;
  x: number;
  y: number;
  zIndex?: number;
  opacity?: number;
};

// Types
/** Phase charge : remplace « XX% » par le jet 2D6 minimum (ex. `7+`) et un tooltip dédié. */
export type ChargeMinRollOverlay = {
  primaryText: string;
  tooltipText: string;
};

/**
 * @param distanceSubhexRaw Distance minimale entre empreintes en **pas de grille** (Board×10 : sous-hex).
 * @param chargeMaxInches Maximum du jet 2D6 en **pouces** (ex. 12), aligné sur `game_rules.charge_max_distance`.
 * @param inchesToSubhex Pas sous-hex par pouce (ex. 10) — `board_config.inches_to_subhex`.
 */
export function buildChargeMinRollOverlay(
  distanceSubhexRaw: number,
  chargeMaxInches: number,
  inchesToSubhex: number,
): ChargeMinRollOverlay {
  const scale = Math.max(1, Math.floor(inchesToSubhex));
  const maxSubhex = chargeMaxInches * scale;
  const dSub = Math.floor(distanceSubhexRaw);

  if (dSub <= 0) {
    return {
      primaryText: "—",
      tooltipText:
        "Empreintes adjacentes ou superposées : charge impossible vers cette cible.",
    };
  }
  if (distanceSubhexRaw > maxSubhex) {
    const approxIn = Math.ceil(distanceSubhexRaw / scale);
    return {
      primaryText: "—",
      tooltipText: `Distance minimale ≈ ${approxIn}″ (${dSub} pas sous-hex) : au-delà du maximum du jet 2D6 (${chargeMaxInches}″).`,
    };
  }
  // Jet 2D6 (2–12) en pouces ; minimum pour couvrir la distance en sous-hex.
  const minRollInches = Math.max(2, Math.ceil(distanceSubhexRaw / scale));
  return {
    primaryText: `${minRollInches}+`,
    tooltipText: `Jet 2D6 minimum : ${minRollInches}+ pour couvrir environ ${minRollInches}″ entre empreintes (1″ = ${scale} pas de grille ; ${dSub} pas mesurés).`,
  };
}

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
  /** Si défini (phase charge), remplace l’affichage probabilité / tooltip blessure. */
  chargeMinRollOverlay?: ChargeMinRollOverlay | null;
  /** Cadre % / bouclier en HTML (net) — obligatoire côté BoardPvp en jeu. */
  onBlinkProbHtml?: (payload: BlinkProbHtmlPayload) => void;
  /**
   * HP affiché dans les tranches (clignotant). Si absent, `unit.HP_CUR` (ou HP_MAX).
   * Permet la prévisu targetPreview (currentBlinkStep) et le suivi après dégâts réels.
   */
  sliceHpCur?: number;
}

/** Géométrie + métadonnées pour repeindre les tranches HP sans recréer le conteneur. */
export interface BlinkHpSliceLayout {
  finalBarX: number;
  finalBarY: number;
  sliceWidth: number;
  finalBarHeight: number;
  slicePad: number;
  cornerR: number;
  hpMax: number;
  player: Unit["player"];
}

export interface HPBlinkContainer extends PIXI.Container {
  unitId?: number;
  attackerId?: number | null;
  weaponSignature?: string | null;
  cleanupBlink?: () => void;
  blinkTicker?: () => void;
  background?: PIXI.Graphics;
  /** Références créées dans createBlinkingHPBar — mises à jour quand HP_CUR / prévisu changent. */
  blinkNormalSlices?: PIXI.Graphics[];
  blinkHighlightSlices?: PIXI.Graphics[];
  blinkSliceLayout?: BlinkHpSliceLayout;
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
    const ranged = getSelectedRangedWeaponAgainstTarget(attacker, target, inCover);
    return ranged ? ranged.overallProbability : 0;
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
    const ranged = getSelectedRangedWeaponAgainstTarget(attacker, target, inCover);
    return ranged ? ranged.potentialDamage : 0;
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

function paintRoundedHpSlice(
  gfx: PIXI.Graphics,
  x: number,
  y: number,
  w: number,
  h: number,
  sliceCornerR: number,
  fill: number
): void {
  gfx.clear();
  gfx.beginFill(fill, 1);
  gfx.drawRoundedRect(x, y, w, h, Math.max(0.5, sliceCornerR * 0.7));
  gfx.endFill();
}

/**
 * Met à jour les couleurs des tranches (normal + highlight) quand les PV ou l’aperçu de dégâts changent,
 * sans recréer le conteneur (réemploi même attaquant / même arme).
 */
export function refreshBlinkingHpBarSlices(
  container: HPBlinkContainer,
  unit: Unit,
  attacker: Unit | null,
  phase: "shoot" | "fight" | "charge",
  inCover: boolean,
  getCSSColor: (cssVar: string) => number,
  sliceHpCur?: number
): void {
  const layout = container.blinkSliceLayout;
  const normalSlices = container.blinkNormalSlices;
  const highlightSlices = container.blinkHighlightSlices;
  if (!layout || !normalSlices || !highlightSlices) return;
  if (normalSlices.length !== highlightSlices.length || normalSlices.length !== layout.hpMax) return;

  const currentHP =
    sliceHpCur !== undefined
      ? Math.max(0, sliceHpCur)
      : Math.max(0, unit.HP_CUR ?? unit.HP_MAX);
  const shooterDamage = attacker ? calculateDamagePerAttack(attacker, unit, phase, inCover) : 0;

  const lostColor = getCSSColor("--hp-bar-lost");
  const previewColor = getCSSColor("--hp-bar-damage-preview");
  const p1 = getCSSColor("--hp-bar-player1");
  const p2 = getCSSColor("--hp-bar-player2");
  const aliveColor = layout.player === 1 ? p1 : p2;

  const { finalBarX, finalBarY, sliceWidth, finalBarHeight, slicePad, cornerR, hpMax } = layout;
  const innerW = sliceWidth - slicePad * 2;
  const innerH = finalBarHeight - slicePad * 2;

  for (let i = 0; i < hpMax; i++) {
    const sx = finalBarX + i * sliceWidth + slicePad;
    const sy = finalBarY + slicePad;

    const normalColor = i < currentHP ? aliveColor : lostColor;
    paintRoundedHpSlice(normalSlices[i], sx, sy, innerW, innerH, cornerR, normalColor);

    const wouldBeDamaged = i >= currentHP - shooterDamage && i < currentHP;
    const highlightColor = wouldBeDamaged
      ? previewColor
      : i < currentHP
        ? aliveColor
        : lostColor;
    paintRoundedHpSlice(highlightSlices[i], sx, sy, innerW, innerH, cornerR, highlightColor);
  }
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

// Create blinking HP bar container with animation
export function createBlinkingHPBar(config: BlinkingHPBarConfig): BlinkingHPBarResult {
  const {
    unit,
    attacker,
    phase,
    inCover,
    onTooltip: _onTooltip,
    app,
    finalBarX,
    finalBarY,
    finalBarWidth,
    finalBarHeight,
    sliceWidth,
    getCSSColor,
    chargeMinRollOverlay,
    onBlinkProbHtml,
    sliceHpCur: sliceHpCurFromConfig,
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
      const ranged = getSelectedRangedWeaponAgainstTarget(attacker, unit, inCover);
      if (ranged) {
        weaponSignature = buildWeaponSignature(ranged.weapon);
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
  // (phase charge : pas de mise à jour rapide — le jet affiché dépend de la distance empreintes, recalculée à chaque rendu)
  if (existingContainer?.blinkTicker && phase !== "charge") {
    const attackerMatches = existingContainer.attackerId === attackerIdNum;
    const weaponMatches = existingContainer.weaponSignature === weaponSignature;
    if (attackerMatches && weaponMatches) {
      existingContainer.zIndex = HP_BLINK_STAGE_Z_INDEX;
      updateProbabilityDisplay(existingContainer, attacker, unit, phase, inCover, onBlinkProbHtml);
      refreshBlinkingHpBarSlices(
        existingContainer,
        unit,
        attacker,
        phase,
        inCover,
        getCSSColor,
        sliceHpCurFromConfig
      );
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
  hpContainer.zIndex = HP_BLINK_STAGE_Z_INDEX;
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
  barBg.zIndex = HP_BLINK_INNER_BG_Z;
  hpContainer.background = barBg;
  hpContainer.addChild(barBg);

  // Calculate damage
  const shooterDamage = attacker ? calculateDamagePerAttack(attacker, unit, phase, inCover) : 0;

  // Current HP (état serveur ou prévisu ciblée)
  const currentHP =
    sliceHpCurFromConfig !== undefined
      ? Math.max(0, sliceHpCurFromConfig)
      : Math.max(0, unit.HP_CUR ?? unit.HP_MAX);

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
    normalSlice.zIndex = HP_BLINK_INNER_SLICES_Z;
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
    highlightSlice.zIndex = HP_BLINK_INNER_SLICES_Z;
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

  // Calculate and display probability (sauf phase charge avec overlay jet 2D6)
  let displayProbability = 0;
  if (attacker && !chargeMinRollOverlay) {
    displayProbability = calculateWoundProbability(attacker, unit, phase, inCover);
  }

  const probLabel =
    chargeMinRollOverlay?.primaryText ?? `${Math.round(displayProbability * 100)}%`;

  const scale = Math.max(1, finalBarHeight / 7);
  const hasCoverIcon = phase === "shoot" && inCover;

  const tooltipFontPx = readCssTooltipFontSizePx();
  const tooltipPad = readCssTooltipPaddingPx();
  const estimatedTextHeight = Math.ceil(tooltipFontPx * 1.25);
  const cellHeight = estimatedTextHeight + (tooltipPad.padY + 1) * 2;
  const squareY = finalBarY - cellHeight - 4 * scale;
  const barCenterX = finalBarX + finalBarWidth * 0.5;
  const screenPos = pixiStagePointToClientScreen(app, barCenterX, squareY);

  const probabilityHelpText =
    chargeMinRollOverlay?.tooltipText ?? DEFAULT_BLINK_PROBABILITY_HELP_TEXT;

  onBlinkProbHtml?.({
    action: "show",
    unitId: unitIdNum,
    left: screenPos.x,
    top: screenPos.y,
    label: probLabel,
    showCoverShield: hasCoverIcon,
    probabilityHelpText,
  });

  // Cleanup function
  const cleanup = () => {
    onBlinkProbHtml?.({ action: "hide", unitId: unitIdNum });
    if (hpContainer.blinkTicker) {
      app.ticker.remove(hpContainer.blinkTicker);
    }
    if (hpContainer.parent) {
      hpContainer.parent.removeChild(hpContainer);
    }
    hpContainer.destroy({ children: true });
  };

  hpContainer.cleanupBlink = cleanup;

  hpContainer.blinkNormalSlices = normalSlices;
  hpContainer.blinkHighlightSlices = highlightSlices;
  hpContainer.blinkSliceLayout = {
    finalBarX,
    finalBarY,
    sliceWidth,
    finalBarHeight,
    slicePad,
    cornerR,
    hpMax: unit.HP_MAX,
    player: unit.player,
  };

  // Add to stage
  app.stage.addChild(hpContainer);

  return {
    container: hpContainer,
    cleanup,
  };
}

// Update probability display for existing container (overlay HTML)
export function updateProbabilityDisplay(
  _container: HPBlinkContainer,
  attacker: Unit | null,
  target: Unit,
  phase: "shoot" | "fight" | "charge",
  inCover: boolean = false,
  onBlinkProbHtml?: (payload: BlinkProbHtmlPayload) => void
): void {
  const displayProbability = attacker ? calculateWoundProbability(attacker, target, phase, inCover) : 0;
  const unitIdNum = typeof target.id === "string" ? parseInt(target.id, 10) : target.id;
  const showCoverShield = phase === "shoot" && inCover;
  onBlinkProbHtml?.({
    action: "updateLabel",
    unitId: unitIdNum,
    label: `${Math.round(displayProbability * 100)}%`,
    showCoverShield,
    probabilityHelpText: DEFAULT_BLINK_PROBABILITY_HELP_TEXT,
  });
}
