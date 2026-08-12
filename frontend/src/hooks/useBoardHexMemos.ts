/**
 * Dérivations VOLUMINEUSES du chemin de rendu du plateau, mémoïsées sur la référence de leur SOURCE.
 *
 * POURQUOI CE MODULE EXISTE. Trois tableaux étaient reconstruits à CHAQUE rendu alors que leur
 * source ne change qu'au chargement d'un plateau ou d'une réponse API : la normalisation des
 * objectifs (`BoardWithAPI`), leur aplatissement en couples (`BoardPvp`), et le `Set` des murs de
 * la branche de glisser du déploiement (`BoardPvp`). MESURÉ (node, 5 zones × 2 116 sous-hex =
 * 10 580 hexes, 1 000 murs, moyenne sur 2 000 à 20 000 itérations, 3 exécutions) :
 * 0,10 + 0,15 + 0,07 ≈ 0,32 ms par rendu, et ~21 000 objets jetés à chaque fois — pression GC
 * pendant un glisser. Sur source de référence stable, le coût par rendu tombe sous 0,0001 ms.
 *
 * Le vrai coût du premier n'est PAS ses 0,2 ms : sa sortie descend en prop `objectivesOverride`,
 * qui figure dans les dépendances du gros effet de dessin de `BoardPvp`. Une référence neuve à
 * chaque rendu y REJOUE tout le dessin PIXI, y compris quand rien de dessinable n'a bougé.
 *
 * Les hooks vivent ici, et pas en ligne dans les composants, pour que l'IDENTITÉ de leur sortie
 * soit verrouillée par test (`useBoardHexMemos.test.ts`) : une mémoïsation ne se prouve pas par la
 * valeur — elle rend la même dans les deux cas — mais par `Object.is` entre deux rendus.
 */

import { useMemo } from "react";

/** Liste vide PARTAGÉE : la sortie « pas d'hexes » garde la même référence d'un hook à l'autre et
 * d'un appel à l'autre, y compris hors mémoïsation — un `[]` littéral ne le garantirait que tant
 * qu'il reste enfermé dans un `useMemo`. */
const EMPTY_HEX_TUPLES: [number, number][] = [];

export type RawObjectiveHex = { col: number; row: number } | [number, number];
export interface RawObjective {
  name: string;
  hexes: RawObjectiveHex[];
}
export interface NormalizedObjective {
  name: string;
  hexes: Array<{ col: number; row: number }>;
}

/**
 * Normalise `game_state.objectives` en hexes `{col,row}`.
 *
 * Les `throw` sont VOULUS (pas de repli qui masquerait une réponse API malformée) : un objectif
 * sans `name` ou sans `hexes` est une erreur de contrat, pas un cas à absorber.
 */
export function normalizeObjectives(objectives: RawObjective[]): NormalizedObjective[] {
  return objectives.map((objective) => {
    if (!objective?.name) {
      throw new Error("Objective missing required name field");
    }
    if (!objective.hexes) {
      throw new Error(`Objective ${objective.name} missing required hexes`);
    }
    const normalizedHexes = objective.hexes.map((hex) => {
      if (Array.isArray(hex)) {
        if (hex.length !== 2) {
          throw new Error(
            `Objective ${objective.name} has invalid hex tuple: ${JSON.stringify(hex)}`
          );
        }
        return { col: hex[0], row: hex[1] };
      }
      if (typeof hex === "object" && hex !== null && "col" in hex && "row" in hex) {
        return { col: (hex as { col: number }).col, row: (hex as { row: number }).row };
      }
      throw new Error(`Objective ${objective.name} has invalid hex format: ${JSON.stringify(hex)}`);
    });
    return { name: objective.name, hexes: normalizedHexes };
  });
}

/** Aplatit des objectifs normalisés en couples `[col,row]` — la forme que `drawBoard` consomme. */
export function flattenObjectiveHexes(
  objectives: readonly NormalizedObjective[]
): [number, number][] {
  const out: [number, number][] = [];
  for (const objective of objectives) {
    for (const hex of objective.hexes) {
      out.push([hex.col, hex.row]);
    }
  }
  return out;
}

/** `Set` de clés `"col,row"` — la forme d'appartenance lue par les tests de placement. */
export function buildHexKeySet(hexes: readonly [number, number][]): Set<string> {
  const set = new Set<string>();
  for (const [col, row] of hexes) {
    set.add(`${col},${row}`);
  }
  return set;
}

/**
 * Objectifs normalisés, mémoïsés sur la référence de `objectives`.
 *
 * La dépendance porte sur le CHAMP, jamais sur le `gameState` englobant : chaque réponse API rend
 * un objet `gameState` neuf. Elle est en outre STABLE d'une réponse à l'autre — l'API omet
 * `objectives` des réponses post-action et `mergeGameStatePreservingOmittedObjectives` réinjecte la
 * MÊME référence — donc la normalisation ne tourne qu'une fois par partie en pratique.
 *
 * Les `throw` de `normalizeObjectives` restent atteints au même moment qu'avant : au premier rendu
 * qui voit ces objectifs-là, et à chaque changement de la liste. Une liste malformée lève toujours,
 * simplement pas en boucle.
 */
export function useNormalizedObjectives(
  objectives: RawObjective[] | undefined
): NormalizedObjective[] | undefined {
  return useMemo(
    () => (objectives === undefined ? undefined : normalizeObjectives(objectives)),
    [objectives]
  );
}

/**
 * Hexes d'objectif EFFECTIFS en couples : l'override runtime s'il porte des zones, sinon la liste
 * statique du plateau. Mémoïsé sur les deux références.
 */
export function useEffectiveObjectiveHexes(
  objectivesOverride: readonly NormalizedObjective[] | undefined,
  boardObjectiveHexes: [number, number][] | undefined
): [number, number][] {
  return useMemo(() => {
    if (objectivesOverride && objectivesOverride.length > 0) {
      return flattenObjectiveHexes(objectivesOverride);
    }
    return boardObjectiveHexes ?? EMPTY_HEX_TUPLES;
  }, [objectivesOverride, boardObjectiveHexes]);
}

/**
 * `Set` des murs, mémoïsé sur la référence du tableau ET SUR SA LONGUEUR.
 *
 * La longueur n'est pas une précaution : l'effet de dessin de `BoardPvp` COMPLÈTE `wall_hexes` en
 * place (rangée du bas, colonnes impaires) sur le tableau de `boardConfig` lui-même. Le tableau
 * garde donc sa référence en changeant de contenu, une fois, après le premier passage de l'effet.
 * Sans la longueur, ce `Set` resterait figé sur l'état d'avant complétion et le glisser de
 * déploiement tiendrait la rangée du bas pour libre. La complétion étant idempotente (elle est
 * gardée par un test d'appartenance), la longueur se stabilise dès le premier passage.
 */
export function useWallHexKeySet(wallHexes: [number, number][] | undefined): Set<string> {
  const length = wallHexes?.length ?? 0;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `length` est VOULUE — le tableau source est muté EN PLACE par l'effet de dessin, sa référence ne suffit donc pas (cf. docstring).
  return useMemo(() => buildHexKeySet(wallHexes ?? EMPTY_HEX_TUPLES), [wallHexes, length]);
}
