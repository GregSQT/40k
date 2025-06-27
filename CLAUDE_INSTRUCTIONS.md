# Claude Development Requirements - ALWAYS FOLLOW

## Core Environment
- PowerShell for prompts, TypeScript/React for scripts
- Always answer in English
- Use ai\event_log\train_best_game_replay.json for replay checking
- French Windows version compatibility

## Code Standards
- Never change variable names
- Never remove code features still in use
- Never provide "simple" versions - always full implementation
- Always include script path/name as first line comment
- Provide target scripts directly, not PowerShell creation scripts
- Show 3 lines before/after when updating an existing scripts

## Error Handling
- Raise errors for missing files/data - never create defaults
- Fix ALL errors at once when error messages provided

## Configuration Usage
- Use same board display as game feature for the replay feature
- Use existing config files for board/units/rewards
- Never hardcode values already defined in config files
- Always search project knowledge FIRST before other tools

## AI Training Instructions
- Always use config_loader.py for training configurations - never hardcode training parameters
- Reference config/training_config.json for model parameters (learning rates, buffer sizes, etc.)
- Reference config/rewards_config.json for reward system configurations
- Use train.py as the main training script, not variants
- Use evaluation.py as the main evaluation script, not variants
- When suggesting training changes, modify config files, not script parameters
- Always check tensorboard logs at ./tensorboard/ for training monitoring
- Use debug config for quick testing (50k timesteps), default for production

## File System Rules
- AI scripts always run from project root directory, not ai/ subdirectory
- Frontend components use /ai/ prefix for public file access
- Config files are in config/ directory, not ai/config/
- Event logs go to ai/event_log/ directory
- Model files save to ai/model.zip (never change this path)
- Tensorboard logs to ./tensorboard/ from root

## Code Quality Requirements
- Use TypeScript strict mode - no 'any' types unless absolutely necessary
- Add proper error boundaries in React components
- Include loading states for all async operations
- Use proper PIXI.js cleanup (removeChildren, destroy) to prevent memory leaks
- Validate all JSON data before use - check for required properties
- Use consistent naming: camelCase for JS/TS, snake_case for Python

## Testing Standards
- Always test AI model loading before training modifications
- Validate scenario.json format before environment creation
- Test replay viewer with actual replay files, not mock data
- Check config file changes with both original and modified parameters
- Verify unit registry consistency between frontend and AI

## Common Error Patterns to Fix
- Missing imports from gym40k environment
- Incorrect file paths (ai/ prefix vs relative paths)
- Unit registry mismatches between frontend and AI
- Scenario.json format inconsistencies
- Reward system parameter misalignment
- Model loading/saving path conflicts

## Common Error Patterns to Fix
- Missing imports from gym40k environment
- Incorrect file paths (ai/ prefix vs relative paths)
- Unit registry mismatches between frontend and AI
- Scenario.json format inconsistencies
- Reward system parameter misalignment
- Model loading/saving path conflicts