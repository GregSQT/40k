#!/usr/bin/env python3
"""
engine/phase_handlers/shooting_handlers.py - AI_Shooting_Phase.md Basic Implementation
Only pool building functionality - foundation for complete handler autonomy
"""

import copy
import math
import os
import time
from typing import Dict, List, Tuple, Set, Optional, Any
from engine.combat_utils import (
    normalize_coordinates,
    get_unit_by_id,
    resolve_dice_value,
    expected_dice_value,
    set_unit_coordinates,
)
from shared.data_validation import require_key, require_present
from engine.action_log_utils import append_action_log
from .shared_utils import (
    calculate_target_priority_score, enrich_unit_for_reward_mapper, check_if_melee_can_charge,
    ACTION, WAIT, PASS, SHOOTING, ADVANCE, NOT_REMOVED,
    update_units_cache_position, update_units_cache_hp, remove_from_units_cache,
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
    update_enemy_adjacent_caches_after_unit_move,
    maybe_resolve_reactive_move,
    unit_has_rule_effect as shared_unit_has_rule_effect,
    get_source_unit_rule_id_for_effect as shared_get_source_unit_rule_id_for_effect,
    get_source_unit_rule_display_name_for_effect as shared_get_source_unit_rule_display_name_for_effect,
    build_occupied_positions_set, compute_candidate_footprint, is_footprint_placement_valid,
    is_placement_valid_with_clearance,
    _compute_unit_occupied_hexes,
    _roll_squad_shot_sequence, wound_threshold, save_threshold,
)

# ============================================================================
# PERFORMANCE: Target pool caching (30-40% speedup)
# ============================================================================
# Cache valid target pools to avoid repeated distance/LoS calculations
# Cache key: (pid, id(game_state), episode_num, turn, unit_id, col, row, advance_status, adjacent_status, player)
_target_pool_cache = {}  # per-process, per-env, per-episode; invalidates when unit/weapon changes
_move_los_preview_cache = {}
_cache_size_limit = 100  # Prevent memory leak in long episodes
_MOVE_AFTER_SHOOTING_DISTANCE_ARG = "distance"
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
    dest_col: int,
    dest_row: int,
    advance_position: bool,
) -> Tuple[Any, ...]:
    """Build strict backend cache key for move LoS target preview."""
    return (
        os.getpid(),
        require_key(game_state, "episode_number"),
        require_key(game_state, "turn"),
        require_key(game_state, "episode_steps"),
        str(require_key(game_state, "current_player")),
        unit_id_str,
        int(dest_col),
        int(dest_row),
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
    """
    Convert weapon dict to JSON-serializable format.
    Converts ParsedWeaponRule objects in WEAPON_RULES to strings.
    Recursively handles all fields to ensure complete serialization.
    """
    from engine.weapons.rules import ParsedWeaponRule
    
    serialized = {}
    
    # Recursively convert all fields
    for key, value in weapon.items():
        if isinstance(value, ParsedWeaponRule):
            # Convert ParsedWeaponRule to string
            if value.parameter is not None:
                serialized[key] = f"{value.rule}:{value.parameter}"
            else:
                serialized[key] = value.rule
        elif isinstance(value, list):
            # Convert list elements (e.g., WEAPON_RULES)
            serialized_list = []
            for item in value:
                if isinstance(item, ParsedWeaponRule):
                    if item.parameter is not None:
                        serialized_list.append(f"{item.rule}:{item.parameter}")
                    else:
                        serialized_list.append(item.rule)
                else:
                    serialized_list.append(item)
            serialized[key] = serialized_list
        else:
            # Copy other fields as-is
            serialized[key] = value
    
    return serialized


def _weapon_has_assault_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has ASSAULT rule allowing shooting after advance."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, 'rule'):  # ParsedWeaponRule object
            if rule.rule == "ASSAULT":
                return True
        elif rule == "ASSAULT":  # String
            return True
    return False


def _weapon_has_pistol_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has PISTOL rule."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, 'rule'):  # ParsedWeaponRule object
            if rule.rule == "PISTOL":
                return True
        elif rule == "PISTOL":  # String
            return True
    return False


def _get_rapid_fire_parameter(weapon: Dict[str, Any]) -> Optional[int]:
    """Return RAPID_FIRE parameter X from weapon rules, or None if absent."""
    if not weapon:
        return None
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    for rule in rules:
        if hasattr(rule, "rule"):
            if rule.rule == "RAPID_FIRE":
                if rule.parameter is None:
                    raise ValueError("RAPID_FIRE rule is missing required parameter")
                try:
                    value = int(rule.parameter)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid RAPID_FIRE parameter: {rule.parameter}") from exc
                if value <= 0:
                    raise ValueError(f"RAPID_FIRE parameter must be > 0, got {value}")
                return value
        elif isinstance(rule, str):
            if rule == "RAPID_FIRE":
                raise ValueError("RAPID_FIRE rule is missing required parameter")
            if rule.startswith("RAPID_FIRE:"):
                raw_value = rule.split(":", 1)[1]
                try:
                    value = int(raw_value)
                except ValueError as exc:
                    raise ValueError(f"Invalid RAPID_FIRE parameter: {raw_value}") from exc
                if value <= 0:
                    raise ValueError(f"RAPID_FIRE parameter must be > 0, got {value}")
                return value
    return None


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


def _tracking_set_contains_unit(unit_id: Any, tracking_set: Set[Any]) -> bool:
    """Check unit membership in tracking sets with normalized string comparison."""
    unit_id_str = str(unit_id)
    return any(str(tracked_id) == unit_id_str for tracked_id in tracking_set)


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
    source_rule_id = _get_source_unit_rule_id_for_effect(unit, effect_rule_id)
    if source_rule_id is None:
        raise ValueError(
            f"Rule effect '{effect_rule_id}' is not present on unit "
            f"{require_key(unit, 'id')}"
        )
    unit_rules = require_key(unit, "UNIT_RULES")
    for unit_rule_entry in unit_rules:
        if str(require_key(unit_rule_entry, "ruleId")) != str(source_rule_id):
            continue
        rule_args = unit_rule_entry.get("rule_args")
        if not isinstance(rule_args, dict):
            raise ValueError(
                f"Rule '{source_rule_id}' on unit {require_key(unit, 'id')} must define rule_args"
            )
        if argument_key not in rule_args:
            raise ValueError(
                f"Rule '{source_rule_id}' on unit {require_key(unit, 'id')} "
                f"missing required argument '{argument_key}'"
            )
        raw_value = rule_args[argument_key]
        if not isinstance(raw_value, int):
            raise TypeError(
                f"Rule '{source_rule_id}' argument '{argument_key}' must be int, "
                f"got {type(raw_value).__name__}"
            )
        if raw_value <= 0:
            raise ValueError(
                f"Rule '{source_rule_id}' argument '{argument_key}' must be > 0, got {raw_value}"
            )
        return raw_value
    raise ValueError(
        f"Source rule '{source_rule_id}' not found in UNIT_RULES for unit {require_key(unit, 'id')}"
    )


def _can_unit_shoot_after_advance_with_weapon(unit: Dict[str, Any], weapon: Dict[str, Any]) -> bool:
    """Return True if unit is allowed to shoot after advance with this weapon."""
    if _weapon_has_assault_rule(weapon):
        return True
    return _unit_has_rule(unit, "shoot_after_advance")


def _can_unit_advance_in_shoot_phase(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """
    Return True only when unit can still advance in current shooting activation.

    Strict requirement: _can_advance must be initialized during activation start.
    """
    if "_can_advance" not in unit:
        raise KeyError(f"Unit missing required '_can_advance' field: unit_id={unit.get('id')}")
    if "id" not in unit:
        raise KeyError(f"Unit missing required 'id' field: {unit}")
    has_advanced = str(unit["id"]) in require_key(game_state, "units_advanced")
    has_shot = _unit_has_shot_with_any_weapon(unit)
    return bool(unit["_can_advance"]) and not has_advanced and not has_shot


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


def _set_combi_weapon_choice(game_state: Dict[str, Any], unit: Dict[str, Any], weapon_index: int) -> None:
    """Record COMBI_WEAPON profile choice for this activation."""
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    if weapon_index < 0 or weapon_index >= len(rng_weapons):
        raise IndexError(f"Invalid ranged weapon index {weapon_index} for unit {unit['id']}")
    weapon = rng_weapons[weapon_index]
    combi_key = _get_combi_weapon_key(weapon)
    if not combi_key:
        return
    if "_combi_weapon_choice" not in unit or unit["_combi_weapon_choice"] is None:
        unit["_combi_weapon_choice"] = {}
    combi_choice = unit["_combi_weapon_choice"]
    if combi_key in combi_choice and combi_choice[combi_key] != weapon_index:
        raise ValueError(
            f"COMBI_WEAPON profile already selected for '{combi_key}': "
            f"existing_index={combi_choice[combi_key]} new_index={weapon_index} unit_id={unit['id']}"
        )
    combi_choice[combi_key] = weapon_index
    from engine.game_utils import add_debug_log
    weapon_name = weapon.get("display_name", f"weapon_{weapon_index}")
    add_debug_log(
        game_state,
        f"[COMBI_WEAPON] Unit {unit.get('id')} locked weapon {weapon_index} ({weapon_name}) combi_key={combi_key}"
    )


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


def _ranged_distance_metric() -> str:
    """Métrique de portée tir (``hex``|``euclidean``) — sélecteur unique, source game_config.json."""
    from config_loader import get_config_loader
    from engine.combat_utils import get_distance_metric
    return get_distance_metric("ranged", get_config_loader().get_game_config())


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

    _ranged_metric = _ranged_distance_metric()

    max_rng = 0
    for w in rng_weapons:
        try:
            r = require_key(w, "RNG")
            if r > max_rng:
                max_rng = r
        except Exception:
            continue
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
    for enemy_id, cache_entry in list(units_cache.items()):
        enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if enemy_player != unit_player:
            enemy = get_unit_by_id(game_state, enemy_id)
            if enemy is None:
                raise KeyError(f"Unit {enemy_id} missing from game_state['units']")
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
                _ue, cache_entry, melee_range
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
                # arg1=1 AND arg3=1 -> ✅ Weapon MUST have PISTOL rule (continue to next check)
                if not _weapon_has_pistol_rule(weapon):
                    can_use = False
                    reason = "No PISTOL rule (cannot shoot non-PISTOL when adjacent)"
        
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
        
        # Check PISTOL category mixing restriction
        # If unit has already fired with a weapon, can only use weapons of the same category
        if can_use and "_shooting_with_pistol" in unit and unit["_shooting_with_pistol"] is not None:
            weapon_is_pistol = _weapon_has_pistol_rule(weapon)
            
            if unit["_shooting_with_pistol"]:
                # Unit fired with PISTOL weapon, can only select other PISTOL weapons
                if not weapon_is_pistol:
                    can_use = False
                    reason = "Cannot mix PISTOL with non-PISTOL weapons"
            else:
                # Unit fired with non-PISTOL weapon, cannot select PISTOL weapons
                if weapon_is_pistol:
                    can_use = False
                    reason = "Cannot mix non-PISTOL with PISTOL weapons"
        
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
                weapon_is_pistol = _weapon_has_pistol_rule(weapon)
                shooter_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, unit)

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
                                if not weapon_is_pistol:
                                    continue
                                if not row["enemy_engaged_with_shooter"]:
                                    continue
                            elif row["enemy_engaged_with_shooter"] and not weapon_is_pistol:
                                continue
                            if row["friendly_blocks"]:
                                continue
                            weapon_has_valid_target = True
                            break
                        _row_enemy = get_unit_by_id(game_state, row["enemy_id_str"])
                        if _row_enemy is None:
                            continue
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

def _get_available_weapons_for_selection(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    current_weapon_is_pistol: Optional[bool] = None,
    exclude_used: bool = True,
    has_advanced: bool = False
) -> List[Dict[str, Any]]:
    """
    DEPRECATED: This function is kept for backward compatibility.
    Use weapon_availability_check() instead.
    
    Get list of available weapons for selection, filtered by:
    - Range: weapon must have at least one target in range
    - LoS: weapon must have at least one target with line of sight
    - ASSAULT rule: if unit advanced
    - PISTOL rule: category (PISTOL or non-PISTOL)
    - Used weapons: if exclude_used=True, exclude weapons with weapon.shot = 1
    
    Returns:
        List of dicts with keys: index, weapon, can_use, reason
    """
    available_weapons = []
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    
    # Build valid targets for range/LoS checking
    # We'll check each weapon individually
    unit_id = unit["id"]
    
    for idx, weapon in enumerate(rng_weapons):
        can_use = True
        reason = None
        
        # Check weapon.shot flag
        if exclude_used:
            weapon_shot = require_key(weapon, "shot")
            if weapon_shot == 1:
                can_use = False
                reason = "Weapon already used (weapon.shot = 1)"
                available_weapons.append({
                    "index": idx,
                    "weapon": _serialize_weapon_for_json(weapon),
                    "can_use": can_use,
                    "reason": reason
                })
                continue
        
        # Check ASSAULT rule if unit advanced
        if has_advanced:
            if not _weapon_has_assault_rule(weapon):
                can_use = False
                reason = "No ASSAULT rule (cannot shoot after advancing)"
                available_weapons.append({
                    "index": idx,
                    "weapon": _serialize_weapon_for_json(weapon),
                    "can_use": can_use,
                    "reason": reason
                })
                continue
        
        # Check PISTOL rule category
        # Only apply PISTOL filter if unit has already fired (current_weapon_is_pistol is not None)
        # If None, unit hasn't fired yet, so all weapons should be selectable
        weapon_rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
        is_pistol = "PISTOL" in weapon_rules
        
        if current_weapon_is_pistol is not None:
            if current_weapon_is_pistol:
                # If current weapon is PISTOL, can only select other PISTOL weapons
                if not is_pistol:
                    can_use = False
                    reason = "Cannot mix PISTOL with non-PISTOL weapons"
                    available_weapons.append({
                        "index": idx,
                        "weapon": _serialize_weapon_for_json(weapon),
                        "can_use": can_use,
                        "reason": reason
                    })
                    continue
            else:
                # If current weapon is not PISTOL, exclude PISTOL weapons
                if is_pistol:
                    can_use = False
                    reason = "Cannot mix non-PISTOL with PISTOL weapons"
                    available_weapons.append({
                        "index": idx,
                        "weapon": _serialize_weapon_for_json(weapon),
                        "can_use": can_use,
                        "reason": reason
                    })
                    continue
        
        # Check if weapon has at least one valid target (range + LoS)
        weapon_has_valid_target = False
        weapon_range = require_key(weapon, "RNG")
        
        # Skip if weapon has no range
        if weapon_range <= 0:
            can_use = False
            reason = "Weapon has no range"
            available_weapons.append({
                "index": idx,
                "weapon": _serialize_weapon_for_json(weapon),
                "can_use": can_use,
                "reason": reason
            })
            continue
        
        from engine.combat_utils import ranged_edge_distance
        from engine.hex_utils import Socle
        _metric2 = _ranged_distance_metric()
        units_cache = require_key(game_state, "units_cache")
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        unit_col, unit_row = require_unit_position(unit, game_state)
        _uid2 = str(unit["id"])
        _ue2 = units_cache.get(_uid2)
        _shooter_socle2 = _socle_from_entry(_ue2) if _ue2 else Socle(
            unit["BASE_SHAPE"], unit["BASE_SIZE"], unit_col, unit_row, {(unit_col, unit_row)}
        )
        for enemy_id, cache_entry in units_cache.items():
            enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
            if enemy_player != unit_player:
                enemy = get_unit_by_id(game_state, enemy_id)
                if enemy is None:
                    raise KeyError(f"Unit {enemy_id} missing from game_state['units']")
                distance = ranged_edge_distance(
                    _shooter_socle2, _socle_from_entry(cache_entry), _metric2, max_distance=weapon_range
                )
                if distance > weapon_range:
                    continue
                
                # Check if target is valid (LoS, melee, etc.)
                # Create temporary unit with only this weapon for validation
                # Use dict() constructor to create a proper copy
                temp_unit = dict(unit)
                temp_unit["RNG_WEAPONS"] = [weapon]
                temp_unit["selectedRngWeaponIndex"] = 0
                
                try:
                    if _is_valid_shooting_target(game_state, temp_unit, enemy):
                        weapon_has_valid_target = True
                        break
                except (KeyError, IndexError, AttributeError) as e:
                    # If validation fails, skip this weapon
                    can_use = False
                    reason = f"Validation error: {str(e)}"
                    break
        
        if not weapon_has_valid_target:
            can_use = False
            reason = "No valid targets in range or line of sight"
        
        available_weapons.append({
            "index": idx,
            "weapon": _serialize_weapon_for_json(weapon),
            "can_use": can_use,
            "reason": reason
        })
    
    return available_weapons

def shooting_phase_start(game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI_Shooting_Phase.md EXACT: Initialize shooting phase and build activation pool
    Initialize weapon_rule and weapon.shot flags
    """
    global _target_pool_cache

    if game_state.get("pending_shooting_phase_init"):
        game_state["pending_shooting_phase_init"] = False

    # Set phase
    game_state["phase"] = "shoot"

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
            unit = get_unit_by_id(game_state, unit_id)
            if unit is None:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
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
                "_shooting_with_pistol",
                "_manual_weapon_selected",
                "manualWeaponSelected",
                "_shoot_activation_started",
                "_current_shoot_nb",
                "_rapid_fire_context_weapon_index",
                "_rapid_fire_base_nb",
                "_rapid_fire_shots_fired",
                "_rapid_fire_bonus_total",
                "_rapid_fire_rule_value",
                "_rapid_fire_bonus_shot_current",
                "_rapid_fire_bonus_applied_by_weapon",
            )
            for field_name in transient_shoot_state_fields:
                if field_name in unit:
                    del unit[field_name]
            rng_weapons = require_key(unit, "RNG_WEAPONS")
            for weapon in rng_weapons:
                weapon["shot"] = 0
            
            if rng_weapons:
                # Initialize weapon selection. Full weapon_availability_check is only needed when
                # adjacent (PISTOL) or after advance (ASSAULT / combi) — otherwise O(weapons×enemies)
                # per ally dominated SHOOT_PHASE_START reset_allies_s.
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                weapon_rule = game_state.get("weapon_rule", 1)

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
                        # If adjacent, prioritize PISTOL weapons
                        if is_adjacent:
                            pistol_weapons = [
                                w for w in usable_weapons if _weapon_has_pistol_rule(require_key(w, "weapon"))
                            ]
                            if pistol_weapons:
                                first_weapon = pistol_weapons[0]
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

    # If no eligible units, end phase immediately (align with MOVE phase)
    if not eligible_units:
        if "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
        return shooting_phase_end(game_state)
    
    # Auto-activate next unit only for AI-controlled players.
    cfg = require_key(game_state, "config")
    if not _should_auto_activate_next_shooting_unit(game_state, cfg, eligible_units):
        if "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
    else:
        game_state["active_shooting_unit"] = eligible_units[0]
    
    # Silent pool building - no console logs during normal operation
    if "console_logs" not in game_state:
        game_state["console_logs"] = []
    
    return {
        "phase_initialized": True,
        "eligible_units": len(eligible_units),
        "phase_complete": len(eligible_units) == 0
    }


def compute_unit_hidden_models(
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
    from engine.terrain_utils import model_within_terrain
    base_shape = require_key(unit, "BASE_SHAPE")
    base_size = require_key(unit, "BASE_SIZE")
    orientation = int(require_key(unit, "orientation"))
    hidden_model_ids: List[Any] = []
    for mid, (col, row) in by_model.items():
        if model_within_terrain(
            int(col), int(row), base_shape, base_size, orientation,
            terrain_areas, obscuring_only=True,
        ):
            hidden_model_ids.append(mid)
    return hidden_model_ids


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
        unit = _get_unit_by_id(game_state, str(unit_id))
        if unit is None:
            continue
        if not is_unit_alive(str(unit_id), game_state) or not bool(unit.get("hideable")):
            unit["hidden"] = False
            unit["hidden_models"] = []
            continue
        if str(unit_id) in shot_ids or str(unit_id) in shot_prev_ids:
            unit["hidden"] = False
            unit["hidden_models"] = []
            continue
        by_model = require_key(units_cache[str(unit_id)], "occupied_hexes_by_model")
        hidden_model_ids = compute_unit_hidden_models(unit, by_model, game_state, terrain_areas)
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
    appliquée à l'unité avant recalcul du footprint) puis réutilise ``compute_unit_hidden_models``
    → résultat identique au recalcul effectué après le drop, sans muter ``game_state`` ni deepcopy.

    Retourne ``{"hidden_models": [...], "hidden": bool}``.
    """
    unit_id_str = str(unit_id)
    empty = {"hidden_models": [], "hidden": False}
    unit = _get_unit_by_id(game_state, unit_id_str)
    if unit is None:
        return empty
    # Gates niveau-unité, identiques à compute_hidden_statuses.
    if not is_unit_alive(unit_id_str, game_state) or not bool(unit.get("hideable")):
        return empty
    shot_ids = {str(x) for x in game_state.get("units_shot", set())}
    shot_prev_ids = {str(x) for x in game_state.get("units_shot_previous_turn", set())}
    if unit_id_str in shot_ids or unit_id_str in shot_prev_ids:
        return empty
    units_cache = require_key(game_state, "units_cache")
    entry = units_cache.get(unit_id_str)
    if entry is None:
        return empty
    terrain_areas = require_key(game_state, "terrain_areas")
    norm_dest_col, norm_dest_row = normalize_coordinates(int(dest_col), int(dest_row))
    old_col = int(entry.get("col", norm_dest_col))
    old_row = int(entry.get("row", norm_dest_row))
    delta_col = norm_dest_col - old_col
    delta_row = norm_dest_row - old_row
    by_model = require_key(entry, "occupied_hexes_by_model")
    # Translation offset rigide des figs (cf. translate_squad_to_destination), sans mutation.
    moved_by_model = {
        mid: (int(c) + delta_col, int(r) + delta_row)
        for mid, (c, r) in by_model.items()
    }
    # Le move applique unit['orientation'] = orientation avant de recalculer le footprint.
    unit_for_footprint = unit if orientation is None else {**unit, "orientation": int(orientation)}
    hidden_model_ids = compute_unit_hidden_models(
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
    figurine-par-figurine (squadModelMove), où chaque fig a sa propre position provisoire (pas une
    translation rigide). Réutilise ``compute_unit_hidden_models`` → identique au recalcul après pose.

    Retourne ``{"hidden_models": [...], "hidden": bool}``.
    """
    unit_id_str = str(unit_id)
    empty = {"hidden_models": [], "hidden": False}
    unit = _get_unit_by_id(game_state, unit_id_str)
    if unit is None:
        return empty
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
    hidden_model_ids = compute_unit_hidden_models(
        unit_for_footprint, by_model, game_state, terrain_areas
    )
    return {
        "hidden_models": hidden_model_ids,
        "hidden": len(hidden_model_ids) == len(by_model) and len(by_model) > 0,
    }


def build_unit_los_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    AI_TURN.md: Calculate LoS cache for a specific unit.
    Uses units_cache and has_line_of_sight_coords() for performance.
    
    Returns: void (updates unit["los_cache"])
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return

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

    # Calculate LoS for each enemy in units_cache (only alive enemies — dead must not appear in pool).
    # All visibility/cover is delegated to compute_unit_los() — the single source of truth.
    for target_id, target_data in units_cache.items():
        # Skip friendly units (only calculate LoS to enemies)
        if target_data["player"] == unit_player:
            continue
        # CRITICAL: Exclude dead units so they never appear in los_cache → valid_target_pool
        if not is_unit_alive(str(target_id), game_state):
            continue
        target_unit = _get_unit_by_id(game_state, str(target_id))
        if target_unit is None:
            continue

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


def _build_shooting_los_cache(game_state: Dict[str, Any]) -> None:
    """
    DEPRECATED: This function is kept for backward compatibility but should not be used.
    Use build_unit_los_cache() instead for unit-local cache (AI_TURN.md compliance).
    
    Build LoS cache for all unit pairs at shooting phase start.
    Pure function, stores in game_state, no copying.
    
    Performance: O(n²) calculation once per phase vs O(n²×m) per activation.
    Called once per shooting phase, massive speedup during unit activations.
    
    NOTE: Cache is invalidated when units move or die to prevent stale results.
    """
    los_cache = {}
    
    # Get all alive units (both players; units_cache is source of truth)
    units_cache = require_key(game_state, "units_cache")
    alive_units = []
    for unit_id in units_cache.keys():
        unit = _get_unit_by_id(game_state, unit_id)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        alive_units.append(unit)
    
    # Calculate LoS for every shooter-target pair
    for shooter in alive_units:
        for target in alive_units:
            # Skip same unit
            if shooter["id"] == target["id"]:
                continue
            
            # Calculate LoS using existing function (expensive but only once)
            # CRITICAL: Always recalculate, don't rely on potentially stale cache
            # CRITICAL: Normalize IDs to string for consistent cache key comparison
            cache_key = (str(shooter["id"]), str(target["id"]))
            los_cache[cache_key] = _has_line_of_sight(game_state, shooter, target)
    
    # Store cache in game_state (single source of truth)
    game_state["los_cache"] = los_cache
    
    # Debug log cache size (optional, remove in production)
    # print(f"LoS CACHE: Built {len(los_cache)} entries for {len(alive_units)} units")

def preview_shoot_valid_targets_from_position(
    game_state: Dict[str, Any],
    unit_id: str,
    dest_col: int,
    dest_row: int,
    *,
    advance_position: bool = False,
    include_los_cells: bool = True,
) -> Dict[str, Any]:
    """
    Return shooting preview data from a hypothetical position (read-only, no mutation).

    Aligné sur l'activation tir : copie d'état, tireur déplacé virtuellement, ``build_unit_los_cache``
    puis ``valid_target_pool_build`` (empreintes §3.3, PISTOL / adjacent, alliés au contact, etc.).

    L'ancienne implémentation (distance centre-à-centre + ``compute_los_state`` seuls) pouvait
    marquer des cibles « valides » alors que le pool moteur les exclut.

    Args:
        advance_position: Si True, simule une unité après Advance (``units_advanced`` sur la copie).
        include_los_cells: Si False, ne calcule pas la grille complète LoS (coûteuse) et renvoie
            seulement les cibles tirables backend + couvert par cible.
    """
    empty_preview: Dict[str, Any] = {
        "valid_targets": [],
        "los_preview_attack_cells": [],
        "los_preview_cover_cells": [],
        "los_preview_ratio_by_hex": {},
        "cover_by_unit_id": {},
        "hidden_too_far_by_unit_id": {},
        "visible_cells_by_target": {},
    }

    unit_id_str = str(unit_id)
    unit = _get_unit_by_id(game_state, unit_id_str)
    if not unit:
        return empty_preview
    if not game_state.get("units_cache"):
        return empty_preview
    if not unit.get("RNG_WEAPONS"):
        return empty_preview

    _preview_perf_t0 = time.perf_counter()
    preview_cache_key: Optional[Tuple[Any, ...]] = None
    if not include_los_cells:
        _preview_perf_cache_t0 = time.perf_counter()
        preview_cache_key = _move_los_preview_cache_key(
            game_state,
            unit,
            unit_id_str,
            dest_col,
            dest_row,
            advance_position,
        )
        cached_preview = _move_los_preview_cache.get(preview_cache_key)
        if cached_preview is not None:
            _preview_perf_after_cache = time.perf_counter()
            # print(
            #     "[MOVE_LOS_PREVIEW_PERF] "
            #     f"unit={unit_id_str} dest=({dest_col},{dest_row}) "
            #     f"total_ms={(_preview_perf_after_cache - _preview_perf_t0) * 1000:.1f} "
            #     f"cache_hit=1 "
            #     f"cache_lookup_ms={(_preview_perf_after_cache - _preview_perf_cache_t0) * 1000:.1f} "
            #     f"valid_targets={cached_preview['valid_targets']}",
            #     flush=True,
            # )
            return copy.deepcopy(cached_preview)

    _preview_perf_deepcopy_t0 = time.perf_counter()
    gs = copy.deepcopy(game_state)
    _preview_perf_after_deepcopy = time.perf_counter()
    if "weapon_rule" not in gs:
        gs["weapon_rule"] = 1

    u = _get_unit_by_id(gs, unit_id_str)
    if not u:
        return empty_preview

    u.pop("valid_target_pool", None)
    u.pop("_pool_from_cache", None)
    u.pop("_pool_cache_key", None)

    # Move-phase preview simulates a fresh future shooting activation; weapon["shot"]
    # is normally initialized at shooting_phase_start, which has not run yet.
    for weapon in require_key(u, "RNG_WEAPONS"):
        weapon["shot"] = 0

    set_unit_coordinates(u, dest_col, dest_row)
    update_units_cache_position(gs, unit_id_str, int(u["col"]), int(u["row"]))

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

    _preview_perf_los_t0 = time.perf_counter()
    build_unit_los_cache(gs, unit_id_str)
    _preview_perf_after_los = time.perf_counter()
    _preview_perf_enemy_precheck_t0 = time.perf_counter()
    preview_enemy_precheck = _build_weapon_availability_enemy_precheck(
        gs, u, require_key(u, "RNG_WEAPONS")
    )
    _preview_perf_after_enemy_precheck = time.perf_counter()
    _preview_perf_weapon_availability_t0 = time.perf_counter()
    preview_weapon_available_pool = weapon_availability_check(
        gs,
        u,
        weapon_rule,
        advance_status,
        adjacent_status,
        _precheck=preview_enemy_precheck,
    )
    _preview_perf_after_weapon_availability = time.perf_counter()

    _preview_perf_pool_t0 = time.perf_counter()
    valid_targets = valid_target_pool_build(
        gs,
        u,
        weapon_rule,
        advance_status,
        adjacent_status,
        precomputed_weapon_available_pool=preview_weapon_available_pool,
        precomputed_enemy_precheck=preview_enemy_precheck,
    )
    _preview_perf_after_pool = time.perf_counter()
    if include_los_cells:
        _preview_perf_cells_t0 = time.perf_counter()
        _update_unit_los_preview_data(gs, u, weapon_rule, advance_status, adjacent_status)
        _preview_perf_after_cells = time.perf_counter()
    else:
        _preview_perf_cells_t0 = time.perf_counter()
        u["los_preview_attack_cells"] = []
        u["los_preview_cover_cells"] = []
        u["los_preview_ratio_by_hex"] = {}
        _preview_perf_after_cells = time.perf_counter()

    _preview_perf_cover_t0 = time.perf_counter()
    cover_by_unit_id = build_cover_by_unit_id_for_valid_targets(gs, u, valid_targets)
    visible_cells_by_target = build_visible_cells_by_target(gs, u, valid_targets)
    _preview_perf_after_cover = time.perf_counter()
    # print(
    #     "[MOVE_LOS_PREVIEW_PERF] "
    #     f"unit={unit_id_str} dest=({dest_col},{dest_row}) "
    #     f"total_ms={(_preview_perf_after_cover - _preview_perf_t0) * 1000:.1f} "
    #     f"deepcopy_ms={(_preview_perf_after_deepcopy - _preview_perf_deepcopy_t0) * 1000:.1f} "
    #     f"los_cache_ms={(_preview_perf_after_los - _preview_perf_los_t0) * 1000:.1f} "
    #     f"enemy_precheck_ms={(_preview_perf_after_enemy_precheck - _preview_perf_enemy_precheck_t0) * 1000:.1f} "
    #     f"weapon_availability_ms={(_preview_perf_after_weapon_availability - _preview_perf_weapon_availability_t0) * 1000:.1f} "
    #     f"valid_pool_ms={(_preview_perf_after_pool - _preview_perf_pool_t0) * 1000:.1f} "
    #     f"cells_ms={(_preview_perf_after_cells - _preview_perf_cells_t0) * 1000:.1f} "
    #     f"cover_ms={(_preview_perf_after_cover - _preview_perf_cover_t0) * 1000:.1f} "
    #     f"valid_targets={valid_targets}",
    #     flush=True,
    # )

    result_payload = {
        "valid_targets": valid_targets,
        "los_preview_attack_cells": require_key(u, "los_preview_attack_cells"),
        "los_preview_cover_cells": require_key(u, "los_preview_cover_cells"),
        "los_preview_ratio_by_hex": require_key(u, "los_preview_ratio_by_hex"),
        "cover_by_unit_id": cover_by_unit_id,
        "hidden_too_far_by_unit_id": build_hidden_too_far_by_unit_id(gs, u),
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
        target_unit = _get_unit_by_id(game_state, target_id_str)
        if target_unit is None:
            continue
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
    from engine.hex_utils import min_distance_between_sets
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
    units_cache = require_key(game_state, "units_cache")
    shooter_id = str(require_key(shooter, "id"))
    shooter_player = int(require_key(shooter, "player"))
    shooter_col, shooter_row = require_unit_position(shooter, game_state)
    shooter_entry = units_cache.get(shooter_id)
    shooter_fp = (
        shooter_entry.get("occupied_hexes", {(shooter_col, shooter_row)})
        if shooter_entry else {(shooter_col, shooter_row)}
    )
    result: Dict[str, bool] = {}
    for target_id, has_los in los_cache.items():
        if not has_los:
            continue
        target_id_str = str(target_id)
        if target_id_str == shooter_id:
            continue
        enemy = _get_unit_by_id(game_state, target_id_str)
        if enemy is None or not is_unit_alive(target_id_str, game_state):
            continue
        if int(require_key(enemy, "player")) == shooter_player:
            continue
        if not bool(enemy.get("hidden")):
            continue
        enemy_entry = units_cache.get(target_id_str)
        if enemy_entry is None:
            continue
        enemy_fp = enemy_entry.get(
            "occupied_hexes", {(enemy_entry["col"], enemy_entry["row"])}
        )
        distance = min_distance_between_sets(shooter_fp, enemy_fp)
        if distance > max_rng:
            continue  # hors portée : pas "à portée mais trop loin"
        if distance > detection_range_subhex:
            result[target_id_str] = True
    return result


def update_los_cache_after_target_death(game_state: Dict[str, Any], dead_target_id: str) -> None:
    """
    AI_TURN.md: Update LoS cache after target death.
    Removes dead target from active unit's los_cache.
    
    NOTE: units_cache removal is handled by update_units_cache_hp when HP becomes 0.
    
    Returns: void (updates unit["los_cache"])
    """
    dead_target_id_str = str(dead_target_id)
    
    # Update active unit's los_cache (only active unit has los_cache)
    active_unit_id = game_state.get("active_shooting_unit")
    if active_unit_id:
        active_unit = _get_unit_by_id(game_state, active_unit_id)
        if active_unit and "los_cache" in active_unit:
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
    unit = _get_unit_by_id(game_state, dead_unit_id)
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


def _rebuild_los_cache_for_unit(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    Rebuild LoS cache for a specific unit after it moves (e.g., after advance).
    Recalculates LoS from this unit to all other alive units.
    
    CRITICAL: Called after unit moves to ensure cache is up-to-date with new position.
    This prevents "shoot through wall" bugs caused by stale cache.
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return
    
    # Initialize cache if it doesn't exist
    if "los_cache" not in game_state:
        game_state["los_cache"] = {}
    
    # Get all alive units (both players; units_cache is source of truth)
    units_cache = require_key(game_state, "units_cache")
    alive_units = []
    for target_id in units_cache.keys():
        target = _get_unit_by_id(game_state, target_id)
        if target is None:
            raise KeyError(f"Unit {target_id} missing from game_state['units']")
        alive_units.append(target)
    
    # Recalculate LoS from this unit to all other units
    for target in alive_units:
        if target["id"] == unit_id:
            continue  # Skip self
        
        # Calculate LoS using current positions
        # CRITICAL: Normalize IDs to string for consistent cache key comparison
        cache_key = (str(unit_id), str(target["id"]))
        has_los = _has_line_of_sight(game_state, unit, target)
        game_state["los_cache"][cache_key] = has_los
        
        # Also update reverse direction (target -> unit)
        # CRITICAL: Normalize IDs to string for consistent cache key comparison
        reverse_key = (str(target["id"]), str(unit_id))
        game_state["los_cache"][reverse_key] = has_los


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
    """
    # Invalidate los_cache (unit ID-based cache)
    # CRITICAL: Normalize moved_unit_id to string for consistent comparison
    if "los_cache" in game_state:
        moved_unit_id_str = str(moved_unit_id)
        keys_to_remove = [
            key for key in game_state["los_cache"].keys()
            if str(key[0]) == moved_unit_id_str or str(key[1]) == moved_unit_id_str
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
            old_col_int, old_row_int = normalize_coordinates(old_col, old_row)
            old_pos = (old_col_int, old_row_int)
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

def _ai_select_shooting_target(game_state: Dict[str, Any], unit_id: str, valid_targets: List[str]) -> str:
    """AI target selection using RewardMapper system"""
    if not valid_targets:
        raise ValueError("valid_targets required for AI shooting target selection")
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        raise ValueError(f"AI shooting target selection missing unit: unit_id={unit_id}")
    
    from ai.reward_mapper import RewardMapper
    reward_configs = require_key(game_state, "reward_configs")
    
    # Get unit type for config lookup
    global _unit_registry_singleton
    if _unit_registry_singleton is None:
        from ai.unit_registry import UnitRegistry
        _unit_registry_singleton = UnitRegistry()
    shooter_unit_type = require_key(unit, "unitType")
    shooter_agent_key = _unit_registry_singleton.get_model_key(shooter_unit_type)
    
    # Get unit-specific config
    unit_reward_config = require_key(reward_configs, shooter_agent_key)
    reward_mapper = RewardMapper(unit_reward_config)
    
    # Build target list for reward mapper (single lookup per tid)
    all_targets = []
    for tid in valid_targets:
        t = _get_unit_by_id(game_state, tid)
        if not t:
            raise ValueError(f"AI shooting target selection missing target: target_id={tid}")
        all_targets.append(t)

    best_target = valid_targets[0]
    best_reward = None
    
    for target_id in valid_targets:
        target = _get_unit_by_id(game_state, target_id)
        if not target:
            raise ValueError(f"AI shooting target selection missing target: target_id={target_id}")
        
        can_melee_charge = False  # TODO: implement melee charge check
        
        reward = reward_mapper.get_shooting_priority_reward(unit, target, all_targets, can_melee_charge, game_state)
        
        if best_reward is None or reward > best_reward:
            best_reward = reward
            best_target = target_id

    return best_target


def _is_ai_controlled_shooting_unit(
    game_state: Dict[str, Any], unit: Dict[str, Any], config: Dict[str, Any]
) -> bool:
    """
    Determine whether the active shooting unit is AI-controlled.

    Source of truth is game_state.player_types.
    """
    player_types = require_key(game_state, "player_types")
    if not isinstance(player_types, dict):
        raise TypeError(f"game_state['player_types'] must be a dict, got {type(player_types).__name__}")
    unit_player = str(require_key(unit, "player"))
    if unit_player not in player_types:
        raise KeyError(f"Missing player_types entry for player {unit_player}")
    return player_types[unit_player] == "ai"


def _should_auto_activate_next_shooting_unit(
    game_state: Dict[str, Any], config: Dict[str, Any], pool: List[str]
) -> bool:
    """
    Auto-activate next unit only when that unit is AI-controlled.
    """
    if not pool:
        return False
    next_unit = _get_unit_by_id(game_state, pool[0])
    if not next_unit:
        return False
    return _is_ai_controlled_shooting_unit(game_state, next_unit, config)

def _has_valid_shooting_targets(game_state: Dict[str, Any], unit: Dict[str, Any], current_player: int) -> bool:
    """
    ADVANCE_IMPLEMENTATION: Updated to support Advance action.
    Unit is eligible for shooting phase if it CAN_SHOOT OR CAN_ADVANCE.
    CAN_ADVANCE = alive AND correct player AND not fled AND not in melee.
    """
    # PISTOL rule: Initialize _shooting_with_pistol to None for eligibility check
    # This ensures each unit starts with no PISTOL category restriction
    unit["_shooting_with_pistol"] = None

    _ep = game_state.get("episode_number", "?")
    _tn = game_state.get("turn", "?")
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
    _has_advanced = unit_id_str in game_state.get("units_advanced", set())
    _has_moved = unit_id_str in game_state.get("units_moved", set())
    _has_fled = unit_id_str in game_state["units_fled"]
    print(f"[SHOOT ELIG] E{_ep} T{_tn} unit={_uid} moved={_has_moved} advanced={_has_advanced} fled={_has_fled}")
    if unit_id_str in game_state["units_fled"] and not _unit_has_rule(unit, "shoot_after_flee"):
        print(f"[SHOOT ELIG] E{_ep} T{_tn} unit={_uid} -> NOT ELIGIBLE (fled)")
        return False

    # STEP 1: ELIGIBILITY CHECK
    # Check if unit is adjacent to enemy (melee range)
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    
    # Determine CAN_ADVANCE and CAN_SHOOT using weapon_availability_check
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    
    if is_adjacent:
        # Adjacent to enemy
        # CAN_ADVANCE = false (cannot advance when adjacent)
        can_advance = False
        # weapon_availability_check(weapon_rule, 0, 1) -> Build weapon_available_pool
        advance_status = 0  # Not advanced yet (eligibility check)
        adjacent_status = 1  # Adjacent to enemy
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        # weapon_available_pool NOT empty? -> CAN_SHOOT = true, else false
        can_shoot = len(usable_weapons) > 0
        print(f"[SHOOT ELIG] E{_ep} T{_tn} unit={_uid} adjacent=True usable_weapons={len(usable_weapons)}/{len(weapon_available_pool)} can_shoot={can_shoot}")
        # If CAN_SHOOT = false -> ❌ Skip (no valid actions)
        if not can_shoot:
            print(f"[SHOOT ELIG] E{_ep} T{_tn} unit={_uid} -> NOT ELIGIBLE (adjacent, no usable weapon)")
            return False
        unit["_can_shoot"] = can_shoot
        unit["_can_advance"] = can_advance
        return True
    else:
        # NOT adjacent to enemy: CAN_ADVANCE is always true → unit is always eligible for the
        # shoot_activation_pool (can at least Advance). The old code still called
        # weapon_availability_check then evaluated (can_shoot or can_advance) which is always
        # true here — that duplicate O(weapons×enemies) work dominated SHOOT_PHASE_START timing.
        can_advance = True
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        has_positive_rng = any(require_key(w, "RNG") > 0 for w in rng_weapons)
        unit["_can_advance"] = can_advance
        unit["_can_shoot"] = has_positive_rng
        print(f"[SHOOT ELIG] E{_ep} T{_tn} unit={_uid} adjacent=False rng_weapons={len(rng_weapons)} can_shoot={has_positive_rng} (eligible via advance)")
        return True


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
    for friendly_id, cache_entry in units_cache.items():
        friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if friendly_player == shooter_player_int and friendly_id != shooter_id_str:
            if unit_entries_within_engagement_zone(target_entry, cache_entry, melee_range):
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

    shooter_col, shooter_row = require_unit_position(shooter, game_state)
    target_col, target_row = require_unit_position(target, game_state)

    shooter_entry = units_cache.get(shooter_id_str)
    target_entry = units_cache.get(target_id_str)
    shooter_fp = shooter_entry.get("occupied_hexes", {(shooter_col, shooter_row)}) if shooter_entry else {(shooter_col, shooter_row)}
    target_fp = target_entry.get("occupied_hexes", {(target_col, target_row)}) if target_entry else {(target_col, target_row)}
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
        shooter_entry, target_entry, melee_range
    )
    selected_weapon = get_selected_ranged_weapon(shooter)
    weapon_is_pistol = bool(selected_weapon and _weapon_has_pistol_rule(selected_weapon))
    shooter_is_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, shooter)

    if shooter_is_engaged:
        if not weapon_is_pistol:
            return False
        if not enemy_adjacent_to_shooter:
            return False
    elif enemy_adjacent_to_shooter and not weapon_is_pistol:
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
    # Unit-local cache avoids 56-call spike at shooting_phase_start (AI_TURN.md per-unit cache).
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
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return {"error": "unit_not_found", "unitId": unit_id}
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
    
    # AI_TURN.md STEP 2: Build unit's los_cache at activation
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
    # Recompute advance capability at activation time from current board state.
    # Do not rely on stale value set at phase-start pool build.
    unit["_can_advance"] = not unit_is_adjacent

    # PISTOL rule: Reset _shooting_with_pistol for this activation (no category restriction yet)
    # This must be done BEFORE weapon_availability_check to avoid incorrect filtering
    unit["_shooting_with_pistol"] = None
    # RAPID_FIRE state is activation-scoped and must be reset at activation start.
    unit["_rapid_fire_context_weapon_index"] = None
    unit["_rapid_fire_base_nb"] = 0
    unit["_rapid_fire_shots_fired"] = 0
    unit["_rapid_fire_bonus_total"] = 0
    unit["_rapid_fire_rule_value"] = 0
    unit["_rapid_fire_bonus_shot_current"] = False
    unit["_rapid_fire_bonus_applied_by_weapon"] = {}
    
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
        can_advance = _can_unit_advance_in_shoot_phase(unit, game_state)
        if can_advance:
            unit["_current_shoot_nb"] = require_key(unit, "SHOOT_LEFT")
            _emit_shoot_activation_perf(game_state, str(unit_id), _t_act0, _t_after_los, None, None, None, None, None, "empty_pool_advance", 0)
            return {
                "success": True,
                "unitId": unit_id,
                "empty_target_pool": True,
                "can_advance": True,
                "allow_advance": True,
                "waiting_for_player": True,
                "action": "empty_target_advance_available",
                "context": "empty_target_pool_advance_available",
                "available_weapons": [],
            }
        else:
            _success, result = _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip")
            result["skip_reason"] = "no_valid_actions"
            _emit_shoot_activation_perf(game_state, str(unit_id), _t_act0, _t_after_los, None, None, None, None, None, "empty_pool_skip", 0)
            return result

    # weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0) -> Build weapon_available_pool
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    advance_status = 0  # STEP 2: Unit has NOT advanced yet
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
        # Mark unit as active BEFORE returning (required for frontend to show advance icon)
        game_state["active_shooting_unit"] = unit_id
        
        # unit.CAN_ADVANCE = true?
        can_advance = _can_unit_advance_in_shoot_phase(unit, game_state)
        if can_advance:
            # YES -> Only action available is advance
            # Return signal to allow advance action (handled by frontend/action handler)
            unit["valid_target_pool"] = []
            unit["_current_shoot_nb"] = require_key(unit, "SHOOT_LEFT")
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
                "empty_pool_advance",
                0,
            )
            return {
                "success": True,
                "unitId": unit_id,
                "empty_target_pool": True,
                "can_advance": True,
                "allow_advance": True,  # Signal frontend to use advancePreview mode (no shooting preview)
                "waiting_for_player": True,
                "action": "empty_target_advance_available",
                "context": "empty_target_pool_advance_available",
                "available_weapons": []  # Explicitly return empty array to prevent frontend from using stale weapons
            }
        else:
            # NO -> unit.CAN_ADVANCE = false -> No valid actions (SKIP: cannot act)
            _success, result = _handle_shooting_end_activation(
                game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
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
    
    # AI_TURN.md STEP 3: Pre-select first available weapon
    # If unit is adjacent to enemy, prioritize PISTOL weapons
    if not usable_weapons:
        # No usable weapons under current rules -> treat as no valid actions
        can_advance = _can_unit_advance_in_shoot_phase(unit, game_state)
        if can_advance:
            unit["valid_target_pool"] = []
            unit["_current_shoot_nb"] = require_key(unit, "SHOOT_LEFT")
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
                "no_usable_advance",
                len(valid_target_pool),
            )
            return {
                "success": True,
                "unitId": unit_id,
                "empty_target_pool": True,
                "can_advance": True,
                "allow_advance": True,
                "waiting_for_player": True,
                "action": "empty_target_advance_available",
                "context": "no_usable_weapon_advance_available",
                "available_weapons": []
            }
        _success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
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
            # Prioritize PISTOL weapons when adjacent to enemy
            pistol_weapons = []
            non_pistol_weapons = []
            for w in usable_weapons:
                weapon = require_key(w, "weapon")
                if _weapon_has_pistol_rule(weapon):
                    pistol_weapons.append(w)
                else:
                    non_pistol_weapons.append(w)
            
            # Prefer PISTOL weapons, but fall back to non-PISTOL if no PISTOL available
            if pistol_weapons:
                first_weapon = pistol_weapons[0]
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
    _ranged_metric_pool = _ranged_distance_metric()

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
    
    # AI_TURN.md: ASSERT unit["los_cache"] exists (must be created by build_unit_los_cache at activation)
    if "los_cache" not in unit:
        # Check if unit has fled (fled units without shoot_after_flee can still advance, but cannot shoot)
        unit_id_str = str(unit["id"])
        if unit_id_str not in require_key(game_state, "units_fled") or _unit_has_rule(unit, "shoot_after_flee"):
            raise KeyError(f"Unit {unit_id_normalized} missing required 'los_cache' field. Must call build_unit_los_cache() at activation.")
        else:
            # Unit has fled - cannot shoot, return empty pool
            return []
    
    # AI_TURN.md: Filter los_cache to get only targets with LoS (optimization)
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
            f"los_cache_size={len(unit.get('los_cache', {}))}",
            flush=True,
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
        shooter_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}
        enemy_fp = enemy_entry.get("occupied_hexes", {(enemy_entry["col"], enemy_entry["row"])})

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
            _shooter_socle_pool = socle_from_cache_entry(unit_entry) if unit_entry else Socle(
                unit["BASE_SHAPE"], unit["BASE_SIZE"], unit_col, unit_row, shooter_fp
            )
            distance_to_enemy = ranged_edge_distance(
                _shooter_socle_pool, socle_from_cache_entry(enemy_entry), _ranged_metric_pool, max_distance=_md_cap
            )
            enemy_adjacent_to_shooter = unit_entries_within_engagement_zone(
                unit_entry, enemy_entry, melee_range
            )

        shooter_is_engaged = adjacent_status == 1
        has_pistol_weapon = False
        
        if enemy_adjacent_to_shooter:
            # Enemy is adjacent to shooter - check if any weapon has PISTOL rule
            for weapon_idx in usable_weapon_indices:
                if weapon_idx < len(rng_weapons):
                    weapon = rng_weapons[weapon_idx]
                    if _weapon_has_pistol_rule(weapon):
                        has_pistol_weapon = True
                        break
            
            # If no PISTOL weapon available, cannot shoot at adjacent enemy
            if not has_pistol_weapon:
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    _ep = enemy.get("col", "?")
                    _er = enemy.get("row", "?")
                    add_debug_file_log(
                        game_state,
                        f"[TARGET POOL DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized}({_ep},{_er}) EXCLUDED - adjacent without PISTOL weapon"
                    )
                continue
        
        # Engaged shooter can only target adjacent enemies.
        if shooter_is_engaged and not enemy_adjacent_to_shooter:
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
        # If enemy is adjacent to shooter AND we have PISTOL weapon, we can shoot regardless of engagement
        # If enemy is NOT adjacent to shooter, normal rules apply: cannot shoot if enemy is engaged with friendly units
        if not enemy_adjacent_to_shooter and row_opt is None:
            enemy_adjacent_to_friendly = False
            engaged_friendly_id = None
            for friendly_id, cache_entry in units_cache.items():
                friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
                if (friendly_player == current_player_int and 
                    friendly_id != unit_id_normalized):
                    if unit_entries_within_engagement_zone(enemy_entry, cache_entry, melee_range):
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
        
        # AI_TURN.md: LoS check already done in build_unit_los_cache()
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
            if bool(enemy.get("hidden")) and distance > detection_range_subhex:
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

    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return []
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
    # enemy_pos_hash: cache per player, invalidate when any unit moves (_unit_move_version)
    # Safe on unit death: cache-hit path re-filters with is_unit_alive()
    _move_ver = game_state["_unit_move_version"]
    _eph_store = game_state.setdefault("_enemy_pos_hash_v", {})
    _eph_entry = _eph_store.get(unit_player_int)
    if _eph_entry is None or _eph_entry[0] != _move_ver:
        units_cache = require_key(game_state, "units_cache")
        _eph = tuple(
            sorted(
                (tid, int(e["col"]), int(e["row"]))
                for tid, e in units_cache.items()
                if int(e.get("player", -1)) != unit_player_int and is_unit_alive(tid, game_state)
            )
        )
        _eph_store[unit_player_int] = (_move_ver, _eph)
        enemy_pos_hash = _eph
    else:
        enemy_pos_hash = _eph_entry[1]
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
        enemy_pos_hash,
        wall_hexes_tuple,
        precheck_cache_tag,
    )

    # Check cache
    if cache_key in _target_pool_cache:
        # Cache hit: Fast path - filter dead targets only
        cached_pool = _target_pool_cache[cache_key]

        # Filter out units that died, friendly, or lost LoS
        alive_targets = []
        current_player = unit["player"]
        # CRITICAL: Convert to int for consistent comparison (player can be int or string)
        current_player_int = int(current_player) if current_player is not None else None
        for target_id_str in cached_pool:  # Iterate over string IDs
            target = _get_unit_by_id(game_state, target_id_str)
            if target and is_unit_alive(target_id_str, game_state):
                # CRITICAL: First check - target must not be friendly (fast check)
                # This is the most important check - friendly units should NEVER be in the pool
                # CRITICAL: Convert to int for consistent comparison (player can be int or string)
                target_player = int(target["player"]) if target["player"] is not None else None
                if target_player == current_player_int:
                    # This is a bug - log it for debugging
                    from engine.game_utils import add_console_log, add_debug_log
                    add_console_log(game_state, f"[BUG] Cache contained friendly unit {target_id_str} (player {target['player']}) for shooter {unit_id} (player {current_player})")
                    continue  # Skip friendly units
                # AI_TURN.md: No re-validation needed - cache is reliable during activation
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
        target = _get_unit_by_id(game_state, target_id)
        if target:
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
    _ranged_metric_prio = _ranged_distance_metric()
    _units_cache_prio = require_key(game_state, "units_cache")
    _shooter_socle_prio = socle_from_cache_entry(_units_cache_prio[unit_id_str])
    for target_id in filtered_targets:
        target = _get_unit_by_id(game_state, target_id)
        if not target:
            target_priorities.append((target_id, (999, 0, 999)))
            continue

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

    # LOS_DEBUG=1: Log topology value for each target when storing (baseline for contradiction analysis)
    if os.environ.get("LOS_DEBUG") == "1" and valid_target_pool:
        import sys
        from engine.combat_utils import has_line_of_sight_coords
        units_cache = require_key(game_state, "units_cache")
        sc, sr = unit_col, unit_row
        for tid in valid_target_pool:
            entry = units_cache.get(tid)
            if entry:
                tc, tr = entry["col"], entry["row"]
                has_los = has_line_of_sight_coords(int(sc), int(sr), int(tc), int(tr), game_state)
                try:
                    ratio, can_see = _get_los_visibility_state(
                        game_state, int(sc), int(sr), int(tc), int(tr)
                    )
                    topo_str = f"topology={ratio:.6f} can_see={can_see}"
                except Exception:
                    topo_str = "topology=N/A"
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


def _resolve_target_hexes_for_los(
    game_state: Dict[str, Any],
    target: Dict[str, Any],
    center_col: int,
    center_row: int,
) -> List[Tuple[int, int]]:
    """Resolve target footprint hexes from units_cache, else use center hex."""
    target_hexes: List[Tuple[int, int]] = [(center_col, center_row)]
    if "id" not in target:
        return target_hexes
    units_cache = require_key(game_state, "units_cache")
    target_entry = units_cache.get(str(require_key(target, "id")))
    occ = target_entry.get("occupied_hexes") if isinstance(target_entry, dict) else None
    if isinstance(occ, (set, list, tuple)) and len(occ) > 0:
        occ_list: List[Tuple[int, int]] = []
        for hx in occ:
            if isinstance(hx, (list, tuple)) and len(hx) >= 2:
                hc, hr = normalize_coordinates(hx[0], hx[1])
                occ_list.append((hc, hr))
        if occ_list:
            target_hexes = occ_list
    return target_hexes


def _dump_los_contradiction_diagnostic(
    game_state: Dict[str, Any],
    attacker: Dict[str, Any],
    target: Dict[str, Any],
    attacker_id: Any,
    target_id: Any,
    attacker_col: Any,
    attacker_row: Any,
    target_col: Any,
    target_row: Any,
) -> None:
    """
    Diagnostic: target was in valid_target_pool (los_cache said visible) but
    has_line_of_sight_coords returned False during save. Dump state to find root cause.
    """
    import sys
    from engine.combat_utils import normalize_coordinates

    lines: List[str] = []
    lines.append("=" * 80)
    lines.append("LOS CONTRADICTION DIAGNOSTIC")
    lines.append("Target was in valid_target_pool (visible) but has_line_of_sight_coords returned False")
    lines.append("=" * 80)

    # Positions used in save path
    ac, ar = int(attacker_col), int(attacker_row)
    tc, tr = int(target_col), int(target_row)
    ac_norm, ar_norm = normalize_coordinates(ac, ar)
    tc_norm, tr_norm = normalize_coordinates(tc, tr)
    cache_key = ((ac_norm, ar_norm), (tc_norm, tr_norm))
    cache_key_inv = ((tc_norm, tr_norm), (ac_norm, ar_norm))

    lines.append(f"Save path positions: attacker({attacker_id})=({ac},{ar}) target({target_id})=({tc},{tr})")
    lines.append(f"Normalized: attacker=({ac_norm},{ar_norm}) target=({tc_norm},{tr_norm})")
    lines.append(f"Cache key: {cache_key}")

    # units_cache positions (what build_unit_los_cache uses)
    uc = game_state.get("units_cache") or {}
    attacker_uid = str(attacker_id)
    target_uid = str(target_id)
    if attacker_uid in uc:
        ae = uc[attacker_uid]
        ua_col, ua_row = ae.get("col"), ae.get("row")
        lines.append(f"units_cache attacker: col={ua_col} (type={type(ua_col).__name__}) row={ua_row} (type={type(ua_row).__name__})")
        if (ua_col, ua_row) != (ac_norm, ar_norm):
            lines.append(f"  >>> MISMATCH vs save path ({ac_norm},{ar_norm})")
    if target_uid in uc:
        te = uc[target_uid]
        ut_col, ut_row = te.get("col"), te.get("row")
        lines.append(f"units_cache target: col={ut_col} (type={type(ut_col).__name__}) row={ut_row} (type={type(ut_row).__name__})")
        if (ut_col, ut_row) != (tc_norm, tr_norm):
            lines.append(f"  >>> MISMATCH vs save path ({tc_norm},{tr_norm})")

    # los_cache (what we stored when building pool)
    los_cache = attacker.get("los_cache") or {}
    if target_uid in los_cache:
        lines.append(f"attacker los_cache[{target_uid}] = {los_cache[target_uid]} (True=was visible when pool built)")
    else:
        lines.append(f"attacker los_cache: target {target_uid} NOT in los_cache")

    # valid_target_pool
    vtp = attacker.get("valid_target_pool") or []
    lines.append(f"valid_target_pool contains target: {target_uid in vtp} (pool size={len(vtp)})")

    # Pool cache trace (for LOS contradiction root cause)
    pool_from_cache = attacker.get("_pool_from_cache")
    pool_cache_key = attacker.get("_pool_cache_key")
    lines.append(f"_pool_from_cache: {pool_from_cache} (True=pool came from cache HIT)")
    lines.append(f"_pool_cache_key: {pool_cache_key}")

    # hex_los_cache
    hlc = game_state.get("hex_los_cache") or {}
    lines.append(f"hex_los_cache size: {len(hlc)}")
    if cache_key in hlc:
        lines.append(f"hex_los_cache[cache_key] = {hlc[cache_key]}")
    else:
        lines.append(f"hex_los_cache[cache_key]: NOT FOUND (cache miss)")
    if cache_key_inv in hlc:
        lines.append(f"hex_los_cache[inverse_key] = {hlc[cache_key_inv]}")

    # topology (legacy) or on-demand (×10)
    lt = game_state.get("los_topology")
    bc, br = game_state.get("board_cols"), game_state.get("board_rows")
    if lt is not None and bc is not None and br is not None:
        n = bc * br
        fi = ar_norm * bc + ac_norm
        ti = tr_norm * bc + tc_norm
        if 0 <= fi < n and 0 <= ti < n:
            val_fwd = float(lt[fi, ti])
            val_inv = float(lt[ti, fi])
            lines.append(f"los_topology[attacker_idx, target_idx] = {val_fwd:.6f} (idx {fi}->{ti})")
            lines.append(f"los_topology[target_idx, attacker_idx] = {val_inv:.6f} (idx {ti}->{fi})")
        else:
            lines.append(f"Topology indices out of bounds: fi={fi} ti={ti} n={n}")
    elif lt is None:
        from engine.hex_utils import compute_los_visibility
        wall_set = _get_wall_set(game_state)
        v_fwd = compute_los_visibility(ac_norm, ar_norm, tc_norm, tr_norm, wall_set)
        v_inv = compute_los_visibility(tc_norm, tr_norm, ac_norm, ar_norm, wall_set)
        lines.append(f"on-demand LoS (no topology): fwd={v_fwd:.6f} inv={v_inv:.6f}")
    else:
        lines.append(f"los_topology present: {lt is not None}, board_cols={bc}, board_rows={br}")

    # Episode context
    lines.append(f"episode={game_state.get('episode_number')} turn={game_state.get('turn')} phase={game_state.get('phase')}")

    lines.append("=" * 80)
    msg = "\n".join(lines)
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _get_los_visibility_state(
    game_state: Dict[str, Any],
    start_col: int,
    start_row: int,
    end_col: int,
    end_row: int,
) -> Tuple[float, bool]:
    """Return (visibility_ratio, can_see).

    Uses precomputed los_topology when available (legacy boards with .npz).
    Falls back to on-demand hex line trace (Board ×10) via hex_utils.
    Binary visibility (rule 06.01): can_see = ratio > 0 (no threshold).
    """
    board_cols = game_state.get("board_cols")
    board_rows = game_state.get("board_rows")
    if not (
        isinstance(board_cols, int)
        and isinstance(board_rows, int)
        and 0 <= start_col < board_cols
        and 0 <= start_row < board_rows
        and 0 <= end_col < board_cols
        and 0 <= end_row < board_rows
    ):
        return 0.0, False

    los_topology = game_state.get("los_topology")
    if los_topology is not None:
        from_idx = start_row * board_cols + start_col
        to_idx = end_row * board_cols + end_col
        visibility_ratio = float(los_topology[from_idx, to_idx])
    else:
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

    can_see = visibility_ratio > 0.0
    return visibility_ratio, can_see


def _get_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return cached wall_set from game_state, building it on first call."""
    cached = game_state.get("_wall_set_cache")
    if cached is not None:
        return cached
    from engine.hex_utils import build_wall_set
    ws = build_wall_set(game_state)
    game_state["_wall_set_cache"] = ws
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


def _shooter_lateral_vantage_hexes(
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    target_anchor: Tuple[int, int],
) -> List[Tuple[int, int]]:
    """Return up to 2 shooter footprint hexes that are the perpendicular extremes relative to
    the anchor→target axis (the lateral "peek" vantage points, rule: LoS from any part of the
    observing model). Empty when the footprint collapses to the anchor (single-hex base).

    Geometry is computed in the odd-q projected space (same projection as the renderer and the
    obscuring rasterizer), so "perpendicular" is geometrically faithful, then mapped back to the
    actual footprint hexes (no rounding artefacts — the points are real occupied hexes).
    """
    if len(shooter_hexes) <= 1:
        return []
    from engine.hex_utils import _hex_projected

    ax, ay = _hex_projected(int(shooter_anchor[0]), int(shooter_anchor[1]))
    tx, ty = _hex_projected(int(target_anchor[0]), int(target_anchor[1]))
    dx, dy = tx - ax, ty - ay
    if dx == 0.0 and dy == 0.0:
        return []
    perp_x, perp_y = -dy, dx  # 90° rotation of the anchor→target axis

    best_pos: Optional[Tuple[int, int]] = None
    best_neg: Optional[Tuple[int, int]] = None
    max_d = float("-inf")
    min_d = float("inf")
    for hc, hr in shooter_hexes:
        hx, hy = _hex_projected(int(hc), int(hr))
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


def _los_line_segment_clear(
    src_col: int, src_row: int, tgt_col: int, tgt_row: int,
    wall_set: Set[Tuple[int, int]],
    obscuring_by_hex: Dict[Tuple[int, int], str],
    excluded_areas: "Set[str] | frozenset",
) -> bool:
    """Ligne de visée hex dégagée entre deux hexes (cube-lerp ``hex_line``).

    Bloquée par un mur, ou par une case obscuring dont l'area n'est pas dans ``excluded_areas``
    (rule 13.10 : les areas occupées par le tireur ou la cible ne bloquent pas). PRIMITIVE DE
    TRACÉ UNIQUE partagée par le ciblage (unit→unit) et la preview (shooter→cellule), et mirroir
    du WASM ``has_los_fast``. Toute évolution de la règle de blocage se fait ICI, une seule fois.
    """
    from engine.hex_utils import hex_line
    for c, r in hex_line(int(src_col), int(src_row), int(tgt_col), int(tgt_row))[1:-1]:
        if (c, r) in wall_set:
            return False
        area = obscuring_by_hex.get((c, r))
        if area is not None and area not in excluded_areas:
            return False
    return True


def _los_hex_visible(
    shooter_anchor: Tuple[int, int],
    shooter_hexes: List[Tuple[int, int]],
    tgt_col: int, tgt_row: int,
    wall_set: Set[Tuple[int, int]],
    obscuring_by_hex: Dict[Tuple[int, int], str],
    excluded_areas: "Set[str] | frozenset",
) -> bool:
    """True si la case cible est vue depuis l'ancre OU un vantage latéral du tireur.

    « LoS depuis n'importe quelle partie du socle » (peek de coin) : l'ancre d'abord, les extrêmes
    perpendiculaires du socle en 2ᵉ chance (calculés seulement si l'ancre est bloquée). L'axe des
    perpendiculaires est TOUJOURS la case visée elle-même (peek par-cellule) — pas l'ancre de
    l'unité cible : sinon, pour une cible étalée (swarm), un latéral fixe « regarde au coin » et
    voit des cases dans une direction différente (faux positif). PRIMITIVE PARTAGÉE ciblage +
    preview + mirroir WASM : LoS identique par construction.
    """
    if _los_line_segment_clear(shooter_anchor[0], shooter_anchor[1], tgt_col, tgt_row,
                               wall_set, obscuring_by_hex, excluded_areas):
        return True
    for sc, sr in _shooter_lateral_vantage_hexes(shooter_anchor, shooter_hexes, (tgt_col, tgt_row)):
        if _los_line_segment_clear(sc, sr, tgt_col, tgt_row, wall_set, obscuring_by_hex, excluded_areas):
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
) -> Tuple[int, int, Set[Tuple[int, int]]]:
    """Count target footprint hexes reachable by a clear hex-line from the shooter.

    Rule (LoS, §1.x + terrain §13.10): the observing unit sees a target hex if a 1mm line can be
    drawn from ANY part of the observing model to that hex. We approximate "any part of the
    observer" with the anchor hex plus the two perpendicular footprint extremes (lateral peek),
    evaluated as a 2nd chance only when the anchor line is blocked. A line is blocked by a dense
    wall (always) or by an obscuring terrain area that neither the shooter nor the target occupies
    (excluding areas one or both units are within).
    Returns (visible_hexes, total_hexes, visible_hex_set).
    """
    wall_set = _get_wall_set(game_state)
    obscuring_by_hex = _get_obscuring_hex_to_area(game_state)

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
    visible = 0
    visible_hex_set: Set[Tuple[int, int]] = set()
    for tc, tr in target_hexes:
        if _los_hex_visible(anchor, shooter_hexes, tc, tr, wall_set, obscuring_by_hex,
                            excluded_areas):
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
        units_cache = require_key(game_state, "units_cache")
        entry = units_cache.get(str(unit["id"]))
        occ = entry.get("occupied_hexes") if isinstance(entry, dict) else None
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

    Returns {can_see, fully_visible, cover, visible, total, visible_cells}:
    - can_see: >= 1 target model has >= 1 base cell reachable (rule 06.01 — binary,
      per-model; no visibility ratio threshold).
    - visible_cells: sorted list of (col,row) of the target footprint hexes actually seen.
    - fully_visible: every target footprint hex is reachable (no intervening terrain).
    - cover (rule 13.08, unit-level): can_see AND ((target hideable AND within a terrain area)
      OR not fully_visible).

    All shooting LoS/cover/eligibility/observation must route through this function so the engine
    enforces one consistent visibility everywhere.

    Per-pair cache: visibility is static for a fixed board layout + unit positions, so results are
    cached by (shooter_id, target_id) and invalidated whenever any unit moves (via the global
    ``_unit_move_version``). Coordinate-only dicts (e.g. deployment exposure) have no id and bypass
    the cache. This keeps the per-step observation cost and the eligibility sweep cheap.
    """
    sid = shooter.get("id")
    tid = target.get("id")
    if sid is not None and tid is not None:
        ver = game_state["_unit_move_version"]
        holder = game_state.get("_unit_los_pair_cache")
        if holder is None or holder[0] != ver:
            holder = (ver, {})
            game_state["_unit_los_pair_cache"] = holder
        key = (str(sid), str(tid))
        cached = holder[1].get(key)
        if cached is not None:
            return cached
        result = _compute_unit_los_uncached(game_state, shooter, target)
        holder[1][key] = result
        return result
    return _compute_unit_los_uncached(game_state, shooter, target)


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

    shooter_anchor, shooter_hexes = _resolve_unit_anchor_and_footprint(
        game_state, shooter, gym_training=gym_training
    )

    # Règles 06.01 + 13.10 : visibilité binaire évaluée PAR MODÈLE cible. Un modèle est
    # visible si >= 1 cellule de son socle a une ligne dégagée ; l'unité est visible si
    # >= 1 modèle l'est. Chaque test exclut les areas obscuring du tireur et celles que
    # CE modèle occupe (exclusion par paire de modèles, pas l'union de l'escouade).
    target_model_footprints: List[List[Tuple[int, int]]] = []
    target_id = target.get("id")
    if not gym_training and target_id is not None:
        model_ids = require_key(game_state, "squad_models").get(str(target_id))
        if model_ids:
            from engine.hex_utils import compute_occupied_hexes
            models_cache = require_key(game_state, "models_cache")
            base_shape = require_key(target, "BASE_SHAPE")
            base_size = require_key(target, "BASE_SIZE")
            orientation = require_key(target, "orientation")
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
    if not target_model_footprints:
        # Pas de découpage par modèle (gym : empreinte réduite à l'ancre ; dict
        # coordonnées-seules : pas de squad) → l'empreinte entière vaut un modèle.
        _target_anchor, target_hexes = _resolve_unit_anchor_and_footprint(
            game_state, target, gym_training=gym_training
        )
        target_model_footprints.append([(int(c), int(r)) for c, r in target_hexes])

    visible = 0
    total = 0
    visible_models = 0
    visible_hex_set: Set[Tuple[int, int]] = set()
    for model_hexes in target_model_footprints:
        v, t, vset = _compute_visibility_with_obscuring(
            game_state, shooter_anchor, shooter_hexes, model_hexes[0], model_hexes
        )
        visible += v
        total += t
        visible_hex_set |= vset
        if v > 0:
            visible_models += 1
    can_see = visible_models > 0
    fully_visible = total > 0 and visible == total

    from engine.terrain_utils import model_within_terrain
    from engine.hex_utils import compute_occupied_hexes
    terrain_areas = require_key(game_state, "terrain_areas")
    cond_terrain = False

    if can_see and target.get("hideable"):
        target_id = str(require_key(target, "id"))
        squad_models_map = require_key(game_state, "squad_models")
        models_cache = require_key(game_state, "models_cache")
        model_ids = squad_models_map.get(target_id)
        if not model_ids:
            raise ValueError(f"Target unit {target_id} has no models in squad_models")
        base_shape = require_key(target, "BASE_SHAPE")
        base_size = require_key(target, "BASE_SIZE")
        orientation = require_key(target, "orientation")
        all_visible_in_terrain = True
        for mid in model_ids:
            m = models_cache.get(mid)
            if m is None:
                raise KeyError(f"Model {mid} missing from models_cache")
            if int(require_key(m, "HP_CUR")) <= 0:
                continue
            model_hexes = list(compute_occupied_hexes(
                int(m["col"]), int(m["row"]), base_shape, base_size, orientation
            ))
            if any((int(hx[0]), int(hx[1])) in visible_hex_set for hx in model_hexes):
                if not model_within_terrain(
                    int(m["col"]), int(m["row"]), base_shape, base_size, orientation,
                    terrain_areas, obscuring_only=False,
                ):
                    all_visible_in_terrain = False
                    break
        cond_terrain = all_visible_in_terrain

    cover = bool(can_see and (cond_terrain or not fully_visible))

    return {
        "can_see": can_see,
        "fully_visible": fully_visible,
        "cover": cover,
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
    from engine.hex_utils import Socle
    from engine.combat_utils import ranged_edge_distance_to_cell
    _preview_metric = _ranged_distance_metric()
    _preview_socle = Socle(
        unit["BASE_SHAPE"], unit["BASE_SIZE"], sc, sr,
        {(int(c), int(r)) for c, r in _shooter_hexes},
    )
    attack_cells: List[Dict[str, int]] = []
    cover_cells: List[Dict[str, int]] = []
    ratio_by_hex: Dict[str, float] = {}

    for col in range(board_cols):
        for row in range(board_rows):
            if row == board_rows - 1 and (col % 2) == 1:
                continue
            distance = ranged_edge_distance_to_cell(_preview_socle, sc, sr, col, row, _preview_metric)
            if distance <= 0 or distance > max_range:
                continue
            hex_area = obscuring_by_hex.get((col, row))
            _excluded_areas = frozenset((hex_area,)) if hex_area is not None else frozenset()
            # Même primitive que le ciblage → ancre + vantages latéraux (peek de coin).
            visible = _los_hex_visible(
                (sc, sr), _shooter_hexes, col, row, wall_set, obscuring_by_hex, _excluded_areas
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


def _hex_to_pixel(col: int, row: int, hex_radius: float) -> Tuple[float, float]:
    """Convert offset hex coordinates to pixel center coordinates."""
    hex_width = 1.5 * hex_radius
    hex_height = math.sqrt(3.0) * hex_radius
    x = col * hex_width
    y = row * hex_height + ((col % 2) * hex_height) / 2.0
    return x, y


def _line_segments_intersect(
    line1_start: Tuple[float, float],
    line1_end: Tuple[float, float],
    line2_start: Tuple[float, float],
    line2_end: Tuple[float, float],
) -> bool:
    """Return whether two 2D line segments intersect."""
    d1x = line1_end[0] - line1_start[0]
    d1y = line1_end[1] - line1_start[1]
    d2x = line2_end[0] - line2_start[0]
    d2y = line2_end[1] - line2_start[1]
    d3x = line2_start[0] - line1_start[0]
    d3y = line2_start[1] - line1_start[1]

    cross1 = d1x * d2y - d1y * d2x
    if abs(cross1) < 0.0001:
        return False
    cross2 = d3x * d2y - d3y * d2x
    cross3 = d3x * d1y - d3y * d1x
    t1 = cross2 / cross1
    t2 = cross3 / cross1
    return 0.0 <= t1 <= 1.0 and 0.0 <= t2 <= 1.0


def _line_passes_through_hex(
    start_point: Tuple[float, float],
    end_point: Tuple[float, float],
    hex_col: int,
    hex_row: int,
    hex_radius: float,
) -> bool:
    """Return whether the segment intersects the boundary of a wall hex polygon."""
    center_x, center_y = _hex_to_pixel(hex_col, hex_row, hex_radius)
    hex_points: List[Tuple[float, float]] = []
    for i in range(6):
        angle = (i * math.pi) / 3.0
        px = center_x + hex_radius * math.cos(angle)
        py = center_y + hex_radius * math.sin(angle)
        hex_points.append((px, py))

    for i in range(len(hex_points)):
        p1 = hex_points[i]
        p2 = hex_points[(i + 1) % len(hex_points)]
        if _line_segments_intersect(start_point, end_point, p1, p2):
            return True
    return False


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
        # AI_TURN.md Line 105: P1 Move -> P1 Shoot -> P1 Charge -> P1 Fight
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
        # AI_TURN.md Line 105: P2 Move -> P2 Shoot -> P2 Charge -> P2 Fight
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
    - unit's _shooting_with_pistol
    - unit's SHOOT_LEFT (reset to 0)
    
    Called BEFORE end_activation to clean up state, exactly like movement_clear_preview in MOVE.
    
    CRITICAL: Only called when arg5=1 (actually ending activation).
    If arg5=0 (NOT_REMOVED), state is preserved to continue activation.
    """
    # Clear active unit
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]
    
    # Clear unit activation state
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    if "_pool_from_cache" in unit:
        del unit["_pool_from_cache"]
    if "_pool_cache_key" in unit:
        del unit["_pool_cache_key"]
    # AI_TURN.md: Clean up los_cache at end of activation
    if "los_cache" in unit:
        del unit["los_cache"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]
    if "_shooting_with_pistol" in unit:
        del unit["_shooting_with_pistol"]
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
    if "_current_shoot_nb" in unit:
        del unit["_current_shoot_nb"]
    if "_rapid_fire_context_weapon_index" in unit:
        del unit["_rapid_fire_context_weapon_index"]
    if "_rapid_fire_base_nb" in unit:
        del unit["_rapid_fire_base_nb"]
    if "_rapid_fire_shots_fired" in unit:
        del unit["_rapid_fire_shots_fired"]
    if "_rapid_fire_bonus_total" in unit:
        del unit["_rapid_fire_bonus_total"]
    if "_rapid_fire_rule_value" in unit:
        del unit["_rapid_fire_rule_value"]
    if "_rapid_fire_bonus_shot_current" in unit:
        del unit["_rapid_fire_bonus_shot_current"]
    if "_rapid_fire_bonus_applied_by_weapon" in unit:
        del unit["_rapid_fire_bonus_applied_by_weapon"]
    if "advance_range" in unit:
        del unit["advance_range"]
    unit["SHOOT_LEFT"] = 0

def _get_shooting_context(game_state: Dict[str, Any], unit: Dict[str, Any]) -> str:
    """Determine current shooting context for nested behavior."""
    # Direct field access
    if "selected_target_id" in unit and unit["selected_target_id"]:
        return "target_selected"
    else:
        return "no_target_selected"


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
    enemies = [
        enemy_id
        for enemy_id, cache_entry in units_cache.items()
        if int(cache_entry["player"]) != unit_player
    ]
    if not enemies:
        return destinations[0]

    # Portée/positionnement post-tir en euclidien bord-à-bord (sélecteur `ranged`).
    from engine.combat_utils import (
        ranged_edge_distance,
        ranged_edge_distance_to_cell,
        socle_from_cache_entry,
    )
    metric = _ranged_distance_metric()
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
    update_units_cache_position(game_state, unit_id_str, dest_col_int, dest_row_int)

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
    _invalidate_los_cache_for_moved_unit(game_state, unit_id_str, old_col=orig_col, old_row=orig_row)
    game_state["_unit_move_version"] += 1
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
                                     action_type: Optional[str] = None, include_attack_results: bool = True) -> Tuple[bool, Dict[str, Any]]:
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

    # Optional post-shoot movement rule: move_after_shooting.
    # Only relevant when a real shooting activation is ending.
    if (
        arg5 == 1
        and arg1 == ACTION
        and arg3 == SHOOTING
        and not unit.get("_move_after_shooting_resolved", False)
        and _unit_has_rule(unit, "move_after_shooting")
    ):
        move_after_shooting_distance = _get_required_rule_int_argument(
            unit, "move_after_shooting", _MOVE_AFTER_SHOOTING_DISTANCE_ARG
        )
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
    
    # Auto-select next unit only for AI-controlled player.
    pool = require_key(game_state, "shoot_activation_pool")
    auto_selected_next_unit = False
    if pool:
        cfg = require_key(game_state, "config")
        if _should_auto_activate_next_shooting_unit(game_state, cfg, pool):
            game_state["active_shooting_unit"] = pool[0]
            auto_selected_next_unit = True
        elif "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
    
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
            if arg3 == "ADVANCE":
                action_type = "advance"
            elif arg3 == "SHOOTING":
                action_type = "shoot"
            else:
                action_type = "shoot"
        else:
            action_type = "shoot"
    
    # Update result with action type and activation_complete (like _handle_skip_action in MOVE)
    result.update({
        "action": action_type,
        "unitId": unit["id"],
        "activation_complete": True,
        "phase": "shoot",
    })
    # Backend is source of truth: when activation really ends and no next unit is auto-activated,
    # explicitly instruct frontend to return to neutral select state.
    if arg5 == 1 and not auto_selected_next_unit and "active_shooting_unit" not in game_state:
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

# DEPRECATED: _shooting_activation_end is replaced by _handle_shooting_end_activation + end_activation
# This function is kept for backward compatibility but should not be used in new code
# All calls have been migrated to use end_activation directly (aligned with MOVE phase)
def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """
    DEPRECATED: Use _handle_shooting_end_activation instead (aligned with MOVE phase).
    
    This function is kept for backward compatibility but should not be used in new code.
    All calls have been migrated to use end_activation directly via _handle_shooting_end_activation.
    
    Migration path:
    - Replace all calls to _shooting_activation_end with _handle_shooting_end_activation
    - For arg5=0 (NOT_REMOVED), call end_activation directly instead
    """
    # Redirect to new implementation
    return _handle_shooting_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)


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
    # AI_TURN.md COMPLIANCE: Pool is built once at phase start (STEP 1: ELIGIBILITY CHECK)
    # Units are removed ONLY via:
    # 1. end_activation() with Arg4 = SHOOTING (when unit finishes activation)
    # 2. _remove_dead_unit_from_pools() (when unit dies)
    # No filtering or modification of pool in execute_action - this is not described in AI_TURN.md
    
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
        has_advance_choice = bool(result_payload.get("allow_advance")) or bool(result_payload.get("can_advance"))
        requires_manual_weapon_selection = bool(result_payload.get("weapon_selection_required"))

        if requires_manual_weapon_selection or not (has_target_choices or has_advance_choice):
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
                f"allow_advance={result_payload.get('allow_advance')}, "
                f"can_advance={result_payload.get('can_advance')}, "
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
                f"unit_can_advance={unit.get('_can_advance')}, "
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
    if action_type in ["shoot", "advance", "move_after_shooting"]:
        unit_id_str = str(unit_id)
        active_unit_id = str(active_shooting_unit) if active_shooting_unit is not None else None
        if active_unit_id and active_unit_id != unit_id_str:
            raise ValueError(
                f"shoot/advance/move_after_shooting called for non-active unit: "
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
                        or activation_result.get("action") == "empty_target_advance_available"
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

    elif action_type == "advance":
        # ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase
        return _handle_advance_action(game_state, unit, action, config)

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
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
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
        
        # AI_TURN.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # AI_TURN.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to AI_TURN.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = require_key(game_state, "shoot_activation_pool")
        if not pool_after_removal:
            # Pool is empty - phase is complete (AI_TURN.md LINE 794: "NO → End of shooting phase")
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
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
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
        
        # AI_TURN.md LINE 997: "WAIT_ACTION → UNIT_ACTIVABLE_CHECK: Always (end activation)"
        # After end_activation, return to UNIT_ACTIVABLE_CHECK which checks if pool is empty
        # AI_TURN.md LINE 781: "shoot_activation_pool NOT empty?" - check pool directly
        # CRITICAL: According to AI_TURN.md, pool should never contain dead units, so checking pool emptiness is correct
        pool_after_removal = require_key(game_state, "shoot_activation_pool")
        if not pool_after_removal:
            # Pool is empty - phase is complete (AI_TURN.md LINE 794: "NO → End of shooting phase")
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


def _calculate_save_target(target: Dict[str, Any], ap: int, save_bonus: int = 0) -> int:
    """Calculate save target with AP, optional save bonus, and invulnerable save."""
    # Direct UPPERCASE field access
    if "ARMOR_SAVE" not in target:
        raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
    if "INVUL_SAVE" not in target:
        raise KeyError(f"Target missing required 'INVUL_SAVE' field: {target}")
    armor_save = target["ARMOR_SAVE"]
    invul_save = target["INVUL_SAVE"]
    
    if not isinstance(save_bonus, int):
        raise TypeError(f"save_bonus must be int, got {type(save_bonus).__name__}")
    if save_bonus < 0:
        raise ValueError(f"save_bonus must be >= 0, got {save_bonus}")
    effective_save_bonus = min(1, save_bonus)
    # Apply AP to armor save (AP is negative, subtract to worsen save: 3+ with -1 AP = 4+)
    modified_armor_save = armor_save - ap
    # Save bonus improves armor save target number (cannot stack above +1 total).
    modified_armor_save = modified_armor_save - effective_save_bonus
    
    # Handle invulnerable saves: 0 means no invul save, use 7 (impossible)
    effective_invul = invul_save if invul_save > 0 else 7
    
    # Use best available save (lower target number is better)
    best_save = min(modified_armor_save, effective_invul)
    
    # Cap impossible saves at 7, minimum save is 2+
    return max(2, min(best_save, 6))


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

    Strict semantics:
    - True as soon as one shot is fired in current weapon context
      (`_rapid_fire_shots_fired > 0`), even if current weapon is not exhausted yet.
    - True if any weapon is marked exhausted (`weapon["shot"] == 1`).
    """
    if "_rapid_fire_shots_fired" in unit:
        shots_fired_current_context = require_key(unit, "_rapid_fire_shots_fired")
        if not isinstance(shots_fired_current_context, int):
            raise TypeError(
                f"unit['_rapid_fire_shots_fired'] must be int, "
                f"got {type(shots_fired_current_context).__name__}"
            )
        if shots_fired_current_context > 0:
            return True
    rng_weapons = require_key(unit, "RNG_WEAPONS")
    for weapon in rng_weapons:
        if require_key(weapon, "shot") == 1:
            return True
    return False


def _shooting_activation_has_committed_action(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """
    A shooting activation is committed after the first shot or after an advance.
    Once committed, it cannot be postponed back into shoot_activation_pool.
    """
    if _shooting_activation_has_started_or_completed_advance(game_state, unit):
        return True
    if _unit_has_shot_with_any_weapon(unit):
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


def _keep_committed_shooting_activation_waiting(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    error_code: str,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Preserve the active shooting selection after an invalid postpone/switch attempt.

    This keeps the backend HP blink contract intact: if the active unit still has target
    ids in its pool, the response includes waiting_for_player + start_blinking +
    blinking_units for that same active unit.
    """
    unit_id = require_key(unit, "id")
    game_state["active_shooting_unit"] = str(unit_id)
    valid_targets = require_key(unit, "valid_target_pool")
    response: Dict[str, Any] = {
        "action": "no_effect",
        "unitId": unit_id,
        "error": error_code,
        "waiting_for_player": True,
        "phase": "shoot",
    }
    if valid_targets:
        response["valid_targets"] = valid_targets
        response["blinking_units"] = valid_targets
        response["start_blinking"] = True
    if "available_weapons" in unit:
        response["available_weapons"] = unit["available_weapons"]
    return True, response


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


def _has_los_to_enemies_within_range(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """Check if any enemy is within weapon range using footprint distance (§3.3)."""
    from engine.utils.weapon_helpers import get_max_ranged_range
    from engine.hex_utils import min_distance_between_sets
    max_range = get_max_ranged_range(unit)
    if max_range <= 0:
        return False

    unit_player = int(unit["player"]) if unit["player"] is not None else None
    units_cache = require_key(game_state, "units_cache")
    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    for enemy_id, cache_entry in units_cache.items():
        enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if enemy_player != unit_player:
            enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            distance = min_distance_between_sets(unit_fp, enemy_fp, max_distance=max_range)
            if distance <= max_range:
                return True

    return False

def _get_unit_by_id(game_state: Dict[str, Any], unit_id: str) -> Optional[Dict[str, Any]]:
    """Get unit by ID from game state. Compare both sides as strings for int/str ID mismatch.
    REQUIRES: game_state['unit_by_id'] (built at reset/reload). Absence = bug, raise explicitly.
    """
    unit_by_id = require_key(game_state, "unit_by_id")
    return unit_by_id.get(str(unit_id))


# ============================================================================
# ADVANCE_IMPLEMENTATION: Advance action handler
# ============================================================================

def _handle_advance_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase.

    Board ×10 (Documentation/TODO/Boardx10-final.md §9.0): roll D6 (affichage 1–6 inch équivalent),
    budget de déplacement en sous-hex = jet × ``inches_to_subhex`` (ex. ×10 → 10–60).
    Pathfinding identique à la phase move via ``movement_build_valid_destinations_pool`` (MOVE temporaire).
    After advance: cannot shoot (unless Assault weapon), cannot charge.
    Unit is only marked as "advanced" if it actually moved to a different hex.
    """
    import random
    from engine.combat_utils import get_hex_neighbors, is_hex_adjacent_to_enemy
    from engine.phase_handlers.movement_handlers import (
        movement_build_valid_destinations_pool,
        _select_strategic_destination,
    )
    from .shared_utils import build_enemy_adjacent_hexes
    
    unit_id = unit["id"]
    orig_col, orig_row = require_unit_position(unit, game_state)
    is_gym_training = bool(config.get("gym_training_mode", False))
    is_pve_ai = bool(config.get("pve_mode", False)) and int(unit["player"]) == 2
    unit_id_str = str(unit_id)

    # Hard invariant: at most one ADVANCE per unit in shooting phase.
    if unit_id_str in require_key(game_state, "units_advanced"):
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["advance_rejected"] = True
        result["skip_reason"] = "cannot_advance_twice_in_shoot_phase"
        return success, result
    
    # CRITICAL: Cannot advance if unit has already shot -> SKIP (unit cannot act)
    has_shot = _unit_has_shot_with_any_weapon(unit)
    if has_shot:
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            unit_id_str = str(unit["id"])
            rng_weapons = require_key(unit, "RNG_WEAPONS")
            shot_flags = [weapon.get("shot") for weapon in rng_weapons]
            activation_started = unit.get("_shoot_activation_started", False)
            add_debug_file_log(
                game_state,
                f"[ADVANCE SKIP] E{episode} T{turn} Unit {unit_id_str} "
                f"reason=cannot_advance_after_shooting activation_started={activation_started} "
                f"weapon_shot_flags={shot_flags}"
            )
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["advance_rejected"] = True
        result["skip_reason"] = "cannot_advance_after_shooting"
        return success, result

    # Re-evaluate adjacency on current board state right before advance execution.
    # Reactive moves may have changed engagement after activation start.
    unit_is_adjacent_now = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    unit["_can_advance"] = not unit_is_adjacent_now
    if unit_is_adjacent_now:
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            unit_id_str = str(unit["id"])
            unit_player_int = int(unit["player"]) if unit["player"] is not None else None
            neighbors = set(get_hex_neighbors(orig_col, orig_row))
            units_cache = require_key(game_state, "units_cache")
            adjacent_enemies = []
            for enemy_id, cache_entry in units_cache.items():
                enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
                if enemy_player != unit_player_int:
                    enemy_col, enemy_row = cache_entry["col"], cache_entry["row"]
                    if (enemy_col, enemy_row) in neighbors:
                        adjacent_enemies.append(f"{enemy_id}@({enemy_col},{enemy_row})")
            add_debug_file_log(
                game_state,
                f"[ADVANCE DEBUG] E{episode} T{turn} _handle_advance_action: "
                f"Unit {unit_id_str} at ({orig_col},{orig_row}) advance blocked "
                f"(adjacent_enemies={adjacent_enemies}, dynamic_recheck=True)"
            )
        success, result = _handle_shooting_end_activation(
            game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
        )
        result["advance_rejected"] = True
        result["skip_reason"] = "cannot_advance_adjacent_to_enemy"
        return success, result

    if game_state.get("debug_mode", False):
        from engine.game_utils import add_debug_file_log
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        unit_id_str = str(unit["id"])
        unit_player_int = int(unit["player"]) if unit["player"] is not None else None
        neighbors = set(get_hex_neighbors(orig_col, orig_row))
        units_cache = require_key(game_state, "units_cache")
        adjacent_enemies = []
        for enemy_id, cache_entry in units_cache.items():
            enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
            if enemy_player != unit_player_int:
                enemy_col, enemy_row = cache_entry["col"], cache_entry["row"]
                if (enemy_col, enemy_row) in neighbors:
                    adjacent_enemies.append(f"{enemy_id}@({enemy_col},{enemy_row})")
        if adjacent_enemies:
            add_debug_file_log(
                game_state,
                f"[ADVANCE DEBUG] E{episode} T{turn} _handle_advance_action: "
                f"Unit {unit_id_str} at ({orig_col},{orig_row}) advance allowed "
                f"while adjacent_enemies={adjacent_enemies}"
            )
    
    scale = int(require_key(game_state, "inches_to_subhex"))
    gr = require_key(config, "game_rules")
    advance_cap_subhex = require_key(gr, "advance_distance_range")
    remainder = advance_cap_subhex % scale
    if remainder != 0:
        raise ValueError(
            f"advance_distance_range ({advance_cap_subhex} sub-hex) must be divisible by "
            f"inches_to_subhex ({scale}) so advance dice maps to GW inches (Boardx10-final §9.0); "
            f"remainder={remainder}"
        )
    advance_dice_max = advance_cap_subhex // scale
    if advance_dice_max < 1:
        raise ValueError(
            f"Invalid advance dice max derived from config: advance_dice_max={advance_dice_max} "
            f"(advance_cap_subhex={advance_cap_subhex}, scale={scale})"
        )

    # ``unit["advance_range"]`` stores the D6 face (1..advance_dice_max) for display and multi-step selection
    if "advance_range" in unit and unit["advance_range"] is not None:
        advance_roll = int(unit["advance_range"])
    else:
        advance_roll = random.randint(1, advance_dice_max)
        unit["advance_range"] = advance_roll

    advance_move_budget = advance_roll * scale

    from engine.perf_timing import perf_timing_enabled, append_perf_timing_line
    _adv_pt = perf_timing_enabled(game_state)
    _t_adv0 = time.perf_counter() if _adv_pt else None

    # Build valid destinations using BFS (same as movement phase)
    original_move = unit["MOVE"]
    unit["MOVE"] = advance_move_budget

    # Use movement pathfinding to get valid destinations
    # "_valid_destinations" is injected by the first (no-dest) call to avoid a second BFS
    if "_valid_destinations" in action:
        valid_destinations = action["_valid_destinations"]
    else:
        valid_destinations = movement_build_valid_destinations_pool(game_state, unit_id)

    # Restore original MOVE
    unit["MOVE"] = original_move
    _t_adv_pool = time.perf_counter() if _adv_pt else None

    # Check if destination provided in action
    dest_col = action.get("destCol")
    dest_row = action.get("destRow")

    if dest_col is not None and dest_row is not None:
        # CRITICAL: Convert coordinates to int for consistent tuple comparison
        dest_col, dest_row = int(dest_col), int(dest_row)
        
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            unit_id_str = str(unit["id"])
            units_cache = require_key(game_state, "units_cache")
            occupants = []
            for check_id, check_entry in units_cache.items():
                check_col, check_row = check_entry["col"], check_entry["row"]
                if check_col == dest_col and check_row == dest_row:
                    check_hp = get_hp_from_cache(str(check_id), game_state)
                    occupants.append(f"{check_id}@({check_col},{check_row}) HP={check_hp}")
            add_debug_file_log(
                game_state,
                f"[ADVANCE DEBUG] E{episode} T{turn} _handle_advance_action: "
                f"Unit {unit_id_str} dest=({dest_col},{dest_row}) "
                f"valid_destinations={len(valid_destinations)} occupants={occupants}"
            )
        
        # Destination provided - validate and execute
        if (dest_col, dest_row) not in valid_destinations:
            return False, {"error": "invalid_advance_destination", "destination": (dest_col, dest_row)}

        from engine.hex_utils import min_distance_between_sets
        from .shared_utils import get_engagement_zone, compute_candidate_footprint
        engagement_zone = get_engagement_zone(game_state)
        unit_player_int = int(require_key(unit, "player"))
        units_cache = require_key(game_state, "units_cache")
        candidate_fp = compute_candidate_footprint(dest_col, dest_row, unit, game_state)
        for enemy_id, cache_entry in units_cache.items():
            enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
            if enemy_player == unit_player_int:
                continue
            enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            if min_distance_between_sets(candidate_fp, enemy_fp, max_distance=engagement_zone) <= engagement_zone:
                return False, {
                    "error": "advance_destination_adjacent_to_enemy",
                    "enemy_id": enemy_id,
                    "destination": (dest_col, dest_row),
                }
        _t_adv_dest_check = time.perf_counter() if _adv_pt else None

        # CRITICAL: Final occupation check IMMEDIATELY before position assignment
        dest_col_int, dest_row_int = int(dest_col), int(dest_row)

        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "shoot")
        from engine.game_utils import conditional_debug_print
        conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Unit {unit['id']} checking advance destination ({dest_col_int},{dest_row_int})")

        unit_id_str = str(unit["id"])
        candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, unit, game_state)
        if not is_placement_valid_with_clearance(
            game_state, candidate_fp,
            shape=unit["BASE_SHAPE"], base_size=unit["BASE_SIZE"],
            col=dest_col_int, row=dest_row_int, exclude_unit_id=unit_id_str,
        ):
            if "console_logs" not in game_state:
                game_state["console_logs"] = []
            log_msg = f"[ADVANCE COLLISION PREVENTED] E{episode} T{turn} {phase}: Unit {unit['id']} cannot advance to ({dest_col_int},{dest_row_int}) - footprint blocked"
            from engine.game_utils import add_console_log, add_debug_log
            from engine.game_utils import safe_print
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
            return False, {
                "error": "advance_destination_occupied",
                "destination": (dest_col, dest_row)
            }
        
        conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Unit {unit['id']} advance destination ({dest_col_int},{dest_row_int}) is FREE - proceeding with advance")
        _t_adv_occ_check = time.perf_counter() if _adv_pt else None

        # Execute advance movement
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col},{dest_row}) via ADVANCE"
        from engine.game_utils import add_console_log, add_debug_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)

        from engine.game_utils import conditional_debug_print
        dest_col_int, dest_row_int = normalize_coordinates(dest_col, dest_row)
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: Setting col={dest_col_int} row={dest_row_int}")
        from engine.combat_utils import set_unit_coordinates
        set_unit_coordinates(unit, dest_col_int, dest_row_int)
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: col set to {unit['col']}")
        conditional_debug_print(game_state, f"[DIRECT ASSIGNMENT] E{episode} T{turn} {phase} Unit {unit['id']}: row set to {unit['row']}")

        # Capture old footprint before cache update (for multi-hex adjacency delta)
        adv_uid_str = str(unit["id"])
        adv_old_entry = require_key(game_state, "units_cache").get(adv_uid_str)
        adv_old_occupied = adv_old_entry.get("occupied_hexes") if adv_old_entry else None

        update_units_cache_position(game_state, adv_uid_str, dest_col_int, dest_row_int)

        adv_new_entry = require_key(game_state, "units_cache").get(adv_uid_str)
        adv_new_occupied = adv_new_entry.get("occupied_hexes") if adv_new_entry else None
        _t_adv_pos_update = time.perf_counter() if _adv_pt else None

        moved_unit_player = int(require_key(unit, "player"))
        update_enemy_adjacent_caches_after_unit_move(
            game_state,
            moved_unit_player=moved_unit_player,
            old_col=orig_col,
            old_row=orig_row,
            new_col=dest_col_int,
            new_row=dest_row_int,
            old_occupied=adv_old_occupied,
            new_occupied=adv_new_occupied,
        )
        _t_adv_adj_cache = time.perf_counter() if _adv_pt else None

        # Check if unit actually moved (for cache invalidation and logging)
        actually_moved = (orig_col != dest_col) or (orig_row != dest_row)

        if actually_moved:
            _invalidate_los_cache_for_moved_unit(game_state, unit["id"], old_col=orig_col, old_row=orig_row)
            game_state["_unit_move_version"] += 1
            build_unit_los_cache(game_state, unit["id"])
            _t_adv_los = time.perf_counter() if _adv_pt else None

            from .movement_handlers import _invalidate_all_destination_pools_after_movement
            _invalidate_all_destination_pools_after_movement(game_state)

            maybe_resolve_reactive_move(
                game_state=game_state,
                moved_unit_id=str(unit["id"]),
                from_col=orig_col,
                from_row=orig_row,
                to_col=dest_col_int,
                to_row=dest_row_int,
                move_kind="advance",
                move_cause="normal",
            )
            _t_adv_reactive = time.perf_counter() if _adv_pt else None

            if _adv_pt and _t_adv0 is not None:
                _ep = game_state.get("episode_number", "?")
                _tu = game_state.get("turn", "?")
                _uid = str(unit["id"])
                _t_adv_pool_v        = require_present(_t_adv_pool, "_t_adv_pool")
                _t_adv_dest_check_v  = require_present(_t_adv_dest_check, "_t_adv_dest_check")
                _t_adv_occ_check_v   = require_present(_t_adv_occ_check, "_t_adv_occ_check")
                _t_adv_pos_update_v  = require_present(_t_adv_pos_update, "_t_adv_pos_update")
                _t_adv_adj_cache_v   = require_present(_t_adv_adj_cache, "_t_adv_adj_cache")
                _t_adv_los_v         = require_present(_t_adv_los, "_t_adv_los")
                _t_adv_reactive_v    = require_present(_t_adv_reactive, "_t_adv_reactive")
                _pool_s  = (_t_adv_pool_v        - _t_adv0)              if _t_adv_pool_v        else 0.0
                _dchk_s  = (_t_adv_dest_check_v  - _t_adv_pool_v)        if _t_adv_dest_check_v  else 0.0
                _ochk_s  = (_t_adv_occ_check_v   - _t_adv_dest_check_v)  if _t_adv_occ_check_v   else 0.0
                _pos_s   = (_t_adv_pos_update_v  - _t_adv_occ_check_v)   if _t_adv_pos_update_v  else 0.0
                _adj_s   = (_t_adv_adj_cache_v   - _t_adv_pos_update_v)  if _t_adv_adj_cache_v   else 0.0
                _los_s   = (_t_adv_los_v         - _t_adv_adj_cache_v)   if _t_adv_los_v         else 0.0
                _react_s = (_t_adv_reactive_v    - _t_adv_los_v)         if _t_adv_reactive_v    else 0.0
                _total_s = _t_adv_reactive_v - _t_adv0
                append_perf_timing_line(
                    f"ADVANCE_TIMING episode={_ep} turn={_tu} unitId={_uid!r} "
                    f"pool_s={_pool_s:.6f} dest_check_s={_dchk_s:.6f} occ_check_s={_ochk_s:.6f} "
                    f"pos_update_s={_pos_s:.6f} adj_cache_s={_adj_s:.6f} "
                    f"los_cache_s={_los_s:.6f} reactive_s={_react_s:.6f} total_s={_total_s:.6f}"
                )
        
        # CRITICAL FIX: Mark unit as advanced REGARDLESS of whether it moved
        # Units must be marked as advanced even if they stay in place (for ASSAULT weapon rule)
        # AI_TURN.md ligne 666: Log: end_activation(ACTION, 1, ADVANCE, SHOOTING, 0)
        # This marks units_advanced (ligne 665 describes what this does)
        # arg5=0 means NOT_REMOVED (do not remove from pool, do not end activation)
        # We track the advance but continue to shooting, so we don't use the return value
        # CRITICAL: Call end_activation directly (not _handle_shooting_end_activation) because:
        # 1. arg5=0 means NOT_REMOVED - we don't want to clear activation state
        # 2. We don't want to trigger phase_complete check
        # 3. This is just a tracking/logging call, not an actual activation end
        from engine.phase_handlers.generic_handlers import end_activation
        end_activation(game_state, unit, ACTION, 1, ADVANCE, NOT_REMOVED, 0)
        
        # Log the advance action
        if "action_logs" not in game_state:
            game_state["action_logs"] = []

        append_action_log(
            game_state,
            {
                "type": "advance",
                "message": f"Unit {unit_id} ({orig_col}, {orig_row}) ADVANCED to ({dest_col}, {dest_row}) (Roll: {advance_roll})",
                "turn": game_state.get("turn", 1),
                "phase": "shoot",
                "unitId": unit_id,
                "player": unit["player"],
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_roll,
                "advance_max_subhex": advance_move_budget,
                "advance_strategy": action.get("advance_strategy"),
                "actually_moved": actually_moved,
                "timestamp": "server_time",
            },
        )
        
        # Clean up advance state AFTER logging
        if "advance_range" in unit:
            del unit["advance_range"]
        
        # AI_TURN.md STEP 4: ADVANCE_ACTION post-advance logic (lines 666-679)
        # Continue only if unit actually moved
        if not actually_moved:
            # In gym/PvE automatic mode, staying on same hex must close activation to avoid deadlock loops.
            if is_gym_training or is_pve_ai:
                success, result = _handle_shooting_end_activation(
                    game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
                )
                result["advance_rejected"] = True
                result["skip_reason"] = "no_effective_advance_movement"
                return success, result
            # Unit did not advance -> Go back to STEP 3: ACTION_SELECTION
            return True, {
                "waiting_for_player": True,
                "action": "advance_cancelled",
                "unitId": unit_id
            }
        
        # Clear valid_target_pool
        if "valid_target_pool" in unit:
            del unit["valid_target_pool"]
        
        # Update capabilities
        # CAN_ADVANCE = false (unit has advanced, cannot advance again)
        unit["_can_advance"] = False
        
        # CRITICAL: Call weapon_availability_check FIRST to get usable weapons
        # Then rebuild valid_target_pool using those usable weapons
        weapon_rule = require_key(game_state, "weapon_rule")
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status=1, adjacent_status=0
        )
        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        
        # CRITICAL: Rebuild valid_target_pool using shooting_build_valid_target_pool for consistency
        # This wrapper automatically determines context (advance_status=1 after advance, adjacent_status=0)
        # and handles cache correctly
        valid_target_pool = shooting_build_valid_target_pool(game_state, unit_id)
        unit["valid_target_pool"] = valid_target_pool
        # CAN_SHOOT = (weapon_available_pool NOT empty)
        can_shoot = len(usable_weapons) > 0
        unit["_can_shoot"] = can_shoot
        
        # Pre-select first available weapon
        if usable_weapons:
            first_weapon = usable_weapons[0]
            unit["selectedRngWeaponIndex"] = first_weapon["index"]
            selected_weapon = require_key(first_weapon, "weapon")
            nb_roll = resolve_dice_value(require_key(selected_weapon, "NB"), "shooting_nb_post_advance")
            unit["SHOOT_LEFT"] = nb_roll
            unit["_current_shoot_nb"] = nb_roll
            _append_shoot_nb_roll_info_log(game_state, unit, selected_weapon, nb_roll)
        else:
            unit["SHOOT_LEFT"] = 0
        
        # valid_target_pool NOT empty AND CAN_SHOOT = true?
        if valid_target_pool and can_shoot:
            # YES -> SHOOTING ACTIONS AVAILABLE (post-advance) -> Go to STEP 5: ADVANCED_SHOOTING_ACTION_SELECTION
            # Mark unit as currently active (required for frontend to show weapon icon)
            game_state["active_shooting_unit"] = unit_id
            available_weapons = [
                {"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")}
                for w in weapon_available_pool
            ]
            # Return advance action so it gets logged as its own step
            cover_by_unit_id = build_cover_by_unit_id_for_valid_targets(game_state, unit, valid_target_pool)
            return True, {
                "action": "advance",
                "unitId": unit_id,
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_roll,
                "advance_max_subhex": advance_move_budget,
                "advance_strategy": action.get("advance_strategy"),
                "actually_moved": actually_moved,
                "blinking_units": valid_target_pool,
                "start_blinking": True,
                "waiting_for_player": True,
                "available_weapons": available_weapons,
                "cover_by_unit_id": cover_by_unit_id,
                "hidden_too_far_by_unit_id": build_hidden_too_far_by_unit_id(game_state, unit),
            }
        else:
            # NO -> Unit advanced but no valid targets -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
            # arg3="ADVANCE", arg4="SHOOTING", arg5=1 (remove from pool)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, ADVANCE, SHOOTING, 1, action_type="advance")
            result.update({
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_roll,
                "advance_max_subhex": advance_move_budget,
                "advance_strategy": action.get("advance_strategy"),
                "actually_moved": actually_moved
            })
            return success, result
    else:
        # No destination - return valid destinations for player/AI to choose
        # For AI, auto-select best destination
        movable_destinations = [d for d in valid_destinations if int(d[0]) != int(orig_col) or int(d[1]) != int(orig_row)]

        # AI_TURN.md §STEP4: valid_advance_destinations must exclude enemy-adjacent hexes
        # Filter BEFORE auto-select to prevent advance_destination_adjacent_to_enemy loop
        from .shared_utils import get_engagement_zone
        from engine.hex_utils import dilate_hex_set_unbounded, precompute_footprint_offsets
        _ez = get_engagement_zone(game_state)
        _units_cache = require_key(game_state, "units_cache")
        _unit_player = int(unit["player"]) if unit["player"] is not None else None
        _forbidden_zone: set = set()
        for _ce in _units_cache.values():
            if int(_ce.get("player", _unit_player)) != _unit_player:
                _enemy_fp = _ce.get("occupied_hexes", {(_ce["col"], _ce["row"])})
                _forbidden_zone.update(dilate_hex_set_unbounded(_enemy_fp, _ez))
        if _forbidden_zone:
            _base_shape = unit["BASE_SHAPE"]
            _base_size = unit["BASE_SIZE"]
            _orientation = int(require_key(unit, "orientation")) if "orientation" in unit else 0
            if _ez <= 1 or _base_size == 1:
                movable_destinations = [
                    d for d in movable_destinations
                    if (d[0], d[1]) not in _forbidden_zone
                ]
            else:
                _off_even, _off_odd = precompute_footprint_offsets(_base_shape, _base_size, _orientation)
                movable_destinations = [
                    d for d in movable_destinations
                    if not any(
                        (d[0] + dc, d[1] + dr) in _forbidden_zone
                        for dc, dr in (_off_even if d[0] % 2 == 0 else _off_odd)
                    )
                ]

        if (is_gym_training or is_pve_ai) and movable_destinations:
            # Auto-select destination using the strategy carried by the action dict (default: aggressive)
            strategy_id = require_key(action, "advance_strategy")
            action["_valid_destinations"] = valid_destinations
            remaining = list(movable_destinations)
            while remaining:
                best_dest = _select_strategic_destination(strategy_id, remaining, unit, game_state)
                action["destCol"] = best_dest[0]
                action["destRow"] = best_dest[1]
                result = _handle_advance_action(game_state, unit, action, config)
                if result[0] or result[1].get("error") not in ("advance_destination_adjacent_to_enemy", "advance_destination_occupied"):
                    action.pop("_valid_destinations", None)
                    return result
                remaining.remove(best_dest)
            action.pop("_valid_destinations", None)
        
        # CRITICAL FIX: If no valid destinations in gym training, end activation to prevent infinite loop
        if (is_gym_training or is_pve_ai) and not movable_destinations:
            # No valid destinations - SKIP (cannot advance)
            success, result = _handle_shooting_end_activation(
                game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="skip"
            )
            result["advance_rejected"] = True
            result["skip_reason"] = "no_valid_advance_destinations"
            return success, result
        
        # Human player - return destinations for UI
        # ADVANCE_IMPLEMENTATION_PLAN.md Phase 5: Use advance_destinations and advance_roll names
        # to match frontend expectations in useEngineAPI.ts (lines ~330-340)
        return True, {
            "waiting_for_player": True,
            "action": "advance_select_destination",
            "unitId": unit_id,
            "advance_roll": advance_roll,
            # Même valeur que advance_roll (face D6) — alias pour clients qui lisent advance_range
            "advance_range": advance_roll,
            "advance_max_subhex": advance_move_budget,
            "advance_destinations": [{"col": (norm_coords := normalize_coordinates(d[0], d[1]))[0], "row": norm_coords[1]} for d in valid_destinations],
            "highlight_color": "orange"
        }


def _attack_sequence_rng(
    attacker: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]
) -> Dict[str, Any]:
    """Séquence d'une attaque complète avec règles spéciales. Utilisé par les tests via monkeypatch de random.randint.

    Ordre des jets : hit → hazardous (si HAZARDOUS) → wound (si hit) → reroll wound (si règle) → save (si wound non-critique).
    """
    import random

    weapon_index = int(require_key(attacker, "selectedRngWeaponIndex"))
    weapon = attacker["RNG_WEAPONS"][weapon_index]
    weapon_rules = [r.upper() for r in (weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else [])]
    unit_rules: List[Dict[str, Any]] = require_key(attacker, "UNIT_RULES")
    weapon_name: str = weapon.get("display_name", weapon.get("NAME", weapon.get("name", "")))
    attacker_id = str(attacker["id"])

    # AP de base, potentiellement amélioré par closest_target_penetration
    ap = int(weapon["AP"] if "AP" in weapon else 0)
    ap_modifier_ability_display_name: Optional[str] = None
    try:
        ctp_rule = next(r for r in unit_rules if r.get("ruleId") == "closest_target_penetration")
    except StopIteration:
        ctp_rule = None
    if ctp_rule:
        pool = shooting_build_valid_target_pool(game_state, attacker_id)
        target_id_str = str(target["id"])
        if pool:
            # « Cible la plus proche » = mesure bord-à-bord (règle 01.04), euclidienne
            # via le sélecteur `ranged` — cohérent avec le gate de portée tir.
            from engine.combat_utils import ranged_edge_distance, socle_from_cache_entry
            _ctp_metric = _ranged_distance_metric()
            _ctp_cache = require_key(game_state, "units_cache")
            _attacker_socle = socle_from_cache_entry(_ctp_cache[attacker_id])
            def _dist(uid: str) -> float:
                if uid not in _ctp_cache:
                    raise KeyError(f"_attack_sequence_rng: unit {uid} not in units_cache")
                return ranged_edge_distance(
                    _attacker_socle, socle_from_cache_entry(_ctp_cache[uid]), _ctp_metric
                )
            closest_id = min(pool, key=_dist)
            if closest_id == target_id_str:
                ap = ap - 1
                ap_modifier_ability_display_name = ctp_rule.get("displayName", "").upper()

    # Stats de base
    bs = int(weapon.get("ATK", weapon.get("BS", 4)))
    strength = int(weapon.get("STR", weapon.get("S", attacker.get("T", 4))))
    dmg_raw = weapon.get("DMG", 1)

    # HEAVY : réduit le seuil de touche de 1 si l'attaquant n'a pas bougé
    has_heavy = "HEAVY" in weapon_rules
    attacker_moved = (
        attacker_id in game_state.get("units_moved", set())
        or attacker_id in game_state.get("units_advanced", set())
    )
    hit_target_base = bs
    hit_rule_modifier: Optional[str] = None
    effective_bs = bs
    if has_heavy and not attacker_moved:
        effective_bs = max(2, bs - 1)
        hit_rule_modifier = "HEAVY"
    hit_target = effective_bs

    # Seuils
    wth = wound_threshold(strength, int(target["T"]))
    save_th = save_threshold(int(target["ARMOR_SAVE"]), int(target.get("INVUL_SAVE", 7)), ap)

    has_hazardous = "HAZARDOUS" in weapon_rules
    has_devastating = "DEVASTATING_WOUNDS" in weapon_rules

    def _base_result(**overrides: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "hit_success": False, "wound_success": False, "save_success": False, "damage": 0,
            "hit_roll": None, "hit_target": hit_target, "hit_target_base": hit_target_base,
            "hit_rule_modifier": hit_rule_modifier,
            "wound_roll": None, "wound_target": wth, "wound_ability_display_name": None,
            "save_roll": 0, "save_target": save_th, "save_skipped": False, "save_skip_reason": None,
            "critical_wound_unmodified": False, "devastating_wounds_applied": False,
            "hazardous_test_required": has_hazardous, "hazardous_test_roll": None, "hazardous_triggered": False,
            "ap_modifier_ability_display_name": ap_modifier_ability_display_name,
            "weapon_name": weapon_name,
        }
        base.update(overrides)
        parts = [f"HIT:{base.get('hit_roll','?')}/{hit_target}"]
        if base.get("wound_roll") is not None:
            parts.append(f"WOUND:{base['wound_roll']}/{wth}")
        if base.get("save_roll"):
            parts.append(f"SAVE:{base['save_roll']}/{save_th}")
        parts.append(f"DMG:{base['damage']}")
        base["attack_log"] = " ".join(parts)
        base["devastating_wounds_flag"] = base["devastating_wounds_applied"]
        return base

    # 1. Jet de touche
    hit_roll = random.randint(1, 6)

    # 2. Jet HAZARDOUS (même en cas de miss)
    hazardous_test_roll: Optional[int] = None
    hazardous_triggered = False
    if has_hazardous:
        hazardous_test_roll = random.randint(1, 6)
        hazardous_triggered = hazardous_test_roll == 1

    hit_success = hit_roll != 1 and hit_roll >= effective_bs
    if not hit_success:
        return _base_result(
            hit_success=False, hit_roll=hit_roll,
            hazardous_test_roll=hazardous_test_roll, hazardous_triggered=hazardous_triggered,
        )

    # 3. Jet de blessure (avec reroll éventuel)
    wound_roll = random.randint(1, 6)
    wound_ability_display_name: Optional[str] = None

    try:
        reroll1 = next(r for r in unit_rules if r.get("ruleId") == "reroll_1_towound")
    except StopIteration:
        reroll1 = None
    if reroll1 and wound_roll == 1:
        wound_roll = random.randint(1, 6)
        wound_ability_display_name = reroll1.get("displayName", "").upper()

    wound_success_pre = wound_roll != 1 and wound_roll >= wth
    if not wound_success_pre:
        try:
            reroll_obj = next(r for r in unit_rules if r.get("ruleId") == "reroll_towound_target_on_objective")
        except StopIteration:
            reroll_obj = None
        if reroll_obj:
            target_col, target_row = int(target.get("col", -1)), int(target.get("row", -1))
            on_obj = any(
                [target_col, target_row] == list(h)[:2]
                for obj in require_key(game_state, "objectives")
                for h in require_key(obj, "hexes")
            )
            if on_obj:
                wound_roll = random.randint(1, 6)
                wound_ability_display_name = reroll_obj.get("displayName", "").upper()

    wound_success = wound_roll != 1 and wound_roll >= wth
    critical_wound = wound_roll == 6

    if not wound_success:
        return _base_result(
            hit_success=True, hit_roll=hit_roll,
            wound_roll=wound_roll, wound_ability_display_name=wound_ability_display_name,
            critical_wound_unmodified=critical_wound,
            hazardous_test_roll=hazardous_test_roll, hazardous_triggered=hazardous_triggered,
        )

    # 4. DEVASTATING_WOUNDS : blessure critique (6) → save sauté
    if has_devastating and critical_wound:
        try:
            dmg = resolve_dice_value(dmg_raw, f"attack_seq_dmg_{attacker_id}")
        except Exception:
            dmg = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1
        return _base_result(
            hit_success=True, wound_success=True, save_success=False, damage=dmg,
            hit_roll=hit_roll,
            wound_roll=wound_roll, wound_ability_display_name=wound_ability_display_name,
            save_roll=0, save_skipped=True, save_skip_reason="DEVASTATING_WOUNDS",
            critical_wound_unmodified=True, devastating_wounds_applied=True,
            hazardous_test_roll=hazardous_test_roll, hazardous_triggered=hazardous_triggered,
        )

    # 5. Jet de sauvegarde
    save_roll = random.randint(1, 6)
    save_success = save_roll != 1 and save_roll >= save_th

    damage = 0
    if not save_success:
        try:
            damage = resolve_dice_value(dmg_raw, f"attack_seq_dmg_{attacker_id}")
        except Exception:
            damage = int(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1

    return _base_result(
        hit_success=True, wound_success=True, save_success=save_success, damage=damage,
        hit_roll=hit_roll,
        wound_roll=wound_roll, wound_ability_display_name=wound_ability_display_name,
        save_roll=save_roll, save_skipped=False,
        critical_wound_unmodified=critical_wound, devastating_wounds_applied=False,
        hazardous_test_roll=hazardous_test_roll, hazardous_triggered=hazardous_triggered,
    )
