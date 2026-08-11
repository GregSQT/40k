"""Distance d'un hexe à l'AIRE d'un objectif (14.02), et non à son centre.

POURQUOI CE MODULE EXISTE
=========================
Un objectif est une aire de terrain entière (14.02 : « a model is within range of a terrain
objective while it is within that terrain area »), soit plusieurs milliers d'hexes sur les
scénarios réels — 2030 à 3000 pour le scénario PvE. Les décisions qui demandent « de quel
objectif suis-je le plus proche ? » réduisaient cette aire à son CENTROÏDE. Une unité posée sur
le bord d'un objectif — donc en train de le contrôler, socle dans l'aire — ressortait à une
trentaine d'hexes de « l'objectif », et pouvait en viser un autre.

Le centroïde était juste tant qu'un objectif faisait 7 hexes. Il ne l'est plus.

STRUCTURE : SEGMENTS PAR COLONNE, PUIS CARTE
============================================
Énumérer les hexes de l'aire donnerait la bonne réponse au mauvais prix (mesuré : 584 ms pour
14 000 candidats de déploiement, contre 0,4 ms au centroïde). Deux réductions successives, toutes
deux EXACTES — vérifiées par comparaison à l'énumération complète dans les tests :

1. ``_zone_column_segments`` : à colonne fixe, la distance hexagonale vaut simplement l'écart de
   ligne, donc le plus proche hexe d'une colonne est celui dont la ligne est la plus proche,
   bornée au segment. Une aire de 3000 hexes se décrit ainsi par ~50 segments (facteur 25 à 60
   mesuré sur les cinq objectifs du scénario PvE). Coût : 25 ms pour 14 000 candidats.

2. ``objective_distance_maps`` : la carte complète du plateau, une entrée par hexe et par
   objectif. 345 ms de construction, 645 Ko, puis 0,6 ms par requête de 14 000 candidats. Elle
   est rentable dès ~14 requêtes, et le scoring de déploiement en fait une par unité à placer.

CACHE PAR CONTENU, ET NON PAR ÉPISODE
=====================================
Le cache est indexé par le CONTENU des aires (leurs hexes), au niveau module, et pas sur
l'identité de la liste ``objectives`` comme le fait ``objective_hex_zones``. La raison est
l'entraînement : chaque ``reset()`` reconstruit un ``game_state``, donc une nouvelle liste, alors
que les aires du scénario sont rigoureusement les mêmes. Un cache par identité paierait les
345 ms à chaque épisode et sur chaque environnement vectorisé. Par contenu, il les paie une fois
par FORME d'objectif et pour toute la session.

Le cache est borné (``_MAX_CACHED_BOARDS``) : un entraînement multi-scénarios verrait sinon la
mémoire croître sans limite à mesure que les terrains changent.
"""

from typing import Any, Dict, List, Sequence, Set, Tuple

import numpy as np

from shared.data_validation import require_key

#: Nombre de configurations d'objectifs gardées en cache. Au-delà, la plus ancienne est jetée.
#: Une valeur haute ne coûte que de la mémoire (≈645 Ko par entrée sur un plateau 220×300), une
#: valeur basse fait repayer la construction à chaque alternance de scénario.
_MAX_CACHED_BOARDS = 8

#: {clé de contenu: (cols, rows, [carte par objectif])}. Inséré dans l'ordre d'usage.
_DISTANCE_MAP_CACHE: Dict[Any, Tuple[int, int, List["np.ndarray"]]] = {}

#: Raccourci d'IDENTITÉ devant le cache de contenu : {id(objectives): (objectives, cartes)}.
#: MESURÉ : construire la clé de contenu coûte 6 ms sur les cinq aires du scénario PvE (elle
#: hache 10 538 hexes), et cette fonction est appelée par unité et par décision de bot — le seul
#: calcul de clé coûtait donc plus cher que tout ce qu'il économisait. Dans un épisode, la liste
#: `objectives` est le MÊME objet d'un appel à l'autre : une comparaison `is` suffit et est
#: gratuite. Le cache de contenu ne sert plus qu'au changement d'épisode, où l'identité change
#: mais où les aires sont les mêmes.
#: La liste est conservée dans l'entrée et comparée par `is` : un `id()` recyclé après collecte
#: d'un ancien état ne peut pas produire de fausse correspondance.
_IDENTITY_CACHE: Dict[int, Tuple[Any, List["np.ndarray"]]] = {}

#: Épisodes vectorisés : quelques états vivent en parallèle, pas des milliers.
_MAX_IDENTITY_ENTRIES = 64


def _zone_column_segments(zone_hexes: Set[Tuple[int, int]]) -> List[Tuple[int, int, int]]:
    """Décrit une aire par ses segments verticaux contigus ``(col, row_min, row_max)``.

    Exact : à colonne fixe, deux hexes ne diffèrent que par leur ligne et la distance hexagonale
    entre eux vaut cet écart, donc borner la ligne au segment donne le plus proche hexe de cette
    colonne. Une aire non convexe (plusieurs blocs dans une même colonne) rend simplement
    plusieurs segments — aucune hypothèse de convexité n'est faite.
    """
    rows_by_col: Dict[int, List[int]] = {}
    for col, row in zone_hexes:
        rows_by_col.setdefault(int(col), []).append(int(row))
    segments: List[Tuple[int, int, int]] = []
    for col in sorted(rows_by_col):
        rows = sorted(rows_by_col[col])
        start = previous = rows[0]
        for row in rows[1:]:
            if row == previous + 1:
                previous = row
                continue
            segments.append((col, start, previous))
            start = previous = row
        segments.append((col, start, previous))
    return segments


def _cube_coordinates(cols: "np.ndarray", rows: "np.ndarray"):
    """Projection odd-q → cube, même convention que ``engine.hex_utils``."""
    x = cols
    z = rows - ((cols - (cols & 1)) >> 1)
    return x, -x - z, z


def distances_to_zone(
    cols: "np.ndarray", rows: "np.ndarray", segments: Sequence[Tuple[int, int, int]]
) -> "np.ndarray":
    """Distance hexagonale de chaque ``(col, row)`` à l'aire décrite par ``segments``.

    Vaut 0 sur les hexes de l'aire (la ligne bornée y est la ligne elle-même). Une aire sans
    segment LÈVE : une distance « infinie » servie par défaut ferait scorer tout le plateau à
    l'identique, exactement le défaut que ``_nearest_hex_distance_vec`` refuse déjà côté
    déploiement.
    """
    if len(segments) == 0:
        raise ValueError("distances_to_zone: aire d'objectif vide — aucune distance à mesurer")
    x1, y1, z1 = _cube_coordinates(cols, rows)
    best = np.full(np.shape(cols), np.iinfo(np.int64).max, dtype=np.int64)
    for col, row_min, row_max in segments:
        clamped = np.clip(rows, row_min, row_max)
        z2 = clamped - ((col - (col & 1)) >> 1)
        y2 = -col - z2
        distance = np.maximum(
            np.maximum(np.abs(x1 - col), np.abs(y1 - y2)), np.abs(z1 - z2)
        )
        np.minimum(best, distance, out=best)
    return best


def _cache_key(zones: Sequence[Tuple[Any, Set[Tuple[int, int]]]], cols: int, rows: int) -> Any:
    """Clé de CONTENU : mêmes aires sur le même plateau = même carte, quel que soit l'épisode."""
    return (
        cols,
        rows,
        tuple(
            (str(objective_id), frozenset(zone_hexes))
            for objective_id, zone_hexes in zones
        ),
    )


def objective_distance_maps(game_state: Dict[str, Any]) -> List["np.ndarray"]:
    """Carte ``[col, row] → distance à l'aire``, une par objectif, DANS L'ORDRE de ``objectives``.

    L'ordre est le même contrat que ``objective_hex_zones`` : les appelants indexent la liste par
    numéro de zone. Les cartes sont en ``int16`` — la plus grande distance possible sur un
    plateau est de l'ordre de quelques centaines d'hexes.
    """
    from engine.game_state import objective_hex_zones

    objectives = require_key(game_state, "objectives")
    identity_entry = _IDENTITY_CACHE.get(id(objectives))  # get allowed (premier passage)
    if identity_entry is not None and identity_entry[0] is objectives:
        return identity_entry[1]

    zones = objective_hex_zones(game_state)
    if not zones:
        return []
    # Dimensions du plateau : `config_loader.get_board_size()`, la MÊME source que la
    # rasterisation des terrains et des zones d'objectif (`game_state._load_terrain_areas_*`).
    # Et non `game_state["board_cols"]` : ce serait une seconde source pour la même grandeur, et
    # surtout une exigence nouvelle imposée à tout état de jeu construit à la main — le rendant
    # dépendant d'une clé que seul ce module lirait.
    from config_loader import get_board_size

    board_cols, board_rows = get_board_size()
    board_cols = int(board_cols)
    board_rows = int(board_rows)

    key = _cache_key(zones, board_cols, board_rows)
    cached = _DISTANCE_MAP_CACHE.get(key)  # get allowed (premier passage)
    if cached is not None:
        # Réinsertion : la clé la plus récemment utilisée devient la dernière à être évincée.
        _DISTANCE_MAP_CACHE[key] = _DISTANCE_MAP_CACHE.pop(key)
        maps = cached[2]
    else:
        all_cols, all_rows = np.meshgrid(
            np.arange(board_cols), np.arange(board_rows), indexing="ij"
        )
        flat_cols = all_cols.ravel()
        flat_rows = all_rows.ravel()
        maps = [
            distances_to_zone(flat_cols, flat_rows, _zone_column_segments(zone_hexes))
            .astype(np.int16)
            .reshape(board_cols, board_rows)
            for _objective_id, zone_hexes in zones
        ]
        _DISTANCE_MAP_CACHE[key] = (board_cols, board_rows, maps)
        while len(_DISTANCE_MAP_CACHE) > _MAX_CACHED_BOARDS:
            _DISTANCE_MAP_CACHE.pop(next(iter(_DISTANCE_MAP_CACHE)))

    _IDENTITY_CACHE[id(objectives)] = (objectives, maps)
    while len(_IDENTITY_CACHE) > _MAX_IDENTITY_ENTRIES:
        _IDENTITY_CACHE.pop(next(iter(_IDENTITY_CACHE)))
    return maps


def distance_to_objective(game_state: Dict[str, Any], zone_index: int, col: int, row: int) -> int:
    """Distance d'un hexe à l'aire de l'objectif ``zone_index`` (0 s'il est dedans)."""
    maps = objective_distance_maps(game_state)
    if not 0 <= zone_index < len(maps):
        raise IndexError(
            f"distance_to_objective: zone {zone_index} hors des {len(maps)} objectifs du scénario"
        )
    distance_map = maps[zone_index]
    if not (0 <= col < distance_map.shape[0] and 0 <= row < distance_map.shape[1]):
        raise ValueError(
            f"distance_to_objective: hexe ({col},{row}) hors plateau "
            f"{distance_map.shape[0]}x{distance_map.shape[1]}"
        )
    return int(distance_map[col, row])


def nearest_objective_zone(game_state: Dict[str, Any], col: int, row: int) -> int:
    """Index de l'objectif dont l'AIRE est la plus proche de ``(col, row)``.

    Égalité tranchée par le plus petit index : un ordre stable évite qu'une décision d'agent
    dépende de l'ordre de parcours d'un dictionnaire. Aucun objectif au scénario → 0, valeur que
    rendait déjà ``macro_intents.get_nearest_objective_zone`` dans ce cas.
    """
    maps = objective_distance_maps(game_state)
    if not maps:
        return 0
    best_index = 0
    best_distance = None
    for index, distance_map in enumerate(maps):
        distance = int(distance_map[col, row])
        if best_distance is None or distance < best_distance:
            best_index = index
            best_distance = distance
    return best_index
