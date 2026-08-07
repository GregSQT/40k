import { describe, expect, it } from "vitest";
import {
  type DestroyableSprite,
  enqueueForIconLoad,
  type IconLoadSource,
  pendingIconQueueSize,
} from "./iconLoadQueue";

/** BaseTexture factice : compte les écouteurs posés et permet de déclencher "loaded" à la main. */
function makeSource(): IconLoadSource & { listeners: Array<() => void>; fire: () => void } {
  const listeners: Array<() => void> = [];
  return {
    listeners,
    once(_event: "loaded", handler: () => void) {
      listeners.push(handler);
      return this;
    },
    fire() {
      // ``once`` : chaque écouteur ne part qu'une fois, et seulement s'il s'exécute.
      const firing = listeners.splice(0, listeners.length);
      for (const handler of firing) handler();
    },
  };
}

function makeSprite(): DestroyableSprite {
  return { destroyed: false };
}

describe("enqueueForIconLoad", () => {
  it("ne pose QU'UN écouteur quelle que soit la quantité de rendus (le verrou de la fuite)", () => {
    const source = makeSource();
    const icon = "un-seul-ecouteur.png";

    // Le scénario réel : l'asset n'arrive jamais, donc "loaded" ne part jamais et rien ne se
    // retire tout seul. Chaque redraw réinscrit la même figurine.
    for (let redraw = 0; redraw < 500; redraw++) {
      enqueueForIconLoad(icon, source, makeSprite(), () => {});
    }

    expect(source.listeners.length).toBe(1);
  });

  it("ne retient pas les sprites détruits par les redraws précédents", () => {
    const source = makeSource();
    const icon = "purge-des-detruits.png";

    const survivor = makeSprite();
    enqueueForIconLoad(icon, source, survivor, () => {});
    for (let redraw = 0; redraw < 200; redraw++) {
      const dead = makeSprite();
      enqueueForIconLoad(icon, source, dead, () => {});
      dead.destroyed = true; // le redraw suivant détruit le sprite du précédent
    }

    // Le dernier inscrit n'a pas encore été détruit : le survivant initial + lui.
    expect(pendingIconQueueSize(icon)).toBe(2);
  });

  it("applique chaque sprite en attente au chargement, avec SON propre effet", () => {
    const source = makeSource();
    const icon = "application.png";
    const applied: string[] = [];

    enqueueForIconLoad(icon, source, makeSprite(), () => applied.push("petit"));
    enqueueForIconLoad(icon, source, makeSprite(), () => applied.push("grand"));
    expect(applied).toEqual([]);

    source.fire();

    expect(applied).toEqual(["petit", "grand"]);
    expect(pendingIconQueueSize(icon)).toBe(0);
  });

  it("n'applique pas un sprite détruit avant le chargement", () => {
    const source = makeSource();
    const icon = "detruit-avant-chargement.png";
    const applied: string[] = [];

    const doomed = makeSprite();
    enqueueForIconLoad(icon, source, doomed, () => applied.push("detruit"));
    enqueueForIconLoad(icon, source, makeSprite(), () => applied.push("vivant"));
    doomed.destroyed = true;

    source.fire();

    expect(applied).toEqual(["vivant"]);
  });

  it("repose un écouteur pour un chargement ultérieur de la même icône", () => {
    const source = makeSource();
    const icon = "re-inscription.png";

    enqueueForIconLoad(icon, source, makeSprite(), () => {});
    source.fire();
    expect(pendingIconQueueSize(icon)).toBe(0);

    enqueueForIconLoad(icon, source, makeSprite(), () => {});
    expect(source.listeners.length).toBe(1);
  });
});
