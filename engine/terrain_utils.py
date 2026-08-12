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
import threading
from typing import AbstractSet, Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

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
    from engine.spatial_relations import entry_footprint
    return [(int(h[0]), int(h[1])) for h in entry_footprint(entry)]


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


class _FloorIndex:
    """Vue dérivée des étages d'un terrain — construite UNE fois, relue partout.

    Les quatre accesseurs d'étage (``floor_levels_present``, ``floor_hexes_at_level``,
    ``floor_polys_at_level``, ``floor_height_at``) reconstruisaient chacun leur réponse en
    reparcourant TOUT ``terrain_areas`` à chaque appel : un `set` de tous les hexes de plancher,
    une liste de polygones avec un ``_hex_center`` par sommet, un `set` de plus pour la hauteur.
    C'est O(hexes de plancher + sommets) **par appel**.

    Ça ne se voyait pas tant que ces fonctions servaient au commit d'un mouvement. Depuis que la
    charge, le pile-in et la consolidation résolvent un niveau PAR CELLULE CANDIDATE
    (``resolve_model_floor_level`` dans les boucles de pool), c'est 10²–10³ reconstructions du
    même index par construction de pool, pour un terrain qui n'a pas bougé.
    """

    __slots__ = (
        "levels", "hexes_by_level", "height_by_cell", "_low_clearance",
        "_low_clearance_by_height", "_raw_floors_by_level", "_polys_by_level",
    )


    def __init__(self, terrain_areas: List[Dict[str, Any]]) -> None:
        _hexes: Dict[int, Set[Tuple[int, int]]] = {}
        # Polygones : construits À LA DEMANDE, jamais à l'indexation. ``polygon_vertices`` ne sert
        # qu'au confinement euclidien des socles RONDS (13.06) ; l'exiger ici ferait échouer
        # `floor_levels_present` / `floor_hexes_at_level` / `floor_height_at` /
        # `low_clearance_ground_hexes` sur un terrain sans cette clé, qu'aucune d'elles ne lisait.
        self._raw_floors_by_level: Dict[int, List[Dict[str, Any]]] = {}
        self._polys_by_level: Dict[int, List[List[Tuple[float, float]]]] = {}
        # (level, cell) -> height_inches. PAR POSITION et non par niveau : deux ruines peuvent
        # porter un étage au même `level` à des `height_inches` différents (stage.md §4.1).
        self.height_by_cell: Dict[Tuple[int, int, int], float] = {}
        # (height_inches du plancher) -> hexes, pour `low_clearance_ground_hexes` qui compare un
        # seuil variable (la taille du modèle) à une donnée fixe.
        self._low_clearance: List[Tuple[float, Set[Tuple[int, int]]]] = []
        # Union mémoïsée PAR HAUTEUR DEMANDÉE. Depuis que la hauteur est par-figurine, une même
        # phase interroge l'index une fois par figurine : sans ce mémo, chaque appel refait l'union
        # des planchers trop bas. Le nombre de hauteurs distinctes d'une bataille est minuscule
        # (une ou deux par escouade), et l'index est déjà indexé par identité de `terrain_areas`.
        self._low_clearance_by_height: Dict[float, Set[Tuple[int, int]]] = {}
        for area in terrain_areas:
            for floor in area.get("floors", []):  # get allowed (aire sans étage = sol seul)
                level = int(require_key(floor, "level"))
                cells = {(int(h[0]), int(h[1])) for h in require_key(floor, "hexes")}
                height = float(require_key(floor, "height_inches"))
                _hexes.setdefault(level, set()).update(cells)
                self._raw_floors_by_level.setdefault(level, []).append(floor)
                for cell in cells:
                    ckey = (level, cell[0], cell[1])
                    # Deux planchers qui se recouvrent au MÊME niveau avec des hauteurs
                    # DIFFÉRENTES : la case n'a pas de hauteur définie. La boucle d'origine
                    # rendait le premier trouvé, l'index le dernier écrit — deux arbitraires. Un
                    # état incohérent se signale, il ne s'arbitre pas (CLAUDE.md, pas de masquage).
                    previous = self.height_by_cell.get(ckey)  # get allowed (case pas encore vue)
                    if previous is not None and previous != height:
                        raise ValueError(
                            f"_FloorIndex: cell ({cell[0]}, {cell[1]}) is covered twice at level "
                            f"{level} with conflicting height_inches ({previous} vs {height})"
                        )
                    self.height_by_cell[ckey] = height
                self._low_clearance.append((height, cells))
        # FROZEN : ces sets sont partages par tous les appelants du terrain. Les figer rend
        # impossible qu'un consommateur mute l'index sous les autres.
        self.hexes_by_level: Dict[int, FrozenSet[Tuple[int, int]]] = {
            lv: frozenset(cells) for lv, cells in _hexes.items()
        }
        # TUPLE : rendu tel quel par `floor_levels_present`, donc immuable plutôt que recopié à
        # chaque appel pour protéger l'index.
        self.levels: Tuple[int, ...] = tuple(sorted(self.hexes_by_level))

    def polys(self, level: int) -> List[List[Tuple[float, float]]]:
        """Polygones du niveau, calculés au PREMIER appel puis mémoïsés (cf. ``__init__``)."""
        cached = self._polys_by_level.get(level)  # get allowed (niveau pas encore demandé)
        if cached is None:
            from engine.hex_utils import _hex_center
            cached = [
                [_hex_center(int(v[0]), int(v[1])) for v in require_key(floor, "polygon_vertices")]
                for floor in self._raw_floors_by_level.get(level, [])  # get allowed (niveau sans plancher)
            ]
            self._polys_by_level[level] = cached
        return cached

    def low_clearance(self, model_height: float) -> Set[Tuple[int, int]]:
        cached = self._low_clearance_by_height.get(float(model_height))
        if cached is not None:
            return cached
        blocked: Set[Tuple[int, int]] = set()
        for height, cells in self._low_clearance:
            if height < model_height:
                blocked |= cells
        self._low_clearance_by_height[float(model_height)] = blocked
        return blocked


# Mémo de l'index, clé = IDENTITÉ de la liste ``terrain_areas``.
#
# L'entrée garde une référence FORTE à la liste : c'est ce qui rend `id()` sûr ici — tant que la
# clé est dans le mémo, l'objet est vivant, donc son adresse ne peut pas être réattribuée à un
# autre terrain. Le mémo est borné, en FIFO : quelques terrains coexistent au plus (board courant,
# scénarios d'éval, fixtures de test).
#
# ``terrain_areas`` est normalement mis à l'échelle une fois au chargement
# (``GameState._downscale_terrain_data``, qui travaille sur une copie profonde des données de
# fichier) puis n'est plus muté. L'identité NE SUFFIT PAS à le garantir : une mutation en place
# (``floors[0]["hexes"].extend(...)``, comme le fait une fixture de test) laisserait servir un
# index périmé — des cellules légales rejetées par ``footprint_within_floor``, ou
# ``floor_height_at`` qui lève sur une case pourtant planchéiée, sans que rien ne désigne le
# cache. L'entrée mémoïsée porte donc une SIGNATURE de forme, relue à chaque accès et reconstruite
# si elle a bougé.
#
# VERROU : l'API Flask sert en multi-THREADS (``app.run`` par défaut). Scanner puis supprimer puis
# ajouter n'est pas atomique — deux requêtes concurrentes suffisent à ce qu'un `del` porte sur un
# index décalé par l'autre thread, jusqu'à l'``IndexError`` si la liste a raccourci entre-temps.
# Le mutex couvre toute l'opération ; il est non réentrant, ce qui est sûr car ni ``_FloorIndex``
# ni ``_floor_signature`` ne rappellent ``_floor_index``.
_FLOOR_INDEX_CACHE: "Dict[int, Tuple[List[Dict[str, Any]], Any, _FloorIndex]]" = {}
_FLOOR_INDEX_CACHE_MAX = 8
_FLOOR_INDEX_LOCK = threading.Lock()


def _floor_signature(terrain_areas: List[Dict[str, Any]]) -> Any:
    """Empreinte de FORME des étages — O(nombre de floors), pas O(nombre d'hexes).

    Suffit à détecter toute mutation en place qui change la structure (floor/hex ajouté ou retiré,
    niveau ou hauteur modifiés) : ce sont les seules mutations que le dépôt pratique. Une
    substitution de coordonnée à taille constante ne s'y verrait pas — l'index reste donc à ne pas
    muter en place case par case.

    Cette empreinte est relue à CHAQUE accès, sur un chemin parcouru 10²–10³ fois par construction
    de pool : elle est écrite pour être plate. Un aplatissement sur tous les étages (pas de tuple
    par aire, pas de longueur redondante) et l'accès direct aux clés (déjà validées par
    ``_FloorIndex`` ; leur absence lève un ``KeyError`` nommé) la ramènent de 24 µs à 6,8 µs sur un
    terrain réel de 22 étages — mesuré, à comparer aux 933 µs du rescan qu'elle remplace."""
    return tuple(
        (f["level"], f["height_inches"], len(f["hexes"]))
        for area in terrain_areas
        for f in area.get("floors", ())  # get allowed (aire sans étage = sol seul)
    )


def _floor_index(terrain_areas: List[Dict[str, Any]]) -> _FloorIndex:
    key = id(terrain_areas)
    signature = _floor_signature(terrain_areas)
    with _FLOOR_INDEX_LOCK:
        cached = _FLOOR_INDEX_CACHE.get(key)  # get allowed (terrain pas encore indexé)
        if cached is not None and cached[1] == signature:
            return cached[2]
        # Absent, ou terrain muté en place : l'entrée décrivait un état qui n'existe plus.
        index = _FloorIndex(terrain_areas)
        _FLOOR_INDEX_CACHE[key] = (terrain_areas, signature, index)
        if len(_FLOOR_INDEX_CACHE) > _FLOOR_INDEX_CACHE_MAX:
            # Un dict Python conserve l'ordre d'insertion : la première clé est la plus ancienne.
            del _FLOOR_INDEX_CACHE[next(iter(_FLOOR_INDEX_CACHE))]
        return index


def floor_levels_present(terrain_areas: List[Dict[str, Any]]) -> Tuple[int, ...]:
    """Niveaux d'étage (>= 1) réellement décrits par le terrain, triés croissant.

    Le sol (0) n'y figure pas : il n'a pas d'entrée ``floors``, il existe partout. Sert à borner les
    parcours multi-niveaux et à écarter d'emblée un niveau qu'aucune ruine ne porte."""
    return _floor_index(terrain_areas).levels


def floor_hexes_at_level(
    terrain_areas: List[Dict[str, Any]], level: int
) -> FrozenSet[Tuple[int, int]]:
    """Union des hexes de tous les étages (``floors``) au niveau donné (format B, >= 1).

    Le niveau 0 (rez-de-chaussée) n'a pas d'entrée ``floors`` : c'est la terrain area
    elle-même / le sol. Appeler cette fonction avec level 0 est une erreur d'usage.

    Le set rendu APPARTIENT à l'index mémoïsé — il est donc FROZEN, pas seulement « à ne pas
    muter » : la mutation est impossible plutôt que déconseillée.
    """
    if level < 1:
        raise ValueError(f"floor_hexes_at_level: level must be >= 1 (0 = ground), got {level}")
    return _floor_index(terrain_areas).hexes_by_level.get(level, frozenset())  # get allowed (niveau sans plancher)


def floor_polys_at_level(
    terrain_areas: List[Dict[str, Any]], level: int
) -> List[List[Tuple[float, float]]]:
    """Polygones (repère ``_hex_center``) de tous les étages au niveau donné (>= 1).

    Un polygone par ``floor`` à ce niveau (plusieurs ruines → plusieurs polygones). Sert au
    confinement euclidien « socle rond entièrement sur l'étage » (13.06), pendant continu de
    ``floor_hexes_at_level`` (méthode hex, conservée pour oval/carré). Niveau 0 = sol, pas de bord :
    usage interdit (erreur explicite, cohérent avec ``floor_hexes_at_level``)."""
    if level < 1:
        raise ValueError(f"floor_polys_at_level: level must be >= 1 (0 = ground), got {level}")
    return _floor_index(terrain_areas).polys(level)


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
    Aucun repli : une figurine marquee ``level >= 1`` dont la case n'appartient a aucun floor de
    ce niveau est une incoherence d'etat -> ``ValueError`` explicite (CLAUDE.md, pas de masquage)."""
    if int(level) <= 0:
        return 0.0
    height = _floor_index(terrain_areas).height_by_cell.get(  # get allowed (case hors plancher)
        (int(level), int(col), int(row))
    )
    if height is not None:
        return height
    raise ValueError(
        f"floor_height_at: no floor at level {level} contains cell ({col}, {row}) "
        f"(figurine marquee a l'etage mais hors empreinte de plancher)"
    )


def low_clearance_ground_hexes(
    terrain_areas: List[Dict[str, Any]],
    model_entry: Mapping[str, Any],
    squad_entry: Mapping[str, Any],
) -> Set[Tuple[int, int]]:
    """Hexes du SOL (niveau 0) infranchissables par LA FIGURINE ``model_entry`` (§13.06).

    Union des hexes des étages dont la hauteur libre ``height_inches`` est STRICTEMENT inférieure à
    la hauteur de la figurine : un modèle plus haut que la clairance ne peut ni traverser ni
    s'arrêter sous cet étage (même unité pouce que ``height_inches``, pas de scaling). Tangence
    (égalité) autorisée. Retourne un set vide si aucun étage n'est trop bas. À unir aux murs pour le
    pathfinding AU SOL uniquement (la surface de l'étage, elle, reste praticable).

    POURQUOI DEUX ENTRÉES ET NON UNE HAUTEUR. Cette fonction a longtemps pris un ``float`` nu : rien
    ne distinguait alors « hauteur de la figurine » de « hauteur de l'escouade », et ses onze
    appelants — des pools qui raisonnent par figurine pour tout le reste — passaient tous la
    seconde. Le défaut a dû être corrigé site par site, puis surveillé par un test qui relisait le
    TEXTE des handlers. En exigeant les deux entrées, la hauteur ne peut plus venir que de
    ``_model_height_of``, seule source de l'héritage figurine→escouade.

    LES DEUX RÔLES SONT VÉRIFIÉS, pas seulement documentés. Une signature à deux entrées de même
    forme laisse écrire ``(units_cache[squad_id], unit)`` ou l'ordre inverse : la hauteur
    d'escouade repasserait en silence, et c'est exactement le défaut d'origine. On exige donc la
    MARQUE de chaque rôle — ``squad_id`` n'existe que sur une entrée de ``models_cache``, ``id``
    que sur une unité. Les deux fautes lèvent au lieu de mesurer faux.

    ⚠️ Le set rendu est MÉMOÏSÉ par hauteur : les appelants le lisent, ils ne le mutent jamais. Une
    mutation en place corromprait la clairance de toutes les figurines de cette taille pour le
    reste de la bataille."""
    # Import local : `shared_utils` importe `terrain_utils`, l'inverse au chargement fermerait le
    # cycle. Même convention que les autres primitives inter-modules de ce fichier.
    from engine.phase_handlers.shared_utils import _model_height_of

    if "squad_id" not in model_entry:
        raise ValueError(
            "low_clearance_ground_hexes: `model_entry` doit être une entrée de `models_cache` "
            "(une FIGURINE, reconnaissable à sa clé `squad_id`). La clairance se mesure par "
            "figurine (§13.06) ; passer l'escouade y ramènerait le défaut que cette signature "
            f"existe pour interdire. Reçu les clés : {sorted(model_entry)[:8]}"
        )
    if "id" not in squad_entry:
        raise ValueError(
            "low_clearance_ground_hexes: `squad_entry` doit être l'unité (`game_state['units']`, "
            "reconnaissable à sa clé `id`) — elle ne sert que d'héritage quand la figurine ne "
            f"porte pas sa hauteur. Reçu les clés : {sorted(squad_entry)[:8]}"
        )
    return _floor_index(terrain_areas).low_clearance(
        _model_height_of(model_entry, squad_entry)
    )


def footprint_within_floor(
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    floor_hexes: AbstractSet[Tuple[int, int]],
    floor_polys: Optional[List[List[Tuple[float, float]]]] = None,
) -> bool:
    """True si le socle tient ENTIÈREMENT sur l'étage (règle 13.06 : aucun débordement du bord).

    Base RONDE avec ``floor_polys`` fourni : test euclidien continu disque↔polygone(s)
    (``disc_within_any_polygon``) — aligné pixel-pour-pixel sur le rendu (disque d'icône + polygone
    d'étage), supprime le débordement d'~½ hex que la rasterisation hex tolérait. Base OVAL/CARRÉ (ou
    ``floor_polys`` absent) : méthode empreinte hex — tous les hexes du socle doivent appartenir à
    ``floor_hexes`` (union des hexes de l'étage). Convention hybride identique à ``model_within_terrain``
    (round=euclidien, autres=hex). ``floor_hexes`` / ``floor_polys`` vides → False (pas de surface).

    N.B. la règle exige aussi une position « stable » (13.06), non chiffrée dans les règles et
    non modélisable ici : non représentée (surface d'étage supposée plane).
    """
    if base_shape == "round" and floor_polys is not None:
        from engine.hex_utils import (
            _hex_center, round_base_radius_norm, disc_within_any_polygon,
            require_scalar_base_size,
        )
        cx, cy = _hex_center(int(col), int(row))
        r = round_base_radius_norm(
            require_scalar_base_size(base_shape, base_size, "footprint_within_floor")
        )
        return disc_within_any_polygon(cx, cy, r, floor_polys)
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
    # UN seul passage par le mémo : cette fonction est appelée par cellule candidate (boucles de
    # pool charge / pile-in / consolidation), et chaque passage revalide la signature du terrain.
    index = _floor_index(terrain_areas)
    fh = index.hexes_by_level.get(requested_level, frozenset())  # get allowed (niveau sans plancher)
    # Base ronde : confinement euclidien (aucun débordement du bord) ; oval/carré : hex.
    fpoly = index.polys(requested_level) if base_shape == "round" else None
    if fh and footprint_within_floor(col, row, base_shape, base_size, orientation, fh, fpoly):
        return requested_level
    return 0


def resolved_floor_height_at(
    terrain_areas: List[Dict[str, Any]],
    col: int,
    row: int,
    base_shape: str,
    base_size: "int | list[int]",
    orientation: int,
    requested_level: int,
) -> float:
    """Hauteur du plancher SOUS une figurine posée en ``(col, row)`` avec ce niveau DEMANDÉ.

    Un niveau est une DEMANDE, pas un fait : c'est le plancher qui tranche (§13.06). Cette
    fonction enchaîne donc ``resolve_model_floor_level`` puis ``floor_height_at`` — la même
    résolution que le move et le déploiement appliquent au commit.

    ``floor_height_at`` seule LÈVE sur une case sans plancher au niveau demandé. C'est le bon
    contrat pour un état déjà résolu, mais pas pour un CANDIDAT : une position hypothétique hors
    plancher n'est pas un état corrompu, c'est une figurine au sol. Passer par ici évite qu'un
    pool de destinations, un aperçu en lecture seule ou une translation rigide ne plante là où la
    règle demande simplement de poser la figurine au niveau 0.
    """
    level = resolve_model_floor_level(
        col, row, base_shape, base_size, orientation, requested_level, terrain_areas
    )
    return floor_height_at(terrain_areas, col, row, level)


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
    base_shape = require_key(unit, "BASE_SHAPE")
    # Base ronde : confinement euclidien (aucun débordement du bord) ; oval/carré : hex.
    floor_polys = floor_polys_at_level(terrain_areas, level) if base_shape == "round" else None
    if not footprint_within_floor(
        col, row, base_shape, require_key(unit, "BASE_SIZE"), orientation, floor_hexes, floor_polys
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
        from engine.hex_utils import (
            _hex_center, round_base_radius_norm, disc_overlaps_polygon,
            require_scalar_base_size,
        )
        cx, cy = _hex_center(int(col), int(row))
        r = round_base_radius_norm(
            require_scalar_base_size(base_shape, base_size, "model_within_terrain")
        )
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
