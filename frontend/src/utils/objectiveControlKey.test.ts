import { describe, expect, it } from "vitest";

import {
  buildObjectiveControlTable,
  type ObjectiveController,
  type ObjectiveControlTable,
  type ObjectiveZoneLike,
  objectiveControlKey,
  objectiveZoneSampleHexKey,
  objectiveZonesGeometryKey,
} from "./objectiveControlKey";

/**
 * Clé EXHAUSTIVE remplacée : sérialisation triée des 10 500 entrées de la table. Elle est la
 * RÉFÉRENCE de ce test — pas du code de production. La propriété verrouillée ici est simple et
 * c'est la seule qui protège du défaut du 2026-08-12 (objectif capturé jamais recoloré) :
 *
 *     la clé exhaustive change  ⟹  la clé courte change.
 *
 * L'implication inverse n'est vérifiée qu'à géométrie constante : la clé courte porte en plus les
 * identifiants de zone, que la table ne contient pas.
 */
function legacyObjectiveControlKey(control: Readonly<ObjectiveControlTable>): string {
  return Object.entries(control)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}:${v ?? "n"}`)
    .join("|");
}

/** Zone rectangulaire rasterisée, comme le fait le backend pour un terrain-objectif. */
function zone(id: string, col0: number, row0: number, w = 3, h = 3): ObjectiveZoneLike {
  const hexes: Array<[number, number]> = [];
  for (let c = col0; c < col0 + w; c++) {
    for (let r = row0; r < row0 + h; r++) hexes.push([c, r]);
  }
  return { id, hexes };
}

const ZONES: ObjectiveZoneLike[] = [
  zone("ruin_center", 10, 10),
  zone("rect_nw", 30, 10),
  zone("rect_ne", 50, 10),
  zone("rect_sw", 30, 40),
  zone("rect_se", 50, 40),
];

/**
 * Suite d'instantanés de contrôle successifs, du début de partie à la fin. Chaque paire consécutive
 * (et, par la boucle du test, chaque paire tout court) est comparée clé à clé.
 */
const SNAPSHOTS: Array<Record<string, ObjectiveController>> = [
  {}, // T1 : le moteur n'a encore publié aucun objectif
  { ruin_center: null, rect_nw: null, rect_ne: null, rect_sw: null, rect_se: null }, // publiés, contestés
  { ruin_center: 1, rect_nw: null, rect_ne: null, rect_sw: null, rect_se: null }, // UNE seule bascule
  { ruin_center: 1, rect_nw: null, rect_ne: null, rect_sw: null, rect_se: 2 },
  { ruin_center: 2, rect_nw: null, rect_ne: null, rect_sw: null, rect_se: 2 }, // reprise par l'adversaire
  { ruin_center: null, rect_nw: null, rect_ne: null, rect_sw: null, rect_se: 2 }, // retour à AUCUN contrôleur
  { ruin_center: 1, rect_nw: 1, rect_ne: 1, rect_sw: 1, rect_se: 1 }, // tout tenu
];

/** Clé courte, telle que `BoardPvp` la calcule hors mode replay. */
function shortKey(
  zones: ObjectiveZoneLike[],
  controllers: Record<string, ObjectiveController>
): string {
  const table = buildObjectiveControlTable(zones, controllers);
  return objectiveControlKey(zones, table, controllers);
}

describe("objectiveControlKey — équivalence avec la clé exhaustive", () => {
  it("change EXACTEMENT aux mêmes instants que la clé exhaustive", () => {
    const rows = SNAPSHOTS.map((controllers) => ({
      controllers,
      legacy: legacyObjectiveControlKey(buildObjectiveControlTable(ZONES, controllers)),
      short: shortKey(ZONES, controllers),
    }));
    // Contrôle « vert vacant » : sans données, deux clés vides seraient trivialement équivalentes.
    expect(rows.every((r) => r.legacy.length > 0 && r.short.length > 0)).toBe(true);
    // Les instantanés 0 et 1 rendent la MÊME table (aucun contrôleur des deux côtés) : la clé
    // exhaustive ne les distingue pas, la clé courte non plus — c'est la paire d'égalité du test.
    // Les six autres états sont deux à deux distincts : le test compare donc bien des différences.
    expect(rows[0]!.legacy).toBe(rows[1]!.legacy);
    expect(new Set(rows.map((r) => r.legacy)).size).toBe(SNAPSHOTS.length - 1);

    for (const a of rows) {
      for (const b of rows) {
        expect([a.controllers, b.controllers, a.short === b.short]).toEqual([
          a.controllers,
          b.controllers,
          a.legacy === b.legacy,
        ]);
      }
    }
  });

  it("distingue « zone absente de la table » de « zone présente sans contrôleur »", () => {
    // Absente : aucune entrée pour ses hexes (elle se dessine neutre). Présente sans contrôleur :
    // entrée à `null`. Les deux se dessinent pareil AUJOURD'HUI, mais confondre les deux états
    // ferait rater la transition « la zone entre dans la table ».
    const absente = objectiveControlKey(ZONES, {}, null);
    const presenteSansControleur = objectiveControlKey(
      ZONES,
      buildObjectiveControlTable(ZONES, {}),
      null
    );
    expect(absente).not.toBe(presenteSansControleur);
  });

  it("suit l'override de replay, qui REMPLACE la table", () => {
    // En replay, la table vient du `step.log` ; l'instantané `objective_controllers` de l'état
    // courant ne la décrit plus (d'où `controllers = null`). Une clé qui reconstruirait la table
    // depuis le gameState afficherait un contrôle qui n'est pas celui rendu.
    const overrideA = buildObjectiveControlTable(ZONES, { ruin_center: 1 });
    const overrideB = buildObjectiveControlTable(ZONES, { ruin_center: 2 });
    expect(objectiveControlKey(ZONES, overrideA, null)).not.toBe(
      objectiveControlKey(ZONES, overrideB, null)
    );
    expect(objectiveControlKey(ZONES, overrideA, null)).toBe(
      objectiveControlKey(ZONES, { ...overrideA }, null)
    );
  });

  it("voit un changement de contrôle même si deux zones se chevauchent", () => {
    // Chevauchement : `rect_b` écrase tous les hexes de `rect_a`, dont son échantillon. La part
    // « échantillon » de la clé de `rect_a` ne bouge donc plus quand SON contrôleur change — c'est
    // la part « contrôleur source » qui rattrape le changement. Sans elle, le chemin de rendu
    // legacy (pastilles par sous-hex, `objective_smooth_contour: false`) pourrait recolorer sans
    // que le calque statique soit invalidé.
    const chevauchantes: ObjectiveZoneLike[] = [zone("rect_a", 10, 10), zone("rect_b", 10, 10)];
    expect(shortKey(chevauchantes, { rect_a: null, rect_b: 2 })).not.toBe(
      shortKey(chevauchantes, { rect_a: 1, rect_b: 2 })
    );
  });

  it("distingue deux géométries de mêmes identifiants (replay épisode N → N+1)", () => {
    // La clé exhaustive portait la géométrie par accident (toutes les coordonnées y étaient).
    // La clé courte ne la porte pas : l'empreinte de géométrie doit la porter à sa place.
    const deplacees = ZONES.map((z, i) => (i === 0 ? zone("ruin_center", 11, 10) : z));
    const controllers = SNAPSHOTS[3]!;
    expect(shortKey(ZONES, controllers)).toBe(shortKey(deplacees, controllers));
    expect(objectiveZonesGeometryKey(ZONES)).not.toBe(objectiveZonesGeometryKey(deplacees));
    expect(legacyObjectiveControlKey(buildObjectiveControlTable(ZONES, controllers))).not.toBe(
      legacyObjectiveControlKey(buildObjectiveControlTable(deplacees, controllers))
    );
  });

  it("échantillonne l'hex que le rendu lit — le premier aux coordonnées finies", () => {
    const malformee: ObjectiveZoneLike = {
      id: "z",
      hexes: [[Number.NaN, 3] as [number, number], [7, 8]],
    };
    expect(objectiveZoneSampleHexKey(malformee)).toBe("7,8");
    expect(objectiveZoneSampleHexKey({ id: "vide", hexes: [] })).toBe(null);
  });
});
