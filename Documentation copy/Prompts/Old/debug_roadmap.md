# Roadmap : Résolution du bug des coordonnées incorrectes dans step.log

## Statut : 🔍 ANALYSE COMPLÈTE - FIX IDENTIFIÉ

## Problème résumé

Le script `check/hidden_action_finder.py` détecte des actions avec coordonnées incorrectes dans `step.log` :
- **24 mouvements** avec coordonnées incorrectes
- **23 attaques** avec coordonnées incorrectes

**Exemple** : `Unit 2(4,11) MOVED from (7,14) to (4,11)` alors que la destination correcte est `(6,11)`.

## Cause racine identifiée

### Problème principal : `unit_with_coords` non mis à jour

**Localisation** : `engine/w40k_core.py` lignes 1108-1170

**Problème** :
1. Ligne 1111 : `unit_with_coords` est construit avec `updated_unit["col"]` et `updated_unit["row"]` qui peuvent être obsolètes
2. Ligne 1114 : `end_pos` est défini avec `updated_unit["col"]` et `updated_unit["row"]` (valeur incorrecte initiale)
3. Lignes 1158-1164 : `dest_col` et `dest_row` sont calculés correctement depuis `result.get("toCol")` et `result.get("toRow")`
4. Lignes 1165-1170 : `end_pos` est mis à jour correctement avec `(dest_col, dest_row)`
5. **MAIS** : `unit_with_coords` n'est **PAS** mis à jour dans `action_details.update()`

**Impact** : Dans `ai/step_logger.py` ligne 183, le message utilise `unit_coords` (extrait de `unit_with_coords`) qui contient les anciennes coordonnées, créant une incohérence dans le message final.

## Fix validé

### Fix 1 : Mettre à jour `unit_with_coords` dans `action_details.update()`

**Fichier** : `engine/w40k_core.py`  
**Lignes** : 1165-1170

**CODE ACTUEL**
```python
action_details.update({
    "start_pos": start_pos,
    "end_pos": end_pos,
    "col": dest_col,
    "row": dest_row
})
```

**CODE MIS À JOUR**
```python
action_details.update({
    "start_pos": start_pos,
    "end_pos": end_pos,
    "col": dest_col,
    "row": dest_row,
    "unit_with_coords": f"{unit_id}({dest_col},{dest_row})"  # CRITICAL FIX
})
```

**Justification** : `unit_with_coords` doit refléter la position finale de l'unité après le mouvement, calculée depuis `result` (source de vérité).

### Fix 2 (recommandé) : Supprimer la définition initiale incorrecte de `end_pos`

**Fichier** : `engine/w40k_core.py`  
**Lignes** : 1108-1115

**CODE ACTUEL**
```python
action_details = {
    "current_turn": pre_action_turn,
    "current_episode": pre_action_episode,
    "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']},{updated_unit['row']})",
    "action": action,
    "start_pos": (orig_col, orig_row),
    "end_pos": (updated_unit["col"], updated_unit["row"])  # ⚠️ Valeur incorrecte
}
```

**CODE MIS À JOUR**
```python
action_details = {
    "current_turn": pre_action_turn,
    "current_episode": pre_action_episode,
    "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']},{updated_unit['row']})",  # Sera mis à jour plus bas
    "action": action,
    "start_pos": (orig_col, orig_row)
    # end_pos et unit_with_coords seront définis dans action_details.update() avec result
}
```

**Justification** : Évite toute confusion et garantit que `end_pos` n'est défini qu'une seule fois avec les bonnes valeurs depuis `result`.

## Plan d'implémentation

### Phase 1 : Fix minimal (priorité haute)
- [ ] Appliquer Fix 1 : Mettre à jour `unit_with_coords` dans `action_details.update()` (ligne 1169)
- [ ] Tester avec un mouvement simple
- [ ] Vérifier que `step.log` contient les bonnes coordonnées

### Phase 2 : Fix complet (recommandé)
- [ ] Appliquer Fix 2 : Supprimer `end_pos` de la définition initiale (ligne 1114)
- [ ] Tester avec plusieurs mouvements
- [ ] Vérifier que tous les mouvements sont correctement logués

### Phase 3 : Vérification
- [ ] Relancer `check/hidden_action_finder.py`
- [ ] Vérifier que les 24 mouvements et 23 attaques sont maintenant correctement logués
- [ ] Comparer `step.log` avec `debug.log` pour confirmer la cohérence

## Fichiers concernés

- `engine/w40k_core.py` : lignes 1108-1170 (construction et mise à jour de `action_details`)
- `ai/step_logger.py` : lignes 163-183 (extraction de `unit_coords` et formatage du message)
- `engine/phase_handlers/movement_handlers.py` : lignes 1392-1400 (retour de `result` avec `toCol`/`toRow`)

## Notes techniques

### Flux de données
1. Handler de mouvement retourne `result` avec `toCol`/`toRow` (correct)
2. `w40k_core.py` calcule `dest_col`/`dest_row` depuis `result` (correct)
3. `action_details.update()` met à jour `end_pos` avec `(dest_col, dest_row)` (correct)
4. **PROBLÈME** : `unit_with_coords` n'est pas mis à jour, reste avec anciennes valeurs
5. `step_logger.py` extrait `unit_coords` depuis `unit_with_coords` (incorrect)
6. Message final contient `unit_coords` incorrect dans le format `Unit X(coords)`

### Hypothèses invalidées
- ❌ Le message est modifié après `[STEP LOGGER MESSAGE]` → Non, le problème est dans `unit_with_coords`
- ❌ Plusieurs messages écrits → Non, un seul message mais avec `unit_coords` incorrect
- ❌ Autre code path → Non, le problème est dans la construction de `action_details`

### Hypothèses validées
- ✅ Problème de timing : `updated_unit` utilisé avant mise à jour → Partiellement, mais le vrai problème est que `unit_with_coords` n'est pas mis à jour après calcul de `dest_col`/`dest_row`

## Références

- Document d'analyse initial : `Documentation/Prompts/debug_missing_actions_coordinates.md`
- Code source : `engine/w40k_core.py` lignes 1104-1170
- Logger : `ai/step_logger.py` lignes 163-183
