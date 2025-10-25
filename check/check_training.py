from tensorboard.backend.event_processing import event_accumulator

event_file = "tensorboard/SpaceMarine_Infantry_Troop_RangedSwarm/events.out.tfevents.1760863664.MSI.21188.0"

ea = event_accumulator.EventAccumulator(event_file)
ea.Reload()

print("📊 TRAINING ANALYSIS:\n")

# 1. Episode Rewards
if 'episode/reward' in ea.Tags()['scalars']:
    rewards = ea.Scalars('episode/reward')
    print(f"Episode Rewards:")
    print(f"  First reward: {rewards[0].value:.2f}")
    print(f"  Last reward: {rewards[-1].value:.2f}")
    print(f"  Total episodes: {len(rewards)}")
    print()

# 2. Win Rate
if 'episode/win_rate' in ea.Tags()['scalars']:
    win_rate = ea.Scalars('episode/win_rate')
    print(f"Win Rate:")
    print(f"  Final win rate: {win_rate[-1].value:.2%}")
    print()

# 3. CRITICAL: Invalid Action Rate
if 'ai_turn/invalid_action_rate' in ea.Tags()['scalars']:
    invalid_rate = ea.Scalars('ai_turn/invalid_action_rate')
    print(f"❌ Invalid Action Rate:")
    print(f"  Final rate: {invalid_rate[-1].value:.2%}")
    print()

# 4. Action Efficiency
if 'AI_Quality/Action_Efficiency' in ea.Tags()['scalars']:
    efficiency = ea.Scalars('AI_Quality/Action_Efficiency')
    print(f"Action Efficiency:")
    print(f"  Final efficiency: {efficiency[-1].value:.2%}")
    print()

# 5. CRITICAL: Shooting Stats
if 'Combat/Shots_Fired' in ea.Tags()['scalars']:
    shots_fired = ea.Scalars('Combat/Shots_Fired')
    print(f"🎯 Combat Stats:")
    print(f"  Total shots fired: {shots_fired[-1].value:.0f}")
    
if 'Combat/Shots_Hit' in ea.Tags()['scalars']:
    shots_hit = ea.Scalars('Combat/Shots_Hit')
    print(f"  Total shots hit: {shots_hit[-1].value:.0f}")
    
if 'Combat/Shooting_Accuracy' in ea.Tags()['scalars']:
    accuracy = ea.Scalars('Combat/Shooting_Accuracy')
    print(f"  Shooting accuracy: {accuracy[-1].value:.2%}")