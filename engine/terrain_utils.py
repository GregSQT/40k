"""Terrain area membership helpers (hex-based).

Terrain areas are polygon zones rasterized to board hexes at load time
(see ``game_state._load_terrain_areas_from_ref``). Each area dict holds:
  - ``id``: str
  - ``obscuring``: bool
  - ``polygon_vertices``: list[[col, row]]
  - ``hexes``: list[[col, row]]  (rasterized membership, odd-q projection)

Membership is answered by testing hex appartenance against the precomputed
``hexes`` sets — same odd-q projection as objectives and the frontend renderer,
so a unit "within a terrain area" matches exactly what the player sees on board.
"""
from typing import Any, Dict, List, Set, Tuple, cast

from shared.data_validation import require_key


def _area_hex_set(area: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return the area's rasterized hexes as a set of (col, row).

    Built inline (no mutation of the area dict) so terrain areas stay JSON-serializable.
    """
    return {(int(h[0]), int(h[1])) for h in require_key(area, "hexes")}


def resolve_unit_hexes(unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Return the list of (col, row) hexes occupied by a unit's footprint."""
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(str(require_key(unit, "id")))
    if not isinstance(entry, dict):
        raise KeyError(f"unit {unit.get('id')!r} not present in units_cache")
    occ = entry.get("occupied_hexes")
    if isinstance(occ, (set, list, tuple)) and len(occ) > 0:
        return [(int(h[0]), int(h[1])) for h in occ]
    return [(int(require_key(entry, "col")), int(require_key(entry, "row")))]


def get_terrain_area_ids_for_hexes(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> List[str]:
    """IDs of terrain areas containing at least one of the unit's hexes."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    ids: List[str] = []
    for area in terrain_areas:
        if unit_set & _area_hex_set(area):
            ids.append(str(require_key(area, "id")))
    return ids


def hexes_in_any_terrain(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> bool:
    """True if the unit's footprint touches at least one terrain area (any kind)."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    for area in terrain_areas:
        if unit_set & _area_hex_set(area):
            return True
    return False


def hexes_in_obscuring_terrain(
    unit_hexes: List[Tuple[int, int]],
    terrain_areas: List[Dict[str, Any]],
) -> bool:
    """True if the unit's footprint touches at least one obscuring terrain area."""
    unit_set = {(int(c), int(r)) for c, r in unit_hexes}
    for area in terrain_areas:
        if area.get("obscuring") and (unit_set & _area_hex_set(area)):
            return True
    return False


def floor_hexes_at_level(terrain_areas: List[Dict[str, Any]], level: int) -> Set[Tuple[int, int]]:
    """Union des hexes de tous les étages (``floors``) au niveau donné (format B, >= 1).

    Le niveau 0 (rez-de-chaussée) n'a pas d'entrée ``floors`` : c'est la terrain area
    elle-même / le sol. Appeler cette fonction avec level 0 est une erreur d'usage.
    """
    if level < 1:
        raise ValueError(f"floor_hexes_at_level: level must be >= 1 (0 = ground), got {level}")
    hexes: Set[Tuple[int, int]] = set()
    for area in terrain_areas:
        for floor in area.get("floors", []):  # get allowed (aire sans étage = sol seul)
            if int(require_key(floor, "level")) == level:
                hexes.update((int(h[0]), int(h[1])) for h in require_key(floor, "hexes"))
    return hexes


def floor_height_at(
    terrain_areas: List[Dict[str, Any]],
    col: int,
    row: int,
    level: int,
) -> float:
    """Hauteur (pouces) du plancher sous une figurine à ``(col, row, level)``.

    Rez-de-chaussée (``level`` <= 0) = ``0.0`` (retour immédiat, cas courant, aucune itération).
    Niveau >= 1 : ``height_inches`` du floor (format B) contenant la case ``(col, row)`` à ce niveau.
    La résolution est PAR POSITION (pas un mapping global niveau->hauteur) : deux ruines peuvent
    avoir un floor au même ``level`` avec des ``height_inches`` differents (cf. stage.md §4.1).
    Aucun fallback : une figurine marquee ``level >= 1`` dont la case n'appartient a aucun floor de
    ce niveau est une incoherence d'etat -> ``ValueError`` explicite (CLAUDE.md, pas de masquage)."""
    if int(level) <= 0:
        return 0.0
    cell = (int(col), int(row))
    for area in terrain_areas:
        for floor in area.get("floors", []):  # get allowed (aire sans etage = sol seul)
            if int(require_key(floor, "level")) == int(level):
                floor_hexes = {(int(h[0]), int(h[1])) for h in require_key(floor, "hexes")}
                if cell in floor_hexes:
                    return float(require_key(floor, "height_inches"))
    raise ValueError(
        f"floor_height_at: no floor at level {level} contains cell ({col}, {row}) "
        f"(figurine marquee a l'etage mais hors empreinte de plancher)"
    )


def low_clearance_ground_hexes(
    terrain_areas: List[Dict[str, Any]],
    model_height: float,
) -> Set[Tuple[int, int]]:
    """Hexes du SOL (niveau 0) infranchissables par un modèle de hauteur ``model_height`` (pouces).

    Union des hexes des étages dont la hauteur libre ``height_inches`` est STRICTEMENT inférieure à
    ``model_height`` : un modèle plus haut que la clairance ne peut ni traverser ni s'arrêter sous cet
    étage (même unité pouce que ``height_inches``, pas de scaling). Tangence (égalité) autorisée.
    Retourne un set vide si aucun étage n'est trop bas. À unir aux murs pour le pathfinding AU SOL
    uniquement (la surface de l'étage, elle, reste praticable)."""
    blocked: Set[Tuple[int, int]] = set()
    mh = float(model_height)
    for area in terrain_areas:
        for floor in area.get("floors", []):  # get allowed (aire sans étage)
            if float(require_key(floor, "height_inches")) < mh:
                blocked.update((int(h[0]), int(h[1])) for h in require_key(floor, "hexes"))
    return blocked


def footprint_within_floor(
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    floor_hexes: Set[Tuple[int, int]],
) -> bool:
    """True si le socle tient ENTIÈREMENT sur l'étage (règle 13.06 : aucun débordement du bord).

    Convention hex : tous les hexes de l'empreinte du socle doivent appartenir à ``floor_hexes``
    (union des hexes de l'étage). 100% dedans = règle officielle (décision §5.1, défaut).
    ``floor_hexes`` vide → aucun étage à ce niveau → False (pas de surface où tenir).

    N.B. la règle exige aussi une position « stable » (13.06), non chiffrée dans les règles et
    non modélisable en hex plan : non représentée ici (surface d'étage supposée plane).
    """
    if not floor_hexes:
        return False
    from engine.hex_utils import compute_occupied_hexes
    fp = {
        (int(c), int(r))
        for c, r in compute_occupied_hexes(int(col), int(row), base_shape, base_size, int(orientation))
    }
    if not fp:
        raise ValueError(f"footprint_within_floor: empreinte vide pour socle ({base_shape},{base_size})")
    return fp <= floor_hexes


def resolve_model_floor_level(
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    requested_level: int,
    terrain_areas: List[Dict[str, Any]],
) -> int:
    """Niveau EFFECTIF d'une figurine posée à ``(col, row)``.

    ``requested_level`` (= étage courant de la vue) est un HINT : la fig est réellement sur cet étage
    seulement si son empreinte tient entièrement sur un plancher de ce niveau (13.06). Sinon elle est
    au **sol (0)** — une fig hors empreinte d'étage n'est pas 'illégale', elle est simplement au sol.
    Permet un déploiement/move d'escouade MIXTE (certaines figs sur l'étage, d'autres au sol) sans que
    les figs de sol soient rejetées parce que la vue est sur l'étage. La légalité mot-clé (§13.06) reste
    contrôlée par ``validate_floor_placement`` pour les figs effectivement sur l'étage.
    """
    if requested_level is None or requested_level < 1:
        return 0
    fh = floor_hexes_at_level(terrain_areas, requested_level)
    if fh and footprint_within_floor(col, row, base_shape, base_size, orientation, fh):
        return requested_level
    return 0


def validate_floor_placement(
    unit: Dict[str, Any],
    col: int,
    row: int,
    level: int,
    terrain_areas: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Valide qu'une figurine peut finir un move / être posée à ``(col, row, level)`` (règle 13.06).

    - Niveau 0 (rez-de-chaussée) : toujours autorisé (aucune contrainte d'étage).
    - Niveau >= 1 : exige les DEUX conditions de 13.06 :
        (a) mot-clé INFANTRY / BEASTS / SWARM / FLY / MONSTER ;
        (b) empreinte du socle ENTIÈREMENT sur un étage de ce niveau (aucun débordement).

    Retourne ``(ok, reason)`` — ``reason`` vide si ok, sinon motif explicite du refus (pour
    remonter une erreur claire côté move/déploiement, jamais un placement silencieusement corrigé).
    """
    if level < 0:
        raise ValueError(f"validate_floor_placement: level must be >= 0, got {level}")
    if level == 0:
        return (True, "")
    from engine.game_state import unit_can_occupy_upper_floor
    if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
        return (False, f"unit {unit.get('id')!r} lacks INFANTRY/BEASTS/SWARM/FLY/MONSTER (13.06) for level {level}")
    floor_hexes = floor_hexes_at_level(terrain_areas, level)
    if not floor_hexes:
        return (False, f"no floor declared at level {level}")
    orientation = int(require_key(unit, "orientation")) if "orientation" in unit else 0
    if not footprint_within_floor(
        col, row, require_key(unit, "BASE_SHAPE"), require_key(unit, "BASE_SIZE"), orientation, floor_hexes
    ):
        return (False, f"footprint at ({col},{row}) overhangs the level {level} floor edge (13.06)")
    return (True, "")


def model_within_terrain(
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    terrain_areas: List[Dict[str, Any]],
    obscuring_only: bool,
) -> bool:
    """True si le socle d'un modèle est « within a terrain area » (règles 13.08 / 13.09).

    Base RONDE : test euclidien continu disque↔polygone (``disc_overlaps_polygon`` sur les
    ``polygon_vertices``), pendant fig↔terrain de ``euclidean_edge_clearance_round_round``
    (fig↔fig) — aligné pixel-pour-pixel sur le rendu (disque d'icône + polygone terrain),
    contrairement à l'intersection de hexes rasterisés qui rogne ~½ hex de chaque côté.
    Base OVAL/SQUARE : méthode empreinte hex (intersection cellules), exactement la même
    convention hybride que l'engagement (round=euclidien, autres=hex).

    ``obscuring_only=True`` restreint aux zones obscurantes (hidden 13.09) ; ``False`` = toute
    zone de terrain (cover 13.08, volet « within terrain area »)."""
    areas = [a for a in terrain_areas if (not obscuring_only or a.get("obscuring"))]
    if not areas:
        return False
    if base_shape == "round":
        from engine.hex_utils import _hex_center, round_base_radius_norm, disc_overlaps_polygon
        cx, cy = _hex_center(int(col), int(row))
        r = round_base_radius_norm(cast(float, base_size))
        for area in areas:
            poly = [_hex_center(int(v[0]), int(v[1])) for v in require_key(area, "polygon_vertices")]
            if disc_overlaps_polygon(cx, cy, r, poly):
                return True
        return False
    # Base non ronde (oval/square) : empreinte hex, comme l'engagement.
    from engine.hex_utils import compute_occupied_hexes
    fp = {
        (int(c), int(r))
        for c, r in compute_occupied_hexes(int(col), int(row), base_shape, base_size, int(orientation))
    }
    for area in areas:
        if fp & _area_hex_set(area):
            return True
    return False
