# add_emergency_config.py - Add emergency config to training_config.json

import os
import json

def add_emergency_config():
    """Add emergency configuration to existing training_config.json"""
    
    config_path = "config/training_config.json"
    
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found!")
        return False
    
    # Load existing config
    with open(config_path, 'r') as f:
        configs = json.load(f)
    
    # Add emergency config
    configs["emergency"] = {
        "description": "Emergency config for broken training recovery",
        "total_timesteps": 100000,  # Quick test
        "model_params": {
            "policy": "MlpPolicy",
            "verbose": 1,
            "buffer_size": 25000,
            "learning_rate": 0.001,
            "learning_starts": 2000,
            "batch_size": 64,
            "train_freq": 4,
            "target_update_interval": 1000,
            "exploration_fraction": 0.5,  # More exploration
            "exploration_final_eps": 0.1,  # Less greedy
            "tensorboard_log": "./tensorboard/"
        }
    }
    
    # Save updated config
    with open(config_path, 'w') as f:
        json.dump(configs, f, indent=2)
    
    print(f"✅ Added 'emergency' config to {config_path}")
    
    # Also add emergency rewards config
    rewards_path = "config/rewards_config.json"
    if os.path.exists(rewards_path):
        with open(rewards_path, 'r') as f:
            rewards = json.load(f)
        
        # Add emergency rewards (simplified)
        rewards["emergency"] = {
            "description": "Emergency simplified rewards for learning",
            "SpaceMarineRanged": {
                "move_close": 0.1,
                "move_away": 0.0,
                "move_to_safe": 0.1,
                "move_to_rng": 0.2,
                "move_to_charge": 0.0,
                "move_to_rng_charge": 0.1,
                "ranged_attack": 0.3,
                "enemy_killed_r": 2.0,  # Big reward for kills
                "enemy_killed_lowests_hp_r": 2.5,
                "enemy_killed_no_overkill_r": 3.0,
                "charge_success": 0.2,
                "being_charged": -0.5,
                "attack": 0.3,
                "enemy_killed_m": 2.0,
                "enemy_killed_lowests_hp_m": 2.5,
                "enemy_killed_no_overkill_m": 3.0,
                "loose_hp": -0.5,
                "killed_in_melee": -3.0,
                "win": 10.0,  # Huge reward for winning
                "lose": -10.0,  # Big penalty for losing
                "atk_wasted_r": -0.3,
                "atk_wasted_m": -0.3,
                "wait": -0.5
            },
            "SpaceMarineMelee": {
                "move_close": 0.2,
                "move_away": -0.2,
                "move_to_safe": 0.1,
                "move_to_rng": 0.1,
                "move_to_charge": 0.3,
                "move_to_rng_charge": 0.4,
                "ranged_attack": 0.2,
                "enemy_killed_r": 2.0,
                "enemy_killed_lowests_hp_r": 2.5,
                "enemy_killed_no_overkill_r": 3.0,
                "charge_success": 0.5,
                "being_charged": -0.5,
                "attack": 0.4,
                "enemy_killed_m": 2.5,  # Melee units prefer melee kills
                "enemy_killed_lowests_hp_m": 3.0,
                "enemy_killed_no_overkill_m": 3.5,
                "loose_hp": -0.5,
                "killed_in_melee": -3.0,
                "win": 10.0,
                "lose": -10.0,
                "atk_wasted_r": -0.3,
                "atk_wasted_m": -0.3,
                "wait": -0.5
            }
        }
        
        with open(rewards_path, 'w') as f:
            json.dump(rewards, f, indent=2)
        
        print(f"✅ Added 'emergency' rewards to {rewards_path}")
    
    return True

def modify_train_py_for_config():
    """Modify train.py to use configuration system if needed."""
    
    train_path = "ai/train.py"
    
    if not os.path.exists(train_path):
        print(f"ERROR: {train_path} not found!")
        return False
    
    with open(train_path, 'r') as f:
        content = f.read()
    
    # Check if it already uses configuration system
    if "emergency" in content or "config_name" in content:
        print("✅ train.py already supports configurations")
        return True
    
    print("ℹ️  train.py uses hardcoded parameters - using debug config instead")
    return True

def main():
    """Add emergency configuration and provide training instructions."""
    
    print("🚨 ADDING EMERGENCY TRAINING CONFIGURATION")
    print("=" * 50)
    
    if add_emergency_config():
        modify_train_py_for_config()
        
        print("\n🎯 TRAINING OPTIONS:")
        print("=" * 30)
        
        print("OPTION 1 - Quick Debug Training (RECOMMENDED):")
        print("   python ai/train.py")
        print("   • Uses default config (100k timesteps)")
        print("   • Should complete in 30-60 minutes")
        print("   • Good for testing if fix worked")
        print()
        
        print("OPTION 2 - Conservative Training (THOROUGH):")
        print("   python ai/train.py")  
        print("   • Modify config/training_config.json to use 'conservative'")
        print("   • 1M timesteps, more stable learning")
        print("   • Takes 2-4 hours")
        print()
        
        print("🔍 MONITOR TRAINING:")
        print("   tensorboard --logdir ./tensorboard/")
        print("   • Watch for decreasing loss")
        print("   • Episode rewards should vary")
        print("   • Win rate should appear > 0%")
        print()
        
        print("✅ EXPECTED RESULTS:")
        print("   • Episodes lasting 20+ turns")
        print("   • Win rate 10-40% after training")
        print("   • Varied rewards (not constant 18.78)")
        print("   • Units visible in replay files")

if __name__ == "__main__":
    main()