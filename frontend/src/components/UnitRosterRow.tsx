// frontend/src/components/UnitRosterRow.tsx
import type { KeyboardEvent, MouseEvent, ReactElement, ReactNode } from "react";
import type { PlayerId, Unit } from "../types";
import { getIconDiameterRatio } from "../utils/unitBaseDisplay";

/**
 * Une ligne d'escouade HORS TABLE : le format partagé par la liste des unités à déployer et par
 * le conteneur des réserves stratégiques (20.01).
 *
 * UN SEUL format, parce qu'il désigne la même chose des deux côtés — une escouade qui n'est pas
 * sur le champ de bataille, montrée par ses figurines. Les deux listes en avaient chacune un
 * jusqu'ici ; celle des réserves affichait un simple texte, donc la même escouade n'avait pas la
 * même tête selon l'endroit d'où on la regardait.
 *
 * Ordre imposé, de gauche à droite : figurines, nom, puis à DROITE l'emplacement `trailing`
 * (bouton d'action propre au siège), la valeur en points, le nombre de figurines, l'id.
 */

/** Ce que la ligne lit du `units_cache` : les figurines de l'escouade et leur métadonnée d'icône. */
export type RosterRowUnitsCache =
  | Record<
      string,
      {
        occupied_hexes_by_model?: Record<string, unknown>;
        models_meta_by_model?: Record<
          string,
          {
            ICON?: string;
            BASE_SIZE?: number | [number, number];
            BASE_SHAPE?: string;
            ICON_SCALE?: number;
            role?: string | null;
          }
        >;
      }
    >
  | undefined;

// Ordre d'affichage gauche→droite : leader → support → sergeant → special_weapon → figurine de
// base. Le rôle par figurine est exposé par le backend dans `models_meta_by_model`.
const ROLE_ORDER: Record<string, number> = {
  leader: 0,
  support: 1,
  sergeant: 2,
  special_weapon: 3,
};

/** Contour d'une ligne, à la couleur du joueur — la même des deux côtés (déploiement, réserves). */
export function rosterRowBorderColor(player: PlayerId): string {
  return player === 2 ? "var(--hp-bar-player2)" : "var(--hp-bar-player1)";
}

// Taille d'icône = même ratio que le board (source unique `getIconDiameterRatio`), avec un
// HEX_RADIUS fictif de calibrage tel que l'infanterie standard ≈ 36px.
const ICON_HEX_RADIUS = 3;
const ICON_SCALE_GLOBAL = 1.2; // = board_config.display.icon_scale

export function UnitRosterRow({
  unit,
  player,
  unitsCache,
  boundIconSize,
  selected,
  interactive,
  onClick,
  onHover,
  onLeave,
  tooltipSuffix = "",
  borderColor,
  haloGlow,
  trailing,
}: {
  unit: Unit;
  player: PlayerId;
  unitsCache: RosterRowUnitsCache;
  /** `settings.deployIconBaseSizeBounded` : borne les icônes à 24..60px. */
  boundIconSize: boolean;
  selected: boolean;
  interactive: boolean;
  onClick: () => void;
  /** Tooltip SUIVEUR (il se repositionne à chaque mouvement). Optionnel, et volontairement absent
   *  du conteneur de réserves : la ligne y montre déjà nom, points, figurines et id, donc le
   *  tooltip ne dirait rien de plus — et il ferait remonter un `setState` au rythme du pointeur
   *  dans un composant dont le plateau (`BoardPvp`, non mémoïsé) est un enfant. */
  onHover?: (text: string, x: number, y: number) => void;
  onLeave?: () => void;
  /** Ajouté au tooltip, ex. « (inactive this turn) ». */
  tooltipSuffix?: string;
  borderColor: string;
  haloGlow: string;
  /** Bouton d'action du siège, aligné à droite AVANT les points. */
  trailing?: ReactNode;
}): ReactElement {
  const displayName =
    unit.DISPLAY_NAME || unit.name || unit.type || unit.unitType || String(unit.id);
  const ucEntry = unitsCache?.[String(unit.id)];
  const roleRank = (modelId: string): number => {
    const role = ucEntry?.models_meta_by_model?.[modelId]?.role;
    return role != null && role in ROLE_ORDER ? ROLE_ORDER[role] : 4;
  };
  // Nombre de figurines = clés de `occupied_hexes_by_model` (source du board, toujours présente
  // même pour une escouade non déployée à (-1,-1)).
  const figModelIds = (
    ucEntry?.occupied_hexes_by_model
      ? Object.keys(ucEntry.occupied_hexes_by_model)
      : [String(unit.id)]
  ).sort((a, b) => roleRank(a) - roleRank(b));
  const figCount = figModelIds.length;
  // Icône par figurine : `models_meta_by_model` n'est exposé que pour les escouades
  // hétérogènes ; sinon repli métier sur l'icône d'unité.
  const iconForModel = (modelId: string): string => {
    const baseIcon = ucEntry?.models_meta_by_model?.[modelId]?.ICON ?? unit.ICON;
    return player === 2 ? baseIcon.replace(".webp", "_red.webp") : baseIcon;
  };
  const iconPxForModel = (modelId: string): number => {
    const meta = ucEntry?.models_meta_by_model?.[modelId];
    const figUnit = {
      BASE_SIZE: meta?.BASE_SIZE ?? unit.BASE_SIZE,
      BASE_SHAPE: meta?.BASE_SHAPE ?? unit.BASE_SHAPE,
      ICON_SCALE: meta?.ICON_SCALE ?? unit.ICON_SCALE,
    } as Unit;
    const px = Math.round(getIconDiameterRatio(figUnit, ICON_SCALE_GLOBAL) * ICON_HEX_RADIUS);
    return boundIconSize ? Math.max(24, Math.min(60, px)) : px;
  };
  const tooltipText = `${displayName} - ID ${unit.id} - ${figCount} fig.${tooltipSuffix}`;

  // `div role="button"` et non `<button>` : la ligne PORTE un bouton (`trailing`), et un
  // <button> imbriquant un <button> est du HTML invalide. Le clavier est câblé explicitement
  // pour que la ligne reste actionnable sans souris. La ligne ENTIÈRE est la cible : c'est le
  // geste qu'elle avait avant d'accueillir le bouton, et rétrécir la zone cliquable à
  // « icônes + nom » rendait le bout droit (points, figurines, id) inerte au clic.
  const activate = (): void => {
    if (interactive) onClick();
  };
  return (
    // biome-ignore lint/a11y/useSemanticElements: <button> impossible — la ligne porte `trailing`
    <div
      role="button"
      tabIndex={interactive ? 0 : -1}
      aria-disabled={!interactive}
      aria-label={displayName}
      data-testid={`roster-row-select-${unit.id}`}
      className={`deployment-panel__unit-row deployment-panel__unit-row--player${player}`}
      onMouseEnter={
        onHover
          ? (e: MouseEvent<HTMLDivElement>) => onHover(tooltipText, e.clientX, e.clientY)
          : undefined
      }
      onMouseMove={
        onHover
          ? (e: MouseEvent<HTMLDivElement>) => onHover(tooltipText, e.clientX, e.clientY)
          : undefined
      }
      onMouseLeave={onLeave}
      onClick={activate}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        width: "100%",
        minHeight: "32px",
        borderRadius: "6px",
        border: selected ? "1px solid transparent" : `1px solid ${borderColor}`,
        background: selected ? "rgba(8, 40, 22, 0.92)" : "rgba(0, 0, 0, 0.35)",
        boxShadow: selected ? haloGlow : undefined,
        outline: "none",
        color: "white",
        cursor: interactive ? "pointer" : "not-allowed",
        opacity: interactive ? 1 : 0.55,
        padding: "4px 8px",
        textAlign: "left",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "2px",
          flex: "0 1 auto",
          minWidth: 0,
        }}
      >
        {figModelIds.map((figModelId) => {
          const figPx = iconPxForModel(figModelId);
          return (
            <img
              key={`roster-fig-${player}-${unit.id}-${figModelId}`}
              src={iconForModel(figModelId)}
              alt={displayName}
              style={{
                width: `${figPx}px`,
                height: `${figPx}px`,
                objectFit: "contain",
                pointerEvents: "none",
                flex: "0 0 auto",
              }}
            />
          );
        })}
      </div>
      <span
        style={{
          flex: "1 1 auto",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {displayName}
      </span>
      {trailing}
      {/* Valeur en points de l'ESCOUADE : c'est elle que le plafond de 50 % (20.01) consomme,
          donc c'est elle que le joueur doit voir avant de décider d'une mise en réserves. */}
      <span
        data-testid={`roster-row-points-${unit.id}`}
        style={{ fontSize: "11px", opacity: 0.85, flex: "0 0 auto" }}
      >
        {unit.VALUE ?? "-"} pts
      </span>
      <span style={{ fontSize: "11px", opacity: 0.85, flex: "0 0 auto" }}>{figCount} fig.</span>
      <span
        style={{
          fontSize: "10px",
          background: "rgba(0, 0, 0, 0.65)",
          padding: "1px 4px",
          borderRadius: "3px",
          flex: "0 0 auto",
        }}
      >
        #{unit.id}
      </span>
    </div>
  );
}
