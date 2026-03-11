# AI_TRAINING.md
## Guide training et tuning — référence unique

> **📍 Purpose** : Ce document est la **référence unique** pour tout ce qui concerne l’entraînement et le tuning : architecture du pipeline, configuration, monitoring, métriques, hyperparamètres, anti-overfitting, dépannage.
>
> **Moteur de jeu** : voir [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md).  
> **Métriques détaillées et tuning ciblé** : voir [AI_METRICS.md](AI_METRICS.md) (inclut le guide de tuning rapide).

---

## 📋 TABLE OF CONTENTS

- [Quick Start](#-quick-start)
  - [Run Training](#run-training)
  - [Continue Existing Model](#continue-existing-model)
  - [Key Paths](#key-paths)
- [Training pipeline (architecture)](#-training-pipeline-architecture)
  - [Point d’entrée et CLI](#point-dentrée-et-cli)
  - [Chargement de la config](#chargement-de-la-config)
  - [Création de l’environnement](#création-de-lenvironnement)
  - [Modèle et boucle d’entraînement](#modèle-et-boucle-dentraînement)
- [Macro Training Status](#-macro-training-status)
  - [Implémenté aujourd'hui](#implémente-aujourdhui)
  - [Recommandations / non implémenté](#recommandations--non-implémente)
- [Replay Mode](#-replay-mode)
  - [Overview](#overview)
  - [Generating Replay Logs](#generating-replay-logs)
  - [Using the Replay Viewer](#using-the-replay-viewer)
  - [Replay Features](#replay-features)
  - [Log Format Reference](#log-format-reference)
  - [Best Practices](#best-practices)
- [Training Strategy](#-training-strategy)
  - [Unified Training (No Curriculum)](#unified-training-no-curriculum)
  - [Reward Design Philosophy](#reward-design-philosophy)
  - [Target Priority & Positioning](#target-priority--positioning)
- [Configuration Files](#️-configuration-files)
  - [training_config.json Structure](#trainingconfigjson-structure)
  - [rewards_config.json Structure](#rewardsconfigjson-structure)
- [Monitoring Training](#-monitoring-training)
  - [TensorBoard Metrics](#tensorboard-metrics)
  - [Success Indicators](#success-indicators)
  - [Red Flags (Training Collapse)](#red-flags-training-collapse)
- [Métriques avancées et tuning](#-métriques-avancées-et-tuning)
- [Bot Evaluation System](#-bot-evaluation-system)
  - [Bot Types](#bot-types)
  - [Evaluation Commands](#evaluation-commands)
  - [Win Rate Benchmarks](#win-rate-benchmarks)
- [Anti-Overfitting Strategies](#️-anti-overfitting-strategies)
  - [The Problem: Pattern Exploitation](#the-problem-pattern-exploitation-vs-robust-tactics)
  - [Solution 1: Bot Stochasticity](#solution-1-bot-stochasticity-prevent-pattern-exploitation)
  - [Solution 2: Balanced Reward Penalties](#solution-2-balanced-reward-penalties-reduce-over-aggression)
  - [Solution 3: Increased RandomBot Weight](#solution-3-increased-randombot-evaluation-weight)
  - [Solution 4: Weighted Training Bots](#solution-4-weighted-training-bots-prevent-randombot-overfitting)
  - [Monitoring for Overfitting](#monitoring-for-overfitting)
  - [Troubleshooting Overfitting](#troubleshooting-overfitting)
- [Hyperparameter Tuning Guide](#-hyperparameter-tuning-guide)
  - [When Agent Isn't Learning](#when-agent-isnt-learning)
  - [When Agent Is Unstable](#when-agent-is-unstable)
  - [When Training Is Too Slow](#when-training-is-too-slow)
  - [When Agent Exploits Mechanics](#when-agent-exploits-mechanics)
- [Performance Optimization](#-performance-optimization)
  - [CPU vs GPU](#cpu-vs-gpu)
  - [Training Speed Tips](#training-speed-tips)
- [Troubleshooting](#-troubleshooting)
  - [Common Errors](#common-errors)
  - [Performance Issues](#performance-issues)
- [Évolutions prévues : League / curriculum training](#évolutions-prévues--league--curriculum-training)
- [Advanced Topics (External References)](#-advanced-topics-external-references)
- [Quick Reference Cheat Sheet](#-quick-reference-cheat-sheet)
- [Summary](#-summary)

---

## 📋 QUICK START

### Run Training
```bash
# From project root (--agent obligatoire pour entraînement ciblé)
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot   # Entraînement standard
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --step  # + step logging (step.log)
python ai/train.py --agent <agent_key> --scenario bot --test-only --step --test-episodes 50   # Test rapide avec logs
```

### Continue Existing Model
```bash
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --append
```
(Le chemin du modèle est dérivé de l’agent : `ai/models/<agent_key>/model_<agent_key>.zip`.)

### Key Paths
- **Training Configs**: `config/agents/<agent_name>/<agent_name>_training_config.json`
- **Reward Configs**: `config/agents/<agent_name>/<agent_name>_rewards_config.json` (par agent)
- **Models**: `ai/models/<agent_key>/model_<agent_key>.zip`
- **Logs**: `./tensorboard/` (TensorBoard data)
- **Step Logs**: `step.log` (généré avec `--step` ; utilisé par l’analyzer et le replay viewer)
- **Agent inheritance metadata**: `inherits_from` dans `config/agents/<agent_name>/<agent_name>_training_config.json`
- **Shared training defaults**: `config/agents/_training_common.json`
- **Agent P1 rosters (100 pts)**:
  - `config/agents/<agent_key>/rosters/100pts/training/p1_roster-XX.json`
  - `config/agents/<agent_key>/rosters/100pts/holdout_regular/p1_roster-XX.json`
  - `config/agents/<agent_key>/rosters/100pts/holdout_hard/p1_roster-XX.json`
- **Shared P2 rosters (100 pts)**:
  - `config/agents/_p2_rosters/100pts/training/p2_roster-XX.json`
  - `config/agents/_p2_rosters/100pts/holdout/p2_roster-XX.json`
- **Shared walls**:
  - `config/board/{cols}x{rows}/walls/walls-XX.json`
- **Shared objectives**:
  - `config/board/{cols}x{rows}/objectives/objectives-XX.json`

---

## 🏗️ TRAINING PIPELINE (ARCHITECTURE)

Cette section décrit comment le training est structuré (qui appelle quoi). Pour la config des paramètres, voir les sections suivantes.

### Point d’entrée et CLI

- **Script** : `ai/train.py`. Tous les modes (entraînement, test-only, macro, orchestrate, convert-steplog) partent de ce script.
- **Arguments essentiels** :
  - `--agent <agent_key>` : agent à entraîner (obligatoire pour training ciblé). Détermine le dossier de config et le chemin du modèle.
  - `--training-config <name>` : clé du bloc dans `*_training_config.json` (ex. `default`, `debug`).
  - `--rewards-config <name>` : en pratique le même que `--agent` ou un alias ; utilisé comme `rewards_config_name` et pour charger `*_rewards_config.json`.
  - `--scenario <name>` : scénario ou mode (`bot`, `default`, `phase1`, etc.). Avec `bot`, l’adversaire est un ou plusieurs bots (RandomBot, GreedyBot, DefensiveBot).
- **Options utiles** : `--step` (écrit `step.log`), `--test-only` (pas d’apprentissage, évaluation uniquement), `--test-episodes N`, `--append` (reprendre un modèle existant), `--new-model` (partir de zéro).

### Chargement de la config

- **config_loader** (`config_loader.py`) :
  - `load_agent_training_config(agent_key, training_config_name)` → charge `config/agents/<agent>/<agent>_training_config.json` et retourne le bloc demandé (ex. `default`). Gère `inherits_from` (héritage vers un autre dossier d’agent).
  - `load_agent_rewards_config(agent_key)` → charge `config/agents/<agent>/<agent>_rewards_config.json`.
  - `get_models_root()` → racine des modèles (ex. `ai/models/`).
- **UnitRegistry** (`ai/unit_registry.py`) : mappe `unit_type` (ex. type d’unité du scénario) vers `model_key` (clé d’agent pour charger le bon micro-modèle). Requis pour créer le moteur et les wrappers (BotControlledEnv, macro).

#### Scénarios minces + rosters compacts

- Un scénario peut rester en format legacy (`"units": [...]`) ou pointer vers des rosters via:
  - `"scale"` (ex: `"100pts"`),
  - `"p1_roster_ref"`,
  - `"p2_roster_ref"`.
- En holdout, `p1_roster_ref` doit être explicite et séparé par difficulté:
  - `holdout_regular/...` pour les scénarios dans `scenarios/holdout_regular/`
  - `holdout_hard/...` pour les scénarios dans `scenarios/holdout_hard/`
- Pour `p1_roster_ref`, un alias explicite est supporté en training:
  - `"training_random"` -> tirage aléatoire d’un roster dans `rosters/<scale>/training/` (liste triée avant tirage).
- Optionnel: `"p1_roster_seed"` (int >= 0) pour forcer un tirage déterministe local du roster P1.
- Un scénario peut aussi référencer des données de carte partagées via:
  - `"wall_ref"` (au lieu de `"wall_hexes"`),
  - `"objectives_ref"` (au lieu de `"objectives"` / `"objective_hexes"`).
- Les rosters compacts utilisent ce format:
  - `"roster_id"`: identifiant lisible (ex: `p1_roster-02`),
  - `"composition"`: liste de `{ "unit_type": "<UnitName>", "count": <N> }`.
- Expansion runtime:
  - IDs P1 déterministes: `1..N`.
  - IDs P2 déterministes: `101..(100+N2)`.
  - Pas de `col/row` dans le roster compact: le déploiement est géré par le scénario (`deployment_type`/`deployment_zone`).
- En training, `p1_roster_ref` peut être une liste pour tirage aléatoire par épisode; en holdout, utiliser une ref unique déterministe.
- `step.log` journalise les rosters sélectionnés en début d’épisode (`Rosters: ...`).

### Création de l’environnement

1. **Moteur de base** : `W40KEngine` (`engine/w40k_core.py`) avec :
   - `rewards_config=rewards_config_name`, `training_config_name=...`, `controlled_agent=controlled_agent_key`,
   - `scenario_file` ou `scenario_files` (liste pour tirage aléatoire),
   - `unit_registry=unit_registry`, `gym_training_mode=True`.
2. **Step logger** (si `--step`) : `StepLogger("step.log", ...)` attaché à `base_env.step_logger` ; désactivé pour les envs vectorisés (SubprocVecEnv).
3. **ActionMasker** : wrapper SB3 `ActionMasker(base_env, mask_fn)` avec `mask_fn(env) = env.get_action_mask()` pour MaskablePPO.
4. **Adversaire** :
   - **Scénario bot** : `BotControlledEnv(masked_env, bots=training_bots, unit_registry=unit_registry)`. Les bots sont instanciés à partir de `training_config` (ratios, randomness) ou par défaut (RandomBot, GreedyBot, DefensiveBot avec randomness 0.10).
   - **Self-play** : `SelfPlayWrapper(masked_env, ...)` (autre joueur = copie du modèle, mise à jour périodique).
5. **Monitor** : `Monitor(wrapped_env)` pour les stats d’épisode (reward, length) utilisées par TensorBoard et les callbacks.

Pour l’entraînement vectorisé, `make_training_env()` dans `ai/training_utils.py` encapsule cette construction (W40KEngine → ActionMasker → BotControlledEnv ou SelfPlayWrapper → Monitor).

### Modèle et boucle d’entraînement

- **Modèle** : `MaskablePPO` (sb3_contrib). Chargement depuis `ai/models/<agent_key>/model_<agent_key>.zip` ; sauvegarde via callbacks (CheckpointCallback) et à la fin de l’entraînement.
- **Callbacks** (définis dans `train.py`, paramétrés par `training_config["callback_params"]`) : sauvegarde de checkpoints, évaluation périodique contre les bots (`BotEvaluationCallback` : `bot_eval_freq`, `bot_eval_intermediate`), logging TensorBoard.
- **Boucle** : `model.learn(total_timesteps=...)` (ou équivalent selon le mode). Chaque step : `action = model.predict(obs, action_masks=mask)` puis `env.step(action)`.

**Références code** : `ai/train.py`, `ai/training_utils.py` (`make_training_env`), `ai/env_wrappers.py` (BotControlledEnv, SelfPlayWrapper), `engine/w40k_core.py` (W40KEngine).

---

## 🧭 MACRO TRAINING STATUS

### Implémente aujourd'hui

Cette section couvre uniquement ce qui est actuellement supporté côté code.

- **Entrée CLI unique** : `ai/train.py` gère les modes macro et micro.
- **Wrappers macro** : `ai/macro_training_env.py` (`MacroTrainingWrapper`, `MacroVsBotWrapper`).
- **Config macro** : `config/agents/MacroController/MacroController_training_config.json`.
- **Scénarios macro** : `config/agents/MacroController/scenarios/*.json`.
- **Modes d'évaluation macro** :
  - `--macro-eval-mode micro` : macro vs pipeline micro.
  - `--macro-eval-mode bot` : macro vs bots d'évaluation.
- **Lancement macro (exemple)** :
  ```bash
  python ai/train.py --agent MacroController --training-config default --rewards-config MacroController --scenario all --new
  ```

### Recommandations / non implémente

> **⚠️ IMPORTANT**
> Les éléments ci-dessous sont des recommandations de design/process et ne sont pas garantis comme implémentés partout.
> Le document détaillé a été déplacé vers `Documentation/TODO/Macro_agent.md`.

- Structuration macro complète en `scenarios/training` + `scenarios/holdout_regular` + `scenarios/holdout_hard`.
- Couverture de scénarios plus large (volumétrie et variété topologique).
- Stratégie “1 macro-agent par armée”.
- Pipeline de validation robuste orienté holdout + multi-bots + fenêtre temporelle.

---

## 🎬 REPLAY MODE

### Overview
The Replay Mode allows you to visualize training episodes step-by-step in the frontend. This is invaluable for understanding agent behavior and debugging tactical decisions.

### Generating Replay Logs
During training or evaluation with `--step`, a `step.log` file is generated containing detailed action logs:

```bash
# Training with step logging enabled
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --step
```

The log captures:
- Episode start/end markers
- Unit starting positions
- Move actions (from/to coordinates)
- Shoot actions (hit/wound/save rolls, damage dealt)
- Episode results (winner, total actions)

### Using the Replay Viewer

1. **Start the frontend**:
   ```bash
   cd frontend && npm run dev
   ```

2. **Navigate to Replay Mode**:
   - Click the "Replay" tab in the frontend
   - Click "Browse" to select your `step.log` (or `train_step.log` if the API expects that name)

3. **Select an Episode**:
   - Use the dropdown to select an episode
   - Episodes show: `Episode N - BotName - Result`
   - Example: `Episode 5 - GreedyBot - Agent Win`

4. **Control Playback**:
   - Use forward/backward buttons to step through actions
   - Watch units move, shoot, and take damage
   - Dead units appear as grey ghosts before being removed

### Replay Features

**Visual Indicators:**
- **Shoot lines**: Orange lines show shooting actions
- **Explosion icons**: Appear on damaged/killed units
- **Grey ghosts**: Units killed in the current step appear grey before removal
- **Death logs**: Black log entries appear when a unit is destroyed
- **HP display**: Unit health shown as bars

**Movement Phase Indicators:**
- **Ghost unit at origin**: Darkened ghost shows where unit started
- **Orange destination hexes**: All valid movement destinations highlighted

**Charge Phase Indicators:**
- **Ghost unit at origin**: Darkened ghost shows where charging unit started
- **Orange destination hexes**: All valid charge destinations (hexes adjacent to enemies within charge roll)
- **Charge roll badge**: Bottom-right badge on charging unit shows the 2d6 roll result
  - **Green badge**: Charge roll succeeded (light green text on dark green background)
  - **Red badge**: Charge roll failed (light red text on dark red background)

**Fight Phase Indicators:**
- **Crossed swords icon**: Appears on the fighting unit
- **Explosion icon**: Appears on the target unit

**Game Log Color Coding:**

*Charge Actions:*
- **Purple**: Successful charge action
- **Light Purple**: Failed charge (roll too low or chose not to charge)

*Shooting Actions (Blue Palette):*
- **Light Blue**: Failed hit or wound rolls (MISS)
- **Cyan**: Target succeeded save roll (SAVED)
- **Dark Blue**: Damage dealt to target (DMG)

*Combat/Fight Actions (Warm Palette):*
- **Yellow**: Failed hit or wound rolls
- **Orange**: Target succeeded save roll
- **Red**: Damage dealt to target

*Death:*
- **Black**: Unit DESTROYED (separate event after damage)

**Episode Information:**
- Bot opponent name (e.g., GreedyBot, RandomBot)
- Win/Loss/Draw result
- Total actions in episode
- Current action counter

### Log Format Reference

The `step.log` uses this format:

```
[HH:MM:SS] === EPISODE START ===
[HH:MM:SS] Scenario: default
[HH:MM:SS] Opponent: GreedyBot
[HH:MM:SS] Unit 1 (Intercessor) P0: Starting position (9, 12)
[HH:MM:SS] === ACTIONS START ===
[HH:MM:SS] T1 P0 MOVE : Unit 1(6, 15) MOVED from (9, 12) to (6, 15) [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 SHOOT : Unit 1(6, 15) SHOT at Unit 5 - Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED) Dmg:1HP [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 CHARGE : Unit 2(9, 6) CHARGED Unit 8 from (7, 13) to (9, 6) [Roll:7] [R:+3.0] [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 CHARGE : Unit 3(10, 5) WAIT [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 FIGHT : Unit 2(9, 6) FOUGHT unit 8 - Hit:3+:5(HIT) Wound:4+:4(SUCCESS) Save:4+:6(SAVED) Dmg:0HP [SUCCESS] [STEP: YES]
[HH:MM:SS] EPISODE END: Winner=0, Actions=68, Steps=68, Total=138
```

#### Action Log Formats

| Action | Format |
|--------|--------|
| MOVE | `Unit X(col, row) MOVED from (a, b) to (c, d)` |
| SHOOT | `Unit X(col, row) SHOT at Unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |
| CHARGE | `Unit X(col, row) CHARGED Unit Y from (a, b) to (c, d) [Roll:N]` where N is the 2d6 charge roll |
| CHARGE WAIT | `Unit X(col, row) WAIT` (unit chose not to charge or roll was too low) |
| FIGHT | `Unit X(col, row) FOUGHT unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |

### Best Practices

1. **Debug unexpected behavior**: Use replay to see exactly what the agent did
2. **Validate training progress**: Check if agent is making tactical decisions
3. **Compare episodes**: Replay episodes from different training stages to see improvement
4. **Check target selection**: Verify agent is prioritizing correct targets

---

## 🎯 TRAINING STRATEGY

### Unified Training (No Curriculum)

> **IMPORTANT**: This project uses **unified training from the start** - NO curriculum learning.
> See the "Unified Training" and "Reward Design" sections below for rationale.

**Why NOT Curriculum Learning?**

Research and testing show curriculum learning **fails** for tactical games like this:

1. **Early phases teach wrong policies**
   - Phase 1 (simplified): Learns "standing still is optimal"
   - Phase 2 (full game): Must unlearn Phase 1 habits
   - Result: Negative transfer, worse performance

2. **Mechanics are interdependent**
   - Shooting effectiveness depends on positioning
   - Can't learn optimal shooting without walls/cover

3. **Dense rewards + simple exploration**
  - Agent gets rewards for shooting and objectives
   - Random policy can discover basic strategies
   - No need for staged difficulty

**Evidence from testing:**
- Curriculum Phase 1→2 training: 18k episodes, 14% win rate
- Unified from-scratch training: 15k episodes, 50-60% win rate
- **Curriculum took MORE time and got WORSE results**

---

### Reward Design Philosophy

**Key Principles:**
- All game mechanics active from episode 1 (MOVE, SHOOT, CHARGE, FIGHT)
- All unit types in scenarios from start (mixed armies)
- Objectives active from episode 1
- Single reward configuration, no phased weights

**Current Reward Structure** (from `config/agents/<agent>/<agent>_rewards_config.json`):
```json
{
  "SpaceMarineRanged": {
    "ranged_attack": 0.2,
    "enemy_killed_r": 0.4,
    "enemy_killed_lowests_hp_r": 0.6,
    "charge_success": 0.2,
    "attack": 0.4,
    "enemy_killed_m": 0.2,
    "win": 1,
    "lose": -1,
    "wait": -0.9
  }
}
```

---

### Target Priority & Positioning

The agent learns target prioritization through reward signals:

**Target Priority Formula:**
```
target_priority = VALUE / turns_to_kill
```

- **VALUE**: W40K point cost from unit profile (e.g., Termagant=6, Intercessor=19, Captain=80)
- **turns_to_kill**: How many activations needed to kill this target

**Example priorities (Intercessor selecting targets):**

| Target | VALUE | Turns to Kill | Priority Score |
|--------|-------|---------------|----------------|
| Captain (wounded, 2HP left) | 80 | 2 | **40** (highest) |
| Intercessor (wounded, 1HP) | 19 | 1 | **19** |
| Termagant | 6 | 1.35 | **4.4** |

This naturally encourages:
- High-value targets when killable (Captain > Intercessor)
- Finishing wounded enemies (faster kill = higher priority)
- Efficient use of attacks (don't waste on hard-to-kill targets)

---

## ⚙️ CONFIGURATION FILES

### training_config.json Structure

Training configs are per-agent at: `config/agents/<agent_name>/<agent_name>_training_config.json`

### Agent Inheritance (EXPLICIT)

> **🚨 CRITICAL - AGENT INHERITANCE IS EXPLICIT**
>
> Il n'y a plus de mapping hardcodé dans `config_loader.py` pour rediriger un agent vers un autre.
> La résolution se fait uniquement via le champ `inherits_from` défini dans le
> `*_training_config.json` de l'agent demandé.
>
> Si `inherits_from` est renseigné, l'entraînement/chargement utilise les configs du dossier parent.
> Un **gros WARNING** est affiché au runtime pour signaler clairement la redirection.

Règles:
- `inherits_from: null` → pas d'héritage, l'agent charge son propre dossier.
- `inherits_from: "<AgentKeyParent>"` → héritage explicite vers `config/agents/<AgentKeyParent>/`.
- Valeur invalide (vide, auto-référence, dossier parent absent) → erreur explicite (fail fast).
- Pour les paramètres communs de training: une valeur de phase à `null` (ex: `seed`, `total_episodes`)
  est résolue via `config/agents/_training_common.json`. Si la clé manque dans ce fichier commun: erreur explicite.

```json
{
  "inherits_from": null,
  "default": {
    "total_episodes": 5000,              // How many episodes to train
    "max_turns_per_episode": 5,          // Game length limit
    "max_steps_per_turn": 200,           // Steps per turn limit

    "callback_params": {
      "checkpoint_save_freq": 50000,     // Save model every N steps
      "checkpoint_name_prefix": "ppo_checkpoint",
      "n_eval_episodes": 5,              // Evaluation frequency
      "bot_eval_freq": 200,              // Bot eval every N episodes (100-200 recommended)
      "bot_eval_use_episodes": true,     // true = freq in episodes, false = timesteps
      "bot_eval_intermediate": 30,       // Episodes per bot per eval (30 = good precision/speed balance)
      "bot_eval_final": 0,               // Final eval episodes (0 = skip)
      "save_best_robust": true,          // If true, canonical model comes from robust selection
      "robust_window": 3,                // Moving window size for robust score
      "robust_drawdown_penalty": 0.5,    // Drawdown penalty applied to robust score
      "model_gating_enabled": true,      // Enable hard gating before model promotion
      "model_gating_min_combined": 0.55, // Min combined score required
      "model_gating_min_worst_bot": 0.45, // Min(min random, greedy, defensive)
      "model_gating_min_worst_scenario_combined": 0.45 // Min scenario combined required
    },

    "observation_params": {
      "obs_size": 300,                   // Total observation vector size
      "perception_radius": 25,           // Fog of war radius
      "max_nearby_units": 10,            // Max units to observe
      "max_valid_targets": 5             // Max targets to track
    },
    
    "model_params": {
      "learning_rate": 0.0003,           // How fast agent learns
      "n_steps": 256,                    // Steps before update
      "batch_size": 128,                 // Training batch size
      "n_epochs": 10,                    // Training epochs per update
      "gamma": 0.95,                     // Future reward discount
      "gae_lambda": 0.95,                // Advantage estimation
      "clip_range": 0.2,                 // PPO clipping parameter
      "ent_coef": 0.10,                  // Exploration bonus
      "vf_coef": 1.0,                    // Value function weight
      "max_grad_norm": 0.5,              // Gradient clipping
      "policy_kwargs": {
        "net_arch": [320, 320]           // Neural network size
      }
    }
  }
}
```

**Key Parameters to Adjust:**

| Parameter | Low Value | High Value | Effect |
|-----------|-----------|------------|--------|
| `learning_rate` | 0.0001 | 0.001 | Faster learning (risk: instability) |
| `ent_coef` | 0.01 | 0.20 | More exploration (risk: chaos) |
| `n_steps` | 256 | 4096 | Larger batches (slower, more stable) |
| `batch_size` | 64 | 256 | Training speed vs memory |
| `gamma` | 0.90 | 0.99 | Long-term vs short-term rewards |

---

### Agent rewards_config.json Structure

Chaque agent a son fichier `config/agents/<agent>/<agent>_rewards_config.json`. Les récompenses sont par type d’unité / archétype dans ce fichier.

**Reward Categories** (exemple, depuis un rewards_config d’agent) :

```json
{
  "SpaceMarineRanged": {
    // Combat rewards
    "ranged_attack": 0.2,        // Shooting action
    "enemy_killed_r": 0.4,       // Kill with ranged
    "enemy_killed_lowests_hp_r": 0.6,  // Kill lowest HP target
    "enemy_killed_no_overkill_r": 0.8, // Kill without overkill
    "charge_success": 0.2,       // Successful charge
    "attack": 0.4,               // Melee attack
    "enemy_killed_m": 0.2,       // Kill in melee

    // Penalties
    "being_charged": -0.4,       // Getting charged
    "loose_hp": -0.4,            // Taking damage
    "killed_in_melee": -0.8,     // Dying in melee
    "atk_wasted_r": -0.8,        // Wasted ranged attack
    "atk_wasted_m": -0.8,        // Wasted melee attack
    "wait": -0.9,                // Waiting instead of acting

    // Game outcome
    "win": 1,
    "lose": -1.0,
    "friendly_fire_penalty": -0.8
  }
}
```

**Common Reward Design Mistakes:**

❌ **Reward Hacking**: Too high rewards cause agent to exploit mechanics
- Example: `kill_target: 100.0` → Agent ignores positioning to chase kills

❌ **Conflicting Rewards**: Mixed signals confuse learning
- Example: equal rewards on opposed actions → Random behavior

❌ **Sparse Rewards**: Agent never learns what's good
- Example: Only `win: 1.0`, no intermediate rewards → Random actions

✅ **Good Practice**: Balanced progressive rewards
- Small rewards for good actions (0.1-1.0)
- Medium rewards for tactical wins (1.0-5.0)
- Large rewards for objectives (5.0-50.0)

---

## 📊 MONITORING TRAINING

> **💡 TIP:** Monitoring de base ci-dessous. Pour le tuning (quoi modifier selon les métriques) et l’analyse experte des métriques, voir [AI_METRICS.md](AI_METRICS.md) (inclut le guide de tuning rapide).

### TensorBoard Metrics

Start TensorBoard:
```bash
tensorboard --logdir=./tensorboard/
```

#### 🎯 **Quick Start: The `0_critical/` Dashboard**

**For immediate training monitoring, start here:**

Navigate to the `0_critical/` namespace in TensorBoard - it contains **10 essential metrics** optimized for hyperparameter tuning:

**Primary Metrics to Check Daily:**
- `0_critical/a_bot_eval_combined` - **Your primary goal** (overall competence vs all bots)
- `0_critical/b_win_rate_100ep` - Recent 100-episode performance trend
- `0_critical/g_approx_kl` - Policy stability (<0.02 = healthy)
- `0_critical/h_entropy_loss` - Exploration level (should decrease gradually)
- `0_critical/e_explained_variance` - Value function quality (target: >0.70 early, >0.85 late training)

**✅ Healthy Training:** All `0_critical/` metrics trending toward targets
**⚠️ Red Flag:** Any metric outside range for 200+ episodes needs intervention

**Pour le détail des métriques et le tuning**, voir [AI_METRICS.md](AI_METRICS.md).

---

#### **Other Key Metrics**

| Namespace | Metric | What It Shows | Good Trend |
|-----------|--------|---------------|------------|
| `rollout/` | `ep_rew_mean` | Average episode reward | Increasing |
| `rollout/` | `ep_len_mean` | Episode length | Stable or decreasing |
| `train/` | `entropy_loss` | Exploration level | Decreasing gradually |
| `train/` | `policy_loss` | Policy improvement | Decreasing |
| `train/` | `value_loss` | Value estimation | Decreasing then stable |
| `game_critical/` | `win_rate_100ep` | Rolling win rate | Increasing to target |
| `game_critical/` | `invalid_action_rate` | Action masking health | <5% (ideally <2%) |
| `bot_eval/` | `vs_random` | Performance vs RandomBot | Improving |
| `bot_eval/` | `vs_greedy` | Performance vs GreedyBot | Improving |
| `bot_eval/` | `vs_defensive` | Performance vs DefensiveBot | Improving |
| `bot_eval/` | `combined` | Overall bot evaluation | Increasing to 0.70+ |

### Success Indicators

**Early Training (0-1000 episodes):**
- `rollout/ep_rew_mean`: Should increase from negative to positive
- Wait penalties: Should decrease sharply
- Win rate vs Random bot: 40%+ after 500 episodes

**Mid Training (1000-3000 episodes):**
- `rollout/ep_rew_mean`: Should continue increasing steadily
- Win rate vs Greedy bot: 50%+ after 2000 episodes
- Invalid action rate: Should drop below 5%

**Late Training (3000+ episodes):**
- `rollout/ep_rew_mean`: Steady high values
- Combined bot evaluation: 60%+
- Win rate vs Tactical bots: 50%+ after 4000 episodes

### Red Flags (Training Collapse)

🚨 **Policy Collapse:**
- Symptom: `rollout/ep_rew_mean` drops suddenly
- Cause: Learning rate too high or reward hacking
- Fix: Reduce `learning_rate` by 50%, restart from last checkpoint

🚨 **No Learning:**
- Symptom: Flat `rollout/ep_rew_mean` for 500+ episodes
- Cause: Rewards too sparse or `ent_coef` too low
- Fix: Increase `ent_coef` to 0.15, check reward config

🚨 **Instability:**
- Symptom: `rollout/ep_rew_mean` oscillates wildly
- Cause: Batch size too small or conflicting rewards
- Fix: Increase `n_steps` to 1024, review reward balance

---

## 📊 MÉTRIQUES AVANCÉES ET TUNING

Ce document couvre le **monitoring de base** (TensorBoard, 0_critical/, indicateurs de succès, red flags). Pour aller plus loin :

- **[AI_METRICS.md](AI_METRICS.md)** — Métriques et tuning : guide de tuning rapide (tableau, problèmes courants, matrice métrique → paramètres, actions correctives, n_envs, workflow) + analyse experte (explication détaillée de chaque métrique, patterns, arbres de décision, études de cas). **À utiliser pour « quoi changer quand ça va mal » et pour le diagnostic avancé.**

---

## 🤖 BOT EVALUATION SYSTEM

### Bot Types

**Random Bot (Easiest)**
- Selects random valid actions
- No tactical awareness
- Baseline: Any competent agent should win 90%+

**Greedy Bot (Medium)**
- Always shoots nearest enemy
- Moves toward closest target
- Basic threat: Tests if agent learned shooting
- **Supports randomness parameter** (0.0-0.3) to prevent pattern exploitation

**Tactical Bot (Hard)** _(Also called DefensiveBot)_
- Prioritizes low-HP targets
- Uses cover when available
- Avoids being charged
- Real challenge: Tests full tactical learning
- **Supports randomness parameter** (0.0-0.3) to prevent pattern exploitation

### Evaluation Commands

```bash
# Automatic evaluation during training (configured in training_config callback_params)
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot
# bot_eval_freq, bot_eval_intermediate are in callback_params (e.g. 200 episodes, 30 per bot)

# Manual evaluation (test-only, no training)
python ai/train.py --agent <agent_key> --scenario bot --test-only --test-episodes 20
# Uses model at ai/models/<agent_key>/model_<agent_key>.zip
```

**Eval parameters** (`callback_params`): `bot_eval_freq` (how often), `bot_eval_intermediate` (episodes per bot — 30 recommended for stable estimates without long runs).

**Model gating (production)**:
- `model_gating_enabled=true` active un gate dur avant promotion de modèle.
- Un eval passe le gate uniquement si les 3 conditions sont vraies:
  - `combined >= model_gating_min_combined`
  - `worst_bot_score >= model_gating_min_worst_bot` (`min(random, greedy, defensive)`)
  - `worst_scenario_combined >= model_gating_min_worst_scenario_combined`
- Si le gate échoue:
  - pas de promotion `best_model`,
  - pas de promotion robust (`model_<agent>.zip` non écrasé),
  - logs explicites `PASS/FAIL` par critère.

**Résolution des `callback_params`**:
- Une clé absente ou `null` dans le config agent est résolue via `config/agents/_training_common.json`.
- Si la clé manque aussi dans `_training_common.json`: erreur explicite (fail fast).

### Win Rate Benchmarks

| Training Stage | vs Random | vs Greedy | vs Tactical |
|----------------|-----------|-----------|-------------|
| Start          | 30-40%    | 10-20%    | 0-5%        |
| 1000 episodes  | 60-70%    | 40-50%    | 20-30%      |
| 3000 episodes  | 80-90%    | 60-70%    | 40-50%      |
| 5000 episodes  | 90%+      | 75-85%    | 55-65%      |

---

## 🛡️ ANTI-OVERFITTING STRATEGIES

### The Problem: Pattern Exploitation vs. Robust Tactics

**Symptom**: Agent performs well against GreedyBot and DefensiveBot but fails against RandomBot

**Root Cause**: The agent learned to **exploit predictable patterns** instead of developing robust tactical strategies.

**Example Bad Behavior**:
- Agent assumes enemies always shoot the nearest target (GreedyBot pattern)
- Agent positions based on enemy predictability
- When facing random/unpredictable opponents, strategy falls apart

### Solution 1: Bot Stochasticity (Prevent Pattern Exploitation)

**Location**: `ai/evaluation_bots.py`

Both `GreedyBot` and `DefensiveBot` accept a `randomness` parameter:

```python
GreedyBot(randomness=0.15)    # 15% chance of random action
DefensiveBot(randomness=0.15) # 15% chance of random action
```

**How it works**:
- Bots make their normal strategic decision (100 - randomness)% of the time
- Randomness% of the time they make a random valid action
- This prevents your agent from perfectly predicting and exploiting their behavior

**Tuning recommendations**:
- `0.0` = Pure bot (fully predictable) - use for testing specific strategies
- `0.10` = **Training** - stronger, more consistent opponents (used in `ai/train.py`)
- `0.15` = **Evaluation** - standard benchmark (used in `ai/bot_evaluation.py`)
- `0.20-0.25` = More unpredictable - use if agent overfits to bot patterns
- `0.30+` = Too random, defeats the purpose of strategic bots

**Evaluation bots** (in `ai/bot_evaluation.py`): Equal weight, `randomness=0.15`

**Training bots** (in `ai/train.py`): Weighted 20/40/40, `randomness=0.10` for Greedy/Defensive — see [Solution 4](#solution-4-weighted-training-bots-prevent-randombot-overfitting)

---

### Solution 2: Balanced Reward Penalties (Reduce Over-Aggression)

**Location**: `config/agents/<agent>/<agent>_rewards_config.json`

**Problem**: Overly harsh penalties force hyper-aggressive play that becomes predictable.

**Example adjustments**:
```json
{
  "SpaceMarineRanged": {
    "wait": -0.9           // Moderate penalty (not too harsh)
  }
}
```

**Why this helps**:
- Very harsh wait penalties forced hyper-aggressive play (always seeking shots)
- Aggressive strategies are predictable and exploitable by random opponents
- Moderate values allow tactical patience and positional flexibility

**Tuning recommendations**:
- **Wait penalty**: -0.5 to -1.0 (avoid -2.0+ which forces reckless play)
- **Win/lose**: Keep at ±1.0 for stable training

---

### Solution 3: Increased RandomBot Evaluation Weight

**Location**: `ai/train.py` (model selection logic)

**Old weights**:
```python
combined_score = 0.20 * random + 0.30 * greedy + 0.50 * defensive
```

**New weights** (Recommended):
```python
combined_score = 0.35 * random + 0.30 * greedy + 0.35 * defensive
```

**Why this helps**:
- RandomBot performance now impacts overall score significantly
- Model selection favors agents that handle unpredictability
- Prevents models that only beat predictable opponents from being saved as "best"

**Recommended weighting**:

```python
# Balanced weighting (RECOMMENDED)
combined_score = 0.35 * random + 0.30 * greedy + 0.35 * defensive
```

---

### Solution 4: Weighted Training Bots (Prevent RandomBot Overfitting)

**Symptom**: `b_win_rate_100ep` (training) increases but `a_bot_eval_combined` decreases.

**Root cause**: Agent overfits to RandomBot (easiest opponent) and regresses vs Greedy/Defensive.

**Solution**: Configure bot ratios in `training_config.json` via `bot_training` section.

**Configuration** (in `config/agents/<agent>/<agent>_training_config.json`):

```json
"bot_training": {
  "ratios": {"random": 0.4, "greedy": 0.3, "defensive": 0.3},
  "greedy_randomness": 0.10,
  "defensive_randomness": 0.10
}
```

- **ratios**: Must sum to 1.0. Example: 40% Random, 30% Greedy, 30% Defensive (more wins to learn from).
- **greedy_randomness** / **defensive_randomness**: Lower = stronger bots. Default 0.10 (vs eval's 0.15).

**Defaults** when `bot_training` is omitted: 20% Random, 40% Greedy, 40% Defensive.

---

### How to Use Anti-Overfitting Changes

#### Starting Fresh Training

```bash
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot
```

The new settings will automatically be used if:
- Bot randomness is configured in `evaluation_bots.py` and referenced in training config / train.py
- Reward penalties are balanced in the agent's `*_rewards_config.json`
- Evaluation weights are set in the bot evaluation callback (train.py / bot_evaluation.py)

#### Continue Existing Training

If your agent already learned bad habits:

1. **Option A: Continue training with new rewards**
   - Agent will slowly unlearn over-aggressive patterns
   - Takes 500-1000 episodes to adapt
   - Monitor `bot_eval/vs_random` for improvement

2. **Option B: Start fresh** (Recommended)
   - Faster to learn correct patterns
   - Use if current performance vs RandomBot is very poor (<40% win rate)
   - Delete old model and restart training

---

### Monitoring for Overfitting

Watch these metrics in TensorBoard:

```
bot_eval/vs_random      - Should improve from -0.5 to 0.0+
bot_eval/vs_greedy      - Should stay around 0.05-0.1
bot_eval/vs_defensive   - Should stay around 0.1-0.15
0_critical/a_bot_eval_combined  - Overall score (primary goal)
0_critical/b_win_rate_100ep     - Training win rate
```

**✅ Healthy performance**: All three bots within 0.2 reward range of each other; `bot_eval_combined` and `win_rate_100ep` trend together

**⚠️ Overfitting to predictable bots**: Agent beats Greedy/Defensive but fails vs Random — large gap between random and others (>0.5 difference)

**⚠️ Overfitting to RandomBot**: `win_rate_100ep` ↑ but `bot_eval_combined` ↓ — agent exploits easy opponent. Fix: Apply [Solution 4](#solution-4-weighted-training-bots-prevent-randombot-overfitting) (weighted training bots)

**Example healthy progression**:
```
Episode 1000:
  vs_random: -0.3, vs_greedy: 0.0, vs_defensive: 0.1  (Gap: 0.4 - concerning)

Episode 2000:
  vs_random: -0.1, vs_greedy: 0.1, vs_defensive: 0.15 (Gap: 0.25 - improving)

Episode 3000:
  vs_random: 0.05, vs_greedy: 0.15, vs_defensive: 0.2 (Gap: 0.15 - healthy!)
```

---

### Advanced: Self-Play Training (Future Enhancement)

For future implementation, consider training against copies of your own agent:

```python
# Pseudo-code for self-play
every N episodes:
    save current model as "opponent_snapshot"
    train against mix of:
        - 40% current agent
        - 30% RandomBot
        - 15% GreedyBot(randomness=0.15)
        - 15% DefensiveBot(randomness=0.15)
```

This forces continuous adaptation and prevents exploitation strategies.

---

### Configuration Summary

| Setting | Value | Location | Impact |
|--------|-------|----------|--------|
| GreedyBot/DefensiveBot (eval) | randomness=0.15 | `ai/bot_evaluation.py` | Standard benchmark |
| GreedyBot/DefensiveBot (training) | randomness=0.10 | `ai/train.py` | Stronger opponents during training |
| Training bot ratios | Configurable via `bot_training.ratios` | `training_config.json` | Default 20/40/40; use 40/30/30 for more Random wins |
| RandomBot eval weight | 35% | `ai/bot_evaluation.py` | Higher importance in combined score |
| DefensiveBot eval weight | 35% | `ai/bot_evaluation.py` | Balanced with random |

---

### Troubleshooting Overfitting

**Agent still struggles vs RandomBot after 1000 episodes**:
- Increase GreedyBot/DefensiveBot randomness to 0.20-0.25
- Further reduce wait penalty to -0.5
- Consider starting fresh training
- Check that combined_score weights favor RandomBot performance

**Agent becomes too passive**:
- Increase wait penalty (make more negative: -0.5 → -1.0)
- Check ent_coef isn't too low (should be 0.10+)

**Agent performs poorly against all bots**:
- Rewards may be too balanced (not enough learning signal)
- Increase key rewards: kill_target, damage_target
- Check observation includes enough enemy information
- Verify bot randomness isn't too high (should be ≤0.20)

---

## 🔧 HYPERPARAMETER TUNING GUIDE

### When Agent Isn't Learning

**Problem**: Flat rewards after 500+ episodes

**Try:**
1. Increase `ent_coef` from 0.05 → 0.15 (more exploration)
2. Increase `learning_rate` from 0.0003 → 0.0005
3. Check rewards_config: Are intermediate rewards present?

**Avoid**: Changing multiple parameters at once

---

### When Agent Is Unstable

**Problem**: Reward oscillates wildly

**Try:**
1. Decrease `learning_rate` from 0.001 → 0.0003
2. Increase `n_steps` from 512 → 1024 (more stable updates)
3. Increase `batch_size` from 64 → 128

**Avoid**: Setting `learning_rate` > 0.001

---

### When Training Is Too Slow

**Problem**: 50+ hours for training run

**Try:**
1. Reduce `total_episodes` (use debug config first)
2. Reduce `n_eval_episodes` from 5 → 2
3. Increase `n_steps` from 256 → 1024 (fewer updates)
4. Use CPU instead of GPU (see Performance section)

**Avoid**: Reducing `batch_size` below 64

---

### When Agent Exploits Mechanics

**Problem**: High rewards but nonsensical behavior

**Try:**
1. Review rewards_config: Find the exploited reward
2. Reduce exploited reward by 50%
3. Add balancing penalty (e.g., movement cost)
4. Restart training from earlier checkpoint

**Example**: Agent shoots friendly units for "hit_target" reward
- **Fix**: Ensure `friendly_fire_penalty: -5.0` is present and large

---

## ⚡ PERFORMANCE OPTIMIZATION

### CPU vs GPU

**Current Benchmark**: Training runs **10% faster on CPU** than GPU
- CPU: 311 it/s (optimized)
- GPU: 280 it/s (transfer overhead)

**Recommendation**: Use CPU for training unless batch size > 256

```bash
# Force CPU usage
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --device cpu
```

---

### Training Speed Tips

1. **Use debug config first** - Validate setup in 10 minutes instead of 10 hours
2. **Reduce evaluation frequency** - Set `n_eval_episodes: 2` during development
3. **Increase n_steps** - Larger batches = fewer updates = faster training
4. **Disable verbose logging** - Set `verbose: 0` in model_params

---

## 🐛 TROUBLESHOOTING

### Common Errors

**Error**: `Observation size mismatch (expected 295, got 150)`
- **Cause**: Old model trained with different observation size
- **Fix**: Train new model from scratch or update observation_params

**Error**: `Reward key not found: SpaceMarineXXX`
- **Cause**: Unit archetype not defined in the agent rewards config
- **Fix**: Add the missing reward profile to `config/agents/<agent>/<agent>_rewards_config.json`

**Error**: `CUDA out of memory`
- **Cause**: Batch size too large for GPU
- **Fix**: Switch to CPU or reduce `batch_size`

**Error**: `No improvement in 1000 episodes`
- **Cause**: Rewards too sparse or `ent_coef` too low
- **Fix**: Check rewards_config, increase `ent_coef` to 0.15

---

### Performance Issues

**Symptom**: Training speed < 50 it/s
- Check: Are you using GPU? (CPU is faster)
- Check: Is TensorBoard running? (Disable during training)
- Check: Is `n_steps` too small? (Increase to 1024+)

**Symptom**: Memory usage > 8GB
- Reduce `n_steps` from 2048 → 1024
- Reduce `batch_size` from 256 → 128
- Close TensorBoard during training

---

## 📚 ADVANCED TOPICS (EXTERNAL REFERENCES)

### PPO Algorithm Details
- [Stable-Baselines3 PPO Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
- [PPO Paper (Schulman et al.)](https://arxiv.org/abs/1707.06347)

### Observation Space Internals
- See `w40k_core.py:build_observation()` for implementation
- 295 floats = 72 ally + 138 enemy + 35 targets + 50 self-state

### Reward Calculation Logic
- See `reward_mapper.py:calculate_reward()` for implementation
- Uses RewardMapper class to aggregate rewards from config

### Gym Environment Interface
- See `w40k_core.py:W40KCore` for gym.Env implementation
- Complies with Stable-Baselines3 requirements

---

## 📝 QUICK REFERENCE CHEAT SHEET

```bash
# Training commands (replace <agent_key> e.g. Infantry_Troop_RangedTroop)
python ai/train.py --agent <agent_key> --training-config debug --rewards-config <agent_key> --scenario bot    # Fast test
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot  # Standard training
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --append  # Continue from checkpoint
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --step    # With step logging
python ai/train.py --agent <agent_key> --scenario bot --device cpu   # Force CPU

# Evaluation (no training)
python ai/train.py --agent <agent_key> --scenario bot --test-only --test-episodes 20

# Monitoring
tensorboard --logdir=./tensorboard/

# Key paths
config/agents/<agent>/<agent>_training_config.json  # Training parameters
config/agents/<agent>/<agent>_rewards_config.json   # Reward definitions (per agent)
ai/models/<agent_key>/model_<agent_key>.zip         # Saved model
./tensorboard/                                      # TensorBoard logs
step.log                                            # Step log (with --step) for analyzer & replay viewer

# Success Criteria (5000 episodes)
vs Random: 90%+
vs Greedy: 75%+
vs Tactical: 55%+
```

---

## Évolutions prévues : League / curriculum training

> Ce bloc reprend l’ancien **LEAGUE_CURRICULUM_TRAINING_PLAN.md** fusionné ici. Il décrit l’évolution prévue du pipeline (curriculum puis league) ; non implémenté à ce jour.

### Objectif

Mettre en place un pipeline d'entraînement progressif qui:

1. apprend d'abord des fondamentaux contre bots scriptés,
2. injecte ensuite progressivement des adversaires IA entraînés,
3. améliore la robustesse sans introduire de workaround ni de logique implicite.

Ce plan vise à réduire les oscillations de performance et à éviter les plateaux observés en fin de run.

---

### Pourquoi changer le pipeline actuel

Constat sur les runs récents:

- l'effondrement brutal a été corrigé,
- la performance oscille encore fortement,
- la progression en fin de training devient faible.

Cause probable:

- l'agent apprend dans un environnement trop bruité/non stationnaire (adversaires variés + randomness),
- sans curriculum explicite contre des adversaires entraînés.

Le passage à un league training progressif permet:

- une montée en difficulté contrôlée,
- une meilleure généralisation,
- une robustesse plus stable en évaluation.

---

### Principe retenu (version simple et robuste)

#### Phase 1 - Bots only

- Entraîner uniquement contre bots scriptés.
- Critère de passage vers phase 2 basé sur la performance robuste en évaluation.

#### Phase 2 - Mix progressif bots/agents

- Début: 80% bots / 20% agents entraînés.
- Fin: 20% bots / 80% agents entraînés.
- Progression linéaire des ratios sur la durée de la phase 2.

Ce design ne dépend pas d'un Elo/PFSP au départ (volontairement simple).

---

### Schéma de configuration JSON proposé

À ajouter dans les profils d'entraînement (`default`, `stabilize`) de
`config/agents/<agent>/<agent>_training_config.json`.

#### Exemple phase 1 (`default`)

```json
"curriculum": {
  "enabled": true,
  "phase_id": 1,
  "advance_to_phase2": {
    "metric": "bot_eval/combined",
    "threshold": 0.75,
    "worst_bot_metric": "bot_eval/worst_bot_score",
    "worst_bot_threshold": 0.60,
    "max_drawdown": 0.08,
    "min_evals": 5,
    "require_consecutive": 3
  }
}
```

#### Exemple phase 2 (`stabilize`)

```json
"curriculum": {
  "enabled": true,
  "phase_id": 2,
  "league_opponent_deterministic": true,
  "opponent_mix": {
    "bot_ratio": { "start": 0.80, "end": 0.20 },
    "trained_agent_ratio": { "start": 0.20, "end": 0.80 }
  },
  "trained_opponent_pool": {
    "strategy": "recent_snapshots",
    "max_models": 8,
    "include_best_robust": true,
    "include_best_model": true,
    "include_recent_checkpoints": true
  }
}
```

---

### Mise en pratique dans les scripts

#### 1) `ai/train.py`

**À ajouter**

- Lecture stricte de `training_config["curriculum"]`.
- Validation stricte des champs requis selon `phase_id`.
- Construction d'un `opponent_selector`:
  - phase 1: bots uniquement,
  - phase 2: bots + modèles entraînés selon ratio courant.

**Logique ratio en phase 2**

```python
progress = episodes_trained / total_episodes_phase2
bot_ratio = bot_start + (bot_end - bot_start) * progress
agent_ratio = 1.0 - bot_ratio
```

**Construction du pool d'adversaires entraînés**

Depuis `ai/models/<agent_key>/`:

- `best_robust_model.zip`,
- `best_model.zip`,
- checkpoints récents (`ppo_checkpoint_*`), triés et limités à `max_models`.

Si aucun modèle éligible alors erreur explicite (pas de fallback silencieux).

**Politique de rétention des checkpoints (important)**

Les checkpoints `ppo_checkpoint_*` servent à:

- constituer le pool league d'adversaires entraînés,
- reprendre un run depuis un point intermédiaire,
- diagnostiquer une régression tardive (rollback ciblé).

Recommandation:

- ajouter un flag de config explicite (ex: `retain_training_checkpoints`) pour conserver/supprimer les checkpoints en fin de run,
- ne pas hardcoder la suppression dans le script quand la league est activée.

---

#### 2) `ai/env_wrappers.py`

**Nouveau wrapper recommandé: `LeagueControlledEnv`**

Rôle:

- à chaque `reset()`, tirer un type d'adversaire selon les ratios courants:
  - bot scripté,
  - agent entraîné.
- exécuter ensuite le tour adverse avec l'interface actuelle (`predict(..., action_masks=...)`).

Comportement attendu:

- deterministic piloté par config (`league_opponent_deterministic`) pour les adversaires entraînés,
- conservation du comportement bots existant.

---

#### 3) `ai/training_callbacks.py`

**Gate de transition phase 1 -> phase 2**

Ajouter un callback de validation de passage:

- lit la métrique cible (`bot_eval/combined`),
- vérifie `threshold`, `min_evals`, `require_consecutive`,
- vérifie un second garde-fou: `worst_bot_score >= worst_bot_threshold`,
- vérifie une borne de régression: `drawdown <= max_drawdown`,
- stoppe proprement la phase 1 quand le critère est rempli.

Pas de bascule implicite sans conditions validées.

---

#### 4) `ai/bot_evaluation.py`

Le pipeline actuel (normalisation éval via `vec_normalize_eval`) reste valide.

Recommandation:

- conserver un set d'évaluation fixe bots,
- ajouter ensuite un set d'évaluation league séparé,
- ne pas réutiliser exactement le même pool pour train et eval finale.

---

### Plan d'intégration recommandé

**Étape 1 - Infra minimale (sans changer les métriques)**

- Ajouter `curriculum` en config.
- Implémenter validation des clés.
- Ajouter `LeagueControlledEnv`.
- Ajouter construction du pool d'adversaires entraînés.

**Étape 2 - Transition contrôlée**

- Activer gate phase 1 -> phase 2.
- Démarrer la phase 2 avec ratio 80/20 et progression linéaire.

**Étape 3 - Stabilisation et mesure**

- Suivre:
  - `bot_eval/combined`,
  - `bot_eval/worst_bot_score`,
  - `0_critical/b_win_rate_100ep`,
  - `0_critical/g_approx_kl`,
  - `0_critical/f_clip_fraction`.

---

### Critères de succès

Le changement est considéré positif si:

1. disparition des régressions fortes en fin de run,
2. hausse du `worst_bot_score` moyen,
3. variance réduite sur `combined` à budget d'épisodes comparable,
4. amélioration de la robustesse inter-runs (moins de dépendance seed).

---

### Risques et mitigations

- **Risque:** surapprentissage à la league locale.
  - **Mitigation:** conserver 20% bots en fin de phase 2.

- **Risque:** non-stationnarité trop forte.
  - **Mitigation:** pool borné (`max_models`) + snapshots figés.

- **Risque:** complexité de debug.
  - **Mitigation:** logs explicites par épisode:
    - type d'adversaire tiré,
    - identifiant du modèle adverse,
    - ratio courant bots/agents.

---

### Décision

Approche recommandée: **implémenter une v1 simple sans Elo/PFSP**, puis ajouter un rating seulement si nécessaire.

Ce plan donne un gain robuste à coût d'implémentation maîtrisé, compatible avec l'architecture actuelle.

---

## 🎯 SUMMARY

**Ce document est la référence unique pour tout le training et le tuning** : pipeline, configs, monitoring, hyperparamètres, anti-overfitting, dépannage.

**Principe clé** : entraînement en complexité complète dès le début (pas de curriculum).

**Tout ce qui concerne training / tuning** : dans ce document (AI_TRAINING.md). Compléments :
- **Métriques et tuning (quoi changer, diagnostic)** → [AI_METRICS.md](AI_METRICS.md)
- **Moteur de jeu** → [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md), `engine/w40k_core.py`
- **Règles de tour** → [AI_TURN.md](AI_TURN.md)

En pratique : modifier les configs agent (`*_training_config.json`, `*_rewards_config.json`), surveiller TensorBoard, ajuster les hyperparamètres selon les métriques (voir AI_METRICS). Entraînement itératif : commencer en config debug, valider, puis monter en charge.