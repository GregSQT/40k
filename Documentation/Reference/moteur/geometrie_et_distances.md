# Géométrie et distances — plateau odd-q, résolutions, empreintes, métriques

**Objet :** référence unique de la géométrie du moteur — système de coordonnées odd-q, résolutions de plateau et conversion inches→subhex, empreintes de socles, métriques de distance (hex vs euclidien) côté backend et frontend, et contrat « hors table = hors géométrie ».
**Sources absorbées** (destinées à `Documentation/Archives/docs/` avec bandeau retour) : `Boardx10-final.md`, `V11_board_44x60x1.md`, `Distance management.md`, `compute_footprint_placement_mask.md`, `1_unites_hors_table_chemins_geometriques.md`.
**L'état des chantiers fait foi dans [Documentation/Roadmap/](../../Roadmap/ROADMAP_INDEX.md), jamais ici.**
Les chiffres volatils (obs_size, tailles d'espaces, comptes de tests, win-rates) ne sont pas recopiés : chaque fois, le document dit où les lire.

---

## 1. Le plateau

### 1.1 Coordonnées : offset odd-q (figé)

Pavage hexagonal **pointy-top**, coordonnées **offset odd-q** : `(col, row)` avec `0 ≤ col < COLS`, `0 ≤ row < ROWS` ; les colonnes **impaires** (`col % 2 == 1`) sont décalées de **+½ rangée vers le bas**. C'est le système de tout le moteur ([engine/hex_utils.py](../../../engine/hex_utils.py), en-tête « single source of truth ») et du frontend.

Norme physique de la micro-maille (P1, décision produit ×10) : distance **plat à plat** d'une cellule = **0,1″** à `inches_to_subhex = 10` — d'où l'intuition « ~10 cellules ≈ 1″ de largeur ». Le moteur ne manipule que des **entiers** sur la grille ; le 0,1″ est un brief physique, pas un flottant injecté.

L'approche A (grille 10×10 logique par hex inch) a été **rejetée** ; le plateau ×N est un plateau neuf, pas une subdivision de macro-hex. `COLS`/`ROWS` sont des **paramètres** de `board_config.json`, jamais codés en dur.

### 1.2 Résolutions et plateaux

La table résolution → dossier est **unique** : `BOARD_DIR_BY_INCHES_TO_SUBHEX` dans [config_loader.py](../../../config_loader.py). Un appelant qui reconstruit un nom de dossier à la main diverge au premier plateau ajouté. Le plateau actif vient de `W40K_BOARD_PATH` (ou `--resolution` de `ai/train.py`, qui lit cette table).

| Dossier | cols × rows | `inches_to_subhex` | Plateau physique |
|---|---|---|---|
| `config/board/44x60x1` | 44 × 60 | 1 | 44″ × 60″ — banc rapide, 1 hex = 1 pouce |
| `config/board/44x60x5` | 220 × 300 | 5 | 44″ × 60″ — résolution de référence |
| `config/board/44x60x10` | 360 × 312 | 10 | **36″ × 31,2″** — plateau physiquement différent malgré le nom du dossier |

Chaque `board_config.json` porte (section `default`) : `cols`, `rows`, `inches_to_subhex`, `hex_radius`, `margin`, `chunk_size`, `hex_orientations`. Valeurs à lire dans le fichier, pas ici.

L'ancien board `25x21` (25″×21″, un **autre** plateau physique) est supprimé, avec ses annexes (`config/deployment/25x21`, `config/primary_objective/25x21`) et le mode tutoriel entier. Y jouer un scénario 44×60 faussait toute la géométrie tactique (portées de 24″ sur un plateau de 25″ de large). Les topologies précalculées `.npz` (`los_topology`, `pathfinding_topology`, `wall_edge_topology`) et leur builder sont supprimés : plus rien ne pouvait les alimenter, les chemins **à la demande** sont les seuls (voir §4.12 et §2.3).

### 1.3 Conversion inches → subhex (§P3) — raisonner en subhex

**Approche retenue : conversion au chargement.** Les fichiers de données (rosters, armories, `game_config.json`) restent en **inches** (standard GW, lisible). Le moteur convertit **une seule fois** au chargement, par le facteur `inches_to_subhex` du `board_config.json` :

- `def create_unit` ([engine/game_state.py](../../../engine/game_state.py)) : `MOVE`, `weapon.RNG` × scale (via `def _get_inches_to_subhex`) ;
- init de `engine/w40k_core.py` : distances de `game_rules` × scale (dont `engagement_zone`), et `charge.charge_max_distance` × scale ;
- `engine/observation_builder.py` : normalisations RL mises à l'échelle par `inches_to_subhex`.

Toute **validation d'action** compare des **entiers subhex** ; l'affichage en pouces est une **vue dérivée**, jamais une seconde source de vérité. Les seuils et conversions passent par `inches_to_subhex` — raisonner en subhex, pas en pouces absolus.

Clés de distances dans [config/game_config.json](../../../config/game_config.json), en inches, converties au chargement :

| Clé | Section | Rôle |
|---|---|---|
| `engagement_zone` | `game_rules` | périmètre d'engagement autour de l'empreinte — **2″ depuis le 2026-06-03** (1″ auparavant ; ce changement a une conséquence architecturale, voir §4.5). Régit aussi le corps à corps : il n'existe **pas** de clé `melee_range` séparée, les handlers lisent `def get_engagement_zone` (`engine/spatial_relations.py`) |
| `engagement_zone_vertical` | `game_rules` | composante verticale 5″ (03.04) |
| `charge_max_distance` | `charge` | pré-gate d'éligibilité 12″ (11.02) |
| `advance_distance_range` | `game_rules` | budget d'advance |
| `max_search_distance` | `game_rules` | rayon max de recherche |
| `avg_charge_roll` | `game_rules` | moyenne du jet de charge |
| `detection_range` | `game_rules` | détection des unités cachées 13.09 |
| `unit_model_cohesion_range` | `game_rules` | cohérence d'escouade 03.03 (voir §4.8) |

**§P3, contrat cité par le code** (`ai/analyzer.py`) : **le budget d'advance = face de D6 × scale** (`inches_to_subhex`). Plus généralement, toute constante de règle vit en pouces dans les données et en subhex dans le moteur.

### 1.4 Le banc x1 : géométrie hex pure

`44x60x1` est le même plateau physique que `44x60x5` à 1 hex = 1 pouce : mêmes distances en pouces, mêmes portées relatives, ~5× plus rapide au step moteur (mesuré). Son but est de mesurer une **tendance** d'entraînement (KL, entropie, explained variance, value loss) en quelques heures ; le modèle produit est jetable.

Ce que x1 **ne mesure pas** : `inches_to_subhex = 1` ⇒ une figurine occupe UN hex, pas d'empreinte (`is_micro_board` faux dans `def create_unit`) — pile-in/consolidation par figurine, occlusion partielle et engagement au socle ne sont pas exercés. Le win-rate absolu ne se transpose pas ; la tendance si. L'observation est invariante en résolution (grille égocentrique, distances normalisées par `inches_to_subhex` — géométrie dans `engine/spatial_grid.py` : `GRID_SIZE`, `GRID_CHANNELS`).

**Règle actée (2026-07-29) : à x1, TOUT est hex.** `def geometry_is_hex` ([engine/spatial_relations.py](../../../engine/spatial_relations.py)) est le **seul** juge de la résolution — critère unique `inches_to_subhex`, **jamais** `ez`. Les quatre sélecteurs de métrique le consultent (§4.5). Détail du piège historique qui a imposé ce point de bascule : §4.5.

### 1.5 Contraintes de complexité (héritées du chantier ×10)

Invariants tenus par l'architecture actuelle, à ne pas ré-enfreindre :

- **aucune structure Ω(n²) globale** (n = cellules) : ni matrice LoS ni matrice pathfinding « toutes paires » (à 52 500 cellules, n² ≈ 2,76 Go — c'est ce qui a tué les topologies denses) ;
- LoS **à la demande**, O(L) par requête (L borné par la portée) ; pathfinding **borné** (fenêtre locale, budgets) ;
- obstacles et occupation **sparse** (sets, caches par phase) ;
- RL : **macro-actions** (la policy choisit une destination, le moteur exécute le chemin — jamais un step PPO par sous-hex), observation **bornée** (tenseurs d'entités + grille égocentrique, jamais un tenseur COLS×ROWS×C), masques **O(k)** jamais O(n), normalisations par échelles **fixes** ;
- un changement d'échelle de plateau invalide les checkpoints existants ;
- ordre d'attaque perf éprouvé : algorithmes/caches/budgets → parallélisme d'envs → curriculum → JIT/vectorisation → GPU (le goulot est presque toujours `env.step`, pas le réseau).

---

## 2. Primitives hex odd-q (Boardx10-final §2.2 et §2.3)

**Source de vérité unique : [engine/hex_utils.py](../../../engine/hex_utils.py)** — son en-tête cite ces deux sections. Bornes, voisins, distance, conversions vivent dans **un seul module** ; toute primitive dupliquée ailleurs est un bug. Voisinages et conversions sont **O(1)** ; aucun fallback silencieux hors plage ; les bords du plateau sont couverts par tests (`tests/unit/engine/test_hex_utils.py`).

### 2.1 Voisinage (§2.2)

6 voisins, dépendants de la **parité de colonne** (`def get_neighbors`, `def get_neighbors_bounded` ; côté données : `_NEIGHBORS_EVEN_COL`/impair) :

Colonne **paire** (`col % 2 == 0`) :

| Direction | Δcol | Δrow |
|-----------|------|------|
| N | 0 | −1 |
| NE | +1 | −1 |
| SE | +1 | 0 |
| S | 0 | +1 |
| SO | −1 | 0 |
| NO | −1 | −1 |

Colonne **impaire** (`col % 2 == 1`) :

| Direction | Δcol | Δrow |
|-----------|------|------|
| N | 0 | −1 |
| NE | +1 | 0 |
| SE | +1 | +1 |
| S | 0 | +1 |
| SO | −1 | +1 |
| NO | −1 | 0 |

Miroir frontend : `getAdjacentPositions` ([frontend/src/utils/gameHelpers.ts](../../../frontend/src/utils/gameHelpers.ts)), `getHexNeighbors` (BoardReplay).

### 2.2 Distance hex : offset → cube (§2.2)

Conversion offset odd-q → cube puis `distance = max(|Δx|, |Δy|, |Δz|)` :

```
x = col
z = row - (col - (col & 1)) / 2
y = -x - z
```

Implémentations : `def hex_distance` et `def offset_to_cube` / `def cube_to_offset` (hex_utils) ; `def calculate_hex_distance` ([engine/combat_utils.py](../../../engine/combat_utils.py)) — **distance en ligne droite, ignore les murs**. Le moteur n'a **plus** de fonction générique de distance de pathfinding : `calculate_pathfinding_distance` et son champ BFS ont été supprimés le 2026-07-28, faute d'appelant (la docstring de `calculate_hex_distance` en garde trace). Les BFS restants sont ceux des **pools** de move/charge (§4.4, §4.7). Miroir frontend : `cubeDistance` / `getHexDistance` (gameHelpers.ts), `wasm_hex_distance` (`frontend/src/wasm-los-pkg/wasm_los.d.ts`).

**Distance entre unités (normatif, §3.3 historique)** : la distance de règle entre deux unités est la distance hex **minimale entre empreintes** — `def min_distance_between_sets` (hex_utils), qui lève sur ensemble vide (voir §5) et porte un paramètre `max_distance` : résultat garanti exact seulement tant qu'il est `≤ max_distance`, au-delà un minorant strictement supérieur est rendu — suffisant pour les tests de seuil, et c'est le contrat jumeau de `euclidean_edge_distance` (§4.2). À 1 hex = 1 unité, elle coïncide avec la distance entre centres.

**Protocole (issu de l'audit « 1 hex = 1 unité », normatif)** : toute distance servant à une **décision de règle** (portée, engagement, fight) se mesure entre **empreintes** (`min_distance_between_sets`, ou primitive euclidienne §4.2) ; la distance centre-à-centre n'est légitime que pour les **heuristiques pures** sans impact gameplay (tri approximatif, budget BFS, prune conservatrice).

### 2.3 Tracés, bornes, murs (§2.3)

- `def is_in_bounds`, `def is_phantom_bottom_hex` / `def phantom_bottom_hexes` (cellules fantômes du bas de grille) ;
- `def hex_line`, `def hex_line_iter` (grid traversal — sert aussi la LoS à la demande §4.12 et la rasterisation des murs) ;
- `def build_wall_set` / `def build_dense_wall_set` ; `def expand_wall_group_to_hex_list` ;
- objectifs : `def expand_objectives_to_hex_list` et les `_objective_*_hexes` (les sommets de polygone sont des **indices de cellule**, projetés par `def _hex_projected` avant test d'appartenance) ;
- dilatations : `def dilate_hex_set`, `def dilate_hex_set_unbounded` (zone d'engagement hex), noyaux `dilate_by_kernel`/`erode_by_kernel`.

**Biais de départage des segments horizontaux — à lire avant d'écrire des murs de terrain**

`hex_line_iter` applique un nudge constant ``(+1e-6, +1e-6, -2e-6)`` aux coordonnées cube des deux extrémités pour rompre les égalités exactes. Sur un **segment horizontal** (row constant), ce nudge fait que la comparaison `dz > dy` alterne selon la parité de colonne : la rangée rasterisée est `R` pour certaines colonnes et `R − 1` pour les autres. Résultat observable : un mur déclaré à `row = R` bloque la LoS sur `row = R − 1` pour les colonnes de parité opposée à l'extrémité — la ligne bloquante effective se situe **une demi-case au-dessus** de la ligne écrite, sur les colonnes de parité alternante.

Exemples vérifiés : `[[132,123],[126,123]]` et `[[88,123],[108,123]]` rasterisent en rangées alternant entre 123 et 122, dans les deux sens de parcours.

Ce biais est **partagé bit-à-bit** par `hex_line_iter_t` (LoS 3D plancher-occulteur) et par `batch_hex_line_steps` (LoS vectorisée) — le nudge ne doit jamais être modifié sans propager la modification aux deux miroirs. Il n'est **pas corrigé** : il sert à résoudre les égalités exactes de façon déterministe et symétrique en translation.

### 2.4 Changement de résolution : `downscale_cell` et conversion au chargement

`board_ref` déclare la résolution **native** des fichiers partagés d'un scénario (murs, terrain, positions de roster). Quand le plateau actif est plus **grossier**, `engine/game_state.py` convertit **à la lecture** — aucune donnée dupliquée par résolution (une copie divergerait en silence au premier changement) :

- `def _board_ref_downscale_ratio` — rapport `ish_source / ish_actif`, lu dans les deux `board_config.json`. Rapport non entier, ou plateaux qui ne se correspondent pas après réduction ⇒ **erreur explicite** (jamais d'approximation) ; la conversion ne va que vers le **plus grossier** — remonter en résolution demanderait d'inventer de l'information, et échoue explicitement. Résolutions identiques ⇒ rapport 1, PvP et x5 strictement inchangés.
- `def downscale_cell` (hex_utils) — la conversion d'une coordonnée. **Diviser col et row séparément est faux** en odd-q (le décalage de demi-hauteur des colonnes impaires est ignoré — mesuré sur `terrain-mc1` : 28 % des points déplacés d'une case). La conversion projette le centre (`def _hex_projected`) et retient la cellule grossière au centre le plus proche.
- `def _downscale_terrain_data` — convertit exactement les champs de coordonnées (`terrain[].vertices`, `floors[].vertices`, `walls[].segments`, `walls[].hexes`, `deployment_zones[].vertices`, `icons[].center`) ; `height_inches` reste en pouces. Trois entrées converties : `def _read_terrain_file`, les murs partagés (`wall_ref`, convertis **avant** rasterisation par `hex_line` — réduire des hexes déjà rasterisés donnerait une ligne à trous), et les `wall_hexes` inline. Condition d'applicabilité : le scénario **déclare** sa résolution d'origine — `board_ref` ou appartenance à `config/board/<board>/scenario/` (`def _has_declared_source_board`, prédicat unique). Le rapport fait partie de la clé du cache de murs (`W40K_BOARD_PATH` change par requête côté API PvP) ; le `board_config.json` source est mémoïsé sur `(chemin, mtime_ns)`.
- `def _downscale_fixed_unit` — positions de roster. Réduire chaque figurine séparément écraserait une escouade sur une case (espacements x5 < 1 hex après ÷5) : chaque figurine va sur sa case réduite si libre, sinon la case libre la plus proche dans un rayon borné par `unit_model_cohesion_range` (03.03) ; aucune case libre ⇒ erreur explicite. Contrats : invariant **ancre == `models[0]`** (dont dépend `def build_units_cache`) ; retour par **copie** (les scénarios sont mémoïsés) ; **refus explicite** si le plateau cible a `inches_to_subhex > 1` (le placement converti raisonne par case ; sur un plateau à empreintes il laisserait deux socles se chevaucher — cas atteint par aucune paire de plateaux du dépôt).

Côté API : `BOARD_PATH_MAP` (plateau **joué**) est distinct de `TEST_SCENARIO_BOARD_MAP` (dossier qui **porte** les scénarios de test, x5) dans `services/api_server.py` ; le moteur convertit. `/api/config/board` lit murs/terrain **à la source** et convertit avec la même fonction que le moteur, en refaisant ses deux contrôles (rapport entier, dimensions correspondantes).

Verrous : `tests/unit/engine/test_board_downscale.py` (oracle géométrique indépendant, refus de plateau physiquement différent, source non mutée, rosters — dont cohérence 03.03 et non-chevauchement), `tests/unit/engine/test_roster_downscale_coherency.py`.

---

## 3. Empreintes et socles

### 3.1 Modèle : le socle est dérivé, jamais stocké à la main

- **Unité** : entité identifiée (`unit_id`). **Socle** : `occupied_hexes` = ensemble des cellules occupées **à une pose donnée**, fonction pure `f(centre, forme, taille, orientation)` — recalculé quand centre, taille ou orientation changent. Source de vérité collision/occupation, avec index inverse `cellule → unit_id`.
- **`BASE_SHAPE`** (`"round" | "oval" | "square"`) et **`BASE_SIZE`** (diamètre en hex, entier ou paire pour l'ovale) sont déclarés dans chaque fichier d'unité des rosters TypeScript (`frontend/src/roster/**/units/*.ts`, `static BASE_SHAPE` / `static BASE_SIZE`).
- **Orientation** : discrétisée en 6 pas de 60° (`hex_orientations` du board config). Aucune règle de jeu ne dépend de l'orientation (pas de facing) : elle n'affecte que pathfinding et placement des formes non circulaires.
- Le replay/analyzer reçoit le **hex central** + orientation dans les logs et recalcule `occupied_hexes` avec la même fonction que le moteur (`BASE_SHAPE`/`BASE_SIZE`/`orientation` journalisés par `ai/step_logger.py`).

### 3.2 Calcul d'empreinte

`def compute_occupied_hexes` (hex_utils) délègue à `def _footprint_round` / `def _footprint_oval` / `def _footprint_square` — discrétisation **euclidienne** (distance au centre projeté) de la forme sur la grille. Miroir frontend : `computeOccupiedHexes` / `footprintRound` ([frontend/src/utils/hexFootprint.ts](../../../frontend/src/utils/hexFootprint.ts)).

Géométrie continue des socles : `class Socle` (+ `RoundSocle`, `OvalSocle`, `SquareSocle`) dans hex_utils — contours réels (cercle analytique, polygone orienté ; l'ovale échantillonné sur `_OVAL_EDGE_SAMPLES` sommets, `def _socle_edge_primitives`). `def footprints_overlap` teste la collision au niveau socle.

### 3.3 Scaling du socle : `_scale_socle`, normalisation à x1

`def _scale_socle` ([engine/game_state.py](../../../engine/game_state.py)) est l'**autorité unique** du dimensionnement du socle (unité et figurines) à la résolution du plateau. À `inches_to_subhex == 1`, une figurine tient dans UNE case : la forme n'a plus de sens géométrique, `_scale_socle` **normalise en `round`/1**. Ne pas normaliser casse le moteur de deux façons opposées (historique mesuré) : un scalaire `1` avec `BASE_SHAPE="oval"` fait indexer `size[0]` sur un int (`TypeError` dans `def _socle_edge_primitives`) ; une paire `[1,1]` envoie l'unité sur le chemin multi-hex du pool de move, dont le prédicat d'engagement diverge du set dilaté de la validation (« incohérence masque/exécution », workers morts). Prédicat courant : `def socle_is_single_hex` (hex_utils).

Verrou : `tests/unit/engine/test_socle_normalized_at_x1.py` — construit socle non-rond + ennemi à portée d'EZ, contre-épreuve par mutation (6 destinations sur 506 violent l'EZ sans la normalisation). `test_move_mask_is_executable.py` couvre les deux résolutions mais reste vert sous cette mutation (trajectoires aléatoires) — sa docstring le dit.

Ce que la normalisation ne traite pas : deux définitions de « dans la zone d'engagement » coexistent (dilatation hex du cache `enemy_adjacent_hexes_player_<N>` vs distance bord-à-bord de socles). Mesuré (2026-07-28) : elles ne divergent nulle part où le moteur peut aller — dès `base_size > 1` la dilatation est incluse dans la zone de socles ; à `base_size == 1` les deux retombent sur la dilatation ; l'inclusion masque ⊆ exécutable tient par construction via `def erode_move_pool_by_squad_block`, qui rejoue le prédicat de `def validate_move_plan` (même helper `def build_move_blocked_cells_by_level`) sur toutes les figurines. Unifier coûterait le cache O(1) partagé par quatre phases sans corriger aucun comportement observable — non fait, délibérément.

### 3.4 Placement et occupation

- Empreinte candidate : `def compute_candidate_footprint`, validée par `def is_footprint_placement_valid` et `def candidate_overlaps_any_unit` (`engine/phase_handlers/shared_utils.py`) ; ensemble occupé : `def build_occupied_positions_set`.
- Primitives génériques : `def build_occupation_map`, `def validate_placement` (hex_utils).
- Déploiement : `def _is_footprint_deployable` (game_state, filtre du déploiement aléatoire) ; `def execute_deployment_action` (`engine/phase_handlers/deployment_handlers.py`) valide l'empreinte entière (zone, murs, overlap) avant placement. Frontend : pré-validation visuelle par les mêmes règles portées en TS (`isFootprintOnWall`, `isFootprintOverlapping`, `isFootprintInDeployPool`, `buildOccupiedSet`, `getContestedObjectives` — hexFootprint.ts) ; le backend reste l'autorité.
- **Invariant de non-chevauchement** : `occupied_hexes(U) ∩ occupied_hexes(V) = ∅` pour toute paire d'unités vivantes distinctes (sauf règle spéciale). L'overlap est et reste une couche **hex** (§4.10).

### 3.5 Primitives de placement multi-hex (perf)

Trois mécanismes dans/autour de hex_utils :

- `def precompute_footprint_offsets` — calcule une fois les offsets du socle pour colonnes **paires et impaires** (en odd-q les offsets dépendent de la parité de l'ancre) ; reconstruction O(|footprint|) par ancre par additions entières. Consommé par movement, deployment, shared_utils, spatial_relations, game_state.
- `def compute_footprint_placement_mask` — masque `bytearray` « ancre invalide » par **Minkowski inverse** (pour chaque obstacle, marquer les ancres qui le couvriraient ; parité gérée en filtrant `nc = fc − dc`). Construction O(|obstacles| × |offsets|), lookup O(1). **Jamais branchée en production** (seuls les tests l'exercent) : la tentative sur le BFS de consolidation a été revertée — construire le masque sur tout le plateau coûtait plus cher que les ~1 740 checks remplacés (BFS ne visitant que ~1,5 % du plateau). Rentable seulement si le BFS visite une fraction significative du plateau.
- `def _build_multi_hex_vectorized` (`engine/phase_handlers/movement_handlers.py`) — BFS multi-hex numpy du mouvement (bounds, murs, traversée, EZ, destinations). Dilations en slices numpy, **pas de scipy** (`binary_dilation` a produit des segfaults sur certains environnements).

### 3.6 Invariants normatifs des empreintes

- **I — Budget par cellule du socle** : aucune cellule ne parcourt plus que le budget de la phase ; le socle se déplace en **corps rigide** (translation + rotation), donc en translation tout point parcourt la distance du centre — c'est ce qui fonde la mesure centre-à-centre du budget (§4.1).
- **II — Largeur minimale** : le socle doit **passer** partout sur le chemin — obstacles dilatés par l'empreinte, ou clearance continue (§4.4) ; la rotation est un degré de liberté pour les formes non circulaires.
- **III — Non-chevauchement** (§3.4).

---

## 4. Métriques de distance — hex vs euclidien

### 4.1 Les métriques, et l'invariant budget vs portée

| Métrique | Primitive | Sert à |
|---|---|---|
| Hex cube | `def hex_distance` / `def calculate_hex_distance` | distances droites hex (gym, observations, adjacence) |
| Hex entre empreintes | `def min_distance_between_sets` | distance de règle entre unités côté hex |
| Euclidien bord-à-bord | `def euclidean_edge_distance` (hex_utils) | portée/adjacence/EZ côté euclidien (règle 01.04) |
| Géodésique any-angle | `def geodesic_field` (hex_utils) | **budget** de move/charge euclidien (règle 03.01) |
| BFS 6-voisins borné | pools de move/charge (§4.4, §4.7) | budget de move/charge côté hex, respecte les murs |
| Adjacence | 6 voisins, ou cache dilaté `enemy_adjacent_hexes_player_<N>` | contact direct |
| Overlap | intersection d'empreintes / `footprints_overlap` | collision de socles — **toujours hex** |

**Invariant vérifié sur tout le code (2026-07-03), à ne jamais casser :**

- le **budget de déplacement** (move, charge) se mesure **centre-à-centre**, en **cumul de longueurs de segments** (règle 03.01 « same point on its base ... add that distance » ; en translation rigide = déplacement du centre) → seul `geodesic_field` le calcule ;
- toute distance **figurine ↔ autre chose** (figurine, terrain, objectif) se mesure **bord-à-bord** (règle 01.04 « closest part of that model's base ») → `euclidean_edge_distance` / `ranged_edge_distance`, jamais un budget.

Mesurer un budget en bord-à-bord donnerait ~1 diamètre de trop. Les positions restent posées sur les **centres d'hexagones** : l'hex reste le système de coordonnées et d'occupation, l'euclidien est une couche de calcul par-dessus.

### 4.2 Le point de bascule unique (Distance management, Étapes 1-2)

Section citée par le code (`engine/combat_utils.py`, sélecteur de métrique). Trois briques, et la conversion confinée :

- **Primitive bord-à-bord** : `def euclidean_edge_distance` (hex_utils), entrées typées `Socle`. Rond↔rond en O(1) (`def euclidean_edge_clearance_round_round`) ; non-rond = distance continue entre contours réels. Retourne un `float` en unités-norme, sans arrondi. Paramètre `max_distance` (même contrat que son jumeau hex `min_distance_between_sets` : exact seulement sous le seuil, minorant au-delà) — les paires trop éloignées sont écartées en O(1) ; mesuré : primitive 3,3× plus rapide sur un mix véhicule↔escouade, verdicts identiques. Verrou : `tests/unit/engine/test_euclidean_edge_distance_bounds.py`. **Aucune primitive centre-à-centre de portée n'existe** : 01.04 impose le bord-à-bord.
- **Sélecteur par règle** : `def get_distance_metric` ([engine/combat_utils.py](../../../engine/combat_utils.py)) lit `game_config["distance_metric"][rule]` pour les règles de `DISTANCE_METRIC_RULES` — **erreur explicite** si section/clé/valeur manquante ou invalide, aucun fallback.
- **Fonction de portée unifiée** : `def ranged_in_range` / `def ranged_edge_distance` (combat_utils). `hex` → `min_distance_between_sets(fp) <= rng` ; `euclidean` → `euclidean_edge_distance <= rng × 1.5`. La conversion ×1.5 vit **ici et dans les primitives seulement**, jamais aux call-sites.

Clés de `distance_metric` (valeurs actuelles à lire dans [config/game_config.json](../../../config/game_config.json)) : `ranged`, `move`, `move_gym`, `charge`, `charge_gym`, `engagement`, `overlap`. Design acté : PvP/replay euclidien (ranged, move, charge, engagement), gym hex par défaut (clés `*_gym`, surchargeables par phase — §4.9), **`overlap` hex pour toujours** (couche d'occupation, orthogonale à la portée). Un `_gym` absent = pas de split.

**Cohérences imposées** (leçons de la migration tir) : le précheck de disponibilité d'arme (`def _build_weapon_availability_enemy_precheck`, `engine/phase_handlers/shooting_handlers.py`) et le check de portée en aval mesurent par la **même** fonction — en migrer un sans l'autre crée « arme disponible / cible refusée ». La branche gym du précheck a été supprimée : gym et PvP passent par `ranged_in_range`. La sélection « cible la plus proche » trie par la même distance que le seuil. Les mesures de portée IA (`ai/target_selector.py`, `engine/ai/weapon_selector.py` branche RNG, `ai/analyzer_phases/shoot_handler.py`) suivent la règle de la phase : ranged → euclidien, melee/stratégique → hex.

### 4.3 La convention ×1.5 (unités-norme) — ne pas « corriger »

Pipeline de conversion à **deux étages distincts** :

```
pouces × inches_to_subhex → subhex × ENGAGEMENT_NORM_HEX_WIDTH (1.5) → unités-norme (_hex_center)
```

`ENGAGEMENT_NORM_HEX_WIDTH = 1.5` (hex_utils) est le **pas horizontal entre centres de colonnes** dans le repère `def _hex_center` (`hex_width = 1.5 × hex_radius`, géométrie flat-top du repère de projection) — **pas √3** (√3 ≈ 1,732 serait la distance entre centres adjacents). Toutes les primitives (`_FOOTPRINT_SIZE_SCALE`, `def round_base_radius_norm`, `def engagement_minimum_clearance_norm`, `geodesic_field`) utilisent 1.5, aligné sur le rendu frontend : le système est cohérent en interne. C'est une convention maison délibérée — portée = EZ = overlap = rendu restent alignés.

### 4.4 Le champ géodésique any-angle (move/charge euclidien)

**Algorithme acté : lazy Theta\* en flood** — propagation type Dijkstra où un nœud hérite de la distance de l'**ancêtre** de son voisin si la ligne de vue est dégagée → coût cumulé = vraie distance euclidienne à angle libre. Quasi-optimal, **sur-estime sans jamais tricher** (jamais à travers un mur) ; erreur pire cas mesurée au spike : 0,86 subhex (< 1 subhex = sous la résolution de la grille, seuil exprimé en subhex via `inches_to_subhex`, jamais en pouces absolus). Prototype isolé : `spikes/geodesic_field_spike.py`.

- `def geodesic_field` (hex_utils) : champ complet en une passe, résultat en unités-norme. Perf : index spatial en buckets + parcours **DDA (Amanatides-Woo)** + rejet rapide centre→segment (mesuré : 1,12 s → 0,10 s par champ sur board ×10).
- `def segment_clear` / `def _segment_clear_indexed` : test **capsule** segment↔obstacles avec `clearance` (0 = rayon LoS, tangence permise ; > 0 = disque).
- **Budget-socle (option A, Minkowski)** : en translation rigide tout point du socle parcourt la distance du centre ; le vrai risque est le centre qui rase un coin. Solution : `clearance = rayon du socle` (`round_base_radius_norm`) — les obstacles sont gonflés de r, le champ mesure le centre et borne exactement tout point du socle (03.01). Effet assumé : un socle rond ne se faufile plus dans un passage plus étroit que lui (plus strict que l'hex, physiquement correct).
- **« 4.0-bis » — correctif grazing/squeeze** (identifiant cité par un commentaire de hex_utils) : la clearance n'était appliquée qu'au raccourci any-angle, pas au **pas adjacent** emprunté quand le raccourci échoue — un socle rond passait un goulot plus étroit que son diamètre. Fix dans `geodesic_field` : le pas adjacent est lui aussi testé à la capsule ; court-circuit `clearance <= 0` = no-op prouvé. Validé : `clearance > 0` ne fait que **retirer** des cellules ; seuil rond = passe ssi goulot ≥ diamètre.
- **Socles non-ronds** (option 2 retenue) : inflation **discrète de l'empreinte orientée** (`def inflate_obstacles_by_footprint`, hex_utils) puis champ à clearance 0 — garde l'orientation (le disque circonscrit la perdait). Unifié dans `def _euclidean_move_field` ([engine/phase_handlers/geodesic_move.py](../../../engine/phase_handlers/geodesic_move.py)), module de géométrie pure partagé move/charge ; multi-niveaux : `def reachable_multilevel_field` (coût de descente 13.06).
- **FLY (21.03)** : ignore murs/figurines → le champ dégénère en **disque euclidien centre-à-centre** (obstacles vides) — dans le pool par-figurine et le pool d'ancre.
- **Caches par phase, jamais mutualisés** : les obstacles diffèrent (move = murs+ennemis+amies+EZ ; charge = murs+ennemis seuls) → `_move_model_field_cache` et `_charge_model_field_cache`, vidés **au début de phase ET après chaque commit réel** — jamais par les poses provisoires (contrat de `movement_handlers`, commentaire près de la déclaration du cache) ; **exclus de la sérialisation API** (`_GAME_STATE_EXCLUDE_KEYS`, `services/api_server.py` — sinon chaque réponse embarque des milliers de cellules). Résiduel connu, jamais unifié : `def charge_build_valid_targets` recalcule encore **un champ géodésique par activation d'escouade** hors de ces caches (ex-« unification C » de Distance management, étape 5).

Branchement move : `def movement_build_model_destinations_pool` (par-figurine — c'est lui que le PvP interactif consomme) et `def movement_build_valid_destinations_pool` (pool d'ancre, dont `def _euclidean_ground_anchor_multihex`). Le PvP frontend est **backend-driven** (il consomme les pools) : aucun portage TS des champs n'a été nécessaire ; `BoardReplay.tsx` recalcule en hex localement (cosmétique, parties passées).

### 4.5 Sélecteurs par règle × résolution : `geometry_is_hex` prime tout

Quatre sélecteurs consultent la config **et** la résolution : `def engagement_distance_metric` (spatial_relations), `def _move_distance_metric` (movement_handlers), `def _charge_distance_metric` (charge_handlers), `def _ranged_distance_metric` (shooting_handlers). Tous appliquent : **à `inches_to_subhex <= 1`, la géométrie est hex**, quoi que dise la config (`def geometry_is_hex`, critère unique `inches_to_subhex`) ; la clé de config est quand même lue et validée (une valeur invalide lève à x1 comme ailleurs).

**Le piège qui a imposé ce point de bascule** (à ne pas réintroduire) : le moteur identifiait « board x1 » par `ez <= 1`, disséminé dans ~15 gardes. Quand `game_rules.engagement_zone` est passé de 1″ à 2″ (2026-06-03), toutes ces gardes ont cessé de se déclencher **silencieusement** — le x1 repartait en euclidien, avec deux crashes « incohérence masque/exécution » en training. Règle : `ez` n'est **jamais** un test de résolution.

### 4.6 Zone d'engagement (EZ)

L'EZ est un concept **unique** consommé par quatre phases (move, tir, charge, fight) — la basculer dans une phase et pas les autres crée « engagé côté move mais pas côté tir ». Décision actée : métrique unique via `engagement_distance_metric`, **sans variante gym** (un split y imposerait un retrain de toute façon).

- Sémantique euclidienne (03.04, EZ = disque bord-à-bord) : `euclidean_edge_distance(socle_a, socle_b) ≤ engagement_minimum_clearance_norm(ez)` — primitive de paire : `def entries_in_engagement_zone` (spatial_relations), prédicat plateau : `def unit_within_engagement_zone_footprints` / `def unit_entries_within_engagement_zone`, contrainte du move : `def move_anchor_violates_engagement_clearance` ; masque vectorisé du pool de move : `def _euclidean_mover_ez_forbidden_mask` (movement_handlers, chemin hex : `def _compute_mover_ez_forbidden_mask`).
- Chemin hex/single-hex : cache dilaté `def build_enemy_adjacent_hexes` (shared_utils), clé `enemy_adjacent_hexes_player_<N>`, partagé par les phases.
- Consommateurs de phase : `def _friendly_engagement_blocks_ranged_shot` et `def _is_adjacent_to_enemy_within_cc_range` (shooting), `def _charge_unit_within_engagement_zone` (charge), `def _is_in_enemy_engagement_zone` et `def _enemy_items_within_move_engagement_horizon` (move — la seconde est une prune superset, légitimement hex).
- Le corps à corps est régi par l'EZ (pas de `melee_range` séparé, §1.3). Composante verticale 5″ : `def get_engagement_zone_vertical`.

### 4.7 Charge : deux systèmes de reachability, deux checks

**Deux systèmes distincts — ne pas re-rater** (le premier essai de migration avait migré le mauvais) :

1. `def charge_build_valid_destinations_pool` (pool d'ancre) → éligibilité de phase + liste de cibles à l'activation (`def charge_build_valid_targets`) ;
2. le plan-context par-figurine (`_euclidean_reach`, ex-`_bfs_reach`) → la **zone violette interactive** dessinée à l'écran — c'est lui que voit le joueur.

**Deux checks à métriques différentes, par règle** :

- **éligibilité à déclarer (11.02)** : « within 12" » — euclidien bord-à-bord **en ligne droite** (`def _has_valid_charge_target` via `ranged_in_range`), O(ennemis), **pas** de pathfinding. Raison actée : `fly` peut être accordé en cours de phase → la mesure doit être fly-agnostique ; et une unité à 11″ en ligne droite mais 13″ en géodésique est **éligible mais peut rater sa charge** — règle-correct.
- **budget du charge move (11.04)** : le jet 2D6 a lieu **à l'activation, avant** la désignation des cibles ; les cibles sont bornées par **le jet**, pas par 12″. Budget = `def _charge_budget_subhex` — **source unique** des sites de calcul, y compris le malus **take to the skies** (21.03 : −2″ **et** traversée libre, gouvernés ensemble par le set `units_took_to_skies_charge` ; traversée : `def _charge_fly_active`, source unique des BFS/champs).
- Côté hex : `def _charge_bfs_max_distance` ; prune : `def _charge_skip_hex_lb_prune_round_round_engagement` (compatible euclidien). Le filtre « must end closer to target » (11.04) du plan-context reste hex — approximation mineure, orthogonale au disque de reachability.
- La parité masque/commit passe par `def charge_check_eligibility` (shared_utils), source unique interrogée par le masque **et** re-vérifiée au commit (voir aussi §5.4).

### 4.8 Cohérence d'escouade (03.03) — unifiée, alignée sur la résolution

PDF lu, décisions actées (2026-07-29) :

- **1re puce = CONNEXITÉ** (une seule chaîne à `unit_model_cohesion_range`), plus stricte que le littéral « ≥ 1 voisin » — appliquée dans les deux modes ;
- **2e puce = PAR PAIRES** (« within 9" of every other model »), jamais un cercle d'étalement (verdict dépendant de la position absolue sinon — verrou : `tests/unit/engine/test_coherency_translation_invariance.py`) ;
- **métrique par résolution** : `geometry_is_hex` → mode footprint (hex centre-à-centre) à x1, mode de `game_rules.cohesion_distance_mode` (euclidien bord d'empreinte) à x5+ ;
- **source unique** : `def coherency_violation_flags` (shared_utils) — les copies inline de charge/fight (pile-in, consolidation) sont supprimées ; l'enforcement au commit passe par `can_validate` sur la même règle partout ;
- restent ouverts : les 5″ verticaux (à câbler avec le chantier étages) et le cercle de 9″ dessiné par le front (`drawCohesionHalos`, `BoardPvp.tsx`), qui n'est plus le critère du backend.

### 4.9 `gym_distance_metric` — métrique imposée par une phase de training

Clé **optionnelle** d'un bloc de `config/agents/<agent>/<agent>_training_config.json` (constante `GYM_DISTANCE_METRIC_KEY`, `def gym_distance_metric_override`, combat_utils). Absente : les sélecteurs lisent `move_gym`/`charge_gym`. Présente : impose la métrique gym du run — `move` **et** `charge` ensemble (11.04 : la charge est un move), jamais l'engagement. Valeur invalide → erreur à la **construction** du moteur. **La résolution prime toujours** (`geometry_is_hex`) : la clé est sans effet à x1, par construction.

Pourquoi elle existe (mesuré sur 162 états de move réels, x5) : pools hex et euclidien diffèrent dans 100 % des états (11,4 % du pool en médiane, `euclidean ⊆ hex` partout — l'agent n'est aveugle à aucune destination légale PvP mais apprend une frontière hexagonale là où elle est circulaire, 72 % de l'écart sur l'anneau extérieur). Pourquoi pas par défaut : ×3,55 sur la construction du pool (structurel : le champ géodésique encode le contournement d'obstacle, non reconstituable par filtre du pool hex au sol). D'où le réglage **par phase** : curriculum en hex, phase finale euclidienne en `--append`. Le gain en win-rate n'est pas prouvé — à évaluer, pas à supposer.

### 4.10 Ce qui reste hex PAR CHOIX (dette actée)

| Règle | Raison |
|---|---|
| Overlap / collision de socles | couche d'occupation, ne bascule jamais |
| Adjacence & voisinage | primitive de grille |
| Observations / récompenses IA | retrain prévu de toute façon → épinglées hex pendant la migration |
| Pile-in / consolidation (12.03 / 12.08) | budget 3″ max, erreur ~10 % jugée négligeable — dette explicite (12.0x appelle 03, devrait être euclidien) |
| Fall-back move (09.07) | non planifié — même logique que le move normal, à acter le jour venu |
| IA analyzer / replay charge (`ai/analyzer_phases/charge_handler.py`, `ai/step_logger.py` et la chaîne replay) | mesurent des runs gym-hex → la métrique suit le run analysé, sinon on mesure de l'euclidien sur du hex |
| Filtre « closer to target » du plan-context charge | approximation mineure orthogonale |
| Gym (`move_gym`/`charge_gym` = hex) | perf ×3,55 mesurée — surchargeable par phase (§4.9) |
| x1 entier | décision « RÉSOLUTION x1 » (§4.5) |
| Replay TS (`BoardReplay.tsx`) | cosmétique, parties passées |

Tout call-site hex de portée/budget hors de cette table = **bug non documenté**. Grep de contrôle historique : aucun call-site de portée/budget tir/move/charge/EZ n'appelle `calculate_hex_distance` directement.

### 4.11 Frontend : qui mesure quoi

- **Hex** : `cubeDistance` / `getHexDistance`, `getAdjacentPositions` / `areUnitsAdjacent`, `isUnitInRange`, `getValidMovePositions` ([frontend/src/utils/gameHelpers.ts](../../../frontend/src/utils/gameHelpers.ts)) ; BFS locaux de `BoardReplay.tsx` ; `wasm_hex_distance`.
- **Euclidien** : `hasLineOfSight` (gameHelpers, échantillonnage multi-points + murs ; accéléré par `frontend/src/wasm-los-pkg/`) ; empreintes et distances bord-à-bord de `hexFootprint.ts` (dont `euclideanEdgeDistanceToCellSubhex`, miroir du backend, même facteur ×1.5, même absence d'arrondi — consommé par `losPreviewHelpers.ts`) ; `blinkingHPBar.ts` (distances subhex pour roll min / arme optimale) ; `probabilityCalculator.ts`, `weaponHelpers.ts`.
- **Backend-driven** : les previews PvP de move et de charge consomment les pools calculés par le moteur (`useEngineAPI.ts`, `useGameActions.ts`, `BoardPvp.tsx`) — la géométrie euclidienne y est visible sans portage TS.
- La règle de sync : toute mesure affichée doit matcher la géométrie moteur (mêmes primitives portées, même ×1.5) ; le halo de cohésion de `drawCohesionHalos` est une exception connue (§4.8).

### 4.12 LoS et détection

- Le moteur calcule la LoS **à la demande**, **binaire** (règle 06.01 : `can_see = ratio > 0`, pas de seuil) : `def compute_los_visibility` / `def compute_los_state` (hex_utils, trace `hex_line`), consommées par `def _get_los_visibility_state` (shooting_handlers).
- Le modèle « proportion de bordure visible » du chantier ×10 (V ∈ [0,1], seuils P = 0,05 « pas de LoS » et C = 0,95 « à découvert ») est resté une **cible jamais implémentée** : les clés `los_visibility_min_ratio` / `cover_ratio` n'existent ni dans `game_config.json` ni dans le moteur (grep 0-hit). Si ce modèle revient un jour, repartir de la spec archivée (Boardx10-final §7.2), pas du code.
- `detection_range` (unités cachées 13.09) est une **portée de tir** : gate autoritaire ET affichage (`def build_hidden_too_far_by_unit_id`, shooting_handlers) passent par `ranged_edge_distance` avec la métrique `ranged` — la divergence gate-euclidien / affichage-hex relevée par l'audit a été soldée dans le code.

---

## 5. Unités hors table — le contrat « hors table = hors géométrie »

Contrat cité par le code (`ai/evaluation_bots.py`). Corrigé le 2026-08-05.

### 5.1 L'état hors table

Une unité hors table (réserves 20.01, ou tout le monde au reset en `deployment_type: "active"`) est **vivante** (`is_unit_alive` → True), présente dans `units_cache`, à la position **sentinelle `(-1,-1)`**, avec `occupied_hexes` **vide** et `deployed_on_turn is None`. Tout filtre écrit sur « vivante » la laisse passer. Le motif `.get("occupied_hexes", {ancre})` ne protégeait rien : hors table la clé est **présente et vide**. Pire : l'entrée-cache hors table a ses champs par-figurine peuplés de `(-1,-1)`, donc `def entry_has_vertical_data` répond True et la mesure part sur le chemin 3D — le repli d'ancre n'est jamais atteint ; mesuré : deux fantômes étaient mutuellement « engagés », et ça remontait aux features d'observation.

### 5.2 La règle

> **Une MESURE par paire lève ; un PRÉDICAT sur le plateau répond par la RÈGLE ; une ÉNUMÉRATION filtre.**

Un helper feuille qui rendrait « distance infinie » serait exactement le fallback interdit (T1). Le `False` du prédicat n'est pas un repli : une unité absente du champ de bataille n'est engagée avec personne (20.01) — c'est une réponse de règle. Faire **lever** les feuilles a transformé chaque filtre manquant en crash localisable au lieu d'un verdict faux silencieux.

### 5.3 Les primitives ([engine/spatial_relations.py](../../../engine/spatial_relations.py))

`def entry_is_on_battlefield` vit dans `spatial_relations` (couche basse, dépend de hex_utils seul) et est ré-exporté par `shared_utils` — même symbole.

| Primitive | Rôle | Hors table |
|---|---|---|
| `def require_entry_on_battlefield` | garde nommée | **lève** |
| `def entry_footprint` | empreinte d'escouade, source unique | **lève** |
| `def entries_in_engagement_zone` | mesure EZ par paire | **lève** |
| `def unit_within_engagement_zone_footprints` | prédicat « engagée ? » | **`False`** (règle 20.01) |
| `def entries_on_battlefield` | énumération, toutes unités | **écarte** |
| `def enemy_entries_on_battlefield` | énumération, ennemis | **écarte** |

Le repli sur l'ancre de `entry_footprint` ne subsiste que pour les entrées **synthétiques posées** (mover candidat, fixtures mono-figurine), où il est exact. Les gardes côté **acteur** (`*_phase_start`, pools d'activation : une unité hors table ne tire pas, ne charge pas, ne bouge pas) restent dans les handlers — ce ne sont pas des filtres d'énumération d'ennemis.

### 5.4 Pièges mesurés (chers à redécouvrir)

- **La sentinelle est géométriquement loin** (~274 subhex de la zone de déploiement) : un test qui met une unité en réserves *sans construire la géométrie* reste **vert avec le défaut** — le fantôme n'est jamais mesuré. Il faut amener une unité réelle à portée. Second piège : `shooting_phase_start` n'atteint le précheck d'ennemis que si l'unité est en advance ou au contact.
- **Fuite inter-épisodes** : les objets `unit` survivent au reset ; il faut y restaurer `deployed_on_turn`, `in_strategic_reserves`, `reserves_repositioned` avec la sémantique de `create_unit` — sinon un roster à réserves ne se comporte comme tel qu'au premier épisode de chaque worker, et l'observation déclare « posées » des escouades à la sentinelle.
- **Parité masque/commit de la charge** : `def charge_check_eligibility` est interrogée par le masque ET re-vérifiée au commit ; son test des 12″ sur positions de grille brute prenait la sentinelle pour « à portée » — les deux chemins sont gardés.
- **Les zones de déploiement sont une donnée de scénario**, publiées à la racine `game_state["deployment_pools"]` dans tous les modes ; `deployment_state` ne garde que la comptabilité mutable de la phase. Deux lecteurs en dépendent hors phase de déploiement : `def squad_grid_anchor` (observation_builder) et `def _opponent_deployment_zone_cells` (movement_handlers, clause 20.04).
- **Deux faits vérifiés** avant tout chantier holdout+réserves : les rosters *adverses* à réserves du holdout n'existent pas (un bot ne décide jamais une mise en réserve — c'est un choix de liste, cf. `TacticalBot.select_placement_action`, [ai/evaluation_bots.py](../../../ai/evaluation_bots.py) ; et quand un roster à réserves lui est donné, il fait **arriver ses réserves au premier slot ouvert — arrivée DÉTERMINISTE**) ; et tout scénario déposé dans `holdout_regular/` entre automatiquement dans le score (collecte par glob, `ai/training_utils.py`) — la rupture de série est structurelle. `def _filter_training_roster_candidates` (game_state) ne filtre rien tant que `roster_pool_schedule.enabled` est false ; sa regex écarterait tous les rosters Armageddon actuels si on l'activait.
- **Décisions OUVERTES avant tout chantier holdout+réserves** (héritées de l'ex-1_unites_hors_table, jamais tranchées) : où déposer un scénario holdout à réserves — (a) dans `holdout_hard/` (hors score), (b) restreindre le score aux 4 scénarios d'origine, ou (c) l'assumer dans `holdout_regular/` et **re-baseliner en datant** la rupture de série ; et l'arbitrage rosters — passer de 2 à 4 rosters élargit la distribution d'évaluation mais contredit la spécialisation SM/Orks actée (décision 2026-07-19).
- **Asymétrie d'éligibilité assumée** : la garde hors-table ajoutée à `def _fight_v11_grouped_step_eligible` est **sans effet observable mesuré** — aucun test ne peut la faire virer au rouge, inutile d'en chercher un ; elle reste parce que le `False` vient d'un effet de bord géométrique, pas d'une règle. Ne pas la supprimer comme « code mort », ne pas ouvrir de chasse au test.
- **Méthode** : une trajectoire ne verrouille pas (tirer l'action parmi les légales, vérifier la couverture sur l'union des graines) ; ce qui n'est atteint par aucune trajectoire doit être **construit**.

### 5.5 Verrous

`tests/unit/engine/test_off_table_geometry.py` (contrat des primitives + les deux familles DISTANCE/ENGAGEMENT par le chemin de production, anti-vert-vacant), `tests/unit/engine/test_reserves_full_episode.py` (épisode complet multi-graines, invariant `col >= 0` ⟺ `deployed_on_turn is not None` à travers un reset, parité masque/commit), `tests/unit/engine/test_fight_off_table_enumeration.py` (l'énumérateur ET ses consommateurs), `tests/unit/ai/test_evaluation_bots.py` (les énumérations des bots). `tests/unit/engine/test_strategic_reserves_20.py` et `test_bot_ingress_reserves.py` sont pinnés sur une fixture sans réserves — c'est ce qui les tient debout, ne pas dé-pinner.

---

## 6. Historique et sources

- **Chantier Board ×10** (2026-04→05) : abandon des topologies denses Θ(n²), création de `engine/hex_utils.py` (primitives odd-q, LoS à la demande, BFS bornés), empreintes multi-hex (`occupied_hexes`, invariants I-III), `engagement_zone` intégrée à move/advance/charge/fight, conversion inches→subhex au chargement. Un audit « 1 hex = 1 unité » (2026-05-06) a ensuite migré reward/action/observation/bots vers les distances entre empreintes — tout soldé, seul le protocole (§2.2 de ce document) reste normatif.
- **Migration hex → euclidien** (2026-07-01→04, « Distance management ») : Étapes 0-7 — inventaire, point de bascule unique, tir bord-à-bord, spike géodésique, move (option A Minkowski, 4.0-bis), charge (deux systèmes, pré-gate ligne droite), EZ euclidienne 4 phases. Décision x1-tout-hex et coherency unifiée le 2026-07-29 ; `gym_distance_metric` le 2026-08-04 ; borne `max_distance` euclidienne le 2026-08-08.
- **Banc x1 44×60** (2026-07-27→28) : plateau x1, conversion terrain/rosters au chargement, retrait de `25x21`, du mode tutoriel et des topologies `.npz`, normalisation du socle à x1.
- **Hors table = hors géométrie** (2026-08-04→05, chantier 04c puis correctif global) : primitives `spatial_relations`, fuite inter-épisodes, `deployment_pools` à la racine, activation des variantes de rosters.
- Les documents sources détaillés (avec leurs mesures et checklists d'époque) sont dans `Documentation/Archives/docs/`.

---

## 7. Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| Boardx10-final.md | §2.2 (odd-q, voisins, cube) — **cité par `engine/hex_utils.py`** | §1.1, §2.1, §2.2 |
| Boardx10-final.md | §2.3 (module unique de primitives) — **cité par `engine/hex_utils.py`** | §2 (chapeau), §2.3 |
| Boardx10-final.md | §P3 (conversion inches→subhex ; « advance budget = D6 face × scale ») — **cité par `ai/analyzer.py`** | §1.3 |
| Boardx10-final.md | §2.5, §9.1-9.3, §18 (socles, invariants, replay) | §3.1, §3.6 |
| Boardx10-final.md | §3.3 (distance plus-proche-paire) | §2.2 |
| Boardx10-final.md | §6, §10, §14 (n², contraintes RL/perf) | §1.5 |
| Boardx10-final.md | §7.2 (LoS V-ratio, seuils P/C — jamais implémentés) | §4.12 |
| Boardx10-final.md | §9.0 (`game_rules`, engagement_zone) | §1.3, §4.6 |
| Boardx10-final.md | §20 (audit 1 hex = 1 unité — protocole) | §2.2 (protocole), §6 (historique) |
| Boardx10-final.md | §4-§5 (déploiement ×10, objectifs ×10 — valeurs de l'époque) | §1.2 ; chiffres remplacés par les configs `config/board/*/` |
| Boardx10-final.md | §7.3-§7.6, §11-§13, §15-§17, §19 (topologies denses .npz, builder LoS, caches ×10 — mécanisme SUPPRIMÉ le 2026-07-28) | §1.2 (ligne d'historique) ; purge : `los_topology_builder` et `_load_topology_cached` 0 hit |
| Boardx10-final.md | §8, §9.4-§9.8 (perf RL ×10, budgets d'époque) | §1.5, §3.6, §4.6 ; chiffres volatils non recopiés |
| Distance management.md | §18, §21 (résidus d'audit, notes de clôture) | §4.10 ; état des chantiers → Roadmap/ |
| Distance management.md | Étape 0 (inventaire initial des métriques) | §4.1 (la carte à jour remplace l'inventaire daté) |
| Distance management.md | Étape 6 (doc de la clé `distance_metric`, grep de contrôle) | §4.2, §4.10 |
| V11_board_44x60x1.md | §1-2 (conversion au chargement, `downscale_cell`) — cité par `services/api_server.py` et `frontend/src/hooks/useGameConfig.ts` | §2.4 |
| V11_board_44x60x1.md | §2 bis (rosters, `_scale_socle`, normalisation x1) | §2.4, §3.3 |
| V11_board_44x60x1.md | §3-4 (contenu du plateau, ce que x1 ne mesure pas) | §1.2, §1.4 |
| V11_board_44x60x1.md | §5 (retrait 25x21, topologies, tutoriel) | §1.2, §2.4 |
| V11_board_44x60x1.md | §6 (vérifications) | §2.4 (verrous), §1.4 |
| Distance management.md | §0-17 (cartographie des call-sites) | §4.1, §4.6, §4.11 |
| Distance management.md | **Étapes 1-2** (point de bascule, tir) — **cité par `engine/combat_utils.py`** | §4.2 |
| Distance management.md | Étape 3 + **4.0-bis** (géodésique, grazing) — 4.0-bis cité par `engine/hex_utils.py` | §4.4 |
| Distance management.md | Étapes 4-5 (move, charge) | §4.4, §4.7 |
| Distance management.md | Étape 7 (EZ euclidienne) | §4.6 |
| Distance management.md | Décisions actées (dont RÉSOLUTION x1, coherency 03.03) | §4.1, §4.5, §4.8 |
| Distance management.md | `gym_distance_metric` | §4.9 |
| Distance management.md | Dette hex intentionnelle | §4.10 |
| Distance management.md | §20 (audit règles : ×1.5, 01.04, 03.01, 03.04, 20.12, 20.13) | §4.3, §4.1, §4.7, §4.12 |
| compute_footprint_placement_mask.md | tout | §3.5 |
| 1_unites_hors_table_chemins_geometriques.md | tout | §5 |
