# test_training_config.py
def verify_training_config():
    """Verify training config suitable for presentation timeline"""
    
    from config_loader import get_config_loader
    config = get_config_loader()
    
    # Load debug config for testing
    debug_config = config.load_training_config("debug")
    print("Debug config:")
    for key, value in debug_config.items():
        print(f"  {key}: {value}")
    
    # Verify reasonable episode length for 5-day deadline
    max_episodes = debug_config.get("total_episodes", 0)
    max_turns = debug_config.get("max_turns_per_episode", 0)
    
    print(f"\nTraining scope:")
    print(f"  Episodes: {max_episodes}")
    print(f"  Max turns per episode: {max_turns}")
    
    # Quick training should complete in < 30 minutes for presentation prep
    estimated_minutes = max_episodes * max_turns * 0.1  # Rough estimate
    print(f"  Estimated training time: {estimated_minutes:.1f} minutes")
    
    if estimated_minutes > 60:
        print("⚠️  WARNING: Training might take too long for 5-day deadline")
    else:
        print("✅ Training duration suitable for deadline")

if __name__ == "__main__":
    verify_training_config()