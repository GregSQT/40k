#!/usr/bin/env python3
"""
Enhanced configuration loader for W40K AI training
"""

import json
import os
import shutil
from datetime import datetime

class ConfigLoader:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        self.config_dir = os.path.join(project_root, "config")
        
    def load_main_config(self):
        """Load main configuration file with defaults."""
        config_path = os.path.join(self.config_dir, "config.json")
        if not os.path.exists(config_path):
            self._create_default_main_config()
        
        with open(config_path, "r") as f:
            return json.load(f)
    
    def _create_default_main_config(self):
        """Create default main config.json if it doesn't exist."""
        print("Creating default config.json...")
        
        default_config = {
            "project": {
                "name": "WH40K Tactics RL",
                "version": "1.0.0",
                "description": "Warhammer 40k tactical game with AI opponents"
            },
            "paths": {
                "ai_models": "ai/",
                "scenarios": "config/scenarios.json",
                "rewards": "config/rewards_config.json",
                "training": "config/training_config.json",
                "tensorboard": "./tensorboard/"
            },
            "defaults": {
                "scenario": "default",
                "training_config": "default",
                "rewards_config": "original"
            },
            "game": {
                "board_size": [24, 18],
                "max_turns": 50
            }
        }
        
        os.makedirs(self.config_dir, exist_ok=True)
        config_path = os.path.join(self.config_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(default_config, f, indent=2)
        print(f"Created {config_path}")
        
    def load_scenario(self, scenario_name="default"):
        """Load scenario configuration."""
        config_path = os.path.join(self.config_dir, "scenarios.json")
        if not os.path.exists(config_path):
            self._create_default_scenarios()
            
        with open(config_path, "r") as f:
            scenarios = json.load(f)
        if scenario_name not in scenarios:
            available = list(scenarios.keys())
            raise ValueError(f"Scenario '{scenario_name}' not found. Available: {available}")
        return scenarios[scenario_name]
        
    def load_training_config(self, config_name="default"):
        """Load training configuration."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Training config not found: {config_path}")
        with open(config_path, "r") as f:
            configs = json.load(f)
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Config '{config_name}' not found. Available: {available}")
        return configs[config_name]
    
    def load_rewards_config(self, config_name="original"):
        """Load rewards configuration."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Rewards config not found: {config_path}")
        with open(config_path, "r") as f:
            configs = json.load(f)
        if config_name not in configs:
            available = list(configs.keys())
            raise ValueError(f"Rewards config '{config_name}' not found. Available: {available}")
        return configs[config_name]
    
    def list_scenarios(self):
        """List available scenarios."""
        config_path = os.path.join(self.config_dir, "scenarios.json")
        if not os.path.exists(config_path): 
            return ["default"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def list_training_configs(self):
        """List available training configurations."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        if not os.path.exists(config_path): 
            return ["default"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def list_rewards_configs(self):
        """List available reward configurations."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        if not os.path.exists(config_path): 
            return ["original"]
        with open(config_path, "r") as f:
            return list(json.load(f).keys())
    
    def apply_scenario_to_file(self, scenario_name="default"):
        """Apply scenario config to ai/scenario.json"""
        scenario_config = self.load_scenario(scenario_name)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        scenario_file = os.path.join(script_dir, "scenario.json")
        
        with open(scenario_file, "w") as f:
            json.dump(scenario_config["units"], f, indent=2)
        print(f"Applied '{scenario_name}' scenario")
    
    def apply_rewards_to_file(self, rewards_config_name="original"):
        """Apply rewards config to ai/rewards_master.json"""
        rewards_config = self.load_rewards_config(rewards_config_name)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        rewards_file = os.path.join(script_dir, "rewards_master.json")
        
        with open(rewards_file, "w") as f:
            reward_data = {k: v for k, v in rewards_config.items() if k != "description"}
            json.dump(reward_data, f, indent=2)
        print(f"Applied '{rewards_config_name}' rewards")
    
    def _create_default_scenarios(self):
        """Create default scenarios.json if it doesn't exist."""
        print("Creating default scenarios.json...")
        
        # Try to load existing scenario from ai/scenario.json
        script_dir = os.path.dirname(os.path.abspath(__file__))
        existing_scenario_path = os.path.join(script_dir, "scenario.json")
        
        if os.path.exists(existing_scenario_path):
            with open(existing_scenario_path, "r") as f:
                existing_units = json.load(f)
        else:
            # Create basic default scenario
            existing_units = [
                {
                    "id": 1, "unit_type": "Intercessor", "player": 0,
                    "col": 23, "row": 12, "cur_hp": 3, "hp_max": 3,
                    "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                    "is_ranged": True, "is_melee": False, "alive": True
                },
                {
                    "id": 2, "unit_type": "AssaultIntercessor", "player": 0,
                    "col": 1, "row": 12, "cur_hp": 4, "hp_max": 4,
                    "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                    "is_ranged": False, "is_melee": True, "alive": True
                },
                {
                    "id": 3, "unit_type": "Intercessor", "player": 1,
                    "col": 0, "row": 5, "cur_hp": 3, "hp_max": 3,
                    "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                    "is_ranged": True, "is_melee": False, "alive": True
                },
                {
                    "id": 4, "unit_type": "AssaultIntercessor", "player": 1,
                    "col": 22, "row": 3, "cur_hp": 4, "hp_max": 4,
                    "move": 6, "rng_rng": 4, "rng_dmg": 1, "cc_dmg": 2,
                    "is_ranged": False, "is_melee": True, "alive": True
                }
            ]
        
        scenarios = {
            "default": {
                "description": "Default 4-unit scenario with 2 Intercessors and 2 Assault Intercessors",
                "units": existing_units
            },
            "test": {
                "description": "Small 2-unit scenario for quick testing",
                "units": existing_units[:2]
            },
            "large": {
                "description": "Larger scenario with more units",
                "units": existing_units + [
                    {
                        "id": 5, "unit_type": "Intercessor", "player": 0,
                        "col": 20, "row": 15, "cur_hp": 3, "hp_max": 3,
                        "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                        "is_ranged": True, "is_melee": False, "alive": True
                    },
                    {
                        "id": 6, "unit_type": "Intercessor", "player": 1,
                        "col": 3, "row": 2, "cur_hp": 3, "hp_max": 3,
                        "move": 4, "rng_rng": 8, "rng_dmg": 2, "cc_dmg": 1,
                        "is_ranged": True, "is_melee": False, "alive": True
                    }
                ]
            }
        }
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Write scenarios file
        config_path = os.path.join(self.config_dir, "scenarios.json")
        with open(config_path, "w") as f:
            json.dump(scenarios, f, indent=2)
        
        print(f"Created {config_path}")

if __name__ == "__main__":
    loader = ConfigLoader()
    print("Available scenarios:", loader.list_scenarios())
    print("Available training configs:", loader.list_training_configs())
    print("Available reward configs:", loader.list_rewards_configs())
