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
| engine/ai/analyzer_phases/move_handler.py | 358-380 | calcul fly_distance | Hex cube | Move fly : distance droite |

## 7. BACKEND — Charge (charge phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/phase_handlers/charge_handlers.py | 565-630 | `_charge_bfs_max_distance()` | Pathfinding BFS | Distance max traversable |
| engine/phase_handlers/charge_handlers.py | ~630-670 | `_charge_skip_hex_lb_prune_round_round_engagement()` | **Euclidienne** round-round | Prune hexes trop loin |
| engine/phase_handlers/charge_handlers.py | 2398-2480 | `charge_build_valid_targets()` | Pathfinding ≤ charge_distance | Cibles valides |
| engine/ai/analyzer_phases/charge_handler.py | 75-110 | calcul charge_distance | Hex cube | IA : distance charge déclarée |
| engine/ai/game_replay_logger.py | 169-200 | distance_needed | Hex cube | Log : distance min requise |

## 8. BACKEND — Tir (shooting phase)

| Fichier | Ligne | Fonction | Métrique | Usage |
|---------|-------|----------|----------|-------|
| engine/phase_handlers/shooting_handlers.py | 620-660 | vérif `weapon_range` | Hex cube | Cible à portée arme |
| engine/phase_handlers/shooting_handlers.py | 800-840 | distance footprint↔footprint | `min_distance_between_sets()` | Empreintes ≤ RNG |
| engine/phase_handlers/shooting_handlers.py | 3150-3970 | distances shooter→target | Hex cube | Distance de tir (plusieurs points) |
| engine/phase_handlers/shooting_handlers.py | 4293-4310 | cible la plus proche | Hex cube | IA : sélection cible |
| engine/ai/analyzer_phases/shoot_handler.py | 406-610 | distances shooter→target | Hex cube | IA tir : validité/visée |
| engine/ai/target_selector.py | 198-210 | distance ally→target | Hex cube | IA : sélection cible |
| engine/engine/ai/weapon_selector.py | 383-400 | distance unit→target | Hex cube | IA arme : cible à portée |

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
- **IA** : retrain prévu de toute façon → l'impact sur observations/récompenses
  (section 10) est ignoré pendant la migration.
- **Positions** : les unités restent posées sur les centres d'hexagones. L'hex
  reste le système de coordonnées et d'occupation ; l'euclidien est une couche
  de calcul de portée par-dessus.
- **Move / charge** : distance max en euclidien via un **champ de distance
  géodésique any-angle** (contourne les murs) ; overlap alliés/ennemis reste hex.
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
- **Tir** : shooting_handlers.py (620-660, 800-840, 3150-3970, 4293-4310),
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
Fichier : [combat_utils.py](engine/combat_utils.py)
- Ajouter `calculate_euclidean_distance(a, b)` à côté de `calculate_hex_distance`.
- Introduire un **sélecteur de métrique par règle** (ex. lecture d'une clé de
  config `distance_metric` : `{ ranged: "euclidean", move: "euclidean",
  charge: "euclidean", engagement: "hex", overlap: "hex" }`).
- Aucune bascule effective encore : par défaut tout reste `hex`. On vérifie juste
  que le sélecteur est branché et testable.
- **Checkpoint** : comportement identique à aujourd'hui (métriques encore hex).

### Étape 2 — Migration TIR (risque faible)
- Remplacer les appels directs `calculate_hex_distance` de portée d'arme par le
  sélecteur (métrique `ranged`).
- Passer la config `ranged: "euclidean"`.
- Frontend : miroir dans gameHelpers/probabilityCalculator/blinkingHPBar.
- **Checkpoint** : une cible à portée en diagonale doit être atteignable en
  euclidien là où l'hex la refusait (et inversement). Valider PvP + replay.

### Étape 3 — Champ de distance géodésique any-angle (move/charge)
Nouvelle fonction backend (à côté du BFS existant, pas en remplacement direct).
- Propagation d'une distance euclidienne qui contourne les murs (Dijkstra à
  relaxation any-angle, type Theta\* en flood, ou fast marching).
- **Gestion explicite des coins de murs** (grazing) : interdire de "raser" un
  angle si les deux hexes adjacents au coin sont des murs.
- Sortie = pour chaque hex candidate, sa distance géodésique au point de départ.
- **Checkpoint** : sur une carte sans mur, la zone atteignable est un disque ;
  avec un mur, elle le contourne proprement (pas de traversée d'angle).

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
