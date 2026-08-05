// frontend/src/components/StrategicReservesContainer.tsx
import type { MouseEvent, ReactElement } from "react";
import type { PlayerId } from "../types";
import type { StrategicReservesPlayerSummary, Unit, UnitId } from "../types/game";
import { formatStrategicReservesRatio } from "../utils/strategicReservesUi";
import { type RosterRowUnitsCache, UnitRosterRow } from "./UnitRosterRow";

/** Contour ORANGE du conteneur de réserves — le distingue des lignes d'unités normales. */
export const RESERVES_BORDER_COLOR = "#ff8c00";

/**
 * 20.01 — le bouton qui met l'escouade SÉLECTIONNÉE en réserves au lieu de la déployer.
 *
 * Vert quand le moteur accepterait le dépôt, gris sinon. La couleur n'est pas décorative : elle
 * est l'unique réponse rendue au joueur sur « cette escouade tient-elle sous le plafond de 50 % ».
 * Elle vient donc de `placeable_unit_ids` (le calcul qui décide vraiment), jamais d'une
 * arithmétique refaite ici.
 */
export function StrategicReserveButton({
  canDrop,
  onDrop,
}: {
  canDrop: boolean;
  onDrop: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      data-testid="strategic-reserves-drop"
      disabled={!canDrop}
      onClick={(e: MouseEvent<HTMLButtonElement>) => {
        // La ligne entière est cliquable (sélection) : sans cet arrêt, le dépôt rejouerait
        // aussi la sélection de l'escouade qu'il vient de retirer de la liste.
        e.stopPropagation();
        onDrop();
      }}
      style={{
        flex: "0 0 auto",
        background: canDrop ? "var(--ui-green-validate)" : "var(--ui-gray-cancel)",
        color: "#fff",
        border: "1px solid rgba(0, 0, 0, 0.35)",
        borderRadius: "4px",
        fontSize: "11px",
        fontWeight: 700,
        padding: "3px 8px",
        whiteSpace: "nowrap",
        cursor: canDrop ? "pointer" : "not-allowed",
      }}
    >
      Strategic Reserve
    </button>
  );
}

/**
 * Annule la MISE EN PLACE en cours (déploiement ou arrivée 20.04) et rend l'escouade à son état
 * d'avant : rien n'est écrit côté moteur, donc elle reste à poser et peut être reprise
 * immédiatement — après en avoir placé une autre, par exemple.
 *
 * Occupe l'emplacement du bouton `Strategic Reserve`, qu'il remplace dès que l'escouade est
 * posée : à ce moment-là le dépôt en réserves n'a plus de sens (l'escouade est sur le plateau,
 * en provisoire), et c'est se dédire qui en a un.
 */
export function ResetPlacementButton({ onReset }: { onReset: () => void }): ReactElement {
  return (
    <button
      type="button"
      data-testid="placement-reset"
      onClick={(e: MouseEvent<HTMLButtonElement>) => {
        // La ligne entière sélectionne : sans cet arrêt, l'annulation serait suivie d'une
        // re-sélection de l'escouade qu'on vient justement de reposer.
        e.stopPropagation();
        onReset();
      }}
      style={{
        flex: "0 0 auto",
        background: "var(--ui-gray-cancel)",
        color: "#fff",
        border: "1px solid rgba(0, 0, 0, 0.35)",
        borderRadius: "4px",
        fontSize: "11px",
        fontWeight: 700,
        padding: "3px 8px",
        whiteSpace: "nowrap",
        cursor: "pointer",
      }}
    >
      Reset
    </button>
  );
}

/**
 * 20.01/20.04 — le conteneur des escouades TENUES EN RÉSERVES d'un joueur.
 *
 * Rendu SOUS la table de statut de son joueur, à toutes les phases : c'est la seule vue des
 * escouades hors table, et c'est par lui qu'elles reviennent en jeu (20.04). Public des deux
 * côtés (« place them to one side » : les réserves sont déclarées ouvertement), mais cliquable
 * seulement pour son propriétaire et seulement en phase de mouvement, où l'arrivée existe.
 *
 * Le DÉPÔT ne se fait pas ici : il se fait par le bouton `StrategicReserveButton` porté par la
 * ligne de l'escouade dans la liste des unités à déployer. Une escouade qu'on n'a pas encore
 * choisi de déployer n'a rien à faire dans ce conteneur, et le geste reste là où est la décision.
 *
 * Les lignes sont au FORMAT COMMUN (`UnitRosterRow`), celui de la liste à déployer : même
 * escouade, même tête, qu'elle attende son déploiement ou son arrivée.
 *
 * Le ratio « 120/250 » est LU (`strategic_reserves` du moteur) ; il n'est jamais recalculé ici —
 * l'afficher autrement que le calcul qui refuse un dépôt, c'est afficher un mensonge.
 */
export function StrategicReservesContainer({
  reserveUnits,
  summary,
  player,
  unitsCache,
  boundIconSize,
  borderColor,
  onSelectReserveUnit,
  canSelectReserveUnit,
  placingUnitId = null,
  onCancelPlacement,
  phase,
  haloGlow,
}: {
  reserveUnits: Unit[];
  summary: StrategicReservesPlayerSummary | null;
  player: PlayerId;
  unitsCache: RosterRowUnitsCache;
  boundIconSize: boolean;
  /** Contour des lignes, couleur du joueur (identique à la liste à déployer). */
  borderColor: string;
  /** 20.04 — les escouades listées sont-elles cliquables pour demander leur aire d'arrivée ? */
  canSelectReserveUnit: boolean;
  onSelectReserveUnit?: (unitId: UnitId) => void;
  /** 20.04 — escouade dont l'ARRIVÉE est en cours de placement : sa ligne porte le `Reset`. */
  placingUnitId?: UnitId | null;
  onCancelPlacement?: () => void;
  /** Phase courante : décide de l'AFFICHAGE du conteneur vide (cf. corps). */
  phase: string | undefined;
  /** Halo vert de « cible active », partagé avec les lignes d'unités (`HALO_GLOW`). */
  haloGlow: string;
}): ReactElement | null {
  // Un conteneur VIDE hors déploiement ne dit rien : pas d'escouade à voir, pas de dépôt à
  // décider. Il resterait à l'écran en permanence, y compris avant qu'une partie soit chargée
  // (`phase` indéfinie) et dans les scénarios sans réserves. Pendant le DÉPLOIEMENT il reste
  // affiché même vide : son ratio est la seule lecture du plafond restant au moment où le joueur
  // décide de mettre une escouade de côté.
  if (reserveUnits.length === 0 && phase !== "deployment") {
    return null;
  }
  const ratio = formatStrategicReservesRatio(summary);
  return (
    <div
      data-testid={`strategic-reserves-container-${player}`}
      style={{
        marginTop: "4px",
        border: `2px solid ${RESERVES_BORDER_COLOR}`,
        borderRadius: "4px",
        backgroundColor: "#1b1b1b",
        padding: "4px 6px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          color: RESERVES_BORDER_COLOR,
          fontWeight: "bold",
          fontSize: "12px",
        }}
      >
        <span>STRATEGIC RESERVES</span>
        {/* Ratio 20.01 (plafond de 50 %), LU du moteur — jamais recalculé ici. */}
        <span data-testid={`strategic-reserves-ratio-${player}`}>{ratio}</span>
      </div>
      {reserveUnits.length > 0 && (
        <div style={{ marginTop: "3px", display: "flex", flexDirection: "column", gap: "4px" }}>
          {reserveUnits.map((unit) => (
            <div key={unit.id} data-testid={`strategic-reserves-unit-${unit.id}`}>
              <UnitRosterRow
                unit={unit}
                player={player}
                unitsCache={unitsCache}
                boundIconSize={boundIconSize}
                selected={false}
                interactive={canSelectReserveUnit}
                onClick={() => onSelectReserveUnit?.(unit.id)}
                borderColor={borderColor}
                haloGlow={haloGlow}
                trailing={
                  placingUnitId !== null &&
                  String(placingUnitId) === String(unit.id) &&
                  onCancelPlacement ? (
                    <ResetPlacementButton onReset={onCancelPlacement} />
                  ) : undefined
                }
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
