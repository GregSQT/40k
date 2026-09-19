import { describe, expect, it } from "vitest";

import type { ReplayAction } from "./replayParser";
import { fightShotDetail, shootShotDetail } from "./replayShotDetails";

/**
 * Projection replay → détail par-attaque.
 *
 * Le contrat d'affichage (`ShootDetail`) n'admet que `"SUCCESS"` / `"FAILED"` côté blessure, et
 * `GameLog` n'affiche la sauvegarde, les dégâts et le marqueur Feel No Pain que sous ce garde.
 * La mêlée y recopiait le vocabulaire du journal (`"WOUND"`), dans une littérale non typée :
 * toute ligne de mêlée rendait « Bless: ✗ » sur une blessure réussie, puis perdait la fin de la
 * séquence. C'est ce que ces tests verrouillent, avec le passage des trois champs FNP.
 */
const fightAction = (over: Partial<ReplayAction> = {}): ReplayAction => ({
  type: "fight",
  timestamp: "12:00:00",
  turn: "T1",
  player: 1,
  hit_roll: 4,
  hit_result: "HIT",
  wound_roll: 6,
  wound_result: "WOUND",
  save_roll: 2,
  save_target: 3,
  damage: 1,
  ...over,
});

describe("fightShotDetail", () => {
  it("traduit le vocabulaire du journal vers celui du contrat d'affichage", () => {
    const detail = fightShotDetail(fightAction());
    expect(detail?.hitResult).toBe("HIT");
    expect(detail?.strengthResult).toBe("SUCCESS");
    expect(detail?.saveSuccess).toBe(false);
    expect(detail?.damageDealt).toBe(1);
  });

  it("rend FAILED sur une blessure ratée, jamais le mot du journal", () => {
    const detail = fightShotDetail(fightAction({ wound_result: "FAIL" }));
    expect(detail?.strengthResult).toBe("FAILED");
  });

  it("porte les trois champs Feel No Pain lus dans la ligne", () => {
    const detail = fightShotDetail(
      fightAction({ damage: 0, fnp_saves: 2, fnp_threshold: 4, fnp_attempts: 2 })
    );
    expect(detail?.fnpSaves).toBe(2);
    expect(detail?.fnpThreshold).toBe(4);
    expect(detail?.fnpAttempts).toBe(2);
  });

  it("ne rend aucun détail quand la ligne ne porte pas de jet de touche", () => {
    expect(fightShotDetail(fightAction({ hit_roll: undefined }))).toBeUndefined();
  });
});

describe("shootShotDetail", () => {
  it("dérive les résultats des seuils et porte les champs Feel No Pain", () => {
    const detail = shootShotDetail({
      type: "shoot",
      timestamp: "12:00:00",
      turn: "T1",
      player: 1,
      hit_roll: 4,
      hit_target: 3,
      wound_roll: 6,
      wound_target: 3,
      save_roll: 2,
      save_target: 3,
      damage: 1,
      fnp_saves: 1,
      fnp_threshold: 5,
      fnp_attempts: 3,
    });
    expect(detail?.hitResult).toBe("HIT");
    expect(detail?.strengthResult).toBe("SUCCESS");
    expect(detail?.saveSuccess).toBe(false);
    expect(detail?.fnpSaves).toBe(1);
    expect(detail?.fnpThreshold).toBe(5);
    expect(detail?.fnpAttempts).toBe(3);
  });
});
