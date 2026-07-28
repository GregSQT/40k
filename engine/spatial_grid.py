#!/usr/bin/env python3
"""engine/spatial_grid.py - Geometrie de la grille egocentrique de mouvement.

SOURCE UNIQUE du mapping grille<->hex. Partagee par les trois couches de la refonte
(Documentation/Implementation/A_faire/move_action_space_spatial_rework.md) :

  - T1 `engine/observation_builder.py`          : rasterisation des canaux (`GRID_CHANNELS`)
  - T2 `engine/phase_handlers/shared_utils.py`  : projection du pool BFS -> masque
  - T3 `engine/action_decoder.py`               : cellule choisie -> destination d'ancre

Si ces trois couches recalculaient le mapping chacune de leur cote, une meme cellule ne
designerait pas le meme hex des trois cotes : l'agent verrait un mur en (gx,gy), le masque
autoriserait (gx,gy) et le decoder y enverrait l'escouade ailleurs. D'ou le module unique.

Geometrie (spec §6.2 / §10.2 / §10.9)
------------------------------------
- Mode UNIQUE `budget_normalized` : la demi-etendue de la grille est le budget Advance
  MAXIMAL de l'escouade (`M + 6" x inches_to_subhex`). La grille couvre donc toujours le
  disque atteignable, quelle que soit l'echelle du board -> plus rien dans l'action ne
  depend de `inches_to_subhex` (c'est l'argument central de la refonte).
- Demi-etendue indexee sur le jet d'Advance MAXIMAL, jamais sur le jet effectivement tire :
  la geometrie doit etre identique entre obs/masque/decoder ET stable d'un step a l'autre.
  L'indexer sur le D6 ferait respirer l'echelle spatiale au gre du jet et detruirait la
  semantique apprise par le CNN. Le pool reel (budget `M + jet`) est toujours strictement
  inclus ; les cellules au-dela sont simplement masquees a 0.
- Rasterisation GEOMETRIQUE (§10.9) : les hexes sont projetes via leurs centres euclidiens
  (`_hex_center`), pas via leurs indices offset -> pas d'anisotropie de parite.

Aucun repli, aucune valeur par defaut masquant une erreur.
"""

import math
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

import numpy as np

from engine.hex_utils import _hex_center

# --- Forme de la grille (spec §10.1 ; 7e canal : V11 §9.10 ; 8e/9e : V11 §0.32) ---
GRID_SIZE = 32
GRID_CELL_COUNT = GRID_SIZE * GRID_SIZE  # 1024 cellules = taille de la tete spatiale
GRID_CHANNELS = 9

# Canaux (spec §10.1)
GRID_CH_WALL = 0       # murs / obstacles infranchissables
GRID_CH_ALLY = 1       # occupation alliee
GRID_CH_ENEMY = 2      # occupation ennemie
GRID_CH_EZ = 3         # zone d'engagement ennemie
GRID_CH_OBJECTIVE = 4  # objectifs
GRID_CH_LEVEL = 5      # niveau (etages)
# Cases qui DONNENT le benefice du couvert (regle 13.08 : « within a terrain area ») — hexes
# des terrain areas, exactement l ensemble que le moteur peint en cover_cells. Le drapeau
# « a couvert » du vecteur dit SI l escouade est couverte ; ce canal dit OU aller se couvrir,
# case par case : sans lui la grille ne distinguait pas un terrain couvrant d un simple
# bloqueur de vue (V11 §5bis.4 / §9.10).
GRID_CH_COVER = 6

# V11 §0.32 T-L. La grille est EGOCENTRIQUE : elle est centree sur l escouade active, sa
# demi-etendue est SON budget et chaque cellule jouable est une destination de SON bloc rigide.
# Peindre cette escouade dans `GRID_CH_ALLY` avec toutes les autres unites amies la rendait
# indistinguable d une escouade amie voisine — l agent ne pouvait pas lire la FORME de son propre
# bloc (celle-la meme qui est translatee a l execution). `GRID_CH_ALLY` ne porte donc plus que les
# AUTRES escouades du joueur actif.
GRID_CH_SELF = 7

# V11 §0.32 T-K. Cout GEODESIQUE (distance de CHEMIN du BFS, pas la distance a vol d oiseau) de
# chaque cellule du pool de move, encode par `normalize_move_costs` : dans [0,1], et surtout avec
# le seuil normal/advance a `MOVE_COST_ADVANCE_THRESHOLD` EXACTEMENT, pour toute unite et toute
# echelle de board.
#
# POURQUOI ce canal : c est ce cout qui arbitre normal vs advance (`classify_squad_move_type`), et
# un advance interdit le tir non-[ASSAULT] et la charge. Il etait deja calcule a chaque activation
# POUR LE MASQUE, puis jete : l agent voyait les murs bruts et devait refaire le BFS mentalement
# pour savoir si la cellule visee lui coutait son tir.
#
# 0 hors du pool. L ATTEIGNABILITE reste portee par le masque d action (elle n est PAS dupliquee
# ici) : une cellule a cout 0 est soit hors pool, soit l origine meme de l escouade.
GRID_CH_MOVE_COST = 8

# Valeur du canal `GRID_CH_MOVE_COST` au budget de move NORMAL (`M`) — la frontiere normal/advance.
#
# POURQUOI un seuil CONSTANT plutot qu une simple division par la demi-etendue. La grille passe
# SEULE dans le CNN (`ai/spatial_extractor.py` : `self.cnn(observations["grid"])`) et le vecteur
# n est concatene qu APRES l aplatissement. Un canal `cout / demi-etendue` placerait la frontiere
# a `M / (M + 6" x i2s)` = `MOVE / (MOVE + 6)`, soit 0,40 (MOVE 4") a 0,70 (MOVE 14") selon
# l unite : pour savoir si une cellule lui coute son tir, le CNN devrait croiser le canal avec le
# MOVE, qui ne lui parvient jamais. L information la plus utile du canal serait illisible la ou
# elle est produite — et le serait plus encore depuis la tete de move (§0.32 T-G, LIVREE), qui
# score chaque cellule par une conv 1x1 sur sa colonne de features CNN, donc LOCALEMENT.
MOVE_COST_ADVANCE_THRESHOLD = 0.5

# Tolerance d ARRONDI sur les bornes des couts geodesiques, dans `normalize_move_costs`. Tres
# au-dessus de l erreur flottante accumulee (~1e-15 sur une somme de pas de `2/sqrt(3)`) et tres
# en dessous d un pas hex (~1,15) : une vraie incoherence pool/grille ne peut pas s y cacher.
_COST_BOUND_TOLERANCE = 1e-6

# Distance centre-a-centre de deux hexes voisins, dans l'espace de `_hex_center`
# (hex_radius=1.0, flat-top). VERIFIE : uniforme sur les 6 voisins et les 2 parites.
#
# NE PAS confondre avec `ENGAGEMENT_NORM_HEX_WIDTH` (=1.5), qui est le facteur
# subhex->pixel de la metrique EUCLIDIENNE (any-angle) du move PvP. Le gym tourne en
# metrique `hex` (`distance_metric.move_gym`, spec §4.4) : un pas de BFS = un hex = sqrt(3) px.
# Dimensionner la grille sur 1.5 rejetterait hors grille ~2.5% du disque atteignable (mesure :
# 272/10981 destinations a half_extent=60), concentres sur l'axe VERTICAL, ou le rapport
# vaut sqrt(3)/1.5 = 1.155 (sur l'axe horizontal il vaut 1.0, d'ou un effet limite aux
# extremites et non uniforme). Ces destinations sont legales : les perdre bornerait l'agent.
HEX_STEP_PX = math.sqrt(3.0)

# Jet d'Advance maximal (1D6), en POUCES. Borne la demi-etendue de la grille.
MAX_ADVANCE_ROLL_INCHES = 6


def grid_half_extent_subhex(game_state: Dict[str, Any], squad_id: str) -> int:
    """Demi-etendue de la grille en subhex = budget Advance MAXIMAL de l'escouade.

    `M + 6" x inches_to_subhex`, via le budget moteur (source unique des regles, applique
    aussi le malus Take to the skies 21.03). Deterministe a etat donne, donc identique
    entre obs / masque / decoder appeles au meme point de decision.

    Leve si le budget est nul : une escouade sans budget n'a pas de grille de mouvement, et
    normaliser par 0 serait une division par zero silencieuse.
    """
    from engine.phase_handlers.shared_utils import get_squad_move_budget

    half_extent = get_squad_move_budget(
        squad_id, game_state, "advance", advance_roll=MAX_ADVANCE_ROLL_INCHES
    )
    if half_extent <= 0:
        raise ValueError(
            f"grid_half_extent_subhex: budget Advance maximal nul pour squad {squad_id} "
            f"(={half_extent}) - impossible de normaliser la grille egocentrique"
        )
    return int(half_extent)


def _half_extent_px(half_extent_subhex: int) -> float:
    """Demi-cote de la grille, en unites `_hex_center`.

    Marge d'un DEMI pas hex au-dela du budget. Sans elle, un hex situe a distance-hex
    exactement egale au budget tombe a |u| == 1.0 pile, soit l'indice `GRID_SIZE` : le carre
    [-W,+W] doit etre demi-ouvert pour se decouper en GRID_SIZE cellules, donc son bord exact
    serait ejecte de la grille. Ces hexes extremes sont des destinations LEGALES du pool (un
    move exactement au budget), les perdre bornerait l'agent. La marge les rabat proprement
    dans la cellule de bord.
    """
    return (float(half_extent_subhex) + 0.5) * HEX_STEP_PX


def cover_dilation_cells(base_size: Any, half_extent_subhex: int) -> int:
    """Rayon de dilatation, EN CELLULES, du canal « couvert » pour un socle de `base_size`.

    Règle 13.08 : une figurine est « within a terrain area » dès que son SOCLE chevauche la
    zone — pas seulement quand son ancre y tombe. Peindre les seuls hexes de la zone laisse
    donc à 0 une couronne de cases où l'agent aurait pourtant le couvert : sur le board ×5, un
    socle d'infanterie de 16 subhex de diamètre déborde de ~2 cellules de grille.

    Conversion : la grille couvre [-W, +W] en unités `_hex_center` sur GRID_SIZE cellules, donc
    une cellule vaut `2W / GRID_SIZE`. On arrondit au SUPÉRIEUR (couronne complète plutôt que
    tronquée) et on borne à 0 quand le socle tient dans une cellule (infanterie de petite base :
    la dilatation serait du bruit).
    """
    from engine.hex_utils import round_base_radius_norm

    # Socle non rond (oval/square) : on prend sa plus GRANDE dimension — borne superieure du
    # debordement quelle que soit l orientation, donc jamais de couronne manquante.
    if isinstance(base_size, (list, tuple)):
        if not base_size:
            raise ValueError("cover_dilation_cells: BASE_SIZE liste vide")
        span = max(float(v) for v in base_size)
    else:
        span = float(base_size)
    cell_px = 2.0 * _half_extent_px(half_extent_subhex) / GRID_SIZE
    if cell_px <= 0:
        raise ValueError(f"cover_dilation_cells: taille de cellule invalide ({cell_px})")
    return int(math.floor(round_base_radius_norm(span) / cell_px))


def dilate_channel(channel: np.ndarray, radius_cells: int) -> np.ndarray:
    """Dilatation morphologique (voisinage carré) d'un canal de grille, `radius_cells` fois.

    Pure numpy (pas de dépendance scipy) : à chaque passe, chaque cellule prend le max de ses
    voisines. `radius_cells <= 0` renvoie le canal inchangé.
    """
    if radius_cells <= 0:
        return channel
    out = channel
    for _ in range(int(radius_cells)):
        shifted = out.copy()
        shifted[1:, :] = np.maximum(shifted[1:, :], out[:-1, :])
        shifted[:-1, :] = np.maximum(shifted[:-1, :], out[1:, :])
        base = shifted.copy()
        shifted[:, 1:] = np.maximum(shifted[:, 1:], base[:, :-1])
        shifted[:, :-1] = np.maximum(shifted[:, :-1], base[:, 1:])
        out = shifted
    return out


def hex_to_cell(
    col: int,
    row: int,
    anchor_col: int,
    anchor_row: int,
    half_extent_subhex: int,
    clamp: bool = False,
) -> Optional[Tuple[int, int]]:
    """Projette l'hex (col,row) sur la cellule (gx,gy) de la grille centree sur l'ancre.

    Renvoie None si l'hex tombe hors de la grille.

    `clamp=True` : rabat sur la cellule de bord au lieu de renvoyer None. Reserve a la
    projection du POOL, ou l'hex est atteignable par construction (donc a l'interieur du
    disque) et ou seul l'arrondi exact au bord (|u| == 1.0) pourrait sortir du carre. Ne
    JAMAIS l'utiliser pour la rasterisation des canaux : un mur lointain serait rabattu sur
    le bord de la grille et l'agent verrait un obstacle qui n'existe pas la.
    """
    ax, ay = _hex_center(anchor_col, anchor_row)
    x, y = _hex_center(col, row)
    w = _half_extent_px(half_extent_subhex)
    u = (x - ax) / w
    v = (y - ay) / w

    gx = int(math.floor((u + 1.0) * 0.5 * GRID_SIZE))
    gy = int(math.floor((v + 1.0) * 0.5 * GRID_SIZE))
    if gx < 0 or gx >= GRID_SIZE or gy < 0 or gy >= GRID_SIZE:
        if not clamp:
            return None
        gx = min(GRID_SIZE - 1, max(0, gx))
        gy = min(GRID_SIZE - 1, max(0, gy))
    return gx, gy


def hex_arrays_to_cells(
    cols: "np.ndarray",
    rows: "np.ndarray",
    anchor_col: int,
    anchor_row: int,
    half_extent_subhex: int,
) -> Tuple["np.ndarray", "np.ndarray", "np.ndarray"]:
    """Jumeau VECTORISE de `hex_to_cell` (clamp=False) -> (gx, gy, valid).

    Meme formule, appliquee a des tableaux. Existe pour la rasterisation des canaux (T1), ou
    le nombre d'hexes a projeter est eleve : sur le board x5, les objectifs seuls totalisent
    ~10 500 hexes (ce sont des ZONES, pas des points), et le chemin scalaire recalculait le
    centre de l'ancre a chaque hex (2 appels `_hex_center` par projection).

    `valid` : False pour les hexes hors grille — l'appelant DOIT les ecarter (pas de clamp),
    sinon un obstacle lointain serait rabattu sur le bord de la grille.

    L'equivalence stricte avec `hex_to_cell` est verrouillee par test : c'est elle qui garantit
    que l'obs et le masque designent le meme hex.
    """
    cols = np.asarray(cols, dtype=np.float64)
    rows = np.asarray(rows, dtype=np.float64)

    # Inline de `_hex_center` (hex_radius=1.0, flat-top odd-q), vectorise.
    hex_width = 1.5
    hex_height = HEX_STEP_PX
    x = cols * hex_width + hex_width / 2.0
    y = rows * hex_height + (np.mod(cols, 2.0) * hex_height) / 2.0 + hex_height / 2.0

    ax, ay = _hex_center(anchor_col, anchor_row)
    w = _half_extent_px(half_extent_subhex)

    gx = np.floor(((x - ax) / w + 1.0) * 0.5 * GRID_SIZE).astype(np.int64)
    gy = np.floor(((y - ay) / w + 1.0) * 0.5 * GRID_SIZE).astype(np.int64)
    valid = (gx >= 0) & (gx < GRID_SIZE) & (gy >= 0) & (gy < GRID_SIZE)
    return gx, gy, valid


def cell_center_px(
    gx: int,
    gy: int,
    anchor_col: int,
    anchor_row: int,
    half_extent_subhex: int,
) -> Tuple[float, float]:
    """Centre geometrique de la cellule (gx,gy), en unites `_hex_center`."""
    ax, ay = _hex_center(anchor_col, anchor_row)
    w = _half_extent_px(half_extent_subhex)
    x = ax + (((gx + 0.5) / GRID_SIZE) * 2.0 - 1.0) * w
    y = ay + (((gy + 0.5) / GRID_SIZE) * 2.0 - 1.0) * w
    return x, y


def cell_index(gx: int, gy: int) -> int:
    """(gx,gy) -> index plat [0, GRID_CELL_COUNT)."""
    if not (0 <= gx < GRID_SIZE and 0 <= gy < GRID_SIZE):
        raise ValueError(f"cell_index: cellule hors grille ({gx},{gy}), grille={GRID_SIZE}x{GRID_SIZE}")
    return gy * GRID_SIZE + gx


def cell_from_index(idx: int) -> Tuple[int, int]:
    """Index plat -> (gx,gy)."""
    if not (0 <= idx < GRID_CELL_COUNT):
        raise ValueError(f"cell_from_index: index hors grille ({idx}), attendu [0,{GRID_CELL_COUNT})")
    return idx % GRID_SIZE, idx // GRID_SIZE


def project_pool_to_grid(
    pool_costs: Mapping[Tuple[int, int], float],
    anchor_col: int,
    anchor_row: int,
    half_extent_subhex: int,
) -> Dict[int, Tuple[Tuple[int, int], float]]:
    """Projette le pool BFS sur la grille -> {cell_index: ((col,row), cout_geodesique)}.

    `pool_costs` : {(col,row): cout geodesique} — le cout est la distance de CHEMIN du BFS
    (pas la distance a vol d'oiseau), car c'est lui qui determine le type de move (spec §6.2 :
    cout <= M -> normal, cout > M -> advance ; regle 03 : la distance d'un move est celle du
    chemin parcouru).

    Plusieurs hexes du pool peuvent tomber dans la meme cellule : on retient l'hex le PLUS
    PROCHE du centre geometrique de la cellule, departage deterministe par (col,row) min
    (spec §10.3). L'action executee correspond ainsi au plus pres a ce que l'agent a vise.

    Le dict renvoye est la source du masque (cles = cellules jouables) ET du decodage.
    """
    if not pool_costs:
        return {}

    # --- Geometrie vectorisee -------------------------------------------------
    # Le chemin scalaire appelait `hex_to_cell` + `cell_center_px` + `_hex_center` par hex du
    # pool, soit ~150 M appels a `_hex_center` sur un run de training (29% du CPU au profil) —
    # dont deux tiers recalculaient le centre de l'ancre et `_half_extent_px`, IDENTIQUES pour
    # tout le pool. Ils sont hisses hors de la boucle et le reste passe en numpy.
    #
    # La SELECTION (fold ci-dessous) reste scalaire et sequentielle a dessein : le departage
    # `d2 < cur_d2 - 1e-12` est une comparaison a tolerance, donc NON transitive — elle ne
    # definit pas un ordre total. Un `argmin`/`lexsort` vectorise donnerait un autre gagnant
    # sur les cas limites, et masque et decodage designeraient des hexes differents. On ne
    # vectorise que ce qui est arithmetiquement exact.
    items = list(pool_costs.items())
    n = len(items)
    cols = np.fromiter((cr[0] for cr, _ in items), dtype=np.float64, count=n)
    rows = np.fromiter((cr[1] for cr, _ in items), dtype=np.float64, count=n)

    # Inline de `_hex_center` — MEME formule et MEME ordre d'operations que `hex_arrays_to_cells`
    # (donc que `_hex_center`) : `np.mod(cols, 2.0)` == `col & 1` pour col >= 0 (indices de board).
    hex_width = 1.5
    hex_height = HEX_STEP_PX
    hxs = cols * hex_width + hex_width / 2.0
    hys = rows * hex_height + (np.mod(cols, 2.0) * hex_height) / 2.0 + hex_height / 2.0

    ax, ay = _hex_center(anchor_col, anchor_row)
    w = _half_extent_px(half_extent_subhex)

    # `clamp=True` : jamais None, l'hex du pool est atteignable donc dans le disque ; seul
    # l'arrondi au bord exact peut sortir. Miroir du min/max scalaire, applique par axe.
    gxs = np.clip(np.floor(((hxs - ax) / w + 1.0) * 0.5 * GRID_SIZE), 0, GRID_SIZE - 1).astype(np.int64)
    gys = np.clip(np.floor(((hys - ay) / w + 1.0) * 0.5 * GRID_SIZE), 0, GRID_SIZE - 1).astype(np.int64)
    idxs = gys * GRID_SIZE + gxs

    cxs = ax + (((gxs + 0.5) / GRID_SIZE) * 2.0 - 1.0) * w
    cys = ay + (((gys + 0.5) / GRID_SIZE) * 2.0 - 1.0) * w
    d2s = (hxs - cxs) ** 2 + (hys - cys) ** 2

    best: Dict[int, Tuple[float, Tuple[int, int], float]] = {}
    for _i, ((col, row), cost) in enumerate(items):
        idx = int(idxs[_i])
        d2 = float(d2s[_i])
        current = best.get(idx)
        if current is None:
            best[idx] = (d2, (col, row), float(cost))
            continue
        cur_d2, cur_hex, _ = current
        if d2 < cur_d2 - 1e-12 or (abs(d2 - cur_d2) <= 1e-12 and (col, row) < cur_hex):
            best[idx] = (d2, (col, row), float(cost))
    return {idx: (hex_cr, cost) for idx, (_, hex_cr, cost) in best.items()}


def normalize_move_costs(
    costs: "np.ndarray", normal_budget: int, half_extent_subhex: int
) -> "np.ndarray":
    """Couts geodesiques (subhex) -> valeurs du canal `GRID_CH_MOVE_COST`, dans [0,1].

    Affine PAR MORCEAUX, de sorte que la frontiere normal/advance tombe exactement sur
    `MOVE_COST_ADVANCE_THRESHOLD` quels que soient le MOVE de l unite et l echelle du board :

        cout in [0, M]  ->  [0, seuil]          (regime NORMAL)
        cout in (M, H]  ->  (seuil, 1]          (regime ADVANCE)

    ou `M` = budget de move normal EXECUTABLE (`squad_normal_move_frontier_subhex` : le MOVE moins
    le cout de descente §13.06 — la MEME grandeur que `classify_squad_move_type` compare au cout,
    cf. §0.34) et `H` = demi-etendue de la grille = budget Advance MAXIMAL
    (`grid_half_extent_subhex`), borne superieure de tout cout du pool.

    Monotone et bijective par morceaux : rien n est perdu, seule l echelle est recalee. Une simple
    division par `H` serait plus courte mais placerait la frontiere a `MOVE / (MOVE + 6)` — cf. le
    commentaire de `MOVE_COST_ADVANCE_THRESHOLD` : le CNN ne voit que la grille, il ne peut pas
    retrouver ou est cette frontiere.

    Escouade ENGAGEE : le pool est construit au budget Fall Back (= M), donc tous les couts sont
    <= M et le canal reste <= seuil. C est exact, et informatif : « aucun advance disponible ».
    """
    if half_extent_subhex <= 0:
        raise ValueError(
            f"normalize_move_costs: demi-etendue invalide ({half_extent_subhex})"
        )
    if normal_budget < 0 or normal_budget >= half_extent_subhex:
        raise ValueError(
            f"normalize_move_costs: budget normal {normal_budget} hors de [0, "
            f"{half_extent_subhex}[ — le budget Advance maximal doit le dominer strictement"
        )
    costs = np.asarray(costs, dtype=np.float64)
    if costs.size:
        # TOLERANCE D ARRONDI, pas un repli. Les couts du BFS sont des sommes de pas de
        # `2/sqrt(3)` : une destination pile au budget ressort a `12.000000000000005` pour un
        # budget de 12. Le depassement mesure est de l ordre de 1e-15 ; une vraie incoherence
        # entre le pool et la grille vaudrait au moins UN pas (~1,15), donc 1e-6 separe les deux
        # sans ambiguite. Sous la tolerance on recale (`clip`) ; au-dela on leve.
        # (Ce cas ne se voyait pas en float32, ou l epsilon disparaissait a l arrondi — il a ete
        # trouve par `test_spatial_move_decode_execute`, pas par les tests de la grille.)
        lo, hi = float(costs.min()), float(costs.max())
        if lo < -_COST_BOUND_TOLERANCE or hi > float(half_extent_subhex) + _COST_BOUND_TOLERANCE:
            raise ValueError(
                f"normalize_move_costs: cout hors de [0, {half_extent_subhex}] "
                f"(min={lo}, max={hi}) — le pool et la grille ne partagent plus le meme budget "
                f"Advance maximal"
            )
        costs = np.clip(costs, 0.0, float(half_extent_subhex))

    threshold = float(MOVE_COST_ADVANCE_THRESHOLD)
    span_advance = float(half_extent_subhex - normal_budget)
    if normal_budget == 0:
        # Budget normal NUL (Take to the skies 21.03 sur une unite tres lente) : rester sur place
        # est le seul « normal », toute cellule atteinte est un advance. Pas de division par zero
        # a masquer — le regime normal est vide, on le dit.
        out = np.where(costs > 0.0, threshold + (1.0 - threshold) * costs / span_advance, 0.0)
    else:
        out = np.where(
            costs <= float(normal_budget),
            threshold * costs / float(normal_budget),
            threshold + (1.0 - threshold) * (costs - float(normal_budget)) / span_advance,
        )
    return out.astype(np.float32)


def iter_window_hexes(
    anchor_col: int,
    anchor_row: int,
    half_extent_subhex: int,
    board_cols: int,
    board_rows: int,
) -> Iterable[Tuple[int, int]]:
    """Itere les hexes du board susceptibles de tomber dans la grille (bounding box).

    Sur-approximation volontaire : le filtrage exact est fait par `hex_to_cell` (qui renvoie
    None hors grille). Sert a borner la rasterisation sans scanner tout le board.
    """
    w = _half_extent_px(half_extent_subhex)
    # `_hex_center` : x = col * 1.5 + cst, y = row * sqrt(3) + parite * sqrt(3)/2 + cst.
    # Marge de 1 hex pour absorber le demi-decalage de parite et les arrondis.
    d_col = int(math.ceil(w / 1.5)) + 1
    d_row = int(math.ceil(w / HEX_STEP_PX)) + 1
    col_lo = max(0, anchor_col - d_col)
    col_hi = min(board_cols - 1, anchor_col + d_col)
    row_lo = max(0, anchor_row - d_row)
    row_hi = min(board_rows - 1, anchor_row + d_row)
    for c in range(col_lo, col_hi + 1):
        for r in range(row_lo, row_hi + 1):
            yield c, r
