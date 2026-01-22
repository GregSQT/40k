# PROMPT: Corrections de la Phase de Tir (Shooting Phase) - Déblocage et Continuité du Tour

## CONTEXTE DU PROBLÈME

Après un refactoring des caches, la phase de tir (`shoot`) ne générait plus de logs dans `step.log` et le tour s'arrêtait prématurément après la phase de tir, empêchant la transition vers la phase de charge (`charge`).

**Commit de référence fonctionnel :** `428051e13255a09ca6033199a2afbcd85099e0d6`

## PROBLÈME 1 : Phase de tir bloquée / pas de logs

### SYMPTÔME
- La phase de tir ne génère plus de logs dans `step.log`
- Les unités ne semblent pas pouvoir tirer
- La phase passe directement à la phase suivante sans exécution

### CAUSE RACINE
Dans `engine/action_decoder.py`, la fonction `_get_eligible_units_for_current_phase()` pour la phase `"shoot"` ne considérait que les unités avec `SHOOT_LEFT > 0`. Cependant, certaines unités peuvent avoir `SHOOT_LEFT == 0` mais être éligibles pour l'action `advance` (avancement). Ces unités "advance-only" étaient exclues du pool d'éligibilité, ce qui pouvait rendre le pool vide prématurément et bloquer la phase.

### SOLUTION IMPLÉMENTÉE

**Fichier :** `engine/action_decoder.py`  
**Fonction :** `_get_eligible_units_for_current_phase()`  
**Lignes :** 158-178

**CODE AVANT (problématique) :**
```python
elif current_phase == "shoot":
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    pool_unit_ids = game_state["shoot_activation_pool"]
    eligible = []
    from shared.data_validation import require_key
    for uid in pool_unit_ids:
        unit = get_unit_by_id(uid, game_state)
        if unit and require_key(unit, "HP_CUR") > 0:
            eligible.append(unit)  # ❌ Inclut toutes les unités vivantes, mais ne vérifie pas SHOOT_LEFT
    return eligible
```

**CODE APRÈS (corrigé) :**
```python
elif current_phase == "shoot":
    # AI_TURN.md COMPLIANCE: Use handler's authoritative activation pool
    if "shoot_activation_pool" not in game_state:
        raise KeyError("game_state missing required 'shoot_activation_pool' field")
    pool_unit_ids = game_state["shoot_activation_pool"]
    # PRINCIPLE: "Le Pool DOIT gérer les morts" - Pool should never contain dead units
    # If a unit dies after pool build, _remove_dead_unit_from_pools should have removed it
    # Defense in depth: filter dead units here as safety check
    # CRITICAL: Include units that can shoot (SHOOT_LEFT>0) OR that can advance (advance-only)
    eligible = []
    from shared.data_validation import require_key
    units_advanced = game_state.get("units_advanced", set())
    for uid in pool_unit_ids:
        unit = get_unit_by_id(uid, game_state)
        if unit and require_key(unit, "HP_CUR") > 0:
            shots_left = unit.get("SHOOT_LEFT", 0)
            can_advance = unit.get("_can_advance", False)
            uid_in_advanced = (unit.get("id") in units_advanced) or (str(unit.get("id")) in units_advanced)
            if shots_left > 0 or (can_advance and not uid_in_advanced):
                eligible.append(unit)
    return eligible
```

**CHANGEMENTS CLÉS :**
1. **Vérification de `SHOOT_LEFT`** : On vérifie maintenant `shots_left = unit.get("SHOOT_LEFT", 0)`
2. **Vérification de `_can_advance`** : On vérifie `can_advance = unit.get("_can_advance", False)`
3. **Vérification de `units_advanced`** : On récupère le set `units_advanced` et on vérifie si l'unité n'y est pas déjà
4. **Condition d'éligibilité élargie** : Une unité est éligible si `shots_left > 0` OU si `(can_advance and not uid_in_advanced)`

**LOGIQUE :**
- Une unité peut tirer si elle a des tirs restants (`SHOOT_LEFT > 0`)
- OU si elle peut avancer (`_can_advance == True`) et n'a pas encore avancé ce tour (`uid not in units_advanced`)

## PROBLÈME 2 : Tour qui s'arrête après la phase de tir

### SYMPTÔME
- Après la phase de tir, le tour s'arrête
- La phase de charge (`charge`) n'est jamais atteinte
- Le jeu semble bloqué ou termine prématurément

### CAUSE RACINE
Dans `engine/phase_handlers/shooting_handlers.py`, la fonction `_shooting_activation_end()` déclenchait une transition de phase (`_shooting_phase_complete()`) même en cas d'erreur (`arg1 == "ERROR"`). Cela causait :
1. Des recalculs coûteux du cache de probabilité de kill (`precompute_kill_probability_cache()`) même en cas d'erreur
2. Des transitions de phase prématurées qui pouvaient corrompre l'état du jeu
3. Des logs manquants car les données d'activation étaient perdues lors de la transition

### SOLUTION IMPLÉMENTÉE

**Fichier :** `engine/phase_handlers/shooting_handlers.py`  
**Fonction :** `_shooting_activation_end()`  
**Lignes :** 1962-1991

**CODE AVANT (problématique) :**
```python
# Signal phase completion if pool is empty - delegate to proper phase end function
if pool_empty:
    # Don't just set a flag - call the complete phase transition function
    return _shooting_phase_complete(game_state)

return response
```

**CODE APRÈS (corrigé) :**
```python
# Signal phase completion if pool is empty - delegate to proper phase end function
# PERFORMANCE: Don't trigger phase transition on ERROR - let normal flow handle it
# ERROR cases should not trigger expensive phase transitions (precompute_kill_probability_cache)
if pool_empty and arg1 != "ERROR":
    # CRITICAL: Preserve action and all_attack_results before merging phase transition
    preserved_action = response.get("action")
    preserved_attack_results = response.get("all_attack_results")
    preserved_unit_id = response.get("unitId")
    
    # Don't just set a flag - call the complete phase transition function
    # But merge activation response info so logs are still generated
    phase_complete_result = _shooting_phase_complete(game_state)
    # Merge activation info into phase complete result so logs include unit activation details
    phase_complete_result.update(response)
    
    # CRITICAL: Restore preserved action for logging, but force "shoot" if attacks were executed
    if preserved_attack_results:
        phase_complete_result["all_attack_results"] = preserved_attack_results
        # CRITICAL: If attacks were executed, action must be "shoot" for logging
        phase_complete_result["action"] = "shoot"
    elif preserved_action is not None:
        phase_complete_result["action"] = preserved_action
    elif "action" not in phase_complete_result:
        phase_complete_result["action"] = "wait"
    if preserved_unit_id:
        phase_complete_result["unitId"] = preserved_unit_id
    
    return phase_complete_result

return response
```

**CHANGEMENTS CLÉS :**
1. **Condition de transition protégée** : `if pool_empty and arg1 != "ERROR"` - Ne déclenche pas la transition si `arg1 == "ERROR"`
2. **Préservation des données d'activation** : Avant d'appeler `_shooting_phase_complete()`, on préserve :
   - `preserved_action
   - `preserved_attack_results` (résultats des attaques pour les logs)
   - `preserved_unit_id` (ID de l'unité pour les logs)
3. **Merge des données** : Après `_shooting_phase_complete()`, on merge les données préservées dans le résultat
4. **Restoration prioritaire** : Si `preserved_attack_results` existe, on force `action = "shoot"` pour les logs

**LOGIQUE :**
- Si le pool est vide ET qu'il n'y a pas d'erreur (`arg1 != "ERROR"`), on déclenche la transition de phase
- Si le pool est vide MAIS qu'il y a une erreur, on retourne simplement `response` sans transition
- Les données d'activation sont préservées et mergées pour garantir que les logs sont générés correctement

## IMPACT DES CORRECTIONS

### AVANT
- Phase de tir bloquée, pas de logs
- Tour qui s'arrête après la phase de tir
- Transitions de phase prématurées en cas d'erreur
- Recalculs coûteux du cache même en cas d'erreur

### APRÈS
- Phase de tir fonctionnelle avec logs complets
- Transition correcte vers la phase de charge
- Pas de transition prématurée en cas d'erreur
- Performance améliorée (pas de recalcul inutile du cache)

## FICHIERS MODIFIÉS

1. **`engine/action_decoder.py`** (lignes 158-178)
   - Modification de `_get_eligible_units_for_current_phase()` pour la phase `"shoot"`
   - Inclusion des unités "advance-only" dans le pool d'éligibilité

2. **`engine/phase_handlers/shooting_handlers.py`** (lignes 1962-1991)
   - Modification de `_shooting_activation_end()` pour éviter les transitions prématurées
   - Préservation et merge des données d'activation pour les logs

## VALIDATION

Pour valider que les corrections fonctionnent :
1. Vérifier que `step.log` contient des entrées pour la phase de tir
2. Vérifier que la phase de charge est atteinte après la phase de tir
3. Vérifier qu'il n'y a pas de transitions prématurées en cas d'erreur
4. Vérifier que les performances sont améliorées (pas de recalcul inutile du cache)

## NOTES TECHNIQUES

- `SHOOT_LEFT` : Nombre de tirs restants pour l'arme sélectionnée de l'unité
- `_can_advance` : Flag indiquant si l'unité peut effectuer une action "Advance"
- `units_advanced` : Set dans `game_state` qui track les unités qui ont déjà avancé ce tour
- `arg1` : Paramètre de `_shooting_activation_end()` qui indique le type de fin d'activation ("ERROR", "PASS", "SKIP", etc.)
- `_shooting_phase_complete()` : Fonction qui gère la fin complète de la phase de tir, incluant la progression du joueur et la transition vers la phase suivante
