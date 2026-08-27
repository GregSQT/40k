# Debug : Actions manquantes / Coordonnées incorrectes dans step.log

## Problème initial

Le script `check/hidden_action_finder.py` détecte des actions non loguées dans `step.log` :
- **24 mouvements non logués**
- **23 attaques non loguées**

## Découverte critique

Après analyse approfondie, le problème n'est **PAS** que les actions ne sont pas loguées, mais que **les coordonnées sont incorrectes** dans `step.log`.

### Exemple concret : Unit 2 E1 T1

- **`debug.log`** (`[POSITION CHANGE]`) : `(7,14)→(6,11)` ✅ **CORRECT**
- **`step.log`** : `Unit 2(4,11) MOVED from (7,14) to (4,11)` ❌ **INCORRECT** (devrait être `to (6,11)`)

## Constats techniques

### 1. Les logs de debug montrent que les valeurs sont correctes

```
[STEP LOGGER DEBUG] E1 T1 move Unit 2: result.toCol=6 result.toRow=11 updated_unit.col=6 updated_unit.row=11
[STEP LOGGER DEBUG] E1 T1 move Unit 2 BEFORE log_action: end_pos=(6, 11) unit_with_coords=2(6,11)
[STEP LOGGER FORMAT] E1 T1 move Unit 2: start_pos=(7, 14) end_pos=(6, 11) end_col=6 end_row=11
[STEP LOGGER MESSAGE] E1 T1 move Unit 2: from (7,14) to (6,11) ✅ CORRECT
```

**MAIS** `step.log` contient : `from (7,14) to (4,11)` ❌ **INCORRECT**

### 2. Le log `[STEP LOGGER WRITE]` n'est pas écrit pour E1 T1 Unit 2

- Le log `[STEP LOGGER WRITE]` n'est écrit que si `_debug_game_state` est présent dans `action_details` (ligne 77 de `ai/step_logger.py`)
- Pour E1 T1 Unit 2, ce log n'existe pas, ce qui suggère que `_debug_game_state` n'est pas présent au moment de l'écriture
- **MAIS** le log est quand même écrit dans `step.log` avec des coordonnées incorrectes

### 3. Analyse systématique

- **15 mouvements** sont logués avec des coordonnées incorrectes (même unité, même tour, mais coordonnées différentes)
- Le problème est **systématique**, pas isolé
- Réparti sur plusieurs unités et tours

## Code concerné

### Construction de `action_details` (lignes 1108-1115 de `engine/w40k_core.py`)

```python
if str(unit_id) in pre_action_positions and action_type == "move":
    orig_col, orig_row = pre_action_positions[str(unit_id)]
    action_details = {
        ...
        "end_pos": (updated_unit["col"], updated_unit["row"])  # ⚠️ Utilise updated_unit directement
    }
```

### Mise à jour de `action_details` (lignes 1165-1170)

```python
action_details.update({
    "start_pos": start_pos,
    "end_pos": end_pos,  # ✅ Devrait utiliser result.get("toCol") et result.get("toRow")
    "col": dest_col,
    "row": dest_row
})
```

### Formatage du message (`ai/step_logger.py` ligne 183)

```python
base_msg = f"Unit {unit_id}{unit_coords} MOVED from ({start_col},{start_row}) to ({end_col},{end_row})"
```

Les logs de debug montrent que `end_pos=(6,11)` est correct dans `action_details` avant l'appel à `log_action()`, et que `base_msg` est correct dans `[STEP LOGGER MESSAGE]`.

**MAIS** `step.log` contient des coordonnées incorrectes.

## Hypothèses

1. **Le message est modifié après `[STEP LOGGER MESSAGE]`** mais avant l'écriture dans `step.log`
2. **Plusieurs messages sont écrits** pour le même mouvement (un correct, un incorrect)
3. **Un autre code path** écrit dans `step.log` avec des valeurs différentes
4. **Problème de timing** : `updated_unit` est récupéré avant que les coordonnées ne soient mises à jour par le handler de mouvement

## Questions à résoudre

1. Pourquoi `step.log` contient-il `(4,11)` alors que tous les logs de debug montrent `(6,11)` ?
2. Pourquoi le log `[STEP LOGGER WRITE]` n'est-il pas écrit pour E1 T1 Unit 2 ?
3. Y a-t-il plusieurs appels à `log_action()` pour le même mouvement ?
4. Le message est-il modifié entre `[STEP LOGGER MESSAGE]` et l'écriture dans `step.log` ?

## Fichiers à analyser

- `engine/w40k_core.py` : lignes 1104-1170 (construction de `action_details`)
- `ai/step_logger.py` : lignes 75-84 (écriture dans `step.log`)
- `engine/phase_handlers/movement_handlers.py` : lignes 1392-1400 (retour de `result` avec `toCol`/`toRow`)

## Objectif

Trouver la **cause racine** de l'incohérence entre :
- Les valeurs correctes dans les logs de debug
- Les valeurs incorrectes dans `step.log`

Et corriger le code pour que `step.log` contienne les bonnes coordonnées.
