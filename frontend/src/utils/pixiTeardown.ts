/**
 * Destruction d'un sous-arbre PIXI attaché à un layer de plateau.
 *
 * LA RÈGLE QUE CE MODULE PORTE — qui possède sa texture :
 * un sprite d'unité PARTAGE sa texture avec toutes les figurines du même chemin d'icône (cache
 * ``PIXI.Texture.from``) : la libérer au rebuild la reprendrait aux autres. Un ``PIXI.Text``, lui,
 * possède SON canvas et SA BaseTexture, jamais partagés — et ``Text.destroy`` fusionne ses propres
 * defaults ``texture/baseTexture: true`` : les forcer à ``false`` (le réglage correct pour un
 * sprite) laisserait une texture GPU par texte et par rebuild.
 *
 * D'où la descente explicite : chaque nœud reçoit le traitement de SON type, au lieu d'un unique
 * jeu d'options propagé par ``destroy({ children: true })`` à tout l'arbre.
 */
// ``pixi.js-legacy`` comme partout dans le front : c'est le même objet de classe que ``pixi.js``
// (réexport), mais un import divergent ferait échouer les ``instanceof`` si les deux copies
// venaient à ne plus être dédupliquées.
import * as PIXI from "pixi.js-legacy";

export function destroyLayerChild(child: PIXI.DisplayObject): void {
  if (child instanceof PIXI.Container) {
    // Du dernier au premier : chaque destruction détache l'enfant, donc les indices inférieurs
    // restent valides et aucune copie du tableau n'est nécessaire.
    for (let index = child.children.length - 1; index >= 0; index--) {
      destroyLayerChild(child.children[index]);
    }
  }
  // ``children: false`` partout : la descente ci-dessus a déjà tout traité, et rien ne dépend
  // alors de l'ordre de détachement interne de PIXI.
  child.destroy(
    child instanceof PIXI.Text
      ? { children: false }
      : { children: false, texture: false, baseTexture: false }
  );
}
