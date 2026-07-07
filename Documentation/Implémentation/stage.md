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

### 2.11 Hauteur de figurine / garde au sol sous un étage — `03 Moving.pdf` §03.01 + encart SOLID §13.06
- `03 Moving.pdf` §03.01 "ENDING A MOVE" : une figurine ne peut pas finir son move "on another model or
  **partway through a surface of a terrain feature (e.g. a wall or ceiling)**". → une fig **plus haute que
  le plancher qui la surplombe** ne peut pas finir sous ce plancher : partout où son empreinte au sol est
  sous l'empreinte de l'étage, son sommet traverserait le plafond.
- Renfort — encart **SOLID** de §13.06 : "a model cannot end a move such that any part of it is through any
  enclosed part of that terrain feature that is 3" or less from ground level (…) protruding elements of
  models cannot be used to circumvent the visibility restrictions."
- ⚠️ **La hauteur réelle des figs n'est jamais chiffrée** dans les 25 PDFs (géométrie physique du modèle,
  comme la True LoS) → aucune valeur "règle" à importer ; c'est une donnée à ajouter au moteur.
- **Contrainte moteur = conditionnelle, pas absolue** : empreinte-sol interdite sous empreinte-étage
  **seulement si** `hauteur_fig > height_inches` du plancher au-dessus. Une fig plus courte que le plancher
  passe dessous librement (les règles ne l'interdisent pas).

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
   - ⏳ **2d Garde au sol sous un étage** (§2.11) — **champ front ajouté, reste backend + test** :
     - ✅ Champ `static MODEL_HEIGHT` (inches) sur **les 158 fichiers roster** (`frontend/src/roster/**`),
       juste après `BASE_SIZE`, avec commentaire `IMPORTANT: temporary indicative value`. **Valeurs
       indicatives temporaires** dérivées de `BASE_SIZE` : `≤20 → 2.5` (passe sous un étage 3"),
       `>20 → 4` (bloqué) ; ovale `[a,b]` → seuil sur `max` ; référence `Autre.BASE_SIZE` →
       `Autre.MODEL_HEIGHT` (miroir). tsc vert. **À affiner par figurine** (la hauteur réelle n'est pas
       une fonction stricte du socle, §2.11).
     - ⏸️ **RESTE** : propager `MODEL_HEIGHT` au **backend** (payload API → `units_cache`/`models_cache`)
       puis brancher le test de clearance dans `validate_floor_placement` / la fin de move : interdire une
       empreinte-sol chevauchant l'empreinte d'un étage **si** `MODEL_HEIGHT > height_inches` du plancher
       au-dessus (contrainte conditionnelle, §2.11).
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
     - ✅ **(b) `validate_move_plan` niveau-conscient** : lit le **niveau cible** dans le plan (4ᵉ élément)
       au lieu du niveau committé (`models_cache`) — un move à l'étage au-dessus d'une case occupée au sol
       n'est plus bloqué. Le call-site preview passe le niveau effectif. Le pool par-figurine
       `movement_build_model_destinations_pool` est passé niveau-conscient (cf. 6d).
     - ⏸️ **RESTE** : (a) chemin **FLY** du producteur (retourne avant le point sol — fly+étages à part) ;
       (b) règles d'**engagement vertical 2"/5"** (§2.5) toujours non modélisées (chantier 4) ;
       (c) pool **squad** (`movement_build_valid_destinations_pool`, suivi de bloc) et retrait du miroir
       transitoire `valid_move_destinations_pool` — le move **par-figurine** est complet (6d), le suivi rigide
       reste à migrer sur `_by_level`.
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
     tracé polygone de plancher, `currentLevel` threadé via `DrawBoardOptions` + deps de l'effet de dessin
     ([BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)) → redessine au clic du bouton.
     ⚠️ **Voir la refonte plus bas** (« Contour au sol : conteneur dédié dynamique + couleur PAR-DÉCOR ») :
     le contour blanc/statique décrit ici a été remplacé par un conteneur dynamique, une couleur par-décor
     et un z-order murs-au-dessus. tsc vert, backend suite verte.
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
     + autres au sol) ne rejette plus les figs de sol au voile rouge — elles redeviennent 'sol'.
     **✅ Rappliqué au MOVE** (preview `movement_preview_move_plan` + commit `commit_move_plan`, cf. 6d).
   - ✅ **Badge étage** : par-figurine, haut-gauche de l'icône, **numéro seul blanc sur rond noir**
     (niveau backend-autoritaire `level_by_model`/`level`). Même rayon que les badges du bas
     (`statusBadgeRadius`). Squad **réparti** (figs à niveaux différents) → **toutes** les figs affichent
     leur niveau (y compris 0) ; sinon seulement les figs à l'étage (≥1). `modelLevels` threadé
     BoardPvp → `renderUnit` → `UnitRenderer.renderFloorBadge`
     ([UnitRenderer.tsx](file:///home/greg/40k/frontend/src/components/UnitRenderer.tsx)).
   - ✅ **Empreinte colorée par niveau** (palette badge : 1 vert, 2 orange, 3 rouge ; 0 = terrain) :
     vue étage L → voile + contour couleur(L) ([BoardDisplay.tsx](file:///home/greg/40k/frontend/src/components/BoardDisplay.tsx)).
   - ✅ **Contour au sol : conteneur dédié dynamique + couleur PAR-DÉCOR** (refonte) :
     - Le contour au sol n'est **plus** dessiné dans le plateau statique (`baseHexContainer`) mais dans un
       **conteneur dédié `floorContours`** reconstruit à **chaque** draw. `lvl`/`ofl` retirés de la clé de
       cache statique `bcKey` → changer de niveau **ne reconstruit plus** le plateau (fini l'apparition
       progressive au retour niveau 1→0) et la couleur d'occupation est **live**.
     - **Vue sol** : on ne trace que la **forme du 1er étage** (`floor.level === 1`) de chaque décor. La
       forme du décor au sol reste assurée par le contour de zone statique (inchangé).
     - **Couleur par-décor** : terrain par défaut ; **vert/orange/rouge** (plus bas niveau occupé) **si ce
       décor précis a un étage occupé** — aucun impact sur les autres décors. Occupation localisée
       PAR-FIGURINE : centre par-modèle (`occupied_hexes_by_model`) situé dans le plancher de SON niveau
       (`level_by_model`), agrégé en `occupiedZoneLevels` (clés `zoneId@@level`), threadé via
       `DrawBoardOptions` + `occupiedZoneLevelsKey` dans les deps et le fingerprint highlights.
     - Trait épaissi : `lineStyle(Math.max(2.5, HEX_RADIUS*0.5), color, 0.85)`.
   - ✅ **Z-order des couches** (`app.stage.sortableChildren`) :
     `base(0)` < `floorContours(10)` < previews/voile (`highlightContainer` 120) < **murs(130)** < unités(2000).
     Les **murs passent au-dessus du voile/contour d'étage ET des previews tir/move** (choix utilisateur :
     previews < voile < murs), tout en restant sous les figs et la ligne de mesure. `wallsContainer.zIndex = 130`
     est (re)forcé à **chaque réattache** dans [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx) —
     sinon, le conteneur des murs étant réutilisé (`staticWallsRef`), un mur créé avant l'ajout du zIndex
     (ex. HMR) resterait à 0 et repasserait sous les contours. Le conteneur `floorContours` a son cycle de
     vie calqué sur les highlights (préservé au reuse, sinon reconstruit par `drawBoard`).
   - ✅ **Voile au-dessus des previews** : le voile (vue étage ≥1) est dessiné dans `highlightContainer`
     (zIndex 5000 + `sortableChildren`), à chaque draw → passe **par-dessus les zones de preview tir/move**
     (zIndex 0 dans ce conteneur), sous les unités.
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
   - ✅ **6d Move par-figurine niveau-conscient (COMPLET)** — miroir exact du déploiement, bout-en-bout :
     - **Pool** `movement_build_model_destinations_pool(…, level)` : occupation des autres escouades ET des
       sœurs calculée **par niveau** (sol + niveau de vue), niveau **effectif** de chaque destination dérivé
       de l'empreinte sur le plancher, filtre socle intra-escouade au **même niveau effectif**. Murs bloquants
       à tous niveaux. Tout au niveau 0 → comportement 2D historique (non-régression)
       ([movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)).
     - **API** `move_model_destinations` + `move_squad_unplaced_destinations` : acceptent `level` (vue) et un
       `provisional_plan` en `(col,row,level)` ([api_server.py](file:///home/greg/40k/services/api_server.py)).
     - **Front** : le plan de move porte `level` **de bout en bout** — `readSquadModelPositions` lit
       `level_by_model` (init), le **drop** capture `currentLevel` (`handleMoveModelInPlan`), preview
       (`refreshSquadMovePlanValidity`), pool (`handleSelectModelForMove` + batch `move_squad_unplaced_destinations`)
       et commit (`handleCommitSquadMovePlan`) envoient `(mid,col,row,level)`
       ([useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts), [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)).
     - **Publication `level_by_model`** : `_recompute_squad_occupied_hexes` (appelé à chaque mutation de position)
       et le build initial de `units_cache` publient désormais `level_by_model` depuis `models_cache[mid]["level"]`.
       Sans ça le niveau par-figurine ne remontait jamais au front (rendu + init du plan retombaient au niveau
       d'ancre → tout traité niveau 0) ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
     - **Niveau EFFECTIF au move** (§13.06, appliqué comme au déploiement) : preview (`movement_preview_move_plan`)
       ET commit (`commit_move_plan`) résolvent le niveau via `resolve_model_floor_level`. Une fig dont
       l'empreinte **déborde partiellement** du plancher n'est **plus en voile rouge** — elle est simplement
       ramenée au **sol (0)** (preview) et committée au sol (persist). `validate_floor_placement`/`floor_bad`
       du preview supprimé (le niveau effectif encode déjà l'appartenance au plancher).

   ### ✅ BUGS RÉSOLUS (confirmés par l'utilisateur)
   1. **Collision inter-niveaux au MOVE** (une fig à l'étage bloquée par une fig au sol au même hex) — **réglé**.
      Checks niveau-conscients : `movement_build_valid_destinations_pool` (obstacles filtrés par `unit.level`)
      + `validate_move_plan` (`other_occupied_by_level`, [shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)).
   2. **Badge de niveau dynamique au drag** — **réglé** : le ghost de destination reçoit désormais
      `modelLevels`/`modelLevelGhost` dérivés live ([BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)).
   3. **Superposition inter-niveaux au MOVE par-figurine** — **réglé** : le pool par-fig, l'API, le preview,
      le commit et le front sont niveau-conscients de bout en bout (cf. 6d). Deux figs peuvent finir au même
      `(col,row)` à des niveaux différents.
   4. **« Figs niveau 1 aussi au niveau 0 »** — **réglé** : root cause = le niveau n'était ni capturé au drop,
      ni persisté, ni publié dans le cycle du move (`level_by_model` jamais écrit côté backend). Câblage complet
      + publication `level_by_model` à chaque recompute.
   5. **Voile rouge sur débordement partiel d'étage (move)** — **réglé** : une fig posée en partie sur l'étage
      n'est plus rejetée, elle est ramenée au niveau 0 (niveau effectif `resolve_model_floor_level` dans preview
      + commit).

   **Logs de diagnostic** : tous les logs temporaires `[DIAG ...]` (FORMATION, POOL, SQUAD-POOL, PREVIEW,
   DEPLOY-COMMIT dans [deployment_handlers.py](file:///home/greg/40k/engine/phase_handlers/deployment_handlers.py) ;
   MOVE dans [movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) ont été
   **retirés**. Le calcul `resolve_model_floor_level` (niveau effectif) reste utilisé par le commit.

   ### ✅ AJOUTS RÉCENTS — coût de montée, hauteur de modèle, charge niveau-consciente (2026-07-07)

   - **6e Coût de montée §13.06 dans le pool move par-figurine** (`movement_build_model_destinations_pool`,
     [movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) : le pool
     par-fig était **planaire** (le champ 2D atteignait « gratuitement » les cases d'étage — bug). Désormais,
     en vue étage (`view_level ≥ 1`, métrique euclidienne, hors FLY) :
     - les cases dont l'empreinte tient sur le plancher (placement en hauteur) proviennent du champ
       **climb-aware** `reachable_multilevel_field` (montée/descente soustraite du budget) via le helper
       `_model_climb_reachable_floor_cells` → plus de montée gratuite ; unité non-montante → aucune case d'étage.
     - les cases **sol** dont le socle chevauche l'empreinte de l'étage en vue sont **retirées** (le preview
       s'arrête au bord du bâtiment). Test **euclidien disque↔polygone** sur `floor["polygon_vertices"]`
       (aligné pixel-pour-pixel sur le contour rendu et la précision fig↔fig ronde) ; non-rond → empreinte hex.
     - `destinations` porte le **niveau réel par case** `[col,row,level]` (API `move_model_destinations`) ;
       le front stocke `Map "c,r"→level` et **pose la fig au niveau de la destination** (plus `currentLevel`
       aveugle) — `handleMoveModelInPlan` ([useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts)),
       erreur explicite si case hors pool (aucun fallback).
     - **Refetch au changement de niveau** : une fig **active** refetch son pool au nouveau niveau (effet sur
       `currentLevel`, `activeModelId` lu via ref, [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx))
       — sinon le pool restait figé au niveau de sélection.

   - **Hauteur de modèle / clairance sous étage (§13.06 maison)** :
     - `MODEL_HEIGHT` (pouces) acheminé du roster jusqu'au moteur : déjà extrait par `UnitRegistry`, désormais
       recopié par le **builder central `create_unit`** (+ `_build_enhanced_unit` et build army API)
       ([game_state.py](file:///home/greg/40k/engine/game_state.py), [api_server.py](file:///home/greg/40k/services/api_server.py))
       → `units_cache`. (Root cause d'un 500 : `create_unit` re-whitelistait et **droppait** le champ.)
     - Helper `low_clearance_ground_hexes(terrain_areas, model_height)`
       ([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)) : union des hexes d'étages dont
       `height_inches < MODEL_HEIGHT`. Injecté dans les **obstacles AU SOL** uniquement (jamais `wall_hexes`
       partagé — ces hexes SONT le plancher, praticable en surface ; vol non concerné). Une fig trop haute ne
       peut ni traverser ni s'arrêter sous un étage bas.
     - **Appliqué** : move **par-figurine** (champ euclidien + niveau 0 du champ climb) et **charge** (cf. ci-dessous).
       **RESTE** : pool **squad** `movement_build_valid_destinations_pool` (= pathfinding **IA**) et **voile rouge**
       `movement_preview_move_plan` — même injection ground-only/non-fly à faire (piège : plancher = hexes
       clairance → la surface d'étage doit rester walkable, ne pas polluer `wall_hexes` global).

   - **Charge niveau-consciente** (`_compute_plan_context` + `charge_model_plan_state`,
     [charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)) :
     - Clairance hauteur injectée dans `path_blocked` (sol ; vol via `set()` non concerné).
     - `level` propagé (dispatch → `charge_model_plan_state`) ; post-filtre `_charge_pool_clip_under_floor`
       retire du pool les ancres dont le socle chevauche l'empreinte de l'étage en vue (miroir exact du clip
       move). Appliqué **hors cache mémoïsé** → changement de niveau = clip recalculé sans invalider `ctx`.
     - Front : `charge_plan_state` envoie `level` ; refetch de la fig de charge active au changement de niveau
       (fusionné avec le refetch move dans le même effet `currentLevel`).
     - ⚠️ **PAS de destinations de charge EN HAUTEUR** : une charge doit finir **engagée** avec une cible
       déclarée, or l'**engagement est purement 2D** — `entries_in_engagement_zone`
       ([spatial_relations.py](file:///home/greg/40k/engine/spatial_relations.py)) ne compare que les empreintes
       (col/row/occupied_hexes), **sans `level`** ; `occupied_hexes` du units_cache est l'**union tous niveaux**.
       Les unités PEUVENT être en hauteur (champ `level`, `_occupied_hexes_at_level`), mais la verticalité est
       **ignorée** dans l'engagement. Charger vers une cible à l'étage n'a donc pas de sens tant que l'engagement
       n'est pas 3D.

   ### 🎯 ENGAGEMENT 3D — CONCEPTION OPTIMALE (CENTRALISÉE) — chantier 4

   > **Décision (2026-07-07)** : centralisation immédiate dans la primitive partagée `spatial_relations`,
   > pas de gate local à la charge. Rationale : `entries_in_engagement_zone` est la **source unique**
   > d'engagement pour ~80 call-sites (shooting/fight/charge/move/observations RL) — un gate dupliqué
   > par phase serait de la dette permanente (cf. principe move/déploiement miroir). Le 3D doit vivre
   > à l'endroit unique où l'engagement est décidé.

   **Constat de code (vérifié, ne rien assumer)** :
   - Primitive `entries_in_engagement_zone(first, second, engagement_zone, metric)`
     ([spatial_relations.py:115](file:///home/greg/40k/engine/spatial_relations.py#L115)) — deux métriques :
     - `hex` : `min_distance_between_sets` d'empreintes union ([hex_utils.py:101](file:///home/greg/40k/engine/hex_utils.py#L101)).
       **Épinglée** RL/observations (`metric="hex"`), unités **jamais multi-niveaux** dans ce chemin.
     - `euclidean` : `euclidean_edge_distance(socle_a, socle_b) ≤ engagement_minimum_clearance_norm(ez)`
       (= ez×1,5, [hex_utils.py:1378](file:///home/greg/40k/engine/hex_utils.py#L1378)). **Métrique GAMEPLAY**
       (config 7.6) — c'est celle de la charge.
   - `socle_from_cache_entry` ([combat_utils.py:324](file:///home/greg/40k/engine/combat_utils.py#L324)) construit
     un `Socle` portant **`model_centers` par-figurine** (`occupied_hexes_by_model`) → la granularité par-fig
     existe déjà côté euclidean ; il ne manque que la **hauteur par centre**.
   - Wrappers additifs : `unit_entries_within_engagement_zone` (:145), `unit_within_engagement_zone_footprints`
     (:165), `move_anchor_violates_engagement_clearance` (:190) — tous délèguent à la primitive.
   - **Unités** : horizontal = **subhex** (positions col/row board ×`inches_to_subhex`) ; hauteur `height_inches`
     = **pouces**. Le gate vertical se fait **en pouces** (hauteur↔hauteur, pas de conversion croisée).

   **Règle** — `03 Moving.pdf` §03.04 (déjà §2.5) : engagement range = ≤2" horiz **ET** ≤5" vert.
   Coherency §03.03 = 5" vert aussi. Le 5" vertical est **fixe** (indépendant du seuil horizontal, qui varie
   selon le contrat : engagement 2", contact charge `within_1` 1", melee…). → le vertical **doit être un
   paramètre séparé**, jamais dérivé de `engagement_zone`.

   **Implémentation optimale (3 briques, additive → zéro régression)** :

   1. ✅ **FAIT — Fondation data — `floor_height_by_model` (pouces) au build cache.** Helper
      `floor_height_at(terrain_areas, col, row, level)` ([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py))
      (sol=0.0, résolution PAR POSITION, `ValueError` si fig level≥1 hors plancher — pas de fallback) ;
      publié aux DEUX points du cache : build initial `build_units_cache` + `_recompute_squad_occupied_hexes`
      ([shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)). Backend-only, aucun
      consommateur → no-op. Testé (helper + bout-en-bout sol/étage, non-régression suite `units_cache` verte).
      Détail conception ci-dessous. À côté de `level_by_model`
      ([shared_utils.py:750](file:///home/greg/40k/engine/phase_handlers/shared_utils.py#L750) + recompute
      `:2862`), publier la hauteur du **plancher** sous chaque fig : `height_inches` du floor de son `level`
      sous le décor où elle se trouve (sol = 0"). **Résolution par position** (`terrain_areas` + `level_by_model`),
      PAS un mapping global level→hauteur : deux ruines peuvent différer au même `level` (§4.1). La **borne
      haute** de l'intervalle vient de `MODEL_HEIGHT` déjà présent dans `units_cache` (§6e) — pas de champ
      supplémentaire. Aucun consommateur encore → **no-op testable seul**.

   2. ✅ **FAIT — Gate vertical DANS la primitive.** Config `engagement_zone_vertical: 5` (POUCES, non scalé —
      absent de la liste [w40k_core.py:401](file:///home/greg/40k/engine/w40k_core.py#L401)) + getter
      `get_engagement_zone_vertical`. `MODEL_HEIGHT` publié dans l'entry `units_cache` (borne haute).
      `entries_in_engagement_zone(..., vertical_zone_inches=None)` + helpers `_vertical_classes` /
      `_entries_in_engagement_zone_3d` (3D par-paire à intervalles, euclidean only, erreur explicite si
      hex+vertical ou données verticales manquantes) ; param propagé aux 3 wrappers. **Testé** (gate
      proche→engagé/loin→non, dégénérescence sol=2D, erreur hex+vertical ; 73 échecs de suites **pré-existants**,
      `level` manquant sur vieux stubs, hors diff). Détail conception ci-dessous.

   2bis. **Détail conception — paramètre `vertical_zone_inches` (défaut `None`).**
      `entries_in_engagement_zone(first, second, engagement_zone, metric, vertical_zone_inches=None)` :
      - `None` → **chemin actuel exact** (agrégat union / socle multi-centres), **byte-identique**. Les ~80
        call-sites qui ne passent rien restent 2D → **zéro régression**.
      - non-`None` → mode **3D par-paire de figurines** (fidèle à §03.04, qui est par-fig) :
        ∃ (fig_a, fig_b) avec **séparation d'intervalles verticaux** `max(0, max(loA,loB) − min(hiA,hiB)) ≤
        vertical_zone_inches` **ET** distance horizontale ≤ seuil, où `[lo,hi] = [floor_height, floor_height +
        MODEL_HEIGHT]` (§01.04 « partie la plus proche », pas plancher-à-plancher). Le gate vertical **filtre
        les paires en amont** ; le test horizontal reste **inchangé** (réutilise `euclidean_edge_distance` sur
        les centres du `Socle`). Court-circuit : si un côté n'a pas `floor_height_by_model` ou si tout est au
        sol des deux côtés → **une seule classe** → équivalent exact au test agrégé 2D actuel.
      - **Cible = métrique `euclidean` uniquement** (gameplay ; `model_centers` déjà par-fig). `hex` reste 2D
        (RL/obs mono-niveau, jamais concerné) → pas de reconstruction d'empreinte hex par-fig, pas de coût RL.
      - **Perf** : les préfiltres hex-distance existants des call-sites (ex. charge `:788`, `:3563`) sont
        conservés ; le gate vertical est un check scalaire O(1) par paire, Na×Nb petits (figs/unité).
      - Propagation additive du paramètre dans les 3 wrappers (défaut `None` partout).

   3. **Migration des call-sites (incrémentale, primitive déjà centralisée).** Seuls les call-sites qui
      doivent devenir 3D passent `vertical_zone_inches=5"` : **engagement/charge d'abord**. Les autres
      (shooting cover, coherency, fight adjacency…) restent `None` → inchangés, migrés quand une fig y sera
      réellement multi-niveaux. La source unique existe déjà : pas de re-centralisation ultérieure.
      - ✅ **Infra synth vertical FAITE** : `_charge_synthetic_charger_cache_entry(..., level=None)`
        ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)) — `level=None`
        → entrée 2D **byte-identique** ; un entier pose les données verticales (classe unique à l'ancre,
        `floor_height_by_model`/`occupied_hexes_by_model` au singleton `_CHARGE_SYNTH_ANCHOR_MID`). **Testé
        en isolation** : cible étage 3" → engageable 3D & 2D ; cible étage 8" → **refusée en 3D** (sep 5,5">5)
        alors que le 2D l'acceptait à tort (union projetée au sol). **Aucun call-site câblé** → zéro
        changement de comportement charge.
      - ✅ **AUDIT DES CALL-SITES (2026-07-07)** — 19 appels effectifs d'engagement dans `charge_handlers`
        (le reste = docstrings/imports). **Enseignement clé** : aucun n'est à laisser 2D définitivement (tous
        sont des tests d'engagement réels) ; les préfiltres hex-distance sont **séparés** et restent valides
        en 3D (le gate vertical ne fait que **restreindre**, jamais élargir → pas de faux négatif).
        **16 « 3D direct »** (synth/vraie entry via primitive) : L413, L477 (anchors), L1742/1745/1747
        (model pool), L2219/2226 (plan ctx UI), L4485 (preview), L4387, L4635 (non-cibles AFTER MOVING),
        L873 (eligibility), L2569 (valid targets), L3527/3704 (destinations sol), L2552, L3095 (départ,
        vraies entries). **2 « 3D COMPLEXE » — ✅ FAITS** : `_eng` (`_compute_plan_context`) — branche
        euclidienne via primitive 3D (`synth_base` reçoit les données verticales à l'ancre à la mutation) +
        branche empreinte-dilatée gardée par un **gate vertical par-ennemi** (`entry_vertically_reachable`
        [spatial_relations.py](file:///home/greg/40k/engine/spatial_relations.py), précalculé `tgt_vreach`/
        `ntgt_vreach`) ; `_fp_engages` (`charge_autoplace_plan`) — en config **euclidean** (gameplay)
        `_entry_engage_struct` renvoie toujours `("euclid", entry)` → primitive 3D directe ; la branche
        empreinte `("fp", …)` n'existe qu'en métrique **hex** (RL/obs, mono-niveau) → **reste 2D** (assumé).
        Testé `entry_vertically_reachable` (ennemi 3"→True, 8"→False) ; dégénérescence sol structurelle.
        **1 différé** L3431 (FLY, §707).
      - ✅ **VALIDATION D'INTÉGRATION 3a (2026-07-07)** — script **pérennisé**
        [scripts/charge3d_integration_test.py](file:///home/greg/40k/scripts/charge3d_integration_test.py)
        (lancer : `source .venv/bin/activate && python3 scripts/charge3d_integration_test.py`) sur le VRAI
        `scenario_floors_test` (env W40KEngine réel, floors rasterisés L1=1200/L2=400 hexes, roster réel) :
        `MODEL_HEIGHT` propagé (cible 4.0 / chargeur 2.5), `floor_height_by_model` = {sol 0.0, L1 3.0, L2 6.0}
        via les vrais floors, et le gate d'engagement 3D **bascule exactement au gap vertical réel** (cible L2,
        gap 3.5" : vz=3→refus, vz=4→engagé). Confirme la chaîne roster→units_cache→primitive 3D avec données
        réelles. **C'est le SEUL moyen de non-régression du gameplay 3D d'étages** (le RL est HS → pas de test
        pytest gameplay ; à relancer après tout changement backend de 3b).
      - 🎯 **DÉCOUPE 3a / 3b** :
        - ✅ **3a — cible/ennemi surélevé engagé DEPUIS LE SOL — FAIT & VALIDÉ** : les 2 constructeurs de synth
          portent le niveau (`_charge_synthetic_charger_cache_entry(..., level)` + `_synth_model_entry(..., level)`
          [shared_utils.py](file:///home/greg/40k/engine/phase_handlers/shared_utils.py)) ; helper
          `_charge_vertical_zone` ; **18 call-sites d'engagement câblés** (16 directs + les 2 complexes
          `_eng`/`_fp_engages` avec gate vertical par-ennemi `entry_vertically_reachable`)
          ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)). `synth level=0`
          partout (chargeur au sol). **Seul L3431 (FLY) reste 2D** (différé §707). Validé bout-en-bout par le
          script d'intégration ci-dessus + non-régression sol/no-floor structurelle.
        - ⏳ **3b — le chargeur MONTE** (ancres `level ≥ 1`) : **RESTE À FAIRE**. Nécessite
          `reachable_multilevel_field` (champ climb, déjà écrit, utilisé par le move par-fig §6e) branché dans la
          production des destinations de charge, `synth level = niveau de la destination` (plus 0), le
          **passage de `cand_floor` réel** (plus `0.0` hardcodé) aux gates verticaux de `_eng`/`_fp_engages`,
          **+ front** (rendu destinations par niveau, miroir move §6d/6e). Validation = app + `scenario_floors_test`.

   **✅ Décisions figées (2026-07-07)** :
   - **Seuils verticaux = 5" pour les DEUX contrats** : engagement range (§03.04, conforme) ET contact
     `within_1` de la charge. Le `within_1` est un resserrement **horizontal** (1" au lieu de 2",
     [charge_handlers.py:449](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py#L449)) ; les
     règles ne lui donnent **aucun** vertical propre → on aligne sur les 5" de l'engagement range, **pas de
     règle maison**. → **une seule valeur verticale = 5"**, configurée dans `config/game_config.json`
     (nouvelle clé, pendant vertical de `engagement_zone: 2`).
   - **Mesure verticale = INTERVALLE, pas plancher-à-plancher** : chaque fig est modélisée comme le segment
     vertical `[plancher, plancher + MODEL_HEIGHT]` (`MODEL_HEIGHT` déjà dans `units_cache`, §6e). L'écart
     vertical = séparation entre les deux intervalles `max(0, max(loA,loB) − min(hiA,hiB))` → conforme au
     « partie la plus proche » §01.04, **sans donnée nouvelle**. Rejette l'approximation plancher-à-plancher
     (qui surestimait l'écart : fig 2,5" au sol vs base 3" = **0,5"** réel, pas 3"). Approximation résiduelle
     **inévitable** : la fig est traitée comme colonne pleine (silhouette réelle non chiffrée dans les PDF,
     §2.11, même statut que la True LoS).
   - Le mode 3D est **lié à la métrique `euclidean`** (config active `game_config.json:55`). Une bascule
     config `engagement:"hex"` rendrait le gate vertical inopérant (hex reste 2D) → re-travail hex requis.

   **Débouché charge** (une fois 1→3 en place) : brancher `vertical_zone_inches` dans les tests d'engagement
   de la charge, **retirer le garde-fou** « PAS de destinations en hauteur » ([charge_handlers.py:690](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py))
   et brancher `reachable_multilevel_field` ([geodesic_move.py](file:///home/greg/40k/engine/phase_handlers/geodesic_move.py))
   pour produire les ancres d'étage (le champ climb-aware existe déjà, cf. 3a/6e). L'EZ inter-niveaux
   (`enemy_adjacent_hexes`, 2D) suit la même bascule.

   ### ⏳ RESTE À FAIRE (mis à jour 2026-07-07)

   1. ✅ **Engagement 3D (chantier 4) — FAIT & VALIDÉ** : étapes 1 (fondation `floor_height_by_model` +
      `MODEL_HEIGHT` dans `units_cache`), 2 (primitive `entries_in_engagement_zone(..., vertical_zone_inches)`
      + config `engagement_zone_vertical: 5` + getter + wrappers), 3a (18 call-sites charge câblés, FLY différé).
      Validé sur le vrai scénario ([scripts/charge3d_integration_test.py](file:///home/greg/40k/scripts/charge3d_integration_test.py)).
      Non-régression pytest **entièrement rétablie** (`python3 -m pytest tests/` → **1152 passed, 2 skipped, 0 failed** ;
      dette de stubs `level`/`MODEL_HEIGHT`/`engagement_zone_vertical`/`_unit_move_version` + 7 tests obsolètes
      de la refonte advance→move réparés au passage).
   2. ⏳ **3b — Champ climb-aware dans la charge** (destinations d'étage, chargeur qui MONTE) — **PROCHAINE ÉTAPE**.
      Brancher `reachable_multilevel_field` ([geodesic_move.py](file:///home/greg/40k/engine/phase_handlers/geodesic_move.py))
      dans la production des destinations de charge + `synth level = niveau destination` + `cand_floor` réel dans
      `_eng`/`_fp_engages` + **front** (rendu par niveau, miroir move §6d/6e). Validation = app + `scenario_floors_test`.
   3. **Clairance hauteur — reste du mouvement** (voile rouge + pool squad/IA) — *plan détaillé, à faire d'un
      seul bloc* : le move **par-figurine** et la **charge** enforcent déjà la clairance ; restent les deux
      dernières surfaces du mouvement. À traiter ensemble (même helper, même piège, périmètre « tout le
      mouvement » déjà validé) pour ne pas laisser un état incohérent (voile rouge corrigé mais IA qui planifie
      encore des trajets impossibles).
      - **3.1 Voile rouge** `movement_preview_move_plan`
        ([movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) : calculer une
        fois `_low_clear = low_clearance_ground_hexes(terrain_areas, MODEL_HEIGHT_de_l_unité)` puis, dans la boucle
        par-modèle, ajouter la clairance à la détection d'obstacle **uniquement pour une figurine au sol**
        (`lv == 0`) — étendre le test `fp_wall` (actuellement `fp & wall_hexes_set`) avec `fp & _low_clear`, sans
        toucher `wall_hexes_set`. Une fig **à l'étage** (`lv >= 1`) n'est jamais bloquée par la clairance (elle est
        sur le plancher, pas dessous).
      - **3.2 Pool squad/IA** `movement_build_valid_destinations_pool`
        ([movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) : même injection
        `set(wall_hexes) | _low_clear` dans les obstacles **AU SOL** du pathfinding (miroir exact de ce qui est fait
        pour le move par-fig aux obstacles ground, `_mm_obstacles` / `_ground_obs`), branche non-fly. La branche FLY
        (`_fly_walls`) reste inchangée (vol non concerné).
      - **Piège (identique move par-fig)** : ne JAMAIS unir `_low_clear` à `wall_hexes` global ni aux obstacles
        d'étage — ces hexes SONT le plancher, praticable **en surface**. L'injection est strictement ground-only.
      - **Validation** : suite complète + `--step` + replay ; vérifier qu'une fig haute (`MODEL_HEIGHT > height_inches`)
        voit du rouge / est exclue du pool sous un étage bas, et qu'une fig basse (tangence `==`) passe.
   4. **FLY + étages** (move et charge) : toujours traité en planaire (différé).
   5. **Métrique hex + étages** : le climb-aware est euclidien seulement (les floors sont euclidiens).
   6. Pool **squad** move (suivi de bloc) : retrait du miroir transitoire `valid_move_destinations_pool` →
      migration sur `_by_level`.

Chantiers 1→5 sont backend (moteur + règles), 6 est frontend. 1 doit précéder tous les autres.
