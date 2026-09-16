"""Primitives géodésiques euclidiennes partagées MOVE / CHARGE.

La charge est un move (règle 11.04) : elle réutilise exactement le champ géodésique
any-angle du move (Étape 4), seul le budget change (2D6 au lieu de M). Ces deux helpers
sont de la géométrie PURE (aucun état de phase) — ils vivent ici pour être consommés
par ``movement_handlers`` ET ``charge_handlers`` sans duplication ni couplage inter-phase.
"""

import heapq
import math
import threading
from typing import AbstractSet, Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from engine.hex_utils import (
    _SEG_TOL, ENGAGEMENT_NORM_HEX_WIDTH, geodesic_field, geodesic_field_multi_source,
    get_neighbors, hex_distance, round_base_radius_norm, _hex_center,
    inflate_obstacles_by_footprint as _inflate_obstacles_by_footprint, obstacles_touching_disc,
)


def _euclidean_move_field(
    start_pos: Tuple[int, int],
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    obstacles_traverse: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    budget_norm: float,
) -> Dict[Tuple[int, int], float]:
    """Champ géodésique euclidien du CENTRE de l'ancre (règle 03.01), budget en unités-norme.

    - Socle **rond** : clearance continue = rayon du socle (option A Minkowski), obstacles bruts.
    - Socle **non-rond** (oval/square) : clearance=0 + obstacles dilatés par l'empreinte discrète
      orientée (``_inflate_obstacles_by_footprint``) → garde l'orientation.
    Round et non-round partagent la MÊME primitive → pool d'ancre (preview) et model pool (commit)
    restent cohérents pour toutes les formes.
    """
    if base_shape == "round":
        # Obstacles que le socle chevauche DÉJÀ au départ (contact de mêlée) : ils gardent leurs
        # cases bloquantes mais ne dilatent plus, sinon aucun premier pas n'existe — cf.
        # ``geodesic_field``. Sur socle NON ROND la question ne se pose pas : la dilatation y est
        # discrète (empreinte ∩ obstacles), et la tangence ne fait pas se recouper deux empreintes.
        radius = round_base_radius_norm(base_size)
        return geodesic_field(
            start_pos, board_cols, board_rows, obstacles_traverse,
            budget_norm, radius,
            contact_obstacles=obstacles_touching_disc(obstacles_traverse, start_pos, radius),
        )
    _inflated = _inflate_obstacles_by_footprint(obstacles_traverse, off_even, off_odd)
    _inflated.discard(start_pos)  # start jamais obstacle (geodesic_field lèverait sinon)
    return geodesic_field(start_pos, board_cols, board_rows, _inflated, budget_norm, 0.0)


def _euclidean_move_field_multi(
    starts: Dict[Tuple[int, int], float],
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    obstacles_traverse: Set[Tuple[int, int]],
    board_cols: int,
    board_rows: int,
    budget_norm: float,
    contact_obstacles: Optional[AbstractSet[Tuple[int, int]]] = None,
    contact_start: Optional[Tuple[int, int]] = None,
) -> Dict[Tuple[int, int], float]:
    """Version MULTI-SOURCE de ``_euclidean_move_field`` (départs multiples avec distance initiale).

    Même gestion socle rond (clearance = rayon) / non-rond (obstacles dilatés par empreinte). Une
    seule passe couvre toutes les sources → indispensable pour le mouvement multi-niveaux (seeder
    toutes les entrées d'étage d'un coup au lieu de relancer un champ par entrée).
    """
    if base_shape == "round":
        return geodesic_field_multi_source(
            starts, board_cols, board_rows, obstacles_traverse,
            budget_norm, round_base_radius_norm(base_size),
            contact_obstacles=contact_obstacles, contact_start=contact_start,
        )
    _inflated = _inflate_obstacles_by_footprint(obstacles_traverse, off_even, off_odd)
    for s in starts:
        _inflated.discard(s)
    return geodesic_field_multi_source(starts, board_cols, board_rows, _inflated, budget_norm, 0.0)


def multilevel_target_within_straight_bound(
    start_pos: Tuple[int, int],
    start_level: int,
    target_levels: Iterable[int],
    floor_hexes_by_level: Mapping[int, AbstractSet[Tuple[int, int]]],
    height_by_level: Mapping[int, float],
    budget_norm: float,
    ground_is_hex: bool = False,
) -> bool:
    """Un niveau cible peut-il porter AU MOINS une cellule dans ``budget_norm`` ? Borne INFÉRIEURE,
    sans Dijkstra — sert de pré-check aux champs multi-niveaux par-figurine.

    Toute distance du champ (``reachable_multilevel_field``) est une somme de segments any-angle
    et de portails, chacun un ``hypot`` entre centres d'hexes, plus les coûts verticaux
    ``|height(L+1) − height(L)|`` des portails traversés. Par inégalité triangulaire la part
    horizontale vaut au moins la ligne droite départ→cellule, et la part verticale au moins
    ``|height(cible) − height(départ)|``. Une cellule dont cette borne dépasse
    ``budget_norm + _SEG_TOL`` (la tolérance d'admission du Dijkstra, cf. ``geodesic_field``) ne
    peut donc PAS figurer dans le champ ; si aucune cellule d'aucun niveau cible ne passe, le
    champ rendu serait vide sur ces niveaux — et le calcul peut être sauté sans rien changer.

    ``ground_is_hex`` : la passe de DÉPART est un champ hex par cellule injecté en
    ``precomputed_start_field`` (métrique hex du gym, ``ascent_field_for_model``), coûtée
    ``ENGAGEMENT_NORM_HEX_WIDTH × pas``. La ligne droite n'en est PLUS une borne inférieure :
    ``1,5 × pas`` vaut au plus la distance euclidienne, et jusqu'à 15 % de moins en colonne
    (√3 par pas vers le sud). La borne devient ``1,5 × hex_distance(départ, cellule)`` : chaque
    segment any-angle ou portail vaut au moins ``1,5 × hex_distance`` de ses extrémités (le pas
    le plus court du repère ``_hex_center`` est 1,5, minimum atteint sur une ligne est-ouest), la
    passe hex exactement ``1,5 × pas`` avec ``pas >= hex_distance``, et ``hex_distance`` est une
    métrique — l'inégalité triangulaire enchaîne les segments comme pour la ligne droite. Cette
    borne est plus lâche que la ligne droite (elle écarte moins de champs), pas moins sûre. La
    tolérance ``_SEG_TOL`` reste : la passe d'ÉTAGE est toujours any-angle et admet à
    ``budget_norm + _SEG_TOL``.

    Le SOL (niveau 0) parmi les cibles vaut toujours True : il n'a pas d'empreinte finie à
    borner, on ne cherche pas à le prouver inatteignable. Une cible sans plancher n'apporte
    aucune cellule. Mesures : sous la borne LIGNE DROITE (sol any-angle, HEAD daf17143b,
    ``refactor_fingerprint.py --episodes 8``), 305 des 675 champs de montée n'atteignaient aucune
    cible, pour 34 % du temps de ces champs ; sous la borne HEX (2026-09-16, chemin de
    ``scripts/bench_env_step.py``, 200 pas, x1_long bots, graine 42, les deux bornes évaluées
    sur les MÊMES 191 appels), 54 champs sortent tôt contre 65 sous la ligne droite — 11 champs
    de plus calculés, chacun une passe d'étage de ~7 ms, contre 0 passe any-angle au sol.
    """
    if any(int(lv) == 0 for lv in target_levels):
        return True
    sx, sy = _hex_center(start_pos[0], start_pos[1])
    h_start = float(height_by_level[int(start_level)])
    limit = budget_norm + _SEG_TOL
    for lv in target_levels:
        cells = floor_hexes_by_level.get(int(lv))  # get allowed (cible sans plancher = aucune cellule)
        if not cells:
            continue
        vc = abs(float(height_by_level[int(lv)]) - h_start)
        if vc > limit:
            continue
        for c, r in cells:
            if ground_is_hex:
                horizontal = ENGAGEMENT_NORM_HEX_WIDTH * hex_distance(
                    start_pos[0], start_pos[1], c, r
                )
            else:
                hx, hy = _hex_center(c, r)
                horizontal = math.hypot(hx - sx, hy - sy)
            if horizontal + vc <= limit:
                return True
    return False


# Portails mémoïsés PAR VALEUR : (planchers, hauteurs, plateau, flag) → index. Statiques par
# partie (le terrain ne bouge pas), ils étaient reconstruits à CHAQUE champ par-figurine
# (675 fois sur 8 épisodes, 2,0 s sous cProfile). La clé porte les frozensets d'étage eux-mêmes
# (hash mis en cache par l'objet, rendu par ``floor_hexes_at_level``), jamais un ``id()`` — un
# identifiant recyclé après GC servirait les portails d'un autre terrain. Borné et verrouillé
# comme ``_FLOOR_INDEX_CACHE`` (API Flask multi-threads). L'index rendu est PARTAGÉ : lecture seule.
_LEVEL_TRANSITIONS_CACHE: Dict[Any, Dict[Tuple[int, int, int], List[Tuple[int, int, int, float]]]] = {}
_LEVEL_TRANSITIONS_CACHE_MAX = 8
_LEVEL_TRANSITIONS_LOCK = threading.Lock()


def _build_level_transitions(
    floor_hexes_by_level: Mapping[int, AbstractSet[Tuple[int, int]]],
    height_by_level: Dict[int, float],
    board_cols: int,
    board_rows: int,
    ignore_vertical_cost: bool = False,
) -> Dict[Tuple[int, int, int], List[Tuple[int, int, int, float]]]:
    """Portails de ``_compute_level_transitions``, mémoïsés par VALEUR des entrées (cf. le cache
    ci-dessus). Même signature, même résultat ; l'index rendu ne doit pas être muté."""
    key = (
        tuple(sorted((int(lv), frozenset(fh)) for lv, fh in floor_hexes_by_level.items())),
        tuple(sorted((int(lv), float(h)) for lv, h in height_by_level.items())),
        int(board_cols), int(board_rows), bool(ignore_vertical_cost),
    )
    with _LEVEL_TRANSITIONS_LOCK:
        cached = _LEVEL_TRANSITIONS_CACHE.get(key)  # get allowed (terrain pas encore vu)
        if cached is not None:
            return cached
    index = _compute_level_transitions(
        floor_hexes_by_level, height_by_level, board_cols, board_rows, ignore_vertical_cost
    )
    with _LEVEL_TRANSITIONS_LOCK:
        _LEVEL_TRANSITIONS_CACHE[key] = index
        if len(_LEVEL_TRANSITIONS_CACHE) > _LEVEL_TRANSITIONS_CACHE_MAX:
            # Un dict Python conserve l'ordre d'insertion : la première clé est la plus ancienne.
            del _LEVEL_TRANSITIONS_CACHE[next(iter(_LEVEL_TRANSITIONS_CACHE))]
    return index


def _compute_level_transitions(
    floor_hexes_by_level: Mapping[int, AbstractSet[Tuple[int, int]]],
    height_by_level: Dict[int, float],
    board_cols: int,
    board_rows: int,
    ignore_vertical_cost: bool = False,
) -> Dict[Tuple[int, int, int], List[Tuple[int, int, int, float]]]:
    """Portails de transition entre niveaux CONSÉCUTIFS (L ↔ L+1), fondés sur l'archi du spike.

    On monte/descend le long du bord de l'étage supérieur (règle 13.06). Pour chaque hex ``t``
    de l'étage ``L+1``, ses hexes d'approche au niveau ``L`` sont ``t`` et ses voisins :
      - L == 0 (sol) : approche = tout hex in-bounds ;
      - L >= 1 : approche = hex appartenant à l'étage ``L``.
    Coût du portail = distance horizontale d'approche ``dist(g,t)`` + distance verticale
    ``|height(L+1) − height(L)|`` (cumulée au budget, §13.06). Portail bidirectionnel.
    ``ignore_vertical_cost`` (FLY « take to the skies », §21.03) : composante verticale nulle.

    Retour : index ``{(level, hex): [(other_level, other_hex, cost), ...]}``.
    """
    index: Dict[Tuple[int, int, int], List[Tuple[int, int, int, float]]] = {}

    def _add(a_level: int, a_hex: Tuple[int, int], b_level: int, b_hex: Tuple[int, int], cost: float) -> None:
        index.setdefault((a_level, a_hex[0], a_hex[1]), []).append((b_level, b_hex[0], b_hex[1], cost))

    upper_levels = sorted(l for l in floor_hexes_by_level if l >= 1)
    for upper in upper_levels:
        lower = upper - 1
        if lower >= 1 and lower not in floor_hexes_by_level:
            continue  # niveau intermédiaire manquant : pas d'empilement contigu
        vcost = 0.0 if ignore_vertical_cost else abs(float(height_by_level[upper]) - float(height_by_level[lower]))
        lower_hexes = floor_hexes_by_level.get(lower) if lower >= 1 else None  # None = sol (tout in-bounds)
        for t in floor_hexes_by_level[upper]:
            tx, ty = _hex_center(t[0], t[1])
            for g in [t] + list(get_neighbors(t[0], t[1])):
                gc, gr = g
                # `lower_hexes is None` <=> `lower == 0` (le sol, ou tout hex in-bounds est
                # valide) : c'est ainsi qu'il est construit trois lignes plus haut. Tester
                # l'ensemble plutot que le niveau donne exactement le meme branchement, mais
                # rend le `not in` prouvable — l'ignore precedent taisait un `in` sur Optional.
                if lower_hexes is None:
                    if gc < 0 or gr < 0 or gc >= board_cols or gr >= board_rows:
                        continue
                elif g not in lower_hexes:
                    continue
                gx, gy = _hex_center(gc, gr)
                cost = math.hypot(tx - gx, ty - gy) + vcost
                _add(lower, g, upper, t, cost)
                _add(upper, t, lower, g, cost)
    return index


def reachable_multilevel_field(
    start_pos: Tuple[int, int],
    start_level: int,
    base_shape: str,
    base_size: Any,
    off_even: Tuple[Tuple[int, int], ...],
    off_odd: Tuple[Tuple[int, int], ...],
    board_cols: int,
    board_rows: int,
    obstacles_by_level: Dict[int, Set[Tuple[int, int]]],
    floor_hexes_by_level: Mapping[int, AbstractSet[Tuple[int, int]]],
    height_by_level: Dict[int, float],
    budget_norm: float,
    allow_vertical: bool = True,
    ignore_vertical_cost: bool = False,
    precomputed_start_field: Optional[Dict[Tuple[int, int], float]] = None,
) -> Dict[Tuple[int, int, int], float]:
    """Champ géodésique MULTI-NIVEAUX (mouvement vertical, chantier 3, archi validée par le spike).

    Dijkstra sur nœuds ``(col, row, level)`` : chaque niveau est développé par le VRAI champ
    any-angle planaire (``_euclidean_move_field``, réutilisé tel quel), les niveaux consécutifs
    étant reliés par les portails de ``_build_level_transitions`` (coût horizontal d'approche +
    vertical cumulé, §13.06). Distances non-croissantes bornées par ``budget_norm`` → terminaison.

    - ``obstacles_by_level[level]`` : obstacles de traversée du plan de ce niveau. Niveau 0 = sol
      (murs + figs du sol). Niveau >= 1 = complément du plancher (hors-étage) + figs de l'étage :
      le champ ne peut alors sortir de l'empreinte, et la clearance du socle interdit le débordement.
    - ``floor_hexes_by_level[level>=1]`` : hexes de chaque étage (aucune entrée pour le sol).
    - ``height_by_level`` : hauteur (unités-norme) par niveau ; le sol (0) doit valoir 0.

    Restrictions mot-clé (§2.2, appliquées par l'appelant via ces flags) :
    - ``allow_vertical=False`` (unité incapable de finir en hauteur : MOBILE/VEHICLE et tout ce qui n'a
      pas INFANTRY/BEASTS/SWARM/FLY/MONSTER, cf. ``unit_can_occupy_upper_floor``) → aucune transition :
      le champ reste sur ``start_level`` (au sol en pratique). Nuance non modélisée : un VEHICLE peut
      escalader l'EXTÉRIEUR d'une section >2" sans y finir (le modèle de niveaux ne distingue pas
      intérieur/extérieur ni sections <2") — hors périmètre, documenté dans verticalite.md.
    - ``ignore_vertical_cost=True`` (FLY « take to the skies », §21.03) → transitions à coût horizontal
      seul (le malus −2" de budget est appliqué en amont dans ``get_squad_move_budget``).

    Retour : ``{(col, row, level): distance}`` — cellules atteignables dans le budget, tous niveaux.
    PERF : chaque niveau est développé par UNE passe MULTI-SOURCE (``_euclidean_move_field_multi``,
    toutes les entrées seedées d'un coup) au lieu d'un champ single-source par entrée de transition.
    Rounds bornés par le nombre de niveaux (montée+descente), distances non-croissantes → terminaison.
    """
    if start_level not in height_by_level:
        raise KeyError(f"reachable_multilevel_field: start_level {start_level} absent de height_by_level")
    portals = (
        _build_level_transitions(
            floor_hexes_by_level, height_by_level, board_cols, board_rows, ignore_vertical_cost
        )
        if allow_vertical else {}
    )

    best: Dict[Tuple[int, int, int], float] = {}
    # Frontière de seeds par niveau : {level: {cell: dist_init}}. Départ = start_pos @ start_level.
    if precomputed_start_field is not None:
        # Le champ du niveau de départ est déjà calculé (move principal, mêmes obstacles/budget) :
        # on l'injecte directement dans ``best`` et on amorce les portails, SANS relancer
        # ``_euclidean_move_field_multi`` sur ce niveau (le poste coûteux). Les ré-expansions
        # ultérieures de ce niveau (descente via portail) restent gérées par la boucle ci-dessous,
        # mais sont quasi toujours élaguées car ``best`` contient déjà la distance directe (plus courte).
        seeds_by_level: Dict[int, Dict[Tuple[int, int], float]] = {}
        # Amorçage direct de ``best`` pour TOUTES les cellules sol atteignables (nécessaire pour élaguer
        # les ré-expansions en descente : une case déjà atteinte en direct ne sera pas recalculée).
        # Les cellules de ``precomputed_start_field`` sont uniques → affectation inconditionnelle.
        for (cc, cr), dc in precomputed_start_field.items():
            if dc <= budget_norm:
                best[(cc, cr, start_level)] = dc
        # Seeds de portail : n'itère que les entrées de portail du niveau de départ (≈ périmètre
        # d'étage), pas les milliers de cellules sol. Résultat identique (mêmes portails, mêmes coûts).
        for (plevel, pc, pr), edges in portals.items():
            if plevel != start_level:
                continue
            dc = best.get((pc, pr, start_level))
            if dc is None:
                continue
            for (nlevel, nc, nr, edge_cost) in edges:
                nd = dc + edge_cost
                if nd <= budget_norm and nd < best.get((nlevel, nc, nr), math.inf):
                    lvl_seeds = seeds_by_level.setdefault(nlevel, {})
                    if nd < lvl_seeds.get((nc, nr), math.inf):
                        lvl_seeds[(nc, nr)] = nd
    else:
        seeds_by_level = {start_level: {(start_pos[0], start_pos[1]): 0.0}}
    # Borne de rounds : chaque round propage d'un saut de niveau ; converge en O(niveaux) (garde-fou).
    max_rounds = 2 * (len(floor_hexes_by_level) + 2) + 2
    rounds = 0
    while seeds_by_level and rounds < max_rounds:
        rounds += 1
        next_seeds: Dict[int, Dict[Tuple[int, int], float]] = {}
        for level, seeds in seeds_by_level.items():
            active = {
                cell: d for cell, d in seeds.items()
                if d <= budget_norm and d < best.get((cell[0], cell[1], level), math.inf)
            }
            if not active:
                continue
            # Sortie de CONTACT : uniquement pour la passe qui part de la position réelle du
            # mobile (son niveau ET sa case). Aux passes suivantes il a franchi un portail, donc
            # il n'est plus au contact et l'exception élargirait le champ à tort.
            _contact = (
                obstacles_touching_disc(
                    obstacles_by_level.get(level, set()), start_pos,
                    round_base_radius_norm(base_size),
                )
                if base_shape == "round" and level == start_level and start_pos in active
                else None
            )
            field = _euclidean_move_field_multi(
                active, base_shape, base_size, off_even, off_odd,
                obstacles_by_level.get(level, set()), board_cols, board_rows, budget_norm,
                contact_obstacles=_contact, contact_start=start_pos if _contact else None,
            )
            for (cc, cr), dc in field.items():
                key = (cc, cr, level)
                if dc < best.get(key, math.inf):
                    best[key] = dc
                    for (nlevel, nc, nr, edge_cost) in portals.get((level, cc, cr), ()):  # get allowed
                        nd = dc + edge_cost
                        if nd <= budget_norm and nd < best.get((nlevel, nc, nr), math.inf):
                            lvl_seeds = next_seeds.setdefault(nlevel, {})
                            if nd < lvl_seeds.get((nc, nr), math.inf):
                                lvl_seeds[(nc, nr)] = nd
        seeds_by_level = next_seeds
    return best
