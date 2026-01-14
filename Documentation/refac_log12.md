# REFONTE DU SYSTÈME DE LOGGING - PLAN DÉTAILLÉ VERSION AMÉLIORÉE

**Date**: 2025-01-21  
**Version**: 1.2 (Amélioration de refac_log2.md avec éléments de refac_log3.md)  
**Objectif**: Centraliser le logging dans un seul point pour éliminer les pertes d'actions

**Base**: `refac_log2.md`  
**Améliorations**: Éléments pertinents de `refac_log3.md`

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

### Problème 5: Actions Échouées Potentiellement Non Loguées (DE REFAC_LOG3.MD)

**Localisation**: `engine/w40k_core.py:686`

**Situation actuelle:**
```python
if (self.step_logger and self.step_logger.enabled and success):
```

**Problème identifié dans refac_log3.md:**
- Si `success=False`, aucune action n'est loguée dans `step.log`
- Selon `step_logger.py` ligne 36: `"STEP INCREMENT ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)"`
- `step_logger.py` supporte le logging des actions échouées
- **MAIS**: Ligne 642 montre que `episode_steps` n'est incrémenté QUE si `success=True`

**Analyse**:
- Actions échouées n'incrémentent PAS le step (ligne 642)
- Si pas d'incrément de step, cohérent de ne pas logger? (comportement actuel ligne 686)
- **À VÉRIFIER**: Est-ce que `hidden_action_finder.py` détecte des actions échouées manquantes?

**Impact**: Potentiellement des actions échouées invisibles dans les logs de training

### Problème 6: Incohérence Turn Number (DE REFAC_LOG3.MD)

**Situation actuelle:**
- `step_logger.py:71`: `turn_number = action_details.get('current_turn', 1)`
- `w40k_core.py:725`: utilise `pre_action_turn`

**Problème**: Deux sources de vérité différentes pour le turn

**Solution**: Utiliser UNIQUEMENT `pre_action_turn` capturé AVANT action (déjà fait dans refac_log2.md)

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
- ✅ Conserve `step_logger.py` existant qui fonctionne déjà

### Responsabilités

#### Handlers (`fight_handlers.py`, etc.)
- **RESPONSABILITÉ**: Retourner `result` avec `all_attack_results` COMPLET
- **INTERDIT**: Faire du logging directement
- **INTERDIT**: Utiliser `fight_attack_results` comme état partagé

#### `w40k_core.py` - `step()`
- **RESPONSABILITÉ UNIQUE**: Logger TOUTES les actions
- **UN SEUL ENDROIT**: Lignes 880-1035 (section existante)
- **INTERDIT**: Logging dans `_process_semantic_action()`
- **SOURCE DE VÉRITÉ UNIQUE**: `pre_action_turn`, `pre_action_phase`, `pre_action_player` capturés AVANT action

#### `step_logger.py`
- **AUCUN CHANGEMENT**: Déjà correct et produit le format attendu
- **VALIDATION INTERNE**: `step_logger` valide déjà les données requises (lignes 216-237)

---

## 📝 FORMAT DE SORTIE À CONSERVER {#format-output}

### Format Actuel (À CONSERVER EXACTEMENT)

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

### Structure Format

- **En-têtes de section**: `--- ACTION_TYPE ---` (pour MOVE, SHOOT, ADVANCE, CHARGE, FIGHT)
- **Ligne de log**: `[timestamp] T{turn} P{player} {PHASE} : {message} [R:{reward}] [SUCCESS/FAILED] [STEP: YES/NO]`
- **Message détaillé**: Format spécifique selon action (voir `step_logger._format_replay_style_message()`)

### Contraintes

✅ **CONSERVER**:
- Format des timestamps `[HH:MM:SS]`
- Format des sections `--- ACTION_TYPE ---`
- Format des messages détaillés (avec hit_roll, wound_roll, etc.)
- Placement de `[R:{reward:+.1f}]`, `[SUCCESS/FAILED]`, `[STEP: YES/NO]`
- Ordre exact des champs

❌ **NE PAS MODIFIER**:
- L'ordre des champs
- Le formatage des nombres
- Les séparateurs et espaces
- `step_logger.py` (génère déjà le bon format)

### En-têtes de Section `--- ACTION_TYPE ---`

**IMPORTANT**: Ces en-têtes sont générés automatiquement par `step_logger.py` dans `log_action()` via `_format_replay_style_message()`. La refonte ne modifie **PAS** cette fonction, donc les en-têtes sont **automatiquement conservés**. Pas d'action requise.

**Preuve**: Le code actuel produit déjà ces en-têtes, donc ils seront conservés.

### Format Multi-Attack Combat (Exemple Complet)

Pour une unité avec CC_NB=3 qui attaque 3 fois:

```
--- FIGHT ---
[19:31:44] T1 P1 FIGHT : Unit 1(21,6) ATTACKED unit 13(20,6) with [Close Combat Weapon] - Hit:3+:4(HIT) Wound:3+:5(WOUND) Save:6+:2(FAIL) Dmg:1HP [R:+3.0] [SUCCESS] [STEP: YES]
[19:31:44] T1 P1 FIGHT : Unit 1(21,6) ATTACKED unit 13(20,6) with [Close Combat Weapon] - Hit:3+:6(HIT) Wound:3+:4(WOUND) Save:6+:3(FAIL) Dmg:1HP [R:+0.0] [SUCCESS] [STEP: NO]
[19:31:44] T1 P1 FIGHT : Unit 1(21,6) ATTACKED unit 13(20,6) with [Close Combat Weapon] - Hit:3+:1(MISS) [R:+0.0] [SUCCESS] [STEP: NO]
```

**Points clés**:
- 3 lignes distinctes (une par attaque)
- **En-tête** `--- FIGHT ---` présent (généré automatiquement)
- Première ligne: `[STEP: YES]` avec reward non-nul (`[R:+3.0]`)
- Lignes suivantes: `[STEP: NO]` avec reward = 0.0 (`[R:+0.0]`)
- Chaque ligne contient tous les détails de l'attaque
- Format identique pour chaque ligne

### Format Actions Échouées (Exemple - Si Applicable)

Si une charge échoue (roll trop bas):

```
--- CHARGE ---
[19:31:44] T1 P1 CHARGE : Unit 1(21,7) FAILED CHARGE unit 13(20,6) from (21,7) to (21,6) [Roll:3] [R:-1.0] [FAILED] [STEP: YES]
```

**Note**: Ce format sera produit automatiquement par `step_logger._format_replay_style_message()` si `success=False` est passé.

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

#### Étape 1.4: Supprimer DEBUG excessif

**Fichier**: `engine/w40k_core.py`  
**Lignes à SUPPRIMER**: 889-904 (DEBUG excessif dans section combat)

**Raison**: Code pollué, garder seulement erreurs critiques si nécessaire.

### Phase 2: Garantir `all_attack_results` Complet dans Handlers

#### Étape 2.1: Vérifier que handlers retournent `all_attack_results`

**Fichier**: `engine/phase_handlers/fight_handlers.py`

**Vérifications nécessaires:**
1. Ligne 1858: `result["all_attack_results"] = fight_attack_results` ✅
2. Ligne 1957: `result["all_attack_results"] = fight_attack_results` ✅
3. Ligne 1812: `"all_attack_results": all_attack_results` ✅

**CONFIRMATION**: Les handlers RETOURNENT déjà `all_attack_results`. ✅

#### Étape 2.2: Vérifier copie explicite dans handlers (Recommandé)

**Fichier**: `engine/phase_handlers/fight_handlers.py`

**Vérification**: S'assurer que `result["all_attack_results"]` est une COPIE, pas une référence.

**Code actuel:**
```python
result["all_attack_results"] = fight_attack_results
```

**Code recommandé (pour clarté et sécurité):**
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
3. Supprimer DEBUG excessif (lignes 889-904)
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
                "current_turn": pre_action_turn,  # Source de vérité unique
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
                phase=pre_action_phase,  # Source de vérité unique
                player=pre_action_player,  # Source de vérité unique
                success=success,
                step_increment=(i == 0),  # Only first attack increments step
                action_details=attack_details
            )
```

**Changements:**
1. ✅ Supprimé vérification `combat_already_logged`
2. ✅ Supprimé code de récupération `fight_attack_results`
3. ✅ Supprimé DEBUG excessif (garder seulement erreurs)
4. ✅ Simplifié logique: si `all_attack_results` vide et pas `waiting_for_player` → erreur
5. ✅ **FORMAT CONSERVÉ**: `step_logger.log_action()` génère déjà le format correct
6. ✅ **SOURCE DE VÉRITÉ UNIQUE**: Utilise `pre_action_turn`, `pre_action_phase`, `pre_action_player`

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

### Modification 4: Vérifier Logging Actions Échouées (DÉCISION REQUISE)

**Fichier**: `engine/w40k_core.py`  
**Ligne**: 686

**CODE ACTUEL:**
```python
if (self.step_logger and self.step_logger.enabled and success):
```

**ANALYSE COMPLÈTE** (inspirée de refac_log3.md):

**Problème identifié**:
- Cette condition filtre les actions avec `success=False`
- Selon `step_logger.py` ligne 36: `"STEP INCREMENT ACTIONS: move, shoot, charge, combat, wait (SUCCESS OR FAILURE)"`
- Selon `step_logger.py` ligne 59: `success_status = "SUCCESS" if success else "FAILED"`
- `step_logger.py` supporte le logging des actions échouées

**Comportement actuel**:
- Ligne 642: `episode_steps` n'est incrémenté QUE si `success=True`
- Donc: Actions échouées n'incrémentent PAS le step
- Logique actuelle: Si pas d'incrément de step, pas de logging? (cohérent avec ligne 686)

**PROCESSUS DE DÉCISION**:

1. **Vérifier avec `hidden_action_finder.py`**:
   - Lancer un training
   - Vérifier si des actions échouées sont détectées comme "manquantes"
   - Si OUI → Actions échouées doivent être loguées
   - Si NON → Comportement actuel est correct

2. **Si actions échouées doivent être loguées**:
   ```python
   if (self.step_logger and self.step_logger.enabled):  # Log toutes les actions
   ```
   - **AVANTAGE**: Visibilité complète dans les logs
   - **INCONVÉNIENT**: Logs plus longs, mais cohérent avec `step_logger.py` ligne 36

3. **Si actions échouées ne doivent PAS être loguées** (comportement actuel):
   ```python
   # Aucun changement - garder la condition actuelle
   if (self.step_logger and self.step_logger.enabled and success):
       # Actions échouées ne sont pas loguées (cohérent: pas d'incrément de step)
   ```
   - **AVANTAGE**: Logs plus courts, seulement actions qui incrémentent step
   - **INCONVÉNIENT**: Actions échouées invisibles (mais peut-être intentionnel)

**RECOMMANDATION**: 
- **ÉTAPE 1**: Vérifier avec `hidden_action_finder.py` après Modification 1-3
- **ÉTAPE 2**: Si actions échouées détectées comme manquantes → Supprimer `and success`
- **ÉTAPE 3**: Si aucune action échouée manquante → Garder comportement actuel (cohérent)

**CODE MIS À JOUR (décision après vérification):**

**Option A (si actions échouées doivent être loguées):**
```python
if (self.step_logger and self.step_logger.enabled):  # Log toutes les actions
```

**Option B (si comportement actuel est correct):**
```python
if (self.step_logger and self.step_logger.enabled and success):  # Garder comportement actuel
```

**Note**: Cette modification doit être faite **APRÈS** vérification avec `hidden_action_finder.py`.

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
4. ✅ Format identique à l'exemple fourni (lignes 854-868)
5. ✅ En-tête `--- FIGHT ---` présent (généré automatiquement)

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

### Test 5: Comparaison avec `debug.log`

**Scénario**: Lancer `check/hidden_action_finder.py` après training.

**Vérifications:**
1. ✅ `hidden_action_finder_output.txt` montre 0 attaques non loguées
2. ✅ `hidden_action_finder_output.txt` montre 0 mouvements non logués
3. ✅ **NOUVEAU**: Vérifier si des actions échouées sont détectées comme manquantes

### Test 6: Format de Sortie Identique

**Scénario**: Comparer `step.log` avant et après refonte.

**Vérifications:**
1. ✅ Format des timestamps identique `[HH:MM:SS]`
2. ✅ Format des sections `--- ACTION_TYPE ---` identique (en-têtes générés automatiquement)
3. ✅ Format des messages détaillés identique
4. ✅ Placement de `[R:{reward:+.1f}]`, `[SUCCESS/FAILED]`, `[STEP: YES/NO]` identique
5. ✅ Format multi-attack conforme à l'exemple fourni
6. ✅ Ordre exact des champs préservé

### Test 7: Actions Échouées (Validation Décision Modification 4)

**Scénario**: Tester une action qui échoue (ex: charge avec roll trop bas).

**Vérifications:**
1. ✅ Vérifier si action échouée est loguée ou non (selon décision Modification 4)
2. ✅ Si loguée: format `[FAILED]` présent et conforme à l'exemple
3. ✅ Si non loguée: vérifier avec `hidden_action_finder.py` qu'elle n'est pas détectée comme manquante
4. ✅ Vérifier que le comportement est cohérent avec incrément de step (ligne 642)

### Test 8: Source de Vérité Unique pour Turn/Phase/Player

**Scénario**: Vérifier que turn/phase/player sont corrects dans les logs.

**Vérifications:**
1. ✅ Turn dans log = turn AVANT action (pas après)
2. ✅ Phase dans log = phase AVANT action (pas après transition)
3. ✅ Player dans log = player AVANT action
4. ✅ Aucune incohérence détectée par `analyzer.py`

---

## 📋 CHECKLIST DE VALIDATION {#checklist}

### Avant Modification

- [ ] Backup de `engine/w40k_core.py`
- [ ] Backup de `engine/phase_handlers/fight_handlers.py`
- [ ] Comprendre le flux actuel (lire ce document)
- [ ] Comprendre le format de sortie attendu (lignes 854-868)
- [ ] Lire `refac_log2.md` (base) et `refac_log3.md` (problèmes additionnels)

### Pendant Modification

- [ ] **Modification 1**: Supprimer lignes 1395-1469 dans `w40k_core.py`
- [ ] **Modification 2**: Simplifier section combat lignes 880-995
- [ ] **Modification 3**: Vérifier/corriger copies dans handlers (optionnel mais recommandé)
- [ ] **Modification 4**: Vérifier/valider condition ligne 686 pour actions échouées (documenter décision)

### Après Modification (Modifications 1-3)

- [ ] Tests unitaires passent
- [ ] Training tourne sans erreur
- [ ] `step.log` généré correctement
- [ ] **Format de sortie identique** à l'exemple fourni (lignes 854-868)
- [ ] `hidden_action_finder.py` montre 0 problèmes
- [ ] `analyzer.py` analyse `step.log` sans erreur

### Validation Actions Échouées (Modification 4)

- [ ] Lancer `hidden_action_finder.py` sur training
- [ ] Vérifier si actions échouées sont détectées comme manquantes
- [ ] **Décision**: Loguer actions échouées ou non
- [ ] Appliquer Modification 4 selon décision
- [ ] Re-valider avec `hidden_action_finder.py`

### Validation Finale

- [ ] Comparer `debug.log` vs `step.log` → 0 différence
- [ ] Vérifier qu'aucune attaque n'est perdue
- [ ] Vérifier qu'aucun mouvement n'est perdu
- [ ] **Vérifier format de sortie ligne par ligne** avec exemple (lignes 854-868)
- [ ] Vérifier source de vérité unique (turn/phase/player corrects)
- [ ] Documenter résultats dans ce fichier

---

## 🎯 PRINCIPES À RESPECTER

1. **UN SEUL POINT DE LOGGING**: Tout se fait dans `step()` après réception du `result`
2. **HANDLERS RETOURNENT TOUT**: Les handlers doivent retourner `all_attack_results` complet
3. **PAS D'ÉTAT PARTAGÉ**: Ne pas utiliser `fight_attack_results` comme état partagé
4. **SIMPLICITÉ**: Supprimer tout code de récupération/fallback (signe de problème architectural)
5. **FORMAT CONSERVÉ**: Le format de sortie doit rester **EXACTEMENT** identique à l'exemple fourni (lignes 854-868)
6. **SOURCE DE VÉRITÉ UNIQUE**: Utiliser `pre_action_turn`, `pre_action_phase`, `pre_action_player` capturés AVANT action
7. **VALIDATION AVANT ACTION**: Vérifier avec `hidden_action_finder.py` avant Modification 4

---

## 📚 RÉFÉRENCES

- `AI_TURN.md`: Spécifications du système de tour
- `check/hidden_action_finder.py`: Vérification des actions non loguées
- `ai/analyzer.py`: Analyse de `step.log`
- Format de sortie attendu: Voir exemple lignes 854-868 (terminal selection)
- `refac_log2.md`: Base de cette approche (simplification minimaliste)
- `refac_log3.md`: Analyse complète des problèmes (inclus Problème 5 et 6)

---

## 🔍 NOTES TECHNIQUES

### Pourquoi le format est déjà correct

Le format de sortie est généré par `step_logger._format_replay_style_message()` qui produit déjà le format attendu. La refonte ne modifie **PAS** cette méthode, seulement garantit que toutes les actions sont loguées.

### Points d'attention

- ⚠️ Ne pas modifier `step_logger.py` (format déjà correct)
- ⚠️ S'assurer que `pre_action_phase` est utilisé (pas `current_phase`)
- ⚠️ S'assurer que `pre_action_turn` est utilisé (pas `current_turn`)
- ⚠️ S'assurer que `pre_action_player` est utilisé (pas `current_player`)
- ⚠️ Vérifier que les handlers retournent bien `all_attack_results` complet
- ⚠️ **NOUVEAU**: Vérifier actions échouées avec `hidden_action_finder.py` avant Modification 4

### Validation Stricte (Inspirée de refac_log3.md)

Bien que `step_logger.py` fasse déjà de la validation (lignes 216-237), la validation dans `w40k_core.py` (ligne 686-716) est également importante:

- ✅ Validation `action_type` dans whitelist (ligne 707)
- ✅ Validation `unit_id` non-null (ligne 709)
- ✅ Validation données requises pour combat (Modification 2)

**Pas de fallback silencieux**: Si données manquantes → erreur explicite (Modification 2 ligne 315-318)

---

## 🎯 DIFFÉRENCES AVEC REFAC_LOG3.MD

**Pourquoi cette approche plutôt que refac_log3.md**:

1. ✅ **Garde `step_logger.py` existant**: Ne réimplémente pas le formatage (risque de perdre le format)
2. ✅ **Changements minimaux**: Suppression seulement, pas de refonte complète
3. ✅ **Risque minimal**: Format garanti car code existant conservé
4. ✅ **Conforme `.cursorrules`**: Modifications ciblées, une à la fois

**Éléments pris de refac_log3.md**:
- Problème 5: Actions échouées (Modification 4)
- Problème 6: Incohérence turn (déjà résolu dans refac_log2.md avec `pre_action_turn`)
- Validation stricte (concept appliqué dans Modification 2)

**Éléments NON pris de refac_log3.md**:
- Nouveau module `ActionLogger` (trop de changements, risque élevé)
- Réécriture formatage (risque de perdre format exact)
- Logging synchrone step.log + debug.log (pas nécessaire, step_logger fonctionne)

---

**FIN DU DOCUMENT**

