# Zone Intent System — Phase 2

> **Status** : IMPLÉMENTÉ  
> **Lien** : `AI_OBSERVATION.md` §9 (obs[346:357]), `AI_TURN.md` (phases), `AI_IMPLEMENTATION.md` (handlers)

> ⚠️ **BANDEAU DE DOCUMENT — le candidat ATTACK décrit ici n'existe plus (V11 §0.43 / §9 P3-1/P3-2,
> commit `2d6bd2a8`).** `get_best_enemy_global`, `get_best_enemy_score` et
> `get_best_enemy_score_for_unit` ont été **supprimées** de `engine/macro_intents.py` : cette
> heuristique par `damage_ratio` tranchait la cible à la place de l'agent, alors que la cible
> (charge 11.02/11.04, mêlée 12.05) est désormais une **dimension d'action** (slots ennemis
> `CHARGE_SLOT_BASE`/`FIGHT_SLOT_BASE`, scorés par la tête pointeur).
> **Ce bandeau couvre TOUT le document**, et en particulier :
> - l'exemple de code de la section *Observation* (candidat 1 d'ATTACK) : ces appels ne
>   compilent plus ;
> - les paragraphes « Candidat 1 pour ATTACK — toujours global » et « Comportement sans ennemi
>   vivant » ;
> - la table *Fichiers à modifier*, dont la ligne 3 **prescrit de créer ces fonctions** : cette
>   prescription est CADUQUE, ne pas la réexécuter. La même table renvoie à `convert_gym_action`
>   pour le décodage des zone intents ; le décodage vif est `is_zone_intent_action` /
>   `decode_zone_intent_action` (`w40k_core`), et `convert_gym_action` est lui-même en cours de
>   suppression sur une autre branche.
>
> Le reste (design des zones, intents INVADE/DEFEND/ATTACK, `get_objective_control`,
> `get_nearest_objective_zone`, free steps) reste vif. Le document est conservé comme mémoire de
> conception.

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

> ⚠️ **PÉRIMÉ** — voir le bandeau en tête de document : les fonctions citées ci-dessous n'existent
> plus (V11 §0.43, commit `2d6bd2a8`).

**Candidat 1 pour ATTACK — toujours global** : `get_best_enemy_global(game_state)` retourne le meilleur ennemi vivant toutes zones confondues (critère : damage_ratio). Il n'y a pas de filtrage par zone. Le `zone_idx` sert uniquement à choisir *sur quelle zone* poser l'intent ATTACK — pas à restreindre la cible de navigation.

**Comportement sans ennemi vivant** : le jeu peut continuer jusqu'au tour 5 sans ennemis. Si `get_best_enemy_global` ne trouve aucun ennemi vivant, elle retourne la position de l'objectif de la zone — comportement identique à INVADE. Ce n'est pas un fallback défensif : c'est un comportement métier explicite documenté ici. Dans l'implémentation, ce cas doit être commenté comme tel dans `macro_intents.py` (`# No enemy alive: navigate to zone objective, game may continue to turn 5`). `get_best_enemy_score` retourne `0.0` dans ce cas.

**Distinguishabilité ATTACK vs INVADE sans ennemi** : quand ATTACK + aucun ennemi vivant, `obs[346:354]` est identique à INVADE (deux fois l'objectif de zone). La distinction est préservée uniquement par le one-hot `obs[354:357]` = `[0,0,1]` vs `[1,0,0]`. Ce n'est pas un bug : l'agent apprend correctement que "ATTACK sans ennemi = aller à l'objectif" via le signal one-hot. Le risque réel est de corrélation si ces états dominent le rollout (fin d'épisode uniquement — marginal). Surveiller `intent_attack_ratio` : si la valeur reste proche de `intent_invade_ratio` après 500k steps, l'agent ne distingue pas les deux intents sur les états mid-game.

---

## Fichiers à modifier (ordre strict)

> **Règle de dépendance** : la config (étape 1) doit précéder `action_decoder.py` (étape 4) car `ActionDecoder.__init__` lit `action_space_size` dès l'instanciation. Suivre l'ordre numérique sans exception.

| # | Fichier | Modification |
|---|---------|-------------|
| 0 | — | **Avant toute suppression** : `grep -r "macro_training_env\|macro_intent_id\|DETAIL_OBJECTIVE\|INTENT_TAKE\|INTENT_HOLD\|INTENT_FOCUS\|INTENT_SCREEN\|INTENT_ATTRITION\|INTENT_COUNT\|DETAIL_ENEMY\|DETAIL_ALLY\|DETAIL_NONE\|INTENT_DETAIL_TYPE" --include="*.py"` — vérifier qu'aucun fichier hors périmètre n'importe ces symboles. Import error garanti au démarrage sinon. |
| 1 | `config/agents/CoreAgent/CoreAgent_training_config.json` | `obs_size: 357`, ajouter `action_space_size: 31` (= 16 + 5×3) dans `observation_params`. Mettre `ent_coef: 0.10` (au lieu de 0.15) — voir §Risques/Dilution des gradients. **Cette étape est en position 1 car `ActionDecoder.__init__` lit `config["observation_params"]["action_space_size"]` dès son instanciation** (w40k_core.py — `ActionDecoder(self.config)` reçoit le config complet). Si la clé est absente à l'étape 4, crash à l'init. |
| 2 | `ai/macro_training_env.py` | **Supprimer** — env hiérarchique Phase 1 abandonné. L'agent unifié Phase 2 le remplace. Suppression directe (historique conservé dans git). |
| 3 | `engine/macro_intents.py` | **Remplacer entièrement** le système Phase 1 (5 intents unité + `INTENT_DETAIL_TYPE` etc.). Nouveau contenu : constantes `INTENT_INVADE/DEFEND/ATTACK`, `MAX_OBJECTIVES` ; constantes action space `BASE_ZONE_INTENT = 16`, `TOTAL_ACTION_SIZE = 16 + MAX_OBJECTIVES * 3` ; fonctions `get_nearest_objective_zone(active_unit, game_state)` (utilisée uniquement pour peupler `unit_zone_assignments` en début de command phase, **pas** dans l'obs builder), `get_best_enemy_global(game_state)` (meilleur ennemi vivant toutes zones, critère damage_ratio), `get_best_enemy_score(game_state)` (retourne `0.0` si aucun ennemi vivant), `get_objective_control(zone_idx, game_state)` (voir §Observation). |
| 4 | `engine/action_decoder.py` | **Code net-new dans `__init__`** : `ActionDecoder.__init__` ne lit actuellement aucun `action_space_size` — il stocke seulement `self.config`. Ajouter la lecture : `self.total_action_size = config["observation_params"]["action_space_size"]` (raise `KeyError` si absent — pas de default). Deux magic numbers à remplacer par `self.total_action_size` : ligne 133 (`np.zeros(16, dtype=bool)`) et ligne 497 (`action_space_size=16`). `_build_mask_for_units` : mask `np.zeros(self.total_action_size)` ; lit `game_state["zone_intent_free_steps_remaining"]` pour masquer les zone intent actions quand = 0 ; masking command phase only ; masking zones > num_zones. `convert_gym_action` : décodage des actions zone intent. |
| 5 | `engine/w40k_core.py` | Init `game_state["zone_intents"]`, `zone_intent_free_steps_remaining`, `unit_zone_assignments` — **deux locations** : lignes 472–474 (reset épisode) et 931–933 (init partie). Supprimer les imports `INTENT_TAKE_OBJECTIVE`, `DETAIL_OBJECTIVE` ligne 42. Handler free step dans `step()`. |
| 6 | `engine/observation_builder.py` | Supprimer les deux branches legacy (`obs_size=323` et `obs_size=355`). Remplacer les constantes `LEGACY_OBS_SIZE = 323` et `RULE_AWARE_OBS_SIZE = 355` par `PHASE2_OBS_SIZE = 357` — source unique de vérité. Réécrire `_encode_macro_intent_context` : 2 candidats + intent one-hot 3D, obs_size → 357. Supprimer les imports `INTENT_DETAIL_TYPE`, `DETAIL_OBJECTIVE`, `DETAIL_ENEMY`, `DETAIL_ALLY`, `DETAIL_NONE`, `INTENT_COUNT`. Lire `zone_idx` depuis `game_state["unit_zone_assignments"]`, pas depuis `get_nearest_objective_zone`. |
| 7 | `engine/reward_calculator.py` | `settle_zone_intent_declaration(game_state, declaration) -> float` : solde une déclaration contre le contrôle **obtenu**. ⚠️ La prescription d'origine — `compute_zone_intent_shaping`, évaluée « au moment où les intents sont actifs », donc sur l'état hérité — était un défaut, voir §Shaping ci-dessous. **Appelée depuis `w40k_core`** (voir §Design free steps), jamais en interne dans `reward_calculator`. Pour les actions zone intent elles-mêmes, le reward 0.0 est retourné directement dans `step()` sans passer par le calculateur. **Import requis** : `from engine.macro_intents import INTENT_DEFEND, INTENT_INVADE, get_objective_control` — ajouter à la liste des imports de `reward_calculator.py`. |
| 8 | `ai/metrics_tracker.py` | Metrics `00_critical/n_intent_zone_steps` (nombre moyen de free steps par épisode), `00_critical/o_intent_control_dependency`, `combat/intent_invade_ratio`, `combat/intent_defend_ratio`, `combat/intent_attack_ratio` (distribution des intents sur les free steps uniquement, somme = 1.0), `combat/intent_shaping_aligned_ratio` |
| 9 | `Documentation/Reference/training/AI_OBSERVATION.md` | Documenter les nouvelles actions + obs[346:357] |
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

**Mitigation** : shaping reward sur le RÉSULTAT de l'intent, soldé au tour suivant (§Shaping). Activer dès le début — ne pas attendre l'effondrement de l'entropie. (±0.01 est noyé dans le bruit avec GAE sur 30-50 steps ; ±0.05 ≈ 2.5% d'un kill, propagé à ~0.008 aux free steps du début de tour via (γλ)^30 = (0.99 × 0.95)^30 ≈ 0.16.)

### Spam de free steps
L'agent peut looper sur les zone intents pour éviter les décisions tactiques.

**Mitigation** : cap à `MAX_OBJECTIVES` free steps max par command phase. Surveiller via `00_critical/n_intent_zone_steps` — si la valeur converge vers 0, l'agent ignore les intents ; si elle vaut `MAX_OBJECTIVES × nombre de tours`, il spamme. Attention à l'échelle : la courbe est un nombre de free steps **par épisode**, donc par tour il faut la diviser par la longueur d'épisode en tours.

### Régression Policy existante
Ajouter `MAX_OBJECTIVES × 3` actions dilue la distribution de politique. Les couches de sortie pour les nouvelles actions sont initialisées à zéro → déséquilibre des gradients au début.

**Mitigation** : training from scratch obligatoire (`--new`) — obs_size 355→357 rend tout checkpoint Phase 1 incompatible. Surveiller `00_critical/j_entropy_loss` sur les 100k premiers steps — une chute brutale indique que les nouvelles têtes de sortie absorbent les gradients.

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
        # Cap épuisé : la déclaration est close, on l'ENREGISTRE (intents + contrôle au moment
        # du choix). Elle sera soldée au tour suivant du même joueur — voir §Shaping.
        engine._record_zone_intent_declaration()
    # NE PAS avancer la phase — retourner (True, result) sans phase_complete=True
    # Le wrapper Gym rappelle ObservationBuilder normalement : aucune interface spéciale.
    return True, {"action": "zone_intent", "zone_idx": zone_idx, "intent": intent_value,
                  "zone_control": zone_control}   # zone_control : axe des métriques, cf. §Metric

# Action non-zone-intent → sortir des free steps
if game_state["zone_intent_free_steps_remaining"] > 0:
    # Sortie volontaire : n'enregistrer que si au moins un intent a été joué.
    engine._record_zone_intent_declaration()
game_state["zone_intent_free_steps_remaining"] = 0

# Le SOLDE, lui, a lieu en tête de la command phase (marqueur : remaining == MAX_OBJECTIVES),
# et à la terminaison pour la déclaration du dernier tour. Il alimente _pending_zone_shaping,
# que step() ajoute au reward de la première action non-zone-intent.
shaping = game_state.pop("_pending_zone_shaping", 0.0)
```

**Note architecture** : `w40k_core.step()` retourne `(success, result_dict)` — c'est le wrapper Gym (SB3 `VecEnv`) qui appelle `ObservationBuilder` ensuite. Le free step ne nécessite aucune interface supplémentaire : retourner sans `phase_complete: True` suffit pour que le wrapper reboucle normalement sur la même phase.

### Points critiques

- **Invariant** : `zone_intent_free_steps_remaining` est remis à `MAX_OBJECTIVES` au début de chaque command phase, pas au début du tour. Si la command phase est skippée, il reste à 0 et aucun free step n'est disponible.
- **Masking cohérent** : quand `free_steps_remaining = 0`, les actions zone intent doivent être masquées même si on est en command phase.
- **Reset épisode** : dans `reset()`, initialiser `game_state["zone_intents"] = [INVADE] * MAX_OBJECTIVES`, `game_state["zone_intent_free_steps_remaining"] = 0` et `game_state["unit_zone_assignments"] = {}`. Sans ce dernier reset, un `KeyError` est garanti au premier obs build si la command phase n'est pas atteinte avant l'appel à `_encode_macro_intent_context`.
- **Logging** : le step callback (`ai/training_callbacks.py`) est l'**écrivain unique** de ces compteurs — il appelle `log_zone_intent_step(intent_value, zone_control)` en lisant `info['intent_value']` et `info['zone_control']`, tous deux posés par la branche zone-intent de `w40k_core`. Le moteur a longtemps compté **en plus**, via un `_metrics_tracker` posé sur l'env par `train.py` ; ce chemin n'étant armé qu'à `n_envs == 1`, `--step` comptait double et l'entraînement multi-env non. L'attribut a été supprimé : ne pas le réintroduire.
- **Interaction avec le reward shaping** : voir §Shaping ci-dessous. La déclaration est *enregistrée* à la clôture des free steps (deux chemins : sortie volontaire, ou cap épuisé), et *soldée* au tour suivant du même joueur.

---

## Shaping : l'intent est payé sur son RÉSULTAT

**Le défaut corrigé.** La première implémentation (`compute_zone_intent_shaping`) lisait `get_objective_control` en command phase, au moment même où l'agent déclarait ses intents — donc avant qu'il ait joué son tour, et sur un contrôle figé à la fin du tour précédent (14.02 : le contrôle n'est réévalué qu'aux frontières de phase/tour). Le versement était **entièrement déterminé par l'état hérité** : déclarer DEFEND sur une zone déjà tenue rapportait le bonus que l'agent la défende ou l'abandonne ensuite.

Ce terme récompensait donc la *description* de l'état, pas sa *transformation*. Sa politique optimale consiste à recopier `objective_controllers` en intents sans changer une seule action tactique. Pire, cette politique creuse produit exactement la signature qu'une bonne politique produirait sur `00_critical/o_intent_control_dependency` — un conditionnement parfait entre intent et contrôle, pour un comportement vide. **C'est le reward qui rendait la métrique inexploitable, pas l'inverse.**

Effet de bord du même code : la boucle parcourait les `MAX_OBJECTIVES` entrées de `zone_intents` alors que `get_objective_control` rend `0.0` hors liste, si bien que les zones **inexistantes** tombaient dans « INVADE sur neutre » et versaient `invade_neutral_bonus` chaque tour — +0.2/tour gratuits sur un scénario à 3 objectifs (l'intent par défaut étant INVADE). Ce revenu passif disparaît avec l'évaluation sur résultat : une zone inexistante n'est jamais prise.

**Le cycle.** À la clôture des free steps, `W40KEngine._record_zone_intent_declaration` fige les intents déclarés **et** le contrôle au moment du choix (l'état visé n'existe plus une fois le tour joué), dans `game_state["_zone_intent_declarations"]`, une entrée par joueur. Le solde a lieu à l'ouverture de la command phase suivante *du même joueur* — `zone_intent_free_steps_remaining` plein sert de marqueur « aucun intent joué ce tour », ce qui garantit un solde et un seul, même si le joueur ne déclare rien. À cet instant le contrôle a été rafraîchi par la frontière de tour, et l'action en cours est celle du déclarant, donc `_pending_zone_shaping` part bien dans **sa** récompense (solder à la frontière elle-même tomberait sur le step de l'adversaire).

**Solde terminal** : la déclaration du dernier tour n'atteint jamais la command phase suivante. Sans rattrapage à la terminaison, le dernier tour de *chaque* épisode serait muet — et c'est celui qui décide la partie. Le solde terminal porte sur le joueur **contrôlé** et non sur l'auteur du dernier step : la partie se termine le plus souvent pendant le tour de l'adversaire, et les wrappers cumulent de toute façon les récompenses des steps du bot dans celle rendue à l'agent.

**Point de vue explicite, jamais `get_objective_control`.** Ce helper est relatif à `game_state["current_player"]`. Or le solde terminal porte sur le joueur contrôlé alors que la partie se termine pendant le tour de l'adversaire — mesuré sur le harnais moteur : **6 terminaisons sur 6** avec `current_player=2` pour `controlled_player=1`. Passer par la version relative y inversait le signe de *tous* les objectifs : le bonus DEFEND était payé exactement quand la zone avait été **perdue**. Le solde utilise donc `get_objective_control_for_player(zone_idx, game_state, player)`, et `get_objective_control` n'en est plus qu'un cas particulier.

**Ventilation** : le shaping n'est pas produit par `calculate_reward`, donc il n'apparaît pas dans `last_reward_breakdown`. Il est rattaché explicitement à la catégorie `objective` (il paie la prise et la conservation d'objectifs), sans quoi il gonflait le retour de l'épisode sans entrer dans aucune catégorie — les cinq `reward/*_total` ne sommaient plus le retour, et `reward/objective_share`, la métrique que ce shaping doit éclairer, ignorait un flux d'objectif réellement perçu.

**Fuite du solde calculé** : `_pending_zone_shaping` n'est poppé que par une action non-zone-intent, et plusieurs chemins n'y arrivent jamais (fin de partie pendant les free steps, sortie anticipée turn-limit, auto-advance). Il est donc remis à `0.0` à l'init et au reset, comme `_zone_intent_declarations`.

**Fuite inter-épisodes** : `reset()` fait un `update()` de `game_state`, pas une recréation. `_zone_intent_declarations` est donc remis à `{}` explicitement à l'init **et** au reset, sans quoi une déclaration non soldée serait payée au tour 1 de l'épisode suivant contre un plateau sans rapport.

**Barème** — les quatre montants de config gardent leurs valeurs, seule leur condition de déclenchement change :

| clé | condition |
|---|---|
| `defend_held_bonus` | DEFEND sur zone tenue à la déclaration **et conservée** |
| `invade_success_bonus` | INVADE sur zone adverse **devenue tenue** |
| `invade_neutral_bonus` | INVADE sur zone neutre **devenue tenue** |
| `invade_lost_penalty` | INVADE sur sa propre zone — incohérence de déclaration, jugée sans attendre le résultat |

ATTACK ne porte aucun terme de shaping.

⚠️ **Ce changement modifie la fonction de récompense : ré-entraînement obligatoire, les runs antérieurs ne sont pas comparables.**

---

## Metric TensorBoard

| Metric | Namespace | Valeur attendue | Signal |
|--------|-----------|-----------------|--------|
| `00_critical/n_intent_zone_steps` | 00_critical | free steps **par épisode** | =0 → agent ignore les intents ; =`MAX_OBJECTIVES × tours` → spam |
| `00_critical/o_intent_control_dependency` | 00_critical | 0–1 | **~0 → le choix d'intent est indépendant de l'état du plateau : la tête zone-intent n'a rien appris.** Non émise si `intent_control_entropy_bits` = 0. Voir ci-dessous |
| `combat/intent_mutual_info_bits` | combat | 0–H(contrôle) | numérateur de la précédente, à ne pas lire seul |
| `combat/intent_control_entropy_bits` | combat | 0–log2(3) ≈ 1.585 bit | contraste d'état offert par le plateau. **=0 → il n'y avait rien à conditionner**, la question ne se pose pas |
| `combat/intent_shaping_aligned_ratio` | combat | > sa ligne de référence | part des free steps que `settle_zone_intent_declaration` récompense — donne le SENS que la dépendance ignore |
| `combat/intent_shaping_aligned_baseline` | combat | — | ce que la même politique marquerait **sans regarder le plateau**. Seul l'écart entre les deux courbes a un sens |
| `combat/intent_invade_ratio` | combat | 0.2–0.6 | ~1.0 → agent utilise seulement INVADE, n'a pas appris DEFEND/ATTACK |
| `combat/intent_defend_ratio` | combat | 0.1–0.4 | ~0.0 → agent ne défend jamais (objectifs non tenus) |
| `combat/intent_attack_ratio` | combat | 0.1–0.4 | ~0.0 → ATTACK jamais utilisé (signal de dommage pas exploité) |
| `train/value_loss` | train (SB3) | décroissant puis stable | hausse transitoire les 100k premiers steps = normale (états command phase à reward 0.0 élargissent la target distribution) ; hausse persistante après 200k steps = signal de value divergence |

Ces trois ratios sont calculés sur les free steps de la command phase uniquement. Leur somme = 1.0. Si après 500k steps la distribution reste ~(1.0, 0.0, 0.0), les nouvelles têtes de sortie ne convergent pas.

**Pourquoi les ratios marginaux ne suffisent pas.** Une distribution plate à (1/3, 1/3, 1/3) est ambiguë : elle décrit aussi bien une tête qui tire au hasard qu'une tête qui a parfaitement appris à conditionner son intent sur l'état de l'objectif (INVADE sur zone ennemie, DEFEND sur zone tenue…) — dans les deux cas la moyenne vaut 1/3. C'est exactement ce qui a été observé sur un run de 50 000 épisodes, sans possibilité de trancher. D'où la mesure de I(intent ; contrôle de l'objectif) sur la table de contingence 3×3 (contrôle ∈ {adverse, neutre, tenu} × intent).

**Pourquoi l'information mutuelle brute ne suffit pas non plus.** I est bornée par H(contrôle), pas par log2(3). Or le contrôle est très peu contrasté au moment des free steps : ils sont joués en command phase, avant tout mouvement du tour. Mesure sur le vrai moteur — jeu aléatoire : `{neutre: 24}`, soit **H = 0 et donc I = 0 quelle que soit la politique** ; figurines immobiles : `{neutre: 5, tenu: 20}`, H = 0,72 bit seulement. Publier I seule en `00_critical` ferait lire « la tête n'a rien appris » là où il n'y avait rien à apprendre — le vert vacant déplacé d'un cran.

Le diagnostic publié est donc le **coefficient d'incertitude** `00_critical/o_intent_control_dependency` = I / H(contrôle) ∈ [0, 1] : la fraction de l'incertitude d'intent expliquée par l'état, 1.0 = intent entièrement déterminé, indépendamment du contraste du plateau. Il n'est **pas émis** quand H(contrôle) = 0 : la question n'a alors pas de sens, et un 0.0 imputerait à tort la politique. `combat/intent_control_entropy_bits` publie H pour que les deux cas restent distinguables.

Cette dépendance ne dit pas le *sens* — une politique systématiquement inverse du shaping la sature aussi (test dédié). Le sens vient de `combat/intent_shaping_aligned_ratio`, part des free steps sur un couple que `settle_zone_intent_declaration` paie réellement. **À lire uniquement contre `combat/intent_shaping_aligned_baseline`**, ce que la même politique marquerait sans regarder le plateau : cette référence n'est pas une constante et elle est haute (5/9 sur un plateau équilibré, INVADE étant payé sur deux états de contrôle sur trois). Un seuil absolu du type « > 0.5 = bon » serait trompeur ; seul l'écart entre les deux courbes porte le signal.

**Implémentation dans `metrics_tracker.py`** : fenêtre **glissante** de `ZONE_INTENT_WINDOW_EPISODES = 100` épisodes (`deque(maxlen=…)`), émise à **chaque** fin d'épisode — donc à la même cadence que toutes les autres courbes `00_critical`, ce qui les rend corrélables visuellement. Deux fenêtres parallèles : le nombre de free steps écoulés entre deux fins d'épisode, et la table de contingence 3×3.

Deux pièges dont dépend la validité de la mesure :

- **La grandeur est un ratio, jamais une valeur par épisode.** Le tracker est unique et reçoit `n_envs` épisodes entrelacés : aucun free step n'est attribuable à un épisode précis, un épisode qui se termine ramasse ce que les autres environnements ont accumulé entre-temps. Seul `total steps / total épisodes` sur la fenêtre a un sens — c'est pourquoi une lecture point-par-point de cette courbe (des pics à 144 pour une moyenne de 20) n'a jamais rien voulu dire.
- **La largeur de 100 n'est pas cosmétique.** L'écart-type par épisode est de ~18,5 sur un run de référence ; 100 épisodes le ramènent à ~0,94, contre ~0,87 à 200 et ~0,78 à 830 (un rollout) : le gain est épuisé bien avant. La constante est fixe et non dérivée de `n_steps`/`n_envs`, pour que la courbe reste comparable entre configurations. Elle porte aussi le biais de la MI empirique, positif sur échantillon fini : ~2000 free steps pour 9 cellules donnent ~0,001 bit, négligeable — réduire la fenêtre le dégraderait.

Fenêtre sans aucun free step : ni MI ni ratios ne sont émis. Écrire 0.0 se lirait comme « distribution uniforme, MI nulle », soit précisément le diagnostic recherché — un vert vacant.

---

## Critère de succès

1. Les `num_zones × 3` actions zone intent apparaissent dans le masque en command phase
2. Elles sont masquées en move/shoot/charge/fight
3. Les zones au-delà de `len(objectives)` sont masquées même en command phase
4. `game_state["zone_intents"]` se met à jour après une action zone intent
5. Pour intent ATTACK : obs[346:350] = position ennemi scoré, obs[350:354] = position objectif (valeurs distinctes) — vérifier obs[346:357]
6. `00_critical/n_intent_zone_steps` est loggé et borné
7. `00_critical/o_intent_control_dependency` est significativement > 0, avec `combat/intent_control_entropy_bits` non nulle : sans cela, soit la tête zone-intent tire indépendamment de l'état du plateau, soit le plateau n'offrait aucun contraste — les points 1–6 ne prouvent que le câblage

Gate de performance : winrate > 60% stable sur 3 scénarios bot distincts après 2M steps.

