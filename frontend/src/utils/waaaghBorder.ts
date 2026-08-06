/**
 * Waaagh! actif (08.04) — failles vertes ouvertes dans le pourtour du plateau.
 *
 * Ce module produit des SURFACES, pas des traits. Une première version traçait des polylignes
 * d'épaisseur constante : à l'écran, une ligne d'épaisseur constante ne peut lire que comme une
 * corde, et ses branches perpendiculaires comme des ficelles nouées dessus. Les quatre décisions
 * qui font la différence, toutes vérifiables ci-dessous :
 *
 *   1. DISCONTINU — une dizaine de failles indépendantes par bord, jamais un anneau qui fait le
 *      tour. Une fissure est un accident local.
 *   2. EFFILÉ — chaque faille est un polygone à deux rives dont la demi-largeur vaut zéro aux
 *      deux pointes et maximum vers le milieu. C'est ce profil qui dit « cassure » ; une largeur
 *      constante dit « cordon ».
 *   3. ANGLE AIGU — les ramifications quittent leur mère à 20-40°, pas à 90°, et rétrécissent de
 *      moitié à chaque niveau.
 *   4. CREUX — le remplissage va du vert vif sur les rives à un cœur presque noir : c'est le
 *      contraste sombre/lumineux qui donne la profondeur. Du vert plein sur un plateau vert reste
 *      plat quelle que soit la forme.
 *
 * Séparation géométrie / animation : `buildWaaaghCracks` produit une fois des polygones figés
 * (PRNG déterministe, jamais `Math.random`), `drawWaaaghCracks` les grave une fois dans des
 * `PIXI.Graphics`, et `setWaaaghCracksPulse` n'ajuste ensuite que l'`alpha` de ces objets. Aucune
 * re-triangulation par frame, et surtout : la forme ne bouge JAMAIS. Une géométrie régénérée en
 * continu grouille.
 *
 * Repère : celui des overlays de `app.stage` (mêmes pixels monde que la grille hex), origine en
 * haut-gauche du plateau, y vers le bas. Le tracé suit donc le pan et le zoom du plateau — un
 * halo CSS sur le canvas s'en décollerait au premier déplacement.
 */
import * as PIXI from "pixi.js-legacy";

/**
 * Couches concentriques d'une faille, de la plus large à la plus fine. `widthScale` multiplie la
 * demi-largeur du profil ; l'ordre est celui du dessin, donc du fond vers le dessus.
 *
 * Le cœur ne pulse pas (`alphaPulse: 0`) : un trou qui bat donnerait l'impression de s'ouvrir et
 * de se refermer. Ce qui respire, c'est la lumière autour.
 */
const CRACK_LAYERS = [
  /** Lueur diffuse qui déborde largement — l'énergie qui sort du sol. */
  { widthScale: 3.0, color: 0x0a5c16, alphaBase: 0.1, alphaPulse: 0.1 },
  /** Halo rapproché, transition vers les rives. */
  { widthScale: 1.75, color: 0x14a02a, alphaBase: 0.17, alphaPulse: 0.15 },
  /** Rives : le vert néon franc qui dessine la forme. */
  { widthScale: 1.0, color: 0x39ff14, alphaBase: 0.5, alphaPulse: 0.3 },
  /** Cœur : le vide sous la table. Presque noir, c'est lui qui creuse. */
  { widthScale: 0.52, color: 0x02140a, alphaBase: 0.92, alphaPulse: 0 },
  /** Éclat central : la lumière qui remonte du fond de la faille. */
  { widthScale: 0.18, color: 0xc9ffb8, alphaBase: 0.35, alphaPulse: 0.45 },
] as const;

/** Nombre de phases de pulsation distinctes. Une seule phase globale ferait clignoter tout le
 *  pourtour d'un bloc — l'effet « guirlande » que l'on cherche précisément à éviter. */
export const PULSE_GROUP_COUNT = 4;

/** Période de la respiration, en ms. Lente : c'est une braise, pas un clignotant. */
export const PULSE_PERIOD_MS = 2600;

/** Graine fixe : les failles ne dépendent que des dimensions du plateau, jamais du tour. */
export const WAAAGH_CRACKS_SEED = 0x57414147;

/**
 * Un groupe de pulsation : tous ses polygones partagent la même phase. `polygonsByLayer[i]`
 * correspond à `CRACK_LAYERS[i]`, chaque polygone étant une liste plate `[x0, y0, x1, y1, …]`.
 */
export interface WaaaghCrackGroup {
  /** Décalage de phase dans [0, 1). */
  phase: number;
  polygonsByLayer: number[][][];
}

export interface WaaaghCracksGeometry {
  groups: WaaaghCrackGroup[];
  /** Nombre de failles, ramifications comprises — lisible pour les tests et le diagnostic. */
  crackCount: number;
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

/** Squelette d'une faille dans le repère LOCAL d'un bord : `u` le long du bord, `v` en profondeur
 *  vers l'intérieur du plateau. Une demi-largeur par point, nulle aux deux extrémités. */
interface CrackSpine {
  points: Array<{ u: number; v: number }>;
  halfWidths: number[];
  /** Angle de la tangente au point d'attache de chaque segment — sert aux ramifications. */
  angles: number[];
}

/** Bornes du repère local : la bande dans laquelle une faille a le droit de vivre. */
interface LocalBounds {
  uMin: number;
  uMax: number;
  vMin: number;
  vMax: number;
}

/**
 * Fait pousser un squelette depuis `(u0, v0)` dans la direction `angle0`.
 *
 * La croissance REBONDIT sur les bornes (angle réfléchi) au lieu d'être tronquée : une faille
 * reste ainsi entière et dans sa bande, sans qu'aucun point n'ait à être ramené de force — un
 * `clamp` aurait produit des segments écrasés le long du bord, visiblement artificiels.
 */
function growSpine(
  rng: () => number,
  bounds: LocalBounds,
  start: { u: number; v: number; angle: number; length: number; maxHalfWidth: number }
): CrackSpine {
  const segments = 4 + Math.floor(rng() * 4);
  const segmentLength = start.length / segments;
  const points = [{ u: start.u, v: start.v }];
  const angles: number[] = [];
  let angle = start.angle;
  let u = start.u;
  let v = start.v;
  for (let i = 0; i < segments; i += 1) {
    // Irrégularité de parcours : sans elle le zigzag est périodique, donc lu comme une ondulation
    // régulière — l'autre moitié de l'effet « corde ».
    angle += (rng() - 0.5) * 0.55;
    let nextU = u + Math.cos(angle) * segmentLength;
    let nextV = v + Math.sin(angle) * segmentLength;
    if (nextV < bounds.vMin || nextV > bounds.vMax) {
      angle = -angle;
      nextV = v + Math.sin(angle) * segmentLength;
    }
    if (nextU < bounds.uMin || nextU > bounds.uMax) {
      angle = Math.PI - angle;
      nextU = u + Math.cos(angle) * segmentLength;
      nextV = v + Math.sin(angle) * segmentLength;
    }
    angles.push(angle);
    u = nextU;
    v = nextV;
    points.push({ u, v });
  }
  // Profil de largeur : nul aux deux pointes, maximal vers le milieu. L'exposant < 1 élargit le
  // ventre et raccourcit les pointes — au-delà, la faille ressemble à une lentille.
  const halfWidths = points.map((_, index) => {
    if (index === 0 || index === points.length - 1) return 0;
    const t = index / (points.length - 1);
    return start.maxHalfWidth * Math.sin(Math.PI * t) ** 0.7 * (0.7 + rng() * 0.6);
  });
  return { points, halfWidths, angles };
}

/** Conversion locale → monde d'un bord, sous forme de repère orthonormé. */
interface EdgeFrame {
  originX: number;
  originY: number;
  /** Vecteur unitaire le long du bord. */
  ux: number;
  uy: number;
  /** Normale unitaire rentrante. */
  nx: number;
  ny: number;
}

/**
 * Contour fermé d'une faille à l'échelle `widthScale` : rive gauche parcourue dans le sens du
 * squelette, puis rive droite en sens inverse.
 *
 * Les deux rives reçoivent un bruit INDÉPENDANT : une faille parfaitement symétrique autour de
 * son axe se lit comme un ruban. C'est l'asymétrie des deux bords qui la rend minérale.
 */
function crackPolygon(
  rng: () => number,
  spine: CrackSpine,
  frame: EdgeFrame,
  widthScale: number
): number[] {
  const toWorldX = (u: number, v: number) => frame.originX + frame.ux * u + frame.nx * v;
  const toWorldY = (u: number, v: number) => frame.originY + frame.uy * u + frame.ny * v;
  const left: number[] = [];
  const right: number[] = [];
  for (let i = 0; i < spine.points.length; i += 1) {
    const point = spine.points[i];
    // Normale locale au squelette, prise sur le segment adjacent.
    const angle = spine.angles[Math.min(i, spine.angles.length - 1)];
    const perpU = -Math.sin(angle);
    const perpV = Math.cos(angle);
    const half = spine.halfWidths[i] * widthScale;
    const leftHalf = half * (0.75 + rng() * 0.5);
    const rightHalf = half * (0.75 + rng() * 0.5);
    left.push(
      toWorldX(point.u + perpU * leftHalf, point.v + perpV * leftHalf),
      toWorldY(point.u + perpU * leftHalf, point.v + perpV * leftHalf)
    );
    right.push(
      toWorldX(point.u - perpU * rightHalf, point.v - perpV * rightHalf),
      toWorldY(point.u - perpU * rightHalf, point.v - perpV * rightHalf)
    );
  }
  const polygon = [...left];
  for (let i = right.length - 2; i >= 0; i -= 2) {
    polygon.push(right[i], right[i + 1]);
  }
  return polygon;
}

/**
 * Failles du pourtour : une bande de cassures indépendantes le long des quatre bords, chacune
 * ramifiée sur deux niveaux.
 *
 * `boardWidth`/`boardHeight` sont les dimensions TOTALES du plateau en pixels monde (celles de
 * `TOTAL_WIDTH`/`TOTAL_HEIGHT` côté BoardDisplay), marges comprises.
 */
export function buildWaaaghCracks(p: {
  boardWidth: number;
  boardHeight: number;
  hexRadius: number;
  seed: number;
}): WaaaghCracksGeometry {
  const { boardWidth: W, boardHeight: H, hexRadius: R } = p;
  if (!(W > 0) || !(H > 0) || !(R > 0)) {
    throw new Error(
      `buildWaaaghCracks: dimensions invalides (W=${W}, H=${H}, hexRadius=${R}) — ` +
        "la géométrie du plateau doit être connue avant de tracer les failles."
    );
  }
  const rng = makeRng(p.seed);
  /** Demi-largeur maximale d'une faille mère. */
  const maxHalfWidth = R * 1.15;
  /** Marge de sûreté : distance minimale entre le squelette d'une faille et le bord du plateau.
   *  Elle cumule les TROIS facteurs qui élargissent une rive au-delà de `maxHalfWidth` — le bruit
   *  du profil de largeur (≤ 1.3), l'échelle de la couche la plus large, et le bruit de rive
   *  (≤ 1.25). Ne retenir que l'échelle laissait dépasser les halos de quelques pixels. */
  const clearance = maxHalfWidth * 1.3 * CRACK_LAYERS[0].widthScale * 1.25;

  const groups: WaaaghCrackGroup[] = Array.from({ length: PULSE_GROUP_COUNT }, (_, index) => ({
    // Phases réparties puis brouillées : quatre phases exactement équidistantes produisent une
    // ronde perceptible, qui est une autre forme de régularité.
    phase: (index / PULSE_GROUP_COUNT + rng() * 0.12) % 1,
    polygonsByLayer: CRACK_LAYERS.map(() => []),
  }));

  const edges: Array<{ frame: EdgeFrame; length: number }> = [
    { frame: { originX: 0, originY: 0, ux: 1, uy: 0, nx: 0, ny: 1 }, length: W },
    { frame: { originX: W, originY: 0, ux: 0, uy: 1, nx: -1, ny: 0 }, length: H },
    { frame: { originX: W, originY: H, ux: -1, uy: 0, nx: 0, ny: -1 }, length: W },
    { frame: { originX: 0, originY: H, ux: 0, uy: -1, nx: 1, ny: 0 }, length: H },
  ];

  let crackCount = 0;
  /** Grave une faille et ses ramifications dans le groupe de pulsation tiré pour elle. */
  const emit = (spine: CrackSpine, frame: EdgeFrame, group: WaaaghCrackGroup) => {
    crackCount += 1;
    CRACK_LAYERS.forEach((layer, layerIndex) => {
      group.polygonsByLayer[layerIndex].push(crackPolygon(rng, spine, frame, layer.widthScale));
    });
  };

  for (const edge of edges) {
    const bounds: LocalBounds = {
      uMin: clearance,
      uMax: edge.length - clearance,
      vMin: clearance,
      // Bande de profondeur : les failles restent un phénomène de BORD. Au-delà elles envahiraient
      // la zone de jeu et cesseraient d'encadrer le plateau.
      vMax: clearance + R * 7,
    };
    if (bounds.uMax <= bounds.uMin || bounds.vMax <= bounds.vMin) {
      throw new Error(
        `buildWaaaghCracks: plateau trop petit pour la bande de failles (bord=${edge.length}, ` +
          `hexRadius=${R}) — aucune faille ne pourrait tenir dans le pourtour.`
      );
    }
    /** Une faille tous les ~18 hexagones, au moins trois par bord. */
    const crackTotal = Math.max(3, Math.round(edge.length / (R * 18)));
    for (let i = 0; i < crackTotal; i += 1) {
      const group = groups[Math.floor(rng() * PULSE_GROUP_COUNT)];
      // Positions échelonnées avec jitter : régulièrement espacées, la série se lit comme un motif.
      const u = bounds.uMin + ((i + 0.15 + rng() * 0.7) / crackTotal) * (bounds.uMax - bounds.uMin);
      const v = bounds.vMin + rng() * (bounds.vMax - bounds.vMin) * 0.55;
      // Direction dominante : le long du bord (une faille de bordure court avec le bord), déviée
      // d'un tiers de tour au plus. `Math.sign` : sens de parcours tiré à pile ou face.
      const along = rng() < 0.5 ? 0 : Math.PI;
      const angle = along + (rng() - 0.5) * 1.0;
      const length = R * (7 + rng() * 13);
      const spine = growSpine(rng, bounds, { u, v, angle, length, maxHalfWidth });
      const group0 = group;
      emit(spine, edge.frame, group0);

      // Ramifications, deux niveaux. Elles partent d'un point INTERNE de leur mère, à angle aigu,
      // et perdent la moitié de leur longueur et de leur largeur à chaque niveau.
      const branchFrom = (parent: CrackSpine, depth: number, parentLength: number) => {
        if (depth > 2) return;
        const branchTotal = depth === 1 ? 1 + Math.floor(rng() * 2) : Math.floor(rng() * 2);
        for (let b = 0; b < branchTotal; b += 1) {
          const anchor = 1 + Math.floor(rng() * Math.max(1, parent.points.length - 2));
          const point = parent.points[anchor];
          const parentAngle = parent.angles[Math.min(anchor, parent.angles.length - 1)];
          // 20° à 40°, d'un côté ou de l'autre : c'est l'angle aigu qui distingue une ramification
          // d'une « ficelle nouée » perpendiculaire.
          const deviation = (0.35 + rng() * 0.35) * (rng() < 0.5 ? -1 : 1);
          const branchLength = parentLength * (0.4 + rng() * 0.2);
          const branch = growSpine(rng, bounds, {
            u: point.u,
            v: point.v,
            angle: parentAngle + deviation,
            length: branchLength,
            maxHalfWidth: parent.halfWidths[anchor] * 0.55,
          });
          emit(branch, edge.frame, group0);
          branchFrom(branch, depth + 1, branchLength);
        }
      };
      branchFrom(spine, 1, length);
    }
  }

  return { groups, crackCount };
}

/**
 * Grave la géométrie dans `container` : un `PIXI.Graphics` par (couche, groupe de pulsation),
 * ordonné couche par couche pour que le halo d'une faille ne passe jamais par-dessus le cœur
 * d'une autre. Les enfants existants sont détruits — la fonction est réentrante.
 *
 * L'alpha de chaque `Graphics` est ensuite piloté par `setWaaaghCracksPulse` : c'est une propriété
 * du DisplayObject, donc l'animation ne re-triangule aucun polygone.
 */
export function drawWaaaghCracks(container: PIXI.Container, geometry: WaaaghCracksGeometry): void {
  for (const child of container.removeChildren()) {
    child.destroy({ children: true });
  }
  CRACK_LAYERS.forEach((layer, layerIndex) => {
    for (const group of geometry.groups) {
      const g = new PIXI.Graphics();
      g.eventMode = "none";
      g.beginFill(layer.color, 1);
      for (const polygon of group.polygonsByLayer[layerIndex]) {
        // Un polygone dégénéré (faille naine dont toutes les demi-largeurs sont nulles) n'a rien
        // à remplir : PIXI le tolère, mais le laisser passer masquerait un générateur en panne.
        if (polygon.length >= 6) g.drawPolygon(polygon);
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
export function setWaaaghCracksPulse(
  container: PIXI.Container,
  geometry: WaaaghCracksGeometry,
  elapsedMs: number
): void {
  const expected = CRACK_LAYERS.length * geometry.groups.length;
  if (container.children.length !== expected) {
    throw new Error(
      `setWaaaghCracksPulse: ${container.children.length} calques graves pour ${expected} attendus — ` +
        "la geometrie et le rendu ont diverge."
    );
  }
  CRACK_LAYERS.forEach((layer, layerIndex) => {
    geometry.groups.forEach((group, groupIndex) => {
      const child = container.children[layerIndex * geometry.groups.length + groupIndex];
      const pulse = 0.5 + 0.5 * Math.sin((elapsedMs / PULSE_PERIOD_MS + group.phase) * 2 * Math.PI);
      child.alpha = layer.alphaBase + layer.alphaPulse * pulse;
    });
  });
}
