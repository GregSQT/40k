#!/usr/bin/env python3
"""
observation_builder.py - Builds observations from game state
"""

import numpy as np
from typing import Dict, List, Any, Optional
from engine.combat_utils import calculate_hex_distance, has_line_of_sight
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
        
        # Validate required UPPERCASE fields
        required_fields = ["RNG_NB", "RNG_ATK", "RNG_STR", "RNG_AP", "RNG_DMG",
                          "CC_NB", "CC_ATK", "CC_STR", "CC_AP", "CC_DMG"]
        for field in required_fields:
            if field not in unit:
                raise KeyError(f"Unit missing required '{field}' field: {unit}")
        
        # Calculate EXPECTED ranged damage per turn
        ranged_expected = self._calculate_expected_damage(
            num_attacks=unit["RNG_NB"],
            to_hit_stat=unit["RNG_ATK"],
            strength=unit["RNG_STR"],
            target_toughness=target_T,
            ap=unit["RNG_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["RNG_DMG"]
        )
        
        # Calculate EXPECTED melee damage per turn
        melee_expected = self._calculate_expected_damage(
            num_attacks=unit["CC_NB"],
            to_hit_stat=unit["CC_ATK"],
            strength=unit["CC_STR"],
            target_toughness=target_T,
            ap=unit["CC_AP"],
            target_save=target_save,
            target_invul=target_invul,
            damage_per_wound=unit["CC_DMG"]
        )
        
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
        curr_col, curr_row = unit["col"], unit["row"]
        
        # Calculate movement toward/away from active unit
        prev_dist = calculate_hex_distance(
            prev_col, prev_row, 
            active_unit["col"], active_unit["row"]
        )
        curr_dist = calculate_hex_distance(
            curr_col, curr_row,
            active_unit["col"], active_unit["row"]
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
        # Use LoS cache if available (Phase 1 implementation)
        if "los_cache" in game_state and game_state["los_cache"]:
            cache_key = (shooter["id"], target["id"])
            if cache_key in game_state["los_cache"]:
                return 1.0 if game_state["los_cache"][cache_key] else 0.0
        
        # Fallback: calculate LoS (happens if cache not built yet)
        from engine.phase_handlers import shooting_handlers
        has_los = shooting_handlers._has_line_of_sight(game_state, shooter, target)
        return 1.0 if has_los else 0.0
    
    def _calculate_kill_probability(self, shooter: Dict[str, Any], target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """
        Calculate actual probability to kill target this turn considering W40K dice mechanics.
        
        Considers:
        - Hit probability (RNG_ATK vs d6)
        - Wound probability (RNG_STR vs target T)
        - Save failure probability (target saves vs RNG_AP)
        - Number of shots (RNG_NB)
        - Damage per successful wound (RNG_DMG)
        
        Returns: 0.0-1.0 probability
        """
        current_phase = game_state["phase"]
        
        if current_phase == "shoot":
            if "RNG_ATK" not in shooter or "RNG_STR" not in shooter or "RNG_DMG" not in shooter:
                raise KeyError(f"Shooter missing required ranged stats: {shooter}")
            if "RNG_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'RNG_NB' field: {shooter}")
            
            hit_target = shooter["RNG_ATK"]
            strength = shooter["RNG_STR"]
            damage = shooter["RNG_DMG"]
            num_attacks = shooter["RNG_NB"]
            ap = shooter.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in shooter or "CC_STR" not in shooter or "CC_DMG" not in shooter:
                raise KeyError(f"Shooter missing required melee stats: {shooter}")
            if "CC_NB" not in shooter:
                raise KeyError(f"Shooter missing required 'CC_NB' field: {shooter}")
            
            hit_target = shooter["CC_ATK"]
            strength = shooter["CC_STR"]
            damage = shooter["CC_DMG"]
            num_attacks = shooter["CC_NB"]
            ap = shooter.get("CC_AP", 0)
        
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
        - Distance (can they reach?)
        - Hit/wound/save probabilities
        - Number of attacks
        - Damage output
        
        Returns: 0.0-1.0 probability
        """
        distance = calculate_hex_distance(
            defender["col"], defender["row"],
            attacker["col"], attacker["row"]
        )
        
        can_use_ranged = distance <= attacker.get("RNG_RNG", 0)
        can_use_melee = distance <= attacker.get("CC_RNG", 0)
        
        if not can_use_ranged and not can_use_melee:
            return 0.0
        
        if can_use_ranged and not can_use_melee:
            if "RNG_ATK" not in attacker or "RNG_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["RNG_ATK"]
            strength = attacker["RNG_STR"]
            damage = attacker["RNG_DMG"]
            num_attacks = attacker.get("RNG_NB", 0)
            ap = attacker.get("RNG_AP", 0)
        else:
            if "CC_ATK" not in attacker or "CC_STR" not in attacker:
                return 0.0
            
            hit_target = attacker["CC_ATK"]
            strength = attacker["CC_STR"]
            damage = attacker["CC_DMG"]
            num_attacks = attacker.get("CC_NB", 0)
            ap = attacker.get("CC_AP", 0)
        
        if num_attacks == 0:
            return 0.0
        
        p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
        
        if "T" not in defender:
            return 0.0
        wound_target = self._calculate_wound_target(strength, defender["T"])
        p_wound = max(0.0, min(1.0, (7 - wound_target) / 6.0))
        
        save_target = _calculate_save_target(defender, ap)
        p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
        
        p_damage_per_attack = p_hit * p_wound * p_fail_save
        expected_damage = num_attacks * p_damage_per_attack * damage
        
        if expected_damage >= defender["HP_CUR"]:
            return 1.0
        else:
            return min(1.0, expected_damage / defender["HP_CUR"])
    
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
            unit_value = friendly.get("VALUE", 10.0)
            weighted_threat = danger * unit_value
            total_weighted_threat += weighted_threat
        
        all_weighted_threats = []
        for t in valid_targets:
            t_total = 0.0
            for friendly in friendly_units:
                danger = self._calculate_danger_probability(friendly, t)
                unit_value = friendly.get("VALUE", 10.0)
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
            
            unit_type = active_unit.get("unitType", "")
            
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
            
            target_hp = target.get("HP_MAX", 1)
            if target_hp <= 1:
                target_type = "swarm"
            elif target_hp <= 3:
                target_type = "troop"
            elif target_hp <= 6:
                target_type = "elite"
            else:
                target_type = "leader"
            
            return 1.0 if preferred == target_type else 0.3
            
        except Exception:
            return 0.5

    def _can_melee_units_charge_target(self, target: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if any friendly melee units can charge this target."""
        current_player = game_state["current_player"]
        
        for unit in game_state["units"]:
            if (unit["player"] == current_player and 
                unit["HP_CUR"] > 0 and
                unit["CC_DMG"] > 0):  # AI_TURN.md: Direct field access
                
                # Simple charge range check (2d6 movement + unit MOVE)
                distance = abs(unit["col"] - target["col"]) + abs(unit["row"] - target["row"])
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
        
        Structure (295 floats):
        - [0:10]    Global context (10 floats)
        - [10:18]   Active unit capabilities (8 floats)
        - [18:50]   Directional terrain (32 floats: 8 directions × 4 features)
        - [50:122]  Allied units (72 floats: 6 units × 12 features)
        - [122:260] Enemy units (138 floats: 6 units × 23 features)
        - [260:295] Valid targets (35 floats: 5 targets × 7 features)
        
        Asymmetric design: More complete information about enemies than allies.
        Agent discovers optimal tactical combinations through training.
        """
        obs = np.zeros(295, dtype=np.float32)
        
        # Get active unit (agent's current unit)
        active_unit = self._get_active_unit_for_observation(game_state)
        if not active_unit:
            # No active unit - return zero observation
            return obs
        
        # === SECTION 1: Global Context (10 floats) ===
        obs[0] = float(game_state["current_player"])
        obs[1] = {"move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}[game_state["phase"]]
        obs[2] = min(1.0, game_state["turn"] / 10.0)
        obs[3] = min(1.0, game_state["episode_steps"] / 100.0)
        obs[4] = active_unit["HP_CUR"] / active_unit["HP_MAX"]
        obs[5] = 1.0 if active_unit["id"] in game_state["units_moved"] else 0.0
        obs[6] = 1.0 if active_unit["id"] in game_state["units_shot"] else 0.0
        obs[7] = 1.0 if active_unit["id"] in game_state["units_attacked"] else 0.0
        
        # Count alive units for strategic awareness
        alive_friendlies = sum(1 for u in game_state["units"] 
                              if u["player"] == active_unit["player"] and u["HP_CUR"] > 0)
        alive_enemies = sum(1 for u in game_state["units"] 
                           if u["player"] != active_unit["player"] and u["HP_CUR"] > 0)
        max_nearby = self.max_nearby_units
        obs[8] = alive_friendlies / max(1, max_nearby)
        obs[9] = alive_enemies / max(1, max_nearby)
        
        # === SECTION 2: Active Unit Capabilities (8 floats) ===
        obs[10] = active_unit["MOVE"] / 12.0  # Normalize by max expected (bikes)
        obs[11] = active_unit["RNG_RNG"] / 24.0
        obs[12] = active_unit["RNG_DMG"] / 5.0
        obs[13] = active_unit["RNG_NB"] / 10.0
        obs[14] = active_unit["CC_RNG"] / 6.0
        obs[15] = active_unit["CC_DMG"] / 5.0
        obs[16] = active_unit["T"] / 10.0
        obs[17] = active_unit["ARMOR_SAVE"] / 6.0
        
        # === SECTION 3: Directional Terrain Awareness (32 floats) ===
        self._encode_directional_terrain(obs, active_unit, game_state, base_idx=18)
        
        # === SECTION 4: Allied Units (72 floats) ===
        self._encode_allied_units(obs, active_unit, game_state, base_idx=50)
        
        # === SECTION 5: Enemy Units (138 floats) ===
        self._encode_enemy_units(obs, active_unit, game_state, base_idx=122)
        
        # === SECTION 6: Valid Targets (35 floats) ===
        self._encode_valid_targets(obs, active_unit, game_state, base_idx=260)
        
        return obs
    
    # ============================================================================
    # HELPER METHODS
    # ============================================================================
    
    def _get_active_unit_for_observation(self, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get the active unit for observation encoding.
        AI_TURN.md COMPLIANCE: Uses activation pools (single source of truth).
        """
        current_phase = game_state["phase"]
        current_player = game_state["current_player"]
        
        # Get first eligible unit from current phase pool
        if current_phase == "move":
            pool = game_state.get("move_activation_pool", [])
        elif current_phase == "shoot":
            pool = game_state.get("shoot_activation_pool", [])
        elif current_phase == "charge":
            pool = game_state.get("charge_activation_pool", [])
        elif current_phase == "fight":
            pool = game_state.get("charging_activation_pool", [])
        else:
            pool = []
        
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
        5. movement_direction (0.0-1.0: fled far → charged at me)
        6. distance_normalized (distance / perception_radius)
        7. combat_mix_score (0.1-0.9: melee → ranged specialist)
        8. ranged_favorite_target (0.0-1.0: swarm → monster)
        9. melee_favorite_target (0.0-1.0: swarm → monster)
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
            
            distance = calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
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
                rel_col = (ally["col"] - active_unit["col"]) / 24.0
                rel_row = (ally["row"] - active_unit["row"]) / 24.0
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
                obs[feature_base + 8] = self._calculate_favorite_target(ally)
                obs[feature_base + 9] = self._calculate_favorite_target(ally)  # Same for both modes
                
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
        138 floats = 6 units × 23 features per unit.
        
        Asymmetric design: MORE complete information about enemies for tactical decisions.
        
        Features per enemy (23 floats):
        0. relative_col, 1. relative_row (egocentric position)
        2. distance_normalized (distance / perception_radius)
        3. hp_ratio (HP_CUR / HP_MAX)
        4. hp_capacity (HP_MAX normalized)
        5. has_moved, 6. movement_direction (temporal behavior)
        7. has_shot, 8. has_charged, 9. has_attacked
        10. is_valid_target (1.0 if can be shot/attacked now)
        11. kill_probability (0.0-1.0: chance I kill them this turn)
        12. danger_to_me (0.0-1.0: chance they kill ME next turn)
        13. visibility_to_allies (how many allies can see this enemy)
        14. combined_friendly_threat (total threat from all allies to this enemy)
        15. can_be_charged_by_melee (1.0 if friendly melee can reach)
        16. target_type_match (0.0-1.0: matchup quality)
        17. can_be_meleed (1.0 if I can melee them now)
        18. is_adjacent (1.0 if within melee range)
        19. is_in_range (1.0 if within my weapon range)
        20. combat_mix_score (enemy's ranged/melee preference)
        21. ranged_favorite_target (enemy's preferred ranged target)
        22. melee_favorite_target (enemy's preferred melee target)
        
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
            
            distance = calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
            )
            
            if distance <= perception_radius:
                enemies.append((distance, other_unit))
        
        # Sort by priority: closer > can_attack_me > wounded
        def enemy_priority(item):
            distance, unit = item
            hp_ratio = unit["HP_CUR"] / max(1, unit["HP_MAX"])
            
            # Check if enemy can attack me
            can_attack = 0.0
            if "RNG_RNG" in unit and distance <= unit["RNG_RNG"]:
                can_attack = 1.0
            elif "CC_RNG" in unit and distance <= unit["CC_RNG"]:
                can_attack = 1.0
            
            # Priority: enemies (always), closer (higher), can attack (higher), wounded (higher)
            return (
                1000,  # Enemy weight
                -distance * 10,  # Closer = higher priority
                can_attack * 100,  # Can attack me = much higher priority
                -(1.0 - hp_ratio) * 5  # More wounded = higher priority
            )
        
        enemies.sort(key=enemy_priority, reverse=True)
        
        # Encode up to 6 enemies
        max_encoded = 6
        for i in range(max_encoded):
            feature_base = base_idx + i * 23
            
            if i < len(enemies):
                distance, enemy = enemies[i]
                
                # Feature 0-2: Position and distance
                rel_col = (enemy["col"] - active_unit["col"]) / 24.0
                rel_row = (enemy["row"] - active_unit["row"]) / 24.0
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
                if current_phase == "shoot" and "RNG_RNG" in active_unit:
                    is_valid = 1.0 if distance <= active_unit["RNG_RNG"] else 0.0
                elif current_phase == "fight" and "CC_RNG" in active_unit:
                    is_valid = 1.0 if distance <= active_unit["CC_RNG"] else 0.0
                obs[feature_base + 10] = is_valid
                
                # Feature 11-12: Kill probability and danger
                obs[feature_base + 11] = self._calculate_kill_probability(active_unit, enemy, game_state)
                obs[feature_base + 12] = self._calculate_danger_probability(active_unit, enemy, game_state)
                
                # Feature 13-14: Allied coordination
                visibility = 0.0
                combined_threat = 0.0
                for ally in game_state["units"]:
                    if ally["player"] == active_unit["player"] and ally["HP_CUR"] > 0:
                        if self._check_los_cached(ally, enemy, game_state) > 0.5:
                            visibility += 1.0
                        combined_threat += self._calculate_danger_probability(enemy, ally, game_state)
                obs[feature_base + 13] = min(1.0, visibility / 6.0)
                obs[feature_base + 14] = min(1.0, combined_threat / 5.0)
                
                # Feature 15-19: Tactical flags
                obs[feature_base + 15] = 1.0 if self._can_melee_units_charge_target(enemy, game_state) else 0.0
                obs[feature_base + 16] = self._calculate_target_type_match(active_unit, enemy)
                obs[feature_base + 17] = 1.0 if ("CC_RNG" in active_unit and distance <= active_unit["CC_RNG"]) else 0.0
                obs[feature_base + 18] = 1.0 if distance <= 1 else 0.0
                
                in_range = 0.0
                if "RNG_RNG" in active_unit and distance <= active_unit["RNG_RNG"]:
                    in_range = 1.0
                elif "CC_RNG" in active_unit and distance <= active_unit["CC_RNG"]:
                    in_range = 1.0
                obs[feature_base + 19] = in_range
                
                # Feature 20-22: Enemy capabilities
                obs[feature_base + 20] = self._calculate_combat_mix_score(enemy)
                obs[feature_base + 21] = self._calculate_favorite_target(enemy)
                obs[feature_base + 22] = self._calculate_favorite_target(enemy)
            else:
                # Padding for empty slots
                for j in range(23):
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
            
            distance = calculate_hex_distance(
                active_unit["col"], active_unit["row"],
                other_unit["col"], other_unit["row"]
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
                rel_col = (unit["col"] - active_unit["col"]) / 24.0
                rel_row = (unit["row"] - active_unit["row"]) / 24.0
                dist_norm = distance / perception_radius
                hp_ratio = unit["HP_CUR"] / unit["HP_MAX"]
                is_enemy = 1.0 if unit["player"] != active_unit["player"] else 0.0
                
                # Threat calculation (potential damage to active unit)
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
                if "RNG_DMG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'RNG_DMG' field: {unit}")
                if "CC_DMG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'CC_DMG' field: {unit}")
                
                if is_enemy > 0.5:
                    threat = max(unit["RNG_DMG"], unit["CC_DMG"]) / 5.0
                else:
                    threat = 0.0
                
                # Defensive type encoding (Swarm=0.25, Troop=0.5, Elite=0.75, Leader=1.0)
                defensive_type = self._encode_defensive_type(unit)
                
                # Offensive type encoding (Melee=0.0, Ranged=1.0)
                # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
                if "RNG_RNG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'RNG_RNG' field: {unit}")
                if "CC_RNG" not in unit:
                    raise KeyError(f"Nearby unit missing required 'CC_RNG' field: {unit}")
                
                offensive_type = 1.0 if unit["RNG_RNG"] > unit["CC_RNG"] else 0.0
                
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
        35 floats = 5 actions × 7 features per action
        
        SIMPLIFIED from 9 to 7 features (removed redundant features with enemy section).
        
        CRITICAL DESIGN: obs[260 + action_offset*7] directly corresponds to action (4 + action_offset)
        Example: 
        - obs[260:267] = features for what happens if agent presses action 4
        - obs[267:274] = features for what happens if agent presses action 5
        
        This creates DIRECT causal relationship for RL learning:
        "When obs[261]=1.0 (high kill_probability), pressing action 4 gives high reward"
        
        Features per action slot (7 floats) - CORE TACTICAL ESSENTIALS:
        0. is_valid (1.0 = target exists, 0.0 = no target in this slot)
        1. kill_probability (0.0-1.0, probability to kill target this turn considering dice)
        2. danger_to_me (0.0-1.0, probability target kills ME next turn)
        3. enemy_index (0-5: which enemy in obs[122:260] this action targets)
        4. distance_normalized (hex_distance / perception_radius)
        5. is_priority_target (1.0 if moved toward me, high threat)
        6. coordination_bonus (1.0 if friendly melee can charge after I shoot)
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
            
            valid_targets = [
                get_unit_by_id(str(tid), game_state) 
                for tid in target_ids 
                if get_unit_by_id(str(tid), game_state)
            ]
            
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
                    
                    distance = calculate_hex_distance(
                        active_unit["col"], active_unit["row"],
                        enemy["col"], enemy["row"]
                    )
                    
                    # Max charge = MOVE + 12 (maximum 2d6 roll)
                    max_charge = active_unit["MOVE"] + 12
                    if distance <= max_charge:
                        valid_targets.append(enemy)
        
        elif current_phase == "fight":
            # Get valid melee targets (enemies within CC_RNG)
            # AI_TURN.md COMPLIANCE: Direct UPPERCASE field access
            if "CC_RNG" not in active_unit:
                raise KeyError(f"Active unit missing required 'CC_RNG' field: {active_unit}")
            
            for enemy in game_state["units"]:
                if "player" not in enemy or "HP_CUR" not in enemy:
                    raise KeyError(f"Enemy unit missing required fields: {enemy}")
                
                if enemy["player"] != active_unit["player"] and enemy["HP_CUR"] > 0:
                    if "col" not in enemy or "row" not in enemy:
                        raise KeyError(f"Enemy unit missing required position fields: {enemy}")
                    
                    distance = calculate_hex_distance(
                        active_unit["col"], active_unit["row"],
                        enemy["col"], enemy["row"]
                    )
                    
                    if distance <= active_unit["CC_RNG"]:
                        valid_targets.append(enemy)
        
        # Sort by distance (prioritize closer targets)
        valid_targets.sort(key=lambda t: calculate_hex_distance(
            active_unit["col"], active_unit["row"], t["col"], t["row"]
        ))
        
        # Build enemy index map for reference
        enemy_index_map = {}
        enemy_list = [u for u in game_state["units"] 
                     if u["player"] != active_unit["player"] and u["HP_CUR"] > 0]
        enemy_list.sort(key=lambda e: calculate_hex_distance(
            active_unit["col"], active_unit["row"], e["col"], e["row"]
        ))
        for idx, enemy in enumerate(enemy_list[:6]):
            enemy_index_map[enemy["id"]] = idx
        
        # Encode up to max_valid_targets (5 targets × 7 features = 35 floats)
        max_encoded = 5
        for i in range(max_encoded):
            feature_base = base_idx + i * 7
            
            if i < len(valid_targets):
                target = valid_targets[i]
                
                # Feature 0: Action validity (CRITICAL - tells agent this action works)
                obs[feature_base + 0] = 1.0
                
                # Feature 1: Kill probability (W40K dice mechanics)
                kill_prob = self._calculate_kill_probability(active_unit, target, game_state)
                obs[feature_base + 1] = kill_prob
                
                # Feature 2: Danger to me (probability target kills ME next turn)
                danger_prob = self._calculate_danger_probability(active_unit, target, game_state)
                obs[feature_base + 2] = danger_prob
                
                # Feature 3: Enemy index (reference to obs[122:260])
                enemy_idx = enemy_index_map.get(target["id"], 0)
                obs[feature_base + 3] = enemy_idx / 5.0
                
                # Feature 4: Distance (accessibility)
                distance = calculate_hex_distance(
                    active_unit["col"], active_unit["row"],
                    target["col"], target["row"]
                )
                obs[feature_base + 4] = distance / perception_radius
                
                # Feature 5: Is priority target (moved toward me + high threat)
                movement_dir = self._calculate_movement_direction(target, active_unit)
                is_approaching = 1.0 if movement_dir > 0.75 else 0.0
                danger = self._calculate_danger_probability(active_unit, target, game_state)
                is_priority = 1.0 if (is_approaching > 0.5 and danger > 0.5) else 0.0
                obs[feature_base + 5] = is_priority
                
                # Feature 6: Coordination bonus (can friendly melee charge after I shoot)
                can_be_charged = 1.0 if self._can_melee_units_charge_target(target, game_state) else 0.0
                obs[feature_base + 6] = can_be_charged
            else:
                # Padding for empty slots
                for j in range(7):
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
                    dist = calculate_hex_distance(unit["col"], unit["row"], wall_col, wall_row)
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist
        
        elif search_type in ["friendly", "enemy"]:
            target_player = unit["player"] if search_type == "friendly" else 1 - unit["player"]
            for other_unit in game_state["units"]:
                if other_unit["HP_CUR"] <= 0:
                    continue
                if other_unit["player"] != target_player:
                    continue
                if other_unit["id"] == unit["id"]:
                    continue
                    
                if self._is_in_direction(unit, other_unit["col"], other_unit["row"], game_state, dx, dy):
                    dist = calculate_hex_distance(unit["col"], unit["row"], 
                                                        other_unit["col"], other_unit["row"])
                    if dist < min_distance and dist <= perception_radius:
                        min_distance = dist
        
        return min_distance if min_distance < 999.0 else perception_radius
    
    def _is_in_direction(self, unit: Dict[str, Any], target_col: int, target_row: int, game_state: Dict[str, Any],
                        dx: int, dy: int) -> bool:
        """Check if target is roughly in the specified direction from unit."""
        delta_col = target_col - unit["col"]
        delta_row = target_row - unit["row"]
        
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
            edge_dist = game_state["board_cols"] - unit["col"] - 1
        elif dx < 0:  # West
            edge_dist = unit["col"]
        else:
            edge_dist = perception_radius
        
        if dy > 0:  # South
            edge_dist = min(edge_dist, game_state["board_rows"] - unit["row"] - 1)
        elif dy < 0:  # North
            edge_dist = min(edge_dist, unit["row"])
        
        return float(edge_dist)