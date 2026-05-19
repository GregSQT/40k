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
- [Seat-Aware Training (P1/P2/Random)](#-seat-aware-training-p1--p2--random)
  - [Concept](#concept)
  - [Architecture](#architecture-seat)
  - [Observation égocentrique](#observation-égocentrique)
  - [Reward seat-aware](#reward-seat-aware)
  - [Configuration](#configuration-seat)
  - [Évaluation cross-seat](#évaluation-cross-seat)
  - [Contraintes connues](#contraintes-connues)
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
  - [Dynamic Roster Generation (150pts)](#dynamic-roster-generation-150pts)
  - [Organisation Training — Agent Unique](#organisation-training--agent-unique)
  - [Reward Design Philosophy](#reward-design-philosophy)
  - [Target Priority & Positioning](#target-priority--positioning)
- [Configuration Files](#️-configuration-files)
  - [training_config.json Structure](#trainingconfigjson-structure)
  - [Unit Rules Implementation Flags (`RULES_STATUS`)](#unit-rules-implementation-flags-rules_status)
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
- [Pipeline opérationnel holdout hard (CoreAgent 150pts)](#-pipeline-opérationnel-holdout-hard-coreagent-150pts)
  - [Objectif](#objectif)
  - [Étape 0 — Préparation rosters et scénarios](#étape-0--préparation-rosters-et-scénarios)
  - [Étape 1 — Matrices BOT rapides (e12)](#étape-1--matrices-bot-rapides-e12)
  - [Étape 2 — Rebalancing BOT](#étape-2--rebalancing-bot)
  - [Étape 3 — Revalidation robuste (e30)](#étape-3--revalidation-robuste-e30)
  - [Étape 4 — Validation finale ciblée (e50)](#étape-4--validation-finale-ciblée-e50)
  - [Étape 5 — Boost des rosters faibles](#étape-5--boost-des-rosters-faibles)
- [Advanced Topics (External References)](#-advanced-topics-external-references)
- [Quick Reference Cheat Sheet](#-quick-reference-cheat-sheet)
- [Summary](#-summary)

---

## 📋 QUICK START

### Run Training
```bash
# From project root (--agent obligatoire pour entraînement ciblé)
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot   # Entraînement standard (P1)
python ai/train.py --agent <agent_key> --scenario bot --new --param agent_seat_mode p2                         # Entraînement en P2
python ai/train.py --agent <agent_key> --scenario bot --new --param agent_seat_mode random                     # Entraînement seat aléatoire
python ai/train.py --agent <agent_key> --scenario bot --test-only --step --test-episodes 50                    # Test rapide avec logs
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
  - `--scenario <name>` : scénario ou mode (`bot`, `default`, `phase1`, etc.). Avec `bot`, l’adversaire est un mix configurable de 7 bots (Tier 1 : Random, Greedy, Defensive, Control ; Tier 2 : AggressiveSmart, DefensiveSmart, Adaptive).
- **Options utiles** : `--step` (écrit `step.log`), `--test-only` (pas d’apprentissage, évaluation uniquement), `--eval` (alias de `--test-only`), `--test-episodes N`, `--append` (reprendre un modèle existant), `--new-model` (partir de zéro).

### Chargement de la config

- **config_loader** (`config_loader.py`) :
  - `load_agent_training_config(agent_key, training_config_name)` → charge `config/agents/<agent>/<agent>_training_config.json` et retourne le bloc demandé (ex. `default`). Gère `inherits_from` (héritage vers un autre dossier d’agent).
  - `load_agent_rewards_config(agent_key)` → charge `config/agents/<agent>/<agent>_rewards_config.json`.
  - `get_models_root()` → racine des modèles (ex. `ai/models/`).
- **UnitRegistry** (`ai/unit_registry.py`) : mappe `unit_type` (ex. type d’unité du scénario) vers `model_key` (clé d’agent pour charger le bon micro-modèle). Requis pour créer le moteur et les wrappers (BotControlledEnv, macro).

#### Scénarios minces + rosters compacts

- Un scénario peut rester en format legacy (`"units": [...]`) ou pointer vers des rosters via:
  - `"scale"` (ex: `"150pts"`),
  - `"agent_roster_ref"` : roster de l'agent (chargé depuis `config/agents/<agent>/rosters/<scale>/`),
  - `"opponent_roster_ref"` : roster de l'adversaire (chargé depuis `config/agents/_p2_rosters/<scale>/`).
- Le mapping agent/opponent → Player 1/2 est résolu au runtime par `controlled_player` (voir [Seat-Aware Training](#-seat-aware-training-p1--p2--random)).
- En holdout, `agent_roster_ref` doit être explicite et séparé par difficulté:
  - `holdout_regular/...` pour les scénarios dans `scenarios/holdout_regular/`
  - `holdout_hard/...` pour les scénarios dans `scenarios/holdout_hard/`
- Pour `agent_roster_ref`, un alias est supporté en training:
  - `"training_random"` -> tirage aléatoire d’un roster dans `rosters/<scale>/training/` (liste triée avant tirage).
- Optionnel: `"agent_roster_seed"` (int >= 0) pour forcer un tirage déterministe local du roster agent.
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
- En training, `agent_roster_ref` peut être une liste pour tirage aléatoire par épisode; en holdout, utiliser une ref unique déterministe.
- `step.log` journalise les rosters sélectionnés en début d’épisode (`Rosters: ...`).

### Création de l’environnement

1. **Moteur de base** : `W40KEngine` (`engine/w40k_core.py`) avec :
   - `rewards_config=rewards_config_name`, `training_config_name=...`, `controlled_agent=controlled_agent_key`,
   - `scenario_file` ou `scenario_files` (liste pour tirage aléatoire),
   - `unit_registry=unit_registry`, `gym_training_mode=True`.
2. **Step logger** (si `--step`) : `StepLogger("step.log", ...)` attaché à `base_env.step_logger` ; désactivé pour les envs vectorisés (SubprocVecEnv).
3. **ActionMasker** : wrapper SB3 `ActionMasker(base_env, mask_fn)` avec `mask_fn(env) = env.get_action_mask()` pour MaskablePPO.
4. **Adversaire** :
   - **Scénario bot** : `BotControlledEnv(masked_env, bots=training_bots, unit_registry=unit_registry, agent_seat_mode=..., global_seed=..., env_rank=...)`. Les bots sont instanciés dynamiquement à partir de `training_config` (`bot_training.ratios` + `bot_training.randomness`) — 7 bots disponibles : Tier 1 (Random, Greedy, Defensive, Control) et Tier 2 (AggressiveSmart, DefensiveSmart, Adaptive). Le `agent_seat_mode` détermine quel joueur l'agent contrôle (voir [Seat-Aware Training](#-seat-aware-training-p1--p2--random)).
   - **Self-play** : `SelfPlayWrapper(masked_env, ...)` (autre joueur = copie du modèle, mise à jour périodique).
5. **Monitor** : `Monitor(wrapped_env)` pour les stats d’épisode (reward, length) utilisées par TensorBoard et les callbacks.

Pour l’entraînement vectorisé, `make_training_env()` dans `ai/training_utils.py` encapsule cette construction (W40KEngine → ActionMasker → BotControlledEnv ou SelfPlayWrapper → Monitor).

### Modèle et boucle d’entraînement

- **Modèle** : `MaskablePPO` (sb3_contrib). Chargement depuis `ai/models/<agent_key>/model_<agent_key>.zip` ; sauvegarde via callbacks (CheckpointCallback) et à la fin de l’entraînement.
- **Callbacks** (définis dans `train.py`, paramétrés par `training_config["callback_params"]`) : sauvegarde de checkpoints, évaluation périodique contre les bots (`BotEvaluationCallback` : `bot_eval_freq`, `bot_eval_intermediate`), logging TensorBoard.
- **Boucle** : `model.learn(total_timesteps=...)` (ou équivalent selon le mode). Chaque step : `action = model.predict(obs, action_masks=mask)` puis `env.step(action)`.

**Références code** : `ai/train.py`, `ai/training_utils.py` (`make_training_env`), `ai/env_wrappers.py` (BotControlledEnv, SelfPlayWrapper), `engine/w40k_core.py` (W40KEngine).

---

## 🎮 SEAT-AWARE TRAINING (P1 / P2 / RANDOM)

L'agent peut être entraîné en tant que Player 1, Player 2, ou en alternance aléatoire par épisode. Le pipeline garantit que toutes les observations, rewards et métriques sont **égocentriques** : l'agent voit toujours "mes unités" vs "unités ennemies", indépendamment du numéro de joueur.

### Concept

Trois modes d'entraînement via `agent_seat_mode` :

| Mode | `controlled_player` | Comportement |
|------|---------------------|-------------|
| `p1` | Toujours 1 | Agent = Player 1, Bot = Player 2 |
| `p2` | Toujours 2 | Agent = Player 2, Bot = Player 1 |
| `random` | 1 ou 2 par épisode | Tirage déterministe par `(global_seed, env_rank, episode_index)` |

En mode `random`, le tirage est indépendant par sous-env vectorisé. Seuils d'audit : écart épisodes ≤ 5%, écart timesteps ≤ 10%, fenêtre ≥ 2000 épisodes.

### Architecture (seat)

Le seat est résolu à chaque `reset()` d'épisode dans `BotControlledEnv` :

1. `_resolve_controlled_player_for_episode()` → détermine `controlled_player` (1 ou 2)
2. `_apply_episode_seat()` → écrit dans `engine.config` et `game_state` :
   - `controlled_player` : joueur contrôlé par l'agent
   - `opponent_player` : joueur contrôlé par le bot
3. `_play_bot_until_control_returns()` → le bot joue jusqu'à ce que l'agent ait une décision à prendre

**Source de vérité unique** : `engine.config["controlled_player"]` est la seule source runtime. Écriture autorisée uniquement au reset d'épisode. Toute logique reward/metrics/eval lit cette valeur.

**Roster mapping** : Les scénarios définissent `agent_roster_ref` et `opponent_roster_ref`. Au chargement (`game_state.py:_load_units_from_roster_refs`), l'agent roster est assigné au `controlled_player` et l'opponent roster au `opponent_player`. Les IDs d'unités suivent la convention historique : Player 1 = `[1..N]`, Player 2 = `[101..N]`.

### Observation égocentrique

Toutes les features de l'observation flat sont relatives à l'unité active (qui appartient toujours au `controlled_player`) :

| Feature | Encodage | Référence |
|---------|----------|-----------|
| `obs[0]` (turn ownership) | `1.0` si c'est le tour de l'unité active, `0.0` sinon | `current_player == active_unit["player"]` |
| Objective control (`obs[11:16]`) | `+1.0` = contrôlé par mon camp, `-1.0` = ennemi | `active_unit["player"]` pour my/enemy OC |
| Allied units | Filtré par `unit["player"] == active_unit["player"]` | Positions/HP relatifs à l'unité active |
| Enemy units | Filtré par `unit["player"] != active_unit["player"]` | Idem |
| Army value diff (macro) | `my_value - enemy_value` basé sur `current_player` | `_calculate_army_value_diff()` |
| Macro objective control_state | `+1.0`/`-1.0` recalculé à chaque observation | Cache `macro_objectives` invalidé par `build_observation()` |
| Directional helpers (friendly/enemy) | `unit["player"]` pour target_player | `_find_nearest_in_direction()` |

**Invariant critique** : Pendant `build_observation()`, `game_state["current_player"] == active_unit["player"]`. Toute utilisation de `current_player` dans les helpers est donc correcte dans ce contexte.

**Cache `macro_objectives`** : Ce cache contient des `control_state` relatifs au joueur courant. Il est invalidé (`game_state.pop("macro_objectives", None)`) au début de chaque `build_observation()` pour éviter qu'un calcul fait pendant le tour du bot ne pollue l'observation de l'agent.

### Reward seat-aware

Le `RewardCalculator` (`engine/reward_calculator.py`) filtre les rewards par joueur :

1. **Actions non-contrôlées** : si `acting_unit["player"] != controlled_player` → seuls les rewards objectifs par tour et situationnels (game_over) sont retournés. Pas de reward d'action pour les coups du bot.

2. **Actions contrôlées** : reward complète (base_action + result_bonuses + tactical_bonuses + situational).

3. **Reward situationnelle** (`_get_situational_reward`) :
   - `winner == controlled_player` → bonus win
   - `winner == opponent_player` → pénalité lose
   - `winner == -1` → reward draw
   - Si toutes les unités contrôlées sont éliminées (`_get_controlled_player_unit() is None`) : le penalty lose/draw est quand même appliqué via la config rewards.

4. **Reward objectifs par tour** (`_calculate_objective_reward_per_turn`) : nombre d'objectifs contrôlés par `controlled_player` × `reward_per_objective`. Appliqué une fois par tour à la transition vers la phase move.

5. **Victory Points** : scorés par joueur absolu (P1 et P2 scorent indépendamment). Le winner est déterminé par comparaison VP à la fin du turn 5.

### Configuration (seat)

**training_config.json** :
```json
{
  "agent_seat_mode": "p1",
  "agent_seat_seed": 42
}
```

- `agent_seat_mode` : `"p1"` | `"p2"` | `"random"` (obligatoire)
- `agent_seat_seed` : seed pour le mode random (obligatoire si `random`)

**CLI override** :
```bash
python ai/train.py --agent CoreAgent --scenario bot --new --param agent_seat_mode p2
python ai/train.py --agent CoreAgent --scenario bot --new --param agent_seat_mode random
```

Le `--param` override s'applique à tous les chargements de config via monkey-patch sur `config_loader.load_agent_training_config`.

### Évaluation cross-seat

L'évaluation bot (`evaluate_against_bots`) lit `agent_seat_mode` depuis la training config. Le `--param` override fonctionne aussi en mode `--eval` :

```bash
# Évaluer le modèle courant en tant que P1
python ai/train.py --agent CoreAgent --eval --param agent_seat_mode p1 --test-episodes 100

# Évaluer le même modèle en tant que P2
python ai/train.py --agent CoreAgent --eval --param agent_seat_mode p2 --test-episodes 100
```

**Protocole de validation cross-seat** : pour vérifier si un gap de performance P1/P2 est structurel (going-second) ou dû à un bug, évaluer un même modèle dans les deux seats. Un drop symétrique (~10-15 pts) en P2 confirme le désavantage going-second.

### Contraintes connues

**Désavantage going-second** : En W40K, Player 1 agit en premier chaque tour (move → shoot → charge → fight). Player 2 subit les actions de P1 avant de pouvoir réagir. Cela crée un désavantage structurel pour P2 (~10-15 pts win_rate) qui n'est pas un bug mais une propriété du jeu. Un modèle entraîné en mode `random` apprend à compenser ce désavantage.

**Métriques seat-aware** : Les métriques TensorBoard (`win_rate_100ep`, `episode_reward_smooth`, `victory_points_cumulative_mean`) sont toutes calculées du point de vue du `controlled_player`. Comparer directement les courbes P1 vs P2 nécessite de prendre en compte le going-second.

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

### Dynamic Roster Generation (150pts)

Le pipeline utilise `scripts/build_dynamic_rosters.py` (version consolidée v21) pour générer des rosters dynamiques compatibles avec le format compact attendu par les scénarios.

**Entrées nécessaires**
- `reports/unit_sampling_matrix.json` (généré par `scripts/unit_classifier.py`)
- `matrix["unit_values"]` est requis (mapping `"roster::unit_type" -> VALUE`)

**Important**
- Le générateur de rosters ne parse plus les fichiers TypeScript pour `NAME/VALUE`.
- Si `unit_values` est absent de la matrice, le script échoue explicitement.

**Ce que fait le script**
- Génère des rosters par `target_tanking` (`Swarm|Troop|Elite`) avec budget `points-scale +/- points-tolerance` (défaut `150 +/- 2`).
- Utilise des poids issus de la matrice:
  - `blend_group` (inverse-sqrt),
  - `mobility_weights`,
  - `weapon_profile_weights`,
  - densité de cellule (`count`).
- Applique des contraintes de robustesse:
  - faisabilité budget en cours de construction (lookahead),
  - `max-copies-per-unit`,
  - anti-répétition globale (`anti-repeat-window`, `anti-repeat-penalty`).
- Génère des matchups optionnels avec buckets VALUE:
  - `strict/medium/wide`,
  - ratios configurables (`matchup-ratio-*`),
  - équilibrage optionnel du signe des gaps (`--enforce-matchup-sign-balance`) sans inversion de rôles P1/P2.
- Exporte des KPIs de génération (`..._kpis_v21.json`) et matchups (`..._matchups.json`).

**Workflow recommandé**
```bash
# 1) Rebuild classification + matrix (inclut unit_values)
python scripts/unit_classifier.py --roster all

# 2) Génération training (exemple Troop)
python scripts/build_dynamic_rosters.py \
  --target-tanking Troop \
  --points-scale 150 \
  --num-rosters 200 \
  --units-per-roster 5 \
  --split training

# 3) Génération holdout (exemple Troop)
python scripts/build_dynamic_rosters.py \
  --target-tanking Troop \
  --points-scale 150 \
  --num-rosters 60 \
  --units-per-roster 5 \
  --split holdout
```

**Sorties par défaut**
- `config/agents/_p2_rosters/150pts/training/`
- `config/agents/_p2_rosters/150pts/holdout/`

---

### Organisation Training — Agent Unique

Ce mode vise un **seul agent PPO** entraîné sur une distribution de situations variées, plutôt que 3 agents séparés par tanking.

**Principe**
- Un seul `agent_key` en entraînement (`ai/train.py --agent <agent_key>`).
- La diversité est apportée par:
  - les rosters dynamiques (mix de profils),
  - les buckets de gap VALUE (`strict/medium/wide`),
  - les bots d’entraînement pondérés.
- Le tanking reste un signal observé, mais ne sert plus à définir des modèles distincts.

**Organisation pratique**
1. Rebuild matrix (`unit_classifier.py --roster all`) après chaque update roster.
2. Générer les rosters P2 150pts (training/holdout) avec `build_dynamic_rosters.py`.
3. Pointer les scénarios training/holdout vers les refs rosters 150pts.
4. Entraîner un seul agent sur ce flux.
5. Valider via holdout régulier + holdout dur + robust gating.

**KPIs à suivre en priorité**
- `rejection_rate_roster_budget`
- `distribution_drift_blend/mobility/weapon_profile`
- `matchup_value_gap_mean`, `matchup_value_gap_p95`
- `%matchups_in_strict/medium/wide_bucket`
- métriques RL standard (`0_critical/*`, `bot_eval/*`)

**Commande type (agent unique)**
```bash
python ai/train.py \
  --agent <agent_unique_key> \
  --training-config default \
  --rewards-config <agent_unique_key> \
  --scenario bot
```

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
      "bot_eval_use_subprocess": true,   // ProcessPoolExecutor for eval tasks (set false to force serial)
      "bot_eval_n_workers": 6,           // Number of eval workers when subprocess mode is enabled
      "bot_eval_task_timeout_seconds": 300, // Per-task timeout in parallel eval
      "bot_eval_worker_device": "cpu",   // Model device in eval workers: "cpu" or "auto"
      "save_best_robust": true,          // If true, canonical model comes from robust selection
      "robust_window": 3,                // Moving window size for robust score
      "robust_drawdown_penalty": 0.5,    // Drawdown penalty applied to robust score
      "model_gating_enabled": true,      // Enable hard gating before model promotion
      "model_gating_min_combined": 0.55, // Min combined score required
      "model_gating_min_worst_bot": 0.45, // Min(min random, greedy, defensive)
      "model_gating_min_worst_scenario_combined": 0.45 // Min scenario combined required
    },

    "observation_params": {
      "obs_size": 355,                   // Total observation vector size (CoreAgent v2.4 rule-aware; legacy mode = 323)
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

### Unit Rules Implementation Flags (`RULES_STATUS`)

Cette feature sert a distinguer une regle **declaree** d'une regle **effectivement appliquee** dans le moteur.

Conventions dans les fichiers d'unites (`frontend/src/roster/**/units/*.ts`):

- `UNIT_RULES`: regles declarees/capacites de l'unite (source metier)
- `RULES_STATUS`: statut d'implementation technique de chaque `ruleId`

Exemple:

```ts
static UNIT_RULES = [{ ruleId: "closest_target_penetration", displayName: "Close-quarter firepower" }];
static RULES_STATUS = { closest_target_penetration: 2 };
```

Valeurs de `RULES_STATUS`:

- `0` = `NOT_IMPLEMENTED`
- `1` = `NOT_IMPLEMENTABLE_YET`
- `2` = `IMPLEMENTED`

Regles pratiques:

- Une regle ne passe a `2` que si son effet est valide dans les handlers runtime (pas seulement declaree).
- Pour les regles composees (`grants_rule_ids`), il faut statuer le `ruleId` parent et les regles accordees.
- En cas d'ambiguite, laisser `0` tant que le test runtime n'est pas valide.

Note de nomenclature:

- Correction appliquee: `move_after_shouting` -> `move_after_shooting`.

Reference audit:

- `Documentation/RULES_IMPLEMENTATION_AUDIT_CHECKLIST.md`

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
| `bot_eval/` | `vs_control` | Performance vs ControlBot | Improving |
| `bot_eval/` | `vs_aggressive_smart` | Performance vs AggressiveSmartBot | Improving |
| `bot_eval/` | `vs_defensive_smart` | Performance vs DefensiveSmartBot | Improving |
| `bot_eval/` | `vs_adaptive` | Performance vs AdaptiveBot | Improving |
| `bot_eval/` | `combined` | Weighted average across all 7 bots | Increasing to 0.70+ |

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

#### Tier 1 — Bots simples (comportement fixe)

**RandomBot (Easiest)**
- Selects random valid actions
- No tactical awareness
- Baseline: Any competent agent should win 90%+

**GreedyBot (Medium)**
- Always shoots nearest enemy, moves aggressively (action 0)
- Basic threat: Tests if agent learned shooting
- **Supports randomness parameter** (0.0-0.3)

**DefensiveBot (Medium-Hard)**
- Moves defensively (action 2) when threatened, waits otherwise
- Shoots first available target systematically
- Tests tactical patience and positioning
- **Supports randomness parameter** (0.0-0.3)

**ControlBot (Medium)**
- Moves toward objectives (action 3) when off-objective, holds position once on
- Objective-focused: Tests if agent can contest/control objectives
- **Supports randomness parameter** (0.0-0.3)

#### Tier 2 — Bots intelligents (comportement contextuel)

**AggressiveSmartBot (Hard)**
- Aggressive movement (action 0), always charges (action 9), advances (action 12) if no targets
- Focus fire: lowest-HP enemy (achever les cibles faibles)
- Forces l'agent à apprendre advance et charge par exposition

**DefensiveSmartBot (Hard)**
- Defensive movement (action 2) if threatened, tactical (action 1) otherwise
- Never charges or advances — purely positional
- Focus fire: highest-threat enemy (neutraliser les menaces)
- Tests if agent can beat a cautious, threat-aware opponent

**AdaptiveBot (Hardest)**
- Adapts strategy based on game state (early/winning/losing postures)
- Early: objective movement (action 3); Winning: defensive; Losing: aggressive + charge
- Focus fire: lowest-HP enemy
- The most challenging bot — tests full adaptive tactical learning

### Evaluation Commands

```bash
# Automatic evaluation during training (configured in training_config callback_params)
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot
# bot_eval_freq, bot_eval_intermediate are in callback_params (e.g. 200 episodes, 30 per bot)

# Manual evaluation (test-only, no training)
python ai/train.py --agent <agent_key> --scenario bot --test-only --test-episodes 20
# Equivalent alias:
python ai/train.py --agent <agent_key> --scenario bot --eval --test-episodes 20
# Uses model at ai/models/<agent_key>/model_<agent_key>.zip
```

### Runtime architecture (current implementation)

- `evaluate_against_bots()` (`ai/bot_evaluation.py`) est le point unique d’évaluation.
- Mode parallèle: `ProcessPoolExecutor` avec contexte `spawn` (isolation process stricte).
- Worker initializer: le modèle + normalizer sont chargés une seule fois par worker.
- Fallback sérial forcé si `step_logger` actif ou `debug_mode=true` (évite objets non picklables et facilite le debug).
- Seeds d’épisode déterministes via `hashlib.md5` (`_episode_seed`).
- En mode parallèle, la collecte est robuste aux hangs:
  - polling non-bloquant (`wait(..., FIRST_COMPLETED)`),
  - deadline par tâche (`bot_eval_task_timeout_seconds`),
  - arrêt forcé du pool si timeout détecté,
  - marquage des tâches restantes en timeout (`failed_episodes`).

**Eval parameters** (`callback_params`) :
- fréquence/volume: `bot_eval_freq`, `bot_eval_intermediate`, `bot_eval_final`, `bot_eval_use_episodes`
- parallélisation: `bot_eval_use_subprocess`, `bot_eval_n_workers`, `bot_eval_worker_device`
- robustesse runtime: `bot_eval_task_timeout_seconds`

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

**Sorties runtime d'évaluation** (`evaluate_against_bots`) :
- `total_failed_episodes`: nombre total d’épisodes échoués (timeouts/erreurs agrégés)
- `eval_reliable`: `true` si `total_failed_episodes == 0`, sinon `false`
- `eval_duration_seconds`: durée murale de l’évaluation
- `scenario_bot_stats` / `scenario_scores`: agrégats par scénario (utilisés par les gates robustesse)

### Win Rate Benchmarks

| Training Stage | vs Random | vs Greedy | vs Defensive | vs Control | vs Tier 2 (avg) |
|----------------|-----------|-----------|--------------|------------|-----------------|
| Start          | 30-40%    | 10-20%   | 5-15%        | 10-20%     | 0-10%           |
| 1000 episodes  | 60-70%    | 40-50%   | 30-40%       | 35-45%     | 15-25%          |
| 3000 episodes  | 80-90%    | 60-70%   | 50-60%       | 55-65%     | 35-45%          |
| 5000 episodes  | 90%+      | 75-85%   | 65-75%       | 65-75%     | 50-60%          |

---

## 🛡️ ANTI-OVERFITTING STRATEGIES

### The Problem: Pattern Exploitation vs. Robust Tactics

**Symptom**: Agent performs well against simple bots (Greedy, Defensive) but fails against RandomBot or Tier 2 bots

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

### Solution 3: Balanced Multi-Bot Evaluation Weights

**Location**: `config/agents/<agent>/<agent>_training_config.json` → `callback_params.bot_eval_weights`

**Configuration actuelle** (7 bots) :
```json
"bot_eval_weights": {
  "random": 0.10,
  "greedy": 0.15,
  "defensive": 0.15,
  "control": 0.15,
  "aggressive_smart": 0.15,
  "defensive_smart": 0.15,
  "adaptive": 0.15
}
```

**Why this helps**:
- Evaluation couvre 7 profils tactiques distincts (Tier 1 + Tier 2)
- Poids équilibrés entre bots — aucun bot ne domine le score
- RandomBot conserve un poids (10%) pour détecter les régressions de base
- Les bots Tier 2 (advance, charge, focus fire) forcent l'agent à développer des tactiques avancées

**Randomness par bot** (dans `callback_params.bot_eval_randomness`) :
- Tier 1 : `0.05` (Greedy, Defensive, Control) — peu de bruit, benchmark stable
- Tier 2 : `0.1` (AggressiveSmart, DefensiveSmart, Adaptive) — léger bruit pour variabilité

---

### Solution 4: Weighted Training Bots (Multi-Tier)

**Symptom**: `b_win_rate_100ep` (training) increases but `a_bot_eval_combined` decreases.

**Root cause**: Agent overfits to simple bots and never apprend advance/charge/focus fire.

**Solution**: Configure bot ratios et randomness dans `training_config.json` via `bot_training`.

**Configuration actuelle** (in `config/agents/<agent>/<agent>_training_config.json`):

```json
"bot_training": {
  "ratios": {
    "random": 0.10,
    "greedy": 0.15,
    "defensive": 0.15,
    "control": 0.15,
    "aggressive_smart": 0.15,
    "defensive_smart": 0.15,
    "adaptive": 0.15
  },
  "randomness": {
    "greedy": 0.05,
    "defensive": 0.05,
    "control": 0.05,
    "aggressive_smart": 0.1,
    "defensive_smart": 0.1,
    "adaptive": 0.1
  }
}
```

- **ratios**: Must sum to 1.0. Distribution identique entre eval et training pour cohérence.
- **randomness**: Format unifié (dict imbriqué). Tier 1 = `0.05`, Tier 2 = `0.1`.

**Defaults** when `bot_training` is omitted: 20% Random, 40% Greedy, 40% Defensive (legacy).

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
        - 10% RandomBot
        - 15% GreedyBot + 15% DefensiveBot + 15% ControlBot
        - 15% AggressiveSmartBot + 15% DefensiveSmartBot + 15% AdaptiveBot
```

This forces continuous adaptation and prevents exploitation strategies.

---

### Configuration Summary

| Setting | Value | Location | Impact |
|--------|-------|----------|--------|
| Tier 1 bots (eval) | randomness=0.05 | `training_config.json` → `bot_eval_randomness` | Benchmark stable |
| Tier 2 bots (eval) | randomness=0.10 | `training_config.json` → `bot_eval_randomness` | Variabilité contrôlée |
| Tier 1 bots (training) | randomness=0.05 | `training_config.json` → `bot_training.randomness` | Adversaires forts |
| Tier 2 bots (training) | randomness=0.10 | `training_config.json` → `bot_training.randomness` | Adversaires variés |
| Training/eval bot ratios | 7 bots, ~15% each (random 10%) | `training_config.json` | Distribution équilibrée |
| Eval weights | 7 bots, ~15% each (random 10%) | `training_config.json` → `bot_eval_weights` | Score combiné multi-profil |

---

### Troubleshooting Overfitting

**Agent still struggles vs RandomBot after 1000 episodes**:
- Increase Tier 1 bot randomness to 0.15-0.20
- Further reduce wait penalty to -0.5
- Consider starting fresh training
- Check that `bot_eval_weights` doesn't over-penalize RandomBot performance

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

### 📓 Journal de tuning performance

> Ce journal trace les tentatives d'optimisation avec leur résultat réel. But : ne pas répéter les mêmes erreurs, comprendre pourquoi ça a marché ou non.

---

#### [2026-05] Accélération entraînement x10 — BFS pathfinding

**Contexte**

L'entraînement x10 (`--training-config x10 --resolution 10`, 48 SubprocVecEnv, n_steps=16384) tournait à ~230 s/ep (vs ~5.7 s/ep en x1). Un profiling via `W40K_PERF_TIMING_MIN_EPISODE=2` sur 48 épisodes a révélé :

- **94% du temps handler** est dans le BFS pathfinding (559s / 594s)
- Move BFS : 102s (~17% du total)
- Charge BFS : 237s (~40% du total)

Particularités x10 : board 360×312 = 112 320 hexes, empreintes de 433 hexes (base 25mm), move_range=60 hexes, pas de topologie .npz → tout le pathfinding est on-demand.

---

**Tentative 1 — numba JIT sur le move BFS** ❌ Revert

- **Cible** : `engine/phase_handlers/movement_handlers.py` — boucle deque Python remplacée par `@numba.njit(cache=True)` avec queue numpy préallouée (`engine/fast_bfs.py`)
- **Résultat x1** : 5.69 → 5.98 s/ep (légèrement plus lent, pas de gain)
- **Raisons de l'échec** :
  1. Sur x1 (25×21), le BFS visite ~37 nœuds → Python est quasi-instantané, l'overhead numba domine
  2. L'allocation de 3 tableaux `int32[112K]` à l'intérieur de la fonction JIT (1.3 MB) génère une pression mémoire par appel
  3. Move BFS = seulement 17% du temps total sur x10 → gain maximal théorique ~15%, insuffisant même parfait
- **Leçon** : numba est efficace quand la boucle est longue et les données déjà numpy. Ici, la fonction était appelée trop souvent avec une queue trop grande et trop peu de nœuds visités sur x1.

---

**Tentative 2 — numpy board arrays sur le charge BFS** ❌ Revert

- **Cible** : `engine/phase_handlers/charge_handlers.py` — `charge_build_valid_destinations_pool` et `_charge_reverse_goal_bfs_for_eligibility`
- **Idée** : remplacer les sets Python (433 tuples par empreinte) par des tableaux numpy 2D précomputés :
  - `_candidate_footprint_charge()` + set comprehension → `fp_c = nc + offs_dc` (1 op numpy)
  - Intersections de sets → `arr[fp_c, fp_r].any()` (fancy indexing numpy)
  - `unit_entries_within_engagement_zone` (non-round-round) → éliminé, remplacé par check numpy (équivalence prouvée : `dilate(fp, r) ∩ charger_fp ≠ ∅ ↔ min_distance ≤ r`)
  - `visited` dict → `_vis_arr` numpy board uint8
- **Résultat x10** : 233.83 → 287.59 s/ep (**+23%, plus lent**)
- **Raisons de l'échec** :
  1. Sur x10 (360×312 = 112K cellules), chaque appel à `charge_build_valid_destinations_pool` initialise 5-6 tableaux `np.zeros((360, 312))` + itère en Python sur ~13K hexes occupés + ~17K hexes de `near_enemy_set` pour remplir les arrays. Coût estimé : 3-5ms par appel, payé en Python avant le BFS
  2. Ce coût d'initialisation n'est pas amorti : le BFS peut être pruné tôt (early_exit, lower bounds) et ne visiter que quelques dizaines de nœuds near-enemy
  3. L'original utilisait déjà des sets Python (lookups O(1) implémentés en C) qui sont très rapides pour des ensembles de taille modérée

- **Erreur de diagnostic** : le `perf_timing_x10.log` mesurait le temps CPU total sur 48 épisodes, pas le coût par appel BFS individuel. Sans mesure du coût moyen par appel vs. nombre de nœuds near-enemy visités, il était impossible de prédire si l'amortisation serait suffisante.

---

**Leçons générales**

| Leçon | Détail |
|-------|--------|
| Tester sur la board cible | x1 n'est pas représentatif de x10. Les deux boards ont des profils de coût radicalement différents. |
| Mesurer le coût d'init vs. gain per-nœud | Un tableau `np.zeros(112K)` coûte plusieurs ms en Python. Profitable seulement si des milliers de nœuds bénéficient de l'array. |
| Le profiling agrégé ne suffit pas | "BFS = 237s sur 48 épisodes" ne dit pas si c'est 1 appel lent ou 10 000 appels courts. |
| Sets Python C sont déjà optimisés | `x in set` est O(1) en C, souvent plus rapide que numpy fancy indexing sur des petits ensembles. |
| Le gain max borné | Si une pièce = 17% du total, même la rendre instantanée ne donne que 17% d'amélioration globale. |

---

**Pistes non explorées**

- **Caching des board arrays entre appels** : construire `occ_arr`, `enemy_eng_arr` une fois par tour (pas par appel BFS) pour amortir le coût d'initialisation
- **Numba sur la boucle BFS entière** : possible si tous les inputs sont numériques, mais nécessite de précomputer les board arrays au niveau épisode (pas appel)
- **Parallélisation intra-step** : les 48 envs SubprocVecEnv sont déjà parallèles, mais le charge BFS par env est séquentiel — threading intra-env non trivial avec le GIL

---

#### [2026-05] Charge BFS — `bfs_cache_hits_n=0` ❌ Non optimisable

**Constat** : `CHARGE_BUILD_POOL` log `bfs_cache_hits_n=0` sur 473 calls (5.5s total). Le cache `_has_valid_charge_cache` est implémenté avec la clé `(unit_id, _unit_move_version)` mais ne produit aucun hit.

**Pourquoi** : le cache est invalidé à chaque incrément de `_unit_move_version`. Or `_unit_move_version` s'incrémente après chaque charge (l'unité se déplace physiquement). Donc quand `build_charge_eligible_units_pool` est rappelé pour l'activation suivante, toutes les clés ont une version périmée.

**Pourquoi l'invalidation est correcte** (deux raisons métier) :
1. Une unité peut mourir pendant une charge en cours (combat réactif) → les cibles valides changent
2. Une charge peut bloquer le chemin BFS vers une cible qui était atteignable avant → le résultat BFS change

On ne peut pas clef par hash des positions ennemies seules car le chemin dépend aussi des alliés (positions bloquantes). Utiliser `_unit_move_version` est la seule clé correcte.

**Conclusion** : pas d'optimisation possible sans changer la sémantique du jeu. Le coût de 5.5s est incompressible tant que les règles 40K permettent mort-en-charge et blocage de chemin.

---

#### [2026-05] MOVE_POOL_BUILD BFS fly=False MOVE=60 — Non optimisable

**Constat** : 236 calls MOVE=60 fly=False, bfs_s moyen 27ms, max 146ms, total 6.4s. Visited ~10 600 hexes par call.

**Pourquoi ce n'est pas optimisable** : sur Board ×10 (360×312), une unité MOVE=60 placée en position centrale peut géométriquement atteindre π×60² ≈ 11 300 hexes. Le BFS en visite ~10 600 — c'est le coût exact du calcul correct. Il n'existe pas d'algorithme sub-linéaire pour calculer l'ensemble des hexes atteignables avec obstacles (murs + occupation).

Le pool est déjà mis en cache via `valid_move_destinations_pool` (réutilisé si non-vide, invalidé après chaque mouvement). Les 4449 calls sont des rebuilds légitimes : un par activation d'unité en phase mouvement.

**MOVE=60 est réel** : ce sont des unités avec MOVE=6 en x1 mises à l'échelle ×10. Pas un artefact de debug.

---

#### [2026-05] MOVE_POOL_BUILD fly=True single-hex — `_build_multi_hex_vectorized` ❌ Revert

**Contexte**

Benchmark x10_debug : MOVE_POOL_BUILD coûte 1 962s cumulés (avg 35.5ms/call, 55K calls). Les 20 appels les plus lents sont tous `fly=True MOVE=120 base_size=1` (BFS Python single-hex) à ~0.4–0.5s chacun, visitant jusqu'à 43 561 nœuds. Le chemin vectorisé NumPy (`_build_multi_hex_vectorized`) existait déjà pour les unités fly multi-hex (base_size > 1) mais était exclu pour base_size=1 via `_fly_single_hex = (ez <= 1 or base_size == 1)`.

**Ce qui a été tenté**

Changer `_fly_single_hex = (ez <= 1 or _fly_base_size == 1)` → `_fly_single_hex = ez <= 1` dans `movement_handlers.py`. Les offsets `((0, 0),)` pour base_size=1 sont corrects (`precompute_footprint_offsets('round', 1, 0)` retourne `((0, 0),)`, vérifié). La sémantique est rigoureusement identique au BFS Python (même ensemble de destinations valides, même traitement walls/occupied/EZ).

**Résultat**

SCORE : 13.1587 → 13.1311 ms/call (**-0.21%, dans le bruit ±0.2%**). MOVE_POOL_BUILD avg : 35.22 → 34.99ms (négligeable). Revert.

**Pourquoi ça n'a pas marché**

Le chemin NumPy traite un array 360×312 = 112K cellules **en entier**, incluant :
- `_dilate_by_kernel` / `_spread_by_kernel` pour l'engagement zone : ez=10 à x10 → 10 passes de spread sur 112K cells = ~60 opérations array
- Allocation et initialisation de plusieurs arrays 112K à chaque appel

Le BFS Python optimisé (bytearray + deque) visite 25K–43K nœuds avec des lookups O(1) en C. L'overhead NumPy pour le plateau complet compense le gain de vectorisation — les deux approches coûtent ~35ms.

**Ce qui resterait à explorer**

- Réduire les passes EZ dans `_build_multi_hex_vectorized` en précomputant la zone d'engagement une fois par tour (pas par appel BFS)
- ~~Pour fly single-hex MOVE=120 spécifiquement : énumération géométrique pure du disque hex sans BFS ni NumPy full-board~~ → **Fait, voir entrée suivante**

---

#### [2026-05] MOVE_POOL_BUILD fly=True single-hex — Énumération géométrique ✅ Appliqué

**Contexte**

Bottleneck identifié : fly=True single-hex BFS Python (deque + bytearray 112K) visitait ~43K nœuds séquentiellement pour MOVE=120 sur x10. Le BFS est redondant : les fly units traversent les obstacles → distance BFS == distance cube → le disque cube est énumérable directement.

**Ce qui a été fait**

Remplacement du BFS (deque + bytearray) par une énumération géométrique directe du disque cube dans `engine/phase_handlers/movement_handlers.py` :
- Conversion start offset → cube : `sx=col, sz=row-((col-(col&1))>>1)`
- Double boucle `dx in [-r, r]`, `dy in [max(-r,-r-dx), min(r,r-dx)]`
- Reconversion cube → offset : `nc=sx+dx, nr=(sz-dx-dy)+((nc-(nc&1))>>1)`
- Filtrage bounds/walls/occupied/EZ identique à l'ancienne logique BFS

Supprimé : `bytearray(112K)`, `deque`, `fly_queue`, marquage visited, propagation neighbor-par-neighbor.

**Résultat**

| Mesure | SCORE | Delta |
|--------|-------|-------|
| Baseline | 13.1587 ms/call | — |
| Après (run 1) | 12.9837 ms/call | -1.33% |
| Après (run 2) | 12.8903 ms/call | -2.04% |
| Après (run 3) | 12.8027 ms/call | -2.70% |

SCORE stabilisé ~12.80 ms/call → **-2.7% net**, bien au-delà du bruit ±0.16%. Wall-clock : 4:58 → ~4:30.

**Analyse post-mesure (données log seconde moitié, post-fix)**

La moyenne per-call fly=True MOVE=120 est passée de **~35ms (BFS) à ~81ms (géométrique)**. La double boucle Python génère ~43K itérations avec overhead loop Python (~1.9μs/iter), contre un BFS dont les ops critiques (deque, bytearray) étaient en C (~0.85μs/iter).

Le SCORE global s'améliore quand même de **-2.7%** car le BFS générait des pics à **0.4–0.5s** sur certains appels (variabilité positionnelle). Avec SubprocVecEnv 48 envs, chaque pic bloque tous les envs. L'énumération géométrique est **uniforme** (~81ms partout) → moins de stalls de synchronisation → meilleur débit global malgré la moyenne plus élevée.

**Ce qui resterait à explorer**

Vectoriser l'énumération du disque avec NumPy (générer tous les (dx,dy) valides en array, calculer (nc,nr) vectoriellement, filtrer bounds en array) pour ramener la moyenne ≤35ms. Le filtre walls/occupied/EZ reste Python mais ne s'applique qu'aux destinations valides (minorité). Gain potentiel : récupérer les ~300-400s supplémentaires sur 7800 appels.

**Compatibilité métier**

100% identique : même ensemble de destinations (disque cube = disque BFS pour fly), même filtrage walls/occupied/EZ, même `_fly_enemy_proximity_filter`. Les fly units passaient déjà à travers les murs en BFS (propagation non bloquée), l'énumération géométrique est strictement équivalente.

---

#### [2026-05] MOVE_POOL_BUILD fly=True — Précomputation `_fly_ez_prox_set` ✅ Appliqué

**Contexte**

Analyse fine du breakdown de `bfs_s=66ms` sur fly=True MOVE=120 (via instrumentation `perf_counter()` dans la boucle) :
- Géométrie + bounds + tuple creation : 27ms (37%)
- Walls/occupied lookup : 11ms (15%)
- EZ checks (`_movement_engagement_violates`) : **35ms (47%)** ← bottleneck

Les 35ms EZ se décomposaient en :
- ~21ms : proximity filter — boucle Python N ennemis × `calculate_hex_distance` pour chacun des ~43K hexes du disque
- ~11ms : appels réels à `_movement_engagement_violates` (~2260 hexes proches d'un ennemi)

Le proximity filter servait à décider "ce hex est-il proche d'au moins un ennemi ?" pour 43K hexes × N ennemis = 215K calculs de distance Python par appel.

**Ce qui a été fait**

Remplacement du proximity filter per-hex par une **précomputation unique** avant la boucle dans `engine/phase_handlers/movement_handlers.py` :

```python
# Une seule fois avant la boucle
_fly_ez_prox_set = set()
for _fec, _fer, _feth in _fly_prox_list:
    _fly_ez_prox_set |= dilate_hex_set({(_fec, _fer)}, _feth, board_cols, board_rows)
    _fly_ez_prox_set.add((_fec, _fer))

# Dans la boucle : O(1) set lookup au lieu de N × distance_calc
if _fly_ez_prox_set is not None and nb not in _fly_ez_prox_set:
    valid_destinations.append(nb)   # loin de tous les ennemis → pas de violation EZ possible
elif not _movement_engagement_violates(...):
    valid_destinations.append(nb)
```

N appels à `dilate_hex_set(radius≈13)` ≈ N × 1ms (une fois) → remplace 43K × N distance calcs Python. Sémantique identique : le set contient exactement les hexes à distance ≤ threshold de chaque ennemi.

**Résultat**

| Mesure | SCORE | Delta |
|--------|-------|-------|
| Baseline (post charge-fix) | 12.0060 ms/call | — |
| Après fix (incrémental 9.41ms/call) | **11.5560 ms/call** | **-3.75%** |

Gain supérieur à l'estimation (-1.2%) : le set lookup O(1) est aussi plus rapide que la boucle proximity filter elle-même.

**Cumulé depuis le baseline original (13.1587) : -12.2%.**

**Compatibilité métier**

100% identique : `dilate_hex_set({enemy_pos}, threshold)` produit exactement les hexes à distance ≤ threshold, ce que vérifiait `calculate_hex_distance(...) <= threshold`. Logique de validation EZ inchangée pour les hexes proches.

---

#### [2026-05] CHARGE_REVERSE_GOAL_BFS — Suppression `dilate_hex_set({start_pos}, 120)` ✅ Appliqué

**Contexte**

Analyse post-fix fly : `CHARGE_HAS_VALID_TARGET` / `CHARGE_REVERSE_GOAL_BFS` coûtaient 100ms/call avec seulement 18ms de BFS réel. Les 82ms restants étaient dans le setup pré-BFS non timé. Breakdown par soustraction des sous-timers : `goal_candidate_fp_s + goal_placement_s + goal_engagement_s = 3ms` → **79ms non timés**.

Root cause : `_charge_reverse_goal_bfs_for_eligibility` calculait `dilate_hex_set({start_pos}, 120, 360, 312)` à chaque appel pour construire le `start_reach_disk`. Radius 120 = CHARGE_MAX_DISTANCE (12 pouces × 10) → disque de ~43K hexes, même problème que fly=True MOVE=120. Le cache `_charge_reach_disk_cache` ne servait à rien : chaque chargeur a une position différente → 100% de cache misses.

**Ce qui a été fait**

Remplacement de `dilate_hex_set({start_pos}, bfs_max_distance)` + intersection set par un filtre géométrique direct dans `engine/phase_handlers/charge_handlers.py` (lignes 608-617) :

```python
# Avant — O(43K BFS) + O(n) intersection
start_reach_disk = dilate_hex_set({start_pos}, 120, ...)  # ~60ms
goal_zone = enemy_goal_zone & start_reach_disk             # ~380 hexes dans enemy_goal_zone

# Après — O(|enemy_goal_zone|) checks de distance
goal_zone = {h for h in enemy_goal_zone if hex_distance(h[0], h[1], start_col, start_row) <= _bfs_max}
```

`enemy_goal_zone` ≈ 786 hexes → 786 appels O(1) à `hex_distance` au lieu de 43K BFS. Suppression du cache `_charge_reach_disk_cache` (devenu inutile). Sémantique identique : `dilate_hex_set({start_pos}, r)` retourne exactement les hexes à distance cube ≤ r du point de départ.

**Résultat**

| Mesure | SCORE | Delta vs baseline fly-fix (12.80) |
|--------|-------|-----------------------------------|
| Baseline fly-fix | 12.80 ms/call | — |
| Après charge fix (run 1, 192 ep) | 12.5802 ms/call | -1.72% |
| Après charge fix (run 2, 192 ep) | 12.4334 ms/call | -2.86% |
| Après charge fix (600 ep) | **12.0060 ms/call** | **-6.2%** |

**Cumulé depuis le baseline original (13.1587) : -8.8%.**

**Pourquoi ça a marché**

La matérialisation du disque entier (~43K hexes) n'était jamais nécessaire : seul le sous-ensemble `enemy_goal_zone ∩ disk(start_pos, r)` était utilisé, et `enemy_goal_zone` ne contient que ~786 hexes. Le filtre O(|enemy_goal_zone|) est O(1000) fois moins cher que le BFS O(43K).

**Ce qui reste**

`enemy_engagement_zones` (loop ligne 621-638) : N × `dilate_hex_set(enemy_fp, ez=10)` ≈ N×2ms. Non timé séparément, estimé à ~15ms sur les 82ms restants post-fix. Optimisable séparément (même approche : filtre distance au lieu de matérialisation).

---

#### [2026-05] Méthode d'évaluation des optimisations perf — Référence

**Métrique de référence** : `SCORE = total_s / total_calls` (ms/call), calculé automatiquement par `python3 engine/perf_timing.py <log>` et sauvegardé dans `<log>.score.json`.

**Stabilité mesurée** : 3 runs consécutifs identiques donnent 13.1587 / 13.2009 / 13.1808 ms/call → variance ±0.16%. Un delta > 1% est significatif.

**Commande benchmark** :
```bash
W40K_PERF_TIMING=1 W40K_PERF_TIMING_LOG=perf_timing_bench_x10.log W40K_PERF_TIMING_MIN_EPISODE=2 \
  python3 ai/train.py --agent CoreAgent --training-config x10_debug \
  --scenario config/agents/CoreAgent/scenarios/training/training_benchmark/scenario_training_benchmark.json \
  --new --resolution 10 && python3 engine/perf_timing.py perf_timing_bench_x10.log
```

**Pourquoi pas `s/ep`** : CV=36% sur x10_debug → il faut ≥50 épisodes pour ±10% IC95%. Le SCORE ms/call est stable sur 192 épisodes car il normalise par le volume total de calls — indépendant du nombre d'épisodes terminés et de la composition des rosters.

---

#### [2026-05] Suppression invalidation hex_los_cache / _hex_los_state_cache ✅ Appliqué

**Contexte**

Profiling via `W40K_PERF_TIMING=1 W40K_PERF_TIMING_MIN_EPISODE=2` sur scénario `x10_debug` (Board ×10, 2 épisodes, `perf_timing_x10.log`). Budget des hotspots sur ~98.7s mesurées :

| Hotspot | Temps | % |
|---|---|---|
| ADVANCE `los_cache_s` | 30.7s | 31% |
| MOVE_COMMIT `los_cache_s` | 20.1s | 20% |
| MOVE_POOL_BUILD BFS | 24.9s | 25% |
| ADVANCE `adj_cache_s` + MOVE_COMMIT `adj_cache_s` | 13.2s | 13% |
| CHARGE_BUILD_POOL BFS | 5.5s | 6% |
| SHOOT enemy_adj_hex | 4.2s | 4% |

Les 50.8s de `los_cache_s` (advance + move_commit) représentaient le premier hotspot.

**Diagnostic**

`MOVE_COMMIT los_cache_s` = uniquement `_invalidate_los_cache_for_moved_unit` (pas de rebuild dans movement_handlers). La fonction itérait en O(N) sur TOUT `_hex_los_state_cache` à chaque mouvement pour supprimer les entrées liées à l'ancien hex :

```python
keys_to_remove = [k for k in game_state["_hex_los_state_cache"].keys()
                  if (k[0] == old_pos or k[1] == old_pos)]
```

Avec un cache qui grossit jusqu'à ~27 000 entrées, ce scan Python coûtait ~19ms/call × 1054 moves = 20s.

**Pourquoi l'invalidation était incorrecte**

`_hex_los_state_cache` et `hex_los_cache` stockent des résultats géométriques `((sc,sr),(ec,er)) → (visibility_ratio, can_see, in_cover)`, calculés par `compute_los_state()` (hex_utils.py) qui dépend **uniquement de `wall_set` (terrain statique)**. En 40K, les unités ne bloquent pas le LOS — seuls les murs comptent. Le résultat LOS entre deux hexes est donc une constante de la map, valide pour toute la durée de la partie, indépendamment des positions d'unités.

**Correction**

Deux caches hex distincts, traitement différencié :

| Cache | Dépend de | Traitement |
|---|---|---|
| `_hex_los_state_cache` | `wall_set` uniquement (terrain statique) | **Jamais invalidé** |
| `hex_los_cache` | `occupied_hexes` via `_has_line_of_sight` (dépend de l'empreinte du target) | Invalidation sélective maintenue |

- `_invalidate_los_cache_for_moved_unit` (`shooting_handlers.py`) : suppression du bloc d'invalidation de `_hex_los_state_cache` uniquement ; `hex_los_cache` conserve son invalidation sélective (O(N) scan mais sur un cache plus petit)
- `refresh_all_positional_caches_after_reactive_move` (`shared_utils.py`) : idem

`unit["los_cache"]` et `game_state["los_cache"]` (basés sur unit IDs) continuent d'être invalidés normalement.

Le choix de conserver l'invalidation de `hex_los_cache` : son résultat dépend de `occupied_hexes` (footprint multi-hex), qui varie selon l'unité. Si une unité A quitte un hex et une unité B avec une empreinte différente arrive au même hex, un cache stale donnerait un résultat incorrect. `_hex_los_state_cache` n'a pas ce problème car il est purement géométrique (hex-pair → terrain).

**Tests mis à jour**

`tests/unit/engine/test_los_cache_invalidation.py` — 2 tests obsolètes remplacés :
- `test_clears_hex_los_cache_fully_when_no_old_position` → `test_hex_los_cache_preserved_when_no_old_position`
- `test_selective_hex_cache_invalidation_with_old_position` → `test_hex_los_cache_preserved_with_old_position`

Les nouveaux tests vérifient que `hex_los_cache` est **intact** après un mouvement d'unité. Suite complète : 8/8 ✅

**Gain estimé**

- MOVE_COMMIT `los_cache_s` : 20s → ~0 (plus de scan O(N))
- ADVANCE `los_cache_s` : 30.7s → seulement `build_unit_los_cache` avec `_get_los_visibility_state` quasi-gratuit (dict lookup au lieu de `compute_los_state`)
- **Total estimé : ~40-45s récupérés sur 50.8s**

---

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

**Error**: `Observation size mismatch (expected 355, got 323)` (or inverse)
- **Cause**: Model trained with a different observation layout (`v2.4` rule-aware = 355, legacy = 323)
- **Fix**: Train new model from scratch with the target `obs_size`, or align `observation_params.obs_size` with the model

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
- See `engine/observation_builder.py:ObservationBuilder.build_observation()` for implementation
- Canonical layout reference: `Documentation/AI_OBSERVATION.md`
- Current CoreAgent layout (`v2.4`): 355 floats = legacy 323 + rules block 32

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

## 🔁 PIPELINE OPÉRATIONNEL HOLDOUT HARD (COREAGENT 150PTS)

### Objectif

Construire un benchmark `holdout_hard`:
- stable (scénarios fixes),
- équitable en `holdout_regular` (pool commun agent/opponent),
- exigeant en `holdout_hard` (opponent +10% budget),
- calibré de façon data-driven via matrices multi-bots + rebalancing.

Ce pipeline est la séquence recommandée pour `CoreAgent` en `150pts`.

### Étape 0 — Préparation rosters et scénarios

1. **Nettoyer les pools rosters** (`training`, `holdout_regular`, `holdout_hard`) côté agent et `_p2_rosters`.
2. **Générer rosters agent**:
   - `training`: specific + balanced,
   - `holdout_regular`: specific + balanced.
3. **Rendre `training` identique côté opponent** (copie + rename + `roster_id`).
4. **Rendre `holdout_regular` identique côté opponent** (copie + rename + `roster_id`).
5. **Générer `holdout_hard` séparé**:
   - agent: `150pts`,
   - opponent: `165pts` (+10%).
6. **Générer les scénarios holdout fixes** (`holdout_regular` et `holdout_hard`) avec `wall_ref` et `objectives_ref` explicites.
7. **Vérifier les comptes** (volumétrie rosters + scénarios).

Notes:
- Les fichiers `*_kpis_v21.json` ne sont pas des rosters.
- Les scénarios doivent être présents (`10/10`) avant toute phase matchup.

### Étape 1 — Matrices BOT rapides (e12)

But: obtenir une première estimation rapide de difficulté.

1. Nettoyer sorties matchup précédentes (`scenarios/.../matchups/*.json`, `rosters/.../matchups/*.json`).
2. Lancer 3 jobs en parallèle (un par bot):
   - `greedy`,
   - `defensive_smart`,
   - `adaptive`.
3. Utiliser `--episodes 12` (ou 10/12) pour réduire le temps.

Important:
- Avec `90x90` rosters hard, la matrice complète = `8100` matchups **par bot**.
- Le temps mur est dominé par un bot (même en parallèle inter-bots).

### Étape 2 — Rebalancing BOT

1. **Dry-run** (`rebalance_holdout_hard_scenarios.py` sans `--apply`) pour proposer des affectations.
2. Vérifier:
   - cible (`target-win-rate`, ex `0.40`),
   - bande (`min/max`, ex `0.25-0.50`),
   - plancher (`floor-win-rate`, ex `0.20`),
   - filtre opponent (`min/max p1 win rate vs p2`, ex `0.20-0.60`),
   - diversité (`max-repeat-per-opponent`, ex `2`).
3. **Apply** (`--apply`) pour écrire les nouveaux `opponent_roster_ref` dans les scénarios hard.

### Étape 3 — Revalidation robuste (e30)

But: confirmer la qualité après `apply` avec moins de bruit statistique.

1. Nettoyer sorties matchup.
2. Lancer à nouveau 3 bots en parallèle avec `--episodes 30`.
3. Analyser:
   - `wr_mean` par scénario,
   - dispersion inter-bots,
   - respect de la bande cible.

Critère pratique GO:
- au moins `8/10` scénarios dans `[0.25, 0.50]`,
- pas de scénario sous `0.20`,
- dispersion inter-bots raisonnable.

### Étape 4 — Validation finale ciblée (e50)

But: verrouiller la fiabilité finale sans coût d’un full-matrix e50.

1. Extraire les cas borderline depuis e30:
   - proches de `0.25±0.05`,
   - proches de `0.50±0.05`,
   - forte dispersion inter-bots.
2. Lancer des évaluations ciblées en `--episodes 50` (P1 benchmark par roster/scénario concerné).
3. Snapshotter chaque résultat e50 ciblé dans `reports/e50_candidates/raw_matchups/`.
4. Consolider le résumé e50 **depuis ces snapshots ciblés** (et non depuis les fichiers matchups globaux, potentiellement écrasés au fil des runs).

Notes opérationnelles:
- Exécuter les blocs shell critiques en mode fail-fast (ex: subshell `(`...`)` + `set -euo pipefail`).
- Ne pas exécuter deux fois le script généré `run_e50_commands.sh`.

### Décision GO / NO-GO (fin branche calibration)

Le GO global doit être pris sur la vue complète e30 (10 scénarios), pas sur le sous-ensemble e50 ciblé:
- `IN_BAND_25_50 >= 8/10`,
- aucun scénario `< 0.20`,
- dispersion inter-bots acceptable (majorité des `wr_spread <= 0.20`).

Le e50 ciblé sert à confirmer/affiner les cas limites, pas à remplacer la décision globale.

### Étape 5 — Boost des rosters faibles

But: réintégrer progressivement les rosters exclus (souvent swarm faibles) au lieu de les ignorer.

Process recommandé:
1. Extraire les IDs faibles depuis le dry-run.
2. Si la liste est vide: skip propre des étapes de boost (`dry-run` et `apply`).
3. Générer des candidats boostés par type (palier `+5` points).
4. Appliquer le remplacement des rosters faibles validés.
5. **Recalculer les 3 matrices BOT (`e30`) immédiatement après remplacement**.
6. Recalibrer les scénarios hard (dry-run puis apply) avec les matrices fraîchement régénérées.
7. Revalider (`e30`) puis contrôle structurel avec l’agent.
8. Cible de performance: `0.40-0.50`, stabilité sur 2 passes.
9. Archiver les anciens (`*_deprecated`) et tagger les boosts élevés (`+30`, `+40`) pour audit humain.

Outil d’automatisation:
- `scripts/auto_boost_weak_rosters.py` (plan + apply + rapport CSV).

---

## 🎯 SUMMARY

**Ce document est la référence unique pour tout le training et le tuning** : pipeline, configs, monitoring, hyperparamètres, anti-overfitting, dépannage.

**Principe clé** : entraînement en complexité complète dès le début (pas de curriculum).

**Tout ce qui concerne training / tuning** : dans ce document (AI_TRAINING.md). Compléments :
- **Métriques et tuning (quoi changer, diagnostic)** → [AI_METRICS.md](AI_METRICS.md)
- **Moteur de jeu** → [AI_IMPLEMENTATION.md](AI_IMPLEMENTATION.md), `engine/w40k_core.py`
- **Règles de tour** → [AI_TURN.md](AI_TURN.md)

En pratique : modifier les configs agent (`*_training_config.json`, `*_rewards_config.json`), surveiller TensorBoard, ajuster les hyperparamètres selon les métriques (voir AI_METRICS). Entraînement itératif : commencer en config debug, valider, puis monter en charge.