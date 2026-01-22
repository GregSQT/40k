# Alignement Phase SHOOT sur Phase MOVE - Remplacement complet de `_shooting_activation_end`

## Objectif

Remplacer complètement `_shooting_activation_end` par `end_activation` (de `generic_handlers.py`) pour aligner la phase SHOOT exactement sur la phase MOVE, résolvant ainsi le bug des épisodes incomplets causé par des boucles infinies de WAIT.

## Root Cause Identifiée

**Problème :** Les épisodes #23 et #25 atteignent 999/996 actions avec 944 WAIT répétés, puis sont tronqués à 1000 actions sans loguer "EPISODE END".

**Cause :** 
- En phase SHOOT, `_shooting_activation_end` retire l'unité du pool mais le résultat n'est pas correctement propagé
- `get_action_mask()` réactive automatiquement l'unité avant que le pool ne soit mis à jour (voir `action_decoder.py` lignes 69-82 qui contient un workaround pour ce bug)
- L'unité reste dans le pool → boucle infinie de WAIT

**Solution :** Utiliser `end_activation` directement (comme en phase MOVE) pour garantir une gestion cohérente du pool et laisser le cascade loop gérer les transitions de phase.

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
   - **IMPORTANT :** `end_activation` ne met PAS `next_phase` dans le result

3. **Cascade loop gère la transition :**
   - `w40k_core.py` ligne 1595 détecte `phase_complete: True` ET `next_phase` dans le result
   - Pour MOVE, `_process_movement_phase` (ligne 1674-1679) ajoute manuellement `next_phase: "shoot"` après avoir détecté `phase_complete`
   - Le cascade loop appelle alors automatiquement `shooting_phase_start()`

### Phase SHOOT (Avant modification - Bugué)

1. **Nettoyage DANS _shooting_activation_end :**
   - Nettoyage fait APRÈS retrait du pool (ligne 1837-1863)
   - Logique complexe et non standardisée
   - Duplication de la logique de retrait du pool (ligne 1805-1835)

2. **Retrait du pool dans _shooting_activation_end :**
   - Logique dupliquée au lieu d'utiliser `end_activation`
   - Risque de désynchronisation avec `get_action_mask()`

3. **Appel direct à shooting_phase_end :**
   - Ligne 1904 : appelle directement `shooting_phase_end(game_state)` quand pool vide
   - Contourne le cascade loop
   - Incohérent avec MOVE

## Modifications Proposées

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
    
    CRITICAL: Only called when arg5=1 (actually ending activation).
    If arg5=0 (NOT_REMOVED), state is preserved to continue activation.
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

### 2. Créer `_handle_shooting_end_activation()`

**Fichier :** `engine/phase_handlers/shooting_handlers.py`

**Position :** Avant `_shooting_activation_end()` (qui sera dépréciée)

```python
def _handle_shooting_end_activation(game_state: Dict[str, Any], unit: Dict[str, Any],
                                     arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1,
                                     action_type: str = None, include_attack_results: bool = True) -> Tuple[bool, Dict[str, Any]]:
    """Handle shooting activation end using end_activation (aligned with MOVE phase).
    
    This function:
    1. Clears activation state BEFORE end_activation (like movement_clear_preview in MOVE)
    2. Calls end_activation (which removes from pool and checks if pool empty)
    3. Preserves all_attack_results if needed (for logging before phase transition)
    4. Handles phase_complete by calling shooting_phase_end to get next_phase (like cascade loop pattern)
    
    CRITICAL DIFFERENCE FROM MOVE:
    - MOVE: _process_movement_phase adds next_phase manually after detecting phase_complete
    - SHOOT: We call shooting_phase_end here to get next_phase, then cascade loop handles transition
    - This is necessary because shooting_phase_end also includes all_attack_results and cleanup signals
    
    Args:
        arg1: ACTION/WAIT/PASS - logging behavior
        arg2: 1/0 - step increment
        arg3: SHOOTING/ADVANCE/PASS - tracking sets
        arg4: SHOOTING - pool removal phase
        arg5: 1/0 - error logging (1=remove from pool, 0=NOT_REMOVED)
        action_type: Optional action type for result dict (defaults to inferred from arg1)
        include_attack_results: Whether to include shoot_attack_results in response
    
    Returns:
        Tuple[bool, Dict] - (success, result) where result may contain phase_complete and next_phase
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
    # CRITICAL: This must be done BEFORE phase transition to ensure logging
    if include_attack_results:
        shoot_attack_results = game_state.get("shoot_attack_results", [])
        if shoot_attack_results:
            result["all_attack_results"] = list(shoot_attack_results)
    
    # Check if phase complete (end_activation sets phase_complete: True if pool empty)
    # CRITICAL: end_activation does NOT set next_phase, so we need to call shooting_phase_end
    # to get next_phase and phase transition data (like all_attack_results, cleanup signals)
    # The cascade loop (w40k_core.py:1595) will then handle the actual phase transition
    if result.get("phase_complete"):
        phase_end_result = shooting_phase_end(game_state)
        # Merge phase transition data into result
        # This includes: next_phase, all_attack_results (if not already set), cleanup signals
        result.update(phase_end_result)
        # CRITICAL: cascade loop preserves all_attack_results during transition (w40k_core.py:1623)
        # So we ensure it's in result before cascade loop processes it
    
    return True, result
```

### 3. Remplacer tous les appels à `_shooting_activation_end`

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
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
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
                    # CRITICAL: include_attack_results=True ensures all_attack_results is included
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
                # CRITICAL: include_attack_results=True ensures all_attack_results is included
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
        # CRITICAL: Call end_activation directly (not _handle_shooting_end_activation) because:
        # 1. arg5=0 means NOT_REMOVED - we don't want to clear activation state
        # 2. We don't want to trigger phase_complete check
        # 3. This is just a tracking/logging call, not an actual activation end
        from engine.phase_handlers.generic_handlers import end_activation
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

**AVANT :** Fonction complète avec toute sa logique (137 lignes)

**APRÈS :**
```python
# DEPRECATED: _shooting_activation_end is replaced by _handle_shooting_end_activation + end_activation
# This function is kept for backward compatibility but should not be used in new code
# All calls have been migrated to use end_activation directly (aligned with MOVE phase)
def _shooting_activation_end(game_state: Dict[str, Any], unit: Dict[str, Any], 
                   arg1: str, arg2: int, arg3: str, arg4: str, arg5: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """
    DEPRECATED: Use _handle_shooting_end_activation instead (aligned with MOVE phase).
    
    This function is kept for backward compatibility but should not be used in new code.
    All calls have been migrated to use end_activation directly via _handle_shooting_end_activation.
    
    Migration path:
    - Replace all calls to _shooting_activation_end with _handle_shooting_end_activation
    - For arg5=0 (NOT_REMOVED), call end_activation directly instead
    """
    # Redirect to new implementation
    return _handle_shooting_end_activation(game_state, unit, arg1, arg2, arg3, arg4, arg5)
```

## Résumé des Changements

### Fonctions Ajoutées

1. **`shooting_clear_activation_state()`** - Nettoie l'état d'activation AVANT `end_activation` (comme `movement_clear_preview` en MOVE)
   - Nettoie uniquement si `arg5=1` (activation réellement terminée)
   - Préserve l'état si `arg5=0` (NOT_REMOVED)

2. **`_handle_shooting_end_activation()`** - Helper qui encapsule la logique (comme `_handle_skip_action` en MOVE)
   - Appelle `end_activation` pour retirer du pool et détecter `phase_complete`
   - Appelle `shooting_phase_end` quand `phase_complete=True` pour obtenir `next_phase` et les données de transition
   - Préserve `all_attack_results` pour le logging

### Fonctions Modifiées

- Tous les appels à `_shooting_activation_end` remplacés par `_handle_shooting_end_activation` (sauf cas `arg5=0`)
- **27 remplacements** au total dans `shooting_handlers.py`
- Cas spécial `arg5=0` : appel direct à `end_activation` (pas de nettoyage, pas de phase_complete)

### Fonctions Dépréciées

- **`_shooting_activation_end()`** - Conservée pour compatibilité mais redirige vers la nouvelle implémentation

## Bénéfices

1. **Cohérence** : Phase SHOOT alignée exactement sur phase MOVE
2. **Fiabilité** : Utilisation de `end_activation` standardisé (déjà testé en MOVE)
3. **Maintenabilité** : Une seule source de vérité pour la gestion des pools
4. **Bug fix** : Résout le problème des boucles infinies de WAIT et épisodes incomplets
5. **Cascade loop** : Respecte le pattern cascade loop pour les transitions de phase

## Flux de Transition de Phase

### Avant (Bugué)
```
_shooting_activation_end
  → retire du pool manuellement
  → vérifie pool vide
  → appelle directement shooting_phase_end (contourne cascade loop)
  → get_action_mask réactive l'unité avant mise à jour du pool → BOUCLE INFINIE
```

### Après (Corrigé)
```
_handle_shooting_end_activation
  → shooting_clear_activation_state (nettoyage AVANT)
  → end_activation (retire du pool, vérifie pool vide, met phase_complete)
  → si phase_complete: shooting_phase_end (obtient next_phase et données de transition)
  → retourne result avec phase_complete + next_phase
  → cascade loop (w40k_core.py:1595) détecte phase_complete + next_phase
  → cascade loop appelle shooting_phase_start automatiquement
  → get_action_mask voit pool vide → pas de réactivation → PAS DE BOUCLE
```

## Tests à Effectuer

1. ✅ Vérifier que les épisodes se terminent correctement (pas de troncature à 1000 actions)
2. ✅ Vérifier que "EPISODE END" est logué pour tous les épisodes
3. ✅ Vérifier qu'il n'y a plus de boucles infinies de WAIT
4. ✅ Vérifier que les transitions de phase fonctionnent correctement
5. ✅ Comparer le comportement avec la phase MOVE pour validation
6. ✅ Vérifier que `all_attack_results` est préservé lors des transitions de phase
7. ✅ Vérifier que le cas `arg5=0` (NOT_REMOVED) fonctionne correctement

## Suppression du Workaround dans `action_decoder.py`

**IMPORTANT :** Après avoir implémenté les modifications ci-dessus et vérifié qu'elles fonctionnent correctement, le workaround dans `action_decoder.py` doit être supprimé car il devient obsolète.

### Localisation des Workarounds

**Fichier :** `engine/action_decoder.py`  
**Workaround 1 :** Lignes 69-86 (vérification avant auto-activation)  
**Workaround 2 :** Lignes 90-100 (vérification supplémentaire avant auto-activation)

### Pourquoi le Workaround Peut Être Supprimé

Le workaround a été ajouté pour contourner le bug où `_shooting_activation_end` ne synchronisait pas correctement le pool avec `get_action_mask()`. Après l'implémentation :

1. `end_activation` retire l'unité du pool de manière atomique et cohérente
2. Le pool est mis à jour **AVANT** que `get_action_mask()` ne soit appelé
3. Le cascade loop gère correctement les transitions de phase
4. Il n'y a plus de race condition entre le retrait du pool et la vérification dans `get_action_mask()`

**Le workaround n'est plus nécessaire** car la root cause est corrigée.

### Code à Supprimer

#### Workaround 1 (Lignes 69-86)

**AVANT (avec workaround) :**
```python
                if not active_shooting_unit:
                    # CRITICAL FIX (Episode 11): Verify first unit is still in pool before auto-activation
                    # After WAIT action, _shooting_activation_end removes unit from pool, but eligible_units
                    # may have been computed before pool update, causing infinite WAIT loop
                    shoot_pool = game_state.get("shoot_activation_pool", [])
                    first_unit_id = str(eligible_units[0]["id"])
                    if first_unit_id not in shoot_pool:
                        # Unit not in pool - refresh eligible_units to get accurate state
                        eligible_units = self._get_eligible_units_for_current_phase(game_state)
                        if not eligible_units:
                            # No eligible units - phase should end naturally, skip auto-activation
                            episode = game_state.get("episode_number", "?")
                            turn = game_state.get("turn", "?")
                            from engine.game_utils import add_console_log
                            add_console_log(game_state, f"[AUTO_ACTIVATION DEBUG] E{episode} T{turn} get_action_mask: No eligible units after refresh, skipping auto-activation. Pool={shoot_pool}")
                            pass
                        else:
                            # Use first truly eligible unit
                            first_unit_id = str(eligible_units[0]["id"])
                    
                    # Only auto-activate if we still have eligible units
                    if eligible_units:
                        # CRITICAL DEBUG (Episodes 9,31,56,57,65,94,103,106): Verify unit is still in pool before auto-activation
                        # Use add_console_log instead of add_debug_log to ensure logs are always written
                        shoot_pool_check = game_state.get("shoot_activation_pool", [])
                        first_unit_id_check = str(eligible_units[0]["id"])
                        if first_unit_id_check not in shoot_pool_check:
                            # Unit not in pool - skip auto-activation to prevent infinite loop
                            episode = game_state.get("episode_number", "?")
                            turn = game_state.get("turn", "?")
                            from engine.game_utils import add_console_log
                            add_console_log(game_state, f"[AUTO_ACTIVATION ERROR] E{episode} T{turn} get_action_mask: Unit {first_unit_id_check} NOT in pool after refresh, skipping auto-activation. Pool={shoot_pool_check}, eligible_ids={[str(u['id']) for u in eligible_units]}")
                            eligible_units = []  # Clear eligible_units to skip auto-activation
                    
                    if eligible_units:
```

**APRÈS (sans workarounds) :**
```python
                if not active_shooting_unit:
                    # Only auto-activate if we have eligible units
                    if eligible_units:
```

### Vérification Avant Suppression

**CRITICAL :** Ne supprimer le workaround QUE si tous les tests suivants passent :

1. ✅ Les épisodes se terminent correctement (pas de troncature à 1000 actions)
2. ✅ Aucune boucle infinie de WAIT n'est observée
3. ✅ Les transitions de phase fonctionnent correctement
4. ✅ `get_action_mask()` ne réactive plus d'unités qui ont déjà été retirées du pool
5. ✅ Les logs ne montrent plus de messages `[AUTO_ACTIVATION DEBUG]` ou `[AUTO_ACTIVATION ERROR]` indiquant des unités non trouvées dans le pool

### Ordre d'Implémentation Recommandé

1. **Étape 1 :** Implémenter toutes les modifications de `phase_end_alignment3.md`
2. **Étape 2 :** Exécuter tous les tests de validation
3. **Étape 3 :** Vérifier que le comportement est correct sur plusieurs épisodes
4. **Étape 4 :** Supprimer le workaround dans `action_decoder.py`
5. **Étape 5 :** Re-tester pour confirmer que tout fonctionne sans le workaround

### Note de Migration

Le commentaire `# CRITICAL FIX (Episode 11)` peut être supprimé car le fix est maintenant intégré dans la solution principale via `end_activation`. Le workaround était une solution temporaire qui n'est plus nécessaire.

## Notes d'Implémentation

- Le nettoyage se fait **AVANT** `end_activation` (comme MOVE)
- `end_activation` gère le retrait du pool et la vérification du pool vide
- `end_activation` met `phase_complete: True` mais **ne met PAS** `next_phase`
- `_handle_shooting_end_activation` appelle `shooting_phase_end` pour obtenir `next_phase` quand `phase_complete=True`
- Le cascade loop dans `w40k_core.py` gère automatiquement les transitions de phase (ligne 1595)
- Le cascade loop préserve `all_attack_results` lors des transitions (ligne 1623)
- Le cas spécial `arg5=0` (NOT_REMOVED) est géré directement avec `end_activation` sans nettoyage ni phase_complete

## Différences Subtiles avec MOVE

**MOVE :**
- `_handle_skip_action` ne met pas `next_phase` dans le result
- `_process_movement_phase` (w40k_core.py:1674-1679) ajoute manuellement `next_phase: "shoot"` après avoir détecté `phase_complete`

**SHOOT :**
- `_handle_shooting_end_activation` appelle `shooting_phase_end` pour obtenir `next_phase` quand `phase_complete=True`
- C'est nécessaire car `shooting_phase_end` inclut aussi `all_attack_results` et les signaux de nettoyage frontend
- Le cascade loop gère ensuite la transition automatiquement

Cette différence est acceptable car elle préserve les données nécessaires (`all_attack_results`) avant la transition de phase.
