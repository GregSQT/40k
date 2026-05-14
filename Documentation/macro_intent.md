# Zone Intent System — Phase 2

> **Status** : IMPLÉMENTÉ  
> **Lien** : `AI_OBSERVATION.md` §9 (obs[346:357]), `AI_TURN.md` (phases), `AI_IMPLEMENTATION.md` (handlers)

---

## Contexte

### Ce que Phase 2 ajoute

L'agent choisit explicitement un **intent par objectif** au début de chaque tour. Chaque unité lit l'intent de son objectif le plus proche dans son observation et adapte son comportement. L'agent apprend quelle zone prioriser selon l'état du jeu.

---

## Design des zones

**Les zones sont les objectifs eux-mêmes** — pas une grille géographique fixe.

- `num_zones = len(game_state["objectives"])` au début de l'épisode
- Zone index = index de l'objectif dans la liste (ordre déterministe)
- L'unité appartient à la zone de l'objectif le plus proche d'elle : `get_nearest_objective_zone(active_unit, game_state)`
- `MAX_OBJECTIVES` = paramètre config (default : 5)

Ce design fonctionne pour toute configuration de scénario (1, 3, 5 objectifs ou autre). Les zones au-delà du nombre réel d'objectifs sont masquées dans l'action space.

---

## Les 3 intents

| Intent | Constante | Comportement mouvement | Comportement engagement |
|--------|-----------|----------------------|------------------------|
| INVADE | 0 | Avance vers l'objectif de la zone | Engage tout |
| DEFEND | 1 | Reste en position | Engage menaces locales uniquement |
| ATTACK | 2 | Voir obs ci-dessous (2 candidats, agent choisit) | Engage tout |

**Intent ATTACK — pas d'heuristique hard-coded** : l'agent reçoit deux candidats de navigation dans son observation (meilleur ennemi global + objectif de la zone) et apprend lui-même quelle cible prioriser. La cible ATTACK est toujours le meilleur ennemi *global* (pas filtré par zone). Il n'y a pas de seuils MELEE_THRESHOLD / OC_RATIO_THRESHOLD.

Default au reset : toutes les zones initialisées à INVADE.

---

## Espace d'action

`MAX_OBJECTIVES × 3` actions (ex. 5 objectifs → 15 actions).

```python
# Encoding : action_id = BASE_ZONE_INTENT + zone_idx * 3 + intent_value
# Exemple : zone 2, DEFEND → BASE_ZONE_INTENT + 2*3 + 1
```

**Disponibilité** : uniquement en command phase, comme **free steps** (l'env re-demande une action immédiatement après sans avancer la phase).

**Reward** : 0.0. L'agent apprend l'utilité de ces actions via les rewards tactiques qui suivent.

**Masking** :
- Command phase : `num_zones × 3` actions disponibles (zones actives uniquement) + actions standard
- Move / shoot / charge / fight : toutes les zone intent actions masquées
- Zones au-delà de `num_zones` : toujours masquées
- Quand `free_steps_remaining = 0` (cap épuisé) : zone intent actions masquées même en command phase

**Pas de risque de mask tout-False en command phase** : WAIT (index 11) est toujours activé dans les phases non-fight, qu'il y ait des unités éligibles ou non (`mask[11] = True` si aucune unité éligible). Les indices 16–30 (zone intents) sont `False` par `np.zeros(self.total_action_size)` — ils n'interfèrent pas avec cette garantie.

**Terminaison des free steps** : l'agent sort dès qu'il choisit une action hors des zone intent. Cap à `MAX_OBJECTIVES` free steps par command phase.

---

## Observation : obs[346:357] — 11 floats, obs_size = 357

```python
def _encode_macro_intent_context(game_state, active_unit):
    # Source de vérité pour zone_idx : unit_zone_assignments (peuplé une fois en début de command phase)
    zone_idx = game_state["unit_zone_assignments"][str(active_unit["id"])]
    intent = game_state["zone_intents"][zone_idx]   # INVADE/DEFEND/ATTACK
    objectives = game_state["objectives"]
    board_cols = game_state["board_cols"]   # normalisation col : / (board_cols - 1)
    board_rows = game_state["board_rows"]   # normalisation row : / (board_rows - 1)
    max_range  = game_state["max_range"]    # MAX_DISTANCE : distance max sur le plateau (hex)

    # Candidat 1 : navigation principale selon intent
    if intent == INVADE:
        c1_col, c1_row = objectives[zone_idx]["col"], objectives[zone_idx]["row"]
        c1_signal = get_objective_control(zone_idx, game_state)   # -1/0/1
    elif intent == DEFEND:
        c1_col, c1_row = active_unit["col"], active_unit["row"]
        c1_signal = 0.0
    elif intent == ATTACK:
        c1_col, c1_row = get_best_enemy_global(game_state)   # meilleur ennemi vivant toutes zones ; objectif de zone si aucun ennemi vivant
        c1_signal = get_best_enemy_score(game_state)          # expected_damage / HP_remaining ; 0.0 si aucun ennemi vivant

    c1_dist = calculate_hex_distance(active_unit["col"], active_unit["row"], c1_col, c1_row) / max_range

    # Candidat 2 : objectif de la zone (toujours disponible)
    c2_col, c2_row = objectives[zone_idx]["col"], objectives[zone_idx]["row"]
    c2_signal = get_objective_control(zone_idx, game_state)  # -1/0/1
    c2_dist = calculate_hex_distance(active_unit["col"], active_unit["row"], c2_col, c2_row) / max_range

    intent_onehot = [int(intent == INVADE), int(intent == DEFEND), int(intent == ATTACK)]

    return [
        c1_col / (board_cols - 1), c1_row / (board_rows - 1), c1_signal, c1_dist,   # obs[346:350]
        c2_col / (board_cols - 1), c2_row / (board_rows - 1), c2_signal, c2_dist,   # obs[350:354]
    ] + intent_onehot                                                                  # obs[354:357]
    # Total : 11 floats → obs_size = 357
```

**`get_objective_control(zone_idx, game_state) -> float`** : lit `game_state["objectives"][zone_idx]` et retourne `1.0` si contrôlé par le joueur courant (`current_player`), `-1.0` si contrôlé par l'adversaire, `0.0` si neutre ou contesté. Définie dans `macro_intents.py`.

**Source de vérité pour zone_idx dans l'obs builder** : `_encode_macro_intent_context` ne doit **pas** appeler `get_nearest_objective_zone` directement. Elle lit `zone_idx = game_state["unit_zone_assignments"][str(active_unit["id"])]`. `get_nearest_objective_zone` est appelée une seule fois en début de command phase pour peupler `unit_zone_assignments` — garantit que le masking dans `step()` et l'encodage obs utilisent la même affectation de zone.

**Pour INVADE** : candidat 1 = candidat 2 (objectif de la zone). L'agent reçoit une info redondante sur les deux candidats, mais la structure de l'observation reste stable.

**Pour DEFEND** : candidat 1 = position actuelle de l'unité (distance = 0, signal = 0.0), candidat 2 = objectif de la zone. Les deux candidats sont distincts. Le signal contextuel vient du one-hot DEFEND et de `c2_signal` (contrôle de l'objectif).

**Pour ATTACK** : candidat 1 = ennemi scoré (damage_ratio), candidat 2 = objectif. L'agent apprend s'il vaut mieux engager ou capturer selon le contexte.

**Candidat 1 pour ATTACK — toujours global** : `get_best_enemy_global(game_state)` retourne le meilleur ennemi vivant toutes zones confondues (critère : damage_ratio). Il n'y a pas de filtrage par zone. Le `zone_idx` sert uniquement à choisir *sur quelle zone* poser l'intent ATTACK — pas à restreindre la cible de navigation.

**Comportement sans ennemi vivant** : le jeu peut continuer jusqu'au tour 5 sans ennemis. Si `get_best_enemy_global` ne trouve aucun ennemi vivant, elle retourne la position de l'objectif de la zone — comportement identique à INVADE. Ce n'est pas un fallback défensif : c'est un comportement métier explicite documenté ici. Dans l'implémentation, ce cas doit être commenté comme tel dans `macro_intents.py` (`# No enemy alive: navigate to zone objective, game may continue to turn 5`). `get_best_enemy_score` retourne `0.0` dans ce cas.

**Distinguishabilité ATTACK vs INVADE sans ennemi** : quand ATTACK + aucun ennemi vivant, `obs[346:354]` est identique à INVADE (deux fois l'objectif de zone). La distinction est préservée uniquement par le one-hot `obs[354:357]` = `[0,0,1]` vs `[1,0,0]`. Ce n'est pas un bug : l'agent apprend correctement que "ATTACK sans ennemi = aller à l'objectif" via le signal one-hot. Le risque réel est de corrélation si ces états dominent le rollout (fin d'épisode uniquement — marginal). Surveiller `intent_attack_ratio` : si la valeur reste proche de `intent_invade_ratio` après 500k steps, l'agent ne distingue pas les deux intents sur les états mid-game.

---

## Fichiers à modifier (ordre strict)

> **Règle de dépendance** : la config (étape 1) doit précéder `action_decoder.py` (étape 4) car `ActionDecoder.__init__` lit `action_space_size` dès l'instanciation. Suivre l'ordre numérique sans exception.

| # | Fichier | Modification |
|---|---------|-------------|
| 0 | — | **Avant toute suppression** : `grep -r "macro_training_env\|macro_intent_id\|DETAIL_OBJECTIVE\|INTENT_TAKE\|INTENT_HOLD\|INTENT_FOCUS\|INTENT_SCREEN\|INTENT_ATTRITION\|INTENT_COUNT\|DETAIL_ENEMY\|DETAIL_ALLY\|DETAIL_NONE\|INTENT_DETAIL_TYPE" --include="*.py"` — vérifier qu'aucun fichier hors périmètre n'importe ces symboles. Import error garanti au démarrage sinon. |
| 1 | `config/agents/CoreAgent/CoreAgent_training_config.json` | `obs_size: 357`, ajouter `action_space_size: 31` (= 16 + 5×3) dans `observation_params`. Mettre `ent_coef: 0.10` (au lieu de 0.15) — voir §Risques/Dilution des gradients. **Cette étape est en position 1 car `ActionDecoder.__init__` lit `config["observation_params"]["action_space_size"]` dès son instanciation** (w40k_core.py:562 — `ActionDecoder(self.config)` reçoit le config complet). Si la clé est absente à l'étape 4, crash à l'init. |
| 2 | `ai/macro_training_env.py` | **Supprimer** — env hiérarchique Phase 1 abandonné. L'agent unifié Phase 2 le remplace. Suppression directe (historique conservé dans git). |
| 3 | `engine/macro_intents.py` | **Remplacer entièrement** le système Phase 1 (5 intents unité + `INTENT_DETAIL_TYPE` etc.). Nouveau contenu : constantes `INTENT_INVADE/DEFEND/ATTACK`, `MAX_OBJECTIVES` ; constantes action space `BASE_ZONE_INTENT = 16`, `TOTAL_ACTION_SIZE = 16 + MAX_OBJECTIVES * 3` ; fonctions `get_nearest_objective_zone(active_unit, game_state)` (utilisée uniquement pour peupler `unit_zone_assignments` en début de command phase, **pas** dans l'obs builder), `get_best_enemy_global(game_state)` (meilleur ennemi vivant toutes zones, critère damage_ratio), `get_best_enemy_score(game_state)` (retourne `0.0` si aucun ennemi vivant), `get_objective_control(zone_idx, game_state)` (voir §Observation). |
| 4 | `engine/action_decoder.py` | **Code net-new dans `__init__`** : `ActionDecoder.__init__` ne lit actuellement aucun `action_space_size` — il stocke seulement `self.config`. Ajouter la lecture : `self.total_action_size = config["observation_params"]["action_space_size"]` (raise `KeyError` si absent — pas de default). Deux magic numbers à remplacer par `self.total_action_size` : ligne 133 (`np.zeros(16, dtype=bool)`) et ligne 497 (`action_space_size=16`). `_build_mask_for_units` : mask `np.zeros(self.total_action_size)` ; lit `game_state["zone_intent_free_steps_remaining"]` pour masquer les zone intent actions quand = 0 ; masking command phase only ; masking zones > num_zones. `convert_gym_action` : décodage des actions zone intent. |
| 5 | `engine/w40k_core.py` | Init `game_state["zone_intents"]`, `zone_intent_free_steps_remaining`, `unit_zone_assignments` — **deux locations** : lignes 472–474 (reset épisode) et 931–933 (init partie). Supprimer les imports `INTENT_TAKE_OBJECTIVE`, `DETAIL_OBJECTIVE` ligne 42. Handler free step dans `step()`. |
| 6 | `engine/observation_builder.py` | Supprimer les deux branches legacy (`obs_size=323` et `obs_size=355`). Remplacer les constantes `LEGACY_OBS_SIZE = 323` et `RULE_AWARE_OBS_SIZE = 355` par `PHASE2_OBS_SIZE = 357` — source unique de vérité. Réécrire `_encode_macro_intent_context` : 2 candidats + intent one-hot 3D, obs_size → 357. Supprimer les imports `INTENT_DETAIL_TYPE`, `DETAIL_OBJECTIVE`, `DETAIL_ENEMY`, `DETAIL_ALLY`, `DETAIL_NONE`, `INTENT_COUNT`. Lire `zone_idx` depuis `game_state["unit_zone_assignments"]`, pas depuis `get_nearest_objective_zone`. |
| 7 | `engine/reward_calculator.py` | Ajouter `compute_zone_intent_shaping(game_state) -> float` : +0.05 par zone DEFEND si objectif tenu, -0.05 si objectif perdu en zone INVADE. **Appelée depuis `w40k_core.step()`** (voir §Design free steps), jamais en interne dans `reward_calculator`. Évalue l'état hérité du tour précédent au moment où les intents sont actifs. Pour les actions zone intent elles-mêmes, le reward 0.0 est retourné directement dans `step()` sans passer par le calculateur. **Import requis** : `from engine.macro_intents import INTENT_DEFEND, INTENT_INVADE, get_objective_control` — ajouter à la liste des imports de `reward_calculator.py`. |
| 8 | `ai/metrics_tracker.py` | Metrics `0_critical/n_intent_zone_steps` (nombre moyen de free steps par tour), `0_critical/intent_invade_ratio`, `0_critical/intent_defend_ratio`, `0_critical/intent_attack_ratio` (distribution des intents sur les free steps uniquement, somme = 1.0) |
| 9 | `Documentation/AI_OBSERVATION.md` | Documenter les nouvelles actions + obs[346:357] |
| 10 | `engine/pve_controller.py` | Supprimer les writes `game_state["macro_intent_id"]`, `["macro_detail_type"]`, `["macro_detail_id"]`. Supprimer les imports des constantes Phase 1 (`INTENT_TAKE_OBJECTIVE`, `DETAIL_OBJECTIVE` etc.). **Supprimer également** les blocs masking et décodage d'actions macro Phase 1 (lignes ~563–813) — ils deviennent unreachable et importent des constantes supprimées de `macro_intents.py` (import error au démarrage si non nettoyés). Le bot continue à jouer normalement — ses handlers mouvement/tir ne lisent pas ces clés. **Le bot n'émettra jamais d'actions 16–30** : `pve_controller.py` génère des actions hardcodées dans l'espace 0–15 uniquement (ses handlers sont des appels directs, pas des samples de l'action space). Si par bug `convert_gym_action` reçoit une valeur 16–30 via le bot, c'est un invariant cassé — ajouter une guard explicite dans `convert_gym_action` : `if action_int >= BASE_ZONE_INTENT and source == "pve": raise ValueError(...)`. |
| 11 | `ai/train.py` | Supprimer l'import `MacroTrainingWrapper, MacroVsBotWrapper` (ligne 1013) et l'import `make_macro_training_env` (ligne 1038). Supprimer l'appel `make_macro_training_env(...)` (ligne 2009). Import error garanti au démarrage si ces références survivent à la suppression de `macro_training_env.py`. |
| 12 | `ai/training_utils.py` | Supprimer l'export `'make_macro_training_env'` (ligne 33), la définition `make_macro_training_env(...)` (lignes 261–293), et l'import interne `from ai.macro_training_env import MacroTrainingWrapper` (ligne 294). |
| 13 | Tests | **`tests/unit/engine/test_observation_builder.py`** : remplacer `obs_size: 323` (ligne 23) par `obs_size: 357` et l'assertion `b.obs_size == 323` (ligne 199) par `b.obs_size == 357`. Supprimer ou adapter `_make_builder()` pour pointer sur le seul obs_size valide. **`tests/unit/engine/test_action_decoder.py`** : mettre à jour `mask = np.zeros(16, dtype=bool)` (ligne 283), les `assert len(mask) == 16` (lignes 333, 344), et réécrire `test_action_space_size_is_16` (ligne 445) pour tester `total_action_size = 31` via config. Les tests doivent passer `action_space_size: 31` dans leur config de fixture. |

---

## Ce qui ne change pas

- Architecture PPO (MaskablePPO, n_envs=48, hyperparams)
- Logique de jeu du bot (`pve_controller.py`) — seuls les writes des anciennes clés macro intent sont supprimés
- Les features obs[0:346] sont inchangées

## Ce qui disparaît (Phase 1 → Phase 2)

Le système Phase 1 de macro intent est **entièrement remplacé**, pas étendu :

| Supprimé | Remplacé par |
|----------|-------------|
| `macro_intent_id` dans `game_state` | `game_state["zone_intents"][zone_idx]` |
| `macro_detail_type`, `macro_detail_id` | Encodé directement dans obs (candidats c1/c2) |
| `INTENT_TAKE_OBJECTIVE`, `HOLD_OBJECTIVE`, `FOCUS_KILL`, `SCREEN`, `ATTRITION` | `INTENT_INVADE`, `INTENT_DEFEND`, `INTENT_ATTACK` |
| `INTENT_DETAIL_TYPE`, `DETAIL_OBJECTIVE`, `DETAIL_ENEMY`, `DETAIL_ALLY`, `DETAIL_NONE` | Supprimés |
| Intent choisi par logique externe | Intent choisi par l'agent via action en command phase |

Vérifier qu'aucun autre fichier n'importe ces constantes avant suppression (`grep -r "macro_intent_id\|DETAIL_OBJECTIVE\|INTENT_TAKE" --include="*.py"`).

**Action space** : `BASE_ZONE_INTENT = 16` et `TOTAL_ACTION_SIZE = 16 + MAX_OBJECTIVES * 3` sont la source unique de vérité, définis dans `macro_intents.py`. `ActionDecoder` et `w40k_core` lisent ces constantes — aucun magic number 16 dans le code.

**Branches legacy supprimées** : les branches `obs_size=323` dans `observation_builder.py` et `action_decoder.py` sont supprimées. Aucun checkpoint antérieur à Phase 2 n'est rechargeable — comportement attendu puisque Phase 2 repart d'un nouveau training.

---

## Risques et mitigations

### Credit assignment dilué
Les actions zone intent ont reward=0.0. L'agent apprend leur utilité via des rewards différés. Avec GAE (λ=0.95) et des épisodes de 30-50 steps, le signal se propage jusqu'aux free steps du début de tour avec une décroissance ~0.95^30 ≈ 0.21.

**Mitigation** : shaping reward +0.05 par zone DEFEND si objectif tenu en fin de free steps, -0.05 si objectif perdu en zone INVADE. Activer dès le début — ne pas attendre l'effondrement de l'entropie. (±0.01 est noyé dans le bruit avec GAE sur 30-50 steps ; ±0.05 ≈ 2.5% d'un kill, propagé à ~0.008 aux free steps du début de tour via (γλ)^30 = (0.99 × 0.95)^30 ≈ 0.16.)

### Spam de free steps
L'agent peut looper sur les zone intents pour éviter les décisions tactiques.

**Mitigation** : cap à `MAX_OBJECTIVES` free steps max par command phase. Surveiller via `0_critical/n_intent_zone_steps` — si la valeur converge vers 0, l'agent ignore les intents ; si elle est proche de MAX_OBJECTIVES à chaque tour, il spamme.

### Régression Policy existante
Ajouter `MAX_OBJECTIVES × 3` actions dilue la distribution de politique. Les couches de sortie pour les nouvelles actions sont initialisées à zéro → déséquilibre des gradients au début.

**Mitigation** : training from scratch obligatoire (`--new`) — obs_size 355→357 rend tout checkpoint Phase 1 incompatible. Surveiller `0_critical/j_entropy_loss` sur les 100k premiers steps — une chute brutale indique que les nouvelles têtes de sortie absorbent les gradients.

### obs_size change (355 → 357)
Un checkpoint entraîné avec obs_size=355 est **incompatible** avec obs_size=357.

**Mitigation** : l'implémentation Phase 2 repart nécessairement d'un nouveau training. Documenter le changement dans le config CoreAgent.

### Dilution des gradients sur les 16 actions existantes
Avec 31 actions au lieu de 16, l'entropie initiale est log(31) ≈ 3.4 nats vs log(16) ≈ 2.8 nats. Avec `ent_coef=0.15`, la pression entropique élevée ralentirait la convergence des actions tactiques.

**Mitigation** : utiliser `ent_coef=0.10` pour Phase 2 (au lieu de 0.15). Réduit la pression entropique sans tuer l'exploration des nouvelles têtes. Si après 500k steps `intent_defend_ratio` et `intent_attack_ratio` restent ~0.0, monter à 0.12 ponctuellement pour forcer l'exploration DEFEND/ATTACK. Surveiller `j_entropy_loss` : une décroissance continue (même lente) est normale ; une entropie plate au-delà de 200k steps indique un problème de gradient.

### total_episodes n'est plus un proxy fiable pour le temps de training
`bot_eval_freq: 2000` compte des **épisodes**, pas des timesteps. Les free steps n'ajoutent pas d'épisodes — ils allongent chaque épisode (max ~8% de steps supplémentaires par épisode avec 5 free steps sur ~300 steps). Aucune action requise. Piloter le training par `train/total_timesteps` en TensorBoard pour les comparaisons Phase 1 / Phase 2.

---

## Design d'implémentation : free steps dans w40k_core.py

C'est le changement le plus risqué. Voici le design précis à implémenter dans `step()`.

### État nécessaire dans `game_state`

```python
game_state["zone_intent_free_steps_remaining"] = 0   # reset à MAX_OBJECTIVES au début de command phase
game_state["unit_zone_assignments"] = {}              # {unit_id: zone_idx}, calculé une fois en début de command phase
```

`unit_zone_assignments` est calculé au même moment que le reset de `zone_intent_free_steps_remaining` (avant les free steps). Reste stable pendant tout le tour — la résolution dynamique (quelle cible pour ATTACK) est recalculée à chaque step dans l'observation, mais l'appartenance à une zone ne change pas en cours de tour.

### Logique dans step() — command phase

```python
# En command phase, si action ∈ zone intent actions :
if is_zone_intent_action(action):
    if game_state["zone_intent_free_steps_remaining"] <= 0:
        # garde : l'agent a tenté un zone intent alors que le masking aurait dû l'en empêcher
        return invalid_action_penalty()
    zone_idx, intent_value = decode_zone_intent_action(action)
    game_state["zone_intents"][zone_idx] = intent_value
    game_state["zone_intent_free_steps_remaining"] -= 1
    if game_state["zone_intent_free_steps_remaining"] == 0:
        # Cap épuisé : déclencher le shaping maintenant, avant de retourner.
        # La prochaine action sera non-zone-intent (zone intents masqués) mais remaining=0
        # → le hook de la branche non-zone-intent ne firrait PAS sans cette ligne.
        game_state["_pending_zone_shaping"] = reward_calculator.compute_zone_intent_shaping(game_state)
    # NE PAS avancer la phase — retourner (True, result) sans phase_complete=True
    # Le wrapper Gym rappelle ObservationBuilder normalement : aucune interface spéciale.
    return True, {"action": "zone_intent", "zone_idx": zone_idx, "intent": intent_value}

# Action non-zone-intent → sortir des free steps
if game_state["zone_intent_free_steps_remaining"] > 0:
    # Sortie volontaire : l'agent a choisi une action tactique avant d'épuiser le cap.
    game_state["_pending_zone_shaping"] = reward_calculator.compute_zone_intent_shaping(game_state)
game_state["zone_intent_free_steps_remaining"] = 0

# Ajouter le shaping accumulé (cap épuisé ou sortie volontaire) au reward de cette action.
# _pending_zone_shaping est absent si aucun free step n'a eu lieu ce tour.
shaping = game_state.pop("_pending_zone_shaping", 0.0)
# ... traitement normal de la command phase (shaping additionné au reward final)
```

**Note architecture** : `w40k_core.step()` retourne `(success, result_dict)` — c'est le wrapper Gym (SB3 `VecEnv`) qui appelle `ObservationBuilder` ensuite. Le free step ne nécessite aucune interface supplémentaire : retourner sans `phase_complete: True` suffit pour que le wrapper reboucle normalement sur la même phase.

### Points critiques

- **Invariant** : `zone_intent_free_steps_remaining` est remis à `MAX_OBJECTIVES` au début de chaque command phase, pas au début du tour. Si la command phase est skippée, il reste à 0 et aucun free step n'est disponible.
- **Masking cohérent** : quand `free_steps_remaining = 0`, les actions zone intent doivent être masquées même si on est en command phase.
- **Reset épisode** : dans `reset()`, initialiser `game_state["zone_intents"] = [INVADE] * MAX_OBJECTIVES`, `game_state["zone_intent_free_steps_remaining"] = 0` et `game_state["unit_zone_assignments"] = {}`. Sans ce dernier reset, un `KeyError` est garanti au premier obs build si la command phase n'est pas atteinte avant l'appel à `_encode_macro_intent_context`.
- **Logging** : incrémenter le compteur `n_intent_zone_steps` dans le step callback uniquement quand `is_zone_intent_action(action)` est True.
- **Interaction avec le reward shaping** : le shaping zone (+0.05 DEFEND / -0.05 INVADE) est déclenché exactement une fois par command phase, stocké dans `game_state["_pending_zone_shaping"]`, puis ajouté au reward de la première action tactique réelle. Deux chemins de déclenchement : (1) sortie volontaire — l'agent choisit une action non-zone-intent alors que `remaining > 0` ; (2) cap épuisé — le compteur passe à 0 après le dernier zone intent valide (déclenché dans la branche zone-intent elle-même, car à ce moment `remaining` vient d'atteindre 0 et la prochaine action aura `remaining=0` → la branche non-zone-intent ne firerait pas). `_pending_zone_shaping` est absent (ou 0.0) si l'agent n'a utilisé aucun free step ce tour.

---

## Metric TensorBoard

| Metric | Namespace | Valeur attendue | Signal |
|--------|-----------|-----------------|--------|
| `0_critical/n_intent_zone_steps` | 0_critical | 1–MAX_OBJECTIVES | =0 → agent ignore les intents ; =MAX_OBJECTIVES systématique → spam |
| `0_critical/intent_invade_ratio` | 0_critical | 0.2–0.6 | ~1.0 → agent utilise seulement INVADE, n'a pas appris DEFEND/ATTACK |
| `0_critical/intent_defend_ratio` | 0_critical | 0.1–0.4 | ~0.0 → agent ne défend jamais (objectifs non tenus) |
| `0_critical/intent_attack_ratio` | 0_critical | 0.1–0.4 | ~0.0 → ATTACK jamais utilisé (signal de dommage pas exploité) |
| `train/value_loss` | train (SB3) | décroissant puis stable | hausse transitoire les 100k premiers steps = normale (états command phase à reward 0.0 élargissent la target distribution) ; hausse persistante après 200k steps = signal de value divergence |

Ces trois ratios sont calculés sur les free steps de la command phase uniquement. Leur somme = 1.0. Si après 500k steps la distribution reste ~(1.0, 0.0, 0.0), les nouvelles têtes de sortie ne convergent pas.

**Implémentation dans `metrics_tracker.py`** : maintenir trois compteurs cumulatifs (`_intent_invade_count`, `_intent_defend_count`, `_intent_attack_count`) incrémentés à chaque free step. Les ratios sont calculés et loggés à chaque intervalle de log (`n_steps` rollout) en divisant par le total des free steps sur la fenêtre. Réinitialiser les compteurs après chaque log (fenêtre glissante, pas cumulatif depuis le début du training) pour que les ratios reflètent l'évolution récente de la politique. `n_intent_zone_steps` : moyenne sur les épisodes complétés dans la fenêtre courante.

---

## Critère de succès

1. Les `num_zones × 3` actions zone intent apparaissent dans le masque en command phase
2. Elles sont masquées en move/shoot/charge/fight
3. Les zones au-delà de `len(objectives)` sont masquées même en command phase
4. `game_state["zone_intents"]` se met à jour après une action zone intent
5. Pour intent ATTACK : obs[346:350] = position ennemi scoré, obs[350:354] = position objectif (valeurs distinctes) — vérifier obs[346:357]
6. `0_critical/n_intent_zone_steps` est loggé et borné

Gate de performance : winrate > 60% stable sur 3 scénarios bot distincts après 2M steps.

