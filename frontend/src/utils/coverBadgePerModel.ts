/**
 * Décision du badge de COUVERT (règle 13.08) pour UNE figurine, en mode badge par-figurine.
 *
 * Le couvert 13.08 se juge à l'échelle de l'UNITÉ — « if EVERY model in that unit meets one or
 * more of the following conditions » — et c'est ce booléen d'unité, lui seul, qui donne le -1 BS.
 * Mais une escouade est dessinée figurine par figurine, et répliquer ce booléen sur chacune
 * produit une lecture inversée :
 *
 *   - 4 figurines dans un terrain, 1 à découvert → l'unité n'a PAS le couvert, donc aucune des
 *     4 n'affichait de badge, alors qu'elles sont visiblement à l'abri ;
 *   - inversement, quand l'unité qualifie, une figurine plantée en terrain découvert affichait
 *     le badge comme les autres.
 *
 * Le moteur fournit désormais la condition remplie par CHAQUE figurine
 * (`compute_unit_los(...)["cover_conditions"]`). Cette fonction en tire l'état d'affichage, en
 * gardant les deux informations distinctes plutôt qu'en les aplatissant : ce qui protège la
 * figurine, et si l'escouade touche réellement le bonus.
 */
import type { CoverConditionsByUnitId, ModelCoverCondition } from "../types/game";

/**
 * Empreinte stable des conditions par figurine, pour détecter un changement.
 *
 * Deux pièges, tous deux constatés en revue, et tous deux dus au fait que `""` (figurine à
 * découvert) est une valeur PORTEUSE DE SENS et non une absence :
 *
 *  - concaténer sans séparateur confond `["b", ""]` et `["", "b"]`, c'est-à-dire deux escouades
 *    où ce n'est pas la même figurine qui est exposée ;
 *  - ignorer la longueur confond une escouade de 5 avec la même après la mort d'une figurine,
 *    alors que tous les index suivants ont glissé d'un cran.
 *
 * Sérialiser le tableau tel quel écarte les deux : chaque élément reste distinct et positionné.
 * Consommée à la fois par la clé de rendu du plateau et par la détection de changement du blink —
 * une seule définition, pour que ces deux-là ne puissent pas diverger.
 */
export function coverConditionsFingerprint(m: CoverConditionsByUnitId): string {
  return JSON.stringify(
    Object.keys(m)
      .sort()
      .map((k) => [k, m[k]])
  );
}

/**
 * - `"none"` → aucun badge : la figurine est à découvert (et si l'unité n'a pas le couvert,
 *   c'est une figurine comme elle qui le lui coûte).
 * - `"cover"` → badge plein : la figurine est protégée ET son unité qualifie → le -1 BS s'applique.
 * - `"cover-unqualified"` → badge atténué : la figurine est géométriquement protégée, mais une
 *   autre figurine de l'escouade est à découvert → AUCUN bonus. Sans cet état, afficher le badge
 *   remplacerait un affichage faux par un autre, en promettant un -1 BS que la règle refuse.
 */
export type ModelCoverBadge = "none" | "cover" | "cover-unqualified";

/**
 * @param index        Index de la figurine, aligné sur `modelCenters`.
 * @param conditions   Conditions 13.08 par figurine, ou `null` si le moteur ne les a pas fournies
 *                     (couvert calculé côté WASM, qui n'a pas ce détail) → repli sur `unitInCover`,
 *                     c'est-à-dire le comportement historique, jamais une invention côté client.
 * @param unitInCover  Couvert d'UNITÉ effectif (IGNORES_COVER déjà appliqué) : la seule source
 *                     du -1 BS.
 */
export function modelCoverBadge(
  index: number,
  conditions: ModelCoverCondition[] | null,
  unitInCover: boolean
): ModelCoverBadge {
  if (conditions === null) {
    return unitInCover ? "cover" : "none";
  }
  // Hors bornes = figurine que le moteur n'a pas décrite (cible non vue, escouade désynchronisée
  // d'un rendu en retard). On n'invente pas de couvert pour elle.
  if (!conditions[index]) {
    return "none";
  }
  return unitInCover ? "cover" : "cover-unqualified";
}
