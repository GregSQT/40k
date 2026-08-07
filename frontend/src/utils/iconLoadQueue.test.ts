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
    valid: false,
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

  it("passe le sprite en ARGUMENT (contrat qui permet à l'appelant de ne pas le capturer)", () => {
    const source = makeSource();
    const icon = "sprite-en-argument.png";
    const sprite = makeSprite();
    let received: DestroyableSprite | null = null;

    enqueueForIconLoad(icon, source, sprite, (pending) => {
      received = pending;
    });
    source.fire();

    // Sans cet argument, l'appelant devrait fermer sur ``sprite`` — la file le retiendrait en
    // référence forte et les ``WeakRef`` ne serviraient plus à rien.
    expect(received).toBe(sprite);
  });

  it("applique un sprite DÉTACHÉ mais non détruit (removeChildren du layer de ghosts)", () => {
    const source = makeSource();
    const icon = "detache-non-detruit.png";
    const applied: string[] = [];

    // ``removeChildren()`` détache sans détruire : ``destroyed`` reste faux. Le sprite reste
    // donc légitimement servi s'il est encore joignable — c'est le ramasse-miettes, et non une
    // purge sur ``destroyed``, qui borne la file dans ce cas.
    const detached = makeSprite();
    enqueueForIconLoad(icon, source, detached, () => applied.push("detache"));
    source.fire();

    expect(applied).toEqual(["detache"]);
  });

  it("garde une file BORNÉE malgré les redraws, et la borne ne dépend pas de leur nombre", () => {
    // La purge est amortie (elle ne repasse que quand la file a doublé) : la file n'est donc
    // pas minimale à tout instant. Ce qui ferme la fuite n'est pas sa taille exacte, c'est
    // qu'elle ne CROISSE PAS avec le nombre de rendus — d'où la comparaison des deux volumes.
    function queueAfter(redraws: number, icon: string): number {
      const source = makeSource();
      for (let redraw = 0; redraw < redraws; redraw++) {
        const dead = makeSprite();
        enqueueForIconLoad(icon, source, dead, () => {});
        dead.destroyed = true; // le redraw suivant détruit le sprite du précédent
      }
      return pendingIconQueueSize(icon);
    }

    const after200 = queueAfter(200, "borne-200.png");
    const after2000 = queueAfter(2000, "borne-2000.png");

    // Pas d'égalité stricte : la taille dépend de l'endroit du cycle de doublement où l'on
    // s'arrête. Ce qui doit tenir, c'est la BORNE — sans purge, ce serait 200 puis 2000.
    expect(after200).toBeLessThan(64);
    expect(after2000).toBeLessThan(64);
  });

  it("ne fait RIEN sur une source déjà chargée (loaded ne repartirait jamais)", () => {
    const source = makeSource();
    source.valid = true;
    const icon = "deja-chargee.png";

    enqueueForIconLoad(icon, source, makeSprite(), () => {});

    // Sans ce garde-fou, l'entrée resterait à vie : c'est le cas d'une texture valide dont le
    // diamètre est nul, où le rognage circulaire échoue sans qu'aucun chargement soit à venir.
    expect(source.listeners.length).toBe(0);
    expect(pendingIconQueueSize(icon)).toBe(0);
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
