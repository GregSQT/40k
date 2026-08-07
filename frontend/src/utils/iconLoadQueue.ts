/**
 * File d'attente des sprites en attente du chargement de leur icône.
 *
 * POURQUOI CE MODULE EXISTE — la fuite qu'il ferme :
 * une BaseTexture PIXI est MUTUALISÉE entre toutes les figurines qui partagent un chemin
 * d'icône. Poser ``baseTexture.once("loaded", …)`` à chaque rendu de chaque figurine semble
 * anodin puisque ``once`` se retire tout seul — mais il ne se retire QU'EN S'EXÉCUTANT.
 * Quand l'asset est absent, ``valid`` reste faux pour toujours (comportement assumé :
 * l'initiale de l'unité reste affichée à la place du portrait), l'événement ne part jamais,
 * et les centaines de redraws par tour empilent autant de closures mortes retenant chacune
 * un sprite. Croissance mémoire non bornée sur la durée d'une session.
 *
 * DEUX bornes sont nécessaires, et la seconde n'est pas intuitive :
 *  1. UN écouteur par chemin d'icône, pas un par rendu ;
 *  2. la file ne doit retenir AUCUN sprite — d'où les ``WeakRef``. Purger sur
 *     ``sprite.destroyed`` ne suffit pas : le layer de ghosts du move-preview est vidé par
 *     ``removeChildren()`` (BoardPvp), qui détache sans détruire. ``destroyed`` reste faux,
 *     et une file qui tiendrait les sprites en référence forte les maintiendrait vivants —
 *     la fuite serait déplacée de l'écouteur vers la file, pas fermée.
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
  valid: boolean;
  once(event: "loaded", handler: () => void): unknown;
}

/** Une inscription : le sprite en référence FAIBLE, et quoi lui appliquer au chargement. */
interface PendingEntry {
  ref: WeakRef<DestroyableSprite>;
  apply: (sprite: DestroyableSprite) => void;
}

interface IconQueue {
  entries: PendingEntry[];
  /** Longueur à partir de laquelle une purge est rentable (cf. ``enqueueForIconLoad``). */
  purgeAt: number;
}

/** En deçà, purger coûte plus que ce que ça rend : une poignée d'entrées de deux champs. */
const MIN_PURGE_WATERMARK = 32;

const pendingByIcon = new Map<string, IconQueue>();

/** Le sprite inscrit s'il est encore joignable ET vivant, ``undefined`` sinon. */
function liveSprite(entry: PendingEntry): DestroyableSprite | undefined {
  const sprite = entry.ref.deref();
  return sprite !== undefined && !sprite.destroyed ? sprite : undefined;
}

/**
 * Inscrit ``sprite`` pour que ``apply`` soit exécuté au chargement de ``iconPath``.
 *
 * Le PREMIER appelant d'une icône pose l'écouteur ; les suivants rejoignent sa file.
 * Sans effet si la source est DÉJÀ chargée : ``loaded`` ne repartirait pas et l'inscription
 * resterait morte à vie. Le module fait respecter cette précondition lui-même plutôt que de
 * la confier en prose à chaque site d'appel.
 *
 * ``apply`` reçoit le sprite en ARGUMENT et ne doit pas le capturer par fermeture, sinon la
 * file le retiendrait à nouveau et la borne 2 ci-dessus tomberait.
 */
export function enqueueForIconLoad<TSprite extends DestroyableSprite>(
  iconPath: string,
  source: IconLoadSource,
  sprite: TSprite,
  apply: (sprite: TSprite) => void
): void {
  if (source.valid) return;

  const entry: PendingEntry = {
    ref: new WeakRef(sprite),
    // ``liveSprite`` ne rend que le sprite déréférencé depuis CETTE entrée, donc du type
    // inscrit : la conversion est sûre, et confinée ici plutôt que répétée par appelant.
    apply: apply as (pending: DestroyableSprite) => void,
  };

  const queue = pendingByIcon.get(iconPath);
  if (queue) {
    queue.entries.push(entry);
    // Purge AMORTIE. Un redraw inscrit un sprit neuf par figurine et rien ne devient
    // collectable dans l'intervalle : purger à chaque inscription rendrait le redraw
    // quadratique pour ne rien libérer. On ne repasse que quand la file a doublé.
    if (queue.entries.length >= queue.purgeAt) {
      queue.entries = queue.entries.filter((pending) => liveSprite(pending) !== undefined);
      queue.purgeAt = Math.max(MIN_PURGE_WATERMARK, queue.entries.length * 2);
    }
    return;
  }

  pendingByIcon.set(iconPath, { entries: [entry], purgeAt: MIN_PURGE_WATERMARK });
  source.once("loaded", () => {
    // La file est relue depuis la table, jamais capturée : l'inscription peut donc remplacer
    // le tableau lors d'une purge sans que cet écouteur serve une version périmée.
    const loaded = pendingByIcon.get(iconPath);
    pendingByIcon.delete(iconPath);
    if (loaded === undefined) return;
    for (const pending of loaded.entries) {
      const alive = liveSprite(pending);
      if (alive !== undefined) pending.apply(alive);
    }
  });
}

/**
 * Nombre d'inscriptions en attente pour une icône.
 * @internal Seam de vérification de la fuite — ne fait pas partie du contrat du module.
 */
export function pendingIconQueueSize(iconPath: string): number {
  return pendingByIcon.get(iconPath)?.entries.length ?? 0;
}
