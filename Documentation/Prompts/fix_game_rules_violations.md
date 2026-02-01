# CONSIGNE OPTIMISÉE - Résolution autonome des violations de règles de jeu

⚠️ **MODE AUTO ACTIVÉ** ⚠️
Suivre les règles "MODE AGENT/AUTO" de `.cursorrules`.
Ce prompt définit un workflow itératif avec checkpoints de validation stratégiques.

## CHECKPOINTS DE VALIDATION (OBLIGATOIRES)

**En MODE AUTO, s'arrêter pour validation uniquement aux checkpoints suivants :**

1. **CHECKPOINT 1 : Après Phase 1** (analyse initiale)
   - ✅ Peut continuer automatiquement si violations détectées
   - ⏸️ S'arrêter et présenter le résumé si aucune violation

2. **CHECKPOINT 2 : Après Phase 2** (investigation)
   - ✅ Peut continuer automatiquement si root cause identifiée à 100% avec preuve (2+ exemples)
   - ⏸️ S'arrêter et demander validation si root cause incertaine ou si script d'investigation nécessaire

3. **CHECKPOINT 3 : Avant Phase 3** (fix)
   - ✅ Peut continuer automatiquement si root cause identifiée à 100% avec preuve
   - ⏸️ S'arrêter et présenter le plan de fix si :
     - Modification impacte plusieurs fichiers (>2 fichiers)
     - Modification risque de casser d'autres règles (changement structurel majeur)
     - Fix nécessite refactoring significatif

4. **CHECKPOINT 4 : Après Phase 3** (relance workflow)
   - ✅ Peut relancer automatiquement Phase 1 si :
     - Fix réussi (violations diminuent)
     - Critères d'arrêt non atteints
     - Nombre d'itérations < 5
   - ⏸️ S'arrêter et présenter le rapport si :
     - Fix échoue (violations augmentent) → REVERT et investiguer
     - 5+ itérations consécutives → présenter rapport de progression
     - Critères d'arrêt atteints → présenter rapport final

5. **CHECKPOINT 5 : Critères d'arrêt atteints**
   - ⏸️ TOUJOURS s'arrêter et présenter le rapport final complet

**En dehors de ces checkpoints, continuer automatiquement.**

## WORKFLOW ITÉRATIF

### Phase 1 : EXÉCUTION & ANALYSE INITIALE

**En MODE AUTO : Exécution automatique autorisée**

1. **Exécuter automatiquement** : `python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config default --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm --scenario bot --test-only --step --test-episodes 15 2>&1 | tee debug.log ; python ai/analyzer.py step.log ; python check/hidden_action_finder.py`

2. **Analyser automatiquement** les résultats dans cet ordre de priorité :
   - **FATAL ERRORS** (ValueError, exceptions) → STOP, fix immédiat
   - **Résumé de `ai/analyzer.py`** : compter les violations de règles (par catégorie)
   - **Patterns récurrents** : si >50% des violations sont du même type → investiguer ce type en priorité
   - **Priorité des violations** :
     1. **UNIT POSITION COLLISIONS** (2+ unités sur même hex) → CRITIQUE
     2. **Shoot at friendly unit** → CRITIQUE
     3. **Moves to adjacent enemy** → HAUTE
     4. **Shoot at engaged enemy** → HAUTE
     5. **Charges from adjacent hex** → MOYENNE
     6. **Charge after fled** → MOYENNE
     7. **Shoot after fled** → MOYENNE
     8. **Advances from adjacent hex** → BASSE
     9. **Shoot through wall** → BASSE

### Phase 2 : INVESTIGATION CIBLÉE (si violations détectées)

**Règle d'or** : Ne jamais modifier le code sans avoir identifié la root cause avec certitude.

#### 2.1 Pour chaque type de violation, investiguer dans cet ordre :

**UNIT POSITION COLLISIONS** :
1. Extraire 2-3 exemples spécifiques (Episode #X, Turn Y, action_type: Unit A, Unit B at (col,row))
2. Vérifier dans `step.log` les actions impliquées (mouvement/charge)
3. Vérifier dans `debug.log` si les validations de position ont été effectuées
4. Identifier si le problème vient de :
   - Validation insuffisante avant mouvement/charge
   - Race condition (deux unités se déplacent simultanément)
   - Position non mise à jour correctement après mouvement

**Shoot at friendly unit** :
1. Extraire 2-3 exemples spécifiques (E1 T1 SHOOT : Unit X SHOT at Unit Y)
2. Vérifier si `target_id` est une unité amie
3. Identifier si le problème vient de :
   - Filtrage des cibles insuffisant dans `valid_target_pool_build`
   - Validation manquante avant l'exécution du tir
   - Changement d'appartenance après la construction de la pool (improbable)

**Moves to adjacent enemy** :
1. Extraire 2-3 exemples spécifiques (E1 T1 MOVE : Unit X MOVED from (a,b) to (c,d))
2. Vérifier dans `debug.log` si `build_enemy_adjacent_hexes` a été appelé
3. Vérifier si la destination est dans `enemy_adjacent_hexes`
4. Identifier si le problème vient de :
   - `build_valid_destinations` ne filtre pas correctement les hex adjacents à l'ennemi
   - Validation manquante avant l'exécution du mouvement

**Shoot at engaged enemy** :
1. Extraire 2-3 exemples spécifiques (E1 T1 SHOOT : Unit X SHOT at Unit Y)
2. Vérifier si la cible est engagée (adjacente à une unité amie)
3. Identifier si le problème vient de :
   - Filtrage insuffisant dans `valid_target_pool_build` (règle de l'unité adjacente)
   - Validation manquante avant l'exécution du tir

**Charges from adjacent hex** :
1. Extraire 2-3 exemples spécifiques (E1 T1 CHARGE : Unit X CHARGED Unit Y from (a,b) to (c,d))
2. Vérifier si l'unité était déjà adjacente à la cible avant le charge
3. Identifier si le problème vient de :
   - `charge_build_valid_destinations` n'exclut pas les positions où l'unité est déjà adjacente
   - Validation manquante avant l'exécution du charge

**Charge after fled / Shoot after fled** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si l'unité a fui dans le même tour/phase
3. Identifier si le problème vient de :
   - Flag `units_fled` non mis à jour correctement
   - Validation manquante pour vérifier si l'unité a fui avant charge/shoot

**Advances from adjacent hex** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si l'unité était adjacente à un ennemi avant l'advance
3. Identifier si le problème vient de :
   - Validation manquante dans `shooting_unit_activation_start` (CAN_ADVANCE check)
   - Flag `_can_advance` mal calculé

**Shoot through wall** :
1. Extraire 2-3 exemples spécifiques
2. Vérifier si un mur bloque la ligne de vue
3. Identifier si le problème vient de :
   - `_has_line_of_sight` ne détecte pas correctement les murs
   - Cache LoS obsolète

#### 2.1.1 Flux correct de la phase de charge (référence : `Documentation/AI_TURN.md`) :

**ELIGIBILITY CHECK (Pool Building Phase)** :
```javascript
Dans le pool d'activation si :
├── ELIGIBILITY CHECK (Pool Building Phase)
│   ├── unit.HP_CUR > 0?
│   │   └── NO → ❌ Dead unit (Skip, no log)
│   ├── unit.player === current_player?
│   │   └── NO → ❌ Wrong player (Skip, no log)
│   ├── units_fled.includes(unit.id)?
│   │   └── YES → ❌ Fled unit (Skip, no log)
│   ├── units_advanced.includes(unit.id)?
│   │   └── YES → ❌ Advanced unit cannot charge (Skip, no log)
│   ├── Adjacent to enemy unit within CC_RNG?
│   │   └── YES → ❌ Already in fight (Skip, no log)
│   ├── Enemies exist within charge_max_distance hexes AND has non occupied adjacent hex(es) at 12 hexes or less ?
│   │   └── NO → ❌ No charge targets (Skip, no log)
│   └── ALL conditions met → ✅ Add to charge_activation_pool
```

**Activation** :
1. **Build valid targets** :
   - Enemy unit
   - within charge_max_distance hexes
   - having non occupied adjacent hex(es) at 12 hexes or less from the active unit
2. **Agent choisit une cible** (parmi les valid targets)
3. **Roll 2d6** (charge roll)
4. **Build le pool avec le roll réel pour cette cible** contenant toutes les cases qui sont :
   - adjacentes à la cible
   - à une distance <= charge roll
   - inoccupées

**Points de validation à vérifier lors de l'investigation** :
- La condition "has non occupied adjacent hex(es) at 12 hexes or less" est-elle vérifiée dans l'ELIGIBILITY CHECK ?
- Le pool de valid targets est-il construit correctement avant le choix de l'agent ?
- Le roll 2d6 est-il effectué après le choix de la cible par l'agent ?
- Le pool de destinations finales est-il construit avec le roll réel pour la cible choisie (et non avec charge_max_distance) ?

#### 2.2 Confirmation de root cause :
- **Critère de certitude** : Avoir identifié le code exact qui cause la violation (fichier + ligne + condition)
- **Preuve** : Au moins 2 exemples concrets qui montrent le pattern
- **Si incertain** : Créer un script d'investigation ciblé (max 30 lignes) pour confirmer → **CHECKPOINT 2 : S'arrêter avant**
- **Référence** : Vérifier que la violation est bien contraire à `Documentation/AI_TURN.md` ou aux règles du jeu
- **Décision** :
  - ✅ Root cause identifiée à 100% + 2+ exemples → Continuer automatiquement vers Phase 3
  - ⏸️ Root cause incertaine ou < 2 exemples → **CHECKPOINT 2 : S'arrêter et présenter l'investigation**

### Phase 3 : FIX (seulement si root cause identifiée à 100%)

**Avant chaque fix** :
1. Vérifier que le fix ne casse pas d'autres règles (lire le contexte du code)
2. Vérifier que le fix est conforme à `Documentation/AI_TURN.md`
3. Fix minimal : modifier uniquement ce qui est nécessaire pour empêcher la violation
4. Ajouter un commentaire expliquant le fix et référençant la règle si non évident
5. **SUIVRE LE FORMAT STRICT** : Utiliser le template avec CODE ACTUEL + CODE MIS À JOUR selon `.cursorrules`
6. **Évaluer la complexité** :
   - ✅ Fix simple (1-2 fichiers, modification locale) → Continuer automatiquement
   - ⏸️ Fix complexe (>2 fichiers, changement structurel) → **CHECKPOINT 3 : S'arrêter et présenter le plan**

**Après chaque fix** :
1. **Relancer automatiquement Phase 1** si conditions remplies :
   - ✅ Fix réussi (violations diminuent) ET
   - ✅ Nombre d'itérations < 5 ET
   - ✅ Critères d'arrêt non atteints
2. Vérifier que le nombre de violations diminue pour la catégorie concernée
3. Vérifier que le fix n'a pas introduit de nouvelles violations
4. **Si violations augmentent** → **CHECKPOINT 4 : STOP, REVERT immédiat, investiguer plus**
5. **Si 5+ itérations** → **CHECKPOINT 4 : S'arrêter et présenter rapport de progression**

### Phase 4 : CRITÈRES D'ARRÊT

**CHECKPOINT 5 : TOUJOURS s'arrêter et présenter le rapport final quand :**
- Toutes les violations critiques sont résolues (UNIT POSITION COLLISIONS, Shoot at friendly unit) ET
- Violations haute priorité < 5% des actions totales OU
- 3 itérations consécutives sans amélioration significative (<10% réduction) OU
- Toutes les violations restantes sont identifiées comme faux positifs ou comportements voulus OU
- Nombre d'itérations atteint 10 (sécurité)

**Si arrêt sans résolution complète** :
- Documenter les violations restantes avec exemples concrets
- Expliquer pourquoi elles ne peuvent pas être résolues (limitation de conception, edge case rare, etc.)
- Prioriser les violations les plus fréquentes pour une résolution future
- Présenter le rapport final complet avec statistiques et recommandations

## RÈGLES D'OPTIMISATION TOKENS

1. **Ne pas relire les mêmes logs** : Si déjà analysé, référencer l'analyse précédente
2. **Analyser par échantillonnage** : 2-3 exemples suffisent pour identifier un pattern
3. **Scripts d'investigation courts** : Max 30 lignes, ciblés sur un problème spécifique
4. **Pas de répétition** : Ne pas réexpliquer ce qui a déjà été fait
5. **Focus sur les changements** : Après un fix, analyser seulement ce qui a changé
6. **Prioriser par impact** : Traiter d'abord les violations les plus fréquentes

## FORMAT DE RAPPORT ITÉRATIF

**IMPORTANT** : Le format de rapport ci-dessous est un **résumé itératif**. Pour les **modifications de code**, toujours utiliser le format strict (CODE ACTUEL + CODE MIS À JOUR) selon `.cursorrules`.

**Pour chaque itération complète, rapporter :**

```
[ITÉRATION N]
Violations détectées : [catégorie: nombre, ...]
Priorité cible : [catégorie la plus fréquente]
Root cause identifiée : [description concise]
Fichiers modifiés : [fichier1:ligne(s), fichier2:ligne(s), ...]
Changements appliqués : [description concise du changement]
Résultat : [réduction % ou "stagnant" ou "échoué"]
```

**Exemple de rapport itératif** :
```
[ITÉRATION 1]
Violations détectées : UNIT_POSITION_COLLISIONS: 15, Shoot_at_friendly: 3
Priorité cible : UNIT_POSITION_COLLISIONS
Root cause identifiée : Validation insuffisante dans movement_handlers.py:167 - position non vérifiée avant mouvement
Fichiers modifiés : engine/phase_handlers/movement_handlers.py:167-175
Changements appliqués : Ajout vérification position disponible avant mouvement
Résultat : UNIT_POSITION_COLLISIONS réduit de 15 à 8 (-47%)
```

**Note** : Chaque modification de code individuelle doit utiliser le format strict avec CODE ACTUEL + CODE MIS À JOUR. Le rapport itératif est un résumé pour le suivi global.

## EXCEPTIONS

- **Fatal errors** : Fix immédiat sans investigation approfondie
- **Violations < 1%** : Documenter mais ne pas prioriser
- **Comportements voulus** : Si la violation fait partie des règles du jeu (documenter dans Documentation/AI_TURN.md)

## CONTEXTE IMPORTANT

- Les violations peuvent venir de :
  - Validation insuffisante dans les handlers de phase
  - Race conditions entre actions concurrentes
  - États du jeu non synchronisés (flags, pools)
  - Logique de filtrage incomplète dans les pools de validité
- Toujours vérifier `Documentation/AI_TURN.md` pour confirmer que c'est bien une violation
- Certaines "violations" peuvent être des faux positifs du parser `ai/analyzer.py`

