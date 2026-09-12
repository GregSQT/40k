import type { StrategicReservesPlayerSummary, StrategicReservesSummary } from "../types/game";

/**
 * Décisions d'interface des réserves stratégiques (20.01 / 20.04).
 *
 * Ces fonctions ne CALCULENT aucune règle : elles combinent la phase, le joueur, et ce que le
 * moteur a déjà tranché (`strategic_reserves` de l'API). En particulier `declarable` et
 * `cancellable` portent à eux seuls les conditions de 20.01 (plafond de 50 %, pas FORTIFICATION,
 * encore à poser, camp qui a la main) — les rejouer ici donnerait deux formules pour une même
 * règle, et l'UI proposerait des dépôts que le moteur refuse.
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
 * fait que ne pas proposer un geste voué au refus — elle ne rejoue pas la règle, elle lit le camp
 * que le moteur dit en train de déclarer.
 */
export function isReservesDeclarationStepOpen(o: {
  phase: string | undefined;
  declaringPlayer: number | null | undefined;
}): boolean {
  if (o.phase !== "deployment") return false;
  return o.declaringPlayer != null;
}

/**
 * 20.01 — le camp HUMAIN qui compose sa déclaration MAINTENANT, ou `null`.
 *
 * C'est lui, et lui seul, dont les lignes portent le bouton `Reserve`, dont le conteneur porte
 * les boutons `Cancel`, et à qui le bandeau offre `Validate`. Chaque camp déclare pour TOUTE son
 * armée avant que l'autre commence — 20.01 dit « select one or more friendly units », une
 * formation de bataille, pas une escouade à la fois.
 *
 * `deploymentStarted` SÉPARE LA PRÉPARATION DE LA PARTIE. Tant que l'écran de préparation est
 * ouvert, le joueur choisit encore son armée ; 20.01 place la déclaration après que les listes
 * sont arrêtées, et le moteur refuse le changement d'armée dès le premier geste
 * (`change_roster_locked_after_reserves_declaration`). Ouvrir la déclaration avant le démarrage
 * mettrait les deux gestes dans la MÊME fenêtre : réserver y coûterait le droit de changer
 * d'armée, dans le seul écran où ce droit existe.
 *
 * ET SEULEMENT À UN SIÈGE HUMAIN. 20.01 dit « **you** can select one or more friendly units » :
 * la déclaration d'un camp appartient à son siège. En PvE, celle du bot est composée par le
 * modèle (`apply_reserves_declaration_decision`) et le moteur refuse la route humaine
 * (`reserves_declaration_seat_is_not_human`) — sans ce filtre, le client offrirait le temps d'un
 * aller-retour d'état des boutons qui ne peuvent que revenir en erreur. Le type de joueur vient
 * du moteur, jamais d'un numéro : même lecture que `shouldWarnReservesLastRound`.
 */
export function humanReservesDeclarer(o: {
  phase: string | undefined;
  declaringPlayer: number | null | undefined;
  deploymentStarted: boolean;
  playerTypes: Record<string, "human" | "ai"> | undefined;
}): number | null {
  if (!o.deploymentStarted) return null;
  if (!isReservesDeclarationStepOpen({ phase: o.phase, declaringPlayer: o.declaringPlayer })) {
    return null;
  }
  const player = o.declaringPlayer as number;
  if (o.playerTypes?.[String(player)] !== "human") return null;
  return player;
}

/**
 * 20.01 — CETTE escouade est-elle dans une des deux listes que le moteur publie pour le camp
 * déclarant ?
 *
 * Le client n'a aucune éligibilité à calculer : le plafond de 50 %, la clause FORTIFICATION et
 * « encore à poser » sont tranchés côté moteur (`reserves_declarable_squads`,
 * `reserves_cancellable_squads`), et c'est la même fonction qui refuse le dépôt. Les lignes du
 * panneau portent des ids numériques, le moteur publie des chaînes : la comparaison se fait en
 * chaîne, sans quoi rien ne matcherait jamais et les boutons resteraient invisibles.
 */
export function isUnitListedForDeclaration(o: {
  unitId: number | string;
  list: readonly string[] | undefined;
}): boolean {
  return (o.list ?? []).some((id) => String(id) === String(o.unitId));
}

/** Les trois lectures 20.01 du résumé moteur, sous une seule forme pour les appelants. */
export function readReservesDeclaration(summary: StrategicReservesSummary | undefined): {
  declaringPlayer: number | null;
  declarable: readonly string[];
  cancellable: readonly string[];
} {
  return {
    declaringPlayer: summary?.declaring_player ?? null,
    declarable: summary?.declarable ?? [],
    cancellable: summary?.cancellable ?? [],
  };
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
