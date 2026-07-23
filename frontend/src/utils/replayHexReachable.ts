/**
 * BFS d'atteignabilité hex pour le replay (move / advance).
 *
 * Le replay ne reçoit pas le pool moteur (`valid_move_destinations_pool`) : il est calculé
 * en live côté backend lors de la sélection en PvP. On reproduit donc côté client un BFS
 * borné par un budget en sous-hex (positions et board déjà en grille fine sous-hex).
 *
 * Voile de précision assumé (cf. décision replay) : mêmes voisins/traversabilité que le BFS
 * d'advance historique (bornes, murs, occupation) ; pas de blocage fin sur la zone d'engagement.
 */

export interface HexPos {
  col: number;
  row: number;
}

interface ReachableUnit {
  col: number;
  row: number;
  id: number;
  HP_CUR: number;
}

/** Voisins hex (offset odd-q, parité par colonne) — identique aux BFS charge/advance existants. */
function getHexNeighbors(col: number, row: number): HexPos[] {
  const parity = col & 1;
  if (parity === 0) {
    return [
      { col, row: row - 1 },
      { col: col + 1, row: row - 1 },
      { col: col + 1, row },
      { col, row: row + 1 },
      { col: col - 1, row },
      { col: col - 1, row: row - 1 },
    ];
  }
  return [
    { col, row: row - 1 },
    { col: col + 1, row },
    { col: col + 1, row: row + 1 },
    { col, row: row + 1 },
    { col: col - 1, row: row + 1 },
    { col: col - 1, row },
  ];
}

export interface HexReachableParams {
  from: HexPos;
  /** Budget de déplacement en pas sous-hex (ex: MOVE_pouces × inches_to_subhex). */
  budget: number;
  boardCols: number;
  boardRows: number;
  walls: HexPos[] | undefined;
  units: ReachableUnit[];
  /** Unité en mouvement : exclue du test d'occupation (elle libère sa case de départ). */
  selfUnitId: number;
}

/**
 * Retourne toutes les cases atteignables (hors case de départ) dans la limite du budget.
 * Reproduit exactement la sémantique du BFS d'advance : une case est retenue si
 * 0 < distance ≤ budget et traversable ; l'expansion continue tant que distance < budget.
 */
export function computeHexReachable(params: HexReachableParams): HexPos[] {
  const { from, budget, boardCols, boardRows, walls, units, selfUnitId } = params;
  if (budget <= 0) return [];

  const isTraversable = (col: number, row: number): boolean => {
    if (col < 0 || row < 0 || col >= boardCols || row >= boardRows) {
      return false;
    }
    if (walls?.some((w) => w.col === col && w.row === row)) {
      return false;
    }
    if (
      units.some(
        (u) => u.col === col && u.row === row && u.id !== selfUnitId && u.id >= 0 && u.HP_CUR > 0
      )
    ) {
      return false;
    }
    return true;
  };

  const validDestinations: HexPos[] = [];
  const visited = new Set<string>();
  const queue: Array<{ col: number; row: number; distance: number }> = [
    { col: from.col, row: from.row, distance: 0 },
  ];
  visited.add(`${from.col},${from.row}`);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const { col, row, distance } = current;

    if (distance > 0 && distance <= budget && isTraversable(col, row)) {
      validDestinations.push({ col, row });
    }

    if (distance < budget) {
      const neighbors = getHexNeighbors(col, row);
      for (const neighbor of neighbors) {
        const neighborKey = `${neighbor.col},${neighbor.row}`;
        if (!visited.has(neighborKey)) {
          visited.add(neighborKey);
          const neighborDistance = distance + 1;
          if (neighborDistance <= budget && isTraversable(neighbor.col, neighbor.row)) {
            queue.push({ col: neighbor.col, row: neighbor.row, distance: neighborDistance });
          }
        }
      }
    }
  }

  return validDestinations;
}
