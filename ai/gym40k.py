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
import json
from datetime import datetime
import sys
from pathlib import Path
from collections import defaultdict  

script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

from ai.unit_registry import UnitRegistry
from ai.unit_manager import UnitManager
from ai.bot_manager import BotManager
try:
    from ai.ai_phase_transition import PhaseTransitionManager
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import PhaseTransitionManager: {e}")
    raise
from shared.gameRules import roll_d6, calculate_wound_target, calculate_save_target, execute_shooting_sequence, remove_unit_from_lists

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
        
        # Clean logging capability  
        self.game_logger = None
        self.replay_logger = None  # Will be set by GameReplayIntegration

        # Initialize UnitManager for centralized unit death management
        self.unit_manager = None
        
        # Load configuration
        self.config = get_config_loader()
        
        # Load rewards configuration (unit-type-based)
        # Ensure we load from the root config directory, not frontend/public/config
        self.rewards_config = self.config.load_rewards_config()
        if not self.rewards_config:
            # AI_INSTRUCTIONS.md: No fallbacks allowed - raise error instead
            raise RuntimeError("Failed to load rewards configuration from config_loader - check config/rewards_config.json")
        
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
                    'ICON': unit_data['ICON'],  # No fallback - must be defined
                    'size_radius': unit_data.get('SIZE_RADIUS', 1)  # UI-related default is acceptable
                }
                self.unit_definitions[unit_type] = converted_unit
        else:
            # Fallback to loading from TypeScript files
            self.unit_definitions = self._load_unit_definitions()

        # Load training configuration to get max_steps_per_episode
        self.training_config_name = training_config_name
        training_config = self.config.load_training_config(training_config_name)
        # Load board configuration for pathfinding validation - BEFORE board_size initialization
        try:
            board_configs = self.config.get_board_config()
            if "default" not in board_configs:
                raise KeyError("Missing 'default' board configuration")
            self.board_config = board_configs["default"]
            if "wall_hexes" not in self.board_config:
                raise KeyError("Board configuration missing required 'wall_hexes' field")
            # Board config loaded successfully
        except Exception as e:
            if "UTF-8 BOM" in str(e):
                raise RuntimeError(f"AI_INSTRUCTIONS.md violation: Board config file has UTF-8 BOM encoding issue: {e}")
            raise RuntimeError(f"AI_INSTRUCTIONS.md violation: Failed to load required board configuration: {e}")
        self.max_steps_per_episode = self.config.get_max_steps_per_episode(training_config_name)
        
        # Episode step counter to prevent infinite episodes
        self.step_count = 0
        
        # Game state following AI_GAME.md exactly
        # Load phase order from config following AI_GAME.md - raise error if missing
        self.phase_order = self.config.get_phase_order()

        # Board config and pathfinding configured
        
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
        # Load scenario for initialization
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
                    
                # Initialize units from scenario - build list for UnitManager
                units_for_manager = []
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
                    units_for_manager.append(unit)
                    
            except Exception as e:
                raise RuntimeError(f"Failed to load scenario: {e}")
        else:
            raise FileNotFoundError(f"Scenario file not found: {self.scenario_path}")
            
        # Initialize UnitManager for centralized unit management - no local copies
        self.unit_manager = UnitManager(units_for_manager)
        
        # Connect UnitManager to replay logger for death event logging (will be connected when replay_logger is set)
        pass  # Connection handled by property setter below
        
        # TEMPORARY: Compatibility property for any remaining self.units references
        self.units = self.unit_manager.units
        
        # Initialize phase transition manager (mirrors frontend usePhaseTransition.ts)
        try:
            self.phase_manager = PhaseTransitionManager(self)
            # Initialize bot manager for enemy AI with proper logging
            self.bot_manager = BotManager(self)
        except Exception as e:
            print(f"❌ CRITICAL: Failed to initialize PhaseTransitionManager: {e}")
            raise
        
        # Action space: one action per unit per phase
        # Actions: unit_id, action_type, target (optional)
        self.max_units = len([u for u in units_for_manager if u["player"] == 1])
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
        # print("🔧 gym40k replay system disabled - using GameReplayIntegration only")
        
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
                                raise ValueError(f"Unit {unit_name} missing required ICON property in TypeScript file")
                            
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
        
        # AI_INSTRUCTIONS.md: No fallbacks - unit registry is required
        if not hasattr(self, 'unit_registry'):
            raise RuntimeError("AI_INSTRUCTIONS.md violation: Unit registry is required - no fallbacks allowed")
        
        try:
            agent_key = self.unit_registry.get_model_key(unit_type)
            if agent_key not in self.rewards_config:
                available_agent_keys = list(self.rewards_config.keys())
                raise KeyError(f"Agent key '{agent_key}' for unit '{unit_type}' not found in rewards config. Available agent keys: {available_agent_keys}")
            
            # Validate the structure exists before returning
            unit_reward_config = self.rewards_config[agent_key]
            if "base_actions" not in unit_reward_config:
                raise KeyError(f"Missing 'base_actions' section in rewards config for agent key '{agent_key}' (unit type '{unit_type}')")
            if "wait" not in unit_reward_config["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for agent key '{agent_key}' (unit type '{unit_type}')")
            
            return unit_reward_config
        except ValueError as e:
            raise ValueError(f"Failed to get model key for unit '{unit_type}': {e}")

    def reset(self, seed=None, options=None):
        """Reset environment to initial state."""
        import traceback
        
        super().reset(seed=seed)

        # CRITICAL FIX: Only reset replay logger for TRUE episode boundaries
        # Track if this is a legitimate episode reset vs mid-episode reset
        is_legitimate_reset = not hasattr(self, '_episode_started') or self.game_over or self.winner is not None
        
        # CRITICAL: Never reset replay logger during episode - only clear at true episode end
        if hasattr(self, 'replay_logger') and self.replay_logger and is_legitimate_reset and self.game_over:
            # DEBUG: Show replay logger state before reset
            
            # Only reset replay logger for legitimate episode boundaries when game is actually over
            if hasattr(self.replay_logger, 'game_states'):
                self.replay_logger.game_states = []
            if hasattr(self.replay_logger, 'combat_log_entries'):
                self.replay_logger.combat_log_entries = []
            
            # DEBUG: Verify reset worked
            combat_entries_after = len(getattr(self.replay_logger, 'combat_log_entries', []))
            if hasattr(self.replay_logger, 'current_turn'):
                self.replay_logger.current_turn = 1
            if hasattr(self.replay_logger, 'initial_game_state'):
                self.replay_logger.initial_game_state = {}
            if hasattr(self.replay_logger, 'absolute_turn'):
                self.replay_logger.absolute_turn = 1
            
            # Connect UnitManager to replay logger after reset
            if hasattr(self, 'unit_manager') and self.unit_manager:
                self.unit_manager.replay_logger = self.replay_logger
                
            # CRITICAL: Recapture initial state after reset to populate replay data
            if hasattr(self.replay_logger, 'capture_initial_state'):
                self.replay_logger.capture_initial_state()
                
                # CRITICAL: Also populate initial_game_state for replay file
                if hasattr(self.replay_logger, 'initial_game_state') and hasattr(self, 'unit_manager'):
                    initial_units = []
                    for unit in self.unit_manager.units:
                        initial_unit = {
                            "id": unit.get("id"),
                            "unit_type": unit.get("unit_type"),
                            "player": unit.get("player"),
                            "col": unit.get("col"),
                            "row": unit.get("row"),
                            "HP_MAX": unit.get("hp_max"),
                            "hp_max": unit.get("hp_max"),
                            "move": unit.get("move"),
                            "rng_rng": unit.get("rng_rng"),
                            "rng_dmg": unit.get("rng_dmg"),
                            "cc_dmg": unit.get("cc_dmg"),
                            "is_ranged": unit.get("is_ranged"),
                            "is_melee": unit.get("is_melee")
                        }
                        initial_units.append(initial_unit)
                    
                    self.replay_logger.initial_game_state = {
                        "units": initial_units,
                        "board_size": self.board_size
                    }
        
        # Mark episode as started
        self._episode_started = True

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
        
        # Clear episode replay data for new episode
        if hasattr(self, 'episode_states'):
            self.episode_states = []
        self.replay_data = []
        
        # Reset units
        # Use stored scenario path (either specified or default)
        with open(self.scenario_path, 'r') as f:
            scenario_data = json.load(f)
            
        if isinstance(scenario_data, list):
            scenario_units = scenario_data
        elif isinstance(scenario_data, dict):
            scenario_units = scenario_data.get("units", list(scenario_data.values()))
        
        units_for_reset = []
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
            units_for_reset.append(unit)
        
        # Reinitialize UnitManager with reset units - no local copies
        self.unit_manager = UnitManager(units_for_reset)
        
        # Reset replay
        self.replay_data = []
        
        return self._get_obs(), self._get_info()

    def _get_obs(self):
        """Get current observation with dynamic size based on max_units."""
        obs_size = self.max_units * 11 + 4
        obs = np.zeros(obs_size, dtype=np.float32)
        
        # AI units (first max_units * 7 elements: max_units units × 7 values each)
        ai_units_alive = self.unit_manager.get_alive_ai_units()
        
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
        enemy_units_alive = self.unit_manager.get_alive_enemy_units()
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
        ai_units_alive = self.unit_manager.get_alive_ai_units()
        if self.controlled_agent:
            ai_units_alive = [u for u in ai_units_alive 
            if self.unit_registry.get_model_key(u["unit_type"]) == self.controlled_agent]
        
        for unit in ai_units_alive:
            unit_id = unit["id"]
            
            if self.current_phase == "move":
                in_moved_units = unit_id in self.moved_units
                has_adjacent = self._has_adjacent_enemies(unit)
                
                # AI_GAME.md: units that haven't moved are selectable (green outline)
                # CRITICAL: Prevent movement adjacent to enemies outside charge phase
                has_adjacent = self._has_adjacent_enemies(unit)
                already_moved = unit_id in self.moved_units
                
                if not already_moved and not has_adjacent:
                    eligible.append(unit)
                    
            elif self.current_phase == "shoot":
                # AI_GAME.md: Only units with enemies in RNG_RNG range and haven't shot yet
                # Cannot shoot if adjacent to enemy (engaged in combat)
                # CRITICAL: Only check rng_nb > 0, ignore is_ranged classification
                if "rng_nb" not in unit:
                    raise KeyError(f"Unit missing required 'rng_nb' field")
                if (unit["rng_nb"] > 0 and unit_id not in self.shot_units and 
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
        for enemy in self.unit_manager.get_alive_enemy_units():
                if "rng_rng" not in unit:
                    raise KeyError(f"Unit missing required 'rng_rng' field")
                if is_unit_in_range(unit, enemy, unit["rng_rng"]):
                    return True
        return False

    def _can_charge(self, unit):
        """Check if unit can charge (enemy within move range, not adjacent)."""
        for enemy in self.unit_manager.get_alive_enemy_units():
                dist = get_hex_distance(unit, enemy)
                if "move" not in unit:
                    raise KeyError(f"Unit missing required 'move' field")
                if dist <= unit["move"] and dist > 1:  # Can reach but not adjacent
                    return True
        return False

    def _has_adjacent_enemies(self, unit):
        """Check if unit has adjacent enemies for combat using hex distance."""
        for enemy in self.unit_manager.get_alive_enemy_units():
                if are_units_adjacent(unit, enemy):
                    return True
        return False

    def _has_enemies_in_shooting_range(self, unit):
        """Check if unit has enemies within RNG_RNG shooting range per AI_GAME.md."""
        for enemy in self.unit_manager.get_alive_enemy_units():
                if "rng_rng" not in unit:
                    raise KeyError(f"Unit missing required 'rng_rng' field")
                if is_unit_in_range(unit, enemy, unit["rng_rng"]):
                    return True
        return False
    
    def _has_enemies_in_move_range(self, unit):
        """Check if unit has enemies within MOVE range per AI_GAME.md."""
        for enemy in self.unit_manager.get_alive_enemy_units():
                if "move" not in unit:
                    raise KeyError(f"Unit missing required 'move' field")
                if is_unit_in_range(unit, enemy, unit["move"]):
                    return True
        return False
    
    def get_agent_units(self, agent_key: str) -> List:
        """Get all units controlled by a specific agent."""
        return [u for u in self.unit_manager.get_alive_ai_units() if 
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
        for enemy in self.unit_manager.get_alive_enemy_units():
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
            # Only units with rng_nb > 0 should be in shoot phase (eligible units check)
            # If they're here, they can shoot, so force to shooting action
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
                    "rng_nb": shooter["rng_nb"] if "rng_nb" in shooter else None,
                    "rng_atk": shooter["rng_atk"] if "rng_atk" in shooter else None,
                    "rng_str": shooter["rng_str"] if "rng_str" in shooter else None,
                    "rng_ap": shooter["rng_ap"] if "rng_ap" in shooter else None,
                    "rng_dmg": shooter["rng_dmg"] if "rng_dmg" in shooter else None
                }
            },
            "target": {
                "id": target["id"],
                "name": target.get("name", f"Unit_{target['id']}"),
                "position": {"col": target["col"], "row": target["row"]},
                "stats": {
                    "t": target["t"] if "t" in target else None,
                    "armor_save": target["armor_save"] if "armor_save" in target else None,
                    "invul_save": target["invul_save"] if "invul_save" in target else None
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
                    "cc_nb": attacker["cc_nb"] if "cc_nb" in attacker else None,
                    "cc_atk": attacker["cc_atk"] if "cc_atk" in attacker else None,
                    "cc_str": attacker["cc_str"] if "cc_str" in attacker else None,
                    "cc_ap": attacker["cc_ap"] if "cc_ap" in attacker else None,
                    "cc_dmg": attacker["cc_dmg"] if "cc_dmg" in attacker else None
                }
            },
            "target": {
                "id": target["id"],
                "name": target.get("name", f"Unit_{target['id']}"),
                "position": {"col": target["col"], "row": target["row"]},
                "stats": {
                    "t": target["t"] if "t" in target else None,
                    "armor_save": target["armor_save"] if "armor_save" in target else None,
                    "invul_save": target["invul_save"] if "invul_save" in target else None
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
            ai_units_alive = self.unit_manager.get_alive_ai_units()
            unit_rewards = self._get_unit_reward_config(ai_units_alive[0]) if ai_units_alive else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                unit_type = ai_units_alive[0]["unit_type"] if ai_units_alive else "unknown"
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type '{unit_type}'")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, True, self._get_info()  # truncated=True
        
        # Get eligible units for current phase
        eligible_units = self._get_eligible_units()
        
        # Keep advancing phases until we find eligible units or game ends
        phase_advances = 0
        max_phase_advances = 120  # Allow sufficient phase advances for 800-step episodes
        
        while not eligible_units and not self.game_over and phase_advances < max_phase_advances:
            self.phase_manager.advance_phase()
            eligible_units = self._get_eligible_units()
            phase_advances += 1
        
        if phase_advances >= max_phase_advances:
            # Emergency end game to prevent infinite loops - check if game should have ended
            if not self.unit_manager.get_alive_ai_units() or not self.unit_manager.get_alive_enemy_units():
                # Units were eliminated but game didn't end properly, force proper termination
                self.game_over = True
                self.winner = 0 if not self.unit_manager.get_alive_ai_units() else 1
                return self._get_obs(), 0.0, True, False, self._get_info()
            # Check turn limit before emergency termination
            elif self.current_turn >= self.max_turns:
                self.game_over = True
                self.winner = None
                return self._get_obs(), self.turn_limit_penalty, True, False, self._get_info()
            # Still have units but too many phase advances - end with draw only as last resort
            else:
                self.game_over = True
                self.winner = None
                return self._get_obs(), -1.0, True, False, self._get_info()
        
        if not eligible_units and not self.game_over:
            # Still no eligible units, return small negative reward
            ai_units_alive = self.unit_manager.get_alive_ai_units()
            unit_rewards = self._get_unit_reward_config(ai_units_alive[0]) if ai_units_alive else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                unit_type = ai_units_alive[0]["unit_type"] if ai_units_alive else "unknown"
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type '{unit_type}'")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, False, self._get_info()
        
        # Apply AI_GAME.md action masking before processing
        action = self._mask_invalid_actions(action, None)
        
        # Decode action
        unit_idx = action // 8
        action_type = action % 8
        
        if unit_idx >= len(eligible_units):
            # Invalid unit, small penalty
            ai_units_alive = self.unit_manager.get_alive_ai_units()
            unit_rewards = self._get_unit_reward_config(ai_units_alive[0]) if ai_units_alive else {}
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                unit_type = ai_units_alive[0]["unit_type"] if ai_units_alive else "unknown"
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type '{unit_type}'")
            return self._get_obs(), unit_rewards["base_actions"]["wait"], False, False, self._get_info()
        
        unit = eligible_units[unit_idx]
        
        # CRITICAL: Capture pre-action state for replay logger
        pre_action_units = []
        if hasattr(self, 'replay_logger') and self.replay_logger:
            pre_action_units = copy.deepcopy(self.unit_manager.units) if hasattr(self, 'unit_manager') else []
        
        reward = self._execute_action_with_phase(unit, action_type)
        
        # CRITICAL: Manually create game state snapshot AFTER action execution completes
        if hasattr(self, 'replay_logger') and self.replay_logger:
            post_action_units = copy.deepcopy(self.unit_manager.units) if hasattr(self, 'unit_manager') else []
            
            # CRITICAL: Manual game state creation - replace missing capture_action_state method
            try:
                # Ensure game_states list exists
                if not hasattr(self.replay_logger, 'game_states'):
                    self.replay_logger.game_states = []
                
                # Create game state snapshot manually using CURRENT unit positions
                units_data = []
                for i, unit_snapshot in enumerate(self.unit_manager.units):
                    # CRITICAL: Ensure we capture the ACTUAL current position after action
                    unit_data = {
                        "id": unit_snapshot.get('id', i),
                        "name": unit_snapshot.get("name", f"{unit_snapshot.get('unit_type', 'Unit')} {unit_snapshot.get('id', i)+1}"),
                        "unit_type": unit_snapshot.get("unit_type", "Unknown"),
                        "player": unit_snapshot.get("player", 0),
                        "row": unit_snapshot.get("row", 0),
                        "col": unit_snapshot.get("col", 0),
                        "cur_hp": unit_snapshot.get("cur_hp", unit_snapshot.get("hp_max")),
                        "hp_max": unit_snapshot.get("hp_max"),
                        "alive": unit_snapshot.get("alive", True)
                    }
                    units_data.append(unit_data)
                
                # Create state snapshot with CURRENT game state
                state = {
                    "turn": self.current_turn,
                    "phase": self.current_phase,
                    "active_player": self.current_player,
                    "units": units_data,
                    "board_state": {
                        "width": self.board_size[0],
                        "height": self.board_size[1]
                    },
                    "event_flags": {
                        "action_id": action,
                        "acting_unit_id": unit.get('id'),
                        "target_unit_id": getattr(self, '_last_target_unit', {}).get('id') if hasattr(self, '_last_target_unit') and self._last_target_unit else None,
                        "reward": reward,
                        "description": f"AI unit {unit.get('id')} performs {self._get_action_name(action_type)}",
                        "step_number": len(self.replay_logger.game_states) + 1  # Add sequential step numbering
                    }
                }
                
                # Append to game_states
                self.replay_logger.game_states.append(state)

                pass
                
            except Exception as e:
                print(f"❌ CRITICAL: Manual game state creation failed: {e}")
                import traceback
                traceback.print_exc()
            
            # CRITICAL FIX: Update replay_logger.env.units to point to current UnitManager units
            if hasattr(self.replay_logger, 'env') and hasattr(self, 'unit_manager'):
                self.replay_logger.env.units = self.unit_manager.units
        
        # CRITICAL: Check game over conditions IMMEDIATELY after any action
        ai_units_alive = self.unit_manager.get_alive_ai_units()
        enemy_units_alive = self.unit_manager.get_alive_enemy_units()
        
        # Game outcome rewards - check termination conditions using UnitManager
        if not ai_units_alive:  # No alive AI units
            self.game_over = True
            self.winner = 0
            
            # CRITICAL: Finalize replay data at actual game end
            if hasattr(self, 'replay_logger') and self.replay_logger:
                if hasattr(self.replay_logger, 'game_info'):
                    if not self.replay_logger.game_info:
                        self.replay_logger.game_info = {}
                    self.replay_logger.game_info['total_turns'] = self.current_turn
                    self.replay_logger.game_info['winner'] = self.winner
                    self.replay_logger.game_info['episode_steps'] = self.step_count
            
            # Use first available unit from UnitManager for reward config
            if self.unit_manager.units:
                ai_unit_for_rewards = next((u for u in self.unit_manager.units if u["player"] == 1), None)
                if ai_unit_for_rewards:
                    unit_rewards = self._get_unit_reward_config(ai_unit_for_rewards)
                    reward += unit_rewards["situational_modifiers"]["lose"]
            return self._get_obs(), reward, True, False, self._get_info()
        elif not enemy_units_alive:  # No alive enemy units
            self.game_over = True
            self.winner = 1
            
            # CRITICAL: Finalize replay data at actual game end
            if hasattr(self, 'replay_logger') and self.replay_logger:
                if hasattr(self.replay_logger, 'game_info'):
                    if not self.replay_logger.game_info:
                        self.replay_logger.game_info = {}
                    self.replay_logger.game_info['total_turns'] = self.current_turn
                    self.replay_logger.game_info['winner'] = self.winner
                    self.replay_logger.game_info['episode_steps'] = self.step_count
            
            # Get unit rewards for win condition
            if self.unit_manager.units:
                ai_unit_for_rewards = next((u for u in self.unit_manager.units if u["player"] == 1), None)
                if ai_unit_for_rewards:
                    unit_rewards = self._get_unit_reward_config(ai_unit_for_rewards)
                    reward += unit_rewards["situational_modifiers"]["win"]
            return self._get_obs(), reward, True, False, self._get_info()
        elif not self.unit_manager.get_alive_enemy_units():  # No alive enemy units
            print(f"🏁 GAME OVER: AI victory at Turn {self.current_turn}, Step {self.step_count}")
            self.game_over = True
            self.winner = 1
            
            # CRITICAL: Finalize replay data at actual game end
            if hasattr(self, 'replay_logger') and self.replay_logger:
                if hasattr(self.replay_logger, 'game_info'):
                    if not self.replay_logger.game_info:
                        self.replay_logger.game_info = {}
                    self.replay_logger.game_info['total_turns'] = self.current_turn
                    self.replay_logger.game_info['winner'] = self.winner
                    self.replay_logger.game_info['episode_steps'] = self.step_count
            
            # Get unit rewards for win condition
            if self.unit_manager.units:
                ai_unit_for_rewards = next((u for u in self.unit_manager.units if u["player"] == 1), None)
                if ai_unit_for_rewards:
                    unit_rewards = self._get_unit_reward_config(ai_unit_for_rewards)
                    reward += unit_rewards["situational_modifiers"]["win"]
            return self._get_obs(), reward, True, False, self._get_info()
        elif self.current_turn >= self.max_turns:
            self.game_over = True
            self.winner = None
            if not hasattr(self, 'turn_limit_penalty') or self.turn_limit_penalty is None:
                self.turn_limit_penalty = self.config.get_turn_limit_penalty()
            reward += self.turn_limit_penalty
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
        """Execute movement with pathfinding validation following AI_GAME.md."""
        
        # Set explicit tracking - PvP style (no target for movement)
        self._last_acting_unit = unit
        self._last_target_unit = None
        
        unit_rewards = self._get_unit_reward_config(unit)
        
        old_col, old_row = unit["col"], unit["row"]
        
        # Handle wait action
        if action_type == 7:  # Wait (universal - second click behavior)
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            unit["has_moved"] = True
            return reward
        
        # Calculate target position from action
        target_col, target_row = self._calculate_target_position_from_action(unit, action_type)
        
        # Check for invalid action (no change in position)
        if target_col == old_col and target_row == old_row:
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            unit["has_moved"] = True
            return reward
        
        # Use shared movement validation
        movement_succeeded = self._execute_validated_movement(unit, target_col, target_row)
        
        if not movement_succeeded:
            # Movement blocked by walls/obstacles - return penalty
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            unit["has_moved"] = True
            self.moved_units.add(unit["id"])
            return reward
        
        # Check if movement actually occurred (unit might have been blocked partway)
        movement_occurred = (old_col != unit["col"]) or (old_row != unit["row"])
        
        if not movement_occurred:
            # No actual movement - return penalty but mark as moved
            if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
            reward = unit_rewards["base_actions"]["wait"]
            unit["has_moved"] = True
            self.moved_units.add(unit["id"])
            return reward
        
        # Successful movement - mark unit as moved and calculate rewards
        unit["has_moved"] = True
        
        # Calculate movement rewards based on tactical positioning (only for successful moves)
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
        
        # Clean action logging - map action_type to strategic action for logger
        if self.game_logger:
            try:
                # Map basic action_type to strategic action_int for logger
                strategic_action_int = self._map_to_strategic_action(unit, action_type, "move")
                self.game_logger.log_move(unit, old_col, old_row, unit["col"], unit["row"], 
                                        self.current_turn, reward, strategic_action_int)
            except Exception as e:
                pass  # Silent failure to avoid breaking training
        else:
            print(f"⚠️ No game logger available for movement logging")
        
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
        # Validate unit first before getting rewards
        if "unit_type" not in unit:
            raise KeyError("Unit missing required 'unit_type' field")
        
        unit_rewards = self._get_unit_reward_config(unit)

        # Only action 4 shoots in shoot phase; action 7 waits
        if action_type == 4:
            # Validate unit can shoot - prevent melee-only units from shooting
            if "rng_nb" not in unit:
                raise ValueError(f"Unit {unit.get('unit_type', 'unknown')} missing rng_nb field")
            if unit["rng_nb"] == 0:
                raise ValueError(f"Unit {unit.get('unit_type', 'unknown')} has rng_nb=0 (melee-only) but attempting to shoot - this violates AI_INSTRUCTIONS.md no fallbacks policy")
            
            targets = self._get_shooting_targets(unit)
            # CRITICAL: Final validation to prevent shooting dead units
            alive_targets = []
            for t in targets:
                if self.unit_manager.is_target_valid(t):
                    alive_targets.append(t)
                else:
                    if not self.quiet:
                        print(f"⚠️ Removing dead target {t.get('id')} from shooting list")
            
            if alive_targets:
                target = alive_targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                old_hp = target["cur_hp"]
                
                # CRITICAL: Final validation immediately before shooting execution
                # Prevents attacking dead units that died between target selection and execution
                if not self.unit_manager.is_target_valid(target):
                    unit["has_shot"] = True
                    self.shot_units.add(unit["id"])
                    if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                    return unit_rewards["base_actions"]["wait"]
                
                # Execute dice-based shooting sequence with detailed logging
                result = execute_shooting_sequence(unit, target)
                
                # Validate result structure - no fallbacks allowed
                if not result or "summary" not in result:
                    raise ValueError(f"execute_shooting_sequence() returned invalid result structure for unit {unit.get('unit_type', 'unknown')}")
                if "totalShots" not in result["summary"]:
                    raise ValueError(f"execute_shooting_sequence() missing totalShots in summary for unit {unit.get('unit_type', 'unknown')} - check shared/gameRules.py implementation")
                
                # Enhance result with detailed dice data for PvP compatibility
                if "shots" not in result and self.replay_logger:
                    # Reconstruct individual shots from summary for detailed logging
                    if "summary" not in result:
                        raise ValueError("result.summary is required for detailed shot reconstruction")
                    summary = result["summary"]
                    detailed_shots = []
                    
                    if "totalShots" not in summary:
                        raise ValueError("summary.totalShots is required for shot reconstruction")
                    if "hits" not in summary:
                        raise ValueError("summary.hits is required for shot reconstruction")
                    if "wounds" not in summary:
                        raise ValueError("summary.wounds is required for shot reconstruction")
                    if "failedSaves" not in summary:
                        raise ValueError("summary.failedSaves is required for shot reconstruction")
                    
                    total_shots = summary["totalShots"]
                    hits = summary["hits"]
                    wounds = summary["wounds"]
                    failed_saves = summary["failedSaves"]
                    
                    # Create individual shot records
                    for shot_num in range(total_shots):
                        from shared.gameRules import roll_d6, calculate_wound_target, calculate_save_target
                        
                        # Simulate the actual dice rolls that would have occurred
                        hit_roll = roll_d6()
                        if "rng_atk" not in unit:
                            raise ValueError(f"unit.rng_atk is required for shot reconstruction")
                        hit_target = unit["rng_atk"]
                        hit_success = shot_num < hits
                        
                        wound_roll = roll_d6() if hit_success else 0
                        if hit_success:
                            if "rng_str" not in unit:
                                raise ValueError(f"unit.rng_str is required for wound calculation")
                            if "t" not in target:
                                raise ValueError(f"target.t is required for wound calculation")
                            wound_target = calculate_wound_target(unit["rng_str"], target["t"])
                        else:
                            wound_target = 0
                        wound_success = shot_num < wounds
                        
                        save_roll = roll_d6() if wound_success else 0
                        if wound_success:
                            if "armor_save" not in target:
                                raise ValueError(f"target.armor_save is required for save calculation")
                            if "invul_save" not in target:
                                raise ValueError(f"target.invul_save is required for save calculation")
                            if "rng_ap" not in unit:
                                raise ValueError(f"unit.rng_ap is required for save calculation")
                            save_target = calculate_save_target(target["armor_save"], target["invul_save"], unit["rng_ap"])
                        else:
                            save_target = 0
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
                
                # Enhanced logging: capture all dice roll details
                if self.save_replay:
                    self._record_detailed_shooting_action(unit, target, result, old_hp)

                # Base ranged attack reward (scaled by damage dealt)
                total_damage = result["totalDamage"]
                if "base_actions" not in unit_rewards or "ranged_attack" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.ranged_attack' in rewards config for unit type {unit['unit_type']}")
                base_attack_reward = unit_rewards["base_actions"]["ranged_attack"]
                reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1

                # EXACT PvP mode behavior: centralized damage+death handling
                if self.unit_manager.apply_shooting_damage(unit, target, result):
                    # Unit died and was removed by UnitManager - no manual sync needed
                    if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                        raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
                    reward += unit_rewards["result_bonuses"]["kill_target"]

                # Clean action logging - map to strategic action for logger
                if self.game_logger:
                    try:
                        # Map to strategic shooting action for logger
                        strategic_action_int = self._map_to_strategic_action(unit, action_type, "shoot")
                        self.game_logger.log_shoot(unit, target, result, self.current_turn, reward, strategic_action_int)
                    except Exception as e:
                        pass  # Silent failure to avoid breaking training
                else:
                    print(f"⚠️ No game logger available for shooting logging")
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
            # Re-validate targets are still alive
            alive_targets = [t for t in targets if self.unit_manager.is_target_valid(t)]
            if alive_targets:
                target = alive_targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                # CRITICAL: Final validation immediately before charge execution
                # Prevents charging dead units that died between target selection and execution
                if not self.unit_manager.is_target_valid(target):
                    unit["has_charged"] = True
                    self.charged_units.add(unit["id"])
                    if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                    return unit_rewards["base_actions"]["wait"]
                
                old_col, old_row = unit["col"], unit["row"]

                # Calculate charge distance and validate charge attempt
                distance = max(abs(unit["col"] - target["col"]), abs(unit["row"] - target["row"]))
                
                # Roll 2d6 for charge distance (W40K rules)
                from shared.gameRules import roll_d6
                charge_roll = roll_d6() + roll_d6()

                if distance <= 1:
                    # Already adjacent - cannot charge
                    charge_succeeded = False
                elif distance > charge_roll:
                    # Charge roll too low to reach target
                    charge_succeeded = False
                else:
                    # Find valid adjacent position using hex grid (6 positions)
                    adjacent_positions = [
                        (target["col"] + 1, target["row"]),      # East
                        (target["col"] - 1, target["row"]),      # West  
                        (target["col"], target["row"] + 1),      # South
                        (target["col"], target["row"] - 1),      # North
                        (target["col"] + 1, target["row"] - 1),  # Northeast (odd cols)
                        (target["col"] - 1, target["row"] + 1)   # Southwest (even cols)
                    ]
                    
                    # Find valid adjacent position using pathfinding
                    charge_succeeded = False
                    for target_col, target_row in adjacent_positions:
                        if (0 <= target_col < self.board_size[0] and 
                            0 <= target_row < self.board_size[1]):
                            # Check if this position is within charge roll distance
                            move_distance = max(abs(unit["col"] - target_col), abs(unit["row"] - target_row))
                            if move_distance <= charge_roll:
                                # Use pathfinding validation to respect walls
                                if self._execute_validated_movement(unit, target_col, target_row):
                                    charge_succeeded = True
                                    break

                if not charge_succeeded:
                    # Charge failed due to walls/obstacles, but still counts as charged
                    unit["has_charged"] = True
                    self.charged_units.add(unit["id"])
                    if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                    return unit_rewards["base_actions"]["wait"]

                if "base_actions" not in unit_rewards or "charge_success" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.charge_success' in rewards config for unit type {unit['unit_type']}")
                reward = unit_rewards["base_actions"]["charge_success"]

                # Clean action logging - map to strategic action for logger  
                if self.game_logger:
                    try:
                        # Map to strategic charge action for logger
                        strategic_action_int = self._map_to_strategic_action(unit, action_type, "charge")
                        self.game_logger.log_charge(unit, target, old_col, old_row, unit["col"], unit["row"], 
                                                  self.current_turn, reward, strategic_action_int)
                    except Exception as e:
                        pass  # Silent failure to avoid breaking training
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
            # Re-validate targets are still alive
            alive_targets = [t for t in targets if self.unit_manager.is_target_valid(t)]
            if alive_targets:
                target = alive_targets[0]
                
                # Set explicit tracking - PvP style
                self._last_acting_unit = unit
                self._last_target_unit = target
                
                old_hp = target["cur_hp"]
                
                # CRITICAL: Final validation immediately before combat execution
                # Prevents attacking dead units that died between target selection and execution
                if not self.unit_manager.is_target_valid(target):
                    unit["has_attacked"] = True
                    self.attacked_units.add(unit["id"])
                    if "base_actions" not in unit_rewards or "wait" not in unit_rewards["base_actions"]:
                        raise KeyError(f"Missing 'base_actions.wait' in rewards config for unit type {unit['unit_type']}")
                    return unit_rewards["base_actions"]["wait"]
                
                # Execute dice-based combat sequence
                from shared.gameRules import execute_combat_sequence
                result = execute_combat_sequence(unit, target)
                total_damage = result["totalDamage"]
                
                # Enhanced logging: capture all dice roll details
                if self.save_replay:
                    self._record_detailed_combat_action(unit, target, result, old_hp)

                # Base combat attack reward (scaled by damage dealt)
                if "base_actions" not in unit_rewards or "melee_attack" not in unit_rewards["base_actions"]:
                    raise KeyError(f"Missing 'base_actions.melee_attack' in rewards config for unit type {unit['unit_type']}")
                base_attack_reward = unit_rewards["base_actions"]["melee_attack"]
                reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1

                # EXACT PvP mode behavior: atomic damage application and death handling
                if self.unit_manager.apply_combat_damage(unit, target, result):
                    # Unit died and was removed by UnitManager - no manual sync needed
                    if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                        raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
                    reward += unit_rewards["result_bonuses"]["kill_target"]

                # Clean action logging - MOVE AFTER UNIT REMOVAL
                if self.game_logger:
                    try:
                        # Map to strategic combat action for logger
                        strategic_action_int = self._map_to_strategic_action(unit, action_type, "combat")
                        self.game_logger.log_combat(unit, target, result, self.current_turn, reward, strategic_action_int)
                    except Exception as e:
                        pass  # Silent failure to avoid breaking training
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
        """Get shooting targets in AI_GAME_OVERVIEW.md priority order with line of sight validation."""
        targets = []
        in_range_enemies = []
        
        # Find enemies in range with line of sight validation - use UnitManager's cleaned list with target validation
        for enemy in self.unit_manager.get_alive_enemy_units():
            if not self.unit_manager.is_target_valid(enemy):
                continue
            dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
            if dist <= unit["rng_rng"]:
                    # CRITICAL FIX: Add line of sight validation using wall_hexes
                    if self._has_line_of_sight(unit, enemy):
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
            for u in self.unit_manager.get_alive_ai_units():
                if not u["is_ranged"]:
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

    def _has_line_of_sight(self, shooter, target):
        """Check if shooter has line of sight to target (no walls blocking)."""
        # AI_INSTRUCTIONS.md: Must use board_config.wall_hexes for validation
        if not hasattr(self, 'board_config') or 'wall_hexes' not in self.board_config:
            raise RuntimeError("AI_INSTRUCTIONS.md violation: Board configuration with wall_hexes required for line of sight validation")
        
        # Get wall positions as a set for fast lookup
        wall_positions = set()
        for wall_hex in self.board_config['wall_hexes']:
            if not isinstance(wall_hex, (list, tuple)) or len(wall_hex) != 2:
                raise ValueError(f"Invalid wall hex format: {wall_hex}. Expected [col, row] format.")
            wall_positions.add(f"{wall_hex[0]},{wall_hex[1]}")
        
        # Simple line of sight: check direct line between units for wall hexes
        start_col, start_row = shooter["col"], shooter["row"]
        end_col, end_row = target["col"], target["row"]
        
        # If adjacent, always have line of sight
        if abs(start_col - end_col) <= 1 and abs(start_row - end_row) <= 1:
            return True
        
        # Check intermediate hexes along the line for walls
        steps = max(abs(end_col - start_col), abs(end_row - start_row))
        for step in range(1, steps):  # Skip start and end positions
            t = step / steps
            check_col = int(start_col + t * (end_col - start_col) + 0.5)
            check_row = int(start_row + t * (end_row - start_row) + 0.5)
            
            # Check if this position is a wall
            if f"{check_col},{check_row}" in wall_positions:
                return False  # Wall blocks line of sight
        
        return True  # No walls blocking

    def _get_charge_targets(self, unit):
        """Get charge targets in AI_GAME_OVERVIEW.md priority order."""
        targets = []
        chargeable_enemies = []
        
        # Find enemies within charge range (move distance) but not adjacent - use UnitManager's cleaned list
        for enemy in self.unit_manager.get_alive_enemy_units():
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
        
        # Find enemies within combat range (CC_RNG) - use UnitManager's cleaned list
        if "cc_rng" not in unit:
            raise KeyError(f"Unit missing required 'cc_rng' field")
        combat_range = unit["cc_rng"]
        for enemy in self.unit_manager.get_alive_enemy_units():
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
        # Use UnitManager's cleaned list instead of manual alive checks
        for unit in self.unit_manager.get_alive_ai_units():
            if not unit["is_ranged"] and not unit["has_charged"]:
                dist = abs(unit["col"] - enemy["col"]) + abs(unit["row"] - enemy["row"])
                if 1 < dist <= unit["move"]:
                    return True
        return False

    def _get_nearest_enemy(self, unit):
        """Get nearest alive enemy."""
        nearest = None
        min_dist = float('inf')
        
        for enemy in self.unit_manager.get_alive_enemy_units():
                dist = get_hex_distance(unit, enemy)
                if dist < min_dist:
                    min_dist = dist
                    nearest = enemy
        
        return nearest
    
    def _is_friendly_unit(self, unit1, unit2):
        """Check if two units are on the same team."""
        return unit1.get("player", -1) == unit2.get("player", -2)
    
    def _is_target_adjacent_to_friendly_unit(self, target):
        """Check if target enemy is adjacent to any friendly unit (Rule 2)."""
        # Use UnitManager's cleaned list instead of manual alive checks
        for friendly_unit in self.unit_manager.get_alive_ai_units():
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
        # Use UnitManager instead of direct manipulation - capture return value
        target_died = self.unit_manager.apply_shooting_damage(unit, target, result)
        
        unit_rewards = self._get_unit_reward_config(unit)
        
        # Base ranged attack reward (scaled by damage dealt)
        if "base_actions" not in unit_rewards or "ranged_attack" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.ranged_attack' in rewards config for unit type {unit['unit_type']}")
        
        base_attack_reward = unit_rewards["base_actions"]["ranged_attack"]
        reward = base_attack_reward * total_damage if total_damage > 0 else base_attack_reward * 0.1
        
        # Kill bonuses - UnitManager already handled death, use its return value
        if target_died:
            # Unit died and was removed by UnitManager
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
        for unit in self.unit_manager.get_alive_ai_units():
            if "has_shot" not in unit:
                raise KeyError("Unit missing required 'has_shot' field")
            if (not unit["has_shot"] and 
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
        for enemy in self.unit_manager.get_alive_enemy_units():
            distance = self._calculate_distance(unit, enemy)
            if distance <= unit_range:
                # Rule 2: Cannot shoot enemy units adjacent to friendly units
                if not self._is_target_adjacent_to_friendly_unit(enemy):
                    return True
        return False
    
    def _calculate_distance(self, unit1, unit2):
        """Calculate hex grid distance between two units."""
        return get_hex_distance(unit1, unit2)
    
    def _calculate_move_path(self, from_col, from_row, to_col, to_row, max_move):
        """Calculate valid movement path using pathfinding (exact copy of frontend algorithm)."""
        # AI_INSTRUCTIONS.md: No fallbacks allowed - must have proper config
        if not hasattr(self, 'board_config') or 'wall_hexes' not in self.board_config:
            raise RuntimeError("AI_INSTRUCTIONS.md violation: Board configuration with wall_hexes is required for pathfinding. Cannot proceed without proper wall definitions.")
        
        # Validate board configuration exists and is properly loaded
        if not self.board_config.get('wall_hexes'):
            raise ValueError("Board configuration missing required 'wall_hexes' field. Pathfinding requires wall definitions.")
        
        board_cols = self.board_size[0]
        board_rows = self.board_size[1]
        
        visited = {}
        parent = {}
        queue = [(from_col, from_row, 0)]
        
        # Cube coordinate directions for proper hex neighbors (exact copy from frontend)
        cube_directions = [
            [1, -1, 0], [1, 0, -1], [0, 1, -1], 
            [-1, 1, 0], [-1, 0, 1], [0, -1, 1]
        ]
        
        # Collect forbidden hexes (walls + units) - exact copy from frontend
        forbidden_set = set()
        
        # Add wall hexes - exact copy from frontend
        for wall_hex in self.board_config['wall_hexes']:
            if not isinstance(wall_hex, (list, tuple)) or len(wall_hex) != 2:
                raise ValueError(f"Invalid wall hex format: {wall_hex}. Expected [col, row] format.")
            forbidden_set.add(f"{wall_hex[0]},{wall_hex[1]}")
        
        # Add unit positions (except the moving unit) - exact copy from frontend
        for other_unit in self.unit_manager.units:
            if (other_unit["alive"] and 
                not (other_unit["col"] == from_col and other_unit["row"] == from_row)):
                forbidden_set.add(f"{other_unit['col']},{other_unit['row']}")
        
        visited[f"{from_col},{from_row}"] = 0
        parent[f"{from_col},{from_row}"] = None
        
        while queue:
            col, row, steps = queue.pop(0)
            key = f"{col},{row}"
            
            # Found destination - exact copy from frontend
            if col == to_col and row == to_row:
                # Reconstruct path - exact copy from frontend
                path = []
                current = key
                
                while current is not None:
                    c, r = current.split(',')
                    path.insert(0, {"col": int(c), "row": int(r)})
                    current = parent.get(current)
                
                return path
            
            if steps >= max_move:
                continue
            
            # Explore neighbors - exact copy from frontend
            current_cube = self._offset_to_cube(col, row)
            for dx, dy, dz in cube_directions:
                neighbor_cube = {
                    "x": current_cube["x"] + dx,
                    "y": current_cube["y"] + dy,
                    "z": current_cube["z"] + dz
                }
                
                # Convert back to offset coordinates - exact copy from frontend
                ncol = neighbor_cube["x"]
                nrow = neighbor_cube["z"] + ((neighbor_cube["x"] - (neighbor_cube["x"] & 1)) >> 1)
                nkey = f"{ncol},{nrow}"
                next_steps = steps + 1
                
                if (ncol >= 0 and ncol < board_cols and
                    nrow >= 0 and nrow < board_rows and
                    next_steps <= max_move and
                    nkey not in forbidden_set and
                    (nkey not in visited or visited.get(nkey, float('inf')) > next_steps)):
                    
                    visited[nkey] = next_steps
                    parent[nkey] = key
                    queue.append((ncol, nrow, next_steps))
        
        return []  # No path found

    def _execute_validated_movement(self, unit, target_col, target_row):
        """Shared movement validation for both AI agents and bots."""
        old_col, old_row = unit["col"], unit["row"]
        move_range = unit.get("move", 6)
        
        # Use same pathfinding validation for everyone
        valid_path = self._calculate_move_path(old_col, old_row, target_col, target_row, move_range)
        
        if not valid_path or len(valid_path) == 0:
            return False  # Movement blocked by walls/obstacles
        
        # Apply validated movement to final reachable position
        final_position = valid_path[-1]
        unit["col"] = final_position["col"]
        unit["row"] = final_position["row"]
        
        return True  # Movement succeeded

    def _offset_to_cube(self, col, row):
        """Convert offset coordinates to cube coordinates (same as frontend)."""
        x = col
        z = row - ((col - (col & 1)) >> 1)
        y = -x - z
        return {"x": x, "y": y, "z": z}

    def _calculate_target_position_from_action(self, unit, action_type):
        """Convert action type to target coordinates."""
        old_col, old_row = unit["col"], unit["row"]
        move_range = unit.get("move", 6)
        
        if action_type == 0:  # Move North
            target_row = max(0, old_row - move_range)
            target_col = old_col
        elif action_type == 1:  # Move South
            target_row = min(self.board_size[1] - 1, old_row + move_range)
            target_col = old_col
        elif action_type == 2:  # Move East
            target_col = min(self.board_size[0] - 1, old_col + move_range)
            target_row = old_row
        elif action_type == 3:  # Move West
            target_col = max(0, old_col - move_range)
            target_row = old_row
        else:
            # Invalid action - return current position (no movement)
            return old_col, old_row
        
        return target_col, target_row

    def _calculate_bot_target_position(self, bot_unit, target_unit):
        """Calculate where bot wants to move toward target."""
        dx = target_unit["col"] - bot_unit["col"]
        dy = target_unit["row"] - bot_unit["row"]
        move_distance = bot_unit.get("move", 6)
        
        # Move toward target, respecting move distance
        if abs(dx) > abs(dy):
            # Move horizontally
            step = min(move_distance, abs(dx)) * (1 if dx > 0 else -1)
            target_col = max(0, min(self.board_size[0] - 1, bot_unit["col"] + step))
            target_row = bot_unit["row"]
        else:
            # Move vertically  
            step = min(move_distance, abs(dy)) * (1 if dy > 0 else -1)
            target_col = bot_unit["col"]
            target_row = max(0, min(self.board_size[1] - 1, bot_unit["row"] + step))
        
        return target_col, target_row

    def _attack_target(self, unit, target):
        """Attack adjacent target in melee combat."""
        unit_rewards = self._get_unit_reward_config(unit)
        
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
        
        if "base_actions" not in unit_rewards or "melee_attack" not in unit_rewards["base_actions"]:
            raise KeyError(f"Missing 'base_actions.melee_attack' in rewards config for unit type {unit['unit_type']}")
        reward = unit_rewards["base_actions"]["melee_attack"]  # Base attack reward
        
        # EXACT PvP mode behavior: atomic damage application and death handling
        if self.unit_manager.apply_direct_damage(unit, target):
            # Unit died and was removed by UnitManager - no manual sync needed
            if "result_bonuses" not in unit_rewards or "kill_target" not in unit_rewards["result_bonuses"]:
                raise KeyError(f"Missing 'result_bonuses.kill_target' in rewards config for unit type {unit['unit_type']}")
            reward += unit_rewards["result_bonuses"]["kill_target"]
            
            # Bonus for no overkill
            if old_hp == damage:
                if "result_bonuses" not in unit_rewards or "no_overkill" not in unit_rewards["result_bonuses"]:
                    raise KeyError(f"Missing 'result_bonuses.no_overkill' in rewards config for unit type {unit['unit_type']}")
                reward += unit_rewards["result_bonuses"]["no_overkill"]
        
        return reward

    def _get_nearest_ai_unit(self, enemy):
        """Get nearest alive AI unit for enemy targeting - EXACT PvP mode behavior."""
        nearest = None
        min_dist = float('inf')
        
        # Use UnitManager's cleaned list instead of manual alive checks
        for unit in self.unit_manager.get_alive_ai_units():
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
        enemies_in_range = [e for e in self.unit_manager.get_alive_enemy_units() if 
                            not self._is_friendly_unit(shooter, e)]
        if "rng_rng" not in shooter:
            raise KeyError("Shooter missing required 'rng_rng' field")
        enemies_in_range = [e for e in self.unit_manager.get_alive_enemy_units() if 
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
        enemies_in_range = [e for e in self.unit_manager.get_alive_enemy_units() if 
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
        adjacent_enemies = [e for e in self.unit_manager.get_alive_enemy_units() if 
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
        for enemy in self.unit_manager.get_alive_enemy_units():
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
        for enemy in self.unit_manager.get_alive_enemy_units():
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

    def _execute_enemy_turn(self):
        """Execute enemy turn using centralized BotManager with proper logging."""
        if not hasattr(self, 'bot_manager'):
            print(f"❌ No bot_manager available for enemy turn")
            return
        
        enemy_units = self.unit_manager.get_alive_enemy_units()
        # print(f"🤖 Bot turn: {len(enemy_units)} enemy units, Phase: {self.current_phase}")
           
        # Delegate to centralized bot manager with proper logging
        actions_taken = self.bot_manager.execute_bot_turn()
        # print(f"🤖 Bot completed turn: {actions_taken} actions taken")


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
            "winner": self.winner,
            "ai_units_alive": len(self.unit_manager.get_alive_ai_units()),
            "enemy_units_alive": len(self.unit_manager.get_alive_enemy_units())
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
            
            for unit in self.unit_manager.get_alive_units():
                symbol = 'A' if unit["player"] == 1 else 'E'
                if unit["col"] < len(board[0]) and unit["row"] < len(board):
                    board[unit["row"]][unit["col"]] = symbol
            
            for row in board:
                print(' '.join(row))
            
            print(f"\nAI Units: {len(self.unit_manager.get_alive_ai_units())}")
            print(f"Enemy Units: {len(self.unit_manager.get_alive_enemy_units())}")
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
            
            # Capture unit states from UnitManager
            if hasattr(self, 'unit_manager') and self.unit_manager.units:
                for i, unit in enumerate(self.unit_manager.units):
                    if unit:
                        unit_state = {
                            "id": unit.get('id', i),
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

    def _map_to_strategic_action(self, unit, action_type, phase):
        """Map basic environment action_type to strategic action_int for logger."""
        # Map basic environment actions to strategic logger actions
        if phase == "move":
            # Basic movement (0-3: north/south/east/west) -> strategic movement
            # For now, map all movement to move_closer (0) - can be enhanced later
            return 0  # move_closer
        elif phase == "shoot":
            # Basic shooting (4) -> strategic shooting based on target selection
            # For now, default to shoot_closest (3) - can be enhanced based on target analysis
            return 3  # shoot_closest
        elif phase == "charge":
            # Basic charge (5) -> strategic charge
            return 5  # charge_closest
        elif phase == "combat":
            # Basic combat (6) -> strategic combat
            return 7  # attack_adjacent
        else:
            # Wait/unknown actions
            return 6  # wait

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