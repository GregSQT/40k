/**
 * ⚠️ INSTRUMENT TEMPORAIRE (2026-08-12) — à retirer avec l'affichage qui le consomme.
 *
 * Pourquoi il existe : le seul témoin du contrôle d'objectif sur le plateau est un contour de
 * 2,4 px, dont la couleur ne se vérifie ni à l'œil ni sur une capture. Trois diagnostics faux ont
 * été rendus sur ce sujet faute d'un endroit où LIRE ce que le moteur considère comme tenu.
 * Cette fonction rend cette information en texte, donc vérifiable.
 *
 * Elle est PURE et sans dépendance au rendu : c'est ce qui la rend testable sans PIXI ni WebGL.
 */

/** Identité d'un objectif telle que le moteur la sérialise (`game_state["objectives"]`). */
export interface ObjectiveIdentity {
  id?: string | number;
  name?: string;
}

/**
 * Libellés des objectifs tenus par ``player``, règle 14.02.
 *
 * ``controllers`` est ``game_state.objective_controllers`` : l'état AUTORITAIRE du moteur, figé à
 * chaque frontière de phase, indexé par **id** d'objectif. ``objectives`` ne sert qu'à traduire ces
 * ids en noms lisibles ; son absence n'est pas une erreur (l'API l'omet des réponses d'action), on
 * retombe alors sur l'id — qui reste exact, seulement moins joli.
 *
 * L'ordre suit celui du moteur, donc celui du scénario.
 */
export function heldObjectiveLabels(
  controllers: Record<string, number | null> | undefined,
  objectives: ObjectiveIdentity[] | undefined,
  player: number
): string[] {
  if (!controllers) {
    return [];
  }
  const labelById = new Map<string, string>();
  for (const objective of objectives ?? []) {
    if (objective.id === undefined || objective.id === null) {
      continue;
    }
    const id = String(objective.id);
    const name = typeof objective.name === "string" ? objective.name.trim() : "";
    labelById.set(id, name.length > 0 ? name : id);
  }
  const held: string[] = [];
  for (const [id, controller] of Object.entries(controllers)) {
    if (controller !== player) {
      continue;
    }
    held.push(labelById.get(id) ?? id);
  }
  return held;
}
