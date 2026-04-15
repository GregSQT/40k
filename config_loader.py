# config_loader.py - ROOT FOLDER
"""
Centralized configuration loader for WH40K Tactics game.
This module provides a single source of truth for all game configuration values.
Place this file in the PROJECT ROOT directory.
"""

import json
import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

class ConfigLoader:
    """Centralized configuration loader."""
    
    _LOGGER = logging.getLogger(__name__)
    
    def __init__(self, root_path: str):
        """Initialize config loader.
        
        Args:
            root_path: Root path for configuration directory.
        """
        self.root_path = Path(root_path)
        self.config_dir = self.root_path / "config"
        self._cache = {}
    
    def load_config(self, config_name: str, force_reload: bool) -> Dict[str, Any]:
        """Load configuration file.
        
        Args:
            config_name: Name of config file (without .json extension)
            force_reload: Force reload from disk even if cached
            
        Returns:
            Configuration dictionary
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is invalid JSON
        """
        if not force_reload and config_name in self._cache:
            return self._cache[config_name]
        
        config_file = self.config_dir / f"{config_name}.json"
        
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        try:
            with open(config_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                self._cache[config_name] = config
                return config
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {config_file}: {e}")
    
    def get_game_config(self) -> Dict[str, Any]:
        """Get game configuration."""
        return self.load_config("game_config", force_reload=False)
    
    def get_models_dir(self) -> str:
        """Get models directory path."""
        return os.path.join(self.root_path, "models")
    
    def get_max_turns(self) -> int:
        """Get maximum number of turns per game."""
        game_config = self.get_game_config()
        return game_config["game_rules"]["max_turns"]
    
    def get_board_size(self) -> tuple[int, int]:
        """Get board size as (cols, rows) from board_config as single source of truth."""
        board_config = self.get_board_config()
        cols = board_config["default"]["cols"]
        rows = board_config["default"]["rows"]
        return (cols, rows)
    
    def get_turn_limit_penalty(self) -> float:
        """Get penalty applied when reaching turn limit."""
        game_config = self.get_game_config()
        return game_config["game_rules"]["turn_limit_penalty"]
    
    def get_model_path(self) -> str:
        """Get the model file path - AI_INSTRUCTIONS.md compliance."""
        try:
            config = self.load_config("config", force_reload=False)
            return config["paths"]["model_file"]
        except (KeyError, FileNotFoundError):
            # AI_INSTRUCTIONS.md: No hardcoded fallbacks allowed
            raise FileNotFoundError("AI_INSTRUCTIONS.md violation: Model path not configured in config/config.json. Must define paths.model_file")

    def get_models_root(self) -> str:
        """Get the root directory for model files."""
        try:
            config = self.load_config("config", force_reload=False)
            models_root = config["paths"]["models_root"]
            if not isinstance(models_root, str) or not models_root.strip():
                raise ValueError(
                    "Invalid config/config.json: paths.models_root must be a non-empty string"
                )
            models_root_path = Path(models_root)
            if not models_root_path.is_absolute():
                models_root_path = self.root_path / models_root_path
            return str(models_root_path)
        except (KeyError, FileNotFoundError):
            raise FileNotFoundError("Model root path not configured in config/config.json. Must define paths.models_root")
    
    def get_phase_order(self) -> list[str]:
        """Get game phase order - raises error if missing."""
        game_config = self.get_game_config()
        if "gameplay" not in game_config:
            raise KeyError("Missing 'gameplay' section in game_config.json")
        if "phase_order" not in game_config["gameplay"]:
            raise KeyError("Missing 'phase_order' in gameplay section of game_config.json")
        phase_order = game_config["gameplay"]["phase_order"]
        if not phase_order:
            raise ValueError("Phase order is empty in game_config.json")
        return phase_order

    def get_reward_value(self, unit_type: str, action: str) -> float:
        """Get specific reward value - raises error if missing."""
        rewards_config = self.load_rewards_config()
        
        if unit_type not in rewards_config:
            available_types = list(rewards_config.keys())
            raise KeyError(f"Unit type '{unit_type}' not found in rewards config. Available: {available_types}")
        
        unit_rewards = rewards_config[unit_type]
        if action not in unit_rewards:
            available_actions = list(unit_rewards.keys())
            raise KeyError(f"Action '{action}' not found for unit type '{unit_type}'. Available: {available_actions}")
        
        return unit_rewards[action]    
    
    def get_max_history(self, training_config_name: str = "default") -> int:
        """Get max history for state management - raises error if missing."""
        full_config = self.load_config("training_config", force_reload=False)
        shared_params = full_config.get("shared_parameters", {})
        state_mgmt = shared_params.get("state_management", {})
        if "max_history" not in state_mgmt:
            raise KeyError(f"max_history missing from global shared_parameters.state_management")
        return state_mgmt["max_history"]

    def get_log_available_height(self) -> int:
        """Get log available height from game config."""
        game_config = self.get_game_config()
        if "ui" not in game_config:
            raise KeyError("Missing 'ui' section in game_config.json")
        if "log_available_height" not in game_config["ui"]:
            raise KeyError("Missing 'log_available_height' in ui section of game_config.json")
        return game_config["ui"]["log_available_height"]
     
    def get_training_config(self) -> Dict[str, Any]:
        """DEPRECATED: Use load_agent_training_config() instead.
        
        Legacy method for backwards compatibility - raises error directing to new method.
        """
        raise RuntimeError(
            "get_training_config() is deprecated. Training configs are now agent-specific.\n"
            "Use config_loader.load_agent_training_config(agent_key) instead.\n"
            "Agent configs located at: config/agents/{AGENT_KEY}/{AGENT_KEY}_training_config.json"
        )
    
    def get_rewards_config(self) -> Dict[str, Any]:
        """DEPRECATED: Use load_agent_rewards_config() instead.
        
        Legacy method for backwards compatibility - raises error directing to new method.
        """
        raise RuntimeError(
            "get_rewards_config() is deprecated. Rewards configs are now agent-specific.\n"
            "Use config_loader.load_agent_rewards_config(agent_key) instead.\n"
            "Agent configs located at: config/agents/{AGENT_KEY}/{AGENT_KEY}_rewards_config.json"
        )
    
    # ─── DEPRECATED: Alias methods for named config loading ─────────────────────────
    def load_training_config(self, name: str) -> Dict[str, Any]:
        """DEPRECATED: Use load_agent_training_config() instead."""
        raise RuntimeError(
            f"load_training_config('{name}') is deprecated. Training configs are now agent-specific.\n"
            "Use config_loader.load_agent_training_config(agent_key, phase) instead.\n"
            "Agent configs located at: config/agents/{AGENT_KEY}/{AGENT_KEY}_training_config.json"
        )

    def load_rewards_config(self, name: str) -> Dict[str, Any]:
        """DEPRECATED: Use load_agent_rewards_config() instead."""
        raise RuntimeError(
            f"load_rewards_config('{name}') is deprecated. Rewards configs are now agent-specific.\n"
            "Use config_loader.load_agent_rewards_config(agent_key) instead.\n"
            "Agent configs located at: config/agents/{AGENT_KEY}/{AGENT_KEY}_rewards_config.json"
        )
    
    def get_board_config(self) -> Dict[str, Any]:
        """Get board configuration from config/board/{paths.board}/board_config.json."""
        config = self.load_config("config", force_reload=False)
        board_subdir = config.get("paths", {}).get("board")
        if board_subdir:
            board_path = self.config_dir / board_subdir / "board_config.json"
        else:
            board_path = self.config_dir / "board_config.json"
        if not board_path.exists():
            raise FileNotFoundError(f"Board config not found: {board_path}")
        cache_key = "board_config"
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            with open(board_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            self._cache[cache_key] = data
            return data
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {board_path}: {e}")
    
    def get_unit_definitions(self) -> Dict[str, Any]:
        """Get unit definitions."""
        return self.load_config("unit_definitions", force_reload=False)
    
    # ─── Agent-specific config loading ──────────────────────────────────
    def load_agent_training_config(self, agent_key: str, phase: str = None) -> Dict[str, Any]:
        """Load agent-specific training configuration.
        
        Args:
            agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
            phase: Optional phase name (e.g., 'phase1', 'phase2'). If provided, returns 
                   only that phase's config. If None, returns entire config file.
        
        Returns:
            Training configuration dictionary or phase-specific config
            
        Raises:
            FileNotFoundError: If agent config file doesn't exist
            KeyError: If phase specified but not found in config
        """
        resolved_agent_key = self._resolve_agent_config_key(agent_key)
        agent_config_path = self.config_dir / "agents" / resolved_agent_key / f"{resolved_agent_key}_training_config.json"
        
        if not agent_config_path.exists():
            raise FileNotFoundError(
                f"Agent training config not found: {agent_config_path}\n"
                f"Expected path: config/agents/{resolved_agent_key}/{resolved_agent_key}_training_config.json"
            )
        
        try:
            with open(agent_config_path, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                
                if phase is not None:
                    if phase not in config:
                        available_phases = [k for k in config.keys() if not k.startswith('_')]
                        raise KeyError(
                            f"Phase '{phase}' not found in {resolved_agent_key}_training_config.json. "
                            f"Available phases: {available_phases}"
                        )
                    phase_config = config[phase]
                    if not isinstance(phase_config, dict):
                        raise TypeError(
                            f"Invalid phase config type in {agent_config_path}: "
                            f"phase '{phase}' must be an object, got {type(phase_config).__name__}"
                        )
                    return self._resolve_training_common_references(
                        phase_config=phase_config,
                        agent_key=resolved_agent_key,
                        phase=phase
                    )
                
                return config
                
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {agent_config_path}: {e}")

    def load_training_common_config(self) -> Dict[str, Any]:
        """Load shared training defaults from config/agents/_training_common.json."""
        cache_key = "agents::_training_common"
        if cache_key in self._cache:
            return self._cache[cache_key]

        common_path = self.config_dir / "agents" / "_training_common.json"
        if not common_path.exists():
            raise FileNotFoundError(
                f"Shared training config not found: {common_path}\n"
                f"Expected path: config/agents/_training_common.json"
            )
        try:
            with open(common_path, "r", encoding="utf-8-sig") as f:
                common_config = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {common_path}: {e}")

        if not isinstance(common_config, dict):
            raise TypeError(
                f"Invalid shared training config format in {common_path}: "
                f"expected JSON object, got {type(common_config).__name__}"
            )
        self._cache[cache_key] = common_config
        return common_config

    def _resolve_training_common_references(
        self,
        phase_config: Dict[str, Any],
        agent_key: str,
        phase: str
    ) -> Dict[str, Any]:
        """Resolve phase keys set to null using config/agents/_training_common.json."""
        resolved = dict(phase_config)
        null_keys = [k for k, v in resolved.items() if v is None]
        if not null_keys:
            return resolved

        common_config = self.load_training_common_config()
        for key in null_keys:
            if key not in common_config:
                raise KeyError(
                    f"Training config '{agent_key}/{phase}' uses null for '{key}' "
                    f"but config/agents/_training_common.json does not define '{key}'"
                )
            common_value = common_config[key]
            if common_value is None:
                raise ValueError(
                    f"Invalid shared training value for '{key}' in config/agents/_training_common.json: null"
                )
            resolved[key] = common_value
        return resolved
    
    def load_agent_rewards_config(self, agent_key: str) -> Dict[str, Any]:
        """Load agent-specific rewards configuration.
        
        Args:
            agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
        
        Returns:
            Rewards configuration dictionary
            
        Raises:
            FileNotFoundError: If agent rewards config file doesn't exist
        """
        cache_key = f"rewards_config::{agent_key}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        resolved_agent_key = self._resolve_agent_config_key(agent_key)
        agent_config_path = self.config_dir / "agents" / resolved_agent_key / f"{resolved_agent_key}_rewards_config.json"
        
        if not agent_config_path.exists():
            raise FileNotFoundError(
                f"Agent rewards config not found: {agent_config_path}\n"
                f"Expected path: config/agents/{resolved_agent_key}/{resolved_agent_key}_rewards_config.json"
            )
        
        try:
            with open(agent_config_path, 'r', encoding='utf-8-sig') as f:
                rewards_config = json.load(f)
                if agent_key == resolved_agent_key:
                    self._cache[cache_key] = rewards_config
                    return rewards_config

                # Inter-faction mode: expose canonical key while keeping source key.
                if resolved_agent_key not in rewards_config:
                    raise KeyError(
                        f"Rewards config '{agent_config_path}' missing expected source key "
                        f"'{resolved_agent_key}' for canonical agent '{agent_key}'. "
                        f"Available keys: {list(rewards_config.keys())}"
                    )

                rewards_with_alias = dict(rewards_config)
                rewards_with_alias[agent_key] = rewards_config[resolved_agent_key]
                self._cache[cache_key] = rewards_with_alias
                return rewards_with_alias
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {agent_config_path}: {e}")

    def load_primary_objective_config(self, objective_id: str) -> Dict[str, Any]:
        """Load primary objective configuration by ID.

        Searches in config/primary_objective/{cols}x{rows}/ based on current board size.

        Args:
            objective_id: Primary objective identifier (e.g., "objectives_control")

        Returns:
            Primary objective configuration dictionary

        Raises:
            FileNotFoundError: If primary objective directory is missing
            KeyError: If no config matches the requested objective_id
            RuntimeError: If JSON is invalid
        """
        if not objective_id:
            raise ValueError("objective_id is required to load primary objective config")
        cols, rows = self.get_board_size()
        board_size_dir = f"{cols}x{rows}"
        cache_key = f"primary_objective:{board_size_dir}:{objective_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        primary_objective_dir = self.config_dir / "primary_objective" / board_size_dir
        if not primary_objective_dir.exists():
            raise FileNotFoundError(
                f"Primary objective config directory not found: {primary_objective_dir}"
            )

        for config_file in primary_objective_dir.glob("*.json"):
            try:
                with open(config_file, "r", encoding="utf-8-sig") as f:
                    config = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON in {config_file}: {e}")

            config_id = config.get("id")
            if config_id is None:
                raise KeyError(f"Primary objective config missing required 'id': {config_file}")
            if str(config_id) == str(objective_id):
                self._cache[cache_key] = config
                return config

        raise KeyError(
            f"Primary objective id '{objective_id}' not found in {primary_objective_dir}"
        )

    def load_unit_rules_config(self) -> Dict[str, Any]:
        """Load unit rules configuration with strict validation."""
        cache_key = "unit_rules"
        if cache_key in self._cache:
            return self._cache[cache_key]

        unit_rules_path = self.config_dir / "unit_rules.json"
        if not unit_rules_path.exists():
            raise FileNotFoundError(f"Unit rules config not found: {unit_rules_path}")

        try:
            with open(unit_rules_path, "r", encoding="utf-8-sig") as f:
                unit_rules = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {unit_rules_path}: {e}")

        if not isinstance(unit_rules, dict):
            raise ValueError(f"unit_rules.json must be a dict mapping rule_id to rule config")

        for rule_id, rule_data in unit_rules.items():
            if not isinstance(rule_data, dict):
                raise ValueError(f"Rule '{rule_id}' must be an object, got {type(rule_data).__name__}")
            if "id" not in rule_data:
                raise KeyError(f"Rule '{rule_id}' missing required 'id' field")
            if str(rule_data["id"]) != str(rule_id):
                raise ValueError(f"Rule id mismatch: key '{rule_id}' != rule.id '{rule_data['id']}'")
            if "name" in rule_data:
                name_value = rule_data["name"]
                if not isinstance(name_value, str) or not name_value.strip():
                    raise ValueError(f"Rule '{rule_id}' has invalid 'name': {name_value!r}")
            if "alias" in rule_data:
                alias_value = rule_data["alias"]
                if not isinstance(alias_value, str) or not alias_value.strip():
                    raise ValueError(f"Rule '{rule_id}' has invalid 'alias': {alias_value!r}")
                alias_rule_id = alias_value.strip()
                if alias_rule_id not in unit_rules:
                    raise KeyError(
                        f"Rule '{rule_id}' alias '{alias_rule_id}' is missing in config/unit_rules.json"
                    )
                if alias_rule_id == str(rule_id):
                    raise ValueError(f"Rule '{rule_id}' cannot alias itself")

        self._cache[cache_key] = unit_rules
        return unit_rules
    
    def load_agent_scenario(self, agent_key: str, scenario_name: str) -> Dict[str, Any]:
        """Load agent-specific scenario file.
        
        Args:
            agent_key: Agent identifier (e.g., 'SpaceMarine_Infantry_Troop_RangedSwarm')
            scenario_name: Scenario name (e.g., 'phase1', 'phase2-1', 'phase2-2')
        
        Returns:
            Scenario configuration dictionary:
            - legacy format with 'units' array, or
            - thin format with roster refs (scale, p1_roster_ref, p2_roster_ref)
            
        Raises:
            FileNotFoundError: If scenario file doesn't exist
        """
        resolved_agent_key = self._resolve_agent_config_key(agent_key)
        scenarios_dir = self.config_dir / "agents" / resolved_agent_key / "scenarios"
        scenario_path = scenarios_dir / f"scenario_{scenario_name}.json"
        if not scenario_path.exists():
            raise FileNotFoundError(
                f"Agent scenario not found: {scenario_path}\n"
                f"Expected path:\n"
                f"- config/agents/{resolved_agent_key}/scenarios/scenario_{scenario_name}.json"
            )
        
        try:
            with open(scenario_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {scenario_path}: {e}")

    def _resolve_agent_config_key(self, agent_key: str) -> str:
        """Resolve agent config directory using explicit inherits_from metadata."""
        direct_path = self.config_dir / "agents" / agent_key
        if not direct_path.exists():
            available_agents = sorted([p.name for p in (self.config_dir / "agents").iterdir() if p.is_dir()])
            raise FileNotFoundError(
                f"No config directory found for agent key '{agent_key}'. "
                f"Available config agent directories: {available_agents}"
            )

        training_config_path = direct_path / f"{agent_key}_training_config.json"
        if not training_config_path.exists():
            raise FileNotFoundError(
                f"Agent training config not found for inheritance resolution: {training_config_path}\n"
                f"Expected path: config/agents/{agent_key}/{agent_key}_training_config.json"
            )

        try:
            with open(training_config_path, "r", encoding="utf-8-sig") as f:
                training_config = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {training_config_path}: {e}")

        inherits_from = training_config.get("inherits_from")
        if inherits_from is None:
            return agent_key

        if not isinstance(inherits_from, str) or not inherits_from.strip():
            raise ValueError(
                f"Invalid inherits_from in {training_config_path}: expected non-empty string or null, "
                f"got {inherits_from!r}"
            )

        resolved_agent_key = inherits_from.strip()
        if resolved_agent_key == agent_key:
            raise ValueError(
                f"Invalid inherits_from in {training_config_path}: agent cannot inherit from itself "
                f"('{agent_key}')"
            )

        resolved_path = self.config_dir / "agents" / resolved_agent_key
        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Invalid inherits_from in {training_config_path}: resolved agent directory does not exist: "
                f"{resolved_path}"
            )

        resolved_training_config_path = (
            resolved_path / f"{resolved_agent_key}_training_config.json"
        )
        if not resolved_training_config_path.exists():
            raise FileNotFoundError(
                f"Invalid inherits_from in {training_config_path}: target agent training config not found: "
                f"{resolved_training_config_path}"
            )

        self._LOGGER.warning(
            "\n"
            "================================================================================\n"
            "===================== !!! CRITICAL AGENT INHERITANCE !!! ======================\n"
            "Requested agent key : %s\n"
            "Inherited from      : %s\n"
            "Loaded config dir   : config/agents/%s\n"
            "IMPORTANT: Training/rewards/scenarios are loaded from inherited agent config.\n"
            "================================================================================",
            agent_key,
            resolved_agent_key,
            resolved_agent_key,
        )

        return resolved_agent_key


# Global instance for easy access
_config_loader = None

def get_config_loader() -> ConfigLoader:
    """Get global config loader instance."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(root_path=str(Path(__file__).resolve().parent))
    return _config_loader

def get_max_turns() -> int:
    """Convenience function to get max turns."""
    return get_config_loader().get_max_turns()

def get_board_size() -> tuple[int, int]:
    """Convenience function to get board size."""
    return get_config_loader().get_board_size()

def get_turn_limit_penalty() -> float:
    """Convenience function to get turn limit penalty."""
    return get_config_loader().get_turn_limit_penalty()

def get_model_path() -> str:
    """Convenience function to get model path."""
    return get_config_loader().get_model_path()

# Example usage:
if __name__ == "__main__":
    # Test configuration loading
    config = get_config_loader()
    
    print(f"Max turns: {config.get_max_turns()}")
    print(f"Board size: {config.get_board_size()}")
    print(f"Turn penalty: {config.get_turn_limit_penalty()}")
    
    # Test all configs can be loaded
    try:
        print("\nTesting config loading...")
        config.get_game_config()
        print("✅ game_config.json loaded")
        
        config.get_training_config()
        print("✅ training_config.json loaded")
        
        config.get_rewards_config()
        print("✅ rewards_config.json loaded")
        
        config.get_board_config()
        print("✅ board_config.json loaded")
        
        config.get_unit_definitions()
        print("✅ unit_definitions.json loaded")
        
    except Exception as e:
        print(f"❌ Config loading failed: {e}")

def get_phase_order(self) -> list[str]:
    """Get game phase order - raises error if missing."""
    game_config = self.get_game_config()
    if "gameplay" not in game_config:
        raise KeyError("Missing 'gameplay' section in game_config.json")
    if "phase_order" not in game_config["gameplay"]:
        raise KeyError("Missing 'phase_order' in gameplay section of game_config.json")
    phase_order = game_config["gameplay"]["phase_order"]
    if not phase_order:
        raise ValueError("Phase order is empty in game_config.json")
    return phase_order

def get_reward_value(self, unit_type: str, action: str, rewards_config_name: str) -> float:
    """Get specific reward value - raises error if missing."""
    rewards_config = self.load_rewards_config(rewards_config_name)
    
    if unit_type not in rewards_config:
        available_types = list(rewards_config.keys())
        raise KeyError(f"Unit type '{unit_type}' not found in rewards config '{rewards_config_name}'. Available: {available_types}")
    
    unit_rewards = rewards_config[unit_type]
    if action not in unit_rewards:
        available_actions = list(unit_rewards.keys())
        raise KeyError(f"Action '{action}' not found for unit '{unit_type}' in rewards config '{rewards_config_name}'. Available: {available_actions}")
    
    return unit_rewards[action]

def get_ai_behavior_config(self) -> dict:
    """Get AI behavior configuration with fallbacks."""
    try:
        game_config = self.get_game_config()
        return game_config.get("ai_behavior", {
            "timeout_ms": 5000,
            "retries": 3,
            "fallback_action": "wait"
        })
    except (KeyError, FileNotFoundError):
        return {
            "timeout_ms": 5000,
            "retries": 3,
            "fallback_action": "wait"
        }