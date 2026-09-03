"""
Hex grid primitives — single source of truth (geometrie_et_distances.md (ex-Boardx10-final) §2.2, §2.3).

Coordinate system: offset odd-q
  - (col, row) with 0 <= col < COLS, 0 <= row < ROWS
  - Odd columns (col % 2 == 1) are shifted +½ row downward

All functions are O(1) per call unless documented otherwise.
"""

import heapq
import math
from functools import lru_cache
from typing import (
    AbstractSet,
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    overload,
)

import numpy as np


# ---------------------------------------------------------------------------
# Neighbor offsets — offset odd-q (§2.2 P2)
# ---------------------------------------------------------------------------

_NEIGHBORS_EVEN_COL: Tuple[Tuple[int, int], ...] = (
    (0, -1),    # N
    (1, -1),    # NE
    (1, 0),     # SE
    (0, 1),     # S
    (-1, 0),    # SW
    (-1, -1),   # NW
)

_NEIGHBORS_ODD_COL: Tuple[Tuple[int, int], ...] = (
    (0, -1),    # N
    (1, 0),     # NE
    (1, 1),     # SE
    (0, 1),     # S
    (-1, 1),    # SW
    (-1, 0),    # NW
)


def get_neighbors(col: int, row: int) -> List[Tuple[int, int]]:
    """Return the 6 hex neighbors of (col, row) in offset odd-q.

    No bounds checking — caller must filter out-of-bounds if needed.
    """
    offsets = _NEIGHBORS_ODD_COL if (col & 1) else _NEIGHBORS_EVEN_COL
    return [(col + dc, row + dr) for dc, dr in offsets]


def get_neighbors_bounded(
    col: int, row: int, cols: int, rows: int
) -> List[Tuple[int, int]]:
    """Return neighbors of (col, row) that are within [0, cols) × [0, rows)."""
    offsets = _NEIGHBORS_ODD_COL if (col & 1) else _NEIGHBORS_EVEN_COL
    result: List[Tuple[int, int]] = []
    for dc, dr in offsets:
        nc, nr = col + dc, row + dr
        if 0 <= nc < cols and 0 <= nr < rows:
            result.append((nc, nr))
    return result


# ---------------------------------------------------------------------------
# Coordinate conversions — offset odd-q ↔ cube (§2.2 P2)
# ---------------------------------------------------------------------------

def offset_to_cube(col: int, row: int) -> Tuple[int, int, int]:
    """Convert offset odd-q (col, row) to cube (x, y, z).

    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    """
    x = col
    z = row - ((col - (col & 1)) >> 1)
    y = -x - z
    return x, y, z


def offset_to_cube_vec(
    cols: np.ndarray, rows: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Jumeau VECTORISÉ de :func:`offset_to_cube` — mêmes opérations, sur des tableaux.

    `& 1` et `>> 1` se comportent identiquement sur un `int` Python et un `int64` numpy, y
    compris en négatif : les deux fonctions rendent donc les mêmes entiers, et une seule
    convention odd-q existe. La version vectorisée VIT ICI, avec la géométrie, parce qu'elle
    en était à sa troisième copie (le tracé de LoS batch, `ActionDecoder._offset_to_cube_vec`)
    dont une seule était sous test d'équivalence.
    """
    x = cols
    z = rows - ((cols - (cols & 1)) >> 1)
    return x, -x - z, z


def cube_to_offset(x: int, y: int, z: int) -> Tuple[int, int]:
    """Convert cube (x, y, z) to offset odd-q (col, row)."""
    col = x
    row = z + ((x - (x & 1)) >> 1)
    return col, row


# ---------------------------------------------------------------------------
# Distance (§2.2 P2)
# ---------------------------------------------------------------------------

def hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
    """Hex distance between two offset odd-q positions (straight line, no walls).

    Uses cube coordinates: distance = max(|dx|, |dy|, |dz|).
    """
    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)
    return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


# Seuil |A|x|B| sous lequel `min_distance_between_sets` balaye directement les paires au lieu
# de calculer la borne par boite englobante puis de trier. Cf. le commentaire dans la fonction.
_SMALL_SET_PRODUCT = 36


def min_distance_between_sets(
    set_a: AbstractSet[Tuple[int, int]], set_b: AbstractSet[Tuple[int, int]],
    max_distance: int = 0,
) -> int:
    """Minimum hex distance between any cell in set_a and any cell in set_b (§3.3).

    Used for distance between unit footprints (occupied_hexes).
    Returns 0 if sets overlap. Raises ValueError if either set is empty.

    Args:
        max_distance: If > 0, the result is only guaranteed exact while it is
            <= max_distance. When the sets are farther apart, a value strictly
            greater than max_distance is returned (a cube bounding-box lower
            bound, not necessarily max_distance + 1) — sufficient for the
            threshold tests (<= / >) every caller performs. With max_distance == 0
            the exact distance is always returned.

    Computes a cube bounding-box lower bound in O(|A|+|B|); if that already
    exceeds max_distance the bound is returned without pairwise work. Otherwise
    the cells of A are scanned nearest-first (by cube distance to B's bounding-box
    centre) against B with early-exit, avoiding the O(|A|*|B|) worst case on large
    overlapping footprints (base_size=18 ≈ 211 hexes, base_size=35 ≈ 1113 hexes).
    """
    if not set_a or not set_b:
        raise ValueError("Cannot compute distance between empty sets")
    if set_a & set_b:
        return 0

    # Chemin rapide petits ensembles — mesure sur un episode d'entrainement x1 : 70 % des appels
    # sont 1x1 et le produit |A|x|B| moyen vaut 8. Sous ce seuil, le balayage direct coute moins
    # que la borne par boite englobante + le tri de `cubes_a` qui la precedent. Resultat EXACT,
    # donc conforme au contrat `max_distance` (qui n'autorise l'approximation que par exces).
    if len(set_a) * len(set_b) <= _SMALL_SET_PRODUCT:
        cubes_b_small = [offset_to_cube(c, r) for c, r in set_b]
        best_small = _UNREACHABLE
        for c, r in set_a:
            x1, y1, z1 = offset_to_cube(c, r)
            for x2, y2, z2 in cubes_b_small:
                d = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
                if d < best_small:
                    if d <= 1:
                        return d
                    best_small = d
        return best_small

    cubes_a = [offset_to_cube(c, r) for c, r in set_a]
    cubes_b = [offset_to_cube(c, r) for c, r in set_b]
    bxs = [c[0] for c in cubes_b]
    bys = [c[1] for c in cubes_b]
    bzs = [c[2] for c in cubes_b]
    bxmin, bxmax = min(bxs), max(bxs)
    bymin, bymax = min(bys), max(bys)
    bzmin, bzmax = min(bzs), max(bzs)
    axs = [c[0] for c in cubes_a]
    ays = [c[1] for c in cubes_a]
    azs = [c[2] for c in cubes_a]

    def _axis_gap(lo1: int, hi1: int, lo2: int, hi2: int) -> int:
        if hi1 < lo2:
            return lo2 - hi1
        if hi2 < lo1:
            return lo1 - hi2
        return 0

    lower = max(
        _axis_gap(min(axs), max(axs), bxmin, bxmax),
        _axis_gap(min(ays), max(ays), bymin, bymax),
        _axis_gap(min(azs), max(azs), bzmin, bzmax),
    )
    if max_distance > 0 and lower > max_distance:
        return lower

    # Scan A nearest-first so a near-optimal `best` appears early, then early-exit
    # as soon as `best` cannot be beaten (best <= 1, or best already hits `lower`).
    cbx = (bxmin + bxmax) / 2.0
    cby = (bymin + bymax) / 2.0
    cbz = (bzmin + bzmax) / 2.0
    cubes_a.sort(key=lambda p: max(abs(p[0] - cbx), abs(p[1] - cby), abs(p[2] - cbz)))

    best = _UNREACHABLE
    for x1, y1, z1 in cubes_a:
        for x2, y2, z2 in cubes_b:
            d = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
            if d < best:
                best = d
                if best <= 1 or best == lower:
                    return best
    return best


def dilate_hex_set_unbounded(
    fp: Set[Tuple[int, int]],
    radius: int,
) -> Set[Tuple[int, int]]:
    """All hexes on the infinite odd-q grid within ``radius`` steps of ``fp`` (inclusive).

    Uses the 6-neighbor odd-q expansion (multi-source unbounded BFS). Consistent
    with the cube hex metric of ``min_distance_between_sets``: for disjoint
    non-empty footprints A and B, ``min_distance_between_sets(A, B) <= radius``
    iff ``A & dilate_hex_set_unbounded(B, radius)`` is non-empty (and same symmetrically).

    Args:
        fp: Non-empty set of (col, row) cells; empty input returns empty set.
        radius: Number of expansion layers (must be >= 0).

    Raises:
        ValueError: if ``radius`` is negative.
    """
    if radius < 0:
        raise ValueError("radius must be non-negative")
    if not fp:
        return set()
    result: Set[Tuple[int, int]] = set(fp)
    frontier = list(fp)
    for _ in range(radius):
        next_frontier: List[Tuple[int, int]] = []
        for c, r in frontier:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                npos = (nc, nr)
                if npos not in result:
                    result.add(npos)
                    next_frontier.append(npos)
        frontier = next_frontier
        if not frontier:
            break
    return result


# ---------------------------------------------------------------------------
# Bounds checking
# ---------------------------------------------------------------------------

def is_in_bounds(col: int, row: int, cols: int, rows: int) -> bool:
    """Check if (col, row) is within [0, cols) × [0, rows)."""
    return 0 <= col < cols and 0 <= row < rows


def is_phantom_bottom_hex(col: int, row: int, rows: int) -> bool:
    """Vrai si (col, row) est une demi-case fantôme du bord bas du plateau.

    En offset odd-q (§2.2), les colonnes impaires sont décalées d'une demi-ligne vers
    le bas : leur dernière case déborde sous le bord du plateau et n'existe donc pas.
    Elle est dans les bornes de `is_in_bounds` mais n'est pas jouable.

    Prédicat O(1) sans allocation : à privilégier dans les chemins chauds.
    Pour l'ensemble complet — à unir aux murs — voir `phantom_bottom_hexes`.
    """
    return row == rows - 1 and col % 2 == 1


@lru_cache(maxsize=8)
def phantom_bottom_hexes(cols: int, rows: int) -> FrozenSet[Tuple[int, int]]:
    """Ensemble des demi-cases fantômes du bord bas (cf. `is_phantom_bottom_hex`).

    SOURCE UNIQUE : tout code qui construit ou reconstruit `game_state["wall_hexes"]`
    doit unir cet ensemble aux murs du scénario, sinon les figurines peuvent être
    déployées sur des cases inexistantes et les tirs les traversent.

    Mémoïsé et immuable : l'analyzer le réunit aux murs à CHAQUE contrôle de LoS
    (une fois par tir de chaque ligne du step.log), le plateau ne changeant jamais
    de taille en cours de run.
    """
    return frozenset(
        (col, rows - 1) for col in range(cols) if is_phantom_bottom_hex(col, rows - 1, rows)
    )


# ---------------------------------------------------------------------------
# Coordinate normalization (moved from combat_utils — kept for compat)
# ---------------------------------------------------------------------------

def normalize_coordinate(coord: Any) -> int:
    """Normalize a single coordinate to int.

    Raises ValueError/TypeError on invalid input.
    """
    if isinstance(coord, int):
        return coord
    if isinstance(coord, float):
        return int(coord)
    if isinstance(coord, str):
        try:
            return int(float(coord))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid coordinate string '{coord}': {e}") from e
    raise TypeError(
        f"Invalid coordinate type {type(coord).__name__}: {coord}. "
        "Expected int, float, or numeric string."
    )


def normalize_coordinates(col: Any, row: Any) -> Tuple[int, int]:
    """Normalize (col, row) to (int, int)."""
    return normalize_coordinate(col), normalize_coordinate(row)


# ---------------------------------------------------------------------------
# Hex line (grid traversal / supercover) — for LoS rays (§7.3)
# ---------------------------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def hex_line_iter(
    col1: int, row1: int, col2: int, row2: int
) -> Iterator[Tuple[int, int]]:
    """Yield hex cells along the line from (col1,row1) to (col2,row2), lazily.

    Corps historique de :func:`hex_line`, transformé en générateur : les appelants qui s'arrêtent au
    premier hex bloquant (LoS) ne paient plus la construction de la ligne entière — mesuré : 52 % des
    cellules construites n'étaient jamais examinées. Séquence, ordre et déduplication IDENTIQUES à
    :func:`hex_line`, qui n'est plus qu'un ``list()`` de ce générateur (source de vérité unique).

    **Biais de départage des égalités exactes (invariant à ne pas corriger)**

    Les coordonnées cube de départ sont décalées de ``(+1e-6, +1e-6, -2e-6)`` et celles d'arrivée
    identiquement, de sorte que la somme reste nulle (contrainte cube x+y+z=0 conservée). Ce nudge
    constant rompt les égalités *dz == dy* qui surviennent sur les **segments horizontaux** (row
    constant) : sur ces lignes, les colonnes de parité alternante atterrissent systématiquement sur la
    rangée ``row`` ou ``row - 1`` selon la parité de la colonne.

    Conséquence pour les auteurs de terrain : un mur déclaré sur ``row = R`` bloque la LoS sur
    ``row = R - 1`` pour les colonnes de parité opposée à l'extrémité. En pratique, la ligne
    bloquante effective se situe **une demi-case au-dessus** de la ligne telle qu'écrite.

    Exemple vérifié : ``[[132,123],[126,123]]`` et ``[[88,123],[108,123]]`` rasterisent en rangées
    alternant entre 123 et 122 selon la parité de colonne, dans les deux sens de parcours.

    Ce biais est **partagé bit-à-bit** par :func:`hex_line_iter_t` (LoS 3D plancher-occulteur) et
    par la version vectorisée ``batch_hex_line_steps`` : ne jamais modifier le nudge sans propager la
    modification aux deux miroirs ET re-valider que les résultats restent identiques.
    """
    if col1 == col2 and row1 == row2:
        yield (col1, row1)
        return

    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)

    n = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
    seen: Set[Tuple[int, int]] = set()

    # Chemin chaud (~1,6 M d'itérations par preview de tir) : ``_lerp`` et ``cube_to_offset`` sont
    # inlinés et les bornes hissées hors boucle. L'EXPRESSION reste `a + (b - a) * t` avec
    # `t = i / n` recalculé à chaque point — surtout pas une accumulation incrémentale, dont la
    # dérive flottante changerait le départage des lignes rasantes, donc le couvert (rule 13.06).
    ax = x1 + 1e-6
    ay = y1 + 1e-6
    az = z1 - 2e-6
    bx = (x2 + 1e-6) - ax
    by = (y2 + 1e-6) - ay
    bz = (z2 - 2e-6) - az

    for i in range(n + 1):
        t = i / n if n > 0 else 0.0
        fx = ax + bx * t
        fy = ay + by * t
        fz = az + bz * t

        rx = round(fx)
        ry = round(fy)
        rz = round(fz)

        dx = rx - fx
        if dx < 0.0:
            dx = -dx
        dy = ry - fy
        if dy < 0.0:
            dy = -dy
        dz = rz - fz
        if dz < 0.0:
            dz = -dz
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy > dz:
            ry = -rx - rz
        else:
            rz = -rx - ry

        cell = (rx, rz + ((rx - (rx & 1)) >> 1))
        if cell not in seen:
            seen.add(cell)
            yield cell


def hex_line_iter_t(
    col1: int, row1: int, col2: int, row2: int
) -> Iterator[Tuple[Tuple[int, int], float]]:
    """Comme :func:`hex_line_iter`, mais yield ``(cell, t)`` avec ``t = i / n`` la position
    paramétrique de la cellule le long du tracé (0.0 au départ, 1.0 à l'arrivée).

    MIROIR EXACT de :func:`hex_line_iter` : même nudge de départage, même cube-lerp
    ``a + (b - a) * t`` recalculé à chaque point, même déduplication, même séquence. Sert la LoS 3D
    plancher-occulteur (interpolation de hauteur ``h(t)``) sans alourdir le chemin chaud 2D de
    :func:`hex_line_iter`. La duplication du corps est VOULUE : garder les deux boucles
    byte-identiques est plus sûr qu'une factorisation qui ralentirait le hot path 2D.
    """
    if col1 == col2 and row1 == row2:
        yield (col1, row1), 0.0
        return

    x1, y1, z1 = offset_to_cube(col1, row1)
    x2, y2, z2 = offset_to_cube(col2, row2)

    n = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
    seen: Set[Tuple[int, int]] = set()

    ax = x1 + 1e-6
    ay = y1 + 1e-6
    az = z1 - 2e-6
    bx = (x2 + 1e-6) - ax
    by = (y2 + 1e-6) - ay
    bz = (z2 - 2e-6) - az

    for i in range(n + 1):
        t = i / n if n > 0 else 0.0
        fx = ax + bx * t
        fy = ay + by * t
        fz = az + bz * t

        rx = round(fx)
        ry = round(fy)
        rz = round(fz)

        dx = rx - fx
        if dx < 0.0:
            dx = -dx
        dy = ry - fy
        if dy < 0.0:
            dy = -dy
        dz = rz - fz
        if dz < 0.0:
            dz = -dz
        if dx > dy and dx > dz:
            rx = -ry - rz
        elif dy > dz:
            ry = -rx - rz
        else:
            rz = -rx - ry

        cell = (rx, rz + ((rx - (rx & 1)) >> 1))
        if cell not in seen:
            seen.add(cell)
            yield cell, t


def hex_line(
    col1: int, row1: int, col2: int, row2: int
) -> List[Tuple[int, int]]:
    """Return hex cells along the line from (col1,row1) to (col2,row2).

    Uses cube-space linear interpolation then rounds to nearest hex.
    Includes both endpoints. Order: from start to end.
    """
    return list(hex_line_iter(col1, row1, col2, row2))


# ── PIERRE TOMBALE — `batch_has_los_from_source` (2026-08-03) ────────────────────────────
# Traçait les mêmes lignes que `hex_line_iter` mais ne testait QUE une grille de murs 2D : ni
# obscuring (13.10), ni plancher-occulteur 3D. C'était le SECOND modèle de ligne de vue du
# moteur, celui qui divergeait de `compute_unit_los` sur 607 hexes (V11 §0.64). §0.64 lui a
# retiré son dernier appelant — le scoring de déploiement — sans le supprimer.
# Il part ici, en même temps qu'arrive `batch_hex_line_steps` : garder à côté d'un tracé
# vectorisé CONFORME un tracé vectorisé FAUX, c'est offrir à quelqu'un de rebrancher le mauvais.
# La géométrie reste ici, la RÈGLE de blocage vit dans `shooting_handlers` — c'est la
# séparation qui empêche un 3e modèle de naître.
# ─────────────────────────────────────────────────────────────────────────────────────────


def batch_hex_line_steps(
    from_col: int,
    from_row: int,
    to_arr: np.ndarray,
    alive: np.ndarray,
) -> "Iterator[Tuple[np.ndarray, np.ndarray, np.ndarray]]":
    """JUMEAU VECTORISÉ de :func:`hex_line_iter` — une source, N cibles, en même temps.

    Yield, pour chaque rang ``i`` de cellule INTERMÉDIAIRE (``1 <= i < n_j``),
    ``(idx, c_off, r_off)`` : les indices des cibles encore vivantes à ce rang et la cellule
    que leur ligne traverse. Les extrémités ne sont jamais rendues — ni la cellule source
    (jamais bloquante), ni la cellule cible (elle PORTE la cible) : exactement les cellules que
    :func:`_los_line_segment_clear` examine.

    ``alive`` (bool, shape (N,)) est lu à CHAQUE rang : l'appelant y met ``False`` les cibles
    qu'il vient de déclarer bloquées, et leurs rangs suivants ne sont plus calculés. C'est le
    pendant vectoriel de l'arrêt au premier bloqueur du générateur scalaire (mesuré : 68 % des
    lignes sont bloquées, la moitié des cellules ne sert à rien).

    IDENTITÉ AVEC LE CHEMIN SCALAIRE — ce qu'il faut savoir avant d'y toucher :
    - même nudge de départage (``+1e-6``, ``-2e-6``), même expression ``a + (b - a) * t`` avec
      ``t = i / n`` RECALCULÉ à chaque rang. Surtout pas une accumulation incrémentale : la
      dérive flottante changerait le départage des lignes rasantes, donc le couvert (13.06).
      numpy calcule en float64, comme Python : les deux suites sont bit-à-bit les mêmes.
    - ``np.round`` et ``round`` arrondissent tous deux au pair le plus proche (round-half-even).
    - la déduplication du générateur scalaire (``seen``) n'a pas d'équivalent ici, et n'en a pas
      besoin : la i-ème cellule d'un cube-lerp est à distance cube ``i`` de la source, donc les
      ``n+1`` cellules sont deux à deux distinctes et ``seen`` ne retire jamais rien. Cette
      propriété n'est pas une supposition : elle est vérifiée par test sur un échantillon de
      paires (``test_deployment_los_vectorized_equivalence``), en même temps que l'égalité
      hexe par hexe des deux chemins.
    """
    n_targets = len(to_arr)
    if n_targets == 0:
        return
    if alive.shape != (n_targets,):
        raise ValueError(
            f"batch_hex_line_steps: alive de forme {alive.shape}, attendu ({n_targets},)"
        )

    to_cols = to_arr[:, 0].astype(np.int64)
    to_rows = to_arr[:, 1].astype(np.int64)

    # offset_to_cube, source puis cibles — la MÊME conversion des deux côtés, scalaire ici,
    # vectorisée là, prises toutes deux à leur source unique.
    x1, y1, z1 = offset_to_cube(from_col, from_row)
    x2, y2, z2 = offset_to_cube_vec(to_cols, to_rows)

    n_arr = np.maximum(np.maximum(np.abs(x2 - x1), np.abs(y2 - y1)), np.abs(z2 - z1))
    max_n = int(n_arr.max())
    if max_n <= 1:
        return  # 0 ou 1 pas : aucune cellule intermédiaire

    fx1 = float(x1) + 1e-6
    fy1 = float(y1) + 1e-6
    fz1 = float(z1) - 2e-6
    fx2 = x2.astype(np.float64) + 1e-6
    fy2 = y2.astype(np.float64) + 1e-6
    fz2 = z2.astype(np.float64) - 2e-6

    for i in range(1, max_n):
        active = alive & (n_arr > i)
        if not active.any():
            return
        idx = np.flatnonzero(active)
        t = float(i) / n_arr[idx].astype(np.float64)

        fx = fx1 + (fx2[idx] - fx1) * t
        fy = fy1 + (fy2[idx] - fy1) * t
        fz = fz1 + (fz2[idx] - fz1) * t

        rx = np.round(fx).astype(np.int64)
        ry = np.round(fy).astype(np.int64)
        rz = np.round(fz).astype(np.int64)

        dx = np.abs(rx.astype(np.float64) - fx)
        dy = np.abs(ry.astype(np.float64) - fy)
        dz = np.abs(rz.astype(np.float64) - fz)

        # Départage : on recalcule la coordonnée dont l'arrondi a le plus dérivé. Le scalaire
        # teste `dx > dy and dx > dz`, sinon `dy > dz`, sinon la branche z ; ici les deux
        # masques utiles sont exclusifs, donc chaque formule lit les rx/ry/rz d'ORIGINE.
        # La branche `y` n'a pas de masque : `ry_f` ne sert à personne (`cube_to_offset` ne lit
        # que x et z, et cette branche laisse justement x et z intacts), donc `mask_z` s'écrit
        # directement — `(~mask_x) & ~(dy > dz)` est `(~mask_x) & (dy <= dz)`.
        mask_x = (dx > dy) & (dx > dz)
        mask_z = (~mask_x) & (dy <= dz)
        rx_f = np.where(mask_x, -ry - rz, rx)
        rz_f = np.where(mask_z, -rx - ry, rz)

        # cube_to_offset : col = x, row = z + ((x - (x & 1)) >> 1)
        yield idx, rx_f, rz_f + ((rx_f - (rx_f & 1)) >> 1)


def expand_wall_group_to_hex_list(
    group: Dict[str, Any],
    *,
    path_hint: str = "wall group",
) -> List[List[int]]:
    """Expand one wall JSON object into a list of [col, row] (deduplicated, order preserved).

    Supported keys:
    - ``hexes``: optional list of ``[col, row]`` (explicit blocked cells).
    - ``segments``: optional list of segments ``[[c1, r1], [c2, r2]]``; each segment is
      expanded with :func:`hex_line` (offset odd-q), endpoints included.

    At least one of ``hexes`` or ``segments`` must be non-empty after parsing.
    """
    if "hexes" in group and group["hexes"] is not None:
        hexes_raw = group["hexes"]
        if not isinstance(hexes_raw, list):
            raise ValueError(f"{path_hint}: 'hexes' must be a list")
    else:
        hexes_raw = []

    if "segments" in group and group["segments"] is not None:
        segments_raw = group["segments"]
        if not isinstance(segments_raw, list):
            raise ValueError(f"{path_hint}: 'segments' must be a list")
    else:
        segments_raw = []

    if len(hexes_raw) == 0 and len(segments_raw) == 0:
        raise ValueError(
            f"{path_hint}: wall group must define non-empty 'hexes' and/or 'segments'"
        )

    seen: Set[Tuple[int, int]] = set()
    out: List[List[int]] = []

    def _add_cell(c: int, r: int) -> None:
        t = (c, r)
        if t not in seen:
            seen.add(t)
            out.append([c, r])

    for h in hexes_raw:
        if not isinstance(h, (list, tuple)) or len(h) < 2:
            raise ValueError(f"{path_hint}: invalid wall hex {h!r}")
        _add_cell(int(h[0]), int(h[1]))

    for seg_i, seg in enumerate(segments_raw):
        if not isinstance(seg, list) or len(seg) != 2:
            raise ValueError(
                f"{path_hint}: segment {seg_i} must be [[c1,r1],[c2,r2]], got {seg!r}"
            )
        a, b = seg[0], seg[1]
        if (
            not isinstance(a, (list, tuple))
            or not isinstance(b, (list, tuple))
            or len(a) < 2
            or len(b) < 2
        ):
            raise ValueError(f"{path_hint}: segment {seg_i} has invalid endpoints {seg!r}")
        c1, r1 = int(a[0]), int(a[1])
        c2, r2 = int(b[0]), int(b[1])
        for c, r in hex_line(c1, r1, c2, r2):
            _add_cell(c, r)

    return out


def _hex_projected(c: int, r: int) -> tuple:
    hex_horiz_spacing = 1.5
    hex_vert_spacing = math.sqrt(3.0)
    hx = c * hex_horiz_spacing
    hy = r * hex_vert_spacing + ((c % 2) * hex_vert_spacing) / 2.0
    return hx, hy


def downscale_cell(col: int, row: int, ratio: int) -> Tuple[int, int]:
    """Cellule du plateau `ratio` fois plus grossier qui contient la cellule fine `(col, row)`.

    Diviser col et row séparément est FAUX en odd-q : les colonnes impaires sont décalées d'une
    demi-hauteur d'hex (`_hex_projected`), donc une division par axe ignore ce décalage et
    déplace environ un point sur quatre d'une case (mesuré sur `terrain-mc1`).

    Conversion exacte : centre projeté de la cellule fine → mise à l'échelle → cellule grossière
    dont le centre projeté est le plus proche. On s'appuie sur `_hex_projected`, la projection
    déjà utilisée par la rasterisation des polygones et par le rendu du plateau, donc la
    conversion est cohérente avec la géométrie du reste du moteur.

    La recherche balaie ±2 autour de l'estimation analytique : l'estimation est exacte à ±1 près
    (les colonnes le sont exactement, les lignes à un demi-pas près), la marge couvre le reste.
    """
    if ratio <= 0:
        raise ValueError(f"downscale_cell: ratio must be >= 1, got {ratio}")
    if ratio == 1:
        return int(col), int(row)
    x, y = _hex_projected(int(col), int(row))
    x /= ratio
    y /= ratio
    col_estimate = int(round(x / 1.5))
    row_estimate = int(round(y / math.sqrt(3.0)))
    best: Optional[Tuple[int, int]] = None
    best_distance = math.inf
    for candidate_col in range(col_estimate - 2, col_estimate + 3):
        for candidate_row in range(row_estimate - 2, row_estimate + 3):
            hx, hy = _hex_projected(candidate_col, candidate_row)
            distance = (hx - x) ** 2 + (hy - y) ** 2
            if distance < best_distance:
                best, best_distance = (candidate_col, candidate_row), distance
    if best is None:
        raise RuntimeError(f"downscale_cell: aucune cellule candidate pour ({col},{row}) ratio {ratio}")
    return best


def _objective_rect_hexes(
    *,
    top_left: Sequence,
    bottom_right: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    px_min, py_min = _hex_projected(int(top_left[0]), int(top_left[1]))
    px_max, py_max = _hex_projected(int(bottom_right[0]), int(bottom_right[1]))
    if px_min > px_max:
        px_min, px_max = px_max, px_min
    if py_min > py_max:
        py_min, py_max = py_max, py_min

    c1 = max(0, min(int(top_left[0]), int(bottom_right[0])))
    c2 = min(cols - 1, max(int(top_left[0]), int(bottom_right[0])))
    r1 = max(0, min(int(top_left[1]), int(bottom_right[1])))
    r2 = min(rows - 1, max(int(top_left[1]), int(bottom_right[1])))

    out: List[List[int]] = []
    for c in range(c1, c2 + 1):
        for r in range(r1, r2 + 1):
            hx, hy = _hex_projected(c, r)
            if px_min <= hx <= px_max and py_min <= hy <= py_max:
                out.append([c, r])
    return out


def _objective_triangle_hexes(
    *,
    vertices: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    (ax, ay) = _hex_projected(int(vertices[0][0]), int(vertices[0][1]))
    (bx, by) = _hex_projected(int(vertices[1][0]), int(vertices[1][1]))
    (cx, cy) = _hex_projected(int(vertices[2][0]), int(vertices[2][1]))

    col_min = max(0, min(int(v[0]) for v in vertices) - 1)
    col_max = min(cols - 1, max(int(v[0]) for v in vertices) + 1)
    row_min = max(0, min(int(v[1]) for v in vertices) - 1)
    row_max = min(rows - 1, max(int(v[1]) for v in vertices) + 1)

    def _sign(px, py, x1, y1, x2, y2) -> float:
        return (px - x2) * (y1 - y2) - (x1 - x2) * (py - y2)

    out: List[List[int]] = []
    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            px, py = _hex_projected(c, r)
            d1 = _sign(px, py, ax, ay, bx, by)
            d2 = _sign(px, py, bx, by, cx, cy)
            d3 = _sign(px, py, cx, cy, ax, ay)
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            if not (has_neg and has_pos):
                out.append([c, r])
    return out


def _objective_polygon_hexes(
    *,
    vertices: Sequence,
    cols: int,
    rows: int,
) -> List[List[int]]:
    """Generate hexes inside an arbitrary polygon (3+ vertices) via ray-casting.

    Uses the same odd-q projection as rect/triangle so tilted (rotated)
    footprints are captured exactly from their corner coordinates.
    """
    pts = [_hex_projected(int(v[0]), int(v[1])) for v in vertices]
    n = len(pts)
    col_min = max(0, min(int(v[0]) for v in vertices) - 1)
    col_max = min(cols - 1, max(int(v[0]) for v in vertices) + 1)
    row_min = max(0, min(int(v[1]) for v in vertices) - 1)
    row_max = min(rows - 1, max(int(v[1]) for v in vertices) + 1)

    def _inside(px: float, py: float) -> bool:
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > py) != (yj > py)) and (
                px < (xj - xi) * (py - yi) / (yj - yi) + xi
            ):
                inside = not inside
            j = i
        return inside

    out: List[List[int]] = []
    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            px, py = _hex_projected(c, r)
            if _inside(px, py):
                out.append([c, r])
    return out


def polygon_to_hex_list(vertices: list, cols: int, rows: int) -> List[List[int]]:
    """Rasterize an arbitrary polygon (3+ [col, row] vertices) to the list of board hexes
    whose centers fall inside it, using the same odd-q projection as objectives/terrain rendering.

    Public wrapper around the objective polygon rasterizer so terrain areas share the exact
    same hex membership semantics as objective zones and the frontend board renderer.
    """
    if not isinstance(vertices, (list, tuple)) or len(vertices) < 3:
        raise ValueError(f"polygon_to_hex_list: need >= 3 vertices, got {vertices!r}")
    return _objective_polygon_hexes(vertices=vertices, cols=cols, rows=rows)


def _objective_disc_hexes(
    *,
    center_col: int,
    center_row: int,
    diameter: int,
    cols: int,
    rows: int,
) -> List[List[int]]:
    """Generate objective hexes for a Euclidean disc in odd-q projection.

    Uses the same geometric projection as the frontend board renderer:
    - HEX_HORIZ_SPACING = 1.5
    - HEX_VERT_SPACING = sqrt(3)
    - odd columns shifted by HEX_VERT_SPACING / 2
    """
    if diameter <= 0:
        raise ValueError(f"objective disc diameter must be > 0, got {diameter}")

    hex_horiz_spacing = 1.5
    hex_vert_spacing = math.sqrt(3.0)

    cx = center_col * hex_horiz_spacing
    cy = center_row * hex_vert_spacing + ((center_col % 2) * hex_vert_spacing) / 2.0
    radius_cols = diameter / 2.0
    radius_px = radius_cols * hex_horiz_spacing
    radius_sq = radius_px * radius_px

    scan_cols = int(math.ceil(radius_cols)) + 2
    scan_rows = int(math.ceil(radius_px / hex_vert_spacing)) + 3

    out: List[List[int]] = []
    col_min = max(0, center_col - scan_cols)
    col_max = min(cols - 1, center_col + scan_cols)
    row_min = max(0, center_row - scan_rows)
    row_max = min(rows - 1, center_row + scan_rows)

    for c in range(col_min, col_max + 1):
        for r in range(row_min, row_max + 1):
            hx = c * hex_horiz_spacing
            hy = r * hex_vert_spacing + ((c % 2) * hex_vert_spacing) / 2.0
            dist_sq = (hx - cx) ** 2 + (hy - cy) ** 2
            if dist_sq <= radius_sq:
                out.append([c, r])
    return out


def _objective_line_hexes(
    p1: Sequence[int],
    p2: Sequence[int],
    cols: int,
    rows: int,
) -> List[List[int]]:
    return [
        list(hx) for hx in hex_line(int(p1[0]), int(p1[1]), int(p2[0]), int(p2[1]))
        if 0 <= hx[0] < cols and 0 <= hx[1] < rows
    ]


def expand_objectives_to_hex_list(
    objectives_raw: Any,
    *,
    cols: int,
    rows: int,
    path_hint: str = "objectives",
) -> List[Dict[str, Any]]:
    """Expand objective definitions to explicit `hexes`.

    Supported objective formats:
    - Explicit:  {"id": ..., "name": ..., "hexes": [[c, r], ...]}
    - Disc:      {"id": ..., "name": ..., "shape": "disc", "center": [c, r], "diameter": N}
    - Rectangle: {"id": ..., "name": ..., "shape": "rect", "top_left": [c, r], "bottom_right": [c, r]}
    - Triangle:  {"id": ..., "name": ..., "shape": "triangle", "vertices": [[c,r],[c,r],[c,r]]}
    """
    if not isinstance(objectives_raw, list):
        raise ValueError(f"{path_hint}: objectives must be a list")

    expanded: List[Dict[str, Any]] = []
    for idx, objective in enumerate(objectives_raw):
        if not isinstance(objective, dict):
            raise ValueError(f"{path_hint}: objective[{idx}] must be an object")

        if "id" not in objective:
            raise ValueError(f"{path_hint}: objective[{idx}] missing required 'id'")
        has_hexes = "hexes" in objective and objective["hexes"] is not None
        has_shape = "shape" in objective and objective["shape"] is not None
        if has_hexes and has_shape:
            raise ValueError(
                f"{path_hint}: objective[{idx}] cannot define both 'hexes' and 'shape'"
            )

        objective_out = dict(objective)

        if has_hexes:
            hexes_raw = objective["hexes"]
            if not isinstance(hexes_raw, list):
                raise ValueError(f"{path_hint}: objective[{idx}] field 'hexes' must be a list")
            hexes_out: List[List[int]] = []
            for hi, h in enumerate(hexes_raw):
                if not isinstance(h, (list, tuple)) or len(h) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] invalid hex at index {hi}: {h!r}"
                    )
                hexes_out.append([int(h[0]), int(h[1])])
            objective_out["hexes"] = hexes_out
            expanded.append(objective_out)
            continue

        if not has_shape:
            raise ValueError(
                f"{path_hint}: objective[{idx}] must define either 'hexes' or 'shape'"
            )

        shape = objective["shape"]
        if shape == "disc":
            center = objective.get("center")
            if not isinstance(center, (list, tuple)) or len(center) < 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'center' must be [col, row]"
                )
            diameter_raw = objective.get("diameter")
            if not isinstance(diameter_raw, int):
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'diameter' must be an int"
                )
            center_col = int(center[0])
            center_row = int(center[1])
            if center_col < 0 or center_col >= cols or center_row < 0 or center_row >= rows:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] center {(center_col, center_row)} out of bounds "
                    f"for board {cols}x{rows}"
                )
            objective_out["hexes"] = _objective_disc_hexes(
                center_col=center_col,
                center_row=center_row,
                diameter=diameter_raw,
                cols=cols,
                rows=rows,
            )
        elif shape == "rect":
            top_left = objective.get("top_left")
            bottom_right = objective.get("bottom_right")
            if not isinstance(top_left, (list, tuple)) or len(top_left) < 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'top_left' must be [col, row]"
                )
            if not isinstance(bottom_right, (list, tuple)) or len(bottom_right) < 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'bottom_right' must be [col, row]"
                )
            objective_out["hexes"] = _objective_rect_hexes(
                top_left=top_left,
                bottom_right=bottom_right,
                cols=cols,
                rows=rows,
            )
        elif shape == "triangle":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) != 3:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of 3 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_triangle_hexes(
                vertices=vertices,
                cols=cols,
                rows=rows,
            )
        elif shape == "line":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) != 2:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of 2 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_line_hexes(
                p1=vertices[0],
                p2=vertices[1],
                cols=cols,
                rows=rows,
            )
        elif shape == "polygon":
            vertices = objective.get("vertices")
            if not isinstance(vertices, (list, tuple)) or len(vertices) < 3:
                raise ValueError(
                    f"{path_hint}: objective[{idx}] field 'vertices' must be a list of >= 3 [col, row]"
                )
            for vi, v in enumerate(vertices):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    raise ValueError(
                        f"{path_hint}: objective[{idx}] vertices[{vi}] must be [col, row]"
                    )
            objective_out["hexes"] = _objective_polygon_hexes(
                vertices=vertices,
                cols=cols,
                rows=rows,
            )
        else:
            raise ValueError(
                f"{path_hint}: objective[{idx}] unsupported shape {shape!r} (expected 'disc', 'rect', 'triangle', or 'polygon')"
            )
        expanded.append(objective_out)

    return expanded


# ---------------------------------------------------------------------------
# LoS — on-demand computation (§7.1, §7.2, §7.3)
# ---------------------------------------------------------------------------

_UNREACHABLE = 999_999


def compute_los_visibility(
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    wall_set: Set[Tuple[int, int]],
) -> float:
    """Compute LoS visibility ratio between two single hexes.

    Traces a hex line from (from_col, from_row) to (to_col, to_row).
    Returns 1.0 if no wall blocks the line, 0.0 if any intermediate
    cell is a wall.

    Pour une unité multi-hex, l'appelant doit utiliser
    compute_los_visibility_footprint (§7.2).
    """
    if from_col == to_col and from_row == to_row:
        return 1.0

    line = hex_line(from_col, from_row, to_col, to_row)
    for c, r in line[1:-1]:
        if (c, r) in wall_set:
            return 0.0
    return 1.0


def compute_los_state(
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    wall_set: Set[Tuple[int, int]],
) -> Tuple[float, bool]:
    """Compute (visibility_ratio, can_see) for a single-hex pair.

    Primitive partagée par _get_los_visibility_state (shooting_handlers)
    et _has_los_on_demand (observation_builder).

    Binary visibility (rule 06.01): can_see = ratio > 0 (no threshold).

    Args:
        from_col, from_row: Shooter position.
        to_col, to_row: Target position.
        wall_set: Set of (col, row) wall hexes.

    Returns:
        (visibility_ratio, can_see)
    """
    v = compute_los_visibility(from_col, from_row, to_col, to_row, wall_set)
    return v, v > 0.0


# ---------------------------------------------------------------------------
# Engagement zone — hex set dilation (§9.0, §8.5)
# ---------------------------------------------------------------------------

def dilate_hex_set(
    hexes: Set[Tuple[int, int]],
    radius: int,
    cols: int,
    rows: int,
) -> Set[Tuple[int, int]]:
    """Return all hexes within [1, radius] hex distance of any hex in the input set.

    The input hexes themselves are NOT included in the result (distance 0 excluded).
    Uses multi-source BFS for efficiency: O(output_size).

    Args:
        hexes: Source hex set (e.g. enemy occupied_hexes).
        radius: Max expansion distance (e.g. engagement_zone = 10).
        cols, rows: Board dimensions for bounds checking.

    Returns:
        Set of (col, row) within distance [1, radius] of any source hex, in bounds.
    """
    if not hexes or radius <= 0:
        return set()

    if radius == 1:
        result: Set[Tuple[int, int]] = set()
        for c, r in hexes:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                if 0 <= nc < cols and 0 <= nr < rows and (nc, nr) not in hexes:
                    result.add((nc, nr))
        return result

    visited: Set[Tuple[int, int]] = set(hexes)
    frontier = list(hexes)
    result: Set[Tuple[int, int]] = set()

    for _dist in range(radius):
        next_frontier: List[Tuple[int, int]] = []
        for c, r in frontier:
            offsets = _NEIGHBORS_ODD_COL if (c & 1) else _NEIGHBORS_EVEN_COL
            for dc, dr in offsets:
                nc, nr = c + dc, r + dr
                if nc < 0 or nr < 0 or nc >= cols or nr >= rows:
                    continue
                npos = (nc, nr)
                if npos in visited:
                    continue
                visited.add(npos)
                next_frontier.append(npos)
                result.add(npos)
        frontier = next_frontier
        if not frontier:
            break

    return result


# ---------------------------------------------------------------------------
# Footprint / occupied_hexes (§2.5, §9.1)
# ---------------------------------------------------------------------------

# Flat-top odd-q pixel embedding (same layout as frontend BoardDisplay / hexToPixel).
# Normalized with hex_radius = 1 (center to vertex):
#   hex_width  = 1.5   — horizontal distance between column centers
#   hex_height = sqrt(3) — vertical distance between row centers
# Odd columns are staggered down by hex_height / 2.
#
# Footprint diameters (round/square/oval) are expressed in hex-cell counts. The legacy
# embedding used horizontal column pitch 1.0; flat-top centers use pitch ``hex_width``.
# Scale footprint semi-axes so a given diameter still spans the same approximate number
# of cells as before.
_FOOTPRINT_SIZE_SCALE: float = 1.5

# Nombre de crans discrets d'orientation d'un socle (pivot molette). L'angle d'un cran vaut
# 2π / ORIENTATION_STEP_COUNT. DOIT rester synchronisé avec le frontend (ORIENTATION_STEP_COUNT
# dans frontend/src/constants/gameConfig.ts) — sinon empreinte moteur et socle affiché divergent.
ORIENTATION_STEP_COUNT: int = 12
_ORIENTATION_STEP_RAD: float = 2.0 * math.pi / ORIENTATION_STEP_COUNT


def _hex_center(col: int, row: int) -> Tuple[float, float]:
    """Pixel-space center of hex (col, row) in offset odd-q, flat-top layout.

    Matches ``frontend/src/utils/hexFootprint.ts`` (and ``hexToPixel`` there) up to
    ``hex_radius`` and margin. x-axis horizontal, y-axis vertical (down).
    """
    hex_radius = 1.0
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3.0) * hex_radius
    x = col * hex_width + hex_width / 2.0
    y = row * hex_height + ((col & 1) * hex_height) / 2.0 + hex_height / 2.0
    return x, y


def compute_occupied_hexes(
    center_col: int,
    center_row: int,
    base_shape: str,
    base_size: "int | Sequence[int]",
    orientation: int = 0,
) -> Set[Tuple[int, int]]:
    """Compute the set of hex cells occupied by a unit's base (§2.5).

    Args:
        center_col, center_row: Center hex of the unit.
        base_shape: "round", "oval", or "square".
        base_size: Diameter in hex for round/square; [major, minor] for oval.
        orientation: Discrete rotation step (0–5 for 60° increments).
            Only affects oval and square shapes.

    Returns:
        Set of (col, row) hex cells forming the footprint.

    Raises:
        ValueError: On unknown base_shape or invalid base_size.

    L'empreinte est une TRANSLATION pure de sa forme de référence, à parité de colonne égale :
    ``_hex_center`` est affine en (col, row) et ne dépend de la colonne que par sa parité. On
    traduit donc les offsets mémoïsés par ``precompute_footprint_offsets`` au lieu de rebalayer
    la géométrie (O(|empreinte|) au lieu d'un balayage carré avec trigonométrie par cellule).
    Mesure : 390 k appels / 51 s sur `test_move_mask_is_executable`, 41 k / 13 s sur les tests de
    déploiement. L'équivalence stricte avec le balayage est verrouillée par
    ``TestComputeOccupiedHexesMatchesRawGeometry`` (oracle = ``_compute_occupied_hexes_raw``).
    """
    offsets_even, offsets_odd = precompute_footprint_offsets(base_shape, base_size, orientation)
    offsets = offsets_odd if (int(center_col) & 1) else offsets_even
    return {(int(center_col) + dc, int(center_row) + dr) for dc, dr in offsets}


def _compute_occupied_hexes_raw(
    center_col: int,
    center_row: int,
    base_shape: str,
    base_size: "int | Sequence[int]",
    orientation: int = 0,
) -> Set[Tuple[int, int]]:
    """Balayage géométrique de l'empreinte, sans mémoïsation — SOURCE de vérité de la forme.

    Utilisé par ``precompute_footprint_offsets`` (qui en dérive les offsets, deux fois par
    (forme, taille, orientation)) et par les tests comme oracle indépendant. Le code applicatif
    passe par ``compute_occupied_hexes``.
    """
    if base_shape == "round":
        if not isinstance(base_size, (int, float)):
            raise ValueError(f"round base_size must be numeric, got {type(base_size).__name__}")
        return _footprint_round(center_col, center_row, base_size)
    elif base_shape == "oval":
        if not isinstance(base_size, (list, tuple)) or len(base_size) != 2:
            raise ValueError(f"oval base_size must be [major, minor], got {base_size}")
        return _footprint_oval(center_col, center_row, base_size[0], base_size[1], orientation)
    elif base_shape == "square":
        if not isinstance(base_size, (int, float)):
            raise ValueError(f"square base_size must be numeric, got {type(base_size).__name__}")
        return _footprint_square(center_col, center_row, base_size, orientation)
    else:
        raise ValueError(f"Unknown base_shape: {base_shape!r} (expected 'round', 'oval', or 'square')")


def compute_footprint_placement_mask(
    board_cols: int,
    board_rows: int,
    offsets_even: Tuple[Tuple[int, int], ...],
    offsets_odd: Tuple[Tuple[int, int], ...],
    obstacles: Set[Tuple[int, int]],
) -> bytearray:
    """Masque O(1) « placement invalide » par ancre (utilisé par le BFS multi-hex).

    Retourne un ``bytearray`` de taille ``board_cols * board_rows`` indexé
    ``col + row * board_cols``. Une ancre vaut ``1`` si le socle centré dessus
    **sort du plateau** ou **chevauche un obstacle** (``obstacles`` = union
    murs ∪ ennemis, ou murs ∪ toutes les occupations selon le contexte d'appel).

    Minkowski inverse : pour chaque cellule obstacle, on marque en ``1`` tous
    les ancres qui la couvriraient. Complexité ``O(|obstacles| × |offsets|)``
    + ``O(cols × rows)`` pour les bornes. Aligné sur la reconstruction décrite
    par ``precompute_footprint_offsets``.
    """
    n_cells = board_cols * board_rows
    bad = bytearray(n_cells)

    min_dc_e = min((dc for dc, _ in offsets_even), default=0)
    max_dc_e = max((dc for dc, _ in offsets_even), default=0)
    min_dr_e = min((dr for _, dr in offsets_even), default=0)
    max_dr_e = max((dr for _, dr in offsets_even), default=0)
    min_dc_o = min((dc for dc, _ in offsets_odd), default=0)
    max_dc_o = max((dc for dc, _ in offsets_odd), default=0)
    min_dr_o = min((dr for _, dr in offsets_odd), default=0)
    max_dr_o = max((dr for _, dr in offsets_odd), default=0)

    for col in range(board_cols):
        if (col & 1) == 0:
            min_dc, max_dc, min_dr, max_dr = min_dc_e, max_dc_e, min_dr_e, max_dr_e
        else:
            min_dc, max_dc, min_dr, max_dr = min_dc_o, max_dc_o, min_dr_o, max_dr_o
        col_oob = (col + min_dc < 0) or (col + max_dc >= board_cols)
        if col_oob:
            base = col
            for row in range(board_rows):
                bad[base + row * board_cols] = 1
            continue
        for row in range(board_rows):
            if (row + min_dr < 0) or (row + max_dr >= board_rows):
                bad[col + row * board_cols] = 1

    for fc, fr in obstacles:
        for dc, dr in offsets_even:
            nc = fc - dc
            if (nc & 1) != 0:
                continue
            nr = fr - dr
            if 0 <= nc < board_cols and 0 <= nr < board_rows:
                bad[nc + nr * board_cols] = 1
        for dc, dr in offsets_odd:
            nc = fc - dc
            if (nc & 1) != 1:
                continue
            nr = fr - dr
            if 0 <= nc < board_cols and 0 <= nr < board_rows:
                bad[nc + nr * board_cols] = 1

    return bad


#: Fenêtre de slice 2D, bornes demi-ouvertes ``(c_lo, c_hi, r_lo, r_hi)``.
SliceWindow = Tuple[int, int, int, int]


def offset_slice_windows(
    dc: int,
    dr: int,
    board_cols: int,
    board_rows: int,
    *,
    bbox: Optional[SliceWindow] = None,
    clamp: str = "dst",
) -> Optional[Tuple[SliceWindow, SliceWindow]]:
    """Fenêtres ``(source, destination)`` d'un décalage de grille, pour ``dst_vue op= src_vue``.

    Brique BAS NIVEAU. Les appelants du moteur passent par ``dilate_by_kernel`` /
    ``spread_by_kernel`` / ``erode_by_kernel`` juste en dessous, qui apparient pour eux le signe du
    décalage et le côté à borner — c'est cet appariement, et non le calcul des bornes, qui est
    facile à écrire de travers. N'appeler directement que pour un opérateur qu'aucune des trois ne
    couvre.

    CONVENTION, unique et explicite : ``src = dst + (dc, dr)``, c'est-à-dire
    ``out[c, r] op= src[c + dc, r + dr]`` (une DILATATION par le noyau).
    Une PROPAGATION (``out[c + dc, r + dr] op= src[c, r]``) est la même opération avec le décalage
    OPPOSÉ : l'appeler avec ``(-dc, -dr)``. C'est ce qui permet un seul calcul pour les deux sens,
    au lieu des deux jeux de bornes symétriques d'avant.

    ``bbox`` (L_bbox, §0.22) : borne la fenêtre à ``(c_lo, c_hi, r_lo, r_hi)``, l'autre côté étant
    RE-DÉRIVÉ du décalage — jamais clampé lui aussi, ce qui décalerait les deux vues l'une par
    rapport à l'autre. ``clamp`` dit de quel côté la bbox s'applique :
      - ``"dst"`` : la sortie utile est connue (dilatation bornée à la bbox du move) ;
      - ``"src"`` : les sources non nulles sont connues (union d'empreintes : les ancres valides
        sont toutes dans la bbox).
    Les deux étaient déjà en usage, chacun avec sa propre écriture ; ils sont ici le MÊME code.

    Rend ``None`` quand le décalage ne laisse aucune case commune (l'appelant passe à l'offset
    suivant) — le ``continue`` que les six copies écrivaient chacune.
    """
    if clamp not in ("dst", "src"):
        raise ValueError(f"clamp doit valoir 'dst' ou 'src', reçu {clamp!r}")
    dc, dr = int(dc), int(dr)

    # Intersection naturelle : la source doit tenir dans le plateau, la destination aussi.
    src_c_lo = max(0, dc)
    src_c_hi = board_cols - max(0, -dc)
    src_r_lo = max(0, dr)
    src_r_hi = board_rows - max(0, -dr)
    if src_c_lo >= src_c_hi or src_r_lo >= src_r_hi:
        return None
    dst_c_lo, dst_c_hi = src_c_lo - dc, src_c_hi - dc
    dst_r_lo, dst_r_hi = src_r_lo - dr, src_r_hi - dr

    if bbox is not None:
        if clamp == "dst":
            dst_c_lo = max(dst_c_lo, bbox[0])
            dst_c_hi = min(dst_c_hi, bbox[1])
            dst_r_lo = max(dst_r_lo, bbox[2])
            dst_r_hi = min(dst_r_hi, bbox[3])
            if dst_c_lo >= dst_c_hi or dst_r_lo >= dst_r_hi:
                return None
            src_c_lo, src_c_hi = dst_c_lo + dc, dst_c_hi + dc
            src_r_lo, src_r_hi = dst_r_lo + dr, dst_r_hi + dr
        else:
            src_c_lo = max(src_c_lo, bbox[0])
            src_c_hi = min(src_c_hi, bbox[1])
            src_r_lo = max(src_r_lo, bbox[2])
            src_r_hi = min(src_r_hi, bbox[3])
            if src_c_lo >= src_c_hi or src_r_lo >= src_r_hi:
                return None
            dst_c_lo, dst_c_hi = src_c_lo - dc, src_c_hi - dc
            dst_r_lo, dst_r_hi = src_r_lo - dr, src_r_hi - dr

    return (
        (src_c_lo, src_c_hi, src_r_lo, src_r_hi),
        (dst_c_lo, dst_c_hi, dst_r_lo, dst_r_hi),
    )


def _accumulate_by_kernel(
    src: "np.ndarray",
    kernel: "Any",
    board_cols: int,
    board_rows: int,
    *,
    spread: bool,
    bbox: Optional[SliceWindow],
    erode: bool,
) -> "np.ndarray":
    """Noyau commun des trois opérations de décalage ci-dessous. Ne pas appeler directement.

    Toute la géométrie tient dans les deux lignes qui suivent : le SENS décide à la fois du signe
    du décalage et du côté à borner, et ces deux choix ne sont pas indépendants. Les tenir ici est
    l'objet même de ce module — les six sites d'appel les appariaient à la main, et rien ne signalait
    un appariement croisé (offsets non niés avec un clamp de source, par exemple), qui produit un
    masque faux sans lever.
    """
    sign = -1 if spread else 1
    clamp = "src" if spread else "dst"
    out = np.ones_like(src) if erode else np.zeros_like(src)
    for dc, dr in kernel:
        windows = offset_slice_windows(
            sign * int(dc), sign * int(dr), board_cols, board_rows, bbox=bbox, clamp=clamp
        )
        if erode:
            # Une empreinte dont un décalage sort entièrement du plateau ne peut être placée
            # NULLE PART : l'accumulateur tombe à faux et il n'y a plus rien à intersecter.
            if windows is None:
                out[:] = False
                return out
            (sc0, sc1, sr0, sr1), (dc0, dc1, dr0, dr1) = windows
            shifted = np.zeros_like(src)
            shifted[dc0:dc1, dr0:dr1] = src[sc0:sc1, sr0:sr1]
            out &= shifted
            if not out.any():
                return out
            continue
        if windows is None:
            continue
        (sc0, sc1, sr0, sr1), (dc0, dc1, dr0, dr1) = windows
        out[dc0:dc1, dr0:dr1] |= src[sc0:sc1, sr0:sr1]
    return out


def dilate_by_kernel(
    src: "np.ndarray",
    kernel: "Any",
    board_cols: int,
    board_rows: int,
    *,
    bbox: Optional[SliceWindow] = None,
) -> "np.ndarray":
    """``out[c, r] = any_{(dc, dr) ∈ kernel} src[c + dc, r + dr]``.

    SOURCE UNIQUE des dilatations de masque du moteur. Boucle de slices uniquement :
    ``scipy.ndimage.binary_dilation`` a provoqué des segfaults sur certains environnements
    (extensions natives / ``origin``), donc pas de chemin SciPy ici — ni ailleurs.

    ``bbox`` (L_bbox, §0.22) : borne le slice DESTINATION à cette fenêtre, la source suivant par le
    décalage. Le tableau reste plein-board ; seules les cases de sortie utiles sont écrites → coût
    ``O(|kernel| × bbox)`` au lieu de ``O(|kernel| × board)``, sans remapping ni perte de parité.
    Correct dès que la sortie n'est jamais LUE hors de la fenêtre.
    """
    if getattr(kernel, "size", None) == 0:
        return np.zeros_like(src)
    return _accumulate_by_kernel(
        src, kernel, board_cols, board_rows, spread=False, bbox=bbox, erode=False
    )


def spread_by_kernel(
    src: "np.ndarray",
    kernel: "Any",
    board_cols: int,
    board_rows: int,
    *,
    bbox: Optional[SliceWindow] = None,
) -> "np.ndarray":
    """``out[c + dc, r + dr] = any src[c, r]`` pour chaque ``(dc, dr)`` du noyau.

    SOURCE UNIQUE des propagations : pas de BFS (src → voisin) ou union d'empreintes (ancre valide →
    cellules de son empreinte). C'est la dilatation par le décalage OPPOSÉ ; la négation des offsets
    et le bornage côté SOURCE en découlent tous les deux et sont faits ici, jamais par l'appelant.

    ``bbox`` : borne le slice SOURCE, la destination suivant par le décalage. Correct quand toutes
    les sources non nulles sont dans la fenêtre (union d'empreintes : ancres valides ⊆ reach ⊆ bbox).
    """
    return _accumulate_by_kernel(
        src, kernel, board_cols, board_rows, spread=True, bbox=bbox, erode=False
    )


def erode_by_kernel(
    src: "np.ndarray",
    kernel: "Any",
    board_cols: int,
    board_rows: int,
) -> "np.ndarray":
    """``out[c, r] = all_{(dc, dr) ∈ kernel} src[c + dc, r + dr]`` — l'érosion, jumelle du ET.

    Même géométrie que ``dilate_by_kernel`` (``src = dst + offset``), opérateur ``&`` au lieu de
    ``|``, et court-circuit dès que l'accumulateur est vide : une empreinte qui ne tient nulle part
    n'a plus besoin des offsets restants. Utilisée pour « l'ANCRE est-elle valide, c'est-à-dire
    TOUTE son empreinte est-elle acceptable ? ».
    """
    return _accumulate_by_kernel(
        src, kernel, board_cols, board_rows, spread=False, bbox=None, erode=True
    )


_FOOTPRINT_OFFSETS_CACHE: Dict[
    Tuple[str, Any, int],
    Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]],
] = {}


def base_size_cache_key(base_size: Any) -> Any:
    """Rend un ``BASE_SIZE`` HACHABLE, utilisable tel quel dans une clé de cache.

    ``BASE_SIZE`` est un SCALAIRE pour ``round``/``square`` mais une PAIRE
    ``[grand axe, petit axe]`` pour ``oval`` (invariant du socle, cf. ``require_base_size``) :
    une liste n'est pas hachable, donc toute mémoïsation clefée sur un socle lève
    ``TypeError: unhashable type: 'list'`` sur un socle oval. Le tuple garde l'identité
    discriminante (deux ovales de tailles différentes n'ont pas la même clé).

    SOURCE UNIQUE : cinq caches du moteur clefaient sur un socle, chacun avec sa copie de ce
    test — et l'une d'elles avait déjà dérivé (``isinstance(..., list)`` seul).
    """
    return tuple(base_size) if isinstance(base_size, (list, tuple)) else base_size


def socle_is_single_hex(base_shape: str, base_size: "int | Sequence[int]") -> bool:
    """Le socle tient-il dans UNE case, donc son empreinte est-elle son ancre ?

    SOURCE UNIQUE du prédicat : répondre « oui » à tort fait sauter l'expansion de l'empreinte,
    et tous les contrôles qui en dépendent (mur, chevauchement d'escouades, collision
    intra-escouade, EZ) ne regardent alors plus qu'un hex sur les dizaines que couvre le socle.

    Un socle NON ROND est toujours multi-hex : son ``BASE_SIZE`` est une PAIRE, si bien que le
    prédicat naïf ``not isinstance(base_size, int)`` — écrit deux fois dans le move — le classait
    à tort mono-hex. C'est la forme, pas le type de la taille, qui tranche.

    Une taille de socle ROND est scalaire (``require_scalar_base_size`` refuse tout le reste) : une
    paire y est un état FAUX et doit le rester. La branche ``not isinstance(base_size, int) or …``
    qui survivait ici rendait ``True`` dans ce cas — donc « ce socle tient dans une case » là où
    ``compute_occupied_hexes`` LÈVE, et un appelant qui l'aurait crue aurait transformé un état
    corrompu en empreinte plausible (mesuré le 2026-08-12 sur 1 344 couples forme/taille).

    ⚠️ CE PRÉDICAT N'EST PAS EXACT, ET NE PEUT PAS L'ÊTRE À CETTE SIGNATURE. Il rend ``False`` pour
    ``round``/2, ``square``/1 ou ``oval``/[2, 1], dont l'empreinte est pourtant l'ancre seule — 33
    couples sont dans ce cas. L'exactitude n'est pas une fonction de ``(forme, taille)`` : un
    ``oval``/[1, 3] n'occupe une seule case qu'aux orientations 1, 3 et 5, et un ``oval``/[3, 1]
    qu'aux orientations 0, 2 et 4. Il faudrait donc un paramètre ``orientation``, et il serait
    TOXIQUE là où ce prédicat compte : ``movement_handlers`` l'appelle avec l'orientation EN COURS
    d'un pivot à la molette non committé, si bien que le chemin rapide basculerait pendant que le
    joueur tourne la molette. La forme exacte est de toute façon
    ``len(precompute_footprint_offsets(...)[0]) == 1``, c'est-à-dire le calcul que le prédicat sert
    à éviter. Le conservatisme est donc la réponse, pas un pis-aller : un ``False`` de trop ne
    coûte qu'un calcul d'empreinte, un ``True`` de trop fait sauter tous les contrôles.
    Aucun de ces 33 couples n'est d'ailleurs atteignable : les ``BASE_SIZE`` du roster sont ≥ 10,
    et ``_scale_socle`` normalise tout en ``round``/1 dès ``inches_to_subhex <= 1``.
    """
    return base_shape == "round" and isinstance(base_size, int) and base_size <= 1


def precompute_footprint_offsets(
    base_shape: str,
    base_size: "int | Sequence[int]",
    orientation: int = 0,
) -> Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]:
    """Pre-compute footprint offsets for even-column and odd-column centers.

    On hex grids (offset odd-q), the pixel-space distance between a center
    and its surrounding hexes depends on column parity.  Computing the full
    footprint (via compute_occupied_hexes) is expensive when called per-BFS-step.
    This function computes it ONCE at two reference positions (one even-col,
    one odd-col) and returns relative (dc, dr) offset tuples that can be
    translated to any position in O(|footprint|).

    Args:
        base_shape: "round", "oval", or "square".
        base_size:  Diameter for round/square; [major, minor] for oval.
        orientation: Rotation step (0–5), affects oval/square only.

    Returns:
        (offsets_even, offsets_odd) where each is a tuple of (dc, dr) pairs.
        To reconstruct the footprint at (c, r):
            offsets = offsets_even if c % 2 == 0 else offsets_odd
            footprint = {(c + dc, r + dr) for dc, dr in offsets}

    Mémoïsé (L1) : le résultat ne dépend que de ``(base_shape, base_size,
    orientation)`` — géométrie pure, déterministe, sans état ni I/O. La sortie
    est immuable (tuples), donc partageable entre appelants sans copie ni risque
    de mutation. Aucune invalidation nécessaire.
    """
    cache_key = (base_shape, base_size_cache_key(base_size), orientation)
    cached = _FOOTPRINT_OFFSETS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    ref_row = 100
    fp_even = _compute_occupied_hexes_raw(0, ref_row, base_shape, base_size, orientation)
    fp_odd = _compute_occupied_hexes_raw(1, ref_row, base_shape, base_size, orientation)
    offsets_even = tuple((c - 0, r - ref_row) for c, r in fp_even)
    offsets_odd = tuple((c - 1, r - ref_row) for c, r in fp_odd)
    result = (offsets_even, offsets_odd)
    _FOOTPRINT_OFFSETS_CACHE[cache_key] = result
    return result


def _footprint_round(center_col: int, center_row: int, diameter: int) -> Set[Tuple[int, int]]:
    """Hex cells within a circle of given diameter (in hex units) centered on (center_col, center_row)."""
    radius = (diameter / 2.0) * _FOOTPRINT_SIZE_SCALE
    radius_sq = radius**2
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(diameter / 2.0)) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dist_sq = (hx - cx) ** 2 + (hy - cy) ** 2
            if dist_sq <= radius_sq:
                result.add((c, r))
    return result


def _footprint_oval(
    center_col: int, center_row: int,
    major: int, minor: int,
    orientation: int,
) -> Set[Tuple[int, int]]:
    """Hex cells within an axis-aligned ellipse, optionally rotated by orientation × (2π/ORIENTATION_STEP_COUNT)."""
    a = (major / 2.0) * _FOOTPRINT_SIZE_SCALE
    b = (minor / 2.0) * _FOOTPRINT_SIZE_SCALE
    angle_rad = orientation * _ORIENTATION_STEP_RAD
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(max(a, b))) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dx, dy = hx - cx, hy - cy
            lx = dx * cos_a + dy * sin_a
            ly = -dx * sin_a + dy * cos_a
            if a > 0 and b > 0 and (lx / a) ** 2 + (ly / b) ** 2 <= 1.0:
                result.add((c, r))
    return result


def _footprint_square(
    center_col: int, center_row: int,
    side: int,
    orientation: int,
) -> Set[Tuple[int, int]]:
    """Hex cells within a square of given side length, optionally rotated by orientation × (2π/ORIENTATION_STEP_COUNT)."""
    half = (side / 2.0) * _FOOTPRINT_SIZE_SCALE
    angle_rad = orientation * _ORIENTATION_STEP_RAD
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    cx, cy = _hex_center(center_col, center_row)
    scan_r = int(math.ceil(half * 1.5)) + 2
    result: Set[Tuple[int, int]] = set()
    for dc in range(-scan_r, scan_r + 1):
        for dr in range(-scan_r, scan_r + 1):
            c, r = center_col + dc, center_row + dr
            hx, hy = _hex_center(c, r)
            dx, dy = hx - cx, hy - cy
            lx = dx * cos_a + dy * sin_a
            ly = -dx * sin_a + dy * cos_a
            if abs(lx) <= half and abs(ly) <= half:
                result.add((c, r))
    return result


# ---------------------------------------------------------------------------
# Occupation map — cell → unit_id (§9.1, Invariant III §9.2)
# ---------------------------------------------------------------------------

def build_occupation_map(
    units_cache: Dict[str, Any],
    get_footprint: Callable[..., Set[Tuple[int, int]]],
) -> Dict[Tuple[int, int], str]:
    """Build sparse cell→unit_id map from all alive units.

    Args:
        units_cache: game_state["units_cache"], keyed by unit_id string.
        get_footprint: Callable(unit_entry) -> Set[(col, row)].

    Returns:
        Dict mapping each occupied cell to its unit_id.

    Raises:
        ValueError: If two units overlap (Invariant III violation).
    """
    occ: Dict[Tuple[int, int], str] = {}
    for uid, entry in units_cache.items():
        footprint = get_footprint(entry)
        for cell in footprint:
            if cell in occ:
                raise ValueError(
                    f"Invariant III violation: cell {cell} occupied by both "
                    f"unit {occ[cell]} and unit {uid}"
                )
            occ[cell] = uid
    return occ


def validate_placement(
    candidate_hexes: Set[Tuple[int, int]],
    unit_id: str,
    occupation_map: Dict[Tuple[int, int], str],
    wall_set: Set[Tuple[int, int]],
    cols: int,
    rows: int,
) -> Optional[str]:
    """Validate that a footprint can be placed without violations.

    Returns None if valid, or an error message string if invalid.
    """
    for c, r in candidate_hexes:
        if not is_in_bounds(c, r, cols, rows):
            return f"Cell ({c},{r}) out of bounds ({cols}x{rows})"
        if (c, r) in wall_set:
            return f"Cell ({c},{r}) is a wall"
        existing = occupation_map.get((c, r))
        if existing is not None and existing != unit_id:
            return f"Cell ({c},{r}) already occupied by unit {existing}"
    return None


# ---------------------------------------------------------------------------
# Wall set helper
# ---------------------------------------------------------------------------

def build_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Extract wall_hexes from game_state as a set of (int, int) tuples."""
    raw = game_state.get("wall_hexes")
    if not raw:
        return set()
    return {
        (int(w[0]), int(w[1])) if isinstance(w, (list, tuple)) else w
        for w in raw
    }


def build_dense_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Extract dense_wall_hexes (murs issus de terrains Solid/dense, rule 13.11) as a hex set.

    Sous-ensemble de wall_hexes limité aux murs typés ``"dense"`` à la source. Sert la règle
    13.5 (Gone to Ground) : seul un terrain Solid intervenant peut rendre un modèle "gone to
    ground", pas une simple obscuring area. Les murs sans type (forme brute ``wall_hexes`` sans
    classification) ne sont PAS Solid-prouvables → absents de ce set (aucun repli : on ne
    déclenche GtG que derrière un terrain dense avéré)."""
    raw = game_state.get("dense_wall_hexes")
    if not raw:
        return set()
    return {
        (int(w[0]), int(w[1])) if isinstance(w, (list, tuple)) else w
        for w in raw
    }


# ---------------------------------------------------------------------------
# Euclidean clearance — round bases (Board ×10), aligné sur frontend hexFootprint
# ---------------------------------------------------------------------------

# Pas horizontal entre centres de cases (repère _hex_center, hex_radius = 1).
ENGAGEMENT_NORM_HEX_WIDTH: float = 1.5


def round_base_radius_norm(base_size: float) -> float:
    """Rayon d'un socle rond en unités _hex_center (identique à ``_footprint_round``)."""
    if base_size < 1:
        base_size = 1
    return (base_size / 2.0) * _FOOTPRINT_SIZE_SCALE


def inflate_obstacles_by_footprint(
    obstacles: AbstractSet[Tuple[int, int]],
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
) -> Set[Tuple[int, int]]:
    """Minkowski discret : cellules-ancre dont l'empreinte toucherait un obstacle.

    Une ancre ``A`` est bloquée ssi ``A + off`` ∈ ``obstacles`` pour un ``off`` de son empreinte
    (``off_even`` si colonne paire, ``off_odd`` si impaire). C'est la forme « ensemble d'ancres »
    du test ``empreinte ∩ obstacles``, et la seule géométrie que le champ géodésique applique aux
    socles NON RONDS (clearance 0 + obstacles dilatés).
    """
    inflated: Set[Tuple[int, int]] = set()
    for _oc, _orr in obstacles:
        for _dc, _dr in off_even:
            _ac, _ar = _oc - _dc, _orr - _dr
            if (_ac & 1) == 0:
                inflated.add((_ac, _ar))
        for _dc, _dr in off_odd:
            _ac, _ar = _oc - _dc, _orr - _dr
            if (_ac & 1) == 1:
                inflated.add((_ac, _ar))
    return inflated


def socle_blocked_anchor_cells(
    obstacle_hexes: AbstractSet[Tuple[int, int]],
    base_shape: str,
    base_size: Any,
    orientation: int,
    board_cols: int,
    board_rows: int,
) -> Set[Tuple[int, int]]:
    """Ancres où le SOCLE chevaucherait l'un des ``obstacle_hexes``.

    SOURCE UNIQUE de « ce socle touche-t-il un obstacle de terrain ? » pour le PLACEMENT.
    Un hex-obstacle est un HEXAGONE, pas son centre : c'est déjà la géométrie qu'applique la
    TRAVERSÉE (``_segment_hits_hex``, clearance = rayon du socle). Le placement, lui, mesurait
    l'obstacle comme un POINT via l'empreinte hex (``_footprint_round`` = cases dont le CENTRE est
    dans le disque). Les deux critères divergent exactement sur la bande ``r < d <= r +
    circumradius`` : une figurine posée là est légale au placement et n'a AUCUN premier pas
    possible — ``geodesic_field`` ne garde le départ que par appartenance de case et suppose donc
    que le socle de départ ne chevauche aucun hexagone d'obstacle. Mesuré sur ``terrain-mc1``
    (base 8 à ×5) : 664 ancres légales au pool de mouvement VIDE, dont 198 dans les zones de
    déploiement. Cette fonction rétablit la précondition.

    Le désaccord est une propriété des géométries OBLIQUES : sur un mur en colonne droite les pas
    de colonne valent 1,5 unité-norme et la bande tombe entre deux colonnes, donc reste vide
    (mesuré : 0 ancre piège sur une colonne, 40 sur une diagonale, 25 sur un coin).

    Socle NON ROND : rien ne change, et c'est voulu — le champ géodésique dilate déjà ces socles
    par leur empreinte hex ORIENTÉE (``inflate_obstacles_by_footprint``, clearance 0), donc
    placement et traversée y coïncident déjà. Renvoyer autre chose ROUVRIRAIT l'écart.

    Lecture pure. Ne dépend que d'entrées STATIQUES pour une partie (murs, socle, orientation) →
    mémoïsé par ``shared_utils.wall_blocked_anchors``.
    """
    if not obstacle_hexes:
        return set()
    if base_shape != "round":
        off_even, off_odd = precompute_footprint_offsets(base_shape, base_size, orientation)
        blocked = inflate_obstacles_by_footprint(obstacle_hexes, off_even, off_odd)
    else:
        diameter = require_scalar_base_size(base_shape, base_size, "socle_blocked_anchor_cells")
        off_even_r, off_odd_r = _round_disc_contact_offsets(diameter)
        # Dilatation par un MOTIF, pas un test géométrique par paire (ancre, obstacle) : le motif
        # ne dépend que du rayon et de la parité de colonne de l'obstacle, donc il se calcule une
        # fois. Un scan géométrique coûtait ~1,4 M tests disque↔hexagone par rotation à ×10.
        blocked = set()
        for oc, orr in obstacle_hexes:
            oc_i, or_i = int(oc), int(orr)
            for dc, dr in (off_even_r if (oc_i & 1) == 0 else off_odd_r):
                blocked.add((oc_i + dc, or_i + dr))
    blocked |= _isolated_anchor_cells(blocked, board_cols, board_rows)
    return blocked


@lru_cache(maxsize=64)
def _round_disc_contact_offsets(
    diameter: int,
) -> Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]:
    """Offsets ``obstacle → ancre`` où le disque de l'ancre chevauche l'HEXAGONE de l'obstacle.

    Deux motifs, indexés par la parité de colonne de l'OBSTACLE : en odd-q, le décalage vertical
    d'une demi-hauteur dépend de la parité de chaque colonne, donc la géométrie relative n'est pas
    invariante par translation — même raison qui fait porter deux jeux d'offsets à
    ``precompute_footprint_offsets``. Mémoïsé : le motif ne dépend que du diamètre.
    """
    radius = round_base_radius_norm(diameter)
    reach = radius + _HEX_CIRCUMRADIUS  # au-delà, contact impossible
    d_col = int(math.ceil(reach / ENGAGEMENT_NORM_HEX_WIDTH)) + 1
    d_row = int(math.ceil(reach / math.sqrt(3.0))) + 1
    out: List[Tuple[Tuple[int, int], ...]] = []
    for obstacle_parity in (0, 1):
        corners = _hex_corners_at(*_hex_center(obstacle_parity, 0))
        offs: List[Tuple[int, int]] = []
        for dc in range(-d_col, d_col + 1):
            for dr in range(-d_row, d_row + 1):
                acx, acy = _hex_center(obstacle_parity + dc, dr)
                if disc_overlaps_polygon(acx, acy, radius, corners):
                    offs.append((dc, dr))
        out.append(tuple(offs))
    return out[0], out[1]


def _isolated_anchor_cells(
    blocked: AbstractSet[Tuple[int, int]], board_cols: int, board_rows: int
) -> Set[Tuple[int, int]]:
    """Ancres licites dont les SIX voisines sont interdites (ou hors plateau).

    Résidu mesuré : sur ``terrain-mc1``, la dilatation par le disque couvre 663 des 664 ancres d'où
    aucun mouvement n'est possible. La 664ᵉ n'est PAS une contradiction de métrique — le socle y
    tient vraiment — mais une POCHE d'une seule case : les six voisines sont trop étroites pour le
    socle, donc la figurine y entre au déploiement et n'en sort jamais. Aucun seuil arbitraire
    ici : « aucune voisine licite » est la définition exacte de « ne peut pas faire un premier
    pas », donc la règle ferme la classe sans en inventer une autre.

    Hors plateau compte comme interdit : une poche adossée au bord se referme par le bord.
    """
    # Phase 1 : construire la frange — seules les cases NON bloquées adjacentes à `blocked`
    # peuvent être des poches. Dédupliquées en un Set : chaque candidate est testée UNE SEULE
    # fois en phase 2, même si elle est voisine de plusieurs cells de `blocked`.
    # Coût : O(|blocked| × 6 + |frange| × 6) vs O(|blocked| × 36) pour l'approche naïve ;
    # à ×5 avec des murs étendus, |blocked| peut dépasser 30 000 cells — la différence est
    # mesurable (×5-×10 selon la forme du terrain).
    fringe: Set[Tuple[int, int]] = set()
    for cell in blocked:
        for nb in get_neighbors(*cell):
            nc, nr = nb
            if nb not in blocked and 0 <= nc < board_cols and 0 <= nr < board_rows:
                fringe.add(nb)
    # Phase 2 : parmi les candidates de la frange, garder celles dont TOUTES les voisines
    # sont bloquées ou hors plateau (définition exacte de « poche sans premier pas »).
    isolated: Set[Tuple[int, int]] = set()
    for nb in fringe:
        nc, nr = nb
        if all(
            (m in blocked) or not (0 <= m[0] < board_cols and 0 <= m[1] < board_rows)
            for m in get_neighbors(nc, nr)
        ):
            isolated.add(nb)
    return isolated


def euclidean_edge_clearance_round_round(
    center_col_a: int,
    center_row_a: int,
    base_size_a: float,
    center_col_b: int,
    center_row_b: int,
    base_size_b: float,
    *,
    mover_center_xy: Optional[Tuple[float, float]] = None,
) -> float:
    """Écart bord à bord entre deux socles ronds (négatif si chevauchement).

    ``mover_center_xy`` : optionnel, centre déjà calculé pour ``(center_col_a, center_row_a)``
    (évite des milliers de ``_hex_center`` identiques dans les boucles d’engagement).
    """
    if mover_center_xy is not None:
        cxa, cya = mover_center_xy
    else:
        cxa, cya = _hex_center(center_col_a, center_row_a)
    cxb, cyb = _hex_center(center_col_b, center_row_b)
    d = math.hypot(cxb - cxa, cyb - cya)
    return d - round_base_radius_norm(base_size_a) - round_base_radius_norm(base_size_b)


def engagement_minimum_clearance_norm(engagement_zone: int) -> float:
    """Écart bord à bord minimal d'engagement, en unités ``_hex_center``.

    ``engagement_zone`` : portée d'engagement exprimée en SOUS-HEX, soit
    ``game_rules['engagement_zone']`` (en pouces) × ``inches_to_subhex``, déjà convertie au
    chargement. Le seuil renvoyé = ``engagement_zone`` × pas horizontal normalisé — aligné
    ``getFightEngagementRingBoardPixels`` / ``engagementRoundRingPreviewHexesOnBoard``.
    """
    if engagement_zone <= 0:
        return 0.0
    return float(engagement_zone) * ENGAGEMENT_NORM_HEX_WIDTH


# ---------------------------------------------------------------------------
# Chevauchement de socles — test unifié (plan collision continue, étape 0)
# ---------------------------------------------------------------------------

# Tolérance flottante : un écart bord-à-bord >= -_OVERLAP_TOL est considéré « sans
# chevauchement » (tangence/contact toléré, superposition interdite). Même ordre de
# grandeur que le 1e-6 du test d'engagement.
_OVERLAP_TOL: float = 1e-6


def require_scalar_base_size(base_shape: str, base_size: Any, context: str) -> int:
    """Diamètre d'un socle `round`/`square` — la moitié « scalaire » de l'union `BASE_SIZE`.

    `BASE_SHAPE` est l'étiquette qui DÉTERMINE le type de `BASE_SIZE` : `round`/`square`
    portent un diamètre scalaire, `oval` une paire `[grand axe, petit axe]`. Le couple est
    validé UNE fois à la frontière de chargement (`game_state._scale_socle` /
    `GameStateManager.create_unit`).

    Ces gardes servent aux sites qui manipulent le couple BRUT (`units_cache`, datasheet) :
    elles transforment un `Any` de dictionnaire en valeur typée. Un SOCLE, lui, n'en a plus
    besoin : la fabrique ``Socle(...)`` choisit la classe concrète et c'est elle qui porte
    le type exact de `base_size`.
    """
    if isinstance(base_size, bool) or not isinstance(base_size, int):
        raise TypeError(
            f"{context}: BASE_SHAPE {base_shape!r} exige un BASE_SIZE entier (diamètre), "
            f"reçu {base_size!r}"
        )
    return base_size


def require_oval_base_size(base_size: Any, context: str) -> List[int]:
    """Paire `[grand axe, petit axe]` d'un socle `oval` (cf. ``require_scalar_base_size``)."""
    if (
        not isinstance(base_size, (list, tuple))
        or len(base_size) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) for v in base_size)
    ):
        raise TypeError(
            f"{context}: BASE_SHAPE 'oval' exige un BASE_SIZE [grand axe, petit axe] "
            f"d'entiers, reçu {base_size!r}"
        )
    return [int(base_size[0]), int(base_size[1])]


def require_base_size(base_shape: str, base_size: Any, context: str) -> "int | list[int]":
    """Valide le couple (`BASE_SHAPE`, `BASE_SIZE`) et rend la taille dans son type d'étiquette.

    C'est LA garde de l'invariant, appelée à la frontière où la donnée entre (chargement de
    datasheet) ; `context` doit nommer l'unité pour qu'une datasheet incohérente soit
    identifiable sans instrumenter le moteur.
    """
    if base_shape == "round" or base_shape == "square":
        return require_scalar_base_size(base_shape, base_size, context)
    if base_shape == "oval":
        return require_oval_base_size(base_size, context)
    raise ValueError(
        f"{context}: BASE_SHAPE inconnue {base_shape!r} (attendu 'round', 'square' ou 'oval')"
    )


class Socle:
    """Socle d'une figurine (ou empreinte d'une escouade) pour les tests de distance.

    UNION ÉTIQUETÉE, pas un enregistrement plat : `BASE_SHAPE` ne décrit pas seulement la
    forme, elle DÉTERMINE le type de la taille (`round`/`square` → diamètre scalaire,
    `oval` → paire `[grand axe, petit axe]`). Cette classe ne porte donc QUE ce qui est
    indépendant de la forme ; `base_size` vit sur les trois classes concrètes
    ``RoundSocle`` / ``SquareSocle`` / ``OvalSocle``, chacune avec son type exact. On ne
    peut pas lire une taille de socle sans savoir de quelle forme il s'agit — le
    vérificateur l'impose au lieu qu'un `cast` l'affirme.

    ``Socle(...)`` est la FABRIQUE : elle choisit la classe concrète d'après ``shape`` et
    refuse une taille qui contredit l'étiquette. Il n'existe donc aucune instance dont
    l'étiquette et la taille se contredisent — l'invariant n'est plus « vérifié », il est
    impossible à violer. La classe de base n'est jamais instanciée telle quelle.
    Les sites de lecture rétrécissent par ``type(s) is RoundSocle`` /
    ``isinstance(s, OvalSocle)``, un test que le chemin chaud faisait DÉJÀ sur ``shape``.

    ``fp`` (empreinte = cellules occupées) n'est nécessaire que pour la méthode
    empreinte (toute paire impliquant une base non ronde). Pour une paire ronde↔ronde
    MONO-figurine, le test est purement géométrique (centre + base_size) et ``fp`` peut
    rester None.

    ``model_centers`` : centres (col,row) de CHAQUE figurine vivante de l'escouade
    (source : ``occupied_hexes_by_model``). Requis pour mesurer une distance bord-à-bord
    ronde correcte vers une escouade multi-figurines : sans lui, le raccourci round↔round
    mesurerait jusqu'à la seule figurine-ancre (règle 01.04 : point le plus proche des
    socles). ``None`` ou liste à 1 élément → mono-figurine, comportement historique.
    """
    __slots__ = ("shape", "col", "row", "fp", "model_centers", "orientation")

    shape: str
    col: int
    row: int
    fp: Optional[Set[Tuple[int, int]]]
    model_centers: Optional[List[Tuple[int, int]]]
    orientation: int

    @overload
    def __new__(
        cls, shape: Literal["round"], base_size: int, col: int, row: int,
        fp: Optional[Set[Tuple[int, int]]] = None,
        model_centers: Optional[List[Tuple[int, int]]] = None,
        orientation: int = 0,
    ) -> "RoundSocle": ...

    @overload
    def __new__(
        cls, shape: Literal["square"], base_size: int, col: int, row: int,
        fp: Optional[Set[Tuple[int, int]]] = None,
        model_centers: Optional[List[Tuple[int, int]]] = None,
        orientation: int = 0,
    ) -> "SquareSocle": ...

    @overload
    def __new__(
        cls, shape: Literal["oval"], base_size: List[int], col: int, row: int,
        fp: Optional[Set[Tuple[int, int]]] = None,
        model_centers: Optional[List[Tuple[int, int]]] = None,
        orientation: int = 0,
    ) -> "OvalSocle": ...

    @overload
    def __new__(
        cls, shape: str, base_size: "int | List[int]", col: int, row: int,
        fp: Optional[Set[Tuple[int, int]]] = None,
        model_centers: Optional[List[Tuple[int, int]]] = None,
        orientation: int = 0,
    ) -> "Socle": ...

    def __new__(
        cls, shape: str, base_size: "int | List[int]", col: int, row: int,
        fp: Optional[Set[Tuple[int, int]]] = None,
        model_centers: Optional[List[Tuple[int, int]]] = None,
        orientation: int = 0,
    ) -> "Socle":
        """Choisit la classe concrète d'après l'étiquette et vérifie la taille associée.

        Les tests sont écrits `type(x) is int` / `type(x) is list` (et non `isinstance`)
        pour la même raison que ``require_scalar_base_size`` excluait explicitement `bool` :
        `True` est un `int` pour `isinstance`, jamais un diamètre.
        """
        obj: "Socle"
        if shape == "round":
            if type(base_size) is not int:
                raise TypeError(
                    f"Socle: BASE_SHAPE 'round' exige un BASE_SIZE entier (diamètre), "
                    f"reçu {base_size!r}"
                )
            obj = object.__new__(RoundSocle)
            obj.shape = "round"
            obj.base_size = base_size
        elif shape == "oval":
            if (
                type(base_size) is not list
                or len(base_size) != 2
                or type(base_size[0]) is not int
                or type(base_size[1]) is not int
            ):
                raise TypeError(
                    f"Socle: BASE_SHAPE 'oval' exige un BASE_SIZE [grand axe, petit axe] "
                    f"d'entiers, reçu {base_size!r}"
                )
            obj = object.__new__(OvalSocle)
            obj.shape = "oval"
            obj.base_size = base_size
        elif shape == "square":
            if type(base_size) is not int:
                raise TypeError(
                    f"Socle: BASE_SHAPE 'square' exige un BASE_SIZE entier (diamètre), "
                    f"reçu {base_size!r}"
                )
            obj = object.__new__(SquareSocle)
            obj.shape = "square"
            obj.base_size = base_size
        else:
            raise ValueError(
                f"Socle: BASE_SHAPE inconnue {shape!r} (attendu 'round', 'square' ou 'oval')"
            )
        obj.col = col
        obj.row = row
        obj.fp = fp
        obj.model_centers = model_centers
        obj.orientation = orientation
        return obj

    def _size_value(self) -> "int | List[int]":
        """Taille du socle dans sa forme élargie — sert UNIQUEMENT à repasser par la fabrique.

        Élargir le type est correct ici et seulement ici : la valeur retourne
        immédiatement dans ``Socle(...)``, qui la ré-étiquette. Aucun calcul géométrique
        ne passe par ce chemin (ils lisent ``base_size`` sur la classe concrète).
        """
        raise NotImplementedError(f"{type(self).__name__}._size_value")

    def bounding_radius(self) -> float:
        """Rayon englobant du socle (unités ``_hex_center``) — cf. ``bounding_radius_norm``."""
        raise NotImplementedError(f"{type(self).__name__}.bounding_radius")

    def with_model_centers(self, centers: List[Tuple[int, int]]) -> "Socle":
        """Même socle, autres centres de figurines (repasse par la fabrique)."""
        return Socle(
            self.shape, self._size_value(), self.col, self.row,
            self.fp, centers, self.orientation,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(shape={self.shape!r}, base_size={self._size_value()!r}, "
            f"col={self.col!r}, row={self.row!r}, orientation={self.orientation!r})"
        )


class RoundSocle(Socle):
    """Socle rond : ``base_size`` est le diamètre."""
    __slots__ = ("base_size",)

    base_size: int

    def _size_value(self) -> int:
        return self.base_size

    def bounding_radius(self) -> float:
        return (max(1, self.base_size) / 2.0) * _FOOTPRINT_SIZE_SCALE


class SquareSocle(Socle):
    """Socle carré : ``base_size`` est le côté."""
    __slots__ = ("base_size",)

    base_size: int

    def _size_value(self) -> int:
        return self.base_size

    def bounding_radius(self) -> float:
        # Le point le plus éloigné du centre est un COIN, à `demi-côté × √2` — cf.
        # `bounding_radius_norm`, dont ceci est le jumeau par classe. `footprints_overlap`
        # s'en sert pour ÉCARTER une paire sans la tester (`d > reach` → « pas de
        # chevauchement ») : sous-estimé, il déclarait disjoints deux carrés qui se touchent
        # par les diagonales.
        return (max(1, self.base_size) / 2.0) * _FOOTPRINT_SIZE_SCALE * math.sqrt(2.0)


class OvalSocle(Socle):
    """Socle ovale : ``base_size`` est la paire ``[grand axe, petit axe]``."""
    __slots__ = ("base_size",)

    base_size: List[int]

    def _size_value(self) -> List[int]:
        return self.base_size

    def bounding_radius(self) -> float:
        # Conservateur (broad-phase) : la plus grande dimension, cf. bounding_radius_norm.
        return (max(1, max(self.base_size)) / 2.0) * _FOOTPRINT_SIZE_SCALE


def bounding_radius_norm(shape: str, base_size: "int | list[int]") -> float:
    """Rayon englobant (unités ``_hex_center``), toutes formes — pour la broad-phase.

    Conservateur : pour oval/square on prend la plus grande dimension. Aligné sur
    ``_FOOTPRINT_SIZE_SCALE`` comme ``round_base_radius_norm``.

    ⚠️ CARRÉ : le point le plus éloigné du centre est un COIN, à ``demi-côté × √2``, et non le
    milieu d'un côté. `_socle_edge_primitives` construit d'ailleurs le polygone avec ses coins
    en ``(±half, ±half)``. Rendre ``half`` pour un carré n'englobait donc pas le socle : toute
    broad-phase qui s'en sert pour ÉCARTER des candidats sans les tester (clearance de mise en
    place, chevauchement d'empreintes) en laissait passer près des diagonales. Latent tant
    qu'aucune datasheet ne déclare `BASE_SHAPE: "square"` — les 161 unités du dépôt sont rondes
    ou ovales, et l'ovale, lui, est exact (son extrême EST le demi-grand-axe).
    """
    dim = max(base_size) if isinstance(base_size, (list, tuple)) else base_size
    if dim < 1:
        dim = 1
    radius = (dim / 2.0) * _FOOTPRINT_SIZE_SCALE
    if shape == "square":
        return radius * math.sqrt(2.0)
    return radius


def footprints_overlap(a: Socle, b: Socle) -> bool:
    """True si les deux socles se chevauchent (superposition interdite ; contact toléré).

    - Paire ronde↔ronde : clearance euclidien **continu** (exact). Chevauchement si l'écart
      bord-à-bord est strictement négatif (``< -_OVERLAP_TOL``) ; tangence (gap≈0) autorisée.
    - Toute paire impliquant une base non ronde : **méthode empreinte** (intersection des
      cellules). ``a.fp`` et ``b.fp`` doivent alors être fournis.

    Broad-phase (distance des centres vs rayons englobants) appliquée UNIQUEMENT devant le
    méthode empreinte : pour une paire ronde le test précis est déjà O(1), une broad-phase
    y serait redondante.
    """
    if type(a) is RoundSocle and type(b) is RoundSocle:
        gap = euclidean_edge_clearance_round_round(
            a.col, a.row, a.base_size, b.col, b.row, b.base_size
        )
        return gap < -_OVERLAP_TOL
    # Méthode empreinte (au moins une base non ronde) : broad-phase, puis intersection.
    cxa, cya = _hex_center(a.col, a.row)
    cxb, cyb = _hex_center(b.col, b.row)
    d = math.hypot(cxb - cxa, cyb - cya)
    reach = a.bounding_radius() + b.bounding_radius()
    if d > reach + _OVERLAP_TOL:
        return False
    if a.fp is None or b.fp is None:
        raise ValueError("footprints_overlap: empreinte (fp) requise pour une paire non ronde")
    return bool(a.fp & b.fp)


# Échantillonnage du contour d'un socle oval en polygone convexe pour la distance
# bord-à-bord continue. 32 sommets : l'erreur d'inscription max (corde vs arc) est
# < 0,5 % du demi-grand axe — négligeable devant la précision de portée requise.
_OVAL_EDGE_SAMPLES: int = 32


@lru_cache(maxsize=256)
def _oval_local_outline(
    size_a: float, size_b: float, orientation: int
) -> Tuple[Tuple[float, float], ...]:
    """Contour d'un socle oval, DÉJÀ TOURNÉ, centré sur l'origine. Mémoïsé.

    La clé porte l'orientation en plus de la taille : ``s.orientation`` est un entier discret
    (six valeurs), donc la rotation est aussi cachable que la forme. Sans elle, chaque figurine
    d'une escouade repayait ``_OVAL_EDGE_SAMPLES`` multiplications-additions pour le MÊME angle —
    la boucle chaude des 120 656 constructions de primitives mesurées sur un drive de 200 pas.
    Il ne reste au constructeur qu'une translation par figurine.
    """
    aa = (size_a / 2.0) * _FOOTPRINT_SIZE_SCALE
    bb = (size_b / 2.0) * _FOOTPRINT_SIZE_SCALE
    ang = orientation * _ORIENTATION_STEP_RAD
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    return tuple(
        (lx * cos_a - ly * sin_a, lx * sin_a + ly * cos_a)
        for lx, ly in (
            (aa * math.cos(2.0 * math.pi * k / _OVAL_EDGE_SAMPLES),
             bb * math.sin(2.0 * math.pi * k / _OVAL_EDGE_SAMPLES))
            for k in range(_OVAL_EDGE_SAMPLES)
        )
    )


@lru_cache(maxsize=64)
def _square_local_outline(size: float, orientation: int) -> Tuple[Tuple[float, float], ...]:
    """Contour d'un socle carré, DÉJÀ TOURNÉ, centré sur l'origine. Même rôle que l'oval."""
    half = (size / 2.0) * _FOOTPRINT_SIZE_SCALE
    ang = orientation * _ORIENTATION_STEP_RAD
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    return tuple(
        (lx * cos_a - ly * sin_a, lx * sin_a + ly * cos_a)
        for lx, ly in ((-half, -half), (half, -half), (half, half), (-half, half))
    )


def _socle_bounding_circles(s: Socle) -> List[Tuple[float, float, float]]:
    """Disque englobant ``(cx, cy, r)`` de CHAQUE figurine — sans construire aucun contour.

    C'est la moitié bon marché de ``_socle_edge_primitives`` : elle ne coûte qu'un
    ``_hex_center`` par figurine, là où le contour coûte ``_OVAL_EDGE_SAMPLES`` sommets. Le rayon
    vient de ``bounding_radius()``, LA primitive de broad-phase du fichier — la même que celle
    dont se servent ``footprints_overlap`` et la porte de clearance de la mise en place. En
    dériver un second (par exemple le max sur les sommets échantillonnés) donnerait aujourd'hui
    la même valeur par coïncidence — ``_OVAL_EDGE_SAMPLES`` étant multiple de 4, deux sommets
    tombent pile sur les axes — et divergerait silencieusement au premier changement
    d'échantillonnage, en rendant un booléen d'engagement faux sans rien lever.
    """
    centers = s.model_centers if s.model_centers else [(s.col, s.row)]
    radius = s.bounding_radius()
    out: List[Tuple[float, float, float]] = []
    for col, row in centers:
        cx, cy = _hex_center(int(col), int(row))
        out.append((cx, cy, radius))
    return out


def _group_bounding_circle(
    circles: List[Tuple[float, float, float]]
) -> Tuple[float, float, float]:
    """Disque englobant de TOUTE l'escouade, en O(n).

    Centre = barycentre des centres de figurines (pas le plus petit cercle englobant, dont le
    calcul exact coûterait plus cher que ce qu'il fait gagner) ; rayon = le plus éloigné. Un
    disque plus large qu'optimal reste un disque englobant : le minorant qu'il porte est plus
    lâche, jamais faux.
    """
    if len(circles) == 1:
        return circles[0]
    cx = sum(c[0] for c in circles) / len(circles)
    cy = sum(c[1] for c in circles) / len(circles)
    radius = max(math.hypot(x - cx, y - cy) + r for x, y, r in circles)
    return cx, cy, radius


def _group_lower_bound(
    circles_a: List[Tuple[float, float, float]],
    circles_b: List[Tuple[float, float, float]],
) -> float:
    """Minorant AGRÉGÉ de la distance bord-à-bord entre deux escouades, en un seul ``hypot``.

    Deux escouades dont les disques d'escouade sont séparés de plus que le seuil ne peuvent avoir
    AUCUNE paire de figurines en portée : le produit figurine × figurine — 100 mesures pour deux
    escouades de dix — se tranche alors d'un coup.
    """
    gx_a, gy_a, gr_a = _group_bounding_circle(circles_a)
    gx_b, gy_b, gr_b = _group_bounding_circle(circles_b)
    return math.hypot(gx_b - gx_a, gy_b - gy_a) - gr_a - gr_b


def _socle_edge_primitives(s: Socle) -> List[Tuple]:
    """Primitives géométriques continues (repère ``_hex_center``) d'un socle, une par figurine.

    Retourne une liste de primitives : ``('c', cx, cy, r)`` pour un socle rond (cercle
    analytique), ``('p', [(x, y), ...])`` pour oval/carré (polygone convexe orienté).
    ``model_centers`` (escouade multi-figurines) → une primitive par figurine ; sinon une
    seule primitive à l'ancre ``(col, row)``. L'orientation (oval/carré) vient de ``s.orientation``.

    Coûteuse par construction (un contour de ``_OVAL_EDGE_SAMPLES`` sommets par figurine) : les
    appelants qui n'ont besoin que d'un ordre de grandeur passent par ``_socle_bounding_circles``,
    et ne viennent ici que pour les paires que l'élagage n'a pas tranchées.
    """
    centers = s.model_centers if s.model_centers else [(s.col, s.row)]
    prims: List[Tuple] = []
    if type(s) is RoundSocle:
        r = round_base_radius_norm(s.base_size)
        for c, rr in centers:
            cx, cy = _hex_center(int(c), int(rr))
            prims.append(("c", cx, cy, r))
        return prims
    if type(s) is OvalSocle:
        size = s.base_size
        outline = _oval_local_outline(size[0], size[1], s.orientation)
    elif type(s) is SquareSocle:
        outline = _square_local_outline(s.base_size, s.orientation)
    else:
        # Inatteignable via la fabrique (elle n'émet que les trois classes concrètes) ;
        # seul un `object.__new__` direct sur la classe de base y mènerait.
        raise ValueError(f"euclidean_edge_distance: socle sans forme concrète {s!r}")
    for c, rr in centers:
        cx, cy = _hex_center(int(c), int(rr))
        prims.append(("p", [(cx + lx, cy + ly) for lx, ly in outline]))
    return prims


def _circle_poly_edge_dist(cx: float, cy: float, r: float, poly: List[Tuple[float, float]]) -> float:
    """Distance bord-à-bord entre un cercle (centre, rayon) et un polygone convexe. 0 si chevauchement."""
    if _point_in_polygon(cx, cy, poly):
        return 0.0
    best = math.inf
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        d2 = _point_segment_dist_sq(cx, cy, ax, ay, bx, by)
        if d2 < best:
            best = d2
    d = math.sqrt(best) - r
    return d if d > 0.0 else 0.0


def _poly_poly_edge_dist(pa: List[Tuple[float, float]], pb: List[Tuple[float, float]]) -> float:
    """Distance bord-à-bord entre deux polygones convexes. 0 si containment ou arêtes sécantes."""
    for x, y in pa:
        if _point_in_polygon(x, y, pb):
            return 0.0
    for x, y in pb:
        if _point_in_polygon(x, y, pa):
            return 0.0
    best = math.inf
    na, nb = len(pa), len(pb)
    for i in range(na):
        ax, ay = pa[i]
        bx, by = pa[(i + 1) % na]
        for j in range(nb):
            cx, cy = pb[j]
            dx, dy = pb[(j + 1) % nb]
            d2 = _seg_seg_dist_sq(ax, ay, bx, by, cx, cy, dx, dy)
            if d2 < best:
                best = d2
                if best <= 0.0:
                    return 0.0
    return math.sqrt(best)


def _vec_point_in_polygon(
    px: "np.ndarray", py: "np.ndarray", poly: "np.ndarray"
) -> "np.ndarray":
    """Ray casting vectorisé : N points (px, py) (N,) vs polygone convexe (M, 2) → bool (N,)."""
    n = len(poly)
    xi = poly[:, 0]
    yi = poly[:, 1]
    idx_nxt = np.roll(np.arange(n), -1)
    xj = xi[idx_nxt]
    yj = yi[idx_nxt]
    px2 = px[:, np.newaxis]       # (N, 1)
    py2 = py[:, np.newaxis]
    yi2 = yi[np.newaxis, :]       # (1, M)
    yj2 = yj[np.newaxis, :]
    xi2 = xi[np.newaxis, :]
    xj2 = xj[np.newaxis, :]
    cond1 = (yi2 > py2) != (yj2 > py2)                    # (N, M)
    ydiff = np.where(cond1, yj2 - yi2, 1.0)               # safe divisor
    cond2 = px2 < (xj2 - xi2) * (py2 - yi2) / ydiff + xi2
    return (cond1 & cond2).sum(axis=1) % 2 == 1           # (N,) bool


def _batch_circle_poly_dist(
    r_mover: float,
    enemy_abs: "np.ndarray",   # (nb, 2) sommets absolus du polygone ennemi
    cx: "np.ndarray",          # (N,) centres x des cercles mobile
    cy: "np.ndarray",          # (N,) centres y
) -> "np.ndarray":             # (N,) distances ≥ 0
    """Distance bord-à-bord vectorisée : N cercles (rayon fixe) vs 1 polygone convexe fixe."""
    N = len(cx)
    if N == 0:
        return np.empty(0, dtype=np.float64)
    nb = len(enemy_abs)
    inside = _vec_point_in_polygon(cx, cy, enemy_abs)    # (N,) bool
    ax_e = enemy_abs[:, 0]                               # (nb,)
    ay_e = enemy_abs[:, 1]
    bx_e = ax_e[np.roll(np.arange(nb), -1)]
    by_e = ay_e[np.roll(np.arange(nb), -1)]
    ddx = bx_e - ax_e                                   # (nb,)
    ddy = by_e - ay_e
    seg_sq = np.where(ddx * ddx + ddy * ddy > 0, ddx * ddx + ddy * ddy, 1.0)  # (nb,)
    px_n = cx[:, np.newaxis]                             # (N, 1)
    py_n = cy[:, np.newaxis]
    t_c = np.clip(
        ((px_n - ax_e[np.newaxis, :]) * ddx[np.newaxis, :]
         + (py_n - ay_e[np.newaxis, :]) * ddy[np.newaxis, :]) / seg_sq[np.newaxis, :],
        0.0, 1.0,
    )                                                    # (N, nb)
    qx = ax_e[np.newaxis, :] + t_c * ddx[np.newaxis, :]
    qy = ay_e[np.newaxis, :] + t_c * ddy[np.newaxis, :]
    d2 = (px_n - qx) ** 2 + (py_n - qy) ** 2          # (N, nb)
    min_d = np.sqrt(d2.min(axis=1))                     # (N,)
    return np.where(inside, 0.0, np.maximum(0.0, min_d - r_mover))


def _batch_poly_circle_dist(
    mover_rel: "np.ndarray",   # (na, 2) sommets relatifs au centre du polygone mobile
    r_enemy: float,
    enemy_cx: float,
    enemy_cy: float,
    cx: "np.ndarray",          # (N,) centres x des polygones mobiles
    cy: "np.ndarray",          # (N,) centres y
) -> "np.ndarray":             # (N,) distances ≥ 0
    """Distance bord-à-bord vectorisée : N polygones (translaté mover_rel) vs 1 cercle fixe."""
    N = len(cx)
    if N == 0:
        return np.empty(0, dtype=np.float64)
    na = len(mover_rel)
    rel_ex = enemy_cx - cx                              # (N,)
    rel_ey = enemy_cy - cy
    inside = _vec_point_in_polygon(rel_ex, rel_ey, mover_rel)  # (N,) bool
    ax_m = mover_rel[:, 0]                              # (na,)
    ay_m = mover_rel[:, 1]
    bx_m = ax_m[np.roll(np.arange(na), -1)]
    by_m = ay_m[np.roll(np.arange(na), -1)]
    ddx = bx_m - ax_m
    ddy = by_m - ay_m
    seg_sq = np.where(ddx * ddx + ddy * ddy > 0, ddx * ddx + ddy * ddy, 1.0)
    px_n = rel_ex[:, np.newaxis]                        # (N, 1)
    py_n = rel_ey[:, np.newaxis]
    t_c = np.clip(
        ((px_n - ax_m[np.newaxis, :]) * ddx[np.newaxis, :]
         + (py_n - ay_m[np.newaxis, :]) * ddy[np.newaxis, :]) / seg_sq[np.newaxis, :],
        0.0, 1.0,
    )                                                   # (N, na)
    qx = ax_m[np.newaxis, :] + t_c * ddx[np.newaxis, :]
    qy = ay_m[np.newaxis, :] + t_c * ddy[np.newaxis, :]
    d2 = (px_n - qx) ** 2 + (py_n - qy) ** 2
    min_d = np.sqrt(d2.min(axis=1))
    return np.where(inside, 0.0, np.maximum(0.0, min_d - r_enemy))


def _batch_poly_poly_dist(
    mover_rel: "np.ndarray",   # (na, 2) sommets relatifs au centre du polygone mobile
    enemy_abs: "np.ndarray",   # (nb, 2) sommets absolus du polygone ennemi
    cx: "np.ndarray",          # (N,) centres x des polygones mobiles
    cy: "np.ndarray",          # (N,) centres y
) -> "np.ndarray":             # (N,) distances ≥ 0
    """Distance bord-à-bord vectorisée : N polygones (translaté mover_rel) vs 1 polygone fixe.

    Algorithme : containment par ray-casting vectorisé (O(N·na·nb) mémoire), puis distances
    arête-arête en boucle sur les na×nb paires — chaque itération est O(M) en NumPy, avec
    M = candidats non-contenus. Pic mémoire ≪ (N·na·nb), compatible avec les noyaux EZ.
    """
    N = len(cx)
    na = len(mover_rel)
    nb = len(enemy_abs)
    if N == 0:
        return np.empty(0, dtype=np.float64)

    nxt_m = np.roll(np.arange(na), -1)
    mpa_s = mover_rel                        # (na, 2) départ arêtes mobile
    mpa_e = mover_rel[nxt_m]                 # (na, 2) arrivée arêtes mobile
    r0x = (mpa_e[:, 0] - mpa_s[:, 0]).astype(np.float64)   # (na,)
    r0y = (mpa_e[:, 1] - mpa_s[:, 1]).astype(np.float64)
    ab_sq = r0x * r0x + r0y * r0y           # (na,)

    nxt_e = np.roll(np.arange(nb), -1)
    epb_s = enemy_abs                        # (nb, 2)
    epb_e = enemy_abs[nxt_e]
    s0x = (epb_e[:, 0] - epb_s[:, 0]).astype(np.float64)   # (nb,)
    s0y = (epb_e[:, 1] - epb_s[:, 1]).astype(np.float64)
    cd_sq = s0x * s0x + s0y * s0y           # (nb,)

    # ── Containment : sommets du mobile dans le polygone ennemi ──────────────────────────
    mover_vx = mpa_s[:, 0, np.newaxis] + cx[np.newaxis, :]   # (na, N)
    mover_vy = mpa_s[:, 1, np.newaxis] + cy[np.newaxis, :]
    in_enemy = _vec_point_in_polygon(
        mover_vx.ravel(), mover_vy.ravel(), enemy_abs
    ).reshape(na, N).any(axis=0)                             # (N,)

    # ── Containment : sommets ennemis dans le polygone mobile (coordonnées relatives) ────
    enemy_rx = epb_s[:, 0, np.newaxis] - cx[np.newaxis, :]   # (nb, N)
    enemy_ry = epb_s[:, 1, np.newaxis] - cy[np.newaxis, :]
    in_mover = _vec_point_in_polygon(
        enemy_rx.ravel(), enemy_ry.ravel(), mover_rel
    ).reshape(nb, N).any(axis=0)                             # (N,)

    contained = in_enemy | in_mover
    dist = np.full(N, np.inf, dtype=np.float64)
    dist[contained] = 0.0

    need = ~contained
    if not need.any():
        return dist

    cx_n = cx[need]   # (M,)
    cy_n = cy[need]
    M = len(cx_n)

    # ── Distances arête-arête pour les M candidats non-contenus ──────────────────────────
    # Boucle sur na×nb paires d'arêtes ; chaque itération est vectorisée sur M.
    d2_min = np.full(M, np.inf, dtype=np.float64)
    for i in range(na):
        ax_k = mpa_s[i, 0] + cx_n   # (M,) coord absolue du départ de l'arête i du mobile
        ay_k = mpa_s[i, 1] + cy_n
        r0xi = float(r0x[i])         # scalaire : direction (shift-invariant)
        r0yi = float(r0y[i])
        ab_sqi = float(ab_sq[i])
        for j in range(nb):
            cxj = float(epb_s[j, 0])
            cyj = float(epb_s[j, 1])
            dxj = float(epb_e[j, 0])
            dyj = float(epb_e[j, 1])
            s0xj = float(s0x[j])
            s0yj = float(s0y[j])
            cd_sqj = float(cd_sq[j])
            # Vecteur C→A (dépend de la position du candidat)
            dcx = cxj - ax_k   # (M,)
            dcy = cyj - ay_k
            # ── 4 distances point-segment ──────────────────────────────────────────────
            # C vs AB :
            if ab_sqi > 0.0:
                tc = np.clip((dcx * r0xi + dcy * r0yi) / ab_sqi, 0.0, 1.0)
            else:
                tc = np.zeros(M, dtype=np.float64)
            d2_cAB = (dcx - tc * r0xi) ** 2 + (dcy - tc * r0yi) ** 2
            # D vs AB :
            dcx_D = dcx + s0xj
            dcy_D = dcy + s0yj
            if ab_sqi > 0.0:
                td = np.clip((dcx_D * r0xi + dcy_D * r0yi) / ab_sqi, 0.0, 1.0)
            else:
                td = np.zeros(M, dtype=np.float64)
            d2_dAB = (dcx_D - td * r0xi) ** 2 + (dcy_D - td * r0yi) ** 2
            # A vs CD :
            if cd_sqj > 0.0:
                ta = np.clip((-dcx * s0xj - dcy * s0yj) / cd_sqj, 0.0, 1.0)
            else:
                ta = np.zeros(M, dtype=np.float64)
            d2_aCD = (dcx + ta * s0xj) ** 2 + (dcy + ta * s0yj) ** 2
            # B vs CD :
            bcx = r0xi - dcx   # = bx_k - cxj
            bcy = r0yi - dcy
            if cd_sqj > 0.0:
                tb = np.clip((bcx * s0xj + bcy * s0yj) / cd_sqj, 0.0, 1.0)
            else:
                tb = np.zeros(M, dtype=np.float64)
            d2_bCD = (bcx - tb * s0xj) ** 2 + (bcy - tb * s0yj) ** 2
            d2_pair = np.minimum(np.minimum(d2_cAB, d2_dAB), np.minimum(d2_aCD, d2_bCD))
            # Intersection → distance nulle
            denom = r0xi * s0yj - r0yi * s0xj   # scalaire
            if abs(denom) > 1e-12:
                inv = 1.0 / denom
                t_s = (dcx * s0yj - dcy * s0xj) * inv   # (M,)
                u_s = (dcx * r0yi - dcy * r0xi) * inv
                inter = (t_s >= -1e-12) & (t_s <= 1.0 + 1e-12) & (u_s >= -1e-12) & (u_s <= 1.0 + 1e-12)
                d2_pair[inter] = 0.0
            d2_min = np.minimum(d2_min, d2_pair)
            if not (d2_min > 0.0).any():   # sortie anticipée : tous à 0
                break
        if not (d2_min > 0.0).any():
            break

    dist[need] = np.sqrt(d2_min)
    return dist


def _primitive_edge_dist(pa: Tuple, pb: Tuple) -> float:
    """Distance bord-à-bord entre deux primitives (``'c'`` cercle / ``'p'`` polygone)."""
    if pa[0] == "c" and pb[0] == "c":
        gap = math.hypot(pb[1] - pa[1], pb[2] - pa[2]) - pa[3] - pb[3]
        return gap if gap > 0.0 else 0.0
    if pa[0] == "c":
        return _circle_poly_edge_dist(pa[1], pa[2], pa[3], pb[1])
    if pb[0] == "c":
        return _circle_poly_edge_dist(pb[1], pb[2], pb[3], pa[1])
    return _poly_poly_edge_dist(pa[1], pb[1])


def euclidean_edge_distance(a: Socle, b: Socle, max_distance: Optional[float] = None) -> float:
    """Distance euclidienne **bord-à-bord** entre deux socles, en unités ``_hex_center``.

    Équivalent euclidien de ``min_distance_between_sets`` (règle 01.04 : on mesure au
    point le plus proche des socles). Même dispatch que ``footprints_overlap``, mais
    renvoie la distance au lieu d'un booléen de chevauchement.

    - Paire ronde↔ronde : clearance euclidien continu (exact), O(1), via
      ``euclidean_edge_clearance_round_round``. Borné à 0 (socles tangents/chevauchants).
    - Toute paire impliquant une base non ronde : distance bord-à-bord **continue** entre les
      contours géométriques réels (cercle analytique / polygone convexe oval ou carré orienté),
      via ``_socle_edge_primitives`` — plus l'approximation centre-de-cellule. Escouade
      multi-figurines : min sur chaque paire de figurines. 0 si les socles se chevauchent.

    ÉCHELLE : résultat en unités ``_hex_center`` (1 subhex = ``_FOOTPRINT_SIZE_SCALE`` = 1,5).
    Pour comparer à une portée en subhexes, l'appelant convertit le seuil :
    ``distance <= rng_subhex * ENGAGEMENT_NORM_HEX_WIDTH``.

    ``max_distance`` — même PROMESSE que ``min_distance_between_sets``, dont c'est le jumeau
    euclidien : le résultat n'est garanti EXACT que tant qu'il est ``<= max_distance``. Au-delà,
    une valeur strictement supérieure à ``max_distance`` est rendue (une borne inférieure par
    disques englobants, pas nécessairement la distance) — suffisant pour le test de seuil que
    font TOUS les appelants qui le passent, et pour eux seuls.

    ⚠️ La SENTINELLE, elle, est l'inverse de celle du jumeau, et le copier-coller hex→euclidien
    est le mode d'échec dominant de ce dépôt : ``min_distance_between_sets`` désactive son prune
    avec ``max_distance=0``, cette fonction avec ``max_distance=None``. Raison : en unités-norme
    flottantes, ``0.0`` est un seuil LÉGITIME (socles tangents), donc il ne peut pas signifier
    « pas de seuil ». La traduction entre les deux conventions est faite une seule fois, dans
    ``combat_utils.ranged_edge_distance``, qui sert les deux métriques.

    Pourquoi ce paramètre existe : mesuré sur un drive de 200 pas du vrai moteur, cette fonction
    pesait 13,7 s sur 37 s, dont 21 M d'appels à ``_point_segment_dist_sq`` — le produit
    arête × arête de deux contours ovals à 32 sommets, refait pour des socles souvent très
    éloignés. Le disque circonscrit écarte ces paires-là en O(1), sans jamais changer le verdict.
    """
    if type(a) is RoundSocle and type(b) is RoundSocle:
        # Règle 01.04 : distance au point le plus proche des socles. Pour une escouade
        # multi-figurines, on prend le min du clearance bord-à-bord sur chaque paire de
        # figurines (centres réels), pas seulement l'ancre. Mono-figurine → une seule paire
        # = comportement historique.
        centers_a = a.model_centers if a.model_centers else [(a.col, a.row)]
        centers_b = b.model_centers if b.model_centers else [(b.col, b.row)]
        if max_distance is not None and len(centers_a) * len(centers_b) > 1:
            # Le raccourci d'escouade ne paie QUE s'il remplace plusieurs paires : la mesure
            # ronde↔ronde est déjà O(1) par paire de figurines, donc pour un duel 1×1 la
            # broad-phase serait du travail net en plus — et c'est la forme la plus fréquente
            # du jeu. Mesuré : la poser inconditionnellement ajoutait 2,7 M d'appels de fonction
            # sur un drive de 200 pas, pour un gain nul sur ce cas-là.
            grouped = _group_lower_bound(_socle_bounding_circles(a), _socle_bounding_circles(b))
            if grouped > max_distance:
                return grouped
        base_a = a.base_size
        base_b = b.base_size
        best = math.inf
        for ca, ra in centers_a:
            for cb, rb in centers_b:
                gap = euclidean_edge_clearance_round_round(ca, ra, base_a, cb, rb, base_b)
                if gap < best:
                    best = gap
                    if best <= 0.0:
                        return 0.0
        return best if best > 0.0 else 0.0
    # Au moins une base non ronde : distance bord-à-bord continue entre contours géométriques.
    # Les contours ne sont PAS construits d'avance — c'est la dépense que l'élagage veut éviter.
    circles_a = _socle_bounding_circles(a)
    circles_b = _socle_bounding_circles(b)
    if max_distance is not None and len(circles_a) * len(circles_b) > 1:
        grouped = _group_lower_bound(circles_a, circles_b)
        if grouped > max_distance:
            return grouped
    prims_a: Optional[List[Tuple]] = None
    prims_b: Optional[List[Tuple]] = None
    best = math.inf
    for i, (ax, ay, rad_circ_a) in enumerate(circles_a):
        for j, (bx, by, rad_circ_b) in enumerate(circles_b):
            # MINORANT exact : chaque contour est inclus dans son disque englobant.
            lower = math.hypot(bx - ax, by - ay) - rad_circ_a - rad_circ_b
            if lower >= best:
                continue  # cette paire ne peut plus améliorer le minimum — élagage sans effet
            if max_distance is not None and lower > max_distance:
                # Hors seuil de façon certaine. On retient le minorant : il est lui-même
                # > max_distance, donc tout ce que l'élagage écarte ensuite l'est aussi, et la
                # valeur rendue reste conforme au contrat. Mélanger ainsi borne et distance dans
                # `best` est sûr pour cette raison, et pour elle seule.
                #
                # Le majorant symétrique — `écart des centres - r_inscrit_a - r_inscrit_b`, qui
                # conclurait « en portée » sans parcourir les arêtes — n'est délibérément PAS
                # utilisé : il rendrait une valeur `<= max_distance` SUPÉRIEURE à la distance
                # réelle, alors que le contrat (celui de `min_distance_between_sets`, dont ce
                # paramètre est le jumeau) promet l'exactitude sous le seuil. Un appelant futur
                # qui lirait la distance au lieu du seul booléen recevrait une mesure gonflée.
                best = lower
                continue
            if prims_a is None:
                prims_a = _socle_edge_primitives(a)
                prims_b = _socle_edge_primitives(b)
            assert prims_b is not None  # posé avec prims_a, jamais séparément
            # Élagage par fonction support : séparation signée dans la direction inter-centres.
            # Couvre poly–poly ET circle–poly (round vs oval) — le cas circle–circle est sauté
            # (tight == lower déjà testé ci-dessus). Réduit ~81 % des appels _primitive_edge_dist
            # pour les kernels EZ oval–oval et oval–round à x5.
            if max_distance is not None:
                dist_ab = lower + rad_circ_a + rad_circ_b
                if dist_ab > 1e-12:
                    _a_poly = prims_a[i][0] == "p"
                    _b_poly = prims_b[j][0] == "p"
                    if _a_poly or _b_poly:
                        dx_n = (bx - ax) / dist_ab
                        dy_n = (by - ay) / dist_ab
                        max_a = (
                            max(x * dx_n + y * dy_n for x, y in prims_a[i][1])
                            if _a_poly else ax * dx_n + ay * dy_n + prims_a[i][3]
                        )
                        min_b = (
                            min(x * dx_n + y * dy_n for x, y in prims_b[j][1])
                            if _b_poly else bx * dx_n + by * dy_n - prims_b[j][3]
                        )
                        tight = min_b - max_a
                        if tight > max_distance:
                            best = min(best, tight)
                            continue
            d = _primitive_edge_dist(prims_a[i], prims_b[j])
            if d < best:
                best = d
                if best <= 0.0:
                    return 0.0
    return best if best > 0.0 else 0.0


def _point_in_polygon(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> bool:
    """Ray casting : True si (px,py) est à l'intérieur du polygone (mêmes semantiques que
    le rasterizer ``_objective_polygon_hexes``)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_segment_dist_sq(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance au carré minimale du point (px,py) au segment [a,b]."""
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq <= 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2  # segment dégénéré -> distance au point a
    t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


# ---------------------------------------------------------------------------
# Champ de distance géodésique any-angle (lazy Theta* en flood) — Étape 4.0.
#
# Porté du spike `spikes/geodesic_field_spike.py` sur la VRAIE géométrie moteur :
#   - centres via `_hex_center` (pas hex_width/hex_height locaux) ;
#   - voisins via `get_neighbors` (odd-q autoritaire, = listes inline du BFS move).
# Résultat en unités `_hex_center` (1 subhex = ENGAGEMENT_NORM_HEX_WIDTH = 1,5).
#
# Deux généralisations vs le spike :
#   - `clearance` : le test de visibilité devient un test de CAPSULE (segment épaissi
#     du rayon de socle). À `clearance=0` → LoS-ray (tangence à un coin convexe permise,
#     comme le spike, pour serrer un angle isolé) ; à `clearance>0` → un disque de rayon
#     `clearance` ne peut passer à moins de `clearance` d'un mur (règle 03 : mesurer le
#     point le plus éloigné du socle revient à mesurer le CENTRE avec obstacles gonflés,
#     puisqu'en translation tout point du socle parcourt la distance du centre).
#   - `obstacles` : ensemble générique de cellules bloquantes (murs, et selon les toggles
#     de traversée : ennemis / amis / bande d'EZ) — pas seulement les murs.
#
# GRAZING / SQUEEZE (2026-07-04) : à `clearance=0` la règle « deux murs jointifs bloquent
# le passage par leur coin partagé » n'est PAS gérée (LoS-ray, tangence permise) — assumé
# pour le point/oval (l'oval est géré en amont par dilatation d'empreinte). À `clearance>0`
# elle EST gérée, mais PAS « de fait » : le rattachement (plus bas) teste le pas adjacent
# `cur→nb` à la capsule et écarte `nb` si le socle y chevaucherait un mur → un socle rond ne
# peut ni traverser ni se centrer sur un goulot plus étroit que son diamètre. Sans ce test,
# le flood cellule-par-cellule se faufilait partout (la clearance ne bornait que le raccourci
# any-angle). Cf. « 4.0-bis » de Documentation/Reference/moteur/geometrie_et_distances.md.
# ---------------------------------------------------------------------------

_SEG_TOL: float = 1e-9
_HEX_CIRCUMRADIUS: float = 1.0  # centre→sommet dans le repère `_hex_center`
# Décalages des 6 sommets flat-top (précalculés une fois : évite 6 cos/sin par test d'obstacle).
_HEX_CORNER_OFFSETS: Tuple[Tuple[float, float], ...] = tuple(
    (_HEX_CIRCUMRADIUS * math.cos(math.radians(60 * k)),
     _HEX_CIRCUMRADIUS * math.sin(math.radians(60 * k)))
    for k in range(6)
)


def _hex_corners_at(cx: float, cy: float) -> List[Tuple[float, float]]:
    """6 sommets d'une cellule flat-top centrée en (cx, cy) (circumradius 1)."""
    return [(cx + ox, cy + oy) for ox, oy in _HEX_CORNER_OFFSETS]


def build_hex_center_index(
    hexes: "set[tuple[int, int]] | Sequence[Tuple[int, int]]", bucket_size: float
) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Index spatial des centres ``_hex_center`` des ``hexes``, groupés par bucket de côté
    ``bucket_size``. Construit UNE fois, réutilisé par ``disc_overlaps_indexed_hexes`` pour un test
    O(1) amorti par case (au lieu de re-parcourir tout ``hexes``). ``bucket_size`` doit valoir la
    portée de contact (``r + circumradius``) pour qu'un hexagone chevauchant soit dans le bucket de la
    case testée ou l'un de ses 8 voisins."""
    idx: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    for hc, hr in hexes:
        cx, cy = _hex_center(int(hc), int(hr))
        idx.setdefault((int(cx // bucket_size), int(cy // bucket_size)), []).append((cx, cy))
    return idx


def disc_overlaps_indexed_hexes(
    cx: float, cy: float, r: float,
    index: Dict[Tuple[int, int], List[Tuple[float, float]]], bucket_size: float,
) -> bool:
    """True si le disque ``((cx,cy), r)`` chevauche l'un des hexagones indexés par
    ``build_hex_center_index`` (même ``bucket_size``). Pendant STATIONNAIRE de la clairance capsule du
    champ géodésique du move (un socle rond « heurte » un hex-obstacle ssi son disque le chevauche) →
    réplique EXACTEMENT, hors BFS, la clairance ``_low_clear`` du move. Ne teste que le bucket de la case
    et ses 8 voisins (portée = ``r + circumradius`` = ``bucket_size``)."""
    if not index:
        return False
    reach_sq = (r + _HEX_CIRCUMRADIUS) ** 2
    gx, gy = int(cx // bucket_size), int(cy // bucket_size)
    for bgx in (gx - 1, gx, gx + 1):
        for bgy in (gy - 1, gy, gy + 1):
            for (hx, hy) in index.get((bgx, bgy), ()):  # get allowed
                if (hx - cx) ** 2 + (hy - cy) ** 2 > reach_sq:
                    continue
                if disc_overlaps_polygon(cx, cy, r, _hex_corners_at(hx, hy)):
                    return True
    return False


def _obstacle_bucket_size(clearance: float) -> float:
    """Taille de bucket de l'index spatial d'obstacles (unités ``_hex_center``)."""
    return max(2.0, _HEX_CIRCUMRADIUS + (clearance if clearance > 0.0 else 0.0))


def _build_obstacle_index(
    obstacles: Set[Tuple[int, int]], bucket_size: float,
    center: Optional[Tuple[float, float]] = None, reach_sq: Optional[float] = None,
) -> Dict[Tuple[int, int], List[Tuple[float, float]]]:
    """Index spatial : bucket (grille pixel) → centres des obstacles. Chaque obstacle est inscrit
    dans SON bucket ET ses 8 voisins (la marge circumradius+clearance ≤ bucket_size est ainsi
    absorbée à la construction). Un segment n'a donc qu'à visiter les buckets qu'il TRAVERSE
    (DDA), sans balayage latéral par segment. Centres précalculés une fois.

    ``center``/``reach_sq`` (optionnels) : élagage à la source — un obstacle dont le centre est
    au-delà de ``reach_sq`` du départ ne peut affecter aucune cellule atteignable (voir
    ``geodesic_field``), il est donc omis de l'index. Sans ces params : aucun élagage (comportement
    d'origine, utilisé par le multi-source)."""
    idx: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    _cx, _cy = center if center is not None else (0.0, 0.0)
    for (wc, wr) in obstacles:
        ocx, ocy = _hex_center(wc, wr)
        if reach_sq is not None and (ocx - _cx) * (ocx - _cx) + (ocy - _cy) * (ocy - _cy) > reach_sq:
            continue
        bgx, bgy = int(ocx // bucket_size), int(ocy // bucket_size)
        for gx in range(bgx - 1, bgx + 2):
            for gy in range(bgy - 1, bgy + 2):
                idx.setdefault((gx, gy), []).append((ocx, ocy))
    return idx


def _segment_clear_indexed(
    ax: float, ay: float, bx: float, by: float,
    bucket_size: float, idx: Dict[Tuple[int, int], List[Tuple[float, float]]], clearance: float,
) -> bool:
    """``segment_clear`` sur index pré-bâti : DDA (Amanatides-Woo) le long du segment — ne visite
    que les buckets réellement traversés (chacun une fois). La marge est déjà dans l'index.

    ⚠️ LE TEST DE BUCKET EST ÉCRIT DEUX FOIS — bucket de départ, puis boucle DDA. Toute
    modification de l'un DOIT être reportée sur l'autre (`grep -n "Rejet rapide" hex_utils.py`
    les trouve tous les deux). C'est le motif jumeau que ce dépôt rate le plus souvent, et il est
    assumé ici pour une raison mesurée : le test vivait dans une closure `_hit`, reconstruite à
    chaque appel et invoquée une fois par bucket visité — 4 à 20 visites par segment selon la
    taille de socle. Mesure sur le champ de charge x5 (8 588 cellules, 26 971 segments,
    207 168 visites) : 6 à 10 % de gain, trois réplicats à ±0,5 %, témoins « origine »
    relabellisés dans la bande [-5 %, +4 %]. Champ rendu bit-identique.
    """
    if not idx:
        return True
    _bucket_of = idx.get
    gx, gy = int(ax // bucket_size), int(ay // bucket_size)
    gxe, gye = int(bx // bucket_size), int(by // bucket_size)
    # Rejet rapide : l'hexagone tient dans le disque circumradius autour de son centre ; si ce
    # centre est plus loin que circumradius+clearance du segment, aucun contact possible → on
    # évite `_hex_corners_at` (alloc) + le test capsule (12 arêtes) pour la plupart des obstacles.
    _reach = _HEX_CIRCUMRADIUS + (clearance if clearance > 0.0 else 0.0) + _SEG_TOL
    _reach_sq = _reach * _reach

    bucket = _bucket_of((gx, gy))
    if bucket:
        for (ocx, ocy) in bucket:
            if _point_segment_dist_sq(ocx, ocy, ax, ay, bx, by) <= _reach_sq and _segment_hits_hex(
                ax, ay, bx, by, _hex_corners_at(ocx, ocy), ocx, ocy, clearance
            ):
                return False
    if gx == gxe and gy == gye:
        return True
    dx, dy = bx - ax, by - ay
    step_x = 1 if dx > 0 else -1
    step_y = 1 if dy > 0 else -1
    t_delta_x = bucket_size / abs(dx) if dx != 0 else math.inf
    t_delta_y = bucket_size / abs(dy) if dy != 0 else math.inf
    if dx > 0:
        t_max_x = ((gx + 1) * bucket_size - ax) / dx
    elif dx < 0:
        t_max_x = (gx * bucket_size - ax) / dx
    else:
        t_max_x = math.inf
    if dy > 0:
        t_max_y = ((gy + 1) * bucket_size - ay) / dy
    elif dy < 0:
        t_max_y = (gy * bucket_size - ay) / dy
    else:
        t_max_y = math.inf
    while True:
        if t_max_x < t_max_y:
            if t_max_x > 1.0:
                break
            gx += step_x
            t_max_x += t_delta_x
        else:
            if t_max_y > 1.0:
                break
            gy += step_y
            t_max_y += t_delta_y
        # Rejet rapide : COPIE du test du bucket de départ ci-dessus (cf. l'avertissement de la
        # docstring). Les deux doivent rester identiques.
        bucket = _bucket_of((gx, gy))
        if bucket:
            for (ocx, ocy) in bucket:
                if _point_segment_dist_sq(
                    ocx, ocy, ax, ay, bx, by
                ) <= _reach_sq and _segment_hits_hex(
                    ax, ay, bx, by, _hex_corners_at(ocx, ocy), ocx, ocy, clearance
                ):
                    return False
        if gx == gxe and gy == gye:
            break
    return True


def _segment_crosses_hex_interior(
    ax: float, ay: float, bx: float, by: float,
    corners: Sequence[Tuple[float, float]], cx: float, cy: float,
) -> bool:
    """True si [A,B] traverse l'INTÉRIEUR de la cellule (longueur d'intersection > 0).

    Cyrus-Beck sur l'hexagone convexe. La simple tangence à un sommet/arête ne bloque
    PAS (on peut serrer l'angle convexe d'un mur isolé = plus court chemin). Identique
    au `_segment_hits_hex` du spike.
    """
    dx, dy = bx - ax, by - ay
    t_enter, t_exit = 0.0, 1.0
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        ex, ey = x2 - x1, y2 - y1
        nx, ny = ey, -ex  # normale de l'arête
        if (nx * (cx - x1) + ny * (cy - y1)) > 0:  # oriente vers l'extérieur
            nx, ny = -nx, -ny
        denom = nx * dx + ny * dy
        num = nx * (ax - x1) + ny * (ay - y1)
        if abs(denom) < 1e-12:
            if num > 1e-12:
                return False  # parallèle et hors du demi-plan
            continue
        t = -num / denom
        if denom < 0:
            t_enter = max(t_enter, t)
        else:
            t_exit = min(t_exit, t)
        if t_enter > t_exit:
            return False
    return (t_exit - t_enter) > _SEG_TOL


def _seg_seg_dist_sq(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> float:
    """Distance au carré minimale entre les segments [A,B] et [C,D] (0 s'ils se coupent)."""
    r0x, r0y = bx - ax, by - ay
    s0x, s0y = dx - cx, dy - cy
    denom = r0x * s0y - r0y * s0x
    if abs(denom) > 1e-12:  # non parallèles : test d'intersection propre
        t = ((cx - ax) * s0y - (cy - ay) * s0x) / denom
        u = ((cx - ax) * r0y - (cy - ay) * r0x) / denom
        if -1e-12 <= t <= 1.0 + 1e-12 and -1e-12 <= u <= 1.0 + 1e-12:
            return 0.0
    return min(
        _point_segment_dist_sq(cx, cy, ax, ay, bx, by),
        _point_segment_dist_sq(dx, dy, ax, ay, bx, by),
        _point_segment_dist_sq(ax, ay, cx, cy, dx, dy),
        _point_segment_dist_sq(bx, by, cx, cy, dx, dy),
    )


def _segment_hits_hex(
    ax: float, ay: float, bx: float, by: float,
    corners: Sequence[Tuple[float, float]], cx: float, cy: float, clearance: float,
) -> bool:
    """True si le segment [A,B] épaissi de `clearance` heurte la cellule.

    `clearance <= 0` : intérieur strict (LoS-ray). `clearance > 0` : capsule — bloqué
    si la distance segment↔hexagone est < clearance.
    """
    if clearance <= _SEG_TOL:
        return _segment_crosses_hex_interior(ax, ay, bx, by, corners, cx, cy)
    if _segment_crosses_hex_interior(ax, ay, bx, by, corners, cx, cy):
        return True
    thr_sq = (clearance - _SEG_TOL) ** 2
    for i in range(6):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 6]
        if _seg_seg_dist_sq(ax, ay, bx, by, x1, y1, x2, y2) < thr_sq:
            return True
    return False


def segment_clear(
    ax: float, ay: float, bx: float, by: float,
    obstacles: Set[Tuple[int, int]], clearance: float = 0.0,
) -> bool:
    """True si aucune cellule bloquante ne coupe le segment [A,B] (épaissi de `clearance`).

    `obstacles` : cellules (col,row) bloquantes (murs + ennemis/amis/EZ selon toggles).
    Bâtit un index spatial à la volée ; pour des appels répétés (le champ), préférer
    `_build_obstacle_index` + `_segment_clear_indexed` (index bâti une seule fois).
    """
    if not obstacles:
        return True
    bs = _obstacle_bucket_size(clearance)
    return _segment_clear_indexed(ax, ay, bx, by, bs, _build_obstacle_index(obstacles, bs), clearance)


def obstacles_touching_disc(
    obstacles: AbstractSet[Tuple[int, int]], start: Tuple[int, int], radius: float
) -> Set[Tuple[int, int]]:
    """Obstacles dont l'HEXAGONE est déjà chevauché par le disque du socle posé en ``start``.

    Alimente ``geodesic_field(contact_obstacles=...)``. Pendant STATIONNAIRE du test de segment
    (``_segment_hits_hex`` sur un segment dégénéré) : même géométrie, donc un obstacle « au
    contact » ici est exactement celui qui, sinon, refuserait les six premiers pas.
    """
    if not obstacles or radius <= 0.0:
        return set()
    sx, sy = _hex_center(*start)
    reach_sq = (radius + _HEX_CIRCUMRADIUS) ** 2
    touching: Set[Tuple[int, int]] = set()
    for oc, orr in obstacles:
        ox, oy = _hex_center(int(oc), int(orr))
        if (ox - sx) ** 2 + (oy - sy) ** 2 > reach_sq:
            continue
        if disc_overlaps_polygon(sx, sy, radius, _hex_corners_at(ox, oy)):
            touching.add((int(oc), int(orr)))
    return touching


def geodesic_field(
    start: Tuple[int, int],
    board_cols: int,
    board_rows: int,
    obstacles: Set[Tuple[int, int]],
    budget: float,
    clearance: float = 0.0,
    contact_obstacles: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> Dict[Tuple[int, int], float]:
    """Distance géodésique any-angle de `start` à chaque cellule atteignable dans `budget`.

    Lazy Theta* en flood (Dijkstra + rattachement d'un nœud à l'ANCÊTRE de son voisin si
    la ligne de vue est dégagée → coût = vraie distance euclidienne, chemins à angle libre).

    - `board_cols`/`board_rows` : bornes du plateau (une cellule est libre si dans les bornes
      et pas dans `obstacles` — pas de set plein board à matérialiser).
    - `obstacles` : cellules bloquantes (voir `segment_clear`).
    - `budget` : distance max en unités `_hex_center` (= MOVE_subhex × ENGAGEMENT_NORM_HEX_WIDTH).
    - `clearance` : rayon de socle (règle 03). 0 = robot-point.
    - `contact_obstacles` : obstacles que le socle chevauche DÉJÀ au départ. Ils bloquent encore
      leurs propres cases (on ne les traverse pas) mais ne sont plus DILATÉS de `clearance`, et
      SEULEMENT pour les pas qui partent de `start`.

    Pourquoi `contact_obstacles`. La garde du départ est une appartenance de case
    (`start in obstacles`), donc cette fonction suppose que le socle de départ ne chevauche aucun
    hexagone d'obstacle. Pour les murs, `socle_blocked_anchor_cells` le garantit désormais côté
    placement. Pour les obstacles MOBILES, non : le contact socle à socle avec un ennemi est
    l'issue NORMALE d'une charge, et on ne peut pas l'interdire. Sans cette distinction, tout
    segment partant du départ passe dans la clairance de l'ennemi au contact — les six directions
    sont refusées et l'unité ne peut plus faire son Fall Back (mesuré : 0 destination au contact,
    1277 avec l'exception). La règle 09.07 ne permet de TRAVERSER les figurines ennemies que sous
    Desperate Escape ; garder leurs cases bloquantes préserve exactement cela.

    La borne « pas partant de `start` » est le cœur du raisonnement : elle dit « ce sur quoi je
    suis déjà posé ne peut pas m'empêcher de partir », pas « cet ennemi ne me gêne plus de la
    partie ». Sans elle, un mobile flanqué de deux ennemis pourrait, plus loin dans le champ, se
    faufiler ENTRE eux en chevauchant les deux socles. Un pas vaut ~1,5 unité-norme et le contact
    n'excède le seuil que de moins que ça : après le premier pas, la clairance pleine est
    satisfaite d'elle-même.

    Retourne {cellule: distance}. Une seule passe (champ complet), pas point-à-point.
    Sur-estime légèrement (lazy Theta* quasi-optimal) → ne triche jamais vs la règle 03.
    """
    if start in obstacles:
        raise ValueError(f"geodesic_field: start {start} est un obstacle")
    bs = _obstacle_bucket_size(clearance)
    # Élagage lossless : un obstacle dont le centre est au-delà de ``budget + clearance + 4·circumradius``
    # du départ ne peut bloquer aucun segment testé. Preuve : tout point d'un segment (ancre→voisin) est
    # à ≤ budget + pas_hex du départ (norme convexe, max aux extrémités ; ancre/voisin atteignables donc
    # à ≤ budget euclidien ≤ budget géodésique) ; un mur bloque à ≤ clearance + circumradius de ce point.
    # 4·circumradius couvre pas_hex (≤ 2·circ) + extent mur (circ) + marge. Retire les murs hors zone
    # atteignable → index plus petit, résultat identique.
    _gf_sx, _gf_sy = _hex_center(*start)
    _gf_reach = budget + (clearance if clearance > 0.0 else 0.0) + 4.0 * _HEX_CIRCUMRADIUS
    idx = _build_obstacle_index(obstacles, bs, center=(_gf_sx, _gf_sy), reach_sq=_gf_reach * _gf_reach)
    # `idx_far` = tout sauf le contact, dilaté normalement ; `idx_contact` = le contact, à
    # clairance NULLE. Un pas partant de `start` doit franchir les deux : « clairance pleine
    # partout, sauf sur ce que le socle chevauche déjà, qui reste infranchissable ».
    _gf_contact = frozenset(contact_obstacles) & obstacles if contact_obstacles else frozenset()
    bs0 = _obstacle_bucket_size(0.0)
    if _gf_contact:
        idx_far = _build_obstacle_index(
            obstacles - _gf_contact, bs,
            center=(_gf_sx, _gf_sy), reach_sq=_gf_reach * _gf_reach,
        )
        idx_contact = _build_obstacle_index(set(_gf_contact), bs0)
    else:
        idx_far, idx_contact = idx, {}
    g: Dict[Tuple[int, int], float] = {start: 0.0}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {start: start}
    pq: List[Tuple[float, Tuple[int, int]]] = [(0.0, start)]
    closed: Set[Tuple[int, int]] = set()

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in closed:
            continue
        closed.add(cur)
        cx, cy = _hex_center(*cur)
        par = parent[cur]
        px, py = _hex_center(*par)
        g_par, g_cur = g[par], g[cur]
        for nb in get_neighbors(*cur):
            nc, nr = nb
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            if nb in obstacles or nb in closed:
                continue
            nx, ny = _hex_center(nc, nr)
            # Rattachement à l'ancêtre si LoS dégagé (cœur de Theta*). L'exception de CONTACT ne
            # vaut que pour les pas partant de `start` : au-delà, le mobile n'est plus posé sur
            # l'obstacle. Sans `idx_contact`, la boucle est bit-identique à l'originale.
            if _segment_clear_indexed(px, py, nx, ny, bs, idx, clearance) or (
                idx_contact and par == start
                and _segment_clear_indexed(px, py, nx, ny, bs, idx_far, clearance)
                and _segment_clear_indexed(px, py, nx, ny, bs0, idx_contact, 0.0)
            ):
                anchor, axr, ayr, base = par, px, py, g_par
            elif (
                clearance <= _SEG_TOL
                or _segment_clear_indexed(cx, cy, nx, ny, bs, idx, clearance)
                or (
                    idx_contact and cur == start
                    and _segment_clear_indexed(cx, cy, nx, ny, bs, idx_far, clearance)
                    and _segment_clear_indexed(cx, cy, nx, ny, bs0, idx_contact, 0.0)
                )
            ):
                # Raccourci ancêtre bloqué → pas adjacent cur→nb, testé à la CAPSULE : à
                # `clearance>0` un socle ne peut ni transiter ni se centrer sur `nb` s'il
                # chevauche un mur (couvre goulot + corner-cutting). Court-circuit à
                # `clearance<=0` : le gate est prouvé no-op (oval/point/gym-hex) → zéro surcoût.
                anchor, axr, ayr, base = cur, cx, cy, g_cur
            else:
                continue  # nb inatteignable via cur (mur trop proche) ; re-proposé par un autre voisin
            cand = base + math.hypot(nx - axr, ny - ayr)
            if cand <= budget + _SEG_TOL and cand < g.get(nb, math.inf):
                g[nb] = cand
                parent[nb] = anchor
                heapq.heappush(pq, (cand, nb))
    return g


def geodesic_field_multi_source(
    starts: Dict[Tuple[int, int], float],
    board_cols: int,
    board_rows: int,
    obstacles: Set[Tuple[int, int]],
    budget: float,
    clearance: float = 0.0,
    contact_obstacles: Optional[AbstractSet[Tuple[int, int]]] = None,
    contact_start: Optional[Tuple[int, int]] = None,
) -> Dict[Tuple[int, int], float]:
    """Variante MULTI-SOURCE de ``geodesic_field`` : plusieurs départs, chacun avec sa distance
    initiale ``starts[cell]``. Une seule passe couvre toutes les sources (Dijkstra classique à
    fronts multiples) → évite de relancer un champ single-source par source (perf : O(1) passe au
    lieu de O(sources) passes). Utilisé pour le mouvement multi-niveaux (entrées d'étage seedées
    en bloc). ``budget`` borne la distance TOTALE (init + trajet). Sources dans ``obstacles`` ignorées.

    ``contact_obstacles`` / ``contact_start`` : même rôle et même contrat que dans
    ``geodesic_field``. ``contact_start`` désigne, parmi les sources, la position RÉELLE du mobile
    — l'exception ne vaut que pour les pas qui en partent, jamais depuis une entrée d'étage seedée
    par un portail. Obligatoire dès que ``contact_obstacles`` est fourni : le déduire serait une
    supposition sur l'appelant.

    Retourne ``{cellule: distance_totale}`` — chaque source est sa propre ancre (any-angle depuis elle).
    """
    bs = _obstacle_bucket_size(clearance)
    _gm_contact = frozenset(contact_obstacles) & obstacles if contact_obstacles else frozenset()
    if _gm_contact and contact_start is None:
        raise ValueError(
            "geodesic_field_multi_source: contact_obstacles exige contact_start "
            "(la position RÉELLE du mobile parmi les sources)"
        )
    idx = _build_obstacle_index(obstacles, bs)
    bs0 = _obstacle_bucket_size(0.0)
    if _gm_contact:
        idx_far = _build_obstacle_index(obstacles - _gm_contact, bs)
        idx_contact = _build_obstacle_index(set(_gm_contact), bs0)
    else:
        idx_far, idx_contact = idx, {}
    g: Dict[Tuple[int, int], float] = {}
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}
    pq: List[Tuple[float, Tuple[int, int]]] = []
    for s, d0 in starts.items():
        if s in obstacles or d0 > budget + _SEG_TOL:
            continue
        if d0 < g.get(s, math.inf):
            g[s] = d0
            parent[s] = s
            heapq.heappush(pq, (d0, s))
    closed: Set[Tuple[int, int]] = set()

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in closed:
            continue
        closed.add(cur)
        cx, cy = _hex_center(*cur)
        par = parent[cur]
        px, py = _hex_center(*par)
        g_par, g_cur = g[par], g[cur]
        for nb in get_neighbors(*cur):
            nc, nr = nb
            if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                continue
            if nb in obstacles or nb in closed:
                continue
            nx, ny = _hex_center(nc, nr)
            # Exception de CONTACT bornée aux pas partant de `contact_start` (cf. geodesic_field).
            if _segment_clear_indexed(px, py, nx, ny, bs, idx, clearance) or (
                idx_contact and par == contact_start
                and _segment_clear_indexed(px, py, nx, ny, bs, idx_far, clearance)
                and _segment_clear_indexed(px, py, nx, ny, bs0, idx_contact, 0.0)
            ):
                anchor, axr, ayr, base = par, px, py, g_par
            elif (
                clearance <= _SEG_TOL
                or _segment_clear_indexed(cx, cy, nx, ny, bs, idx, clearance)
                or (
                    idx_contact and cur == contact_start
                    and _segment_clear_indexed(cx, cy, nx, ny, bs, idx_far, clearance)
                    and _segment_clear_indexed(cx, cy, nx, ny, bs0, idx_contact, 0.0)
                )
            ):
                anchor, axr, ayr, base = cur, cx, cy, g_cur
            else:
                continue
            cand = base + math.hypot(nx - axr, ny - ayr)
            if cand <= budget + _SEG_TOL and cand < g.get(nb, math.inf):
                g[nb] = cand
                parent[nb] = anchor
                heapq.heappush(pq, (cand, nb))
    return g


def disc_overlaps_polygon(
    cx: float, cy: float, r: float, poly: Sequence[Tuple[float, float]]
) -> bool:
    """True si un disque (centre (cx,cy), rayon r) chevauche ou touche un polygone.

    Repère ``_hex_center`` : (cx,cy) ET les sommets ``poly`` doivent y être exprimés, cohérent
    avec ``round_base_radius_norm`` (le rayon) et avec le rendu terrain (vertices projetés par
    ``toPixelT`` côté frontend, même projection que ``_hex_center``). Pendant fig↔terrain de
    ``euclidean_edge_clearance_round_round`` (fig↔fig) : sert au test « within a terrain area »
    (règles 13.08 cover / 13.09 hidden) pour les bases rondes.

    Overlap si le centre est dans le polygone, OU si une arête est à distance <= r (contact /
    tangence compté comme « within », cohérent avec la base qui touche la zone)."""
    if len(poly) < 3:
        raise ValueError(f"disc_overlaps_polygon: polygone invalide ({len(poly)} sommets)")
    if _point_in_polygon(cx, cy, poly):
        return True
    r_sq = r * r
    n = len(poly)
    j = n - 1
    for i in range(n):
        if _point_segment_dist_sq(cx, cy, poly[j][0], poly[j][1], poly[i][0], poly[i][1]) <= r_sq:
            return True
        j = i
    return False


def disc_within_polygon(
    cx: float, cy: float, r: float, poly: Sequence[Tuple[float, float]]
) -> bool:
    """True si un disque (centre (cx,cy), rayon r) est ENTIÈREMENT inclus dans un polygone simple.

    Pendant strict de ``disc_overlaps_polygon`` : ici on exige l'inclusion totale (aucun débordement
    du bord), pour le confinement « socle rond entièrement sur l'étage » (13.06). Exact pour tout
    polygone simple (convexe OU concave) : le disque est inclus ssi son centre est dans le polygone ET
    la distance du centre à chaque arête est >= r (le bord n'entre alors jamais dans le disque).
    Tangence (distance == r) tolérée = socle qui affleure le bord sans le dépasser."""
    if len(poly) < 3:
        raise ValueError(f"disc_within_polygon: polygone invalide ({len(poly)} sommets)")
    if not _point_in_polygon(cx, cy, poly):
        return False
    r_sq = r * r
    n = len(poly)
    j = n - 1
    for i in range(n):
        if _point_segment_dist_sq(cx, cy, poly[j][0], poly[j][1], poly[i][0], poly[i][1]) < r_sq:
            return False
        j = i
    return True


def disc_within_any_polygon(
    cx: float, cy: float, r: float, polys: Sequence[Sequence[Tuple[float, float]]]
) -> bool:
    """True si le disque est entièrement inclus dans AU MOINS UN des polygones.

    Conservateur sur une union de polygones adjacents (un socle à cheval sur la frontière commune de
    deux étages distincts serait rejeté) : côté sûr, jamais de débordement autorisé. En pratique un
    étage de ruine = un seul polygone, donc exact. ``polys`` vide → False (aucune surface où tenir)."""
    return any(disc_within_polygon(cx, cy, r, p) for p in polys)
