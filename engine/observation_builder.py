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
)
from engine.macro_intents import (
    INTENT_COUNT,
    DETAIL_OBJECTIVE,
    DETAIL_ENEMY,
    DETAIL_ALLY,
    DETAIL_NONE,
)

class ObservationBuilder:
    """Builds observations for the agent."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
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
        """Compute sum(VALUE) alive for P1 minus P2."""
        p1_value = 0
        p2_value = 0
        for unit_id, cache_entry in units_cache.items():
            unit = get_unit_by_id(str(unit_id), game_state)
            if unit is None:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if cache_entry["player"] == 1:
                p1_value += unit_value
            elif cache_entry["player"] == 2:
                p2_value += unit_value
        return p1_value - p2_value
    
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
        Calculate unit's combat preference based on ACTUAL expected damage
        against their favorite target types (from unitType).
        
        Returns 0.1-0.9:
        - 0.1-0.3: Melee specialist (CC damage >> RNG damage)
        - 0.4-0.6: Balanced combatant
        - 0.7-0.9: Ranged specialist (RNG damage >> CC damage)
        
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Determine favorite target stats based on specialization
        if "Swarm" in unit_type:
            target_T = 3
            target_save = 5
            target_invul = 7  # No invul (7+ = impossible)
        elif "Troop" in unit_type:
            target_T = 4
            target_save = 3
            target_invul = 7  # No invul
        elif "Elite" in unit_type:
            target_T = 5
            target_save = 2
            target_invul = 4  # 4+ invulnerable
        else:  # Monster/Leader
            target_T = 6
            target_save = 3
            target_invul = 7  # No invul
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Calculate max expected damage from all weapons
        # Calculate EXPECTED ranged damage per turn (max from all ranged weapons)
        ranged_expected = 0.0
        if unit.get("RNG_WEAPONS"):
            for weapon in unit["RNG_WEAPONS"]:
                weapon_expected = self._calculate_expected_damage(
                    num_attacks=expected_dice_value(require_key(weapon, "NB"), "combat_mix_rng_nb"),
                    to_hit_stat=require_key(weapon, "ATK"),
                    strength=require_key(weapon, "STR"),
                    target_toughness=target_T,
                    ap=require_key(weapon, "AP"),
                    target_save=target_save,
                    target_invul=target_invul,
                    damage_per_wound=expected_dice_value(require_key(weapon, "DMG"), "combat_mix_rng_dmg")
                )
                ranged_expected = max(ranged_expected, weapon_expected)
        
        # Calculate EXPECTED melee damage per turn (max from all melee weapons)
        melee_expected = 0.0
        if unit.get("CC_WEAPONS"):
            for weapon in unit["CC_WEAPONS"]:
                weapon_expected = self._calculate_expected_damage(
                    num_attacks=expected_dice_value(require_key(weapon, "NB"), "combat_mix_cc_nb"),
                    to_hit_stat=require_key(weapon, "ATK"),
                    strength=require_key(weapon, "STR"),
                    target_toughness=target_T,
                    ap=require_key(weapon, "AP"),
                    target_save=target_save,
                    target_invul=target_invul,
                    damage_per_wound=expected_dice_value(require_key(weapon, "DMG"), "combat_mix_cc_dmg")
                )
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
        Extract favorite target type from unitType name.
        
        unitType format: "Faction_Movement_PowerLevel_AttackPreference"
        Example: "SpaceMarine_Infantry_Troop_RangedSwarm"
                                              ^^^^^^^^^^^^
                                              Ranged + Swarm
        
        Returns 0.0-1.0 encoding:
        - 0.0 = Swarm specialist (vs HP_MAX ≤ 1)
        - 0.33 = Troop specialist (vs HP_MAX 2-3)
        - 0.66 = Elite specialist (vs HP_MAX 4-6)
        - 1.0 = Monster specialist (vs HP_MAX ≥ 7)
        
        AI_TURN.md COMPLIANCE: Direct field access
        """
        if "unitType" not in unit:
            raise KeyError(f"Unit missing required 'unitType' field: {unit}")
        
        unit_type = unit["unitType"]
        
        # Parse attack preference component (last part after final underscore)
        parts = unit_type.split("_")
        if len(parts) < 4:
            return 0.5  # Default neutral if format unexpected
        
        attack_pref = parts[3]  # e.g., "RangedSwarm", "MeleeElite"
        
        # Extract target preference from attack_pref
        if "Swarm" in attack_pref:
            return 0.0
        elif "Troop" in attack_pref:
            return 0.33
        elif "Elite" in attack_pref:
            return 0.66
        elif "Monster" in attack_pref or "Leader" in attack_pref:
            return 1.0
        else:
            return 0.5  # Default neutral
    
    def _calculate_movement_direction(self, unit: Dict[str, Any], 
                                     active_unit: Dict[str, Any],
                                     game_state: Dict[str, Any]) -> float:
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
        curr_col, curr_row = require_unit_position(unit, game_state)
        
        # Calculate movement toward/away from active unit
        active_col, active_row = require_unit_position(active_unit, game_state)
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

    def _calculate_kill_probability(self, shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Calculate actual probability to kill target this turn considering W40K dice mechanics.
        MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon

        Considers:
        - Hit probability (weapon.ATK vs d6)
        - Wound probability (weapon.STR vs target T)
        - Save failure probability (target saves vs weapon.AP)
        - Number of attacks (weapon.NB)
        - Damage per successful wound (weapon.DMG)

        Returns: 0.0-1.0 probability
        """
        current_phase = game_state["phase"]
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon
        from engine.ai.weapon_selector import get_best_weapon_for_target

        if current_phase == "shoot":
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=True)
            rng_weapons = require_key(shooter, "RNG_WEAPONS")
            if best_weapon_idx < 0 or best_weapon_idx >= len(rng_weapons):
                raise ValueError(f"Invalid best ranged weapon index {best_weapon_idx} for shooter_id={shooter.get('id')}")
            weapon = rng_weapons[best_weapon_idx]
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "kill_prob_rng_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "kill_prob_rng_nb")
            ap = weapon["AP"]
        else:
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=False)
            cc_weapons = require_key(shooter, "CC_WEAPONS")
            if best_weapon_idx < 0 or best_weapon_idx >= len(cc_weapons):
                raise ValueError(f"Invalid best melee weapon index {best_weapon_idx} for shooter_id={shooter.get('id')}")
            weapon = cc_weapons[best_weapon_idx]
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "kill_prob_cc_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "kill_prob_cc_nb")
            ap = weapon["AP"]
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in target:
            raise KeyError(f"Target missing required 'T' field: {target}")
        wound_target = self._calculate_wound_target(strength, target["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        # Save failure probability (uses imported function from shooting_handlers)
        save_target = _calculate_save_target(target, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        target_hp = get_hp_from_cache(str(target["id"]), game_state)
        if target_hp is None:
            target_hp = 0
        if expected_damage >= target_hp:
            return 1.0
        else:
            return min(1.0, expected_damage / target_hp)
    
    def _calculate_danger_probability(self, defender: Dict[str, Any], attacker: Dict[str, Any], game_state: Dict[str, Any]) -> float:
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
        defender_col, defender_row = require_unit_position(defender, game_state)
        attacker_col, attacker_row = require_unit_position(attacker, game_state)
        distance = calculate_pathfinding_distance(
            defender_col, defender_row,
            attacker_col, attacker_row,
            game_state
        )

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
        from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
        max_ranged_range = get_max_ranged_range(attacker)
        melee_range = get_melee_range()  # Always 1

        can_use_ranged = max_ranged_range > 0 and distance <= max_ranged_range
        can_use_melee = distance <= melee_range

        if not can_use_ranged and not can_use_melee:
            self._danger_probability_cache[cache_key] = 0.0
            return 0.0

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use best weapon for this defender
        from engine.ai.weapon_selector import get_best_weapon_for_target
        
        if can_use_ranged and not can_use_melee:
            # Use best ranged weapon
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=True)
            rng_weapons = require_key(attacker, "RNG_WEAPONS")
            if best_weapon_idx < 0 or best_weapon_idx >= len(rng_weapons):
                raise ValueError(f"Invalid best ranged weapon index {best_weapon_idx} for attacker_id={attacker.get('id')}")
            weapon = rng_weapons[best_weapon_idx]
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "danger_rng_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "danger_rng_nb")
            ap = weapon["AP"]
        else:
            # Use best melee weapon (or if both available, prefer melee if in range)
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            cc_weapons = require_key(attacker, "CC_WEAPONS")
            if best_weapon_idx < 0 or best_weapon_idx >= len(cc_weapons):
                raise ValueError(f"Invalid best melee weapon index {best_weapon_idx} for attacker_id={attacker.get('id')}")
            weapon = cc_weapons[best_weapon_idx]
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = expected_dice_value(require_key(weapon, "DMG"), "danger_cc_dmg")
            num_attacks = expected_dice_value(require_key(weapon, "NB"), "danger_cc_nb")
            ap = weapon["AP"]
        
        if num_attacks == 0:
            self._danger_probability_cache[cache_key] = 0.0
            return 0.0
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in defender:
            self._danger_probability_cache[cache_key] = 0.0
            return 0.0
        wound_target = self._calculate_wound_target(strength, defender["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        save_target = _calculate_save_target(defender, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        defender_hp = get_hp_from_cache(str(defender["id"]), game_state)
        if defender_hp is None:
            defender_hp = 0
        if expected_damage >= defender_hp:
            self._danger_probability_cache[cache_key] = 1.0
            return 1.0
        else:
            result = min(1.0, expected_damage / defender_hp)
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
            if not hasattr(self, 'unit_registry') or not self.unit_registry:
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

    def _can_melee_units_charge_target(self, target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
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

                # Charge range check using BFS pathfinding to respect walls
                unit_col, unit_row = require_unit_position(unit, game_state)
                target_col, target_row = require_unit_position(target, game_state)
                distance = calculate_pathfinding_distance(
                    unit_col, unit_row,
                    target_col, target_row,
                    game_state
                )
                if "MOVE" not in unit:
                    raise KeyError(f"Unit missing required 'MOVE' field: {unit}")
                max_charge_range = unit["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety

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

        Structure (323 floats):
        - [0:15]    Global context (15 floats) - includes objective control
        - [15:37]   Active unit capabilities (22 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        - [37:69]   Directional terrain (32 floats: 8 directions × 4 features)
        - [69:141]  Allied units (72 floats: 6 units × 12 features)
        - [141:273] Enemy units (132 floats: 6 units × 22 features) - OPTIMISÉ
        - [273:313] Valid targets (40 floats: 5 targets × 8 features)
        - [314:318] Macro target (4 floats)
        - [318:323] Macro intent (5 floats)

        Asymmetric design: More complete information about enemies than allies.
        Agent discovers optimal tactical combinations through training.
        """
        # PERFORMANCE: Clear per-observation cache (same pairs recalculated multiple times)
        self._danger_probability_cache = {}

        obs = np.zeros(self.obs_size, dtype=np.float32)
        
        # Get active unit (agent's current unit); pool building ensures only alive units.
        active_unit = active_unit_override if active_unit_override is not None else self._get_active_unit_for_observation(game_state)
        if not active_unit:
            # No active unit - return zero observation
            return obs
        if not is_unit_alive(str(active_unit["id"]), game_state):
            raise ValueError(f"Active unit for observation is not alive: unit_id={active_unit.get('id')}")
        
        # Build los_cache explicitly for observation (single source of truth)
        from engine.phase_handlers.shooting_handlers import build_unit_los_cache
        units_cache = require_key(game_state, "units_cache")
        active_player = int(active_unit["player"]) if active_unit["player"] is not None else None
        if active_player is None:
            raise ValueError(f"Active unit missing player: {active_unit}")
        for ally_id, cache_entry in units_cache.items():
            if int(cache_entry["player"]) == active_player:
                build_unit_los_cache(game_state, str(ally_id))
        # === SECTION 1: Global Context (15 floats) - includes objective control ===
        obs[0] = float(game_state["current_player"])
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
        self._encode_objective_control(obs, active_unit, game_state, base_idx=11)
        # === SECTION 2: Active Unit Capabilities (22 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md ===
        obs[16] = require_key(active_unit, "MOVE") / 12.0

        # RNG_WEAPONS[0] (3 floats: RNG, DMG, NB)
        rng_weapons = require_key(active_unit, "RNG_WEAPONS")
        if len(rng_weapons) > 0:
            obs[17] = require_key(rng_weapons[0], "RNG") / 24.0
            obs[18] = expected_dice_value(require_key(rng_weapons[0], "DMG"), "obs_rng0_dmg") / 5.0
            obs[19] = expected_dice_value(require_key(rng_weapons[0], "NB"), "obs_rng0_nb") / 10.0
        else:
            obs[17] = obs[18] = obs[19] = 0.0

        # RNG_WEAPONS[1] (3 floats)
        if len(rng_weapons) > 1:
            obs[20] = require_key(rng_weapons[1], "RNG") / 24.0
            obs[21] = expected_dice_value(require_key(rng_weapons[1], "DMG"), "obs_rng1_dmg") / 5.0
            obs[22] = expected_dice_value(require_key(rng_weapons[1], "NB"), "obs_rng1_nb") / 10.0
        else:
            obs[20] = obs[21] = obs[22] = 0.0

        # RNG_WEAPONS[2] (3 floats)
        if len(rng_weapons) > 2:
            obs[23] = require_key(rng_weapons[2], "RNG") / 24.0
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
        self._encode_directional_terrain(obs, active_unit, game_state, base_idx=38)
        # === SECTION 4: Allied Units (72 floats) ===
        # Directional Terrain: [38:70] = 32 floats
        # base_idx = 38 + 32 = 70
        self._encode_allied_units(obs, active_unit, game_state, base_idx=70)
        # === SECTION 5: Enemy Units (132 floats) ===
        # Allied Units: [70:142] = 72 floats
        # base_idx = 70 + 72 = 142
        # === SECTION 6: Valid Targets (40 floats) ===
        # Shared 6 reference enemies so every valid target has enemy_index; avoid "Required key 'X' missing".
        # Sort before building 6 so encoded targets (first 5) are always in the 6.
        valid_targets = self._get_valid_targets(active_unit, game_state)
        self._sort_valid_targets(valid_targets, active_unit, game_state)
        six_enemies = self._get_six_reference_enemies(active_unit, game_state, valid_targets)
        self._encode_enemy_units(obs, active_unit, game_state, base_idx=142, six_enemies=six_enemies)
        # Enemy Units: [142:274] = 132 floats (6 × 22 features)
        # base_idx = 142 + 132 = 274
        self._encode_valid_targets(
            obs, active_unit, game_state, base_idx=274,
            valid_targets=valid_targets, six_enemies=six_enemies
        )
        # === SECTION 7: Macro target + intent (9 floats) ===
        if self.obs_size < 323:
            raise ValueError(f"obs_size too small for macro target features: {self.obs_size}")
        self._encode_macro_intent_context(obs, active_unit, game_state, base_idx=314)
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
                                   game_state: Dict[str, Any], base_idx: int):
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

                    unit_pos = require_unit_position(unit, game_state)
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

    def _encode_macro_intent_context(
        self,
        obs: np.ndarray,
        active_unit: Dict[str, Any],
        game_state: Dict[str, Any],
        base_idx: int
    ) -> None:
        """
        Encode macro intent context for the active unit.

        Detail features (4 floats):
        - target_col_norm
        - target_row_norm
        - target_signal (objective: control_state, unit: hp_ratio, none: 0.0)
        - target_distance_norm (distance / max_range)
        """
        macro_intent_id = require_key(game_state, "macro_intent_id")
        if macro_intent_id is None:
            raise ValueError("macro_intent_id is required for macro intent encoding")
        try:
            macro_intent_id_int = int(macro_intent_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid macro_intent_id: {macro_intent_id}") from exc
        if macro_intent_id_int < 0 or macro_intent_id_int >= INTENT_COUNT:
            raise ValueError(f"macro_intent_id out of range: {macro_intent_id_int}")

        detail_type = require_key(game_state, "macro_detail_type")
        if detail_type is None:
            raise ValueError("macro_detail_type is required for macro intent encoding")
        try:
            detail_type_int = int(detail_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid macro_detail_type: {detail_type}") from exc

        detail_id = require_key(game_state, "macro_detail_id")
        if detail_id is None:
            raise ValueError("macro_detail_id is required for macro intent encoding")
        try:
            detail_id_int = int(detail_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid macro_detail_id: {detail_id}") from exc

        board_cols = require_key(game_state, "board_cols")
        board_rows = require_key(game_state, "board_rows")
        if board_cols <= 0 or board_rows <= 0:
            raise ValueError(f"Invalid board size for macro intent encoding: cols={board_cols}, rows={board_rows}")

        unit_col, unit_row = require_unit_position(active_unit, game_state)
        max_range = require_key(game_state, "max_range")

        target_col_norm = 0.0
        target_row_norm = 0.0
        target_signal = 0.0
        distance_norm = 0.0

        if detail_type_int == DETAIL_OBJECTIVE:
            if "macro_objectives" not in game_state:
                objectives = require_key(game_state, "objectives")
                macro_objectives = self._build_macro_objective_entries(
                    objectives, game_state, board_cols, board_rows
                )
                game_state["macro_objectives"] = macro_objectives
                game_state["macro_attrition_objective_index"] = len(macro_objectives) - 1
            macro_objectives = require_key(game_state, "macro_objectives")
            if not macro_objectives:
                raise ValueError("macro_objectives is required for macro intent encoding")
            if detail_id_int < 0 or detail_id_int >= len(macro_objectives):
                raise ValueError(
                    f"macro_detail_id out of range for objectives: {detail_id_int} "
                    f"(objectives={len(macro_objectives)})"
                )
            objective = macro_objectives[detail_id_int]
            centroid_col = require_key(objective, "col")
            centroid_row = require_key(objective, "row")
            target_col_norm = require_key(objective, "col_norm")
            target_row_norm = require_key(objective, "row_norm")
            target_signal = require_key(objective, "control_state")
            distance = calculate_hex_distance(
                unit_col,
                unit_row,
                int(round(centroid_col)),
                int(round(centroid_row))
            )
            distance_norm = distance / float(max_range) if max_range > 0 else 0.0
        elif detail_type_int in (DETAIL_ENEMY, DETAIL_ALLY):
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            target_unit = unit_by_id.get(str(detail_id_int))
            if target_unit is None:
                raise KeyError(f"macro_detail_id unit missing from game_state: {detail_id_int}")
            target_col, target_row = require_unit_position(target_unit, game_state)
            target_col_norm = target_col / float(board_cols - 1)
            target_row_norm = target_row / float(board_rows - 1)
            hp_cur = require_hp_from_cache(str(detail_id_int), game_state)
            hp_max = require_key(target_unit, "HP_MAX")
            target_signal = (hp_cur / hp_max) if hp_max > 0 else 0.0
            distance = calculate_hex_distance(unit_col, unit_row, target_col, target_row)
            distance_norm = distance / float(max_range) if max_range > 0 else 0.0
        elif detail_type_int == DETAIL_NONE:
            target_col_norm = 0.0
            target_row_norm = 0.0
            target_signal = 0.0
            distance_norm = 0.0
        else:
            raise ValueError(f"Unsupported macro_detail_type: {detail_type_int}")

        obs[base_idx + 0] = target_col_norm
        obs[base_idx + 1] = target_row_norm
        obs[base_idx + 2] = target_signal
        obs[base_idx + 3] = distance_norm

        intent_base = base_idx + 4
        for idx in range(INTENT_COUNT):
            obs[intent_base + idx] = 1.0 if idx == macro_intent_id_int else 0.0

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
            # Command phase has no "active unit" for observation; return None so build_observation returns zeros
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
    
    def _encode_directional_terrain(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int):
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
        
        for dir_idx, (dx, dy) in enumerate(directions):
            feature_base = base_idx + dir_idx * 4
            
            # Find nearest wall, friendly, enemy, and edge in this direction
            wall_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "wall")
            friendly_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "friendly")
            enemy_dist = self._find_nearest_in_direction(active_unit, dx, dy, game_state, "enemy")
            edge_dist = self._find_edge_distance(active_unit, dx, dy, game_state)
            
            # Normalize by perception radius
            obs[feature_base + 0] = min(1.0, wall_dist / perception_radius)
            obs[feature_base + 1] = min(1.0, friendly_dist / perception_radius)
            obs[feature_base + 2] = min(1.0, enemy_dist / perception_radius)
            obs[feature_base + 3] = min(1.0, edge_dist / perception_radius)
    
    def _encode_allied_units(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int):
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
            
            active_col, active_row = require_unit_position(active_unit, game_state)
            other_col, other_row = require_unit_position(other_unit, game_state)
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
                ally_col, ally_row = require_unit_position(ally, game_state)
                active_col, active_row = require_unit_position(active_unit, game_state)
                rel_col = (ally_col - active_col) / 24.0
                rel_row = (ally_row - active_row) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                
                # Feature 2-3: Health status (Phase 2: HP from cache; dead = 0)
                hp_cur = get_hp_from_cache(str(ally["id"]), game_state)
                obs[feature_base + 2] = (hp_cur if hp_cur is not None else 0) / max(1, ally["HP_MAX"])
                obs[feature_base + 3] = ally["HP_MAX"] / 10.0
                
                # Feature 4: Has moved
                obs[feature_base + 4] = 1.0 if ally["id"] in game_state["units_moved"] else 0.0
                
                # Feature 5: Movement direction (temporal behavior)
                obs[feature_base + 5] = self._calculate_movement_direction(ally, active_unit, game_state)
                
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
                danger = self._calculate_danger_probability(active_unit, ally, game_state)
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
    ):
        """
        Encode up to 6 enemy units within perception radius.
        132 floats = 6 units × 22 features per unit. - MULTIPLE_WEAPONS_IMPLEMENTATION.md

        Asymmetric design: MORE complete information about enemies for tactical decisions.

        Uses unit["los_cache"] for visibility features (must be built explicitly before this call).

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
                active_col, active_row = require_unit_position(active_unit, game_state)
                other_col, other_row = require_unit_position(other_unit, game_state)
                d = calculate_hex_distance(active_col, active_row, other_col, other_row)
                if d <= perception_radius:
                    enemies.append((d, other_unit))
            from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range

            def _enemy_priority(item):
                distance, unit = item
                hp_cur = get_hp_from_cache(str(unit["id"]), game_state)
                hp_ratio = (hp_cur if hp_cur is not None else 0) / max(1, unit["HP_MAX"])
                can_attack = 0.0
                max_range = get_max_ranged_range(unit)
                if max_range > 0 and distance <= max_range:
                    can_attack = 1.0
                elif distance <= get_melee_range():
                    can_attack = 1.0
                return (
                    1000,
                    -((1.0 - hp_ratio) * 200),
                    can_attack * 100,
                    -distance * 10,
                )

            enemies.sort(key=_enemy_priority, reverse=True)
        
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 22
            if i < len(enemies):
                distance, enemy = enemies[i]
                
                # Feature 0-2: Position and distance
                enemy_col, enemy_row = require_unit_position(enemy, game_state)
                active_col, active_row = require_unit_position(active_unit, game_state)
                rel_col = (enemy_col - active_col) / 24.0
                rel_row = (enemy_row - active_row) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = distance / perception_radius
                
                # Feature 3-4: Health status (Phase 2: HP from cache; dead = 0)
                hp_cur = get_hp_from_cache(str(enemy["id"]), game_state)
                obs[feature_base + 3] = (hp_cur if hp_cur is not None else 0) / max(1, enemy["HP_MAX"])
                obs[feature_base + 4] = enemy["HP_MAX"] / 10.0
                
                # Feature 5-6: Movement tracking
                obs[feature_base + 5] = 1.0 if enemy["id"] in game_state["units_moved"] else 0.0
                obs[feature_base + 6] = self._calculate_movement_direction(enemy, active_unit, game_state)
                
                # Feature 7-9: Action tracking
                obs[feature_base + 7] = 1.0 if enemy["id"] in game_state["units_shot"] else 0.0
                obs[feature_base + 8] = 1.0 if enemy["id"] in game_state["units_charged"] else 0.0
                obs[feature_base + 9] = 1.0 if enemy["id"] in game_state["units_attacked"] else 0.0
                
                # Feature 10: Is valid target (basic check)
                current_phase = game_state["phase"]
                is_valid = 0.0
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
                from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
                if current_phase == "shoot":
                    max_range = get_max_ranged_range(active_unit)
                    is_valid = 1.0 if distance <= max_range else 0.0
                elif current_phase == "fight":
                    melee_range = get_melee_range()  # Always 1
                    is_valid = 1.0 if distance <= melee_range else 0.0
                obs[feature_base + 10] = is_valid
                
                # Feature 11-12: best_weapon_index + best_kill_probability (NOUVEAU)
                from engine.ai.weapon_selector import get_best_weapon_for_target
                best_weapon_idx, best_kill_prob = get_best_weapon_for_target(
                    active_unit, enemy, game_state, is_ranged=True
                )
                obs[feature_base + 11] = best_weapon_idx / 2.0 if best_weapon_idx >= 0 else 0.0
                obs[feature_base + 12] = best_kill_prob
                
                # Feature 13: danger_to_me (était feature 12) - DÉCALÉ
                obs[feature_base + 13] = self._calculate_danger_probability(active_unit, enemy, game_state)
                
                # Features 14-16: Allied coordination (3 floats, était 13-15) - DÉCALÉ
                visibility = 0.0
                combined_threat = 0.0
                units_cache = require_key(game_state, "units_cache")
                active_player = int(active_unit["player"]) if active_unit["player"] is not None else None
                if active_player is None:
                    raise ValueError(f"Active unit missing player: {active_unit}")
                for ally_id, cache_entry in units_cache.items():
                    if int(cache_entry["player"]) != active_player:
                        continue
                    ally = get_unit_by_id(str(ally_id), game_state)
                    if ally is None:
                        raise KeyError(f"Unit {ally_id} missing from game_state['units']")
                        target_id = str(enemy["id"])
                        los_cache = require_key(ally, "los_cache")
                        if target_id not in los_cache:
                            raise KeyError(f"los_cache missing target_id={target_id} for ally_id={ally.get('id')}")
                        if los_cache[target_id]:
                            visibility += 1.0
                    combined_threat += self._calculate_danger_probability(enemy, ally, game_state)
                obs[feature_base + 14] = min(1.0, visibility / 6.0)  # visibility_to_allies (était feature 13)
                obs[feature_base + 15] = min(1.0, combined_threat / 5.0)  # combined_friendly_threat (était feature 14)
                
                # Feature 16: melee_charge_preference (0.0-1.0) - AMÉLIORÉ POST-ÉTAPE 9
                # Compare TTK melee vs TTK range pour le meilleur allié melee
                # 1.0 = melee est beaucoup plus efficace (charge préféré)
                # 0.0 = range est plus efficace (ne chargerait pas)
                # 0.5 = équivalent
                from engine.ai.weapon_selector import get_best_weapon_for_target, calculate_ttk_with_weapon
                best_melee_ally = None
                best_melee_ttk = float('inf')
                best_range_ttk = float('inf')
                
                current_player = game_state["current_player"]
                for ally in game_state["units"]:
                    if (ally["player"] == current_player and 
                        is_unit_alive(str(ally["id"]), game_state) and
                        ally.get("CC_WEAPONS") and len(ally["CC_WEAPONS"]) > 0 and  # A des armes melee
                        ally.get("RNG_WEAPONS") and len(ally["RNG_WEAPONS"]) > 0):  # A aussi des armes range
                        
                        # Vérifier si peut charger (distance)
                        ally_col, ally_row = require_unit_position(ally, game_state)
                        enemy_col, enemy_row = require_unit_position(enemy, game_state)
                        ally_distance = calculate_pathfinding_distance(
                            ally_col, ally_row,
                            enemy_col, enemy_row,
                            game_state
                        )
                        if "MOVE" not in ally:
                            raise KeyError(f"Unit missing required 'MOVE' field: {ally}")
                        max_charge_range = ally["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
                        
                        if ally_distance <= max_charge_range:
                            # TTK avec meilleure arme melee
                            best_melee_weapon_idx, _ = get_best_weapon_for_target(
                                ally, enemy, game_state, is_ranged=False
                            )
                            melee_ttk = 100.0
                            if best_melee_weapon_idx >= 0:
                                melee_weapon = ally["CC_WEAPONS"][best_melee_weapon_idx]
                                melee_ttk = calculate_ttk_with_weapon(ally, melee_weapon, enemy, game_state)
                            
                            # TTK avec meilleure arme range
                            best_range_weapon_idx, _ = get_best_weapon_for_target(
                                ally, enemy, game_state, is_ranged=True
                            )
                            range_ttk = 100.0
                            if best_range_weapon_idx >= 0:
                                range_weapon = ally["RNG_WEAPONS"][best_range_weapon_idx]
                                range_ttk = calculate_ttk_with_weapon(ally, range_weapon, enemy, game_state)
                            
                            if melee_ttk < best_melee_ttk:
                                best_melee_ally = ally
                                best_melee_ttk = melee_ttk
                                best_range_ttk = range_ttk
                
                if best_melee_ally and best_range_ttk > 0:
                    # Normaliser: 1.0 si melee 2x plus rapide, 0.0 si range 2x plus rapide
                    ratio = best_range_ttk / best_melee_ttk if best_melee_ttk > 0 else 0.0
                    # Ratio > 1.0 = melee plus rapide (préféré)
                    # Ratio < 1.0 = range plus rapide (ne chargerait pas)
                    # Normaliser: (ratio - 0.5) * 2.0 maps 0.5->0.0, 1.0->1.0, 2.0->3.0 (clamp to 1.0)
                    obs[feature_base + 16] = min(1.0, max(0.0, (ratio - 0.5) * 2.0))
                else:
                    obs[feature_base + 16] = 0.0  # Pas d'allié melee ou pas de comparaison possible
                
                # Feature 17: target_efficiency (0.0-1.0) - AMÉLIORÉ POST-ÉTAPE 9
                # TTK avec ma meilleure arme contre cette cible
                # Normalisé: 1.0 = je peux tuer en 1 tour, 0.0 = je ne peux pas tuer (ou très lent)
                best_weapon_idx, _ = get_best_weapon_for_target(
                    active_unit, enemy, game_state, is_ranged=True
                )
                
                if best_weapon_idx >= 0 and active_unit.get("RNG_WEAPONS"):
                    weapon = active_unit["RNG_WEAPONS"][best_weapon_idx]
                    ttk = calculate_ttk_with_weapon(active_unit, weapon, enemy, game_state)
                    # Normaliser: 1.0 = ttk ≤ 1, 0.0 = ttk ≥ 5
                    obs[feature_base + 17] = max(0.0, min(1.0, 1.0 - (ttk - 1.0) / 4.0))
                else:
                    # Pas d'armes ranged, essayer melee
                    best_melee_weapon_idx, _ = get_best_weapon_for_target(
                        active_unit, enemy, game_state, is_ranged=False
                    )
                    if best_melee_weapon_idx >= 0 and active_unit.get("CC_WEAPONS"):
                        weapon = active_unit["CC_WEAPONS"][best_melee_weapon_idx]
                        ttk = calculate_ttk_with_weapon(active_unit, weapon, enemy, game_state)
                        obs[feature_base + 17] = max(0.0, min(1.0, 1.0 - (ttk - 1.0) / 4.0))
                    else:
                        obs[feature_base + 17] = 0.0  # Pas d'armes disponibles
                
                # Feature 18: is_adjacent (était feature 18 originale) - INCHANGÉ
                obs[feature_base + 18] = 1.0 if distance <= 1 else 0.0
                
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
            
            active_col, active_row = require_unit_position(active_unit, game_state)
            other_col, other_row = require_unit_position(other_unit, game_state)
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
                unit_col, unit_row = require_unit_position(unit, game_state)
                active_col, active_row = require_unit_position(active_unit, game_state)
                rel_col = (unit_col - active_col) / 24.0
                rel_row = (unit_row - active_row) / 24.0
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
                from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
                max_rng_range = get_max_ranged_range(unit)
                melee_range = get_melee_range()  # Always 1
                
                offensive_type = 1.0 if max_rng_range > melee_range else 0.0
                
                # LoS check using cache (only for enemies)
                has_los = 0.0
                if is_enemy > 0.5:
                    target_id = str(unit["id"])
                    active_los_cache = require_key(active_unit, "los_cache")
                    if target_id not in active_los_cache:
                        raise KeyError(f"los_cache missing target_id={target_id} for active_unit_id={active_unit.get('id')}")
                    has_los = 1.0 if active_los_cache[target_id] else 0.0
                
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
    
    def _get_valid_targets(self, active_unit: Dict[str, Any], game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                active_col, active_row = require_unit_position(active_unit, game_state)
                enemy_col, enemy_row = require_unit_position(enemy, game_state)
                distance = calculate_pathfinding_distance(
                    active_col, active_row, enemy_col, enemy_row, game_state
                )
                if distance <= active_unit["MOVE"] + 12:
                    valid_targets.append(enemy)
        elif current_phase == "fight":
            from engine.utils.weapon_helpers import get_melee_range
            melee_range = get_melee_range()
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
                active_col, active_row = require_unit_position(active_unit, game_state)
                enemy_col, enemy_row = require_unit_position(enemy, game_state)
                if calculate_hex_distance(
                    active_col, active_row, enemy_col, enemy_row
                ) <= melee_range:
                    valid_targets.append(enemy)
        return valid_targets
    
    def _get_six_reference_enemies(
        self, active_unit: Dict[str, Any], game_state: Dict[str, Any],
        valid_targets: List[Dict[str, Any]]
    ) -> List[tuple]:
        """
        Build the 6 reference enemies for obs[141:273] and enemy_index_map.
        Ensures every valid target is in the 6 so require_key(enemy_index_map, id) never fails.
        Returns list of (distance, unit) ordered: valid_targets first (up to 6), then fill by distance.
        """
        perception_radius = self.perception_radius
        active_col, active_row = require_unit_position(active_unit, game_state)
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
            oc, or_ = require_unit_position(other, game_state)
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
            dc = calculate_hex_distance(active_col, active_row, *require_unit_position(u, game_state))
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
    ):
        """
        Sort key for valid targets: (lower = higher priority).
        Returns (-strategic_efficiency, distance) so best targets sort first.
        """
        active_col, active_row = require_unit_position(active_unit, game_state)
        target_col, target_row = require_unit_position(target, game_state)
        distance = calculate_hex_distance(
            active_col, active_row, target_col, target_row
        )
        if "VALUE" not in target:
            raise KeyError(f"Target missing required 'VALUE' field: {target}")
        target_value = target["VALUE"]
        from engine.utils.weapon_helpers import get_selected_ranged_weapon
        from engine.ai.weapon_selector import get_best_weapon_for_target
        best_weapon_idx, _ = get_best_weapon_for_target(
            active_unit, target, game_state, is_ranged=True
        )
        if best_weapon_idx >= 0 and active_unit.get("RNG_WEAPONS"):
            weapon = active_unit["RNG_WEAPONS"][best_weapon_idx]
        else:
            selected_weapon = get_selected_ranged_weapon(active_unit)
            if selected_weapon:
                weapon = selected_weapon
            elif active_unit.get("RNG_WEAPONS"):
                weapon = active_unit["RNG_WEAPONS"][0]
            else:
                return (0.0, distance)
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
    ) -> List[Dict[str, Any]]:
        """Sort valid targets by strategic efficiency (best first). In-place then return."""
        valid_targets.sort(
            key=lambda t: self._target_priority_score(t, active_unit, game_state)
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
        if valid_targets is None:
            valid_targets = self._get_valid_targets(active_unit, game_state)
            self._sort_valid_targets(valid_targets, active_unit, game_state)
        if six_enemies is None:
            six_enemies = self._get_six_reference_enemies(
                active_unit, game_state, valid_targets
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
                
                # Feature 1: best_weapon_index (NOUVEAU, 0-2, normalisé / 2.0)
                from engine.ai.weapon_selector import get_best_weapon_for_target
                best_weapon_idx, best_kill_prob = get_best_weapon_for_target(
                    active_unit, target, game_state, is_ranged=True
                )
                obs[feature_base + 1] = best_weapon_idx / 2.0 if best_weapon_idx >= 0 else 0.0
                
                # Feature 2: best_kill_probability (NOUVEAU, remplace ancien feature 1)
                obs[feature_base + 2] = best_kill_prob
                
                # Feature 3: Danger to me (probability target kills ME next turn) - DÉCALÉ
                danger_prob = self._calculate_danger_probability(active_unit, target, game_state)
                obs[feature_base + 3] = danger_prob
                
                # Feature 4: Enemy index (reference to obs[141:273]) - DÉCALÉ
                enemy_idx = require_key(enemy_index_map, str(target["id"]))
                obs[feature_base + 4] = enemy_idx / 5.0
                
                # Feature 5: Distance (accessibility) - DÉCALÉ
                active_col, active_row = require_unit_position(active_unit, game_state)
                target_col, target_row = require_unit_position(target, game_state)
                distance = calculate_hex_distance(
                    active_col, active_row,
                    target_col, target_row
                )
                obs[feature_base + 5] = distance / perception_radius
                
                # Feature 6: Is priority target (moved toward me + high threat) - DÉCALÉ
                movement_dir = self._calculate_movement_direction(target, active_unit, game_state)
                is_approaching = 1.0 if movement_dir > 0.75 else 0.0
                danger = self._calculate_danger_probability(active_unit, target, game_state)
                is_priority = 1.0 if (is_approaching > 0.5 and danger > 0.5) else 0.0
                obs[feature_base + 6] = is_priority
                
                # Feature 7: Coordination bonus (can friendly melee charge after I shoot) - DÉCALÉ
                can_be_charged = 1.0 if self._can_melee_units_charge_target(target, game_state) else 0.0
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
                                   search_type: str) -> float:
        """Find nearest object (wall/friendly/enemy) in given direction."""
        perception_radius = self.perception_radius
        min_distance = 999.0
        
        if search_type == "wall":
            # Search walls in direction
            for wall_col, wall_row in game_state["wall_hexes"]:
                if self._is_in_direction(unit, wall_col, wall_row, game_state, dx, dy):
                    unit_col, unit_row = require_unit_position(unit, game_state)
                    dist = calculate_hex_distance(unit_col, unit_row, wall_col, wall_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist
        
        elif search_type in ["friendly", "enemy"]:
            # P1/P2: friendly = same player, enemy = opposite player (1->2, 2->1)
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
                    
                other_col, other_row = require_unit_position(other_unit, game_state)
                if self._is_in_direction(unit, other_col, other_row, game_state, dx, dy):
                    unit_col, unit_row = require_unit_position(unit, game_state)
                    dist = calculate_hex_distance(unit_col, unit_row, other_col, other_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist
        
        return min_distance if min_distance < 999.0 else perception_radius
    
    def _is_in_direction(self, unit: Dict[str, Any], target_col: int, target_row: int, game_state: Dict[str, Any],
                        dx: int, dy: int) -> bool:
        """Check if target is roughly in the specified direction from unit."""
        unit_col, unit_row = require_unit_position(unit, game_state)
        delta_col = target_col - unit_col
        delta_row = target_row - unit_row
        
        # Rough directional check (within 45-degree cone)
        if dx == 0:  # North/South
            return abs(delta_col) <= abs(delta_row) and (delta_row * dy > 0)
        elif dy == 0:  # East/West
            return abs(delta_row) <= abs(delta_col) and (delta_col * dx > 0)
        else:  # Diagonal
            return (delta_col * dx > 0) and (delta_row * dy > 0)
    
    def _find_edge_distance(self, unit: Dict[str, Any], dx: int, dy: int, game_state: Dict[str, Any]) -> float:
        """Calculate distance to board edge in given direction."""
        perception_radius = self.perception_radius
        if dx > 0:  # East
            unit_col, unit_row = require_unit_position(unit, game_state)
            edge_dist = game_state["board_cols"] - unit_col - 1
        elif dx < 0:  # West
            unit_col, unit_row = require_unit_position(unit, game_state)
            edge_dist = unit_col
        else:
            edge_dist = perception_radius
        
        if dy > 0:  # South
            unit_col, unit_row = require_unit_position(unit, game_state)
            edge_dist = min(edge_dist, game_state["board_rows"] - unit_row - 1)
        elif dy < 0:  # North
            unit_col, unit_row = require_unit_position(unit, game_state)
            edge_dist = min(edge_dist, unit_row)
        
        return float(edge_dist)
