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
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from engine.hex_utils import compute_occupied_hexes, min_distance_between_sets
from shared.data_validation import require_key

# `<mid>@(<col>,<row>)` ou `<mid>@(<col>,<row>,z<hauteur>)` — mid = token sans espace contenant '#'.
#
# `z<hauteur>` = hauteur du PLANCHER sous la figurine, en POUCES (§03.04 : le gate vertical
# compare des hauteurs, pas des niveaux — la hauteur d'un `level` donné dépend de la POSITION, et
# le step.log ne porte aucun terrain, donc elle ne serait pas re-dérivable).
#
# OPTIONNEL À LA LECTURE, et ce n'est pas un repli masquant : une hauteur absente a un
# comportement DÉFINI et juste — le contrôle reste 2D, ce qui est exact sur un plateau plat, donc
# sur tous les journaux antérieurs aux étages. C'est la différence avec l'entête `Run rules:`,
# qui est EXIGÉE : pour une règle absente il n'existe aucun repli correct (prendre celle du
# config du jour rend un verdict FAUX, pas un verdict absent). Le moteur, lui, l'écrit toujours.
_MODELS_RE = re.compile(r'\[MODELS:\s*([^\]]+)\]')
_TARGET_MODELS_RE = re.compile(r'\[TARGET_MODELS:\s*([^\]]+)\]')
#: Grammaire d'un token per-figurine `mid@(col,row[,zH])`. SOURCE UNIQUE : la ligne d'état
#: (`T{tour} STATE:`) en dérive son propre motif au lieu d'en réécrire une variante — les
#: deux avaient déjà divergé (mid avec/sans `#`, `z` requis/optionnel), et une divergence
#: fait échouer le parseur d'état EN SILENCE : l'unité sort de l'instantané, donc elle est
#: comptée morte et tuée dans l'état reconstruit — le compteur 2.8 se met alors à crier.
MODEL_TOKEN_PATTERN = r'(\S+?#\S*?)@\((-?\d+),\s*(-?\d+)(?:,\s*z(-?[\d.]+))?\)'
_TOKEN_RE = re.compile(MODEL_TOKEN_PATTERN)

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


def position_is_on_battlefield(pos: Optional[Tuple[int, int]]) -> bool:
    """Cette position lue dans le journal est-elle SUR LE CHAMP DE BATAILLE ?

    Jumeau analyzer de ``engine.spatial_relations.entry_is_on_battlefield`` — même sentinelle
    ``(-1,-1)``, même règle (03.04 / 20.01) : une escouade hors table (pas encore déployée, ou en
    réserves stratégiques tant qu'elle n'a pas fait son ingress move) n'a pas de position, donc
    aucune géométrie à mesurer. Elle ne peut ni engager, ni bloquer, ni être prise pour cible.

    L'entête du journal DÉCLARE toutes les escouades à la sentinelle (« Starting position
    (-1,-1) ») et ``unit_positions`` la garde jusqu'à leur mise en place : toute énumération
    géométrique de l'analyzer doit donc écarter ces unités, faute de quoi elle mesure contre le
    coin du plateau et rend un verdict INVENTÉ — jamais une erreur. Le filtre se pose à
    l'ÉNUMÉRATION, exactement comme ``entries_on_battlefield`` côté moteur.
    """
    return pos is not None and int(pos[0]) >= 0


def parse_models_and_heights(
    text: str,
) -> Tuple[Optional[Dict[str, Dict[str, Tuple[int, int]]]], Optional[Dict[str, Dict[str, float]]]]:
    """Extrait le segment [MODELS:] → ``(positions, hauteurs)`` en UN seul parcours.

    ``positions`` = ``{unit_id: {mid: (col,row)}}``, ``hauteurs`` = ``{unit_id: {mid: pouces}}``.
    ``unit_id`` = préfixe de mid avant '#'. Les deux valent None si la ligne ne porte pas de
    segment (ligne sans suffixe per-figurine, p.ex. logs anciens/synthétiques).

    UN parcours et non deux : les deux cartes viennent du MÊME match, et leurs consommateurs les
    lisent ENSEMBLE (``_vertical_classes`` exige les centres ET les hauteurs). Les séparer coûtait
    un `search` sur la ligne entière et un `finditer` complet de plus **par ligne de journal** —
    la boucle la plus chaude de l'analyzer — et laissait la convention de token (format `z`,
    dérivation de l'``unit_id``) s'écrire à deux endroits, donc diverger.

    Les socles SANS `z` sont ABSENTS de la carte des hauteurs — pas posés à 0.0. Le consommateur
    voit alors « pas d'altitude connue » et reste en 2D, au lieu de mesurer une figurine réelle
    contre un sol supposé. La carte vaut None si aucun socle du segment ne porte de hauteur.
    """
    m = _MODELS_RE.search(text)
    if not m:
        return None, None
    positions: Dict[str, Dict[str, Tuple[int, int]]] = {}
    heights: Dict[str, Dict[str, float]] = {}
    for tok in _TOKEN_RE.finditer(m.group(1)):
        mid = tok.group(1)
        unit_id = mid.split('#', 1)[0]
        positions.setdefault(unit_id, {})[mid] = (int(tok.group(2)), int(tok.group(3)))
        if tok.group(4) is not None:
            heights.setdefault(unit_id, {})[mid] = float(tok.group(4))
    if not positions:
        raise ValueError(f"Segment [MODELS:] présent mais vide/illisible: {m.group(1)[:120]}")
    return positions, heights or None


def parse_models_segment(text: str) -> Optional[Dict[str, Dict[str, Tuple[int, int]]]]:
    """Positions seules du segment [MODELS:] — enveloppe de ``parse_models_and_heights``.

    Pour les appelants qui n'ont que faire de l'altitude (contrôles horizontaux, tests).
    """
    return parse_models_and_heights(text)[0]


def parse_models_heights(text: str) -> Optional[Dict[str, Dict[str, float]]]:
    """Hauteurs seules du segment [MODELS:] — enveloppe de ``parse_models_and_heights``."""
    return parse_models_and_heights(text)[1]


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


_SHOOTER_MODELS_RE = re.compile(r'\[SHOOTER_MODELS: ([^\]]+)\]')


def parse_shooter_models_segment(text: str) -> Tuple[str, ...]:
    """Socles qui ont RÉELLEMENT tiré ou frappé sur cette ligne (`[SHOOTER_MODELS:]`), ou ().

    Vivait en privé dans `analyzer_phases/fight_handler`, que `shoot_handler` importait par son
    nom souligné — l'aveu que la donnée n'est pas propre à la mêlée. Elle est ici, à côté des
    autres lecteurs de segment per-figurine (`parse_models_segment`, `parse_target_models_segment`).
    """
    m = _SHOOTER_MODELS_RE.search(text)
    return tuple(m.group(1).split()) if m else ()


def per_model_attack_cap(
    shooters: Tuple[str, ...],
    model_types: Dict[str, str],
    squad_unit_type: str,
    weapon_display_name: str,
    unit_attack_limits: Dict[str, Any],
    per_unit_key: str,
    global_by_weapon: Dict[str, int],
    squad_value: int,
    n_models: int,
    bonus: int = 0,
) -> int:
    """Plafond d'attaques d'UNE ligne, calculé PAR FIGURINE quand le journal le permet.

    UN SEUL calcul pour le TIR et pour la MÊLÉE. Il a d'abord été écrit du seul côté mêlée
    (`fight_handler._cc_cap_for_line`, 2026-08-09), et le côté tir est resté au niveau ESCOUADE
    pendant que la doc de couverture le nommait « le jumeau non traité » (vert vacant V14). C'est
    exactement le motif d'échec n°1 de ce dépôt : une correction faite d'un côté et pas de l'autre.

    Deux données rendent le calcul juste :
      - `[MODEL_TYPES:]` (entête d'épisode) donne la DATASHEET de chaque socle. Sans elle, le NB
        vient du type d'escouade — faux dès qu'un personnage est rattaché (règle 19) ou qu'un
        sergent porte une autre arme. Cinq armes s'appellent « Close Combat Weapon », de NB 2 à 6 ;
        au tir, un pistolet de sergent dans une escouade Vanguard produit le même écart.
      - `[SHOOTER_MODELS:]` nomme les socles qui ont RÉELLEMENT tiré / frappé sur cette ligne. Le
        pool se compte sur eux, pas sur l'effectif entier.

    `bonus` est le modificateur d'ATTAQUES en vigueur, LU par l'appelant dans `T{tour} EFFECTS:`
    (`waaagh_melee_atk`) et jamais redeviné ici : le coder ferait vivre une seconde définition de
    la règle, qui divergerait le jour où la constante du moteur bouge. Il s'ajoute PAR FIGURINE —
    « add 1 to the Attacks characteristic » modifie la caractéristique, pas le total d'escouade.

    REPLI EXPLICITE sur `(squad_value + bonus) × n_models` quand le journal ne porte pas ces
    segments : un journal antérieur au format reste analysable, avec la précision qu'il permet et
    pas davantage. Ce n'est pas un défaut masqué, c'est la même mesure qu'avant sur une donnée qui
    n'a pas changé.
    """
    if not shooters or not model_types:
        return (squad_value + bonus) * n_models

    total = 0
    for mid in shooters:
        model_type = model_types.get(mid, squad_unit_type)  # get allowed : socle hors [MODEL_TYPES:]
        limits = unit_attack_limits.get(model_type)  # get allowed : type hors registre
        value = None
        if limits is not None:
            value = resolve_weapon_value(
                weapon_display_name, require_key(limits, per_unit_key), global_by_weapon,
            )
        total += (value if value is not None else squad_value) + bonus
    return total


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
    heights: Optional[Dict[str, float]] = None,
    model_height: Optional[float] = None,
) -> List[Dict[str, object]]:
    """Entrées `units_cache` moteur — UNE PAR FIGURINE, socle réel.

    Les primitives d'engagement du moteur (`entries_in_engagement_zone`) mesurent entre DEUX
    entrées : en métrique hex par empreintes, en métrique euclidienne par
    `socle_from_cache_entry`, qui lit `BASE_SHAPE`/`BASE_SIZE` **et l'ancre** de l'entrée. Une
    entrée par ESCOUADE y perdrait donc toutes les figurines sauf l'ancre dès que la métrique
    est euclidienne — exactement le défaut qu'on corrige. Une entrée par figurine rend la mesure
    per-socle exacte quelle que soit la métrique.

    Sans donnée per-figurine : une seule entrée à l'ancre (donnée absente, pas mesure fausse).

    ENGAGEMENT 3D (§03.04 : 2" horizontal ET 5" vertical). ``heights`` (hauteur de plancher par
    socle, lue dans le segment `[MODELS:]`) et ``model_height`` (MODEL_HEIGHT de l'unité,
    registry) vont ENSEMBLE : fournis, chaque entrée porte les cartes verticales qu'exige
    ``_vertical_classes``. Comme UNE entrée = UNE figurine, ces cartes n'ont qu'un élément et le
    couplage horizontal/vertical y est EXACT — pas l'approximation « union horizontale + gate
    global » que subissent les entrées d'escouade. Une figurine sans hauteur connue ne reçoit
    aucune carte : la primitive lève alors si le gate est demandé, et l'appelant retombe en 2D
    plutôt que de la supposer au sol.

    HORS TABLE : les socles à la sentinelle `(-1,-1)` ne produisent AUCUNE entrée. Le filtre vit
    ICI, seule fabrique d'entrées de l'analyzer — jumeau exact d'``entries_on_battlefield`` côté
    moteur, qui écarte à l'énumération pour la même raison : les primitives de mesure lèvent sur
    une entrée hors table (``require_entry_on_battlefield``), et une escouade non déployée est à
    portée d'engagement de l'origine du plateau. Une escouade entièrement hors table rend donc
    une liste VIDE, que l'appelant lit comme « rien à mesurer ».
    """
    shape, size = _unit_base(unit_base, unit_id)
    if models:
        placed = list(models.items())
    else:
        placed = [(f"{unit_id}#anchor", anchor)] if anchor is not None else []
    entries: List[Dict[str, object]] = []
    for mid, pos in placed:
        if not position_is_on_battlefield(pos):
            continue
        col, row = pos
        entry: Dict[str, object] = {
            "col": col, "row": row, "player": int(player),
            "occupied_hexes": _model_footprint(col, row, (shape, size)),
            "BASE_SHAPE": shape, "BASE_SIZE": size, "orientation": 0,
        }
        if heights is not None and model_height is not None and mid in heights:
            entry["occupied_hexes_by_model"] = {mid: (col, row)}
            entry["floor_height_by_model"] = {mid: float(heights[mid])}
            entry["MODEL_HEIGHT"] = float(model_height)
        entries.append(entry)
    return entries


def squads_min_ranged_distance(
    models_a: Dict[str, Tuple[int, int]],
    base_a: Base,
    models_b: Dict[str, Tuple[int, int]],
    base_b: Base,
    metric: str,
    max_distance: float = 0,
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
