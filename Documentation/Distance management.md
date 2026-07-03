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
   → **Acté à l'Étape 7 (2026-07-03)** : l'EZ passe euclidienne dans les 4 phases
   simultanément, via un point de bascule unique (`get_distance_metric("engagement")`).

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

### État d'avancement (2026-07-03)
- **Étape 0 — Inventaire** : ✅ FAIT (le présent document).
- **Étape 1 — Point de bascule unique (backend)** : ✅ FAIT. `euclidean_edge_distance`
  (hex_utils), `get_distance_metric` + `ranged_in_range` (combat_utils), section
  `distance_metric` dans game_config.json (tout `hex` par défaut).
- **Étape 2 — Migration TIR** : ✅ FAIT côté code (backend routé via
  `_ranged_distance_metric`, `ranged: "euclidean"`, miroir frontend
  `euclideanEdgeDistanceToCellSubhex` + `losPreviewHelpers`). ⚠️ Validation
  runtime PvP + replay non re-confirmée dans la dernière session.
- **Étape 3 — Spike champ géodésique** : ✅ FAIT et validé (voir « Résultat du
  spike » plus bas). Prototype isolé `spikes/geodesic_field_spike.py`, AUCUN
  branchement moteur.
- **Étape 4 — Migration MOVE** : ✅ FAIT (backend + PvP interactif), périmètre précis
  ci-dessous. Le point [3] budget-socle est résolu par l'**option A (Minkowski)**.
  **Tranche 4b traitée (2026-07-03)** : FLY (model pool + pool d'ancre squad), ground
  multi-hex du pool d'ancre (preview escouade), socles **non-ronds** (oval/square) dans les
  deux pools via empreinte discrète orientée. RESTE : miroir replay TS, branches legacy
  single-hex du pool d'ancre (X1 / `base_size==1`), gym (`move_gym=hex` par choix).
  Détail complet dans la section « Étape 4 » plus bas.
- **Étape 5 — Migration CHARGE** : ✅ FAIT et **entièrement soldée (2026-07-04)** — les 3 cas de
  validation restants sont couverts (multi-cibles V11 runtime OK, take-to-the-skies §20.12, coins de
  murs via 4.0-bis). Périmètre précis dans la section « Étape 5 » plus bas. Points clés : module partagé
  `geodesic_move.py` ; **deux** systèmes de reachability migrés (pool d'éligibilité/cibles ET
  `_compute_plan_context._bfs_reach` = la zone violette visible) ; pré-gate 12" euclidien **ligne droite**
  (pas géodésique) ; IA analyzer/replay restent hex (runs gym-hex). RESTE : miroir replay TS, unification
  du cache de champ entre pool et plan-context (C), branches legacy single-hex.
- **Étape 6 — Cohérence & nettoyage** : ⬜ À FAIRE.
- **Étape 7 — Migration EZ euclidienne** : ⬜ À FAIRE. **Décision révisée le 2026-07-03**
  (l'EZ ne reste PLUS hex — voir « Décisions actées » et la section « Étape 7 »).

### Décisions actées
- **Zone d'engagement (EZ)** : ~~NON touchée → reste hex partout~~ **DÉCISION RÉVISÉE
  (2026-07-03) → l'EZ bascule en EUCLIDIEN partout** (move, tir, charge, fight). Voir
  Étape 7. Motif : l'EZ est un concept UNIQUE consommé par 4 phases ; la garder hex
  pendant que move/charge passent euclidien recrée exactement l'incohérence inter-phase
  que le §18 (point de vigilance 2) anticipait (« engagé » côté move mais pas côté tir).
  Une seule métrique = une seule vérité, + fidélité au rayon d'engagement circulaire réel
  (l'hexagone d'EZ n'est qu'une approximation en escalier). **L'overlap/collision de socles
  reste hex** (couche d'occupation, orthogonale à l'EJ — cf. §22-24).
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
- **Métrique centre-à-centre vs bord-à-bord (2026-07-03, invariant vérifié)** : le
  **budget de déplacement** (move/charge) se mesure **centre-à-centre** (règle 03.01 :
  same-point-to-same-point ; en translation rigide = déplacement du centre) → seul
  `geodesic_field` (depuis le centre de l'ancre) le calcule. Toute distance **figurine ↔
  autre chose** (figurine, terrain, objectif) se mesure **bord-à-bord** (règle 01.04 :
  point le plus proche du socle) → `euclidean_edge_distance` / `ranged_edge_distance`.
  Invariant vérifié sur tout le code : `geodesic_field` = uniquement budget de move ;
  `euclidean_edge_distance` = uniquement portée/adjacence, jamais un budget de déplacement.
  ⚠️ Ne PAS mesurer un budget de move en bord-à-bord (donnerait ~1 diamètre de trop).
- **FLY (Règles 21.03) → euclidien (2026-07-03)** : FLY ignore murs/figurines → pas de
  pathfinding → le champ géodésique dégénère en **disque euclidien centre-à-centre** (obstacles
  vides). Fait dans le **model pool par-fig** (obstacles `set()`) ET dans le **pool d'ancre
  squad** (disque vectorisé NumPy centre-à-centre, gaté metric euclidean). Reste cube-distance
  en gym (`move_gym=hex`) et sur la branche single-hex legacy du pool d'ancre.
- **Socles non-ronds (oval/square) → euclidien (2026-07-03, Option 2 retenue)** : `geodesic_field`
  ne prend qu'une clearance scalaire (disque rond). Deux voies évaluées — (1) disque circonscrit
  (simple mais **perd l'orientation** → régression vs hex), (2) **inflation discrète de l'empreinte
  orientée** (obstacles dilatés par les offsets `off_even/off_odd`, puis `geodesic_field`
  clearance=0). **Option 2 retenue** : garde l'orientation, même fidélité que le hex + trajet
  any-angle. Appliquée aux **deux pools** (`_euclidean_move_field` unifie rond=clearance continue /
  non-rond=empreinte discrète). Le rond garde la clearance continue (option A Minkowski).
- **`base_size==1` legacy — PARKÉ (2026-07-03)** : suppression envisagée puis écartée. `base_size==1`
  est atteignable (curriculum X1 `inches_to_subhex=1`, et petites bases retombant à 1 sur ×5) →
  supprimer = abandonner le support X1. Non tranché → laissé en l'état, à re-challenger si X1 meurt.
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
| Adjacence & voisins (§3, §13) | Distance max de move / advance (§6) |
| Observations / récompenses IA (§10) | Distance max de charge (§7) |
| LoS (déjà euclidien §17) | **Zone d'engagement / EZ (§4) — Étape 7** (révision 2026-07-03) |
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
- **Call-sites IA ranged à migrer dans le même lot** (décisions actées : "Ranged → euclidien") :
  - `ai/target_selector.py` (198-210) — distance ally→target branche ranged
  - `engine/ai/weapon_selector.py` (383-400) — branche RNG (`select_best_ranged_weapon`)
  - `ai/analyzer_phases/shoot_handler.py` (406-610) — distances tir IA
  Ces trois fichiers doivent basculer **avec** le tir, pas séparément. Ne pas les oublier
  sous prétexte qu'ils sont dans `ai/` : la mesure de portée IA doit matcher la règle PvP.
- Frontend : miroir dans gameHelpers/probabilityCalculator/blinkingHPBar/
  weaponHelpers (même formule bord-à-bord, **même facteur `× 1.5`**, même absence
  d'arrondi que le backend).
- **Checkpoint** : une cible à portée en diagonale doit être atteignable en
  euclidien là où l'hex la refusait (et inversement) ; les deux checks (précheck
  620-660 et 800-840) restent cohérents ; les 3 fichiers IA produisent les mêmes
  distances que le moteur PvP. Valider PvP + replay.

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

### Étape 4 — Migration MOVE ✅ (état réel 2026-07-03)

**Budget-socle (point [3]) — OPTION A retenue (Minkowski).** En translation rigide,
tout point du socle parcourt la MÊME distance que le centre. Le vrai problème n'est pas
« le bord parcourt un arc plus long » mais que le centre d'un socle de rayon r ne peut pas
raser un coin (il reste à ≥ r). Solution : donner au test de segment une **clearance = rayon
du socle** (`round_base_radius_norm(base_size)`), i.e. gonfler les obstacles de r. Le champ
mesure alors le centre, et sa longueur borne exactement la distance de tout point du socle
(règle 03). Effet de jeu **assumé** : un socle rond ne peut plus se faufiler dans un passage
plus étroit que lui (plus strict que l'hex, plus correct physiquement). Décision utilisateur : A.

**4.0 — Primitive moteur (`engine/hex_utils.py`).**
- `geodesic_field(start, board_cols, board_rows, obstacles, budget, clearance)` : lazy Theta\*
  en flood porté du spike sur la géométrie moteur réelle (`_hex_center`, voisins `get_neighbors`).
  Résultat en unités-norme (1 subhex = `ENGAGEMENT_NORM_HEX_WIDTH` = 1,5). Sur-estime (quasi-optimal)
  → ne triche jamais (validé identique à un brute-force visibility sur scénarios concaves).
- `segment_clear` / `_segment_clear_indexed` : test capsule segment↔obstacles avec `clearance`.
  À `clearance=0` = LoS-ray (tangence coin convexe permise) ; `>0` = disque de rayon clearance.
- **Perf (critique)** : index spatial d'obstacles (buckets, obstacles inscrits dans 9 buckets →
  marge absorbée), parcours **DDA (Amanatides-Woo)** ne visitant que les buckets traversés, +
  **rejet rapide centre→segment** avant le test capsule. Cas réel mesuré : **1.12 s → 0.10 s** par
  champ (board ×10, ~3500 obstacles, socle base 6, budget 60 subhex).

**4.0-bis — Correctif grazing / squeeze de socle rond (2026-07-04).** Bug découvert en validant
« coins de murs multiples » (Étape 5) : la `clearance` n'était appliquée qu'au **raccourci any-angle**
(rattachement Theta\* à l'ancêtre). Le **pas adjacent** `cur→nb` (emprunté quand le raccourci LoS
échoue) était accepté **inconditionnellement**, sans test capsule → le flood se propageait cellule
par cellule à travers n'importe quel goulot ouvert. Conséquence : un socle rond de rayon r **passait
un goulot plus étroit que son diamètre** (le champ atteignait `nb` même si le socle y chevauche un
mur), contredisant l'effet « assumé » ci-dessus (Option A) et le commentaire *LIMITE ASSUMÉE* de
`geodesic_field` (« à `clearance>0` la grazing est gérée de fait »), qui était **inexact**.
Asymétrie : l'oval, lui, était déjà correct (obstacles dilatés par l'empreinte → cellules-ancre du
chemin bloquées). **Fix** (`geodesic_field`, branche `else` du rattachement) : quand le raccourci
ancêtre est bloqué, tester le pas adjacent `cur→nb` à la **capsule** ; si le socle y chevaucherait un
mur → `continue` (nb inatteignable via cur, re-proposé par un autre voisin). Un seul test couvre à la
fois le gate d'entrée de cellule (goulot) et le corner-cutting du pas adjacent, en réutilisant
`_segment_clear_indexed`. **Court-circuit `clearance<=0`** → no-op prouvé (oval/point/gym-hex), zéro
surcoût. Validé (moteur, déterministe, `scratchpad/validate_fix.py`) : `clearance=0` **strictement
identique** avant/après ; `clearance>0` ne fait que **retirer** des cellules (0 ajoutée = aucune
nouvelle sur-portée), 0 sur-blocage en terrain dégagé ; seuil rond = passe ssi goulot ≥ diamètre ;
FLY no-op (obstacles vides). Perf : rond **+24 %** (~15 ms/appel 220×300, absolu OK tour-par-tour),
`clearance=0` surcoût nul. Test visuel PvP OK (2026-07-04). Partagé **move + charge rond** (principe
miroir). Le commentaire *LIMITE ASSUMÉE* de [hex_utils.py] reste à réécrire (désormais garanti par le
gate de pas adjacent, plus « de fait »).

**4.1 — Branchement (`movement_handlers.py`, `config/game_config.json`).**
- Résolveur `_move_distance_metric(game_state)` : **PvP/replay → `distance_metric["move"]`**
  (= `euclidean`), **gym → `distance_metric["move_gym"]`** (= `hex` par défaut, 1 paramètre pour
  basculer le training). Erreurs explicites, aucun fallback.
- Branche euclidienne dans **`movement_build_valid_destinations_pool`** (pool d'ancre, ground) —
  gate socle **rond mono-hex** (`base_size == 1`) : ne se déclenche donc PAS sur board ×N (bases
  multi-subhex) → ce pool reste hex en pratique (voir 4b).
- Branche euclidienne dans **`movement_build_model_destinations_pool`** (pool par-figurine, **c'est
  lui que le PvP interactif utilise**) — gate socle **rond, toute taille** ; la reachability est
  calculée sur le CENTRE avec clearance = rayon socle, l'empreinte multi-hex est expansée séparément
  comme le BFS hex. **C'est cette branche qui rend le move euclidien visible en PvP.**
- Obstacles du champ = murs + (ennemis / amis / bande-EZ **selon les toggles** `config["move"]`,
  identique au BFS hex). `can_move_through_friendly_model=true` → les sœurs ne sont PAS obstacles →
  le champ est **indépendant du plan provisoire** → cacheable.
- **Cache** `_move_model_field_cache` (clé `(model_id, start, budget)`), vidé au phase start et
  après chaque commit réel (pas par les poses provisoires) → chaque champ calculé 1×/phase, poses
  suivantes instantanées. **Exclu de la sérialisation API** (`_GAME_STATE_EXCLUDE_KEYS`) — sinon le
  cache (dicts de milliers de cellules) gonfle chaque réponse (bug observé : previews à >1 s).
- `distance_metric` : `move: "euclidean"`, ajout `move_gym: "hex"`.

**Frontend (état).**
- **PvP = backend-driven** : la preview de move consomme `valid_move_destinations_pool` /
  le pool par-figurine (commentaire BoardPvp « use backend-computed destinations ») → euclidien
  déjà live, **aucun portage TS nécessaire pour le PvP**.
- `getValidMovePositions` (gameHelpers) : **aucun appelant prod** → rien à migrer.
- **Perf « apparition preview » single-fig** : mesurée côté moteur (< 0.16 s partout) ; le lag
  résiduel au 1er affichage est le **rendu PIXI de l'overlay LoS masqué** (`los-hover-polar-masked`,
  BoardPvp), **pré-existant, hors périmètre distance** → investigation frontend séparée si besoin.

**Tranche 4b — FAIT (2026-07-03) :**
- **FLY → euclidien** : model pool par-fig (obstacles `set()` → disque centre-à-centre) ET pool
  d'ancre squad (`_build_multi_hex_vectorized` : disque euclidien vectorisé si metric euclidean,
  cube-distance sinon). Voir « Décisions actées ».
- **Pool d'ancre ground multi-hex → euclidien** (preview escouade) : `movement_build_valid_destinations_pool`
  route le ground multi-hex vers `_euclidean_ground_anchor_multihex` (miroir du model pool : mêmes
  obstacles, mêmes 2 régimes EZ) quand metric euclidean. Le gym (`move_gym=hex`) garde le vectorisé hex.
- **Socles non-ronds (oval/square) → euclidien** dans les deux pools via **empreinte discrète orientée**
  (Option 2). `_euclidean_move_field` unifie rond (clearance continue) / non-rond (inflation empreinte,
  clearance=0). Fix `is_single_hex` du model pool (base_size liste = oval → multi-hex, empreinte expansée).
- Helpers ajoutés : `_inflate_obstacles_by_footprint`, `_euclidean_move_field`,
  `_euclidean_ground_anchor_multihex` (movement_handlers.py).
- **Perf à surveiller** : le pool d'ancre n'a PAS de cache de champ (le model pool si) → recalcul
  `geodesic_field` à chaque activation d'escouade ; et le chemin **éligibilité** (`read_only=True`)
  déclenche désormais un geodesic en PvP.

**RESTE — tranche 4b (⬜) :**
- Miroir **replay** : `BoardReplay.tsx` recalcule move/advance en hex localement → portage TS du
  champ (cosmétique, parties passées).
- Branches **single-hex legacy du pool d'ancre** (`ez<=1` X1 / `base_size==1`) : FLY encore
  cube-distance, ground encore hex — liées à la dette `base_size==1` parkée.
- **Checkpoint (fait pour le périmètre livré)** : disque qui contourne les murs, passage étroit
  fermé (clearance), pas d'overlap allié possible (filtre hex conservé), PvP fluide, squad rond/oval
  euclidien == par-fig.

### Étape 5 — Migration CHARGE ✅ (état réel 2026-07-03)

> ⚠️ **DÉCOUVERTE MAJEURE (ne pas re-rater) : la charge a DEUX systèmes de reachability
> distincts.** Le premier essai a migré le mauvais et n'a rien changé à l'affichage tout en
> plombant la perf. Les deux ont été migrés :
> 1. **`charge_build_valid_destinations_pool`** (pool d'ancre) → sert l'**éligibilité** (init
>    de phase, via `_has_valid_charge_target`) + la **liste de cibles** à l'activation
>    (`charge_build_valid_targets`).
> 2. **`_compute_plan_context._bfs_reach`** (BFS hex par-figurine) → sert la **zone violette
>    interactive dessinée à l'écran** (region_by_base, ~92 % du coût preview). **C'est lui
>    que voit le joueur.** Le pool (1) ne dessine RIEN d'interactif.

**Ordre réel (code PvP = règles 11.02, vérifié).** Le jet 2D6 a lieu **à l'activation**
(`charge` action, `charge_handlers.py:2580`), **AVANT** la désignation des cibles. Les cibles
sont ensuite bornées par la **distance jetée** (11.04 « within the maximum distance »), **pas
par 12"**. Le 12" n'est QUE le pré-gate d'éligibilité à déclarer (11.02.1). En gym (RL) le jet
est fait à la sélection (MDP inchangé).

**5.0 — Module partagé (`engine/phase_handlers/geodesic_move.py`).** `_euclidean_move_field` +
`_inflate_obstacles_by_footprint` extraits de `movement_handlers.py` (géométrie pure, deps =
hex_utils seul). Le **cache** de champ N'EST PAS mutualisé : les obstacles diffèrent (move =
murs+ennemis+amies+EZ ; charge = murs+ennemis seuls, traverse les amies, ignore l'EZ) → un
cache partagé clé `(model,start,budget)` collisionnerait entre phases. Chaque phase garde son
cache local ; seul le CALCUL est partagé.

**5.1 — Sélecteur (`_charge_distance_metric`).** PvP/replay → `distance_metric["charge"]`
(= `euclidean`), gym → `distance_metric["charge_gym"]` (= `hex`). Miroir de `_move_distance_metric`.

**5.2 — Pool euclidien (`charge_build_valid_destinations_pool`).** Branche euclidienne calquée
sur la branche FLY (itère les cellules du champ, rejoue la validation placement/overlap/engagement).
Budget = **`charge_range × NORM`** centre-à-centre (règle 03.01), **SANS** le `extra` hex de
`bfs_max_distance` (l'euclidien encapsule le décalage ancre↔bord via la clearance socle + le test
d'engagement empreinte→ennemi ; l'ajouter = sur-portée = triche). FLY = disque droit (déjà en place,
obstacles vides). **Préfiltre `near_enemy`** (une destination valide est forcément en EZ d'un ennemi)
→ évite les checks sur les dizaines de milliers de cellules du champ.

**5.3 — Pré-gate d'éligibilité 12" (`_has_valid_charge_target`).** = `ranged_in_range(..., "euclidean")`
bord-à-bord **EN LIGNE DROITE**, O(ennemis), **PAS de pathfinding/géodésique**. Raison actée : un
joueur peut donner `fly` à une unité en cours de phase → une mesure en ligne droite est fly-agnostique,
correcte (11.02.1 « within 12" »), et supprime le coût géodésique qui plombait l'init de phase. Le
pathfinding ne gouverne QUE l'aboutissement du move (post-jet, 11.04), jamais l'éligibilité. Gym/hex :
comportement pathfinding historique inchangé (gaté sur la métrique).

**5.A — Zone violette euclidienne (`_compute_plan_context._bfs_reach` → `_euclidean_reach`).** Champ
géodésique euclidien par-figurine (budget `roll_subhex × NORM`, disque droit FLY), même contrat
`(reach, dist)` que le BFS hex. **Cache de champ** `_charge_model_field_cache` clé
`(model, start, budget, fly, move_version)` → 1 géodésique/fig/phase, re-previews instantanés. Vidé au
start de phase (`charge_phase_start`), exclu de la sérialisation API (`_GAME_STATE_EXCLUDE_KEYS`).

**`_charge_skip_hex_lb_prune_round_round_engagement` (~630-670) :** confirmé **déjà compatible
euclidien** (désactive la prune hex pour round↔round) — non retouché.

**5.4 — IA analyzer / replay : restent HEX (décision révisée).** `ai/analyzer_phases/charge_handler.py`
et `ai/game_replay_logger.py` traitent le pipeline **gym/training/replay**, où la charge est **hex**
(`charge_gym`). Les migrer en euclidien mesurerait de l'euclidien sur des runs hex = incohérence
métrique. Le §5.4 initial (« migrer en euclidien ») était **faux** → ces deux fichiers restent hex,
la métrique suit le run analysé.

**Frontend :** PvP backend-driven (pool + plan-context) → aucun portage TS. `BoardReplay.tsx` BFS charge
→ reste hex (cosmétique, replay).

**Overlap et contact ennemi :** inchangés (hex).

**RESTE (⬜) :**
- **C (unification cache)** : `charge_build_valid_targets` relance un `geodesic_field` par activation
  (pool d'ancre) au lieu de réutiliser le cache par-figurine du plan-context. Atténué par le préfiltre
  `near_enemy`, mais un géodésique par activation subsiste. À unifier si la perf activation redevient un souci.
- **`dist_tgt` / `_dist_field`** (plan-context, filtre « must end closer to target » 11.04) : reste hex.
  Approximation mineure, orthogonale au disque de reachability euclidien.
- Miroir **replay** TS ; branches legacy single-hex (`base_size==1`/X1) ; gym (`charge_gym=hex`, par choix).

**Checkpoint (SOLDÉ 2026-07-04) :** init de phase rapide, activation rapide, zone violette euclidienne
(contourne les murs au sol, disque droit en vol). Validé runtime PvP. Les 3 cas « NON re-testés » ont
été couverts : coins de murs multiples (fix grazing 4.0-bis), **multi-cibles V11 (validé runtime PvP
2026-07-04)**, charge FLY déclarée / take-to-the-skies (vérifié code §20.12, −2" + traversée complets).
**Étape 5 entièrement close.**

### Étape 6 — Cohérence & nettoyage
- Vérifier qu'aucun call-site de portée tir/move/charge n'appelle encore
  directement `calculate_hex_distance` (grep de contrôle).
- Documenter la clé de config `distance_metric` (valeurs et effet par règle).
- Retrain IA (hors périmètre migration, mais à planifier juste après).

**Dette hex intentionnelle — ce qui reste hex PAR CHOIX après les Étapes 1-7 :**

| Règle | Raison du maintien hex |
|-------|------------------------|
| ~~FLY (21)~~ | ✅ Migré euclidien (2026-07-03, tranche 4b) — sauf branche single-hex legacy pool d'ancre |
| Pile-in / consolidation (12.03 / 12.08) | Budget 3" max, erreur ~10% jugée négligeable |
| Fall-back move (09.07) | Non planifié — ajouter à une Étape 8 |
| Cohérence inter-modèles (03.03) | Non planifié — ajouter à une Étape 8 |
| ~~Socles non-ronds (oval/square) move~~ | ✅ Migré euclidien (2026-07-03, Option 2 empreinte discrète) |
| ~~Pool d'ancre multi-hex (`ez>1`)~~ | ✅ Migré euclidien ground (2026-07-03) — sauf single-hex legacy `base_size==1`/X1 |
| ~~Charge (11.04) + éligibilité 12" (11.02)~~ | ✅ Migré euclidien (2026-07-03, Étape 5) — voir « Étape 5 » |
| IA analyzer/replay charge (`ai/analyzer_phases/charge_handler.py`, `ai/game_replay_logger.py`) | Restent hex : traitent des runs gym-hex → la métrique suit le run (décision Étape 5.4) |
| `dist_tgt` plan-context charge (filtre « closer to target » 11.04) | Reste hex, approximation mineure orthogonale au disque de reachability |
| Gym (`move_gym=hex`) | Choix : training reste hex (perf) — 1 param (`distance_metric.move_gym`) pour basculer |
| `base_size==1` / X1 (`inches_to_subhex=1`) legacy | Parké — suppression = abandon support X1 (curriculum) ; non tranché |
| Observations / récompenses IA (§10) | Retrain prévu de toute façon → ignoré pendant migration |
| Replay TS (BoardReplay.tsx) | Cosmétique, parties passées — faible priorité |

Tout ce qui n'est pas dans ce tableau et utilise encore hex après Étape 7 = **bug non documenté**.

### Étape 7 — Migration EZ euclidienne (⬜, décision 2026-07-03)

**But** : la zone d'engagement (EZ) passe euclidienne dans les **4 phases simultanément**
(move, tir, charge, fight), via un point de bascule unique. L'overlap/collision de socles
**reste hex** (couche d'occupation, orthogonale). Les observations/récompenses IA **restent
hex** (§10, retrain de toute façon prévu).

**Règle euclidienne unique.** Un socle mover en `(c,r)` est « en EZ » d'un ennemi ⇔
`euclidean_edge_distance(socle_mover, socle_ennemi) ≤ engagement_zone_subhex × ENGAGEMENT_NORM_HEX_WIDTH`
(= `engagement_minimum_clearance_norm(ez)`, DÉJÀ euclidien dans hex_utils.py:1378). Les briques
existent : `euclidean_edge_distance` / `euclidean_edge_clearance_round_round` (rond↔rond O(1)),
`engagement_minimum_clearance_norm`. **Le docstring de `move_anchor_violates_engagement_clearance`
(spatial_relations.py:165) vise déjà cette sémantique** — l'implémentation réelle est restée hex.

**Constat de départ (vérifié, ne pas re-supposer).** Aujourd'hui l'EZ est **hex partout** :
- `ez > 1` (board ×N) : `_compute_mover_ez_forbidden_mask` (movement_handlers.py:1186) fait une
  **dilatation hex cube-distance de rayon `ez`** des empreintes ennemies puis dilate par l'empreinte
  du mover (ligne 1277 « empreinte hex uniquement, jamais euclidien » — le docstring de la fonction
  est TROMPEUR, il annonce de l'euclidien non implémenté).
- `ez ≤ 1` (legacy) : cache `enemy_adjacent_hexes` (1-anneau hex, `build_enemy_adjacent_hexes`,
  shared_utils.py:1307).

**Point de bascule unique.** `get_distance_metric("engagement", game_config)` existe déjà
(`DISTANCE_METRIC_RULES` inclut `"engagement"`, config à `"hex"`). Étape 7 = router tous les
call-sites EZ via une fonction unifiée (type `in_engagement_zone(a, b, ez, metric)`) et passer
`engagement: "euclidean"`.

**Call-sites EZ à router (§4 de l'audit) :**
- `spatial_relations.py` : `enemy_footprint_distances` (41-66), `unit_entries_within_engagement_zone` /
  `unit_within_engagement_zone_footprints` (125-163), `move_anchor_violates_engagement_clearance` (165-210).
- `movement_handlers.py` : `_enemy_items_within_move_engagement_horizon` / `_movement_engagement_violates`
  (171-355), `_is_in_enemy_engagement_zone` (1123-1150), **`_compute_mover_ez_forbidden_mask` (1186)**,
  et le legacy `enemy_adjacent_hexes`.
- `shooting_handlers.py` : `_friendly_engagement_blocks_ranged_shot` (2051-2150),
  `_is_adjacent_to_enemy_within_cc_range` (5084-5115).
- `charge_handlers.py` : `_charge_unit_within_engagement_zone` (2993-3010).
- `fight_handlers.py` : `_fight_footprint_in_engagement_with_any_enemy` (973-1000).
- `shared_utils.py` : `build_enemy_adjacent_hexes` & co. (1307-1440) — remplacer/doubler par
  l'équivalent euclidien pour le cache d'EZ.

**Tranches proposées (checkpoint à chacune) :**

> ⚠️ **ORDRE RÉVISÉ** — `spatial_relations` doit être migré en **7.1** (pas en 7.5) car c'est
> la fondation commune consommée par les trois handlers (movement, charge, fight). Si elle est
> migrée en dernier, chaque handler doit porter sa propre logique EZ → risque de divergence entre
> couches et duplication. En la migrant en premier, les tranches 7.2–7.5 héritent de l'EZ via
> `spatial_relations` sans re-implémenter. `build_enemy_adjacent_hexes` (shared_utils, cross-phase)
> appartient à 7.0, pas à la tranche MOVE.

- **7.0** — Point de bascule : fonction unifiée `in_engagement_zone` (+ champ « forbidden EZ »
  euclidien vectorisé pour le move, réutilisant l'approche distance-field/DDA de l'Étape 4 pour la
  perf). **`build_enemy_adjacent_hexes` & co. (shared_utils.py:1307-1440) câblés ici** — cache
  cross-phase, pas spécifique au move. `engagement: "hex"` par défaut → comportement identique.
  Checkpoint : `--step` + PvP inchangés.
- **7.1 — spatial_relations** (fondation commune) : `enemy_footprint_distances` (41-66),
  `unit_entries_within_engagement_zone` / `unit_within_engagement_zone_footprints` (125-163),
  `move_anchor_violates_engagement_clearance` (165-210 — aligner l'implémentation sur son
  docstring). Checkpoint : `--step` inchangé (config encore hex).
- **7.2 — MOVE** : `_compute_mover_ez_forbidden_mask` + `_enemy_items_within_move_engagement_horizon`
  / `_movement_engagement_violates` (171-355) + `_is_in_enemy_engagement_zone` (1123-1150).
  Checkpoint : le « trou » d'EZ dans le disque de move devient un anneau rond (config encore hex
  → pas de changement visible, mais structure prête) ; IA == PvP.
- **7.3 — TIR** : `_friendly_engagement_blocks_ranged_shot` (2051-2150),
  `_is_adjacent_to_enemy_within_cc_range` (5084-5115). ⚠️ Vérifier également le check
  d'éligibilité **Close-Quarters Shooting (règle 10.06)** — conditionné à "Engaged" donc
  dépendant de l'EZ — et s'assurer qu'il passe par une des fonctions `spatial_relations`
  déjà câblées (sinon call-site manquant à ajouter ici).
- **7.4 — CHARGE** : `_charge_unit_within_engagement_zone` (2993-3010) (+ cohérence avec Étape 5).
- **7.5 — FIGHT** : `_fight_footprint_in_engagement_with_any_enemy` (973-1000).
- **7.6** — Config `engagement: "euclidean"`, miroir frontend (anneau d'engagement preview :
  `getFightEngagementRingBoardPixels` etc. déjà en unités-norme — ⚠️ la divergence visuelle
  frontend/moteur pré-7.6 est **assumée** : l'anneau affiché est euclidien pendant que le moteur
  est encore hex ; ne pas confondre avec un bug), **retrain IA**.

**Vigilances Étape 7 :**
- **États dérivés de l'EZ** : éligibilité fight, `flee`/fall-back, tir-si-engagé, Desperate Escape,
  battle-shock — l'EZ euclidienne change la détection d'« engagé » → valider qu'aucune de ces règles
  ne casse (ni resté-engagé fantôme, ni désengagement indu).
- **Overlap reste hex** : ne toucher AUCUN call-site d'overlap (§5, §15).
- **Perf** : le masque « forbidden EZ » sur tout le board doit être vectorisé/efficace (disque
  euclidien autour des socles ennemis), pas un test O(cellules × ennemis) naïf.
- **Sync front/back** : l'anneau d'EZ affiché doit matcher la géométrie moteur (même `× 1.5`).

### Risques & points ouverts
- **Coins de murs** : principale source de bugs → tester en priorité.
- **Perf move/charge** : champ recalculé à chaque activation ; réutiliser le LoS
  WASM côté frontend ; profiler si plateau large.
- **Sync front/back** : la métrique doit donner le même résultat des deux côtés
  (mêmes règles de coin) sinon l'UI diverge du moteur → source d'incohérence
  d'affichage. Prévoir un mode de vérification croisée.
- **EZ hex + portée euclidienne** : cohabitation assumée pour l'instant ; à
  re-challenger si des incohérences de bord apparaissent (engagé vs à portée).

---

## 21. Mise à niveau — ratés des Étapes 1-4 (2026-07-03)

> Les Étapes 1 à 4 sont considérées comme terminées. Ce paragraphe liste ce qui
> **aurait dû être fait** dans ces étapes mais ne l'a pas été. À traiter avant
> d'entamer l'Étape 5, sous peine de dettes cachées qui s'accumulent.

### 21.1 — Étape 2 (TIR) : ✅ DÉJÀ FAIT (vérifié 2026-07-03)

Vérification exhaustive des 3 fichiers après rédaction initiale de ce §21 :

| Fichier | Call-site | État |
|---------|-----------|------|
| `ai/target_selector.py` | :202 `ranged_edge_distance(..., metric="ranged")` | ✅ migré |
| `engine/ai/weapon_selector.py` | :390 `ranged_edge_distance(..., metric="ranged")` | ✅ migré |
| `ai/analyzer_phases/shoot_handler.py` | :459 + :631 `ranged_edge_distance(..., metric="ranged")` | ✅ migré |

Les `calculate_hex_distance` restants dans ces fichiers ne sont **pas** de la portée :
- `shoot_handler.py` :425/:491/:626 → test d'adjacence == 1 (pistolet), légitimement hex
- `weapon_selector.py` :389 → `perception_distance` (distance stratégique, reste hex par décision actée §18)
- `shoot_handler.py` :825 → distance d'advance FLY, relève de §21.2(A), pas du tir

**§21.1 soldé. Aucune action requise.**

### 21.2 — Étape 4 (MOVE) tranche 4b : ✅ TRAITÉE (2026-07-03)

| Item | État |
|------|------|
| **FLY** | ✅ Euclidien : model pool par-fig (disque centre-à-centre, obstacles vides) + pool d'ancre squad (disque vectorisé euclidien si metric euclidean). Reste cube-distance sur la branche single-hex legacy du pool d'ancre. |
| **Pool d'ancre multi-hex ground** | ✅ Euclidien (`_euclidean_ground_anchor_multihex`, miroir du model pool). Gym/PvP : la bascule passe par `distance_metric.move` vs `move_gym` (pas de flag `move_anchor_gym` séparé — le sélecteur `_move_distance_metric` suffit). |
| **Socles non-ronds (oval/square)** | ✅ Euclidien via **empreinte discrète orientée** (Option 2), dans les deux pools. Plus de proxy cellules — l'orientation est conservée. |
| **Miroir replay (BoardReplay.tsx)** | ⬜ Reste hex (cosmétique, parties passées). |

**Décision `base_size==1`** : la suppression du legacy `base_size==1` (proposée en marge)
est **parkée** — atteignable via curriculum X1 (`inches_to_subhex=1`) et petites bases sur ×5 ;
supprimer = abandonner le support X1. Voir « Décisions actées ».

**§21.2 soldé** (hors replay TS + branches single-hex legacy). Prêt pour l'Étape 5.

---

## 20. Audit règles vs implémentation — points ouverts (2026-07-03)

Résultat d'une relecture exhaustive des PDFs de règles (01 Core concepts, 03 Moving,
11 Charge phase, 12 Fights phase) croisée avec ce document. Les points CORRECT
confirment des décisions bien fondées ; les points LACUNE sont des dettes à documenter
ou des bugs potentiels.

### 20.1 — Facteur × 1.5 : convention interne, PAS remplaceable par `inches_to_subhex`

La pipeline de conversion est à **deux étapes distinctes** :

```
pouces  ×  inches_to_subhex (ex. 10)  →  subhexes  ×  ENGAGEMENT_NORM_HEX_WIDTH (1.5)  →  unités _hex_center
```

- **`inches_to_subhex`** (board_config.json) = facteur d'échelle du plateau, variable
  (ex. 10 pour le board 44×60×10). Convertit des pouces en subhexes. **Ne pas remplacer.**
- **`ENGAGEMENT_NORM_HEX_WIDTH = 1.5`** = pas horizontal entre centres de colonnes dans le
  repère `_hex_center` (`hex_width = 1.5 × hex_radius`), fixé par la géométrie flat-top.
  Défini dans `hex_utils.py:1344`.

**Pourquoi 1.5 et non √3 ?** La distance euclidienne entre deux centres de cases
adjacentes est √3 ≈ 1.732 (valeur `hex_height`). Mais le pas horizontal de colonne à
colonne est 1.5 (`hex_width`). Toutes les primitives du moteur
(`_FOOTPRINT_SIZE_SCALE`, `round_base_radius_norm`, `engagement_minimum_clearance_norm`,
`geodesic_field`) utilisent 1.5 → le système est **cohérent en interne**. C'est une
convention délibérée alignée sur le rendu frontend, non une erreur.
**À ne pas "corriger"** ; à documenter comme convention maison (pas √3).

### 20.2 — CORRECT : mesure bord-à-bord (règle 01.04)

Règle 01.04 : *"measure to or from the **closest part of that model's base**"*.
L'abandon du centre-à-centre est **obligatoire**. `euclidean_edge_distance` est
la bonne primitive.

### 20.3 — CORRECT : EZ = 2" euclidien (règle 03.04)

Règle 03.04 : *"within 2" horizontally and 5" vertically"*, mesuré depuis la partie la
plus proche du socle (01.04). L'EZ est un disque euclidien de 2" bord-à-bord. La
décision d'Étape 7 (EZ euclidienne partout simultanément) est **architecturalement
obligatoire**, pas juste souhaitable.

### 20.4 — CORRECT : budget de move = cumul de segments (règle 03.01)

Règle 03.01 : *"Measure from the **same point on its base** at the start and end of
that move, and **add that distance** to any other distance it has moved."* La distance
est un cumul de longueurs de segments (path length), pas un déplacement net centre→centre.
Le champ géodésique = longueur minimale du chemin = bonne primitive.

### 20.5 — CORRECT : Minkowski clearance = rayon du socle (règle 03.01)

Règle 03.01 : *"It can be moved through any space its base can fit through."*
Gonfler les obstacles du rayon du socle (option A) est la traduction exacte de
cette contrainte physique.

### 20.6 — ✅ RÉSOLU (2026-07-03) : FLY migré euclidien

FLY ignore le terrain (règles 21) → pas de pathfinding → **disque euclidien centre-à-centre**
(champ géodésique à obstacles vides). Fait dans model pool + pool d'ancre squad.
⚠️ **Correction de terminologie** : le budget de move FLY est **centre-à-centre** (règle 03.01,
same-point), PAS bord-à-bord comme l'écrivait la rédaction initiale — le bord-à-bord (01.04) est
réservé aux distances figurine↔autre chose (portée/adjacence). Voir « Décisions actées ».

### 20.7 — LACUNE : Pile-in (12.03) et consolidation (12.08) restent en hex

Ces deux move types appellent *"Your unit moves as described in Moving (03)"* — mêmes
règles de distance que le move normal → devraient être euclidiens. À 3" max, l'erreur
hex vs euclidien est ~10-15% dans les diagonales. Déféré intentionnellement pour
l'instant ; à acter comme dette technique explicite plutôt que de l'ignorer.

### 20.8 — LACUNE : Deux checks distincts dans la charge (11.02 vs 11.04)

- **Check d'éligibilité à la déclaration (11.02)** : *"It is not within 12" of one or
  more enemy units"* → mesure euclidienne bord-à-bord (01.04), ligne droite.
- **Budget du charge move (11.04)** : distance max = jet 2D6, mesurée selon 03.01
  (cumul de segments) → géodésique.

Ces deux checks ont des **métriques différentes**. Cas concret où elles divergent :
unité à 11" en euclidien mais à 13" en géodésique (couloir de murs) → éligible à
déclarer une charge, mais charge ratée à l'exécution. C'est règle-correct (charge
ratée légitime), mais le code doit distinguer les deux checks, pas les fusionner dans
`charge_build_valid_targets`. À vérifier à l'Étape 5.

✅ **RÉSOLU (Étape 5, 2026-07-03).** Pré-gate d'éligibilité (`_has_valid_charge_target`) =
euclidien **ligne droite** (`ranged_in_range`, O(ennemis)), séparé du budget géodésique (pool
`charge_build_valid_destinations_pool` au jet). Précision de l'ordre : le jet a lieu à
l'activation AVANT la désignation des cibles ; les cibles sont bornées par **le jet**, pas par
12". Le 12" n'est que le pré-gate d'éligibilité. Décision : le pré-gate reste **ligne droite**
(pas géodésique) car un `fly` peut être accordé en cours de phase → mesure fly-agnostique.

### 20.9 — LACUNE : Cohérence (03.03) non mentionnée dans le plan

Règle 03.03 : *"Within 2" horizontally [...] of at least one other model in that unit"*
— mesure bord-à-bord euclidienne (01.04). La cohérence est actuellement en hex.
L'erreur à 2" est ~10% dans les diagonales. Non bloquant, mais à acter comme dette.

### 20.10 — LACUNE : Fall-back move (09.07) absent du plan

Move type soumis aux mêmes règles de distance (03.01). Non mentionné dans le plan de
migration. Même logique que le normal move — à ajouter à l'Étape 5 ou 6.

### 20.11 — LACUNE : Docstring trompeur de `move_anchor_violates_engagement_clearance`

`spatial_relations.py:165` — le docstring annonce de l'euclidien ; l'implémentation
réelle est hex (§4 de l'audit, ligne 537). Risque de maintenance : un développeur peut
croire la fonction déjà migrée. Corriger le docstring à l'Étape 7.0 (avant le code).
**Mise à jour (2026-07-04)** : le docstring réel est désormais neutre
(`"...C/clearance engagement contract"`, `spatial_relations.py:176`) — plus de mention
euclidienne trompeuse. Implémentation toujours hex. Micro-tâche du 7.0 déjà partiellement
faite ; reste à aligner l'implémentation sur la sémantique euclidienne à l'Étape 7.1.

### 20.12 — ✅ CORRECT (vérifié 2026-07-04) : Take to the skies en CHARGE (21.03) complet

Règle 21.03 : une unité FLYING peut déclarer `take to the skies` avant un charge move →
`−2"` sur la distance max **et** traversée libre (murs + figurines + ignore vertical).
Vérification exhaustive du code (charge) :
- **−2"** : `_charge_budget_subhex` (charge_handlers.py:90) = `jet × inches_to_subhex − 2×inches_to_subhex`
  si vol déclaré. **Source unique** des 5 sites de calcul de distance de charge (pool euclidien,
  cibles, BFS) → le malus se propage dans le budget du champ géodésique euclidien. Aucun site oublié.
- **Traversée** : `_charge_fly_active` (charge_handlers.py:65) = source unique des 4 BFS/champs ;
  vol actif → obstacles vides (disque droit), sinon obstacles normaux.
- **Vertical** : N/A (grille hex 2D horizontale, vertical non modélisé).
- **Optionnel/cohérent** : sans déclaration → 2D6 plein + pas de traversée ; avec → −2" + traversée
  (les deux gouvernés par la même déclaration `units_took_to_skies_charge`, set dédié charge).
- **IA** ne déclare jamais (charge IA inchangée, pas de régression training).
- **Éligibilité généreuse** (`for_eligibility=True`) : propose la charge si atteignable par les airs
  avant déclaration — règle-correct (le pré-gate est le 12" ligne droite ; charge ratée légitime 11.04).

**Aucune action requise.** Point rattaché à l'Étape 5 (charge FLY déclarée = un des cas « NON re-testés
exhaustivement » du checkpoint Étape 5, désormais couvert côté code).
