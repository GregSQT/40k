#!/usr/bin/env python3
"""
deployment_handlers.py - Deployment Phase Implementation (Test mode)

Footprint-aware: validates entire unit footprint (multi-hex bases) during deployment.
"""

from typing import Dict, Any, Tuple, List, Optional, Set
from shared.data_validation import require_key
from engine.game_utils import get_unit_by_id
from engine.combat_utils import set_unit_coordinates
from engine.terrain_utils import validate_floor_placement, resolve_model_floor_level
from engine.phase_handlers.shared_utils import (
    update_units_cache_position, rebuild_choice_timing_index,
    compute_candidate_footprint, build_occupied_positions_set,
    candidate_overlaps_any_unit, coherency_violation_flags,
    update_model_position,
)


def deployment_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize deployment phase using precomputed deployment_state.
    """
    if "deployment_state" not in game_state:
        raise KeyError("deployment_state is required to start deployment phase")
    game_state["phase"] = "deployment"
    return {"phase_start": True}


def _get_deployment_pool(deployment_pools: Dict[Any, Any], player: int) -> List[Tuple[int, int]]:
    if player in deployment_pools:
        return deployment_pools[player]
    player_key = str(player)
    if player_key in deployment_pools:
        return deployment_pools[player_key]
    raise KeyError(f"deployment_pools missing player {player}")


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
# coherency_violation_flags, update_model_position ; hex_utils : Socle,
# footprints_overlap). La SEULE différence avec le move plan est la contrainte
# spatiale : footprint ⊆ zone de déploiement (pool_set) au lieu d'un budget de
# mouvement + zone d'engagement ennemie.


def _deploy_pool_set(game_state: Dict[str, Any], player: int) -> Set[Tuple[int, int]]:
    deployment_state = require_key(game_state, "deployment_state")
    deployment_pools = require_key(deployment_state, "deployment_pools")
    pool = _get_deployment_pool(deployment_pools, int(player))
    return {(int(c), int(r)) for c, r in pool}


def _deployed_occupied_positions(
    game_state: Dict[str, Any], exclude_squad_id: str, level: Optional[int] = None
) -> Set[Tuple[int, int]]:
    """Cellules occupées par les escouades DÉJÀ déployées (hors ``exclude_squad_id``).

    On exclut les unités non déployées (ancre sentinelle ``(-1,-1)``) : leurs
    empreintes fictives ne doivent pas bloquer une zone de déploiement réelle.

    ``level`` : None = toutes figs confondues (comportement historique). Un entier
    restreint aux figurines DÉPLOYÉES à ce niveau (deux figs à des étages différents
    ne se gênent pas — murs mis à part, cf. stage.md § murs verticaux prolongés).
    """
    deployment_state = require_key(game_state, "deployment_state")
    deployed_units = require_key(deployment_state, "deployed_units")
    deployed_str = {str(u) for u in deployed_units}
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    if level is None:
        for uid, entry in units_cache.items():
            if str(uid) == str(exclude_squad_id) or str(uid) not in deployed_str:
                continue
            occ = entry.get("occupied_hexes")  # get allowed
            if occ:
                occupied.update((int(c), int(r)) for c, r in occ)
        return occupied
    # Filtrage par niveau : empreinte par-figurine des figs déployées au niveau demandé.
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    for uid in units_cache:
        if str(uid) == str(exclude_squad_id) or str(uid) not in deployed_str:
            continue
        for mid in squad_models.get(str(uid), []):  # get allowed
            m = models_cache.get(mid)
            if m is None or int(require_key(m, "level")) != level:
                continue
            occupied.update(_model_footprint(game_state, m, int(m["col"]), int(m["row"])))
    return occupied


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
    game_state: Dict[str, Any], squad_id: str, center_col: int, center_row: int
) -> List[Tuple[str, int, int]]:
    """Génère une formation compacte (anneaux hex) autour de ``center`` pour toutes
    les figurines vivantes de l'escouade.

    Spirale BFS depuis le centre : chaque figurine prend la 1re cellule légale
    (dans la zone, hors mur, hors empreinte des unités déjà déployées et des
    figurines déjà placées). Si la zone ne peut pas accueillir toutes les
    figurines, les restantes sont posées au centre (le preview les signalera en
    rouge — pas de placement silencieux hors-règle).
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
    pool_set = _deploy_pool_set(game_state, player)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())  # get allowed
    # Formation générée AU SOL → seules les figs déployées au niveau 0 bloquent (une fig à
    # l'étage ne bloque pas le sol sous elle). Le preview revalide ensuite par niveau effectif.
    other_occ = _deployed_occupied_positions(game_state, str(squad_id), level=0)

    from engine.hex_utils import Socle, footprints_overlap

    placed: List[Tuple[str, int, int]] = []
    placed_socles: List["Socle"] = []

    def _legal_socle(model: Dict[str, Any], c: int, r: int) -> Optional["Socle"]:
        """Place légale = empreinte dans la zone (hors mur / hors unités déployées) ET
        à 1 hex de marge des figs déjà posées (empreinte + anneau de voisins).

        NB : la marge est propre à la GÉNÉRATION (formation aérée). La règle de validité
        (``footprints_overlap``, preview/commit) tolère le contact — non modifiée — pour
        ne pas flagger en rouge un ajustement manuel où les socles se touchent."""
        fp = _model_footprint(game_state, model, c, r)
        for cc, rr in fp:
            if cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows:
                return None
            if (cc, rr) not in pool_set:
                return None
            if (cc, rr) in wall_hexes:
                return None
            if (cc, rr) in other_occ:
                return None
        cand = Socle(
            shape=require_key(model, "BASE_SHAPE"),
            base_size=require_key(model, "BASE_SIZE"),
            col=int(c), row=int(r), fp=fp,
        )
        # Marge de 1 hex : la candidate ne doit ni chevaucher ni TOUCHER une fig déjà posée.
        # On bloque l'empreinte de chaque socle posé + son anneau de voisins.
        for s in placed_socles:
            s_fp = s.fp or set()
            blocked: Set[Tuple[int, int]] = set(s_fp)
            for cc, rr in s_fp:
                for nb in get_neighbors(cc, rr):
                    blocked.add(nb)
            if any(cell in blocked for cell in fp):
                return None
        return cand

    seen: Set[Tuple[int, int]] = {(int(center_col), int(center_row))}
    queue: "deque[Tuple[int, int]]" = deque([(int(center_col), int(center_row))])
    idx = 0
    while queue and idx < len(model_ids):
        c, r = queue.popleft()
        model = models_cache[model_ids[idx]]
        socle = _legal_socle(model, c, r)
        if socle is not None:
            placed.append((model_ids[idx], c, r))
            placed_socles.append(socle)
            idx += 1
        for nc, nr in get_neighbors(c, r):
            if (nc, nr) not in seen:
                seen.add((nc, nr))
                queue.append((nc, nr))
    for j in range(idx, len(model_ids)):
        placed.append((model_ids[j], int(center_col), int(center_row)))
    return placed


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
    pool_set = _deploy_pool_set(game_state, player)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())  # get allowed
    level = int(level or 0)
    terrain_areas = require_key(game_state, "terrain_areas")
    from engine.terrain_utils import floor_hexes_at_level
    floor_hexes: Set[Tuple[int, int]] = (
        floor_hexes_at_level(terrain_areas, level) if level >= 1 else set()
    )
    # Occupation des unités déployées PAR NIVEAU effectif possible d'une candidate (sol, et étage
    # vue si >= 1) — plus d'union tous-niveaux (bug : une fig à l'étage bloquait le sol dessous).
    occ_by_level: Dict[int, Set[Tuple[int, int]]] = {
        0: _deployed_occupied_positions(game_state, squad_id, level=0)
    }
    if level >= 1:
        occ_by_level[level] = _deployed_occupied_positions(game_state, squad_id, level=level)

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
        sib_eff = resolve_model_floor_level(
            sc, sr, require_key(sibling, "BASE_SHAPE"), require_key(sibling, "BASE_SIZE"),
            int(sibling.get("orientation", 0)), sib_req, terrain_areas,  # get allowed
        )
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
    pool_cube = {offset_to_cube(int(c), int(r)) for (c, r) in pool_set}
    wall_cube = {offset_to_cube(int(c), int(r)) for (c, r) in wall_hexes}
    floor_cube = {offset_to_cube(int(c), int(r)) for (c, r) in floor_hexes}
    blocked_cube_by_level: Dict[int, Set[Tuple[int, int, int]]] = {
        lv: {
            offset_to_cube(int(c), int(r))
            for (c, r) in (occ_by_level[lv] | same_squad_by_level.get(lv, set()))
        }
        for lv in occ_by_level
    }
    destinations: List[Tuple[int, int]] = []
    eff_by_dest: Dict[Tuple[int, int], int] = {}
    for (cc, rr) in pool_set:
        bx, by, bz = offset_to_cube(int(cc), int(rr))
        cells = [(bx + ox, by + oy, bz + oz) for (ox, oy, oz) in fp_offsets]
        if any(cell not in pool_cube or cell in wall_cube for cell in cells):
            continue
        # Niveau effectif de la candidate : étage vue si l'empreinte tient ENTIÈREMENT sur le
        # plancher (13.06, même dérivation que resolve_model_floor_level), sinon sol.
        eff = level if (
            level >= 1 and floor_cube and all(cell in floor_cube for cell in cells)
        ) else 0
        if any(cell in blocked_cube_by_level.get(eff, blocked_cube_by_level[0]) for cell in cells):
            continue
        destinations.append((int(cc), int(rr)))
        eff_by_dest[(int(cc), int(rr))] = eff

    # Miroir EXACT du move (movement_build_model_destinations_pool) : le blocage par cases hex
    # ci-dessus sous-estime le disque (~16% de recouvrement à 5 sous-hex passe entre les cases).
    # On retire du pool les ancres où le socle de la fig chevaucherait une sœur AU MÊME NIVEAU
    # effectif en clearance euclidien (base RÉELLE, footprints_overlap) → pool et voile rouge
    # cohérents. Tangence tolérée. Sœurs d'un autre étage : pas de gêne.
    from engine.hex_utils import Socle, footprints_overlap

    m_shape = require_key(model, "BASE_SHAPE")
    m_base = require_key(model, "BASE_SIZE")
    m_orient = int(model.get("orientation", 0))  # get allowed
    sibling_socles_by_level: Dict[int, List["Socle"]] = {}
    for sibling, sc, sr, sib_eff in sibling_states:
        s_shape = require_key(sibling, "BASE_SHAPE")
        s_base = require_key(sibling, "BASE_SIZE")
        s_fp = None if s_shape == "round" else _model_footprint(game_state, sibling, sc, sr)
        sibling_socles_by_level.setdefault(sib_eff, []).append(
            Socle(shape=s_shape, base_size=s_base, col=sc, row=sr, fp=s_fp)
        )
    if sibling_socles_by_level:
        filtered: List[Tuple[int, int]] = []
        for (dc, dr) in destinations:
            same_level_socles = sibling_socles_by_level.get(eff_by_dest[(dc, dr)], [])
            if not same_level_socles:
                filtered.append((dc, dr))
                continue
            m_fp = None if m_shape == "round" else compute_candidate_footprint(
                dc, dr,
                {"BASE_SHAPE": m_shape, "BASE_SIZE": m_base, "orientation": m_orient},
                game_state,
            )
            m_socle = Socle(shape=m_shape, base_size=m_base, col=dc, row=dr, fp=m_fp)
            if not any(footprints_overlap(m_socle, s) for s in same_level_socles):
                filtered.append((dc, dr))
        destinations = filtered
    return {"destinations": destinations}


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
    pool_set = _deploy_pool_set(game_state, player)

    # Empreinte combinée (absolue) du bloc aux positions provisoires.
    combined: Set[Tuple[int, int]] = set()
    for mid, c, r in plan:
        m = models_cache.get(str(mid))  # get allowed
        if m is None:
            continue
        combined.update(_model_footprint(game_state, m, int(c), int(r)))

    # Offsets cube relatifs à l'ancre-réf : invariants par translation rigide du bloc.
    rx, ry, rz = offset_to_cube(int(ref_col), int(ref_row))
    offsets: List[Tuple[int, int, int]] = []
    for (cc, rr) in combined:
        x, y, z = offset_to_cube(int(cc), int(rr))
        offsets.append((x - rx, y - ry, z - rz))

    # pool en CUBE → test d'appartenance direct, sans cube_to_offset dans la boucle interne.
    pool_cube = {offset_to_cube(int(c), int(r)) for (c, r) in pool_set}
    destinations: List[Tuple[int, int]] = []
    for (cc, rr) in pool_set:
        bx, by, bz = offset_to_cube(int(cc), int(rr))
        ok = True
        for (ox, oy, oz) in offsets:
            if (bx + ox, by + oy, bz + oz) not in pool_cube:
                ok = False
                break
        if ok:
            destinations.append((int(cc), int(rr)))
    return {"destinations": destinations}


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
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[Any, ...]]
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
    pool_set = _deploy_pool_set(game_state, player)
    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())  # get allowed
    terrain_areas = require_key(game_state, "terrain_areas")
    unit = get_unit_by_id(str(squad_id), game_state)
    if not unit:
        raise KeyError(f"deployment_preview_plan: unit {squad_id} missing from game_state['units']")
    unit_keywords = require_key(unit, "UNIT_KEYWORDS")

    # Niveau EFFECTIF par figurine = niveau demandé (vue) SI l'empreinte tient sur ce plancher, sinon
    # sol (0). Permet une escouade MIXTE (figs sur l'étage + figs au sol) déployée depuis la vue étage :
    # les figs hors empreinte redeviennent 'sol' au lieu d'être rejetées (voile rouge) à tort.
    norm: List[Tuple[str, int, int, int]] = []
    for _mid, _nc, _nr, _req in (_normalize_plan_entry(e) for e in plan):
        _m = require_key(models_cache, str(_mid))
        _bs = require_key(_m, "BASE_SHAPE")
        _bz = require_key(_m, "BASE_SIZE")
        _ori = int(_m.get("orientation", 0))  # get allowed
        _eff = resolve_model_floor_level(_nc, _nr, _bs, _bz, _ori, _req, terrain_areas)
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
        fp = footprints[idx]
        out_of_bounds = any(
            cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows for cc, rr in fp
        )
        out_of_zone = any((cc, rr) not in pool_set for cc, rr in fp)
        on_wall = bool(wall_hexes and fp & wall_hexes)
        on_other = bool(other_occ_by_level[lv] and fp & other_occ_by_level[lv])
        # Collision intra-escouade uniquement entre figs du plan AU MÊME NIVEAU.
        intra = any(
            footprints_overlap(socles[idx], socles[j])
            for j in range(n) if j != idx and levels[j] == lv
        )
        # Pose sur étage (niveau >= 1) : règle 13.06 (mot-clé + empreinte entièrement sur l'étage).
        floor_bad = False
        if lv >= 1:
            m = require_key(models_cache, str(mid))
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
        per_model[str(mid)] = bool(
            not out_of_bounds and not out_of_zone and not on_wall
            and not on_other and not intra and not cohesion_red[idx] and not floor_bad
        )
    coherency_ok = not any(cohesion_red)
    all_valid = n > 0 and all(per_model.values())
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
    }


def _parse_plan(action: Dict[str, Any]) -> List[Tuple[str, int, int, int]]:
    """Parse un plan de déploiement en 4-uplets ``(model_id, col, row, level)``.

    Le niveau est OPTIONNEL : une entrée à 3 éléments ``[mid, col, row]`` reste valide
    (niveau 0 = sol) — le front existant reste compatible. Une entrée à 4 éléments
    ``[mid, col, row, level]`` cible un étage.
    """
    raw_plan = require_key(action, "plan")
    if not isinstance(raw_plan, list) or not raw_plan:
        raise ValueError(f"deployment plan must be a non-empty list, got {raw_plan!r}")
    plan: List[Tuple[str, int, int, int]] = []
    for e in raw_plan:
        if not (isinstance(e, (list, tuple)) and len(e) in (3, 4)):
            raise ValueError(f"deployment plan entry must be [model_id, col, row(, level)], got {e!r}")
        level = int(e[3]) if len(e) == 4 else 0
        if level < 0:
            raise ValueError(f"deployment plan entry level must be >= 0, got {e!r}")
        plan.append((str(e[0]), int(e[1]), int(e[2]), level))
    return plan


def deployment_generate_formation_action(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action read-only : renvoie une formation compacte + son preview rouge/vert."""
    squad_id = str(require_key(action, "unitId"))
    center_col = int(require_key(action, "destCol"))
    center_row = int(require_key(action, "destRow"))
    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = int(require_key(deployment_state, "current_deployer"))
    units_cache = require_key(game_state, "units_cache")
    entry = require_key(units_cache, squad_id)
    if int(require_key(entry, "player")) != current_deployer:
        return False, {"error": "unit_not_current_deployer", "unitId": squad_id}
    plan = generate_compact_formation(game_state, squad_id, center_col, center_row)
    preview = deployment_preview_plan(game_state, squad_id, plan)
    return True, {
        "action": "deploy_generate_formation",
        "unitId": squad_id,
        "plan": [[mid, c, r] for mid, c, r in plan],
        **preview,
    }


def deployment_preview_action(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Action read-only : dry-run d'un plan fourni par le front."""
    squad_id = str(require_key(action, "unitId"))
    plan = _parse_plan(action)
    preview = deployment_preview_plan(game_state, squad_id, plan)
    return True, {
        "action": "deploy_preview",
        "unitId": squad_id,
        **preview,
    }


def _apply_deploy_plan(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Tronc commun commit/recommit : résout l'unité, valide le plan (placement +
    cohésion via ``deployment_preview_plan``) et écrit les positions des figurines.

    NE TOUCHE PAS ``deployable_units`` / ``deployed_units`` ni l'alternance des
    déployeurs : la gestion de l'état de progression appartient aux appelants.

    Retourne (True, {}) si le plan a été appliqué, sinon (False, erreur).
    """
    squad_id = str(require_key(action, "unitId"))
    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = int(require_key(deployment_state, "current_deployer"))

    unit = get_unit_by_id(squad_id, game_state)
    if not unit:
        raise KeyError(f"Unit {squad_id} missing from game_state['units']")
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

    preview = deployment_preview_plan(game_state, squad_id, plan)
    if not preview["can_validate"]:
        return False, {
            "error": "invalid_deploy_plan",
            "unitId": squad_id,
            "per_model": preview["per_model"],
            "coherency_ok": preview["coherency_ok"],
        }

    # Persiste le niveau EFFECTIF (dérivé de la position, cf. deployment_preview_plan) : une fig
    # hors empreinte d'étage est posée au sol même si la vue était sur l'étage.
    _terrain_areas = require_key(game_state, "terrain_areas")
    _models_cache = require_key(game_state, "models_cache")
    for mid, c, r, level in plan:
        _m = require_key(_models_cache, str(mid))
        _bs = require_key(_m, "BASE_SHAPE")
        _bz = require_key(_m, "BASE_SIZE")
        _ori = int(_m.get("orientation", 0))
        _eff = resolve_model_floor_level(c, r, _bs, _bz, _ori, level, _terrain_areas)
        update_model_position(game_state, mid, c, r, level=_eff)

    # Sync ancre de la liste units sur l'ancre recalculée dans units_cache (col/row + niveau).
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)  # get allowed
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))
        unit["level"] = int(require_key(entry, "level"))
    rebuild_choice_timing_index(game_state)
    return True, {}


def deployment_commit_plan(
    game_state: Dict[str, Any], action: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """Valide (bouton Valider) puis commit le déploiement d'une escouade.

    ``plan`` doit couvrir TOUTES les figurines vivantes de l'escouade.
    """
    squad_id = str(require_key(action, "unitId"))
    deployment_state = require_key(game_state, "deployment_state")
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

    unit = get_unit_by_id(unit_id, game_state)
    if not unit:
        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
    unit_player = require_key(unit, "player")
    if int(unit_player) != int(current_deployer):
        return False, {"error": "unit_not_current_deployer", "unitId": unit_id, "current_deployer": current_deployer}

    deployment_pools = require_key(deployment_state, "deployment_pools")
    pool = _get_deployment_pool(deployment_pools, int(current_deployer))
    pool_set = {(int(col), int(row)) for col, row in pool}

    candidate_fp = compute_candidate_footprint(int(dest_col), int(dest_row), unit, game_state)

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    wall_hexes = game_state.get("wall_hexes", set())

    for c, r in candidate_fp:
        if c < 0 or c >= board_cols or r < 0 or r >= board_rows:
            return False, {"error": "deploy_footprint_out_of_bounds", "cell": (c, r)}
        if (c, r) not in pool_set:
            return False, {"error": "deploy_footprint_outside_zone", "cell": (c, r)}
        if (c, r) in wall_hexes:
            return False, {"error": "deploy_footprint_on_wall", "cell": (c, r)}

    if _is_footprint_overlapping(
        game_state, candidate_fp,
        shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
        col=int(dest_col), row=int(dest_row), exclude_unit_id=unit_id,
    ):
        return False, {"error": "deploy_footprint_occupied", "unitId": unit_id}

    set_unit_coordinates(unit, dest_col, dest_row)
    update_units_cache_position(game_state, unit_id, dest_col, dest_row)
    rebuild_choice_timing_index(game_state)
    _mark_deployed(deployment_state, unit_id, int(current_deployer))

    next_deployer = _resolve_next_deployer_after_success(deployment_state, int(current_deployer))
    if next_deployer is None:
        deployment_state["deployment_complete"] = True
    else:
        deployment_state["current_deployer"] = next_deployer
        game_state["current_player"] = next_deployer

    result = {
        "action": "deploy_unit",
        "unitId": unit_id,
        "destCol": dest_col,
        "destRow": dest_row,
        "deployment_complete": deployment_state.get("deployment_complete", False)
    }

    if deployment_state.get("deployment_complete", False):
        game_state["current_player"] = 1
        result.update({
            "phase_complete": True,
            "next_phase": "command"
        })

    return True, result


