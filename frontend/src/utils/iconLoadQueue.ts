/**
 * File d'attente des sprites en attente du chargement de leur icône.
 *
 * POURQUOI CE MODULE EXISTE — la fuite qu'il ferme :
 * une BaseTexture PIXI est MUTUALISÉE entre toutes les figurines qui partagent un chemin
 * d'icône. Poser ``baseTexture.once("loaded", …)` à chaque rendu de chaque figurine semble
 * anodin puisque ``once`` se retire tout seul — mais il ne se retire QU'EN S'EXÉCUTANT.
 * Quand l'asset est absent, ``valid`` reste faux pour toujours (comportement assumé :
 * l'initiale de l'unité reste affichée à la place du portrait), l'événement ne part jamais,
 * et les centaines de redraws par tour empilent autant de closures mortes retenant chacune
 * un sprite détruit. Croissance mémoire non bornée sur la durée d'une session.
 *
 * Ici : UN écouteur par chemin d'icône, et une file purgée de ses sprites détruits à chaque
 * inscription — sinon la fuite se déplacerait simplement de l'écouteur vers la file.
 *
 * Volontairement sans dépendance à PIXI (typage structurel) : c'est ce qui rend le verrou
 * testable sans navigateur ni contexte WebGL.
 */

/** Ce que la file exige d'un sprite : savoir s'il a été détruit depuis son inscription. */
export interface DestroyableSprite {
  destroyed: boolean;
}

/** Ce que la file exige d'une source de texture (satisfait par ``PIXI.BaseTexture``). */
export interface IconLoadSource {
  once(event: "loaded", handler: () => void): unknown;
}

interface PendingEntry {
  sprite: DestroyableSprite;
  apply: () => void;
}

const pendingByIcon = new Map<string, PendingEntry[]>();

/**
 * Inscrit ``sprite`` pour que ``apply`` soit exécuté au chargement de ``iconPath``.
 *
 * Le PREMIER appelant d'une icône pose l'écouteur ; les suivants rejoignent sa file. ``apply``
 * n'est appelé que si le sprite n'a pas été détruit entre-temps.
 */
export function enqueueForIconLoad(
  iconPath: string,
  source: IconLoadSource,
  sprite: DestroyableSprite,
  apply: () => void
): void {
  const existing = pendingByIcon.get(iconPath);
  if (existing) {
    // Purge EN PLACE, jamais par remplacement du tableau : l'écouteur déjà posé retient
    // cette référence, donc lui substituer un nouveau tableau ferait disparaître tous les
    // sprites inscrits après le premier.
    for (let index = existing.length - 1; index >= 0; index--) {
      if (existing[index].sprite.destroyed) existing.splice(index, 1);
    }
    existing.push({ sprite, apply });
    return;
  }

  const queue: PendingEntry[] = [{ sprite, apply }];
  pendingByIcon.set(iconPath, queue);
  source.once("loaded", () => {
    pendingByIcon.delete(iconPath);
    for (const entry of queue) {
      if (!entry.sprite.destroyed) entry.apply();
    }
  });
}

/** Nombre de sprites en attente pour une icône. Exposé pour les tests du verrou. */
export function pendingIconQueueSize(iconPath: string): number {
  return pendingByIcon.get(iconPath)?.length ?? 0;
}
