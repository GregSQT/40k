# AUDIT ET PLAN D'IMPLÉMENTATION : COMMAND PHASE

## OBJECTIF

Ajouter une nouvelle phase **command phase** qui se déroule **avant** la phase de mouvement. Cette phase gère tous les aspects administratifs non liés au mouvement (reset des marks, clear des caches, etc.).

**IMPORTANT :** L'architecture actuelle est conservée. Le changement de joueur/tour reste géré dans `fight_handlers`. La command phase est une phase à part entière qui transitionne automatiquement vers la phase move.

## FLUX ACTUEL vs FLUX SOUHAITÉ

### FLUX ACTUEL
```
P0: Move → Shoot → Charge → Fight
P1: Move → Shoot → Charge → Fight
→ P0: Move → (tour incrémenté)
```

### FLUX SOUHAITÉ
```
P0: Command → Move → Shoot → Charge → Fight
P1: Command → Move → Shoot → Charge → Fight
→ P0: Command → (tour incrémenté)
```

### RÈGLES DE TRANSITION

1. **Fin de la phase Fight de P0** → `fight_handlers` change `current_player = 1`, retourne `next_phase="command"`, le cascade loop appelle `command_phase_start()`
2. **Fin de la phase Fight de P1** → `fight_handlers` change `current_player = 0`, incrémente `turn`, retourne `next_phase="command"`, le cascade loop appelle `command_phase_start()`
3. **Command Phase** → Auto-avance vers phase Move (pas de changement de joueur/tour)

**PRINCIPE CLÉ :** Le changement de joueur/tour reste dans `fight_handlers` (architecture conservée). La command phase fait uniquement la maintenance (resets) puis transitionne vers move.

---

## AUDIT COMPLET : FEATURES À DÉPLACER

### 1. RESET DES TRACKING SETS

**Emplacement actuel :** `engine/phase_handlers/movement_handlers.py` - fonction `movement_phase_start()` (lignes 22-29)

**Code actuel :**
```python
game_state["units_moved"] = set()
game_state["units_fled"] = set()
game_state["units_shot"] = set()
game_state["units_charged"] = set()
game_state["units_fought"] = set()
game_state["units_attacked"] = set()
game_state["units_advanced"] = set()
```

**Action :** Déplacer dans `command_phase_start()`

**Fichiers impactés :**
- `engine/phase_handlers/movement_handlers.py` (supprimer les resets)
- Nouveau : `engine/phase_handlers/command_handlers.py` (ajouter les resets)

---

### 2. CLEAR DES POOLS DE PRÉVISUALISATION

**Emplacement actuel :** `engine/phase_handlers/movement_handlers.py` - fonction `movement_phase_start()` (lignes 31-34)

**Code actuel :**
```python
game_state["valid_move_destinations_pool"] = []
game_state["preview_hexes"] = []
game_state["active_movement_unit"] = None
```

**Action :** Déplacer dans `command_phase_start()`

**Fichiers impactés :**
- `engine/phase_handlers/movement_handlers.py` (supprimer les clears)
- Nouveau : `engine/phase_handlers/command_handlers.py` (ajouter les clears)

---

### 3. CLEAR DU CACHE ENEMY_REACHABLE_CACHE

**Emplacement actuel :** `engine/phase_handlers/movement_handlers.py` - fonction `movement_phase_start()` (ligne 38)

**Code actuel :**
```python
game_state["enemy_reachable_cache"] = {}
```

**Action :** Déplacer dans `command_phase_start()`

**Fichiers impactés :**
- `engine/phase_handlers/movement_handlers.py` (supprimer)
- Nouveau : `engine/phase_handlers/command_handlers.py` (ajouter)

---

### 4. CHANGEMENT DE JOUEUR/TOUR

**IMPORTANT :** Le changement de joueur/tour **RESTE** dans `fight_handlers`. Seule la transition de phase change.

**Emplacement actuel :** `engine/phase_handlers/fight_handlers.py` - fonction `_fight_phase_complete()` (lignes 781-804, 820-843)

**Code actuel P0 → P1 :**
```python
if game_state["current_player"] == 0:
    game_state["current_player"] = 1
    game_state["phase"] = "move"
    movement_handlers.movement_phase_start(game_state)  # ← Appel direct (sera supprimé)
    return {
        "next_phase": "move",
        ...
    }
```

**Code actuel P1 → P0 :**
```python
elif game_state["current_player"] == 1:
    game_state["turn"] += 1
    game_state["current_player"] = 0
    game_state["phase"] = "move"
    movement_handlers.movement_phase_start(game_state)  # ← Appel direct (sera supprimé)
    return {
        "next_phase": "move",
        ...
    }
```

**Action :** 
- Changer `"move"` → `"command"` dans `game_state["phase"]`
- **SUPPRIMER** l'appel direct à `movement_handlers.movement_phase_start(game_state)` (ne pas le remplacer)
- Changer `"next_phase": "move"` → `"next_phase": "command"` dans le return
- Le cascade loop dans `w40k_core.py` appellera automatiquement `command_phase_start()` quand il verra `next_phase="command"`

**Le changement de joueur/tour reste dans fight_handlers (pas de changement d'architecture).**

**Fichiers impactés :**
- `engine/phase_handlers/fight_handlers.py` (modifier seulement la transition de phase)

---

## DÉCISIONS DE CONCEPTION

### 1. Auto-Advance

**Décision :** La command phase **auto-avance** directement vers move. `command_phase_start()` fait les resets puis appelle `command_phase_end()` qui retourne `phase_complete=True, next_phase="move"`.

**Pattern CRITICAL :** `command_phase_end()` doit retourner SEULEMENT le dict `{"phase_complete": True, "next_phase": "move"}`, et **NE DOIT PAS** appeler `movement_phase_start()` directement. Le cascade loop dans `w40k_core.py` (lignes 1212-1237) gère automatiquement la transition en appelant `movement_phase_start()` quand il reçoit `next_phase="move"`.

**Rationale :** Phase administrative sans actions utilisateur pour l'instant (structure prête pour actions futures). Ce pattern est cohérent avec toutes les autres phases (move, shoot, charge, fight).

### 2. Activation Pool

**Décision :** Pool vide par défaut (`command_activation_pool = []`), mais structure prête pour actions futures d'unité dans la command phase.

**Rationale :** Permet d'ajouter des actions d'unité plus tard sans refactoriser la structure.

### 3. Pattern de Phase

**Décision :** La command phase suit le pattern standard des autres phases :
- `command_phase_start()` : Initialise, fait les resets, transitionne vers move
- `command_phase_end()` : Transition vers move
- `execute_action()` : Structure prête (vide pour l'instant)

### 4. Pattern de Transition (CRITICAL)

**IMPORTANT :** Toutes les transitions de phase suivent le **Pattern Standard** pour cohérence :

**Pattern Standard (toutes les phases) :**
- `phase_end()` ou `_fight_phase_complete()` retourne SEULEMENT le dict : `{"phase_complete": True, "next_phase": "..."}`
- Le cascade loop dans `w40k_core.py` (lignes 1212-1237) gère la transition en appelant automatiquement `next_phase_start()`
- **AUCUN appel direct** à `*_phase_start()` dans les handlers de phase

**Pour _fight_phase_complete() :**
- `_fight_phase_complete()` change le joueur/tour (lignes 783, 822)
- **NE DOIT PAS** appeler `command_phase_start()` directement
- Retourne SEULEMENT `next_phase: "command"` (au lieu de "move")
- Le cascade loop gère l'appel à `command_phase_start()` automatiquement

**Pour command_phase_end() :**
- `command_phase_end()` suit le **Pattern Standard** : retourne SEULEMENT `{"phase_complete": True, "next_phase": "move"}`
- **NE DOIT PAS** appeler `movement_phase_start()` directement
- Le cascade loop gère la transition vers move en appelant `movement_phase_start()` automatiquement

**Résumé du flux (corrigé) :**
```
_fight_phase_complete() 
  → change joueur/tour
  → retourne {"next_phase": "command"} (PAS d'appel direct)
  → cascade loop voit next_phase="command"
  → cascade loop appelle command_phase_start()
  → command_phase_start() fait resets
  → command_phase_start() appelle command_phase_end()
  → command_phase_end() retourne {"next_phase": "move"}
  → cascade loop voit next_phase="move"
  → cascade loop appelle movement_phase_start()
```

**Note :** Ce pattern est plus propre et évite les doubles appels. Le code actuel fait un double appel à `movement_phase_start()` (une fois dans `_fight_phase_complete()` et une fois dans le cascade loop), mais cela fonctionne car les opérations sont idempotentes. Pour la command phase, on adopte le pattern propre dès le départ.

---

## FICHIERS À MODIFIER

### BACKEND (Python)

#### 1. Nouveau fichier : `engine/phase_handlers/command_handlers.py`
- Créer le module de gestion de la phase de commandement
- Fonctions nécessaires :
  - `command_phase_start(game_state)` : Fait tous les resets/maintenance, puis transitionne vers move (auto-advance)
  - `command_phase_end(game_state)` : Transition vers la phase Move
  - `command_build_activation_pool(game_state)` : Build pool vide (structure prête pour futur)
  - `execute_action(game_state, unit, action, config)` : Structure prête (vide pour l'instant)

#### 2. `engine/action_decoder.py`
- Ligne 12 : Ajouter `"command"` dans `GAME_PHASES`
- Dans `get_action_mask()` : Ajouter le cas `current_phase == "command"` (enable WAIT action 11)
- Dans `_get_eligible_units_for_current_phase()` : Ajouter le cas "command" (retourner liste vide)

#### 3. `engine/w40k_core.py`
- Ligne 246 (dans `__init__()`) : Initialiser avec `"phase": "command"` et `"command_activation_pool": []`
  - **Note :** `__init__()` initialise seulement l'état. L'initialisation complète avec les handlers est faite dans `reset()`
- Ligne 397 (dans `reset()`) : Initialiser avec `"phase": "command"` et `"command_activation_pool": []`
- **CRITICAL :** Dans `reset()`, appeler `command_handlers.command_phase_start()` pour faire les resets, puis appeler directement `movement_handlers.movement_phase_start()` pour initialiser la phase move (car reset() n'est pas dans le cascade loop)
- Lignes 1186-1189 : Ajouter la transition `"fight" → "command"` et `"command" → "move"`
- Lignes 1220-1230 : Ajouter l'appel à `command_handlers.command_phase_start()` dans la cascade loop
- Lignes 1197-1206 : Ajouter `elif current_phase == "command"` dans le routing
- Créer `_process_command_phase()` similaire aux autres méthodes _process_*

#### 4. `engine/phase_handlers/movement_handlers.py`
- Lignes 22-29 : **SUPPRIMER** les resets des tracking sets
- Lignes 31-34 : **SUPPRIMER** les clears des pools de prévisualisation
- Ligne 38 : **SUPPRIMER** le clear du cache
- Garder uniquement : set phase, build activation pool, console log

#### 5. `engine/phase_handlers/fight_handlers.py`
- Lignes 783-784 : Modifier transition P0 → P1 : `"move"` → `"command"` dans `game_state["phase"]`
- Ligne 791 : **SUPPRIMER** l'appel direct à `movement_handlers.movement_phase_start(game_state)`
- Ligne 796 : Modifier `"next_phase": "move"` → `"next_phase": "command"`
- Lignes 823-824 : Modifier transition P1 → P0 : `"move"` → `"command"` dans `game_state["phase"]`
- Ligne 830 : **SUPPRIMER** l'appel direct à `movement_handlers.movement_phase_start(game_state)`
- Ligne 835 : Modifier `"next_phase": "move"` → `"next_phase": "command"`
- **GARDER** le changement de joueur/tour (lignes 783, 822) et la vérification max_turns (lignes 806-819) - pas de changement d'architecture
- **IMPORTANT :** Ne PAS appeler `command_phase_start()` directement - le cascade loop gère l'appel

#### 6. `engine/phase_handlers/generic_handlers.py`
- Lignes 188-203 : Dans `end_activation()`, ajouter le cas `"command"` pour vérifier si le pool est vide
- Ajouter :
  ```python
  elif current_phase == "command":
      if "command_activation_pool" not in game_state:
          pool_empty = True
      else:
          pool_empty = len(game_state["command_activation_pool"]) == 0
  ```

#### 7. `engine/pve_controller.py`
- Lignes 128-142 : Dans `make_ai_decision()`, ajouter le cas `"command"` pour gérer la phase command
- Ajouter :
  ```python
  elif current_phase == "command":
      # Command phase: empty pool for now, ready for future
      eligible_pool = game_state.get("command_activation_pool", [])
  ```

#### 8. `engine/reward_calculator.py` (À VÉRIFIER)
- Lignes 327-328 : Dans `calculate_reward()`, la condition `if current_phase == "move"` détermine le type de WAIT reward
  - **Comportement :** Si WAIT est fait en phase command (peu probable car auto-advance), il sera traité comme `"shoot_wait"` (else branch)
  - **Impact :** Probablement OK car la phase command auto-avance immédiatement, donc WAIT ne devrait jamais être fait en phase command
  - **Action :** Aucune modification nécessaire pour l'instant, mais à documenter dans le code
- Lignes 1065-1071 : Vérifier si des conditions `phase == "move"` ou autres nécessitent d'inclure `"command"`
- Probablement pas nécessaire si la command phase auto-avance immédiatement
- À vérifier après implémentation de base

#### 9. `engine/observation_builder.py` (À VÉRIFIER)
- **Ligne 643 : CRITICAL** - Encodage one-hot de la phase - **NÉCESSITE MODIFICATION**
  - Code actuel : `{"move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}[game_state["phase"]]`
  - Modifier en :
    ```python
    phase_encoding = {"command": 0.0, "move": 0.25, "shoot": 0.5, "charge": 0.75, "fight": 1.0}
    obs[1] = phase_encoding.get(game_state["phase"], 0.0)  # Fallback à 0.0 si phase inconnue
    ```
  - **Rationale :** Utiliser `.get()` avec fallback évite les KeyError si une phase inconnue est rencontrée (rétrocompatibilité, bugs futurs)
- Lignes 310-316, 800-810, 1081-1088, 1340-1387 : Vérifier les conditions de phase
- Si des conditions `if phase == "move"` existent, vérifier si elles doivent aussi gérer "command" (probablement non si command auto-advance)

---

### FRONTEND (TypeScript/React)

#### 10. `frontend/src/types/game.ts`
- Ligne 5 : Modifier `GamePhase` type pour inclure `"command"`
```typescript
export type GamePhase = "command" | "move" | "shoot" | "charge" | "fight";
```

#### 11. `frontend/src/components/TurnPhaseTracker.tsx`
- Pas de modification nécessaire (gère dynamiquement le tableau `phases`)

#### 12. `frontend/src/components/BoardWithAPI.tsx`
- Ligne 370 : Modifier le tableau phases
```typescript
phases={["command", "move", "shoot", "charge", "fight"]}
```

#### 13. `frontend/src/components/BoardReplay.tsx`
- Ligne 860 : Modifier le tableau phases
```typescript
phases={["command", "move", "shoot", "charge", "fight"]}
```

#### 14. `frontend/src/components/GameController.tsx`
- Ligne 250 : Modifier le tableau phases
```typescript
phases={["command", "move", "shoot", "charge", "fight"]}
```

#### 15. `frontend/src/hooks/useEngineAPI.ts`
- Dans `getEligibleUnitIds()` : Ajouter le cas `"command"` (retourner liste vide)

#### 16. `frontend/src/hooks/usePhaseTransition.ts`
- **IMPORTANT :** Ce hook est utilisé UNIQUEMENT dans `GameController.tsx` (mode local). Les modes API (BoardWithAPI, BoardReplay) gèrent les transitions côté backend.
- Modifier le switch pour gérer "command" :
  - Ajouter `case "command": actions.setPhase("move"); break;`
  - Modifier `case "fight":` pour transitionner vers `"command"` au lieu de `"move"`
  - Retirer l'incrément de tour (fait par le backend dans fight_handlers)

#### 17. `frontend/src/hooks/useGameState.ts`
- Ligne 53 : Initialiser avec `phase: "command"` au lieu de `phase: "move"`

#### 18. `frontend/src/utils/replayParser.ts`
- Vérifier si des modifications sont nécessaires pour parser la phase "command" dans les replays (probablement pas nécessaire immédiatement)

---

## ORDRE D'IMPLÉMENTATION RECOMMANDÉ

**IMPORTANT :** Suivre cet ordre pour éviter les erreurs de dépendances et les erreurs de compilation.

### PHASE 1 : Backend Core (Fondations)

1. **Créer `engine/phase_handlers/command_handlers.py`**
   - Implémenter toutes les fonctions (command_phase_start, command_phase_end, command_build_activation_pool, execute_action)
   - Ne pas encore appeler depuis d'autres fichiers
   - Tester unitairement si possible

2. **Modifier `engine/action_decoder.py`**
   - Ajouter "command" dans GAME_PHASES
   - Ajouter le cas "command" dans get_action_mask()
   - Ajouter le cas "command" dans _get_eligible_units_for_current_phase()
   - **Test :** Vérifier que le code compile

3. **Modifier `engine/w40k_core.py` - Initialisation**
   - Ligne 246 (__init__) : Initialiser phase="command" et command_activation_pool=[]
     - **Note :** `__init__()` initialise seulement l'état. L'initialisation complète est faite dans `reset()`
   - Ligne 397 (reset) : Initialiser phase="command", command_activation_pool=[], appeler command_phase_start() puis movement_phase_start()
   - **Test :** Vérifier que le code compile

### PHASE 2 : Backend Transitions

4. **Modifier `engine/w40k_core.py` - Routing et cascade loop**
   - Ajouter "command" dans les transitions (lignes 1186-1189)
   - Ajouter "command" dans le cascade loop (lignes 1220-1230)
   - Ajouter le routing "command" (lignes 1197-1206)
   - Créer _process_command_phase()
   - **Test :** Vérifier que le code compile

5. **Modifier `engine/phase_handlers/fight_handlers.py`**
   - Changer "move" → "command" dans game_state["phase"] (lignes 784, 824)
   - **SUPPRIMER** les appels directs à movement_phase_start() (lignes 791, 830)
   - Changer "next_phase": "move" → "next_phase": "command" (lignes 796, 835)
   - **Test :** Vérifier que le code compile et que le cascade loop appelle command_phase_start()

6. **Modifier `engine/phase_handlers/movement_handlers.py`**
   - Supprimer les resets (lignes 22-29)
   - Supprimer les clears (lignes 31-34, 38)
   - **Test :** Vérifier que le code compile et que movement_phase_start() fonctionne toujours

### PHASE 3 : Backend Support

7. **Modifier `engine/phase_handlers/generic_handlers.py`**
   - Ajouter le cas "command" dans end_activation()
   - **Test :** Vérifier que le code compile

8. **Modifier `engine/pve_controller.py`**
   - Ajouter le cas "command" dans make_ai_decision()
   - **Test :** Vérifier que le code compile

9. **Vérifier `engine/observation_builder.py`**
   - Ligne 643 : Modifier l'encodage one-hot pour inclure "command" avec gestion d'erreur (utiliser `.get()` avec fallback)
   - Vérifier autres conditions de phase si nécessaire
   - **Test :** Vérifier que les observations fonctionnent et que le fallback fonctionne pour les phases inconnues

10. **Vérifier `engine/reward_calculator.py`**
    - Vérifier si des modifications sont nécessaires (probablement non)
    - **Test :** Vérifier que les récompenses fonctionnent

### PHASE 4 : Frontend Types et State

11. **Modifier `frontend/src/types/game.ts`**
    - Ajouter "command" dans GamePhase
    - **Test :** Vérifier que TypeScript compile

12. **Modifier `frontend/src/hooks/useGameState.ts`**
    - Initialiser phase="command"
    - **Test :** Vérifier que le code compile

### PHASE 5 : Frontend Components

13. **Modifier `frontend/src/components/BoardWithAPI.tsx`**
    - Ajouter "command" dans phases array
    - **Test :** Vérifier que le composant s'affiche

14. **Modifier `frontend/src/components/BoardReplay.tsx`**
    - Ajouter "command" dans phases array
    - **Test :** Vérifier que le composant s'affiche

15. **Modifier `frontend/src/components/GameController.tsx`**
    - Ajouter "command" dans phases array
    - **Test :** Vérifier que le composant s'affiche

### PHASE 6 : Frontend Logic

16. **Modifier `frontend/src/hooks/usePhaseTransition.ts`**
    - Ajouter case "command" → "move"
    - Modifier case "fight" → "command"
    - **Test :** Vérifier que les transitions fonctionnent

17. **Modifier `frontend/src/hooks/useEngineAPI.ts`**
    - Ajouter le cas "command" dans getEligibleUnitIds()
    - **Test :** Vérifier que le code compile

18. **Vérifier `frontend/src/utils/replayParser.ts`**
    - Vérifier si des modifications sont nécessaires
    - **Test :** Vérifier que les replays fonctionnent

### PHASE 7 : Tests et Validation

19. **Tests Backend**
    - Test transition P0 Fight → P1 Command → P1 Move
    - Test transition P1 Fight → P0 Command (tour incrémenté) → P0 Move
    - Test initialisation dans reset() : Vérifier que command_phase_start() fait les resets, puis movement_phase_start() initialise correctement la phase move
    - Test que tous les resets fonctionnent correctement dans command_phase_start()
    - Test que le cascade loop gère correctement la transition command → move
    - Test que __init__() initialise seulement l'état (pas d'appel aux handlers)

20. **Tests Frontend**
    - Test affichage dans TurnPhaseTracker
    - Test transitions de phase
    - Test que le bouton command phase s'affiche

21. **Tests Intégration**
    - Test complet d'un tour (P0 Command → Move → Shoot → Charge → Fight → P1 Command)
    - Test replay avec nouvelle phase
    - Test PvE avec command phase

---

## PLAN D'IMPLÉMENTATION DÉTAILLÉ

### ÉTAPE 1 : CRÉER LE MODULE COMMAND_HANDLERS (Backend)

**Fichier :** `engine/phase_handlers/command_handlers.py`

**Fonctions à implémenter :**

1. **`command_phase_start(game_state)`**
   - Set `phase = "command"`
   - Reset tous les tracking sets (units_moved, units_fled, etc.)
   - Clear tous les pools de prévisualisation (valid_move_destinations_pool, preview_hexes, etc.)
   - Clear le cache `enemy_reachable_cache`
   - Build activation pool (vide pour l'instant)
   - Console log "COMMAND PHASE START"
   - **Auto-advance :** Appeler `command_phase_end()` et retourner le résultat

2. **`command_build_activation_pool(game_state)`**
   - Initialiser `command_activation_pool = []` (vide pour l'instant, structure prête pour futur)

3. **`command_phase_end(game_state)`**
   - Console log "COMMAND PHASE COMPLETE"
   - **CRITICAL :** Retourner SEULEMENT le dict `{"phase_complete": True, "next_phase": "move", "phase_transition": True}`
   - **NE PAS** appeler `movement_phase_start()` directement - le cascade loop dans `w40k_core.py` gère la transition

4. **`execute_action(game_state, unit, action, config)`**
   - Structure prête pour actions futures (vide pour l'instant)
   - Pour l'instant, retourner `command_phase_end()`

---

### ÉTAPE 2 : MODIFIER ACTION_DECODER (Backend)

**Fichier :** `engine/action_decoder.py`

- Ligne 12 : `GAME_PHASES = ["command", "move", "shoot", "charge", "fight"]`
- Dans `get_action_mask()`, ajouter :
  ```python
  elif current_phase == "command":
      # Command phase: auto-advances, but enable WAIT for consistency
      mask[11] = True  # WAIT action
      return mask
  ```
- Dans `_get_eligible_units_for_current_phase()`, ajouter :
  ```python
  elif phase == "command":
      return []  # Empty pool for now, ready for future
  ```

---

### ÉTAPE 3 : MODIFIER W40K_CORE (Backend)

**Fichier :** `engine/w40k_core.py`

1. **Ligne 246 (dans `__init__()`)** : Initialiser avec `"phase": "command"` et `"command_activation_pool": []`
   - **Note :** `__init__()` initialise seulement l'état du game_state. L'initialisation complète avec les handlers est faite dans `reset()`. C'est normal car `reset()` est toujours appelé après `__init__()` dans le workflow standard.

2. **Ligne 397 (dans `reset()`)** : 
   - Initialiser avec `"phase": "command"` et `"command_activation_pool": []`
   - **CRITICAL :** `reset()` n'est pas dans le cascade loop, donc il faut gérer l'initialisation différemment :
     ```python
     # Appeler command_phase_start() pour faire les resets (ignore le résultat car pas dans cascade loop)
     from engine.phase_handlers import command_handlers
     command_handlers.command_phase_start(self.game_state)  # Fait les resets
     
     # Puis initialiser directement la phase move (reset() n'est pas dans le cascade loop)
     from engine.phase_handlers import movement_handlers
     movement_handlers.movement_phase_start(self.game_state)  # Initialise la phase move
     ```
   - **Rationale :** `command_phase_start()` fait auto-advance et retourne `next_phase="move"`, mais `reset()` n'est pas dans le cascade loop qui gère normalement cette transition. Donc on appelle directement `movement_phase_start()` pour initialiser la phase move, comme c'était fait avant avec seulement `movement_phase_start()`.

3. **Lignes 1186-1189** : Modifier la logique de transition
   ```python
   elif from_phase == "fight":
       result["next_phase"] = "command"  # Au lieu de "move"
   ```
   Et ajouter :
   ```python
   elif from_phase == "command":
       result["next_phase"] = "move"
   ```

4. **Lignes 1220-1230** : Ajouter dans la cascade loop
   ```python
   elif next_phase == "command":
       phase_init_result = command_handlers.command_phase_start(self.game_state)
   ```

5. **Lignes 1197-1206** : Ajouter le routing
   ```python
   elif current_phase == "command":
       success, result = self._process_command_phase(action)
   ```

6. **Créer `_process_command_phase()`** (similaire aux autres méthodes _process_*)
   ```python
   def _process_command_phase(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
       """Process command phase actions."""
       unit_id = action.get("unitId")
       current_unit = None
       if unit_id:
           current_unit = self._get_unit_by_id(unit_id)
       
       from engine.phase_handlers import command_handlers
       success, result = command_handlers.execute_action(self.game_state, current_unit, action, self.config)
       return success, result
   ```

---

### ÉTAPE 4 : MODIFIER GENERIC_HANDLERS (Backend)

**Fichier :** `engine/phase_handlers/generic_handlers.py`

Dans `end_activation()`, lignes 188-203, ajouter le cas "command" :
```python
elif current_phase == "command":
    if "command_activation_pool" not in game_state:
        pool_empty = True
    else:
        pool_empty = len(game_state["command_activation_pool"]) == 0
```

---

### ÉTAPE 5 : MODIFIER PVE_CONTROLLER (Backend)

**Fichier :** `engine/pve_controller.py`

Dans `make_ai_decision()`, lignes 128-142, ajouter le cas "command" :
```python
elif current_phase == "command":
    # Command phase: empty pool for now, ready for future
    if "command_activation_pool" not in game_state:
        eligible_pool = []
    else:
        eligible_pool = game_state["command_activation_pool"]
    print(f"🔍 [AI_DECISION] Command phase detected, pool: {eligible_pool}")
```

---

### ÉTAPE 6 : NETTOYER MOVEMENT_HANDLERS (Backend)

**Fichier :** `engine/phase_handlers/movement_handlers.py`

- **SUPPRIMER** lignes 22-29 (resets des tracking sets)
- **SUPPRIMER** lignes 31-34 (clear des pools)
- **SUPPRIMER** ligne 38 (clear du cache)
- Garder uniquement : set phase, build activation pool, console log

---

### ÉTAPE 7 : MODIFIER FIGHT_HANDLERS (Backend)

**Fichier :** `engine/phase_handlers/fight_handlers.py`

**Modifications pour P0 → P1 (lignes 781-803) :**
- **Ligne 784** : `"move"` → `"command"` dans `game_state["phase"]`
- **Ligne 791** : **SUPPRIMER** l'appel `movement_handlers.movement_phase_start(game_state)` (ne pas le remplacer)
- **Ligne 796** : `"next_phase": "move"` → `"next_phase": "command"`

**Modifications pour P1 → P0 (lignes 820-843) :**
- **Ligne 824** : `"move"` → `"command"` dans `game_state["phase"]`
- **Ligne 830** : **SUPPRIMER** l'appel `movement_handlers.movement_phase_start(game_state)` (ne pas le remplacer)
- **Ligne 835** : `"next_phase": "move"` → `"next_phase": "command"`

**GARDER :**
- Le changement de joueur/tour (lignes 783, 822) - pas de changement
- La vérification max_turns (lignes 806-819) - pas de changement

**IMPORTANT :** Ne PAS appeler `command_phase_start()` directement dans `_fight_phase_complete()`. Le cascade loop dans `w40k_core.py` gère l'appel automatiquement quand il voit `next_phase="command"`.

---

### ÉTAPE 8 : MODIFIER LES TYPES FRONTEND

**Fichier :** `frontend/src/types/game.ts`

- Ligne 5 : `export type GamePhase = "command" | "move" | "shoot" | "charge" | "fight";`

---

### ÉTAPE 9 : METTRE À JOUR LES TABLEAUX PHASES (Frontend)

1. **`frontend/src/components/BoardWithAPI.tsx`** ligne 370
2. **`frontend/src/components/BoardReplay.tsx`** ligne 860
3. **`frontend/src/components/GameController.tsx`** ligne 250

Changer : `phases={["move", "shoot", "charge", "fight"]}`
En : `phases={["command", "move", "shoot", "charge", "fight"]}`

---

### ÉTAPE 10 : MODIFIER USEPHASETRANSITION (Frontend)

**Fichier :** `frontend/src/hooks/usePhaseTransition.ts`

Modifier le switch pour gérer "command" :
```typescript
switch (gameState.phase) {
  case "command":
    actions.setPhase("move");
    break;
  case "move":
    actions.setPhase("shoot");
    break;
  case "shoot":
    actions.setPhase("charge");
    break;
  case "charge":
    actions.setPhase("fight");
    break;
  case "fight": {
    // End turn - transition to command phase (not move)
    const newPlayer = gameState.currentPlayer === 0 ? 1 : 0;
    actions.setCurrentPlayer(newPlayer);
    actions.setPhase("command");  // Au lieu de "move"
    // Note: Turn increment is handled by backend in fight_handlers
    break;
  }
}
```

---

### ÉTAPE 11 : MODIFIER USEENGINEAPI (Frontend)

**Fichier :** `frontend/src/hooks/useEngineAPI.ts`

Dans `getEligibleUnitIds()`, ajouter :
```typescript
if (gameState.phase === "command") {
  // Command phase: empty pool for now, ready for future
  return [];
}
```

---

### ÉTAPE 12 : MODIFIER USEGAMESTATE (Frontend)

**Fichier :** `frontend/src/hooks/useGameState.ts`

- Ligne 53 : Initialiser avec `phase: "command"` au lieu de `phase: "move"`

---

### ÉTAPE 13 : TESTS ET VALIDATION

1. **Test backend :** Vérifier que la phase command s'exécute correctement
2. **Test frontend :** Vérifier l'affichage dans TurnPhaseTracker
3. **Test transition :** Vérifier P0 Fight → P1 Command → P1 Move
4. **Test tour :** Vérifier P1 Fight → P0 Command (tour incrémenté) → P0 Move
5. **Test replay :** Vérifier que les replays fonctionnent avec la nouvelle phase

---

## POINTS D'ATTENTION

1. **Architecture conservée :** Le changement de joueur/tour reste dans `fight_handlers` (pas de changement d'architecture)
2. **Auto-advance :** La command phase transitionne automatiquement vers move (pas d'action utilisateur pour l'instant)
3. **Pool vide :** Structure prête pour actions futures d'unité dans la command phase
4. **Initialisation :** Le jeu commence maintenant en phase "command" au tour 1
5. **CRITICAL - reset() :** Doit appeler `command_phase_start()` pour faire les resets, puis appeler directement `movement_phase_start()` pour initialiser la phase move (car reset() n'est pas dans le cascade loop qui gère normalement la transition)
6. **CRITICAL - __init__() vs reset() :** `__init__()` initialise seulement l'état (`phase="command"`, `command_activation_pool=[]`). `reset()` fait l'initialisation complète avec les appels aux handlers. C'est normal car `reset()` est toujours appelé après `__init__()` dans le workflow standard.
7. **Pattern auto-advance :** `command_phase_end()` retourne SEULEMENT le dict, ne doit PAS appeler `movement_phase_start()` directement - le cascade loop gère la transition
8. **Fichiers critiques :** `generic_handlers.py` et `pve_controller.py` doivent gérer le cas "command" pour éviter les erreurs
9. **observation_builder.py :** Utiliser `.get()` avec fallback pour l'encodage one-hot de la phase (évite KeyError pour phases inconnues)
10. **reward_calculator.py :** WAIT en phase command (peu probable) sera traité comme "shoot_wait" - OK car phase auto-advance
11. **usePhaseTransition.ts :** Hook utilisé UNIQUEMENT dans mode local (GameController). Modes API gèrent transitions côté backend.
12. **Rétrocompatibilité replays :** Les anciens replays n'auront pas la phase "command" → À gérer si nécessaire

---

## RÉSUMÉ DES MODIFICATIONS

- **1 nouveau fichier** : `engine/phase_handlers/command_handlers.py`
- **~7 fichiers backend** à modifier (w40k_core, action_decoder, movement_handlers, fight_handlers, generic_handlers, pve_controller)
- **~7 fichiers frontend** à modifier
- **~15-18 points de modification** au total

**Complexité estimée :** Moyenne (architecture conservée, modifications ciblées)

**Risques :** 
- Bugs dans les transitions de phase
- Régressions dans le système de tracking (mitigé par tests)
- Problèmes de rétrocompatibilité replays (mineur)

**Recommandation :** Implémentation par étapes, tests après chaque étape majeure.
