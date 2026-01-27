#!/usr/bin/env python3
"""
observation_builder.py - Builds observations from game state
"""

import numpy as np
from typing import Dict, List, Any, Optional
from shared.data_validation import require_key
from engine.combat_utils import calculate_hex_distance, calculate_pathfinding_distance, has_line_of_sight, get_unit_coordinates
from engine.game_utils import get_unit_by_id
from engine.phase_handlers.shooting_handlers import _calculate_save_target, _calculate_wound_target

class ObservationBuilder:
    """Builds observations for the agent."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Initialize position cache for movement_direction feature
        self.last_unit_positions = {}
        
        # Load perception parameters from config
        obs_params = config.get("observation_params")
        if not obs_params:
            raise KeyError("Config missing required 'observation_params' field - check w40k_core.py config dict creation")  # ✓ CHANGE 3: Enforce required config
        
        # AI_OBSERVATION.md COMPLIANCE: No defaults - force explicit configuration
        # Cache as instance variables (read config ONCE, not 8 times)
        self.perception_radius = obs_params["perception_radius"]  # ✓ CHANGE 3: No default fallback
        self.max_nearby_units = obs_params.get("max_nearby_units", 10)  # ✓ CHANGE 3: Cache for line 553
        self.max_valid_targets = obs_params.get("max_valid_targets", 5)  # ✓ CHANGE 3: Cache for future use
        
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
        from shared.data_validation import require_key
        ranged_expected = 0.0
        if unit.get("RNG_WEAPONS"):
            for weapon in unit["RNG_WEAPONS"]:
                weapon_expected = self._calculate_expected_damage(
                    num_attacks=require_key(weapon, "NB"),
                    to_hit_stat=require_key(weapon, "ATK"),
                    strength=require_key(weapon, "STR"),
                    target_toughness=target_T,
                    ap=require_key(weapon, "AP"),
                    target_save=target_save,
                    target_invul=target_invul,
                    damage_per_wound=require_key(weapon, "DMG")
                )
                ranged_expected = max(ranged_expected, weapon_expected)
        
        # Calculate EXPECTED melee damage per turn (max from all melee weapons)
        melee_expected = 0.0
        if unit.get("CC_WEAPONS"):
            for weapon in unit["CC_WEAPONS"]:
                weapon_expected = self._calculate_expected_damage(
                    num_attacks=require_key(weapon, "NB"),
                    to_hit_stat=require_key(weapon, "ATK"),
                    strength=require_key(weapon, "STR"),
                    target_toughness=target_T,
                    ap=require_key(weapon, "AP"),
                    target_save=target_save,
                    target_invul=target_invul,
                    damage_per_wound=require_key(weapon, "DMG")
                )
                melee_expected = max(melee_expected, weapon_expected)
        
        total_expected = ranged_expected + melee_expected
        
        if total_expected == 0:
            return 0.5  # Neutral (no combat power)
        
        # Scale to 0.1-0.9 range
        raw_ratio = ranged_expected / total_expected
        return 0.1 + (raw_ratio * 0.8)
    
    def _calculate_expected_damage(self, num_attacks: int, to_hit_stat: int, 
                                   strength: int, target_toughness: int, ap: int, 
                                   target_save: int, target_invul: int, 
                                   damage_per_wound: int) -> float:
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
                                     active_unit: Dict[str, Any]) -> float:
        """
        Encode temporal behavior in single float - replaces frame stacking.
        
        Detects unit's movement pattern relative to active unit:
        - 0.00-0.24: Fled far from me (>50% MOVE away)
        - 0.25-0.49: Moved away slightly (<50% MOVE away)
        - 0.50-0.74: Advanced slightly (<50% MOVE toward)
        - 0.75-1.00: Charged at me (>50% MOVE toward)
        
        Critical for detecting threats before they strike!
        AI_TURN.md COMPLIANCE: Direct field access
        """
        # Get last known position from cache
        if not hasattr(self, 'last_unit_positions') or not self.last_unit_positions:
            return 0.5  # Unknown/first turn
        
        if "id" not in unit:
            raise KeyError(f"Unit missing required 'id' field: {unit}")
        
        unit_id = str(unit["id"])
        if unit_id not in self.last_unit_positions:
            return 0.5  # No previous position data
        
        # Validate required position fields
        if "col" not in unit or "row" not in unit:
            raise KeyError(f"Unit missing required position fields: {unit}")
        if "col" not in active_unit or "row" not in active_unit:
            raise KeyError(f"Active unit missing required position fields: {active_unit}")
        
        prev_col, prev_row = self.last_unit_positions[unit_id]
        curr_col, curr_row = get_unit_coordinates(unit)
        
        # Calculate movement toward/away from active unit
        active_col, active_row = get_unit_coordinates(active_unit)
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
        Check LoS using cache if available, fallback to calculation.
        AI_TURN.md COMPLIANCE: Direct field access, uses game_state cache.
        
        Returns:
        - 1.0 = Clear line of sight
        - 0.0 = Blocked line of sight
        """
        # AI_TURN_SHOOTING_UPDATE.md: Use shooter["los_cache"] (new architecture)
        target_id = target["id"]
        
        if "los_cache" in shooter and shooter["los_cache"]:
            if target_id in shooter["los_cache"]:
                return 1.0 if shooter["los_cache"][target_id] else 0.0
        
        # Fallback: calculate LoS (happens if cache not built yet or used outside shooting phase)
        from engine.phase_handlers import shooting_handlers
        has_los = shooting_handlers._has_line_of_sight(game_state, shooter, target)
        return 1.0 if has_los else 0.0
    
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
        from engine.utils.weapon_helpers import get_selected_ranged_weapon, get_selected_melee_weapon
        from engine.ai.weapon_selector import get_best_weapon_for_target

        if current_phase == "shoot":
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=True)
            if best_weapon_idx >= 0 and shooter.get("RNG_WEAPONS"):
                weapon = shooter["RNG_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected weapon
                weapon = get_selected_ranged_weapon(shooter)
                if not weapon and shooter.get("RNG_WEAPONS"):
                    weapon = shooter["RNG_WEAPONS"][0]  # Fallback to first weapon
                if not weapon:
                    return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
            ap = weapon["AP"]
        else:
            # Get best weapon for this target
            best_weapon_idx, _ = get_best_weapon_for_target(shooter, target, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and shooter.get("CC_WEAPONS"):
                weapon = shooter["CC_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected weapon
                weapon = get_selected_melee_weapon(shooter)
                if not weapon and shooter.get("CC_WEAPONS"):
                    weapon = shooter["CC_WEAPONS"][0]  # Fallback to first weapon
                if not weapon:
                    return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
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
        
        if expected_damage >= target["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / target["HP_CUR"])
    
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
        defender_col, defender_row = get_unit_coordinates(defender)
        attacker_col, attacker_row = get_unit_coordinates(attacker)
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
            if best_weapon_idx >= 0 and attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][best_weapon_idx]
            elif attacker.get("RNG_WEAPONS"):
                weapon = attacker["RNG_WEAPONS"][0]  # Fallback to first weapon
            else:
                self._danger_probability_cache[cache_key] = 0.0
                return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
            ap = weapon["AP"]
        else:
            # Use best melee weapon (or if both available, prefer melee if in range)
            best_weapon_idx, _ = get_best_weapon_for_target(attacker, defender, game_state, is_ranged=False)
            if best_weapon_idx >= 0 and attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][best_weapon_idx]
            elif attacker.get("CC_WEAPONS"):
                weapon = attacker["CC_WEAPONS"][0]  # Fallback to first weapon
            else:
                self._danger_probability_cache[cache_key] = 0.0
                return 0.0
            
            hit_target = weapon["ATK"]
            strength = weapon["STR"]
            damage = weapon["DMG"]
            num_attacks = weapon["NB"]
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
        
        if expected_damage >= defender["HP_CUR"]:
            self._danger_probability_cache[cache_key] = 1.0
            return 1.0
        else:
            result = min(1.0, expected_damage / defender["HP_CUR"])
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
            if u["player"] == my_player and u["HP_CUR"] > 0
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
                has_melee = any(require_key(w, "DMG") > 0 for w in unit["CC_WEAPONS"])
            
            if (unit["player"] == current_player and
                unit["HP_CUR"] > 0 and
                has_melee):  # Has melee capability

                # Charge range check using BFS pathfinding to respect walls
                unit_col, unit_row = get_unit_coordinates(unit)
                target_col, target_row = get_unit_coordinates(target)
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

    
    def build_observation(self, game_state: Dict[str, Any]) -> np.ndarray:
        """
        Build asymmetric egocentric observation vector with R=25 perception radius.
        AI_TURN.md COMPLIANCE: Direct UPPERCASE field access, no state copying.

        Structure (313 floats):
        - [0:15]    Global context (15 floats) - includes objective control
        - [15:37]   Active unit capabilities (22 floats) - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        - [37:69]   Directional terrain (32 floats: 8 directions × 4 features)
        - [69:141]  Allied units (72 floats: 6 units × 12 features)
        - [141:273] Enemy units (132 floats: 6 units × 22 features) - OPTIMISÉ
        - [273:313] Valid targets (40 floats: 5 targets × 8 features)

        Asymmetric design: More complete information about enemies than allies.
        Agent discovers optimal tactical combinations through training.
        """
        # PERFORMANCE: Clear per-observation cache (same pairs recalculated multiple times)
        self._danger_probability_cache = {}

        obs = np.zeros(self.obs_size, dtype=np.float32)
        
        # Get active unit (agent's current unit)
        active_unit = self._get_active_unit_for_observation(game_state)
        if not active_unit:
            # No active unit - return zero observation
            return obs
        
        # === SECTION 1: Global Context (15 floats) - includes objective control ===
        obs[0] = float(game_state["current_player"])
        phase_encoding = {"command": 0.0, "move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}
        obs[1] = phase_encoding.get(game_state["phase"], 0.0)  # Fallback à 0.0 si phase inconnue
        obs[2] = min(1.0, game_state["turn"] / 5.0)  # Normalized by max 5 turns
        obs[3] = min(1.0, game_state["episode_steps"] / 100.0)
        obs[4] = active_unit["HP_CUR"] / active_unit["HP_MAX"]
        obs[5] = 1.0 if active_unit["id"] in game_state["units_moved"] else 0.0
        obs[6] = 1.0 if active_unit["id"] in game_state["units_shot"] else 0.0
        obs[7] = 1.0 if active_unit["id"] in game_state["units_attacked"] else 0.0
        # ADVANCE_IMPLEMENTATION: Track if unit has advanced this turn
        obs[8] = 1.0 if active_unit["id"] in game_state.get("units_advanced", set()) else 0.0

        # Count alive units for strategic awareness
        alive_friendlies = sum(1 for u in game_state["units"]
                              if u["player"] == active_unit["player"] and u["HP_CUR"] > 0)
        alive_enemies = sum(1 for u in game_state["units"]
                           if u["player"] != active_unit["player"] and u["HP_CUR"] > 0)
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
            obs[18] = require_key(rng_weapons[0], "DMG") / 5.0
            obs[19] = require_key(rng_weapons[0], "NB") / 10.0
        else:
            obs[17] = obs[18] = obs[19] = 0.0

        # RNG_WEAPONS[1] (3 floats)
        if len(rng_weapons) > 1:
            obs[20] = require_key(rng_weapons[1], "RNG") / 24.0
            obs[21] = require_key(rng_weapons[1], "DMG") / 5.0
            obs[22] = require_key(rng_weapons[1], "NB") / 10.0
        else:
            obs[20] = obs[21] = obs[22] = 0.0

        # RNG_WEAPONS[2] (3 floats)
        if len(rng_weapons) > 2:
            obs[23] = require_key(rng_weapons[2], "RNG") / 24.0
            obs[24] = require_key(rng_weapons[2], "DMG") / 5.0
            obs[25] = require_key(rng_weapons[2], "NB") / 10.0
        else:
            obs[23] = obs[24] = obs[25] = 0.0

        # CC_WEAPONS[0] (5 floats: NB, ATK, STR, AP, DMG)
        cc_weapons = require_key(active_unit, "CC_WEAPONS")
        if len(cc_weapons) > 0:
            obs[26] = require_key(cc_weapons[0], "NB") / 10.0
            obs[27] = require_key(cc_weapons[0], "ATK") / 6.0
            obs[28] = require_key(cc_weapons[0], "STR") / 10.0
            obs[29] = require_key(cc_weapons[0], "AP") / 6.0
            obs[30] = require_key(cc_weapons[0], "DMG") / 5.0
        else:
            obs[26] = obs[27] = obs[28] = obs[29] = obs[30] = 0.0

        # CC_WEAPONS[1] (5 floats)
        if len(cc_weapons) > 1:
            obs[31] = require_key(cc_weapons[1], "NB") / 10.0
            obs[32] = require_key(cc_weapons[1], "ATK") / 6.0
            obs[33] = require_key(cc_weapons[1], "STR") / 10.0
            obs[34] = require_key(cc_weapons[1], "AP") / 6.0
            obs[35] = require_key(cc_weapons[1], "DMG") / 5.0
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
        self._encode_enemy_units(obs, active_unit, game_state, base_idx=142)

        # === SECTION 6: Valid Targets (40 floats) ===
        # Enemy Units: [142:274] = 132 floats (6 × 22 features)
        # base_idx = 142 + 132 = 274
        self._encode_valid_targets(obs, active_unit, game_state, base_idx=274)
        
        return obs
    
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
                    if unit["HP_CUR"] <= 0:
                        continue

                    unit_pos = get_unit_coordinates(unit)
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

    def _get_active_unit_for_observation(self, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get the active unit for observation encoding.
        AI_TURN.md COMPLIANCE: Uses activation pools (single source of truth).
        """
        current_phase = game_state["phase"]
        current_player = game_state["current_player"]
        
        # Get first eligible unit from current phase pool
        if current_phase == "move":
            pool = require_key(game_state, "move_activation_pool")
        elif current_phase == "shoot":
            pool = require_key(game_state, "shoot_activation_pool")
        elif current_phase == "charge":
            pool = require_key(game_state, "charge_activation_pool")
        elif current_phase == "fight":
            pool = require_key(game_state, "charging_activation_pool")
        elif current_phase == "command":
            # Command phase has no "active unit" for observation; return None so build_observation returns zeros
            return None
        else:
            raise KeyError(f"game_state phase must be move/shoot/charge/fight/command, got: {current_phase}")
        
        # Get first unit from pool that belongs to current player
        for unit_id in pool:
            unit = get_unit_by_id(str(unit_id), game_state)
            if unit and unit["player"] == current_player:
                return unit
        
        # Fallback: return any alive unit from current player
        for unit in game_state["units"]:
            if unit["player"] == current_player and unit["HP_CUR"] > 0:
                return unit
        
        return None
    
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
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            if "player" not in other_unit:
                raise KeyError(f"Unit missing required 'player' field: {other_unit}")
            if other_unit["player"] != active_unit["player"]:
                continue  # Skip enemies
            
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            active_col, active_row = get_unit_coordinates(active_unit)
            other_col, other_row = get_unit_coordinates(other_unit)
            distance = calculate_hex_distance(
                active_col, active_row,
                other_col, other_row
            )
            
            if distance <= perception_radius:
                allies.append((distance, other_unit))
        
        # Sort by priority: closer > wounded > can_still_act
        def ally_priority(item):
            distance, unit = item
            hp_ratio = unit["HP_CUR"] / max(1, unit["HP_MAX"])
            has_acted = 1.0 if unit["id"] in game_state.get("units_moved", set()) else 0.0
            
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
                ally_col, ally_row = get_unit_coordinates(ally)
                active_col, active_row = get_unit_coordinates(active_unit)
                rel_col = (ally_col - active_col) / 24.0
                rel_row = (ally_row - active_row) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                
                # Feature 2-3: Health status
                obs[feature_base + 2] = ally["HP_CUR"] / max(1, ally["HP_MAX"])
                obs[feature_base + 3] = ally["HP_MAX"] / 10.0
                
                # Feature 4: Has moved
                obs[feature_base + 4] = 1.0 if ally["id"] in game_state.get("units_moved", set()) else 0.0
                
                # Feature 5: Movement direction (temporal behavior)
                obs[feature_base + 5] = self._calculate_movement_direction(ally, active_unit)
                
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
    
    def _encode_enemy_units(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int):
        """
        Encode up to 6 enemy units within perception radius.
        132 floats = 6 units × 22 features per unit. - MULTIPLE_WEAPONS_IMPLEMENTATION.md
        
        Asymmetric design: MORE complete information about enemies for tactical decisions.
        
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
        """
        perception_radius = self.perception_radius
        # Get all enemy units within perception radius
        enemies = []
        for other_unit in game_state["units"]:
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if "player" not in other_unit:
                raise KeyError(f"Unit missing required 'player' field: {other_unit}")
            if other_unit["player"] == active_unit["player"]:
                continue  # Skip allies
            
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            active_col, active_row = get_unit_coordinates(active_unit)
            other_col, other_row = get_unit_coordinates(other_unit)
            distance = calculate_hex_distance(
                active_col, active_row,
                other_col, other_row
            )
            
            if distance <= perception_radius:
                enemies.append((distance, other_unit))
        
        # Sort by priority: wounded > can_attack_me > closer
        # Wounded enemies are tactical priorities for focus fire
        def enemy_priority(item):
            distance, unit = item
            hp_ratio = unit["HP_CUR"] / max(1, unit["HP_MAX"])

            # Check if enemy can attack me
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max range from weapons
            from engine.utils.weapon_helpers import get_max_ranged_range, get_melee_range
            can_attack = 0.0
            max_range = get_max_ranged_range(unit)
            if max_range > 0 and distance <= max_range:
                can_attack = 1.0
            else:
                melee_range = get_melee_range()  # Always 1
                if distance <= melee_range:
                    can_attack = 1.0

            # Priority: wounded (highest), can attack (high), closer (low)
            # More wounded = HIGHER priority for focus fire learning
            return (
                1000,  # Enemy weight
                -((1.0 - hp_ratio) * 200),  # More wounded = much higher priority
                can_attack * 100,  # Can attack me = high priority
                -distance * 10,  # Closer = higher priority
            )
        
        enemies.sort(key=enemy_priority, reverse=True)
        
        # Encode up to 6 enemies
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 22  # Changed from 23 to 22 (removed 2 features)
            
            if i < len(enemies):
                distance, enemy = enemies[i]
                
                # Feature 0-2: Position and distance
                enemy_col, enemy_row = get_unit_coordinates(enemy)
                active_col, active_row = get_unit_coordinates(active_unit)
                rel_col = (enemy_col - active_col) / 24.0
                rel_row = (enemy_row - active_row) / 24.0
                obs[feature_base + 0] = np.clip(rel_col, -1.0, 1.0)
                obs[feature_base + 1] = np.clip(rel_row, -1.0, 1.0)
                obs[feature_base + 2] = distance / perception_radius
                
                # Feature 3-4: Health status
                obs[feature_base + 3] = enemy["HP_CUR"] / max(1, enemy["HP_MAX"])
                obs[feature_base + 4] = enemy["HP_MAX"] / 10.0
                
                # Feature 5-6: Movement tracking
                obs[feature_base + 5] = 1.0 if enemy["id"] in game_state.get("units_moved", set()) else 0.0
                obs[feature_base + 6] = self._calculate_movement_direction(enemy, active_unit)
                
                # Feature 7-9: Action tracking
                obs[feature_base + 7] = 1.0 if enemy["id"] in game_state.get("units_shot", set()) else 0.0
                obs[feature_base + 8] = 1.0 if enemy["id"] in game_state.get("units_charged", set()) else 0.0
                obs[feature_base + 9] = 1.0 if enemy["id"] in game_state.get("units_attacked", set()) else 0.0
                
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
                for ally in game_state["units"]:
                    if ally["player"] == active_unit["player"] and ally["HP_CUR"] > 0:
                        if self._check_los_cached(ally, enemy, game_state) > 0.5:
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
                        ally["HP_CUR"] > 0 and
                        ally.get("CC_WEAPONS") and len(ally["CC_WEAPONS"]) > 0 and  # A des armes melee
                        ally.get("RNG_WEAPONS") and len(ally["RNG_WEAPONS"]) > 0):  # A aussi des armes range
                        
                        # Vérifier si peut charger (distance)
                        ally_col, ally_row = get_unit_coordinates(ally)
                        enemy_col, enemy_row = get_unit_coordinates(enemy)
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
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "HP_CUR" not in other_unit:
                raise KeyError(f"Unit missing required 'HP_CUR' field: {other_unit}")
            
            if other_unit["HP_CUR"] <= 0:
                continue
            if other_unit["id"] == active_unit["id"]:
                continue
            
            # AI_TURN.md COMPLIANCE: Direct field access
            if "col" not in other_unit or "row" not in other_unit:
                raise KeyError(f"Unit missing required position fields: {other_unit}")
            
            active_col, active_row = get_unit_coordinates(active_unit)
            other_col, other_row = get_unit_coordinates(other_unit)
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
                if "HP_CUR" not in unit:
                    raise KeyError(f"Nearby unit missing required 'HP_CUR' field: {unit}")
                if "HP_MAX" not in unit:
                    raise KeyError(f"Nearby unit missing required 'HP_MAX' field: {unit}")
                if "player" not in unit:
                    raise KeyError(f"Nearby unit missing required 'player' field: {unit}")
                
                # Relative position (egocentric)
                unit_col, unit_row = get_unit_coordinates(unit)
                active_col, active_row = get_unit_coordinates(active_unit)
                rel_col = (unit_col - active_col) / 24.0
                rel_row = (unit_row - active_row) / 24.0
                dist_norm = distance / perception_radius
                hp_ratio = unit["HP_CUR"] / unit["HP_MAX"]
                is_enemy = 1.0 if unit["player"] != active_unit["player"] else 0.0
                
                # Threat calculation (potential damage to active unit)
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use max damage from all weapons
                from shared.data_validation import require_key
                rng_weapons = require_key(unit, "RNG_WEAPONS")
                cc_weapons = require_key(unit, "CC_WEAPONS")
                
                max_rng_dmg = max((require_key(w, "DMG") for w in rng_weapons), default=0.0)
                max_cc_dmg = max((require_key(w, "DMG") for w in cc_weapons), default=0.0)
                
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
                
                # LoS check using cache
                has_los = self._check_los_cached(active_unit, unit, game_state)
                
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
    
    def _encode_valid_targets(self, obs: np.ndarray, active_unit: Dict[str, Any], game_state: Dict[str, Any], base_idx: int):
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
        
        # Get valid targets based on current phase
        valid_targets = []
        current_phase = game_state["phase"]
        
        if current_phase == "shoot":
            # Get valid shooting targets using shooting handler
            from engine.phase_handlers import shooting_handlers
            
            # Build target pool using handler's validation
            target_ids = shooting_handlers.shooting_build_valid_target_pool(
                game_state, active_unit["id"]
            )
            
            # PERFORMANCE: Call get_unit_by_id once per target, not twice
            valid_targets = []
            for tid in target_ids:
                unit = get_unit_by_id(str(tid), game_state)
                if unit:
                    valid_targets.append(unit)
            
        elif current_phase == "charge":
            # Get valid charge targets (enemies within charge range)
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "MOVE" not in active_unit:
                raise KeyError(f"Active unit missing required 'MOVE' field: {active_unit}")

            for enemy in game_state["units"]:
                # AI_TURN.md COMPLIANCE: Direct field access with validation
                if "player" not in enemy:
                    raise KeyError(f"Enemy unit missing required 'player' field: {enemy}")
                if "HP_CUR" not in enemy:
                    raise KeyError(f"Enemy unit missing required 'HP_CUR' field: {enemy}")

                if enemy["player"] != active_unit["player"] and enemy["HP_CUR"] > 0:
                    if "col" not in enemy or "row" not in enemy:
                        raise KeyError(f"Enemy unit missing required position fields: {enemy}")

                    # Use BFS pathfinding distance for charge reachability (respects walls)
                    active_col, active_row = get_unit_coordinates(active_unit)
                    enemy_col, enemy_row = get_unit_coordinates(enemy)
                    distance = calculate_pathfinding_distance(
                        active_col, active_row,
                        enemy_col, enemy_row,
                        game_state
                    )

                    # Max charge = MOVE + 12 (maximum 2d6 roll)
                    max_charge = active_unit["MOVE"] + 12
                    if distance <= max_charge:
                        valid_targets.append(enemy)
        
        elif current_phase == "fight":
            # Get valid melee targets (enemies within melee range)
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Melee range is always 1
            from engine.utils.weapon_helpers import get_melee_range
            melee_range = get_melee_range()  # Always 1

            for enemy in game_state["units"]:
                if "player" not in enemy or "HP_CUR" not in enemy:
                    raise KeyError(f"Enemy unit missing required fields: {enemy}")

                if enemy["player"] != active_unit["player"] and enemy["HP_CUR"] > 0:
                    if "col" not in enemy or "row" not in enemy:
                        raise KeyError(f"Enemy unit missing required position fields: {enemy}")

                    # Melee range is always 1 (adjacent), so pathfinding vs hex distance
                    # is equivalent for melee. Use hex distance for performance.
                    active_col, active_row = get_unit_coordinates(active_unit)
                    enemy_col, enemy_row = get_unit_coordinates(enemy)
                    distance = calculate_hex_distance(
                        active_col, active_row,
                        enemy_col, enemy_row
                    )

                    if distance <= melee_range:
                        valid_targets.append(enemy)
        
        # Sort by priority: VALUE / turns_to_kill (strategic efficiency)
        # This prioritizes targets that give best point return per activation spent
        # Validated: All targets already passed LoS check in shooting_build_valid_target_pool
        def target_priority(target):
            active_col, active_row = get_unit_coordinates(active_unit)
            target_col, target_row = get_unit_coordinates(target)
            distance = calculate_hex_distance(
                active_col, active_row,
                target_col, target_row
            )

            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access - no defaults
            if "VALUE" not in target:
                raise KeyError(f"Target missing required 'VALUE' field: {target}")
            target_value = target["VALUE"]

            # Calculate activations needed to kill this target
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Use selected weapon or best weapon for target
            from engine.utils.weapon_helpers import get_selected_ranged_weapon
            from engine.ai.weapon_selector import get_best_weapon_for_target
            
            # Get best weapon for this target (for priority calculation)
            best_weapon_idx, _ = get_best_weapon_for_target(active_unit, target, game_state, is_ranged=True)
            if best_weapon_idx >= 0 and active_unit.get("RNG_WEAPONS"):
                weapon = active_unit["RNG_WEAPONS"][best_weapon_idx]
            else:
                # Fallback to selected weapon or first weapon
                selected_weapon = get_selected_ranged_weapon(active_unit)
                if selected_weapon:
                    weapon = selected_weapon
                elif active_unit.get("RNG_WEAPONS"):
                    weapon = active_unit["RNG_WEAPONS"][0]
                else:
                    # No ranged weapons - can't calculate priority
                    return 0.0
            
            unit_attacks = weapon["NB"]
            unit_bs = weapon["ATK"]
            unit_s = weapon["STR"]
            unit_ap = weapon["AP"]
            unit_dmg = weapon["DMG"]

            if "T" not in target:
                raise KeyError(f"Target missing required 'T' field: {target}")
            if "ARMOR_SAVE" not in target:
                raise KeyError(f"Target missing required 'ARMOR_SAVE' field: {target}")
            if "HP_CUR" not in target:
                raise KeyError(f"Target missing required 'HP_CUR' field: {target}")

            target_t = target["T"]
            target_save = target["ARMOR_SAVE"]
            target_hp = target["HP_CUR"]

            # Our hit probability
            our_hit_prob = (7 - unit_bs) / 6.0

            # Our wound probability (S vs T)
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

            # Target's failed save probability (AP is negative, subtract to worsen save)
            target_modified_save = target_save - unit_ap
            if target_modified_save > 6:
                target_failed_save = 1.0
            else:
                target_failed_save = (target_modified_save - 1) / 6.0

            # Expected damage per activation
            damage_per_attack = our_hit_prob * our_wound_prob * target_failed_save * unit_dmg
            expected_damage_per_activation = unit_attacks * damage_per_attack

            # Expected activations to kill
            if expected_damage_per_activation > 0:
                activations_to_kill = target_hp / expected_damage_per_activation
            else:
                activations_to_kill = 100  # Can't kill = very low priority

            # Strategic efficiency = VALUE / turns_to_kill
            # Higher = better target (more points per activation spent)
            if activations_to_kill > 0:
                strategic_efficiency = target_value / activations_to_kill
            else:
                strategic_efficiency = target_value * 100  # Instant kill = very high priority

            # Priority scoring (lower = higher priority)
            return (
                -strategic_efficiency,       # Higher efficiency = lower score = first
                distance                     # Closer = lower score (tiebreaker)
            )

        valid_targets.sort(key=target_priority)
        
        # Build enemy index map for reference
        enemy_index_map = {}
        enemy_list = [u for u in game_state["units"] 
                     if u["player"] != active_unit["player"] and u["HP_CUR"] > 0]
        active_col, active_row = get_unit_coordinates(active_unit)
        enemy_list.sort(key=lambda e: calculate_hex_distance(
            active_col, active_row, *get_unit_coordinates(e)
        ))
        for idx, enemy in enumerate(enemy_list[:6]):
            enemy_index_map[enemy["id"]] = idx
        
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
                active_col, active_row = get_unit_coordinates(active_unit)
                target_col, target_row = get_unit_coordinates(target)
                distance = calculate_hex_distance(
                    active_col, active_row,
                    target_col, target_row
                )
                obs[feature_base + 5] = distance / perception_radius
                
                # Feature 6: Is priority target (moved toward me + high threat) - DÉCALÉ
                movement_dir = self._calculate_movement_direction(target, active_unit)
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
                    unit_col, unit_row = get_unit_coordinates(unit)
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
                if other_unit["HP_CUR"] <= 0:
                    continue
                if other_unit["player"] != target_player:
                    continue
                if other_unit["id"] == unit["id"]:
                    continue
                    
                other_col, other_row = get_unit_coordinates(other_unit)
                if self._is_in_direction(unit, other_col, other_row, game_state, dx, dy):
                    unit_col, unit_row = get_unit_coordinates(unit)
                    dist = calculate_hex_distance(unit_col, unit_row, other_col, other_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist
        
        return min_distance if min_distance < 999.0 else perception_radius
    
    def _is_in_direction(self, unit: Dict[str, Any], target_col: int, target_row: int, game_state: Dict[str, Any],
                        dx: int, dy: int) -> bool:
        """Check if target is roughly in the specified direction from unit."""
        unit_col, unit_row = get_unit_coordinates(unit)
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
            unit_col, unit_row = get_unit_coordinates(unit)
            edge_dist = game_state["board_cols"] - unit_col - 1
        elif dx < 0:  # West
            unit_col, unit_row = get_unit_coordinates(unit)
            edge_dist = unit_col
        else:
            edge_dist = perception_radius
        
        if dy > 0:  # South
            unit_col, unit_row = get_unit_coordinates(unit)
            edge_dist = min(edge_dist, game_state["board_rows"] - unit_row - 1)
        elif dy < 0:  # North
            unit_col, unit_row = get_unit_coordinates(unit)
            edge_dist = min(edge_dist, unit_row)
        
        return float(edge_dist)
