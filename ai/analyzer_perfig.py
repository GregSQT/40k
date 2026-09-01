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
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

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

_fp_cache: Dict[Tuple[int, int, str, Union[int, Tuple[int, ...]]], FrozenSet[Tuple[int, int]]] = {}


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


def _model_footprint(col: int, row: int, base: Base) -> FrozenSet[Tuple[int, int]]:
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


def squad_coherency_offenders(
    models: Dict[str, Tuple[int, int]],
    base: Base,
    coherency_subhex: int,
    global_subhex: int,
    min_neighbors: int,
) -> List[str]:
    """03.03 — figurines de l'escouade EN VIOLATION de cohérence, nommées.

    « A unit is in coherency while both of the following apply to every model in that unit:
    within 2" of at least one other model in that unit ; within 9" of every other model. »

    Le VERDICT n'est pas ré-écrit ici : il est délégué à `_coherency_verdict` du MOTEUR, qui
    porte la partie délicate — la 1re puce n'est pas « au moins un voisin » mais la CONNEXITÉ de
    toute l'escouade en une seule chaîne. Deux paquets de figurines respectant chacun les 2" à
    l'intérieur ne sont PAS en cohérence, et une lecture naïve les accepte (le moteur a vécu
    exactement ce défaut, cf. `_coherency_flags_footprint`). Seule la MESURE est faite ici, avec
    les empreintes par-figurine de l'analyzer — les mêmes qui servent au BFS de mouvement.

    Mesure d'empreinte à empreinte (`min_distance_between_sets`), c'est-à-dire de bord de socle
    à bord de socle (01.04), et donc de centre à centre à x1 où une figurine tient dans une case.
    Les trois seuils viennent de l'entête `Run rules:` du journal analysé, jamais du config du
    jour. Le volet VERTICAL (5") n'est pas mesuré : `[MODELS:]` porte l'altitude par socle, mais
    la cohérence verticale n'a jamais été le volet en défaut et l'ajouter sans témoin serait un
    contrôle non éprouvé — c'est dit dans `analyzer_couverture.md`, pas passé sous silence.
    """
    from engine.phase_handlers.shared_utils import _coherency_verdict

    ids = sorted(models)
    n = len(ids)
    if n <= 1:
        # 03.03 ne s'applique qu'aux unités de plus d'une figurine (« a unit that contains more
        # than one model »).
        return []
    footprints = [_model_footprint(*models[mid], base) for mid in ids]
    neighbor = [[False] * n for _ in range(n)]
    too_far = [False] * n
    for i in range(n):
        for j in range(i + 1, n):
            d = min_distance_between_sets(footprints[i], footprints[j], max_distance=global_subhex)
            if d <= coherency_subhex:
                neighbor[i][j] = neighbor[j][i] = True
            if d > global_subhex:
                too_far[i] = too_far[j] = True
    flags = _coherency_verdict(neighbor, too_far, min_neighbors)
    return [ids[i] for i, bad in enumerate(flags) if bad]


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


def weapon_profile_names(weapon_name: str) -> Tuple[str, ...]:
    """Les PROFILS qu'un nom d'arme logué désigne — un seul, ou les composantes d'un « A / B ».

    Le moteur fusionne sur une seule ligne les armes de même signature d'attaque et écrit leurs
    noms joints (`shared_utils`, `" / ".join(g["weapon_names"])`). La ligne porte alors DEUX
    profils, et tout ce qui se résout par arme doit le savoir.
    """
    name = weapon_name.strip()
    return tuple(p.strip() for p in name.split(" / ")) if " / " in name else (name,)


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
    profiles = weapon_profile_names(name)
    if len(profiles) > 1:
        # Découpage par `weapon_profile_names`, SEUL site qui connaisse la grammaire du nom
        # composite. Le refaire ici à la main, c'était deux définitions du séparateur à quinze
        # lignes d'écart : celle du jumeau `resolve_weapon_characteristic` suivrait le jour où le
        # moteur change le joint, celle-ci non, et les deux résolveurs du MÊME nom logué
        # divergeraient en silence.
        vals = []
        for part in profiles:
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


def resolve_weapon_characteristic(
    weapon_name: str,
    per_unit_map: Dict[str, int],
) -> Dict[str, Optional[int]]:
    """CARACTÉRISTIQUE (Force…) de CHAQUE profil de la ligne, SUR CETTE DATASHEET, sans agrégation.

    Jumeau de `resolve_weapon_value` pour l'autre nature de valeur, et il n'y en a que deux :

    - un PLAFOND (NB d'attaques, [RAPID FIRE], [SUSTAINED HITS]) borne un comptage. Sur-évaluer
      ne peut que sur-autoriser, donc l'agrégation y est SÛRE : `resolve_weapon_value` emprunte à
      la carte globale et retient le `max()` des composantes d'un profil fusionné.
    - une CARACTÉRISTIQUE entre dans un CALCUL de règle (la F dans la table 05.02). Une valeur
      agrégée n'est portée par AUCUNE figurine : elle est inventée, et le contrôle qui s'en sert
      rend un verdict faux au lieu d'un honnête « non vérifiable ». D'où cette fonction, qui
      n'agrège RIEN — ni carte globale (aucun paramètre pour en passer une : l'emprunt est
      impossible, pas seulement non branché — les cartes globales de Force ont été supprimées
      d'`AnalyzerConfig` pour la même raison), ni `max()`, ni moyenne. Elle RENVOIE LES PROFILS,
      chacun sous son nom, et laisse l'appelant décider ce qu'une ligne à deux profils permet de
      conclure : lui seul sait quelles figurines ont frappé et quel calcul en dépend.

    `None` pour un profil = absent de CETTE datasheet (porté par une autre figurine de la ligne,
    ou caractéristique symbolique du registre). Ce n'est pas une valeur manquante en soi : sur un
    composite inter-datasheets, chaque figurine ne connaît que le sien.

    Le composite aux profils DIVERGENTS est ATTEIGNABLE, mesuré sur `config/unit_registry.json` :
    le `DreadnoughtRedemptor` (deux rosters de training) porte Heavy Onslaught Gatling Cannon F6
    et Onslaught Gatling Cannon F5, de mêmes ATK/AP/DMG/règles — la clé de fusion moteur (`gkey`)
    les réunit dès que les deux blessent la cible sur le même seuil (E ∈ {1,2,4,7,8,9,12,13,14}).
    """
    # `weapon_profile_names` est la SEULE définition du découpage, y compris quand le nom entier
    # figure dans la carte : essayer d'abord le nom entier ferait rendre à cette fonction des
    # clés que l'appelant n'attend pas (il énumère les profils avec le même helper), donc un
    # `KeyError` au premier `display_name` contenant lui-même « / ». Un tel nom se découperait
    # ici en composantes inconnues → `None` partout → ligne non vérifiable : le contrat tient,
    # et il se voit, au lieu d'abattre l'analyse entière.
    # get allowed : profil porté par une AUTRE figurine de la ligne, ou valeur symbolique
    return {part: per_unit_map.get(part) for part in weapon_profile_names(weapon_name)}


_SHOOTER_MODELS_RE = re.compile(r'\[SHOOTER_MODELS: ([^\]]+)\]')


def parse_shooter_models_segment(text: str) -> Tuple[str, ...]:
    """Socles qui ont RÉELLEMENT tiré ou frappé sur cette ligne (`[SHOOTER_MODELS:]`), ou ().

    Vivait en privé dans `analyzer_phases/fight_handler`, que `shoot_handler` importait par son
    nom souligné — l'aveu que la donnée n'est pas propre à la mêlée. Elle est ici, à côté des
    autres lecteurs de segment per-figurine (`parse_models_segment`, `parse_target_models_segment`).
    """
    m = _SHOOTER_MODELS_RE.search(text)
    return tuple(m.group(1).split()) if m else ()


def weapon_profile_for_line(
    shooters: Tuple[str, ...],
    model_types: Dict[str, str],
    squad_unit_type: str,
    weapon_display_name: str,
    unit_weapons_cache: Dict[str, List[Dict[str, Any]]],
    is_melee: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Tuple[str, ...]]:
    """Profil d'arme d'UNE ligne et DATASHEET qui le porte — `(info, porteur, ambigus)`.

    `is_melee` = phase de la LIGNE, et c'est un paramètre OBLIGATOIRE : trois noms d'affichage
    désignent deux profils différents selon la phase (`Castellan Axe`, `Guardian Spear`,
    `Sentinel Blade`, chez les Custodes). Résoudre par le seul nom rendrait pour ces trois-là le
    profil de l'autre phase — donc ses règles dans le tableau d'usage, et une portée absente
    pour un contrôle de portée de tir. Aucun défaut : c'est l'appelant qui sait d'où vient sa
    ligne, le deviner ici serait une seconde définition de la phase.

    Le profil était cherché dans le seul équipement du TYPE D'ESCOUADE. Une arme portée par un
    personnage rattaché (règle 19) ou par un sergent n'y est pas : elle ressortait introuvable,
    donc sans portée (aucun contrôle de portée possible), sans `is_close_quarters` fiable, et
    surtout absente du tableau d'usage des règles d'armes. Même écart que celui déjà fermé pour
    les PLAFONDS d'attaques par `per_model_attack_cap` ci-dessous, qui lit `[MODEL_TYPES:]` —
    le comptage d'usage, lui, n'avait pas suivi. Mesuré sur le run du 2026-08-11 : sur 23 169
    tirs, 3 138 (14 %) portaient une arme absente du type d'escouade, dont les 21 blessures
    dévastatrices d'un Librarian rattaché qui manquaient à la ventilation par arme.

    RÉSOLUTION TOTALE ET DÉTERMINISTE, dans cet ordre :
      1. le type d'ESCOUADE déclare l'arme → c'est lui le porteur. Représentant canonique du
         groupe, et non un choix par défaut : c'est l'étiquette sous laquelle le tableau a
         toujours compté cette arme, et 20 031 des 23 169 tirs du run passent par là. Elle
         s'applique même quand les figurines qui tirent sont un sergent et un personnage (les
         autres sont mortes) : l'arme reste celle de l'escouade.
      2. sinon, les datasheets des figurines qui ont TIRÉ (`[SHOOTER_MODELS:]`) sont
         consultées. Un seul porteur → c'est lui.
      3. plusieurs porteurs distincts hors escouade → INDÉTERMINÉ. Le journal ne dit pas quelle
         figurine a porté quelle attaque, et deviner attribuerait un usage à une datasheet au
         hasard. Rendu en troisième membre pour que l'appelant l'écrive en `parse_errors` : le
         cas ne survient pas sur le run mesuré, et s'il survient il doit se voir.
      4. arme introuvable partout → `(None, None, ())`, comme avant.
    """
    weapon_name_lower = weapon_display_name.lower()

    def _declared_by(unit_type: Optional[str]) -> Optional[Dict[str, Any]]:
        if not unit_type:
            return None
        for weapon_info in unit_weapons_cache.get(unit_type, []):  # get allowed : type hors registre
            if require_key(weapon_info, "is_melee") != is_melee:
                continue
            if require_key(weapon_info, "name").lower() == weapon_name_lower:
                return weapon_info
        return None

    squad_weapon = _declared_by(squad_unit_type)
    if squad_weapon is not None:
        return squad_weapon, squad_unit_type, ()

    carriers: Dict[str, Dict[str, Any]] = {}
    for model_id in shooters:
        model_type = model_types.get(model_id)  # get allowed : socle hors [MODEL_TYPES:]
        if not model_type or model_type in carriers:
            continue
        carrier_weapon = _declared_by(model_type)
        if carrier_weapon is not None:
            carriers[model_type] = carrier_weapon
    if len(carriers) == 1:
        carrier_type, carrier_weapon = next(iter(carriers.items()))
        return carrier_weapon, carrier_type, ()
    if len(carriers) > 1:
        return None, None, tuple(sorted(carriers))
    return None, None, ()


#: Tranche de figurines de la cible qui ouvre un dé additionnel, pour [BLAST] 24.05 comme pour
#: [CLEAVE] 24.06 : « for every five models that were in the target unit ». Nommée parce que les
#: deux règles la partagent et qu'un `// 5` écrit deux fois est un `// 5` qui divergera.
ADDITIVE_RULE_MODELS_PER_DIE: int = 5


def additive_rule_extra_dice(
    rule_label: str,
    action_desc: str,
    shooters: Tuple[str, ...],
    model_types: Dict[str, str],
    squad_unit_type: str,
    weapon_display_name: str,
    unit_attack_limits: Dict[str, Any],
    per_unit_key: str,
    global_by_weapon: Dict[str, int],
    n_models: int,
    target_models: int,
) -> Tuple[int, Optional[str]]:
    """Dés additionnels de [BLAST] 24.05 (tir) / [CLEAVE] 24.06 (mêlée) sur CETTE ligne.

    UN SEUL calcul pour les deux règles : elles ont le même texte (« add X additional attack
    dice for every five models that were in the target unit in the Select Targets step »),
    [CLEAVE] ajoutant seulement la clause « une seule cible pour toutes les attaques de cette
    arme ». Cette clause n'est PAS rejouée ici — le moteur l'a tranchée, et il le dit en posant
    (ou non) le token sur la ligne, exactement comme `[RAPID FIRE:X]` dit que la cible était à
    demi-portée. Le lecteur n'a pas à redevenir juge d'une déclaration qu'il ne voit pas.

    Ce que le token NE dit PAS, et que ce site calcule donc lui-même : le NOMBRE de dés. Le lire
    dans le journal rendrait le contrôle vacant — l'analyzer vérifierait le moteur avec le
    chiffre du moteur. X vient du registre d'armes, l'effectif de la cible de l'état reconstruit.

    `target_models` est l'effectif au Select Targets step (figé à l'ouverture de la séquence par
    l'appelant), et non celui de la ligne courante : la séquence tue en avançant.

    Retourne `(dés additionnels, message d'erreur ou None)`. L'erreur — token posé sur une arme
    qui ne déclare pas la règle, ou X du journal différent de celui du registre — est RENDUE et
    non écrite : `parse_errors` appartient à l'appelant, qui seul a l'épisode et le tour.
    JUMEAU des deux mêmes contrôles sur `[RAPID FIRE:X]` dans `shoot_handler`.
    """
    logged = re.search(rf'\[{rule_label}:(\d+)\]', action_desc, re.IGNORECASE)
    if logged is None:
        return 0, None
    logged_value = int(logged.group(1))
    limits = unit_attack_limits.get(squad_unit_type)  # get allowed : type hors registre
    declared = None
    if limits is not None:
        declared = resolve_weapon_value(
            weapon_display_name, require_key(limits, per_unit_key), global_by_weapon,
        )
    if declared is None or declared <= 0:
        return 0, (
            f"{rule_label} marker present for weapon without {rule_label} rule: "
            f"{squad_unit_type}/{weapon_display_name}"
        )
    if logged_value != declared:
        return 0, (
            f"{rule_label} marker value mismatch for {squad_unit_type}/{weapon_display_name}: "
            f"log={logged_value}, expected={declared}"
        )
    # X est un attribut de l'ARME : il se résout PAR FIGURINE comme le NB (une escouade porte des
    # datasheets différentes, règle 19). Somme des X des porteurs × tranches de 5 de la cible —
    # `(ΣX) × k` est bien `Σ(X × k)`, la factorisation ne change pas le compte.
    x_by_models = per_model_attack_cap(
        shooters, model_types, squad_unit_type, weapon_display_name,
        unit_attack_limits, per_unit_key, global_by_weapon, declared, n_models,
    )
    return x_by_models * (int(target_models) // ADDITIVE_RULE_MODELS_PER_DIE), None


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


def unit_ability_attack_cap(
    shooters: Tuple[str, ...],
    model_types: Dict[str, str],
    unit_id: str,
    squad_unit_type: str,
    weapon_display_name: str,
    unit_attack_limits: Dict[str, Any],
    per_unit_key: str,
    n_models: int,
) -> int:
    """Plafond apporté par une capacité d'UNITÉ, propagée selon 19.04.

    JUMEAU INVERSE de `per_model_attack_cap`, et la distinction est la règle elle-même. Ce que
    `per_model_attack_cap` résout — NB, [RAPID FIRE], [BLAST], [CLEAVE], [SUSTAINED HITS] — est
    INTRINSÈQUE À L'ARME : chaque socle apporte ce que sa propre datasheet lui donne, et un
    personnage rattaché tire avec SON arme, pas avec celle de l'escouade.

    Une capacité d'UNITÉ obéit à la règle inverse. 19.04 : « abilities/rules that affect a unit
    (or models in it) apply to EVERY model in an attached unit » — seules les capacités visant un
    socle nommé (enhancement, wargear) restent locales. Hail of Bolts
    (`weapon_attacks_bonus_vs_designated_target`) est une capacité d'escouade : elle vaut donc
    aussi pour l'Ancient et le Captain rattachés, dont la datasheet ne la porte pas.

    Le moteur applique déjà cette lecture — `shared_utils.py` lit les arguments sur
    `attacker_unit`, jamais sur le socle. Résoudre le bonus par datasheet individuelle refusait
    aux personnages rattachés un bonus que le moteur leur accorde : 2447 faux
    `shoot_over_rng_nb` sur le run de 300 épisodes du 2026-09-02.

    La source peut être N'IMPORTE QUELLE unité composante (l'escouade ou un de ses meneurs) :
    on balaie donc tous les types présents dans l'unité, pas seulement celui de l'escouade.
    """
    _types = {squad_unit_type}
    _prefix = f"{unit_id}#"
    for _mid, _mt in model_types.items():
        if _mid.startswith(_prefix):
            _types.add(_mt)
    per_model_bonus = 0
    for _t in _types:
        limits = unit_attack_limits.get(_t)  # get allowed : type hors registre
        if limits is None:
            continue
        value = resolve_weapon_value(
            weapon_display_name, require_key(limits, per_unit_key), {},
        )
        if value is not None and value > per_model_bonus:
            per_model_bonus = value
    if not per_model_bonus:
        return 0
    # Le bonus modifie la caractéristique d'Attaques : il vaut PAR SOCLE qui tire, comme le NB.
    return per_model_bonus * (len(shooters) if shooters else n_models)


def models_for_unit(
    positions_by_model: Dict[str, Dict[str, Tuple[int, int]]],
    unit_id: str,
) -> Optional[Dict[str, Tuple[int, int]]]:
    """Socles vivants connus pour unit_id, ou None si jamais vu en per-figurine."""
    m = positions_by_model.get(unit_id)
    if not m:
        return None
    return m


def unit_effect_in_force(
    state: Any,
    config: Any,
    unit_id: str,
    effect_rule_id: str,
) -> Optional[bool]:
    """19.04 — l'effet est-il EN VIGUEUR sur cette escouade ? ``None`` = indécidable.

    « An Attached unit has the abilities of its Leader » : la règle est portée par une FIGURINE
    (le Warboss, le Chaplain) et vaut pour toute l'escouade TANT QUE cette figurine vit. Le
    verdict se prend donc sur les SOCLES VIVANTS — `positions_by_model` — et jamais sur le type
    de l'escouade : `unit_rules_by_type["Boyz"]` ne connaît pas Might Is Right, alors que des
    Boyz menés par un Warboss touchent bel et bien à +1.

    ``None`` (indécidable) quand les socles vivants sont inconnus, ou qu'une figurine porte un
    type absent du registre : le contrôle appelant compte alors la ligne en « non vérifiable »
    plutôt que de trancher. Retomber sur le roster complet (`model_types`) serait FAUX ici,
    contrairement à l'Endurance de 19.02 : une capacité de leader DISPARAÎT à sa mort, donc un
    roster qui contient les morts répondrait « oui » à une escouade décapitée.
    """
    mids = positions_by_model_for(state, unit_id)
    if not mids:
        return None
    pending_dead = state.pending_model_removals.get(unit_id, frozenset())
    effective_mids = {m for m in mids if m not in pending_dead}
    if not effective_mids:
        return None
    for mid in effective_mids:
        model_type = state.model_types.get(mid)  # get allowed : figurine de type inconnu
        if model_type is None:
            return None
        if effect_rule_id in config.unit_rules_by_type.get(model_type, set()):  # get allowed
            return True
    return False


def positions_by_model_for(state: Any, unit_id: str) -> Dict[str, Tuple[int, int]]:
    """Socles vivants connus d'une escouade, `{}` si l'analyzer ne les a jamais vus."""
    return state.positions_by_model.get(unit_id) or {}  # get allowed : jamais vue en per-figurine


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
