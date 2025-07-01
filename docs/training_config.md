# Training Configuration Documentation

## Parameter Explanations

### Training Duration & Episode Control

| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `total_timesteps` | Total number of environment steps to train for | 100k-2M (1M = substantial learning) |
| `max_steps_per_episode` | Maximum steps before episode is truncated | 50-200 (prevents infinite games) |
| `eval_freq` | How often to evaluate model performance | 1k-10k (balance monitoring vs training time) |

### Callback Parameters

| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `eval_deterministic` | Use deterministic policy during evaluation | `true` (no random exploration during eval) |
| `eval_render` | Render visual output during evaluation | `false` (faster evaluation) |
| `n_eval_episodes` | Number of episodes to run per evaluation | 3-10 (statistical reliability vs speed) |
| `checkpoint_save_freq` | Save model checkpoint frequency | 10k-50k steps |
| `checkpoint_name_prefix` | Filename prefix for saved checkpoints | String for organization |

### Model Parameters

#### Neural Network Architecture
| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `policy` | Neural network architecture type | `"MlpPolicy"` (fully-connected layers) |
| `verbose` | Logging level during training | 0=silent, 1=info, 2=debug |

#### Experience Replay Settings
| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `buffer_size` | Size of replay buffer (stores past experiences) | 10k-200k (more = diverse experiences) |
| `learning_starts` | Steps of pure exploration before learning begins | 1k-10k (fills buffer first) |
| `batch_size` | Number of experiences sampled per learning update | 32, 64, 128, 256 (powers of 2 for GPU efficiency) |

#### Learning Control
| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `learning_rate` | How fast the neural network learns | 0.0001-0.01 (lower = stable, higher = faster) |
| `train_freq` | Learn from replay buffer every N steps | 1-8 (lower = more frequent learning) |
| `target_update_interval` | How often to update target network | 500-2000 (DQN stability mechanism) |

#### Exploration Strategy
| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `exploration_fraction` | Fraction of training with decaying exploration | 0.1-0.5 (portion of training to explore) |
| `exploration_final_eps` | Final exploration rate after decay | 0.01-0.1 (% random actions at end) |

#### Monitoring
| Parameter | Purpose | Typical Values |
|-----------|---------|----------------|
| `tensorboard_log` | Directory to save training metrics | `"./tensorboard/"` |

## Key Relationships

- **Buffer Fill**: `buffer_size` > `learning_starts` ensures diverse experiences before learning
- **Evaluation Frequency**: `eval_freq` < `total_timesteps` allows multiple evaluations during training
- **Exploration Decay**: `exploration_fraction` × `total_timesteps` = steps of exploration decay
- **Checkpointing**: `checkpoint_save_freq` < `total_timesteps` creates multiple save points
- **Batch Efficiency**: `batch_size` should be power of 2 for GPU efficiency

## Configuration Profiles

### Quick Testing
- `total_timesteps`: 10k-50k
- `learning_starts`: 1k
- `buffer_size`: 10k
- High exploration for rapid discovery

### Balanced Learning
- `total_timesteps`: 100k-500k
- `learning_starts`: 2k-5k
- `buffer_size`: 25k-50k
- Moderate exploration with stable learning

### Deep Training
- `total_timesteps`: 1M-2M
- `learning_starts`: 5k-10k
- `buffer_size`: 100k-200k
- Conservative exploration for refined policies

## Troubleshooting

### Common Issues
- **No learning**: Check `learning_starts` < `total_timesteps`
- **Unstable training**: Reduce `learning_rate`, increase `target_update_interval`
- **Slow convergence**: Increase `train_freq`, decrease `exploration_final_eps`
- **Memory issues**: Reduce `buffer_size`, `batch_size`

### Performance Tuning
- **Faster training**: Increase `train_freq`, reduce `eval_freq`
- **More stable**: Increase `target_update_interval`, reduce `learning_rate`
- **Better exploration**: Increase `exploration_fraction`, `exploration_final_eps`