## Critical PPO Parameters

"n_steps": 2048        # Collect 2048 steps before policy update
                       # Higher = more stable, slower updates
                       # Your episodes ~250 steps, so 8 episodes per update

"batch_size": 64       # Mini-batch size for gradient updates
                       # Must divide n_steps evenly
                       # 64 is good balance for your observation size

"n_epochs": 10         # How many times to reuse collected data
                       # Higher = more learning per sample
                       # 10 is standard for discrete actions

"gamma": 0.99          # Discount factor for future rewards
                       # 0.99 = plan ~100 steps ahead
                       # Good for your multi-turn tactical game

"gae_lambda": 0.95     # GAE for advantage estimation
                       # 0.95 = smooth credit assignment
                       # Critical for delayed rewards

"clip_range": 0.2      # PPO policy clipping
                       # Prevents too-large policy updates
                       # 0.2 is standard, stable value

"ent_coef": 0.01       # Entropy bonus for exploration
                       # 0.01 = moderate exploration
                       # Decrease to 0.005 after 50K steps for exploitation

"vf_coef": 0.5         # Value function loss weight
                       # 0.5 balances policy and value learning

"max_grad_norm": 0.5   # Gradient clipping for stability
                       # Prevents exploding gradients


## Network Architecture

"policy_kwargs": {
    "net_arch": [256, 256]  # Two hidden layers, 256 neurons each
}

### For complex tactics, use deeper network:
"policy_kwargs": {
    "net_arch": [512, 512, 256]  # Three layers for aggressive config
}