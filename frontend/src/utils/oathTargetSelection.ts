// frontend/src/utils/oathTargetSelection.ts
//
// Oath of Moment (08.04) — résolution du clic plateau en unité désignée.
//
// La LÉGALITÉ des cibles n'est pas jouée ici : `targetUnitIds` vient du même filtre que le moteur
// (`oath_selectable_enemy_ids`), côté BoardWithAPI. Ce module ne fait que dire QUELLE de ces
// unités le joueur a visée.

import { cubeDistance, offsetToCube } from "./gameHelpers";

/** Rayon de tolérance du clic, en sous-hex — même valeur que les hit-tests par-figurine du board. */
export const OATH_HEX_HIT_TOLERANCE = 4;

export type OathUnitsCache = Record<
  string,
  { occupied_hexes_by_model?: Record<string, [number, number]> } | undefined
>;

/**
 * Unité désignable la plus proche de l'hex cliqué, ou `null` si le clic ne vise rien.
 *
 * Le test porte sur les FIGURINES (`occupied_hexes_by_model`), pas sur l'ancre d'escouade : c'est
 * ce qui est dessiné, donc ce que le joueur vise. Une unité sans positions par-figurine n'est pas
 * dessinée sur le plateau : elle ne peut pas être cliquée (elle reste désignable depuis la table
 * de statut).
 */
export function pickOathTargetAtHex(params: {
  col: number;
  row: number;
  targetUnitIds: number[];
  unitsCache: OathUnitsCache | undefined;
  tolerance?: number;
}): number | null {
  const tolerance = params.tolerance ?? OATH_HEX_HIT_TOLERANCE;
  const clickCube = offsetToCube(params.col, params.row);
  let bestUnitId: number | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const targetId of params.targetUnitIds) {
    const byModel = params.unitsCache?.[String(targetId)]?.occupied_hexes_by_model;
    if (!byModel) continue;
    for (const [modelCol, modelRow] of Object.values(byModel)) {
      const distance = cubeDistance(clickCube, offsetToCube(modelCol, modelRow));
      if (distance <= tolerance && distance < bestDistance) {
        bestDistance = distance;
        bestUnitId = targetId;
      }
    }
  }
  return bestUnitId;
}
