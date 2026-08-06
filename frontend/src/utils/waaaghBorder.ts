/**
 * Waaagh! actif (08.04) — une gueule verte qui mord le plateau sur tout son pourtour.
 *
 * POURQUOI DES CROCS ET PLUS DES FISSURES. Deux versions ont échoué avant celle-ci, et pour des
 * raisons de forme, pas de réglage :
 *   - des polylignes d'épaisseur constante se lisent comme une corde, jamais comme une cassure ;
 *   - des failles fines, même bien profilées, MEURENT au dézoom : le plateau fait ~2700 px monde
 *     pour ~930 px à l'écran, et un détail de 4 px monde disparaît purement et simplement.
 * Une mâchoire est une forme MASSIVE et immédiatement reconnaissable : elle survit à l'échelle
 * d'affichage réelle, et le glyphe Ork est précisément une gueule.
 *
 * POURQUOI ÇA BRILLE. Deux mécanismes se cumulent, et aucun des deux n'est décoratif :
 *   - le mélange ADDITIF (`BLEND_MODES.ADD`) : les pixels s'ajoutent au fond au lieu de le
 *     recouvrir, ce qui EST la définition visuelle d'une source lumineuse. Un aplat translucide
 *     ordinaire ternit le terrain, il ne l'éclaire pas — c'est ce qui rendait le halo de la
 *     version précédente strictement invisible ;
 *   - un vrai `BlurFilter` sur les seules couches de halo, à `resolution` RÉDUITE. Un flou est
 *     flou par définition : le calculer dans une texture 4× plus petite en chaque dimension (16×
 *     moins de pixels) ne se voit pas, et ramène le coût à deux passes sur ~0,7 Mpx. À résolution
 *     pleine, le même filtre sur un plateau de 2700×4200 coûterait quinze fois plus pour un
 *     résultat identique à l'œil.
 * Le corps du croc, lui, reste NET : c'est un objet opaque, pas une lumière.
 *
 * Séparation géométrie / animation : `buildWaaaghFangs` produit une fois des polygones figés
 * (PRNG déterministe, jamais `Math.random`), `drawWaaaghFangs` les grave une fois dans des
 * `PIXI.Graphics`, et `setWaaaghFangsPulse` n'ajuste ensuite que l'`alpha` de ces objets. Aucune
 * re-triangulation par frame, et la forme ne bouge jamais.
 *
 * Repère : celui des overlays de `app.stage` (mêmes pixels monde que la grille hex), origine en
 * haut-gauche du plateau, y vers le bas. Le tracé suit donc le pan et le zoom du plateau — un
 * halo CSS sur le canvas s'en décollerait au premier déplacement.
 */
import * as PIXI from "pixi.js-legacy";

/**
 * Couches d'un croc, du fond vers le dessus. `swell` dilate (ou rétrécit) le contour d'une
 * distance constante, exprimée en fraction du `hexRadius`.
 *
 * `additive` : mélange ADD, donc la couche ÉCLAIRE le fond.
 * `blurHex` : rayon du flou, en `hexRadius`. Zéro = aucun filtre, donc aucune texture
 * intermédiaire — réservé aux couches qui doivent rester nettes.
 */
const FANG_LAYERS = [
  /** Lueur large et floue : la gueule irradie sur le terrain autour d'elle. */
  { swell: 1.5, blurHex: 1.6, color: 0x1f8f2a, alphaBase: 0.16, alphaPulse: 0.16, additive: true },
  /** Lueur proche, plus dense, à peine adoucie. */
  { swell: 0.7, blurHex: 0.7, color: 0x35c93a, alphaBase: 0.22, alphaPulse: 0.18, additive: true },
  /** Le croc lui-même : vert profond opaque et NET, c'est la matière. */
  { swell: 0.06, blurHex: 0, color: 0x0f5c17, alphaBase: 0.88, alphaPulse: 0, additive: false },
  /** Arête vive : le liseré néon qui dessine la silhouette. */
  { swell: -0.12, blurHex: 0, color: 0x39ff14, alphaBase: 0.55, alphaPulse: 0.25, additive: true },
  /** Crête centrale : l'éclat qui court de la base à la pointe. */
  { swell: -0.34, blurHex: 0, color: 0xd6ffb8, alphaBase: 0.3, alphaPulse: 0.4, additive: true },
] as const;

/**
 * Résolution des textures de flou, en fraction de celle du renderer. 0.25 = 16× moins de pixels à
 * filtrer. Monter cette valeur n'améliore rien de perceptible sur un flou de plusieurs hexagones
 * de rayon, et multiplie le coût par frame.
 */
const BLUR_RESOLUTION = 0.25;

/** Passes du flou. Deux suffisent pour un dégradé propre ; au-delà, coût sans gain visible. */
const BLUR_QUALITY = 2;

/** Nombre de phases de pulsation distinctes. Une seule phase globale ferait battre toute la
 *  gueule d'un bloc — l'effet « guirlande » que l'on cherche précisément à éviter. */
export const PULSE_GROUP_COUNT = 4;

/** Période de la respiration, en ms. Lente : la gueule serre, elle ne clignote pas. */
export const PULSE_PERIOD_MS = 2600;

/** Graine fixe : la denture ne dépend que des dimensions du plateau, jamais du tour. */
export const WAAAGH_CRACKS_SEED = 0x57414147;

/** Inclinaison maximale de la pointe, en fraction de la hauteur. Aucun croc n'est vertical — une
 *  rangée de dents parfaitement droites redevient un peigne. */
const MAX_FANG_TILT = 0.25;

/** Points par flanc. Assez pour que la concavité se voie, pas plus : chaque point est multiplié
 *  par 5 couches et par plusieurs centaines de crocs. */
const FANG_SIDE_STEPS = 6;

/** Pas moyen entre deux crocs, en `hexRadius`. Dimensionné pour rester lisible une fois le
 *  plateau dézoomé — c'est exactement ce que la version « failles » avait raté. */
const FANG_PITCH_HEX = 5;

/**
 * Trois calibres, dans l'ordre où ils se répètent : canine, petite, moyenne. Une rangée de dents
 * identiques se lit comme un peigne ; c'est l'alternance qui fait la mâchoire. Hauteurs et
 * demi-bases en `hexRadius` — la canine vaut ~9 hex, largement visible au dézoom.
 */
const FANG_CALIBRES = [
  { height: 9.0, halfBase: 2.1 },
  { height: 4.2, halfBase: 1.3 },
  { height: 6.4, halfBase: 1.7 },
] as const;

/** Amplitude du tirage sur la taille d'un croc, autour de son calibre. */
const FANG_SIZE_JITTER = { heightMin: 0.8, heightSpan: 0.4, baseMin: 0.85, baseSpan: 0.3 };

/**
 * Un groupe de pulsation : tous ses polygones partagent la même phase. `polygonsByLayer[i]`
 * correspond à `FANG_LAYERS[i]`, chaque polygone étant une liste plate `[x0, y0, x1, y1, …]`.
 */
export interface WaaaghFangGroup {
  /** Décalage de phase dans [0, 1). */
  phase: number;
  polygonsByLayer: number[][][];
}

export interface WaaaghFangsGeometry {
  groups: WaaaghFangGroup[];
  /** Nombre de crocs, tous bords confondus — lisible pour les tests et le diagnostic. */
  fangCount: number;
  /** Débordement maximal hors plateau, en pixels monde. Borne vérifiable, cf. son calcul. */
  maxOutwardBleed: number;
  /** Rayon de flou de chaque couche, en pixels monde (déjà multiplié par le `hexRadius`). */
  blurRadiiByLayer: number[];
}

/** PRNG mulberry32 — 32 bits, déterministe, sans état global (contrairement à `Math.random`). */
function makeRng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Conversion locale → monde d'un bord. `u` court le long du bord, `v` s'enfonce vers l'intérieur
 *  du plateau ; la base des crocs est posée en `v = 0`, donc exactement sur le bord. */
interface EdgeFrame {
  originX: number;
  originY: number;
  ux: number;
  uy: number;
  nx: number;
  ny: number;
}

/** Un croc, décrit dans le repère local de son bord. */
interface Fang {
  /** Position de la base le long du bord. */
  u: number;
  /** Demi-largeur de la base. */
  halfBase: number;
  /** Hauteur, vers l'intérieur du plateau. */
  height: number;
  /** Dérive latérale de la pointe, en fraction de la hauteur. */
  tilt: number;
}

/**
 * Contour fermé d'un croc, dilaté de `swell` (en pixels monde).
 *
 * Le profil est CONCAVE : la demi-largeur décroît en puissance > 1, si bien que le croc s'affine
 * vite en sortant de la base puis file en pointe. Un triangle isocèle donnerait une scie, pas une
 * dent — c'est cette courbure qui fait la différence entre « peigne » et « mâchoire ».
 */
function fangPolygon(fang: Fang, frame: EdgeFrame, swell: number): number[] {
  const toWorld = (u: number, v: number): [number, number] => [
    frame.originX + frame.ux * u + frame.nx * v,
    frame.originY + frame.uy * u + frame.ny * v,
  ];
  // Axe du croc : de la base `(u, 0)` à la pointe `(u + tilt · height, height)`. Dilater le croc,
  // c'est reculer la base ET allonger la pointe le long de cet axe, tout en épaississant les
  // flancs — sinon la pointe d'une couche dilatée resterait plantée au même endroit et le halo
  // s'arrêterait net avant le bout de la dent.
  const axisLength = Math.hypot(fang.tilt * fang.height, fang.height);
  const axisU = (fang.tilt * fang.height) / axisLength;
  const axisV = fang.height / axisLength;
  const baseU = fang.u - axisU * swell;
  const baseV = -axisV * swell;
  const height = fang.height + 2 * swell;
  if (!(height > 0)) {
    // Un croc qui ne dépasse pas sa propre dilatation n'a pas de forme. Renvoyer un polygone vide
    // laisserait un calque muet et un compteur menteur : c'est un générateur en panne, pas un cas
    // à absorber.
    throw new Error(
      `fangPolygon: croc degenere (hauteur=${fang.height}, dilatation=${swell}) — ` +
        "les calibres et les couches ne sont plus coherents."
    );
  }

  const left: number[] = [];
  const right: number[] = [];
  for (let i = 0; i <= FANG_SIDE_STEPS; i += 1) {
    const t = i / FANG_SIDE_STEPS;
    const halfWidth = Math.max(0, fang.halfBase * (1 - t) ** 1.7 + swell * (1 - t * 0.65));
    const centerU = baseU + axisU * height * t;
    const centerV = baseV + axisV * height * t;
    const [lx, ly] = toWorld(centerU - axisV * halfWidth, centerV + axisU * halfWidth);
    const [rx, ry] = toWorld(centerU + axisV * halfWidth, centerV - axisU * halfWidth);
    left.push(lx, ly);
    right.push(rx, ry);
  }
  const polygon = [...left];
  for (let i = right.length - 2; i >= 0; i -= 2) {
    polygon.push(right[i], right[i + 1]);
  }
  return polygon;
}

/**
 * La denture du pourtour : une rangée de crocs par bord, pointant vers l'intérieur, sur les
 * quatre côtés — la gueule fait le tour complet. Pas de gencive continue : des crocs, et rien
 * d'autre entre eux.
 *
 * `boardWidth`/`boardHeight` sont les dimensions TOTALES du plateau en pixels monde (celles de
 * `TOTAL_WIDTH`/`TOTAL_HEIGHT` côté BoardDisplay), marges comprises.
 */
export function buildWaaaghFangs(p: {
  boardWidth: number;
  boardHeight: number;
  hexRadius: number;
  seed: number;
}): WaaaghFangsGeometry {
  const { boardWidth: W, boardHeight: H, hexRadius: R } = p;
  if (!(W > 0) || !(H > 0) || !(R > 0)) {
    throw new Error(
      `buildWaaaghFangs: dimensions invalides (W=${W}, H=${H}, hexRadius=${R}) — ` +
        "la géométrie du plateau doit être connue avant de tracer la gueule."
    );
  }
  const rng = makeRng(p.seed);
  const pitch = R * FANG_PITCH_HEX;

  const groups: WaaaghFangGroup[] = Array.from({ length: PULSE_GROUP_COUNT }, (_, index) => ({
    // Phases réparties puis brouillées : quatre phases exactement équidistantes produisent une
    // ronde perceptible, qui est une autre forme de régularité.
    phase: (index / PULSE_GROUP_COUNT + rng() * 0.12) % 1,
    polygonsByLayer: FANG_LAYERS.map(() => []),
  }));

  const edges: Array<{ frame: EdgeFrame; length: number }> = [
    { frame: { originX: 0, originY: 0, ux: 1, uy: 0, nx: 0, ny: 1 }, length: W },
    { frame: { originX: W, originY: 0, ux: 0, uy: 1, nx: -1, ny: 0 }, length: H },
    { frame: { originX: W, originY: H, ux: -1, uy: 0, nx: 0, ny: -1 }, length: W },
    { frame: { originX: 0, originY: H, ux: 0, uy: -1, nx: 1, ny: 0 }, length: H },
  ];

  let fangCount = 0;
  for (const edge of edges) {
    if (edge.length < pitch * 2) {
      throw new Error(
        `buildWaaaghFangs: bord de ${edge.length} px trop court pour des crocs de pas ${pitch} ` +
          `(hexRadius=${R}) — la gueule ne pourrait pas faire le tour.`
      );
    }
    const fangTotal = Math.max(4, Math.round(edge.length / pitch));
    const spacing = edge.length / fangTotal;
    for (let i = 0; i < fangTotal; i += 1) {
      const calibre = FANG_CALIBRES[i % FANG_CALIBRES.length];
      const fang: Fang = {
        // Jitter borné à un tiers du pas : au-delà les crocs se chevauchent, en deçà la rangée
        // redevient un peigne régulier.
        u: (i + 0.5) * spacing + (rng() - 0.5) * spacing * 0.34,
        halfBase:
          R * calibre.halfBase * (FANG_SIZE_JITTER.baseMin + rng() * FANG_SIZE_JITTER.baseSpan),
        height:
          R * calibre.height * (FANG_SIZE_JITTER.heightMin + rng() * FANG_SIZE_JITTER.heightSpan),
        tilt: (rng() - 0.5) * 2 * MAX_FANG_TILT,
      };
      const group = groups[Math.floor(rng() * PULSE_GROUP_COUNT)];
      fangCount += 1;
      FANG_LAYERS.forEach((layer, layerIndex) => {
        group.polygonsByLayer[layerIndex].push(fangPolygon(fang, edge.frame, layer.swell * R));
      });
    }
  }

  // Débordement extérieur maximal, borné ANALYTIQUEMENT à partir des paramètres de génération —
  // et non mesuré sur le résultat, ce qui rendrait le contrôle tautologique. Deux termes, et le
  // second a été oublié une première fois : la dilatation recule la base le long de l'axe, ET la
  // demi-largeur dilatée déborde vers l'extérieur dès que le croc est incliné, à hauteur de sa
  // projection sur la normale du bord (majorée par `MAX_FANG_TILT`).
  const maxSwell = Math.max(...FANG_LAYERS.map((layer) => layer.swell)) * R;
  const maxHalfBase =
    R *
    Math.max(...FANG_CALIBRES.map((calibre) => calibre.halfBase)) *
    (FANG_SIZE_JITTER.baseMin + FANG_SIZE_JITTER.baseSpan);
  return {
    groups,
    fangCount,
    maxOutwardBleed: maxSwell + (maxHalfBase + maxSwell) * MAX_FANG_TILT,
    blurRadiiByLayer: FANG_LAYERS.map((layer) => layer.blurHex * R),
  };
}

/**
 * Grave la géométrie dans `container` : un `PIXI.Graphics` par (couche, groupe de pulsation),
 * ordonné couche par couche pour que la lueur d'un croc ne passe jamais par-dessus le corps d'un
 * autre. Les enfants existants sont détruits — la fonction est réentrante.
 *
 * Le `BlurFilter` n'est posé que sur les couches qui le demandent, et à résolution réduite : sans
 * ce garde-fou, chaque couche coûterait une texture plein plateau par frame.
 *
 * L'alpha de chaque `Graphics` est ensuite piloté par `setWaaaghFangsPulse` : c'est une propriété
 * du DisplayObject, donc l'animation ne re-triangule ni ne re-filtre rien de plus.
 */
export function drawWaaaghFangs(container: PIXI.Container, geometry: WaaaghFangsGeometry): void {
  for (const child of container.removeChildren()) {
    child.destroy({ children: true });
  }
  FANG_LAYERS.forEach((layer, layerIndex) => {
    const blurRadius = geometry.blurRadiiByLayer[layerIndex];
    for (const group of geometry.groups) {
      const g = new PIXI.Graphics();
      g.eventMode = "none";
      // ADD : la couche s'ajoute au fond au lieu de le recouvrir. C'est ce qui fait qu'un vert
      // translucide ÉCLAIRE le terrain au lieu de le ternir.
      if (layer.additive) g.blendMode = PIXI.BLEND_MODES.ADD;
      if (blurRadius > 0) {
        const blur = new PIXI.BlurFilter(blurRadius, BLUR_QUALITY, BLUR_RESOLUTION);
        // La zone filtrée déborde de la forme : sans marge, le flou serait coupé net au ras des
        // crocs et redeviendrait un aplat à bord franc — le défaut même qu'il corrige.
        blur.padding = blurRadius * 2;
        g.filters = [blur];
      }
      g.beginFill(layer.color, 1);
      for (const polygon of group.polygonsByLayer[layerIndex]) {
        g.drawPolygon(polygon);
      }
      g.endFill();
      container.addChild(g);
    }
  });
}

/**
 * Ajuste l'opacité des couches gravées pour l'instant `elapsedMs`. À appeler à chaque frame ;
 * ne touche QUE `alpha`.
 *
 * Lève si le contenu du container ne correspond pas à la géométrie : c'est le signe que les deux
 * ont divergé (géométrie reconstruite sans re-gravure), et le rendu serait alors silencieusement
 * décalé d'une couche.
 */
export function setWaaaghFangsPulse(
  container: PIXI.Container,
  geometry: WaaaghFangsGeometry,
  elapsedMs: number
): void {
  const expected = FANG_LAYERS.length * geometry.groups.length;
  if (container.children.length !== expected) {
    throw new Error(
      `setWaaaghFangsPulse: ${container.children.length} calques graves pour ${expected} attendus — ` +
        "la geometrie et le rendu ont diverge."
    );
  }
  FANG_LAYERS.forEach((layer, layerIndex) => {
    geometry.groups.forEach((group, groupIndex) => {
      const child = container.children[layerIndex * geometry.groups.length + groupIndex];
      const pulse = 0.5 + 0.5 * Math.sin((elapsedMs / PULSE_PERIOD_MS + group.phase) * 2 * Math.PI);
      child.alpha = layer.alphaBase + layer.alphaPulse * pulse;
    });
  });
}
