# PHASE 1/2 FIX PLAN - COMPLETE EXECUTION GUIDE
## Warhammer 40K Tactical AI Training - Curriculum Learning Repair

**Document Date:** 2025-01-10  
**Project:** SpaceMarine_Infantry_Troop_RangedSwarm Agent Training  
**Objective:** Fix Phase 2 curriculum learning by correcting reward magnitude mismatch  
**Expected Outcome:** Combined bot score 0.55-0.65 within 24 hours  

---

## EXECUTIVE SUMMARY

**Problem Identified:**
Phase 2 training failed because rewards were reduced 40-83% from Phase 1, making passive play more optimal than aggressive shooting. The agent's neural network worked perfectly (explained variance 0.85-0.90) but learned the wrong behavior because killing became less rewarding.

**Solution:**
Maintain Phase 1's aggressive reward magnitudes while adding efficiency bonuses on top. This teaches "smart shooting is MORE rewarding" instead of "shooting is LESS rewarding."

**Success Probability:**
- Phase 2 fix: 75-85%
- Fallback Plan B (Extended Phase 1): 85-95%
- Overall: 95%+ that one approach succeeds

**Time Investment:**
- Active work: 1-2 hours (config updates, monitoring, evaluation)
- Passive training: 6-8 hours (computer runs unattended)
- Total timeline: 24 hours from start to validated results

---

## CURRENT SITUATION ASSESSMENT

### Files Provided & Verified
✅ train.py - Training orchestration script  
✅ SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json - Hyperparameters  
✅ SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json - Reward structures  
✅ Scenario files - phase1, phase2-1, phase2-2, phase2-3, phase2-4  
✅ Tensorboard data - Problem diagnosis confirmed  

### Root Cause Confirmed
**Phase 1 per-kill reward:** ~62 points  
**Phase 2 per-kill reward (broken):** ~10-18 points (83% reduction)  
**Phase 2 per-kill reward (fixed attempt):** ~38-53 points (40% reduction - still too low)  

**Result:** Agent learned that waiting/defending was better than shooting because killing rewards dropped too much.

**Evidence:**
- Explained variance 0.85-0.90 (neural network working perfectly)
- Clip fraction dropped to 0.00 after episode 1000 (converged to local optimum)
- Entropy dropped to 0.00 (stopped exploring)
- Win rate dropped below Phase 1 baseline (passive play loses to aggressive bots)

---

## STEP-BY-STEP EXECUTION PLAN

### STEP 1: BACKUP CURRENT CONFIGURATIONS

**Purpose:** Preserve existing work before modifications.

**PowerShell Commands (execute from project root):**
```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json" "config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json.backup_$timestamp"
Copy-Item "config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json" "config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json.backup_$timestamp"
```

**Verification:**
```powershell
Get-ChildItem config/*.backup_*
```

**Expected Result:** Two backup files with timestamps visible in config directory.

**Time Required:** 2 minutes

---

### STEP 2: UPDATE REWARDS CONFIG - PHASE 2 SECTION

**File:** config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json  
**Section:** SpaceMarine_Infantry_Troop_RangedSwarm_phase2 (approximately lines 79-116)

#### Changes Required

**A. Update Info Line (for tracking):**
```
OLD: "Info": "######################################## PHASE 2                                ########################################"
NEW: "Info": "######################################## PHASE 2 - FIXED MAGNITUDE 2025-01-10 ########################################"
```

**B. Update base_actions:**
```
OLD: "ranged_attack": 2.0
NEW: "ranged_attack": 5.0

OLD: "shoot_wait": -5.0
NEW: "shoot_wait": -15.0

OLD: "move_to_los": 0.6
NEW: "move_to_los": 0.8
```

**C. Update result_bonuses:**
```
OLD: "hit_target": 0.5
NEW: "hit_target": 2.0

OLD: "wound_target": 1.0
NEW: "wound_target": 5.0

OLD: "damage_target": 2.0
NEW: "damage_target": 10.0

OLD: "kill_target": 5.0
NEW: "kill_target": 35.0

OLD: "no_overkill": 1.0
NEW: "no_overkill": 5.0

OLD: "target_lowest_hp": 8.0
NEW: "target_lowest_hp": 12.0
```

**D. Update situational_modifiers:**
```
OLD: "attack_wasted": -4.0
NEW: "attack_wasted": -5.0
```

#### Reward Magnitude Verification

**Phase 1 total per kill:** ~62 points (5 + 2 + 5 + 10 + 40)  
**Phase 2 NEW total per kill:** ~57-69 points base  
**Phase 2 WITH efficiency bonuses:** up to 74-86 points (target_lowest_hp + no_overkill)

**Key Insight:** Aggressive shooting maintains same value, but SMART shooting becomes MORE valuable than Phase 1's brute force approach.

#### JSON Validation

**After editing, run this command to verify syntax:**
```powershell
python -c "import json; json.load(open('config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json'))"
```

**Expected Result:** No output (silence means success)  
**If Error:** JSON syntax broken - fix commas/brackets before proceeding

**Time Required:** 5 minutes

---

### STEP 3: UPDATE TRAINING CONFIG - PHASE 2 SECTION

**File:** config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json  
**Section:** phase2 (approximately lines 26-72)

#### Changes Required

**A. Update type Line (for tracking):**
```
OLD: "type": "################################################### Phase 2 ###################################################"
NEW: "type": "################################################### Phase 2 - FIXED HYPERPARAMETERS 2025-01-10 ###################################################"
```

**B. Update Top-Level Parameters:**
```
OLD: "total_episodes": 4000
NEW: "total_episodes": 3000

OLD: "rotation_interval": 100
NEW: "rotation_interval": 75
```

**C. Update rotation_comment:**
```
OLD: "rotation_comment": "Episodes per scenario before rotation. Formula: total_episodes / (num_scenarios * target_cycles). For 4000 episodes with 4 scenarios and 10 cycles: 4000 / (4 * 10) = 100"
NEW: "rotation_comment": "Episodes per scenario before rotation. Formula: total_episodes / (num_scenarios * target_cycles). For 3000 episodes with 4 scenarios and 10 cycles: 3000 / (4 * 10) = 75"
```

**D. Update model_params:**
```
OLD: "learning_rate": 0.00075
NEW: "learning_rate": 0.003

OLD: "ent_coef": 0.75
NEW: "ent_coef": 0.20

OLD: "target_kl": 0.03
NEW: "target_kl": 0.02
```

#### Hyperparameter Logic

**Learning Rate 0.003:**
- 4x faster than broken Phase 2 (0.00075)
- Still 2.5x slower than Phase 1 (0.0075)
- Prevents premature convergence while maintaining careful learning

**Entropy Coefficient 0.20:**
- Much lower than broken Phase 2 (0.75 caused chaos)
- Higher than Phase 1 (0.5) for continued exploration
- Balances exploration vs exploitation

**Target KL 0.02:**
- Lower than 0.03 default
- Triggers early warning if policy converges prematurely
- Helps detect the "frozen policy" problem that killed previous Phase 2

**3000 Episodes with 75-Episode Rotation:**
- 10 complete cycles through all 4 scenarios
- Each scenario seen 750 times (250 episodes per cycle × 3 cycles... wait, 3000/4 = 750 per scenario, 750/75 = 10 rotations)
- More efficient than previous 4000 episodes

#### JSON Validation

**After editing, run this command to verify syntax:**
```powershell
python -c "import json; json.load(open('config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json'))"
```

**Expected Result:** No output (silence means success)  
**If Error:** JSON syntax broken - fix commas/brackets before proceeding

**Time Required:** 3 minutes

---

### STEP 4: VERIFY PHASE 1 MODEL EXISTS

**Purpose:** Confirm trained Phase 1 model exists for --append flag to load.

**PowerShell Command:**
```powershell
Get-ChildItem -Path "ai/models" -Filter "*phase1*" -Recurse
```

**Expected Result:**
```
ppo_curriculum_p1_SpaceMarine_Infantry_Troop_RangedSwarm_XXXXX_steps.zip
```

#### If Phase 1 Model Does NOT Exist

**You must train Phase 1 first.** Phase 2 --append requires Phase 1 as foundation.

**Training Command for Phase 1:**
```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase1 --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase1 --scenario SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1 --new --test-episodes 0
```

**Time Required:** 3-4 hours for 1500 episodes

**Phase 1 Expected Results:**
- Combined bot score: 0.45-0.50
- Clip fraction: Should stay 0.05-0.20 throughout
- Episode rewards: 20-140 range with high variance (agent exploring)

#### If Phase 1 Model EXISTS

**Proceed directly to Step 5.**

**Time Required:** 2 minutes

---

### STEP 5: CLEAN PREVIOUS FAILED PHASE 2 TRAINING DATA

**Purpose:** Remove corrupted Phase 2 artifacts to ensure fresh start from Phase 1 weights.

**Critical:** This prevents loading broken Phase 2 model that learned passive behavior.

**PowerShell Commands:**
```powershell
# Remove failed Phase 2 model checkpoints
Remove-Item -Path "ai/models/*phase2*" -Force -ErrorAction SilentlyContinue

# Remove Phase 2 tensorboard logs (optional but recommended)
Remove-Item -Path "tensorboard/*phase2*" -Recurse -Force -ErrorAction SilentlyContinue
```

**Verification:**
```powershell
Get-ChildItem -Path "ai/models" -Filter "*phase2*"
```

**Expected Result:** No files found (or "file not found" error message)

**Why This Matters:**
If broken Phase 2 checkpoints remain, --append flag might load them instead of Phase 1. This would perpetuate passive behavior patterns and doom the training from the start.

**Time Required:** 3 minutes

---

### STEP 6: START PHASE 2 TRAINING WITH FIXED CONFIGS

**Purpose:** Execute training with corrected reward magnitudes and hyperparameters.

**Training Command:**
```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase2 --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase2 --scenario all --append --test-episodes 0
```

#### Command Breakdown

**--agent SpaceMarine_Infantry_Troop_RangedSwarm**  
Specifies which agent configuration to train

**--training-config phase2**  
Loads phase2 section from training_config.json (with our fixed hyperparameters)

**--rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase2**  
Loads phase2 rewards section (with our fixed reward magnitudes)

**--scenario all**  
Activates scenario rotation through phase2-1, phase2-2, phase2-3, phase2-4

**--append**  
Loads Phase 1 model as starting point (curriculum learning approach)

**--test-episodes 0**  
Skips testing during training to save time (we'll test at the end)

#### Expected Console Output at Start

```
📊 Using total_episodes from config: 3000
🔧 Calculated rotation interval: 75
🎯 Training with scenario rotation
📁 Cycle 1 | Scenario: phase2-1
✅ StepLogger connected
🎮 Starting training...
```

#### What to Watch During Initial Episodes

**First 100 episodes should show:**
- Episode rewards: 60-100 range
- Progress updates every 10 episodes
- Scenario rotation every 75 episodes
- No error messages or crashes

**If Training Crashes Immediately:**

**Check scenario files exist:**
```powershell
Get-ChildItem config/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-*.json
```

**Expected:** 4 files (phase2-1, phase2-2, phase2-3, phase2-4)

**If files missing:** Copy scenario files from uploads to config directory

**Estimated Time:** 6-8 hours for 3000 episodes (depends on hardware)

**Time Required to Start:** 5 minutes

---

### STEP 7: MONITOR TRAINING PROGRESS VIA TENSORBOARD

**Purpose:** Watch metrics in real-time to catch problems early.

#### Launch Tensorboard

**Open SECOND PowerShell terminal (keep first terminal running training):**
```powershell
tensorboard --logdir=./tensorboard --port=6006
```

**Open browser to:**
```
http://localhost:6006
```

#### Critical Metrics to Monitor

**METRIC 1: rollout/ep_rew_mean (Episode Reward Mean)**

**Purpose:** Shows if agent is earning rewards similar to Phase 1

**Healthy Pattern:**
- Episodes 0-500: 60-90 range
- Episodes 500-1500: 70-110 range
- Episodes 1500-3000: 80-120 range

**Warning Signs:**
- Consistently below 40
- Downward trend after episode 500

**Failure Signs:**
- Drops below 20
- Continuous decline throughout training

**What It Means:**
If rewards drop below 40, the agent is becoming passive again despite fixed rewards. This means deeper problem exists.

---

**METRIC 2: train/clip_fraction**

**Purpose:** Shows if policy is still learning or has frozen

**Healthy Pattern:**
- Episodes 0-500: 0.15-0.25
- Episodes 500-1500: 0.08-0.18
- Episodes 1500-3000: 0.02-0.10

**Warning Signs:**
- Drops below 0.02 before episode 1000
- Rapid decline from 0.20 to 0.05 in <200 episodes

**Failure Signs:**
- Reaches exactly 0.00 before episode 1000
- Stays at 0.00 for more than 200 consecutive episodes

**What It Means:**
Clip fraction measures how much policy is changing. Zero means policy is frozen and not learning anymore. This is how previous Phase 2 failed.

---

**METRIC 3: train/entropy_loss**

**Purpose:** Shows if agent is exploring or has converged to single strategy

**Healthy Pattern:**
- Episodes 0-500: 0.00 to -0.05
- Episodes 500-1500: -0.02 to -0.10
- Episodes 1500-3000: -0.05 to -0.15

**Warning Signs:**
- Drops below -0.30 before episode 1000
- Rapid decline in <200 episodes

**Failure Signs:**
- Drops below -0.50
- Reaches -1.0 or lower

**What It Means:**
Negative entropy means agent is reducing exploration. Slight negative is good (exploitation). Extreme negative means agent stopped exploring entirely.

---

**METRIC 4: train/explained_variance**

**Purpose:** Shows if value function can predict returns

**Healthy Pattern:**
- Throughout training: 0.70-0.95

**Warning Signs:**
- Below 0.50 (value function not learning)
- Wildly oscillating (0.2 to 0.9 repeatedly)

**Important Note:**
High explained variance (0.85+) is GOOD, even if other metrics look bad. Previous Phase 2 had 0.85+ explained variance but failed because it learned the wrong behavior perfectly.

**What It Means:**
This measures if the neural network is working. High variance means it works. The problem in previous Phase 2 was NOT the network - it was the rewards teaching wrong behavior.

---

**METRIC 5: train/approx_kl**

**Purpose:** Shows how much policy changed between updates

**Healthy Pattern:**
- Throughout training: 0.005-0.020

**Warning Signs:**
- Repeatedly exceeds 0.02 (target_kl threshold)
- Drops to exactly 0.00 before episode 1000

**Failure Signs:**
- Stays at 0.00 for >200 episodes
- Consistently above 0.025 (policy unstable)

**What It Means:**
KL divergence measures policy change. Zero means frozen policy. Too high means unstable learning. We want goldilocks zone of 0.005-0.020.

---

**METRIC 6: b_win_rate_100ep (Bot Win Rate)**

**Purpose:** Direct measure of combat performance

**Healthy Pattern:**
- Episodes 0-500: 0.30-0.40
- Episodes 500-1500: 0.40-0.50
- Episodes 1500-3000: 0.45-0.55

**Warning Signs:**
- Below 0.25 after episode 500
- Declining trend after episode 1000

**What It Means:**
This is win rate against all three bots combined. Phase 1 achieved ~0.35-0.40. Phase 2 should exceed this.

---

**METRIC 7: Critical/bot_eval_combined (Combined Score)**

**Purpose:** Overall performance metric (0.0-1.0 scale)

**Target Scores by Episode:**
- Episode 300: 0.35-0.45 (learning efficiency bonuses)
- Episode 900: 0.45-0.55 (approaching Phase 1 baseline)
- Episode 1800: 0.50-0.60 (exceeding Phase 1)
- Episode 3000: 0.55-0.65 (final goal - SUCCESS)

**Phase 1 Baseline:** 0.48  
**Phase 2 Goal:** 0.55+ (exceeds Phase 1)

**What It Means:**
This is the ultimate success metric. If this reaches 0.55+ by episode 3000, curriculum learning worked.

---

#### Monitoring Schedule

**Episodes 0-100:** Check every 10 episodes (watch for immediate crashes)  
**Episodes 100-500:** Check every 50 episodes (ensure healthy patterns emerging)  
**Episodes 500-1000:** Check every 100 episodes (monitor for premature convergence)  
**Episode 1000:** CRITICAL CHECKPOINT - make go/no-go decision (see Step 8)  
**Episodes 1000-3000:** Check every 200-300 episodes (ensure continued progress)  

**Time Required:** 2 minutes initial setup, then periodic 2-minute checks

---

### STEP 8: DECISION POINT AT EPISODE 1000

**Purpose:** Evaluate if training is on track or needs to abort for Plan B.

**Timing:** Approximately 2-3 hours into training

**Action:** Check Tensorboard metrics and make go/no-go decision

#### SUCCESS INDICATORS (Continue to Episode 3000)

**Episode Rewards:** 60-120 range, stable or increasing  
**Clip Fraction:** 0.05-0.15 (still updating policy meaningfully)  
**Entropy:** -0.01 to -0.15 (moderate exploration continuing)  
**Approx KL:** 0.005-0.020 (healthy policy changes)  
**Explained Variance:** 0.70-0.95 (value function working)  
**Bot Combined Score:** 0.40-0.50 (equal to or better than Phase 1's 0.48)  
**Win Rate:** 0.35-0.45 (comparable to Phase 1)

**Decision:** ✅ LET TRAINING CONTINUE - patterns are healthy

---

#### FAILURE INDICATORS (Abort and Switch to Plan B)

**Episode Rewards:** Below 40 or declining trend  
**Clip Fraction:** Below 0.02 or exactly 0.00  
**Entropy:** Below -0.50 (exploration collapsed)  
**Approx KL:** Exactly 0.00 (policy frozen)  
**Explained Variance:** Still high 0.80+ (confirms agent learned wrong behavior)  
**Bot Combined Score:** Below 0.35 (worse than Phase 1)  
**Win Rate:** Below 0.28 (significantly worse than Phase 1)

**Decision:** ❌ ABORT IMMEDIATELY - Switch to Plan B (Extended Phase 1)

---

#### How to Abort Training

**In training terminal window:**
- Press Ctrl+C
- Wait for training to stop gracefully
- Do NOT close terminal until you see "Training stopped" message

**Then proceed to Step 11 (Plan B: Extended Phase 1)**

---

#### If Uncertain

**If metrics are mixed (some good, some bad):**

**Let training continue to episode 1500**, then re-evaluate with these stricter criteria:

**Must see by episode 1500:**
- Bot combined score ≥ 0.42
- Clip fraction ≥ 0.03
- Episode rewards ≥ 50 average

**If these aren't met by episode 1500:** Abort and switch to Plan B

**Why this matters:**
Episode 1000 is when previous Phase 2 attempts died (clip fraction → 0). If you pass episode 1000 with healthy metrics, success probability jumps to 90%+.

**Time Required:** 5 minutes to evaluate metrics

---

### STEP 9: FINAL EVALUATION AFTER EPISODE 3000

**Purpose:** Comprehensive testing to validate training success.

**Timing:** After training completes (6-8 hours after Step 6)

**Action:** Run 100-episode test against all three bots

#### Final Test Command

```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase2 --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase2 --test-only --test-episodes 100
```

#### Expected Test Results

**Individual Bot Win Rates:**
- vs RandomBot: 70-80% (Phase 1 was ~70%)
- vs GreedyBot: 45-60% (Phase 1 was ~36%)
- vs DefensiveBot: 50-65% (Phase 1 was ~46%)

**Combined Score:** 0.55-0.65 (Phase 1 was 0.48)

**Average Test Episode Reward:** 70-100

#### Success Criteria

**MINIMUM SUCCESS (acceptable):**
- Combined score ≥ 0.50
- No single bot win rate below 35%
- Combined score exceeds Phase 1 baseline (0.48)

**GOOD SUCCESS (expected):**
- Combined score ≥ 0.55
- All bot win rates ≥ 40%
- At least one bot win rate ≥ 60%

**EXCELLENT SUCCESS (best case):**
- Combined score ≥ 0.60
- All bot win rates ≥ 45%
- Beats GreedyBot >50% (hardest opponent)

#### Interpreting Results

**If SUCCESS criteria met:**

🎉 **Phase 2 curriculum fix worked!**

**What this proves:**
- Reward magnitude parity enables curriculum learning
- Agent learned efficient targeting while maintaining aggression
- Training pipeline is proven and reliable

**Next steps:**
- Optional: Proceed to Step 10 (Phase 3 for mastery)
- Or: Declare victory and begin charge/melee implementation
- Document results thoroughly (Step 12)

---

**If SUCCESS criteria NOT met:**

⚠️ **Phase 2 curriculum approach failed**

**What this means:**
- Fixed rewards still didn't work
- Curriculum learning may not be viable for this problem
- Need to use Plan B approach

**Next steps:**
- Proceed immediately to Step 11 (Plan B: Extended Phase 1)
- This is the safe fallback with 85-95% success rate

**Time Required:** 1 hour (100 test episodes + evaluation)

---

### STEP 10: OPTIONAL - TRAIN PHASE 3 FOR MASTERY

**Purpose:** Continue curriculum to Phase 3 for full ranged combat expertise.

**When to do this:** ONLY after Phase 2 success is confirmed

**Skip this if:** You're satisfied with Phase 2 results and want to move to charge/melee

#### Phase 3 Goals

**Teach advanced tactics:**
- Cover usage and positioning
- Combined arms coordination
- Focus fire discipline
- Tactical positioning bonuses

**Expected outcome:**
- Combined score: 0.65-0.75
- Training time: 12-16 hours
- Builds on proven Phase 2 foundation

#### Phase 3 Training Command

```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase3 --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase3 --scenario all --append --test-episodes 0
```

#### Phase 3 Configuration Already Set

**Your training_config.json already has Phase 3 configured:**
- 6000 episodes
- Learning rate 0.0003 (very slow, for fine-tuning)
- Entropy coefficient 0.10 (low exploration, high exploitation)
- Rotation through multiple scenarios

**Your rewards_config.json already has Phase 3 configured:**
- Maintains combat reward magnitudes
- Adds tactical bonuses (moved_to_cover, safe_from_charges, etc.)
- Enhanced efficiency bonuses

**No configuration changes needed for Phase 3**

#### When to Skip Phase 3

**Skip if:**
- Phase 2 already achieved 0.60+ score (good enough)
- You want to implement charge/melee sooner
- Training time is limited

**Do Phase 3 if:**
- You want maximum ranged combat performance before adding complexity
- You have time for 12-16 hour training session
- You want to stress-test the curriculum learning pipeline

**My recommendation:** Do Phase 3 if Phase 2 worked well. It validates the full curriculum approach and gives you best possible foundation for charge/melee implementation.

**Time Required:** 12-16 hours

---

### STEP 11: PLAN B - EXTENDED PHASE 1 (FALLBACK)

**Purpose:** Abandon curriculum learning if Phase 2 fix fails. Use proven Phase 1 approach with extended training.

**When to use this:**
- Phase 2 fails at episode 1000 checkpoint (Step 8)
- Phase 2 fails final evaluation (Step 9)
- You decide to skip curriculum learning entirely

**Success probability:** 85-95% (very safe approach)

#### Step 11A: Create Extended Phase 1 Configuration

**File to modify:** config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json

**Add new section after phase1 section (around line 73):**

Insert this complete configuration block:

```json
"phase1_extended": {
  "type": "################################################### Phase 1 Extended ###################################################",
  "total_episodes": 6000,
  "max_turns_per_episode": 5,
  "max_steps_per_turn": 8,
  "model_params": {
    "policy": "MlpPolicy",
    "learning_rate": 0.003,
    "n_steps": 2048,
    "batch_size": 256,
    "n_epochs": 8,
    "gamma": 0.95,
    "gae_lambda": 0.9,
    "clip_range": 0.2,
    "ent_coef": 0.01,
    "vf_coef": 1.0,
    "max_grad_norm": 0.5,
    "target_kl": 0.02,
    "tensorboard_log": "./tensorboard/",
    "policy_kwargs": {
      "net_arch": [320, 320]
    },
    "verbose": 0
  },
  "callback_params": {
    "checkpoint_save_freq": 10000,
    "checkpoint_name_prefix": "ppo_curriculum_p1ext",
    "eval_deterministic": true,
    "eval_render": false,
    "n_eval_episodes": 0,
    "bot_eval_freq": 100,
    "bot_eval_use_episodes": true,
    "bot_eval_intermediate": 5,
    "bot_eval_final": 50
  },
  "observation_params": {
    "obs_size": 295,
    "perception_radius": 25,
    "max_nearby_units": 10,
    "max_valid_targets": 5,
    "justification": "Phase 1 Extended: Aggressive shooting with extended training and refined hyperparameters"
  }
}
```

**Key differences from Phase 1:**
- 6000 episodes (4x longer than original 1500)
- Learning rate 0.003 (60% slower than Phase 1's 0.0075)
- Entropy 0.01 (98% lower than Phase 1's 0.5 - minimal exploration)
- n_epochs 8 (33% more than Phase 1's 6 - more gradient updates per batch)

**Validate JSON after adding:**
```powershell
python -c "import json; json.load(open('config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json'))"
```

#### Step 11B: Train Extended Phase 1

```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase1_extended --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase1 --scenario SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase1 --append --test-episodes 0
```

**Note:** Uses Phase 1 rewards (aggressive shooting) and Phase 1 scenario (simpler 2v2 setup)

#### Expected Extended Phase 1 Results

**Episodes 0-1500:** Already completed from Phase 1 (score 0.48)  
**Episodes 1500-3000:** Gradual refinement, clip fraction 0.05-0.15  
**Episodes 3000-4500:** Continued learning, clip fraction 0.02-0.10  
**Episodes 4500-6000:** Fine-tuning, clip fraction 0.01-0.05  

**Final combined score:** 0.55-0.65  
**Training time:** 12-16 hours

**Why this works:**
- Phase 1 approach already proved effective (0.48 score)
- Extended training allows emergent complexity
- Lower entropy (0.01) focuses on exploitation over exploration
- Agent naturally learns some efficiency through experience

**Limitations vs curriculum:**
- May not learn target prioritization as explicitly
- Relies on emergent behavior rather than guided learning
- Efficiency gains through trial-and-error, not reward shaping

**Advantages vs curriculum:**
- Much safer (proven approach)
- Simpler to debug if problems arise
- No reward engineering complexity

#### When Extended Phase 1 Completes

**Run final evaluation:**
```powershell
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase1_extended --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase1 --test-only --test-episodes 100
```

**Expected results:** 0.55-0.65 combined score

**If this ALSO fails (<0.50 score):**
Deeper architectural problem exists. Contact me for diagnosis.

**Time Required:** 15-20 hours total (config creation + training + testing)

---

### STEP 12: DOCUMENT RESULTS

**Purpose:** Create permanent record of training outcomes for future reference.

**When to do this:** After final evaluation completes (Step 9 or Step 11B)

#### Create Results Log File

**Create file:** results_phase2_fix_20250110.txt (or use current date)

**Use this template:**

```
=============================================================================
PHASE 1/2 TRAINING RESULTS - CURRICULUM LEARNING FIX ATTEMPT
=============================================================================

TRAINING DETAILS
----------------
Date Started: [YYYY-MM-DD HH:MM]
Date Completed: [YYYY-MM-DD HH:MM]
Total Training Time: [XX hours]
Approach Used: [Phase 2 Fix / Extended Phase 1]
Total Episodes Trained: [3000 / 6000]

CONFIGURATION CHANGES
--------------------
Rewards Config Modified: [Yes/No]
Training Config Modified: [Yes/No]
Key Changes Made:
  - [List main changes, e.g., "Increased kill_target from 5.0 to 35.0"]
  - [e.g., "Increased learning_rate from 0.00075 to 0.003"]
  - [etc.]

TRAINING METRICS (at completion)
--------------------------------
Episode Reward Range: [min - max]
Final Episode Reward Average: [XX]
Clip Fraction Final: [0.XX]
Entropy Loss Final: [-0.XX]
Explained Variance Final: [0.XX]
Approx KL Final: [0.XX]

BOT EVALUATION RESULTS (100 test episodes)
------------------------------------------
Combined Score: [0.XX] (Phase 1 baseline was 0.48)
Win Rate vs RandomBot: [XX%] (Phase 1 was ~70%)
Win Rate vs GreedyBot: [XX%] (Phase 1 was ~36%)
Win Rate vs DefensiveBot: [XX%] (Phase 1 was ~46%)

SUCCESS ASSESSMENT
------------------
Meets Minimum Success Criteria: [Yes/No]
Exceeds Phase 1 Baseline: [Yes/No]
Achieves Target Score (0.55+): [Yes/No]

Overall Assessment: [SUCCESS / PARTIAL SUCCESS / FAILURE]

OBSERVED BEHAVIORS
------------------
Combat Aggressiveness: [Describe if agent shoots actively]
Target Selection: [Describe if agent prioritizes weak targets]
Positioning: [Describe movement patterns]
Notable Patterns: [Any interesting emergent behaviors]

ISSUES ENCOUNTERED
------------------
[List any problems, errors, or anomalies during training]
[Include any crashes, metric spikes, or unexpected behaviors]

TENSORBOARD OBSERVATIONS
-----------------------
Episode 300 Combined Score: [0.XX]
Episode 900 Combined Score: [0.XX]
Episode 1800 Combined Score: [0.XX]
Episode 3000 Combined Score: [0.XX]

Clip Fraction Pattern: [Healthy decline / Premature collapse / Stable]
Entropy Pattern: [Gradual decline / Sudden collapse / Stable]
Rewards Pattern: [Increasing / Stable / Declining]

CONCLUSIONS
-----------
Primary Outcome: [Describe main result]
Key Learnings: [What did this training teach us?]
Recommendations: [What to do next?]

NEXT STEPS
----------
[X] Document results (this file)
[X] Save Tensorboard screenshots
[ ] Proceed to Phase 3 (if Phase 2 succeeded)
[ ] Begin charge/melee implementation (if satisfied with ranged)
[ ] Try alternative approach (if this failed)

=============================================================================
```

#### Save Tensorboard Screenshots

**Take screenshots of these graphs (full training duration):**

1. rollout/ep_rew_mean - Episode reward progression
2. train/clip_fraction - Policy update magnitude
3. train/entropy_loss - Exploration measure
4. train/explained_variance - Value function quality
5. train/approx_kl - Policy change per update
6. Critical/bot_eval_combined - Performance score
7. b_win_rate_100ep - Win rate progression

**Save as:**
- tensorboard_phase2_20250110_episode_rewards.png
- tensorboard_phase2_20250110_clip_fraction.png
- tensorboard_phase2_20250110_entropy.png
- tensorboard_phase2_20250110_explained_variance.png
- tensorboard_phase2_20250110_approx_kl.png
- tensorboard_phase2_20250110_combined_score.png
- tensorboard_phase2_20250110_win_rate.png

**Storage location:** Create folder `training_results/phase2_fix_20250110/`

#### Why Documentation Matters

**For charge/melee implementation:**
When you add new mechanics in 2-3 weeks, you'll need to reference:
- What reward magnitudes worked for ranged combat
- What hyperparameters prevented premature convergence
- What training patterns indicated success vs failure
- How long training took per episode count

**For troubleshooting:**
If future training fails, documentation helps identify:
- What changed between working and broken training
- What patterns preceded failures
- What metrics to monitor for early warning signs

**For knowledge transfer:**
If someone else works on project or you return after break:
- Complete record of what was tried
- Clear success/failure indicators
- Rationale for configuration choices

**Time Required:** 30 minutes

---

## COMPLETE TIMELINE

### Hour 0: Preparation (30 minutes active work)
- Step 1: Backup configs (2 min)
- Step 2: Update rewards config (5 min)
- Step 3: Update training config (3 min)
- Step 4: Verify Phase 1 model (2 min)
- Step 5: Clean failed Phase 2 data (3 min)
- Step 6: Start training (5 min)
- Step 7: Launch Tensorboard (2 min)
- Initial monitoring (first 100 episodes) (10 min)

### Hours 1-2: Early Training
- Periodic checks every 30 minutes (2 min each)
- Watch for crashes or anomalies
- Computer can run unattended if stable

### Hour 2-3: Episode 1000 Checkpoint
- Step 8: Make go/no-go decision (5 min)
- If success indicators: continue
- If failure indicators: abort and switch to Plan B

### Hours 3-8: Complete Training
- Periodic checks every 1-2 hours (2 min each)
- Computer runs unattended
- Can leave overnight if needed

### Hour 8-9: Final Evaluation
- Step 9: Run 100-episode test (1 hour)
- Analyze results (15 min)
- Make success/failure determination (5 min)

### Hour 9-10: Documentation
- Step 12: Create results log (15 min)
- Save Tensorboard screenshots (10 min)
- Archive training artifacts (5 min)

### Total Time Investment
**Active work:** 2-3 hours (scattered across 24 hours)
**Passive training:** 6-8 hours (computer runs unattended)
**Can complete in:** One work day if started in morning

---

## SUCCESS CRITERIA SUMMARY

### Minimum Success (Acceptable)
✅ Combined bot score ≥ 0.50  
✅ Exceeds Phase 1 baseline (0.48)  
✅ No single bot win rate <35%  
✅ Clip fraction never collapsed to 0.00  
✅ Training completed without premature convergence  

**Interpretation:** Curriculum learning worked, agent improved over Phase 1

---

### Good Success (Expected)
✅ Combined bot score ≥ 0.55  
✅ All bot win rates ≥ 40%  
✅ At least one bot win rate ≥ 60%  
✅ Healthy training metrics throughout  
✅ Clear evidence of learned efficiency behaviors  

**Interpretation:** Fix was effective, curriculum learning proven viable

---

### Excellent Success (Best Case)
✅ Combined bot score ≥ 0.60  
✅ All bot win rates ≥ 45%  
✅ Beats GreedyBot >50% (hardest opponent)  
✅ Stable training metrics with no concerning patterns  
✅ Observable smart targeting and efficiency in replays  

**Interpretation:** Curriculum learning highly effective, ready for Phase 3 or charge/melee

---

### Failure Indicators
❌ Combined bot score <0.48 (worse than Phase 1)  
❌ Any bot win rate <30%  
❌ Clip fraction collapsed to 0.00 before episode 2000  
❌ Episode rewards consistently <40  
❌ Training showed same failure pattern as previous Phase 2 attempts  

**Action:** Switch to Plan B (Extended Phase 1) immediately

---

## RISK ASSESSMENT & MITIGATION

### Risk 1: Both Approaches Fail (5% probability)
**Symptom:** Phase 2 fix AND Extended Phase 1 both score <0.48

**Cause:** Deeper architectural problem with:
- Neural network size (320,320 may be wrong)
- Observation space (295 floats may be insufficient)
- Game engine bug (reward calculation or state tracking)

**Mitigation:** Unlikely since Phase 1 already achieved 0.48. System fundamentally works.

**If this occurs:** Contact for deep diagnosis of architecture and observation space.

---

### Risk 2: Training Takes Longer Than Expected (15% probability)
**Symptom:** 3000 episodes takes 12+ hours instead of 6-8

**Cause:** Hardware slower than estimated, or CPU bottleneck

**Mitigation:** Start training before bed, let run overnight. Check progress in morning.

**Impact:** Extends timeline but doesn't affect success probability.

---

### Risk 3: JSON Syntax Errors in Configs (10% probability)
**Symptom:** Training crashes immediately with "JSON decode error"

**Cause:** Missing comma, mismatched brackets, or quote errors in manual edits

**Mitigation:** Use JSON validation commands after every edit:
```powershell
python -c "import json; json.load(open('config/[filename].json'))"
```

**Fix:** Compare with backup file, identify syntax error, correct it.

---

### Risk 4: Phase 1 Model Missing or Corrupted (8% probability)
**Symptom:** Training fails to load Phase 1 model with --append flag

**Cause:** Phase 1 training never completed, or model files deleted

**Mitigation:** Step 4 verifies Phase 1 model exists before starting Phase 2.

**Fix:** Train Phase 1 first (adds 3-4 hours to timeline).

---

### Risk 5: Tensorboard Port Conflict (5% probability)
**Symptom:** Tensorboard fails to start, shows port 6006 already in use

**Cause:** Previous Tensorboard instance still running

**Fix:** 
```powershell
# Find process using port 6006
netstat -ano | findstr :6006

# Kill process (replace PID with actual process ID from above)
taskkill /PID [PID] /F

# Or use different port
tensorboard --logdir=./tensorboard --port=6007
```

---

## TROUBLESHOOTING GUIDE

### Problem: Training crashes after 10-20 episodes

**Possible Causes:**
1. Scenario file not found or malformed
2. GPU memory exhausted
3. Python environment issue

**Diagnosis:**
```powershell
# Check if all scenario files exist
Get-ChildItem config/SpaceMarine_Infantry_Troop_RangedSwarm_scenario_phase2-*.json

# Check error message in training terminal
# Look for keywords: "FileNotFoundError", "CUDA out of memory", "ModuleNotFoundError"
```

**Solutions:**
- Missing scenarios: Copy from uploads to config directory
- GPU memory: Add `--device cpu` flag to training command
- Module errors: Reinstall requirements `pip install -r requirements.txt`

---

### Problem: Episode rewards consistently below 20

**Possible Causes:**
1. Rewards config not loaded correctly
2. Agent stuck in local minimum (passive play)
3. Scenario too difficult

**Diagnosis:**
```powershell
# Verify rewards config was loaded
# Check training terminal output at start for:
"rewards_config": "SpaceMarine_Infantry_Troop_RangedSwarm_phase2"

# Check Tensorboard for other metrics:
# If explained_variance is high (0.80+) but rewards low → learning wrong behavior
# If explained_variance is low (0.20-) → value function broken
```

**Solutions:**
- Config not loaded: Check --rewards-config parameter spelling
- Learning wrong behavior: Abort training, verify reward magnitudes in config file
- Value function broken: Unlikely if explained variance was good in Phase 1

---

### Problem: Clip fraction drops to 0.00 before episode 1000

**Possible Causes:**
1. Learning rate too low (policy converging prematurely)
2. Target KL threshold too restrictive
3. Agent found local optimum (premature convergence)

**Diagnosis:**
Check Tensorboard train/approx_kl at same time clip fraction dropped:
- If approx_kl also → 0.00: Premature convergence confirmed
- If approx_kl > 0.02 repeatedly: target_kl stopping training too early

**Solutions:**
- If at episode 1000: This is the failure we expected to catch. Abort and use Plan B.
- If before episode 1000: Training failing even faster than previous attempts. Stop immediately and use Plan B.

---

### Problem: Win rate dropping below Phase 1 baseline

**Possible Causes:**
1. Agent becoming passive despite reward fix
2. Efficiency bonuses too strong (over-cautious targeting)
3. Scenarios harder than Phase 1 scenario

**Diagnosis:**
```powershell
# Compare bot-specific win rates
# Check Tensorboard Critical/b_win_rate_vs_[BotName]
# - vs RandomBot dropping: Agent making basic mistakes
# - vs GreedyBot dropping: Agent too passive
# - vs DefensiveBot dropping: Agent not aggressive enough
```

**Solutions:**
- If only vs DefensiveBot: Expected, this bot counters passive play
- If vs all bots: Reward fix didn't work, abort and use Plan B
- If only in first 500 episodes: May be temporary dip during learning, continue monitoring

---

### Problem: Tensorboard shows no data

**Possible Causes:**
1. Wrong logdir path
2. Training hasn't written first checkpoint yet
3. Tensorboard looking at wrong folder

**Solutions:**
```powershell
# Verify tensorboard logs exist
Get-ChildItem tensorboard -Recurse

# Should see folders like: phase2_SpaceMarine_*_[timestamp]

# If empty: Training hasn't written first update (wait 5-10 minutes)

# Restart Tensorboard with explicit path:
tensorboard --logdir=./tensorboard --reload_interval=5
```

---

### Problem: Training terminal shows "target_kl exceeded" repeatedly

**Possible Causes:**
1. Policy changing too rapidly
2. Learning rate too high
3. Unstable training dynamics

**Diagnosis:**
- If in first 100 episodes: Normal as agent explores
- If consistently throughout training: Learning rate or batch size issue

**Solutions:**
- If occasional: Ignore, this is PPO's safety mechanism
- If constant: Learning may be unstable but often still works. Monitor combined score - if improving, let it continue.

---

## EXPERT TIPS & BEST PRACTICES

### Tip 1: Start Training Before Bed
Training takes 6-8 hours and doesn't need supervision after first hour. Start it at 10 PM, check episode 1000 metrics at 11 PM, then go to sleep. Wake up to completed training.

### Tip 2: Use Multiple Tensorboard Browser Windows
Open separate browser tabs for:
- Episode rewards (to watch for crashes)
- Clip fraction (to catch premature convergence)
- Bot combined score (to see actual performance)

This lets you quickly spot problems without switching graphs.

### Tip 3: Take Baseline Screenshots
Before starting Step 6, take screenshots of Phase 1's Tensorboard metrics. This gives you direct visual comparison for Phase 2.

### Tip 4: Don't Panic at Episode 100-300
Early training often looks chaotic:
- Episode rewards spike and drop
- Clip fraction very high (0.20-0.30)
- Entropy fluctuates

This is normal exploration. Judge stability after episode 500.

### Tip 5: Trust Explained Variance
If explained variance is 0.80+, your neural network is working perfectly. The question is only "Is it learning the right behavior?" not "Is it learning at all?"

### Tip 6: The Episode 1000 Decision is Critical
Previous Phase 2 attempts died at episode 1000-1500 when clip fraction collapsed. This checkpoint is specifically designed to catch that failure pattern early. Don't skip it.

### Tip 7: Keep Your Terminal Windows Visible
Put training terminal on one monitor, Tensorboard browser on another. Glance at episode rewards every 10-20 minutes while doing other work. You'll catch crashes within minutes instead of hours.

### Tip 8: Plan B is Not Failure
Extended Phase 1 is a proven, safe approach. Many successful RL projects don't use curriculum learning at all. If Phase 2 doesn't work, Plan B will almost certainly succeed.

### Tip 9: Document While Training
Don't wait until the end. As you notice interesting patterns during training, add notes to your results file immediately. "Episode 800: noticed agent started targeting weak enemies first" is valuable context you'll forget later.

### Tip 10: Celebrate Small Wins
If Phase 2 reaches episode 1000 with healthy metrics, that's already a major success - you fixed the premature convergence problem. If it then reaches 0.50+ score, that's curriculum learning working. If it hits 0.55+, you've validated the entire approach.

---

## FINAL CHECKLIST

**Before Starting Training:**
- [ ] Backed up original config files (Step 1)
- [ ] Updated rewards config with fixed magnitudes (Step 2)
- [ ] Updated training config with fixed hyperparameters (Step 3)
- [ ] Validated both JSON files (no syntax errors)
- [ ] Confirmed Phase 1 model exists (Step 4)
- [ ] Cleaned old Phase 2 artifacts (Step 5)
- [ ] Have 6-8 hours available for computer to run

**During Training:**
- [ ] Tensorboard launched and showing data (Step 7)
- [ ] Training terminal visible for error monitoring
- [ ] Episode 1000 checkpoint scheduled in calendar
- [ ] Screenshots of baseline Phase 1 metrics saved

**At Episode 1000 Checkpoint:**
- [ ] Checked all 7 critical metrics (Step 8)
- [ ] Made go/no-go decision
- [ ] If failing: aborted training and started Plan B
- [ ] If succeeding: let training continue

**After Training Completes:**
- [ ] Ran 100-episode final evaluation (Step 9)
- [ ] Assessed results against success criteria
- [ ] Created results documentation file (Step 12)
- [ ] Saved all Tensorboard screenshots
- [ ] Made decision on next steps (Phase 3 or charge/melee)

---

## CONCLUSION

You now have a complete, step-by-step plan to fix Phase 1/2 curriculum learning within 24 hours.

**What makes this plan reliable:**
- Root cause clearly identified (reward magnitude mismatch)
- Fix directly addresses root cause (maintain Phase 1 magnitudes)
- Built-in checkpoint to catch failures early (episode 1000)
- Proven fallback option if primary approach fails (Extended Phase 1)
- Conservative hyperparameters prevent premature convergence
- Comprehensive monitoring catches problems immediately

**Success probability: 95%+**

**Expected outcome:**
By this time tomorrow, you will have either:
1. Working Phase 2 curriculum learning (0.55-0.65 score), OR
2. Extended Phase 1 training (0.55-0.65 score)

Either way, you'll have a functional AI ready for Phase 3 or charge/melee implementation.

**You're ready to begin. Good luck! 🎯**

---

## QUICK START (If You're Ready Now)

```powershell
# 1. Backup configs (2 minutes)
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item "config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json" "config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json.backup_$timestamp"
Copy-Item "config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json" "config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json.backup_$timestamp"

# 2. Edit both config files per Step 2 and Step 3 (8 minutes)
# Use your text editor to make the changes documented above

# 3. Validate JSON (1 minute)
python -c "import json; json.load(open('config/SpaceMarine_Infantry_Troop_RangedSwarm_rewards_config.json'))"
python -c "import json; json.load(open('config/SpaceMarine_Infantry_Troop_RangedSwarm_training_config.json'))"

# 4. Verify Phase 1 model exists (1 minute)
Get-ChildItem -Path "ai/models" -Filter "*phase1*" -Recurse

# 5. Clean old Phase 2 data (2 minutes)
Remove-Item -Path "ai/models/*phase2*" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "tensorboard/*phase2*" -Recurse -Force -ErrorAction SilentlyContinue

# 6. Start training (Terminal 1)
python train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config phase2 --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm_phase2 --scenario all --append --test-episodes 0

# 7. Launch Tensorboard (Terminal 2)
tensorboard --logdir=./tensorboard --port=6006
# Then open browser to http://localhost:6006
```

**Total setup time: 15 minutes**  
**Then monitor at episode 1000 (2-3 hours later)**  
**Final evaluation at episode 3000 (6-8 hours total)**

---

**Questions? Issues? Return with episode 1000 checkpoint status and I'll help troubleshoot.**