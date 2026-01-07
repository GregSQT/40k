# REFONTE DU SYSTÈME DE LOGGING - PLAN DÉTAILLÉ (VERSION AMÉLIORÉE)

**Date**: 2025-01-XX  
**Version**: 1.3 (basé sur refac_log2.md avec améliorations)  
**Objectif**: Centraliser le logging dans un seul point pour éliminer les pertes d'actions

**Améliorations par rapport à refac_log2.md**:
- ✅ Section complète sur le logging des actions échouées
- ✅ Section sur la validation stricte
- ✅ Tests mis à jour pour inclure les actions échouées

---

## 📋 TABLE DES MATIÈRES

1. [Diagnostic des problèmes actuels](#diagnostic)
2. [Architecture proposée](#architecture)
3. [Format de sortie à conserver](#format-output)
4. [Plan de migration étape par étape](#plan-migration)
5. [Code exact à modifier](#code-modifications)
6. [Tests de validation](#tests-validation)
7. [Checklist de validation](#checklist)

---

## 🔍 DIAGNOSTIC DES PROBLÈMES ACTUELS {#diagnostic}

### Problème 1: Logging Fragmenté (3 emplacements)

**Situation actuelle:**
- **Emplacement A**: `w40k_core.py` lignes 1402-1469 - Logging avant transition de phase
- **Emplacement B**: `w40k_core.py` lignes 880-1035 - Logging après action dans `step()`
- **Emplacement C**: Handlers qui accumulent dans `fight_attack_results` (état partagé)

**Conséquence**: Double logging possible OU perte d'attaques si un chemin échoue

### Problème 2: Race Condition avec `fight_attack_results`

**Situation actuelle:**
```python
# Dans fight_handlers.py ligne 1875
game_state["fight_attack_results"] = []  # Vidé après ajout au result
```

**Problème**: Si le logging se fait APRÈS cette ligne, les attaques sont perdues.

**Preuve du problème**: Code de récupération présent (lignes 911-916, 1411-1416) qui indique que des attaques sont PERDUES.

### Problème 3: Flag `combat_already_logged` Fragile

**Situation actuelle:**
- Flag set ligne 1469 dans `_process_semantic_action()`
- Vérifié ligne 882 dans `step()`
- MAIS: Si phase transition modifie `result`, le flag peut être perdu

### Problème 4: Concurrence avec Transitions de Phase

**Situation actuelle:**
- Logging avant transition (ligne 1402) utilise `current_phase` qui peut changer
- Logging après transition (ligne 880) peut avoir phase incorrecte
- Merge de `result` avec phase transition peut écraser données

### Problème 5: Actions Échouées Non Loguées

**Situation actuelle:**
- Ligne 686: `if (self.step_logger and self.step_logger.enabled and success):`
- Cette condition filtre les actions avec `success=False`
- Ligne 642: `episode_steps` n'est incrémenté QUE si `success=True`
- **Conséquence**: Actions échouées ne sont pas loguées

**Impact**: Si `hidden_action_finder.py` détecte des actions échouées exécutées mais non loguées, elles apparaîtront comme "manquantes"

### Problème 6: Validation Trop Permissive

**Situation actuelle:**
- Lignes 707-709: Validation avec whitelist mais skip silencieux si invalide
- Pas de validation stricte des données requises
- Actions peuvent être ignorées silencieusement

**Impact**: Actions valides peuvent être non loguées si validation échoue

---

## 🏗️ ARCHITECTURE PROPOSÉE {#architecture}

### Principe Fondamental

**UN SEUL POINT DE LOGGING**: Dans `step()` de `w40k_core.py`, APRÈS réception du `result` des handlers.

### Flux Simplifié

```
Handler → result (avec all_attack_results complet) → step() → step_logger.log_action()
```

**Avantages:**
- ✅ Point unique de logging
- ✅ Pas de race condition (pas d'état partagé)
- ✅ Flux simple et prévisible
- ✅ Conforme AI_TURN.md

### Responsabilités

#### Handlers (`fight_handlers.py`, etc.)
- **RESPONSABILITÉ**: Retourner `result` avec `all_attack_results` COMPLET
- **INTERDIT**: Faire du logging directement
- **INTERDIT**: Utiliser `fight_attack_results` comme état partagé

#### `w40k_core.py` - `step()`
- **RESPONSABILITÉ UNIQUE**: Logger TOUTES les actions (réussies ET échouées)
- **UN SEUL ENDROIT**: Lignes 880-1035 (section existante)
- **INTERDIT**: Logging dans `_process_semantic_action()`

#### `step_logger.py`
- **AUCUN CHANGEMENT**: Déjà correct et produit le format attendu

---

## 📝 FORMAT DE SORTIE À CONSERVER {#format-output}

### Format Actuel (À CONSERVER)

Le format de `step.log` doit rester **EXACTEMENT** comme actuellement:

```
--- MOVE ---
[19:31:44] T1 P1 MOVE : Unit 1(21,7) MOVED from (18,12) to (21,7) [R:+0.7] [SUCCESS] [STEP: YES]

--- SHOOT ---
[19:31:44] T1 P1 SHOOT : Unit 1(21,7) SHOT at unit 11(17,5) with [Bolt Rifle] - Hit:3+:4(HIT) Wound:3+:3(WOUND) Save:6+:4(FAIL) Dmg:1HP [R:+38.0] [SUCCESS] [STEP: YES]

--- ADVANCE ---
[19:31:44] T1 P1 SHOOT : Unit 2(3,10) ADVANCED from (4,11) to (3,10) [Roll: 4] [R:+0.1] [SUCCESS] [STEP: YES]

--- CHARGE ---
[19:31:44] T1 P1 CHARGE : Unit 1(21,6) CHARGED unit 13(20,6) from (21,7) to (21,6) [Roll:6] [R:+3.0] [SUCCESS] [STEP: YES]

--- FIGHT ---
[19:31:44] T1 P1 FIGHT : Unit 1(21,6) ATTACKED unit 13(20,6) with [Close Combat Weapon] - Hit:3+:1(MISS) [R:+3.0] [SUCCESS] [STEP: YES]
```

### Format Actions Échouées (À AJOUTER)

Pour les actions échouées, le format doit être:

```
--- CHARGE ---
[19:31:44] T1 P1 CHARGE : Unit 1(21,7) FAILED CHARGE unit 13(20,6) from (21,7) to (21,6) [Roll:3] [R:-1.0] [FAILED] [STEP: NO]
```

**Points clés**:
- `[FAILED]` au lieu de `[SUCCESS]`
- `[STEP: NO]` car les actions échouées n'incrémentent pas `episode_steps` (ligne 642)
- Message indique "FAILED CHARGE" avec raison si disponible

### Structure Format

- **En-têtes de section**: `--- ACTION_TYPE ---` (pour MOVE, SHOOT, ADVANCE, CHARGE, FIGHT)
- **Ligne de log**: `[timestamp] T{turn} P{player} {PHASE} : {message} [R:{reward}] [SUCCESS/FAILED] [STEP: YES/NO]`
- **Message détaillé**: Format spécifique selon action (voir `step_logger._format_replay_style_message()`)

### Contraintes

✅ **CONSERVER**:
- Format des timestamps
- Format des sections `--- ACTION_TYPE ---`
- Format des messages détaillés (avec hit_roll, wound_roll, etc.)
- Placement de `[R:reward]`, `[SUCCESS/FAILED]`, `[STEP: YES/NO]`

❌ **NE PAS MODIFIER**:
- L'ordre des champs
- Le formatage des nombres
- Les séparateurs et espaces

### Note Importante

`step_logger.py` génère déjà ce format correctement. La refonte ne doit **PAS** modifier le format, seulement garantir que toutes les actions sont loguées (réussies ET échouées).

---

## 🔄 PLAN DE MIGRATION ÉTAPE PAR ÉTAPE {#plan-migration}

### Phase 1: Nettoyage (SUPPRESSION)

#### Étape 1.1: Supprimer logging dans `_process_semantic_action()`

**Fichier**: `engine/w40k_core.py`  
**Lignes à SUPPRIMER**: 1395-1469

**Code à supprimer:**
```python
# CRITICAL: If fight phase completed with combat action, log it BEFORE phase transition
# This ensures combat actions are logged in the fight phase, not the next phase
if (success and result.get("action") == "combat" and 
    result.get("phase_complete") and result.get("next_phase")):
    # Log combat action before phase transition
    # ... (TOUT LE BLOC 1402-1469)
```

**Raison**: Ce logging est redondant et cause des problèmes de timing. Le logging se fera dans `step()` avec les données correctes du `result`.

#### Étape 1.2: Supprimer flag `combat_already_logged`

**Fichier**: `engine/w40k_core.py`  
**Ligne 882**: Supprimer la vérification `if not result.get("combat_already_logged"):`

**Raison**: Plus nécessaire avec un seul point de logging.

#### Étape 1.3: Nettoyer code de récupération dans `step()`

**Fichier**: `engine/w40k_core.py`  
**Lignes à SUPPRIMER**: 909-933 (code de récupération `fight_attack_results`)

**Raison**: Les handlers doivent retourner `all_attack_results` complet, pas besoin de récupération.

### Phase 2: Garantir `all_attack_results` Complet dans Handlers

#### Étape 2.1: Vérifier que handlers retournent `all_attack_results`

**Fichier**: `engine/phase_handlers/fight_handlers.py`

**Vérifications nécessaires:**
1. Ligne 1858: `result["all_attack_results"] = fight_attack_results` ✅
2. Ligne 1957: `result["all_attack_results"] = fight_attack_results` ✅
3. Ligne 1812: `"all_attack_results": all_attack_results` ✅

**CONFIRMATION**: Les handlers RETOURNENT déjà `all_attack_results`. ✅

#### Étape 2.2: Vérifier copie explicite dans handlers

**Fichier**: `engine/phase_handlers/fight_handlers.py`

**Vérification**: S'assurer que `result["all_attack_results"]` est une COPIE, pas une référence.

**Code actuel:**
```python
result["all_attack_results"] = fight_attack_results
```

**Code recommandé (pour clarté):**
```python
result["all_attack_results"] = list(fight_attack_results)  # Copie explicite
```

**Note**: Python copie déjà lors de l'assignation dans un dict, mais copie explicite = plus clair et plus sûr.

### Phase 3: Simplifier Logging dans `step()`

#### Étape 3.1: Simplifier section combat dans `step()`

**Fichier**: `engine/w40k_core.py`  
**Lignes**: 880-995

**Changements:**
1. Supprimer vérification `combat_already_logged` (ligne 882)
2. Supprimer code de récupération (lignes 909-933)
3. Supprimer DEBUG excessif (garder seulement erreurs critiques)
4. Garder UNIQUEMENT le logging direct avec `all_attack_results`

---

## 📝 CODE EXACT À MODIFIER {#code-modifications}

### Modification 1: Supprimer Logging dans `_process_semantic_action()`

**Fichier**: `engine/w40k_core.py`  
**Lignes**: 1392-1469

**CODE ACTUEL:**
```python
elif current_phase == "fight":
    success, result = self._process_fight_phase(action)
    
    # CRITICAL: If fight phase completed with combat action, log it BEFORE phase transition
    # This ensures combat actions are logged in the fight phase, not the next phase
    if (success and result.get("action") == "combat" and 
        result.get("phase_complete") and result.get("next_phase")):
        # Log combat action before phase transition
        # ... (TOUT LE BLOC DE LOGGING 1402-1469)
```

**CODE MIS À JOUR:**
```python
elif current_phase == "fight":
    success, result = self._process_fight_phase(action)
```

**Raison**: Le logging se fera dans `step()` avec les données correctes du `result`.

### Modification 2: Simplifier Logging Combat dans `step()`

**Fichier**: `engine/w40k_core.py`  
**Lignes**: 880-995

**CODE ACTUEL:**
```python
elif action_type == "combat":
    # Check if combat was already logged before phase transition
    if not result.get("combat_already_logged"):
        # Only log if not already logged in _process_semantic_action before phase transition
        
        # Check if we have multiple attack results from fight phase (CC_NB attacks)
        all_attack_results = result.get("all_attack_results", [])

        # DEBUG: Log all_attack_results received with detailed info
        # ... (DEBUG LINES 889-904)

        # CRITICAL FIX: Handle empty all_attack_results gracefully
        # ... (CODE DE RÉCUPÉRATION 909-933)
        
        # Log EACH attack individually for proper step log output
        step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)

        for i, attack_result in enumerate(all_attack_results):
            # ... (LOGGING CODE 939-994)
```

**CODE MIS À JOUR:**
```python
elif action_type == "combat":
    # Log combat action - handlers MUST return all_attack_results complete
    all_attack_results = result.get("all_attack_results", [])
    
    if not all_attack_results:
        # No attack results - check if waiting for player input
        waiting_for_player = result.get("waiting_for_player", False)
        if waiting_for_player:
            # Waiting for player to select target - no attacks executed yet
            # Skip logging for now, will be logged when target is selected
            pass
        else:
            # This is an error - combat action should have attack results
            raise ValueError(
                f"combat action missing all_attack_results - handlers must return complete data. "
                f"unit_id={unit_id}, result keys={list(result.keys())}"
            )
    else:
        # Log EACH attack individually for proper step log output
        step_reward = self.reward_calculator.calculate_reward(success, result, self.game_state)

        for i, attack_result in enumerate(all_attack_results):
            target_id = attack_result.get("targetId", result.get("targetId"))
            target_unit = self._get_unit_by_id(str(target_id)) if target_id else None
            target_coords = None
            if target_unit:
                target_coords = (target_unit["col"], target_unit["row"])
            
            attack_details = {
                "current_turn": pre_action_turn,
                "unit_with_coords": f"{updated_unit['id']}({updated_unit['col']},{updated_unit['row']})",
                "semantic_action": semantic_action,
                "target_id": target_id,
                "target_coords": target_coords,
                "hit_roll": attack_result.get("hit_roll", 0),
                "wound_roll": attack_result.get("wound_roll", 0),
                "save_roll": attack_result.get("save_roll", 0),
                "damage_dealt": attack_result.get("damage", 0),
                "hit_result": "HIT" if attack_result.get("hit_success") else "MISS",
                "wound_result": "WOUND" if attack_result.get("wound_success") else "FAIL",
                "save_result": "SAVED" if attack_result.get("save_success") else "FAIL",
                "hit_target": attack_result.get("hit_target", 4),
                "wound_target": attack_result.get("wound_target", 4),
                "save_target": attack_result.get("save_target", 4),
                "target_died": attack_result.get("target_died", False),
                "weapon_name": attack_result.get("weapon_name", ""),
                "reward": step_reward if i == 0 else 0.0
            }
            
            self.step_logger.log_action(
                unit_id=updated_unit["id"],
                action_type=action_type,
                phase=pre_action_phase,
                player=pre_action_player,
                success=success,
                step_increment=(i == 0),
                action_details=attack_details
            )
```

**Changements:**
1. ✅ Supprimé vérification `combat_already_logged`
2. ✅ Supprimé code de récupération `fight_attack_results`
3. ✅ Supprimé DEBUG excessif (garder seulement erreurs)
4. ✅ Simplifié logique: si `all_attack_results` vide et pas `waiting_for_player` → erreur
5. ✅ **FORMAT CONSERVÉ**: `step_logger.log_action()` génère déjà le format correct

### Modification 3: Vérifier Copies Explicites dans Handlers (Optionnel mais Recommandé)

**Fichier**: `engine/phase_handlers/fight_handlers.py`

**Lignes**: 1858, 1957, 1812

**CODE ACTUEL:**
```python
result["all_attack_results"] = fight_attack_results
```

**CODE RECOMMANDÉ:**
```python
result["all_attack_results"] = list(fight_attack_results)  # Copie explicite pour sécurité
```

**Note**: Cette modification est optionnelle mais recommandée pour éviter toute référence partagée.

### Modification 4: Logger les Actions Échouées

**Fichier**: `engine/w40k_core.py`  
**Ligne**: 686

**CODE ACTUEL:**
```python
if (self.step_logger and self.step_logger.enabled and success):
```

**PROBLÈME**:
- Cette condition filtre les actions avec `success=False`
- Les actions échouées ne sont pas loguées
- Si `hidden_action_finder.py` détecte des actions échouées exécutées, elles apparaîtront comme "manquantes"

**ANALYSE**:
- Ligne 642: `episode_steps` n'est incrémenté QUE si `success=True`
- Donc: Actions échouées n'incrémentent PAS le step
- **DÉCISION**: Logger les actions échouées avec `step_increment=False` pour visibilité complète

**CODE MIS À JOUR:**
```python
# Logger toutes les actions (réussies ET échouées) pour visibilité complète
# Les actions échouées n'incrémentent pas episode_steps (ligne 642) donc step_increment=False
if (self.step_logger and self.step_logger.enabled):
    # success peut être True ou False - logger dans les deux cas
    # step_increment sera déterminé selon le type d'action et success
```

**IMPLÉMENTATION DÉTAILLÉE**:

Dans la section de logging (après ligne 686), pour chaque type d'action:

```python
if (self.step_logger and self.step_logger.enabled):
    # Déterminer step_increment selon le type d'action et success
    # Pour les actions qui incrémentent episode_steps (ligne 642), step_increment = success
    # Pour les actions qui n'incrémentent pas (ex: multi-attack après la première), step_increment = False
    
    if action_type == "combat":
        # Pour combat, step_increment seulement pour la première attaque ET si success
        step_increment = (i == 0) and success
    else:
        # Pour les autres actions, step_increment = success (cohérent avec ligne 642)
        step_increment = success
    
    # Logger l'action (réussie ou échouée)
    self.step_logger.log_action(
        unit_id=updated_unit["id"],
        action_type=action_type,
        phase=pre_action_phase,
        player=pre_action_player,
        success=success,  # True ou False
        step_increment=step_increment,  # False pour actions échouées
        action_details=action_details
    )
```

**Raison**: 
- Visibilité complète dans les logs (toutes les actions exécutées)
- Cohérent avec `step_logger.py` qui supporte `success=False` et `step_increment=False`
- Permet à `hidden_action_finder.py` de détecter correctement toutes les actions

**⚠️ NOTE IMPORTANTE**:
Cette modification assume que les actions échouées doivent être loguées pour visibilité complète.
Si le comportement actuel (ne pas logger les actions échouées) est intentionnel et cohérent avec votre workflow,
vous pouvez **optionnellement** vérifier avec `hidden_action_finder.py` avant d'appliquer cette modification :

1. **ÉTAPE 1**: Appliquer les Modifications 1-3 uniquement
2. **ÉTAPE 2**: Lancer un training et exécuter `check/hidden_action_finder.py`
3. **ÉTAPE 3**: 
   - Si des actions échouées sont détectées comme "manquantes" → Appliquer Modification 4
   - Si aucune action échouée manquante → Garder comportement actuel (ne pas appliquer Modification 4)

Si vous choisissez de ne pas appliquer cette modification, garder la condition actuelle :
```python
if (self.step_logger and self.step_logger.enabled and success):
    # Actions échouées ne sont pas loguées (comportement actuel conservé)
```

### Modification 5: Validation Stricte

**Fichier**: `engine/w40k_core.py`  
**Lignes**: 707-709

**CODE ACTUEL:**
```python
valid_action_types = ["move", "shoot", "charge", "charge_fail", "combat", "wait", "advance", "flee"]
action_type_valid = action_type in valid_action_types
unit_id_valid = unit_id and unit_id != "none" and unit_id != "SYSTEM"

if (action_type_valid and unit_id_valid):
    # ... logging
```

**PROBLÈME**:
- Skip silencieux si validation échoue
- Pas d'erreur explicite si données invalides
- Actions peuvent être ignorées sans trace

**CODE MIS À JOUR:**
```python
# Validation stricte - pas de fallback, pas de skip silencieux
if not action_type:
    raise ValueError(f"action_type is None or empty - cannot log action. result keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")

valid_action_types = ["move", "shoot", "charge", "charge_fail", "combat", "wait", "advance", "flee"]
if action_type not in valid_action_types:
    raise ValueError(f"Invalid action_type '{action_type}'. Valid types: {valid_action_types}")

if not unit_id:
    raise ValueError(f"unit_id is None or empty - cannot log action. action_type={action_type}")

if unit_id == "none" or unit_id == "SYSTEM":
    raise ValueError(f"Invalid unit_id '{unit_id}' - cannot log system actions. action_type={action_type}")

# Validation passée - procéder au logging
```

**Raison**: 
- Validation stricte évite les actions silencieusement ignorées
- Erreurs explicites facilitent le debugging
- Pas de fallback = pas de comportement imprévisible

**⚠️ NOTE IMPORTANTE**:
Cette validation stricte lève des `ValueError` qui peuvent **interrompre le training** si des données invalides sont détectées.
Si des données invalides sont légitimes dans certains cas (ex: actions système, actions spéciales),
vous devez **adapter la validation** en conséquence pour éviter de casser le système.

**Options d'adaptation**:
1. **Ajouter des exceptions** pour des cas légitimes :
   ```python
   # Exemple: Permettre certaines actions système si nécessaire
   if unit_id == "SYSTEM" and action_type == "system_action":
       # Log action système spéciale
       pass
   else:
       # Validation stricte pour actions normales
       if not unit_id or unit_id == "none":
           raise ValueError(...)
   ```

2. **Logger un warning au lieu de lever une exception** :
   ```python
   if action_type not in valid_action_types:
       import warnings
       warnings.warn(f"Invalid action_type '{action_type}' - skipping logging")
       return  # Skip logging mais ne pas casser le training
   ```

3. **Garder validation permissive** si le comportement actuel est intentionnel :
   ```python
   # Garder le code actuel si skip silencieux est acceptable
   if (action_type_valid and unit_id_valid):
       # ... logging
   ```

**Recommandation**: Tester cette modification sur un training court avant de l'appliquer en production.

---

## ✅ TESTS DE VALIDATION {#tests-validation}

### Test 1: Combat Action Simple (1 attaque)

**Scénario**: Unité attaque une fois en phase fight.

**Vérifications:**
1. ✅ 1 ligne dans `step.log` avec format exact:
   ```
   [timestamp] T{turn} P{player} FIGHT : Unit X(col,row) ATTACKED unit Y(col,row) with [Weapon] - Hit:X+:Y(RESULT) ... [R:reward] [SUCCESS] [STEP: YES]
   ```
2. ✅ Phase = "FIGHT" (pas la phase suivante)
3. ✅ Détails complets (hit_roll, wound_roll, save_roll, damage)
4. ✅ Format identique à l'exemple fourni (lignes 854-867)

### Test 2: Combat Action Multi-Attaque (CC_NB > 1)

**Scénario**: Unité avec CC_NB=3 attaque 3 fois.

**Vérifications:**
1. ✅ 3 lignes dans `step.log` sous section `--- FIGHT ---`
2. ✅ Première ligne: `[STEP: YES]` avec reward non-nul
3. ✅ Lignes 2-3: `[STEP: NO]` avec reward = 0.0
4. ✅ Toutes les attaques loguées, aucune perdue
5. ✅ Format identique pour chaque ligne
6. ✅ Format exact comme exemple dans section "Format Multi-Attack Combat"

### Test 3: Combat avec Phase Transition

**Scénario**: Dernière unité en fight phase complète la phase.

**Vérifications:**
1. ✅ Toutes les attaques loguées AVANT transition
2. ✅ Phase dans log = "FIGHT" (pas "MOVE" suivante)
3. ✅ Pas de double logging
4. ✅ Format correct maintenu

### Test 4: Combat avec `waiting_for_player`

**Scénario**: Combat nécessite sélection manuelle de cible.

**Vérifications:**
1. ✅ Pas de logging si `waiting_for_player=True` et `all_attack_results` vide
2. ✅ Logging quand attaque exécutée après sélection
3. ✅ Format correct quand logging effectué

### Test 5: Comparaison avec `movement_debug.log`

**Scénario**: Lancer `check/hidden_action_finder.py` après training.

**Vérifications:**
1. ✅ `hidden_action_finder_output.txt` montre 0 attaques non loguées
2. ✅ `hidden_action_finder_output.txt` montre 0 mouvements non logués

### Test 6: Format de Sortie Identique

**Scénario**: Comparer `step.log` avant et après refonte.

**Vérifications:**
1. ✅ Format des timestamps identique
2. ✅ Format des sections `--- ACTION_TYPE ---` identique (en-têtes générés automatiquement)
3. ✅ Format des messages détaillés identique
4. ✅ Placement de `[R:reward]`, `[SUCCESS/FAILED]`, `[STEP: YES/NO]` identique
5. ✅ Format multi-attack conforme à l'exemple fourni

### Test 7: Actions Échouées

**Scénario**: Tester une action qui échoue (ex: charge avec roll trop bas).

**Vérifications:**
1. ✅ Action échouée est loguée dans `step.log`
2. ✅ Format: `[FAILED]` présent (pas `[SUCCESS]`)
3. ✅ Format: `[STEP: NO]` présent (actions échouées n'incrémentent pas episode_steps)
4. ✅ Message indique "FAILED CHARGE" ou similaire
5. ✅ `hidden_action_finder.py` ne détecte pas cette action comme "manquante"
6. ✅ Format conforme à l'exemple dans section "Format Actions Échouées"

**Exemple attendu:**
```
--- CHARGE ---
[19:31:44] T1 P1 CHARGE : Unit 1(21,7) FAILED CHARGE unit 13(20,6) from (21,7) to (21,6) [Roll:3] [R:-1.0] [FAILED] [STEP: NO]
```

### Test 8: Validation Stricte

**Scénario**: Tester avec des données invalides.

**Vérifications:**
1. ✅ Si `action_type` est None → ValueError levée (pas de skip silencieux)
2. ✅ Si `action_type` invalide → ValueError levée avec message explicite
3. ✅ Si `unit_id` est None → ValueError levée
4. ✅ Si `unit_id` est "none" ou "SYSTEM" → ValueError levée
5. ✅ Pas d'actions silencieusement ignorées

---

## 📋 CHECKLIST DE VALIDATION {#checklist}

### Avant Modification

- [ ] Backup de `engine/w40k_core.py`
- [ ] Backup de `engine/phase_handlers/fight_handlers.py`
- [ ] Comprendre le flux actuel (lire ce document)
- [ ] Comprendre le format de sortie attendu (lignes 854-867)

### Pendant Modification

- [ ] **Modification 1**: Supprimer lignes 1395-1469 dans `w40k_core.py`
- [ ] **Modification 2**: Simplifier section combat lignes 880-995
- [ ] **Modification 3**: Vérifier/corriger copies dans handlers (optionnel mais recommandé)
- [ ] **Modification 4**: Modifier condition ligne 686 pour logger actions échouées
  - [ ] **Optionnel**: Vérifier avec `hidden_action_finder.py` avant application (voir NOTE IMPORTANTE Modification 4)
- [ ] **Modification 5**: Remplacer validation permissive par validation stricte (lignes 707-709)
  - [ ] **Attention**: Tester sur training court avant production (voir NOTE IMPORTANTE Modification 5)

### Après Modification

- [ ] Tests unitaires passent
- [ ] Training tourne sans erreur
- [ ] `step.log` généré correctement
- [ ] **Format de sortie identique** à l'exemple fourni
- [ ] Actions échouées sont loguées avec `[FAILED]` et `[STEP: NO]`
- [ ] `hidden_action_finder.py` montre 0 problèmes
- [ ] `analyzer.py` analyse `step.log` sans erreur

### Validation Finale

- [ ] Comparer `movement_debug.log` vs `step.log` → 0 différence
- [ ] Vérifier qu'aucune attaque n'est perdue
- [ ] Vérifier qu'aucun mouvement n'est perdu
- [ ] **Vérifier format de sortie ligne par ligne** avec exemple (lignes 854-867)
- [ ] Vérifier format actions échouées conforme à l'exemple
- [ ] Vérifier validation stricte (erreurs explicites, pas de skip silencieux)
- [ ] Documenter résultats dans ce fichier

---

## 🎯 PRINCIPES À RESPECTER

1. **UN SEUL POINT DE LOGGING**: Tout se fait dans `step()` après réception du `result`
2. **HANDLERS RETOURNENT TOUT**: Les handlers doivent retourner `all_attack_results` complet
3. **PAS D'ÉTAT PARTAGÉ**: Ne pas utiliser `fight_attack_results` comme état partagé
4. **SIMPLICITÉ**: Supprimer tout code de récupération/fallback (signe de problème architectural)
5. **FORMAT CONSERVÉ**: Le format de sortie doit rester **EXACTEMENT** identique à l'exemple fourni
6. **LOGGING COMPLET**: Logger toutes les actions (réussies ET échouées) pour visibilité complète
7. **VALIDATION STRICTE**: Pas de fallback, pas de skip silencieux - erreurs explicites

---

## 📚 RÉFÉRENCES

- `AI_TURN.md`: Spécifications du système de tour
- `check/hidden_action_finder.py`: Vérification des actions non loguées
- `ai/analyzer.py`: Analyse de `step.log`
- Format de sortie attendu: Voir exemple lignes 854-867 (terminal selection)

---

## 🔍 NOTES TECHNIQUES

### Pourquoi le format est déjà correct

Le format de sortie est généré par `step_logger._format_replay_style_message()` qui produit déjà le format attendu. La refonte ne modifie **PAS** cette méthode, seulement garantit que toutes les actions sont loguées.

### Points d'attention

- ⚠️ Ne pas modifier `step_logger.py` (format déjà correct)
- ⚠️ S'assurer que `pre_action_phase` est utilisé (pas `current_phase`)
- ⚠️ S'assurer que `pre_action_turn` est utilisé (pas `current_turn`)
- ⚠️ Vérifier que les handlers retournent bien `all_attack_results` complet
- ⚠️ Actions échouées: `step_increment=False` (cohérent avec ligne 642)
- ⚠️ Validation stricte: lever des erreurs explicites, pas de skip silencieux

### Logging des Actions Échouées

**Décision**: Logger toutes les actions (réussies ET échouées) pour visibilité complète.

**Raison**:
- `hidden_action_finder.py` peut détecter des actions échouées exécutées
- Visibilité complète dans les logs de training
- `step_logger.py` supporte déjà `success=False` et `step_increment=False`

**Implémentation**:
- Supprimer `and success` de la condition ligne 686
- Déterminer `step_increment` selon le type d'action et `success`
- Actions échouées: `step_increment=False` (cohérent avec ligne 642)

---

**FIN DU DOCUMENT**

