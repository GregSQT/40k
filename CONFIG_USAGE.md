# W40K AI Configuration System - Usage Examples

## Quick Start

### 1. Use default optimized settings:
```bash
python train_ai_config.py
```

### 2. Use your original parameters with original rewards:
```bash
python train_ai_config.py --training-config original --rewards-config original
```

### 3. Try conservative settings with balanced rewards:
```bash
python train_ai_config.py --training-config conservative --rewards-config balanced
```

### 4. Quick debug training:
```bash
python train_ai_config.py --training-config debug --rewards-config simplified
```

### 5. Resume training with different rewards:
```bash
python train_ai_config.py --resume --rewards-config balanced
```

## Configuration Details

### Training Configurations:
- **default**: Optimized parameters for complex reward learning
- **original**: Your original parameters from train.py  
- **conservative**: Moderate increase from original
- **aggressive**: Fast learning with large buffers
- **debug**: Quick training for testing

### Reward Configurations:
- **original**: Your sophisticated tactical reward system
- **simplified**: Simpler rewards for faster learning
- **balanced**: Intermediate complexity with extra feedback

## Customizing Configurations

### Edit training parameters:
```bash
nano config/training_config.json
```

### Edit reward values:
```bash
nano config/rewards_config.json
```

### Apply rewards without training:
```python
from config_loader import ConfigLoader
loader = ConfigLoader()
loader.apply_rewards_to_file("original")
```

## Monitoring Training

```bash
# Start tensorboard
tensorboard --logdir ./tensorboard/

# Test trained model
python test_ai.py
```

## Experimentation Workflow

1. **Start with simplified rewards** for initial learning
2. **Use debug config** for quick testing (50k timesteps)
3. **Switch to balanced rewards** once learning
4. **Use original rewards** for final sophisticated training
5. **Monitor win rates** and adjust accordingly

## Parameter Tuning Tips

- **Higher learning_starts** = more exploration before learning
- **Larger buffer_size** = more diverse experience replay  
- **Smaller learning_rate** = more stable but slower learning
- **Larger batch_size** = more stable gradients
- **Lower exploration_fraction** = less random exploration
