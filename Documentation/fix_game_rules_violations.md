# CONSIGNE OPTIMISÉE - Résolution autonome des violations de règles de jeu

## WORKFLOW ITÉRATIF

### Phase 1 : EXÉCUTION & ANALYSE INITIALE
1. Exécuter : `python ai/train.py --agent SpaceMarine_Infantry_Troop_RangedSwarm --training-config default --rewards-config SpaceMarine_Infantry_Troop_RangedSwarm --scenario bot --test-only --step --test-episodes 15 2>&1 | tee movement_debug.log ; python ai/analyzer.py step.log ; python check/hidden_action_finder.py`

2. Analyser les résultats dans cet ordre de priorité :
   - **FATAL ERRORS** (ValueError, exceptions) → STOP, fix immédiat
   - **Résumé de `ai/analyzer.py`** : compter les violations de règles (par catégorie) — voir [ANALYZER.md](ANALYZER.md)
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
3. Vérifier dans `movement_debug.log` si les validations de position ont été effectuées
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
2. Vérifier dans `movement_debug.log` si `build_enemy_adjacent_hexes` a été appelé
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

#### 2.2 Confirmation de root cause :
- **Critère de certitude** : Avoir identifié le code exact qui cause la violation (fichier + ligne + condition)
- **Preuve** : Au moins 2 exemples concrets qui montrent le pattern
- **Si incertain** : Créer un script d'investigation ciblé (max 30 lignes) pour confirmer
- **Référence** : Vérifier que la violation est bien contraire à `AI_TURN.md` ou aux règles du jeu

### Phase 3 : FIX (seulement si root cause identifiée à 100%)

**Avant chaque fix** :
1. Vérifier que le fix ne casse pas d'autres règles (lire le contexte du code)
2. Vérifier que le fix est conforme à `AI_TURN.md`
3. Fix minimal : modifier uniquement ce qui est nécessaire pour empêcher la violation
4. Ajouter un commentaire expliquant le fix et référençant la règle si non évident

**Après chaque fix** :
1. Relancer le workflow (Phase 1)
2. Vérifier que le nombre de violations diminue pour la catégorie concernée
3. Vérifier que le fix n'a pas introduit de nouvelles violations
4. Si violations augmentent → REVERT immédiat, investiguer plus

### Phase 4 : CRITÈRES D'ARRÊT

**Arrêter quand** :
- Toutes les violations critiques sont résolues (UNIT POSITION COLLISIONS, Shoot at friendly unit) ET
- Violations haute priorité < 5% des actions totales OU
- 3 itérations consécutives sans amélioration significative (<10% réduction) OU
- Toutes les violations restantes sont identifiées comme faux positifs ou comportements voulus

**Si arrêt sans résolution complète** :
- Documenter les violations restantes avec exemples concrets
- Expliquer pourquoi elles ne peuvent pas être résolues (limitation de conception, edge case rare, etc.)
- Prioriser les violations les plus fréquentes pour une résolution future

## RÈGLES D'OPTIMISATION TOKENS

1. **Ne pas relire les mêmes logs** : Si déjà analysé, référencer l'analyse précédente
2. **Analyser par échantillonnage** : 2-3 exemples suffisent pour identifier un pattern
3. **Scripts d'investigation courts** : Max 30 lignes, ciblés sur un problème spécifique
4. **Pas de répétition** : Ne pas réexpliquer ce qui a déjà été fait
5. **Focus sur les changements** : Après un fix, analyser seulement ce qui a changé
6. **Prioriser par impact** : Traiter d'abord les violations les plus fréquentes

## FORMAT DE RAPPORT ITÉRATIF

Pour chaque itération, rapporter :

[ITÉRATION N]
Violations détectées : [catégorie: nombre, ...]
Priorité cible : [catégorie la plus fréquente]
Root cause identifiée : [description concise]
Fix appliqué : [fichier + ligne + changement]
Résultat : [réduction % ou "stagnant"]

## EXCEPTIONS

- **Fatal errors** : Fix immédiat sans investigation approfondie
- **Violations < 1%** : Documenter mais ne pas prioriser
- **Comportements voulus** : Si la violation fait partie des règles du jeu (documenter dans AI_TURN.md)

## CONTEXTE IMPORTANT

- Les violations peuvent venir de :
  - Validation insuffisante dans les handlers de phase
  - Race conditions entre actions concurrentes
  - États du jeu non synchronisés (flags, pools)
  - Logique de filtrage incomplète dans les pools de validité
- Toujours vérifier `AI_TURN.md` pour confirmer que c'est bien une violation
- Certaines "violations" peuvent être des faux positifs du parser `ai/analyzer.py`

