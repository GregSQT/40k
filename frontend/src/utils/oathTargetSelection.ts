// frontend/src/utils/oathTargetSelection.ts
//
// Oath of Moment (08.04) — légalité des cibles et résolution du clic plateau.
//
// Deux responsabilités :
//  1. `filterOathTargets` — les cibles LÉGALES (les MÊMES que le moteur : `oath_selectable_enemy_ids`).
//  2. `pickOathTargetAtHex` — laquelle de ces unités le clic désigne.

import { cubeDistance, offsetToCube } from "./gameHelpers";

/** Rayon de tolérance du clic, en sous-hex — même valeur que les hit-tests par-figurine du board. */
export const OATH_HEX_HIT_TOLERANCE = 4;

export type OathUnitsCache = Record<
  string,
  { occupied_hexes_by_model?: Record<string, [number, number]> } | undefined
>;

/** Forme minimale d'une unité pour `filterOathTargets`. */
export interface OathTargetCandidate {
  id: number;
  player: number;
  HP_CUR?: number | null;
  /** Colonne d'ancre : -1 si l'unité est en réserves stratégiques (20.01). */
  col: number;
}

/**
 * Unités adverses désignables par l'Oath of Moment : ennemies, vivantes, et SUR LA TABLE.
 *
 * Alignées sur `oath_selectable_enemy_ids` (engine/phase_handlers/command_handlers.py) et sur
 * `entry_is_on_battlefield` (engine/spatial_relations.py) : `col >= 0`. `set_oath_target` lève
 * depuis le 2026-09-08 pour une unité hors table — toute liste plus large bloquerait la phase.
 */
export function filterOathTargets(
  units: ReadonlyArray<OathTargetCandidate>,
  selectionPlayer: number,
): OathTargetCandidate[] {
  return units.filter(
    (unit) => unit.player !== selectionPlayer && (unit.HP_CUR ?? 0) > 0 && unit.col >= 0,
  );
}

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
