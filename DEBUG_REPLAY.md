# 🎬 W40K Replay Architecture - Quick Reference

## 📋 CORE COMPONENTS

### Backend (Python)
- **GameReplayLogger** (`ai/game_replay_logger.py`) - Main capture system
- **GameReplayIntegration** - Training environment integration
- **Shared Log Structure** (`shared/gameLogStructure.py`) - Unified format

### Frontend (TypeScript)
- **ReplayPage.tsx** - Main replay viewer component
- **BoardReplay.tsx** - PIXI.js replay board renderer
- **Replay Types** (`frontend/src/types/replay.ts`) - Type definitions

---

# 🔄 DATA FLOW

```
Training Episode → GameReplayLogger → JSON File → Frontend Viewer
     ↓               ↓                   ↓           ↓
  AI Actions     Dice Details      Enhanced Format  Visual Replay
```

---

# 📁 FILE FORMAT

## Detailed Dice Tracking Structure
```json
"shoot_details": [
  {
    "shotNumber": 1,
    "attackRoll": 4,           // Actual dice roll (1-6)
    "hitResult": "HIT",        // "HIT" or "MISS"
    "hitTarget": 3,            // Target number needed
    "strengthRoll": 5,         // Wound dice roll
    "strengthResult": "SUCCESS", // "SUCCESS" or "FAILED" 
    "woundTarget": 4,          // Wound target number
    "saveRoll": 2,             // Save dice roll
    "saveTarget": 4,           // Save target number
    "saveSuccess": false,      // Save succeeded?
    "damageDealt": 1           // Final damage dealt
  }
]
```

## Frontend Consumption
- **Direct Loading**: React components load JSON files directly
- **Type Safety**: Full TypeScript interfaces for all replay data
- **PIXI.js Rendering**: Hardware-accelerated visual replay
- **Replay Viewer**: `/replay` route with episode selection dropdown
```

---

# ⚙️ INTEGRATION POINTS

## Training Integration
```python
# Add to training environment
env = GameReplayIntegration.enhance_training_env(env)

# Save episode replay
GameReplayIntegration.save_episode_replay(env, episode_reward)
```

## Evaluation Mode Detection
- **Multiple Flag Check**: `is_evaluation_mode` OR `_force_evaluation_mode` OR `env.is_evaluation_mode`
- **Training Skip**: Returns early from logging methods if not in evaluation mode
- **Performance**: Zero logging overhead during training episodes

## File Structure & Naming
```python
# Evaluation replay files (3 per evaluation session)
"ai/event_log/eval_best_episode.json"
"ai/event_log/eval_worst_episode.json"  
"ai/event_log/eval_shortest_episode.json"

# Training replay files (if any - usually disabled)
"ai/event_log/game_replay.json"
```

## Critical Implementation Details
- **Field Names**: ALL uppercase (RNG_ATK, ARMOR_SAVE, CC_STR) - lowercase causes KeyError
- **Controller Integration**: `env.controller.game_state["current_turn"]` for turn access
- **State Tracking**: Must use `controller.get_units()` not direct env access
- **JSON Format**: "format_version": "2.0" for enhanced replays with dice details

---

# ⏱️ EPISODE & TURN MANAGEMENT

## Episode Lifecycle
- **Episode Start**: Beginning of first Player 0 turn (movement phase)
- **Episode End**: Player has no active units OR max steps reached
- **Turn Numbering**: Turn 1 = first P0 movement phase, increments at each P0 movement phase start

## Turn Progression
```
Turn 1: P0 Move → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
Turn 2: P0 Move (Turn++ here) → P0 Shoot → P0 Charge → P0 Combat → P1 Move → P1 Shoot → P1 Charge → P1 Combat
Turn 3: P0 Move (Turn++ here) → ...
```

---

# 🏆 EVALUATION & REPLAY SELECTION

## Post-Training Evaluation
- **Timing**: Replays captured ONLY during evaluation phase (after training)
- **Selection Process**: Best, worst, and shortest episodes identified during evaluation
- **Storage**: Three separate replay files saved per evaluation session

## Episode Selection Criteria
- **BEST**: Episode with highest total reward
- **WORST**: Episode with lowest total reward  
- **SHORTEST**: Episode with fewest total steps

## Single Episode Focus
- **One Replay = One Episode**: Each replay file contains exactly one complete episode
- **No Multi-Episode**: No aggregation or multiple episodes per file
- **Complete Coverage**: Full episode from start to finish with all actions

---

# 🎯 KEY FEATURES

- ✅ **Complete Dice Tracking** - Every roll captured with targets
- ✅ **Evaluation-Only Capture** - No training performance impact
- ✅ **Frontend Ready** - Direct React/PIXI.js consumption  
- ✅ **Turn Management** - Proper P0-based turn incrementing
- ✅ **Selective Episodes** - Best/worst/shortest episode identification
- ✅ **Uppercase Fields** - Consistent ARMOR_SAVE, CC_STR naming
- ✅ **Enhanced Format** - Version 2.0 with detailed combat data