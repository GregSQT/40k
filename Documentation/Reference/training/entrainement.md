# Entraînement IA

> **Référence unique** pour l'architecture du pipeline, la configuration, le monitoring, les métriques,
> les hyperparamètres, l'anti-overfitting et le dépannage.
>
> **Moteur de jeu** : voir [architecture_moteur.md](../moteur/architecture_moteur.md).
> **Métriques détaillées et tuning ciblé** : voir [metriques.md](metriques.md).

---

## ⚠️ Interface agent

> Les mentions **`obs_size: 355`** (et `323`, `313`, `150`) qui subsistent dans des docs ou configs
> **historiques** décrivent des layouts périmés. L'interface réelle est celle-ci :
>
> | | Valeur en vigueur | Source de vérité (à relire, jamais à recopier) |
> |---|---|---|
> | `obs_size` | **16 735** (2026-08-24 — `charged` ajouté à `UNIT_BIN_FIELDS`, slot réservé §15.08/§15.11, +32 = 1 bit × 32 entités ; 16 703 avant, 2026-08-19 — V11 §9.5 P4 : `effective_range`, la portée max de tir de l'unité active en subhexes, entre dans `UNIT_CONT_FIELDS`, soit +32 = 1 scalaire × 32 entités ; 16 671 avant, V11 §9.4 P3-4 : `decision_options_cont`, 6 candidats × 2 scalaires ; 16 659 avant lui, V11 §0.48 `L2` : `K_ALLY_SLOTS` 8 → 12, une ligne alliée par action d'activation, +2 044 scalaires et **0 paramètre**) | `ObservationBuilder.SQUAD_OBS_SIZE_TARGET`, **calculé** depuis le schéma d'entités (`engine/observation_entities.py`) ; porté par `config/agents/<agent>/<agent>_training_config.json` → `observation_params`. Confronté à la source par `scripts/check_doc_references.py` (passe valeurs) |
> | espace d'action | **1 398** (1 024 cellules grille + 1 wait + 20 tir + 20 charge mono-cible + 190 charge multi-cibles + 20 mêlée + 1 fight sans cible + 20 tir indirect + 15 zone intents + 6 `CHOICE_i` + 20 Oath + 12 activation + 10 arme mêlée + 20 cohérence + 10 sélection arme tir + 9 slots passe 2 chantier 06) | `engine/macro_intents.py` (`TOTAL_ACTION_SIZE`) |
>
> - **L'observation n'est plus un vecteur** : c'est un `Dict` de **tenseurs d'entités** (chaque
>   unité — la mienne, mes alliées, les ennemies — porte le même schéma et passe par le même
>   encodeur), plus une grille égocentrique 9×32×32. Détail :
>   [observation_et_actions.md](observation_et_actions.md) — qui ne décrit QUE le pipeline actuel depuis le
>   2026-07-28 (le vecteur plat mono-figurine est archivé dans
>   [AI_OBSERVATION_Legacy.md](../../Archives/docs/AI_OBSERVATION_Legacy.md)).
> - Espace d'action = **0-1023** cellules de la grille égocentrique, **1024** wait,
>   **1025-1044** tir (20 slots), **1045-1064** charge mono-cible (20 slots, P3-2),
>   **1065-1254** charge multi-cibles (190 slots C(20,2)+20, P3-8), **1255-1274** mêlée (20 slots,
>   P3-1), **1275** fight sans cible, **1276-1295** tir indirect (20 slots), **1296-1310** zone
>   intents (15 slots), **1311-1316** `CHOICE_i` (EXCLUSIVES — quand une décision est en attente,
>   le masque n'expose qu'elles), **1317-1336** Oath of Moment (20 slots), **1337-1348** activation
>   escouade (12 slots, §0.48 L2), **1349-1358** arme mêlée (10 slots), **1359-1378** cohérence
>   (20 slots), **1379-1388** sélection arme tir (10 slots, P3-8 split-fire).
>   **Constantes nommées obligatoires** (`engine/macro_intents.py`) : un littéral d'action dans
>   `ai/` est un bug de revue (rupture R5).
> - `action_space_size` **n'est plus configuré** : la taille est DÉRIVÉE du moteur. Le recopier en
>   config créait une seconde source de vérité qui ne pouvait qu'avoir tort.
> - **Aucun modèle antérieur n'est réutilisable** (layout obs + stats VecNormalize) : tout run se
>   fait avec `--new`. Un `obs_size` périmé en config **lève désormais à l'init du moteur**, en
>   citant la valeur attendue.
>
> Source : `Documentation/Chantiers/v11/index_v11.md` (rupture R8, hygiène T6) et
> `observation_et_actions.md` (§0.30, tranches T-A→T-F).

---

## Quick Start

### Run Training
```bash
# From project root (--agent obligatoire : argparse refuse la commande sans lui)
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --new   # Entraînement standard (P1), depuis zéro
python ai/train.py --agent <agent_key> --scenario bot --new --param agent_seat_mode p2                         # Entraînement en P2
python ai/train.py --agent <agent_key> --scenario bot --new --param agent_seat_mode random                     # Entraînement seat aléatoire
python ai/train.py --agent <agent_key> --test-only --step --test-episodes 50                    # Test rapide avec logs
```

### Continue Existing Model
```bash
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --append
```
(Le chemin du modèle est dérivé de l'agent : `ai/models/<agent_key>/model_<agent_key>.zip`.)

### `--new` ou `--append` : obligatoire dès qu'un modèle existe

Si `ai/models/<agent_key>/model_<agent_key>.zip` est déjà là, une commande d'**entraînement** qui
ne porte ni `--new` ni `--append` est **refusée à l'entrée**, avant le moindre effet de bord :

- `--new` repart de poids aléatoires ; le modèle en place et ses artefacts canoniques
  (`best_model.zip` **et ses stats**, `_vec_normalize.pkl`, `_run_state.json`, `_robust_meta.json`,
  `_interrupted.zip` **et ses compagnons**, sidecar `*.tb_run.json`) sont **écartés sous un nom
  horodaté**, jamais écrasés ni supprimés ;
  l'archive reste un modèle **entier et reprenable**, et le run TensorBoard repart à neuf ;
- `--append` **continue** le modèle en place (poids, compteur d'épisodes, stats VecNormalize) ;
- `--resume-from` implique `--append`, il n'a donc pas à être accompagné.

Le refus JUMEAU vaut dans l'autre sens : `--append` alors qu'**aucun** `model_<agent_key>.zip`
n'existe est refusé aussi. Pour un **premier** entraînement : `--new`.

Les modes qui ne s'entraînent pas — `--test-only` / `--eval`, `--convert-steplog`, `--replay` — ne
lisent aucun des deux drapeaux et n'en exigent aucun.

### Reprendre depuis un checkpoint périodique
```bash
python ai/train.py --agent <agent_key> --training-config default --scenario bot \
  --resume-from ai/models/<agent_key>/ppo_checkpoint_640000_steps.zip
```
`--resume-from` installe le checkpoint **et ses stats VecNormalize** (`<stem>_vec_normalize.pkl`,
écrit par le callback de checkpoint) au chemin canonique du modèle, écarte les artefacts canoniques
du run précédent en `*_pre_resume_<horodatage>` au lieu de les écraser, ouvre un **run TensorBoard
neuf** (le checkpoint est un point antérieur : prolonger l'ancien run ferait reculer les steps),
puis active `--append`.

**La promotion est transactionnelle.** Elle n'est définitive qu'au démarrage de l'entraînement :
tant que le premier pas n'a pas tourné, tout échec — checkpoint illisible ou incompatible,
environnement inconstruisible, `Ctrl-C` — **remet le run précédent à sa place** et le dit dans le
log (`↩️ --resume-from annulé`).

Un checkpoint sans son `.pkl` de stats n'est **pas** reprenable : la commande échoue
explicitement plutôt que de servir les stats d'un autre modèle (V11 §0.35).

### Key Paths
- **Training Configs**: `config/agents/<agent_name>/<agent_name>_training_config.json`
- **Reward Configs**: `config/agents/<agent_name>/<agent_name>_rewards_config.json` (par agent)
- **Models**: `ai/models/<agent_key>/model_<agent_key>.zip`
- **Logs**: `./tensorboard/` (TensorBoard data)
- **Step Logs**: `step.log` (généré avec `--step` ; utilisé par l'analyzer et le replay viewer)
- **Agent inheritance metadata**: `inherits_from` dans `config/agents/<agent_name>/<agent_name>_training_config.json`
- **Shared training defaults**: `config/agents/_training_common.json`
- **Agent P1 rosters (100 pts)**:
  - `config/agents/<agent_key>/rosters/100pts/training/p1_roster-XX.json`
  - `config/agents/<agent_key>/rosters/100pts/holdout_regular/p1_roster-XX.json`
  - `config/agents/<agent_key>/rosters/100pts/holdout_hard/p1_roster-XX.json`
- **Shared P2 rosters (100 pts)**:
  - `config/agents/_p2_rosters/100pts/training/p2_roster-XX.json`
  - `config/agents/_p2_rosters/100pts/holdout/p2_roster-XX.json`
- **Shared walls**: `config/board/{cols}x{rows}/walls/walls-XX.json`
- **Shared objectives**: `config/board/{cols}x{rows}/objectives/objectives-XX.json`

---

## Architecture du pipeline

### Point d'entrée et CLI

- **Script** : `ai/train.py`. Tous les modes (entraînement, test-only, convert-steplog) partent de ce script.
  ⚠️ Le mode `orchestrate` a été **supprimé** le 2026-07-19 avec `ai/multi_agent_trainer.py` :
  legacy pré-squad qui chargeait les modèles en `DQN.load` alors que tous les `.zip` sont MaskablePPO.
- **Arguments essentiels** :
  - `--agent <agent_key>` : agent à entraîner (**obligatoire**, et non vide).
  - `--training-config <name>` : clé du bloc dans `*_training_config.json` (ex. `default`, `debug`).
  - `--rewards-config <name>` : en pratique le même que `--agent` ou un alias.
  - `--scenario <name>` : scénario ou mode (`bot`, `default`, `phase1`, etc.). Avec `bot`, l'adversaire est un mix configurable de 5 bots (Random, Greedy, Defensive, Control, Adaptive).
- **Options utiles** : `--step` (écrit `step.log`), `--test-only` (pas d'apprentissage), `--eval` (alias de `--test-only`), `--test-episodes N`, `--append`, `--resume-from <checkpoint.zip>`

`--test-episodes N` mesure le win-rate sur le **holdout** (`holdout_regular` en priorité, `holdout_hard` à défaut). Le scénario est résolu **avant** le premier épisode : un agent sans dossier de scénarios holdout fait échouer la commande immédiatement.

### Chargement de la config

- **config_loader** (`config_loader.py`) :
  - `load_agent_training_config(agent_key, training_config_name)` → charge le bloc demandé. Gère `inherits_from`.
  - `load_agent_rewards_config(agent_key)` → charge `*_rewards_config.json`.
  - `get_models_root()` → racine des modèles.
- **UnitRegistry** (`ai/unit_registry.py`) : mappe `unit_type` vers `model_key`.

#### Scénarios minces + rosters compacts

- Un scénario peut pointer vers des rosters via `"scale"`, `"agent_roster_ref"`, `"opponent_roster_ref"`.
- Le mapping agent/opponent → Player 1/2 est résolu au runtime par `controlled_player`.
- `"training_random"` → tirage aléatoire d'un roster dans `rosters/<scale>/training/`.
- Les rosters compacts utilisent `"roster_id"` + `"composition"` (liste de `{ "unit_type", "count" }`).
- Expansion runtime : IDs P1 = `1..N`, IDs P2 = `101..(100+N2)`. Déploiement géré par le scénario.
- `step.log` journalise les rosters sélectionnés en début d'épisode (`Rosters: ...`).

### Création de l'environnement

1. **Moteur de base** : `W40KEngine` (`engine/w40k_core.py`)
2. **Step logger** (si `--step`) : `StepLogger("step.log", ...)` ; désactivé pour les envs vectorisés.
3. **ActionMasker** : wrapper SB3 `ActionMasker(base_env, mask_fn)` pour MaskablePPO.
4. **Adversaire** :
   - **Scénario bot** : `BotControlledEnv(masked_env, bots=training_bots, unit_registry=..., agent_seat_mode=..., agent_seat_p2_ratio=..., global_seed=..., env_rank=...)`.
   - **Self-play** : `SelfPlayWrapper(masked_env, ...)`.
5. **Monitor** : `Monitor(wrapped_env)` pour les stats d'épisode.

Pour l'entraînement vectorisé, `make_training_env()` dans `ai/training_utils.py` encapsule cette construction.

### Modèle et boucle d'entraînement

- **Modèle** : `MaskablePPO` (sb3_contrib).
- **Callbacks** : sauvegarde de checkpoints, `BotEvaluationCallback`, logging TensorBoard.
- **Boucle** : `model.learn(total_timesteps=...)`. Chaque step : `action = model.predict(obs, action_masks=mask)` puis `env.step(action)`.

**Références code** : `ai/train.py`, `ai/training_utils.py`, `ai/env_wrappers.py`, `engine/w40k_core.py`.

---

## Seat-Aware Training (P1 / P2 / Random)

L'agent peut être entraîné en tant que Player 1, Player 2, ou en alternance aléatoire par épisode. Le pipeline garantit que toutes les observations, rewards et métriques sont **égocentriques**.

### Concept

Trois modes d'entraînement via `agent_seat_mode` :

| Mode | `controlled_player` | Comportement |
|------|---------------------|-------------|
| `p1` | Toujours 1 | Agent = Player 1, Bot = Player 2 |
| `p2` | Toujours 2 | Agent = Player 2, Bot = Player 1 |
| `random` | 1 ou 2 par épisode | Tirage déterministe par `(global_seed, env_rank, episode_index)`, pondéré par `agent_seat_p2_ratio` |

#### `agent_seat_p2_ratio` — part des épisodes joués en SECOND

Clé **obligatoire** dès que `agent_seat_mode` vaut `random` (aucune valeur par défaut). Elle donne la proportion d'épisodes d'entraînement où l'agent joue second : `0.5` est le tirage équitable, `0.65` (réglage courant, 2026-08-28) sur-échantillonne le second siège.

Raison d'être : l'agent joue nettement moins bien en second — run x1_long du 2026-08-12, `0.707` de win-rate en jouant premier contre `0.586` en jouant second, 12 points stables jusqu'à la fin du run. Sur-échantillonner le siège faible est le seul levier d'exposition ; passer `agent_seat_mode` à `p2` supprimerait l'autre siège et rendrait `00_critical/0_gap_p1-p2` aveugle.

**L'évaluation n'est pas concernée** : `ai/bot_evaluation.py` construit ses environnements sans passer cette clé, donc son tirage reste équitable et le win-rate publié reste comparable d'un run à l'autre. Même séparation que `deployment_mode_schedule.training_only`.

Un override `--param agent_seat_mode p1|p2` rend la clé sans objet — elle n'est alors ni lue ni refusée, exactement comme `agent_seat_seed`.

Le tirage est un **seuil** sur les 32 premiers bits du hachage (uniformes), et non la parité utilisée jusqu'au 2026-08-28 : à `0.5` la distribution est inchangée, mais la séquence siège-par-siège d'un run rejoué diffère.

En mode `random`, l'écart d'épisodes entre les deux sièges suit `agent_seat_p2_ratio` — ce n'est plus une parité à ±5 %. Ce qui reste à auditer : que le siège minoritaire garde assez d'épisodes pour que `seat_aware/winrate_agent_p1` et `00_critical/0_gap_p1-p2` restent lisibles (fenêtre ≥ 2000 épisodes).

### Architecture (seat)

Le seat est résolu à chaque `reset()` d'épisode dans `BotControlledEnv` :

1. `_resolve_controlled_player_for_episode()` → détermine `controlled_player` (1 ou 2)
2. `_apply_episode_seat()` → écrit dans `engine.config` et `game_state`
3. `_play_bot_until_control_returns()` → le bot joue jusqu'à ce que l'agent ait une décision

**Source de vérité unique** : `engine.config["controlled_player"]`. Écriture autorisée uniquement au reset d'épisode.

**Roster mapping** : les IDs d'unités suivent la convention historique : Player 1 = `[1..N]`, Player 2 = `[101..N]`.

### Observation égocentrique

| Feature | Encodage |
|---------|----------|
| `obs[0]` (turn ownership) | `1.0` si c'est le tour de l'unité active |
| Objective control | `+1.0` = contrôlé par mon camp, `-1.0` = ennemi |
| Allied units | Filtré par `unit["player"] == active_unit["player"]` |
| Enemy units | Filtré par `unit["player"] != active_unit["player"]` |
| Army value diff (macro) | `my_value - enemy_value` |

**Cache `macro_objectives`** : ⚠️ **supprimé le 2026-07-28** avec le pipeline mono-figurine. Le contrôle d'objectif est rafraîchi aux frontières de phase/tour par `GameStateManager.refresh_objective_control_on_boundary`.

### Reward seat-aware

Le `RewardCalculator` (`engine/reward_calculator.py`) filtre les rewards par joueur :

1. **Actions non-contrôlées** : seuls les rewards objectifs par tour et situationnels sont retournés.
2. **Actions contrôlées** : reward complète (`base_action + result_bonuses + objective + situational`).

La ventilation `last_reward_breakdown` expose `base_actions`, `result_bonuses`, `objective`, `situational`, `penalties` et `total`. La clé `objective` agrège le versement de fin de tour (`_calculate_objective_reward_per_turn`) et le bonus « se poser sur un objectif » (`_calculate_on_objective_reward`).

**`reward/objective_share`** : part de l'objectif dans ce que l'épisode a rapporté — `objective⁺ / (base_actions⁺ + result_bonuses⁺ + objective⁺)`, flux positifs accumulés pas à pas.

**Accumulation côté moteur** : dans `episode_tactical_data['reward_breakdown']`, alimenté à chaque step moteur, pas dans le callback. Le callback ne voit qu'un `info` par step gym — les wrappers d'adversaire remplacent `info` par celui de l'adversaire. Corrigé le 2026-07-31.

**Contrat d'`info` des wrappers** (`AGENT_STEP_INFO_KEYS`, `ai/env_wrappers.py`) : les clés qui décrivent l'action de l'agent (`phase`, `success`, `charge_succeeded`, `action`, `intent_value`, `is_controlled_action`) sont **remplacées en bloc** (`apply_agent_step_info`).

3. **Reward situationnelle** (`_get_situational_reward`) :
   - `winner == controlled_player` → bonus win
   - `winner == opponent_player` → pénalité lose
   - `winner == -1` → reward draw

4. **Reward objectifs par tour** (`_calculate_objective_reward_per_turn`) : `objective_reward_factor` × **les VP que la mission attribue ce tour-là**. Appliqué une fois par tour, à la transition vers la phase move **du joueur contrôlé**.

5. **Bonus « sur un objectif »** (`_calculate_on_objective_reward`) : versé quand une action qui porte une destination laisse l'unité **dans** une zone d'objectif que l'agent ne contrôle pas encore. La présence se juge **par figurine, sur l'empreinte de socle** (14.02), via `unit_is_within_objective`. Une unité **battle-shocked** ne touche rien (01.07).

6. **Pénalité de réserve gaspillée** (`RewardCalculator.wasted_reserve_penalty`, **−25.0 par escouade**) : facturée quand une escouade du joueur contrôlé est détruite par 20.04 **après avoir refusé au moins une arrivée possible**. Une escouade sans destination légale (pool d'ingress vide) n'est PAS facturée.

7. **Zone-intent — DÉBRANCHÉ** (`zone_intent_shaping.enabled: false`). Le code et les quatre montants restent ; un `true` rebranche tout.

### Configuration (seat)

**training_config.json** :
```json
{
  "agent_seat_mode": "random",
  "agent_seat_seed": 42,
  "agent_seat_p2_ratio": 0.65
}
```

`agent_seat_p2_ratio` est obligatoire avec `"agent_seat_mode": "random"` et sans objet avec `"p1"` / `"p2"`.

**CLI override** :
```bash
python ai/train.py --agent CoreAgent --scenario bot --new --param agent_seat_mode p2
python ai/train.py --agent CoreAgent --scenario bot --new --param agent_seat_mode random
```

### Évaluation cross-seat

```bash
# Évaluer le modèle courant en tant que P1
python ai/train.py --agent CoreAgent --eval --param agent_seat_mode p1 --test-episodes 100

# Évaluer le même modèle en tant que P2
python ai/train.py --agent CoreAgent --eval --param agent_seat_mode p2 --test-episodes 100
```

**Protocole de validation cross-seat** : un drop symétrique (~10-15 pts) en P2 confirme le désavantage going-second.

### Contraintes connues

**Désavantage going-second** : Player 1 agit en premier chaque tour. Cela crée un désavantage structurel pour P2 (~10-15 pts win_rate) qui n'est pas un bug mais une propriété du jeu.

---

## Macro Training — SUPPRIMÉ

**Il n'y a plus d'agent macro. `--agent MacroController` n'existe plus.** L'intention de zone est
portée par l'agent micro unifié. Le code correspondant a été retiré de `ai/train.py`. Il n'y a
aucun chantier macro ouvert : relancer le sujet demande une décision produit, pas une reprise de code.

---

## Replay Mode

### Overview
Le Replay Mode permet de visualiser les épisodes d'entraînement dans le frontend.

### Generating Replay Logs
```bash
python ai/train.py --agent <agent_key> --training-config default --rewards-config <agent_key> --scenario bot --new --step
```

Le log capture : marqueurs début/fin d'épisode, positions de départ, moves, tirs (rolls), charges, fights, résultats d'épisode.

### Using the Replay Viewer

1. Démarrer le frontend : `cd frontend && npm run dev`
2. Cliquer l'onglet "Replay"
3. Cliquer "Browse" pour sélectionner `step.log`
4. Choisir un épisode dans le dropdown
5. Utiliser les boutons forward/backward

### Replay Features

**Visual Indicators:**
- **Shoot lines**: Orange lines show shooting actions
- **Explosion icons**: Appear on damaged/killed units
- **Grey ghosts**: Units killed in the current step appear grey before removal
- **HP display**: Unit health shown as bars

**Game Log Color Coding:**

| Palette | Signification |
|---------|---------------|
| Purple / Light Purple | Charge success / failed |
| Light Blue / Cyan / Dark Blue | Shooting : miss / saved / damage |
| Yellow / Orange / Red | Melee : miss / saved / damage |
| Black | Unit DESTROYED |

### Log Format Reference

```
[HH:MM:SS] === EPISODE START ===
[HH:MM:SS] Scenario: default
[HH:MM:SS] Opponent: GreedyBot
[HH:MM:SS] Unit 1 (Intercessor) P0: Starting position (9, 12)
[HH:MM:SS] === ACTIONS START ===
[HH:MM:SS] T1 P0 MOVE : Unit 1(6, 15) MOVED from (9, 12) to (6, 15) [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 SHOOT : Unit 1(6, 15) SHOT at Unit 5 - Hit:3+:6(HIT) Wound:4+:5(SUCCESS) Save:3+:2(FAILED) Dmg:1HP [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 CHARGE : Unit 2(9, 6) CHARGED Unit 8 from (7, 13) to (9, 6) [Roll:7] [R:+3.0] [SUCCESS] [STEP: YES]
[HH:MM:SS] T1 P0 FIGHT : Unit 2(9, 6) FOUGHT unit 8 - Hit:3+:5(HIT) Wound:4+:4(SUCCESS) Save:4+:6(SAVED) Dmg:0HP [SUCCESS] [STEP: YES]
[HH:MM:SS] EPISODE END: Winner=0, Actions=68, Steps=68, Total=138
```

| Action | Format |
|--------|--------|
| MOVE | `Unit X(col, row) MOVED from (a, b) to (c, d)` |
| SHOOT | `Unit X(col, row) SHOT at Unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |
| CHARGE | `Unit X(col, row) CHARGED Unit Y from (a, b) to (c, d) [Roll:N]` |
| FIGHT | `Unit X(col, row) FOUGHT unit Y - Hit:T+:R(HIT/MISS) Wound:T+:R(SUCCESS/FAIL) Save:T+:R(SAVED/FAILED) Dmg:NHP` |

---

## Stratégie d'entraînement

### Unified Training (No Curriculum)

> **Ce projet utilise l'entraînement en complexité complète dès le début — PAS de curriculum.**

**Pourquoi pas de curriculum ?** Les tests montrent que le curriculum échoue pour les jeux tactiques :
1. Les premières phases apprennent de mauvaises politiques (« rester immobile est optimal »)
2. Les mécaniques sont interdépendantes (tir dépend du positionnement)
3. Les rewards denses + exploration simple suffisent

**Evidence from testing:**
- Curriculum Phase 1→2 : 18k épisodes, 14% win rate
- Unified from-scratch : 15k épisodes, 50-60% win rate

### Dynamic Roster Generation (150pts)

`scripts/build_dynamic_rosters.py` (version consolidée v21) génère les rosters dynamiques.

**Entrées nécessaires**
- `reports/unit_sampling_matrix.json` (généré par `scripts/unit_classifier.py`)
- `matrix["unit_values"]` requis (mapping `"roster::unit_type" -> VALUE`)

**Workflow recommandé**
```bash
# 1) Rebuild classification + matrix
python scripts/unit_classifier.py --roster all

# 2) Génération training (exemple Troop)
python scripts/build_dynamic_rosters.py \
  --target-tanking Troop \
  --points-scale 150 \
  --num-rosters 200 \
  --units-per-roster 5 \
  --split training

# 3) Génération holdout
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

### Organisation Training — Agent Unique

Un seul agent PPO entraîné sur une distribution de situations variées.

**Principe** : la diversité est apportée par les rosters dynamiques, les buckets de gap VALUE (`strict/medium/wide`), les bots d'entraînement pondérés.

**KPIs à suivre en priorité**
- `rejection_rate_roster_budget`
- `distribution_drift_blend/mobility/weapon_profile`
- `matchup_value_gap_mean`, `matchup_value_gap_p95`
- métriques RL standard (`00_critical/*`, `bot_eval/*`)

### Reward Design Philosophy

**Key Principles:**
- All game mechanics active from episode 1 (MOVE, SHOOT, CHARGE, FIGHT)
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

### Target Priority & Positioning

**Target Priority Formula:**
```
target_priority = VALUE / turns_to_kill
```

| Target | VALUE | Turns to Kill | Priority Score |
|--------|-------|---------------|----------------|
| Captain (wounded, 2HP left) | 80 | 2 | **40** (highest) |
| Intercessor (wounded, 1HP) | 19 | 1 | **19** |
| Termagant | 6 | 1.35 | **4.4** |

---

## Configuration

### training_config.json Structure

Training configs sont par agent : `config/agents/<agent_name>/<agent_name>_training_config.json`

#### Agent Inheritance (EXPLICIT)

> **CRITIQUE** : il n'y a plus de mapping hardcodé dans `config_loader.py`. La résolution se fait
> uniquement via le champ `inherits_from` dans `*_training_config.json`.

Règles:
- `inherits_from: null` → pas d'héritage.
- `inherits_from: "<AgentKeyParent>"` → héritage explicite.
- Valeur invalide → erreur explicite (fail fast).
- Paramètre `null` → résolu via `config/agents/_training_common.json`. Clé absente dans le commun → erreur explicite.

```json
{
  "inherits_from": null,
  "default": {
    "total_episodes": 5000,
    "max_turns_per_episode": 5,
    "max_steps_per_turn": 200,
    "gym_distance_metric": "euclidean",

    "callback_params": {
      "checkpoint_save_freq": 50000,
      "checkpoint_name_prefix": "ppo_checkpoint",
      "n_eval_episodes": 5,
      "bot_eval_freq": 200,
      "bot_eval_use_episodes": true,
      "bot_eval_intermediate": 30,
      "bot_eval_final": 0,
      "bot_eval_use_subprocess": true,
      "bot_eval_n_workers": 6,
      "bot_eval_task_timeout_seconds": 300,
      "bot_eval_worker_device": "cpu",
      "save_best_robust": true,
      "robust_window": 3,
      "robust_drawdown_penalty": 0.5,
      "model_gating_enabled": true,
      "model_gating_min_combined": 0.55,
      "model_gating_min_worst_bot": 0.45,
      "model_gating_min_worst_scenario_combined": 0.45
    },

    "observation_params": {
      "obs_size": 16735
    },

    "model_params": {
      "learning_rate": 0.0003,
      "n_steps": 256,
      "batch_size": 128,
      "n_epochs": 10,
      "gamma": 0.95,
      "gae_lambda": 0.95,
      "clip_range": 0.2,
      "ent_coef": 0.10,
      "vf_coef": 1.0,
      "max_grad_norm": 0.5,
      "policy_kwargs": {
        "net_arch": [320, 320]
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

### Rampes `learning_rate` / `ent_coef` — et `decay_fraction`

`learning_rate` et `ent_coef` acceptent un **dict** :

```jsonc
"learning_rate": { "initial": 0.002, "final": 0.0002, "decay_fraction": 0.4 },
"ent_coef":      { "start": 0.1,     "end": 0.01,     "decay_fraction": 0.4 }
```

**Les trois clés sont OBLIGATOIRES** (sans valeur par défaut). Une valeur scalaire = pas de callback, valeur constante.

**`decay_fraction`** découple la longueur du run et la rampe : la rampe s'achève à cette fraction du run, puis la valeur **reste au plancher**. `1.0` reproduit le comportement historique.

| Profil | `total_episodes` | `learning_rate` | `ent_coef` |
|--------|------------------|-----------------|------------|
| `x1` | 10 000 | 1.0 → fin du run | 1.0 → fin du run |
| `x1_long` | 50 000 | **0.7** → 35 000 ép. | **0.4** → 20 000 ép. |
| `x5_long` | 200 000 | **0.7** → 140 000 ép. | **0.4** → 80 000 ép. |

L'**entropie** s'arrête aux 40 % : passé ce point, la politique exploite ce qu'elle a appris. Le **learning rate** descend jusqu'aux 70 % pour ne pas brider l'apprentissage trop tôt.

**Le LR n'est PAS piloté par le schedule SB3.** `_make_learning_rate_schedule` ne sert qu'à donner sa valeur initiale à l'optimizer : le callback remplace `model.lr_schedule` par sa propre constante dès `on_training_start`.

`bot_eval_freq` de `x1_long` vaut **10 000** (5 points de mesure). `bot_eval_intermediate` reste à **100**. `robust_window` vaut **3** (5 points → 3 positions de fenêtre).

`x1` est passé à `save_best_robust: false` : 10 000 épisodes à `bot_eval_freq` 2000 donnent 5 points pour une fenêtre de 5, soit une seule position — sélection mécanique sur le dernier point.

`checkpoint_save_freq` est **aligné sur `x1`** : SB3 sauvegarde tous les `save_freq` **appels** (pas des épisodes).

`batch_size: 1020` : à `n_steps: 8160` / `n_envs: 24`, le rollout vaut `(8160 // 24) × 24 = 8160 = 8 × 1020` — 8 mini-lots pleins, aucun tronqué.

### Unit Rules Implementation Flags (`RULES_STATUS`)

Conventions dans les fichiers d'unités (`frontend/src/roster/**/units/*.ts`):

```ts
static UNIT_RULES = [{ ruleId: "closest_target_penetration", displayName: "Close-quarter firepower" }];
static RULES_STATUS = { closest_target_penetration: 2 };
```

Valeurs de `RULES_STATUS`:
- `0` = `NOT_IMPLEMENTED`
- `1` = `NOT_IMPLEMENTABLE_YET`
- `2` = `IMPLEMENTED`

Une règle ne passe à `2` que si son effet est valide dans les handlers runtime. Référence audit : `Documentation/RULES_IMPLEMENTATION_AUDIT_CHECKLIST.md`.

### rewards_config.json Structure

```json
{
  "SpaceMarineRanged": {
    "ranged_attack": 0.2,
    "enemy_killed_r": 0.4,
    "enemy_killed_lowests_hp_r": 0.6,
    "enemy_killed_no_overkill_r": 0.8,
    "charge_success": 0.2,
    "attack": 0.4,
    "enemy_killed_m": 0.2,
    "being_charged": -0.4,
    "loose_hp": -0.4,
    "killed_in_melee": -0.8,
    "atk_wasted_r": -0.8,
    "atk_wasted_m": -0.8,
    "wait": -0.9,
    "win": 1,
    "lose": -1.0,
    "friendly_fire_penalty": -0.8
  }
}
```

**Common Reward Design Mistakes:**

❌ **Reward Hacking**: Too high rewards cause agent to exploit mechanics
❌ **Conflicting Rewards**: Mixed signals confuse learning
❌ **Sparse Rewards**: Agent never learns what's good

✅ **Good Practice**: Balanced progressive rewards (small 0.1-1.0, medium 1.0-5.0, large 5.0-50.0)

---

## Monitoring

> Pour le tuning (quoi modifier selon les métriques) et l'analyse experte, voir [metriques.md](metriques.md).

### TensorBoard

```bash
tensorboard --logdir=./tensorboard/
```

#### Dashboard `00_critical/`

**Primary Metrics to Check Daily:**
- `00_critical/a_bot_eval_combined` — **objectif principal** (compétence vs tous les bots)
- `00_critical/b_win_rate_100ep` — tendance récente sur 100 épisodes
- `00_critical/g_approx_kl` — stabilité de la politique (<0.02 = sain)
- `00_critical/h_entropy_loss` — niveau d'exploration (doit décroître progressivement)
- `00_critical/e_explained_variance` — qualité de la value function (cible : >0.70 tôt, >0.85 tard)

#### Other Key Metrics

| Namespace | Metric | Good Trend |
|-----------|--------|------------|
| `rollout/` | `ep_rew_mean` | Increasing |
| `rollout/` | `ep_len_mean` | Stable or decreasing |
| `train/` | `entropy_loss` | Decreasing gradually |
| `game_critical/` | `win_rate_100ep` | Increasing to target |
| `game_critical/` | `invalid_action_rate` | <5% (ideally <2%) |
| `bot_eval/` | `vs_random` / `vs_greedy` / `vs_defensive` / `vs_control` / `vs_adaptive` | Improving |
| `bot_eval/` | `combined` | Increasing to 0.70+ |

### Success Indicators

**Early Training (0-1000 episodes):**
- Win rate vs Random bot: 40%+ after 500 episodes

**Mid Training (1000-3000 episodes):**
- Win rate vs Greedy bot: 50%+ after 2000 episodes
- Invalid action rate: <5%

**Late Training (3000+ episodes):**
- Combined bot evaluation: 60%+
- Win rate vs Tactical bots: 50%+ after 4000 episodes

### Red Flags (Training Collapse)

🚨 **Policy Collapse**: `ep_rew_mean` drops suddenly → reduce `learning_rate` by 50%

🚨 **No Learning**: flat `ep_rew_mean` for 500+ episodes → increase `ent_coef` to 0.15

🚨 **Instability**: `ep_rew_mean` oscillates wildly → increase `n_steps` to 1024, review reward balance

---

## Métriques avancées et tuning

Ce document couvre le monitoring de base. Pour aller plus loin :

- **[metriques.md](metriques.md)** — guide de tuning rapide (tableau, problèmes courants, matrice métrique → paramètres, actions correctives) + analyse experte (explication de chaque métrique, patterns, arbres de décision).

---

## Évaluation — Panel de bots

### Bot Types

> ⚠️ **Fiches refaites le 2026-07-29.** Trois défauts corrigés : (1) `DefensiveBot` ne chargeait jamais ;
> (2) le focus-fire des bots Tier 2 était débranché ; (3) `TacticalBot` n'exposait pas
> `select_action_with_state`. Toute mesure antérieure n'est pas comparable.
>
> ⚠️ **Refonte du panel (2026-07-30).** `AggressiveSmartBot` et `DefensiveSmartBot` supprimés ;
> déplacement des bots = score pondéré `w_objective × (-d_objectif) + w_enemy × (-d_ennemi)` ;
> deux lectures d'objectif corrigées. `combined` en baisse attendue — seuils de gate à recalibrer.
>
> **Critère de cible = définition de l'adversaire.** Chaque bot choisit sa cible par un critère
> explicite via `get_enemy_slot_mapping`, jamais par l'ordre des slots.

| Bot | Critère de cible |
|---|---|
| RandomBot | aléatoire (doctrine) |
| GreedyBot | la plus **entamée** (achever) — identique aux trois phases |
| DefensiveBot | la plus **menaçante** au tir et en mêlée ; **contre-charge** en charge |
| ControlBot | celle qui **conteste** — la plus proche d'un objectif |
| AdaptiveBot | la plus **entamée** |
| TacticalBot | **tuable ce tour > peu de PV > menace élevée** |

#### Géométrie de déplacement (commune, `config/bot_movement_weights.json`)

`score(dest) = w_objective × (−distance_objectif) + w_enemy × (−distance_ennemi)` + `hold_bonus` si dans une zone d'objectif.

| Bot | `w_objective` | `w_enemy` |
|---|---|---|
| Greedy | 0.3 | +1.0 |
| Defensive | 0.7 | −0.5 |
| Control | 1.0 | +0.1 |
| Adaptive (early / winning / losing) | 1.0 / 1.0 / 0.5 | +0.2 / −0.2 / +1.0 |
| Tactical | 0.5 | — (géométrie propre) |

`hold_bonus` = 3.0 (en distance-hex).

#### Détail des bots

**RandomBot (Easiest)** — sélection aléatoire. Baseline : tout agent compétent doit gagner 90%+.

**GreedyBot (Medium)** — pousse offensive + attrait d'objectif ; doctrine ACHEVER. Supporte `randomness` (0.0-0.3).

**DefensiveBot (Medium-Hard)** — se replie vers son objectif, tire sur la cible la plus menaçante. **Contre-charge** si une escouade de mêlée ennemie est déjà déclarable (ne pas lui laisser Fights First). Supporte `randomness`.

**ControlBot (Medium)** — va vers l'objectif et le tient. Cible celle qui conteste. Ne charge pas s'il tient déjà un objectif. Supporte `randomness`.

**AdaptiveBot (le plus dur du panel d'entraînement)** — adapte sa stratégie selon l'état (early/winning/losing). Focus fire : PV les plus bas. La posture « winning » tient ses objectifs.

**TacticalBot (holdout d'évaluation, V11 §10.5)** — utilisé UNIQUEMENT en évaluation, jamais dans `bot_training.ratios`. Tir et mêlée : **tuable ce tour > peu de PV > menace élevée**. Charge : seulement si la mêlée est avantageuse.

### Evaluation Commands

```bash
# Manual evaluation (no training)
python ai/train.py --agent <agent_key> --test-only --test-episodes 20
# Equivalent alias:
python ai/train.py --agent <agent_key> --eval --test-episodes 20
```

### Architecture d'évaluation (runtime)

- `evaluate_against_bots()` (`ai/bot_evaluation.py`) est le **point unique d'évaluation**.
- Mode parallèle : `ProcessPoolExecutor` avec contexte `spawn`.
- Seeds d'épisode déterministes via `hashlib.md5`.
- Robustesse aux hangs : polling non-bloquant, deadline par tâche (`bot_eval_task_timeout_seconds`).

### ⚠️ `ai/bot_evaluation.py` est LA boucle d'évaluation de référence

**Règle : aucun autre outil ne réécrit une boucle d'évaluation.**

Les décisions qui doivent être identiques partout (`_eval_worker_task` et `_build_eval_obs_normalizer_for_worker`) :

| Décision | Voie unique |
|---|---|
| Observation | obs `Dict` servie telle quelle à `predict` (jamais aplatie) |
| Normalisation | `_build_eval_obs_normalizer_for_worker` (traite `Dict` **et** `Box`) |
| Masque d'actions | `W40KEngine.get_action_mask` |
| Plafond de pas | dérivé de `config_loader.get_max_turns` |
| Siège contrôlé | `require_key(info, "controlled_player")` |
| Épisode tronqué | compté à part (`failed_episodes`), hors du taux de victoire |

Copies connues : `scripts/roster_matchup_stats.py` (`_run_single_episode`), verrouillée par `tests/unit/scripts/test_roster_matchup_eval_loop.py`.

### Model gating (production)

`model_gating_enabled=true` active un gate dur avant promotion de modèle. Un eval passe le gate uniquement si :
- `combined >= model_gating_min_combined`
- `worst_bot_score >= model_gating_min_worst_bot` (`min(random, greedy, defensive)`)
- `worst_scenario_combined >= model_gating_min_worst_scenario_combined`

**Plancher `vs_control`** (`model_gating_min_vs_control`) : s'applique **même quand `model_gating_enabled` est `false`**. La clé doit être présente dans le profil (pas dans `_training_common.json`). Mettre `0.0` pour désarmer explicitement.

### Win Rate Benchmarks

| Training Stage | vs Random | vs Greedy | vs Defensive | vs Control | vs Adaptive |
|----------------|-----------|-----------|--------------|------------|-----------------|
| Start          | 30-40%    | 10-20%   | 5-15%        | 10-20%     | 0-10%           |
| 1000 episodes  | 60-70%    | 40-50%   | 30-40%       | 35-45%     | 15-25%          |
| 3000 episodes  | 80-90%    | 60-70%   | 50-60%       | 55-65%     | 35-45%          |
| 5000 episodes  | 90%+      | 75-85%   | 65-75%       | 65-75%     | 50-60%          |

---

## Anti-Overfitting Strategies

### The Problem: Pattern Exploitation vs. Robust Tactics

**Symptom**: Agent performs well against simple bots but fails against RandomBot or ControlBot/AdaptiveBot.

**Root Cause**: L'agent a appris à **exploiter des patterns prévisibles** au lieu de développer des stratégies robustes.

### Solution 1: Bot Stochasticity

```python
GreedyBot(randomness=0.15)    # 15% chance of random action
DefensiveBot(randomness=0.15)
```

**Tuning recommendations**:
- `0.10` = **Training** (adversaires plus forts et consistants)
- `0.15` = **Evaluation** (benchmark standard)
- `0.05` = configuration courante dans les profils

### Solution 2: Balanced Reward Penalties

**Wait penalty**: -0.5 to -1.0 (éviter -2.0+ qui force un jeu imprudent).

### Solution 3: Balanced Multi-Bot Evaluation Weights

**Configuration actuelle** :
```json
"bot_eval_weights": {
  "control": 0.40,
  "adaptive": 0.20,
  "greedy": 0.20,
  "defensive": 0.20,
  "tactical": 0.0
}
```
`tactical` (holdout) est joué et mesuré, mais son poids nul l'exclut du `combined`. `random` n'est pas évalué.

**Randomness par bot** (`bot_eval_randomness`) : `0.05` pour chaque bot pondéré, `tactical` compris — l'absence d'une entrée lève un `KeyError` explicite.

### Solution 4: Weighted Training Bots

```json
"bot_training": {
  "ratios": {
    "control": 0.40,
    "adaptive": 0.20,
    "greedy": 0.20,
    "defensive": 0.20,
    "random": 0.05
  },
  "randomness": {
    "control": 0.05,
    "adaptive": 0.05,
    "greedy": 0.05,
    "defensive": 0.05
  }
}
```

Les ratios sont convertis en effectifs (`round(ratio × 10)`, `random` au minimum à 1) → pool de 11 bots. Un bot présent dans `ratios` sans entrée `randomness` lève.

**Defaults quand `bot_training` est absent**: 20% Random, 40% Greedy, 40% Defensive (legacy).

### Monitoring for Overfitting

```
bot_eval/vs_random      — Should improve from -0.5 to 0.0+
bot_eval/vs_greedy      — Should stay around 0.05-0.1
bot_eval/vs_defensive   — Should stay around 0.1-0.15
00_critical/a_bot_eval_combined  — Overall score (primary goal)
```

**✅ Healthy**: All bots within 0.2 reward range; `bot_eval_combined` et `win_rate_100ep` trend together.

**⚠️ Overfitting to predictable bots**: Agent beats Greedy/Defensive but fails vs Random (gap >0.5).

**⚠️ Overfitting to RandomBot**: `win_rate_100ep` ↑ but `bot_eval_combined` ↓.

### Troubleshooting Overfitting

**Agent struggles vs RandomBot after 1000 episodes**: increase Tier 1 bot randomness to 0.15-0.20 ; reduce wait penalty to -0.5.

**Agent becomes too passive**: increase wait penalty (-0.5 → -1.0) ; check `ent_coef` ≥ 0.10.

**Agent performs poorly against all bots**: rewards trop équilibrés (pas assez de signal) ; increase kill/damage rewards ; verify bot randomness ≤ 0.20.

---

## Hyperparamètres

### When Agent Isn't Learning

Flat rewards after 500+ episodes → increase `ent_coef` 0.05 → 0.15 ; increase `learning_rate` 0.0003 → 0.0005 ; check rewards_config.

### When Agent Is Unstable

Reward oscillates wildly → decrease `learning_rate` 0.001 → 0.0003 ; increase `n_steps` 512 → 1024 ; increase `batch_size` 64 → 128.

### When Training Is Too Slow

- Reduce `total_episodes` (use debug config first)
- Reduce `n_eval_episodes` from 5 → 2
- Use CPU instead of GPU (see section suivante)

### When Agent Exploits Mechanics

High rewards but nonsensical behavior → find the exploited reward ; reduce by 50% ; add balancing penalty ; restart from earlier checkpoint.

---

## Performance Optimization

### CPU vs GPU

**Mesuré le 2026-08-26** (i9-13900H 16 threads WSL2, RTX 4060 Laptop 8 Go, torch 2.13 cu130 — run `x1_long`).

| Metric | Value |
|---|---|
| Global throughput (`time/fps`) | ~200 steps/s (~96 episodes/min) |
| GPU utilisation | 20-38%, 3 Go / 8 Go VRAM |
| PPO update | 142 ms per minibatch of 1020 |
| Env step (offline bench) | 9,47 ms |

**Où va le temps** (cycle PPO, ~41 s de wall) : attente lockstep + IPC ≈ **73%**, GPU update ≈ 15%, env compute ≈ 8%, rollout inference ≈ 5%.

**Recommandation** : laisser `auto` (ne pas passer `--mode`). Avec l'obs `Dict` V11, la policy est un CNN et `auto` choisit CUDA si un GPU est présent. Forcer `--mode CPU` charge les mêmes cœurs que les 24 workers. L'effort d'optimisation appartient côté workers (action mask 33,2%, observation 31,9%, bot turns 30,7% d'un env step).

La configuration actuelle est `n_envs: 24`, `n_steps: 8160`, `batch_size: 1020`. Pour l'historique des benchmarks de perf et des tentatives d'optimisation BFS, voir [training_journal.md](../../Roadmap/archives/training_journal.md).

### Training Speed Tips

1. **Use debug config first** — validate setup in 10 minutes
2. **Reduce evaluation frequency** — `n_eval_episodes: 2` during development
3. **Increase n_steps** — fewer updates = faster training
4. **Disable verbose logging** — `verbose: 0` in `model_params`

---

## Troubleshooting

### Common Errors

**Error**: `Observation size mismatch`
- **Cause**: modèle entraîné avec un layout obs différent
- **Fix**: entraîner un nouveau modèle avec le `obs_size` cible (`--new`)

**Error**: `Reward key not found: SpaceMarineXXX`
- **Cause**: archétype d'unité absent du rewards config agent
- **Fix**: ajouter le profil manquant dans `*_rewards_config.json`

**Error**: `CUDA out of memory`
- **Cause**: batch size trop grand
- **Fix**: passer sur CPU ou réduire `batch_size`

**Error**: `No improvement in 1000 episodes`
- **Cause**: rewards trop sparse ou `ent_coef` trop faible
- **Fix**: vérifier rewards_config, augmenter `ent_coef` à 0.15

### Performance Issues

**Symptom**: Memory > 8GB
- Reduce `n_steps` 2048 → 1024
- Reduce `batch_size` 256 → 128
- Close TensorBoard during training

---

## Advanced Topics (External References)

### PPO Algorithm Details
- [Stable-Baselines3 PPO Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
- [PPO Paper (Schulman et al.)](https://arxiv.org/abs/1707.06347)

### Observation Space Internals
- `engine/observation_builder.py:ObservationBuilder.build_squad_observation()`
- Layout actuel : [observation_et_actions.md](observation_et_actions.md)

### Reward Calculation Logic
- `engine/reward_calculator.py:RewardCalculator`

---

## Quick Reference Cheat Sheet

```bash
# Training commands — agent ArmageddonAgent, résolution 1 (x1) ou 5 (x5_new)
python3 ai/train.py --agent ArmageddonAgent --training-config x1_debug --scenario bot --resolution 1 --new   # Test rapide
python3 ai/train.py --agent ArmageddonAgent --training-config x1       --scenario bot --resolution 1 --new   # Entraînement x1 depuis zéro
python3 ai/train.py --agent ArmageddonAgent --training-config x1_long  --scenario bot --resolution 1 --new   # Entraînement x1 long depuis zéro
python3 ai/train.py --agent ArmageddonAgent --training-config x5_new   --scenario bot --resolution 5 --new   # Entraînement x5 depuis zéro
python3 ai/train.py --agent ArmageddonAgent --training-config x5_long  --scenario bot --resolution 5 --new   # Entraînement x5 long depuis zéro
python3 ai/train.py --agent ArmageddonAgent --training-config x1       --scenario bot --resolution 1 --new --step  # Avec step logging

# Reprise sur un modèle EXISTANT
python3 ai/train.py --agent ArmageddonAgent --training-config x1 --scenario bot --resolution 1 --append
python3 ai/train.py --agent ArmageddonAgent --scenario bot --resolution 1 \
    --resume-from ai/models/ArmageddonAgent/ppo_checkpoint_640000_steps.zip

# Evaluation (no training)
python3 ai/train.py --agent ArmageddonAgent --training-config x1 --resolution 1 --test-only --step

# Monitoring
tensorboard --logdir=./tensorboard/

# Key paths
config/agents/<agent>/<agent>_training_config.json  # Training parameters
config/agents/<agent>/<agent>_rewards_config.json   # Reward definitions
ai/models/<agent_key>/model_<agent_key>.zip         # Saved model
./tensorboard/                                      # TensorBoard logs
step.log                                            # Step log (with --step)

# Success Criteria (5000 episodes)
vs Random: 90%+
vs Greedy: 75%+
vs Tactical: 55%+
```

---

## Évolutions prévues : League / curriculum training

> Ce bloc décrit l'évolution prévue du pipeline (curriculum puis league) ; **non implémenté à ce jour**.

### Objectif

Pipeline d'entraînement progressif :
1. apprentissage des fondamentaux contre bots scriptés,
2. injection progressive d'adversaires IA entraînés,
3. robustesse améliorée sans workaround.

### Principe retenu (version simple)

**Phase 1 — Bots only** : entraîner uniquement contre bots scriptés. Passage vers phase 2 basé sur la performance robuste.

**Phase 2 — Mix progressif bots/agents** : début 80% bots / 20% agents entraînés ; fin 20% bots / 80% agents.

### Schéma de configuration JSON

**Phase 1 (`default`)** :
```json
"curriculum": {
  "enabled": true,
  "phase_id": 1,
  "advance_to_phase2": {
    "metric": "bot_eval/combined",
    "threshold": 0.75,
    "worst_bot_threshold": 0.60,
    "max_drawdown": 0.08,
    "min_evals": 5,
    "require_consecutive": 3
  }
}
```

**Phase 2 (`stabilize`)** :
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

### Modules à modifier

- **`ai/train.py`** : lecture stricte de `training_config["curriculum"]` ; construction d'un `opponent_selector`.
- **`ai/env_wrappers.py`** : nouveau wrapper `LeagueControlledEnv` — tire le type d'adversaire à chaque `reset()`.
- **`ai/training_callbacks.py`** : gate de transition phase 1 → phase 2 (vérifie threshold, min_evals, consecutive, drawdown).
- **`ai/bot_evaluation.py`** : set d'évaluation bots fixe + set league séparé.

### Critères de succès

1. disparition des régressions fortes en fin de run
2. hausse du `worst_bot_score` moyen
3. variance réduite sur `combined` à budget d'épisodes comparable

### Risques et mitigations

| Risque | Mitigation |
|---|---|
| Surapprentissage à la league locale | Conserver 20% bots en fin de phase 2 |
| Non-stationnarité trop forte | Pool borné (`max_models`) + snapshots figés |
| Complexité de debug | Logs explicites : type d'adversaire, identifiant du modèle, ratio courant |

---

## Pipeline opérationnel holdout hard (CoreAgent 150pts)

### Objectif

Benchmark `holdout_hard` stable, équitable en `holdout_regular`, exigeant en `holdout_hard` (opponent +10% budget), calibré via matrices multi-bots + rebalancing.

### Étape 0 — Préparation rosters et scénarios

1. Nettoyer les pools rosters (`training`, `holdout_regular`, `holdout_hard`).
2. Générer rosters agent et les rendre identiques côté opponent pour `training` et `holdout_regular`.
3. Générer `holdout_hard` séparé : agent 150pts, opponent 165pts (+10%).
4. Générer les scénarios holdout fixes avec `wall_ref` et `objectives_ref` explicites.

### Étape 1 — Matrices BOT rapides (e12)

Lancer un job par bot de `RANKING_BOTS` en parallèle (`control`, `adaptive`, `greedy`, `defensive`) avec `--episodes 12`. Avec 90×90 rosters hard : 8100 matchups **par bot**.

### Étape 2 — Rebalancing BOT

```bash
# Dry-run (propose des affectations sans écrire)
python scripts/rebalance_holdout_hard_scenarios.py
# Apply
python scripts/rebalance_holdout_hard_scenarios.py --apply
```

Paramètres : `target-win-rate` (ex: 0.40), bande `min/max` (ex: 0.25-0.50), plancher (ex: 0.20), filtre opponent, diversité (`max-repeat-per-opponent`).

### Étape 3 — Revalidation robuste (e30)

Relancer 3 bots en parallèle avec `--episodes 30`. Critère GO : au moins 8/10 scénarios dans `[0.25, 0.50]`, aucun scénario sous `0.20`, dispersion inter-bots raisonnable.

### Étape 4 — Validation finale ciblée (e50)

1. Extraire les cas borderline depuis e30 (proches de `0.25±0.05` ou `0.50±0.05`, forte dispersion).
2. Lancer des évaluations ciblées en `--episodes 50`.
3. Snapshotter chaque résultat e50 dans `reports/e50_candidates/raw_matchups/`.

**Décision GO / NO-GO sur la vue complète e30** (10 scénarios), pas sur le sous-ensemble e50.

### Étape 5 — Boost des rosters faibles

1. Extraire les IDs faibles depuis le dry-run.
2. Générer des candidats boostés par type (palier `+5` points).
3. **Recalculer les 3 matrices BOT (`e30`) immédiatement après remplacement**.
4. Recalibrer les scénarios hard (dry-run puis apply).
5. Archiver les anciens (`*_deprecated`).

Outil d'automatisation : `scripts/auto_boost_weak_rosters.py`.

---

## Summary

**Ce document est la référence unique pour tout le training et le tuning** : pipeline, configs, monitoring, hyperparamètres, anti-overfitting, dépannage.

**Principe clé** : entraînement en complexité complète dès le début (pas de curriculum).

Compléments :
- **Métriques et tuning** → [metriques.md](metriques.md)
- **Journal de runs datés / perf** → [../../Roadmap/archives/training_journal.md](../../Roadmap/archives/training_journal.md)
- **Moteur de jeu** → [architecture_moteur.md](../moteur/architecture_moteur.md)
- **Observation** → [observation_et_actions.md](observation_et_actions.md)
