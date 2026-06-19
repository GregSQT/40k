#!/usr/bin/env python3
"""
deployment_handlers.py - Deployment Phase Implementation (Test mode)

Footprint-aware: validates entire unit footprint (multi-hex bases) during deployment.
"""

from typing import Dict, Any, Tuple, List, Optional, Set
from shared.data_validation import require_key
from engine.game_utils import get_unit_by_id
from engine.combat_utils import set_unit_coordinates
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
    game_state: Dict[str, Any], exclude_squad_id: str
) -> Set[Tuple[int, int]]:
    """Cellules occupées par les escouades DÉJÀ déployées (hors ``exclude_squad_id``).

    On exclut les unités non déployées (ancre sentinelle ``(-1,-1)``) : leurs
    empreintes fictives ne doivent pas bloquer une zone de déploiement réelle.
    """
    deployment_state = require_key(game_state, "deployment_state")
    deployed_units = require_key(deployment_state, "deployed_units")
    deployed_str = {str(u) for u in deployed_units}
    units_cache = require_key(game_state, "units_cache")
    occupied: Set[Tuple[int, int]] = set()
    for uid, entry in units_cache.items():
        if str(uid) == str(exclude_squad_id) or str(uid) not in deployed_str:
            continue
        occ = entry.get("occupied_hexes")  # get allowed
        if occ:
            occupied.update((int(c), int(r)) for c, r in occ)
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
    other_occ = _deployed_occupied_positions(game_state, str(squad_id))

    from engine.hex_utils import Socle, footprints_overlap

    placed: List[Tuple[str, int, int]] = []
    placed_socles: List["Socle"] = []

    def _legal_socle(model: Dict[str, Any], c: int, r: int) -> Optional["Socle"]:
        """Place légale = empreinte dans la zone (hors mur / hors unités déployées) ET
        dégagement EUCLIDIEN avec les figs déjà posées — MÊME test que le preview
        (``footprints_overlap``), sinon la formation générée serait flaggée rouge."""
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
        for s in placed_socles:
            if footprints_overlap(cand, s):
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


def deployment_preview_plan(
    game_state: Dict[str, Any], squad_id: str, plan: List[Tuple[str, int, int]]
) -> Dict[str, Any]:
    """Dry-run d'un plan de déploiement par-figurine. Aucune écriture.

    Voile rouge d'une figurine = empreinte hors zone / hors plateau / sur mur /
    chevauchant une unité déjà déployée ou une coéquipière, OU hors cohésion.
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
    other_occ = _deployed_occupied_positions(game_state, str(squad_id))

    n = len(plan)
    footprints: List[Set[Tuple[int, int]]] = []
    socles: List["Socle"] = []
    for mid, nc, nr in plan:
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
        for mid, nc, nr in plan
    ]
    cohesion_red = coherency_violation_flags(cohesion_models, game_state)

    per_model: Dict[str, bool] = {}
    for idx, (mid, nc, nr) in enumerate(plan):
        fp = footprints[idx]
        out_of_bounds = any(
            cc < 0 or cc >= board_cols or rr < 0 or rr >= board_rows for cc, rr in fp
        )
        out_of_zone = any((cc, rr) not in pool_set for cc, rr in fp)
        on_wall = bool(wall_hexes and fp & wall_hexes)
        on_other = bool(other_occ and fp & other_occ)
        intra = any(
            footprints_overlap(socles[idx], socles[j]) for j in range(n) if j != idx
        )
        per_model[str(mid)] = bool(
            not out_of_bounds and not out_of_zone and not on_wall
            and not on_other and not intra and not cohesion_red[idx]
        )

    coherency_ok = not any(cohesion_red)
    all_valid = n > 0 and all(per_model.values())
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "can_validate": bool(all_valid),
    }


def _parse_plan(action: Dict[str, Any]) -> List[Tuple[str, int, int]]:
    raw_plan = require_key(action, "plan")
    if not isinstance(raw_plan, list) or not raw_plan:
        raise ValueError(f"deployment plan must be a non-empty list, got {raw_plan!r}")
    plan: List[Tuple[str, int, int]] = []
    for e in raw_plan:
        if not (isinstance(e, (list, tuple)) and len(e) == 3):
            raise ValueError(f"deployment plan entry must be [model_id, col, row], got {e!r}")
        plan.append((str(e[0]), int(e[1]), int(e[2])))
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

    unit = get_unit_by_id(squad_id, game_state)
    if not unit:
        raise KeyError(f"Unit {squad_id} missing from game_state['units']")
    if int(require_key(unit, "player")) != current_deployer:
        return False, {"error": "unit_not_current_deployer", "unitId": squad_id}

    plan = _parse_plan(action)
    alive = set(_alive_model_ids(game_state, squad_id))
    plan_ids = {mid for mid, _, _ in plan}
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

    for mid, c, r in plan:
        update_model_position(game_state, mid, c, r)

    # Sync ancre de la liste units sur l'ancre recalculée dans units_cache.
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(squad_id)  # get allowed
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))
    rebuild_choice_timing_index(game_state)
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


