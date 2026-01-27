# Observation tuning — analyse de performance et description du processus

## 1. Analyse de performance (episode 58, step 111)

### Constat

- **STEP_TIMING** step 111 : **3,59 s**
- **ENGINE_TIMING** (même step) : `get_mask_s` ≈ 0,03 s, `process_s` ≈ 0,12 s, **`build_obs_s` ≈ 3,59 s**
- **BUILD_OBS_TIMING** : **`enemies_s` = 3,59 s** ; toutes les autres sections < 0,001 s

Le pic est intégralement dans **`build_observation`** → section **enemies** (entre t5 et t6), c’est‑à‑dire :

- `_get_valid_targets`
- `_sort_valid_targets`
- `_get_six_reference_enemies`
- **`_encode_enemy_units`**

### Logs

Juste avant le BUILD_OBS_TIMING, une grosse série de **`[LOS DEBUG]`** :

- `_has_line_of_sight: Shooter X(...) -> Target Y(...)`
- `Wall source: game_state['wall_hexes'], Length: 72`, `Converted 72 valid wall hexes`
- `Hex path (N hexes): ...`, `LoS BLOCKED` / `LoS CLEAR`

avec plusieurs shooters (5, 7, 9, 11, 12, 13, 14…) et plusieurs cibles (1, 2, 5, 7, …).

### Root cause

Dans **`_encode_enemy_units`**, pour **chaque** des 6 ennemis encodés :

1. **Visibility to allies (feature 14)**  
   Boucle sur **tous les alliés** vivants. Pour chaque `(ally, enemy)` :  
   `_check_los_cached(ally, enemy, game_state)`.  
   Les alliés n’ont en général **pas** de `los_cache` (seul l’unité active en shoot en a un).  
   → Fallback systématique vers `_has_line_of_sight` → raycast complet (murs, hex path).

2. **Combined friendly threat (feature 15)**  
   Même boucle sur les alliés avec `_calculate_danger_probability(enemy, ally)`.

3. **Melee charge preference (feature 16)**  
   Pour chaque allié avec CC+RNG à portée de charge :  
   `calculate_pathfinding_distance(ally, enemy)`, `get_best_weapon_for_target`, `calculate_ttk_with_weapon`, etc.

On obtient **6 × N_allies** vérifications LoS sans cache → autant de `_has_line_of_sight` complets (72 murs, chemins hex). Avec 5–10 alliés, 30–60 raycasts coûteux par `build_observation`, d’où les ~3,6 s.

### Pistes de correction

1. **Cache LoS pour l’obs**  
   Lors du `build_observation` en phase shoot, construire (ou réutiliser) un **los_cache** pour les unités utilisées dans `_encode_enemy_units` (au minimum les alliés pour visibility / combined threat), afin que `_check_los_cached` utilise le cache au lieu de `_has_line_of_sight` à chaque fois.

2. **Pré‑calcul LoS pour l’obs**  
   Avant d’encoder les 6 ennemis, calculer une fois les LoS utiles (p.ex. `(ally_id, enemy_id) -> bool`) pour les paires concernées, puis utiliser ce pré‑calcul dans `_encode_enemy_units`.

3. **Alléger les features coûteuses**  
   Réduire le nombre d’alliés considérés pour visibility / combined threat, ou simplifier / cacher la partie melee_charge_preference (pathfinding, TTK).

---

## 2. Déroulement du processus (build_observation, section enemies)

### Quand est‑ce que ça s’exécute ?

À chaque step, après `process` (exécution de l’action) et avant `get_mask` / `predict`, le moteur appelle **`build_observation(game_state)`** pour produire le vecteur d’observation de l’unité qui va jouer au step suivant.

### Structure globale de `build_observation`

Le vecteur est construit en **6 sections** :

| Section | Plage | Contenu |
|--------|-------|--------|
| 1 | [0:16] | Contexte global (objectifs, etc.) |
| 2 | [16:38] | Capacités de l’unité active |
| 3 | [38:70] | Terrain directionnel |
| 4 | [70:142] | Unités alliées (12 × 6 floats) |
| **5** | **[142:274]** | **Unités ennemies (6 × 22 floats)** |
| 6 | [274:314] | Cibles valides (5 × 8 floats) |

La section **5 (enemies)** est celle qui coûte ~3,6 s dans le cas pathologique.

### Enchaînement de la section enemies (t5 → t6)

1. **`_get_valid_targets(active_unit, game_state)`**  
   Selon la phase (shoot / charge / fight), construit la liste des cibles valides. En shoot : appelle `shooting_build_valid_target_pool` pour l’unité active (une seule unité, LoS déjà cachée → rapide).

2. **`_sort_valid_targets(...)`**  
   Trie ces cibles par priorité (stratégie, distance).

3. **`_get_six_reference_enemies(...)`**  
   À partir des cibles valides + tous les ennemis à portée de perception, forme une liste de **6 ennemis de référence** (distance, tri). Ces 6 sont utilisés pour l’encodage et pour les valid targets.

4. **`_encode_enemy_units(..., six_enemies=...)`**  
   Pour **chaque** des 6 ennemis, remplit **22 floats** (position relative, distance, HP, has_moved, has_shot, has_charged, has_attacked, is_valid_target, best_weapon_index, best_kill_probability, danger_to_me, **visibility_to_allies**, **combined_friendly_threat**, **melee_charge_preference**, target_efficiency, is_adjacent, combat_mix_score, favorite_target).  
   C’est ici que se font les boucles coûteuses :
   - **Visibility to allies** : pour chaque allié, `_check_los_cached(ally, enemy)` → souvent sans cache → `_has_line_of_sight`.
   - **Combined friendly threat** : pour chaque allié, `_calculate_danger_probability(enemy, ally)`.
   - **Melee charge preference** : pour les alliés CC+RNG à portée de charge, pathfinding + best weapon + TTK.

Résumé : **6 ennemis × (N_allies × LoS + N_allies × danger + alliés melee × pathfinding/TTK)** → complexité élevée quand il y a beaucoup d’unités et de murs, d’où le pic de 3,6 s.

### Où dans le code ?

- **`build_observation`** : `engine/observation_builder.py` (sections 1–6, timings t0–t7).
- **Section 5** : appels `_get_valid_targets`, `_sort_valid_targets`, `_get_six_reference_enemies`, `_encode_enemy_units` (même fichier).
- **LoS** : `_check_los_cached` → `shooting_handlers._has_line_of_sight` (murs, hex path).
