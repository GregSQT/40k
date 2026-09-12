import { describe, expect, it } from "vitest";
import type { StrategicReservesPlayerSummary, StrategicReservesSummary } from "../types/game";
import {
  canSelectReserveUnitForIngress,
  formatStrategicReservesRatio,
  humanReservesDeclarer,
  isReservesDeclarationStepOpen,
  isUnitListedForDeclaration,
  readReservesDeclaration,
  shouldWarnReservesLastRound,
} from "./strategicReservesUi";

/** 120 pts engagés sur un plafond de 250 : le ratio affiché du conteneur. */
const SUMMARY_120_OF_250: StrategicReservesPlayerSummary = {
  used_points: 120,
  cap_points: 250,
};

describe("formatStrategicReservesRatio", () => {
  it("affiche le ratio du moteur, jamais un calcul local", () => {
    expect(formatStrategicReservesRatio(SUMMARY_120_OF_250)).toBe("120/250");
  });

  it("n'invente pas de ratio quand le moteur n'a rien dit", () => {
    expect(formatStrategicReservesRatio(null)).toBe("—");
    expect(formatStrategicReservesRatio(undefined)).toBe("—");
  });
});

describe("humanReservesDeclarer — 20.01", () => {
  const base = {
    phase: "deployment" as string | undefined,
    declaringPlayer: 1 as number | null | undefined,
    deploymentStarted: true,
    playerTypes: { "1": "human", "2": "ai" } as Record<string, "human" | "ai"> | undefined,
  };

  it("rend le camp humain que le moteur dit en train de déclarer", () => {
    expect(humanReservesDeclarer(base)).toBe(1);
  });

  it("la déclaration n'existe QU'EN phase de déploiement", () => {
    for (const phase of ["command", "move", "shoot", "charge", "fight", undefined]) {
      expect(humanReservesDeclarer({ ...base, phase })).toBeNull();
    }
  });

  it("étape close : plus aucun déclarant, donc plus aucun bouton", () => {
    for (const declaringPlayer of [null, undefined]) {
      expect(isReservesDeclarationStepOpen({ phase: "deployment", declaringPlayer })).toBe(false);
      expect(humanReservesDeclarer({ ...base, declaringPlayer })).toBeNull();
    }
  });

  it("aucune déclaration tant que le déploiement n'a pas démarré", () => {
    // L'écran de préparation est la SEULE fenêtre où le joueur peut encore changer d'armée, et
    // le moteur refuse ce changement dès le premier geste 20.01
    // (`change_roster_locked_after_reserves_declaration`). Ouvrir la déclaration là ferait payer
    // le droit de changer d'armée pour un geste que le joueur n'a pas demandé à faire maintenant.
    expect(humanReservesDeclarer({ ...base, deploymentStarted: false })).toBeNull();
    // VERT VACANT : le même état, déploiement démarré, ouvre bien la déclaration.
    expect(humanReservesDeclarer({ ...base, deploymentStarted: true })).toBe(1);
  });

  it("la déclaration d'un siège piloté par le modèle n'est jamais rendue au client", () => {
    // 20.01 : « you can select one or more friendly units » — la liste d'un camp se décide depuis
    // son siège. En PvE le moteur refuse la route humaine sur ce camp
    // (`reserves_declaration_seat_is_not_human`) : les boutons ne pourraient que revenir en
    // erreur, et le temps d'un aller-retour d'état l'humain choisirait la liste de son adversaire.
    expect(humanReservesDeclarer({ ...base, declaringPlayer: 2 })).toBeNull();
    // VERT VACANT : le MÊME camp, sur un siège humain, déclare bien — l'absence ci-dessus vient
    // du siège, pas du joueur 2 en tant que numéro.
    expect(
      humanReservesDeclarer({
        ...base,
        declaringPlayer: 2,
        playerTypes: { "1": "human", "2": "human" },
      })
    ).toBe(2);
  });

  it("aucun type de joueur connu : aucun déclarant, jamais un siège déduit d'un numéro", () => {
    // Même doctrine que `shouldWarnReservesLastRound` : le type de joueur vient du moteur. Sans
    // lui, offrir les boutons reviendrait à parier que le siège déclarant est humain.
    expect(humanReservesDeclarer({ ...base, playerTypes: undefined })).toBeNull();
  });

  it("étape ouverte dès qu'un camp déclare, quel qu'il soit", () => {
    // C'est ce prédicat-là qui gèle la liste de pose : tant qu'un camp déclare, le moteur refuse
    // `deploy_commit` pour les DEUX joueurs, pas seulement pour le déclarant.
    expect(isReservesDeclarationStepOpen({ phase: "deployment", declaringPlayer: 2 })).toBe(true);
  });
});

describe("isUnitListedForDeclaration — 20.01", () => {
  it("l'escouade est dans la liste que le moteur publie, ou elle n'y est pas", () => {
    // L'éligibilité (plafond de 50 %, FORTIFICATION, encore à poser) est tranchée côté moteur
    // (test_strategic_reserves_summary_asks_only_about_a_unit_the_engine_would_accept) : le
    // client n'en refait rien, il regarde si l'identifiant est dans la liste reçue.
    expect(isUnitListedForDeclaration({ unitId: 7, list: ["7", "9"] })).toBe(true);
    expect(isUnitListedForDeclaration({ unitId: 8, list: ["7", "9"] })).toBe(false);
  });

  it("l'identifiant est comparé en CHAÎNE, comme le moteur le publie", () => {
    // Les lignes du panneau portent des ids numériques, le moteur publie des chaînes : une
    // comparaison stricte sans conversion ne matcherait jamais, et les boutons resteraient
    // invisibles — donc le déploiement bloqué sans que rien ne l'explique.
    expect(isUnitListedForDeclaration({ unitId: "7", list: ["7"] })).toBe(true);
  });

  it("liste absente : rien n'est listé, aucun bouton inventé", () => {
    expect(isUnitListedForDeclaration({ unitId: 7, list: undefined })).toBe(false);
  });
});

describe("readReservesDeclaration — 20.01", () => {
  it("lit les trois champs du résumé moteur", () => {
    const summary: StrategicReservesSummary = {
      declaring_player: 2,
      declarable: ["11"],
      cancellable: ["12"],
    };
    expect(readReservesDeclaration(summary)).toEqual({
      declaringPlayer: 2,
      declarable: ["11"],
      cancellable: ["12"],
    });
  });

  it("sans résumé, aucun déclarant et deux listes vides — jamais une clé absente", () => {
    expect(readReservesDeclaration(undefined)).toEqual({
      declaringPlayer: null,
      declarable: [],
      cancellable: [],
    });
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
