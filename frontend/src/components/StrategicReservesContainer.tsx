// frontend/src/components/StrategicReservesContainer.tsx
import type { MouseEvent, ReactElement } from "react";
import type { PlayerId } from "../types";
import type { StrategicReservesPlayerSummary, Unit, UnitId } from "../types/game";
import {
  formatStrategicReservesRatio,
  isUnitListedForDeclaration,
} from "../utils/strategicReservesUi";
import { type RosterRowUnitsCache, UnitRosterRow } from "./UnitRosterRow";

/** Contour ORANGE du conteneur de réserves — le distingue des lignes d'unités normales. */
export const RESERVES_BORDER_COLOR = "#ff8c00";

function _declarationButton(
  testId: string,
  label: string,
  background: string,
  onClick: () => void
): ReactElement {
  return (
    <button
      type="button"
      key={testId}
      data-testid={testId}
      onClick={(e: MouseEvent<HTMLButtonElement>) => {
        // La ligne entière est cliquable (sélection) : sans cet arrêt, la réponse rejouerait
        // aussi la sélection de l'escouade dont elle vient de retirer la question.
        e.stopPropagation();
        onClick();
      }}
      style={{
        flex: "0 0 auto",
        background,
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
      {label}
    </button>
  );
}

/**
 * 20.01 — le bouton `Reserve` d'une escouade SÉLECTIONNÉE pendant l'étape Declare Battle
 * Formations.
 *
 * UN SEUL bouton, et pas de `Deploy` en face : 20.01 dit « select one or more friendly units to
 * place in strategic reserves. Instead of setting up these units on the battlefield during
 * deployment » — ne pas réserver, c'est déployer, il n'y a rien à déclarer pour ça. La version
 * précédente posait une question fermée à deux boutons sur l'escouade que le moteur désignait,
 * dans un ordre figé ; la règle ne porte ni la question, ni l'ordre.
 *
 * Le composant n'apparaît QUE sur une escouade que le moteur liste comme déclarable
 * (`strategic_reserves.declarable`), donc il n'a aucune éligibilité à évaluer : le plafond de 50 %
 * et la clause FORTIFICATION ont déjà décidé côté moteur.
 */
export function ReserveButton({ onReserve }: { onReserve: () => void }): ReactElement {
  return _declarationButton(
    "strategic-reserves-declare",
    "Reserve",
    "var(--ui-green-validate)",
    onReserve
  );
}

/**
 * 20.01 — le bouton `Cancel` d'une escouade DU conteneur, tant que son camp n'a pas validé.
 *
 * La déclaration est un ENSEMBLE que le joueur compose, pas une suite de réponses définitives :
 * tant qu'il n'a pas validé, il n'a rien arrêté. N'apparaît que sur une escouade que le moteur
 * liste comme annulable (`strategic_reserves.cancellable`) — donc jamais après validation, ni sur
 * le conteneur adverse, ni hors de l'étape.
 */
export function CancelReserveButton({ onCancel }: { onCancel: () => void }): ReactElement {
  return _declarationButton(
    "strategic-reserves-cancel",
    "Cancel",
    "var(--ui-gray-cancel)",
    onCancel
  );
}

/**
 * 20.01 — le bandeau de l'étape Declare Battle Formations : QUI déclare, et `Validate`.
 *
 * Pas un modal bloquant, délibérément : le joueur doit pouvoir cliquer les lignes de sa liste
 * derrière pour y faire apparaître `Reserve`, et son conteneur pour `Cancel`. Le bandeau informe
 * et offre le seul geste qui n'est porté par aucune ligne — figer la déclaration.
 *
 * `Validate` est TOUJOURS actif : déclarer zéro réserve est une déclaration légale (« can
 * select »), et c'est même le cas majoritaire. Un bouton grisé sur un conteneur vide dirait au
 * joueur qu'il doit réserver quelque chose, ce qui est faux.
 */
export function ReservesDeclarationBanner({
  playerLabel,
  onValidate,
}: {
  playerLabel: string;
  onValidate: () => void;
}): ReactElement {
  return (
    <div
      data-testid="strategic-reserves-declaration-banner"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        marginBottom: "6px",
        padding: "6px 10px",
        border: `2px solid ${RESERVES_BORDER_COLOR}`,
        borderRadius: "4px",
        backgroundColor: "#1b1b1b",
        color: RESERVES_BORDER_COLOR,
        fontWeight: "bold",
        fontSize: "12px",
      }}
    >
      <span>STRATEGIC RESERVES DECLARATION — {playerLabel}</span>
      {_declarationButton(
        "strategic-reserves-validate",
        "Validate",
        "var(--ui-green-validate)",
        onValidate
      )}
    </div>
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
 * La MISE EN RÉSERVES ne se fait pas ici : elle se fait par `ReserveButton`, porté par la ligne
 * sélectionnée dans la liste des unités à déployer. Une escouade qu'on n'a pas encore choisi de
 * réserver n'a rien à faire dans ce conteneur, et le geste reste là où est la décision. Son
 * ANNULATION, elle, se fait ici (`CancelReserveButton`) : c'est ici que l'escouade réservée est
 * visible, tant que son camp n'a pas validé.
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
  cancellableUnitIds = [],
  onCancelReserve,
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
  /** 20.01 — escouades que le moteur dit ANNULABLES (`strategic_reserves.cancellable`) : leur
   *  ligne porte `Cancel`. Vide hors de l'étape, pour l'adversaire, ou après validation. */
  cancellableUnitIds?: readonly string[];
  onCancelReserve?: (unitId: UnitId) => void;
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
                trailing={(() => {
                  // 20.01 d'abord : pendant l'étape, l'escouade n'a aucune arrivée à annuler, elle
                  // n'est même pas encore « en réserves » de façon définitive. Les deux gestes ne
                  // coexistent jamais sur une même ligne — l'un vit avant la partie, l'autre
                  // pendant.
                  if (
                    onCancelReserve &&
                    isUnitListedForDeclaration({ unitId: unit.id, list: cancellableUnitIds })
                  ) {
                    return <CancelReserveButton onCancel={() => onCancelReserve(unit.id)} />;
                  }
                  if (
                    placingUnitId !== null &&
                    String(placingUnitId) === String(unit.id) &&
                    onCancelPlacement
                  ) {
                    return <ResetPlacementButton onReset={onCancelPlacement} />;
                  }
                  return undefined;
                })()}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
