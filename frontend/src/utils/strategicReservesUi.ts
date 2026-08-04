import type { StrategicReservesPlayerSummary } from "../types/game";

/**
 * Décisions d'interface des réserves stratégiques (20.01 / 20.04).
 *
 * Ces fonctions ne CALCULENT aucune règle : elles combinent la phase, le joueur, et ce que le
 * moteur a déjà tranché (`strategic_reserves` de l'API). En particulier `placeable_unit_ids` porte
 * à lui seul les trois conditions de 20.01 (plafond de 50 %, pas FORTIFICATION, encore à poser) —
 * les rejouer ici donnerait deux formules pour une même règle, et l'UI proposerait des dépôts que
 * le moteur refuse (ou refuserait des dépôts qu'il accepte).
 */

/** Forme minimale d'une unité pour les sélecteurs ci-dessous — le hook manipule les unités BRUTES
 *  de l'API et la table leurs équivalents convertis ; seuls ces trois champs sont communs. */
interface ReserveSelectableUnit {
  player: number;
  HP_CUR: number;
  in_strategic_reserves?: boolean;
}

/**
 * Les escouades VIVANTES tenues en réserves (20.01), éventuellement bornées à un joueur.
 *
 * Un seul endroit décide de ce que « en réserves » veut dire. Le conteneur de la table et le
 * popup de dernier round s'accordaient jusqu'ici par discipline : la table excluait les mortes,
 * le hook non — donc l'avertissement 20.04 pouvait annoncer la destruction d'escouades que le
 * conteneur ne montrait pas.
 */
export function selectReserveUnits<T extends ReserveSelectableUnit>(
  units: readonly T[],
  player?: number
): T[] {
  return units.filter(
    (u) =>
      u.in_strategic_reserves === true &&
      u.HP_CUR > 0 &&
      (player === undefined || u.player === player)
  );
}

/** Ratio « 120/250 » affiché dans l'espace vide du conteneur. ``—`` tant que le moteur n'a rien dit. */
export function formatStrategicReservesRatio(
  summary: StrategicReservesPlayerSummary | null | undefined
): string {
  if (!summary) return "—";
  return `${summary.used_points}/${summary.cap_points}`;
}

/**
 * 20.01 — le conteneur accepte-t-il l'unité sélectionnée ?
 *
 * Phase de déploiement UNIQUEMENT, unité de CE joueur, et présente dans la liste que le moteur
 * accepterait. Hors déploiement la réponse est non, quel que soit le reste : le moteur ferme aussi
 * (cf. `test_strategic_reserves_deposit_is_refused_outside_the_deployment_phase`), l'UI ne fait
 * que ne pas proposer un geste voué au refus.
 */
export function canDropUnitIntoReserves(o: {
  phase: string | undefined;
  selectedUnitId: number | null;
  summary: StrategicReservesPlayerSummary | null | undefined;
}): boolean {
  if (o.phase !== "deployment") return false;
  if (o.selectedUnitId === null) return false;
  // Pas de contrôle d'appartenance au joueur ici : `placeable_unit_ids` est déjà construit à
  // partir de `deployable_units[player]` côté moteur, et le conteneur reçoit le résumé de SON
  // joueur. Le refaire côté client serait une seconde notion d'appartenance, qui ne peut que
  // diverger de celle qui décide vraiment.
  return (o.summary?.placeable_unit_ids ?? []).includes(String(o.selectedUnitId));
}

/**
 * 20.04 — une escouade DU conteneur est-elle cliquable pour demander son aire d'arrivée ?
 *
 * Phase de mouvement UNIQUEMENT et joueur dont c'est le tour. Que ce soit ou non le round
 * d'arrivée de CETTE escouade n'est PAS tranché ici : `ingress_preview` le dit (`not_yet_arriving`),
 * et le round d'arrivée peut être avancé par une capacité — une constante côté client se
 * tromperait sur ces unités-là.
 */
export function canSelectReserveUnitForIngress(o: {
  phase: string | undefined;
  tablePlayer: number;
  currentPlayer: number | undefined;
}): boolean {
  return o.phase === "move" && o.currentPlayer === o.tablePlayer;
}

/**
 * 20.04 — faut-il avertir CE joueur que ses réserves seront détruites à la fin du round ?
 *
 * Vrai au début du tour du joueur concerné, au round de destruction lu du moteur
 * (`strategic_reserves.last_round`), et seulement s'il lui reste des escouades hors table.
 * L'avertissement ne s'adresse jamais aux deux joueurs à la fois : `currentPlayer` est le filtre.
 */
export function shouldWarnReservesLastRound(o: {
  turn: number | undefined;
  lastRound: number | undefined;
  currentPlayer: number | undefined;
  /** Unités encore en réserves, tous joueurs confondus. */
  reserveUnits: ReadonlyArray<{ player: number }>;
}): boolean {
  if (o.turn === undefined || o.lastRound === undefined || o.currentPlayer === undefined) {
    return false;
  }
  if (o.turn !== o.lastRound) return false;
  return o.reserveUnits.some((u) => u.player === o.currentPlayer);
}
