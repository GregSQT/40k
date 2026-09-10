import { describe, expect, it } from "vitest";
import type {
  StrategicReservesPendingDeclaration,
  StrategicReservesPlayerSummary,
} from "../types/game";
import {
  canSelectReserveUnitForIngress,
  formatStrategicReservesRatio,
  isReservesDeclarationPendingFor,
  isReservesDeclarationStepOpen,
  shouldWarnReservesLastRound,
} from "./strategicReservesUi";

/** 120 pts engagés sur un plafond de 250 : le ratio affiché du conteneur. */
const SUMMARY_120_OF_250: StrategicReservesPlayerSummary = {
  used_points: 120,
  cap_points: 250,
};

/** La question 20.01 que le moteur pose : l'unité 7 du joueur 1, et elle seule. */
const PENDING_ON_7: StrategicReservesPendingDeclaration = { player: 1, unitId: "7" };

describe("formatStrategicReservesRatio", () => {
  it("affiche le ratio du moteur, jamais un calcul local", () => {
    expect(formatStrategicReservesRatio(SUMMARY_120_OF_250)).toBe("120/250");
  });

  it("n'invente pas de ratio quand le moteur n'a rien dit", () => {
    expect(formatStrategicReservesRatio(null)).toBe("—");
    expect(formatStrategicReservesRatio(undefined)).toBe("—");
  });
});

describe("isReservesDeclarationPendingFor — 20.01", () => {
  const base = {
    phase: "deployment" as string | undefined,
    pending: PENDING_ON_7,
    deploymentStarted: true,
  };

  it("la question porte sur UNE escouade, celle que le moteur désigne", () => {
    // L'éligibilité (plafond de 50 %, FORTIFICATION) est tranchée côté moteur
    // (test_strategic_reserves_summary_asks_only_about_a_unit_the_engine_would_accept) : le
    // client n'en refait rien, il compare l'identifiant que le moteur lui a donné.
    expect(isReservesDeclarationPendingFor({ ...base, unitId: 7 })).toBe(true);
    expect(isReservesDeclarationPendingFor({ ...base, unitId: 8 })).toBe(false);
  });

  it("l'identifiant est comparé en CHAÎNE, comme le moteur le publie", () => {
    // Les lignes du panneau portent des ids numériques, `pending_declaration.unitId` est une
    // chaîne : une comparaison stricte sans conversion ne matcherait jamais, et la question
    // resterait invisible — donc le déploiement bloqué sans que rien ne l'explique.
    expect(isReservesDeclarationPendingFor({ ...base, unitId: "7" })).toBe(true);
  });

  it("la déclaration n'existe QU'EN phase de déploiement", () => {
    for (const phase of ["command", "move", "shoot", "charge", "fight", undefined]) {
      expect(isReservesDeclarationPendingFor({ ...base, phase, unitId: 7 })).toBe(false);
    }
  });

  it("étape close : plus aucune question, donc plus aucun bouton", () => {
    for (const pending of [null, undefined]) {
      expect(isReservesDeclarationStepOpen({ phase: "deployment", pending })).toBe(false);
      expect(isReservesDeclarationPendingFor({ ...base, pending, unitId: 7 })).toBe(false);
    }
  });

  it("aucune question tant que le déploiement n'a pas démarré", () => {
    // L'écran de préparation est la SEULE fenêtre où le joueur peut encore changer d'armée, et
    // le moteur refuse ce changement dès la première réponse 20.01
    // (`change_roster_locked_after_reserves_declaration`). Poser la question là ferait payer le
    // droit de changer d'armée pour un geste que le joueur n'a pas demandé à faire maintenant.
    expect(isReservesDeclarationPendingFor({ ...base, deploymentStarted: false, unitId: 7 })).toBe(
      false
    );
    // VERT VACANT : la même question, déploiement démarré, est bien posée.
    expect(isReservesDeclarationPendingFor({ ...base, deploymentStarted: true, unitId: 7 })).toBe(
      true
    );
  });

  it("étape ouverte dès qu'une question existe, quelle que soit l'escouade visée", () => {
    // C'est ce prédicat-là qui gèle la liste de pose : tant qu'une question est en attente, le
    // moteur refuse `deploy_commit` pour les DEUX joueurs, pas seulement pour l'interrogé.
    expect(isReservesDeclarationStepOpen({ phase: "deployment", pending: PENDING_ON_7 })).toBe(
      true
    );
  });
});

describe("canSelectReserveUnitForIngress — 20.04", () => {
  it("le retrait n'existe QU'EN phase de mouvement", () => {
    for (const phase of ["deployment", "command", "shoot", "charge", "fight", undefined]) {
      expect(canSelectReserveUnitForIngress({ phase, tablePlayer: 1, currentPlayer: 1 })).toBe(
        false
      );
    }
    expect(
      canSelectReserveUnitForIngress({ phase: "move", tablePlayer: 1, currentPlayer: 1 })
    ).toBe(true);
  });

  it("le conteneur ADVERSE reste visible mais n'est pas jouable", () => {
    expect(
      canSelectReserveUnitForIngress({ phase: "move", tablePlayer: 2, currentPlayer: 1 })
    ).toBe(false);
  });
});

describe("shouldWarnReservesLastRound — 20.04", () => {
  const reserves = [{ player: 1 }];
  /** PvP local : les deux joueurs sont humains. */
  const bothHuman: Record<string, "human" | "ai"> = { "1": "human", "2": "human" };

  it("avertit le joueur concerné au round de destruction lu du moteur", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 1,
        playerTypes: bothHuman,
        isPreviewState: false,
        reserveUnits: reserves,
      })
    ).toBe(true);
  });

  it("n'avertit PAS l'autre joueur, qui n'a rien en réserves", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 2,
        playerTypes: bothHuman,
        isPreviewState: false,
        reserveUnits: reserves,
      })
    ).toBe(false);
  });

  it("n'avertit pas avant le round de destruction", () => {
    for (const turn of [1, 2]) {
      expect(
        shouldWarnReservesLastRound({
          turn,
          lastRound: 3,
          currentPlayer: 1,
          playerTypes: bothHuman,
          isPreviewState: false,
          reserveUnits: reserves,
        })
      ).toBe(false);
    }
  });

  it("n'avertit pas un joueur dont toutes les réserves sont arrivées", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 1,
        playerTypes: bothHuman,
        isPreviewState: false,
        reserveUnits: [],
      })
    ).toBe(false);
  });

  it("sans round de destruction moteur, aucun avertissement n'est inventé", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: undefined,
        currentPlayer: 1,
        playerTypes: bothHuman,
        isPreviewState: false,
        reserveUnits: reserves,
      })
    ).toBe(false);
  });

  // PvE : le modal est un backdrop plein écran à valider. Sur le tour du BOT il bloquerait
  // l'humain pour lui annoncer la destruction d'unités qui ne sont pas les siennes.
  it("n'avertit pas sur le tour d'un joueur IA, même s'il a des réserves", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 2,
        playerTypes: { "1": "human", "2": "ai" },
        isPreviewState: false,
        reserveUnits: [{ player: 2 }],
      })
    ).toBe(false);
  });

  it("l'humain du même PvE reste averti de SES réserves", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 1,
        playerTypes: { "1": "human", "2": "ai" },
        isPreviewState: false,
        reserveUnits: reserves,
      })
    ).toBe(true);
  });

  // Rembobinage : le popup consommerait la clé `round:joueur` mémorisée par l'appelant, et
  // l'avertissement RÉEL ne serait plus émis au retour au live — réserves détruites en silence.
  it("n'avertit pas sur un état APERÇU, même quand tout le reste est réuni", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 1,
        playerTypes: bothHuman,
        isPreviewState: true,
        reserveUnits: reserves,
      })
    ).toBe(false);
  });

  // `player_types` vient du moteur (`_attach_player_types`) : tant qu'il n'a rien dit, le type
  // de joueur n'est pas devinable et aucun modal bloquant ne s'ouvre.
  it("sans player_types, aucun avertissement", () => {
    expect(
      shouldWarnReservesLastRound({
        turn: 3,
        lastRound: 3,
        currentPlayer: 1,
        playerTypes: undefined,
        isPreviewState: false,
        reserveUnits: reserves,
      })
    ).toBe(false);
  });
});
