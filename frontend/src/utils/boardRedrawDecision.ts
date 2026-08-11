/**
 * Le plateau PIXI est fait de DEUX calques au cycle de vie distinct :
 *
 * - le calque STATIQUE (fond, murs, décor, **couleur de contrôle des objectifs**), invalidé par
 *   `bcKey` — dimensions, contrôle d'objectif, géométrie des zones, murs, phase de déploiement ;
 * - le calque des SURBRILLANCES (previews de move/tir/charge, halos, voiles), invalidé par
 *   l'empreinte structurelle de `computeDrawBoardPartialRedrawFingerprint`.
 *
 * `drawBoard` reconstruit les deux. Le chemin rapide qui la court-circuite ne consultait que la
 * seconde invalidation : quand les surbrillances n'avaient pas structurellement changé, `drawBoard`
 * n'était pas appelée DU TOUT, et le calque statique restait celui d'avant — même si `bcKey` avait
 * changé.
 *
 * EFFET MESURÉ EN JEU (2026-08-12, trace console à l'appui) : le plateau a été construit une seule
 * fois, à un instant où `rect b SE` était déjà tenu et la ruine centrale pas encore. Le Dreadnought
 * est ensuite entré dans la ruine, le moteur a bien basculé le contrôle (journal de partie et
 * panneau joueur le montrent), et la zone est restée neutre pour le reste de la partie —
 * l'empreinte des surbrillances ne contient aucune référence au contrôle d'objectif.
 */

/** Les deux calques peuvent-ils être réutilisés, c'est-à-dire `drawBoard` être évitée ? */
export function canSkipBoardRedraw(params: {
  /** Le calque des surbrillances est intact ET son empreinte structurelle est inchangée. */
  highlightsReusable: boolean;
  /** `bcKey` est inchangée ET le calque statique existe encore. */
  staticLayerReusable: boolean;
}): boolean {
  // ⚠️ LA CONJONCTION EST LE CORRECTIF. Retirer `staticLayerReusable` réintroduit à l'identique le
  // défaut ci-dessus : une capture d'objectif qui ne change pas les surbrillances ne serait plus
  // jamais dessinée.
  return params.highlightsReusable && params.staticLayerReusable;
}
