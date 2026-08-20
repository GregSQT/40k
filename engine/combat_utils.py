#!/usr/bin/env python3
"""
combat_utils.py - Pure utility functions for combat calculations
"""

import math
import os
from typing import Dict, List, Tuple, Any, Optional, Union

# NOTE: Do not import is_unit_alive at top level — causes circular import
# (combat_utils → shared_utils → phase_handlers → generic_handlers → combat_utils).
# Use lazy import inside functions that need it.
from engine.game_utils import require_unit_by_id  # noqa: F401 – re-export for callers

# ============================================================================
# DICE UTILITIES
# ============================================================================

DiceValue = Union[int, str]
EXPECTED_D3 = 2.0
EXPECTED_D6 = 3.5
EXPECTED_2D6 = 7.0
EXPECTED_D6_PLUS_1 = 4.5
EXPECTED_D6_PLUS_2 = 5.5
EXPECTED_D6_PLUS_3 = 6.5


def resolve_dice_value(value: DiceValue, roll_context: str) -> int:
    """
    Resolve a dice expression or integer into a concrete roll.

    Supported dice strings: "D3", "D6", "2D6", "D6+1", "D6+2", "D6+3".
    - D3: roll a D6, divide by 2 and round up (1-3).
    - D6: roll a D6 (1-6).
    - 2D6: roll two D6 and sum (2-12).
    - D6+1: roll a D6 and add 1 (2-7).
    - D6+2: roll a D6 and add 2 (3-8).
    - D6+3: roll a D6 and add 3 (4-9).
    """
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Invalid dice value type for {roll_context}: {type(value).__name__}")
    if value not in {"D3", "D6", "2D6", "D6+1", "D6+2", "D6+3"}:
        raise ValueError(f"Unsupported dice expression for {roll_context}: {value}")

    import random
    d6_roll = random.randint(1, 6)
    if value == "2D6":
        second_d6_roll = random.randint(1, 6)
        return d6_roll + second_d6_roll
    if value == "D6+1":
        return d6_roll + 1
    if value == "D6+2":
        return d6_roll + 2
    if value == "D6+3":
        return d6_roll + 3
    if value == "D6":
        return d6_roll
    return (d6_roll + 1) // 2


def expected_dice_value(value: DiceValue, roll_context: str) -> float:
    """
    Resolve a dice expression or integer into its expected value (no RNG).

    Supported dice strings: "D3", "D6", "2D6", "D6+1", "D6+2", "D6+3".
    - D3 expected value: 2.0
    - D6 expected value: 3.5
    - 2D6 expected value: 7.0
    - D6+1 expected value: 4.5
    - D6+2 expected value: 5.5
    - D6+3 expected value: 6.5
    """
    if isinstance(value, int):
        return float(value)
    if not isinstance(value, str):
        raise TypeError(f"Invalid dice value type for {roll_context}: {type(value).__name__}")
    if value == "D3":
        return EXPECTED_D3
    if value == "D6":
        return EXPECTED_D6
    if value == "2D6":
        return EXPECTED_2D6
    if value == "D6+1":
        return EXPECTED_D6_PLUS_1
    if value == "D6+2":
        return EXPECTED_D6_PLUS_2
    if value == "D6+3":
        return EXPECTED_D6_PLUS_3
    raise ValueError(f"Unsupported dice expression for {roll_context}: {value}")

# ============================================================================
# UNIT UTILITIES
# ============================================================================

def get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """
    Get unit by ID from game state.

    Les identifiants d'unite sont des `str` de bout en bout : `GameState` les stringifie a la
    construction (`"id": str(unit_data["id"])`) et l'index `unit_by_id` est cle par `str(u["id"])`.
    Aucune conversion ici : passer autre chose qu'un `str` est un bug de l'appelant, pas un cas
    a rattraper silencieusement (une coercition rendrait le lookup faussement tolerant).

    Args:
        game_state: Game state dictionary with "unit_by_id" index
        unit_id: Unit ID to find (str, comme dans game_state["units"])

    Returns:
        Unit dictionary if found, None otherwise

    REQUIRES: game_state['unit_by_id'] (built at reset/reload). Absence = bug, raise explicitly.
    """
    from shared.data_validation import require_key  # Lazy: avoid circular import
    unit_by_id = require_key(game_state, "unit_by_id")
    return unit_by_id.get(unit_id)


_HEX_NEIGHBORS_CACHE: Dict[Tuple[int, int], Tuple[Tuple[int, int], ...]] = {}


def get_hex_neighbors(col: Any, row: Any) -> Tuple[Tuple[int, int], ...]:
    """
    Get all 6 hexagonal neighbors for offset coordinates.

    Hex neighbor offsets depend on whether column is even or odd.
    Even columns: NE/SE are (+1, -1) and (+1, 0)
    Odd columns: NE/SE are (+1, 0) and (+1, +1)

    Fonction PURE d'une paire d'entiers : le resultat est memoise par (col, row). C'est la
    boucle interne de tous les BFS du moteur (pool de move, geodesique, charge, pile-in) —
    mesure sur `test_move_mask_is_executable` : 94,7 M appels pour 187 s, soit 44 % du temps.
    Le cache est borne par le plateau (~2 600 entrees), donc constant en memoire.

    Le tuple renvoye est PARTAGE entre appelants, donc IMMUABLE par construction : renvoyer
    une liste exposerait le cache a une mutation d'appelant. Tous les appelants iterent,
    testent l'appartenance, indexent ou construisent un `set` — aucun ne mute.

    Args:
        col: Column coordinate (will be normalized to int)
        row: Row coordinate (will be normalized to int)

    Returns:
        Tuple of 6 neighbor (col, row) tuples, all normalized to int
    """
    # Chemin rapide, sur des entiers DEJA normalises : le cache est interroge avant tout appel
    # a `normalize_coordinates`. C'est la boucle interne de tous les BFS du moteur, ou `col` et
    # `row` sortent d'un tuple d'entiers et n'ont donc rien a normaliser — la normalisation y
    # coutait deux appels de fonction et deux `isinstance` par appel, 17,9 M fois sur une eval
    # de 24 episodes (mesure cProfile : 8,90 s, 5,5 % du temps total).
    #
    # Le garde porte sur `type(...) is int` et non `isinstance` : `True` est un `int` pour
    # `isinstance` (bool en est une sous-classe), mais n'est pas une coordonnee valide. Tout ce qui
    # n'est pas exactement `int` (float, str, bool, type invalide) emprunte la voie normale
    # ci-dessous — memes conversions, memes erreurs, aux memes endroits.
    if type(col) is int and type(row) is int:
        cached = _HEX_NEIGHBORS_CACHE.get((col, row))
        if cached is not None:
            return cached
    # Normalize coordinates to int
    key = normalize_coordinates(col, row)
    cached = _HEX_NEIGHBORS_CACHE.get(key)
    if cached is not None:
        return cached
    col_int, row_int = key

    # Determine if column is even or odd
    parity = col_int & 1  # 0 for even, 1 for odd

    if parity == 0:  # Even column
        neighbors = (
            (int(col_int), int(row_int - 1)),      # N
            (int(col_int + 1), int(row_int - 1)),  # NE
            (int(col_int + 1), int(row_int)),      # SE
            (int(col_int), int(row_int + 1)),      # S
            (int(col_int - 1), int(row_int)),      # SW
            (int(col_int - 1), int(row_int - 1))   # NW
        )
    else:  # Odd column
        neighbors = (
            (int(col_int), int(row_int - 1)),      # N
            (int(col_int + 1), int(row_int)),      # NE
            (int(col_int + 1), int(row_int + 1)),  # SE
            (int(col_int), int(row_int + 1)),      # S
            (int(col_int - 1), int(row_int + 1)),  # SW
            (int(col_int - 1), int(row_int))       # NW
        )

    _HEX_NEIGHBORS_CACHE[key] = neighbors
    return neighbors


# ============================================================================
# COORDINATE NORMALIZATION
# ============================================================================

def normalize_coordinate(coord: Any) -> int:
    """
    Normalize coordinate to int. Raises ValueError if conversion fails.
    
    CRITICAL: All hex coordinates must be int. This function ensures type consistency
    and raises clear errors if coordinates are invalid.
    
    Args:
        coord: Coordinate value (int, float, or numeric string)
    
    Returns:
        int: Normalized coordinate as integer
    
    Raises:
        ValueError: If coordinate string cannot be converted
        TypeError: If coordinate type is not supported
    """
    if isinstance(coord, int):
        return coord
    elif isinstance(coord, float):
        return int(coord)
    elif isinstance(coord, str):
        try:
            return int(float(coord))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid coordinate string '{coord}': {e}")
    else:
        raise TypeError(f"Invalid coordinate type {type(coord).__name__}: {coord}. Expected int, float, or numeric string.")


def normalize_coordinates(col: Any, row: Any) -> Tuple[int, int]:
    """
    Normalize both coordinates to int. Raises ValueError if conversion fails.
    
    Args:
        col: Column coordinate (int, float, or numeric string)
        row: Row coordinate (int, float, or numeric string)
    
    Returns:
        Tuple[int, int]: Normalized (col, row) as integers
    """
    return normalize_coordinate(col), normalize_coordinate(row)


def get_unit_coordinates(unit: Dict[str, Any]) -> Tuple[int, int]:
    """
    Extract and normalize unit coordinates from unit dict.
    
    CRITICAL: Always use this function to get unit coordinates to ensure
    they are normalized to int for consistent comparison.
    
    Args:
        unit: Unit dictionary with "col" and "row" keys
    
    Returns:
        Tuple[int, int]: Normalized (col, row) coordinates
    
    Raises:
        KeyError: If unit dict missing "col" or "row" keys
    """
    return normalize_coordinates(unit["col"], unit["row"])


def set_unit_coordinates(unit: Dict[str, Any], col: Any, row: Any) -> None:
    """
    Set and normalize unit coordinates in unit dict.
    
    CRITICAL: Always use this function to set unit coordinates to ensure
    they are normalized to int before storage.
    
    Args:
        unit: Unit dictionary to update
        col: Column coordinate (int, float, or numeric string)
        row: Row coordinate (int, float, or numeric string)
    
    Raises:
        ValueError: If coordinate conversion fails
        TypeError: If coordinate type is not supported
    """
    unit["col"], unit["row"] = normalize_coordinates(col, row)


# ============================================================================
# DISTANCE CALCULATION
# ============================================================================

def calculate_hex_distance(col1: int, row1: int, col2: int, row2: int) -> int:
        """Calculate hex distance using cube coordinates (matching handlers).

        WARNING: This is straight-line distance, ignoring walls! Le moteur n'a plus de
        distance de pathfinding : `calculate_pathfinding_distance` et son champ BFS ont ete
        supprimes le 2026-07-28, faute d'appelant (cf. `V11_agent_rework.md` §0.39).
        """
        # Convert offset to cube
        x1 = col1
        z1 = row1 - ((col1 - (col1 & 1)) >> 1)
        y1 = -x1 - z1

        x2 = col2
        z2 = row2 - ((col2 - (col2 & 1)) >> 1)
        y2 = -x2 - z2

        # Cube distance
        return max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))


# ----------------------------------------------------------------------------
# Sélecteur de métrique de portée (point de bascule unique hex ↔ euclidien)
# Voir Documentation/Implémentation/Implémenté/Distance management.md, Étapes 1-2.
# ----------------------------------------------------------------------------

VALID_DISTANCE_METRICS = ("hex", "euclidean")
DISTANCE_METRIC_RULES = ("ranged", "move", "charge", "engagement", "overlap")


def get_distance_metric(rule: str, game_config: Dict[str, Any]) -> str:
    """Métrique de distance à appliquer à une règle (``ranged``/``move``/…).

    Lit ``game_config["distance_metric"][rule]``. Aucune valeur par défaut :
    section/clé/valeur manquante ou invalide → erreur explicite (CLAUDE.md).
    """
    if rule not in DISTANCE_METRIC_RULES:
        raise ValueError(f"Unknown distance rule {rule!r}, expected one of {DISTANCE_METRIC_RULES}")
    if "distance_metric" not in game_config:
        raise KeyError("Missing 'distance_metric' section in game_config.json")
    metrics = game_config["distance_metric"]
    if rule not in metrics:
        raise KeyError(f"Missing distance_metric['{rule}'] in game_config.json")
    metric = metrics[rule]
    if metric not in VALID_DISTANCE_METRICS:
        raise ValueError(
            f"Invalid distance_metric['{rule}'] = {metric!r}, expected one of {VALID_DISTANCE_METRICS}"
        )
    return metric


#: Clé du training config (et du ``game_state``) qui impose la métrique de distance du GYM.
#: Nom UNIQUE, propriétaire de l'orthographe : le training config l'écrit, ``w40k_core`` la
#: recopie dans le ``game_state``, les sélecteurs move/charge la lisent. Une constante plutôt
#: qu'un littéral répété — une faute de frappe dans l'un des trois sites rendrait le switch
#: silencieusement inopérant (le pire mode d'échec pour un réglage de fidélité).
GYM_DISTANCE_METRIC_KEY = "gym_distance_metric"


def gym_distance_metric_override(source: Optional[Dict[str, Any]]) -> Optional[str]:
    """Métrique imposée au GYM par le training config, ou ``None`` si la phase n'en impose pas.

    ``source`` = le training config (à la construction du moteur) OU le ``game_state`` (aux
    sélecteurs) : les deux portent la MÊME clé, et c'est délibéré — un seul nom à chercher pour
    savoir d'où sort une métrique, du JSON jusqu'au pool.

    POURQUOI CE RÉGLAGE EXISTE. Les clés ``move_gym``/``charge_gym`` valent ``hex`` alors que le
    PvP résout en ``euclidean`` dès x5 : l'agent s'entraîne sur un pool de destinations dont
    11-15 % n'existent pas en partie (mesuré sur 162 états réels, x5). Le pool euclidien est un
    sous-ensemble STRICT du pool hex — l'agent n'est donc aveugle à rien, mais il apprend une
    frontière de portée hexagonale là où elle est circulaire, et 72 % de l'écart tombe sur
    l'anneau extérieur du disque de move, celui qui décide des entrées en portée de charge.

    Aligner le gym coûte ×3,55 sur la construction du pool (mesuré). Ce surcoût est STRUCTUREL,
    pas un défaut d'implémentation : au sol, le pool euclidien est un champ géodésique qui encode
    le contournement d'obstacle, et aucun filtre radial du pool hex ne le reconstitue (testé —
    le pool euclidien n'est radialement clos dans le hex que pour 21 % des états au sol, contre
    100 % en FLY, où il dégénère en disque, 21.03).

    D'où ce réglage PAR PHASE : gros du curriculum en ``hex`` (rapide), puis phase finale en
    ``euclidean`` via ``--append`` pour recalibrer la frontière. ``obs_size`` ne change pas et
    l'espace d'actions se RESSERRE — un modèle reste chargeable d'une phase à l'autre.

    Absente → ``None`` → les sélecteurs lisent ``game_config`` comme avant : ce réglage est
    strictement opt-in, il ne déplace rien tant qu'aucune phase ne le pose. Présente mais
    invalide → erreur explicite, jamais un repli silencieux (CLAUDE.md).

    ⚠️ PORTÉE. Ce switch ne pilote que ``move`` et ``charge``, les deux seules règles à avoir une
    variante gym. La zone d'ENGAGEMENT n'en a pas : elle résout déjà en euclidien à x5, en
    training comme en PvP. Une phase en ``hex`` a donc un move hex et un engagement euclidien —
    ce qui est exactement l'état actuel du training, pas une incohérence introduite ici.
    """
    if source is None:
        return None
    value = source.get(GYM_DISTANCE_METRIC_KEY)  # get allowed (réglage OPTIONNEL, cf. docstring)
    if value is None:
        return None
    if value not in VALID_DISTANCE_METRICS:
        raise ValueError(
            f"Invalid {GYM_DISTANCE_METRIC_KEY} = {value!r} dans le training config, "
            f"expected one of {VALID_DISTANCE_METRICS}"
        )
    return value


#: Règles dont la métrique a une variante GYM (``<rule>_gym``) distincte de la variante PvP.
#: ``engagement`` n'en fait PAS partie — pas de split gym, cf. ``engagement_distance_metric``.
GYM_SPLIT_DISTANCE_RULES = ("move", "charge")


def resolve_gym_split_metric(rule: str, game_state: Optional[Dict[str, Any]]) -> str:
    """Métrique effective d'une règle à split gym (``move``/``charge``) — CORPS UNIQUE.

    ``_move_distance_metric`` et ``_charge_distance_metric`` avaient le même corps à la clé près,
    tenus en phase à la main (« Miroir de… » dans les deux docstrings). C'est le motif JUMEAU :
    une modification de la PRÉCÉDENCE faite d'un côté et pas de l'autre donnerait à l'agent une
    portée de move et une portée de charge mesurées différemment, alors que 11.04 dit que la
    charge EST un move. Un seul corps rend la divergence impossible plutôt qu'improbable.

    Précédence, dans cet ordre et pour les deux règles :
    1. la CLÉ de config (``<rule>_gym`` en gym, ``<rule>`` sinon) est lue et VALIDÉE — une config
       cassée doit lever même quand un réglage la recouvre, sinon elle reste invisible ;
    2. en gym seulement, la PHASE de training peut imposer sa métrique
       (``gym_distance_metric``, cf. ``gym_distance_metric_override``) ;
    3. la RÉSOLUTION prime sur tout : à ``inches_to_subhex <= 1`` la géométrie est hex
       (``spatial_relations.geometry_is_hex``), quoi qu'en disent la config et la phase.

    ``game_state`` optionnel — même convention que ``engagement_distance_metric``, qui est le
    troisième sélecteur de ce jeu. Il n'utilise pas cette fonction aujourd'hui parce qu'il n'a
    pas de variante ``_gym`` ; le jour où il en gagne une, il n'y aura pas de troisième corps à
    écrire (ni de troisième copie de la précédence à tenir en phase).
    """
    if rule not in GYM_SPLIT_DISTANCE_RULES:
        raise ValueError(
            f"Unknown gym-split distance rule {rule!r}, expected one of {GYM_SPLIT_DISTANCE_RULES}"
        )
    from config_loader import get_config_loader

    game_config = get_config_loader().get_game_config()
    if "distance_metric" not in game_config:
        raise KeyError("Missing 'distance_metric' section in game_config.json")
    metrics = game_config["distance_metric"]
    is_gym = bool(game_state.get("gym_training_mode")) if game_state else False  # get allowed (drapeau optionnel)
    key = f"{rule}_gym" if is_gym else rule
    if key not in metrics:
        raise KeyError(f"Missing distance_metric['{key}'] in game_config.json")
    metric = metrics[key]
    if metric not in VALID_DISTANCE_METRICS:
        raise ValueError(
            f"Invalid distance_metric['{key}'] = {metric!r}, expected one of {VALID_DISTANCE_METRICS}"
        )
    if is_gym:
        # Revalidé à chaque appel, et c'est VOULU : le `game_state` est un dict muté par le
        # moteur et fabriqué à la main par les tests. La validation de `w40k_core` couvre le
        # training config, pas un état trafiqué en cours de route.
        override = gym_distance_metric_override(game_state)
        if override is not None:
            metric = override
    from engine.spatial_relations import geometry_is_hex

    return "hex" if geometry_is_hex(game_state) else metric


def socle_from_cache_entry(entry: Dict[str, Any]) -> Any:
    """Construit un ``Socle`` (engine.hex_utils) depuis une entrée ``units_cache``.

    L'entrée porte BASE_SHAPE/BASE_SIZE/col/row/occupied_hexes/occupied_hexes_by_model
    (cf build_units_cache). ``model_centers`` = centres par-figurine → distance bord-à-bord
    ronde correcte vers une escouade multi-figurines.
    """
    from engine.hex_utils import Socle
    by_model = entry.get("occupied_hexes_by_model")
    model_centers = (
        [(int(c), int(r)) for (c, r) in by_model.values()]
        if isinstance(by_model, dict) and by_model
        else None
    )
    return Socle(
        entry["BASE_SHAPE"],
        entry["BASE_SIZE"],
        entry["col"],
        entry["row"],
        entry["occupied_hexes"],
        model_centers,
        int(entry.get("orientation", 0)),  # fallback allowed — entrees synthetiques (mover candidat, synth model) sans orientation = facing 0
    )


def ranged_edge_distance(a: Any, b: Any, metric: str, max_distance: float = 0) -> float:
    """Distance de portée bord-à-bord, exprimée en **subhexes** (comparable direct à RNG).

    Point de conversion unique subhex↔norme : le facteur ``ENGAGEMENT_NORM_HEX_WIDTH``
    (= 1,5) vit ICI et nulle part ailleurs. Tous les call-sites tir comparent le résultat
    à une portée en subhexes (``dist > RNG``), sans jamais manipuler le 1,5.

    ``a``, ``b`` : ``Socle`` (engine.hex_utils).
    - ``metric == "hex"``       : ``min_distance_between_sets(fp)`` (déjà en subhexes ;
      comportement actuel). ``max_distance`` : prune ARRONDI AU-DESSUS, la distance hex étant
      entière. L'arrondi vit ici et non chez l'appelant : le seuil qu'il compare, lui, est un
      flottant (``detection_range_subhex``, une portée d'arme scalée), et un cap tronqué SOUS ce
      seuil rendrait un minorant pour une cible située entre les deux — un tir hors portée compté
      légal, une figurine hors détection traitée comme détectable. Chaque appelant devait donc
      poser le même ``math.ceil`` en le justifiant : l'invariant « cap >= seuil comparé »
      appartient à la primitive, pas à ses sept sites d'appel.
    - ``metric == "euclidean"`` : ``euclidean_edge_distance(a, b)`` [unités-norme] ÷ 1,5
      → subhexes (règle 01.04, bord-à-bord). ``max_distance`` : prune passé lui aussi, converti
      en unités-norme par le même facteur — les deux métriques rendent donc désormais la même
      promesse (exact tant que ``<= max_distance``, valeur supérieure au-delà). Il était
      transmis au chemin hex et IGNORÉ par le chemin euclidien : le tir en géométrie euclidienne
      payait le contour complet des socles pour toute cible, y compris à l'autre bout du plateau.
    """
    from engine.hex_utils import (
        min_distance_between_sets,
        euclidean_edge_distance,
        ENGAGEMENT_NORM_HEX_WIDTH,
    )
    if metric == "hex":
        if not a.fp or not b.fp:
            raise ValueError("ranged_edge_distance(hex): empreintes (fp) absentes ou vides")
        return min_distance_between_sets(a.fp, b.fp, max_distance=math.ceil(max_distance))
    if metric == "euclidean":
        # `max_distance == 0` : convention de `min_distance_between_sets` — pas d'élagage,
        # distance exacte en toutes circonstances. Reprise telle quelle, c'est le même paramètre.
        norm_cap = max_distance * ENGAGEMENT_NORM_HEX_WIDTH if max_distance > 0 else None
        return euclidean_edge_distance(a, b, max_distance=norm_cap) / ENGAGEMENT_NORM_HEX_WIDTH
    raise ValueError(f"Invalid metric {metric!r}, expected one of {VALID_DISTANCE_METRICS}")


def ranged_in_range(a: Any, b: Any, rng_subhex: int, metric: str) -> bool:
    """Cible à portée de tir (bool) — délègue à ``ranged_edge_distance`` (subhexes)."""
    return ranged_edge_distance(a, b, metric, max_distance=rng_subhex) <= rng_subhex


def ranged_edge_distance_to_cell(shooter: Any, anchor_col: int, anchor_row: int,
                                 col: int, row: int, metric: str) -> float:
    """Distance de portée tireur→**cellule** (subhexes), pour l'overlay de portée (base→point).

    Cas particulier de ``ranged_edge_distance`` où la cible est une case (pas un socle).
    Le facteur subhex↔norme (1,5) et le choix de métrique vivent ICI.

    - ``metric == "hex"``       : distance hex ancre→cellule (comportement historique overlay).
    - ``metric == "euclidean"`` : bord du socle tireur → centre de la cellule, ÷ 1,5 (règle 01.04).
      Rond : centre-à-cellule − rayon. Non-rond : min sur les cellules du socle.
    """
    if metric == "hex":
        return float(calculate_hex_distance(anchor_col, anchor_row, col, row))
    if metric == "euclidean":
        import math
        from engine.hex_utils import _hex_center, round_base_radius_norm, ENGAGEMENT_NORM_HEX_WIDTH
        cxb, cyb = _hex_center(col, row)
        if shooter.shape == "round":
            cxa, cya = _hex_center(shooter.col, shooter.row)
            edge = math.hypot(cxb - cxa, cyb - cya) - round_base_radius_norm(shooter.base_size)
        else:
            if shooter.fp is None:
                raise ValueError("ranged_edge_distance_to_cell(euclidean, non-rond): fp requis")
            edge = min(
                math.hypot(cxb - _hex_center(c, r)[0], cyb - _hex_center(c, r)[1])
                for c, r in shooter.fp
            )
        return (edge if edge > 0.0 else 0.0) / ENGAGEMENT_NORM_HEX_WIDTH
    raise ValueError(f"Invalid metric {metric!r}, expected one of {VALID_DISTANCE_METRICS}")


def get_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
        """Get hex line using handler delegation."""
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._get_accurate_hex_line(start_col, start_row, end_col, end_row)


# ============================================================================
# LINE OF SIGHT
# ============================================================================

def has_line_of_sight(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """
        Check line of sight between shooter and target.

        PERFORMANCE: Uses hex-coordinate cache (5-10x speedup on cache hits).
        Cache key: ((from_col, from_row), (to_col, to_row))
        Walls are static within episode, so LoS from hex A to hex B is constant.
        """
        from engine.phase_handlers import shooting_handlers

        # Extract and normalize coordinates
        from_col_int, from_row_int = get_unit_coordinates(shooter)
        to_col_int, to_row_int = get_unit_coordinates(target)

        # Check hex-coordinate cache first
        if "hex_los_cache" in game_state:
            cache_key = ((from_col_int, from_row_int), (to_col_int, to_row_int))
            if cache_key in game_state["hex_los_cache"]:
                return game_state["hex_los_cache"][cache_key]

        # Cache miss: compute LoS (expensive)
        has_los = shooting_handlers._has_line_of_sight(game_state, shooter, target)

        # Store in cache for future lookups
        if "hex_los_cache" not in game_state:
            game_state["hex_los_cache"] = {}
        game_state["hex_los_cache"][((from_col_int, from_row_int), (to_col_int, to_row_int))] = has_los

        return has_los


def has_line_of_sight_coords(from_col: int, from_row: int, to_col: int, to_row: int,
                              game_state: Dict[str, Any]) -> bool:
        """
        Check line of sight between two hex coordinates.

        PERFORMANCE: Direct coordinate-based LoS check with caching.
        Use this when you don't have unit dicts, only coordinates.
        """
        from engine.phase_handlers import shooting_handlers

        # CRITICAL: Normalize coordinates to int for consistent comparison
        from_col_int, from_row_int = normalize_coordinates(from_col, from_row)
        to_col_int, to_row_int = normalize_coordinates(to_col, to_row)

        # Check hex-coordinate cache first
        if "hex_los_cache" in game_state:
            cache_key = ((from_col_int, from_row_int), (to_col_int, to_row_int))
            if cache_key in game_state["hex_los_cache"]:
                result = game_state["hex_los_cache"][cache_key]
                if os.environ.get("LOS_DEBUG") == "1":
                    _trace_hex_los(
                        "hex_los_cache HIT",
                        from_col_int, from_row_int, to_col_int, to_row_int,
                        result, game_state,
                    )
                return result

        # Cache miss: compute LoS using temp unit dicts
        temp_shooter = {"col": from_col_int, "row": from_row_int}
        temp_target = {"col": to_col_int, "row": to_row_int}
        has_los = shooting_handlers._has_line_of_sight(game_state, temp_shooter, temp_target)

        # Store in cache
        if "hex_los_cache" not in game_state:
            game_state["hex_los_cache"] = {}
        game_state["hex_los_cache"][((from_col_int, from_row_int), (to_col_int, to_row_int))] = has_los

        if os.environ.get("LOS_DEBUG") == "1":
            _trace_hex_los(
                "hex_los_cache MISS (computed)",
                from_col_int, from_row_int, to_col_int, to_row_int,
                has_los, game_state,
            )

        return has_los


def _trace_hex_los(
    event: str,
    from_col: int, from_row: int, to_col: int, to_row: int,
    result: bool,
    game_state: Dict[str, Any],
) -> None:
    """Trace hex LoS for LOS_DEBUG=1. Logs event, coords, result, and LoS ratio."""
    import sys
    try:
        from engine.phase_handlers import shooting_handlers
        ratio, can_see = shooting_handlers._get_los_visibility_state(
            game_state, from_col, from_row, to_col, to_row
        )
        topo_str = f"los={ratio:.6f} can_see={can_see}"
    except Exception:
        topo_str = "los=N/A"
    ep = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    pid = os.getpid()
    msg = f"[LOS_DEBUG] {event} ({from_col},{from_row})->({to_col},{to_row}) result={result} {topo_str} ep={ep} turn={turn} pid={pid}\n"
    sys.stderr.write(msg)
    sys.stderr.flush()


def check_los_cached(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Check LoS using cache (required).
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # AI_TURN_SHOOTING_UPDATE.md: Use shooter["los_cache"] (new architecture)
        if "id" not in target:
            raise KeyError(f"Target missing required 'id' field: {target}")
        target_id = target["id"]
        
        if "los_cache" not in shooter or not shooter["los_cache"]:
            raise ValueError(f"los_cache missing for shooter {shooter.get('id')}")
        
        if target_id not in shooter["los_cache"]:
            raise ValueError(f"los_cache missing target {target_id} for shooter {shooter.get('id')}")
        
        return 1.0 if shooter["los_cache"][target_id] else 0.0

# ============================================================================
# COMBAT VALIDATION
# ============================================================================

def calculate_wound_target(strength: int, toughness: int) -> int:
        """W40K wound chart - basic calculation without external dependencies"""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+


def has_valid_shooting_targets(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if unit has valid shooting targets per AI_TURN.md restrictions."""
        from engine.phase_handlers import shooting_handlers
        from shared.data_validation import require_key  # Lazy: avoid circular import
        units_cache = require_key(game_state, "units_cache")
        for unit_id, entry in units_cache.items():
            if entry["player"] != unit["player"]:
                enemy = get_unit_by_id(game_state, unit_id)
                if not enemy:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                if shooting_handlers._is_valid_shooting_target(game_state, unit, enemy):
                    return True
        return False


def is_valid_shooting_target(shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """REMOVED: Redundant with handler. Use shooting_handlers._is_valid_shooting_target exclusively."""
        # AI_IMPLEMENTATION.md: Complete delegation to handler for consistency
        from engine.phase_handlers import shooting_handlers
        return shooting_handlers._is_valid_shooting_target(game_state, shooter, target)