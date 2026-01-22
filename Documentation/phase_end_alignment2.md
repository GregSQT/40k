# Alignement Phase SHOOT sur Phase MOVE - Remplacement complet de `_shooting_activation_end` (VERSION AMÉLIORÉE)

## Objectif

Remplacer complètement `_shooting_activation_end` par `end_activation` (de `generic_handlers.py`) pour aligner la phase SHOOT exactement sur la phase MOVE, résolvant ainsi le bug des épisodes incomplets causé par des boucles infinies de WAIT.

## Root Cause Identifiée

**Problème :** Les épisodes #23 et #25 atteignent 999/996 actions avec 944 WAIT répétés, puis sont tronqués à 1000 actions sans loguer "EPISODE END".

**Cause :** 
- En phase SHOOT, `_shooting_activation_end` retire l'unité du pool mais le résultat n'est pas correctement propagé
- `get_action_mask()` réactive automatiquement l'unité avant que le pool ne soit mis à jour
- L'unité reste dans le pool → boucle infinie de WAIT

**Solution :** Utiliser `end_activation` directement (comme en phase MOVE) pour garantir une gestion cohérente du pool.

## Comparaison MOVE vs SHOOT

### Phase MOVE (Référence - Fonctionne correctement)

1. **Nettoyage AVANT end_activation :**
   ```python
   movement_clear_preview(game_state)  # Efface active_movement_unit, valid_move_destinations_pool
   result = end_activation(game_state, unit, "WAIT", 1, "MOVE", "MOVE", 0)
   ```

2. **end_activation retire du pool :**
   - Dans `generic_handlers.py` ligne 112-113 : retire directement de `move_activation_pool`
   - Vérifie si pool vide (ligne 199-204)
   - Met `phase_complete: True` si pool vide (ligne 265)
   - **IMPORTANT :** `end_activation` retourne SEULEMENT `phase_complete: True`, PAS `next_phase`

3. **Cascade loop gère la transition :**
   - `w40k_core.py` ligne 1595 détecte `phase_complete: True` dans le résultat
   - **MAIS** le cascade loop a besoin de `next_phase` pour savoir quelle phase appeler
   - Le cascade loop appelle automatiquement `movement_phase_end()` qui retourne `{"phase_complete": True, "next_phase": "shoot"}`
   - Puis le cascade loop appelle `shooting_phase_start()` automatiquement

### Phase SHOOT (Avant modification - Bugué)

1. **Nettoyage DANS _shooting_activation_end :**
   - Nettoyage fait APRÈS retrait du pool
   - Logique complexe et non standardisée

2. **Retrait du pool dans _shooting_activation_end :**
   - Logique dupliquée au lieu d'utiliser `end_activation`
   - Risque de désynchronisation

3. **Appel direct à _shooting_phase_complete :**
   - Contourne le cascade loop
   - Incohérent avec MOVE

## Modifications Proposées (VERSION AMÉLIORÉE)

### 1. Créer `shooting_clear_activation_state()`

**Fichier :** `engine/phase_handlers/shooting_handlers.py`

**Position :** Avant `_get_shooting_context()`

```python
def shooting_clear_activation_state(game_state: Dict[str, Any], unit: Dict[str, Any]) -> None:
    """Clear shooting activation state (equivalent to movement_clear_preview in MOVE phase).
    
    This function clears:
    - active_shooting_unit
    - unit's valid_target_pool
    - unit's TOTAL_ATTACK_LOG
    - unit's selected_target_id
    - unit's activation_position
    - unit's _shooting_with_pistol
    - unit's SHOOT_LEFT (reset to 0)
    
    Called BEFORE end_activation to clean up state, exactly like movement_clear_preview in MOVE.
    """
    # Clear active unit
    if "active_shooting_unit" in game_state:
        del game_state["active_shooting_unit"]
    
    # Clear unit activation state
    if "valid_target_pool" in unit:
        del unit["valid_target_pool"]
    if "TOTAL_ATTACK_LOG" in unit:
        del unit["TOTAL_ATTACK_LOG"]
    if "selected_target_id" in unit:
        del unit["selected_target_id"]
    if "activation_position" in unit:
        del unit["activation_position"]
    if "_shooting_with_pistol" in unit:
        del unit["_shooting_with_pistol"]
    unit["SHOOT_LEFT"] = 0
```

### 2. Créer `_handle_shooting_end_activation()` (VERSION CORRIGÉE)

**Fichier :** `engine/phase_handlers/shooting_handlers.py`

**Position :** Avant `_shooting_activation_end()` (qui sera dépréciée)

**CRITIQUE :** Cette version est alignée avec le pattern MOVE et le cascade loop.

```python
def _handle_shooting_end_activation(game_state: Dict[str, Any], unit: Dict[str, Any],
                                     arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1,
                                     action_type: str = None, include_attack_results: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """Handle shooting activation end using end_activation (aligned with MOVE phase).
    
    This function:
    1. Clears activation state BEFORE end_activation (like movement_clear_preview in MOVE)
    2. Calls end_activation (which removes from pool and checks if pool empty)
    3. Returns result with phase_complete if pool is empty (cascade loop handles transition)
    4. Includes attack results if needed
    
    CRITICAL: This function does NOT call shooting_phase_end() directly.
    The cascade loop in w40k_core.py will detect phase_complete: True and call
    shooting_phase_end() automatically, which returns next_phase for the cascade loop.
    
    Args:
        arg1: ACTION/WAIT/PASS - logging behavior
        arg2: 1/0 - step increment
        arg3: SHOOTING/ADVANCE/PASS - tracking sets
        arg4: SHOOTING - pool removal phase
        arg5: 1/0 - error logging (1=remove from pool, 0=NOT_REMOVED)
        action_type: Optional action type for result dict (defaults to inferred from arg1)
        include_attack_results: Whether to include shoot_attack_results in response
    
    Returns:
        Tuple[bool, Dict] - (success, result) where result may contain phase_complete
        If phase_complete: True, cascade loop will call shooting_phase_end() automatically
    """
    from engine.phase_handlers.generic_handlers import end_activation
    
    # CRITICAL: Only clear state if actually ending activation (arg5=1)
    # If arg5=0 (NOT_REMOVED), we continue activation, so keep state intact
    if arg5 == 1:
        shooting_clear_activation_state(game_state, unit)
    
    # Call end_activation (exactly like MOVE phase)
    result = end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)
    
    # Determine action type for result
    if action_type is None:
        if arg1 == "PASS":
            action_type = "skip"
        elif arg1 == "WAIT":
            action_type = "wait"
        elif arg1 == "ACTION":
            if arg3 == "ADVANCE":
                action_type = "advance"
            elif arg3 == "SHOOTING":
                action_type = "shoot"
            else:
                action_type = "shoot"
        else:
            action_type = "shoot"
    
    # Update result with action type and activation_complete (like _handle_skip_action in MOVE)
    result.update({
        "action": action_type,
        "unitId": unit["id"],
        "activation_complete": True
    })
    
    # Include attack results if needed (for cases where attacks were executed before ending)
    if include_attack_results:
        shoot_attack_results = game_state.get("shoot_attack_results", [])
        if shoot_attack_results:
            result["all_attack_results"] = list(shoot_attack_results)
    
    # CRITICAL: If phase_complete: True, we need to provide next_phase for cascade loop
    # BUT we don't call shooting_phase_end() directly - the cascade loop will do it
    # However, end_activation only sets phase_complete: True, not next_phase
    # So we need to merge shooting_phase_end() result here to provide next_phase
    # This is different from MOVE because MOVE's cascade loop calls movement_phase_end() directly
    # For SHOOT, we need to provide next_phase in the result so cascade loop knows what to call
    if result.get("phase_complete"):
        # Merge shooting_phase_end() result to get next_phase
        # This ensures cascade loop has next_phase to work with
        phase_end_result = shooting_phase_end(game_state)
        result.update(phase_end_result)
    
    return True, result
```

**NOTE IMPORTANTE :** La différence avec MOVE est que le cascade loop pour MOVE appelle `movement_phase_end()` directement quand il voit `phase_complete: True`. Pour SHOOT, nous devons fournir `next_phase` dans le résultat pour que le cascade loop sache quelle phase appeler. C'est pourquoi nous fusionnons le résultat de `shooting_phase_end()` ici.

### 3. Remplacer tous les appels à `_shooting_activation_end`

**IMPORTANT :** Vérifier les signatures de retour. Certains appels attendent `Dict`, d'autres `Tuple[bool, Dict]`. Tous les appels à `_handle_shooting_end_activation` retournent `Tuple[bool, Dict]`, donc adapter les appels qui attendent seulement `Dict`.

#### 3.1. WAIT action dans `execute_action`

**Ligne ~2386-2402**

**AVANT :**
```python
elif action_type == "wait" or action_type == "skip":
    has_shot = _unit_has_shot_with_any_weapon(unit)
    unit_id_str = str(unit["id"])
    if has_shot:
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
    else:
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            return _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
        else:
            return _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

**APRÈS :**
```python
elif action_type == "wait" or action_type == "skip":
    has_shot = _unit_has_shot_with_any_weapon(unit)
    unit_id_str = str(unit["id"])
    if has_shot:
        return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
    else:
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
        else:
            return _handle_shooting_end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

#### 3.2. right_click action dans `execute_action`

**Ligne ~2408-2423**

**AVANT :**
```python
elif action_type == "right_click":
    has_shot = _unit_has_shot_with_any_weapon(unit)
    unit_id_str = str(unit["id"])
    if has_shot:
        return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
    else:
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            return _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
        else:
            return _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

**APRÈS :**
```python
elif action_type == "right_click":
    has_shot = _unit_has_shot_with_any_weapon(unit)
    unit_id_str = str(unit["id"])
    if has_shot:
        return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
    else:
        has_advanced = unit_id_str in game_state.get("units_advanced", set())
        if has_advanced:
            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
        else:
            return _handle_shooting_end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

#### 3.3. skip action dans `execute_action`

**Ligne ~2425-2426**

**AVANT :**
```python
elif action_type == "skip":
    return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1)
```

**APRÈS :**
```python
elif action_type == "skip":
    return _handle_shooting_end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1, action_type="skip")
```

#### 3.4. Empty target pool dans `shooting_unit_activation_start`

**Ligne ~947-954**

**AVANT :**
```python
        else:
            # NO -> unit.CAN_ADVANCE = false -> No valid actions available
            unit["valid_target_pool"] = []
            success, result = _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
            return result
```

**APRÈS :**
```python
        else:
            # NO -> unit.CAN_ADVANCE = false -> No valid actions available
            success, result = _handle_shooting_end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
            return result
```

#### 3.5. Weapon exhaustion dans `_shooting_unit_execution_loop`

**Ligne ~2000-2008**

**AVANT :**
```python
                except Exception as e:
                    # If weapon selection fails, end activation
                    return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                
                # Check if at least one weapon is usable (can_use: True)
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                if not usable_weapons:
                    # No usable weapons left, end activation
                    return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
```

**APRÈS :**
```python
                except Exception as e:
                    # If weapon selection fails, end activation
                    return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
                
                # Check if at least one weapon is usable (can_use: True)
                usable_weapons = [w for w in available_weapons if w["can_use"]]
                if not usable_weapons:
                    # No usable weapons left, end activation
                    return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
```

#### 3.6. No more weapons dans `_shooting_unit_execution_loop`

**Ligne ~2022-2027**

**AVANT :**
```python
            else:
                # No more weapons of the same category or no targets, end activation
                return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        else:
            # No weapon selected, end activation
            return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
```

**APRÈS :**
```python
            else:
                # No more weapons of the same category or no targets, end activation
                return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
        else:
            # No weapon selected, end activation
            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
```

#### 3.7. No targets at activation dans `_shooting_unit_execution_loop`

**Ligne ~2083-2103**

**AVANT :**
```python
        if is_pve_ai or is_gym_training or is_bot:
            if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
                # No targets at activation
                return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
            else:
                # Shot last target available
                return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
        
        # For human players: allow advance mode instead of ending activation
        if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
            # No targets at activation - return signal to allow advance mode
            return True, {
                "waiting_for_player": True,
                "unitId": unit_id,
                "no_targets": True,
                "allow_advance": True,
                "context": "no_targets_advance_available"
            }
        else:
            # Shot last target available
            return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
```

**APRÈS :**
```python
        if is_pve_ai or is_gym_training or is_bot:
            if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
                # No targets at activation
                return _handle_shooting_end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1)
            else:
                # Shot last target available
                return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
        
        # For human players: allow advance mode instead of ending activation
        if selected_weapon and unit["SHOOT_LEFT"] == selected_weapon["NB"]:
            # No targets at activation - return signal to allow advance mode
            return True, {
                "waiting_for_player": True,
                "unitId": unit_id,
                "no_targets": True,
                "allow_advance": True,
                "context": "no_targets_advance_available"
            }
        else:
            # Shot last target available
            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
```

#### 3.8. No valid targets after rebuild dans `_shooting_unit_execution_loop`

**Ligne ~2124-2126**

**AVANT :**
```python
        if not valid_targets:
            # No valid targets after rebuild - end activation
            return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
```

**APRÈS :**
```python
        if not valid_targets:
            # No valid targets after rebuild - end activation
            return _handle_shooting_end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1)
```

#### 3.9. No valid targets dans `execute_action` (shoot action)

**Ligne ~2329-2332**

**AVANT :**
```python
            if not valid_targets:
                # No valid targets - end activation with wait
                return _shooting_activation_end(game_state, unit, "PASS", 1, "PASS", "SHOOTING")
```

**APRÈS :**
```python
            if not valid_targets:
                # No valid targets - end activation with wait
                return _handle_shooting_end_activation(game_state, unit, "PASS", 1, "PASS", "SHOOTING", 1)
```

#### 3.10. Cannot advance dans `_handle_advance_action`

**Ligne ~2627-2629**

**AVANT :**
```python
            else:
                # Cannot advance - must WAIT
                return _shooting_activation_end(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

**APRÈS :**
```python
            else:
                # Cannot advance - must WAIT
                return _handle_shooting_end_activation(game_state, unit, "WAIT", 1, "PASS", "SHOOTING", 1)
```

#### 3.11. Weapon selection fails dans `shooting_target_selection_handler`

**Ligne ~2763-2765 et 2779-2781**

**AVANT :**
```python
                        except Exception as e:
                            # If weapon selection fails, end activation
                            return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                        
                        # ... code ...
                            
                            except (KeyError, AttributeError, IndexError) as e:
                                # If weapon selection fails, end activation
                                return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
```

**APRÈS :**
```python
                        except Exception as e:
                            # If weapon selection fails, end activation
                            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
                        
                        # ... code ...
                            
                            except (KeyError, AttributeError, IndexError) as e:
                                # If weapon selection fails, end activation
                                return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
```

#### 3.12. No more weapons of same category dans `shooting_target_selection_handler`

**Ligne ~2793-2795**

**AVANT :**
```python
                        else:
                            # No more weapons of the same category available
                            # End activation since all weapons of this category have been used
                            return _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
```

**APRÈS :**
```python
                        else:
                            # No more weapons of the same category available
                            # End activation since all weapons of this category have been used
                            return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1)
```

#### 3.13. All weapons exhausted dans `shooting_target_selection_handler`

**Ligne ~3005-3012**

**AVANT :**
```python
            else:
                # NO -> All weapons exhausted -> End activation
                success, result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                # CRITICAL: Include all_attack_results even when ending activation
                shoot_attack_results = game_state.get("shoot_attack_results", [])
                if shoot_attack_results:
                    result["all_attack_results"] = list(shoot_attack_results)
                return success, result
```

**APRÈS :**
```python
            else:
                # NO -> All weapons exhausted -> End activation
                return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1, include_attack_results=True)
```

#### 3.14. Target pool empty (Slaughter handling) dans `shooting_target_selection_handler`

**Ligne ~3025-3033**

**AVANT :**
```python
                # valid_target_pool empty? -> YES -> End activation (Slaughter handling)
                if not unit.get("valid_target_pool"):
                    success, result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                    # CRITICAL: Include all_attack_results even when ending activation
                    shoot_attack_results = game_state.get("shoot_attack_results", [])
                    if shoot_attack_results:
                        result["all_attack_results"] = list(shoot_attack_results)
                    return success, result
```

**APRÈS :**
```python
                # valid_target_pool empty? -> YES -> End activation (Slaughter handling)
                if not unit.get("valid_target_pool"):
                    return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1, include_attack_results=True)
```

#### 3.15. Final safety check dans `shooting_target_selection_handler`

**Ligne ~3038-3047**

**AVANT :**
```python
            # Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            valid_targets = unit.get("valid_target_pool", [])
            if not valid_targets and unit["SHOOT_LEFT"] > 0:
                # YES -> End activation (Slaughter handling)
                success, result = _shooting_activation_end(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING")
                # CRITICAL: Include all_attack_results even when ending activation
                shoot_attack_results = game_state.get("shoot_attack_results", [])
                if shoot_attack_results:
                    result["all_attack_results"] = list(shoot_attack_results)
                return success, result
```

**APRÈS :**
```python
            # Final safety check: valid_target_pool empty AND SHOOT_LEFT > 0?
            valid_targets = unit.get("valid_target_pool", [])
            if not valid_targets and unit["SHOOT_LEFT"] > 0:
                # YES -> End activation (Slaughter handling)
                return _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "SHOOTING", "SHOOTING", 1, include_attack_results=True)
```

#### 3.16. NOT_REMOVED case dans `_handle_advance_action` (arg5=0)

**Ligne ~4010-4015**

**AVANT :**
```python
        # Units must be marked as advanced even if they stay in place (for ASSAULT weapon rule)
        # AI_TURN.md ligne 666: Log: end_activation(ACTION, 1, ADVANCE, NOT_REMOVED, 1, 0)
        # This marks units_advanced (ligne 665 describes what this does)
        # arg5=0 means NOT_REMOVED (do not remove from pool, do not end activation)
        # We track the advance but continue to shooting, so we don't use the return value
        _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 0)
```

**APRÈS :**
```python
        # Units must be marked as advanced even if they stay in place (for ASSAULT weapon rule)
        # AI_TURN.md ligne 666: Log: end_activation(ACTION, 1, ADVANCE, SHOOTING, 0)
        # This marks units_advanced (ligne 665 describes what this does)
        # arg5=0 means NOT_REMOVED (do not remove from pool, do not end activation)
        # We track the advance but continue to shooting, so we don't use the return value
        from engine.phase_handlers.generic_handlers import end_activation
        # CRITICAL: arg5=0 means NOT_REMOVED - do NOT clear activation state
        # Call end_activation directly (no wrapper needed for NOT_REMOVED case)
        end_activation(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 0)
```

#### 3.17. No targets after advance dans `_handle_advance_action`

**Ligne ~4092-4105**

**AVANT :**
```python
        else:
            # NO -> Unit advanced but no valid targets -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1, 1)
            # arg3="ADVANCE", arg4="SHOOTING", arg5=1 (remove from pool)
            success, result = _shooting_activation_end(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1)
            result.update({
                "action": "advance",
                "unitId": unit_id,
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_range,
                "actually_moved": actually_moved
            })
            return success, result
```

**APRÈS :**
```python
        else:
            # NO -> Unit advanced but no valid targets -> end_activation(ACTION, 1, ADVANCE, SHOOTING, 1)
            # arg3="ADVANCE", arg4="SHOOTING", arg5=1 (remove from pool)
            success, result = _handle_shooting_end_activation(game_state, unit, "ACTION", 1, "ADVANCE", "SHOOTING", 1, action_type="advance")
            result.update({
                "fromCol": orig_col,
                "fromRow": orig_row,
                "toCol": dest_col,
                "toRow": dest_row,
                "advance_range": advance_range,
                "actually_moved": actually_moved
            })
            return success, result
```

### 4. Déprécier `_shooting_activation_end`

**Fichier :** `engine/phase_handlers/shooting_handlers.py`

**Ligne ~1769-1906**

**AVANT :** Fonction complète avec toute sa logique

**APRÈS :**
```python
# DEPRECATED: _shooting_activation_end is replaced by _handle_shooting_end_activation + end_activation
# This function is kept for reference but should not be used
# All calls have been migrated to use end_activation directly (aligned with MOVE phase)
def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """
    DEPRECATED: Use _handle_shooting_end_activation instead (aligned with MOVE phase).
    
    This function is kept for backward compatibility but should not be used in new code.
    All calls have been migrated to use end_activation directly via _handle_shooting_end_activation.
    """
    # Redirect to new implementation
    return _handle_shooting_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)
```

## Résumé des Changements

### Fonctions Ajoutées

1. **`shooting_clear_activation_state()`** - Nettoie l'état d'activation AVANT `end_activation` (comme `movement_clear_preview` en MOVE)

2. **`_handle_shooting_end_activation()`** - Helper qui encapsule la logique (comme `_handle_skip_action` en MOVE)
   - **AMÉLIORATION :** Fusionne le résultat de `shooting_phase_end()` si `phase_complete: True` pour fournir `next_phase` au cascade loop

### Fonctions Modifiées

- Tous les appels à `_shooting_activation_end` remplacés par `_handle_shooting_end_activation`
- **27 remplacements** au total dans `shooting_handlers.py`
- **IMPORTANT :** Vérifier que tous les appels gèrent correctement le retour `Tuple[bool, Dict]`

### Fonctions Dépréciées

- **`_shooting_activation_end()`** - Conservée pour compatibilité mais redirige vers la nouvelle implémentation

## Bénéfices

1. **Cohérence** : Phase SHOOT alignée exactement sur phase MOVE
2. **Fiabilité** : Utilisation de `end_activation` standardisé (déjà testé en MOVE)
3. **Maintenabilité** : Une seule source de vérité pour la gestion des pools
4. **Bug fix** : Résout le problème des boucles infinies de WAIT et épisodes incomplets
5. **Cascade loop** : Respect du pattern standard avec `phase_complete` et `next_phase`

## Différences Clés avec MOVE

**MOVE :**
- `end_activation` retourne `phase_complete: True`
- Cascade loop appelle `movement_phase_end()` qui retourne `next_phase`
- Cascade loop appelle `shooting_phase_start()` automatiquement

**SHOOT (après modification) :**
- `end_activation` retourne `phase_complete: True`
- `_handle_shooting_end_activation` fusionne `shooting_phase_end()` pour fournir `next_phase` dans le résultat
- Cascade loop voit `phase_complete: True` ET `next_phase` dans le résultat
- Cascade loop appelle `charge_phase_start()` automatiquement

**Pourquoi cette différence ?**
- Le cascade loop a besoin de `next_phase` pour savoir quelle phase appeler
- En MOVE, le cascade loop appelle `movement_phase_end()` directement
- En SHOOT, nous fournissons `next_phase` directement dans le résultat pour éviter un double appel

## Tests à Effectuer

1. Vérifier que les épisodes se terminent correctement (pas de troncature à 1000 actions)
2. Vérifier que "EPISODE END" est logué pour tous les épisodes
3. Vérifier qu'il n'y a plus de boucles infinies de WAIT
4. Vérifier que les transitions de phase fonctionnent correctement
5. Comparer le comportement avec la phase MOVE pour validation
6. **NOUVEAU :** Vérifier que le cascade loop gère correctement `phase_complete` et `next_phase` pour SHOOT

## Notes d'Implémentation

- Le nettoyage se fait **AVANT** `end_activation` (comme MOVE)
- `end_activation` gère le retrait du pool et la vérification du pool vide
- `_handle_shooting_end_activation` fusionne `shooting_phase_end()` si `phase_complete: True` pour fournir `next_phase`
- Le cascade loop dans `w40k_core.py` gère automatiquement les transitions de phase
- Le cas spécial `arg5=0` (NOT_REMOVED) est géré directement avec `end_activation` sans nettoyage ni wrapper

## Points d'Attention

1. **Signatures de retour :** Tous les appels à `_handle_shooting_end_activation` retournent `Tuple[bool, Dict]`. Vérifier que les appels qui attendaient seulement `Dict` sont adaptés.

2. **Cascade loop :** Vérifier que le cascade loop dans `w40k_core.py` ligne 1595 gère bien SHOOT comme MOVE. Le cascade loop doit détecter `phase_complete: True` ET `next_phase` dans le résultat.

3. **Double appel :** S'assurer qu'il n'y a pas de double appel à `shooting_phase_end()` - une fois dans `_handle_shooting_end_activation` et une fois dans le cascade loop.
