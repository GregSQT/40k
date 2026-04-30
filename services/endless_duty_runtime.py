#!/usr/bin/env python3
"""
services/endless_duty_runtime.py

Endless Duty orchestration layer on top of the existing engine loop:
- wave budget composition (VALUE-driven)
- objective loss tracking
- inter-wave requisition capital accounting
- enemy wave spawning on board edges
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, resolve_dice_value
from engine.phase_handlers.shared_utils import build_units_cache, rebuild_choice_timing_index
from engine.phase_handlers import command_handlers, movement_handlers


ED_MODE_CODE = "endless_duty"
ED_SCENARIO_DEFAULT = "config/scenario_endless_duty.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ED_START_LEADER_COL = 12
ED_START_LEADER_ROW = 10


def is_endless_duty_mode(engine_instance: Any) -> bool:
    """Return True when engine runs Endless Duty mode."""
    mode_code = engine_instance.game_state.get("current_mode_code")
    return isinstance(mode_code, str) and mode_code == ED_MODE_CODE


def load_endless_duty_config(project_root: Path, scenario_file: str) -> Dict[str, Any]:
    """Load scenario endless_duty config with strict validation."""
    scenario_path = project_root / scenario_file
    if not scenario_path.exists():
        raise FileNotFoundError(f"Endless Duty scenario not found: {scenario_path}")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)
    endless_cfg = require_key(scenario_data, "endless_duty")
    if not isinstance(endless_cfg, dict):
        raise TypeError("scenario_endless_duty.json field 'endless_duty' must be an object")
    return endless_cfg


def initialize_endless_duty_state(
    engine_instance: Any,
    project_root: Path,
    scenario_file: str,
) -> Dict[str, Any]:
    """Initialize Endless Duty run state on a fresh engine.reset()."""
    endless_cfg = load_endless_duty_config(project_root, scenario_file)
    gs = require_key(engine_instance.__dict__, "game_state")
    if "units_cache" not in gs:
        raise KeyError("units_cache is required before Endless Duty initialization")

    # Ensure mode code is persisted in game_state (single source for API routing).
    gs["current_mode_code"] = ED_MODE_CODE
    gs["player_types"] = {"1": "human", "2": "ai"}
    gs["endless_duty_config"] = copy.deepcopy(endless_cfg)
    _disable_turn_limit_for_endless_duty(engine_instance, gs)

    objective_rules = require_key(endless_cfg, "objective_rules")
    loss_threshold = require_key(objective_rules, "loss_counter_threshold")
    if not isinstance(loss_threshold, int) or loss_threshold <= 0:
        raise ValueError("endless_duty.objective_rules.loss_counter_threshold must be a positive integer")

    # Build initial slot assignments from current player-1 units.
    old_p1_units = _get_alive_units_for_player(gs, player=1)
    if not old_p1_units:
        raise ValueError("Endless Duty requires at least one living player-1 unit at initialization")
    initial_profiles = {"leader": "Sergeant", "melee": None, "range": None}
    initial_picks = {
        "leader": _default_slot_picks_for_profile("leader", "Sergeant"),
        "melee": None,
        "range": None,
    }
    rebuilt_p1_units = _rebuild_player_units_for_slots(
        engine_instance, initial_profiles, initial_picks, old_p1_units
    )
    if not rebuilt_p1_units:
        raise ValueError("Endless Duty initialization requires at least one rebuilt player unit")

    # Endless Duty fixed spawn: leader starts at objective center (12,10).
    rebuilt_p1_units[0]["col"] = ED_START_LEADER_COL
    rebuilt_p1_units[0]["row"] = ED_START_LEADER_ROW
    _replace_units_for_player(gs, player=1, replacement_units=rebuilt_p1_units)

    slot_unit_ids = _extract_slot_unit_ids(rebuilt_p1_units)
    invested_total = _sum_units_value(rebuilt_p1_units)
    state = {
        "enabled": True,
        "wave_index": 1,
        "inter_wave_pending": False,
        "objective_lost_counter": 0,
        "last_objective_eval_turn": 0,
        "requisition_capital_total": int(invested_total),
        "requisition_invested_total": int(invested_total),
        "requisition_available": 0,
        "wave_enemy_spawned_value_total": 0,
        "wave_enemy_alive_value_last": 0,
        "slot_unit_ids": slot_unit_ids,
        "slot_profiles": initial_profiles,
        "slot_picks": initial_picks,
    }
    gs["endless_duty_state"] = state

    # Spawn wave 1 enemies immediately.
    spawn_result = spawn_next_wave_for_current_index(engine_instance)
    _start_initial_wave_turn_context(gs)
    _append_ed_log(gs, {"type": "endless_wave_start", "wave_index": 1, "details": spawn_result})
    return state


def handle_endless_duty_post_action(engine_instance: Any) -> Dict[str, Any]:
    """Update ED lifecycle after each player or AI action."""
    gs = require_key(engine_instance.__dict__, "game_state")
    if not is_endless_duty_mode(engine_instance):
        return {"processed": False}
    ed_state = require_key(gs, "endless_duty_state")
    if not isinstance(ed_state, dict):
        raise TypeError("game_state.endless_duty_state must be an object")

    # Defeat condition 1: all player units dead.
    if not _get_alive_units_for_player(gs, 1):
        gs["game_over"] = True
        gs["winner"] = 2
        _append_ed_log(gs, {"type": "endless_defeat", "reason": "all_player_units_destroyed"})
        return {"processed": True, "game_over": True, "reason": "all_player_units_destroyed"}

    # Defeat condition 2: objective control by tyranids for N consecutive round-ends.
    _update_objective_loss_counter(engine_instance)
    objective_rules = require_key(require_key(gs, "endless_duty_config"), "objective_rules")
    loss_threshold = require_key(objective_rules, "loss_counter_threshold")
    if require_key(ed_state, "objective_lost_counter") >= loss_threshold:
        gs["game_over"] = True
        gs["winner"] = 2
        _append_ed_log(gs, {"type": "endless_defeat", "reason": "objective_lost"})
        return {"processed": True, "game_over": True, "reason": "objective_lost"}

    if require_key(ed_state, "inter_wave_pending"):
        return {"processed": True, "inter_wave_pending": True}

    # Wave clear detection: no living tyranid units.
    alive_enemies = _get_alive_units_for_player(gs, 2)
    if alive_enemies:
        ed_state["wave_enemy_alive_value_last"] = _sum_units_value(alive_enemies)
        return {"processed": True, "inter_wave_pending": False}

    credits_delta = _compute_wave_credits(engine_instance)
    before = int(require_key(ed_state, "requisition_capital_total"))
    after = before + credits_delta
    ed_state["requisition_capital_total"] = after
    invested = int(require_key(ed_state, "requisition_invested_total"))
    ed_state["requisition_available"] = after - invested
    ed_state["inter_wave_pending"] = True

    _append_ed_log(
        gs,
        {
            "type": "endless_wave_cleared",
            "wave_index": require_key(ed_state, "wave_index"),
            "credits_delta": credits_delta,
            "credits_balance_before": before,
            "credits_balance_after": after,
            "credits_reason": "wave_clear_bundle",
        },
    )
    return {"processed": True, "inter_wave_pending": True, "credits_delta": credits_delta}


def commit_inter_wave_requisition(engine_instance: Any, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Apply inter-wave requisition decisions and spawn next wave.

    Expected action payload:
    {
      "action": "endless_duty_commit",
      "slot_profiles": {"leader":"Captain","melee":"Aggressor","range":"Hellblaster"},
      "slot_picks": {
        "leader": {"melee":"intercessor_sergeant_power_weapon","ranged":"bolt_rifle","secondary":"bolt_pistol","special":"none","package":None}
      }
    }
    """
    gs = require_key(engine_instance.__dict__, "game_state")
    if not is_endless_duty_mode(engine_instance):
        return False, {"error": "not_endless_duty_mode"}
    ed_state = require_key(gs, "endless_duty_state")
    if not require_key(ed_state, "inter_wave_pending"):
        return False, {"error": "inter_wave_not_pending"}

    requested_profiles = require_key(action, "slot_profiles")
    if not isinstance(requested_profiles, dict):
        raise TypeError("endless_duty_commit.slot_profiles must be an object")

    endless_cfg = require_key(gs, "endless_duty_config")
    unlock_rules = require_key(endless_cfg, "wave_unlock_rules")
    wave_index = int(require_key(ed_state, "wave_index"))

    current_profiles = require_key(ed_state, "slot_profiles")
    current_picks = ed_state.get("slot_picks")
    if current_picks is None:
        current_picks = {"leader": None, "melee": None, "range": None}
    if not isinstance(current_picks, dict):
        raise TypeError("game_state.endless_duty_state.slot_picks must be an object when provided")
    target_profiles = {
        "leader": requested_profiles.get("leader", current_profiles.get("leader")),
        "melee": requested_profiles.get("melee", current_profiles.get("melee")),
        "range": requested_profiles.get("range", current_profiles.get("range")),
    }
    requested_picks = action.get("slot_picks", {})
    if not isinstance(requested_picks, dict):
        raise TypeError("endless_duty_commit.slot_picks must be an object when provided")
    target_picks = _build_target_slot_picks(target_profiles, current_profiles, current_picks, requested_picks)
    _validate_requested_slot_configuration(target_profiles, target_picks, wave_index, unlock_rules)

    old_p1_alive = _get_alive_units_for_player(gs, 1)
    old_invested = int(require_key(ed_state, "requisition_invested_total"))
    old_capital = int(require_key(ed_state, "requisition_capital_total"))

    rebuilt_units = _rebuild_player_units_for_slots(engine_instance, target_profiles, target_picks, old_p1_alive)
    new_invested = _sum_units_value(rebuilt_units)
    purchase_delta = int(new_invested - old_invested)
    if old_capital - new_invested < 0:
        return False, {
            "error": "insufficient_requisition_capital",
            "capital_total": old_capital,
            "invested_before": old_invested,
            "invested_after": new_invested,
            "purchase_delta": purchase_delta,
        }

    _replace_units_for_player(gs, player=1, replacement_units=rebuilt_units)
    ed_state["slot_profiles"] = target_profiles
    ed_state["slot_picks"] = target_picks
    ed_state["slot_unit_ids"] = _extract_slot_unit_ids(rebuilt_units)
    ed_state["requisition_invested_total"] = int(new_invested)
    ed_state["requisition_available"] = int(old_capital - new_invested)
    ed_state["inter_wave_pending"] = False
    ed_state["wave_index"] = wave_index + 1

    _append_ed_log(
        gs,
        {
            "type": "endless_purchase",
            "wave_index": wave_index,
            "purchase_type": "slot_reconfiguration",
            "purchase_item_id": "slot_profiles",
            "purchase_item_from": copy.deepcopy(current_profiles),
            "purchase_item_to": copy.deepcopy(target_profiles),
            "purchase_picks_from": copy.deepcopy(current_picks),
            "purchase_picks_to": copy.deepcopy(target_picks),
            "purchase_cost": purchase_delta,
            "purchase_delta": purchase_delta,
            "credits_balance_before": old_capital - old_invested,
            "credits_balance_after": old_capital - new_invested,
        },
    )

    # Start next wave.
    spawn_result = spawn_next_wave_for_current_index(engine_instance)
    _start_next_wave_turn_context(gs)
    _append_ed_log(
        gs,
        {
            "type": "endless_wave_start",
            "wave_index": require_key(ed_state, "wave_index"),
            "details": spawn_result,
        },
    )
    return True, {
        "action": "endless_duty_commit",
        "wave_index": require_key(ed_state, "wave_index"),
        "invested_before": old_invested,
        "invested_after": new_invested,
        "purchase_delta": purchase_delta,
        "capital_total": old_capital,
        "available_after": require_key(ed_state, "requisition_available"),
        "spawned_enemies": spawn_result,
    }


def load_wave_forced_spawns_config(project_root: Path) -> Dict[str, Any]:
    """
    Charge config/endless_duty/wave_forced_spawns.json (optionnel).
    Si le fichier est absent, retourne des vagues vides.
    """
    path = project_root / "config" / "endless_duty" / "wave_forced_spawns.json"
    if not path.exists():
        return {"waves": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError("wave_forced_spawns.json root must be an object")
    waves = require_key(data, "waves")
    if not isinstance(waves, dict):
        raise TypeError("wave_forced_spawns.waves must be an object")
    return {"waves": waves}


def _forced_wave_entries_for_index(wave_forced_cfg: Dict[str, Any], wave_index: int) -> List[Dict[str, Any]]:
    waves = require_key(wave_forced_cfg, "waves")
    key = str(wave_index)
    if key not in waves:
        return []
    raw = require_key(waves, key)
    if not isinstance(raw, list):
        raise TypeError(f"wave_forced_spawns.waves[{key}] must be a list")
    return list(raw)


def _validate_forced_spawn_tyranid(registry: Any, unit_type: str) -> None:
    if unit_type not in registry.units:
        raise KeyError(f"Unknown unit_type for forced spawn: {unit_type}")
    data = registry.get_unit_data(unit_type)
    faction = str(require_key(data, "faction")).lower()
    if faction != "tyranid":
        raise ValueError(
            f"endless_duty forced spawn must be tyranid faction, got {unit_type} (faction={faction})"
        )


def _expand_forced_wave_unit_types(engine_instance: Any, entries: List[Dict[str, Any]]) -> List[str]:
    """Construit la liste ordonnée des types ennemis forcés (répétitions incluses)."""
    registry = require_key(engine_instance.__dict__, "unit_registry")
    out: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("each wave_forced_spawns entry must be an object")
        qty = int(require_key(entry, "quantity"))
        if qty <= 0:
            raise ValueError("wave_forced_spawns quantity must be a positive integer")
        if "one_of" in entry:
            if "unit_type" in entry:
                raise ValueError("wave_forced_spawns entry cannot combine unit_type and one_of")
            candidates = require_key(entry, "one_of")
            if not isinstance(candidates, list) or len(candidates) < 1:
                raise ValueError("one_of must be a non-empty list of unit_type strings")
            for _ in range(qty):
                picked = random.choice(candidates)
                if not isinstance(picked, str):
                    raise TypeError("one_of entries must be strings")
                _validate_forced_spawn_tyranid(registry, picked)
                out.append(picked)
        else:
            unit_type = require_key(entry, "unit_type")
            if not isinstance(unit_type, str):
                raise TypeError("unit_type must be a string")
            for _ in range(qty):
                _validate_forced_spawn_tyranid(registry, unit_type)
                out.append(unit_type)
    return out


def _sum_unit_types_value(registry: Any, unit_types: List[str]) -> int:
    total = 0
    for ut in unit_types:
        total += int(require_key(registry.get_unit_data(ut), "VALUE"))
    return total


def spawn_next_wave_for_current_index(engine_instance: Any) -> Dict[str, Any]:
    """Spawn tyranid wave for current ED wave_index."""
    gs = require_key(engine_instance.__dict__, "game_state")
    ed_state = require_key(gs, "endless_duty_state")
    endless_cfg = require_key(gs, "endless_duty_config")
    wave_index = int(require_key(ed_state, "wave_index"))
    registry = require_key(engine_instance.__dict__, "unit_registry")

    forced_cfg = load_wave_forced_spawns_config(PROJECT_ROOT)
    forced_entries = _forced_wave_entries_for_index(forced_cfg, wave_index)
    forced_types = _expand_forced_wave_unit_types(engine_instance, forced_entries) if forced_entries else []
    forced_value = _sum_unit_types_value(registry, forced_types) if forced_types else 0

    budget = _compute_wave_budget(endless_cfg, wave_index)
    available_enemy_types = _get_unlocked_enemy_unit_types(engine_instance, endless_cfg, wave_index)
    filler_budget = budget - forced_value
    if filler_budget < 0:
        raise ValueError(
            f"Endless Duty wave {wave_index}: forced spawns VALUE total {forced_value} "
            f"exceeds wave budget {budget}"
        )
    filler_types = _compose_enemy_wave(engine_instance, filler_budget, available_enemy_types, endless_cfg)
    selected_enemy_types = forced_types + filler_types
    placed_units = _build_and_place_enemy_units(engine_instance, selected_enemy_types, endless_cfg)

    _replace_units_for_player(gs, player=2, replacement_units=placed_units)
    spawned_total_value = _sum_units_value(placed_units)
    ed_state["wave_enemy_spawned_value_total"] = int(spawned_total_value)
    ed_state["wave_enemy_alive_value_last"] = int(spawned_total_value)

    return {
        "wave_index": wave_index,
        "budget_target": budget,
        "forced_spawn_unit_types": list(forced_types),
        "forced_spawn_value": int(forced_value),
        "filler_budget": int(filler_budget),
        "spawned_count": len(placed_units),
        "spawned_total_value": int(spawned_total_value),
        "spawned_unit_types": [require_key(u, "unitType") for u in placed_units],
    }


def _compute_wave_budget(endless_cfg: Dict[str, Any], wave_index: int) -> int:
    budgets = require_key(endless_cfg, "budget_by_wave")
    if not isinstance(budgets, dict):
        raise TypeError("endless_duty.budget_by_wave must be an object")
    budget_value: int
    wave_key = str(wave_index)
    if wave_key in budgets:
        budget_value = int(require_key(budgets, wave_key))
    else:
        growth_cfg = require_key(endless_cfg, "budget_growth_after_wave_20")
        enabled = require_key(growth_cfg, "enabled")
        if not isinstance(enabled, bool):
            raise TypeError("budget_growth_after_wave_20.enabled must be boolean")
        if not enabled:
            raise KeyError(f"Missing budget_by_wave entry for wave {wave_index} and growth disabled")
        start_wave = int(require_key(growth_cfg, "start_wave"))
        delta_per_wave = int(require_key(growth_cfg, "delta_per_wave"))
        base_wave_key = str(start_wave - 1)
        if base_wave_key not in budgets:
            raise KeyError(
                f"budget_growth_after_wave_20 requires budget_by_wave[{base_wave_key}] to compute wave {wave_index}"
            )
        base_budget = int(require_key(budgets, base_wave_key))
        budget_value = base_budget + (wave_index - (start_wave - 1)) * delta_per_wave

    spike_cfg = require_key(endless_cfg, "wave_spike")
    every_n = int(require_key(spike_cfg, "every_n_waves"))
    multiplier = float(require_key(spike_cfg, "budget_multiplier"))
    if every_n <= 0:
        raise ValueError("wave_spike.every_n_waves must be > 0")
    if wave_index % every_n == 0:
        budget_value = int(round(budget_value * multiplier))
    return int(budget_value)


def _get_unlocked_enemy_unit_types(engine_instance: Any, endless_cfg: Dict[str, Any], wave_index: int) -> List[str]:
    registry = require_key(engine_instance.__dict__, "unit_registry")
    if registry is None:
        raise ValueError("engine.unit_registry is required for Endless Duty enemy composition")

    tyranid_types = []
    for unit_type, data in registry.units.items():
        faction = str(require_key(data, "faction")).lower()
        if faction == "tyranid":
            tyranid_types.append(unit_type)
    if not tyranid_types:
        raise ValueError("No tyranid units found in unit registry")

    unlock_cfg = require_key(endless_cfg, "spawn_unlock_rules")
    max_val = None
    if wave_index <= 4:
        max_val = int(require_key(unlock_cfg, "waves_1_4_max_enemy_value"))
    elif wave_index <= 9:
        max_val = int(require_key(unlock_cfg, "waves_5_9_max_enemy_value"))
    elif wave_index >= 10:
        allow_high = require_key(unlock_cfg, "wave_10_plus_allow_value_gte_90")
        if not isinstance(allow_high, bool):
            raise TypeError("spawn_unlock_rules.wave_10_plus_allow_value_gte_90 must be boolean")
        max_val = None if allow_high else int(require_key(unlock_cfg, "waves_5_9_max_enemy_value"))

    eligible = []
    for unit_type in tyranid_types:
        value = int(require_key(registry.get_unit_data(unit_type), "VALUE"))
        if max_val is not None and value > max_val:
            continue
        eligible.append(unit_type)
    if not eligible:
        raise ValueError(f"No eligible tyranid units for wave {wave_index} with current unlock rules")
    return eligible


def _compose_enemy_wave(
    engine_instance: Any,
    budget: int,
    available_enemy_types: List[str],
    endless_cfg: Dict[str, Any],
) -> List[str]:
    """Compose a wave using VALUE budget with optional soft cap."""
    registry = require_key(engine_instance.__dict__, "unit_registry")
    budget_mode = require_key(endless_cfg, "budget_mode")
    if budget_mode not in {"strict", "soft_cap"}:
        raise ValueError("endless_duty.budget_mode must be 'strict' or 'soft_cap'")
    soft_cap_pct = float(require_key(endless_cfg, "budget_soft_cap_pct"))
    max_total = budget
    if budget_mode == "soft_cap":
        max_total = int(budget * (1.0 + soft_cap_pct))

    values_by_type = {
        unit_type: int(require_key(registry.get_unit_data(unit_type), "VALUE"))
        for unit_type in available_enemy_types
    }
    min_value = min(values_by_type.values())
    picked: List[str] = []
    current_total = 0

    safety = 0
    while True:
        safety += 1
        if safety > 1000:
            raise RuntimeError("Enemy wave composition exceeded safety loop limit")
        remaining = max_total - current_total
        if remaining < min_value:
            break
        candidates = [u for u, v in values_by_type.items() if v <= remaining]
        if not candidates:
            break
        choice = random.choice(candidates)
        picked.append(choice)
        current_total += values_by_type[choice]
        if current_total >= budget and budget_mode == "strict":
            break
    if not picked:
        # Ensure at least one enemy when budget is lower than all values.
        cheapest = min(values_by_type.items(), key=lambda kv: kv[1])[0]
        picked = [cheapest]
    return picked


def _build_and_place_enemy_units(
    engine_instance: Any,
    enemy_unit_types: List[str],
    endless_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    gs = require_key(engine_instance.__dict__, "game_state")
    board_cols = int(require_key(gs, "board_cols"))
    board_rows = int(require_key(gs, "board_rows"))
    spawn_cfg = require_key(endless_cfg, "enemy_spawn_rules")
    min_distance_objective = int(require_key(spawn_cfg, "min_distance_from_objective"))
    min_distance_between = int(require_key(spawn_cfg, "min_distance_between_spawns"))
    max_retries = int(require_key(spawn_cfg, "max_retries_per_unit"))
    objective_hexes = _collect_objective_hexes(gs)
    occupied = _collect_occupied_hexes(gs)
    wall_hexes = set(tuple(h) for h in require_key(gs, "wall_hexes"))

    next_id = _next_unit_id(gs)
    built_units: List[Dict[str, Any]] = []
    spawned_positions: List[Tuple[int, int]] = []
    candidate_edges = require_key(spawn_cfg, "candidate_edges")
    if not isinstance(candidate_edges, list) or not candidate_edges:
        raise ValueError("endless_duty.enemy_spawn_rules.candidate_edges must be a non-empty list")

    for unit_type in enemy_unit_types:
        placed = False
        for _ in range(max_retries):
            col, row = _random_edge_hex(board_cols, board_rows, candidate_edges)
            if not _is_valid_board_hex(col, row, board_cols, board_rows):
                continue
            if (col, row) in wall_hexes or (col, row) in occupied:
                continue
            if (col, row) in objective_hexes:
                continue
            if _min_hex_distance((col, row), objective_hexes) < min_distance_objective:
                continue
            if spawned_positions and _min_hex_distance((col, row), spawned_positions) < min_distance_between:
                continue

            unit = _build_unit_from_registry(engine_instance, unit_type, player=2, unit_id=next_id, col=col, row=row)
            built_units.append(unit)
            next_id += 1
            occupied.add((col, row))
            spawned_positions.append((col, row))
            placed = True
            break
        if not placed:
            raise RuntimeError(f"Failed to place enemy unit '{unit_type}' after {max_retries} retries")
    return built_units


def _build_unit_from_registry(
    engine_instance: Any,
    unit_type: str,
    player: int,
    unit_id: int,
    col: int,
    row: int,
) -> Dict[str, Any]:
    unit_data = engine_instance.unit_registry.get_unit_data(unit_type)
    rng_weapons = copy.deepcopy(require_key(unit_data, "RNG_WEAPONS"))
    cc_weapons = copy.deepcopy(require_key(unit_data, "CC_WEAPONS"))
    selected_rng_weapon_index = 0 if rng_weapons else None
    selected_cc_weapon_index = 0 if cc_weapons else None
    shoot_left = 0
    if rng_weapons and selected_rng_weapon_index is not None:
        shoot_left = resolve_dice_value(require_key(rng_weapons[selected_rng_weapon_index], "NB"), "endless_spawn_shoot_left")
    attack_left = 0
    if cc_weapons and selected_cc_weapon_index is not None:
        attack_left = resolve_dice_value(require_key(cc_weapons[selected_cc_weapon_index], "NB"), "endless_spawn_attack_left")
    hp_max = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "HP_MAX")
    move = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "MOVE")
    toughness = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "T")
    armor_save = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "ARMOR_SAVE")
    invul_save = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "INVUL_SAVE")
    leadership = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "LD")
    objective_control = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "OC")
    value = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "VALUE")
    icon_scale = _resolve_numeric_unit_field(engine_instance, unit_type, unit_data, "ICON_SCALE", allow_float=True)
    illustration_ratio = _resolve_numeric_unit_field(
        engine_instance,
        unit_type,
        unit_data,
        "ILLUSTRATION_RATIO",
        allow_float=True,
    )

    return {
        "id": str(unit_id),
        "player": int(player),
        "unitType": unit_type,
        "DISPLAY_NAME": require_key(unit_data, "DISPLAY_NAME"),
        "col": int(col),
        "row": int(row),
        "HP_CUR": hp_max,
        "HP_MAX": hp_max,
        "MOVE": move,
        "T": toughness,
        "ARMOR_SAVE": armor_save,
        "INVUL_SAVE": invul_save,
        "RNG_WEAPONS": rng_weapons,
        "CC_WEAPONS": cc_weapons,
        "selectedRngWeaponIndex": selected_rng_weapon_index,
        "selectedCcWeaponIndex": selected_cc_weapon_index,
        "LD": leadership,
        "OC": objective_control,
        "VALUE": value,
        "ICON": require_key(unit_data, "ICON"),
        "ICON_SCALE": icon_scale,
        "ILLUSTRATION_RATIO": illustration_ratio,
        "UNIT_RULES": copy.deepcopy(require_key(unit_data, "UNIT_RULES")),
        "UNIT_KEYWORDS": copy.deepcopy(require_key(unit_data, "UNIT_KEYWORDS")),
        "SHOOT_LEFT": shoot_left,
        "ATTACK_LEFT": attack_left,
    }


def _resolve_numeric_unit_field(
    engine_instance: Any,
    unit_type: str,
    unit_data: Dict[str, Any],
    field_name: str,
    allow_float: bool = False,
) -> int | float:
    """
    Resolve numeric unit field from registry data.

    Supports direct numeric values and static references in the form
    '<OtherUnitType>.<FIELD>'.
    """
    raw_value = require_key(unit_data, field_name)
    if isinstance(raw_value, (int, float)):
        return float(raw_value) if allow_float else int(raw_value)
    if not isinstance(raw_value, str):
        raise TypeError(f"{unit_type}.{field_name} must be numeric or static reference string, got {type(raw_value).__name__}")
    if "." not in raw_value:
        raise TypeError(
            f"{unit_type}.{field_name} contains non-numeric string '{raw_value}' that is not a static reference"
        )
    ref_unit_type, ref_field = raw_value.split(".", 1)
    ref_unit_data = engine_instance.unit_registry.get_unit_data(ref_unit_type)
    ref_value = require_key(ref_unit_data, ref_field)
    if not isinstance(ref_value, (int, float)):
        raise TypeError(
            f"Resolved reference {raw_value} for {unit_type}.{field_name} is not numeric (got {type(ref_value).__name__})"
        )
    return float(ref_value) if allow_float else int(ref_value)


def _replace_units_for_player(gs: Dict[str, Any], player: int, replacement_units: List[Dict[str, Any]]) -> None:
    kept = [u for u in require_key(gs, "units") if int(require_key(u, "player")) != int(player)]
    gs["units"] = kept + replacement_units
    gs["unit_by_id"] = {str(require_key(u, "id")): u for u in gs["units"]}
    build_units_cache(gs)
    rebuild_choice_timing_index(gs)
    units_cache = require_key(gs, "units_cache")
    gs["units_cache_prev"] = {
        uid: {
            "col": require_key(entry, "col"),
            "row": require_key(entry, "row"),
            "HP_CUR": require_key(entry, "HP_CUR"),
            "player": require_key(entry, "player"),
        }
        for uid, entry in units_cache.items()
    }


def _compute_wave_credits(engine_instance: Any) -> int:
    gs = require_key(engine_instance.__dict__, "game_state")
    ed_state = require_key(gs, "endless_duty_state")
    cfg = require_key(gs, "endless_duty_config")
    eco = require_key(cfg, "economy")
    alpha = float(require_key(eco, "credits_alpha_on_kill_value"))
    wave_clear_bonus = int(require_key(eco, "wave_clear_bonus"))
    no_consumable_bonus = int(require_key(eco, "no_consumable_bonus"))
    objective_hold_bonus = int(require_key(eco, "objective_hold_bonus"))
    spawned_total = int(require_key(ed_state, "wave_enemy_spawned_value_total"))
    alive_enemies = _get_alive_units_for_player(gs, 2)
    alive_value = _sum_units_value(alive_enemies)
    killed_value = max(0, spawned_total - alive_value)

    objective_control = engine_instance.state_manager.calculate_objective_control(gs)
    objective_state = _objective_state_from_control_data(objective_control)
    objective_bonus = objective_hold_bonus if objective_state == "SM_CONTROL" else 0
    # V1: no consumables pipeline yet in engine => treat as unused for scoring.
    credits = int((alpha * killed_value) // 1) + wave_clear_bonus + no_consumable_bonus + objective_bonus
    return credits


def _update_objective_loss_counter(engine_instance: Any) -> None:
    gs = require_key(engine_instance.__dict__, "game_state")
    ed_state = require_key(gs, "endless_duty_state")
    current_turn = int(require_key(gs, "turn"))
    if int(require_key(gs, "current_player")) != 1:
        return
    if require_key(gs, "phase") != "command":
        return
    last_eval_turn = int(require_key(ed_state, "last_objective_eval_turn"))
    if current_turn <= last_eval_turn:
        return

    control_data = engine_instance.state_manager.calculate_objective_control(gs)
    objective_state = _objective_state_from_control_data(control_data)
    if objective_state == "TYR_CONTROL":
        ed_state["objective_lost_counter"] = int(require_key(ed_state, "objective_lost_counter")) + 1
    else:
        ed_state["objective_lost_counter"] = 0
    ed_state["last_objective_eval_turn"] = current_turn


def _objective_state_from_control_data(control_data: Dict[int, Dict[str, Any]]) -> str:
    if not control_data:
        return "NEUTRAL"
    first_obj = next(iter(control_data.values()))
    controller = first_obj.get("controller")
    if controller == 1:
        return "SM_CONTROL"
    if controller == 2:
        return "TYR_CONTROL"
    return "NEUTRAL"


def _validate_requested_slot_configuration(
    target_profiles: Dict[str, Any],
    target_picks: Dict[str, Any],
    wave_index: int,
    unlock_rules: Dict[str, Any],
) -> None:
    if target_profiles.get("leader") is None:
        raise ValueError("slot_profiles.leader is required")
    leader_unlock = int(require_key(unlock_rules, "leader"))
    melee_unlock = int(require_key(unlock_rules, "melee"))
    range_unlock = int(require_key(unlock_rules, "range"))
    if wave_index < leader_unlock:
        raise ValueError(f"Leader slot is locked until wave {leader_unlock}")
    if target_profiles.get("melee") is not None and wave_index < melee_unlock:
        raise ValueError(f"Melee slot is locked until wave {melee_unlock}")
    if target_profiles.get("range") is not None and wave_index < range_unlock:
        raise ValueError(f"Range slot is locked until wave {range_unlock}")

    allowed_profiles_by_slot = _load_allowed_profiles_by_slot()
    for slot_name in ("leader", "melee", "range"):
        profile = target_profiles.get(slot_name)
        slot_picks = target_picks.get(slot_name)
        if profile is None:
            if slot_picks is not None:
                raise ValueError(f"slot_picks.{slot_name} must be null when slot_profiles.{slot_name} is null")
            continue
        if not isinstance(profile, str) or not profile.strip():
            raise ValueError(f"slot_profiles.{slot_name} must be a non-empty string when provided")
        allowed_profiles = require_key(allowed_profiles_by_slot, slot_name)
        if profile not in allowed_profiles:
            raise ValueError(
                f"Unsupported {slot_name} profile '{profile}'. Allowed: {sorted(allowed_profiles)}"
            )
        _validate_slot_picks_for_profile(slot_name, profile, slot_picks)


def _rebuild_player_units_for_slots(
    engine_instance: Any,
    target_profiles: Dict[str, Any],
    target_picks: Dict[str, Any],
    old_alive_units: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    old_by_slot = _map_old_units_by_slot(target_profiles, old_alive_units)
    ordered_slots = [("leader", target_profiles.get("leader")), ("melee", target_profiles.get("melee")), ("range", target_profiles.get("range"))]
    next_id = _next_unit_id(require_key(engine_instance.__dict__, "game_state"))
    new_units: List[Dict[str, Any]] = []
    for slot_name, profile_name in ordered_slots:
        if profile_name is None:
            continue
        unit_type = _slot_profile_to_unit_type(slot_name, str(profile_name))
        old_unit = old_by_slot.get(slot_name)
        if old_unit is not None:
            col = int(require_key(old_unit, "col"))
            row = int(require_key(old_unit, "row"))
            preserved_hp = int(require_key(old_unit, "HP_CUR"))
        else:
            col, row = _fallback_spawn_from_objective(require_key(engine_instance.__dict__, "game_state"))
            preserved_hp = None
        unit = _build_unit_from_registry(engine_instance, unit_type, player=1, unit_id=next_id, col=col, row=row)
        slot_picks = target_picks.get(slot_name)
        _apply_slot_picks_to_unit(unit, slot_name, str(profile_name), slot_picks)
        next_id += 1
        if preserved_hp is not None:
            unit["HP_CUR"] = max(1, min(int(require_key(unit, "HP_MAX")), preserved_hp))
        new_units.append(unit)
    if not new_units:
        raise ValueError("Requisition commit must produce at least one player unit")
    return new_units


def _map_old_units_by_slot(target_profiles: Dict[str, Any], old_alive_units: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    sorted_units = sorted(old_alive_units, key=lambda u: int(require_key(u, "id")))
    mapped: Dict[str, Dict[str, Any]] = {}
    if sorted_units:
        mapped["leader"] = sorted_units[0]
    if len(sorted_units) > 1:
        mapped["melee"] = sorted_units[1]
    if len(sorted_units) > 2:
        mapped["range"] = sorted_units[2]
    # Keep only slots requested in this commit.
    return {k: v for k, v in mapped.items() if target_profiles.get(k) is not None}


def _extract_slot_unit_ids(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    sorted_units = sorted(units, key=lambda u: int(require_key(u, "id")))
    slot_ids = {"leader": None, "melee": None, "range": None}
    if sorted_units:
        slot_ids["leader"] = str(require_key(sorted_units[0], "id"))
    if len(sorted_units) > 1:
        slot_ids["melee"] = str(require_key(sorted_units[1], "id"))
    if len(sorted_units) > 2:
        slot_ids["range"] = str(require_key(sorted_units[2], "id"))
    return slot_ids


def _slot_profile_to_unit_type(slot_name: str, profile_name: str) -> str:
    if slot_name == "leader":
        return f"Leader{profile_name}"
    if slot_name == "melee":
        return f"Melee{profile_name}"
    if slot_name == "range":
        return f"Range{profile_name}"
    raise ValueError(f"Unknown Endless Duty slot: {slot_name}")


def _start_next_wave_turn_context(gs: Dict[str, Any]) -> None:
    gs["turn"] = int(require_key(gs, "turn")) + 1
    gs["current_player"] = 1
    gs["phase"] = "command"
    gs["turn_limit_reached"] = False
    gs["game_over"] = False
    gs["winner"] = None
    command_handlers.command_phase_start(gs)
    movement_handlers.movement_phase_start(gs)


def _start_initial_wave_turn_context(gs: Dict[str, Any]) -> None:
    """Initialize run at P1 command phase (no deployment / no auto-move)."""
    gs["current_player"] = 1
    gs["phase"] = "command"
    gs["turn_limit_reached"] = False
    gs["game_over"] = False
    gs["winner"] = None
    if "deployment_state" in gs and isinstance(gs["deployment_state"], dict):
        gs["deployment_state"]["deployment_complete"] = True
    command_result = command_handlers.command_phase_start(gs)
    command_pool = gs.get("command_activation_pool", [])
    has_command_actions = isinstance(command_pool, list) and len(command_pool) > 0
    # If command phase has no actionable content, start move phase immediately.
    if (
        not has_command_actions
        and isinstance(command_result, dict)
        and command_result.get("phase_transition") is True
        and command_result.get("next_phase") == "move"
    ):
        movement_handlers.movement_phase_start(gs)


def _disable_turn_limit_for_endless_duty(engine_instance: Any, gs: Dict[str, Any]) -> None:
    """Disable training turn cap for Endless Duty runtime."""
    engine_training_config = require_key(engine_instance.__dict__, "training_config")
    if not isinstance(engine_training_config, dict):
        raise TypeError("engine.training_config must be an object for Endless Duty turn-limit override")
    state_config = require_key(gs, "config")
    if not isinstance(state_config, dict):
        raise TypeError("game_state.config must be an object for Endless Duty turn-limit override")

    # Endless Duty is wave-based and must not terminate by max turns.
    engine_training_config["max_turns_per_episode"] = None
    state_training_config = state_config.get("training_config")
    if state_training_config is not None:
        if not isinstance(state_training_config, dict):
            raise TypeError(
                "game_state.config.training_config must be an object when provided for Endless Duty turn-limit override"
            )
        state_training_config["max_turns_per_episode"] = None
    gs["turn_limit_reached"] = False


def _get_alive_units_for_player(gs: Dict[str, Any], player: int) -> List[Dict[str, Any]]:
    units_cache = require_key(gs, "units_cache")
    alive_ids = {
        str(uid)
        for uid, entry in units_cache.items()
        if int(require_key(entry, "player")) == int(player) and int(require_key(entry, "HP_CUR")) > 0
    }
    return [u for u in require_key(gs, "units") if str(require_key(u, "id")) in alive_ids]


def _sum_units_value(units: List[Dict[str, Any]]) -> int:
    return int(sum(int(require_key(u, "VALUE")) for u in units))


def _collect_objective_hexes(gs: Dict[str, Any]) -> set[Tuple[int, int]]:
    objective_hexes: set[Tuple[int, int]] = set()
    for objective in require_key(gs, "objectives"):
        for raw_hex in require_key(objective, "hexes"):
            if not isinstance(raw_hex, (list, tuple)) or len(raw_hex) != 2:
                raise ValueError(f"Objective hex must be [col,row], got {raw_hex!r}")
            objective_hexes.add((int(raw_hex[0]), int(raw_hex[1])))
    return objective_hexes


def _collect_occupied_hexes(gs: Dict[str, Any]) -> set[Tuple[int, int]]:
    occupied = set()
    for unit in require_key(gs, "units"):
        col = int(require_key(unit, "col"))
        row = int(require_key(unit, "row"))
        if col >= 0 and row >= 0:
            occupied.add((col, row))
    return occupied


def _next_unit_id(gs: Dict[str, Any]) -> int:
    units = require_key(gs, "units")
    if not units:
        return 1
    return max(int(require_key(u, "id")) for u in units) + 1


def _min_hex_distance(origin: Tuple[int, int], targets: set[Tuple[int, int]] | List[Tuple[int, int]]) -> int:
    if not targets:
        return 9999
    col, row = origin
    return min(calculate_hex_distance(col, row, t_col, t_row) for t_col, t_row in targets)


def _random_edge_hex(cols: int, rows: int, candidate_edges: List[str]) -> Tuple[int, int]:
    edge = random.choice(candidate_edges)
    if edge == "north":
        return random.randint(0, cols - 1), 0
    if edge == "south":
        col = random.randint(0, cols - 1)
        row = rows - 1
        if row >= 0 and (col % 2 == 1):
            row = max(0, row - 1)
        return col, row
    if edge == "east":
        return cols - 1, random.randint(0, rows - 1)
    if edge == "west":
        return 0, random.randint(0, rows - 1)
    raise ValueError(f"Unsupported candidate edge '{edge}'")


def _is_valid_board_hex(col: int, row: int, cols: int, rows: int) -> bool:
    if col < 0 or col >= cols or row < 0 or row >= rows:
        return False
    if row == rows - 1 and (col % 2 == 1):
        return False
    return True


def _load_allowed_profiles_by_slot() -> Dict[str, List[str]]:
    cfg_dir = PROJECT_ROOT / "config" / "endless_duty"
    evolution_files = {
        "leader": cfg_dir / "leader_evolution.json",
        "melee": cfg_dir / "melee_evolution.json",
        "range": cfg_dir / "range_evolution.json",
    }
    allowed: Dict[str, List[str]] = {}
    for slot_name, file_path in evolution_files.items():
        if not file_path.exists():
            raise FileNotFoundError(f"Missing evolution config for slot '{slot_name}': {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        catalog = require_key(payload, "catalog")
        if not isinstance(catalog, dict):
            raise TypeError(f"{file_path} field 'catalog' must be an object")
        allowed[slot_name] = list(catalog.keys())
    return allowed


def _evolution_file_path_for_slot(slot_name: str) -> Path:
    cfg_dir = PROJECT_ROOT / "config" / "endless_duty"
    mapping = {
        "leader": cfg_dir / "leader_evolution.json",
        "melee": cfg_dir / "melee_evolution.json",
        "range": cfg_dir / "range_evolution.json",
    }
    file_path = require_key(mapping, slot_name)
    if not file_path.exists():
        raise FileNotFoundError(f"Missing evolution config for slot '{slot_name}': {file_path}")
    return file_path


def _load_evolution_payload_for_slot(slot_name: str) -> Dict[str, Any]:
    file_path = _evolution_file_path_for_slot(slot_name)
    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise TypeError(f"{file_path} must contain a JSON object")
    return payload


def _default_slot_picks_for_profile(slot_name: str, profile_name: str) -> Dict[str, Any]:
    payload = _load_evolution_payload_for_slot(slot_name)
    loadouts = require_key(payload, "loadouts")
    if not isinstance(loadouts, list):
        raise TypeError(f"Slot '{slot_name}' evolution field 'loadouts' must be a list")
    starter_loadout_id = payload.get("starter_loadout_id")
    selected_loadout: Dict[str, Any] | None = None
    for loadout in loadouts:
        if not isinstance(loadout, dict):
            continue
        if str(loadout.get("profile")) != profile_name:
            continue
        if starter_loadout_id is not None and str(loadout.get("id")) == str(starter_loadout_id):
            selected_loadout = loadout
            break
        if selected_loadout is None:
            selected_loadout = loadout
    if selected_loadout is None:
        raise ValueError(f"No loadout found for slot '{slot_name}' profile '{profile_name}'")
    raw_picks = require_key(selected_loadout, "picks")
    if not isinstance(raw_picks, dict):
        raise TypeError(f"Starter loadout picks for slot '{slot_name}' profile '{profile_name}' must be an object")
    normalized = {
        "package": raw_picks.get("package"),
        "melee": raw_picks.get("melee"),
        "ranged": raw_picks.get("ranged"),
        "secondary": raw_picks.get("secondary"),
        "special": raw_picks.get("special", raw_picks.get("equipment")),
    }
    return {
        key: (None if value is None or str(value) == "none" else str(value))
        for key, value in normalized.items()
    }


def _build_target_slot_picks(
    target_profiles: Dict[str, Any],
    current_profiles: Dict[str, Any],
    current_picks: Dict[str, Any],
    requested_picks: Dict[str, Any],
) -> Dict[str, Any]:
    target: Dict[str, Any] = {}
    for slot_name in ("leader", "melee", "range"):
        profile = target_profiles.get(slot_name)
        if profile is None:
            target[slot_name] = None
            continue
        if slot_name in requested_picks:
            target[slot_name] = requested_picks.get(slot_name)
            continue
        current_profile = current_profiles.get(slot_name)
        if current_profile == profile and current_picks.get(slot_name) is not None:
            target[slot_name] = current_picks.get(slot_name)
            continue
        target[slot_name] = _default_slot_picks_for_profile(slot_name, str(profile))
    return target


def _validate_slot_picks_for_profile(slot_name: str, profile_name: str, slot_picks: Any) -> None:
    if not isinstance(slot_picks, dict):
        raise ValueError(f"slot_picks.{slot_name} must be an object")
    _resolve_slot_pick_override(slot_name, profile_name, slot_picks)


def _resolve_slot_pick_override(
    slot_name: str,
    profile_name: str,
    slot_picks: Dict[str, Any],
) -> Dict[str, Any]:
    payload = _load_evolution_payload_for_slot(slot_name)
    catalog = require_key(payload, "catalog")
    profile_catalog = require_key(catalog, profile_name)
    base_value = require_key(profile_catalog, "base")
    if not isinstance(base_value, (int, float)):
        raise TypeError(f"Catalog profile '{profile_name}' in slot '{slot_name}' must define numeric field 'base'")
    rows = require_key(profile_catalog, "rows")
    packages = require_key(profile_catalog, "packages")
    if not isinstance(rows, list) or not isinstance(packages, list):
        raise TypeError(f"Catalog profile '{profile_name}' must define list fields rows/packages")

    rules = payload.get("rules", {})
    if not isinstance(rules, dict):
        raise TypeError(f"Slot '{slot_name}' evolution field 'rules' must be an object when provided")
    package_blocks_extras = bool(rules.get("package_blocks_extras", False))

    from engine.weapons import get_weapons

    ranged_codes: List[str] = []
    melee_codes: List[str] = []
    total_cost = float(base_value)
    normalized_picks: Dict[str, str | None] = {
        "package": None,
        "melee": None,
        "ranged": None,
        "secondary": None,
        "special": None,
    }

    for key in normalized_picks.keys():
        raw = slot_picks.get(key)
        if raw is None:
            normalized_picks[key] = None
        else:
            val = str(raw)
            normalized_picks[key] = None if val == "none" else val

    def _append_row_pick(slot_key: str, pick_id: str) -> None:
        nonlocal total_cost
        row_match = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("slot")) == slot_key and str(row.get("pick")) == pick_id:
                row_match = row
                break
        if row_match is None:
            raise KeyError(
                f"slot_picks.{slot_name}.{slot_key}='{pick_id}' is unknown for profile '{profile_name}'"
            )
        if row_match.get("implemented") is False:
            raise ValueError(
                f"slot_picks.{slot_name}.{slot_key}='{pick_id}' is not implemented for profile '{profile_name}'"
            )
        row_cost = require_key(row_match, "cost")
        if not isinstance(row_cost, (int, float)):
            raise TypeError(
                f"Row pick '{pick_id}' in profile '{profile_name}' must define numeric field 'cost'"
            )
        total_cost += float(row_cost)
        includes = row_match.get("includes")
        target_list = ranged_codes if slot_key in ("ranged", "secondary") else melee_codes
        if includes is not None:
            if not isinstance(includes, list):
                raise TypeError(f"Row '{pick_id}' in profile '{profile_name}' has non-list includes")
            for weapon_code in includes:
                target_list.append(str(weapon_code))
        else:
            target_list.append(pick_id)

    package_id = normalized_picks["package"]
    if package_id is not None:
        package_match = None
        for package in packages:
            if not isinstance(package, dict):
                continue
            if str(package.get("id")) == package_id:
                package_match = package
                break
        if package_match is None:
            raise KeyError(f"slot_picks.{slot_name}.package='{package_id}' is unknown for profile '{profile_name}'")
        if package_match.get("implemented") is False:
            raise ValueError(
                f"slot_picks.{slot_name}.package='{package_id}' is not implemented for profile '{profile_name}'"
            )
        package_cost = require_key(package_match, "cost")
        if not isinstance(package_cost, (int, float)):
            raise TypeError(f"Package '{package_id}' in profile '{profile_name}' must define numeric field 'cost'")
        total_cost += float(package_cost)
        package_picks = require_key(package_match, "picks")
        if not isinstance(package_picks, list):
            raise TypeError(f"Package '{package_id}' in profile '{profile_name}' must define list field 'picks'")
        for package_pick in package_picks:
            if not isinstance(package_pick, dict):
                continue
            pick_id = str(require_key(package_pick, "id"))
            pick_kind = str(require_key(package_pick, "kind"))
            if pick_kind != "weapon":
                continue
            weapon_def = get_weapons("SpaceMarine", [pick_id])[0]
            if "RNG" in weapon_def:
                ranged_codes.append(pick_id)
            else:
                melee_codes.append(pick_id)
        if package_blocks_extras:
            for key in ("melee", "ranged", "secondary", "special"):
                if normalized_picks[key] is not None:
                    raise ValueError(
                        f"slot_picks.{slot_name}.{key} must be empty when package is selected for profile '{profile_name}'"
                    )

    for slot_key in ("melee", "ranged", "secondary"):
        pick_val = normalized_picks[slot_key]
        if pick_val is None:
            continue
        _append_row_pick(slot_key, pick_val)

    special_pick = normalized_picks["special"]
    if special_pick is not None:
        row_match = None
        for special_slot in ("special", "equipment"):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("slot")) == special_slot and str(row.get("pick")) == special_pick:
                    row_match = row
                    break
            if row_match is not None:
                break
        if row_match is None:
            raise KeyError(
                f"slot_picks.{slot_name}.special='{special_pick}' is unknown for profile '{profile_name}'"
            )
        if row_match.get("implemented") is False:
            raise ValueError(
                f"slot_picks.{slot_name}.special='{special_pick}' is not implemented for profile '{profile_name}'"
            )
        special_cost = require_key(row_match, "cost")
        if not isinstance(special_cost, (int, float)):
            raise TypeError(
                f"Special/equipment pick '{special_pick}' in profile '{profile_name}' must define numeric field 'cost'"
            )
        total_cost += float(special_cost)

    return {
        "rng_codes": ranged_codes,
        "cc_codes": melee_codes,
        "value": int(total_cost),
        "normalized_picks": normalized_picks,
    }


def _apply_slot_picks_to_unit(
    unit: Dict[str, Any],
    slot_name: str,
    profile_name: str,
    slot_picks: Any,
) -> None:
    if not isinstance(slot_picks, dict):
        raise ValueError(f"slot_picks.{slot_name} must be an object")
    override = _resolve_slot_pick_override(slot_name, profile_name, slot_picks)
    from engine.weapons import get_weapons

    rng_codes = require_key(override, "rng_codes")
    cc_codes = require_key(override, "cc_codes")
    if not isinstance(rng_codes, list) or not isinstance(cc_codes, list):
        raise TypeError("Slot pick override must provide list fields rng_codes/cc_codes")
    unit["RNG_WEAPONS"] = get_weapons("SpaceMarine", [str(code) for code in rng_codes])
    unit["CC_WEAPONS"] = get_weapons("SpaceMarine", [str(code) for code in cc_codes])
    unit["selectedRngWeaponIndex"] = 0 if unit["RNG_WEAPONS"] else None
    unit["selectedCcWeaponIndex"] = 0 if unit["CC_WEAPONS"] else None
    if unit["selectedRngWeaponIndex"] is not None:
        unit["SHOOT_LEFT"] = resolve_dice_value(
            require_key(unit["RNG_WEAPONS"][unit["selectedRngWeaponIndex"]], "NB"),
            "endless_picks_shoot_left",
        )
    else:
        unit["SHOOT_LEFT"] = 0
    if unit["selectedCcWeaponIndex"] is not None:
        unit["ATTACK_LEFT"] = resolve_dice_value(
            require_key(unit["CC_WEAPONS"][unit["selectedCcWeaponIndex"]], "NB"),
            "endless_picks_attack_left",
        )
    else:
        unit["ATTACK_LEFT"] = 0
    unit["VALUE"] = int(require_key(override, "value"))


def _fallback_spawn_from_objective(gs: Dict[str, Any]) -> Tuple[int, int]:
    objectives = require_key(gs, "objectives")
    first_objective = objectives[0]
    first_hex = require_key(first_objective, "hexes")[0]
    return int(first_hex[0]), int(first_hex[1])


def _append_ed_log(gs: Dict[str, Any], payload: Dict[str, Any]) -> None:
    from engine.action_log_utils import append_action_log

    append_action_log(gs, payload)

