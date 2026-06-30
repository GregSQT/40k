// frontend/src/components/UnitRenderer.tsx
import * as PIXI from "pixi.js-legacy";
import type {
  FightSubPhase,
  GameState,
  PlayerId,
  TargetPreview,
  Unit,
  UnitId,
} from "../types/game";
import {
  type BlinkProbHtmlPayload,
  buildChargeMinRollOverlay,
  buildWeaponSignature,
  createBlinkingHPBar,
  DEFAULT_BLINK_PROBABILITY_HELP_TEXT,
  type HPBlinkContainer,
  type HpBarHtmlTooltipPayload,
} from "../utils/blinkingHPBar";
import { logFightClick } from "../utils/fightClickDebug";
import { cubeDistance, offsetToCube } from "../utils/gameHelpers";
import {
  minHexDistanceBetweenUnitFootprintsLive,
  resolveBaseSizeForUnitDisplay,
} from "../utils/hexFootprint";
import { drawHiddenEyeBadge } from "../utils/hiddenBadgeDraw";
import {
  drawBattleShockBadge,
  drawMoveStatusBadge,
  type MoveStatusKind,
} from "../utils/moveStatusBadgeDraw";
import { getSelectedRangedWeaponAgainstTarget } from "../utils/probabilityCalculator";
import {
  getHpBarWidthBase,
  getIconDiameterRatio,
  getNonRoundBasePixelLayout,
  getNonRoundIconRadius,
  getSquareCornerRadiusPx,
  getUnitTokenTopExtentY,
} from "../utils/unitBaseDisplay";
import {
  getDiceAverage,
  getMeleeRange,
  getSelectedMeleeWeapon,
  getSelectedRangedWeapon,
} from "../utils/weaponHelpers";

/**
 * Rayon commun à tous les badges-statut (hidden / mouvement / battle-shock).
 * Taille FIXE, basée uniquement sur HEX_RADIUS : les badges gardent la même taille
 * absolue quelle que soit la taille de la figurine.
 */
function statusBadgeRadius(HEX_RADIUS: number): number {
  return Math.max(7, HEX_RADIUS * 0.32);
}

/** Couleur de l'œil "caché trop loin" (hors detection range), distincte du gris "couvert". */
const EYE_COLOR_TOO_FAR = 0xff3b30;

/**
 * Cache des textures d'icône rognées en disque (clé = chemin d'icône). Une base ronde est
 * rendue via un sprite CARRÉ : sans rognage, les coins de l'illustration dépassent le disque
 * de base d'un facteur √2 et débordent sur les figurines tangentes. On pré-bake UNE fois par
 * icône une texture où l'art carré est masqué par le cercle inscrit, puis on la réutilise pour
 * toutes les figurines (scale uniforme → le cercle reste cercle, valable à tout zoom).
 * Coût : 1 render-pass par icône distincte ; ZÉRO masque/surcoût par figurine, sprites batchés.
 */
const circularIconTextureCache = new Map<string, PIXI.Texture>();

/**
 * Renvoie la texture circulaire en cache pour ``iconPath`` ; ``null`` si la texture source
 * n'est pas encore chargée (l'appelant réessaie via ``baseTexture.once('loaded')``).
 */
function getCircularIconTexture(
  source: PIXI.Texture,
  iconPath: string,
  renderer: PIXI.IRenderer
): PIXI.Texture | null {
  const cached = circularIconTextureCache.get(iconPath);
  if (cached) return cached;
  if (!source.baseTexture.valid) return null;
  const diameter = Math.min(source.width, source.height);
  if (!(diameter > 0)) return null;

  // Rognage via beginTextureFill + drawCircle (PAS sprite.mask) : le masque stencil est
  // ignoré lors d'un rendu vers RenderTexture en WebGL → la texture ressortirait carrée.
  // Le disque rempli par la texture donne un rognage circulaire fiable.
  const renderTexture = PIXI.RenderTexture.create({ width: diameter, height: diameter });
  const g = new PIXI.Graphics();
  g.beginTextureFill({ texture: source });
  g.drawCircle(diameter / 2, diameter / 2, diameter / 2);
  g.endFill();
  renderer.render(g, { renderTexture });
  g.destroy();

  circularIconTextureCache.set(iconPath, renderTexture);
  return renderTexture;
}

/**
 * Profil visuel d'une figurine dans une escouade hétérogène (override de l'unité
 * parente). Valeurs déjà prêtes à l'affichage (BASE_SIZE transformé subhex côté backend).
 */
export interface ModelVisualMeta {
  DISPLAY_NAME?: string;
  ICON?: string;
  ICON_SCALE?: number;
  BASE_SHAPE?: "round" | "oval" | "square";
  BASE_SIZE?: number | [number, number];
}

interface UnitRendererProps {
  unit: Unit;
  centerX: number;
  centerY: number;
  /**
   * Pixel centers for each model (figure) of a multi-model squad.
   * When provided, per-figure components (circle/icon/eligibility/debug-id) are rendered
   * once per entry, and squad-level components (HP bar, counters, badges, indicators) are
   * rendered once at modelCenters[0]. When omitted, the unit is treated as a single figure
   * located at (centerX, centerY) — legacy behaviour.
   */
  modelCenters?: Array<[number, number]>;
  /**
   * Per-model visual overrides, aligned index-for-index with modelCenters.
   * A non-null entry replaces the unit's icon/scale/base for that figure
   * (heterogeneous squad: Sergeant / attached character). Empty array or null
   * entries fall back to the parent unit's own visual fields.
   */
  modelMetas?: Array<ModelVisualMeta | null>;
  /**
   * PV réels par figurine, alignés index-pour-index avec modelCenters.
   * Source : units_cache.models_hp_by_model (backend). Permet d'afficher la
   * barre HP propre des figs character et, en mode hpBarPerModel, de chaque fig.
   */
  modelHps?: Array<{ HP_CUR: number; HP_MAX: number; is_character: boolean } | null>;
  /**
   * Flag "caché" (rule 13.09) par figurine, aligné index-pour-index avec modelCenters.
   * Utilisé uniquement en mode statusBadgePerModel pour poser un badge sur chaque fig cachée.
   */
  modelHidden?: boolean[];
  /**
   * Flag "ghost" par figurine, aligné index-pour-index avec modelCenters.
   * true → cette figurine est rendue en ghost (cercle + icône atténués) à sa
   * position d'origine, pendant qu'elle est en cours de déplacement (move/déploiement
   * par figurine). Les autres figs restent pleines.
   */
  modelGhost?: boolean[];
  /**
   * true → une barre HP par figurine. false (défaut) → une barre agrégée par
   * escouade (figs non-character uniquement) ; les characters gardent leur barre.
   */
  hpBarPerModel?: boolean;
  /**
   * Option générique badges de statut (caché / fui / battle-shock).
   * true → un badge sur chaque figurine concernée (caché suit modelHidden ; fui et
   *        battle-shock sont au niveau unité → un badge sur chaque fig vivante).
   * false (défaut) → un seul badge si toute l'escouade a le statut.
   */
  statusBadgePerModel?: boolean;
  /** true → masque tous les indicateurs autour des icônes (HP, badges, cercle vert, voile charge, debug-id). L'icône et son cercle de base restent visibles. */
  hideIndicators?: boolean;
  app: PIXI.Application;
  uiElementsContainer?: PIXI.Container; // Persistent container for UI elements (target logos, badges) that should never be cleaned up
  useOverlayIcons?: boolean; // Render advance/weapon icons in DOM overlay
  isPreview?: boolean;
  previewType?: "move" | "attack";
  isEligible?: boolean; // Add eligibility as a prop instead of calculating it
  isShootable?: boolean; // Add shootability based on LoS validation
  displayOrientationStep?: number;

  // Blinking state for multi-unit HP bars
  blinkingUnits?: number[];
  blinkingAttackerId?: number | null;
  isBlinkingActive?: boolean;
  blinkVersion?: number;
  blinkState?: boolean;
  shootingTargetInCover?: boolean;
  /** Per-unit cover from move-preview LoS hover (footprint ratio); overrides shootingTargetInCover when set */
  movePreviewShootingTargetInCoverByUnitId?: Record<string, boolean>;
  /** True if this target is hidden beyond the active shooter's detection range ("trop loin" → œil rouge). */
  hiddenTooFar?: boolean;
  /** Per-unit "trop loin" from LoS hover/blink; overrides hiddenTooFar when set. Parallèle au cover. */
  movePreviewHiddenTooFarByUnitId?: Record<string, boolean>;

  // Shooting target (for replay mode explosion icon)
  shootingTargetId?: number | null;
  shootingUnitId?: number | null;

  // Movement indicator (for replay mode boot icon)
  movingUnitId?: number | null;

  // Charge indicator (for replay mode lightning icon)
  chargingUnitId?: number | null;
  chargeTargetId?: number | null;
  /** V11 multi-cibles : cibles toggleées en mode chargeTargetSelect (voile violet pré-validation). */
  chargePreviewTargetIds?: number[];

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
  HEX_HORIZ_SPACING: number;
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
  ruleChoiceHighlightedUnitId?: number | null;
  unitsMoved: number[];
  unitsCharged?: number[];
  unitsAttacked?: number[];
  unitsFled?: number[];
  unitsAdvanced?: number[];
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
  onUnitTooltip?: (tooltip: HpBarHtmlTooltipPayload) => void;
  onUnitIconHoverChange?: (unitId: UnitId | null) => void;
  /** Clic gauche sur une unité non-activable : épingle son illustration (display-select). */
  onUnitDisplaySelect?: (unitId: UnitId) => void;
  /** Cadre % / bouclier net (HTML) au-dessus de la barre blink */
  onBlinkProbHtml?: (payload: BlinkProbHtmlPayload) => void;
  renderTarget?: PIXI.Container;
  /** Plafond du jet 2D6 (règle `charge_max_distance`) pour l’affichage au-dessus de la barre blink en phase charge. */
  chargeMaxDistance?: number;
}

export class UnitRenderer {
  private props: UnitRendererProps;
  private lastBlinkVersion: number | null = null;
  private target: PIXI.Container;

  constructor(props: UnitRendererProps) {
    this.props = props;
    this.target = props.renderTarget ?? props.app.stage;
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

  private getUnitTooltipText(): string {
    const { unit } = this.props;
    const displayName = unit.DISPLAY_NAME || unit.name || unit.type || unit.unitType || "Unknown";
    return `${displayName} - ID ${unit.id}`;
  }

  private attachTooltipHandlers(displayObject: PIXI.DisplayObject): void {
    if (!this.props.onUnitTooltip && !this.props.onUnitIconHoverChange) {
      return;
    }
    const tooltipText = this.getUnitTooltipText();
    const updateTooltipPosition = (e: PIXI.FederatedPointerEvent): void => {
      const canvas = this.props.app.view as HTMLCanvasElement;
      const rect = canvas.getBoundingClientRect();
      this.props.onUnitTooltip?.({
        visible: true,
        text: tooltipText,
        x: rect.left + e.global.x,
        y: rect.top + e.global.y,
      });
    };
    displayObject.on("pointerover", (e: PIXI.FederatedPointerEvent) => {
      this.props.onUnitIconHoverChange?.(this.props.unit.id);
      updateTooltipPosition(e);
    });
    displayObject.on("pointermove", (e: PIXI.FederatedPointerEvent) => {
      updateTooltipPosition(e);
    });
    const hideTooltip = (): void => {
      this.props.onUnitIconHoverChange?.(null);
      this.props.onUnitTooltip?.({
        visible: false,
        text: tooltipText,
        x: 0,
        y: 0,
      });
    };
    const handlePointerDown = (e: PIXI.FederatedPointerEvent): void => {
      const { unit, selectedUnitId, current_player, isEligible, onUnitDisplaySelect } = this.props;
      // Display-select (épingle) seulement si : clic gauche, aucune unité en cours d'activation,
      // et l'unité cliquée n'est pas elle-même activable (sinon ce clic l'active).
      const noActiveUnit = selectedUnitId == null;
      const isActivatable = unit.player === current_player && (isEligible ?? false);
      if (e.button === 0 && noActiveUnit && !isActivatable && onUnitDisplaySelect) {
        e.stopPropagation();
        onUnitDisplaySelect(unit.id);
        return; // on épingle : ne pas masquer l'illustration
      }
      hideTooltip();
    };
    displayObject.on("pointerout", hideTooltip);
    displayObject.on("pointerleave", hideTooltip);
    displayObject.on("pointerdown", handlePointerDown);
  }

  private cleanupExistingBlinkIntervals(): void {
    // Find any existing blink containers and clean them up
    // Check if this unit should still be blinking
    const shouldBlink =
      Array.isArray(this.props.blinkingUnits) &&
      this.props.blinkingUnits.some((id) => String(id) === String(this.props.unit.id));
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
      const useRangedForBlinkSignature =
        this.props.phase === "shoot" ||
        this.props.mode === "movePreview" ||
        (this.props.phase === "move" &&
          (this.props.mode === "select" || this.props.mode === "movePreview"));
      if (attacker && useRangedForBlinkSignature) {
        const selectedRangedWeapon = getSelectedRangedWeapon(attacker);
        const selectedWeaponIgnoresCover =
          Array.isArray(selectedRangedWeapon?.WEAPON_RULES) &&
          selectedRangedWeapon.WEAPON_RULES.some((rule) => rule === "IGNORES_COVER");
        let effectiveTargetInCover = false;
        if (selectedWeaponIgnoresCover) {
          effectiveTargetInCover = false;
        } else if (
          (this.props.mode === "movePreview" ||
            this.props.mode === "select" ||
            this.props.mode === "attackPreview" ||
            this.props.mode === "squadModelShoot") &&
          this.props.movePreviewShootingTargetInCoverByUnitId
        ) {
          const key = String(this.props.unit.id);
          const map = this.props.movePreviewShootingTargetInCoverByUnitId;
          if (Object.hasOwn(map, key)) {
            effectiveTargetInCover = map[key] === true;
          } else {
            effectiveTargetInCover = this.props.shootingTargetInCover === true;
          }
        } else {
          effectiveTargetInCover = this.props.shootingTargetInCover === true;
        }
        const rangedEff = getSelectedRangedWeaponAgainstTarget(
          attacker,
          this.props.unit,
          effectiveTargetInCover
        );
        if (rangedEff) {
          expectedWeaponSignature = buildWeaponSignature(rangedEff.weapon);
        }
      } else if (attacker && !useRangedForBlinkSignature) {
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
      if (!isJustKilled) {
        // Unit destroyed: purge its persistent UI badges (hidden / battle-shocked)
        // from uiElementsContainer, which survives drawBoard cleanup.
        const { uiElementsContainer } = this.props;
        if (uiElementsContainer) {
          const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
          const prefixes = [
            `hidden-badge-${unitIdNum}`,
            `fled-badge-${unitIdNum}`,
            `move-status-${unitIdNum}`,
            `battle-shocked-${unitIdNum}`,
          ];
          uiElementsContainer.children
            .filter(
              (child: PIXI.DisplayObject) =>
                typeof child.name === "string" &&
                prefixes.some((p) => child.name === p || child.name!.startsWith(`${p}-`))
            )
            .forEach((child: PIXI.DisplayObject) => {
              uiElementsContainer.removeChild(child);
              if ("destroy" in child && typeof child.destroy === "function") child.destroy();
            });
        }
        return;
      }
    }

    const HEX_HORIZ_SPACING = 1.5 * this.props.HEX_RADIUS;
    const displayBase = resolveBaseSizeForUnitDisplay(unit);
    const baseSize = displayBase > 1 ? displayBase : undefined;
    const unitIconScale = baseSize
      ? (baseSize * HEX_HORIZ_SPACING) / this.props.HEX_RADIUS
      : unit.ICON_SCALE || this.props.ICON_SCALE;

    // ===== Z-INDEX CALCULATIONS =====
    const unitZIndexRange = 149;
    const minIconScale = 0.5;
    const maxIconScale = baseSize ? Math.max(2.5, unitIconScale + 1) : 2.5;
    const minZIndex = 100;
    const scaleRange = maxIconScale - minIconScale;
    const iconZIndex =
      minZIndex + Math.round(((maxIconScale - unitIconScale) / scaleRange) * unitZIndexRange);

    // ===== AI_TURN.md COMPLIANT ELIGIBILITY =====
    const isEligible = this.calculateEligibilityCompliant();

    // ===== MULTI-FIGURE LOOP =====
    // Per-figure components are rendered once per model position; squad-level components
    // are rendered once at the anchor (first model center).
    const modelCenters: Array<[number, number]> =
      this.props.modelCenters && this.props.modelCenters.length > 0
        ? this.props.modelCenters
        : [[this.props.centerX, this.props.centerY]];
    const originalCenterX = this.props.centerX;
    const originalCenterY = this.props.centerY;

    // Escouade hétérogène : chaque figurine peut avoir son propre profil visuel
    // (icône, échelle, base). On substitue temporairement this.props.unit par un
    // "unit virtuel" pour que TOUTES les fonctions de rendu (cercle, icône, rayon
    // de base) voient les bonnes valeurs sans réécriture. Restauré après la boucle.
    const modelMetas = this.props.modelMetas;
    const modelHps = this.props.modelHps;
    const originalUnit = this.props.unit;
    const multiModel = modelCenters.length > 1;
    // Barre HP par-figurine désactivée quand l'escouade entière clignote (preview
    // de tir/charge) : la barre squad prend le relais le temps du survol.
    const squadBlinkActive =
      (Array.isArray(this.props.blinkingUnits) &&
        this.props.blinkingUnits.some((id) => String(id) === String(originalUnit.id))) ||
      ((this.props.mode === "targetPreview" || this.props.mode === "attackPreview") &&
        !!this.props.targetPreview &&
        this.props.targetPreview.targetId === originalUnit.id);
    modelCenters.forEach(([mx, my], i) => {
      this.props.centerX = mx;
      this.props.centerY = my;
      const meta = modelMetas?.[i];
      const figGhost = this.props.modelGhost?.[i] === true;
      const figUnit = meta ? ({ ...originalUnit, ...meta } as Unit) : originalUnit;
      this.props.unit = figGhost ? ({ ...figUnit, isGhost: true } as Unit) : figUnit;
      // Échelle d'icône recalculée par figurine (dépend de BASE_SIZE / ICON_SCALE).
      const figDisplayBase = resolveBaseSizeForUnitDisplay(this.props.unit);
      const figBaseSize = figDisplayBase > 1 ? figDisplayBase : undefined;
      const figIconScale = figBaseSize
        ? (figBaseSize * HEX_HORIZ_SPACING) / this.props.HEX_RADIUS
        : this.props.unit.ICON_SCALE || this.props.ICON_SCALE;
      this.renderUnitCircle(iconZIndex);
      this.renderUnitIcon(iconZIndex);
      if (!this.props.hideIndicators) {
        this.renderChargeTargetVeil(iconZIndex);
        this.renderGreenActivationCircle(isEligible, figIconScale);
        this.renderUnitIdDebug(iconZIndex);
        // Barre HP propre de la figurine : pour toutes les figs en mode
        // hpBarPerModel, et TOUJOURS pour un character (les deux modes).
        const mh = modelHps?.[i];
        if (
          mh &&
          multiModel &&
          !squadBlinkActive &&
          (this.props.hpBarPerModel || mh.is_character)
        ) {
          this.drawStaticHpBar(mh.HP_CUR, mh.HP_MAX, figIconScale);
        }
      }
    });
    this.props.unit = originalUnit;

    // Squad-level UI anchored at first model center
    this.props.centerX = modelCenters[0][0];
    this.props.centerY = modelCenters[0][1];
    if (!this.props.hideIndicators) {
      this.renderHPBar(unitIconScale);
      this.renderShootingCounter(unitIconScale);
      this.renderAdvanceButton(unitIconScale, iconZIndex);
      this.renderWeaponSelectionIcon(unitIconScale, iconZIndex);
      this.renderTargetIndicator(iconZIndex);
      this.renderShootingIndicator(iconZIndex);
      this.renderMovementIndicator(iconZIndex);
      this.renderChargeIndicator(iconZIndex);
      this.renderFightIndicator(iconZIndex);
      this.renderAttackCounter(unitIconScale);
      this.renderHiddenBadge(unitIconScale);
      this.renderMoveStatusBadge(unitIconScale);
      this.renderBattleShockedIndicator();
    }

    this.props.centerX = originalCenterX;
    this.props.centerY = originalCenterY;
  }

  private calculateEligibilityCompliant(): boolean {
    const { unit, phase, current_player, unitsFled } = this.props;

    // Basic eligibility checks
    // Allow just-killed units to be rendered as grey ghosts
    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;
    const isJustKilled = unitWithFlags.isJustKilled === true;
    const hpCurValue = Number(unit.HP_CUR);
    if (Number.isNaN(hpCurValue)) {
      throw new Error(`Invalid HP_CUR value for unit ${unit.id}`);
    }
    if (unit.HP_CUR === undefined || (hpCurValue <= 0 && !isJustKilled)) return false;
    if (phase !== "fight" && unit.player !== current_player) return false;

    switch (phase) {
      case "move":
        return this.props.isEligible || false;
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
      isPreview,
      selectedUnitId,
      ruleChoiceHighlightedUnitId,
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

    // Grey-out enemies that are NOT valid shooting targets during shooting phase
    // ONLY apply when we have actual blinking data (prevents grey flash during loading)
    // - Replay mode: blinkingUnits is undefined -> skip greying
    // - PvP mode before backend responds: blinkingUnits is [] or undefined -> skip greying
    // - PvP mode with targets: blinkingUnits has IDs -> apply greying
    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;

    // Unified: movePreview and shoot phase use same greying logic (non-targetable = ghost)
    const hasShootingPreviewContext =
      (phase === "shoot" && selectedUnitId !== null) || this.props.mode === "movePreview";
    if (
      !isPreview &&
      hasShootingPreviewContext &&
      unit.player !== current_player &&
      this.props.blinkingUnits &&
      this.props.blinkingUnits.length > 0
    ) {
      const isShootable =
        this.props.isShootable !== undefined
          ? this.props.isShootable
          : this.props.blinkingUnits.some((id) => String(id) === String(unit.id));

      if (!isShootable && !unitWithFlags.isGhost) {
        const grey = 0x888888;
        const nrGrey = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
        const g = new PIXI.Graphics();
        g.beginFill(grey);
        g.lineStyle(DEFAULT_BORDER_WIDTH, grey);
        if (nrGrey) {
          if (nrGrey.kind === "oval") {
            g.drawEllipse(centerX, centerY, nrGrey.outerRx, nrGrey.outerRy);
          } else {
            const h = nrGrey.squareHalf;
            const s = nrGrey.squareSide;
            g.drawRoundedRect(centerX - h, centerY - h, s, s, getSquareCornerRadiusPx());
          }
        } else {
          const displayGrey = resolveBaseSizeForUnitDisplay(unit);
          const baseSizeGrey = displayGrey > 1 ? displayGrey : undefined;
          const greyRadius = baseSizeGrey
            ? (baseSizeGrey / 2) * 1.5 * HEX_RADIUS
            : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
          g.drawCircle(centerX, centerY, greyRadius);
        }
        g.endFill();
        g.zIndex = iconZIndex;
        g.eventMode = "static";
        g.cursor = "default";
        this.attachTooltipHandlers(g);
        this.target.addChild(g);
        return;
      }
    }

    /** Remplissage socle : toujours couleur joueur (sauf ghost / just-killed) — l’état « déjà activé » ne grise plus le socle. */
    const socleFill = unit.color;
    let borderColor = 0x000000;
    let borderWidth = DEFAULT_BORDER_WIDTH;

    const hasUsedState =
      unitsMoved.includes(unit.id) ||
      Boolean(unitsCharged?.includes(unit.id)) ||
      Boolean(unitsAttacked?.includes(unit.id));

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
    } else if (hasUsedState) {
      borderColor = 0x777777;
      borderWidth = DEFAULT_BORDER_WIDTH;
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

    let finalSocleFill = socleFill;
    let finalBorderColor = borderColor;
    let circleAlpha = 1.0;
    if (unitWithFlags.isGhost) {
      // Ghost uses move-preview icon palette, but darker.
      finalSocleFill = this.getCSSColor("--icon-move-bg-color");
      finalBorderColor = this.getCSSColor("--icon-move-color");
      circleAlpha = 0.45;
    }

    // Just-killed unit styling (show as grey ghost before removal)
    if (unitWithFlags.isJustKilled) {
      finalSocleFill = 0x999999;
      finalBorderColor = 0xbbbbbb;
      circleAlpha = 0.65;
    }

    const displayCircle = resolveBaseSizeForUnitDisplay(unit);
    const baseSizeVal = displayCircle > 1 ? displayCircle : undefined;
    const nrBase = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    const displayOrientationStep = this.props.displayOrientationStep;
    if (
      displayOrientationStep !== undefined &&
      (!Number.isInteger(displayOrientationStep) ||
        displayOrientationStep < 0 ||
        displayOrientationStep > 5)
    ) {
      throw new Error(
        `displayOrientationStep must be an integer in 0..5, got ${String(displayOrientationStep)}`
      );
    }
    const circleRadius = baseSizeVal
      ? (baseSizeVal / 2) * 1.5 * HEX_RADIUS
      : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;

    unitCircle.beginFill(finalSocleFill);
    unitCircle.lineStyle(borderWidth, finalBorderColor);
    if (nrBase) {
      if (nrBase.kind === "oval") {
        unitCircle.drawEllipse(centerX, centerY, nrBase.outerRx, nrBase.outerRy);
      } else {
        const h = nrBase.squareHalf;
        const s = nrBase.squareSide;
        unitCircle.drawRoundedRect(centerX - h, centerY - h, s, s, getSquareCornerRadiusPx());
      }
    } else {
      unitCircle.drawCircle(centerX, centerY, circleRadius);
    }
    unitCircle.endFill();
    unitCircle.alpha = circleAlpha;
    unitCircle.zIndex = iconZIndex;
    if (nrBase && displayOrientationStep !== undefined) {
      unitCircle.pivot.set(centerX, centerY);
      unitCircle.position.set(centerX, centerY);
      unitCircle.rotation = (displayOrientationStep * Math.PI) / 3;
    }

    if (isPreview) {
      unitCircle.eventMode = "none";
      unitCircle.cursor = "default";
    } else {
      // Add click handlers for normal units (with charge-cancel on re-click)
      unitCircle.eventMode = "static";
      unitCircle.cursor = "pointer";
      this.attachTooltipHandlers(unitCircle);

      // hitArea bypasses PIXI v7's stale bounding-box pre-check and routes directly to the
      // shape's contains() — reliable for freshly-added circles in the unitsLayer.
      if (!nrBase) {
        unitCircle.hitArea = new PIXI.Circle(centerX, centerY, circleRadius);
      }
    }

    if (
      !isPreview &&
      phase === "charge" &&
      selectedUnitId === unit.id &&
      this.props.mode === "chargePreview"
    ) {
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
    } else if (!isPreview) {
      // Block enemy unit clicks when no friendly unit is selected
      let addClickHandler = true;

      // Fight phase exception - allow clicking units in ALL fight subphases
      // Lines 738, 765, 820, 847: "player activate one unit by left clicking on it"
      const isFightPhaseActive =
        phase === "fight" &&
        (this.props.fightSubPhase === "pile_in" ||
          this.props.fightSubPhase === "fight" ||
          this.props.fightSubPhase === "consolidate");

      // Block enemy clicks when no unit is selected (prevents stuck preview)
      // EXCEPT during fight phase where eligible units must be clickable
      if (unit.player !== current_player && selectedUnitId === null && !isFightPhaseActive) {
        addClickHandler = false;
      }

      // Movement phase: only the selected unit must pass pointer events through
      // to the hitArea underneath (boardHexClick → onDirectMove).
      // Non-active units stay hoverable for the illustration preview.
      if (phase === "move" && unit.id === selectedUnitId) {
        addClickHandler = false;
        unitCircle.eventMode = "none";
        unitCircle.cursor = "default";
      }
      if (phase === "move" && unit.player !== current_player) {
        addClickHandler = false;
        unitCircle.cursor = "default";
      }
      // Advance (shoot) : même principe que le move — clic gauche sur l’icône / l’hex valide
      // via capture canvas (boardHexClick → onAdvanceMove), pas d’annulation sur l’unité.
      if (phase === "shoot" && this.props.mode === "advancePreview" && unit.id === selectedUnitId) {
        addClickHandler = false;
        unitCircle.eventMode = "none";
        unitCircle.cursor = "default";
      }
      if (
        phase === "charge" &&
        unit.player !== current_player &&
        this.props.mode !== "chargePreview" &&
        this.props.mode !== "chargeTargetSelect"
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
          unitCircle.cursor = "default";
        } else {
          unitCircle.on("pointerdown", (e: PIXI.FederatedPointerEvent) => {
            if (e.button === 0 || e.button === 2) {
              // Left or right click
              // Prevent context menu and event bubbling
              e.preventDefault();
              e.stopPropagation();

              if (phase === "fight") {
                logFightClick("UnitRenderer: pointerdown sur cercle unité", {
                  unitId: unit.id,
                  unitPlayer: unit.player,
                  mode,
                  selectedUnitId,
                  fightSubPhase: this.props.fightSubPhase,
                  button: e.button,
                });
              }

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
        unitCircle.cursor = "default";
        if (phase === "fight") {
          logFightClick("UnitRenderer: pas de handler pointerdown (clic ignoré au niveau unité)", {
            unitId: unit.id,
            unitPlayer: unit.player,
            current_player,
            mode,
            selectedUnitId,
            fightSubPhase: this.props.fightSubPhase,
            isFightPhaseActive:
              phase === "fight" &&
              (this.props.fightSubPhase === "pile_in" ||
                this.props.fightSubPhase === "fight" ||
                this.props.fightSubPhase === "consolidate"),
          });
        }
      }
    }

    this.target.addChild(unitCircle);

    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
    const isRuleChoiceHighlighted =
      !isPreview &&
      ruleChoiceHighlightedUnitId !== null &&
      Number.isFinite(unitIdNum) &&
      Number.isFinite(ruleChoiceHighlightedUnitId) &&
      unitIdNum === ruleChoiceHighlightedUnitId;
    if (isRuleChoiceHighlighted) {
      const markerCircle = new PIXI.Graphics();
      markerCircle.lineStyle(borderWidth + 2, 0xffd700, 0.95);
      if (nrBase) {
        if (nrBase.kind === "oval") {
          markerCircle.drawEllipse(centerX, centerY, nrBase.outerRx + 5, nrBase.outerRy + 5);
        } else {
          const pad = 5;
          markerCircle.drawRoundedRect(
            centerX - nrBase.squareHalf - pad,
            centerY - nrBase.squareHalf - pad,
            nrBase.squareSide + pad * 2,
            nrBase.squareSide + pad * 2,
            getSquareCornerRadiusPx() + 2
          );
        }
      } else {
        markerCircle.drawCircle(centerX, centerY, circleRadius + 5);
      }
      markerCircle.zIndex = iconZIndex + 1;
      markerCircle.eventMode = "none";
      this.target.addChild(markerCircle);
    }
  }

  private renderUnitIcon(iconZIndex: number): void {
    const {
      unit,
      centerX,
      centerY,
      isPreview,
      previewType,
      HEX_RADIUS,
      ICON_SCALE,
      phase,
      current_player,
      onConfirmMove,
      selectedUnitId,
      unitsMoved,
      unitsCharged,
      unitsAttacked,
    } = this.props;

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

        const nonRoundIconR = getNonRoundIconRadius(unit, HEX_RADIUS);
        // Source unique : ratio partagé (cf. getIconDiameterRatio), × HEX_RADIUS.
        const iconDiameter = getIconDiameterRatio(unit, ICON_SCALE) * HEX_RADIUS;

        const sprite = new PIXI.Sprite(texture);
        sprite.anchor.set(0.5);
        sprite.position.set(centerX, centerY);

        // Base ronde : rogner l'illustration carrée en disque (rayon = rayon de collision) via la
        // texture circulaire mutualisée → les coins ne débordent plus sur les voisines tangentes.
        if (nonRoundIconR == null) {
          const circular = getCircularIconTexture(texture, iconPath, this.props.app.renderer);
          if (circular) {
            sprite.texture = circular;
          } else {
            texture.baseTexture.once("loaded", () => {
              if (sprite.destroyed) return;
              const t = getCircularIconTexture(texture, iconPath, this.props.app.renderer);
              if (t) {
                sprite.texture = t;
                sprite.width = iconDiameter;
                sprite.height = iconDiameter;
              }
            });
          }
        }

        sprite.width = iconDiameter;
        sprite.height = iconDiameter;
        sprite.zIndex = iconZIndex;
        sprite.alpha = 1.0; // Always fully opaque

        let iconMask: PIXI.Graphics | null = null;
        if (nonRoundIconR != null) {
          iconMask = new PIXI.Graphics();
          iconMask.beginFill(0xffffff);
          iconMask.drawCircle(centerX, centerY, nonRoundIconR);
          iconMask.endFill();
          sprite.mask = iconMask;
        }

        interface UnitWithFlags extends Unit {
          isJustKilled?: boolean;
          isGhost?: boolean;
        }
        const unitWithFlags = unit as UnitWithFlags;

        // Ghost unit rendering (for replay move visualization)
        if (unitWithFlags.isGhost) {
          sprite.alpha = 0.42;
          sprite.tint = this.getCSSColor("--icon-move-color");
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

        const iconUsedState =
          !isPreview &&
          !unitWithFlags.isGhost &&
          !unitWithFlags.isJustKilled &&
          (unitsMoved.includes(unit.id) ||
            Boolean(unitsCharged?.includes(unit.id)) ||
            Boolean(unitsAttacked?.includes(unit.id)));
        if (iconUsedState) {
          sprite.alpha *= 0.88;
        }

        // Unified: movePreview and shoot phase use same greying logic
        const hasShootingPreviewContextSprite =
          (phase === "shoot" && selectedUnitId !== null) || this.props.mode === "movePreview";
        if (
          !isPreview &&
          hasShootingPreviewContextSprite &&
          unit.player !== current_player &&
          this.props.blinkingUnits != null
        ) {
          const isShootable =
            this.props.isShootable !== undefined
              ? this.props.isShootable
              : this.props.blinkingUnits.some((id) => String(id) === String(unit.id));

          if (!isShootable) {
            sprite.alpha = 0.5;
            sprite.tint = 0x888888;
          }
        }

        if (iconMask) {
          this.target.addChild(iconMask);
        }
        this.target.addChild(sprite);
      } catch {
        this.renderTextFallback(iconZIndex);
      }
    } else {
      this.renderTextFallback(iconZIndex);
    }
  }

  private renderTextFallback(iconZIndex: number): void {
    const { unit, centerX, centerY } = this.props;

    interface UnitWithFlags extends Unit {
      isJustKilled?: boolean;
      isGhost?: boolean;
    }
    const unitWithFlags = unit as UnitWithFlags;

    // Ghost unit styling
    let textColor = 0xffffff;
    let textAlpha = 1.0;
    if (unitWithFlags.isGhost) {
      textColor = this.getCSSColor("--icon-move-color");
      textAlpha = 0.65;
    }

    // Just-killed unit styling
    if (unitWithFlags.isJustKilled) {
      textColor = 0x666666;
      textAlpha = 0.5;
    }

    const unitText = new PIXI.Text(unit.DISPLAY_NAME || unit.name || `U${unit.id}`, {
      fontSize: this.props.UNIT_TEXT_SIZE,
      fill: textColor,
      align: "center",
      fontWeight: "bold",
    });
    unitText.anchor.set(0.5);
    unitText.position.set(centerX, centerY);
    unitText.alpha = textAlpha;
    unitText.zIndex = iconZIndex;
    this.target.addChild(unitText);
  }

  /**
   * V11 multi-cibles : voile violet semi-transparent sur une unité toggleée comme cible de
   * charge (mode `chargeTargetSelect`, avant validation par le bouton « Charge »).
   */
  private renderChargeTargetVeil(iconZIndex: number): void {
    const { unit, centerX, centerY, mode, HEX_RADIUS, UNIT_CIRCLE_RADIUS_RATIO } = this.props;
    // chargeTargetSelect : voile jaune (contour + remplissage). chargePreview : on garde seulement
    // le cercle jaune (contour) sur les cibles déclarées jusqu'à la validation de la charge.
    if (mode !== "chargeTargetSelect" && mode !== "chargePreview") return;
    const withFill = mode === "chargeTargetSelect";
    const ids = this.props.chargePreviewTargetIds;
    if (!ids || ids.length === 0) return;
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
    if (!ids.some((id) => id === unitIdNum)) return;

    const YELLOW = this.getCSSColor("--icon-blink-target-ring");
    const nrBase = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    const veil = new PIXI.Graphics();
    if (withFill) veil.beginFill(YELLOW, 0.45);
    veil.lineStyle(3, YELLOW, 0.95);
    if (nrBase) {
      if (nrBase.kind === "oval") {
        veil.drawEllipse(centerX, centerY, nrBase.outerRx, nrBase.outerRy);
      } else {
        const h = nrBase.squareHalf;
        const s = nrBase.squareSide;
        veil.drawRoundedRect(centerX - h, centerY - h, s, s, getSquareCornerRadiusPx());
      }
    } else {
      const displayBase = resolveBaseSizeForUnitDisplay(unit);
      const baseSizeVal = displayBase > 1 ? displayBase : undefined;
      const radius = baseSizeVal
        ? (baseSizeVal / 2) * 1.5 * HEX_RADIUS
        : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
      veil.drawCircle(centerX, centerY, radius);
    }
    if (withFill) veil.endFill();
    veil.zIndex = iconZIndex + 60; // au-dessus de l'icône
    veil.eventMode = "none";
    this.target.addChild(veil);
  }

  private renderGreenActivationCircle(isEligible: boolean, unitIconScale: number): void {
    if (!isEligible) return;

    const {
      centerX,
      centerY,
      unit,
      HEX_RADIUS,
      ELIGIBLE_OUTLINE_WIDTH,
      ELIGIBLE_COLOR,
      ELIGIBLE_OUTLINE_ALPHA,
      phase,
      fightSubPhase,
      displayOrientationStep,
    } = this.props;

    const nrEl = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    const eligibleOutline = new PIXI.Graphics();
    eligibleOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, ELIGIBLE_COLOR, ELIGIBLE_OUTLINE_ALPHA);
    const outlinePad = 1.045;
    if (nrEl) {
      if (
        displayOrientationStep !== undefined &&
        (!Number.isInteger(displayOrientationStep) ||
          displayOrientationStep < 0 ||
          displayOrientationStep > 5)
      ) {
        throw new Error(
          `displayOrientationStep must be an integer in 0..5, got ${String(displayOrientationStep)}`
        );
      }
      if (nrEl.kind === "oval") {
        eligibleOutline.drawEllipse(
          centerX,
          centerY,
          nrEl.outerRx * outlinePad,
          nrEl.outerRy * outlinePad
        );
      } else {
        const sh = nrEl.squareHalf * outlinePad;
        const ss = nrEl.squareSide * outlinePad;
        eligibleOutline.drawRoundedRect(
          centerX - sh,
          centerY - sh,
          ss,
          ss,
          getSquareCornerRadiusPx() + 2
        );
      }
      if (displayOrientationStep !== undefined) {
        eligibleOutline.pivot.set(centerX, centerY);
        eligibleOutline.position.set(centerX, centerY);
        eligibleOutline.rotation = (displayOrientationStep * Math.PI) / 3;
      }
    } else {
      const circleRadius = ((HEX_RADIUS * unitIconScale) / 2) * 1.1;
      eligibleOutline.drawCircle(centerX, centerY, circleRadius);
    }

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
    this.target.addChild(eligibleOutline);

    // Anneau rouge pour les unités ayant chargé (Fights First V11) — visible pendant
    // les sous-phases pile_in et fight.
    if (
      phase === "fight" &&
      (fightSubPhase === "pile_in" || fightSubPhase === "fight") &&
      unit.hasChargedThisTurn &&
      isEligible
    ) {
      const chargedOutline = new PIXI.Graphics();
      chargedOutline.lineStyle(ELIGIBLE_OUTLINE_WIDTH, 0xff0000, ELIGIBLE_OUTLINE_ALPHA);
      const redPad = 1.07;
      if (nrEl) {
        if (nrEl.kind === "oval") {
          chargedOutline.drawEllipse(
            centerX,
            centerY,
            nrEl.outerRx * redPad,
            nrEl.outerRy * redPad
          );
        } else {
          const sh = nrEl.squareHalf * redPad;
          const ss = nrEl.squareSide * redPad;
          chargedOutline.drawRoundedRect(
            centerX - sh,
            centerY - sh,
            ss,
            ss,
            getSquareCornerRadiusPx() + 3
          );
        }
        if (displayOrientationStep !== undefined) {
          chargedOutline.pivot.set(centerX, centerY);
          chargedOutline.position.set(centerX, centerY);
          chargedOutline.rotation = (displayOrientationStep * Math.PI) / 3;
        }
      } else {
        const circleRadius = ((HEX_RADIUS * unitIconScale) / 2) * 1.1;
        const outerCircleRadius = circleRadius + ELIGIBLE_OUTLINE_WIDTH + 2;
        chargedOutline.drawCircle(centerX, centerY, outerCircleRadius);
      }
      chargedOutline.zIndex = 251; // Above green circle
      this.target.addChild(chargedOutline);
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
      (shootingTargetId !== null &&
        shootingTargetId !== undefined &&
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
    const { HEX_RADIUS } = this.props;

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
    squareBg.zIndex = iconZIndex + 1000;
    this.target.addChild(squareBg);

    // Load and create icon sprite
    const texture = PIXI.Texture.from(iconPath);
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001;
    this.target.addChild(iconSprite);
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
    const { HEX_RADIUS } = this.props;

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
    circleBg.zIndex = iconZIndex + 1000;
    this.target.addChild(circleBg);

    // Load and create icon sprite
    const texture = PIXI.Texture.from(iconPath);
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const iconDisplaySize = HEX_RADIUS * iconSize * iconScale;
    iconSprite.width = iconDisplaySize;
    iconSprite.height = iconDisplaySize;
    iconSprite.zIndex = iconZIndex + 1001;
    this.target.addChild(iconSprite);
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
      targetPreview,
      units,
      mode,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      HP_BAR_WIDTH_RATIO,
      HP_BAR_HEIGHT,
      UNIT_CIRCLE_RADIUS_RATIO,
    } = this.props;

    if (!unit.HP_MAX) return; // Only skip if no HP_MAX, not if isPreview

    const nrHp = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    const hpDisplayBase = resolveBaseSizeForUnitDisplay(unit);
    const baseSizeVal = hpDisplayBase > 1 ? hpDisplayBase : 0;
    const tokenTop = getUnitTokenTopExtentY(
      unit,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      UNIT_CIRCLE_RADIUS_RATIO
    );
    const hpWidthBase = getHpBarWidthBase(unit, HEX_RADIUS, HEX_HORIZ_SPACING, unitIconScale);
    const HP_BAR_WIDTH =
      (baseSizeVal > 0 || nrHp ? hpWidthBase : HEX_RADIUS * unitIconScale) * HP_BAR_WIDTH_RATIO;
    const barX = centerX - HP_BAR_WIDTH / 2;
    const barY = centerY - tokenTop - HP_BAR_HEIGHT - 1;

    // Check if this unit is being previewed for shooting
    const isTargetPreviewed =
      (mode === "targetPreview" || mode === "attackPreview") &&
      targetPreview &&
      targetPreview.targetId === unit.id;

    // Check if this unit should be blinking (multi-unit blinking for valid targets)
    const shouldBlink =
      Array.isArray(this.props.blinkingUnits) &&
      this.props.blinkingUnits.some((id) => String(id) === String(unit.id));

    const getEffectiveTargetInCover = (attacker: Unit | null): boolean =>
      this.getEffectiveTargetInCover(attacker);

    // Use either individual target preview OR multi-unit blinking
    const shouldShowBlinkingHP = isTargetPreviewed || shouldBlink;
    const finalBarWidth = shouldShowBlinkingHP ? HP_BAR_WIDTH * 1.5 : HP_BAR_WIDTH;
    const finalBarHeight = shouldShowBlinkingHP ? HP_BAR_HEIGHT * 1.5 : HP_BAR_HEIGHT;
    const finalBarX = shouldShowBlinkingHP ? centerX - finalBarWidth / 2 : barX;
    const finalBarY = shouldShowBlinkingHP ? barY - (finalBarHeight - HP_BAR_HEIGHT) : barY;

    // HP calculation with preview
    const currentHP = Math.max(0, unit.HP_CUR);
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
            const rangedEff = getSelectedRangedWeaponAgainstTarget(
              shooter,
              unit,
              getEffectiveTargetInCover(shooter)
            );
            if (rangedEff) {
              const potentialDamage = Number(rangedEff.potentialDamage);
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
      // movePreview ou move+select (survol destination) → dégâts tir comme phase shoot
      const blinkPhase: "shoot" | "fight" | "charge" =
        this.props.mode === "movePreview" ||
        (this.props.phase === "move" && this.props.mode === "select")
          ? "shoot"
          : (this.props.phase as "shoot" | "fight" | "charge");

      const chargeMaxInches = this.props.chargeMaxDistance ?? 12;
      const bc = this.props.boardConfig;
      const inchesToSubhexRaw =
        bc &&
        typeof bc === "object" &&
        "inches_to_subhex" in bc &&
        typeof (bc as { inches_to_subhex?: unknown }).inches_to_subhex === "number"
          ? (bc as { inches_to_subhex: number }).inches_to_subhex
          : 10;
      const inchesToSubhex = Math.max(1, Math.floor(inchesToSubhexRaw));
      const chargeMaxSubhex = chargeMaxInches * inchesToSubhex;
      // Engagement Range en sous-hex (le moteur expose engagement_zone scalé, souvent 10 = 2").
      // Repli sur 2× inches_to_subhex si la config locale reste à 1 (même logique que BoardPvp).
      const ezRules = (
        this.props.gameState as
          | { config?: { game_rules?: { engagement_zone?: number } } }
          | undefined
      )?.config?.game_rules?.engagement_zone;
      const engagementSubhex =
        typeof ezRules === "number" && ezRules > 1 ? ezRules : inchesToSubhex * 2;
      // Distance figurine-la-plus-proche : empreinte union de chaque squad depuis les centres
      // de figs vivants (units_cache.occupied_hexes_by_model), pas l'ancre du squad.
      const unitsCacheForFootprint = this.props.gameState?.units_cache as
        | Record<string, { occupied_hexes_by_model?: Record<string, [number, number]> }>
        | undefined;
      const chargeMinRollOverlay =
        blinkPhase === "charge" && attacker
          ? buildChargeMinRollOverlay(
              minHexDistanceBetweenUnitFootprintsLive(
                attacker,
                unit,
                unitsCacheForFootprint?.[String(attacker.id)]?.occupied_hexes_by_model,
                unitsCacheForFootprint?.[String(unit.id)]?.occupied_hexes_by_model,
                chargeMaxSubhex
              ),
              chargeMaxInches,
              inchesToSubhex,
              engagementSubhex
            )
          : null;

      createBlinkingHPBar({
        unit,
        attacker,
        phase: blinkPhase,
        inCover: getEffectiveTargetInCover(attacker),
        onTooltip: this.props.onUnitTooltip,
        app: this.props.app,
        centerX: this.props.centerX,
        finalBarX,
        finalBarY,
        finalBarWidth,
        finalBarHeight,
        sliceWidth,
        getCSSColor: this.getCSSColor.bind(this),
        chargeMinRollOverlay,
        onBlinkProbHtml: this.props.onBlinkProbHtml,
        sliceHpCur: displayHP,
      });

      // If targetPreview has overallProbability, update the display (pas en phase charge : affichage jet 2D6)
      if (
        blinkPhase !== "charge" &&
        isTargetPreviewed &&
        targetPreview &&
        targetPreview.overallProbability !== undefined
      ) {
        const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;
        const showCoverShield = blinkPhase === "shoot" && getEffectiveTargetInCover(attacker);
        this.props.onBlinkProbHtml?.({
          action: "updateLabel",
          unitId: unitIdNum,
          label: `${Math.round(targetPreview.overallProbability * 100)}%`,
          showCoverShield,
          probabilityHelpText: DEFAULT_BLINK_PROBABILITY_HELP_TEXT,
        });
      }

      // Skip normal HP bar rendering when blinking
      return;
    } else {
      // Mode "par figurine" : chaque fig a sa propre barre (boucle multi-fig),
      // donc pas de barre squad unique.
      if (
        this.props.hpBarPerModel &&
        this.props.modelCenters &&
        this.props.modelCenters.length > 1
      ) {
        return;
      }
      // Défaut : une seule barre par escouade (comportement d'origine).
      this.drawStaticHpBar(displayHP, unit.HP_MAX, unitIconScale);
    }
  }

  /**
   * Barre HP statique (slices) dessinée à la position courante (this.props.centerX/Y)
   * en se basant sur this.props.unit pour la taille/forme de base. Réutilisée par la
   * barre squad agrégée et par les barres par-figurine (characters / mode hpBarPerModel).
   */
  private drawStaticHpBar(hpCur: number, hpMax: number, unitIconScale: number): void {
    if (!hpMax) return;
    const {
      unit,
      centerX,
      centerY,
      boardConfig,
      parseColor,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      HP_BAR_WIDTH_RATIO,
      HP_BAR_HEIGHT,
      UNIT_CIRCLE_RADIUS_RATIO,
    } = this.props;

    const nrHp = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    const hpDisplayBase = resolveBaseSizeForUnitDisplay(unit);
    const baseSizeVal = hpDisplayBase > 1 ? hpDisplayBase : 0;
    const tokenTop = getUnitTokenTopExtentY(
      unit,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      UNIT_CIRCLE_RADIUS_RATIO
    );
    const hpWidthBase = getHpBarWidthBase(unit, HEX_RADIUS, HEX_HORIZ_SPACING, unitIconScale);
    const barWidth =
      (baseSizeVal > 0 || nrHp ? hpWidthBase : HEX_RADIUS * unitIconScale) * HP_BAR_WIDTH_RATIO;
    const barX = centerX - barWidth / 2;
    const barY = centerY - tokenTop - HP_BAR_HEIGHT - 1;
    const displayHP = Math.max(0, hpCur);
    const sliceWidth = barWidth / hpMax;

    const barBg = new PIXI.Graphics();
    barBg.beginFill(0x222222, 1);
    const cornerRadius = Math.max(0.5, HP_BAR_HEIGHT * 0.3);
    const rawSlicePad = Math.max(0.3, HP_BAR_HEIGHT * 0.1);
    const slicePad = Math.min(rawSlicePad, sliceWidth * 0.15);
    barBg.drawRoundedRect(barX, barY, barWidth, HP_BAR_HEIGHT, cornerRadius);
    barBg.endFill();
    barBg.zIndex = 350;
    this.target.addChild(barBg);

    const hpDamagedColor =
      boardConfig &&
      typeof boardConfig === "object" &&
      "colors" in boardConfig &&
      boardConfig.colors &&
      typeof boardConfig.colors === "object" &&
      "hp_damaged" in boardConfig.colors
        ? (boardConfig.colors as { hp_damaged?: string }).hp_damaged
        : undefined;
    for (let i = 0; i < hpMax; i++) {
      const slice = new PIXI.Graphics();
      const color =
        i < displayHP
          ? unit.player === 1
            ? this.getCSSColor("--hp-bar-player1")
            : this.getCSSColor("--hp-bar-player2")
          : parseColor(hpDamagedColor || "#666666");
      slice.beginFill(color, 1);
      slice.drawRoundedRect(
        barX + i * sliceWidth + slicePad,
        barY + slicePad,
        sliceWidth - slicePad * 2,
        HP_BAR_HEIGHT - slicePad * 2,
        Math.max(0.5, cornerRadius * 0.7)
      );
      slice.endFill();
      slice.zIndex = 350;
      this.target.addChild(slice);
    }
  }

  private renderShootingCounter(unitIconScale: number): void {
    const { unit, centerX, centerY, phase, current_player, HEX_RADIUS, unitsFled, isEligible } =
      this.props;

    if (phase !== "shoot" || unit.player !== current_player) return;

    // NEW RULE: Hide shooting counter for units that fled
    if (unitsFled?.includes(unit.id)) {
      return;
    }

    // Show counter only for eligible units with shots remaining
    if (unit.SHOOT_LEFT === undefined || unit.SHOOT_LEFT <= 0) return;
    if (!isEligible) return;

    // Backend target pool is the source of truth for "can actually shoot now".
    // No implicit fallback: if pool is missing or empty, hide the shooting counter.
    const validTargetPool = unit.valid_target_pool;
    if (!Array.isArray(validTargetPool) || validTargetPool.length === 0) {
      return;
    }

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
      typeof unit.currentShootNb === "number" && unit.currentShootNb > 0
        ? `${unit.currentShootNb}`
        : typeof selectedRngWeapon.NB === "number"
          ? `${selectedRngWeapon.NB}`
          : selectedRngWeapon.NB;
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
    this.target.addChild(shootText);
  }

  private renderAdvanceButton(_unitIconScale: number, iconZIndex: number): void {
    const {
      unit,
      phase,
      current_player,
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
    if (this.props.mode === "advancePreview") return;

    // Only show icon when unit is actively activated (backend source of truth)
    const isActiveShooting =
      gameState?.active_shooting_unit && parseInt(gameState.active_shooting_unit, 10) === unit.id;
    if (!isActiveShooting) return;

    // Position: above HP bar (same calculation as renderHPBar)
    const { HEX_HORIZ_SPACING, UNIT_CIRCLE_RADIUS_RATIO } = this.props;
    const tokenTopAdv = getUnitTokenTopExtentY(
      unit,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      UNIT_CIRCLE_RADIUS_RATIO
    );
    const barY = centerY - tokenTopAdv - this.props.HP_BAR_HEIGHT - 1;
    const squareSizeRatio = this.getCSSNumber("--icon-square-standard-size", 0.5);
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const positionX = centerX;
    const positionY = barY - squareSize / 2 - Math.max(2, this.props.HP_BAR_HEIGHT * 0.7);

    // Get values from CSS variables for icon size
    const iconSize = this.getCSSNumber("--icon-advance-size", 1.5);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);
    /* Si la variable existe sur :root (App.css), la valeur CSS prime — le 2e argument n'est pas utilisé. */
    const iconBoost = this.getCSSNumber("--shooting-overlay-action-icon-boost", 1.45);

    // Load and create icon sprite (same pattern as renderActionIconInSquare, but without background square)
    const texture = PIXI.Texture.from("/icons/Action_Logo/3-5 - Advance.png");
    const iconSprite = new PIXI.Sprite(texture);
    iconSprite.anchor.set(0.5);
    iconSprite.position.set(positionX, positionY);
    const bc = this.props.boardConfig;
    const itsRawAdv =
      bc &&
      typeof bc === "object" &&
      "inches_to_subhex" in bc &&
      typeof (bc as { inches_to_subhex?: unknown }).inches_to_subhex === "number"
        ? (bc as { inches_to_subhex: number }).inches_to_subhex
        : 10;
    const iconScaleRatioAdv = itsRawAdv / 10;
    const iconDisplaySize = HEX_RADIUS * iconScaleRatioAdv * iconSize * iconScale * iconBoost;
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

    this.target.addChild(iconSprite);
  }

  private renderWeaponSelectionIcon(_unitIconScale: number, iconZIndex: number): void {
    const {
      unit,
      phase,
      current_player,
      centerX,
      centerY,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      UNIT_CIRCLE_RADIUS_RATIO,
      gameState,
    } = this.props;

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
    const availableWeapons = unit.available_weapons;

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
    const tokenTopWpn = getUnitTokenTopExtentY(
      unit,
      HEX_RADIUS,
      HEX_HORIZ_SPACING,
      UNIT_CIRCLE_RADIUS_RATIO
    );
    const barY = centerY - tokenTopWpn - this.props.HP_BAR_HEIGHT - 1;
    const squareSizeRatio = this.getCSSNumber("--icon-square-standard-size", 0.5);
    const squareSize = HEX_RADIUS * squareSizeRatio;
    const positionY = barY - squareSize / 2 - Math.max(2, this.props.HP_BAR_HEIGHT * 0.7);

    // Position X: to the right of Advance icon (centerX + spacing)
    const iconSize = this.getCSSNumber("--icon-advance-size", 1.5);
    const iconScale = this.getCSSNumber("--icon-square-icon-scale", 0.7);
    /* Si la variable existe sur :root (App.css), la valeur CSS prime — le 2e argument n'est pas utilisé. */
    const iconBoost = this.getCSSNumber("--shooting-overlay-action-icon-boost", 1.45);
    const bc = this.props.boardConfig;
    const itsRawWpn =
      bc &&
      typeof bc === "object" &&
      "inches_to_subhex" in bc &&
      typeof (bc as { inches_to_subhex?: unknown }).inches_to_subhex === "number"
        ? (bc as { inches_to_subhex: number }).inches_to_subhex
        : 10;
    const iconScaleRatioWpn = itsRawWpn / 10;
    const iconDisplaySize = HEX_RADIUS * iconScaleRatioWpn * iconSize * iconScale * iconBoost;
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

    this.target.addChild(iconSprite);
  }

  private renderAttackCounter(unitIconScale: number): void {
    const {
      unit,
      centerX,
      centerY,
      phase,
      HEX_RADIUS,
      unitsFled,
      units,
      mode,
      selectedUnitId,
      isEligible,
    } = this.props;

    // Attack counter shows for actively fighting units in fight phase
    if (phase !== "fight") return;
    if (unit.ATTACK_LEFT === undefined || unit.ATTACK_LEFT <= 0) return;

    // AI_TURN.md Lines 768, 777: ATTACK_LEFT visible during fight activation
    // Show counter for: (1) actively attacking unit (selectedUnitId in attackPreview)
    // OR (2) eligible units in their pool waiting to be activated
    const isActivelyAttacking = mode === "attackPreview" && selectedUnitId === unit.id;

    if (!isActivelyAttacking) {
      // Not actively attacking - check if eligible in current subphase pool
      let shouldShowIfEligible = false;

      // V11 : l'éligibilité (isEligible) reflète déjà le pool actionnable courant
      // (fight_eligible_units, tout joueur confondu) → le compteur suit isEligible.
      shouldShowIfEligible = true;

      if (!shouldShowIfEligible || !isEligible) return;
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
      typeof unit.currentFightNb === "number" && unit.currentFightNb > 0
        ? `${unit.currentFightNb}`
        : typeof selectedCcWeapon.NB === "number"
          ? `${selectedCcWeapon.NB}`
          : selectedCcWeapon.NB;
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
    this.target.addChild(attackText);
  }

  private renderHiddenBadge(unitIconScale: number): void {
    const { unit, centerX, centerY, app, HEX_RADIUS, uiElementsContainer } = this.props;
    const targetContainer = uiElementsContainer || app.stage;
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;

    // Clean up any existing hidden badge(s) for this unit (avoids stale duplicates across renders).
    if (uiElementsContainer) {
      const prefix = `hidden-badge-${unitIdNum}`;
      const existing = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) =>
          typeof child.name === "string" &&
          (child.name === prefix || child.name.startsWith(`${prefix}-`))
      );
      existing.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    const r = statusBadgeRadius(HEX_RADIUS);
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * 0.8;
    // Bottom-left of a figure (mirror of the bottom-right charge badge).
    const drawBadgeAt = (cx: number, cy: number, name: string, eyeColor?: number): void => {
      const badgeX = cx - scaledOffset;
      const badgeY = cy + scaledOffset;
      const g = new PIXI.Graphics();
      drawHiddenEyeBadge(g, badgeX, badgeY, r, eyeColor);
      g.name = name;
      g.zIndex = 10001;
      targetContainer.addChild(g);
    };

    if (this.props.statusBadgePerModel) {
      // Per-figure mode (rule 13.09) — one badge on each hidden figure (follows modelHidden).
      // Couleur relative au tireur actif : rouge si l'unité est cachée hors detection range
      // ("trop loin"), gris sinon (statut caché/couvert). Trop-loin = par unité → toutes ses figs.
      const centers = this.props.modelCenters;
      const flags = this.props.modelHidden;
      if (!centers || !flags) return;
      const eyeColor = this.getEffectiveTargetTooFar(this.getActiveAttacker())
        ? EYE_COLOR_TOO_FAR
        : undefined;
      centers.forEach(([cx, cy], i) => {
        if (flags[i]) drawBadgeAt(cx, cy, `hidden-badge-${unitIdNum}-${i}`, eyeColor);
      });
      return;
    }

    // Squad mode — œil relatif au tireur actif : rouge si l'ennemi est caché au-delà de la
    // detection range ("trop loin"), gris s'il est en couvert (ajusté arme). Mutuellement exclusifs
    // (le backend ne met une unité que dans un seul des deux maps). Sinon aucun badge.
    const attacker = this.getActiveAttacker();
    if (this.getEffectiveTargetTooFar(attacker)) {
      drawBadgeAt(centerX, centerY, `hidden-badge-${unitIdNum}`, EYE_COLOR_TOO_FAR);
      return;
    }
    if (this.getEffectiveTargetInCover(attacker)) {
      drawBadgeAt(centerX, centerY, `hidden-badge-${unitIdNum}`);
    }
  }

  /** Tireur actif (source de l'œil couvert/trop-loin), résolu comme dans render(). */
  private getActiveAttacker(): Unit | null {
    const attackerId =
      this.props.blinkingAttackerId ||
      this.props.gameState?.active_shooting_unit ||
      this.props.gameState?.active_fight_unit ||
      this.props.gameState?.active_charge_unit ||
      this.props.selectedUnitId;
    if (!attackerId) return null;
    const attackerIdNum = typeof attackerId === "string" ? parseInt(attackerId, 10) : attackerId;
    return (
      this.props.units.find((u) => {
        const idNum = typeof u.id === "string" ? parseInt(u.id, 10) : u.id;
        return idNum === attackerIdNum;
      }) || null
    );
  }

  /** Couvert effectif de cette unité-cible vis-à-vis du tireur (ajusté IGNORES_COVER). */
  private getEffectiveTargetInCover(attacker: Unit | null): boolean {
    if (!attacker) {
      return false;
    }
    const movePhaseLosHover =
      this.props.phase === "move" &&
      (this.props.mode === "select" || this.props.mode === "movePreview") &&
      this.props.movePreviewShootingTargetInCoverByUnitId !== undefined;
    if (this.props.phase !== "shoot" && this.props.mode !== "movePreview" && !movePhaseLosHover) {
      return false;
    }
    const selectedRangedWeapon = getSelectedRangedWeapon(attacker);
    const selectedWeaponIgnoresCover =
      Array.isArray(selectedRangedWeapon?.WEAPON_RULES) &&
      selectedRangedWeapon.WEAPON_RULES.some((rule) => rule === "IGNORES_COVER");
    if (selectedWeaponIgnoresCover) {
      return false;
    }
    if (
      (this.props.mode === "movePreview" ||
        this.props.mode === "select" ||
        this.props.mode === "attackPreview" ||
        this.props.mode === "squadModelShoot") &&
      this.props.movePreviewShootingTargetInCoverByUnitId
    ) {
      const key = String(this.props.unit.id);
      const map = this.props.movePreviewShootingTargetInCoverByUnitId;
      if (Object.hasOwn(map, key)) {
        return map[key] === true;
      }
    }
    return this.props.shootingTargetInCover === true;
  }

  /** "Trop loin" : cette unité-cible est cachée hors detection range du tireur (œil rouge).
   * Indépendant de l'arme (detection range, pas couvert) ; même gating de contexte que le couvert. */
  private getEffectiveTargetTooFar(attacker: Unit | null): boolean {
    if (!attacker) {
      return false;
    }
    const movePhaseLosHover =
      this.props.phase === "move" &&
      (this.props.mode === "select" ||
        this.props.mode === "movePreview" ||
        this.props.mode === "squadModelMove") &&
      this.props.movePreviewHiddenTooFarByUnitId !== undefined;
    if (this.props.phase !== "shoot" && this.props.mode !== "movePreview" && !movePhaseLosHover) {
      return false;
    }
    if (
      (this.props.mode === "movePreview" ||
        this.props.mode === "select" ||
        this.props.mode === "squadModelMove" ||
        this.props.mode === "attackPreview" ||
        this.props.mode === "squadModelShoot") &&
      this.props.movePreviewHiddenTooFarByUnitId
    ) {
      const key = String(this.props.unit.id);
      const map = this.props.movePreviewHiddenTooFarByUnitId;
      if (Object.hasOwn(map, key)) {
        return map[key] === true;
      }
    }
    return this.props.hiddenTooFar === true;
  }

  /**
   * Badge-statut de mouvement (bas-droite de la figurine) — une seule icône selon la priorité
   * charge > fall-back > advance > move > stationary. Remplace l'ancien badge "fui" vert.
   * Stationary n'est posé que sur les unités du joueur actif déjà sorties de la pool d'activation.
   */
  private renderMoveStatusBadge(unitIconScale: number): void {
    const {
      unit,
      centerX,
      centerY,
      app,
      HEX_RADIUS,
      unitsMoved,
      unitsCharged,
      unitsFled,
      unitsAdvanced,
      gameState,
      current_player,
      uiElementsContainer,
    } = this.props;
    const targetContainer = uiElementsContainer || app.stage;
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;

    // Nettoyage des badges-statut existants de cette unité (évite les doublons entre rendus).
    if (uiElementsContainer) {
      const prefix = `move-status-${unitIdNum}`;
      const existing = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) =>
          typeof child.name === "string" &&
          (child.name === prefix || child.name.startsWith(`${prefix}-`))
      );
      existing.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    // Sélection du statut par priorité.
    let kind: MoveStatusKind | null = null;
    if (unitsCharged?.includes(unit.id)) kind = "charge";
    else if (unitsFled?.includes(unit.id)) kind = "fallback";
    else if (unitsAdvanced?.includes(unit.id)) kind = "advance";
    else if (unitsMoved.includes(unit.id)) kind = "move";
    else if (
      unit.player === current_player &&
      !gameState?.move_activation_pool?.includes(String(unit.id))
    ) {
      kind = "stationary";
    }
    if (!kind) return;

    const r = statusBadgeRadius(HEX_RADIUS);
    const scaledOffset = ((HEX_RADIUS * unitIconScale) / 2) * 0.8;
    // Bas-droite de la figurine (emplacement de l'ancien badge "fui").
    const drawBadgeAt = (cx: number, cy: number, name: string): void => {
      const badgeX = cx + scaledOffset;
      const badgeY = cy + scaledOffset;
      const g = new PIXI.Graphics();
      drawMoveStatusBadge(g, badgeX, badgeY, r, kind!);
      g.name = name;
      g.zIndex = 10001;
      targetContainer.addChild(g);
    };

    if (this.props.statusBadgePerModel) {
      const centers = this.props.modelCenters;
      if (!centers) return;
      centers.forEach(([cx, cy], i) => {
        drawBadgeAt(cx, cy, `move-status-${unitIdNum}-${i}`);
      });
      return;
    }

    drawBadgeAt(centerX, centerY, `move-status-${unitIdNum}`);
  }

  private renderBattleShockedIndicator(): void {
    const {
      unit,
      centerX,
      centerY,
      HEX_RADIUS,
      UNIT_CIRCLE_RADIUS_RATIO,
      HEX_HORIZ_SPACING,
      app,
      uiElementsContainer,
    } = this.props;
    const targetContainer = uiElementsContainer || app.stage;
    const unitIdNum = typeof unit.id === "string" ? parseInt(unit.id, 10) : unit.id;

    if (uiElementsContainer) {
      const prefix = `battle-shocked-${unitIdNum}`;
      const existing = uiElementsContainer.children.filter(
        (child: PIXI.DisplayObject) =>
          typeof child.name === "string" && child.name.startsWith(prefix)
      );
      existing.forEach((child: PIXI.DisplayObject) => {
        uiElementsContainer.removeChild(child);
        if ("destroy" in child && typeof child.destroy === "function") child.destroy();
      });
    }

    if (!unit.battle_shocked) return;

    const drawAt = (posX: number, posY: number, emojiSize: number, name: string): void => {
      const r = emojiSize * 0.55;
      const g = new PIXI.Graphics();
      drawBattleShockBadge(g, posX, posY, r);
      g.name = name;
      g.zIndex = 10001;
      targetContainer.addChild(g);
    };

    // Rayon vertical de la base d'UNE figurine (même base pour toutes les figs de l'unité),
    // calculé en tenant compte de la BASE_SIZE réelle (pas du fallback UNIT_CIRCLE_RADIUS_RATIO).
    const nr = getNonRoundBasePixelLayout(unit, HEX_RADIUS);
    let bottomExtentY: number;
    if (nr) {
      bottomExtentY = nr.topExtentY;
    } else {
      const displayBase = resolveBaseSizeForUnitDisplay(unit);
      bottomExtentY =
        displayBase > 1
          ? (displayBase / 2) * HEX_HORIZ_SPACING
          : HEX_RADIUS * UNIT_CIRCLE_RADIUS_RATIO;
    }
    // Même rayon de fond que les autres badges-statut : le fond noir a un rayon de
    // emojiSize * 0.55, donc on dérive emojiSize pour que ce rayon == statusBadgeRadius.
    const emojiSize = statusBadgeRadius(HEX_RADIUS) / 0.55;

    if (this.props.statusBadgePerModel) {
      // Per-figure mode — one emoji centred-bottom of each living figure (unit-level status).
      const centers = this.props.modelCenters;
      if (!centers) return;
      centers.forEach(([cx, cy], i) => {
        drawAt(
          cx,
          cy + bottomExtentY - 0.25 * emojiSize,
          emojiSize,
          `battle-shocked-${unitIdNum}-${i}`
        );
      });
      return;
    }

    drawAt(
      centerX,
      centerY + bottomExtentY - 0.25 * emojiSize,
      emojiSize,
      `battle-shocked-${unitIdNum}`
    );
  }

  private renderUnitIdDebug(iconZIndex: number): void {
    const { unit, centerX, centerY, HEX_RADIUS, debugMode } = this.props;

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
    squareBg.zIndex = iconZIndex + 2000;
    this.target.addChild(squareBg);

    // Create text with unit ID
    const unitIdText = new PIXI.Text(String(unit.id), {
      fontSize: squareSize * 0.7,
      align: "center",
      fill: 0xffffff,
      fontWeight: "bold",
    });
    unitIdText.anchor.set(0.5);
    unitIdText.position.set(centerX, centerY);
    unitIdText.zIndex = iconZIndex + 2001;
    this.target.addChild(unitIdText);
  }
}

// Helper function to create and render a unit
export function renderUnit(props: UnitRendererProps): void {
  const renderer = new UnitRenderer(props);
  renderer.render();
}
