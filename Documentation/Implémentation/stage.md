# Projet Étages / Niveaux verticaux (multi-level)

> Document de reformulation fondé **uniquement** sur le code existant (`engine/`, `frontend/`)
> et sur les règles officielles (`Documentation/40k_rules/`).
> Toute affirmation "règle" est citée avec son PDF source. Toute affirmation "code" est
> ancrée sur un fichier + ligne.

---

## 1. Objectif

Le moteur est aujourd'hui **strictement 2D** (grille hexagonale odd-q, position = `col`/`row`).
Le vrai jeu 40K se joue en 3D : les ruines à plusieurs étages permettent de poser des
figurines en hauteur, avec des règles propres de déplacement vertical et de ligne de vue.

Cible fonctionnelle (idée initiale) :
- Chaque étage est une **empreinte au sol** (polygone) rattachée à un décor.
- Empreinte non occupée → contour couleur/style d'un terrain non-objectif.
- Empreinte occupée (≥1 fig posée dessus) → contour **blanc**.
- Un **bouton "feuilles empilées"** à côté de la loupe de zoom, avec le n° de niveau courant (`0` = rez-de-chaussée).
- Vue mono-niveau : au niveau courant on ne voit que les figs de ce niveau ; les figs d'un
  autre niveau dont l'empreinte déborde sous le niveau courant passent en **mode ghost**.

---

## 2. Règles 40K officielles applicables

> Il n'existe **pas** de PDF "Ruins" séparé : les ruines sont des **dense terrain features**
> (`13 Terrain.pdf` §13.05, "Examples: Buildings, ruins, …"). Toutes les règles dense + Solid s'appliquent.

### 2.1 Être "sur" un étage — `13 Terrain.pdf` §13.06 "SETTING UP OR ENDING A MOVE"
Une figurine peut finir un move sur une surface **hors rez-de-chaussée** ssi **les deux** conditions :
- La figurine a l'un des mots-clés **INFANTRY / BEASTS / SWARM / FLY / MONSTER**.
- Après le move elle est **stable** ET **aucune partie de sa base ne déborde du bord extérieur de la surface**.

→ La base doit être **entièrement** sur la surface (aucun porte-à-faux). "Stable" est exigé mais non chiffré.

Complément `03 Moving.pdf` §03.01 : une fig ne peut pas finir "on another model or partway through
a surface of a terrain feature (e.g. a wall or ceiling)" — pas à cheval dans un plancher/mur.

### 2.2 Déplacement vertical — `13 Terrain.pdf` §13.06 "MOVING VERTICALLY" / "TERRAIN AND MOVEMENT"
- **INFANTRY / BEASTS / SWARM** montent/descendent librement à travers murs et étages des ruines.
- **MOBILE** : traversée des dense **horizontale seulement** (pas de traversée verticale des planchers/murs).
  Nuance : la sous-section générique "MOVING VERTICALLY" ne restreint pas par mot-clé l'ascension par
  l'**extérieur** d'un décor ; mais MOBILE ne peut pas **finir** en hauteur (absent de la liste §2.1).
- **Autres (ex. VEHICLE)** : peuvent gravir/descendre verticalement des sections >2" de haut,
  mais **sans traverser planchers/plafonds** et **sans finir en hauteur**.
- Coût : "Add the distance moved vertically up, and the distance moved vertically down, to any
  other distance that model has moved" → la distance verticale (montée **et** descente) **se cumule**
  au mouvement horizontal, contre le M. Contrainte : rester ≤ **½" horizontalement** du décor pendant l'ascension.
- Pas de règle "échelle"/coût forfaitaire : c'est de la distance mesurée.

**FLY** — `21 Flying and surging.pdf` §21.03 : en déclarant "take to the skies", la fig **ignore
toute la distance verticale** (montée/descente gratuite) contre **−2"** de mouvement max.
Limites : uniquement pour les moves **normal / advance / fall back / charge** (pas pile-in/consolidation) ;
se déclare **par unité, avant de déplacer la moindre figurine** ; permet aussi de traverser **tous les
modèles** (ennemis, MONSTER/VEHICLE inclus) et **toutes les catégories de terrain**, horiz. et vert.

### 2.3 Ligne de vue vers/depuis un étage
- Base — `06 Other concepts.pdf` §06.01 "VISIBILITY" (True Line of Sight) : LoS = ligne droite
  imaginaire de **1 mm** de large depuis **n'importe quelle partie** de l'observateur vers
  **n'importe quelle partie** de la cible. Lors du tracé, les modèles de l'unité observatrice **et**
  de l'unité observée sont **ignorés**. Distinction **visible / fully visible** : fully visible
  conditionne le benefit of cover (§13.08).
- Blocage en hauteur — `13 Terrain.pdf` §13.11 "SOLID" (les dense/ruines l'ont) :
  "Line of sight cannot be drawn across any enclosed gap in the surface of such a terrain feature
  that is **3" or less from ground level**."
  → Sous 3" (≈ rez-de-chaussée), la LoS ne traverse **aucune ouverture** (fenêtre/porte/impact).
  Au-dessus de 3", la LoS se trace **normalement** à travers les ouvertures.
  Designer's Note : 3" = hauteur du 1er étage de beaucoup de décors ; certaines missions peuvent
  **ajuster ce seuil** → argument direct pour un seuil configurable dans le moteur.
  ⚠️ Les deux "3 pouces" ne mesurent pas la même chose : Solid = hauteur du **gap** "from ground
  level" ; Plunging Fire (§2.4) = hauteur de la **section** ("3 or more in height").
- Obscuring — `13 Terrain.pdf` §13.10 : si **toute** la LoS entre 2 figs traverse une obscuring area
  (hors celle où l'une des deux se trouve), elles ne se voient pas. Une fig posée **sur** la ruine est
  dans cette area → l'exclusion la concerne.

### 2.4 Bonus / états liés à la hauteur
- **Plunging Fire** — `22 Other rules and abilities.pdf` §22.05 : attaque à distance sur une cible
  **visible** contenant ≥1 fig au sol → **+1 BS** si **au moins une** des conditions :
  (a) la fig tireuse est sur une section **≥ 3" de haut**, OU (b) la fig tireuse a le mot-clé
  **TOWERING** et la cible est ≤ **12"**.
- **Benefit of cover** — §13.08 : deux conditions alternatives — INFANTRY/BEASTS/SWARM dans l'area,
  OU modèle **pas fully visible** (terrain/obscuring intermédiaire, tout mot-clé) ; évalué **par
  modèle** de l'unité ; effet : **−1 BS** contre l'unité à couvert.
- **Hidden** — §13.09 : terrain area contenant du dense + unité **n'ayant pas tiré ce tour ni le
  précédent** → visible seulement à ≤ **15"** (detection range). Très pertinent pour la LoS en ruines.

### 2.5 Multi-niveaux : cohésion & engagement (verticalité déjà chiffrée)
- Coherency — `03 Moving.pdf` §03.03 : **deux conditions simultanées** pour chaque fig :
  (a) ≤ **2" horiz. et 5" vert.** d'au moins **une** autre fig, ET (b) ≤ **9" horiz. et 5" vert.**
  de **toutes** les autres figs. (Pas d'alternative liée au nombre de figurines.)
  Regaining coherency : en fin de tour, une unité hors coherency **détruit des figurines** jusqu'à
  la retrouver — pertinent si un move multi-niveaux laisse des figs à >5" de vertical.
- Engagement range — `03 Moving.pdf` §03.04 : ≤ **2" horiz. ET ≤ 5" vertical**.
  → Combat/engagement entre étages possible si horiz. ≤2" et vertical ≤5".

### 2.6 Débordement / chevauchement — **interdit**
Aucune règle n'autorise le débordement de base sur un étage. Trois interdictions explicites :
§13.06 (aucune partie de la base ne déborde du bord), §03.01 (pas à cheval dans plancher/plafond/mur),
encart SOLID (aucune partie de la fig à travers une portion fermée ≤3" du sol).

> ⚠️ **Divergence à trancher** : l'idée initiale propose "hex central + 50% de l'empreinte sur la zone"
> pour considérer une fig posée. C'est une **règle maison** qui **contredit** §13.06 (base **entièrement**
> dessus, 0% de débordement). Décision requise : coller aux règles (100% dedans) ou assumer une
> tolérance de jeu numérique. Le reste du document est écrit pour supporter les deux (seuil paramétrable).

### 2.7 Mesure des distances — **3D par défaut** (`01 Core concepts.pdf` §01.04)
- Toute distance se mesure **socle à socle, partie la plus proche**, en **ligne droite** — donc en **3D**
  entre étages, sauf règle explicitement "horizontale". Le socle **fait partie de la figurine** pour
  toutes les règles (§01.02). Les figs **FRAME** (sans socle, `17 Monsters and vehicles.pdf` §17.02)
  mesurent depuis le **point le plus proche de la coque** (donc engagement possible en hauteur via le
  haut d'un tank) et restent toujours verticales ("upright").
- **Portée d'arme** (`02 Datasheets.pdf` §02.04 + `04 Making attacks.pdf` §04.02) : vérifiée **par
  figurine porteuse**, en distance 3D — la hauteur consomme de la portée.
- **Exceptions "horizontales" explicites** (la composante verticale est ignorée) : arrivées de réserves
  et aptitudes de setup → **>8" horizontalement** des ennemis (`20 Strategic reserves.pdf` §20.04 ingress,
  `24 Core abilities.pdf` §24.09 Deep Strike, §24.20 Infiltrators, §24.31-32 Scouts).

### 2.8 Un seul moteur de mouvement vertical pour toutes les phases
Charge (`11 Charge phase.pdf` §11.04), pile-in (`12 Fights pahse.pdf` §12.03), overrun (§12.06) et
consolidation (§12.08) sont tous définis comme des moves "**as described in Moving (03)**" — les règles
verticales §13.06 (coût cumulé, ½", restrictions mot-clé) s'appliquent donc **uniformément** ; seules
changent la distance max (2D6 / 3") et les contraintes de fin de move (engaged/closer, mesurées en 3D).
Conséquences : une charge vers un étage doit couvrir la montée avec le 2D6 et finir en engagement
2"/5" ; un pile-in/consolidation de 3" ne franchit un étage que si la distance verticale tient dans les 3".

### 2.9 Contrôle d'objectifs et verticalité
- **Terrain objective** (`14 Objectives.pdf` §14.01-14.02) : "within range" = être **dans la terrain
  area** (empreinte au sol) — une fig à **n'importe quel étage** de la ruine-objectif compte son OC.
  Pas de mesure de distance : test d'appartenance à la zone.
- **Objectif-pion hors terrain area** (`25 Rules appendix.pdf`) : cylindre **≤3" horizontal ET ≤5"
  vertical** du marqueur — une fig au 1er étage (<5") peut contrôler un objectif au sol.
- **Actions** (`16 Actions.pdf` §16.01) : éligibilité "within a terrain area" indépendante de l'étage ;
  pile-in/consolidation (même verticaux) n'interrompent pas une action.

### 2.10 Cas particuliers vérifiés (balayage complet des 25 PDFs)
- **AIRCRAFT** (`23 Aircraft.pdf`) : verticalité entièrement **abstraite** — réserves obligatoires,
  ingress moves uniquement, **Plunging Fire sans effet** (§23.03), ignorés pour pile-in/consolidation/surge
  par les unités sans FLY, mêlée FLY-only. Aucune altitude chiffrée.
- **Hover** (`24 Core abilities.pdf` §24.17) : pas de −2" en "take to the skies".
- **Super-Heavy Walker** (§24.35) : traverse horizontalement les sections ≤**4"** de haut ;
  option de traversée du dense (jet D6, 1 = battle-shock).
- **Indirect Fire** (`10 Shooting phase.pdf` §10.07) : seule voie de tir **sans LoS** (cible à couvert,
  malus) — pertinent contre une unité masquée par un étage.
- **Transports** (`18 Transports.pdf` §18.02/18.04) : embarquement ≤3" (3D) ; débarquement = set up
  "wholly within 3"/6"" — finir sur un étage bas n'est pas interdit par le texte.
- **Surge move** (`21 Flying and surging.pdf` §21.01-02) : "closest enemy" mesuré en 3D, coût vertical
  hérité de Moving (03). Take to the skies non applicable au surge.
- Sans règle verticale propre (vérifié) : 05 Attack sequence, 07 Battle round, 08 Command phase,
  15 Stratagems, 19 Attached units. Le glossaire étendu (ground level, stable…) n'existe pas dans la
  doc locale (renvoi de l'appendix vers l'app officielle).

---

## 3. État actuel du code (fondations existantes)

### 3.1 Modèle d'état — 2D strict, **aucune** verticalité
- Position unité = entiers `col`/`row` (odd-q), posés dans `UnitFactory.create_unit`
  ([game_state.py:124-126](file:///home/greg/40k/engine/game_state.py)) et `_build_enhanced_unit` (`:768-769`).
- Source de vérité runtime = `units_cache`, construit par `build_units_cache`
  ([shared_utils.py:586](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
  Entrée : `{col, row, HP_CUR, player, VALUE, BASE_SHAPE, BASE_SIZE, orientation,
  occupied_hexes:Set[(col,row)], occupied_hexes_by_model:{model_id:(col,row)}}` (`:654-672`).
- `models_cache` par figurine (`:557-582`), `occupation_map : {(col,row) → unit_id}` (`:610`).
- **Recherche exhaustive** `z_level|elevation|storey|floor|altitude|height_level` sur `engine/` : **zéro** résultat.
  Les `z_` existants = coordonnées **cube 2D** pour distances hex (pas d'altitude). `floor` = `math.floor`.
  Le seul "vertical" = commentaires "ignore vertical" sur FLY (conceptuel, non implémenté).

### 3.2 Empreinte (footprint) multi-hex — **déjà développée**
- `compute_occupied_hexes(center_col, center_row, base_shape, base_size, orientation)`
  ([hex_utils.py:1064-1099](file:///home/greg/40k/engine/hex_utils.py)) : dispatch round/oval/square,
  rotation par `orientation × 60°`.
- Champs socle sur l'unité : `BASE_SHAPE`, `BASE_SIZE`, `orientation` ([game_state.py:149-151](file:///home/greg/40k/engine/game_state.py)).
- Point d'entrée moteur `_compute_unit_occupied_hexes` ([shared_utils.py:263-286](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)) —
  empreinte multi-hex calculée **seulement** si `engagement_zone > 1` (`:274`, valeur déjà scalée
  ×`inches_to_subhex` au chargement → board ×10 en pratique) **et** `base_size > 1` ; sinon 1 unité = 1 cellule.
- `occupied_hexes` unité = union des footprints des figs vivantes (`:728-734`) ;
  `occupied_hexes_by_model` = footprint par figurine.
- Masques de placement / distances bord-à-bord : `spatial_relations.py`, `combat_utils.py:327-386`.

### 3.3 Ligne de vue — per-model, binaire, occlusion 2D
- Point d'entrée `has_line_of_sight` ([combat_utils.py:512](file:///home/greg/40k/engine/combat_utils.py)) →
  source unique `compute_unit_los` ([shooting_handlers.py:3895](file:///home/greg/40k/engine/phase_handlers/shooting_handlers.py)),
  cœur `_compute_unit_los_uncached` (`:3936`).
- Découpe cible en empreintes par-figurine ; visible si ≥1 modèle a ≥1 cellule à ligne dégagée (`:3975-4014`).
- Primitive de tracé `_los_line_segment_clear` (`:3763`) : trace `hex_line` ([hex_utils.py:260](file:///home/greg/40k/engine/hex_utils.py),
  cube-lerp) et inspecte chaque cellule intermédiaire.
- **Bloque** (`:3777-3782`) : un **mur** (`wall_set`, toujours) ; une **area obscuring**
  (sauf si elle appartient au tireur ou à la cible, règle 13.10).
- "Peek de coin" déjà géré : vantages latéraux du socle (`_shooter_lateral_vantage_hexes`, `:3716`).
- Miroir WASM frontend `has_los_fast` que la primitive Python doit refléter (commentaire `:3774`).
  Le miroir est en **Rust** ([lib.rs:84](file:///home/greg/40k/frontend/wasm-los/src/lib.rs)) : toute
  évolution LoS impose de modifier le Rust **et de rebuilder le wasm**.
- Caches 2D sans notion de niveau : `hex_los_cache` ([combat_utils.py:527-538](file:///home/greg/40k/engine/combat_utils.py)),
  clé `((col,row),(col,row))` ; `pathfinding_distance_cache` (`:495-497`) idem.
- Murs = `game_state["wall_hexes"]` (hexes 2D JSON, consommés par deployment_handlers/combat_utils) ;
  `terrain_areas = {id, obscuring, polygon_vertices, hexes}`
  ([terrain_utils.py:4-8](file:///home/greg/40k/engine/terrain_utils.py)) — **aucun champ hauteur/étage**.

### 3.4 Mouvement — champ géodésique any-angle, terrain binaire
- Budget `get_squad_move_budget` ([shared_utils.py:3404](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)) :
  normal/fall_back = `MOVE` ; advance = `MOVE + roll×échelle` ; charge = `2D6×échelle` ;
  pile_in/conso = `3×échelle`. Malus "take to the skies" −2" déjà présent (`:3435-3438`).
- Hexes atteignables = `geodesic_field` ([hex_utils.py:1870](file:///home/greg/40k/engine/hex_utils.py),
  Lazy Theta*, clearance = rayon socle) via `_euclidean_move_field` ([geodesic_move.py:40](file:///home/greg/40k/engine/phase_handlers/geodesic_move.py)).
  Charge réutilise **exactement** ce champ.
- **Aucun coût de terrain** (pas de difficult terrain) : terrain **binaire** obstacle/libre.
  Toggles de traversée `_get_move_traversal_rules` ([movement_handlers.py:1725](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)),
  config `game_config.json:40-42`. Murs bloquent toujours ; FLY = disque euclidien ignorant murs+figs (`:1608-1639`).
- Échelle `inches_to_subhex` (config board) ; métrique par règle `game_config.json:48` (`hex`/`euclidean`).

### 3.5 Rendu (PIXI) — briques réutilisables
- Rendu statique dans `drawBoard` ([BoardDisplay.tsx:1831](file:///home/greg/40k/frontend/src/components/BoardDisplay.tsx)),
  overlays + UI dans [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx), figs dans [UnitRenderer.tsx](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx).
- **Zone au sol type terrain** (modèle à copier pour l'empreinte d'étage) : bloc terrain
  [BoardDisplay.tsx:2058-2153](file:///home/greg/40k/frontend/src/components/BoardDisplay.tsx),
  tracé polygone `:2124-2137` = `beginFill(zoneColor, fillAlpha)` (0.1, ou 0.18 si obscuring)
  + `lineStyle(Math.max(1.5, HEX_RADIUS*0.3), color, 0.85)`, ajouté à `baseHexContainer`. Type `ObjectiveZone` ([useGameConfig.ts:43-52](file:///home/greg/40k/frontend/src/hooks/useGameConfig.ts)).
- **Changement de couleur selon état** (blanc si occupé) : reprendre le motif `objectiveControl` + ternaire
  (`BoardDisplay.tsx:2080-2094`, `:2278-2293`). Chaque `lineStyle(w,color,alpha)` démarre un tracé de couleur.
- **Mode ghost existant** (chaîne complète dans le renderer) : flag `modelGhost?: boolean[]`
  ([UnitRenderer.tsx:143-148](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx)),
  socle `circleAlpha=0.45` (`:816-822`), sprite `alpha=0.42` (`:1176-1178`), texte `0.65` (`:1255-1258`).
  ⚠️ Seul producteur actuel : la **fig active en cours de déplacement** (BoardPvp.tsx:8977-8980), avec
  tint move-preview → réutilisation directe = **collision sémantique/visuelle** (fig d'un autre étage
  indistinguable d'une fig en transit). Prévoir un 2e flag (ex. `modelLevelGhost`) ou un style paramétrable.
- **Bouton loupe zoom** : `<button>` [BoardPvp.tsx:10533-10550](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx).
  Deux divs imbriquées : parente `:10494-10505` (`position:absolute, top:8, right:8, zIndex:1600`, colonne),
  flex row `:10507-10513` (conteneur direct du bouton). Frère horizontal → row `:10507` ; empilé → colonne `:10494`.

---

## 4. Reformulation du projet, mappée sur le code

La feature = **ajout d'un axe vertical `level` (entier, 0 = sol)** dans le modèle de jeu, puis
propagation dans occupation / mouvement / LoS, puis rendu. L'affichage est la partie **facile** ;
le modèle + LoS 3D est le vrai chantier.

### 4.1 Modèle de données (fondation)
- Ajouter un champ `level` (int, défaut 0) sur : dict unité et `models[]`
  ([game_state.py:117-172](file:///home/greg/40k/engine/game_state.py)),
  puis le propager dans `units_cache` / `models_cache` ([shared_utils.py:557-582, 654-672](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)),
  et jusqu'au **frontend** (payload API + types TS Unit) — aujourd'hui aucune notion de niveau côté front.
- **Impact RL (non bloquant)** : `level` change l'espace d'observation (obs builder, `action_decoder.py`).
  Le RL étant HS et destiné au retrain, aucune rétro-compat à préserver → prévoir simplement le canal
  `level` dans l'obs dès la conception (cf. §5.7).
- `occupation_map` : clé `(col,row)` → `(col,row,level)` (`shared_utils.py:610`). Deux figs peuvent
  occuper le même `(col,row)` à des niveaux différents.
- **Définition de l'empreinte d'étage — SOURCE = fichier terrain du board**
  (`config/board/<board>/terrain/terrain-*.json`, tableau `terrain[]`), là où sont déjà déclarées les
  ruines (empreinte au sol = `vertices` en subhex + `walls[]`). Ex. actuel :
  `{ "id": "ruin_center_OK", "shape": "polygon", "vertices": [[85,120],...], "objective": true }`.
  **Format retenu = B (étages rattachés à la ruine parente)** : sous-tableau `floors` dans l'entrée ruine :
  ```json
  { "id": "ruin_center_OK", "vertices": [[85,120],[135,120],[135,180],[85,180]], "objective": true,
    "floors": [ { "level": 1, "height_inches": 3, "vertices": [[...]] } ] }
  ```
  Le lien empreinte-au-sol ↔ étages est conservé (nécessaire pour LoS Solid ≤3", blanchiment/ghost par
  ruine). `height_inches` sert aux seuils règles (3" Solid/Plunging, 5" vertical).
- Ce format JSON est parsé côté moteur dans `terrain_areas`
  ([terrain_utils.py:4-8](file:///home/greg/40k/engine/terrain_utils.py)) — à étendre pour porter `floors`
  par étage `{level, height_inches, vertices, hexes}`. **À figer en premier dans le chantier 1.**

### 4.2 Occupation d'un étage (poser une fig)
- Règle officielle (§13.06) : empreinte de la fig **entièrement** incluse dans le polygone de l'étage
  (0% de débordement) + mot-clé INFANTRY/BEASTS/SWARM/FLY/MONSTER.
  Réutiliser `compute_occupied_hexes` ([hex_utils.py:1064](file:///home/greg/40k/engine/hex_utils.py)) et tester
  l'inclusion des hexes du footprint dans les `hexes` de l'étage.
- **Décision requise** (§2.6) : remplacer par le seuil maison "hex central + ≥50% du footprint dedans" ?
  → À trancher. Recommandé : seuil **paramétrable** (config), défaut = règle officielle (100%), pour ne pas
  diverger silencieusement des règles (cf. mémoire `feedback_mirror_move_phase`).

### 4.3 Mouvement vertical

> ✅ **Spike de faisabilité validé** (POC isolé, réutilisant le vrai `geodesic_field`) :
> l'archi "un champ géodésique par niveau + chaînage aux hexes de transition, coût vertical cumulé"
> **fonctionne sans réécrire la primitive de pathfinding**. Option A (transitions implicites au
> périmètre) retenue. Deux enseignements du spike à respecter en implémentation :
> 1. **Facturer le pas d'approche horizontal** vers le mur : coût d'entrée sur un hex de bord `t` =
>    `field0[g] + dist_horiz(g,t) + coût_vertical` — oublier le segment `g→t` crée une fuite d'un hex
>    (bug attrapé au 1er run du spike).
> 2. `geodesic_field` est **single-source** (g=0 sur un seul start) → le chaînage multi-entrées coûte
>    **N relances** (N = hexes de périmètre atteignables). Sur board ×10 avec grandes ruines, à surveiller ;
>    optimisation prod = variante **multi-source** (Dijkstra avec `g` initial par entrée), modif locale
>    de la primitive, pas une refonte.

- `geodesic_field` ([hex_utils.py:1870](file:///home/greg/40k/engine/hex_utils.py)) est **strictement
  planaire** : le raccourci Lazy Theta* (rattachement à l'ancêtre via segment clear) suppose un plan
  continu — injecter une arête inter-niveaux dans le champ **casse cette hypothèse**. Architecture cible
  (validée par le spike) : **un champ géodésique par niveau**, chaînés aux **hexes de transition**
  (périmètre de l'étage supérieur, approché depuis les hexes de sol adjacents), coût au raccord =
  approche horizontale `+` distance verticale mesurée (`|height(level_a) − height(level_b)|`),
  **cumulée** au budget (§13.06), + contrainte ≤ ½" horiz. du décor pendant l'ascension.
- Le disque FLY ([movement_handlers.py:1608-1639](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py))
  est un calcul NumPy planaire séparé — à traiter aussi.
- Restrictions par mot-clé (§2.2) : INFANTRY/BEASTS/SWARM libres ; MOBILE horizontal ; VEHICLE gravit >2"
  sans finir en hauteur. À brancher sur `_get_move_traversal_rules` ([movement_handlers.py:1725](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)).
- FLY "take to the skies" : ignore le coût vertical (le malus −2" existe déjà, `shared_utils.py:3435-3438`).

### 4.4 Ligne de vue 3D
- Enrichir la primitive `_los_line_segment_clear` ([shooting_handlers.py:3763](file:///home/greg/40k/engine/phase_handlers/shooting_handlers.py))
  et `hex_line` pour tenir compte du niveau observateur/cible :
  - Solid (§13.11) : bloquer la LoS traversant une ouverture de ruine **si le segment passe ≤3" du sol** ;
    au-dessus de 3", tracé normal. Nécessite `height_inches` de l'étage traversé.
  - Obscuring (§13.10) : exclusion d'area inchangée, mais une fig posée **sur** l'étage appartient à cette area.
  - Étendre la clé du `hex_los_cache` ([combat_utils.py:527-538](file:///home/greg/40k/engine/combat_utils.py))
    au niveau — aujourd'hui `((col,row),(col,row))`, deux paires à niveaux différents collisionneraient.
  - Répercuter la même logique dans le **miroir WASM** `has_los_fast`
    ([lib.rs:84](file:///home/greg/40k/frontend/wasm-los/src/lib.rs), commentaire `:3774`) :
    modifier le Rust **et rebuilder le wasm** — sinon front/back divergent.
- Plunging Fire (§22.05) : +1 BS si cible **visible** avec ≥1 fig au sol ET (tireur sur section ≥3"
  OU tireur TOWERING avec cible ≤12"). À ajouter au calcul BS du tir.

### 4.5 Rendu
- **Empreinte d'étage** : nouveau bloc dans `drawBoard` (à côté de `BoardDisplay.tsx:2058-2153`), tracé polygone
  copié de `:2124-2137`, couleur = `terrainColor` (contour non-occupé) / **blanc** si occupé (motif `objectiveControl` `:2080-2094`).
  Ne dessiner que les empreintes pertinentes au niveau courant.
- **Bouton "feuilles empilées"** : `<button>` frère inséré dans la div flex [BoardPvp.tsx:10507-10513](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx),
  style du bouton loupe `:10538-10547`, badge n° niveau en bas-droite ; état `currentLevel` (nouveau, à côté de `boardZoom` `:1732`).
- **Vue mono-niveau + ghost** : ne rendre que les figs du niveau courant ; passer en ghost (flag `modelGhost`
  déjà existant [UnitRenderer.tsx:143-148](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx)) les figs d'un
  autre niveau dont le footprint chevauche l'empreinte de l'étage affiché.

---

## 5. Divergences code/règles à trancher (checkpoints décision)

1. **Occupation d'un étage** : règle officielle = base **100% dedans** (§13.06). Idée initiale = "hex central + 50%".
   → Choisir ; recommandé : seuil paramétrable, défaut règles.
2. **Coût vertical** : les règles cumulent la distance verticale au M (§13.06). Le moteur n'a **aucun coût de
   terrain** aujourd'hui (§3.4). → Introduire le 1er coût non-binaire du pathfinding (arêtes inter-niveaux).
3. **Seuil 3" (Solid/Plunging)** et **5" (coherency/engagement)** : nécessitent une hauteur réelle par étage
   (`height_inches`), aujourd'hui inexistante. → Ajouter au modèle de terrain.
4. **Parité WASM** : toute évolution LoS doit être répliquée dans `has_los_fast`
   ([lib.rs:84](file:///home/greg/40k/frontend/wasm-los/src/lib.rs)) — code **Rust**, donc modification
   + **rebuild du wasm** obligatoires ; risque de divergence back/front.
5. **Parité 2D du moteur hors move/LoS** : collisions/placement (`build_occupied_positions_set`
   [shared_utils.py:289](file:///home/greg/40k/engine/phase_handlers/shared_utils.py),
   `_inflate_obstacles_by_footprint` [geodesic_move.py:14](file:///home/greg/40k/engine/phase_handlers/geodesic_move.py)),
   engagement/cohésion/fight (masques `eng_bad`, adjacence `spatial_relations`, éligibilité fight),
   déploiement, contrôle d'**objectifs** (règle tranchée en §2.9 : appartenance à la terrain area, ou
   cylindre 3"/5" pour un pion — à implémenter par niveau), hidden/cover (`model_within_terrain` 2D) —
   tout est 2D aujourd'hui, sans niveau une fig à l'étage bloquerait/serait bloquée par le sol sous elle.
6. **Mesures 3D** (§2.7) : portée d'arme, distance de charge, "closest enemy" (surge) se mesurent en
   **3D socle-à-socle** — toutes les distances du moteur (`ranged_edge_distance`, budgets de charge,
   seuils) sont aujourd'hui 2D. Ajouter la composante verticale (`height_inches` des niveaux) aux
   calculs de distance, sauf exceptions horizontales explicites (réserves/Deep Strike >8" horiz).
7. **RL (non bloquant)** : le RL est actuellement HS et sera **retrain de toute façon** → pas de contrainte
   de rétro-compat. `level` s'intègre au futur espace d'observation/action (obs builder,
   `action_decoder.py`) **dès sa conception**. Ce n'est plus un go/no-go, juste une exigence de design
   du chantier 1 (prévoir le canal `level` dans l'obs).

---

## 6. Découpage en chantiers (ordre suggéré)

> ✅ **Préalable technique levé** : le spike pathfinding 3D (§4.3) confirme la faisabilité sur l'archi
> actuelle. Le RL n'est plus un go/no-go (§5.7). Les chantiers ci-dessous peuvent démarrer.

1. **Modèle d'état multi-niveau** — ⏳ **EN COURS** :
   - ✅ Parsing `floors` (format B) dans `_load_terrain_areas_from_ref` + `_parse_terrain_floors`
     ([game_state.py](file:///home/greg/40k/engine/game_state.py)) — validation stricte, `floors` absent → `[]`.
   - ✅ Champ `level` sur l'unité (`create_unit` + `_build_enhanced_unit`), helper `_validate_level` (0 = sol).
   - ✅ Propagation `level` dans `units_cache` + `models_cache` (ancre + par-figurine)
     ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
   - ✅ Exposition payload API (`_UNITS_CACHE_FRONTEND_KEYS` + `level_by_model`) + types TS
     (`Unit.level`, `units_cache.level`/`level_by_model`) — tsc vert, chargement scénario réel vert.
   - ⏸️ **Différé** : `occupation_map`/`occupied_hexes` restent 2D (collisions par niveau → chantier 2) ;
     canal `level` dans l'obs RL (§5.7) → au retrain, quand les mécaniques multi-niveaux existeront.
   *Prérequis de tout le reste. Aucun impact visuel.*
2. **Occupation & placement** — ⏳ **EN COURS** :
   - ✅ **2a Validation "poser sur un étage"** (§13.06, décision §5.1 = 100% dedans par défaut) :
     - `unit_can_occupy_upper_floor(keywords)` — gate mot-clé INFANTRY/BEASTS/SWARM/FLY/MONSTER
       ([game_state.py](file:///home/greg/40k/engine/game_state.py)).
     - `floor_hexes_at_level(terrain_areas, level)` + `footprint_within_floor(...)` (0 débordement)
       + validateur composé `validate_floor_placement(unit, col, row, level, terrain_areas) -> (ok, reason)`
       ([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)). Tous testés (conditions cumulatives 13.06).
       Note : "stable" (13.06) non chiffré → non modélisé (surface d'étage supposée plane).
     - Prêt à câbler dans le déploiement (poser à l'étage) et la fin de move (valider l'atterrissage).
   - ⏸️ **2b Collisions/placement par niveau** (§5.5 : `build_occupied_positions_set`, masques) : **différé**.
     Raison : le filtrage par niveau n'a de sens qu'avec des figs réellement à des niveaux différents
     (aujourd'hui tout est au niveau 0 → no-op) ; un param `level` non consommé serait du code spéculatif.
   - 🧱 **Décision — murs verticaux prolongés** : les murs d'une ruine montent sur toute la hauteur.
     Les mêmes `wall_hexes` (2D) s'appliquent donc à **tous les niveaux** : on ne peut jamais *finir* sur
     un hex de mur, quel que soit l'étage (cohérent §13.06 : l'infanterie *traverse* les murs de ruine
     en mouvement mais ne s'y *arrête* pas). Pas de format « murs par niveau ». Nuance LoS pour plus tard :
     au-dessus de 3", la vue passe par les ouvertures (§13.11) → chantier LoS 3D, pas le déploiement.
   - ✅ **2c Déploiement à l'étage** (câblage `level` dans le pipeline de déploiement) — FAIT & testé :
     1. plan `(mid,c,r)` → `(mid,c,r,level)` — `_parse_plan` accepte 3 ou 4 (front compatible)
        ([deployment_handlers.py](file:///home/greg/40k/engine/phase_handlers/deployment_handlers.py)).
     2. `deployment_preview_plan` niveau-conscient : `out_of_bounds`/`out_of_zone`/`on_wall` restent **2D
        inchangés** (horizontal + murs verticaux prolongés) ; `on_other`/`intra` filtrés au **même niveau** ;
        + `validate_floor_placement` pour level≥1.
     3. `_deployed_occupied_positions(…, level)` filtré par niveau (branche `level=None` = comportement historique).
     4. commit : `update_model_position(…, level)` persiste `model["level"]` → ancre `units_cache["level"]`
        → `unit["level"]` ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
     5. API : parsing squad-plan tolère 3/4-uplets (plus de drop silencieux) ([api_server.py](file:///home/greg/40k/services/api_server.py)).
     **Test bout-en-bout (6 cas)** : infantry sur étage→vert, vehicle→rouge (mot-clé), hors-empreinte→rouge
     (débordement), sol 3-uplet→vert (non-régression), collision niveau-consciente (même (col,row) : sol→rouge,
     étage→vert), commit persistant level=1 sur models_cache/units_cache/units. Suite complète verte.
   - ⏸️ **2b Collisions par niveau hors déploiement** (move/charge/fight via `build_occupied_positions_set`) :
     reste au chantier 3 (mouvement vertical), même principe additif que `_deployed_occupied_positions`.
3. **Mouvement vertical** — ⏳ **EN COURS** :
   - ✅ **3a Champ multi-niveaux (cœur algo)** : `reachable_multilevel_field`
     ([geodesic_move.py](file:///home/greg/40k/engine/phase_handlers/geodesic_move.py)) — Dijkstra sur
     nœuds `(col,row,level)`, chaque niveau développé par le VRAI champ any-angle `_euclidean_move_field`,
     niveaux consécutifs reliés par `_build_level_transitions` (approche horizontale + vertical cumulé, §13.06).
     Gère montée **N niveaux empilés**, descente, seuil vertical. Testé (pile 3 niveaux : coût L2 = borne
     basse exacte). **Isolé, non câblé dans `movement_handlers` → zéro régression 2D.** Note perf : champ
     relancé par entrée de transition (single-source), optim multi-source possible plus tard.
   - ✅ **3b Restrictions mot-clé** (§2.2) : deux flags sur `reachable_multilevel_field` —
     `allow_vertical` (False = MOBILE/VEHICLE et tout ce qui n'a pas INFANTRY/BEASTS/SWARM/FLY/MONSTER,
     via `unit_can_occupy_upper_floor` → aucune transition, reste au sol) et `ignore_vertical_cost`
     (FLY « take to the skies » §21.03 → montée/descente à coût horizontal seul). Testés (FLY monte à
     coût horizontal ; sans capacité → aucun étage). **Simplification documentée** : le modèle de niveaux
     ne distingue pas escalade extérieure/intérieure ni sections <2" → la nuance « VEHICLE gravit >2"
     par l'extérieur sans y finir » n'est pas représentée (hors périmètre).
   - ✅ **2b Occupation niveau-consciente** : `build_occupied_positions_set(…, level)` +
     `build_enemy_occupied_positions_set(…, level)` + helper `_occupied_hexes_at_level`
     ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)). Param additif
     `level=None` = chemin historique **byte-identique** (tous les appelants actuels inchangés → zéro
     régression) ; un entier filtre par niveau (figs à des étages différents ne se gênent pas). Testé.
   - ⏸️ **3c Câblage `movement_handlers`** — **CADRÉ, pas encore codé**. Le producteur
     `movement_build_valid_destinations_pool` (~500 l., chemins fly/sol vectorisés numpy + géodésique)
     renvoie un pool **plat `List[(col,row)]` sans niveau**. Changement transversal (back producteur +
     preview + **frontend** qui dessine + commit qui déballe), non vérifiable bout-en-bout sans UI +
     scénario à étages → **étape délibérée**, idéalement avec le chantier 6 (UI).

     **DÉCISION — forme du pool = B (dict par niveau)**, cible long terme. Rationale : `level` est déjà
     dimension première partout (units_cache/models_cache/occupation/champ) ; le pool doit suivre, le sol
     n'étant pas un cas spécial mais `pool[0]`. Une seule structure, une seule logique (évite la dette
     d'un traitement sol≠étages, cf. principe move/déploiement miroir). Écarté : C (side-channel = dette
     permanente sol/étages) ; A (triplets = re-filtrage front + casse tout unpack `(col,row)`).
     ```
     valid_move_destinations_pool = { 0: [(c,r),…], 1: [(c,r),…], … }   # cible B
     ```
     **Décisions liées** :
     - Transport commit : l'action de move ajoute `destLevel` (optionnel, défaut 0) — sans quoi (10,10)@sol
       et (10,10)@étage sont indistinguables au commit.
     - Filtrage preview : le back envoie **tous** les niveaux ; le front dessine `pool[niveau_courant]`
       (vue mono-niveau, bouton d'étage).

     **PLAN DE MIGRATION SÛR (2 temps, zéro rupture)** :
     1. Introduire le dict `{level:[…]}` + exposer une **clé miroir transitoire**
        `valid_move_destinations_pool = pool[0]` → le front actuel ne casse pas. **✅ FAIT.**
     2. Migrer les consommateurs front un par un, puis **retirer le miroir** (dette transitoire tracée). ⏸️

     **Steps d'implémentation :**
     1. ✅ **Adaptateur** `_multilevel_floor_destinations`
        ([movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) →
        `reachable_multilevel_field` + obstacles par niveau (**2b**) + budget réel (`move_range`) + floors
        (`floor_hexes_at_level`) + flags mot-clé (`unit_can_occupy_upper_floor`, FLY) + validation fin de
        move (`validate_floor_placement`). Testé isolément (étages 1&2 atteignables, vehicle→{}, no-op sans floors).
     - ⚡ **Perf (critique)** : la 1ʳᵉ version (single-source relancé par entrée de transition + complément
       du plancher `all_cells - fh`) était O(périmètre × O(board)) → **>24 s/sélection** sur board 220×300.
       Corrigé en 3 temps : (a) **anneau** au lieu du complément (obstacles O(périmètre)) ; (b)
       `geodesic_field_multi_source` + `reachable_multilevel_field` en **Dijkstra par-niveau multi-source**
       (1 passe/niveau au lieu d'1 par entrée) ; (c) **pré-check de portée** (retour `{}` immédiat si aucun
       étage à portée). Résultat : unité loin d'une ruine **0.8 ms**, étage moyen ~100 ms, gros étage
       (1271 hex) ~400 ms. Correctness préservée (coûts optimaux inchangés dans les tests).
     2. ✅ **Pool forme B + miroir** intégré dans `movement_build_valid_destinations_pool` (point sol) :
        `game_state["valid_move_destinations_pool_by_level"] = {0: sol, 1:[…], 2:[…]}`,
        `valid_move_destinations_pool` = miroir = pool[0]. **Testé end-to-end** (avec étages : sol=399/L1=81/L2=25 ;
        sans étage : `{0: liste}`, pool 2D **byte-identique** → zéro régression). Garde no-floors = retour `{}`
        de l'adaptateur avant tout accès → sûr.
     3. ✅ validation fin de move sur étage (`validate_floor_placement`) — intégrée dans l'adaptateur.
     4. ✅ **Commit du niveau (destLevel)** : plan de move `(mid,c,r)`→`(mid,c,r,level)` sur tout le chemin —
        `commit_move` (niveau absent = **garder le niveau courant**, pas de reset sol), `_parse` du
        `movement_commit_move_plan_handler`, `movement_preview_move_plan` **niveau-conscient** (other_occ par
        niveau + `validate_floor_placement` + collision intra même niveau), sync `unit["level"]`, et API
        `preview_move_plan` (préserve le niveau, plus de troncature à 3). Testé (commit persiste/conserve/reset
        le niveau ; preview move étage valide, vehicle refusé).
     - ✅ **Scénario de test à étages** : `config/board/44x60x5/{terrain/terrain-floors-test.json,
       scenario/scenario_floors_test.json}` — ruine centrale avec `floors` L1(3")/L2(6"), chargé & rasterisé
       (L1=1200, L2=400 hexes) via le vrai loader. Débloque la validation front + réelle.
     - ⏸️ **RESTE** : (a) chemin **FLY** du producteur (retourne avant le point sol — fly+étages à part) ;
       (b) `validate_move_plan` **niveau-aveugle** : un move à l'étage AU-DESSUS d'une case occupée au sol
       est encore bloqué par ce validateur 2D (+ règles d'engagement vertical 2"/5" §2.5 non modélisées) —
       chunk à part ; le cas courant (sol libre sous la destination) marche ;
       (c) **frontend** (chantier 6) : consommer `_by_level`, bouton d'étage, dessiner `pool[niveau_courant]`,
       envoyer `destLevel`, retirer le miroir.
4. **Distances 3D / engagement / cohésion / objectifs** : composante verticale dans les mesures
   (portée d'arme, charge, §5.7) ; règle 2" horiz + 5" vert sur les masques `eng_bad`, adjacence,
   éligibilité fight, coherency ; contrôle d'objectif par appartenance à la terrain area (§2.9) ou
   cylindre 3"/5" pour un pion. Charge/pile-in/consolidation héritent du moteur vertical (§2.8).
5. **LoS 3D** : Solid ≤3", Plunging +1 BS (avec branche TOWERING), extension `hex_los_cache`,
   parité WASM (Rust + rebuild).
6. **Rendu/UI (frontend)** — ⏳ **EN COURS** (visuel : à valider en lançant l'app) :
   - ✅ **6a Données + bouton d'étage** : floors exposés au front (`_zone_entry` rasterise les `floors`
     → `boardConfig.terrain_zones[].floors`, type `TerrainFloor` dans
     [useGameConfig.ts](file:///home/greg/40k/frontend/src/hooks/useGameConfig.ts)) ; état `currentLevel`
     + `maxFloorLevel` (dérivé des floors) + **bouton feuilles empilées** (🗂 + n° niveau en bas-droite,
     cycle les niveaux) à côté de la loupe, masqué si aucun étage ([BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)). tsc vert.
   - ✅ **6b Empreinte d'étage** dans `drawBoard` ([BoardDisplay.tsx](file:///home/greg/40k/frontend/src/components/BoardDisplay.tsx)) :
     tracé polygone de chaque plancher (couleur terrain, **blanc si le niveau est occupé** par ≥1 fig).
     Vue mono-niveau (sol → tous les étages en indicateur ; à un étage → planchers de ce niveau).
     `currentLevel` + `occupiedFloorLevels` threadés via `DrawBoardOptions` + clé de cache statique `bcKey`
     + deps de l'effet de dessin ([BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)) →
     redessine au clic du bouton. tsc vert, backend suite verte. **À valider visuellement.**
   - ⏸️ **6c Vue mono-niveau + ghost** : filtrer les figs par niveau (via `level_by_model` déjà exposé),
     ghost pour les figs d'un autre niveau qui débordent (nouveau flag, pas `modelGhost`).
   - ⏳ **6c-deploy Déploiement à l'étage** — **constat archi + décision A** :
     La logique de déploiement (`deploy_preview` + `deploy_commit`) vit dans `useEngineAPI`, appelé dans
     **BoardWithAPI** — donc **au-dessus** de `BoardPvp` où `currentLevel` a été mis. L'état du bouton
     d'étage est sous la logique qui en a besoin. De plus **preview ET commit** doivent envoyer le niveau
     (sinon le voile rouge valide au sol pendant que le commit pose à l'étage → placement d'étage illégal
     non détecté, §13.06 contournée).
     **DÉCISION = Option A — ✅ FAIT (tsc vert, à valider visuellement)** :
     `currentLevel` remonté dans `BoardWithAPI` (état + `currentLevelRef` synchronisée) →
     passé à `useEngineAPI` (option `currentLevelRef`) ET à `BoardPvp` (props `currentLevel` +
     `onCurrentLevelChange`, avec **fallback état interne** → `BoardReplay`/tutorial intacts).
     `deploy_preview` **et** `deploy_commit` envoient le plan `[mid,col,row,level]` quand niveau ≥ 1
     (sinon 3-uplet inchangé). Chaîne complète : bouton d'étage → preview valide §13.06 → commit persiste
     le niveau → `unit.level` → `occupiedFloorLevels` → empreinte **blanchie**.
   - ✅ **Niveau EFFECTIF par figurine** (`resolve_model_floor_level`, [terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)) :
     `currentLevel` est un HINT de vue. Le niveau réel d'une fig = `currentLevel` **si son empreinte tient
     sur le plancher de ce niveau**, sinon **sol (0)**. Appliqué dans `deployment_preview_plan` ET le commit
     `_apply_deploy_plan`. Corrige le bug : une **escouade mixte** déployée en vue étage (1 fig sur le plancher
     + autres au sol) ne rejette plus les figs de sol au voile rouge — elles redeviennent 'sol'. (À rappliquer
     au **move** quand 6d enverra `destLevel`.)
   - ✅ **Badge étage** : par-figurine, haut-gauche de l'icône, **numéro seul blanc sur rond noir**
     (niveau backend-autoritaire `level_by_model`/`level`). Même rayon que les badges du bas
     (`statusBadgeRadius`). Squad **réparti** (figs à niveaux différents) → **toutes** les figs affichent
     leur niveau (y compris 0) ; sinon seulement les figs à l'étage (≥1). `modelLevels` threadé
     BoardPvp → `renderUnit` → `UnitRenderer.renderFloorBadge`
     ([UnitRenderer.tsx](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx)).
   - ✅ **Empreinte colorée par niveau** (palette badge : 1 vert, 2 orange, 3 rouge ; 0 = terrain) :
     vue étage L → voile + contour couleur(L) ; vue sol → pas de voile, contour = couleur du **1er étage
     occupé** (le plus bas), sinon terrain ([BoardDisplay.tsx](file:///home/greg/40k/frontend/src/components/BoardDisplay.tsx)).
     Occupation par-fig (`occupiedFloorLevels` ← `level_by_model`, et non `unit.level` ancre).
   - ✅ **Voile au-dessus des previews** : le voile (vue étage ≥1) est dessiné dans `highlightContainer`
     (zIndex 5000 + `sortableChildren`), à chaque draw → passe **par-dessus les zones de preview tir/move**
     (zIndex 0 dans ce conteneur), sous les unités. Contour sol reste dans `baseHexContainer`.
   - ✅ **Badge dynamique au drag** : pendant un move/déploiement preview, le niveau du badge est dérivé
     LIVE de la position provisoire (`floorHexKeysByLevel`, approx. hex-ancre ; commit backend autoritaire).
   - ✅ **Collision niveau-consciente (move)** : deux corrections —
     (a) `movement_build_valid_destinations_pool` filtre `build_occupied_positions_set`/`build_enemy_...`
     par le niveau du mover ;
     (b) **`validate_move_plan`** (appelée par le preview de move via `base_valid`) construisait `other_occupied`
     en **union tous niveaux** → c'était LE bug résiduel : une fig à l'étage était bloquée par une fig d'un
     autre squad au sol au même (col,row). Corrigé : `other_occupied_by_level` par niveau, check contre le
     niveau courant de chaque fig ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
     Testé (A niv1 → hex libre malgré B niv0 ; A niv0 → bloqué par B niv0). Tout au niveau 0 = inchangé.
   - ✅ **Vue mono-niveau (ghost)** : les figs qui ne sont pas au niveau d'affichage courant sont
     **atténuées** (fade). Flag `modelLevelGhost` (distinct de `modelGhost`, même rendu atténué),
     `modelLevels[i] !== currentLevel` ([UnitRenderer.tsx](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx)).
   - 💡 **Remarque (à faire) — couleur du mur dense support d'étage** : changer la couleur du mur dense
     d'une ruine **qui porte des étages** (pour le distinguer visuellement). Front-only : dans `drawBoard`,
     recolorer les `wall_hexes`/segments appartenant à une ruine dont l'entrée `terrain` a des `floors`
     (mapper mur→ruine par appartenance à l'empreinte, ou tagger les murs porteurs dans le JSON terrain).
   - ⏸️ Reste **engagement/EZ inter-niveaux** : `enemy_adjacent_hexes` (EZ) reste 2D (une fig ennemie à
     l'étage crée encore une EZ au sol) — à traiter avec la LoS/engagement 3D (règles 2"/5" §2.5).
   - ⏸️ **6c Vue mono-niveau + ghost** : n'afficher que les figs du niveau courant, ghost pour celles d'un
     autre niveau qui débordent (via `level_by_model` déjà exposé ; nouveau flag, pas `modelGhost`).
   - ⏸️ **6d Move preview par niveau** : consommer `valid_move_destinations_pool_by_level`, dessiner
     `pool[currentLevel]`, envoyer `destLevel` dans l'action de move (back déjà prêt).

   ### 🐞 BUGS OUVERTS (en cours de diagnostic) — l'utilisateur les voit encore malgré les fixes
   1. **Collision encore inter-niveaux au MOVE** d'une unité déployée à l'étage (une fig à l'étage est
      bloquée par une fig au sol au même hex). Déjà rendus niveau-conscients : `movement_build_valid_destinations_pool`
      (obstacles filtrés par `unit.level`) ET `validate_move_plan` (`other_occupied_by_level`,
      [shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)). Un test unitaire de
      `validate_move_plan` PASSE (niv1 ne collisionne pas niv0). → Donc soit le move ne passe pas par ces
      checks, soit **l'unité déployée est en réalité au niveau 0**.
   2. **Badge de niveau pas dynamique au drag** (et « pas toujours affiché »). Le fantôme collé à la souris
      est rendu par un `renderUnit` SÉPARÉ ([BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)
      ~ligne 9624, « Ghost de destination ») qui ne reçoit PAS `modelLevels`/`modelLevelGhost` — contrairement
      au `renderUnit` principal (~9221). À câbler (dériver le niveau live via `floorHexKeysByLevel`).

   **HYPOTHÈSE PRIORITAIRE (#1)** : l'unité déployée est persistée au **niveau 0** (`resolve_model_floor_level`
   la remet au sol car son empreinte ne tient pas ENTIÈREMENT sur le plancher, §5.1 règle 100%). Ça
   expliquerait TOUT d'un coup : collisions même niveau 0, pas de badge, pas de ghost.

   **DIAGNOSTIC EN PLACE** : log TEMPORAIRE `[DIAG DEPLOY-COMMIT]` dans `_apply_deploy_plan`
   ([deployment_handlers.py](file:///home/greg/40k/engine/phase_handlers/deployment_handlers.py)) — affiche
   dans le terminal API à chaque déploiement : `requested_level`, `effective` (niveau dérivé), `floorN_hexes`,
   `footprint_in_floor`. → Si `effective=0` : hypothèse confirmée (fig au sol, empreinte hors plancher) ;
   décision à prendre : agrandir le plancher de test, ou assouplir la règle (centre + X% au lieu de 100%,
   cf. §5.1). **Retirer ce log + `[DIAG ÉTAGES]`/`[DIAG DEPLOY]` (front) une fois résolu.**

Chantiers 1→5 sont backend (moteur + règles), 6 est frontend. 1 doit précéder tous les autres.
