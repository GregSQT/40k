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
    const intersect = yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / dy + xi;
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

/**
 * Point dans la surface RÉELLEMENT PEINTE par un masque à trous (règle pair-impair).
 *
 * Différence avec `pointInAnyMaskLoop`, qui est un OU : une boucle imbriquée dans une autre est
 * un TROU, pas une surface. Le rendu le fait explicitement (`beginHole` sur toute boucle dont le
 * centroïde tombe dans une boucle plus grande) ; un OU répondrait « dedans » pour un point situé
 * dans un trou visiblement non peint — typiquement, pour l'aire d'arrivée des réserves (20.04),
 * les bulles d'exclusion de 9" autour de chaque unité ennemie.
 *
 * Compter les appartenances et regarder leur parité redonne exactement la surface peinte : 1 pour
 * l'intérieur d'un anneau, 2 (donc dehors) pour un trou, 3 pour un îlot dans ce trou.
 */
export function pointInMaskLoopsEvenOdd(px: number, py: number, loops: number[][]): boolean {
  let crossings = 0;
  for (const loop of loops) {
    if (pointInPolygon(px, py, loop)) crossings++;
  }
  return crossings % 2 === 1;
}
