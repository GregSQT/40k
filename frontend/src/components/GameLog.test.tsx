// @vitest-environment jsdom
/**
 * Combat log — capacités de relance EFFECTUÉES.
 *
 * Le moteur nomme, sur CHAQUE record de tir/combat, la capacité qui a ouvert une relance
 * (`hitAbility` côté touche — « Oath of Moment » 08.04 —, `woundAbility` côté blessure). La donnée
 * voyageait déjà jusqu'au navigateur dans `shootDetails` sans jamais être affichée : un jet relancé
 * était indiscernable d'un jet direct. Ce test verrouille le token, au même format majuscule que
 * `step.log`, et son ABSENCE quand aucune relance n'a eu lieu.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { GameLog, type GameLogEvent } from "./GameLog";

afterEach(cleanup);

function shootEvent(shot: Record<string, unknown>): GameLogEvent {
  return {
    id: "event_1",
    timestamp: new Date(0),
    type: "shoot",
    message: "Unit 1 SHOT at Unit 2 - Shots:1 - Hit:3+ Wound:4+ Save:3+ - HP lost:1 Killed:0",
    turnNumber: 1,
    phase: "SHOOT",
    player: 1,
    unitId: 1,
    targetId: 2,
    weaponName: "Bolt rifle",
    shootDetails: [
      {
        shotNumber: 1,
        attackRoll: 4,
        strengthRoll: 5,
        hitResult: "HIT",
        strengthResult: "SUCCESS",
        ...shot,
      },
    ],
  } as unknown as GameLogEvent;
}

/** Le détail par tir n'est rendu qu'une fois la ligne dépliée. */
function expandFirstEntry(): void {
  fireEvent.click(screen.getByRole("button", { name: "Voir le détail" }));
}

describe("GameLog — tokens de relance", () => {
  it("affiche [OATH OF MOMENT] sur le jet de touche relancé", () => {
    render(<GameLog events={[shootEvent({ hitAbility: "Oath of Moment" })]} />);
    expandFirstEntry();
    expect(screen.getByText(/Tir: ✓ \(4\) \[OATH OF MOMENT\]/)).toBeTruthy();
  });

  it("affiche la capacité de relance de BLESSURE sur le jet de blessure", () => {
    render(<GameLog events={[shootEvent({ woundAbility: "Targeted Intercession" })]} />);
    expandFirstEntry();
    expect(screen.getByText(/Bless: ✓ \(5\) \[TARGETED INTERCESSION\]/)).toBeTruthy();
  });

  it("affiche le +1 de blessure d'Oath, qui n'est PAS une relance", () => {
    render(<GameLog events={[shootEvent({ woundBonusAbility: "Oath of Moment" })]} />);
    expandFirstEntry();
    expect(screen.getByText(/Bless: ✓ \(5\) \[OATH OF MOMENT\]/)).toBeTruthy();
  });

  it("n'affiche AUCUN token quand aucune relance n'a eu lieu", () => {
    render(<GameLog events={[shootEvent({})]} />);
    expandFirstEntry();
    const row = screen.getByText(/Tir: ✓ \(4\)/);
    expect(row.textContent).not.toContain("[");
  });
});

describe("GameLog — jets relancés", () => {
  it("affiche « initial->final » sur la touche relancée", () => {
    render(
      <GameLog
        events={[shootEvent({ attackRoll: 3, attackRollInitial: 1, hitAbility: "Oath of Moment" })]}
      />
    );
    expandFirstEntry();
    expect(screen.getByText(/Tir: ✓ \(1->3\) \[OATH OF MOMENT\]/)).toBeTruthy();
  });

  it("affiche « initial->final » sur la blessure et la sauvegarde relancées", () => {
    render(
      <GameLog
        events={[
          shootEvent({
            strengthRoll: 6,
            strengthRollInitial: 1,
            saveRoll: 4,
            saveRollInitial: 1,
            saveSuccess: true,
          }),
        ]}
      />
    );
    expandFirstEntry();
    const row = screen.getByText(/Bless: ✓ \(1->6\)/);
    expect(row.textContent).toContain("Svg: ✓ (1->4)");
  });

  it("n'affiche aucun dé sur une attaque qui n'en jette pas ([TORRENT])", () => {
    // Le moteur envoie `null`, pas l'absence de clé : c'est ce qui affichait « Tir: ✓ (null) ».
    render(<GameLog events={[shootEvent({ attackRoll: null })]} />);
    expandFirstEntry();
    const row = screen.getByText(/Tir: ✓/);
    expect(row.textContent).not.toContain("null");
    expect(row.textContent).toContain("Tir: ✓ |");
  });

  it("n'affiche aucun dé de blessure sur [LETHAL HITS] (blessure automatique)", () => {
    render(<GameLog events={[shootEvent({ strengthRoll: null })]} />);
    expandFirstEntry();
    const row = screen.getByText(/Bless: ✓/);
    expect(row.textContent).not.toContain("null");
  });

  it("n'affiche qu'un seul dé quand il n'y a pas eu de relance", () => {
    render(<GameLog events={[shootEvent({ attackRoll: 4 })]} />);
    expandFirstEntry();
    expect(screen.getByText(/Tir: ✓ \(4\)/).textContent).not.toContain("->");
  });
});
