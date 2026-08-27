# Diagnostic : Mouvements logués avec coordonnées incorrectes

## Problème identifié

17 mouvements sont logués dans `step.log`, mais avec des coordonnées de destination incorrectes :

- **Unit 2 E1 T1** : Loguée comme `MOVED from (7,14) to (4,11)` mais devrait être `from (7,14) to (6,11)`
- **Unit 4 E1 T1** : Loguée comme `MOVED from (1,13) to (1,9)` mais devrait être `from (1,13) to (4,9)`
- **Unit 6 E1 T1** : Loguée comme `MOVED from (23,6) to (23,7)` mais devrait être `from (23,6) to (19,6)`
- **Unit 5 E1 T1** : Loguée comme `MOVED from (10,5) to (10,4)` mais devrait être `from (16,5) to (16,4)` (action_type=flee)
- **Unit 7 E1 T1** : Loguée comme `MOVED from (6,8) to (11,5)` mais devrait être `from (6,8) to (6,7)` (action_type=flee)

## Diagnostic technique

### 1. Les mouvements passent bien par le code de logging

Les diagnostics `[ACTION TYPE DIAGNOSTIC]` et `[MOVE LOGGING]` montrent que :
- Les mouvements Unit 2, 4, 6, 8 passent par le code de logging avec `action_type=move` et `waiting_for_player=False`
- Les mouvements Unit 5, 7 passent par le code de logging avec `action_type=flee` et `waiting_for_player=False`
- Tous les mouvements ont `waiting_for_player=False` dans le résultat

### 2. Le code de diagnostic n'est pas exécuté

Le code ligne 1218-1219 dans `engine/w40k_core.py` utilise `add_console_log` pour écrire des messages `[STEP LOGGER DEBUG]` :

```python
debug_msg = f"[STEP LOGGER DEBUG] E{pre_action_episode} T{pre_action_turn} move Unit {unit_id}: result.toCol={result_to_col} result.toRow={result_to_row} updated_unit.col={updated_unit_col} updated_unit.row={updated_unit_row} action.destCol={action_dest_col} action.destRow={action_dest_row}"
add_console_log(self.game_state, debug_msg)
```

**Problème identifié** : `add_console_log` (ligne 57-58 de `engine/game_utils.py`) retourne immédiatement si `gym_training_mode` est True et `debug_mode` est False :

```python
# Skip logging in training mode for performance (unless debug_mode is enabled)
if gym_training_mode and not debug_mode:
    return
```

**Vérification** : Les messages `[STEP LOGGER DEBUG]` n'apparaissent pas dans `debug.log` (0 occurrences), ce qui confirme que le code ligne 1218-1219 n'est pas exécuté car `add_console_log` retourne immédiatement.

### 3. Hypothèse sur la cause racine

Le problème semble venir du fait que `result.get("toCol")` et `result.get("toRow")` ne contiennent pas les bonnes valeurs au moment du logging. Sans les messages de diagnostic, il est impossible de vérifier quelles valeurs sont utilisées.

**Code concerné** (lignes 1221-1227 de `engine/w40k_core.py`) :

```python
if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
    dest_col = result.get("toCol")
    dest_row = result.get("toRow")
else:
    dest_col = action.get("destCol", updated_unit["col"])
    dest_row = action.get("destRow", updated_unit["row"])
end_pos = (dest_col, dest_row)
```

**Hypothèses possibles** :
1. `result.get("toCol")` et `result.get("toRow")` contiennent des valeurs incorrectes (peut-être la position de l'unité après un autre mouvement)
2. Le fallback vers `action.get("destCol")` et `action.get("destRow")` est utilisé, mais ces valeurs sont incorrectes
3. Le fallback vers `updated_unit["col"]` et `updated_unit["row"]` est utilisé, mais l'unité a déjà été déplacée par un autre mouvement

## Recommandation

### Solution immédiate : Activer les diagnostics à plusieurs niveaux

Pour identifier la cause racine, il faut activer les diagnostics à **trois points critiques** :

#### 1. Dans `w40k_core.py` : Logging des valeurs au moment de l'extraction

**Fichier :** `engine/w40k_core.py`

**Modification 1 : Ajouter l'import en haut du fichier (ligne ~23)**

**CODE ACTUEL**
```python
# Import shared utilities FIRST (no circular dependencies)
from engine.game_utils import get_unit_by_id
```

**CODE MIS À JOUR**
```python
# Import shared utilities FIRST (no circular dependencies)
from engine.game_utils import get_unit_by_id, _write_diagnostic_to_debug_log
```

**Modification 2 : Remplacer add_console_log par _write_diagnostic_to_debug_log (lignes 1217-1219)**

**CODE ACTUEL**
```python
                                action_dest_col = action.get("destCol") if isinstance(action, dict) else None
                                action_dest_row = action.get("destRow") if isinstance(action, dict) else None
                                from engine.game_utils import add_console_log
                                debug_msg = f"[STEP LOGGER DEBUG] E{pre_action_episode} T{pre_action_turn} move Unit {unit_id}: result.toCol={result_to_col} result.toRow={result_to_row} updated_unit.col={updated_unit_col} updated_unit.row={updated_unit_row} action.destCol={action_dest_col} action.destRow={action_dest_row}"
                                add_console_log(self.game_state, debug_msg)
                                
                                if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
```

**CODE MIS À JOUR**
```python
                                action_dest_col = action.get("destCol") if isinstance(action, dict) else None
                                action_dest_row = action.get("destRow") if isinstance(action, dict) else None
                                debug_msg = f"[STEP LOGGER DEBUG] E{pre_action_episode} T{pre_action_turn} move Unit {unit_id}: result.toCol={result_to_col} result.toRow={result_to_row} updated_unit.col={updated_unit_col} updated_unit.row={updated_unit_row} action.destCol={action_dest_col} action.destRow={action_dest_row}"
                                _write_diagnostic_to_debug_log(debug_msg)
                                
                                if isinstance(result, dict) and result.get("toCol") is not None and result.get("toRow") is not None:
```

**Explication :** `_write_diagnostic_to_debug_log` écrit directement dans `debug.log` sans dépendre de `debug_mode`, permettant de voir les valeurs utilisées pour `toCol` et `toRow` au moment de l'extraction.

#### 2. Dans `movement_handlers.py` : Logging des valeurs à la source (avant result.update)

**Fichier :** `engine/phase_handlers/movement_handlers.py`

**Modification : Ajouter diagnostic avant result.update (ligne ~1419)**

**CODE ACTUEL**
```python
    if not actually_moved:
        # Unit stayed in same position - treat as wait, not move
        action_name = "wait"
    elif was_adjacent:
        action_name = "flee"
    else:
        action_name = "move"
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "activation_complete": True,
        "waiting_for_player": False  # AI_TURN.md: Movement is complete, no waiting needed
    })
```

**CODE MIS À JOUR**
```python
    if not actually_moved:
        # Unit stayed in same position - treat as wait, not move
        action_name = "wait"
    elif was_adjacent:
        action_name = "flee"
    else:
        action_name = "move"
    
    # DIAGNOSTIC: Log values at source before result.update
    from engine.game_utils import _write_diagnostic_to_debug_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    debug_msg = f"[MOVEMENT HANDLER DEBUG] E{episode} T{turn} Unit {unit['id']}: orig=({orig_col},{orig_row}) dest=({dest_col},{dest_row}) action_name={action_name} action.destCol={action.get('destCol')} action.destRow={action.get('destRow')}"
    _write_diagnostic_to_debug_log(debug_msg)
    
    result.update({
        "action": action_name,
        "unitId": unit["id"],
        "fromCol": orig_col,
        "fromRow": orig_row,
        "toCol": dest_col,
        "toRow": dest_row,
        "activation_complete": True,
        "waiting_for_player": False  # AI_TURN.md: Movement is complete, no waiting needed
    })
```

**Explication :** Ce diagnostic permet de vérifier que les valeurs `dest_col` et `dest_row` sont correctes **avant** qu'elles ne soient ajoutées au `result`. Cela permet de déterminer si le problème vient du handler lui-même ou de l'extraction dans `w40k_core.py`.

#### 3. Dans `movement_destination_selection_handler` : Logging des valeurs d'entrée

**Fichier :** `engine/phase_handlers/movement_handlers.py`

**Modification : Ajouter diagnostic au début du handler (ligne ~1227)**

**CODE ACTUEL**
```python
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    # Use int(float(...)) to match the conversion used in pool construction
    dest_col, dest_row = int(float(dest_col)), int(float(dest_row))
    
    # Pool is already built during activation - no need to rebuild here
```

**CODE MIS À JOUR**
```python
    # CRITICAL: Convert coordinates to int for consistent tuple comparison
    # Use int(float(...)) to match the conversion used in pool construction
    dest_col, dest_row = int(float(dest_col)), int(float(dest_row))
    
    # DIAGNOSTIC: Log input values from action
    from engine.game_utils import _write_diagnostic_to_debug_log
    episode = game_state.get("episode_number", "?")
    turn = game_state.get("turn", "?")
    debug_msg = f"[MOVEMENT HANDLER INPUT] E{episode} T{turn} Unit {unit_id}: action.destCol={action.get('destCol')} action.destRow={action.get('destRow')} converted=({dest_col},{dest_row})"
    _write_diagnostic_to_debug_log(debug_msg)
    
    # Pool is already built during activation - no need to rebuild here
```

**Explication :** Ce diagnostic permet de vérifier que les valeurs d'entrée de l'action sont correctes dès le début du handler, avant toute conversion ou validation.

### Solution à long terme : Corriger la source des coordonnées

Une fois les diagnostics activés et les valeurs vérifiées dans `debug.log`, corriger la source des coordonnées incorrectes selon les résultats :

1. **Si `[MOVEMENT HANDLER INPUT]` montre des valeurs incorrectes** : Le problème vient d'ActionDecoder qui ne fournit pas les bonnes coordonnées dans l'action.

2. **Si `[MOVEMENT HANDLER DEBUG]` montre des valeurs incorrectes** : Le problème vient du calcul de `dest_col`/`dest_row` dans le handler (peut-être une corruption lors de l'exécution du mouvement).

3. **Si `[STEP LOGGER DEBUG]` montre des valeurs incorrectes mais que les handlers sont corrects** : Le problème vient de l'extraction ou du fallback dans `w40k_core.py` (peut-être `updated_unit` est obsolète).

4. **Si le fallback vers `updated_unit["col"]` est utilisé** : Vérifier pourquoi l'unité a déjà été déplacée avant le logging (problème d'ordre d'exécution).

## Fichiers concernés

- `engine/w40k_core.py` : 
  - Ligne ~23 (import de `_write_diagnostic_to_debug_log`)
  - Lignes 1210-1227 (extraction des coordonnées et logging)
- `engine/game_utils.py` : 
  - Lignes 11-26 (fonction `_write_diagnostic_to_debug_log`)
  - Lignes 43-62 (`add_console_log` qui retourne en mode training)
- `engine/phase_handlers/movement_handlers.py` : 
  - Ligne ~1227 (diagnostic d'entrée dans `movement_destination_selection_handler`)
  - Lignes 1420-1429 (retour du résultat avec `toCol`/`toRow` et diagnostic avant `result.update`)

## Prochaines étapes

1. **Appliquer les trois modifications de diagnostic** :
   - Ajouter l'import dans `w40k_core.py` (ligne ~23)
   - Remplacer `add_console_log` par `_write_diagnostic_to_debug_log` dans `w40k_core.py` (lignes 1217-1219)
   - Ajouter le diagnostic dans `movement_destination_selection_handler` (ligne ~1227)
   - Ajouter le diagnostic avant `result.update` dans le handler de mouvement (ligne ~1419)

2. **Relancer un training** pour générer des logs avec les diagnostics activés

3. **Analyser `debug.log`** en cherchant les trois types de messages :
   - `[MOVEMENT HANDLER INPUT]` : Valeurs d'entrée de l'action
   - `[MOVEMENT HANDLER DEBUG]` : Valeurs avant `result.update`
   - `[STEP LOGGER DEBUG]` : Valeurs au moment de l'extraction dans `w40k_core.py`

4. **Identifier la source des coordonnées incorrectes** en comparant les trois niveaux de diagnostic :
   - Si `[MOVEMENT HANDLER INPUT]` est incorrect → Problème dans ActionDecoder
   - Si `[MOVEMENT HANDLER DEBUG]` est incorrect → Problème dans le calcul du handler
   - Si `[STEP LOGGER DEBUG]` est incorrect mais les handlers sont corrects → Problème dans l'extraction/fallback

5. **Corriger la source du problème** selon l'identification effectuée à l'étape 4
