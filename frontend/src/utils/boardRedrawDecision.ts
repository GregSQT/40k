/**
 * Le plateau PIXI est fait de DEUX calques au cycle de vie distinct :
 *
 * - le calque STATIQUE (fond, murs, décor, **couleur de contrôle des objectifs**), invalidé par
 *   `geomKey` + `controlKey` — dimensions, géométrie des zones, murs, phase de déploiement, et contrôle d'objectif ;
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
 * DÉFAUTS MESURÉS (2026-08-12) que ce contrat ferme, chacun un conteneur périmé laissé sur le
 * stage : `drawBoard` court-circuitée sur la seule réutilisabilité des surbrillances, alors que la
 * couleur de contrôle vit dans le statique (une zone capturée n'a plus jamais changé de couleur
 * de la partie) ; le statique périmé ré-attaché AU-DESSUS du neuf, que `drawBoard` insère en
 * index 0 ; les surbrillances conservées pendant que `drawBoard` en ajoutait de nouvelles.
 *
 * L'invariant qui les ferme tous : **on ne conserve jamais un calque que `drawBoard` va recréer.**
 */
import type { DrawBoardResult } from "../components/BoardDisplay";

/** Calques que `drawBoard` recrée avec le fond et le décor — cycle de vie du STATIQUE. */
const STATIC_LAYERS = ["baseHexContainer", "wallsContainer"] as const;
/** Calques que `drawBoard` recrée à chaque appel — cycle de vie des SURBRILLANCES. */
const HIGHLIGHT_LAYERS = ["highlightContainer", "floorContourContainer"] as const;

/**
 * GARDE-FOU DE COMPLÉTUDE, vérifiée par le compilateur et par rien d'autre.
 *
 * Le plan ci-dessous n'est exhaustif que parce que `drawBoard` produit exactement ces quatre
 * conteneurs, en deux cycles de vie. Ajouter un cinquième champ à `DrawBoardResult` sans le
 * classer ici en ferait un orphelin VISIBLE sur le stage, en silence — c'est exactement la classe
 * de défaut corrigée. Ce type force alors une erreur de compilation.
 */
type _TousLesCalquesOntUnCycleDeVie = keyof DrawBoardResult extends
  | (typeof STATIC_LAYERS)[number]
  | (typeof HIGHLIGHT_LAYERS)[number]
  ? true
  : never;
/** Consommation du garde-fou : sans usage, `noUnusedLocals` supprimerait la vérification. */
export const LAYER_LIFECYCLES_ARE_EXHAUSTIVE: _TousLesCalquesOntUnCycleDeVie = true;

/**
 * Clé de GÉOMÉTRIE du plateau statique : dimensions, zones d'objectif (forme + coordonnées),
 * murs, et flag déploiement. Ne change qu'au chargement d'un plateau ou d'un épisode de replay,
 * jamais lors d'une capture d'objectif.
 */
export function buildBoardGeomKey(params: {
  cols: number;
  rows: number;
  objectiveZonesGeomKey: string;
  wallsFp: string;
  isDeployment: boolean;
}): string {
  const { cols, rows, objectiveZonesGeomKey, wallsFp, isDeployment } = params;
  return `${cols}x${rows}|oz:${objectiveZonesGeomKey}|w:${wallsFp}|dep:${isDeployment ? 1 : 0}`;
}

/**
 * Clé de CONTRÔLE du plateau statique : couleur de contrôle des objectifs (14.02). Change à
 * chaque capture d'objectif ou bascule de contrôleur.
 */
export function buildBoardControlKey(params: { objectiveControlKeyForBoard: string }): string {
  return `oc:${params.objectiveControlKeyForBoard}`;
}

/**
 * Le calque statique PIXI est réutilisable exactement quand les deux clés sont inchangées ET
 * que le conteneur existe encore. Cette décision était inline dans `BoardPvp` ; elle vit ici
 * pour être verrouillée par les tests plutôt que par la discipline du prochain lecteur.
 */
export function computeStaticLayerReusable(params: {
  prevGeomKey: string;
  currGeomKey: string;
  prevControlKey: string;
  currControlKey: string;
  staticLayerExists: boolean;
}): boolean {
  const { prevGeomKey, currGeomKey, prevControlKey, currControlKey, staticLayerExists } = params;
  return prevGeomKey === currGeomKey && prevControlKey === currControlKey && staticLayerExists;
}

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
  /** `geomKey` et `controlKey` sont inchangées ET le calque statique existe encore. */
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
