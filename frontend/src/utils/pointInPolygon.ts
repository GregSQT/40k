/** Ray casting : point dans un polygone fermé (sommets plats [x0,y0,…]). */
export function pointInPolygon(px: number, py: number, flat: number[]): boolean {
  let inside = false;
  const nv = flat.length / 2;
  if (nv < 3) return false;
  for (let i = 0, j = nv - 1; i < nv; j = i, i++) {
    const xi = flat[i * 2]!;
    const yi = flat[i * 2 + 1]!;
    const xj = flat[j * 2]!;
    const yj = flat[j * 2 + 1]!;
    const dy = yj - yi;
    if (dy === 0) continue;
    const intersect =
      yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / dy + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function pointInAnyMaskLoop(px: number, py: number, loops: number[][]): boolean {
  for (const loop of loops) {
    if (pointInPolygon(px, py, loop)) return true;
  }
  return false;
}
