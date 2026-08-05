import { describe, expect, it } from "vitest";
import type { StrategicReservesPlayerSummary } from "../types/game";
import {
  canDropUnitIntoReserves,
  canSelectReserveUnitForIngress,
  formatStrategicReservesRatio,
  shouldWarnReservesLastRound,
} from "./strategicReservesUi";

/** 120 pts engagés sur un plafond de 250 : il reste 130 pts. L'unité 7 (130 pts) tient encore,
 *  l'unité 8 (131 pts) non — c'est le MOTEUR qui a tranché, la liste ne contient que 7. */
const SUMMARY_120_OF_250: StrategicReservesPlayerSummary = {
  used_points: 120,
  cap_points: 250,
  placeable_unit_ids: ["7"],
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

describe("canDropUnitIntoReserves — 20.01", () => {
  const base = {
    phase: "deployment" as string | undefined,
    summary: SUMMARY_120_OF_250,
  };

  it("BORNE du plafond : 130 pts passe, 131 pts ne passe pas", () => {
    // La borne elle-même est verrouillée côté moteur/API
    // (test_strategic_reserves_summary_only_offers_units_the_engine_would_accept) ; ici on
    // vérifie que l'UI SUIT cette liste au lieu de refaire la soustraction.
    expect(canDropUnitIntoReserves({ ...base, selectedUnitId: 7 })).toBe(true);
    expect(canDropUnitIntoReserves({ ...base, selectedUnitId: 8 })).toBe(false);
  });

  it("le dépôt n'existe QU'EN phase de déploiement", () => {
    for (const phase of ["command", "move", "shoot", "charge", "fight", undefined]) {
      expect(canDropUnitIntoReserves({ ...base, phase, selectedUnitId: 7 })).toBe(false);
    }
  });

  it("sans unité sélectionnée, le conteneur n'est pas une cible", () => {
    expect(canDropUnitIntoReserves({ ...base, selectedUnitId: null })).toBe(false);
  });

  it("un conteneur dont le résumé ne liste rien n'accepte aucun dépôt", () => {
    // Conteneur du joueur adverse : son résumé porte SES `placeable_unit_ids`, donc l'unité
    // sélectionnée par l'autre joueur n'y figure pas. C'est le moteur qui borne, pas le client.
    const other = { used_points: 0, cap_points: 250, placeable_unit_ids: [] };
    expect(canDropUnitIntoReserves({ ...base, summary: other, selectedUnitId: 7 })).toBe(false);
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
