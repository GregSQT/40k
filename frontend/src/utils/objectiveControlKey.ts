/**
 * Contrôle d'objectif (14.02) — la TABLE par sous-hex, et la CLÉ qui l'invalide.
 *
 * La table `objectiveControl` associe un contrôleur à chaque sous-hex de zone d'objectif. Elle est
 * dérivée de deux choses seulement : la géométrie STATIQUE des zones (`objective_zones`) et
 * l'instantané moteur `game_state.objective_controllers`, autorité unique du contrôle. En replay,
 * elle est REMPLACÉE par l'instantané pré-calculé du `step.log`.
 *
 * POURQUOI CE MODULE EXISTE — deux raisons, une de coût et une de sûreté.
 *
 * 1. COÛT. Sur `terrain-mc1`, cinq zones rasterisées font ~10 500 entrées. L'effet de dessin de
 *    `BoardPvp` se réexécute à cadence de souris (survol, glisser). MESURÉ (vite-node, moyenne sur
 *    200 à 20 000 itérations) : reconstruire la table à chaque rendu coûtait 1,96 ms et ~1 Mo
 *    jetés, sérialiser ses entrées triées pour en faire une clé 4,31 ms de plus — 6,40 ms par
 *    rendu, pour distinguer CINQ valeurs, une par zone. La clé ci-dessous : 0,001 ms.
 *
 * 2. SÛRETÉ. La clé entre dans `bcKey`, qui décide si le calque PIXI STATIQUE est reconstruit — et
 *    la couleur de contrôle des objectifs vit dans ce calque (cf. `boardRedrawDecision.ts`). Une
 *    clé qui rate un changement de contrôle rejoue le défaut du 2026-08-12 : un objectif capturé
 *    ne devenait JAMAIS bleu de toute la partie. L'équivalence avec la clé exhaustive est donc
 *    verrouillée par `objectiveControlKey.test.ts`, pas laissée à la relecture.
 *
 * CE QUI REND LA CLÉ COURTE EXACTE : tous les sous-hex d'une zone portent la MÊME valeur
 * (`buildObjectiveControlTable` ci-dessous), et le rendu ne lit qu'un hex ÉCHANTILLON par zone
 * (`BoardDisplay` : « any zone hex works »). La clé lit donc le même échantillon que le rendu —
 * elle ne peut pas diverger de ce qui est affiché. Elle porte EN PLUS le contrôleur SOURCE de
 * chaque zone : si deux zones se chevauchaient, l'échantillon d'une zone pourrait porter la valeur
 * de l'autre, et cette seconde composante garantit qu'un changement de contrôle reste vu.
 *
 * La GÉOMÉTRIE, elle, n'est pas dans cette clé (cf. `objectiveZonesGeometryKey`) : elle ne change
 * qu'au chargement d'un plateau ou d'un épisode de replay, et se mémoïse sur la référence du
 * tableau de zones.
 */

export type ObjectiveController = number | null;
export type ObjectiveControlTable = Record<string, ObjectiveController>;
export type ObjectiveZoneHex = [number, number] | { col: number; row: number };

export interface ObjectiveZoneLike {
  id: string | number;
  hexes: ObjectiveZoneHex[];
  /** Tracé de la zone (`"polygon"`, `"rect"`, absent = union d'hexes) — entre dans la géométrie. */
  shape?: string;
}

/** Clé de table d'un sous-hex — `"col,row"`, l'unique forme lue par le rendu. */
export function objectiveHexKey(hex: ObjectiveZoneHex): string {
  return Array.isArray(hex) ? `${hex[0]},${hex[1]}` : `${hex.col},${hex.row}`;
}

/**
 * Hex ÉCHANTILLON d'une zone : le premier aux coordonnées finies, exactement la règle de
 * `BoardDisplay` (`zoneCells[0]`, les hexes non finis étant écartés). Toute autre règle ferait
 * lire à la clé un hex que le rendu ne lit pas.
 */
export function objectiveZoneSampleHexKey(zone: ObjectiveZoneLike): string | null {
  for (const hex of zone.hexes ?? []) {
    const col = Array.isArray(hex) ? Number(hex[0]) : Number(hex.col);
    const row = Array.isArray(hex) ? Number(hex[1]) : Number(hex.row);
    if (!Number.isFinite(col) || !Number.isFinite(row)) continue;
    return `${col},${row}`;
  }
  return null;
}

/**
 * Table par sous-hex, à partir de la géométrie statique des zones et de l'instantané moteur.
 *
 * Une zone absente de l'instantané vaut « aucun contrôleur » (`null`) : le moteur n'écrit une
 * entrée que pour les objectifs qu'il connaît, et une zone inconnue n'est contrôlée par personne.
 */
export function buildObjectiveControlTable(
  zones: readonly ObjectiveZoneLike[],
  controllers: Readonly<Record<string, ObjectiveController>>
): ObjectiveControlTable {
  const table: ObjectiveControlTable = {};
  for (const zone of zones) {
    const controller = controllers[String(zone.id)] ?? null;
    for (const hex of zone.hexes) {
      table[objectiveHexKey(hex)] = controller;
    }
  }
  return table;
}

/**
 * Clé d'invalidation du contrôle : O(zones), pas O(sous-hex).
 *
 * @param zones       zones RENDUES (celles que `drawBoard` colorie), pas celles qui ont servi à
 *                    bâtir la table — c'est ce que le rendu lit qui doit gouverner l'invalidation.
 * @param control     table EFFECTIVE, override de replay compris.
 * @param controllers instantané moteur dont `control` dérive, ou `null` quand un override l'a
 *                    remplacée (l'instantané ne décrit alors plus ce qui est affiché).
 *
 * Trois états distincts par zone, jamais confondus : hex échantillon ABSENT de la table (`-`, la
 * zone se dessine en neutre), présent SANS contrôleur (`n`), présent avec un contrôleur (son
 * numéro). Une zone sans aucun hex exploitable vaut `?` — elle n'est pas dessinée.
 */
export function objectiveControlKey(
  zones: readonly ObjectiveZoneLike[],
  control: Readonly<ObjectiveControlTable>,
  controllers: Readonly<Record<string, ObjectiveController>> | null
): string {
  const parts: string[] = [];
  for (const zone of zones) {
    const sampleKey = objectiveZoneSampleHexKey(zone);
    let sample: string;
    if (sampleKey === null) {
      sample = "?";
    } else if (!(sampleKey in control)) {
      sample = "-";
    } else {
      sample = String(control[sampleKey] ?? "n");
    }
    const src = controllers === null ? "" : `/${String(controllers[String(zone.id)] ?? "n")}`;
    parts.push(`${String(zone.id)}=${sample}${src}`);
  }
  return parts.join("|");
}

/**
 * djb2 sur une liste de sous-hex — le hachage de `bcKey` pour toute géométrie volumineuse (zones
 * d'objectif, murs). Rend le hachage BRUT : l'appelant y ajoute le nombre d'éléments, sans quoi
 * deux listes de longueurs différentes pourraient se confondre.
 */
export function hashHexList(hexes: readonly ObjectiveZoneHex[], seed = 5381 >>> 0): number {
  let hash = seed;
  for (const hex of hexes) {
    const col = Array.isArray(hex) ? Number(hex[0]) : Number(hex.col);
    const row = Array.isArray(hex) ? Number(hex[1]) : Number(hex.row);
    hash = Math.imul(33, hash) ^ col;
    hash = Math.imul(33, hash) ^ row;
  }
  return (hash | 0) >>> 0;
}

/**
 * Empreinte de la GÉOMÉTRIE des zones : identifiant, forme et coordonnées de chacune.
 *
 * Sans elle, deux plateaux aux zones différentes mais de mêmes identifiants réutiliseraient le
 * calque statique de l'un pour l'autre (replay : épisode N → N+1) — la clé exhaustive remplacée
 * ici portait cette information par accident, en sérialisant toutes les coordonnées.
 *
 * O(sous-hex) : à mémoïser sur la RÉFÉRENCE du tableau de zones, qui ne change qu'au chargement.
 */
export function objectiveZonesGeometryKey(zones: readonly ObjectiveZoneLike[]): string {
  let hash = 5381 >>> 0;
  let count = 0;
  for (const zone of zones) {
    // `shape` gouverne le tracé de la zone (polygone, rectangle, union d'hexes) : deux zones de
    // mêmes hexes mais de formes différentes ne se dessinent pas pareil.
    for (const ch of `${zone.id}:${zone.shape ?? "hexes"}`) {
      hash = Math.imul(33, hash) ^ ch.charCodeAt(0);
    }
    hash = hashHexList(zone.hexes, hash);
    count += zone.hexes.length;
  }
  return `${zones.length}:${count}:${hash}`;
}
