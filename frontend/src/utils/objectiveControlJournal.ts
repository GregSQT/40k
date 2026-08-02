/**
 * Journal du contrôle d'objectif (14.02) — DIFFÉRENCE d'instantanés, jamais un calcul.
 *
 * Le moteur est la seule autorité sur le contrôle d'objectif : il l'écrit dans le step.log
 * (`ai/step_logger.py::log_objective_control_snapshot`) et `replayParser.ts` l'attache à chaque
 * état de la timeline. Le rôle de ce module est de dire CE QUI A CHANGÉ entre deux instantanés,
 * pour que le journal du replay le raconte.
 *
 * Il ne doit JAMAIS compter d'OC, tester une position ni appliquer un barème : c'est exactement
 * ce que faisait le code remplacé, qui divergeait du moteur sur l'ancre d'escouade (au lieu de
 * l'empreinte de socle par figurine) et ignorait le battle-shock (01.07/02.02).
 */

export interface ObjectiveControlChange {
  zoneName: string;
  /** Joueur contrôlant après le changement, ou `null` si la zone est contestée. */
  controller: number | null;
}

/**
 * Zones dont le contrôleur a changé entre `previous` et `controllers`.
 *
 * Une zone absente de `previous` vaut « non contrôlée » : sur le tout premier instantané, une zone
 * contestée ne produit donc aucun événement (rien ne s'est passé), et une zone déjà contrôlée en
 * produit un — sinon la prise initiale n'apparaîtrait nulle part.
 *
 * @param previous    dernier contrôleur connu par zone (zone absente = jamais vue).
 * @param controllers instantané moteur courant.
 */
export function diffObjectiveControllers(
  previous: Record<string, number | null>,
  controllers: Record<string, number | null>
): ObjectiveControlChange[] {
  const changes: ObjectiveControlChange[] = [];
  for (const [zoneName, controller] of Object.entries(controllers)) {
    const before = previous[zoneName] ?? null;
    if (controller === before) {
      continue;
    }
    changes.push({ zoneName, controller });
  }
  return changes;
}

/** Message de journal d'un changement, sans somme d'OC : le moteur ne les publie pas. */
export function objectiveControlMessage(change: ObjectiveControlChange): string {
  return change.controller === null
    ? `Objective ${change.zoneName} contested`
    : `P${change.controller} controls objective ${change.zoneName}`;
}
