#!/usr/bin/env python3
"""
deployment_handlers.py - Deployment Phase Implementation (Test mode)

Footprint-aware: validates entire unit footprint (multi-hex bases) during deployment.
"""

import math
from typing import AbstractSet, Dict, Any, Iterable, Sequence, Tuple, List, Optional, Set
from shared.data_validation import require_key
from engine.game_utils import enter_phase, get_unit_by_id
from engine.combat_utils import set_unit_coordinates
from engine.terrain_utils import validate_floor_placement
from engine.phase_handlers.shared_utils import (
    rebuild_choice_timing_index,
    compute_candidate_footprint, build_occupied_positions_set,
    candidate_overlaps_any_unit, coherency_violation_flags,
    place_model_at_effective_level, resolve_model_effective_level, wall_blocked_anchors,
    _model_height_of,
    _build_enemy_adjacent_hexes_all_players,
    _squad_mode_level,
)


def deployment_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize deployment phase using precomputed deployment_state.
    """
    if "deployment_state" not in game_state:
        raise KeyError("deployment_state is required to start deployment phase")
    _build_enemy_adjacent_hexes_all_players(game_state)
    enter_phase(game_state, "deployment")
    return {"phase_start": True}


def _get_deployment_pool(deployment_pools: Dict[Any, Any], player: int) -> List[Tuple[int, int]]:
    if player in deployment_pools:
        return deployment_pools[player]
    player_key = str(player)
    if player_key in deployment_pools:
        return deployment_pools[player_key]
    raise KeyError(f"deployment_pools missing player {player}")


def deployable_units_of(deployment_state: Dict[str, Any], player: int) -> list:
    """Alias PUBLIC de `_get_deployable_remaining` — la convention de clés int-ou-str, une fois.

    Existe parce que trois modules hors de ce fichier (le résumé API, la clôture de phase, le
    poseur automatique) posent la MÊME question et la résolvaient chacun à leur façon
    (`.get(player, .get(str(player)))` recopié). Une 5e copie divergerait le jour où les clés
    seront normalisées.
    """
    return _get_deployable_remaining(deployment_state, player)


def _get_deployable_remaining(deployment_state: Dict[str, Any], player: int) -> list:
    """Get remaining deployable units for player. Raises KeyError if player key missing."""
    deployable_units = require_key(deployment_state, "deployable_units")
    if player in deployable_units:
        return deployable_units[player]
    if str(player) in deployable_units:
        return deployable_units[str(player)]
    raise KeyError(f"deployable_units missing player {player}")


def _is_footprint_overlapping(
    game_state: Dict[str, Any],
    candidate_fp: Set[Tuple[int, int]],
    *,
    shape: str,
    base_size: "int | list[int]",
    col: int,
    row: int,
    exclude_unit_id: Optional[str] = None,
) -> bool:
    """True si le socle candidat chevauche celui d'une unité déjà déployée.

    Clearance continu rond↔rond, méthode empreinte (via ``candidate_overlaps_any_unit``).
    """
    from engine.hex_utils import Socle

    cand = Socle(shape=shape, base_size=base_size, col=col, row=row, fp=candidate_fp)
    return candidate_overlaps_any_unit(game_state, cand, exclude_unit_id=exclude_unit_id)


def _mark_deployed(deployment_state: Dict[str, Any], unit_id: str, current_deployer: int) -> None:
    deployable_units = require_key(deployment_state, "deployable_units")
    deployed_units = require_key(deployment_state, "deployed_units")
    if not isinstance(deployed_units, set):
        raise TypeError("deployment_state.deployed_units must be a set")
    deployed_units.add(unit_id)
    if current_deployer in deployable_units:
        deployable_units[current_deployer] = [uid for uid in deployable_units[current_deployer] if str(uid) != str(unit_id)]
    else:
        current_key = str(current_deployer)
        if current_key in deployable_units:
            deployable_units[current_key] = [uid for uid in deployable_units[current_key] if str(uid) != str(unit_id)]
        else:
            raise KeyError(f"deployable_units missing player {current_deployer}")


def _resolve_next_deployer_after_success(
    deployment_state: Dict[str, Any], current_deployer: int
) -> Optional[int]:
    """
    Resolve next deployer after a successful deployment with alternated order.

    Rules:
    - Player 1 starts (initialized elsewhere).
    - Alternate after each deployment while both players still have deployable units.
    - If only one player has deployable units left, that player continues.
    - Return None when deployment is complete.
    """
    remaining_current = _get_deployable_remaining(deployment_state, int(current_deployer))
    other_player = 2 if int(current_deployer) == 1 else 1
    remaining_other = _get_deployable_remaining(deployment_state, other_player)

    has_current = len(remaining_current) > 0
    has_other = len(remaining_other) > 0

    if has_current and has_other:
        return other_player
    if has_current:
        return int(current_deployer)
    if has_other:
        return other_player
    return None


# ============================================================================
# DÉPLOIEMENT PAR ESCOUADE (plan par-figurine)
# ============================================================================
# Réutilise les primitives partagées (shared_utils : compute_candidate_footprint,
# coherency_violation_flags, place_model_at_effective_level ; hex_utils : Socle,
# footprints_overlap). La SEULE différence avec le move plan est la contrainte
# spatiale : footprint ⊆ zone de déploiement (pool_set) au lieu d'un budget de
# mouvement + zone d'engagement ennemie.


def _deploy_pool_set(
    game_state: Dict[str, Any],
    player: int,
    pool_override: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> AbstractSet[Tuple[int, int]]:
    """Cellules où la mise en place (03.02) est légale pour ``player``.

    ``pool_override`` : aire légale IMPOSÉE par la règle qui déclenche la mise en place. La
    zone de déploiement n'est qu'un cas particulier — l'ingress move (20.04) pose l'unité à 6"
    d'un bord et à plus de 8" des ennemis, le Deep Strike (24.09) n'importe où sur le plateau.
    Le RESTE de la validité de placement (bornes, murs, empreintes, cohésion, étages) est
    identique et n'est donc jamais réimplémenté : seul cet ensemble change.
    """
    if pool_override is not None:
        # `frozenset` : passe-plat. L'aire d'ingress fait jusqu'à 57 538 cases DÉJÀ normalisées
        # en `(int, int)` et immuables ; la recopie défensive coûtait 36,6 ms sur les 53 ms d'une
        # action d'arrivée (3 appels), pour protéger d'une mutation qui ne peut pas arriver.
        if isinstance(pool_override, frozenset):
            return pool_override
        return {(int(c), int(r)) for c, r in pool_override}
    # `require_key` AVANT toute lecture du cache : sans zones déclarées, les lecteurs doivent lever
    # au lieu de se voir servir une zone périmée (verrouillé par test).
    deployment_pools = require_key(game_state, "deployment_pools")
    # Mémoïsé par joueur : la zone est une donnée de SCÉNARIO (aucun écrivain hors du reset et de
    # la rotation), alors que ce `set` de ~16 000 hexes était rematérialisé à chaque appel — 2,5 ms
    # sur les 12,6 ms d'une formation, soit 20 %, pour recopier une donnée immuable.
    #
    # JUMEAU de `_los_blocking_grids_cache` (shooting_handlers), même triplet obligatoire :
    #   1. stocké dans `game_state` — jamais au niveau module, où `id()` se recycle d'un engine à
    #      l'autre (c'est la raison d'être de `_cache_instance_id`, cf. shooting_handlers.py) ;
    #   2. déclaré dans `_GS_STATIC_KEYS` (game_snapshots) — sinon deepcopy à CHAQUE capture de
    #      phase PvP, soit l'inverse du gain recherché ;
    #   3. PURGÉ partout où les zones sont (re)publiées — `reset` et `_reload_scenario`.
    # Sans (3) le cache survivrait à un changement de scénario et rendrait la zone du précédent ;
    # pire, il masquerait la branche « scénario sans zones » du reset, qui RETIRE la clé
    # précisément pour que les lecteurs lèvent (require_key) au lieu de lire une zone périmée.
    cache = game_state.get("_deploy_pool_set_cache")  # get allowed (cache absent = 1er appel)
    if cache is None:
        cache = {}
        game_state["_deploy_pool_set_cache"] = cache
    key = int(player)
    cached = cache.get(key)  # get allowed
    if cached is None:
        pool = _get_deployment_pool(deployment_pools, key)
        # `frozenset` : le résultat est partagé entre tous les appelants, donc il doit être
        # immuable — un appelant qui muterait le set corromprait la zone de tous les autres.
        cached = frozenset((int(c), int(r)) for c, r in pool)
        cache[key] = cached
    return cached


def placement_pool_for_squad(
    game_state: Dict[str, Any], squad_id: str
) -> Optional[AbstractSet[Tuple[int, int]]]:
    """L'aire légale de mise en place de CETTE escouade, ou ``None`` pour « zone de déploiement ».

    UN SEUL endroit répond à « où cette escouade a-t-elle le droit d'être posée ? ». Une escouade
    EN RÉSERVES (20.01) n'est pas posée dans la zone de déploiement mais dans son aire d'arrivée
    20.04, qui dépend de SES paramètres (bande de bord, clairance ennemie, zone adverse) — donc
    d'elle, pas de son joueur. Toutes les primitives de placement (formation compacte, preview
    par-figurine, pool per-fig, pool de suivi de bloc) passent par ici : le plan que le joueur
    édite à l'écran est ainsi contraint par la MÊME aire que celle qui validera son commit.

    Rendre ``None`` plutôt que la zone de déploiement garde `_deploy_pool_set` seul propriétaire
    de la lecture des zones : un seul site à repointer le jour où leur stockage change.
    """
    from engine.phase_handlers.movement_handlers import (
        ingress_setup_pool,
        unit_is_in_strategic_reserves,
    )

    if not unit_is_in_strategic_reserves(game_state, str(squad_id)):
        return None
    return ingress_setup_pool(game_state, str(squad_id))


def _deployed_occupied_positions(
    game_state: Dict[str, Any], exclude_squad_id: str, level: Optional[int] = None
) -> Set[Tuple[int, int]]:
    """Cellules occupées par les escouades SUR LE CHAMP DE BATAILLE (hors ``exclude_squad_id``).

    Le critère est la PRÉSENCE sur le plateau (``entry_is_on_battlefield``), pas l'appartenance
    à ``deployment_state["deployed_units"]`` : ce set ne recense que les poses commises par le
    déploiement ACTIF, donc il ignorait les unités du camp d'en face posées en mode 'fixed'
    (elles ne bloquaient aucune case) et il ne connaît pas les unités arrivées de réserves
    (20.04). Les unités hors table n'ont, elles, aucune empreinte (`occupied_hexes` vide).

    ``level`` : None = toutes figs confondues (comportement historique). Un entier
    restreint aux figurines à ce niveau (deux figs à des étages différents
    ne se gênent pas — murs mis à part, cf. verticalite.md § murs verticaux prolongés).
    """
    from engine.spatial_relations import entries_on_battlefield, entry_footprint

    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    if level is None:
        for _uid, entry in entries_on_battlefield(units_cache, exclude_id=exclude_squad_id):
            occupied.update((int(c), int(r)) for c, r in entry_footprint(entry))
        return occupied
    # Filtrage par niveau : empreinte par-figurine des figs présentes au niveau demandé.
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for uid, _entry in entries_on_battlefield(units_cache, exclude_id=exclude_squad_id):
        for mid in squad_models.get(str(uid), []):  # get allowed
            m = models_cache.get(mid)
            if m is None or int(require_key(m, "level")) != level:
                continue
            occupied.update(_model_footprint(game_state, m, int(m["col"]), int(m["row"])))
    return occupied


_FOOTPRINT_OFFSETS_CACHE: Dict[
    Tuple[Any, ...], Optional[Tuple[Tuple[Tuple[int, int], ...], ...]]
] = {}


def _footprint_offsets_for(
    base_shape: str, base_size: Any, orientation: int, engagement_zone: int
) -> Optional[Tuple[Tuple[Tuple[int, int], ...], ...]]:
    """Offsets d'empreinte (colonne paire, colonne impaire) pour une géométrie de socle.

    ``None`` = socle mono-hex (``engagement_zone <= 1`` ou ``base_size == 1``) : rien à
    translater, l'empreinte est la cellule elle-même — les DEUX cas dégénérés de
    ``_compute_unit_occupied_hexes``, reproduits à l'identique.

    Cache au niveau MODULE : les offsets ne dépendent que de la géométrie du socle
    (forme, taille, orientation), jamais de l'état de jeu — les recalculer par appel de
    ``generate_compact_formation`` rejetterait le travail à chaque formation.
    """
    from engine.hex_utils import base_size_cache_key

    key = (
        base_shape,
        base_size_cache_key(base_size),
        int(orientation),
        int(engagement_zone) <= 1,
    )
    if key not in _FOOTPRINT_OFFSETS_CACHE:
        from engine.hex_utils import precompute_footprint_offsets

        _FOOTPRINT_OFFSETS_CACHE[key] = (
            None if (int(engagement_zone) <= 1 or base_size == 1)
            else precompute_footprint_offsets(base_shape, base_size, int(orientation))
        )
    return _FOOTPRINT_OFFSETS_CACHE[key]


def _model_footprint(
    game_state: Dict[str, Any], model: Dict[str, Any], col: int, row: int
) -> Set[Tuple[int, int]]:
    return compute_candidate_footprint(
        int(col), int(row),
        {
            "BASE_SHAPE": require_key(model, "BASE_SHAPE"),
            "BASE_SIZE": require_key(model, "BASE_SIZE"),
            "orientation": int(model.get("orientation", 0)),  # get allowed
        },
        game_state,
    )


def _alive_model_ids(game_state: Dict[str, Any], squad_id: str) -> List[str]:
    squad_models = require_key(game_state, "squad_models")
    models_cache = require_key(game_state, "models_cache")
    return [m for m in squad_models.get(str(squad_id), []) if m in models_cache]  # get allowed


def generate_compact_formation(
    game_state: Dict[str, Any], squad_id: str, center_col: int, center_row: int,
    pool_override: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> List[Tuple[str, int, int]]:
    """Génère une formation compacte (anneaux hex) autour de ``center`` pour toutes
    les figurines vivantes de l'escouade.

    Spirale BFS BORNÉE au plateau depuis le centre : chaque figurine prend la 1re
    cellule légale (dans la zone, hors mur, hors empreinte des unités déjà déployées
    et des figurines déjà placées). Si la zone ne peut pas toutes les accueillir, les
    restantes sont posées sur la 1re case in-bounds ne CHEVAUCHANT PAS une sœur déjà
    posée (zone/mur/autres unités ignorés → signalées rouge par le preview, à
    repositionner) : le squad est affiché EN ENTIER près du clic, sans empilement de
    socles (aucun placement hors-règle n'est masqué).
    """
    from collections import deque
    from engine.hex_utils import get_neighbors

    models_cache = require_key(game_state, "models_cache")
    model_ids = _alive_model_ids(game_state, squad_id)
    if not model_ids:
        raise KeyError(f"generate_compact_formation: no alive models for squad {squad_id}")

    units_cache = require_key(game_state, "units_cache")
    entry = require_key(units_cache, str(squad_id))
    player = int(require_key(entry, "player"))
    pool_set = _deploy_pool_set(game_state, player, pool_override)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    # Formation générée AU SOL → seules les figs déployées au niveau 0 bloquent (une fig à
    # l'étage ne bloque pas le sol sous elle). Le preview revalide ensuite par niveau effectif.
    other_occ = _deployed_occupied_positions(game_state, str(squad_id), level=0)
    # Clairance verticale (§13.06, miroir move) : la formation est AU SOL → une fig trop haute ne peut
    # être posée sous un étage trop bas (les restantes tombent au centre, signalées rouge par le preview).
    terrain_areas = require_key(game_state, "terrain_areas")
    from engine.terrain_utils import low_clearance_ground_hexes
    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        raise KeyError(f"generate_compact_formation: unit {squad_id} missing from game_state['units']")
    from engine.hex_utils import (
        Socle, footprints_overlap, _hex_center, _HEX_CIRCUMRADIUS,
        build_hex_center_index, disc_overlaps_indexed_hexes, round_base_radius_norm,
    )
    from engine.phase_handlers.shared_utils import get_engagement_zone
    ez = get_engagement_zone(game_state)

    # Clairance verticale — miroir du pool per-fig / du move. Base ronde : le DISQUE ne doit
    # chevaucher aucun hex de clairance (capsule stationnaire, rayon = socle) ; base non-ronde :
    # empreinte hex.
    #
    # PAR FIGURINE (socle ET hauteur), comme tout le reste de ce placement : les deux venaient de
    # l'escouade, si bien qu'un personnage attaché — plus large, éventuellement plus haut — était
    # posé sous un plancher où il ne tient pas. Mémoïsé par (hauteur, rayon) : une escouade
    # homogène ne construit qu'un index, exactement comme avant.
    _lc_by_gabarit: Dict[Tuple[float, float], Tuple[Set[Tuple[int, int]], Dict[Any, Any], float, float]] = {}

    def _clearance_for(model: Dict[str, Any]) -> Tuple[Set[Tuple[int, int]], Dict[Any, Any], float, float]:
        """(hexes de clairance, index disque, bucket, rayon) du gabarit de CETTE figurine."""
        _h = _model_height_of(model, unit)
        _shape = require_key(model, "BASE_SHAPE")
        _radius = round_base_radius_norm(require_key(model, "BASE_SIZE")) if _shape == "round" else 0.0
        cached = _lc_by_gabarit.get((_h, _radius))
        if cached is None:
            _cells = low_clearance_ground_hexes(terrain_areas, model, unit)
            _bucket = _radius + _HEX_CIRCUMRADIUS
            _index = build_hex_center_index(_cells, _bucket) if (_shape == "round" and _cells) else {}
            cached = (_cells, _index, _bucket, _radius)
            _lc_by_gabarit[(_h, _radius)] = cached
        return cached

    placed: List[Tuple[str, int, int]] = []
    placed_socles: List["Socle"] = []
    # Anneau bloquant cumulatif : empreinte + voisins de CHAQUE socle posé.
    # Mis à jour O(fp) à chaque placement ; la vérification dans _legal_socle
    # passe de O(N×fp×6) à O(fp) par cellule BFS.
    margin_blocked: Set[Tuple[int, int]] = set()

    # Empreinte par TRANSLATION d'offsets pré-calculés, au lieu de la recalculer à chaque case
    # de la spirale. Mesuré (cProfile, board x5, escouade de 6) : `_legal_socle` = 92 % du coût
    # de cette fonction, dont 67 % dans `compute_occupied_hexes`/`_footprint_round` — 2590
    # reconstructions d'empreinte et 341 660 appels à `_hex_center` pour UNE formation.
    # `precompute_footprint_offsets` est fait pour ça (docstring : « expensive when called
    # per-BFS-step … computes it ONCE at two reference positions ») et sert déjà au masque de
    # déploiement multi-hex (`_get_valid_deployment_hexes`). Deux jeux d'offsets car en grille
    # offset odd-q la forme dépend de la PARITÉ de colonne.
    # Équivalence stricte avec `_model_footprint` : celui-ci délègue à
    # `compute_candidate_footprint` → `_compute_unit_occupied_hexes`, qui renvoie {(col,row)}
    # quand `engagement_zone <= 1` OU `base_size == 1`, et `compute_occupied_hexes` sinon —
    # les deux cas dégénérés sont reproduits ici. Verrouillé par test.
    def _model_fp(model: Dict[str, Any], c: int, r: int) -> Set[Tuple[int, int]]:
        offsets = _footprint_offsets_for(
            require_key(model, "BASE_SHAPE"),
            require_key(model, "BASE_SIZE"),
            int(model.get("orientation", 0)),  # get allowed (défaut 0 = face nord)
            ez,
        )
        if offsets is None:
            return {(int(c), int(r))}
        off = offsets[0] if int(c) % 2 == 0 else offsets[1]
        return {(int(c) + dc, int(r) + dr) for dc, dr in off}

    def _legal_socle(model: Dict[str, Any], c: int, r: int) -> Optional["Socle"]:
        """Place légale = empreinte dans la zone (hors mur / hors unités déployées) ET
        à 1 hex de marge des figs déjà posées (empreinte + anneau de voisins).

        NB : la marge est propre à la GÉNÉRATION (formation aérée). La règle de validité
        (``footprints_overlap``, preview/commit) tolère le contact — non modifiée — pour
        ne pas flagger en rouge un ajustement manuel où les socles se touchent."""
        _is_round = require_key(model, "BASE_SHAPE") == "round"
        _lc_cells, _lc_index, _lc_bucket, _lc_radius = _clearance_for(model)
        fp = _model_fp(model, c, r)
        # Mur : ancre interdite au SOCLE (jumeau du pool et du commit). La boucle par cellules
        # ci-dessous ne teste donc plus les murs — elle mesurait le mur comme un point.
        if (int(c), int(r)) in wall_blocked_anchors(game_state, model):
            return None
        for cc, rr in fp:
            if cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows:
                return None
            if (cc, rr) not in pool_set:
                return None
            # Clairance par empreinte hex : NON-rond seulement (le rond passe par le disque).
            if not _is_round and (cc, rr) in _lc_cells:
                return None
            if (cc, rr) in other_occ:
                return None
        # Base ronde : clairance disque↔hexunion _low_clear (miroir move) → la spirale continue tant que
        # le DISQUE chevauche un étage trop bas, s'arrête dès qu'il est dégagé (même distance que le move).
        if _is_round and _lc_index:
            _cx, _cy = _hex_center(int(c), int(r))
            if disc_overlaps_indexed_hexes(_cx, _cy, _lc_radius, _lc_index, _lc_bucket):
                return None
        cand = Socle(
            shape=require_key(model, "BASE_SHAPE"),
            base_size=require_key(model, "BASE_SIZE"),
            col=int(c), row=int(r), fp=fp,
        )
        # Marge de 1 hex : la candidate ne doit ni chevaucher ni TOUCHER une fig déjà posée.
        # margin_blocked est tenu à jour incrémentalement (O(fp) par placement) ;
        # la vérification ici est donc O(fp) au lieu de O(N×fp×6).
        if any(cell in margin_blocked for cell in fp):
            return None
        return cand

    # Ordre spirale BORNÉ au plateau (termination garantie : chaque case in-bounds visitée une
    # seule fois, du centre vers l'extérieur). ``spiral`` mémorise cet ordre pour l'overflow.
    seen: Set[Tuple[int, int]] = {(int(center_col), int(center_row))}
    queue: "deque[Tuple[int, int]]" = deque([(int(center_col), int(center_row))])
    spiral: List[Tuple[int, int]] = []
    idx = 0
    while queue and idx < len(model_ids):
        c, r = queue.popleft()
        spiral.append((c, r))
        model = models_cache[model_ids[idx]]
        socle = _legal_socle(model, c, r)
        if socle is not None:
            placed.append((model_ids[idx], c, r))
            placed_socles.append(socle)
            for _mc, _mr in socle.fp or set():
                margin_blocked.add((_mc, _mr))
                for _nb in get_neighbors(_mc, _mr):
                    margin_blocked.add(_nb)
            idx += 1
        for nc, nr in get_neighbors(c, r):
            if 0 <= nc < board_cols and 0 <= nr < board_rows and (nc, nr) not in seen:
                seen.add((nc, nr))
                queue.append((nc, nr))
    # Overflow : la zone n'a pas pu accueillir toutes les figs (idx < len ⇒ la passe 1 a vidé la
    # file, donc ``spiral`` couvre déjà tout le plateau). Chaque fig restante est posée sur la 1re
    # case in-bounds ne chevauchant AUCUNE sœur déjà posée (zone/mur/autres unités ignorés → voile
    # rouge au preview, à repositionner). Jamais d'empilement de socles.
    for j in range(idx, len(model_ids)):
        model = models_cache[model_ids[j]]
        chosen: Optional[Tuple[int, int, "Socle"]] = None
        for c, r in spiral:
            fp = _model_fp(model, c, r)
            cand = Socle(
                shape=require_key(model, "BASE_SHAPE"),
                base_size=require_key(model, "BASE_SIZE"),
                col=int(c), row=int(r), fp=fp,
            )
            if not any(footprints_overlap(cand, ps) for ps in placed_socles):
                chosen = (int(c), int(r), cand)
                break
        if chosen is None:
            raise KeyError(
                f"generate_compact_formation: aucune case in-bounds libre pour {model_ids[j]} "
                f"(plateau saturé, squad {squad_id})"
            )
        placed.append((model_ids[j], chosen[0], chosen[1]))
        placed_socles.append(chosen[2])
    return placed


#: Intentions de placement des figurines rendues (REVIVED). L'ORDRE est contractuel : il fixe
#: l'index des candidats de la décision d'agent `returned_models_placement`.
RETURNED_PLACEMENT_INTENTS: Tuple[str, ...] = (
    "toward_enemy",
    "toward_objective",
    "away_from_enemy",
)

def _returned_placement_search_radius(
    game_state: Dict[str, Any], template: Dict[str, Any], anchor: Tuple[int, int]
) -> int:
    """Rayon de la spirale de recherche, en hexes — DÉRIVÉ de la géométrie, jamais figé.

    Une constante ne peut pas convenir : à x5 un socle couvre plusieurs subhexes, et deux socles
    voisins ne peuvent se toucher qu'à `2 × extension` l'un de l'autre. Un rayon trop court ne
    trouverait AUCUNE case légale sur les grandes bases et ferait silencieusement échouer la
    restitution. La borne est donc « deux socles côte à côte, plus la portée de cohérence ».
    """
    from engine.phase_handlers.shared_utils import get_coherency_subhex

    col, row = int(anchor[0]), int(anchor[1])
    footprint = _model_footprint(game_state, template, col, row)
    extent = max(
        (max(abs(c - col), abs(r - row)) for c, r in footprint),
        default=0,
    )
    return 2 * int(extent) + int(get_coherency_subhex(game_state)) + 1


def returned_models_legal_cells(
    game_state: Dict[str, Any], squad_id: str, template: Dict[str, Any]
) -> List[Tuple[int, int]]:
    """Ancres où une figurine RENDUE peut légalement être posée (25 Rules appendix, REVIVED).

    « Models returned to a unit on the battlefield must be set up […] in coherency with models in
    that unit that started that phase on the battlefield […] They can be engaged with one or more
    enemy units, but only if those enemy units are already engaged with the unit those models are
    being returned to. »

    Le test est PAR EMPREINTE, jamais par ancre : à x5 un socle couvre plusieurs subhexes, et le
    validateur de plan de move ne compare, lui, que les ancres (`explain_move_plan_rejection`) —
    deux socles posés sur des ancres distinctes mais dont les empreintes se recouvrent
    passeraient donc INAPERÇUS et se propageraient à chaque mouvement suivant.

    Contrairement à `generate_compact_formation`, aucune marge d'un hex entre socles : celle-là
    est propre à la GÉNÉRATION d'une formation aérée, alors qu'ici c'est la règle de validité qui
    s'applique — le contact entre socles est légal.
    """
    from collections import deque

    from engine.spatial_relations import unit_entries_within_engagement_zone
    from engine.phase_handlers.shared_utils import (
        _synth_model_entry, get_engagement_zone,
    )

    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    squad_id = str(squad_id)
    entry = require_key(units_cache, squad_id)
    player = int(require_key(entry, "player"))
    # Niveau COURANT du squad (mode des survivants) — pas le niveau archivé du template.
    # Un squad qui change d'étage après des pertes verrait `present` vide si on lisait
    # `template["level"]` (niveau de la mort), et aucune case légale ne serait retournée.
    _alive = _alive_model_ids(game_state, squad_id)
    _alive_levels = [int(require_key(models_cache[mid], "level")) for mid in _alive if mid in models_cache]
    level = _squad_mode_level(_alive_levels, int(require_key(template, "level")))

    present = [
        models_cache[mid] for mid in _alive
        if int(require_key(models_cache[mid], "level")) == level
    ]
    if not present:
        return []
    own_occupied: Set[Tuple[int, int]] = set()
    for m in present:
        own_occupied.update(_model_footprint(game_state, m, int(m["col"]), int(m["row"])))

    walls = wall_blocked_anchors(game_state, template)
    ez = get_engagement_zone(game_state)
    # « only if those enemy units are already engaged with the unit » : les ennemis DÉJÀ engagés
    # avec l'escouade ne ferment aucune case ; les autres ferment celles qui les engageraient.
    # `*_on_battlefield` et pas « toutes les entrées du cache » : une unité en réserves (20.01)
    # est vivante et présente dans `units_cache`, mais posée à la sentinelle (-1,-1). Comptée
    # comme ennemi bloquant, elle fermerait toutes les cases du coin du plateau.
    from engine.spatial_relations import enemy_entries_on_battlefield

    blocking_enemies = []
    for esid, e_entry in enemy_entries_on_battlefield(units_cache, player):
        already = any(
            unit_entries_within_engagement_zone(
                _synth_model_entry(game_state, squad_id, m, int(m["col"]), int(m["row"]), level=level),
                e_entry, ez, game_state=game_state,
            )
            for m in present
        )
        if not already:
            blocking_enemies.append(e_entry)

    from engine.hex_utils import (
        _HEX_CIRCUMRADIUS, build_hex_center_index, get_neighbors, round_base_radius_norm,
    )
    from engine.terrain_utils import low_clearance_ground_hexes

    # Clairance verticale §13.06 du gabarit rendu — construite UNE fois : le socle est le même
    # pour toutes les cases de la spirale (jumeau de `_clearance_for`, formation compacte).
    unit = get_unit_by_id(game_state, squad_id)
    if unit is None:
        raise KeyError(
            f"returned_models_legal_cells: unite {squad_id} absente de game_state['units']"
        )
    lc_shape = require_key(template, "BASE_SHAPE")
    lc_radius = (
        round_base_radius_norm(require_key(template, "BASE_SIZE"))
        if lc_shape == "round" else 0.0
    )
    lc_cells = low_clearance_ground_hexes(
        require_key(game_state, "terrain_areas"), template, unit
    )
    lc_bucket = lc_radius + _HEX_CIRCUMRADIUS
    low_clearance = (
        lc_cells,
        build_hex_center_index(lc_cells, lc_bucket) if (lc_shape == "round" and lc_cells) else {},
        lc_bucket,
        lc_radius,
    )

    # Le BFS part d'une figurine PRÉSENTE, jamais de `template` : depuis que les figurines rendues
    # sont les vraies figurines détruites (REVIVED), le template est un profil ARCHIVÉ, dont les
    # coordonnées sont la sentinelle (-1,-1) — la recherche explorait alors le coin (0,0) du
    # plateau et ne trouvait aucune case cohérente avec l'escouade. `template` ne sert plus qu'à
    # l'EMPREINTE (socle, hauteur, niveau) ; l'origine de la recherche est l'escouade, ce que dit
    # d'ailleurs la règle : « in coherency with models in that unit that started that phase on the
    # battlefield ». `present` est non vide (contrôlé plus haut) et filtré sur le bon niveau.
    anchor_col, anchor_row = int(present[0]["col"]), int(present[0]["row"])
    radius = _returned_placement_search_radius(
        game_state, template, (anchor_col, anchor_row)
    )
    legal: List[Tuple[int, int]] = []
    seen: Set[Tuple[int, int]] = {(anchor_col, anchor_row)}
    queue: "deque[Tuple[int, int, int]]" = deque([(anchor_col, anchor_row, 0)])
    while queue:
        col, row, dist = queue.popleft()
        if 0 <= col < board_cols and 0 <= row < board_rows:
            if _returned_cell_is_legal(
                game_state, squad_id, template, col, row, level,
                walls, own_occupied, blocking_enemies, ez, low_clearance,
            ):
                legal.append((col, row))
        if dist >= radius:
            continue
        for ncol, nrow in get_neighbors(col, row):
            if (ncol, nrow) in seen:
                continue
            seen.add((ncol, nrow))
            queue.append((ncol, nrow, dist + 1))
    return legal


def _returned_cell_is_legal(
    game_state: Dict[str, Any], squad_id: str, template: Dict[str, Any],
    col: int, row: int, level: int,
    walls: AbstractSet[Tuple[int, int]], own_occupied: Set[Tuple[int, int]],
    blocking_enemies: List[Dict[str, Any]], ez: int,
    low_clearance: Tuple[Set[Tuple[int, int]], Dict[Any, Any], float, float],
) -> bool:
    """Une ancre est légale pour une figurine rendue : empreinte libre, hors mur, hors EZ interdite.

    La cohérence n'est PAS testée ici : elle porte sur l'ENSEMBLE des positions retenues, donc
    elle est vérifiée par `plan_returned_models_placement` au fur et à mesure des choix.
    """
    from engine.hex_utils import Socle, _hex_center, disc_overlaps_indexed_hexes
    from engine.spatial_relations import unit_entries_within_engagement_zone
    from engine.phase_handlers.shared_utils import _synth_model_entry

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    if (int(col), int(row)) in walls:
        return False
    footprint = _model_footprint(game_state, template, int(col), int(row))
    # L'EMPREINTE doit tenir sur le plateau, pas seulement l'ancre : à x5 un socle posé près du
    # bord déborderait, et le validateur de plan de move (qui ne regarde que les ancres) ne le
    # signalerait jamais — jumeau du contrôle de `generate_compact_formation`.
    if any(
        cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows
        for cc, rr in footprint
    ):
        return False
    if any(cell in own_occupied for cell in footprint):
        return False
    # Clairance verticale §13.06 AU SOL, miroir de la formation compacte : socle rond → le DISQUE
    # ne doit chevaucher aucun hex de clairance ; socle non-rond → empreinte hex.
    lc_cells, lc_index, lc_bucket, lc_radius = low_clearance
    is_round = require_key(template, "BASE_SHAPE") == "round"
    if is_round:
        if lc_index:
            cx, cy = _hex_center(int(col), int(row))
            if disc_overlaps_indexed_hexes(cx, cy, lc_radius, lc_index, lc_bucket):
                return False
    elif any(cell in lc_cells for cell in footprint):
        return False
    candidate = Socle(
        shape=require_key(template, "BASE_SHAPE"),
        base_size=require_key(template, "BASE_SIZE"),
        col=int(col), row=int(row), fp=footprint,
    )
    if candidate_overlaps_any_unit(game_state, candidate, exclude_unit_id=str(squad_id)):
        return False
    # 13.06 : contrainte d'étage seulement à partir du niveau 1 (le sol n'en a aucune).
    if int(level) >= 1:
        unit = get_unit_by_id(game_state, str(squad_id))
        if unit is None:
            raise KeyError(f"_returned_cell_is_legal: unite {squad_id} absente de game_state['units']")
        floor_ok, _reason = validate_floor_placement(
            {
                "id": str(squad_id),
                "UNIT_KEYWORDS": require_key(unit, "UNIT_KEYWORDS"),
                "BASE_SHAPE": require_key(template, "BASE_SHAPE"),
                "BASE_SIZE": require_key(template, "BASE_SIZE"),
                "orientation": int(template.get("orientation", 0)),  # get allowed
            },
            int(col), int(row), int(level), require_key(game_state, "terrain_areas"),
        )
        if not floor_ok:
            return False
    if blocking_enemies:
        synth = _synth_model_entry(game_state, str(squad_id), template, int(col), int(row), level=level)
        for enemy in blocking_enemies:
            if unit_entries_within_engagement_zone(synth, enemy, ez, game_state=game_state):
                return False
    return True


def plan_returned_models_placement(
    game_state: Dict[str, Any], squad_id: str, template: Dict[str, Any],
    count: int, intent: str,
    precomputed_cells: Optional[List[Tuple[int, int]]] = None,
) -> List[Tuple[int, int]]:
    """Positions retenues pour `count` figurines rendues, selon l'`intent` de placement.

    Les cases légales sont ORDONNÉES par l'intention, puis retenues une à une : chaque case prise
    retire son empreinte des suivantes, et la cohérence (03.03) est vérifiée sur l'ensemble
    accumulé. Une figurine sans case légale n'est pas rendue — la règle impose un placement
    conforme, elle ne prévoit aucune pose illégale de repli.

    `precomputed_cells` : cases légales déjà calculées par `returned_models_legal_cells` — évite
    de refaire le BFS quand plusieurs intentions sont évaluées sur le même template (cf.
    `_returned_placement_plans`).
    """
    from engine.phase_handlers.shared_utils import _positions_in_coherency

    if intent not in RETURNED_PLACEMENT_INTENTS:
        raise ValueError(
            f"plan_returned_models_placement: intention {intent!r} inconnue "
            f"(attendu : {RETURNED_PLACEMENT_INTENTS})"
        )
    models_cache = require_key(game_state, "models_cache")
    cells = (
        precomputed_cells
        if precomputed_cells is not None
        else returned_models_legal_cells(game_state, squad_id, template)
    )
    if not cells:
        return []

    ordered = sorted(cells, key=_returned_placement_sort_key(game_state, squad_id, intent))

    present = [models_cache[mid] for mid in _alive_model_ids(game_state, str(squad_id))]
    taken: List[Tuple[int, int]] = []
    taken_cells: Set[Tuple[int, int]] = set()
    for col, row in ordered:
        if len(taken) >= int(count):
            break
        footprint = _model_footprint(game_state, template, col, row)
        if any(cell in taken_cells for cell in footprint):
            continue
        hypothetical = present + [
            {**template, "col": c, "row": r} for c, r in taken + [(col, row)]
        ]
        if not _positions_in_coherency(hypothetical, game_state):
            continue
        taken.append((col, row))
        taken_cells.update(footprint)
    return taken


def _returned_placement_sort_key(game_state: Dict[str, Any], squad_id: str, intent: str):
    """Clé de tri des cases légales pour une intention de placement."""
    from engine.combat_utils import calculate_hex_distance
    from engine.objective_distance import distance_to_objective, nearest_objective_zone
    from engine.spatial_relations import enemy_entries_on_battlefield

    units_cache = require_key(game_state, "units_cache")
    player = int(require_key(require_key(units_cache, str(squad_id)), "player"))
    # POSÉES seulement : une unité en réserves est à la sentinelle (-1,-1) et orienterait
    # `toward_enemy` / `away_from_enemy` vers un ennemi qui n'est pas sur la table — ce qui
    # décide aussi, en amont, si les intentions divergent assez pour poser une décision.
    enemy_positions = [
        (int(require_key(e, "col")), int(require_key(e, "row")))
        for _eid, e in enemy_entries_on_battlefield(units_cache, player)
    ]

    def _enemy_distance(col: int, row: int) -> int:
        if not enemy_positions:
            return 0
        return min(calculate_hex_distance(col, row, ec, er) for ec, er in enemy_positions)

    if intent == "toward_enemy":
        return lambda cr: (_enemy_distance(cr[0], cr[1]), cr)
    if intent == "away_from_enemy":
        return lambda cr: (-_enemy_distance(cr[0], cr[1]), cr)
    # toward_objective : l'aire la plus proche de la case, pas le centroïde (14.02).
    if not game_state["objectives"]:
        return lambda cr: cr
    return lambda cr: (
        distance_to_objective(
            game_state, nearest_objective_zone(game_state, cr[0], cr[1]), cr[0], cr[1]
        ),
        cr,
    )


def erode_pool_by_block_offsets(
    pool_set: AbstractSet[Tuple[int, int]],
    offsets: Iterable[Tuple[int, int, int]],
    *,
    allowed: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> Set[Tuple[int, int]]:
    """Ancres du pool dont TOUTES les cases ``ancre + offset`` sont acceptables. Érosion 03.02.

    C'est LA question de toute mise en place : « l'objet, translaté ici, tient-il entièrement dans
    ce qui est permis ? » — posée pour l'empreinte d'UNE figurine comme pour l'empreinte combinée
    d'un BLOC. Un seul code y répond, sinon les deux réponses divergent le jour où l'une des deux
    est corrigée.

    ``allowed`` : ensemble des cases acceptables pour les cases translatées, quand il diffère du
    pool des ancres (empreinte d'une figurine : les ancres candidates sont dans la zone, mais les
    cases acceptables en excluent en plus les murs et les positions occupées). Par défaut, le pool
    lui-même — cas du suivi de bloc.

    POURQUOI VECTORISÉ : écrit en deux boucles Python imbriquées, ce test coûte |pool| × |offsets|
    appartenances. Mesuré sur ce dépôt : 0,43 s sur une zone de déploiement (16 104 cases) mais
    2,3 s sur l'aire d'arrivée d'une unité Deep Strike (59 050 cases, 20.04) — à chaque clic.
    Une translation en coordonnées CUBE est une translation constante en (x, z) (l'axe y est
    redondant, x + y + z = 0), donc l'ensemble acceptable devient une grille booléenne et chaque
    offset un simple DÉCALAGE de cette grille : l'érosion est le ET logique des décalages.
    Le résultat est IDENTIQUE au test case-par-case — c'est la même condition, écrite en une fois
    (verrouillé par les tests d'oracle naïf de `test_strategic_reserves_20.py`).

    Un seul ``allowed`` : passe-plat vers `erode_pool_by_block_offsets_multi`, qui porte le calcul.
    Les appelants qui érodent le MÊME pool avec plusieurs ensembles acceptables (le pool de mise en
    place, un par niveau) doivent appeler la variante multi directement — voir son en-tête.
    """
    return erode_pool_by_block_offsets_multi(pool_set, offsets, (allowed,))[0]


def erode_pool_by_block_offsets_multi(
    pool_set: AbstractSet[Tuple[int, int]],
    offsets: Iterable[Tuple[int, int, int]],
    allowed_sets: Sequence[Optional[AbstractSet[Tuple[int, int]]]],
) -> List[Set[Tuple[int, int]]]:
    """Érosion 03.02 du MÊME pool par PLUSIEURS ensembles de cases acceptables, en une passe.

    POURQUOI CETTE VARIANTE EXISTE. Le pool de mise en place érode le même pool une fois par
    NIVEAU (sol, étage) : mêmes ancres, mêmes offsets, seul l'ensemble acceptable change. Or deux
    blocs du calcul ne dépendent QUE du pool et des offsets — les bornes des ancres et le
    remappage de sortie, soit deux parcours complets de ~60 000 ancres avec conversion en cube.
    Les refaire par niveau coûtait 59,8 ms par appel à `level >= 1`, ~22 % du temps de
    `deployment_build_model_destinations_pool`.

    Rend une liste PARALLÈLE à ``allowed_sets`` : ``resultat[i]`` est l'érosion par
    ``allowed_sets[i]``. Un ``None`` y vaut « le pool lui-même » (cas du suivi de bloc), exactement
    comme le paramètre ``allowed`` de la fonction à un seul ensemble.
    """
    import numpy as np

    from engine.hex_utils import offset_to_cube

    if not pool_set:
        return [set() for _ in allowed_sets]
    offsets = list(offsets)

    # Les cas dégénérés se tranchent PAR ENSEMBLE, dans l'ordre de la version à un seul argument :
    # un ensemble acceptable vide rend l'ensemble vide, même quand il n'y a aucun offset.
    resolved: List[AbstractSet[Tuple[int, int]]] = []
    results: List[Optional[Set[Tuple[int, int]]]] = []
    for entry in allowed_sets:
        allowed_set = pool_set if entry is None else entry
        resolved.append(allowed_set)
        results.append(set() if not allowed_set else None)

    if not offsets:
        # Aucun offset : toute ancre convient, quel que soit l'ensemble acceptable non vide.
        whole_pool = {(int(c), int(r)) for c, r in pool_set}
        return [set(whole_pool) if res is None else res for res in results]

    if all(res is not None for res in results):
        # TOUS les ensembles acceptables sont vides : plus rien à éroder. La version à un seul
        # argument sortait ici, AVANT de toucher au pool ; sans cette garde, la passe de bornes
        # ci-dessous parcourrait les ~66 000 ancres pour rien. Rare (il faut que la zone entière
        # soit bloquée) mais gratuit à éviter, et ça garde les deux versions équivalentes jusque
        # dans leurs sorties anticipées.
        return [res for res in results if res is not None]

    # ---- Travail qui ne dépend QUE du pool et des offsets : fait UNE fois ---------------------
    # Bornes des ancres en UNE passe. La liste intermédiaire des ~60 000 couples n'avait aucun
    # autre lecteur que quatre extrema, et quatre `min`/`max` la reparcouraient (27,9 ms contre
    # 6,7 ms). `pool_set` est non vide (garde ci-dessus) : la 1re ancre amorce les quatre bornes.
    #
    # L'index de grille de chaque ancre n'est MÉMORISÉ QUE s'il servira plus d'une fois. Le
    # matérialiser systématiquement coûtait 45 ms de plus sur le cas à UN SEUL ensemble — le plus
    # fréquent, le déploiement au sol — pour n'en économiser que 15 sur le cas à deux. MESURÉ,
    # après avoir cru l'inverse : une liste de 66 000 tuples n'est pas gratuite face à une boucle
    # qui streame.
    reuse_anchors = sum(1 for res in results if res is None) > 1
    anchors: List[Tuple[Tuple[int, int], int, int]] = []
    _pool_iter = iter(pool_set)
    _c0, _r0 = next(_pool_iter)
    _x0, _y0, _z0 = offset_to_cube(int(_c0), int(_r0))
    ax_min = ax_max = _x0
    az_min = az_max = _z0
    if reuse_anchors:
        anchors.append(((int(_c0), int(_r0)), _x0, _z0))
    for c, r in _pool_iter:
        x, _y, z = offset_to_cube(int(c), int(r))
        if reuse_anchors:
            anchors.append(((int(c), int(r)), x, z))
        # `elif` légitime : `ax_min <= ax_max`, donc une ancre sous le min ne peut pas dépasser
        # le max. Même raisonnement sur z.
        if x < ax_min:
            ax_min = x
        elif x > ax_max:
            ax_max = x
        if z < az_min:
            az_min = z
        elif z > az_max:
            az_max = z
    # La grille couvre TOUTES les cases lisibles : l'ancre la plus extrême translatée par l'offset
    # le plus extrême. Elle n'est PAS bornée à la boîte de `allowed` — une ancre en dehors de
    # celle-ci reste une ancre valide dès lors que l'objet, lui, retombe dans `allowed` (offsets
    # qui ne contiennent pas l'origine). Une case non marquée y vaut « non acceptable », ce qui
    # est la bonne réponse, tandis qu'écarter ces ancres d'avance en perdait.
    ox_min = min(ox for ox, _oy, _oz in offsets)
    ox_max = max(ox for ox, _oy, _oz in offsets)
    oz_min = min(oz for _ox, _oy, oz in offsets)
    oz_max = max(oz for _ox, _oy, oz in offsets)
    gx_min, gx_max = ax_min + ox_min, ax_max + ox_max
    gz_min, gz_max = az_min + oz_min, az_max + oz_max
    core_w = ax_max - ax_min + 1
    core_h = az_max - az_min + 1
    unique_offsets = set(offsets)

    # ---- Travail propre à CHAQUE ensemble acceptable ------------------------------------------
    for index, allowed_set in enumerate(resolved):
        if results[index] is not None:
            continue
        grid = np.zeros((gx_max - gx_min + 1, gz_max - gz_min + 1), dtype=bool)
        marked_x = []
        marked_z = []
        for c, r in allowed_set:
            x, _y, z = offset_to_cube(int(c), int(r))
            if gx_min <= x <= gx_max and gz_min <= z <= gz_max:
                marked_x.append(x - gx_min)
                marked_z.append(z - gz_min)
        if not marked_x:
            results[index] = set()
            continue
        grid[np.fromiter(marked_x, dtype=np.int64), np.fromiter(marked_z, dtype=np.int64)] = True

        keep = np.ones((core_w, core_h), dtype=bool)
        emptied = False
        for ox, _oy, oz in unique_offsets:
            sx = ax_min + ox - gx_min
            sz = az_min + oz - gz_min
            keep &= grid[sx : sx + core_w, sz : sz + core_h]
            if not keep.any():
                emptied = True
                break
        if emptied:
            results[index] = set()
            continue

        out: Set[Tuple[int, int]] = set()
        if anchors:
            for cell, x, z in anchors:
                if keep[x - ax_min, z - az_min]:
                    out.add(cell)
        else:
            for cc, rr in pool_set:
                x, _y, z = offset_to_cube(int(cc), int(rr))
                if keep[x - ax_min, z - az_min]:
                    out.add((int(cc), int(rr)))
        results[index] = out

    return [res if res is not None else set() for res in results]


def deployment_build_model_destinations_pool(
    game_state: Dict[str, Any],
    model_id: str,
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    level: int = 0,
) -> Dict[str, Any]:
    """Pool des ancres VALIDES pour UNE figurine en déploiement (miroir per-fig du move,
    sans BFS/portée : toute la zone est candidate).

    Une ancre est retenue si l'empreinte de la figurine y tient : dans la zone, hors plateau
    exclu, hors mur, hors empreinte des AUTRES unités déployées (amies/ennemies) et des AUTRES
    figurines de l'escouade (positions provisoires via ``provisional_plan``). La cohésion n'est
    PAS filtrée (comme le move) → poser hors-cohésion reste possible (voile rouge au preview).

    ``level`` (étages) = niveau de VUE courant (hint, même sémantique que le preview). Le niveau
    EFFECTIF de chaque candidate est dérivé par position (empreinte entière sur le plancher du
    niveau vue → étage, sinon sol) et seule l'occupation DE CE NIVEAU bloque — une fig à l'étage
    ne bloque plus une destination au sol sous elle (et réciproquement). Murs = verticaux
    prolongés, bloquent à tous les niveaux.

    Retourne {"destinations": [[col, row], ...]}. Lecture pure.
    """
    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))  # get allowed
    if model is None:
        raise KeyError(
            f"deployment_build_model_destinations_pool: model {model_id} not in models_cache"
        )
    squad_id = str(require_key(model, "squad_id"))
    player = int(require_key(model, "player"))
    pool_set = _deploy_pool_set(game_state, player, placement_pool_for_squad(game_state, squad_id))
    level = int(level or 0)
    terrain_areas = require_key(game_state, "terrain_areas")
    from engine.terrain_utils import (
        floor_hexes_at_level, floor_polys_at_level, footprint_within_floor,
        low_clearance_ground_hexes,
    )
    floor_hexes: AbstractSet[Tuple[int, int]] = (
        floor_hexes_at_level(terrain_areas, level) if level >= 1 else set()
    )
    # Base + polygones du plancher pour le niveau effectif EUCLIDIEN par case (miroir move /
    # preview / commit = resolve_model_floor_level). Base ronde → disque↔polygone ; autre → hex.
    _m_shape = require_key(model, "BASE_SHAPE")
    _m_base = require_key(model, "BASE_SIZE")
    _m_orient = int(model.get("orientation", 0))  # get allowed
    floor_polys = (
        floor_polys_at_level(terrain_areas, level)
        if level >= 1 and _m_shape == "round" else None
    )
    # Clairance verticale (§13.06, miroir move) : hexes de SOL infranchissables par ce modèle (trop haut
    # pour tenir sous un étage bas). Bloque uniquement le niveau 0 (une fig posée EN SURFACE de l'étage
    # n'est pas concernée). MODEL_HEIGHT est requis au chargement des unités → toujours présent.
    unit = get_unit_by_id(game_state, squad_id)
    if not unit:
        raise KeyError(f"deployment_build_model_destinations_pool: unit {squad_id} missing from game_state['units']")
    # Clairance de LA FIGURINE (`_model_height_of`) : ce pool est par-figurine de bout en bout
    # (socle, facing, niveau), la hauteur ne pouvait pas rester celle de l'escouade.
    _low_clear = low_clearance_ground_hexes(terrain_areas, model, unit)
    # Clairance verticale — MIROIR EXACT du move. Le move n'ajoute PAS _low_clear au filtre d'empreinte :
    # il met _low_clear dans les obstacles du champ géodésique avec clearance = RAYON du socle (round).
    # Le socle rond « heurte » un hex _low_clear ssi son DISQUE le chevauche (clairance capsule
    # stationnaire) — jamais l'empreinte hex (qui sur-couvre et poussait le deploy plus loin que le move).
    # Base ronde → test disque↔hexunion _low_clear ; oval/carré → empreinte hex (comme le move non-rond).
    from engine.hex_utils import (
        _hex_center, _HEX_CIRCUMRADIUS, build_hex_center_index, disc_overlaps_indexed_hexes,
        round_base_radius_norm,
    )
    _m_round = _m_shape == "round"
    _m_radius = round_base_radius_norm(_m_base) if _m_round else 0.0
    # Index spatial des hexes _low_clear (construit UNE fois) : clairance disque O(1) par case.
    _lc_bucket = _m_radius + _HEX_CIRCUMRADIUS
    _lc_index = build_hex_center_index(_low_clear, _lc_bucket) if (_m_round and _low_clear) else {}
    # Gate mot-clé §13.06 (miroir move, correction multi-niveaux) : une unité qui ne peut PAS finir en
    # hauteur (ni INFANTRY/BEASTS/SWARM/FLY/MONSTER) n'obtient jamais une candidate taguée étage — sinon
    # une grosse fig (ex. VEHICLE trop haute) serait posée en débordant sur l'empreinte de l'étage, ou au
    # sol sous le bord (eff=level contourne _low_clear, ajouté au seul niveau 0). Non-montante → eff force 0.
    from engine.game_state import unit_can_occupy_upper_floor
    _can_climb = unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS"))
    # LES NIVEAUX où une candidate peut être taguée. Une seule expression les définit, et tout ce
    # qui suit s'y adosse : occupation, cases acceptables, érosion, résolution par candidate. Poser
    # la question à chaque consommateur laisse toujours l'un d'eux derrière (le producteur
    # d'occupation l'était encore), et fait vivre la même condition à quatre endroits.
    _upper_reachable = level >= 1 and _can_climb and bool(floor_hexes)
    _levels = (0, level) if _upper_reachable else (0,)

    # Positions provisoires + niveau EFFECTIF des AUTRES figs de l'escouade (collision intra-squad,
    # même dérivation par position que le preview). provisional_plan override les positions des
    # figs déjà repositionnées dans le plan UI.
    squad_models = game_state.get("squad_models", {})  # get allowed
    sibling_states: List[Tuple[Dict[str, Any], int, int, int]] = []  # (model, col, row, eff_level)
    for mid in squad_models.get(squad_id, []):  # get allowed
        if str(mid) == str(model_id):
            continue
        sibling = models_cache.get(str(mid))  # get allowed
        if sibling is None:
            continue
        # Niveau DEMANDÉ propre à CHAQUE sœur : niveau capturé dans le plan provisoire (3e élément)
        # si présent, sinon son niveau committé (models_cache). SURTOUT PAS le niveau de vue de la fig
        # déplacée — sinon une sœur à l'étage était re-dérivée au sol et bloquait à tort (bug collision
        # inter-étage). L'effectif reste validé par l'empreinte sur le plancher (13.06).
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            sc, sr = int(_pv[0]), int(_pv[1])
            sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sibling.get("level", 0))  # get allowed
        else:
            sc, sr = int(sibling["col"]), int(sibling["row"])
            sib_req = int(sibling.get("level", 0))  # get allowed
        sib_eff = resolve_model_effective_level(game_state, sibling, sc, sr, sib_req)
        sibling_states.append((sibling, sc, sr, sib_eff))
    same_squad_by_level: Dict[int, Set[Tuple[int, int]]] = {}
    for sibling, sc, sr, sib_eff in sibling_states:
        same_squad_by_level.setdefault(sib_eff, set()).update(
            _model_footprint(game_state, sibling, sc, sr)
        )

    from engine.hex_utils import offset_to_cube
    if not pool_set:
        return {"destinations": []}
    # Empreinte de la fig en offsets CUBE, calculée UNE fois à une réf (invariante par translation
    # rigide). Évite |zone| appels à _model_footprint (géométrie lourde). pool/blocked en cube →
    # test d'appartenance direct, sans cube_to_offset dans la boucle. Board bounds redondant (zone ⊆ board).
    ref_c, ref_r = next(iter(pool_set))
    rcx, rcy, rcz = offset_to_cube(int(ref_c), int(ref_r))
    fp_offsets: List[Tuple[int, int, int]] = []
    for (fc, fr) in _model_footprint(game_state, model, int(ref_c), int(ref_r)):
        fx, fy, fz = offset_to_cube(int(fc), int(fr))
        fp_offsets.append((fx - rcx, fy - rcy, fz - rcz))
    # Filtrage par ÉROSION (même primitive que le suivi de bloc) au lieu d'un `any` par case :
    # « l'empreinte translatée tient-elle entièrement dans les cases acceptables ? ». Les cases
    # acceptables sont la zone MOINS les murs et les positions occupées — et elles dépendent du
    # niveau EFFECTIF de la candidate, d'où une érosion par niveau ATTEIGNABLE (cf. `_levels`).
    # Mesuré sur l'aire d'arrivée Deep Strike : 1,6 s de `any` par case avant ce filtrage.
    # Les coordonnées du pool sont déjà normalisées `(int, int)` par `_deploy_pool_set` : la
    # soustraction d'ensembles fait donc le même travail que la comprehension qui les recastait.
    #
    # Les murs sont retirés UNE FOIS, hors de la boucle : ils ne dépendent pas du niveau, alors que
    # l'occupation et les sœurs en dépendent. Les refaire par niveau réallouait un ensemble de
    # ~60 000 tuples pour rien — mesuré 12,7 ms par appel à `level >= 1`. Associativité de la
    # différence : `(pool − occ − sœurs − lc) − murs == (pool − murs) − occ − sœurs − lc`.
    # L'occupation déployée est lue ICI, à son unique consommateur, et non pré-calculée dans un
    # dict par niveau : c'est ce producteur-là qui s'était désynchronisé des niveaux réellement
    # atteignables. Il ne peut plus, il itère `_levels`.
    # Murs : ancres où le SOCLE chevauche un mur (géométrie d'hexagone, jumeau exact du move).
    # `pool_set - wall_hexes` mesurait le mur comme un point, si bien que le déploiement offrait
    # des cases d'où la figurine ne pouvait plus faire un seul pas (664 sur `terrain-mc1`).
    pool_free = pool_set - wall_blocked_anchors(game_state, model)
    allowed_by_level: List[Optional[AbstractSet[Tuple[int, int]]]] = []
    for lv in _levels:
        # Occupation des unités déployées AU NIVEAU EFFECTIF de la candidate — plus d'union
        # tous-niveaux (bug : une fig à l'étage bloquait le sol dessous).
        allowed = pool_free - _deployed_occupied_positions(game_state, squad_id, level=lv)
        allowed -= same_squad_by_level.get(lv, set())
        if lv == 0 and _low_clear and not _m_round:
            allowed -= _low_clear
        allowed_by_level.append(allowed)
    # UNE seule érosion pour les deux niveaux : mêmes ancres, mêmes offsets, seul l'ensemble
    # acceptable change. Deux appels séparés refaisaient les bornes d'ancres et le remappage de
    # sortie — deux parcours complets du pool, 59,8 ms par appel à `level >= 1`.
    kept_by_level: Dict[int, Set[Tuple[int, int]]] = dict(
        zip(_levels, erode_pool_by_block_offsets_multi(pool_set, fp_offsets, allowed_by_level))
    )
    # Le niveau effectif d'une candidate n'est PAS connu d'avance : il vaut le niveau de vue si
    # l'empreinte tient entièrement sur le plancher (§13.06 euclidien), sinon le sol.
    #
    # « L'empreinte touche-t-elle le plancher ? » se répondait en translatant l'empreinte sous
    # CHAQUE case du pool — 19 tuples par case pour 59 050 cases, alors que 2 582 ancres (4,4 %)
    # touchent réellement. On DILATE donc le plancher une fois par la forme de l'empreinte : la
    # question devient une appartenance. Même ensemble d'ancres touchantes, mesuré 0,448 s → 0,032 s.
    touching_floor: Set[Tuple[int, int]] = set()
    if _upper_reachable:
        from engine.hex_utils import cube_to_offset

        touching_floor = {
            cube_to_offset(fx - ox, fy - oy, fz - oz)
            for (fx, fy, fz) in (offset_to_cube(int(c), int(r)) for c, r in floor_hexes)
            for (ox, oy, oz) in fp_offsets
        }
    destinations: List[Tuple[int, int]] = []
    eff_by_dest: Dict[Tuple[int, int], int] = {}
    ground_kept = kept_by_level[0]
    upper_kept = kept_by_level[level] if _upper_reachable else set()
    for cell in pool_set:
        eff = 0
        if cell in touching_floor and footprint_within_floor(
            cell[0], cell[1], _m_shape, _m_base, _m_orient, floor_hexes, floor_polys
        ):
            eff = level
        if cell not in (upper_kept if eff else ground_kept):
            continue
        # Clairance verticale base RONDE au SOL — MIROIR EXACT du move : le disque du socle ne doit
        # chevaucher aucun hex _low_clear (clairance capsule stationnaire, obstacle = hexunion des étages
        # trop bas, rayon = socle). Identique au champ géodésique du move → deploy et move au même endroit.
        if eff == 0 and _lc_index:
            _dcx, _dcy = _hex_center(cell[0], cell[1])
            if disc_overlaps_indexed_hexes(_dcx, _dcy, _m_radius, _lc_index, _lc_bucket):
                continue
        destinations.append(cell)
        eff_by_dest[cell] = eff

    # Miroir EXACT du move (movement_build_model_destinations_pool) : le blocage par cases hex
    # ci-dessus sous-estime le disque (~16% de recouvrement à 5 sous-hex passe entre les cases).
    # On retire du pool les ancres où le socle de la fig chevaucherait une sœur AU MÊME NIVEAU
    # effectif en clearance euclidien (base RÉELLE, footprints_overlap) → pool et voile rouge
    # cohérents. Tangence tolérée. Sœurs d'un autre étage : pas de gêne.
    from engine.hex_utils import Socle, footprints_overlap

    # BORNE DE PORTÉE, exacte : deux socles ne peuvent se chevaucher que si la distance entre leurs
    # centres est inférieure à la somme de leurs EXTENSIONS (rayon pour un socle rond ; pour une
    # empreinte hex, la case la plus éloignée du centre plus le circumrayon d'un hex, puisqu'un
    # chevauchement exige de partager une case ou de mordre un hex). Au-delà, la réponse est non
    # sans calcul. Ce n'est donc PAS une approximation : le test euclidien reste seul juge à
    # l'intérieur de la borne, il n'est simplement plus appelé là où il ne peut que répondre non.
    # Mesuré : 256 374 appels sur une aire d'arrivée Deep Strike.
    def _extent(shape: str, base_size: Any, col: int, row: int, fp: Any) -> float:
        if shape == "round":
            return round_base_radius_norm(base_size)
        cx, cy = _hex_center(int(col), int(row))
        reach = 0.0
        for (fc, fr) in (fp or ()):
            hx, hy = _hex_center(int(fc), int(fr))
            reach = max(reach, math.hypot(hx - cx, hy - cy))
        return reach + _HEX_CIRCUMRADIUS

    # L'extension est calculée ICI, où la FORME et la TAILLE de la sœur sont sous la main : les
    # relire sur le `Socle` construit demanderait de connaître sa sous-classe concrète (la classe
    # abstraite ne déclare pas `base_size`).
    sibling_reach_by_level: Dict[int, List[Tuple["Socle", float, float, float]]] = {}
    for sibling, sc, sr, sib_eff in sibling_states:
        s_shape = require_key(sibling, "BASE_SHAPE")
        s_base = require_key(sibling, "BASE_SIZE")
        s_fp = None if s_shape == "round" else _model_footprint(game_state, sibling, sc, sr)
        s_cx, s_cy = _hex_center(int(sc), int(sr))
        sibling_reach_by_level.setdefault(sib_eff, []).append(
            (
                Socle(shape=s_shape, base_size=s_base, col=sc, row=sr, fp=s_fp),
                s_cx,
                s_cy,
                _extent(s_shape, s_base, sc, sr, s_fp),
            )
        )
    if sibling_reach_by_level:
        m_reach_round = round_base_radius_norm(_m_base) if _m_round else None

        filtered: List[Tuple[int, int]] = []
        for (dc, dr) in destinations:
            near = sibling_reach_by_level.get(eff_by_dest[(dc, dr)], [])
            if not near:
                filtered.append((dc, dr))
                continue
            mx, my = _hex_center(int(dc), int(dr))
            m_fp = None
            m_reach = m_reach_round
            candidates = []
            for sc_socle, sx, sy, s_reach in near:
                if m_reach is None:
                    # Socle non rond : son extension dépend de son empreinte, qu'il faut calculer.
                    m_fp = compute_candidate_footprint(
                        dc, dr,
                        {"BASE_SHAPE": _m_shape, "BASE_SIZE": _m_base, "orientation": _m_orient},
                        game_state,
                    )
                    m_reach = _extent(_m_shape, _m_base, dc, dr, m_fp)
                if math.hypot(sx - mx, sy - my) <= m_reach + s_reach:
                    candidates.append(sc_socle)
            if not candidates:
                filtered.append((dc, dr))
                continue
            m_socle = Socle(shape=_m_shape, base_size=_m_base, col=dc, row=dr, fp=m_fp)
            if not any(footprints_overlap(m_socle, s) for s in candidates):
                filtered.append((dc, dr))
        destinations = filtered
    # Destinations avec niveau EFFECTIF par case (miroir move_model_destinations : [col,row,level]) →
    # le front pose la fig au niveau réel de la case, plus au niveau de vue aveugle.
    return {"destinations": [(dc, dr, eff_by_dest[(dc, dr)]) for (dc, dr) in destinations]}


def deployment_build_squad_destinations_pool(
    game_state: Dict[str, Any],
    plan: List[Tuple[str, int, int]],
) -> Dict[str, Any]:
    """Pool des positions de l'ANCRE (1re fig du plan) où le BLOC, translaté RIGIDEMENT, garde
    TOUTES ses empreintes dans la zone de déploiement (suivi squad : snap de l'ancre comme le move,
    étendu aux empreintes — aucune ne sort de la zone).

    ``plan`` : [(model_id, col, row), ...] positions provisoires de toutes les figs. La translation
    rigide passe par les coords cube (pas de bug de parité). Empreinte combinée calculée UNE fois
    en offsets relatifs à l'ancre, puis testée par candidate. Lecture pure.

    Retourne {"destinations": [[col, row], ...]}.
    """
    from engine.hex_utils import offset_to_cube

    if not plan:
        return {"destinations": []}
    models_cache = require_key(game_state, "models_cache")
    ref_mid, ref_col, ref_row = plan[0]
    ref_model = models_cache.get(str(ref_mid))  # get allowed
    if ref_model is None:
        raise KeyError(
            f"deployment_build_squad_destinations_pool: model {ref_mid} not in models_cache"
        )
    player = int(require_key(ref_model, "player"))
    pool_set = _deploy_pool_set(
        game_state, player,
        placement_pool_for_squad(game_state, str(require_key(ref_model, "squad_id"))),
    )

    # Empreinte combinée (absolue) du bloc aux positions provisoires.
    combined: Set[Tuple[int, int]] = set()
    for mid, c, r in plan:
        m = models_cache.get(str(mid))  # get allowed
        if m is None:
            raise KeyError(
                f"deployment_build_squad_destinations_pool: model {mid} not in models_cache"
            )
        combined.update(_model_footprint(game_state, m, int(c), int(r)))

    # Offsets cube relatifs à l'ancre-réf : invariants par translation rigide du bloc.
    rx, ry, rz = offset_to_cube(int(ref_col), int(ref_row))
    offsets: List[Tuple[int, int, int]] = []
    for (cc, rr) in combined:
        x, y, z = offset_to_cube(int(cc), int(rr))
        offsets.append((x - rx, y - ry, z - rz))

    # Murs : mêmes critères que pour le pool par-figurine (ligne ~810).
    # L'ancre de référence définit la géométrie du bloc ; wall_blocked_anchors filtre les
    # positions où le socle de ref_model chevauche un mur.
    pool_free = pool_set - wall_blocked_anchors(game_state, ref_model)
    # Le bloc entier translaté doit rester dans pool_free : érosion 03.02, même code que
    # pour l'empreinte d'une figurine.
    kept = erode_pool_by_block_offsets(pool_free, offsets)
    return {"destinations": [(int(c), int(r)) for (c, r) in kept]}


def _normalize_plan_entry(e: Tuple[Any, ...]) -> Tuple[str, int, int, int]:
    """Normalise une entrée de plan en ``(mid, col, row, level)`` (level défaut 0).

    Accepte les 3-uplets (sol) émis par la génération de formation et les 4-uplets
    (étages) de ``_parse_plan``.
    """
    if len(e) == 3:
        return (str(e[0]), int(e[1]), int(e[2]), 0)
    if len(e) == 4:
        return (str(e[0]), int(e[1]), int(e[2]), int(e[3]))
    raise ValueError(f"deployment plan entry must be (mid, col, row[, level]), got {e!r}")


def deployment_preview_plan(
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[Any, ...]],
    pool_override: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> Dict[str, Any]:
    """Dry-run d'un plan de déploiement par-figurine. Aucune écriture.

    Voile rouge d'une figurine = empreinte hors zone / hors plateau / sur mur /
    chevauchant une unité déjà déployée ou une coéquipière AU MÊME NIVEAU, hors
    cohésion, OU pose d'étage illégale (règle 13.06).

    Niveaux (étages) : l'horizontal (zone/bornes) et les murs (verticaux, prolongés)
    restent 2D et s'appliquent à tous les niveaux ; seules les collisions entre figs
    (`on_other`/`intra`) sont filtrées par niveau ; la pose à un niveau >= 1 exige en
    plus ``validate_floor_placement`` (mot-clé + empreinte 100% sur l'étage).
    """
    from engine.hex_utils import Socle, footprints_overlap

    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    entry = require_key(units_cache, str(squad_id))
    player = int(require_key(entry, "player"))
    pool_set = _deploy_pool_set(game_state, player, pool_override)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    terrain_areas = require_key(game_state, "terrain_areas")
    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        raise KeyError(f"deployment_preview_plan: unit {squad_id} missing from game_state['units']")
    unit_keywords = require_key(unit, "UNIT_KEYWORDS")
    # Clairance verticale (§13.06, miroir move) : au SOL, une fig trop haute ne peut tenir sous un étage
    # trop bas → voile rouge. Ne concerne que le niveau 0 (la pose EN SURFACE d'un étage passe par
    # validate_floor_placement). MODEL_HEIGHT requis au chargement → toujours présent.
    from engine.terrain_utils import low_clearance_ground_hexes
    # Clairance verticale — miroir du pool per-fig / du move. Base ronde : le DISQUE ne doit chevaucher
    # aucun hex de clairance (capsule, index spatial). Base non-ronde : empreinte hex ∩ clairance.
    from engine.hex_utils import (
        _hex_center, _HEX_CIRCUMRADIUS, build_hex_center_index, disc_overlaps_indexed_hexes,
        round_base_radius_norm,
    )
    # Gabarit (hauteur ET socle) pris sur la FIGURINE, pas sur l'escouade : le voile rouge de cette
    # fonction juge chaque figurine du plan, et le reste de son verdict (empreinte, plancher) la lit
    # déjà par figurine. Mémoïsé par (hauteur, rayon) — escouade homogène = un seul index.
    _pv_lc_by_gabarit: Dict[Tuple[float, float], Tuple[Set[Tuple[int, int]], Dict[Any, Any], float, float]] = {}

    def _pv_clearance_for(model: Dict[str, Any]) -> Tuple[Set[Tuple[int, int]], Dict[Any, Any], float, float]:
        _h = _model_height_of(model, unit)
        _shape = require_key(model, "BASE_SHAPE")
        _radius = round_base_radius_norm(require_key(model, "BASE_SIZE")) if _shape == "round" else 0.0
        cached = _pv_lc_by_gabarit.get((_h, _radius))
        if cached is None:
            _cells = low_clearance_ground_hexes(terrain_areas, model, unit)
            _bucket = _radius + _HEX_CIRCUMRADIUS
            _index = build_hex_center_index(_cells, _bucket) if (_shape == "round" and _cells) else {}
            cached = (_cells, _index, _bucket, _radius)
            _pv_lc_by_gabarit[(_h, _radius)] = cached
        return cached

    # Niveau EFFECTIF par figurine = niveau demandé (vue) SI l'empreinte tient sur ce plancher, sinon
    # sol (0). Permet une escouade MIXTE (figs sur l'étage + figs au sol) déployée depuis la vue étage :
    # les figs hors empreinte redeviennent 'sol' au lieu d'être rejetées (voile rouge) à tort.
    norm: List[Tuple[str, int, int, int]] = []
    for _mid, _nc, _nr, _req in (_normalize_plan_entry(e) for e in plan):
        _m = require_key(models_cache, str(_mid))
        _eff = resolve_model_effective_level(game_state, _m, _nc, _nr, _req)
        norm.append((_mid, _nc, _nr, _eff))
    n = len(norm)
    levels = [lv for _, _, _, lv in norm]
    # Occupation des figs déjà déployées, par niveau présent dans le plan (calcul unique/niveau).
    other_occ_by_level: Dict[int, Set[Tuple[int, int]]] = {
        lv: _deployed_occupied_positions(game_state, str(squad_id), level=lv) for lv in set(levels)
    }

    footprints: List[Set[Tuple[int, int]]] = []
    socles: List["Socle"] = []
    for mid, nc, nr, _lv in norm:
        m = require_key(models_cache, str(mid))
        fp = _model_footprint(game_state, m, int(nc), int(nr))
        footprints.append(fp)
        socles.append(
            Socle(
                shape=require_key(m, "BASE_SHAPE"),
                base_size=require_key(m, "BASE_SIZE"),
                col=int(nc), row=int(nr), fp=fp,
            )
        )

    cohesion_models = [
        {**require_key(models_cache, str(mid)), "col": int(nc), "row": int(nr)}
        for mid, nc, nr, _lv in norm
    ]
    cohesion_red = coherency_violation_flags(cohesion_models, game_state)

    per_model: Dict[str, bool] = {}
    for idx, (mid, nc, nr, lv) in enumerate(norm):
        m = require_key(models_cache, str(mid))
        fp = footprints[idx]
        out_of_bounds = any(
            cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows for cc, rr in fp
        )
        out_of_zone = any((cc, rr) not in pool_set for cc, rr in fp)
        on_wall = (nc, nr) in wall_blocked_anchors(
            game_state, require_key(models_cache, str(mid))
        )
        on_other = bool(other_occ_by_level[lv] and fp & other_occ_by_level[lv])
        # Collision intra-escouade uniquement entre figs du plan AU MÊME NIVEAU.
        intra = any(
            footprints_overlap(socles[idx], socles[j])
            for j in range(n) if j != idx and levels[j] == lv
        )
        # Pose sur étage (niveau >= 1) : règle 13.06 (mot-clé + empreinte entièrement sur l'étage).
        floor_bad = False
        if lv >= 1:
            floor_ok, _reason = validate_floor_placement(
                {
                    "id": squad_id,
                    "UNIT_KEYWORDS": unit_keywords,
                    "BASE_SHAPE": require_key(m, "BASE_SHAPE"),
                    "BASE_SIZE": require_key(m, "BASE_SIZE"),
                    "orientation": int(m.get("orientation", 0)),  # get allowed
                },
                int(nc), int(nr), lv, terrain_areas,
            )
            floor_bad = not floor_ok
        # Niveau 0 : fig trop haute sous un étage trop bas (§13.06, clairance verticale) → invalide.
        # Base ronde : DISQUE↔hexunion _low_clear (miroir move, index). Non-ronde : empreinte hex.
        _lc_cells, _lc_index, _lc_bucket, _lc_radius = _pv_clearance_for(m)
        if lv == 0 and _lc_index:
            _cx, _cy = _hex_center(int(nc), int(nr))
            low_clear_bad = disc_overlaps_indexed_hexes(_cx, _cy, _lc_radius, _lc_index, _lc_bucket)
        else:
            low_clear_bad = lv == 0 and bool(_lc_cells) and bool(fp & _lc_cells)
        per_model[str(mid)] = bool(
            not out_of_bounds and not out_of_zone and not on_wall
            and not on_other and not intra and not cohesion_red[idx] and not floor_bad
            and not low_clear_bad
        )
    coherency_ok = not any(cohesion_red)
    all_valid = n > 0 and all(per_model.values())
    # Niveau EFFECTIF par figurine (§13.06, euclidien) : le front l'applique au plan pour que chaque
    # fig affiche son vrai niveau — une fig dont l'empreinte déborde du plancher redevient sol (0),
    # même si la vue (drop de bloc) l'avait posée au niveau de l'étage.
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
        "effective_levels": {str(mid): int(lv) for mid, _nc, _nr, lv in norm},
    }


def _parse_plan(action: Dict[str, Any]) -> List[Tuple[str, int, int, int]]:
    """Parse un plan de déploiement en 4-uplets ``(model_id, col, row, level)``.

    Le niveau est OBLIGATOIRE (frontière ``parse_model_plan``) : une entrée sans étage est
    REFUSÉE, jamais complétée à 0 — cf. shared_utils, ``_PLAN_LEVEL_REQUIRED_MSG``.
    """
    from engine.phase_handlers.shared_utils import parse_model_plan

    raw_plan = require_key(action, "plan")
    if not isinstance(raw_plan, list) or not raw_plan:
        raise ValueError(f"deployment plan must be a non-empty list, got {raw_plan!r}")
    return parse_model_plan(raw_plan, action_name="deployment plan")


def deployment_generate_formation_action(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action read-only : renvoie une formation compacte + son preview rouge/vert."""
    squad_id = str(require_key(action, "unitId"))
    center_col = int(require_key(action, "destCol"))
    center_row = int(require_key(action, "destRow"))
    pool = placement_pool_for_squad(game_state, squad_id)
    if pool is None:
        # Mise en place de DÉPLOIEMENT : c'est l'alternance des déployeurs qui dit à qui c'est.
        deployment_state = require_key(game_state, "deployment_state")
        current_deployer = int(require_key(deployment_state, "current_deployer"))
        units_cache = require_key(game_state, "units_cache")
        entry = require_key(units_cache, squad_id)
        if int(require_key(entry, "player")) != current_deployer:
            return False, {"error": "unit_not_current_deployer", "unitId": squad_id}
    else:
        # Arrivée de réserves (20.04) : pas de `current_deployer` pendant la phase de mouvement.
        # La porte équivalente est l'éligibilité du tour — le round d'arrivée est LU par unité.
        from engine.phase_handlers.movement_handlers import ingress_eligible_units

        if squad_id not in ingress_eligible_units(game_state):
            return False, {"error": "ingress_not_available_this_round", "unitId": squad_id}
    # Niveau de VUE au drop (étages) : sert de niveau DEMANDÉ pour résoudre l'effectif par fig
    # (§13.06). Sans lui, le preview le prendrait à 0 → toutes les figs au sol même en vue étage.
    view_level = int(action.get("level") or 0)  # get allowed (défaut sol)
    plan = generate_compact_formation(game_state, squad_id, center_col, center_row, pool)
    plan_leveled = [(mid, c, r, view_level) for mid, c, r in plan]
    preview = deployment_preview_plan(game_state, squad_id, plan_leveled, pool)
    return True, {
        "action": "deploy_generate_formation",
        "unitId": squad_id,
        # Le plan rendu au front porte son étage : c'est CE plan que le front renvoie au preview
        # puis au commit, et la frontière de décodage refuse désormais toute entrée muette.
        "plan": [[mid, c, r, lv] for mid, c, r, lv in plan_leveled],
        **preview,
    }


def deployment_preview_action(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action read-only : dry-run d'un plan fourni par le front."""
    squad_id = str(require_key(action, "unitId"))
    plan = _parse_plan(action)
    preview = deployment_preview_plan(
        game_state, squad_id, plan, placement_pool_for_squad(game_state, squad_id)
    )
    return True, {
        "action": "deploy_preview",
        "unitId": squad_id,
        **preview,
    }


def build_validated_deployment_plan(
    game_state: Dict[str, Any], squad_id: str, anchor_col: int, anchor_row: int,
    pool_override: Optional[AbstractSet[Tuple[int, int]]] = None,
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Formation compacte AU SOL autour de l'ancre + validation par-figurine.

    Retourne le plan en 4-uplets ``(model_id, col, row, level=0)`` si TOUTES les figurines
    sont légales (``deployment_preview_plan.can_validate``), sinon ``None``.

    Pourquoi cette fonction existe : ``generate_compact_formation`` est un helper UX qui
    peut rendre un plan avec des figurines HORS ZONE (overflow documenté : « signalées
    rouge par le preview, à repositionner »). Le plan n'est donc PAS légal par
    construction — seul le preview le garantit. Tout appelant qui veut committer un
    placement par-figurine depuis une simple ancre DOIT passer par ici.

    Lecture pure et DÉTERMINISTE (spirale BFS + preview, aucune écriture) : le décodeur gym
    l'appelle pour choisir une ancre exécutable et le commit la rappelle pour produire le
    plan — à état identique, les deux obtiennent le MÊME plan. Même contrat que la carte de
    cellules du move (``store_squad_move_cell_map``) : ce que le masque autorise est
    exactement ce que le commit exécute.

    ⚠️ L'ancre ORIENTE le placement, elle ne le CONTRAINT pas : la spirale de
    ``generate_compact_formation`` retient la 1re case légale, donc une ancre hors zone place
    l'escouade dans la zone la plus proche au lieu d'échouer. Le refus d'une ancre hors zone
    reste donc la responsabilité de la validation mono-ancre de ``deploy_unit``
    (``deploy_footprint_outside_zone``) — ne pas la retirer en croyant ce helper suffisant.

    Niveau 0 : la formation est générée au sol (cf. ``generate_compact_formation``). Les
    étages restent Phase B pour le gym ; le flux PvP par escouade passe, lui, par
    ``deploy_generate_formation`` avec son niveau de vue.
    """
    plan = generate_compact_formation(
        game_state, str(squad_id), int(anchor_col), int(anchor_row), pool_override
    )
    leveled: List[Tuple[str, int, int, int]] = [(mid, c, r, 0) for mid, c, r in plan]
    preview = deployment_preview_plan(game_state, str(squad_id), leveled, pool_override)
    if not preview["can_validate"]:
        return None
    return leveled


DEPLOY_PLAN_CACHE_KEY = "_deploy_plan_cache"


def _deploy_plan_cache_stamp(
    game_state: Dict[str, Any], squad_id: str, anchor_col: int, anchor_row: int
) -> Dict[str, Any]:
    """Tampon d'identité d'un plan mémoisé : escouade + ancre + phase + avancement.

    ``deployed_count`` capture le SEUL changement d'état capable de rendre un plan périmé
    entre sa validation et son commit (une autre escouade posée entre-temps déplace les
    chevauchements). Miroir du tampon (ancre, phase) de ``store_squad_move_cell_map``.
    """
    deployment_state = require_key(game_state, "deployment_state")
    return {
        "squad_id": str(squad_id),
        "anchor": (int(anchor_col), int(anchor_row)),
        "phase": str(game_state.get("phase", "")),  # get allowed (board sans phase posée)
        "deployed_count": len(require_key(deployment_state, "deployed_units")),
    }


def store_validated_deployment_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    anchor_col: int,
    anchor_row: int,
    plan: List[Tuple[str, int, int, int]],
) -> None:
    """Mémoise le plan validé par le décodeur pour que le commit ne le RECALCULE pas.

    Pure optimisation : ``build_validated_deployment_plan`` est déterministe (verrouillé par
    test), donc un recalcul rendrait le même plan — la mémo n'est jamais une source de vérité
    divergente, seulement l'économie d'un 2e ``generate_compact_formation`` (~77 ms mesurés sur
    board x5, soit le double du coût de la phase de déploiement si on le paie deux fois).
    """
    game_state[DEPLOY_PLAN_CACHE_KEY] = {
        **_deploy_plan_cache_stamp(game_state, squad_id, anchor_col, anchor_row),
        "plan": plan,
    }


def read_validated_deployment_plan(
    game_state: Dict[str, Any], squad_id: str, anchor_col: int, anchor_row: int
) -> Optional[List[Tuple[str, int, int, int]]]:
    """Relit le plan mémoisé SI son tampon correspond exactement, sinon ``None``.

    ``None`` est un état LÉGITIME, pas une erreur masquée : les appelants sans décodeur
    (auto-déploiement du tutoriel PvP, drag mono-socle) n'en mémoisent jamais — ils passent
    simplement par le calcul.
    """
    cached = game_state.get(DEPLOY_PLAN_CACHE_KEY)  # get allowed (aucun plan mémoisé)
    if cached is None:
        return None
    stamp = _deploy_plan_cache_stamp(game_state, squad_id, anchor_col, anchor_row)
    if any(cached.get(k) != v for k, v in stamp.items()):  # get allowed (comparaison de tampon)
        return None
    return require_key(cached, "plan")


def _apply_deploy_plan(
    game_state: Dict[str, Any], action: Dict[str, Any],
    pool_override: Optional[AbstractSet[Tuple[int, int]]] = None,
    check_current_deployer: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
    """Tronc commun commit/recommit : résout l'unité, valide le plan (placement +
    cohésion via ``deployment_preview_plan``) et écrit les positions des figurines.

    NE TOUCHE PAS ``deployable_units`` / ``deployed_units`` ni l'alternance des
    déployeurs : la gestion de l'état de progression appartient aux appelants.

    Retourne (True, {}) si le plan a été appliqué, sinon (False, erreur).
    """
    squad_id = str(require_key(action, "unitId"))

    unit = get_unit_by_id(game_state, squad_id)
    if not unit:
        raise KeyError(f"Unit {squad_id} missing from game_state['units']")
    # L'alternance des déployeurs n'existe QUE pendant la phase de déploiement. Une mise en
    # place déclenchée par une règle (ingress move 20.04) survient pendant le tour de son
    # propriétaire, sans `deployment_state["current_deployer"]` à interroger.
    if check_current_deployer:
        deployment_state = require_key(game_state, "deployment_state")
        current_deployer = int(require_key(deployment_state, "current_deployer"))
        if int(require_key(unit, "player")) != current_deployer:
            return False, {"error": "unit_not_current_deployer", "unitId": squad_id}

    plan = _parse_plan(action)
    alive = set(_alive_model_ids(game_state, squad_id))
    plan_ids = {mid for mid, _, _, _ in plan}
    if plan_ids != alive:
        return False, {
            "error": "plan_models_mismatch",
            "unitId": squad_id,
            "expected": sorted(alive),
            "got": sorted(plan_ids),
        }

    preview = deployment_preview_plan(game_state, squad_id, plan, pool_override)
    if not preview["can_validate"]:
        return False, {
            "error": "invalid_deploy_plan",
            "unitId": squad_id,
            "per_model": preview["per_model"],
            "coherency_ok": preview["coherency_ok"],
        }

    # Persiste le niveau EFFECTIF (dérivé de la position, cf. deployment_preview_plan) : une fig
    # hors empreinte d'étage est posée au sol même si la vue était sur l'étage. Un plan de
    # déploiement ne porte pas d'orientation (4-uplets) : la primitive résout donc avec celle déjà
    # posée sur la figurine, et ne l'écrit pas.
    for mid, c, r, level in plan:
        place_model_at_effective_level(game_state, mid, c, r, level)

    # Sync ancre de la liste units sur l'ancre recalculée dans units_cache (col/row + niveau).
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)  # get allowed
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))
        unit["level"] = int(require_key(entry, "level"))
    # Statut de mise en place (source unique) — clause « that unit was not set up on the
    # battlefield this turn » de [HEAVY] 24.16, et base de la feature d'observation
    # déploiement/réserve (V11_audit_observation.md §8). Sentinelle None = pas encore sur le
    # board. Une mise en place pendant la PHASE de déploiement est PRÉ-BATAILLE (tour 0), pas
    # « this turn » : sans cette distinction, HEAVY serait refusé à tort au 1er tour. Une arrivée
    # en cours de bataille (réserves, 20 — non modélisées à ce jour) porterait le tour courant.
    unit["deployed_on_turn"] = (
        0 if require_key(game_state, "phase") == "deployment" else int(require_key(game_state, "turn"))
    )
    # 20.03 — « To arrive on the battlefield, each strategic reserves unit must make an ingress
    # move ». Une fois POSÉE, l'unité n'est plus en réserves : elle est arrivée. Écrit ici, dans
    # le commit de mise en place (source unique du passage hors table -> table), et non dans le
    # handler d'ingress : les deux états ne peuvent donc pas diverger.
    unit["in_strategic_reserves"] = False
    # Caches d'adjacence ennemie : l'unité vient d'APPARAÎTRE sur le plateau, donc les hexes
    # qu'elle rend adjacents doivent entrer dans le cache des AUTRES joueurs — celui qu'ils
    # consultent pour savoir où ils n'ont pas le droit d'aller. Ces caches sont construits une
    # fois à l'ouverture de la phase de mouvement : une mise en place SURVENUE PENDANT cette
    # phase (ingress move 20.04) les laissait ignorer l'arrivante, et un mouvement réactif
    # adverse (9") pouvait alors se poser dans sa zone d'engagement. Jumeau de l'appel que fait
    # `movement_commit_move_plan_handler` après un déplacement.
    #
    # Exclu PENDANT la phase de déploiement : `movement_phase_start` construit ces caches de
    # zéro juste après, pour tous les joueurs. Les recalculer à chaque pose y serait du travail
    # jeté, pas une sécurité.
    if entry is not None and require_key(game_state, "phase") != "deployment":
        from engine.phase_handlers.shared_utils import (
            update_enemy_adjacent_caches_after_unit_move,
        )

        update_enemy_adjacent_caches_after_unit_move(
            game_state,
            moved_unit_player=int(require_key(unit, "player")),
            # (-1,-1) = position hors table d'où l'unité arrive : aucun hexe à retirer du cache.
            old_col=-1, old_row=-1,
            new_col=int(entry["col"]), new_row=int(entry["row"]),
            old_occupied=set(),
            new_occupied=entry.get("occupied_hexes"),  # get allowed (mono-hex -> ancre seule)
        )
    rebuild_choice_timing_index(game_state)
    return True, {}


def deployment_commit_plan(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Valide (bouton Valider) puis commit le déploiement d'une escouade.

    ``plan`` doit couvrir TOUTES les figurines vivantes de l'escouade.

    REFUSE tant que l'étape Declare Battle Formations n'est pas épuisée : 20.01 place la mise en
    réserves AVANT le déploiement, et poser une seule figurine avant la fin des déclarations
    donnerait au déclarant suivant une information que la règle ne lui accorde pas.
    """
    squad_id = str(require_key(action, "unitId"))
    deployment_state = require_key(game_state, "deployment_state")
    if reserves_declaration_step_is_open(game_state):
        return False, {"error": "reserves_declaration_still_open", "unitId": squad_id}
    current_deployer = int(require_key(deployment_state, "current_deployer"))

    deployable_units = require_key(deployment_state, "deployable_units")
    deployable_list = deployable_units.get(
        current_deployer, deployable_units.get(str(current_deployer))
    )
    if deployable_list is None:
        raise KeyError(f"deployable_units missing player {current_deployer}")
    if squad_id not in [str(uid) for uid in deployable_list]:
        return False, {"error": "unit_not_deployable", "unitId": squad_id}

    ok, err = _apply_deploy_plan(game_state, action)
    if not ok:
        return False, err

    _mark_deployed(deployment_state, squad_id, current_deployer)

    next_deployer = _resolve_next_deployer_after_success(deployment_state, current_deployer)
    if next_deployer is None:
        deployment_state["deployment_complete"] = True
    else:
        deployment_state["current_deployer"] = next_deployer
        game_state["current_player"] = next_deployer

    result: Dict[str, Any] = {
        "action": "deploy_commit",
        "unitId": squad_id,
        "deployment_complete": deployment_state.get("deployment_complete", False),  # get allowed
    }
    if deployment_state.get("deployment_complete", False):  # get allowed
        game_state["current_player"] = 1
        result.update({"phase_complete": True, "next_phase": "command"})
    return True, result


def strategic_reserves_usage(game_state: Dict[str, Any], player: int) -> Tuple[int, int]:
    """``(points engagés, plafond)`` en réserves pour ``player`` — règle 20.01 (50 %).

    SOURCE UNIQUE des deux grandeurs : celle qui DÉCIDE de l'acceptation d'un dépôt
    (`unit_can_be_placed_in_strategic_reserves`, via le headroom) et celle qui est AFFICHÉE au
    joueur (le ratio « 120/250 » du conteneur PvP) doivent être le même calcul. Les séparer
    ferait afficher un ratio qui n'est pas celui qui refuse le dépôt — exactement le défaut que
    l'API cherchait à éviter côté client.

    Plafond nul quand la taille de bataille (`points_limit`, posée au chargement) est absente :
    la règle est alors invérifiable, donc AUCUN dépôt n'est possible. C'est la règle qui ferme.
    """
    from engine.game_state import STRATEGIC_RESERVES_POINTS_RATIO

    points_limit = require_key(game_state, "points_limit")
    cap = int(int(points_limit) * STRATEGIC_RESERVES_POINTS_RATIO) if points_limit else 0
    used = sum(
        int(require_key(u, "VALUE"))
        for u in require_key(game_state, "units")
        if int(require_key(u, "player")) == int(player)
        and u.get("in_strategic_reserves", False)  # get allowed (champ optionnel, cf. loader)
    )
    return (used, cap)


def strategic_reserves_points_headroom(game_state: Dict[str, Any], player: int) -> int:
    """Points encore plaçables en réserves par ``player`` sans dépasser le plafond 20.01 (50 %).

    Le plafond porte sur la valeur TOTALE des réserves du joueur ; le contrôle est donc le même
    qu'au chargement (`validate_strategic_reserves_cap`), appliqué ici de façon INCRÉMENTALE :
    c'est ce qui permet au masque de fermer la mise en réserve dès qu'une unité ne tiendrait
    plus sous le plafond, au lieu de laisser l'agent produire une liste illégale.
    """
    used, cap = strategic_reserves_usage(game_state, player)
    return max(0, cap - used)


def unit_can_be_placed_in_strategic_reserves(game_state: Dict[str, Any], unit_id: str) -> bool:
    """20.01 — cette unité peut-elle être placée en réserves au lieu d'être déployée ?

    Trois conditions, toutes du texte de la règle : elle n'est pas une FORTIFICATION, elle n'est
    pas déjà posée, et sa valeur en points tient sous le plafond de 50 % restant.
    """
    unit = get_unit_by_id(game_state, str(unit_id))
    if unit is None:
        raise KeyError(f"unit_can_be_placed_in_strategic_reserves: unit {unit_id} introuvable")
    if require_key(unit, "deployed_on_turn") is not None:
        return False
    keywords = {
        str(require_key(kw, "keywordId")).strip().lower()
        for kw in require_key(unit, "UNIT_KEYWORDS")
    }
    if "fortification" in keywords:
        return False
    return int(require_key(unit, "VALUE")) <= strategic_reserves_points_headroom(
        game_state, int(require_key(unit, "player"))
    )


#: Clé de `deployment_state` portant la FILE des unités à qui l'étape Declare Battle Formations
#: doit encore poser la question 20.01. Chaque entrée est un couple ``[joueur, id d'escouade]``.
#:
#: POURQUOI UNE FILE, ET POURQUOI ELLE EST BÂTIE AVANT TOUTE MISE EN PLACE. 20.01 situe la
#: déclaration « Before the battle, in the Declare Battle Formations step » — une étape qui
#: PRÉCÈDE le déploiement (`25 Rules appendix.pdf` : Declare Battle Formations, puis Pre-battle
#: Abilities, puis Begin the Battle). Tant que la question était posée au fil du déploiement, le
#: joueur 2 déclarait ses réserves en voyant les unités adverses déjà posées : mesuré, quatre
#: unités du joueur 1 sur la table au moment où le slot restait ouvert. La file fige donc l'ordre
#: des questions au reset, et l'étape entière se résout avant la première pose.
RESERVES_DECLARATION_QUEUE_KEY = "reserves_declaration_queue"

#: Clé de `deployment_state` marquant l'étape 20.01 CLOSE. Une file vide ne suffit pas à la
#: remplacer : la clôture rend la main au premier déployeur, et ce transfert doit se produire UNE
#: fois. Rejoué à chaque construction de masque — ce que ferait un test « la file est vide » — il
#: ramènerait `current_deployer` au joueur 1 après CHAQUE pose et détruirait l'alternance du
#: déploiement.
RESERVES_DECLARATION_CLOSED_KEY = "reserves_declaration_closed"

#: Clé de `deployment_state` marquant qu'une RÉPONSE 20.01 a été donnée, par l'un ou l'autre camp.
#:
#: POURQUOI ELLE NE SE DÉDUIT PAS DE LA FILE. `change_roster` doit être refusé dès que l'étape
#: Declare Battle Formations a commencé : 20.01 place la déclaration après que les listes sont
#: arrêtées, et une armée remplacée en cours d'étape réécrit l'état de l'ADVERSAIRE — question
#: reposée à qui avait déjà répondu, et unité mise de côté remise dans le pool de pose alors que
#: la règle dit « instead of setting up these units on the battlefield ». Comparer la file à celle
#: qu'un reset produirait ne le dit PAS : `next_reserves_declaration_entry` ampute la file des
#: unités qui ne peuvent pas partir en réserves (FORTIFICATION, plafond de 50 % atteint) sans
#: qu'aucune réponse ait été donnée, et une déclaration acceptée retire l'unité de la file ET du
#: pool, donc laisse les deux comparables identiques. Le marqueur est explicite pour cette raison.
#:
#: Une réponse ne se reprend pas : le drapeau ne redevient jamais faux dans une partie.
RESERVES_DECLARATION_STARTED_KEY = "reserves_declaration_started"


def build_reserves_declaration_queue(
    deployable_units: Dict[Any, Any]
) -> List[List[Any]]:
    """File d'interrogation 20.01, ALTERNÉE, figée avant toute mise en place.

    L'alternance (joueur 1, joueur 2, joueur 1, …) est celle du déploiement lui-même
    (`_resolve_next_deployer_after_success`) : la réutiliser plutôt qu'en inventer une seconde
    évite deux ordres de tour concurrents dans la même phase. Elle n'ouvre aucune information —
    une escouade hors table n'a AUCUNE ligne d'entité dans l'observation
    (`deployed_friendly_squad_ids`, `_refresh_enemy_slot_mapping`), donc la déclaration adverse
    reste invisible quel que soit l'ordre.

    L'ordre à l'intérieur d'un joueur est celui de `deployable_units`, la MÊME source que le pool
    de pose : deux ordres divergents feraient poser la question sur une unité et la pose sur une
    autre.
    """
    per_player = {
        player: [
            str(uid)
            for uid in (
                deployable_units.get(player, deployable_units.get(str(player)))  # get allowed
                or []
            )
        ]
        for player in (1, 2)
    }
    queue: List[List[Any]] = []
    for index in range(max(len(per_player[1]), len(per_player[2]))):
        for player in (1, 2):
            if index < len(per_player[player]):
                queue.append([player, per_player[player][index]])
    return queue


def reserves_declaration_step_is_open(game_state: Dict[str, Any]) -> bool:
    """True tant que l'étape Declare Battle Formations n'est pas épuisée.

    Prédicat PARTAGÉ : le masque gym s'en sert pour poser la question avant d'ouvrir le moindre
    slot de pose, et `deployment_commit_plan` refuse tant qu'il est vrai. Deux dérivations
    feraient diverger « la question est-elle encore due ? » de « la pose est-elle encore
    interdite ? », et c'est précisément l'écart qui laissait déclarer après avoir vu le
    déploiement adverse.

    `deployment_recommit_plan` n'a PAS de garde équivalent, et n'en a pas besoin : il repositionne
    une escouade DÉJÀ POSÉE, ce qui suppose qu'une pose a eu lieu, donc que l'étape est close.
    Lui en ajouter un serait un contrôle qui ne peut jamais se déclencher.

    Une entrée dont l'unité ne PEUT PAS aller en réserves (FORTIFICATION, ou plafond de 50 %
    atteint) ne rend pas l'étape ouverte : il n'y a pas de question à lui poser, et un candidat
    unique n'est pas une décision (`agent_decision._validate_options`).
    """
    deployment_state = game_state.get("deployment_state")  # get allowed : absent hors déploiement
    if deployment_state is None:
        return False
    if require_key(deployment_state, RESERVES_DECLARATION_CLOSED_KEY):
        return False
    queue = deployment_state.get(RESERVES_DECLARATION_QUEUE_KEY)  # get allowed : contrôlé ci-dessous
    if queue is None:
        raise KeyError(
            f"deployment_state sans '{RESERVES_DECLARATION_QUEUE_KEY}' : l'etape Declare Battle "
            "Formations 20.01 n'a pas ete initialisee au reset. Sans elle la declaration se "
            "ferait au fil du deploiement, donc apres avoir vu les poses adverses."
        )
    return any(
        unit_can_be_placed_in_strategic_reserves(game_state, str(squad_id))
        for _player, squad_id in queue
    )


def next_reserves_declaration_entry(
    game_state: Dict[str, Any]
) -> Optional[Tuple[int, str]]:
    """Tête de file 20.01 réellement interrogeable — ``(joueur, escouade)`` — ou ``None``.

    Les entrées en tête dont l'unité ne peut plus aller en réserves sont RETIRÉES au passage :
    la question ne se posera jamais pour elles, et les laisser ferait boucler l'appelant.
    """
    deployment_state = require_key(game_state, "deployment_state")
    queue = require_key(deployment_state, RESERVES_DECLARATION_QUEUE_KEY)
    while queue:
        player, squad_id = int(queue[0][0]), str(queue[0][1])
        if unit_can_be_placed_in_strategic_reserves(game_state, squad_id):
            return player, squad_id
        queue.pop(0)
    return None


def consume_reserves_declaration_entry(deployment_state: Dict[str, Any]) -> None:
    """Retire la tête de file 20.01 PARCE QU'ON Y A RÉPONDU, et marque l'étape commencée.

    ÉCRIVAIN UNIQUE des deux gestes, pour les deux sièges : le siège piloté par le modèle y arrive
    par `apply_reserves_declaration_decision`, le siège humain par
    `deployment_place_in_strategic_reserves`. Séparés, l'un des deux oublierait le marqueur et le
    verrou de `change_roster` dépendrait de qui joue.

    À NE PAS CONFONDRE avec le `pop` de `next_reserves_declaration_entry` : celui-là retire une
    question qui ne sera JAMAIS posée (unité inéligible aux réserves), aucune réponse n'a été
    donnée, et l'étape n'est donc pas commencée pour autant.
    """
    require_key(deployment_state, RESERVES_DECLARATION_QUEUE_KEY).pop(0)
    deployment_state[RESERVES_DECLARATION_STARTED_KEY] = True


def reserves_declaration_step_has_started(deployment_state: Dict[str, Any]) -> bool:
    """Une réponse 20.01 a-t-elle déjà été donnée dans cette partie ?

    Lecture unique du marqueur, en `require_key` : une partie en phase de déploiement dont
    `deployment_state` n'aurait pas la clé vient d'un état qui n'est pas passé par le reset, et
    répondre « non » y autoriserait le remplacement d'armée que ce prédicat existe pour refuser.
    """
    return bool(require_key(deployment_state, RESERVES_DECLARATION_STARTED_KEY))


def reserves_declaration_decline_slot(
    game_state: Dict[str, Any], action_mask: Any
) -> Optional[int]:
    """Le `CHOICE_i` qui REFUSE la déclaration 20.01 en attente, ou ``None`` s'il n'y en a pas.

    SOURCE UNIQUE de la doctrine « 20.01 est une décision de LISTE, jamais une décision de
    doctrine » pour les deux poseurs automatiques : les bots d'évaluation
    (`ai.env_wrappers.bot_action_for_pending_choice`) et le déploiement `auto` du moteur
    (`W40KEngine._pick_placement_action`). Écrite deux fois, elle divergerait — et l'adversaire de
    référence se mettrait à réserver dans l'un des deux régimes seulement, ce qui déplacerait la
    baseline de win-rate sans que rien ne le signale.

    Le candidat est retrouvé par son drapeau `declines`, jamais par son index : c'est lui qui
    porte « ne rien faire » (`DECISION_OPTION_BIN_FIELDS`), et un index en dur deviendrait faux le
    jour où l'ordre des candidats changerait.
    """
    from engine.agent_decision import read_pending_agent_decision
    from engine.macro_intents import CHOICE_BASE

    decision = read_pending_agent_decision(game_state)
    if decision is None or str(require_key(decision, "type")) != "reserves_declaration":
        return None
    options = require_key(decision, "options")
    declining = [i for i, option in enumerate(options) if require_key(option, "declines")]
    if len(declining) != 1:
        raise RuntimeError(
            f"reserves_declaration_decline_slot: {len(declining)} candidats `declines` — il en "
            "faut exactement un pour que le refus soit sans ambiguite."
        )
    slot = int(CHOICE_BASE + declining[0])
    if not bool(action_mask[slot]):
        raise RuntimeError(
            f"reserves_declaration_decline_slot: CHOICE_{declining[0]} ferme alors qu'une "
            "declaration 20.01 est en attente — masque incoherent."
        )
    return slot


def close_reserves_declaration_step_if_done(game_state: Dict[str, Any]) -> bool:
    """Ferme l'étape Declare Battle Formations si plus aucune question 20.01 n'est due.

    Rend ``True`` seulement au passage ouvert -> fermé. POINT DE FERMETURE UNIQUE des deux
    sièges : le siège piloté par le modèle y arrive par `arm_reserves_declaration_decision`, le
    siège humain par `deployment_place_in_strategic_reserves`. Deux fermetures séparées feraient
    dépendre du siège l'ordre dans lequel la mise en place reprend.
    """
    deployment_state = require_key(game_state, "deployment_state")
    if require_key(deployment_state, RESERVES_DECLARATION_CLOSED_KEY):
        return False
    if next_reserves_declaration_entry(game_state) is not None:
        return False
    deployment_state[RESERVES_DECLARATION_CLOSED_KEY] = True
    restore_deployer_after_reserves_declaration(game_state)
    return True


def restore_deployer_after_reserves_declaration(game_state: Dict[str, Any]) -> None:
    """Rend la main au PREMIER déployeur une fois l'étape Declare Battle Formations épuisée.

    Les questions 20.01 déplacent `current_deployer` au fil de la file ; la mise en place, elle,
    commence par le joueur 1 — la MÊME règle que le reset (`W40KEngine.reset` : joueur 1, ou
    joueur 2 s'il est le seul à avoir encore une unité à poser). La recopier ici plutôt que de
    laisser `current_deployer` sur le dernier interrogé évite que l'ordre du déploiement dépende
    de la parité du nombre de déclarations.

    Idempotent : appelé à chaque construction de masque une fois la file vide.
    """
    deployment_state = require_key(game_state, "deployment_state")
    first = 1 if _get_deployable_remaining(deployment_state, 1) else 2
    deployment_state["current_deployer"] = first
    game_state["current_player"] = first


def arm_reserves_declaration_decision(
    game_state: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Pose la question 20.01 de la tête de file, ou ``None`` si l'étape est finie.

    Miroir exact d'`arm_fly_declaration_decision` (21.03) : l'appelant qui reçoit une décision
    rend la main au décideur (masque exclusivement `CHOICE_*`), et la mise en place reprendra au
    step suivant.

    ORDRE CONTRACTUEL des candidats (§9.6) : `CHOICE_0` = déclarer l'unité en réserves,
    `CHOICE_1` = la garder pour le déploiement. Aucun des deux n'accorde d'effet de datasheet,
    c'est `declines` qui les sépare — sans lui les deux lignes sortiraient identiques et le choix
    serait un pile-ou-face que PPO ne peut pas apprendre (défaut mesuré sur `waaagh_call`).

    `current_deployer` suit la question : c'est lui que `W40KEngine` recopie dans
    `current_player`, et `consume_pending_agent_decision` refuse une décision qui ne serait pas
    celle du siège courant.
    """
    deployment_state = require_key(game_state, "deployment_state")
    close_reserves_declaration_step_if_done(game_state)
    if require_key(deployment_state, RESERVES_DECLARATION_CLOSED_KEY):
        return None
    entry = next_reserves_declaration_entry(game_state)
    if entry is None:
        raise RuntimeError(
            "arm_reserves_declaration_decision: etape 20.01 declaree ouverte sans question due "
            "— `close_reserves_declaration_step_if_done` vient pourtant de la laisser ouverte."
        )
    player, squad_id = entry
    deployment_state["current_deployer"] = player
    game_state["current_player"] = player

    from engine.agent_decision import set_pending_agent_decision

    return set_pending_agent_decision(
        game_state,
        decision_type="reserves_declaration",
        player=player,
        unit_id=squad_id,
        options=[
            {
                "label": "Place in strategic reserves",
                "effect_ids": (),
                "declines": False,
                "payload": {"declare": True},
            },
            {
                "label": "Deploy normally",
                "effect_ids": (),
                "declines": True,
                "payload": {"declare": False},
            },
        ],
    )


def apply_reserves_declaration_decision(
    game_state: Dict[str, Any], squad_id: str, declared: bool
) -> None:
    """Applique le candidat choisi pour `reserves_declaration`, et EFFACE la décision.

    « Ne pas déclarer » n'est PAS un non-événement : c'est le second candidat, et il doit retirer
    l'unité de la file, sans quoi la question se reposerait indéfiniment — le même piège que le
    set de résolution de la déclaration de vol.

    Le joueur passé au vérificateur vient de l'ÉTAT (`current_player`), donc d'une source
    INDÉPENDANTE de la décision : ce contrôle-là mord, il refuse une réponse qui ne vient pas du
    siège interrogé. `unit_id` est l'escouade SUR LAQUELLE on écrit ; il barre un futur appelant
    qui appliquerait la déclaration à une autre.
    """
    from engine.agent_decision import consume_pending_agent_decision

    deployment_state = require_key(game_state, "deployment_state")
    queue = require_key(deployment_state, RESERVES_DECLARATION_QUEUE_KEY)
    if not queue or str(queue[0][1]) != str(squad_id):
        raise RuntimeError(
            f"apply_reserves_declaration_decision: la reponse porte sur {squad_id}, or la tete de "
            f"file 20.01 est {None if not queue else queue[0][1]!r} — la file et la decision ont "
            "diverge."
        )
    consume_pending_agent_decision(
        game_state,
        decision_type="reserves_declaration",
        player=int(require_key(game_state, "current_player")),
        unit_id=str(squad_id),
    )
    consume_reserves_declaration_entry(deployment_state)
    if declared:
        commit_strategic_reserves(game_state, str(squad_id))
    close_reserves_declaration_step_if_done(game_state)


def commit_strategic_reserves(game_state: Dict[str, Any], squad_id: str) -> None:
    """Écrit la mise en réserves 20.01 d'une unité — ÉCRIVAIN UNIQUE, les deux sièges y passent.

    Le siège piloté par le modèle y arrive par `apply_reserves_declaration_decision`, le siège
    humain par `deployment_place_in_strategic_reserves` : la mutation elle-même ne peut pas
    différer entre les deux, sinon la comptabilité du plafond (`_reserves_placed`) et le pool de
    pose divergeraient selon qui joue.

    L'unité sort du POOL À POSER, mais n'entre PAS dans `deployed_units` : elle n'est pas sur le
    champ de bataille, et `deployment_recommit_plan` (repositionnement pendant la phase de
    déploiement) ne doit pas pouvoir la poser après coup — elle n'arrive que par 20.04.
    """
    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        raise KeyError(f"Unit {squad_id} missing from game_state['units']")
    player = int(require_key(unit, "player"))
    unit["in_strategic_reserves"] = True
    # Compté POUR LES DEUX CAMPS, sans filtre sur le joueur contrôlé : c'est ce filtre qui
    # rendait la mise en réserve du bot invisible. Le siège de l'agent n'est connu qu'à la
    # terminaison (`agent_seat_mode: random`), la projection s'y fait.
    require_key(game_state, "_reserves_placed")[player] += 1
    # _reserves_placed est AUSSI initialisé au reset par le compte des unités pré-déclarées
    # en réserve dans le roster (strategic_reserves: true). Ce hook ne couvre que les unités
    # déclarées EN PLUS pendant l'étape Declare Battle Formations (20.01).
    deployment_state = require_key(game_state, "deployment_state")
    deployable_units = require_key(deployment_state, "deployable_units")
    key = player if player in deployable_units else str(player)
    if key not in deployable_units:
        raise KeyError(f"deployable_units missing player {player}")
    deployable_units[key] = [
        uid for uid in deployable_units[key] if str(uid) != str(squad_id)
    ]

    from engine.game_utils import add_console_log
    add_console_log(game_state, f"STRATEGIC RESERVES (20.01): unit {squad_id} held in reserves")


def deployment_place_in_strategic_reserves(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """20.01 — réponse du SIÈGE HUMAIN à la question de l'étape Declare Battle Formations.

    Pendant de `apply_reserves_declaration_decision`, qui porte la réponse du siège piloté par le
    modèle : même file, même écrivain de la mutation (`commit_strategic_reserves`), même ordre
    d'interrogation. Les deux sièges ne peuvent donc pas jouer deux règles différentes — c'est
    l'invariant que la version précédente ne tenait pas, où le gym passait par `SQUAD_ACTION_WAIT`
    au fil du déploiement et l'humain par un panneau libre.

    ``action["declare"]`` est REQUIS : « garder l'unité pour le déploiement » est le second
    candidat de la décision, pas l'absence de réponse. Le déduire de l'appel ferait de l'un des
    deux choix un défaut silencieux.

    Aucune alternance ici, et c'est le fond de la correction : la déclaration N'EST PAS un tour de
    déploiement. L'ordre des questions est celui de la file, figée au reset, et la mise en place
    ne commence qu'une fois la file vide.
    """
    squad_id = str(require_key(action, "unitId"))
    declare = require_key(action, "declare")
    if not isinstance(declare, bool):
        raise TypeError(
            f"deployment_place_in_strategic_reserves: 'declare' doit etre un booleen, "
            f"recu {declare!r}"
        )
    deployment_state = require_key(game_state, "deployment_state")

    entry = next_reserves_declaration_entry(game_state)
    if entry is None:
        return False, {"error": "reserves_declaration_step_closed", "unitId": squad_id}
    expected_player, expected_squad_id = entry
    if squad_id != expected_squad_id:
        return False, {
            "error": "not_the_pending_reserves_declaration",
            "unitId": squad_id,
            "expectedUnitId": expected_squad_id,
        }

    consume_reserves_declaration_entry(deployment_state)
    if declare:
        commit_strategic_reserves(game_state, squad_id)
    close_reserves_declaration_step_if_done(game_state)

    result: Dict[str, Any] = {
        "action": "deploy_strategic_reserves",
        "unitId": squad_id,
        "player": expected_player,
        "declared": declare,
        "reserves_declaration_open": reserves_declaration_step_is_open(game_state),
    }
    # PLUS RIEN À POSER : cas limite RÉEL — un roster dont la valeur totale tient sous le plafond
    # de 50 % peut partir ENTIÈREMENT en réserves. Sans cette clôture, la phase de déploiement
    # resterait ouverte avec deux pools vides et la partie serait figée pour le siège humain,
    # là où le siège gym s'en sort par `_complete_deployment_if_nothing_to_place`. C'est
    # exactement le `phase_complete` que `deployment_commit_plan` rend dans le même état : les
    # deux sorties de la phase de déploiement doivent le signaler de la même façon.
    if not any(
        deployable_units_of(deployment_state, player) for player in (1, 2)
    ):
        deployment_state["deployment_complete"] = True
        game_state["current_player"] = 1
        result.update({"phase_complete": True, "next_phase": "command"})
    result["deployment_complete"] = deployment_state.get(  # get allowed (posé ci-dessus)
        "deployment_complete", False
    )
    return True, result


def deployment_recommit_plan(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Repositionne une escouade DÉJÀ déployée pendant la phase de déploiement.

    Revalide le plan (zone + collisions + cohésion via ``_apply_deploy_plan``) et
    réécrit les positions, SANS toucher ``deployable_units`` / ``deployed_units``
    ni l'alternance : l'unité reste déployée et le joueur garde la main.
    """
    squad_id = str(require_key(action, "unitId"))
    deployment_state = require_key(game_state, "deployment_state")
    deployed_units = require_key(deployment_state, "deployed_units")
    if squad_id not in {str(u) for u in deployed_units}:
        return False, {"error": "unit_not_deployed", "unitId": squad_id}

    ok, err = _apply_deploy_plan(game_state, action)
    if not ok:
        return False, err

    return True, {"action": "deploy_recommit", "unitId": squad_id}


def execute_deployment_action(game_state: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute deployment action with footprint-aware validation.

    Validates that the entire unit footprint (multi-hex base) fits within the
    deployment pool, does not overlap walls, and does not overlap other units.
    """
    current_phase = require_key(game_state, "phase")
    if current_phase != "deployment":
        return False, {"error": "invalid_phase", "phase": current_phase}

    action_type = require_key(action, "action")
    # Déploiement par escouade (plan par-figurine) : génération de formation,
    # dry-run (rouge/vert + cohésion), commit. ``deploy_unit`` reste le chemin
    # legacy mono-ancre (IA / déploiement random/fixed).
    if action_type == "deploy_generate_formation":
        return deployment_generate_formation_action(game_state, action)
    if action_type == "deploy_preview":
        return deployment_preview_action(game_state, action)
    if action_type == "deploy_commit":
        return deployment_commit_plan(game_state, action)
    if action_type == "deploy_recommit":
        return deployment_recommit_plan(game_state, action)
    # 20.01 — mise en réserves AU LIEU du déploiement. Routée ICI, dans le dispatcher commun aux
    # deux sièges, et non depuis l'API : elle MUTE l'état (l'unité sort du pool à poser, la main
    # passe au déployeur suivant), donc elle doit emprunter le chemin qui journalise l'action,
    # capture le snapshot de rewind et resérialise l'état pour le client.
    if action_type == "deploy_strategic_reserves":
        return deployment_place_in_strategic_reserves(game_state, action)
    if action_type != "deploy_unit":
        return False, {"error": "invalid_deployment_action", "action": action_type}

    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = require_key(deployment_state, "current_deployer")
    unit_id = str(require_key(action, "unitId"))
    dest_col = require_key(action, "destCol")
    dest_row = require_key(action, "destRow")

    deployable_units = require_key(deployment_state, "deployable_units")
    deployable_list = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
    if deployable_list is None:
        raise KeyError(f"deployable_units missing player {current_deployer}")
    if unit_id not in [str(uid) for uid in deployable_list]:
        return False, {"error": "unit_not_deployable", "unitId": unit_id, "current_deployer": current_deployer}

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
    unit_player = require_key(unit, "player")
    if int(unit_player) != int(current_deployer):
        return False, {"error": "unit_not_current_deployer", "unitId": unit_id, "current_deployer": current_deployer}

    # `_deploy_pool_set` et non une matérialisation locale : ces trois lignes en étaient la copie
    # exacte (require_key + `_get_deployment_pool` + normalisation), ce qui reconstruisait les
    # ~16 000 hexes à chaque commit ET contournait la mémoïsation. C'est aussi ce que promet la
    # docstring de `placement_pool_for_squad` — `_deploy_pool_set` est le SEUL propriétaire de la
    # lecture des zones, pour n'avoir qu'un site à repointer le jour où leur stockage change.
    pool_set = _deploy_pool_set(game_state, int(current_deployer))

    candidate_fp = compute_candidate_footprint(int(dest_col), int(dest_row), unit, game_state)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")

    for c, r in candidate_fp:
        if c < 0 or c >= board_cols or r < 0 or r >= board_rows:
            return False, {"error": "deploy_footprint_out_of_bounds", "cell": (c, r)}
        if (c, r) not in pool_set:
            return False, {"error": "deploy_footprint_outside_zone", "cell": (c, r)}

    # Mur : ancre interdite au SOCLE, pas cellule d'empreinte — même prédicat que le pool qui a
    # offert la case, sinon le commit et le pool ne peuvent que diverger.
    if (int(dest_col), int(dest_row)) in wall_blocked_anchors(game_state, unit):
        return False, {
            "error": "deploy_footprint_on_wall", "cell": (int(dest_col), int(dest_row)),
        }

    if _is_footprint_overlapping(
        game_state, candidate_fp,
        shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
        col=int(dest_col), row=int(dest_row), exclude_unit_id=unit_id,
    ):
        return False, {"error": "deploy_footprint_occupied", "unitId": unit_id}

    # Commit PAR-FIGURINE, via le MÊME écrivain que le flux PvP par escouade
    # (``_apply_deploy_plan`` → ``place_model_at_effective_level`` par figurine, puis sync de l'ancre).
    # L'ancien commit n'écrivait que l'ancre (``set_unit_coordinates`` +
    # ``update_units_cache_position``, qui ne touchent JAMAIS ``models_cache``) : les figurines
    # restaient à (-1,-1) et le pipeline squad par-figurine explosait une phase plus tard
    # (``build_rigid_plan`` translatait 6 figurines confondues sur un même hex → « incohérence
    # masque/exécution » au premier move). Cf. V11 T6-f.
    # Aucune formation légale à cette ancre = refus EXPLICITE : le décodeur gym ne propose que
    # des ancres dont le plan est validé (``_select_deployment_hex_for_action``), donc ce retour
    # ne concerne que les appelants qui imposent une ancre (tutoriel PvP, drag mono-socle).
    plan = read_validated_deployment_plan(game_state, unit_id, int(dest_col), int(dest_row))
    if plan is None:
        plan = build_validated_deployment_plan(game_state, unit_id, int(dest_col), int(dest_row))
    if plan is None:
        return False, {
            "error": "deploy_plan_invalid",
            "unitId": unit_id,
            "anchor": (int(dest_col), int(dest_row)),
        }
    ok, plan_err = _apply_deploy_plan(
        game_state,
        {"unitId": unit_id, "plan": [[mid, c, r, lv] for mid, c, r, lv in plan]},
    )
    if not ok:
        return False, plan_err
    _mark_deployed(deployment_state, unit_id, int(current_deployer))

    next_deployer = _resolve_next_deployer_after_success(deployment_state, int(current_deployer))
    if next_deployer is None:
        deployment_state["deployment_complete"] = True
    else:
        deployment_state["current_deployer"] = next_deployer
        game_state["current_player"] = next_deployer

    # Ancre EFFECTIVE (recalculée depuis les figurines par ``_apply_deploy_plan``), pas l'ancre
    # demandée : la formation compacte peut décaler la 1re figurine si la case du clic est prise.
    _committed = require_key(require_key(game_state, "units_cache"), unit_id)
    result = {
        "action": "deploy_unit",
        "unitId": unit_id,
        "destCol": int(require_key(_committed, "col")),
        "destRow": int(require_key(_committed, "row")),
        "deployment_complete": deployment_state.get("deployment_complete", False)
    }

    if deployment_state.get("deployment_complete", False):
        game_state["current_player"] = 1
        result.update({
            "phase_complete": True,
            "next_phase": "command"
        })

    return True, result


