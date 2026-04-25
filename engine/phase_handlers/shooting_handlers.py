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
    calculate_hex_distance as _calculate_hex_distance,
)
from shared.data_validation import require_key
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
)

# ============================================================================
# PERFORMANCE: Target pool caching (30-40% speedup)
# ============================================================================
# Cache valid target pools to avoid repeated distance/LoS calculations
# Cache key: (pid, id(game_state), episode_num, turn, unit_id, col, row, advance_status, adjacent_status, player)
_target_pool_cache = {}  # per-process, per-env, per-episode; invalidates when unit/weapon changes
_cache_size_limit = 100  # Prevent memory leak in long episodes
_MOVE_AFTER_SHOOTING_DISTANCE_ARG = "distance"


def clear_target_pool_cache() -> None:
    """Clear _target_pool_cache. Call on scenario rotation to avoid stale pool from different topology."""
    global _target_pool_cache
    n = len(_target_pool_cache)
    _target_pool_cache.clear()
    if os.environ.get("LOS_DEBUG") == "1" and n > 0:
        import sys
        sys.stderr.write(f"[LOS_DEBUG] clear_target_pool_cache cleared {n} entries\n")
        sys.stderr.flush()


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


def _weapon_has_heavy_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has HEAVY rule."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, 'rule'):  # ParsedWeaponRule object
            if rule.rule == "HEAVY":
                return True
        elif rule == "HEAVY":  # String
            return True
    return False


def _weapon_has_devastating_wounds_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has DEVASTATING_WOUNDS rule."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    # Handle both ParsedWeaponRule objects and strings
    for rule in rules:
        if hasattr(rule, "rule"):  # ParsedWeaponRule object
            if rule.rule == "DEVASTATING_WOUNDS":
                return True
        elif rule == "DEVASTATING_WOUNDS":  # String
            return True
    return False


def _weapon_has_ignores_cover_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has IGNORES_COVER rule."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    for rule in rules:
        if hasattr(rule, "rule"):  # ParsedWeaponRule object
            if rule.rule == "IGNORES_COVER":
                return True
        elif rule == "IGNORES_COVER":  # String
            return True
    return False


def _weapon_has_hazardous_rule(weapon: Dict[str, Any]) -> bool:
    """Check if weapon has HAZARDOUS rule."""
    if not weapon:
        return False
    rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
    for rule in rules:
        if hasattr(rule, "rule"):  # ParsedWeaponRule object
            if rule.rule == "HAZARDOUS":
                return True
        elif rule == "HAZARDOUS":  # String
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

    action_logs = game_state.setdefault("action_logs", [])
    action_logs.append(
        {
            "type": "roll_info",
            "phase": "SHOOT",
            "player": require_key(unit, "player"),
            "unitId": unit_id,
            "message": (
                f"Unit {unit_id}({unit_col},{unit_row}) SHOOT with [{weapon_name}]. "
                f"Number of shoots ({nb_value}): {nb_roll}"
            ),
        }
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


def _is_unit_on_objective(unit: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
    """Return True if unit coordinates are inside any objective hex."""
    unit_col, unit_row = require_unit_position(unit, game_state)
    objectives = require_key(game_state, "objectives")
    if not isinstance(objectives, list):
        raise TypeError(f"game_state['objectives'] must be a list, got {type(objectives).__name__}")

    for objective in objectives:
        objective_hexes = require_key(objective, "hexes")
        if not isinstance(objective_hexes, list):
            raise TypeError(f"objective['hexes'] must be a list, got {type(objective_hexes).__name__}")
        for objective_hex in objective_hexes:
            if isinstance(objective_hex, dict):
                obj_col, obj_row = normalize_coordinates(
                    require_key(objective_hex, "col"),
                    require_key(objective_hex, "row")
                )
            elif isinstance(objective_hex, (list, tuple)) and len(objective_hex) == 2:
                obj_col, obj_row = normalize_coordinates(objective_hex[0], objective_hex[1])
            else:
                raise TypeError(
                    "objective hex entry must be {'col','row'} or [col,row]/(col,row), "
                    f"got {objective_hex!r}"
                )
            if unit_col == obj_col and unit_row == obj_row:
                return True
    return False


def _is_unit_stationary_for_heavy(attacker_id: Any, game_state: Dict[str, Any]) -> bool:
    """
    HEAVY applies only if the unit remained stationary this turn.

    Stationary means:
    - not in units_moved during MOVE phase
    - not in units_advanced during SHOOT phase
    """
    units_moved = require_key(game_state, "units_moved")
    units_advanced = require_key(game_state, "units_advanced")
    if _tracking_set_contains_unit(attacker_id, units_moved):
        return False
    if _tracking_set_contains_unit(attacker_id, units_advanced):
        return False
    return True


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


def _build_weapon_availability_enemy_precheck(
    game_state: Dict[str, Any],
    unit: Dict[str, Any],
    rng_weapons: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Une passe par ennemi (distance max RNG, blocage allié/mêlée, clé los_cache) pour
    weapon_availability_check : évite de répéter min_distance / boucle alliés pour chaque arme.
    """
    from engine.hex_utils import min_distance_between_sets as _mds_wpn
    from engine.utils.weapon_helpers import get_melee_range

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
    _u_fp = _ue.get("occupied_hexes", {(unit_col, unit_row)}) if _ue else {(unit_col, unit_row)}
    shooter_id_str = _uid_str
    shooter_player_int = int(unit["player"]) if unit["player"] is not None else None
    melee_range = get_melee_range(game_state)

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

            _e_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            d = _mds_wpn(_u_fp, _e_fp, max_distance=max_rng)
            if d > max_rng:
                continue

            enemy_adjacent_to_shooter = d <= melee_range
            friendly_blocks = _friendly_engagement_blocks_ranged_shot(
                game_state,
                shooter_id_str,
                shooter_player_int,
                _e_fp,
                _enemy_id_str,
                enemy_adjacent_to_shooter,
                units_cache,
            )

            los_cache_has_key = isinstance(_los_map, dict) and _enemy_id_str in _los_map
            los_cache_true = bool(_los_map[_enemy_id_str]) if los_cache_has_key else False

            out.append({
                "enemy": enemy,
                "enemy_id_str": _enemy_id_str,
                "distance": d,
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
                    _tpb = time.perf_counter() if _perf_wa else None
                    _enemy_precheck_for_availability = _build_weapon_availability_enemy_precheck(
                        game_state, unit, rng_weapons
                    )
                    if _perf_wa and _tpb is not None:
                        _precheck_build_s += time.perf_counter() - _tpb
                from engine.utils.weapon_helpers import get_melee_range

                melee_range = get_melee_range(game_state)
                weapon_is_pistol = _weapon_has_pistol_rule(weapon)
                shooter_engaged = _is_adjacent_to_enemy_within_cc_range(game_state, unit)

                _trs = time.perf_counter() if _perf_wa else None
                for row in _enemy_precheck_for_availability:
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
                                if row["distance"] > melee_range:
                                    continue
                            elif row["distance"] <= melee_range and not weapon_is_pistol:
                                continue
                            if row["friendly_blocks"]:
                                continue
                            weapon_has_valid_target = True
                            break
                        is_valid = _is_valid_shooting_target(game_state, temp_unit, row["enemy"])
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
        
        from engine.hex_utils import min_distance_between_sets as _mds_wpn2
        units_cache = require_key(game_state, "units_cache")
        unit_player = int(unit["player"]) if unit["player"] is not None else None
        unit_col, unit_row = require_unit_position(unit, game_state)
        _uid2 = str(unit["id"])
        _ue2 = units_cache.get(_uid2)
        _u_fp2 = _ue2.get("occupied_hexes", {(unit_col, unit_row)}) if _ue2 else {(unit_col, unit_row)}
        for enemy_id, cache_entry in units_cache.items():
            enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
            if enemy_player != unit_player:
                enemy = get_unit_by_id(game_state, enemy_id)
                if enemy is None:
                    raise KeyError(f"Unit {enemy_id} missing from game_state['units']")
                _e_fp2 = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
                distance = _mds_wpn2(_u_fp2, _e_fp2, max_distance=weapon_range)
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


def build_unit_los_cache(game_state: Dict[str, Any], unit_id: str) -> None:
    """
    AI_TURN.md: Calculate LoS cache for a specific unit.
    Uses units_cache and has_line_of_sight_coords() for performance.
    
    Returns: void (updates unit["los_cache"])
    """
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return

    # Initialize cache
    unit["los_cache"] = {}
    
    # Get unit position from cache (single source of truth)
    unit_pos = get_unit_position(unit, game_state)
    if unit_pos is None:
        return
    unit_col, unit_row = unit_pos
    
    # Get units_cache (must exist, built at reset)
    if "units_cache" not in game_state:
        raise KeyError("units_cache must exist (built at reset)")
    
    units_cache = game_state["units_cache"]
    
    # If units_cache is empty, los_cache remains empty (no units)
    if not units_cache:
        return
    
    # Get unit's player for filtering enemies
    unit_player = int(unit["player"]) if unit["player"] is not None else None
    
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    los_visibility_min_ratio = float(game_rules.get("los_visibility_min_ratio", 0.0))
    
    # Defensive: ensure los_cache exists before loop (handles edge cases)
    if "los_cache" not in unit:
        unit["los_cache"] = {}

    # Calculate LoS for each enemy in units_cache (only alive enemies — dead must not appear in pool)
    for target_id, target_data in units_cache.items():
        # Skip friendly units (only calculate LoS to enemies)
        target_player = target_data["player"]
        if target_player == unit_player:
            continue
        # CRITICAL: Exclude dead units so they never appear in los_cache → valid_target_pool
        if not is_unit_alive(str(target_id), game_state):
            continue

        target_col = target_data["col"]
        target_row = target_data["row"]
        target_hexes: List[Tuple[int, int]] = []
        occupied_hexes = target_data.get("occupied_hexes")
        if isinstance(occupied_hexes, (set, list, tuple)) and len(occupied_hexes) > 0:
            for hx in occupied_hexes:
                if isinstance(hx, (list, tuple)) and len(hx) >= 2:
                    hc, hr = normalize_coordinates(hx[0], hx[1])
                    target_hexes.append((hc, hr))
        if not target_hexes:
            tc, tr = normalize_coordinates(target_col, target_row)
            target_hexes = [(tc, tr)]

        visible_hexes = 0
        for tc, tr in target_hexes:
            _, can_see_hex, _ = _get_los_visibility_state(
                game_state,
                int(unit_col),
                int(unit_row),
                int(tc),
                int(tr),
            )
            if can_see_hex:
                visible_hexes += 1
        target_visibility_ratio = visible_hexes / len(target_hexes)
        has_los = target_visibility_ratio >= los_visibility_min_ratio

        unit["los_cache"][str(target_id)] = has_los

        if os.environ.get("LOS_DEBUG") == "1":
            import sys
            try:
                ratio, can_see, _ = _get_los_visibility_state(
                    game_state, int(unit_col), int(unit_row), int(target_col), int(target_row)
                )
                topo_str = f"topology={ratio:.6f}"
            except Exception:
                topo_str = "topology=N/A"
            ep = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            msg = f"[LOS_DEBUG] build_unit_los_cache unit={unit_id} target={target_id} ({unit_col},{unit_row})->({target_col},{target_row}) has_los={has_los} {topo_str} ep={ep} turn={turn}\n"
            sys.stderr.write(msg)
            sys.stderr.flush()


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
) -> List[str]:
    """
    Return IDs of enemies targetable from a hypothetical position (read-only, no mutation).

    Aligné sur l'activation tir : copie d'état, tireur déplacé virtuellement, ``build_unit_los_cache``
    puis ``valid_target_pool_build`` (empreintes §3.3, PISTOL / adjacent, alliés au contact, etc.).

    L'ancienne implémentation (distance centre-à-centre + ``compute_los_state`` seuls) pouvait
    marquer des cibles « valides » alors que le pool moteur les exclut.

    Args:
        advance_position: Si True, simule une unité après Advance (``units_advanced`` sur la copie).
    """
    unit_id_str = str(unit_id)
    unit = _get_unit_by_id(game_state, unit_id_str)
    if not unit:
        return []
    if not game_state.get("units_cache"):
        return []
    if not unit.get("RNG_WEAPONS"):
        return []

    gs = copy.deepcopy(game_state)
    if "weapon_rule" not in gs:
        gs["weapon_rule"] = 1

    u = _get_unit_by_id(gs, unit_id_str)
    if not u:
        return []

    u.pop("valid_target_pool", None)
    u.pop("_pool_from_cache", None)
    u.pop("_pool_cache_key", None)

    set_unit_coordinates(u, dest_col, dest_row)
    update_units_cache_position(gs, unit_id_str, int(u["col"]), int(u["row"]))

    if advance_position:
        ua_raw = gs.get("units_advanced") or []
        ua_list = list(ua_raw)
        if not any(str(x) == unit_id_str for x in ua_list):
            ua_list.append(unit_id_str)
        gs["units_advanced"] = ua_list

    if unit_id_str in require_key(gs, "units_fled") and not _unit_has_rule(u, "shoot_after_flee"):
        return []

    build_unit_los_cache(gs, unit_id_str)

    weapon_rule = require_key(gs, "weapon_rule")
    advance_status = (
        1 if any(str(x) == unit_id_str for x in require_key(gs, "units_advanced")) else 0
    )
    if advance_status == 1:
        adjacent_status = 0
    else:
        adjacent_status = 1 if _is_adjacent_to_enemy_within_cc_range(gs, u) else 0

    return valid_target_pool_build(
        gs,
        u,
        weapon_rule,
        advance_status,
        adjacent_status,
        precomputed_weapon_available_pool=None,
        precomputed_enemy_precheck=None,
    )


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


def _invalidate_los_cache_for_unit(game_state: Dict[str, Any], dead_unit_id: str) -> None:
    """
    Partially invalidate LoS cache when unit dies.
    Direct field access, no state copying.
    
    Only removes entries involving dead unit (performance optimization).
    """
    if "los_cache" not in game_state:
        return
    
    # Remove all cache entries involving dead unit
    # CRITICAL: Normalize dead_unit_id to string for consistent comparison
    dead_unit_id_str = str(dead_unit_id)
    keys_to_remove = [
        key for key in game_state["los_cache"].keys()
        if str(key[0]) == dead_unit_id_str or str(key[1]) == dead_unit_id_str
    ]
    
    for key in keys_to_remove:
        del game_state["los_cache"][key]


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
    
    # hex_los_cache: selective invalidation when old position known (PERF: preserves
    # LoS between other hex pairs; full clear caused training ~0.2 ep/min)
    if "hex_los_cache" not in game_state:
        return
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
        # Full clear when old position not provided (callers without coords use this path)
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
    from ai.unit_registry import UnitRegistry
    unit_registry = UnitRegistry()
    shooter_unit_type = require_key(unit, "unitType")
    shooter_agent_key = unit_registry.get_model_key(shooter_unit_type)
    
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
    
    # unit alive? (units_cache is source of truth)
    if not is_unit_alive(str(unit["id"]), game_state):
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
        # If CAN_SHOOT = false -> ❌ Skip (no valid actions)
        if not can_shoot:
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
        return True


def _friendly_engagement_blocks_ranged_shot(
    game_state: Dict[str, Any],
    shooter_id_str: str,
    shooter_player_int: int,
    target_fp: Set[Tuple[int, int]],
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
    from engine.hex_utils import min_distance_between_sets
    from engine.utils.weapon_helpers import get_melee_range

    melee_range = get_melee_range(game_state)
    for friendly_id, cache_entry in units_cache.items():
        friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if friendly_player == shooter_player_int and friendly_id != shooter_id_str:
            friendly_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            friendly_distance = min_distance_between_sets(target_fp, friendly_fp, max_distance=melee_range)

            if friendly_distance <= melee_range:
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    episode = game_state.get("episode_number", "?")
                    turn = game_state.get("turn", "?")
                    add_debug_file_log(
                        game_state,
                        f"[SHOOT DEBUG] E{episode} T{turn} _is_valid_shooting_target: "
                        f"Shooter {shooter_id_str} blocked - target {target_id_str} engaged with "
                        f"friendly {friendly_id} (dist={friendly_distance})"
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
    from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range, get_selected_ranged_weapon

    shooter_col, shooter_row = require_unit_position(shooter, game_state)
    target_col, target_row = require_unit_position(target, game_state)

    units_cache = require_key(game_state, "units_cache")
    shooter_id_str = str(shooter["id"])
    target_id_str = str(target["id"])
    shooter_entry = units_cache.get(shooter_id_str)
    target_entry = units_cache.get(target_id_str)
    shooter_fp = shooter_entry.get("occupied_hexes", {(shooter_col, shooter_row)}) if shooter_entry else {(shooter_col, shooter_row)}
    target_fp = target_entry.get("occupied_hexes", {(target_col, target_row)}) if target_entry else {(target_col, target_row)}
    max_range = get_max_ranged_range(shooter)
    distance = min_distance_between_sets(shooter_fp, target_fp, max_distance=max_range)
    if distance > max_range:
        return False

    if not is_unit_alive(target_id_str, game_state):
        return False

    target_player = int(target["player"]) if target["player"] is not None else None
    shooter_player = int(shooter["player"]) if shooter["player"] is not None else None
    if target_player == shooter_player:
        return False

    melee_range = get_melee_range(game_state)
    enemy_adjacent_to_shooter = (distance <= melee_range)
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

    shooter_player_int = int(shooter["player"]) if shooter["player"] is not None else None
    if _friendly_engagement_blocks_ranged_shot(
        game_state,
        shooter_id_str,
        shooter_player_int,
        target_fp,
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
            précheck sont encore traitées via ``min_distance_between_sets`` borné par la portée max
            des armes **utilisables** (cohérent avec le test de portée).
    
    Returns:
        List of enemy unit IDs that can be targeted (valid_target_pool)
    """
    current_player = unit["player"]
    
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

    from engine.utils.weapon_helpers import get_melee_range
    from engine.hex_utils import min_distance_between_sets

    melee_range = get_melee_range(game_state)
    max_usable_rng = 0
    for widx in usable_weapon_indices:
        if widx < len(rng_weapons):
            rw = require_key(rng_weapons[widx], "RNG")
            if rw > max_usable_rng:
                max_usable_rng = rw
    
    # For each target_id in targets_with_los.keys():
    units_cache = require_key(game_state, "units_cache")
    unit_col, unit_row = require_unit_position(unit, game_state)
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
            distance_to_enemy = int(row_opt["distance"])
            enemy_adjacent_to_shooter = distance_to_enemy <= melee_range
            if not enemy_adjacent_to_shooter and bool(row_opt.get("friendly_blocks")):
                continue
        else:
            # Pas de ligne précheck (ex. cible avec LoS mais hors max RNG du précheck, ou appel sans précheck).
            # Distance tireur/cible §3.3 : borner la recherche par la portée max des armes utilisables,
            # pas par melee_range seul — sinon la distance renvoyée peut être tronquée et fausser le test de portée.
            _md_cap = max_usable_rng if max_usable_rng > 0 else 0
            distance_to_enemy = min_distance_between_sets(
                shooter_fp, enemy_fp, max_distance=_md_cap
            )
            enemy_adjacent_to_shooter = distance_to_enemy <= melee_range

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
            engaged_friendly_distance = None
            for friendly_id, cache_entry in units_cache.items():
                friendly_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
                if (friendly_player == current_player_int and 
                    friendly_id != unit_id_normalized):
                    friendly_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
                    friendly_distance = min_distance_between_sets(enemy_fp, friendly_fp, max_distance=melee_range)
                    if friendly_distance <= melee_range:
                        enemy_adjacent_to_friendly = True
                        engaged_friendly_id = friendly_id
                        engaged_friendly_distance = friendly_distance
                        break
            
            if enemy_adjacent_to_friendly:
                if game_state.get("debug_mode", False):
                    from engine.game_utils import add_debug_file_log
                    _ep = enemy.get("col", "?")
                    _er = enemy.get("row", "?")
                    add_debug_file_log(
                        game_state,
                        f"[SHOOT DEBUG] E{episode} T{turn} valid_target_pool_build: "
                        f"Enemy {enemy_id_normalized}({_ep},{_er}) engaged with friendly "
                        f"{engaged_friendly_id} (dist={engaged_friendly_distance})"
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
        
        # ALL conditions met -> ✅ Add unit to valid_target_pool
        # CRITICAL: Convert ID to string for consistent comparison (target_id is passed as str)
        # Note: Friendly units are already filtered out at line 949-960 above
        if unit_within_range:
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
    # Hash enemy positions so cache invalidates when any target moves
    units_cache = require_key(game_state, "units_cache")
    enemy_pos_hash = tuple(
        sorted(
            (tid, int(e["col"]), int(e["row"]))
            for tid, e in units_cache.items()
            if int(e.get("player", -1)) != unit_player_int and is_unit_alive(tid, game_state)
        )
    )
    wall_hexes = require_key(game_state, "wall_hexes")
    if not isinstance(wall_hexes, (list, set, tuple)):
        raise TypeError(
            f"wall_hexes must be list/set/tuple (got {type(wall_hexes).__name__})"
        )
    normalized_wall_hexes: List[Tuple[int, int]] = []
    for raw_wall in wall_hexes:
        if not isinstance(raw_wall, (list, tuple)) or len(raw_wall) != 2:
            raise ValueError(f"Invalid wall hex format in game_state.wall_hexes: {raw_wall!r}")
        wall_col, wall_row = normalize_coordinates(raw_wall[0], raw_wall[1])
        normalized_wall_hexes.append((wall_col, wall_row))
    wall_hexes_tuple = tuple(sorted(normalized_wall_hexes))
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
    for target_id in filtered_targets:
        target = _get_unit_by_id(game_state, target_id)
        if not target:
            target_priorities.append((target_id, (999, 0, 999)))
            continue

        distance = _calculate_hex_distance(*require_unit_position(unit, game_state), *require_unit_position(target, game_state))

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
                    ratio, can_see, _ = _get_los_visibility_state(
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
    """
    Line of sight check with proper hex pathfinding.
    Fixed to get wall data from multiple possible sources.

    Shooter/target may be:
    - Full unit dicts (with "id"): position read via require_unit_position() from units_cache.
    - Coordinate-only dicts ({"col", "row"}): when called from has_line_of_sight_coords();
      those coordinates are already derived from units_cache in build_unit_los_cache().
    So positions used for LoS always originate from units_cache (single source of truth).
    """
    debug_mode = game_state.get("debug_mode", False)
    from engine.game_utils import add_debug_log
    if debug_mode:
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        shooter_id = shooter.get("id", "?")
        target_id = target.get("id", "?")
    if "id" in shooter:
        start_col, start_row = require_unit_position(shooter, game_state)
    else:
        if "col" not in shooter or "row" not in shooter:
            raise KeyError(f"Shooter dict must have 'id' or 'col'/'row': {list(shooter.keys())}")
        start_col, start_row = int(shooter["col"]), int(shooter["row"])
    if "id" in target:
        end_col, end_row = require_unit_position(target, game_state)
    else:
        if "col" not in target or "row" not in target:
            raise KeyError(f"Target dict must have 'id' or 'col'/'row': {list(target.keys())}")
        end_col, end_row = int(target["col"]), int(target["row"])

    start_col_int = int(start_col)
    start_row_int = int(start_row)
    end_col_int = int(end_col)
    end_row_int = int(end_row)

    # Keep frontend/backend LoS rules aligned:
    # - 7-point sampling per hex (center + 6 vertices)
    # - visibility ratio thresholds from config:
    #   < los_visibility_min_ratio => blocked
    #   [los_visibility_min_ratio, cover_ratio) => in cover
    #   >= cover_ratio => clear
    target_hexes = _resolve_target_hexes_for_los(game_state, target, end_col_int, end_row_int)
    target_visibility_ratio, can_see_target, in_cover_target, visible_hexes, max_visibility_ratio = (
        _compute_target_visibility_from_hexes(
            game_state,
            start_col_int,
            start_row_int,
            target_hexes,
        )
    )
    if debug_mode:
        visibility_state = "BLOCKED" if not can_see_target else ("COVER" if in_cover_target else "CLEAR")
        add_debug_log(
            game_state,
            f"[LOS DEBUG] E{episode} T{turn} Shooter {shooter_id}({start_col},{start_row}) "
            f"-> Target {target_id}({end_col},{end_row}): {visibility_state} "
            f"target_vis_ratio={target_visibility_ratio:.3f} max_hex_ratio={max_visibility_ratio:.3f} "
            f"visible_hexes={visible_hexes}/{len(target_hexes)}"
        )
    return can_see_target


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


def _compute_target_visibility_from_hexes(
    game_state: Dict[str, Any],
    shooter_col: int,
    shooter_row: int,
    target_hexes: List[Tuple[int, int]],
) -> Tuple[float, bool, bool, int, float]:
    """
    Compute target-level visibility from footprint hexes, aligned with shooting pool logic.
    Returns: (target_visibility_ratio, can_see_target, in_cover_target, visible_hexes, max_hex_ratio)
    """
    game_rules = require_key(require_key(game_state, "config"), "game_rules")
    los_visibility_min_ratio = float(game_rules.get("los_visibility_min_ratio", 0.0))
    cover_ratio = float(game_rules.get("cover_ratio", 1.0))
    visible_hexes = 0
    max_hex_ratio = 0.0
    for tc, tr in target_hexes:
        visibility_ratio, can_see_hex, _ = _get_los_visibility_state(
            game_state,
            int(shooter_col),
            int(shooter_row),
            int(tc),
            int(tr),
        )
        if visibility_ratio > max_hex_ratio:
            max_hex_ratio = float(visibility_ratio)
        if can_see_hex:
            visible_hexes += 1
    target_visibility_ratio = visible_hexes / len(target_hexes) if target_hexes else 0.0
    can_see_target = visible_hexes > 0 and target_visibility_ratio >= los_visibility_min_ratio
    in_cover_target = can_see_target and target_visibility_ratio < cover_ratio
    return target_visibility_ratio, can_see_target, in_cover_target, visible_hexes, max_hex_ratio


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
) -> Tuple[float, bool, bool]:
    """Return (visibility_ratio, can_see, in_cover).

    Uses precomputed los_topology when available (legacy boards with .npz).
    Falls back to on-demand hex line trace (Board ×10) via hex_utils.
    """
    config = require_key(game_state, "config")
    game_rules = require_key(config, "game_rules")
    los_visibility_min_ratio = float(require_key(game_rules, "los_visibility_min_ratio"))
    cover_ratio = float(require_key(game_rules, "cover_ratio"))

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
        return 0.0, False, False

    los_topology = game_state.get("los_topology")
    if los_topology is not None:
        from_idx = start_row * board_cols + start_col
        to_idx = end_row * board_cols + end_col
        visibility_ratio = float(los_topology[from_idx, to_idx])
    else:
        from engine.hex_utils import compute_los_state, build_wall_set
        wall_set = _get_wall_set(game_state)
        return compute_los_state(
            start_col, start_row, end_col, end_row,
            wall_set, los_visibility_min_ratio, cover_ratio,
        )

    can_see = visibility_ratio >= los_visibility_min_ratio
    in_cover = can_see and visibility_ratio < cover_ratio
    return visibility_ratio, can_see, in_cover


def _get_wall_set(game_state: Dict[str, Any]) -> Set[Tuple[int, int]]:
    """Return cached wall_set from game_state, building it on first call."""
    cached = game_state.get("_wall_set_cache")
    if cached is not None:
        return cached
    from engine.hex_utils import build_wall_set
    ws = build_wall_set(game_state)
    game_state["_wall_set_cache"] = ws
    return ws


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
    attack_cells: List[Dict[str, int]] = []
    cover_cells: List[Dict[str, int]] = []
    ratio_by_hex: Dict[str, float] = {}

    for col in range(board_cols):
        for row in range(board_rows):
            if row == board_rows - 1 and (col % 2) == 1:
                continue
            distance = _calculate_hex_distance(shooter_col, shooter_row, col, row)
            if distance <= 0 or distance > max_range:
                continue
            visibility_ratio, can_see, in_cover = _get_los_visibility_state(
                game_state,
                int(shooter_col),
                int(shooter_row),
                int(col),
                int(row),
            )
            ratio_by_hex[f"{col},{row}"] = float(visibility_ratio)
            if not can_see:
                continue
            if in_cover:
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


def _compute_los_visibility_ratio(
    start_col: int,
    start_row: int,
    end_col: int,
    end_row: int,
    wall_hexes: Set[Tuple[int, int]],
    los_visibility_min_ratio: float,
    cover_ratio: float,
) -> Tuple[float, bool, bool]:
    """
    Compute LoS visibility ratio using hex-native sampling (center + 6 vertices).

    Returns:
        (visibility_ratio, can_see, in_cover)
        - can_see is True when visibility_ratio >= los_visibility_min_ratio.
    """
    if not isinstance(los_visibility_min_ratio, (int, float)):
        raise TypeError(
            f"los_visibility_min_ratio must be numeric, got {type(los_visibility_min_ratio).__name__}"
        )
    if (
        math.isnan(float(los_visibility_min_ratio))
        or los_visibility_min_ratio <= 0
        or los_visibility_min_ratio > 1
    ):
        raise ValueError(
            f"los_visibility_min_ratio must be in (0, 1], got {los_visibility_min_ratio}"
        )
    if not isinstance(cover_ratio, (int, float)):
        raise TypeError(f"cover_ratio must be numeric, got {type(cover_ratio).__name__}")
    if math.isnan(float(cover_ratio)) or cover_ratio <= 0 or cover_ratio > 1:
        raise ValueError(f"cover_ratio must be in (0, 1], got {cover_ratio}")
    if float(los_visibility_min_ratio) >= float(cover_ratio):
        raise ValueError(
            f"Invalid LoS thresholds: los_visibility_min_ratio ({los_visibility_min_ratio}) "
            f"must be < cover_ratio ({cover_ratio})"
        )

    hex_radius = 21.0
    shooter_x, shooter_y = _hex_to_pixel(start_col, start_row, hex_radius)
    target_x, target_y = _hex_to_pixel(end_col, end_row, hex_radius)

    def build_hex_points(center_x: float, center_y: float) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = [(center_x, center_y)]
        for i in range(6):
            angle = (i * math.pi) / 3.0
            px = center_x + hex_radius * 0.8 * math.cos(angle)
            py = center_y + hex_radius * 0.8 * math.sin(angle)
            points.append((px, py))
        return points

    shooter_points = build_hex_points(shooter_x, shooter_y)
    target_points = build_hex_points(target_x, target_y)
    clear_sight_lines = 0
    total_sight_lines = len(shooter_points) * len(target_points)

    for shooter_point in shooter_points:
        for target_point in target_points:
            line_blocked = False
            for wall_col, wall_row in wall_hexes:
                if _line_passes_through_hex(
                    shooter_point,
                    target_point,
                    int(wall_col),
                    int(wall_row),
                    hex_radius,
                ):
                    line_blocked = True
                    break
            if not line_blocked:
                clear_sight_lines += 1

    visibility_ratio = clear_sight_lines / total_sight_lines
    can_see = visibility_ratio >= float(los_visibility_min_ratio)
    in_cover = can_see and visibility_ratio < float(cover_ratio)
    return visibility_ratio, can_see, in_cover

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

    unit_col, unit_row = require_unit_position(unit, game_state)
    nearest_enemy_id = min(
        enemies,
        key=lambda enemy_id: _calculate_hex_distance(
            unit_col,
            unit_row,
            *require_unit_position(enemy_id, game_state),
        ),
    )
    nearest_enemy_col, nearest_enemy_row = require_unit_position(nearest_enemy_id, game_state)
    return min(
        destinations,
        key=lambda destination: _calculate_hex_distance(
            int(destination[0]),
            int(destination[1]),
            nearest_enemy_col,
            nearest_enemy_row,
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

    action_logs = require_key(game_state, "action_logs")
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
    action_logs.append({
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
    })
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
                                     action_type: str = None, include_attack_results: bool = True) -> Tuple[bool, Dict[str, Any]]:
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
        "activation_complete": True
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

def _shooting_unit_execution_loop(game_state: Dict[str, Any], unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Execute While SHOOT_LEFT > 0 loop automatically
    """
    
    unit = _get_unit_by_id(game_state, unit_id)
    if not unit:
        return False, {"error": "unit_not_found"}
    
    # While SHOOT_LEFT > 0
    if unit["SHOOT_LEFT"] <= 0:
        # Check if current weapon is PISTOL and find available weapons of same category
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        if selected_weapon:
            weapon_rules = selected_weapon["WEAPON_RULES"] if "WEAPON_RULES" in selected_weapon else []
            current_weapon_is_pistol = "PISTOL" in weapon_rules
            current_weapon_index = unit["selectedRngWeaponIndex"] if "selectedRngWeaponIndex" in unit else 0
            
            # Find available weapons of the same category (PISTOL or non-PISTOL)
            rng_weapons = require_key(unit, "RNG_WEAPONS")
            available_weapons_same_category = []
            for idx, weapon in enumerate(rng_weapons):
                if idx == current_weapon_index:
                    continue  # Skip current weapon
                if _is_combi_profile_blocked(unit, weapon, idx):
                    continue
                weapon_rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
                is_pistol = "PISTOL" in weapon_rules
                if current_weapon_is_pistol and is_pistol:
                    # Current is PISTOL, looking for other PISTOL weapons
                    available_weapons_same_category.append(idx)
                elif not current_weapon_is_pistol and not is_pistol:
                    # Current is non-PISTOL, looking for other non-PISTOL weapons
                    available_weapons_same_category.append(idx)
            
            # Build valid target pool to check if there are targets
            # BUG FIX: Check if ANY available weapon has valid targets
            # Not just the current (exhausted) weapon
            has_valid_targets_for_any_weapon = False
            valid_targets = []
            
            if available_weapons_same_category:
                # Store original weapon index to restore later
                original_weapon_index = unit["selectedRngWeaponIndex"] if "selectedRngWeaponIndex" in unit else 0
                
                # Check each available weapon for valid targets
                for weapon_idx in available_weapons_same_category:
                    # Temporarily switch to this weapon for target pool calculation
                    unit["selectedRngWeaponIndex"] = weapon_idx
                    temp_valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
                    
                    if temp_valid_targets:
                        has_valid_targets_for_any_weapon = True
                        valid_targets = temp_valid_targets
                        # Restore original weapon index
                        unit["selectedRngWeaponIndex"] = original_weapon_index
                        break
                
                # Restore original weapon index if no targets found
                if not has_valid_targets_for_any_weapon:
                    unit["selectedRngWeaponIndex"] = original_weapon_index
            else:
                # No alternative weapons, use current weapon
                valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
                has_valid_targets_for_any_weapon = len(valid_targets) > 0
            
            if available_weapons_same_category and has_valid_targets_for_any_weapon:
                # There are other weapons of the same category and targets available
                # Allow weapon selection to continue shooting
                # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                if "weapon_rule" not in game_state:
                    raise KeyError("game_state missing required 'weapon_rule' field")
                weapon_rule = game_state["weapon_rule"]
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                try:
                    weapon_available_pool = weapon_availability_check(
                        game_state, unit, weapon_rule, advance_status, adjacent_status
                    )
                    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                    # Filter by same category (PISTOL or non-PISTOL) if needed
                    if current_weapon_is_pistol:
                        usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                    else:
                        usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                    
                    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                    # CRITICAL FIX: Store on unit for frontend access (not in game_state global)
                    unit["available_weapons"] = available_weapons
                except Exception as e:
                    # If weapon selection fails, end activation
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                
                # Check if at least one weapon is usable (can_use: True)
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                if not usable_weapons:
                    # No usable weapons left, end activation
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)

                # Training/PvE path: do not return waiting_for_player without a matching gym action.
                # This prevents deadlocks where the active unit stays forever in shoot_activation_pool.
                if _is_ai_controlled_shooting_unit(game_state, unit, config):
                    selected_weapon_info = usable_weapons[0]
                    selected_weapon_index = require_key(selected_weapon_info, "index")
                    selected_weapon = require_key(selected_weapon_info, "weapon")

                    unit["selectedRngWeaponIndex"] = selected_weapon_index
                    nb_roll = resolve_dice_value(require_key(selected_weapon, "NB"), "shooting_nb_auto_weapon_switch")
                    unit["SHOOT_LEFT"] = nb_roll
                    unit["_current_shoot_nb"] = nb_roll
                    _append_shoot_nb_roll_info_log(game_state, unit, selected_weapon, nb_roll)

                    updated_valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
                    unit["valid_target_pool"] = updated_valid_targets

                    if not updated_valid_targets:
                        return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)

                    target_id = _ai_select_shooting_target(game_state, unit_id, updated_valid_targets)
                    return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)

                return True, {
                    "while_loop_active": True,
                    "valid_targets": valid_targets,
                    "shootLeft": 0,
                    "weapon_selection_required": True,
                    "context": "weapon_selection_after_shots_exhausted",
                    "blinking_units": valid_targets,
                    "start_blinking": True,
                    "waiting_for_player": True,
                    "available_weapons": available_weapons
                }
            else:
                # No more weapons of the same category or no targets, end activation
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # No weapon selected, end activation
            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
    
    # Build valid_target_pool only if missing (pool is source of truth during activation)
    # shooting_build_valid_target_pool() now correctly determines context
    # including arg2=1, arg3=0 if unit has advanced
    if "valid_target_pool" in unit:
        valid_targets = unit["valid_target_pool"]
    else:
        valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
        unit["valid_target_pool"] = valid_targets
    
    # valid_target_pool NOT empty?
    if len(valid_targets) == 0:
        # Check if a target died and rebuild valid_targets for all available weapons
        # This allows switching to another weapon if current weapon has no targets
        # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
        if "weapon_rule" not in game_state:
            raise KeyError("game_state missing required 'weapon_rule' field")
        weapon_rule = game_state["weapon_rule"]
        unit_id_str = str(unit["id"])
        has_advanced = unit_id_str in require_key(game_state, "units_advanced")
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        advance_status = 1 if has_advanced else 0
        adjacent_status = 1 if is_adjacent else 0
        
        try:
            weapon_available_pool = weapon_availability_check(
                game_state, unit, weapon_rule, advance_status, adjacent_status
            )
            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
        except Exception as e:
            # If weapon selection fails, continue with normal flow (no targets)
            usable_weapons = []
        
        # Try to rebuild valid_targets for each usable weapon
        for weapon_info in usable_weapons:
            weapon = weapon_info["weapon"]
            # Create temporary unit with this weapon to check targets
            temp_unit = unit.copy()
            temp_unit["RNG_WEAPONS"] = [weapon]
            temp_unit["selectedRngWeaponIndex"] = 0
            temp_valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            if temp_valid_targets:
                # Found targets for this weapon, switch to it
                unit["selectedRngWeaponIndex"] = weapon_info["index"]
                nb_roll = resolve_dice_value(require_key(weapon, "NB"), "shooting_nb_switch")
                unit["SHOOT_LEFT"] = nb_roll
                unit["_current_shoot_nb"] = nb_roll
                _append_shoot_nb_roll_info_log(game_state, unit, weapon, nb_roll)
                valid_targets = temp_valid_targets
                break
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if SHOOT_LEFT equals selected weapon NB
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        current_weapon_nb = require_key(unit, "_current_shoot_nb") if selected_weapon else None
        
        unit_check = _get_unit_by_id(game_state, unit_id)
        if unit_check and _is_ai_controlled_shooting_unit(game_state, unit_check, config):
            if selected_weapon and unit["SHOOT_LEFT"] == current_weapon_nb:
                # No targets at activation
                return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)
            else:
                # Shot last target available
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        
        # For human players: allow advance mode instead of ending activation
        # only if unit has not already advanced in this shooting phase.
        has_shot = _unit_has_shot_with_any_weapon(unit)
        if (
            selected_weapon
            and unit["SHOOT_LEFT"] == current_weapon_nb
            and str(unit_id) not in require_key(game_state, "units_advanced")
            and not has_shot
        ):
            # No targets at activation - return signal to allow advance mode
            return True, {
                "waiting_for_player": True,
                "unitId": unit_id,
                "no_targets": True,
                "allow_advance": True,
                "context": "no_targets_advance_available"
            }
        else:
            # Shot last target available
            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
    
    unit = _get_unit_by_id(game_state, unit_id)
    # Gym/PvE AI can auto-continue attacks; humans must explicitly choose targets.
    if unit and _is_ai_controlled_shooting_unit(game_state, unit, config) and valid_targets:
        # Pool is source of truth - do not rebuild here (AI_TURN.md: no redundant checks)
        
        # AUTO-SHOOT: PvE AI and gym training
        target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly and return result
        return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
    
    # Only humans get waiting_for_player response
    # Get available weapons for frontend weapon menu
    has_advanced = str(unit_id) in require_key(game_state, "units_advanced")
    
    # Check if unit has already fired with a weapon to apply PISTOL category filter
    # Use _shooting_with_pistol if available (set after first shot), otherwise check if unit has fired
    current_weapon_is_pistol = None  # Default: no filter (unit hasn't fired yet)
    
    if "_shooting_with_pistol" in unit:
        # Unit has fired at least once, use stored category
        current_weapon_is_pistol = unit["_shooting_with_pistol"]
    else:
        raise KeyError(f"Unit missing required '_shooting_with_pistol' field: unit_id={unit.get('id')}")
        
    # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
    if "weapon_rule" not in game_state:
        raise KeyError("game_state missing required 'weapon_rule' field")
    weapon_rule = game_state["weapon_rule"]
    unit_id_str = str(unit["id"])
    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
    advance_status = 1 if has_advanced else 0
    adjacent_status = 1 if is_adjacent else 0
    ctx_now = (advance_status, adjacent_status)
    reuse_pool = unit.get("_shoot_activation_reuse_weapon_pool")
    reuse_ctx = unit.get("_shoot_activation_reuse_ctx")
    enemy_precheck = unit.get("_shoot_activation_enemy_precheck")
    if (
        reuse_pool is not None
        and reuse_ctx == ctx_now
        and not _unit_has_shot_with_any_weapon(unit)
    ):
        weapon_available_pool = reuse_pool
    elif reuse_ctx == ctx_now and enemy_precheck is not None:
        weapon_available_pool = weapon_availability_check(
            game_state,
            unit,
            weapon_rule,
            advance_status,
            adjacent_status,
            _precheck=enemy_precheck,
        )
    else:
        weapon_available_pool = weapon_availability_check(
            game_state, unit, weapon_rule, advance_status, adjacent_status
        )
    _clear_shoot_activation_weapon_reuse_cache(unit)
    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
    
    # Filter by category (PISTOL or non-PISTOL) if needed
    if current_weapon_is_pistol is not None:
        if current_weapon_is_pistol:
            usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
        else:
            usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
    
    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
    
    # CRITICAL: Include all_attack_results if attacks were executed before (in a loop)
    # This ensures attacks already executed are logged to step.log
    shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
    
    response = {
        "while_loop_active": True,
        "valid_targets": valid_targets,
        "shootLeft": unit["SHOOT_LEFT"],
        "context": "player_action_selection",
        "blinking_units": valid_targets,
        "start_blinking": True,
        "waiting_for_player": True,
        "available_weapons": available_weapons,
        "action": "wait",  # CRITICAL: Set action for logging (waiting for target selection)
        "unitId": unit_id,
        "phase": "shoot"
    }
    
    # CRITICAL: Include all_attack_results if attacks were executed
    # This ensures attacks already executed are logged even when waiting_for_player=True
    if shoot_attack_results:
        response["all_attack_results"] = list(shoot_attack_results)
        # Change action to "shoot" if attacks were executed (not just waiting)
        response["action"] = "shoot"
        game_state["shoot_attack_results"] = []
    
    return True, response


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


def execute_action(game_state: Dict[str, Any], unit: Dict[str, Any], action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
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
        active_unit_id = game_state.get("active_shooting_unit")
        if active_unit_id is not None and str(active_unit_id) != unit_id_str:
            active_unit = _get_unit_by_id(game_state, str(active_unit_id))
            if active_unit is None:
                raise KeyError(f"active_shooting_unit {active_unit_id} missing from game_state['units']")
            if _shooting_activation_has_committed_action(game_state, active_unit):
                return _keep_committed_shooting_activation_waiting(
                    game_state,
                    active_unit,
                    "cannot_activate_other_unit_after_committed_shooting_action",
                )
            del game_state["active_shooting_unit"]

        result = shooting_unit_activation_start(game_state, unit_id)
        if result.get("success"):
            # Normalize backend contract: allow_advance implies player can act (advance) now.
            # Keep this path explicit and return immediately so the signal is never lost.
            if result.get("allow_advance"):
                result["waiting_for_player"] = True
                result["action"] = "empty_target_advance_available"
                if "empty_target_pool" not in result:
                    result["empty_target_pool"] = True
                if "can_advance" not in result:
                    result["can_advance"] = True
                return True, result
            # Check if empty_target_pool with can_advance
            if result.get("empty_target_pool") and result.get("can_advance"):
                # STEP 6: EMPTY_TARGET_HANDLING - advance available
                # Return to allow advance action selection
                return True, result
            elif result.get("empty_target_pool"):
                # STEP 6: Already handled in shooting_unit_activation_start (WAIT)
                return True, result
            # Normal flow: valid targets available
            execution_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            if isinstance(execution_result, tuple) and len(execution_result) == 2:
                success, loop_result = execution_result
                if success and isinstance(loop_result, dict):
                    _assert_gym_waiting_state_is_actionable(loop_result)
                    _enforce_active_shooting_unit_for_waiting_targets(loop_result)
                return success, loop_result
            return execution_result
        # If no success and no error handled above, return the result (may contain other errors)
        return False, result
    
    elif action_type == "shoot":
        # Handle gym-style shoot action with optional targetId
        if "targetId" not in action:
            target_id = None
        else:
            target_id = action["targetId"]
        
        # Validate unit eligibility
        # Pool always contains string IDs (normalized at creation), so direct comparison is safe
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        if unit_id_str not in pool_ids:
            return False, {"error": "unit_not_eligible", "unitId": unit_id}
        
        # Initialize unit for shooting if needed (only if not already activated)
        active_shooting_unit = game_state["active_shooting_unit"] if "active_shooting_unit" in game_state else None
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if SHOOT_LEFT equals selected weapon NB
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        activation_started_in_this_execute = False
        if selected_weapon and "_current_shoot_nb" not in unit:
            if unit.get("_shoot_activation_started", False):
                valid_targets = unit.get("valid_target_pool")
                if valid_targets:
                    raise KeyError(
                        f"Unit missing required '_current_shoot_nb' after activation start: unit_id={unit.get('id')}"
                    )
            activation_result = shooting_unit_activation_start(game_state, unit_id)
            if activation_result.get("error"):
                return False, activation_result
            activation_started_in_this_execute = True
            if "_current_shoot_nb" not in unit and unit.get("valid_target_pool"):
                raise KeyError(
                    f"Unit missing required '_current_shoot_nb' after activation start: unit_id={unit.get('id')}"
                )
        current_weapon_nb = require_key(unit, "_current_shoot_nb") if selected_weapon else None
        
        # Auto-select target if not provided (AI mode)
        if not target_id:
            # shooting_unit_activation_start already called shooting_build_valid_target_pool (same request).
            # Reuse that list here — no stale risk (same execute_action, no intervening state).
            if activation_started_in_this_execute:
                pool_raw = unit.get("valid_target_pool")
                if not isinstance(pool_raw, list):
                    raise TypeError(
                        f"valid_target_pool must be list after shooting_unit_activation_start, "
                        f"got {type(pool_raw).__name__} for unit_id={unit.get('id')}"
                    )
                valid_targets = [str(x) for x in pool_raw]
            else:
                valid_targets = shooting_build_valid_target_pool(game_state, unit_id)
            
            # Debug output only in debug training mode
            if not valid_targets:
                # No valid targets - end activation with wait
                return _handle_shooting_end_activation(game_state, unit, PASS, 1, PASS, SHOOTING, 1)
            target_id = _ai_select_shooting_target(game_state, unit_id, valid_targets)
        
        # Execute shooting directly without UI loops
        execution_result = shooting_target_selection_handler(game_state, unit_id, str(target_id), config)
        # Ensure all_attack_results is surfaced for step_logger (training uses returned result)
        if isinstance(execution_result, tuple) and len(execution_result) == 2:
            success, result = execution_result
            if success and isinstance(result, dict):
                _assert_gym_waiting_state_is_actionable(result)
            if success and isinstance(result, dict) and "all_attack_results" not in result:
                shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
                if shoot_attack_results:
                    result["all_attack_results"] = list(shoot_attack_results)
                    if not result.get("waiting_for_player", False):
                        game_state["shoot_attack_results"] = []
            return success, result
        return execution_result
    
    elif action_type == "advance":
        # ADVANCE_IMPLEMENTATION: Handle advance action during shooting phase
        return _handle_advance_action(game_state, unit, action, config)

    elif action_type == "move_after_shooting":
        return _handle_move_after_shooting_action(game_state, unit, action, config)
    
    elif action_type == "select_weapon":
        # WEAPON_SELECTION: Handle weapon selection action
        weapon_index_raw = action.get("weaponIndex")
        if weapon_index_raw is None:
            return False, {"error": "missing_weapon_index"}
        try:
            weapon_index = int(weapon_index_raw)
        except (TypeError, ValueError):
            return False, {"error": "invalid_weapon_index_type", "weaponIndex": weapon_index_raw}
        
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        if weapon_index < 0 or weapon_index >= len(rng_weapons):
            return False, {"error": "invalid_weapon_index", "weaponIndex": weapon_index}

        unit["selectedRngWeaponIndex"] = weapon_index
        unit["_manual_weapon_selected"] = True
        # JSON / frontend (camelCase) : aligné sur useEngineAPI.convertUnits + UnitRenderer
        unit["manualWeaponSelected"] = True
        _clear_shoot_activation_weapon_reuse_cache(unit)

        # CRITICAL FIX: Invalidate target pool cache after weapon change
        # Cache key doesn't include selectedRngWeaponIndex, so we must clear matching entries
        # Cache key format: (pid, id(gs), ep, turn, unit_id, col, row, advance, adjacent, player, enemy_pos_hash)
        global _target_pool_cache
        unit_col, unit_row = require_unit_position(unit, game_state)
        unit_id_str = str(unit_id)
        gs_instance_id = game_state.get("_cache_instance_id", id(game_state))
        pid = os.getpid()
        ep = require_key(game_state, "episode_number")
        turn_num = require_key(game_state, "turn")
        keys_to_remove = [
            key for key in _target_pool_cache.keys()
            if len(key) >= 7 and key[0] == pid and key[1] == gs_instance_id and key[2] == ep and key[3] == turn_num
            and str(key[4]) == unit_id_str and key[5] == unit_col and key[6] == unit_row
        ]
        for key in keys_to_remove:
            del _target_pool_cache[key]

        # PRINCIPLE: "Le Pool DOIT gérer les morts" - If unit is in pool, it's alive (no need to check)
        # Update SHOOT_LEFT with the new weapon's NB
        weapon = rng_weapons[weapon_index]
        nb_roll = resolve_dice_value(require_key(weapon, "NB"), "shooting_nb_select_weapon")
        unit["SHOOT_LEFT"] = nb_roll
        unit["_current_shoot_nb"] = nb_roll
        _append_shoot_nb_roll_info_log(game_state, unit, weapon, nb_roll)
        # AI_TURN.md COMPLIANCE: Unit must already be in pool (pool is built once at phase start)
        # If unit is not in pool, it was removed via end_activation and cannot be reactivated
        # CRITICAL: Normalize unit_id to string for consistent comparison (pool stores strings)
        unit_id_str = str(unit_id)
        pool_ids = [str(uid) for uid in require_key(game_state, "shoot_activation_pool")]
        if unit_id_str not in pool_ids:
            # Unit not in pool - cannot select weapon (unit was removed via end_activation)
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_debug_log
            add_debug_log(game_state, f"[SELECT_WEAPON ERROR] E{episode} T{turn} select_weapon: Unit {unit_id_str} NOT in pool, cannot select weapon. Pool={pool_ids}")
            return False, {"error": "unit_not_in_pool", "unitId": unit_id, "message": "Unit was removed from pool and cannot select weapon"}
        
        # Store autoSelectWeapon in game_state if provided
        if "autoSelectWeapon" in action:
            if "config" not in game_state:
                game_state["config"] = {}
            if "game_settings" not in game_state["config"]:
                game_state["config"]["game_settings"] = {}
            game_state["config"]["game_settings"]["autoSelectWeapon"] = action["autoSelectWeapon"]

        result = _shooting_unit_execution_loop(game_state, unit_id, config)
        if isinstance(result, tuple) and len(result) == 2:
            success, loop_result = result
            if success and isinstance(loop_result, dict):
                _assert_gym_waiting_state_is_actionable(loop_result)
                _enforce_active_shooting_unit_for_waiting_targets(loop_result)
            return success, loop_result
        return result

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
            # Check if unit has advanced (ADVANCED_SHOOTING_ACTION_SELECTION)
            has_advanced = unit_id_str in require_key(game_state, "units_advanced")
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
        return shooting_click_handler(game_state, unit_id, action, config)
    
    elif action_type == "right_click":
        # AI_TURN.md STEP 5A/5B: Wait action - check if unit has shot with ANY weapon
        has_shot = _unit_has_shot_with_any_weapon(unit)
        unit_id_str = str(unit["id"])
        if has_shot:
            # YES -> end_activation(ACTION, 1, SHOOTING, SHOOTING, 1)
            success, result = _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        else:
            # Check if unit has advanced (ADVANCED_SHOOTING_ACTION_SELECTION)
            has_advanced = unit_id_str in require_key(game_state, "units_advanced")
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
        # Handle invalid actions with training penalty - treat as miss but continue shooting sequence
        if "shoot_activation_pool" not in game_state:
            raise KeyError("game_state missing required 'shoot_activation_pool' field")
        current_pool = game_state["shoot_activation_pool"]
        pool_ids = [str(uid) for uid in current_pool]
        if str(unit_id) in pool_ids:
            if action.get("end_activation_required"):
                attempted_action = action.get("attempted_action")
                if attempted_action is None:
                    raise ValueError(f"Action missing 'attempted_action' field: {action}")
                success, result = _handle_shooting_end_activation(
                    game_state, unit, PASS, 1, PASS, SHOOTING, 1, action_type="invalid"
                )
                result["invalid_action_penalty"] = True
                result["attempted_action"] = attempted_action
                return success, result
            # Initialize unit if not already activated (this was the missing piece)
            active_shooting_unit = game_state.get("active_shooting_unit")
            if active_shooting_unit != unit_id:
                activation_result = shooting_unit_activation_start(game_state, unit_id)
            
            # DO NOT decrement SHOOT_LEFT - invalid action doesn't consume a shot
            # Just continue execution loop which will handle auto-shooting for PvE AI
            result = _shooting_unit_execution_loop(game_state, unit_id, config)
            if isinstance(result, tuple) and len(result) >= 2:
                success, loop_result = result
                loop_result["invalid_action_penalty"] = True
                # CRITICAL: No default value - require explicit attempted_action
                attempted_action = action.get("attempted_action")
                if attempted_action is None:
                    raise ValueError(f"Action missing 'attempted_action' field: {action}")
                loop_result["attempted_action"] = attempted_action
                return success, loop_result
            else:
                # CRITICAL: No default value - require explicit attempted_action
                attempted_action = action.get("attempted_action")
                if attempted_action is None:
                    raise ValueError(f"Action missing 'attempted_action' field: {action}")
                return True, {"invalid_action_penalty": True, "attempted_action": attempted_action}
        return False, {"error": "unit_not_eligible", "unitId": unit_id}
    
    else:
        return False, {"error": "invalid_action_for_phase", "action": action_type, "phase": "shoot"}


def shooting_click_handler(game_state: Dict[str, Any], unit_id: str, action: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Route click actions to appropriate handlers
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf_click = perf_timing_enabled(game_state)
    _t_click0 = time.perf_counter() if _perf_click else None
    _click_branch = "unknown"
    _ep_click = game_state.get("episode_number", "?")
    _turn_click = game_state.get("turn", "?")

    # Direct field access
    if "targetId" not in action:
        target_id = None
    else:
        target_id = action["targetId"]
    
    if "clickTarget" not in action:
        click_target = "target"
    else:
        click_target = action["clickTarget"]
    
    try:
        if click_target in ["target", "enemy"] and target_id:
            _click_branch = "target_or_enemy"
            if action.get("tutorial_force_kill") is True:
                game_state["_tutorial_force_kill_this_shot"] = True
            if action.get("tutorial_force_miss") is True:
                game_state["_tutorial_force_miss_this_shot"] = True
            return shooting_target_selection_handler(game_state, unit_id, str(target_id), config)

        elif click_target == "friendly_unit" and target_id:
            _click_branch = "friendly_unit_switch"
            # Left click on another unit in pool - switch only before shot/advance.
            if "shoot_activation_pool" not in game_state:
                raise KeyError("game_state missing required 'shoot_activation_pool' field")
            target_id_str = str(target_id)
            pool_ids = [str(uid) for uid in game_state["shoot_activation_pool"]]
            if target_id_str in pool_ids:
                current_unit = _get_unit_by_id(game_state, unit_id)
                if current_unit:
                    if _shooting_activation_has_committed_action(game_state, current_unit):
                        return _keep_committed_shooting_activation_waiting(
                            game_state,
                            current_unit,
                            "cannot_switch_after_committed_shooting_action",
                        )
                return _handle_unit_switch_with_context(game_state, unit_id, target_id_str, config)
            return False, {"error": "unit_not_in_pool", "targetId": target_id_str}

        elif click_target == "active_unit":
            _click_branch = "active_unit"
            # Left click on active unit postpones only before shot/advance.
            unit = _get_unit_by_id(game_state, unit_id)
            if not unit:
                return False, {"error": "unit_not_found", "unitId": unit_id}
            if _shooting_activation_has_committed_action(game_state, unit):
                return _keep_committed_shooting_activation_waiting(
                    game_state,
                    unit,
                    "cannot_postpone_after_committed_shooting_action",
                )
            else:
                # Unit has not shot or advanced yet - postpone (deselect, return to pool)
                if "active_shooting_unit" in game_state:
                    del game_state["active_shooting_unit"]
                # Auto-select next unit only for AI-controlled player.
                pool = require_key(game_state, "shoot_activation_pool")
                if pool:
                    cfg = require_key(game_state, "config")
                    if _should_auto_activate_next_shooting_unit(game_state, cfg, pool):
                        game_state["active_shooting_unit"] = pool[0]
                return True, {
                    "action": "postpone",
                    "unitId": unit_id,
                    "activation_ended": False,
                    "reset_mode": "select",
                    "clear_selected_unit": True
                }

        else:
            _click_branch = "elsewhere"
            # STEP 5A/5B: Postpone/Click elsewhere (Human only)
            # Postpone only while no shot or advance has been consumed.
            unit = _get_unit_by_id(game_state, unit_id)
            if not unit:
                return False, {"error": "unit_not_found", "unitId": unit_id}
            if not _shooting_activation_has_committed_action(game_state, unit):
                # NO -> POSTPONE_ACTIVATION() -> UNIT_ACTIVABLE_CHECK
                # Unit is NOT removed from shoot_activation_pool (can be re-activated later)
                # Remove weapon selection icon from UI (handled by frontend)
                # Clear active unit
                if "active_shooting_unit" in game_state:
                    del game_state["active_shooting_unit"]
                # Auto-select next unit only for AI-controlled player.
                pool = require_key(game_state, "shoot_activation_pool")
                if pool:
                    cfg = require_key(game_state, "config")
                    if _should_auto_activate_next_shooting_unit(game_state, cfg, pool):
                        game_state["active_shooting_unit"] = pool[0]
                # Return to UNIT_ACTIVABLE_CHECK step (by returning activation_ended=False)
                return True, {
                    "action": "postpone",
                    "unitId": unit_id,
                    "activation_ended": False,
                    "reset_mode": "select",
                    "clear_selected_unit": True
                }
            else:
                return _keep_committed_shooting_activation_waiting(
                    game_state,
                    unit,
                    "cannot_postpone_after_committed_shooting_action",
                )
    finally:
        if _perf_click and _t_click0 is not None:
            append_perf_timing_line(
                f"SHOOT_CLICK_HANDLER episode={_ep_click} turn={_turn_click} branch={_click_branch} "
                f"unit_id={unit_id} duration_s={time.perf_counter() - _t_click0:.6f}"
            )


def shooting_target_selection_handler(game_state: Dict[str, Any], unit_id: str, target_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle target selection and shooting execution.
    Requires explicit targetId selection.
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    _perf_ts = perf_timing_enabled(game_state)
    _ts_start = time.perf_counter() if _perf_ts else None
    _ep_ts = game_state.get("episode_number", "?")
    _turn_ts = game_state.get("turn", "?")

    try:
        unit = _get_unit_by_id(game_state, unit_id)
        
        if not unit:
            return False, {"error": "unit_not_found"}
        
        # CRITICAL: Check units_fled just before execution (may have changed during phase)
        # CRITICAL: Normalize unit ID to string for consistent comparison (units_fled stores strings)
        # Exception: units with shoot_after_flee effect are allowed to shoot after fleeing.
        unit_id_str = str(unit["id"])
        if unit_id_str in require_key(game_state, "units_fled") and not _unit_has_rule(unit, "shoot_after_flee"):
            return False, {"error": "unit_has_fled", "unitId": unit_id}
        
        # ASSAULT RULE VALIDATION: Block shooting if unit advanced without ASSAULT weapon
        unit_id_str = str(unit["id"])
        has_advanced = unit_id_str in require_key(game_state, "units_advanced")
        if has_advanced:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if not selected_weapon or not _can_unit_shoot_after_advance_with_weapon(unit, selected_weapon):
                return False, {"error": "cannot_shoot_after_advance_without_assault", "unitId": unit_id_str}
        
        # PISTOL RULE VALIDATION: Block shooting non-PISTOL weapons when adjacent to enemy
        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
        if is_adjacent:
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(unit)
            if not selected_weapon or not _weapon_has_pistol_rule(selected_weapon):
                return False, {"error": "cannot_shoot_non_pistol_when_adjacent", "unitId": unit_id_str}
                
        # Validate unit has shots remaining
        if "SHOOT_LEFT" not in unit:
            raise KeyError(f"Unit missing required 'SHOOT_LEFT' field: {unit}")
        
        # Always check if current weapon is PISTOL to filter weapons correctly below
        # This is needed even when SHOOT_LEFT > 0 to maintain PISTOL category consistency
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        current_weapon_is_pistol = False
        if selected_weapon:
            current_weapon_is_pistol = _weapon_has_pistol_rule(selected_weapon)
            weapon_name = require_key(selected_weapon, "display_name")
            if require_key(selected_weapon, "shot") == 1:
                return False, {"error": "weapon_already_used", "unitId": unit_id, "weapon": weapon_name}
        else:
            return False, {"error": "no_weapons_available", "unitId": unit_id}
        
        # Check if SHOOT_LEFT == 0 and handle weapon selection/switching
        if unit["SHOOT_LEFT"] <= 0:
            # SHOOT_LEFT is 0, route to execution loop for weapon selection/end activation
            success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            return success, loop_result
        
        # CRITICAL: Use existing valid_target_pool from unit (rebuilt at activation, after advance, or after target death)
        # Do NOT rebuild here - pool is source of truth and is rebuilt only at specific moments
        unit = _get_unit_by_id(game_state, unit_id)
        if not unit:
            return False, {"error": "unit_not_found"}
        
        valid_targets = unit["valid_target_pool"] if "valid_target_pool" in unit else []
        
        # AI_TURN.md: If pool is empty, go to EMPTY_TARGET_HANDLING (advance or WAIT)
        # Pool should not be empty here if unit was properly activated, but if all targets died
        # between activation and this call, allow agent to choose advance or WAIT
        if len(valid_targets) == 0:
            # Mark unit as active for EMPTY_TARGET_HANDLING
            game_state["active_shooting_unit"] = unit_id
            unit["valid_target_pool"] = []
            
            # Check if unit can advance
            can_advance = _can_unit_advance_in_shoot_phase(unit, game_state)
            if can_advance:
                # Return signal to allow advance action (EMPTY_TARGET_HANDLING)
                return True, {
                    "success": True,
                    "unitId": unit_id,
                    "empty_target_pool": True,
                    "can_advance": True,
                    "allow_advance": True,
                    "waiting_for_player": False,  # Agent can choose immediately
                    "action": "empty_target_advance_available"
                }
            else:
                # Cannot advance - must WAIT
                return _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
        
        # Handle target selection: agent-provided or auto-select
        # NOTE: Friendly fire and LoS checks are already done in valid_target_pool_build().
        # No redundant checks here - trust the pool generation.
        # CRITICAL: Convert target_id to string for consistent comparison with valid_targets
        target_id_str = str(target_id) if target_id else None
        if target_id_str and target_id_str in valid_targets:
            # Agent provided valid target (pool is source of truth — no redundant check)
            selected_target_id = target_id_str

            # === MULTIPLE_WEAPONS_IMPLEMENTATION.md: Sélection d'arme pour cette cible ===
            target = _get_unit_by_id(game_state, selected_target_id)
            if not target:
                return False, {"error": "target_not_found", "targetId": selected_target_id}
            
            # Only auto-select weapon if autoSelectWeapon is enabled
            cfg = game_state["config"] if "config" in game_state else None
            gs = cfg["game_settings"] if cfg and "game_settings" in cfg else None
            auto_select = gs["autoSelectWeapon"] if gs and "autoSelectWeapon" in gs else True
            manual_weapon_chosen = (
                unit.get("_manual_weapon_selected") is True
                or unit.get("manualWeaponSelected") is True
            )
            if manual_weapon_chosen:
                auto_select = False
            
            # If SHOOT_LEFT > 0, weapon is already selected and has remaining shots
            # Don't re-select weapon, just use the already selected one
            current_shoot_left = require_key(unit, "SHOOT_LEFT")
            if current_shoot_left > 0:
                # Weapon already selected, just verify it's still valid
                selected_weapon = get_selected_ranged_weapon(unit)
                if not selected_weapon:
                    return False, {"error": "no_weapons_available", "unitId": unit_id}
                # If auto-select is enabled and no shot has been fired yet with the current
                # weapon context, pick the best weapon now.
                # IMPORTANT: do not rely on weapon["shot"] here. That flag is set when a weapon
                # profile is exhausted, not when the first attack is fired. With RAPID_FIRE,
                # SHOOT_LEFT can remain equal to _current_shoot_nb after the first shot.
                shots_fired_in_current_context = int(require_key(unit, "_rapid_fire_shots_fired"))
                if (auto_select
                        and shots_fired_in_current_context == 0
                        and current_shoot_left == require_key(unit, "_current_shoot_nb")):
                    if "weapon_rule" not in game_state:
                        raise KeyError("game_state missing required 'weapon_rule' field")
                    weapon_rule = game_state["weapon_rule"]
                    unit_id_str = str(unit["id"])
                    has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                    is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                    advance_status = 1 if has_advanced else 0
                    adjacent_status = 1 if is_adjacent else 0

                    try:
                        weapon_available_pool = weapon_availability_check(
                            game_state, unit, weapon_rule, advance_status, adjacent_status
                        )
                        usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                        available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                    except Exception as e:
                        return False, {"error": "no_weapons_available", "unitId": unit_id}

                    usable_weapons = [w for w in available_weapons if w["can_use"]]
                    if not usable_weapons:
                        return False, {"error": "no_weapons_available", "unitId": unit_id}

                    from engine.ai.weapon_selector import select_best_ranged_weapon
                    filtered_weapons = [w["weapon"] for w in usable_weapons]
                    filtered_indices = [w["index"] for w in usable_weapons]
                    temp_unit = unit.copy()
                    temp_unit["RNG_WEAPONS"] = filtered_weapons
                    best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)

                    if best_weapon_idx_in_filtered >= 0:
                        best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                        unit["selectedRngWeaponIndex"] = best_weapon_idx
                        weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                        nb_roll = resolve_dice_value(require_key(weapon, "NB"), "shooting_nb_auto_select")
                        unit["SHOOT_LEFT"] = nb_roll
                        unit["_current_shoot_nb"] = nb_roll
                        _append_shoot_nb_roll_info_log(game_state, unit, weapon, nb_roll)
                        selected_weapon = weapon
                    else:
                        return False, {"error": "no_weapons_available", "unitId": unit_id}
                # Use already selected weapon, no re-selection needed
            elif auto_select:
                # SHOOT_LEFT == 0, need to select a new weapon (same category if current weapon was used)
                # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                if "weapon_rule" not in game_state:
                    raise KeyError("game_state missing required 'weapon_rule' field")
                weapon_rule = game_state["weapon_rule"]
                unit_id_str = str(unit["id"])
                has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                advance_status = 1 if has_advanced else 0
                adjacent_status = 1 if is_adjacent else 0
                
                try:
                    weapon_available_pool = weapon_availability_check(
                        game_state, unit, weapon_rule, advance_status, adjacent_status
                    )
                    usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                    # Filter by same category (PISTOL or non-PISTOL) if needed
                    if current_weapon_is_pistol:
                        usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                    else:
                        usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                    
                    available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                except Exception as e:
                    # If weapon selection fails, return error
                    if current_weapon_is_pistol:
                        return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                    else:
                        return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                
                # Filter to only usable weapons
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                
                if not usable_weapons:
                    if current_weapon_is_pistol:
                        return False, {"error": "no_pistol_weapons_available", "unitId": unit_id}
                    else:
                        return False, {"error": "no_non_pistol_weapons_available", "unitId": unit_id}
                
                # Create temporary unit with filtered weapons for selection
                from engine.ai.weapon_selector import select_best_ranged_weapon
                filtered_weapons = [w["weapon"] for w in usable_weapons]
                filtered_indices = [w["index"] for w in usable_weapons]
                temp_unit = unit.copy()
                temp_unit["RNG_WEAPONS"] = filtered_weapons
                best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)
                
                if best_weapon_idx_in_filtered >= 0:
                    # Map back to original weapon index
                    best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                    unit["selectedRngWeaponIndex"] = best_weapon_idx
                    weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                    nb_roll = resolve_dice_value(require_key(weapon, "NB"), "shooting_nb_auto_select_category")
                    unit["SHOOT_LEFT"] = nb_roll
                    unit["_current_shoot_nb"] = nb_roll
                    _append_shoot_nb_roll_info_log(game_state, unit, weapon, nb_roll)
                    
                    # PISTOL RULE VALIDATION: Re-validate after weapon selection
                    # This ensures the newly selected weapon is valid for current context
                    if is_adjacent:
                        if not _weapon_has_pistol_rule(weapon):
                            return False, {"error": "cannot_shoot_non_pistol_when_adjacent", "unitId": unit_id_str}
                else:
                    unit["SHOOT_LEFT"] = 0
                    return False, {"error": "no_weapons_available", "unitId": unit_id}
            else:
                # Manual mode: Use already selected weapon, just update SHOOT_LEFT if needed
                from engine.utils.weapon_helpers import get_selected_ranged_weapon
                selected_weapon = get_selected_ranged_weapon(unit)
                if selected_weapon:
                    current_shoot_left = require_key(unit, "SHOOT_LEFT")
                    active_shooting_unit = game_state["active_shooting_unit"] if "active_shooting_unit" in game_state else None
                    # Only initialize SHOOT_LEFT if it hasn't been initialized yet
                    # If SHOOT_LEFT == 0 after shooting, it means all shots from this weapon have been used
                    # Check if unit has started shooting (has active_shooting_unit set)
                    if current_shoot_left == 0 and active_shooting_unit != unit_id:
                        # Unit hasn't started shooting yet, initialize SHOOT_LEFT
                        nb_roll = resolve_dice_value(require_key(selected_weapon, "NB"), "shooting_nb_manual_init")
                        unit["SHOOT_LEFT"] = nb_roll
                        unit["_current_shoot_nb"] = nb_roll
                        _append_shoot_nb_roll_info_log(game_state, unit, selected_weapon, nb_roll)
                    elif current_shoot_left == 0 and active_shooting_unit == unit_id:
                        # Unit has already shot and SHOOT_LEFT is 0
                        # Need to select another weapon of the same category (PISTOL or non-PISTOL)
                        # Even in manual mode, auto-select the best weapon of same category to continue
                        weapon_rules = selected_weapon["WEAPON_RULES"] if "WEAPON_RULES" in selected_weapon else []
                        current_weapon_is_pistol = "PISTOL" in weapon_rules
                        
                        # AI_TURN.md ligne 526-535: Use weapon_availability_check instead
                        if "weapon_rule" not in game_state:
                            raise KeyError("game_state missing required 'weapon_rule' field")
                        weapon_rule = game_state["weapon_rule"]
                        unit_id_str = str(unit["id"])
                        has_advanced = unit_id_str in require_key(game_state, "units_advanced")
                        is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
                        advance_status = 1 if has_advanced else 0
                        adjacent_status = 1 if is_adjacent else 0
                        
                        try:
                            weapon_available_pool = weapon_availability_check(
                                game_state, unit, weapon_rule, advance_status, adjacent_status
                            )
                            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
                            # Filter by same category (PISTOL or non-PISTOL) if needed
                            if current_weapon_is_pistol:
                                usable_weapons = [w for w in usable_weapons if _weapon_has_pistol_rule(w["weapon"])]
                            else:
                                usable_weapons = [w for w in usable_weapons if not _weapon_has_pistol_rule(w["weapon"])]
                            
                            available_weapons = [{"index": w["index"], "weapon": w["weapon"], "can_use": w["can_use"], "reason": w.get("reason")} for w in usable_weapons]
                        except Exception as e:
                            # If weapon selection fails, end activation
                            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                        
                        # Filter to only usable weapons
                        usable_weapons = [w for w in available_weapons if w["can_use"]]
                        
                        if usable_weapons:
                            # Auto-select best weapon of same category to continue shooting
                            from engine.ai.weapon_selector import select_best_ranged_weapon
                            filtered_weapons = [w["weapon"] for w in usable_weapons]
                            filtered_indices = [w["index"] for w in usable_weapons]
                            temp_unit = dict(unit)  # Use dict() for safer copy
                            temp_unit["RNG_WEAPONS"] = filtered_weapons
                            try:
                                best_weapon_idx_in_filtered = select_best_ranged_weapon(temp_unit, target, game_state)
                            except (KeyError, AttributeError, IndexError) as e:
                                # If weapon selection fails, end activation
                                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
                            
                            if best_weapon_idx_in_filtered >= 0:
                                # Map back to original weapon index
                                best_weapon_idx = filtered_indices[best_weapon_idx_in_filtered]
                                unit["selectedRngWeaponIndex"] = best_weapon_idx
                                weapon = unit["RNG_WEAPONS"][best_weapon_idx]
                                nb_roll = resolve_dice_value(require_key(weapon, "NB"), "shooting_nb_manual_continue")
                                unit["SHOOT_LEFT"] = nb_roll
                                unit["_current_shoot_nb"] = nb_roll
                                _append_shoot_nb_roll_info_log(game_state, unit, weapon, nb_roll)
                                # Continue with shooting
                            else:
                                return False, {"error": "no_weapons_available", "unitId": unit_id}
                        else:
                            # No more weapons of the same category available
                            # End activation since all weapons of this category have been used
                            return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1)
        # === FIN NOUVEAU ===
        elif target_id:
            # Agent provided invalid target
            return False, {"error": "target_not_valid", "targetId": target_id}
        else:
            return False, {"error": "missing_target", "unitId": unit_id}
        
        # Determine selected_target_id if not already set (from if/elif blocks above)
        if 'selected_target_id' not in locals():
            # CRITICAL: Convert target_id to string for consistent comparison with valid_targets
            target_id_str = str(target_id) if target_id else None
            if target_id_str and target_id_str in valid_targets:
                selected_target_id = target_id_str
            elif target_id_str:
                return False, {"error": "target_not_valid", "targetId": target_id_str, "valid_targets": valid_targets[:5]}
            else:
                return False, {"error": "missing_target", "unitId": unit_id}
        
        target = _get_unit_by_id(game_state, selected_target_id)
        if not target:
            if _perf_ts:
                _t_pool0 = time.perf_counter()
            updated_pool = shooting_build_valid_target_pool(game_state, unit_id)
            if _perf_ts:
                append_perf_timing_line(
                    f"SHOOT_BUILD_VALID_TARGET_POOL episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} "
                    f"duration_s={time.perf_counter() - _t_pool0:.6f}"
                )
            unit["valid_target_pool"] = updated_pool
            if not updated_pool:
                game_state["active_shooting_unit"] = unit_id
                can_advance = _can_unit_advance_in_shoot_phase(unit, game_state)
                if can_advance:
                    return True, {
                        "success": True,
                        "unitId": unit_id,
                        "empty_target_pool": True,
                        "can_advance": True,
                        "allow_advance": True,
                        "waiting_for_player": False,
                        "action": "empty_target_advance_available"
                    }
                return _handle_shooting_end_activation(game_state, unit, WAIT, 1, PASS, SHOOTING, 1)
            return False, {"error": "target_not_found", "targetId": selected_target_id, "valid_targets": updated_pool[:5]}

        # RAPID_FIRE: On first shot with this weapon, add bonus shots if target is within half range.
        # Bonus shots are flagged individually as [RAPID FIRE:<value>] in logs.
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        selected_weapon = get_selected_ranged_weapon(unit)
        if not selected_weapon:
            raise ValueError(f"Unit {unit_id} has no selected ranged weapon before attack resolution")
        selected_weapon_index_raw = require_key(unit, "selectedRngWeaponIndex")
        try:
            selected_weapon_index = int(selected_weapon_index_raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"Unit {unit_id} has invalid selectedRngWeaponIndex type/value for RAPID_FIRE: "
                f"{selected_weapon_index_raw!r}"
            )
        unit["selectedRngWeaponIndex"] = selected_weapon_index
        current_context_weapon_index_raw = unit.get("_rapid_fire_context_weapon_index")
        current_context_weapon_index = (
            int(current_context_weapon_index_raw)
            if current_context_weapon_index_raw is not None
            else None
        )
        if current_context_weapon_index != selected_weapon_index:
            unit["_rapid_fire_context_weapon_index"] = selected_weapon_index
            # RAPID_FIRE base shots must come from the current live context.
            # _current_shoot_nb can be stale across some activation paths; SHOOT_LEFT
            # at context start is the authoritative rolled NB before RAPID_FIRE bonus.
            rapid_fire_base_nb = require_key(unit, "SHOOT_LEFT")
            if not isinstance(rapid_fire_base_nb, int) or rapid_fire_base_nb <= 0:
                raise ValueError(
                    f"Invalid SHOOT_LEFT for RAPID_FIRE context init on unit {unit_id}: "
                    f"{rapid_fire_base_nb!r}"
                )
            unit["_rapid_fire_base_nb"] = rapid_fire_base_nb
            unit["_rapid_fire_shots_fired"] = 0
            unit["_rapid_fire_bonus_total"] = 0
            rapid_fire_value = _get_rapid_fire_parameter(selected_weapon)
            unit["_rapid_fire_rule_value"] = rapid_fire_value if rapid_fire_value is not None else 0
            if rapid_fire_value is not None:
                rapid_fire_applied_by_weapon = unit.get("_rapid_fire_bonus_applied_by_weapon")
                if not isinstance(rapid_fire_applied_by_weapon, dict):
                    raise ValueError(
                        f"Unit {unit_id} has invalid _rapid_fire_bonus_applied_by_weapon: "
                        f"{type(rapid_fire_applied_by_weapon).__name__}"
                    )
                weapon_key = str(selected_weapon_index)
                if rapid_fire_applied_by_weapon.get(weapon_key, False):
                    rapid_fire_value = None
                else:
                    rapid_fire_applied_by_weapon[weapon_key] = True
            if rapid_fire_value is not None:
                shooter_col, shooter_row = require_unit_position(unit, game_state)
                target_col, target_row = require_unit_position(target, game_state)
                weapon_range = require_key(selected_weapon, "RNG")
                if not isinstance(weapon_range, int):
                    raise ValueError(f"Weapon RNG must be int for RAPID_FIRE, got {type(weapon_range).__name__}: {weapon_range}")
                if weapon_range <= 0:
                    raise ValueError(f"Weapon RNG must be > 0 for RAPID_FIRE, got {weapon_range}")
                distance = _calculate_hex_distance(shooter_col, shooter_row, target_col, target_row)
                if distance <= (weapon_range / 2):
                    unit["SHOOT_LEFT"] += rapid_fire_value
                    unit["_rapid_fire_bonus_total"] = rapid_fire_value

        # RAPID_FIRE bonus tagging uses shot index within current weapon context.
        # This avoids fragile dependence on SHOOT_LEFT state transitions.
        shots_fired_in_context = int(require_key(unit, "_rapid_fire_shots_fired"))
        rapid_fire_base_nb = int(require_key(unit, "_rapid_fire_base_nb"))
        rapid_fire_bonus_total = int(require_key(unit, "_rapid_fire_bonus_total"))
        if rapid_fire_base_nb <= 0:
            raise ValueError(
                f"Invalid RAPID_FIRE base NB for unit {unit_id}: "
                f"base_nb={rapid_fire_base_nb}, selected_weapon_index={selected_weapon_index}, "
                f"context_weapon_index={unit.get('_rapid_fire_context_weapon_index')}, "
                f"shoot_left={unit.get('SHOOT_LEFT')}, current_shoot_nb={unit.get('_current_shoot_nb')}, "
                f"shots_fired={shots_fired_in_context}, bonus_total={rapid_fire_bonus_total}"
            )
        current_shot_index = shots_fired_in_context + 1
        max_shots_in_context = rapid_fire_base_nb + rapid_fire_bonus_total
        if current_shot_index > max_shots_in_context:
            raise ValueError(
                f"Invalid RAPID_FIRE shot index for unit {unit_id}: "
                f"shot_index={current_shot_index}, base_nb={rapid_fire_base_nb}, "
                f"bonus_total={rapid_fire_bonus_total}, max_shots={max_shots_in_context}"
            )
        rapid_fire_bonus_shot_current = (
            rapid_fire_bonus_total > 0 and current_shot_index > rapid_fire_base_nb
        )
        unit["_rapid_fire_bonus_shot_current"] = rapid_fire_bonus_shot_current
        # Pool is source of truth — no redundant validation
        _atk_t0: Optional[float] = None
        if _perf_ts and _ts_start is not None:
            _atk_t0 = time.perf_counter()
            append_perf_timing_line(
                f"SHOOT_TARGET_PRE_ATTACK episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} target_id={selected_target_id} "
                f"duration_s={_atk_t0 - _ts_start:.6f}"
            )
        attack_result = shooting_attack_controller(game_state, unit_id, selected_target_id)
        if _perf_ts and _atk_t0 is not None:
            append_perf_timing_line(
                f"SHOOT_ATTACK_CONTROLLER_CALL episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} target_id={selected_target_id} "
                f"duration_s={time.perf_counter() - _atk_t0:.6f}"
            )

        # CRITICAL: Check if attack_result is an error before adding to shoot_attack_results
        # Error results don't have required fields like hit_roll, wound_roll, etc.
        if "error" in attack_result:
            return False, attack_result
        
        # CRITICAL: Add attack result to shoot_attack_results for logging
        # This ensures all attacks are logged even if waiting_for_player=True
        # Do NOT reset here; the list is cleared at activation start and after logging.
        if "shoot_attack_results" not in game_state:
            game_state["shoot_attack_results"] = []
        # CRITICAL: Extract nested attack_result from wrapper (shooting_attack_controller returns wrapper)
        # The actual attack data is in attack_result["attack_result"]
        actual_attack_result = attack_result["attack_result"].copy()
        actual_attack_result["targetId"] = selected_target_id
        # CRITICAL: Include shooterId in actual_attack_result for correct logging
        # shooting_attack_controller returns shooterId in the wrapper, we need it in the attack_result for logging
        actual_attack_result["shooterId"] = require_key(attack_result, "shooterId")
        # CRITICAL: Ensure target_died is always present (it's added in shooting_attack_controller but may be missing)
        if "target_died" not in actual_attack_result:
            actual_attack_result["target_died"] = attack_result["target_died"] if "target_died" in attack_result else False
        game_state["shoot_attack_results"].append(actual_attack_result)

        # HAZARDOUS critical failure (roll=1) can kill the shooter: activation must stop immediately.
        if bool(actual_attack_result.get("hazardous_self_died", False)):
            return _handle_shooting_end_activation(
                game_state,
                unit,
                ACTION,
                1,
                SHOOTING,
                SHOOTING,
                1,
                include_attack_results=True,
            )

        # Update SHOOT_LEFT and continue loop per AI_TURN.md
        unit["SHOOT_LEFT"] -= 1
        unit["_rapid_fire_shots_fired"] = int(require_key(unit, "_rapid_fire_shots_fired")) + 1
        
        # PISTOL rule: Update _shooting_with_pistol after each shot to track weapon category
        # This ensures the filter persists even if unit switches weapons
        current_weapon_index = unit["selectedRngWeaponIndex"] if "selectedRngWeaponIndex" in unit else 0
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        if current_weapon_index < len(rng_weapons):
            _set_combi_weapon_choice(game_state, unit, current_weapon_index)
            weapon = rng_weapons[current_weapon_index]
            weapon_rules = weapon["WEAPON_RULES"] if "WEAPON_RULES" in weapon else []
            weapon_name = weapon.get("display_name", f"weapon_{current_weapon_index}")
            is_pistol = "PISTOL" in weapon_rules
            if is_pistol:
                unit["_shooting_with_pistol"] = True
            else:
                unit["_shooting_with_pistol"] = False

        # AI_TURN.md ligne 523-536: SHOOT_LEFT == 0 handling
        if unit["SHOOT_LEFT"] == 0:
            # Mark selected_weapon as used (set weapon.shot = 1)
            if current_weapon_index < len(rng_weapons):
                weapon = rng_weapons[current_weapon_index]
                weapon["shot"] = 1
            
            # weapon_available_pool NOT empty? Check using weapon_availability_check
            if "weapon_rule" not in game_state:
                raise KeyError("game_state missing required 'weapon_rule' field")
            weapon_rule = game_state["weapon_rule"]
            unit_id_str = str(unit["id"])
            has_advanced = unit_id_str in require_key(game_state, "units_advanced")
            is_adjacent = _is_adjacent_to_enemy_within_cc_range(game_state, unit)
            advance_status = 1 if has_advanced else 0
            adjacent_status = 1 if is_adjacent else 0
            
            weapon_available_pool = weapon_availability_check(
                game_state, unit, weapon_rule, advance_status, adjacent_status
            )
            usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
            
            if usable_weapons:
                # YES -> Select next available weapon (AI/Human chooses)
                # For now, auto-select first usable weapon
                next_weapon = usable_weapons[0]
                unit["selectedRngWeaponIndex"] = next_weapon["index"]
                next_weapon_data = require_key(next_weapon, "weapon")
                nb_roll = resolve_dice_value(
                    require_key(next_weapon_data, "NB"),
                    "shooting_nb_next_weapon"
                )
                unit["SHOOT_LEFT"] = nb_roll
                unit["_current_shoot_nb"] = nb_roll
                _append_shoot_nb_roll_info_log(game_state, unit, next_weapon_data, nb_roll)
                
                # CRITICAL: Rebuild target pool using shooting_build_valid_target_pool for consistency
                # This wrapper automatically determines context (advance_status, adjacent_status)
                if _perf_ts:
                    _t_vtp0 = time.perf_counter()
                valid_target_pool = shooting_build_valid_target_pool(game_state, unit_id)
                if _perf_ts:
                    append_perf_timing_line(
                        f"SHOOT_BUILD_VALID_TARGET_POOL episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} "
                        f"context=after_weapon_switch duration_s={time.perf_counter() - _t_vtp0:.6f}"
                    )
                unit["valid_target_pool"] = valid_target_pool
                
                # Continue to shooting action selection step (ADVANCED if arg2=1, else normal)
                # This is handled by _shooting_unit_execution_loop
                if _perf_ts:
                    _t_ex0 = time.perf_counter()
                success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
                if _perf_ts:
                    append_perf_timing_line(
                        f"SHOOT_EXEC_LOOP episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} "
                        f"context=after_shoot_left_zero_weapon_switch duration_s={time.perf_counter() - _t_ex0:.6f}"
                    )
                loop_result["phase"] = "shoot"
                loop_result["target_died"] = attack_result["target_died"] if "target_died" in attack_result else False
                loop_result["damage"] = attack_result["damage"] if "damage" in attack_result else 0
                loop_result["target_hp_remaining"] = attack_result["target_hp_remaining"] if "target_hp_remaining" in attack_result else 0
                # CRITICAL: Ensure action and unitId are set for logging
                if "action" not in loop_result:
                    loop_result["action"] = "shoot"
                if "unitId" not in loop_result:
                    loop_result["unitId"] = unit_id
                # CRITICAL: Include all_attack_results even when waiting_for_player
                # This ensures attacks already executed are logged to step.log
                shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
                if shoot_attack_results:
                    loop_result["all_attack_results"] = list(shoot_attack_results)
                    if not loop_result.get("waiting_for_player", False):
                        game_state["shoot_attack_results"] = []
                return success, loop_result
            else:
                # NO -> All weapons exhausted -> End activation
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
        else:
            # NO -> Continue normally (SHOOT_LEFT > 0)
            # Handle target outcome (died/survived)
            target_died = attack_result.get("target_died", False)
            
            if target_died:
                # Remove from valid_target_pool
                valid_target_pool = unit["valid_target_pool"] if "valid_target_pool" in unit else []
                if selected_target_id in valid_target_pool:
                    valid_target_pool.remove(selected_target_id)
                    unit["valid_target_pool"] = valid_target_pool
                
                # valid_target_pool empty? -> YES -> End activation (Slaughter handling)
                if not unit["valid_target_pool"]:
                    # CRITICAL: include_attack_results=True ensures all_attack_results is included
                    return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
                # NO -> Continue to shooting action selection step
            # else: Target survives
            
            # Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            valid_targets = unit["valid_target_pool"] if "valid_target_pool" in unit else []
            if not valid_targets and unit["SHOOT_LEFT"] > 0:
                # YES -> End activation (Slaughter handling)
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
                return _handle_shooting_end_activation(game_state, unit, ACTION, 1, SHOOTING, SHOOTING, 1, include_attack_results=True)
            # NO -> Continue to shooting action selection step
            
            # Continue to shooting action selection step
            if _perf_ts:
                _t_ex1 = time.perf_counter()
            success, loop_result = _shooting_unit_execution_loop(game_state, unit_id, config)
            if _perf_ts:
                append_perf_timing_line(
                    f"SHOOT_EXEC_LOOP episode={_ep_ts} turn={_turn_ts} unit_id={unit_id} "
                    f"context=continue_after_shot duration_s={time.perf_counter() - _t_ex1:.6f}"
                )
            loop_result["phase"] = "shoot"
            loop_result["target_died"] = attack_result["target_died"] if "target_died" in attack_result else False
            loop_result["damage"] = attack_result["damage"] if "damage" in attack_result else 0
            loop_result["target_hp_remaining"] = attack_result["target_hp_remaining"] if "target_hp_remaining" in attack_result else 0
            # CRITICAL: Ensure action and unitId are set for logging
            if "action" not in loop_result:
                loop_result["action"] = "shoot"
            if "unitId" not in loop_result:
                loop_result["unitId"] = unit_id
            # CRITICAL: Include all_attack_results even when waiting_for_player
            # This ensures attacks already executed are logged to step.log
            shoot_attack_results = game_state["shoot_attack_results"] if "shoot_attack_results" in game_state else []
            if shoot_attack_results:
                loop_result["all_attack_results"] = list(shoot_attack_results)
                if not loop_result.get("waiting_for_player", False):
                    game_state["shoot_attack_results"] = []
            return success, loop_result
    
    except Exception as e:
        import traceback
        raise  # Re-raise to see full error in server logs


def shooting_attack_controller(game_state: Dict[str, Any], unit_id: str, target_id: str) -> Dict[str, Any]:
    """
    attack_sequence(RNG) implementation with proper logging
    """
    from engine.perf_timing import append_perf_timing_line, perf_timing_enabled

    # CRITICAL: Enforce activation pool membership (no out-of-pool shooting)
    shoot_pool = require_key(game_state, "shoot_activation_pool")
    unit_id_str = str(unit_id)
    if unit_id_str not in [str(uid) for uid in shoot_pool]:
        raise ValueError(
            f"shooting_attack_controller: unit {unit_id_str} not in shoot_activation_pool={shoot_pool}"
        )
    shooter = _get_unit_by_id(game_state, unit_id)
    target = _get_unit_by_id(game_state, target_id)
    
    if not shooter or not target:
        return {"error": "unit_or_target_not_found"}

    _perf_sac = perf_timing_enabled(game_state)
    _t_sac0 = time.perf_counter() if _perf_sac else None
    _ep_sac = game_state.get("episode_number", "?")
    _turn_sac = game_state.get("turn", "?")
    
    # CRITICAL: Validate unit_id matches shooter ID (detect ID mismatches)
    shooter_id_str = str(shooter["id"])
    unit_id_str = str(unit_id)
    if shooter_id_str != unit_id_str:
        # This should never happen if _get_unit_by_id works correctly
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        from engine.game_utils import add_console_log, add_debug_log, safe_print
        log_msg = f"[CRITICAL ID BUG] E{episode} T{turn} shooting_attack_controller: unit_id={unit_id_str} but shooter.id={shooter_id_str} - ID MISMATCH!"
        add_console_log(game_state, log_msg)
        safe_print(game_state, log_msg)
    
    # CRITICAL DEBUG: Log unit details for weapon/type mismatch detection
    # This helps identify if the wrong unit is being retrieved
    shooter_unit_type = shooter.get("unitType", "Unknown")
    shooter_player = shooter.get("player", "?")
    shooter_weapons = [w.get("display_name", "unknown") for w in (shooter["RNG_WEAPONS"] if "RNG_WEAPONS" in shooter else [])]
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    from engine.game_utils import add_console_log, add_debug_log, safe_print
    debug_msg = f"[SHOOT DEBUG] E{episode} T{turn} shooting_attack_controller: unit_id={unit_id_str} shooter.id={shooter_id_str} type={shooter_unit_type} player={shooter_player} weapons={shooter_weapons}"
    add_debug_log(game_state, debug_msg)
    safe_print(game_state, debug_msg)
    
    # FOCUS FIRE: Store target's HP before damage for reward calculation (Phase 2: from cache)
    target_hp_before_damage = require_hp_from_cache(str(target["id"]), game_state)

    # Capture positions before damage so logs still have target position after target is removed from cache
    shooter_col, shooter_row = require_unit_position(shooter, game_state)
    target_col, target_row = require_unit_position(target, game_state)

    # Tutoriel 1-24 : forcer un miss au 1er tir et la mort au tir suivant (sans lancer les dés)
    if game_state.pop("_tutorial_force_miss_this_shot", False):
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        weapon = get_selected_ranged_weapon(shooter)
        weapon_name = weapon.get("display_name", "") if weapon else ""
        attack_result = {
            "damage": 0,
            "target_died": False,
            "hit_roll": 1,
            "wound_roll": None,
            "save_roll": None,
            "hit_success": False,
            "wound_success": False,
            "attack_log": "Hit:3+:1(MISS) Dmg:0HP [TUTORIAL]",
            "weapon_name": weapon_name,
            "hazardous_test_required": False,
            "hazardous_test_roll": None,
            "hazardous_triggered": False,
        }
    elif game_state.pop("_tutorial_force_kill_this_shot", False):
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        weapon = get_selected_ranged_weapon(shooter)
        weapon_name = weapon.get("display_name", "") if weapon else ""
        attack_result = {
            "damage": target_hp_before_damage,
            "target_died": True,
            "hit_roll": 6,
            "wound_roll": 6,
            "save_roll": 1,
            "hit_success": True,
            "wound_success": True,
            "attack_log": (
                f"Hit:3+:6(HIT) Wound:4+:6(WOUND) Save:4+:1(FAIL) Dmg:{target_hp_before_damage}HP"
            ),
            "weapon_name": weapon_name,
            "hazardous_test_required": False,
            "hazardous_test_roll": None,
            "hazardous_triggered": False,
        }
    else:
        # Execute single attack_sequence(RNG) per AI_TURN.md
        _t_seq0 = time.perf_counter() if _perf_sac else None
        attack_result = _attack_sequence_rng(shooter, target, game_state)
        if _perf_sac and _t_seq0 is not None:
            append_perf_timing_line(
                f"SHOOT_ATTACK_SEQUENCE_RNG episode={_ep_sac} turn={_turn_sac} shooter_id={unit_id_str} "
                f"target_id={target_id} duration_s={time.perf_counter() - _t_seq0:.6f}"
            )

    if _perf_sac and _t_sac0 is not None:
        _t_after_resolve = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_RESOLVE_ATTACK episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_resolve - _t_sac0:.6f}"
        )
    else:
        _t_after_resolve = None

    attack_result["target_hp_before_damage"] = target_hp_before_damage
    attack_result["target_coords"] = (target_col, target_row)
    # Preserve shooter metadata before potential hazardous self-destruction removes it from units_cache.
    attack_result["shooter_coords"] = (shooter_col, shooter_row)
    attack_result["shooter_player"] = require_key(shooter, "player")
    attack_result["shooter_display_name"] = shooter.get("DISPLAY_NAME")
    
    # AI_TURN.md ligne 521: Concatenate Return to TOTAL_ACTION log
    if "TOTAL_ATTACK_LOG" not in shooter:
        shooter["TOTAL_ATTACK_LOG"] = ""
    attack_log_message = attack_result.get("attack_log", "")
    if attack_log_message:
        if shooter["TOTAL_ATTACK_LOG"]:
            shooter["TOTAL_ATTACK_LOG"] += " / " + attack_log_message
        else:
            shooter["TOTAL_ATTACK_LOG"] = attack_log_message

    if _perf_sac and _t_after_resolve is not None:
        _t_after_meta = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_RESULT_META episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_meta - _t_after_resolve:.6f}"
        )
    else:
        _t_after_meta = None

    # Apply damage immediately per AI_TURN.md — HP_CUR single write path: update_units_cache_hp only (Phase 2: from cache)
    damage = require_key(attack_result, "damage")
    if damage > 0:
        new_hp = max(0, target_hp_before_damage - damage)
        target_id_str = str(target["id"])
        if not is_unit_alive(target_id_str, game_state):
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import _write_diagnostic_to_debug_log
            _write_diagnostic_to_debug_log(
                f"[ERROR] E{episode} T{turn} shooting_attack_controller: target {target_id_str} missing from units_cache before damage application"
            )
        update_units_cache_hp(game_state, target_id_str, new_hp)
        from engine.game_utils import add_debug_file_log
        hp_after = get_hp_from_cache(target_id_str, game_state)
        if hp_after is not None and hp_after != new_hp:
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_file_log(
                game_state,
                f"[HP MISMATCH] E{episode} T{turn} shooting_attack_controller: target={target_id_str} expected_hp={new_hp} actual_hp={hp_after}"
            )
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate kill probability cache for target
        from engine.ai.weapon_selector import invalidate_cache_for_target
        cache = game_state["kill_probability_cache"] if "kill_probability_cache" in game_state else {}
        invalidate_cache_for_target(cache, str(target["id"]))
        
        # Check if target died (units_cache updated above; source of truth)
        if not is_unit_alive(str(target["id"]), game_state):
            attack_result["target_died"] = True
            # DEBUG: Log target death
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_console_log, add_debug_log
            add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} target_died: Unit {target['id']} died (removed from units_cache), calling update_los_cache_after_target_death")
            
            # AI_TURN.md: Update los_cache after target death (remove entry, no recalculation)
            update_los_cache_after_target_death(game_state, target["id"])
            
            # PERFORMANCE: Invalidate LoS cache for dead unit (partial invalidation)
            # DEPRECATED: Keep for backward compatibility with global cache
            _invalidate_los_cache_for_unit(game_state, target["id"])
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Invalidate cache for dead unit (can't attack anymore)
            from engine.ai.weapon_selector import invalidate_cache_for_unit
            invalidate_cache_for_unit(cache, str(target["id"]))
            # CRITICAL: Remove dead unit from activation pools (prevents dead units from acting)
            _remove_dead_unit_from_pools(game_state, target["id"])
            
            # CRITICAL: Remove dead target from valid_target_pool for all active shooting units
            # Simply remove the dead target ID from each unit's pool (no need to rebuild)
            target_id_str = str(target["id"])
            if "shoot_activation_pool" in game_state:
                for active_unit_id in game_state["shoot_activation_pool"]:
                    active_unit = _get_unit_by_id(game_state, active_unit_id)
                    if active_unit and is_unit_alive(str(active_unit["id"]), game_state):
                        # Remove dead target from this unit's valid_target_pool
                        if "valid_target_pool" in active_unit:
                            pool_before = len(active_unit["valid_target_pool"])
                            active_unit["valid_target_pool"] = [
                                tid for tid in active_unit["valid_target_pool"] 
                                if str(tid) != target_id_str
                            ]
                            pool_after = len(active_unit["valid_target_pool"])
                            if pool_before != pool_after:
                                add_debug_log(game_state, f"[POOL DEBUG] E{episode} T{turn} target_died: Removed dead target {target_id_str} from Unit {active_unit_id} pool (before={pool_before}, after={pool_after})")

    if _perf_sac and _t_after_meta is not None:
        _t_after_damage = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_DAMAGE_AND_DEATH episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_damage - _t_after_meta:.6f}"
        )
    else:
        _t_after_damage = None

    # Store pre-damage HP in attack_result for reward calculation
    attack_result["target_hp_before_damage"] = target_hp_before_damage

    hazardous_test_required = bool(attack_result.get("hazardous_test_required", False))
    hazardous_test_roll = attack_result.get("hazardous_test_roll")
    hazardous_triggered = bool(attack_result.get("hazardous_triggered", False))
    hazardous_mortal_wounds = 0
    hazardous_self_died = False
    if hazardous_test_required:
        if not isinstance(hazardous_test_roll, int) or hazardous_test_roll < 1 or hazardous_test_roll > 6:
            raise ValueError(
                f"Invalid hazardous_test_roll for shooter {unit_id}: {hazardous_test_roll}"
            )
    if hazardous_triggered:
        shooter_id_str = str(unit_id)
        shooter_hp_before_hazardous = require_hp_from_cache(shooter_id_str, game_state)
        hazardous_mortal_wounds = 3
        shooter_new_hp = max(0, shooter_hp_before_hazardous - hazardous_mortal_wounds)
        update_units_cache_hp(game_state, shooter_id_str, shooter_new_hp)
        hazardous_self_died = not is_unit_alive(shooter_id_str, game_state)
        if hazardous_self_died:
            _remove_dead_unit_from_pools(game_state, unit_id)
            update_los_cache_after_target_death(game_state, unit_id)
            _invalidate_los_cache_for_unit(game_state, unit_id)
    attack_result["hazardous_mortal_wounds"] = hazardous_mortal_wounds
    attack_result["hazardous_self_died"] = hazardous_self_died

    if _perf_sac and _t_after_damage is not None:
        _t_after_hazard = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_HAZARDOUS_AND_HP_DEDUP episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_hazard - _t_after_damage:.6f}"
        )
    else:
        _t_after_hazard = None
    
    # Store detailed log for frontend display with location data
    if "action_logs" not in game_state:
        game_state["action_logs"] = []
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get weapon_name before building message
    weapon_name = attack_result.get("weapon_name", "")
    weapon_suffix = f" with [{weapon_name}]" if weapon_name else ""
    
    # CRITICAL: Validate weapon matches unit type (detect unit type/weapon mismatches)
    # This detects cases where a Space Marine unit uses Tyranid weapons or vice versa
    if weapon_name:
        shooter_unit_type = shooter.get("unitType", "")
        # Check if weapon faction doesn't match unit faction
        tyranid_weapons = ['deathspitter', 'fleshborer', 'devourer', 'scything talons', 'bonesword', 'lash whip']
        space_marine_weapons = ['bolt rifle', 'bolt pistol', 'chainsword', 'power sword', 'power fist', 'stalker bolt rifle']
        
        weapon_name_lower = weapon_name.lower()
        weapon_is_tyranid = any(tyranid_wpn in weapon_name_lower for tyranid_wpn in tyranid_weapons)
        weapon_is_space_marine = any(sm_wpn in weapon_name_lower for sm_wpn in space_marine_weapons)
        
        unit_is_space_marine = 'intercessor' in shooter_unit_type.lower() or 'captain' in shooter_unit_type.lower() or 'spacemarine' in shooter_unit_type.lower()
        unit_is_tyranid = 'tyranid' in shooter_unit_type.lower() or 'genestealer' in shooter_unit_type.lower() or 'hormagaunt' in shooter_unit_type.lower() or 'termagant' in shooter_unit_type.lower()
        
        # If weapon faction doesn't match unit faction, log as critical bug
        if (weapon_is_tyranid and unit_is_space_marine) or (weapon_is_space_marine and unit_is_tyranid):
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            from engine.game_utils import add_console_log, add_debug_log, safe_print
            log_msg = f"[CRITICAL WEAPON BUG] E{episode} T{turn} shooting_attack_controller: Unit {unit_id} (type={shooter_unit_type}, player={shooter.get('player')}) using weapon={weapon_name} - WEAPON/TYPE MISMATCH!"
            add_console_log(game_state, log_msg)
            safe_print(game_state, log_msg)
    
    # Enhanced message format including shooter position and weapon name per movement phase integration
    # Positions captured before damage (target may be removed from cache if dead)
    attack_log_part = attack_result["attack_log"]
    shot_rule_marker = ""
    shot_rule_ability_display_name = None
    rapid_fire_marker = ""
    if attack_result.get("rapid_fire_bonus_shot", False):
        rapid_fire_rule_value = attack_result.get("rapid_fire_rule_value")
        if not isinstance(rapid_fire_rule_value, int) or rapid_fire_rule_value <= 0:
            raise ValueError(
                f"rapid_fire_bonus_shot=True but rapid_fire_rule_value is invalid: {rapid_fire_rule_value}"
            )
        rapid_fire_marker = f" [RAPID FIRE:{rapid_fire_rule_value}]"
    shooter_id_str = str(unit_id)
    if shooter_id_str in require_key(game_state, "units_fled"):
        source_rule_display_name = _get_source_unit_rule_display_name_for_effect(shooter, "shoot_after_flee")
        if source_rule_display_name is not None:
            shot_rule_marker = f" [{source_rule_display_name}]"
            shot_rule_ability_display_name = source_rule_display_name
    else:
        if shooter_id_str in require_key(game_state, "units_advanced"):
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            selected_weapon = get_selected_ranged_weapon(shooter)
            if selected_weapon and not _weapon_has_assault_rule(selected_weapon):
                source_rule_display_name = _get_source_unit_rule_display_name_for_effect(shooter, "shoot_after_advance")
                if source_rule_display_name is not None:
                    shot_rule_marker = f" [{source_rule_display_name}]"
                    shot_rule_ability_display_name = source_rule_display_name
    enhanced_message = (
        f"Unit {unit_id}({shooter_col},{shooter_row}) SHOT{shot_rule_marker}{rapid_fire_marker} "
        f"at Unit {target_id}({target_col},{target_row}){weapon_suffix} - {attack_log_part}"
    )

    # CRITICAL FIX: Append action_log BEFORE reward calculation
    # This ensures the log exists even if reward calculation fails
    action_reward = 0.0
    action_name = "ranged_attack"
    
    # Create shoot log entry (will be appended after reward calculation)
    shoot_log_entry = {
        "type": "shoot",
        "message": enhanced_message,
        "turn": game_state["turn"],
        "phase": "shoot",
        "shooterId": unit_id,
        "targetId": target_id,
        "weaponName": weapon_name if weapon_name else None,
        "player": shooter["player"],
        "shooterCol": shooter_col,
        "shooterRow": shooter_row,
        "targetCol": target_col,
        "targetRow": target_row,
        "damage": attack_result["damage"],
        "target_died": attack_result.get("target_died", False),
        "hitRoll": attack_result.get("hit_roll"),
        "woundRoll": attack_result.get("wound_roll"),
        "saveRoll": attack_result.get("save_roll"),
        "saveTarget": attack_result.get("save_target"),
        "saveSkipped": attack_result.get("save_skipped", False),
        "saveSkipReason": attack_result.get("save_skip_reason"),
        "devastatingWoundsApplied": attack_result.get("devastating_wounds_applied", False),
        "ability_display_name": shot_rule_ability_display_name,
        "wound_ability_display_name": attack_result.get("wound_ability_display_name"),
        "ap_modifier_ability_display_name": attack_result.get("ap_modifier_ability_display_name"),
        "rapidFireBonusShot": attack_result.get("rapid_fire_bonus_shot", False),
        "rapidFireRuleValue": attack_result.get("rapid_fire_rule_value"),
        "hazardousTestRequired": hazardous_test_required,
        "hazardousTestRoll": hazardous_test_roll,
        "hazardousTriggered": hazardous_triggered,
        "hazardousMortalWounds": hazardous_mortal_wounds,
        "hazardousSelfDied": hazardous_self_died,
        "timestamp": "server_time",
        "action_name": action_name,
        "reward": 0.0,  # Will be updated after reward calculation
        "is_ai_action": shooter["player"] == 1
    }
    
    # Append the shoot log entry immediately
    game_state["action_logs"].append(shoot_log_entry)
    if hazardous_triggered:
        if hazardous_self_died:
            hazardous_message = f"Unit {unit_id}({shooter_col},{shooter_row}) was DESTROYED [HAZARDOUS]"
            game_state["action_logs"].append({
                "type": "death",
                "message": hazardous_message,
                "turn": game_state["turn"],
                "phase": "shoot",
                "targetId": unit_id,
                "unitId": unit_id,
                "player": shooter["player"],
                "timestamp": "server_time",
            })
        else:
            hazardous_message = (
                f"Unit {unit_id}({shooter_col},{shooter_row}) SUFFERS "
                f"{hazardous_mortal_wounds} Mortal Wounds [HAZARDOUS]"
            )
            game_state["action_logs"].append({
                "type": "reactive_move",
                "message": hazardous_message,
                "turn": game_state["turn"],
                "phase": "shoot",
                "unitId": unit_id,
                "player": shooter["player"],
                "timestamp": "server_time",
            })
    add_console_log(game_state, enhanced_message)
    
    # DEBUG: Log shooting attack execution
    if "episode_number" in game_state and "turn" in game_state:
        episode = game_state["episode_number"]
        turn = game_state["turn"]
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        damage = attack_result["damage"] if "damage" in attack_result else 0
        target_died = attack_result["target_died"] if "target_died" in attack_result else False
        log_msg = f"[SHOOT DEBUG] E{episode} T{turn} shoot attack_executed: Unit {unit_id} -> Unit {target_id} damage={damage} target_died={target_died}"
        from engine.game_utils import add_console_log, add_debug_log
        from engine.game_utils import safe_print
        add_debug_log(game_state, log_msg)
        safe_print(game_state, log_msg)

    if _perf_sac and _t_after_hazard is not None:
        _t_after_ux = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_MSG_ACTION_LOGS_CONSOLE episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_ux - _t_after_hazard:.6f}"
        )
    else:
        _t_after_ux = None

    # Calculate reward for this action using progressive bonus system
    # OPTIMIZATION: Only calculate rewards for controlled player's units
    # Bot units don't need rewards since they don't learn
    cfg = require_key(game_state, "config")
    controlled_player = int(require_key(cfg, "controlled_player"))

    # Skip reward calculation for bot units (not the controlled player)
    if shooter["player"] != controlled_player:
        action_reward = 0.0
        # Continue without calculating detailed rewards
    else:
   
        try:
            from ai.reward_mapper import RewardMapper
            rewards_configs = require_key(game_state, "rewards_configs")
            from ai.unit_registry import UnitRegistry
            unit_registry = UnitRegistry()
            scenario_unit_type = require_key(shooter, "unitType")
            reward_config_key = unit_registry.get_model_key(scenario_unit_type)
            unit_reward_config = require_key(rewards_configs, reward_config_key)

            reward_mapper = RewardMapper(unit_reward_config)
            enriched_shooter = shooter.copy()
            enriched_shooter["unitType"] = reward_config_key
       
        # Get unit rewards config
            unit_rewards = reward_mapper._get_unit_rewards(enriched_shooter)
            base_actions = require_key(unit_rewards, "base_actions")
            result_bonuses = require_key(unit_rewards, "result_bonuses")
       
            if "ranged_attack" not in base_actions:
                raise KeyError(f"Missing 'ranged_attack' in base_actions for unit {shooter['id']} (enriched_unitType={enriched_shooter.get('unitType')}): base_actions={base_actions}")
        
            base_ranged_reward = base_actions["ranged_attack"]
        
        # Base shooting reward (always given for taking the shot)
            action_reward = base_ranged_reward
       
        # Progressive bonuses based on attack sequence results
            if attack_result.get("hit_success", False):
                if "hit_target" in result_bonuses:
                    action_reward += result_bonuses["hit_target"]
                    action_name = "hit_target"
       
            if attack_result.get("wound_success", False):
                if "wound_target" in result_bonuses:
                    action_reward += result_bonuses["wound_target"]
                    action_name = "wound_target"
       
            if (attack_result["damage"] if "damage" in attack_result else 0) > 0:
                if "damage_target" in result_bonuses:
                    action_reward += result_bonuses["damage_target"]
                    action_name = "damage_target"
       
            if attack_result["target_died"] if "target_died" in attack_result else False:
                if "kill_target" in result_bonuses:
                    action_reward += result_bonuses["kill_target"]
                    action_name = "kill_target"

            # No overkill bonus (exact kill)
                dmg = attack_result["damage"] if "damage" in attack_result else 0
                if (target_hp_before_damage or 0) == dmg:
                    if "no_overkill" in result_bonuses:
                        action_reward += result_bonuses["no_overkill"]

            # FOCUS FIRE BONUS: Check if shooter targeted the lowest HP enemy
            if "target_lowest_hp" in result_bonuses:
                try:
                    from engine.perf_timing import append_perf_timing_line, focus_fire_pool_audit_enabled

                    valid_target_ids = focus_fire_valid_target_ids_for_reward(shooter, game_state)

                    if focus_fire_pool_audit_enabled(game_state):
                        _rebuilt_ff = shooting_build_valid_target_pool(
                            game_state, str(shooter["id"])
                        )
                        _vpool = shooter.get("valid_target_pool")
                        if isinstance(_vpool, list):
                            _cached_set = {str(x) for x in _vpool}
                        else:
                            _cached_set = set()
                        _used_set = {str(x) for x in valid_target_ids}
                        _rebuilt_set = {str(x) for x in _rebuilt_ff}
                        _tdied = bool(attack_result.get("target_died", False))
                        _ep_ff = game_state.get("episode_number", "?")
                        _turn_ff = game_state.get("turn", "?")
                        _sid = str(shooter["id"])
                        if _rebuilt_set == _used_set:
                            append_perf_timing_line(
                                f"SHOOT_FOCUS_FIRE_POOL_AUDIT episode={_ep_ff} turn={_turn_ff} shooter_id={_sid} "
                                f"match=1 count={len(_rebuilt_set)} target_died={_tdied}"
                            )
                        else:
                            append_perf_timing_line(
                                f"SHOOT_FOCUS_FIRE_POOL_AUDIT episode={_ep_ff} turn={_turn_ff} shooter_id={_sid} "
                                f"match=0 target_died={_tdied} count_rebuilt={len(_rebuilt_set)} count_used={len(_used_set)} "
                                f"count_cached={len(_cached_set)} "
                                f"only_in_rebuild={sorted(_rebuilt_set - _used_set)} "
                                f"only_in_used={sorted(_used_set - _rebuilt_set)}"
                            )

                    if len(valid_target_ids) > 1:  # Only apply if there was a choice
                        # Get the target's HP before this shot (from attack_result)
                        target_hp_before = attack_result.get("target_hp_before_damage")
                        if target_hp_before is None:
                            target_hp_before = target_hp_before_damage

                        # Find the lowest HP among all valid targets AT THE TIME OF SHOOTING
                        lowest_hp = float('inf')
                        for focus_pool_tid in valid_target_ids:
                            candidate = _get_unit_by_id(game_state, focus_pool_tid)
                            if not candidate:
                                continue

                            # Get candidate's current HP (Phase 2: from cache)
                            # If this is the target we just shot, use pre-damage HP
                            if candidate["id"] == target["id"]:
                                candidate_hp = target_hp_before
                            else:
                                candidate_hp = get_hp_from_cache(str(candidate["id"]), game_state)
                                if candidate_hp is None:
                                    continue

                            # Only consider alive targets
                            if candidate_hp > 0:
                                lowest_hp = min(lowest_hp, candidate_hp)

                        # Check if the actual target had the lowest HP (or tied for lowest)
                        if target_hp_before > 0 and target_hp_before <= lowest_hp:
                            action_reward += result_bonuses["target_lowest_hp"]
                            # Don't override action_name - keep kill_target/damage_target as primary
                except Exception as focus_fire_error:
                    # Don't crash training if focus fire bonus fails
                    pass

        except Exception as e:
            pass
            raise

    if _perf_sac and _t_after_ux is not None:
        _t_after_reward = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_REWARD_BLOCK episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_after_reward - _t_after_ux:.6f}"
        )
    else:
        _t_after_reward = None

    # Update the shoot log entry with calculated reward and action_name
    logged_reward = round(action_reward, 2)
    shoot_log_entry["reward"] = logged_reward
    shoot_log_entry["action_name"] = action_name
    
    # Add separate death log event if target was killed (AFTER shoot log)
    if attack_result.get("target_died", False):
        game_state["action_logs"].append({
            "type": "death",
            "message": f"Unit {target_id} was DESTROYED",
            "turn": game_state["turn"],
            "phase": "shoot",
            "targetId": target_id,
            "unitId": target_id,
            "player": target["player"],
            "timestamp": "server_time"
        })
    
    # Store attack result for engine access
    game_state["last_attack_result"] = attack_result
    game_state["last_target_id"] = target_id
    
    if "calculated_rewards" not in game_state:
        game_state["calculated_rewards"] = {}
    game_state["calculated_rewards"][unit_id] = logged_reward
    game_state["last_calculated_reward"] = logged_reward
    
    # Target may have been removed from cache if it died; use get_hp_from_cache (0 if dead)
    target_hp_remaining = get_hp_from_cache(str(target["id"]), game_state)
    target_hp_remaining = 0 if target_hp_remaining is None else target_hp_remaining

    if _perf_sac and _t_after_reward is not None:
        _t_before_return = time.perf_counter()
        append_perf_timing_line(
            f"SHOOT_CTRL_TAIL episode={_ep_sac} turn={_turn_sac} unit_id={unit_id} target_id={target_id} "
            f"duration_s={_t_before_return - _t_after_reward:.6f}"
        )

    return {
        "action": "shot_executed",
        "phase": "shoot",  # For metrics tracking
        "shooterId": unit_id,
        "targetId": target_id,
        "attack_result": attack_result,
        "target_hp_remaining": target_hp_remaining,
        "target_died": not is_unit_alive(str(target["id"]), game_state),
        "calculated_reward": logged_reward
    }


def _attack_sequence_rng(attacker: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    attack_sequence(RNG) with proper <OFF> replacement
    MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon
    """
    import random
    from engine.utils.weapon_helpers import get_selected_ranged_weapon
    
    attacker_id = attacker["id"] 
    target_id = target["id"]
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Get selected weapon
    weapon = get_selected_ranged_weapon(attacker)
    if not weapon:
        raise ValueError(f"Attacker {attacker_id} has no selected ranged weapon")
    
    # Hit roll -> hit_roll >= weapon.ATK
    hit_roll = random.randint(1, 6)
    base_hit_target = weapon["ATK"]
    heavy_applied = _weapon_has_heavy_rule(weapon) and _is_unit_stationary_for_heavy(attacker_id, game_state)
    if heavy_applied:
        hit_target = max(2, base_hit_target - 1)
    else:
        hit_target = base_hit_target
    hit_target_display = f"{hit_target}+"
    hit_target_display_with_heavy = f"{base_hit_target}+->{hit_target}+" if heavy_applied else hit_target_display
    heavy_log_suffix = " [HEAVY]" if heavy_applied else ""
    hit_success = hit_roll >= hit_target
    
    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Include weapon name in attack_log
    weapon_name = weapon.get("display_name", "")
    weapon_prefix = f" with [{weapon_name}]" if weapon_name else ""
    has_devastating_wounds = _weapon_has_devastating_wounds_rule(weapon)
    has_hazardous = _weapon_has_hazardous_rule(weapon)
    hazardous_roll = random.randint(1, 6) if has_hazardous else None
    hazardous_triggered = has_hazardous and hazardous_roll == 1
    hazardous_log_suffix = f" [HAZARDOUS] Roll:{hazardous_roll}" if has_hazardous else ""
    rapid_fire_bonus_shot = bool(attacker.get("_rapid_fire_bonus_shot_current", False))
    rapid_fire_rule_value = int(require_key(attacker, "_rapid_fire_rule_value"))
    if rapid_fire_bonus_shot and rapid_fire_rule_value <= 0:
        raise ValueError(
            f"rapid_fire_bonus_shot=True but _rapid_fire_rule_value is invalid: {rapid_fire_rule_value}"
        )
    rapid_fire_rule_marker = f" [RAPID FIRE:{rapid_fire_rule_value}]" if rapid_fire_bonus_shot else ""
    
    if not hit_success:
        # MISS case
        attack_log = f"Hit:{hit_target_display_with_heavy}:{hit_roll}(FAIL){heavy_log_suffix}{hazardous_log_suffix}"
        return {
            "hit_roll": hit_roll,
            "hit_target_base": base_hit_target,
            "hit_target": hit_target,
            "hit_rule_modifier": "HEAVY" if heavy_applied else None,
            "hit_success": False,
            "wound_roll": 0,
            "wound_target": 0,
            "wound_success": False,
            "save_roll": 0,
            "save_target": 0,
            "save_target_base": 0,
            "save_cover_applied": False,
            "save_cover_bonus": 0,
            "save_success": False,
            "save_skipped": False,
            "save_skip_reason": None,
            "critical_wound_unmodified": False,
            "devastating_wounds_expected": False,
            "devastating_wounds_applied": False,
            "devastating_wounds_flag": False,
            "rapid_fire_bonus_shot": rapid_fire_bonus_shot,
            "rapid_fire_rule_value": rapid_fire_rule_value,
            "hazardous_test_required": has_hazardous,
            "hazardous_test_roll": hazardous_roll,
            "hazardous_triggered": hazardous_triggered,
            "damage": 0,
            "wound_ability_display_name": None,
            "ap_modifier_ability_display_name": None,
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # HIT -> Continue to wound roll
    wound_roll = random.randint(1, 6)
    wound_target = _calculate_wound_target(weapon["STR"], target["T"])
    wound_success = wound_roll >= wound_target
    wound_log_suffix = ""
    wound_ability_display_name = None
    if not wound_success:
        can_reroll_failed_wound_on_objective = (
            _unit_has_rule(attacker, "reroll_towound_target_on_objective")
            and _is_unit_on_objective(target, game_state)
        )
        can_reroll_wound_ones = wound_roll == 1 and _unit_has_rule(attacker, "reroll_1_towound")
        if can_reroll_failed_wound_on_objective or can_reroll_wound_ones:
            wound_roll = random.randint(1, 6)
            wound_success = wound_roll >= wound_target
            if can_reroll_failed_wound_on_objective:
                source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                    attacker, "reroll_towound_target_on_objective"
                )
                if source_rule_display_name is None:
                    raise ValueError(
                        f"Attacker {attacker_id} rerolled wound on objective without source unit rule"
                    )
                wound_ability_display_name = source_rule_display_name
                wound_log_suffix = f" [{source_rule_display_name}]"
            else:
                source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                    attacker, "reroll_1_towound"
                )
                if source_rule_display_name is None:
                    raise ValueError(
                        f"Attacker {attacker_id} rerolled wound roll of 1 without source unit rule"
                    )
                wound_ability_display_name = source_rule_display_name
                wound_log_suffix = f" [{source_rule_display_name}]"
    
    if not wound_success:
        # FAIL case
        attack_log = (
            f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
            f"Wound:{wound_target}+:{wound_roll}(FAIL){wound_log_suffix}{hazardous_log_suffix}"
        )
        return {
            "hit_roll": hit_roll,
            "hit_target_base": base_hit_target,
            "hit_target": hit_target,
            "hit_rule_modifier": "HEAVY" if heavy_applied else None,
            "hit_success": True,  # Hit succeeded to reach wound roll
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": False,
            "save_roll": 0,
            "save_target": 0,
            "save_target_base": 0,
            "save_cover_applied": False,
            "save_cover_bonus": 0,
            "save_success": False,
            "save_skipped": False,
            "save_skip_reason": None,
            "critical_wound_unmodified": False,
            "devastating_wounds_expected": False,
            "devastating_wounds_applied": False,
            "devastating_wounds_flag": False,
            "rapid_fire_bonus_shot": rapid_fire_bonus_shot,
            "rapid_fire_rule_value": rapid_fire_rule_value,
            "hazardous_test_required": has_hazardous,
            "hazardous_test_roll": hazardous_roll,
            "hazardous_triggered": hazardous_triggered,
            "damage": 0,
            "wound_ability_display_name": wound_ability_display_name,
            "ap_modifier_ability_display_name": None,
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # WOUND -> Continue to save roll
    critical_wound_unmodified = wound_roll == 6
    devastating_wounds_applied = has_devastating_wounds and critical_wound_unmodified
    if devastating_wounds_applied:
        damage_dealt = resolve_dice_value(require_key(weapon, "DMG"), "shooting_damage")
        target_hp = require_hp_from_cache(str(target["id"]), game_state)
        new_hp = max(0, target_hp - damage_dealt)
        if new_hp <= 0:
            attack_log = (
                f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
                f"Wound:{wound_target}+:{wound_roll}(SUCCESS){wound_log_suffix} "
                f"Save:SKIPPED [DEVASTATING WOUNDS] Dmg:{damage_dealt}HP{hazardous_log_suffix}"
            )
        else:
            attack_log = (
                f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
                f"Wound:{wound_target}+:{wound_roll}(SUCCESS){wound_log_suffix} "
                f"Save:SKIPPED [DEVASTATING WOUNDS] Dmg:{damage_dealt}HP{hazardous_log_suffix}"
            )
        return {
            "hit_roll": hit_roll,
            "hit_target_base": base_hit_target,
            "hit_target": hit_target,
            "hit_rule_modifier": "HEAVY" if heavy_applied else None,
            "hit_success": True,
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": True,
            "save_roll": 0,
            "save_target": 0,
            "save_target_base": 0,
            "save_cover_applied": False,
            "save_cover_bonus": 0,
            "save_success": False,
            "save_skipped": True,
            "save_skip_reason": "DEVASTATING_WOUNDS",
            "critical_wound_unmodified": True,
            "devastating_wounds_expected": True,
            "devastating_wounds_applied": True,
            "devastating_wounds_flag": True,
            "rapid_fire_bonus_shot": rapid_fire_bonus_shot,
            "rapid_fire_rule_value": rapid_fire_rule_value,
            "hazardous_test_required": has_hazardous,
            "hazardous_test_roll": hazardous_roll,
            "hazardous_triggered": hazardous_triggered,
            "damage": damage_dealt,
            "wound_ability_display_name": wound_ability_display_name,
            "ap_modifier_ability_display_name": None,
            "attack_log": attack_log,
            "weapon_name": weapon_name,
        }

    save_roll = random.randint(1, 6)
    effective_ap = require_key(weapon, "AP")
    ap_modifier_ability_display_name = None
    if _unit_has_rule(attacker, "closest_target_penetration"):
        valid_target_ids = shooting_build_valid_target_pool(game_state, str(attacker_id))
        if valid_target_ids:
            attacker_col, attacker_row = require_unit_position(attacker, game_state)
            min_distance = None
            target_distance = None
            target_id_str = str(target_id)
            for candidate_id in valid_target_ids:
                candidate_unit = _get_unit_by_id(game_state, candidate_id)
                if not candidate_unit:
                    continue
                candidate_col, candidate_row = require_unit_position(candidate_unit, game_state)
                candidate_distance = _calculate_hex_distance(
                    attacker_col, attacker_row, candidate_col, candidate_row
                )
                if min_distance is None or candidate_distance < min_distance:
                    min_distance = candidate_distance
                if str(candidate_unit["id"]) == target_id_str:
                    target_distance = candidate_distance
            if (
                min_distance is not None
                and target_distance is not None
                and target_distance == min_distance
            ):
                source_rule_display_name = _get_source_unit_rule_display_name_for_effect(
                    attacker, "closest_target_penetration"
                )
                if source_rule_display_name is None:
                    raise ValueError(
                        f"Attacker {attacker_id} applied closest_target_penetration without source unit rule"
                    )
                ap_modifier_ability_display_name = source_rule_display_name
                effective_ap = effective_ap - 1
    save_target_base = _calculate_save_target(target, effective_ap, save_bonus=0)
    target_in_cover = False
    cover_bonus_applied = False
    cover_bonus_value = 0
    if not _weapon_has_ignores_cover_rule(weapon):
        attacker_col, attacker_row = require_unit_position(attacker, game_state)
        target_col, target_row = require_unit_position(target, game_state)
        target_hexes = _resolve_target_hexes_for_los(
            game_state,
            target,
            int(target_col),
            int(target_row),
        )
        target_visibility_ratio, can_see, target_in_cover, _visible_hexes, _max_hex_ratio = (
            _compute_target_visibility_from_hexes(
                game_state,
                int(attacker_col),
                int(attacker_row),
                target_hexes,
            )
        )
        if not can_see:
            _dump_los_contradiction_diagnostic(
                game_state, attacker, target, attacker_id, target_id,
                attacker_col, attacker_row, target_col, target_row,
            )
            raise ValueError(
                f"Target {target_id} became not visible during save calculation "
                f"(target_visibility_ratio={target_visibility_ratio:.3f})"
            )
        if target_in_cover:
            cover_bonus_applied = True
            cover_bonus_value = 1
    save_target = _calculate_save_target(target, effective_ap, save_bonus=cover_bonus_value)
    save_target_display = (
        f"{save_target_base}+->{save_target}+"
        if cover_bonus_applied
        else f"{save_target}+"
    )
    save_cover_log_suffix = " [COVER]" if cover_bonus_applied else ""
    save_log_suffix = (
        f" [{ap_modifier_ability_display_name}]"
        if isinstance(ap_modifier_ability_display_name, str) and ap_modifier_ability_display_name.strip()
        else ""
    )
    save_success = save_roll >= save_target
    
    if save_success:
        # SAVE case
        attack_log = (
            f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
            f"Wound:{wound_target}+:{wound_roll}(WOUND){wound_log_suffix} "
            f"Save:{save_target_display}:{save_roll}(SAVED){save_log_suffix}{save_cover_log_suffix}{hazardous_log_suffix}"
        )
        return {
            "hit_roll": hit_roll,
            "hit_target_base": base_hit_target,
            "hit_target": hit_target,
            "hit_rule_modifier": "HEAVY" if heavy_applied else None,
            "hit_success": True,  # Hit succeeded
            "wound_roll": wound_roll,
            "wound_target": wound_target,
            "wound_success": True,  # Wound succeeded
            "save_roll": save_roll,
            "save_target": save_target,
            "save_target_base": save_target_base,
            "save_cover_applied": cover_bonus_applied,
            "save_cover_bonus": cover_bonus_value,
            "save_success": True,
            "save_skipped": False,
            "save_skip_reason": None,
            "critical_wound_unmodified": critical_wound_unmodified,
            "devastating_wounds_expected": False,
            "devastating_wounds_applied": False,
            "devastating_wounds_flag": False,
            "rapid_fire_bonus_shot": rapid_fire_bonus_shot,
            "rapid_fire_rule_value": rapid_fire_rule_value,
            "hazardous_test_required": has_hazardous,
            "hazardous_test_roll": hazardous_roll,
            "hazardous_triggered": hazardous_triggered,
            "damage": 0,
            "wound_ability_display_name": wound_ability_display_name,
            "ap_modifier_ability_display_name": ap_modifier_ability_display_name,
            "attack_log": attack_log,
            "weapon_name": weapon_name
        }
    
    # FAIL -> Continue to damage (Phase 2: HP from cache)
    damage_dealt = resolve_dice_value(require_key(weapon, "DMG"), "shooting_damage")
    target_hp = require_hp_from_cache(str(target["id"]), game_state)
    new_hp = max(0, target_hp - damage_dealt)
    
    if new_hp <= 0:
        # Target dies
        attack_log = (
            f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
            f"Wound:{wound_target}+:{wound_roll}(WOUND){wound_log_suffix} "
            f"Save:{save_target_display}:{save_roll}(FAIL){save_log_suffix}{save_cover_log_suffix} Dmg:{damage_dealt}HP{hazardous_log_suffix}"
        )
    else:
        # Target survives
        attack_log = (
            f"Hit:{hit_target_display_with_heavy}:{hit_roll}(HIT){heavy_log_suffix} "
            f"Wound:{wound_target}+:{wound_roll}(WOUND){wound_log_suffix} "
            f"Save:{save_target_display}:{save_roll}(FAIL){save_log_suffix}{save_cover_log_suffix} Dmg:{damage_dealt}HP{hazardous_log_suffix}"
        )
    
    return {
        "hit_roll": hit_roll,
        "hit_target_base": base_hit_target,
        "hit_target": hit_target,
        "hit_rule_modifier": "HEAVY" if heavy_applied else None,
        "hit_success": True,  # Hit succeeded
        "wound_roll": wound_roll,
        "wound_target": wound_target,
        "wound_success": True,  # Wound succeeded
        "save_roll": save_roll,
        "save_target": save_target,
        "save_target_base": save_target_base,
        "save_cover_applied": cover_bonus_applied,
        "save_cover_bonus": cover_bonus_value,
        "save_success": False,  # Save failed
        "save_skipped": False,
        "save_skip_reason": None,
        "critical_wound_unmodified": critical_wound_unmodified,
        "devastating_wounds_expected": False,
        "devastating_wounds_applied": False,
        "devastating_wounds_flag": False,
        "rapid_fire_bonus_shot": rapid_fire_bonus_shot,
        "rapid_fire_rule_value": rapid_fire_rule_value,
        "hazardous_test_required": has_hazardous,
        "hazardous_test_roll": hazardous_roll,
        "hazardous_triggered": hazardous_triggered,
        "damage": damage_dealt,
        "wound_ability_display_name": wound_ability_display_name,
        "ap_modifier_ability_display_name": ap_modifier_ability_display_name,
        "attack_log": attack_log,
        "weapon_name": weapon_name
    }


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


def _handle_unit_switch_with_context(game_state: Dict[str, Any], current_unit_id: str, new_unit_id: str, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    AI_SHOOT.md: Handle switching between units in activation pool
    Postpone current unit (if hasn't shot) and activate new unit
    """
    # Postpone current unit activation (clear active unit, keep in pool)
    current_unit = _get_unit_by_id(game_state, current_unit_id)
    if current_unit:
        # Clear active unit but don't remove from pool
        if "active_shooting_unit" in game_state:
            del game_state["active_shooting_unit"]
    
    # Start new unit activation
    new_unit = _get_unit_by_id(game_state, new_unit_id)
    if new_unit:
        result = shooting_unit_activation_start(game_state, new_unit_id)
        if result.get("success"):
            # Preserve advance availability contract for units without valid shooting targets.
            if result.get("allow_advance"):
                result["waiting_for_player"] = True
                result["action"] = "empty_target_advance_available"
                if "empty_target_pool" not in result:
                    result["empty_target_pool"] = True
                if "can_advance" not in result:
                    result["can_advance"] = True
                return True, result
            return _shooting_unit_execution_loop(game_state, new_unit_id, config)
    
    return False, {"error": "unit_switch_failed"}


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
    unit_id_str = str(require_key(unit, "id"))
    if _unit_has_shot_with_any_weapon(unit):
        return True
    return unit_id_str in require_key(game_state, "units_advanced")


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
    from engine.utils.weapon_helpers import get_melee_range
    from engine.hex_utils import min_distance_between_sets
    cc_range = get_melee_range(game_state)

    unit_col, unit_row = require_unit_position(unit, game_state)
    unit_player = int(unit["player"]) if unit["player"] is not None else None

    units_cache = require_key(game_state, "units_cache")
    unit_id_str = str(unit["id"])
    unit_entry = units_cache.get(unit_id_str)
    unit_fp = unit_entry.get("occupied_hexes", {(unit_col, unit_row)}) if unit_entry else {(unit_col, unit_row)}

    for enemy_id, cache_entry in units_cache.items():
        enemy_player = int(cache_entry["player"]) if cache_entry.get("player") is not None else None
        if enemy_player != unit_player:
            enemy_fp = cache_entry.get("occupied_hexes", {(cache_entry["col"], cache_entry["row"])})
            distance = min_distance_between_sets(unit_fp, enemy_fp, max_distance=cc_range)
            if distance <= cc_range:
                return True
    return False


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

    # Build valid destinations using BFS (same as movement phase)
    original_move = unit["MOVE"]
    unit["MOVE"] = advance_move_budget

    # Use movement pathfinding to get valid destinations
    valid_destinations = movement_build_valid_destinations_pool(game_state, unit_id)

    # Restore original MOVE
    unit["MOVE"] = original_move
    
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

        # CRITICAL: Final occupation check IMMEDIATELY before position assignment
        # This prevents race conditions where multiple units select the same destination
        # before any of them have moved. Must check JUST before assignment, not earlier.
        dest_col_int, dest_row_int = int(dest_col), int(dest_row)
        
        # DEBUG: Log occupation check for debugging collisions
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "shoot")
        from engine.game_utils import conditional_debug_print
        conditional_debug_print(game_state, f"[OCCUPATION CHECK] E{episode} T{turn} {phase}: Unit {unit['id']} checking advance destination ({dest_col_int},{dest_row_int})")
        
        unit_id_str = str(unit["id"])
        occupied_positions = build_occupied_positions_set(game_state, exclude_unit_id=unit_id_str)
        candidate_fp = compute_candidate_footprint(dest_col_int, dest_row_int, unit, game_state)
        if not is_footprint_placement_valid(candidate_fp, game_state, occupied_positions):
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
        
        # Execute advance movement
        # CRITICAL: Log ALL position changes to detect unauthorized modifications
        # CRITICAL: Log ALL position changes to detect unauthorized modifications
        # ALWAYS log, even if episode_number/turn/phase are missing (for debugging)
        episode = game_state.get("episode_number", "?")
        turn = game_state.get("turn", "?")
        phase = game_state.get("phase", "shoot")
        if "console_logs" not in game_state:
            game_state["console_logs"] = []
        log_message = f"[POSITION CHANGE] E{episode} T{turn} {phase} Unit {unit['id']}: ({orig_col},{orig_row})→({dest_col},{dest_row}) via ADVANCE"
        from engine.game_utils import add_console_log, add_debug_log
        from engine.game_utils import safe_print
        add_console_log(game_state, log_message)
        safe_print(game_state, log_message)
        
        # CRITICAL: Log BEFORE each assignment to catch any modification
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

        # Update units_cache after position change (advance)
        update_units_cache_position(game_state, adv_uid_str, dest_col_int, dest_row_int)

        adv_new_entry = require_key(game_state, "units_cache").get(adv_uid_str)
        adv_new_occupied = adv_new_entry.get("occupied_hexes") if adv_new_entry else None

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
        
        # Check if unit actually moved (for cache invalidation and logging)
        actually_moved = (orig_col != dest_col) or (orig_row != dest_row)
        
        # CRITICAL: Invalidate LoS cache ONLY if unit actually moved
        # The unit's position changed, so LoS cache entries are now stale
        if actually_moved:
            # CRITICAL: Invalidate LoS cache when unit advances (moves)
            _invalidate_los_cache_for_moved_unit(game_state, unit["id"], old_col=orig_col, old_row=orig_row)
            
            # AI_TURN.md STEP 4: Rebuild unit's los_cache with new position after advance
            # CRITICAL: Rebuild unit-local cache (not global cache) with new position
            build_unit_los_cache(game_state, unit["id"])
            
            # CRITICAL: Invalidate all destination pools after advance movement
            # Positions have changed, so all pools (move, charge, shoot) are now stale
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
                    
        game_state["action_logs"].append({
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
            "actually_moved": actually_moved,
            "timestamp": "server_time"
        })
        
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
            return True, {
                "action": "advance",
                "unitId": unit_id,
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_roll,
                "advance_max_subhex": advance_move_budget,
                "actually_moved": actually_moved,
                "blinking_units": valid_target_pool,
                "start_blinking": True,
                "waiting_for_player": True,
                "available_weapons": available_weapons
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
                "actually_moved": actually_moved
            })
            return success, result
    else:
        # No destination - return valid destinations for player/AI to choose
        # For AI, auto-select best destination
        movable_destinations = [d for d in valid_destinations if int(d[0]) != int(orig_col) or int(d[1]) != int(orig_row)]
        
        if (is_gym_training or is_pve_ai) and movable_destinations:
            # Auto-select: move toward nearest enemy (aggressive strategy)
            units_cache = require_key(game_state, "units_cache")
            unit_player = int(unit["player"]) if unit["player"] is not None else None
            enemies = [enemy_id for enemy_id, cache_entry in units_cache.items()
                       if int(cache_entry["player"]) != unit_player]
            
            if enemies:
                unit_col, unit_row = require_unit_position(unit, game_state)
                nearest_enemy_id = min(enemies, key=lambda e: _calculate_hex_distance(unit_col, unit_row, *require_unit_position(e, game_state)))
                nearest_enemy_col, nearest_enemy_row = require_unit_position(nearest_enemy_id, game_state)
                best_dest = min(movable_destinations, key=lambda d: _calculate_hex_distance(d[0], d[1], nearest_enemy_col, nearest_enemy_row))
            else:
                best_dest = movable_destinations[0]
            
            # Recursively call with destination
            action["destCol"] = best_dest[0]
            action["destRow"] = best_dest[1]
            return _handle_advance_action(game_state, unit, action, config)
        
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
