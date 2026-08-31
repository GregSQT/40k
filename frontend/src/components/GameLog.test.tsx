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

/** Texte COMPLET de la ligne de détail du premier tir.
 *
 *  Pas `getByText` : un token de règle reconnu est rendu en `RuleReferenceTag` (un `<button>`
 *  enfant), donc la ligne est répartie sur plusieurs nœuds et aucune regex ne matche un nœud
 *  unique. Le `textContent` du conteneur est insensible à ce découpage — et ne dépend donc pas
 *  de la présence d'une description pour telle ou telle règle dans les configs. */
function shotRowText(): string {
  const row = document.querySelector(".game-log-entry__shot-detail-row");
  if (row === null) {
    throw new Error("aucune ligne de détail de tir rendue");
  }
  return row.textContent ?? "";
}

describe("GameLog — tokens de relance", () => {
  it("affiche [OATH OF MOMENT] sur le jet de touche relancé", () => {
    render(<GameLog events={[shootEvent({ hitAbility: "Oath of Moment" })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("Tir: ✓ (4) [OATH OF MOMENT]");
  });

  it("affiche la capacité de relance de BLESSURE sur le jet de blessure", () => {
    render(<GameLog events={[shootEvent({ woundAbility: "Targeted Intercession" })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("Bless: ✓ (5) [TARGETED INTERCESSION]");
  });

  it("affiche le +1 de blessure d'Oath, qui n'est PAS une relance", () => {
    render(<GameLog events={[shootEvent({ woundBonusAbility: "Oath of Moment" })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("Bless: ✓ (5) [OATH OF MOMENT]");
  });

  it("nomme les MODIFICATEURS de seuil de la Primitive A, sur les deux jets", () => {
    // Les seuils (`hitTarget`, `woundTarget`) arrivent DÉJÀ NETS du moteur : sans ces tokens,
    // une escouade menée par un Warboss touche à 3+ dans le Game Log avec une datasheet à 4+ et
    // rien ne l'explique. Trois champs distincts, parce que les trois jouent ensemble.
    render(
      <GameLog
        events={[
          shootEvent({
            hitRollBonusAbility: "Might Is Right",
            hitRollMalusAbility: "Suppressed",
            woundRollBonusAbility: "Litany of Hate",
          }),
        ]}
      />,
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("Tir: ✓ (4) [MIGHT IS RIGHT] [SUPPRESSED]");
    expect(shotRowText()).toContain("Bless: ✓ (5) [LITANY OF HATE]");
  });

  it("n'affiche AUCUN token quand aucune relance n'a eu lieu", () => {
    render(<GameLog events={[shootEvent({})]} />);
    expandFirstEntry();
    // ANCRE POSITIVE d'abord : sans elle, une ligne qui ne rend RIEN satisfait le `not.toContain`
    // et ce test vert affirmerait le contraire de la vérité.
    expect(shotRowText()).toContain("Tir: ✓ (4)");
    expect(shotRowText()).not.toContain("[");
  });

  it("accroche la bulle d'aide de la règle au token, comme sur la ligne de résumé", () => {
    // Le token posé sur la ligne de tir a la MÊME forme `[NOM]` que celui du message moteur :
    // il doit passer par le même rendu, donc devenir un bouton de description.
    render(<GameLog events={[shootEvent({ woundAbility: "Targeted Intercession" })]} />);
    expandFirstEntry();
    expect(
      screen.getByRole("button", {
        name: "Afficher la description de la regle TARGETED INTERCESSION",
      })
    ).toBeTruthy();
  });

  it("expose la bulle d'aide d'OATH OF MOMENT, capacité de FACTION", () => {
    // Oath n'est portée par aucune datasheet : sans entrée dédiée au registre des règles, son
    // token restait du texte nu, seul token du log à ne pas exposer sa règle au survol.
    render(<GameLog events={[shootEvent({ hitAbility: "Oath of Moment" })]} />);
    expandFirstEntry();
    const tag = screen.getByRole("button", {
      name: "Afficher la description de la regle OATH OF MOMENT",
    });
    fireEvent.mouseEnter(tag);
    // La description AFFICHÉE doit être celle du registre, pas une chaîne vide rendue en bulle.
    expect(document.body.textContent).toContain("Oath of Moment target");
  });

  it("expose la bulle d'aide de [WAAAGH!], capacité de FACTION elle aussi", () => {
    // JUMEAU du test ci-dessus. Le moteur pose `[WAAAGH!]` sur la ligne de synthèse (`Shots:`,
    // `Wound:`, `Save:`) et sur la charge après Advance ; le `!` fait partie de la clé, donc une
    // entrée nommée « Waaagh » sans lui ne serait jamais trouvée.
    render(
      <GameLog
        events={[
          {
            ...shootEvent({}),
            message:
              "Unit 1 FOUGHT at Unit 2 - Shots:2 [WAAAGH!] - Hit:3+ Wound:3+ [WAAAGH!] Save:5+ [WAAAGH!] - HP lost:1 Killed:0",
          } as GameLogEvent,
        ]}
      />
    );
    const tags = screen.getAllByRole("button", {
      name: "Afficher la description de la regle WAAAGH!",
    });
    expect(tags.length).toBe(3);
    fireEvent.mouseEnter(tags[0]);
    expect(document.body.textContent).toContain("5+ invulnerable save");
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
    expect(shotRowText()).toContain("Tir: ✓ (1->3) [OATH OF MOMENT]");
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
    expect(shotRowText()).toContain("Bless: ✓ (1->6)");
    expect(shotRowText()).toContain("Svg: ✓ (1->4)");
  });

  it("n'affiche aucun dé sur une attaque qui n'en jette pas ([TORRENT])", () => {
    // Le moteur envoie `null`, pas l'absence de clé : c'est ce qui affichait « Tir: ✓ (null) ».
    render(<GameLog events={[shootEvent({ attackRoll: null })]} />);
    expandFirstEntry();
    expect(shotRowText()).not.toContain("null");
    expect(shotRowText()).toContain("Tir: ✓ |");
  });

  it("n'affiche aucun dé de blessure sur [LETHAL HITS] (blessure automatique)", () => {
    render(<GameLog events={[shootEvent({ strengthRoll: null })]} />);
    expandFirstEntry();
    // ANCRE POSITIVE : le segment Bless doit EXISTER, sans son dé. Sans cette ligne, un rendu
    // qui sauterait entièrement la blessure passerait pour un succès.
    expect(shotRowText()).toContain("Bless: ✓");
    expect(shotRowText()).not.toContain("null");
  });

  it("n'affiche qu'un seul dé quand il n'y a pas eu de relance", () => {
    render(<GameLog events={[shootEvent({ attackRoll: 4 })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("Tir: ✓ (4)");
    expect(shotRowText()).not.toContain("->");
  });
});

/**
 * Règles d'ARME ayant joué sur UN dé. Le moteur ne pose que des drapeaux booléens sur le record
 * (`autoHit`, `sustainedHit`, `criticalHit`, `lethalHit`, `criticalWound`, `devastating`) plus la
 * cause de relance d'arme (`woundRerollRule`) : c'est l'affichage qui les nomme. Ces données
 * voyageaient déjà jusqu'au navigateur sans jamais être rendues — un dé [TORRENT] était
 * indiscernable d'un jet, et une blessure [DEVASTATING WOUNDS] faisait simplement disparaître la
 * sauvegarde de la ligne, sans dire pourquoi.
 */
describe("GameLog — règles d'arme par dé", () => {
  it("nomme la touche automatique de [TORRENT]", () => {
    render(<GameLog events={[shootEvent({ attackRoll: null, autoHit: true })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("[TORRENT]");
  });

  it("nomme la touche additionnelle de [SUSTAINED HITS] et le critique qui l'a produite", () => {
    render(
      <GameLog events={[shootEvent({ attackRoll: 6, criticalHit: true, sustainedHit: true })]} />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("[CRITICAL HIT]");
    expect(shotRowText()).toContain("[SUSTAINED HITS]");
  });

  it("nomme la blessure automatique de [LETHAL HITS]", () => {
    render(<GameLog events={[shootEvent({ strengthRoll: null, lethalHit: true })]} />);
    expandFirstEntry();
    expect(shotRowText()).toContain("[LETHAL HITS]");
  });

  it("nomme la relance d'arme [TWIN-LINKED], distincte d'une capacité d'unité", () => {
    render(
      <GameLog
        events={[
          shootEvent({ strengthRoll: 5, strengthRollInitial: 1, woundRerollRule: "TWIN-LINKED" }),
        ]}
      />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("(1->5)");
    expect(shotRowText()).toContain("[TWIN-LINKED]");
  });

  it("explique la sauvegarde absente d'une blessure [DEVASTATING WOUNDS]", () => {
    // 24.10 : « no saving throw can be made » — le moteur n'écrit AUCUN `saveRoll`. Sans ce
    // segment, la ligne passait de « Bless: ✓ » à « Dmg: 2 » sans rien dire de la sauvegarde.
    render(
      <GameLog
        events={[
          shootEvent({
            strengthRoll: 6,
            criticalWound: true,
            devastating: true,
            damageDealt: 2,
          }),
        ]}
      />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("[CRITICAL WOUND]");
    expect(shotRowText()).toContain("Svg: aucune [DEVASTATING WOUNDS]");
    expect(shotRowText()).toContain("Dmg: 2");
  });

  it("ne nomme aucune règle sur une attaque ordinaire", () => {
    // Sans elle, un rendu qui écrirait les tokens INCONDITIONNELLEMENT passerait les cinq
    // tests ci-dessus.
    render(<GameLog events={[shootEvent({ attackRoll: 4, strengthRoll: 5, saveRoll: 2 })]} />);
    expandFirstEntry();
    const row = shotRowText();
    for (const token of [
      "TORRENT",
      "SUSTAINED HITS",
      "CRITICAL HIT",
      "LETHAL HITS",
      "CRITICAL WOUND",
      "TWIN-LINKED",
      "DEVASTATING WOUNDS",
    ]) {
      expect(row).not.toContain(token);
    }
  });
});

describe("GameLog — token [HALF RANGE]", () => {
  it("expose la bulle d'aide de [HALF RANGE] dans le message de synthèse", () => {
    // [HALF RANGE] est posé sur la ligne de synthèse par step_logger (§24.25/24.30) quand la
    // cible était à demi-portée d'une arme RAPID_FIRE ou MELTA. Sans entrée dans le registre,
    // le token restait du texte brut non cliquable.
    render(
      <GameLog
        events={[
          {
            ...shootEvent({}),
            message:
              "Unit 1 SHOT [HALF RANGE] Unit 2 with [Bolt rifle] - Shots:2 - Hit:3+ Wound:4+ Save:3+ - HP lost:1 Killed:0",
          } as unknown as GameLogEvent,
        ]}
      />
    );
    const tag = screen.getByRole("button", {
      name: "Afficher la description de la regle HALF RANGE",
    });
    fireEvent.mouseEnter(tag);
    expect(document.body.textContent).toContain("half the weapon's range");
  });
});
