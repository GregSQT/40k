#!/usr/bin/env python3
"""
Configuration loader for W40K AI training
"""

import json
import os

class ConfigLoader:
    def __init__(self):
        self.config_dir = "config"
        
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
    
    def list_training_configs(self):
        """List available training configurations."""
        config_path = os.path.join(self.config_dir, "training_config.json")
        with open(config_path, "r") as f:
            configs = json.load(f)
        return list(configs.keys())
    
    def list_rewards_configs(self):
        """List available reward configurations."""
        config_path = os.path.join(self.config_dir, "rewards_config.json")
        with open(config_path, "r") as f:
            configs = json.load(f)
        return list(configs.keys())
    
    def apply_rewards_to_file(self, rewards_config_name="original"):
        """Apply rewards config to ai/rewards_master.json"""
        rewards_config = self.load_rewards_config(rewards_config_name)
        
        # Create backup
        import shutil
        from datetime import datetime
        
        rewards_file = "ai/rewards_master.json"
        if os.path.exists(rewards_file):
            backup_name = f"ai/rewards_master.json.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(rewards_file, backup_name)
            print(f"Backed up current rewards to {backup_name}")
        
        # Write new rewards
        os.makedirs("ai", exist_ok=True)
        with open(rewards_file, "w", encoding="utf-8") as f:
            # Extract just the reward values, not the description
            reward_data = {k: v for k, v in rewards_config.items() if k != "description"}
            json.dump(reward_data, f, indent=2)
        
        print(f"Applied '{rewards_config_name}' rewards to {rewards_file}")

# Example usage
if __name__ == "__main__":
    loader = ConfigLoader()
    
    print("Available training configs:", loader.list_training_configs())
    print("Available reward configs:", loader.list_rewards_configs())
    
    # Example: Load default training config
    training_config = loader.load_training_config("default")
    print("\nDefault training config:")
    print(f"  Total timesteps: {training_config['total_timesteps']:,}")
    print(f"  Learning rate: {training_config['model_params']['learning_rate']}")
    print(f"  Buffer size: {training_config['model_params']['buffer_size']:,}")
    
    # Example: Apply original rewards
    loader.apply_rewards_to_file("original")
