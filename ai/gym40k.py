# ai/gym40k.py
#!/usr/bin/env python3
"""
ai/gym40k.py - Phase-based W40K environment following AI_GAME_OVERVIEW.md specifications
"""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from typing import List, Dict, Tuple, Optional, Any
import json
import os
import re
import random
import copy
from datetime import datetime
import sys
from pathlib import Path
from collections import defaultdict  

script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from ai.unit_registry import UnitRegistry
from shared.gameRules import roll_d6, calculate_wound_target, calculate_save_target, execute_shooting_sequence

try:
    from config_loader import get_config_loader
except ImportError:
    # Add fallback path for config_loader
    sys.path.append(str(project_root))
    from config_loader import get_config_loader

# === HEX GRID DISTANCE CALCULATION ===

def get_hex_distance(unit1, unit2):
    """Calculate hex grid distance using Chebyshev distance (consistent with frontend)."""
    return max(abs(unit1["col"] - unit2["col"]), abs(unit1["row"] - unit2["row"]))

def are_units_adjacent(unit1, unit2):
    """Check if two units are adjacent (distance = 1)."""
    return get_hex_distance(unit1, unit2) == 1

def is_unit_in_range(attacker, target, range_value):
    """Check if target is within specified range of attacker."""
    return get_hex_distance(attacker, target) <= range_value

# roll_d6 function removed - now using shared function

# calculate_wound_target function removed - now using shared functioncalculate_save_target

# calculate_save_target function removed - now using shared function

# execute_shooting_sequence function removed - now using shared function

class W40KEnv(gym.Env):
    """Phase-based W40K environment following AI_GAME_OVERVIEW.md specifications exactly."""

    def __init__(self, rewards_config=None, training_config_name="default", 
             controlled_agent=None, active_agents=None, scenario_file=None, unit_registry=None, quiet=False):
        super().__init__()
        
        self.quiet = quiet  # Add quiet mode flag

        # Multi-agent support - reuse shared registry if provided
        self.unit_registry = unit_registry if unit_registry is not None else UnitRegistry()
        self.controlled_agent = controlled_agent  # Which agent this env controls
        self.active_agents = active_agents or []  # All active agents in training
        
        # Explicit unit tracking for PvP-style logging (eliminates action decoding)
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Direct logging capability (set by GameReplayIntegration)
        self.replay_logger = None

        # Initialize unit lists early to prevent AttributeError
        self.units = []
        self.ai_units = []
        self.enemy_units = []
        
        # Load configuration
        self.config = get_config_loader()
        
        # Load rewards configuration (unit-type-based)
        self.rewards_config = self.config.load_rewards_config()
        
        # Load unit definitions from the unit registry instead of parsing files separately
        if unit_registry is not None:
            # Convert unit registry data to the format expected by gym40k
            self.unit_definitions = {}
            for unit_type, unit_data in unit_registry.units.items():
                # Validate all required unit data exists
                required_fields = ['HP_MAX', 'MOVE', 'RNG_RNG', 'RNG_DMG', 'CC_DMG', 'RNG_NB', 'RNG_ATK', 'RNG_STR', 'RNG_AP', 'CC_NB', 'CC_ATK', 'CC_STR', 'CC_AP', 'CC_RNG', 'T', 'ARMOR_SAVE', 'INVUL_SAVE']
                for field in required_fields:
                    if field not in unit_data:
                        raise KeyError(f"Unit '{unit_type}' missing required field '{field}' in unit registry")
                
                converted_unit = {
                    'unit_type': unit_type,
                    'hp_max': unit_data['HP_MAX'],
                    'move': unit_data['MOVE'],
                    'rng_rng': unit_data['RNG_RNG'],
                    'rng_dmg': unit_data['RNG_DMG'],
                    'cc_dmg': unit_data['CC_DMG'],
                    'rng_nb': unit_data['RNG_NB'],
                    'rng_atk': unit_data['RNG_ATK'],
                    'rng_str': unit_data['RNG_STR'],
                    'rng_ap': unit_data['RNG_AP'],
                    'cc_nb': unit_data['CC_NB'],
                    'cc_atk': unit_data['CC_ATK'],
                    'cc_str': unit_data['CC_STR'],
                    'cc_ap': unit_data['CC_AP'],
                    'cc_rng': unit_data['CC_RNG'],
                    't': unit_data['T'],
                    'armor_save': unit_data['ARMOR_SAVE'],
                    'invul_save': unit_data['INVUL_SAVE'],
                    'is_ranged': unit_data['role'] == 'Ranged',
                    'is_melee': unit_data['role'] == 'Melee',
                    'ICON': unit_data.get('ICON', f"icons/{unit_type}.webp"),  # Keep this default as it's UI-related
                    'size_radius': unit_data.get('SIZE_RADIUS', 1)  # Keep this default as it's UI-related
                }
                self.unit_definitions[unit_type] = converted_unit
        else:
            # Fallback to loading from TypeScript files
            self.unit_definitions = self._load_unit_definitions()

        # Load training configuration to get max_steps_per_episode
        self.training_config_name = training_config_name
        training_config = self.config.load_training_config(training_config_name)
        self.max_steps_per_episode = self.config.get_max_steps_per_episode(training_config_name)
        
        # Episode step counter to prevent infinite episodes
        self.step_count = 0
        
        # Game state following AI_GAME.md exactly
        # Load phase order from config following AI_GAME.md - raise error if missing
        self.phase_order = self.config.get_phase_order()
        
        # Game state following AI_GAME.md exactly
        self.current_phase = "move"  # Always start with move phase
        self.current_player = 1  # 1 = AI, 0 = enemy/human
        self.game_over = False
        self.winner = None
        self.phase_acted_units = set()
        self.current_turn = 0
        self.max_turns = self.config.get_max_turns()
        self.turn_limit_penalty = self.config.get_turn_limit_penalty()
        # Phase-specific tracking following AI_GAME.md exactly
        self.moved_units = set()     # Units that moved this turn
        # AI_GAME.md compliance tracking
        self.ranged_units_shot_first = True
        self.phase_behavioral_violations = []
        self.tactical_guideline_compliance = {
            'movement': {'ranged_avoid_charge': 0, 'melee_charge_position': 0},
            'shooting': {'ranged_first': 0, 'priority_targeting': 0},
            'charge': {'melee_priority': 0, 'ranged_priority': 0},
            'combat': {'priority_targeting': 0}
        }
        self.shot_units = set()      # Units that shot this turn  
        self.charged_units = set()   # Units that charged this turn
        self.attacked_units = set()  # Units that attacked this turn
        self.board_size = self.config.get_board_size()
        
        # Phase tracking - units that have acted in current phase
        self.phase_acted_units = set()
        
        # Load scenario from specified file - NO FALLBACKS ALLOWED
        if scenario_file is None:
            raise ValueError("scenario_file parameter is required - no fallbacks allowed per AI_INSTRUCTIONS.md")
        
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(f"Specified scenario file not found: {scenario_file}")
        
        self.scenario_path = scenario_file
        
        # Calculate max_units dynamically from scenario for action space
        self._calculate_max_units_from_scenario()
        # Reduced verbosity - scenario path logged only if needed
        if os.path.exists(self.scenario_path):
            try:
                with open(self.scenario_path, 'r') as f:
                    scenario_data = json.load(f)
                    
                # Handle different JSON structures
                if isinstance(scenario_data, list):
                    scenario_units = scenario_data
                elif isinstance(scenario_data, dict):
                    if "units" in scenario_data:
                        scenario_units = scenario_data["units"]
                    else:
                        scenario_units = list(scenario_data.values())
                else:
                    raise ValueError(f"Scenario data must be list or dict, got {type(scenario_data)}")
                    
                # Initialize units from scenario
                self.units = []
                for unit_data in scenario_units:
                    # Get unit stats from definitions
                    unit_type = unit_data["unit_type"]
                    if unit_type not in self.unit_definitions:
                        raise ValueError(f"Unknown unit type: {unit_type}")
                    
                    # Merge scenario position data with unit definition stats
                    unit = copy.deepcopy(self.unit_definitions[unit_type])
            
                    # Validate required attributes - raise error if missing per AI_INSTRUCTIONS.md
                    required_attrs = ["hp_max", "move", "rng_rng", "rng_dmg", "cc_dmg", "cc_nb", "cc_atk", "cc_str", "cc_ap", "is_ranged", "is_melee"]
                    for attr in required_attrs:
                        if attr not in unit:
                            raise KeyError(f"Unit definition for '{unit_type}' missing required attribute '{attr}'")
                    
                    # Generic icon assignment: Bot space marines get red versions
                    if unit_data["player"] == 0:  # Bot player
                        icon_name = f"icons/{unit_type}_red.webp"
                    else:  # AI player uses original icons
                        if "ICON" not in unit:
                            raise KeyError(f"Unit '{unit_type}' missing required 'ICON' field")
                        icon_name = unit["ICON"]
                    
                    unit.update({
                        "id": unit_data["id"],
                        "player": unit_data["player"],
                        "col": unit_data["col"],
                        "row": unit_data["row"],
                        "alive": True,
                        "cur_hp": unit["hp_max"],
                        "has_moved": False,
                        "has_shot": False,
                        "has_charged": False,
                        "has_attacked": False,
                        "ICON": icon_name,
                        "size_radius": unit["size_radius"] if "size_radius" in unit else 1  # Pass size_radius to frontend
                    })
                    self.units.append(unit)
                    
            except Exception as e:
                raise RuntimeError(f"Failed to load scenario: {e}")
        else:
            raise FileNotFoundError(f"Scenario file not found: {self.scenario_path}")
        
        # Initialize AI and enemy unit lists first
        self.ai_units = [u for u in self.units if u["player"] == 1]
        self.enemy_units = [u for u in self.units if u["player"] == 0]
        
        # Action space: one action per unit per phase
        # Actions: unit_id, action_type, target (optional)
        self.max_units = len(self.ai_units)
        # Action encoding:
        # 0-7: Unit actions for first unit
        # 8-15: Unit actions for second unit, etc.
        # Actions per unit: [move_north, move_south, move_east, move_west, shoot_target, charge_target, attack_target, wait]
        self.action_space = spaces.Discrete(self.max_units * 8)
        
        # Fixed observation space: Always use consistent size regardless of actual unit count
        # AI units (max_units): max_units * 7
        # Enemy units (max_units): max_units * 4  
        # Phase encoding: 4
        # Total: (max_units * 7) + (max_units * 4) + 4 = max_units * 11 + 4
        obs_size = self.max_units * 11 + 4
        self.observation_space = spaces.Box(low=0, high=1, shape=(obs_size,), dtype=np.float32)
        
        # Replay tracking - COMPLETELY DISABLED, using GameReplayIntegration only
        self.replay_data = []
        self.save_replay = False
        print("🔧 gym40k replay system disabled - using GameReplayIntegration only")
        
        # Store scenario metadata for replay
        self.scenario_metadata = None
        if scenario_file and os.path.exists(scenario_file):
            try:
                with open(scenario_file, 'r') as f:
                    scenario_data = json.load(f)
                if isinstance(scenario_data, dict) and "metadata" in scenario_data:
                    self.scenario_metadata = scenario_data["metadata"]
            except Exception:
                pass  # Don't fail if metadata is missing

    def _calculate_max_units_from_scenario(self):
        """Calculate max_units dynamically from scenario file for action space."""
        try:
            with open(self.scenario_path, 'r') as f:
                scenario_data = json.load(f)
                
            # Handle different JSON structures
            if isinstance(scenario_data, list):
                scenario_units = scenario_data
            elif isinstance(scenario_data, dict):
                if "units" in scenario_data:
                    scenario_units = scenario_data["units"]
                else:
                    scenario_units = list(scenario_data.values())
            else:
                raise ValueError(f"Scenario data must be list or dict, got {type(scenario_data)}")
            
            # Count maximum units per player for action space calculation
            player_unit_counts = defaultdict(int)
            for unit_data in scenario_units:
                player = unit_data.get("player", 0)
                player_unit_counts[player] += 1
            
            # Use maximum units per player as the action space basis
            if not player_unit_counts:
                raise ValueError("No units found in scenario file")
            
            self.max_units = max(player_unit_counts.values())
            print(f"🎯 Dynamic action space: {self.max_units} max units per player (total action space: {self.max_units * 8})")
            
        except Exception as e:
            raise RuntimeError(f"CRITICAL ERROR: Cannot calculate max_units from scenario file '{self.scenario_path}': {e}. "
                             f"AI_INSTRUCTIONS.md: No fallbacks allowed - scenario file must be valid and readable.")

    def _load_unit_definitions(self):
        """Load unit definitions from TypeScript files exactly like the original."""
        definitions = {}
        
        # Define path to the TypeScript unit files
        frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "src")
        roster_dir = os.path.join(frontend_dir, "roster")
        
        if not os.path.exists(roster_dir):
            raise FileNotFoundError(f"TypeScript unit files not found at {roster_dir}. Cannot load unit definitions without roster files.")
        
        # Load from TypeScript files - scan all faction directories
        for faction_dir in os.listdir(roster_dir):
            faction_path = os.path.join(roster_dir, faction_dir)
            if os.path.isdir(faction_path) and not faction_dir.startswith('.'):
                # Only scan the units subfolder, skip classes folder
                units_path = os.path.join(faction_path, "units")
                if os.path.exists(units_path):
                    for filename in os.listdir(units_path):
                        if filename.endswith('.ts') and not filename.startswith('index'):
                            file_path = os.path.join(units_path, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # Parse TypeScript class with static properties
                        class_match = re.search(r'export class (\w+)', content)
                        if class_match:
                            unit_name = class_match.group(1)
                            
                            # Parse static properties
                            unit_data = {"unit_type": unit_name}
                            
                            # Extract static numeric properties
                            static_props = {
                                'HP_MAX': 'hp_max', 'MOVE': 'move', 'RNG_RNG': 'rng_rng', 'RNG_DMG': 'rng_dmg', 'CC_DMG': 'cc_dmg',
                                'RNG_NB': 'rng_nb', 'RNG_ATK': 'rng_atk', 'RNG_STR': 'rng_str', 'RNG_AP': 'rng_ap',
                                'CC_NB': 'cc_nb', 'CC_ATK': 'cc_atk', 'CC_STR': 'cc_str', 'CC_AP': 'cc_ap', 'CC_RNG': 'cc_rng',
                                'T': 't', 'ARMOR_SAVE': 'armor_save', 'INVUL_SAVE': 'invul_save',
                                'SIZE_RADIUS': 'size_radius'  # New: Extract size_radius if defined in TS
                            }
                            
                            for ts_prop, py_prop in static_props.items():
                                prop_match = re.search(rf'static {ts_prop}\s*=\s*(\d+)', content)
                                if prop_match:
                                    unit_data[py_prop] = int(prop_match.group(1))
                            
                            # Extract ICON property
                            icon_match = re.search(r'static ICON\s*=\s*["\']([^"\']+)["\']', content)
                            if icon_match:
                                unit_data['ICON'] = icon_match.group(1)
                            else:
                                unit_data['ICON'] = f"icons/{unit_name}.webp"  # Default fallback
                            
                            # Determine unit type from class hierarchy - check 4-part classes first, then fallback to 2-part
                            if ('SpaceMarineInfantryTroopRangedSwarm' in content or 'SpaceMarineInfantryTroopRangedElite' in content or 
                                'SpaceMarineInfantryLeaderTroopRangedElite' in content or 'TyranidInfantrySwarmRangedSwarm' in content or
                                'SpaceMarineRangedUnit' in content or 'TyranidRangedUnit' in content):
                                unit_data['is_ranged'] = True
                                unit_data['is_melee'] = False
                            elif ('SpaceMarineInfantryTroopMeleeTroop' in content or 'SpaceMarineInfantryLeaderEliteMeleeElite' in content or
                                'TyranidInfantrySwarmMeleeSwarm' in content or 'TyranidInfantryEliteMeleeElite' in content or
                                'SpaceMarineMeleeUnit' in content or 'TyranidMeleeUnit' in content):
                                unit_data['is_ranged'] = False
                                unit_data['is_melee'] = True
                            else:
                                # Must determine from actual weapon stats (no defaults)
                                if 'rng_rng' not in unit_data or 'cc_dmg' not in unit_data:
                                    raise KeyError(f"Unit '{unit_name}' missing weapon stats to determine is_ranged/is_melee")
                                unit_data['is_ranged'] = unit_data['rng_rng'] > 1
                                unit_data['is_melee'] = unit_data['cc_dmg'] > 0
                            
                            # size_radius defaults to 1 for hex-based gameplay (standard unit size)
                            if 'size_radius' not in unit_data:
                                unit_data['size_radius'] = 1
                            
                            # Validate we got essential data
                            if all(prop in unit_data for prop in ['hp_max', 'move', 'rng_rng', 'rng_dmg', 'cc_dmg', 'cc_rng', 'rng_nb', 'rng_atk', 'rng_str', 'rng_ap', 't', 'armor_save', 'invul_save']):
                                definitions[unit_name] = unit_data
                            # Remove incomplete data warnings to reduce log clutter
        
        # Reduced verbosity - unit loading completed silently
        return definitions

    def _get_default_rewards(self):
        """Removed following AI_INSTRUCTIONS.md - all rewards must come from config files."""
        raise FileNotFoundError("Rewards configuration not found. AI_INSTRUCTIONS.md requires all rewards come from config files.")

    def _get_unit_reward_config(self, unit):
        """Get reward configuration for specific unit type using dynamic registry."""
        if "unit_type" not in unit:
            raise KeyError("Unit missing required 'unit_type' field")
        unit_type = unit["unit_type"]
        
        # Primary method: Get agent key dynamically from unit registry
        if hasattr(self, 'unit_registry'):
            try:
                agent_key = self.unit_registry.get_model_key(unit_type)
                if agent_key in self.rewards_config:
                    return self.rewards_config[agent_key]
                else:
                    available_agent_keys = list(self.rewards_config.keys())
                    raise KeyError(f"Agent key '{agent_key}' for unit '{unit_type}' not found in rewards config. Available agent keys: {available_agent_keys}")
            except ValueError as e:
                raise ValueError(f"Failed to get model key for unit '{unit_type}': {e}")
        
        # Fallback: Try direct unit type lookup
        if unit_type in self.rewards_config:
            return self.rewards_config[unit_type]
        
        # No registry available and no direct match
        raise RuntimeError(f"Unit registry not available and unit type '{unit_type}' not found in rewards config. Available types: {list(self.rewards_config.keys())}")

    def reset(self, seed=None, options=None):
        """Reset environment to initial state."""
        super().reset(seed=seed)

        # Reset game state
        self.current_phase = "move"  # Always start with move per AI_GAME.md
        self.current_player = 1  # AI starts
        self.current_turn = 1
        self.game_over = False
        self.winner = None
        self.phase_acted_units = set()
        
        # Reset phase tracking for AI_GAME.md compliance
        self.moved_units.clear()
        self.shot_units.clear()
        self.charged_units.clear()
        self.attacked_units.clear()
        
        # Reset step counter
        self.step_count = 0
        
        # Clear explicit unit tracking for clean state
        self._last_acting_unit = None
        self._last_target_unit = None
        
        # Reset units
        # Use stored scenario path (either specified or default)
        with open(self.scenario_path, 'r') as f:
            scenario_data = json.load(f)
            
        if isinstance(scenario_data, list):
            scenario_units = scenario_data
        elif isinstance(scenario_data, dict):
            scenario_units = scenario_data.get("units", list(scenario_data.values()))
        
        self.units = []
        for unit_data in scenario_units:
            unit_type = unit_data["unit_type"]
            unit = copy.deepcopy(self.unit_definitions[unit_type])
            # Generic icon assignment: Bot space marines get red versions
            if unit_data["player"] == 0:  # Bot player
                icon_name = f"icons/{unit_type}_red.webp"
            else:  # AI player uses original icons
                if "ICON" not in unit:
                    raise KeyError(f"Unit '{unit_type}' missing required 'ICON' field")
                icon_name = unit["ICON"]
            
            unit.update({
                "id": unit_data["id"],
                "player": unit_data["player"],
                "col": unit_data["col"],
                "row": unit_data["row"],
                "alive": True,
                "cur_hp": unit["hp_max"],
                "has_moved": False,
                "has_shot": False,
                "has_charged": False,
                "has_attacked": False,
                "ICON": icon_name,
                # All shooting attributes must be defined (no defaults)
                "rng_nb": unit["rng_nb"],
                "rng_atk": unit["rng_atk"],
                "rng_str": unit["rng_str"],
                "rng_ap": unit["rng_ap"],
                "t": unit["t"],
                "armor_save": unit["armor_save"],
                "invul_save": unit["invul_save"]
            })
            self.units.append(unit)
        
        # Update unit lists
        self.ai_units = [u for u in self.units if u["player"] == 1 and u["alive"]]
        self.enemy_units = [u for u in self.units if u["player"] == 0 and u["alive"]]
        
        # Reset replay
        self.replay_data = []
        
        return self._get_obs(), self._get_info()

    def _get_obs(self):
        """Get current observation with dynamic size based on max_units."""
        obs_size = self.max_units * 11 + 4
        obs = np.zeros(obs_size, dtype=np.float32)
        
        # AI units (first max_units * 7 elements: max_units units × 7 values each)
        ai_units_alive = [u for u in self.ai_units if u["alive"]]
        
        for i in range(self.max_units):  # Dynamic slots for AI units
            if i < len(ai_units_alive):
                unit = ai_units_alive[i]
                base_idx = i * 7
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit["cur_hp"] / unit["hp_max"]
                obs[base_idx + 3] = 1.0 if unit["has_moved"] else 0.0
                obs[base_idx + 4] = 1.0 if unit["has_shot"] else 0.0
                obs[base_idx + 5] = 1.0 if unit["has_charged"] else 0.0
                obs[base_idx + 6] = 1.0 if unit["has_attacked"] else 0.0
        
        # Enemy units (next max_units * 4 elements: max_units units × 4 values each)
        enemy_units_alive = [u for u in self.enemy_units if u["alive"]]
        for i in range(self.max_units):  # Dynamic slots for enemy units
            if i < len(enemy_units_alive):
                unit = enemy_units_alive[i]
                base_idx = self.max_units * 7 + i * 4
                obs[base_idx] = unit["col"] / self.board_size[0]
                obs[base_idx + 1] = unit["row"] / self.board_size[1]
                obs[base_idx + 2] = unit["cur_hp"] / unit["hp_max"]
                obs[base_idx + 3] = 1.0  # alive
        
        # Phase encoding (last 4 elements)
        phase_idx = self.max_units * 11  # Dynamic position based on max_units
        if self.current_phase == "move":
            obs[phase_idx] = 1.0
        elif self.current_phase == "shoot":
            obs[phase_idx + 1] = 1.0
        elif self.current_phase == "charge":
            obs[phase_idx + 2] = 1.0
        elif self.current_phase == "combat":
            obs[phase_idx + 3] = 1.0
        
        return obs

    def _get_eligible_units(self):
        """Get units eligible for current phase following AI_GAME.md rules exactly."""
        eligible = []
        ai_units_alive = [u for u in self.ai_units if u["alive"]]
        if self.controlled_agent:
            ai_units_alive = [u for u in ai_units_alive 
            if self.unit_registry.get_model_key(u["unit_type"]) == self.controlled_agent]
        for unit in ai_units_alive:
            unit_id = unit["id"]
            
            if self.current_phase == "move":
                # AI_GAME.md: units that haven't moved are selectable (green outline)
                if unit_id not in self.moved_units and not self._has_adjacent_enemies(unit):
                    eligible.append(unit)
                    
            elif self.current_phase == "shoot":
                # AI_GAME.md: Only units with enemies in RNG_RNG range and haven't shot yet
                # Cannot shoot if adjacent to enemy (engaged in combat)
                if "is_ranged" not in unit:
                    raise KeyError(f"Unit missing required 'is_ranged' field")
                if (unit["is_ranged"] and unit_id not in self.shot_units and 
                    not self._has_adjacent_enemies(unit) and
                    self._has_enemies_in_shooting_range(unit)):
                    eligible.append(unit)
            elif self.current_phase == "charge":
                # AI_GAME.md: No enemy adjacent, enemy within MOVE range, hasn't charged
                if (unit_id not in self.charged_units and 
                    not self._has_adjacent_enemies(unit) and
                    self._has_enemies_in_move_range(unit)):
                    eligible.append(unit)
                    
            elif self.current_phase == "combat":
                # AI_GAME.md: Enemy within CC_RNG range, hasn't attacked this phase
                if (unit_id not in self.attacked_units and 
                    self._has_enemies_in_combat_range(unit)):
                    eligible.append(unit)
        
        return eligible

    def _has_enemies_in_range(self, unit):
        """Check if unit has enemies within shooting range."""
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if "rng_rng" not in unit:
                    raise KeyError(f"Unit missing required 'rng_rng' field")
                if is_unit_in_range(unit, enemy, unit["rng_rng"]):
                    return True
        return False

    def _can_charge(self, unit):
        """Check if unit can charge (enemy within move range, not adjacent)."""
        for enemy in self.enemy_units:
            if enemy["alive"]:
                dist = get_hex_distance(unit, enemy)
                if "move" not in unit:
                    raise KeyError(f"Unit missing required 'move' field")
                if dist <= unit["move"] and dist > 1:  # Can reach but not adjacent
                    return True
        return False

    def _has_adjacent_enemies(self, unit):
        """Check if unit has adjacent enemies for combat using hex distance."""
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if are_units_adjacent(unit, enemy):
                    return True
        return False

    def _has_enemies_in_shooting_range(self, unit):
        """Check if unit has enemies within RNG_RNG shooting range per AI_GAME.md."""
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if "rng_rng" not in unit:
                    raise KeyError(f"Unit missing required 'rng_rng' field")
                if is_unit_in_range(unit, enemy, unit["rng_rng"]):
                    return True
        return False
    
    def _has_enemies_in_move_range(self, unit):
        """Check if unit has enemies within MOVE range per AI_GAME.md."""
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if "move" not in unit:
                    raise KeyError(f"Unit missing required 'move' field")
                if is_unit_in_range(unit, enemy, unit["move"]):
                    return True
        return False
    
    def get_agent_units(self, agent_key: str) -> List:
        """Get all units controlled by a specific agent."""
        return [u for u in self.ai_units if u["alive"] and 
                self.unit_registry.get_model_key(u["unit_type"]) == agent_key]
    
    def set_controlled_agent(self, agent_key: str):
        """Set which agent this environment instance controls."""
        self.controlled_agent = agent_key
        
    def get_current_controlling_agent(self) -> str:
        """Get the agent that should act in current phase."""
        eligible_units = self._get_eligible_units()
        if not eligible_units:
            return None
        # Return the agent type of the first eligible unit
        return self.unit_registry.get_model_key(eligible_units[0]["unit_type"])

    def _has_enemies_in_combat_range(self, unit):
        """Check if unit has enemies within CC_RNG combat range per AI_GAME.md."""
        if "cc_rng" not in unit:
            raise KeyError(f"Unit missing required 'cc_rng' field")
        combat_range = unit["cc_rng"]
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if is_unit_in_range(unit, enemy, combat_range):
                    return True
        return False

    def _execute_action_with_phase(self, unit, action_type):
        """Execute action with current phase context and AI_GAME.md tracking."""
        unit_rewards = self._get_unit_reward_config(unit)
        
        # AI_GAME.md: Strict phase action enforcement - Limit available actions
        if self.current_phase == "move" and action_type not in [0, 1, 2, 3]:
            # AI_GAME.md: "The only available action in this phase is moving"
            # Force action to be movement (default to action 0)
            action_type = 0
        elif self.current_phase == "shoot" and action_type != 4:
            # AI_GAME.md: "The only available action in this phase is shooting"
            # Force action to be shooting
            action_type = 4
        elif self.current_phase == "charge" and action_type != 5:
            # AI_GAME.md: Charge phase restriction
            # Force action to be charging
            action_type = 5
        elif self.current_phase == "combat" and action_type != 6:
            # AI_GAME.md: "The only available action in this phase is attacking"
            # Force action to be attacking
            action_type = 6
        
        action_success = False
        
        if self.current_phase == "move":
            reward = self._execute_move_action(unit, action_type)
            # ✅ FIXED: Move action handles has_moved internally based on success
            # Only add to moved_units if unit was actually marked as moved
            if "has_moved" not in unit:
                raise KeyError(f"Unit missing required 'has_moved' field")
            if unit["has_moved"]:
                self.moved_units.add(unit["id"])  # AI_GAME.md tracking
        elif self.current_phase == "shoot":
            reward = self._execute_shoot_action(unit, action_type)
            action_success = reward > 0
            if action_success:
                unit["has_shot"] = True
                self.shot_units.add(unit["id"])  # AI_GAME.md tracking
        elif self.current_phase == "charge":
            reward = self._execute_charge_action(unit, action_type)
            action_success = reward > 0
            if action_success:
                unit["has_charged"] = True
                self.charged_units.add(unit["id"])  # AI_GAME.md tracking
        elif self.current_phase == "combat":
            reward = self._execute_combat_action(unit, action_type)
            action_success = reward > 0
            if action_success:
                unit["has_attacked"] = True
                self.attacked_units.add(unit["id"])  # AI_GAME.md tracking
        else:
            return -0.1  # Invalid phase penalty
        
        return reward

    def _record_detailed_shooting_action(self, shooter, target, shooting_result, old_hp):
        """Record detailed shooting action with all dice rolls."""
        if not hasattr(self, 'detailed_action_log'):
            self.detailed_action_log = []
        
        action_record = {
            "turn": self.current_turn,
            "phase": self.current_phase,
            "action_type": "shooting",
            "shooter": {
                "id": shooter["id"],
                "name": shooter.get("name", f"Unit_{shooter['id']}"),
                "position": {"col": shooter["col"], "row": shooter["row"]},
                "stats": {
                    "rng_nb": shooter.get("rng_nb", 1),
                    "rng_atk": shooter.get("rng_atk", 4),
                    "rng_str": shooter.get("rng_str", 4),
                    "rng_ap": shooter.get("rng_ap", 0),
                    "rng_dmg": shooter.get("rng_dmg", 1)
                }
            },
            "target": {
                "id": target["id"],
                "name": target.get("name", f"Unit_{target['id']}"),
                "position": {"col": target["col"], "row": target["row"]},
                "stats": {
                    "t": target.get("t", 4),
                    "armor_save": target.get("armor_save", 4),
                    "invul_save": target.get("invul_save", 0)
                },
                "hp_before": old_hp,
                "hp_after": target["cur_hp"]
            },
            "shooting_summary": shooting_result["summary"],
            "total_damage": shooting_result["totalDamage"]
        }
        
        self.detailed_action_log.append(action_record)

    def _record_detailed_combat_action(self, attacker, target, combat_result, old_hp):
        """Record detailed combat action with all dice rolls."""
        if not hasattr(self, 'detailed_action_log'):
            self.detailed_action_log = []
        
        action_record = {
            "turn": self.current_turn,
            "phase": self.current_phase,
            "action_type": "combat",
            "attacker": {
                "id": attacker["id"],
                "name": attacker.get("name", f"Unit_{attacker['id']}"),
                "position": {"col": attacker["col"], "row": attacker["row"]},
                "stats": {
                    "cc_nb": attacker.get("cc_nb", 1),
                    "cc_atk": attacker.get("cc_atk", 4),
                    "cc_str": attacker.get("cc_str", 4),
                    "cc_ap": attacker.get("cc_ap", 0),
                    "cc_dmg": attacker.get("cc_dmg", 1)
                }
            },
            "target": {
                "id": target["id"],
                "name": target.get("name", f"Unit_{target['id']}"),
                "position": {"col": target["col"], "row": target["row"]},
                "stats": {
                    "t": target.get("t", 4),
                    "armor_save": target.get("armor_save", 4),
                    "invul_save": target.get("invul_save", 0)
                },
                "hp_before": old_hp,
                "hp_after": target["cur_hp"]
            },
            "combat_summary": combat_result["summary"],
            "total_damage": combat_result["totalDamage"],
            "attacks_detail": combat_result["attackDetails"]  # All individual dice rolls
        }
        
        self.detailed_action_log.append(action_record)

    def step(self, action):
        """Execute one step in the environment."""
        
        # Initialize reward variable
        reward = 0.0
        
        # Increment step counter and check limit
        self.step_count += 1
        
        # AI_GAME.md: Enforce ranged-first shooting rule BEFORE action execution
        if self.current_phase == "shoot":
            unit_idx = action // 8
            action_type = action % 8
            
            if action_type == 4 and unit_idx < len(self._get_eligible_units()):  # Shoot action
                eligible_units = self._get_eligible_units()
                acting_unit = eligible_units[unit_idx]
                is_ranged = self._is_ranged_unit(acting_unit)
                
                # Check if melee unit trying to shoot before all ranged units
                if not is_ranged and self._ranged_units_available():
                    if "unit_type" not in acting_unit:
                        raise KeyError("Acting unit missing required 'unit_type' field")
                    violation_msg = f"AI_GAME.md violation: Melee unit {acting_unit['unit_type']} shooting before ranged units complete"
                    self.phase_behavioral_violations.append(violation_msg)
                    unit_rewards = self._get_unit_reward_config(acting_unit)
                    if "situational_modifiers" not in unit_rewards or "ai_game_violation" not in unit_rewards["situational_modifiers"]:
                        if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                            raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {acting_unit['unit_type']}")
                        reward += unit_rewards["base_actions"]["wait"]
                    else:
                        reward += unit_rewards["situational_modifiers"]["ai_game_violation"]

        # Capture state for replay system
        self._capture_game_state(action, reward)
        if self.step_count >= self.max_steps_per_episode:
            # Episode too long, truncate it
            self.game_over = True
            self.winner = None
            unit_rewards = self._get_unit_reward_config(self.ai_units[0]) if self.ai_units else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, True, self._get_info()  # truncated=True
        if self.game_over:
            return self._get_obs(), 0.0, True, False, self._get_info()
        
        # Get eligible units for current phase
        eligible_units = self._get_eligible_units()
        
        # Keep advancing phases until we find eligible units or game ends
        phase_advances = 0
        max_phase_advances = 16  # Prevent infinite loops (2 full turns max)
        
        while not eligible_units and not self.game_over and phase_advances < max_phase_advances:
            self._advance_phase()
            eligible_units = self._get_eligible_units()
            phase_advances += 1
        
        if phase_advances >= max_phase_advances:
            # Emergency end game to prevent infinite loops
            self.game_over = True
            self.winner = None
            unit_rewards = self._get_unit_reward_config(self.ai_units[0]) if self.ai_units else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], True, False, self._get_info()
        
        if not eligible_units and not self.game_over:
            # Still no eligible units, return small negative reward
            unit_rewards = self._get_unit_reward_config(self.ai_units[0]) if self.ai_units else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, False, self._get_info()
        
        # Apply AI_GAME.md action masking before processing
        action = self._mask_invalid_actions(action, None)
        
        # Decode action
        unit_idx = action // 8
        action_type = action % 8
        
        if unit_idx >= len(eligible_units):
            # Invalid unit, small penalty
            unit_rewards = self._get_unit_reward_config(self.ai_units[0]) if self.ai_units else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, False, self._get_info()
        
        unit = eligible_units[unit_idx]
        reward = self._execute_action_with_phase(unit, action_type)
        
        # Game outcome rewards  
        unit_rewards = self._get_unit_reward_config(self.ai_units[0]) if self.ai_units else {}
        
        if not any(u["alive"] for u in self.ai_units):
            self.game_over = True
            self.winner = 0
            if "situational_modifiers" not in unit_rewards or "lose" not in unit_rewards["situational_modifiers"]:
                raise KeyError(f"Missing 'situational_modifiers.lose' in rewards config for unit type")
            reward += unit_rewards["situational_modifiers"]["lose"]
        elif not any(u["alive"] for u in self.enemy_units):
            self.game_over = True
            self.winner = 1
            if "situational_modifiers" not in unit_rewards or "win" not in unit_rewards["situational_modifiers"]:
                raise KeyError(f"Missing 'situational_modifiers.win' in rewards config for unit type")
            reward += unit_rewards["situational_modifiers"]["win"]
        elif self.current_turn >= self.max_turns:
            self.game_over = True
            self.winner = None
            if not hasattr(self, 'turn_limit_penalty') or self.turn_limit_penalty is None:
                self.turn_limit_penalty = self.config.get_turn_limit_penalty()
            reward += self.turn_limit_penalty
        
        # Replay recording handled by GameReplayIntegration wrapper
        pass
        
        # Note: Don't clear explicit unit tracking here - GameReplayIntegration wrapper needs it
        
        return self._get_obs(), reward, self.game_over, False, self._get_info()

    def _execute_action(self, unit, action_type):
        """Execute action following AI_GAME_OVERVIEW.md specifications."""
        reward = 0.0
        
        if self.current_phase == "move":
            return self._execute_move_action(unit, action_type)
        elif self.current_phase == "shoot":
            return self._execute_shoot_action(unit, action_type)
        elif self.current_phase == "charge":
            return self._execute_charge_action(unit, action_type)
        elif self.current_phase == "combat":
            return self._execute_combat_action(unit, action_type)
        
        return reward

    def _was_lowest_hp_target(self, target, target_list):
        """Check if target was the lowest HP among the target list."""
        for other_target in target_list:
            if other_target != target and other_target["cur_hp"] < target["cur_hp"]:
                return False
        return True

    def _execute_move_action(self, unit, action_type):
        """Execute movement following AI_GAME.md: only movement actions allowed."""
        
        # Set explicit tracking - PvP style (no target for movement)
        self._last_acting_unit = unit
        self._last_target_unit = None
        
        unit_rewards = self._get_unit_reward_config(unit)
        
        old_col, old_row = unit["col"], unit["row"]
        
        if action_type == 0:  # Move North
            new_row = max(0, unit["row"] - unit["move"])
            unit["row"] = new_row
        elif action_type == 1:  # Move South
            new_row = min(self.board_size[1] - 1, unit["row"] + unit["move"])
            unit["row"] = new_row
        elif action_type == 2:  # Move East
            new_col = min(self.board_size[0] - 1, unit["col"] + unit["move"])
            unit["col"] = new_col
        elif action_type == 3:  # Move West
            new_col = max(0, unit["col"] - unit["move"])
            unit["col"] = new_col
        elif action_type == 7:  # Wait (universal - second click behavior)
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            unit["has_moved"] = True
            return reward
        else:
            # Invalid action type in move phase
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]  # Penalty for invalid action
        
        # ✅ CRITICAL FIX: Check if movement actually occurred
        movement_occurred = (old_col != unit["col"]) or (old_row != unit["row"])
        
        if not movement_occurred:
            # ❌ FAILED MOVE: Unit hit wall/boundary, return negative penalty
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            # ✅ CRITICAL FIX: Mark unit as moved to prevent infinite loops
            unit["has_moved"] = True
            self.moved_units.add(unit["id"])  # Also add to phase tracking
            return reward
        
        # ✅ SUCCESSFUL MOVE: Mark unit as moved and calculate rewards
        unit["has_moved"] = True
        
        # Movement rewards based on tactical positioning (only for successful moves)
        nearest_enemy = self._get_nearest_enemy(unit)
        if nearest_enemy:
            new_dist = get_hex_distance(unit, nearest_enemy)
            
            if unit["is_ranged"]:
                # Ranged units want to be at optimal range
                optimal_range = unit["rng_rng"] - 1
                if new_dist == optimal_range:
                    if "base_actions" not in unit_rewards or "move_to_los" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.move_to_los' in rewards config for unit type {unit.get('unit_type')}")
                    reward = unit_rewards["base_actions"]["move_to_los"]
                elif new_dist < optimal_range:
                    if "base_actions" not in unit_rewards or "move_close" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.move_close' in rewards config for unit type {unit['unit_type']}")
                    reward = unit_rewards["base_actions"]["move_close"]
                else:
                    if "base_actions" not in unit_rewards or "move_away" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.move_away' in rewards config for unit type {unit.get('unit_type')}")
                    reward = unit_rewards["base_actions"]["move_away"]
            else:
                # Melee units want to get closer for charging
                if new_dist <= unit["move"]:
                    if "base_actions" not in unit_rewards or "move_to_charge" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.move_to_charge' in rewards config for unit type {unit.get('unit_type')}")
                    reward = unit_rewards["base_actions"]["move_to_charge"]
                else:
                    if "base_actions" not in unit_rewards or "move_close" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.move_close' in rewards config for unit type {unit['unit_type']}")
                    reward = unit_rewards["base_actions"]["move_close"]
        else:
            # No enemies found, movement reward
            if "base_actions" not in unit_rewards or "move_close" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.move_close' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["move_close"]
        
        # Direct PvP-style logging (after all movement processing)
        if self.replay_logger:
            self.replay_logger.log_move_action(unit, old_col, old_row, unit["col"], unit["row"], self.current_turn)
        
        return reward

    def _check_unit_second_click(self, unit, action_type):
        """Handle second click on unit = wait/end activation following AI_GAME.md."""
        # This method can be expanded for human player interface
        # For AI training, action_type 7 serves this purpose
        unit_rewards = self._get_unit_reward_config(unit)
        unit["has_moved"] = True
        if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
        return unit_rewards["base_actions"]["wait"]

    def _execute_shoot_action(self, unit, action_type):
        """Execute shooting using dice-based system: only action_type==4 shoots following AI_GAME.md."""
        unit_rewards = self._get_unit_reward_config(unit)

        # Only action 4 shoots in shoot phase; action 7 waits
        if action_type == 4:
            targets = self._get_shooting_targets(unit)
            if targets:
                target = targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                old_hp = target["cur_hp"]
                
                # Execute dice-based shooting sequence with detailed logging
                result = execute_shooting_sequence(unit, target)
                
                # Enhance result with detailed dice data for PvP compatibility
                if "shots" not in result and self.replay_logger:
                    # Reconstruct individual shots from summary for detailed logging
                    summary = result.get("summary", {})
                    detailed_shots = []
                    
                    total_shots = summary.get("totalShots", 1)
                    hits = summary.get("hits", 0)
                    wounds = summary.get("wounds", 0)
                    failed_saves = summary.get("failedSaves", 0)
                    
                    # Create individual shot records
                    for shot_num in range(total_shots):
                        from shared.gameRules import roll_d6, calculate_wound_target, calculate_save_target
                        
                        # Simulate the actual dice rolls that would have occurred
                        hit_roll = roll_d6()
                        hit_target = unit.get("rng_atk", 4)
                        hit_success = shot_num < hits
                        
                        wound_roll = roll_d6() if hit_success else 0
                        wound_target = calculate_wound_target(unit.get("rng_str", 4), target.get("t", 4)) if hit_success else 0
                        wound_success = shot_num < wounds
                        
                        save_roll = roll_d6() if wound_success else 0
                        save_target = calculate_save_target(target.get("armor_save", 4), target.get("invul_save", 0), unit.get("rng_ap", 0)) if wound_success else 0
                        save_success = not (shot_num < failed_saves)
                        
                        detailed_shots.append({
                            "hit_roll": hit_roll,
                            "hit_target": hit_target,
                            "hit": hit_success,
                            "wound_roll": wound_roll,
                            "wound_target": wound_target,
                            "wound": wound_success,
                            "save_roll": save_roll,
                            "save_target": save_target,
                            "save_success": save_success,
                            "damage": 1 if not save_success and wound_success else 0
                        })
                    
                    result["shots"] = detailed_shots
                
                total_damage = result["totalDamage"]
                target["cur_hp"] = max(0, old_hp - total_damage)

                # Enhanced logging: capture all dice roll details
                if self.save_replay:
                    self._record_detailed_shooting_action(unit, target, result, old_hp)

                # Direct PvP-style logging
                if self.replay_logger:
                    self.replay_logger.log_shooting_action(unit, target, result, self.current_turn)

                # Base ranged attack reward (scaled by damage dealt)
                if "base_actions" not in unit_rewards or "ranged_attack" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.ranged_attack' in rewards config for unit type {unit['unit_type']}")
                base_attack_reward = unit_rewards["base_actions"]["ranged_attack"]
                reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1

                # Kill bonuses
                if target["cur_hp"] <= 0:
                    target["alive"] = False
                    if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                        raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
                    reward += unit_rewards["result_bonuses"]["kill_target"]
                    if old_hp == total_damage:
                        if "result_bonuses" not in unit_rewards or "no_overkill" not in unit_rewards["result_bonuses"]:
                            raise KeyError(f"Missing 'result_bonuses.no_overkill' in rewards config for unit type {unit['unit_type']}")
                        reward += unit_rewards["result_bonuses"]["no_overkill"]
                    if self._was_lowest_hp_target(target, targets):
                        if "result_bonuses" not in unit_rewards or "target_lowest_hp" not in unit_rewards["result_bonuses"]:
                            raise KeyError(f"Missing 'result_bonuses.target_lowest_hp' in rewards config for unit type {unit['unit_type']}")
                        reward += unit_rewards["result_bonuses"]["target_lowest_hp"]
            else:
                if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                reward = unit_rewards["base_actions"]["wait"]

            unit["has_shot"] = True
            self.shot_units.add(unit["id"])
            return reward

        elif action_type == 7:
            # Set explicit tracking - PvP style (wait action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_shot"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

        else:
            # Set explicit tracking - PvP style (invalid action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_shot"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

    def _execute_charge_action(self, unit, action_type):
        """Execute charge: only action_type==5 charges following AI_GAME.md."""
        unit_rewards = self._get_unit_reward_config(unit)

        if action_type == 5:
            targets = self._get_charge_targets(unit)
            if targets:
                target = targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                old_col, old_row = unit["col"], unit["row"]
                unit["col"], unit["row"] = target["col"], target["row"]

                # Direct PvP-style logging  
                if self.replay_logger:
                    self.replay_logger.log_charge_action(unit, target, old_col, old_row, unit["col"], unit["row"], self.current_turn)

                if "base_actions" not in unit_rewards or "charge_success" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.charge_success' in rewards config for unit type {unit['unit_type']}")
                reward = unit_rewards["base_actions"]["charge_success"]
            else:
                # Set explicit tracking - PvP style (no targets available)
                self._last_acting_unit = unit
                self._last_target_unit = None
                
                if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                reward = unit_rewards["base_actions"]["wait"]

            unit["has_charged"] = True
            self.charged_units.add(unit["id"])
            return reward

        elif action_type == 7:
            # Set explicit tracking - PvP style (wait action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_charged"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

        else:
            # Set explicit tracking - PvP style (invalid action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_charged"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

    def _execute_combat_action(self, unit, action_type):
        """Execute melee attack using dice-based system: only action_type==6 attacks following AI_GAME.md."""
        unit_rewards = self._get_unit_reward_config(unit)

        # Only action 6 attacks in combat phase; action 7 waits
        if action_type == 6:
            targets = self._get_combat_targets(unit)
            if targets:
                target = targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                old_hp = target["cur_hp"]
                
                # Execute dice-based combat sequence
                from shared.gameRules import execute_combat_sequence
                result = execute_combat_sequence(unit, target)
                total_damage = result["totalDamage"]
                target["cur_hp"] = max(0, old_hp - total_damage)

                # Enhanced logging: capture all dice roll details
                if self.save_replay:
                    self._record_detailed_combat_action(unit, target, result, old_hp)

                # Direct PvP-style logging
                if self.replay_logger:
                    self.replay_logger.log_combat_action(unit, target, result, self.current_turn)

                # Base combat attack reward (scaled by damage dealt)
                if "base_actions" not in unit_rewards or "melee_attack" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.melee_attack' in rewards config for unit type {unit['unit_type']}")
                base_attack_reward = unit_rewards["base_actions"]["melee_attack"]
                reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1

                # Kill bonuses
                if target["cur_hp"] <= 0:
                    target["alive"] = False
                    if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                        raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
                    reward += unit_rewards["result_bonuses"]["kill_target"]
                    if old_hp == total_damage:
                        if "result_bonuses" not in unit_rewards or "no_overkill" not in unit_rewards["result_bonuses"]:
                            raise KeyError(f"Missing 'result_bonuses.no_overkill' in rewards config for unit type {unit['unit_type']}")
                        reward += unit_rewards["result_bonuses"]["no_overkill"]
                    if self._was_lowest_hp_target(target, targets):
                        if "result_bonuses" not in unit_rewards or "target_lowest_hp" not in unit_rewards["result_bonuses"]:
                            raise KeyError(f"Missing 'result_bonuses.target_lowest_hp' in rewards config for unit type {unit['unit_type']}")
                        reward += unit_rewards["result_bonuses"]["target_lowest_hp"]
            else:
                # Set explicit tracking - PvP style (no targets available)
                self._last_acting_unit = unit
                self._last_target_unit = None
                
                if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                reward = unit_rewards["base_actions"]["wait"]

            unit["has_attacked"] = True
            self.attacked_units.add(unit["id"])
            return reward

        elif action_type == 7:
            # Set explicit tracking - PvP style (wait action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_attacked"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

        else:
            # Set explicit tracking - PvP style (invalid action, no target)
            self._last_acting_unit = unit
            self._last_target_unit = None
            
            unit["has_attacked"] = True
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]

    def _get_shooting_targets(self, unit):
        """Get shooting targets in AI_GAME_OVERVIEW.md priority order."""
        targets = []
        in_range_enemies = []
        
        # Find enemies in range
        for enemy in self.enemy_units:
            if enemy["alive"]:
                dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
                if dist <= unit["rng_rng"]:
                    in_range_enemies.append(enemy)
        
        if not in_range_enemies:
            return targets
        
        # Priority 1: Enemy with highest threat that melee can charge but won't kill in 1 phase
        for enemy in in_range_enemies:
            if "rng_dmg" not in enemy or "cc_dmg" not in enemy:
                raise KeyError(f"Enemy missing required 'rng_dmg' or 'cc_dmg' field")
            threat_score = max(enemy["rng_dmg"], enemy["cc_dmg"])
            can_be_charged = self._can_melee_units_charge(enemy)
            melee_damages = []
            for u in self.ai_units:
                if u["alive"] and not u["is_ranged"]:
                    if "cc_dmg" not in u:
                        raise KeyError(f"Unit missing required 'cc_dmg' field")
                    melee_damages.append(u["cc_dmg"])
            wont_be_killed_melee = enemy["cur_hp"] > max(melee_damages, default=0)
            
            if can_be_charged and wont_be_killed_melee:
                targets.append(enemy)
        
        # Priority 2: Enemy with highest threat that can be killed in 1 shooting phase
        for enemy in in_range_enemies:
            if enemy not in targets and enemy["cur_hp"] <= unit["rng_dmg"]:
                targets.append(enemy)
        
        # Priority 3: Enemy with highest threat and lowest HP that can be killed in 1 phase
        remaining = [e for e in in_range_enemies if e not in targets and e["cur_hp"] <= unit["rng_dmg"]]
        def sort_key(e):
            if "rng_dmg" not in e or "cc_dmg" not in e:
                raise KeyError(f"Enemy missing required 'rng_dmg' or 'cc_dmg' field")
            return (max(e["rng_dmg"], e["cc_dmg"]), -e["cur_hp"])
        remaining.sort(key=sort_key, reverse=True)
        targets.extend(remaining)
        
        return targets[:3]  # Return top 3 priorities

    def _get_charge_targets(self, unit):
        """Get charge targets in AI_GAME_OVERVIEW.md priority order."""
        targets = []
        chargeable_enemies = []
        
        # Find enemies within charge range (move distance) but not adjacent
        for enemy in self.enemy_units:
            if enemy["alive"]:
                dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
                if 1 < dist <= unit["move"]:  # Can charge (not adjacent, within move)
                    chargeable_enemies.append(enemy)
        
        if not chargeable_enemies:
            return targets
        
        if unit["is_melee"]:
            # Melee unit charge priorities
            # Priority 1: Can kill in 1 melee phase
            for enemy in chargeable_enemies:
                if "rng_dmg" not in enemy or "cc_dmg" not in enemy:
                    raise KeyError(f"Enemy missing required 'rng_dmg' or 'cc_dmg' field")
                threat_score = max(enemy["rng_dmg"], enemy["cc_dmg"])
                if enemy["cur_hp"] <= unit["cc_dmg"]:
                    targets.append(enemy)
            
            # Priority 2: Highest threat, lowest HP, HP >= unit's CC_DMG
            for enemy in chargeable_enemies:
                if enemy not in targets and enemy["cur_hp"] >= unit["cc_dmg"]:
                    targets.append(enemy)
            
            # Priority 3: Highest threat, lowest HP
            remaining = [e for e in chargeable_enemies if e not in targets]
            def sort_key(e):
                if "rng_dmg" not in e or "cc_dmg" not in e:
                    raise KeyError(f"Enemy missing required 'rng_dmg' or 'cc_dmg' field")
                return (max(e["rng_dmg"], e["cc_dmg"]), -e["cur_hp"])
            remaining.sort(key=sort_key, reverse=True)
            targets.extend(remaining)
        else:
            # Ranged unit charge priorities (different from melee)
            # Priority 1: Highest threat, highest HP, can kill in 1 melee phase
            for enemy in chargeable_enemies:
                if enemy["cur_hp"] <= unit["cc_dmg"]:
                    targets.append(enemy)
        
        return targets[:3]

    def _get_combat_targets(self, unit):
        """Get combat targets in AI_GAME_OVERVIEW.md priority order."""
        targets = []
        combat_enemies = []
        
        # Find enemies within combat range (CC_RNG)
        if "cc_rng" not in unit:
            raise KeyError(f"Unit missing required 'cc_rng' field")
        combat_range = unit["cc_rng"]
        for enemy in self.enemy_units:
            if enemy["alive"]:
                if is_unit_in_range(unit, enemy, combat_range):
                    combat_enemies.append(enemy)
        
        if not combat_enemies:
            return targets
        
        # Priority 1: Can kill in 1 melee phase
        for enemy in combat_enemies:
            if enemy["cur_hp"] <= unit["cc_dmg"]:
                targets.append(enemy)
        
        # Priority 2: Highest threat, lowest HP
        remaining = [e for e in combat_enemies if e not in targets]
        def sort_key(e):
            if "rng_dmg" not in e or "cc_dmg" not in e:
                raise KeyError(f"Enemy missing required 'rng_dmg' or 'cc_dmg' field")
            return (max(e["rng_dmg"], e["cc_dmg"]), -e["cur_hp"])
        remaining.sort(key=sort_key, reverse=True)
        targets.extend(remaining)
        
        return targets[:2]

    def _can_melee_units_charge(self, enemy):
        """Check if any of our melee units can charge this enemy."""
        for unit in self.ai_units:
            if unit["alive"] and not unit["is_ranged"] and not unit["has_charged"]:
                dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
                if 1 < dist <= unit["move"]:
                    return True
        return False

    def _get_nearest_enemy(self, unit):
        """Get nearest alive enemy."""
        nearest = None
        min_dist = float('inf')
        
        for enemy in self.enemy_units:
            if enemy["alive"]:
                dist = get_hex_distance(unit, enemy)
                if dist < min_dist:
                    min_dist = dist
                    nearest = enemy
        
        return nearest
    
    def _is_target_adjacent_to_friendly_unit(self, target):
        """Check if target enemy is adjacent to any friendly unit (Rule 2)."""
        for friendly_unit in self.ai_units:
            if "alive" not in friendly_unit:
                raise KeyError(f"Friendly unit missing required 'alive' field")
            if friendly_unit["alive"]:
                if are_units_adjacent(target, friendly_unit):
                    return True
        return False

    def _get_valid_actions_for_phase(self, unit, current_phase):
        """Get valid action types for current phase following AI_GAME.md."""
        # AI_GAME.md: Phase-specific action restrictions
        if current_phase == "move":
            return [0, 1, 2, 3]  # Only movement actions
        elif current_phase == "shoot":
            return [4]  # Only shooting action
        elif current_phase == "charge":
            return [5]  # Only charge action
        elif current_phase == "combat":
            return [6]  # Only attack action
        else:
            return []  # No valid actions for unknown phase
    
    def _mask_invalid_actions(self, action, unit):
        """Mask invalid actions based on current phase and return valid action."""
        unit_idx = action // 8
        action_type = action % 8
        
        valid_actions = self._get_valid_actions_for_phase(unit, self.current_phase)
        
        if action_type not in valid_actions and valid_actions:
            # Force to first valid action for current phase
            new_action_type = valid_actions[0]
            new_action = unit_idx * 8 + new_action_type
            return new_action
        
        return action

    def _shoot_at_target(self, unit, target):
        """Shoot at target and return reward."""
        if not target["alive"]:
            unit_rewards = self._get_unit_reward_config(unit)
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]
        
        # PREVENT FRIENDLY FIRE: Cannot shoot friendly units
        if self._is_friendly_unit(unit, target):
            unit_rewards = self._get_unit_reward_config(unit)
            if "situational_modifiers" not in unit_rewards or "friendly_fire_penalty" not in unit_rewards["situational_modifiers"]:
                raise KeyError(f"Missing 'situational_modifiers.friendly_fire_penalty' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["situational_modifiers"]["friendly_fire_penalty"]
        
        # RULE 2: Cannot shoot enemy units adjacent to friendly units
        if self._is_target_adjacent_to_friendly_unit(target):
            unit_rewards = self._get_unit_reward_config(unit)
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]
        
        result = execute_shooting_sequence(unit, target)
        total_damage = result["totalDamage"]
        old_hp = target["cur_hp"]
        target["cur_hp"] = max(0, target["cur_hp"] - total_damage)
        
        unit_rewards = self._get_unit_reward_config(unit)
        
        # Base ranged attack reward (scaled by damage dealt)
        if "base_actions" not in unit_rewards or "ranged_attack" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.ranged_attack' in rewards config for unit type {unit['unit_type']}")
        
        base_attack_reward = unit_rewards["base_actions"]["ranged_attack"]
        reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1
        
        if target["cur_hp"] <= 0:
            target["alive"] = False
            if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
            reward += unit_rewards["result_bonuses"]["kill_target"]
            
            # Bonus for no overkill
            if old_hp == total_damage:
                if "result_bonuses" not in unit_rewards or "no_overkill" not in unit_rewards["result_bonuses"]:
                    raise KeyError(f"Missing 'result_bonuses.no_overkill' in rewards config for unit type {unit['unit_type']}")
                reward += unit_rewards["result_bonuses"]["no_overkill"]
        
        return reward

    def _charge_at_target(self, unit, target):
        """Charge at target (move adjacent)."""
        unit_rewards = self._get_unit_reward_config(unit)
        
        if not target["alive"]:
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]
        
        # Move unit adjacent to target
        dx = target["col"] - unit["col"]
        dy = target["row"] - unit["row"]
        
        # Find adjacent position
        if abs(dx) > abs(dy):
            new_col = target["col"] - (1 if dx > 0 else -1)
            new_row = target["row"]
        else:
            new_col = target["col"]
            new_row = target["row"] - (1 if dy > 0 else -1)
        
        # Ensure within bounds
        new_col = max(0, min(self.board_size[0] - 1, new_col))
        new_row = max(0, min(self.board_size[1] - 1, new_row))
        
        unit["col"] = new_col
        unit["row"] = new_row
        
        if "base_actions" not in unit_rewards or "charge_success" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.charge_success' in rewards config for unit type {unit['unit_type']}")
        return unit_rewards["base_actions"]["charge_success"]  # Charge reward

    def _is_ranged_unit(self, unit):
        """Check if unit is ranged based on unit definitions."""
        if "unit_type" not in unit:
            raise KeyError("Unit missing required 'unit_type' field")
        unit_type = unit["unit_type"]
        if unit_type not in self.unit_definitions:
            raise KeyError(f"Unit type '{unit_type}' not found in unit definitions. Available types: {list(self.unit_definitions.keys())}")
        unit_def = self.unit_definitions[unit_type]
        if "rng_rng" not in unit_def:
            # Show what fields are actually available for debugging
            available_fields = list(unit_def.keys())
            raise KeyError(f"Unit definition for '{unit_type}' missing required 'rng_rng' field. Available fields: {available_fields}")
        # Ranged units have shooting range > 1
        return unit_def["rng_rng"] > 1

    def _ranged_units_available(self):
        """Check if any ranged units can still shoot this phase."""
        for unit in self.ai_units:
            if "alive" not in unit:
                raise KeyError("Unit missing required 'alive' field")
            if "has_shot" not in unit:
                raise KeyError("Unit missing required 'has_shot' field")
            if (unit["alive"] and 
                not unit["has_shot"] and 
                self._is_ranged_unit(unit) and
                self._has_shooting_targets(unit)):
                return True
        return False

    def _has_shooting_targets(self, unit):
        """Check if unit has valid shooting targets."""
        if "unit_type" not in unit:
            raise KeyError("Unit missing required 'unit_type' field")
        unit_type = unit["unit_type"]
        if unit_type not in self.unit_definitions:
            raise KeyError(f"Unit type '{unit_type}' not found in unit definitions")
        unit_def = self.unit_definitions[unit_type]
        if "rng_rng" not in unit_def:
            raise KeyError(f"Unit definition for '{unit_type}' missing required 'RNG_RNG' field")
        unit_range = unit_def["RNG_RNG"]
        for enemy in self.enemy_units:
            if "alive" not in enemy:
                raise KeyError("Enemy missing required 'alive' field")
            if enemy["alive"]:
                distance = self._calculate_distance(unit, enemy)
                if distance <= unit_range:
                    # Rule 2: Cannot shoot enemy units adjacent to friendly units
                    if not self._is_target_adjacent_to_friendly_unit(enemy):
                        return True
        return False
    
    def _calculate_distance(self, unit1, unit2):
        """Calculate hex grid distance between two units."""
        return get_hex_distance(unit1, unit2)

    def _attack_target(self, unit, target):
        """Attack adjacent target in melee combat."""
        unit_rewards = self._get_unit_reward_config(unit)
        
        if not target["alive"]:
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["base_actions"]["wait"]
        
        # PREVENT FRIENDLY FIRE: Cannot attack friendly units
        if self._is_friendly_unit(unit, target):
            if "situational_modifiers" not in unit_rewards or "friendly_fire_penalty" not in unit_rewards["situational_modifiers"]:
                raise KeyError(f"Missing 'situational_modifiers.friendly_fire_penalty' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["situational_modifiers"]["friendly_fire_penalty"]  # Large penalty for friendly fire
        
        # Check if actually adjacent
        dist = abs(unit["col"] - target["col"]) + abs(unit["row"] - target["row"])
        if dist > 1:
            if "situational_modifiers" not in unit_rewards or "attack_wasted" not in unit_rewards["situational_modifiers"]:
                raise KeyError(f"Missing 'situational_modifiers.attack_wasted' in rewards config for unit type {unit['unit_type']}")
            return unit_rewards["situational_modifiers"]["attack_wasted"]  # Not adjacent penalty
        
        damage = unit["cc_dmg"]
        old_hp = target["cur_hp"]
        target["cur_hp"] = max(0, target["cur_hp"] - damage)
        
        if "base_actions" not in unit_rewards or "melee_attack" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.melee_attack' in rewards config for unit type {unit['unit_type']}")
        reward = unit_rewards["base_actions"]["melee_attack"]  # Base attack reward
        
        if target["cur_hp"] <= 0:
            target["alive"] = False
            if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
            reward += unit_rewards["result_bonuses"]["kill_target"]  # Kill bonus
            
            # Bonus for no overkill
            if old_hp == damage:
                if "result_bonuses" not in unit_rewards or "no_overkill" not in unit_rewards["result_bonuses"]:
                    raise KeyError(f"Missing 'result_bonuses.no_overkill' in rewards config for unit type {unit['unit_type']}")
                reward += unit_rewards["result_bonuses"]["no_overkill"]
        
        return reward

    def _get_nearest_ai_unit(self, enemy):
        """Get nearest alive AI unit for enemy targeting."""
        nearest = None
        min_dist = float('inf')
        
        for unit in self.ai_units:
            if unit["alive"]:
                dist = get_hex_distance(enemy, unit)
                if dist < min_dist:
                    min_dist = dist
                    nearest = unit
        
        return nearest

    def _validate_ai_game_compliance(self, unit, action_type, target=None):
        """
        Validate AI behavior against AI_GAME.md tactical guidelines.
        AI_INSTRUCTIONS.md: "All units must respect and follow the GAME MECHANISM as described"
        """
        violations = []
        current_phase = self.current_phase
        if "unit_type" not in unit:
            raise KeyError("Unit missing required 'unit_type' field")
        if "is_ranged" not in unit:
            raise KeyError("Unit missing required 'is_ranged' field")
        unit_type = unit['unit_type']
        is_ranged = unit['is_ranged']
        
        if current_phase == 'move':
            # AI_GAME.md: "Ranged units avoid being charged, keep 1 enemy within RNG_RNG range"
            if is_ranged and action_type in [0, 1, 2, 3]:  # Movement actions
                enemies_in_charge_range = self._count_enemies_in_charge_range(unit)
                enemies_in_shooting_range = self._count_enemies_in_shooting_range(unit)
                
                if enemies_in_charge_range > 0:
                    self.tactical_guideline_compliance['movement']['ranged_avoid_charge'] += 1
                
                if enemies_in_shooting_range == 0:
                    violations.append(f"AI_GAME.md violation: Ranged unit {unit_type} moved out of shooting range")
            
            # AI_GAME.md: "Melee units try to be in charge position"
            elif not is_ranged and action_type in [0, 1, 2, 3]:  # Movement actions
                charge_opportunities = self._count_charge_opportunities_after_move(unit)
                if charge_opportunities > 0:
                    self.tactical_guideline_compliance['movement']['melee_charge_position'] += 1
        
        elif current_phase == 'shoot':
            # AI_GAME.md: "First make the ranged units play"
            if action_type == 4:  # Shoot action
                if not is_ranged and self._ranged_units_available():
                    violations.append(f"AI_GAME.md violation: Melee unit {unit_type} shot before ranged units")
                    self.ranged_units_shot_first = False
                else:
                    self.tactical_guideline_compliance['shooting']['ranged_first'] += 1
                
                # AI_GAME.md: Priority targeting validation
                if target and not self._validate_shooting_priority(unit, target):
                    violations.append(f"AI_GAME.md violation: Unit {unit_type} violated shooting priority targeting")
                else:
                    self.tactical_guideline_compliance['shooting']['priority_targeting'] += 1
        
        elif current_phase == 'charge':
            # AI_GAME.md: Charge priority validation
            if action_type == 5 and target:  # Charge action
                if not self._validate_charge_priority(unit, target):
                    violations.append(f"AI_GAME.md violation: Unit {unit_type} violated charge priority targeting")
                else:
                    compliance_key = 'melee_priority' if not is_ranged else 'ranged_priority'
                    self.tactical_guideline_compliance['charge'][compliance_key] += 1
        
        elif current_phase == 'combat':
            # AI_GAME.md: Combat priority validation  
            if action_type == 6 and target:  # Attack action
                if not self._validate_combat_priority(unit, target):
                    violations.append(f"AI_GAME.md violation: Unit {unit_type} violated combat priority targeting")
                else:
                    self.tactical_guideline_compliance['combat']['priority_targeting'] += 1
        
        # Store violations for analysis
        self.phase_behavioral_violations.extend(violations)
        
        #if violations:
        #    print(f"⚠️ AI_GAME.md Behavioral Violations: {violations}")
        
        return len(violations) == 0

    def _validate_shooting_priority(self, shooter, target):
        """
        AI_GAME.md: Validate shooting target selection against priority system.
        Priority order from AI_GAME.md:
        1. High damage enemy, can't be killed, chargeable, would die from charge  
        2. High damage enemy, low HP, can be killed by shooting
        3. High damage enemy, can be killed by shooting
        4. High damage enemy, can't be killed by shooting
        """
        enemies_in_range = [e for e in self.enemy_units if e['alive'] and 
                            not self._is_friendly_unit(shooter, e)]
        if "rng_rng" not in shooter:
            raise KeyError("Shooter missing required 'rng_rng' field")
        enemies_in_range = [e for e in self.enemy_units if e['alive'] and 
            not self._is_friendly_unit(shooter, e) and
            abs(shooter['col'] - e['col']) + abs(shooter['row'] - e['row']) <= shooter['rng_rng']]
        if not enemies_in_range:
            return True
        
        # Get damage scores - AI_GAME.md: "highest RNG_DMG or CC_DMG (pick the best)"
        if "rng_dmg" not in target or "cc_dmg" not in target:
            raise KeyError("Target missing required 'rng_dmg' or 'cc_dmg' field")
        target_damage_score = max(target['rng_dmg'], target['cc_dmg'])
        highest_damage_enemies = []
        for e in enemies_in_range:
            if "rng_dmg" not in e or "cc_dmg" not in e:
                raise KeyError("Enemy missing required 'rng_dmg' or 'cc_dmg' field")
            if max(e['rng_dmg'], e['cc_dmg']) >= target_damage_score:
                highest_damage_enemies.append(e)
        
        # Basic priority validation - target should be among highest damage enemies
        return target in highest_damage_enemies

    def _validate_charge_priority(self, charger, target):
        """AI_GAME.md: Validate charge target selection against priority system."""
        if "move" not in charger:
            raise KeyError("Charger missing required 'move' field")
        enemies_in_range = [e for e in self.enemy_units if e['alive'] and 
                           abs(charger['col'] - e['col']) + abs(charger['row'] - e['row']) <= charger['move']]
        if not enemies_in_range:
            return True
        
        if "is_ranged" not in charger:
            raise KeyError("Charger missing required 'is_ranged' field")
        if "rng_dmg" not in target or "cc_dmg" not in target:
            raise KeyError("Target missing required 'rng_dmg' or 'cc_dmg' field")
        if "cur_hp" not in target:
            raise KeyError("Target missing required 'cur_hp' field")
        if "cc_dmg" not in charger:
            raise KeyError("Charger missing required 'cc_dmg' field")
        is_ranged_charger = charger['is_ranged']
        target_damage_score = max(target['rng_dmg'], target['cc_dmg'])
        can_kill_target = target['cur_hp'] <= charger['cc_dmg']
        
        # AI_GAME.md priority validation
        if is_ranged_charger:
            # Ranged units charge high HP enemies they can kill
            return can_kill_target and target['cur_hp'] > 0
        else:
            # Melee units prioritize high damage targets they can kill
            return target_damage_score > 0 or can_kill_target

    def _validate_combat_priority(self, attacker, target):
        """AI_GAME.md: Validate combat target selection against priority system."""
        adjacent_enemies = [e for e in self.enemy_units if e['alive'] and 
                           not self._is_friendly_unit(attacker, e) and
                           abs(attacker['col'] - e['col']) + abs(attacker['row'] - e['row']) == 1]
        if not adjacent_enemies:
            return True
        
        if "rng_dmg" not in target or "cc_dmg" not in target:
            raise KeyError("Target missing required 'rng_dmg' or 'cc_dmg' field")
        if "cur_hp" not in target:
            raise KeyError("Target missing required 'cur_hp' field")
        if "cc_dmg" not in attacker:
            raise KeyError("Attacker missing required 'cc_dmg' field")
        target_damage_score = max(target['rng_dmg'], target['cc_dmg'])
        can_kill_target = target['cur_hp'] <= attacker['cc_dmg']
        
        # AI_GAME.md Priority 1: Can kill high damage enemy
        if can_kill_target and target_damage_score > 0:
            return True
        
        # AI_GAME.md Priority 2: Highest damage enemy with lowest HP
        highest_damage_enemies = []
        for e in adjacent_enemies:
            if "rng_dmg" not in e or "cc_dmg" not in e:
                raise KeyError("Enemy missing required 'rng_dmg' or 'cc_dmg' field")
            if max(e['rng_dmg'], e['cc_dmg']) >= target_damage_score:
                highest_damage_enemies.append(e)
        
        return target in highest_damage_enemies

    def _ranged_units_available(self):
        """Check if ranged units are still available to shoot."""
        eligible_units = self._get_eligible_units()
        for unit in eligible_units:
            if "is_ranged" not in unit:
                raise KeyError("Unit missing required 'is_ranged' field")
            if "id" not in unit:
                raise KeyError("Unit missing required 'id' field")
            if unit['is_ranged'] and unit['id'] not in self.shot_units:
                return True
        return False

    def _count_enemies_in_charge_range(self, unit):
        """Count enemies within charge range (1 hex) of unit."""
        count = 0
        for enemy in self.enemy_units:
            if enemy['alive']:
                distance = abs(unit['col'] - enemy['col']) + abs(unit['row'] - enemy['row'])
                if distance == 1:
                    count += 1
        return count

    def _count_enemies_in_shooting_range(self, unit):
        """Count enemies within shooting range of unit."""
        if "rng_rng" not in unit:
            raise KeyError("Unit missing required 'rng_rng' field")
        shooting_range = unit['rng_rng']
        count = 0
        for enemy in self.enemy_units:
            if enemy['alive']:
                distance = abs(unit['col'] - enemy['col']) + abs(unit['row'] - enemy['row'])
                if distance <= shooting_range:
                    count += 1
        return count

    def _count_charge_opportunities_after_move(self, unit):
        """Count potential charge opportunities after moving."""
        if "move" not in unit:
            raise KeyError("Unit missing required 'move' field")
        move_range = unit['move']
        return move_range  # Simplified - would need full move calculation

    def _advance_phase(self):
        """Advance to next phase following AI_GAME.md phase order exactly."""
        
        # Apply phase-specific penalties before advancing
        self._apply_phase_penalties()
        
        current_phase_idx = self.phase_order.index(self.current_phase)
        
        if current_phase_idx < len(self.phase_order) - 1:
            # Move to next phase
            self.current_phase = self.phase_order[current_phase_idx + 1]
        else:
            # End of all phases - switch to other player
            self.current_phase = self.phase_order[0]  # Reset to move phase
            self.current_player = 1 - self.current_player
            
            # Reset phase tracking for new turn when back to AI player
            if self.current_player == 1:  # AI player's turn
                self.current_turn += 1
                self.moved_units.clear()
                self.shot_units.clear()
                self.charged_units.clear()
                self.attacked_units.clear()
                
                # Reset unit flags for compatibility
                for unit in self.ai_units:
                    unit["has_moved"] = False
                    unit["has_shot"] = False
                    unit["has_charged"] = False
                    unit["has_attacked"] = False
            else:
                # Execute enemy turn when switching to enemy player
                self._execute_enemy_turn()
        
        # Clear phase tracking for new phase
        self.phase_acted_units.clear()

    def _apply_phase_penalties(self):
        """Apply penalties for units that couldn't act in their optimal phase."""
        ai_units_alive = [u for u in self.ai_units if u["alive"]]
        
        if self.current_phase == "shoot":
            # Penalty for ranged units that couldn't shoot
            for unit in ai_units_alive:
                if "is_ranged" not in unit:
                    raise KeyError("Unit missing required 'is_ranged' field")
                if (unit["is_ranged"] and 
                    unit["id"] not in self.shot_units and
                    not self._has_enemies_in_shooting_range(unit)):
                    
                    unit_rewards = self._get_unit_reward_config(unit)
                    if "situational_modifiers" not in unit_rewards or "no_targets_penalty" not in unit_rewards["situational_modifiers"]:
                        raise KeyError(f"Missing 'situational_modifiers.no_targets_penalty' in rewards config for unit type {unit['unit_type']}")
                    penalty = unit_rewards["situational_modifiers"]["no_targets_penalty"]
                    
                    # Record penalty action for replay
                    if self.save_replay:
                        self._record_penalty_action(unit, "no_shooting_targets", penalty)
        
        elif self.current_phase == "combat":
            # Penalty for melee units that couldn't fight
            for unit in ai_units_alive:
                if "is_ranged" not in unit:
                    raise KeyError("Unit missing required 'is_ranged' field")
                if (not unit["is_ranged"] and 
                    unit["id"] not in self.attacked_units and
                    not self._has_adjacent_enemies(unit)):
                    
                    unit_rewards = self._get_unit_reward_config(unit)
                    if "situational_modifiers" not in unit_rewards or "no_targets_penalty" not in unit_rewards["situational_modifiers"]:
                        raise KeyError(f"Missing 'situational_modifiers.no_targets_penalty' in rewards config for unit type {unit['unit_type']}")
                    penalty = unit_rewards["situational_modifiers"]["no_targets_penalty"]
                    
                    # Record penalty action for replay
                    if self.save_replay:
                        self._record_penalty_action(unit, "no_combat_targets", penalty)

    def _execute_enemy_turn(self):
        """Execute enemy turn using scripted behavior as mentioned in AI_GAME_OVERVIEW.md."""
        # BALANCED scripted enemy behavior for training - LIMITED ACTIONS
        enemy_units_alive = [u for u in self.enemy_units if u["alive"]]
        
        # Limit total enemy actions per turn to prevent overwhelming AI
        max_enemy_actions = min(2, len(enemy_units_alive))  # Max 2 actions total
        enemy_actions_taken = 0
        
        for enemy in enemy_units_alive:
            if enemy_actions_taken >= max_enemy_actions:
                break  # Limit enemy actions to give AI a chance
                
            nearest_ai = self._get_nearest_ai_unit(enemy)
            if not nearest_ai:
                continue
            
            dist = abs(enemy["col"] - nearest_ai["col"]) + abs(enemy["row"] - nearest_ai["row"])
            
            # BALANCED: Only ONE action per enemy per turn
            action_taken = False
            
            # Priority 1: Shoot if in range (instead of moving closer)
            enemy_rng_rng = 4  # Default for enemy units
            if "rng_rng" in enemy:
                enemy_rng_rng = enemy["rng_rng"]
            enemy_rng_dmg = 0  # Default for enemy units
            if "rng_dmg" in enemy:
                enemy_rng_dmg = enemy["rng_dmg"]
            if is_unit_in_range(enemy, nearest_ai, enemy_rng_rng) and enemy_rng_dmg > 0:
                # Execute dice-based shooting for enemy
                result = execute_shooting_sequence(enemy, nearest_ai)
                total_damage = result["totalDamage"]
                nearest_ai["cur_hp"] = max(0, nearest_ai["cur_hp"] - total_damage)
                if nearest_ai["cur_hp"] <= 0:
                    nearest_ai["alive"] = False
                action_taken = True
                
                # Record bot shooting action
                if self.save_replay:
                    self._record_action(enemy, 4, 0.0)  # action_type 4 = shoot, reward 0 for bot

            # Priority 2: Melee attack if adjacent (no change needed - it's already using damage directly)
            elif are_units_adjacent(enemy, nearest_ai):
                enemy_cc_dmg = 0  # Default for enemy units
                if "cc_dmg" in enemy:
                    enemy_cc_dmg = enemy["cc_dmg"]
                if enemy_cc_dmg > 0:
                    damage = min(enemy_cc_dmg, nearest_ai["cur_hp"])  # Prevent overkill
                    nearest_ai["cur_hp"] = max(0, nearest_ai["cur_hp"] - damage)
                if nearest_ai["cur_hp"] <= 0:
                    nearest_ai["alive"] = False
                action_taken = True
                
                # Record bot melee attack action
                if self.save_replay:
                    self._record_action(enemy, 6, 0.0)  # action_type 6 = attack, reward 0 for bot
                
            # Priority 3: Move closer (only if can't attack)
            elif dist > 1:
                # Limited movement: only 1-2 hexes max
                enemy_move = 1  # Default for enemy units
                if "move" in enemy:
                    enemy_move = enemy["move"]
                move_distance = min(2, enemy_move)
                dx = nearest_ai["col"] - enemy["col"]
                dy = nearest_ai["row"] - enemy["row"]
                
                if abs(dx) > abs(dy):
                    step = min(move_distance, abs(dx)) * (1 if dx > 0 else -1)
                    enemy["col"] = max(0, min(self.board_size[0] - 1, enemy["col"] + step))
                else:
                    step = min(move_distance, abs(dy)) * (1 if dy > 0 else -1)
                    enemy["row"] = max(0, min(self.board_size[1] - 1, enemy["row"] + step))
                action_taken = True
                
                # Record bot movement action
                if self.save_replay:
                    # Determine movement direction for proper action_type
                    if abs(dx) > abs(dy):
                        action_type = 2 if dx > 0 else 3  # East or West
                    else:
                        action_type = 1 if dy > 0 else 0  # South or North
                    self._record_action(enemy, action_type, 0.0)  # Movement with reward 0 for bot
            
            if action_taken:
                enemy_actions_taken += 1
        
        # Update AI units list
        self.ai_units = [u for u in self.units if u["player"] == 1]

    def _get_nearest_ai_unit(self, enemy):
        """Get nearest alive AI unit for enemy targeting."""
        nearest = None
        min_dist = float('inf')
        
        for unit in self.ai_units:
            if unit["alive"]:
                dist = get_hex_distance(enemy, unit)
                if dist < min_dist:
                    min_dist = dist
                    nearest = unit
        
        return nearest

    def _record_action(self, unit, action_type, reward):
        """DISABLED - Using GameReplayIntegration only."""
        pass  # All replay recording handled by GameReplayIntegration

    def _record_penalty_action(self, unit, penalty_type, penalty_amount):
        """DISABLED - Using GameReplayIntegration only."""
        pass  # All replay recording handled by GameReplayIntegration

    def _get_info(self):
        """Get info dictionary for step return."""
        return {
            "current_phase": self.current_phase,
            "current_player": self.current_player,
            "current_turn": self.current_turn,
            "game_over": self.game_over,
            "winner": self.winner,  # ADD THIS LINE
            "ai_units_alive": len([u for u in self.ai_units if u.get("alive", True)]),  # Keep this one for compatibility
            "enemy_units_alive": len([u for u in self.enemy_units if u.get("alive", True)])  # Keep this one for compatibility
        }


    def save_web_compatible_replay(self, filename=None):
        """COMPLETELY DISABLED - Using GameReplayIntegration only."""
        print("⚠️ gym40k.save_web_compatible_replay() disabled - using GameReplayIntegration")
        return None

    def render(self, mode='human'):
        """Render current state for debugging."""
        if mode == 'human':
            print(f"\n=== TURN {self.current_turn} - PHASE: {self.current_phase.upper()} ===")
            
            # Show board state
            board = [['.' for _ in range(self.board_size[0])] for _ in range(self.board_size[1])]
            
            for unit in self.units:
                if unit["alive"]:
                    symbol = 'A' if unit["player"] == 1 else 'E'
                    if unit["col"] < len(board[0]) and unit["row"] < len(board):
                        board[unit["row"]][unit["col"]] = symbol
            
            for row in board:
                print(' '.join(row))
            
            print(f"\nAI Units: {len([u for u in self.ai_units if u['alive']])}")
            print(f"Enemy Units: {len([u for u in self.enemy_units if u['alive']])}")
            print(f"Eligible Units: {len(self._get_eligible_units())}")

    def _capture_game_state(self, action, reward):
        """Capture current state for replay."""
        try:
            if not hasattr(self, 'episode_states'):
                self.episode_states = []
                
            state = {
                "turn": self.current_turn,
                "phase": self.current_phase,
                "action_id": int(action) if hasattr(action, '__int__') else action,
                "reward": float(reward),
                "game_over": self.game_over,
                "units": []
            }
            
            # Capture unit states
            if hasattr(self, 'units') and self.units:
                for i, unit in enumerate(self.units):
                    if unit:
                        unit_state = {
                            "id": i,
                            "player": unit.get('player', 0),  # Keep for replay compatibility
                            "col": unit.get('col', 0),  # Keep for replay compatibility
                            "row": unit.get('row', 0),  # Keep for replay compatibility
                            "cur_hp": unit.get('cur_hp', unit.get('HP', 100)),  # Keep for replay compatibility
                            "alive": unit.get('alive', True)  # Keep for replay compatibility
                        }
                        state["units"].append(unit_state)
            
            self.episode_states.append(state)
        except Exception as e:
            pass  # Don't break training if capture fails

    def close(self):
        """Clean up environment."""
        # Replay saving now handled by GameReplayIntegration
        pass

    # _generate_combat_log_from_actions removed - using GameReplayIntegration only

    def _map_action_to_event_type(self, action_type):
        """Map action_type to combat_log event_type."""
        action_map = {
            0: "move", 1: "move", 2: "move", 3: "move",  # Movement
            4: "shoot",  # Shooting
            5: "charge", # Charge
            6: "combat", # Combat
            7: "wait",   # Wait
            -1: "penalty" # Penalty actions
        }
        return action_map.get(action_type, "unknown")

    def _format_action_message(self, action_type, unit_type, unit_id):
        """Format action message for combat log."""
        if action_type in [0, 1, 2, 3]:
            directions = ["north", "south", "east", "west"]
            direction = directions[action_type] if action_type < 4 else "unknown"
            return f"Unit {unit_type} {unit_id} moved {direction}"
        elif action_type == 4:
            return f"Unit {unit_type} {unit_id} fired ranged weapons"
        elif action_type == 5:
            return f"Unit {unit_type} {unit_id} charged into combat"
        elif action_type == 6:
            return f"Unit {unit_type} {unit_id} attacked in melee combat"
        elif action_type == 7:
            return f"Unit {unit_type} {unit_id} waited"
        elif action_type == -1:
            return f"Unit {unit_type} {unit_id} received penalty"
        else:
            return f"Unit {unit_type} {unit_id} performed unknown action"

    def _get_action_name(self, action_type):
        """Get human-readable action name."""
        action_names = {
            0: "move_north", 1: "move_south", 2: "move_east", 3: "move_west",
            4: "shoot", 5: "charge", 6: "attack", 7: "wait", -1: "penalty"
        }
        return action_names.get(action_type, f"action_{action_type}")

# Register environment with gymnasium
def register_environment():
    """Register the phase-based W40K environment with gymnasium."""
    try:
        import gymnasium as gym
        gym.register(
            id='W40K-Phases-v0',
            entry_point='ai.gym40k:W40KEnv',
        )
        print("✅ W40K Phase-based environment registered with gymnasium")
    except Exception as e:
        print(f"⚠️  Failed to register phase-based environment: {e}")

if __name__ == "__main__":
    # Test environment creation and basic functionality
    print("🎮 Testing W40K Phase-Based Environment")
    print("=" * 50)
    
    try:
        # Create environment
        env = W40KEnv()
        print("✅ Phase-based environment created successfully")
        
        # Test reset
        obs, info = env.reset()
        print(f"✅ Environment reset - observation shape: {obs.shape}")
        print(f"   Game info: Turn {info['current_turn']}, Phase {info['current_phase']}")
        print(f"   Units: {info['ai_units_alive']} AI, {info['enemy_units_alive']} enemy")
        print(f"   Eligible units: {len(env._get_eligible_units())}")
        
        # Test a few steps in different phases
        print("\n🎯 Testing phase-based actions...")
        for step in range(10):
            eligible = len(env._get_eligible_units())
            if eligible == 0:
                print(f"   Step {step}: No eligible units, phase will advance")
            
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            print(f"   Step {step}: Phase {info['current_phase']}, Reward {reward:.2f}, Eligible {len(env._get_eligible_units())}")
            
            if done:
                print(f"   Game ended! Winner: {info['winner']}")
                break
        
        # Test replay saving
        env.save_web_compatible_replay("ai/test_phase_replay.json")
        print("✅ Test phase-based replay saved")
        
        print("🎉 All phase-based tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()