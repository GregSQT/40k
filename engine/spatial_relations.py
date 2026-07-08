"""Shared spatial relation helpers for footprint contact and engagement checks."""

from typing import Any, Dict, List, Optional, Set, Tuple, cast

from engine.hex_utils import (
    _hex_center,
    compute_occupied_hexes,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    euclidean_edge_distance,
    min_distance_between_sets,
)
from shared.data_validation import require_key


def _require_unit_position_from_cache(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[int, int]:
    """Return unit position from units_cache, raising if the unit is absent."""
    units_cache = require_key(game_state, "units_cache")
    unit_id = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id} not in units_cache (dead or absent); cannot read position")
    return int(require_key(unit_entry, "col")), int(require_key(unit_entry, "row"))


def get_engagement_zone(game_state: Dict[str, Any]) -> int:
    """Engagement zone en sous-hexes. NB: game_rules['engagement_zone'] est DÉJÀ converti
    (× inches_to_subhex) au chargement dans w40k_core (clé scalée). Ne PAS re-multiplier ici."""
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "engagement_zone"))


def get_engagement_zone_from_config(config: Dict[str, Any]) -> int:
    """engagement_zone déjà converti au chargement (cf. get_engagement_zone)."""
    game_rules = require_key(config, "game_rules")
    return int(require_key(game_rules, "engagement_zone"))


def get_engagement_zone_vertical(game_state: Dict[str, Any]) -> float:
    """Seuil vertical d'engagement 3D en POUCES (règle 03.04 = 5" vertical).

    Contrairement à ``engagement_zone`` (horizontal, scalé ×inches_to_subhex au chargement),
    ce seuil reste en pouces : il se compare aux ``height_inches`` des étages (mêmes unités),
    donc NON scalé (absent de la liste de conversion de w40k_core). Aucun défaut caché."""
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    return float(require_key(game_rules, "engagement_zone_vertical"))


def _cache_entry_footprint(cache_entry: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return a unit cache entry footprint, using its anchor only when no footprint is stored."""
    footprint = cache_entry.get("occupied_hexes")
    if footprint:
        return footprint
    return {(require_key(cache_entry, "col"), require_key(cache_entry, "row"))}


def _cache_entry_round_base_size(cache_entry: Dict[str, Any]) -> float:
    """Return a round base size from a cache entry, raising when the stored value is invalid."""
    base_size = require_key(cache_entry, "BASE_SIZE")
    if not isinstance(base_size, (int, float)):
        raise TypeError(f"round BASE_SIZE must be numeric, got {type(base_size).__name__}")
    return base_size


# Hex count of a single base, memoized by geometry. The COUNT is invariant under
# translation and depends only on (shape, size, orientation, column parity) — see
# precompute_footprint_offsets: only column parity shifts the odd-q footprint.
_SINGLE_BASE_HEX_COUNT_CACHE: Dict[Tuple[Any, ...], int] = {}


def _single_base_hex_count(
    base_shape: str, base_size: Any, orientation: int, col_parity: int
) -> int:
    """Memoized number of hexes occupied by one base of the given geometry."""
    size_key = tuple(base_size) if isinstance(base_size, (list, tuple)) else base_size
    key = (base_shape, size_key, orientation, col_parity)
    cached = _SINGLE_BASE_HEX_COUNT_CACHE.get(key)
    if cached is None:
        # col_parity as the reference column preserves odd-q parity; row 0 is arbitrary
        # (the count is translation-invariant), matching the legacy per-call computation.
        cached = len(compute_occupied_hexes(col_parity, 0, base_shape, cast("int | list[int]", base_size), orientation))
        _SINGLE_BASE_HEX_COUNT_CACHE[key] = cached
    return cached


def _entry_is_multi_figure(cache_entry: Dict[str, Any]) -> bool:
    """True when a cache entry's live footprint spans more than one base (a squad).

    Uses ``occupied_hexes`` (kept live from models_cache, dead figs removed) compared to
    the footprint of a single base — never the stale init-time ``entry["models"]`` snapshot.
    A multi-figure squad cannot be reduced to one round circle at its anchor, so the
    euclidean round-round shortcut is invalid for it and the footprint metric is used.
    """
    occ = cache_entry.get("occupied_hexes")
    if not occ:
        return False
    single_count = _single_base_hex_count(
        require_key(cache_entry, "BASE_SHAPE"),
        require_key(cache_entry, "BASE_SIZE"),
        int(require_key(cache_entry, "orientation")),
        int(require_key(cache_entry, "col")) & 1,
    )
    return len(occ) > single_count


def engagement_distance_metric(game_state: Optional[Dict[str, Any]] = None) -> str:
    """Métrique de la zone d'engagement (``hex``|``euclidean``) — sélecteur UNIQUE (Étape 7).

    L'EZ est un concept unique consommé par 4 phases (move, tir, charge, fight) → une seule
    clé ``distance_metric["engagement"]``, pas de split gym (contrairement à move/charge : le
    retrain IA est prévu à la bascule 7.6, cf. Distance management.md). Lue depuis le config-loader
    global (``game_state`` non requis) → la primitive canonique ``unit_entries_within_engagement_zone``
    peut résoudre la métrique sans toucher ses ~60 call-sites. Aucun défaut caché : section/clé/valeur
    invalide → erreur explicite (CLAUDE.md).
    """
    from config_loader import get_config_loader
    from engine.combat_utils import get_distance_metric

    return get_distance_metric("engagement", get_config_loader().get_game_config())


def entries_in_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    metric: str,
    vertical_zone_inches: Optional[float] = None,
) -> bool:
    """Point de bascule pairwise de l'EZ (règle 03.04, bord-à-bord). Deux socles sont en zone
    d'engagement mutuelle ssi leur distance bord-à-bord ≤ ``engagement_zone`` :

    - ``metric == "hex"``       : ``min_distance_between_sets`` d'empreintes ≤ ez (comportement
      historique, byte-identique à l'ancien ``unit_entries_within_engagement_zone``).
    - ``metric == "euclidean"`` : ``euclidean_edge_distance`` ≤ ``engagement_minimum_clearance_norm``
      (= ez × 1,5). Miroir de ``ranged_in_range`` — l'EZ est une portée de ``ez`` subhexes bord-à-bord.

    Conversion ×1,5 confinée à ``engagement_minimum_clearance_norm``, jamais dispersée.

    ``vertical_zone_inches`` (défaut ``None``) — engagement 3D (règle 03.04 = 2" horiz ET 5" vert,
    stage.md chantier 4) :
    - ``None`` → chemin 2D historique **inchangé** (agrégat), byte-identique. Les call-sites qui ne
      passent rien restent 2D → zéro régression.
    - valeur (pouces) → gate vertical **par paire de figurines** (§03.04 est par-modèle) : ∃ (fig_a,
      fig_b) dont les intervalles verticaux ``[plancher, plancher+MODEL_HEIGHT]`` sont séparés de
      ``≤ vertical_zone_inches`` (§01.04 « partie la plus proche », pas plancher-à-plancher) ET dont
      la distance horizontale ≤ seuil. Métrique **euclidean uniquement** (gameplay ; ``model_centers``
      déjà par-fig). Tout au sol des deux côtés → une seule classe verticale → résultat identique au 2D.
    """
    if vertical_zone_inches is not None:
        if metric != "euclidean":
            raise ValueError(
                f"vertical engagement gate (3D) supporté uniquement en métrique 'euclidean', reçu {metric!r}"
            )
        return _entries_in_engagement_zone_3d(
            first_entry, second_entry, engagement_zone, float(vertical_zone_inches)
        )
    if metric == "hex":
        first_fp = _cache_entry_footprint(first_entry)
        second_fp = _cache_entry_footprint(second_entry)
        return min_distance_between_sets(
            first_fp, second_fp, max_distance=engagement_zone
        ) <= engagement_zone
    if metric == "euclidean":
        from engine.combat_utils import socle_from_cache_entry
        a = socle_from_cache_entry(first_entry)
        b = socle_from_cache_entry(second_entry)
        return euclidean_edge_distance(a, b) <= engagement_minimum_clearance_norm(engagement_zone)
    raise ValueError(f"Invalid engagement metric {metric!r}, expected 'hex' or 'euclidean'")


def _vertical_classes(
    entry: Dict[str, Any],
) -> Tuple[Dict[float, List[Tuple[int, int]]], float]:
    """Regroupe les centres par-figurine d'une entrée-cache par hauteur de PLANCHER, + MODEL_HEIGHT.

    Retour : ``({floor_height: [(col,row), …]}, model_height)``. Source : ``occupied_hexes_by_model``
    (centres) + ``floor_height_by_model`` (plancher par fig, chantier 4 étape 1) + ``MODEL_HEIGHT``
    (borne haute). Aucune de ces clés absente n'est tolérée en mode 3D : erreur explicite (câblage
    incomplet), pas de repli silencieux (CLAUDE.md)."""
    by_model = entry.get("occupied_hexes_by_model")
    floor_h = entry.get("floor_height_by_model")
    if not by_model or floor_h is None or "MODEL_HEIGHT" not in entry:
        raise ValueError(
            "engagement 3D demandé mais entrée-cache sans données verticales "
            "(occupied_hexes_by_model / floor_height_by_model / MODEL_HEIGHT) — câblage incomplet"
        )
    classes: Dict[float, List[Tuple[int, int]]] = {}
    for mid, (col, row) in by_model.items():
        h = float(require_key(floor_h, mid))
        classes.setdefault(h, []).append((int(col), int(row)))
    return classes, float(entry["MODEL_HEIGHT"])


def entry_vertically_reachable(
    cand_floor_inches: float,
    cand_model_height: float,
    entry: Dict[str, Any],
    vertical_zone_inches: float,
) -> bool:
    """True si ≥1 figurine de ``entry`` est à **portée verticale** d'un candidat mono-niveau.

    Le candidat occupe l'intervalle vertical ``[cand_floor, cand_floor + cand_model_height]`` ; on teste
    la séparation d'intervalles (§01.04, même formule que ``_entries_in_engagement_zone_3d``) contre
    **chaque classe de hauteur** de ``entry``. Sert aux chemins d'engagement qui court-circuitent la
    primitive par un test d'empreinte 2D (masque dilaté) : le gate vertical y est appliqué en amont,
    par-ennemi, tandis que le test horizontal reste l'intersection de sets. Approximation assumée : le
    couplage horizontal/vertical par-figurine n'est pas exact (union horizontale + gate vertical global),
    mais conservateur et bien plus correct que le 2D pur (rejette un ennemi hors des 5" verticaux)."""
    classes, entry_height = _vertical_classes(entry)
    lo_c, hi_c = cand_floor_inches, cand_floor_inches + cand_model_height
    for floor_e in classes:
        lo_e, hi_e = floor_e, floor_e + entry_height
        if max(0.0, max(lo_c, lo_e) - min(hi_c, hi_e)) <= vertical_zone_inches:
            return True
    return False


def _entries_in_engagement_zone_3d(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    vertical_zone_inches: float,
) -> bool:
    """Engagement 3D euclidien par paire de figurines (cf. ``entries_in_engagement_zone``).

    Pour chaque paire de classes verticales (hauteur de plancher) des deux unités, on applique
    d'abord le **gate vertical** (séparation des intervalles ``[plancher, plancher+MODEL_HEIGHT]``),
    puis — seulement si la paire passe — le **test horizontal** euclidien inchangé sur le sous-socle
    restreint aux centres de cette classe (réutilise ``euclidean_edge_distance``)."""
    from engine.combat_utils import socle_from_cache_entry

    a_classes, a_height = _vertical_classes(first_entry)
    b_classes, b_height = _vertical_classes(second_entry)
    threshold = engagement_minimum_clearance_norm(engagement_zone)
    base_a = socle_from_cache_entry(first_entry)
    base_b = socle_from_cache_entry(second_entry)
    for floor_a, centers_a in a_classes.items():
        lo_a, hi_a = floor_a, floor_a + a_height
        for floor_b, centers_b in b_classes.items():
            lo_b, hi_b = floor_b, floor_b + b_height
            vertical_gap = max(0.0, max(lo_a, lo_b) - min(hi_a, hi_b))
            if vertical_gap > vertical_zone_inches:
                continue
            socle_a = base_a._replace(model_centers=centers_a)
            socle_b = base_b._replace(model_centers=centers_b)
            if euclidean_edge_distance(socle_a, socle_b) <= threshold:
                return True
    return False


def unit_entries_within_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    metric: Optional[str] = None,
    vertical_zone_inches: Optional[float] = None,
) -> bool:
    """Return True when two unit cache entries are within the shared engagement contract.

    Primitive canonique EZ (règle 03.04, bord-à-bord). ``metric`` :
    - ``None`` (défaut) → résolue via ``engagement_distance_metric`` (config-loader global) : tous
      les call-sites GAMEPLAY basculent automatiquement à la config 7.6, sans changement de signature.
    - explicite (``"hex"``) → épinglé, pour les call-sites qui doivent rester hex indépendamment de
      la config (observations/récompenses IA, §10 — retrain hors périmètre migration).
    Config ``engagement:"hex"`` (défaut actuel) → comportement byte-identique à l'historique.
    """
    if metric is None:
        metric = engagement_distance_metric()
    return entries_in_engagement_zone(
        first_entry, second_entry, engagement_zone, metric, vertical_zone_inches
    )


def unit_within_engagement_zone_footprints(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    engagement_zone: int,
    max_distance: Optional[int],
    vertical_zone_inches: Optional[float] = None,
) -> bool:
    """Return True when unit is within B/engagement range of at least one enemy footprint."""
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id_str)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache (dead or absent); cannot read engagement")

    unit_player = int(require_key(unit, "player"))
    for enemy_id, cache_entry in units_cache.items():
        if str(enemy_id) == unit_id_str:
            continue
        enemy_player = int(require_key(cache_entry, "player"))
        if enemy_player == unit_player:
            continue
        if unit_entries_within_engagement_zone(
            unit_entry, cache_entry, engagement_zone, vertical_zone_inches=vertical_zone_inches
        ):
            return True
    return False


def move_anchor_violates_engagement_clearance(
    game_state: Dict[str, Any],
    mover: Dict[str, Any],
    center_col: int,
    center_row: int,
    candidate_fp: Set[Tuple[int, int]],
    units_cache: Dict[str, Any],
    enemy_adjacent_hexes: Optional[Set[Tuple[int, int]]],
    *,
    enemy_cache_items: Optional[List[Tuple[Any, Any]]],
    engagement_zone_ez: int,
    vertical_zone_inches: Optional[float] = None,
) -> bool:
    """Return True when a move anchor violates the C/clearance engagement contract."""
    mover_id = str(require_key(mover, "id"))
    mover_player = int(require_key(mover, "player"))

    if engagement_zone_ez <= 1:
        if enemy_adjacent_hexes is None:
            ck = f"enemy_adjacent_hexes_player_{mover_player}"
            adjacent_hexes: Set[Tuple[int, int]] = require_key(game_state, ck)
        else:
            adjacent_hexes = enemy_adjacent_hexes
        for c, r in candidate_fp:
            if (c, r) in adjacent_hexes:
                return True
        return False

    # Métrique d'engagement unifiée (Étape 7.1) : routée via le switch pairwise. Config hex
    # (défaut) → distance d'empreinte, byte-identique à l'historique. Le mover candidat est
    # synthétisé en entrée-cache (empreinte candidate + socle du mover) pour alimenter le switch.
    metric = engagement_distance_metric()
    mover_entry = {
        "BASE_SHAPE": require_key(mover, "BASE_SHAPE"),
        "BASE_SIZE": require_key(mover, "BASE_SIZE"),
        "col": center_col,
        "row": center_row,
        "occupied_hexes": candidate_fp,
    }
    if enemy_cache_items is not None:
        enemy_iter: Any = enemy_cache_items
    else:
        enemy_iter = (
            (eid, ce)
            for eid, ce in units_cache.items()
            if str(eid) != mover_id and int(require_key(ce, "player")) != mover_player
        )

    for _, cache_entry in enemy_iter:
        if entries_in_engagement_zone(
            mover_entry, cache_entry, engagement_zone_ez, metric, vertical_zone_inches
        ):
            return True
    return False
