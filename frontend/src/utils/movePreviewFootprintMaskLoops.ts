/**
 * Normalise ``move_preview_footprint_mask_loops`` API (boucles [[x,y],…]) → ``number[][]``
 * (chaque boucle : [x0,y0,…] plat) pour BoardDisplay / hit-test.
 */
export function normalizeMaskLoopsFromApi(raw: unknown): number[][] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: number[][] = [];
  for (const loop of raw) {
    if (!Array.isArray(loop)) continue;
    const flat: number[] = [];
    for (const pt of loop) {
      if (Array.isArray(pt) && pt.length >= 2) {
        flat.push(Number(pt[0]), Number(pt[1]));
      }
    }
    if (flat.length >= 6) out.push(flat);
  }
  return out.length > 0 ? out : null;
}
