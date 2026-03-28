import type React from "react";
import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { getEventIcon } from "../../../shared/gameLogStructure";
import {
  getTutorialUiBehavior,
  TUTORIAL_UI_RUNTIME_CONFIG,
  type TutorialAfterCursorIconKey,
} from "../config/tutorialUiRules";
import type {
  TutorialLang,
  TutorialSpotlightCircle,
  TutorialSpotlightPosition,
  TutorialSpotlightRect,
  TutorialStepDisplay,
} from "../contexts/TutorialContext";

/** Fusionne les rects halo Name + M en un cadre englobant (viewport px). */
function unionTutorialSpotlightRects(rects: TutorialSpotlightRect[]): TutorialSpotlightRect | null {
  if (rects.length === 0) return null;
  const first = rects[0];
  let minL = first.left;
  let minT = first.top;
  let maxR = first.left + first.width;
  let maxB = first.top + first.height;
  for (let i = 1; i < rects.length; i++) {
    const r = rects[i];
    minL = Math.min(minL, r.left);
    minT = Math.min(minT, r.top);
    maxR = Math.max(maxR, r.left + r.width);
    maxB = Math.max(maxB, r.top + r.height);
  }
  return {
    shape: "rect",
    left: minL,
    top: minT,
    width: maxR - minL,
    height: maxB - minT,
  };
}

/** Path SVG (viewport moins trous des spotlights) pour bloquer les clics hors zones autorisées. */
function buildBlockingPath(
  width: number,
  height: number,
  spotlights: TutorialSpotlightPosition[]
): string {
  const viewport = `M 0 0 L ${width} 0 L ${width} ${height} L 0 ${height} Z`;
  if (spotlights.length === 0) return viewport;
  const holes = spotlights.map((s) => {
    if (s.shape === "circle") {
      const c = s as TutorialSpotlightCircle;
      const r = Math.max(0, (c.radius ?? 0) + 20);
      return `M ${c.x + r} ${c.y} A ${r} ${r} 0 1 1 ${c.x - r} ${c.y} A ${r} ${r} 0 1 1 ${c.x + r} ${c.y} Z`;
    }
    const r = s as TutorialSpotlightRect;
    const pad = 4;
    const left = r.left - pad;
    const top = r.top - pad;
    const w = r.width + pad * 2;
    const h = r.height + pad * 2;
    return `M ${left} ${top} L ${left + w} ${top} L ${left + w} ${top + h} L ${left} ${top + h} Z`;
  });
  return [viewport, ...holes].join(" ");
}

/**
 * Avec fill-rule="evenodd", un cercle (trou) entièrement contenu dans un rect (trou) réinverse
 * la zone centrale : le disque redevient « plein » et bloque les clics. On retire les cercles
 * dont le centre est déjà dans un rect trou pour permettre les clics sur tout le plateau.
 */
function filterCircleHolesContainedInRectHoles(
  holes: TutorialSpotlightPosition[]
): TutorialSpotlightPosition[] {
  const rects = holes.filter((h): h is TutorialSpotlightRect => h.shape === "rect");
  if (rects.length === 0) return holes;
  return holes.filter((h) => {
    if (h.shape !== "circle") return true;
    const c = h as TutorialSpotlightCircle;
    const cx = c.x;
    const cy = c.y;
    const insideSomeRect = rects.some((r) => {
      const pad = 4;
      const left = r.left - pad;
      const top = r.top - pad;
      const w = r.width + pad * 2;
      const h = r.height + pad * 2;
      return cx >= left && cx <= left + w && cy >= top && cy <= top + h;
    });
    return !insideSomeRect;
  });
}

interface TutorialOverlayProps {
  step: TutorialStepDisplay;
  lang: TutorialLang;
  onLangChange: (lang: TutorialLang) => void;
  onClose: () => void;
  onSkipTutorial?: () => void;
  /** Positions viewport (px) des halos : cercles ou rectangles non grisés (board, panneau). */
  spotlights?: TutorialSpotlightPosition[];
  /** Zones où les clics sont autorisés (trous dans la couche de blocage). Si absent, = spotlights. */
  allowedClickSpotlights?: TutorialSpotlightPosition[] | null;
  /** Rects viewport (px) des zones de fog sur le panneau gauche (étape 1-5 : 2 bandes, opacité réduite). */
  fogLeftPanelRects?: TutorialSpotlightRect[] | null;
  /** Rects viewport (px) des zones de fog sur le panneau droit (étape 2-11). */
  fogRightPanelRects?: TutorialSpotlightRect[] | null;
  /** Labels debug des spotlights (affichés seulement si fournis). */
  debugSpotlightLabels?: Array<{ id: string; position: TutorialSpotlightPosition }>;
  /** Étapes 1-11 / 1-12 / 1-13 : ancrage (bord droit du popup sur centre du bouton cible). */
  tutorialPopupAnchor?: { centerX: number; bottomY: number } | null;
  /** Halo panneau gauche (board) : repli 1-15 si halo Name+M indisponible. */
  panelLeftSpotlightForLayout?: TutorialSpotlightRect | null;
  /** 1-15 : rects halo colonnes Name + M (ligne Intercessor) — popup à gauche de ce bloc. */
  tableNameMSpotlightRectsForLayout?: TutorialSpotlightRect[] | null;
  /** 1-16 : halo section RANGED WEAPON(S) — centrage vertical ; bord gauche du popup au bord droit du plateau. */
  rangedWeaponsSpotlightRectsForLayout?: TutorialSpotlightRect[] | null;
}

/**
 * Modal d'étape du tutoriel : titre, corps, bouton Compris, optionnel Passer le tutoriel.
 * Accessibilité : focus trap, fermeture à Échap.
 */
/** Opacité des 2 bandes de fog sur le panneau gauche (étape 1-5), pour un rendu moins noir. */
const FOG_LEFT_PANEL_OPACITY = 0.5;

const MASK_ID = "tutorial-spotlight-mask";
const BLUR_FILTER_ID = "tutorial-spotlight-blur";
const FOG_BLUR_FILTER_ID = "tutorial-fog-blur";
const BLUR_EDGE = 8;
/** Marge autour du rect de fog pour que le flou ne soit pas coupé. */
const FOG_BLUR_MARGIN = 24;

/** Popups 1-11 / 1-12 / 1-13 : écart sous la bande / bouton cible (TurnPhaseTracker). */
const TUTORIAL_POPUP_TRACKER_ANCHOR_GAP_BELOW_PX = 20;

/** 1-14 : écart entre le bord droit du halo unité (board.activeUnit) et le bord gauche du popup (≈ demi-hex). */
const TUTORIAL_POPUP_1_14_GAP_RIGHT_OF_UNIT_HALO_PX = 24;

/** 1-15 (repli plateau) : écart entre le bord bas du popup et le haut du plateau. */
const TUTORIAL_POPUP_1_15_GAP_ABOVE_BOARD_TOP_PX = 12;
/** 1-15 (repli plateau) : hauteur max estimée du dialog si ancrage tableau indisponible. */
const TUTORIAL_POPUP_1_15_MAX_HEIGHT_ESTIMATE_PX = 420;
/** 1-15 : écart entre le bord droit du popup et le bord gauche du halo Name/M (plus grand = popup plus à gauche). */
const TUTORIAL_POPUP_1_15_GAP_LEFT_OF_NAME_M_ROW_PX = 48;
/** 1-15 : décalage vertical vers le bas par rapport au centre du halo Name/M. */
const TUTORIAL_POPUP_1_15_SHIFT_DOWN_PX = 100;

/** 1-16 : écart entre le bord gauche du popup et le bord droit du halo plateau (panel.left). */
const TUTORIAL_POPUP_1_16_GAP_AFTER_BOARD_RIGHT_PX = -100;
/** 1-16 : décalage vertical (px) sous le centre du halo armes à distance. */
const TUTORIAL_POPUP_1_16_SHIFT_DOWN_PX = 300;

/** Marge (px) entre le bord du popup tutoriel et les bords du viewport (clamp général). */
const TUTORIAL_DIALOG_VIEWPORT_MARGIN_PX = 8;
/**
 * 1-14 : demi-hauteur estimée (px) pour borner le `top` avec translateY(-50%) et éviter de couper le bas.
 * Complété par le clamp viewport JS sur le dialog.
 */
const TUTORIAL_POPUP_1_14_VERTICAL_CENTER_CLAMP_HALF_EST_PX = 240;

/** Logos des phases (frontend/public/icons/Action_Logo) affichés à gauche du titre. */
const PHASE_LOGO: Record<string, string> = {
  move: "/icons/Action_Logo/2 - Movemement.png",
  shoot: "/icons/Action_Logo/3 - Shooting.png",
  shooting: "/icons/Action_Logo/3 - Shooting.png",
  charge: "/icons/Action_Logo/4 - Charge.png",
  fight: "/icons/Action_Logo/5 - Fight.png",
};

const TERMAGANT_ICON_PATH = "/icons/Termagant_red.webp";
const INTERCESSOR_ICON_PATH = "/icons/Intercessor.webp";
const CURSOR_POINTER_ICON_PATH = "/icons/Cursor.png";
const WEAPON_MENU_ICON_PATH = "/icons/weapon_menu_icon.png";

/** Mini icônes entre le curseur et le texte (étapes 1-14, 1-15, 1-16, 1-21, 1-22, 1-24). */
const MINI_ICON_CLASS = "tutorial-overlay-dialog__mini-icon";
function MiniIntercessorIcon(): React.ReactElement {
  return (
    <img
      src={INTERCESSOR_ICON_PATH}
      alt=""
      className={MINI_ICON_CLASS}
      aria-hidden
    />
  );
}
/** Mini Intercessor avec cercle vert (étape 1-21). */
function MiniIntercessorIconWithGreenCircle(): React.ReactElement {
  return (
    <span className="tutorial-overlay-dialog__mini-icon-with-green-circle" aria-hidden>
      <svg
        className="tutorial-overlay-dialog__mini-green-activation-circle"
        viewBox="0 0 32 32"
        aria-hidden
      >
        <title>Cercle vert unité activable</title>
        <circle
          cx="16"
          cy="16"
          r="14"
          fill="none"
          stroke="#00ff00"
          strokeWidth="2"
          strokeOpacity="0.8"
        />
      </svg>
      <img
        src={INTERCESSOR_ICON_PATH}
        alt=""
        className={MINI_ICON_CLASS}
        aria-hidden
      />
    </span>
  );
}
function MiniHexIcon(): React.ReactElement {
  return (
    <svg
      className={MINI_ICON_CLASS}
      viewBox="0 0 50 50"
      aria-hidden
      role="img"
      style={{ verticalAlign: "middle", margin: "0 4px" }}
    >
      <title>Hex destination</title>
      <polygon
        points={[0, 60, 120, 180, 240, 300]
          .map((deg) => {
            const rad = (deg * Math.PI) / 180;
            return `${25 + 20 * Math.cos(rad)},${25 + 20 * Math.sin(rad)}`;
          })
          .join(" ")}
        fill="rgba(144, 208, 144, 0.5)"
        stroke="#00aa00"
        strokeWidth="1.2"
      />
    </svg>
  );
}
function MiniWeaponMenuIcon(): React.ReactElement {
  return (
    <img
      src={WEAPON_MENU_ICON_PATH}
      alt=""
      className={MINI_ICON_CLASS}
      aria-hidden
    />
  );
}
function MiniTermagantIcon(): React.ReactElement {
  return (
    <img
      src={TERMAGANT_ICON_PATH}
      alt=""
      className={MINI_ICON_CLASS}
      aria-hidden
    />
  );
}

function resolveDefaultAfterCursorIcon(stepStage: string): TutorialAfterCursorIconKey | null {
  // No implicit icon by stage: icon display must be explicit in YAML.
  void stepStage;
  return null;
}

function renderAfterCursorIcon(iconKey: TutorialAfterCursorIconKey | null): React.ReactNode {
  if (iconKey === null) return null;
  switch (iconKey) {
    case "intercessor":
      return <MiniIntercessorIcon />;
    case "intercessorGreen":
      return <MiniIntercessorIconWithGreenCircle />;
    case "hex":
      return <MiniHexIcon />;
    case "weaponMenu":
      return <MiniWeaponMenuIcon />;
    case "termagant":
      return <MiniTermagantIcon />;
    default:
      throw new Error(`Unknown after cursor icon key: ${String(iconKey)}`);
  }
}
/** Icône Termagant en fantôme (étape 1-25 : unité morte). */
function TermagantGhostIcon(): React.ReactElement {
  return (
    <img
      src={TERMAGANT_ICON_PATH}
      alt=""
      className="tutorial-overlay-dialog__termagant-ghost-icon"
      aria-hidden
    />
  );
}

/** Ligne commençant par Cliquez ou Clickez (optionnellement après espaces). */
const CLICK_LINE_RE = /^\s*(Cliquez|Clickez)/i;

/** Composant icône pointeur réutilisable (placeholder <cursor> ou début de ligne Cliquez). */
function CursorIcon(): React.ReactElement {
  return (
    <img
      src={CURSOR_POINTER_ICON_PATH}
      alt=""
      className="tutorial-overlay-dialog__click-icon"
      aria-hidden
    />
  );
}

/**
 * Rendu du corps avec icône pointeur :
 * - Placeholder <cursor> dans le texte → icône à cet endroit (+ optionnel afterCursor entre curseur et texte).
 * - Sinon, ligne qui commence par "Cliquez" / "Clickez" → icône en début de ligne.
 */
function renderBodyWithClickIcon(
  body: string,
  options?: { afterCursor?: React.ReactNode }
): React.ReactNode {
  const afterCursor = options?.afterCursor ?? null;
  const lines = body.split("\n");
  if (lines.length === 0) return <p>{body}</p>;
  return (
    <p className="tutorial-overlay-dialog__body-paragraph" style={{ whiteSpace: "pre-wrap" }}>
      {lines.map((line, i) => {
        const hasPlaceholder = line.includes("<cursor>");
        const parts = line.split("<cursor>");
        const showIconAtStart = !hasPlaceholder && CLICK_LINE_RE.test(line);
        return (
          <span key={line ? `click-${line.slice(0, 40)}-${i}` : `click-empty-${i}`}>
            {showIconAtStart && (
              <>
                <CursorIcon />
                {afterCursor}
                {" "}
              </>
            )}
            {hasPlaceholder
              ? parts.map((part, j) => (
                  <span key={`part-${i}-${part.slice(0, 20)}-${j}`}>
                    {replaceCursorInText(part)}
                    {j < parts.length - 1 && (
                      <>
                        <CursorIcon />
                        {afterCursor}
                        {" "}
                      </>
                    )}
                  </span>
                ))
              : replaceCursorInText(line)}
            {i < lines.length - 1 ? "\n" : ""}
          </span>
        );
      })}
    </p>
  );
}

/** Regex : ligne commençant par <Range>, <A>, <BS>, <S>, <AP> ou <DMG> puis la description. */
const WEAPON_ATTR_LINE_RE = /^<(Range|A|BS|S|AP|DMG)>\s*(.*)$/;

/**
 * Rendu du corps pour l'étape 2-2 / 1-23 : intro, tableau 2 colonnes (attributs), puis texte de fin (optionnel afterCursor et Bolt Rifle en gras pour 1-23).
 */
function renderBodyWithWeaponAttrTooltips(
  body: string,
  options?: { afterCursor?: React.ReactNode; boltRifleBold?: boolean }
): React.ReactNode {
  const { afterCursor, boltRifleBold } = options ?? {};
  const lines = body.split("\n");
  const intro: string[] = [];
  const attrRows: { attrName: string; description: string }[] = [];
  const trailing: string[] = [];
  let phase: "intro" | "attrs" | "trailing" = "intro";
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = line.match(WEAPON_ATTR_LINE_RE);
    if (m !== null) {
      if (phase === "intro") phase = "attrs";
      attrRows.push({ attrName: m[1], description: m[2].trim() });
    } else {
      if (phase === "attrs") phase = "trailing";
      if (phase === "intro") intro.push(line);
      else trailing.push(line);
    }
  }
  return (
    <div className="tutorial-overlay-dialog__body-paragraph">
      {intro.length > 0 && (
        <p
          className="tutorial-overlay-dialog__weapon-attr-intro"
          style={{ whiteSpace: "pre-wrap" }}
        >
          {replaceCursorInText(intro.join("\n"))}
        </p>
      )}
      {attrRows.length > 0 && (
        <div className="tutorial-overlay-dialog__weapon-attr-cols">
          <div className="tutorial-overlay-dialog__weapon-attr-col tutorial-overlay-dialog__weapon-attr-col--left">
            {attrRows.map(({ attrName }) => (
              <div key={attrName} className="tutorial-overlay-dialog__weapon-attr-cell">
                <span className="tutorial-overlay-dialog__weapon-attr-badge">{attrName}</span>
              </div>
            ))}
          </div>
          <div className="tutorial-overlay-dialog__weapon-attr-col tutorial-overlay-dialog__weapon-attr-col--right">
            {attrRows.map(({ attrName, description }) => (
              <div
                key={attrName}
                className="tutorial-overlay-dialog__weapon-attr-cell tutorial-overlay-dialog__weapon-attr-desc"
              >
                {description}
              </div>
            ))}
          </div>
        </div>
      )}
      {trailing.length > 0 && (
        <p
          className="tutorial-overlay-dialog__weapon-attr-trailing"
          style={{ whiteSpace: "pre-wrap" }}
        >
          {replaceCursorInText(trailing.join("\n"), { afterCursor, boltRifleBold })}
        </p>
      )}
    </div>
  );
}

/** Points du polygone hexagone (même format que l’hex vert 1-5) : centre 25,25, rayon 20. */
const HEX_POINTS = [0, 60, 120, 180, 240, 300]
  .map((deg) => {
    const rad = (deg * Math.PI) / 180;
    const x = 25 + 20 * Math.cos(rad);
    const y = 25 + 20 * Math.sin(rad);
    return `${x},${y}`;
  })
  .join(" ");

/** Remplace les placeholders <icone mort> / <death icon> par l’icône mort du game log (même ligne, étape 1-25). Option ghostTermagant : affiche une icône fantôme du Termagant avant la première icône mort. */
function replaceDeathIconInText(
  text: string,
  options?: { ghostTermagant?: boolean }
): React.ReactNode {
  const deathIcon = getEventIcon("death");
  const showGhostTermagant = options?.ghostTermagant === true;
  const re = /<icone mort>|<death icon>/gi;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let firstDeathIcon = true;
  let m = re.exec(text);
  while (m !== null) {
    if (m.index > lastIndex) {
      parts.push(
        <Fragment key={`death-text-${lastIndex}`}>
          {replaceCursorInText(text.slice(lastIndex, m.index))}
        </Fragment>
      );
    }
    parts.push(
      <span
        key={`death-icon-${m.index}`}
        className="tutorial-overlay-dialog__death-icon-inline"
        aria-hidden
      >
        {showGhostTermagant && firstDeathIcon ? (
          <>
            <TermagantGhostIcon />
            {deathIcon}
          </>
        ) : (
          deathIcon
        )}
      </span>
    );
    firstDeathIcon = false;
    lastIndex = re.lastIndex;
    m = re.exec(text);
  }
  if (parts.length === 0) return replaceCursorInText(text);
  if (lastIndex < text.length) {
    parts.push(
      <Fragment key={`death-text-tail-${lastIndex}`}>
        {replaceCursorInText(text.slice(lastIndex))}
      </Fragment>
    );
  }
  return <>{parts}</>;
}

/** Optionnel : mettre "Bolt Rifle" en gras et blanc (étape 1-23). */
function highlightBoltRifleInSegment(seg: string): React.ReactNode {
  if (!seg.includes("Bolt Rifle")) return seg;
  const parts = seg.split(/(Bolt Rifle)/g);
  return (
    <>
      {parts.map((p, i) =>
        p === "Bolt Rifle" ? (
          <strong key={`bolt-rifle-${i}-${p}`} className="tutorial-overlay-dialog__bolt-rifle">
            Bolt Rifle
          </strong>
        ) : (
          <Fragment key={`seg-${i}-${String(p).slice(0, 8)}`}>{p}</Fragment>
        )
      )}
    </>
  );
}

function highlightBoundingLeapInSegment(seg: string): React.ReactNode {
  if (!seg.includes("Bounding Leap")) return seg;
  const parts = seg.split(/(Bounding Leap)/g);
  return (
    <>
      {parts.map((p, i) =>
        p === "Bounding Leap" ? (
          <span
            key={`bounding-leap-${i}-${p}`}
            className="rule-tooltip tutorial-overlay-dialog__inline-rule-tooltip"
          >
            Bounding Leap
          </span>
        ) : (
          <Fragment key={`bound-seg-${i}-${String(p).slice(0, 8)}`}>{p}</Fragment>
        )
      )}
    </>
  );
}

/** Remplace les occurrences de <cursor> dans un texte par l'icône pointeur (+ optionnel afterCursor entre curseur et texte ; optionnel boltRifleBold pour 1-23). */
function replaceCursorInText(
  text: string,
  options?: { afterCursor?: React.ReactNode; boltRifleBold?: boolean }
): React.ReactNode {
  const afterCursor = options?.afterCursor;
  const boltRifleBold = options?.boltRifleBold === true;
  const renderTextDecorators = (seg: string): React.ReactNode => {
    const withBolt = boltRifleBold ? highlightBoltRifleInSegment(seg) : seg;
    if (typeof withBolt === "string") {
      return highlightBoundingLeapInSegment(withBolt);
    }
    return withBolt;
  };
  const renderSegment = (seg: string): React.ReactNode => {
    if (!seg.includes("<icon:")) {
      return renderTextDecorators(seg);
    }
    const parts = seg.split(/(<icon:[^>]+>)/g);
    const keyCounts: Record<string, number> = {};
    const nextKey = (base: string): string => {
      const n = (keyCounts[base] ?? 0) + 1;
      keyCounts[base] = n;
      return `${base}-${n}`;
    };
    return (
      <>
        {parts.map((part) => {
          const m = part.match(/^<icon:\s*([^>]+)\s*>$/);
          if (m != null) {
            const src = m[1].trim();
            if (src === "") {
              throw new Error("Invalid empty inline icon source in tutorial body");
            }
            return (
              <img
                key={nextKey(`inline-icon-${src}`)}
                src={src}
                alt=""
                className={MINI_ICON_CLASS}
                aria-hidden
              />
            );
          }
          return <Fragment key={nextKey(`inline-text-${part}`)}>{renderTextDecorators(part)}</Fragment>;
        })}
      </>
    );
  };
  if (!text.includes("<cursor>")) {
    return renderSegment(text);
  }
  const segments = text.split("<cursor>");
  return (
    <>
      {segments.map((seg, k) => (
        <span key={seg ? `cursor-${k}-${seg.slice(0, 15)}` : `cursor-${k}`}>
          {renderSegment(seg)}
          {k < segments.length - 1 && (
            <>
              <CursorIcon />
              {afterCursor ?? null}
              {" "}
            </>
          )}
        </span>
      ))}
    </>
  );
}

function renderBodyWithLosPlaceholders(
  body: string,
  lang: "fr" | "en",
  options?: { afterCursor?: React.ReactNode }
): React.ReactNode {
  const afterCursor = options?.afterCursor;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  const re =
    /(<Hex bleu foncé>|<Dark blue hex>|<Hex bleu clair>|<Light blue hex>|<icone termagant>|<Termagant icon>)/g;
  let m = re.exec(body);
  while (m !== null) {
    if (m.index > lastIndex) {
      parts.push(
        <Fragment key={`text-${lastIndex}`}>
          {replaceCursorInText(body.slice(lastIndex, m.index), { afterCursor })}
        </Fragment>
      );
    }
    const tag = m[1] ?? m[0];
    if (tag.includes("termagant") || tag.includes("Termagant icon")) {
      parts.push(
        <span key={`termagant-${m.index}`} aria-hidden>
          <img
            src={TERMAGANT_ICON_PATH}
            alt=""
            className={MINI_ICON_CLASS}
            aria-hidden
          />
        </span>
      );
    } else if (tag.includes("foncé") || tag.includes("Dark blue")) {
      parts.push(
        <span key={`dark-${m.index}`} aria-hidden>
          <svg
            className="tutorial-overlay-dialog__los-hex"
            viewBox="0 0 50 50"
            aria-hidden
            role="img"
          >
            <title>{lang === "fr" ? "Vue directe" : "Direct view"}</title>
            <polygon
              points={HEX_POINTS}
              fill="rgba(79, 139, 255, 0.5)"
              stroke="#4f8bff"
              strokeWidth="1.2"
            />
          </svg>
        </span>
      );
    } else {
      parts.push(
        <span key={`cover-${m.index}`} aria-hidden>
          <svg
            className="tutorial-overlay-dialog__los-hex"
            viewBox="0 0 50 50"
            aria-hidden
            role="img"
          >
            <title>{lang === "fr" ? "Vue partielle (couvert)" : "Partial view (cover)"}</title>
            <polygon
              points={HEX_POINTS}
              fill="rgba(158, 197, 255, 0.5)"
              stroke="#9ec5ff"
              strokeWidth="1.2"
            />
          </svg>
        </span>
      );
    }
    lastIndex = re.lastIndex;
    m = re.exec(body);
  }
  if (lastIndex < body.length) {
    parts.push(
      <Fragment key={`text-tail-${lastIndex}`}>
        {replaceCursorInText(body.slice(lastIndex), { afterCursor })}
      </Fragment>
    );
  }
  return parts.length > 1 ? parts : (parts[0] ?? replaceCursorInText(body, { afterCursor }));
}

/** Ajoute une translation de correction pour garder le dialog dans le viewport (après positionnement de base). */
function mergeTutorialDialogViewportTransform(
  style: React.CSSProperties,
  nudge: { x: number; y: number }
): React.CSSProperties {
  if (nudge.x === 0 && nudge.y === 0) return style;
  const t = style.transform;
  const baseT = !t || t === "none" ? "" : String(t);
  const extra = `translate(${nudge.x}px, ${nudge.y}px)`;
  return { ...style, transform: baseT ? `${baseT} ${extra}` : extra };
}

export const TutorialOverlay: React.FC<TutorialOverlayProps> = ({
  step,
  lang,
  onLangChange,
  onClose,
  onSkipTutorial,
  spotlights = [],
  allowedClickSpotlights = null,
  fogLeftPanelRects = [],
  fogRightPanelRects = [],
  debugSpotlightLabels = [],
  tutorialPopupAnchor = null,
  panelLeftSpotlightForLayout = null,
  tableNameMSpotlightRectsForLayout = null,
  rangedWeaponsSpotlightRectsForLayout = null,
}) => {
  const clickHoles = allowedClickSpotlights ?? spotlights;
  const title = lang === "fr" ? step.title_fr : step.title_en;
  const body = lang === "fr" ? step.body_fr : step.body_en;
  const uiBehavior = getTutorialUiBehavior(step.stage);
  const defaultAfterCursorIcon = resolveDefaultAfterCursorIcon(step.stage);
  const effectiveAfterCursorIcon =
    uiBehavior.afterCursorIcon === undefined ? defaultAfterCursorIcon : uiBehavior.afterCursorIcon;
  const popupImageGhostClass = uiBehavior.popupImageGhost === true ? " tutorial-overlay-dialog__popup-image--ghost" : "";
  const backdropOpacity =
    step.fog.global === true
      ? (uiBehavior.overlayBackdropOpacity ?? TUTORIAL_UI_RUNTIME_CONFIG.fogBackdropOpacity)
      : 0;
  const titleIconSrc =
    typeof step.titleIcon === "string" && step.titleIcon.trim() !== ""
      ? step.titleIcon
      : step.phase && PHASE_LOGO[step.phase]
        ? PHASE_LOGO[step.phase]
        : null;
  const afterCursorIcon = useMemo(() => {
    return renderAfterCursorIcon(effectiveAfterCursorIcon);
  }, [effectiveAfterCursorIcon]);
  const bodyContent =
    step.stage === "1-16" || step.stage === "1-22" || step.stage === "2-2"
      ? renderBodyWithLosPlaceholders(body, lang, { afterCursor: afterCursorIcon })
      : step.stage === "1-23" || step.stage === "2-3"
        ? renderBodyWithWeaponAttrTooltips(body, {
            afterCursor: afterCursorIcon,
            boltRifleBold: step.stage === "1-23",
          })
        : step.stage === "1-25"
          ? replaceDeathIconInText(body, { ghostTermagant: false })
          : renderBodyWithClickIcon(body, { afterCursor: afterCursorIcon });
  const isStepIconAndFirstLine = step.popupFirstLineWithIcon === true;
  const bodyFirstLineIcon = isStepIconAndFirstLine ? (body.split("\n")[0] ?? "") : "";
  const bodyRestIcon = isStepIconAndFirstLine ? body.split("\n").slice(1).join("\n") : "";
  const bodyContentRestIcon =
    isStepIconAndFirstLine
      ? renderBodyWithClickIcon(bodyRestIcon, { afterCursor: afterCursorIcon })
      : null;
  const isStep1_5 = step.stage === "1-15";
  const bodyFirstLine1_5 = isStep1_5 ? (body.split("\n")[0] ?? "") : "";
  const bodyRest1_5 = isStep1_5 ? body.split("\n").slice(1).join("\n") : "";
  const bodyContentRest1_5 =
    isStep1_5
      ? renderBodyWithClickIcon(bodyRest1_5, { afterCursor: afterCursorIcon })
      : null;
  const showIllustrationBlock =
    uiBehavior.hidePopupIllustrationBlock === true
      ? false
      : Boolean(step.popupImage || step.popupShowMoveHex || step.popupShowGreenCircle);
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [overlayRect, setOverlayRect] = useState<DOMRect | null>(null);
  const [dialogPosition, setDialogPosition] = useState<{ x: number; y: number } | null>(null);
  const [viewportInsetNudge, setViewportInsetNudge] = useState({ x: 0, y: 0 });
  const dragStartRef = useRef<{
    mouseX: number;
    mouseY: number;
    dialogX: number;
    dialogY: number;
  } | null>(null);

  // Coordonnées viewport : on utilise (0,0) + taille fenêtre pour que les spotlights (déjà en viewport)
  // soient corrects même si l’overlay était rendu dans un ancêtre avec transform. Rendu dans body via Portal.
  useLayoutEffect(() => {
    const update = () =>
      setOverlayRect(
        new DOMRect(
          0,
          0,
          document.documentElement.clientWidth,
          document.documentElement.clientHeight
        )
      );
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Masque SVG : coordonnées viewport (overlay en portal = (0,0) → viewport)
  const svgMask =
    spotlights.length > 0 && overlayRect ? (
      <svg
        aria-hidden
        role="img"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
        }}
        width="100%"
        height="100%"
        viewBox={`0 0 ${overlayRect.width} ${overlayRect.height}`}
        preserveAspectRatio="none"
      >
        <title>Masque tutoriel</title>
        <defs>
          <filter id={BLUR_FILTER_ID}>
            <feGaussianBlur in="SourceGraphic" stdDeviation={BLUR_EDGE} />
          </filter>
          <mask id={MASK_ID}>
            <rect x="0" y="0" width={overlayRect.width} height={overlayRect.height} fill="white" />
            <g filter={`url(#${BLUR_FILTER_ID})`}>
              {spotlights.map((s, idx) => {
                if (s.shape === "circle") {
                  const c = s as TutorialSpotlightCircle;
                  const r = c.radius + 20;
                  return (
                    <circle
                      key={`circle-${c.x}-${c.y}-${idx}`}
                      cx={c.x}
                      cy={c.y}
                      r={r}
                      fill="black"
                    />
                  );
                }
                const r = s as TutorialSpotlightRect;
                const pad = 4;
                return (
                  <rect
                    key={`rect-${r.left}-${r.top}-${idx}`}
                    x={r.left - pad}
                    y={r.top - pad}
                    width={r.width + pad * 2}
                    height={r.height + pad * 2}
                    fill="black"
                  />
                );
              })}
            </g>
          </mask>
        </defs>
      </svg>
    ) : null;

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  useEffect(() => {
    setDialogPosition(null);
  }, [step.stage]);

  const tutorialLayoutDepsKey = useMemo(() => {
    const spotlightSig = spotlights
      .map((s) => {
        if (s.shape === "circle") {
          const c = s as TutorialSpotlightCircle;
          return `circle:${c.x},${c.y},${c.radius}`;
        }
        const r = s as TutorialSpotlightRect;
        return `rect:${r.left},${r.top},${r.width},${r.height}`;
      })
      .join("|");
    const tableSig =
      tableNameMSpotlightRectsForLayout != null
        ? tableNameMSpotlightRectsForLayout
            .map((r) => `${r.left},${r.top},${r.width},${r.height}`)
            .join(";")
        : "";
    const rangedSig =
      rangedWeaponsSpotlightRectsForLayout != null
        ? rangedWeaponsSpotlightRectsForLayout
            .map((r) => `${r.left},${r.top},${r.width},${r.height}`)
            .join(";")
        : "";
    const panelSig =
      panelLeftSpotlightForLayout != null
        ? `${panelLeftSpotlightForLayout.left},${panelLeftSpotlightForLayout.top},${panelLeftSpotlightForLayout.width},${panelLeftSpotlightForLayout.height}`
        : "";
    const anchorSig =
      tutorialPopupAnchor != null &&
      typeof tutorialPopupAnchor.centerX === "number" &&
      typeof tutorialPopupAnchor.bottomY === "number"
        ? `${tutorialPopupAnchor.centerX},${tutorialPopupAnchor.bottomY}`
        : "";
    const popupPosSig =
      step.popupPosition && step.popupPosition !== "center" && typeof step.popupPosition === "object"
        ? JSON.stringify(step.popupPosition)
        : String(step.popupPosition ?? "");
    return [
      step.stage,
      dialogPosition?.x ?? "x",
      dialogPosition?.y ?? "y",
      anchorSig,
      panelSig,
      tableSig,
      rangedSig,
      spotlightSig,
      popupPosSig,
    ].join("::");
  }, [
    step.stage,
    dialogPosition,
    tutorialPopupAnchor,
    panelLeftSpotlightForLayout,
    tableNameMSpotlightRectsForLayout,
    rangedWeaponsSpotlightRectsForLayout,
    spotlights,
    step.popupPosition,
  ]);

  const clampDialogToViewport = useCallback(() => {
    const el = dialogRef.current;
    if (!el) return;
    const margin = TUTORIAL_DIALOG_VIEWPORT_MARGIN_PX;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let dx = 0;
    let dy = 0;
    if (rect.left < margin) dx = margin - rect.left;
    else if (rect.right > vw - margin) dx = vw - margin - rect.right;
    if (rect.top < margin) dy = margin - rect.top;
    else if (rect.bottom > vh - margin) dy = vh - margin - rect.bottom;
    setViewportInsetNudge((prev) =>
      prev.x === dx && prev.y === dy ? prev : { x: dx, y: dy }
    );
  }, []);

  useLayoutEffect(() => {
    // Pas de flushSync ici : il déclenchait « flushSync was called from inside a lifecycle method »
    // et pouvait perturber le batching React pendant le rendu parent (TutorialProvider).
    setViewportInsetNudge({ x: 0, y: 0 });
    clampDialogToViewport();
    const el = dialogRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      clampDialogToViewport();
    });
    ro.observe(el);
    window.addEventListener("resize", clampDialogToViewport);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", clampDialogToViewport);
    };
  }, [tutorialLayoutDepsKey, clampDialogToViewport]);

  const dialogStyle = ((): React.CSSProperties => {
    const base: React.CSSProperties = {
      position: "absolute",
      zIndex: 1,
      pointerEvents: "auto",
      padding: "24px",
      minWidth: "320px",
      maxWidth: "520px",
    };
    const toCss = (v: string | number): string => (typeof v === "number" ? `${v}px` : v);
    if (dialogPosition !== null) {
      return {
        ...base,
        left: dialogPosition.x,
        top: dialogPosition.y,
        transform: "none",
      };
    }
    if (
      (step.stage === "1-11" || step.stage === "1-12" || step.stage === "1-13") &&
      tutorialPopupAnchor != null &&
      typeof tutorialPopupAnchor.centerX === "number" &&
      typeof tutorialPopupAnchor.bottomY === "number"
    ) {
      return {
        ...base,
        left: tutorialPopupAnchor.centerX,
        top: tutorialPopupAnchor.bottomY + TUTORIAL_POPUP_TRACKER_ANCHOR_GAP_BELOW_PX,
        transform: "translateX(-100%)",
      };
    }
    if (step.stage === "1-14" || step.stage === "1-21") {
      const unitCircle = spotlights.find((s): s is TutorialSpotlightCircle => s.shape === "circle");
      if (unitCircle != null) {
        const margin = TUTORIAL_DIALOG_VIEWPORT_MARGIN_PX;
        const vh = typeof window !== "undefined" ? window.innerHeight : 900;
        const halfEst = TUTORIAL_POPUP_1_14_VERTICAL_CENTER_CLAMP_HALF_EST_PX;
        const minTop = margin + halfEst;
        const maxTop = vh - margin - halfEst;
        const topY =
          Number.isFinite(minTop) && Number.isFinite(maxTop) && maxTop >= minTop
            ? Math.max(minTop, Math.min(unitCircle.y, maxTop))
            : unitCircle.y;
        return {
          ...base,
          position: "fixed",
          left: unitCircle.x + unitCircle.radius + TUTORIAL_POPUP_1_14_GAP_RIGHT_OF_UNIT_HALO_PX,
          top: topY,
          transform: "translateY(-50%)",
        };
      }
    }
    if (step.stage === "1-15") {
      const tableRects = tableNameMSpotlightRectsForLayout;
      if (tableRects != null && tableRects.length > 0) {
        const union = unionTutorialSpotlightRects(tableRects);
        if (
          union != null &&
          union.width >= 2 &&
          union.height >= 2 &&
          Number.isFinite(union.left) &&
          Number.isFinite(union.top)
        ) {
          const leftAnchor = union.left - TUTORIAL_POPUP_1_15_GAP_LEFT_OF_NAME_M_ROW_PX;
          const topCenter =
            union.top + union.height / 2 + TUTORIAL_POPUP_1_15_SHIFT_DOWN_PX;
          return {
            ...base,
            position: "fixed",
            left: leftAnchor,
            top: topCenter,
            transform: "translate(-100%, -50%)",
          };
        }
      }
      if (panelLeftSpotlightForLayout != null) {
        const r = panelLeftSpotlightForLayout;
        if (r.width >= 2 && r.height >= 2) {
          let fullBoardTop =
            step.fog.leftPanel === true ? r.top - r.height : r.top;
          if (!Number.isFinite(fullBoardTop) || fullBoardTop < 0) {
            fullBoardTop = r.top;
          }
          const boardCenterX = r.left + r.width / 2;
          const desiredBottom = fullBoardTop - TUTORIAL_POPUP_1_15_GAP_ABOVE_BOARD_TOP_PX;
          const topPx = Math.max(
            12,
            desiredBottom - TUTORIAL_POPUP_1_15_MAX_HEIGHT_ESTIMATE_PX
          );
          if (Number.isFinite(boardCenterX) && Number.isFinite(topPx)) {
            return {
              ...base,
              position: "fixed",
              left: boardCenterX,
              top: topPx,
              transform: "translateX(-50%)",
            };
          }
        }
      }
    }
    if (step.stage === "1-16" && panelLeftSpotlightForLayout != null) {
      const board = panelLeftSpotlightForLayout;
      if (board.width >= 2 && board.height >= 2) {
        const boardRight = board.left + board.width;
        const leftPx = boardRight + TUTORIAL_POPUP_1_16_GAP_AFTER_BOARD_RIGHT_PX;
        const rangedRects = rangedWeaponsSpotlightRectsForLayout;
        let topCenter: number;
        if (rangedRects != null && rangedRects.length > 0) {
          const union = unionTutorialSpotlightRects(rangedRects);
          if (union != null && union.width >= 2 && union.height >= 2) {
            topCenter =
              union.top + union.height / 2 + TUTORIAL_POPUP_1_16_SHIFT_DOWN_PX;
          } else {
            topCenter = board.top + board.height / 2;
          }
        } else {
          topCenter = board.top + board.height / 2;
        }
        if (Number.isFinite(leftPx) && Number.isFinite(topCenter)) {
          return {
            ...base,
            position: "fixed",
            left: leftPx,
            top: topCenter,
            transform: "translateY(-50%)",
          };
        }
      }
    }
    if (
      step.popupPosition &&
      step.popupPosition !== "center" &&
      typeof step.popupPosition === "object"
    ) {
      return {
        ...base,
        left: toCss(step.popupPosition.left),
        top: toCss(step.popupPosition.top),
        transform: "none",
      };
    }
    return {
      ...base,
      left: "50%",
      top: "50%",
      transform: "translate(-50%, -50%)",
    };
  })();

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const handleTitleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button")) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const rect = dialog.getBoundingClientRect();
    dragStartRef.current = {
      mouseX: e.clientX,
      mouseY: e.clientY,
      dialogX: rect.left,
      dialogY: rect.top,
    };
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const start = dragStartRef.current;
      if (!start) return;
      setDialogPosition({
        x: start.dialogX + (e.clientX - start.mouseX),
        y: start.dialogY + (e.clientY - start.mouseY),
      });
    };
    const handleMouseUp = () => {
      dragStartRef.current = null;
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  /** Path pour bloquer les clics hors clickHoles et hors dialog (tutoriel : seuls les clics qui font avancer sont autorisés). */
  const blockingPathD = useMemo(
    () =>
      overlayRect && overlayRect.width > 0 && overlayRect.height > 0
        ? buildBlockingPath(
            overlayRect.width,
            overlayRect.height,
            filterCircleHolesContainedInRectHoles(clickHoles)
          )
        : "",
    [overlayRect, clickHoles]
  );

  const blockClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
  }, []);

  /** Overlay pleine page pour que les halos (ex. Intercessor) soient visibles. Clics hors zones autorisées bloqués. */
  const overlayContent = (
    <div
      ref={overlayRef}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 10000,
        pointerEvents: "none",
      }}
    >
      {spotlights.length > 0 && svgMask ? (
        <>
          {svgMask}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: `rgba(0, 0, 0, ${backdropOpacity})`,
              mask: `url(#${MASK_ID})`,
              WebkitMask: `url(#${MASK_ID})`,
              pointerEvents: "none",
            }}
            aria-hidden
          />
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              pointerEvents: "none",
            }}
            aria-hidden
          />
        </>
      ) : (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: `rgba(0, 0, 0, ${backdropOpacity})`,
            pointerEvents: "none",
          }}
          aria-hidden
        />
      )}
      {Array.isArray(fogLeftPanelRects) && fogLeftPanelRects.length > 0
        ? (fogLeftPanelRects as TutorialSpotlightRect[]).map((rect, i) =>
            rect.shape === "rect" ? (
              <svg
                key={`fog-left-${rect.left}-${rect.top}-${i}`}
                aria-hidden
                role="img"
                style={{
                  position: "fixed",
                  left: rect.left - FOG_BLUR_MARGIN,
                  top: rect.top - FOG_BLUR_MARGIN,
                  width: rect.width + FOG_BLUR_MARGIN * 2,
                  height: rect.height + FOG_BLUR_MARGIN * 2,
                  pointerEvents: "none",
                }}
                width={rect.width + FOG_BLUR_MARGIN * 2}
                height={rect.height + FOG_BLUR_MARGIN * 2}
                viewBox={`0 0 ${rect.width + FOG_BLUR_MARGIN * 2} ${rect.height + FOG_BLUR_MARGIN * 2}`}
              >
                <title>Fog tutoriel panneau gauche (bande {i + 1})</title>
                <defs>
                  <filter
                    id={`${FOG_BLUR_FILTER_ID}-left-${i}`}
                    x="-20%"
                    y="-20%"
                    width="140%"
                    height="140%"
                    colorInterpolationFilters="sRGB"
                  >
                    <feGaussianBlur in="SourceGraphic" stdDeviation={BLUR_EDGE} />
                  </filter>
                </defs>
                <rect
                  x={FOG_BLUR_MARGIN}
                  y={FOG_BLUR_MARGIN}
                  width={rect.width}
                  height={rect.height}
                  fill={`rgba(0, 0, 0, ${FOG_LEFT_PANEL_OPACITY})`}
                  filter={`url(#${FOG_BLUR_FILTER_ID}-left-${i})`}
                />
              </svg>
            ) : null
          )
        : null}
      {Array.isArray(fogRightPanelRects) && fogRightPanelRects.length > 0
        ? (fogRightPanelRects as TutorialSpotlightRect[]).map((rect, i) =>
            rect.shape === "rect" ? (
              <div
                key={`fog-right-${rect.left}-${rect.top}-${i}`}
                aria-hidden
                style={{
                  position: "fixed",
                  left: 0,
                  top: 0,
                  right: 0,
                  bottom: 0,
                  backgroundColor: `rgba(0, 0, 0, ${FOG_LEFT_PANEL_OPACITY})`,
                  clipPath:
                    overlayRect != null
                      ? `inset(${rect.top}px ${Math.max(
                          0,
                          overlayRect.width - (rect.left + rect.width)
                        )}px ${Math.max(0, overlayRect.height - (rect.top + rect.height))}px ${
                          rect.left
                        }px)`
                      : undefined,
                  mask: spotlights.length > 0 ? `url(#${MASK_ID})` : undefined,
                  WebkitMask: spotlights.length > 0 ? `url(#${MASK_ID})` : undefined,
                  pointerEvents: "none",
                }}
              />
            ) : null
          )
        : null}
      {debugSpotlightLabels.map((entry) => {
        const p = entry.position;
        const left = p.shape === "circle" ? p.x : p.left;
        const top = p.shape === "circle" ? p.y - p.radius - 22 : p.top - 22;
        return (
          <div
            key={`debug-spotlight-${entry.id}-${left}-${top}`}
            style={{
              position: "fixed",
              left: Math.max(4, left),
              top: Math.max(4, top),
              background: "rgba(0, 0, 0, 0.85)",
              color: "#7CFF7C",
              border: "1px solid rgba(124, 255, 124, 0.45)",
              borderRadius: "4px",
              padding: "2px 6px",
              fontSize: "11px",
              fontFamily: "monospace",
              lineHeight: 1.2,
              pointerEvents: "none",
              zIndex: 10002,
            }}
            aria-hidden
          >
            {entry.id}
          </div>
        );
      })}
      {/* Couche qui bloque les clics hors spotlights et hors dialog (seuls les clics qui font avancer passent). */}
      {blockingPathD && overlayRect ? (
        <svg
          aria-hidden
          role="presentation"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: overlayRect.width,
            height: overlayRect.height,
            pointerEvents: "none",
          }}
          width={overlayRect.width}
          height={overlayRect.height}
          viewBox={`0 0 ${overlayRect.width} ${overlayRect.height}`}
        >
          {/* biome-ignore lint/a11y/noStaticElementInteractions: couche de blocage des clics hors zones autorisées (trou = spotlight). */}
          <path
            fill="transparent"
            fillRule="evenodd"
            d={blockingPathD}
            style={{ pointerEvents: "auto" }}
            onClick={blockClick}
            onMouseDown={blockClick}
            onContextMenu={blockClick}
          />
        </svg>
      ) : null}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-title"
        tabIndex={-1}
        className="tutorial-overlay-dialog"
        style={{
          ...mergeTutorialDialogViewportTransform(dialogStyle, viewportInsetNudge),
          pointerEvents: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* biome-ignore lint/a11y/useSemanticElements: drag handle, cannot use button (contains interactive children) */}
        <div
          className="tutorial-overlay-dialog__title-bar"
          role="button"
          tabIndex={0}
          aria-label="Déplacer la fenêtre"
          onMouseDown={handleTitleMouseDown}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") e.preventDefault();
          }}
          style={{ cursor: "move", userSelect: "none" }}
        >
          <div className="tutorial-overlay-dialog__title-row">
            {titleIconSrc ? (
              <img
                src={titleIconSrc}
                alt=""
                className="tutorial-overlay-dialog__phase-logo"
                aria-hidden
              />
            ) : null}
            <h2 id="tutorial-title">{title}</h2>
          </div>
          <div className="tutorial-overlay-dialog__lang-buttons">
            <button
              type="button"
              onClick={() => onLangChange("fr")}
              className="tutorial-lang-btn"
              aria-pressed={lang === "fr"}
              aria-label="Français"
            >
              FR
            </button>
            <button
              type="button"
              onClick={() => onLangChange("en")}
              className="tutorial-lang-btn"
              aria-pressed={lang === "en"}
              aria-label="English"
            >
              EN
            </button>
          </div>
        </div>
        {showIllustrationBlock ? (
          <div className="tutorial-overlay-dialog__body-with-illustration">
            {step.popupShowMoveHex ? (
              isStep1_5 && bodyFirstLine1_5 ? (
                <div className="tutorial-overlay-dialog__icon-and-first-line tutorial-overlay-dialog__icon-and-first-line--hex-same-line">
                  <svg
                    className="tutorial-overlay-dialog__move-hex"
                    viewBox="0 0 50 50"
                    aria-hidden
                    role="img"
                  >
                    <title>Hexagone de destination de déplacement</title>
                    <polygon
                      points={[0, 60, 120, 180, 240, 300]
                        .map((deg) => {
                          const rad = (deg * Math.PI) / 180;
                          const x = 25 + 20 * Math.cos(rad);
                          const y = 25 + 20 * Math.sin(rad);
                          return `${x},${y}`;
                        })
                        .join(" ")}
                      fill="rgba(144, 208, 144, 0.5)"
                      stroke="#00aa00"
                      strokeWidth="1.2"
                    />
                  </svg>
                  <span className="tutorial-overlay-dialog__body-first-line">
                    {bodyFirstLine1_5}
                  </span>
                </div>
              ) : (
                <svg
                  className="tutorial-overlay-dialog__move-hex"
                  viewBox="0 0 50 50"
                  aria-hidden
                  role="img"
                >
                  <title>Hexagone de destination de déplacement</title>
                  <polygon
                    points={[0, 60, 120, 180, 240, 300]
                      .map((deg) => {
                        const rad = (deg * Math.PI) / 180;
                        const x = 25 + 20 * Math.cos(rad);
                        const y = 25 + 20 * Math.sin(rad);
                        return `${x},${y}`;
                      })
                      .join(" ")}
                    fill="rgba(144, 208, 144, 0.5)"
                    stroke="#00aa00"
                    strokeWidth="1.2"
                  />
                </svg>
              )
            ) : null}
            {step.popupImage && step.popupShowGreenCircle ? (
              <div
                className={
                  isStepIconAndFirstLine
                    ? "tutorial-overlay-dialog__icon-and-first-line"
                    : "tutorial-overlay-dialog__unit-icon-with-green-circle"
                }
                aria-hidden={!isStepIconAndFirstLine}
              >
                <div className="tutorial-overlay-dialog__unit-icon-with-green-circle" aria-hidden>
                  <svg
                    className="tutorial-overlay-dialog__green-activation-circle"
                    viewBox="0 0 64 64"
                    aria-hidden
                  >
                    <title>Cercle vert d’unité activable</title>
                    <circle
                      cx="32"
                      cy="32"
                      r="28"
                      fill="none"
                      stroke="#00ff00"
                      strokeWidth="3"
                      strokeOpacity="0.8"
                    />
                  </svg>
                  <img
                    src={step.popupImage}
                    alt=""
                    className={`tutorial-overlay-dialog__popup-image tutorial-overlay-dialog__popup-image--in-circle${popupImageGhostClass}`}
                    aria-hidden
                  />
                </div>
                {isStepIconAndFirstLine && bodyFirstLineIcon ? (
                  <span className="tutorial-overlay-dialog__body-first-line">
                    {bodyFirstLineIcon}
                  </span>
                ) : null}
              </div>
            ) : null}
            {step.popupImage && body.includes("{{ICON}}") ? (
              <p
                className="tutorial-overlay-dialog__body-paragraph"
                style={{ whiteSpace: "pre-wrap" }}
              >
                {body.split("{{ICON}}")[0]}
                <img
                  src={step.popupImage}
                  alt=""
                  className={`tutorial-overlay-dialog__popup-image tutorial-overlay-dialog__popup-image--inline${popupImageGhostClass}`}
                  aria-hidden
                />
                {body.split("{{ICON}}").slice(1).join("{{ICON}}")}
              </p>
            ) : step.popupImage && !step.popupShowGreenCircle ? (
              step.popupFirstLineWithIcon && bodyFirstLineIcon ? (
                <>
                  <div className="tutorial-overlay-dialog__icon-and-first-line">
                    <img
                      src={step.popupImage}
                      alt=""
                      className={`tutorial-overlay-dialog__popup-image${popupImageGhostClass}`}
                      aria-hidden
                    />
                    <span className="tutorial-overlay-dialog__body-first-line">
                      {bodyFirstLineIcon}
                    </span>
                  </div>
                  {bodyContentRestIcon !== null &&
                    (typeof bodyContentRestIcon === "string" ? (
                      <p>{bodyContentRestIcon}</p>
                    ) : (
                      <div
                        className="tutorial-overlay-dialog__body-paragraph"
                        style={{ whiteSpace: "pre-wrap" }}
                      >
                        {bodyContentRestIcon}
                      </div>
                    ))}
                </>
              ) : (
                <>
                  <img
                    src={step.popupImage}
                    alt=""
                    className={`tutorial-overlay-dialog__popup-image${popupImageGhostClass}`}
                    aria-hidden
                  />
                  {typeof bodyContent === "string" ? (
                    <p>{bodyContent}</p>
                  ) : (
                    <div
                      className="tutorial-overlay-dialog__body-paragraph"
                      style={{ whiteSpace: "pre-wrap" }}
                    >
                      {bodyContent}
                    </div>
                  )}
                </>
              )
            ) : (
              (() => {
                const content =
                  isStepIconAndFirstLine && bodyContentRestIcon !== null
                    ? bodyContentRestIcon
                    : isStep1_5 && bodyContentRest1_5 !== null
                      ? bodyContentRest1_5
                      : bodyContent;
                return typeof content === "string" ? (
                  <p>{content}</p>
                ) : (
                  <div
                    className="tutorial-overlay-dialog__body-paragraph"
                    style={{ whiteSpace: "pre-wrap" }}
                  >
                    {content}
                  </div>
                );
              })()
            )}
          </div>
        ) : typeof bodyContent === "string" ? (
          <p>{bodyContent}</p>
        ) : (
          <div
            className="tutorial-overlay-dialog__body-paragraph"
            style={{ whiteSpace: "pre-wrap" }}
          >
            {bodyContent}
          </div>
        )}
        <div
          style={{
            display: "flex",
            gap: "12px",
            flexWrap: "wrap",
            justifyContent: "flex-end",
            alignItems: "flex-end",
          }}
        >
          <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
            {!step.advanceOnUnitClick && !step.advanceOnMoveClick && !step.advanceOnWeaponClick && (
              <button type="button" onClick={onClose} className="tutorial-btn-primary">
                Suivant
              </button>
            )}
            {onSkipTutorial && (
              <button type="button" onClick={onSkipTutorial} className="tutorial-btn-secondary">
                Passer le tutoriel
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlayContent, document.body);
};

export default TutorialOverlay;
