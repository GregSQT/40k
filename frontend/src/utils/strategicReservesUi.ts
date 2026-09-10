import type {
  StrategicReservesPendingDeclaration,
  StrategicReservesPlayerSummary,
} from "../types/game";

/**
 * Décisions d'interface des réserves stratégiques (20.01 / 20.04).
 *
 * Ces fonctions ne CALCULENT aucune règle : elles combinent la phase, le joueur, et ce que le
 * moteur a déjà tranché (`strategic_reserves` de l'API). En particulier `pending_declaration`
 * porte à lui seul les trois conditions de 20.01 (plafond de 50 %, pas FORTIFICATION, encore à
 * poser) ET le moment où la question se pose — les rejouer ici donnerait deux formules pour une
 * même règle, et l'UI proposerait des dépôts que le moteur refuse.
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
 * 20.01 — l'étape Declare Battle Formations est-elle encore ouverte ?
 *
 * TANT QU'ELLE L'EST, AUCUNE POSE N'EST POSSIBLE : la règle situe la déclaration avant le
 * déploiement, et le moteur refuse `deploy_commit` (`reserves_declaration_still_open`). L'UI ne
 * fait que ne pas proposer un geste voué au refus — elle ne rejoue pas la règle, elle lit la
 * question que le moteur a posée.
 */
export function isReservesDeclarationStepOpen(o: {
  phase: string | undefined;
  pending: StrategicReservesPendingDeclaration | null | undefined;
}): boolean {
  if (o.phase !== "deployment") return false;
  return o.pending != null;
}

/**
 * 20.01 — la question en attente porte-t-elle sur CETTE unité, MAINTENANT ?
 *
 * Le client n'a aucune liste de candidats à filtrer : le moteur interroge une unité à la fois,
 * dans un ordre figé au reset, et publie laquelle. Reconstruire ici « quelles unités pourraient
 * partir en réserves » rouvrirait la sélection libre — donc la possibilité de déclarer après
 * avoir vu le déploiement adverse, le défaut que ce contrat ferme.
 *
 * `deploymentStarted` SÉPARE LA PRÉPARATION DE LA PARTIE. Tant que l'écran de préparation est
 * ouvert, le joueur choisit encore son armée ; 20.01 place la déclaration après que les listes
 * sont arrêtées, et le moteur refuse désormais le changement d'armée dès la première réponse
 * (`change_roster_locked_after_reserves_declaration`). Poser la question avant le démarrage
 * mettait les deux gestes dans la MÊME fenêtre : répondre y coûtait le droit de changer d'armée,
 * dans le seul écran où ce droit existe.
 */
export function isReservesDeclarationPendingFor(o: {
  phase: string | undefined;
  unitId: number | string;
  pending: StrategicReservesPendingDeclaration | null | undefined;
  deploymentStarted: boolean;
}): boolean {
  if (!o.deploymentStarted) return false;
  if (!isReservesDeclarationStepOpen({ phase: o.phase, pending: o.pending })) return false;
  return o.pending!.unitId === String(o.unitId);
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
 *
 * Et seulement à un joueur HUMAIN. L'avertissement est un modal plein écran à valider : sur le
 * tour du bot (PvE, `player_types[joueur] === "ai"`), il bloquerait l'humain pour lui annoncer
 * la destruction d'unités qui ne sont pas les siennes et sur lesquelles il ne peut rien.
 * `playerTypes` vient du moteur (`_attach_player_types`) — le type de joueur n'est jamais déduit
 * d'un numéro.
 *
 * Et jamais sur un état APERÇU (rembobinage non destructif). L'appelant mémorise « ce round-là,
 * ce joueur-là, c'est dit » pour ne pas rouvrir le popup à chaque réponse serveur : un
 * avertissement tiré sur un état rembobiné consommerait cette mémoire, et l'avertissement RÉEL
 * ne serait plus jamais émis au retour au live.
 */
export function shouldWarnReservesLastRound(o: {
  turn: number | undefined;
  lastRound: number | undefined;
  currentPlayer: number | undefined;
  playerTypes: Record<string, "human" | "ai"> | undefined;
  /** L'état affiché est un aperçu non destructif, pas la partie vivante. */
  isPreviewState: boolean;
  /** Unités encore en réserves, tous joueurs confondus. */
  reserveUnits: ReadonlyArray<{ player: number }>;
}): boolean {
  if (o.isPreviewState) return false;
  if (o.turn === undefined || o.lastRound === undefined || o.currentPlayer === undefined) {
    return false;
  }
  if (o.turn !== o.lastRound) return false;
  if (o.playerTypes?.[String(o.currentPlayer)] !== "human") return false;
  return o.reserveUnits.some((u) => u.player === o.currentPlayer);
}
