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
import { fightShotDetail } from "../utils/replayShotDetails";
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
      />
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

  it("expose la bulle d'aide de [ENGAGED TARGET], règle de phase 17.03 (2026-09-18)", () => {
    // Jumeau de [POINT-BLANK] : le moteur pose le token sur le segment Hit de la ligne de
    // synthèse (`shared_utils`, `engaged_target_malus`) ; sans entrée dédiée il resterait du
    // texte nu.
    render(
      <GameLog
        events={[
          {
            ...shootEvent({}),
            message:
              "Unit 1 SHOT at Unit 2 - Shots:2 - Hit:3+->4+ [ENGAGED TARGET] Wound:4+ Save:3+ - HP lost:1 Killed:0",
          } as GameLogEvent,
        ]}
      />
    );
    const tag = screen.getByRole("button", {
      name: "Afficher la description de la regle ENGAGED TARGET",
    });
    fireEvent.mouseEnter(tag);
    expect(document.body.textContent).toContain("17.03");
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

  it("dit qu'une blessure critique [DEVASTATING WOUNDS] devient mortelle", () => {
    // 24.10 : la séquence d'attaque s'arrête sur la blessure critique et la cible subit des
    // blessures MORTELLES — le moteur n'écrit donc AUCUN `saveRoll`, et ce que la cible perd
    // n'est pas un dégât ordinaire. Sans ce segment, la ligne passait de « Bless: ✓ » au
    // silence.
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
    expect(shotRowText()).toContain("MW: 2 [DEVASTATING WOUNDS]");
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

/**
 * Feel No Pain 24.12 — le moteur jette le dé et pose `fnpSaves` / `fnpThreshold` / `fnpAttempts`
 * sur chaque record d'attaque, au site unique de résolution des blessures (tir ET mêlée). La
 * donnée voyageait jusqu'au navigateur sans jamais être affichée : un `Dmg: 0` sur une
 * sauvegarde RATÉE était indistinguable d'une attaque sans effet.
 *
 * Forme verrouillée ici : celle de step.log (`_damage_segment`, grammaire 16), au caractère près.
 */
describe("GameLog — jets Feel No Pain", () => {
  it("affiche le marqueur FNP accolé aux dégâts d'une sauvegarde ratée", () => {
    render(
      <GameLog
        events={[
          shootEvent({
            saveRoll: 2,
            saveTarget: 3,
            saveSuccess: false,
            damageDealt: 1,
            fnpSaves: 2,
            fnpThreshold: 5,
            fnpAttempts: 3,
          }),
        ]}
      />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("Dmg: 1 [FNP:2/5+ ×3]");
  });

  it("explique un MW: 0 dû à un FNP total sur une attaque dévastatrice (24.10)", () => {
    // 24.12 s'applique aux blessures mortelles comme aux dégâts : le segment `MW:` accole le
    // marqueur exactement comme le segment `Dmg:` d'une sauvegarde ratée.
    render(
      <GameLog
        events={[
          shootEvent({
            devastating: true,
            saveSuccess: false,
            damageDealt: 0,
            fnpSaves: 2,
            fnpThreshold: 4,
            fnpAttempts: 2,
          }),
        ]}
      />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("MW: 0 [DEVASTATING WOUNDS] [FNP:2/4+ ×2]");
  });

  it("n'affiche aucun marqueur quand aucun Feel No Pain n'a été jeté", () => {
    render(
      <GameLog
        events={[shootEvent({ saveRoll: 2, saveTarget: 3, saveSuccess: false, damageDealt: 1 })]}
      />
    );
    expandFirstEntry();
    // ANCRE POSITIVE : sans elle, une ligne qui ne rend rien satisferait le `not.toContain`.
    expect(shotRowText()).toContain("Dmg: 1");
    expect(shotRowText()).not.toContain("[FNP:");
  });

  it("accroche la bulle d'aide 24.12 au marqueur, dont le paramètre n'est pas un entier", () => {
    // Le résolveur ne savait retirer qu'un paramètre ENTIER ([RAPID FIRE:2]) : `1/5+ ×3` le
    // laissait sans description. Il retombe désormais sur le nom du token, `FNP`.
    render(
      <GameLog
        events={[
          shootEvent({
            saveRoll: 2,
            saveTarget: 3,
            saveSuccess: false,
            damageDealt: 1,
            fnpSaves: 1,
            fnpThreshold: 5,
            fnpAttempts: 3,
          }),
        ]}
      />
    );
    expandFirstEntry();
    const tag = screen.getByRole("button", {
      name: "Afficher la description de la regle FNP:1/5+ ×3",
    });
    fireEvent.mouseEnter(tag);
    expect(document.body.textContent).toContain("24.12");
  });

  it("lève sur un record de FNP incomplet plutôt que d'inventer un seuil", () => {
    // Les trois champs voyagent ensemble depuis le moteur : n'en afficher qu'une partie
    // décrirait un jet dont on ignore le seuil ou le nombre de dés.
    expect(() =>
      render(
        <GameLog
          events={[
            shootEvent({
              saveRoll: 2,
              saveTarget: 3,
              saveSuccess: false,
              damageDealt: 1,
              fnpSaves: 1,
              fnpAttempts: 3,
            }),
          ]}
        />
      )
    ).not.toThrow();
    expect(() => expandFirstEntry()).toThrow(/Incomplete Feel No Pain record/);
  });
});

/**
 * [DEVASTATING WOUNDS] 24.10 — sur une blessure critique, la séquence d'attaque S'ARRÊTE et la
 * cible subit des blessures MORTELLES égales à la caractéristique D ; 06.02 les résout en
 * retirant 1 PV par blessure, sans aucun jet, une figurine au plus par blessure critique.
 *
 * Le journal annonçait une sauvegarde « aucune » puis des « dégâts » — deux mots que la règle ne
 * prononce pas. Un segment unique les remplace, sur le tir comme sur la mêlée, qui partagent ce
 * rendu et divergeaient : la mêlée ne posait pas `devastating`, donc n'affichait rien du tout.
 */
describe("GameLog — blessures mortelles de [DEVASTATING WOUNDS]", () => {
  it("remplace le couple sauvegarde/dégâts par le nombre de blessures mortelles", () => {
    render(
      <GameLog events={[shootEvent({ devastating: true, saveSuccess: false, damageDealt: 2 })]} />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("MW: 2 [DEVASTATING WOUNDS]");
    expect(shotRowText()).not.toContain("Svg:");
    expect(shotRowText()).not.toContain("Dmg:");
  });

  it("nomme la règle sur une ligne de MÊLÉE projetée depuis step.log", () => {
    // Le vrai chemin du replay : le parseur pose `devastating_wounds_applied` sur la branche
    // FOUGHT (`Save [DEVASTATING WOUNDS]`), la projection le reporte, le rendu le nomme. Sans
    // le report, la ligne affichait ses dégâts SANS aucun segment de sauvegarde.
    const detail = fightShotDetail({
      type: "fight",
      timestamp: "12:00:00",
      turn: "T1",
      player: 1,
      hit_roll: 4,
      hit_result: "HIT",
      wound_roll: 6,
      wound_result: "WOUND",
      devastating_wounds_applied: true,
      damage: 2,
    });
    render(
      <GameLog
        events={[
          {
            id: "event_fight",
            timestamp: new Date(0),
            type: "combat",
            message: "Unit 1 FOUGHT Unit 2 - Save [DEVASTATING WOUNDS] - Dmg:2HP",
            turnNumber: 1,
            phase: "FIGHT",
            player: 1,
            shootDetails: [detail],
          } as unknown as GameLogEvent,
        ]}
      />
    );
    expandFirstEntry();
    expect(shotRowText()).toContain("MW: 2 [DEVASTATING WOUNDS]");
  });

  it("lève sur une attaque dévastatrice sans nombre de blessures mortelles", () => {
    // 24.10 fait de la caractéristique D le nombre de blessures mortelles : une attaque
    // dévastatrice dont on ignore la quantité est une donnée invalide, pas un cas d'affichage.
    render(<GameLog events={[shootEvent({ devastating: true, saveSuccess: false })]} />);
    expect(() => expandFirstEntry()).toThrow(/without damageDealt/);
  });
});

/**
 * Feel No Pain 24.12 sur les blessures MORTELLES — miroir du marqueur des attaques.
 *
 * 06.02 dit que la figurine sélectionnée perd 1 PV ; 24.12 dit que sur un X+ ce PV n'est pas
 * perdu. Le moteur jetait bien le dé et marquait le record, mais le détail par-figurine ne lisait
 * que la position et la mort : une blessure ANNULÉE s'affichait exactement comme une blessure
 * subie. Le seuil varie d'une figurine à l'autre (position, règles d'unité), donc il fait partie
 * du marqueur — sans lui, rien ne permet de vérifier que le dé a sauvé à bon droit.
 */
describe("GameLog — Feel No Pain sur blessures mortelles", () => {
  function mortalWoundEvent(details: Array<Record<string, unknown>>): GameLogEvent {
    return {
      id: "event_mw",
      timestamp: new Date(0),
      type: "hazardous",
      message: "Unit 3 SUFFERS 2 Mortal Wounds [HAZARDOUS]",
      turnNumber: 1,
      phase: "SHOOT",
      player: 1,
      unitId: 3,
      hazardDetails: details,
    } as unknown as GameLogEvent;
  }

  /** Texte de CHAQUE ligne du détail déplié, dans l'ordre. */
  function detailRowTexts(): string[] {
    const rows = document.querySelectorAll(".game-log-entry__shot-detail-row");
    if (rows.length === 0) {
      throw new Error("aucune ligne de détail rendue");
    }
    return Array.from(rows).map((r) => r.textContent ?? "");
  }

  it("dit qu'une blessure mortelle sauvée n'a pas été perdue, et laisse l'autre intacte", () => {
    render(
      <GameLog
        events={[
          mortalWoundEvent([
            {
              modelId: "3#1",
              col: 5,
              row: 7,
              died: false,
              fnpSaved: true,
              fnpSaves: 1,
              fnpThreshold: 5,
              fnpAttempts: 1,
            },
            {
              modelId: "3#1",
              col: 5,
              row: 7,
              died: false,
              fnpSaves: 0,
              fnpThreshold: 5,
              fnpAttempts: 1,
            },
          ]),
        ]}
      />
    );
    expandFirstEntry();
    const rows = detailRowTexts();
    expect(rows[0]).toContain("1 MW not lost at (5,7) [FNP:1/5+ ×1]");
    expect(rows[1]).toContain("1 MW at (5,7) [FNP:0/5+ ×1]");
    expect(rows[1]).not.toContain("not lost");
  });

  it("n'affiche aucun marqueur quand aucun Feel No Pain n'a été jeté", () => {
    render(
      <GameLog events={[mortalWoundEvent([{ modelId: "3#1", col: 2, row: 2, died: true }])]} />
    );
    expandFirstEntry();
    // ANCRE POSITIVE : sans elle, une ligne qui ne rend rien satisferait le `not.toContain`.
    expect(detailRowTexts()[0]).toContain("1 MW at (2,2) 💀");
    expect(detailRowTexts()[0]).not.toContain("[FNP:");
  });
});
