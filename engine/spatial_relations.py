"""Shared spatial relation helpers for footprint contact and engagement checks."""

from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from engine.hex_utils import (
    _hex_center,
    base_size_cache_key,
    compute_occupied_hexes,
    engagement_minimum_clearance_norm,
    euclidean_edge_clearance_round_round,
    euclidean_edge_distance,
    min_distance_between_sets,
    require_base_size,
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


def get_engagement_zone_vertical(game_state: Optional[Dict[str, Any]] = None) -> float:
    """Seuil vertical d'engagement 3D en POUCES (règle 03.04 = 5" vertical) — sélecteur UNIQUE.

    Contrairement à ``engagement_zone`` (horizontal, scalé ×inches_to_subhex au chargement),
    ce seuil reste en pouces : il se compare aux ``height_inches`` des étages (mêmes unités),
    donc NON scalé (absent de la liste de conversion de w40k_core). Aucun défaut caché.

    ``game_state`` OPTIONNEL, exactement comme ``engagement_distance_metric`` : sans état, la
    valeur est relue du config-loader global. C'est ce qui permet à la primitive
    ``entries_in_engagement_zone`` de résoudre elle-même le seuil au lieu de le faire plomber par
    ses ~60 call-sites — un seul oubli y laissait un contrôle en 2D, en silence, sur un jeu qui
    résout en 3D.

    ``game_state`` FOURNI → l'état fait foi, et son ``config`` est EXIGÉ : un état sans
    ``config`` est malformé, pas un cas à replier sur le disque. C'est la même exigence que
    ``get_engagement_zone`` pour le volet horizontal, et elle compte doublement ici :
    ``w40k_core._run_rules_for_step_log`` journalise la valeur de l'ÉTAT dans l'entête
    ``Run rules:``, sur laquelle l'analyzer épingle son seuil. Laisser l'état muet retomber sur le
    disque ferait mesurer au moteur une règle que l'audit ne verrait pas.
    """
    if game_state is not None:
        game_rules = require_key(require_key(game_state, "config"), "game_rules")
        return float(require_key(game_rules, "engagement_zone_vertical"))
    from config_loader import get_config_loader

    game_rules = require_key(get_config_loader().get_game_config(), "game_rules")
    return float(require_key(game_rules, "engagement_zone_vertical"))


#: Clés que doit porter une entrée-cache pour être mesurable en 3D (§03.04). Propriétaire UNIQUE
#: de cette liste : ``_vertical_classes`` la consomme, et tout consommateur qui la recopiait
#: (l'analyzer n'en testait qu'une sur trois) restait d'accord avec elle par chance.
_VERTICAL_ENTRY_KEYS = ("occupied_hexes_by_model", "floor_height_by_model", "MODEL_HEIGHT")

# ============================================================================
# MÉMOÏSATION DE L'ENGAGEMENT PAR PAIRE (§03.04)
# ============================================================================
# L'engagement est une FONCTION PURE de la géométrie des deux entrées : mêmes positions, même
# verdict. Or dans un seul step d'agent, la même paire est mesurée par le masque d'actions, par
# les pools de destination ET par l'observation, sur un plateau qui n'a pas bougé entre les trois.
# Profil du 2026-08-10 (évaluation x1, 12 épisodes) : `_entries_in_engagement_zone_3d` totalise
# 96 626 appels pour 13,6 s, et `min_distance_between_sets` 331 816 appels — pour une poignée
# d'unités réelles.
#
# CLÉ CONTENANT LA GÉOMÉTRIE, jamais un compteur de version. C'est le point de conception, et il
# vient d'un défaut vécu : la 1re version du cache de `build_squad_move_cell_map` était clée sur
# `_unit_move_version`, qu'un chemin d'écriture de position ne bumpe pas — elle servait une carte
# périmée et produisait une divergence masque/exécution (§0.18). Ici, si une figurine bouge, la
# clé change PAR CONSTRUCTION : il n'existe aucun chemin d'écriture capable de rendre une entrée
# périmée sans changer sa clé. Le prix est de reconstruire la clé à chaque appel — c'est ce que la
# mesure valide, pas une intuition.
#
# Conséquence : une entrée « périmée » n'existe pas, seulement des entrées DEVENUES INUTILES. Le
# cache est donc borné par purge, pas par invalidation.
#
# QUI EST MÉMOÏSÉ, ET QUI NE L'EST PAS — c'est le critère de conception, pas un réglage.
# Est mémoïsée une paire décrivant deux positions OCCUPÉES ; ne l'est pas une paire dont une
# entrée décrit une CELLULE TESTÉE. Les boucles de candidats — pool de move, BFS de charge,
# recherche de placement — construisent une entrée par cellule explorée : clé neuve à chaque fois,
# jamais redemandée, et surtout elle CHASSE du cache les paires unité↔unité que le masque, les
# pools et l'observation du même step vont redemander. Ces sites passent `memoise=False` :
# 1 dans `move_anchor_violates_engagement_clearance`, 2 dans `shared_utils` (charge), 13 dans
# `charge_handlers` — chacun commenté sur place. Mesuré à x5 : les laisser entrer fait tomber le
# taux de touche de 83 % à 29 %, déclenche 110 purges et retourne le gain à **−0,83 s**.
#
# ⚠️ CE CRITÈRE NE SE VÉRIFIE PAS EN LISANT LE SITE D'APPEL. Il a fallu QUATRE passes pour le
# poser correctement, et chaque rechute venait de la même illusion : croire au nom de la variable.
# Le cas d'école est `_eng` (`charge_handlers`), qui reçoit un `synth_base` construit ~60 lignes
# plus haut, hors de la boucle — donc « invariant » à la lecture. Il est en fait RÉÉCRIT à chaque
# cellule candidate, ~30 lignes PLUS BAS que l'appel. Il a été classé « producteur de touches »
# dans ce même commentaire avant qu'une review ne le rattrape.
# La seule vérification qui tienne : ÉCHANTILLONNER les ratés en production (une pile d'appel sur
# 50) et regarder qui apparaît. Un site qui rate systématiquement est un site à exclure.
#
# À l'inverse, RESTENT mémoïsées les entrées posées sur une position RÉELLE, vérifiées une par une :
# synth par-figurine de `shared_utils`, `placed_synths` d'un plan committé, positions d'un plan
# validé, entrées `units_cache` directes. Ce sont elles qui produisent les touches.
#
# GAIN MESURÉ le 2026-08-11, par comptabilité INTERNE À UN SEUL RUN — coût des clés d'un côté,
# coût réel des mesures évitées de l'autre, le prix d'une touche étant échantillonné en la
# recalculant une fois sur vingt plutôt que déduit du prix d'un raté :
#   x1 (`--resolution 1`, 24 ép.) : touches 86,2 %, 5 purges, 28,0 Mo → évité 4,62 s pour 1,20 s
#                                   de clés, soit **net +3,42 s, ratio 3,9×** ;
#   x5 (`--resolution 5`,  6 ép.) : touches 84,2 %, 9 purges, 23,1 Mo → évité 1,13 s pour 0,36 s,
#                                   soit **net +0,76 s, ratio 3,1×**.
#
# ⚠️ LIRE LE RATIO, PAS LES SECONDES. Les secondes dépendent du modèle chargé et de la charge
# machine : une campagne du 2026-08-10, sur le modèle précédent, donnait +12,64 s à x1 pour un
# ratio de 3,8× — même ratio, secondes ×3,7. Le ratio évité/coût, lui, est stable d'une campagne
# à l'autre et d'une résolution à l'autre : c'est la seule grandeur transposable.
#
# Une touche coûte PLUS cher qu'un raté (42,97 µs contre 29,53 µs, mesuré à x1) : les paires
# redemandées sont les paires proches, celles dont les boucles 3D vont le plus loin. Estimer le
# gain sur le prix moyen d'un raté le sous-estimait de 40 %.
#
# ⚠️ MÉTHODE — comparer deux runs au chronomètre NE MARCHE PAS ici, et c'est ce qui a d'abord fait
# conclure (à tort) que ce cache était une perte. Les parties jouées diffèrent d'un run à l'autre,
# donc le travail aussi : mesuré à x5, 184 s puis 279 s de temps CPU pour la MÊME configuration —
# une variance de 50 %, largement au-dessus de l'effet cherché. Toute reprise de ce sujet doit
# mesurer les deux moitiés du compromis DANS le même run.
_EZ_PAIR_CACHE: Dict[Any, bool] = {}

# BORNE EN POIDS, PAS EN NOMBRE D'ENTRÉES — et la différence n'est pas théorique.
# Une clé porte deux empreintes complètes, donc son poids varie d'un facteur 60 selon la
# résolution et la taille d'escouade. Un plafond de 50 000 ENTRÉES — la première version —
# laissait passer **4,4 GB** à x5, et l'entraînement tourne à `n_envs: 48` processus.
#
# MÉTHODE DE MESURE — elle a compté deux fois ici, et deux estimations successives se sont
# trompées avant celle-ci. `sys.getsizeof` récursif sur UNE clé isolée ne répond pas à la
# question : il double-compte les objets partagés entre clés, ou ignore le surcoût du dict, selon
# la façon dont on somme. La seule mesure honnête est la CROISSANCE RSS du processus en
# remplissant le vrai dict avec 20 000 clés distinctes :
#   x1,  1 figurine  (1 hex)      →  1,45 kB/clé → 246,8 octets par élément
#   x1,  5 figurines (1 hex/fig)  →  3,39 kB/clé → 115,7
#   x5,  5 figurines (19 hex/fig) → 23,97 kB/clé → 116,9
#   x5, 10 figurines (43 hex/fig) → 89,43 kB/clé → 101,7
#
# Le poids est compté en ÉLÉMENTS d'empreinte (hexes + figurines), pas en octets réels : c'est un
# `len()` sur des objets déjà construits, donc gratuit. Le rapport octets/élément n'est PAS
# constant — les petites clés paient proportionnellement bien plus de surcoût de conteneur, et ce
# sont justement les plus nombreuses (une figurine synthétique par modèle). On retient donc la
# borne HAUTE mesurée, jamais la moyenne : une borne qui sous-estime ne borne rien.
_EZ_BYTES_PER_ITEM = 250
#: Garde-fou en NOMBRE, second verrou de la borne en poids. `_EZ_WEIGHT` est un compteur global
#: incrémenté hors verrou ; `services/api_server.py` tourne en Flask `threaded=True`, donc deux
#: aperçus PvP concurrents peuvent perdre un incrément et retarder la purge. L'entraînement, lui,
#: est multi-PROCESSUS (mémoire séparée) : la course n'existe que côté serveur. Ce plafond est
#: dimensionné sur la PLUS PETITE clé mesurée (1,45 kB) — c'est le cas où les incréments sont les
#: plus nombreux, donc où une dérive s'accumulerait ; pour les grosses clés la borne en poids
#: déclenche bien avant.
_EZ_MAX_ENTRIES = 30_000
#: ~32 Mo par processus. Dimensionné sur le VRAI jeu de travail, pas sur le pire cas : à x5 il
#: contient une centaine de paires escouade↔escouade (les clés lourdes) et quelques centaines de
#: paires figurine↔escouade (clés légères, une figurine chacune). Ce qui déclenche les purges est
#: le flot de clés À USAGE UNIQUE de `move_anchor_violates_engagement_clearance` en métrique
#: euclidienne — une clé par (cellule candidate × ennemi) — et celles-là ne touchent jamais : les
#: purger est exactement ce qu'on veut.
_EZ_PAIR_CACHE_MAX_BYTES = 32 * 1024 * 1024
_EZ_WEIGHT = {"items": 0}
def _fingerprint_weight(fp: Tuple[Any, ...]) -> int:
    """Nombre d'éléments portés par une empreinte — proxy de son poids mémoire (cf. ci-dessus)."""
    total = 0
    for part in fp:
        if isinstance(part, (frozenset, tuple)):
            total += len(part)
    return total

#: Marqueur de clé ABSENTE dans une empreinte d'entrée. `None` ne conviendrait pas : une clé
#: PRÉSENTE ET VIDE est un état DIFFÉRENT d'une clé absente (cf. `entry_has_vertical_data` et
#: `_require_measurable_entry` — l'une est le cas synthétique légitime, l'autre une corruption).
#: Les confondre dans l'empreinte ferait partager une entrée de cache à deux états distincts.
_EZ_FP_ABSENT = "\x00absent"

def _hashable(value: Any) -> Any:
    """Rend une valeur utilisable dans une clé de cache, sans la dénaturer.

    Seules les listes sont converties (en tuple) : une clé de cache doit être hashable, et une
    liste ne l'est pas. Aucune autre transformation — tronquer ou normaliser ici ferait partager
    une entrée de cache à deux géométries différentes, ce qui est le seul défaut que ce cache
    puisse produire, et il serait silencieux.
    """
    return tuple(value) if isinstance(value, list) else value


def _engagement_entry_fingerprint(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    """Empreinte hashable de TOUT ce que la mesure d'engagement lit dans une entrée-cache.

    Exhaustivité VÉRIFIÉE champ par champ contre les trois chemins de `entries_in_engagement_zone`
    (verrouillée par `tests/unit/engine/test_engagement_pair_cache.py`) :

    - `col` / `row` — sentinelle hors table (`entry_is_on_battlefield`) et repli d'ancre de
      `entry_footprint` ;
    - `occupied_hexes` — chemin 2D hex, et `Socle` du chemin euclidien ;
    - `occupied_hexes_by_model` — chemin 3D (`_vertical_classes`), centres par-figurine du `Socle`,
      et contrôle de corruption `_require_measurable_entry` ;
    - `floor_height_by_model` — gate vertical 3D, et même contrôle de corruption ;
    - `MODEL_HEIGHT` — borne haute de l'intervalle vertical ;
    - `BASE_SHAPE` / `BASE_SIZE` / `orientation` — empreinte par classe (`_class_footprint`) et `Socle`.

    Un champ oublié ici = deux états de jeu différents qui partagent une entrée de cache, donc un
    verdict d'engagement faux SANS erreur visible. C'est le seul mode d'échec de ce cache, et c'est
    pour ça que le test énumère les champs plutôt que d'échantillonner un scénario.

    MÉMOÏSÉ dans l'entrée elle-même (item 1.8 perf_entrainement) — clé `_ez_fp`, invalidée par
    `_apply_los_invalidation` via `_touch_unit_los`. Sur un hit, l'empreinte est retournée
    directement sans relire aucun champ de l'entrée. Correct : les champs de géométrie (col, row,
    occupied_hexes, …) ne changent jamais sans passer par `_touch_unit_los`, source unique.
    ⚠️ Pendant une fenêtre de batch LoS (`_los_begin_batch` / `_los_end_batch`), les positions
    sont écrites mais `_touch_unit_los` est différé : `_ez_fp` peut être stale le temps du batch.
    En pratique, `entries_in_engagement_zone` n'est jamais appelée pendant un batch de `commit_move`.
    """
    _cached_fp = entry.get("_ez_fp")  # get allowed — None si jamais calculée ou invalidée
    if _cached_fp is not None:
        return _cached_fp
    occ = entry.get("occupied_hexes")  # get allowed (absente sur les entrées synthétiques)
    by_model = entry.get("occupied_hexes_by_model")  # get allowed (idem)
    floors = entry.get("floor_height_by_model")  # get allowed (idem)
    _fp = (
        entry.get("col"),  # get allowed (l'absence est une entrée malformée, signalée en aval)
        entry.get("row"),  # get allowed (idem)
        frozenset(occ) if occ is not None else _EZ_FP_ABSENT,
        tuple(sorted((str(m), int(c), int(r)) for m, (c, r) in by_model.items()))
        if by_model is not None else _EZ_FP_ABSENT,
        tuple(sorted((str(m), float(h)) for m, h in floors.items()))
        if floors is not None else _EZ_FP_ABSENT,
        entry.get("MODEL_HEIGHT", _EZ_FP_ABSENT),  # get allowed (absente = pas de couche verticale)
        entry.get("BASE_SHAPE", _EZ_FP_ABSENT),  # get allowed (validée en aval par require_key)
        # `BASE_SIZE` est un SCALAIRE pour un socle rond mais une LISTE pour un socle rectangulaire
        # (largeur, longueur) — donc non hashable telle quelle. Le même piège est déjà documenté
        # dans `perf_timing.perf_field`. Il ne se voit pas à x1, où tous les socles du roster sont
        # ronds : c'est un run à x5 qui l'a levé, par un `TypeError: unhashable type: 'list'`.
        _hashable(entry.get("BASE_SIZE", _EZ_FP_ABSENT)),  # get allowed (validée en aval)
        int(entry.get("orientation", 0)),  # get allowed — jumeau exact du défaut de `socle_from_cache_entry`
    )
    entry["_ez_fp"] = _fp
    return _fp


def entry_has_vertical_data(entry: Dict[str, Any]) -> bool:
    """L'entrée-cache porte-t-elle de quoi mesurer l'engagement VERTICAL (§03.04) ?

    Les trois clés sont écrites ENSEMBLE par les deux écrivains du cache
    (``build_units_cache``, ``_recompute_squad_occupied_hexes``) : une vraie unité les a toujours.
    Les entrées SYNTHÉTIQUES (candidats de pool construits sans niveau) ne les ont pas — elles
    restent alors mesurées à plat, ce qui est le verdict correct en l'absence de donnée, jamais
    une altitude supposée.

    ABSENTE vs PRÉSENTE-ET-VIDE, ce n'est pas la même chose et ça ne se traite pas pareil :
    - clé ABSENTE → l'entrée n'a pas de couche par-figurine (cas des synthétiques construites
      sans niveau : ``_synth_model_entry`` / ``_charge_synthetic_charger_cache_entry`` laissent
      alors la clé de côté). Mesure à plat, verdict correct en l'absence de donnée ;
    - carte PRÉSENTE ET VIDE → une escouade sans aucune figurine, encore dans ``units_cache``.
      C'est une contradiction avec l'invariant du cache — « Dead = absent from cache (single
      source of truth) », cf. ``remove_from_units_cache`` — donc un état corrompu.
      ``_require_measurable_entry`` lève dessus : une escouade morte ne se mesure pas, ni en 3D
      (aucune classe verticale → « non engagé » muet) ni en 2D (repli sur l'ancre → une unité
      détruite redeviendrait engageable).

    ``MODEL_HEIGHT`` est testé sur la PRÉSENCE — une hauteur de 0.0 est une valeur légitime, pas
    une absence.
    """
    entry_height = entry.get("MODEL_HEIGHT")  # get allowed (le test EST l'absence)
    return (
        bool(entry.get("occupied_hexes_by_model"))  # get allowed (idem)
        and bool(entry.get("floor_height_by_model"))  # get allowed (idem)
        and entry_height is not None
    )


def _require_measurable_entry(entry: Dict[str, Any]) -> None:
    """Lève si l'entrée-cache décrit une escouade SANS figurine (état corrompu).

    ``units_cache`` porte un invariant : une escouade détruite en est RETIRÉE
    (``remove_from_units_cache`` : « Dead = absent from cache »). Une entrée qui y reste avec une
    carte par-figurine vide viole cet invariant, et il n'existe aucune mesure juste à lui
    appliquer — la mesurer à son ancre ferait engager une unité détruite, la mesurer en 3D
    rendrait « non engagé » sans rien regarder. Les deux sont des verdicts inventés.

    La clé ABSENTE, elle, est légitime (entrée synthétique sans couche par-figurine) : seule la
    présence d'une carte VIDE est le signal de corruption.
    """
    for key in ("occupied_hexes_by_model", "floor_height_by_model"):
        value = entry.get(key)  # get allowed (l'absence est le cas LÉGITIME, cf. docstring)
        if value is not None and not value:
            raise ValueError(
                f"units_cache: entrée {entry.get('id', '?')!r} avec `{key}` VIDE — escouade sans "  # get allowed
                "figurine encore présente dans le cache. L'invariant est « détruite = absente du "
                "cache » (remove_from_units_cache) : une escouade morte ne se mesure pas."
            )


def entry_is_on_battlefield(entry: Dict[str, Any]) -> bool:
    """L'escouade décrite par cette entrée de ``units_cache`` est-elle SUR LE CHAMP DE BATAILLE ?

    Une unité VIVANTE peut être hors table : en attente de déploiement actif, ou en réserves
    stratégiques (20.01) tant qu'elle n'a pas fait son ingress move (20.04). Elle reste dans
    ``units_cache`` — elle compte pour la victoire aux points et elle peut encore arriver — mais
    elle n'a ni position ni empreinte : elle ne peut être ni ciblée, ni chargée, ni engagée, et
    elle ne contrôle aucun objectif.

    Prédicat = la sentinelle de position ``(-1,-1)``, jumelle exacte de ``deployed_on_turn is
    None`` côté unité : les deux sont écrites par le MÊME commit de mise en place
    (``_apply_deploy_plan``) et par le MÊME chargeur. Ici on lit le cache, la source des
    énumérations de ciblage.

    Vit dans la couche BASSE (``spatial_relations``) et non dans ``shared_utils`` parce que les
    primitives de mesure elles-mêmes en dépendent (``entry_footprint``,
    ``entries_in_engagement_zone``). ``shared_utils`` le ré-exporte : c'est le même symbole.
    """
    return int(require_key(entry, "col")) >= 0


def require_entry_on_battlefield(entry: Dict[str, Any], what: str) -> None:
    """Lève si l'entrée-cache est HORS TABLE — mesurer une unité sans position est une erreur.

    Contrat volontairement BRUYANT. Une entrée hors table porte la sentinelle ``(-1,-1)`` avec
    ``occupied_hexes`` VIDE et ``occupied_hexes_by_model`` peuplé de ``(-1,-1)`` par figurine :
    toute mesure qui l'accepte rend un verdict INVENTÉ, sans jamais crasher. MESURÉ le
    2026-08-05 : à x1/hex (EZ = 2), une unité hors table ressort « engagée » avec toute unité
    réelle en ``(0,0)`` et avec toutes les autres unités hors table.

    Le bon geste est donc de la SAUTER à l'ÉNUMÉRATION (``enemy_entries_on_battlefield``), pas de
    laisser la feuille inventer une distance ou un booléen. La feuille lève pour que l'oubli d'un
    filtre soit un crash localisable au lieu d'un verdict faux silencieux.
    """
    if not entry_is_on_battlefield(entry):
        raise ValueError(
            f"{what}: escouade {entry.get('id', '?')!r} HORS TABLE (sentinelle "  # get allowed
            "`(-1,-1)`, cf. `entry_is_on_battlefield`) — pas de position, donc aucune géométrie "
            "à mesurer. Elle doit être écartée à l'énumération "
            "(`enemy_entries_on_battlefield` / `entries_on_battlefield`), pas mesurée ici."
        )


def entry_footprint(cache_entry: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Empreinte hex d'une entrée ``units_cache``, à l'ancre seulement si aucune n'est stockée.

    Source UNIQUE de l'empreinte d'escouade. Remplace le motif
    ``entry.get("occupied_hexes", {(col, row)})`` qui était recopié ~96 fois : ce défaut de ``.get``
    ne protégeait RIEN hors table, la clé y étant PRÉSENTE et VIDE — l'ensemble vide passait, et
    ``min_distance_between_sets`` levait « Cannot compute distance between empty sets » loin du
    vrai coupable.

    Hors table → lève (cf. ``require_entry_on_battlefield``). Le repli sur l'ancre ne subsiste que
    pour les entrées SYNTHÉTIQUES posées sur la table (mover candidat de
    ``move_anchor_violates_engagement_clearance``, fixtures mono-figurine), où il est exact.
    """
    require_entry_on_battlefield(cache_entry, "entry_footprint")
    footprint = cache_entry.get("occupied_hexes")  # get allowed (l'absence est le cas synthétique)
    if footprint:
        return footprint
    return {(require_key(cache_entry, "col"), require_key(cache_entry, "row"))}


def entries_on_battlefield(
    units_cache: Dict[str, Any], *, exclude_id: Optional[str] = None
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Énumère les entrées ``units_cache`` POSÉES, dans l'ordre du cache.

    Filtre UNIQUE des unités hors table pour tout code qui mesure une géométrie. Écrire le filtre
    ici et non à chaque boucle est le correctif de fond : ~30 énumérations le manquaient, et un
    filtre manquant ne se voit pas — l'unité hors table est VIVANTE et présente dans le cache,
    donc tout test écrit sur « vivante » la laisse passer.
    """
    exclude = None if exclude_id is None else str(exclude_id)
    for unit_id, entry in units_cache.items():
        if exclude is not None and str(unit_id) == exclude:
            continue
        if not entry_is_on_battlefield(entry):
            continue
        yield str(unit_id), entry


def enemy_entries_on_battlefield(
    units_cache: Dict[str, Any], player: Optional[int], *, exclude_id: Optional[str] = None
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Énumère les entrées ennemies de ``player`` qui sont POSÉES (jumeau de
    ``entries_on_battlefield`` côté ciblage).

    ``player`` ``None`` (unité sans camp) → aucune entrée n'est ennemie, la comparaison
    ``==`` étant fausse pour tout camp entier ; c'est le comportement des boucles remplacées.
    """
    for unit_id, entry in entries_on_battlefield(units_cache, exclude_id=exclude_id):
        if int(require_key(entry, "player")) == player:
            continue
        yield unit_id, entry


# Hex count of a single base, memoized by geometry. The COUNT is invariant under
# translation and depends only on (shape, size, orientation, column parity) — see
# precompute_footprint_offsets: only column parity shifts the odd-q footprint.
_SINGLE_BASE_HEX_COUNT_CACHE: Dict[Tuple[Any, ...], int] = {}


def _single_base_hex_count(
    base_shape: str, base_size: Any, orientation: int, col_parity: int
) -> int:
    """Memoized number of hexes occupied by one base of the given geometry."""
    key = (base_shape, base_size_cache_key(base_size), orientation, col_parity)
    cached = _SINGLE_BASE_HEX_COUNT_CACHE.get(key)
    if cached is None:
        # col_parity as the reference column preserves odd-q parity; row 0 is arbitrary
        # (the count is translation-invariant), matching the legacy per-call computation.
        cached = len(compute_occupied_hexes(
            col_parity, 0, base_shape,
            require_base_size(base_shape, base_size, "_single_base_hex_count"),
            orientation,
        ))
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


def geometry_is_hex(game_state: Optional[Dict[str, Any]] = None) -> bool:
    """POINT DE BASCULE UNIQUE de la résolution : la géométrie du jeu est-elle HEXAGONALE ?

    Vrai ssi ``inches_to_subhex <= 1``. À cette résolution une figurine tient dans UNE case —
    c'est la définition du board x1, et ``game_state._scale_socle`` y normalise déjà le socle en
    ``round``/1 pour la même raison. Mesurer une distance CONTINUE (euclidienne, bord à bord)
    entre des socles réduits à un point de grille n'a pas de sens : la géométrie est hex, donc
    move / charge / EZ / coherency s'y mesurent en hex. Au-dessus (x5 et plus), le socle occupe
    plusieurs cases, « bord à bord » a un sens, et la métrique configurée s'applique.

    SEUL critère de résolution du moteur : ``inches_to_subhex``. Le prédicat historique
    ``ez <= 1`` disséminé dans ~15 sites était un PROXY de « board x1 » — il a cessé d'en être un
    le 2026-06-03 (`7aaecaf9`), quand ``game_rules.engagement_zone`` est passé de 1" à 2" : à x1,
    ``ez = 2 × 1 = 2``, donc ces gardes ne se déclenchent plus et le x1 est reparti en euclidien
    sans que rien ne le dise. Deux crashes « incohérence masque/exécution » en sont sortis (pool
    FLY, coherency d'escouade).

    ``game_state`` absent : la résolution est relue depuis le MÊME config-loader que la métrique
    (``get_board_config``), ce qui permet aux ~60 call-sites de la primitive
    ``unit_entries_within_engagement_zone`` de rester inchangés. Aucun défaut caché : clé absente
    → erreur explicite (CLAUDE.md).
    """
    if game_state is not None and "inches_to_subhex" in game_state:
        return int(game_state["inches_to_subhex"]) <= 1
    from config_loader import get_config_loader

    board = require_key(get_config_loader().get_board_config(), "default")
    return int(require_key(board, "inches_to_subhex")) <= 1


def engagement_distance_metric(game_state: Optional[Dict[str, Any]] = None) -> str:
    """Métrique de la zone d'engagement (``hex``|``euclidean``) — sélecteur UNIQUE (Étape 7).

    L'EZ est un concept unique consommé par 4 phases (move, tir, charge, fight) → une seule
    clé ``distance_metric["engagement"]``, pas de split gym (contrairement à move/charge : le
    retrain IA est prévu à la bascule 7.6, cf. Distance management.md). Lue depuis le config-loader
    global (``game_state`` non requis) → la primitive canonique ``unit_entries_within_engagement_zone``
    peut résoudre la métrique sans toucher ses ~60 call-sites. Aucun défaut caché : section/clé/valeur
    invalide → erreur explicite (CLAUDE.md).

    La RÉSOLUTION primer sur la config : à ``inches_to_subhex <= 1`` la géométrie est hex
    (cf. ``geometry_is_hex``). La clé de config reste lue et validée — une valeur invalide doit
    lever à x1 comme ailleurs, pas être court-circuitée par la résolution.

    Pourquoi fight_handlers.py passe ``game_state`` explicitement (commit 2dc65810) :
    la justification du commit (empoisonnement du singleton config-loader entre workers
    parallèles x1/x5) est FAUSSE — chaque worker porte sa propre résolution via
    ``os.environ["W40K_BOARD_PATH"]`` posé dans ``train.py`` avant tout chargement, et les
    workers vectorisés sont des process séparés avec chacun leur singleton. La divergence
    ``geometry_is_hex(game_state)`` ≠ ``geometry_is_hex(None)`` n'apparaît qu'en construction
    de test, jamais en production. Le pattern est conservé car il est absorbé par le chantier
    « primitive porteuse de game_state » (moteur.md §replis-unit-by-id et suivants).
    """
    from config_loader import get_config_loader
    from engine.combat_utils import get_distance_metric

    metric = get_distance_metric("engagement", get_config_loader().get_game_config())
    return "hex" if geometry_is_hex(game_state) else metric


def entries_in_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    metric: str,
    vertical_zone_inches: Optional[float] = None,
    *,
    memoise: bool = True,
) -> bool:
    """Point de bascule pairwise de l'EZ (règle 03.04, bord-à-bord). Deux socles sont en zone
    d'engagement mutuelle ssi leur distance bord-à-bord ≤ ``engagement_zone`` :

    - ``metric == "hex"``       : ``min_distance_between_sets`` d'empreintes ≤ ez (comportement
      historique, byte-identique à l'ancien ``unit_entries_within_engagement_zone``).
    - ``metric == "euclidean"`` : ``euclidean_edge_distance`` ≤ ``engagement_minimum_clearance_norm``
      (= ez × 1,5). Miroir de ``ranged_in_range`` — l'EZ est une portée de ``ez`` subhexes bord-à-bord.

    Conversion ×1,5 confinée à ``engagement_minimum_clearance_norm``, jamais dispersée.

    ENGAGEMENT 3D (règle 03.04 = 2" horizontal ET 5" vertical, stage.md chantier 4). Le gate
    vertical est piloté par la DONNÉE, pas par l'opt-in de l'appelant :
    - les deux entrées portent leurs cartes verticales (``entry_has_vertical_data``) → gate
      appliqué, **par paire de figurines** (§03.04 est par-modèle) : ∃ (fig_a, fig_b) dont les
      intervalles ``[plancher, plancher+MODEL_HEIGHT]`` sont séparés de ``≤ seuil`` (§01.04
      « partie la plus proche », pas plancher-à-plancher) ET dont la distance horizontale ≤ seuil
      horizontal ;
    - sinon → chemin 2D (agrégat). Donnée absente = verdict horizontal, jamais une altitude
      supposée.

    POURQUOI PAR LA DONNÉE ET NON PAR L'APPELANT. Le gate a d'abord été plombé à la main sur ~49
    call-sites via ``vertical_zone_inches=``. Il en restait **17 en 2D**, dont deux jumeaux directs
    de sites traités (``generic_handlers._is_adjacent_to_enemy_for_fight`` vs
    ``fight_handlers._is_adjacent_to_enemy_within_cc_range`` ; ``shared_utils.squad_is_engaged`` vs
    ``fight_handlers._fight_v11_engaged_now``) et les sept tests d'engagement de 10.05/10.06 — une
    escouade pouvait donc être *engagée* pour l'interdiction de tir et *non engagée* pour le
    combat, sur la même paire. Un oubli d'opt-in ne lève pas : il rend un verdict faux. C'est
    exactement le raisonnement déjà tenu pour ``metric`` (résolue par la primitive, cf.
    ``engagement_distance_metric``), appliqué à l'autre moitié de la règle.

    ``vertical_zone_inches`` ne survit donc que comme ÉPINGLAGE, même rôle que ``metric`` explicite :
    ``None`` → seuil résolu par ``get_engagement_zone_vertical()`` (config-loader) ; valeur → seuil
    imposé. L'analyzer en a besoin — il lit le sien dans l'entête ``Run rules:`` du journal analysé,
    pas dans le config du jour.
    """
    # Hors table AVANT « mesurable » : l'entrée hors table est bien FORMÉE (cartes par-figurine
    # peuplées de `(-1,-1)`), donc `_require_measurable_entry` la laisse passer et le chemin 3D
    # ci-dessous rend « engagée » face à toute unité réelle proche de l'origine. MESURÉ à x1/hex
    # (EZ = 2) : fantôme vs unité en `(0,0)` → True. Un verdict inventé, jamais un crash.
    # Les quatre gardes restent HORS du cache : elles lèvent sur un état incohérent, et servir une
    # valeur mémoïsée à leur place ferait disparaître l'erreur au lieu de la signaler.
    require_entry_on_battlefield(first_entry, "entries_in_engagement_zone")
    require_entry_on_battlefield(second_entry, "entries_in_engagement_zone")
    _require_measurable_entry(first_entry)
    _require_measurable_entry(second_entry)
    is_3d = entry_has_vertical_data(first_entry) and entry_has_vertical_data(second_entry)
    # Le seuil vertical entre dans la clé sous sa forme RÉSOLUE : à `None`, il vient du config, et
    # deux configs différentes doivent donner deux entrées de cache distinctes. Il n'est résolu que
    # sur le chemin 3D, exactement comme avant — le chemin 2D ne le lit pas.
    threshold_v = (
        (get_engagement_zone_vertical() if vertical_zone_inches is None
         else float(vertical_zone_inches))
        if is_3d else None
    )
    # La paire est ORDONNÉE (pas de `frozenset`) : la mesure est symétrique, mais l'exprimer dans
    # la clé demanderait de trier deux empreintes à chaque appel — plus cher que le doublon qu'on
    # économiserait. Un doublon coûte une entrée, jamais un verdict faux.
    if not memoise:
        return _entries_in_engagement_zone_uncached(
            first_entry, second_entry, engagement_zone, metric, is_3d, threshold_v
        )
    fp_a = _engagement_entry_fingerprint(first_entry)
    fp_b = _engagement_entry_fingerprint(second_entry)
    cache_key = (fp_a, fp_b, engagement_zone, metric, threshold_v)
    cached = _EZ_PAIR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    weight = _fingerprint_weight(fp_a) + _fingerprint_weight(fp_b)
    if (
        (_EZ_WEIGHT["items"] + weight) * _EZ_BYTES_PER_ITEM > _EZ_PAIR_CACHE_MAX_BYTES
        or len(_EZ_PAIR_CACHE) >= _EZ_MAX_ENTRIES
    ):
        _EZ_PAIR_CACHE.clear()
        _EZ_WEIGHT["items"] = 0
    result = _entries_in_engagement_zone_uncached(
        first_entry, second_entry, engagement_zone, metric, is_3d, threshold_v
    )
    _EZ_PAIR_CACHE[cache_key] = result
    _EZ_WEIGHT["items"] += weight
    return result


def _entries_in_engagement_zone_uncached(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    metric: str,
    is_3d: bool,
    threshold_v: Optional[float],
) -> bool:
    """Mesure d'engagement PROPREMENT DITE — cf. `entries_in_engagement_zone` pour la règle.

    Séparée uniquement pour que la mémoïsation n'ait pas à s'intercaler dans le corps de la règle.
    Les gardes d'état incohérent ont déjà été appliquées par l'appelant.
    """
    if is_3d:
        assert threshold_v is not None  # posé par l'appelant sur ce chemin exactement
        return _entries_in_engagement_zone_3d(
            first_entry, second_entry, engagement_zone, threshold_v, metric
        )
    if metric == "hex":
        first_fp = entry_footprint(first_entry)
        second_fp = entry_footprint(second_entry)
        return min_distance_between_sets(
            first_fp, second_fp, max_distance=engagement_zone
        ) <= engagement_zone
    if metric == "euclidean":
        from engine.combat_utils import socle_from_cache_entry
        a = socle_from_cache_entry(first_entry)
        b = socle_from_cache_entry(second_entry)
        threshold = engagement_minimum_clearance_norm(engagement_zone)
        # `max_distance` : jumeau euclidien de l'appel `hex` ci-dessus. Ce site ne lit qu'un
        # booléen de seuil, donc l'exactitude au-delà du seuil ne lui sert à rien.
        return euclidean_edge_distance(a, b, max_distance=threshold) <= threshold
    raise ValueError(f"Invalid engagement metric {metric!r}, expected 'hex' or 'euclidean'")


def _vertical_classes(
    entry: Dict[str, Any],
) -> Tuple[Dict[float, List[Tuple[int, int]]], float]:
    """Regroupe les centres par-figurine d'une entrée-cache par hauteur de PLANCHER, + MODEL_HEIGHT.

    Retour : ``({floor_height: [(col,row), …]}, model_height)``. Source : ``occupied_hexes_by_model``
    (centres) + ``floor_height_by_model`` (plancher par fig, chantier 4 étape 1) + ``MODEL_HEIGHT``
    (borne haute). Aucune de ces clés absente n'est tolérée en mode 3D : erreur explicite (câblage
    incomplet), pas de repli silencieux (CLAUDE.md)."""
    if not entry_has_vertical_data(entry):
        raise ValueError(
            "engagement 3D demandé mais entrée-cache sans données verticales "
            f"({' / '.join(_VERTICAL_ENTRY_KEYS)}) — câblage incomplet"
        )
    by_model = entry["occupied_hexes_by_model"]
    floor_h = entry["floor_height_by_model"]
    classes: Dict[float, List[Tuple[int, int]]] = {}
    for mid, (col, row) in by_model.items():
        h = float(require_key(floor_h, mid))
        classes.setdefault(h, []).append((int(col), int(row)))
    return classes, float(entry["MODEL_HEIGHT"])


def vertical_intervals_within(
    floor_a: float, height_a: float, floor_b: float, height_b: float,
    vertical_zone_inches: float,
) -> bool:
    """Deux figurines sont-elles à portée VERTICALE l'une de l'autre (§03.04 : 5") ?

    Chaque figurine occupe la tranche ``[plancher, plancher + MODEL_HEIGHT]`` ; on mesure la
    séparation des deux tranches (§01.04 « partie la plus proche », pas plancher-à-plancher) et
    on la compare au seuil. Tranches qui se recouvrent → séparation nulle → à portée.

    SOURCE UNIQUE de cette formule. Elle a existé en quatre exemplaires, dont deux hors de ce
    module : le jour où la règle verticale bouge — mesure depuis le sommet du socle, MODEL_HEIGHT
    par figurine plutôt que par unité, tolérance — les copies restent silencieusement sur
    l'ancienne définition. C'est le motif JUMEAU, appliqué à quatre lignes identiques.
    """
    return max(
        0.0, max(floor_a, floor_b) - min(floor_a + height_a, floor_b + height_b)
    ) <= vertical_zone_inches


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
    for floor_e in classes:
        if vertical_intervals_within(
            cand_floor_inches, cand_model_height, floor_e, entry_height, vertical_zone_inches
        ):
            return True
    return False


def _entries_in_engagement_zone_3d(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    vertical_zone_inches: float,
    metric: str,
) -> bool:
    """Engagement 3D par paire de figurines (cf. ``entries_in_engagement_zone``).

    Pour chaque paire de classes verticales (hauteur de plancher) des deux unités, on applique
    d'abord le **gate vertical** (séparation des intervalles ``[plancher, plancher+MODEL_HEIGHT]``),
    puis — seulement si la paire passe — le **test horizontal** de la métrique courante, restreint
    aux centres de cette classe.

    Le gate vertical est INDÉPENDANT de la métrique horizontale (§03.04 : 2" horizontal ET 5"
    vertical). Cette fonction levait « supporté uniquement en métrique euclidean » : c'était vrai de
    l'implémentation, pas de la règle, et à x1 — où la géométrie est hex
    (``geometry_is_hex``) — l'éligibilité de charge tombait dessus. Le test horizontal hex est le
    même que celui du chemin 2D (distance d'empreinte ≤ ez), calculé sur les empreintes des seules
    figurines de la classe verticale."""
    from engine.combat_utils import socle_from_cache_entry
    from engine.hex_utils import compute_occupied_hexes

    a_classes, a_height = _vertical_classes(first_entry)
    b_classes, b_height = _vertical_classes(second_entry)
    threshold = engagement_minimum_clearance_norm(engagement_zone)
    if metric not in ("hex", "euclidean"):
        raise ValueError(f"Invalid engagement metric {metric!r}, expected 'hex' or 'euclidean'")
    hex_metric = metric == "hex"
    # Socles complets : seul le chemin euclidien les consomme (le hex mesure des empreintes).
    base_a = None if hex_metric else socle_from_cache_entry(first_entry)
    base_b = None if hex_metric else socle_from_cache_entry(second_entry)

    def _class_footprint(entry: Dict[str, Any], centers: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        shape = require_key(entry, "BASE_SHAPE")
        size = require_key(entry, "BASE_SIZE")
        orient = int(entry.get("orientation", 0))  # fallback allowed — entrées synthétiques sans facing
        cells: Set[Tuple[int, int]] = set()
        for c, r in centers:
            cells |= set(compute_occupied_hexes(int(c), int(r), shape, size, orient))
        return cells

    # Empreintes par classe verticale calculées UNE fois : une classe de A est comparée à toutes
    # les classes de B, donc les recalculer dans la boucle interne les refabriquerait |B| fois.
    fps_a: Dict[float, Set[Tuple[int, int]]] = (
        {f: _class_footprint(first_entry, c) for f, c in a_classes.items()} if hex_metric else {}
    )
    fps_b: Dict[float, Set[Tuple[int, int]]] = (
        {f: _class_footprint(second_entry, c) for f, c in b_classes.items()} if hex_metric else {}
    )

    for floor_a, centers_a in a_classes.items():
        for floor_b, centers_b in b_classes.items():
            if not vertical_intervals_within(
                floor_a, a_height, floor_b, b_height, vertical_zone_inches
            ):
                continue
            if hex_metric:
                if min_distance_between_sets(
                    fps_a[floor_a], fps_b[floor_b], max_distance=engagement_zone
                ) <= engagement_zone:
                    return True
                continue
            assert base_a is not None and base_b is not None  # métrique euclidienne (cf. ci-dessus)
            socle_a = base_a.with_model_centers(centers_a)
            socle_b = base_b.with_model_centers(centers_b)
            if euclidean_edge_distance(socle_a, socle_b, max_distance=threshold) <= threshold:
                return True
    return False


def unit_entries_within_engagement_zone(
    first_entry: Dict[str, Any],
    second_entry: Dict[str, Any],
    engagement_zone: int,
    metric: Optional[str] = None,
    vertical_zone_inches: Optional[float] = None,
    *,
    game_state: Optional[Dict[str, Any]] = None,
    memoise: bool = True,
) -> bool:
    """Return True when two unit cache entries are within the shared engagement contract.

    Primitive canonique EZ (règle 03.04, bord-à-bord).

    Résolution de la métrique — deux formes légitimes :
    - **Normale** (``metric=None``, ``game_state=game_state``) : la primitive appelle
      ``engagement_distance_metric(game_state)`` et le verdict suit l'état courant de la partie.
      C'est la forme par défaut pour tout nouveau call-site.
    - **Pré-calculé** (``metric=metric_str``) : l'appelant résout la métrique UNE fois avant une
      boucle serrée (pool BFS — N ≥ quelques milliers d'appels par invocation) et la passe
      explicitement. ``game_state`` est ignoré quand ``metric`` est fourni.

    Épingler une valeur CODÉE EN DUR (ex. ``metric="hex"``) hors des tests est interdit.
    Les tests peuvent fixer la métrique pour construire une situation dans une géométrie donnée.
    """
    if metric is None:
        metric = engagement_distance_metric(game_state)
    return entries_in_engagement_zone(
        first_entry, second_entry, engagement_zone, metric, vertical_zone_inches,
        memoise=memoise,
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

    # HORS TABLE (réserves 20.01, attente de déploiement) : la réponse est donnée par la RÈGLE —
    # une unité absente du champ de bataille n'est engagée avec personne. Ce n'est pas un repli
    # anti-erreur : c'est un prédicat qui a une réponse juste, contrairement à la MESURE par paire
    # (`entries_in_engagement_zone`), qui n'en a aucune et lève. Les appelants posent la question
    # sur TOUTES les unités vivantes (snapshot 12.04, masque d'observation), réserves comprises.
    if not entry_is_on_battlefield(unit_entry):
        return False
    unit_player = int(require_key(unit, "player"))
    for _enemy_id, cache_entry in enemy_entries_on_battlefield(
        units_cache, unit_player, exclude_id=unit_id_str
    ):
        if unit_entries_within_engagement_zone(
            unit_entry, cache_entry, engagement_zone,
            vertical_zone_inches=vertical_zone_inches, game_state=game_state,
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
    metric = engagement_distance_metric(game_state)

    # Géométrie HEX (x1, ou config ``engagement:"hex"``) : l'EZ EST l'ensemble pré-dilaté
    # ``enemy_adjacent_hexes_player_N``. C'est la MÊME source que l'exécution
    # (``build_move_blocked_cells_by_level`` → ``validate_move_plan`` / érosion du pool), donc
    # « masque ⊆ exécutable » tient par construction et non par une inclusion numérique.
    # ⚠️ La condition était ``engagement_zone_ez <= 1``, un proxy de « board x1 » devenu faux le
    # 2026-06-03 (engagement_zone 1" → 2") : à x1 cette branche ne se déclenchait plus et le pool
    # partait en euclidien face à une exécution hex — cf. ``geometry_is_hex``.
    if metric == "hex":
        if enemy_adjacent_hexes is None:
            ck = f"enemy_adjacent_hexes_player_{mover_player}"
            adjacent_hexes: Set[Tuple[int, int]] = require_key(game_state, ck)
        else:
            adjacent_hexes = enemy_adjacent_hexes
        for c, r in candidate_fp:
            if (c, r) in adjacent_hexes:
                return True
        return False

    # Métrique d'engagement unifiée (Étape 7.1) : routée via le switch pairwise. Le mover candidat
    # est synthétisé en entrée-cache (empreinte candidate + socle du mover) pour alimenter le switch.
    mover_entry = {
        "BASE_SHAPE": require_key(mover, "BASE_SHAPE"),
        "BASE_SIZE": require_key(mover, "BASE_SIZE"),
        "col": center_col,
        "row": center_row,
        "occupied_hexes": candidate_fp,
        # ORIENTATION propagée. Sans elle, `socle_from_cache_entry` retombait sur 0 et la branche
        # euclidienne — qui reconstruit le CONTOUR depuis `s.orientation` et ignore
        # `candidate_fp` — mesurait un socle non rond à l'horizontale quelle que soit sa pose
        # réelle. Un WarTrakk (oval) pivoté pouvait donc finir son move engagé (09.05) : la
        # revalidation d'EZ au commit passe par ici.
        "orientation": int(mover.get("orientation", 0)),  # get allowed (socle rond non orienté)
    }
    if enemy_cache_items is not None:
        enemy_iter: Any = enemy_cache_items
    else:
        enemy_iter = enemy_entries_on_battlefield(
            units_cache, mover_player, exclude_id=mover_id
        )

    for _, cache_entry in enemy_iter:
        # `memoise=False` : `mover_entry` décrit une CELLULE CANDIDATE, pas une unité posée. Un
        # pool de move en construit une par cellule explorée, donc une clé de cache neuve à chaque
        # fois, qui ne resservira jamais — mesuré à x5 : ~21 600 clés à usage unique pour un seul
        # pool. Les mémoïser ne fait pas que gaspiller la construction de la clé, ça CHASSE du
        # cache les paires unité↔unité qui, elles, sont redemandées par le masque, les pools et
        # l'observation du même step. Mesuré : taux de touche 66 % → 29 %, 109 purges, et le gain
        # net passe de +4,53 s à **−2,00 s**. Le flot de candidats est donc exclu à la source.
        if entries_in_engagement_zone(
            mover_entry, cache_entry, engagement_zone_ez, metric, vertical_zone_inches,
            memoise=False,
        ):
            return True
    return False
