/**
 * Encodage d'un plan par-figurine vers le backend — SOURCE UNIQUE.
 *
 * ⚠️ NE PAS RECOPIER CES FONCTIONS SUR UN SITE D'APPEL. Le dépôt a déjà payé cette duplication :
 * les versions recopiées par site avaient produit deux dialectes de défaut pour l'étage (`?? 0`
 * contre le niveau de VUE), c'est-à-dire exactement l'étage inventé que la frontière backend
 * élimine. L'encodeur a donc été centralisé — puis re-dupliqué une fois de plus dans
 * `BoardPvp` (aperçu de tir par figurine, 2026-08-11), et la review suivante a trouvé un bug de
 * niveau à cet endroit précis. Le module vit ici, et non dans `useEngineAPI`, pour que les
 * composants puissent l'appeler sans dépendre du hook : c'est ce qui rendait la copie tentante.
 *
 * Miroir front de `parse_model_plan` / `parse_model_plan_with_orientation`
 * (engine/phase_handlers/shared_utils.py).
 */

/** Modèle d'un plan provisoire côté front : position + étage capturé au drop. */
export type PlanModel = { col: number; row: number; level?: number };

/** Plan par-figurine pouvant porter l'orientation socle (move : pivot molette). */
export type PlanModelWithOrientation = PlanModel & { orientation?: number | null };

/**
 * Encode un plan par-figurine : `[[model_id, col, row, level], …]`.
 *
 * L'étage est TOUJOURS envoyé, le backend refuse une entrée muette. Il reste un HINT : le moteur
 * le résout en niveau effectif (`resolve_model_floor_level`), une figurine dont le socle ne tient
 * pas sur le plancher étant au sol (13.06).
 */
export function toPlanArray(
  models: Record<string, PlanModel>,
  fallbackLevel = 0
): Array<[string, number, number, number]> {
  return Object.entries(models).map(([mid, p]) => [mid, p.col, p.row, p.level ?? fallbackLevel]);
}

/** Variante du move : l'orientation socle par-fig voyage en 5ᵉ élément (`null` = inchangée). */
export function toPlanArrayWithOrientation(
  models: Record<string, PlanModelWithOrientation>
): Array<[string, number, number, number, number | null]> {
  return Object.entries(models).map(([mid, p]) => [
    mid,
    p.col,
    p.row,
    p.level ?? 0,
    p.orientation ?? null,
  ]);
}
