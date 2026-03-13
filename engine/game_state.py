#!/usr/bin/env python3
"""
game_state.py - Game state initialization and management
"""

from typing import Dict, List, Any, Optional, Tuple
import copy
import json
from pathlib import Path
from shared.data_validation import require_key
from engine.combat_utils import normalize_coordinates, get_unit_coordinates, resolve_dice_value
from engine.phase_handlers.shared_utils import is_unit_alive

class GameStateManager:
    """Manages game state."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.unit_registry = unit_registry
    
    # ============================================================================
    # UNIT MANAGEMENT
    # ============================================================================
    
    def initialize_units(self, game_state: Dict[str, Any]):
        """Initialize units with UPPERCASE field validation."""
        # AI_TURN.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field")
        unit_configs = self.config["units"]
        
        for unit_config in unit_configs:
            unit = self.create_unit(unit_config)
            self.validate_uppercase_fields(unit)
            game_state["units"].append(unit)
    
    def create_unit(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create unit with AI_TURN.md compliant fields."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
        rng_weapons = copy.deepcopy(require_key(config, "RNG_WEAPONS"))
        cc_weapons = copy.deepcopy(require_key(config, "CC_WEAPONS"))
        
        if not rng_weapons and not cc_weapons:
            raise ValueError(f"Unit {config.get('id', 'unknown')} must have at least RNG_WEAPONS or CC_WEAPONS")
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
        selected_rng_weapon_index = 0 if rng_weapons else None
        selected_cc_weapon_index = 0 if cc_weapons else None
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
        shoot_left = 0
        if rng_weapons and selected_rng_weapon_index is not None:
            selected_weapon = rng_weapons[selected_rng_weapon_index]
            shoot_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_shoot_left",
            )
        
        attack_left = 0
        if cc_weapons and selected_cc_weapon_index is not None:
            selected_weapon = cc_weapons[selected_cc_weapon_index]
            attack_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_attack_left",
            )
        
        unit_rules = copy.deepcopy(config["UNIT_RULES"]) if "UNIT_RULES" in config else []
        unit_keywords = copy.deepcopy(require_key(config, "UNIT_KEYWORDS"))
        return {
            # Identity
            "id": config["id"],
            "player": config["player"],
            "unitType": config["unitType"],  # NO DEFAULTS - must be provided
            "DISPLAY_NAME": config["DISPLAY_NAME"],
            
            # Position
            "col": normalize_coordinates(config["col"], config["row"])[0],
            "row": normalize_coordinates(config["col"], config["row"])[1],
            
            # UPPERCASE STATS (AI_TURN.md requirement) - NO DEFAULTS
            "HP_CUR": config["HP_CUR"],
            "HP_MAX": config["HP_MAX"],
            "MOVE": config["MOVE"],
            "T": config["T"],
            "ARMOR_SAVE": config["ARMOR_SAVE"],
            "INVUL_SAVE": config["INVUL_SAVE"],
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
            "RNG_WEAPONS": rng_weapons,
            "CC_WEAPONS": cc_weapons,
            "selectedRngWeaponIndex": selected_rng_weapon_index,
            "selectedCcWeaponIndex": selected_cc_weapon_index,
            
            # Required stats - NO DEFAULTS
            "LD": config["LD"],
            "OC": config["OC"],
            "VALUE": config["VALUE"],
            "ICON": config["ICON"],
            "ICON_SCALE": config["ICON_SCALE"],
            "UNIT_RULES": unit_rules,
            "UNIT_KEYWORDS": unit_keywords,
            
            # AI_TURN.md action tracking fields
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left
        }
    
    def validate_uppercase_fields(self, unit: Dict[str, Any]):
        """Validate unit uses UPPERCASE field naming convention."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons instead of individual weapon fields
        required_uppercase = {
            "HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
            "RNG_WEAPONS", "CC_WEAPONS",
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE", "UNIT_RULES", "UNIT_KEYWORDS",
            "SHOOT_LEFT", "ATTACK_LEFT"
        }
        
        for field in required_uppercase:
            if field not in unit:
                raise ValueError(f"Unit {unit['id']} missing required UPPERCASE field: {field}")
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
        rng_weapons = require_key(unit, "RNG_WEAPONS")
        cc_weapons = require_key(unit, "CC_WEAPONS")
        if not rng_weapons and not cc_weapons:
            raise ValueError(f"Unit {unit['id']} must have at least RNG_WEAPONS or CC_WEAPONS")
    
    def load_units_from_scenario(self, scenario_file, unit_registry):
            """Load units from scenario file - NO FALLBACKS ALLOWED."""
            if not scenario_file:
                raise ValueError("scenario_file is required - no fallbacks allowed")
            if not unit_registry:
                raise ValueError("unit_registry is required - no fallbacks allowed")
            
            import json
            import os
            import random
            
            if not os.path.exists(scenario_file):
                raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
            
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
            except Exception as e:
                raise ValueError(f"Failed to parse scenario file {scenario_file}: {e}")
            
            scenario_roster_info: Optional[Dict[str, Any]] = None
            if isinstance(scenario_data, list):
                basic_units = scenario_data
            elif isinstance(scenario_data, dict) and "units" in scenario_data:
                basic_units = scenario_data["units"]
            elif isinstance(scenario_data, dict) and "p1_roster_ref" in scenario_data and "p2_roster_ref" in scenario_data:
                basic_units, scenario_roster_info = self._load_units_from_roster_refs(
                    scenario_data=scenario_data,
                    scenario_file=scenario_file
                )
            else:
                raise ValueError(
                    f"Invalid scenario format in {scenario_file}: must have 'units' array or "
                    f"'p1_roster_ref'+'p2_roster_ref'"
                )
            
            if not basic_units:
                raise ValueError(f"Scenario file {scenario_file} contains no units")

            deployment_zone = None
            deployment_type = "fixed"
            deployment_type_by_player: Dict[int, str] = {1: "fixed", 2: "fixed"}
            resolved_scenario_walls = None
            resolved_scenario_objectives = None
            if isinstance(scenario_data, dict):
                has_wall_hexes = "wall_hexes" in scenario_data
                has_wall_ref = "wall_ref" in scenario_data
                if has_wall_hexes and has_wall_ref:
                    raise ValueError(
                        f"Scenario file {scenario_file} cannot define both 'wall_hexes' and 'wall_ref'"
                    )
                if has_wall_hexes:
                    resolved_scenario_walls = require_key(scenario_data, "wall_hexes")
                elif has_wall_ref:
                    resolved_scenario_walls = self._load_shared_walls_from_ref(
                        require_key(scenario_data, "wall_ref"),
                        scenario_file
                    )

                has_objectives_inline = "objectives" in scenario_data
                has_objective_hexes_legacy = "objective_hexes" in scenario_data
                has_objectives_ref = "objectives_ref" in scenario_data
                if has_objectives_ref and (has_objectives_inline or has_objective_hexes_legacy):
                    raise ValueError(
                        f"Scenario file {scenario_file} cannot define both objectives inline and 'objectives_ref'"
                    )
                if has_objectives_ref:
                    resolved_scenario_objectives = self._load_shared_objectives_from_ref(
                        require_key(scenario_data, "objectives_ref"),
                        scenario_file
                    )
                elif has_objectives_inline:
                    resolved_scenario_objectives = require_key(scenario_data, "objectives")
                elif has_objective_hexes_legacy:
                    resolved_scenario_objectives = require_key(scenario_data, "objective_hexes")

                has_deployment_zone = "deployment_zone" in scenario_data
                has_deployment_type = "deployment_type" in scenario_data
                has_deployment_type_p1 = "deployment_type_P1" in scenario_data
                has_deployment_type_p2 = "deployment_type_P2" in scenario_data
                has_any_deployment_type = (
                    has_deployment_type
                    or has_deployment_type_p1
                    or has_deployment_type_p2
                )
                if has_deployment_zone or has_any_deployment_type:
                    if not has_deployment_zone:
                        raise KeyError(
                            f"Scenario file {scenario_file} requires 'deployment_zone' when deployment type is configured"
                        )
                    deployment_zone = require_key(scenario_data, "deployment_zone")
                    if has_deployment_type:
                        deployment_type = require_key(scenario_data, "deployment_type")
                    else:
                        deployment_type = "fixed"
                    deployment_type_p1 = (
                        require_key(scenario_data, "deployment_type_P1")
                        if has_deployment_type_p1
                        else deployment_type
                    )
                    deployment_type_p2 = (
                        require_key(scenario_data, "deployment_type_P2")
                        if has_deployment_type_p2
                        else deployment_type
                    )
                    deployment_type_by_player = {
                        1: deployment_type_p1,
                        2: deployment_type_p2,
                    }
                valid_deployment_types = ("random", "fixed", "active")
                for player_id, player_deployment_type in deployment_type_by_player.items():
                    if player_deployment_type not in valid_deployment_types:
                        raise ValueError(
                            f"Invalid deployment type for player {player_id}: '{player_deployment_type}' "
                            f"in {scenario_file} (expected one of {valid_deployment_types})"
                        )
            
            wall_hex_set = set()
            if resolved_scenario_walls is not None:
                wall_hex_set = {(int(col), int(row)) for col, row in resolved_scenario_walls}
            
            from config_loader import get_config_loader
            config_loader = get_config_loader()
            board_config = config_loader.get_board_config()
            board_spec = board_config["default"] if "default" in board_config else board_config
            board_cols = require_key(board_spec, "cols")
            board_rows = require_key(board_spec, "rows")
            if board_cols <= 0 or board_rows <= 0:
                raise ValueError(f"Invalid board dimensions: cols={board_cols}, rows={board_rows}")

            def _is_valid_deploy_hex(col: int, row: int) -> bool:
                if col < 0 or col >= board_cols or row < 0 or row >= board_rows:
                    return False
                if row == board_rows - 1 and (col % 2) == 1:
                    return False
                return True

            deploy_pools = {}
            if deployment_zone:
                if deployment_zone not in ("hammer", "hammer_tutorial"):
                    raise ValueError(
                        f"Unsupported deployment_zone '{deployment_zone}' in {scenario_file}"
                    )
                project_root = os.path.dirname(os.path.dirname(__file__))
                deployment_path = os.path.join(
                    project_root, "config", "deployment", f"{deployment_zone}.json"
                )
                if not os.path.exists(deployment_path):
                    raise FileNotFoundError(f"Deployment file not found: {deployment_path}")
                try:
                    with open(deployment_path, "r") as f:
                        deployment_data = json.load(f)
                except Exception as e:
                    raise ValueError(f"Failed to parse deployment file {deployment_path}: {e}")
                if "p1" not in deployment_data or "p2" not in deployment_data:
                    raise KeyError(f"Deployment file {deployment_path} missing required p1/p2 zones")
                
                def _build_deploy_pool(zone: Dict[str, Any]) -> set[tuple[int, int]]:
                    col_min = require_key(zone, "col_min")
                    col_max = require_key(zone, "col_max")
                    row_min = require_key(zone, "row_min")
                    row_max = require_key(zone, "row_max")
                    if col_min > col_max or row_min > row_max:
                        raise ValueError(
                            f"Invalid deploy bounds: col=({col_min},{col_max}) row=({row_min},{row_max})"
                        )
                    pool = {
                        (col, row)
                        for col in range(col_min, col_max + 1)
                        for row in range(row_min, row_max + 1)
                        if _is_valid_deploy_hex(col, row)
                    }
                    return pool
                
                deploy_pools = {
                    1: _build_deploy_pool(deployment_data["p1"]),
                    2: _build_deploy_pool(deployment_data["p2"]),
                }
                if any(
                    deployment_type_by_player[player_id] in ("random", "active")
                    for player_id in (1, 2)
                ):
                    if not wall_hex_set:
                        raise KeyError(
                            f"Scenario file {scenario_file} missing required 'wall_hexes' for random/active deployment"
                        )
                    deploy_pools = {
                        1: deploy_pools[1] - wall_hex_set,
                        2: deploy_pools[2] - wall_hex_set,
                    }
            used_hexes = set()
            
            enhanced_units = []
            for unit_data in basic_units:
                if "unit_type" not in unit_data:
                    raise KeyError(f"Unit missing required 'unit_type' field: {unit_data}")
                
                unit_type = unit_data["unit_type"]
                unit_player = require_key(unit_data, "player")
                if int(unit_player) not in deployment_type_by_player:
                    raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                player_deployment_type = deployment_type_by_player[int(unit_player)]
                if player_deployment_type == "random":
                    if unit_player not in deploy_pools:
                        raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                    available_hexes = list(deploy_pools[unit_player] - used_hexes)
                    if not available_hexes:
                        raise ValueError(
                            f"No available deployment hexes for player {unit_player} "
                            f"(units={len([u for u in basic_units if require_key(u, 'player') == unit_player])})"
                        )
                    chosen_col, chosen_row = random.choice(available_hexes)
                    used_hexes.add((chosen_col, chosen_row))
                elif player_deployment_type == "active":
                    chosen_col, chosen_row = -1, -1
                else:
                    required_fields = ["id", "player", "col", "row"]
                    for field in required_fields:
                        if field not in unit_data:
                            raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                    chosen_col, chosen_row = normalize_coordinates(unit_data["col"], unit_data["row"])
                    if deployment_zone:
                        if unit_player not in deploy_pools:
                            raise ValueError(f"Invalid unit player for deployment: {unit_player}")
                        if (chosen_col, chosen_row) not in deploy_pools[unit_player]:
                            raise ValueError(
                                f"Unit {unit_data.get('id')} outside deployment zone '{deployment_zone}' "
                                f"for player {unit_player}: ({chosen_col},{chosen_row})"
                            )
                    if deployment_zone and not _is_valid_deploy_hex(chosen_col, chosen_row):
                        raise ValueError(
                            f"Unit {unit_data.get('id')} on invalid deploy hex: ({chosen_col},{chosen_row})"
                        )
                    if wall_hex_set and (chosen_col, chosen_row) in wall_hex_set:
                        raise ValueError(
                            f"Unit {unit_data.get('id')} placed on wall hex: ({chosen_col},{chosen_row})"
                        )
                    if (chosen_col, chosen_row) in used_hexes:
                        raise ValueError(
                            f"Duplicate unit position: ({chosen_col},{chosen_row})"
                        )
                    used_hexes.add((chosen_col, chosen_row))
                
                try:
                    full_unit_data = unit_registry.get_unit_data(unit_type)
                except Exception as e:
                    raise ValueError(f"Failed to get unit data for '{unit_type}': {e}")
                
                required_fields = ["id", "player"]
                for field in required_fields:
                    if field not in unit_data:
                        raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract RNG_WEAPONS and CC_WEAPONS
                rng_weapons = copy.deepcopy(require_key(full_unit_data, "RNG_WEAPONS"))
                cc_weapons = copy.deepcopy(require_key(full_unit_data, "CC_WEAPONS"))
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate at least one weapon type exists
                if not rng_weapons and not cc_weapons:
                    raise ValueError(f"Unit {unit_type} must have at least RNG_WEAPONS or CC_WEAPONS")
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
                selected_rng_weapon_index = 0 if rng_weapons else None
                selected_cc_weapon_index = 0 if cc_weapons else None
                
                # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
                shoot_left = 0
                if rng_weapons and selected_rng_weapon_index is not None:
                    selected_weapon = rng_weapons[selected_rng_weapon_index]
                    if isinstance(selected_weapon, dict):
                        shoot_left = resolve_dice_value(
                            require_key(selected_weapon, "NB"),
                            "scenario_init_shoot_left",
                        )
                    else:
                        raise TypeError(f"Unit {unit_type}: RNG_WEAPONS[{selected_rng_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")
                
                attack_left = 0
                if cc_weapons and selected_cc_weapon_index is not None:
                    selected_weapon = cc_weapons[selected_cc_weapon_index]
                    if isinstance(selected_weapon, dict):
                        attack_left = resolve_dice_value(
                            require_key(selected_weapon, "NB"),
                            "scenario_init_attack_left",
                        )
                    else:
                        raise TypeError(f"Unit {unit_type}: CC_WEAPONS[{selected_cc_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")
                
                enhanced_unit = {
                    "id": str(unit_data["id"]),
                    "player": unit_player,
                    "unitType": unit_type,
                    "DISPLAY_NAME": require_key(full_unit_data, "DISPLAY_NAME"),
                    "col": normalize_coordinates(chosen_col, chosen_row)[0],
                    "row": normalize_coordinates(chosen_col, chosen_row)[1],
                    "HP_CUR": full_unit_data["HP_MAX"],
                    "HP_MAX": full_unit_data["HP_MAX"],
                    "MOVE": full_unit_data["MOVE"],
                    "T": full_unit_data["T"],
                    "ARMOR_SAVE": full_unit_data["ARMOR_SAVE"],
                    "INVUL_SAVE": full_unit_data["INVUL_SAVE"],
                    # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
                    "RNG_WEAPONS": rng_weapons,
                    "CC_WEAPONS": cc_weapons,
                    "selectedRngWeaponIndex": selected_rng_weapon_index,
                    "selectedCcWeaponIndex": selected_cc_weapon_index,
                    "LD": full_unit_data["LD"],
                    "OC": full_unit_data["OC"],
                    "VALUE": full_unit_data["VALUE"],
                    "ICON": full_unit_data["ICON"],
                    "ICON_SCALE": full_unit_data["ICON_SCALE"],
                    "UNIT_RULES": copy.deepcopy(require_key(full_unit_data, "UNIT_RULES")),
                    "UNIT_KEYWORDS": copy.deepcopy(require_key(full_unit_data, "UNIT_KEYWORDS")),
                    "SHOOT_LEFT": shoot_left,
                    "ATTACK_LEFT": attack_left
                }
                
                enhanced_units.append(enhanced_unit)

            # Extract optional terrain data from scenario
            # If present in scenario, use it; otherwise return None for board config selection
            scenario_walls = resolved_scenario_walls
            scenario_objectives = resolved_scenario_objectives
            scenario_primary_objective = None
            scenario_wall_ref = (
                scenario_data.get("wall_ref") if isinstance(scenario_data, dict) else None
            )

            if isinstance(scenario_data, dict):
                if "primary_objectives" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objectives"]
                elif "primary_objective" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objective"]

            scenario_primary_objectives = (
                scenario_primary_objective
                if isinstance(scenario_primary_objective, list)
                else None
            )
            scenario_primary_objective_single = (
                scenario_primary_objective
                if scenario_primary_objective is not None and not isinstance(scenario_primary_objective, list)
                else None
            )

            deployment_pools_serializable = None
            if deploy_pools:
                deployment_pools_serializable = {
                    player: sorted(list(pool))
                    for player, pool in deploy_pools.items()
                }

            # Return dict with units and optional terrain
            return {
                "units": enhanced_units,
                "wall_hexes": scenario_walls,
                "wall_ref": scenario_wall_ref,
                "objectives": scenario_objectives,
                "primary_objectives": scenario_primary_objectives,
                "primary_objective": scenario_primary_objective_single,
                "deployment_zone": deployment_zone,
                "deployment_type": deployment_type,
                "deployment_type_by_player": deployment_type_by_player,
                "deployment_pools": deployment_pools_serializable,
                "roster_info": scenario_roster_info
            }

    def _load_units_from_roster_refs(
        self,
        scenario_data: Dict[str, Any],
        scenario_file: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Load P1/P2 units from compact roster references."""
        scale = require_key(scenario_data, "scale")
        if not isinstance(scale, str) or not scale.strip():
            raise ValueError(f"Scenario '{scenario_file}' has invalid 'scale': {scale!r}")
        scale_name = scale.strip()

        scenario_path = Path(scenario_file).resolve()
        path_parts = scenario_path.parts
        try:
            agents_idx = path_parts.index("agents")
            scenario_agent_key = path_parts[agents_idx + 1]
        except Exception as e:
            raise ValueError(
                f"Cannot resolve agent key from scenario path '{scenario_file}': {e}"
            )
        if scenario_agent_key in {"_p2_rosters", "p2_rosters"}:
            raise ValueError(
                f"Scenario path '{scenario_file}' points to shared roster directory, not an agent scenario"
            )

        split: Optional[str] = None
        if "/scenarios/training/" in scenario_file:
            split = "training"
        elif "/scenarios/holdout_regular/" in scenario_file or "/scenarios/holdout_hard/" in scenario_file:
            split = "holdout"
        else:
            raise ValueError(
                f"Scenario '{scenario_file}' must be located under scenarios/training, "
                f"scenarios/holdout_regular, or scenarios/holdout_hard"
            )
        holdout_split_for_p1: Optional[str] = None
        if split == "holdout":
            if "/scenarios/holdout_regular/" in scenario_file:
                holdout_split_for_p1 = "holdout_regular"
            elif "/scenarios/holdout_hard/" in scenario_file:
                holdout_split_for_p1 = "holdout_hard"
            else:
                raise ValueError(
                    f"Holdout scenario '{scenario_file}' must be in holdout_regular/ or holdout_hard/"
                )

        p1_ref_value = require_key(scenario_data, "p1_roster_ref")
        p2_ref_value = require_key(scenario_data, "p2_roster_ref")
        p1_roster_seed = scenario_data.get("p1_roster_seed")
        if p1_roster_seed is not None:
            if not isinstance(p1_roster_seed, int) or isinstance(p1_roster_seed, bool) or p1_roster_seed < 0:
                raise ValueError(
                    f"Scenario '{scenario_file}' has invalid 'p1_roster_seed': {p1_roster_seed!r} "
                    f"(expected non-negative integer)"
                )

        p1_ref, p1_ref_randomized = self._resolve_roster_ref(
            p1_ref_value,
            expected_split=(split if split == "training" else str(holdout_split_for_p1)),
            scenario_file=scenario_file,
            field_name="p1_roster_ref",
            allow_random=(split == "training"),
            scenario_agent_key=scenario_agent_key,
            scale_name=scale_name,
            roster_kind="p1",
            random_seed=p1_roster_seed
        )
        p2_ref, _ = self._resolve_roster_ref(
            p2_ref_value,
            expected_split=split,
            scenario_file=scenario_file,
            field_name="p2_roster_ref",
            allow_random=False,
            scenario_agent_key=scenario_agent_key,
            scale_name=scale_name,
            roster_kind="p2",
            random_seed=None
        )

        project_root = Path(__file__).resolve().parent.parent
        p1_roster_path = (
            project_root / "config" / "agents" / scenario_agent_key / "rosters" / scale_name / p1_ref
        )
        p2_roster_path = (
            project_root / "config" / "agents" / "_p2_rosters" / scale_name / p2_ref
        )

        p1_roster_data = self._load_compact_roster_file(p1_roster_path, "P1")
        p2_roster_data = self._load_compact_roster_file(p2_roster_path, "P2")

        p1_units = self._expand_compact_roster_to_basic_units(
            roster_data=p1_roster_data,
            player=1,
            id_start=1,
            roster_path=str(p1_roster_path)
        )
        p2_units = self._expand_compact_roster_to_basic_units(
            roster_data=p2_roster_data,
            player=2,
            id_start=101,
            roster_path=str(p2_roster_path)
        )

        roster_info = {
            "scale": scale_name,
            "p1_roster_ref": p1_ref,
            "p2_roster_ref": p2_ref,
            "p1_roster_id": str(require_key(p1_roster_data, "roster_id")),
            "p2_roster_id": str(require_key(p2_roster_data, "roster_id")),
            "p1_ref_randomized": p1_ref_randomized
        }
        return p1_units + p2_units, roster_info

    def _resolve_roster_ref(
        self,
        raw_ref: Any,
        expected_split: str,
        scenario_file: str,
        field_name: str,
        allow_random: bool,
        scenario_agent_key: str,
        scale_name: str,
        roster_kind: str,
        random_seed: Optional[int]
    ) -> Tuple[str, bool]:
        """Resolve roster reference to '<expected_split>/file.json'."""
        import random

        if roster_kind not in {"p1", "p2"}:
            raise ValueError(f"Invalid roster_kind: {roster_kind!r}")

        rng = random.Random(random_seed) if random_seed is not None else random

        ref_value = raw_ref
        was_randomized = False
        if isinstance(raw_ref, str) and allow_random:
            normalized_ref = raw_ref.strip().replace("\\", "/")
            random_token = f"{expected_split}_random"
            if normalized_ref == random_token:
                project_root = Path(__file__).resolve().parent.parent
                if roster_kind == "p1":
                    base_dir = (
                        project_root
                        / "config"
                        / "agents"
                        / scenario_agent_key
                        / "rosters"
                        / scale_name
                        / expected_split
                    )
                    pattern = f"p1_{expected_split}_roster-*.json"
                else:
                    base_dir = (
                        project_root
                        / "config"
                        / "agents"
                        / "_p2_rosters"
                        / scale_name
                        / expected_split
                    )
                    pattern = f"p2_{expected_split}_roster-*.json"
                if not base_dir.exists():
                    raise FileNotFoundError(
                        f"Scenario '{scenario_file}' {field_name}={random_token!r} but directory does not exist: {base_dir}"
                    )
                candidates = sorted(base_dir.glob(pattern), key=lambda p: p.name)
                if not candidates:
                    raise FileNotFoundError(
                        f"Scenario '{scenario_file}' {field_name}={random_token!r} but no files matching "
                        f"{pattern} in {base_dir}"
                    )
                chosen = rng.choice(candidates)
                ref_value = f"{expected_split}/{chosen.name}"
                was_randomized = True

        if isinstance(raw_ref, list):
            if not allow_random:
                raise ValueError(
                    f"Scenario '{scenario_file}' field '{field_name}' cannot be a list outside training split"
                )
            if not raw_ref:
                raise ValueError(
                    f"Scenario '{scenario_file}' field '{field_name}' list cannot be empty"
                )
            ref_value = rng.choice(raw_ref)
            was_randomized = True

        if not isinstance(ref_value, str) or not ref_value.strip():
            raise ValueError(
                f"Scenario '{scenario_file}' has invalid '{field_name}': {ref_value!r}"
            )

        normalized = ref_value.strip().replace("\\", "/")
        if normalized.startswith("../") or "/../" in normalized or normalized.startswith("/"):
            raise ValueError(
                f"Scenario '{scenario_file}' has unsafe roster ref in '{field_name}': {normalized}"
            )

        if "/" not in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must be explicit '<split>/file.json', got '{normalized}'"
            )
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"

        ref_split, _, ref_filename = normalized.partition("/")
        VALID_P1_SPLITS = {"training", "holdout_regular", "holdout_hard"}
        VALID_P2_SPLITS = {"training", "holdout"}
        valid_splits = VALID_P1_SPLITS if roster_kind == "p1" else VALID_P2_SPLITS
        project_root = Path(__file__).resolve().parent.parent

        # Allow explicit split in ref (e.g. holdout_regular/... when scenario is in training/)
        # Enables cross-split evaluation (P1 holdout vs P2 training)
        if ref_split in valid_splits:
            if roster_kind == "p1":
                explicit_base = (
                    project_root
                    / "config"
                    / "agents"
                    / scenario_agent_key
                    / "rosters"
                    / scale_name
                    / ref_split
                )
            else:
                explicit_base = (
                    project_root
                    / "config"
                    / "agents"
                    / "_p2_rosters"
                    / scale_name
                    / ref_split
                )
            explicit_path = explicit_base / ref_filename
            if explicit_path.exists():
                return normalized, was_randomized
            # Try roster_id match in explicit split (e.g. holdout_regular_p1_roster-01)
            if explicit_base.exists():
                requested_id = Path(ref_filename).stem
                for candidate_path in sorted(explicit_base.glob("*.json"), key=lambda p: p.name):
                    try:
                        with open(candidate_path, "r", encoding="utf-8-sig") as f:
                            data = json.load(f)
                        if require_key(data, "roster_id") == requested_id:
                            return f"{ref_split}/{candidate_path.name}", was_randomized
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Fallback: require ref to match expected_split (scenario path context)
        prefix = f"{expected_split}/"
        if not normalized.startswith(prefix):
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must target '{expected_split}/...' "
                f"(or explicit valid split) but got '{normalized}'"
            )
        filename = ref_filename
        if roster_kind == "p1":
            base_dir = (
                project_root
                / "config"
                / "agents"
                / scenario_agent_key
                / "rosters"
                / scale_name
                / expected_split
            )
        else:
            base_dir = (
                project_root
                / "config"
                / "agents"
                / "_p2_rosters"
                / scale_name
                / expected_split
            )
        direct_path = base_dir / filename
        if direct_path.exists():
            return normalized, was_randomized

        requested_roster_id = Path(filename).stem
        if not requested_roster_id.startswith(f"{roster_kind}_") or "roster-" not in requested_roster_id:
            raise FileNotFoundError(
                f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
                f"and roster id inference is not supported for '{requested_roster_id}'"
            )

        if not base_dir.exists():
            raise FileNotFoundError(
                f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
                f"and roster directory does not exist: {base_dir}"
            )

        matching_files: List[Path] = []
        for candidate_path in sorted(base_dir.glob("*.json"), key=lambda p: p.name):
            try:
                with open(candidate_path, "r", encoding="utf-8-sig") as candidate_file:
                    candidate_data = json.load(candidate_file)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in roster file {candidate_path}: {e}")
            candidate_roster_id = require_key(candidate_data, "roster_id")
            if not isinstance(candidate_roster_id, str):
                raise TypeError(
                    f"Roster file {candidate_path} has non-string roster_id: "
                    f"{type(candidate_roster_id).__name__}"
                )
            if candidate_roster_id == requested_roster_id:
                matching_files.append(candidate_path)

        if len(matching_files) == 1:
            resolved_filename = matching_files[0].name
            return f"{expected_split}/{resolved_filename}", was_randomized
        if len(matching_files) > 1:
            raise ValueError(
                f"Scenario '{scenario_file}' roster ref '{normalized}' is ambiguous by roster_id "
                f"'{requested_roster_id}': {[str(path) for path in matching_files]}"
            )
        raise FileNotFoundError(
            f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
            f"and no roster with roster_id '{requested_roster_id}' exists in {base_dir}"
        )

    def _load_shared_walls_from_ref(self, wall_ref: Any, scenario_file: str) -> List[List[int]]:
        """Load shared wall_hexes file referenced by scenario wall_ref."""
        wall_path = self._resolve_shared_config_path("_walls", wall_ref, scenario_file, "wall_ref")
        if not wall_path.exists():
            raise FileNotFoundError(f"Shared walls file not found for scenario {scenario_file}: {wall_path}")
        try:
            with open(wall_path, "r", encoding="utf-8-sig") as f:
                wall_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in shared walls file {wall_path}: {e}")
        if not isinstance(wall_data, dict):
            raise ValueError(f"Shared walls file {wall_path} must be JSON object")
        if "walls" in wall_data:
            walls = require_key(wall_data, "walls")
            if not isinstance(walls, list):
                raise ValueError(f"Shared walls file {wall_path} field 'walls' must be list")
            result: List[List[int]] = []
            for g in walls:
                if not isinstance(g, dict):
                    raise ValueError(f"Shared walls file {wall_path}: wall group must be dict")
                hexes = require_key(g, "hexes")
                if not isinstance(hexes, list):
                    raise ValueError(f"Shared walls file {wall_path}: wall group 'hexes' must be list")
                for h in hexes:
                    if not isinstance(h, (list, tuple)) or len(h) < 2:
                        raise ValueError(f"Shared walls file {wall_path}: invalid wall hex {h}")
                    result.append([int(h[0]), int(h[1])])
            return result
        wall_hexes = require_key(wall_data, "wall_hexes")
        if not isinstance(wall_hexes, list):
            raise ValueError(f"Shared walls file {wall_path} field 'wall_hexes' must be list")
        return wall_hexes

    def _load_shared_objectives_from_ref(self, objectives_ref: Any, scenario_file: str) -> List[Dict[str, Any]]:
        """Load shared objectives file referenced by scenario objectives_ref."""
        objectives_path = self._resolve_shared_config_path(
            "_objectives",
            objectives_ref,
            scenario_file,
            "objectives_ref"
        )
        if not objectives_path.exists():
            raise FileNotFoundError(
                f"Shared objectives file not found for scenario {scenario_file}: {objectives_path}"
            )
        try:
            with open(objectives_path, "r", encoding="utf-8-sig") as f:
                objectives_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in shared objectives file {objectives_path}: {e}")
        if not isinstance(objectives_data, dict):
            raise ValueError(f"Shared objectives file {objectives_path} must be JSON object")
        objectives = require_key(objectives_data, "objectives")
        if not isinstance(objectives, list):
            raise ValueError(f"Shared objectives file {objectives_path} field 'objectives' must be list")
        return objectives

    def _resolve_shared_config_path(
        self,
        shared_dir_name: str,
        raw_ref: Any,
        scenario_file: str,
        field_name: str
    ) -> Path:
        """Resolve shared config path. _walls -> config/board/{cols}x{rows}/walls/, _objectives -> .../objectives/, else config/agents/<shared_dir_name>/."""
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            raise ValueError(
                f"Scenario '{scenario_file}' has invalid '{field_name}': {raw_ref!r}"
            )
        normalized = raw_ref.strip().replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' has unsafe '{field_name}': {normalized}"
            )
        if "/" in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must be filename only under {shared_dir_name}, got: {normalized}"
            )
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"

        project_root = Path(__file__).resolve().parent.parent
        from config_loader import get_config_loader
        cols, rows = get_config_loader().get_board_size()
        board_dir = project_root / "config" / "board" / f"{cols}x{rows}"
        if shared_dir_name == "_walls":
            return board_dir / "walls" / normalized
        if shared_dir_name == "_objectives":
            return board_dir / "objectives" / normalized
        return project_root / "config" / "agents" / shared_dir_name / normalized

    def _load_compact_roster_file(self, roster_path: Path, roster_label: str) -> Dict[str, Any]:
        """Load and validate compact roster JSON file."""
        if not roster_path.exists():
            raise FileNotFoundError(f"{roster_label} roster file not found: {roster_path}")
        try:
            with open(roster_path, "r", encoding="utf-8-sig") as f:
                roster_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {roster_label} roster file {roster_path}: {e}")
        if not isinstance(roster_data, dict):
            raise ValueError(
                f"{roster_label} roster file {roster_path} must be JSON object, got {type(roster_data).__name__}"
            )
        require_key(roster_data, "roster_id")
        composition = require_key(roster_data, "composition")
        if not isinstance(composition, list) or not composition:
            raise ValueError(f"{roster_label} roster {roster_path} must define non-empty 'composition' list")
        return roster_data

    def _expand_compact_roster_to_basic_units(
        self,
        roster_data: Dict[str, Any],
        player: int,
        id_start: int,
        roster_path: str
    ) -> List[Dict[str, Any]]:
        """Expand compact composition format to basic unit entries."""
        composition = require_key(roster_data, "composition")
        if not isinstance(composition, list):
            raise ValueError(f"Roster {roster_path} field 'composition' must be list")

        next_id = id_start
        expanded_units: List[Dict[str, Any]] = []
        for idx, comp_entry in enumerate(composition):
            if not isinstance(comp_entry, dict):
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}] must be object, got {type(comp_entry).__name__}"
                )
            unit_type = require_key(comp_entry, "unit_type")
            count = require_key(comp_entry, "count")
            if not isinstance(unit_type, str) or not unit_type.strip():
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}].unit_type must be non-empty string"
                )
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}].count must be positive int, got {count!r}"
                )
            for _ in range(count):
                expanded_units.append({
                    "id": next_id,
                    "player": player,
                    "unit_type": unit_type.strip()
                })
                next_id += 1
        return expanded_units
    
    # ============================================================================
    # UTILITIES
    # ============================================================================

    def get_unit_by_id(self, unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state.

        CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
        """
        for unit in game_state["units"]:
            if str(unit["id"]) == str(unit_id):
                return unit
        return None

    # ============================================================================
    # OBJECTIVE CONTROL SYSTEM
    # ============================================================================

    def calculate_objective_control(self, game_state: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        """
        Calculate objective control for each objective with configured control method.

        Win condition: Control more objectives than opponent at end of turn 5.
        Control rules:
        - To CAPTURE an objective: Your OC sum must be > opponent's OC sum
        - control_method == "sticky": keep control until opponent captures
        - control_method == "occupy": control only if currently occupied with greater OC
        - Equal OC = current controller keeps control (sticky) or stays neutral (occupy)

        Returns:
            Dict[objective_id, {
                'player_1_oc': int,  # Total OC for player 1
                'player_2_oc': int,  # Total OC for player 2
                'controller': int|None  # 1, 2, or None (contested/uncontrolled)
            }]
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {}

        primary_objective = require_key(game_state, "primary_objective")
        if primary_objective is None:
            raise ValueError("primary_objective is required to calculate objective control")
        if isinstance(primary_objective, list):
            if not primary_objective:
                raise ValueError("primary_objective list cannot be empty for objective control")
            primary_configs = primary_objective
        else:
            primary_configs = [primary_objective]

        control_method: Optional[str] = None
        for objective_cfg in primary_configs:
            if not isinstance(objective_cfg, dict):
                raise TypeError("primary_objective entry must be a dict for objective control")
            control_cfg = require_key(objective_cfg, "control")
            method = require_key(control_cfg, "method")
            if method != "oc_sum_greater":
                raise ValueError(f"Unsupported primary objective control method: {method}")
            current_control_method = require_key(control_cfg, "control_method")
            if current_control_method not in ("sticky", "occupy"):
                raise ValueError(f"Unsupported control_method: {current_control_method}")
            tie_behavior = require_key(control_cfg, "tie_behavior")
            if tie_behavior != "no_control":
                raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")
            if control_method is None:
                control_method = current_control_method
            elif control_method != current_control_method:
                raise ValueError("primary_objective control_method must be consistent across configs")

        if control_method is None:
            raise ValueError("control_method is required to calculate objective control")

        # Get persistent control state (initialize if not present)
        if "objective_controllers" not in game_state:
            game_state["objective_controllers"] = {}

        result = {}

        for objective in objectives:
            obj_id = objective["id"]
            obj_hexes = objective["hexes"]
            obj_id_key = str(obj_id)

            # Convert hex list to set of tuples for fast lookup
            hex_set = set(tuple(h) for h in obj_hexes)

            # Calculate OC per player
            player_1_oc = 0
            player_2_oc = 0

            units_cache = require_key(game_state, "units_cache")
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            for unit_id, entry in units_cache.items():
                unit = unit_by_id.get(str(unit_id))
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")

                unit_pos = normalize_coordinates(entry["col"], entry["row"])
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    unit_player = require_key(unit, "player")
                    if unit_player == 1:
                        player_1_oc += oc
                    elif unit_player == 2:
                        player_2_oc += oc
                    else:
                        raise ValueError(f"Unexpected unit player id: {unit_player}")

            # Get current controller from persistent state; explicit init when first seeing this objective
            if obj_id_key not in game_state["objective_controllers"]:
                game_state["objective_controllers"][obj_id_key] = None
            current_controller = game_state["objective_controllers"][obj_id_key]

            if control_method == "sticky":
                # Determine new controller with PERSISTENT control rules
                new_controller = current_controller  # Default: keep current control

                if player_1_oc > player_2_oc:
                    # P1 has more OC - P1 captures/keeps
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    # P2 has more OC - P2 captures/keeps
                    new_controller = 2
                # If equal OC: current controller keeps control (no change)
                # This includes 0-0 case where objective stays in its current state
            elif control_method == "occupy":
                new_controller = None
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
            else:
                raise ValueError(f"Unsupported control_method: {control_method}")

            # Update persistent state
            game_state["objective_controllers"][obj_id_key] = new_controller

            result[obj_id] = {
                "player_1_oc": player_1_oc,
                "player_2_oc": player_2_oc,
                "controller": new_controller
            }

        return result

    def count_controlled_objectives(self, game_state: Dict[str, Any]) -> Dict[int, int]:
        """
        Count objectives controlled by each player.

        Returns:
            {1: count_for_player_1, 2: count_for_player_2}
        """
        control_data = self.calculate_objective_control(game_state)

        counts = {1: 0, 2: 0}
        for obj_id, data in control_data.items():
            if data["controller"] is not None:
                controller = data["controller"]
                if controller not in counts:
                    raise ValueError(f"Unexpected objective controller: {controller}")
                counts[controller] += 1

        return counts

    def _calculate_primary_objective_control_counts(
        self,
        game_state: Dict[str, Any],
        primary_objective: Dict[str, Any]
    ) -> Dict[int, int]:
        """
        Calculate objective control counts for primary objective scoring.

        Uses primary objective control rules (method + tie behavior) to count
        objectives controlled by each player for scoring purposes.
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {1: 0, 2: 0}

        objective_controllers = require_key(game_state, "objective_controllers")

        control_cfg = require_key(primary_objective, "control")
        method = require_key(control_cfg, "method")
        control_method = require_key(control_cfg, "control_method")
        tie_behavior = require_key(control_cfg, "tie_behavior")

        if method != "oc_sum_greater":
            raise ValueError(f"Unsupported primary objective control method: {method}")
        if control_method not in ("sticky", "occupy"):
            raise ValueError(f"Unsupported control_method: {control_method}")
        if tie_behavior != "no_control":
            raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}

        counts = {1: 0, 2: 0}

        for objective in objectives:
            obj_id = require_key(objective, "id")
            obj_id_key = str(obj_id)
            obj_hexes = require_key(objective, "hexes")
            hex_set = {normalize_coordinates(h[0], h[1]) for h in obj_hexes}
            player_1_oc = 0
            player_2_oc = 0

            for unit_id, entry in units_cache.items():
                unit = unit_by_id.get(str(unit_id))
                if not unit:
                    raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                unit_pos = normalize_coordinates(entry["col"], entry["row"])
                if unit_pos in hex_set:
                    oc = require_key(unit, "OC")
                    unit_player = require_key(entry, "player")
                    unit_player_int = int(unit_player)
                    if unit_player_int == 1:
                        player_1_oc += oc
                    elif unit_player_int == 2:
                        player_2_oc += oc
                    else:
                        raise ValueError(f"Unexpected unit player id: {unit_player}")

            if obj_id_key not in objective_controllers:
                objective_controllers[obj_id_key] = None
            current_controller = objective_controllers[obj_id_key]
            if control_method == "sticky":
                new_controller = current_controller
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
                # If equal OC: current controller keeps control (sticky)
            elif control_method == "occupy":
                new_controller = None
                if player_1_oc > player_2_oc:
                    new_controller = 1
                elif player_2_oc > player_1_oc:
                    new_controller = 2
            else:
                raise ValueError(f"Unsupported control_method: {control_method}")

            objective_controllers[obj_id_key] = new_controller
            if new_controller is not None:
                counts[new_controller] += 1

        return counts

    def apply_primary_objective_scoring(self, game_state: Dict[str, Any], scoring_phase: str) -> None:
        """
        Apply primary objective scoring for the current turn and player.
        
        scoring_phase: "command" or "fight"
        """
        primary_objective = game_state.get("primary_objective")
        if primary_objective is None:
            return
        if isinstance(primary_objective, list):
            for objective in primary_objective:
                if not isinstance(objective, dict):
                    raise TypeError(f"primary_objective list entry is {type(objective).__name__}, expected dict")
                self._apply_primary_objective_scoring_single(game_state, scoring_phase, objective)
            return
        if not isinstance(primary_objective, dict):
            raise TypeError(f"primary_objective is {type(primary_objective).__name__}, expected dict")
        self._apply_primary_objective_scoring_single(game_state, scoring_phase, primary_objective)

    def _apply_primary_objective_scoring_single(
        self,
        game_state: Dict[str, Any],
        scoring_phase: str,
        primary_objective: Dict[str, Any]
    ) -> None:
        """
        Apply primary objective scoring for a single objective config.
        """

        scoring_cfg = require_key(primary_objective, "scoring")
        timing_cfg = require_key(primary_objective, "timing")
        start_turn = require_key(scoring_cfg, "start_turn")
        max_points_per_turn = require_key(scoring_cfg, "max_points_per_turn")
        rules = require_key(scoring_cfg, "rules")
        default_phase = require_key(timing_cfg, "default_phase")
        round5_second_player_phase = require_key(timing_cfg, "round5_second_player_phase")

        current_turn = require_key(game_state, "turn")
        current_player = require_key(game_state, "current_player")
        current_player_int = int(current_player)

        if current_turn < start_turn:
            return

        if current_turn == 5 and current_player_int == 2:
            expected_phase = round5_second_player_phase
        else:
            expected_phase = default_phase

        if scoring_phase != expected_phase:
            return

        objective_id = require_key(primary_objective, "id")
        scored_turns = require_key(game_state, "primary_objective_scored_turns")
        score_key = (objective_id, current_turn, current_player_int)
        if score_key in scored_turns:
            return

        counts = self._calculate_primary_objective_control_counts(game_state, primary_objective)
        opponent_player = 1 if current_player_int == 2 else 2

        total_points = 0
        for rule in rules:
            condition = require_key(rule, "condition")
            points = require_key(rule, "points")
            if condition == "control_at_least_one":
                if counts[current_player_int] >= 1:
                    total_points += points
            elif condition == "control_at_least_two":
                if counts[current_player_int] >= 2:
                    total_points += points
            elif condition == "control_more_than_opponent":
                if counts[current_player_int] > counts[opponent_player]:
                    total_points += points
            else:
                raise ValueError(f"Unsupported primary objective condition: {condition}")

        if total_points > max_points_per_turn:
            total_points = max_points_per_turn

        victory_points = require_key(game_state, "victory_points")
        if current_player_int not in victory_points:
            raise KeyError(f"victory_points missing player {current_player_int}")
        victory_points[current_player_int] += total_points
        scored_turns.add(score_key)

    def check_game_over(self, game_state: Dict[str, Any]) -> bool:
        """
        Check if game is over.

        Game ends when:
        1. Turn limit reached (training config override)
        """
        # Check training turn limit (for RL training - may differ from standard 5 turns)
        if hasattr(self, 'training_config'):
            max_turns = self.training_config.get("max_turns_per_episode")
            if max_turns and game_state["turn"] > max_turns:
                return True

        if require_key(game_state, "turn_limit_reached"):
            return True

        return False
    
    def determine_winner(self, game_state: Dict[str, Any]) -> Optional[int]:
        """
        Determine winner based on primary objective victory points.

        Victory conditions:
        1. More victory points at end of game
        2. Tiebreaker: More total VALUE of living units
        3. Draw if still tied

        Returns:
            1 = Player 1 wins
            2 = Player 2 wins
            -1 = Draw
            None = Game still ongoing
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1
        if p2_points > p1_points:
            return 2

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        p1_value = 0
        p2_value = 0
        for unit_id, entry in units_cache.items():
            unit = unit_by_id.get(str(unit_id))
            if not unit:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if entry["player"] == 1:
                p1_value += unit_value
            elif entry["player"] == 2:
                p2_value += unit_value
            else:
                raise ValueError(f"Unexpected unit player id: {entry['player']}")

        if p1_value > p2_value:
            return 1
        if p2_value > p1_value:
            return 2
        return -1

    def determine_winner_with_method(self, game_state: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
        """
        Determine winner AND the method of victory.

        Returns:
            Tuple of (winner, win_method):
            - winner: 1, 2, -1 (draw), or None (ongoing)
            - win_method: "objectives", "value_tiebreaker", "draw", or None
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None, None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1, "objectives"
        if p2_points > p1_points:
            return 2, "objectives"

        units_cache = require_key(game_state, "units_cache")
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        p1_value = 0
        p2_value = 0
        for unit_id, entry in units_cache.items():
            unit = unit_by_id.get(str(unit_id))
            if not unit:
                raise KeyError(f"Unit {unit_id} missing from game_state['units']")
            unit_value = require_key(unit, "VALUE")
            if entry["player"] == 1:
                p1_value += unit_value
            elif entry["player"] == 2:
                p2_value += unit_value
            else:
                raise ValueError(f"Unexpected unit player id: {entry['player']}")

        if p1_value > p2_value:
            return 1, "value_tiebreaker"
        if p2_value > p1_value:
            return 2, "value_tiebreaker"
        return -1, "draw"
