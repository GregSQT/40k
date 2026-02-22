#!/usr/bin/env python3
"""
services/api_server.py - HTTP API Server for W40K Engine
Connects AI_TURN.md compliant engine to frontend board visualization
"""

import json
import os
import sqlite3
import sys
import time
import hashlib
import secrets
import copy
from typing import Dict, Any, Optional, Tuple
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# Add parent directory (project root) to path
parent_dir = os.path.join(os.path.dirname(__file__), '..')
abs_parent = os.path.abspath(parent_dir)
sys.path.insert(0, abs_parent)

# Add engine subdirectory to path
engine_dir = os.path.join(abs_parent, 'engine')
sys.path.insert(0, engine_dir)

from engine.w40k_core import W40KEngine
from main import load_config
from shared.data_validation import require_key
from engine.combat_utils import resolve_dice_value
from engine.phase_handlers.shared_utils import build_units_cache

AUTH_DB_PATH = os.path.join(abs_parent, "config", "users.db")
PBKDF2_ITERATIONS = 200000


def make_json_serializable(obj):
    """Recursively convert non-JSON-serializable types to serializable ones."""
    # Handle ParsedWeaponRule objects
    try:
        from engine.weapons.rules import ParsedWeaponRule
        if isinstance(obj, ParsedWeaponRule):
            if obj.parameter is not None:
                return f"{obj.rule}:{obj.parameter}"
            return obj.rule
    except ImportError:
        pass
    
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Convert tuple keys to strings
            if isinstance(k, tuple):
                k = ",".join(str(x) for x in k)
            result[k] = make_json_serializable(v)
        return result
    elif isinstance(obj, (list, tuple)):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, set):
        return [make_json_serializable(item) for item in obj]
    elif hasattr(obj, '__dict__'):
        # Handle objects with __dict__ (convert to dict)
        return make_json_serializable(obj.__dict__)
    else:
        return obj

def _sync_units_hp_from_cache(serializable_state: Dict[str, Any], game_state: Dict[str, Any]) -> None:
    """
    Ensure HP_CUR in serialized units reflects units_cache (single source of truth).
    
    Dead units are absent from units_cache and must appear with HP_CUR=0 in the response.
    """
    units_cache = require_key(game_state, "units_cache")
    units = require_key(serializable_state, "units")
    
    for unit in units:
        unit_id = str(require_key(unit, "id"))
        cache_entry = units_cache.get(unit_id)
        if cache_entry is None:
            unit["HP_CUR"] = 0
            continue
        unit["HP_CUR"] = require_key(cache_entry, "HP_CUR")


def _build_player_types(is_ai_enabled: bool) -> Dict[str, str]:
    """
    Build player type mapping for frontend orchestration.

    Player 1 is always human in current game modes.
    Player 2 is AI only for AI-enabled modes.
    """
    return {
        "1": "human",
        "2": "ai" if is_ai_enabled else "human",
    }


def _attach_player_types(serializable_state: Dict[str, Any], engine_instance: W40KEngine) -> None:
    """
    Ensure player_types is present in both engine.game_state and serialized response.
    """
    is_pve_mode = bool(getattr(engine_instance, "is_pve_mode", False))
    is_test_mode = bool(getattr(engine_instance, "is_test_mode", False))
    is_debug_mode = bool(getattr(engine_instance, "is_debug_mode", False))
    player_types = _build_player_types(is_pve_mode or is_test_mode or is_debug_mode)
    engine_instance.game_state["player_types"] = player_types
    serializable_state["player_types"] = player_types


def _get_auth_db_connection() -> sqlite3.Connection:
    """
    Return a sqlite connection configured for named column access.
    """
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    connection = sqlite3.connect(AUTH_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _hash_password(password: str) -> str:
    """
    Hash password with PBKDF2-HMAC-SHA256.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password is required and must be a non-empty string")
    salt = secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${derived_key.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify password against PBKDF2 hash format.
    """
    if not isinstance(password, str) or not password:
        return False
    if not isinstance(stored_hash, str) or not stored_hash:
        raise ValueError("stored_hash must be a non-empty string")

    parts = stored_hash.split("$")
    if len(parts) != 4:
        raise ValueError("Invalid password hash format in database")
    algorithm, iterations_str, salt_hex, hash_hex = parts
    if algorithm != "pbkdf2_sha256":
        raise ValueError(f"Unsupported password hash algorithm: {algorithm}")
    iterations = int(iterations_str)
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(candidate, expected)


def _extract_bearer_token() -> str:
    """
    Extract Bearer token from Authorization header.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise ValueError("Missing Authorization header")
    parts = auth_header.strip().split(" ")
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        raise ValueError("Invalid Authorization header format. Expected: Bearer <token>")
    return parts[1]


def _resolve_permissions_for_profile(connection: sqlite3.Connection, profile_id: int) -> Dict[str, Any]:
    """
    Resolve allowed game modes and options for a profile.
    """
    modes_rows = connection.execute(
        """
        SELECT gm.code
        FROM profile_game_modes pgm
        JOIN game_modes gm ON gm.id = pgm.game_mode_id
        WHERE pgm.profile_id = ?
        ORDER BY gm.code
        """,
        (profile_id,),
    ).fetchall()
    option_rows = connection.execute(
        """
        SELECT o.code, po.enabled
        FROM profile_options po
        JOIN options o ON o.id = po.option_id
        WHERE po.profile_id = ?
        ORDER BY o.code
        """,
        (profile_id,),
    ).fetchall()

    options_map: Dict[str, bool] = {}
    for row in option_rows:
        option_code = row["code"]
        options_map[option_code] = bool(row["enabled"])

    return {
        "game_modes": [row["code"] for row in modes_rows],
        "options": options_map,
    }


def _get_authenticated_user_or_response():
    """
    Validate bearer session token and return current user row.
    """
    try:
        token = _extract_bearer_token()
    except ValueError as auth_error:
        return None, (jsonify({"success": False, "error": str(auth_error)}), 401)

    connection = _get_auth_db_connection()
    try:
        row = connection.execute(
            """
            SELECT u.id AS user_id, u.login AS login, p.id AS profile_id, p.code AS profile_code
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN profiles p ON p.id = u.profile_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None, (jsonify({"success": False, "error": "Invalid or expired session"}), 401)
    return row, None


def _is_mode_allowed(mode: str, permissions: Dict[str, Any]) -> bool:
    """
    Check if requested mode is present in allowed game modes.
    """
    allowed_modes = require_key(permissions, "game_modes")
    if not isinstance(allowed_modes, list):
        raise TypeError("permissions.game_modes must be a list")
    if mode in allowed_modes:
        return True
    # Backward compatibility for stale permissions snapshots.
    if mode == "pvp_old" and "pvp" in allowed_modes:
        return True
    if mode == "pve_old" and "pve" in allowed_modes:
        return True
    return False


def initialize_auth_db() -> None:
    """
    Create auth tables and seed default profile permissions.
    """
    connection = _get_auth_db_connection()
    try:
        cursor = connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                profile_id INTEGER NOT NULL REFERENCES profiles(id)
            );

            CREATE TABLE IF NOT EXISTS game_modes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_game_modes (
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                game_mode_id INTEGER NOT NULL REFERENCES game_modes(id) ON DELETE CASCADE,
                UNIQUE(profile_id, game_mode_id)
            );

            CREATE TABLE IF NOT EXISTS profile_options (
                profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                option_id INTEGER NOT NULL REFERENCES options(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL,
                UNIQUE(profile_id, option_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            """
        )

        cursor.execute(
            "INSERT OR IGNORE INTO profiles (code, label) VALUES (?, ?)",
            ("base", "Joueur Base"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profiles (code, label) VALUES (?, ?)",
            ("admin", "Administrateur"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pve", "Player vs Environment"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pve_old", "Player vs Environment (Old)"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pvp", "Player vs Player"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("pvp_old", "Player vs Player (Old)"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("debug", "Debug Mode"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO game_modes (code, label) VALUES (?, ?)",
            ("test", "Test Mode"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO options (code, label) VALUES (?, ?)",
            ("show_advance_warning", "Afficher avertissement mode advance"),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO options (code, label) VALUES (?, ?)",
            ("auto_weapon_selection", "Selection automatique d'arme"),
        )

        profile_row = cursor.execute(
            "SELECT id FROM profiles WHERE code = ?",
            ("base",),
        ).fetchone()
        if profile_row is None:
            raise RuntimeError("Failed to seed required profile 'base'")
        profile_id = profile_row["id"]
        admin_profile_row = cursor.execute(
            "SELECT id FROM profiles WHERE code = ?",
            ("admin",),
        ).fetchone()
        if admin_profile_row is None:
            raise RuntimeError("Failed to seed required profile 'admin'")
        admin_profile_id = admin_profile_row["id"]

        pve_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pve",),
        ).fetchone()
        pve_old_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pve_old",),
        ).fetchone()
        pvp_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pvp",),
        ).fetchone()
        pvp_old_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("pvp_old",),
        ).fetchone()
        if pve_row is None or pve_old_row is None or pvp_row is None or pvp_old_row is None:
            raise RuntimeError("Failed to seed required game modes")
        debug_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("debug",),
        ).fetchone()
        test_row = cursor.execute(
            "SELECT id FROM game_modes WHERE code = ?",
            ("test",),
        ).fetchone()
        if debug_row is None or test_row is None:
            raise RuntimeError("Failed to seed required admin game modes")

        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pve_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pve_old_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pvp_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (profile_id, pvp_old_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pve_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pve_old_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pvp_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, pvp_old_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, debug_row["id"]),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO profile_game_modes (profile_id, game_mode_id) VALUES (?, ?)",
            (admin_profile_id, test_row["id"]),
        )

        warning_option_row = cursor.execute(
            "SELECT id FROM options WHERE code = ?",
            ("show_advance_warning",),
        ).fetchone()
        auto_weapon_row = cursor.execute(
            "SELECT id FROM options WHERE code = ?",
            ("auto_weapon_selection",),
        ).fetchone()
        if warning_option_row is None or auto_weapon_row is None:
            raise RuntimeError("Failed to seed required option definitions")

        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (profile_id, warning_option_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (profile_id, auto_weapon_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (admin_profile_id, warning_option_row["id"]),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO profile_options (profile_id, option_id, enabled)
            VALUES (?, ?, 1)
            """,
            (admin_profile_id, auto_weapon_row["id"]),
        )

        connection.commit()
    finally:
        connection.close()

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

# Minimal Flask logging for debugging when needed
flask_request_logs = []

initialize_auth_db()

# Global engine instance
engine: Optional[W40KEngine] = None

def get_agents_from_scenario(scenario_file: str, unit_registry) -> set:
    """Extract unique agent keys from scenario units.
    
    Args:
        scenario_file: Path to scenario.json
        unit_registry: UnitRegistry instance for unit_type -> agent_key mapping
        
    Returns:
        Set of unique agent keys found in scenario
        
    Raises:
        FileNotFoundError: If scenario file doesn't exist
        ValueError: If scenario format invalid or unit type not found in registry
    """
    import json
    
    if not os.path.exists(scenario_file):
        raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
    
    try:
        with open(scenario_file, 'r') as f:
            scenario_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in scenario file: {e}")
    
    if not isinstance(scenario_data, dict) or "units" not in scenario_data:
        raise ValueError(f"Invalid scenario format: must have 'units' array")
    
    units = scenario_data["units"]
    if not units:
        raise ValueError("Scenario contains no units")
    
    agent_keys = set()
    for unit in units:
        if "unit_type" not in unit:
            raise ValueError(f"Unit missing 'unit_type' field: {unit}")
        
        unit_type = unit["unit_type"]
        try:
            agent_key = unit_registry.get_model_key(unit_type)
            agent_keys.add(agent_key)
        except ValueError as e:
            raise ValueError(
                f"Failed to determine agent for unit type '{unit_type}': {e}\n"
                f"Ensure unit is defined in frontend/src/roster/ with proper agent properties"
            )
    
    return agent_keys

def initialize_engine():
    """Initialize the W40K engine with configuration."""
    global engine
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Define scenario file path for game/API mode
        scenario_file = os.path.join("config", "scenario_game.json")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"Game scenario file not found: {scenario_file}\n"
                f"This file is required for the API server.\n"
                f"Training scenarios are in config/agents/<agent>/scenarios/"
            )

        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        # Load agent-specific configs based on scenario units
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()
        game_config = config_loader.get_game_config()
        
        from engine.game_state import GameStateManager
        scenario_manager = GameStateManager({"board": {}}, unit_registry)
        scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
        scenario_units = require_key(scenario_result, "units")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_primary_objective_id = scenario_result.get("primary_objective")
        scenario_wall_hexes = scenario_result.get("wall_hexes")
        scenario_objectives = scenario_result.get("objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        
        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None
        
        config = {
            "board": board_config,
            "game_rules": require_key(game_config, "game_rules"),
            "units": scenario_units,
            "primary_objective": primary_objective_config,
            "scenario_wall_hexes": scenario_wall_hexes,
            "scenario_objectives": scenario_objectives,
            "deployment_type": scenario_deployment_type,
            "deployment_type_by_player": scenario_deployment_type_by_player,
            "deployment_zone": scenario_deployment_zone,
            "deployment_pools": scenario_deployment_pools
        }
        
        # Determine which agents are in the scenario
        agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
        if not agent_keys:
            raise ValueError("No agents found in scenario")
        
        print(f"DEBUG: Found {len(agent_keys)} unique agent(s) in scenario: {agent_keys}")
        
        # For PvP mode, we need configs for all agents
        # Load configs for each agent and merge them
        all_rewards_configs = {}
        all_training_configs = {}
        
        for agent_key in agent_keys:
            try:
                agent_rewards = config_loader.load_agent_rewards_config(agent_key)
                # Load entire config file (contains "default" and "debug" phases)
                agent_training_full = config_loader.load_agent_training_config(agent_key)
                # Load "default" phase for observation params
                agent_training_default = config_loader.load_agent_training_config(agent_key, "default")
                
                # Store agent-specific configs
                all_rewards_configs[agent_key] = agent_rewards
                all_training_configs[agent_key] = agent_training_full  # Store full config for engine
                
                print(f"✅ Loaded configs for agent: {agent_key}")
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"Missing config for agent '{agent_key}' found in scenario.\n{e}\n"
                    f"Create required files:\n"
                    f"  - config/agents/{agent_key}/{agent_key}_rewards_config.json\n"
                    f"  - config/agents/{agent_key}/{agent_key}_training_config.json"
                )
        
        # Use first agent's training config for observation params (all agents should match)
        first_agent = list(agent_keys)[0]
        training_config_default = config_loader.load_agent_training_config(first_agent, "default")
        
        # Add configs to main config
        config["rewards_configs"] = all_rewards_configs  # Multi-agent support
        config["training_configs"] = all_training_configs  # Multi-agent support
        config["agent_keys"] = list(agent_keys)  # Track which agents are active
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        
        # CRITICAL FIX: Add observation_params from training_config "default" phase
        obs_params = training_config_default.get("observation_params", {})
        
        # Validation stricte: obs_size DOIT être présent
        if "obs_size" not in obs_params:
            raise KeyError(
                f"training_config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json 'default' phase. "
                f"Config: {first_agent}"
            )
        
        config["observation_params"] = obs_params  # Inclut obs_size validé
        
        # Create engine with proper parameters
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="default",
            controlled_agent=first_agent,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True
        )
        
        # CRITICAL FIX: Add rewards_configs to game_state after engine creation
        engine.game_state["rewards_configs"] = all_rewards_configs
        engine.game_state["agent_keys"] = list(agent_keys)
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvP mode)")
        return True
    except Exception as e:
        # Restore original working directory on error
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        print(f"❌ Failed to initialize engine: {e}")
        print(f"❌ Exception type: {type(e).__name__}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return False

def initialize_pve_engine(scenario_file: str = None, debug_mode: bool = False):
    """Initialize the W40K engine for PvE mode with AI Player 2."""
    global engine
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Define scenario file path for game/API mode (default if not provided)
        if scenario_file is None:
            scenario_file = os.path.join("config", "scenario_game.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"Game scenario file not found: {scenario_file}\n"
                f"This file is required for the API server.\n"
                f"Training scenarios are in config/agents/<agent>/scenarios/"
            )

        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()
        game_config = config_loader.get_game_config()
        
        from engine.game_state import GameStateManager
        scenario_manager = GameStateManager({"board": {}}, unit_registry)
        scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
        scenario_units = require_key(scenario_result, "units")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_primary_objective_id = scenario_result.get("primary_objective")
        scenario_wall_hexes = scenario_result.get("wall_hexes")
        scenario_objectives = scenario_result.get("objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        
        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None
        
        config = {
            "board": board_config,
            "game_rules": require_key(game_config, "game_rules"),
            "units": scenario_units,
            "primary_objective": primary_objective_config,
            "scenario_wall_hexes": scenario_wall_hexes,
            "scenario_objectives": scenario_objectives,
            "deployment_type": scenario_deployment_type,
            "deployment_type_by_player": scenario_deployment_type_by_player,
            "deployment_zone": scenario_deployment_zone,
            "deployment_pools": scenario_deployment_pools
        }
        
        # Determine which agents are in the scenario
        agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
        if not agent_keys:
            raise ValueError("No agents found in scenario")
        
        print(f"DEBUG: Found {len(agent_keys)} unique agent(s) in scenario: {agent_keys}")
        
        # For PvE mode, load configs for all agents
        all_rewards_configs = {}
        all_training_configs = {}
        
        for agent_key in agent_keys:
            try:
                agent_rewards = config_loader.load_agent_rewards_config(agent_key)
                # Load entire config file (contains "default" and "debug" phases)
                agent_training_full = config_loader.load_agent_training_config(agent_key)
                
                # Store agent-specific configs
                all_rewards_configs[agent_key] = agent_rewards
                all_training_configs[agent_key] = agent_training_full  # Store full config for engine
                
                print(f"✅ Loaded configs for agent: {agent_key}")
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"Missing config for agent '{agent_key}' found in scenario.\n{e}\n"
                    f"Create required files:\n"
                    f"  - config/agents/{agent_key}/{agent_key}_rewards_config.json\n"
                    f"  - config/agents/{agent_key}/{agent_key}_training_config.json"
                )
        
        # Use first agent's training config for observation params
        first_agent = list(agent_keys)[0]
        training_config_default = config_loader.load_agent_training_config(first_agent, "default")
        
        # Create engine with PvE configuration - set pve_mode in config
        config["pve_mode"] = True
        config["rewards_configs"] = all_rewards_configs  # Multi-agent support
        config["training_configs"] = all_training_configs  # Multi-agent support
        config["agent_keys"] = list(agent_keys)  # Track which agents are active
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        
        # CRITICAL FIX: Add observation_params from training_config "default" phase
        obs_params = training_config_default.get("observation_params", {})
        
        # Validation stricte: obs_size DOIT être présent
        if "obs_size" not in obs_params:
            raise KeyError(
                f"training_config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json 'default' phase. "
                f"Config: {first_agent}"
            )
        
        config["observation_params"] = obs_params  # Inclut obs_size validé
        
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="default",
            controlled_agent=first_agent,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            debug_mode=debug_mode
        )
        
        # CRITICAL FIX: Add rewards_configs to game_state after engine creation
        engine.game_state["rewards_configs"] = all_rewards_configs
        engine.game_state["agent_keys"] = list(agent_keys)
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (PvE mode)")
        return True
    except Exception as e:
        # Restore original working directory on error
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        print(f"❌ Failed to initialize PvE engine: {e}")
        print(f"❌ Exception type: {type(e).__name__}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return False

def initialize_test_engine(scenario_file: str = None, debug_mode: bool = False):
    """Initialize the W40K engine for Test mode (isolated from PvE)."""
    global engine
    try:
        # Change to project root directory for config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        # Define scenario file path for test mode (default if not provided)
        if scenario_file is None:
            scenario_file = os.path.join("config", "scenario_test.json")
        elif not isinstance(scenario_file, str):
            raise ValueError(f"scenario_file must be a string if provided (got {type(scenario_file).__name__})")

        # Verify scenario file exists - no fallback
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(
                f"Test scenario file not found: {scenario_file}\n"
                f"This file is required for Test mode.\n"
                f"Create it from config/scenario_pve.json or another scenario."
            )

        # Initialize unit registry
        from ai.unit_registry import UnitRegistry
        unit_registry = UnitRegistry()
        
        from config_loader import get_config_loader
        config_loader = get_config_loader()
        board_config = config_loader.get_board_config()
        game_config = config_loader.get_game_config()
        
        from engine.game_state import GameStateManager
        scenario_manager = GameStateManager({"board": {}}, unit_registry)
        scenario_result = scenario_manager.load_units_from_scenario(scenario_file, unit_registry)
        scenario_units = require_key(scenario_result, "units")
        scenario_primary_objective_ids = scenario_result.get("primary_objectives")
        scenario_primary_objective_id = scenario_result.get("primary_objective")
        scenario_wall_hexes = scenario_result.get("wall_hexes")
        scenario_objectives = scenario_result.get("objectives")
        scenario_deployment_type = scenario_result.get("deployment_type")
        scenario_deployment_type_by_player = scenario_result.get("deployment_type_by_player")
        scenario_deployment_zone = scenario_result.get("deployment_zone")
        scenario_deployment_pools = scenario_result.get("deployment_pools")
        
        if scenario_primary_objective_ids is not None:
            if not isinstance(scenario_primary_objective_ids, list):
                raise TypeError("primary_objectives must be a list of objective IDs")
            if not scenario_primary_objective_ids:
                raise ValueError("primary_objectives list cannot be empty")
            primary_objective_config = [
                config_loader.load_primary_objective_config(obj_id)
                for obj_id in scenario_primary_objective_ids
            ]
        elif scenario_primary_objective_id is not None:
            primary_objective_config = config_loader.load_primary_objective_config(
                scenario_primary_objective_id
            )
        else:
            primary_objective_config = None
        
        config = {
            "board": board_config,
            "game_rules": require_key(game_config, "game_rules"),
            "units": scenario_units,
            "primary_objective": primary_objective_config,
            "scenario_wall_hexes": scenario_wall_hexes,
            "scenario_objectives": scenario_objectives,
            "deployment_type": scenario_deployment_type,
            "deployment_type_by_player": scenario_deployment_type_by_player,
            "deployment_zone": scenario_deployment_zone,
            "deployment_pools": scenario_deployment_pools
        }
        
        # Determine which agents are in the scenario
        agent_keys = get_agents_from_scenario(scenario_file, unit_registry)
        if not agent_keys:
            raise ValueError("No agents found in scenario")
        
        print(f"DEBUG: Found {len(agent_keys)} unique agent(s) in scenario: {agent_keys}")
        
        # For Test mode, load configs for all agents (same agents as PvE)
        all_rewards_configs = {}
        all_training_configs = {}
        
        for agent_key in agent_keys:
            try:
                agent_rewards = config_loader.load_agent_rewards_config(agent_key)
                # Load entire config file (contains "default" and "debug" phases)
                agent_training_full = config_loader.load_agent_training_config(agent_key)
                
                # Store agent-specific configs
                all_rewards_configs[agent_key] = agent_rewards
                all_training_configs[agent_key] = agent_training_full  # Store full config for engine
                
                print(f"✅ Loaded configs for agent: {agent_key}")
            except FileNotFoundError as e:
                raise FileNotFoundError(
                    f"Missing config for agent '{agent_key}' found in scenario.\n{e}\n"
                    f"Create required files:\n"
                    f"  - config/agents/{agent_key}/{agent_key}_rewards_config.json\n"
                    f"  - config/agents/{agent_key}/{agent_key}_training_config.json"
                )
        
        # Use first agent's training config for observation params
        first_agent = list(agent_keys)[0]
        training_config_default = config_loader.load_agent_training_config(first_agent, "default")
        
        # Test mode config: keep PvE behavior, add test_mode flag for isolation
        config["pve_mode"] = True
        config["test_mode"] = True
        config["rewards_configs"] = all_rewards_configs  # Multi-agent support
        config["training_configs"] = all_training_configs  # Multi-agent support
        config["agent_keys"] = list(agent_keys)  # Track which agents are active
        config["controlled_agent"] = first_agent  # Required for reward mapping in handlers
        
        # CRITICAL FIX: Add observation_params from training_config "default" phase
        obs_params = training_config_default.get("observation_params", {})
        
        # Validation stricte: obs_size DOIT être présent
        if "obs_size" not in obs_params:
            raise KeyError(
                f"training_config missing required 'obs_size' in observation_params. "
                f"Must be defined in training_config.json 'default' phase. "
                f"Config: {first_agent}"
            )
        
        config["observation_params"] = obs_params  # Inclut obs_size validé
        
        engine = W40KEngine(
            config=config,
            rewards_config="default",
            training_config_name="default",
            controlled_agent=first_agent,
            active_agents=None,
            scenario_file=scenario_file,
            unit_registry=unit_registry,
            quiet=True,
            debug_mode=debug_mode
        )
        
        # CRITICAL FIX: Add rewards_configs to game_state after engine creation
        engine.game_state["rewards_configs"] = all_rewards_configs
        engine.game_state["agent_keys"] = list(agent_keys)
        engine.is_test_mode = True
        
        # Restore original working directory
        os.chdir(original_cwd)
        
        print("✅ W40K Engine initialized successfully (Test mode)")
        return True
    except Exception as e:
        # Restore original working directory on error
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        print(f"❌ Failed to initialize Test engine: {e}")
        print(f"❌ Exception type: {type(e).__name__}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        return False

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "engine_initialized": engine is not None
    })

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    """Create a user account with base profile."""
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "JSON body is required"}), 400

    login = data.get("login")
    password = data.get("password")
    if not isinstance(login, str) or not login.strip():
        return jsonify({"success": False, "error": "login is required and must be a non-empty string"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"success": False, "error": "password is required and must be a non-empty string"}), 400

    normalized_login = login.strip()
    connection = _get_auth_db_connection()
    try:
        existing_user = connection.execute(
            "SELECT id FROM users WHERE login = ?",
            (normalized_login,),
        ).fetchone()
        if existing_user is not None:
            return jsonify({"success": False, "error": "login already exists"}), 409

        base_profile = connection.execute(
            "SELECT id, code FROM profiles WHERE code = ?",
            ("base",),
        ).fetchone()
        if base_profile is None:
            raise RuntimeError("Profile 'base' is missing from auth database")

        password_hash = _hash_password(password)
        cursor = connection.execute(
            "INSERT INTO users (login, password_hash, profile_id) VALUES (?, ?, ?)",
            (normalized_login, password_hash, base_profile["id"]),
        )
        connection.commit()
        return jsonify(
            {
                "success": True,
                "user_id": cursor.lastrowid,
                "login": normalized_login,
                "profile": base_profile["code"],
            }
        ), 201
    finally:
        connection.close()


@app.route('/api/auth/login', methods=['POST'])
def login_user():
    """Authenticate user and return access token with permissions."""
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "JSON body is required"}), 400

    login = data.get("login")
    password = data.get("password")
    if not isinstance(login, str) or not login.strip():
        return jsonify({"success": False, "error": "login is required and must be a non-empty string"}), 400
    if not isinstance(password, str) or not password:
        return jsonify({"success": False, "error": "password is required and must be a non-empty string"}), 400

    normalized_login = login.strip()
    connection = _get_auth_db_connection()
    try:
        user_row = connection.execute(
            """
            SELECT u.id AS user_id, u.login, u.password_hash, p.id AS profile_id, p.code AS profile_code
            FROM users u
            JOIN profiles p ON p.id = u.profile_id
            WHERE u.login = ?
            """,
            (normalized_login,),
        ).fetchone()
        if user_row is None:
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        if not _verify_password(password, user_row["password_hash"]):
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        access_token = secrets.token_urlsafe(48)
        connection.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (access_token, user_row["user_id"], str(int(time.time()))),
        )
        permissions = _resolve_permissions_for_profile(connection, user_row["profile_id"])
        connection.commit()

        return jsonify(
            {
                "success": True,
                "access_token": access_token,
                "user": {
                    "id": user_row["user_id"],
                    "login": user_row["login"],
                    "profile": user_row["profile_code"],
                },
                "permissions": permissions,
                "default_redirect_mode": "pve",
            }
        )
    finally:
        connection.close()


@app.route('/api/auth/me', methods=['GET'])
def current_user():
    """Return current user session and permissions."""
    user_row, error_response = _get_authenticated_user_or_response()
    if error_response is not None:
        return error_response
    if user_row is None:
        return jsonify({"success": False, "error": "authentication failed"}), 401

    connection = _get_auth_db_connection()
    try:
        permissions = _resolve_permissions_for_profile(connection, user_row["profile_id"])
    finally:
        connection.close()

    return jsonify(
        {
            "success": True,
            "user": {
                "id": user_row["user_id"],
                "login": user_row["login"],
                "profile": user_row["profile_code"],
            },
            "permissions": permissions,
            "default_redirect_mode": "pve",
        }
    )

@app.route('/api/debug/engine-test', methods=['GET'])
def test_engine():
    """Test engine initialization directly."""
    try:
        # Test config loading
        original_cwd = os.getcwd()
        project_root = os.path.join(os.path.dirname(__file__), '..')
        os.chdir(os.path.abspath(project_root))
        
        from main import load_config
        config = load_config()
        
        os.chdir(original_cwd)
        
        return jsonify({
            "success": True,
            "config_loaded": True,
            "units_count": len(config.get("units", [])),
            "board_config": bool(config.get("board"))
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": str(e.__class__.__name__)
        }), 500

@app.route('/api/game/start', methods=['POST'])
def start_game():
    """Start a new game session with optional PvE mode."""
    global engine
    
    try:
        auth_user, auth_error = _get_authenticated_user_or_response()
        if auth_error is not None:
            return auth_error
        if auth_user is None:
            return jsonify({"success": False, "error": "authentication failed"}), 401

        # Check for PvE mode in request
        data = request.get_json() or {}
        if "pve_mode" in data and not isinstance(data["pve_mode"], bool):
            raise ValueError(f"pve_mode must be boolean (got {type(data['pve_mode']).__name__})")
        if "test_mode" in data and not isinstance(data["test_mode"], bool):
            raise ValueError(f"test_mode must be boolean (got {type(data['test_mode']).__name__})")
        if "debug_mode" in data and not isinstance(data["debug_mode"], bool):
            raise ValueError(f"debug_mode must be boolean (got {type(data['debug_mode']).__name__})")
        if "mode_code" in data and data["mode_code"] is not None and not isinstance(data["mode_code"], str):
            raise ValueError(f"mode_code must be string or null (got {type(data['mode_code']).__name__})")
        if "scenario_file" in data and data["scenario_file"] is not None and not isinstance(data["scenario_file"], str):
            raise ValueError(f"scenario_file must be string or null (got {type(data['scenario_file']).__name__})")
        pve_mode = data.get('pve_mode', False)
        test_mode = data.get('test_mode', False)
        debug_mode = data.get('debug_mode', False)
        mode_code = data.get('mode_code', None)
        scenario_file = data.get('scenario_file', None)

        requested_mode = "pvp"
        if test_mode:
            requested_mode = "test"
        elif debug_mode:
            requested_mode = "debug"
        elif mode_code is not None:
            allowed_mode_codes = {"pvp", "pvp_old", "pve", "pve_old"}
            if mode_code not in allowed_mode_codes:
                raise ValueError(f"Unsupported mode_code '{mode_code}'. Allowed values: {sorted(allowed_mode_codes)}")
            requested_mode = mode_code
        elif pve_mode:
            requested_mode = "pve_old"

        connection = _get_auth_db_connection()
        try:
            permissions = _resolve_permissions_for_profile(connection, auth_user["profile_id"])
        finally:
            connection.close()

        if not _is_mode_allowed(requested_mode, permissions):
            return jsonify(
                {
                    "success": False,
                    "error": (
                        f"Mode '{requested_mode}' is not allowed for profile "
                        f"'{auth_user['profile_code']}'"
                    ),
                }
            ), 403
        
        # CRITICAL: Always reinitialize engine based on requested mode to prevent mode contamination
        if test_mode:
            print("DEBUG: Initializing engine for Test mode")
            if not initialize_test_engine(scenario_file=scenario_file, debug_mode=debug_mode):
                return jsonify({"success": False, "error": "Test engine initialization failed"}), 500
        elif requested_mode == "pvp":
            print("DEBUG: Initializing engine for PvP mode (copied from Test mode)")
            if not initialize_test_engine(scenario_file=scenario_file, debug_mode=debug_mode):
                return jsonify({"success": False, "error": "PvP engine initialization failed"}), 500
            # PvP must remain human vs human even if initialization reuses Test flow.
            engine.is_pve_mode = False
            engine.is_test_mode = False
            engine.is_debug_mode = False
        elif requested_mode == "pve":
            print("DEBUG: Initializing engine for PvE mode (copied from Test mode)")
            if not initialize_test_engine(scenario_file=scenario_file, debug_mode=debug_mode):
                return jsonify({"success": False, "error": "PvE engine initialization failed"}), 500
        elif requested_mode == "pve_old":
            print("DEBUG: Initializing engine for PvE mode")
            if not initialize_pve_engine(scenario_file=scenario_file, debug_mode=debug_mode):
                return jsonify({"success": False, "error": "PvE engine initialization failed"}), 500
        else:
            print("DEBUG: Initializing engine for PvP mode")
            if not initialize_engine():
                return jsonify({"success": False, "error": "PvP engine initialization failed"}), 500
            # Ensure PvE mode is explicitly disabled for PvP
            engine.is_pve_mode = False
            engine.is_test_mode = False
            engine.is_debug_mode = False
        engine.current_mode_code = requested_mode
        
        print("DEBUG: About to call engine.reset()")
        # Reset the engine for new game
        try:
            obs, info = engine.reset()
        except Exception as reset_error:
            print(f"CRITICAL ERROR in engine.reset(): {reset_error}")
            print(f"ERROR TYPE: {type(reset_error).__name__}")
            import traceback
            print(f"FULL TRACEBACK:\n{traceback.format_exc()}")
            raise
        print("DEBUG: engine.reset() completed successfully")

        # Convert game state to JSON-serializable format
        serializable_state = make_json_serializable(dict(engine.game_state))
        _sync_units_hp_from_cache(serializable_state, engine.game_state)
        engine.is_debug_mode = debug_mode
        _attach_player_types(serializable_state, engine)

        # Add max_turns from game config
        from config_loader import get_config_loader
        config = get_config_loader()
        serializable_state["max_turns"] = config.get_max_turns()

        # Add mode flags to response
        serializable_state["pve_mode"] = getattr(engine, 'is_pve_mode', False)
        serializable_state["test_mode"] = getattr(engine, 'is_test_mode', False)

        mode_labels = {
            "pvp": "PvP",
            "pvp_old": "PvP Old",
            "pve_old": "PvE Old",
            "pve": "PvE",
            "test": "Test",
            "debug": "Debug",
        }
        mode_label = mode_labels.get(requested_mode)
        if mode_label is None:
            raise ValueError(f"Unsupported requested_mode '{requested_mode}'")
        return jsonify({
            "success": True,
            "game_state": serializable_state,
            "message": f"Game started successfully ({mode_label} mode)"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to start game: {str(e)}"
        }), 500

@app.route('/api/game/action', methods=['POST'])
def execute_action():
    """Execute a semantic action in the game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        # Convert frontend hex click to engine semantic action format
        if "col" in data and "row" in data and "selectedUnitId" in data:
            action = {
                "action": "move",
                "unitId": str(data["selectedUnitId"]),
                "destCol": data["col"],
                "destRow": data["row"]
            }
        else:
            action = data  # Pass through already formatted actions
        
        if not action:
            return jsonify({"success": False, "error": "No action provided"}), 400
        
        # Route ALL actions through engine consistently
        if action.get("action") == "end_phase":
            success, result = _execute_end_phase_action(engine, action)
        elif action.get("action") == "change_roster":
            success, result = _execute_change_roster_action(engine, action)
        else:
            success, result = engine.execute_semantic_action(action)

        # Convert game state to JSON-serializable format
        serializable_state = make_json_serializable(dict(engine.game_state))
        _sync_units_hp_from_cache(serializable_state, engine.game_state)
        _attach_player_types(serializable_state, engine)

        # WEAPON_SELECTION: Copy available_weapons from result to active unit in game_state
        # AI_TURN.md: After advance, _shooting_unit_execution_loop returns available_weapons
        # Use active_shooting_unit from game_state (not shooterId from result which doesn't exist)
        if result and isinstance(result, dict) and "available_weapons" in result:
            active_unit_id = engine.game_state.get("active_shooting_unit")
            if active_unit_id and "units" in serializable_state:
                for unit in serializable_state["units"]:
                    if str(unit.get("id")) == str(active_unit_id):
                        unit["available_weapons"] = result["available_weapons"]
                        break
        # Extract and send detailed action logs to frontend
        action_logs = serializable_state.get("action_logs", [])
        # CRITICAL: Always clear logs after each AI turn to prevent accumulation
        engine.game_state["action_logs"] = []
        serializable_state["action_logs"] = []
        
        return jsonify({
            "success": success,
            "result": result,
            "game_state": serializable_state,
            "action_logs": action_logs,
            "message": "Action executed successfully" if success else "Action failed"
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"🔥 FULL ERROR TRACEBACK:")
        print(error_details)
        return jsonify({
            "success": False,
            "error": f"Action execution failed: {str(e)}",
            "traceback": error_details
        }), 500


def _get_activation_pool_key_for_phase(phase: str) -> str:
    """Return activation pool key for a phase supporting manual end_phase."""
    if phase == "move":
        return "move_activation_pool"
    if phase == "shoot":
        return "shoot_activation_pool"
    if phase == "charge":
        return "charge_activation_pool"
    raise ValueError(f"end_phase is not supported for phase '{phase}'")


def _execute_end_phase_action(engine_instance: W40KEngine, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    End current phase by applying WAIT/SKIP end_activation to all remaining units in pool.
    Only supports move/shoot/charge phases.
    """
    game_state = require_key(engine_instance.__dict__, "game_state")
    current_phase = require_key(game_state, "phase")
    pool_key = _get_activation_pool_key_for_phase(current_phase)
    current_player = require_key(game_state, "current_player")

    if "player" not in action:
        raise KeyError("end_phase action missing required 'player' field")
    requested_player = int(action["player"])
    if int(current_player) != requested_player:
        return False, {
            "error": "wrong_player_end_phase",
            "current_player": int(current_player),
            "requested_player": requested_player,
            "phase": current_phase,
        }

    # Process all units currently eligible in this phase.
    loop_count = 0
    max_loops = 300
    last_result: Dict[str, Any] = {"action": "end_phase", "phase": current_phase}

    while True:
        loop_count += 1
        if loop_count > max_loops:
            raise RuntimeError(f"end_phase loop exceeded safety limit for phase '{current_phase}'")

        if require_key(game_state, "phase") != current_phase:
            return True, last_result

        activation_pool = require_key(game_state, pool_key)
        if not activation_pool:
            break

        unit_id = str(activation_pool[0])
        activate_success, activate_result = engine_instance.execute_semantic_action(
            {"action": "activate_unit", "unitId": unit_id}
        )
        if not activate_success:
            return False, {
                "error": "end_phase_activation_failed",
                "phase": current_phase,
                "unitId": unit_id,
                "details": activate_result,
            }

        last_result = activate_result if isinstance(activate_result, dict) else last_result

        if require_key(game_state, "phase") != current_phase:
            return True, last_result

        skip_success, skip_result = engine_instance.execute_semantic_action(
            {"action": "skip", "unitId": unit_id}
        )
        if not skip_success:
            return False, {
                "error": "end_phase_skip_failed",
                "phase": current_phase,
                "unitId": unit_id,
                "details": skip_result,
            }
        last_result = skip_result if isinstance(skip_result, dict) else last_result

        if require_key(game_state, "phase") != current_phase:
            return True, last_result

    # If pool is empty but phase did not transition yet, trigger explicit phase advance.
    advance_success, advance_result = engine_instance.execute_semantic_action(
        {"action": "advance_phase", "from": current_phase, "reason": "manual_end_phase"}
    )
    if not advance_success:
        return False, {
            "error": "end_phase_advance_failed",
            "phase": current_phase,
            "details": advance_result,
        }
    if isinstance(advance_result, dict):
        advance_result["action"] = "end_phase"
    return True, advance_result


def _load_army_file(army_file: str) -> Dict[str, Any]:
    """Load and validate one army config from config/armies."""
    if not army_file or not isinstance(army_file, str):
        raise ValueError("army_file must be a non-empty string")
    if "/" in army_file or "\\" in army_file:
        raise ValueError(f"army_file must be a filename only, got: {army_file}")
    if not army_file.endswith(".json"):
        raise ValueError(f"army_file must end with .json, got: {army_file}")

    armies_dir = os.path.join(abs_parent, "config", "armies")
    army_path = os.path.join(armies_dir, army_file)
    if not os.path.exists(army_path):
        raise FileNotFoundError(f"Army file not found: {army_file}")

    with open(army_path, "r", encoding="utf-8") as f:
        army_cfg = json.load(f)

    require_key(army_cfg, "faction")
    require_key(army_cfg, "description")
    units = require_key(army_cfg, "units")
    if not isinstance(units, list) or not units:
        raise ValueError(f"Army file {army_file} must contain a non-empty units array")
    for idx, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise TypeError(f"Army file {army_file} units[{idx}] must be an object")
        unit_type = require_key(unit, "unit_type")
        count = require_key(unit, "count")
        if not isinstance(unit_type, str) or not unit_type.strip():
            raise ValueError(f"Army file {army_file} units[{idx}].unit_type must be a non-empty string")
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"Army file {army_file} units[{idx}].count must be a positive integer")
    return army_cfg


def _list_armies() -> list[Dict[str, Any]]:
    """Return metadata for all army files in config/armies."""
    armies_dir = os.path.join(abs_parent, "config", "armies")
    if not os.path.isdir(armies_dir):
        raise FileNotFoundError(f"Armies directory not found: {armies_dir}")

    army_files = sorted([name for name in os.listdir(armies_dir) if name.endswith(".json")])
    armies: list[Dict[str, Any]] = []
    for army_file in army_files:
        army_cfg = _load_army_file(army_file)
        armies.append(
            {
                "file": army_file,
                "name": army_file[:-5],
                "faction": require_key(army_cfg, "faction"),
                "description": require_key(army_cfg, "description"),
            }
        )
    return armies


def _build_units_from_army_config(
    army_cfg: Dict[str, Any],
    player: int,
    next_unit_id: int,
    engine_instance: W40KEngine,
) -> Tuple[list[Dict[str, Any]], int]:
    """Build full engine units for one player from army config."""
    if not hasattr(engine_instance, "unit_registry") or engine_instance.unit_registry is None:
        raise ValueError("engine.unit_registry is required to build units from army config")

    built_units: list[Dict[str, Any]] = []
    units = require_key(army_cfg, "units")
    for unit_def in units:
        unit_type = require_key(unit_def, "unit_type")
        count = require_key(unit_def, "count")
        unit_data = engine_instance.unit_registry.get_unit_data(unit_type)
        for _ in range(count):
            unit_id_str = str(next_unit_id)
            next_unit_id += 1
            rng_weapons = copy.deepcopy(require_key(unit_data, "RNG_WEAPONS"))
            cc_weapons = copy.deepcopy(require_key(unit_data, "CC_WEAPONS"))
            selected_rng_weapon_index = 0 if rng_weapons else None
            selected_cc_weapon_index = 0 if cc_weapons else None
            shoot_left = 0
            if rng_weapons and selected_rng_weapon_index is not None:
                selected_weapon = rng_weapons[selected_rng_weapon_index]
                shoot_left = resolve_dice_value(require_key(selected_weapon, "NB"), "api_roster_change_shoot_left")
            attack_left = 0
            if cc_weapons and selected_cc_weapon_index is not None:
                selected_weapon = cc_weapons[selected_cc_weapon_index]
                attack_left = resolve_dice_value(require_key(selected_weapon, "NB"), "api_roster_change_attack_left")

            built_units.append(
                {
                    "id": unit_id_str,
                    "player": player,
                    "unitType": unit_type,
                    "DISPLAY_NAME": require_key(unit_data, "DISPLAY_NAME"),
                    "col": -1,
                    "row": -1,
                    "HP_CUR": require_key(unit_data, "HP_MAX"),
                    "HP_MAX": require_key(unit_data, "HP_MAX"),
                    "MOVE": require_key(unit_data, "MOVE"),
                    "T": require_key(unit_data, "T"),
                    "ARMOR_SAVE": require_key(unit_data, "ARMOR_SAVE"),
                    "INVUL_SAVE": require_key(unit_data, "INVUL_SAVE"),
                    "RNG_WEAPONS": rng_weapons,
                    "CC_WEAPONS": cc_weapons,
                    "selectedRngWeaponIndex": selected_rng_weapon_index,
                    "selectedCcWeaponIndex": selected_cc_weapon_index,
                    "LD": require_key(unit_data, "LD"),
                    "OC": require_key(unit_data, "OC"),
                    "VALUE": require_key(unit_data, "VALUE"),
                    "ICON": require_key(unit_data, "ICON"),
                    "ICON_SCALE": require_key(unit_data, "ICON_SCALE"),
                    "UNIT_RULES": copy.deepcopy(require_key(unit_data, "UNIT_RULES")),
                    "SHOOT_LEFT": shoot_left,
                    "ATTACK_LEFT": attack_left,
                }
            )
    return built_units, next_unit_id


def _execute_change_roster_action(engine_instance: W40KEngine, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Replace active deployer's undeployed roster with selected army file."""
    game_state = require_key(engine_instance.__dict__, "game_state")
    if require_key(game_state, "phase") != "deployment":
        return False, {"error": "change_roster_only_in_deployment", "phase": game_state.get("phase")}
    if require_key(game_state, "deployment_type") != "active":
        return False, {"error": "change_roster_requires_active_deployment"}
    deployment_state = require_key(game_state, "deployment_state")
    current_deployer = int(require_key(deployment_state, "current_deployer"))
    target_deployer = current_deployer

    requested_player = action.get("player")
    if requested_player is not None:
        current_mode_code = getattr(engine_instance, "current_mode_code", None)
        allowed_multi_player_roster_modes = {"test", "pvp", "pve"}
        player_types = game_state.get("player_types")
        legacy_human_vs_human_setup = (
            isinstance(player_types, dict)
            and player_types.get("1") == "human"
            and player_types.get("2") == "human"
        )
        if current_mode_code not in allowed_multi_player_roster_modes and not legacy_human_vs_human_setup:
            return False, {"error": "change_roster_player_only_in_setup_modes"}
        target_deployer = int(requested_player)
        if target_deployer not in (1, 2):
            raise ValueError(f"Invalid player for change_roster: {requested_player}")

    # Enforce: change roster only before active player deploys first unit.
    deployable_units = require_key(deployment_state, "deployable_units")
    deployed_units = require_key(deployment_state, "deployed_units")
    deployable_for_player = deployable_units.get(target_deployer, deployable_units.get(str(target_deployer)))
    if deployable_for_player is None:
        raise KeyError(f"deployable_units missing player {target_deployer}")
    deployed_set = {str(uid) for uid in deployed_units}
    current_player_units = [u for u in require_key(game_state, "units") if int(require_key(u, "player")) == target_deployer]
    current_player_unit_ids = {str(require_key(unit, "id")) for unit in current_player_units}
    if current_player_unit_ids & deployed_set:
        return False, {"error": "change_roster_locked_after_first_deploy", "current_deployer": target_deployer}

    army_file = require_key(action, "army_file")
    army_cfg = _load_army_file(army_file)

    all_unit_ids = [int(str(require_key(unit, "id"))) for unit in require_key(game_state, "units")]
    next_unit_id = (max(all_unit_ids) + 1) if all_unit_ids else 1
    new_units, _ = _build_units_from_army_config(army_cfg, target_deployer, next_unit_id, engine_instance)

    # Replace only current deployer's units, then compact IDs to prevent unbounded growth.
    other_units = [u for u in require_key(game_state, "units") if int(require_key(u, "player")) != target_deployer]
    combined_units = other_units + new_units
    id_remap: Dict[str, str] = {}
    for idx, unit in enumerate(combined_units, start=1):
        old_id = str(require_key(unit, "id"))
        new_id = str(idx)
        id_remap[old_id] = new_id
        unit["id"] = new_id
    game_state["units"] = combined_units

    # Keep deployment state coherent after replacement and ID compaction.
    old_deployed_after_replace = {uid for uid in deployed_set if uid not in current_player_unit_ids}
    new_deployed_set = {id_remap[uid] for uid in old_deployed_after_replace if uid in id_remap}
    deployment_state["deployed_units"] = new_deployed_set

    rebuilt_deployable_units: Dict[int, list[str]] = {1: [], 2: []}
    for unit in combined_units:
        unit_id = str(require_key(unit, "id"))
        unit_player = int(require_key(unit, "player"))
        if unit_id not in new_deployed_set:
            rebuilt_deployable_units[unit_player].append(unit_id)
    deployment_state["deployable_units"] = rebuilt_deployable_units

    deployment_state["current_deployer"] = current_deployer
    game_state["current_player"] = current_deployer

    # Rebuild cache from updated units list.
    build_units_cache(game_state)
    units_cache = require_key(game_state, "units_cache")
    game_state["units_cache_prev"] = {
        uid: {
            "col": require_key(entry, "col"),
            "row": require_key(entry, "row"),
            "HP_CUR": require_key(entry, "HP_CUR"),
            "player": require_key(entry, "player"),
        }
        for uid, entry in units_cache.items()
    }

    # If AI player roster changed, reload micro models so PvE/Test AI can act with new unit types.
    ai_enabled = bool(
        getattr(engine_instance, "is_pve_mode", False)
        or getattr(engine_instance, "is_test_mode", False)
        or getattr(engine_instance, "is_debug_mode", False)
    )
    if ai_enabled and target_deployer == 2:
        engine_instance.pve_controller.load_ai_model_for_pve(game_state, engine_instance)

    updated_unit_ids = [
        str(require_key(unit, "id"))
        for unit in combined_units
        if int(require_key(unit, "player")) == target_deployer
    ]
    return True, {
        "action": "change_roster",
        "army_file": army_file,
        "army_name": army_file[:-5],
        "current_deployer": current_deployer,
        "updated_player": target_deployer,
        "updated_unit_ids": updated_unit_ids,
    }


@app.route('/api/armies', methods=['GET'])
def list_armies():
    """List selectable armies from config/armies."""
    try:
        return jsonify({"success": True, "armies": _list_armies()})
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to list armies: {str(e)}"}), 500

@app.route('/api/game/state', methods=['GET'])
def get_game_state():
    """Get current game state."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    # Convert game state to JSON-serializable format
    serializable_state = make_json_serializable(dict(engine.game_state))
    _sync_units_hp_from_cache(serializable_state, engine.game_state)
    _attach_player_types(serializable_state, engine)
    
    return jsonify({
        "success": True,
        "game_state": serializable_state
    })

@app.route('/api/game/reset', methods=['POST'])
def reset_game():
    """Reset the current game."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        obs, info = engine.reset()
        serializable_state = make_json_serializable(dict(engine.game_state))
        _sync_units_hp_from_cache(serializable_state, engine.game_state)
        _attach_player_types(serializable_state, engine)

        return jsonify({
            "success": True,
            "game_state": serializable_state,
            "message": "Game reset successfully"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Reset failed: {str(e)}"
        }), 500

@app.route('/api/config/board', methods=['GET'])
def get_board_config():
    """Get board configuration for frontend."""
    try:
        # Load board config from file
        board_config_path = "config/board_config.json"
        if os.path.exists(board_config_path):
            with open(board_config_path, 'r', encoding='utf-8-sig') as f:
                board_data = json.loads(f.read())
            return jsonify({
                "success": True,
                "config": board_data["default"]
            })
        else:
            return jsonify({
                "success": False,
                "error": "Board config not found"
            }), 404
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Config load failed: {str(e)}"
        }), 500

@app.route('/api/debug/actions', methods=['GET'])
def get_available_actions():
    """Get list of available semantic actions for debugging."""
    return jsonify({
        "success": True,
        "actions": {
            "move": {
                "description": "Move a unit to specific destination",
                "format": {
                    "action": "move",
                    "unitId": "unit_id_string",
                    "destCol": "integer",
                    "destRow": "integer"
                },
                "example": {
                    "action": "move",
                    "unitId": "player1_unit1",
                    "destCol": 5,
                    "destRow": 3
                }
            },
            "skip": {
                "description": "Skip current unit's activation",
                "format": {
                    "action": "skip",
                    "unitId": "unit_id_string"
                },
                "example": {
                    "action": "skip",
                    "unitId": "player0_unit1"
                }
            }
        }
    })

@app.route('/api/game/ai-turn', methods=['POST'])
def execute_ai_turn():
    """Execute AI turn - pure HTTP wrapper."""
    global engine
    
    if not engine:
        return jsonify({"success": False, "error": "Engine not initialized"}), 400
    
    try:
        # Debug: Check engine state before AI turn (conditional on debug mode)
        debug_mode = os.environ.get('W40K_DEBUG', 'false').lower() == 'true'
        
        if debug_mode:
            print(f"DEBUG AI_TURN: AI model loaded = {hasattr(engine.pve_controller, 'ai_model') and engine.pve_controller.ai_model is not None}")
        
        success, result = engine.execute_ai_turn()
        
        if debug_mode:
            print(f"DEBUG AI_TURN: execute_ai_turn returned success={success}, result={result}")
            print(f"DEBUG AI_TURN: current_phase={engine.game_state.get('phase')}, current_player={engine.game_state.get('current_player')}")
            if engine.game_state.get('phase') == 'shoot':
                print(f"DEBUG AI_TURN: shoot_activation_pool={engine.game_state.get('shoot_activation_pool', [])}")
            print(f"DEBUG AI_TURN: shoot_activation_pool={engine.game_state.get('shoot_activation_pool', [])}")
        
        if not success:
            error_type = result.get("error", "unknown_error")
            print(f"❌ [API] execute_ai_turn failed: error_type={error_type}, result={result}")
            if error_type in ["not_pve_mode", "not_ai_player_turn"]:
                return jsonify({"success": False, "error": result}), 400
            else:
                return jsonify({"success": False, "error": result}), 500

        # Convert game state to JSON-serializable format
        serializable_state = make_json_serializable(dict(engine.game_state))
        _sync_units_hp_from_cache(serializable_state, engine.game_state)
        _attach_player_types(serializable_state, engine)
        
        # Extract action logs for this specific AI action
        action_logs = serializable_state.get("action_logs", [])
        
        # CRITICAL: Always clear logs after extracting to prevent accumulation
        engine.game_state["action_logs"] = []
        serializable_state["action_logs"] = []
        
        return jsonify({
            "success": True,
            "result": result,
            "game_state": serializable_state,
            "action_logs": action_logs
        })
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/replay/parse', methods=['POST'])
def parse_replay_log():
    """
    Parse train_step.log into replay format.

    Request body:
        {
            "log_path": "train_step.log"  // Optional, defaults to "train_step.log"
        }

    Returns:
        {
            "total_episodes": N,
            "episodes": [...]
        }
    """
    try:
        from services.replay_parser import parse_log_file

        data = request.get_json() or {}
        log_path = data.get('log_path', 'train_step.log')

        # Security: Only allow logs in current directory or subdirectories
        if '..' in log_path or log_path.startswith('/'):
            return jsonify({"error": "Invalid log path"}), 400

        if not os.path.exists(log_path):
            return jsonify({"error": f"Log file not found: {log_path}"}), 404

        replay_data = parse_log_file(log_path)
        return jsonify(replay_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/replay/default', methods=['GET'])
def get_default_replay_log():
    """
    Get the default step.log file content for auto-loading in replay mode.

    Returns:
        Raw text content of step.log
    """
    try:
        # Look in project root (one directory up from services/)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(project_root, 'step.log')

        if not os.path.exists(log_path):
            return jsonify({"error": "step.log not found"}), 404

        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Return as plain text for frontend parsing
        from flask import Response
        return Response(content, mimetype='text/plain')

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/replay/file/<filename>', methods=['GET'])
def get_replay_log_file(filename):
    """
    Get a specific replay log file content by filename.

    Args:
        filename: Name of the log file (e.g., "train_step.log")

    Returns:
        Raw text content of the log file
    """
    try:
        # Security: Only allow .log files, no path traversal
        if not filename.endswith('.log'):
            return jsonify({"error": "Only .log files are allowed"}), 400
        
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({"error": "Invalid filename"}), 400

        # Look in project root (one directory up from services/)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(project_root, filename)

        if not os.path.exists(log_path):
            return jsonify({"error": f"Log file not found: {filename}"}), 404

        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Return as plain text for frontend parsing
        from flask import Response
        return Response(content, mimetype='text/plain')

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/replay/list', methods=['GET'])
def list_replay_logs():
    """
    List available replay log files.

    Returns:
        {
            "logs": [
                {"name": "train_step.log", "size": 12345, "modified": "2025-01-14"},
                ...
            ]
        }
    """
    try:
        logs = []
        
        # Look in project root (one directory up from services/)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Check for train_step.log in project root
        train_step_path = os.path.join(project_root, 'train_step.log')
        if os.path.exists(train_step_path):
            stats = os.stat(train_step_path)
            logs.append({
                'name': 'train_step.log',
                'size': stats.st_size,
                'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))
            })

        # Check for other .log files in project root
        for filename in os.listdir(project_root):
            if filename.endswith('.log') and filename != 'train_step.log':
                file_path = os.path.join(project_root, filename)
                if os.path.isfile(file_path):
                    stats = os.stat(file_path)
                    logs.append({
                        'name': filename,
                        'size': stats.st_size,
                        'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats.st_mtime))
                    })

        return jsonify({'logs': logs})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def serve_frontend():
    """Serve frontend instructions."""
    return jsonify({
        "message": "W40K Engine API Server",
        "frontend_url": "http://localhost:5175",
        "api_endpoints": {
            "health": "/api/health",
            "auth_register": "/api/auth/register",
            "auth_login": "/api/auth/login",
            "auth_me": "/api/auth/me",
            "start_game": "/api/game/start",
            "execute_action": "/api/game/action",
            "ai_turn": "/api/game/ai-turn",
            "get_state": "/api/game/state",
            "reset_game": "/api/game/reset",
            "board_config": "/api/config/board",
            "debug_actions": "/api/debug/actions",
            "replay_parse": "/api/replay/parse",
            "replay_default": "/api/replay/default",
            "replay_list": "/api/replay/list"
        },
        "instructions": [
            "1. Start frontend: cd frontend && npm run dev",
            "2. API server runs on http://localhost:5001",
            "3. Frontend runs on http://localhost:5175",
            "4. POST /api/game/start with pve_mode:true for AI",
            "5. POST /api/game/action with semantic actions",
            "6. POST /api/game/ai-turn to execute AI Player 2 turn"
        ]
    })

if __name__ == '__main__':
    print("🚀 Starting W40K Engine API Server...")
    print("📡 Server will run on http://localhost:5001")
    print("🎮 Frontend should connect to this API")
    print("✨ Use AI_TURN.md compliant semantic actions")
    
    # Initialize engine on startup
    if initialize_engine():
        print("⚡ Ready to serve the board!")
    else:
        print("⚠️  Engine initialization failed - will retry on first request")
    
    app.run(host='0.0.0.0', port=5001, debug=True)