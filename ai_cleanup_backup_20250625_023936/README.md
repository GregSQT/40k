# AI Training Scripts

## Main Scripts

- train.py - Main training script (uses config defaults)
- test.py - Main testing script
- config_loader.py - Configuration management

## Usage

```bash
# Simple training with defaults
python ai/train.py

# Force new model
python ai/train.py --new

# Continue existing model
python ai/train.py --append

# Test model
python ai/test.py
```

## Configurations

All configurations are in ../config/:
- scenarios.json - Game scenarios
- training_config.json - Training parameters  
- rewards_config.json - Reward configurations

## Monitoring

```bash
tensorboard --logdir ../tensorboard/
```
