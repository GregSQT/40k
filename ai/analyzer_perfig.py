"""analyzer_perfig.py — couche per-figurine de l'analyzer (V11).

Le step logger émet, en fin de chaque ligne d'action et avant [SUCCESS]/[FAILED],
un segment `[MODELS: <mid>@(<col>,<row>) ...]` listant les socles VIVANTS de
l'unité qui agit (les socles morts disparaissent). `<mid>` = `<unit_id>#<index>`.

Ce module :
  - parse ce segment (parse_models_segment) ;
  - reconstruit des empreintes de socle (footprints) via les helpers moteur
    (engine.hex_utils.compute_occupied_hexes / min_distance_between_sets), garantissant
    la parité géométrique avec le jeu ;
  - fournit les primitives per-socle utilisées par les handlers pour remplacer les
    contrôles ancre-à-ancre (portée, adjacence de combat, distance de move).

Aucun fallback masquant une erreur : si une donnée requise manque, on lève.
"""

import re
from typing import Dict, List, Optional, Set, Tuple, Union

from engine.hex_utils import compute_occupied_hexes, min_distance_between_sets

# `<mid>@(<col>,<row>)` — mid = token sans espace contenant '#'
_MODELS_RE = re.compile(r'\[MODELS:\s*([^\]]+)\]')
_TARGET_MODELS_RE = re.compile(r'\[TARGET_MODELS:\s*([^\]]+)\]')
_TOKEN_RE = re.compile(r'(\S+?#\S*?)@\((-?\d+),\s*(-?\d+)\)')

# Taille de socle telle que l'attend le moteur (`compute_occupied_hexes`) : diamètre entier pour
# un socle rond, [major, minor] pour un ovale.
BaseSize = Union[int, List[int]]
Base = Tuple[str, BaseSize]

# Base par défaut si un socle n'a pas de base connue : round diamètre 1 (1 hex).
# Utilisé uniquement quand aucune ligne "Starting position ... base=" n'a été vue
# (logs de test synthétiques) — jamais pour masquer une erreur métier.
_DEFAULT_BASE: Base = ("round", 1)

_fp_cache: Dict[Tuple[int, int, str, Union[int, Tuple[int, ...]]], frozenset] = {}


def parse_base_token(token: str) -> Base:
    """Parse un token `base=round/6` ou `base=oval/[20, 14]` → (shape, size)."""
    if not token.startswith("base="):
        raise ValueError(f"Base token invalide: {token!r}")
    body = token[len("base="):]
    shape, _, size_str = body.partition("/")
    if not shape or not size_str:
        raise ValueError(f"Base token invalide: {token!r}")
    if size_str.startswith("["):
        nums = [int(n) for n in re.findall(r'-?\d+', size_str)]
        if len(nums) != 2:
            raise ValueError(f"Base oval attend [major, minor]: {token!r}")
        return (shape, nums)
    return (shape, int(size_str))


def parse_models_segment(text: str) -> Optional[Dict[str, Dict[str, Tuple[int, int]]]]:
    """Extrait le segment [MODELS:] → {unit_id: {mid: (col,row)}}.

    unit_id = préfixe de mid avant '#'. Retourne None si aucun segment (ligne
    sans suffixe per-figurine, p.ex. logs anciens/synthétiques).
    """
    m = _MODELS_RE.search(text)
    if not m:
        return None
    result: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for tok in _TOKEN_RE.finditer(m.group(1)):
        mid = tok.group(1)
        col = int(tok.group(2))
        row = int(tok.group(3))
        unit_id = mid.split('#', 1)[0]
        result.setdefault(unit_id, {})[mid] = (col, row)
    if not result:
        raise ValueError(f"Segment [MODELS:] présent mais vide/illisible: {m.group(1)[:120]}")
    return result


def _model_footprint(col: int, row: int, base: Base) -> frozenset:
    shape, size = base
    key = (col, row, shape, size if isinstance(size, int) else tuple(size))
    cached = _fp_cache.get(key)
    if cached is not None:
        return cached
    fp = frozenset(compute_occupied_hexes(col, row, shape, size, 0))
    _fp_cache[key] = fp
    return fp


def _unit_base(unit_base: Dict[str, Base], unit_id: str) -> Base:
    return unit_base.get(unit_id, _DEFAULT_BASE)


def squad_footprint(
    models: Dict[str, Tuple[int, int]],
    base: Base,
) -> Set[Tuple[int, int]]:
    """Union des empreintes de tous les socles vivants d'une escouade."""
    fp: Set[Tuple[int, int]] = set()
    for (col, row) in models.values():
        fp |= _model_footprint(col, row, base)
    return fp


def move_start_status(
    models: Optional[Dict[str, Tuple[int, int]]],
    base: Base,
    anchor_stored: Optional[Tuple[int, int]],
    start_col: int,
    start_row: int,
    models_invalidated: bool = False,
) -> str:
    """Statut de cohérence de la position de départ loggée d'un déplacement (contrôle 2.2,
    version per-figurine). Retourne l'un de :

    - ``'mismatch'``  : départ HORS de l'empreinte des socles de départ connus (dernier segment
      [MODELS:]) → vraie incohérence (téléportation / log manquant).
    - ``'absorbed'``  : départ cohérent géométriquement (dans l'empreinte) mais ≠ ancre
      mémorisée → bruit de recalcul d'ancre d'escouade moteur (±1 subhex entre une consolidation
      et l'advance suivant, socles inchangés). Compté pour information, pas une erreur.
    - ``'exact'``     : départ = ancre mémorisée.

    Sans donnée per-figurine (log sans [MODELS:]) : repli ancre-à-ancre → ``'exact'`` si
    égalité, sinon ``'mismatch'``."""
    start = (start_col, start_row)
    if not models:
        if models_invalidated:
            # Socles invalidés par une perte de figurine : l'ancre d'ESCOUADE se recalcule sans
            # que l'unité ait agi, donc l'écart avec le départ logué est du bruit d'ancre. On
            # ne sait plus, on ne conclut pas — « jamais su » et « ne sait plus » se traitent
            # différemment, sinon toute escouade fauchée remonte une fausse téléportation.
            return "exact" if anchor_stored == start else "absorbed"
        return "exact" if anchor_stored == start else "mismatch"
    if start not in squad_footprint(models, base):
        return "mismatch"
    return "exact" if anchor_stored == start else "absorbed"


def squads_min_edge_distance(
    models_a: Dict[str, Tuple[int, int]],
    base_a: Base,
    models_b: Dict[str, Tuple[int, int]],
    base_b: Base,
    max_distance: int = 0,
) -> int:
    """Distance bord-à-bord minimale (subhexes) entre le socle le plus proche de A et
    celui de B — parité moteur (min_distance_between_sets sur empreintes)."""
    fp_a = squad_footprint(models_a, base_a)
    fp_b = squad_footprint(models_b, base_b)
    if not fp_a or not fp_b:
        raise ValueError("squads_min_edge_distance: empreinte vide (escouade sans socle vivant)")
    return min_distance_between_sets(fp_a, fp_b, max_distance=max_distance)


def resolve_weapon_value(
    weapon_name: str,
    per_unit_map: Dict[str, int],
    global_map: Dict[str, int],
) -> Optional[int]:
    """Résout le NB (ou une autre valeur entière) d'une arme loguée au niveau escouade.

    Ordre : (1) carte per-unit-type ; (2) si le nom est un profil composite « A / B »
    (armes de profil identique fusionnées par le moteur, cf. shared_utils
    _build_multi_hex... " / ".join), on résout CHAQUE composante et on retient le MAX
    (plafond générique — voir Class B) ; (3) carte globale tous model-types.
    Retourne None si irrésolu (vraie donnée manquante — on laisse l'erreur remonter).
    """
    name = weapon_name.strip()
    if name in per_unit_map:
        return per_unit_map[name]
    if " / " in name:
        vals = []
        for part in name.split(" / "):
            part = part.strip()
            v = per_unit_map.get(part)
            if v is None:
                v = global_map.get(part)
            if v is not None:
                vals.append(v)
        if vals:
            return max(vals)
        return None
    if name in global_map:
        return global_map[name]
    return None


def models_for_unit(
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]],
    unit_id: str,
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Socles vivants connus pour unit_id, ou None si jamais vu en per-figurine."""
    m = positions_by_model.get(unit_id)
    if not m:
        return None
    return m


def surviving_start_models(
    prev_models: Optional[Dict[str, Tuple[int, int]]],
    line_models: Optional[Dict[str, Tuple[int, int]]],
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Socles d'une escouade AVANT son action, réduits à ceux qui y ont survécu.

    `positions_by_model` porte le dernier `[MODELS:]` où l'unité était l'ACTRICE : une escouade
    fauchée pendant le tir adverse y garde ses socles morts jusqu'à sa prochaine action. Mesurer
    l'engagement de départ sur ce jeu-là, c'est le mesurer sur des figurines retirées du plateau
    — un « advance from adjacent » a été fabriqué exactement comme ça.

    Les VIVANTS sont listés par le `[MODELS:]` de la ligne en cours, leurs positions de DÉPART
    par le jeu précédent : on croise les deux. Même convention que le contrôle de distance
    per-socle du move (`common_mids`). Retourne None si le croisement est vide — l'appelant
    retombe alors sur l'ancre, donnée absente plutôt que mesure fausse.
    """
    if not prev_models or not line_models:
        return prev_models or None
    survivors = {mid: pos for mid, pos in prev_models.items() if mid in line_models}
    return survivors or None


def footprint_or_anchor(
    unit_id: str,
    models: Optional[Dict[str, Tuple[int, int]]],
    unit_base: Dict[str, Base],
    anchor: Optional[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """Empreinte d'une escouade : ses socles si on les connaît, son ancre sinon.

    Repli unique de tout l'analyzer sur ce point. Il était écrit en trois exemplaires (mesure
    d'engagement, obstacles du BFS de mouvement, engagement tireur↔cible) : le jour où le repli
    change — lever plutôt que rendre l'ancre, par exemple — trois copies devraient suivre.
    Empreinte VIDE (aucun socle, aucune ancre) = donnée absente, l'appelant décide.
    """
    if models:
        return squad_footprint(models, _unit_base(unit_base, unit_id))
    return {anchor} if anchor is not None else set()


def model_cache_entries(
    unit_id: str,
    models: Optional[Dict[str, Tuple[int, int]]],
    unit_base: Dict[str, Base],
    anchor: Optional[Tuple[int, int]],
    player: int,
) -> List[Dict[str, object]]:
    """Entrées `units_cache` moteur — UNE PAR FIGURINE, socle réel.

    Les primitives d'engagement du moteur (`entries_in_engagement_zone`) mesurent entre DEUX
    entrées : en métrique hex par empreintes, en métrique euclidienne par
    `socle_from_cache_entry`, qui lit `BASE_SHAPE`/`BASE_SIZE` **et l'ancre** de l'entrée. Une
    entrée par ESCOUADE y perdrait donc toutes les figurines sauf l'ancre dès que la métrique
    est euclidienne — exactement le défaut qu'on corrige. Une entrée par figurine rend la mesure
    per-socle exacte quelle que soit la métrique.

    Sans donnée per-figurine : une seule entrée à l'ancre (donnée absente, pas mesure fausse).
    """
    shape, size = _unit_base(unit_base, unit_id)
    positions = list(models.values()) if models else ([anchor] if anchor is not None else [])
    return [
        {
            "col": col, "row": row, "player": int(player),
            "occupied_hexes": _model_footprint(col, row, (shape, size)),
            "BASE_SHAPE": shape, "BASE_SIZE": size, "orientation": 0,
        }
        for (col, row) in positions
    ]


def squads_min_ranged_distance(
    models_a: Dict[str, Tuple[int, int]],
    base_a: Base,
    models_b: Dict[str, Tuple[int, int]],
    base_b: Base,
    metric: str,
    max_distance: int = 0,
) -> float:
    """Distance de PORTÉE minimale entre deux escouades, socle par socle (10 Shooting / 06.01).

    À portée si AU MOINS un socle tireur atteint AU MOINS un socle cible. La mesure passe par
    `engine.combat_utils.ranged_edge_distance`, donc par la métrique que le moteur applique —
    `min_distance_between_sets` seul fige le hex, et douze tirs légaux en euclidien
    ressortaient « out of range » à x1 pour cette seule raison.
    """
    from engine.combat_utils import ranged_edge_distance
    from engine.hex_utils import Socle

    def _socles(models: Dict[str, Tuple[int, int]], base: Base) -> List:
        shape, size = base
        return [
            Socle(shape, size, col, row, set(_model_footprint(col, row, base)))
            for (col, row) in models.values()
        ]

    socles_a = _socles(models_a, base_a)
    socles_b = _socles(models_b, base_b)
    if not socles_a or not socles_b:
        raise ValueError("squads_min_ranged_distance: escouade sans socle")
    return min(
        ranged_edge_distance(sa, sb, metric, max_distance=max_distance)
        for sa in socles_a
        for sb in socles_b
    )


def parse_target_models_segment(text: str) -> Optional[Dict[str, Tuple[int, int]]]:
    """Socles SURVIVANTS de la cible, depuis le segment `[TARGET_MODELS:]` de la ligne.

    Le step logger l'écrit sur le DERNIER jet visant cette cible, après retrait des pertes
    (cf. `ai/step_logger.py`) : c'est la seule donnée fraîche sur une unité qui subit sans agir.
    `positions_by_model` d'une cible, lui, date de sa dernière ACTION — et il est effacé dès
    qu'elle perd une figurine, faute de savoir laquelle. Sans ce segment, la portée se mesurait
    contre l'ANCRE de l'escouade, alors que le moteur mesure contre la figurine la plus proche.

    Retourne None si le segment est absent (jets intermédiaires d'un même groupe).
    """
    m = _TARGET_MODELS_RE.search(text)
    if not m:
        return None
    models: Dict[str, Tuple[int, int]] = {}
    for tok in _TOKEN_RE.finditer(m.group(1)):
        models[tok.group(1)] = (int(tok.group(2)), int(tok.group(3)))
    if not models:
        raise ValueError(f"Segment [TARGET_MODELS:] présent mais illisible: {m.group(1)[:120]}")
    return models
