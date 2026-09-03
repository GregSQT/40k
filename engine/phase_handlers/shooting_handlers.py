#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_Shooting_Phase.md Basic Implementation
Only pool building functionality - foundation for complete handler autonomy
"""

import copy
import hashlib
import os
import time
from typing import Dict, List, Tuple, Set, Optional, Any

import numpy as np
from engine.combat_utils import (
    normalize_coordinates,
    get_unit_by_id,
    require_unit_by_id,
    resolve_dice_value,
    expected_dice_value,
    set_unit_coordinates,
)
from shared.data_validation import require_key, require_present
from engine.utils.weapon_helpers import ranged_weapons, weapon_has_rule
from engine.action_log_utils import append_action_log
from .shared_utils import (
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, WAIT, PASS, SHOOTING, ADVANCE, NOT_REMOVED,
    translate_squad_to_destination, update_units_cache_hp, remove_from_units_cache,
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position, require_unit_from_cache,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    _get_unit_rule_arg,
    build_occupied_positions_set, compute_candidate_footprint, is_footprint_placement_valid,
    is_placement_valid_with_clearance,
    _compute_unit_occupied_hexes,
    enemy_entries_on_battlefield,
    entries_on_battlefield,
    entry_footprint,
    entry_is_on_battlefield,
)

# ============================================================================
# PERFORMANCE: Target pool caching (30-40% speedup)
# ============================================================================
# Cache valid target pools to avoid repeated distance/LoS calculations
# Cache key: (pid, instance_id, episode_num, turn, unit_id, col, row, advance_status, adjacent_status, player, _move_ver, wall_hexes_tuple, precheck_tag)
_target_pool_cache = {}  # per-process, per-env, per-episode; invalidates when unit/weapon changes
_move_los_preview_cache = {}
_cache_size_limit = 100  # Prevent memory leak in long episodes
_MOVE_AFTER_SHOOTING_DISTANCE_ARG = "distance"
_MOVE_AFTER_SHOOTING_DISTANCE_DICE_ARG = "distance_dice"
_unit_registry_singleton = None  # UnitRegistry reads static files — safe to share across all episodes


def clear_target_pool_cache() -> None:
    """Clear _target_pool_cache. Call on scenario rotation to avoid stale pool from different topology."""
    global _target_pool_cache
    global _move_los_preview_cache
    n = len(_target_pool_cache)
    preview_n = len(_move_los_preview_cache)
    _target_pool_cache.clear()
    _move_los_preview_cache.clear()
    if os.environ.get("LOS_DEBUG") == "1" and (n > 0 or preview_n > 0):
        import sys
        sys.stderr.write(
            f"[LOS_DEBUG] clear_target_pool_cache cleared target_pool={n} "
            f"move_los_preview={preview_n} entries\n"
        )
        sys.stderr.flush()


def _tracking_collection_fingerprint(collection: Any) -> Tuple[str, ...]:
    """Return normalized tracking collection fingerprint for cache keys."""
    return tuple(sorted(str(item) for item in collection))


def _occupied_hexes_fingerprint(raw_hexes: Any) -> Tuple[Tuple[int, int], ...]:
    """Return normalized occupied hexes fingerprint for units_cache entries."""
    if raw_hexes is None:
        return ()
    if not isinstance(raw_hexes, (set, list, tuple)):
        raise TypeError(f"occupied_hexes must be a set/list/tuple when present, got {type(raw_hexes).__name__}")
    normalized_hexes: List[Tuple[int, int]] = []
    for raw_hex in raw_hexes:
        if not isinstance(raw_hex, (list, tuple)) or len(raw_hex) < 2:
            raise ValueError(f"occupied_hexes entry must contain col,row, got {raw_hex!r}")
        hex_col, hex_row = normalize_coordinates(raw_hex[0], raw_hex[1])
        normalized_hexes.append((hex_col, hex_row))
    return tuple(sorted(normalized_hexes))


def _units_cache_fingerprint(units_cache: Dict[str, Any]) -> Tuple[Tuple[Any, ...], ...]:
    """Return units_cache fingerprint for exact move LoS preview memoization."""
    rows: List[Tuple[Any, ...]] = []
    for unit_id, entry in sorted(units_cache.items(), key=lambda item: str(item[0])):
        if not isinstance(entry, dict):
            raise TypeError(f"units_cache[{unit_id}] must be a dict, got {type(entry).__name__}")
        rows.append((
            str(unit_id),
            int(require_key(entry, "col")),
            int(require_key(entry, "row")),
            int(require_key(entry, "player")),
            int(require_key(entry, "HP_CUR")),
            _occupied_hexes_fingerprint(entry.get("occupied_hexes")),
        ))
    return tuple(rows)


def _weapon_rules_fingerprint(raw_rules: Any) -> Tuple[str, ...]:
    """Return normalized weapon rules fingerprint for cache keys."""
    if raw_rules is None:
        return ()
    if not isinstance(raw_rules, (list, tuple)):
        raise TypeError(f"WEAPON_RULES must be a list/tuple when present, got {type(raw_rules).__name__}")
    rules: List[str] = []
    for rule in raw_rules:
        if hasattr(rule, "rule"):
            rules.append(str(rule.rule))
        else:
            rules.append(str(rule))
    return tuple(sorted(rules))


def _rng_weapons_fingerprint(unit: Dict[str, Any]) -> Tuple[Tuple[Any, ...], ...]:
    """Return ranged weapon targetability fingerprint for move LoS preview cache."""
    rows: List[Tuple[Any, ...]] = []
    for weapon in require_key(unit, "RNG_WEAPONS"):
        rows.append((
            int(require_key(weapon, "RNG")),
            _weapon_rules_fingerprint(weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else None),
        ))
    return tuple(rows)


def _move_los_preview_cache_key(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    unit_id_str: str,
    placement: Tuple[Any, ...],
    advance_position: bool,
) -> Tuple[Any, ...]:
    """Build strict backend cache key for move LoS target preview.

    ``placement`` décrit OÙ l'aperçu pose l'escouade : ancre `("anchor", col, row)` ou plan par
    figurine `("models", ((model_id, col, row, level, orientation), ...))`. Il entre dans la clé
    sous cette forme parce que les deux placements donnent des empreintes DIFFÉRENTES pour la même
    escouade — une clé qui ne porterait que l'ancre servirait le résultat de l'un à l'autre. Le
    niveau et l'orientation en font partie : ils changent l'empreinte et le gate vertical, donc
    deux plans qui n'en diffèrent que par eux ne peuvent pas partager une entrée.
    """
    return (
        os.getpid(),
        require_key(game_state, "episode_number"),
        require_key(game_state, "turn"),
        require_key(game_state, "episode_steps"),
        str(require_key(game_state, "current_player")),
        unit_id_str,
        placement,
        bool(advance_position),
        _units_cache_fingerprint(require_key(game_state, "units_cache")),
        _tracking_collection_fingerprint(require_key(game_state, "units_advanced")),
        _tracking_collection_fingerprint(require_key(game_state, "units_fled")),
        _rng_weapons_fingerprint(unit),
    )


# LOS debugging env vars (stderr, no debug.log):
#   LOS_ENV_TRACE=1    - Log env creation in bot_evaluation (batch, id(gs), _cache_instance_id)
#   LOS_DEBUG=1        - Log hex_los_cache HIT/MISS, build_unit_los_cache per target, cache MISS store
#   LOS_VERIFY=1       - On pool cache HIT, verify each target with has_line_of_sight_coords;
#                        if any returns False, dump CONTRADICTION diagnostic (catches root cause)


def _serialize_weapon_for_json(weapon: Dict[str, Any]) -> Dict[str, Any]:
    """Copie d'une arme destinee a une charge utile JSON (``available_weapons[].weapon``).

    Copie SUPERFICIELLE, plus une copie des listes de premier niveau (``WEAPON_RULES``...) :
    la reponse API ne doit jamais aliaser les listes du dict d'arme du moteur, sinon une
    mutation cote moteur se refleterait dans une charge deja construite.

    2026-07-29 — les branches `isinstance(..., ParsedWeaponRule)` (sur la valeur ET sur chaque
    element de liste) ont ete SUPPRIMEES. Leur domaine est borne et prouve : ce dict d'arme ne
    peut plus contenir d'objet `ParsedWeaponRule`. Ce type n'est construit qu'en
    `engine/weapons/rules.py` (`parse_weapon_rule`) ; son unique chemin de production,
    `engine/weapons/parser.py`, jette desormais le retour de la validation. `WEAPON_RULES` ne
    contient que des chaines, partout dans le depot. Verifie aussi au runtime : apres parsing des
    153 armes des deux factions, zero instance vivante dans le tas du processus.
    """
    serialized: Dict[str, Any] = {}
    for key, value in weapon.items():
        if isinstance(value, list):
            serialized[key] = list(value)
        else:
            serialized[key] = value
    return serialized


# 2026-07-29 — `_weapon_has_assault_rule` et `_weapon_has_close_quarters_rule` ont ete
# SUPPRIMEES. C'etaient des DOUBLONS laxistes de
# `engine/utils/weapon_helpers.weapon_has_rule(weapon, "ASSAULT" | "CLOSE_QUARTERS")`, dont elles
# s'ecartaient par deux replis muets : `if not weapon: return False` et
# `weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []`. Une arme depourvue de la cle y
# devenait « n'a pas la regle » au lieu de lever — exactement le repli anti-erreur interdit ici.
#
# Revue des 24 sites d'appel avant suppression : AUCUN ne s'appuyait sur le laxisme. Les armes y
# arrivent toujours d'une iteration sur `require_key(unit, "RNG_WEAPONS")`, d'un
# `require_key(w, "weapon")` ou derriere une garde `isinstance(w, dict)` ; et sur plusieurs
# chemins le MEME objet est deja passe a `weapon_has_rule(..., "BLAST")` (strict) dans le meme
# bloc — shooting_handlers l.674/678, shared_utils l.5396/5400 et l.6415/6419. Le seul argument
# qui pouvait valoir None etait deja ecarte par son appelant (`bool(selected_weapon and ...)`).
#
# Consequence ASSUMEE : une arme sans WEAPON_RULES leve desormais explicitement sur le chemin du
# tir au lieu de repondre False en silence. Les armes des rosters reels des deux factions ont ete
# verifiees : toutes portent la cle, et les seules formes presentes sont « ASSAULT » et
# « CLOSE_QUARTERS » exactes — le remplacement est iso-comportement sur les donnees reelles.
# Ne pas reintroduire de helper local : appeler `weapon_has_rule` directement.


def _unit_shoots_as_monster_or_vehicle(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """L'unité tire-t-elle sous le volet MONSTER/VEHICLE de 10.06 ?

    **PDF 10.06 — CLOSE-QUARTERS SHOOTING** : « MONSTER and VEHICLE Models: you can select any
    of that model's ranged weapons. » Le volet est donc PAR FIGURINE, et le prédicat exact est
    `_model_is_monster_or_vehicle` (shared_utils) — c'est lui que le chemin par-figurine utilise
    (`_shoot_engagement_blocks_target`, `_manual_roll_intent`).

    Ici, on répond pour l'UNITÉ entière : ces gates-là (cercle vert, menu d'armes, pool de
    cibles) décident au niveau unité. On exige donc que **TOUTES** les figurines vivantes soient
    MONSTER/VEHICLE. Répondre « oui » dès qu'une seule l'est ouvrirait dans l'interface un tir
    que la déclaration par-figurine refuserait ensuite — la classe de bug « le masque offre plus
    que l'exécutable ». Exact sur les rosters réels (les 9 unités MONSTER/VEHICLE y sont
    mono-figurine, aucune escouade mixte), conservateur sinon, jamais laxiste.
    """
    from engine.phase_handlers.shared_utils import _model_is_monster_or_vehicle

    models_cache = game_state.get("models_cache")  # get allowed (chemin sans caches -> unité)
    squad_models = game_state.get("squad_models")  # get allowed
    if models_cache and squad_models:
        alive = [
            models_cache[mid]
            for mid in squad_models.get(str(unit["id"]), [])  # get allowed
            if mid in models_cache
        ]
        if alive:
            return all(_model_is_monster_or_vehicle(m) for m in alive)
    return _model_is_monster_or_vehicle(unit)


def _append_shoot_nb_roll_info_log(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon: Dict[str, Any],
    nb_roll: int
) -> None:
    """
    Append informational log line for randomized shooting attack count rolls.
    """
    nb_value = require_key(weapon, "NB")
    if not isinstance(nb_value, str):
        return

    unit_id = require_key(unit, "id")
    unit_col, unit_row = require_unit_position(unit, game_state)
    weapon_name = str(require_key(weapon, "display_name"))

    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    append_action_log(
        game_state,
        {
            "type": "roll_info",
            "phase": "SHOOT",
            "player": require_key(unit, "player"),
            "unitId": unit_id,
            "message": (
                f"Unit {unit_id}({unit_col},{unit_row}) SHOOT with [{weapon_name}]. "
                f"Number of shoots ({nb_value}): {nb_roll}"
            ),
        },
    )


def _unit_has_rule(unit: Dict[str, Any], rule_id: str) -> bool:
    """Check if unit has a specific direct or granted rule effect by ruleId."""
    return shared_unit_has_rule_effect(unit, rule_id)


def _get_source_unit_rule_id_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.ruleId that grants/owns the effect; None if absent."""
    return shared_get_source_unit_rule_id_for_effect(unit, effect_rule_id)


def _get_source_unit_rule_display_name_for_effect(unit: Dict[str, Any], effect_rule_id: str) -> Optional[str]:
    """Return source UNIT_RULES.displayName for an effect rule; None if absent."""
    return shared_get_source_unit_rule_display_name_for_effect(unit, effect_rule_id)


def _get_required_rule_int_argument(
    unit: Dict[str, Any], effect_rule_id: str, argument_key: str
) -> int:
    """Read required integer argument from source UNIT_RULES entry for an effect rule."""
    raw = _get_unit_rule_arg(unit, effect_rule_id, argument_key, (int,))
    if raw is None:
        raise ValueError(
            f"Rule effect '{effect_rule_id}' is not present on unit "
            f"{require_key(unit, 'id')}"
        )
    if raw <= 0:
        raise ValueError(
            f"Rule argument '{argument_key}' must be > 0, got {raw} "
            f"for unit {require_key(unit, 'id')}"
        )
    return raw


def _resolve_move_after_shooting_distance(unit: Dict[str, Any]) -> int:
    """Distance du move_after_shooting : fixe (rule_args.distance) ou lancee (rule_args.distance_dice).

    Primitive F (chantier 06, passe 6) — Purgation Run (LandSpeeder) : D6", pas 6" fixes.
    Les deux parametres sont mutuellement exclusifs dans rule_args ; `distance` prime si les deux
    sont presents (defaut de securite). Un lancer de D6 est effectue une seule fois ici.

    Lit rule_args DIRECTEMENT (iteration sur UNIT_RULES) : les deux cles sont alternatives, et
    `_get_unit_rule_arg` leve quand la cle demandee est absente, ce qui empeche le test de la
    seconde alternative sans try/except.
    """
    unit_id = require_key(unit, "id")
    for rule_entry in require_key(unit, "UNIT_RULES"):
        if str(require_key(rule_entry, "ruleId")) != "move_after_shooting":
            continue
        rule_args = rule_entry.get("rule_args") or {}
        distance = rule_args.get(_MOVE_AFTER_SHOOTING_DISTANCE_ARG)
        if distance is not None:
            d = int(distance)
            if d <= 0:
                raise ValueError(
                    f"move_after_shooting.distance must be > 0, got {d} for unit {unit_id}"
                )
            return d
        dice_spec = rule_args.get(_MOVE_AFTER_SHOOTING_DISTANCE_DICE_ARG)
        if dice_spec is not None:
            rolled = resolve_dice_value(str(dice_spec), "move_after_shooting_distance")
            if rolled <= 0:
                raise ValueError(
                    f"move_after_shooting.distance_dice rolled {rolled} for unit {unit_id}"
                )
            return int(rolled)
        raise ValueError(
            f"move_after_shooting rule on unit {unit_id} requires either "
            f"'{_MOVE_AFTER_SHOOTING_DISTANCE_ARG}' (int) or "
            f"'{_MOVE_AFTER_SHOOTING_DISTANCE_DICE_ARG}' (str) in rule_args"
        )
    raise ValueError(
        f"move_after_shooting rule absent from UNIT_RULES for unit {unit_id}"
    )


def _can_unit_shoot_after_advance_with_weapon(unit: Dict[str, Any], weapon: Dict[str, Any]) -> bool:
    """Return True if unit is allowed to shoot after advance with this weapon."""
    if weapon_has_rule(weapon, "ASSAULT"):
        return True
    return _unit_has_rule(unit, "shoot_after_advance")




def _get_combi_weapon_key(weapon: Dict[str, Any]) -> Optional[str]:
    """Return COMBI_WEAPON key if present."""
    if not weapon:
        return None
    return weapon.get("COMBI_WEAPON")


def _is_combi_profile_blocked(unit: Dict[str, Any], weapon: Dict[str, Any], weapon_index: int) -> bool:
    """Check if weapon is blocked by an existing COMBI_WEAPON choice."""
    combi_key = _get_combi_weapon_key(weapon)
    if not combi_key:
        return False
    if "_combi_weapon_choice" not in unit or unit["_combi_weapon_choice"] is None:
        return False
    combi_choice = unit["_combi_weapon_choice"]
    return combi_key in combi_choice and combi_choice[combi_key] != weapon_index


def _socle_from_entry(entry: Dict[str, Any]):
    """Construit un ``Socle`` (hex_utils) depuis une entrée units_cache.

    L'entrée porte BASE_SHAPE/BASE_SIZE/col/row/occupied_hexes/occupied_hexes_by_model
    (cf build_units_cache). ``model_centers`` = centres par-figurine → distance bord-à-bord
    ronde correcte vers une escouade multi-figurines (règle 01.04).
    """
    from engine.hex_utils import Socle
    by_model = entry.get("occupied_hexes_by_model")
    model_centers = (
        [(int(c), int(r)) for (c, r) in by_model.values()]
        if isinstance(by_model, dict) and by_model
        else None
    )
    return Socle(
        entry["BASE_SHAPE"],
        entry["BASE_SIZE"],
        entry["col"],
        entry["row"],
        entry["occupied_hexes"],
        model_centers,
    )


def _ranged_distance_metric(game_state: Optional[Dict[str, Any]] = None) -> str:
    """Métrique de portée tir (``hex``|``euclidean``) — sélecteur unique, source game_config.json.

    La RÉSOLUTION prime sur la config : à ``inches_to_subhex <= 1`` la géométrie du jeu est
    hexagonale (point de bascule unique ``spatial_relations.geometry_is_hex``, même règle que
    move / charge / EZ). Le x1 ne sert qu'à valider la configuration — aucune mesure continue n'y
    a de sens, une figurine y tenant dans une case. La clé de config est lue ET validée d'abord,
    pour qu'une valeur invalide lève à x1 comme ailleurs ; le x5 (euclidien) est inchangé.

    ``game_state`` optionnel : les call-sites qui ne l'ont pas laissent ``geometry_is_hex`` relire
    la résolution depuis le même config-loader que la métrique.
    """
    from config_loader import get_config_loader
    from engine.combat_utils import get_distance_metric
    from engine.spatial_relations import geometry_is_hex

    metric = get_distance_metric("ranged", get_config_loader().get_game_config())
    return "hex" if geometry_is_hex(game_state) else metric


def _build_weapon_availability_enemy_precheck(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    rng_weapons: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Une passe par ennemi (distance max RNG, blocage allié/mêlée, clé los_cache) pour
    weapon_availability_check : évite de répéter min_distance / boucle alliés pour chaque arme.
    """
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone
    from engine.combat_utils import ranged_edge_distance

    _ranged_metric = _ranged_distance_metric(game_state)

    # Portée maximale des armes de TIR de l'unité. Aucun repli silencieux : `RNG` est porté
    # par les 243 profils d'armes de tir des rosters — une arme rangée sans portée est une
    # donnee d'arme invalide, pas une arme à ignorer (l'ancien `except Exception: continue`
    # la faisait disparaître du calcul, et l'unité pouvait perdre sa portée maximale réelle).
    # `RNG` n'est absent que des armes de MÊLÉE, qui ne sont pas dans `RNG_WEAPONS`.
    max_rng = 0
    for w in rng_weapons:
        r = int(require_key(w, "RNG"))
        if r > max_rng:
            max_rng = r
    if max_rng <= 0:
        return []

    units_cache = require_key(game_state, "units_cache")
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    unit_col, unit_row = require_unit_position(unit, game_state)
    _uid_str = str(unit["id"])
    _ue = units_cache.get(_uid_str)
    if _ue is None:
        raise KeyError(f"Unit {_uid_str} not in units_cache (dead or absent)")
    _shooter_socle = _socle_from_entry(_ue)
    shooter_id_str = _uid_str
    shooter_player_int = require_present(int(unit["player"]) if unit["player"] is not None else None, "unit['player']")
    melee_range = get_engagement_zone(game_state)

    _los_map = unit.get("los_cache")
    out: List[Dict[str, Any]] = []
    # Snapshot iteration to avoid RuntimeError when rapid concurrent clicks
    # mutate units_cache while precheck is in progress.
    # `list(...)` : snapshot, cf. commentaire ci-dessus. Le filtre hors-table (réserves 20.01) est
    # DANS l'énumérateur — il n'a plus à être recopié ici (c'était l'un des trois correctifs
    # par-site du chantier 04c, désormais couverts par la racine).
    for enemy_id, cache_entry in list(enemy_entries_on_battlefield(units_cache, unit_player)):
        enemy = require_unit_by_id(game_state, enemy_id)
        _enemy_id_str = str(enemy_id)
        if not is_unit_alive(_enemy_id_str, game_state):
            continue
        if isinstance(_los_map, dict) and _enemy_id_str in _los_map:
            if not _los_map[_enemy_id_str]:
                continue

        d = ranged_edge_distance(
            _shooter_socle, _socle_from_entry(cache_entry), _ranged_metric, max_distance=max_rng
        )
        if d > max_rng:
            continue

        enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(
            _ue, cache_entry, melee_range, game_state=game_state
        )
        friendly_blocks = _friendly_engagement_blocks_ranged_shot(
            game_state,
            shooter_id_str,
            shooter_player_int,
            cache_entry,
            _enemy_id_str,
            enemy_adjacent_to_shooter,
            units_cache,
        )

        los_cache_has_key = isinstance(_los_map, dict) and _enemy_id_str in _los_map
        los_cache_true = bool(_los_map[_enemy_id_str]) if (isinstance(_los_map, dict) and _enemy_id_str in _los_map) else False

        out.append({
            "enemy_id_str": _enemy_id_str,
            "distance": d,
            "enemy_engaged_with_shooter": enemy_adjacent_to_shooter,
            "friendly_blocks": friendly_blocks,
            "los_cache_has_key": los_cache_has_key,
            "los_cache_true": los_cache_true,
        })
    return out


def weapon_availability_check(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon_rule: int,
    advance_status: int,
    adjacent_status: int,
    *,
    _precheck: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    shoot_refactor.md EXACT: Filter weapons based on rules and context
    
    Args:
        game_state: Game state dictionary
        unit: Unit dictionary
        weapon_rule: 0 = no rules, 1 = rules apply
        advance_status: 0 = no advance, 1 = advanced
        adjacent_status: 0 = not adjacent, 1 = adjacent to enemy
        _precheck: Si fourni (même liste que ``_build_weapon_availability_enemy_precheck``), évite
            de reconstruire le précalcul ennemi (chemin activation).
    
    Returns:
        List of weapons that can be selected (weapon_available_pool)
        Each item has: index, weapon, can_use, reason
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf_wa = perf_timing_enabled(game_state)
    _t_wa0 = time.perf_counter() if _perf_wa else None
    _precheck_build_s = 0.0
    _weapon_row_scan_s = 0.0

    available_weapons = []
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    _enemy_precheck_for_availability: Optional[List[Dict[str, Any]]] = _precheck

    for idx, weapon in enumerate(rng_weapons):
        can_use = True
        reason = None
        weapon_name = weapon.get("display_name", f"weapon_{idx}")
        
        # Check arg1 (weapon_rule)
        # arg1 = 0 -> No weapon rules checked/applied (continue to next check)
        # arg1 = 1 -> Weapon rules apply (continue to next check)
        
        # Check arg2 (advance_status)
        if advance_status == 1:
            # Unit DID advance
            if weapon_rule == 0:
                # arg1=0 AND arg2=1 -> ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot after advance (weapon_rule=0)"
            else:
                # arg1=1 AND arg2=1 -> ✅ Weapon MUST have ASSAULT or unit shoot_after_advance
                if not _can_unit_shoot_after_advance_with_weapon(unit, weapon):
                    can_use = False
                    reason = "Cannot shoot after advance without ASSAULT or shoot_after_advance"
        
        # Check arg3 (adjacent_status)
        if can_use and adjacent_status == 1:
            # Unit IS adjacent to enemy
            if weapon_rule == 0:
                # arg1=0 AND arg3=1 -> ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Cannot shoot when adjacent (weapon_rule=0)"
            else:
                # arg1=1 AND arg3=1 -> ✅ 10.06 « WHILE SHOOTING », deux volets :
                #   - Non-MONSTER/Non-VEHICLE : seules les armes [CLOSE-QUARTERS] ;
                #   - MONSTER/VEHICLE : « you can select ANY of that model's ranged weapons »,
                #     au prix d'un -1 au jet de touche appliqué à la RÉSOLUTION
                #     (`_manual_roll_intent`, shared_utils) — pas ici.
                if not weapon_has_rule(weapon, "CLOSE_QUARTERS") and not _unit_shoots_as_monster_or_vehicle(
                    game_state, unit
                ):
                    can_use = False
                    reason = "No CLOSE_QUARTERS rule (cannot shoot non-CLOSE_QUARTERS when adjacent)"
        
        # Check weapon.shot flag
        if can_use:
            weapon_shot = require_key(weapon, "shot")
            if weapon_shot == 1:
                # ❌ Weapon CANNOT be selectable (skip weapon)
                can_use = False
                reason = "Weapon already used (weapon.shot = 1)"

        # Check COMBI_WEAPON profile lock
        if can_use and _is_combi_profile_blocked(unit, weapon, idx):
            can_use = False
            reason = "COMBI_WEAPON profile already selected"
            from engine.game_utils import add_debug_log
            combi_key = _get_combi_weapon_key(weapon)
            combi_choice = require_key(unit, "_combi_weapon_choice")
            add_debug_log(
                game_state,
                f"[COMBI_WEAPON] Unit {unit.get('id')} blocked weapon {idx} ({weapon_name}) "
                f"combi_key={combi_key} chosen_index={combi_choice[combi_key]}"
            )
        
        # [CLOSE-QUARTERS] 24.07 (SIDEARMS) : « for each model in that unit (EXCLUDING
        # MONSTER/VEHICLE models), you can only select one of the following » — la restriction de
        # melange ne s applique donc PAS a une figurine MONSTER/VEHICLE. Sans cette exclusion, le
        # volet MONSTER/VEHICLE de 10.06 serait rendu inoperant des la 2e arme tiree.
        if (
            can_use
            and "_shooting_with_close_quarters" in unit
            and unit["_shooting_with_close_quarters"] is not None
            and not _unit_shoots_as_monster_or_vehicle(game_state, unit)
        ):
            weapon_is_close_quarters = weapon_has_rule(weapon, "CLOSE_QUARTERS")
            
            if unit["_shooting_with_close_quarters"]:
                # Unit fired with CLOSE_QUARTERS weapon, can only select other CLOSE_QUARTERS weapons
                if not weapon_is_close_quarters:
                    can_use = False
                    reason = "Cannot mix CLOSE_QUARTERS with non-CLOSE_QUARTERS weapons"
            else:
                # Unit fired with non-CLOSE_QUARTERS weapon, cannot select CLOSE_QUARTERS weapons
                if weapon_is_close_quarters:
                    can_use = False
                    reason = "Cannot mix non-CLOSE_QUARTERS with CLOSE_QUARTERS weapons"
        
        # Check weapon.RNG and target availability
        if can_use:
            weapon_range = require_key(weapon, "RNG")
            if weapon_range <= 0:
                can_use = False
                reason = "Weapon has no range"
            else:
                # Check if at least ONE enemy unit meets ALL conditions
                weapon_has_valid_target = False

                if _enemy_precheck_for_availability is None:
                    _mv = game_state.get("_unit_move_version")
                    _pc = unit.get("_precheck_cache")
                    if _pc is not None and _pc.get("version") == _mv:
                        _enemy_precheck_for_availability = _pc["data"]
                    else:
                        _tpb = time.perf_counter() if _perf_wa else None
                        _enemy_precheck_for_availability = _build_weapon_availability_enemy_precheck(
                            game_state, unit, rng_weapons
                        )
                        if _perf_wa and _tpb is not None:
                            _precheck_build_s += time.perf_counter() - _tpb
                        unit["_precheck_cache"] = {"version": _mv, "data": _enemy_precheck_for_availability}
                from engine.spatial_relations import get_engagement_zone

                melee_range = get_engagement_zone(game_state)
                weapon_is_close_quarters = weapon_has_rule(weapon, "CLOSE_QUARTERS")
                shooter_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, unit)

                weapon_is_blast = weapon_has_rule(weapon, "BLAST")

                _trs = time.perf_counter() if _perf_wa else None
                for row in require_present(_enemy_precheck_for_availability, "_enemy_precheck_for_availability"):
                    if row["distance"] > weapon_range:
                        continue
                    temp_unit = dict(unit)
                    temp_unit["RNG_WEAPONS"] = [weapon]
                    temp_unit["selectedRngWeaponIndex"] = 0
                    try:
                        if row["los_cache_has_key"] and row["los_cache_true"]:
                            if shooter_engaged:
                                # 10.06, memes deux volets que `_is_valid_shooting_target` :
                                # MONSTER/VEHICLE = toute arme et toute cible, sauf [BLAST] sur
                                # une unite engagee ; sinon [CLOSE-QUARTERS] + cible engagee.
                                if _unit_shoots_as_monster_or_vehicle(game_state, unit):
                                    if weapon_is_blast and row["enemy_engaged_with_shooter"]:
                                        continue
                                else:
                                    if not weapon_is_close_quarters:
                                        continue
                                    if not row["enemy_engaged_with_shooter"]:
                                        continue
                            elif row["enemy_engaged_with_shooter"] and not weapon_is_close_quarters:
                                continue
                            if row["friendly_blocks"]:
                                continue
                            weapon_has_valid_target = True
                            break
                        # Preuve statique : `_build_weapon_availability_enemy_precheck` lève
                        # KeyError si l'unité manque de unit_by_id (ligne 437-438). unit_by_id
                        # ne rétrécit jamais en cours de partie — require ne peut pas lever ici.
                        _row_enemy = require_unit_by_id(game_state, row["enemy_id_str"])
                        is_valid = _is_valid_shooting_target(game_state, temp_unit, _row_enemy)
                        if is_valid:
                            weapon_has_valid_target = True
                            break
                    except (KeyError, IndexError, AttributeError):
                        continue
                if _perf_wa and _trs is not None:
                    _weapon_row_scan_s += time.perf_counter() - _trs

                if not weapon_has_valid_target:
                    can_use = False
                    reason = "No valid targets in range or line of sight"
        
        available_weapons.append({
            "index": idx,
            "weapon": _serialize_weapon_for_json(weapon),
            "can_use": can_use,
            "reason": reason
        })

    if _perf_wa and _t_wa0 is not None:
        _total = time.perf_counter() - _t_wa0
        _overhead = _total - _precheck_build_s - _weapon_row_scan_s
        ep = game_state.get("episode_number", "?")
        trn = game_state.get("turn", "?")
        uid = str(unit.get("id", "?"))
        append_perf_timing_line(
            f"WEAPON_AVAILABILITY_CHECK episode={ep} turn={trn} unit_id={uid} "
            f"precheck_build_s={_precheck_build_s:.6f} weapon_row_scan_s={_weapon_row_scan_s:.6f} "
            f"overhead_s={_overhead:.6f} total_s={_total:.6f}"
        )

    return available_weapons

# 2026-07-29 — `_get_available_weapons_for_selection` a ete SUPPRIMEE (~160 lignes).
# Elle etait marquee DEPRECATED dans sa propre docstring (« Use weapon_availability_check()
# instead ») et n'avait AUCUN appelant : ni appel direct, ni import, ni mention dans une chaine,
# ni dispatch dynamique (le moteur ne dispatche que par `if name == "<litteral>"`), ni route
# d'API. Le menu d'armes du PvP est servi par `squad_shoot_menu_weapons` (shared_utils) et par
# les charges de `squad_shoot_activate` / `squad_select_weapon` — jamais par elle.
#
# CE N'ETAIT PAS UNE FONCTIONNALITE JAMAIS BRANCHEE : aucune de ses regles ne lui etait propre.
# Ses cinq filtres (arme deja tiree `shot == 1`, ASSAULT apres advance, categorie
# [CLOSE-QUARTERS], portee nulle, portee + LoS) sont TOUS couverts par
# `weapon_availability_check` (ci-dessus), qui est un sur-ensemble strict : elle y ajoute le
# verrou de profil COMBI_WEAPON, les deux volets de 10.06 (MONSTER/VEHICLE), la regle [BLAST]
# sur unite engagee, le blocage par tir ami et le cache de precalcul ennemi.
#
# La rebrancher aurait ete une REGRESSION de regles, pas un gain : son melange
# [CLOSE-QUARTERS] ignorait l'exclusion MONSTER/VEHICLE de 24.07 (SIDEARMS) ; elle testait
# `"CLOSE_QUARTERS" in weapon["WEAPON_RULES"]` en brut (sensible a la casse, aveugle aux formes
# parametrees) au lieu de `weapon_has_rule` ; elle portait le 3e repli laxiste
# `"WEAPON_RULES" in weapon else []` ; et elle convertissait KeyError/IndexError/AttributeError
# en simple chaine `reason`, masquant des erreurs de validation au lieu de les laisser remonter.


def shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Initialize shooting phase and build activation pool
    Initialize weapon_rule and weapon.shot flags
    """
    global _target_pool_cache

    if game_state.get("pending_shooting_phase_init"):
        game_state["pending_shooting_phase_init"] = False

    # Set phase
    from engine.game_utils import enter_phase
    enter_phase(game_state, "shoot")

    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    units_cache = require_key(game_state, "units_cache")
    add_debug_file_log(game_state, f"[PHASE START] E{episode} T{turn} shoot units_cache={units_cache}")

    # Initialize weapon_rule (weapon rules activated = 1)
    # This is a global variable that determines if weapon rules are applied
    game_state["weapon_rule"] = 1

    # Clear target pool cache at phase start - targets may have moved
    # The cache key only includes shooter position, not target positions
    # So stale cache entries could allow shooting blocked targets
    _target_pool_cache.clear()

    # Initialize weapon.shot = 0 for all weapons in all units
    # Reset weapon.shot flag at phase start
    current_player = game_state["current_player"]
    try:
        current_player = int(current_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid current_player value: {current_player}") from exc
    if current_player not in (1, 2):
        raise ValueError(f"Invalid current_player value: {current_player}")
    game_state["current_player"] = current_player
    units_cache = require_key(game_state, "units_cache")

    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf = perf_timing_enabled(game_state)
    _t_reset0 = time.perf_counter() if _perf else None

    for unit_id, cache_entry in units_cache.items():
        if int(cache_entry["player"]) == int(current_player):
            unit = require_unit_by_id(game_state, unit_id)
            # Activation-scoped shooting state must be reset at phase start.
            # Pool/phase transitions are the source of truth (AI_TURN): no carry-over
            # of a previous unit activation context into a new shoot phase.
            transient_shoot_state_fields = (
                "valid_target_pool",
                "_pool_from_cache",
                "_pool_cache_key",
                "TOTAL_ATTACK_LOG",
                "selected_target_id",
                "activation_position",
                "_shooting_with_close_quarters",
                "_manual_weapon_selected",
                "manualWeaponSelected",
                "_shoot_activation_started",
                "_current_shoot_nb",
            )
            for field_name in transient_shoot_state_fields:
                if field_name in unit:
                    del unit[field_name]
            rng_weapons = require_key(unit, "RNG_WEAPONS")
            for weapon in rng_weapons:
                weapon["shot"] = 0

            # La remise a zero ci-dessus vaut pour TOUTE unite vivante, y compris hors table :
            # elle ne lit aucune position. Le CHOIX D'ARME qui suit, lui, en exige une — il
            # mesure des distances aux ennemis, et une unite en reserves stratégiques (20.01)
            # n'a ni position ni empreinte. Ce n'est PAS le filtre d'une enumeration d'ennemis
            # (ceux-la sont dans `enemy_entries_on_battlefield`) : c'est la regle « une unite
            # hors table ne choisit pas son arme », cote TIREUR.
            # Rien n'est perdu : `shooting_build_activation_pool` exclut deja les unites hors
            # table, et celle qui arrive par ingress (20.04) traverse ce meme phase_start au
            # tour ou elle arrive, cette fois posee, donc avec son arme choisie.
            if not entry_is_on_battlefield(cache_entry):
                continue

            if rng_weapons:
                # Initialize weapon selection. Full weapon_availability_check is only needed when
                # adjacent (CLOSE_QUARTERS) or after advance (ASSAULT / combi) — otherwise O(weapons×enemies)
                # per ally dominated SHOOT_PHASE_START reset_allies_s.
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                # `weapon_rule` est pose par CETTE fonction quelques lignes plus haut : le lire
                # avec un defaut re-etablissait ici une valeur deja garantie, et aurait masque
                # sans bruit une divergence si l initialisation venait a changer. Les autres
                # consommateurs exigent deja la cle (require_key / KeyError explicite).
                weapon_rule = require_key(game_state, "weapon_rule")

                if not is_adjacent and advance_status == 0:
                    selected_idx = next(
                        (i for i, w in enumerate(rng_weapons) if require_key(w, "RNG") > 0),
                        0,
                    )
                    unit["selectedRngWeaponIndex"] = selected_idx
                    weapon = rng_weapons[selected_idx]
                    unit["SHOOT_LEFT"] = resolve_dice_value(
                        require_key(weapon, "NB"),
                        "shooting_phase_start_nb",
                    )
                else:
                    weapon_available_pool = weapon_availability_check(
                        game_state, unit, weapon_rule, advance_status, adjacent_status
                    )
                    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                    if usable_weapons:
                        # If adjacent, prioritize CLOSE_QUARTERS weapons
                        if is_adjacent:
                            close_quarters_weapons = [
                                w for w in usable_weapons if weapon_has_rule(require_key(w, "weapon"), "CLOSE_QUARTERS")
                            ]
                            if close_quarters_weapons:
                                first_weapon = close_quarters_weapons[0]
                            else:
                                first_weapon = usable_weapons[0]
                        else:
                            first_weapon = usable_weapons[0]

                        selected_idx = first_weapon["index"]
                        unit["selectedRngWeaponIndex"] = selected_idx
                        weapon = rng_weapons[selected_idx]
                        unit["SHOOT_LEFT"] = resolve_dice_value(
                            require_key(weapon, "NB"),
                            "shooting_phase_start_nb",
                        )
                    else:
                        # No usable weapons, default to first weapon (will be validated later)
                        selected_idx = unit["selectedRngWeaponIndex"] if "selectedRngWeaponIndex" in unit else 0
                        if selected_idx < 0 or selected_idx >= len(rng_weapons):
                            selected_idx = 0
                        weapon = rng_weapons[selected_idx]
                        unit["SHOOT_LEFT"] = resolve_dice_value(
                            require_key(weapon, "NB"),
                            "shooting_phase_start_nb_fallback",
                        )
            else:
                unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged

    _t_reset1 = time.perf_counter() if _perf else None

    # PERFORMANCE: Pre-compute enemy_adjacent_hexes once at phase start for all players present.
    # Reactive movement may query adjacency from the opposing player's perspective.
    from .shared_utils import build_enemy_adjacent_hexes
    players_present = set()
    for cache_entry in units_cache.values():
        player_raw = require_key(cache_entry, "player")
        try:
            player_int = int(player_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid player value in units_cache at shooting_phase_start: {player_raw!r}"
            ) from exc
        players_present.add(player_int)
    for player_int in players_present:
        build_enemy_adjacent_hexes(game_state, player_int)

    _t_enemy_adj = time.perf_counter() if _perf else None

    # UNITS_CACHE: Verify units_cache exists (built at reset, not here - "reset only" policy)
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist at shooting_phase_start (should be built at reset)")
    
    # PERF: No global los_cache at phase start (was 56 _has_line_of_sight calls → ~3s spike).
    # LoS is built per unit at activation via build_unit_los_cache(); _is_valid_shooting_target
    # uses shooter["los_cache"] when present, else _has_line_of_sight (e.g. activation pool build).
    if "los_cache" in game_state:
        game_state["los_cache"] = {}

    # Compute hidden status (rule 13.09) before targeting so enemy units carry the flag.
    compute_hidden_statuses(game_state)

    # Build activation pool
    eligible_units = shooting_build_activation_pool(game_state)

    if (
        _perf
        and _t_reset0 is not None
        and _t_reset1 is not None
        and _t_enemy_adj is not None
    ):
        _t_pool1 = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_PHASE_START episode={episode} turn={turn} "
            f"reset_allies_s={_t_reset1 - _t_reset0:.6f} "
            f"enemy_adj_hex_s={_t_enemy_adj - _t_reset1:.6f} "
            f"los_clear_and_pool_s={_t_pool1 - _t_enemy_adj:.6f} "
            f"total_heavy_s={_t_pool1 - _t_reset0:.6f} eligible_count={len(eligible_units)}"
        )

    # `active_shooting_unit` désigne l'escouade dont l'activation de tir est EN COURS — jamais
    # celle que le moteur activerait ensuite. Le montage du pool n'active rien : il n'écrit donc
    # pas la clé, il ne fait que la purger d'une phase précédente (V11 §0.48 L2).
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]

    # If no eligible units, end phase immediately (align with MOVE phase)
    if not eligible_units:
        return shooting_phase_end(game_state)

    # Silent pool building - no console logs during normal operation
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    
    return {
        "phase_initialized": True,
        "eligible_units": len(eligible_units),
        "phase_complete": len(eligible_units) == 0
    }


def compute_models_in_obscuring_terrain(
    unit: Dict[str, Any],
    by_model: Dict[Any, Any],
    game_state: Dict[str, Any],
    terrain_areas: List[Dict[str, Any]],
) -> List[Any]:
    """SOURCE UNIQUE du test "caché" par figurine (rule 13.09).

    Pour chaque figurine de ``by_model`` (map model_id -> (col, row)), calcule son empreinte à
    cette position (``_compute_unit_occupied_hexes`` — dépend de engagement_zone, base_shape,
    base_size et de ``unit['orientation']``) et la teste contre les zones obscurantes
    (intersection = au moins une case touchée). Read-only, sans effet de bord.

    Appelée par ``compute_hidden_statuses`` (statut réel) ET ``preview_hidden_models_from_position``
    (preview de mouvement) → garantit un résultat identique entre preview et drop, pour toute
    forme de base. Les gates niveau-unité (vivant, hideable, a tiré) sont gérés par l'appelant.
    """
    return compute_models_within_terrain(
        unit, by_model, game_state, terrain_areas, obscuring_only=True
    )


def compute_models_within_terrain(
    unit: Dict[str, Any],
    by_model: Dict[Any, Any],
    game_state: Dict[str, Any],
    terrain_areas: List[Dict[str, Any]],
    obscuring_only: bool,
) -> List[Any]:
    """Figurines de ``by_model`` dont le socle est « within a terrain area », par figurine.

    ``obscuring_only=True`` restreint aux zones obscurantes (Hidden 13.09) ; ``False`` prend
    toute zone de terrain (Benefit of Cover 13.08, volet « INFANTRY/BEASTS/SWARM within a
    terrain area »). Read-only. Généralisation de ``compute_models_in_obscuring_terrain``, dont
    elle est la source : une seule géométrie figurine↔terrain pour les deux règles.
    """
    from engine.terrain_utils import model_within_terrain
    base_shape = require_key(unit, "BASE_SHAPE")
    base_size = require_key(unit, "BASE_SIZE")
    orientation = int(require_key(unit, "orientation"))
    model_ids: List[Any] = []
    for mid, (col, row) in by_model.items():
        if model_within_terrain(
            int(col), int(row), base_shape, base_size, orientation,
            terrain_areas, obscuring_only=obscuring_only,
        ):
            model_ids.append(mid)
    return model_ids


def compute_hidden_statuses(game_state: Dict[str, Any]) -> None:
    """Set ``unit['hidden']`` and ``unit['hidden_models']`` for every unit (rule 13.09 Hidden).

    A model is hidden while it is hideable (INFANTRY/BEASTS/SWARM), its footprint touches
    an obscuring terrain area, and its unit made no ranged attack this turn nor the previous
    turn. Computed per model at shooting phase start.

    unit['hidden_models']: list of model_ids whose footprint touches obscuring terrain.
    unit['hidden']: True only if ALL alive models are hidden.
    """
    terrain_areas = require_key(game_state, "terrain_areas")
    shot_ids = {str(x) for x in game_state.get("units_shot", set())}
    shot_prev_ids = {str(x) for x in game_state.get("units_shot_previous_turn", set())}
    units_cache = require_key(game_state, "units_cache")
    for unit_id in units_cache.keys():
        unit = require_unit_by_id(game_state, str(unit_id))
        if not is_unit_alive(str(unit_id), game_state) or not bool(unit.get("hideable")):
            unit["hidden"] = False
            unit["hidden_models"] = []
            continue
        if str(unit_id) in shot_ids or str(unit_id) in shot_prev_ids:
            unit["hidden"] = False
            unit["hidden_models"] = []
            continue
        by_model = require_key(units_cache[str(unit_id)], "occupied_hexes_by_model")
        hidden_model_ids = compute_models_in_obscuring_terrain(unit, by_model, game_state, terrain_areas)
        unit["hidden_models"] = hidden_model_ids
        unit["hidden"] = len(hidden_model_ids) == len(by_model) and len(by_model) > 0


def preview_hidden_models_from_position(
    game_state: Dict[str, Any],
    unit_id: str,
    dest_col: int,
    dest_row: int,
    orientation: Optional[int] = None,
) -> Dict[str, Any]:
    """Read-only : statut "caché" (rule 13.09) de chaque figurine SI l'escouade était déplacée à
    (dest_col, dest_row) avec ``orientation``. Reproduit le chemin du move réel
    (``translate_squad_to_destination`` : translation offset rigide des figs ; l'orientation est
    appliquée à l'unité avant recalcul du footprint) puis réutilise ``compute_models_in_obscuring_terrain``
    → résultat identique au recalcul effectué après le drop, sans muter ``game_state`` ni deepcopy.

    Retourne ``{"hidden_models": [...], "hidden": bool}``.
    """
    unit_id_str = str(unit_id)
    empty = {"hidden_models": [], "hidden": False}
    unit = require_unit_by_id(game_state, unit_id_str)
    # Gates niveau-unité, identiques à compute_hidden_statuses.
    if not is_unit_alive(unit_id_str, game_state) or not bool(unit.get("hideable")):
        return empty
    shot_ids = {str(x) for x in game_state.get("units_shot", set())}
    shot_prev_ids = {str(x) for x in game_state.get("units_shot_previous_turn", set())}
    if unit_id_str in shot_ids or unit_id_str in shot_prev_ids:
        return empty
    # `is_unit_alive(unit_id_str)` en tête de fonction a déjà tranché la présence dans
    # `units_cache` : ce `return empty` est inatteignable, mais il rendait « aucune figurine
    # masquée » — un verdict de jeu — sur une désynchronisation. Preuve statique.
    entry = require_unit_from_cache(
        unit_id_str, game_state, "preview_hidden_models_from_position"
    )
    terrain_areas = require_key(game_state, "terrain_areas")
    norm_dest_col, norm_dest_row = normalize_coordinates(int(dest_col), int(dest_row))
    old_col = int(entry.get("col", norm_dest_col))
    old_row = int(entry.get("row", norm_dest_row))
    by_model = require_key(entry, "occupied_hexes_by_model")
    # Translation rigide des figs en coords CUBE — MIROIR EXACT de
    # translate_squad_to_destination (offset odd-q : un delta de colonne impair
    # déformerait le bloc, V11 T6-h). Sans mutation.
    from engine.hex_utils import offset_to_cube, cube_to_offset

    _ox, _oy, _oz = offset_to_cube(old_col, old_row)
    _nx, _ny, _nz = offset_to_cube(norm_dest_col, norm_dest_row)
    _dcx, _dcy, _dcz = _nx - _ox, _ny - _oy, _nz - _oz
    moved_by_model = {}
    for mid, (c, r) in by_model.items():
        _mx, _my, _mz = offset_to_cube(int(c), int(r))
        _nc, _nr = cube_to_offset(_mx + _dcx, _my + _dcy, _mz + _dcz)
        moved_by_model[mid] = (int(_nc), int(_nr))
    # Le move applique unit['orientation'] = orientation avant de recalculer le footprint.
    unit_for_footprint = unit if orientation is None else {**unit, "orientation": int(orientation)}
    hidden_model_ids = compute_models_in_obscuring_terrain(
        unit_for_footprint, moved_by_model, game_state, terrain_areas
    )
    return {
        "hidden_models": hidden_model_ids,
        "hidden": len(hidden_model_ids) == len(moved_by_model) and len(moved_by_model) > 0,
    }


def preview_hidden_models_from_model_positions(
    game_state: Dict[str, Any],
    unit_id: str,
    model_positions: Dict[Any, Any],
    orientation: Optional[int] = None,
) -> Dict[str, Any]:
    """Read-only : statut "caché" (rule 13.09) de chaque figurine SI elles étaient aux positions
    EXPLICITES données (``model_positions`` : map model_id -> [col, row]). Pour le déplacement
    figurine-par-figurine (perModelMove), où chaque fig a sa propre position provisoire (pas une
    translation rigide). Réutilise ``compute_models_in_obscuring_terrain`` → identique au recalcul après pose.

    Retourne ``{"hidden_models": [...], "hidden": bool}``.
    """
    unit_id_str = str(unit_id)
    empty = {"hidden_models": [], "hidden": False}
    unit = require_unit_by_id(game_state, unit_id_str)
    if not is_unit_alive(unit_id_str, game_state) or not bool(unit.get("hideable")):
        return empty
    shot_ids = {str(x) for x in game_state.get("units_shot", set())}
    shot_prev_ids = {str(x) for x in game_state.get("units_shot_previous_turn", set())}
    if unit_id_str in shot_ids or unit_id_str in shot_prev_ids:
        return empty
    terrain_areas = require_key(game_state, "terrain_areas")
    by_model = {
        str(mid): (int(pos[0]), int(pos[1])) for mid, pos in model_positions.items()
    }
    unit_for_footprint = unit if orientation is None else {**unit, "orientation": int(orientation)}
    hidden_model_ids = compute_models_in_obscuring_terrain(
        unit_for_footprint, by_model, game_state, terrain_areas
    )
    return {
        "hidden_models": hidden_model_ids,
        "hidden": len(hidden_model_ids) == len(by_model) and len(by_model) > 0,
    }


def build_unit_los_cache(
    game_state: Dict[str, Any],
    unit_id: str,
    *,
    max_target_range: Optional[int] = None,
) -> None:
    """
    tour_de_jeu.md: Calculate LoS cache for a specific unit.
    Uses units_cache and has_line_of_sight_coords() for performance.

    max_target_range: si fourni (> 0), les ennemis dont la distance bord-à-bord dépasse
        cette portée sont EXCLUS du calcul de LoS (aucun `compute_unit_los`). Utilisé par le
        move-LoS-preview : un ennemi hors portée max d'arme ne peut jamais être une cible valide,
        donc calculer sa LoS (coûteuse, par-figurine + obscuring) est inutile. Même métrique et
        même seuil que `_build_weapon_availability_enemy_precheck` → cibles valides identiques.
        Le pool tolère un ennemi absent de `los_cache` (traité comme sans LoS).

    Returns: void (updates unit["los_cache"])
    """
    unit = require_unit_by_id(game_state, unit_id)

    # Get unit position from cache (single source of truth)
    unit_pos = get_unit_position(unit, game_state)
    if unit_pos is None:
        unit["los_cache"] = {}
        return
    unit_col, unit_row = unit_pos

    # Version check: skip full rebuild if no unit has moved since last build
    current_version = game_state["_unit_move_version"]
    if unit.get("_los_cache_version") == current_version and "los_cache" in unit:
        dead_keys = [tid for tid in unit["los_cache"] if not is_unit_alive(tid, game_state)]
        for tid in dead_keys:
            unit["los_cache"].pop(tid, None)
            if "los_cover_cache" in unit:
                unit["los_cover_cache"].pop(tid, None)
        return

    # Get units_cache (must exist, built at reset)
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (built at reset)")

    units_cache = game_state["units_cache"]

    # If units_cache is empty, los_cache remains empty (no units)
    if not units_cache:
        unit["los_cache"] = {}
        return

    # Get unit's player for filtering enemies
    unit_player = int(unit["player"]) if unit["player"] is not None else None

    # Build in a local dict then assign once (avoids KeyError if unit["los_cache"] is cleared mid-build).
    los_map: Dict[str, bool] = {}
    cover_map: Dict[str, bool] = {}

    # Move-LoS-preview : filtre de portée. Prépare le socle tireur + la métrique une seule fois ;
    # les ennemis au-delà de max_target_range sont ignorés (voir docstring).
    _cull_ctx: Optional[Tuple[Any, str, int]] = None
    if isinstance(max_target_range, int) and max_target_range > 0:
        _cull_shooter_entry = units_cache.get(unit_id)
        if _cull_shooter_entry is None:
            raise KeyError(f"Unit {unit_id} not in units_cache (dead or absent)")
        _cull_ctx = (_socle_from_entry(_cull_shooter_entry), _ranged_distance_metric(game_state), max_target_range)

    # Calculate LoS for each enemy in units_cache (only alive enemies — dead must not appear in pool).
    # All visibility/cover is delegated to compute_unit_los() — the single source of truth.
    # Hors table (réserves 20.01) écarté par l'énumérateur : pas de position, donc pas de LoS.
    for target_id, target_data in enemy_entries_on_battlefield(units_cache, unit_player):
        # CRITICAL: Exclude dead units so they never appear in los_cache → valid_target_pool
        if not is_unit_alive(str(target_id), game_state):
            continue
        # Range cull (preview) : ennemi hors portée max d'arme → jamais une cible valide.
        if _cull_ctx is not None:
            from engine.combat_utils import ranged_edge_distance
            _cull_shooter_socle, _cull_metric, _cull_max = _cull_ctx
            _d = ranged_edge_distance(
                _cull_shooter_socle,
                _socle_from_entry(target_data),
                _cull_metric,
                max_distance=_cull_max,
            )
            if _d > _cull_max:
                continue
        target_unit = require_unit_by_id(game_state, str(target_id))

        los = compute_unit_los(game_state, unit, target_unit)
        los_map[str(target_id)] = los["can_see"]
        cover_map[str(target_id)] = los["cover"]

        if os.environ.get("LOS_DEBUG") == "1":
            import sys
            tcol, trow = target_data["col"], target_data["row"]
            ep = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            msg = (
                f"[LOS_DEBUG] build_unit_los_cache unit={unit_id} target={target_id} "
                f"({unit_col},{unit_row})->({tcol},{trow}) can_see={los['can_see']} "
                f"visible={los['visible']}/{los['total']} cover={los['cover']} ep={ep} turn={turn}\n"
            )
            sys.stderr.write(msg)
            sys.stderr.flush()

    unit["los_cache"] = los_map
    unit["los_cover_cache"] = cover_map
    unit["_los_cache_version"] = game_state["_unit_move_version"]


def _emit_shoot_activation_perf(
    game_state: Dict[str, Any],
    unit_id: str,
    t0: Optional[float],
    t_after_los: Optional[float],
    t_ep0: Optional[float],
    t_ep1: Optional[float],
    t_wai0: Optional[float],
    t_wai1: Optional[float],
    t_after_tgt_pool: Optional[float],
    outcome: str,
    valid_targets_n: int,
) -> None:
    """Une ligne ``SHOOT_ACTIVATION_START`` dans perf_timing.log si ``perf_timing`` est actif.

    Segments armes (après ``los_cache_s``) :
    - ``activation_prep_s`` : entre fin LoS et début ``_build_weapon_availability_enemy_precheck`` ;
    - ``enemy_precheck_s`` : uniquement ``_build_weapon_availability_enemy_precheck`` ;
    - ``weapon_avail_inner_s`` : uniquement ``weapon_availability_check`` (avec ``_precheck`` déjà fourni).

    Somme ``enemy_precheck_s`` + ``weapon_avail_inner_s`` ≈ coût total de la passe « armes » avant le pool
    de cibles (à rapprocher de la ligne ``WEAPON_AVAILABILITY_CHECK`` qui ne mesure que l’intérieur de
    ``weapon_availability_check``).
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    if not perf_timing_enabled(game_state) or t0 is None:
        return
    t_end = time.perf_counter()
    los_s = (t_after_los - t0) if t_after_los is not None else 0.0
    activation_prep_s = (t_ep0 - t_after_los) if t_after_los is not None and t_ep0 is not None else 0.0
    enemy_precheck_s = (t_ep1 - t_ep0) if t_ep0 is not None and t_ep1 is not None else 0.0
    weapon_avail_inner_s = (t_wai1 - t_wai0) if t_wai0 is not None and t_wai1 is not None else 0.0
    pool_s = (t_after_tgt_pool - t_wai1) if t_after_tgt_pool is not None and t_wai1 is not None else 0.0
    tail_s = (t_end - t_after_tgt_pool) if t_after_tgt_pool is not None else (t_end - t0)
    total_s = t_end - t0
    ep = game_state.get("episode_number", "?")
    trn = game_state.get("turn", "?")
    append_perf_timing_line(
        f"SHOOT_ACTIVATION_START episode={ep} turn={trn} unit_id={unit_id} "
        f"los_cache_s={los_s:.6f} activation_prep_s={activation_prep_s:.6f} "
        f"enemy_precheck_s={enemy_precheck_s:.6f} weapon_avail_inner_s={weapon_avail_inner_s:.6f} "
        f"target_pool_s={pool_s:.6f} tail_s={tail_s:.6f} total_s={total_s:.6f} "
        f"outcome={outcome} valid_targets_n={valid_targets_n}"
    )


def _apply_preview_placement(
    gs: Dict[str, Any], unit_id_str: str, unit: Dict[str, Any], placement: Tuple[Any, ...]
) -> None:
    """Pose l'escouade sur la COPIE d'aperçu, selon la forme du placement.

    Les deux branches passent par les écrivains RÉELS du moteur — `translate_squad_to_destination`
    pour un placement à l'ancre, `update_model_position` pour les figurines — et non par une
    écriture directe du cache : c'est ce qui garantit que l'aperçu et l'état après validation
    décrivent la même empreinte. `update_model_position` resynchronise au passage
    `occupied_hexes` et l'ancre de l'escouade, donc rien n'est à recalculer ici.
    """
    kind = placement[0]
    if kind == "anchor":
        _unused, dest_col, dest_row = placement
        set_unit_coordinates(unit, int(dest_col), int(dest_row))
        # « Pose l'escouade à cette ancre » = déplacement RIGIDE, donc figurines comprises.
        # `update_units_cache_position` ne bouge que l'ancre : sur une escouade multi-figurines,
        # l'aperçu mesurait la LoS et les cibles depuis l'empreinte RESTÉE à la position
        # courante, pour chaque case survolée — un aperçu qui ne décrit pas ce qu'il annonce.
        translate_squad_to_destination(gs, unit_id_str, int(unit["col"]), int(unit["row"]))
        return
    if kind == "models":
        from engine.phase_handlers.shared_utils import (
            _los_begin_batch,
            _los_end_batch,
            place_model_at_effective_level,
        )

        models_cache = require_key(gs, "models_cache")
        # Batch LoS : `update_model_position` invalide les caches de LoS à CHAQUE appel, et
        # chaque invalidation balaie `los_cache` et `hex_los_cache` en entier. En posant N
        # figurines une à une, on payait N balayages là où un seul suffit. Même encadrement que
        # `commit_move`, le seul autre écrivain multi-figurines du dépôt (« choke-point LoS D1 »).
        # MESURÉ à 6 figurines sur un cache de 20 000 entrées : 8,85 ms → 2,19 ms.
        _los_owned = _los_begin_batch(gs)
        try:
            for entry in placement[1]:
                model_id, col, row, level, orientation = entry
                model = models_cache.get(str(model_id))  # get allowed (absence = plan incohérent)
                if model is None or str(require_key(model, "squad_id")) != unit_id_str:
                    raise KeyError(
                        f"_apply_preview_placement: figurine {model_id!r} absente de l'escouade "
                        f"{unit_id_str!r} — plan incohérent, pas une figurine à ignorer"
                    )
                # NIVEAU EFFECTIF, JAMAIS LE NIVEAU BRUT DU PLAN (§13.06) : le niveau porté par
                # le plan est celui de la VUE au drop, que `deploy_generate_formation` estampe sur
                # TOUTES les figurines sans vérifier chacune. L'écrire tel quel faisait lever
                # `floor_height_at` — requête en 500, client privé de TOUT son calque de LoS.
                # L'orientation visée entre dans la résolution (elle oriente l'empreinte) puis est
                # écrite : la primitive fait les deux, dans cet ordre, pour tous les écrivains.
                place_model_at_effective_level(
                    gs, model_id, int(col), int(row), int(level),
                    orientation=None if orientation is None else int(orientation),
                )
        finally:
            _los_end_batch(gs, _los_owned)
        return
    raise ValueError(f"_apply_preview_placement: forme de placement inconnue {kind!r}")


def preview_shoot_valid_targets_from_position(
    game_state: Dict[str, Any],
    unit_id: str,
    dest_col: int,
    dest_row: int,
    *,
    advance_position: bool = False,
    include_los_cells: bool = True,
) -> Dict[str, Any]:
    """Aperçu de tir depuis une ANCRE hypothétique (lecture pure, aucune mutation).

    ⚠️ PLACEMENT PAR ANCRE — ne convient qu'à une escouade DÉJÀ SUR LA TABLE, déplacée d'un bloc.
    Les figurines SUIVENT l'ancre depuis le 2026-08-12 (`translate_squad_to_destination`, qui
    translate le bloc en préservant la formation) ; auparavant elles restaient en place pour une
    escouade multi-figurines et l'aperçu mesurait depuis l'empreinte d'origine.
    La limite qui SUBSISTE est ailleurs : une escouade PAS ENCORE DÉPLOYÉE a toutes ses figurines
    sur la sentinelle `(-1,-1)`, donc aucune formation à translater — elles s'empilent sur
    l'ancre et l'aperçu mesure depuis un point unique. Pour un placement figurine par figurine —
    déploiement en cours, `perModelMove` — utiliser
    `preview_shoot_valid_targets_from_model_positions`, qui pose CHAQUE figurine.

    Args:
        advance_position: Si True, simule une unité après Advance (``units_advanced`` sur la copie).
        include_los_cells: Si False, ne calcule pas la grille complète LoS (coûteuse) et renvoie
            seulement les cibles tirables backend + couvert par cible.
    """
    return _preview_shoot_valid_targets(
        game_state,
        unit_id,
        placement=("anchor", int(dest_col), int(dest_row)),
        advance_position=advance_position,
        include_los_cells=include_los_cells,
    )


def preview_shoot_valid_targets_from_model_positions(
    game_state: Dict[str, Any],
    unit_id: str,
    model_plan: Any,
    *,
    advance_position: bool = False,
    include_los_cells: bool = True,
) -> Dict[str, Any]:
    """Aperçu de tir depuis le PLAN par figurine (lecture pure).

    Jumeau de `preview_hidden_models_from_model_positions`, pour la même raison : pendant un
    placement figurine par figurine, le plan vit dans le CLIENT et le moteur n'en sait rien avant
    la validation. L'escouade y est donc hors table (`occupied_hexes_by_model` à `(-1,-1)`), et un
    aperçu placé par l'ancre mesurait distances et LoS depuis le coin du plateau sans jamais lever
    — un verdict inventé, précisément ce que `require_entry_on_battlefield` refuse ailleurs.

    ``model_plan`` est le format CANONIQUE du plan, `[[model_id, col, row, level, orientation?]]`,
    lu par le MÊME parseur que la pose réelle (`parse_model_plan_with_orientation`). Le niveau et
    l'orientation en font partie et ne sont pas optionnels par confort :
    - le NIVEAU décide du gate vertical de la LoS 3D (§03.04) — une figurine déployée à l'étage
      d'une ruine, prévisualisée au sol, donne un blink et un couvert qui basculent après
      validation ;
    - l'ORIENTATION décide de l'empreinte d'un socle ovale ou carré (pivot molette du move).
    Les ignorer ferait mesurer à l'aperçu une géométrie que la validation ne reproduit pas — le
    défaut que cette fonction existe pour supprimer, déplacé d'un cran.

    Chaque figurine est posée par `update_model_position`, qui resynchronise l'empreinte de
    l'escouade et son ancre : c'est le MÊME écrivain que la pose réelle.

    Une figurine inconnue lève (incohérence de plan), un plan vide lève (rien à mesurer), une
    position hors table lève (la sentinelle n'a pas de sens en ENTRÉE : ce sont les positions
    choisies par le joueur).
    """
    from engine.phase_handlers.shared_utils import parse_model_plan_with_orientation

    action_name = "preview_shoot_valid_targets_from_model_positions"
    parsed = parse_model_plan_with_orientation(model_plan, action_name=action_name)
    if not parsed:
        raise ValueError(
            f"{action_name}: aucune figurine pour l'unité {unit_id!r} — un aperçu sans position "
            f"n'a rien à mesurer"
        )
    for model_id, col, row, _level, _orientation in parsed:
        if col < 0 or row < 0:
            raise ValueError(
                f"{action_name}: figurine {model_id!r} de l'unité {unit_id!r} HORS TABLE "
                f"({col},{row}) — les positions viennent du plan du joueur, la sentinelle n'y a "
                f"pas de sens"
            )
    return _preview_shoot_valid_targets(
        game_state,
        unit_id,
        placement=("models", tuple(sorted(parsed))),
        advance_position=advance_position,
        include_los_cells=include_los_cells,
    )


def _preview_shoot_valid_targets(
    game_state: Dict[str, Any],
    unit_id: str,
    *,
    placement: Tuple[Any, ...],
    advance_position: bool = False,
    include_los_cells: bool = True,
) -> Dict[str, Any]:
    """Corps commun des deux aperçus : SEUL le placement diffère.

    Aligné sur l'activation tir : copie d'état, tireur déplacé virtuellement, ``build_unit_los_cache``
    puis ``valid_target_pool_build`` (empreintes §3.3, CLOSE_QUARTERS / adjacent, alliés au contact, etc.).

    L'ancienne implémentation (distance centre-à-centre + ``compute_los_state`` seuls) pouvait
    marquer des cibles « valides » alors que le pool moteur les exclut.
    """
    empty_preview: Dict[str, Any] = {
        "valid_targets": [],
        "los_preview_attack_cells": [],
        "los_preview_cover_cells": [],
        "los_preview_ratio_by_hex": {},
        "cover_by_unit_id": {},
        "cover_conditions_by_unit_id": {},
        "hidden_too_far_by_unit_id": {},
        "hidden_detection_info_by_unit_id": {},
        "visible_cells_by_target": {},
    }

    unit_id_str = str(unit_id)
    unit = require_unit_by_id(game_state, unit_id_str)
    if not game_state.get("units_cache"):
        return empty_preview
    if not ranged_weapons(unit):
        return empty_preview

    preview_cache_key: Optional[Tuple[Any, ...]] = None
    if not include_los_cells:
        preview_cache_key = _move_los_preview_cache_key(
            game_state,
            unit,
            unit_id_str,
            placement,
            advance_position,
        )
        cached_preview = _move_los_preview_cache.get(preview_cache_key)
        if cached_preview is not None:
            return copy.deepcopy(cached_preview)

    # Preview read-only : ``config`` et ``weapon_damage_table`` sont des données statiques
    # écrites uniquement à l'init du jeu (w40k_core), jamais durant une action. On les partage
    # PAR RÉFÉRENCE via le memo de deepcopy (elles pèsent ~50% du coût) au lieu de les copier ;
    # le reste de game_state est deepcopié normalement (cross-références préservées).
    # `_move_spatial_cache` est un cache PUR (ensembles spatiaux du move) dont chaque lecture
    # revalide un fingerprint de l'état. Le partager par référence au lieu de le copier est donc
    # sans risque : si la preview bouge une figurine, le fingerprint change et la preview se
    # reconstruit SON propre holder, sans toucher celui de l'état réel.
    #
    # MÊME RAISONNEMENT pour les cinq clés suivantes, chacune vérifiée individuellement — le
    # deepcopy est 99 % du coût de l'aperçu, et l'aperçu part à CHAQUE pose de figurine :
    #   - `objectives` / `terrain_areas` / `deployment_pools` : écrites une fois au chargement du
    #     scénario (`w40k_core`), jamais pendant une action ;
    #   - `_obscuring_area_sets_cache` : RÉ-ASSIGNÉ (`game_state[...] = out`, construit dans un
    #     local), jamais muté en place — une reconstruction sur la copie ne touche pas l'original ;
    #   - `_objective_hex_zones_cache` : idem, ré-assigné en bloc — le triplet
    #     `(objectifs, zones, union)` est reconstruit entier, jamais modifié en place.
    # MESURÉ sur le scénario d'entraînement : 124,5 ms → 54,4 ms de deepcopy, soit 70 ms rendus
    # par aperçu.
    #
    # ⚠️ `_deployment_scoring_cache` est VOLONTAIREMENT ABSENT alors qu'il est le plus gros poste
    # (55 ms) : c'est le seul de la liste qui soit muté EN PLACE (`setdefault` puis écriture d'une
    # sous-clé par joueur, `action_decoder`). Le partager par référence marcherait tant qu'aucun
    # aperçu ne déclenche de scoring de déploiement — c'est-à-dire jusqu'au jour où l'un le fera,
    # et il écrirait alors dans l'état RÉEL depuis une copie de travail. Un gain de 55 ms ne paie
    # pas ce risque-là.
    _preview_share_memo: Dict[int, Any] = {}
    for _shared_key in (
        "config",
        "weapon_damage_table",
        "_move_spatial_cache",
        "objectives",
        "terrain_areas",
        "deployment_pools",
        "_obscuring_area_sets_cache",
        "_objective_hex_zones_cache",
    ):
        _shared_val = game_state.get(_shared_key)
        if _shared_val is not None:
            _preview_share_memo[id(_shared_val)] = _shared_val

    gs = copy.deepcopy(game_state, _preview_share_memo)
    # Preview de la phase de MOVE : elle simule une future activation de tir alors que
    # `shooting_phase_start` (seul poseur de `weapon_rule`) n a pas encore tourne. Cette
    # initialisation est donc un MONTAGE de simulation sur la copie `gs`, au meme titre que
    # `weapon["shot"] = 0` juste en dessous — pas un defaut qui rattraperait une absence
    # anormale dans l etat reel (l etat reel, lui, exige la cle).
    if "weapon_rule" not in gs:
        gs["weapon_rule"] = 1

    u = require_unit_by_id(gs, unit_id_str)

    u.pop("valid_target_pool", None)
    u.pop("_pool_from_cache", None)
    u.pop("_pool_cache_key", None)

    # Move-phase preview simulates a fresh future shooting activation; weapon["shot"]
    # is normally initialized at shooting_phase_start, which has not run yet.
    for weapon in require_key(u, "RNG_WEAPONS"):
        weapon["shot"] = 0

    _apply_preview_placement(gs, unit_id_str, u, placement)

    if advance_position:
        ua_raw = gs.get("units_advanced") or []
        ua_list = list(ua_raw)
        if not any(str(x) == unit_id_str for x in ua_list):
            ua_list.append(unit_id_str)
        gs["units_advanced"] = ua_list

    if unit_id_str in require_key(gs, "units_fled") and not _unit_has_rule(u, "shoot_after_flee"):
        return empty_preview

    weapon_rule = require_key(gs, "weapon_rule")
    advance_status = (
        1 if any(str(x) == unit_id_str for x in require_key(gs, "units_advanced")) else 0
    )
    if advance_status == 1:
        adjacent_status = 0
    else:
        adjacent_status = 1 if _is_adjacent_to_enemy_within_cc_range(gs, u) else 0

    # Portée max d'arme du tireur : au-delà, un ennemi ne peut jamais être ciblé → on évite
    # de calculer sa LoS (poste dominant du preview). Même métrique que le pool de cibles.
    _preview_max_rng = 0
    for _w in require_key(u, "RNG_WEAPONS"):
        _r = require_key(_w, "RNG")
        if _r > _preview_max_rng:
            _preview_max_rng = _r

    build_unit_los_cache(
        gs, unit_id_str,
        max_target_range=_preview_max_rng if _preview_max_rng > 0 else None,
    )
    preview_enemy_precheck = _build_weapon_availability_enemy_precheck(
        gs, u, require_key(u, "RNG_WEAPONS")
    )
    preview_weapon_available_pool = weapon_availability_check(
        gs,
        u,
        weapon_rule,
        advance_status,
        adjacent_status,
        _precheck=preview_enemy_precheck,
    )

    valid_targets = valid_target_pool_build(
        gs,
        u,
        weapon_rule,
        advance_status,
        adjacent_status,
        precomputed_weapon_available_pool=preview_weapon_available_pool,
        precomputed_enemy_precheck=preview_enemy_precheck,
    )
    if include_los_cells:
        _update_unit_los_preview_data(gs, u, weapon_rule, advance_status, adjacent_status)
    else:
        u["los_preview_attack_cells"] = []
        u["los_preview_cover_cells"] = []
        u["los_preview_ratio_by_hex"] = {}

    cover_by_unit_id = build_cover_by_unit_id_for_valid_targets(gs, u, valid_targets)
    cover_conditions_by_unit_id = build_cover_conditions_by_unit_id(gs, u, valid_targets)
    visible_cells_by_target = build_visible_cells_by_target(gs, u, valid_targets)

    result_payload = {
        "valid_targets": valid_targets,
        "los_preview_attack_cells": require_key(u, "los_preview_attack_cells"),
        "los_preview_cover_cells": require_key(u, "los_preview_cover_cells"),
        "los_preview_ratio_by_hex": require_key(u, "los_preview_ratio_by_hex"),
        "cover_by_unit_id": cover_by_unit_id,
        "cover_conditions_by_unit_id": cover_conditions_by_unit_id,
        "hidden_too_far_by_unit_id": build_hidden_too_far_by_unit_id(gs, u),
        "hidden_detection_info_by_unit_id": build_hidden_detection_info_by_unit_id(gs, u),
        "visible_cells_by_target": visible_cells_by_target,
    }
    if preview_cache_key is not None:
        if len(_move_los_preview_cache) >= _cache_size_limit:
            _move_los_preview_cache.clear()
        _move_los_preview_cache[preview_cache_key] = copy.deepcopy(result_payload)
    return result_payload


def build_cover_by_unit_id_for_valid_targets(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    valid_targets: List[str],
) -> Dict[str, bool]:
    """Return backend cover status for each valid shooting target."""
    cover_by_unit_id: Dict[str, bool] = {}
    los_cover_cache = require_key(shooter, "los_cover_cache")
    for target_id in valid_targets:
        target_id_str = str(target_id)
        if target_id_str not in los_cover_cache:
            raise KeyError(f"Target {target_id_str} is in valid_target_pool but missing from los_cover_cache")
        cover_by_unit_id[target_id_str] = bool(los_cover_cache[target_id_str])
    return cover_by_unit_id


def build_cover_conditions_by_unit_id(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    valid_targets: List[str],
) -> Dict[str, List[str]]:
    """Condition 13.08 remplie par CHAQUE figurine, pour chaque cible valide.

    DIAGNOSTIC D'AFFICHAGE : alimente le badge de couvert par figurine du PvP. Le couvert reste
    tout-ou-rien pour la RÉSOLUTION (-1 BS) — celui-là se lit sur
    ``build_cover_by_unit_id_for_valid_targets``, jamais ici.

    Sans cette information, le frontend ne peut que répliquer le booléen d'unité sur chaque
    figurine : une escouade dont une seule figurine est découverte perd le couvert, et AUCUNE
    des figurines réellement en terrain n'affiche alors de badge — le joueur lit une inversion.

    Source unique = ``compute_unit_los`` (la même que le blink et le couvert d'unité) ; le
    pair-cache absorbe l'appel, déjà fait par les autres constructeurs de l'aperçu.
    """
    out: Dict[str, List[str]] = {}
    for target_id in valid_targets:
        target_id_str = str(target_id)
        target_unit = require_unit_by_id(game_state, target_id_str)
        los = compute_unit_los(game_state, shooter, target_unit)
        out[target_id_str] = [str(c) for c in los["cover_conditions"]]
    return out


def build_visible_cells_by_target(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    valid_targets: List[str],
) -> Dict[str, List[List[int]]]:
    """Cellules de l'empreinte réellement vues, par cible valide (règle 06.01/13.10 par-figurine).

    Source unique = ``compute_unit_los`` (le même calcul que le blink). Le frontend peint ces
    cases par-dessus le cône WASM : une cible qui blinke a donc toujours ses cases visibles
    peintes, avec l'exclusion obscuring correcte par-figurine — supprime la divergence
    « unité ciblable hors du cône ». Coût borné aux seules cibles valides (pas de scan plateau).
    """
    out: Dict[str, List[List[int]]] = {}
    for target_id in valid_targets:
        target_id_str = str(target_id)
        target_unit = require_unit_by_id(game_state, target_id_str)
        los = compute_unit_los(game_state, shooter, target_unit)
        out[target_id_str] = [[int(c), int(r)] for c, r in los["visible_cells"]]
    return out


def build_hidden_too_far_by_unit_id(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
) -> Dict[str, bool]:
    """Ennemis "cachés trop loin" relativement au tireur actif (œil rouge frontend).

    Une unité ``hidden`` (rule 13.09, empreinte en terrain obscurcissant), dans la LoS et à
    portée d'une arme du tireur, MAIS au-delà de ``detection_range`` (15") : elle est exclue du
    pool de cibles valides (donc absente de ``cover_by_unit_id``) alors qu'elle reste "en vue
    géométriquement". Source unique pour les deux moteurs de résolution (mono-unité et squad) :
    read-only, relatif au tireur actif. Réutilise ``unit['los_cache']`` (build_unit_los_cache).
    """
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    _ranged_metric = _ranged_distance_metric(game_state)
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    detection_range_subhex = (
        float(require_key(game_rules, "detection_range"))
        * int(require_key(game_state, "inches_to_subhex"))
    )
    rng_weapons = require_key(shooter, "RNG_WEAPONS")
    max_rng = max((require_key(w, "RNG") for w in rng_weapons), default=0)
    if max_rng <= 0:
        return {}
    los_cache = shooter.get("los_cache")
    if not los_cache:
        return {}
    shooter_id = str(require_key(shooter, "id"))
    shooter_player = int(require_key(shooter, "player"))
    shooter_entry = require_unit_from_cache(
        shooter_id, game_state, "build_hidden_too_far_by_unit_id/shooter"
    )
    _shooter_socle = socle_from_cache_entry(shooter_entry)
    result: Dict[str, bool] = {}
    for target_id, has_los in los_cache.items():
        if not has_los:
            continue
        target_id_str = str(target_id)
        if target_id_str == shooter_id:
            continue
        # Preuve statique : target_id vient de los_cache, peuplé par build_unit_los_cache qui
        # exige unit_by_id (require_unit_by_id). unit_by_id ne rétrécit jamais → require ne lève pas.
        enemy = require_unit_by_id(game_state, target_id_str)
        if not is_unit_alive(target_id_str, game_state):
            continue
        if int(require_key(enemy, "player")) == shooter_player:
            continue
        if not bool(enemy.get("hidden")):
            continue
        # Contrat de `is_unit_alive` (cf. son docstring) : la garde ci-dessus prouve la présence.
        # Le `continue` qui était ici aurait effacé un ennemi masqué du rapport « trop loin ».
        enemy_entry = require_unit_from_cache(
            target_id_str, game_state, "build_hidden_too_far_by_unit_id/target"
        )
        distance = ranged_edge_distance(
            _shooter_socle, socle_from_cache_entry(enemy_entry), _ranged_metric, max_distance=max_rng
        )
        if distance > max_rng:
            continue  # hors portée : pas "à portée mais trop loin"
        # Rule 13.09 + 13.5 : "trop loin" = hors detection per-figurine (avec −3" gone to ground
        # pour les figurines masquées par un terrain Solid intervenant).
        if hidden_enemy_out_of_detection(game_state, shooter, enemy, detection_range_subhex):
            result[target_id_str] = True
    return result


def _all_enemy_models_gone_to_ground(
    game_state: Dict[str, Any],
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    enemy: Dict[str, Any],
    dense_wall_set: Set[Tuple[int, int]],
    gym_training: bool,
    ignored_wall_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """True si TOUTES les figurines vivantes de l'ennemi sont "gone to ground" vis-à-vis du tireur.

    Une figurine est GtG quand son empreinte n'est pas entièrement visible à cause d'un terrain
    Solid intervenant (règle 13.5, _model_footprint_not_fully_visible_due_to_solid). Utilisé pour
    déterminer si la detection range affichée est 12" (toutes GtG) ou 15" (au moins une non-GtG).
    """
    if not dense_wall_set:
        return False
    footprints, _centers, _bshape, _bsize, _borient, _levels = _resolve_target_models_for_los(
        game_state, enemy, gym_training
    )
    if not footprints:
        return False
    for model_hexes in footprints:
        if not _model_footprint_not_fully_visible_due_to_solid(
            game_state, shooter_anchor, shooter_hexes, model_hexes, dense_wall_set,
            ignored_wall_hexes,
        ):
            return False
    return True


def build_hidden_detection_info_by_unit_id(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Detection range effective et statut "trop loin" par ennemi caché, relatifs au tireur actif.

    Retourne pour chaque ennemi caché en LoS + à portée d'arme :
      {"detection_inches": 15 | 12, "too_far": bool}
    detection_inches = 12 si TOUTES les figurines vivantes sont "gone to ground" (règle 13.5),
    sinon 15. too_far = cohérent avec build_hidden_too_far_by_unit_id (appelle
    hidden_enemy_out_of_detection). Rétro-compat : build_hidden_too_far_by_unit_id reste inchangé.
    """
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    _ranged_metric = _ranged_distance_metric(game_state)
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    detection_range_subhex = (
        float(require_key(game_rules, "detection_range"))
        * int(require_key(game_state, "inches_to_subhex"))
    )
    base_inches = int(require_key(game_rules, "detection_range"))
    rng_weapons = require_key(shooter, "RNG_WEAPONS")
    max_rng = max((require_key(w, "RNG") for w in rng_weapons), default=0)
    if max_rng <= 0:
        return {}
    los_cache = shooter.get("los_cache")
    if not los_cache:
        return {}
    shooter_id = str(require_key(shooter, "id"))
    shooter_player = int(require_key(shooter, "player"))
    shooter_entry = require_unit_from_cache(
        shooter_id, game_state, "build_hidden_detection_info_by_unit_id/shooter"
    )
    _shooter_socle = socle_from_cache_entry(shooter_entry)
    gym_training = bool(
        game_state.get("gym_training_mode", False)
        or require_key(game_state, "config").get("gym_training_mode", False)
    )
    shooter_anchor, shooter_hexes = _resolve_unit_anchor_and_footprint(
        game_state, shooter, gym_training=gym_training
    )
    dense_wall_set = _get_dense_wall_set(game_state)
    gtg_penalty_inches = 3
    result: Dict[str, Dict[str, Any]] = {}
    for target_id, has_los in los_cache.items():
        if not has_los:
            continue
        target_id_str = str(target_id)
        if target_id_str == shooter_id:
            continue
        # Preuve statique : target_id vient de los_cache, peuplé par build_unit_los_cache qui
        # exige unit_by_id (require_unit_by_id). unit_by_id ne rétrécit jamais → require ne lève pas.
        enemy = require_unit_by_id(game_state, target_id_str)
        if not is_unit_alive(target_id_str, game_state):
            continue
        if int(require_key(enemy, "player")) == shooter_player:
            continue
        if not bool(enemy.get("hidden")):
            continue
        # Contrat de `is_unit_alive` (cf. son docstring) : la garde ci-dessus prouve la présence.
        # Le `continue` qui était ici aurait effacé un ennemi masqué du rapport « trop loin ».
        enemy_entry = require_unit_from_cache(
            target_id_str, game_state, "build_hidden_detection_info_by_unit_id/target"
        )
        distance = ranged_edge_distance(
            _shooter_socle, socle_from_cache_entry(enemy_entry), _ranged_metric, max_distance=max_rng
        )
        if distance > max_rng:
            continue
        all_gtg = _all_enemy_models_gone_to_ground(
            game_state, shooter_anchor, shooter_hexes, enemy, dense_wall_set, gym_training,
            _walls_around_occupied_floor(game_state, shooter, shooter_hexes),
        )
        detection_inches = base_inches - gtg_penalty_inches if all_gtg else base_inches
        too_far = hidden_enemy_out_of_detection(game_state, shooter, enemy, detection_range_subhex)
        result[target_id_str] = {"detection_inches": detection_inches, "too_far": too_far}
    return result


def update_los_cache_after_target_death(game_state: Dict[str, Any], dead_target_id: str) -> None:
    """
    tour_de_jeu.md: Update LoS cache after target death.
    Removes dead target from active unit's los_cache.
    
    NOTE: units_cache removal is handled by update_units_cache_hp when HP becomes 0.
    
    Returns: void (updates unit["los_cache"])
    """
    dead_target_id_str = str(dead_target_id)
    
    # Update active unit's los_cache (only active unit has los_cache)
    active_unit_id = game_state.get("active_shooting_unit")
    if active_unit_id:
        active_unit = require_unit_by_id(game_state, active_unit_id)
        if "los_cache" in active_unit:
            if dead_target_id_str in active_unit["los_cache"]:
                del active_unit["los_cache"][dead_target_id_str]


def _remove_dead_unit_from_pools(game_state: Dict[str, Any], dead_unit_id: str) -> None:
    """
    Remove dead unit from all activation pools.
    Called when a unit dies to ensure it cannot act in any phase.
    PRINCIPLE: "Le Pool DOIT gérer les morts" - This function ensures dead units are removed immediately.
    """
    unit_id_str = str(dead_unit_id)
    
    # DEBUG: Log dead unit removal
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    hp_cur = get_hp_from_cache(unit_id_str, game_state)  # Phase 2: from cache (None if dead)
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: Removing dead Unit {unit_id_str} (HP_CUR={hp_cur})")
    
    # Remove from shooting activation pool
    if "shoot_activation_pool" in game_state:
        pool_before = len(game_state["shoot_activation_pool"])
        was_in_pool = unit_id_str in [str(uid) for uid in game_state["shoot_activation_pool"]]
        # Normalize pool to contain only strings (consistent with pool construction at line 641)
        game_state["shoot_activation_pool"] = [str(uid) for uid in game_state["shoot_activation_pool"] if str(uid) != unit_id_str]
        pool_after = len(game_state["shoot_activation_pool"])
        add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: shoot_activation_pool before={pool_before} after={pool_after} was_in_pool={was_in_pool}")
        # Verify removal worked (defense in depth)
        if pool_before == pool_after and unit_id_str in [str(uid) for uid in game_state["shoot_activation_pool"]]:
            # Unit was not removed - this is a bug, force removal
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} _remove_dead_unit_from_pools: BUG - Unit {unit_id_str} still in pool after removal, forcing removal")
            # Normalize pool to contain only strings (consistent with pool construction at line 641)
            game_state["shoot_activation_pool"] = [str(uid) for uid in game_state["shoot_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from movement activation pool
    if "move_activation_pool" in game_state:
        game_state["move_activation_pool"] = [uid for uid in game_state["move_activation_pool"] if str(uid) != unit_id_str]
    
    # Remove from charge activation pool
    if "charge_activation_pool" in game_state:
        game_state["charge_activation_pool"] = [uid for uid in game_state["charge_activation_pool"] if str(uid) != unit_id_str]

    # If the dead unit was currently active for shooting, clear active selector immediately.
    active_shooting_unit = game_state.get("active_shooting_unit")
    if active_shooting_unit is not None and str(active_shooting_unit) == unit_id_str:
        del game_state["active_shooting_unit"]


def _invalidate_los_cache_for_moved_unit(
    game_state: Dict[str, Any],
    moved_unit_id: str,
    *,
    old_col: Optional[int] = None,
    old_row: Optional[int] = None,
) -> None:
    """
    Invalidate LoS cache when unit moves.
    Direct field access, no state copying.
    
    When a unit moves, its position changes, so all LoS calculations involving
    that unit are now invalid. Remove all cache entries involving the moved unit.
    
    CRITICAL: This prevents "shoot through wall" bugs caused by stale cache
    when units move between positions.
    
    Invalidates BOTH caches:
    - los_cache: key = (shooter_id, target_id) - invalidate entries with moved_unit_id
    - hex_los_cache: key = ((from_col, from_row), (to_col, to_row)) - clear all entries
      (easier to clear all than to track which hexes involved the moved unit)

    Aucune coercition sur les clés : les trois sites qui écrivent `game_state["los_cache"]`
    (`build_los_cache`, la recalculation par unité, le remplissage paresseux de
    `_shooter_can_see_target`) les construisent tous en `(str(id), str(id))`, et `old_col` /
    `old_row` viennent de `units_cache`, où ils sont déjà `int`. Comparer via `str(...)`
    laisserait passer des clés mal typées au lieu de faire échouer leur producteur.
    """
    if "los_cache" in game_state:
        keys_to_remove = [
            key for key in game_state["los_cache"].keys()
            if key[0] == moved_unit_id or key[1] == moved_unit_id
        ]
        for key in keys_to_remove:
            del game_state["los_cache"][key]
    
    # _hex_los_state_cache: NOT invalidated on unit movement.
    # Stores compute_los_state() results keyed by ((sc,sr),(ec,er)) — depends only on
    # wall_set (static terrain). Permanent for the duration of a game.
    # Invalidating here caused O(cache_size) scans on every move (~50s/episode on x10 boards).
    #
    # hex_los_cache: selective invalidation maintained (calls _has_line_of_sight which reads
    # occupied_hexes from units_cache — result is footprint-dependent, not purely geometric).
    if "hex_los_cache" in game_state:
        if old_col is not None and old_row is not None:
            old_pos = (old_col, old_row)
            keys_to_remove = [
                k for k in game_state["hex_los_cache"].keys()
                if (k[0] == old_pos or k[1] == old_pos)
            ]
            for k in keys_to_remove:
                del game_state["hex_los_cache"][k]
        else:
            game_state["hex_los_cache"] = {}


def shooting_build_activation_pool(game_state: Dict[str, Any]) -> List[str]:
    """
    Build activation pool with comprehensive debug logging
    """
    current_player = int(game_state["current_player"]) if game_state["current_player"] is not None else None
    if current_player is None:
        raise ValueError("game_state['current_player'] must be set for shooting activation pool")
    shoot_activation_pool = []
    
    # DEBUG: Log pool building for dead unit detection
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: Building pool for player {current_player}")
    
    # CRITICAL: Clear pool before rebuilding (defense in depth)
    game_state["shoot_activation_pool"] = []
    
    units_cache = require_key(game_state, "units_cache")
    for unit_id, cache_entry in units_cache.items():
        unit = _get_unit_by_id(game_state, unit_id)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        unit_id = unit.get("id", "?")
        hp_cur = require_key(cache_entry, "HP_CUR")
        cache_player = require_key(cache_entry, "player")
        try:
            unit_player = int(cache_player)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid player value in units_cache for unit {unit_id}: {cache_player}") from exc
        
        # CRITICAL: Only process units of current player
        if unit_player != current_player:
            continue  # Skip units of other players

        # HORS TABLE (réserves 20.01 / attente de déploiement) : l'unité n'est pas sur le champ
        # de bataille, elle ne tire pas.
        if not entry_is_on_battlefield(cache_entry):
            continue

        # CRITICAL: units_cache is source of truth; missing entry means unit is dead/removed
        if hp_cur is None:
            continue
        
        # PRINCIPLE: "Le Pool DOIT gérer les morts" - Only add alive units of current player
        # CRITICAL: Normalize unit ID to string when adding to pool to ensure consistent types
        has_targets = _has_valid_shooting_targets(game_state, unit, current_player)
        if has_targets:
            shoot_activation_pool.append(str(unit["id"]))
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: ADDED Unit {unit_id} (player={unit_player}, HP_CUR={hp_cur})")
        else:
            # Log why unit was NOT added (for debugging dead units in pool)
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: SKIPPED Unit {unit_id} (player={unit_player}, HP_CUR={hp_cur}, has_targets={has_targets})")
    
    # Update game_state pool
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - Pool is built correctly (only alive units of current player via _has_valid_shooting_targets)
    game_state["shoot_activation_pool"] = shoot_activation_pool
    add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} shooting_build_activation_pool: Pool built with {len(shoot_activation_pool)} units: {shoot_activation_pool}")

    from engine.game_utils import add_debug_file_log
    add_debug_file_log(game_state, f"[POOL BUILD] E{episode} T{turn} shoot shoot_activation_pool={shoot_activation_pool}")
    
    return game_state["shoot_activation_pool"]

def _unit_has_firable_target(game_state: Dict[str, Any], unit: Dict[str, Any],
                             is_adjacent: bool, max_range: int) -> bool:
    """
    True si au moins un ennemi vivant est une cible de tir valide pour ``unit``, borné à la portée
    ``max_range`` de son arme tirable la plus longue dans l'état courant.

    Reprend exactement les contraintes de _is_valid_shooting_target (portée footprint, engagement,
    blocage par corps-à-corps allié, LoS), mais avec la portée des armes réellement tirables plutôt
    que la portée max brute — sans dépendre de l'arme sélectionnée (état ``is_adjacent`` connu).
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    shooter_id_str = str(unit["id"])
    shooter_entry = require_unit_from_cache(
        shooter_id_str, game_state, "_unit_has_firable_target"
    )
    shooter_fp = entry_footprint(shooter_entry)
    shooter_player_int = require_present(int(unit["player"]) if unit["player"] is not None else None, "unit['player']")
    melee_range = get_engagement_zone(game_state)
    shoots_as_monster_or_vehicle = is_adjacent and _unit_shoots_as_monster_or_vehicle(game_state, unit)

    for enemy_id, enemy_entry in enemy_entries_on_battlefield(
        units_cache, shooter_player_int, exclude_id=shooter_id_str
    ):
        if not is_unit_alive(str(enemy_id), game_state):
            continue
        enemy = require_unit_by_id(game_state, str(enemy_id))
        enemy_fp = entry_footprint(enemy_entry)
        distance = min_distance_between_sets(shooter_fp, enemy_fp, max_distance=max_range)
        if distance > max_range:
            continue
        enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(shooter_entry, enemy_entry, melee_range, game_state=game_state)
        if is_adjacent and not enemy_adjacent_to_shooter and not shoots_as_monster_or_vehicle:
            # CLOSE_QUARTERS : cibles adjacentes seulement — sauf MONSTER/VEHICLE (10.06, toutes cibles).
            continue
        if _friendly_engagement_blocks_ranged_shot(
            game_state, shooter_id_str, shooter_player_int, enemy_entry, str(enemy_id),
            enemy_adjacent_to_shooter, units_cache,
        ):
            continue
        if _unit_can_see_any(game_state, unit, enemy):
            return True
    return False


def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    Éligibilité au pool de tir (règles 10.04-10.07). L'unité est éligible si, dans son état
    courant (engagée / ayant avancé / normale), elle possède au moins une arme réellement
    tirable ET au moins une cible ennemie à portée de cette arme avec LoS.
    L'Advance n'est PAS une action de la phase de tir : elle se joue en phase de mouvement.
    """
    # CLOSE_QUARTERS rule: Initialize _shooting_with_close_quarters to None for eligibility check
    # This ensures each unit starts with no CLOSE_QUARTERS category restriction
    unit["_shooting_with_close_quarters"] = None

    _uid = str(unit["id"])

    # unit alive? (units_cache is source of truth)
    if not is_unit_alive(_uid, game_state):
        return False
        
    # unit.player === current_player?
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    current_player_int = int(current_player) if current_player is not None else None
    if unit_player != current_player_int:
        return False
        
    # units_fled.includes(unit.id)?
    # Direct field access with validation
    # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
    # Exception: units with shoot_after_flee effect are allowed to shoot after fleeing.
    if "units_fled" not in game_state:
        raise KeyError("game_state missing required 'units_fled' field")
    unit_id_str = str(unit["id"])
    if unit_id_str in game_state["units_fled"] and not _unit_has_rule(unit, "shoot_after_flee"):
        return False

    # STEP 1: ELIGIBILITY CHECK (règles 10.04-10.07, types de tir implémentés uniquement)
    # L'Advance n'est PAS une action de la phase de tir (elle se joue en phase de mouvement) :
    # units_advanced est renseigné en amont et ne sert ici qu'à appliquer la règle Assault (10.05).
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    has_advanced = unit_id_str in game_state.get("units_advanced", set())

    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if is_adjacent and has_advanced:
        # 10.06 exige « Engaged AND **did not make an advance move this turn** », et 10.05 exige
        # d'être unengaged : une unité engagée qui a avancé ne relève d'AUCUN type de tir. Ce
        # chemin l'autorisait pourtant (branche `is_adjacent` testée avant `has_advanced`), à la
        # seule condition d'avoir une arme [CLOSE-QUARTERS] — laxisme trouvé en écrivant le test
        # de parité avec `resolve_squad_shooting_type`, qui rend None dans ce cas.
        firable_weapons = []
    elif is_adjacent:
        # Engagé, sans advance : tir à bout portant (10.06). Deux volets :
        #   - Non-MONSTER/Non-VEHICLE : seules les armes [CLOSE-QUARTERS] tirent ;
        #   - MONSTER/VEHICLE : « you can select any of that model's ranged weapons » — toutes
        #     les armes tirent, avec -1 au jet de touche appliqué à la résolution.
        # Le volet MONSTER/VEHICLE était absent de CE chemin alors qu'il existe côté squad/gym
        # depuis T-B : divergence §1.9, refermée le 2026-07-26.
        if _unit_shoots_as_monster_or_vehicle(game_state, unit):
            firable_weapons = [w for w in rng_weapons if require_key(w, "RNG") > 0]
        else:
            firable_weapons = [w for w in rng_weapons
                               if require_key(w, "RNG") > 0 and weapon_has_rule(w, "CLOSE_QUARTERS")]
    elif has_advanced:
        # Non-engagé et ayant avancé : seules les armes ASSAULT (ou shoot_after_advance) tirent (10.05).
        firable_weapons = [w for w in rng_weapons
                           if require_key(w, "RNG") > 0 and _can_unit_shoot_after_advance_with_weapon(unit, w)]
    else:
        # Non-engagé, sans avance : tir normal avec n'importe quelle arme à distance (10.04).
        firable_weapons = [w for w in rng_weapons if require_key(w, "RNG") > 0]

    if not firable_weapons:
        unit["_can_shoot"] = False
        return False

    # Option debug (défaut = transition rapide). Si le test cible+LoS est désactivé, l'unité est
    # éligible dès qu'elle a une arme tirable ; la présence réelle d'une cible est résolue à
    # l'activation (transition move→shoot rapide, mais cercle vert possible sans cible visible).
    # Le pool exact (test LoS au build) coûte ~1.5s/transition et s'active via le menu debug.
    if not game_state.get("shoot_pool_require_los_target", False):
        unit["_can_shoot"] = True
        return True

    # Pool exact : éligible seulement s'il existe au moins une cible ennemie à portée de l'arme
    # tirable la plus longue, avec LoS (INDIRECT FIRE non implémenté → LoS toujours requise).
    max_firable_range = max(require_key(w, "RNG") for w in firable_weapons)
    can_shoot = _unit_has_firable_target(game_state, unit, is_adjacent, max_firable_range)
    unit["_can_shoot"] = can_shoot
    return can_shoot


def _friendly_engagement_blocks_ranged_shot(
    game_state: Dict[str, Any],
    shooter_id_str: str,
    shooter_player_int: int,
    target_entry: Dict[str, Any],
    target_id_str: str,
    enemy_adjacent_to_shooter: bool,
    units_cache: Dict[str, Any],
) -> bool:
    """
    When the target footprint is not adjacent to the shooter's (enemy_adjacent_to_shooter is False),
    a ranged shot is blocked if the enemy is in melee range of a friendly (same logic as
    _is_valid_shooting_target). Weapon-independent for a fixed (shooter, target) pair.
    """
    if enemy_adjacent_to_shooter:
        return False
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone

    melee_range = get_engagement_zone(game_state)
    for friendly_id, cache_entry in entries_on_battlefield(units_cache, exclude_id=shooter_id_str):
        friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if friendly_player == shooter_player_int:
            if unit_entries_within_engagement_zone(target_entry, cache_entry, melee_range, game_state=game_state):
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    add_debug_file_log(
                        game_state,
                        f"[SHOOT DEBUG] E{episode} T{turn} _is_valid_shooting_target: "
                        f"Shooter {shooter_id_str} blocked - target {target_id_str} engaged with "
                        f"friendly {friendly_id}"
                    )
                return True
    return False


def _is_valid_shooting_target(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    EXACT COPY from w40k_engine_save.py working validation with proper LoS
    PERFORMANCE: Uses LoS cache for instant lookups (0.001ms vs 5-10ms)
    """
    # Range check using min footprint distance (§3.3)
    from engine.hex_utils import min_distance_between_sets
    from engine.utils.weapon_helpers import get_max_ranged_range, get_selected_ranged_weapon
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone

    units_cache = require_key(game_state, "units_cache")
    shooter_id_str = str(shooter["id"])
    target_id_str = str(target["id"])

    if not is_unit_alive(target_id_str, game_state):
        return False

    shooter_entry = require_unit_from_cache(
        shooter_id_str, game_state, "_is_valid_shooting_target/shooter"
    )
    target_entry = require_unit_from_cache(
        target_id_str, game_state, "_is_valid_shooting_target/target"
    )
    shooter_col, shooter_row = int(shooter_entry["col"]), int(shooter_entry["row"])
    target_col, target_row = int(target_entry["col"]), int(target_entry["row"])
    if target_col < 0 or target_row < 0 or shooter_col < 0 or shooter_row < 0:
        return False  # tireur ou cible hors-board (réserves stratégiques)

    shooter_fp = entry_footprint(shooter_entry)
    target_fp = entry_footprint(target_entry)
    max_range = get_max_ranged_range(shooter)
    distance = min_distance_between_sets(shooter_fp, target_fp, max_distance=max_range)
    if distance > max_range:
        return False

    target_player = int(target["player"]) if target["player"] is not None else None
    shooter_player = int(shooter["player"]) if shooter["player"] is not None else None
    if target_player == shooter_player:
        return False

    melee_range = get_engagement_zone(game_state)
    enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(
        shooter_entry, target_entry, melee_range, game_state=game_state
    )
    selected_weapon = get_selected_ranged_weapon(shooter)
    weapon_is_close_quarters = bool(selected_weapon and weapon_has_rule(selected_weapon, "CLOSE_QUARTERS"))
    shooter_is_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, shooter)

    # 10.06 « WHILE SHOOTING », deux volets — MÊME découpe que le chemin par-figurine
    # (`_shoot_engagement_blocks_target`, shared_utils), pour que les deux ne divergent pas :
    #  - Non-MONSTER/Non-VEHICLE : armes [CLOSE-QUARTERS] uniquement, ET cibles limitées aux
    #    unités avec lesquelles l'unité est engagée ;
    #  - MONSTER/VEHICLE : n'importe quelle arme et n'importe quelle cible, SAUF qu'une arme
    #    [BLAST] « still cannot target a unit your unit is engaged with ».
    if shooter_is_engaged:
        if _unit_shoots_as_monster_or_vehicle(game_state, shooter):

            if (
                selected_weapon
                and weapon_has_rule(selected_weapon, "BLAST")
                and enemy_adjacent_to_shooter
            ):
                return False
        else:
            if not weapon_is_close_quarters:
                return False
            if not enemy_adjacent_to_shooter:
                return False
    elif enemy_adjacent_to_shooter and not weapon_is_close_quarters:
        return False

    shooter_player_int = require_present(int(shooter["player"]) if shooter["player"] is not None else None, "shooter['player']")
    if _friendly_engagement_blocks_ranged_shot(
        game_state,
        shooter_id_str,
        shooter_player_int,
        target_entry,
        str(target["id"]),
        enemy_adjacent_to_shooter,
        units_cache,
    ):
        return False

    # PERFORMANCE: Prefer unit-local los_cache (built at activation), then global, then direct calc.
    # Unit-local cache avoids 56-call spike at shooting_phase_start (tour_de_jeu.md per-unit cache).
    target_id_str = str(target["id"])
    has_los = False
    if "los_cache" in shooter and shooter["los_cache"] and target_id_str in shooter["los_cache"]:
        has_los = bool(shooter["los_cache"][target_id_str])
    elif "los_cache" in game_state and game_state["los_cache"]:
        cache_key = (str(shooter["id"]), target_id_str)
        if cache_key in game_state["los_cache"]:
            has_los = game_state["los_cache"][cache_key]
        else:
            has_los = _has_line_of_sight(game_state, shooter, target)
            game_state["los_cache"][cache_key] = has_los
    else:
        has_los = _has_line_of_sight(game_state, shooter, target)
    return has_los


def _clear_shoot_activation_weapon_reuse_cache(unit: Dict[str, Any]) -> None:
    """Invalidate activation-scoped weapon pool / precheck reuse (see shooting_unit_activation_start)."""
    unit.pop("_shoot_activation_reuse_weapon_pool", None)
    unit.pop("_shoot_activation_reuse_ctx", None)
    unit.pop("_shoot_activation_enemy_precheck", None)


def shooting_unit_activation_start(game_state: Dict[str, Any], unit_id: str) -> Dict[str, Any]:
    """
    Start unit activation from shoot_activation_pool
    Clear valid_target_pool, clear TOTAL_ACTION_LOG, SHOOT_LEFT = selected weapon NB
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon NB
    """
    unit = require_unit_by_id(game_state, unit_id)
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        unit_id_str = str(unit_id)
        add_debug_file_log(
            game_state,
            f"[SHOOT_ACTIVATION_START] E{episode} T{turn} Unit {unit_id_str}"
        )
    unit["_shoot_activation_started"] = True

    # CRITICAL FIX (Episodes 49, 57, 94, 95, 99): Verify unit is in pool before activation
    # A unit that was removed from pool (e.g., after WAIT) should NEVER be reactivated
    # This prevents infinite WAIT loops where get_action_mask reactivates a unit that was removed
    # CRITICAL: Normalize all IDs to string for consistent comparison (pool stores strings)
    shoot_pool = require_key(game_state, "shoot_activation_pool")
    unit_id_str = str(unit_id)
    pool_ids = [str(uid) for uid in shoot_pool]
    if unit_id_str not in pool_ids:
        # Unit not in pool - cannot activate
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        from engine.game_utils import add_debug_log
        add_debug_log(game_state, f"[ACTIVATION_START ERROR] E{episode} T{turn} shooting_unit_activation_start: Unit {unit_id_str} NOT in pool, cannot activate. Pool={shoot_pool}")
        return {"error": "unit_not_in_pool", "unitId": unit_id, "message": "Unit was removed from pool and cannot be reactivated"}

    from engine.perf_timing import perf_timing_enabled

    _perf_act = perf_timing_enabled(game_state)
    _t_act0 = time.perf_counter() if _perf_act else None
    _t_after_los: Optional[float] = None
    _t_ep0: Optional[float] = None
    _t_ep1: Optional[float] = None
    _t_wai0: Optional[float] = None
    _t_wai1: Optional[float] = None
    _t_after_tgt_pool: Optional[float] = None

    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)

    # STEP 2: UNIT_ACTIVABLE_CHECK
    # Clear valid_target_pool, Clear TOTAL_ATTACK log
    unit["valid_target_pool"] = []
    unit["TOTAL_ATTACK_LOG"] = ""
    
    # CRITICAL: Clear shoot_attack_results at the start of each new unit activation
    # This ensures attacks from different units are not mixed together
    game_state["shoot_attack_results"] = []
    
    # tour_de_jeu.md STEP 2: Build unit's los_cache at activation
    # Build los_cache for units that can shoot (including shoot_after_flee exception).
    unit_id_str = str(unit_id)
    _t_los0 = time.perf_counter() if _perf_act else None
    if unit_id_str not in require_key(game_state, "units_fled") or _unit_has_rule(unit, "shoot_after_flee"):
        build_unit_los_cache(game_state, unit_id)
    else:
        # Unit has fled - cannot shoot, so no los_cache needed
        # Unit can still advance if not adjacent to enemy
        unit["los_cache"] = {}
    if _perf_act and _t_los0 is not None:
        _t_after_los = time.perf_counter()
    
    # Determine adjacency
    unit_is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)

    # CLOSE_QUARTERS rule: Reset _shooting_with_close_quarters for this activation (no category restriction yet)
    # This must be done BEFORE weapon_availability_check to avoid incorrect filtering
    unit["_shooting_with_close_quarters"] = None
    # [RAPID FIRE] 24.30 ne porte AUCUN etat d activation : le bonus est ajoute a la
    # constitution du pool d attaques (`_manual_roll_intent`), a partir de l arme et de la
    # demi-portee. Les 7 champs `_rapid_fire_*` qui vivaient ici etaient morts (V11 §0.38).

    # Reset weapon.shot flags for this unit at activation start
    # Each unit should be able to use all its weapons at the start of its activation
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    for weapon in rng_weapons:
        weapon["shot"] = 0
    # Reset COMBI_WEAPON choice for this activation
    unit["_combi_weapon_choice"] = {}
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        unit_id_str = str(unit["id"])
        shot_flags = [weapon.get("shot") for weapon in rng_weapons]
        add_debug_file_log(
            game_state,
            f"[SHOT RESET] E{episode} T{turn} Unit {unit_id_str} weapon_shot_flags={shot_flags}"
        )
    
    # Short-circuit: aucun ennemi avec LOS → target pool sera vide, skip weapon_avail + pool build
    if not any(unit["los_cache"].values()):
        unit["valid_target_pool"] = []
        game_state["active_shooting_unit"] = unit_id
        # Aucune cible : rien à faire en tir (l'advance se joue en phase de mouvement) → skip.
        _success, result = _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip", skip_reason="no_valid_actions")
        result["skip_reason"] = "no_valid_actions"
        _emit_shoot_activation_perf(game_state, str(unit_id), _t_act0, _t_after_los, None, None, None, None, None, "empty_pool_skip", 0)
        return result

    # weapon_availability_check(advance_status, unit_is_adjacent ? 1 : 0) -> Build weapon_available_pool
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    advance_status = 1 if unit_id_str in game_state.get("units_advanced", set()) else 0
    adjacent_status = 1 if unit_is_adjacent else 0
    _t_ep0 = time.perf_counter() if _perf_act else None
    _activation_enemy_precheck = _build_weapon_availability_enemy_precheck(
        game_state, unit, require_key(unit, "RNG_WEAPONS")
    )
    if _perf_act and _t_ep0 is not None:
        _t_ep1 = time.perf_counter()
    _t_wai0 = time.perf_counter() if _perf_act else None
    weapon_available_pool = weapon_availability_check(
        game_state,
        unit,
        weapon_rule,
        advance_status,
        adjacent_status,
        _precheck=_activation_enemy_precheck,
    )
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    if _perf_act and _t_wai0 is not None:
        _t_wai1 = time.perf_counter()
    
    # CRITICAL: Use shooting_build_valid_target_pool for consistent pool building
    # This wrapper automatically determines context (advance_status, adjacent_status) and handles cache
    _t_pool0 = time.perf_counter() if _perf_act else None
    valid_target_pool = shooting_build_valid_target_pool(
        game_state,
        unit_id,
        precomputed_weapon_available_pool=weapon_available_pool,
        precomputed_enemy_precheck=_activation_enemy_precheck,
    )
    if _perf_act and _t_pool0 is not None:
        _t_after_tgt_pool = time.perf_counter()
    
    # valid_target_pool NOT empty?
    if len(valid_target_pool) == 0:
        # STEP 6: EMPTY_TARGET_HANDLING
        game_state["active_shooting_unit"] = unit_id
        # Aucune cible : rien à faire en tir (l'advance se joue en phase de mouvement) → skip.
        _success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip", skip_reason="no_valid_actions"
        )
        result["skip_reason"] = "no_valid_actions"
        _emit_shoot_activation_perf(
            game_state,
            str(unit_id),
            _t_act0,
            _t_after_los,
            _t_ep0,
            _t_ep1,
            _t_wai0,
            _t_wai1,
            _t_after_tgt_pool,
            "empty_pool_skip",
            0,
        )
        return result
    # YES -> SHOOTING ACTIONS AVAILABLE -> Go to STEP 3: ACTION_SELECTION
    unit["valid_target_pool"] = valid_target_pool
    
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        shoot_left = unit.get("SHOOT_LEFT")
        add_debug_file_log(
            game_state,
            f"[SHOOT DEBUG] E{episode} T{turn} shooting_unit_activation_start: "
            f"Unit {unit_id_str} SHOOT_LEFT={shoot_left} valid_targets={valid_target_pool}"
        )
    
    # tour_de_jeu.md STEP 3: Pre-select first available weapon
    # If unit is adjacent to enemy, prioritize CLOSE_QUARTERS weapons
    if not usable_weapons:
        # No usable weapons under current rules -> no valid actions (l'advance se joue en phase de mouvement) → skip.
        _success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip", skip_reason="no_usable_weapons"
        )
        result["skip_reason"] = "no_usable_weapons"
        _emit_shoot_activation_perf(
            game_state,
            str(unit_id),
            _t_act0,
            _t_after_los,
            _t_ep0,
            _t_ep1,
            _t_wai0,
            _t_wai1,
            _t_after_tgt_pool,
            "no_usable_skip",
            len(valid_target_pool),
        )
        return result
    if usable_weapons:
        if unit_is_adjacent:
            # Prioritize CLOSE_QUARTERS weapons when adjacent to enemy
            close_quarters_weapons = []
            non_close_quarters_weapons = []
            for w in usable_weapons:
                weapon = require_key(w, "weapon")
                if weapon_has_rule(weapon, "CLOSE_QUARTERS"):
                    close_quarters_weapons.append(w)
                else:
                    non_close_quarters_weapons.append(w)
            
            # Prefer CLOSE_QUARTERS weapons, but fall back to non-CLOSE_QUARTERS if no CLOSE_QUARTERS available
            if close_quarters_weapons:
                first_weapon = close_quarters_weapons[0]
            else:
                first_weapon = usable_weapons[0]
        else:
            # Not adjacent, use first available weapon
            first_weapon = usable_weapons[0]
        
        first_weapon_idx = first_weapon["index"]
        unit["selectedRngWeaponIndex"] = first_weapon_idx
        selected_weapon = unit["RNG_WEAPONS"][first_weapon_idx]
        nb_roll = resolve_dice_value(require_key(selected_weapon, "NB"), "shooting_nb_init")
        unit["SHOOT_LEFT"] = nb_roll
        unit["_current_shoot_nb"] = nb_roll
        _append_shoot_nb_roll_info_log(game_state, unit, selected_weapon, nb_roll)
    else:
        unit["SHOOT_LEFT"] = 0
        unit["_current_shoot_nb"] = unit["SHOOT_LEFT"]
    
    unit["selected_target_id"] = None  # For two-click confirmation

    # Capture unit's current location for shooting phase tracking
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit["activation_position"] = {"col": unit_col, "row": unit_row}

    # Mark unit as currently active
    game_state["active_shooting_unit"] = unit_id

    # Serialize available weapons for frontend (weapon_available_pool already contains serialized weapons)
    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in weapon_available_pool]

    unit_col, unit_row = require_unit_position(unit, game_state)
    # Réutilisation immédiate dans _shooting_unit_execution_loop (menu joueur) : évite un second
    # weapon_availability_check identique à celui ci-dessus pour le même (advance, adjacent).
    unit["_shoot_activation_reuse_weapon_pool"] = weapon_available_pool
    unit["_shoot_activation_reuse_ctx"] = (advance_status, adjacent_status)
    unit["_shoot_activation_enemy_precheck"] = _activation_enemy_precheck
    _emit_shoot_activation_perf(
        game_state,
        str(unit_id),
        _t_act0,
        _t_after_los,
        _t_ep0,
        _t_ep1,
        _t_wai0,
        _t_wai1,
        _t_after_tgt_pool,
        "success",
        len(valid_target_pool),
    )
    return {"success": True, "unitId": unit_id, "shootLeft": unit["SHOOT_LEFT"],
            "position": {"col": unit_col, "row": unit_row},
            "selectedRngWeaponIndex": unit["selectedRngWeaponIndex"] if "selectedRngWeaponIndex" in unit else 0,
            "available_weapons": available_weapons}


def valid_target_pool_build(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon_rule: int,
    advance_status: int,
    adjacent_status: int,
    precomputed_weapon_available_pool: Optional[List[Dict[str, Any]]] = None,
    precomputed_enemy_precheck: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    shoot_refactor.md EXACT: Build list of valid enemy targets
    
    Args:
        game_state: Game state dictionary
        unit: Unit dictionary
        weapon_rule: 0 = no rules, 1 = rules apply
        advance_status: 0 = no advance, 1 = advanced
        adjacent_status: 0 = not adjacent, 1 = adjacent to enemy
        precomputed_weapon_available_pool: si fourni (même contexte arg1–arg3), évite un second
            ``weapon_availability_check`` (ex. activation après ``shooting_unit_activation_start``).
        precomputed_enemy_precheck: même liste que ``_build_weapon_availability_enemy_precheck`` pour
            réutiliser distance + ``friendly_blocks`` + drapeaux LoS (évite BFS / boucle alliés
            redondants pour les cibles couvertes). Les cibles avec LoS mais hors portée max du
            précheck sont encore traitées via ``ranged_edge_distance`` (sélecteur de métrique) borné
            par la portée max des armes **utilisables** (cohérent avec le test de portée).
    
    Returns:
        List of enemy unit IDs that can be targeted (valid_target_pool)
    """
    current_player = unit["player"]

    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    from engine.hex_utils import Socle
    _ranged_metric_pool = _ranged_distance_metric(game_state)

    # Perform weapon_availability_check(arg1, arg2, arg3) -> Build weapon_available_pool
    if precomputed_weapon_available_pool is not None:
        weapon_available_pool = precomputed_weapon_available_pool
    else:
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
    
    # Get usable weapons (can_use = True)
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    
    if not usable_weapons:
        return []
    
    # Extract usable weapon indices and ranges
    usable_weapon_indices = [w["index"] for w in usable_weapons]
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    
    # For each enemy unit
    valid_target_pool = []
    
    # CRITICAL: Normalize unit ID once at the start for consistent comparison
    # This prevents bugs where unit["id"] might be int or string, and enemy["id"] might be different type
    unit_id_normalized = str(unit["id"])
    current_player_int = int(current_player) if current_player is not None else None
    
    # DEBUG: Log pool building start (debug.log only, when --debug)
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log
    unit_col, unit_row = require_unit_position(unit_id_normalized, game_state)
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        add_debug_file_log(
            game_state,
            f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
            f"Unit {unit_id_normalized}({unit_col},{unit_row}) building pool "
            f"(advance_status={advance_status}, adjacent_status={adjacent_status})"
        )
    
    # tour_de_jeu.md: ASSERT unit["los_cache"] exists (must be created by build_unit_los_cache at activation)
    if "los_cache" not in unit:
        # Check if unit has fled (fled units without shoot_after_flee can still advance, but cannot shoot)
        unit_id_str = str(unit["id"])
        if unit_id_str not in require_key(game_state, "units_fled") or _unit_has_rule(unit, "shoot_after_flee"):
            raise KeyError(f"Unit {unit_id_normalized} missing required 'los_cache' field. Must call build_unit_los_cache() at activation.")
        else:
            # Unit has fled - cannot shoot, return empty pool
            return []
    
    # tour_de_jeu.md: Filter los_cache to get only targets with LoS (optimization)
    # Filter los_cache: targets_with_los = {target_id: true for target_id, has_los in unit["los_cache"].items() if has_los == true}
    targets_with_los = {
        target_id: True 
        for target_id, has_los in unit["los_cache"].items() 
        if has_los == True
    }
    
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        add_debug_file_log(
            game_state,
            f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
            f"Found {len(targets_with_los)} targets with LoS out of {len(unit['los_cache'])} total targets"
        )

    precheck_by_id: Optional[Dict[str, Dict[str, Any]]] = None
    if precomputed_enemy_precheck is not None:
        precheck_by_id = {
            r["enemy_id_str"]: r
            for r in precomputed_enemy_precheck
            if isinstance(r.get("enemy_id_str"), str)
        }

    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone

    melee_range = get_engagement_zone(game_state)
    max_usable_rng = 0
    for widx in usable_weapon_indices:
        if widx < len(rng_weapons):
            rw = require_key(rng_weapons[widx], "RNG")
            if rw > max_usable_rng:
                max_usable_rng = rw
    
    # Hidden targets (rule 13.09) are only visible to shooters within detection range (15").
    detection_range_subhex = (
        float(require_key(require_key(require_key(game_state, "config"), "game_rules"), "detection_range"))
        * int(require_key(game_state, "inches_to_subhex"))
    )

    # For each target_id in targets_with_los.keys():
    units_cache = require_key(game_state, "units_cache")
    unit_col, unit_row = require_unit_position(unit, game_state)
    import os as _os_losdbg
    if _os_losdbg.environ.get("W40K_LOS_DEBUG"):
        print(
            f"[LOS_DEBUG] valid_target_pool_build shooter={unit_id_normalized} "
            f"pos=({unit_col},{unit_row}) metric={_ranged_metric_pool} "
            f"adv={advance_status} adj={adjacent_status} max_usable_rng={max_usable_rng} "
            f"los_true={sorted(targets_with_los.keys())} "
            f"los_cache_size={len(unit.get('los_cache', {}))}",  # get allowed
            flush=True,
        )
    # DIAG: log every alive enemy that is FILTERED OUT before the pool loop because it lacks LoS.
    # valid_target_pool_build ne parcourt que targets_with_los : une cible sans LoS (los_cache False
    # ou absente) est écartée silencieusement. Ce log rend cette exclusion explicite (raison = LoS).
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        _los_map_diag = unit.get("los_cache") or {}
        for _enemy_id, _entry in enemy_entries_on_battlefield(units_cache, current_player_int):
            _eid = str(_enemy_id)
            if not is_unit_alive(_eid, game_state):
                continue
            if _eid in targets_with_los:
                continue
            _los_val = _los_map_diag[_eid] if _eid in _los_map_diag else "ABSENT"
            add_debug_file_log(
                game_state,
                f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                f"Enemy {_eid}({_entry.get('col','?')},{_entry.get('row','?')}) "
                f"EXCLUDED - no LoS (los_cache={_los_val})"
            )
    for target_id_str in targets_with_los.keys():
        # Get enemy unit by ID
        enemy = _get_unit_by_id(game_state, target_id_str)
        if not enemy:
            # Target not found (may have died) - skip
            continue
        # DEBUG: Log all enemies being checked (position from cache)
        enemy_id_check = str(enemy.get("id", "?"))
        enemy_pos = get_unit_position(enemy, game_state)
        enemy_pos_check = enemy_pos if enemy_pos is not None else ("?", "?")
        enemy_hp_check = get_hp_from_cache(str(enemy["id"]), game_state)  # Phase 2: from cache
        enemy_player_check = enemy.get("player", "?")
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            add_debug_file_log(
                game_state,
                f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                f"Checking Enemy {enemy_id_check}({enemy_pos_check[0]},{enemy_pos_check[1]}) "
                f"HP={enemy_hp_check} player={enemy_player_check}"
            )
        
        # unit alive? (units_cache is source of truth) -> NO -> Skip enemy unit
        if not is_unit_alive(str(enemy["id"]), game_state):
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                add_debug_file_log(
                    game_state,
                    f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                    f"Enemy {enemy_id_check} EXCLUDED - not alive (units_cache)"
                )
            continue
        
        # CRITICAL: Normalize enemy ID for consistent comparison
        # This ensures we catch self-targeting even if IDs are different types (int vs string)
        enemy_id_normalized = str(enemy["id"])
        
        # CRITICAL: Skip the shooter unit itself (cannot shoot self)
        # Use normalized IDs to ensure we catch all cases regardless of type mismatch
        if enemy_id_normalized == unit_id_normalized:
            # Log this as a critical bug if it somehow happens
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log, add_debug_log
                log_msg = f"[SHOOT CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Unit {unit_id_normalized} attempted to add itself (enemy_id={enemy_id_normalized}, unit['id']={unit['id']}, enemy['id']={enemy['id']}) to valid_target_pool - BLOCKED"
                add_console_log(game_state, log_msg)
            continue
        
        # unit.player != current_player? -> NO -> Skip enemy unit
        # CRITICAL: Convert to int for consistent comparison (player can be int or string)
        enemy_player = int(enemy["player"]) if enemy["player"] is not None else None
        if enemy_player == current_player_int:
            # Log this as a bug if it somehow happens
            if "episode_number" in game_state and "turn" in game_state:
                episode = game_state.get("episode_number", "?")
                turn = game_state.get("turn", "?")
                from engine.game_utils import add_console_log, add_debug_log
                log_msg = f"[SHOOT CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Unit {unit_id_normalized} (player={current_player_int}) attempted to add friendly unit {enemy_id_normalized} (player={enemy_player}) to valid_target_pool - BLOCKED"
                add_console_log(game_state, log_msg)
            continue
        
        enemy_entry = units_cache.get(target_id_str)
        if enemy_entry is None:
            raise KeyError(f"Enemy {target_id_str} not in units_cache (dead or absent)")

        unit_entry = units_cache.get(unit_id_normalized)
        if unit_entry is None:
            raise KeyError(f"Shooter {unit_id_normalized} not in units_cache")
        shooter_fp = entry_footprint(unit_entry)
        enemy_fp = entry_footprint(enemy_entry)

        row_opt = precheck_by_id.get(target_id_str) if precheck_by_id else None
        if row_opt is not None:
            distance_to_enemy = float(row_opt["distance"])  # euclidien = float : ne pas tronquer
            enemy_adjacent_to_shooter = bool(row_opt["enemy_engaged_with_shooter"])
            if not enemy_adjacent_to_shooter and bool(row_opt.get("friendly_blocks")):
                continue
        else:
            # Pas de ligne précheck (ex. cible avec LoS mais hors max RNG du précheck, ou appel sans précheck).
            # Distance tireur/cible §3.3 : borner la recherche par la portée max des armes utilisables,
            # pas par melee_range seul — sinon la distance renvoyée peut être tronquée et fausser le test de portée.
            _md_cap = max_usable_rng if max_usable_rng > 0 else 0
            _shooter_socle_pool = socle_from_cache_entry(unit_entry)
            distance_to_enemy = ranged_edge_distance(
                _shooter_socle_pool, socle_from_cache_entry(enemy_entry), _ranged_metric_pool, max_distance=_md_cap
            )
            enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(
                unit_entry, enemy_entry, melee_range, game_state=game_state
            )

        shooter_is_engaged = adjacent_status == 1
        has_close_quarters_weapon = False
        # 10.06 volet MONSTER/VEHICLE : « you can select any of that model's ranged weapons » —
        # l'absence d'arme [CLOSE-QUARTERS] n'exclut donc PAS la cible engagee, et l'unite n'est
        # pas limitee aux seules cibles avec lesquelles elle est engagee. (Divergence §1.9 :
        # ce volet existait cote squad/gym depuis T-B, pas ici.)
        shooter_is_mv = _unit_shoots_as_monster_or_vehicle(game_state, unit)

        if enemy_adjacent_to_shooter and not shooter_is_mv:
            # Enemy is adjacent to shooter - check if any weapon has CLOSE_QUARTERS rule
            for weapon_idx in usable_weapon_indices:
                if weapon_idx < len(rng_weapons):
                    weapon = rng_weapons[weapon_idx]
                    if weapon_has_rule(weapon, "CLOSE_QUARTERS"):
                        has_close_quarters_weapon = True
                        break
            
            # If no CLOSE_QUARTERS weapon available, cannot shoot at adjacent enemy
            if not has_close_quarters_weapon:
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    _ep = enemy.get("col", "?")
                    _er = enemy.get("row", "?")
                    add_debug_file_log(
                        game_state,
                        f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized}({_ep},{_er}) EXCLUDED - adjacent without CLOSE_QUARTERS weapon"
                    )
                continue
        
        # Engaged shooter can only target adjacent enemies (10.06, volet non-MONSTER/VEHICLE).
        if shooter_is_engaged and not enemy_adjacent_to_shooter and not shooter_is_mv:
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                _ep = enemy.get("col", "?")
                _er = enemy.get("row", "?")
                add_debug_file_log(
                    game_state,
                    f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                    f"Enemy {enemy_id_normalized}({_ep},{_er}) EXCLUDED - shooter engaged, non-adjacent target"
                )
            continue

        # Unit NOT adjacent to friendly unit (excluding active unit)? -> NO -> Skip enemy unit
        # CRITICAL: This rule applies ONLY when enemy is NOT adjacent to shooter
        # If enemy is adjacent to shooter AND we have CLOSE_QUARTERS weapon, we can shoot regardless of engagement
        # If enemy is NOT adjacent to shooter, normal rules apply: cannot shoot if enemy is engaged with friendly units
        if not enemy_adjacent_to_shooter and row_opt is None:
            enemy_adjacent_to_friendly = False
            engaged_friendly_id = None
            for friendly_id, cache_entry in entries_on_battlefield(
                units_cache, exclude_id=unit_id_normalized
            ):
                friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
                if friendly_player == current_player_int:
                    if unit_entries_within_engagement_zone(enemy_entry, cache_entry, melee_range, game_state=game_state):
                        enemy_adjacent_to_friendly = True
                        engaged_friendly_id = friendly_id
                        break
            
            if enemy_adjacent_to_friendly:
                _ep = enemy.get("col", "?")
                _er = enemy.get("row", "?")
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    add_debug_file_log(
                        game_state,
                        f"[SHOOT DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized}({_ep},{_er}) engaged with friendly "
                        f"{engaged_friendly_id}"
                    )
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    add_debug_file_log(
                        game_state,
                        f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized}({_ep},{_er}) EXCLUDED - engaged with friendly unit"
                    )
                continue
        
        # tour_de_jeu.md: LoS check already done in build_unit_los_cache()
        # We filtered los_cache above to only include targets with has_los == True
        # So we can skip LoS check here (performance optimization)
        
        # Unit within range of AT LEAST 1 weapon from weapon_available_pool? -> NO -> Skip enemy unit
        # CRITICAL: Reuse distance already calculated above (distance_to_enemy)
        unit_within_range = False
        distance = distance_to_enemy
        
        for weapon_idx in usable_weapon_indices:
            if weapon_idx < len(rng_weapons):
                weapon = rng_weapons[weapon_idx]
                weapon_range = require_key(weapon, "RNG")
                if distance <= weapon_range:
                    unit_within_range = True
                    break

        if _os_losdbg.environ.get("W40K_LOS_DEBUG"):
            print(
                f"[LOS_DEBUG]   enemy={enemy_id_normalized} dist={round(float(distance), 2)} "
                f"in_range={unit_within_range} adj={enemy_adjacent_to_shooter} "
                f"from_precheck={row_opt is not None}",
                flush=True,
            )

        # ALL conditions met -> ✅ Add unit to valid_target_pool
        # CRITICAL: Convert ID to string for consistent comparison (target_id is passed as str)
        # Note: Friendly units are already filtered out at line 949-960 above
        if unit_within_range:
            # Rule 13.09: a hidden enemy can only be targeted by a shooter within detection range.
            # Rule 13.5 (Gone to Ground): detection −3" par figurine non entièrement visible à cause
            # d'un terrain Solid intervenant (évalué per-figurine dans hidden_enemy_out_of_detection).
            if bool(enemy.get("hidden")) and hidden_enemy_out_of_detection(
                game_state, unit, enemy, detection_range_subhex
            ):
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    add_debug_file_log(
                        game_state,
                        f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized} EXCLUDED - hidden beyond detection range "
                        f"(distance={distance}, detection={detection_range_subhex})"
                    )
                continue
            # CRITICAL: Double-check friendly status before adding (defense in depth)
            # This should never happen if line 1030 is correct, but adds safety
            if enemy_player == current_player_int:
                add_console_log(game_state, f"[CRITICAL BUG] E{episode} T{turn} valid_target_pool_build: Attempted to ADD friendly unit {enemy_id_normalized} (player={enemy_player}) to pool for Unit {unit_id_normalized} (player={current_player_int}) - BLOCKED")
                continue  # Skip friendly units
            valid_target_pool.append(str(enemy["id"]))
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                _ep = enemy.get("col", "?")
                _er = enemy.get("row", "?")
                add_debug_file_log(
                    game_state,
                    f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                    f"Enemy {enemy_id_normalized}({_ep},{_er}) ADDED to pool "
                    f"(distance={distance}, shooter_player={current_player_int}, target_player={enemy_player})"
                )
        else:
            max_rng = max((require_key(w, "RNG") for w in rng_weapons), default=0)
            if game_state.get("debug_mode", False):
                from engine.game_utils import add_debug_file_log
                _ep = enemy.get("col", "?")
                _er = enemy.get("row", "?")
                add_debug_file_log(
                    game_state,
                    f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                    f"Enemy {enemy_id_normalized}({_ep},{_er}) EXCLUDED - out of range "
                    f"(distance={distance}, max_range={max_rng})"
                )
    
    return valid_target_pool


def shooting_build_valid_target_pool(
    game_state: Dict[str, Any],
    unit_id: str,
    *,
    precomputed_weapon_available_pool: Optional[List[Dict[str, Any]]] = None,
    precomputed_enemy_precheck: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    Build valid_target_pool and always send blinking data to frontend.
    All enemies within range AND in Line of Sight AND alive (in units_cache)

    PERFORMANCE: Caches target pool per (unit_id, col, row) to avoid repeated
    distance/LoS calculations during a unit's shooting activation.
    Cache invalidates automatically when unit changes or moves.
    
    precomputed_weapon_available_pool: résultat déjà calculé de ``weapon_availability_check`` pour le
    même (weapon_rule, advance_status, adjacent_status) que ce wrapper déduit — évite un double
    appel coûteux sur le chemin activation.
    precomputed_enemy_precheck: même passe ennemis que pour ``weapon_availability_check`` (activation).
    
    NOTE: This function is a wrapper that determines context and calls valid_target_pool_build.
    For direct calls, use valid_target_pool_build() with explicit parameters.
    
    Determines context (arg2, arg3) based on unit state:
    - arg2 = (unit.id in units_advanced) ? 1 : 0
    - arg3 = (unit adjacent to enemy?) ? 1 : 0
    """
    global _target_pool_cache

    unit = require_unit_by_id(game_state, unit_id)
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]

    # Determine context for valid_target_pool_build
    # arg2 = (unit.id in units_advanced) ? 1 : 0
    unit_id_str = str(unit_id)
    has_advanced = unit_id_str in require_key(game_state, "units_advanced")
    advance_status = 1 if has_advanced else 0
    
    # arg3 = (unit adjacent to enemy?) ? 1 : 0
    # After advance, arg3 is ALWAYS 0 (advance restrictions prevent adjacent destinations)
    if has_advanced:
        adjacent_status = 0  # arg3=0 always after advance
    else:
        adjacent_status = 1 if _is_adjacent_to_enemy_within_cc_range(game_state, unit) else 0

    # Create cache key from unit identity, position, player, AND context (advance_status, adjacent_status)
    # Cache must include context to avoid wrong results after advance
    # CRITICAL: Include unit["player"] to ensure cache is invalidated when player changes
    # CRITICAL: Include os.getpid() to avoid cross-worker pollution (SubprocVecEnv fork copies cache, id() can collide)
    # CRITICAL: Use _cache_instance_id (engine id) to avoid cross-env pollution - id(game_state) can
    # be reused after GC when multiple envs run in same process (bot eval), causing wrong pool reuse
    gs_instance_id = game_state.get("_cache_instance_id", id(game_state))
    # CRITICAL: Include episode_number to avoid cross-episode pollution (target positions differ between episodes)
    # CRITICAL: Include turn - targets can MOVE between turns; pool built in turn 1 is stale in turn 2+
    # CRITICAL: Include hash of enemy positions - targets can move between activations (reactive, etc.)
    # Pool built when target at (5,5) is stale when target moved to (12,9)
    # CRITICAL: Include wall_hexes (topology) so pool from one scenario/board is never reused for another.
    # Multiple envs in same process (e.g. bot_eval) can have same (pid, id, ep, turn, positions); only topology differs.
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_id_str = str(unit_id)
    unit_player = require_key(unit, "player")
    try:
        unit_player_int = int(unit_player)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid unit player value: {unit_player}") from exc
    unit["player"] = unit_player_int
    episode_num = require_key(game_state, "episode_number")
    turn_num = require_key(game_state, "turn")
    # wall_hexes_tuple: walls never change — compute once per game_state instance
    if "_wall_hexes_tuple_cache" not in game_state:
        _raw_walls = require_key(game_state, "wall_hexes")
        if not isinstance(_raw_walls, (list, set, tuple)):
            raise TypeError(f"wall_hexes must be list/set/tuple (got {type(_raw_walls).__name__})")
        _norm: List[Tuple[int, int]] = []
        for _raw_wall in _raw_walls:
            if not isinstance(_raw_wall, (list, tuple)) or len(_raw_wall) != 2:
                raise ValueError(f"Invalid wall hex format in game_state.wall_hexes: {_raw_wall!r}")
            _wc, _wr = normalize_coordinates(_raw_wall[0], _raw_wall[1])
            _norm.append((_wc, _wr))
        game_state["_wall_hexes_tuple_cache"] = tuple(sorted(_norm))
    wall_hexes_tuple = game_state["_wall_hexes_tuple_cache"]
    # §04.02 : le pool capture l'état d'engagement — invalider dès que TOUTE unité bouge
    # (allié ou ennemi). enemy_pos_hash ne trackait que les ennemis : un allié qui pile-in
    # adjacent à une cible après le premier build laissait la cible dans le pool stale.
    _move_ver = game_state["_unit_move_version"]
    precheck_cache_tag = 1 if precomputed_enemy_precheck is not None else 0
    cache_key = (
        os.getpid(),
        gs_instance_id,
        episode_num,
        turn_num,
        unit_id_str,
        unit_col,
        unit_row,
        advance_status,
        adjacent_status,
        unit_player_int,
        _move_ver,
        wall_hexes_tuple,
        precheck_cache_tag,
    )

    # Check cache
    if cache_key in _target_pool_cache:
        # Cache hit: Fast path - filter dead targets only
        cached_pool = _target_pool_cache[cache_key]

        # Filter out units that died, friendly, or lost LoS
        alive_targets = []
        from engine.game_utils import add_console_log
        for target_id_str in cached_pool:  # Iterate over string IDs
            if not is_unit_alive(target_id_str, game_state):
                continue
            target = require_unit_by_id(game_state, target_id_str)
            target_player = int(target["player"]) if target["player"] is not None else None
            if target_player == unit_player_int:
                add_console_log(game_state, f"[BUG] Cache contained friendly unit {target_id_str} (player {target['player']}) for shooter {unit_id} (player {unit_player_int})")
                continue  # Skip friendly units
            # Guard : filtre les unités mortes ou devenues alliées depuis la mise en cache
            alive_targets.append(target_id_str)  # Ensure ID is string

        # Update unit's target pool
        unit["valid_target_pool"] = alive_targets
        unit["_pool_from_cache"] = True
        unit["_pool_cache_key"] = str(cache_key)

        return alive_targets

    # Cache miss: Build target pool from scratch using valid_target_pool_build
    # Use context already determined above (lines 881-892)
    # Do NOT recalculate - use advance_status and adjacent_status already computed
    # which correctly implement "arg3=0 always after advance" rule
    # CRITICAL: Ensure los_cache exists and is up-to-date before calling valid_target_pool_build
    # This can happen if shooting_build_valid_target_pool is called before shooting_unit_activation_start
    # OR if unit has advanced since los_cache was built
    unit_id_str = str(unit_id)
    has_advanced = unit_id_str in require_key(game_state, "units_advanced")
    
    # Check if los_cache needs to be rebuilt (missing or unit has advanced)
    if "los_cache" not in unit or has_advanced:
        # UNITS_CACHE: units_cache must exist (built at reset, not phase start)
        if "units_cache" not in game_state:
            raise KeyError("units_cache must exist before valid target pool (built at reset)")
        
        # Build los_cache for unit (rebuild if unit has advanced)
        if unit_id_str not in require_key(game_state, "units_fled") or _unit_has_rule(unit, "shoot_after_flee"):
            build_unit_los_cache(game_state, unit_id)
        else:
            # Unit has fled - cannot shoot, so no los_cache needed
            unit["los_cache"] = {}

    # Call valid_target_pool_build with context parameters
    # Use advance_status and adjacent_status already calculated above (lines 885, 890-892)
    valid_target_pool = valid_target_pool_build(
        game_state,
        unit,
        weapon_rule,
        advance_status,
        adjacent_status,
        precomputed_weapon_available_pool=precomputed_weapon_available_pool,
        precomputed_enemy_precheck=precomputed_enemy_precheck,
    )

    # PERFORMANCE: Pre-calculate priorities for all targets ONCE before sorting
    # This reduces from O(n log n) priority calculations to O(n) calculations
    # Priority: tactical efficiency > type match > distance

    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from all ranged weapons
    from engine.utils.weapon_helpers import get_max_ranged_range
    max_range = get_max_ranged_range(unit)
    
    # Pre-validate unit stats ONCE (not inside loop)
    if "T" not in unit:
        raise KeyError(f"Unit missing required 'T' field: {unit}")
    if "ARMOR_SAVE" not in unit:
        raise KeyError(f"Unit missing required 'ARMOR_SAVE' field: {unit}")
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing required 'RNG_WEAPONS' field: {unit}")
    if "unitType" not in unit:
        raise KeyError(f"Unit missing required 'unitType' field: {unit}")

    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if not rng_weapons:
        # No ranged weapons: return pool without priority scoring
        return valid_target_pool

    # Cache unit stats for priority calculations
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or first weapon for priority
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    selected_weapon = get_selected_ranged_weapon(unit)
    if not selected_weapon:
        raise ValueError(f"Selected ranged weapon is required for shooting priority calculation: unit_id={unit.get('id')}")
    
    unit_t = unit["T"]
    unit_save = unit["ARMOR_SAVE"]
    unit_attacks = (
        expected_dice_value(require_key(selected_weapon, "NB"), "shoot_priority_unit_nb")
        if selected_weapon else 0
    )
    unit_bs = selected_weapon["ATK"] if selected_weapon else 0
    unit_s = selected_weapon["STR"] if selected_weapon else 0
    unit_ap = selected_weapon["AP"] if selected_weapon else 0
    unit_type = unit["unitType"]

    # Determine preferred target type from unit name (ONCE)
    if "Swarm" in unit_type:
        preferred = "swarm"
    elif "Troop" in unit_type:
        preferred = "troop"
    elif "Elite" in unit_type:
        preferred = "elite"
    else:
        preferred = "troop"  # Default

    # Calculate our hit probability (ONCE - unit stats don't change per target)
    our_hit_prob = (7 - unit_bs) / 6.0

    # Pre-calculate priorities for all targets
    target_priorities = []  # [(target_id, priority_tuple)]
    
    # CRITICAL: Filter out self and friendly units before priority calculation
    # This prevents friendly units from being included in priorities
    unit_id_str = str(unit["id"])
    current_player = unit["player"]
    filtered_targets = []
    for target_id in valid_target_pool:
        target = require_unit_by_id(game_state, target_id)
        # Skip self
        if str(target["id"]) == unit_id_str:
            continue
        # Skip friendly units
        if target["player"] == current_player:
            continue
        filtered_targets.append(target_id)
    
    # Use filtered targets for priority calculation
    # Portée tir en euclidien bord-à-bord (sélecteur `ranged`) : la distance de
    # tie-break de priorité suit la même métrique que le gate de portée.
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    _ranged_metric_prio = _ranged_distance_metric(game_state)
    _units_cache_prio = require_key(game_state, "units_cache")
    _shooter_socle_prio = socle_from_cache_entry(_units_cache_prio[unit_id_str])
    for target_id in filtered_targets:
        target = require_unit_by_id(game_state, target_id)

        distance = ranged_edge_distance(
            _shooter_socle_prio,
            socle_from_cache_entry(_units_cache_prio[str(target["id"])]),
            _ranged_metric_prio,
        )

        # Direct UPPERCASE field access - no defaults
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers instead of RNG_* fields
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        if "ARMOR_SAVE" not in target:
            raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
        # Phase 2: HP from get_hp_from_cache; target must be in cache (alive)
        if get_hp_from_cache(str(target["id"]), game_state) is None:
            raise KeyError(f"Target not in units_cache (dead/absent): {target}")
        if "HP_MAX" not in target:
            raise KeyError(f"Target missing required 'HP_MAX' field: {target}")

        # Step 1: Calculate target's threat to us (probability to wound per turn)
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected ranged weapon or best weapon
        target_rng_weapon = get_selected_ranged_weapon(target)
        target_rng_weapons = require_key(target, "RNG_WEAPONS")
        if not target_rng_weapon:
            if target_rng_weapons:
                raise ValueError(f"Selected ranged weapon is required for target threat calculation: target_id={target.get('id')}")
            # Target has no ranged weapons, use default values (threat = 0)
            target_attacks = 0
            target_bs = 7  # Can't hit
            target_s = 0
            target_ap = 0
        else:
            target_attacks = expected_dice_value(
                require_key(target_rng_weapon, "NB"),
                "shoot_priority_target_nb",
            )
            target_bs = require_key(target_rng_weapon, "ATK")
            target_s = require_key(target_rng_weapon, "STR")
            target_ap = require_key(target_rng_weapon, "AP")

        # Hit probability
        hit_prob = (7 - target_bs) / 6.0

        # Wound probability (S vs T)
        if target_s >= unit_t * 2:
            wound_prob = 5/6  # 2+
        elif target_s > unit_t:
            wound_prob = 4/6  # 3+
        elif target_s == unit_t:
            wound_prob = 3/6  # 4+
        elif target_s * 2 <= unit_t:
            wound_prob = 1/6  # 6+
        else:
            wound_prob = 2/6  # 5+

        # Failed save probability (AP is negative, subtract to worsen save)
        modified_save = unit_save - target_ap
        if modified_save > 6:
            failed_save_prob = 1.0
        else:
            failed_save_prob = (modified_save - 1) / 6.0

        # Threat per attack
        threat_per_attack = hit_prob * wound_prob * failed_save_prob
        threat_per_turn = target_attacks * threat_per_attack

        # Step 2: Calculate our kill difficulty (expected activations to kill target)
        target_t = target["T"]
        target_save = target["ARMOR_SAVE"]
        target_hp = require_hp_from_cache(str(target["id"]), game_state)

        # Our wound probability
        if unit_s >= target_t * 2:
            our_wound_prob = 5/6
        elif unit_s > target_t:
            our_wound_prob = 4/6
        elif unit_s == target_t:
            our_wound_prob = 3/6
        elif unit_s * 2 <= target_t:
            our_wound_prob = 1/6
        else:
            our_wound_prob = 2/6

        # Target's failed save (AP is negative, subtract to worsen save)
        target_modified_save = target_save - unit_ap
        if target_modified_save > 6:
            target_failed_save = 1.0
        else:
            target_failed_save = (target_modified_save - 1) / 6.0

        # Expected damage per activation
        damage_per_attack = our_hit_prob * our_wound_prob * target_failed_save
        expected_damage_per_activation = unit_attacks * damage_per_attack

        # Expected activations to kill
        if expected_damage_per_activation > 0:
            activations_to_kill = target_hp / expected_damage_per_activation
        else:
            activations_to_kill = 100  # Very hard to kill

        # Step 3: Tactical efficiency = expected damage target deals before death
        tactical_efficiency = threat_per_turn * activations_to_kill

        # Calculate target type match
        target_max_hp = target["HP_MAX"]

        # Determine target type from HP
        if target_max_hp <= 1:
            target_type = "swarm"
        elif target_max_hp <= 3:
            target_type = "troop"
        elif target_max_hp <= 6:
            target_type = "elite"
        else:
            target_type = "leader"

        type_match = 1.0 if preferred == target_type else 0.3

        # Priority scoring (lower = higher priority)
        priority = (
            -tactical_efficiency * 100,  # Higher efficiency = lower score = first
            -(type_match * 70),          # Favorite type = -70 bonus
            distance                     # Closer = lower score
        )
        target_priorities.append((target_id, priority))

    # Sort by pre-calculated priority (O(n log n) comparisons, O(1) per comparison)
    target_priorities.sort(key=lambda x: x[1])

    # Extract sorted target IDs
    valid_target_pool = [tp[0] for tp in target_priorities]
    
    # CRITICAL: Final safety check - filter out any friendly units that might have slipped through
    # This should never happen if valid_target_pool_build is correct, but adds defense in depth
    current_player = unit["player"]
    # CRITICAL: Convert to int for consistent comparison (player can be int or string)
    current_player_int = int(current_player) if current_player is not None else None
    filtered_pool = []
    for target_id in valid_target_pool:
        target = _get_unit_by_id(game_state, target_id)
        if target:
            # CRITICAL: Convert to int for consistent comparison (player can be int or string)
            target_player = int(target["player"]) if target["player"] is not None else None
            if target_player != current_player_int:
                filtered_pool.append(target_id)
            else:
                # If target is friendly, it's a bug in valid_target_pool_build - log it
                from engine.game_utils import add_console_log, add_debug_log
                add_console_log(game_state, f"[BUG] valid_target_pool_build included friendly unit {target_id} for shooter {unit_id}")
    
    valid_target_pool = filtered_pool

    # Store in cache
    _target_pool_cache[cache_key] = valid_target_pool

    # LOS_DEBUG=1: Log LoS ratio for each target when storing (baseline for contradiction analysis)
    if os.environ.get("LOS_DEBUG") == "1" and valid_target_pool:
        import sys
        from engine.combat_utils import has_line_of_sight_coords
        sc, sr = unit_col, unit_row
        for tid in valid_target_pool:
            # Instrument de diagnostic : il ne rattrape RIEN — ni ici, ni sur la primitive de LoS
            # plus bas. L'ancien `entry = units_cache.get(tid)` / `if entry:` sautait en silence
            # la cible que ce log existe précisément pour observer ; l'ancien
            # `except Exception: topo_str = "los=N/A"` masquait la panne de cette primitive. Un
            # diagnostic qui avale ses propres erreurs ne diagnostique plus rien.
            entry = require_unit_from_cache(
                tid, game_state, "shooting_build_valid_target_pool/LOS_DEBUG"
            )
            tc, tr = entry["col"], entry["row"]
            has_los = has_line_of_sight_coords(int(sc), int(sr), int(tc), int(tr), game_state)
            ratio, can_see = _get_los_visibility_state(
                game_state, int(sc), int(sr), int(tc), int(tr)
            )
            topo_str = f"los={ratio:.6f} can_see={can_see}"
            ep = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            msg = f"[LOS_DEBUG] cache MISS store unit={unit_id_str} target={tid} ({sc},{sr})->({tc},{tr}) has_los={has_los} {topo_str} ep={ep} turn={turn}\n"
            sys.stderr.write(msg)
            sys.stderr.flush()

    # Prevent memory leak: Clear cache if it grows too large
    if len(_target_pool_cache) > _cache_size_limit:
        _target_pool_cache.clear()

    # Update unit's target pool
    unit["valid_target_pool"] = valid_target_pool
    unit["_pool_from_cache"] = False
    unit["_pool_cache_key"] = str(cache_key)

    return valid_target_pool


def focus_fire_valid_target_ids_for_reward(
    shooter: Dict[str, Any], game_state: Dict[str, Any]
) -> List[str]:
    """
    Target IDs for the target_lowest_hp bonus at shot resolution time.

    When the unit already has ``valid_target_pool`` as a list (filled by
    ``shooting_build_valid_target_pool`` during target selection), reusing it
    avoids a second expensive pool build on large boards.

    If the key is missing or not a list, rebuilds via ``shooting_build_valid_target_pool``.
    """
    raw_pool = shooter.get("valid_target_pool")
    if isinstance(raw_pool, list):
        return [str(x) for x in raw_pool]
    return shooting_build_valid_target_pool(game_state, str(shooter["id"]))


def _has_line_of_sight(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Unit→unit Line of Sight (obscuring-aware). Thin wrapper over compute_unit_los() — the single
    source of truth — so eligibility, target validation, reward and deployment exposure all enforce
    the same visibility as the shooting pool.

    Shooter/target may be full unit dicts (with "id") or coordinate-only dicts ({"col","row"}); in
    the coordinate-only case the footprint collapses to the anchor hex. Positions always originate
    from units_cache (single source of truth).
    """
    los = compute_unit_los(game_state, shooter, target)
    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_log
        state = "CLEAR" if los["fully_visible"] else ("COVER" if los["can_see"] else "BLOCKED")
        add_debug_log(
            game_state,
            f"[LOS DEBUG] E{game_state.get('episode_number', '?')} T{game_state.get('turn', '?')} "
            f"Shooter {shooter.get('id', '?')} -> Target {target.get('id', '?')}: {state} "
            f"visible={los['visible']}/{los['total']}"
        )
    return los["can_see"]


def _get_los_visibility_state(
    game_state: Dict[str, Any],
    start_col: int,
    start_row: int,
    end_col: int,
    end_row: int,
) -> Tuple[float, bool]:
    """Return (visibility_ratio, can_see).

    Trace de ligne hex à la demande (``compute_los_state``), mémoïsée par paire dans
    ``_hex_los_state_cache``.
    Binary visibility (rule 06.01): can_see = ratio > 0 (no threshold).
    """
    board_cols = game_state.get("board_cols")
    board_rows = game_state.get("board_rows")
    if not isinstance(board_cols, int) or not isinstance(board_rows, int):
        raise KeyError("game_state missing required 'board_cols'/'board_rows' fields")
    if not (
        0 <= start_col < board_cols
        and 0 <= start_row < board_rows
        and 0 <= end_col < board_cols
        and 0 <= end_row < board_rows
    ):
        return 0.0, False

    _state_cache = game_state.get("_hex_los_state_cache")
    if _state_cache is not None:
        _ck = ((start_col, start_row), (end_col, end_row))
        _cached = _state_cache.get(_ck)
        if _cached is not None:
            return _cached
    from engine.hex_utils import compute_los_state, build_wall_set
    wall_set = _get_wall_set(game_state)
    _result = compute_los_state(
        start_col, start_row, end_col, end_row, wall_set,
    )
    if _state_cache is None:
        _state_cache = {}
        game_state["_hex_los_state_cache"] = _state_cache
    _state_cache[((start_col, start_row), (end_col, end_row))] = _result
    return _result


def _walls_around_occupied_floor(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    shooter_hexes: List[Tuple[int, int]],
) -> Set[Tuple[int, int]]:
    """wall_hexes autour de la délimitation du FLOOR (étage) occupé par un tireur sur étage.

    Un tireur au niveau L >= 1 voit par-dessus les murs qui bordent SON étage. La granularité est le
    ``floor`` (délimitation d'un niveau), PAS la terrain area sol : une même area peut porter plusieurs
    floors au même niveau (décors A/B distincts) → une fig sur le floor A ne doit ignorer que les murs
    de A, pas de B. On prend le(s) floor(s) au niveau L dont l'empreinte contient le socle tireur, puis
    on retire les murs situés dans ce floor OU adjacents (les murs bordent le floor, souvent juste à
    l'extérieur du rasterisé). Halo scoppé au floor → aucun mur d'un autre décor (vérifié). Set vide si
    tireur au sol (niveau 0), hors de tout floor, ou sans mur."""
    level = int(unit.get("level", 0))  # get allowed (champ optionnel, défaut sol)
    if level < 1:
        return set()
    wall_set = _get_wall_set(game_state)
    if not wall_set:
        return set()
    uid = unit.get("id")
    version = game_state.get("_unit_move_version")
    if uid is not None:
        cache = game_state.setdefault("_elevated_ignored_walls_cache", {})
        hit = cache.get(str(uid))
        if hit is not None and hit[0] == version:
            return hit[1]
    shooter_cells = {(int(c), int(r)) for c, r in shooter_hexes}
    occupied: Set[Tuple[int, int]] = set()
    for area in require_key(game_state, "terrain_areas"):
        for floor in area.get("floors", []):  # get allowed (area sans étage)
            if int(require_key(floor, "level")) != level:
                continue
            floor_hexes = {(int(h[0]), int(h[1])) for h in require_key(floor, "hexes")}
            if shooter_cells & floor_hexes:
                occupied |= floor_hexes
    result: Set[Tuple[int, int]] = set()
    if occupied:
        from engine.hex_utils import get_neighbors
        halo = set(occupied)
        for c, r in occupied:
            halo.update(get_neighbors(c, r))
        result = wall_set & halo
    if uid is not None:
        cache = game_state.setdefault("_elevated_ignored_walls_cache", {})
        cache[str(uid)] = (version, result)
    return result


def _floor_footprint_and_height(
    game_state: Dict[str, Any],
    level: int,
    footprint: List[Tuple[int, int]],
) -> "Optional[Tuple[Set[Tuple[int, int]], float]]":
    """Empreinte hex du plancher occupé + sa hauteur (pouces), pour la LoS 3D plancher-occulteur.

    Renvoie ``(E, H)`` où ``E`` = union des hexes du/des floor(s) au niveau ``level`` dont l'empreinte
    contient le socle ``footprint`` (MÊME sélection que ``_walls_around_occupied_floor``, qui calcule
    déjà la variable ``occupied``), et ``H`` = ``height_inches`` (hauteur du dessus de la dalle).
    ``None`` si ``level < 1`` (figurine au sol : aucune dalle occultante).

    Deux floors au même niveau contenant le socle avec des ``height_inches`` DIFFÉRENTS = état
    incohérent → ``ValueError`` explicite (pas de repli silencieux, CLAUDE.md). Cas normal : un seul
    floor → ``(hexes, height)``.
    """
    if int(level) < 1:
        return None
    cells = {(int(c), int(r)) for c, r in footprint}
    occupied: Set[Tuple[int, int]] = set()
    height: Optional[float] = None
    for area in require_key(game_state, "terrain_areas"):
        for floor in area.get("floors", []):  # get allowed (aire sans étage = sol seul)
            if int(require_key(floor, "level")) != int(level):
                continue
            floor_hexes = {(int(h[0]), int(h[1])) for h in require_key(floor, "hexes")}
            if not (cells & floor_hexes):
                continue
            h = float(require_key(floor, "height_inches"))
            if height is None:
                height = h
            elif height != h:
                raise ValueError(
                    f"_floor_footprint_and_height: socle sur deux floors de niveau {level} avec des "
                    f"height_inches différents ({height} vs {h}) — état incohérent"
                )
            occupied |= floor_hexes
    if not occupied or height is None:
        return None
    return occupied, height


def _fig_z_and_occluder(
    game_state: Dict[str, Any],
    level: int,
    footprint: List[Tuple[int, int]],
    model_height: float,
) -> "Tuple[float, Optional[Tuple[Set[Tuple[int, int]], float]]]":
    """Sommet vertical d'une figurine (pouces) + sa dalle-plancher occultante, pour la LoS 3D.

    ``z`` = hauteur du plancher sous la figurine (``height_inches`` du floor à ``level``, ou 0 au sol)
    + ``model_height`` (sommet du modèle, §01.04 « partie la plus proche/haute »). ``occ`` = dalle
    occultante ``(E, H)`` de son étage (``None`` si au sol). Unité : pouces (même échelle que
    ``height_inches`` / ``MODEL_HEIGHT``, jamais convertie en subhex — cf. engagement 3D)."""
    occ = _floor_footprint_and_height(game_state, level, footprint)
    floor_h = occ[1] if occ is not None else 0.0
    return floor_h + float(model_height), occ


def _get_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return cached wall_set from game_state, building it on first call."""
    cached = game_state.get("_wall_set_cache")
    if cached is not None:
        return cached
    from engine.hex_utils import build_wall_set
    ws = build_wall_set(game_state)
    game_state["_wall_set_cache"] = ws
    return ws


def _get_dense_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return cached dense (Solid, rule 13.11) wall_set, building it on first call.

    Sous-ensemble de _get_wall_set limité aux murs de terrains dense. Sert la règle 13.5
    (Gone to Ground). Vide si le plateau n'a pas de murs typés dense."""
    cached = game_state.get("_dense_wall_set_cache")
    if cached is not None:
        return cached
    from engine.hex_utils import build_dense_wall_set
    ws = build_dense_wall_set(game_state)
    game_state["_dense_wall_set_cache"] = ws
    return ws


def _get_obscuring_area_sets(game_state: Dict[str, Any]) -> List[Tuple[str, Set[Tuple[int, int]]]]:
    """Return [(area_id, hex_set), ...] for every obscuring terrain area, cached per game_state."""
    cached = game_state.get("_obscuring_area_sets_cache")
    if cached is not None:
        return cached
    out: List[Tuple[str, Set[Tuple[int, int]]]] = []
    for area in require_key(game_state, "terrain_areas"):
        if not area.get("obscuring"):
            continue
        hex_set = {(int(h[0]), int(h[1])) for h in require_key(area, "hexes")}
        out.append((str(require_key(area, "id")), hex_set))
    game_state["_obscuring_area_sets_cache"] = out
    return out


def _get_obscuring_hex_to_area(game_state: Dict[str, Any]) -> Dict[Tuple[int, int], str]:
    """Map every obscuring hex → its area id, cached per game_state (terrain is static).

    Lets LoS test whether a hit hex belongs to an excluded area in O(1) without unioning area
    hex-sets per pair — the per-pair hot path for eligibility/observation.
    """
    cached = game_state.get("_obscuring_hex_to_area_cache")
    if cached is not None:
        return cached
    out: Dict[Tuple[int, int], str] = {}
    for area_id, hex_set in _get_obscuring_area_sets(game_state):
        for h in hex_set:
            out[h] = area_id
    game_state["_obscuring_hex_to_area_cache"] = out
    return out


def _get_los_blocking_grids(game_state: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    """``(wall_grid, area_grid)`` — les DEUX bloqueurs 2D sous forme de grilles, caché par état.

    ``wall_grid`` (bool) et ``area_grid`` (int32, ``-1`` = pas d'obscuring, sinon l'INDEX de
    l'area dans ``_get_obscuring_area_sets``) portent exactement ce que le chemin scalaire lit
    dans ``wall_set`` et ``obscuring_by_hex``. Terrain statique → même durée de vie que
    ``_wall_set_cache`` et ``_obscuring_hex_to_area_cache``, dont elles sont dérivées.

    La grille couvre le plateau ET tout mur/obscuring qui déborderait de ses bornes ; une
    cellule hors grille est libre, ce qui est le comportement scalaire (``prev in wall_set``
    est faux pour une cellule sans mur, y compris hors plateau). Une coordonnée négative de
    terrain LÈVE : elle serait indexée par la fin de la grille, donc lue comme un mur ailleurs.
    """
    cached = game_state.get("_los_blocking_grids_cache")
    if cached is not None:
        return cached

    wall_set = _get_wall_set(game_state)
    obscuring_areas = _get_obscuring_area_sets(game_state)
    cols = int(require_key(game_state, "board_cols"))
    rows = int(require_key(game_state, "board_rows"))
    for source, hexes in (("wall_hexes", wall_set), *obscuring_areas):
        for c, r in hexes:
            if c < 0 or r < 0:
                raise ValueError(
                    f"Coordonnee de terrain negative dans {source}: ({c},{r}) — la LoS "
                    f"vectorisee ne peut pas l'indexer"
                )
            cols = max(cols, int(c) + 1)
            rows = max(rows, int(r) + 1)

    wall_grid = np.zeros((cols, rows), dtype=bool)
    for c, r in wall_set:
        wall_grid[int(c), int(r)] = True
    area_grid = np.full((cols, rows), -1, dtype=np.int32)
    for area_index, (_area_id, hex_set) in enumerate(obscuring_areas):
        for c, r in hex_set:
            area_grid[int(c), int(r)] = area_index

    grids = (wall_grid, area_grid)
    game_state["_los_blocking_grids_cache"] = grids
    return grids


def ground_los_blocking_signature(game_state: Dict[str, Any]) -> Tuple[Any, ...]:
    """Signature de TOUT ce qui bloque :func:`batch_ground_hex_can_see`, pour une clé de cache.

    DÉRIVÉE DES GRILLES ELLES-MÊMES, et c'est le point : `batch_ground_hex_can_see` ne lit rien
    d'autre que `wall_grid`, `area_grid` et leur forme (une cellule hors grille est libre). Deux
    terrains de même signature produisent donc, par construction, les mêmes expositions — et un
    3ᵉ bloqueur ajouté un jour aux grilles entre dans la clé SANS que personne ait à y penser.

    POURQUOI PAS UNE ÉNUMÉRATION À PART (V11 §0.65, 2ᵉ passe de revue). La version précédente
    vivait dans `ActionDecoder` et relistait les bloqueurs de son côté : murs relus du JSON brut
    avec un parseur maison, areas lues via `_get_obscuring_area_sets`. Deux énumérations de « ce
    qui bloque », à deux altitudes, dont une seule savait ce que la règle applique vraiment —
    exactement la forme de défaut que §0.64 a payée. Ici il n'y a plus rien à synchroniser.

    Le digest porte sur les octets des grilles : déterministe d'un processus à l'autre (mêmes
    murs et mêmes areas → mêmes octets), donc utilisable pour un nom de fichier partagé. La
    FORME est incluse explicitement — `tobytes()` ne la porte pas, et elle décide de ce qui est
    « hors grille », donc libre.

    Coût mesuré : 2,9 ms par appel, 2 appels par épisode (une reconstruction par joueur), soit
    0,45 % de la phase de déploiement — pas de mémoïsation, elle coûterait une 3ᵉ clé de cache
    et deux sites de purge de plus pour ça.
    """
    wall_grid, area_grid = _get_los_blocking_grids(game_state)
    return (
        wall_grid.shape,
        hashlib.sha256(wall_grid.tobytes()).hexdigest(),
        hashlib.sha256(area_grid.tobytes()).hexdigest(),
    )


def batch_ground_hex_can_see(
    game_state: Dict[str, Any],
    from_hex: Tuple[int, int],
    to_arr: np.ndarray,
) -> np.ndarray:
    """JUMEAU VECTORISÉ de :func:`compute_unit_los` pour des paires HEXE→HEXE au sol.

    Rend un tableau bool de longueur ``len(to_arr)`` : ``can_see`` de l'hexe source vers chaque
    hexe cible, pour les paires SANS unité — celles que l'exposition de déploiement construit
    (``{"col": .., "row": ..}``, cf. `ActionDecoder.deployment_los`).

    POURQUOI CE JUMEAU PEUT EXISTER SANS ROUVRIR V11 §0.64. Sur ces paires-là, et sur elles
    seules, `compute_unit_los` se REDUIT à un unique tracé 2D, et c'est démontrable terme à
    terme sur son propre code :
    - dict coordonnées-seules → ``_resolve_unit_anchor_and_footprint`` rend une empreinte
      réduite à l'ancre, donc UNE figurine tireuse et UNE cellule cible ;
    - empreinte d'une seule cellule → ``_shooter_lateral_vantage_hexes`` rend une liste vide :
      pas de vantage latéral, un seul segment à tracer ;
    - pas de clé ``MODEL_HEIGHT`` → ``z_s``/``z_t`` valent None → aucune dalle plancher-occulteur,
      donc le chemin 3D de ``_los_line_segment_clear`` n'est pas pris ;
    - pas de clé ``level`` → niveau 0 → ``_walls_around_occupied_floor`` rend l'ensemble vide,
      donc le wall_set effectif est le wall_set complet ;
    - exclusion obscuring (13.10) = area de la cellule SOURCE (``excluded_base``) ∪ area de la
      cellule CIBLE, les seules empreintes en jeu.
    Reste donc : « un mur, ou une case obscuring dont l'area n'est ni celle de la source ni
    celle de la cible, sur les cellules intermédiaires ». C'est ce qui est écrit ci-dessous.

    ⚠️ Ce qui rend le jumeau SÛR n'est pas ce raisonnement, c'est le test qui le vérifie :
    ``tests/unit/engine/test_deployment_los_vectorized_equivalence.py`` compare les deux
    chemins hexe par hexe sur la TOTALITÉ du pool, sur deux terrains. Toute évolution du modèle
    de LoS doit passer ici aussi — le test devient rouge sinon, c'est sa raison d'être.
    """
    from engine.hex_utils import batch_hex_line_steps

    n_targets = len(to_arr)
    result = np.ones(n_targets, dtype=bool)
    if n_targets == 0:
        return result

    wall_grid, area_grid = _get_los_blocking_grids(game_state)
    grid_cols, grid_rows = wall_grid.shape
    from_col, from_row = int(from_hex[0]), int(from_hex[1])

    # Area obscuring de la SOURCE : exclue de tous les tracés (13.10).
    source_area = -1
    if 0 <= from_col < grid_cols and 0 <= from_row < grid_rows:
        source_area = int(area_grid[from_col, from_row])

    # Area obscuring de CHAQUE cible : exclue de SON tracé, et d'aucun autre.
    to_cols = to_arr[:, 0].astype(np.int64)
    to_rows = to_arr[:, 1].astype(np.int64)
    target_area = np.full(n_targets, -1, dtype=np.int32)
    in_grid = (
        (to_cols >= 0) & (to_cols < grid_cols) & (to_rows >= 0) & (to_rows < grid_rows)
    )
    target_area[in_grid] = area_grid[to_cols[in_grid], to_rows[in_grid]]

    for idx, c_off, r_off in batch_hex_line_steps(from_col, from_row, to_arr, result):
        # Le test de bornes reste indispensable — une cellule hors grille est LIBRE, comme
        # `prev in wall_set` est faux hors plateau — mais il est presque toujours vrai partout
        # (mesuré : 0 cellule hors grille sur les deux terrains), d'où le chemin direct.
        inside = (c_off >= 0) & (c_off < grid_cols) & (r_off >= 0) & (r_off < grid_rows)
        if inside.all():
            sel, c_in, r_in = idx, c_off, r_off
        else:
            sel = idx[inside]
            if sel.size == 0:
                continue
            c_in, r_in = c_off[inside], r_off[inside]
        cell_area = area_grid[c_in, r_in]
        blocked = wall_grid[c_in, r_in] | (
            (cell_area >= 0)
            & (cell_area != source_area)
            & (cell_area != target_area[sel])
        )
        result[sel[blocked]] = False

    return result


def _shooter_lateral_vantage_hexes(
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    target_anchor: Tuple[int, int],
    *,
    _proj_cache: "Optional[List[Tuple[float, float]]]" = None,
    _anchor_proj: "Optional[Tuple[float, float]]" = None,
) -> List[Tuple[int, int]]:
    """Return up to 2 shooter footprint hexes that are the perpendicular extremes relative to
    the anchor→target axis (the lateral "peek" vantage points, rule: LoS from any part of the
    observing model). Empty when the footprint collapses to the anchor (single-hex base).

    Geometry is computed in the odd-q projected space (same projection as the renderer and the
    obscuring rasterizer), so "perpendicular" is geometrically faithful, then mapped back to the
    actual footprint hexes (no rounding artefacts — the points are real occupied hexes).

    ``_proj_cache`` / ``_anchor_proj`` — projections pré-calculées par l'appelant (une seule fois
    pour toute la boucle de cibles dans ``_compute_visibility_with_obscuring``). Si absents,
    la fonction les calcule elle-même (comportement inchangé).
    """
    if len(shooter_hexes) <= 1:
        return []
    from engine.hex_utils import _hex_projected

    ax, ay = _anchor_proj if _anchor_proj is not None else _hex_projected(int(shooter_anchor[0]), int(shooter_anchor[1]))
    tx, ty = _hex_projected(int(target_anchor[0]), int(target_anchor[1]))
    dx, dy = tx - ax, ty - ay
    if dx == 0.0 and dy == 0.0:
        return []
    perp_x, perp_y = -dy, dx  # 90° rotation of the anchor→target axis

    if _proj_cache is None:
        _proj_cache = [_hex_projected(int(hc), int(hr)) for hc, hr in shooter_hexes]

    best_pos: Optional[Tuple[int, int]] = None
    best_neg: Optional[Tuple[int, int]] = None
    max_d = float("-inf")
    min_d = float("inf")
    for (hc, hr), (hx, hy) in zip(shooter_hexes, _proj_cache):
        d = (hx - ax) * perp_x + (hy - ay) * perp_y
        if d > max_d:
            max_d = d
            best_pos = (int(hc), int(hr))
        if d < min_d:
            min_d = d
            best_neg = (int(hc), int(hr))

    anchor = (int(shooter_anchor[0]), int(shooter_anchor[1]))
    out: List[Tuple[int, int]] = []
    if best_pos is not None and best_pos != anchor:
        out.append(best_pos)
    if best_neg is not None and best_neg != anchor and best_neg != best_pos:
        out.append(best_neg)
    return out


def _build_shooter_proj_cache(
    anchor: Tuple[int, int],
    footprint: List[Tuple[int, int]],
) -> Tuple[Optional[Tuple[float, float]], Optional[List[Tuple[float, float]]]]:
    """Anchor projection + footprint projection list for _los_hex_visible cache params.

    Returns (None, None) for single-hex footprints: _shooter_lateral_vantage_hexes
    returns early for those, so computing projections would be wasted work.
    """
    if len(footprint) <= 1:
        return None, None
    from engine.hex_utils import _hex_projected as _hp
    return (
        _hp(int(anchor[0]), int(anchor[1])),
        [_hp(int(hc), int(hr)) for hc, hr in footprint],
    )


def _los_line_segment_clear(
    src_col: int, src_row: int, tgt_col: int, tgt_row: int,
    wall_set: Set[Tuple[int, int]],
    obscuring_by_hex: Dict[Tuple[int, int], str],
    excluded_areas: "Set[str] | frozenset",
    *,
    floor_occluders: "Optional[List[Tuple[Set[Tuple[int, int]], float]]]" = None,
    z_start: Optional[float] = None,
    z_end: Optional[float] = None,
) -> bool:
    """Ligne de visée hex dégagée entre deux hexes (cube-lerp ``hex_line``).

    Bloquée par un mur, ou par une case obscuring dont l'area n'est pas dans ``excluded_areas``
    (rule 13.10 : les areas occupées par le tireur ou la cible ne bloquent pas). PRIMITIVE DE
    TRACÉ UNIQUE partagée par le ciblage (unit→unit) et la preview (shooter→cellule), et mirroir
    du WASM ``has_los_fast``. Toute évolution de la règle de blocage se fait ICI, une seule fois.

    LoS 3D plancher-occulteur (``floor_occluders`` non vide) : en plus des blocages 2D, une case
    intermédiaire appartenant à l'empreinte ``E`` d'une dalle-plancher bloque si la hauteur
    interpolée du tracé ``h(t) = z_start + (z_end - z_start) * t`` est STRICTEMENT sous le dessus de
    la dalle ``H`` (tangence légale, cohérent avec ``low_clearance``). ``z_start``/``z_end`` requis
    dans ce mode. Sol↔sol (``floor_occluders`` vide/None) → chemin 2D historique, byte-identique.
    """
    from engine.hex_utils import hex_line_iter
    if not floor_occluders:
        # Chemin chaud 2D INCHANGÉ (byte-identique). Équivalent strict de ``hex_line(...)[1:-1]``, en
        # paresseux : on saute la 1re cellule, puis on n'examine chaque cellule qu'une fois la
        # SUIVANTE produite — la dernière n'est donc jamais testée (elle porte la cible). Le
        # générateur s'arrête dès qu'un bloqueur est trouvé : sur un plateau chargé, 68 % des lignes
        # sont bloquées et la moitié des cellules ne sert à rien.
        it = hex_line_iter(int(src_col), int(src_row), int(tgt_col), int(tgt_row))
        next(it, None)  # cellule du tireur : jamais bloquante
        prev = next(it, None)
        if prev is None:
            return True
        for cur in it:
            if prev in wall_set:
                return False
            area = obscuring_by_hex.get(prev)
            if area is not None and area not in excluded_areas:
                return False
            prev = cur
        return True
    # Chemin 3D : mêmes blocages 2D + test plancher-occulteur par-case via la hauteur interpolée.
    if z_start is None or z_end is None:
        raise ValueError("_los_line_segment_clear: floor_occluders fourni sans z_start/z_end")
    from engine.hex_utils import hex_line_iter_t
    dz = z_end - z_start
    it3 = hex_line_iter_t(int(src_col), int(src_row), int(tgt_col), int(tgt_row))
    next(it3, None)  # cellule du tireur
    prev3 = next(it3, None)
    if prev3 is None:
        return True
    for cur3 in it3:
        pcell, pt = prev3
        if pcell in wall_set:
            return False
        area = obscuring_by_hex.get(pcell)
        if area is not None and area not in excluded_areas:
            return False
        h = z_start + dz * pt
        for e_hexes, e_height in floor_occluders:
            if h < e_height and pcell in e_hexes:
                return False
        prev3 = cur3
    return True


def _los_hex_visible(
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    tgt_col: int, tgt_row: int,
    wall_set: Set[Tuple[int, int]],
    obscuring_by_hex: Dict[Tuple[int, int], str],
    excluded_areas: "Set[str] | frozenset",
    *,
    floor_occluders: "Optional[List[Tuple[Set[Tuple[int, int]], float]]]" = None,
    z_start: Optional[float] = None,
    z_end: Optional[float] = None,
    _shooter_proj_cache: "Optional[List[Tuple[float, float]]]" = None,
    _shooter_anchor_proj: "Optional[Tuple[float, float]]" = None,
) -> bool:
    """True si la case cible est vue depuis l'ancre OU un vantage latéral du tireur.

    « LoS depuis n'importe quelle partie du socle » (peek de coin) : l'ancre d'abord, les extrêmes
    perpendiculaires du socle en 2ᵉ chance (calculés seulement si l'ancre est bloquée). L'axe des
    perpendiculaires est TOUJOURS la case visée elle-même (peek par-cellule) — pas l'ancre de
    l'unité cible : sinon, pour une cible étalée (swarm), un latéral fixe « regarde au coin » et
    voit des cases dans une direction différente (faux positif). PRIMITIVE PARTAGÉE ciblage +
    preview + mirroir WASM : LoS identique par construction.

    LoS 3D : ``floor_occluders``/``z_start``/``z_end`` propagés tels quels aux tracés ancre ET
    latéraux (même ``z_start`` = sommet du tireur pour tous ses vantages, cf. plan).

    ``_shooter_proj_cache`` / ``_shooter_anchor_proj`` — projections pré-calculées par
    ``_compute_visibility_with_obscuring`` (une seule fois par appel, avant la boucle de cibles),
    transmises à ``_shooter_lateral_vantage_hexes``."""
    if _los_line_segment_clear(shooter_anchor[0], shooter_anchor[1], tgt_col, tgt_row,
                               wall_set, obscuring_by_hex, excluded_areas,
                               floor_occluders=floor_occluders, z_start=z_start, z_end=z_end):
        return True
    for sc, sr in _shooter_lateral_vantage_hexes(
        shooter_anchor, shooter_hexes, (tgt_col, tgt_row),
        _proj_cache=_shooter_proj_cache, _anchor_proj=_shooter_anchor_proj,
    ):
        if _los_line_segment_clear(sc, sr, tgt_col, tgt_row, wall_set, obscuring_by_hex, excluded_areas,
                                   floor_occluders=floor_occluders, z_start=z_start, z_end=z_end):
            import os as _os_losdbg2
            if _os_losdbg2.environ.get("W40K_LOS_DEBUG"):
                print(
                    f"[LOS_DEBUG] LATERAL-PEEK visible: anchor={shooter_anchor} "
                    f"lateral=({sc},{sr}) target=({tgt_col},{tgt_row})",
                    flush=True,
                )
            return True
    return False


def _compute_visibility_with_obscuring(
    game_state: Dict[str, Any],
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    target_anchor: Tuple[int, int],
    target_hexes: List[Tuple[int, int]],
    *,
    wall_set: Optional[Set[Tuple[int, int]]] = None,
    obscuring_by_hex: Optional[Dict[Tuple[int, int], str]] = None,
    ignored_wall_hexes: Optional[Set[Tuple[int, int]]] = None,
    floor_occluders: "Optional[List[Tuple[Set[Tuple[int, int]], float]]]" = None,
    z_start: Optional[float] = None,
    z_end: Optional[float] = None,
) -> Tuple[int, int, Set[Tuple[int, int]]]:
    """Count target footprint hexes reachable by a clear hex-line from the shooter.

    Rule (LoS, §1.x + terrain §13.10): the observing unit sees a target hex if a 1mm line can be
    drawn from ANY part of the observing model to that hex. We approximate "any part of the
    observer" with the anchor hex plus the two perpendicular footprint extremes (lateral peek),
    evaluated as a 2nd chance only when the anchor line is blocked. A line is blocked by a dense
    wall (always) or by an obscuring terrain area that neither the shooter nor the target occupies
    (excluding areas one or both units are within).

    ``wall_set`` / ``obscuring_by_hex`` overrides (défaut = sets complets du plateau) : servent la
    règle 13.5 (Gone to Ground), en restreignant le test aux murs Solid/dense et en désactivant les
    obscuring areas (passer ``{}``) pour isoler "not fully visible due to intervening Solid terrain".

    ``floor_occluders``/``z_start``/``z_end`` (LoS 3D plancher-occulteur, propagés à ``_los_hex_visible``) :
    dalles ``[(E, H), …]`` des étages du tireur et/ou de la cible + sommets verticaux (pouces). Vide/None
    (sol↔sol) → tracé 2D inchangé. ``z_end`` = sommet du MODÈLE cible (constant sur tout son socle).
    Returns (visible_hexes, total_hexes, visible_hex_set).
    """
    wall_set = _get_wall_set(game_state) if wall_set is None else wall_set
    obscuring_by_hex = (
        _get_obscuring_hex_to_area(game_state) if obscuring_by_hex is None else obscuring_by_hex
    )
    # Tireur sur un étage (niveau >= 1) : il voit par-dessus les murs de la ruine qu'il occupe →
    # ces murs (dense ou non) ne bloquent plus sa LoS. Seuls ces murs-là sont retirés ; les murs
    # des autres ruines et les obscuring areas continuent de bloquer normalement.
    if ignored_wall_hexes:
        wall_set = wall_set - ignored_wall_hexes

    # Areas the shooter or target occupies are excluded as blockers (rule 13.10). Resolved via the
    # hex→area map (cheap lookups) instead of unioning every obscuring area's hexes on every pair —
    # the union was the dominant per-pair cost.
    excluded_areas: Set[str] = set()
    for c, r in shooter_hexes:
        area = obscuring_by_hex.get((int(c), int(r)))
        if area is not None:
            excluded_areas.add(area)
    for c, r in target_hexes:
        area = obscuring_by_hex.get((int(c), int(r)))
        if area is not None:
            excluded_areas.add(area)

    anchor = (int(shooter_anchor[0]), int(shooter_anchor[1]))

    # Precompute shooter hex projections once for the whole target loop.
    # At x5, shooter_hexes can be 129+ hexes, and without caching each call to
    # _shooter_lateral_vantage_hexes would reproject them once per target hex → O(n×m).
    _shooter_anchor_proj, _shooter_proj_cache = _build_shooter_proj_cache(anchor, shooter_hexes)

    visible = 0
    visible_hex_set: Set[Tuple[int, int]] = set()
    for tc, tr in target_hexes:
        if _los_hex_visible(anchor, shooter_hexes, tc, tr, wall_set, obscuring_by_hex,
                            excluded_areas, floor_occluders=floor_occluders,
                            z_start=z_start, z_end=z_end,
                            _shooter_proj_cache=_shooter_proj_cache,
                            _shooter_anchor_proj=_shooter_anchor_proj):
            visible += 1
            visible_hex_set.add((int(tc), int(tr)))
    return visible, len(target_hexes), visible_hex_set


def _resolve_unit_anchor_and_footprint(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    *,
    gym_training: bool,
) -> Tuple[Tuple[int, int], List[Tuple[int, int]]]:
    """Return (anchor, footprint) for a unit. Anchor is its single source-of-truth position;
    footprint is the list of occupied hexes (anchor only in gym training or single-cell units).

    Positions always originate from units_cache (single source of truth). A coordinate-only dict
    ({"col","row"}) is also accepted (its anchor is its own coords, footprint = anchor).
    """
    if "id" in unit:
        anchor = require_unit_position(unit, game_state)
    else:
        anchor = normalize_coordinates(int(unit["col"]), int(unit["row"]))
    footprint: List[Tuple[int, int]] = [anchor]
    if not gym_training and "id" in unit:
        # `require_unit_position` ci-dessus a déjà tranché la présence (preuve statique) ; le
        # repli sur l'ancre seule aurait sinon amputé l'empreinte du tireur.
        entry = require_unit_from_cache(
            str(unit["id"]), game_state, "_resolve_unit_anchor_and_footprint"
        )
        occ = entry.get("occupied_hexes")  # get allowed (repli ancre si le champ est vide)
        if isinstance(occ, (set, list, tuple)) and len(occ) > 0:
            resolved = [
                normalize_coordinates(hx[0], hx[1])
                for hx in occ
                if isinstance(hx, (list, tuple)) and len(hx) >= 2
            ]
            if resolved:
                footprint = resolved
    return anchor, footprint


def compute_unit_los(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    target: Dict[str, Any],
) -> Dict[str, Any]:
    """Single source of truth for unit→unit Line of Sight (obscuring-aware).

    Returns {can_see, fully_visible, cover, cover_conditions, visible, total, visible_cells}:
    - can_see: >= 1 target model has >= 1 base cell reachable (rule 06.01 — binary,
      per-model; no visibility ratio threshold).
    - visible_cells: sorted list of (col,row) of the target footprint hexes actually seen.
    - fully_visible: every target footprint hex is reachable (no intervening terrain).
    - cover (rule 13.08, unit-level): can_see AND ((target hideable AND within a terrain area)
      OR not fully_visible).
    - cover_conditions: la condition 13.08 remplie par CHAQUE figurine cible ("a" / "b" / "").
      DIAGNOSTIC D'AFFICHAGE uniquement (badge par figurine) — le -1 BS se lit sur ``cover``,
      qui reste tout-ou-rien : une seule figurine à "" annule le couvert de toute l'escouade.

    All shooting LoS/cover/eligibility/observation must route through this function so the engine
    enforces one consistent visibility everywhere.

    Per-pair cache: visibility is static for a fixed board layout + unit positions, so results are
    cached by (shooter_id, target_id) in ``_unit_los_pair_cache`` (dict pur, persistant) and
    invalidated **de façon ciblée** par ``_touch_unit_los`` (shared_utils) à chaque mouvement / perte
    de figurine : seules les entrées de l'unité concernée sont supprimées (plus de jet global sur
    ``_unit_move_version``). Coordinate-only dicts (e.g. deployment exposure) have no id and bypass
    the cache. This keeps the per-step observation cost and the eligibility sweep cheap.
    """
    sid = shooter.get("id")
    tid = target.get("id")
    if sid is not None and tid is not None:
        # D3 : pair-cache = dict pur {(s,t): result}, persistant (plus jeté sur _unit_move_version).
        # Invalidation ciblée par _touch_unit_los au choke-point (shared_utils) à chaque mouvement /
        # perte de figurine → seules les paires de l'unité concernée sont supprimées.
        holder = game_state.get("_unit_los_pair_cache")
        if holder is None:
            holder = {}
            game_state["_unit_los_pair_cache"] = holder
        key = (str(sid), str(tid))
        cached = holder.get(key)
        if cached is not None:
            return cached
        result = _compute_unit_los_uncached(game_state, shooter, target)
        holder[key] = result
        return result
    return _compute_unit_los_uncached(game_state, shooter, target)


def _resolve_target_models_for_los(
    game_state: Dict[str, Any],
    target: Dict[str, Any],
    gym_training: bool,
) -> Tuple[List[List[Tuple[int, int]]], List[Optional[Tuple[int, int]]], Any, Any, Any, List[int]]:
    """Empreintes par figurine vivante de la cible (+ centres, socle couvert et NIVEAUX).

    Source unique partagée par ``_compute_unit_los_uncached`` (LoS complète) et
    ``_unit_can_see_any`` (éligibilité), pour garantir une géométrie cible identique.

    Retourne (target_model_footprints, target_model_centers, cover_base_shape,
    cover_base_size, cover_orientation, target_model_levels). ``target_model_centers`` et
    ``target_model_levels`` sont alignés index-à-index sur les footprints (niveau utilisé par la
    LoS 3D pour la dalle occultante côté cible). None/0 pour le repli non-découpé (gym / dict
    coordonnées-seules).
    """
    target_model_footprints: List[List[Tuple[int, int]]] = []
    target_model_centers: List[Optional[Tuple[int, int]]] = []
    target_model_levels: List[int] = []
    cover_base_shape: Any = None
    cover_base_size: Any = None
    cover_orientation: Any = None
    target_id = target.get("id")
    if not gym_training and target_id is not None:
        model_ids = require_key(game_state, "squad_models").get(str(target_id))
        if model_ids:
            from engine.hex_utils import compute_occupied_hexes
            models_cache = require_key(game_state, "models_cache")
            base_shape = require_key(target, "BASE_SHAPE")
            base_size = require_key(target, "BASE_SIZE")
            orientation = require_key(target, "orientation")
            cover_base_shape = base_shape
            cover_base_size = base_size
            cover_orientation = orientation
            for mid in model_ids:
                m = models_cache.get(mid)
                if m is None:
                    raise KeyError(f"Model {mid} missing from models_cache")
                if int(require_key(m, "HP_CUR")) <= 0:
                    continue
                target_model_footprints.append([
                    (int(hx[0]), int(hx[1]))
                    for hx in compute_occupied_hexes(
                        int(m["col"]), int(m["row"]), base_shape, base_size, orientation
                    )
                ])
                target_model_centers.append((int(m["col"]), int(m["row"])))
                target_model_levels.append(int(require_key(m, "level")))
    if not target_model_footprints:
        # Pas de découpage par modèle (gym : empreinte réduite à l'ancre ; dict
        # coordonnées-seules : pas de squad) → l'empreinte entière vaut un modèle.
        _target_anchor, target_hexes = _resolve_unit_anchor_and_footprint(
            game_state, target, gym_training=gym_training
        )
        target_model_footprints.append([(int(c), int(r)) for c, r in target_hexes])
        target_model_centers.append(None)
        target_model_levels.append(int(target.get("level", 0)))  # get allowed (défaut sol)
    return (
        target_model_footprints,
        target_model_centers,
        cover_base_shape,
        cover_base_size,
        cover_orientation,
        target_model_levels,
    )


def _resolve_shooter_models_with_walls(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    gym_training: bool,
) -> Tuple[List[Tuple[Tuple[int, int], List[Tuple[int, int]], Set[Tuple[int, int]], Optional[float], Any]], List[Tuple[int, int]]]:
    """Décompose le TIREUR par figurine vivante pour la LoS (règle 06.01, tracée PAR figurine).

    Retourne (shooter_models, shooter_hexes_all) où chaque shooter_model est
    (anchor, footprint, wall_set_effectif, z_s, occ_s) : le wall_set effectif de CETTE figurine est le mur du
    plateau MOINS les murs de la ruine qu'elle occupe si elle est sur un étage (niveau >= 1) —
    sinon le mur complet. Ainsi une figurine au sol reste bloquée par un mur même si une figurine
    de la même escouade, sur l'étage, ne l'est plus. ``shooter_hexes_all`` = union des empreintes
    (sert au calcul des obscuring areas occupées par le tireur, règle 13.10, inchangé au niveau
    unité). Repli non-découpé (gym / dict coordonnées-seules) : une seule figurine = l'unité, niveau
    ``unit["level"]``.

    Résultat mémoïsé par (shooter_id, _unit_move_version) : les empreintes/niveaux des figurines
    tireuses ne dépendent que du tireur et sont recalculées à l'identique pour chaque cible pendant
    la construction du los_cache. Le cache est invalidé au moindre mouvement (version). Les tireurs
    sans id (gym / coord-only) ne sont pas cachés.
    """
    shooter_id = shooter.get("id")
    version = game_state.get("_unit_move_version")
    cache_key = None
    if not gym_training and shooter_id is not None:
        cache_key = str(shooter_id)
        holder = game_state.get("_shooter_los_models_cache")
        if holder is None:
            holder = {}
            game_state["_shooter_los_models_cache"] = holder
        hit = holder.get(cache_key)
        if hit is not None and hit[0] == version:
            return hit[1], hit[2]
    base_wall_set = _get_wall_set(game_state)
    # MODEL_HEIGHT du tireur (pouces) : présent sur toute vraie unité roster. Absent des stubs 2D
    # (gym) → z_s = None → LoS 3D désactivée pour ce tireur (tracé 2D). Requis pour interpoler la
    # hauteur même quand le tireur est au sol mais la cible à l'étage (z_s = 0 + MODEL_HEIGHT).
    shooter_mh = float(shooter["MODEL_HEIGHT"]) if "MODEL_HEIGHT" in shooter else None
    shooter_models: List[Tuple[Tuple[int, int], List[Tuple[int, int]], Set[Tuple[int, int]], Optional[float], Any]] = []
    shooter_hexes_all: List[Tuple[int, int]] = []
    if not gym_training and shooter_id is not None:
        model_ids = require_key(game_state, "squad_models").get(str(shooter_id))
        if model_ids:
            from engine.hex_utils import compute_occupied_hexes
            models_cache = require_key(game_state, "models_cache")
            base_shape = require_key(shooter, "BASE_SHAPE")
            base_size = require_key(shooter, "BASE_SIZE")
            orientation = require_key(shooter, "orientation")
            for mid in model_ids:
                m = models_cache.get(mid)
                if m is None:
                    raise KeyError(f"Model {mid} missing from models_cache")
                if int(require_key(m, "HP_CUR")) <= 0:
                    continue
                anchor = (int(m["col"]), int(m["row"]))
                footprint = [
                    (int(hx[0]), int(hx[1]))
                    for hx in compute_occupied_hexes(
                        anchor[0], anchor[1], base_shape, base_size, orientation
                    )
                ]
                m_level = int(require_key(m, "level"))
                # Set de murs ignorés PAR figurine (∅ si niveau 0). Cache par model id préfixé
                # "m:" pour ne pas entrer en collision avec le cache par unité.
                ignored = _walls_around_occupied_floor(
                    game_state, {"id": f"m:{mid}", "level": m_level}, footprint
                )
                wall_eff = base_wall_set - ignored if ignored else base_wall_set
                # LoS 3D : sommet vertical + dalle occultante PAR figurine tireuse (None si mh absent).
                if shooter_mh is None:
                    z_s, occ_s = None, None
                else:
                    z_s, occ_s = _fig_z_and_occluder(game_state, m_level, footprint, shooter_mh)
                shooter_models.append((anchor, footprint, wall_eff, z_s, occ_s))
                shooter_hexes_all.extend(footprint)
    if not shooter_models:
        anchor, footprint = _resolve_unit_anchor_and_footprint(
            game_state, shooter, gym_training=gym_training
        )
        footprint = [(int(c), int(r)) for c, r in footprint]
        s_level = int(shooter.get("level", 0))  # get allowed (champ optionnel, défaut sol)
        ignored = _walls_around_occupied_floor(game_state, shooter, footprint)
        wall_eff = base_wall_set - ignored if ignored else base_wall_set
        if shooter_mh is None:
            z_s, occ_s = None, None
        else:
            z_s, occ_s = _fig_z_and_occluder(game_state, s_level, footprint, shooter_mh)
        shooter_models.append(((int(anchor[0]), int(anchor[1])), footprint, wall_eff, z_s, occ_s))
        shooter_hexes_all.extend(footprint)
    if cache_key is not None:
        game_state["_shooter_los_models_cache"][cache_key] = (
            version, shooter_models, shooter_hexes_all
        )
    return shooter_models, shooter_hexes_all


def _target_model_visible_cells(
    shooter_models: List[Tuple[Tuple[int, int], List[Tuple[int, int]], Set[Tuple[int, int]], Optional[float], Any]],
    target_model_hexes: List[Tuple[int, int]],
    obscuring_by_hex: Dict[Tuple[int, int], str],
    excluded_areas: Set[str],
    *,
    z_target: Optional[float] = None,
    occ_target: "Optional[Tuple[Set[Tuple[int, int]], float]]" = None,
) -> Set[Tuple[int, int]]:
    """Cases du socle cible vues depuis AU MOINS une figurine tireuse (règle 06.01, binaire).

    Chaque figurine tireuse utilise son propre wall_set effectif (murs ignorés si elle est sur un
    étage). Une case cible est vue dès qu'une figurine tireuse a une ligne dégagée vers elle.

    LoS 3D : ``z_target``/``occ_target`` = sommet vertical + dalle occultante de CE modèle cible.
    Combinés PAR figurine tireuse à ses propres ``z_s``/``occ_s`` (portés par le 5-tuple). Sol↔sol
    (z None des deux côtés, aucune dalle) → tracé 2D inchangé."""
    # Précalculé une fois par figurine tireuse, hors de la boucle des cases :
    # ``floor_occ`` (dalles occultantes) + proj_cache (projections du socle tireur) évitent de
    # recalculer ces valeurs pour chaque case cible × figurine tireuse → O(N×M) au lieu de O(N×M×footprint).
    # Chaque entrée : (anchor, footprint, wall_eff, z_s, floor_occ, proj_cache, anchor_proj).
    prepared: List[Tuple[Tuple[int, int], List[Tuple[int, int]], Set[Tuple[int, int]], Optional[float], Any, Optional[List[Tuple[float, float]]], Optional[Tuple[float, float]]]] = []
    for s_anchor, s_footprint, s_wall, z_s, occ_s in shooter_models:
        if (z_s is not None) and (z_target is not None):
            occs = [o for o in (occ_s, occ_target) if o is not None]
            floor_occ = occs or None
        else:
            floor_occ = None
        s_anchor_proj, s_proj_cache = _build_shooter_proj_cache(s_anchor, s_footprint)
        prepared.append((s_anchor, s_footprint, s_wall, z_s, floor_occ, s_proj_cache, s_anchor_proj))
    vset: Set[Tuple[int, int]] = set()
    for tc, tr in target_model_hexes:
        for s_anchor, s_footprint, s_wall, z_s, floor_occ, s_proj_cache, s_anchor_proj in prepared:
            if _los_hex_visible(
                s_anchor, s_footprint, tc, tr, s_wall, obscuring_by_hex, excluded_areas,
                floor_occluders=floor_occ, z_start=z_s, z_end=z_target,
                _shooter_proj_cache=s_proj_cache, _shooter_anchor_proj=s_anchor_proj,
            ):
                vset.add((int(tc), int(tr)))
                break
    return vset


def _excluded_obscuring_areas(
    obscuring_by_hex: Dict[Tuple[int, int], str],
    *hex_groups: List[Tuple[int, int]],
) -> Set[str]:
    """Obscuring areas occupées par au moins une case des groupes fournis (règle 13.10 : une area
    occupée par le tireur ou la cible ne bloque pas)."""
    excluded: Set[str] = set()
    for group in hex_groups:
        for c, r in group:
            area = obscuring_by_hex.get((int(c), int(r)))
            if area is not None:
                excluded.add(area)
    return excluded


def _unit_can_see_any(game_state: Dict[str, Any], shooter: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """True dès qu'AU MOINS une figurine cible est vue par le tireur (règle 06.01, ``can_see``).

    Variante allégée de ``compute_unit_los`` réservée à l'ÉLIGIBILITÉ du pool de tir :
    early-exit à la première figurine visible, sans calcul de couvert ni écriture du cache
    par-paire (celui-ci attend le résultat complet, produit à l'activation via ``compute_unit_los``).
    Même géométrie tireur/cible que la LoS complète (PAR figurine tireuse) → aucun faux négatif.
    """
    gym_training = bool(
        game_state.get("gym_training_mode", False)
        or require_key(game_state, "config").get("gym_training_mode", False)
    )
    shooter_models, shooter_hexes_all = _resolve_shooter_models_with_walls(
        game_state, shooter, gym_training
    )
    (
        target_model_footprints, _centers, _bshape, _bsize, _borient, target_model_levels
    ) = _resolve_target_models_for_los(game_state, target, gym_training)
    obscuring_by_hex = _get_obscuring_hex_to_area(game_state)
    excluded_base = _excluded_obscuring_areas(obscuring_by_hex, shooter_hexes_all)
    # LoS 3D : MODEL_HEIGHT cible (None sur stubs 2D → z_t None → tracé 2D).
    target_mh = float(target["MODEL_HEIGHT"]) if "MODEL_HEIGHT" in target else None
    for idx, model_hexes in enumerate(target_model_footprints):
        excluded = excluded_base | _excluded_obscuring_areas(obscuring_by_hex, model_hexes)
        if target_mh is None:
            z_t, occ_t = None, None
        else:
            z_t, occ_t = _fig_z_and_occluder(
                game_state, target_model_levels[idx], model_hexes, target_mh
            )
        if _target_model_visible_cells(
            shooter_models, model_hexes, obscuring_by_hex, excluded,
            z_target=z_t, occ_target=occ_t,
        ):
            return True
    return False


def _model_footprint_not_fully_visible_due_to_solid(
    game_state: Dict[str, Any],
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    target_model_hexes: List[Tuple[int, int]],
    dense_wall_set: Set[Tuple[int, int]],
    ignored_wall_hexes: Optional[Set[Tuple[int, int]]] = None,
) -> bool:
    """Règle 13.5, condition 2, PAR FIGURINE : cette figurine cible n'est pas entièrement visible
    pour le tireur à cause d'un terrain Solid (dense) intervenant.

    Teste la visibilité de l'empreinte de CETTE figurine en n'utilisant QUE le set de murs dense et
    en DÉSACTIVANT les obscuring areas (obscuring_by_hex={}), pour que seul un terrain Solid — pas
    une obscuring area (13.10) — puisse rendre la figurine "gone to ground". True si >=1 case du
    socle est masquée par un mur dense. ``ignored_wall_hexes`` (murs de la ruine occupée par un
    tireur élevé) sont retirés → ces murs-là ne déclenchent jamais gone to ground."""
    v, t, _vset = _compute_visibility_with_obscuring(
        game_state, shooter_anchor, shooter_hexes, target_model_hexes[0], target_model_hexes,
        wall_set=dense_wall_set, obscuring_by_hex={},
        ignored_wall_hexes=ignored_wall_hexes,
    )
    return t > 0 and v < t


def hidden_enemy_out_of_detection(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    enemy: Dict[str, Any],
    base_detection_subhex: float,
) -> bool:
    """Règle 13.09 + 13.5, évaluées PAR FIGURINE. True → l'ennemi hidden est hors de la detection de
    ``shooter`` (à exclure du pool de cibles).

    L'unité est détectable dès qu'AU MOINS une figurine cachée est à portée de SA propre detection
    range : ``base``, ou ``base − 3"`` si cette figurine n'est pas entièrement visible pour le
    tireur à cause d'un terrain Solid intervenant ("gone to ground", rule 13.5). Distance bord-à-bord
    socle↔socle par figurine (métrique de tir), cohérente avec valid_target_pool_build. ``shooter``
    peut être un dict unité (id) ou un dict coordonnées-seules ({col,row})."""
    from engine.hex_utils import Socle
    from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
    penalty = 3 * int(require_key(game_state, "inches_to_subhex"))
    dense_wall_set = _get_dense_wall_set(game_state)
    metric = _ranged_distance_metric(game_state)
    gym_training = bool(
        game_state.get("gym_training_mode", False)
        or require_key(game_state, "config").get("gym_training_mode", False)
    )
    shooter_anchor, shooter_hexes = _resolve_unit_anchor_and_footprint(
        game_state, shooter, gym_training=gym_training
    )
    units_cache = require_key(game_state, "units_cache")
    if "id" in shooter:
        shooter_socle = socle_from_cache_entry(units_cache[str(shooter["id"])])
    else:
        shooter_socle = Socle(
            "round", 1, shooter_anchor[0], shooter_anchor[1], set(shooter_hexes), [shooter_anchor]
        )
    footprints, centers, bshape, bsize, borient, _levels = _resolve_target_models_for_los(
        game_state, enemy, gym_training
    )
    _bshape = bshape if bshape is not None else "round"
    _bsize = bsize if bsize is not None else 1
    _borient = int(borient) if borient is not None else 0
    for i, model_hexes in enumerate(footprints):
        _center_i = centers[i]  # local → narrowing fiable (pyright ne narrow pas centers[i] indexé)
        center = _center_i if _center_i is not None else model_hexes[0]
        model_socle = Socle(
            _bshape, _bsize, center[0], center[1], set(model_hexes), [center], _borient
        )
        # Cap passé NON tronqué : c'est bien `base_detection_subhex` que les deux tests
        # ci-dessous comparent, et `ranged_edge_distance` arrondit elle-même ce qu'exige sa
        # branche hex. Un `int()` posé ici rendrait un cap plus petit que le seuil comparé, donc
        # un minorant pour une figurine située entre les deux — hors détection, traitée comme
        # détectable.
        dist = ranged_edge_distance(
            shooter_socle, model_socle, metric, max_distance=base_detection_subhex
        )
        if dist <= base_detection_subhex - penalty:
            return False  # figurine dans la detection réduite → détectable quoi qu'il arrive
        if dist > base_detection_subhex:
            continue  # hors detection même sans GtG
        # Bande ]base−3"; base] : le GtG peut faire basculer CETTE figurine hors detection.
        if not (
            dense_wall_set
            and _model_footprint_not_fully_visible_due_to_solid(
                game_state, shooter_anchor, shooter_hexes, model_hexes, dense_wall_set,
                _walls_around_occupied_floor(game_state, shooter, shooter_hexes),
            )
        ):
            return False  # pas gone to ground → détectable à base
        # gone to ground → detection = base−3" < dist → cette figurine ne détecte pas
    return True


def _compute_unit_los_uncached(
    game_state: Dict[str, Any],
    shooter: Dict[str, Any],
    target: Dict[str, Any],
) -> Dict[str, Any]:
    """Uncached core of compute_unit_los() — see that function for semantics."""
    gym_training = bool(
        game_state.get("gym_training_mode", False)
        or require_key(game_state, "config").get("gym_training_mode", False)
    )

    # Règle 06.01 : la LoS est tracée PAR figurine tireuse. Chaque figurine tireuse a son propre
    # wall_set effectif (murs de sa ruine ignorés si elle est sur un étage) → une figurine au sol
    # reste bloquée par un mur même si une figurine de la même escouade, sur l'étage, ne l'est plus.
    shooter_models, shooter_hexes_all = _resolve_shooter_models_with_walls(
        game_state, shooter, gym_training
    )

    # Règles 06.01 + 13.10 : visibilité binaire évaluée PAR MODÈLE cible. Un modèle est
    # visible si >= 1 cellule de son socle a une ligne dégagée depuis >= 1 figurine tireuse ;
    # l'unité est visible si >= 1 modèle l'est. Chaque test exclut les areas obscuring du tireur
    # (union de l'escouade) et celles que CE modèle cible occupe.
    (
        target_model_footprints,
        target_model_centers,
        cover_base_shape,
        cover_base_size,
        cover_orientation,
        target_model_levels,
    ) = _resolve_target_models_for_los(game_state, target, gym_training)

    obscuring_by_hex = _get_obscuring_hex_to_area(game_state)
    excluded_base = _excluded_obscuring_areas(obscuring_by_hex, shooter_hexes_all)
    # LoS 3D : MODEL_HEIGHT cible (None sur stubs 2D → z_t None → tracé 2D inchangé).
    target_mh = float(target["MODEL_HEIGHT"]) if "MODEL_HEIGHT" in target else None

    visible = 0
    total = 0
    visible_models = 0
    visible_hex_set: Set[Tuple[int, int]] = set()
    # Visibilité intégrale par figurine (index aligné sur target_model_footprints) : True si tout le
    # socle de CETTE figurine est vu par le tireur. Base du test (b) par-figurine du couvert (13.08).
    model_full_vis: List[bool] = []
    for idx, model_hexes in enumerate(target_model_footprints):
        excluded = excluded_base | _excluded_obscuring_areas(obscuring_by_hex, model_hexes)
        if target_mh is None:
            z_t, occ_t = None, None
        else:
            z_t, occ_t = _fig_z_and_occluder(
                game_state, target_model_levels[idx], model_hexes, target_mh
            )
        vset = _target_model_visible_cells(
            shooter_models, model_hexes, obscuring_by_hex, excluded,
            z_target=z_t, occ_target=occ_t,
        )
        v = len(vset)
        t = len(model_hexes)
        visible += v
        total += t
        visible_hex_set |= vset
        if v > 0:
            visible_models += 1
        model_full_vis.append(t > 0 and v == t)
    can_see = visible_models > 0
    fully_visible = total > 0 and visible == total

    # Couvert (règle 13.08) évalué PAR FIGURINE : l'unité a le couvert si CHAQUE figurine vivante
    # remplit au moins une condition :
    #   (a) INFANTRY/BEASTS/SWARM et dans un terrain area (test terrain pur, indépendant du tireur),
    #   (b) pas entièrement visible par le tireur (socle partiellement masqué, ou figurine invisible).
    # Une seule figurine entièrement visible ET hors terrain area annule le couvert de toute l'unité.
    #
    # ``cover_conditions`` retient EN PLUS, pour chaque figurine, la condition qu'elle remplit
    # ("a", "b", ou "" = aucune). C'est un DIAGNOSTIC d'affichage (badge de couvert par figurine
    # côté PvP) : le -1 BS reste unité-niveau et se lit sur ``cover``, jamais ici. Le balayage est
    # donc complet, sans la sortie anticipée que le seul booléen d'unité autoriserait — mesuré à
    # 0,49 % du coût de cette fonction en PvP (153 us contre 31 ms/paire), et nul en entraînement
    # où ``_resolve_target_models_for_los`` ne découpe pas la cible par figurine (boucle à un
    # élément). La clé est TOUJOURS présente : ``assert_los_pair_cache_consistent`` compare le
    # résultat du pair-cache à celui-ci par égalité stricte, une clé conditionnelle le casserait.
    from engine.terrain_utils import model_within_terrain
    terrain_areas = require_key(game_state, "terrain_areas")
    target_hideable = bool(target.get("hideable"))
    cover = False
    cover_conditions: List[str] = []
    if can_see:
        all_models_covered = True
        for idx in range(len(target_model_footprints)):
            # (b) : figurine pas entièrement visible → couverte, condition remplie.
            if not model_full_vis[idx]:
                cover_conditions.append("b")
                continue
            # Figurine entièrement visible → doit remplir (a), sinon l'unité perd le couvert.
            center = target_model_centers[idx]
            cond_a = (
                target_hideable
                and center is not None
                and model_within_terrain(
                    center[0], center[1],
                    cover_base_shape, cover_base_size, cover_orientation,
                    terrain_areas, obscuring_only=False,
                )
            )
            cover_conditions.append("a" if cond_a else "")
            if not cond_a:
                all_models_covered = False
        cover = all_models_covered

    return {
        "can_see": can_see,
        "fully_visible": fully_visible,
        "cover": cover,
        # Condition 13.08 remplie par CHAQUE figurine cible, alignée index-pour-index sur les
        # empreintes : "a" (dans un terrain area), "b" (pas entièrement visible), "" (découverte —
        # c'est elle qui annule le couvert de l'escouade). Vide si la cible n'est pas vue.
        "cover_conditions": cover_conditions,
        "visible": visible,
        "total": total,
        # Cellules de l'empreinte cible réellement vues (règle 06.01/13.10 par-figurine).
        # Consommé par la preview frontend pour peindre les cases visibles des cibles ciblables
        # par-dessus le cône WASM → cohérence blink↔visuel garantie (une cible qui blinke a
        # toujours ses cases peintes, mêmes exclusions obscuring que le ciblage).
        "visible_cells": sorted(visible_hex_set),
    }


def _update_unit_los_preview_data(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    weapon_rule: int,
    advance_status: int,
    adjacent_status: int,
) -> None:
    """
    Build backend LoS preview payload for frontend.

    Single source of truth:
    - Uses backend LoS ratio computation and backend weapon availability context.
    - Persists on unit as:
      - los_preview_attack_cells: [{col,row}, ...] clear LoS
      - los_preview_cover_cells: [{col,row}, ...] visible in cover
      - los_preview_ratio_by_hex: {"col,row": ratio_float, ...} for all evaluated hexes
    """
    if "id" not in unit:
        raise KeyError(f"Unit missing required 'id' field: {unit}")
    if "player" not in unit:
        raise KeyError(f"Unit missing required 'player' field: {unit}")

    weapon_available_pool = weapon_availability_check(
        game_state, unit, weapon_rule, advance_status, adjacent_status
    )
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    if not usable_weapons:
        unit["los_preview_attack_cells"] = []
        unit["los_preview_cover_cells"] = []
        unit["los_preview_ratio_by_hex"] = {}
        return

    max_range = 0
    for weapon_info in usable_weapons:
        weapon = require_key(weapon_info, "weapon")
        weapon_range = require_key(weapon, "RNG")
        if not isinstance(weapon_range, int):
            raise TypeError(
                f"Weapon RNG must be int for LoS preview, got {type(weapon_range).__name__}: {weapon_range}"
            )
        if weapon_range > max_range:
            max_range = weapon_range
    if max_range <= 0:
        unit["los_preview_attack_cells"] = []
        unit["los_preview_cover_cells"] = []
        unit["los_preview_ratio_by_hex"] = {}
        return

    board_cols = require_key(game_state, "board_cols")
    board_rows = require_key(game_state, "board_rows")
    if not isinstance(board_cols, int) or not isinstance(board_rows, int):
        raise TypeError(
            "game_state board dimensions must be ints: "
            f"board_cols={type(board_cols).__name__}, board_rows={type(board_rows).__name__}"
        )

    shooter_col, shooter_row = require_unit_position(unit, game_state)

    # Obscuring-aware hex preview (shooter anchor → each in-range hex). Blockers = dense walls +
    # obscuring areas, EXCEPT areas the shooter occupies and EXCEPT the target hex's own area
    # (a model inside an obscuring area is still visible at its edge — rule 13.10 exclusion).
    # A visible hex that lies within any terrain area is a cover tile (a unit there benefits from
    # terrain cover); a visible hex in the open is a clear attack tile. Single-source-of-truth
    # blockers (no walls-only ratio); the authoritative per-target cover stays in los_cover_cache.
    gym_training = bool(
        game_state.get("gym_training_mode", False)
        or require_key(game_state, "config").get("gym_training_mode", False)
    )
    _shooter_anchor, _shooter_hexes = _resolve_unit_anchor_and_footprint(
        game_state, unit, gym_training=gym_training
    )
    # Cône de preview « au sol » : tous les murs bloquent (niveau unité). L'overlay VERT « vue par
    # l'étage » (murs de la ruine occupée ignorés pour les figs de l'étage AFFICHÉ) est calculé
    # côté frontend, car il dépend du niveau affiché (currentLevel) que le backend ne connaît pas.
    wall_set = _get_wall_set(game_state)
    shooter_set = {(int(c), int(r)) for c, r in _shooter_hexes}
    obscuring_by_hex: Dict[Tuple[int, int], str] = {}
    for _area_id, _hex_set in _get_obscuring_area_sets(game_state):
        if shooter_set & _hex_set:
            continue  # area the shooter occupies → never blocks for this shooter
        for _h in _hex_set:
            obscuring_by_hex[_h] = _area_id
    terrain_hex_set: Set[Tuple[int, int]] = set()
    for _area in require_key(game_state, "terrain_areas"):
        for _h in require_key(_area, "hexes"):
            terrain_hex_set.add((int(_h[0]), int(_h[1])))

    sc, sr = int(shooter_col), int(shooter_row)
    from engine.hex_utils import Socle, is_phantom_bottom_hex
    from engine.combat_utils import ranged_edge_distance_to_cell
    _preview_metric = _ranged_distance_metric(game_state)
    _preview_socle = Socle(
        unit["BASE_SHAPE"], unit["BASE_SIZE"], sc, sr,
        {(int(c), int(r)) for c, r in _shooter_hexes},
    )
    _preview_anchor_proj, _preview_proj_cache = _build_shooter_proj_cache((sc, sr), _shooter_hexes)
    attack_cells: List[Dict[str, int]] = []
    cover_cells: List[Dict[str, int]] = []
    ratio_by_hex: Dict[str, float] = {}

    for col in range(board_cols):
        for row in range(board_rows):
            if is_phantom_bottom_hex(col, row, board_rows):
                continue
            distance = ranged_edge_distance_to_cell(_preview_socle, sc, sr, col, row, _preview_metric)
            if distance <= 0 or distance > max_range:
                continue
            hex_area = obscuring_by_hex.get((col, row))
            _excluded_areas = frozenset((hex_area,)) if hex_area is not None else frozenset()
            # Même primitive que le ciblage → ancre + vantages latéraux (peek de coin).
            visible = _los_hex_visible(
                (sc, sr), _shooter_hexes, col, row, wall_set, obscuring_by_hex, _excluded_areas,
                _shooter_proj_cache=_preview_proj_cache, _shooter_anchor_proj=_preview_anchor_proj,
            )
            ratio_by_hex[f"{col},{row}"] = 1.0 if visible else 0.0
            if not visible:
                continue
            if (col, row) in terrain_hex_set:
                cover_cells.append({"col": int(col), "row": int(row)})
            else:
                attack_cells.append({"col": int(col), "row": int(row)})

    unit["los_preview_attack_cells"] = attack_cells
    unit["los_preview_cover_cells"] = cover_cells
    unit["los_preview_ratio_by_hex"] = ratio_by_hex


def _get_accurate_hex_line(start_col: int, start_row: int, end_col: int, end_row: int) -> List[Tuple[int, int]]:
    """Accurate hex line using cube coordinates."""
    start_cube = _offset_to_cube(start_col, start_row)
    end_cube = _offset_to_cube(end_col, end_row)
    
    distance = max(abs(start_cube.x - end_cube.x), abs(start_cube.y - end_cube.y), abs(start_cube.z - end_cube.z))
    path = []
    
    for i in range(distance + 1):
        t = i / distance if distance > 0 else 0
        
        cube_x = start_cube.x + t * (end_cube.x - start_cube.x)
        cube_y = start_cube.y + t * (end_cube.y - start_cube.y)
        cube_z = start_cube.z + t * (end_cube.z - start_cube.z)
        
        rounded_cube = _cube_round(cube_x, cube_y, cube_z)
        offset_col, offset_row = _cube_to_offset(rounded_cube)
        path.append((offset_col, offset_row))
    
    return path

class CubeCoordinate:
    def __init__(self, x: int, y: int, z: int):
        self.x = x
        self.y = y
        self.z = z


def _offset_to_cube(col: int, row: int) -> CubeCoordinate:
    x = col
    z = row - (col - (col & 1)) // 2
    y = -x - z
    return CubeCoordinate(x, y, z)


def _cube_to_offset(cube: CubeCoordinate) -> Tuple[int, int]:
    col = cube.x
    row = cube.z + (cube.x - (cube.x & 1)) // 2
    return col, row


def _cube_round(x: float, y: float, z: float) -> CubeCoordinate:
    rx = round(x)
    ry = round(y)
    rz = round(z)
    
    x_diff = abs(rx - x)
    y_diff = abs(ry - y)
    z_diff = abs(rz - z)
    
    if x_diff > y_diff and x_diff > z_diff:
        rx = -ry - rz
    elif y_diff > z_diff:
        ry = -rx - rz
    else:
        rz = -rx - ry
    
    return CubeCoordinate(rx, ry, rz)

def _shooting_phase_complete(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complete shooting phase with player progression and turn management
    """
    # CRITICAL: Include all_attack_results if attacks were executed before phase completion
    # This ensures attacks already executed are logged to step.log
    shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
    
    # Final cleanup
    from engine.game_utils import add_debug_file_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    shoot_pool = require_key(game_state, "shoot_activation_pool")
    add_debug_file_log(game_state, f"[POOL PRE-TRANSITION] E{episode} T{turn} shoot shoot_activation_pool={shoot_pool}")
    game_state["shoot_activation_pool"] = []

    # Purge de securite : une declaration de tir ne survit jamais a sa phase. Le joueur
    # peut legitimement laisser une ou plusieurs activations en plan (il compare les
    # cibles de plusieurs unites puis passe a autre chose) : ce n est pas une anomalie,
    # mais ces pendings poisonneraient la phase de tir du tour suivant
    # (assert_no_pending_shoot_intent). On ne leve donc PAS, on nettoie.
    if "pending_squad_shoot_intents" in game_state:
        game_state["pending_squad_shoot_intents"] = {}
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]

    # PERFORMANCE: Clear LoS cache at phase end (will rebuild next shooting phase)
    if "los_cache" in game_state:
        game_state["los_cache"] = {}
    
    # Console log
    from engine.game_utils import add_console_log, add_debug_log
    add_console_log(game_state, "SHOOTING PHASE COMPLETE")
    
    # Base result with all_attack_results if present
    base_result = {}
    if shoot_attack_results:
        base_result["all_attack_results"] = list(shoot_attack_results)
    
    # Player progression logic
    if game_state["current_player"] == 1:
        # tour_de_jeu.md Line 105: P1 Move -> P1 Shoot -> P1 Charge -> P1 Fight
        # Player stays 1, advance to charge phase
        return {
            **base_result,
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "charge",
            "current_player": 1,
            # Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
            # Add missing frontend cleanup signals
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    elif game_state["current_player"] == 2:
        # tour_de_jeu.md Line 105: P2 Move -> P2 Shoot -> P2 Charge -> P2 Fight
        # Player stays 2, advance to charge phase
        # Turn increment happens at P2 Fight end (fight_handlers.py:797)
        return {
            **base_result,
            "phase_complete": True,
            "phase_transition": True,
            "next_phase": "charge",
            "current_player": 2,
            # Direct field access
            "units_processed": len(game_state["units_shot"] if "units_shot" in game_state else set()),
            # Add missing frontend cleanup signals
            "clear_blinking_gentle": True,
            "reset_mode": "select",
            "clear_selected_unit": True,
            "clear_attack_preview": True
        }
    raise ValueError(f"Invalid current_player: {game_state['current_player']!r}")

def shooting_phase_end(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy function - redirects to new complete function"""
    return _shooting_phase_complete(game_state)

def shooting_clear_activation_state(game_state: Dict[str, Any], unit: Dict[str, Any]) -> None:
    """Clear shooting activation state (equivalent to movement_clear_preview in MOVE phase).
    
    This function clears:
    - active_shooting_unit
    - unit's valid_target_pool
    - unit's TOTAL_ATTACK_LOG
    - unit's selected_target_id
    - unit's activation_position
    - unit's _shooting_with_close_quarters
    - unit's SHOOT_LEFT (reset to 0)
    
    Called BEFORE end_activation to clean up state, exactly like movement_clear_preview in MOVE.
    
    CRITICAL: Only called when arg5=1 (actually ending activation).
    If arg5=0 (NOT_REMOVED), state is preserved to continue activation.
    """
    # Clear active unit only if it's THIS unit — a skip/end of a different unit must not
    # evict the manual squad-shoot activation in progress (PvP: active_shooting_unit tracks
    # the unit whose pending_squad_shoot_intents are live; clearing it for a different unit
    # leaves the pending entry orphaned and causes assert_no_pending_shoot_intent to raise).
    unit_id = str(require_key(unit, "id"))
    if str(game_state.get("active_shooting_unit", "")) == unit_id:
        del game_state["active_shooting_unit"]

    # Clear unit activation state
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    if "_pool_from_cache" in unit:
        del unit["_pool_from_cache"]
    if "_pool_cache_key" in unit:
        del unit["_pool_cache_key"]
    # tour_de_jeu.md: Clean up los_cache at end of activation
    if "los_cache" in unit:
        del unit["los_cache"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]
    if "_shooting_with_close_quarters" in unit:
        del unit["_shooting_with_close_quarters"]
    if "_manual_weapon_selected" in unit:
        del unit["_manual_weapon_selected"]
    if "manualWeaponSelected" in unit:
        del unit["manualWeaponSelected"]
    if "_shoot_activation_started" in unit:
        del unit["_shoot_activation_started"]
    _clear_shoot_activation_weapon_reuse_cache(unit)
    if "_pending_move_after_shooting" in unit:
        del unit["_pending_move_after_shooting"]
    if "_move_after_shooting_destinations" in unit:
        del unit["_move_after_shooting_destinations"]
    if "_move_after_shooting_resolved" in unit:
        del unit["_move_after_shooting_resolved"]
    if "_move_after_shooting_distance" in unit:
        del unit["_move_after_shooting_distance"]
    if "_last_shoot_target_id" in unit:
        del unit["_last_shoot_target_id"]
    if "_current_shoot_nb" in unit:
        del unit["_current_shoot_nb"]
    if "advance_range" in unit:
        del unit["advance_range"]
    unit["SHOOT_LEFT"] = 0

def _build_move_after_shooting_destinations(
    game_state: Dict[str, Any], unit: Dict[str, Any], move_distance: int
) -> List[Tuple[int, int]]:
    """Build legal destinations for move_after_shooting (normal move up to rule distance)."""
    from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool

    unit_id = require_key(unit, "id")
    unit_col, unit_row = require_unit_position(unit, game_state)
    original_move = require_key(unit, "MOVE")
    unit["MOVE"] = move_distance
    try:
        valid_destinations = movement_build_valid_destinations_pool(game_state, unit_id)
    finally:
        unit["MOVE"] = original_move

    return [
        (int(col), int(row))
        for (col, row) in valid_destinations
        if int(col) != int(unit_col) or int(row) != int(unit_row)
    ]


def _select_move_after_shooting_destination_for_ai(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    destinations: List[Tuple[int, int]],
) -> Tuple[int, int]:
    """Select one post-shoot move destination for gym/PvE automation."""
    units_cache = require_key(game_state, "units_cache")
    unit_player = int(require_key(unit, "player"))
    # Hors table (réserves 20.01) écarté par l'énumérateur : sans ce filtre,
    # `socle_from_cache_entry` placerait l'ennemi sur la sentinelle (-1,-1) et le « plus proche
    # ennemi » serait un fantôme. C'était le quatrième correctif par-site du chantier 04c.
    enemies = [
        enemy_id
        for enemy_id, _cache_entry in enemy_entries_on_battlefield(units_cache, unit_player)
    ]
    if not enemies:
        return destinations[0]

    # Portée/positionnement post-tir en euclidien bord-à-bord (sélecteur `ranged`).
    from engine.combat_utils import (
        ranged_edge_distance,
        ranged_edge_distance_to_cell,
        socle_from_cache_entry,
    )
    metric = _ranged_distance_metric(game_state)
    unit_socle = socle_from_cache_entry(units_cache[str(unit["id"])])
    nearest_enemy_id = min(
        enemies,
        key=lambda enemy_id: ranged_edge_distance(
            unit_socle, socle_from_cache_entry(units_cache[str(enemy_id)]), metric
        ),
    )
    nearest_enemy_socle = socle_from_cache_entry(units_cache[str(nearest_enemy_id)])
    nearest_enemy_col, nearest_enemy_row = require_unit_position(nearest_enemy_id, game_state)
    return min(
        destinations,
        key=lambda destination: ranged_edge_distance_to_cell(
            nearest_enemy_socle,
            nearest_enemy_col,
            nearest_enemy_row,
            int(destination[0]),
            int(destination[1]),
            metric,
        ),
    )


def _apply_move_after_shooting(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    dest_col: int,
    dest_row: int,
    move_distance: int,
) -> Dict[str, Any]:
    """Apply move_after_shooting movement and refresh positional caches."""
    from .movement_handlers import _invalidate_all_destination_pools_after_movement

    unit_id_str = str(require_key(unit, "id"))
    orig_col, orig_row = require_unit_position(unit, game_state)
    dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)
    if dest_col_int == orig_col and dest_row_int == orig_row:
        raise ValueError("move_after_shooting destination must differ from current position")

    old_cache_entry = require_key(game_state, "units_cache").get(unit_id_str)
    old_occupied = old_cache_entry.get("occupied_hexes") if old_cache_entry else None

    set_unit_coordinates(unit, dest_col_int, dest_row_int)
    # DÉPLACEMENT RIGIDE de l'escouade, pas un simple recalage d'ancre. `move_after_shooting`
    # est nommément listé par la docstring de `translate_squad_to_destination` comme l'un de ses
    # clients ; `update_units_cache_position`, elle, ne bouge QUE l'ancre — « à ne pas confondre »,
    # dit la même docstring. Sur une escouade multi-figurines (Gargoyle, la seule porteuse de la
    # capacité) l'ancre partait à destination et les figurines restaient sur place.
    translate_squad_to_destination(game_state, unit_id_str, dest_col_int, dest_row_int)

    new_cache_entry = require_key(game_state, "units_cache").get(unit_id_str)
    new_occupied = new_cache_entry.get("occupied_hexes") if new_cache_entry else None

    moved_unit_player = int(require_key(unit, "player"))
    update_enemy_adjacent_caches_after_unit_move(
        game_state,
        moved_unit_player=moved_unit_player,
        old_col=orig_col,
        old_row=orig_row,
        new_col=dest_col_int,
        new_row=dest_row_int,
        old_occupied=old_occupied,
        new_occupied=new_occupied,
    )
    # LoS : invalidation ciblée + bump émis par translate_squad_to_destination (ci-dessus, dest) →
    # _touch_unit_los (choke-point a′). build_unit_los_cache reconstruit le los_cache local ensuite.
    build_unit_los_cache(game_state, unit_id_str)
    _invalidate_all_destination_pools_after_movement(game_state)
    maybe_resolve_reactive_move(
        game_state=game_state,
        moved_unit_id=unit_id_str,
        from_col=orig_col,
        from_row=orig_row,
        to_col=dest_col_int,
        to_row=dest_row_int,
        move_kind="move",
        move_cause="normal",
    )
    require_key(game_state, "units_cannot_charge").add(unit_id_str)

    source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
        unit, "move_after_shooting"
    )
    if not isinstance(source_rule_display_name, str) or not source_rule_display_name.strip():
        raise ValueError(
            f"move_after_shooting source rule display name is required for unit {unit_id_str}"
        )
    source_rule_id = _get_source_unit_rule_id_for_effect(unit, "move_after_shooting")
    if not isinstance(source_rule_id, str) or not source_rule_id.strip():
        raise ValueError(
            f"move_after_shooting source rule id is required for unit {unit_id_str}"
        )
    append_action_log(
        game_state,
        {
            "type": "move_after_shooting",
            "turn": game_state.get("turn", 1),
            "phase": "shoot",
            "unitId": unit_id_str,
            "player": require_key(unit, "player"),
            "fromCol": orig_col,
            "fromRow": orig_row,
            "toCol": dest_col_int,
            "toRow": dest_row_int,
            "move_distance": move_distance,
            "ability_display_name": source_rule_display_name.strip(),
            "source_rule_id": source_rule_id.strip(),
            "timestamp": "server_time",
        },
    )
    return {
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col_int,
        "toRow": dest_row_int,
        "move_distance": move_distance,
        "ability_display_name": source_rule_display_name.strip(),
        "source_rule_id": source_rule_id.strip(),
    }

def _handle_shooting_end_activation(game_state: Dict[str, Any], unit: Dict[str, Any],
                                     arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1,
                                     action_type: Optional[str] = None, include_attack_results: bool = True,
                                     skip_reason: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    """Handle shooting activation end using end_activation (aligned with MOVE phase).
    
    This function:
    1. Clears activation state BEFORE end_activation (like movement_clear_preview in MOVE)
    2. Calls end_activation (which removes from pool and checks if pool empty)
    3. Preserves all_attack_results if needed (for logging before phase transition)
    
    CRITICAL: phase_complete is now handled in _process_shooting_phase (like MOVE), not here.
    
    Args:
        arg1: ACTION/WAIT/PASS - logging behavior
        arg2: 1/0 - step increment
        arg3: SHOOTING/ADVANCE/PASS - tracking sets
        arg4: SHOOTING - pool removal phase
        arg5: 1/0 - error logging (1=remove from pool, 0=NOT_REMOVED)
        action_type: Optional action type for result dict (defaults to inferred from arg1)
        include_attack_results: Whether to include shoot_attack_results in response
    
    Returns:
        Tuple[bool, Dict] - (success, result) where result may contain phase_complete (but not next_phase)
    """
    from engine.phase_handlers.generic_handlers import end_activation

    # Primitive F (chantier 06, passe 6) — suppress_target_on_shooting (Indiscriminate Detonations).
    # Déclenché après une vraie activation de tir : l'unité cible est supprimée jusqu'au début de
    # la prochaine phase de commandement du tireur. La cible est le `priority_target_squad_id`
    # mémorisé dans `_last_shoot_target_id` par squad_declare_shoot (shared_utils).
    if (
        arg5 == 1
        and arg1 == ACTION
        and arg3 in (SHOOTING, ADVANCE)
        and _unit_has_rule(unit, "suppress_target_on_shooting")
    ):
        _suppress_target_id = unit.get("_last_shoot_target_id")
        if _suppress_target_id is not None:
            _suppressor_player = int(require_key(unit, "player"))
            game_state.setdefault("suppressed_squads", {})[str(_suppress_target_id)] = _suppressor_player

    # Optional post-shoot movement rule: move_after_shooting.
    # Only relevant when a real shooting activation is ending.
    from engine.phase_handlers.movement_handlers import unit_ingress_move_locked

    if (
        arg5 == 1
        and arg1 == ACTION
        and arg3 == SHOOTING
        and not unit.get("_move_after_shooting_resolved", False)
        and _unit_has_rule(unit, "move_after_shooting")
        # 20.04 AFTER MOVING — « your unit is not eligible to make any OTHER TYPE of move »
        # jusqu'au début de la phase de charge. Le move_after_shooting en est un : une escouade
        # arrivée de réserves ce tour-ci ne le fait pas.
        and not unit_ingress_move_locked(game_state, str(require_key(unit, "id")))
    ):
        move_after_shooting_distance = _resolve_move_after_shooting_distance(unit)
        if not _is_adjacent_to_enemy_within_cc_range(game_state, unit):
            destinations = _build_move_after_shooting_destinations(
                game_state, unit, move_after_shooting_distance
            )
            if destinations:
                cfg = require_key(game_state, "config")
                is_gym_training = bool(cfg.get("gym_training_mode", False) or game_state.get("gym_training_mode", False))
                is_pve_ai = bool(cfg.get("pve_mode", False)) and int(require_key(unit, "player")) == 2
                if is_gym_training or is_pve_ai:
                    chosen_destination = _select_move_after_shooting_destination_for_ai(
                        game_state, unit, destinations
                    )
                    move_result = _apply_move_after_shooting(
                        game_state,
                        unit,
                        int(chosen_destination[0]),
                        int(chosen_destination[1]),
                        move_after_shooting_distance,
                    )
                    unit["_move_after_shooting_resolved"] = True
                    game_state["last_move_after_shooting"] = move_result
                else:
                    unit["_pending_move_after_shooting"] = True
                    unit["_move_after_shooting_destinations"] = destinations
                    unit["_move_after_shooting_distance"] = move_after_shooting_distance
                    game_state["active_shooting_unit"] = require_key(unit, "id")
                    return True, {
                        "waiting_for_player": True,
                        "action": "move_after_shooting_select_destination",
                        "unitId": require_key(unit, "id"),
                        "move_after_shooting_destinations": [
                            {"col": int(col), "row": int(row)} for (col, row) in destinations
                        ],
                        "highlight_color": "orange",
                        "can_skip_move_after_shooting": True,
                    }
        unit["_move_after_shooting_resolved"] = True
    
    # CRITICAL: Only clear state if actually ending activation (arg5=1)
    # If arg5=0 (NOT_REMOVED), we continue activation, so keep state intact
    if arg5 == 1:
        shooting_clear_activation_state(game_state, unit)
    
    # Call end_activation (exactly like MOVE phase)
    result = end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)
    
    # Aucune auto-activation de la suivante : le successeur est choisi par l'agent
    # (V11 §0.48 L2, `ACTIVATE_SLOT`) ou cliqué par le joueur.

    # CRITICAL: Pool empty detection is handled in execute_action (like MOVE phase)
    # This prevents double call to _shooting_phase_complete (once here, once in _process_shooting_phase)
    # execute_action checks pool empty BEFORE processing action, so phase_complete is handled there
    
    # Determine action type for result
    if action_type is None:
        if arg1 == "PASS":
            action_type = "skip"
        elif arg1 == "WAIT":
            action_type = "wait"
        elif arg1 == "ACTION":
            action_type = "shoot"
        else:
            action_type = "shoot"

    # L24 — producteur skip shoot : aucune cible valide ou pas d'arme utilisable.
    # La raison précise est fournie par le caller via `skip_reason` ; elle est incluse dans
    # l'action_log si non-None (consommée par le formateur StepLogger).
    if action_type == "skip":
        _skip_col, _skip_row = require_unit_position(unit, game_state)
        _skip_entry: Dict[str, Any] = {
            "type": "skip",
            "turn": game_state["turn"],
            "phase": game_state.get("phase", "shoot"),
            "unitId": unit["id"],
            "player": require_key(unit, "player"),
            "col": _skip_col,
            "row": _skip_row,
        }
        if skip_reason is not None:
            _skip_entry["skipReason"] = skip_reason
        append_action_log(game_state, _skip_entry)

    # Update result with action type and activation_complete (like _handle_skip_action in MOVE)
    result.update({
        "action": action_type,
        "unitId": unit["id"],
        "activation_complete": True,
        "phase": "shoot",
    })
    # Backend is source of truth: when activation really ends and no next unit is auto-activated,
    # explicitly instruct frontend to return to neutral select state.
    if arg5 == 1 and "active_shooting_unit" not in game_state:
        result["reset_mode"] = "select"
        result["clear_selected_unit"] = True
    # Align with fight phase: ensure waiting_for_player is explicit for shoot logging
    if action_type == "shoot" and "waiting_for_player" not in result:
        result["waiting_for_player"] = False
    
    # Include attack results if needed (for cases where attacks were executed before ending)
    # CRITICAL: This must be done BEFORE phase transition to ensure logging
    if include_attack_results:
        shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
        if shoot_attack_results:
            result["all_attack_results"] = list(shoot_attack_results)
            game_state["shoot_attack_results"] = []
            if action_type != "shoot":
                action_type = "shoot"
                result["action"] = action_type
                if "waiting_for_player" not in result:
                    result["waiting_for_player"] = False

    move_after_shooting_result = game_state.get("last_move_after_shooting")
    if isinstance(move_after_shooting_result, dict):
        result.update(move_after_shooting_result)
        del game_state["last_move_after_shooting"]
    
    return True, result

def _handle_move_after_shooting_action(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    action: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """Resolve optional move_after_shooting player choice, then end activation."""
    del config  # Handler uses game_state/config already embedded.
    if not unit.get("_pending_move_after_shooting", False):
        return False, {"error": "no_pending_move_after_shooting", "unitId": require_key(unit, "id")}

    unit_id_str = str(require_key(unit, "id"))
    destinations = require_key(unit, "_move_after_shooting_destinations")
    normalized_destinations = {(int(col), int(row)) for (col, row) in destinations}

    move_payload: Dict[str, Any] = {}
    skip_move = bool(action.get("skip_move_after_shooting", False))
    dest_col_raw = action.get("destCol")
    dest_row_raw = action.get("destRow")

    if not skip_move and dest_col_raw is not None and dest_row_raw is not None:
        dest_col_int, dest_row_int = normalize_coordinates(dest_col_raw, dest_row_raw)
        if (dest_col_int, dest_row_int) not in normalized_destinations:
            return False, {
                "error": "invalid_move_after_shooting_destination",
                "unitId": unit_id_str,
                "destination": (dest_col_int, dest_row_int),
            }
        move_after_shooting_distance = require_key(unit, "_move_after_shooting_distance")
        if not isinstance(move_after_shooting_distance, int) or move_after_shooting_distance <= 0:
            raise ValueError(
                f"_move_after_shooting_distance must be positive int for unit {require_key(unit, 'id')}, "
                f"got {move_after_shooting_distance!r}"
            )
        move_payload = _apply_move_after_shooting(
            game_state,
            unit,
            dest_col_int,
            dest_row_int,
            move_after_shooting_distance,
        )

    unit["_move_after_shooting_resolved"] = True
    if "_pending_move_after_shooting" in unit:
        del unit["_pending_move_after_shooting"]
    if "_move_after_shooting_destinations" in unit:
        del unit["_move_after_shooting_destinations"]
    if "_move_after_shooting_distance" in unit:
        del unit["_move_after_shooting_distance"]

    success, result = _handle_shooting_end_activation(
        game_state,
        unit,
        ACTION,
        1,
        SHOOTING,
        SHOOTING,
        1,
        action_type="shoot",
        include_attack_results=True,
    )
    result.update(move_payload)
    return success, result


def execute_action(game_state: Dict[str, Any], unit: Optional[Dict[str, Any]], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md EXACT: Complete action routing with full phase lifecycle management
    """
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    # Handler self-initialization (aligned with MOVE phase)
    game_state_phase = game_state["phase"] if "phase" in game_state else None
    shoot_pool_exists = "shoot_activation_pool" in game_state
    if game_state_phase == "shoot" and not shoot_pool_exists and action_type == "advance_phase":
        game_state["_shooting_phase_initialized"] = False
        return True, _shooting_phase_complete(game_state)
    if game_state_phase != "shoot" or not shoot_pool_exists:
        phase_init_result = shooting_phase_start(game_state)
        if phase_init_result.get("phase_complete"):
            return True, phase_init_result
    
    if "unitId" not in action:
        unit_id = "none"  # Allow missing for some action types
    else:
        unit_id = action["unitId"]
    # tour_de_jeu.md COMPLIANCE: Pool is built once at phase start (STEP 1: ELIGIBILITY CHECK)
    # Units are removed ONLY via:
    # 1. end_activation() with Arg4 = SHOOTING (when unit finishes activation)
    # 2. _remove_dead_unit_from_pools() (when unit dies)
    # No filtering or modification of pool in execute_action - this is not described in tour_de_jeu.md
    
    # Check if shooting phase should complete - read directly from game_state (not cached)
    # CRITICAL: Read pool directly to get current state (pool may have been modified by previous actions)
    current_pool = require_key(game_state, "shoot_activation_pool")
    if not current_pool:
        game_state["_shooting_phase_initialized"] = False
        return True, _shooting_phase_complete(game_state)
    
    # Extract unit from action if not provided (engine passes None now)
    if unit is None:
        if "unitId" not in action:
            return False, {"error": "semantic_action_required", "action": action}
        
        unit_id = str(action["unitId"])
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found", "unitId": unit_id}
    
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
    # CRITICAL: Normalize unit_id to string for consistent comparison with pool (which may contain int or string IDs)
    unit_id = str(unit["id"])
    unit_id_str = str(unit_id)

    # Direct field access
    if "action" not in action:
        raise KeyError(f"Action missing required 'action' field: {action}")
    action_type = action["action"]
    
    # CRITICAL FIX: Auto-activate unit if not already activated (aligned with MOVE phase)
    # This prevents get_action_mask from reactivating units before end_activation removes them from pool
    # Auto-activation is now done in execute_action (like MOVE) instead of get_action_mask
    active_shooting_unit = game_state.get("active_shooting_unit")
    is_gym_training = config.get("gym_training_mode", False) or game_state.get("gym_training_mode", False)
    current_player = require_key(game_state, "current_player")
    is_learning_agent_turn = current_player == 1

    def _assert_gym_waiting_state_is_actionable(result_payload: Dict[str, Any]) -> None:
        """
        In gym mode, waiting_for_player must expose a directly executable gym choice.
        Otherwise, it creates an unrecoverable loop (no matching action in ActionDecoder).
        """
        if not is_gym_training:
            return
        if not result_payload.get("waiting_for_player"):
            return

        has_target_choices = (
            isinstance(result_payload.get("valid_targets"), list)
            and len(result_payload["valid_targets"]) > 0
        ) or (
            isinstance(result_payload.get("blinking_units"), list)
            and len(result_payload["blinking_units"]) > 0
        )
        requires_manual_weapon_selection = bool(result_payload.get("weapon_selection_required"))

        if requires_manual_weapon_selection or not has_target_choices:
            shoot_pool = require_key(game_state, "shoot_activation_pool")
            shoot_pool_head = [str(uid) for uid in shoot_pool[:3]]
            units_advanced = require_key(game_state, "units_advanced")
            active_unit_name = unit.get("name") or unit.get("unitType") or "unknown"
            selected_weapon_idx = unit.get("selectedRngWeaponIndex")
            selected_weapon_name = None
            selected_weapon_rules = None
            selected_weapon_shot = None
            if isinstance(selected_weapon_idx, int):
                rng_weapons = require_key(unit, "RNG_WEAPONS")
                if 0 <= selected_weapon_idx < len(rng_weapons):
                    selected_weapon = rng_weapons[selected_weapon_idx]
                    selected_weapon_name = selected_weapon.get("display_name")
                    selected_weapon_rules = selected_weapon.get("WEAPON_RULES")
                    selected_weapon_shot = selected_weapon.get("shot")
            valid_targets = result_payload.get("valid_targets")
            blinking_units = result_payload.get("blinking_units")
            valid_targets_count = len(valid_targets) if isinstance(valid_targets, list) else 0
            blinking_units_count = len(blinking_units) if isinstance(blinking_units, list) else 0
            first_valid_targets = valid_targets[:3] if isinstance(valid_targets, list) else []
            first_blinking_units = blinking_units[:3] if isinstance(blinking_units, list) else []
            raise RuntimeError(
                "Non-actionable waiting_for_player in gym shooting flow: "
                f"episode={game_state.get('episode_number')}, "
                f"turn={game_state.get('turn')}, "
                f"phase={game_state.get('phase')}, "
                f"current_player={game_state.get('current_player')}, "
                f"unit_id={unit_id_str}, unit_name={active_unit_name}, "
                f"unit_player={unit.get('player')}, "
                f"active_shooting_unit={game_state.get('active_shooting_unit')}, "
                f"action_type={action_type}, "
                f"result_action={result_payload.get('action')}, "
                f"context={result_payload.get('context')}, "
                f"waiting_for_player={result_payload.get('waiting_for_player')}, "
                f"weapon_selection_required={requires_manual_weapon_selection}, "
                f"valid_targets_count={valid_targets_count}, "
                f"first_valid_targets={first_valid_targets}, "
                f"blinking_units_count={blinking_units_count}, "
                f"first_blinking_units={first_blinking_units}, "
                f"shoot_left={unit.get('SHOOT_LEFT')}, "
                f"current_shoot_nb={unit.get('_current_shoot_nb')}, "
                f"selected_rng_weapon_index={selected_weapon_idx}, "
                f"selected_weapon_name={selected_weapon_name}, "
                f"selected_weapon_rules={selected_weapon_rules}, "
                f"selected_weapon_shot={selected_weapon_shot}, "
                f"unit_can_shoot={unit.get('_can_shoot')}, "
                f"unit_advanced={unit_id_str in units_advanced}, "
                f"shoot_pool_size={len(shoot_pool)}, "
                f"shoot_pool_head={shoot_pool_head}, "
                f"player_types={game_state.get('player_types')}"
            )

    def _enforce_active_shooting_unit_for_waiting_targets(result_payload: Dict[str, Any]) -> None:
        """
        Backend contract: whenever shooting waits for a human target selection with blinking targets,
        game_state must expose active_shooting_unit for the same unit.
        """
        if not result_payload.get("waiting_for_player"):
            return
        if result_payload.get("start_blinking") is not True:
            return
        blinking_units = result_payload.get("blinking_units")
        if not isinstance(blinking_units, list) or len(blinking_units) == 0:
            return
        game_state["active_shooting_unit"] = unit_id
    
    # STRICT AI_TURN: shoot/advance must ALWAYS follow activation start
    # No shooting/advance allowed for a different unit while one is active
    if action_type in ["shoot", "move_after_shooting"]:
        unit_id_str = str(unit_id)
        active_unit_id = str(active_shooting_unit) if active_shooting_unit is not None else None
        if active_unit_id and active_unit_id != unit_id_str:
            raise ValueError(
                f"shoot/move_after_shooting called for non-active unit: "
                f"active_shooting_unit={active_unit_id} unit_id={unit_id_str}"
            )
        if not unit.get("_shoot_activation_started", False):
            # Verify unit is still in pool before activation (defense in depth)
            pool_ids = [str(uid) for uid in require_key(game_state, "shoot_activation_pool")]
            if unit_id_str not in pool_ids:
                return False, {"error": "unit_not_eligible", "unitId": unit_id}
            if action_type != "move_after_shooting":
                activation_result = shooting_unit_activation_start(game_state, unit_id)
                if activation_result.get("error"):
                    return False, activation_result
                if (activation_result.get("empty_target_pool")
                        or activation_result.get("skip_reason")):
                    return True, activation_result
    
    # CRITICAL FIX: Validate unit is current player's unit to prevent self-targeting
    # CRITICAL: Normalize player values to int for consistent comparison (handles int/string mismatches)
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    current_player_int = int(game_state["current_player"]) if game_state["current_player"] is not None else None
    if unit_player != current_player_int:
        return False, {"error": "wrong_player_unit", "unitId": unit_id, "unit_player": unit["player"], "current_player": game_state["current_player"]}
    
    # Handler validates unit eligibility for all actions
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
    # Pool always contains string IDs (normalized at creation), so direct comparison is safe
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    unit_id_str = str(unit_id)
    pool_ids = [str(uid) for uid in game_state["shoot_activation_pool"]]
    if action_type != "select_weapon" and unit_id_str not in pool_ids:
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    # select_weapon can reactivate unit after weapon exhaustion (unit must have been eligible before)
    
    # AI_SHOOT.md action routing
    if action_type == "activate_unit":
        raise RuntimeError(
            f"activate_unit reached in execute_action — squad path expected. "
            f"unit_id={unit_id_str} episode={game_state.get('episode_number')} turn={game_state.get('turn')}"
        )

    elif action_type == "shoot":
        raise RuntimeError(
            f"shoot reached in execute_action — squad path expected. "
            f"unit_id={unit_id_str} episode={game_state.get('episode_number')} turn={game_state.get('turn')}"
        )

    elif action_type == "move_after_shooting":
        return _handle_move_after_shooting_action(game_state, unit, action, config)
    
    elif action_type == "select_weapon":
        raise RuntimeError(
            f"select_weapon reached in execute_action — squad_select_weapon expected. "
            f"unit_id={unit_id_str} episode={game_state.get('episode_number')} turn={game_state.get('turn')}"
        )

    elif action_type == "skip" and action.get("manual_end_phase"):
        # Fin de phase manuelle (API) : forfait sans enchaîner move_after_shooting (évite un BFS move
        # par unité ayant déjà tiré). Le ``skip`` UI / RL reste sur la branche wait|skip ci-dessous.
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["skip_reason"] = "manual_end_phase"
        pool_after_removal = require_key(game_state, "shoot_activation_pool")
        if not pool_after_removal:
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        return success, result

    elif action_type == "wait" or action_type == "skip":
        # tour_de_jeu.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        # EXACT COMPLIANCE: Same logic as right_click action (lines 2453-2468)
        has_shot = _unit_has_shot_with_any_weapon(unit)
        unit_id_str = str(unit["id"])
        if has_shot:
            # YES -> end_activation(ACTION, 1, SHOOTING, SHOOTING, 1)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # Check if unit has advanced or is cancelling an advance selection.
            has_advanced = _shooting_activation_has_started_or_completed_advance(game_state, unit)
            if has_advanced:
                # NO -> Unit has not shot yet (only advanced) -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1)
            else:
                # NO -> end_activation(WAIT, 1, 0, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # tour_de_jeu.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # tour_de_jeu.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to tour_de_jeu.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = require_key(game_state, "shoot_activation_pool")
        if not pool_after_removal:
            # Pool is empty - phase is complete (tour_de_jeu.md LINE 794: "NO → End of shooting phase")
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        
        return success, result
    
    elif action_type == "left_click":
        raise RuntimeError(
            f"left_click reached in execute_action — squad path expected. "
            f"unit_id={unit_id_str} episode={game_state.get('episode_number')} turn={game_state.get('turn')}"
        )
    
    elif action_type == "right_click":
        # tour_de_jeu.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        has_shot = _unit_has_shot_with_any_weapon(unit)
        unit_id_str = str(unit["id"])
        if has_shot:
            # YES -> end_activation(ACTION, 1, SHOOTING, SHOOTING, 1)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # Check if unit has advanced or is cancelling an advance selection.
            has_advanced = _shooting_activation_has_started_or_completed_advance(game_state, unit)
            if has_advanced:
                # NO -> Unit has not shot yet (only advanced) -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1)
            else:
                # NO -> end_activation(WAIT, 1, 0, SHOOTING, 1)
                success, result = _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # tour_de_jeu.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # tour_de_jeu.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to tour_de_jeu.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = require_key(game_state, "shoot_activation_pool")
        if not pool_after_removal:
            # Pool is empty - phase is complete (tour_de_jeu.md LINE 794: "NO → End of shooting phase")
            game_state["_shooting_phase_initialized"] = False
            phase_complete_result = _shooting_phase_complete(game_state)
            result.update(phase_complete_result)
            if "active_shooting_unit" in game_state:
                del game_state["active_shooting_unit"]
        
        return success, result
    
    elif action_type == "invalid":
        raise RuntimeError(
            f"invalid reached in execute_action — squad path expected. "
            f"unit_id={unit_id_str} episode={game_state.get('episode_number')} turn={game_state.get('turn')}"
        )
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


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

def _unit_has_shot_with_any_weapon(unit: Dict[str, Any]) -> bool:
    """
    Check if unit has already fired at least one ranged attack in current activation.

    Semantique stricte : vrai des qu une arme est marquee epuisee (`weapon["shot"] == 1`).

    Avant V11 §0.38 cette fonction lisait d abord `unit["_rapid_fire_shots_fired"]`, un
    compteur que rien n incrementait jamais (il n etait qu initialise a 0) : la branche etait
    morte et masquait le seul critere reel, l epuisement de l arme.
    """
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    for weapon in rng_weapons:
        if require_key(weapon, "shot") == 1:
            return True
    return False


def _shooting_activation_has_started_or_completed_advance(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
) -> bool:
    """
    True from the advance roll until the shooting activation is closed.
    Cancelling destination selection still consumes the advance action.
    """
    unit_id_str = str(require_key(unit, "id"))
    if unit_id_str in require_key(game_state, "units_advanced"):
        return True
    return "advance_range" in unit and unit["advance_range"] is not None


def _is_adjacent_to_enemy_within_cc_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    Check if unit is engaged (within engagement zone of any enemy).

    Uses min distance between footprints (§3.3, §9.8) for multi-hex units.
    Always uses fresh positions from units_cache.
    """
    from engine.spatial_relations import get_engagement_zone
    from engine.spatial_relations import unit_within_engagement_zone_footprints

    cc_range = get_engagement_zone(game_state)
    return unit_within_engagement_zone_footprints(
        game_state, unit, engagement_zone=cc_range, max_distance=cc_range
    )



def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state. Compare both sides as strings for int/str ID mismatch.
    REQUIRES: game_state['unit_by_id'] (built at reset/reload). Absence = bug, raise explicitly.
    """
    unit_by_id = require_key(game_state, "unit_by_id")
    return unit_by_id.get(str(unit_id))
