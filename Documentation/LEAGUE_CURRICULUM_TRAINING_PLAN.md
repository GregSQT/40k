# Plan de Mise en Place d'un Curriculum League Training (PPO)

## Objectif

Mettre en place un pipeline d'entraînement progressif qui:

1. apprend d'abord des fondamentaux contre bots scriptés,
2. injecte ensuite progressivement des adversaires IA entraînés,
3. améliore la robustesse sans introduire de workaround ni de logique implicite.

Ce plan vise à réduire les oscillations de performance et à éviter les plateaux observés en fin de run.

---

## Pourquoi changer le pipeline actuel

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

## Principe retenu (version simple et robuste)

### Phase 1 - Bots only

- Entraîner uniquement contre bots scriptés.
- Critère de passage vers phase 2 basé sur la performance robuste en évaluation.

### Phase 2 - Mix progressif bots/agents

- Début: 80% bots / 20% agents entraînés.
- Fin: 20% bots / 80% agents entraînés.
- Progression linéaire des ratios sur la durée de la phase 2.

Ce design ne dépend pas d'un Elo/PFSP au départ (volontairement simple).

---

## Schéma de configuration JSON proposé

À ajouter dans les profils d'entraînement (`default`, `stabilize`) de
`config/agents/<agent>/<agent>_training_config.json`.

### Exemple phase 1 (`default`)

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

### Exemple phase 2 (`stabilize`)

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

## Mise en pratique dans les scripts

## 1) `ai/train.py`

### À ajouter

- Lecture stricte de `training_config["curriculum"]`.
- Validation stricte des champs requis selon `phase_id`.
- Construction d'un `opponent_selector`:
  - phase 1: bots uniquement,
  - phase 2: bots + modèles entraînés selon ratio courant.

### Logique ratio en phase 2

```python
progress = episodes_trained / total_episodes_phase2
bot_ratio = bot_start + (bot_end - bot_start) * progress
agent_ratio = 1.0 - bot_ratio
```

### Construction du pool d'adversaires entraînés

Depuis `ai/models/<agent_key>/`:

- `best_robust_model.zip`,
- `best_model.zip`,
- checkpoints récents (`ppo_checkpoint_*`), triés et limités à `max_models`.

Si aucun modèle éligible alors erreur explicite (pas de fallback silencieux).

### Politique de rétention des checkpoints (important)

Les checkpoints `ppo_checkpoint_*` servent à:

- constituer le pool league d'adversaires entraînés,
- reprendre un run depuis un point intermédiaire,
- diagnostiquer une régression tardive (rollback ciblé).

Recommandation:

- ajouter un flag de config explicite (ex: `retain_training_checkpoints`) pour conserver/supprimer les checkpoints en fin de run,
- ne pas hardcoder la suppression dans le script quand la league est activée.

---

## 2) `ai/env_wrappers.py`

### Nouveau wrapper recommandé: `LeagueControlledEnv`

Rôle:

- à chaque `reset()`, tirer un type d'adversaire selon les ratios courants:
  - bot scripté,
  - agent entraîné.
- exécuter ensuite le tour adverse avec l'interface actuelle (`predict(..., action_masks=...)`).

Comportement attendu:

- deterministic piloté par config (`league_opponent_deterministic`) pour les adversaires entraînés,
- conservation du comportement bots existant.

---

## 3) `ai/training_callbacks.py`

### Gate de transition phase 1 -> phase 2

Ajouter un callback de validation de passage:

- lit la métrique cible (`bot_eval/combined`),
- vérifie `threshold`, `min_evals`, `require_consecutive`,
- vérifie un second garde-fou: `worst_bot_score >= worst_bot_threshold`,
- vérifie une borne de régression: `drawdown <= max_drawdown`,
- stoppe proprement la phase 1 quand le critère est rempli.

Pas de bascule implicite sans conditions validées.

---

## 4) `ai/bot_evaluation.py`

Le pipeline actuel (normalisation éval via `vec_normalize_eval`) reste valide.

Recommandation:

- conserver un set d'évaluation fixe bots,
- ajouter ensuite un set d'évaluation league séparé,
- ne pas réutiliser exactement le même pool pour train et eval finale.

---

## Plan d'intégration recommandé

## Étape 1 - Infra minimale (sans changer les métriques)

- Ajouter `curriculum` en config.
- Implémenter validation des clés.
- Ajouter `LeagueControlledEnv`.
- Ajouter construction du pool d'adversaires entraînés.

## Étape 2 - Transition contrôlée

- Activer gate phase 1 -> phase 2.
- Démarrer la phase 2 avec ratio 80/20 et progression linéaire.

## Étape 3 - Stabilisation et mesure

- Suivre:
  - `bot_eval/combined`,
  - `bot_eval/worst_bot_score`,
  - `0_critical/b_win_rate_100ep`,
  - `0_critical/g_approx_kl`,
  - `0_critical/f_clip_fraction`.

---

## Critères de succès

Le changement est considéré positif si:

1. disparition des régressions fortes en fin de run,
2. hausse du `worst_bot_score` moyen,
3. variance réduite sur `combined` à budget d'épisodes comparable,
4. amélioration de la robustesse inter-runs (moins de dépendance seed).

---

## Risques et mitigations

- Risque: surapprentissage à la league locale.
  - Mitigation: conserver 20% bots en fin de phase 2.

- Risque: non-stationnarité trop forte.
  - Mitigation: pool borné (`max_models`) + snapshots figés.

- Risque: complexité de debug.
  - Mitigation: logs explicites par épisode:
    - type d'adversaire tiré,
    - identifiant du modèle adverse,
    - ratio courant bots/agents.

---

## Décision

Approche recommandée: **implémenter une v1 simple sans Elo/PFSP**, puis ajouter un rating seulement si nécessaire.

Ce plan donne un gain robuste à coût d'implémentation maîtrisé, compatible avec l'architecture actuelle.

