#!/usr/bin/env python3
"""
observation_builder.py - Builds observations from game state
"""

import os
import time
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from shared.data_validation import require_key
from engine.combat_utils import (
    calculate_hex_distance,
    calculate_pathfinding_distance,
    has_line_of_sight,
    expected_dice_value,
    normalize_coordinates,
)
from engine.game_utils import get_unit_by_id
from engine.phase_handlers.shooting_handlers import _calculate_save_target, _calculate_wound_target as _calculate_wound_target_engine
from engine.phase_handlers.shared_utils import (
    is_unit_alive, get_hp_from_cache, require_hp_from_cache,
    get_unit_position, require_unit_position,
    unit_has_rule_effect,
    # PR4 4a: nouveau pipeline d observation squad
    get_engagement_range_subhex, get_fighting_models,
    wound_threshold, save_threshold,
    BASE_TO_BASE_SUBHEX,
)
from engine.macro_intents import (
    INTENT_INVADE,
    INTENT_DEFEND,
    INTENT_ATTACK,
    get_best_enemy_global,
    get_best_enemy_score,
    get_objective_control,
    get_objective_center,
)
from engine.weapon_damage_cache import lookup_best_weapon

class ObservationBuilder:
    """Builds observations for the agent."""

    PHASE2_OBS_SIZE = 357
    SQUAD_OBS_SIZE_TARGET = 108  # PR4 cible — voir build_squad_observation
    SUPPORTED_OBS_SIZES = (357, 108)  # PR4 4e-ii : 2 pipelines cohabitent transitoire
    RULE_FEATURE_BASE_IDX = 314
    RULE_FEATURE_COUNT = 32
    RULE_AWARE_MACRO_BASE_IDX = 346  # kept for reference: base of macro intent context (obs[346:357])

    _UNIT_RULE_FEATURE_IDS = (
        "charge_after_advance",
        "charge_after_flee",
        "charge_impact",
        "closest_target_penetration",
        "reactive_move",
        "reroll_1_save_fight",
        "reroll_1_tohit_fight",
        "reroll_1_towound",
        "reroll_towound_target_on_objective",
        "shoot_after_advance",
        "shoot_after_flee",
        "move_after_shooting",
    )

    _WEAPON_RULE_FEATURE_IDS = (
        "ANTI_VEHICLE",
        "ASSAULT",
        "BLAST",
        "DEVASTATING_WOUNDS",
        "EXTRA_ATTACKS",
        "HAZARDOUS",
        "HEAVY",
        "IGNORES_COVER",
        "INDIRECT_FIRE",
        "LETHAL_HITS",
        "MELTA",
        "PISTOL",
        "PSYCHIC",
        "RAPID_FIRE",
        "SUSTAINED_HITS",
        "TORRENT",
        "TWIN_LINKED",
    )

    _WEAPON_RULES_WITH_PARAMETER = frozenset({
        "ANTI_VEHICLE",
        "MELTA",
        "RAPID_FIRE",
        "SUSTAINED_HITS",
    })
    _WEAPON_RULE_OBS_ALIAS = {
        # Keep observation size/model compatibility: ANTI_X rules share the ANTI_VEHICLE channel.
        "ANTI_INFANTRY": "ANTI_VEHICLE",
        "ANTI_FLY": "ANTI_VEHICLE",
    }
    _WEAPON_RULE_PARAMETER_NORMALIZATION = 6.0
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.unit_registry: Optional[Any] = None
        
        # NOTE: last_unit_positions removed - now using game_state["units_cache_prev"] for movement_direction
        
        # Load perception parameters from config
        obs_params = config.get("observation_params")
        if not obs_params:
            raise KeyError("Config missing required 'observation_params' field - check w40k_core.py config dict creation")  # ✓ CHANGE 3: Enforce required config
        
        # AI_OBSERVATION.md COMPLIANCE: No defaults - force explicit configuration
        # Cache as instance variables (read config ONCE, not 8 times)
        self.perception_radius = obs_params["perception_radius"]  # ✓ CHANGE 3: Explicit config required
        self.max_nearby_units = require_key(obs_params, "max_nearby_units")  # ✓ CHANGE 3: Cache for line 553
        self.max_valid_targets = require_key(obs_params, "max_valid_targets")  # ✓ CHANGE 3: Cache for future use
        
        # CRITIQUE: obs_size depuis config, NO DEFAULT - raise error si manquant
        if "obs_size" not in obs_params:
            raise KeyError(
                f"Config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json. Current obs_params: {obs_params}"
            )
        self.obs_size = obs_params["obs_size"]  # Source unique de vérité

        # PERFORMANCE: Per-observation cache for danger probability calculations
        # Cleared at start of each build_observation() call
        self._danger_probability_cache = {}
        
    # ============================================================================
    # MAIN OBSERVATION
    # ============================================================================
    
    def build_macro_observation(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build macro-level observation for super-agent orchestration.
        
        Returns a structured dict with global context, per-unit features, and eligible mask.
        """
        game_rules = require_key(self.config, "game_rules")
        macro_max_unit_value = require_key(game_rules, "macro_max_unit_value")
        macro_target_weights = self._get_macro_target_weights(game_rules)
        target_profiles = self._get_macro_target_profiles()
        
        current_player = require_key(game_state, "current_player")
        turn = require_key(game_state, "turn")
        phase = require_key(game_state, "phase")
        units_cache = require_key(game_state, "units_cache")
        objectives = require_key(game_state, "objectives")
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        max_range = require_key(game_state, "max_range")
        
        if board_cols <= 1 or board_rows <= 1:
            raise ValueError(f"Invalid board size for normalization: cols={board_cols}, rows={board_rows}")
        if macro_max_unit_value <= 0:
            raise ValueError(f"Invalid macro_max_unit_value for macro observation: {macro_max_unit_value}")
        if max_range <= 0:
            raise ValueError(f"Invalid max_range for macro observation: {max_range}")
        
        objectives_controlled = self._calculate_objectives_controlled(objectives, game_state)
        objective_entries = self._build_macro_objective_entries(objectives, game_state, board_cols, board_rows)
        game_state["macro_objectives"] = objective_entries
        army_value_diff = self._calculate_army_value_diff(units_cache, game_state)
        eligible_ids = self._get_macro_eligible_unit_ids(game_state)
        
        unit_entries = []
        eligible_mask = []
        ally_ids = []
        enemy_ids = []
        
        for unit_id in sorted(units_cache.keys(), key=lambda x: str(x)):
            unit = get_unit_by_id(str(unit_id), game_state)
            if unit is None:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            
            unit_entry = self._build_macro_unit_entry(
                unit=unit,
                macro_max_unit_value=macro_max_unit_value,
                macro_target_weights=macro_target_weights,
                target_profiles=target_profiles,
                objectives=objectives,
                board_cols=board_cols,
                board_rows=board_rows,
                max_range=max_range,
                game_state=game_state,
            )
            unit_entries.append(unit_entry)
            eligible_mask.append(1 if str(unit_id) in eligible_ids else 0)
            if str(unit_id) in units_cache:
                cache_entry = require_key(units_cache, str(unit_id))
                unit_player = require_key(cache_entry, "player")
                if unit_player == current_player:
                    ally_ids.append(str(unit_id))
                else:
                    enemy_ids.append(str(unit_id))
        
        game_state["macro_units"] = unit_entries
        game_state["macro_objectives"] = objective_entries
        attrition_index = len(objective_entries) - 1
        game_state["macro_attrition_objective_index"] = attrition_index

        return {
            "global": {
                "turn": turn,
                "phase": phase,
                "current_player": current_player,
                "objectives_controlled": objectives_controlled,
                "army_value_diff": army_value_diff,
            },
            "units": unit_entries,
            "objectives": objective_entries,
            "ally_ids": ally_ids,
            "enemy_ids": enemy_ids,
            "attrition_objective_index": attrition_index,
            "eligible_mask": eligible_mask,
        }
    
    def _get_macro_target_weights(self, game_rules: Dict[str, Any]) -> Dict[str, float]:
        """Get macro target weights with strict validation."""
        weights = require_key(game_rules, "macro_target_weights")
        for key in ("swarm", "troop", "elite"):
            if key not in weights:
                raise KeyError(f"macro_target_weights missing required key '{key}'")
        return {
            "swarm": float(weights["swarm"]),
            "troop": float(weights["troop"]),
            "elite": float(weights["elite"]),
        }
    
    def _get_macro_target_profiles(self) -> Dict[str, Dict[str, int]]:
        """Return reference target profiles for macro scoring."""
        return {
            "swarm": {"T": 3, "ARMOR_SAVE": 6, "INVUL_SAVE": 0, "HP_MAX": 1},
            "troop": {"T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 0, "HP_MAX": 2},
            "elite": {"T": 5, "ARMOR_SAVE": 2, "INVUL_SAVE": 4, "HP_MAX": 3},
        }
    
    def _get_macro_eligible_unit_ids(self, game_state: Dict[str, Any]) -> set:
        """Get eligible unit ids for current phase (macro selection)."""
        current_phase = require_key(game_state, "phase")
        
        if current_phase == "move":
            pool = require_key(game_state, "move_activation_pool")
        elif current_phase == "shoot":
            pool = require_key(game_state, "shoot_activation_pool")
        elif current_phase == "charge":
            pool = require_key(game_state, "charge_activation_pool")
        elif current_phase == "fight":
            fight_subphase = require_key(game_state, "fight_subphase")
            if fight_subphase == "charging":
                pool = require_key(game_state, "charging_activation_pool")
            elif fight_subphase in ("alternating_active", "cleanup_active"):
                pool = require_key(game_state, "active_alternating_activation_pool")
            elif fight_subphase in ("alternating_non_active", "cleanup_non_active"):
                pool = require_key(game_state, "non_active_alternating_activation_pool")
            elif fight_subphase is None:
                charging_pool = require_key(game_state, "charging_activation_pool")
                active_pool = require_key(game_state, "active_alternating_activation_pool")
                non_active_pool = require_key(game_state, "non_active_alternating_activation_pool")
                if charging_pool or active_pool or non_active_pool:
                    raise ValueError(
                        "fight_subphase is None but fight pools are not empty: "
                        f"charging={len(charging_pool)} active={len(active_pool)} non_active={len(non_active_pool)}"
                    )
                return set()
            else:
                raise KeyError(f"Unknown fight_subphase for macro eligibility: {fight_subphase}")
        elif current_phase == "deployment":
            deployment_state = require_key(game_state, "deployment_state")
            current_deployer = int(require_key(deployment_state, "current_deployer"))
            deployable_units = require_key(deployment_state, "deployable_units")
            pool = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
            if pool is None:
                raise KeyError(f"deployable_units missing player {current_deployer}")
            return {str(uid) for uid in pool}
        else:
            raise KeyError(f"Unsupported phase for macro eligibility: {current_phase}")
        
        return {str(uid) for uid in pool}
    
    def _calculate_objectives_controlled(self, objectives: List[Dict[str, Any]], game_state: Dict[str, Any]) -> Dict[str, int]:
        """Count objectives controlled by each player."""
        units_cache = require_key(game_state, "units_cache")
        p1_count = 0
        p2_count = 0
        
        for objective in objectives:
            obj_hexes = require_key(objective, "hexes")
            hex_set = set(tuple(normalize_coordinates(h[0], h[1])) for h in obj_hexes)
            p1_oc = 0
            p2_oc = 0
            for unit_id, cache_entry in units_cache.items():
                unit = get_unit_by_id(str(unit_id), game_state)
                if unit is None:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                unit_pos = require_unit_position(unit, game_state)
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    if cache_entry["player"] == 1:
                        p1_oc += oc
                    elif cache_entry["player"] == 2:
                        p2_oc += oc
            
            if p1_oc > p2_oc:
                p1_count += 1
            elif p2_oc > p1_oc:
                p2_count += 1
        
        return {"p1": p1_count, "p2": p2_count}

    def _build_macro_objective_entries(
        self,
        objectives: List[Dict[str, Any]],
        game_state: Dict[str, Any],
        board_cols: int,
        board_rows: int
    ) -> List[Dict[str, Any]]:
        """Build per-objective macro features."""
        if board_cols <= 0 or board_rows <= 0:
            raise ValueError(f"Invalid board size for macro objectives: cols={board_cols}, rows={board_rows}")

        current_player = require_key(game_state, "current_player")
        units_cache = require_key(game_state, "units_cache")

        entries = []
        for objective in objectives:
            obj_id = require_key(objective, "id")
            obj_hexes = require_key(objective, "hexes")
            if not obj_hexes:
                raise ValueError(f"Objective {obj_id} has no hexes")

            sum_col = 0
            sum_row = 0
            hex_set = set()
            for col, row in obj_hexes:
                norm_col, norm_row = normalize_coordinates(col, row)
                sum_col += norm_col
                sum_row += norm_row
                hex_set.add((norm_col, norm_row))
            centroid_col = sum_col / float(len(obj_hexes))
            centroid_row = sum_row / float(len(obj_hexes))

            p1_oc = 0
            p2_oc = 0
            for unit_id, cache_entry in units_cache.items():
                unit = get_unit_by_id(str(unit_id), game_state)
                if unit is None:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                unit_pos = require_unit_position(unit, game_state)
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    if cache_entry["player"] == 1:
                        p1_oc += oc
                    elif cache_entry["player"] == 2:
                        p2_oc += oc

            if current_player == 1:
                my_oc = p1_oc
                enemy_oc = p2_oc
            elif current_player == 2:
                my_oc = p2_oc
                enemy_oc = p1_oc
            else:
                raise ValueError(f"Invalid current_player for macro objectives: {current_player}")

            if my_oc > enemy_oc:
                control_state = 1.0
            elif enemy_oc > my_oc:
                control_state = -1.0
            else:
                control_state = 0.0

            entries.append({
                "id": str(obj_id),
                "col": centroid_col,
                "row": centroid_row,
                "col_norm": centroid_col / float(board_cols),
                "row_norm": centroid_row / float(board_rows),
                "control_state": control_state,
            })

        return entries
    
    def _calculate_army_value_diff(self, units_cache: Dict[str, Any], game_state: Dict[str, Any]) -> int:
        """Compute sum(VALUE) alive for current_player minus opponent (egocentric)."""
        current_player = int(require_key(game_state, "current_player"))
        my_value = 0
        enemy_value = 0
        for unit_id, cache_entry in units_cache.items():
            unit = get_unit_by_id(str(unit_id), game_state)
            if unit is None:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if int(cache_entry["player"]) == current_player:
                my_value += unit_value
            else:
                enemy_value += unit_value
        return my_value - enemy_value
    
    def _build_macro_unit_entry(
        self,
        unit: Dict[str, Any],
        macro_max_unit_value: float,
        macro_target_weights: Dict[str, float],
        target_profiles: Dict[str, Dict[str, int]],
        objectives: List[Dict[str, Any]],
        board_cols: int,
        board_rows: int,
        max_range: int,
        game_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build per-unit macro features."""
        unit_id = require_key(unit, "id")
        unit_type = require_key(unit, "unitType")
        unit_col, unit_row = require_unit_position(unit, game_state)
        hp_cur = require_hp_from_cache(str(unit_id), game_state)
        hp_max = require_key(unit, "HP_MAX")
        unit_value = require_key(unit, "VALUE")
        if hp_max <= 0:
            raise ValueError(f"Invalid HP_MAX for macro observation: unit_id={unit_id} HP_MAX={hp_max}")
        
        best_ranged_score, best_ranged_target = self._calculate_best_weighted_score(
            require_key(unit, "RNG_WEAPONS"),
            target_profiles,
            macro_target_weights,
            "macro_rng",
        )
        best_melee_score, best_melee_target = self._calculate_best_weighted_score(
            require_key(unit, "CC_WEAPONS"),
            target_profiles,
            macro_target_weights,
            "macro_cc",
        )
        
        total_score = best_ranged_score + best_melee_score
        if total_score == 0:
            raise ValueError(f"Macro score sum is zero for unit_id={unit_id}")
        attack_mode_ratio = best_melee_score / total_score
        
        best_ranged_onehot = self._target_onehot(best_ranged_target)
        best_melee_onehot = self._target_onehot(best_melee_target)
        
        dist_obj = self._min_distance_to_objective((unit_col, unit_row), objectives)
        dist_obj_norm = dist_obj / max_range
        
        return {
            "id": str(unit_id),
            "unitType": unit_type,
            "player": require_key(unit, "player"),
            "col": unit_col,
            "row": unit_row,
            "hp": hp_cur,
            "hp_max": hp_max,
            "value": unit_value,
            "dist_obj": dist_obj,
            "best_ranged_target_onehot": best_ranged_onehot,
            "best_melee_target_onehot": best_melee_onehot,
            "attack_mode_ratio": attack_mode_ratio,
            "hp_ratio": hp_cur / hp_max,
            "value_norm": unit_value / macro_max_unit_value,
            "pos_col_norm": unit_col / (board_cols - 1),
            "pos_row_norm": unit_row / (board_rows - 1),
            "dist_obj_norm": dist_obj_norm,
        }
    
    def _calculate_best_weighted_score(
        self,
        weapons: List[Dict[str, Any]],
        target_profiles: Dict[str, Dict[str, int]],
        macro_target_weights: Dict[str, float],
        roll_context_prefix: str,
    ) -> Tuple[float, Optional[str]]:
        """Calculate best weighted score across weapons and target profiles."""
        best_score = 0.0
        best_target = None
        target_order = ["swarm", "troop", "elite"]
        
        for weapon in weapons:
            for target_key in target_order:
                profile = require_key(target_profiles, target_key)
                weight = require_key(macro_target_weights, target_key)
                score = self._calculate_expected_damage_against_profile(
                    weapon=weapon,
                    target_profile=profile,
                    roll_context_prefix=roll_context_prefix,
                ) * weight
                
                if score > best_score:
                    best_score = score
                    best_target = target_key
                elif score == best_score and best_score > 0 and best_target is not None:
                    if target_order.index(target_key) < target_order.index(best_target):
                        best_target = target_key
        
        return best_score, best_target
    
    def _calculate_expected_damage_against_profile(
        self,
        weapon: Dict[str, Any],
        target_profile: Dict[str, int],
        roll_context_prefix: str,
    ) -> float:
        """Expected damage against a reference target profile (no RNG)."""
        num_attacks = expected_dice_value(require_key(weapon, "NB"), f"{roll_context_prefix}_nb")
        hit_target = require_key(weapon, "ATK")
        strength = require_key(weapon, "STR")
        ap = require_key(weapon, "AP")
        damage = expected_dice_value(require_key(weapon, "DMG"), f"{roll_context_prefix}_dmg")
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        wound_target = _calculate_wound_target_engine(strength, require_key(target_profile, "T"))
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        save_target = _calculate_save_target(
            {
                "ARMOR_SAVE": require_key(target_profile, "ARMOR_SAVE"),
                "INVUL_SAVE": require_key(target_profile, "INVUL_SAVE"),
            },
            ap,
        )
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        return num_attacks * p_hit * p_wound * p_fail_save * damage
    
    def _target_onehot(self, target_key: Optional[str]) -> List[float]:
        """Return one-hot encoding for swarm/troop/elite."""
        if target_key is None:
            return [0.0, 0.0, 0.0]
        if target_key == "swarm":
            return [1.0, 0.0, 0.0]
        if target_key == "troop":
            return [0.0, 1.0, 0.0]
        if target_key == "elite":
            return [0.0, 0.0, 1.0]
        raise ValueError(f"Unknown target key for onehot: {target_key}")
    
    def _min_distance_to_objective(self, unit_pos: Tuple[int, int], objectives: List[Dict[str, Any]]) -> int:
        """Compute minimum hex distance to any objective hex."""
        min_dist = None
        for objective in objectives:
            obj_hexes = require_key(objective, "hexes")
            for h in obj_hexes:
                col, row = normalize_coordinates(h[0], h[1])
                dist = calculate_hex_distance(unit_pos[0], unit_pos[1], col, row)
                if min_dist is None or dist < min_dist:
                    min_dist = dist
        if min_dist is None:
            raise ValueError("No objective hexes found for dist_obj calculation")
        return min_dist
    
    def _calculate_combat_mix_score(self, unit: Dict[str, Any]) -> float:
        """
        Calculate combat preference from dynamic weapon profile only.
        
        Returns 0.1-0.9:
        - 0.1-0.3: Melee specialist (CC damage >> RNG damage)
        - 0.4-0.6: Balanced combatant
        - 0.7-0.9: Ranged specialist (RNG damage >> CC damage)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        """
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        cc_weapons = require_key(unit, "CC_WEAPONS")

        # Dynamic proxy: expected pressure from weapon profile, without static unitType priors.
        ranged_expected = 0.0
        for weapon in rng_weapons:
            attacks = expected_dice_value(require_key(weapon, "NB"), "combat_mix_rng_nb")
            damage = expected_dice_value(require_key(weapon, "DMG"), "combat_mix_rng_dmg")
            hit_prob = max(0.0, min(1.0, (7 - require_key(weapon, "ATK")) / 6.0))
            strength_factor = max(0.0, min(1.0, require_key(weapon, "STR") / 10.0))
            ap_factor = max(0.0, min(1.0, require_key(weapon, "AP") / 6.0))
            weapon_expected = attacks * damage * hit_prob * (0.5 + (0.3 * strength_factor) + (0.2 * ap_factor))
            ranged_expected = max(ranged_expected, weapon_expected)

        melee_expected = 0.0
        for weapon in cc_weapons:
            attacks = expected_dice_value(require_key(weapon, "NB"), "combat_mix_cc_nb")
            damage = expected_dice_value(require_key(weapon, "DMG"), "combat_mix_cc_dmg")
            hit_prob = max(0.0, min(1.0, (7 - require_key(weapon, "ATK")) / 6.0))
            strength_factor = max(0.0, min(1.0, require_key(weapon, "STR") / 10.0))
            ap_factor = max(0.0, min(1.0, require_key(weapon, "AP") / 6.0))
            weapon_expected = attacks * damage * hit_prob * (0.5 + (0.3 * strength_factor) + (0.2 * ap_factor))
            melee_expected = max(melee_expected, weapon_expected)

        total_expected = ranged_expected + melee_expected
        if total_expected == 0:
            return 0.5  # Neutral (no combat power)

        # Scale to 0.1-0.9 range
        raw_ratio = ranged_expected / total_expected
        return 0.1 + (raw_ratio * 0.8)
    
    def _calculate_expected_damage(self, num_attacks: float, to_hit_stat: int,
                                   strength: int, target_toughness: int, ap: int,
                                   target_save: int, target_invul: int,
                                   damage_per_wound: float) -> float:
        """
        Calculate expected damage using W40K dice mechanics with invulnerable saves.
        
        Expected damage = Attacks × P(hit) × P(wound) × P(fail_save) × Damage
        """
        # Hit probability
        p_hit = max(0.0, min(1.0, (7 - to_hit_stat) / 6.0))
        
        # Wound probability
        wound_target = self._calculate_wound_target(strength, target_toughness)
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (use better of armor or invul)
        modified_armor_save = target_save - ap
        best_save = min(modified_armor_save, target_invul)

        if best_save > 6:
            p_fail_save = 1.0  # Impossible to save
        else:
            p_fail_save = max(0.0, min(1.0, (best_save - 1) / 6.0))
        
        # Expected damage per turn
        expected = num_attacks * p_hit * p_wound * p_fail_save * damage_per_wound
        
        return expected
    
    def _calculate_wound_target(self, strength: int, toughness: int) -> int:
        """W40K wound chart - basic calculation without external dependencies"""
        if strength >= toughness * 2:
            return 2  # 2+
        elif strength > toughness:
            return 3  # 3+
        elif strength == toughness:
            return 4  # 4+
        elif strength * 2 <= toughness:
            return 6  # 6+
        else:
            return 5  # 5+
    
    def _calculate_favorite_target(self, unit: Dict[str, Any]) -> float:
        """
        Estimate target toughness preference from dynamic weapon profile only.

        Returns 0.0-1.0 encoding:
        - 0.0: low-toughness leaning profile
        - 1.0: high-toughness leaning profile
        """
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        cc_weapons = require_key(unit, "CC_WEAPONS")
        all_weapons = list(rng_weapons) + list(cc_weapons)
        if not all_weapons:
            return 0.5  # Neutral for non-combat profile

        best_piercing_score = 0.0
        for weapon in all_weapons:
            strength_factor = max(0.0, min(1.0, require_key(weapon, "STR") / 10.0))
            ap_factor = max(0.0, min(1.0, require_key(weapon, "AP") / 6.0))
            damage_factor = max(0.0, min(1.0, expected_dice_value(require_key(weapon, "DMG"), "favorite_target_dmg") / 6.0))
            piercing_score = (0.5 * strength_factor) + (0.3 * ap_factor) + (0.2 * damage_factor)
            best_piercing_score = max(best_piercing_score, piercing_score)

        return best_piercing_score
    
    def _calculate_movement_direction(self, unit: Dict[str, Any],
                                     active_unit: Dict[str, Any],
                                     game_state: Dict[str, Any],
                                     positions: Dict[str, Tuple[int, int]]) -> float:
        """
        Encode temporal behavior in single float - replaces frame stacking.
        
        Detects unit's movement pattern relative to active unit:
        - 0.00-0.24: Fled far from me (>50% MOVE away)
        - 0.25-0.49: Moved away slightly (<50% MOVE away)
        - 0.50-0.74: Advanced slightly (<50% MOVE toward)
        - 0.75-1.00: Charged at me (>50% MOVE toward)
        
        Critical for detecting threats before they strike!
        Uses units_cache_prev for previous positions (snapshot at step start).
        """
        # Get last known position from units_cache_prev
        units_cache_prev = game_state.get("units_cache_prev")
        if not units_cache_prev:
            return 0.5  # Unknown/first turn
        
        if "id" not in unit:
            raise KeyError(f"Unit missing required 'id' field: {unit}")
        
        unit_id = str(unit["id"])
        if unit_id not in units_cache_prev:
            return 0.5  # No previous position data
        
        # Validate required position fields
        if "col" not in unit or "row" not in unit:
            raise KeyError(f"Unit missing required position fields: {unit}")
        if "col" not in active_unit or "row" not in active_unit:
            raise KeyError(f"Active unit missing required position fields: {active_unit}")
        
        prev_entry = units_cache_prev[unit_id]
        prev_col, prev_row = prev_entry["col"], prev_entry["row"]
        curr_col, curr_row = positions[str(unit_id)]
        active_col, active_row = positions[str(active_unit["id"])]
        prev_dist = calculate_hex_distance(
            prev_col, prev_row, 
            active_col, active_row
        )
        curr_dist = calculate_hex_distance(
            curr_col, curr_row,
            active_col, active_row
        )
        
        move_distance = calculate_hex_distance(prev_col, prev_row, curr_col, curr_row)
        
        if "MOVE" not in unit:
            raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
        max_move = unit["MOVE"]
        
        if move_distance == 0:
            return 0.5  # No movement
        
        delta_dist = prev_dist - curr_dist  # Positive = moved closer
        move_ratio = abs(delta_dist) / max(1, max_move)  # Prevent division by zero
        
        if delta_dist < 0:  # Moved away
            if move_ratio > 0.5:
                return 0.12  # Fled far (>50% MOVE away)
            else:
                return 0.37  # Moved away slightly
        else:  # Moved closer
            if move_ratio > 0.5:
                return 0.87  # Charged (>50% MOVE toward)
            else:
                return 0.62  # Advanced slightly
    
    def _check_los_cached(self, shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Check LoS using cache; los_cache is required.
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # AI_TURN_SHOOTING_UPDATE.md: Use shooter["los_cache"] (new architecture)
        target_id = str(target["id"])
        
        los_cache = require_key(shooter, "los_cache")
        if target_id not in los_cache:
            raise KeyError(f"los_cache missing target_id={target_id} for shooter_id={shooter.get('id')}")
        return 1.0 if los_cache[target_id] else 0.0

    def _has_los_from_topology(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
        game_state: Dict[str, Any],
    ) -> bool:
        """Check LoS for observation visibility features.

        Uses precomputed los_topology when available (legacy boards).
        Falls back to on-demand hex line trace (Board ×10) via hex_utils.
        Returns False for out-of-bounds coordinates.
        """
        board_cols = game_state["board_cols"]
        board_rows = game_state["board_rows"]
        if not (
            isinstance(board_cols, int)
            and isinstance(board_rows, int)
            and 0 <= from_col < board_cols
            and 0 <= from_row < board_rows
            and 0 <= to_col < board_cols
            and 0 <= to_row < board_rows
        ):
            return False
        config = require_key(game_state, "config")
        game_rules = require_key(config, "game_rules")
        los_visibility_min_ratio = float(require_key(game_rules, "los_visibility_min_ratio"))

        los_topology = game_state.get("los_topology")
        if los_topology is not None:
            from_idx = from_row * board_cols + from_col
            to_idx = to_row * board_cols + to_col
            visibility_ratio = float(los_topology[from_idx, to_idx])
        else:
            from engine.hex_utils import compute_los_visibility, build_wall_set
            wall_set = game_state.get("_wall_set_cache")
            if wall_set is None:
                wall_set = build_wall_set(game_state)
                game_state["_wall_set_cache"] = wall_set
            visibility_ratio = compute_los_visibility(
                from_col, from_row, to_col, to_row, wall_set,
            )
        return visibility_ratio >= los_visibility_min_ratio

    def _build_los_cache_for_observation(
        self,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        six_enemies: List[Tuple[float, Dict[str, Any]]],
    ) -> Dict[Tuple[str, str], bool]:
        """
        Build a LoS cache for observation: (ally_id, enemy_id) -> bool.
        Uses ally["los_cache"] (must be built explicitly before this call).
        """
        units_cache = require_key(game_state, "units_cache")
        active_entry = require_key(units_cache, str(active_unit["id"]))
        active_player = require_key(active_entry, "player")
        allies = []
        for ally_id, cache_entry in units_cache.items():
            if cache_entry["player"] == active_player:
                ally = get_unit_by_id(ally_id, game_state)
                if ally is None:
                    raise KeyError(f"Unit {ally_id} missing from game_state['units']")
                allies.append(ally)
        result: Dict[Tuple[str, str], bool] = {}
        for ally in allies:
            los_cache = require_key(ally, "los_cache")
            for _distance, enemy in six_enemies:
                target_id = str(enemy["id"])
                key = (str(ally["id"]), target_id)
                if target_id not in los_cache:
                    raise KeyError(f"los_cache missing target_id={target_id} for ally_id={ally.get('id')}")
                result[key] = bool(los_cache[target_id])
        return result

    def _use_ranged_scoring_for_phase(self, game_state: Dict[str, Any]) -> bool:
        """
        Resolve phase-aware weapon mode for target scoring features.

        Returns:
            True for ranged scoring, False for melee scoring.
        """
        phase = require_key(game_state, "phase")
        if phase in ("shoot", "move", "command", "deployment"):
            return True
        if phase in ("charge", "fight"):
            return False
        raise KeyError(f"Unknown phase for phase-aware weapon scoring: {phase}")

    def _get_phase_aware_best_weapon_features(
        self,
        attacker: Dict[str, Any],
        target: Dict[str, Any],
        game_state: Dict[str, Any],
    ) -> Tuple[int, float, bool]:
        """
        Common scoring service used by enemy and valid-target encoding.

        Uses _best_weapon_cache for O(1) lookup (pre-computed at episode reset).

        Returns:
            (best_weapon_index, best_kill_probability, is_ranged_mode)
        """
        is_ranged_mode = self._use_ranged_scoring_for_phase(game_state)
        cache = game_state.get("_best_weapon_cache")
        if cache is None:
            return (-1, 0.0, is_ranged_mode)

        hp_cur = get_hp_from_cache(str(target["id"]), game_state)
        if hp_cur is None or hp_cur <= 0:
            return (-1, 0.0, is_ranged_mode)

        best_idx, best_dmg = lookup_best_weapon(
            cache, str(attacker["id"]), str(target["id"]), is_ranged_mode,
        )
        if best_idx < 0 or best_dmg <= 0.0:
            return (-1, 0.0, is_ranged_mode)
        kp = min(1.0, best_dmg / float(hp_cur))
        return best_idx, kp, is_ranged_mode
    
    def _calculate_danger_probability(self, defender: Dict[str, Any], attacker: Dict[str, Any], game_state: Dict[str, Any],
                                     positions: Optional[Dict[str, Tuple[int, int]]] = None) -> float:
        """
        Calculate probability that attacker will kill defender on its next turn.
        Works for ANY unit pair (active unit vs enemy, VIP vs enemy, etc.)

        Considers:
        - Distance (can they reach?) - uses BFS pathfinding to respect walls
        - Hit/wound/save probabilities
        - Number of attacks
        - Damage output

        Returns: 0.0-1.0 probability

        PERFORMANCE: Memoized per build_observation() call.
        Same (defender, attacker) pairs are calculated 7+ times in single observation.
        Cache is cleared at start of each build_observation() call.
        """
        # PERFORMANCE: Check memoization cache first
        cache_key = (defender["id"], attacker["id"])
        if cache_key in self._danger_probability_cache:
            return self._danger_probability_cache[cache_key]

        # Use BFS pathfinding distance to respect walls for reachability
        if positions is not None:
            defender_col, defender_row = positions[str(defender["id"])]
            attacker_col, attacker_row = positions[str(attacker["id"])]
        else:
            defender_col, defender_row = require_unit_position(defender, game_state)
            attacker_col, attacker_row = require_unit_position(attacker, game_state)
        distance = calculate_pathfinding_distance(
            defender_col, defender_row,
            attacker_col, attacker_row,
            game_state
        )

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
        from engine.utils.weapon_helpers import get_max_ranged_range
        from engine.spatial_relations import get_engagement_zone
        max_ranged_range = get_max_ranged_range(attacker)
        melee_range = get_engagement_zone(game_state)

        can_use_ranged = max_ranged_range > 0 and distance <= max_ranged_range
        can_use_melee = calculate_hex_distance(attacker_col, attacker_row, defender_col, defender_row) <= melee_range

        if not can_use_ranged and not can_use_melee:
            self._danger_probability_cache[cache_key] = 0.0
            return 0.0

        bwc = game_state.get("_best_weapon_cache")
        defender_hp = get_hp_from_cache(str(defender["id"]), game_state)
        if defender_hp is None or defender_hp <= 0:
            self._danger_probability_cache[cache_key] = 1.0
            return 1.0

        if bwc is not None:
            is_ranged = can_use_ranged and not can_use_melee
            _, best_exp_dmg = lookup_best_weapon(
                bwc, str(attacker["id"]), str(defender["id"]), is_ranged,
            )
        else:
            best_exp_dmg = 0.0

        if best_exp_dmg <= 0.0:
            self._danger_probability_cache[cache_key] = 0.0
            return 0.0
        if best_exp_dmg >= defender_hp:
            self._danger_probability_cache[cache_key] = 1.0
            return 1.0
        result = min(1.0, best_exp_dmg / defender_hp)
        self._danger_probability_cache[cache_key] = result
        return result
    
    def _calculate_army_weighted_threat(self, target: Dict[str, Any], valid_targets: List[Dict[str, Any]], game_state: Dict[str, Any])  -> float:
        """
        Calculate army-wide weighted threat score considering all friendly units by VALUE.
        
        This is the STRATEGIC PRIORITY feature that teaches the agent to:
        - Protect high-VALUE units (Leaders, Elites)
        - Consider threats to the entire team, not just personal survival
        - Make sacrifices when strategically necessary
        
        Logic:
        1. For each friendly unit, calculate danger from this target
        2. Weight that danger by the friendly unit's VALUE (1-200)
        3. Sum all weighted dangers
        4. Normalize to 0.0-1.0 based on highest threat among all targets
        
        Returns: 0.0-1.0 (1.0 = highest strategic threat among all targets)
        """
        my_player = game_state["current_player"]
        friendly_units = [
            u for u in game_state["units"]
            if u["player"] == my_player and is_unit_alive(str(u["id"]), game_state)
        ]
        
        if not friendly_units:
            return 0.0
        
        total_weighted_threat = 0.0
        for friendly in friendly_units:
            danger = self._calculate_danger_probability(friendly, target, game_state)
            if "VALUE" not in friendly:
                raise KeyError(f"Friendly unit missing required 'VALUE' field: {friendly}")
            unit_value = friendly["VALUE"]
            weighted_threat = danger * unit_value
            total_weighted_threat += weighted_threat

        all_weighted_threats = []
        for t in valid_targets:
            t_total = 0.0
            for friendly in friendly_units:
                danger = self._calculate_danger_probability(friendly, t, game_state)
                if "VALUE" not in friendly:
                    raise KeyError(f"Friendly unit missing required 'VALUE' field: {friendly}")
                unit_value = friendly["VALUE"]
                t_total += danger * unit_value
            all_weighted_threats.append(t_total)
        
        max_weighted_threat = max(all_weighted_threats) if all_weighted_threats else 1.0
        
        if max_weighted_threat > 0:
            return min(1.0, total_weighted_threat / max_weighted_threat)
        else:
            return 0.0
    
    def _calculate_target_type_match(self, active_unit: Dict[str, Any], 
                                    target: Dict[str, Any]) -> float:
        """
        Calculate unit_registry-based type compatibility (0.0-1.0).
        Higher = this unit is specialized against this target type.
        
        Example: RangedSwarm unit gets 1.0 against Swarm targets, 0.3 against others
        """
        try:
            if not self.unit_registry:
                return 0.5

            if "unitType" not in active_unit:
                raise KeyError(f"Active unit missing required 'unitType' field: {active_unit}")
            unit_type = active_unit["unitType"]
            
            if "Swarm" in unit_type:
                preferred = "swarm"
            elif "Troop" in unit_type:
                preferred = "troop"
            elif "Elite" in unit_type:
                preferred = "elite"
            elif "Leader" in unit_type:
                preferred = "leader"
            else:
                return 0.5

            if "HP_MAX" not in target:
                raise KeyError(f"Target missing required 'HP_MAX' field: {target}")
            target_hp = target["HP_MAX"]
            if target_hp <= 1:
                target_type = "swarm"
            elif target_hp <= 3:
                target_type = "troop"
            elif target_hp <= 6:
                target_type = "elite"
            else:
                target_type = "leader"
            
            return 1.0 if preferred == target_type else 0.3
            
        except Exception as e:
            import logging
            logging.error(f"observation_builder._get_target_type_preference failed: {str(e)} - returning neutral value 0.5")
            return 0.5

    def _can_melee_units_charge_target(self, target: Dict[str, Any], game_state: Dict[str, Any],
                                       positions: Dict[str, Tuple[int, int]]) -> bool:
        """Check if any friendly melee units can charge this target.

        Uses BFS pathfinding distance to respect walls for charge reachability.
        """
        current_player = game_state["current_player"]

        for unit in game_state["units"]:
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Check if unit has melee weapons
            has_melee = False
            if unit.get("CC_WEAPONS") and len(unit["CC_WEAPONS"]) > 0:
                # Check if any melee weapon has DMG > 0 (DMG required per unit definitions)
                has_melee = any(
                    expected_dice_value(require_key(w, "DMG"), "melee_charge_dmg") > 0
                    for w in unit["CC_WEAPONS"]
                )
            
            if (unit["player"] == current_player and
                is_unit_alive(str(unit["id"]), game_state) and
                has_melee):  # Has melee capability

                # Charge range check — anchor-based distance (approx, sufficient for RL obs)
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                _gr = require_key(require_key(game_state, "config"), "game_rules")
                max_charge_range = unit["MOVE"] + require_key(_gr, "charge_max_distance")
                unit_col, unit_row = positions[str(unit["id"])]
                target_col, target_row = positions[str(target["id"])]
                distance = calculate_hex_distance(unit_col, unit_row, target_col, target_row)

                if distance <= max_charge_range:
                    return True

        return False
    
    
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================
    # ============================================================================

    
    def build_observation(self, game_state: Dict[str, Any], active_unit_override: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Build asymmetric egocentric observation vector with R=25 perception radius.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.

        Structure (323 floats, legacy):
        - [0:15]    Global context (15 floats) - includes objective control
        - [15:37]   Active unit capabilities (22 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        - [37:69]   Directional terrain (32 floats: 8 directions × 4 features)
        - [69:141]  Allied units (72 floats: 6 units × 12 features)
        - [141:273] Enemy units (132 floats: 6 units × 22 features) - OPTIMISÉ
        - [273:313] Valid targets (40 floats: 5 targets × 8 features)
        - [314:318] Macro target (4 floats)
        - [318:323] Macro intent (5 floats)

        Structure (355 floats, rule-aware):
        - Legacy blocks [0:313]
        - [314:346] Rules features (32 floats):
          unit rules (12), FLY (1), invul flags (2), weapon rules (17)
        - [346:350] Macro target (4 floats)
        - [350:355] Macro intent (5 floats)

        Asymmetric design: More complete information about enemies than allies.
        Agent discovers optimal tactical combinations through training.
        """
        # PR4 4e-ii : pipeline mono-fig (357-d) uniquement. Si obs_size == 108
        # (squad pipeline), le caller doit appeler build_squad_observation. Cette
        # fonction n est PAS retro-compatible avec 108-d.
        if self.obs_size != self.PHASE2_OBS_SIZE:
            raise RuntimeError(
                f"build_observation requires obs_size={self.PHASE2_OBS_SIZE} (mono-fig pipeline). "
                f"Got obs_size={self.obs_size}. For squad pipeline (108-d), call "
                "build_squad_observation(game_state, active_squad_id) instead."
            )

        # PERFORMANCE: Clear per-observation cache (same pairs recalculated multiple times)
        self._danger_probability_cache = {}
        game_state.pop("macro_objectives", None)

        obs = np.zeros(self.obs_size, dtype=np.float32)
        
        # Get active unit (agent's current unit); pool building ensures only alive units.
        active_unit = active_unit_override if active_unit_override is not None else self._get_active_unit_for_observation(game_state)
        if not active_unit:
            # No active unit - return zero observation
            return obs
        if not is_unit_alive(str(active_unit["id"]), game_state):
            raise ValueError(f"Active unit for observation is not alive: unit_id={active_unit.get('id')}")
        
        # PERF: visibility_to_allies uses los_topology directly (no los_cache rebuild needed)
        # Local positions cache - one extraction from units_cache, reused ~1M times
        units_cache = require_key(game_state, "units_cache")
        positions = {uid: (e["col"], e["row"]) for uid, e in units_cache.items()}

        # === SECTION 1: Global Context (15 floats) - includes objective control ===
        # Encode turn ownership in a seat-agnostic [0, 1] scale.
        # 1.0 means the current decision belongs to the active unit's side.
        # This avoids leaking absolute player IDs (1/2) and keeps observation values within Box[0,1].
        current_player = int(require_key(game_state, "current_player"))
        active_player = int(require_key(active_unit, "player"))
        obs[0] = 1.0 if current_player == active_player else 0.0
        phase_encoding = {"deployment": 0.0, "command": 0.0, "move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}
        if game_state["phase"] not in phase_encoding:
            raise KeyError(f"Unknown phase for observation: {game_state['phase']}")
        obs[1] = phase_encoding[game_state["phase"]]
        obs[2] = min(1.0, game_state["turn"] / 5.0)  # Normalized by max 5 turns
        obs[3] = min(1.0, game_state["episode_steps"] / 100.0)
        hp_cur = get_hp_from_cache(str(active_unit["id"]), game_state)
        obs[4] = (hp_cur if hp_cur is not None else 0) / max(1, active_unit["HP_MAX"])
        obs[5] = 1.0 if active_unit["id"] in game_state["units_moved"] else 0.0
        obs[6] = 1.0 if active_unit["id"] in game_state["units_shot"] else 0.0
        obs[7] = 1.0 if active_unit["id"] in game_state["units_attacked"] else 0.0
        # ADVANCE_IMPLEMENTATION: Track if unit has advanced this turn
        obs[8] = 1.0 if str(active_unit["id"]) in require_key(game_state, "units_advanced") else 0.0

        # Count alive units for strategic awareness
        alive_friendlies = sum(1 for u in game_state["units"]
                              if u["player"] == active_unit["player"] and is_unit_alive(str(u["id"]), game_state))
        alive_enemies = sum(1 for u in game_state["units"]
                           if u["player"] != active_unit["player"] and is_unit_alive(str(u["id"]), game_state))
        max_nearby = self.max_nearby_units
        obs[9] = alive_friendlies / max(1, max_nearby)
        obs[10] = alive_enemies / max(1, max_nearby)

        # Objective control status (5 floats for 5 objectives)
        # -1.0 = enemy controls, 0.0 = contested/empty, 1.0 = we control
        self._encode_objective_control(obs, active_unit, game_state, base_idx=11, positions=positions)
        # === SECTION 2: Active Unit Capabilities (22 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md ===
        _scale = game_state["inches_to_subhex"]
        _move_norm = 12.0 * _scale
        _rng_norm = 24.0 * _scale
        obs[16] = require_key(active_unit, "MOVE") / _move_norm

        # RNG_WEAPONS[0] (3 floats: RNG, DMG, NB)
        rng_weapons = require_key(active_unit, "RNG_WEAPONS")
        if len(rng_weapons) > 0:
            obs[17] = require_key(rng_weapons[0], "RNG") / _rng_norm
            obs[18] = expected_dice_value(require_key(rng_weapons[0], "DMG"), "obs_rng0_dmg") / 5.0
            obs[19] = expected_dice_value(require_key(rng_weapons[0], "NB"), "obs_rng0_nb") / 10.0
        else:
            obs[17] = obs[18] = obs[19] = 0.0

        # RNG_WEAPONS[1] (3 floats)
        if len(rng_weapons) > 1:
            obs[20] = require_key(rng_weapons[1], "RNG") / _rng_norm
            obs[21] = expected_dice_value(require_key(rng_weapons[1], "DMG"), "obs_rng1_dmg") / 5.0
            obs[22] = expected_dice_value(require_key(rng_weapons[1], "NB"), "obs_rng1_nb") / 10.0
        else:
            obs[20] = obs[21] = obs[22] = 0.0

        # RNG_WEAPONS[2] (3 floats)
        if len(rng_weapons) > 2:
            obs[23] = require_key(rng_weapons[2], "RNG") / _rng_norm
            obs[24] = expected_dice_value(require_key(rng_weapons[2], "DMG"), "obs_rng2_dmg") / 5.0
            obs[25] = expected_dice_value(require_key(rng_weapons[2], "NB"), "obs_rng2_nb") / 10.0
        else:
            obs[23] = obs[24] = obs[25] = 0.0

        # CC_WEAPONS[0] (5 floats: NB, ATK, STR, AP, DMG)
        cc_weapons = require_key(active_unit, "CC_WEAPONS")
        if len(cc_weapons) > 0:
            obs[26] = expected_dice_value(require_key(cc_weapons[0], "NB"), "obs_cc0_nb") / 10.0
            obs[27] = require_key(cc_weapons[0], "ATK") / 6.0
            obs[28] = require_key(cc_weapons[0], "STR") / 10.0
            obs[29] = require_key(cc_weapons[0], "AP") / 6.0
            obs[30] = expected_dice_value(require_key(cc_weapons[0], "DMG"), "obs_cc0_dmg") / 5.0
        else:
            obs[26] = obs[27] = obs[28] = obs[29] = obs[30] = 0.0

        # CC_WEAPONS[1] (5 floats)
        if len(cc_weapons) > 1:
            obs[31] = expected_dice_value(require_key(cc_weapons[1], "NB"), "obs_cc1_nb") / 10.0
            obs[32] = require_key(cc_weapons[1], "ATK") / 6.0
            obs[33] = require_key(cc_weapons[1], "STR") / 10.0
            obs[34] = require_key(cc_weapons[1], "AP") / 6.0
            obs[35] = expected_dice_value(require_key(cc_weapons[1], "DMG"), "obs_cc1_dmg") / 5.0
        else:
            obs[31] = obs[32] = obs[33] = obs[34] = obs[35] = 0.0

        obs[36] = require_key(active_unit, "T") / 10.0
        obs[37] = require_key(active_unit, "ARMOR_SAVE") / 6.0
        # === SECTION 3: Directional Terrain Awareness (32 floats) ===
        # Global Context: [0:16] = 16 floats (ADVANCE_IMPLEMENTATION: +1 for has_advanced)
        # Active Unit Capabilities: [16:38] = 22 floats
        # base_idx = 16 + 22 = 38
        self._encode_directional_terrain(obs, active_unit, game_state, base_idx=38, positions=positions)
        # === SECTION 4: Allied Units (72 floats) ===
        self._encode_allied_units(obs, active_unit, game_state, base_idx=70, positions=positions)
        # === SECTION 5+6: Enemy Units + Valid Targets ===
        valid_targets = self._get_valid_targets(active_unit, game_state, positions=positions)
        self._sort_valid_targets(valid_targets, active_unit, game_state, positions=positions)
        six_enemies = self._get_six_reference_enemies(active_unit, game_state, valid_targets, positions=positions)
        self._encode_enemy_units(obs, active_unit, game_state, base_idx=142, six_enemies=six_enemies, positions=positions)
        self._encode_valid_targets(
            obs, active_unit, game_state, base_idx=274,
            valid_targets=valid_targets, six_enemies=six_enemies, positions=positions
        )
        # === SECTION 7: Phase 2 — Rule features + Zone intent context (obs[314:357]) ===
        # obs_size deja valide en tete (PR4 4e-ii early check) : on est en 357-d.
        self._encode_rule_features(obs, active_unit, game_state, base_idx=self.RULE_FEATURE_BASE_IDX)
        self._encode_macro_intent_context(obs, active_unit, game_state, base_idx=self.RULE_AWARE_MACRO_BASE_IDX, positions=positions)
        return obs

    # ========================================================================
    # PR4 4a — NEW SQUAD OBSERVATION (parallel to build_observation)
    # ========================================================================
    # Structure 108-dim per squad.md PR4 :
    #   [0:16]    Global context (16 floats, identique a build_observation[0:16])
    #   [16:21]   Squad aggregates (5 floats: nb_alive_norm, is_coherent, OC_total,
    #             HP_pct, firepower_estimate)
    #   [21:63]   Top-k=6 fig features (7 features × 6 figs, zero-padded if <6 alive)
    #             col_rel/perception_radius, row_rel/perception_radius, HP%,
    #             weapon_idx_norm, is_fighting_eligible, is_b2b_enemy, is_b2b_ally_in_b2b
    #   [63:108]  5 enemy slots × 9 features
    #             squad_size, HP_total, anchor_col_rel, anchor_row_rel, OC_total,
    #             slot_mask, is_locked_by_friendly_er, value_over_ttk, threat_level
    # PR4 4a : slot mapping = premiers 5 squad_ids ennemis tries par index creation.
    # Slot mapping stable (par HP*OC) defere a PR4 4d.

    SQUAD_OBS_SIZE = 108
    SQUAD_N_GLOBAL = 16
    SQUAD_N_AGG = 5
    SQUAD_TOP_K = 6
    SQUAD_PER_MODEL = 7
    SQUAD_N_ENEMY_SLOTS = 5
    SQUAD_PER_ENEMY_SLOT = 9

    def build_squad_observation(
        self, game_state: Dict[str, Any], active_squad_id: str
    ) -> np.ndarray:
        """Construit l observation 108-dim pour une escouade active (PR4 4a).

        Parallel implementation: ne modifie pas build_observation. La selection
        active_squad vs active_unit est de la responsabilite du caller (decoder PR4).

        Spec : Documentation/TODO/squad.md §"Observation (micro)" et formule
        obs_size = N_global + 92.
        """
        obs = np.zeros(self.SQUAD_OBS_SIZE, dtype=np.float32)
        # C2 cleanup (audit) : message d erreur explicite si l ordre d init est cassé.
        # squad_cache, models_cache, squad_models sont construits par build_units_cache.
        # Si absents, appelez build_units_cache(game_state) avant build_squad_observation.
        if not all(k in game_state for k in ("units_cache", "models_cache", "squad_models", "squad_cache")):
            missing = [k for k in ("units_cache", "models_cache", "squad_models", "squad_cache") if k not in game_state]
            raise RuntimeError(
                f"build_squad_observation requires fully initialized caches. "
                f"Missing: {missing}. Call build_units_cache(game_state) first."
            )
        units_cache = game_state["units_cache"]
        models_cache = game_state["models_cache"]
        squad_models = game_state["squad_models"]
        squad_cache = game_state["squad_cache"]

        if active_squad_id not in units_cache or active_squad_id not in squad_cache:
            return obs  # squad dead/absent -> zero observation
        active_entry = units_cache[active_squad_id]
        active_sq = squad_cache[active_squad_id]
        active_player = int(active_entry["player"])

        # === SECTION 1: Global context (16 floats) — meme structure que build_observation ===
        current_player = int(require_key(game_state, "current_player"))
        obs[0] = 1.0 if current_player == active_player else 0.0
        phase_encoding = {"deployment": 0.0, "command": 0.0, "move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}
        obs[1] = phase_encoding.get(game_state.get("phase", "command"), 0.0)
        obs[2] = min(1.0, int(game_state.get("turn", 0)) / 5.0)
        obs[3] = min(1.0, int(game_state.get("episode_steps", 0)) / 100.0)
        # HP pct du squad actif
        model_count_at_start = max(1, int(active_sq.get("model_count_at_start", 1)))
        # HP_MAX par modele (mono-fig: HP_MAX direct; multi-fig: somme via models_cache)
        total_hp_pool = 0
        for mid in squad_models.get(active_squad_id, []):
            m = models_cache.get(mid)
            if m is not None:
                total_hp_pool += int(m["HP_MAX"])
        if total_hp_pool == 0:
            total_hp_pool = model_count_at_start
        obs[4] = min(1.0, int(active_entry["HP_CUR"]) / float(total_hp_pool)) if total_hp_pool > 0 else 0.0
        obs[5] = 1.0 if active_squad_id in game_state.get("units_moved", set()) else 0.0
        obs[6] = 1.0 if active_squad_id in game_state.get("units_shot", set()) else 0.0
        obs[7] = 1.0 if active_squad_id in game_state.get("units_attacked", set()) else 0.0
        obs[8] = 1.0 if active_squad_id in game_state.get("units_advanced", set()) else 0.0
        # alive friendlies/enemies normalises
        max_nearby = self.max_nearby_units
        alive_friendlies = sum(
            1 for sid, e in units_cache.items() if int(e["player"]) == active_player
        )
        alive_enemies = sum(
            1 for sid, e in units_cache.items() if int(e["player"]) != active_player
        )
        obs[9] = alive_friendlies / max(1, max_nearby)
        obs[10] = alive_enemies / max(1, max_nearby)
        # Objective control (5 floats) — reuse existing encoder mais avec active_unit synthetique
        synthetic_active = {
            "id": active_squad_id,
            "player": active_player,
            "col": int(active_entry["col"]),
            "row": int(active_entry["row"]),
        }
        positions = {uid: (int(e["col"]), int(e["row"])) for uid, e in units_cache.items()}
        try:
            self._encode_objective_control(obs, synthetic_active, game_state, base_idx=11, positions=positions)
        except Exception:
            pass  # objectifs absents → zero (PR4 acceptable, sera plus strict en PR5)

        # === SECTION 2: Squad aggregates (5 floats) [16:21] ===
        nb_alive = int(active_sq["model_count"])
        obs[16] = min(1.0, nb_alive / float(model_count_at_start))
        obs[17] = 1.0 if active_sq.get("is_coherent", False) else 0.0
        obs[18] = min(1.0, int(active_sq.get("oc_total", 0)) / 10.0)
        obs[19] = min(1.0, int(active_entry["HP_CUR"]) / float(total_hp_pool)) if total_hp_pool > 0 else 0.0
        # Firepower estimate : sum(P(hit)*P(wound)*D) sur les armes RNG selectionnees,
        # vs cible generique T=4, Sv=4 (normalisation /10)
        firepower = 0.0
        for mid in squad_models.get(active_squad_id, []):
            m = models_cache.get(mid)
            if m is None:
                continue
            weapons = m.get("RNG_WEAPONS", [])
            sel = m.get("selectedRngWeaponIndex")
            if not weapons or sel is None or not (0 <= int(sel) < len(weapons)):
                continue
            w = weapons[int(sel)]
            if not isinstance(w, dict):
                continue
            bs = int(w.get("ATK", w.get("BS", 4)))
            s = int(w.get("STR", w.get("S", 4)))
            ap = int(w.get("AP", 0))
            dmg_raw = w.get("DMG", 1)
            try:
                d = float(expected_dice_value(dmg_raw, "obs_firepower"))
            except Exception:
                d = float(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1.0
            try:
                nb_raw = w.get("NB", 1)
                n = float(expected_dice_value(nb_raw, "obs_firepower_nb"))
            except Exception:
                n = float(nb_raw) if isinstance(nb_raw, (int, float)) else 1.0
            p_hit = max(0.0, (7 - bs) / 6.0) if bs <= 6 else 0.0
            wth = wound_threshold(s, 4)
            p_wound = max(0.0, (7 - wth) / 6.0)
            sv = save_threshold(4, 7, ap)
            p_fail = max(0.0, (sv - 1) / 6.0) if sv < 7 else 1.0
            firepower += n * p_hit * p_wound * p_fail * d
        obs[20] = min(1.0, firepower / 10.0)

        # === SECTION 3: Top-k=6 fig features (7 × 6 = 42 floats) [21:63] ===
        cx = float(active_sq.get("centroid_col", active_entry["col"]))
        cy = float(active_sq.get("centroid_row", active_entry["row"]))
        pr = float(max(1, self.perception_radius))
        # Calcule once : fighting_models + B2B with enemies
        fighting_set: set = set()
        try:
            fighting_set = set(get_fighting_models(game_state, active_squad_id))
        except Exception:
            fighting_set = set()
        # Enemy positions pour B2B
        enemy_positions: List[Tuple[int, int]] = []
        for sid, e in units_cache.items():
            if int(e["player"]) == active_player:
                continue
            for mid in squad_models.get(sid, []):
                m = models_cache.get(mid)
                if m is not None:
                    enemy_positions.append((int(m["col"]), int(m["row"])))
        alive_mids = [m for m in squad_models.get(active_squad_id, []) if m in models_cache]
        for k_idx in range(self.SQUAD_TOP_K):
            base = 21 + k_idx * self.SQUAD_PER_MODEL
            if k_idx >= len(alive_mids):
                continue  # zero-padded
            mid = alive_mids[k_idx]
            m = models_cache[mid]
            col_rel = (int(m["col"]) - cx) / pr
            row_rel = (int(m["row"]) - cy) / pr
            obs[base + 0] = max(-1.0, min(1.0, col_rel))
            obs[base + 1] = max(-1.0, min(1.0, row_rel))
            obs[base + 2] = int(m["HP_CUR"]) / max(1, int(m["HP_MAX"]))
            sel_idx = m.get("selectedCcWeaponIndex")
            obs[base + 3] = (int(sel_idx) if sel_idx is not None else 0) / 5.0
            obs[base + 4] = 1.0 if mid in fighting_set else 0.0
            # B2B with enemy (condition 1 simplified : distance == 1)
            mc = int(m["col"]); mr = int(m["row"])
            is_b2b_enemy = any(
                calculate_hex_distance(mc, mr, ec, er) == BASE_TO_BASE_SUBHEX
                for ec, er in enemy_positions
            )
            obs[base + 5] = 1.0 if is_b2b_enemy else 0.0
            # B2B with ally that is B2B with enemy (buddy rule features)
            is_b2b_ally_in_b2b = False
            if not is_b2b_enemy:
                for other_mid in alive_mids:
                    if other_mid == mid:
                        continue
                    om = models_cache[other_mid]
                    oc, or_ = int(om["col"]), int(om["row"])
                    if calculate_hex_distance(mc, mr, oc, or_) != BASE_TO_BASE_SUBHEX:
                        continue
                    if any(
                        calculate_hex_distance(oc, or_, ec, er) == BASE_TO_BASE_SUBHEX
                        for ec, er in enemy_positions
                    ):
                        is_b2b_ally_in_b2b = True
                        break
            obs[base + 6] = 1.0 if is_b2b_ally_in_b2b else 0.0

        # === SECTION 4: 5 enemy slots × 9 features = 45 floats [63:108] ===
        # PR4 4a : slot mapping naif (ordre de creation). Stable mapping HP*OC = PR4 4d.
        enemy_squads = sorted(
            (sid for sid, e in units_cache.items() if int(e["player"]) != active_player),
            key=lambda s: str(s)
        )
        er_threshold = get_engagement_range_subhex(game_state)
        # ER zone des alliés (pour is_locked_by_friendly_er)
        ally_positions: List[Tuple[int, int]] = []
        for sid, e in units_cache.items():
            if int(e["player"]) != active_player:
                continue
            for mid in squad_models.get(sid, []):
                m = models_cache.get(mid)
                if m is not None:
                    ally_positions.append((int(m["col"]), int(m["row"])))
        # Pour value_over_ttk et threat_level : utiliser arme RNG[0] de l active squad
        active_sample_weapon: Optional[Dict[str, Any]] = None
        if alive_mids:
            a_sample = models_cache[alive_mids[0]]
            a_weapons = a_sample.get("RNG_WEAPONS", [])
            a_sel = a_sample.get("selectedRngWeaponIndex")
            if a_weapons and a_sel is not None and 0 <= int(a_sel) < len(a_weapons):
                active_sample_weapon = a_weapons[int(a_sel)]
        for slot_i in range(self.SQUAD_N_ENEMY_SLOTS):
            base = 63 + slot_i * self.SQUAD_PER_ENEMY_SLOT
            if slot_i >= len(enemy_squads):
                continue  # slot vide (mask=0)
            esid = enemy_squads[slot_i]
            e_entry = units_cache[esid]
            e_sq = squad_cache.get(esid, {})
            e_mids = [m for m in squad_models.get(esid, []) if m in models_cache]
            e_size = len(e_mids)
            e_hp_total = int(e_entry.get("HP_CUR", 0))
            obs[base + 0] = min(1.0, e_size / 10.0)
            obs[base + 1] = min(1.0, e_hp_total / 30.0)
            obs[base + 2] = max(-1.0, min(1.0, (int(e_entry["col"]) - cx) / pr))
            obs[base + 3] = max(-1.0, min(1.0, (int(e_entry["row"]) - cy) / pr))
            obs[base + 4] = min(1.0, int(e_sq.get("oc_total", 0)) / 10.0)
            obs[base + 5] = 1.0  # slot_mask (alive)
            # is_locked_by_friendly_er : au moins une fig de e en ER d un allié
            is_locked = False
            for em in e_mids:
                mm = models_cache[em]
                ec_, er_ = int(mm["col"]), int(mm["row"])
                if any(calculate_hex_distance(ec_, er_, ac, ar) <= er_threshold for ac, ar in ally_positions):
                    is_locked = True
                    break
            obs[base + 6] = 1.0 if is_locked else 0.0
            # value_over_ttk = VALUE_cible / TTK, normalise (cap a 1.0)
            value_over_ttk = 0.0
            threat_level = 0.0
            if active_sample_weapon is not None and isinstance(active_sample_weapon, dict) and e_mids:
                t_target = int(models_cache[e_mids[0]].get("T", 4))
                sv_target = int(models_cache[e_mids[0]].get("ARMOR_SAVE", 7))
                invul_target = int(models_cache[e_mids[0]].get("INVUL_SAVE", 7))
                bs = int(active_sample_weapon.get("ATK", active_sample_weapon.get("BS", 4)))
                s = int(active_sample_weapon.get("STR", active_sample_weapon.get("S", 4)))
                ap = int(active_sample_weapon.get("AP", 0))
                dmg_raw = active_sample_weapon.get("DMG", 1)
                try:
                    d_mean = float(expected_dice_value(dmg_raw, "obs_ttk_dmg"))
                except Exception:
                    d_mean = float(dmg_raw) if isinstance(dmg_raw, (int, float)) else 1.0
                p_hit = max(0.0, (7 - bs) / 6.0) if bs <= 6 else 0.0
                wth = wound_threshold(s, t_target)
                p_wound = max(0.0, (7 - wth) / 6.0)
                sv_th = save_threshold(sv_target, invul_target, ap)
                p_fail = max(0.0, (sv_th - 1) / 6.0) if sv_th < 7 else 1.0
                expected_dmg_per_attack = p_hit * p_wound * p_fail * d_mean
                if expected_dmg_per_attack > 0:
                    # Approx VALUE de la cible : somme points_per_hp * HP_total
                    try:
                        ppl = float(models_cache[e_mids[0]].get("points_per_hp", 0.0))
                    except Exception:
                        ppl = 0.0
                    e_value = ppl * e_hp_total
                    # TTK = HP_total / expected_dmg_per_attack (en nb attaques moyennes)
                    ttk = max(1.0, e_hp_total / expected_dmg_per_attack)
                    value_over_ttk = min(1.0, e_value / (ttk * 50.0))  # /50 normalisation
            # threat_level = expected damage des armes ennemies sur notre escouade
            if e_mids:
                e_sample = models_cache[e_mids[0]]
                e_weapons = e_sample.get("RNG_WEAPONS", [])
                e_sel = e_sample.get("selectedRngWeaponIndex")
                if e_weapons and e_sel is not None and 0 <= int(e_sel) < len(e_weapons):
                    ew = e_weapons[int(e_sel)]
                    if isinstance(ew, dict) and alive_mids:
                        # vs notre T/Sv (premier modele actif)
                        our_t = int(models_cache[alive_mids[0]].get("T", 4))
                        our_sv = int(models_cache[alive_mids[0]].get("ARMOR_SAVE", 7))
                        our_inv = int(models_cache[alive_mids[0]].get("INVUL_SAVE", 7))
                        e_bs = int(ew.get("ATK", ew.get("BS", 4)))
                        e_s = int(ew.get("STR", ew.get("S", 4)))
                        e_ap = int(ew.get("AP", 0))
                        e_dmg_raw = ew.get("DMG", 1)
                        try:
                            e_d = float(expected_dice_value(e_dmg_raw, "obs_threat_dmg"))
                        except Exception:
                            e_d = float(e_dmg_raw) if isinstance(e_dmg_raw, (int, float)) else 1.0
                        try:
                            e_nb = float(expected_dice_value(ew.get("NB", 1), "obs_threat_nb"))
                        except Exception:
                            e_nb = float(ew.get("NB", 1)) if isinstance(ew.get("NB", 1), (int, float)) else 1.0
                        e_phit = max(0.0, (7 - e_bs) / 6.0) if e_bs <= 6 else 0.0
                        e_wth = wound_threshold(e_s, our_t)
                        e_pw = max(0.0, (7 - e_wth) / 6.0)
                        e_svth = save_threshold(our_sv, our_inv, e_ap)
                        e_pf = max(0.0, (e_svth - 1) / 6.0) if e_svth < 7 else 1.0
                        threat_level = min(1.0, e_size * e_nb * e_phit * e_pw * e_pf * e_d / 20.0)
            obs[base + 7] = value_over_ttk
            obs[base + 8] = threat_level

        return obs

    def build_observation_for_unit(self, game_state: Dict[str, Any], unit_id: str) -> np.ndarray:
        """
        Build observation for a specific unit without reordering activation pools.
        """
        unit = get_unit_by_id(str(unit_id), game_state)
        if unit is None:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if not is_unit_alive(str(unit["id"]), game_state):
            raise ValueError(f"Unit {unit_id} is not alive for observation")
        units_cache = require_key(game_state, "units_cache")
        if str(unit_id) not in units_cache:
            raise KeyError(f"Unit {unit_id} missing from units_cache for observation")
        return self.build_observation(game_state, active_unit_override=unit)
    
    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    def _encode_objective_control(self, obs: np.ndarray, active_unit: Dict[str, Any],
                                   game_state: Dict[str, Any], base_idx: int,
                                   positions: Dict[str, Tuple[int, int]]):
        """
        Encode objective control status for each objective.
        5 floats for 5 objectives (obs[10:15]).

        Each objective encoded as:
        - 1.0 = We control this objective
        - 0.0 = Contested or uncontrolled
        - -1.0 = Enemy controls this objective

        This lets the agent know the current objective state for strategic planning.
        """
        objectives = require_key(game_state, "objectives")
        my_player = active_unit["player"]

        for i in range(5):  # Max 5 objectives
            if i < len(objectives):
                objective = objectives[i]
                obj_hexes = require_key(objective, "hexes")

                # Convert hex list to set of tuples for fast lookup
                hex_set = set(tuple(h) for h in obj_hexes)

                # Calculate OC per player for this objective
                my_oc = 0
                enemy_oc = 0

                for unit in game_state["units"]:
                    if not is_unit_alive(str(unit["id"]), game_state):
                        continue

                    unit_pos = positions[str(unit["id"])]
                    if unit_pos in hex_set:
                        oc = require_key(unit, "OC")
                        if unit["player"] == my_player:
                            my_oc += oc
                        else:
                            enemy_oc += oc

                # Determine control status
                if my_oc > enemy_oc:
                    obs[base_idx + i] = 1.0  # We control
                elif enemy_oc > my_oc:
                    obs[base_idx + i] = -1.0  # Enemy controls
                else:
                    obs[base_idx + i] = 0.0  # Contested/empty
            else:
                obs[base_idx + i] = 0.0  # No objective in this slot

    def _encode_rule_features(
        self,
        obs: np.ndarray,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        base_idx: int,
    ) -> None:
        """
        Encode explicit rule features from config/unit_rules.json and config/weapon_rules.json.
        """
        feature_idx = base_idx

        # 1) Unit rules: 12 binary features (alias-aware via shared helper)
        for rule_id in self._UNIT_RULE_FEATURE_IDS:
            obs[feature_idx] = 1.0 if unit_has_rule_effect(active_unit, rule_id) else 0.0
            feature_idx += 1

        # 2) Movement keyword: FLY
        obs[feature_idx] = 1.0 if self._unit_has_keyword(active_unit, "fly") else 0.0
        feature_idx += 1

        # 3) Invulnerable save features (availability + quality)
        invul_save = require_key(active_unit, "INVUL_SAVE")
        if not isinstance(invul_save, int):
            raise TypeError(f"INVUL_SAVE must be int for unit {active_unit.get('id')}, got {type(invul_save).__name__}")
        if invul_save < 2 or invul_save > 7:
            raise ValueError(f"INVUL_SAVE must be in [2, 7] for unit {active_unit.get('id')}, got {invul_save}")
        has_invul = invul_save < 7
        obs[feature_idx] = 1.0 if has_invul else 0.0
        feature_idx += 1
        obs[feature_idx] = ((7 - invul_save) / 5.0) if has_invul else 0.0
        feature_idx += 1

        # 4) Weapon rules from selected ranged + melee weapons
        weapon_rule_features = self._collect_selected_weapon_rule_features(active_unit)
        for rule_id in self._WEAPON_RULE_FEATURE_IDS:
            obs[feature_idx] = weapon_rule_features[rule_id]
            feature_idx += 1

        if feature_idx != base_idx + self.RULE_FEATURE_COUNT:
            raise ValueError(
                f"Rule feature encoding size mismatch: expected {self.RULE_FEATURE_COUNT}, "
                f"got {feature_idx - base_idx}"
            )

    def _unit_has_keyword(self, unit: Dict[str, Any], keyword_id: str) -> bool:
        """
        Check unit keyword presence in UNIT_KEYWORDS list.
        """
        unit_keywords = require_key(unit, "UNIT_KEYWORDS")
        if not isinstance(unit_keywords, list):
            raise TypeError(f"UNIT_KEYWORDS must be list for unit {unit.get('id')}")
        target = keyword_id.strip().lower()
        for keyword_entry in unit_keywords:
            if not isinstance(keyword_entry, dict):
                raise TypeError(f"UNIT_KEYWORDS entry must be dict for unit {unit.get('id')}: {keyword_entry!r}")
            current_id = require_key(keyword_entry, "keywordId")
            if not isinstance(current_id, str) or not current_id.strip():
                raise ValueError(f"Invalid keywordId in UNIT_KEYWORDS for unit {unit.get('id')}: {current_id!r}")
            if current_id.strip().lower() == target:
                return True
        return False

    def _collect_selected_weapon_rule_features(
        self,
        unit: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        Build dense feature map for weapon rules from selected ranged/melee weapons.
        For parameterized rules, stores normalized parameter in [0, 1].
        For boolean rules, stores 1.0 when present.
        """
        from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon

        features = {rule_id: 0.0 for rule_id in self._WEAPON_RULE_FEATURE_IDS}
        known_rule_ids = set(self._WEAPON_RULE_FEATURE_IDS)

        selected_weapons = [
            get_selected_ranged_weapon(unit),
            get_selected_melee_weapon(unit),
        ]
        for weapon in selected_weapons:
            if weapon is None:
                continue
            weapon_rules = require_key(weapon, "WEAPON_RULES")
            if not isinstance(weapon_rules, list):
                raise TypeError(f"WEAPON_RULES must be list for weapon {weapon.get('display_name')}")
            for raw_rule in weapon_rules:
                raw_rule_name, parameter = self._parse_weapon_rule_entry(raw_rule)
                rule_name = self._WEAPON_RULE_OBS_ALIAS.get(raw_rule_name, raw_rule_name)
                if rule_name not in known_rule_ids:
                    raise KeyError(
                        f"Weapon rule '{raw_rule_name}' (canonical='{rule_name}') not mapped in observation features "
                        f"(unit={unit.get('id')}, weapon={weapon.get('display_name')})"
                    )
                if rule_name in self._WEAPON_RULES_WITH_PARAMETER:
                    if parameter is None:
                        raise ValueError(
                            f"Weapon rule '{rule_name}' requires parameter for "
                            f"unit={unit.get('id')} weapon={weapon.get('display_name')}"
                        )
                    normalized_value = min(1.0, float(parameter) / self._WEAPON_RULE_PARAMETER_NORMALIZATION)
                    if normalized_value > features[rule_name]:
                        features[rule_name] = normalized_value
                else:
                    features[rule_name] = 1.0

        return features

    def _parse_weapon_rule_entry(self, raw_rule: Any) -> Tuple[str, Optional[int]]:
        """
        Parse one weapon rule entry from string or ParsedWeaponRule object.
        """
        if hasattr(raw_rule, "rule"):
            rule_name = getattr(raw_rule, "rule")
            parameter = getattr(raw_rule, "parameter", None)
            if not isinstance(rule_name, str) or not rule_name.strip():
                raise ValueError(f"Invalid ParsedWeaponRule.rule value: {rule_name!r}")
            if parameter is not None:
                if not isinstance(parameter, int):
                    raise TypeError(f"ParsedWeaponRule.parameter must be int or None, got {parameter!r}")
                if parameter <= 0:
                    raise ValueError(f"ParsedWeaponRule.parameter must be > 0, got {parameter}")
            return rule_name.strip(), parameter

        if isinstance(raw_rule, str):
            normalized = raw_rule.strip()
            if not normalized:
                raise ValueError("Weapon rule string cannot be empty")
            if ":" not in normalized:
                return normalized, None
            rule_name, raw_parameter = normalized.split(":", 1)
            clean_rule_name = rule_name.strip()
            clean_parameter = raw_parameter.strip()
            if not clean_rule_name:
                raise ValueError(f"Invalid weapon rule id in entry: {raw_rule!r}")
            try:
                parameter = int(clean_parameter)
            except ValueError as exc:
                raise ValueError(f"Invalid weapon rule parameter '{clean_parameter}' in entry '{raw_rule}'") from exc
            if parameter <= 0:
                raise ValueError(f"Weapon rule parameter must be > 0 in entry '{raw_rule}'")
            return clean_rule_name, parameter

        raise TypeError(f"Unsupported weapon rule entry type: {type(raw_rule).__name__} ({raw_rule!r})")

    def _encode_macro_intent_context(
        self,
        obs: np.ndarray,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        base_idx: int,
        positions: Dict[str, Tuple[int, int]],
    ) -> None:
        """
        Phase 2 zone intent context encoding — obs[346:357], 11 floats.

        Source de vérité pour zone_idx : unit_zone_assignments (peuplé en début de command phase).
        Si la clé est absente → KeyError explicite.

        Layout:
          obs[346:350] = c1_col_norm, c1_row_norm, c1_signal, c1_dist  (candidat 1 : navigation)
          obs[350:354] = c2_col_norm, c2_row_norm, c2_signal, c2_dist  (candidat 2 : objectif zone)
          obs[354:357] = intent_onehot [INVADE, DEFEND, ATTACK]
        """
        unit_zone_assignments = game_state["unit_zone_assignments"]
        unit_id_str = str(active_unit["id"])
        if unit_id_str not in unit_zone_assignments:
            raise KeyError(
                f"unit_zone_assignments missing unit_id={unit_id_str}. "
                "This key must be populated at the start of command phase. "
                "Possible cause: command phase was skipped or unit_zone_assignments was not reset."
            )
        zone_idx = unit_zone_assignments[unit_id_str]

        zone_intents = game_state["zone_intents"]
        intent = zone_intents[zone_idx]
        objectives = game_state["objectives"]
        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        max_range = require_key(game_state, "max_range")

        if board_cols <= 1 or board_rows <= 1:
            raise ValueError(f"Invalid board size for zone intent encoding: cols={board_cols}, rows={board_rows}")
        if max_range <= 0:
            raise ValueError(f"Invalid max_range for zone intent encoding: {max_range}")

        unit_col, unit_row = positions[unit_id_str]

        # Candidat 1: navigation principale selon intent
        if intent == INTENT_INVADE:
            c1_col, c1_row = get_objective_center(objectives[zone_idx])
            c1_signal = -get_objective_control(zone_idx, game_state)  # inversé : zone ennemie → +1.0 (priorité invasion)
        elif intent == INTENT_DEFEND:
            c1_col, c1_row = get_objective_center(objectives[zone_idx])
            c1_signal = get_objective_control(zone_idx, game_state)
        elif intent == INTENT_ATTACK:
            c1_col, c1_row = get_best_enemy_global(game_state, zone_idx)
            c1_signal = get_best_enemy_score(game_state)
        else:
            raise ValueError(f"Unsupported zone intent value: {intent}")

        c1_dist = calculate_hex_distance(unit_col, unit_row, c1_col, c1_row) / float(max_range)

        # Candidat 2: objectif de la zone (toujours disponible)
        c2_col, c2_row = get_objective_center(objectives[zone_idx])
        c2_signal = get_objective_control(zone_idx, game_state)
        c2_dist = calculate_hex_distance(unit_col, unit_row, c2_col, c2_row) / float(max_range)

        intent_onehot = [
            1.0 if intent == INTENT_INVADE else 0.0,
            1.0 if intent == INTENT_DEFEND else 0.0,
            1.0 if intent == INTENT_ATTACK else 0.0,
        ]

        obs[base_idx + 0] = c1_col / float(board_cols - 1)
        obs[base_idx + 1] = c1_row / float(board_rows - 1)
        obs[base_idx + 2] = c1_signal
        obs[base_idx + 3] = c1_dist
        obs[base_idx + 4] = c2_col / float(board_cols - 1)
        obs[base_idx + 5] = c2_row / float(board_rows - 1)
        obs[base_idx + 6] = c2_signal
        obs[base_idx + 7] = c2_dist
        obs[base_idx + 8] = intent_onehot[0]
        obs[base_idx + 9] = intent_onehot[1]
        obs[base_idx + 10] = intent_onehot[2]

    def _get_active_unit_for_observation(self, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get the active unit for observation encoding.
        AI_TURN.md COMPLIANCE: Uses activation pools (single source of truth).
        """
        current_phase = game_state["phase"]
        current_player = int(game_state["current_player"]) if game_state["current_player"] is not None else None
        if current_player is None:
            raise ValueError("game_state['current_player'] must be set for observation")
        units_cache = require_key(game_state, "units_cache")
        
        # Get first eligible unit from current phase pool
        if current_phase == "move":
            pool = require_key(game_state, "move_activation_pool")
        elif current_phase == "shoot":
            pool = require_key(game_state, "shoot_activation_pool")
        elif current_phase == "charge":
            pool = require_key(game_state, "charge_activation_pool")
        elif current_phase == "fight":
            fight_subphase = require_key(game_state, "fight_subphase")
            if fight_subphase == "charging":
                pool = require_key(game_state, "charging_activation_pool")
            elif fight_subphase in ("alternating_active", "cleanup_active"):
                pool = require_key(game_state, "active_alternating_activation_pool")
            elif fight_subphase in ("alternating_non_active", "cleanup_non_active"):
                pool = require_key(game_state, "non_active_alternating_activation_pool")
            elif fight_subphase is None:
                raise ValueError("fight_subphase is None while phase is fight")
            else:
                raise KeyError(f"Unknown fight_subphase: {fight_subphase}")
        elif current_phase == "command":
            # Return first alive unit of current player as reference for zone intent observation.
            # Zone intents are global (not per-unit), but the obs builder needs a unit to encode
            # obs[346:357] (c1/c2 candidates, intent one-hot). Any alive friendly unit works.
            for unit in game_state["units"]:
                if unit.get("player") == current_player and is_unit_alive(str(unit["id"]), game_state):
                    return unit
            return None
        elif current_phase == "deployment":
            deployment_state = require_key(game_state, "deployment_state")
            current_deployer = int(require_key(deployment_state, "current_deployer"))
            deployable_units = require_key(deployment_state, "deployable_units")
            deployable_list = deployable_units.get(current_deployer, deployable_units.get(str(current_deployer)))
            if deployable_list is None:
                raise KeyError(f"deployable_units missing player {current_deployer}")
            for unit_id in deployable_list:
                unit = get_unit_by_id(str(unit_id), game_state)
                if unit and is_unit_alive(str(unit["id"]), game_state):
                    return unit
            return None
        else:
            raise KeyError(f"game_state phase must be move/shoot/charge/fight/command/deployment, got: {current_phase}")
        
        # Get first unit from pool that belongs to current player (pool contains only alive units)
        for unit_id in pool:
            unit = get_unit_by_id(str(unit_id), game_state)
            if not unit:
                continue
            if current_phase == "fight":
                return unit
            if not is_unit_alive(str(unit["id"]), game_state):
                continue
            cache_entry = units_cache.get(str(unit_id))
            if cache_entry is None:
                raise KeyError(f"Unit {unit_id} missing from units_cache")
            unit_player = require_key(cache_entry, "player")
            try:
                unit_player = int(unit_player)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid player value in units_cache for unit {unit_id}: {unit_player}") from exc
            if unit_player == current_player:
                return unit
        
        if current_phase == "shoot":
            # No eligible unit for current player in shoot pool; allow empty observation
            return None
        raise ValueError(f"No active unit found in pool for player {current_player} (phase={current_phase})")
    
    def _encode_directional_terrain(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int,
                                   positions: Dict[str, Tuple[int, int]]):
        """
        Encode terrain awareness in 8 cardinal directions.
        32 floats = 8 directions × 4 features per direction.
        """
        perception_radius = self.perception_radius
        # 8 directions: N, NE, E, SE, S, SW, W, NW
        directions = [
            (0, -1),   # N
            (1, -1),   # NE
            (1, 0),    # E
            (1, 1),    # SE
            (0, 1),    # S
            (-1, 1),   # SW
            (-1, 0),   # W
            (-1, -1)   # NW
        ]

        active_col, active_row = positions[str(active_unit["id"])]
        board_cols = game_state["board_cols"]
        board_rows = game_state["board_rows"]
        wall_edge_topology = game_state.get("wall_edge_topology")

        for dir_idx, (dx, dy) in enumerate(directions):
            feature_base = base_idx + dir_idx * 4

            # Wall and edge: use precomputed topology when available (PERF: avoids 8×60 wall loops + 8×4 edge lookups)
            if (
                wall_edge_topology is not None
                and isinstance(board_cols, int)
                and isinstance(board_rows, int)
                and 0 <= active_col < board_cols
                and 0 <= active_row < board_rows
            ):
                hex_idx = active_row * board_cols + active_col
                wall_dist = float(wall_edge_topology[hex_idx, dir_idx, 0])
                edge_dist = float(wall_edge_topology[hex_idx, dir_idx, 1])
            else:
                wall_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "wall", positions)
                edge_dist = self._find_edge_distance(active_unit, dx, dy, game_state, positions)

            friendly_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "friendly", positions)
            enemy_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "enemy", positions)

            # Normalize by perception radius
            obs[feature_base + 0] = min(1.0, wall_dist / perception_radius)
            obs[feature_base + 1] = min(1.0, friendly_dist / perception_radius)
            obs[feature_base + 2] = min(1.0, enemy_dist / perception_radius)
            obs[feature_base + 3] = min(1.0, edge_dist / perception_radius)
    
    def _encode_allied_units(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int,
                            positions: Dict[str, Tuple[int, int]]):
        """
        Encode up to 6 allied units within perception radius.
        72 floats = 6 units × 12 features per unit.
        
        Features per ally (12 floats):
        0. relative_col, 1. relative_row (egocentric position)
        2. hp_ratio (HP_CUR / HP_MAX)
        3. hp_capacity (HP_MAX normalized)
        4. has_moved (1.0 if unit moved this turn)
        5. movement_direction (0.0-1.0: fled far -> charged at me)
        6. distance_normalized (distance / perception_radius)
        7. combat_mix_score (0.1-0.9: melee -> ranged specialist)
        8. ranged_favorite_target (0.0-1.0: swarm -> monster)
        9. melee_favorite_target (0.0-1.0: swarm -> monster)
        10. can_shoot_my_target (1.0 if ally can shoot my current target)
        11. danger_level (0.0-1.0: threat to my survival)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.
        """
        perception_radius = self.perception_radius
        # Get all allied units within perception radius
        allies = []
        for other_unit in game_state["units"]:
            # Phase 2: HP in cache only; is_unit_alive implies present in cache
            if not is_unit_alive(str(other_unit["id"]), game_state):
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            if "player" not in other_unit:
                raise KeyError(f"Unit missing required 'player' field: {other_unit}")
            if other_unit["player"] != active_unit["player"]:
                continue  # Skip enemies

            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")

            active_col, active_row = positions[str(active_unit["id"])]
            other_col, other_row = positions[str(other_unit["id"])]
            distance = calculate_hex_distance(
                active_col, active_row,
                other_col, other_row
            )

            if distance <= perception_radius:
                allies.append((distance, other_unit))
        
        # Sort by priority: closer > wounded > can_still_act
        def ally_priority(item):
            distance, unit = item
            hp_cur = get_hp_from_cache(str(unit["id"]), game_state)
            hp_ratio = (hp_cur if hp_cur is not None else 0) / max(1, unit["HP_MAX"])
            has_acted = 1.0 if unit["id"] in game_state["units_moved"] else 0.0
            
            # Priority: closer units (higher), wounded (higher), not acted (higher)
            return (
                -distance * 10,  # Closer = higher priority
                -(1.0 - hp_ratio) * 5,  # More wounded = higher priority
                -has_acted  # Not acted = higher priority
            )
        
        allies.sort(key=ally_priority, reverse=True)
        
        # Encode up to 6 allies
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 12
            
            if i < len(allies):
                distance, ally = allies[i]
                
                # Feature 0-1: Relative position (egocentric)
                ally_col, ally_row = positions[str(ally["id"])]
                active_col, active_row = positions[str(active_unit["id"])]
                rel_col = (ally_col - active_col) / perception_radius
                rel_row = (ally_row - active_row) / perception_radius
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                
                # Feature 2-3: Health status (Phase 2: HP from cache; dead = 0)
                hp_cur = get_hp_from_cache(str(ally["id"]), game_state)
                obs[feature_base + 2] = (hp_cur if hp_cur is not None else 0) / max(1, ally["HP_MAX"])
                obs[feature_base + 3] = ally["HP_MAX"] / 10.0
                
                # Feature 4: Has moved
                obs[feature_base + 4] = 1.0 if ally["id"] in game_state["units_moved"] else 0.0
                
                # Feature 5: Movement direction (temporal behavior)
                obs[feature_base + 5] = self._calculate_movement_direction(ally, active_unit, game_state, positions)
                
                # Feature 6: Distance normalized
                obs[feature_base + 6] = distance / perception_radius
                
                # Feature 7: Combat mix score
                obs[feature_base + 7] = self._calculate_combat_mix_score(ally)
                
                # Feature 8-9: Favorite targets
                # PERFORMANCE: Calculate once, use twice (was called twice per ally)
                fav_target = self._calculate_favorite_target(ally)
                obs[feature_base + 8] = fav_target
                obs[feature_base + 9] = fav_target
                
                # Feature 10: Can shoot my target (placeholder - requires current target context)
                obs[feature_base + 10] = 0.0
                
                # Feature 11: Danger level (threat to my survival)
                danger = self._calculate_danger_probability(active_unit, ally, game_state, positions)
                obs[feature_base + 11] = danger
            else:
                # Padding for empty slots
                for j in range(12):
                    obs[feature_base + j] = 0.0
    
    def _encode_enemy_units(
        self,
        obs: np.ndarray,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        base_idx: int,
        six_enemies: Optional[List[tuple]] = None,
        positions: Optional[Dict[str, Tuple[int, int]]] = None,
    ):
        """
        Encode up to 6 enemy units within perception radius.
        132 floats = 6 units × 22 features per unit. - MULTIPLE_WEAPONS_IMPLEMENTATION.md

        Asymmetric design: MORE complete information about enemies for tactical decisions.

        Uses los_topology directly for visibility features (O(1) per pair, no los_cache needed).

        Features per enemy (22 floats):
        0. relative_col, 1. relative_row (egocentric position)
        2. distance_normalized (distance / perception_radius)
        3. hp_ratio (HP_CUR / HP_MAX)
        4. hp_capacity (HP_MAX normalized)
        5. has_moved, 6. movement_direction (temporal behavior)
        7. has_shot, 8. has_charged, 9. has_attacked
        10. is_valid_target (1.0 if can be shot/attacked now)
        11. best_weapon_index (0-2, normalized / 2.0) - NOUVEAU
        12. best_kill_probability (0.0-1.0) - NOUVEAU
        13. danger_to_me (0.0-1.0: chance they kill ME next turn) - DÉCALÉ
        14. visibility_to_allies (how many allies can see this enemy) - DÉCALÉ
        15. combined_friendly_threat (total threat from all allies to this enemy) - DÉCALÉ
        16. melee_charge_preference (0.0-1.0: TTK melee vs range for best ally) - AMÉLIORÉ POST-ÉTAPE 9
        17. target_efficiency (0.0-1.0: TTK with best weapon) - AMÉLIORÉ POST-ÉTAPE 9
        18. is_adjacent (1.0 if within melee range) - INCHANGÉ
        19. combat_mix_score (enemy's ranged/melee preference) - DÉCALÉ
        20. favorite_target (enemy's preferred target type) - DÉCALÉ

        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.
        When six_enemies is provided (from build_observation), uses that list so obs[141:273]
        matches enemy_index_map in _encode_valid_targets (avoids "Required key 'X' missing").
        """
        perception_radius = self.perception_radius
        if positions is None:
            positions = {uid: (e["col"], e["row"]) for uid, e in require_key(game_state, "units_cache").items()}
        if six_enemies is not None:
            enemies = six_enemies
        else:
            enemies = []
            for other_unit in game_state["units"]:
                if not is_unit_alive(str(other_unit["id"]), game_state):
                    continue
                if "player" not in other_unit:
                    raise KeyError(f"Unit missing required 'player' field: {other_unit}")
                if other_unit["player"] == active_unit["player"]:
                    continue
                if "col" not in other_unit or "row" not in other_unit:
                    raise KeyError(f"Unit missing required position fields: {other_unit}")
                active_col, active_row = positions[str(active_unit["id"])]
                other_col, other_row = positions[str(other_unit["id"])]
                d = calculate_hex_distance(active_col, active_row, other_col, other_row)
                if d <= perception_radius:
                    enemies.append((d, other_unit))
            from engine.utils.weapon_helpers import get_max_ranged_range
            from engine.spatial_relations import get_engagement_zone

            def _enemy_priority(item):
                distance, unit = item
                hp_cur = get_hp_from_cache(str(unit["id"]), game_state)
                hp_ratio = (hp_cur if hp_cur is not None else 0) / max(1, unit["HP_MAX"])
                can_attack = 0.0
                max_range = get_max_ranged_range(unit)
                _ez_ep = get_engagement_zone(game_state)
                _uc_ep = require_key(game_state, "units_cache")
                _ae_ep = _uc_ep.get(str(active_unit["id"]))
                _ue_ep = _uc_ep.get(str(unit["id"]))
                _ac_ep, _ar_ep = positions[str(active_unit["id"])]
                _ec_ep, _er_ep = positions[str(unit["id"])]
                _fp_dist = calculate_hex_distance(_ac_ep, _ar_ep, _ec_ep, _er_ep)
                if max_range > 0 and _fp_dist <= max_range:
                    can_attack = 1.0
                elif _fp_dist <= _ez_ep:
                    can_attack = 1.0
                return (
                    1000,
                    -((1.0 - hp_ratio) * 200),
                    can_attack * 100,
                    -distance * 10,
                )

            enemies.sort(key=_enemy_priority, reverse=True)
        
        # Pre-compute allies list once (same for all enemies)
        units_cache = require_key(game_state, "units_cache")
        active_player = int(active_unit["player"]) if active_unit["player"] is not None else None
        if active_player is None:
            raise ValueError(f"Active unit missing player: {active_unit}")
        allies_list = []
        for ally_id, cache_entry in units_cache.items():
            if int(cache_entry["player"]) != active_player:
                continue
            ally = get_unit_by_id(str(ally_id), game_state)
            if ally is None:
                raise KeyError(f"Unit {ally_id} missing from game_state['units']")
            allies_list.append((str(ally_id), ally))

        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 22
            if i < len(enemies):
                distance, enemy = enemies[i]

                # Anchor-based distance for engagement features (approx, sufficient for RL obs)
                from engine.spatial_relations import get_engagement_zone as _gez_enc
                _enc_acol, _enc_arow = positions[str(active_unit["id"])]
                _enc_ecol, _enc_erow = positions[str(enemy["id"])]
                _enc_ez = _gez_enc(game_state)
                _enc_fp_dist = calculate_hex_distance(_enc_acol, _enc_arow, _enc_ecol, _enc_erow)

                # Feature 0-2: Position and distance
                enemy_col, enemy_row = positions[str(enemy["id"])]
                active_col, active_row = positions[str(active_unit["id"])]
                rel_col = (enemy_col - active_col) / perception_radius
                rel_row = (enemy_row - active_row) / perception_radius
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = distance / perception_radius
                
                # Feature 3-4: Health status (Phase 2: HP from cache; dead = 0)
                hp_cur = get_hp_from_cache(str(enemy["id"]), game_state)
                obs[feature_base + 3] = (hp_cur if hp_cur is not None else 0) / max(1, enemy["HP_MAX"])
                obs[feature_base + 4] = enemy["HP_MAX"] / 10.0
                
                # Feature 5-6: Movement tracking
                obs[feature_base + 5] = 1.0 if enemy["id"] in game_state["units_moved"] else 0.0
                obs[feature_base + 6] = self._calculate_movement_direction(enemy, active_unit, game_state, positions)
                
                # Feature 7-9: Action tracking
                obs[feature_base + 7] = 1.0 if enemy["id"] in game_state["units_shot"] else 0.0
                obs[feature_base + 8] = 1.0 if enemy["id"] in game_state["units_charged"] else 0.0
                obs[feature_base + 9] = 1.0 if enemy["id"] in game_state["units_attacked"] else 0.0
                
                # Feature 10: Is valid target (basic check)
                current_phase = game_state["phase"]
                is_valid = 0.0
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
                from engine.utils.weapon_helpers import get_max_ranged_range
                from engine.spatial_relations import get_engagement_zone
                if current_phase == "shoot":
                    max_range = get_max_ranged_range(active_unit)
                    is_valid = 1.0 if distance <= max_range else 0.0
                elif current_phase == "fight":
                    is_valid = 1.0 if _enc_fp_dist <= _enc_ez else 0.0
                obs[feature_base + 10] = is_valid
                
                # Feature 11-12: best_weapon_index + best_kill_probability (phase-aware)
                # Called ONCE and reused for Feature 17 (was called twice before)
                phase_best_idx, phase_best_kp, phase_is_ranged = self._get_phase_aware_best_weapon_features(
                    active_unit, enemy, game_state
                )
                obs[feature_base + 11] = phase_best_idx / 2.0 if phase_best_idx >= 0 else 0.0
                obs[feature_base + 12] = phase_best_kp
                
                # Feature 13: danger_to_me (était feature 12) - DÉCALÉ
                obs[feature_base + 13] = self._calculate_danger_probability(active_unit, enemy, game_state, positions)
                
                # Features 14-16: Allied coordination (3 floats, était 13-15) - DÉCALÉ
                # visibility_to_allies: use los_topology directly (O(1) per pair, no los_cache needed)
                visibility = 0.0
                combined_threat = 0.0
                enemy_col, enemy_row = positions[str(enemy["id"])]
                for ally_id, ally in allies_list:
                    ally_col, ally_row = positions[ally_id]
                    if self._has_los_from_topology(ally_col, ally_row, enemy_col, enemy_row, game_state):
                        visibility += 1.0
                    combined_threat += self._calculate_danger_probability(enemy, ally, game_state, positions)
                obs[feature_base + 14] = min(1.0, visibility / 6.0)  # visibility_to_allies (était feature 13)
                obs[feature_base + 15] = min(1.0, combined_threat / 5.0)  # combined_friendly_threat (était feature 14)
                
                # Feature 16: melee_charge_preference (0.0-1.0)
                # Uses _best_weapon_cache for O(1) lookups per ally×enemy pair.
                bwc = game_state.get("_best_weapon_cache")
                enemy_hp = get_hp_from_cache(str(enemy["id"]), game_state)
                enemy_hp_f = float(enemy_hp) if enemy_hp and enemy_hp > 0 else 1.0

                best_melee_ttk = float('inf')
                best_range_ttk = float('inf')
                found_melee_ally = False

                enemy_id_str = str(enemy["id"])
                enemy_col, enemy_row = positions[enemy_id_str]
                for ally_id, ally in allies_list:
                    if not ally.get("CC_WEAPONS") or not ally.get("RNG_WEAPONS"):
                        continue

                    ally_col, ally_row = positions[ally_id]
                    if "MOVE" not in ally:
                        raise KeyError(f"Unit missing required 'MOVE' field: {ally}")
                    _charge_max = require_key(require_key(require_key(game_state, "config"), "game_rules"), "charge_max_distance")
                    if calculate_hex_distance(ally_col, ally_row, enemy_col, enemy_row) > ally["MOVE"] + _charge_max:
                        continue

                    if bwc is not None:
                        _, melee_dmg = lookup_best_weapon(bwc, ally_id, enemy_id_str, False)
                        _, range_dmg = lookup_best_weapon(bwc, ally_id, enemy_id_str, True)
                    else:
                        melee_dmg = 0.0
                        range_dmg = 0.0
                    melee_ttk = enemy_hp_f / melee_dmg if melee_dmg > 0 else 100.0
                    range_ttk = enemy_hp_f / range_dmg if range_dmg > 0 else 100.0

                    if melee_ttk < best_melee_ttk:
                        found_melee_ally = True
                        best_melee_ttk = melee_ttk
                        best_range_ttk = range_ttk

                if found_melee_ally and best_range_ttk > 0:
                    ratio = best_range_ttk / best_melee_ttk if best_melee_ttk > 0 else 0.0
                    obs[feature_base + 16] = min(1.0, max(0.0, (ratio - 0.5) * 2.0))
                else:
                    obs[feature_base + 16] = 0.0

                # Feature 17: target_efficiency — derived from phase_best_kp (Feature 11-12)
                # kp = min(1, dmg/hp) → TTK = 1/kp when kp < 1, else 1.0
                if phase_best_idx >= 0 and phase_best_kp > 0.0:
                    ttk = 1.0 if phase_best_kp >= 1.0 else 1.0 / phase_best_kp
                    obs[feature_base + 17] = max(0.0, min(1.0, 1.0 - (ttk - 1.0) / 4.0))
                else:
                    obs[feature_base + 17] = 0.0
                
                # Feature 18: is_adjacent (within engagement zone — footprint-based)
                obs[feature_base + 18] = 1.0 if _enc_fp_dist <= _enc_ez else 0.0
                
                # Features 19-20: Enemy capabilities (2 floats, était 20-22) - DÉCALÉ
                obs[feature_base + 19] = self._calculate_combat_mix_score(enemy)
                # PERFORMANCE: Calculate once, use once (was used twice, now only once)
                enemy_fav_target = self._calculate_favorite_target(enemy)
                obs[feature_base + 20] = enemy_fav_target
            else:
                # Padding for empty slots
                for j in range(22):  # Changed from 23 to 22 (removed 2 features)
                    obs[feature_base + j] = 0.0
        # Get all units within perception radius
        nearby_units = []
        for other_unit in game_state["units"]:
            # Phase 2: HP in cache only; is_unit_alive implies present in cache
            if not is_unit_alive(str(other_unit["id"]), game_state):
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            
            # AI_TURN.md COMPLIANCE: Direct field access
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")

            active_col, active_row = positions[str(active_unit["id"])]
            other_col, other_row = positions[str(other_unit["id"])]
            distance = calculate_hex_distance(
                active_col, active_row,
                other_col, other_row
            )

            if distance <= perception_radius:
                nearby_units.append((distance, other_unit))

        # Sort by distance (prioritize closer units)
        nearby_units.sort(key=lambda x: x[0])
        
        # Encode up to max_nearby_units (default 10, but use 7 for 70 floats)
        max_encoded = 7  # 7 units × 10 features = 70 floats
        for i in range(max_encoded):
            feature_base = base_idx + i * 10
            
            if i < len(nearby_units):
                distance, unit = nearby_units[i]
                
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access with validation
                if "col" not in unit:
                    raise KeyError(f"Nearby unit missing required 'col' field: {unit}")
                if "row" not in unit:
                    raise KeyError(f"Nearby unit missing required 'row' field: {unit}")
                # Phase 2: HP from get_hp_from_cache (validated by is_unit_alive above)
                if "HP_MAX" not in unit:
                    raise KeyError(f"Nearby unit missing required 'HP_MAX' field: {unit}")
                if "player" not in unit:
                    raise KeyError(f"Nearby unit missing required 'player' field: {unit}")
                
                # Relative position (egocentric)
                unit_col, unit_row = positions[str(unit["id"])]
                active_col, active_row = positions[str(active_unit["id"])]
                rel_col = (unit_col - active_col) / perception_radius
                rel_row = (unit_row - active_row) / perception_radius
                dist_norm = distance / perception_radius
                hp_ratio = require_hp_from_cache(str(unit["id"]), game_state) / max(1, unit["HP_MAX"])
                is_enemy = 1.0 if unit["player"] != active_unit["player"] else 0.0
                
                # Threat calculation (potential damage to active unit)
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max damage from all weapons
                rng_weapons = require_key(unit, "RNG_WEAPONS")
                cc_weapons = require_key(unit, "CC_WEAPONS")
                
                max_rng_dmg = max(
                    (expected_dice_value(require_key(w, "DMG"), "nearby_rng_dmg") for w in rng_weapons),
                    default=0.0,
                )
                max_cc_dmg = max(
                    (expected_dice_value(require_key(w, "DMG"), "nearby_cc_dmg") for w in cc_weapons),
                    default=0.0,
                )
                
                if is_enemy > 0.5:
                    threat = max(max_rng_dmg, max_cc_dmg) / 5.0
                else:
                    threat = 0.0
                
                # Defensive type encoding (Swarm=0.25, Troop=0.5, Elite=0.75, Leader=1.0)
                defensive_type = self._encode_defensive_type(unit)
                
                # Offensive type encoding (Melee=0.0, Ranged=1.0)
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use weapon helpers
                from engine.utils.weapon_helpers import get_max_ranged_range
                from engine.spatial_relations import get_engagement_zone
                max_rng_range = get_max_ranged_range(unit)
                melee_range = get_engagement_zone(game_state)
                
                offensive_type = 1.0 if max_rng_range > melee_range else 0.0
                
                # LoS check using topology (only for enemies) - O(1), no los_cache needed
                has_los = 0.0
                if is_enemy > 0.5:
                    active_col, active_row = positions[str(active_unit["id"])]
                    unit_col, unit_row = positions[str(unit["id"])]
                    has_los = 1.0 if self._has_los_from_topology(
                        active_col, active_row, unit_col, unit_row, game_state
                    ) else 0.0
                
                # Target preference match (placeholder - will enhance with unit registry)
                target_match = 0.5
                
                # Store encoded features
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = dist_norm
                obs[feature_base + 3] = hp_ratio
                obs[feature_base + 4] = is_enemy
                obs[feature_base + 5] = threat
                obs[feature_base + 6] = defensive_type
                obs[feature_base + 7] = offensive_type
                obs[feature_base + 8] = has_los
                obs[feature_base + 9] = target_match
            else:
                # Padding for empty slots
                for j in range(10):
                    obs[feature_base + j] = 0.0
    
    def _get_valid_targets(self, active_unit: Dict[str, Any], game_state: Dict[str, Any],
                          positions: Dict[str, Tuple[int, int]]) -> List[Dict[str, Any]]:
        """
        Build raw list of valid targets for current phase (shoot / charge / fight).
        Unsorted. Used by _get_six_reference_enemies and _encode_valid_targets.
        """
        valid_targets: List[Dict[str, Any]] = []
        current_phase = require_key(game_state, "phase")
        if current_phase == "shoot":
            # Pool is source of truth during shooting activation; avoid redundant rebuilds
            from engine.phase_handlers import shooting_handlers
            if "valid_target_pool" in active_unit:
                target_ids = active_unit["valid_target_pool"]
            else:
                target_ids = shooting_handlers.shooting_build_valid_target_pool(
                    game_state, active_unit["id"]
                )
                active_unit["valid_target_pool"] = target_ids
            for tid in target_ids:
                unit = get_unit_by_id(str(tid), game_state)
                if unit:
                    valid_targets.append(unit)
        elif current_phase == "charge":
            if "MOVE" not in active_unit:
                raise KeyError(f"Active unit missing required 'MOVE' field: {active_unit}")
            units_cache = require_key(game_state, "units_cache")
            active_entry = require_key(units_cache, str(active_unit["id"]))
            active_player = require_key(active_entry, "player")
            for enemy_id, enemy_entry in units_cache.items():
                enemy_player = require_key(enemy_entry, "player")
                if enemy_player == active_player:
                    continue
                enemy = get_unit_by_id(str(enemy_id), game_state)
                if enemy is None:
                    raise KeyError(f"Enemy unit {enemy_id} missing from game_state['units']")
                if "col" not in enemy or "row" not in enemy:
                    raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                active_col, active_row = positions[str(active_unit["id"])]
                enemy_col, enemy_row = positions[str(enemy["id"])]
                distance = calculate_pathfinding_distance(
                    active_col, active_row, enemy_col, enemy_row, game_state
                )
                _charge_max_d = require_key(require_key(require_key(game_state, "config"), "game_rules"), "charge_max_distance")
                if distance <= active_unit["MOVE"] + _charge_max_d:
                    valid_targets.append(enemy)
        elif current_phase == "fight":
            from engine.spatial_relations import get_engagement_zone
            melee_range = get_engagement_zone(game_state)
            units_cache = require_key(game_state, "units_cache")
            active_entry = require_key(units_cache, str(active_unit["id"]))
            active_player = require_key(active_entry, "player")
            for enemy_id, enemy_entry in units_cache.items():
                enemy_player = require_key(enemy_entry, "player")
                if enemy_player == active_player:
                    continue
                enemy = get_unit_by_id(str(enemy_id), game_state)
                if enemy is None:
                    raise KeyError(f"Enemy unit {enemy_id} missing from game_state['units']")
                if "col" not in enemy or "row" not in enemy:
                    raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                active_col, active_row = positions[str(active_unit["id"])]
                enemy_col, enemy_row = positions[str(enemy["id"])]
                if calculate_hex_distance(active_col, active_row, enemy_col, enemy_row) <= melee_range:
                    valid_targets.append(enemy)
        return valid_targets
    
    def _get_six_reference_enemies(
        self, active_unit: Dict[str, Any], game_state: Dict[str, Any],
        valid_targets: List[Dict[str, Any]],
        positions: Dict[str, Tuple[int, int]],
    ) -> List[tuple]:
        """
        Build the 6 reference enemies for obs[141:273] and enemy_index_map.
        Ensures every valid target is in the 6 so require_key(enemy_index_map, id) never fails.
        Returns list of (distance, unit) ordered: valid_targets first (up to 6), then fill by distance.
        """
        perception_radius = self.perception_radius
        active_col, active_row = positions[str(active_unit["id"])]
        all_enemies: List[tuple] = []
        units_cache = require_key(game_state, "units_cache")
        active_entry = require_key(units_cache, str(active_unit["id"]))
        active_player = require_key(active_entry, "player")
        for other_id, other_entry in units_cache.items():
            other_player = require_key(other_entry, "player")
            if other_player == active_player:
                continue
            other = get_unit_by_id(str(other_id), game_state)
            if other is None:
                raise KeyError(f"Unit {other_id} missing from game_state['units']")
            if "col" not in other or "row" not in other:
                raise KeyError(f"Unit missing required position fields: {other}")
            oc, or_ = positions[str(other["id"])]
            d = calculate_hex_distance(active_col, active_row, oc, or_)
            all_enemies.append((d, other))
        all_enemies.sort(key=lambda x: x[0])
        six: List[tuple] = []
        seen: set = set()
        for u in valid_targets:
            if len(six) >= 6:
                break
            kid = str(u["id"])
            if kid in seen:
                continue
            seen.add(kid)
            dc = calculate_hex_distance(active_col, active_row, *positions[str(u["id"])])
            six.append((dc, u))
        for d, u in all_enemies:
            if len(six) >= 6:
                break
            kid = str(u["id"])
            if kid in seen:
                continue
            if d <= perception_radius:
                six.append((d, u))
                seen.add(kid)
        for d, u in all_enemies:
            if len(six) >= 6:
                break
            if str(u["id"]) in seen:
                continue
            six.append((d, u))
            seen.add(str(u["id"]))
        return six[:6]
    
    def _target_priority_score(
        self,
        target: Dict[str, Any],
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        positions: Dict[str, Tuple[int, int]],
    ):
        """
        Sort key for valid targets: (lower = higher priority).
        Returns (-strategic_efficiency, distance) so best targets sort first.
        """
        active_col, active_row = positions[str(active_unit["id"])]
        target_col, target_row = positions[str(target["id"])]
        distance = calculate_hex_distance(
            active_col, active_row, target_col, target_row
        )
        if "VALUE" not in target:
            raise KeyError(f"Target missing required 'VALUE' field: {target}")
        target_value = target["VALUE"]
        best_weapon_idx, _, is_ranged_mode = self._get_phase_aware_best_weapon_features(
            active_unit, target, game_state
        )
        if is_ranged_mode:
            weapons = require_key(active_unit, "RNG_WEAPONS")
        else:
            weapons = require_key(active_unit, "CC_WEAPONS")

        if best_weapon_idx < 0:
            return (0.0, distance)
        if best_weapon_idx >= len(weapons):
            raise ValueError(
                f"Phase-aware best weapon index out of range in target priority: idx={best_weapon_idx}, "
                f"weapons_len={len(weapons)}, is_ranged_mode={is_ranged_mode}, "
                f"active_unit_id={active_unit.get('id')}, target_id={target.get('id')}"
            )
        weapon = weapons[best_weapon_idx]
        unit_attacks = expected_dice_value(require_key(weapon, "NB"), "target_priority_nb")
        unit_bs = weapon["ATK"]
        unit_s = weapon["STR"]
        unit_ap = weapon["AP"]
        unit_dmg = expected_dice_value(require_key(weapon, "DMG"), "target_priority_dmg")
        if "T" not in target or "ARMOR_SAVE" not in target:
            raise KeyError(f"Target missing required T/ARMOR_SAVE: {target}")
        target_t = target["T"]
        target_save = target["ARMOR_SAVE"]
        target_hp = require_hp_from_cache(str(target["id"]), game_state)
        our_hit_prob = (7 - unit_bs) / 6.0
        if unit_s >= target_t * 2:
            our_wound_prob = 5 / 6
        elif unit_s > target_t:
            our_wound_prob = 4 / 6
        elif unit_s == target_t:
            our_wound_prob = 3 / 6
        elif unit_s * 2 <= target_t:
            our_wound_prob = 1 / 6
        else:
            our_wound_prob = 2 / 6
        target_modified_save = target_save - unit_ap
        target_failed_save = (
            1.0 if target_modified_save > 6 else (target_modified_save - 1) / 6.0
        )
        damage_per_attack = (
            our_hit_prob * our_wound_prob * target_failed_save * unit_dmg
        )
        if damage_per_attack > 0:
            activations_to_kill = target_hp / damage_per_attack
        else:
            activations_to_kill = 100
        if activations_to_kill > 0:
            strategic_efficiency = target_value / activations_to_kill
        else:
            strategic_efficiency = target_value * 100
        return (-strategic_efficiency, distance)
    
    def _sort_valid_targets(
        self,
        valid_targets: List[Dict[str, Any]],
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        positions: Dict[str, Tuple[int, int]],
    ) -> List[Dict[str, Any]]:
        """Sort valid targets by strategic efficiency (best first). In-place then return."""
        valid_targets.sort(
            key=lambda t: self._target_priority_score(t, active_unit, game_state, positions)
        )
        return valid_targets
    
    def _encode_valid_targets(
        self,
        obs: np.ndarray,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        base_idx: int,
        valid_targets: Optional[List[Dict[str, Any]]] = None,
        six_enemies: Optional[List[tuple]] = None,
        positions: Optional[Dict[str, Tuple[int, int]]] = None,
    ):
        """
        Encode valid targets with EXPLICIT action-target correspondence and W40K probabilities.
        40 floats = 5 actions × 8 features per action - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        
        CRITICAL DESIGN: obs[273 + action_offset*8] directly corresponds to action (4 + action_offset)
        Example: 
        - obs[273:281] = features for what happens if agent presses action 4
        - obs[281:289] = features for what happens if agent presses action 5
        
        This creates DIRECT causal relationship for RL learning:
        "When obs[274]=1.0 (high kill_probability), pressing action 4 gives high reward"
        
        Features per action slot (8 floats) - CORE TACTICAL ESSENTIALS:
        0. is_valid (1.0 = target exists, 0.0 = no target in this slot)
        1. best_weapon_index (0-2, normalisé / 2.0) - NOUVEAU
        2. best_kill_probability (0.0-1.0) - NOUVEAU, remplace ancien feature 1
        3. danger_to_me (0.0-1.0, probability target kills ME next turn) - DÉCALÉ
        4. enemy_index (0-5: which enemy in obs[141:273] this action targets) - DÉCALÉ
        5. distance_normalized (hex_distance / perception_radius) - DÉCALÉ
        6. is_priority_target (1.0 if moved toward me, high threat) - DÉCALÉ
        7. coordination_bonus (1.0 if friendly melee can charge after I shoot) - DÉCALÉ
        """
        perception_radius = self.perception_radius
        if positions is None:
            positions = {uid: (e["col"], e["row"]) for uid, e in require_key(game_state, "units_cache").items()}
        if valid_targets is None:
            valid_targets = self._get_valid_targets(active_unit, game_state, positions)
            self._sort_valid_targets(valid_targets, active_unit, game_state, positions)
        if six_enemies is None:
            six_enemies = self._get_six_reference_enemies(
                active_unit, game_state, valid_targets, positions
            )
        enemy_index_map: Dict[str, int] = {}
        for idx, (_d, u) in enumerate(six_enemies):
            enemy_index_map[str(u["id"])] = idx
        # valid_targets already sorted (by caller or above)
        # Encode up to max_valid_targets (5 targets × 8 features = 40 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        max_encoded = 5
        for i in range(max_encoded):
            feature_base = base_idx + i * 8
            
            if i < len(valid_targets):
                target = valid_targets[i]
                
                # Feature 0: Action validity (CRITICAL - tells agent this action works)
                obs[feature_base + 0] = 1.0
                
                # Feature 1-2: best_weapon_index + best_kill_probability (phase-aware)
                best_weapon_idx, best_kill_prob, _ = self._get_phase_aware_best_weapon_features(
                    active_unit, target, game_state
                )
                obs[feature_base + 1] = best_weapon_idx / 2.0 if best_weapon_idx >= 0 else 0.0
                
                # Feature 2: best_kill_probability (NOUVEAU, remplace ancien feature 1)
                obs[feature_base + 2] = best_kill_prob
                
                # Feature 3: Danger to me (probability target kills ME next turn) - DÉCALÉ
                danger_prob = self._calculate_danger_probability(active_unit, target, game_state, positions)
                obs[feature_base + 3] = danger_prob

                # Feature 4: Enemy index (reference to obs[141:273]) - DÉCALÉ
                enemy_idx = require_key(enemy_index_map, str(target["id"]))
                obs[feature_base + 4] = enemy_idx / 5.0

                # Feature 5: Distance (accessibility) - DÉCALÉ
                active_col, active_row = positions[str(active_unit["id"])]
                target_col, target_row = positions[str(target["id"])]
                distance = calculate_hex_distance(
                    active_col, active_row,
                    target_col, target_row
                )
                obs[feature_base + 5] = distance / perception_radius
                
                # Feature 6: Is priority target (moved toward me + high threat) - DÉCALÉ
                movement_dir = self._calculate_movement_direction(target, active_unit, game_state, positions)
                is_approaching = 1.0 if movement_dir > 0.75 else 0.0
                danger = self._calculate_danger_probability(active_unit, target, game_state, positions)
                is_priority = 1.0 if (is_approaching > 0.5 and danger > 0.5) else 0.0
                obs[feature_base + 6] = is_priority
                
                # Feature 7: Coordination bonus (can friendly melee charge after I shoot) - DÉCALÉ
                can_be_charged = 1.0 if self._can_melee_units_charge_target(target, game_state, positions) else 0.0
                obs[feature_base + 7] = can_be_charged
            else:
                # Padding for empty slots
                for j in range(8):
                    obs[feature_base + j] = 0.0
    
    def _encode_defensive_type(self, unit: Dict[str, Any]) -> float:
        """
        Encode defensive type based on HP_MAX.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access.
        
        Returns:
        - 0.25 = Swarm (HP_MAX <= 1)
        - 0.5  = Troop (HP_MAX 2-3)
        - 0.75 = Elite (HP_MAX 4-6)
        - 1.0  = Leader (HP_MAX >= 7)
        """
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "HP_MAX" not in unit:
            raise KeyError(f"Unit missing required 'HP_MAX' field: {unit}")
        
        hp_max = unit["HP_MAX"]
        if hp_max <= 1:
            return 0.25  # Swarm
        elif hp_max <= 3:
            return 0.5   # Troop
        elif hp_max <= 6:
            return 0.75  # Elite
        else:
            return 1.0   # Leader
    
    def _encode_defensive_type_detailed(self, unit: Dict[str, Any]) -> float:
        """
        Encode defensive type with 4-tier granularity for target selection.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access.
        
        Returns:
        - 0.0  = Swarm (HP_MAX <= 1)
        - 0.33 = Troop (HP_MAX 2-3)
        - 0.66 = Elite (HP_MAX 4-6)
        - 1.0  = Leader (HP_MAX >= 7)
        """
        # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        if "HP_MAX" not in unit:
            raise KeyError(f"Unit missing required 'HP_MAX' field: {unit}")
        
        hp_max = unit["HP_MAX"]
        if hp_max <= 1:
            return 0.0  # Swarm
        elif hp_max <= 3:
            return 0.33  # Troop
        elif hp_max <= 6:
            return 0.66  # Elite
        else:
            return 1.0   # Leader
    
    # ============================================================================
    # DIRECTIONAL HELPERS
    # ============================================================================
    
    def _find_nearest_in_direction(self, unit: Dict[str, Any], dx: int, dy: int, game_state: Dict[str, Any],
                                   search_type: str, positions: Dict[str, Tuple[int, int]]) -> float:
        """Find nearest object (wall/friendly/enemy) in given direction."""
        perception_radius = self.perception_radius
        min_distance = 999.0
        unit_col, unit_row = positions[str(unit["id"])]

        if search_type == "wall":
            for wall_col, wall_row in game_state["wall_hexes"]:
                if self._is_in_direction(unit_col, unit_row, wall_col, wall_row, dx, dy):
                    dist = calculate_hex_distance(unit_col, unit_row, wall_col, wall_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist

        elif search_type in ["friendly", "enemy"]:
            if search_type == "friendly":
                target_player = unit["player"]
            else:
                target_player = 3 - unit["player"]  # 1->2, 2->1
            for other_unit in game_state["units"]:
                if not is_unit_alive(str(other_unit["id"]), game_state):
                    continue
                if other_unit["player"] != target_player:
                    continue
                if other_unit["id"] == unit["id"]:
                    continue

                other_col, other_row = positions[str(other_unit["id"])]
                if self._is_in_direction(unit_col, unit_row, other_col, other_row, dx, dy):
                    dist = calculate_hex_distance(unit_col, unit_row, other_col, other_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist

        return min_distance if min_distance < 999.0 else perception_radius
    
    def _is_in_direction(self, unit_col: int, unit_row: int, target_col: int, target_row: int,
                        dx: int, dy: int) -> bool:
        """Check if target is roughly in the specified direction from unit."""
        delta_col = target_col - unit_col
        delta_row = target_row - unit_row
        
        # Rough directional check (within 45-degree cone)
        if dx == 0:  # North/South
            return abs(delta_col) <= abs(delta_row) and (delta_row * dy > 0)
        elif dy == 0:  # East/West
            return abs(delta_row) <= abs(delta_col) and (delta_col * dx > 0)
        else:  # Diagonal
            return (delta_col * dx > 0) and (delta_row * dy > 0)
    
    def _find_edge_distance(self, unit: Dict[str, Any], dx: int, dy: int, game_state: Dict[str, Any],
                            positions: Dict[str, Tuple[int, int]]) -> float:
        """Calculate distance to board edge in given direction."""
        perception_radius = self.perception_radius
        unit_col, unit_row = positions[str(unit["id"])]
        if dx > 0:  # East
            edge_dist = game_state["board_cols"] - unit_col - 1
        elif dx < 0:  # West
            edge_dist = unit_col
        else:
            edge_dist = perception_radius

        if dy > 0:  # South
            edge_dist = min(edge_dist, game_state["board_rows"] - unit_row - 1)
        elif dy < 0:  # North
            edge_dist = min(edge_dist, unit_row)

        return float(edge_dist)
