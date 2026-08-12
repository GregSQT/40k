/**
 * Le plateau PIXI est fait de DEUX calques au cycle de vie distinct :
 *
 * - le calque STATIQUE (fond, murs, décor, **couleur de contrôle des objectifs**), invalidé par
 *   `bcKey` — dimensions, contrôle d'objectif, géométrie des zones, murs, phase de déploiement ;
 * - les SURBRILLANCES (previews de move/tir/charge, halos, voiles, contours d'étage), invalidées
 *   par l'empreinte structurelle de `computeDrawBoardPartialRedrawFingerprint`.
 *
 * `drawBoard` reconstruit les deux. Autour d'elle, `BoardPvp` vide le stage puis ré-attache ce
 * qu'il veut conserver. TROIS décisions doivent donc s'accorder : appeler `drawBoard` ou non,
 * conserver le calque statique ou non, conserver les surbrillances ou non. Prises séparément,
 * elles se contredisent, et chaque contradiction laisse un conteneur périmé VISIBLE sur le stage.
 *
 * D'où ce module : les trois sortent d'un seul calcul, et les invariants sont verrouillés par des
 * tests plutôt que par la discipline du prochain lecteur.
 *
 * ─── DÉFAUTS MESURÉS QUI ONT MOTIVÉ CE CONTRAT ────────────────────────────────────────────────
 *
 * 1. `drawBoard` était court-circuitée sur la SEULE réutilisabilité des surbrillances, alors que
 *    la couleur de contrôle des objectifs vit dans le calque statique — et que `objectiveControl`
 *    n'apparaît nulle part dans l'empreinte des surbrillances. Trace console en jeu (2026-08-12) :
 *    UNE reconstruction, à un instant où une zone était déjà tenue et l'autre pas encore, puis
 *    réutilisation jusqu'à la fin de la partie. La seconde zone n'a jamais changé de couleur.
 *
 * 2. Corriger (1) a rendu atteignables deux chemins qui ne l'étaient pas (trouvés par
 *    `/code-review`), tous deux du même genre — un conteneur périmé laissé sur le stage :
 *    - le calque statique périmé était ré-attaché puis `drawBoard` insérait le neuf en index 0,
 *      donc EN DESSOUS (zIndex égaux, tri stable) : la couleur affichée restait l'ancienne et les
 *      remplissages de terrain se doublaient ;
 *    - les surbrillances conservées restaient sur le stage pendant que `drawBoard` en ajoutait de
 *      nouvelles : previews et contours d'étage en double, alpha doublée, et les anciens
 *      orphelins jusqu'au balayage suivant.
 *
 * L'invariant qui ferme les deux : **on ne conserve jamais un calque que `drawBoard` va recréer.**
 */

/** Ce que `BoardPvp` doit faire de son stage pour ce rendu. */
export interface BoardRedrawPlan {
  /** Appeler `drawBoard` (elle recrée les surbrillances, et le statique si absent du cache). */
  callDrawBoard: boolean;
  /** Ré-attacher le calque statique existant. Faux ⇒ le DÉTRUIRE, `drawBoard` en fera un neuf. */
  keepStaticLayer: boolean;
  /** Ré-attacher surbrillances et contours d'étage. Faux ⇒ les laisser au balayage destructeur. */
  keepHighlightLayers: boolean;
}

export function planBoardRedraw(params: {
  /** Le calque des surbrillances est intact ET son empreinte structurelle est inchangée. */
  highlightsReusable: boolean;
  /** `bcKey` est inchangée ET le calque statique existe encore. */
  staticLayerReusable: boolean;
}): BoardRedrawPlan {
  const { highlightsReusable, staticLayerReusable } = params;
  // La conjonction est le correctif du défaut (1) : un statique périmé impose le redessin, même
  // quand les surbrillances n'ont pas bougé.
  const callDrawBoard = !(highlightsReusable && staticLayerReusable);
  return {
    callDrawBoard,
    // Le statique survit exactement quand il est encore valide — jamais parce que les
    // surbrillances, elles, le sont.
    keepStaticLayer: staticLayerReusable,
    // Correctif du défaut (2) : `drawBoard` ajoute TOUJOURS un nouveau conteneur de
    // surbrillances et de contours d'étage. En conserver un pendant qu'elle tourne le laisse
    // orphelin et visible. Donc : on ne les garde que si elle ne tourne pas.
    keepHighlightLayers: !callDrawBoard,
  };
}
