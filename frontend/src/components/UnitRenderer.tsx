// frontend/src/components/UnitRenderer.tsx
import * as PIXI from "pixi.js-legacy";
import type { FightSubPhase, GameState, PlayerId, TargetPreview, Unit } from "../types/game";
import {
  buildWeaponSignature,
  createBlinkingHPBar,
  type HPBlinkContainer,
} from "../utils/blinkingHPBar";
import { cubeDistance, offsetToCube } from "../utils/gameHelpers";
import { getPreferredRangedWeaponAgainstTarget } from "../utils/probabilityCalculator";
import {
  getDiceAverage,
  getMeleeRange,
  getSelectedMeleeWeapon,
  getSelectedRangedWeapon,
} from "../utils/weaponHelpers";

interface UnitRendererProps {
  unit: Unit;
  centerX: number;
  centerY: number;
  app: PIXI.Application;
  uiElementsContainer?: PIXI.Container; // Persistent container for UI elements (target logos, badges) that should never be cleaned up
  useOverlayIcons?: boolean; // Render advance/weapon icons in DOM overlay
  isPreview?: boolean;
  previewType?: "move" | "attack";
  isEligible?: boolean; // Add eligibility as a prop instead of calculating it
  isShootable?: boolean; // Add shootability based on LoS validation

  // Blinking state for multi-unit HP bars
  blinkingUnits?: number[];
  blinkingAttackerId?: number | null;
  isBlinkingActive?: boolean;
  blinkVersion?: number;
  blinkState?: boolean;

  // Shooting target (for replay mode explosion icon)
  shootingTargetId?: number | null;
  shootingUnitId?: number | null;

  // Movement indicator (for replay mode boot icon)
  movingUnitId?: number | null;

  // Charge indicator (for replay mode lightning icon)
  chargingUnitId?: number | null;
  chargeTargetId?: number | null;

  // Fight indicator (for replay mode crossed swords icon)
  fightingUnitId?: number | null;
  fightTargetId?: number | null;

  // Charge roll display (for replay mode)
  chargeRoll?: number | null;
  chargeSuccess?: boolean;

  // Advance roll display (similar to charge roll)
  advanceRoll?: number | null;
  advancingUnitId?: number | null;

  // Board configuration
  boardConfig:
    | {
        colors?: {
          current_unit?: string;
          hp_damaged?: string;
          [key: string]: string | undefined;
        };
        [key: string]: unknown;
      }
    | Record<string, unknown>
    | null
    | {
        cols: number;
        rows: number;
        hex_radius: number;
        margin: number;
        colors: {
          [key: string]: string;
        };
        display?: {
          [key: string]: unknown;
        };
        [key: string]: unknown;
      };
  HEX_RADIUS: number;
  ICON_SCALE: number;
  ELIGIBLE_OUTLINE_WIDTH: number;
  ELIGIBLE_COLOR: number;
  ELIGIBLE_OUTLINE_ALPHA: number;
  HP_BAR_WIDTH_RATIO: number;
  HP_BAR_HEIGHT: number;
  UNIT_CIRCLE_RADIUS_RATIO: number;
  UNIT_TEXT_SIZE: number;
  SELECTED_BORDER_WIDTH: number;
  CHARGE_TARGET_BORDER_WIDTH: number;
  DEFAULT_BORDER_WIDTH: number;

  // Game state
  phase: "move" | "shoot" | "charge" | "fight";
  mode: string;
  current_player: 1 | 2;
  selectedUnitId: number | null;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  fightSubPhase?: FightSubPhase; // NEW
  fightActivePlayer?: PlayerId; // NEW
  gameState?: GameState; // Add gameState property for active_shooting_unit access
  units: Unit[];
  chargeTargets: Unit[];
  fightTargets: Unit[];
  targetPreview?: TargetPreview | null;

  // Advance action (Phase 4 - ADVANCE_IMPLEMENTATION_PLAN.md)
  canAdvance?: boolean;
  onAdvance?: (unitId: number) => void;

  // Weapon selection
  autoSelectWeapon?: boolean;

  // Callbacks
  onConfirmMove?: () => void;
  parseColor: (colorStr: string) => number;

  // Debug mode
  debugMode?: boolean;
}

export class UnitRenderer {
  private props: UnitRendererProps;
  private lastBlinkVersion: number | null = null;

  constructor(props: UnitRendererProps) {
    this.props = props;
  }

  private getCSSColor(variableName: string): number {
    const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
    if (value && value !== "") {
      // Convert hex string like "#4da6ff" to number like 0x4da6ff
      return parseInt(value.replace("#", ""), 16);
    }
    throw new Error(`CSS variable ${variableName} not found or empty`);
  }

  private getCSSNumber(variableName: string, fallback: number): number {
    const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
    if (value && value !== "") {
      return parseFloat(value);
    }
    return fallback;
  }

  private cleanupExistingBlinkIntervals(): void {
    // Find any existing blink containers and clean them up
    // Check if this unit should still be blinking
    const shouldBlink =
      this.props.isBlinkingActive && this.props.blinkingUnits?.includes(this.props.unit.id);
    const isTargetPreviewed =
      (this.props.mode === "targetPreview" || this.props.mode === "attackPreview") &&
      this.props.targetPreview &&
      this.props.targetPreview.targetId === this.props.unit.id;
    const shouldStillBlink = shouldBlink || isTargetPreviewed;
    const forceRebuild =
      this.props.blinkVersion !== undefined && this.props.blinkVersion !== this.lastBlinkVersion;
    if (this.props.blinkVersion !== undefined) {
      this.lastBlinkVersion = this.props.blinkVersion;
    }

    const unitIdNum =
      typeof this.props.unit.id === "string"
        ? parseInt(this.props.unit.id, 10)
        : this.props.unit.id;
    let expectedWeaponSignature: string | null = null;
    let attackerIdNum: number | null = null;
    let attacker: Unit | null = null;
    if (shouldStillBlink) {
      const attackerId =
        this.props.blinkingAttackerId ||
        this.props.gameState?.active_shooting_unit ||
        this.props.gameState?.active_fight_unit ||
        this.props.gameState?.active_charge_unit ||
        this.props.selectedUnitId;
      attackerIdNum = attackerId
        ? typeof attackerId === "string"
          ? parseInt(attackerId, 10)
          : attackerId
        : null;
      attacker = attackerIdNum
        ? this.props.units.find((u) => {
            const idNum = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
            return idNum === attackerIdNum;
          }) || null
        : null;
      if (attacker && this.props.phase === "shoot") {
        const preferred = getPreferredRangedWeaponAgainstTarget(attacker, this.props.unit);
        if (preferred) {
          expectedWeaponSignature = buildWeaponSignature(preferred.weapon);
        }
      }
      if (attacker && this.props.phase !== "shoot") {
        const weapon = getSelectedMeleeWeapon(attacker);
        if (weapon) {
          expectedWeaponSignature = buildWeaponSignature(weapon);
        }
      }
    }

    const existingBlinkContainers = this.props.app.stage.children.filter(
      (child) => child.name === "hp-blink-container"
    );

    existingBlinkContainers.forEach((container) => {
      // Only cleanup OLD containers that belong to current unit (prevent duplicates)
      const blinkContainer = container as HPBlinkContainer;
      const containerUnitId = blinkContainer.unitId;
      const containerUnitIdNum =
        typeof containerUnitId === "string" ? parseInt(containerUnitId, 10) : containerUnitId;
      if (containerUnitIdNum && containerUnitIdNum === unitIdNum) {
        // CRITICAL: Only destroy if unit should NO LONGER blink
        // If unit should still blink, keep the container and its animation running
        const weaponChanged =
          shouldStillBlink &&
          expectedWeaponSignature !== null &&
          blinkContainer.weaponSignature !== expectedWeaponSignature;
        if (!shouldStillBlink || weaponChanged || forceRebuild) {
          if (blinkContainer.cleanupBlink) {
            blinkContainer.cleanupBlink();
          }
          // Remove from stage before destroying to prevent re-render issues
          if (container.parent) {
            container.parent.removeChild(container);
          }
          container.destroy({ children: true });
        }
        // If shouldStillBlink is true, do nothing - let the existing container continue animating
      }
    });
  }

  render(): void {
    // Clean up any existing blink intervals before rendering new ones
    this.cleanupExistingBlinkIntervals();

    const { unit } = this.props;

    // AI_TURN.md COMPLIANCE: Dead units don't render - UNLESS just killed (show as grey ghost)
    // Just-killed units are shown in grey, then removed in the next action
    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;
    const isJustKilled = unitWithFlags.isJustKilled === true;
    if (unit.HP_CUR <= 0) {
      if (isJustKilled) {
        console.log(`Rendering just-killed unit ${unit.id} as grey ghost`);
      } else {
        return;
      }
    }

    const unitIconScale = unit.ICON_SCALE || this.props.ICON_SCALE;

    // ===== Z-INDEX CALCULATIONS =====
    const unitZIndexRange = 149;
    const minIconScale = 0.5;
    const maxIconScale = 2.5;
    const minZIndex = 100;
    const scaleRange = maxIconScale - minIconScale;
    const iconZIndex =
      minZIndex + Math.round(((maxIconScale - unitIconScale) / scaleRange) * unitZIndexRange);

    // ===== AI_TURN.md COMPLIANT ELIGIBILITY =====
    const isEligible = this.calculateEligibilityCompliant();

    // ===== RENDER COMPONENTS =====
    this.renderUnitCircle(iconZIndex);
    this.renderUnitIcon(iconZIndex);
    this.renderGreenActivationCircle(isEligible, unitIconScale);
    this.renderHPBar(unitIconScale);
    this.renderShootingCounter(unitIconScale);
    this.renderAdvanceButton(unitIconScale, iconZIndex);
    this.renderWeaponSelectionIcon(unitIconScale, iconZIndex);
    this.renderTargetIndicator(iconZIndex); // Shows 🎯 for all targets (shoot, charge, fight)
    this.renderShootingIndicator(iconZIndex);
    this.renderMovementIndicator(iconZIndex);
    this.renderAdvanceIndicator(iconZIndex);
    this.renderChargeIndicator(iconZIndex);
    this.renderFightIndicator(iconZIndex);
    this.renderAttackCounter(unitIconScale);
    this.renderChargeRollBadge(unitIconScale);
    this.renderAdvanceRollBadge(unitIconScale);
    this.renderUnitIdDebug(iconZIndex);
  }

  private calculateEligibilityCompliant(): boolean {
    const { unit, phase, current_player, unitsMoved, unitsFled } = this.props;

    // Basic eligibility checks
    // Allow just-killed units to be rendered as grey ghosts
    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;
    const isJustKilled = unitWithFlags.isJustKilled === true;
    const hpCurValue = Number(unit.HP_CUR ?? unit.HP_MAX ?? 0);
    if (Number.isNaN(hpCurValue)) {
      throw new Error(`Invalid HP_CUR value for unit ${unit.id}`);
    }
    if (unit.HP_CUR === undefined || (hpCurValue <= 0 && !isJustKilled)) return false;
    if (phase !== "fight" && unit.player !== current_player) return false;

    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot": {
        // Queue-based eligibility during active shooting phase
        // Type-safe checks with proper fallbacks
        if (unitsFled?.includes(unit.id)) return false;
        // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has ranged weapons (imported at top)
        const selectedRngWeapon = getSelectedRangedWeapon(unit);
        if (!selectedRngWeapon) return false;
        if (selectedRngWeapon.NB === undefined) {
          throw new Error(`Missing RNG weapon NB for unit ${unit.id}`);
        }
        const selectedRngWeaponNb = getDiceAverage(selectedRngWeapon.NB);
        if (selectedRngWeaponNb <= 0) return false;
        // Simplified check - parent should provide queue membership
        return this.props.isEligible || false;
      }
      case "charge":
        // Charge phase uses pool-based eligibility (charge_activation_pool)
        // Parent provides proper eligibility through isEligible prop
        // Lines 493-496: Must have enemies within charge_max_distance AND not already adjacent
        return this.props.isEligible || false;
      case "fight":
        // Fight phase uses pool-based eligibility (sub-phases)
        // Parent provides proper eligibility through isEligible prop
        return this.props.isEligible || false;
      default:
        return false;
    }
  }

  private renderUnitCircle(iconZIndex: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      isPreview,
      selectedUnitId,
      unitsMoved,
      unitsCharged,
      unitsAttacked,
      chargeTargets,
      fightTargets,
      boardConfig,
      HEX_RADIUS,
      UNIT_CIRCLE_RADIUS_RATIO,
      SELECTED_BORDER_WIDTH,
      CHARGE_TARGET_BORDER_WIDTH,
      DEFAULT_BORDER_WIDTH,
      phase,
      mode,
      current_player,
      units,
      parseColor,
    } = this.props;

    if (isPreview) return;

    // Grey-out enemies that are NOT valid shooting targets during shooting phase
    // ONLY apply when we have actual blinking data (prevents grey flash during loading)
    // - Replay mode: blinkingUnits is undefined -> skip greying
    // - PvP mode before backend responds: blinkingUnits is [] or undefined -> skip greying
    // - PvP mode with targets: blinkingUnits has IDs -> apply greying
    if (
      phase === "shoot" &&
      unit.player !== current_player &&
      selectedUnitId !== null &&
      this.props.blinkingUnits &&
      this.props.blinkingUnits.length > 0
    ) {
      const isShootable =
        this.props.isShootable !== undefined
          ? this.props.isShootable
          : this.props.blinkingUnits.includes(unit.id);

      if (!isShootable) {
        const grey = 0x888888;
        const g = new PIXI.Graphics();
        g.beginFill(grey);
        g.lineStyle(DEFAULT_BORDER_WIDTH, grey);
        g.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
        g.endFill();
        g.zIndex = iconZIndex;
        g.eventMode = "none";
        app.stage.addChild(g);
        return;
      }
    }

    let unitColor = unit.color;
    let borderColor = 0xffffff;
    let borderWidth = DEFAULT_BORDER_WIDTH;

    // Handle selection and used unit states
    if (selectedUnitId === unit.id) {
      const currentUnitColor =
        boardConfig &&
        typeof boardConfig === "object" &&
        "colors" in boardConfig &&
        boardConfig.colors &&
        typeof boardConfig.colors === "object" &&
        "current_unit" in boardConfig.colors
          ? (boardConfig.colors as { current_unit?: string }).current_unit
          : undefined;
      borderColor = parseColor(currentUnitColor || "#ffffff");
      borderWidth = SELECTED_BORDER_WIDTH;
    } else if (
      unitsMoved.includes(unit.id) ||
      unitsCharged?.includes(unit.id) ||
      unitsAttacked?.includes(unit.id)
    ) {
      unitColor = 0x666666;
    }

    // Handle red outline for targets
    if (chargeTargets.some((target) => target.id === unit.id)) {
      borderColor = 0xff0000;
      borderWidth = CHARGE_TARGET_BORDER_WIDTH;
    } else if (fightTargets.some((target) => target.id === unit.id)) {
      borderColor = 0xff0000;
      borderWidth = CHARGE_TARGET_BORDER_WIDTH;
    }

    const unitCircle = new PIXI.Graphics();

    // Ghost unit styling (for replay move visualization)
    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;

    let finalUnitColor = unitColor;
    let finalBorderColor = borderColor;
    let circleAlpha = 1.0;
    if (unitWithFlags.isGhost) {
      finalUnitColor = 0x666666; // Medium grey fill
      finalBorderColor = 0x888888; // Lighter grey border
      circleAlpha = 0.6;
    }

    // Just-killed unit styling (show as grey ghost before removal)
    if (unitWithFlags.isJustKilled) {
      finalUnitColor = 0x444444; // Dark grey fill
      finalBorderColor = 0x666666; // Medium grey border
      circleAlpha = 0.5;
    }

    unitCircle.beginFill(finalUnitColor);
    unitCircle.lineStyle(borderWidth, finalBorderColor);
    unitCircle.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
    unitCircle.endFill();
    unitCircle.alpha = circleAlpha;
    unitCircle.zIndex = iconZIndex;

    // Add click handlers for normal units (with charge-cancel on re-click)
    unitCircle.eventMode = "static";
    unitCircle.cursor = "pointer";
    // Always add click handlers so we can detect clicks on all units

    if (phase === "charge" && selectedUnitId === unit.id && this.props.mode === "chargePreview") {
      // Handle clicks on active unit in chargePreview mode (left = deselect, right = skip)
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        if (e.button === 0 || e.button === 2) {
          // Left or right click
          e.preventDefault();
          e.stopPropagation();
          window.dispatchEvent(
            new CustomEvent("boardUnitClick", {
              detail: {
                unitId: unit.id,
                phase: phase,
                mode: this.props.mode,
                selectedUnitId: selectedUnitId,
                clickType: e.button === 0 ? "left" : "right",
              },
            })
          );
        }
      });
    } else if (
      phase === "shoot" &&
      selectedUnitId === unit.id &&
      this.props.mode === "advancePreview"
    ) {
      // Cancel advance on click (left or right) of active unit in advancePreview mode
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        if (e.button === 0 || e.button === 2) {
          // Left or right click
          e.preventDefault();
          e.stopPropagation();
          window.dispatchEvent(new CustomEvent("boardCancelAdvance"));
        }
      });
    } else {
      // Block enemy unit clicks when no friendly unit is selected
      let addClickHandler = true;

      // Fight phase exception - allow clicking units in ALL fight subphases
      // Lines 738, 765, 820, 847: "player activate one unit by left clicking on it"
      const isFightPhaseActive =
        phase === "fight" &&
        (this.props.fightSubPhase === "charging" ||
          this.props.fightSubPhase === "alternating_non_active" ||
          this.props.fightSubPhase === "alternating_active" ||
          this.props.fightSubPhase === "cleanup_non_active" ||
          this.props.fightSubPhase === "cleanup_active");

      // Block enemy clicks when no unit is selected (prevents stuck preview)
      // EXCEPT during fight phase where eligible units must be clickable
      if (unit.player !== current_player && selectedUnitId === null && !isFightPhaseActive) {
        addClickHandler = false;
      }

      // CRITICAL FIX: Block enemy unit clicks during movement phase
      // In movement phase, only destinations are clickable, NOT units
      // In charge phase, block enemy clicks except in chargePreview mode where enemy units are clickable
      if (phase === "move" && unit.player !== current_player) {
        addClickHandler = false;
      }
      if (
        phase === "charge" &&
        unit.player !== current_player &&
        this.props.mode !== "chargePreview"
      ) {
        addClickHandler = false;
      }

      if (
        phase === "shoot" &&
        mode === "attackPreview" &&
        unit.player !== current_player &&
        selectedUnitId !== null &&
        this.props.blinkingUnits &&
        this.props.blinkingUnits.length > 0
      ) {
        const selectedUnit = units.find((u) => u.id === selectedUnitId);
        if (selectedUnit && !this.props.isShootable) {
          addClickHandler = false;
        }
      }
      if (addClickHandler) {
        // Check if unit is shootable during shooting phase (only in PvP mode with actual targets)
        const isShootableUnit = this.props.isShootable !== false;

        if (
          phase === "shoot" &&
          unit.player !== current_player &&
          !isShootableUnit &&
          this.props.blinkingUnits &&
          this.props.blinkingUnits.length > 0
        ) {
          // Unit is blocked by LoS in PvP mode - no click handler, no hand cursor
          unitCircle.eventMode = "none";
          unitCircle.cursor = "default";
        } else {
          unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0 || e.button === 2) {
              // Left or right click
              // Prevent context menu and event bubbling
              e.preventDefault();
              e.stopPropagation();

              if (phase === "shoot" && mode === "attackPreview" && selectedUnitId === unit.id) {
                // Handle clicks on active unit in attackPreview mode
                if (e.button === 2) {
                  // Right click: always cancel (skip)
                  window.dispatchEvent(
                    new CustomEvent("boardSkipShoot", {
                      detail: { unitId: unit.id, type: "action" },
                    })
                  );
                  return;
                } else if (e.button === 0) {
                  // Left click: dispatch to boardClickHandler for postpone/no_effect logic
                  window.dispatchEvent(
                    new CustomEvent("boardUnitClick", {
                      detail: {
                        unitId: unit.id,
                        phase: phase,
                        mode: mode,
                        selectedUnitId: selectedUnitId,
                        clickType: "left",
                      },
                    })
                  );
                  return;
                }
              }

              window.dispatchEvent(
                new CustomEvent("boardUnitClick", {
                  detail: {
                    unitId: unit.id,
                    phase: phase,
                    mode: mode,
                    selectedUnitId: selectedUnitId,
                    clickType: e.button === 0 ? "left" : "right",
                  },
                })
              );
            }
          });
        }
      } else {
        unitCircle.eventMode = "none";
        unitCircle.cursor = "default";
      }
    }

    app.stage.addChild(unitCircle);
  }

  private renderUnitIcon(iconZIndex: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      isPreview,
      previewType,
      HEX_RADIUS,
      ICON_SCALE,
      phase,
      current_player,
      onConfirmMove,
      selectedUnitId,
    } = this.props;

    const unitIconScale = unit.ICON_SCALE || ICON_SCALE;

    if (unit.ICON) {
      try {
        // Use red border icon for Player 2 units
        const iconPath = unit.player === 2 ? unit.ICON.replace(".webp", "_red.webp") : unit.ICON;

        // Get or create texture (PIXI.Texture.from uses cache if available)
        // This ensures textures are reused from cache, preventing black flashing
        const texture = PIXI.Texture.from(
          iconPath,
          isPreview ? { resourceOptions: { crossorigin: "anonymous" } } : undefined
        );

        const sprite = new PIXI.Sprite(texture);
        sprite.anchor.set(0.5);
        sprite.position.set(centerX, centerY);
        sprite.width = HEX_RADIUS * unitIconScale;
        sprite.height = HEX_RADIUS * unitIconScale;
        sprite.zIndex = iconZIndex;
        sprite.alpha = 1.0; // Always fully opaque

        interface UnitWithFlags extends Unit {
          isJustKilled?: boolean;
          isGhost?: boolean;
        }
        const unitWithFlags = unit as UnitWithFlags;

        // Ghost unit rendering (for replay move visualization)
        if (unitWithFlags.isGhost) {
          sprite.alpha = 0.5;
          sprite.tint = 0x666666;
        }

        // Just-killed unit rendering (show as dark grey before removal)
        if (unitWithFlags.isJustKilled) {
          sprite.alpha = 0.4;
          sprite.tint = 0x444444;
        }

        // Preview-specific properties
        if (isPreview) {
          if (previewType === "move") {
            sprite.eventMode = "static";
            sprite.cursor = "pointer";
            sprite.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) onConfirmMove?.();
            });
          }
          if (previewType === "attack") {
            sprite.alpha = 0.8;
          }
        }
        // Grey-out enemies that are NOT valid shooting targets during shooting phase
        // ONLY apply when we have actual blinking data (prevents grey flash during loading)
        if (
          !isPreview &&
          phase === "shoot" &&
          unit.player !== current_player &&
          selectedUnitId !== null &&
          this.props.blinkingUnits &&
          this.props.blinkingUnits.length > 0
        ) {
          const isShootable =
            this.props.isShootable !== undefined
              ? this.props.isShootable
              : this.props.blinkingUnits.includes(unit.id);

          if (!isShootable) {
            sprite.alpha = 0.5;
            sprite.tint = 0x888888;
          }
        }

        app.stage.addChild(sprite);
      } catch {
        this.renderTextFallback(iconZIndex);
      }
    } else {
      this.renderTextFallback(iconZIndex);
    }
  }

  private renderTextFallback(iconZIndex: number): void {
    const { unit, centerX, centerY, app } = this.props;

    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;

    // Ghost unit styling
    let textColor = 0xffffff;
    let textAlpha = 1.0;
    if (unitWithFlags.isGhost) {
      textColor = 0x999999;
      textAlpha = 0.7;
    }

    // Just-killed unit styling
    if (unitWithFlags.isJustKilled) {
      textColor = 0x666666;
      textAlpha = 0.5;
    }

    const unitText = new PIXI.Text(unit.name || `U${unit.id}`, {
      fontSize: this.props.UNIT_TEXT_SIZE,
      fill: textColor,
      align: "center",
      fontWeight: "bold",
    });
    unitText.anchor.set(0.5);
    unitText.position.set(centerX, centerY);
    unitText.alpha = textAlpha;
    unitText.zIndex = iconZIndex;
    app.stage.addChild(unitText);
  }

  private renderGreenActivationCircle(isEligible: boolean, unitIconScale: number): void {
    if (!isEligible) return;

    const {
      centerX,
      centerY,
      app,
      HEX_RADIUS,
      ELIGIBLE_OUTLINE_WIDTH,
      ELIGIBLE_COLOR,
      ELIGIBLE_OUTLINE_ALPHA,
    } = this.props;

    const eligibleOutline = new PIXI.Graphics();
    const circleRadius = ((HEX_RADIUS * unitIconScale) / 2) * 1.1;
    eligibleOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA);
    eligibleOutline.drawCircle(centerX, centerY, circleRadius);

    // Use same z-index calculation as icons to ensure proper layering
    const unitZIndexRange = 149;
    const minIconScale = 0.5;
    const maxIconScale = 2.5;
    const minZIndex = 100;
    const scaleRange = maxIconScale - minIconScale;
    const iconZIndex =
      minZIndex + Math.round(((maxIconScale - unitIconScale) / scaleRange) * unitZIndexRange);
    const greenCircleZIndex = iconZIndex + 50; // Always above the unit icon

    eligibleOutline.zIndex = greenCircleZIndex;
    app.stage.addChild(eligibleOutline);

    // NEW: Add red circle around green circle for charged units in fight phase
    const { unit, phase, fightSubPhase } = this.props;
    if (
      phase === "fight" &&
      fightSubPhase === "charging" &&
      unit.hasChargedThisTurn &&
      isEligible
    ) {
      const chargedOutline = new PIXI.Graphics();
      const outerCircleRadius = circleRadius + ELIGIBLE_OUTLINE_WIDTH + 2; // Slightly larger than green circle
      chargedOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, 0xff0000, ELIGIBLE_OUTLINE_ALPHA); // Red color
      chargedOutline.drawCircle(centerX, centerY, outerCircleRadius);
      chargedOutline.zIndex = 251; // Above green circle
      app.stage.addChild(chargedOutline);
    }
  }

  private renderTargetIndicator(iconZIndex: number): void {
    const {
      unit,
      shootingTargetId,
      chargeTargetId,
      fightTargetId,
      centerX,
      centerY,
      app,
      HEX_RADIUS,
      uiElementsContainer,
    } = this.props;

    // Use persistent UI container if available (for all phases - it survives drawBoard cleanup)
    // Otherwise fall back to stage (for backward compatibility)
    const targetContainer = uiElementsContainer || app.stage;

    // Show target indicator (🎯) on units that are targets of any action
    // CRITICAL: Compare as numbers to handle string/number mismatches
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
    const chargeTargetIdNum = chargeTargetId
      ? typeof chargeTargetId === "string"
        ? parseInt(chargeTargetId, 10)
        : chargeTargetId
      : null;

    const isTarget =
      (shootingTargetId &&
        unitIdNum ===
          (typeof shootingTargetId === "string"
            ? parseInt(shootingTargetId, 10)
            : shootingTargetId)) ||
      (chargeTargetIdNum && unitIdNum === chargeTargetIdNum) ||
      (fightTargetId &&
        unitIdNum ===
          (typeof fightTargetId === "string" ? parseInt(fightTargetId, 10) : fightTargetId));

    if (!isTarget) {
      return;
    }

    const iconSize = this.getCSSNumber("--icon-target-size", 1.6);
    const squareSizeRatio = this.getCSSNumber("--icon-target-square-size", 0.5);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Get values from CSS variables
    const bgColor = this.getCSSColor("--icon-target-bg-color");
    const whiteBorderColor = this.getCSSColor("--icon-square-border-color");
    const bgAlpha = this.getCSSNumber("--icon-square-bg-alpha", 1.0);
    const borderAlpha = this.getCSSNumber("--icon-square-border-alpha", 1.0);
    const borderWidth = this.getCSSNumber("--icon-square-border-width", 2);
    const borderRadius = this.getCSSNumber("--icon-square-border-radius", 4);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);

    // Create square background - size based on CSS variable
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const squareBg = new PIXI.Graphics();
    squareBg.beginFill(bgColor, bgAlpha);
    squareBg.lineStyle(borderWidth, whiteBorderColor, borderAlpha); // White border
    squareBg.drawRoundedRect(
      positionX - squareSize / 2,
      positionY - squareSize / 2,
      squareSize,
      squareSize,
      borderRadius
    );
    squareBg.endFill();
    // Clean up any existing target indicator for this unit from the container
    // This prevents duplicate logos when re-rendering
    if (targetContainer === uiElementsContainer) {
      const existingElements = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) =>
          child.name === `target-indicator-${unitIdNum}-bg` ||
          child.name === `target-indicator-${unitIdNum}-text`
      );
      existingElements.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    } else {
      // For stage, also clean up existing elements
      const existingElements = app.stage.children.filter(
        (child: PIXI.DisplayObject) =>
          (child instanceof PIXI.Graphics || child instanceof PIXI.Text) &&
          (child.name === `target-indicator-${unitIdNum}-bg` ||
            child.name === `target-indicator-${unitIdNum}-text`)
      );
      existingElements.forEach((child: PIXI.DisplayObject) => {
        app.stage.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    squareBg.name = `target-indicator-${unitIdNum}-bg`;
    squareBg.zIndex = iconZIndex + 1000; // Very high z-index to be on top of everything
    targetContainer.addChild(squareBg);

    // Create target emoji text (🎯) - keep emoji for targets
    const iconText = new PIXI.Text("🎯", {
      fontSize: HEX_RADIUS * iconSize * iconScale,
      align: "center",
      fill: 0xffffff,
    });
    iconText.anchor.set(0.5);
    iconText.position.set(positionX, positionY);
    iconText.name = `target-indicator-${unitIdNum}-text`;
    iconText.zIndex = iconZIndex + 1001; // Very high z-index to be on top of everything
    targetContainer.addChild(iconText);
  }

  // DEPRECATED: renderExplosionIcon removed - use renderTargetIndicator directly

  private renderActionIconInSquare(
    iconZIndex: number,
    iconPath: string,
    bgColorVar: string,
    _borderColorVar: string, // unused - kept for API consistency
    iconSizeVar: string,
    squareSizeVar: string,
    positionX: number,
    positionY: number
  ): void {
    const { app, HEX_RADIUS } = this.props;

    // Get values from CSS variables
    const bgColor = this.getCSSColor(bgColorVar);
    const whiteBorderColor = this.getCSSColor("--icon-square-border-color");
    const iconSize = this.getCSSNumber(iconSizeVar, 1.0);
    const squareSizeRatio = this.getCSSNumber(squareSizeVar, 0.5);
    const bgAlpha = this.getCSSNumber("--icon-square-bg-alpha", 1.0);
    const borderAlpha = this.getCSSNumber("--icon-square-border-alpha", 1.0);
    const borderWidth = this.getCSSNumber("--icon-square-border-width", 2);
    const borderRadius = this.getCSSNumber("--icon-square-border-radius", 4);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);

    // Create square background - size based on CSS variable
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const squareBg = new PIXI.Graphics();
    squareBg.beginFill(bgColor, bgAlpha);
    squareBg.lineStyle(borderWidth, whiteBorderColor, borderAlpha); // White border
    squareBg.drawRoundedRect(
      positionX - squareSize / 2,
      positionY - squareSize / 2,
      squareSize,
      squareSize,
      borderRadius
    );
    squareBg.endFill();
    squareBg.zIndex = iconZIndex + 1000; // Very high z-index to be on top of everything
    app.stage.addChild(squareBg);

    // Load and create icon sprite
    const texture = PIXI.Texture.from(iconPath);
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001; // Very high z-index to be on top of everything
    app.stage.addChild(iconSprite);
  }

  private renderActionIconInCircle(
    iconZIndex: number,
    iconPath: string, // Path to icon image file
    bgColorVar: string, // CSS variable name for background color
    iconSizeVar: string, // CSS variable name for icon size
    circleSizeVar: string, // CSS variable name for circle size ratio
    positionX: number,
    positionY: number
  ): void {
    const { app, HEX_RADIUS } = this.props;

    // Get values from CSS variables
    const bgColor = this.getCSSColor(bgColorVar);
    const whiteBorderColor = this.getCSSColor("--icon-square-border-color");
    const iconSize = this.getCSSNumber(iconSizeVar, 1.0);
    const circleSizeRatio = this.getCSSNumber(circleSizeVar, 0.5);
    const bgAlpha = this.getCSSNumber("--icon-square-bg-alpha", 1.0);
    const borderAlpha = this.getCSSNumber("--icon-square-border-alpha", 1.0);
    const borderWidth = this.getCSSNumber("--icon-square-border-width", 2);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);

    // Create circle background - size based on CSS variable
    const circleRadius = (HEX_RADIUS * circleSizeRatio) / 2;
    const circleBg = new PIXI.Graphics();
    circleBg.beginFill(bgColor, bgAlpha);
    circleBg.lineStyle(borderWidth, whiteBorderColor, borderAlpha); // White border
    circleBg.drawCircle(positionX, positionY, circleRadius);
    circleBg.endFill();
    circleBg.zIndex = iconZIndex + 1000; // Very high z-index to be on top of everything
    app.stage.addChild(circleBg);

    // Load and create icon sprite
    const texture = PIXI.Texture.from(iconPath);
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001; // Very high z-index to be on top of everything
    app.stage.addChild(iconSprite);
  }

  private renderShootingIndicator(iconZIndex: number): void {
    const { unit, shootingUnitId, centerX, centerY, HEX_RADIUS } = this.props;

    // Only show shooting indicator on the unit that is shooting
    if (!shootingUnitId || unit.id !== shootingUnitId) return;

    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Yellow/Orange background for shooting (uses standard size)
    this.renderActionIconInSquare(
      iconZIndex,
      "/icons/Action_Logo/3 - Shooting.png",
      "--icon-shoot-bg-color",
      "--icon-shoot-color",
      "--icon-shoot-size",
      "--icon-square-standard-size", // Use standard size
      positionX,
      positionY
    );
  }

  private renderMovementIndicator(iconZIndex: number): void {
    const { unit, movingUnitId, centerX, centerY, HEX_RADIUS } = this.props;

    // Only show movement indicator on the unit that is moving
    if (!movingUnitId || unit.id !== movingUnitId) return;

    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Green circle for movement (uses standard size for consistency)
    this.renderActionIconInCircle(
      iconZIndex,
      "/icons/Action_Logo/2 - Movemement.png",
      "--icon-move-bg-color",
      "--icon-move-size",
      "--icon-square-standard-size", // Use standard size for consistency
      positionX,
      positionY
    );
  }

  private renderAdvanceIndicator(iconZIndex: number): void {
    const { unit, advancingUnitId, centerX, centerY, HEX_RADIUS } = this.props;

    // Only show advance indicator on the unit that is advancing
    if (!advancingUnitId || unit.id !== advancingUnitId) return;

    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Orange background for advance (uses standard size)
    this.renderActionIconInSquare(
      iconZIndex,
      "/icons/Action_Logo/3-5 - Advance.png",
      "--icon-advance-bg-color",
      "--icon-advance-color",
      "--icon-advance-size",
      "--icon-square-standard-size", // Use standard size
      positionX,
      positionY
    );
  }

  private renderChargeIndicator(iconZIndex: number): void {
    const { unit, chargingUnitId, centerX, centerY, HEX_RADIUS } = this.props;

    // Only show charge indicator on the unit that is charging
    if (!chargingUnitId || unit.id !== chargingUnitId) return;

    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Purple background for charge (uses standard size)
    this.renderActionIconInSquare(
      iconZIndex,
      "/icons/Action_Logo/4 - Charge.png",
      "--icon-charge-bg-color",
      "--icon-charge-color",
      "--icon-charge-size",
      "--icon-square-standard-size", // Use standard size
      positionX,
      positionY
    );
  }

  // DEPRECATED: renderChargeTargetIndicator - replaced by renderTargetIndicator
  // Charge targets now show 🎯 icon via renderTargetIndicator

  private renderFightIndicator(iconZIndex: number): void {
    const { unit, fightingUnitId, centerX, centerY, HEX_RADIUS } = this.props;

    // Only show fight indicator on the unit that is fighting
    if (!fightingUnitId || unit.id !== fightingUnitId) return;

    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Red background for combat/fight (uses larger size)
    this.renderActionIconInSquare(
      iconZIndex,
      "/icons/Action_Logo/5 - Fight.png",
      "--icon-fight-bg-color",
      "--icon-fight-color",
      "--icon-fight-size",
      "--icon-fight-square-size",
      positionX,
      positionY
    );
  }

  // DEPRECATED: renderFightTargetIndicator - replaced by renderTargetIndicator
  // Fight targets now show 🎯 icon via renderTargetIndicator

  private renderHPBar(unitIconScale: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      targetPreview,
      units,
      boardConfig,
      parseColor,
      mode,
      HEX_RADIUS,
      HP_BAR_WIDTH_RATIO,
      HP_BAR_HEIGHT,
    } = this.props;

    if (!unit.HP_MAX) return; // Only skip if no HP_MAX, not if isPreview

    const scaledYOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);
    const HP_BAR_WIDTH = HEX_RADIUS * HP_BAR_WIDTH_RATIO;
    const barX = centerX - HP_BAR_WIDTH / 2;
    const barY = centerY - scaledYOffset - HP_BAR_HEIGHT;

    // Check if this unit is being previewed for shooting
    const isTargetPreviewed =
      (mode === "targetPreview" || mode === "attackPreview") &&
      targetPreview &&
      targetPreview.targetId === unit.id;

    // Check if this unit should be blinking (multi-unit blinking for valid targets)
    const shouldBlink = this.props.isBlinkingActive && this.props.blinkingUnits?.includes(unit.id);

    // Use either individual target preview OR multi-unit blinking
    const shouldShowBlinkingHP = isTargetPreviewed || shouldBlink;
    const finalBarWidth = shouldShowBlinkingHP ? HP_BAR_WIDTH * 2.5 : HP_BAR_WIDTH;
    const finalBarHeight = shouldShowBlinkingHP ? HP_BAR_HEIGHT * 2.5 : HP_BAR_HEIGHT;
    const finalBarX = shouldShowBlinkingHP ? centerX - finalBarWidth / 2 : barX;
    const finalBarY = shouldShowBlinkingHP ? barY - (finalBarHeight - HP_BAR_HEIGHT) : barY;

    // HP calculation with preview
    const currentHP = Math.max(0, unit.HP_CUR ?? unit.HP_MAX);
    let displayHP = currentHP;
    if (isTargetPreviewed && targetPreview) {
      const shooter = units.find((u) => u.id === targetPreview.shooterId);
      if (shooter) {
        if (targetPreview.currentBlinkStep === 0) {
          displayHP = currentHP;
        } else {
          // ✅ FIX: Get selected weapon and calculate damage per attack (DMG only, not DMG * NB)
          let totalDamage = 0;
          if (this.props.phase === "fight") {
            const weapon = getSelectedMeleeWeapon(shooter);
            if (weapon) {
              if (weapon.DMG === undefined) {
                throw new Error(`Missing melee weapon DMG for unit ${unit.id}`);
              }
              const weaponDamage = getDiceAverage(weapon.DMG);
              totalDamage = targetPreview.currentBlinkStep * weaponDamage;
            }
          } else {
            const preferred = getPreferredRangedWeaponAgainstTarget(shooter, unit);
            if (preferred) {
              const potentialDamage = Number(preferred.potentialDamage);
              if (Number.isNaN(potentialDamage)) {
                throw new Error(`Invalid ranged potentialDamage for unit ${unit.id}`);
              }
              totalDamage = targetPreview.currentBlinkStep * potentialDamage;
            }
          }
          displayHP = Math.max(0, currentHP - totalDamage);
        }
      }
    }

    // HP slices with blinking animation for target preview
    const sliceWidth = finalBarWidth / unit.HP_MAX;

    if (shouldShowBlinkingHP) {
      // Determine the attacker unit
      let attacker: Unit | null = null;

      if (isTargetPreviewed && targetPreview) {
        // For individual target preview
        attacker = units.find((u) => u.id === targetPreview.shooterId) || null;
      } else if (shouldBlink) {
        // For multi-unit blinking
        // CRITICAL FIX: Use blinkingAttackerId prop first (avoids React timing issues with gameState)
        // Fallback to gameState fields for shoot/fight phases
        const activeAttackerId =
          this.props.blinkingAttackerId ||
          this.props.gameState?.active_shooting_unit ||
          this.props.gameState?.active_fight_unit ||
          this.props.gameState?.active_charge_unit ||
          this.props.selectedUnitId;
        const activeAttackerIdNum = activeAttackerId
          ? typeof activeAttackerId === "string"
            ? parseInt(activeAttackerId, 10)
            : activeAttackerId
          : null;

        attacker = activeAttackerIdNum
          ? this.props.units.find((u) => {
              const unitIdNum = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
              return unitIdNum === activeAttackerIdNum;
            }) || null
          : null;
      }

      // Create blinking HP bar using the new utility module
      createBlinkingHPBar({
        unit,
        attacker,
        phase: this.props.phase as "shoot" | "fight" | "charge",
        app: this.props.app,
        centerX: this.props.centerX,
        finalBarX,
        finalBarY,
        finalBarWidth,
        finalBarHeight,
        sliceWidth,
        getCSSColor: this.getCSSColor.bind(this),
      });

      // If targetPreview has overallProbability, update the display
      if (isTargetPreviewed && targetPreview && targetPreview.overallProbability !== undefined) {
        // Find the container and update probability display
        const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
        const existingContainer = this.props.app.stage.children.find((child) => {
          if (child.name !== "hp-blink-container") return false;
          const blinkContainer = child as HPBlinkContainer;
          if (!blinkContainer.unitId) return false;
          const containerUnitIdNum =
            typeof blinkContainer.unitId === "string"
              ? parseInt(blinkContainer.unitId, 10)
              : blinkContainer.unitId;
          return containerUnitIdNum === unitIdNum;
        }) as HPBlinkContainer | undefined;

        if (existingContainer) {
          const existingProbText = existingContainer.children.find(
            (c: PIXI.DisplayObject) => c.name === `prob-text-${unit.id}`
          ) as PIXI.Text | undefined;

          if (existingProbText && existingProbText instanceof PIXI.Text) {
            existingProbText.text = `${Math.round(targetPreview.overallProbability * 100)}%`;
          }
        }
      }

      // Skip normal HP bar rendering when blinking
      return;
    } else {
      // Normal non-blinking HP slices
      // Create background for normal HP bar
      const barBg = new PIXI.Graphics();
      barBg.beginFill(0x222222, 1);
      barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
      barBg.endFill();
      barBg.zIndex = 350;
      app.stage.addChild(barBg);

      for (let i = 0; i < unit.HP_MAX; i++) {
        const slice = new PIXI.Graphics();
        const hpDamagedColor =
          boardConfig &&
          typeof boardConfig === "object" &&
          "colors" in boardConfig &&
          boardConfig.colors &&
          typeof boardConfig.colors === "object" &&
          "hp_damaged" in boardConfig.colors
            ? (boardConfig.colors as { hp_damaged?: string }).hp_damaged
            : undefined;
        const color =
          i < displayHP
            ? unit.player === 1
              ? this.getCSSColor("--hp-bar-player1")
              : this.getCSSColor("--hp-bar-player2")
            : parseColor(hpDamagedColor || "#666666");
        slice.beginFill(color, 1);
        slice.drawRoundedRect(
          finalBarX + i * sliceWidth + 1,
          finalBarY + 1,
          sliceWidth - 2,
          finalBarHeight - 2,
          2
        );
        slice.endFill();
        slice.zIndex = 350;
        app.stage.addChild(slice);
      }
    }
  }

  private renderShootingCounter(unitIconScale: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      phase,
      current_player,
      HEX_RADIUS,
      unitsFled,
      isEligible,
    } = this.props;

    if (phase !== "shoot" || unit.player !== current_player) return;

    // NEW RULE: Hide shooting counter for units that fled
    if (unitsFled?.includes(unit.id)) {
      return;
    }

    // Show counter only for eligible units with shots remaining
    if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT <= 0) return;
    if (!isEligible) return;

    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get from selected weapon (imported at top)
    const selectedRngWeapon = getSelectedRangedWeapon(unit);
    if (!selectedRngWeapon) {
      throw new Error(`Missing RNG weapon for unit ${unit.id}`);
    }
    if (selectedRngWeapon.NB === undefined) {
      throw new Error(`Missing RNG weapon NB for unit ${unit.id}`);
    }
    if (unit.SHOOT_LEFT === undefined && typeof selectedRngWeapon.NB !== "number") {
      throw new Error(`Missing SHOOT_LEFT for dice-based RNG weapon on unit ${unit.id}`);
    }
    const totalShotsValue = getDiceAverage(selectedRngWeapon.NB);
    const totalShotsLabel =
      typeof selectedRngWeapon.NB === "number" ? `${selectedRngWeapon.NB}` : selectedRngWeapon.NB;
    const shotsLeft = Number(unit.SHOOT_LEFT !== undefined ? unit.SHOOT_LEFT : totalShotsValue);
    if (Number.isNaN(shotsLeft)) {
      throw new Error(`Invalid SHOOT_LEFT for unit ${unit.id}`);
    }
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);

    const shootText = new PIXI.Text(`${shotsLeft}/${totalShotsLabel}`, {
      fontSize: 14,
      fill: shotsLeft > 0 ? 0xffff00 : 0x666666,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 2,
    });
    shootText.anchor.set(0.1);
    shootText.position.set(centerX + scaledOffset, centerY - scaledOffset * 1.1);
    // Ensure shooting counter is always on top of other elements
    shootText.zIndex = 10000;
    app.stage.addChild(shootText);
  }

  private renderAdvanceButton(unitIconScale: number, iconZIndex: number): void {
    const {
      unit,
      phase,
      current_player,
      app,
      centerX,
      centerY,
      HEX_RADIUS,
      canAdvance,
      onAdvance,
      gameState,
    } = this.props;

    if (this.props.useOverlayIcons) {
      return;
    }

    // Show only during shoot phase for active unit of current player
    if (phase !== "shoot") return;
    if (unit.player !== current_player) return;
    if (canAdvance === false) return;

    // Only show icon when unit is actively activated (backend source of truth)
    const isActiveShooting =
      gameState?.active_shooting_unit && parseInt(gameState.active_shooting_unit, 10) === unit.id;
    if (!isActiveShooting) return;

    // Position: above HP bar (same calculation as renderHPBar)
    const scaledYOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);
    const HP_BAR_HEIGHT = this.props.HP_BAR_HEIGHT;
    const barY = centerY - scaledYOffset - HP_BAR_HEIGHT;
    const squareSizeRatio = this.getCSSNumber("--icon-square-standard-size", 0.5);
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const positionX = centerX;
    const positionY = barY - squareSize / 2 - 5; // 5px spacing above HP bar

    // Get values from CSS variables for icon size
    const iconSize = this.getCSSNumber("--icon-advance-size", 1.5);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);

    // Load and create icon sprite (same pattern as renderActionIconInSquare, but without background square)
    const texture = PIXI.Texture.from("/icons/Action_Logo/3-5 - Advance.png");
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001;
    iconSprite.eventMode = "static";
    iconSprite.cursor = "pointer";

    iconSprite.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
      if (e.button === 0 && onAdvance) {
        e.stopPropagation();
        onAdvance(typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10));
      }
    });

    app.stage.addChild(iconSprite);
  }

  private renderWeaponSelectionIcon(unitIconScale: number, iconZIndex: number): void {
    const { unit, phase, current_player, app, centerX, centerY, HEX_RADIUS, gameState } =
      this.props;

    if (this.props.useOverlayIcons) {
      return;
    }

    // AI_TURN.md ligne 694: Human only: Display weapon selection icon (if CAN_SHOOT)
    // Show only during shoot phase for active unit with multiple weapons
    if (phase !== "shoot") {
      return;
    }
    if (unit.player !== current_player) {
      return;
    }

    // Check if unit is active shooting unit (backend sets this when unit has valid targets)
    if (
      !gameState?.active_shooting_unit ||
      parseInt(gameState.active_shooting_unit, 10) !== unit.id
    ) {
      return;
    }

    // AI_TURN.md: Check if unit can actually shoot (CAN_SHOOT = true)
    // If empty_target_pool is true, CAN_SHOOT = false, so don't show weapon icon
    interface UnitWithAvailableWeapons extends Unit {
      available_weapons?: Array<{ can_use: boolean }>;
    }
    const unitWithWeapons = unit as UnitWithAvailableWeapons;
    const availableWeapons = unitWithWeapons.available_weapons;

    // CRITICAL: Only show icon if unit has usable weapons (CAN_SHOOT = true)
    // If available_weapons is undefined or empty, unit cannot shoot
    if (!availableWeapons || availableWeapons.length === 0) return;

    const usableWeapons = availableWeapons.filter((w) => w.can_use);

    // AI_TURN.md ligne 1121: Display weapon selection icon (only if unit.CAN_SHOOT = true)
    // CAN_SHOOT = true if usableWeapons.length > 0 (at least one weapon can be used)
    // Note: Icon should be displayed if CAN_SHOOT = true, even with a single weapon
    // The icon allows manual weapon selection even if only one weapon is available
    if (usableWeapons.length === 0) return;

    // Display for human players (autoSelectWeapon can be used to control auto-selection,
    // but icon should always be shown for human players when CAN_SHOOT and multiple weapons available)
    // If autoSelectWeapon is explicitly false, show icon; if undefined or true, still show for manual selection option
    // Note: The icon allows manual weapon selection even if auto-selection is enabled

    // Position: to the right of Advance icon (same Y position as Advance)
    const scaledYOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);
    const HP_BAR_HEIGHT = this.props.HP_BAR_HEIGHT;
    const barY = centerY - scaledYOffset - HP_BAR_HEIGHT;
    const squareSizeRatio = this.getCSSNumber("--icon-square-standard-size", 0.5);
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const positionY = barY - squareSize / 2 - 5; // Same Y as Advance icon

    // Position X: to the right of Advance icon (centerX + spacing)
    const iconSize = this.getCSSNumber("--icon-advance-size", 1.5);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    const spacing = iconDisplaySize * 1.2; // Spacing between icons
    const positionX = centerX + spacing; // To the right of Advance icon

    // Load pistol icon
    const texture = PIXI.Texture.from("/icons/Action_Logo/3-1 - Gun_Choice.png");
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);

    iconSprite.position.set(positionX, positionY);
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001;
    iconSprite.eventMode = "static";
    iconSprite.cursor = "pointer";

    iconSprite.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
      if (e.button === 0) {
        e.stopPropagation();
        window.dispatchEvent(
          new CustomEvent("boardWeaponSelectionClick", {
            detail: {
              unitId: typeof unit.id === "number" ? unit.id : parseInt(unit.id as string, 10),
            },
          })
        );
      }
    });

    app.stage.addChild(iconSprite);
  }

  private renderAttackCounter(unitIconScale: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      phase,
      current_player,
      HEX_RADIUS,
      unitsFled,
      units,
      mode,
      selectedUnitId,
      fightSubPhase,
      isEligible,
    } = this.props;

    // Attack counter shows for actively fighting units in fight phase
    if (phase !== "fight") return;

    // AI_TURN.md Lines 768, 777: ATTACK_LEFT visible during fight activation
    // Show counter for: (1) actively attacking unit (selectedUnitId in attackPreview)
    // OR (2) eligible units in their pool waiting to be activated
    const isActivelyAttacking = mode === "attackPreview" && selectedUnitId === unit.id;

    if (!isActivelyAttacking) {
      // Not actively attacking - check if eligible in current subphase pool
      let shouldShowIfEligible = false;

      // In replay mode (no fightSubPhase), allow counter for any eligible unit
      if (!fightSubPhase) {
        shouldShowIfEligible = true;
      } else if (fightSubPhase === "charging") {
        shouldShowIfEligible = unit.player === current_player;
      } else if (
        fightSubPhase === "alternating_non_active" ||
        fightSubPhase === "cleanup_non_active"
      ) {
        shouldShowIfEligible = unit.player !== current_player;
      } else if (fightSubPhase === "alternating_active" || fightSubPhase === "cleanup_active") {
        shouldShowIfEligible = unit.player === current_player;
      }

      if (!shouldShowIfEligible || !isEligible) return;
      if (unit.ATTACK_LEFT === undefined || unit.ATTACK_LEFT <= 0) {
        return;
      }
    }

    // NEW: Only show attack counter for units that have enemies in melee range
    const enemies = units.filter((u) => u.player !== unit.player);
    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use getMeleeRange() (always 1, imported at top)
    const fightRange = getMeleeRange();
    const hasEnemiesInMeleeRange = enemies.some((enemy) => {
      const cube1 = offsetToCube(unit.col, unit.row);
      const cube2 = offsetToCube(enemy.col, enemy.row);
      const distance = cubeDistance(cube1, cube2);
      return distance <= fightRange;
    });

    if (!hasEnemiesInMeleeRange) return;

    // NEW RULE: Hide attack counter for units that fled
    if (unitsFled?.includes(unit.id)) {
      return;
    }

    // MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get from selected weapon (imported at top)
    const selectedCcWeapon = getSelectedMeleeWeapon(unit);
    if (!selectedCcWeapon) {
      throw new Error(`Missing CC weapon for unit ${unit.id}`);
    }
    if (selectedCcWeapon.NB === undefined) {
      throw new Error(`Missing CC weapon NB for unit ${unit.id}`);
    }
    if (unit.ATTACK_LEFT === undefined && typeof selectedCcWeapon.NB !== "number") {
      throw new Error(`Missing ATTACK_LEFT for dice-based CC weapon on unit ${unit.id}`);
    }
    const totalAttacksValue = getDiceAverage(selectedCcWeapon.NB);
    const totalAttacksLabel =
      typeof selectedCcWeapon.NB === "number" ? `${selectedCcWeapon.NB}` : selectedCcWeapon.NB;
    const attacksLeft = Number(
      unit.ATTACK_LEFT !== undefined ? unit.ATTACK_LEFT : totalAttacksValue
    );
    if (Number.isNaN(attacksLeft)) {
      throw new Error(`Invalid ATTACK_LEFT for unit ${unit.id}`);
    }
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * (0.9 + 0.3 / unitIconScale);

    const attackText = new PIXI.Text(`${attacksLeft}/${totalAttacksLabel}`, {
      fontSize: 14,
      fill: attacksLeft > 0 ? 0xffff00 : 0x666666,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 2,
    });
    attackText.anchor.set(0.1);
    attackText.position.set(centerX + scaledOffset, centerY - scaledOffset * 1.1);
    // Ensure attack counter is always on top of other elements
    attackText.zIndex = 10000;
    app.stage.addChild(attackText);
  }

  private renderChargeRollBadge(unitIconScale: number): void {
    const {
      unit,
      chargingUnitId,
      chargeRoll,
      chargeSuccess,
      centerX,
      centerY,
      app,
      HEX_RADIUS,
      uiElementsContainer,
    } = this.props;

    // Use persistent UI container if provided, otherwise fall back to stage
    const targetContainer = uiElementsContainer || app.stage;

    // Show charge roll badge ONLY on the unit that is charging or failed charging
    // CRITICAL: Only show badge if this is the charging unit (identified by chargingUnitId)
    if (!chargingUnitId || unit.id !== chargingUnitId) {
      return; // Not the charging unit, don't show badge
    }

    // Must have a charge roll value to display
    if (chargeRoll === undefined || chargeRoll === null) return;

    // Clean up any existing charge badge for this unit from the container
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
    if (uiElementsContainer) {
      const existingElements = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) => child.name === `charge-badge-${unitIdNum}`
      );
      existingElements.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    // Calculate badge position (bottom-right of unit)
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * 0.8;
    const badgeX = centerX + scaledOffset;
    const badgeY = centerY + scaledOffset;

    // Badge colors based on success/failure
    // Success: light green text (#90EE90) on dark green background (#006400)
    // Failure: light red text (#FF6B6B) on dark red background (#8B0000)
    const textColor = chargeSuccess ? 0x90ee90 : 0xff6b6b;
    const bgColor = chargeSuccess ? 0x006400 : 0x8b0000;

    // Create badge background (rounded rectangle)
    const badgeWidth = 28;
    const badgeHeight = 20;
    const badgeBg = new PIXI.Graphics();
    badgeBg.beginFill(bgColor, 0.95);
    badgeBg.lineStyle(2, chargeSuccess ? 0x00aa00 : 0xaa0000, 1);
    badgeBg.drawRoundedRect(
      badgeX - badgeWidth / 2,
      badgeY - badgeHeight / 2,
      badgeWidth,
      badgeHeight,
      4
    );
    badgeBg.endFill();
    badgeBg.name = `charge-badge-${unitIdNum}-bg`;
    badgeBg.zIndex = 10001; // Above everything
    targetContainer.addChild(badgeBg);

    // Create roll number text
    const rollText = new PIXI.Text(`${chargeRoll}`, {
      fontSize: 14,
      fill: textColor,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 1,
    });
    rollText.anchor.set(0.5);
    rollText.position.set(badgeX, badgeY);
    rollText.name = `charge-badge-${unitIdNum}-text`;
    rollText.zIndex = 10002; // Above badge background and everything else
    targetContainer.addChild(rollText);
  }

  private renderUnitIdDebug(iconZIndex: number): void {
    const { unit, centerX, centerY, app, HEX_RADIUS, debugMode } = this.props;

    if (!debugMode) {
      return;
    }

    // Create square background at center of icon
    const squareSize = HEX_RADIUS * 0.7; // Larger square for better visibility
    const squareBg = new PIXI.Graphics();
    squareBg.beginFill(0x000000, 0.65); // Black background with transparency
    squareBg.lineStyle(0, 0xffffff, 1.0); // No border
    squareBg.drawRoundedRect(
      centerX - squareSize / 2,
      centerY - squareSize / 2,
      squareSize,
      squareSize,
      6
    );
    squareBg.endFill();
    squareBg.zIndex = iconZIndex + 2000; // Very high z-index to be on top of everything
    app.stage.addChild(squareBg);

    // Create text with unit ID
    const unitIdText = new PIXI.Text(String(unit.id), {
      fontSize: squareSize * 0.7,
      align: "center",
      fill: 0xffffff,
      fontWeight: "bold",
    });
    unitIdText.anchor.set(0.5);
    unitIdText.position.set(centerX, centerY);
    unitIdText.zIndex = iconZIndex + 2001; // Very high z-index to be on top of everything
    app.stage.addChild(unitIdText);
  }

  private renderAdvanceRollBadge(unitIconScale: number): void {
    const {
      unit,
      advancingUnitId,
      advanceRoll,
      centerX,
      centerY,
      app,
      HEX_RADIUS,
      uiElementsContainer,
    } = this.props;

    // Use persistent UI container if provided, otherwise fall back to stage
    const targetContainer = uiElementsContainer || app.stage;

    // Show advance roll badge ONLY on the unit that is advancing
    if (!advancingUnitId || unit.id !== advancingUnitId) {
      return; // Not the advancing unit, don't show badge
    }

    // Must have an advance roll value to display
    if (advanceRoll === undefined || advanceRoll === null) return;

    // Clean up any existing advance badge for this unit from the container
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
    if (uiElementsContainer) {
      const existingElements = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) => child.name === `advance-badge-${unitIdNum}`
      );
      existingElements.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    // Calculate badge position (bottom-right of unit) - same as charge roll badge
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * 0.8;
    const badgeX = centerX + scaledOffset;
    const badgeY = centerY + scaledOffset;

    // Badge colors - same as charge roll success (green theme)
    // Success: light green text (#90EE90) on dark green background (#006400)
    const textColor = 0x90ee90;
    const bgColor = 0x006400;

    // Create badge background (rounded rectangle)
    const badgeWidth = 28;
    const badgeHeight = 20;
    const badgeBg = new PIXI.Graphics();
    badgeBg.beginFill(bgColor, 0.95);
    badgeBg.lineStyle(2, 0x00aa00, 1);
    badgeBg.drawRoundedRect(
      badgeX - badgeWidth / 2,
      badgeY - badgeHeight / 2,
      badgeWidth,
      badgeHeight,
      4
    );
    badgeBg.endFill();
    badgeBg.name = `advance-badge-${unitIdNum}-bg`;
    badgeBg.zIndex = 10001; // Above everything
    targetContainer.addChild(badgeBg);

    // Create roll number text
    const rollText = new PIXI.Text(`${advanceRoll}`, {
      fontSize: 14,
      fill: textColor,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 1,
    });
    rollText.anchor.set(0.5);
    rollText.position.set(badgeX, badgeY);
    rollText.name = `advance-badge-${unitIdNum}-text`;
    rollText.zIndex = 10002; // Above badge background and everything else
    targetContainer.addChild(rollText);
  }
}

// Helper function to create and render a unit
export function renderUnit(props: UnitRendererProps): void {
  const renderer = new UnitRenderer(props);
  renderer.render();
}
