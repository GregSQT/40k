# Gestion des distances — Cartographie complète

> Audit exhaustif de tous les endroits (backend Python + frontend TS) où une
> distance, une portée, une adjacence ou un chevauchement est calculé.
> Objectif : préparer le passage éventuel de certaines distances de la métrique
> **hexagonale** vers la métrique **euclidienne** (empreintes rondes).
> Les numéros de ligne sont indicatifs (état au moment de l'audit).

---

## 0. Les métriques utilisées aujourd'hui

| Métrique | Formule | Sert à |
|----------|---------|--------|
| **Hex cube** | `max(\|dx\|, \|dy\|, \|dz\|)` | Portée droite (tir, charge, move, engagement) — sans murs |
| **Pathfinding BFS** | plus court chemin 6-voisins, respecte les murs | Distance réellement traversable (move / charge / IA) |
| **Distance footprint** | `min_distance_between_sets()` = distance hex min entre 2 empreintes | Contact base-à-base, engagement |
| **Euclidienne (pixel)** | `sqrt(dx²+dy²)` sur sous-hexes/pixels | Empreintes round/oval, LoS, cohésion, clearance |
| **Adjacence** | 6 voisins offset odd-q, ou set pré-calculé | Contact direct ennemi |
| **Overlap** | distance = 0 / intersection des hexes occupées | Collision de socles (déploiement, move, charge, fight) |

Point clé : **portée** (« jusqu'où je peux atteindre ») et **occupation**
(« quelles cases mon socle remplit ») sont déjà deux couches séparées. C'est ce
qui rend le projet de l'utilisateur faisable.

---

## 1. BACKEND — Distance hexagonale (cube & axial)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/combat_utils.py | 275-292 | `calculate_hex_distance()` | Hex cube | Tir, charge, move, engagement (droite, sans murs) |
| engine/hex_utils.py | 90-98 | `hex_distance()` | Hex cube | Alias de calculate_hex_distance |
| engine/hex_utils.py | 100-171 | `min_distance_between_sets()` | Hex cube entre empreintes | Distance min entre 2 footprints |
| engine/hex_utils.py | 173-211 | `dilate_hex_set_unbounded()` | Hex (BFS expansion) | Zone d'engagement, dilatation par rayon |

## 2. BACKEND — Pathfinding (avec murs)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/combat_utils.py | 294-382 | `calculate_pathfinding_distance()` | BFS murs | Déplacements IA, distance traversable réelle |
| engine/hex_utils.py | ~895-1100 | `pathfinding_distance()` | BFS murs | Calcul interne pathfinding |

## 3. BACKEND — Adjacence & voisins

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/combat_utils.py | 115-140 | `is_hex_adjacent_to_enemy()` | Adjacence (set pré-calculé) | Vérif contact ennemi |
| engine/combat_utils.py | 142-183 | `get_hex_neighbors()` | 6 voisins odd-q | Voisins directs |
| engine/hex_utils.py | 40-47 / 49-60 | `get_neighbors()` / `get_neighbors_bounded()` | 6 voisins odd-q | Voisins (bornés ou non) |
| engine/phase_handlers/generic_handlers.py | 431-445 | `_is_adjacent_to_enemy_for_fight()` | Adjacence + footprint | Éligibilité combat |
| engine/phase_handlers/shared_utils.py | 1307-1440 | `build_enemy_adjacent_hexes()` & co. | Voisins d'empreintes ennemies | Cache adjacence engagement |

## 4. BACKEND — Engagement & zone d'engagement (EZ)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/spatial_relations.py | 27-39 | `get_engagement_zone()` / `_from_config()` | Valeur config (sous-hexes) | Rayon d'engagement |
| engine/spatial_relations.py | 41-66 | `enemy_footprint_distances()` | Distance footprint (hex) | Distances aux ennemis |
| engine/spatial_relations.py | 125-163 | `unit_entries_within_engagement_zone()` / `unit_within_engagement_zone_footprints()` | Distance footprint ≤ EZ | Vérif 2 unités engagées |
| engine/spatial_relations.py | 165-210 | `move_anchor_violates_engagement_clearance()` | Distance footprint ≤ EZ | Move ne viole pas la clearance |
| engine/hex_utils.py | 1378-1428 | `engagement_minimum_clearance_norm()` | **Euclidienne** | EZ → norme euclidienne min |
| engine/phase_handlers/movement_handlers.py | 171-355 | `_enemy_items_within_move_engagement_horizon()`, `_movement_engagement_violates()` | Distance footprint ≤ EZ | Move : violation engagement |
| engine/phase_handlers/movement_handlers.py | 1123-1150 | `_is_in_enemy_engagement_zone()` | Distance footprint ≤ EZ | Unité en EZ ennemie |
| engine/phase_handlers/shooting_handlers.py | 2051-2150 | `_friendly_engagement_blocks_ranged_shot()` | Adjacence + footprint ≤ melee | Tir bloqué si engagé |
| engine/phase_handlers/shooting_handlers.py | 5084-5115 | `_is_adjacent_to_enemy_within_cc_range()` | Distance footprint ≤ melee | État engagement CC |
| engine/phase_handlers/charge_handlers.py | 2993-3010 | `_charge_unit_within_engagement_zone()` | Distance footprint ≤ EZ | Charge : déjà engagé |
| engine/phase_handlers/fight_handlers.py | 973-1000 | `_fight_footprint_in_engagement_with_any_enemy()` | Distance footprint ≤ melee | Fight : footprint engagée |

## 5. BACKEND — Overlap & collision (déploiement, move, charge, fight)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/hex_utils.py | 1428-1445 | `footprints_overlap()` | Distance = 0 (socles) | Collision d'empreintes |
| engine/hex_utils.py | ~1489-1600 | `disc_overlaps_polygon()` | **Euclidienne** (disque/polygone) | Collision round vs formes |
| engine/phase_handlers/deployment_handlers.py | 49-68 | `_is_footprint_overlapping()` | Distance = 0 | Déploiement sans overlap |
| engine/phase_handlers/shared_utils.py | 377-420 | `candidate_overlaps_any_unit()` | Distance = 0 | Placement candidat sans overlap |
| engine/phase_handlers/charge_handlers.py | ~1598-1700 / ~4779-4820 | `_charge_model_placement_overlaps()` / `_overlaps_world()` | Distance = 0 | Charge : placement sans collision |

## 6. BACKEND — Mouvement (move phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/observation_builder.py | 682-695 | calcul move_distance | Hex cube | Observation : distance parcourue |
| engine/phase_handlers/movement_handlers.py | 120-170 | `_build_objective_distance_cache()` | Pathfinding | Cache distances objectifs |
| ai/analyzer_phases/move_handler.py | 358-380 | calcul fly_distance | Hex cube | Move fly : distance droite |

## 7. BACKEND — Charge (charge phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/phase_handlers/charge_handlers.py | 565-630 | `_charge_bfs_max_distance()` | Pathfinding BFS | Distance max traversable |
| engine/phase_handlers/charge_handlers.py | ~630-670 | `_charge_skip_hex_lb_prune_round_round_engagement()` | **Euclidienne** round-round | Prune hexes trop loin |
| engine/phase_handlers/charge_handlers.py | 2398-2480 | `charge_build_valid_targets()` | Pathfinding ≤ charge_distance | Cibles valides |
| ai/analyzer_phases/charge_handler.py | 75-110 | calcul charge_distance | Hex cube | IA : distance charge déclarée |
| ai/game_replay_logger.py | 169-200 | distance_needed | Hex cube | Log : distance min requise |

## 8. BACKEND — Tir (shooting phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/phase_handlers/shooting_handlers.py | 620-660 | vérif `weapon_range` | Hex cube | Cible à portée arme |
| engine/phase_handlers/shooting_handlers.py | 800-840 | distance footprint↔footprint | `min_distance_between_sets()` | Empreintes ≤ RNG |
| engine/phase_handlers/shooting_handlers.py | 424-470 (dont ~479-483) | `_build_weapon_availability_enemy_precheck()` | **split** : `hex_distance()` centre (gym) / `min_distance_between_sets()` footprint (PvP) | Précheck portée arme (source de `row["distance"]` en 620-660) — brancher les DEUX branches |
| engine/phase_handlers/shooting_handlers.py | 3150-3970 | distances shooter→target | Hex cube | Distance de tir (plusieurs points) |
| engine/phase_handlers/shooting_handlers.py | 4293-4310 | cible la plus proche | Hex cube | IA : sélection cible |
| ai/analyzer_phases/shoot_handler.py | 406-610 | distances shooter→target | Hex cube | IA tir : validité/visée |
| ai/target_selector.py | 198-210 | distance ally→target | Hex cube | IA : sélection cible |
| engine/ai/weapon_selector.py | 383-400 | distance unit→target | Hex cube | IA arme : cible à portée |

## 9. BACKEND — Combat rapproché (fight phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/phase_handlers/fight_handlers.py | 349-385 | `_fight_enemy_footprint_distances()`, `_is_adjacent_to_enemy_within_cc_range()` | Distance footprint ≤ melee | Distances / adjacence ennemis |
| engine/phase_handlers/fight_handlers.py | 405-425 | `_fight_footprint_has_enemy_hex_contact()` | Adjacence + dist ≤ 1 | Contact hex ennemi |
| engine/phase_handlers/fight_handlers.py | 501-880 | pile-in : anchor / zone | Adjacence + footprint | Pile-in : placement possible |
| engine/phase_handlers/fight_handlers.py | 1144-1190 | `_fight_fp_has_adjacent_enemy_footprint()` | Adjacence footprint | Footprint ennemie adjacente |
| engine/phase_handlers/fight_handlers.py | 5539-5750 | `_overlaps()`, `_distance_field()`, `_start_engagements()` | dist=0 / hex BFS / adjacence | Placement, pile-in, engagements internes |

## 10. BACKEND — Observation & récompense

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/observation_builder.py | 520-2340 | multiples (`_min_distance_to_objective`, reward move, cible, menace…) | Hex cube | Features d'observation IA |
| engine/reward_calculator.py | 1317-1335+ | distance vers tir / melee | Pathfinding + footprint | Récompenses IA |

## 11. BACKEND — Empreinte physique (footprint)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/hex_utils.py | 1102-1200 | `compute_footprint_placement_mask()`, `precompute_footprint_offsets()` | Hexes occupées | Empreinte physique |
| engine/hex_utils.py | 1200-1280 | `_footprint_round()`, `_footprint_oval()`, `_footprint_square()` | **Euclidienne** (pixel) | Forme de la base |

---

## 12. FRONTEND — Distance hexagonale

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/utils/gameHelpers.ts | 30-35 / 300-304 | `cubeDistance()` / `getHexDistance()` | Hex cube | Distance hex standard |
| frontend/src/wasm-los-pkg/wasm_los.d.ts | 19 | `wasm_hex_distance()` | Hex cube (Rust/WASM) | Perf |

## 13. FRONTEND — Adjacence & voisins

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/utils/gameHelpers.ts | 321-361 | `getAdjacentPositions()`, `areUnitsAdjacent()` | 6 voisins / dist=1 | Adjacence |
| frontend/src/components/BoardReplay.tsx | 2179-2510 | `getHexNeighbors()` (×3) | 6 voisins odd-q | Pathfinding replay (move/advance/charge) |

## 14. FRONTEND — Portée (range)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/utils/gameHelpers.ts | 363-407 | `isUnitInRange()`, `getUnitsInRange()`, `getValidMovePositions()` | Hex cube ≤ range | Portée / move valides |
| frontend/src/utils/weaponHelpers.ts | ~93-110 | `getMaxRangedRange()` | Max RNG | Portée max unité |
| frontend/src/utils/probabilityCalculator.ts | 176-230 | `getSelectedRangedWeaponAgainstTarget()` | Hex cube | Sélection arme vs cible |

## 15. FRONTEND — Footprint & overlap

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/utils/hexFootprint.ts | 46-86 | `footprintRound()`, `computeOccupiedHexes()` | **Euclidienne** (pixel) | Hexes occupées |
| frontend/src/utils/hexFootprint.ts | 480-550 | `isFootprintOverlapping()`, `isFootprintInDeployPool()`, `isFootprintOnWall()`, `buildOccupiedSet()` | dist=0 / hexes | Overlap, déploiement, murs |
| frontend/src/components/BoardPvp.tsx | 9324-9350 | appel `isFootprintOverlapping()` | dist=0 | Déploiement overlap |

## 16. FRONTEND — Move / Charge / Tir / Fight

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/components/BoardReplay.tsx | 2248-2600 | BFS move / avance / charge | Pathfinding 6-voisins | Destinations replay |
| frontend/src/components/BoardPvp.tsx | 8234-8250 | `chargeMaxDistance` | Config | Max distance charge |
| frontend/src/hooks/useEngineAPI.ts | 2497-2510 | `charge_dest_distances` | Distances destinations | Affichage charge |
| frontend/src/utils/blinkingHPBar.ts | 89-230 | `distanceSubhexRaw`, `getSelectedRangedWeaponAgainstTarget()` | Sous-hexes / hex | Roll min tir, arme optimale |
| frontend/src/components/BoardPvp.tsx | 3347-3360 / 7191-7210 | sélection cible / contact | `cubeDistance()` (=1) | Tir / combat |
| frontend/src/hooks/useGameActions.ts | 92-195 | peut charger / combat | `cubeDistance()` (≤ melee / =1) | Éligibilité charge & CC |
| frontend/src/hooks/useEngineAPI.ts | 1352-6800 | validations & damage tir/charge | Hex cube / arme | API |

## 17. FRONTEND — LoS, déploiement, objectifs

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| frontend/src/utils/gameHelpers.ts | 140-250 | `hasLineOfSight()` | **Euclidienne** (7 pts/hex) + murs | Ligne de visée |
| frontend/src/wasm-los-pkg/wasm_los.d.ts | 7-14 | `compute_los_single()`, `compute_visible_hexes()` | WASM | LoS / hexes visibles |
| frontend/src/utils/hexFootprint.ts | 503-511 | `getContestedObjectives()` | Footprint overlap | Objectifs contestés |
| frontend/src/hooks/useEngineAPI.ts | 6478-6490 | `within_objective_range` | Distance objectif | Contrôle objectif |

---

## 18. Analyse du projet euclidien / hex hybride

### Proposition de l'utilisateur
- **Move / advance** : distance max + zones d'engagement en **euclidien** ;
  chevauchement avec figs alliées géré en **hex grid** (comme actuellement).
- **Charge** : distances en **euclidien** ; chevauchement en **hex grid**.

### Verdict : cohérent et faisable
Portée et occupation sont déjà deux couches distinctes dans le code
(sections 4-5 vs 1-3). On peut donc changer la métrique de *portée* sans toucher
à la logique d'*overlap*, à condition que les unités restent **positionnées sur
la grille hex** (centres d'hexagones). L'euclidien devient une couche de calcul
par-dessus les coordonnées hex.

### 3 points de vigilance (à trancher avant de coder)

1. **Murs / pathfinding (le vrai piège).**
   Aujourd'hui la distance max de move et de charge = **pathfinding BFS qui
   contourne les murs** (`_charge_bfs_max_distance`, `_build_objective_distance_cache`).
   L'euclidien pur ignore les murs → une unité pourrait « atteindre » une case à
   travers un mur. Il faut décider :
   - soit euclidien **uniquement** pour la portée droite (tir), et garder le
     pathfinding pour move/charge → mais alors move/charge ne deviennent PAS
     ronds (la forme reste dictée par le BFS) ;
   - soit un pathfinding **any-angle** (type Theta*) : budget de distance
     euclidien mais chemin qui contourne les obstacles. C'est ce qu'il faut pour
     avoir des empreintes rondes ET le respect des murs. Plus de travail.

2. **Cohérence de la zone d'engagement entre phases.**
   L'EZ est utilisée dans move, tir (`_friendly_engagement_blocks_ranged_shot`),
   charge ET fight. Si on la passe en euclidien pour le move mais qu'elle reste
   hex ailleurs, on crée des contradictions (unité « engagée » côté move mais
   pas côté tir). → L'EZ doit basculer en euclidien **partout en même temps**,
   pas seulement dans le move.

3. **IA / observations / récompenses.**
   Toute la section 10 (observation_builder, reward_calculator) mesure en hex.
   Si les distances de jeu changent, les features et récompenses de l'IA
   changent aussi → les modèles entraînés seront à re-valider (voire
   ré-entraîner). Ce n'est pas bloquant mais c'est un coût à anticiper.

### Recommandation
Centraliser d'abord : une seule fonction de portée par métrique
(`calculate_hex_distance` / une future `calculate_euclidean_distance`) et un
flag/param décidant laquelle s'applique à chaque règle (move, tir, charge, EZ).
Aujourd'hui `calculate_hex_distance` est appelée directement partout — tant
qu'on n'a pas ce point de bascule unique, le passage à l'euclidien touchera des
dizaines de call-sites de façon dispersée et risquée.

Ordre suggéré : **tir** d'abord (portée droite, pas de pathfinding, faible
risque) → puis **EZ** (globale, toutes phases) → puis **move/charge** (le plus
délicat à cause des murs).

---

## 19. Plan de migration hex → euclidien

### Décisions actées
- **Zone d'engagement (EZ)** : NON touchée pour l'instant → reste hex partout
  (sections 4). On ne migre que la *portée* de tir, move et charge.
- **IA (observations / récompenses)** : retrain prévu de toute façon → l'impact
  sur observations/récompenses (section 10) est ignoré pendant la migration →
  reste hex.
- **IA (sélection de cible / arme)** : la mesure de *portée* côté IA suit la règle
  de la phase, pas le retrain. **Ranged → euclidien**, **melee → hex**.
  Concrètement : `engine/ai/weapon_selector.py` ligne 383 (branche RNG) et
  `ai/target_selector.py` basculent en euclidien avec le tir ; la branche melee
  (`select_best_melee_weapon`) et `macro_intents.py` (distance stratégique)
  restent hex.
- **Positions** : les unités restent posées sur les centres d'hexagones. L'hex
  reste le système de coordonnées et d'occupation ; l'euclidien est une couche
  de calcul de portée par-dessus.
- **Move / charge** : distance max en euclidien via un **champ de distance
  géodésique any-angle** ; overlap alliés/ennemis reste hex. La charge suit le
  move (règle 11.04 : la charge *est* un move) — **même champ géodésique, seul
  le budget change** (2D6 au lieu de M).
- **Algorithme géodésique acté** : **lazy Theta\* en flood** (propagation d'un
  champ de distance où un nœud hérite la distance de son ancêtre s'il y a ligne
  de vue dégagée), **adossé au LoS WASM existant** pour le test de visibilité /
  la règle de coin. Choix retenu vs fast marching (erreur de discrétisation) et
  visibility graph (exact mais O(n²) + pas de champ) : meilleur compromis
  fidélité / perf / **sync front-back gratuite** (même LoS des deux côtés).
- **Tir** : portée droite en euclidien (pas de pathfinding).

### Périmètre — ce qui bascule vs ce qui reste

| Reste HEX (intouché) | Bascule EUCLIDIEN |
|----------------------|-------------------|
| Overlap / collision de socles (§5, §15) | Portée d'arme / tir (§8, §14) |
| Zone d'engagement (§4) | Distance max de move / advance (§6) |
| Adjacence & voisins (§3, §13) | Distance max de charge (§7) |
| Observations / récompenses IA (§10) | — |
| LoS (déjà euclidien §17) | — |
| Empreintes physiques (déjà euclidien §11) | — |

### Étape 0 — Inventaire figé des call-sites (aucune modif de code)
But : transformer les tables de cet audit en liste exhaustive et vérifiée des
appels à basculer. Sortie = une checklist par fichier.
- **Tir** : shooting_handlers.py (424-470 **dont branche gym ~479-483**, 620-660,
  800-840, 3150-3970, 4293-4310),
  analyzer_phases/shoot_handler.py, target_selector.py, weapon_selector.py ;
  frontend gameHelpers.ts (`isUnitInRange`), probabilityCalculator.ts,
  blinkingHPBar.ts, weaponHelpers.ts.
- **Move** : movement_handlers.py (budget de déplacement), observation exclue,
  frontend gameHelpers.ts (`getValidMovePositions`), BoardReplay.tsx BFS move.
- **Charge** : charge_handlers.py (565-630, 2398-2480), useEngineAPI.ts
  (`charge_dest_distances`), BoardPvp.tsx (`chargeMaxDistance`), BoardReplay.tsx
  BFS charge.
- **Checkpoint** : valider la liste avant tout code.

### Étape 1 — Point de bascule unique (backend)
Fichiers : [hex_utils.py](engine/hex_utils.py), [combat_utils.py](engine/combat_utils.py)
- **Primitive géométrique bord-à-bord** dans `hex_utils.py` : `euclidean_edge_distance(a, b)`
  (entrées typées `Socle`). Rond↔rond → réutilise `euclidean_edge_clearance_round_round`
  (O(1)). Non-rond (oval/square) → min euclidien entre centres de cellules occupées,
  réutilisant le prune de `min_distance_between_sets`. Retourne un `float` en unités-norme
  `_hex_center`, sans arrondi. **Aucun centre-à-centre** : `calculate_euclidean_distance`
  centre-à-centre abandonnée (règle 01.04 = mesure bord-à-bord au point le plus proche).
  Note : le proxy cellules pour le non-rond est suffisant pour la portée (longue distance,
  erreur ~0,1") ; un proxy continu (capsule/OBB) ne deviendrait nécessaire que si l'euclidien
  gagnait un jour les règles courte-distance (engagement/overlap) — exclu par ce plan.
- **Sélecteur de métrique par règle** dans `combat_utils.py` :
  `get_distance_metric(rule, game_config)` lit `game_config["distance_metric"][rule]`,
  **erreur explicite** si section/clé/valeur manquante ou invalide (aucun fallback).
- **Fonction de portée unifiée** (le vrai point de bascule, à distinguer de la primitive) :
  `ranged_in_range(a, b, rng_subhex, metric)`. `hex` → `min_distance_between_sets(fp) <= rng_subhex`
  (actuel) ; `euclidean` → `euclidean_edge_distance(a, b) <= rng_subhex × 1.5`. La conversion
  `× 1.5` vit **ici seulement**, jamais dispersée aux call-sites.
- `distance_metric` ajouté à `game_config.json`, **tout à `"hex"`** par défaut.
- Aucun call-site rerouté : par défaut tout reste `hex`. On vérifie juste que la primitive,
  le sélecteur et la fonction de portée sont branchés et testables.
- **Checkpoint** : comportement identique à aujourd'hui (`--step` + PvP inchangés).

### Étape 2 — Migration TIR (risque faible)
**Portée mesurée bord-à-bord** (base-à-base au point le plus proche, règle 01.04),
**pas centre-à-centre.**
- **Scale acté** : `subhex → unités-norme = × 1.5` (`_FOOTPRINT_SIZE_SCALE` /
  `ENGAGEMENT_NORM_HEX_WIDTH`), la MÊME conversion que l'EZ
  (`engagement_minimum_clearance_norm`) et l'overlap — c'est ce qui garde
  portée = EZ = overlap = rendu frontend cohérents. **Pas √3** (√3 = pas hex réel,
  mais la convention maison est 1.5 = largeur horizontale, alignée sur le rendu).
  RNG est déjà en subhexes (RNG_pouces × `inches_to_subhex`, scalé au chargement
  dans `game_state.py`). Comparaison : `euclidean_edge_distance <= rng_subhex × 1.5`.
- **Router TOUS les call-sites de portée tir** via la fonction de portée unifiée
  `ranged_in_range` (sélecteur `ranged`), y compris les deux mesures footprint hex
  existantes : `min_distance_between_sets` en 800-840 **ET**
  `_build_weapon_availability_enemy_precheck` en 424-470 (source de
  `row["distance"]` lu en 620-660). Ne PAS en migrer une sans l'autre → sinon
  incohérence « arme disponible / cible refusée ».
- **Branche gym/non-gym** (`shooting_handlers.py` ~479-483) : le précheck mesure
  aujourd'hui centre-à-centre hex en gym (`_hex_dist`) et footprint hex en PvP.
  **Supprimer la branche gym** → le gym passe aussi par `ranged_in_range` (gratuit
  en perf : le rond↔rond est O(1)). Sinon training et PvP divergent encore plus.
- **`row["distance"]` int → float** : vérifier qu'aucun consommateur ne le traite
  comme entier (affichage/logs). La sélection « cible la plus proche » (4293-4310)
  **trie** par cette distance → migrer le tri **dans le même lot** que le seuil,
  jamais séparément.
- Passer la config `ranged: "euclidean"`.
- Frontend : miroir dans gameHelpers/probabilityCalculator/blinkingHPBar/
  weaponHelpers (même formule bord-à-bord, **même facteur `× 1.5`**, même absence
  d'arrondi que le backend).
- **Checkpoint** : une cible à portée en diagonale doit être atteignable en
  euclidien là où l'hex la refusait (et inversement) ; les deux checks (précheck
  620-660 et 800-840) restent cohérents. Valider PvP + replay.

### Étape 3 — Champ de distance géodésique any-angle (move/charge)
Nouvelle fonction backend (à côté du BFS existant, pas en remplacement direct).

> ⚠️ **RÈGLE CRITIQUE — « aucune partie du socle ne dépasse M » (Règle 03 Moving).**
> Aujourd'hui (BFS hex) le move est une **translation rigide** : à chaque pas toute
> l'empreinte se décale du même vecteur, donc **tout point du socle parcourt la même
> distance que l'ancre**. Mesurer le centre = mesurer n'importe quel point → la règle
> est respectée trivialement (aucun pivot possible), et les murs/angles sont gérés car
> `_placement_bad` re-teste l'empreinte entière contre les murs à chaque position.
>
> **Ce n'est plus vrai en euclidien any-angle.** Dès qu'un chemin **courbe** (typiquement
> en serrant un angle de mur), le **bord extérieur du socle parcourt un arc plus long que
> l'ancre**. Si le budget reste mesuré sur l'ancre/centre, on **sous-facture les moves
> collés aux angles** (la fig gagne ~½ diamètre à chaque coin) → violation directe de la
> règle 03.
>
> **À faire à l'Étape 3/4/5 :** le budget géodésique doit être testé sur le **point le
> plus éloigné du socle**, pas sur son centre. C'est le point de vigilance n°1 pour les
> mouvements autour des coins de murs.

**Algorithme retenu : lazy Theta\* en flood.**
- Propagation type Dijkstra sur le graphe hex, mais à chaque relaxation on tente
  de rattacher le nœud courant non pas à son voisin immédiat mais à l'**ancêtre
  du voisin** si la **ligne de vue est dégagée** entre eux → le coût cumulé est
  une **vraie distance euclidienne** (chemins à angle libre), pas une somme de
  pas hex à 60°.
- **Réutiliser le LoS WASM existant** (`wasm_los` / `hasLineOfSight`) comme test
  de visibilité ET comme source unique de la **règle de coin de mur** → garantit
  que backend et frontend appliquent exactement la même géométrie (résout le
  point de sync front-back). Ne PAS réimplémenter une règle de coin ad hoc.
- **Coins de murs (grazing)** : la règle de blocage est celle du LoS (un rayon
  qui passe par le point de contact de deux murs est bloqué) — à valider comme
  cohérente avec l'intuition « on ne se faufile pas entre deux murs jointifs ».
- Sortie = pour chaque hex candidate, sa distance géodésique au point de départ
  (un **champ** complet en une passe, pas une requête point-à-point).

**Spike de dé-risquage (à faire AVANT de brancher move/charge) :**
- Implémenter le champ sur une carte de test isolée (aucun branchement moteur).
- **Mesurer l'erreur aux coins** : distance produite vs plus court chemin vrai
  (visibility graph de référence) sur quelques configs concaves. Lazy Theta\*
  est quasi-optimal, pas exact → vérifier que la sur-estimation reste
  négligeable à l'échelle du jeu (< ~0.1").
- **Checkpoint** : sur une carte sans mur, la zone atteignable est un disque
  parfait ; avec un mur, elle le contourne proprement (pas de traversée d'angle) ;
  l'erreur mesurée aux coins est sous le seuil.

**Résultat du spike (FAIT — `spikes/geodesic_field_spike.py`) :**
- Champ lazy Theta\* validé : sans mur = disque euclidien exact (erreur 0.000) ;
  avec mur = contournement propre. **Aucune triche** : `champ ≥ ref` sur toutes
  les cibles → le champ ne traverse jamais un mur.
- Erreur vs visibility graph exact (sommets décalés vers l'extérieur) mesurée sur
  4 configs concaves (L, U/poche, couloir/chicane, angle serré) : **pire cas =
  0.86 subhex** (chicane à double contournement) = 0.17" sur ×5, 0.09" sur ×10.
- **Seuil exprimé en SUBHEX** (via `inches_to_subhex`), pas en pouces absolus :
  les positions sont quantifiées au subhex, donc < 1 subhex = sous la résolution
  de la grille sur tous les boards. 0.86 < 1 → OK. Marge à surveiller : des
  cartes à nombreux coins successifs cumulent l'erreur et pourraient l'approcher.
- **[3] budget sur le point le plus éloigné du socle : NON couvert par le spike**
  (champ mesuré depuis le centre) → à traiter au branchement moteur (Étapes 4/5),
  cf. la RÈGLE CRITIQUE en tête d'Étape 3. Point de vigilance n°1 aux coins.

### Étape 4 — Migration MOVE
- Brancher le champ géodésique sur `movement_handlers.py` (budget = MOVE).
- Overlap alliés inchangé (hex).
- Frontend : `getValidMovePositions` + BFS move de BoardReplay utilisent le
  nouveau champ (ou son miroir TS).
- **Checkpoint** : empreinte de déplacement ronde ; pas de chevauchement possible
  avec une fig alliée ; murs respectés. Valider PvP.

### Étape 5 — Migration CHARGE
- Brancher le champ géodésique sur `charge_handlers.py`
  (`_charge_bfs_max_distance`, `charge_build_valid_targets`).
- Overlap et contact ennemi inchangés (hex).
- Frontend : `charge_dest_distances`, `chargeMaxDistance`, BFS charge replay.
- **Checkpoint** : distance de charge ronde, contournement des murs, contact
  ennemi toujours validé en hex. Valider PvP.

### Étape 6 — Cohérence & nettoyage
- Vérifier qu'aucun call-site de portée tir/move/charge n'appelle encore
  directement `calculate_hex_distance` (grep de contrôle).
- Documenter la clé de config `distance_metric` (valeurs et effet par règle).
- Retrain IA (hors périmètre migration, mais à planifier juste après).

### Risques & points ouverts
- **Coins de murs** : principale source de bugs → tester en priorité.
- **Perf move/charge** : champ recalculé à chaque activation ; réutiliser le LoS
  WASM côté frontend ; profiler si plateau large.
- **Sync front/back** : la métrique doit donner le même résultat des deux côtés
  (mêmes règles de coin) sinon l'UI diverge du moteur → source d'incohérence
  d'affichage. Prévoir un mode de vérification croisée.
- **EZ hex + portée euclidienne** : cohabitation assumée pour l'instant ; à
  re-challenger si des incohérences de bord apparaissent (engagé vs à portée).
