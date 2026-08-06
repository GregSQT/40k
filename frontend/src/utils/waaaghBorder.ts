/**
 * Waaagh! actif (08.04) — fissures vertes sur tout le pourtour du plateau.
 *
 * Deux étapes SÉPARÉES, et la séparation est le point du module :
 *   - `buildWaaaghCracks` produit la GÉOMÉTRIE une seule fois (polylignes en pixels monde) ;
 *   - `drawWaaaghCracks` la redessine à chaque frame avec une intensité `pulse` variable.
 *
 * Regénérer la géométrie par frame la ferait GROUILLER : une fissure est une cassure figée dans
 * le décor, seule sa lueur respire. C'est aussi pourquoi le générateur prend une `seed` et un
 * PRNG déterministe plutôt que `Math.random`.
 *
 * Repère : celui des overlays de `app.stage` (mêmes pixels monde que la grille hex), origine en
 * haut-gauche du plateau, y vers le bas. Le tracé suit donc le pan et le zoom du plateau — un
 * halo CSS sur le canvas s'en décollerait au premier déplacement.
 */
import type * as PIXI from "pixi.js-legacy";

export interface WaaaghCracksGeometry {
  /** Polylignes en pixels monde. La première est le pourtour ; les suivantes sont les branches. */
  strokes: Array<Array<{ x: number; y: number }>>;
}

/** Vert néon du cœur de fissure, et vert profond du halo qui le déborde. */
const WAAAGH_GLOW_COLOR = 0x0b6b16;
const WAAAGH_CRACK_COLOR = 0x39ff14;
const WAAAGH_CORE_COLOR = 0xd8ffcc;

/** Graine fixe : la fissure ne dépend que des dimensions du plateau, jamais du tour ni du hasard. */
export const WAAAGH_CRACKS_SEED = 0x57414147;

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

/**
 * Fissures du pourtour : un anneau brisé qui longe les 4 bords, plus des branches qui partent
 * vers l'intérieur du plateau.
 *
 * `boardWidth`/`boardHeight` sont les dimensions TOTALES du plateau en pixels monde (celles de
 * `TOTAL_WIDTH`/`TOTAL_HEIGHT` côté BoardDisplay), marges comprises : la fissure court sur le
 * bord réel de la table, pas sur la première colonne d'hexagones.
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
        "la géométrie du plateau doit être connue avant de tracer les fissures."
    );
  }
  const rng = makeRng(p.seed);
  /** Distance moyenne entre deux ruptures : une cassure tous les ~3 hex. */
  const step = R * 4.5;
  /** Amplitude du zigzag, vers l'INTÉRIEUR uniquement (une fissure ne sort pas de la table). */
  const jag = R * 1.6;
  /** Retrait du tracé par rapport au bord : le trait large du halo doit tenir dans le plateau. */
  const inset = R * 1.2;

  const strokes: Array<Array<{ x: number; y: number }>> = [];
  const ring: Array<{ x: number; y: number }> = [];
  /** Sommets d'où partiront les branches, avec la direction « vers l'intérieur » de leur bord. */
  const branchSeeds: Array<{ x: number; y: number; nx: number; ny: number }> = [];

  // Les 4 bords, parcourus dans le sens horaire. `nx/ny` = normale rentrante du bord courant.
  const edges = [
    { x0: inset, y0: inset, x1: W - inset, y1: inset, nx: 0, ny: 1 },
    { x0: W - inset, y0: inset, x1: W - inset, y1: H - inset, nx: -1, ny: 0 },
    { x0: W - inset, y0: H - inset, x1: inset, y1: H - inset, nx: 0, ny: -1 },
    { x0: inset, y0: H - inset, x1: inset, y1: inset, nx: 1, ny: 0 },
  ];

  for (const edge of edges) {
    const dx = edge.x1 - edge.x0;
    const dy = edge.y1 - edge.y0;
    const length = Math.hypot(dx, dy);
    const segments = Math.max(3, Math.round(length / step));
    // `i` part de 0 : le premier point de chaque bord recouvre le dernier du bord précédent, ce
    // qui ferme l'anneau sans point isolé dans les angles.
    for (let i = 0; i <= segments; i += 1) {
      const t = i / segments;
      // Les extrémités restent dans l'angle exact : un décalage y aurait ouvert le coin.
      const amp = i === 0 || i === segments ? 0 : jag * (0.25 + 0.75 * rng());
      const x = edge.x0 + dx * t + edge.nx * amp;
      const y = edge.y0 + dy * t + edge.ny * amp;
      ring.push({ x, y });
      if (i > 0 && i < segments && rng() < 0.28) {
        branchSeeds.push({ x, y, nx: edge.nx, ny: edge.ny });
      }
    }
  }
  ring.push({ ...ring[0] });
  strokes.push(ring);

  // Branches : une fissure qui s'enfonce de 2 à 4 hex vers l'intérieur, en serpentant.
  // Elles ne se ramifient pas davantage — au-delà, le pourtour se lit comme une toile d'araignée
  // et non comme une cassure.
  //
  // Construites dans le repère LOCAL du bord (`v` = profondeur vers l'intérieur, `u` = le long du
  // bord) avec `v` STRICTEMENT CROISSANT. Un serpentement libre en angle absolu pouvait repartir
  // vers l'extérieur au bout de deux ou trois déviations cumulées et sortir du plateau — la
  // fissure se serait dessinée dans le vide autour de la table.
  for (const seed of branchSeeds) {
    const segments = 2 + Math.floor(rng() * 3);
    const branch: Array<{ x: number; y: number }> = [{ x: seed.x, y: seed.y }];
    // Vecteur unitaire le long du bord = normale tournée d'un quart de tour.
    const ux = -seed.ny;
    const uy = seed.nx;
    let u = 0;
    let v = 0;
    for (let i = 0; i < segments; i += 1) {
      v += R * (0.9 + rng() * 1.1);
      u += R * (rng() - 0.5) * 2.2;
      branch.push({
        x: seed.x + seed.nx * v + ux * u,
        y: seed.y + seed.ny * v + uy * u,
      });
    }
    strokes.push(branch);
  }

  return { strokes };
}

/**
 * Redessine les fissures dans `g` (vidé au passage) à l'intensité `pulse` ∈ [0, 1].
 *
 * TROIS PASSES superposées, du plus large au plus fin : c'est ce qui donne le néon (PIXI n'a pas
 * de flou sans filtre, et un filtre sur un overlay plein plateau coûte une passe de rendu
 * entière). Seul le halo et le trait médian respirent ; le cœur reste constant, sinon la fissure
 * paraît s'ouvrir et se refermer.
 */
export function drawWaaaghCracks(
  g: PIXI.Graphics,
  geometry: WaaaghCracksGeometry,
  p: { hexRadius: number; pulse: number }
): void {
  const R = p.hexRadius;
  const pulse = Math.min(1, Math.max(0, p.pulse));
  g.clear();
  const passes = [
    { width: R * 2.0, color: WAAAGH_GLOW_COLOR, alpha: 0.1 + 0.16 * pulse },
    { width: R * 0.8, color: WAAAGH_CRACK_COLOR, alpha: 0.35 + 0.3 * pulse },
    { width: R * 0.28, color: WAAAGH_CORE_COLOR, alpha: 0.9 },
  ];
  for (const pass of passes) {
    for (const stroke of geometry.strokes) {
      if (stroke.length < 2) continue;
      g.lineStyle({ width: Math.max(1, pass.width), color: pass.color, alpha: pass.alpha });
      g.moveTo(stroke[0].x, stroke[0].y);
      for (let i = 1; i < stroke.length; i += 1) {
        g.lineTo(stroke[i].x, stroke[i].y);
      }
    }
  }
  g.lineStyle(0);
}
