# MISE À JOUR : SHOOTING PHASE - Architecture des Caches

## 📚 SECTION 1: GLOBAL VARIABLES & REFERENCE TABLES (MISE À JOUR)

### Global Variables
```javascript
weapon_rule = (weapon rules activated) ? 1 : 0

// NOUVEAU: Position cache - snapshot des positions ennemies
position_cache = {
    target_id: {id: target_id, col: col, row: row},
    ...
}
// Mise à jour: Quand une cible meurt (retirer de position_cache)
```

### Unit-Specific Cache
```javascript
// NOUVEAU: Cache LoS par unité active (stocké sur l'unité)
unit["los_cache"] = {
    target_id: has_los,  // booléen
    ...
}
// Calculé à:
// - Activation de l'unité
// - Fin d'advance de l'unité
// Mis à jour à:
// - Mort de la cible: retirer unit["los_cache"][dead_target_id] (pas de recalcul)
// Nettoyé à:
// - Fin de l'activation (comme valid_target_pool)
```

### Function Argument Reference Table

| Function | arg1 | arg2 | arg3 |
|----------|------|------|------|
| `valid_target_pool_build(arg1, arg2, arg3)` | weapon_rule (use weapon rules?) | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |
| `weapon_availability_check(arg1, arg2, arg3)` | weapon_rule | advance_status: 0=no advance, 1=advanced | adjacent_status: 0=not adjacent, 1=adjacent to enemy |

**Critical Note on arg3 after Advance:** When unit has advanced (arg2=1), arg3 is ALWAYS 0 because advance restrictions prevent moving to enemy-adjacent destinations.

---

## 🔧 SECTION 2: CORE FUNCTIONS (MISE À JOUR)

### Function: build_position_cache()
**Purpose**: Construire le snapshot des positions ennemies  
**Returns**: void (met à jour position_cache dans game_state)

```javascript
build_position_cache():
├── position_cache = {}
├── For each unit in game_state["units"]:
│   ├── ELIGIBILITY CHECK:
│   │   ├── unit.HP_CUR > 0? → NO → ❌ Skip (dead unit)
│   │   └── unit.player === current_player? → YES → ❌ Skip (friendly unit)
│   └── ALL conditions met → ✅ Add to position_cache
│       ├── position_cache[unit.id] = {id: unit.id, col: unit.col, row: unit.row}
│       └── Continue
└── Store in game_state["position_cache"]
```

**Appelé à:**
- Début de la phase de tir (une fois)
- **PAS** après mort de cible (juste retirer l'entrée du cache)

### Function: build_unit_los_cache(unit_id)
**Purpose**: Calculer le cache LoS pour une unité spécifique  
**Returns**: void (met à jour unit["los_cache"])

```javascript
build_unit_los_cache(unit_id):
├── unit = get_unit_by_id(unit_id)
├── unit["los_cache"] = {}
├── For each target in position_cache:
│   ├── target_unit = get_unit_by_id(target_id)
│   ├── has_los = _has_line_of_sight(game_state, unit, target_unit)
│   ├── unit["los_cache"][target_id] = has_los
│   └── Continue
└── Cache calculé et stocké sur l'unité
```

**Appelé à:**
- Activation de l'unité (STEP 2: UNIT_ACTIVABLE_CHECK)
- Fin d'advance de l'unité (après mouvement effectif)
- **PAS** après mort de cible (juste retirer l'entrée du cache)

**Cas limites :**
- Si `position_cache` est vide (pas d'ennemis) : `unit["los_cache"] = {}` (cache vide mais existant)
- Si l'unité a fui : `los_cache` n'est **pas construit** (l'unité ne peut pas tirer)

### Function: update_los_cache_after_target_death(dead_target_id)
**Purpose**: Mettre à jour les caches LoS après la mort d'une cible  
**Returns**: void (retire la cible morte des caches)

```javascript
update_los_cache_after_target_death(dead_target_id):
├── Retirer de position_cache:
│   └── del position_cache[dead_target_id]
├── active_unit_id = game_state["active_shooting_unit"]  // Seule l'unité active a un los_cache
├── If active_unit_id:
│   ├── active_unit = get_unit_by_id(active_unit_id)
│   ├── If active_unit AND active_unit["los_cache"] exists:
│   │   ├── If dead_target_id in active_unit["los_cache"]:
│   │   │   └── del active_unit["los_cache"][dead_target_id]
│   │   └── Continue
│   └── Continue
└── Caches mis à jour (pas de recalcul)
```

**Note:** Seule l'unité actuellement active a un `los_cache` (calculé à l'activation). Les autres unités dans `shoot_activation_pool` n'ont pas encore de cache car elles ne sont pas encore activées. Donc on met à jour uniquement l'unité active.

**Appelé à:**
- Après la mort d'une cible dans shooting_attack_controller

### Function: valid_target_pool_build(arg1, arg2, arg3) (MISE À JOUR)
**Purpose**: Construire le pool de cibles valides pour une unité active  
**Returns**: valid_target_pool (liste d'IDs de cibles)

**CHANGEMENT CRITIQUE:** Utilise maintenant `unit["los_cache"]` au lieu de calculer directement.

**FONCTIONNEMENT:**
1. `build_unit_los_cache` parcourt `position_cache` et calcule LoS pour chaque cible, stockant le résultat dans `unit["los_cache"] = {target_id: has_los}`
2. `valid_target_pool_build` filtre `los_cache` pour ne garder que les cibles avec `has_los == true` (optimisation)
3. Pour chaque cible avec LoS, on vérifie :
   - Distance (range d'**au moins une arme** dans `weapon_available_pool`)
   - PISTOL rule (si adjacent)
   - Engaged enemy rule (si pas adjacent)
4. Les cibles qui passent tous les checks sont ajoutées au pool

**IMPORTANT:** 
- `los_cache` contient toutes les cibles de `position_cache` avec leur statut LoS (true/false)
- On filtre d'abord pour ne garder que les cibles avec LoS (pas besoin de vérifier LoS dans la boucle)
- Pas besoin de vérifier `target_id in position_cache` car `los_cache` est construit depuis `position_cache`
- Si une cible meurt, elle est retirée de `position_cache` ET de `los_cache` par `update_los_cache_after_target_death`
- **Distance check:** On vérifie si la cible est dans la portée d'**au moins une arme** du `weapon_available_pool`, pas seulement de `selected_weapon` (l'unité peut changer d'arme)

```javascript
valid_target_pool_build(arg1, arg2, arg3):
├── valid_target_pool = []
├── ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache à l'activation)
├── weapon_available_pool = weapon_availability_check(arg1, arg2, arg3)  // Build weapon_available_pool
├── usable_weapons = [w for w in weapon_available_pool if w["can_use"]]
├── Filter los_cache: targets_with_los = {target_id: true for target_id, has_los in unit["los_cache"].items() if has_los == true}
├── For each target_id in targets_with_los.keys():
│   ├── enemy_unit = get_unit_by_id(target_id)
│   ├── distance = calculate_distance(unit, enemy_unit)
│   ├── Range check: distance <= RNG of AT LEAST ONE weapon in usable_weapons? → NO → Skip enemy unit
│   ├── Adjacent check: enemy adjacent to shooter?
│   │   ├── YES → Check PISTOL weapon rule
│   │   └── NO → Check engaged enemy rule
│   └── ALL conditions met → ✅ Add target_id to valid_target_pool
└── Return valid_target_pool
```

**OPTIMISATION:** On filtre `los_cache` pour ne garder que les cibles avec LoS avant la boucle, évitant de vérifier `has_los == false` à chaque itération.

**Performance:** Utilise le cache LoS pré-calculé au lieu de recalculer à chaque fois.

**Cas limites :**
- Si `unit["los_cache"]` n'existe pas ET `unit.id NOT in units_fled` : **ERREUR** (doit être créé par `build_unit_los_cache` à l'activation)
- Si `unit["los_cache"]` n'existe pas ET `unit.id in units_fled` : NORMAL - l'unité ne peut pas tirer, mais peut avancer
- Si `unit["los_cache"]` est vide `{}` : Aucune cible dans `position_cache` → `valid_target_pool = []`
- Si toutes les cibles sont filtrées (pas de LoS, pas de range, etc.) : `valid_target_pool = []`
- Si `valid_target_pool` est vide ET unité n'a pas encore tiré : → Go to STEP 6: EMPTY_TARGET_HANDLING (l'unité peut avancer si `CAN_ADVANCE == true`)
- Si `valid_target_pool` est vide ET unité a déjà tiré : → Fin d'activation (on ne peut pas avancer après avoir tiré)

---

## 🎯 SECTION 3: PHASE FLOW (MISE À JOUR)

### STEP 0: PHASE INITIALIZATION (NOUVEAU - Avant STEP 1)

**Purpose**: Initialiser les caches globaux au début de la phase

**Appelé à:** 
- Début de la phase de tir (appelé automatiquement dans `execute_action` si `_shooting_phase_initialized` est False)
- Une seule fois par phase de tir

**Note importante :** Ce STEP 0 est ajouté AVANT le STEP 1 de `AI_TURN.md`. La numérotation des steps suivants reste identique à `AI_TURN.md` :
- STEP 1: ELIGIBILITY CHECK (identique à `AI_TURN.md`)
- STEP 2: UNIT_ACTIVABLE_CHECK (identique à `AI_TURN.md`)
- STEP 3: ACTION_SELECTION (identique à `AI_TURN.md`)
- etc.

```javascript
shooting_phase_start():
├── Set phase = "shoot"
├── Initialize weapon_rule = 1
├── Clear target_pool_cache (cache global obsolète)
├── Initialize weapon.shot = 0 for all units
├── build_position_cache()  // NOUVEAU: Construire position_cache
├── shooting_build_activation_pool()  // Build shoot_activation_pool (appelle STEP 1)
└── Continue to STEP 2: UNIT_ACTIVABLE_CHECK
```

**Note:** `shooting_phase_start()` appelle aussi `shooting_build_activation_pool()` qui implémente le STEP 1: ELIGIBILITY CHECK.

### STEP 1: ELIGIBILITY CHECK (Identique à AI_TURN.md - Lignes 584-612)

**Purpose**: Construire le pool d'activation (`shoot_activation_pool`) avec les unités éligibles

**Appelé à:**
- Début de la phase de tir (dans `shooting_phase_start()`)
- Une seule fois par phase de tir

```javascript
shooting_build_activation_pool():
├── shoot_activation_pool = []
├── For each unit in game_state["units"]:
│   ├── unit.player === current_player? → NO → Skip
│   ├── unit.HP_CUR > 0? → NO → Skip
│   ├── unit.id in units_fled? → YES → Check CAN_ADVANCE only (cannot shoot)
│   │   ├── Determine adjacency: Unit adjacent to enemy? → YES → CAN_ADVANCE = false, NO → CAN_ADVANCE = true
│   │   ├── CAN_ADVANCE == true? → YES → Add unit.id to pool (can advance but not shoot)
│   │   └── CAN_ADVANCE == false? → Skip (no valid actions)
│   ├── unit.id NOT in units_fled? → Check CAN_SHOOT OR CAN_ADVANCE
│   │   └── Determine adjacency: Unit adjacent to enemy?
│   │       ├── YES → 
│   │       │   ├── CAN_ADVANCE = false (cannot advance when adjacent)
│   │       │   ├── weapon_availability_check(weapon_rule, 0, 1) → Build weapon_available_pool
│   │       │   ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │       │   └── CAN_SHOOT == false? → YES → Skip (no valid actions)
│   │       │   └── CAN_SHOOT == true? → YES → Add unit.id to pool
│   │       └── NO →
│   │           ├── CAN_ADVANCE = true
│   │           ├── weapon_availability_check(weapon_rule, 0, 0) → Build weapon_available_pool
│   │           ├── CAN_SHOOT = (weapon_available_pool NOT empty)
│   │           ├── (CAN_SHOOT OR CAN_ADVANCE)? → NO → Skip (no valid actions)
│   │           └── (CAN_SHOOT OR CAN_ADVANCE)? → YES → Add unit.id to pool
│   └── Continue
└── Store in game_state["shoot_activation_pool"]
```

**Note:** 
- La logique d'éligibilité est calculée directement dans la boucle (comme dans `AI_TURN.md` lignes 590-611).
- **IMPORTANT:** Une unité qui a fui (`unit.id in units_fled`) peut avancer mais **ne peut pas tirer**. Elle est ajoutée au pool si `CAN_ADVANCE == true` (pas adjacent à un ennemi).
- **NOTE:** Le code actuel utilise `_has_valid_shooting_targets()` qui existe dans `shooting_handlers.py`, mais cette fonction doit être modifiée pour gérer correctement les unités qui ont fui (actuellement elle retourne `False` pour les unités qui ont fui, alors qu'elle devrait vérifier `CAN_ADVANCE`).

### STEP 2: UNIT_ACTIVABLE_CHECK (MISE À JOUR - Identique à AI_TURN.md ligne 614, avec ajout de build_unit_los_cache)

**Purpose**: Activer une unité et construire ses caches

```javascript
STEP : UNIT_ACTIVABLE_CHECK
├── shoot_activation_pool NOT empty?
│   ├── YES → Pick one unit from shoot_activation_pool:
│   │   ├── Clear valid_target_pool
│   │   ├── Clear TOTAL_ATTACK log
│   │   ├── build_unit_los_cache(unit_id)  // NOUVEAU: Calculer cache LoS
│   │   ├── Determine adjacency:
│   │   │   ├── Unit adjacent to enemy? → YES → unit_is_adjacent = true
│   │   │   └── NO → unit_is_adjacent = false
│   │   ├── weapon_availability_check(weapon_rule, 0, unit_is_adjacent ? 1 : 0) → Build weapon_available_pool
│   │   ├── valid_target_pool_build(weapon_rule, arg2=0, arg3=unit_is_adjacent ? 1 : 0)
│   │   └── valid_target_pool NOT empty?
│   │       ├── YES → SHOOTING ACTIONS AVAILABLE → Go to STEP 3: ACTION_SELECTION
│   │       └── NO → valid_target_pool is empty → Go to STEP 6: EMPTY_TARGET_HANDLING
│   └── NO → End of shooting phase → Advance to charge phase
```

**CHANGEMENT:** 
- Le cache LoS est maintenant calculé à l'activation, pas au début de la phase.
- **IMPORTANT:** Une unité qui a fui (`unit.id in units_fled`) **ne peut pas tirer**, mais **peut avancer** si elle n'est pas adjacente à un ennemi. Dans ce cas, on ne construit pas `los_cache` ni `valid_target_pool`.

### STEP 4: ADVANCE ACTION (MISE À JOUR - Identique à AI_TURN.md ligne 662, avec ajout de build_unit_los_cache)

**Purpose**: Exécuter l'action advance et mettre à jour les caches

```javascript
ADVANCE ACTION:
├── Execute advance movement
├── Unit actually moved to different hex?
│   ├── YES → Unit advanced:
│   │   ├── Mark units_advanced
│   │   ├── build_unit_los_cache(unit_id)  // NOUVEAU: Recalculer cache LoS avec nouvelle position
│   │   ├── Invalidate valid_target_pool (vide le pool)
│   │   ├── valid_target_pool_build(weapon_rule, arg2=1, arg3=0)  // Reconstruire pool avec nouveau cache
│   │   └── Continue to shooting action selection
│   └── NO → Unit didn't move → Continue normally
└── Continue to shooting action selection
```

**CHANGEMENT:** Le cache LoS est recalculé après l'advance, puis le pool est reconstruit.

### Function: shoot_action(target) (MISE À JOUR)

**Purpose**: Exécuter une séquence de tir  
**Returns**: void (met à jour SHOOT_LEFT, weapon.shot, valid_target_pool)

```javascript
shoot_action(target):
├── Execute attack_sequence(RNG)
├── Concatenate Return to TOTAL_ACTION log
├── SHOOT_LEFT -= 1
├── Target died?
│   ├── YES → 
│   │   ├── update_los_cache_after_target_death(target_id)  // NOUVEAU: Mettre à jour caches
│   │   ├── Remove from valid_target_pool
│   │   └── valid_target_pool empty? → YES → End activation
│   └── NO → Target survives
└── SHOOT_LEFT == 0 ?
    ├── YES → Current weapon exhausted:
    │   ├── Mark selected_weapon as used
    │   └── weapon_available_pool NOT empty?
    │       ├── YES → Select next available weapon:
    │       │   ├── selected_weapon = next weapon
    │       │   ├── SHOOT_LEFT = selected_weapon.NB
    │       │   ├── Determine context:
    │       │   │   ├── arg1 = weapon_rule
    │       │   │   ├── arg2 = (unit.id in units_advanced) ? 1 : 0
    │       │   │   └── arg3 = (unit adjacent to enemy?) ? 1 : 0
    │       │   ├── valid_target_pool_build(weapon_rule, arg2, arg3)  // Utilise unit["los_cache"]
    │       │   └── Continue to shooting action selection
    │       └── NO → All weapons exhausted → End activation
    └── NO → Continue normally (SHOOT_LEFT > 0):
        └── Continue to shooting action selection step
```

**CHANGEMENT:** Après la mort d'une cible, on met à jour les caches (retirer l'entrée) au lieu de recalculer.

### STEP 7: END_ACTIVATION (MISE À JOUR - Identique à AI_TURN.md, avec ajout de nettoyage de los_cache)

**Purpose**: Nettoyer les données temporaires de l'unité

**Appelé à:**
- Fin de l'activation d'une unité (via `end_activation()` ou `_shooting_activation_end()`)

```javascript
end_activation(...) / _shooting_activation_end(...):
├── Remove unit from shoot_activation_pool
├── If "valid_target_pool" in unit:
│   └── del unit["valid_target_pool"]  // Nettoyer pool
├── If "los_cache" in unit:
│   └── del unit["los_cache"]  // NOUVEAU: Nettoyer cache LoS
├── If "active_shooting_unit" in game_state:
│   └── del game_state["active_shooting_unit"]  // NOUVEAU: Nettoyer unité active
├── Clear TOTAL_ATTACK_LOG
├── Clear selected_target_id
└── SHOOT_LEFT = 0
```

**CHANGEMENT:** 
- Le cache LoS est nettoyé à la fin de l'activation, comme valid_target_pool
- `active_shooting_unit` est nettoyé pour permettre l'activation de la prochaine unité

---

## 📊 RÉSUMÉ DES CHANGEMENTS

### Avant (Architecture actuelle)
- Cache LoS global: `game_state["los_cache"]` avec clés `(shooter_id, target_id)`
- Construit au début de la phase pour toutes les paires
- Invalidé partiellement quand une unité bouge
- Utilisé dans `_is_valid_shooting_target`
- `valid_target_pool_build` calcule LoS directement (pas de cache)

### Après (Nouvelle architecture)
- Cache LoS par unité: `unit["los_cache"]` avec clés `target_id: has_los`
- `position_cache`: snapshot des positions ennemies
- Calculé à l'activation de l'unité
- Recalculé après advance de l'unité
- Mis à jour (retirer entrée) après mort de cible
- Utilisé dans `valid_target_pool_build` et `_is_valid_shooting_target`
- Nettoyé à la fin de l'activation

### Avantages
1. **Performance**: Cache calculé seulement quand nécessaire (activation, advance)
2. **Fiabilité**: Cache toujours à jour (recalculé après advance)
3. **Simplicité**: Pas de cache global partagé à gérer
4. **Efficacité**: Pas de recalcul inutile après mort de cible (juste retirer l'entrée)

---

## 🔄 FLUX D'EXÉCUTION COMPLET (RÉSUMÉ)

```
1. shooting_phase_start()
   └── build_position_cache()  // Construire snapshot positions ennemies

2. UNIT_ACTIVABLE_CHECK
   └── build_unit_los_cache(unit_id)  // Calculer cache LoS pour cette unité
   └── valid_target_pool_build()  // Utilise unit["los_cache"]

3. ACTION_SELECTION
   └── Agent choisit action (ADVANCE ou SHOOT)
   │
   ├── Si ADVANCE choisi:
   │   └── Unit avance
   │   └── build_unit_los_cache(unit_id)  // Recalculer cache avec nouvelle position
   │   └── valid_target_pool_build()  // Reconstruire pool avec nouveau cache
   │   └── Retour à ACTION_SELECTION (peut maintenant tirer)
   │
   └── Si SHOOT choisi:
       └── Agent sélectionne target
       └── Vérifie target_id in valid_target_pool
       └── Execute shoot_action(target)

4. SHOOT ACTION
   └── shooting_attack_controller()
   └── Target meurt?
       └── YES → update_los_cache_after_target_death()  // Retirer de caches
       └── Retirer de valid_target_pool
   └── SHOOT_LEFT > 0? → Retour à ACTION_SELECTION

5. END_ACTIVATION
   └── del unit["valid_target_pool"]
   └── del unit["los_cache"]  // Nettoyer cache
```

---

## ⚠️ POINTS CRITIQUES

1. **position_cache** doit être mis à jour après chaque mort de cible
2. **unit["los_cache"]** doit être recalculé après chaque advance (pas juste invalidé)
3. **unit["los_cache"]** doit être nettoyé à la fin de l'activation
4. Le pool est la source de vérité, mais utilise maintenant le cache LoS pour la performance
5. Pas de recalcul après mort de cible, juste retirer l'entrée du cache

---

## 🔍 CAS LIMITES : POOLS ET CACHES VIDES

### Cas 1 : `los_cache` vide ou inexistant

**Scénarios possibles :**

1. **`los_cache` n'existe pas (clé absente de `unit`) :**
   - **Cause :** `build_unit_los_cache()` n'a pas été appelé
   - **Situation :** 
     - **ERREUR** si `unit.id NOT in units_fled` (doit être créé à l'activation STEP 2)
     - **NORMAL** si `unit.id in units_fled` - on ne construit pas intentionnellement le cache (l'unité ne peut pas tirer, mais peut avancer)
   - **Comportement :** 
     - Si unité normale : `valid_target_pool_build()` doit ASSERT que `unit["los_cache"]` existe
     - Si unité a fui : `valid_target_pool_build()` n'est pas appelé (l'unité ne peut pas tirer)
   - **Action :** 
     - Si unité normale : Corriger le code pour garantir l'appel de `build_unit_los_cache()`
     - Si unité a fui : Aucune - comportement attendu

2. **`los_cache` existe mais est vide `{}` :**
   - **Cause :** `position_cache` est vide (pas d'ennemis sur le terrain)
   - **Situation :** NORMAL - pas d'ennemis, donc pas de LoS à calculer
   - **Comportement :** `valid_target_pool_build()` retourne `[]` (pool vide)
   - **Action :** Aucune - comportement attendu

### Cas 2 : `valid_target_pool` vide

**Scénarios possibles :**

1. **Pool vide après construction (unité n'a pas encore tiré) :**
   - **Causes possibles :**
     - Aucune cible avec LoS (toutes bloquées par des murs)
     - Aucune cible à portée (toutes trop loin)
     - Toutes les cibles sont engagées avec des unités amies (sans PISTOL)
     - Toutes les cibles adjacentes sans arme PISTOL
   - **Situation :** NORMAL - aucune cible valide selon les règles
   - **Comportement :** 
     - Si `CAN_ADVANCE == true` → Go to STEP 3: ACTION_SELECTION (peut avancer)
     - Si `CAN_ADVANCE == false` → Go to STEP 6: EMPTY_TARGET_HANDLING (fin d'activation)
   - **Action :** Aucune - comportement attendu

2. **Pool vide après mort de toutes les cibles (unité a déjà tiré) :**
   - **Cause :** Toutes les cibles dans le pool sont mortes après des tirs
   - **Situation :** NORMAL - toutes les cibles ont été éliminées
   - **Comportement :** Fin d'activation (STEP 7: END_ACTIVATION) - **on ne peut pas avancer après avoir tiré**
   - **Action :** Aucune - comportement attendu

3. **Pool vide après advance :**
   - **Cause :** Après advance, aucune cible n'est valide (nouvelle position, nouvelles contraintes)
   - **Situation :** NORMAL - l'advance peut avoir changé les conditions
   - **Comportement :** 
     - Si `CAN_ADVANCE == true` → Peut encore avancer (si pas déjà avancé)
     - Sinon → Fin d'activation
   - **Action :** Aucune - comportement attendu

### Cas 3 : `position_cache` vide

**Scénario :**
- **Cause :** Aucun ennemi vivant sur le terrain
- **Situation :** RARE mais possible (tous les ennemis sont morts)
- **Comportement :**
  - `build_unit_los_cache()` crée `unit["los_cache"] = {}` (vide)
  - `valid_target_pool_build()` retourne `[]` (pool vide)
  - Toutes les unités peuvent avancer mais pas tirer
- **Action :** Aucune - comportement attendu

### Gestion des erreurs

**Assertions à implémenter :**
```javascript
// Dans valid_target_pool_build()
ASSERT: unit["los_cache"] exists (doit être créé par build_unit_los_cache)
// Si assertion échoue → ERREUR, corriger le code

// Dans build_unit_los_cache()
ASSERT: game_state["position_cache"] exists (doit être créé par build_position_cache)
// Si assertion échoue → ERREUR, corriger le code
```

**Fallback :**
- Si `los_cache` n'existe pas dans `valid_target_pool_build()` : ERREUR (ne pas calculer directement, corriger le code)
- Si `position_cache` n'existe pas dans `build_unit_los_cache()` : ERREUR (ne pas calculer directement, corriger le code)

---

## 🔄 PLAN DE MIGRATION

### Vue d'ensemble

**Ancien système :**
- `game_state["los_cache"]` avec clés `(shooter_id, target_id)`
- Construit au début de phase pour toutes les paires (`_build_shooting_los_cache`)
- Invalidé partiellement quand une unité bouge ou meurt

**Nouveau système :**
- `game_state["position_cache"]` : snapshot des positions ennemies
- `unit["los_cache"]` : cache LoS par unité active avec clés `target_id: has_los`
- Calculé à l'activation de l'unité
- Recalculé après advance

### Fichiers à modifier

#### 1. `engine/phase_handlers/shooting_handlers.py`

**Supprimer :**
- `_build_shooting_los_cache()` (lignes 451-482)
  - **Remplacé par :** `build_position_cache()` dans `shooting_phase_start()`
- `_invalidate_los_cache_for_unit()` (lignes 484-501)
  - **Remplacé par :** `update_los_cache_after_target_death()` qui retire de `position_cache` et `unit["los_cache"]`
- `_rebuild_los_cache_for_unit()` (lignes 542-573)
  - **Remplacé par :** `build_unit_los_cache()` appelé après advance
- `_invalidate_los_cache_for_moved_unit()` (lignes 576-605)
  - **OBSOLÈTE :** Plus besoin d'invalider un cache global, le cache par unité est recalculé après advance

**Modifier :**
- `_has_valid_shooting_targets()` (ligne 701)
  - **PROBLÈME ACTUEL :** Retourne `False` si `unit.id in units_fled` (ligne 723-724)
  - **CORRECTION NÉCESSAIRE :** Doit vérifier `CAN_ADVANCE` pour les unités qui ont fui au lieu de retourner `False`
  - **Changement :** Si `unit.id in units_fled`, vérifier si `CAN_ADVANCE == true` (pas adjacent à un ennemi) et retourner ce résultat

**Modifier :**
- `shooting_phase_start()` (ligne 363)
  - **Supprimer :** `_build_shooting_los_cache(game_state)` (ligne 431)
  - **Ajouter :** `build_position_cache()` (nouvelle fonction)
- `shooting_unit_activation_start()` (ligne 852)
  - **Ajouter :** `build_unit_los_cache(unit_id)` avant `valid_target_pool_build()`
- `_is_valid_shooting_target()` (ligne 776)
  - **Modifier :** Utiliser `shooter["los_cache"][target["id"]]` si disponible, sinon fallback sur calcul direct
  - **Changement :** `cache_key = (shooter["id"], target["id"])` → `target_id = target["id"]` et vérifier dans `shooter["los_cache"]`
- `valid_target_pool_build()` (ligne 981)
  - **Modifier :** Parcourir `unit["los_cache"].keys()` au lieu de `game_state["units"]`
  - **Utiliser :** `unit["los_cache"][target_id]` pour LoS au lieu de `_has_line_of_sight()`
- `_handle_advance_action()` (ligne ~3885)
  - **Supprimer :** `_invalidate_los_cache_for_moved_unit()` et `_rebuild_los_cache_for_unit()`
  - **Ajouter :** `build_unit_los_cache(unit_id)` après mouvement effectif
- `shooting_attack_controller()` (ligne ~3095)
  - **Supprimer :** `_invalidate_los_cache_for_unit()`
  - **Ajouter :** `update_los_cache_after_target_death(target_id)` après mort de cible
- `_shooting_activation_end()` (ligne ~1804)
  - **Ajouter :** Nettoyage de `unit["los_cache"]` si existe

**Ajouter (nouvelles fonctions) :**
- `build_position_cache()` : Construire `game_state["position_cache"]`
- `build_unit_los_cache(unit_id)` : Construire `unit["los_cache"]`
- `update_los_cache_after_target_death(dead_target_id)` : Retirer de `position_cache` et `unit["los_cache"]`

#### 2. `engine/phase_handlers/fight_handlers.py`

**Modifier :**
- `_is_valid_shooting_target()` (ligne 334)
  - **Modifier :** Utiliser `shooter["los_cache"][target["id"]]` si disponible
  - **Changement :** Même logique que dans `shooting_handlers.py`
- **Supprimer :** Import de `_invalidate_los_cache_for_unit` (ligne 19)
  - **Remplacé par :** `update_los_cache_after_target_death()` dans `shooting_handlers.py`
- Ligne 2515 : Appel à `_invalidate_los_cache_for_unit()`
  - **Remplacer par :** `update_los_cache_after_target_death()` si dans la phase de tir

#### 3. `engine/phase_handlers/movement_handlers.py`

**Modifier :**
- Ligne 579-580 : Appel à `_invalidate_los_cache_for_moved_unit()`
  - **SUPPRIMER :** Plus besoin d'invalider, le cache sera recalculé à l'activation suivante

#### 4. `engine/phase_handlers/charge_handlers.py`

**Modifier :**
- Ligne 644-645 : Appel à `_invalidate_los_cache_for_moved_unit()`
  - **SUPPRIMER :** Plus besoin d'invalider, le cache sera recalculé à l'activation suivante

#### 5. `engine/combat_utils.py`

**Modifier :**
- `check_los_cached()` (ligne 212)
  - **PROBLÈME :** Cette fonction utilise `game_state["los_cache"]` avec clés `(shooter_id, target_id)`
  - **SOLUTION :** Vérifier si `shooter["los_cache"]` existe et utiliser `shooter["los_cache"][target["id"]]`
  - **Fallback :** Si pas de cache, calculer directement
  - **NOTE :** Cette fonction est utilisée en dehors de la phase de tir, donc le cache par unité peut ne pas exister

#### 6. `engine/observation_builder.py`

**Modifier :**
- `_check_los_cached()` (ligne 276)
  - **PROBLÈME :** Même problème que `combat_utils.py`
  - **SOLUTION :** Même approche : vérifier `shooter["los_cache"]` si disponible, sinon fallback

#### 7. `engine/w40k_core.py`

**Modifier :**
- Initialisation de `game_state` (ligne 293, 453)
  - **SUPPRIMER :** `"los_cache": {}` (plus de cache global)
  - **AJOUTER :** `"position_cache": {}` (nouveau cache global)
  - **GARDER :** `"hex_los_cache": {}` (utilisé par `combat_utils.py` pour `has_line_of_sight`)

### Ordre d'implémentation recommandé

1. **Étape 1 :** Ajouter les nouvelles fonctions
   - `build_position_cache()`
   - `build_unit_los_cache(unit_id)`
   - `update_los_cache_after_target_death(dead_target_id)`

2. **Étape 2 :** Modifier `shooting_phase_start()`
   - Supprimer `_build_shooting_los_cache()`
   - Ajouter `build_position_cache()`

3. **Étape 3 :** Modifier `shooting_unit_activation_start()`
   - Ajouter `build_unit_los_cache(unit_id)`

4. **Étape 4 :** Modifier `valid_target_pool_build()`
   - Utiliser `unit["los_cache"]` au lieu de calculer LoS

5. **Étape 5 :** Modifier `_is_valid_shooting_target()` dans `shooting_handlers.py` et `fight_handlers.py`
   - Utiliser `shooter["los_cache"]` si disponible

6. **Étape 6 :** Modifier `_handle_advance_action()`
   - Supprimer invalidation/rebuild
   - Ajouter `build_unit_los_cache(unit_id)`

7. **Étape 7 :** Modifier `shooting_attack_controller()`
   - Remplacer `_invalidate_los_cache_for_unit()` par `update_los_cache_after_target_death()`

8. **Étape 8 :** Modifier `_shooting_activation_end()`
   - Ajouter nettoyage de `unit["los_cache"]`

9. **Étape 9 :** Supprimer les fonctions obsolètes
   - `_build_shooting_los_cache()`
   - `_invalidate_los_cache_for_unit()`
   - `_rebuild_los_cache_for_unit()`
   - `_invalidate_los_cache_for_moved_unit()`

10. **Étape 10 :** Modifier les autres fichiers
    - `movement_handlers.py` : Supprimer invalidation
    - `charge_handlers.py` : Supprimer invalidation
    - `combat_utils.py` : Modifier `check_los_cached()`
    - `observation_builder.py` : Modifier `_check_los_cached()`
    - `w40k_core.py` : Modifier initialisation

11. **Étape 11 :** Tests et validation
    - Vérifier que tous les tests passent
    - Vérifier que les performances sont améliorées
    - Vérifier qu'il n'y a pas de régression

### Notes importantes

- **`hex_los_cache` est conservé :** Ce cache est utilisé par `combat_utils.py::has_line_of_sight()` pour optimiser les calculs de LoS au niveau hex. Il n'est pas affecté par cette migration.

- **Fallback nécessaire :** Les fonctions `check_los_cached()` et `_check_los_cached()` doivent gérer le cas où `shooter["los_cache"]` n'existe pas (appels en dehors de la phase de tir).

- **Compatibilité :** Pendant la migration, il peut être nécessaire de maintenir une compatibilité temporaire avec l'ancien système pour éviter les régressions.
