# Board×10 — Audit Entraînement RL

**Date :** 2026-05-06  
**Périmètre :** Reprise de l'entraînement CoreAgent après migration Board×10 (360×312).  
**Méthode :** Lecture directe des fichiers + grep ciblé sur les points critiques.  
**Résultat global :** **L'entraînement peut être lancé. Aucun problème bloquant.**

---

## 1. Résumé exécutif

La migration Board×10 est **complète** du côté IA/entraînement. Les vérifications suivantes passent :

| Point | Résultat |
|-------|---------|
| Action space fixe 13 slots | ✅ |
| Observation vector 355 floats | ✅ |
| Normalisations via `perception_radius` (pas hardcodé) | ✅ |
| `inches_to_subhex` appliqué au chargement | ✅ |
| Board config lu depuis `360x312/board_config.json` | ✅ |
| Scénarios d'entraînement présents | ✅ 10 regular + 10 hard |
| Modèle actuel disponible | ✅ 5.5 MB |
| VecNormalize activé | ✅ |
| Budgets pathfinding configurés | ✅ |
| Problèmes bloquants | **0** |

Deux points nécessitent attention **avant** un entraînement sérieux :
1. La config `default` est en **mode debug** (10 épisodes, 4 envs).
2. Les modèles existants datent du **30 mars 2026**, soit **avant** la migration Board×10 (avril 2026).

---

## 2. Fichiers analysés

| Fichier | Lignes | État | Notes |
|---------|--------|------|-------|
| `ai/train.py` | 5039 | ✅ Migré | Pipeline complet |
| `ai/training_utils.py` | 540 | ✅ Migré | `make_training_env` OK |
| `ai/training_callbacks.py` | 2396 | ✅ Migré | LR/entropy schedules OK |
| `ai/env_wrappers.py` | 1206 | ✅ Migré | `BotControlledEnv`, `SelfPlayWrapper` |
| `engine/w40k_core.py` | 4640 | ✅ Migré | Action/obs spaces, inches_to_subhex |
| `engine/action_decoder.py` | 1520 | ✅ Migré | 13 slots, masques O(k) |
| `engine/observation_builder.py` | ~2400 | ✅ Migré | Norm par `perception_radius` |
| `config/agents/CoreAgent/CoreAgent_training_config.json` | ~350 | ⚠️ Valeurs debug | Voir §4 |
| `config/board/360x312/board_config.json` | ~100 | ✅ Correct | `360×312`, `inches_to_subhex: 10` |
| `config/game_config.json` | — | ✅ Correct | `max_episode_steps: 500` |
| `engine/utils/weapon_helpers.py` | 74 | ℹ️ Faux positif §19 | Voir §5.3 |
---

## 3. Compatibilité Board×10 — vérification point par point

### 3.1 Action space

**Fichier :** [engine/w40k_core.py:580](file:///home/greg/40k/engine/w40k_core.py)

```python
self.action_space = gym.spaces.Discrete(13)
```

- 13 slots fixes : [0-3] move, [4-7] shoot targets, [8] shoot wait, [9] charge, [10] fight, [11] WAIT, [12] ADVANCE.
- Indépendant de la taille du plateau. ✅
- Masques : `get_action_mask()` retourne `np.ndarray(13, bool)`, O(k) avec k = 5 max targets. ✅

### 3.2 Espace d'observation

**Fichier :** [engine/w40k_core.py:611](file:///home/greg/40k/engine/w40k_core.py)

```python
self.observation_space = gym.spaces.Box(low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32)
```

- `obs_size` = 355, chargé depuis config, **sans valeur par défaut** (erreur explicite si absent). ✅
- Composition documentée dans config : `16 global + 22 capabilities + 32 terrain + 72 ally + 132 enemy + 40 targets + 41 extra`. ✅
- Aucun indice `cols×rows` dans les observations. ✅

### 3.3 Normalisations

**Fichier :** [engine/observation_builder.py:102](file:///home/greg/40k/engine/observation_builder.py)

```python
self.perception_radius = obs_params["perception_radius"]  # Obligatoire depuis config
```

- Toutes les distances normalisées par `perception_radius` (pas de `/12.0` ou `/24.0` hardcodés). ✅
- `perception_radius` = 25 inches × 10 = **250 sub-hex** au chargement. ✅
- Ratio normalisé identique avant/après migration :
  - Ancien : MOVE = 6 hex / perception 25 = **0.24**
  - Nouveau : MOVE = 60 sub-hex / perception 250 = **0.24** ✅

### 3.4 Conversion inches → sub-hex

**Fichier :** [engine/w40k_core.py:375-403](file:///home/greg/40k/engine/w40k_core.py)

```python
_scale = int(_board_default.get("inches_to_subhex", 1))
# game_rules : engagement_zone, charge_max_distance, advance_distance_range...
# observation_params.perception_radius
# game_state : MOVE *= scale, weapon.RNG *= scale (via create_unit)
```

- Conversion effectuée **une seule fois** au chargement, via `board_config.json`. ✅
- `inches_to_subhex: 10` dans `config/board/360x312/board_config.json`. ✅

### 3.5 Scénarios d'entraînement

Scénarios disponibles pour CoreAgent :

| Pool | Fichiers | État |
|------|---------|------|
| `holdout_regular` | 10 (`scenario_bot-01..10.json`) | ✅ |
| `holdout_hard` | 10+ (`scenario_bot-01..10.json` + matchups) | ✅ |
| `training/` | 0 (dossier absent) | ℹ️ Voir §5.4 |

Structure d'un scénario (ex. `holdout_regular/scenario_bot-01.json`) :
```json
{
  "wall_ref": "walls-11.json",
  "deployment_zone": "hammer",
  "scale": "150pts",
  "agent_roster_ref": "holdout_regular/agent_holdout_regular_roster_balanced_01.json",
  "opponent_roster_ref": "holdout_regular/opponent_holdout_regular_roster_balanced_01.json",
  "primary_objectives": ["objectives_control"],
  "objectives_ref": "objectives-51.json"
}
```

Pas de `board_config` dans le scénario — il est chargé globalement via `config_loader.get_board_config()` → `360×312`. ✅

Walls disponibles dans `config/board/360x312/walls/` : `walls-11.json`, `walls-12.json`, `walls-13.json`, `walls-21.json`, `tutorial_walls-01.json`. ✅

---

## 4. Configuration d'entraînement

### 4.1 Valeurs actuelles dans `CoreAgent_training_config.json`

| Paramètre | Phase `default` | Phase `suite` | Phase `debug` |
|-----------|----------------|--------------|--------------|
| `total_episodes` | **10** ⚠️ | 50 000 ✅ | 10 |
| `n_envs` | **4** ⚠️ | 48 ✅ | 1 |
| `max_turns_per_episode` | 5 | 5 | 5 |
| `n_steps` | 16 384 | 16 384 | 256 |
| `batch_size` | 4 096 | 4 096 | 256 |
| `VecNormalize` | enabled: true | enabled: true | — |
| `bot_eval_freq` | 5 ⚠️ | 2 500 | 5 |
| `perception_radius` | 25 (inches) | 25 (inches) | 25 (inches) |

**⚠️ IMPORTANT :** La phase `default` est en mode debug avec `total_episodes: 10`. Pour un entraînement réel, utiliser `--phase suite`.

### 4.2 Budgets compute

| Budget | Valeur | Source |
|--------|--------|--------|
| `pathfinding.max_open_nodes` | 2 000 | `board_config.json` |
| `pathfinding.time_budget_us` | 5 000 µs | `board_config.json` |
| `max_episode_steps` | 500 | `game_config.json` |
| `max_turns_per_episode` | 5 | `CoreAgent_training_config.json` |

### 4.3 Hyperparamètres PPO (phase `suite`)

```json
learning_rate: {initial: 0.0001, final: 0.00003}  (linear decay)
n_steps: 16384
batch_size: 4096
n_epochs: 3
gamma: 0.99
gae_lambda: 0.95
clip_range: 0.12
ent_coef: {start: 0.02, end: 0.01}  (decay via callback)
target_kl: 0.008
net_arch: [320, 320]
```

---

## 5. Problèmes détectés

### 5.1 ⚠️ IMPORTANT — Modèles pré-migration

**Constat :** Les modèles actuels datent du **30 mars 2026**, avant la migration Board×10 (démarrée en avril 2026).

```
model_CoreAgent.zip              → 30 mars 2026, 5.5 MB
model_CoreAgent_selfplay_snapshot.zip → 27 mars 2026, 5.5 MB
ppo_checkpoint_1920000_steps.zip → pré-migration
...
```

**Impact :** Les poids du réseau ont été entraînés sur la grille 25×21 (1 inch/hex). La grille est maintenant 360×312 (0.1 inch/hex). Cependant, **les ratios de normalisation sont préservés** (§3.3), donc les valeurs d'observations restent dans le même intervalle [0, 1].

**Conclusion :** Le modèle peut être utilisé comme **point de départ** (continue training). La policy n'est pas immédiatement utilisable telle quelle sur la nouvelle grille, mais les poids ne sont pas "incompatibles" au sens SB3 — l'espace d'obs (355 floats, [0,1]) et l'action space (13) sont inchangés.

**À vérifier :** Lancer 100–200 épisodes en `--phase debug` pour s'assurer que les récompenses convergent dans des plages raisonnables. Si le modèle diverge, repartir avec `--new`.

### 5.2 ⚠️ AVERTISSEMENT — `board_config_Objectives.json` et `board_config_big.json` non migrés

**Fichiers :**
- [config/board_config_Objectives.json](file:///home/greg/40k/config/board_config_Objectives.json) — `cols: 25, rows: 21` (ancienne grille)
- [config/board_config_big.json](file:///home/greg/40k/config/board_config_big.json) — `cols: 27, rows: 23` (ancienne grille)

**Impact entraînement :** Ces fichiers ne semblent **pas utilisés** dans le pipeline d'entraînement CoreAgent. Le board config est chargé via `config_loader.get_board_config()` qui pointe sur `360×312`.

**À faire :** Identifier si ces fichiers sont encore référencés quelque part. S'ils ne le sont pas, ils peuvent être supprimés ou archivés.

### 5.3 ℹ️ INFO — `engine/utils/weapon_helpers.py` marqué unchecked dans §19

**Constat :** Le §19 du TODO cocho `[ ] engine/utils/weapon_helpers.py` comme non migré.

**Analyse :** `weapon_helpers.py` lit `require_key(w, "RNG")` directement depuis le dict d'arme. Les armes sont créées dans `game_state.py::create_unit` avec `weapon.RNG *= scale` — donc RNG est déjà en sub-hex quand `weapon_helpers` est appelé. Pas de valeur hardcodée en inches dans ce fichier.

**Conclusion :** **Faux positif** dans le TODO. `weapon_helpers.py` n'a pas besoin de migration.  
**À faire :** Cocher `[x]` dans §19 et documenter pourquoi.

### 5.4 ℹ️ INFO — Dossier `scenarios/training/` absent

**Constat :** Le code de `training_utils.py` cherche des scénarios dans `scenarios/training/`, `holdout_regular/`, et `holdout_hard/`. Le dossier `training/` n'existe pas pour CoreAgent.

**Impact :** Le `get_scenario_list_for_phase` tombera sur `holdout_regular` + `holdout_hard` uniquement. C'est le comportement attendu d'après la config (`bot_eval_scenario_pool: "holdout"`).

**Pas de problème.**

### 5.5 ℹ️ INFO — Fichier `ai/TO DELETE` vide

**Constat :** Un fichier vide nommé `TO DELETE` existe dans `ai/`. Probablement un artefact de migration.  
**À faire :** Supprimer ce fichier.

### 5.6 ℹ️ INFO — Action WAIT hardcodée `11` dans `env_wrappers.py`

**Fichier :** [ai/env_wrappers.py:418](file:///home/greg/40k/ai/env_wrappers.py)

```python
obs, reward, terminated, truncated, info = self.env.step(11)  # WAIT
```

**Impact :** Nul — l'action WAIT est slot fixe 11 par design (stable depuis la spec). Valeur cohérente avec `action_decoder.py:605`.  
**Amélioration possible :** Définir une constante nommée `ACTION_WAIT = 11` pour lisibilité.

### 5.7 ℹ️ INFO — Profiling `env.step` sur Board×10 non fait

**Constat :** La Phase D du TODO a un item restant :

> `[ ] Profiler env.step sur board 360×312 ; seuils §10.5 (à faire en conditions réelles d'entraînement).`

**Impact :** On ne sait pas encore si `env.step` p95 est dans les seuils. À vérifier lors du premier run d'entraînement.  
**Référence :** Voir `scripts/profile_env_step_360x312.py` déjà existant.

### 5.8 ℹ️ INFO — Checklist §19 replays/logs incomplète

Les items suivants restent unchecked dans §19 :
- `[ ] ai/step_logger.py`
- `[ ] ai/game_replay_logger.py`
- `[ ] ai/replay_converter.py`
- `[ ] frontend/src/utils/replayParser.ts`
- `[ ] services/replay_parser.py`

**Impact entraînement :** Nul. Ces fichiers concernent les replays et l'évaluation, pas le pipeline d'entraînement lui-même. La Phase E du TODO indique que BASE_SHAPE, BASE_SIZE, orientation ont déjà été ajoutés dans `game_replay_logger.py` et `step_logger.py`. Probable discordance entre §19 et Phase E à réconcilier.

---

## 6. Checklist §13 Plan de migration — état actuel

| Phase | Item | État |
|-------|------|------|
| **A** | Convention géométrique odd-q | ✅ |
| **A** | Paramètres perf dans `board_config.json` | ✅ |
| **A** | Périmètre vue macro vs micro | ☐ |
| **A** | Inventaire structures O(n²) | ✅ |
| **B** | Module `hex_utils.py` | ✅ |
| **B** | LoS à la demande | ✅ |
| **B** | Pathfinding BFS borné | ✅ |
| **B** | Chargement .npz optionnel | ✅ |
| **B** | Chunks coordonnées locales | ☐ (optionnel) |
| **C** | Empreintes + occupation socles ronds | ✅ |
| **C** | `engagement_zone` dans toutes les phases | ✅ |
| **C** | Déploiement avec validation empreinte | ✅ |
| **D** | Action space + masques | ✅ |
| **D** | Observations 355 floats | ✅ |
| **D** | Perf BFS FLY | ✅ |
| **D** | Perf BFS deque | ✅ |
| **D** | **Profiler `env.step` Board×10** | **☐ À faire** |
| **E** | ~~los_topology_builder~~ supprimé | ✅ |
| **E** | CI maps références + golden LoS/path | ☐ |
| **E** | Replay : BASE_SHAPE, BASE_SIZE, orientation | ✅ |
| **F** | Feature flag `inches_to_subhex` | ✅ |
| **F** | `scenario_pvp_test.json` migré 360×312 | ✅ |

---

## 7. Checklist avant lancement de l'entraînement

```
[ ] 1. Choisir la phase : --phase suite (production) ou --phase debug (test rapide)
[ ] 2. Pour test initial : lancer 50-100 épisodes en debug pour valider les rewards
[ ] 3. Vérifier que le modèle actuel converge (pas de divergence reward)
      → Si divergence : utiliser --new pour repartir de zéro
[ ] 4. Profiler env.step via scripts/profile_env_step_360x312.py
      → Valider que p95 < 5000 µs
[ ] 5. Supprimer ai/TO DELETE
[ ] 6. Cocher [x] weapon_helpers.py dans §19 du Boardx10-final.md
```

---

## 8. Commandes recommandées

### Test rapide (valider que ça tourne)
```bash
cd /home/greg/40k
python ai/train.py --agent CoreAgent --phase debug
```

### Test continue training (reprendre le modèle existant)
```bash
cd /home/greg/40k
python ai/train.py --agent CoreAgent --phase default
```

### Production (entraînement réel)
```bash
cd /home/greg/40k
python ai/train.py --agent CoreAgent --phase suite
```

### Repartir de zéro (si modèle pré-migration trop dégradé)
```bash
cd /home/greg/40k
python ai/train.py --agent CoreAgent --phase suite --new
```

---

*Audit généré le 2026-05-06 — périmètre : files ai/, engine/action_decoder.py, engine/w40k_core.py, engine/observation_builder.py, config/agents/CoreAgent/, config/board/360x312/.*
