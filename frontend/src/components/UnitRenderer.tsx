// frontend/src/components/UnitRenderer.tsx
import * as PIXI from "pixi.js-legacy";
import type { Unit, TargetPreview, FightSubPhase, PlayerId } from "../types/game";
import { areUnitsAdjacent, offsetToCube, cubeDistance } from '../utils/gameHelpers';

interface UnitRendererProps {
  unit: Unit;
  centerX: number;
  centerY: number;
  app: PIXI.Application;
  isPreview?: boolean;
  previewType?: 'move' | 'attack';
  isEligible?: boolean; // Add eligibility as a prop instead of calculating it
  isShootable?: boolean; // Add shootability based on LoS validation

  // Blinking state for multi-unit HP bars
  blinkingUnits?: number[];
  isBlinkingActive?: boolean;
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

  // Board configuration
  boardConfig: any;
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
  currentPlayer: 0 | 1;
  selectedUnitId: number | null;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  fightSubPhase?: FightSubPhase; // NEW
  fightActivePlayer?: PlayerId; // NEW
  gameState?: any; // Add gameState property for active_shooting_unit access
  units: Unit[];
  chargeTargets: Unit[];
  fightTargets: Unit[];
  targetPreview?: TargetPreview | null;
  
  // Callbacks
  onConfirmMove?: () => void;
  parseColor: (colorStr: string) => number;
}

export class UnitRenderer {
  private props: UnitRendererProps;
  
  constructor(props: UnitRendererProps) {
    this.props = props;
  }
  
  private getCSSColor(variableName: string): number {
    const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
    if (value && value !== '') {
      // Convert hex string like "#4da6ff" to number like 0x4da6ff
      return parseInt(value.replace('#', ''), 16);
    }
    throw new Error(`CSS variable ${variableName} not found or empty`);
  }

  private getCSSNumber(variableName: string, fallback: number): number {
    const value = getComputedStyle(document.documentElement).getPropertyValue(variableName).trim();
    if (value && value !== '') {
      return parseFloat(value);
    }
    return fallback;
  }
  
  private cleanupExistingBlinkIntervals(): void {
    // Find any existing blink containers and clean them up
    const existingBlinkContainers = this.props.app.stage.children.filter(
      child => child.name === 'hp-blink-container'
    );
    
    existingBlinkContainers.forEach((container) => {
      // Only cleanup OLD containers that belong to current unit (prevent duplicates)
      if ((container as any).unitId && (container as any).unitId === this.props.unit.id) {
        if ((container as any).cleanupBlink) {
          (container as any).cleanupBlink();
        }
        container.destroy({ children: true });
      }
    });
  }
  
  render(): void {
    // Clean up any existing blink intervals before rendering new ones
    this.cleanupExistingBlinkIntervals();

    const { unit } = this.props;

    // AI_TURN.md COMPLIANCE: Dead units don't render - UNLESS just killed (show as grey ghost)
    // Just-killed units are shown in grey, then removed in the next action
    const isJustKilled = (unit as any).isJustKilled === true;
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
    const iconZIndex = minZIndex + Math.round((maxIconScale - unitIconScale) / scaleRange * unitZIndexRange);
    
    // ===== AI_TURN.md COMPLIANT ELIGIBILITY =====
    const isEligible = this.calculateEligibilityCompliant();
    
    // ===== RENDER COMPONENTS =====
    this.renderUnitCircle(iconZIndex);
    this.renderUnitIcon(iconZIndex);
    this.renderGreenActivationCircle(isEligible, unitIconScale);
    this.renderHPBar(unitIconScale);
    this.renderShootingCounter(unitIconScale);
    this.renderTargetIndicator(iconZIndex); // Shows 🎯 for all targets (shoot, charge, fight)
    this.renderShootingIndicator(iconZIndex);
    this.renderMovementIndicator(iconZIndex);
    this.renderChargeIndicator(iconZIndex);
    this.renderFightIndicator(iconZIndex);
    this.renderAttackCounter(unitIconScale);
    this.renderChargeRollBadge(unitIconScale, iconZIndex);
  }
  
  private calculateEligibilityCompliant(): boolean {
    const { unit, phase, currentPlayer, unitsMoved, unitsCharged, unitsAttacked, unitsFled } = this.props;

    // AI_TURN.md: Basic eligibility checks
    // Allow just-killed units to be rendered as grey ghosts
    const isJustKilled = (unit as any).isJustKilled === true;
    if (unit.HP_CUR === undefined || (unit.HP_CUR <= 0 && !isJustKilled)) return false;
    if (phase !== "fight" && unit.player !== currentPlayer) return false;
    
    switch (phase) {
      case "move":
        return !unitsMoved.includes(unit.id);
      case "shoot":
        // AI_TURN.md: Queue-based eligibility during active shooting phase
        // Type-safe checks with proper fallbacks
        if (unitsFled && unitsFled.includes(unit.id)) return false;
        if (unit.RNG_NB === undefined || unit.RNG_NB <= 0) return false;
        // Simplified check - parent should provide queue membership
        return this.props.isEligible || false;
      case "charge":
        // AI_TURN.md: Charge phase uses pool-based eligibility (charge_activation_pool)
        // Parent provides proper eligibility through isEligible prop
        // Lines 493-496: Must have enemies within charge_max_distance AND not already adjacent
        return this.props.isEligible || false;
      case "fight":
        // AI_TURN.md: Fight phase uses pool-based eligibility (sub-phases)
        // Parent provides proper eligibility through isEligible prop
        return this.props.isEligible || false;
      default:
        return false;
    }
  }
  
  private renderUnitCircle(iconZIndex: number): void {
    const { unit, centerX, centerY, app, isPreview, selectedUnitId, unitsMoved, unitsCharged, unitsAttacked,
             chargeTargets, fightTargets, boardConfig, HEX_RADIUS, UNIT_CIRCLE_RADIUS_RATIO,
             SELECTED_BORDER_WIDTH, CHARGE_TARGET_BORDER_WIDTH, DEFAULT_BORDER_WIDTH,
             phase, mode, currentPlayer, units, parseColor } = this.props;
    
    if (isPreview) return;
    
    // Grey-out enemies adjacent to any friendly unit during shooting phase
    // Also grey-out enemies with no line of sight
    if (phase === "shoot" && unit.player !== currentPlayer) {
      const friendlies = units.filter(u2 => u2.player === currentPlayer);
      if (friendlies.some(fu => areUnitsAdjacent(unit, fu))) {
        const grey = 0x888888;
        const g = new PIXI.Graphics();
        g.beginFill(grey);
        g.lineStyle(DEFAULT_BORDER_WIDTH, grey);
        g.drawCircle(centerX, centerY, HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO);
        g.endFill();
        g.zIndex = iconZIndex;
        g.eventMode = 'none';
        app.stage.addChild(g);
        return;
      }
    }
    
    let unitColor = unit.color;
    let borderColor = 0xffffff;
    let borderWidth = DEFAULT_BORDER_WIDTH;
    
    // Handle selection and used unit states
    if (selectedUnitId === unit.id) {
      borderColor = parseColor(boardConfig.colors.current_unit);
      borderWidth = SELECTED_BORDER_WIDTH;
    } else if (unitsMoved.includes(unit.id) || unitsCharged?.includes(unit.id) || unitsAttacked?.includes(unit.id)) {
      unitColor = 0x666666;
    }
    
    // Handle red outline for targets
    if (chargeTargets.some(target => target.id === unit.id)) {
      borderColor = 0xff0000;
      borderWidth = CHARGE_TARGET_BORDER_WIDTH;
    } else if (fightTargets.some(target => target.id === unit.id)) {
      borderColor = 0xff0000;
      borderWidth = CHARGE_TARGET_BORDER_WIDTH;
    }
    
    const unitCircle = new PIXI.Graphics();

    // Ghost unit styling (for replay move visualization)
    let finalUnitColor = unitColor;
    let finalBorderColor = borderColor;
    let circleAlpha = 1.0;
    if ((unit as any).isGhost) {
      finalUnitColor = 0x666666;  // Medium grey fill
      finalBorderColor = 0x888888; // Lighter grey border
      circleAlpha = 0.6;
    }

    // Just-killed unit styling (show as grey ghost before removal)
    if ((unit as any).isJustKilled) {
      finalUnitColor = 0x444444;  // Dark grey fill
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
    unitCircle.eventMode = 'static';
    unitCircle.cursor = "pointer";
    // Always add click handlers so we can detect clicks on all units
    
    if (phase === "charge" && selectedUnitId === unit.id) {
      // Cancel charge on second click of active unit
      unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
        if (e.button === 0) {
          window.dispatchEvent(new CustomEvent('boardCancelCharge'));
        }
      });
    } else {
      // AI_TURN.md: Block enemy unit clicks when no friendly unit is selected
      let addClickHandler = true;

      // AI_TURN.md: Fight phase exception - allow clicking units in ALL fight subphases
      // Lines 738, 765, 820, 847: "player activate one unit by left clicking on it"
      const isFightPhaseActive = phase === "fight" && (
        this.props.fightSubPhase === "charging" ||
        this.props.fightSubPhase === "alternating_non_active" ||
        this.props.fightSubPhase === "alternating_active" ||
        this.props.fightSubPhase === "cleanup_non_active" ||
        this.props.fightSubPhase === "cleanup_active"
      );

      // Block enemy clicks when no unit is selected (prevents stuck preview)
      // EXCEPT during fight phase where eligible units must be clickable
      if (unit.player !== currentPlayer && selectedUnitId === null && !isFightPhaseActive) {
        addClickHandler = false;
      }
      
      if (phase === "shoot" && mode === "attackPreview" && unit.player !== currentPlayer && selectedUnitId !== null) {
        const selectedUnit = units.find(u => u.id === selectedUnitId);
        if (selectedUnit && !this.props.isShootable) {
          addClickHandler = false;
        }
      }
      if (addClickHandler) {
        // Check if unit is shootable during shooting phase
        const isShootableUnit = this.props.isShootable !== false;
        
        if (phase === "shoot" && unit.player !== currentPlayer && !isShootableUnit) {
          // Unit is blocked by LoS - no click handler, no hand cursor
          unitCircle.eventMode = 'none';
          unitCircle.cursor = "default";
        } else {
          unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
          if (e.button === 0 || e.button === 2) { // Left or right click
            // Prevent context menu and event bubbling
            e.preventDefault();
            e.stopPropagation();
            
            if (e.button === 2 && phase === "shoot" && mode === "attackPreview" && selectedUnitId === unit.id) {
              // AI_TURN.md: Right click behavior depends on SHOOT_LEFT
              const shootLeft = unit.SHOOT_LEFT || 0;
              const rngNb = unit.RNG_NB || 0;
              
              if (shootLeft === rngNb) {
                // SHOOT_LEFT = RNG_NB: Cancel activation (WAIT)
                window.dispatchEvent(new CustomEvent('boardCancelShoot', {
                  detail: { unitId: unit.id, type: 'wait' }
                }));
              } else {
                // SHOOT_LEFT < RNG_NB: Stop shooting (ACTION)
                window.dispatchEvent(new CustomEvent('boardSkipShoot', {
                  detail: { unitId: unit.id, type: 'action' }
                }));
              }
              return;
            }
            
            window.dispatchEvent(new CustomEvent('boardUnitClick', {
              detail: {
                unitId: unit.id,
                phase: phase,
                mode: mode,
                selectedUnitId: selectedUnitId,
                clickType: e.button === 0 ? 'left' : 'right'
              }
            }));
          }
        });
        }
      } else {
        unitCircle.eventMode = 'none';
        unitCircle.cursor = "default";
      }
    }
    
    app.stage.addChild(unitCircle);
  }
  
  private renderUnitIcon(iconZIndex: number): void {
    const { unit, centerX, centerY, app, isPreview, previewType, HEX_RADIUS,
             ICON_SCALE, phase, currentPlayer, units, onConfirmMove } = this.props;
    
    const unitIconScale = unit.ICON_SCALE || ICON_SCALE;
    
    if (unit.ICON) {
      try {
        // Use red border icon for Player 2 units
        const iconPath = unit.player === 1 ? unit.ICON.replace('.webp', '_red.webp') : unit.ICON;
        
        // Get or create texture (PIXI.Texture.from uses cache if available)
        // This ensures textures are reused from cache, preventing black flashing
        let texture = PIXI.Texture.from(iconPath, isPreview ? { resourceOptions: { crossorigin: 'anonymous' } } : undefined);
        
        const sprite = new PIXI.Sprite(texture);
        sprite.anchor.set(0.5);
        sprite.position.set(centerX, centerY);
        sprite.width = HEX_RADIUS * unitIconScale;
        sprite.height = HEX_RADIUS * unitIconScale;
        sprite.zIndex = iconZIndex;
        sprite.alpha = 1.0; // Always fully opaque

        // Ghost unit rendering (for replay move visualization)
        if ((unit as any).isGhost) {
          sprite.alpha = 0.5;
          sprite.tint = 0x666666;
        }

        // Just-killed unit rendering (show as dark grey before removal)
        if ((unit as any).isJustKilled) {
          sprite.alpha = 0.4;
          sprite.tint = 0x444444;
        }

        // Ghost unit rendering (for replay move visualization)
        if ((unit as any).isGhost) {
          sprite.tint = 0x666666;
        }

        // Just-killed unit rendering (show as dark grey before removal)
        if ((unit as any).isJustKilled) {
          sprite.tint = 0x444444;
        }

        // Preview-specific properties
        if (isPreview) {
          if (previewType === 'move') {
            sprite.eventMode = 'static';
            sprite.cursor = "pointer";
            sprite.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
              if (e.button === 0) onConfirmMove?.();
            });
          }
          if (previewType === 'attack') {
            sprite.alpha = 0.8;
          }
        }
        // Grey-out enemies adjacent to any friendly unit during shooting phase
        if (!isPreview && phase === "shoot" && unit.player !== currentPlayer) {
          const friendlies = units.filter(u2 => u2.player === currentPlayer);
          if (friendlies.some(fu => areUnitsAdjacent(unit, fu))) {
            sprite.alpha = 0.5;
            sprite.tint  = 0x888888;
          }
        }
         
         app.stage.addChild(sprite);

      } catch (iconError) {
        this.renderTextFallback(iconZIndex);
      }
    } else {
      this.renderTextFallback(iconZIndex);
    }
  }
  
  private renderTextFallback(iconZIndex: number): void {
    const { unit, centerX, centerY, app } = this.props;

    // Ghost unit styling
    let textColor = 0xffffff;
    let textAlpha = 1.0;
    if ((unit as any).isGhost) {
      textColor = 0x999999;
      textAlpha = 0.7;
    }

    // Just-killed unit styling
    if ((unit as any).isJustKilled) {
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
    
    const { centerX, centerY, app, HEX_RADIUS, ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA } = this.props;
    
    const eligibleOutline = new PIXI.Graphics();
    const circleRadius = (HEX_RADIUS * unitIconScale) / 2 * 1.1;
    eligibleOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA);
    eligibleOutline.drawCircle(centerX, centerY, circleRadius);
    
    // Use same z-index calculation as icons to ensure proper layering
    const unitZIndexRange = 149;
    const minIconScale = 0.5;
    const maxIconScale = 2.5;
    const minZIndex = 100;
    const scaleRange = maxIconScale - minIconScale;
    const iconZIndex = minZIndex + Math.round((maxIconScale - unitIconScale) / scaleRange * unitZIndexRange);
    const greenCircleZIndex = iconZIndex + 50; // Always above the unit icon
    
    eligibleOutline.zIndex = greenCircleZIndex;
    app.stage.addChild(eligibleOutline);
    
    // NEW: Add red circle around green circle for charged units in fight phase
    const { unit, phase, fightSubPhase } = this.props;
    if (phase === "fight" && fightSubPhase === "charged_units" && unit.hasChargedThisTurn && isEligible) {
      const chargedOutline = new PIXI.Graphics();
      const outerCircleRadius = circleRadius + ELIGIBLE_OUTLINE_WIDTH + 2; // Slightly larger than green circle
      chargedOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, 0xff0000, ELIGIBLE_OUTLINE_ALPHA); // Red color
      chargedOutline.drawCircle(centerX, centerY, outerCircleRadius);
      chargedOutline.zIndex = 251; // Above green circle
      app.stage.addChild(chargedOutline);
    }
  }

  private renderTargetIndicator(iconZIndex: number): void {
    const { unit, shootingTargetId, chargeTargetId, fightTargetId, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Show target indicator (🎯) on units that are targets of any action
    const isTarget = (shootingTargetId && unit.id === shootingTargetId) ||
                    (chargeTargetId && unit.id === chargeTargetId) ||
                    (fightTargetId && unit.id === fightTargetId);
    
    if (!isTarget) return;

    const iconSize = this.getCSSNumber('--icon-target-size', 1.6);
    const squareSizeRatio = this.getCSSNumber('--icon-target-square-size', 0.5);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Get values from CSS variables
    const bgColor = this.getCSSColor('--icon-target-bg-color');
    const whiteBorderColor = this.getCSSColor('--icon-square-border-color');
    const bgAlpha = this.getCSSNumber('--icon-square-bg-alpha', 1.0);
    const borderAlpha = this.getCSSNumber('--icon-square-border-alpha', 1.0);
    const borderWidth = this.getCSSNumber('--icon-square-border-width', 2);
    const borderRadius = this.getCSSNumber('--icon-square-border-radius', 4);
    const iconScale = this.getCSSNumber('--icon-square-icon-scale', 0.7);
    
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

    // Create target emoji text (🎯) - keep emoji for targets
    const iconText = new PIXI.Text('🎯', {
      fontSize: HEX_RADIUS * iconSize * iconScale,
      align: 'center',
      fill: 0xffffff,
    });
    iconText.anchor.set(0.5);
    iconText.position.set(positionX, positionY);
    iconText.zIndex = iconZIndex + 1001; // Very high z-index to be on top of everything
    app.stage.addChild(iconText);
  }

  private renderExplosionIcon(iconZIndex: number): void {
    // DEPRECATED: Replaced by renderTargetIndicator
    // Keep for backward compatibility but redirect to target indicator
    this.renderTargetIndicator(iconZIndex);
  }

  private renderActionIconInSquare(
    iconZIndex: number,
    iconPath: string, // Path to icon image file
    bgColorVar: string, // CSS variable name for background color
    borderColorVar: string, // CSS variable name for border color
    iconSizeVar: string, // CSS variable name for icon size
    squareSizeVar: string, // CSS variable name for square size ratio
    positionX: number,
    positionY: number
  ): void {
    const { app, HEX_RADIUS } = this.props;
    
    // Get values from CSS variables
    const bgColor = this.getCSSColor(bgColorVar);
    const whiteBorderColor = this.getCSSColor('--icon-square-border-color');
    const iconSize = this.getCSSNumber(iconSizeVar, 1.0);
    const squareSizeRatio = this.getCSSNumber(squareSizeVar, 0.5);
    const bgAlpha = this.getCSSNumber('--icon-square-bg-alpha', 1.0);
    const borderAlpha = this.getCSSNumber('--icon-square-border-alpha', 1.0);
    const borderWidth = this.getCSSNumber('--icon-square-border-width', 2);
    const borderRadius = this.getCSSNumber('--icon-square-border-radius', 4);
    const iconScale = this.getCSSNumber('--icon-square-icon-scale', 0.7);
    
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
    const whiteBorderColor = this.getCSSColor('--icon-square-border-color');
    const iconSize = this.getCSSNumber(iconSizeVar, 1.0);
    const circleSizeRatio = this.getCSSNumber(circleSizeVar, 0.5);
    const bgAlpha = this.getCSSNumber('--icon-square-bg-alpha', 1.0);
    const borderAlpha = this.getCSSNumber('--icon-square-border-alpha', 1.0);
    const borderWidth = this.getCSSNumber('--icon-square-border-width', 2);
    const iconScale = this.getCSSNumber('--icon-square-icon-scale', 0.7);
    
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
    const { unit, shootingUnitId, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Only show shooting indicator on the unit that is shooting
    if (!shootingUnitId || unit.id !== shootingUnitId) return;

    const iconSize = this.getCSSNumber('--icon-shoot-size', 1.2);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Yellow/Orange background for shooting (uses standard size)
    this.renderActionIconInSquare(
      iconZIndex,
      '/icons/Action_Logo/3 - Shooting.png',
      '--icon-shoot-bg-color',
      '--icon-shoot-color',
      '--icon-shoot-size',
      '--icon-square-standard-size', // Use standard size
      positionX,
      positionY
    );
  }

  private renderMovementIndicator(iconZIndex: number): void {
    const { unit, movingUnitId, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Only show movement indicator on the unit that is moving
    if (!movingUnitId || unit.id !== movingUnitId) return;

    const iconSize = this.getCSSNumber('--icon-move-size', 1.0);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Green circle for movement (uses standard size for consistency)
    this.renderActionIconInCircle(
      iconZIndex,
      '/icons/Action_Logo/2 - Movemement.png',
      '--icon-move-bg-color',
      '--icon-move-size',
      '--icon-square-standard-size', // Use standard size for consistency
      positionX,
      positionY
    );
  }

  private renderChargeIndicator(iconZIndex: number): void {
    const { unit, chargingUnitId, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Only show charge indicator on the unit that is charging
    if (!chargingUnitId || unit.id !== chargingUnitId) return;

    const iconSize = this.getCSSNumber('--icon-charge-size', 1.2);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Purple background for charge (uses standard size)
    this.renderActionIconInSquare(
      iconZIndex,
      '/icons/Action_Logo/4 - Charge.png',
      '--icon-charge-bg-color',
      '--icon-charge-color',
      '--icon-charge-size',
      '--icon-square-standard-size', // Use standard size
      positionX,
      positionY
    );
  }

  // DEPRECATED: renderChargeTargetIndicator - replaced by renderTargetIndicator
  // Charge targets now show 🎯 icon via renderTargetIndicator

  private renderFightIndicator(iconZIndex: number): void {
    const { unit, fightingUnitId, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Only show fight indicator on the unit that is fighting
    if (!fightingUnitId || unit.id !== fightingUnitId) return;

    const iconSize = this.getCSSNumber('--icon-fight-size', 1.2);
    const offset = HEX_RADIUS * 0.6;
    const positionX = centerX - offset;
    const positionY = centerY + offset;

    // Red background for combat/fight (uses larger size)
    this.renderActionIconInSquare(
      iconZIndex,
      '/icons/Action_Logo/5 - Fight.png',
      '--icon-fight-bg-color',
      '--icon-fight-color',
      '--icon-fight-size',
      '--icon-fight-square-size',
      positionX,
      positionY
    );
  }

  // DEPRECATED: renderFightTargetIndicator - replaced by renderTargetIndicator
  // Fight targets now show 🎯 icon via renderTargetIndicator

  private renderHPBar(unitIconScale: number): void {
    const { unit, centerX, centerY, app, targetPreview, units, boardConfig, parseColor, mode,
             HEX_RADIUS, HP_BAR_WIDTH_RATIO, HP_BAR_HEIGHT } = this.props;
    
    if (!unit.HP_MAX) return; // Only skip if no HP_MAX, not if isPreview
    
    const scaledYOffset = (HEX_RADIUS * unitIconScale) / 2 * (0.9 + 0.3 / unitIconScale);
    const HP_BAR_WIDTH = HEX_RADIUS * HP_BAR_WIDTH_RATIO;
    const barX = centerX - HP_BAR_WIDTH / 2;
    const barY = centerY - scaledYOffset - HP_BAR_HEIGHT;
    
    // Check if this unit is being previewed for shooting
    const isTargetPreviewed = (mode === "targetPreview" || mode === "attackPreview") && targetPreview && targetPreview.targetId === unit.id;
    
    // Check if this unit should be blinking (multi-unit blinking for valid targets)
    const shouldBlink = this.props.isBlinkingActive && this.props.blinkingUnits?.includes(unit.id);
    
    // Use either individual target preview OR multi-unit blinking
    const shouldShowBlinkingHP = isTargetPreviewed || shouldBlink;    
    const finalBarWidth = shouldShowBlinkingHP ? HP_BAR_WIDTH * 2.5 : HP_BAR_WIDTH;
    const finalBarHeight = shouldShowBlinkingHP ? HP_BAR_HEIGHT * 2.5 : HP_BAR_HEIGHT;
    const finalBarX = shouldShowBlinkingHP ? centerX - finalBarWidth / 2 : barX;
    const finalBarY = shouldShowBlinkingHP ? barY - (finalBarHeight - HP_BAR_HEIGHT) : barY;
    
    // Background
    const barBg = new PIXI.Graphics();
    barBg.beginFill(0x222222, 1);
    barBg.drawRoundedRect(finalBarX, finalBarY, finalBarWidth, finalBarHeight, 3);
    barBg.endFill();
    barBg.zIndex = 350;
    app.stage.addChild(barBg);
    
    // HP calculation with preview
    const currentHP = Math.max(0, unit.HP_CUR ?? unit.HP_MAX);
    let displayHP = currentHP;
    if (isTargetPreviewed && targetPreview) {
      const shooter = units.find(u => u.id === targetPreview.shooterId);
      if (shooter) {
        if (targetPreview.currentBlinkStep === 0) {
          displayHP = currentHP;
        } else {
          // ✅ FIX: Use CC_DMG for fight phase, RNG_DMG for shooting phase
          if (this.props.phase === 'fight') {
            if (shooter.CC_DMG === undefined) throw new Error(`shooter.CC_DMG is undefined for unit ${shooter.name || shooter.id}`);
            const totalDamage = targetPreview.currentBlinkStep * shooter.CC_DMG;
            displayHP = Math.max(0, currentHP - totalDamage);
          } else {
            if (shooter.RNG_DMG === undefined) throw new Error(`shooter.RNG_DMG is undefined for unit ${shooter.name || shooter.id}`);
            const totalDamage = targetPreview.currentBlinkStep * shooter.RNG_DMG;
            displayHP = Math.max(0, currentHP - totalDamage);
          }
        }
      }
    }
    
    // HP slices with blinking animation for target preview
    const sliceWidth = finalBarWidth / unit.HP_MAX;
    
    if (shouldShowBlinkingHP) {
      // Create blinking HP bar animation (works for both individual and multi-unit)
      const hpContainer = new PIXI.Container();
      hpContainer.name = 'hp-blink-container';
      hpContainer.zIndex = 350;
      (hpContainer as any).unitId = unit.id; // Tag container with unit ID
      
      // Create normal HP slices
      const normalSlices: PIXI.Graphics[] = [];
      const highlightSlices: PIXI.Graphics[] = [];
      
      for (let i = 0; i < unit.HP_MAX; i++) {
        // Normal HP slice
        const normalSlice = new PIXI.Graphics();
        const normalColor = i < currentHP ? (unit.player === 0 ? this.getCSSColor('--hp-bar-player0') : this.getCSSColor('--hp-bar-player1')) : this.getCSSColor('--hp-bar-lost');
        normalSlice.beginFill(normalColor, 1);
        normalSlice.drawRoundedRect(finalBarX + i * sliceWidth + 1, finalBarY + 1, sliceWidth - 2, finalBarHeight - 2, 2);
        normalSlice.endFill();
        normalSlice.zIndex = 360; // Above background
        normalSlices.push(normalSlice);
        hpContainer.addChild(normalSlice);
        
        // Highlight HP slice for damage preview
        const highlightSlice = new PIXI.Graphics();
        // Calculate damage for both targetPreview and multi-unit blinking
        let shooterDamage = 0;
        if (targetPreview) {
          const previewShooter = units.find(u => u.id === targetPreview.shooterId);
          shooterDamage = this.props.phase === 'fight' ? (previewShooter?.CC_DMG || 0) : (previewShooter?.RNG_DMG || 0);
        } else if (shouldBlink) {
          const activeShooterId = this.props.gameState?.active_shooting_unit || this.props.selectedUnitId;
          const activeShooter = this.props.units.find(u => u.id === activeShooterId);
          if (activeShooter) {
            shooterDamage = this.props.phase === 'fight' ? (activeShooter.CC_DMG || 0) : (activeShooter.RNG_DMG || 0);
          }
        }
        const wouldBeDamaged = i >= (currentHP - shooterDamage) && i < currentHP;
        const highlightColor = wouldBeDamaged ? this.getCSSColor('--hp-bar-damage-preview') : (i < currentHP ? (unit.player === 0 ? this.getCSSColor('--hp-bar-player0') : this.getCSSColor('--hp-bar-player1')) : this.getCSSColor('--hp-bar-lost'));
        highlightSlice.beginFill(highlightColor, 1);
        highlightSlice.drawRoundedRect(finalBarX + i * sliceWidth + 1, finalBarY + 1, sliceWidth - 2, finalBarHeight - 2, 2);
        highlightSlice.endFill();
        highlightSlice.visible = false; // Start hidden
        highlightSlice.zIndex = 360; // Above background
        highlightSlices.push(highlightSlice);
        hpContainer.addChild(highlightSlice);
      }
      
      // Create continuous blinking animation with PIXI render forcing
      let blinkState = false;
      const blinkTicker = () => {
        blinkState = !blinkState;
        normalSlices.forEach(slice => {
          slice.visible = !blinkState;
        });
        highlightSlices.forEach(slice => {
          slice.visible = blinkState;
        });
        // Force PIXI to re-render the stage with safety check
        if (app && app.renderer && app.renderer.type !== undefined) {
          try {
            app.renderer.render(app.stage);
          } catch (error) {
            console.warn('Renderer error during HP bar blink, clearing interval:', error);
          }
        }
      };
      
      // Start blinking immediately and set interval
      const blinkInterval = setInterval(blinkTicker, 500);
      
      // Store cleanup function with proper interval reference
      (hpContainer as any).cleanupBlink = () => {
        if (blinkInterval) {
          clearInterval(blinkInterval);
        }
      };
      (hpContainer as any).blinkInterval = blinkInterval;
      
      app.stage.addChild(hpContainer);
      
    } else {
      // Normal non-blinking HP slices
      for (let i = 0; i < unit.HP_MAX; i++) {
        const slice = new PIXI.Graphics();
        const color = i < displayHP ? (unit.player === 0 ? this.getCSSColor('--hp-bar-player0') : this.getCSSColor('--hp-bar-player1')) : parseColor(boardConfig.colors.hp_damaged);
        slice.beginFill(color, 1);
        slice.drawRoundedRect(finalBarX + i * sliceWidth + 1, finalBarY + 1, sliceWidth - 2, finalBarHeight - 2, 2);
        slice.endFill();
        slice.zIndex = 350;
        app.stage.addChild(slice);
      }
    }
    
    // Probability display for previewed targets (both individual and multi-unit)
    if ((isTargetPreviewed && targetPreview) || (shouldBlink && shouldShowBlinkingHP)) {
      let displayProbability = 0;
      
      if (isTargetPreviewed && targetPreview) {
        displayProbability = targetPreview.overallProbability || 0;
      } else if (shouldBlink) {
        // Calculate probability for multi-unit blinking
        const activeAttackerId = this.props.gameState?.active_shooting_unit || this.props.gameState?.active_fight_unit || this.props.selectedUnitId;
        const activeAttacker = this.props.units.find(u => u.id === activeAttackerId);

        if (activeAttacker && this.props.phase === "shoot") {
          const hitProb = Math.max(0, (7 - (activeAttacker.RNG_ATK || 4)) / 6);
          const strength = activeAttacker.RNG_STR || 4;
          const toughness = unit.T || 4;
          let woundTarget = 4;
          if (strength >= toughness * 2) woundTarget = 2;
          else if (strength > toughness) woundTarget = 3;
          else if (strength === toughness) woundTarget = 4;
          else if (strength < toughness) woundTarget = 5;
          else woundTarget = 6;
          const woundProb = Math.max(0, (7 - woundTarget) / 6);
          const saveTarget = Math.max(2, Math.min((unit.ARMOR_SAVE || 5) - (activeAttacker.RNG_AP || 0), unit.INVUL_SAVE || 7));
          const saveFailProb = Math.max(0, (saveTarget - 1) / 6);
          displayProbability = hitProb * woundProb * saveFailProb;
        } else if (activeAttacker && this.props.phase === "fight") {
          // AI_TURN.md: Fight phase uses CC_ stats instead of RNG_ stats
          const hitProb = Math.max(0, (7 - (activeAttacker.CC_ATK || 4)) / 6);
          const strength = activeAttacker.CC_STR || 4;
          const toughness = unit.T || 4;
          let woundTarget = 4;
          if (strength >= toughness * 2) woundTarget = 2;
          else if (strength > toughness) woundTarget = 3;
          else if (strength === toughness) woundTarget = 4;
          else if (strength < toughness) woundTarget = 5;
          else woundTarget = 6;
          const woundProb = Math.max(0, (7 - woundTarget) / 6);
          const saveTarget = Math.max(2, Math.min((unit.ARMOR_SAVE || 5) - (activeAttacker.CC_AP || 0), unit.INVUL_SAVE || 7));
          const saveFailProb = Math.max(0, (saveTarget - 1) / 6);
          displayProbability = hitProb * woundProb * saveFailProb;
        }
      }
      
      const squareSize = 35;
      const squareX = centerX - squareSize/2;
      const squareY = finalBarY - squareSize - 8;
      
      const probBg = new PIXI.Graphics();
      probBg.beginFill(0x333333, 0.9);
      probBg.lineStyle(2, 0x00ff00, 1);
      probBg.drawRoundedRect(squareX, squareY, squareSize, squareSize, 3);
      probBg.endFill();
      app.stage.addChild(probBg);
      
      const probText = new PIXI.Text(`${Math.round(displayProbability * 100)}%`, {
        fontSize: 12,
        fill: 0x00ff00,
        align: "center",
        fontWeight: "bold"
      });
      probText.anchor.set(0.5);
      probText.position.set(squareX + squareSize/2, squareY + squareSize/2);
      app.stage.addChild(probText);
    }
  }
  
  private renderShootingCounter(unitIconScale: number): void {
    const { unit, centerX, centerY, app, phase, currentPlayer, HEX_RADIUS, unitsFled, isEligible } = this.props;
    
    if (phase !== 'shoot' || unit.player !== currentPlayer) return;
    
    // NEW RULE: Hide shooting counter for units that fled
    if (unitsFled && unitsFled.includes(unit.id)) {
      return;
    }
    
    // AI_TURN.md: Show counter only for eligible units with shots remaining
    if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT <= 0) return;
    if (!isEligible) return;
    
    const shotsLeft = unit.SHOOT_LEFT !== undefined ? unit.SHOOT_LEFT : unit.RNG_NB || 0;
    const totalShots = unit.RNG_NB || 0;
    const scaledOffset = (HEX_RADIUS * unitIconScale) / 2 * (0.9 + 0.3 / unitIconScale);
    
    const shootText = new PIXI.Text(`${shotsLeft}/${totalShots}`, {
      fontSize: 14,
      fill: shotsLeft > 0 ? 0xffff00 : 0x666666,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 2
    });
    shootText.anchor.set(0.1);
    shootText.position.set(centerX + scaledOffset, centerY - scaledOffset * 1.1);
    shootText.zIndex = 450;
    app.stage.addChild(shootText);
  }
  
  private renderAttackCounter(unitIconScale: number): void {
    const { unit, centerX, centerY, app, phase, currentPlayer, HEX_RADIUS, unitsFled, units, mode, selectedUnitId, fightSubPhase, isEligible } = this.props;

    // AI_TURN.md: Attack counter shows for actively fighting units in fight phase
    if (phase !== 'fight') return;

    // AI_TURN.md Lines 768, 777: ATTACK_LEFT visible during fight activation
    // Show counter for: (1) actively attacking unit (selectedUnitId in attackPreview)
    // OR (2) eligible units in their pool waiting to be activated
    const isActivelyAttacking = mode === 'attackPreview' && selectedUnitId === unit.id;

    if (!isActivelyAttacking) {
      // Not actively attacking - check if eligible in current subphase pool
      let shouldShowIfEligible = false;

      if (fightSubPhase === "charging") {
        shouldShowIfEligible = unit.player === currentPlayer;
      } else if (fightSubPhase === "alternating_non_active" || fightSubPhase === "cleanup_non_active") {
        shouldShowIfEligible = unit.player !== currentPlayer;
      } else if (fightSubPhase === "alternating_active" || fightSubPhase === "cleanup_active") {
        shouldShowIfEligible = unit.player === currentPlayer;
      }

      if (!shouldShowIfEligible || !isEligible) return;
    }
    
    // NEW: Only show attack counter for units that have enemies in melee range
    const enemies = units.filter(u => u.player !== unit.player);
    const fightRange = unit.CC_RNG || 1;
    const hasEnemiesInMeleeRange = enemies.some(enemy => {
      const cube1 = offsetToCube(unit.col, unit.row);
      const cube2 = offsetToCube(enemy.col, enemy.row);
      const distance = cubeDistance(cube1, cube2);
      return distance <= fightRange;
    });
    
    if (!hasEnemiesInMeleeRange) return;
    
    // NEW RULE: Hide attack counter for units that fled
    if (unitsFled && unitsFled.includes(unit.id)) {
      return;
    }
    
    const attacksLeft = unit.ATTACK_LEFT !== undefined ? 
      unit.ATTACK_LEFT : unit.CC_NB || 0;
    const totalAttacks = unit.CC_NB || 0;
    const scaledOffset = (HEX_RADIUS * unitIconScale) / 2 * (0.9 + 0.3 / unitIconScale);
    
    const attackText = new PIXI.Text(`${attacksLeft}/${totalAttacks}`, {
      fontSize: 14,
      fill: attacksLeft > 0 ? 0xffff00 : 0x666666,
      align: "center",
      fontWeight: "bold",
      stroke: 0x000000,
      strokeThickness: 2
    });
    attackText.anchor.set(0.1);
    attackText.position.set(centerX + scaledOffset, centerY - scaledOffset * 1.1);
    attackText.zIndex = 450;
    app.stage.addChild(attackText);
  }

  private renderChargeRollBadge(unitIconScale: number, iconZIndex: number): void {
    const { unit, chargingUnitId, chargeRoll, chargeSuccess, centerX, centerY, app, HEX_RADIUS } = this.props;

    // Only show charge roll badge on the unit that is charging
    if (!chargingUnitId || unit.id !== chargingUnitId) return;

    // Must have a charge roll value to display
    if (chargeRoll === undefined || chargeRoll === null) return;

    // Calculate badge position (bottom-right of unit)
    const scaledOffset = (HEX_RADIUS * unitIconScale) / 2 * 0.8;
    const badgeX = centerX + scaledOffset;
    const badgeY = centerY + scaledOffset;

    // Badge colors based on success/failure
    // Success: light green text (#90EE90) on dark green background (#006400)
    // Failure: light red text (#FF6B6B) on dark red background (#8B0000)
    const textColor = chargeSuccess ? 0x90EE90 : 0xFF6B6B;
    const bgColor = chargeSuccess ? 0x006400 : 0x8B0000;

    // Create badge background (rounded rectangle)
    const badgeWidth = 28;
    const badgeHeight = 20;
    const badgeBg = new PIXI.Graphics();
    badgeBg.beginFill(bgColor, 0.95);
    badgeBg.lineStyle(2, chargeSuccess ? 0x00AA00 : 0xAA0000, 1);
    badgeBg.drawRoundedRect(badgeX - badgeWidth / 2, badgeY - badgeHeight / 2, badgeWidth, badgeHeight, 4);
    badgeBg.endFill();
    badgeBg.zIndex = iconZIndex + 150; // Above other indicators
    app.stage.addChild(badgeBg);

    // Create roll number text
    const rollText = new PIXI.Text(`${chargeRoll}`, {
      fontSize: 14,
      fill: textColor,
      align: 'center',
      fontWeight: 'bold',
      stroke: 0x000000,
      strokeThickness: 1
    });
    rollText.anchor.set(0.5);
    rollText.position.set(badgeX, badgeY);
    rollText.zIndex = iconZIndex + 151; // Above badge background
    app.stage.addChild(rollText);
  }
}

// Helper function to create and render a unit
export function renderUnit(props: UnitRendererProps): void {
  const renderer = new UnitRenderer(props);
  renderer.render();
}