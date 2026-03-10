# [TODO] Macro Agent (Reference Unique)

> Ce document contient des recommandations et des cibles de design macro qui ne sont pas toutes garanties comme implémentees.
> Le statut "implémente aujourd'hui" est maintenant maintenu dans `Documentation/AI_TRAINING.md` (section "Macro Training Status").

## Objectif

Ce document est la reference unique pour le macro agent: architecture, mecanismes macro/micro, configuration, scenarios, entrainement, evaluation, tuning et bonnes pratiques.

Il remplace et complete:
- `Documentation/meta_controller.md`
- `Documentation/macro_micro_load.md`

---

## 1) Vue d'ensemble

Le projet supporte deux niveaux de decision:
- **Micro**: selection d'action tactique d'une unite (move/shoot/charge/fight/wait) via modeles PPO specialises.
- **Macro**: orchestration de l'ordre/unite/intention strategique, puis delegation au micro.

Implementation actuelle:
- Wrapper principal: `ai/macro_training_env.py` (`MacroTrainingWrapper`, `MacroVsBotWrapper`).
- Entrainement/evaluation: `ai/train.py`.
- Scenarios macro actuels: `config/agents/MacroController/scenarios/*.json`.
- Config macro: `config/agents/MacroController/MacroController_training_config.json`.

---

## 2) Architecture macro/micro

### 2.1 Flux de decision

1. Le macro observe l'etat global (tour, phase, objectifs, unites, eligibilite).
2. Le macro choisit une action macro.
3. Cette action est decodee en:
   - unite ciblee,
   - intention (`intent_id`),
   - detail de l'intention (`detail_index`).
4. Le wrapper priorise l'unite dans le pool d'activation.
5. Le micro-modele de cette unite est charge et predit l'action micro.
6. L'environnement execute l'action micro.

### 2.2 Action space macro (etat actuel)

Action discrète encodee comme:
- `Discrete(max_units * INTENT_COUNT * detail_max)`

Avec:
- `max_units`: borne haute (`macro_max_units` dans training config)
- `INTENT_COUNT`: nombre d'intentions macro (voir `engine/macro_intents.py`)
- `detail_max`: max entre slots unites et slots objectifs.

### 2.3 Observation macro (etat actuel)

Observation vectorielle fixe:
- features globales (tour, phase, joueur, objectifs controles, diff valeur armee)
- bloc unites (features par unite, padde a `max_units`)
- bloc objectifs (features par objectif, padde a `max_objectives`)

Points stricts:
- `max_units` doit couvrir le pire scenario.
- `max_objectives` derive des scenarios.
- incoherence de taille => erreur explicite.

### 2.4 Interaction avec les micro modeles

Le wrapper charge les modeles micro **requis par les unites presentes dans les scenarios**:
- chemin attendu: `ai/models/<model_key>/model_<model_key>.zip`
- chargement fail-fast si un modele manque.

Le `model_key` est derive via `UnitRegistry`:
- classification par type de deplacement, tanking, cible, role
- methode: `UnitRegistry.get_model_key(unit_type)`.

---

## 3) Modes macro cotes app/PvE

Fichiers:
- `config/agents/MacroController/pve_macro_controller_app.json`
- `config/agents/MacroController/pve_macro_controller.json`

Modes:
- `micro_only`: pas de pilotage macro (pipeline micro seulement)
- `macro_micro`: macro actif + delegation micro

Recommandation:
- production stable: `macro_micro` uniquement quand micro est solide et scenarios macro valides.

---

## 4) Scenarios macro: regles de conception

## 4.1 Regles minimales obligatoires

Chaque scenario doit avoir:
- `units` valide (ids uniques, positions valides, unit_type connu)
- `objectives` non vide
- `primary_objectives` explicite
- cohérence de roster et budget

Interdits:
- ids dupliques
- unit_type absent du registry
- incoherence volontaire "cassee" pour forcer un comportement
- fallback silencieux en cas de donnees manquantes

## 4.2 Etat actuel du repository

Le dossier `config/agents/MacroController/scenarios/` contient 5 scenarios `default-*`.

Constats:
- couverture partielle seulement (pas encore de split `training/holdout` propre pour macro).
- variation de roster presente, mais pool reduit.
- au moins une anomalie de qualite detectee: id duplique dans `MacroController_scenario_default-3.json`.

Conclusion:
- base exploitable pour prototype, insuffisante pour robustesse macro long terme.

## 4.3 Cible recommandee (efficacite + solidite)

Par macro-agent:
- **training**: 12 a 20 scenarios
- **holdout**: 6 a 10 scenarios

Etager la complexite:
- petit roster: 8-10 unites
- moyen roster: 12-16 unites
- dense roster: 18-22 unites

Varier:
- topologie (ouvert/contraint)
- densite de murs
- placements
- asymetrie de valeurs
- repartition types d'unites

---

## 5) Strategie de modelisation recommandee

## 5.1 Un macro-agent par armee (recommande)

Oui: preferer **un macro par armee**.

Pourquoi:
- regles et profils differents par armee
- convergence plus rapide
- debug plus simple
- moins de non-stationnarite

## 5.2 Faut-il entrainer "chaque unite"?

Non.

Il faut couvrir:
- les **roles tactiques** (swarm/troop/elite, melee/ranged)
- les **regles speciales structurantes**
- les **interactions de compo**

Pas necessaire d'avoir 1 scenario par datasheet.

## 5.3 Macro vs micro: ordre d'entrainement

Ordre recommande:
1. stabiliser micro (modeles figes)
2. entrainer macro avec micros figes
3. eventuellement fine-tune micro ensuite, puis re-stabiliser macro

A eviter au debut:
- co-training macro+micro simultane (instable, bruit de cible trop fort).

---

## 6) Configuration macro

Fichier principal:
- `config/agents/MacroController/MacroController_training_config.json`

Champs macro specifiques:
- `macro_player` (1 ou 2)
- `macro_max_units` (borne stricte du nombre d'unites)

Champs PPO importants:
- `n_envs`
- `model_params.n_steps`
- `model_params.batch_size`
- `model_params.learning_rate`
- `model_params.clip_range`
- `model_params.ent_coef`
- `model_params.target_kl`
- `total_episodes`

Evaluation bots:
- `callback_params.bot_eval_freq`
- `callback_params.bot_eval_intermediate`
- `callback_params.bot_eval_final`
- `callback_params.save_best_robust`
- `callback_params.robust_window`
- `callback_params.robust_drawdown_penalty`
- `callback_params.model_gating_enabled`
- `callback_params.model_gating_min_combined`
- `callback_params.model_gating_min_worst_bot`
- `callback_params.model_gating_min_worst_scenario_combined`

Holdout split (si utilise):
- `callback_params.holdout_regular_scenarios`
- `callback_params.holdout_hard_scenarios`

---

## 7) Lancement train/eval macro

## 7.1 Entrainement macro

Exemple:
```bash
python ai/train.py \
  --agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --scenario all \
  --new
```

Notes:
- `--scenario all` active la rotation des scenarios trouves.
- en macro, `self/bot` ne sont pas des modes de scenario train valides.

## 7.2 Evaluation macro

Deux modes:
- `--macro-eval-mode micro`: macro vs pipeline micro
- `--macro-eval-mode bot`: macro vs bots d'evaluation

Exemple:
```bash
python ai/train.py \
  --agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --test-only \
  --scenario default-0 \
  --macro-eval-mode bot \
  --test-episodes 100
```

---

## 8) Tuning PPO macro (pratique)

## 8.1 Regles simples

- commencer simple, augmenter la complexite des scenarios ensuite
- garder `n_steps * n_envs` stable entre runs comparatifs
- ne changer que 1-2 hyperparametres a la fois
- selectionner par score robuste (pas par pic unique)

## 8.2 Plage de depart conseillée

Pour macro:
- `n_envs`: 16 a 48 selon CPU
- `n_steps` (base globale): 8k a 16k (ajustement interne par env possible)
- `batch_size`: 2k a 4k
- `learning_rate`: 2e-4 -> 6e-5 (schedule)
- `clip_range`: 0.10 a 0.15
- `ent_coef`: 0.04 -> 0.02 (schedule)
- `target_kl`: 0.008 a 0.02

## 8.3 Signaux d'alerte

- winrate training monte, holdout baisse => overfit scenarios train
- fort ecart Random vs Greedy/Defensive => policy fragile
- oscillations fortes score combine => instabilite, revoir LR/ent_coef/variete scenarios
- duree episode explose => scenarios trop lourds ou politique indecise

---

## 9) Metriques a suivre (minimum)

Training:
- progression episodes
- duree/throughput
- clip_fraction
- explained_variance
- entropy_loss
- gradient_norm

Evaluation:
- winrate par bot
- score combine
- score par scenario
- split holdout regular/hard
- worst-bot-score

Decision de validation:
- gate sur holdout (pas training)
- gate multi-bot
- gate robustesse temporelle (fenetre glissante)
- gate de promotion modele (seuils explicites, sinon promotion bloquee)

Comportement concret du gating de promotion (implante):
- evaluation PASS seulement si:
  - `combined >= model_gating_min_combined`
  - `worst_bot_score >= model_gating_min_worst_bot`
  - `worst_scenario_combined >= model_gating_min_worst_scenario_combined`
- si FAIL:
  - pas de promotion `best_model`
  - pas de promotion robust vers le modele canonique
  - logs explicites `PASS/FAIL` + detail des criteres

---

## 10) Simulation de charge macro/micro

Script:
- `scripts/macro_micro_load.py`

Objectif:
- simuler une charge macro/micro
- mesurer CPU/RAM/IO/reseau
- obtenir un debit steps/sec

Exemple:
```bash
python scripts/macro_micro_load.py \
  --scenario-file config/agents/MacroController/scenarios/MacroController_scenario_default-0.json \
  --controlled-agent MacroController \
  --training-config default \
  --rewards-config MacroController \
  --episodes 20 \
  --macro-player 1 \
  --macro-every-steps 5
```

Usage recommande:
- smoke test avant long run
- comparaison de perf avant/apres changement architecture/scenarios

---

## 11) Qualite des donnees scenarios (checklist stricte)

Avant un run macro:
- ids unites uniques
- unit_type existants dans `config/unit_registry.json`
- objectifs et primary_objectives presents
- pas de position invalide
- split train/holdout coherent
- couverture des roles tactiques ciblee
- budget et densite unites documentes

Commande recommandee (pipeline qualite):
```bash
python ai/hidden_action_finder.py
python scripts/check_ai_rules.py
python ai/analyzer.py step.log
```

---

## 12) Plan de mise en place robuste (recommande)

1. **Nettoyer** les scenarios macro existants (qualite data, ids, coherence).
2. **Structurer** macro en `scenarios/training` + `scenarios/holdout`.
3. **Creer 1 macro-agent par armee**.
4. **Fixer les micros** avant macro.
5. **Entrainer par curriculum de complexite roster**.
6. **Valider sur holdout + bots ponderes**.
7. **Deployer en `macro_micro`** seulement apres gate robuste.

---

## 13) Points de verite (code)

- Macro wrapper: `ai/macro_training_env.py`
- Entrainement/eval: `ai/train.py`
- Utils scenarios: `ai/training_utils.py`
- Eval bots: `ai/bot_evaluation.py`
- Callbacks/robust selection: `ai/training_callbacks.py`
- Registry unites/model_keys: `ai/unit_registry.py`
- Config macro: `config/agents/MacroController/*.json`

---

## 14) Decisions d'architecture recommandees

- **Oui**: un macro par armee
- **Oui**: scenarios representatifs des roles, pas exhaustivite datasheet
- **Oui**: micro stable puis macro
- **Non**: fallback silencieux
- **Non**: co-training macro+micro des le debut
- **Non**: evaluation uniquement sur scenarios train

Ce cadre maximise la probabilite d'obtenir une policy macro a la fois efficace, stable et maintenable.
