// frontend/src/components/GameLogWithIllustration.tsx
/**
 * Gabarit commun PvP / PvP test / replay : panneau d'illustration d'unité à gauche, Game Log à
 * droite. C'est l'illustration (hauteur fixe) qui donne sa hauteur au log : sans elle, le log
 * grandit avec son contenu et perd sa barre de défilement au profit de celle de la colonne
 * (`.unit-status-tables`) — c'était le cas du replay avant le partage de ce gabarit.
 *
 * Le CHOIX de l'unité affichée appartient au parent (survol / épinglage / figurine inspectée en
 * PvP, action courante en replay). Ce composant ne gère que la présentation : préchargement des
 * assets, fondu enchaîné au changement d'unité, retour à l'illustration par défaut.
 */
import { useEffect, useRef, useState } from "react";
import type { Unit } from "../types";
import { ErrorBoundary } from "./ErrorBoundary";
import UnitStatusBadges from "./UnitStatusBadges";

const UNIT_ILLUSTRATION_FILE_EXTENSION = "png";
/** Socle commun de toutes les illustrations. La taille RELATIVE d'une unité se règle par son
 *  `ILLUSTRATION_RATIO` (en pourcent, sur sa datasheet) et par rien d'autre. */
const UNIT_ILLUSTRATION_BASE_SCALE = 0.7;
const UNIT_ILLUSTRATION_RATIO_PERCENT_BASE = 100;
const DEFAULT_UNIT_ILLUSTRATION_SRC = "/icons/Endless duty.png";
const DEFAULT_UNIT_ILLUSTRATION_DELAY_MS = 2000;
const DEFAULT_UNIT_ILLUSTRATION_FADE_MS = 300;
const UNIT_ILLUSTRATION_FADE_OUT_MS = 100;
const UNIT_ILLUSTRATION_SWAP_FADE_MS = 100;

/** Nom servant à résoudre l'asset, ou `null` s'il n'y en a pas d'exploitable. SEULE définition de
 *  ce test : le getter ci-dessous en fait une erreur (chemin d'affichage, où l'absence doit se
 *  voir), le préchargement en fait un saut (décoration, où elle ne doit rien casser). */
function illustrationAssetName(unit: Unit): string | null {
  const unitName = unit.NAME ?? unit.type;
  return typeof unitName === "string" && unitName.trim() !== "" ? unitName.trim() : null;
}

export function getUnitIllustrationSrc(unit: Unit): string {
  const unitName = illustrationAssetName(unit);
  if (unitName === null) {
    throw new Error(`Unit ${unit.id} missing NAME/type for illustration path`);
  }
  return `/icons/${encodeURIComponent(unitName)}.${UNIT_ILLUSTRATION_FILE_EXTENSION}`;
}

export function getUnitIllustrationScale(unit: Unit): number {
  // `BASE_SIZE` n'entre PAS ici : c'est l'empreinte de la figurine sur le plateau, convertie en
  // cellules (`_scale_socle` moteur / `scaleBaseSize` replay), donc dépendante de la résolution du
  // plateau chargé. La faire entrer dans un calcul d'affichage donnait la même unité à des tailles
  // différentes selon le plateau — et un terme écrasé au plancher sur x1 et x5.
  if (
    typeof unit.ILLUSTRATION_RATIO !== "number" ||
    !Number.isFinite(unit.ILLUSTRATION_RATIO) ||
    unit.ILLUSTRATION_RATIO < 0
  ) {
    throw new Error(`Unit ${unit.id} missing non-negative numeric ILLUSTRATION_RATIO`);
  }
  return (
    UNIT_ILLUSTRATION_BASE_SCALE * (unit.ILLUSTRATION_RATIO / UNIT_ILLUSTRATION_RATIO_PERCENT_BASE)
  );
}

/** Identité visuelle d'une illustration : deux unités de même id et même asset sont, pour ce
 *  composant, la même image — quelle que soit l'identité de l'objet JavaScript. `null` quand
 *  l'unité n'a aucun nom exploitable : elle est alors traitée comme « pas d'illustration », au
 *  lieu de laisser lever `getUnitIllustrationSrc` dans le corps de rendu (hors de portée de
 *  toute ErrorBoundary, donc fatal au Game Log entier). */
function illustrationKey(unit: Unit): string | null {
  const assetName = illustrationAssetName(unit);
  return assetName === null ? null : `${unit.id}|${assetName}`;
}

/** Statuts affichés en overlay sur l'illustration. `null` = source de vérité absente (replay :
 *  le step.log ne transporte pas les ensembles moved/advanced/fled/charged du moteur). */
export type IllustrationBadges = {
  hidden: boolean;
  battleShocked: boolean;
  advanced: boolean;
  moved: boolean;
  charged: boolean;
  fellBack: boolean;
  stationary: boolean;
};

/**
 * Préchargement des illustrations. Vit dans un HOOK appelé par le board, et non dans
 * `GameLogWithIllustration` : en PvP ce dernier est démonté pendant la phase de déploiement,
 * c'est-à-dire exactement la fenêtre où il faut réchauffer les images pour que le premier fondu
 * ne clignote pas. Monté au niveau du board, le cache survit à ces démontages.
 */
export function useUnitIllustrationPreload(units: Unit[]): void {
  const preloadedSrcRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (typeof Image === "undefined") {
      return;
    }
    const sources = new Set<string>([DEFAULT_UNIT_ILLUSTRATION_SRC]);
    for (const candidate of units) {
      // Une unité sans nom exploitable est IGNORÉE ici : ce hook vit au niveau du board, hors de
      // toute ErrorBoundary, et le préchargement n'est que du confort — le laisser lever
      // emporterait la page entière, alors que le même défaut sur le chemin d'affichage se
      // contente de dégrader le panneau. L'absence reste signalée là où elle se voit.
      if (candidate.HP_CUR > 0 && illustrationAssetName(candidate) !== null) {
        sources.add(getUnitIllustrationSrc(candidate));
      }
    }
    for (const src of sources) {
      if (preloadedSrcRef.current.has(src)) {
        continue;
      }
      preloadedSrcRef.current.add(src);
      const image = new Image();
      image.decoding = "async";
      image.src = src;
      if (typeof image.decode === "function") {
        void image.decode().catch(() => undefined);
      }
    }
  }, [units]);
}

/** Initiale affichée à défaut de tout visuel. Le type prime sur le NAME : c'est lui qui nomme la
 *  figurine côté journal comme côté datasheet. */
function unitInitial(unit: Unit): string {
  const label = unit.type ?? unit.NAME;
  if (typeof label !== "string" || label.trim() === "") {
    throw new Error(`Unit ${unit.id} missing type/NAME for illustration initial`);
  }
  return label.trim().charAt(0).toUpperCase();
}

/** Source visuelle courante du panneau, par ordre de repli.
 *  `asset` : `/icons/<nom>.png`. `icon` : le champ `ICON` de la datasheet, qui porte le visuel du
 *  pion (souvent en `.webp`) — 26 unités n'ont que celui-là. `initial` : plus aucun visuel, on
 *  affiche l'initiale du type sur fond blanc. */
type IllustrationSource = "asset" | "icon" | "initial";

/**
 * Panneau d'illustration d'UNE unité. Composant à part entière — et non du JSX en ligne — pour que
 * son rendu ait lieu SOUS l'ErrorBoundary de `GameLogWithIllustration` : `getUnitIllustrationScale`
 * lève sur une unité dont le registre ne donne pas l'ILLUSTRATION_RATIO, et cette levée doit
 * dégrader le seul panneau, jamais emporter le Game Log.
 *
 * L'état de repli n'a pas besoin d'être réinitialisé au changement d'unité : le parent remonte ce
 * sous-arbre par la `key` de l'ErrorBoundary.
 */
function UnitIllustration({
  unit,
  badgesFor,
  visible,
  fadeMs,
}: {
  unit: Unit;
  badgesFor: ((displayed: Unit) => IllustrationBadges) | null;
  visible: boolean;
  fadeMs: number;
}) {
  const [source, setSource] = useState<IllustrationSource>("asset");
  const fadeStyle = {
    opacity: visible ? 1 : 0,
    transition: `opacity ${fadeMs}ms ease`,
    willChange: "opacity",
    backfaceVisibility: "hidden",
  } as const;

  return (
    <aside className="unit-illustration-preview" aria-label={`Illustration unit ${unit.id}`}>
      {badgesFor && <UnitStatusBadges {...badgesFor(unit)} />}
      {source === "initial" ? (
        <div
          className="unit-illustration-preview__initial"
          role="img"
          aria-label={`Unit ${unit.id} sans illustration`}
          style={fadeStyle}
        >
          {unitInitial(unit)}
        </div>
      ) : (
        <img
          className="unit-illustration-preview__image"
          src={source === "asset" ? getUnitIllustrationSrc(unit) : (unit.ICON ?? "")}
          alt={`Unit ${unit.id} illustration`}
          onError={() => {
            // `.png` absent : 26 unités n'ont leur visuel que sous l'extension déclarée par ICON
            // (pion du plateau, cadrage différent mais visuel juste). Au-delà, plus rien n'existe
            // — l'initiale prend le relais et l'absence est SIGNALÉE, jamais silencieuse.
            if (source === "asset" && typeof unit.ICON === "string" && unit.ICON.trim() !== "") {
              setSource("icon");
              return;
            }
            console.error(
              `Aucune illustration pour l'unité ${unit.id} (${unit.type ?? unit.NAME}) : ni ` +
                `${getUnitIllustrationSrc(unit)} ni ICON (${unit.ICON ?? "absent"})`
            );
            setSource("initial");
          }}
          style={{ ...fadeStyle, transform: `scale(${getUnitIllustrationScale(unit)})` }}
        />
      )}
    </aside>
  );
}

interface GameLogWithIllustrationProps {
  /** Unité dont l'illustration est affichée. `null` → illustration par défaut après un délai. */
  unit: Unit | null;
  /** Statuts de l'unité RÉELLEMENT affichée — évalué ici et non par le parent, car pendant un
   *  fondu l'unité affichée n'est pas encore `unit`. `null` = mode sans source de vérité. */
  badgesFor: ((displayed: Unit) => IllustrationBadges) | null;
  /** Le `<GameLog>` du mode appelant. */
  children: React.ReactNode;
}

export function GameLogWithIllustration({
  unit,
  badgesFor,
  children,
}: GameLogWithIllustrationProps) {
  /** Le délai avant l'illustration générique n'existe QUE pour éviter de la faire clignoter entre
   *  deux sélections d'unité. Au MONTAGE sans unité, il n'y a rien à masquer : on l'affiche tout de
   *  suite. Sinon le PvP, qui démonte ce panneau pendant le déploiement, rouvrirait la phase de
   *  commande sur un cadre vide pendant 2 s. */
  const [showDefaultIllustration, setShowDefaultIllustration] = useState(() => unit === null);
  const [displayedUnit, setDisplayedUnit] = useState<Unit | null>(null);
  const [showDisplayedUnit, setShowDisplayedUnit] = useState(false);
  const [fadeMs, setFadeMs] = useState(UNIT_ILLUSTRATION_FADE_OUT_MS);
  const displayedUnitRef = useRef<Unit | null>(null);
  const pendingUnitRef = useRef<Unit | null>(null);

  /** Identité de CE QUI EST AFFICHÉ : id de l'unité + asset. Les appelants reconstruisent leurs
   *  unités à chaque rendu (le replay les re-dérive du journal), donc `unit` change d'identité
   *  sans que l'illustration change. La machine à états est pilotée par cette clé et JAMAIS par
   *  l'objet : un effet dépendant de l'objet verrait son nettoyage s'exécuter à chaque rendu et
   *  annulerait ses propres minuteurs/rAF en vol. */
  const requestedKey = unit ? illustrationKey(unit) : null;
  /** `unit` frais, lu dans l'effet sans le placer en dépendance (cf. `requestedKey`). */
  const unitRef = useRef<Unit | null>(unit);
  unitRef.current = unit;

  // La dépendance EST `requestedKey`, jamais `unit` : mettre l'objet en dépendance relancerait le
  // nettoyage — donc annulerait le fondu en vol — à chaque rendu du parent, sans qu'aucune
  // illustration n'ait changé.
  useEffect(() => {
    const unit = unitRef.current;
    const currentDisplayedUnit = displayedUnitRef.current;

    if (unit && requestedKey !== null) {
      setShowDefaultIllustration(false);
      const isReplacingDisplayedUnit =
        currentDisplayedUnit !== null && illustrationKey(currentDisplayedUnit) !== requestedKey;

      if (isReplacingDisplayedUnit) {
        // Bascule pilotée par un MINUTEUR et non par `onTransitionEnd` : si l'image est déjà à
        // l'opacité 0 (fondu sortant en cours quand une nouvelle unité arrive), passer
        // `showDisplayedUnit` à false ne démarre aucune transition, l'évènement ne survient
        // jamais et l'unité en attente n'est plus jamais affichée.
        pendingUnitRef.current = unit;
        setFadeMs(UNIT_ILLUSTRATION_SWAP_FADE_MS);
        setShowDisplayedUnit(false);
        let firstAnimationFrameId: number | null = null;
        let secondAnimationFrameId: number | null = null;
        const swapTimerId = window.setTimeout(() => {
          const pendingUnit = pendingUnitRef.current;
          if (!pendingUnit) {
            return;
          }
          pendingUnitRef.current = null;
          setDisplayedUnit(pendingUnit);
          displayedUnitRef.current = pendingUnit;
          firstAnimationFrameId = window.requestAnimationFrame(() => {
            secondAnimationFrameId = window.requestAnimationFrame(() => {
              setShowDisplayedUnit(true);
            });
          });
        }, UNIT_ILLUSTRATION_SWAP_FADE_MS);
        return () => {
          window.clearTimeout(swapTimerId);
          if (firstAnimationFrameId !== null) {
            window.cancelAnimationFrame(firstAnimationFrameId);
          }
          if (secondAnimationFrameId !== null) {
            window.cancelAnimationFrame(secondAnimationFrameId);
          }
        };
      }

      pendingUnitRef.current = null;
      setFadeMs(UNIT_ILLUSTRATION_SWAP_FADE_MS);
      if (currentDisplayedUnit === null) {
        setShowDisplayedUnit(false);
        setDisplayedUnit(unit);
        displayedUnitRef.current = unit;
        let secondAnimationFrameId: number | null = null;
        const firstAnimationFrameId = window.requestAnimationFrame(() => {
          secondAnimationFrameId = window.requestAnimationFrame(() => {
            setShowDisplayedUnit(true);
          });
        });
        return () => {
          window.cancelAnimationFrame(firstAnimationFrameId);
          if (secondAnimationFrameId !== null) {
            window.cancelAnimationFrame(secondAnimationFrameId);
          }
        };
      }

      setDisplayedUnit(unit);
      displayedUnitRef.current = unit;
      setShowDisplayedUnit(true);
      return;
    }

    pendingUnitRef.current = null;
    setFadeMs(UNIT_ILLUSTRATION_FADE_OUT_MS);
    if (currentDisplayedUnit === null) {
      return;
    }
    setShowDisplayedUnit(false);
    const timerId = window.setTimeout(() => {
      if (displayedUnitRef.current === currentDisplayedUnit) {
        setDisplayedUnit(null);
        displayedUnitRef.current = null;
        setShowDisplayedUnit(false);
      }
    }, UNIT_ILLUSTRATION_FADE_OUT_MS);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [requestedKey]);

  // Idem : `requestedKey` remplace `unit` en dépendance.
  useEffect(() => {
    if (requestedKey !== null || displayedUnit) {
      setShowDefaultIllustration(false);
      return;
    }
    const timerId = window.setTimeout(() => {
      setShowDefaultIllustration(true);
    }, DEFAULT_UNIT_ILLUSTRATION_DELAY_MS);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [displayedUnit, requestedKey]);

  /** L'illustration affichée, mais lue sur l'objet le PLUS FRAIS quand c'est la même : `displayedUnit`
   *  est un instantané figé au moment de la bascule, or les badges (battle-shock, caché) changent
   *  pendant qu'une unité reste affichée. Pendant un fondu (clés différentes), on garde l'unité
   *  sortante, qui est bien celle à l'écran. */
  const renderedUnit =
    displayedUnit !== null && unit !== null && illustrationKey(displayedUnit) === requestedKey
      ? unit
      : displayedUnit;
  const renderedKey = renderedUnit === null ? null : illustrationKey(renderedUnit);

  return (
    <div className="game-log-with-illustration">
      {/* L'illustration est de la décoration, le Game Log est la donnée : une unité que le registre
          ne sait pas dimensionner (ILLUSTRATION_RATIO absent) ne doit jamais emporter le log avec
          elle. Le panneau est un COMPOSANT ENFANT et non du JSX en ligne : le JSX en ligne est
          évalué dans le rendu de CE composant, donc au-dessus du boundary, qui n'en verrait rien.
          Le fallback garde la place du panneau pour que le gabarit ne bouge pas. */}
      <ErrorBoundary
        // `key` : sans elle, une ErrorBoundary reste en échec DÉFINITIVEMENT. Changer de clé la
        // remonte, donc l'échec reste bien cantonné à l'unité qui l'a provoqué.
        key={renderedKey ?? "default"}
        fallback={<aside className="unit-illustration-preview" aria-label="Illustration absente" />}
      >
        {renderedUnit && renderedKey !== null ? (
          <UnitIllustration
            unit={renderedUnit}
            badgesFor={badgesFor}
            visible={showDisplayedUnit}
            fadeMs={fadeMs}
          />
        ) : (
          <aside className="unit-illustration-preview" aria-label="Endless Duty illustration">
            <img
              className="unit-illustration-preview__image"
              src={DEFAULT_UNIT_ILLUSTRATION_SRC}
              alt="Endless Duty illustration"
              style={{
                opacity: showDefaultIllustration ? 1 : 0,
                transition: `opacity ${DEFAULT_UNIT_ILLUSTRATION_FADE_MS}ms ease`,
              }}
            />
          </aside>
        )}
      </ErrorBoundary>
      <div className="game-log-with-illustration__log">{children}</div>
    </div>
  );
}
