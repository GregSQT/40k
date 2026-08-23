#!/usr/bin/env python3
"""
engine/phase_handlers/fight_handlers.py - AI_TURN.md Fight Phase Implementation
Pure stateless functions implementing AI_TURN.md fight specification

References: AI_TURN.md Section ⚔️ FIGHT PHASE LOGIC
ZERO TOLERANCE for state storage or wrapper patterns

CRITICAL: On ne tire PAS en phase de fight. La règle CLOSE_QUARTERS permet de tirer en phase
de SHOOTING même si l'unité est adjacente à une unité ennemie (exception au "engaged").
"""

import sys
import time
from collections import deque
from typing import Dict, List, Tuple, Set, Optional, Any, Mapping
from .generic_handlers import end_activation
from shared.data_validation import require_key
from engine.utils.weapon_helpers import melee_weapons
from engine.action_log_utils import append_action_log
from engine.game_utils import add_console_log, safe_print, enter_phase
from engine.combat_utils import (
    normalize_coordinates,
    calculate_hex_distance,
    get_unit_by_id,
    get_unit_coordinates,
    get_hex_neighbors,
    resolve_dice_value,
    set_unit_coordinates,
)
from engine.game_state import (
    GameStateManager,
    objective_hex_zones, unit_is_oath_target_of, waaagh_melee_bonus,
)
from engine.hex_utils import cube_to_offset, offset_to_cube
# Etages 13.06 — remontes au NIVEAU MODULE : `_fight_effective_level_at` et
# `_fight_rigid_model_placements` sont appeles par CELLULE CANDIDATE dans les boucles de pool
# (des milliers de fois par construction), et un import local y coute un lookup `sys.modules`
# a chaque appel. Aucun cycle ne le justifiait : `engine.terrain_utils` n'importe rien de
# `engine.phase_handlers`.
from engine.terrain_utils import resolved_floor_height_at
from .shared_utils import (
    # Libelle de token de [CLEAVE] : la cle de `additive_rules_applied`, lue par l afficheur
    # partage. Importee et non reecrite en litteral — c est ce qui lie les deux producteurs
    # (tir et melee) au meme vocabulaire.
    RULE_LABEL_CLEAVE,
    # Traducteurs de causes de relance et marqueurs de capacite, PARTAGES avec le roller de tir :
    # les inliner est la forme exacte sous laquelle ces deux chemins ont deja diverge.
    resolve_oath_effects,
    stamp_reroll_abilities,
    stamp_wound_bonus_ability,
    enemy_entries_on_battlefield,
    entries_on_battlefield,
    entry_footprint,
    entry_is_on_battlefield,
    model_in_base_contact,
    end_of_turn_regain_coherency_all_squads,
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, PASS, ERROR, FIGHT,
    update_units_cache_hp, remove_from_units_cache,
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position, require_unit_from_cache,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    is_unit_on_objective as shared_is_unit_on_objective,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    build_occupied_positions_set,
    compute_candidate_footprint,
    is_footprint_placement_valid,
    is_placement_valid_with_clearance, wall_blocked_anchors, socle_orientation,
    resolve_model_effective_level,
    update_units_cache_position,
    translate_squad_to_destination,
    update_enemy_adjacent_caches_after_unit_move,
    ManualAllocCtx,
    _build_manual_allocation,
    apply_manual_shoot_declare_order,
    apply_manual_shoot_allocation,
    manual_allocation_waiting_payload,
    _target_highest_bodyguard_toughness,
    display_save_threshold_with_waaagh,
    get_fighting_models,
    squad_fight_unit_activation_start,
    squad_fight_restart_activation,
    squad_declare_fight,
    DeclareAttackCtx,
    declare_attack_model,
    declare_attack_weapon,
    declare_attack_weapon_qty,
    weapon_qty_max,
    undeclare_attack_weapon_qty,
    weapons_for_target,
    eligible_models_for_weapon,
    toggle_attack_model_weapon,
    models_status_for_target,
    models_weapons_for_squad,
    _union_weapons,
    _enemy_squad_ids,
    _synth_model_entry,
    MovePlan,
    parse_model_plan_as_map,
)

FightFootprintOffsetPair = Optional[Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]]
_unit_registry_singleton = None  # UnitRegistry reads static files — safe to share across all episodes


def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific direct or granted rule effect by ruleId."""
    return shared_unit_has_rule_effect(unit, rule_id)


def _get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId that grants/owns the effect; None if absent."""
    return shared_get_source_unit_rule_id_for_effect(unit, effect_rule_id)


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.displayName for an effect rule; None if absent."""
    return shared_get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)


def _is_ai_controlled_fight_unit(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Return True when the unit owner is programmatically controlled (auto-resolution).

    Delegue a la source unique is_programmatic_owner (shared_utils) : True en gym training,
    sinon player_types == 'ai'. Utilise par les checks defender_human du flux fight et par
    _fight_auto_defender (FIGHT_CTX) -> allocation des pertes en melee auto-resolue en gym."""
    from .shared_utils import is_programmatic_owner
    unit_player = require_key(unit, "player")
    return is_programmatic_owner(game_state, unit_player)


def _log_end_of_turn_coherency_removals(
    game_state: Dict[str, Any], removed_by_squad: Dict[str, List[str]]
) -> None:
    """Journalise les retraits de l'etape End of Turn (03.03).

    Le retrait est AUTOMATIQUE alors que la regle laisse le choix au joueur (dette assumee, cf.
    `end_of_turn_regain_coherency_all_squads`) : il doit au minimum etre VISIBLE, sans quoi un
    joueur PvP verrait des figurines disparaitre sans explication.

    DEUX canaux, et il en fallait deux. `add_console_log` est debug-only (`--debug`) et ne quitte
    jamais `game_state` : il ne sert que la console PvP. Le retrait 03.03 est pourtant la SEULE
    mort qui ne descend d'aucune attaque, donc la seule qu'aucune ligne de journal ne portait —
    step.log n'a jamais contenu un seul `COHERENCY`. Tout lecteur qui reconstruit l'etat par
    accumulation d'evenements (l'analyzer, le replay) gardait donc la figurine retiree VIVANTE
    jusqu'a la prochaine action de son escouade : un fantome qui engage ses ennemis et bloque
    leurs chemins. Mesure sur le run du 2026-08-12 (E485) : la figurine `2#9`, retiree ici,
    fabriquait a elle seule un « advance from adjacent » ET un « advance au-dela du budget » sur
    l'escouade adverse — deux fautes inventees, sur un tour parfaitement legal.

    L'entree d'action_log porte le segment `[MODELS:]` de l'escouade APRES retrait (pose par
    `_build_step_log_details`, comme pour toute autre ligne) : elle ne dit donc pas seulement
    « une figurine est morte », elle REPOSITIONNE l'escouade entiere chez le lecteur.
    """
    for squad_id in sorted(removed_by_squad):
        removed = removed_by_squad[squad_id]
        add_console_log(
            game_state,
            f"COHERENCY (03.03) : escouade {squad_id} hors coherency en fin de tour — "
            f"{len(removed)} figurine(s) retiree(s) : {', '.join(removed)}",
        )
        # Ancre POST-retrait : `destroy_model` la recalcule quand c'est l'ancre qui tombe. La lire
        # ici (et non avant la boucle de retrait) est ce qui rend la ligne coherente avec son
        # propre segment `[MODELS:]`.
        entry = game_state.get("units_cache", {}).get(str(squad_id))  # get allowed
        if entry is None:
            raise KeyError(
                f"units_cache sans entree pour l'escouade {squad_id} apres retrait 03.03 : "
                "le retrait s'arrete a une figurine, l'escouade ne peut pas avoir disparu"
            )
        append_action_log(
            game_state,
            {
                "type": "coherency_removal",
                "message": (
                    f"Unit {squad_id} COHERENCY REMOVAL (03.03) : "
                    f"{len(removed)} model(s) removed : {' '.join(removed)}"
                ),
                "turn": require_key(game_state, "turn"),
                "phase": "fight",
                "unitId": str(squad_id),
                "player": int(require_key(entry, "player")),
                "col": int(require_key(entry, "col")),
                "row": int(require_key(entry, "row")),
                "removed_models": list(removed),
                "timestamp": "server_time",
                "reward": 0.0,
            },
        )


def _is_fight_auto_execution_allowed(game_state: Dict[str, Any]) -> bool:
    """
    Return whether fight-phase auto execution is allowed for the current mode.

    PvP modes are strictly manual: no auto-activation, no auto-targeting,
    no auto-chain execution in fight phase.
    """
    mode_code = game_state.get("current_mode_code")
    if mode_code is None:
        return True
    if not isinstance(mode_code, str):
        raise TypeError(
            f"game_state['current_mode_code'] must be str when present, got {type(mode_code).__name__}"
        )
    if mode_code in {"pvp", "pvp_test"}:
        return False
    if mode_code in {"pve", "pve_test", "endless_duty"}:
        return True
    raise ValueError(f"Unsupported current_mode_code for fight auto execution: {mode_code}")


def _is_unit_on_objective(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Return True if unit coordinates are inside any objective hex.

    Delegue au helper partage (shared_utils) : identique tir/fight (reroll_towound_target
    _on_objective s applique aux deux phases)."""
    return shared_is_unit_on_objective(unit, game_state)


def _remove_dead_unit_from_fight_pools(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    CRITICAL: Immediately remove a dead unit from the other-phase activation pools.

    This must be called as soon as a unit dies to prevent it from being activated
    in subsequent sub-phases (move/shoot/charge pools survive across the fight phase).
    """
    # CRITICAL: Remove from other phase pools (units can die in fight but be in other pools)
    # Import from shooting_handlers to reuse the function
    from .shooting_handlers import _remove_dead_unit_from_pools
    _remove_dead_unit_from_pools(game_state, unit_id)


def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is adjacent to at least one enemy within engagement zone.

    Uses min distance between footprints (§3.3, §9.8) for multi-hex units.
    For legacy boards (engagement_zone=1, single-hex), equivalent to hex distance <= 1.
    """
    from engine.spatial_relations import get_engagement_zone
    from engine.spatial_relations import unit_within_engagement_zone_footprints
    cc_range = get_engagement_zone(game_state)

    if "console_logs" not in game_state:
        game_state["console_logs"] = []

    if unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=cc_range, max_distance=cc_range,
    ):
        add_console_log(game_state, f"FIGHT ELIGIBLE: Unit {unit['id']} within engagement_zone {cc_range}")
        return True

    add_console_log(game_state, f"FIGHT NOT ELIGIBLE: Unit {unit['id']} has no enemies within engagement_zone {cc_range}")
    return False


def _fight_footprint_has_enemy_hex_contact(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    fp: Set[Tuple[int, int]],
) -> bool:
    """Return True when a footprint has A/contact hex adjacency with any enemy footprint."""
    from engine.hex_utils import min_distance_between_sets

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_id_str = str(unit["id"])
    for _enemy_id, cache_entry in enemy_entries_on_battlefield(
        units_cache, unit_player, exclude_id=unit_id_str
    ):
        enemy_fp = entry_footprint(cache_entry)
        if min_distance_between_sets(fp, enemy_fp, max_distance=1) <= 1:
            return True
    return False


def _fight_unit_is_hex_adjacent_to_enemy_footprint(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    « Collé » : au moins un hex de l'empreinte partage un bord avec un hex d'empreinte ennemie
    (distance minimale entre empreintes == 1).
    """
    unit_id_str = str(unit["id"])
    unit_entry = require_unit_from_cache(
        unit_id_str, game_state, "_fight_unit_is_hex_adjacent_to_enemy_footprint"
    )
    unit_fp = entry_footprint(unit_entry)

    return _fight_footprint_has_enemy_hex_contact(game_state, unit, unit_fp)


def _fight_pile_in_closest_enemy_snapshot(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[int, List[str]]:
    """
    Retourne (d_min, ids des unités ennemies dont l'empreinte est à distance minimale d_min).

    CONTRAT DE SORTIE, sur lequel s'appuient tous les consommateurs du palier : les ids rendus
    sont lus dans ``units_cache`` (via ``enemy_entries_on_battlefield``), donc chacun y est
    présent. Un consommateur qui n'en retrouve pas un constate une désynchronisation, pas un
    palier vide — c'est pourquoi ils lèvent (``require_unit_from_cache``) au lieu de le sauter.
    """
    from engine.hex_utils import min_distance_between_sets

    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = require_unit_from_cache(
        unit_id_str, game_state, "_fight_pile_in_closest_enemy_snapshot"
    )
    unit_col, unit_row = int(unit_entry["col"]), int(unit_entry["row"])
    unit_fp = entry_footprint(unit_entry)
    unit_player = int(unit["player"]) if unit["player"] is not None else None

    d_cap: Optional[int] = None
    for _eid, ce in enemy_entries_on_battlefield(units_cache, unit_player):
        approx = abs(unit_col - int(ce["col"])) + abs(unit_row - int(ce["row"]))
        if d_cap is None or approx < d_cap:
            d_cap = approx

    d_min: Optional[int] = None
    closest_ids: List[str] = []
    for enemy_id, cache_entry in enemy_entries_on_battlefield(units_cache, unit_player):
        enemy_fp = entry_footprint(cache_entry)
        if d_min is not None and d_cap is not None:
            cap = min(d_cap, d_min)
        elif d_min is not None:
            cap = d_min
        else:
            cap = d_cap
        d = min_distance_between_sets(unit_fp, enemy_fp, max_distance=cap if cap is not None else 0)
        if d_min is not None and d > d_min:
            continue
        if d_min is None or d < d_min:
            d_min = d
            closest_ids = [str(enemy_id)]
        elif d == d_min:
            closest_ids.append(str(enemy_id))

    if d_min is None:
        raise ValueError("_fight_pile_in_closest_enemy_snapshot: no enemy on board")
    return d_min, closest_ids


def _fight_pile_in_new_fp_strictly_closer_to_closest_tier(
    game_state: Dict[str, Any],
    new_fp: Set[Tuple[int, int]],
    d_min: int,
    closest_ids: List[str],
    *,
    closest_enemy_fps: Optional[List[Set[Tuple[int, int]]]] = None,
    closer_shell_union: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """True si la nouvelle empreinte est strictement plus proche d'au moins une unité du palier le plus proche."""
    if d_min <= 0:
        return False
    if closer_shell_union is not None:
        return bool(new_fp & closer_shell_union)
    from engine.hex_utils import min_distance_between_sets

    enemy_fps = closest_enemy_fps
    if enemy_fps is None:
        enemy_fps = []
        for eid in closest_ids:
            # Contrat de sortie de `_fight_pile_in_closest_enemy_snapshot` (cf. son docstring).
            # Sauter une empreinte relâchait la contrainte WHILE 12.03 sans le dire.
            ce = require_unit_from_cache(
                str(eid), game_state, "_fight_pile_in_new_fp_strictly_closer_to_closest_tier"
            )
            enemy_fps.append(entry_footprint(ce))
    radius = d_min - 1
    for efp in enemy_fps:
        d = min_distance_between_sets(new_fp, efp, max_distance=radius)
        if d <= radius:
            return True
    return False


def _append_fight_move_log(  # noqa: PLR0913
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    *,
    kind: str,
    from_col: int,
    from_row: int,
    to_col: int,
    to_row: int,
    move_details: List[Dict[str, Any]],
    models_segment: str = "",
    pile_in_target_ids: Optional[List[str]] = None,
    consolidation_mode: Optional[str] = None,
) -> None:
    """Log par-figurine unique d'un déplacement de phase fight (pile-in / consolidation).

    Point de vérité UNIQUE partagé par le chemin manuel PvP et le driver gym
    (`_fight_v11_gym_settle` via `commit_move`) : la ligne (PvP game log + step.log/replay)
    est ainsi strictement identique dans les deux flux. ``kind`` ∈ {"pile_in",
    "overrun_pile_in", "consolidation"} ; le verbe et le type d'event en découlent.
    ``move_details`` : départ→arrivée par figurine.

    ``models_segment`` : segment ``[MODELS:]`` capturé IMMÉDIATEMENT après ``commit_move``
    (positions post-déplacement instantanées). Le driver gym (`_gym_commit_fight_move`) le
    fournit pour éviter que `_build_step_log_details` ne lise `_models_segment_for_unit` au
    moment du flush — trop tard si pile-in et consolidation ont toutes deux été commitées dans
    le même `_fight_v11_gym_settle` avant le drain. Laissé vide par les appelants PvP (flush
    immédiat via `log_action`, pas de décalage).
    """
    if kind == "pile_in":
        verb = "PILED IN"
    elif kind == "overrun_pile_in":
        verb = "OVERRUN PILED IN"
    elif kind == "consolidation":
        verb = "CONSOLIDATED"
    else:
        raise ValueError(f"_append_fight_move_log: kind invalide {kind!r}")
    entry: Dict[str, Any] = {
        "type": kind,
        "message": (
            f"Unit {unit['id']} {verb} from ({from_col},{from_row}) "
            f"to ({to_col},{to_row})"
        ),
        "turn": require_key(game_state, "turn"),
        "phase": "fight",
        "unitId": unit["id"],
        "player": unit["player"],
        "fromCol": from_col,
        "fromRow": from_row,
        "toCol": to_col,
        "toRow": to_row,
        "timestamp": "server_time",
        "is_ai_action": unit["player"] == 2,
        "moveDetails": move_details,
    }
    if models_segment:
        entry["models_segment"] = models_segment
    # L17 — cibles de pile-in (12.03) et mode de consolidation (12.08).
    if pile_in_target_ids is not None:
        entry["pileInTargetIds"] = [str(t) for t in pile_in_target_ids]
    if consolidation_mode is not None:
        entry["consolidationMode"] = consolidation_mode
    append_action_log(game_state, entry)


def _fight_effective_level_at(
    game_state: Dict[str, Any],
    model_entry: Dict[str, Any],
    col: int,
    row: int,
    requested_level: int,
) -> int:
    """Niveau EFFECTIF (§13.06) d'une figurine posée en ``(col, row)`` avec ce niveau DEMANDÉ.

    Point d'entrée du FIGHT vers `resolve_model_effective_level` (`shared_utils`), la source
    unique du dépôt : translation rigide d'un pool d'ancres, slot d'ILP, plan d'auto-placement.
    Un niveau ne se transporte pas d'une position à l'autre — une figurine translatée hors de
    l'empreinte de son plancher est AU SOL. Coller le niveau d'origine à une case sans plancher
    faisait lever ``floor_height_at`` (« figurine marquée à l'étage mais hors empreinte de
    plancher »), c'est-à-dire un crash du pool là où la règle demande de la poser au sol.

    Ce wrapper existait AVANT la primitive commune et en réécrivait le contenu, avec deux
    replis anti-erreur que la source unique n'a pas : `orientation` par défaut 0 (le cache la
    pose toujours) et `terrain_areas` par défaut vide (le moteur la pose toujours). Il ne garde
    que son rôle de nom local.
    """
    return resolve_model_effective_level(
        game_state, model_entry, int(col), int(row), int(requested_level)
    )


def _fight_model_fp_pair(game_state: Dict[str, Any], model_entry: Dict[str, Any]) -> Any:
    """Offsets d'empreinte even/odd au socle de CETTE figurine — SOURCE UNIQUE côté fight.

    Le pile-in et la consolidation sont des mouvements PAR FIGURINE, mais ils préparaient leurs
    offsets d'empreinte avec `_charge_prepare_footprint_offsets(unit, …)`, c'est-à-dire au socle
    de l'ESCOUADE. Mesuré sur les scénarios du dépôt : 67 figurines sur 684 portent un socle
    différent de leur escouade — toutes des personnages attachés — et les 67 étaient
    SOUS-empreintées, de 19 hexes annoncés contre 43 réels (jusqu'à 61). Le pool leur proposait
    donc des cases où leur socle chevauche un mur ou une coéquipière, que le commit refuse
    ensuite : la divergence pool/commit que ce dépôt a déjà payée plusieurs fois.

    Le cache de `_charge_offsets_for_base` est indexé par SOCLE (forme, taille, orientation), pas
    par unité : deux figurines de même socle le partagent, et l'appeler par figurine dans une
    boucle reste un accès de dictionnaire. Mesuré à 20 000 empreintes : 1,05× le coût de la forme
    « préparée une seule fois », sur la part empreinte uniquement.
    """
    from .charge_handlers import _charge_offsets_for_base

    return _charge_offsets_for_base(
        game_state,
        require_key(model_entry, "BASE_SHAPE"),
        require_key(model_entry, "BASE_SIZE"),
        int(require_key(model_entry, "orientation")),
    )


def _fight_rigid_model_placements(
    game_state: Dict[str, Any], squad_id: str, anchor_col: int, anchor_row: int
) -> Dict[str, Tuple[int, int, int]]:
    """Positions par-figurine après TRANSLATION RIGIDE de l'escouade vers ``(anchor_col, anchor_row)``.

    Les pools d'ancres du fight (pile-in / consolidation) déplacent le bloc rigidement : l'empreinte
    candidate est celle du bloc translaté. Les centres par-figurine se translatent donc du MÊME
    vecteur, calculé en coordonnées CUBE — en offset odd-q un dx impair change la parité de colonne
    et déformerait le bloc (miroir de ``build_rigid_plan``). Ces pools sont HORIZONTAUX — ils ne
    font ni monter ni descendre — mais le niveau n'est pas pour autant reconduit tel quel : il est
    RÉSOLU à la position d'arrivée (``_fight_effective_level_at``), car une figurine translatée
    hors de l'empreinte de son plancher se retrouve au sol (§13.06).
    """
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = require_key(game_state, "units_cache")
    src = require_key(units_cache, str(squad_id))
    ax, ay, az = offset_to_cube(int(require_key(src, "col")), int(require_key(src, "row")))
    bx, by, bz = offset_to_cube(int(anchor_col), int(anchor_row))
    dcx, dcy, dcz = bx - ax, by - ay, bz - az
    out: Dict[str, Tuple[int, int, int]] = {}
    for mid in squad_models.get(str(squad_id), []):  # get allowed
        m = models_cache.get(mid)
        if m is None:
            continue
        mx, my, mz = offset_to_cube(int(m["col"]), int(m["row"]))
        new_col, new_row = cube_to_offset(mx + dcx, my + dcy, mz + dcz)
        out[str(mid)] = (
            int(new_col),
            int(new_row),
            _fight_effective_level_at(game_state, m, new_col, new_row, int(require_key(m, "level"))),
        )
    return out


def _fight_synth_cache_entries_at_footprint(
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    anchor_col: int,
    anchor_row: int,
    model_placements: Optional[Mapping[str, Tuple[int, int, int]]] = None,
) -> List[Dict[str, Any]]:
    """Entrées ``units_cache``-compatibles d'une configuration candidate — UNE PAR SOCLE distinct.

    Un test d'engagement d'unité (« Your unit must be engaged », 12.03 / 12.08) se lit sur ces
    entrées avec un ``any`` : l'unité est engagée dès qu'une de ses classes de socle l'est.

    ``model_placements`` (``{model_id: (col, row, level)}``) décrit la position par-figurine dans
    la configuration CANDIDATE. Absent → translation rigide du bloc depuis sa position courante
    (``_fight_rigid_model_placements``), ce que font les pools d'ancres ; fourni → configuration
    par-figurine d'un plan (chaque figurine à SON étage, escouade à cheval sur deux niveaux).

    POURQUOI PLUSIEURS ENTRÉES. Une entrée-cache ne porte QU'UN socle et QU'UNE hauteur
    (``BASE_SHAPE``/``BASE_SIZE``/``orientation``/``MODEL_HEIGHT``), appliqués à tous ses centres
    par-figurine : ``socle_from_cache_entry`` et ``_class_footprint`` les relisent sur l'entrée et
    IGNORENT l'empreinte qu'on y poserait. Une entrée unique mesurait donc TOUTES les figurines au
    gabarit de l'escouade — un personnage attaché à plus grand socle (ou plus haut) était jugé sur
    celui de la troupe qu'il accompagne. Le partitionnement par socle est exact : ``any`` sur les
    classes = minimum sur les figurines, sur les trois chemins de mesure (hex, euclidien, 3D).
    Une escouade homogène rend UNE entrée — le coût est celui d'avant.

    Les cartes par-figurine ne sont PAS optionnelles : elles sont lues sur le vrai chemin de jeu.
    - métrique euclidienne : ``socle_from_cache_entry`` mesure depuis ``occupied_hexes_by_model``
      (``model_centers``) et IGNORE ``occupied_hexes``. Hériter la carte de l'entrée source faisait
      répondre tout contrôle « après mouvement » sur l'état d'AVANT.
    - engagement 3D : ``_vertical_classes`` exige ``occupied_hexes_by_model`` +
      ``floor_height_by_model`` + ``MODEL_HEIGHT``.
    """
    from engine.hex_utils import compute_occupied_hexes
    from engine.spatial_relations import _hashable

    uid = str(require_key(unit, "id"))
    units_cache = require_key(game_state, "units_cache")
    src = units_cache.get(uid)
    if src is None:
        raise ValueError(f"_fight_synth_cache_entries_at_footprint: unit {uid} missing from units_cache")
    placements = (
        dict(model_placements)
        if model_placements is not None
        else _fight_rigid_model_placements(game_state, uid, int(anchor_col), int(anchor_row))
    )
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (plateau sans terrain)
    # Socle, facing et hauteur pris sur la FIGURINE, pas sur l'escouade — cf. docstring. Repli sur
    # l'entrée d'escouade pour les figurines synthétiques, qui n'ont pas d'entrée dans
    # `models_cache` : ce n'est pas un repli anti-erreur mais la seule géométrie que porte alors
    # l'état (états de test 2D, figurines d'ancre).
    models_cache = game_state.get("models_cache", {})  # get allowed (états de test sans par-fig)
    by_base: Dict[Tuple[Any, Any, int, Any], Dict[str, Any]] = {}
    for mid, (c, r, lv) in placements.items():
        _m = models_cache.get(str(mid)) or src
        shape = require_key(_m, "BASE_SHAPE")
        size = require_key(_m, "BASE_SIZE")
        orient = int(_m.get("orientation", 0))  # get allowed (synthétiques sans facing)
        height = _m["MODEL_HEIGHT"] if "MODEL_HEIGHT" in _m else src.get("MODEL_HEIGHT")  # get allowed (états 2D)
        # `BASE_SIZE` est un SCALAIRE pour un socle rond, une LISTE pour un oval — donc non
        # hashable telle quelle (même piège que `_engagement_entry_fingerprint`). La clé passe par
        # `_hashable`, qui laisse `size` intacte pour les appels géométriques ci-dessous.
        key = (shape, _hashable(size), orient, height)
        entry = by_base.get(key)
        if entry is None:
            entry = dict(src)
            entry["col"] = int(anchor_col)
            entry["row"] = int(anchor_row)
            entry["BASE_SHAPE"] = shape
            entry["BASE_SIZE"] = size
            entry["orientation"] = orient
            if height is None:
                entry.pop("MODEL_HEIGHT", None)
            else:
                entry["MODEL_HEIGHT"] = float(height)
            entry["occupied_hexes"] = set()
            entry["occupied_hexes_by_model"] = {}
            entry["floor_height_by_model"] = {}
            by_base[key] = entry
        entry["occupied_hexes"] |= compute_occupied_hexes(int(c), int(r), shape, size, orient)
        entry["occupied_hexes_by_model"][str(mid)] = (int(c), int(r))
        # Le niveau d'un placement est une DEMANDE (plan du joueur, slot d'ILP, translation
        # d'ancre) : c'est le plancher qui tranche. Sans cette résolution, un aperçu en LECTURE
        # SEULE d'un plan posant une figurine hors plancher levait au lieu de rendre
        # `can_validate: False` — une 500 côté PvP là où l'UX attend un voile rouge.
        entry["floor_height_by_model"][str(mid)] = resolved_floor_height_at(
            terrain_areas, int(c), int(r), shape, size, orient, int(lv),
        )
    return list(by_base.values())


def _fight_model_start_engagements(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
    """Unités ennemies avec lesquelles CHAQUE figurine est engagée à sa position courante.

    12.03 / 12.08 AFTER : « each model that started this move engaged with an enemy unit must still
    be engaged with **that** enemy unit ». La clause est par FIGURINE et par UNITÉ ENNEMIE — un
    verdict d'unité (« l'escouade reste engagée avec X ») laisse passer un move où la figurine qui
    tenait X s'en va pendant qu'une autre s'en approche.

    Les figurines qui ne partent engagées avec personne sont ABSENTES du dictionnaire : elles n'ont
    rien à conserver, et les interroger par ancre coûterait sans rien décider.
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone, get_engagement_zone, engagement_distance_metric
    from .shared_utils import _synth_model_entry

    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    player = int(require_key(unit, "player"))
    enemies = list(enemy_entries_on_battlefield(units_cache, player, exclude_id=uid))
    out: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for mid in squad_models.get(uid, []):  # get allowed (escouade sans figurine = rien à conserver)
        m = models_cache.get(str(mid))
        if m is None:
            continue
        synth = _synth_model_entry(
            game_state, uid, m, int(m["col"]), int(m["row"]),
            level=int(require_key(m, "level")),
        )
        # (id, entrée) et non l'entrée seule : les entrées `units_cache` ne portent pas toutes un
        # champ `id`, et un engagement à conserver doit rester NOMMABLE (messages, journaux).
        held = [
            (str(eid), ce) for eid, ce in enemies
            if unit_entries_within_engagement_zone(synth, ce, ez, metric=metric)
        ]
        if held:
            out[str(mid)] = held
    return out


def _fight_models_keep_start_engagements(
    game_state: Dict[str, Any],
    squad_id: str,
    start_engagements: Mapping[str, List[Tuple[str, Dict[str, Any]]]],
    placements: Mapping[str, Tuple[int, int, int]],
    engagement_zone: int,
) -> bool:
    """True si CHAQUE figurine conserve, à sa position d'arrivée, TOUS ses engagements de départ.

    Miroir exact du contrôle du flux par-figurine (``_fight_pile_in_preview_plan``), appliqué ici à
    une configuration d'ancre (translation rigide du bloc).
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import _synth_model_entry

    metric = engagement_distance_metric(game_state)
    models_cache = require_key(game_state, "models_cache")
    for mid, held in start_engagements.items():
        placement = placements.get(str(mid))
        if placement is None:
            continue  # figurine absente de la configuration candidate (morte entre-temps)
        c, r, lv = placement
        m = models_cache.get(str(mid))
        if m is None:
            continue
        synth = _synth_model_entry(game_state, squad_id, m, int(c), int(r), level=int(lv))
        for _eid, ce in held:
            if not unit_entries_within_engagement_zone(synth, ce, engagement_zone, metric=metric):
                return False
    return True


def _fight_entries_in_engagement_with_any_enemy(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    synths: List[Dict[str, Any]],
) -> bool:
    """« Your unit must be engaged » sur des entrées synthétiques DÉJÀ construites (une par socle).

    Les bâtir coûte une translation rigide et une résolution de plancher par figurine. Les
    appelants qui les réutilisent ensuite (pools d'ancres) passent par ici pour ne les payer
    qu'une fois.
    """
    from engine.spatial_relations import unit_entries_within_engagement_zone, get_engagement_zone, engagement_distance_metric

    ez = get_engagement_zone(game_state)
    metric = engagement_distance_metric(game_state)
    mover_id = str(require_key(unit, "id"))
    mover_player = int(require_key(unit, "player"))
    units_cache = require_key(game_state, "units_cache")
    for _eid, ce in enemy_entries_on_battlefield(units_cache, mover_player, exclude_id=mover_id):
        if any(unit_entries_within_engagement_zone(s, ce, ez, metric=metric) for s in synths):
            return True
    return False


def _fight_prepare_footprint_offsets(
    unit: Dict[str, Any], game_state: Dict[str, Any]
) -> FightFootprintOffsetPair:
    """
    Pré-calcule les offsets d'empreinte pair/impair pour accélérer le BFS de consolidation.

    Retourne ``None`` quand il n'y a PAS de chemin rapide à préparer : plateau legacy
    (``engagement_zone <= 1``) ou socle tenant dans une case (``BASE_SIZE == 1``) — dans ces
    deux cas l'empreinte est le seul hex central et ``_candidate_footprint_fight`` la calcule
    directement. ``None`` ne signifie donc JAMAIS « échec » : aucune erreur n'est rattrapée ici.

    Aucun repli silencieux : l'ancien ``except Exception: cache[key] = None`` avalait le
    ``TypeError`` d'un socle incohérent (BASE_SHAPE/BASE_SIZE) ET le MÉMORISAIT — l'unité
    était alors traitée « sans empreinte rapide » pour toute la partie, sans le moindre
    signal. Il n'apportait rien : le chemin lent (``compute_candidate_footprint`` ->
    ``compute_occupied_hexes``) appelle exactement la même primitive et lève la même erreur,
    simplement plus loin de sa cause.
    """
    cache: Dict[Tuple[str, int], FightFootprintOffsetPair] = game_state.setdefault("_fight_fp_offset_pair_cache", {})
    uid = str(unit["id"])
    orient = int(unit["orientation"])
    cache_key = (uid, orient)
    if cache_key in cache:
        return cache[cache_key]

    from engine.hex_utils import precompute_footprint_offsets, require_base_size

    # Socle lu par la garde partagée (même primitive que les masques de mouvement) : elle
    # NOMME l'unité, là où `precompute_footprint_offsets` ne connaît que la forme et la taille.
    shape = require_key(unit, "BASE_SHAPE")
    bs = require_base_size(
        shape, require_key(unit, "BASE_SIZE"), f"fight footprint unit {uid}"
    )
    from engine.spatial_relations import geometry_is_hex

    if geometry_is_hex(game_state) or bs == 1:
        cache[cache_key] = None
        return None
    off_e, off_o = precompute_footprint_offsets(shape, bs, orient)
    out: FightFootprintOffsetPair = (off_e, off_o)
    cache[cache_key] = out
    return out


def _candidate_footprint_fight(
    center_col: int,
    center_row: int,
    unit: Dict[str, Any],
    game_state: Dict[str, Any],
    offset_pair: FightFootprintOffsetPair,
) -> Set[Tuple[int, int]]:
    if offset_pair is not None:
        off_e, off_o = offset_pair
        offs = off_e if (center_col & 1) == 0 else off_o
        return {(center_col + dc, center_row + dr) for dc, dr in offs}
    return compute_candidate_footprint(center_col, center_row, unit, game_state)


def _fight_fp_has_adjacent_enemy_footprint(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    fp: Set[Tuple[int, int]],
) -> bool:
    """
    Contact **A** strict (empreintes : ``min_distance_between_sets`` ≤ 1).

    Le renvoi qui figurait ici vers un jumeau par-ancre a disparu avec lui le 2026-08-05 (code
    mort). Le contact rond↔rond bord-à-bord se mesure par ``unit_entries_within_engagement_zone``
    (``engine/spatial_relations.py``), primitive unique du moteur.
    """
    return _fight_footprint_has_enemy_hex_contact(game_state, unit, fp)


def _fight_opposing_enemies_exist(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_id_str = str(unit["id"])
    for _uid, _cache_entry in enemy_entries_on_battlefield(
        units_cache, unit_player, exclude_id=unit_id_str
    ):
        return True
    return False


def _ai_select_pile_in_destination(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    pile_dests: List[Tuple[int, int]],
    d_min: int,
    closest_ids: List[str],
) -> Tuple[int, int]:
    """
    Choisit la destination qui minimise la distance au palier d'ennemis les plus proches.

    PERF : empreintes ennemies du palier pré-calculées une fois (pas une lecture cache par destination).
    """
    from engine.hex_utils import min_distance_between_sets

    if not pile_dests:
        raise ValueError("_ai_select_pile_in_destination: empty pile_dests")
    tier_efps: List[Set[Tuple[int, int]]] = []
    for eid in closest_ids:
        # Contrat de sortie du palier. En sauter un faussait le score de la destination choisie
        # par l'IA (une cible du palier disparaissait du tri).
        ce = require_unit_from_cache(
            str(eid), game_state, "_ai_select_pile_in_destination"
        )
        tier_efps.append(entry_footprint(ce))
    best: Optional[Tuple[int, int]] = None
    best_score: Optional[int] = None
    for ac, ar in pile_dests:
        fp = compute_candidate_footprint(ac, ar, unit, game_state)
        tier_scores: List[int] = []
        for efp in tier_efps:
            tier_scores.append(min_distance_between_sets(fp, efp))
        if not tier_scores:
            continue
        m = min(tier_scores)
        if best_score is None or m < best_score:
            best_score = m
            best = (ac, ar)
    return best if best is not None else pile_dests[0]


def _ai_select_fight_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """
    AI target selection for fight phase using RewardMapper system.

    Fight priority (same as shooting): lowest HP, highest threat.
    """
    # Pool vide = bug d'appelant : les 4 sites d'appel gardent déjà le cas en amont
    # (fight_handlers ~3381 `if not targets`, ~5537 `if not valid`, ~6271 `if valid`,
    # w40k_core ~5518 `if targets else None`). L'ancien `return ""` était une sentinelle
    # muette sur une branche morte. Retiré le 2026-07-20 (V11 §0.19.2).
    if not valid_targets:
        raise ValueError(
            f"_ai_select_fight_target appelé avec un pool de cibles VIDE (unit_id={unit_id}) — "
            f"l'appelant doit garder ce cas en amont"
        )

    unit = get_unit_by_id(game_state, unit_id)
    if not unit:
        raise ValueError(f"Unit not found for fight target selection: unit_id={unit_id}")
    
    # Aucun try/except ici : une erreur de config/registry est un BUG, elle doit remonter.
    # L'ancien `except Exception: return valid_targets[0]` avalait les deux require_key et le
    # ValueError de get_model_key, et sa seule trace (add_console_log) est un no-op hors
    # --debug : le ciblage tombait silencieusement sur la première cible du pool. Retiré le
    # 2026-07-20 (V11 §9.4), verrouillé par test_fight_target_selection_no_fallback.py.
    from ai.reward_mapper import RewardMapper

    reward_configs = require_key(game_state, "reward_configs")

    # Get unit type for config lookup
    global _unit_registry_singleton
    if _unit_registry_singleton is None:
        from ai.unit_registry import UnitRegistry
        _unit_registry_singleton = UnitRegistry()
    fighter_unit_type = unit["unitType"]
    fighter_agent_key = _unit_registry_singleton.get_model_key(fighter_unit_type)

    # Get unit-specific config (required)
    unit_reward_config = require_key(reward_configs, fighter_agent_key)

    reward_mapper = RewardMapper(unit_reward_config)

    # Build target list for reward mapper (single lookup per tid)
    # Le pool vient de `units_cache` (_fight_build_valid_target_pool ~L2037) : une cible qui y
    # figure mais manque de `unit_by_id` est une DÉSYNCHRONISATION D'INDEX, donc un bug.
    # L'ancien `if t:` / `if not target: continue` la sautait en silence — si toutes les cibles
    # manquaient, la fonction renvoyait `valid_targets[0]` sans avoir scoré quoi que ce soit.
    # Erreur explicite depuis le 2026-07-20 (V11 §0.19.2).
    resolved: List[Tuple[str, Dict[str, Any]]] = []
    for tid in valid_targets:
        t = get_unit_by_id(game_state, tid)
        if t is None:
            raise ValueError(
                f"Cible {tid!r} du pool de combat absente de unit_by_id "
                f"(désynchronisation units_cache/unit_by_id, unit_id={unit_id})"
            )
        resolved.append((tid, t))
    all_targets = [t for _tid, t in resolved]

    # Fight phase uses same priority logic as shooting — RewardMapper handles both.
    # `max` retient le PREMIER maximum : même sémantique de départage que l'ancienne
    # comparaison `>` stricte, donc sélection STABLE à pool identique (déterminisme exigé
    # par §8.1 — l'assignation de crédit PPO se brouille si l'ordre varie).
    # L'ancienne sentinelle `best_reward = -999999` est retirée : depuis que toute cible
    # non résolue lève, il n'existe plus de cas où aucun candidat n'est scoré (V11 §0.19.3).
    best_target, _best_unit = max(
        resolved,
        key=lambda pair: reward_mapper.get_shooting_priority_reward(
            unit, pair[1], all_targets, False, game_state
        ),
    )
    return best_target


def _fight_end_progression_v10(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Progression joueur / tour après la phase FIGHT V10 (Partie B).

    Appelée depuis `_fight_phase_complete` (queue coherency vide) ET depuis le résolveur
    de désignation coherency (queue drainée, pending_coherency_removal_v11=False).
    Ne doit PAS être appelée plus d'une fois par phase.
    """
    if game_state["current_player"] == 1:
        game_state["current_player"] = 2
        return {
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "command",
            "current_player": 2,
            "units_processed": len(require_key(game_state, "units_fought")),
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 2:
        from engine.game_utils import get_effective_turn_limit
        max_turns = get_effective_turn_limit(game_state)
        if max_turns is not None and (game_state["turn"] + 1) > max_turns:
            state_manager = GameStateManager(require_key(game_state, "config"))
            state_manager.apply_primary_objective_scoring(game_state, "fight")
            game_state["turn_limit_reached"] = True
            game_state["game_over"] = True
            return {
                "phase_complete": True,
                "game_over": True,
                "turn_limit_reached": True,
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
        else:
            game_state["turn"] += 1
            game_state["current_player"] = 1
            return {
                "phase_complete": True,
                "phase_transition": True,
                "next_phase": "command",
                "current_player": 1,
                "new_turn": game_state["turn"],
                "units_processed": len(require_key(game_state, "units_fought")),
                "clear_blinking_gentle": True,
                "reset_mode": "select",
                "clear_selected_unit": True,
                "clear_attack_preview": True
            }
    else:
        raise ValueError(f"Unreachable: current_player={game_state['current_player']}")


def _fight_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete fight phase with player progression and turn management.

    CRITICAL: Fight is the LAST phase. After fight:
    - P0 ->    P1 movement phase
    - P1 ->       increment turn, P0 movement phase

    Partie A (une seule fois) : nettoyage + armement queue coherency.
    Partie B (`_fight_end_progression_v10`) : progression joueur/tour, déclenchée immédiatement
    si la queue est vide, sinon différée jusqu'à résolution de tous les pendings.
    """
    # Clear alternation tracking state
    if "fight_alternating_turn" in game_state:
        del game_state["fight_alternating_turn"]

    # AI_TURN.md COMPLIANCE: Clear fight sub-phase at phase end
    game_state["fight_subphase"] = None

    # Console log
    add_console_log(game_state, "FIGHT PHASE COMPLETE")

    # Normalize current_player for deterministic comparisons
    current_player = require_key(game_state, "current_player")
    try:
        current_player_int = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player_int not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player_int}")
    game_state["current_player"] = current_player_int

    # Etape End of Turn — REGAINING COHERENCY (03.03). Les sièges muets sont résolus
    # immédiatement ; les autres arment une queue → la Partie B est différée.
    auto_removed = end_of_turn_regain_coherency_all_squads(game_state)
    if auto_removed:
        _log_end_of_turn_coherency_removals(game_state, auto_removed)
    if game_state.get("pending_coherency_removal"):
        game_state["pending_coherency_removal_v11"] = False
        return {"phase_complete": False, "awaiting_coherency_removal": True}

    return _fight_end_progression_v10(game_state)

def fight_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Fight phase end - redirects to complete function"""
    return _fight_phase_complete(game_state)

def _fight_build_valid_target_pool(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """
    Build valid fight target pool.

    Valid targets:
    - Enemy units
    - Alive (in units_cache)
    - Within engagement zone (min footprint distance, §3.3/§9.8)

    NO LINE OF SIGHT CHECK (fight doesn't need LoS)
    """
    from engine.spatial_relations import (
        engagement_distance_metric,
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )
    cc_range = get_engagement_zone(game_state)
    metric = engagement_distance_metric(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    unit_entry = units_cache.get(unit_id_str)
    if unit_entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache (dead or absent); cannot build fight target pool")
    unit_player = int(require_key(unit_entry, "player"))

    valid_targets = []

    # Attaquant HORS TABLE (réserves 20.01, attente de déploiement) : il n'est engagé avec
    # personne, donc son pool est VIDE. Réponse de RÈGLE, pas repli — la mesure, elle, est
    # refusée par `entries_in_engagement_zone`. L'observation IA construit ce pool pour toute
    # escouade du camp actif, réserves comprises.
    if not entry_is_on_battlefield(unit_entry):
        return valid_targets

    for target_id, target_entry in enemy_entries_on_battlefield(
        units_cache, unit_player, exclude_id=unit_id_str
    ):
        if not unit_entries_within_engagement_zone(
            unit_entry, target_entry, cc_range, metric=metric):
            continue
        valid_targets.append(target_id)

    return valid_targets


def _model_can_fight_target(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
) -> bool:
    """Eligibilite per-figurine au COMBAT (regle 04.02 — Select Targets / While Fighting).

    La cible doit etre ENGAGED avec la figurine qui porte l arme : on teste si la
    figurine attaquante (empreinte synthetique a sa position) est dans la zone
    d engagement d au moins une figurine de l unite cible. Pas de LoS en melee.

    Le squad_id attaquant est fourni par le moteur (les modeles n ont pas tous le
    champ "squad_id" — on ne le devine donc pas depuis le modele).
    """
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone
    # `declare_attack_model` (shared_utils) a DÉJÀ prouvé la cible vivante — via `squad_models` +
    # `models_cache`, pas via `units_cache`. Un `return False` sur l'absence sortait donc sous le
    # message « hors portee/engagement » : une désynchronisation déguisée en refus de règle.
    target_entry = require_unit_from_cache(
        str(target_squad_id), game_state, "_model_can_fight_target"
    )
    if not attacker_squad_id:
        return False
    if not entry_is_on_battlefield(target_entry):
        return False
    ez = get_engagement_zone(game_state)
    synth = _synth_model_entry(
        game_state, str(attacker_squad_id), attacker_model,
        int(attacker_model["col"]), int(attacker_model["row"]),
        level=int(require_key(attacker_model, "level")),
    )
    return model_entry_can_fight_target(
        game_state, synth, target_entry, ez,
    )


def model_entry_can_fight_target(
    game_state: Dict[str, Any],
    attacker_model_entry: Dict[str, Any],
    target_entry: Dict[str, Any],
    engagement_zone: int,
) -> bool:
    """Coeur de 04.02, sur une empreinte de figurine DEJA construite.

    Extrait de `_model_can_fight_target` (qui en est desormais le wrapper) pour les appelants
    qui possedent deja l'entree synthetique : `_synth_model_entry` reconstruit une empreinte a
    chaque appel, ce qui domine le cout quand on teste N figurines contre M cibles —
    l'observation le fait a CHAQUE step (V11 §9 P3-1, `n_models_engaging`). Mesure : le test
    d'engagement seul coute ~10x moins que le test + la reconstruction.

    ⚠️ C'est le MEME predicat, pas une copie : les deux fonctions partagent ce corps. Le
    dupliquer cote observation l'aurait laisse diverger de la resolution (une metrique differente
    et l'obs annoncerait un volume d'attaques que le combat ne produit pas).

    Le gate vertical §03.04 n'a PAS de paramètre : la primitive l'applique dès que les deux
    entrées portent leurs cartes verticales. C'est ce qui garantit que les deux appelants le
    subissent identiquement — un opt-in aurait pu être oublié d'un seul côté, et l'obs aurait
    annoncé engagées des figurines que la résolution refuse.
    """
    from engine.spatial_relations import engagement_distance_metric, unit_entries_within_engagement_zone

    return unit_entries_within_engagement_zone(
        attacker_model_entry, target_entry, engagement_zone,
        metric=engagement_distance_metric(game_state),
    )


def _model_can_fight_target_with_weapon(
    game_state: Dict[str, Any],
    attacker_model: Dict[str, Any],
    attacker_squad_id: str,
    target_squad_id: str,
    weapon_index: int,
) -> bool:
    """Eligibilite per-arme melee : la fig possede l arme CC `weapon_index` ET est
    engagee avec la cible. Les armes de melee n ont pas de portee : la validite se
    reduit a l engagement (cf. _model_can_fight_target)."""
    weapons = melee_weapons(attacker_model)
    if not (0 <= int(weapon_index) < len(weapons)):
        return False
    if not isinstance(weapons[int(weapon_index)], dict):
        return False
    return _model_can_fight_target(game_state, attacker_model, attacker_squad_id, target_squad_id)


# Contexte de declaration COMBAT : engagement (pas de LoS/portee). Jumeau de
# SHOOT_DECLARE_CTX cote tir. Reutilise le moteur generique declare_attack_*.
FIGHT_DECLARE_CTX = DeclareAttackCtx(
    intents_key="pending_squad_fight_intents",
    selected_weapon_attr="selectedCcWeaponIndex",
    weapons_key="CC_WEAPONS",
    phase_label="fight",
    can_target=_model_can_fight_target,
    can_target_with_weapon=_model_can_fight_target_with_weapon,
)


def squad_declare_fight_model(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    attacker_model_id: str,
    target_squad_id: str,
) -> Dict[str, Any]:
    """Declaration MANUELLE d UNE figurine au COMBAT (flux PvP humain).

    Wrapper fin de declare_attack_model via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_model(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, attacker_model_id, target_squad_id
    )


def squad_declare_fight_weapon(
    game_state: Dict[str, Any],
    attacker_squad_id: str,
    weapon_index: int,
    target_squad_id: str,
) -> List[Dict[str, Any]]:
    """Assigne l arme CC `weapon_index` (niveau escouade) a la cible, au COMBAT.

    Wrapper fin de declare_attack_weapon via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_weapon(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_index, target_squad_id
    )


# ---------------------------------------------------------------------------
# Wrappers COMBAT cible-d abord par arme/quantite/figurine.
# Jumeaux exacts des squad_shoot_* (shared_utils.py) via FIGHT_DECLARE_CTX.
# Aucune logique nouvelle : engagement au lieu de portee/LoS, porte par le CTX.
# ---------------------------------------------------------------------------

def squad_declare_fight_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str,
    weapon_code: str, count: int, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Assigne `count` attaques de l arme CC `weapon_code` (identite) a la cible.

    `only_model_id` (optionnel) : attribution restreinte a CETTE figurine (menu par-fig).
    Wrapper fin de declare_attack_weapon_qty via FIGHT_DECLARE_CTX (engagement).
    """
    return declare_attack_weapon_qty(
        game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, count, target_squad_id,
        only_model_id,
    )


def squad_fight_weapon_qty_max(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Borne du champ count au COMBAT — figs pouvant combattre `weapon_code` sur la cible."""
    return weapon_qty_max(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def squad_undeclare_fight_weapon_qty(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> int:
    """Retire la ligne (weapon_code, cible) au COMBAT — bouton "-"."""
    return undeclare_attack_weapon_qty(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id, only_model_id)


def squad_fight_weapons_for_target(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str,
    only_model_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Menu cible-d abord au COMBAT — armes pouvant viser la cible avec (m, x). Cf. weapons_for_target."""
    return weapons_for_target(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, target_squad_id, only_model_id)


def squad_fight_eligible_models(
    game_state: Dict[str, Any], attacker_squad_id: str, weapon_code: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voile vert au COMBAT — figs pouvant combattre `weapon_code` sur la cible (+ assigned)."""
    return eligible_models_for_weapon(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, weapon_code, target_squad_id)


def squad_fight_toggle_model_weapon(
    game_state: Dict[str, Any], attacker_squad_id: str, model_id: str, weapon_code: str, target_squad_id: str
) -> str:
    """Clic sur fig verte au COMBAT — toggle l attribution de cette fig pour (code, cible)."""
    return toggle_attack_model_weapon(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, model_id, weapon_code, target_squad_id)


def squad_fight_models_status(
    game_state: Dict[str, Any], attacker_squad_id: str, target_squad_id: str
) -> List[Dict[str, Any]]:
    """Voiles vert/gris au COMBAT — état de chaque fig vis-à-vis de la cible (+ ses armes)."""
    return models_status_for_target(game_state, FIGHT_DECLARE_CTX, attacker_squad_id, target_squad_id)


def squad_fight_models_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Armes CC par figurine au COMBAT (indépendant de la cible) — encart jaune au clic-fig."""
    return models_weapons_for_squad(game_state, FIGHT_DECLARE_CTX, attacker_squad_id)


def fight_weapon_eligible_slots(
    game_state: Dict[str, Any],
    squad_id: str,
    target_id: str,
) -> Dict[int, str]:
    """Slots d'armes CC éligibles pour le masque de sélection d'arme (V11 §0.69).

    Retourne `{slot_j: weapon_code}` pour chaque slot de mêlée j dans
    [0, K_WEAPONS_MELEE) où ≥1 figurine en engagement peut déclarer cette arme sur
    `target_id`. L'ordre des slots est celui de `collect_weapon_profiles("CC_WEAPONS")`
    (porteurs décroissants) — même ordonnancement que l'obs melee j (invariant D1 armes).

    ⚠️ `squad_fight_restart_activation` DOIT avoir été appelé avant cette fonction :
    `weapon_qty_max` retourne 0 si l'activation n'est pas démarrée.
    """
    from engine.observation_weapon_profiles import collect_weapon_profiles
    from engine.observation_entities import K_WEAPONS_MELEE as _K

    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive_models = [
        models_cache[mid]
        for mid in squad_models.get(squad_id, [])
        if mid in models_cache
    ]
    profiles = collect_weapon_profiles(alive_models, "CC_WEAPONS")
    result: Dict[int, str] = {}
    for slot_j, (weapon, _) in enumerate(profiles[:_K]):
        code = require_key(weapon, "code")
        if weapon_qty_max(game_state, FIGHT_DECLARE_CTX, squad_id, code, target_id) > 0:
            result[slot_j] = code
    return result


def squad_union_cc_weapons(
    game_state: Dict[str, Any], squad_id: str
) -> List[Dict[str, Any]]:
    """Union des armes CC par-figurine (source du menu combat). Cf. _union_weapons."""
    return _union_weapons(game_state, "CC_WEAPONS", squad_id)


def squad_fight_menu_weapons(
    game_state: Dict[str, Any], attacker_squad_id: str
) -> List[Dict[str, Any]]:
    """Profils CC de l escouade pour le menu combat, avec `can_use` correct (par-figurine).

    usable = AU MOINS une figurine portant le profil est engagee avec AU MOINS une unite
    ennemie (calcule par-fig via _model_can_fight_target_with_weapon). Pas de portee/LoS ni
    d exclusion Close-quarters : la melee n a pas la restriction 10.06 (jumeau simplifie de
    squad_shoot_menu_weapons)."""
    from .shared_utils import init_pending_intents, require_key as _require_key
    models_cache = _require_key(game_state, "models_cache")
    squad_models = _require_key(game_state, "squad_models")
    init_pending_intents(game_state)

    mids = squad_models.get(attacker_squad_id, [])  # get allowed
    player = int(models_cache[mids[0]]["player"]) if mids and mids[0] in models_cache else None
    enemy_sids = _enemy_squad_ids(game_state, player) if player is not None else []

    result: List[Dict[str, Any]] = []
    for idx, w in enumerate(_union_weapons(game_state, "CC_WEAPONS", attacker_squad_id)):
        code = w["code"]
        usable = False
        for mid in mids:
            m = models_cache.get(mid)
            if m is None:
                continue
            weapons = melee_weapons(m)
            local_idx = next(
                (i for i, ww in enumerate(weapons) if isinstance(ww, dict) and ww.get("code") == code),
                None,
            )
            if local_idx is None:
                continue
            if any(
                _model_can_fight_target_with_weapon(game_state, m, attacker_squad_id, sid, local_idx)
                for sid in enemy_sids
            ):
                usable = True
                break
        result.append({"index": idx, "weapon": w, "can_use": usable, "reason": None})
    return result


def _fight_ensure_activation_started(game_state: Dict[str, Any], squad_id: str) -> None:
    """Demarre l activation fight de l escouade si pas deja en cours (idempotent).

    Initialise pending_squad_fight_intents[squad_id] = [] pour accueillir les
    declarations manuelles. Ne reinitialise pas si des declarations existent deja
    (re-activation : on conserve l etat declare)."""
    from .shared_utils import init_pending_intents
    init_pending_intents(game_state)
    if squad_id not in game_state["pending_squad_fight_intents"]:
        squad_fight_unit_activation_start(game_state, squad_id)


def _calculate_wound_target(strength: int, toughness: int) -> int:
    """EXACT COPY from 40k_OLD w40k_engine.py wound calculation"""
    if strength >= toughness * 2:
        return 2
    elif strength > toughness:
        return 3
    elif strength == toughness:
        return 4
    elif strength * 2 <= toughness:
        return 6
    else:
        return 5


# === HELPER FUNCTIONS (Minimal Implementation) ===

# Note: _is_adjacent_to_enemy_within_cc_range is defined at top of file




def is_fights_first(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """
    True si l'unité est une **Fights First unit** (ability 24.13).

    Source du grant V1 : le charge move effectué ce tour confère l'ability
    « jusqu'à la fin du tour » (11.04 AFTER MOVING). On lit donc ``units_charged``
    (alimenté uniquement après un charge move effectué). L'API reste « ability » :
    le jour où l'ability datasheet existe (config/unit_rules.json), il suffira
    d'ajouter ici un ``or _unit_has_rule(unit, "fights_first")``.
    """
    if "units_charged" not in game_state:
        raise KeyError(
            "game_state missing required 'units_charged' field "
            "- charge phase must run before is_fights_first()"
        )
    units_charged = {str(uid) for uid in game_state["units_charged"]}
    return str(require_key(unit, "id")) in units_charged


def fight_ensure_v11_state(game_state: Dict[str, Any]) -> None:
    """
    Initialise (idempotent) les sets de suivi V11 de la phase de combat (§6) :
    - ``units_selected_to_fight`` : « selected to fight » cette phase (12.04) ;
    - ``pile_in_done`` / ``consolidation_done`` : 1 move max/unité par étape groupée.
    Suit le pattern d'init paresseuse de ``units_fought``.
    """
    if "units_selected_to_fight" not in game_state:
        game_state["units_selected_to_fight"] = set()
    if "pile_in_done" not in game_state:
        game_state["pile_in_done"] = set()
    if "consolidation_done" not in game_state:
        game_state["consolidation_done"] = set()


def fight_compute_engaged_snapshot(game_state: Dict[str, Any]) -> Dict[str, bool]:
    """
    Snapshot ``engaged_at_fight_step_start`` (12.04 / 12.06).

    Pour chaque unité vivante : True si engagée (zone d'engagement) avec ≥1 ennemi
    MAINTENANT. À appeler au DÉBUT de l'étape FIGHT (donc APRÈS le pile-in groupé).
    Sert à : éligibilité fight 12.04 (« was engaged at the start of this step ») ET
    overrun 12.06 (« was unengaged at the start of the Fight step » = négation).
    """
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_within_engagement_zone_footprints,
    )

    ez = get_engagement_zone(game_state)
    snapshot: Dict[str, bool] = {}
    for u in require_key(game_state, "units"):
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        snapshot[uid] = unit_within_engagement_zone_footprints(
            game_state, u, engagement_zone=ez, max_distance=ez,
        )
    return snapshot


def _fight_units_engaged_with(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Liste des ids d'unités ennemies actuellement engagées avec ``unit`` (zone d'engagement)."""
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
        engagement_distance_metric,
    )

    ez = get_engagement_zone(game_state)
    metric = engagement_distance_metric(game_state)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    entry = units_cache.get(unit_id_str)
    if entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache; cannot compute engagement")
    unit_player = int(require_key(entry, "player"))
    engaged: List[str] = []
    # Hors table = engagée avec personne (20.01). Même raison que le pool de cibles fight.
    if not entry_is_on_battlefield(entry):
        return engaged
    for eid, ce in enemy_entries_on_battlefield(units_cache, unit_player, exclude_id=unit_id_str):
        if unit_entries_within_engagement_zone(entry, ce, ez, metric=metric):
            engaged.append(str(eid))
    return engaged


def pile_in_targets_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Unités ennemies dont l'empreinte est dans ``pile_in_target_range`` (5" × inches_to_subhex)."""
    from engine.hex_utils import min_distance_between_sets

    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    rng_inches = int(require_key(game_rules, "pile_in_target_range"))
    scale = require_key(game_state, "inches_to_subhex")
    rng = rng_inches * int(scale)
    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(require_key(unit, "id"))
    entry = units_cache.get(unit_id_str)
    if entry is None:
        raise ValueError(f"Unit {unit_id_str} not in units_cache; cannot compute pile-in targets")
    unit_player = int(require_key(entry, "player"))
    within: List[str] = []
    # Hors table : aucune cible de pile-in (20.01), et aucune empreinte à mesurer.
    if not entry_is_on_battlefield(entry):
        return within
    unit_fp = entry_footprint(entry)
    for eid, ce in enemy_entries_on_battlefield(units_cache, unit_player, exclude_id=unit_id_str):
        enemy_fp = entry_footprint(ce)
        if min_distance_between_sets(unit_fp, enemy_fp, max_distance=rng) <= rng:
            within.append(str(eid))
    return within


def pile_in_select_targets_12_03(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    chosen_target_ids: Optional[List[str]] = None,
) -> List[str]:
    """
    BEFORE MOVING (12.03) — sélection des cibles de pile-in :
    - unité **engagée** → toutes les unités ennemies engagées (``chosen_target_ids`` ignoré) ;
    - unité **non engagée** → ``chosen_target_ids`` requis : 1+ unités ennemies dans 5"
      (``pile_in_target_range``), validées ici (choix joueur PvP / heuristique IA en amont).
    """
    engaged = _fight_units_engaged_with(game_state, unit)
    if engaged:
        return engaged
    within = set(pile_in_targets_within_range(game_state, unit))
    if chosen_target_ids is None:
        raise ValueError(
            "pile_in_select_targets_12_03: chosen_target_ids required when unit is unengaged"
        )
    chosen = [str(t) for t in chosen_target_ids]
    if not chosen:
        raise ValueError("pile_in_select_targets_12_03: empty target selection for unengaged unit")
    invalid = [t for t in chosen if t not in within]
    if invalid:
        raise ValueError(
            f"pile_in_select_targets_12_03: targets not enemy units within "
            f"{int(require_key(require_key(game_state, 'config'), 'game_rules')['pile_in_target_range'])}\": {invalid}"
        )
    return chosen


# =====================================================================
# === V11 FIGHT PHASE — ÉLIGIBILITÉS & MACHINE DE SÉLECTION (Bloc 1) ===
# =====================================================================
# Fonctions ADDITIVES PURES (non branchées sur le routage V10 actif).
# Implémentent le cœur règles de l'étape FIGHT V11 (PDF 12.04→12.06) :
# éligibilités, types de fight, et la machine de sélection FF→Remaining.
# Pré-condition d'appel : `engaged_at_fight_step_start` (snapshot 12.04)
# présent dans game_state (pris au début de l'étape FIGHT, cf.
# fight_compute_engaged_snapshot). Câblage du routage = cut-over final.


def _fight_v11_engaged_now(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité est engagée (zone d'engagement) avec ≥1 ennemi MAINTENANT."""
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_within_engagement_zone_footprints,
    )

    ez = get_engagement_zone(game_state)
    return unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=ez, max_distance=ez,
    )


def _fight_v11_charged_this_turn(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si l'unité a fait un charge move ce tour (source units_charged)."""
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field")
    return str(require_key(unit, "id")) in {str(x) for x in game_state["units_charged"]}


def fight_v11_is_pile_in_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité PILE IN groupé (étape n°2, 12.03 — sans le bullet overrun) :
    engagée maintenant OU a fait un charge move ce tour.
    """
    return _fight_v11_engaged_now(game_state, unit) or _fight_v11_charged_this_turn(game_state, unit)


def fight_v11_is_eligible_to_fight(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité FIGHT 12.04 : pas déjà « selected to fight » cette phase ET
    (engagée maintenant OU engagée au début de l'étape FIGHT OU a chargé ce tour).
    **Indépendant de la présence de cibles** (cas overrun : a chargé, cible détruite).
    """
    uid = str(require_key(unit, "id"))
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    if uid in selected:
        return False
    if _fight_v11_engaged_now(game_state, unit):
        return True
    snapshot = require_key(game_state, "engaged_at_fight_step_start")
    if not isinstance(snapshot, dict):
        raise TypeError("game_state['engaged_at_fight_step_start'] must be a dict")
    if snapshot.get(uid, False):
        return True
    return _fight_v11_charged_this_turn(game_state, unit)


def fight_v11_is_overrun_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité OVERRUN fight 12.06 : unengaged maintenant, OU était UNengaged au
    début de l'étape FIGHT (négation du snapshot) et est devenue engagée pendant la phase.
    """
    engaged_now = _fight_v11_engaged_now(game_state, unit)
    if not engaged_now:
        return True
    snapshot = require_key(game_state, "engaged_at_fight_step_start")
    was_engaged_at_start = bool(snapshot.get(str(require_key(unit, "id")), False))
    return (not was_engaged_at_start) and engaged_now


def fight_v11_is_normal_fight_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Éligibilité NORMAL fight 12.05 : l'unité est engagée."""
    return _fight_v11_engaged_now(game_state, unit)


def fight_v11_is_consolidation_eligible(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Éligibilité CONSOLIDATION 12.08 : l'unité « was eligible to fight this phase »
    (≈ a été sélectionnée, cf. décision plan §6) ET est vivante.
    """
    uid = str(require_key(unit, "id"))
    if not is_unit_alive(uid, game_state):
        return False
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    return uid in selected


def fight_v11_eligible_unit_ids(
    game_state: Dict[str, Any],
    player: int,
    *,
    fights_first_only: bool,
) -> List[str]:
    """Ids des unités vivantes de ``player`` éligibles à combattre (12.04), filtrées FF si demandé."""
    player = int(player)
    out: List[str] = []
    for u in require_key(game_state, "units"):
        if int(require_key(u, "player")) != player:
            continue
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        # HORS TABLE (réserves 20.01) : une unité qui n'est pas sur le champ de bataille ne
        # combat pas. Elle n'est de toute façon engagée avec personne (empreinte vide), mais le
        # dire ici évite de faire reposer une règle sur un effet de bord géométrique.
        if not entry_is_on_battlefield(require_key(game_state, "units_cache")[uid]):
            continue
        if not fight_v11_is_eligible_to_fight(game_state, u):
            continue
        if fights_first_only and not is_fights_first(u, game_state):
            continue
        out.append(uid)
    return out


def _fight_v11_register_selection(game_state: Dict[str, Any], uid: str) -> None:
    """
    Enregistre une unité « selected to fight » (12.04) et passe la main à l'adversaire
    (alternance par unité : « players alternate selecting one friendly unit »). Si l'autre
    joueur n'a plus d'unité éligible, ``fight_v11_advance_selection`` rebascule
    automatiquement vers le sélecteur courant. À appeler au moment de la sélection
    EFFECTIVE (pas dans advance_selection, qui doit rester idempotent pour le peek/PvP).
    """
    uid = str(uid)
    game_state["units_selected_to_fight"].add(uid)
    game_state.setdefault("units_fought", set()).add(uid)
    selector = game_state.get("fight_selector")
    if selector in (1, 2):
        game_state["fight_selector"] = 3 - selector


def fight_v11_advance_selection(game_state: Dict[str, Any]) -> Optional[str]:
    """
    Machine de sélection 12.04 (exhaustive). Détermine l'unité que le sélecteur
    courant doit sélectionner ensuite, en mettant à jour ``fight_step`` /
    ``fight_selector`` (handoff). Retourne l'id de l'unité, ou None quand l'étape
    FIGHT est terminée. Ne marque PAS « selected to fight » (l'appelant le fait à
    la sélection effective).

    Pré-conditions : ``current_player``, ``fight_step`` ∈ {"fights_first","remaining"},
    ``fight_selector`` ∈ {1,2}, snapshot ``engaged_at_fight_step_start`` présents.
    """
    active = int(require_key(game_state, "current_player"))
    step = require_key(game_state, "fight_step")
    selector = int(require_key(game_state, "fight_selector"))
    if step not in ("fights_first", "remaining"):
        raise ValueError(f"Invalid fight_step: {step!r}")
    if selector not in (1, 2):
        raise ValueError(f"Invalid fight_selector: {selector!r}")

    # Retour à Resolve Fights First (12.04) : si des unités FF redeviennent
    # éligibles pendant Remaining → re-sélecteur = joueur actif (inatteignable
    # tant que FF = charge seule, mais implémenté pour conformité).
    if step == "remaining":
        if (
            fight_v11_eligible_unit_ids(game_state, active, fights_first_only=True)
            or fight_v11_eligible_unit_ids(game_state, 3 - active, fights_first_only=True)
        ):
            step = "fights_first"
            selector = active

    # Boucle de transition (bornée : ff→remaining une fois, handoff sélecteur ≤2).
    for _ in range(8):
        if step == "fights_first":
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=True)
            if mine:
                game_state["fight_step"] = step
                game_state["fight_selector"] = selector
                return mine[0]
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=True)
            if theirs:
                selector = 3 - selector  # l'autre joueur sélectionne
                continue
            # Plus aucune FF des deux côtés → Remaining, ce même joueur sélectionne.
            step = "remaining"
            continue
        else:  # remaining
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=False)
            if mine:
                game_state["fight_step"] = step
                game_state["fight_selector"] = selector
                return mine[0]
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=False)
            if theirs:
                selector = 3 - selector
                continue
            # Plus aucune unité éligible → fin de l'étape FIGHT.
            game_state["fight_step"] = step
            game_state["fight_selector"] = selector
            return None
    raise RuntimeError("fight_v11_advance_selection: transition loop did not converge")


# =====================================================================
# === V11 FIGHT PHASE — CONSOLIDATION : cascade 3 modes (Bloc 5) ======
# =====================================================================
# Fonctions ADDITIVES PURES (non branchées). Cascade obligatoire 12.08 :
# Ongoing (engagée) → Engaging (ennemi dans 3") → Objective (objectif dans 3").
# Portées en pouces converties via inches_to_subhex.


def _fight_v11_enemies_within_range(
    game_state: Dict[str, Any], unit: Dict[str, Any], range_inches: int
) -> List[str]:
    """Ids des unités ennemies dont l'empreinte est dans ``range_inches`` (× inches_to_subhex)."""
    from engine.hex_utils import min_distance_between_sets

    scale = int(require_key(game_state, "inches_to_subhex"))
    rng = int(range_inches) * scale
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None:
        raise ValueError(f"Unit {uid} not in units_cache; cannot compute range query")
    up = int(require_key(entry, "player"))
    out: List[str] = []
    # Hors table : aucun ennemi « à portée » (20.01), et aucune empreinte à mesurer.
    if not entry_is_on_battlefield(entry):
        return out
    ufp = entry_footprint(entry)
    for eid, ce in enemy_entries_on_battlefield(units_cache, up, exclude_id=uid):
        efp = entry_footprint(ce)
        if min_distance_between_sets(ufp, efp, max_distance=rng) <= rng:
            out.append(str(eid))
    return out


def _fight_v11_objectives_within_range(
    game_state: Dict[str, Any], unit: Dict[str, Any], range_inches: int
) -> List[Any]:
    """Ids des objectifs dont la zone de contrôle est dans ``range_inches`` de l'unité."""
    from engine.hex_utils import min_distance_between_sets

    scale = int(require_key(game_state, "inches_to_subhex"))
    rng = int(range_inches) * scale
    units_cache = require_key(game_state, "units_cache")
    uid = str(require_key(unit, "id"))
    entry = units_cache.get(uid)
    if entry is None:
        raise ValueError(f"Unit {uid} not in units_cache; cannot compute objective range")
    out: List[Any] = []
    # Hors table : ne contrôle et n'approche aucun objectif (cf. `entry_is_on_battlefield`).
    if not entry_is_on_battlefield(entry):
        return out
    ufp = entry_footprint(entry)
    for oid, hexes in objective_hex_zones(game_state):
        if min_distance_between_sets(ufp, hexes, max_distance=rng) <= rng:
            out.append(oid)
    return out


def fight_v11_consolidation_mode(game_state: Dict[str, Any], unit: Dict[str, Any]) -> Optional[str]:
    """
    Cascade obligatoire 12.08 (mode imposé) :
    - ``"ongoing"``   : l'unité est engagée ;
    - ``"engaging"``  : sinon, 1+ unités ennemies dans ``consolidation_trigger_range`` (3") ;
    - ``"objective"`` : sinon, 1+ objectifs dans 3" ;
    - ``None``        : aucune branche applicable (pas de consolidation possible).
    """
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    if _fight_v11_engaged_now(game_state, unit):
        return "ongoing"
    if _fight_v11_enemies_within_range(game_state, unit, trig):
        return "engaging"
    if _fight_v11_objectives_within_range(game_state, unit, trig):
        return "objective"
    return None


def fight_v11_engaging_triggered_unit_ids(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[str]:
    """
    Engaging consolidation (12.08 AFTER) : ennemis engagés avec l'unité (après le move)
    non encore « selected to fight » cette phase → l'adversaire devra les sélectionner
    et ils combattent in-place. Retourne ces ids.
    """
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    return [eid for eid in _fight_units_engaged_with(game_state, unit) if eid not in selected]


# =====================================================================
# === V11 FIGHT PHASE — ORCHESTRATION (drivers, Blocs 1/2/5) ==========
# =====================================================================
# Drivers ADDITIFS PURS (non branchés sur execute_action). Pilotent la
# séquence des 5 étapes V11 (12.01→12.09). Le flip des points d'entrée
# (execute_action/fight_phase_start) = cut-over final.


def _fight_v11_log(game_state: Dict[str, Any], message: str) -> None:
    """Log V11 fight (console_logs + terminal serveur). Trace le flux pile_in→fight→consolidate.

    Écriture conditionnée à debug_mode (PvP : W40K_DEBUG=true ; training : --debug), comme
    add_console_log. Sans ce garde, le training écrit une ligne par fight_phase_start sur stderr.
    """
    if not game_state.get("debug_mode", False):
        return
    msg = f"[FIGHT V11] {message}"
    add_console_log(game_state, msg)
    # safe_print est désactivé (no-op) → écriture directe sur stderr pour visibilité terminal.
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def fight_v11_start(game_state: Dict[str, Any]) -> None:
    """
    START OF FIGHT PHASE (12.01) → entre dans l'étape PILE IN (12.02).
    Réinitialise les états de suivi V11 de la phase et positionne la sous-phase.
    """
    enter_phase(game_state, "fight")
    if "units_fought" not in game_state:
        game_state["units_fought"] = set()
    if "units_charged" not in game_state:
        raise KeyError("game_state missing required 'units_charged' field at fight_v11_start")
    game_state["units_selected_to_fight"] = set()
    game_state["pile_in_done"] = set()
    game_state["consolidation_done"] = set()
    game_state.pop("engaged_at_fight_step_start", None)
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    game_state["fight_subphase"] = "pile_in"


def fight_v11_enter_fight_step(game_state: Dict[str, Any]) -> None:
    """
    Transition PILE IN → FIGHT (étape 3). Prend le snapshot
    ``engaged_at_fight_step_start`` (APRÈS le pile-in groupé) et initialise la
    machine de sélection 12.04 (Resolve Fights First, sélecteur = joueur actif).
    """
    game_state["engaged_at_fight_step_start"] = fight_compute_engaged_snapshot(game_state)
    game_state["fight_subphase"] = "fight"
    game_state["fight_step"] = "fights_first"
    game_state["fight_selector"] = int(require_key(game_state, "current_player"))
    _fight_v11_log(
        game_state,
        f"PILE IN terminé → étape FIGHT (snapshot engagés="
        f"{sorted(k for k, v in game_state['engaged_at_fight_step_start'].items() if v)}, "
        f"selector=P{game_state['fight_selector']})",
    )


def fight_v11_enter_consolidate(game_state: Dict[str, Any]) -> None:
    """Transition FIGHT → CONSOLIDATE (étape 4)."""
    game_state["fight_subphase"] = "consolidate"
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    _fight_v11_log(game_state, "FIGHT terminé → étape CONSOLIDATE")


def _fight_v11_grouped_step_eligible(
    game_state: Dict[str, Any], subphase: str, player: int
) -> List[str]:
    """Unités vivantes de ``player`` éligibles pour l'étape groupée ``subphase``, non encore traitées."""
    if subphase == "pile_in":
        done = {str(x) for x in game_state.get("pile_in_done", set())}
    elif subphase == "consolidate":
        done = {str(x) for x in game_state.get("consolidation_done", set())}
    else:
        raise ValueError(f"_fight_v11_grouped_step_eligible: bad subphase {subphase!r}")
    player = int(player)
    out: List[str] = []
    for u in require_key(game_state, "units"):
        if int(require_key(u, "player")) != player:
            continue
        uid = str(require_key(u, "id"))
        if not is_unit_alive(uid, game_state):
            continue
        # HORS TABLE — JUMEAU de `fight_v11_eligible_unit_ids`, qui porte la meme garde.
        # AUCUN EFFET OBSERVABLE AUJOURD'HUI, et c'est verifie, pas suppose : appeles sur une
        # unite a la sentinelle, `fight_v11_is_pile_in_eligible` et
        # `fight_v11_is_consolidation_eligible` rendent deja False (mesure du 2026-08-05). Cette
        # ligne est donc INVERROUILLABLE par un test — inutile d'en chercher un, il serait vert
        # avec ou sans elle.
        # Elle reste parce que ce False vient d'un EFFET DE BORD geometrique (empreinte vide), pas
        # d'une regle : 12.03/12.08 portent sur les figurines sur le champ de bataille, et le dire
        # ici evite que la regle depende de la geometrie du jour. L'asymetrie avec le jumeau etait
        # par ailleurs exactement ce qui rend ce genre d'oubli invisible.
        if not entry_is_on_battlefield(require_key(game_state, "units_cache")[uid]):
            continue
        if uid in done:
            continue
        if subphase == "pile_in":
            if fight_v11_is_pile_in_eligible(game_state, u):
                out.append(uid)
        else:
            if fight_v11_is_consolidation_eligible(game_state, u):
                out.append(uid)
    return out


def fight_v11_grouped_next(
    game_state: Dict[str, Any], subphase: str
) -> Optional[Tuple[int, List[str]]]:
    """
    Étape groupée (PILE IN 12.02 / CONSOLIDATE 12.07) : joueur **actif d'abord**
    (toutes ses unités éligibles non traitées), puis l'adverse. Retourne
    ``(player, [unit_ids])`` pour le tour de groupe courant, ou ``None`` quand les
    deux camps ont épuisé leurs unités éligibles (→ transition d'étape).
    « Skip » = marquer l'unité dans le set ``*_done`` sans déplacement.
    """
    if subphase not in ("pile_in", "consolidate"):
        raise ValueError(f"fight_v11_grouped_next: bad subphase {subphase!r}")
    active = int(require_key(game_state, "current_player"))
    mine = _fight_v11_grouped_step_eligible(game_state, subphase, active)
    if mine:
        return (active, mine)
    theirs = _fight_v11_grouped_step_eligible(game_state, subphase, 3 - active)
    if theirs:
        return (3 - active, theirs)
    return None


def fight_v11_current_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    Liste NON-MUTANTE des unités actionnables dans la sous-phase FIGHT V11 courante
    (pour observation_builder / action_decoder / masking). Miroir lecture-seule des
    drivers : grouped_next pour pile_in/consolidate, machine de sélection 12.04 pour fight.
    """
    sub = game_state.get("fight_subphase")
    if sub in ("pile_in", "consolidate"):
        nxt = fight_v11_grouped_next(game_state, sub)
        return list(nxt[1]) if nxt else []
    if sub == "fight":
        active = int(require_key(game_state, "current_player"))
        step = game_state.get("fight_step") or "fights_first"
        selector = int(game_state.get("fight_selector") or active)
        if step == "remaining" and (
            fight_v11_eligible_unit_ids(game_state, active, fights_first_only=True)
            or fight_v11_eligible_unit_ids(game_state, 3 - active, fights_first_only=True)
        ):
            step, selector = "fights_first", active
        for _ in range(8):
            ff = step == "fights_first"
            mine = fight_v11_eligible_unit_ids(game_state, selector, fights_first_only=ff)
            if mine:
                return mine
            theirs = fight_v11_eligible_unit_ids(game_state, 3 - selector, fights_first_only=ff)
            if theirs:
                selector = 3 - selector
                continue
            if ff:
                step = "remaining"
                continue
            return []
        return []
    return []


def _fight_v11_end_progression(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Progression joueur / tour après la phase FIGHT V11 (Partie B).

    Appelée depuis `_fight_v11_phase_complete` (queue vide) ET depuis le résolveur de
    désignation coherency (queue drainée, pending_coherency_removal_v11=True).
    Inclut 20.04 (réserves stratégiques). Ne doit pas être appelée plus d'une fois.
    """
    current_player = int(require_key(game_state, "current_player"))
    if current_player not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player}")
    units_processed = len(game_state.get("units_selected_to_fight", set()))

    from engine.phase_handlers.movement_handlers import STRATEGIC_RESERVES_LAST_ROUND
    if current_player == 2 and int(require_key(game_state, "turn")) == STRATEGIC_RESERVES_LAST_ROUND:
        from engine.w40k_core import destroy_unarrived_strategic_reserves
        destroyed_units = destroy_unarrived_strategic_reserves(game_state)
        if destroyed_units:
            destroyed_by_player = require_key(game_state, "_reserves_destroyed_turn3")
            for unit in destroyed_units:
                destroyed_by_player[int(require_key(unit, "player"))] += 1
            from engine.game_utils import get_controlled_player
            controlled = get_controlled_player(game_state)
            offered = require_key(game_state, "_ingress_offered")
            declined_ids = {squad_id for player, squad_id, _turn in offered if player == controlled}
            wasted = sum(
                1 for unit in destroyed_units
                if int(require_key(unit, "player")) == controlled
                and str(require_key(unit, "id")) in declined_ids
            )
            if wasted:
                game_state["_pending_reserves_wasted"] = (
                    require_key(game_state, "_pending_reserves_wasted") + wasted
                )

    if current_player == 1:
        game_state["current_player"] = 2
        return {
            "phase_complete": True, "phase_transition": True, "next_phase": "command",
            "current_player": 2, "units_processed": units_processed,
            "clear_blinking_gentle": True, "reset_mode": "select",
            "clear_selected_unit": True, "clear_attack_preview": True,
        }
    # current_player == 2
    from engine.game_utils import get_effective_turn_limit
    max_turns = get_effective_turn_limit(game_state)
    if max_turns is not None and (game_state["turn"] + 1) > max_turns:
        state_manager = GameStateManager(require_key(game_state, "config"))
        state_manager.apply_primary_objective_scoring(game_state, "fight")
        game_state["turn_limit_reached"] = True
        game_state["game_over"] = True
        return {
            "phase_complete": True, "game_over": True, "turn_limit_reached": True,
            "units_processed": units_processed, "clear_blinking_gentle": True,
            "reset_mode": "select", "clear_selected_unit": True, "clear_attack_preview": True,
        }
    game_state["turn"] += 1
    game_state["current_player"] = 1
    return {
        "phase_complete": True, "phase_transition": True, "next_phase": "command",
        "current_player": 1, "new_turn": game_state["turn"], "units_processed": units_processed,
        "clear_blinking_gentle": True, "reset_mode": "select",
        "clear_selected_unit": True, "clear_attack_preview": True,
    }


def _fight_v11_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fin de phase FIGHT V11 (12.09) → progression joueur / tour (Fight = dernière phase).
    Sémantique identique à ``_fight_phase_complete`` mais SANS les pools V10.

    Partie A (une seule fois) : nettoyage + armement queue coherency.
    Partie B (`_fight_v11_end_progression`) : 20.04 + progression joueur/tour.
    """
    game_state["fight_subphase"] = None
    game_state["fight_step"] = None
    game_state["fight_selector"] = None
    game_state["fight_eligible_units"] = []
    game_state["active_fight_unit"] = None
    if "pending_squad_fight_intents" in game_state:
        game_state["pending_squad_fight_intents"] = {}
    add_console_log(game_state, "FIGHT PHASE COMPLETE (V11)")

    # Etape End of Turn — REGAINING COHERENCY (03.03). Les sièges muets sont résolus
    # immédiatement ; les autres arment une queue → la Partie B est différée.
    auto_removed = end_of_turn_regain_coherency_all_squads(game_state)
    if auto_removed:
        _log_end_of_turn_coherency_removals(game_state, auto_removed)
    if game_state.get("pending_coherency_removal"):
        game_state["pending_coherency_removal_v11"] = True
        return {"phase_complete": False, "awaiting_coherency_removal": True}

    return _fight_v11_end_progression(game_state)


def _fight_v11_resolve_attacks(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    config: Dict[str, Any],
    *,
    preferred_target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Résout les attaques de mêlée d'une unité « selected to fight » via le moteur
    d'allocation par-figurine (groupes 05.03/05.04, T bodyguard 19.02, save par figurine
    allouée). Convergence §9.4b-2 : remplace l'ancien résolveur pool
    (``_execute_fight_attack_sequence``, cible = pool de PV homogène).

    Sélection de cible auto (ou ``preferred_target_id``), puis déclaration per-figurine
    (``squad_declare_fight`` : arme CC auto par figurine — 04.01) et allocation headless
    (défenseur non-humain garanti en mode auto → ``auto_decider``). Retourne la liste des
    ``attack_result`` (1 par blessure infligée), adaptée depuis le summary du moteur
    groupes (``target_died``/``damage``/ids consommés par le reward_calculator et
    l'inférence ``unitId`` de w40k_core). Liste vide = fight « à vide ».
    """
    unit_id = str(require_key(unit, "id"))
    if not (melee_weapons(unit) or []):
        return []

    targets = _fight_build_valid_target_pool(game_state, unit)
    if not targets:
        return []
    tid = preferred_target_id if (preferred_target_id in targets) else _ai_select_fight_target(
        game_state, unit_id, targets
    )
    if get_unit_by_id(game_state, tid) is None:
        return []

    # Déclaration per-figurine + allocation via le moteur groupes (jumeau du chemin
    # training w40k_core). Le hook FIGHT_CTX.on_unit_destroyed retire la cible morte des
    # pools de combat (équivalent de l'ancien _remove_dead_unit_from_fight_pools).
    squad_fight_restart_activation(game_state, unit_id)
    squad_declare_fight(game_state, unit_id, tid)
    alloc = build_manual_fight_allocation(game_state, unit_id)
    if not alloc.get("done"):
        raise RuntimeError(
            f"_fight_v11_resolve_attacks: allocation combat non terminée en auto pour "
            f"unité {unit_id} (défenseur non-IA ?) — action={alloc.get('action')}"
        )
    summary = alloc["shoot_result"]
    return [
        {
            "attackerId": unit_id,
            "shooterId": unit_id,
            "targetId": str(ev["target_squad_id"]),
            "target_died": bool(ev["destroyed"]),
            "damage": int(ev["damage"]),
        }
        for ev in require_key(summary, "events")
    ]


def fight_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:  # noqa: F811 (V11 override of V10)
    """
    START OF FIGHT PHASE V11 (12.01) — override de la version V10.
    Initialise les états V11 et entre dans l'étape PILE IN. Si aucune unité n'est
    éligible à aucune étape, termine la phase immédiatement.
    """
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist at fight_phase_start (should be built at reset)")
    fight_v11_start(game_state)
    add_console_log(game_state, "FIGHT PHASE START (V11)")
    # Phase vide : aucune unité engagée ni ayant chargé → rien à résoudre à aucune étape
    # (pile-in/fight/consolidate) → compléter immédiatement (progression joueur/tour).
    any_actionable = any(
        is_unit_alive(str(require_key(u, "id")), game_state)
        and (_fight_v11_engaged_now(game_state, u) or _fight_v11_charged_this_turn(game_state, u))
        for u in require_key(game_state, "units")
    )
    if not any_actionable:
        _fight_v11_log(game_state, "Aucune unité engagée/chargée → phase FIGHT vide, complétion immédiate")
        return _fight_v11_phase_complete(game_state)

    if not _is_fight_auto_execution_allowed(game_state):
        # Manuel (PvP) : entre dans l'étape PILE IN interactive. _fight_v11_manual_state
        # n'auto-présente aucune unité : il expose le pool cliquable (fight_eligible_units,
        # active_fight_unit=None) ; le pile-in lui-même est par-figurine (pile_in_model_move).
        _fight_v11_log(game_state, "START (manuel) → étape PILE IN interactive")
        _ok, state = _fight_v11_manual_state(game_state)
        out = dict(state)
        out["phase_initialized"] = True
        return out

    # Auto (PvE/gym) : reste en PILE IN, _fight_v11_auto_step gère les moves.
    game_state["fight_eligible_units"] = fight_v11_current_pool(game_state)
    game_state["active_fight_unit"] = None
    _fight_v11_log(
        game_state,
        f"START → étape PILE IN (éligibles pile-in courants={game_state['fight_eligible_units']})",
    )
    return {"phase_initialized": True, "fight_subphase": "pile_in", "phase_complete": False}


def _fight_v11_auto_pile_in(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Pile-in groupé AUTO — par-figurine (fight_pile_in_plan). Marque pile_in_done."""
    uid = str(require_key(unit, "id"))
    try:
        from .shared_utils import fight_pile_in_plan, commit_move
        plan = fight_pile_in_plan(game_state, uid)
        if plan is not None:
            commit_move(plan, game_state, "pile_in")
    finally:
        game_state["pile_in_done"].add(uid)


def _fight_v11_auto_consolidate(game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Consolidation AUTO (V1) : skip (consolidation est OPTIONNELLE, 12 encart) — choix
    légal et conservateur. Marque consolidation_done. La consolidation auto effective
    (3 modes + déclencheur Engaging, décision #7) est affinée avec l'UI (Bloc front).
    """
    game_state["consolidation_done"].add(str(require_key(unit, "id")))


def _fight_v11_auto_step(game_state: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Une activation V11 par appel (granularité V10), résolution automatique (IA/gym/PvE)."""
    for _ in range(6):
        sub = require_key(game_state, "fight_subphase")
        if sub == "pile_in":
            nxt = fight_v11_grouped_next(game_state, "pile_in")
            if nxt is None:
                fight_v11_enter_fight_step(game_state)
                continue
            uid = nxt[1][0]
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for pile-in")
            _fight_v11_auto_pile_in(game_state, u, config)
            return True, {"action": "pile_in", "phase": "fight", "unitId": uid,
                          "fight_subphase": "pile_in", "waiting_for_player": False}
        if sub == "fight":
            uid = fight_v11_advance_selection(game_state)
            if uid is None:
                fight_v11_enter_consolidate(game_state)
                continue
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for fight")
            _fight_v11_register_selection(game_state, uid)
            overrun = (
                fight_v11_is_overrun_eligible(game_state, u)
                and not _fight_v11_engaged_now(game_state, u)
            )
            if overrun:
                from .shared_utils import _fight_overrun_pile_in_plan, commit_move
                _ov_plan = _fight_overrun_pile_in_plan(game_state, uid)
                if _ov_plan is not None:
                    commit_move(_ov_plan, game_state, "pile_in")
            results = _fight_v11_resolve_attacks(game_state, u, config)
            return True, {"action": "combat", "phase": "fight", "unitId": uid,
                          "fight_subphase": "fight", "all_attack_results": results,
                          "fight_type": "overrun" if overrun else "normal",
                          "waiting_for_player": False}
        if sub == "consolidate":
            nxt = fight_v11_grouped_next(game_state, "consolidate")
            if nxt is None:
                return True, _fight_v11_phase_complete(game_state)
            uid = nxt[1][0]
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Unit {uid} missing for consolidate")
            _fight_v11_auto_consolidate(game_state, u, config)
            return True, {"action": "consolidation", "phase": "fight", "unitId": uid,
                          "fight_subphase": "consolidate", "waiting_for_player": False}
        return True, _fight_v11_phase_complete(game_state)
    raise RuntimeError("_fight_v11_auto_step did not converge")


def _fight_fig_effective_level(entry: Dict[str, Any], model_id: str) -> int:
    """Niveau EFFECTIF (étage) d'une figurine d'une unité, lu dans le cache unité.

    ``level_by_model`` (source par-figurine, §2.5) prime ; repli sur le niveau d'unité. Sert au
    filtrage des collisions par étage en pile-in/consolidation (superposition inter-étage, §13.06).
    """
    lbm = entry.get("level_by_model")
    if lbm and model_id in lbm:
        return int(lbm[model_id])
    return int(entry.get("level", 0))  # get allowed (champ optionnel : level absent = sol)


def _fight_model_climb_reachable_floor_cells(*args: Any, **kwargs: Any) -> List[Tuple[int, int]]:
    """Wrapper lazy vers le reachable d'étage de la phase move (source unique du coût vertical).

    Import différé pour éviter tout cycle au chargement du module (movement_handlers ↔ fight_handlers).
    """
    from engine.phase_handlers.movement_handlers import _model_climb_reachable_floor_cells
    return _model_climb_reachable_floor_cells(*args, **kwargs)


def _fight_pile_in_build_model_pool(
    game_state: Dict[str, Any],
    model_id: str,
    closest_tier_ids: List[str],
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    view_level: int = 0,
) -> Dict[str, List[List[int]]]:
    """Pool de destinations PAR-FIGURINE pour le pile-in (12.03, move par-figurine).

    BFS d'UNE figurine du squad dans le budget fixe de 3" (× ``inches_to_subhex``), sans
    traverser murs ni figs (ennemies, alliées, coéquipières). ``provisional_plan``
    ({model_id: (col, row[, level])}) remplace les positions des coéquipières déjà posées dans le
    plan UI (recompute temps réel). ``closest_tier_ids`` = unité(s) ennemie(s) la/les plus proche(s)
    de l'ESCOUADE (palier WHILE commun à toutes les figs, cf. ``pile_in_move_destinations_12_03``).

    ``view_level`` (étages, §13.06) : niveau de VUE UI. 0 = plan sol (comportement historique
    inchangé). >= 1 = destinations sur le plancher de ce niveau, atteignables avec le coût vertical
    (source unique move : ``reachable_multilevel_field`` via ``_model_climb_reachable_floor_cells``),
    seedé au niveau EFFECTIF courant du mover → une fig déjà en hauteur reste sur son étage.

    WHILE MOVING (12.03) : chaque destination doit finir l'empreinte du socle **strictement plus
    proche** du palier le plus proche qu'à son départ. Les contraintes AFTER au niveau unité
    (escouade engagée, engagements conservés) et la cohésion sont vérifiées au commit, pas ici.

    Retour : {"closer": [[col,row],...], "engaged": [[col,row],...]} (engaged ⊆ closer ; engaged =
    le socle finit à <= EZ d'au moins une cible du palier). Lecture pure.
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _candidate_footprint_charge,
        _charge_model_socle,
    )
    from engine.hex_utils import footprints_overlap, Socle

    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(f"_fight_pile_in_build_model_pool: model {model_id} not in models_cache")
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    empty: Dict[str, List[List[int]]] = {"closer": [], "engaged": []}
    if not unit:
        return empty

    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    units_cache = require_key(game_state, "units_cache")
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (champ optionnel : board sans terrain)
    _view_level = int(view_level or 0)

    closest = {str(t) for t in closest_tier_ids}
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    from engine.terrain_utils import floor_levels_present, low_clearance_ground_hexes
    from .shared_utils import build_enemy_occupied_positions_set
    # Obstacles au SOL filtrés par NIVEAU (miroir move) : seuls les ennemis au niveau 0 bloquent le
    # sol — un ennemi en hauteur ne gêne pas (superposition inter-étage §13.06). ``_low_clear`` =
    # clairance verticale (§13.06/§2.11 : une fig trop haute ne peut finir/passer sous un plancher bas).
    _enemy_ground = build_enemy_occupied_positions_set(game_state, current_player=player, level=0)
    # Hauteur de LA FIGURINE qui bouge, jumeau du move : le pool est
    # par-figurine, et un personnage attaché plus haut ne passe pas là où passe la troupe.
    _low_clear = low_clearance_ground_hexes(terrain_areas, model, unit)
    # Bloqueurs (ennemis + autres unités amies) → collision par TEST EUCLIDIEN officiel
    # (footprints_overlap), un socle PAR FIGURINE à sa base RÉELLE (miroir consolidation). Le test
    # par cellules (cand_fp & occupied) sous-estimait le disque et rejetait des socles tangents.
    # Chaque socle est étiqueté de son niveau EFFECTIF : une fig d'un autre étage ne gêne pas
    # (superposition inter-étage, §13.06, miroir move par-figurine).
    blocker_socles: List[Tuple[int, Any]] = []
    for eid, entry in entries_on_battlefield(units_cache):
        cells = set(entry_footprint(entry))
        if int(entry["player"]) != player:
            if str(eid) in closest:
                target_entries.append(entry)
                target_fps.append(cells)
        if str(eid) == squad_id:
            continue  # coéquipières traitées à part (positions provisoires)
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for _bmid, (mc, mr) in by_model.items():
                _bm_entry = models_cache.get(str(_bmid))
                if _bm_entry is None:
                    continue
                # Empreinte COMPLÈTE par figurine (même convention que le mover/sœurs via
                # _charge_model_socle) : sans ça, un blocker à base non-ronde n'occupait que son
                # hex central (fp={(mc,mr)}) → superposition partielle permise (méthode empreinte).
                blocker_socles.append((
                    _fight_fig_effective_level(entry, str(_bmid)),
                    _charge_model_socle(game_state, _bm_entry, int(mc), int(mr)),
                ))
        else:
            blocker_socles.append((int(entry.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]), fp=cells)))
    if not target_entries:
        return empty

    # Offsets d'empreinte du MOVER, à SON socle — pas à celui de l'escouade (cf.
    # `_fight_model_fp_pair`). Préparés UNE FOIS hors des boucles, comme avant.
    fp_offset_pair = _fight_model_fp_pair(game_state, model)

    # Coéquipières : collision euclidienne, un socle à la base PROPRE de chaque fig
    # (_charge_model_socle) — un Captain terminator (base large) attaché à des terminators n'est
    # plus sous-estimé. Le plan provisoire override les figs déjà posées (col,row[,level]).
    sib_socles: List[Tuple[int, Any]] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            pc, pr = int(_pv[0]), int(_pv[1])
            _sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
            _sib_req = int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        # Orientation de LA SŒUR, jamais celle de l'escouade : c'est son socle à elle qui doit
        # tenir sur le plancher, et le `Socle` construit à la ligne suivante lit déjà la sienne.
        # Le couple (niveau, socle) était mesuré sur DEUX orientations différentes.
        _sib_eff = resolve_model_effective_level(game_state, sib, pc, pr, _sib_req)
        sib_socles.append((_sib_eff, _charge_model_socle(game_state, sib, int(pc), int(pr))))

    wall_set = set(wall_hexes)
    # Fin de mouvement 03 : ancres où le SOCLE chevauche un mur (jumeau du move et de la charge).
    # `cand_fp & wall_set` mesurait le mur comme un point, donc pile-in / consolidation pouvaient
    # poser une figurine d'où plus aucun mouvement n'est possible. `wall_set` reste pour le seul
    # TRANSIT du BFS sol, qui chemine en cellules.
    _wall_anchors_end = wall_blocked_anchors(game_state, model)
    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _candidate_footprint_charge(start_col, start_row, model, game_state, fp_offset_pair)
    start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)

    # --- Candidats (col,row) selon le niveau de VUE (§13.06) ------------------------------------
    # view_level 0 : BFS sol historique (traverse figs amies, pas murs/ennemis). view_level >= 1 :
    # cases du plancher atteignables avec le coût vertical, seedées au niveau effectif du mover
    # (source unique move : reachable_multilevel_field). Niveau EFFECTIF de destination = view_level.
    if _view_level >= 1:
        present = floor_levels_present(terrain_areas)
        if _view_level not in present:
            return empty
        from engine.game_state import unit_can_occupy_upper_floor
        if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
            return empty  # §13.06 : ne peut pas finir en hauteur
        start_eff = resolve_model_effective_level(
            game_state, model, start_col, start_row,
            int(model.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
        )
        _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
            game_state, exclude_unit_id=squad_id, level=0
        )
        _ground_obs.discard((start_col, start_row))
        reachable = _fight_model_climb_reachable_floor_cells(
            game_state, unit, squad_id, model, (start_col, start_row), budget, _view_level,
            _ground_obs, terrain_areas, start_level=start_eff,
        )
        dest_eff = _view_level
        skip_wall_blocker = True  # murs/occupation d'étage déjà validés par le helper multi-niveaux
    else:
        # Mover DÉJÀ en hauteur descendant vers le SOL (vue 0) : reach = champ multi-niveaux niveau 0
        # (coût de DESCENTE §13.06 facturé sur le budget). Pile-in/conso ≤ 3" ne franchit en général pas
        # un étage, mais certaines unités ont un budget plus grand → descente facturée comme le move.
        _start_eff = resolve_model_effective_level(
            game_state, model, start_col, start_row,
            int(model.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
        )
        if _start_eff >= 1:
            from engine.game_state import unit_can_occupy_upper_floor
            if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
                return empty  # incohérent : une fig posée en hauteur est forcément montante (13.06)
            _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
                game_state, exclude_unit_id=squad_id, level=0
            )
            _ground_obs.discard((start_col, start_row))
            reachable = _fight_model_climb_reachable_floor_cells(
                game_state, unit, squad_id, model, (start_col, start_row), budget, 0,
                _ground_obs, terrain_areas, start_level=_start_eff,
            )
            dest_eff = 0
            skip_wall_blocker = True
        else:
            # 03.01 : traverse figs amies, PAS ennemies ni murs (chemin = cellules). Départ sol : inchangé.
            path_blocked = wall_set | _enemy_ground | _low_clear
            visited: Set[Tuple[int, int]] = {(start_col, start_row)}
            reachable = []
            queue: deque = deque([(start_col, start_row, 0)])
            while queue:
                c, r, d = queue.popleft()
                if d >= budget:
                    continue
                for nc, nr in get_hex_neighbors(c, r):
                    if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                        continue
                    cell = (nc, nr)
                    if cell in visited or cell in path_blocked:
                        continue
                    visited.add(cell)
                    queue.append((nc, nr, d + 1))
                    reachable.append(cell)
            dest_eff = 0
            skip_wall_blocker = False

    # Bloqueurs/coéquipières au niveau EFFECTIF de destination uniquement (superposition inter-étage).
    _blockers_lvl = [s for lv, s in blocker_socles if lv == dest_eff]
    _sibs_lvl = [s for lv, s in sib_socles if lv == dest_eff]

    closer: List[List[int]] = []
    engaged: List[List[int]] = []
    for cc, rr in reachable:
        cand_fp = _candidate_footprint_charge(cc, rr, model, game_state, fp_offset_pair)
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if not skip_wall_blocker and (cc, rr) in _wall_anchors_end:
            continue  # 03 « Ending a move » : socle vs hexagone de mur (déjà exclu sur étage)
        cand_socle = _charge_model_socle(game_state, model, int(cc), int(rr))
        if any(footprints_overlap(cand_socle, b) for b in _blockers_lvl):
            continue
        if any(footprints_overlap(cand_socle, b) for b in _sibs_lvl):
            continue
        d_min = min(
            min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps
        )
        if d_min >= start_min:
            continue  # WHILE MOVING : strictement plus proche du palier le plus proche
        closer.append([cc, rr])
        synth = _synth_model_entry(
            game_state, squad_id, model, cc, rr, level=dest_eff
        )
        if any(
            unit_entries_within_engagement_zone(synth, te, ez, metric=metric)
            for te in target_entries
        ):
            engaged.append([cc, rr])

    return {"closer": closer, "engaged": engaged}


def _fight_pile_in_closest_tier_ids(
    game_state: Dict[str, Any], unit: Dict[str, Any], target_ids: List[str]
) -> List[str]:
    """Sous-ensemble de ``target_ids`` au palier de distance minimale de l'empreinte de l'unité —
    palier WHILE commun à toutes les figs (cf. ``pile_in_move_destinations_12_03``).

    CONTRAT DE SORTIE, identique à ``_fight_pile_in_closest_enemy_snapshot`` : les ids rendus sont
    tous présents dans ``units_cache`` (ils y ont été lus). Les consommateurs du palier lèvent donc
    sur une absence au lieu de la sauter.
    """
    from engine.hex_utils import min_distance_between_sets

    uid = str(require_key(unit, "id"))
    entry = require_unit_from_cache(uid, game_state, "_fight_pile_in_closest_tier_ids")
    if not entry_is_on_battlefield(entry):
        return []
    unit_fp = set(entry_footprint(entry))
    d_min: Optional[int] = None
    tier: List[str] = []
    for tid in target_ids:
        # `target_ids` sort toujours d'une énumération de `units_cache`
        # (`pile_in_targets_within_range` / `_fight_units_engaged_with`) : la sauter faisait
        # disparaître une cible DÉCLARÉE du palier WHILE sans laisser de trace.
        ce = require_unit_from_cache(
            str(tid), game_state, "_fight_pile_in_closest_tier_ids/target"
        )
        if not entry_is_on_battlefield(ce):
            continue
        efp = set(entry_footprint(ce))
        d = min_distance_between_sets(unit_fp, efp)
        if d_min is None or d < d_min:
            d_min = d
            tier = [str(tid)]
        elif d == d_min:
            tier.append(str(tid))
    return tier


def pile_in_move_destinations_12_03(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    target_ids: List[str],
) -> Set[Tuple[int, int]]:
    """Pool d'ancres valides pour le pile-in AUTO (12.03 WHILE + AFTER par-figurine).

    Génère les positions d'ancre d'escouade dans le budget de 3" par TRANSLATION RIGIDE,
    filtrées par :
      - WHILE (12.03) : empreinte de l'unité STRICTEMENT plus proche du palier le plus proche
        parmi ``target_ids`` qu'à son départ (mesure par-unité, pas par-figurine) ;
      - AFTER (12.03) : chaque figurine qui partait engagée avec une unité ennemie reste
        engagée avec CETTE unité après la translation (contrôle par-figurine, pas par-unité).

    ``target_ids`` = unités ennemies déclarées comme cibles du pile-in. Lecture pure.
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from .shared_utils import get_engagement_zone

    uid = str(require_key(unit, "id"))
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(uid)
    if entry is None:
        return set()

    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, target_ids)
    if not closest_tier:
        return set()

    tier_fps: List[Set[Tuple[int, int]]] = [
        set(entry_footprint(require_unit_from_cache(str(tid), game_state, "pile_in_move_destinations_12_03")))
        for tid in closest_tier
    ]

    start_fp = set(entry_footprint(entry))
    start_d_min = min(min_distance_between_sets(start_fp, tfp) for tfp in tier_fps)
    if start_d_min <= 0:
        return set()

    start_engagements = _fight_model_start_engagements(game_state, unit)
    ez = int(get_engagement_zone(game_state))

    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))

    anchor_col = int(require_key(entry, "col"))
    anchor_row = int(require_key(entry, "row"))

    visited: Set[Tuple[int, int]] = {(anchor_col, anchor_row)}
    queue: deque = deque([(anchor_col, anchor_row, 0)])
    valid: Set[Tuple[int, int]] = set()

    while queue:
        col, row, dist = queue.popleft()

        if (col, row) != (anchor_col, anchor_row):
            placements = _fight_rigid_model_placements(game_state, uid, col, row)
            cand_synths = _fight_synth_cache_entries_at_footprint(
                unit, game_state, col, row, model_placements=placements
            )
            cand_fp: Set[Tuple[int, int]] = set()
            for s in cand_synths:
                cand_fp |= set(entry_footprint(s))

            if cand_fp:
                d_cand = min(min_distance_between_sets(cand_fp, tfp) for tfp in tier_fps)
                if d_cand < start_d_min:
                    if not start_engagements or _fight_models_keep_start_engagements(
                        game_state, uid, start_engagements, placements, ez
                    ):
                        valid.add((col, row))

        if dist < budget:
            for nc, nr in get_hex_neighbors(col, row):
                if (nc, nr) not in visited and 0 <= nc < board_cols and 0 <= nr < board_rows:
                    visited.add((nc, nr))
                    queue.append((nc, nr, dist + 1))

    return valid


def _fight_pile_in_preview_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    plan: MovePlan,
    closest_tier_ids: List[str],
) -> Dict[str, Any]:
    """Dry-run d'un plan pile-in par-figurine (12.03 WHILE/AFTER + cohésion 03.03). Lecture pure.

    ``plan`` couvre TOUTES les figs vivantes, entrées ``(mid, col, row[, level])`` (le 4ᵉ élément =
    niveau d'étage de destination ; absent → niveau courant de la fig). Légalité par-fig =
    appartenance au pool ``closer`` calculé AU NIVEAU planifié de la fig (ou figurine laissée à sa
    position d'origine). On ajoute la cohésion d'unité et les contraintes AFTER : l'escouade finit
    engagée (niveau unité) et chaque figurine engagée au départ reste engagée avec la même unité
    ennemie (par-figurine).

    Retour : {per_model, coherency_ok, unit_engaged, kept_engagements, can_validate}.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import (
        get_engagement_zone,
        coherency_violation_flags,
    )
    from .charge_handlers import (
        _candidate_footprint_charge,
    )

    unit = get_unit_by_id(game_state, str(squad_id))
    empty = {
        "per_model": {},
        "coherency_ok": False,
        "unit_engaged": False,
        "kept_engagements": False,
        "can_validate": False,
    }
    if not unit:
        return empty
    models_cache = require_key(game_state, "models_cache")

    # Niveau porté par le plan (frontière de décodage), jamais déduit du models_cache : une fig
    # montée à l'étage doit être validée contre l'occupation de SON étage.
    norm = [(str(e[0]), int(e[1]), int(e[2]), int(e[3])) for e in plan]
    n = len(norm)
    if n == 0:
        return empty

    # 1) Légalité par-fig : dans son pool ``closer`` au NIVEAU planifié (autres figs = positions
    # provisoires (col,row,level)) ou immobile.
    pos_by_model = {mid: (c, r, lv) for mid, c, r, lv in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r, lv in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        m = models_cache.get(mid)
        orig = (int(m["col"]), int(m["row"])) if m else None
        if orig is not None and (c, r) == orig:
            per_model[mid] = True
            continue
        pool = _fight_pile_in_build_model_pool(
            game_state, mid, closest_tier_ids, provisional_plan=prov, view_level=lv
        )["closer"]
        per_model[mid] = [c, r] in pool

    # 2) Cohésion 03.03 — SOURCE UNIQUE `coherency_violation_flags` (move, déploiement, charge et
    # combat mesurent désormais la MÊME chose). Cette section était une COPIE inline des deux puces,
    # qui ignorait `cohesion_distance_mode` ET la connexité : deux paquets disjoints y passaient, si
    # bien qu'un pile-in pouvait committer une formation que la phase de move refusait ensuite de
    # déplacer (« formation actuelle DÉJÀ incohérente »).
    _mc_coh = require_key(game_state, "models_cache")
    coherency_ok = not any(
        coherency_violation_flags(
            [{**_mc_coh[str(mid)], "col": int(c), "row": int(r)} for mid, c, r, _lv in norm],
            game_state,
        )
    )

    # 3) AFTER (12.03) : escouade engagée (niveau unité, « Your unit must be engaged ») +
    # engagements de départ conservés PAR FIGURINE (« each model that started this move engaged
    # with an enemy unit must still be engaged with that enemy unit »).
    anchor_c, anchor_r = norm[0][1], norm[0][2]
    # Configuration par-figurine RÉELLE du plan (chaque fig à SON étage) : sans elle, l'entrée
    # héritait la carte par-figurine d'AVANT le move (euclidien) et écrasait les étages (3D).
    # Une entrée PAR SOCLE : l'unité est engagée dès qu'une de ses classes de socle l'est.
    synth_units = _fight_synth_cache_entries_at_footprint(
        unit, game_state, anchor_c, anchor_r,
        model_placements={mid: (c, r, lv) for mid, c, r, lv in norm},
    )
    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    units_cache = require_key(game_state, "units_cache")
    player = int(require_key(unit, "player"))
    unit_engaged = any(
        unit_entries_within_engagement_zone(su, ce, ez, metric=metric)
        for _eid, ce in enemy_entries_on_battlefield(units_cache, player, exclude_id=squad_id)
        for su in synth_units
    )
    enemy_entries = list(
        enemy_entries_on_battlefield(units_cache, player, exclude_id=squad_id)
    )
    kept_engagements = True
    for i, (mid, c, r, _lv) in enumerate(norm):
        m = models_cache.get(mid)
        if m is None:
            continue
        # Départ = étage COURANT de la figurine, arrivée = étage PLANIFIÉ : comparer les deux
        # engagements au même niveau ferait perdre/gagner un engagement par pur effet vertical.
        synth_start = _synth_model_entry(
            game_state, str(squad_id), m, int(m["col"]), int(m["row"]),
            level=int(require_key(m, "level")),
        )
        synth_end = _synth_model_entry(
            game_state, str(squad_id), m, int(c), int(r), level=int(_lv)
        )
        for _eid, ce in enemy_entries:
            if unit_entries_within_engagement_zone(
                synth_start, ce, ez, metric=metric) and not unit_entries_within_engagement_zone(
                synth_end, ce, ez, metric=metric):
                kept_engagements = False
                break
        if not kept_engagements:
            break

    can_validate = bool(
        all(per_model.values()) and coherency_ok and unit_engaged and kept_engagements
    )
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "unit_engaged": unit_engaged,
        "kept_engagements": kept_engagements,
        "can_validate": can_validate,
    }


def _fight_pile_in_model_plan_state(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    selected_model: Optional[str] = None,
    view_level: int = 0,
) -> Dict[str, Any]:
    """État du plan pile-in par-figurine exposé au front (miroir simplifié de ``charge_model_plan_state``).

    Une seule « phase » (pas de within_1/engaged/closer) : chaque fig peut se déplacer ≤3" en finissant
    plus proche du palier ennemi le plus proche. ``provisional_plan`` = figs déjà posées (col,row[,level]) ;
    les autres restent à leur position/niveau d'origine. ``selected_model`` non-None → calcule SON pool +
    empreinte lissée. ``view_level`` (étages, §13.06) = niveau de VUE UI ; le pool proposé et le niveau de
    destination des figs posées suivent ce niveau (miroir move par-figurine).
    """
    from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _candidate_footprint_charge,
    )

    squad_id = str(require_key(unit, "id"))
    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [str(m) for m in require_key(squad_models, squad_id) if str(m) in models_cache]
    _vl = int(view_level or 0)
    prov: Dict[str, Tuple[int, int, int]] = {
        str(m): (int(v[0]), int(v[1]), int(v[2]) if len(v) >= 3 and v[2] is not None else _vl)
        for m, v in (provisional_plan or {}).items()
    }
    origin = {
        m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]), int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
        for m in alive
    }

    targets = _fight_v11_pile_in_targets(game_state, unit)
    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, targets) if targets else []

    unplaced = [m for m in alive if m not in prov]
    eligible: List[str] = []
    for m in unplaced:
        if _fight_pile_in_build_model_pool(
            game_state, m, closest_tier, provisional_plan=prov, view_level=_vl
        )["closer"]:
            eligible.append(m)

    pool: List[List[int]] = []
    mask_loops: List[List[List[float]]] = []
    if selected_model is not None and str(selected_model) in alive:
        sel = str(selected_model)
        sel_prov = {k: v for k, v in prov.items() if k != sel}
        pool = _fight_pile_in_build_model_pool(
            game_state, sel, closest_tier, provisional_plan=sel_prov, view_level=_vl
        )["closer"]
        if pool:
            # Le pool est celui de la figurine SELECTIONNEE : son voile se mesure a SON socle.
            _m_sel = require_key(game_state, "models_cache")[sel]
            fp_pair = _fight_model_fp_pair(game_state, _m_sel)
            fp_zone: Set[Tuple[int, int]] = set()
            for cc, rr in pool:
                fp_zone |= _candidate_footprint_charge(int(cc), int(rr), _m_sel, game_state, fp_pair)
            loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
            if loops:
                mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    full_plan: List[Tuple[str, int, int, int]] = [
        (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
        else (m, origin[m][0], origin[m][1], origin[m][2]) for m in alive
    ]
    prev = _fight_pile_in_preview_plan(game_state, squad_id, full_plan, closest_tier)

    # Figs (posées ou à l'origine) dont l'empreinte finit à ≤ EZ d'une cible pile-in → voile vert UI
    # (en mesure de frapper). Cibles exposées au front pour le cercle violet + hit-test du Focus.
    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    target_entries = [units_cache[t] for t in targets if t in units_cache]
    engaged_models: List[str] = []
    for m, c, r, _lv in full_plan:
        _m_fp = require_key(game_state, "models_cache")[str(m)]
        synth = _synth_model_entry(
            game_state, squad_id, _m_fp, int(c), int(r), level=int(_lv)
        )
        if any(
            unit_entries_within_engagement_zone(synth, te, ez, metric=metric)
            for te in target_entries
        ):
            engaged_models.append(m)

    return {
        "phase": "fight",
        "fight_subphase": "pile_in",
        "pile_in_model_move": True,
        "engaged_models": engaged_models,
        "pile_in_targets": [str(t) for t in targets],
        "unitId": squad_id,
        "active_fight_unit": squad_id,
        "current_level": _vl,
        "origin_models": {m: [c, r] for m, (c, r, _l) in origin.items()},
        "provisional": {m: [c, r] for m, (c, r, _l) in prov.items()},
        "eligible_models": eligible,
        "selected_model": str(selected_model) if selected_model is not None else None,
        "pool": pool,
        "footprint_mask_loops": mask_loops,
        "unplaced": unplaced,
        "can_validate": prev["can_validate"],
        # Sous-conditions de légalité (diagnostic + voile rouge front) : voile par-fig invalide
        # (per_model False) et raisons unité (cohésion / engagement / engagements conservés).
        "per_model_valid": prev["per_model"],
        "coherency_ok": prev["coherency_ok"],
        "unit_engaged": prev["unit_engaged"],
        "kept_engagements": prev["kept_engagements"],
        "waiting_for_player": True,
        "action": "wait",
    }


def _fight_pile_in_commit_plan(
    game_state: Dict[str, Any], unit: Dict[str, Any], plan: MovePlan
) -> None:
    """Pose le plan pile-in par-figurine (``commit_move`` type ``pile_in``) + resync l'ancre de l'unité."""
    from .shared_utils import commit_move, set_unit_coordinates

    commit_move(plan, game_state, "pile_in")
    entry = require_key(game_state, "units_cache").get(str(require_key(unit, "id")))
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))


# `_fight_model_in_base_contact` a ete remonte dans `shared_utils` sous le nom
# `model_in_base_contact` : le pile-in du GYM (`_assign_cells_toward_enemies`) applique la MEME
# regle 12.03 « Models in base-contact with one or more enemy models cannot be moved » et en
# gardait sa propre geometrie, centre-a-centre. Le nom prive reste ici pour ses deux appelants.
_fight_model_in_base_contact = model_in_base_contact

def pile_in_autoplace_plan(
    game_state: Dict[str, Any], squad_id: str, focus_target_id: str, mode: str = "defensive"
) -> Dict[str, Any]:
    """Auto-placement de pile-in (12.03) : positionne les figs du squad pour MAXIMISER le nombre de
    figs en mesure de frapper le focus (empreinte ≤ EZ bord-à-bord de ``focus_target_id``). Lecture pure.

    ``mode`` (départage à nombre de figs engagées ÉGAL, priorité absolue conservée) :
      - ``"defensive"`` : maximiser la distance au focus → rester à la limite EZ, le plus loin possible ;
      - ``"offensive"`` : minimiser la distance au focus → socle-à-socle où possible, sinon au plus près.

    Optimum EXACT par programme linéaire en nombres entiers (``scipy.optimize.milp`` / HiGHS), car les
    socles sont multi-hex (Board ×10) : le non-chevauchement entre empreintes est modélisé par une
    contrainte **par cellule** (chaque hex couvert par ≤ 1 fig posée), ce qu'un simple matching biparti
    ne capture pas. Formulation :
      - variable binaire x[f,s] = fig f posée au slot s (créée seulement pour les arêtes LÉGALES) ;
      - 1 fig ≤ 1 slot : Σ_s x[f,s] ≤ 1 ;
      - non-chevauchement : pour chaque cellule h, Σ_{(f,s): h ∈ empreinte(s)} x[f,s] ≤ 1 ;
      - objectif : maximiser Σ x (toutes les arêtes engagent le focus), départage = distance minimale.

    Contraintes de règle (12.03), par arête, conformes au pool/commit pile-in existant :
      - budget 3" (× inches_to_subhex), atteignabilité centre-à-centre (mur/ennemi bloquent, amies
        traversables — 03.01) ;
      - figs en base-contact FIGÉES (ne bougent pas) ;
      - WHILE : empreinte au slot strictement plus proche du palier le plus proche que le départ de la fig ;
      - AFTER : chaque engagement de départ de la fig est conservé au slot.

    ÉTAGES (§13.06) — chaque figurine reste sur SON plancher : son niveau EFFECTIF de départ est aussi
    son niveau de destination, et tout ce qui dépend de la géométrie est calculé à ce niveau (obstacles
    de traversée, collisions de socles, atteignabilité). L'optimisation se décompose donc exactement par
    étage : deux figurines de niveaux différents ne peuvent pas se disputer une case (la superposition
    inter-étage est légale), donc leurs contraintes de non-chevauchement ne se croisent jamais.
    Le plan porte le niveau de chaque figurine — sans lui, le commit retombe sur le niveau de VUE
    (``_prov_from_action``) et fait descendre d'un étage, sans coût ni contrôle, toute figurine posée
    en hauteur.

    Les slots sont générés UNE fois par (taille de socle, niveau) sur la BANDE d'engagement du focus (pas
    tout le rayon). Les figs non affectées par l'ILP sont rapprochées au max le long de leur zone
    atteignable (strictement plus proche, sans chevaucher). Garde-fou final : aucun chevauchement.

    Retour : {"plan": [[model_id, col, row, level], ...]} couvrant toutes les figs vivantes.
    """
    import numpy as np
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy.sparse import coo_matrix
    from engine.hex_utils import min_distance_between_sets, footprints_overlap, Socle
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from engine.terrain_utils import low_clearance_ground_hexes
    from .shared_utils import build_enemy_occupied_positions_set, get_engagement_zone
    from .charge_handlers import (
        _charge_model_footprint,
        _charge_model_socle,
    )

    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        return {"plan": []}

    units_cache = require_key(game_state, "units_cache")
    focus_entry = units_cache.get(str(focus_target_id))
    if focus_entry is None:
        raise ValueError(
            f"pile_in_autoplace_plan: cible focus {focus_target_id} absente de units_cache"
        )

    targets = _fight_v11_pile_in_targets(game_state, unit)
    if str(focus_target_id) not in {str(t) for t in targets}:
        raise ValueError(
            f"pile_in_autoplace_plan: focus {focus_target_id} hors cibles pile-in {targets}"
        )
    closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, targets)
    if not closest_tier:
        raise ValueError(f"pile_in_autoplace_plan: palier le plus proche introuvable pour {squad_id}")

    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    walls = set(game_state.get("wall_hexes", set()))
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [str(m) for m in require_key(squad_models, str(squad_id)) if str(m) in models_cache]
    if not alive:
        return {"plan": []}

    player = int(require_key(unit, "player"))
    focus_fp = set(entry_footprint(focus_entry))

    # --- Étages §13.06 : niveau EFFECTIF (plancher réellement occupé) de chaque figurine. C'est à la
    # fois son niveau de départ et son niveau de destination — le pile-in replace une figurine sur son
    # propre plancher. Même source que le pool de validation (``_fight_pile_in_build_model_pool``), qui
    # seede son champ au niveau effectif du mover : toute autre lecture du niveau produirait des slots
    # que le validateur refuserait.
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (champ optionnel : board sans terrain)
    # `_fight_effective_level_at` et non un appel direct à `resolve_model_floor_level` : c'est la
    # SOURCE UNIQUE que le reste de cette fonction (slots, arêtes, plan final) utilise déjà. La
    # boucle manuscrite lisait l'orientation de l'ESCOUADE là où le helper lit celle de la
    # FIGURINE — sur une escouade à pivot par-figurine ou à bases mixtes, la clé de groupe des
    # slots aurait désigné un autre étage que le plan rendu pour la même figurine.
    eff_level: Dict[str, int] = {
        mid: _fight_effective_level_at(
            game_state, models_cache[mid],
            int(models_cache[mid]["col"]), int(models_cache[mid]["row"]),
            int(require_key(models_cache[mid], "level")),
        )
        for mid in alive
    }
    if any(lv >= 1 for lv in eff_level.values()):
        # Garde du pool de validation, reproduite à l'identique : une unité qui ne peut pas finir en
        # hauteur n'a aucune destination légale là-haut, l'autoplace proposerait des slots
        # systématiquement rejetés. (Le niveau lui-même n'a pas à être vérifié : le niveau EFFECTIF
        # n'est rendu que pour un plancher qui existe et qui porte l'empreinte entière.)
        from engine.game_state import unit_can_occupy_upper_floor
        if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
            raise ValueError(
                f"pile_in_autoplace_plan: {squad_id} a des figurines en hauteur alors que ses mots-clés "
                f"lui interdisent d'y finir (§13.06)"
            )

    # Palier WHILE : empreintes des cibles les plus proches de l'unité.
    tier_fps: List[Set[Tuple[int, int]]] = []
    for tid in closest_tier:
        # Contrat de sortie de `_fight_pile_in_closest_tier_ids` : absence = désynchronisation,
        # pas un palier vide.
        ce = require_unit_from_cache(
            str(tid), game_state, "pile_in_autoplace_plan/tier"
        )
        tier_fps.append(set(entry_footprint(ce)))

    # Collision = test EUCLIDIEN officiel du jeu (``footprints_overlap`` : rond↔rond bord-à-bord
    # continu, méthode empreinte sinon), pas l'intersection de cellules — sinon des socles ronds
    # disjoints en cellules mais chevauchants visuellement passent à travers.
    def _socle(mid: str, c: int, r: int) -> Any:
        return _charge_model_socle(game_state, models_cache[mid], c, r)

    def _overlaps(s: Any, others: List[Any], level: int) -> bool:
        # Les murs ne barrent que le SOL : aux étages, l'appartenance au plancher (et donc l'absence
        # de mur) est déjà tranchée par le champ multi-niveaux qui produit l'atteignabilité — c'est
        # la même dispense que ``skip_wall_blocker`` dans le pool de validation.
        if level == 0 and walls and (s.fp & walls):
            return True
        return any(footprints_overlap(s, o) for o in others)

    def _at_level(socles: List[Tuple[int, Any]], level: int) -> List[Any]:
        """Socles du seul étage ``level`` : deux figurines d'étages différents ne se gênent pas
        (superposition inter-étage, §13.06 — même filtrage que le pool de validation)."""
        return [s for lv, s in socles if lv == level]

    # Socles bloquants PAR FIGURINE : ennemis + autres unités amies (rond↔rond exact par modèle).
    # Empreinte COMPLÈTE par figurine via _charge_model_socle (miroir EXACT du pool de validation,
    # cf. _fight_pile_in_build_model_pool ~L3626) : avec fp={(mc,mr)} (une seule case) un blocker à
    # base NON-RONDE n'occupait que son hex central → l'autoplace posait des figs en superposition
    # partielle que le validateur rejetait ensuite (CHEVAUCHE UN BLOQUEUR → plan invalide).
    # Chaque socle est étiqueté de son niveau EFFECTIF (idem pool) : sans cette étiquette, une
    # figurine d'un autre étage interdisait une case parfaitement libre au niveau visé.
    blocker_socles: List[Tuple[int, Any]] = []
    for eid, entry in entries_on_battlefield(units_cache, exclude_id=squad_id):
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for _bmid, (mc, mr) in by_model.items():
                _bm_entry = models_cache.get(str(_bmid))
                if _bm_entry is None:
                    continue
                blocker_socles.append((
                    _fight_fig_effective_level(entry, str(_bmid)),
                    _charge_model_socle(game_state, _bm_entry, int(mc), int(mr)),
                ))
        else:
            blocker_socles.append((
                int(entry.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]),
                      fp=set(entry_footprint(entry))),
            ))

    # Traversée au SOL : ennemis du niveau 0 seulement (les amies sont traversables, 03.01) et
    # clairance verticale §13.06/§2.11 (une figurine trop haute ne passe pas sous un plancher bas).
    # Aux étages, la traversée est portée par le champ multi-niveaux, qui construit ses propres
    # obstacles par plancher — reproduire ici un blocage de sol l'y ferait compter deux fois.
    ground_enemy = build_enemy_occupied_positions_set(game_state, current_player=player, level=0)

    def _low_clear_for(mid: str) -> Set[Tuple[int, int]]:
        """Clairance au sol de CETTE figurine (§13.06) — sa hauteur, pas celle de l'escouade.

        L'ILP place chaque figurine séparément : c'est chacune qui passe, ou non, sous un plancher
        bas. `low_clearance_ground_hexes` mémoïse par hauteur, donc une escouade homogène ne paie
        qu'une union.
        """
        return low_clearance_ground_hexes(terrain_areas, models_cache[mid], unit)

    # Figs figées (base-contact) : ne bougent pas ; leurs socles bloquent les placements de leur étage.
    frozen_socles: List[Tuple[int, Any]] = []
    movable: List[str] = []
    for mid in alive:
        m = models_cache[mid]
        if _fight_model_in_base_contact(game_state, mid, m):
            frozen_socles.append((eff_level[mid], _socle(mid, int(m["col"]), int(m["row"]))))
        else:
            movable.append(mid)

    # Sans la clairance : elle dépend de la figurine (`_low_clear_for`), tout le reste non.
    path_blocked = walls | ground_enemy
    # Obstacles de sol du champ multi-niveaux : ils excluent l'escouade entière, donc la part
    # commune est calculée une fois — seules la clairance (par figurine) et la case de départ
    # (retirée à l'usage) varient.
    ground_obstacles_climb = path_blocked | build_occupied_positions_set(
        game_state, exclude_unit_id=str(squad_id), level=0
    )
    static_blockers: List[Tuple[int, Any]] = blocker_socles + frozen_socles

    def _model_fp(mid: str, c: int, r: int) -> Set[Tuple[int, int]]:
        return _charge_model_footprint(game_state, models_cache[mid], c, r)

    def _engages_focus(mid: str, c: int, r: int) -> bool:
        # ILP horizontal : la figurine garde son étage QUAND le slot en porte un (§13.06) — sinon
        # elle y est au sol. L'engagement se mesure au niveau EFFECTIF du slot, jamais à celui du
        # départ : une fig à l'étage n'engage pas un ennemi trois étages plus bas, et un slot hors
        # plancher n'est pas « à l'étage ».
        synth = _synth_model_entry(
            game_state, squad_id, models_cache[mid], c, r,
            level=_fight_effective_level_at(
                game_state, models_cache[mid], c, r, int(require_key(models_cache[mid], "level"))
            ),
        )
        return unit_entries_within_engagement_zone(
            synth, focus_entry, ez, metric=metric)

    def _fp_min_to_tier(fp: Set[Tuple[int, int]]) -> int:
        return min(min_distance_between_sets(fp, t) for t in tier_fps) if tier_fps else 1 << 30

    # Figs mobiles déjà AU CONTACT du palier (empreinte à distance 0) : la règle pile-in exige un
    # déplacement STRICTEMENT plus proche → elles ne peuvent pas bouger, donc elles RESTENT sur place.
    # L'ILP les écarte (sm<=0) mais sans réserver leur case → root cause du chevauchement ILP-vs-stayer.
    # On les réserve comme bloqueurs statiques (non-dégradant : la case est réellement occupée) pour
    # PRÉVENIR le chevauchement à la source, avant la génération des slots ILP.
    for mid in movable:
        m = models_cache[mid]
        if _fp_min_to_tier(_model_fp(mid, int(m["col"]), int(m["row"]))) <= 0:
            static_blockers.append((eff_level[mid], _socle(mid, int(m["col"]), int(m["row"]))))

    # --- Slots : bande d'engagement du focus, par (socle, ÉTAGE) distinct (coût). ---
    # L'étage fait partie de la clé, pas seulement le socle, pour DEUX raisons qui se cumulent :
    # les bloqueurs à éviter en dépendent (une même case peut être libre au niveau 1 et occupée au
    # sol), et les slots d'un groupe sont validés UNE fois via la figurine représentative
    # (`_engages_focus`), or l'engagement dépend de la hauteur (§03.04). Grouper une escouade à
    # cheval sur deux niveaux par le seul socle faisait valider tous ses slots à l'altitude du
    # représentant — donc au mauvais étage pour la moitié de l'escouade.
    # Niveau EFFECTIF (`eff_level`, résolu par confinement d'empreinte) et non le niveau STOCKÉ :
    # c'est celui que tout le reste de cette fonction utilise — obstacles, collisions, champ
    # d'atteignabilité. Une clé bâtie sur le niveau stocké désignerait un autre étage que celui
    # contre lequel les slots sont validés.
    #
    # `MODEL_HEIGHT` entre dans la clé pour la MÊME raison que l'étage : la validation par
    # représentante mesure un engagement 3D, dont la borne haute est la hauteur de la figurine
    # (§03.04). Tant que la hauteur venait de l'escouade, le socle et l'étage suffisaient à la
    # déterminer ; depuis qu'elle est par-figurine (`build_models_cache`), deux figurines de même
    # socle au même étage peuvent avoir deux intervalles verticaux différents — un personnage
    # attaché à socle identique mais plus haut ferait valider ses slots à la hauteur de la troupe.
    #
    # Calculée UNE fois par figurine : elle est relue par la boucle d'arêtes de l'ILP, plus bas.
    slot_key_by_mid: Dict[str, Tuple[Any, Any, int, Any]] = {}
    for mid in movable:
        _bs = models_cache[mid]["BASE_SIZE"]
        slot_key_by_mid[mid] = (
            models_cache[mid]["BASE_SHAPE"],
            tuple(_bs) if isinstance(_bs, (list, tuple)) else _bs,
            eff_level[mid],
            models_cache[mid].get("MODEL_HEIGHT"),  # get allowed (états 2D sans couche verticale)
        )

    by_base: Dict[Tuple[Any, Any, int, Any], List[str]] = {}
    for mid in movable:
        by_base.setdefault(slot_key_by_mid[mid], []).append(mid)

    # Rayon d'empreinte EN CASES par base (marge de balayage correcte ; cf. charge_autoplace_plan :
    # BASE_SIZE en mm dilatait ~13× trop loin). Les deux parités de colonne sont couvertes.
    def _base_fp_radius(rep_model: Dict[str, Any]) -> int:
        rmax = 0
        for pc, pr in ((0, 0), (1, 0)):
            for cell in _charge_model_footprint(game_state, rep_model, pc, pr):
                rmax = max(rmax, min_distance_between_sets({(pc, pr)}, {cell}))
        return int(rmax)

    fp_radius_by_base = {b: _base_fp_radius(models_cache[m[0]]) for b, m in by_base.items()}
    _max_fp_radius = max(fp_radius_by_base.values()) if fp_radius_by_base else 0

    # Champs de distance hex multi-source (sans obstacle), calculés UNE fois. Identité métrique cube
    # (hex_utils) : min_distance_between_sets(fp, S) == min(dist_field_S[cell] for cell in fp). Remplace
    # les appels par-slot min_distance_between_sets par un lookup O(1). dist_to_focus → df (objectif) et
    # near_cells (balayage borné, vs rectangle plein) ; dist_to_tier → slot_min (WHILE « plus proche »).
    def _distance_field(sources: Set[Tuple[int, int]], radius: int) -> Dict[Tuple[int, int], int]:
        field: Dict[Tuple[int, int], int] = {cell: 0 for cell in sources}
        frontier: List[Tuple[int, int]] = list(sources)
        for _lay in range(1, radius + 1):
            nf: List[Tuple[int, int]] = []
            for cc, rr in frontier:
                for nc, nr in get_hex_neighbors(cc, rr):
                    if 0 <= nc < board_cols and 0 <= nr < board_rows and (nc, nr) not in field:
                        field[(nc, nr)] = _lay
                        nf.append((nc, nr))
            frontier = nf
            if not frontier:
                break
        return field

    _max_margin = max((ez + r + 2 for r in fp_radius_by_base.values()), default=ez + 2)
    _focus_field_radius = _max_margin + _max_fp_radius + 1
    dist_to_focus = _distance_field(set(focus_fp), _focus_field_radius)
    _tier_sources: Set[Tuple[int, int]] = set()
    for _tfp in tier_fps:
        _tier_sources |= _tfp
    dist_to_tier = _distance_field(_tier_sources, board_cols + board_rows)

    # Zone d'intérêt = cellules ≤ _focus_field_radius du focus. Au-delà, un blocker ne peut chevaucher
    # aucun slot (dont l'empreinte est dans cette zone) → on filtre UNE fois pour le balayage des slots.
    # Le repli garde static_blockers complet (positions de repli potentiellement hors zone).
    _zone = set(dist_to_focus)
    near_blockers = [(lv, s) for lv, s in static_blockers if s.fp & _zone]

    # Liste GLOBALE des slots : (col, row, Socle, slot_min_to_tier, dist_to_focus, level).
    all_slots: List[Tuple[int, int, Any, int, int, int]] = []
    # slots_by_base[(shape, base, level, hauteur)] = [index dans all_slots, ...]
    slots_by_base: Dict[Tuple[Any, Any, int, Any], List[int]] = {}
    for bkey, mids in by_base.items():
        rep_id = mids[0]
        slot_level = bkey[2]
        margin = ez + fp_radius_by_base[bkey] + 2
        near_cells = sorted(cell for cell, d in dist_to_focus.items() if d <= margin)
        level_blockers = _at_level(near_blockers, slot_level)
        idxs: List[int] = []
        for (c, r) in near_cells:
            soc = _socle(rep_id, c, r)
            fps = set(soc.fp)
            if any(not (0 <= x < board_cols and 0 <= y < board_rows) for x, y in fps):
                continue
            if _overlaps(soc, level_blockers, slot_level):
                continue
            if not _engages_focus(rep_id, c, r):
                continue
            slot_min = min((dist_to_tier[cell] for cell in fps if cell in dist_to_tier), default=1 << 30)
            df_slot = min((dist_to_focus[cell] for cell in fps if cell in dist_to_focus), default=1 << 30)
            idxs.append(len(all_slots))
            all_slots.append((c, r, soc, slot_min, df_slot, slot_level))
        slots_by_base[bkey] = idxs

    # --- Atteignabilité par fig (BFS centre-à-centre ≤ budget, amies traversables). ---
    starts = {mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in movable}
    start_fp = {mid: _model_fp(mid, *starts[mid]) for mid in movable}
    start_min = {mid: _fp_min_to_tier(start_fp[mid]) for mid in movable}

    _reach_cache: Dict[str, Dict[Tuple[int, int], int]] = {}

    def _reachable(mid: str) -> Dict[Tuple[int, int], int]:
        """Cases atteignables par la figurine SUR SON PLANCHER, avec leur coût (sous-hexes).

        Sol : BFS centre-à-centre du budget (03.01, amies traversables). Étage : champ multi-niveaux
        du move (source unique du coût vertical, §13.06), seedé au niveau effectif de la figurine —
        exactement ce que calcule le pool de validation pour ce même niveau de vue."""
        cached = _reach_cache.get(mid)
        if cached is not None:
            return cached  # même fig réutilisée au repli → pas de 2e parcours
        level = eff_level[mid]
        sc, sr = starts[mid]
        if level >= 1:
            from engine.phase_handlers.movement_handlers import _model_multilevel_reachable_field

            ground_obs = ground_obstacles_climb | _low_clear_for(mid)
            if (sc, sr) in ground_obs:
                ground_obs = ground_obs - {(sc, sr)}
            dist = _model_multilevel_reachable_field(
                game_state, unit, str(squad_id), models_cache[mid], (sc, sr), budget, {level},
                ground_obs, terrain_areas, start_level=level,
            ).get(level, {})  # get allowed (niveau inatteignable = aucune case)
        else:
            blocked_flat = path_blocked | _low_clear_for(mid)
            dist = {(sc, sr): 0}
            queue: deque = deque([(sc, sr, 0)])
            while queue:
                c, r, d = queue.popleft()
                if d >= budget:
                    continue
                for nc, nr in get_hex_neighbors(c, r):
                    if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                        continue
                    cell = (nc, nr)
                    if cell in dist or cell in blocked_flat:
                        continue
                    dist[cell] = d + 1
                    queue.append((nc, nr, d + 1))
        _reach_cache[mid] = dist
        return dist

    # Engagements de départ par fig (AFTER : à conserver au slot).
    def _start_engagements(mid: str) -> List[Dict[str, Any]]:
        synth = _synth_model_entry(
            game_state, squad_id, models_cache[mid], *starts[mid],
            level=int(require_key(models_cache[mid], "level")),
        )
        out: List[Dict[str, Any]] = []
        for _eid, ce in enemy_entries_on_battlefield(units_cache, player, exclude_id=squad_id):
            if unit_entries_within_engagement_zone(synth, ce, ez, metric=metric):
                out.append(ce)
        return out

    # --- Arêtes ILP : (fig f, slot s) légales. edges_by_slot[s] = liste d'indices d'arête. ---
    edges: List[Tuple[str, int, int]] = []  # (mid, slot_index, pathdist)
    for mid in movable:
        sm = start_min[mid]
        if sm <= 0:
            continue  # déjà au contact du palier : aucun slot strictement plus proche
        reach = _reachable(mid)
        start_eng = _start_engagements(mid)
        for si in slots_by_base[slot_key_by_mid[mid]]:
            sc, sr, soc, slot_min, _df, _slv = all_slots[si]
            if slot_min >= sm:
                continue  # WHILE : strictement plus proche du palier
            pd = reach.get((sc, sr))
            if pd is None:
                continue  # slot hors budget (atteignabilité réelle)
            if start_eng:
                synth_slot = _synth_model_entry(
                    game_state, squad_id, models_cache[mid], sc, sr,
                    level=_fight_effective_level_at(
                        game_state, models_cache[mid], sc, sr,
                        int(require_key(models_cache[mid], "level")),
                    ),
                )
                if not all(
                    unit_entries_within_engagement_zone(
                        synth_slot, ce, ez, metric=metric)
                    for ce in start_eng
                ):
                    continue  # AFTER : un engagement de départ serait perdu
            edges.append((mid, si, pd))

    provisional: Dict[str, Tuple[int, int]] = {}
    placed_socles: List[Tuple[int, Any]] = list(static_blockers)

    if edges:
        n = len(edges)
        mids_idx = {mid: i for i, mid in enumerate(sorted({e[0] for e in edges}))}
        used_slots = sorted({e[1] for e in edges})
        slot_row = {si: k for k, si in enumerate(used_slots)}
        n_model = len(mids_idx)
        n_slot = len(used_slots)
        # Contraintes : (1) 1 fig ≤ 1 slot ; (2) 1 slot ≤ 1 fig ; (3) slots en CHEVAUCHEMENT euclidien
        # mutuellement exclusifs (packing exact multi-hex). Lignes : modèles, puis slots, puis conflits.
        rows: List[int] = []
        cols: List[int] = []
        for e_i, (mid, si, _pd) in enumerate(edges):
            rows.append(mids_idx[mid]); cols.append(e_i)              # (1)
            rows.append(n_model + slot_row[si]); cols.append(e_i)     # (2)
        # (3) paires de slots utilisés qui se chevauchent → 1 ligne par paire. Deux slots d'ÉTAGES
        # différents ne sont jamais en conflit : la superposition inter-étage est légale (§13.06),
        # les y contraindre interdirait à une figurine du sol la case située sous une figurine d'étage.
        conflict_pairs: List[Tuple[int, int]] = []
        for a in range(n_slot):
            sa = all_slots[used_slots[a]][2]
            la = all_slots[used_slots[a]][5]
            for b in range(a + 1, n_slot):
                if all_slots[used_slots[b]][5] != la:
                    continue
                if footprints_overlap(sa, all_slots[used_slots[b]][2]):
                    conflict_pairs.append((used_slots[a], used_slots[b]))
        edges_by_slot: Dict[int, List[int]] = {}
        for e_i, (_mid, si, _pd) in enumerate(edges):
            edges_by_slot.setdefault(si, []).append(e_i)
        base_rows = n_model + n_slot
        for k, (s1, s2) in enumerate(conflict_pairs):
            for e_i in edges_by_slot.get(s1, []) + edges_by_slot.get(s2, []):  # get allowed
                rows.append(base_rows + k); cols.append(e_i)
        n_rows = base_rows + len(conflict_pairs)
        A = coo_matrix(([1.0] * len(rows), (rows, cols)), shape=(n_rows, n))
        # Bornes vectorielles (une par ligne du systeme) : les stubs scipy declarent `lb`/`ub`
        # en `float` alors que l'API accepte un tableau. Lacune du typage externe, pas du code.
        lc = LinearConstraint(A, np.zeros(n_rows), np.ones(n_rows))  # type: ignore[arg-type]
        max_pd = max((e[2] for e in edges), default=0) + 1
        max_df = max((all_slots[e[1]][4] for e in edges), default=0) + 1
        # Objectif lexicographique (BIG ≫ W2 ≫ tie) : (1) maximiser le nb de figs engagées ; (2) selon
        # le mode, MIN distance au focus (offensif) ou MAX distance (défensif) ; (3) déplacement minimal.
        BIG = 1.0e6
        W2 = 1.0e3
        sign = 1.0 if mode == "offensive" else -1.0  # offensif → minimise dist ; défensif → maximise
        c = np.array(
            [-BIG + sign * W2 * (all_slots[si][4] / max_df) + pd / (max_pd * 1.0e3)
             for (_mid, si, pd) in edges],
            dtype=float,
        )
        res = milp(
            c=c, constraints=[lc], integrality=np.ones(n),
            bounds=Bounds(0, 1), options={"time_limit": 2.0},
        )
        if res.x is not None:
            for e_i, x in enumerate(res.x):
                if x > 0.5:
                    mid, si, _pd = edges[e_i]
                    sc, sr, soc, _sm, _df, slv = all_slots[si]
                    provisional[mid] = (sc, sr)
                    placed_socles.append((slv, soc))

    # Figs mobiles non posées par l'ILP : rapprochement au max (strictement plus proche, sans chevaucher).
    placed = set(provisional)
    # Réservation des cases de DÉPART : toute fig mobile non encore bougée (candidate au repli ou
    # susceptible de RESTER sur place) occupe son départ → une autre fig ne doit pas s'y poser.
    # Une fig est retirée de la réservation dès qu'elle bouge effectivement (elle libère sa case).
    # Corrige le crash « chevauchement de socles » : une fig restée au départ n'était pas un bloqueur.
    reserved_start_socles: Dict[str, Tuple[int, Any]] = {
        mid: (eff_level[mid], _socle(mid, *starts[mid])) for mid in movable if mid not in placed
    }
    for mid in movable:
        if mid in placed:
            continue
        level = eff_level[mid]
        sm = start_min[mid]
        best: Optional[Tuple[int, int]] = None
        others_reserved = [
            s for om, (lv, s) in reserved_start_socles.items() if om != mid and lv == level
        ]
        level_placed = _at_level(placed_socles, level)
        if sm > 0:
            best_score = None
            for (cc, rr), _pd in _reachable(mid).items():
                if (cc, rr) == starts[mid]:
                    continue
                soc = _socle(mid, cc, rr)
                if any(not (0 <= x < board_cols and 0 <= y < board_rows) for x, y in soc.fp):
                    continue
                if _overlaps(soc, level_placed, level) or _overlaps(soc, others_reserved, level):
                    continue
                d_tier = _fp_min_to_tier(set(soc.fp))
                if d_tier >= sm:
                    continue  # WHILE
                d_focus = min_distance_between_sets(set(soc.fp), focus_fp)
                if best_score is None or d_focus < best_score:
                    best_score = d_focus
                    best = (cc, rr)
            if best is not None:
                provisional[mid] = best
                placed_socles.append((level, _socle(mid, *best)))
                reserved_start_socles.pop(mid, None)  # a bougé → libère sa case de départ
        if mid not in provisional:
            provisional[mid] = starts[mid]  # reste à sa position (départ, déjà réservée)

    # Figs figées : conservées à leur départ.
    for mid in alive:
        if mid not in provisional:
            m = models_cache[mid]
            provisional[mid] = (int(m["col"]), int(m["row"]))

    # Résolution des chevauchements RÉSIDUELS (ex. une fig posée par l'ILP près d'une fig restée sur
    # place que l'ILP n'a pas pu réserver) : plutôt que planter, on ramène la fig en conflit à son
    # ORIGINE. Justification règles : un pile-in de 0" (rester sur place) est toujours légal ; les
    # positions d'origine sont deux à deux non-chevauchantes (état de jeu valide) → la boucle
    # CONVERGE (au pire toutes les figs reviennent à l'origine = configuration initiale valide).
    # On préfère ramener la fig la PLUS LOIN du focus (elle « perd » le moins d'engagement).
    orig_pos = {mid: (int(models_cache[mid]["col"]), int(models_cache[mid]["row"])) for mid in alive}
    ids = list(alive)
    for _iteration in range(len(ids) + 1):
        socs = {mid: _socle(mid, *provisional[mid]) for mid in ids}
        conflict: Optional[Tuple[str, str]] = None
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if eff_level[ids[i]] != eff_level[ids[j]]:
                    continue  # étages différents : superposition légale (§13.06)
                if footprints_overlap(socs[ids[i]], socs[ids[j]]):
                    conflict = (ids[i], ids[j])
                    break
            if conflict is not None:
                break
        if conflict is None:
            break
        ma, mb = conflict
        moved = [m for m in (ma, mb) if provisional[m] != orig_pos[m]]
        if not moved:
            # Deux figs à leur origine qui se chevauchent = incohérence de l'état d'entrée.
            raise ValueError(
                f"pile_in_autoplace_plan: chevauchement d'origines {ma}{orig_pos[ma]} / {mb}{orig_pos[mb]}"
            )
        # Ramène celle qui a bougé et est la plus loin du focus (perte d'engagement minimale).
        victim = max(
            moved,
            key=lambda m: min_distance_between_sets(_model_fp(m, *provisional[m]), focus_fp),
        )
        provisional[victim] = orig_pos[victim]
    else:
        raise ValueError("pile_in_autoplace_plan: résolution des chevauchements non convergente")

    # L'ILP est HORIZONTAL, mais le niveau ANNONCÉ est celui où la figurine atterrit réellement
    # (§13.06) : le même résolveur que les slots ci-dessus, donc le validateur accepte exactement
    # ce que l'auto-placement propose. L'étage n'est jamais omis — un plan muet est refusé à la
    # frontière, et le front n'a plus à le deviner.
    plan = [
        [
            mid, int(provisional[mid][0]), int(provisional[mid][1]),
            _fight_effective_level_at(
                game_state, models_cache[mid], provisional[mid][0], provisional[mid][1],
                int(require_key(models_cache[mid], "level")),
            ),
        ]
        for mid in alive
    ]
    return {"plan": plan}


def consolidate_autoplace_plan(
    game_state: Dict[str, Any], squad_id: str, mode: str = "defensive"
) -> Dict[str, Any]:
    """Auto-placement de consolidation (Focus off./déf., 12.08) — miroir du Focus pile-in/charge.

    Route vers le moteur ILP existant dont l'AFTER correspond exactement au mode V11 courant
    (déterminé par ``_fight_v11_consolidation_targets``) :
      - ``ongoing``  : AFTER « chaque fig conserve SES engagements de départ » (par-figurine) +
        figs base-contact figées → ``pile_in_autoplace_plan`` (focus = ennemi du palier le plus
        proche parmi les unités engagées) ;
      - ``engaging`` : AFTER « unité engagée avec TOUTES les cibles sélectionnées » (par-unité) →
        ``charge_autoplace_plan`` (couverture dure), budget 3", engagement d'ennemis non sélectionnés
        autorisé (New Foes To Face), FLY ignoré (mouvement normal) ;
      - ``objective`` : cible = zone (pas d'engagement) → non couvert par le Focus, erreur explicite.

    ``mode`` est l'intention du bouton : "offensive" (au plus près) | "defensive" (au plus loin).
    Lecture pure (renvoie {"plan": [[model_id, col, row], ...]}).
    """
    if mode not in ("offensive", "defensive"):
        raise ValueError(f"consolidate_autoplace_plan: mode invalide {mode!r}")
    unit = get_unit_by_id(game_state, str(squad_id))
    if not unit:
        return {"plan": []}

    cons_mode, tier = _fight_v11_consolidation_targets(game_state, unit)
    if cons_mode == "ongoing":
        closest = _fight_pile_in_closest_tier_ids(game_state, unit, list(tier))
        if not closest:
            raise ValueError(
                f"consolidate_autoplace_plan: ongoing sans ennemi le plus proche pour {squad_id}"
            )
        return pile_in_autoplace_plan(game_state, str(squad_id), str(closest[0]), mode=mode)
    if cons_mode == "engaging":
        if not tier:
            raise ValueError(
                f"consolidate_autoplace_plan: engaging sans cible sélectionnée pour {squad_id}"
            )
        from .charge_handlers import charge_autoplace_plan
        budget = 3 * int(require_key(game_state, "inches_to_subhex"))
        # Le plan rendu porte DÉJÀ l'étage de chaque figurine : `charge_autoplace_plan` cherche
        # ses slots par niveau (§13.06) et annonce celui auquel il a calculé. Le re-stamper ici
        # à partir du niveau COURANT de la figurine écraserait un placement d'étage que l'ILP
        # vient de valider — 12.08 dit « moves as described in Moving (03) », la consolidation
        # peut donc monter et descendre comme la charge.
        return charge_autoplace_plan(
            game_state, str(squad_id), mode,
            target_ids_override=[str(t) for t in tier],
            budget_override=budget,
            allow_nontarget_engagement=True,
            disable_fly=True,
        )
    if cons_mode == "objective":
        raise ValueError(
            f"consolidate_autoplace_plan: mode objective non supporté par le Focus "
            f"(cible = zone d'objectif, pas d'engagement) pour {squad_id}"
        )
    raise ValueError(
        f"consolidate_autoplace_plan: aucune consolidation applicable pour {squad_id}"
    )


def _fight_v11_pile_in_targets(game_state: Dict[str, Any], unit: Dict[str, Any]) -> List[str]:
    """Cibles de pile-in (12.03) en auto-sélection : toutes les unités engagées si engagée,
    sinon les ennemis dans ``pile_in_target_range`` (5\")."""
    engaged = _fight_units_engaged_with(game_state, unit)
    return engaged if engaged else pile_in_targets_within_range(game_state, unit)


# =====================================================================
# === V11 FIGHT PHASE — CONSOLIDATION par-figurine (12.08) ============
# =====================================================================
# Moteur GÉNÉRIQUE paramétré (plan §4) : une seule copie du cœur de mouvement,
# pilotée par tier_kind ∈ {enemy, zone}, lock_base_contact (Ongoing) et un AFTER
# par mode. NE TOUCHE PAS au pile-in (rebranché plus tard, factorisation A).


def _fight_v11_consolidation_engaging_candidates(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[str]:
    """Engaging (12.08) : ids des unités ennemies à ≤ consolidation_trigger_range (3") — sélectionnables."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    return _fight_v11_enemies_within_range(game_state, unit, trig)


def _fight_v11_consolidation_objective_candidates(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> List[Any]:
    """Objective (12.08) : ids des objectifs à ≤ consolidation_trigger_range (3") — sélectionnables."""
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    trig = int(require_key(game_rules, "consolidation_trigger_range"))
    return _fight_v11_objectives_within_range(game_state, unit, trig)


def _fight_v11_consolidation_objective_zone(
    game_state: Dict[str, Any], objective_id: Any
) -> Set[Tuple[int, int]]:
    """Set d'hexes de la zone de contrôle d'un objectif (par id). ``raise`` si introuvable."""
    for oid, hexes in objective_hex_zones(game_state):
        if oid == objective_id:
            return hexes
    raise ValueError(f"_fight_v11_consolidation_objective_zone: objectif {objective_id!r} sans hexes")


def _fight_v11_consolidation_targets(
    game_state: Dict[str, Any], unit: Dict[str, Any]
) -> Tuple[Optional[str], Any]:
    """``(mode, tier)`` du move de consolidation (12.08), cascade + sélection joueur.

    - ``ongoing``   → tier = ids de **toutes** les unités ennemies engagées (imposé) ;
    - ``engaging``  → tier = ids ennemis **sélectionnés par le joueur** (état
      ``consolidation_engaging_selection``), filtrés sur les candidats à ≤3". Tier vide =
      sélection en attente (move encore impossible) ;
    - ``objective`` → tier = **set d'hexes** de la zone de l'objectif sélectionné
      (``consolidation_objective_selection``), auto si 1 seul candidat. ``None`` = sélection
      en attente ;
    - ``(None, None)`` → aucune branche applicable (pas de consolidation possible).

    ``tier_kind`` est implicite : ``zone`` pour objective, ``enemy`` sinon.
    """
    mode = fight_v11_consolidation_mode(game_state, unit)
    if mode is None:
        return (None, None)
    uid = str(require_key(unit, "id"))
    if mode == "ongoing":
        tier = _fight_units_engaged_with(game_state, unit)
        if not tier:
            raise ValueError(
                f"_fight_v11_consolidation_targets: mode ongoing mais unité {uid} non engagée"
            )
        return ("ongoing", tier)
    if mode == "engaging":
        candidates = set(_fight_v11_consolidation_engaging_candidates(game_state, unit))
        sel = game_state.get("consolidation_engaging_selection", {}).get(uid, [])  # fallback allowed — aucune sélection engaging pour cette unité = tier vide (métier)
        tier = [str(e) for e in sel if str(e) in candidates]
        return ("engaging", tier)
    if mode == "objective":
        cands = _fight_v11_consolidation_objective_candidates(game_state, unit)
        if len(cands) == 1:
            chosen: Any = cands[0]
        else:
            chosen = game_state.get("consolidation_objective_selection", {}).get(uid)  # fallback allowed — aucune sélection objective pour cette unité = None (métier)
            if chosen not in cands:
                chosen = None
        if chosen is None:
            return ("objective", None)
        return ("objective", _fight_v11_consolidation_objective_zone(game_state, chosen))
    raise ValueError(f"_fight_v11_consolidation_targets: mode inattendu {mode!r}")


def _fight_consolidation_build_model_pool(
    game_state: Dict[str, Any],
    model_id: str,
    *,
    tier_kind: str,
    tier: Any,
    lock_base_contact: bool,
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    view_level: int = 0,
) -> Dict[str, List[List[int]]]:
    """Pool de destinations PAR-FIGURINE pour la CONSOLIDATION (12.08), moteur générique.

    Paramètres :
      - ``tier_kind`` ∈ {"enemy","zone"} : nature du palier WHILE ;
      - ``tier`` : pour "enemy" = ids du **palier ennemi le plus proche** (closest tier) ;
        pour "zone" = set d'hexes de la zone de l'objectif sélectionné ;
      - ``lock_base_contact`` : Ongoing — une figurine en base-contact ennemi NE BOUGE PAS (12.08) ;
      - ``view_level`` (étages, §13.06) : niveau de VUE UI. 0 = plan sol (historique). >= 1 = plancher
        de ce niveau, atteignable avec le coût vertical (source unique move), seedé au niveau EFFECTIF
        courant du mover → une fig déjà en hauteur reste sur son étage (miroir pile-in / move).

    WHILE MOVING (12.08) :
      - enemy (Ongoing/Engaging) : empreinte finale STRICTEMENT plus proche du palier le plus
        proche qu'au départ (engaged si possible) — même cœur que le pile-in ;
      - zone (Objective) : empreinte WITHIN RANGE de la zone (empreinte ∩ zone) si possible,
        SINON strictement plus proche de la zone.

    Retour ``{"closer":[...], "engaged":[...]}`` (engaged ⊆ closer ; enemy : ≤ EZ d'un ennemi du
    palier ; zone : empreinte ∩ zone). Lecture pure (réutilise les primitives charge/empreinte).
    """
    from collections import deque
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _candidate_footprint_charge,
        _charge_model_socle,
    )
    from engine.hex_utils import footprints_overlap, Socle

    if tier_kind not in ("enemy", "zone"):
        raise ValueError(f"_fight_consolidation_build_model_pool: tier_kind invalide {tier_kind!r}")
    models_cache = require_key(game_state, "models_cache")
    model = models_cache.get(str(model_id))
    if model is None:
        raise KeyError(f"_fight_consolidation_build_model_pool: model {model_id} not in models_cache")
    squad_id = str(model["squad_id"])
    unit = get_unit_by_id(game_state, squad_id)
    empty: Dict[str, List[List[int]]] = {"closer": [], "engaged": []}
    if not unit:
        return empty

    # Ongoing : verrou base-contact (12.08 WHILE) — figurine collée à un ennemi = figée.
    if lock_base_contact and _fight_model_in_base_contact(game_state, str(model_id), model):
        return empty

    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    budget = 3 * int(require_key(game_state, "inches_to_subhex"))
    board_cols = int(require_key(game_state, "board_cols"))
    board_rows = int(require_key(game_state, "board_rows"))
    wall_hexes = game_state.get("wall_hexes", set())
    player = int(model["player"])
    units_cache = require_key(game_state, "units_cache")
    terrain_areas = game_state.get("terrain_areas", [])  # get allowed (champ optionnel : board sans terrain)
    _view_level = int(view_level or 0)

    closest = {str(t) for t in tier} if tier_kind == "enemy" else set()
    zone_set: Set[Tuple[int, int]] = set(tier) if tier_kind == "zone" else set()
    target_entries: List[Dict[str, Any]] = []
    target_fps: List[Set[Tuple[int, int]]] = []
    from engine.terrain_utils import floor_levels_present, low_clearance_ground_hexes
    from .shared_utils import build_enemy_occupied_positions_set
    # Obstacles au SOL filtrés par NIVEAU (miroir move) : seuls les ennemis au niveau 0 bloquent le
    # sol — un ennemi en hauteur ne gêne pas (superposition inter-étage §13.06). ``_low_clear`` =
    # clairance verticale (§13.06/§2.11 : une fig trop haute ne peut finir/passer sous un plancher bas).
    _enemy_ground = build_enemy_occupied_positions_set(game_state, current_player=player, level=0)
    # Hauteur de LA FIGURINE qui bouge, jumeau du move : le pool est
    # par-figurine, et un personnage attaché plus haut ne passe pas là où passe la troupe.
    _low_clear = low_clearance_ground_hexes(terrain_areas, model, unit)
    # Bloqueurs (ennemis + autres unités amies) → collision par TEST EUCLIDIEN officiel
    # (footprints_overlap), comme les autoplaces. Chaque socle étiqueté de son niveau EFFECTIF :
    # une fig d'un autre étage ne gêne pas (superposition inter-étage, §13.06, miroir pile-in).
    blocker_socles: List[Tuple[int, Any]] = []
    for eid, entry in entries_on_battlefield(units_cache):
        cells = set(entry_footprint(entry))
        if int(entry["player"]) != player:
            if tier_kind == "enemy" and str(eid) in closest:
                target_entries.append(entry)
                target_fps.append(cells)
        if str(eid) == squad_id:
            continue  # coéquipières traitées à part (positions provisoires)
        by_model = entry.get("occupied_hexes_by_model")
        if by_model:
            for _bmid, (mc, mr) in by_model.items():
                _bm_entry = models_cache.get(str(_bmid))
                if _bm_entry is None:
                    continue
                # Empreinte COMPLÈTE par figurine (même convention que le mover/sœurs via
                # _charge_model_socle) : sans ça, un blocker à base non-ronde n'occupait que son
                # hex central (fp={(mc,mr)}) → superposition partielle permise (méthode empreinte).
                blocker_socles.append((
                    _fight_fig_effective_level(entry, str(_bmid)),
                    _charge_model_socle(game_state, _bm_entry, int(mc), int(mr)),
                ))
        else:
            blocker_socles.append((int(entry.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
                Socle(shape=entry["BASE_SHAPE"], base_size=entry["BASE_SIZE"],
                      col=int(entry["col"]), row=int(entry["row"]), fp=cells)))
    if tier_kind == "enemy" and not target_entries:
        return empty
    if tier_kind == "zone" and not zone_set:
        return empty

    # Offsets d'empreinte du MOVER, à SON socle — pas à celui de l'escouade (cf.
    # `_fight_model_fp_pair`). Préparés UNE FOIS hors des boucles, comme avant.
    fp_offset_pair = _fight_model_fp_pair(game_state, model)

    # Coéquipières (collision euclidienne) : le plan provisoire override les figs déjà posées (col,row[,level]).
    sib_socles: List[Tuple[int, Any]] = []
    squad_models = require_key(game_state, "squad_models")
    for mid in require_key(squad_models, squad_id):
        if str(mid) == str(model_id):
            continue
        sib = models_cache.get(str(mid))
        if sib is None:
            continue
        if provisional_plan and str(mid) in provisional_plan:
            _pv = provisional_plan[str(mid)]
            pc, pr = int(_pv[0]), int(_pv[1])
            _sib_req = int(_pv[2]) if len(_pv) >= 3 else int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        else:
            pc, pr = int(sib["col"]), int(sib["row"])
            _sib_req = int(sib.get("level", 0))  # get allowed (champ optionnel : level absent = sol)
        # Orientation de LA SŒUR, jamais celle de l'escouade : c'est son socle à elle qui doit
        # tenir sur le plancher, et le `Socle` construit à la ligne suivante lit déjà la sienne.
        # Le couple (niveau, socle) était mesuré sur DEUX orientations différentes.
        _sib_eff = resolve_model_effective_level(game_state, sib, pc, pr, _sib_req)
        sib_socles.append((_sib_eff, _charge_model_socle(game_state, sib, int(pc), int(pr))))

    wall_set = set(wall_hexes)
    # Fin de mouvement 03 : ancres où le SOCLE chevauche un mur (jumeau du move et de la charge).
    # `cand_fp & wall_set` mesurait le mur comme un point, donc pile-in / consolidation pouvaient
    # poser une figurine d'où plus aucun mouvement n'est possible. `wall_set` reste pour le seul
    # TRANSIT du BFS sol, qui chemine en cellules.
    _wall_anchors_end = wall_blocked_anchors(game_state, model)
    start_col, start_row = int(model["col"]), int(model["row"])
    start_fp = _candidate_footprint_charge(start_col, start_row, model, game_state, fp_offset_pair)
    if tier_kind == "enemy":
        start_min = min(min_distance_between_sets(start_fp, tfp) for tfp in target_fps)
    else:
        start_min = min_distance_between_sets(start_fp, zone_set)

    # --- Candidats (col,row) selon le niveau de VUE (§13.06), miroir pile-in ---------------------
    if _view_level >= 1:
        present = floor_levels_present(terrain_areas)
        if _view_level not in present:
            return empty
        from engine.game_state import unit_can_occupy_upper_floor
        if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
            return empty
        start_eff = resolve_model_effective_level(
            game_state, model, start_col, start_row,
            int(model.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
        )
        _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
            game_state, exclude_unit_id=squad_id, level=0
        )
        _ground_obs.discard((start_col, start_row))
        reachable = _fight_model_climb_reachable_floor_cells(
            game_state, unit, squad_id, model, (start_col, start_row), budget, _view_level,
            _ground_obs, terrain_areas, start_level=start_eff,
        )
        dest_eff = _view_level
        skip_wall_blocker = True
    else:
        # Mover DÉJÀ en hauteur descendant vers le SOL (vue 0) : reach = champ multi-niveaux niveau 0
        # (coût de DESCENTE §13.06), miroir pile-in. Budget conso > 3" possible → descente facturée.
        _start_eff = resolve_model_effective_level(
            game_state, model, start_col, start_row,
            int(model.get("level", 0)),  # get allowed (champ optionnel : level absent = sol)
        )
        if _start_eff >= 1:
            from engine.game_state import unit_can_occupy_upper_floor
            if not unit_can_occupy_upper_floor(require_key(unit, "UNIT_KEYWORDS")):
                return empty  # incohérent : une fig posée en hauteur est forcément montante (13.06)
            _ground_obs = set(wall_set) | _low_clear | _enemy_ground | build_occupied_positions_set(
                game_state, exclude_unit_id=squad_id, level=0
            )
            _ground_obs.discard((start_col, start_row))
            reachable = _fight_model_climb_reachable_floor_cells(
                game_state, unit, squad_id, model, (start_col, start_row), budget, 0,
                _ground_obs, terrain_areas, start_level=_start_eff,
            )
            dest_eff = 0
            skip_wall_blocker = True
        else:
            # 03.01 : traverse les amies, PAS les ennemies ni les murs (BFS = cellules). Départ sol : inchangé.
            path_blocked = wall_set | _enemy_ground | _low_clear
            visited: Set[Tuple[int, int]] = {(start_col, start_row)}
            reachable = []
            queue: deque = deque([(start_col, start_row, 0)])
            while queue:
                c, r, d = queue.popleft()
                if d >= budget:
                    continue
                for nc, nr in get_hex_neighbors(c, r):
                    if nc < 0 or nr < 0 or nc >= board_cols or nr >= board_rows:
                        continue
                    cell = (nc, nr)
                    if cell in visited or cell in path_blocked:
                        continue
                    visited.add(cell)
                    queue.append((nc, nr, d + 1))
                    reachable.append(cell)
            dest_eff = 0
            skip_wall_blocker = False

    _blockers_lvl = [s for lv, s in blocker_socles if lv == dest_eff]
    _sibs_lvl = [s for lv, s in sib_socles if lv == dest_eff]

    closer: List[List[int]] = []
    engaged: List[List[int]] = []
    for cc, rr in reachable:
        cand_fp = _candidate_footprint_charge(cc, rr, model, game_state, fp_offset_pair)
        if any(not (0 <= x < board_cols and 0 <= y < board_rows) for (x, y) in cand_fp):
            continue
        if not skip_wall_blocker and (cc, rr) in _wall_anchors_end:
            continue  # 03 « Ending a move » : socle vs hexagone de mur (déjà exclu sur étage)
        cand_socle = _charge_model_socle(game_state, model, int(cc), int(rr))
        if any(footprints_overlap(cand_socle, b) for b in _blockers_lvl):
            continue  # chevauchement ennemi / autre unité amie AU MÊME ÉTAGE (euclidien, tangence OK)
        if any(footprints_overlap(cand_socle, b) for b in _sibs_lvl):
            continue  # chevauchement coéquipière au même étage (idem)
        if tier_kind == "enemy":
            d_min = min(
                min_distance_between_sets(cand_fp, tfp, max_distance=start_min) for tfp in target_fps
            )
            if d_min >= start_min:
                continue  # WHILE : strictement plus proche du palier le plus proche
            closer.append([cc, rr])
            synth = _synth_model_entry(
                game_state, squad_id, model, cc, rr, level=dest_eff
            )
            if any(
                unit_entries_within_engagement_zone(synth, te, ez, metric=metric)
                for te in target_entries
            ):
                engaged.append([cc, rr])
        else:  # zone (Objective)
            if cand_fp & zone_set:
                # within range = empreinte DANS la zone du terrain (14.02)
                closer.append([cc, rr])
                engaged.append([cc, rr])
            else:
                d_min = min_distance_between_sets(cand_fp, zone_set, max_distance=start_min)
                if d_min < start_min:  # « closer if not » (pas within mais se rapproche)
                    closer.append([cc, rr])

    return {"closer": closer, "engaged": engaged}


def _fight_consolidation_preview_plan(
    game_state: Dict[str, Any],
    squad_id: str,
    plan: MovePlan,
    *,
    mode: str,
    tier_kind: str,
    tier: Any,
    closest_tier_ids: List[str],
    lock_base_contact: bool,
) -> Dict[str, Any]:
    """Dry-run d'un plan de consolidation par-figurine (12.08 WHILE/AFTER + cohésion 03.03).

    AFTER par mode :
      - ongoing   : chaque figurine engagée au départ reste engagée avec la même unité (par-figurine) ;
      - engaging  : unité engagée avec **toutes** les unités ennemies sélectionnées (tier) ;
      - objective : unité within range de l'objectif (≥1 figurine dans la zone).

    ⚠️ ``can_validate=False`` si la cible (tous les ciblés / la zone) est inatteignable : le
    « closer if not » du WHILE ne valide pas le move (move optionnel → on ne bouge pas). Lecture pure.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import (
        get_engagement_zone,
        coherency_violation_flags,
    )
    from .charge_handlers import (
        _candidate_footprint_charge,
    )

    unit = get_unit_by_id(game_state, str(squad_id))
    empty = {
        "per_model": {},
        "coherency_ok": False,
        "unit_engaged": False,
        "kept_engagements": False,
        "engaged_with_all_selected": False,
        "within_objective_range": False,
        "can_validate": False,
    }
    if not unit:
        return empty
    models_cache = require_key(game_state, "models_cache")

    # Niveau porté par le plan (frontière de décodage), jamais déduit du models_cache : une fig
    # montée à l'étage doit être validée contre l'occupation de SON étage.
    norm = [(str(e[0]), int(e[1]), int(e[2]), int(e[3])) for e in plan]
    n = len(norm)
    if n == 0:
        return empty

    # 1) Légalité par-fig : dans son pool ``closer`` au NIVEAU planifié (autres figs = positions
    # provisoires (col,row,level)) ou immobile.
    pos_by_model = {mid: (c, r, lv) for mid, c, r, lv in norm}
    per_model: Dict[str, bool] = {}
    for mid, c, r, lv in norm:
        prov = {m2: pos_by_model[m2] for m2 in pos_by_model if m2 != mid}
        m = models_cache.get(mid)
        orig = (int(m["col"]), int(m["row"])) if m else None
        if orig is not None and (c, r) == orig:
            per_model[mid] = True
            continue
        pool = _fight_consolidation_build_model_pool(
            game_state, mid, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=prov, view_level=lv,
        )["closer"]
        per_model[mid] = [c, r] in pool

    # Empreintes par-figurine du plan : consommées par le test de zone d'objectif ci-dessous
    # (la cohésion, elle, passe par la source unique juste en dessous ; l'engagement, lui, se
    # mesure sur les entrées par socle, qui recalculent leurs empreintes).
    # Empreinte de CHAQUE figurine à SON socle (`_fight_model_fp_pair`) : le plan est par-figurine,
    # et un personnage attaché y était sous-empreinté au socle de l'escouade.
    _mc_fp = require_key(game_state, "models_cache")
    fps = [
        _candidate_footprint_charge(
            c, r, _mc_fp[str(_mid)], game_state,
            _fight_model_fp_pair(game_state, _mc_fp[str(_mid)]),
        )
        for _mid, c, r, _ in norm
    ]

    # 2) Cohésion 03.03 — SOURCE UNIQUE `coherency_violation_flags` (move, déploiement, charge et
    # combat mesurent désormais la MÊME chose). Cette section était une COPIE inline des deux puces,
    # qui ignorait `cohesion_distance_mode` ET la connexité : deux paquets disjoints y passaient, si
    # bien qu'un pile-in pouvait committer une formation que la phase de move refusait ensuite de
    # déplacer (« formation actuelle DÉJÀ incohérente »).
    _mc_coh = require_key(game_state, "models_cache")
    coherency_ok = not any(
        coherency_violation_flags(
            [{**_mc_coh[str(mid)], "col": int(c), "row": int(r)} for mid, c, r, _lv in norm],
            game_state,
        )
    )

    # 3) AFTER (12.08) au niveau unité, selon le mode.
    union_fp: Set[Tuple[int, int]] = set()
    for f in fps:
        union_fp |= f
    anchor_c, anchor_r = norm[0][1], norm[0][2]
    # Configuration par-figurine RÉELLE du plan (chaque fig à SON étage) : sans elle, l'entrée
    # héritait la carte par-figurine d'AVANT le move (euclidien) et écrasait les étages (3D).
    # Une entrée PAR SOCLE : l'unité est engagée dès qu'une de ses classes de socle l'est.
    synth_units = _fight_synth_cache_entries_at_footprint(
        unit, game_state, anchor_c, anchor_r,
        model_placements={mid: (c, r, lv) for mid, c, r, lv in norm},
    )
    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    units_cache = require_key(game_state, "units_cache")
    player = int(require_key(unit, "player"))

    unit_engaged = any(
        unit_entries_within_engagement_zone(su, ce, ez, metric=metric)
        for _eid, ce in enemy_entries_on_battlefield(units_cache, player, exclude_id=squad_id)
        for su in synth_units
    )

    kept_engagements = True
    engaged_with_all_selected = True
    within_objective_range = False
    after_ok = False
    if mode == "ongoing":
        # 12.08 AFTER (Ongoing) PAR FIGURINE : chaque figurine engagée AU DÉPART avec une unité
        # ennemie doit rester engagée avec CETTE unité après le move (pas au niveau unité).
        enemy_entries = list(
            enemy_entries_on_battlefield(units_cache, player, exclude_id=squad_id)
        )
        for i, (mid, c, r, _lv) in enumerate(norm):
            m = models_cache.get(mid)
            if m is None:
                continue
            # Départ = étage COURANT de la figurine (miroir strict du pile-in) : le comparer
            # au sol ferait perdre/gagner un engagement par pur effet vertical.
            synth_start = _synth_model_entry(
                game_state, str(squad_id), m, int(m["col"]), int(m["row"]),
                level=int(require_key(m, "level")),
            )
            synth_end = _synth_model_entry(
                game_state, str(squad_id), m, int(c), int(r), level=int(_lv)
            )
            for _eid, ce in enemy_entries:
                if unit_entries_within_engagement_zone(
                    synth_start, ce, ez, metric=metric) and not unit_entries_within_engagement_zone(
                    synth_end, ce, ez, metric=metric):
                    kept_engagements = False
                    break
            if not kept_engagements:
                break
        after_ok = kept_engagements
    elif mode == "engaging":
        selected = [str(e) for e in tier]
        engaged_with_all_selected = bool(selected)
        for eid in selected:
            # `selected` vient de `tier`, c'est-à-dire de la SÉLECTION du joueur filtrée sur
            # `_fight_v11_consolidation_engaging_candidates` — laquelle énumère `units_cache`.
            # (Pas de `_fight_pile_in_closest_tier_ids` : le contrat tient, mais par cette
            # source-là.) Confondre l'absence avec « pas engagé » refusait la consolidation
            # sans le dire.
            ce = require_unit_from_cache(
                str(eid), game_state, "_fight_consolidation_preview_plan"
            )
            if not any(
                unit_entries_within_engagement_zone(su, ce, ez, metric=metric) for su in synth_units
            ):
                engaged_with_all_selected = False
                break
        after_ok = engaged_with_all_selected
    elif mode == "objective":
        zone_set: Set[Tuple[int, int]] = set(tier) if tier else set()
        within_objective_range = bool(zone_set) and bool(union_fp & zone_set)
        after_ok = within_objective_range
    else:
        raise ValueError(f"_fight_consolidation_preview_plan: mode inattendu {mode!r}")

    can_validate = bool(all(per_model.values()) and coherency_ok and after_ok)
    return {
        "per_model": per_model,
        "coherency_ok": coherency_ok,
        "unit_engaged": unit_engaged,
        "kept_engagements": kept_engagements,
        "engaged_with_all_selected": engaged_with_all_selected,
        "within_objective_range": within_objective_range,
        "can_validate": can_validate,
    }


def _fight_consolidation_model_plan_state(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    provisional_plan: Optional[Dict[str, Tuple[int, ...]]] = None,
    selected_model: Optional[str] = None,
    view_level: int = 0,
) -> Dict[str, Any]:
    """État du plan de consolidation par-figurine exposé au front (miroir du pile-in par-figurine).

    Détermine ``(mode, tier)`` via ``_fight_v11_consolidation_targets``. En Engaging sans sélection
    de cibles, ou en Objective sans objectif choisi (>1 candidat), renvoie un état
    ``awaiting_*_selection`` exposant les candidats cliquables (le move reste bloqué).
    """
    from engine.hex_union_boundary_polygon import compute_move_preview_mask_loops_world
    from engine.spatial_relations import unit_entries_within_engagement_zone, engagement_distance_metric
    from .shared_utils import get_engagement_zone
    from .charge_handlers import (
        _candidate_footprint_charge,
    )

    squad_id = str(require_key(unit, "id"))
    models_cache = require_key(game_state, "models_cache")
    units_cache = require_key(game_state, "units_cache")
    squad_models = require_key(game_state, "squad_models")
    alive = [str(m) for m in require_key(squad_models, squad_id) if str(m) in models_cache]
    _vl = int(view_level or 0)
    prov: Dict[str, Tuple[int, int, int]] = {
        str(m): (int(v[0]), int(v[1]), int(v[2]) if len(v) >= 3 and v[2] is not None else _vl)
        for m, v in (provisional_plan or {}).items()
    }
    origin = {
        m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]), int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
        for m in alive
    }

    mode, tier = _fight_v11_consolidation_targets(game_state, unit)
    engaging_candidates = (
        _fight_v11_consolidation_engaging_candidates(game_state, unit) if mode == "engaging" else []
    )
    objective_candidates = (
        _fight_v11_consolidation_objective_candidates(game_state, unit) if mode == "objective" else []
    )
    base = {
        "phase": "fight",
        "fight_subphase": "consolidate",
        "consolidation_model_move": True,
        "consolidation_mode": mode,
        "unitId": squad_id,
        "active_fight_unit": squad_id,
        "current_level": _vl,
        "origin_models": {m: [c, r] for m, (c, r, _l) in origin.items()},
        "provisional": {m: [c, r] for m, (c, r, _l) in prov.items()},
        "selected_model": str(selected_model) if selected_model is not None else None,
        "engaging_candidates": [str(e) for e in engaging_candidates],
        "objective_candidates": [str(o) for o in objective_candidates],
        "waiting_for_player": True,
        "action": "wait",
    }

    # Sélection préalable requise (Engaging : ≥1 cible ; Objective : 1 objectif si >1 candidat).
    if mode is None:
        return {**base, "awaiting_target_selection": False, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}
    if mode == "engaging" and not tier:
        return {**base, "awaiting_target_selection": True, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}
    if mode == "objective" and tier is None:
        return {**base, "awaiting_objective_selection": True, "eligible_models": [],
                "pool": [], "footprint_mask_loops": [], "can_validate": False}

    tier_kind = "zone" if mode == "objective" else "enemy"
    lock_base_contact = mode == "ongoing"
    if tier_kind == "enemy":
        closest_tier = _fight_pile_in_closest_tier_ids(game_state, unit, list(tier))
    else:
        closest_tier = []

    unplaced = [m for m in alive if m not in prov]
    eligible: List[str] = []
    for m in unplaced:
        if _fight_consolidation_build_model_pool(
            game_state, m, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=prov, view_level=_vl,
        )["closer"]:
            eligible.append(m)

    pool: List[List[int]] = []
    mask_loops: List[List[List[float]]] = []
    if selected_model is not None and str(selected_model) in alive:
        sel = str(selected_model)
        sel_prov = {k: v for k, v in prov.items() if k != sel}
        pool = _fight_consolidation_build_model_pool(
            game_state, sel, tier_kind=tier_kind, tier=tier,
            lock_base_contact=lock_base_contact, provisional_plan=sel_prov, view_level=_vl,
        )["closer"]
        if pool:
            # Le pool est celui de la figurine SELECTIONNEE : son voile se mesure a SON socle.
            _m_sel = require_key(game_state, "models_cache")[sel]
            fp_pair = _fight_model_fp_pair(game_state, _m_sel)
            fp_zone: Set[Tuple[int, int]] = set()
            for cc, rr in pool:
                fp_zone |= _candidate_footprint_charge(int(cc), int(rr), _m_sel, game_state, fp_pair)
            loops = compute_move_preview_mask_loops_world(fp_zone, game_state)
            if loops:
                mask_loops = [[[float(x), float(y)] for (x, y) in loop] for loop in loops]

    full_plan: List[Tuple[str, int, int, int]] = [
        (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
        else (m, origin[m][0], origin[m][1], origin[m][2]) for m in alive
    ]
    prev = _fight_consolidation_preview_plan(
        game_state, squad_id, full_plan, mode=mode, tier_kind=tier_kind, tier=tier,
        closest_tier_ids=closest_tier,
        lock_base_contact=lock_base_contact,
    )

    # Voile vert UI : figs « en position » (≤ EZ d'un ennemi du palier, ou dans la zone objectif).
    ez = int(get_engagement_zone(game_state))
    metric = engagement_distance_metric(game_state)
    engaged_models: List[str] = []
    if tier_kind == "enemy":
        target_entries = [units_cache[t] for t in closest_tier if t in units_cache]
        for m, c, r, _lv in full_plan:
            _m_fp = require_key(game_state, "models_cache")[str(m)]
            synth = _synth_model_entry(
                game_state, squad_id, _m_fp, int(c), int(r), level=int(_lv)
            )
            if any(
                unit_entries_within_engagement_zone(synth, te, ez, metric=metric)
                for te in target_entries
            ):
                engaged_models.append(m)
    else:
        zone_set: Set[Tuple[int, int]] = set(tier)
        for m, c, r, _lv in full_plan:
            _m_fp = require_key(game_state, "models_cache")[str(m)]
            fp = _candidate_footprint_charge(
                int(c), int(r), _m_fp, game_state, _fight_model_fp_pair(game_state, _m_fp)
            )
            if fp & zone_set:
                engaged_models.append(m)

    return {
        **base,
        "awaiting_target_selection": False,
        "awaiting_objective_selection": False,
        "engaged_models": engaged_models,
        "consolidation_targets": [str(t) for t in closest_tier] if tier_kind == "enemy" else [],
        "eligible_models": eligible,
        "pool": pool,
        "footprint_mask_loops": mask_loops,
        "unplaced": unplaced,
        "can_validate": prev["can_validate"],
        "per_model_valid": prev["per_model"],
        "coherency_ok": prev["coherency_ok"],
        "unit_engaged": prev["unit_engaged"],
        "kept_engagements": prev["kept_engagements"],
        "engaged_with_all_selected": prev["engaged_with_all_selected"],
        "within_objective_range": prev["within_objective_range"],
    }


def _fight_consolidation_commit_plan(
    game_state: Dict[str, Any], unit: Dict[str, Any], plan: MovePlan
) -> None:
    """Pose le plan de consolidation par-figurine (``commit_move`` type ``consolidation``) + resync l'ancre."""
    from .shared_utils import commit_move, set_unit_coordinates

    commit_move(plan, game_state, "consolidation")
    entry = require_key(game_state, "units_cache").get(str(require_key(unit, "id")))
    if entry is not None:
        set_unit_coordinates(unit, int(entry["col"]), int(entry["row"]))


def _fight_v11_clear_consolidation_preview(game_state: Dict[str, Any]) -> None:
    """Purge l'aperçu de consolidation ET les **deux** sélections (engaging + objective) — sinon
    un objectif/une cible choisi reste collé au changement d'unité active / fin de conso."""
    game_state.pop("consolidation_engaging_selection", None)
    game_state.pop("consolidation_objective_selection", None)


# --- Engaging « New Foes to Face » (12.08 AFTER, §8.C) : résolution CIBLÉE ---------------------
# Au commit engaging, les ennemis engagés avec U non encore « selected to fight » doivent combattre
# (12.08). Sélecteur = ADVERSAIRE de U, sur un pool EXPLICITE restreint à ces unités (PAS
# fight_v11_advance_selection, qui relancerait l'alternance 12.04 entière — cf. §8.C). La liste est
# GELÉE au commit ; chaque New Foe résout un NORMAL fight via le flux d'allocation manuel existant.
# Invariants : I1 (U consolide 1×, consolidation_done), I2 (New Foe combat 1×, units_selected_to_fight),
# I3 (pas de double bascule), I4 (joueur actif finit ses consos avant l'adversaire — grouped_next),
# I5 (un New Foe devient consolidable côté adverse — fight_v11_is_consolidation_eligible le ramasse).


def _fight_v11_consolidation_new_foes_remaining(game_state: Dict[str, Any]) -> List[str]:
    """New Foes (liste gelée) encore vivants ET non encore « selected to fight »."""
    pending = game_state.get("consolidation_new_foes_pending")
    if not pending:
        return []
    selected = {str(x) for x in game_state.get("units_selected_to_fight", set())}
    out: List[str] = []
    for nf in pending:
        nf = str(nf)
        if nf in selected or not is_unit_alive(nf, game_state):
            continue
        out.append(nf)
    return out


def _fight_v11_consolidation_clear_new_foes(game_state: Dict[str, Any]) -> None:
    game_state.pop("consolidation_new_foes_pending", None)
    game_state.pop("consolidation_new_foes_selector", None)
    game_state.pop("consolidation_new_foes_for_unit", None)


def _fight_v11_consolidation_new_foes_state(game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Payload d'attente présentant les New Foes restants au sélecteur (adversaire). ``None`` quand
    la liste est épuisée (→ purge des clés et reprise de la consolidation par l'appelant)."""
    remaining = _fight_v11_consolidation_new_foes_remaining(game_state)
    if not remaining:
        _fight_v11_consolidation_clear_new_foes(game_state)
        return None
    selector = int(
        game_state.get("consolidation_new_foes_selector", 3 - int(require_key(game_state, "current_player")))
    )
    for_unit = game_state.get("consolidation_new_foes_for_unit")
    game_state["fight_eligible_units"] = list(remaining)
    active = game_state.get("active_fight_unit")
    active = str(active) if active is not None else None
    if active is not None and active in remaining:
        u = get_unit_by_id(game_state, active)
        valid = _fight_build_valid_target_pool(game_state, u) if u else []
        game_state["valid_fight_targets"] = valid
        return {
            "phase": "fight", "fight_subphase": "consolidate",
            "consolidation_new_foes": list(remaining),
            "consolidation_new_foes_for_unit": str(for_unit) if for_unit is not None else None,
            "fight_selector": selector,
            "fight_eligible_units": list(remaining),
            "active_fight_unit": active, "valid_targets": valid,
            "waiting_for_player": True, "action": "wait",
        }
    game_state["active_fight_unit"] = None
    game_state["valid_fight_targets"] = []
    return {
        "phase": "fight", "fight_subphase": "consolidate",
        "consolidation_new_foes": list(remaining),
        "consolidation_new_foes_for_unit": str(for_unit) if for_unit is not None else None,
        "fight_selector": selector,
        "fight_eligible_units": list(remaining),
        "active_fight_unit": None, "valid_targets": [],
        "waiting_for_player": True, "action": "wait",
        "unitId": "SYSTEM",
    }


def _fight_v11_consolidation_resolve_new_foes(
    game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Au commit engaging : gèle les New Foes (ennemis engagés non sélectionnés) et présente le
    premier choix au sélecteur (adversaire). ``None`` si aucun New Foe (reprise immédiate)."""
    new_foes = fight_v11_engaging_triggered_unit_ids(game_state, unit)
    if not new_foes:
        return None
    game_state["consolidation_new_foes_pending"] = [str(x) for x in new_foes]
    game_state["consolidation_new_foes_for_unit"] = str(require_key(unit, "id"))
    game_state["consolidation_new_foes_selector"] = 3 - int(require_key(game_state, "current_player"))
    game_state["active_fight_unit"] = None
    _fight_v11_log(
        game_state,
        f"CONSOLIDATE engaging : New Foes to Face = {list(new_foes)} "
        f"(sélecteur P{game_state['consolidation_new_foes_selector']}, in-place)",
    )
    return _fight_v11_consolidation_new_foes_state(game_state)


def _fight_v11_consolidation_new_foes_step(
    game_state: Dict[str, Any],
    action: Dict[str, Any],
    config: Dict[str, Any],
    remaining: List[str],
) -> Tuple[bool, Dict[str, Any]]:
    """Résout une action sur un New Foe (attaquant) — NORMAL fight via le flux manuel existant.
    Sélecteur = adversaire, pool = ``remaining`` (restreint). Miroir de la résolution du dispatch
    FIGHT, sans relance de l'alternance 12.04."""
    atype = action.get("action")
    uid = action.get("unitId")
    uid = str(uid) if uid is not None else None
    active = game_state.get("active_fight_unit")
    active = str(active) if active is not None else None

    # L'adversaire choisit l'ordre : sélection d'un New Foe à faire combattre.
    if atype == "activate_unit":
        if uid is not None and uid in remaining:
            game_state["active_fight_unit"] = uid
            _fight_v11_log(game_state, f"NEW FOE {uid} ACTIVÉ (sélecteur adverse)")
        return _fight_v11_manual_state(game_state)

    if active is None or active not in remaining:
        return _fight_v11_manual_state(game_state)
    u = get_unit_by_id(game_state, active)
    if u is None:
        raise KeyError(f"New Foe {active} missing from game_state['units']")

    # Déclarations par-arme/figurine (calque du tir), puis validation.
    if atype in ("squad_fight_assign", "squad_fight_assign_weapon"):
        _fight_ensure_activation_started(game_state, active)
        target_id = str(require_key(action, "targetId"))
        if atype == "squad_fight_assign":
            model_id = str(require_key(action, "modelId"))
            if "weaponIndex" in action:
                m = require_key(game_state, "models_cache").get(model_id)
                if m is not None:
                    m["selectedCcWeaponIndex"] = int(action["weaponIndex"])
            squad_declare_fight_model(game_state, active, model_id, target_id)
        else:
            squad_declare_fight_weapon(game_state, active, int(require_key(action, "weaponIndex")), target_id)
        return _fight_v11_manual_state(game_state)

    if atype == "squad_fight_validate":
        from .shared_utils import init_pending_intents
        init_pending_intents(game_state)
        intents = game_state["pending_squad_fight_intents"].get(active, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
        if not intents:
            _fight_v11_log(game_state, f"NEW FOE validate {active} : aucune declaration -> ignore")
            return _fight_v11_manual_state(game_state)
        target_id = str(intents[0]["target_unit_id"])
        target_unit = get_unit_by_id(game_state, target_id)
        defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
        if not defender_human:
            raise RuntimeError(
                f"NEW FOE validate {active} : flux de declaration manuelle non supporte pour defenseur IA"
            )
        _fight_v11_register_selection(game_state, active)
        game_state["active_fight_unit"] = None
        alloc_result = build_manual_fight_allocation(game_state, active)
        if alloc_result.get("waiting_for_player"):
            return True, alloc_result
        return _fight_v11_manual_state(game_state)

    # Clic direct sur une cible → résolution + allocation (defenseur humain) ou auto (IA).
    if atype in ("fight", "left_click"):
        valid = _fight_build_valid_target_pool(game_state, u)
        if not valid:
            # Aucun ennemi à frapper (cas limite) : le New Foe est tout de même « selected to fight ».
            _fight_v11_register_selection(game_state, active)
            game_state["active_fight_unit"] = None
            _fight_v11_log(game_state, f"NEW FOE {active} : aucune cible valide (sélectionné sans attaque)")
            return _fight_v11_manual_state(game_state)
        _fight_v11_register_selection(game_state, active)
        pref = str(action["targetId"]) if "targetId" in action else None
        target_id = pref if (pref is not None and pref in valid) else _ai_select_fight_target(game_state, active, valid)
        target_unit = get_unit_by_id(game_state, target_id)
        defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
        game_state["active_fight_unit"] = None
        _fight_v11_log(game_state, f"NEW FOE {active} -> cible {target_id} (clic={pref}) defenseur_humain={defender_human}")
        if defender_human:
            # Meme regle qu au dispatch FIGHT : le clic-cible repart de zero.
            squad_fight_restart_activation(game_state, active)
            squad_declare_fight(game_state, active, target_id)
            alloc_result = build_manual_fight_allocation(game_state, active)
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
        else:
            _fight_v11_resolve_attacks(game_state, u, config, preferred_target_id=target_id)
        return _fight_v11_manual_state(game_state)

    return _fight_v11_manual_state(game_state)


def _fight_v11_manual_state(game_state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """État actionnable courant pour le joueur humain (PvP). Avance les transitions de sous-phase."""
    for _ in range(64):
        sub = require_key(game_state, "fight_subphase")
        if sub == "pile_in":
            nxt = fight_v11_grouped_next(game_state, "pile_in")
            if nxt is None:
                fight_v11_enter_fight_step(game_state)
                continue
            # Présentation PARESSEUSE : on n'auto-présente AUCUNE unité (aucun BFS calculé
            # d'avance). Le joueur choisit librement l'unité à piler (clic → activate_unit,
            # qui déclenche le calcul de SES destinations) ou termine l'étape (end_pile_in).
            # On expose seulement le pool cliquable + aucune unité active.
            player, eligible = nxt
            done = {str(x) for x in game_state.get("pile_in_done", set())}
            pool = [str(u) for u in eligible if str(u) not in done]
            game_state["fight_eligible_units"] = pool
            game_state["active_fight_unit"] = None
            _fight_v11_log(
                game_state,
                f"PILE IN P{player} : unités éligibles = {pool} (sélection libre)",
            )
            return True, {
                "phase": "fight", "fight_subphase": "pile_in",
                "fight_eligible_units": pool,
                "active_fight_unit": None,
                "waiting_for_player": True, "action": "wait",
                "unitId": "SYSTEM",
            }
        if sub == "fight":
            # advance_selection synchronise fight_step/fight_selector (handoff 12.04) et
            # termine l'étape si plus personne n'est éligible. On ignore l'unité renvoyée :
            # le JOUEUR choisit librement parmi le pool du sélecteur courant (12.04), au lieu
            # de se voir imposer la première.
            if fight_v11_advance_selection(game_state) is None:
                fight_v11_enter_consolidate(game_state)
                continue
            pool = fight_v11_current_pool(game_state)
            if not pool:
                fight_v11_enter_consolidate(game_state)
                continue
            game_state["fight_eligible_units"] = list(pool)
            active = game_state.get("active_fight_unit")
            active = str(active) if active is not None else None
            if active is not None and active in pool:
                # L'unité a été choisie (activate_unit) → on présente ses cibles à frapper.
                u = get_unit_by_id(game_state, active)
                valid_targets = _fight_build_valid_target_pool(game_state, u) if u else []
                game_state["valid_fight_targets"] = valid_targets
                # Declarations offensives en cours (flux manuel par arme/figurine).
                fight_decls = [
                    {"model_id": i["model_id"], "weapon_index": i["weapon_index"],
                     "target_unit_id": i["target_unit_id"]}
                    for i in game_state.get("pending_squad_fight_intents", {}).get(active, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
                ]
                _fight_v11_log(
                    game_state,
                    f"état: FIGHT — unit {active} ACTIVE (selector=P{game_state['fight_selector']}, "
                    f"cibles={valid_targets}, declarations={len(fight_decls)})",
                )
                return True, {"phase": "fight", "fight_subphase": "fight",
                              "fight_step": game_state["fight_step"],
                              "fight_selector": game_state["fight_selector"],
                              "fight_eligible_units": list(pool),
                              "active_fight_unit": active, "valid_targets": valid_targets,
                              "declarations": fight_decls,
                              "overrun_eligible": bool(u and fight_v11_is_overrun_eligible(game_state, u)),
                              "waiting_for_player": True, "action": "wait"}
            # Aucune unité active → le joueur doit choisir (cercle vert sur le pool).
            game_state["active_fight_unit"] = None
            game_state["valid_fight_targets"] = []
            _fight_v11_log(
                game_state,
                f"état: FIGHT — choisir une unité (selector=P{game_state['fight_selector']}, "
                f"pool={list(pool)})",
            )
            return True, {"phase": "fight", "fight_subphase": "fight",
                          "fight_step": game_state["fight_step"],
                          "fight_selector": game_state["fight_selector"],
                          "fight_eligible_units": list(pool),
                          "active_fight_unit": None, "valid_targets": [],
                          "waiting_for_player": True, "action": "wait"}
        if sub == "consolidate":
            # New Foes to Face en cours (12.08 engaging AFTER) : tant qu'il en reste, on les
            # présente à l'adversaire AVANT de reprendre la consolidation (résolution immédiate, §8.C).
            if "consolidation_new_foes_pending" in game_state:
                nf_state = _fight_v11_consolidation_new_foes_state(game_state)
                if nf_state is not None:
                    return True, nf_state
            nxt = fight_v11_grouped_next(game_state, "consolidate")
            if nxt is None:
                return True, _fight_v11_phase_complete(game_state)
            # Présentation PARESSEUSE (miroir pile_in) : pool cliquable, aucune unité active.
            # Le joueur choisit l'unité à consolider (activate_unit) ou termine (end_consolidation).
            # Les sélections (engaging/objective) sont gérées au niveau de l'unité activée et ne
            # sont PAS purgées ici (sinon un refresh perdrait la sélection en cours).
            player, eligible = nxt
            done = {str(x) for x in game_state.get("consolidation_done", set())}
            pool = [str(u) for u in eligible if str(u) not in done]
            game_state["fight_eligible_units"] = pool
            game_state["active_fight_unit"] = None
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE P{player} : unités éligibles = {pool} (sélection libre)",
            )
            return True, {
                "phase": "fight", "fight_subphase": "consolidate",
                "fight_eligible_units": pool,
                "active_fight_unit": None,
                "waiting_for_player": True, "action": "wait",
                "unitId": "SYSTEM",
            }
        return True, _fight_v11_phase_complete(game_state)
    raise RuntimeError("_fight_v11_manual_state did not converge")


# ============================================================================
# COMBAT MANUEL — allocation des pertes par le defenseur (PvP), regles 05.03/05.04
# ============================================================================
# Reutilise le moteur d allocation generique (shared_utils) via FIGHT_CTX. La RESOLUTION
# des jets reste specifique au combat (_manual_roll_fight_intent : rerolls fight preserves,
# §B/§O). L application des degats est PAR-FIGURINE (update_model_hp/destroy_model) + les
# invalidations de cache fight (§D), via les hooks du ctx. Le chemin auto (PvE/gym) reste
# strictement inchange (HP-pool unite).


def _weapon_attacks_single_target(
    game_state: Dict[str, Any], attacker_squad_id: str, attacker_mid: str,
    weapon_index: int, target_sid: str,
) -> bool:
    """True si TOUTES les attaques de cette arme (cette figurine) visent UNE seule unite.

    Clause de [CLEAVE] 24.06 (« if you only selected one target for all of that weapon's
    attacks »). La declaration gym n emet qu une cible par activation ; le flux PvP par arme
    permet de repartir les attaques d une meme arme sur plusieurs unites — dans ce cas la
    regle ne s applique pas. Aucun repli : la liste d intents est exigee.
    """
    intents = require_key(game_state, "pending_squad_fight_intents").get(str(attacker_squad_id), [])  # get allowed (escouade sans declaration = aucune attaque)
    targets = {
        str(require_key(i, "target_unit_id"))
        for i in intents
        if str(require_key(i, "model_id")) == str(attacker_mid)
        and int(require_key(i, "weapon_index")) == int(weapon_index)
    }
    return targets == {str(target_sid)}


def _manual_roll_fight_intent(
    game_state: Dict[str, Any], intent: Dict[str, Any], targets_meta: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Jets melee d un intent (manuel) : hit -> wound (vs T majoritaire) -> save_roll BRUT,
    avec les 4 rerolls de combat (reroll_1_tohit / reroll_towound_objective / reroll_1_towound
    cote attaquant ; reroll_1_save cote cible). Ne compare PAS la save et ne tire PAS les
    degats (differes a l allocation, par figurine choisie). Meme forme de retour que le
    roller tir, consommee par _build_manual_allocation."""
    import random
    models_cache = require_key(game_state, "models_cache")
    attacker_mid = intent["model_id"]
    attacker = models_cache.get(attacker_mid)
    if attacker is None:
        return None
    target_sid = str(intent["target_unit_id"])
    if target_sid not in game_state.get("squad_models", {}):  # get allowed
        return None
    target = get_unit_by_id(game_state, target_sid)
    if target is None:
        return None
    if target_sid not in targets_meta:
        _tgt_uc = require_key(game_state, "units_cache")[target_sid]
        _tgt_sc = require_key(game_state, "squad_cache")[target_sid]
        targets_meta[target_sid] = {
            "value": float(require_key(_tgt_uc, "VALUE")),
            "model_count_at_start": int(require_key(_tgt_sc, "model_count_at_start")),
            "player": int(require_key(_tgt_uc, "player")),
        }
    weapon_index = int(intent.get("weapon_index", 0))  # get allowed
    weapons = melee_weapons(attacker)
    if not (0 <= weapon_index < len(weapons)):
        return None
    weapon = weapons[weapon_index]
    if not isinstance(weapon, dict):
        return None
    n_attacks = int(intent["n_attacks_resolved"]) if "n_attacks_resolved" in intent else 0
    # [CLEAVE X] 24.06 : « Each time you gather attack dice for a [CLEAVE] weapon, IF YOU ONLY
    # SELECTED ONE TARGET for all of that weapon's attacks, add X additional attack dice for
    # every five models that were in the target unit in the Select Targets step (rounding
    # down). » Jumeau melee de [BLAST] 24.05, avec la clause « une seule cible » en plus.
    from engine.utils.weapon_helpers import weapon_rule_parameter_or
    _cleave_x = weapon_rule_parameter_or(weapon, "CLEAVE", 1)
    _cleave_extra_dice = 0
    if _cleave_x is not None and _weapon_attacks_single_target(
        game_state, str(attacker["squad_id"]), attacker_mid, weapon_index, target_sid
    ):
        _tgt_size = int(require_key(intent, "target_squad_size_at_declaration"))
        # Des REELLEMENT ajoutes : 0 si la cible compte moins de 5 figurines, ou si les
        # attaques de l arme sont reparties sur plusieurs cibles. Jumeau de [BLAST] au tir.
        _cleave_extra_dice = _cleave_x * (_tgt_size // 5)
        n_attacks += _cleave_extra_dice
    if n_attacks <= 0:
        return None
    ws = int(weapon["ATK"])
    # Jumeau melee du tir : `STR`/`AP` sont portes par les 185 profils de melee des rosters.
    # L ancien enchainement retombait sur `S` (fossile), puis sur l ENDURANCE DE L ATTAQUANT
    # (caracteristique de figurine, sans rapport avec l arme), puis sur 4 ; `AP` sur 0.
    strength = int(require_key(weapon, "STR"))
    ap = int(require_key(weapon, "AP"))
    dmg_raw = require_key(weapon, "DMG")
    alive0 = [m for m in game_state["squad_models"].get(target_sid, []) if m in models_cache]  # get allowed
    if not alive0:
        return None
    # Attaquant (escouade) resolu ICI et non plus bas : le Waaagh! (chantier 03) modifie les
    # CARACTERISTIQUES de l arme (« add 1 to the Strength and Attacks characteristics of melee
    # weapons equipped by models from your army with this ability »), donc AVANT le seuil de
    # blessure et avant la taille du pool d attaques — pas au moment des relances.
    attacker_unit = get_unit_by_id(game_state, str(attacker["squad_id"]))
    _waaagh_bonus = 0 if attacker_unit is None else waaagh_melee_bonus(game_state, attacker_unit)
    strength += _waaagh_bonus
    n_attacks += _waaagh_bonus
    wth = _calculate_wound_target(strength, _target_highest_bodyguard_toughness(game_state, target_sid))
    # Oath of Moment : MEME helper que le tir (modelisation par abaissement du seuil, plancher
    # a 2, et une seule interrogation de `unit_is_oath_target_of` pour les deux effets).
    _is_oath_target, _oath_wound_bonus, wth = resolve_oath_effects(
        game_state, attacker_unit, target_sid, wth
    )
    first_alive = models_cache[alive0[0]]
    display_wth = wth
    # Seuil affiche + Waaagh! de la CIBLE (invulnerable 5+ octroyee) : helper partage avec le
    # tir, la sauvegarde octroyee s opposant aux deux types d attaques.
    display_save_th, _waaagh_target_invul = display_save_threshold_with_waaagh(
        game_state, target, first_alive, ap
    )
    weapon_name = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))  # get allowed
    # Conditions de reroll (constantes pour cet intent : abilities UNITE, pas figurine).
    # `attacker_unit` est resolu plus haut (les caracteristiques d arme en dependent).
    reroll_hit1 = attacker_unit is not None and _unit_has_rule(attacker_unit, "reroll_1_tohit_fight")
    # Oath of Moment : « You can re-roll the Hit roll » contre la cible designee. Jumeau EXACT
    # du site de tir (`shared_utils._manual_roll_intent`) — c est la moitie de la capacite qui
    # ne depend ni du detachement ni des sous-factions.
    reroll_hit_any = _is_oath_target
    reroll_wound1 = attacker_unit is not None and _unit_has_rule(attacker_unit, "reroll_1_towound")
    reroll_wound_obj = (
        attacker_unit is not None
        and _unit_has_rule(attacker_unit, "reroll_towound_target_on_objective")
        and _is_unit_on_objective(target, game_state)
    )
    reroll_save1 = _unit_has_rule(target, "reroll_1_save_fight")
    # Meme socle que le tir (05.01/05.02 + regles d armes 24) : les armes de melee declarent
    # elles aussi [DEVASTATING WOUNDS], [SUSTAINED HITS], [LETHAL HITS], [ANTI-X],
    # [TWIN-LINKED] — elles etaient jusqu ici ignorees en melee (aucune lecture de
    # WEAPON_RULES dans ce roller). Le socle corrige aussi le 1 non modifie, qui rate
    # toujours (05.01) : le test `hit_roll < ws` seul le laissait passer si ws valait 1.
    from engine.phase_handlers.attack_sequence import (
        RerollProfile, build_weapon_attack_profile, roll_attack_pool,
    )
    from engine.utils.weapon_helpers import weapon_has_rule, weapon_rule_signature
    _attack_profile = build_weapon_attack_profile(weapon, target)
    rolled = roll_attack_pool(
        n_attacks=int(n_attacks),
        hit_target=ws,
        wound_target=wth,
        save_threshold_value=display_save_th,
        profile=_attack_profile,
        rerolls=RerollProfile(
            hit_1=reroll_hit1, hit_any_fail=reroll_hit_any, wound_1=reroll_wound1,
            wound_any_fail=reroll_wound_obj, save_1=reroll_save1,
        ),
        roll_d6=lambda: random.randint(1, 6),
    )
    # Noms des ABILITES qui ont ouvert les relances — MEME helper que le tir, donc plus de
    # divergence possible. Sans lui, `step.log` dit que la relance etait POSSIBLE, jamais
    # qu elle a EU LIEU.
    stamp_reroll_abilities(
        rolled["shot_records"], attacker_unit,
        reroll_1_towound=reroll_wound1,
        reroll_towound_on_objective=reroll_wound_obj,
    )
    # +1 au jet de blessure d Oath. Meme helper que le tir (cf. `stamp_wound_bonus_ability`).
    stamp_wound_bonus_ability(rolled["shot_records"], _oath_wound_bonus)
    # L27 — nom de la capacite de relance de sauvegarde (reroll_1_save_fight). La cause est
    # COTE CIBLE (pas de l'attaquant) : le record porte deja `saveRollInitial` quand la relance
    # a eu lieu (attack_sequence.py). On n'ajoute le nom que si la relance a REELLEMENT joue.
    if reroll_save1:
        _save_ability_name = _get_source_unit_rule_display_name_for_effect(target, "reroll_1_save_fight")
        if _save_ability_name:
            for _rec in rolled["shot_records"]:
                if _rec.get("saveRollInitial") is not None:  # get allowed : relance effective
                    _rec["saveAbility"] = _save_ability_name
    # WAAAGH! : « add 1 to the Strength and Attacks characteristics of melee weapons ». Les deux
    # moities sont appliquees plus haut (`strength += _waaagh_bonus`, `n_attacks += _waaagh_bonus`)
    # mais RIEN ne le disait dans step.log — ni token, ni compteur. Consequence mesuree sur le run
    # de 600 episodes : un WarTrakk (Choppa NB=5) portait 6 attaques, l analyzer plafonnait a 5 et
    # remontait « Attacks over CC_NB » ; et la section « 1.7 Special rules usage » affichait 0
    # utilisation de `waaagh` — un vert vacant, sur une capacite qui avait bel et bien tire.
    # Le drapeau est pose par ATTAQUE et non par ligne d unite : c est la granularite du record,
    # donc la seule qui ne puisse pas se desynchroniser du jet qu elle decrit.
    if _waaagh_bonus:
        for _rec in rolled["shot_records"]:
            _rec["waaaghMelee"] = True
    return {
        "attacker_mid": attacker_mid, "attacker": attacker, "target_sid": target_sid,
        "weapon_name": weapon_name, "bs": ws, "ap": ap, "dmg_raw": dmg_raw,
        # [MELTA] 24.25 est indexee sur la demi-portee d une arme de TIR : aucune arme de melee
        # ne la declare (les armories n en contiennent aucune). Le champ existe car l allocation
        # est mutualisee tir/melee et l exige explicitement (aucun defaut implicite).
        "dmg_bonus": 0,
        # [PRECISION] 24.28 (melee) : `precision_range=None` -> visibilite acquise au contact
        # (06.01 : aucun terrain ne s interpose a distance d engagement).
        "precision": weapon_has_rule(weapon, "PRECISION"),
        "precision_range": None,
        # Arme et regles resolues vs CETTE cible — JUMEAU exact du roller de tir. Le log en tire
        # ses tokens a l emission, via le MEME `weapon_rule_log_tokens`, pour qu une regle ne
        # puisse pas etre nommee d un cote et muette de l autre.
        "weapon": weapon,
        "attack_profile": _attack_profile,
        # 10.06 est une regle de la phase de TIR : elle n a pas de jumeau en melee. La cle est
        # ECRITE et non omise — c est au producteur d affirmer que la regle ne s applique pas,
        # pas au lecteur de le deviner par un defaut.
        "point_blank_malus": False,
        # [ASSAULT] 24.04 (10.05) et [CLOSE-QUARTERS] 24.07 (10.06) : memes regles d ELIGIBILITE
        # AU TIR, donc meme regime que `point_blank_malus` — ecrites `False` par le producteur
        # de melee, jamais laissees au defaut d un lecteur.
        "assault_applied": False,
        "close_quarters_applied": False,
        # Ranged-only : la melee affirme que la regle n a pas joue plutot que de laisser le
        # lecteur derider depuis l absence de cle (T1 : donnee obligatoire absente -> erreur).
        "indirect_fire_fail_below": None,
        # [CLEAVE] 24.06 : a-t-elle joue pour CETTE figurine, et avec quel X declare ? La clause
        # « une seule cible » se juge par figurine, deux porteuses de la meme arme peuvent donc
        # differer. Reunie sur le groupe, jumeau de [BLAST]/[RAPID FIRE] au tir. La table est
        # ECRITE meme vide : la cle de groupe partagee l'exige (`require_key`), donc un
        # producteur qui l'oublierait leve au lieu de valoir « aucune regle », comme l'exige T1.
        # [RAPID FIRE] n'existe qu'au TIR : son entree n'apparait jamais ici, et le X applique
        # que la cle de groupe et le step.log y lisent vaut donc 0 pour toute la melee.
        "additive_rules_applied": (
            {RULE_LABEL_CLEAVE: _cleave_x}
            if _cleave_extra_dice > 0 and _cleave_x is not None else {}
        ),
        # 04.03 IDENTICAL ATTACKS : jumeau exact du roller de tir — la seconde moitie de la
        # definition (« affected by the same applicable abilities and rules ») entre dans la
        # cle de groupe, en melee comme au tir.
        "weapon_rules": weapon_rule_signature(weapon),
        "display_wth": display_wth, "display_save_th": display_save_th,
        # Oath dans la ligne de synthese — JUMEAU du roller de tir (meme cles, meme raison).
        "oath_hit_reroll": bool(_is_oath_target),
        # Booleen, comme le tir : la magnitude est deja absorbee dans `wth` ci-dessus.
        "oath_wound_bonus": bool(_oath_wound_bonus),
        # Waaagh! de l ATTAQUANT dans la ligne de synthese. UN seul drapeau pour les deux
        # caracteristiques : la regle accorde +1 Force et +1 Attaque d un seul tenant
        # (`waaagh_melee_bonus`), et en faire deux booleens laisserait croire qu un site peut
        # appliquer l une sans l autre. La magnitude est deja absorbee (`strength` et
        # `n_attacks` ci-dessus) : le log ne demande que « est-ce que ca a joue ».
        "waaagh_melee_bonus": bool(_waaagh_bonus),
        # Waaagh! de la CIBLE : sauvegarde invulnerable octroyee ET reellement meilleure.
        "waaagh_target_invul": _waaagh_target_invul,
        "shot_records": rolled["shot_records"], "pending_wounds": rolled["pending_wounds"],
        "counts": rolled["counts"],
    }


def _fight_on_target_damaged(game_state: Dict[str, Any], target_sid: str) -> None:
    """Hook fight : invalide le kill_probability_cache de la cible a chaque blessure (§D)."""
    from engine.ai.weapon_selector import invalidate_cache_for_target
    cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
    invalidate_cache_for_target(cache, str(target_sid))


def _fight_on_unit_destroyed(game_state: Dict[str, Any], target_sid: str) -> None:
    """Hook fight : unite cible detruite -> retrait des pools de combat + invalidation cache (§D)."""
    _remove_dead_unit_from_fight_pools(game_state, str(target_sid))
    from engine.ai.weapon_selector import invalidate_cache_for_unit
    cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
    invalidate_cache_for_unit(cache, str(target_sid))


def _fight_auto_defender(game_state: Dict[str, Any], target_sid: str) -> bool:
    """Decideur auto du moteur d allocation combat (05.04) : True si le defenseur de la
    cible est controle par l IA -> le moteur tranche ordre + choix de figurine sans rendre
    la main. Aucun repli silencieux : cible introuvable = bug -> erreur explicite."""
    target = get_unit_by_id(game_state, str(target_sid))
    if target is None:
        raise KeyError(f"_fight_auto_defender: cible {target_sid!r} introuvable")
    return _is_ai_controlled_fight_unit(game_state, target)


FIGHT_CTX = ManualAllocCtx(
    alloc_key="pending_fight_allocation",
    declare_order_action="squad_fight_declare_order",
    manual_alloc_action="squad_fight_manual_alloc",
    phase_label="fight",
    log_type="combat",
    log_verb="FOUGHT",
    attacks_left_attr="ATTACK_LEFT",
    intents_key="pending_squad_fight_intents",
    weapons_key="CC_WEAPONS",
    # [HAZARDOUS] 24.15 : « each time a unit is selected to shoot OR SELECTED TO FIGHT ».
    hazard_origin="fight",
    decrement_by_attacks=True,
    emit_unit_death_log=True,
    on_target_damaged=_fight_on_target_damaged,
    on_unit_destroyed=_fight_on_unit_destroyed,
    auto_decider=_fight_auto_defender,
)


def build_manual_fight_allocation(game_state: Dict[str, Any], attacker_squad_id: str) -> Dict[str, Any]:
    """Allocation manuelle des pertes au COMBAT (defenseur humain). Cf. _build_manual_allocation."""
    return _build_manual_allocation(game_state, attacker_squad_id, FIGHT_CTX, _manual_roll_fight_intent)


def _fight_v11_manual_step(
    game_state: Dict[str, Any],
    unit: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Traite une action humaine (PvP) dans l'étape V11 courante, puis renvoie l'état suivant."""
    sub = require_key(game_state, "fight_subphase")
    atype = action.get("action")
    uid = action.get("unitId")
    if uid is None and unit is not None:
        uid = unit["id"]
    uid = str(uid) if uid is not None else None
    skip = action.get("skip") is True or atype in ("skip", "right_click")
    _fight_v11_log(game_state, f"action manuelle reçue: subphase={sub} action={atype!r} unitId={uid} skip={skip}")

    # Allocation manuelle des pertes (defenseur) en cours : seules les actions d allocation
    # passent ; toute autre action re-signale l attente (garde-fou, §J).
    if "pending_fight_allocation" in game_state:
        if atype == "squad_fight_declare_order":
            order = action.get("order")
            if order is None:
                return False, {"error": "missing_order"}
            res = apply_manual_shoot_declare_order(game_state, list(order), FIGHT_CTX)
            if res.get("waiting_for_player"):
                return True, res
            return _fight_v11_manual_state(game_state)
        if atype == "squad_fight_manual_alloc":
            chosen = action.get("modelId")
            if chosen is None:
                return False, {"error": "missing_model_id"}
            res = apply_manual_shoot_allocation(game_state, str(chosen), FIGHT_CTX)
            if res.get("waiting_for_player"):
                return True, res
            return _fight_v11_manual_state(game_state)
        if atype == "squad_fight_cancel":
            del game_state["pending_fight_allocation"]
            _fight_v11_log(game_state, "FIGHT allocation annulee par le joueur")
            return _fight_v11_manual_state(game_state)
        return True, manual_allocation_waiting_payload(game_state, FIGHT_CTX)

    # Combat cible-d abord par arme/quantite/figurine (jumeau du tir). Traite ICI, dans la
    # machine V11, et NON dans w40k_core : le garde-fou d allocation ci-dessus s applique donc
    # automatiquement (ces actions ne sont atteintes que hors allocation en cours). Lectures =
    # return immediat ; mutations = declaration puis etat manuel V11 rafraichi.
    if atype in (
        "squad_fight_menu_weapons", "squad_fight_weapons_for_target",
        "squad_fight_models_status", "squad_fight_models_weapons",
        "squad_fight_eligible_models", "squad_fight_weapon_qty_max",
        "squad_fight_assign_weapon_qty", "squad_fight_unassign_weapon_qty",
        "squad_fight_toggle_model_weapon",
    ):
        squad_id = str(require_key(action, "unitId"))
        # Idempotent : garantit pending_squad_fight_intents[squad_id] pour les lectures/menus.
        _fight_ensure_activation_started(game_state, squad_id)

        if atype == "squad_fight_menu_weapons":
            return True, {
                "action": atype, "unitId": squad_id,
                "weapons": squad_fight_menu_weapons(game_state, squad_id),
            }

        if atype == "squad_fight_weapons_for_target":
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            model_id = action.get("modelId")  # optionnel : menu par-fig (m/x scopes)
            return True, {
                "action": atype, "unitId": squad_id, "targetId": str(target_id),
                "weapons": squad_fight_weapons_for_target(
                    game_state, squad_id, str(target_id),
                    None if model_id is None else str(model_id),
                ),
            }

        if atype == "squad_fight_models_weapons":
            return True, {
                "action": atype, "unitId": squad_id,
                "models": squad_fight_models_weapons(game_state, squad_id),
            }

        if atype == "squad_fight_models_status":
            target_id = action.get("targetId")
            if target_id is None:
                return False, {"error": "missing_targetId"}
            return True, {
                "action": atype, "unitId": squad_id, "targetId": str(target_id),
                "models": squad_fight_models_status(game_state, squad_id, str(target_id)),
            }

        if atype == "squad_fight_eligible_models":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            return True, {
                "action": atype, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id),
                "models": squad_fight_eligible_models(game_state, squad_id, str(weapon_code), str(target_id)),
            }

        if atype == "squad_fight_weapon_qty_max":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : borne par-fig
            return True, {
                "action": atype, "unitId": squad_id, "weaponCode": str(weapon_code),
                "targetId": str(target_id),
                "qty_max": squad_fight_weapon_qty_max(
                    game_state, squad_id, str(weapon_code), str(target_id),
                    None if model_id is None else str(model_id),
                ),
            }

        if atype == "squad_fight_assign_weapon_qty":
            weapon_code = action.get("weaponCode")
            count_raw = action.get("count")
            if weapon_code is None or count_raw is None:
                return False, {"error": "missing_weaponCode_or_count"}
            try:
                count = int(count_raw)
            except (TypeError, ValueError):
                return False, {"error": "invalid_count_type"}
            target_id = str(require_key(action, "targetId"))
            model_id = action.get("modelId")  # optionnel : attribution par-fig
            try:
                squad_declare_fight_weapon_qty(
                    game_state, squad_id, str(weapon_code), count, target_id,
                    None if model_id is None else str(model_id),
                )
            except ValueError as e:
                return False, {"error": "cannot_fight", "reason": str(e)}
            return _fight_v11_manual_state(game_state)

        if atype == "squad_fight_unassign_weapon_qty":
            weapon_code = action.get("weaponCode")
            target_id = action.get("targetId")
            if weapon_code is None or target_id is None:
                return False, {"error": "missing_weaponCode_or_targetId"}
            model_id = action.get("modelId")  # optionnel : retrait par-fig
            squad_undeclare_fight_weapon_qty(
                game_state, squad_id, str(weapon_code), str(target_id),
                None if model_id is None else str(model_id),
            )
            return _fight_v11_manual_state(game_state)

        # squad_fight_toggle_model_weapon
        model_id = action.get("modelId")
        weapon_code = action.get("weaponCode")
        target_id = action.get("targetId")
        if model_id is None or weapon_code is None or target_id is None:
            return False, {"error": "missing_modelId_weaponCode_or_targetId"}
        try:
            squad_fight_toggle_model_weapon(
                game_state, squad_id, str(model_id), str(weapon_code), str(target_id)
            )
        except ValueError as e:
            return False, {"error": "cannot_fight", "reason": str(e)}
        return _fight_v11_manual_state(game_state)

    if sub == "pile_in":
        nxt = fight_v11_grouped_next(game_state, "pile_in")
        eligible = nxt[1] if nxt else []
        if atype == "end_pile_in":
            # Bouton « Terminer le pile-in » : marque tout le groupe actif comme traité
            # (les unités non pilées sont simplement passées) → on avance vers le groupe
            # adverse puis la sous-phase FIGHT.
            for e in eligible:
                game_state["pile_in_done"].add(str(e))
            _fight_v11_log(
                game_state,
                f"PILE IN → fin demandée par le joueur (groupe {list(eligible)} marqué traité)",
            )
            return _fight_v11_manual_state(game_state)
        # --- Pile-in PAR-FIGURINE (move fin, miroir charge) ---
        active = game_state.get("active_fight_unit")
        act_uid = str(active) if active is not None else None

        _view_level = int(action.get("level") or 0)

        def _prov_from_action() -> Dict[str, Tuple[int, int, int]]:
            # Le niveau d'étage capturé au drop de chaque fig est OBLIGATOIRE : une fig posée sur
            # un étage y reste (§13.06, miroir move par-figurine).
            return parse_model_plan_as_map(
                action.get("plan") or [], action_name="pile_in plan"
            )

        if skip:
            # Le joueur renonce à piler l'unité active → marquée traitée sans déplacement.
            if act_uid is not None and act_uid in eligible:
                game_state["pile_in_done"].add(act_uid)
                _fight_v11_log(game_state, f"PILE IN unit {act_uid} → SKIP (joueur)")
            return _fight_v11_manual_state(game_state)

        if atype == "pile_in_plan_state":
            # Refresh de l'aperçu par-figurine (plan provisoire + figurine sélectionnée).
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            u = get_unit_by_id(game_state, act_uid)
            if u is None:
                raise KeyError(f"Pile-in unit {act_uid} missing from game_state['units']")
            sel = action.get("selected_model")
            return True, _fight_pile_in_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "pile_in_autoplace":
            # Focus : auto-placement optimal (ILP) des figs pour maximiser celles frappant la cible.
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            focus = action.get("targetId")
            if focus is None:
                return False, {"error": "pile_in_autoplace requires targetId", "action": action}
            mode = str(action.get("mode", "defensive"))
            out = pile_in_autoplace_plan(game_state, act_uid, str(focus), mode=mode)
            return True, {"action": "pile_in_autoplace", "unitId": act_uid, **out}

        if atype == "commit_pile_in_plan":
            # Validation finale : pose toutes les figs (posées + origine) si le plan est légal.
            if act_uid is None or act_uid not in eligible:
                return _fight_v11_manual_state(game_state)
            u = get_unit_by_id(game_state, act_uid)
            if u is None:
                raise KeyError(f"Pile-in unit {act_uid} missing from game_state['units']")
            prov = _prov_from_action()
            models_cache = require_key(game_state, "models_cache")
            squad_models = require_key(game_state, "squad_models")
            alive = [str(m) for m in require_key(squad_models, act_uid) if str(m) in models_cache]
            origin = {
                m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]),
                    int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
                for m in alive
            }
            full_plan: List[Tuple[str, int, int, int]] = [
                (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
                else (m, origin[m][0], origin[m][1], origin[m][2])
                for m in alive
            ]
            targets = _fight_v11_pile_in_targets(game_state, u)
            closest = _fight_pile_in_closest_tier_ids(game_state, u, targets) if targets else []
            prev = _fight_pile_in_preview_plan(game_state, act_uid, full_plan, closest)
            if not prev["can_validate"]:
                _fight_v11_log(game_state, f"PILE IN unit {act_uid} → plan invalide {prev}")
                return True, _fight_pile_in_model_plan_state(
                    game_state, u, prov, None, view_level=_view_level
                )
            _uc_before = require_key(game_state, "units_cache")[act_uid]
            _from_col, _from_row = int(_uc_before["col"]), int(_uc_before["row"])
            _fight_pile_in_commit_plan(game_state, u, full_plan)
            game_state["pile_in_done"].add(act_uid)
            # Log par-figurine (mode fin type charge, sans roll) : ligne unite + moveDetails.
            _uc_after = require_key(game_state, "units_cache")[act_uid]
            _to_col, _to_row = int(_uc_after["col"]), int(_uc_after["row"])
            _move_details = [
                {
                    "modelId": m,
                    "fromCol": origin[m][0],
                    "fromRow": origin[m][1],
                    "toCol": int(nc),
                    "toRow": int(nr),
                    "toLevel": int(nlv),
                }
                for m, nc, nr, nlv in full_plan
            ]
            _append_fight_move_log(
                game_state, u, kind="pile_in",
                from_col=_from_col, from_row=_from_row,
                to_col=_to_col, to_row=_to_row,
                move_details=_move_details,
                # L17 — cibles sélectionnées (= targets calculé juste avant commit).
                pile_in_target_ids=[str(t) for t in targets],
            )
            _fight_v11_log(
                game_state, f"PILE IN unit {act_uid} → commit par-figurine ({len(full_plan)} figs)"
            )
            return _fight_v11_manual_state(game_state)

        if atype == "activate_unit" and uid in eligible:
            # Sélection d'une unité à piler → présenter son plan par-figurine (mode fin).
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Pile-in unit {uid} missing from game_state['units']")
            game_state["active_fight_unit"] = uid
            done = {str(x) for x in game_state.get("pile_in_done", set())}
            game_state["fight_eligible_units"] = [e for e in eligible if str(e) not in done]
            state = _fight_pile_in_model_plan_state(
                game_state, u, view_level=_view_level
            )
            _fight_v11_log(
                game_state,
                f"PILE IN : unit {uid} sélectionnée (par-figurine, "
                f"{len(state['eligible_models'])} figs déplaçables)",
            )
            return True, state

        # Autre action en pile_in → ré-afficher l'état courant.
        return _fight_v11_manual_state(game_state)

    if sub == "fight":
        pool = fight_v11_current_pool(game_state)  # unités éligibles du sélecteur courant (12.04)
        active = game_state.get("active_fight_unit")
        active = str(active) if active is not None else None
        _fight_v11_log(
            game_state,
            f"FIGHT dispatch: pool={pool} active={active} uid_recu={uid} action={atype!r} "
            f"step={game_state.get('fight_step')} fought={sorted(game_state.get('units_fought', set()))}"
        )

        if skip:
            # « Passer » une unité en étape fight = clic droit (right_click → skip, calculé
            # plus haut). GARDÉ (encart 12 « you have to fight with all units that can ») :
            # autorisé UNIQUEMENT si l'unité active n'a AUCUNE cible valide. Sinon elle DOIT
            # combattre → skip refusé. Sans cible, elle est « selected to fight » sans attaque
            # (12.04) : elle sort du pool ET devient éligible à la consolidation (12.08).
            if active is not None and active in pool:
                u = get_unit_by_id(game_state, active)
                if u is None:
                    raise KeyError(f"Fight skip unit {active} missing from game_state['units']")
                valid = _fight_build_valid_target_pool(game_state, u)
                if valid:
                    _fight_v11_log(
                        game_state,
                        f"FIGHT skip REFUSÉ pour {active} : cibles valides {valid} "
                        f"(obligation de combattre, encart 12)",
                    )
                    return _fight_v11_manual_state(game_state)
                _fight_v11_register_selection(game_state, active)
                game_state["active_fight_unit"] = None
                _fight_v11_log(
                    game_state,
                    f"FIGHT unit {active} → passée (aucune cible valide, sélectionnée sans attaque)",
                )
            return _fight_v11_manual_state(game_state)

        if atype == "skip_fight":
            # Bouton « Skip » : abandonne TOUTES les attaques restantes (2 joueurs) et passe
            # directement à la consolidation. Contourne sciemment l'obligation de combattre
            # (raccourci de confort). Les unités encore éligibles sont marquées « selected to
            # fight » (sans attaque) pour rester éligibles à la consolidation (12.08, cf.
            # fight_v11_is_consolidation_eligible).
            for p in (1, 2):
                for e in fight_v11_eligible_unit_ids(game_state, p, fights_first_only=False):
                    game_state["units_selected_to_fight"].add(str(e))
            game_state["active_fight_unit"] = None
            fight_v11_enter_consolidate(game_state)
            _fight_v11_log(game_state, "FIGHT → SKIP global (toutes attaques abandonnées) → CONSOLIDATE")
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 1 — le joueur choisit librement une de SES unités éligibles (12.04).
        if atype == "activate_unit":
            if uid is not None and uid in pool:
                game_state["active_fight_unit"] = uid
                _fight_v11_log(game_state, f"FIGHT unit {uid} ACTIVÉE par le joueur")
            else:
                _fight_v11_log(game_state, f"FIGHT activate ignoré : {uid} hors pool {pool}")
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 2 (flux manuel par arme/figurine, calque du tir) — declarations
        # offensives puis validation. Additif : coexiste avec le clic-resolution direct.
        if active is not None and active in pool and atype in ("squad_fight_assign", "squad_fight_assign_weapon"):
            sel = active
            _fight_ensure_activation_started(game_state, sel)
            target_id = str(require_key(action, "targetId"))
            if atype == "squad_fight_assign":
                model_id = str(require_key(action, "modelId"))
                # Choix d arme optionnel par figurine (sinon arme courante / index 0).
                if "weaponIndex" in action:
                    models_cache = require_key(game_state, "models_cache")
                    m = models_cache.get(model_id)
                    if m is not None:
                        m["selectedCcWeaponIndex"] = int(action["weaponIndex"])
                squad_declare_fight_model(game_state, sel, model_id, target_id)
            else:
                widx = int(require_key(action, "weaponIndex"))
                squad_declare_fight_weapon(game_state, sel, widx, target_id)
            return _fight_v11_manual_state(game_state)

        # VALIDATION — resout les attaques DECLAREES (allocation manuelle des pertes).
        if active is not None and active in pool and atype == "squad_fight_validate":
            sel = active
            u = get_unit_by_id(game_state, sel)
            if u is None:
                raise KeyError(f"Fight unit {sel} missing from game_state['units']")
            from .shared_utils import init_pending_intents
            init_pending_intents(game_state)
            intents = game_state["pending_squad_fight_intents"].get(sel, [])  # fallback allowed — unité sans déclaration d'intent = liste vide (métier)
            if not intents:
                _fight_v11_log(game_state, f"FIGHT validate {sel} : aucune declaration -> ignore")
                return _fight_v11_manual_state(game_state)
            # Defenseur : en PvP test les cibles appartiennent au joueur adverse (humain).
            target_id = str(intents[0]["target_unit_id"])
            target_unit = get_unit_by_id(game_state, target_id)
            defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
            if not defender_human:
                raise RuntimeError(
                    f"FIGHT validate {sel} : flux de declaration manuelle non supporte "
                    f"pour un defenseur IA (cible {target_id})"
                )
            _fight_v11_register_selection(game_state, sel)
            game_state["active_fight_unit"] = None
            alloc_result = build_manual_fight_allocation(game_state, sel)
            _fight_v11_log(
                game_state,
                f"FIGHT validate {sel} : alloc waiting={alloc_result.get('waiting_for_player')}"
            )
            if alloc_result.get("waiting_for_player"):
                return True, alloc_result
            return _fight_v11_manual_state(game_state)

        # ÉTAPE 2 — unité active + clic sur une cible → résolution + allocation.
        if active is not None and active in pool and atype in ("fight", "left_click"):
            sel = active
            u = get_unit_by_id(game_state, sel)
            if u is None:
                raise KeyError(f"Fight unit {sel} missing from game_state['units']")
            _fight_v11_register_selection(game_state, sel)
            ftype = "normal"
            if action.get("fight_type") == "overrun" and fight_v11_is_overrun_eligible(game_state, u):
                ftype = "overrun"
                from .shared_utils import _fight_overrun_pile_in_plan, commit_move
                _ov_plan = _fight_overrun_pile_in_plan(game_state, sel)
                if _ov_plan is not None:
                    commit_move(_ov_plan, game_state, "pile_in")
            valid = _fight_build_valid_target_pool(game_state, u)
            _fight_v11_log(game_state, f"FIGHT unit {sel} (type={ftype}) : pool cibles = {valid}")
            if valid:
                pref = str(action["targetId"]) if "targetId" in action else None
                target_id = pref if (pref is not None and pref in valid) else _ai_select_fight_target(game_state, sel, valid)
                target_unit = get_unit_by_id(game_state, target_id)
                defender_human = target_unit is not None and not _is_ai_controlled_fight_unit(game_state, target_unit)
                _fight_v11_log(game_state, f"FIGHT unit {sel} -> cible {target_id} (clic={pref}) defenseur_humain={defender_human}")
                # L'unité a fini d'attaquer : on libère l'active (la prochaine sera re-choisie).
                game_state["active_fight_unit"] = None
                if defender_human:
                    # Defenseur humain (§G) : allocation manuelle des pertes (par-figurine).
                    # restart_ : le clic-cible redeclare toute l escouade, il ecrase donc
                    # ce que squad_fight_assign avait pu declarer avant lui.
                    squad_fight_restart_activation(game_state, sel)
                    squad_declare_fight(game_state, sel, target_id)
                    alloc_result = build_manual_fight_allocation(game_state, sel)
                    _fight_v11_log(
                        game_state,
                        f"FIGHT unit {sel} : alloc waiting={alloc_result.get('waiting_for_player')} done={alloc_result.get('done')}"
                    )
                    if alloc_result.get("waiting_for_player"):
                        return True, alloc_result
                else:
                    # Defenseur IA : resolution auto (chemin V11 inchange, HP-pool unite).
                    _fight_v11_log(game_state, f"FIGHT unit {sel} : defenseur IA -> resolution auto")
                    _fight_v11_resolve_attacks(game_state, u, config, preferred_target_id=target_id)
            else:
                _fight_v11_log(game_state, f"FIGHT unit {sel} : aucune cible valide")
            return _fight_v11_manual_state(game_state)

        _fight_v11_log(game_state, f"FIGHT: action ignorée (active={active}, uid={uid}, action={atype!r})")
        return _fight_v11_manual_state(game_state)

    if sub == "consolidate":
        # New Foes to Face (12.08 engaging AFTER, §8.C) : pool restreint à l'adversaire, prioritaire
        # sur la suite de la consolidation. PAS l'alternance 12.04.
        if "consolidation_new_foes_pending" in game_state:
            remaining = _fight_v11_consolidation_new_foes_remaining(game_state)
            if remaining:
                return _fight_v11_consolidation_new_foes_step(game_state, action, config, remaining)
            _fight_v11_consolidation_clear_new_foes(game_state)

        nxt = fight_v11_grouped_next(game_state, "consolidate")
        eligible = nxt[1] if nxt else []

        if atype == "end_consolidation":
            # « Terminer la consolidation » : marque tout le groupe actif comme traité.
            for e in eligible:
                game_state["consolidation_done"].add(str(e))
            game_state["active_fight_unit"] = None
            _fight_v11_clear_consolidation_preview(game_state)
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE → fin demandée par le joueur (groupe {list(eligible)} marqué traité)",
            )
            return _fight_v11_manual_state(game_state)

        active = game_state.get("active_fight_unit")
        act_uid = str(active) if active is not None else None

        _view_level = int(action.get("level") or 0)

        def _prov_from_action() -> Dict[str, Tuple[int, int, int]]:
            return parse_model_plan_as_map(
                action.get("plan") or [], action_name="consolidation plan"
            )

        if skip:
            # Le joueur renonce à consolider l'unité active → traitée sans déplacement.
            if act_uid is not None and act_uid in eligible:
                game_state["consolidation_done"].add(act_uid)
                game_state["active_fight_unit"] = None
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → SKIP (joueur)")
            _fight_v11_clear_consolidation_preview(game_state)
            return _fight_v11_manual_state(game_state)

        if atype == "cancel_consolidation":
            # Annulation du plan en cours : désélectionne l'unité SANS la consommer (elle reste
            # éligible/sélectionnable) et purge le preview + les sélections engaging/objective.
            if act_uid is not None:
                game_state["active_fight_unit"] = None
                _fight_v11_log(
                    game_state,
                    f"CONSOLIDATE unit {act_uid} → annulation (unité reste sélectionnable)",
                )
            _fight_v11_clear_consolidation_preview(game_state)
            return _fight_v11_manual_state(game_state)

        if atype == "activate_unit" and uid in eligible:
            # Sélection d'une unité à consolider → repart d'une sélection vierge + plan par-figurine.
            u = get_unit_by_id(game_state, uid)
            if u is None:
                raise KeyError(f"Consolidation unit {uid} missing from game_state['units']")
            game_state["active_fight_unit"] = uid
            _fight_v11_clear_consolidation_preview(game_state)
            done = {str(x) for x in game_state.get("consolidation_done", set())}
            game_state["fight_eligible_units"] = [e for e in eligible if str(e) not in done]
            state = _fight_consolidation_model_plan_state(
                game_state, u, view_level=_view_level
            )
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE : unit {uid} sélectionnée (mode={state.get('consolidation_mode')})",
            )
            return True, state

        # Actions portant sur l'unité active.
        if act_uid is None or act_uid not in eligible:
            return _fight_v11_manual_state(game_state)
        u = get_unit_by_id(game_state, act_uid)
        if u is None:
            raise KeyError(f"Consolidation unit {act_uid} missing from game_state['units']")

        if atype == "consolidation_select_target":
            # Engaging : toggle d'un ennemi candidat (≤3") dans la sélection préalable au move.
            target = action.get("targetId")
            if target is None:
                return False, {"error": "consolidation_select_target requires targetId", "action": action}
            tid = str(target)
            candidates = {str(c) for c in _fight_v11_consolidation_engaging_candidates(game_state, u)}
            if tid in candidates:
                sel_map = game_state.setdefault("consolidation_engaging_selection", {})
                cur = {str(x) for x in sel_map.get(act_uid, [])}  # fallback allowed — unité sans sélection préalable = ensemble vide (métier)
                if tid in cur:
                    cur.discard(tid)
                else:
                    cur.add(tid)
                sel_map[act_uid] = sorted(cur)
                _fight_v11_log(game_state, f"CONSOLIDATE engaging : sélection {act_uid} = {sel_map[act_uid]}")
            else:
                _fight_v11_log(game_state, f"CONSOLIDATE engaging : cible {tid} hors candidats {candidates}")
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidation_select_objective":
            # Objective : single-select de l'objectif (si >1 candidat).
            oid = action.get("objectiveId")
            if oid is None:
                return False, {"error": "consolidation_select_objective requires objectiveId", "action": action}
            candidates = _fight_v11_consolidation_objective_candidates(game_state, u)
            match = next((c for c in candidates if str(c) == str(oid)), None)
            if match is not None:
                game_state.setdefault("consolidation_objective_selection", {})[act_uid] = match
                _fight_v11_log(game_state, f"CONSOLIDATE objective : {act_uid} vise objectif {match}")
            else:
                _fight_v11_log(game_state, f"CONSOLIDATE objective : objectif {oid} hors candidats {candidates}")
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidation_plan_state":
            sel = action.get("selected_model")
            return True, _fight_consolidation_model_plan_state(
                game_state, u, _prov_from_action(), str(sel) if sel is not None else None,
                view_level=_view_level,
            )

        if atype == "consolidate_autoplace":
            # Focus off./déf. : auto-placement ILP conforme 12.08 (ongoing → pile-in ; engaging → charge).
            mode = str(action.get("mode", "defensive"))
            out = consolidate_autoplace_plan(game_state, act_uid, mode=mode)
            return True, {"action": "consolidate_autoplace", "unitId": act_uid, **out}

        if atype == "commit_consolidation_plan":
            mode, tier = _fight_v11_consolidation_targets(game_state, u)
            # Move bloqué tant que la sélection préalable n'est pas faite.
            blocked = (
                mode is None
                or (mode == "engaging" and not tier)
                or (mode == "objective" and tier is None)
            )
            if blocked:
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → commit bloqué (sélection requise, mode={mode})")
                return True, _fight_consolidation_model_plan_state(
                    game_state, u, _prov_from_action(), None, view_level=_view_level
                )
            # Invariant post-guard : mode/tier sont renseignés (None ⇒ blocked, déjà retourné).
            assert mode is not None and tier is not None
            prov = _prov_from_action()
            models_cache = require_key(game_state, "models_cache")
            squad_models = require_key(game_state, "squad_models")
            alive = [str(m) for m in require_key(squad_models, act_uid) if str(m) in models_cache]
            origin = {
                m: (int(models_cache[m]["col"]), int(models_cache[m]["row"]),
                    int(models_cache[m].get("level", 0)))  # get allowed (champ optionnel : level absent = sol)
                for m in alive
            }
            full_plan: List[Tuple[str, int, int, int]] = [
                (m, prov[m][0], prov[m][1], prov[m][2]) if m in prov
                else (m, origin[m][0], origin[m][1], origin[m][2])
                for m in alive
            ]
            tier_kind = "zone" if mode == "objective" else "enemy"
            lock_base_contact = mode == "ongoing"
            closest = _fight_pile_in_closest_tier_ids(game_state, u, list(tier)) if tier_kind == "enemy" else []
            prev = _fight_consolidation_preview_plan(
                game_state, act_uid, full_plan, mode=mode, tier_kind=tier_kind, tier=tier,
                closest_tier_ids=closest,
                lock_base_contact=lock_base_contact,
            )
            if not prev["can_validate"]:
                _fight_v11_log(game_state, f"CONSOLIDATE unit {act_uid} → plan invalide {prev}")
                return True, _fight_consolidation_model_plan_state(
                    game_state, u, prov, None, view_level=_view_level
                )
            _uc_before = require_key(game_state, "units_cache")[act_uid]
            _from_col, _from_row = int(_uc_before["col"]), int(_uc_before["row"])
            _fight_consolidation_commit_plan(game_state, u, full_plan)
            game_state["consolidation_done"].add(act_uid)
            game_state["active_fight_unit"] = None
            # Log par-figurine (mode fin type charge, sans roll) : ligne unite + moveDetails.
            _uc_after = require_key(game_state, "units_cache")[act_uid]
            _to_col, _to_row = int(_uc_after["col"]), int(_uc_after["row"])
            _move_details = [
                {
                    "modelId": m,
                    "fromCol": origin[m][0],
                    "fromRow": origin[m][1],
                    "toCol": int(nc),
                    "toRow": int(nr),
                    "toLevel": int(nlv),
                }
                for m, nc, nr, nlv in full_plan
            ]
            _append_fight_move_log(
                game_state, u, kind="consolidation",
                from_col=_from_col, from_row=_from_row,
                to_col=_to_col, to_row=_to_row,
                move_details=_move_details,
                # L17 — mode de consolidation (12.08) : ongoing / engaging / objective.
                consolidation_mode=mode,
            )
            _fight_v11_log(
                game_state,
                f"CONSOLIDATE unit {act_uid} → commit par-figurine (mode={mode}, {len(full_plan)} figs)",
            )
            # Engaging « New Foes to Face » (12.08 AFTER / §8.C) : résolution CIBLÉE in-place.
            new_foes_result: Optional[Dict[str, Any]] = None
            if mode == "engaging":
                new_foes_result = _fight_v11_consolidation_resolve_new_foes(game_state, u, config)
            _fight_v11_clear_consolidation_preview(game_state)
            if new_foes_result is not None and new_foes_result.get("waiting_for_player"):
                return True, new_foes_result
            return _fight_v11_manual_state(game_state)

        # Autre action en consolidate → ré-afficher l'état courant.
        return _fight_v11_manual_state(game_state)

    return _fight_v11_manual_state(game_state)


def execute_action(  # noqa: F811 (V11 override of V10)
    game_state: Dict[str, Any],
    unit: Optional[Dict[str, Any]],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Routage de la phase FIGHT V11 (override). Sous-phases pile_in → fight → consolidate.
    - PvE / gym / endless (auto autorisé) : une activation résolue par appel (_fight_v11_auto_step).
    - PvP / pvp_test (manuel) : traite l'action humaine et renvoie l'état actionnable suivant.
    """
    if game_state.get("phase") != "fight":
        fight_phase_start(game_state)
    fight_ensure_v11_state(game_state)
    if _is_fight_auto_execution_allowed(game_state):
        return _fight_v11_auto_step(game_state, config)
    return _fight_v11_manual_step(game_state, unit, action, config)
