# config_loader.py - ROOT FOLDER
"""
Centralized configuration loader for WH40K Tactics game.
This module provides a single source of truth for all game configuration values.
Place this file in the PROJECT ROOT directory.
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path

class ConfigLoader:
    """Centralized configuration loader."""
    
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
        """Get training configuration."""
        return self.load_config("training_config", force_reload=False)
    
    def get_rewards_config(self) -> Dict[str, Any]:
        """Get rewards configuration."""
        return self.load_config("rewards_config", force_reload=False)
    
    # ─── Alias methods for named config loading ─────────────────────────
    def load_training_config(self, name: str) -> Dict[str, Any]:
        """Load a named training configuration from training_config.json."""
        configs = self.load_config("training_config", force_reload=False)
        try:
            return configs[name]
        except KeyError:
            raise KeyError(f"Training config '{name}' not found in training_config.json")

    def load_rewards_config(self, name: str) -> Dict[str, Any]:
        """Load rewards configuration directly (unit-type-based approach)."""
        return self.load_config("rewards_config", force_reload=False)
    
    def get_board_config(self) -> Dict[str, Any]:
        """Get board configuration."""
        return self.load_config("board_config", force_reload=False)
    
    def get_unit_definitions(self) -> Dict[str, Any]:
        """Get unit definitions."""
        return self.load_config("unit_definitions", force_reload=False)

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