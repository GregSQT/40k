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

  > **Décision de conception (voulue, pas un bug de conformité) :** le texte §13.09 exige une area
  > contenant un terrain **dense** ; le moteur teste à la place l'appartenance à une area
  > **obscuring** (`compute_models_in_obscuring_terrain` → `model_within_terrain(obscuring_only=True)`).
  > Le flag `obscuring` est **posé manuellement** par le concepteur de terrain sur chaque area
  > (`config/board/{board}/terrain/terrain-*.json`, champ `"obscuring": true`) — il n'existe volontairement
  > **aucun marqueur dense/light au niveau de l'area** (seuls les `walls` sont typés `light`/`dense`,
  > pour le blocage de LoS / Solid §13.11). L'`obscuring` manuel **fait donc foi** pour Hidden : une area
  > marquée obscuring accorde Hidden, par choix. Conséquence assumée : le moteur ne distingue pas une
  > area obscuring dense d'une light-only pour Hidden (c'est au concepteur de ne flaguer `obscuring` que
  > les areas qui doivent cacher).

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

> **Plan d'implémentation détaillé** (constat de code 2026-07-10, primitive `_los_line_segment_clear`,
> plancher-occulteur, Solid ≤3"/>3", Plunging, parité WASM, non-régression, décisions à trancher) : voir la
> section « 🎯 TIR 3D — Ligne de vue niveau-consciente (chantier 5) » dans le chantier 6 ci-dessous.

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
5. **LoS 3D (tir)** : plancher-occulteur horizontal (cible sous un étage), Solid ≤3"/>3", Plunging +1 BS
   (branche TOWERING), extension clé `hex_los_cache` au niveau, parité WASM (Rust + rebuild).
   → **Plan détaillé** : section « 🎯 TIR 3D — Ligne de vue niveau-consciente » ci-dessous (chantier 6).
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
     - **Déploiement — clairance alignée EXACTEMENT sur le move [2026-07-09]** (`deployment_handlers.py`) :
       appliqué aux **3 sites** — pool per-fig `deployment_build_model_destinations_pool`, voile rouge
       `deployment_preview_plan`, drop `generate_compact_formation`.
       - **Géométrie = celle du move, pas l'empreinte hex.** Le move n'ajoute jamais `_low_clear` au filtre
         d'empreinte : il le met dans les obstacles du champ géodésique avec clearance = **rayon du socle**.
         Un socle **rond** « heurte » un hex `_low_clear` **ssi son DISQUE le chevauche** (pendant
         stationnaire de la clairance capsule `_segment_hits_hex`). Le blocage par **empreinte hex**
         sur-couvrait le disque (~½ hex) et posait la fig **plus loin** que le move (bug « dread loin en
         deploy / collé en move ») → retiré pour les bases rondes. Base **non-ronde** : empreinte hex
         conservée (miroir du move non-rond, empreinte discrète orientée).
       - Helpers `build_hex_center_index` / `disc_overlaps_indexed_hexes`
         ([hex_utils.py](file:///home/greg/40k/engine/hex_utils.py)) : index spatial bucketé (bucket =
         `rayon + circumradius`) construit **une fois** par appel → clairance disque O(1) par case (sans
         l'index : 1710 hexes × ~7000 cases ⇒ ~2 s/pool = click gelé).
       - **Gate mot-clé §13.06** dans le pool : `unit_can_occupy_upper_floor` — une unité non-montante
         (VEHICLE, etc.) n'obtient jamais de candidate taguée étage (`eff` forcé à 0), donc la clairance sol
         s'applique (sinon `eff=level` contournait `_low_clear`). Miroir de la correction multi-niveaux du move.

   - **Charge niveau-consciente** (`_compute_plan_context` + `charge_model_plan_state`,
     [charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)) :
     - Clairance hauteur injectée dans `path_blocked` (sol ; vol via `set()` non concerné).
     - `level` propagé (dispatch → `charge_model_plan_state`) ; post-filtre `_charge_pool_clip_under_floor`
       retire du pool les ancres dont le socle chevauche l'empreinte de l'étage en vue (miroir exact du clip
       move). Appliqué **hors cache mémoïsé** → changement de niveau = clip recalculé sans invalider `ctx`.
     - Front : `charge_plan_state` envoie `level` ; refetch de la fig de charge active au changement de niveau
       (fusionné avec le refetch move dans le même effet `currentLevel`).
     - ⚠️ ~~**PAS de destinations de charge EN HAUTEUR**~~ **[RÉSOLU — chantier 4 + 3b, 2026-07-08]** : constat
       historique (pré-engagement 3D) conservé pour mémoire. À l'époque l'engagement était **purement 2D**
       (`entries_in_engagement_zone` sans `level`), donc charger vers une cible à l'étage n'avait pas de sens.
       **Désormais** : l'engagement est 3D (`vertical_zone_inches`, chantier 4) ET le chargeur peut MONTER (3b) →
       destinations d'étage produites, engagées en 3D. Voir la section « ENGAGEMENT 3D — chantier 4 » ci-dessous.

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
        - ✅ **3b — le chargeur MONTE (ancres `level ≥ 1`) — FAIT & VALIDÉ (2026-07-08)** :
          - **Helper climb charge** `_charge_model_climb_reachable_floor_cells`
            ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)) : miroir
            EXACT du move `_model_climb_reachable_floor_cells` (source unique `reachable_multilevel_field`),
            **budget = jet de charge sous-hex**, coût de montée §13.06 soustrait, obstacles sol = murs+ennemis+
            clairance (amies traversables). Retour `{(col,row): dist_subhex}`. Testé : 667 cases L1 avec gros
            budget, **0 case sous le coût de montée** (budget < 3" → aucune ancre d'étage → §13.06 confirmé).
          - **`_compute_plan_context` niveau-conscient** : nouveau param `view_level`. En vue étage (≥1,
            euclidean, hors FLY, `can_classify`), reach d'étage **PAR-FIGURINE** (start-dépendant, comme le
            move par-fig) via le helper climb ; classification `floor_region_by_base` par la **primitive 3D
            directe** (`_synth_model_entry(..., level=view_level)` → `cand_floor` = hauteur réelle du plancher,
            plus le `0.0` hardcodé). Les cases d'étage **participent à la détermination de phase** (union
            sol+étage dans `_qual`). Structures `floor_*` ajoutées au ctx. Sig mémo `charge_model_plan_state`
            += `view_level` (recalcul au clic d'étage, rare). **Additif** : tout au sol / vue 0 / non-montant /
            hex / FLY → structures vides → sortie **byte-identique 2D** (non-régression pytest 1152 verte).
          - **`_charge_qualifying`** émet désormais `[col,row,level]` (sol `level 0` inchangé + étage `view_level`).
            **`_charge_pool_clip_under_floor`** ne clippe QUE le sol (`level 0`) ; les ancres d'étage passent.
            `pool_distances`/`footprint_mask_loops` : sol = champ géodésique, étage = `floor_dist`/`floor_region`.
          - **Preview/commit niveau** : `charge_preview_move_plan` (`norm` 4-uplet, synth au niveau réel),
            `_charge_model_pos_is_closer` (nouveau `dest_level` : **reachability climb** au lieu du BFS 2D quand
            l'ancre est à l'étage — sinon le coût vertical serait ignoré), `charge_commit_move_plan_handler`
            (accepte `[mid,col,row(,level)]`, propagé à `commit_move` qui gère déjà le 4-uplet). `provisional_plan`
            porte le niveau (satisfaction/engagement 3D des figs POSÉES à l'étage). Les 2 parseurs de dispatch
            (`charge_plan_state`, `charge_fly_mode_set`) construisent `prov` avec niveau.
          - **Front** (miroir move §6d/6e) : `chargeModelLevelByKeyRef` (Map `"c,r"→level`), plan
            `models:{col,row,level?}`, `applyChargePlanState` lit le niveau par ancre, `handleMoveModelInChargePlan`
            pose au niveau réel (erreur si case hors pool, aucun fallback), `refreshChargePlanState`/
            `handleCommitChargePlan` envoient le niveau. Refetch de la fig active au changement de niveau **déjà
            en place** (effet `currentLevel` → `onSelectChargeModel`) → recalcule les destinations d'étage
            ([useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts), tsc vert).
          - **Piège majeur généralisé** : en 3a `_eng` passait `cand_floor=0.0` hardcodé (`tgt_vreach`/`ntgt_vreach`
            + `synth_base.floor_height_by_model`) — le chargeur au sol. En 3b la branche SOL garde ce chemin
            (byte-identique) ; l'ÉTAGE ne passe **pas** par `_eng`/masques (candidat multi-niveau) mais par la
            **primitive 3D directe** avec synth au niveau réel → `cand_floor` correct sans toucher au fast-path sol.
          - **Piège métrique** : le chemin 3D d'étage est **euclidean-only** (métrique gameplay `charge`) ; l'env
            de training (`charge_gym`) est `hex` (RL 2D) → le sous-test pool bascule `gym_training_mode=False`
            pour exercer le vrai chemin PvP. Le champ climb lui-même est euclidien par nature.
          - **`charge_build_model_destinations_pool` (L1619) est du CODE MORT** (zéro appelant prod/test) — le
            pool interactif du front passe par `charge_model_plan_state` → `_compute_plan_context`.
          - **Affichage mono-niveau (clarté)** : `charge_model_plan_state` ne renvoie au front QUE les ancres
            du **niveau de vue** courant (`pool = [a for a in pool if a[2] == level]`). Une charge finissant
            AU SOL en engageant une cible surélevée (3a, engagement 3D ≤5" vertical §03.04) reste **légale**
            et s'affiche au niveau 0 ; ses ancres sol ne polluent plus la vue étage. La phase/éligibilité
            restent calculées sur TOUS les niveaux (ctx). Ébauche de 6c (vue mono-niveau complète différée).
          - **Bugs 3b résolus (2026-07-08)** :
            - **Collision cross-niveau** (une fig d'étage bloquait une destination de charge au SOL au même
              (col,row)) → `_charge_obstacle_socles(..., level)` filtre les obstacles par niveau ; siblings
              posés groupés par niveau (`placed_sibling_socles_by_level`) ; boucles région sol/étage +
              `_charge_model_pos_is_closer` (`dest_level`) + `charge_preview_move_plan` (niveau dans `prov`)
              utilisent le niveau du candidat. Deux figs à niveaux distincts ne se chevauchent plus.
            - **Fig chargée au sol affichée à l'étage** → `perModelPlanView.models` (BoardPvp) **strippait le
              niveau** → le rendu (`modelLevels`) retombait sur le niveau de VUE. Corrigé : la vue du plan
              préserve le niveau par-fig (posée = niveau du plan, non posée = `level_by_model` committé).
          - **Non-bug clarifié** : « une charge niveau 0 atteint une cible niveau 1 » est **conforme** (§03.04
            engagement = 2" horiz ET 5" vert ; cible à 3" d'étage = <5" au-dessus du sol → engageable au sol).
          - **Limites assumées** : « closer » d'une ancre d'étage mesuré horizontalement (`dist_tgt`, cohérent
            avec le sol) ; traversée BFS sol ne distingue pas un ennemi surélevé (bloque toujours en 2D — nuance
            « passer sous une fig d'étage » non modélisée). **FLY en hauteur toujours différé** (§707, L3431 reste 2D).
          - **Validé bout-en-bout dans l'app (2026-07-08)** : déclaration de charge sur cible à l'étage, sélection
            de la fig chargeuse, pool d'étage affiché en vue mono-niveau, pose et commit de la fig à l'étage
            (engagée, voile vert). Collision cross-niveau et niveau de rendu corrigés (cf. « Bugs 3b résolus »).
          - Non-régression : [scripts/charge3d_integration_test.py](file:///home/greg/40k/scripts/charge3d_integration_test.py)
            étendu (chargeur montant → ancres d'étage `level≥1` dans le pool, gate climb §13.06) + pytest
            **1152 passed / 0 failed** + tsc vert.

   ### 🎯 MÊLÉE 3D — pile-in & consolidation niveau-conscients (chantier 4, ⏳ RESTE À FAIRE)

   > **Constat de code vérifié (2026-07-08, ne rien assumer)** : `engine/phase_handlers/fight_handlers.py`
   > contient **0 occurrence de `level`** → pile-in ET consolidation sont **100 % 2D**. Signatures
   > `provisional_plan: Dict[str, Tuple[int, int]]` (sans niveau) ; pools BFS planaires ; engagement testé
   > **sans** `vertical_zone_inches` ; collision `footprints_overlap` sans niveau ; front `pileInMovePlan` /
   > `consolidationMovePlan` en `models: {col,row}` sans `level`.

   **Règles (lues — `12 Fights pahse.pdf`)** :
   - **Pile-in §12.03** : move **3"** « as described in Moving (03) » → règles verticales §13.06 s'appliquent
     (montée soustraite des 3", fin sur étage gated `INFANTRY/BEASTS/SWARM/FLY/MONSTER` + anti-débord).
     WHILE : figs en **base-contact** ennemi ne bougent pas ; chaque fig déplacée finit **plus proche** de la
     cible la plus proche, **engagée** si possible. AFTER : unité engagée ; chaque fig **déjà engagée** au
     départ le reste (engagement = 3D, 2" horiz + 5" vert §03.04).
   - **Consolidation §12.08** : move **3"** idem, 3 modes — **Ongoing** (engagé : plus proche + base-contact
     lock), **Engaging** (≤3" ennemi : plus proche/engagé), **Objective** (≤3" objectif : **within range** de
     l'objectif si possible, sinon plus proche). §2.9 : « within range » d'un objectif-**terrain area** =
     appartenance à la zone (empreinte ∩ zone, **indépendant du niveau** → une fig à l'étage de la ruine-objectif
     contrôle) ; objectif-**pion** = cylindre ≤3" horiz **ET** ≤5" vert.

   **Enseignement clé** : pile-in/consolidation sont le **jumeau structurel de la charge** — mêmes primitives
   importées (`_charge_prepare_footprint_offsets`, `_candidate_footprint_charge`,
   `_charge_synthetic_charger_cache_entry`, `_charge_model_socle`, `unit_entries_within_engagement_zone`,
   `footprints_overlap`). **Toute l'infra 3D est DÉJÀ écrite et réutilisable telle quelle** (chantier 4 + 3b) :
   primitive engagement 3D (`vertical_zone_inches`), helper `_charge_vertical_zone`, champ climb
   `_charge_model_climb_reachable_floor_cells` (**budget paramétrable** → passer `3×inches_to_subhex`),
   synth au niveau réel (`level=`), collision niveau-consciente (`_charge_obstacle_socles(..., level)`), clip
   sol-only, affichage mono-niveau, `commit_move` 4-uplet. → **tâche PLUS PETITE que 3b** (aucune infra à créer,
   uniquement du câblage miroir).

   **Implémentation optimale (miroir 3a/3b, additive → zéro régression 2D)** :

   1. **Pool par-figurine — étage** (`_fight_pile_in_build_model_pool` L3525 + `_fight_consolidation_build_model_pool`
      L4546, [fight_handlers.py](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py)) : en vue étage
      (`view_level ≥ 1`, euclidean, hors FLY, unité montante), ajouter les cases d'étage via
      `_charge_model_climb_reachable_floor_cells(..., budget_subhex=3×ish, view_level, ground_obs, terrain_areas)`
      (coût de montée §13.06 soustrait des 3") ; classer chaque case par la **primitive 3D directe** (synth
      `_charge_synthetic_charger_cache_entry(..., level=view_level)` + `unit_entries_within_engagement_zone(...,
      vertical_zone_inches=_charge_vertical_zone(game_state))`). **Consolidation Objective (tier "zone")** :
      « within range » = **empreinte ∩ zone d'hexes** de l'objectif (`objective["hexes"]`, `_is_unit_on_objective`
      L144 / viser la zone terrain L1342) — test **déjà level-agnostic** (une fig à l'étage de la ruine-objectif
      contrôle, §2.9/§14.02) → **AUCUN gate vertical à ajouter**, seul le **mouvement** vers l'étage a besoin du
      champ climb. (Les objectifs sont des **zones d'hexes** dans le moteur, pas des pions-cylindres : le cylindre
      5" vertical §2.9 ne vaudrait que si un modèle marqueur/cylindre était introduit — hors périmètre.)
      Pool → `[col,row,level]`.
   2. **Collision niveau-consciente** : filtrer `blocker_socles` et `sib_socles` par niveau (une fig d'étage ne
      bloque pas une destination au sol — même correctif que le bug #1 charge). Réutiliser
      `_charge_obstacle_socles(..., level)` ou filtrer sur `entry["level"]` / le niveau du plan des sœurs.
   3. **Base-contact lock (§12.03 / Ongoing §12.08)** : « models in base-contact cannot move ». **Vérifié** :
      `_fight_model_in_base_contact` ([L3934](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L3934))
      teste le contact en **2D pur** (`euclidean_edge_clearance_round_round` sur col/row, sans niveau) → une fig
      au sol et une fig d'étage aux mêmes (col,row) seraient à tort « en contact ». Le contact est physique : à
      évaluer en **3D** (même intervalle `[plancher, plancher+MODEL_HEIGHT]` que l'engagement) — même niveau =
      contact possible, niveaux différents = jamais. **Seul vrai travail de conception** (le reste est du câblage miroir).
   4. **Plan state** (`_fight_pile_in_model_plan_state` L3822 + `_fight_consolidation_model_plan_state` L4868) :
      param `view_level` (miroir `charge_model_plan_state`), pool `[col,row,level]`, **affichage mono-niveau**
      (`[a for a in pool if a[2]==level]`), `pool_distances`/mask loops dérivés (sol = BFS, étage = climb).
      Mémo (s'il existe) += `view_level`.
   5. **Preview + commit** (`_fight_pile_in_preview_plan` L3707 + équivalents consolidation + handlers de commit) :
      `norm` 4-uplet, synth/légalité au niveau réel (reachability **climb** pour une ancre d'étage, pas BFS 2D),
      `provisional_plan` porte le niveau (collision + AFTER-engagement 3D des figs posées à l'étage),
      `commit_move(plan, "pile_in"|"consolidation")` gère déjà le 4-uplet.
   6. **Front** (miroir charge, machinerie `perModelChargeLike` DÉJÀ partagée dans
      [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)) : `pileInMovePlan` /
      `consolidationMovePlan` en `models:{col,row,level?}`, Map niveau par ancre (miroir
      `chargeModelLevelByKeyRef`), pose au niveau réel, dispatch/refresh/commit envoient le niveau. `perModelPlanView`
      **préserve déjà** le niveau (lit `activeChargeLikePlan.models[mid].level`) → deviendra correct dès que les
      plans pile-in/conso portent `level`. **À ajouter** : étendre l'effet de refetch au changement de niveau
      (BoardPvp, aujourd'hui seulement `move`/`charge`) aux modes pile-in/consolidation actifs.
   7. **FLY en hauteur : différé** (§707, cohérent avec la charge L3431).
   8. **DEUX MOTEURS de pile-in (vérifié 2026-07-08) — cadrer la migration en conséquence.** Le pile-in a **deux
      moteurs de destinations à granularités distinctes** (patron identique au move : pool squad rigide RL/IA vs
      pool par-figurine PvP). Ils ne tournent **jamais en même temps** — le choix dépend du mode (auto vs PvP
      interactif) et du moment (normal vs overrun) :
      - **Moteur B — par-figurine (interactif PvP)** : `_fight_pile_in_build_model_pool`
        ([L3525](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L3525)) → `_fight_pile_in_model_plan_state`
        (L3758) + commit. **C'est le seul que couvrent les points 1-7 ci-dessus.**
      - **Moteur A — unité/rigide (auto/IA/gym)** : `pile_in_move_destinations_12_03`
        ([L2727](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L2727)) → `_ai_select_pile_in_destination`
        → `_fight_apply_pile_in_move` (L883). Utilisé par : le pile-in **normal auto** (`_fight_v11_auto_pile_in`),
        la **présentation squad-level** (`_fight_v11_pile_in_present` L4444), et **surtout le pile-in d'OVERRUN**
        (`_fight_v11_auto_overrun_pile_in` L3450) — lequel est auto-résolu **même en PvP** (dispatch interactif
        [L5915](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L5915), pas seulement auto/gym L3504,
        car il n'y a pas d'UI par-fig pour la pile-in additionnelle §12.06).
      - **Conséquence 3D** : migrer B → couvre le pile-in **PvP interactif normal**. L'**overrun** ET tout le pile-in
        **auto/IA** roulent sur A (voie **RL/hex 2D**) → **différer** comme le pool squad du move, **ou** migrer A
        explicitement (`pile_in_move_destinations_12_03` + apply). Tant que A n'est pas 3D, un **overrun ne peut pas
        finir en hauteur, même en PvP**. **Décision à prendre** (A différé vs migré) — pas un sous-cas gratuit de B.
      - **Consolidation = structure DIFFÉRENTE du pile-in (vérifié)** : (a) son auto **skippe entièrement**
        (`_fight_v11_auto_consolidate` [L3465](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L3465),
        consolidation optionnelle §12) → **aucun moteur A/RL**. (b) Son autoplace Focus `consolidate_autoplace_plan`
        ([L4368](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py#L4368)) **ne calcule rien** : c'est un
        **routeur** vers des autoplaces existants dont l'AFTER coïncide avec le mode (docstring L4373) — `ongoing` →
        `pile_in_autoplace_plan` (L3970, AFTER « chaque fig garde ses engagements »), `engaging` →
        **`charge_autoplace_plan`** (budget 3", couverture dure « toutes les cibles »), `objective` → **non supporté**
        (L4416). → À migrer pour la conso 3D : **le pool par-fig** `_fight_consolidation_build_model_pool` (points 1-7),
        et le 3D de ses délégués (`pile_in_autoplace_plan`, `charge_autoplace_plan`) est **mutualisé** avec la migration
        pile-in/charge (pas de code autoplace propre à dupliquer).
      - **`pile_in_autoplace_plan` (L3970)** est un **maximiseur autonome** (ILP, réutilise les primitives charge
        `_charge_model_socle`/`_charge_synthetic_charger_cache_entry`), **distinct** des moteurs A et B → 3ᵉ chemin
        pile-in à migrer si l'on veut un autoplace pile-in qui monte.
      - **POURQUOI cette asymétrie pile-in vs conso (rationale, dicté par les règles)** : **pile-in et charge sont
        les deux contrats de mouvement-avec-engagement PRIMITIFS ; la consolidation est un COMPOSITE** qui les
        réutilise → elle a structurellement moins de machinerie propre. Trois causes concrètes :
        (1) **consolidation optionnelle** (§12 encart « you don't have to pile in or consolidate ») + politique auto
        qui **skippe** la conso mais fait **toujours** le pile-in → moteur A pour pile-in, pas pour conso ;
        (2) l'**overrun (§12.06) est une pile-in additionnelle**, pas une conso → le moteur A du pile-in sert double
        (normal + overrun), la conso n'a aucun consommateur auto ;
        (3) les **3 modes de conso SONT des contrats existants** — Ongoing ≡ AFTER pile-in, Engaging ≡ AFTER charge,
        Objective ≡ appartenance à une zone (pas d'engagement) → l'autoplace conso **délègue** au lieu de dupliquer ;
        le pile-in étant le contrat de **base**, son autoplace est autonome. **Symétrique** : les deux ont un pool
        par-figurine interactif PvP (`_fight_*_build_model_pool`), car les deux ont besoin d'une UI de pose par-fig.

   **Limites assumées (miroir charge 3b)** : « closest tier » (`_fight_pile_in_closest_tier_ids` L3678) et
   « closer » mesurés en distance **horizontale** d'empreinte (`min_distance_between_sets`, 2D) — une cible
   directement au-dessus (2D≈0, mais 5"+ vertical) serait vue « très proche » ; cohérent avec le « closer »
   horizontal déjà admis pour la charge. Le **gate d'engagement**, lui, est bien 3D. À ré-évaluer seulement si
   une mesure de distance 3D globale est adoptée (roadmap item 4).

   **Validation** : script d'intégration dédié (miroir `charge3d_integration_test.py` : fig montant en pile-in/
   conso → ancres d'étage + gate climb 3") + `python3 -m pytest tests/` (1152/0) + app sur `scenario_floors_test`.
   **Non-régression** : tout au sol / vue 0 / non-montant / hex / FLY → chemins vides → **byte-identique 2D**.

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

   ### 🎯 TIR 3D — Ligne de vue niveau-consciente (chantier 5, ⏳ RESTE À FAIRE)

   > **Constat de code vérifié (2026-07-10, ne rien assumer)** : toute la chaîne LoS est **strictement
   > 2D**. `compute_unit_los` ([shooting_handlers.py:4036](file:///home/greg/40k/engine/phase_handlers/shooting_handlers.py#L4036))
   > → `_compute_unit_los_uncached` (:4254) → `_compute_visibility_with_obscuring` (:3951) →
   > `_los_hex_visible` (:3918) → **primitive de tracé unique** `_los_line_segment_clear` (:3895) : trace
   > `hex_line` (cube-lerp) et bloque **uniquement** sur `wall_set` (murs, tous niveaux) et les cases
   > obscuring hors areas exclues (§13.10). **Aucune** de ces fonctions ne lit `level`, `floor_height`,
   > `MODEL_HEIGHT` ni les `floors` du terrain (grep `level|floor|height|elevation` sur la géométrie LoS =
   > 0 hit géométrique). Le champ `level` existe (units_cache/models_cache) mais **n'entre jamais** dans le
   > calcul de visibilité. Miroir Rust `has_los_fast` ([lib.rs:84](file:///home/greg/40k/frontend/wasm-los/src/lib.rs))
   > = même primitive 2D.

   **Conséquence des deux cas types (unité tireuse 1008 au niveau 1)** :
   - **Cible SOUS un étage** (fig au sol, empreinte sous l'empreinte d'un plancher supérieur) : le
     plancher est une surface **opaque** entre le tireur au-dessus et la cible en-dessous → devrait
     bloquer (True LoS §06.01 : on ne voit pas à travers une surface solide ; la ruine est **dense/Solid**
     §13.05/§13.11). Aujourd'hui le moteur ne modélise **que les murs verticaux** (`wall_set`) ; le
     **plancher horizontal** n'est un obstacle ni de move ni de LoS → la cible ressort **visible à tort**.
   - **Cible AU SOL à côté de l'empreinte de l'étage** (tireur surélevé) : la LoS est tracée en 2D pur
     entre empreintes ; le niveau du tireur (1) et celui de la cible (0) **n'interviennent pas**. Seul le
     `wall_set` (mur de la ruine, prolongé à tous les niveaux, cf. décision 2b §409-413) bloque — et il
     bloque **à tous les niveaux identiquement**, sans la nuance Solid §13.11 (au-dessus de 3" la vue passe
     par les ouvertures).

   **Règles (lues — `13 Terrain.pdf`, `06 Other concepts.pdf`, `22 Other rules and abilities.pdf`)** :
   - **VISIBILITY §06.01 (True Line of Sight)** : LoS = ligne 1 mm de n'importe quelle partie de
     l'observateur vers n'importe quelle partie de la cible ; les modèles des deux unités sont ignorés au
     tracé. Une **surface solide** (mur **ou plancher**) bloque par nature (on ne voit pas au travers).
   - **SOLID §13.11** (les dense/ruines l'ont) : « Line of sight cannot be drawn across any **enclosed gap
     in the surface** of such a terrain feature that is **3" or less from ground level**. » → **sous 3"** du
     sol, la LoS ne traverse **aucune ouverture** (porte/fenêtre/impact) ; **au-dessus de 3"**, la LoS se
     trace **normalement à travers les ouvertures** (exemple officiel : units A/C visibles au-dessus de 3",
     A/B invisibles à travers la fenêtre sous 3"). Designer's Note : 3" = hauteur du 1er étage, **ajustable
     par mission** → seuil **configurable** (cf. §2.3).
   - **OBSCURING §13.10** : si **toute** LoS entre 2 figs traverse une obscuring area (hors celle où l'une
     des deux se trouve), elles ne se voient pas. Une fig posée **sur** l'étage d'une ruine obscuring est
     **dans** cette area → exclusion la concernant (déjà géré en 2D par `excluded_areas`, à conserver).
   - **PLUNGING FIRE §22.05** : contre une cible **visible** contenant ≥1 fig **au sol**, **+1 BS** si
     **(a)** le tireur est sur une section **≥ 3" de haut**, **OU (b)** le tireur a **TOWERING** et la
     cible est ≤ **12"**. (Sans effet pour AIRCRAFT, §23.03.)

   **Données déjà disponibles (aucune nouvelle donnée terrain/unité à créer, chantier 1 + §6e + engagement 3D)** :
   - Par figurine dans `units_cache` : `level_by_model` (niveau), `floor_height_by_model` (**hauteur du
     plancher sous la fig, en pouces**, résolue par position — [shared_utils.py:773](file:///home/greg/40k/engine/phase_handlers/shared_utils.py#L773)
     + recompute :2917) et `MODEL_HEIGHT` (borne haute, :788). → chaque fig = **intervalle vertical**
     `[floor_height, floor_height + MODEL_HEIGHT]`, **exactement** la convention de l'engagement 3D
     (§01.04 « partie la plus proche », pas plancher-à-plancher).
   - `floors` du terrain rasterisés : `{level, height_inches, polygon_vertices, hexes}` par étage
     ([game_state.py:1581](file:///home/greg/40k/engine/game_state.py#L1581) `_parse_terrain_floors`) ;
     helpers `floor_hexes_at_level` / `floor_height_at` / `floor_polys_at_level`
     ([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)) déjà écrits.

   **Implémentation optimale (additive → zéro régression 2D, une seule primitive, miroir WASM)** :

   La règle d'or du fichier : **toute évolution du blocage se fait dans `_los_line_segment_clear`, une seule
   fois** (docstring :3904-3906), puis répliquée dans le Rust. Le plan enrichit cette primitive et le fait
   par-figurine (le tracé cible est déjà par-modèle, :4288), en threadant les niveaux/hauteurs source+cible.

   1. **Signature niveau-consciente (additive).** Ajouter à `_los_line_segment_clear` (et à `_los_hex_visible`,
      `_compute_visibility_with_obscuring`, la boucle :4288) les paramètres **optionnels**
      `src_height`, `tgt_height` (hauteurs de tir/cible en pouces = `floor_height` de la fig +/− offset de
      silhouette) et l'accès aux `floors` (via `game_state`). **`None` partout → chemin actuel byte-identique**
      (tous les call-sites 2D — RL/obs mono-niveau — restent inchangés → zéro régression, patron exact de
      `vertical_zone_inches` de l'engagement 3D). Le pair-cache (`_unit_los_pair_cache`, clé `(sid,tid)`) reste
      valide (invalidé par `_touch_unit_los` à chaque move/perte — **vérifié** : `update_model_position` appelle
      `_touch_unit_los` même quand l'ancre ne bouge pas, et un changement de niveau passe toujours par ce chemin) ;
      **le `hex_los_cache` 2D `((col,row),(col,row))` doit intégrer les niveaux** sous peine de collision entre
      deux paires aux mêmes (col,row) mais niveaux différents (§4.4). ⚠️ **Trois sites à migrer ensemble**
      (vérifié 2026-07-10) : les DEUX writers de la clé — `has_line_of_sight`
      ([combat_utils.py:538](file:///home/greg/40k/engine/combat_utils.py#L538)) **et**
      `has_line_of_sight_coords` (`:578`) — plus l'**invalidation sélective** qui filtre les clés en supposant
      leur forme actuelle ([shooting_handlers.py:2017-2028](file:///home/greg/40k/engine/phase_handlers/shooting_handlers.py#L2017-L2028)).

   2. **Plancher-occulteur horizontal (cas « sous un étage » — le vrai trou).** Pour chaque hex du `hex_line`
      **et les deux extrémités**, tester s'il appartient à un `floor` de niveau `L_f` / hauteur `h_f` : la LoS
      est **bloquée** à cet hex si la sightline **franchit le plan du plancher au-dessus de CET hex**.
      ⚠️ **Interpolation obligatoire le long du tracé** (correction de review 2026-07-10) : le test naïf
      « `min(src_height,tgt_height) < h_f < max(...)` » bloque dès que le plan est entre les deux hauteurs
      d'extrémité, **où que soit l'hex sur la ligne** — faux positif de blocage (ex. : tireur L2 à 6",
      cible au sol à 20" ; un plancher 3" d'une AUTRE ruine à 1 hex du tireur → la ligne y passe encore à
      ~5,7", au-dessus du plancher, mais le test naïf bloque). Test correct, toujours O(1) par hex :
      la hauteur de la ligne à l'hex d'index `i` sur un tracé de `n` pas est `h(t) = src + t×(tgt−src)`
      avec `t = i/n` (le `hex_line` est un cube-lerp, `t` est déjà la fraction du parcours) ; blocage à
      l'hex ssi l'hex ∈ `floor_hexes_at_level(L_f)` ET `h(t)` passe du côté opposé de `h_f` par rapport à
      la source (franchissement local du plan).
      **Cohérence avec les intervalles** (cf. « Hauteur de tir » ci-dessous) : les extrémités sont des
      intervalles `[lo, hi] = [floor_height, floor_height + MODEL_HEIGHT]`, pas des scalaires — True LoS
      §06.01 = visible si **au moins une** ligne intervalle→intervalle passe. Le blocage n'est donc acquis
      que si **toutes** les lignes franchissent le plancher à un hex couvert. Test exact avec les deux
      droites extrêmes (`src_lo→tgt_lo` et `src_hi→tgt_hi` : à chaque `t`, les hauteurs atteignables par
      les lignes intervalle→intervalle forment exactement l'intervalle entre ces deux droites) : calculer
      le point de franchissement du plan `h_f` de chacune (`t* = (h_f − src)/(tgt − src)`) ; les lignes
      intermédiaires franchissent toutes entre `t*_lo` et `t*_hi` → **bloqué ssi TOUS les hexes du tracé
      dans l'intervalle `[min(t*_lo,t*_hi), max(t*_lo,t*_hi)]` appartiennent au plancher** (un seul hex
      non couvert dans cette fenêtre = une ligne passe = visible). Un plancher **au niveau des deux
      extrémités** (même étage) ne
      bloque pas (pas de franchissement). **Source** : `floor_hexes` + `height_inches` déjà rasterisés,
      aucun raycast 3D coûteux.
      **Trois cas limites à spécifier (review 2026-07-10, 2ᵉ passe)** :
      - **Intervalle à cheval sur le plan** (`lo < h_f < hi` strict) : ≥1 ligne ne franchit jamais →
        **jamais bloqué par ce plancher**. C'est la géométrie correcte (pas un fallback) : l'état n'est
        atteignable aujourd'hui que par les chemins sans clairance (pool squad/IA, voile rouge — RESTE À
        FAIRE item 3) et devient impossible une fois l'item 3 câblé, mais la branche reste juste.
      - **Égalité au plan = cas NOMINAL, résolue par le NIVEAU, jamais par comparaison de flottants.**
        Tout tireur posé sur un étage a `src_lo == h_f` (pieds au plan), et la fig **tangente**
        (`MODEL_HEIGHT == height_inches`) est **légale en permanence** (`low_clearance_ground_hexes` =
        `<` strict, « tangence autorisée », vérifié) → `tgt_hi == h_f`. Aucune convention flottante
        globale ne marche : « == compte dessous » rend le plancher transparent sous les pieds du tireur
        (ligne pieds→cible-dessous ne « franchit » plus) ; « == compte dessus » rend visible d'en haut la
        fig tangente sous le plancher. Règle : le côté d'une extrémité à égalité se décide
        **physiquement par le niveau** de la fig vs le plancher testé — fig posée sur/au-dessus de ce
        plancher (`floor_height ≥ h_f`) → côté **dessus** ; fig à un niveau inférieur sous ce plancher →
        côté **dessous**. Déterministe, données déjà présentes (`level_by_model`/`floor_height_by_model`).
      - **Hauteurs égales aux deux bouts d'une droite extrême** (`src == tgt`, ex. deux figs au sol — le
        chemin emprunté à CHAQUE tir dès qu'un hex de plancher est sur le tracé) : dénominateur de `t*`
        nul → ligne horizontale → **aucun franchissement** (deux figs au sol se voient sous un bâtiment,
        murs à part). Garde **explicite en tête de test**, pas une division qui échoue.

   3. **Solid §13.11 — nuance ≤3" / >3".** Le `wall_set` bloque aujourd'hui **inconditionnellement**. Trois
      variantes (décision §5) :
      - **(a) conservateur** : garder les murs pleins à tous niveaux → jamais de faux positif (« tir à
        travers un mur »), mais **ampleur réelle requalifiée** (review 2026-07-10) : ce n'est pas juste
        « une fenêtre haute refusée ». Un tireur posé sur l'étage d'une ruine **murée** (cas réel :
        `ruin_center` porte des murs dense+light, vérifié dans `terrain-mc1.json`/`terrain-floors-test.json`,
        20 murs racine typés `light`/`dense`) ne peut **jamais** tracer vers l'extérieur si le tracé 2D
        croise un hex de mur du périmètre. Combiné à l'obscuring maintenu 2D (step 4, conforme RAW),
        **monter n'apporte alors AUCUN avantage de visibilité** — en playtest, la verticalité se lirait
        comme un bug (« je suis monté, je ne vois rien de plus, et je ne vois plus ce qui est sous moi »).
        Tension directe avec l'encart §13.06 (« As well as gaining superior lines of sight… »).
      - **(b1) seuil-only — LA variante fidèle ET la moins chère (RECOMMANDÉE, même passe que le step 2)** :
        bloquer sur un hex de mur **ssi la hauteur interpolée de la ligne à cet hex ≤ `solid_ground_clearance`**
        (3", configurable — Designer's Note « some missions may adjust »). C'est exactement l'exemple RAW
        de §13.11 : au-dessus de 3", la LoS passe **à travers les ouvertures** (unités A/C du PDF), pas
        seulement par-dessus — les murs de ruine dense sont archétypalement ajourés. **Zéro donnée terrain
        nouvelle** (mêmes `{name, type, segments}`), même helper d'interpolation que le plancher-occulteur.
        Faux positif résiduel : un mur réellement **plein** (sans ouvertures) devient transparent au-dessus
        de 3" — c'est le seul cas qui justifie (b2).
      - **(b2) donnée par-mur (backlog, pas un prérequis)** : `height_inches` ou flag `solid` sur les
        entrées `walls` pour les murs **pleins** (blocage jusqu'au sommet, transparence au-dessus — test
        « la ligne passe au-dessus du sommet », même interpolation). Note : (b2) seule serait MOINS fidèle
        que (b1) pour les ruines (un mur ajouré de 6" bloquerait une ligne à 4" que la règle laisse passer
        par la fenêtre) — (b2) complète (b1), ne la remplace pas.
      → **Décision : implémenter (b1) avec le step 2 dans la même passe** (même helper) ; (a) conservé en
      **kill-switch config** (revenir aux murs pleins si besoin), pas en défaut ; (b2) en backlog pour les
      murs pleins. **Périmètre type de mur à trancher au passage** : §13.11 ne couvre que les murs
      **dense** ; RAW, un mur `light` ne bloque pas la LoS du tout (light ne fait que rendre l'area
      obscuring + cover §13.04/§13.08/§13.10), or le `wall_set` actuel bloque light et dense
      indistinctement — appliquer (b1) aux deux types, ou dense seulement (light = jamais bloquant,
      plus fidèle mais changement de comportement 2D existant → à décider explicitement).

   4. **Obscuring §13.10 : inchangé.** L'exclusion par area occupée (tireur/cible) reste 2D et **correcte**
      (une fig **sur** l'étage est dans l'area de la ruine → déjà exclue via `excluded_areas`). Rien à
      modifier ; juste vérifier que `level_by_model` n'altère pas l'appartenance d'area (les `hexes`
      obscuring sont 2D, une fig à l'étage a son (col,row) dans l'empreinte → inclusion préservée).
      **Condition de validité (review 2026-07-10)** : ce raisonnement suppose `floor ⊆ empreinte de l'area
      parente`. La fig ne peut pas déborder du **plancher** (§13.06, enforce partout), mais **rien ne
      valide** au parsing que les `vertices` d'un étage sont inclus dans ceux de l'area
      (`_parse_terrain_floors`, [game_state.py:1581](file:///home/greg/40k/engine/game_state.py#L1581) —
      vérifié : aucune contrainte d'inclusion ; les données actuelles la respectent, `ruin_center` L1/L2
      dans l'empreinte). Un étage débordant casserait silencieusement l'exclusion (fig sur le surplomb →
      (col,row) hors `obscuring_by_hex` → la ruine bloquerait sa propre occupante) **et**
      `floor_height_at`/le contrôle d'objectif par appartenance. → **Ajouter la validation au parsing**
      (hexes du floor ⊆ hexes de l'area, `ValueError` explicite, pas de fallback) — l'invariant devient
      structurel, aucun code LoS supplémentaire.

   5. **Plunging Fire §22.05 (bonus BS, hors LoS pure).** Après confirmation de visibilité, **+1 BS** si la
      cible contient ≥1 fig au sol (`level_by_model` == 0 pour ≥1 modèle cible) ET **(a)** la section du
      tireur est ≥3" (`floor_height_by_model` du tireur ≥ `seuil_plunging`, config) **OU (b)** tireur
      TOWERING (keyword) et cible ≤12". À brancher dans le **calcul de BS du tir**
      (pas dans `compute_unit_los`) — la visibilité reste binaire, le bonus est un modificateur d'attaque.
      Config `plunging_fire_height: 3` (POUCES, non scalé, pendant de `engagement_zone_vertical`).
      **Approximations assumées (review 2026-07-10)** : le « ≤12" » de la branche TOWERING sera mesuré en
      **2D** tant que le chantier « Distances 3D » (roadmap item 4) n'est pas fait — cohérent avec toutes
      les autres distances du moteur, à migrer avec elles. L'exception AIRCRAFT §23.03 (vérifiée PDF :
      « no effect on attacks made by, **or targeting**, AIRCRAFT units ») est **hors périmètre** — aucun
      AIRCRAFT dans le moteur pour le moment ; à gater sur le keyword si des AIRCRAFT sont ajoutés.

   6. **Parité WASM (Rust).** Répercuter (2) et, si retenu, (3b) dans `has_los_fast`
      ([lib.rs:84](file:///home/greg/40k/frontend/wasm-los/src/lib.rs)) : passer les hauteurs src/tgt + les
      `floor_hexes`/`height_inches` au module, même test d'interpolation de franchissement de plancher, **puis
      rebuild du wasm**. Sinon le cône de preview front (WASM) diverge du ciblage back (Python) → « une cible
      blinke mais n'est pas ciblable » (le doc §3.3 signale déjà ce risque de divergence). Le back reste la
      source de vérité du ciblage ; le WASM ne sert que la preview.
      ⚠️ **« Même primitive » est approximatif** (review 2026-07-10) : la sémantique obscuring du Rust
      diffère du Python — le Rust compare l'area de chaque hex intermédiaire à `dest_area` et exige que
      l'appelant ait **zéroté** les areas du tireur dans `obscuring_grid`, quand le Python exclut le set
      `excluded_areas` (areas tireur **+ cible**) dans la primitive. Au portage des hauteurs, mapper cette
      différence explicitement — ne pas copier-coller la logique Python.

   **Hauteur de tir / de cible (offset de silhouette)** : par défaut, prendre l'**intervalle**
   `[floor_height, floor_height + MODEL_HEIGHT]` des deux côtés et tester le franchissement du plan plancher
   par les lignes intervalle→intervalle (critère exact des deux droites extrêmes, step 2). Cohérent avec
   l'engagement 3D (§01.04) et sans donnée nouvelle. Approximation résiduelle inévitable (silhouette réelle
   non chiffrée dans les PDF, §2.11) — même statut assumé que la True LoS et que l'engagement.

   **Côté tireur PAR-FIGURINE (décision 2026-07-10 : respecter les règles au maximum).** `compute_unit_los`
   est par paire d'unités : par-modèle côté **cible** seulement ; côté tireur = ancre + vantages latéraux,
   avec UNE hauteur. Or une escouade **répartie sol/étage** est un cas supporté (§6d) et §06.01/§22.05 sont
   par-modèle observateur/attaquant. Spécification retenue :
   - **Visibilité** : la cible (unité) est visible s'il existe **≥1 figurine tireuse** qui voit ≥1 modèle
     cible — chaque fig tireuse trace avec **sa** hauteur (`floor_height_by_model[mid]` + intervalle
     `MODEL_HEIGHT`), depuis **son** hex (`occupied_hexes_by_model`). Escouade homogène en niveau (cas
     ultra-majoritaire) → une seule passe, identique à l'ancre actuelle ; hétérogène → une passe par
     **classe de niveau** (mêmes classes que `_vertical_classes` de l'engagement 3D), pas par fig.
   - **Plunging Fire** : §22.05 est par **modèle attaquant** (« Each time a model makes a ranged attack ») —
     le +1 BS ne s'applique qu'aux attaques des figs dont la section est ≥3". Escouade mixte sol/étage →
     brancher sur l'**attribution par-arme/figurine** déjà en place (le BS se résout par fig porteuse),
     jamais un +1 unité-entière.
   - Le pair-cache reste par (sid,tid) : le résultat agrégé « ≥1 fig voit » y est stocké comme aujourd'hui.

   **Non-régression** : `src_height=tgt_height=None` (tous les appels actuels) → primitive **byte-identique**
   2D ; plateau **sans `floors`** → aucun plancher-occulteur, `wall_set` seul → identique à aujourd'hui ;
   RL/obs (métrique mono-niveau, `hex`) non concernés. **Validation** : script d'intégration dédié (miroir
   [scripts/charge3d_integration_test.py](file:///home/greg/40k/scripts/charge3d_integration_test.py) sur
   `scenario_floors_test` : tireur L1 vs cible sous l'étage → **bloquée** ; vs cible au sol à côté, mur
   dense entre les deux → **visible** si la ligne interpolée passe le mur au-dessus de `solid_ground_clearance`
   (b1), **bloquée** avec le kill-switch (a) ; deux figs au sol de part et d'autre du bâtiment → **visibles**
   sous le plancher (garde hauteurs égales), murs à part ; fig tangente (`MODEL_HEIGHT == height_inches`)
   sous l'étage vs tireur au-dessus → **bloquée** (égalité résolue par niveau) ; Plunging +1 BS depuis L1,
   +1 refusé aux figs de la même escouade restées au sol (par-arme/figurine)) + app sur `scenario_floors_test`
   + réutilisation de
   l'invariant `assert_los_pair_cache_consistent` (le pair-cache doit rester cohérent avec la nouvelle
   géométrie). **Le RL étant HS**, c'est le seul filet de non-régression du gameplay 3D (comme pour charge/mêlée).

   **Ordre d'implémentation suggéré** : 1 (signature + cache niveau) → **2 + 3(b1) dans la même passe**
   (plancher-occulteur + seuil Solid sur les murs : même helper d'interpolation, ferme le cas 120 ET donne
   le bénéfice de vue en hauteur — livrés ensemble, sinon la verticalité se joue comme un bug) →
   **6 (parité WASM, immédiatement après)** → 5 (Plunging) ; 3(b2) (donnée mur plein) en backlog.
   6 remonté avant 5 (review 2026-07-10) : entre 2-3 et 6 la preview front montre visibles des cibles que
   le back refuse — fenêtre de divergence visible par l'utilisateur, à fermer au plus tôt ; Plunging (5)
   ne touche pas le WASM (BS uniquement). Le kill-switch (a) permet de neutraliser 3(b1) en config sans
   toucher au code si un plateau l'exige.

   **Décisions à trancher (checkpoints §5)** :
   - ~~Murs de ruine >3"~~ **TRANCHÉ (2026-07-10)** : variante **(b1) seuil-only** (blocage mur ssi hauteur
     interpolée ≤ `solid_ground_clearance`), livrée avec le step 2 ; (a) murs pleins = kill-switch config ;
     (b2) donnée par-mur pour murs pleins = backlog — cf. step 3.
   - **Périmètre type de mur pour (b1)** : dense seulement (fidèle RAW — un mur `light` ne bloque pas la
     LoS §13.04/§13.10, mais le `wall_set` 2D actuel bloque tout → changement de comportement existant)
     vs light+dense (conservateur, aucun changement 2D). **Reste à trancher.**
   - **Offset de silhouette** : intervalle `[h, h+MODEL_HEIGHT]` (recommandé) vs point unique (plancher).
   - **Seuils configurables** : `solid_ground_clearance` (3", Solid) et `plunging_fire_height` (3", Plunging)
     — deux mesures **distinctes** (§2.3 : gap « from ground level » vs section « in height »), ne pas fusionner.
   - ~~Côté tireur mono/par-figurine~~ **TRANCHÉ (2026-07-10)** : par-figurine (classes de niveau), Plunging
     par-arme/figurine — cf. « Côté tireur PAR-FIGURINE » ci-dessus.

   ### ⏳ RESTE À FAIRE (mis à jour 2026-07-08)

   1. ✅ **Engagement 3D (chantier 4) — FAIT & VALIDÉ** : étapes 1 (fondation `floor_height_by_model` +
      `MODEL_HEIGHT` dans `units_cache`), 2 (primitive `entries_in_engagement_zone(..., vertical_zone_inches)`
      + config `engagement_zone_vertical: 5` + getter + wrappers), 3a (18 call-sites charge câblés, FLY différé).
      Validé sur le vrai scénario ([scripts/charge3d_integration_test.py](file:///home/greg/40k/scripts/charge3d_integration_test.py)).
      Non-régression pytest **entièrement rétablie** (`python3 -m pytest tests/` → **1152 passed, 2 skipped, 0 failed** ;
      dette de stubs `level`/`MODEL_HEIGHT`/`engagement_zone_vertical`/`_unit_move_version` + 7 tests obsolètes
      de la refonte advance→move réparés au passage).
   2. ✅ **3b — Champ climb-aware dans la charge (chargeur qui MONTE) — FAIT & VALIDÉ EN APP (2026-07-08)** :
      helper climb charge (`reachable_multilevel_field`, budget = jet, coût §13.06), `_compute_plan_context`
      niveau-conscient (reach étage par-fig + `floor_region_by_base` via primitive 3D, phase inclut l'étage),
      pool `[col,row,level]`, clip sol-only, affichage **mono-niveau**, preview/commit/`_charge_model_pos_is_closer`
      niveau (reachability climb pour une ancre d'étage), **collision cross-niveau** (obstacles/siblings filtrés
      par niveau), `provisional_plan` porté, front (Map niveau + pose/commit niveau + `perModelPlanView` préserve
      le niveau par-fig). Détail complet + pièges + bugs résolus dans la section chantier 4 ci-dessus. Validé
      bout-en-bout **dans l'app** (charge d'une fig vers l'étage : pool → pose → commit engagé) +
      `scripts/charge3d_integration_test.py` étendu + pytest **1152 passed / 0 failed** + tsc vert.
   2bis. ✅ **Mêlée 3D — pile-in (§12.03) & consolidation (§12.08) niveau-conscients : FLUX MANUEL PvP FAIT
      (2026-07-08, compile Python + import + `tsc` verts, NON validé runtime)**. Miroir move complet (option A) :
      une fig déjà en hauteur peut **rester** sur son étage ET **changer** de niveau dans le budget 3".

      **Fait — backend** ([fight_handlers.py](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py)) :
      - Pools par-figurine `_fight_pile_in_build_model_pool` / `_fight_consolidation_build_model_pool` : nouveau
        param `view_level`. `view_level == 0` = BFS sol historique **inchangé** (zéro régression). `view_level >= 1` =
        cases du plancher atteignables avec le coût vertical, via `reachable_multilevel_field`, **seedé au niveau
        EFFECTIF courant du mover** (≠ move par-fig qui seed toujours au sol → une fig en hauteur ne repaie pas la
        montée). Bloqueurs/coéquipières filtrés par **niveau effectif de destination** (superposition inter-étage).
      - Réutilisation directe du reachable d'étage de move : ajout d'un `start_level=0` optionnel rétro-compatible à
        [`_model_climb_reachable_floor_cells`](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)
        (aucune régression move) + wrapper lazy `_fight_model_climb_reachable_floor_cells` (évite le cycle d'import).
        Helper `_fight_fig_effective_level` (lit `level_by_model`, repli niveau d'unité).
      - Plans en **4-tuples `(mid,col,row,level)`** : preview (`_fight_pile_in_preview_plan` /
        `_fight_consolidation_preview_plan` testent la légalité par-fig **au niveau planifié**), `model_plan_state`
        (param `view_level` ; `provisional`/`origin`/`full_plan` portent le niveau ; `current_level` exposé au front),
        dispatch (`_prov_from_action` capture `e[3]` + `action.level` ; commit construit des 4-tuples ; `moveDetails`
        porte `toLevel`), commit via `commit_move` (gère déjà le 4ᵉ élément ; `level=None` = garder niveau).
      - Activation d'unité : `view_level` initial = niveau de l'unité (1er rendu correct).

      **Fait — frontend** ([useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts) +
      [BoardPvp.tsx](file:///home/greg/40k/frontend/src/components/BoardPvp.tsx)) :
      - Miroir move : les 6 flux pile-in/conso (`*_plan_state`, `select_target/objective`, `commit_*`, autoplace)
        envoient `action.level = currentLevel` + un niveau par-fig (pose = niveau de vue au drop) ; state `models`
        typé `{col,row,level?}`.
      - Re-fetch du pool de la fig active au **changement d'étage** (effet `currentLevel` étendu à pile-in/conso,
        miroir move/charge). Bouton d'étage **non gaté par phase** (`maxFloorLevel >= 1`) → dispo en fight. Le rendu
        par-fig lit déjà `plan.models[mid].level`.

      **Conformité 40k** (PDF 12 relu) : 12.03/12.08 = « moves as described in Moving (03) » → mouvement vertical
      dans les 3" autorisé, ce que le miroir applique. Contrainte WHILE « strictement plus proche » restée
      **horizontale** (cohérente avec tout le moteur ; gate vertical 5" = manque transverse déjà documenté).

      **RESTE À FAIRE (2bis) :**
      - **Validation runtime PvP** (impossible headless) : tester unité 119 (niveau 1) sur un scénario à planchers —
        sélection fig → bouton étage → pool sur le plancher → pose → commit → fig rendue au bon niveau ; idem conso.
      - **IA auto pile-in** ([`_fight_v11_auto_pile_in`](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py)
        → `_fight_build_pile_in_valid_destinations` + `_fight_apply_pile_in_move`, **move rigide par ancre**) : encore
        **2D** → une unité IA niveau 1 descend. Moteur distinct (translate rigide de l'escouade), **non porté**.
      - **Autoplace ILP Focus** (`pile_in_autoplace_plan` / `consolidate_autoplace_plan`) : génération de slots **au
        sol** → à niveau ≥1 le preview (désormais level-aware) **REJETTE** le plan (pas de commit silencieux faux,
        mais bouton Focus inopérant en hauteur). Portage multi-niveaux de la génération de slots = chantier dédié.
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

## 7. Fight phase multi-niveaux — pile-in / consolidation (corrections)

Corrections apportées au flux **par-figurine** PvP (pile-in 12.03 / consolidation 12.08). Le
pile-in et la consolidation partagent le même moteur (fonctions miroir) : chaque correction est
appliquée aux **deux**.

### 7.1 Source du niveau à l'activation — miroir move
- **Bug** : « le premier niveau n'était pas reconnu ». L'activation lisait `unit["level"]` (niveau de
  l'ancre, liste `units`) alors que les refresh/commit utilisaient le niveau de **vue** `currentLevel`.
  De plus `unit["level"]` n'était **pas** resynchronisé après une charge (seul le commit move le faisait,
  [movement_handlers.py:3490](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)).
- **Corrigé** :
  - Backend : l'activation pile-in/consolidation utilise `_view_level` (niveau de vue transmis par le
    front), cohérent avec refresh/commit — [fight_handlers.py](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py)
    (`_fight_pile_in_model_plan_state` / `_fight_consolidation_model_plan_state` via `activate_unit`).
  - Front : `activate_unit` en phase fight envoie `level: currentLevel` —
    [useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts) (`handleSelectUnit`).
  - Charge : `unit["level"]` resynchronisé sur l'ancre au commit charge (miroir du commit move) —
    [charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py) (`charge_commit_move_plan_handler`).
- **Code mort supprimé** : `handleActivateFight` / `onActivateFight` (jamais invoqué — l'activation
  fight passe par `onSelectUnit` → `handleSelectUnit`) dans useEngineAPI, BoardPvp, BoardWithAPI, boardClickHandler.

### 7.2 Placement sur étage — convention EUCLIDIENNE (§13.06)
`footprint_within_floor` / `validate_floor_placement` / `resolve_model_floor_level`
([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)) : pour une base **ronde**, le
confinement « entièrement sur le plancher » est un test euclidien disque↔polygone
(`disc_within_any_polygon` sur `floor_polys`), aligné pixel-pour-pixel sur le rendu et sur la charge.
Supprime le rejet d'~½ hex de la rasterisation hex qui « coinçait » une fig ronde posée au **bord** d'un
étage (elle apparaissait dans la zone mais était jugée « déborde » → aucune destination pile-in valide).

### 7.3 Collision par-figurine — empreinte COMPLÈTE
Les blocker socles ennemis du pool pile-in/consolidation sont construits via `_charge_model_socle`
(empreinte réelle par figurine, même convention que le mover et les sœurs) au lieu de `fp={hex central}`
([fight_handlers.py](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py)). Corrige la
superposition partielle qui était permise contre une base **non-ronde** (la méthode empreinte ne testait
que le hex central). Base ronde inchangée (collision par disque euclidien, `fp` ignoré).

### 7.4 Obstacles au sol filtrés par NIVEAU + clairance verticale — miroir move
- `enemy_occupied` tous-niveaux remplacé par les ennemis **au niveau 0** uniquement
  (`build_enemy_occupied_positions_set(..., level=0)`) : un ennemi **en hauteur** ne bloque plus le
  cheminement ni les destinations au sol (superposition inter-étage §13.06). Ça alignait enfin l'obstacle
  de traversée sur les `blocker_socles`, déjà filtrés par niveau effectif.
- Ajout de la **clairance verticale** `_low_clear = low_clearance_ground_hexes(terrain_areas, MODEL_HEIGHT)`
  aux obstacles sol (§13.06 / §2.11 : une fig trop haute ne peut finir/passer **sous** un plancher trop
  bas) — auparavant **absente** du pile-in (masquée par `enemy_occupied` tous-niveaux). Appliqué aux deux
  branches (BFS sol + seed sol de la branche étage), miroir exact du move
  ([movement_handlers.py:2986](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)).
- **Effet** : une fig au sol peut piler/consolider vers la projection d'une cible en hauteur, **sans**
  finir sous un plancher trop bas pour elle. — **✓ Validé runtime PvP.**

### 7.5 Connu / à faire
- **Flux pile-in unit-level (V10 / IA)** ([fight_handlers.py](file:///home/greg/40k/engine/phase_handlers/fight_handlers.py),
  ~`pile_in_move_destinations_12_03`) : mêmes défauts **non corrigés** (`enemy_occupied` tous-niveaux +
  blocker `fp={hex central}`). À aligner si ce flux reste utilisé (hors flux PvP par-figurine).
- **Pool par niveau propre** : le pile-in/consolidation calcule **toutes** les figs au `view_level`
  global. Une escouade répartie sur plusieurs étages (§2.5) doit être pilée en **basculant la vue par
  niveau** (paradigme mono-niveau, miroir move). Amélioration possible : calculer chaque fig à son niveau
  effectif (`models_cache[mid]["level"]`), le `view_level` ne servant qu'à un **changement** de niveau
  explicite. Une **auto-bascule** de la vue a été écartée (diverge de move, casse le multi-niveau).
- **Écart 2D/3D** : l'engagement et la sélection de cibles pile-in sont mesurés en **2D pur**
  (`unit_entries_within_engagement_zone` sans `vertical_zone_inches`) ; le « closer » est mesuré en 2D
  horizontal vers la **projection** de la cible. Correct pour une cible en hauteur (distance 3D monotone à
  hauteur constante) mais pas 3D strict (cf. §2.7).

## 8. Charge phase multi-niveaux — corrections

Corrections apportées au flux de **charge** PvP (11.02–11.04), en cohérence avec le move (§3.4) et le
fight (§7). La charge utilise l'engagement 3D (`vertical_zone_inches`) déjà en place ; les corrections
portent sur le **confinement du bord d'étage** et le **blocage de traversée par niveau**.

### 8.1 Confinement euclidien du bord de niveau — base ronde (§2.6, §13.06)

Le test « socle entièrement sur l'étage » était en **hex rasterisé** (`fp <= floor_hexes`) pour toutes
les bases, ce qui tolérait qu'un disque rond **déborde d'~½ hex** le bord du plancher (le rendu montrait
le socle dépassant dans le vide alors que le moteur validait). Corrigé par un test **euclidien continu
disque↔polygone** pour les bases rondes, aligné pixel-pour-pixel sur le rendu.

- **Primitives** ([hex_utils.py](file:///home/greg/40k/engine/hex_utils.py)) : `disc_within_polygon`
  (centre dans le polygone **et** distance min du centre à chaque arête ≥ rayon — exact pour tout polygone
  simple, convexe ou concave ; tangence tolérée) et `disc_within_any_polygon` (inclusion dans ≥ 1 polygone
  d'étage ; conservateur sur une union, jamais de débordement autorisé). Pendant strict de
  `disc_overlaps_polygon`.
- **Source partagée** ([terrain_utils.py](file:///home/greg/40k/engine/terrain_utils.py)) :
  `floor_polys_at_level` (polygones d'étage en repère `_hex_center`) ; `footprint_within_floor` bascule sur
  l'euclidien pour base **ronde** quand `floor_polys` est fourni (oval/carré → méthode hex inchangée, même
  convention hybride que `model_within_terrain`) ; `validate_floor_placement` et `resolve_model_floor_level`
  alimentent les polygones pour base ronde. **C'est la source unique référencée par §7.2** — move, charge,
  fight et déploiement en héritent, donc aucune divergence.
- **Câblage boucles chaudes** : polygones précalculés **une fois par niveau** (pas par case) — pool d'étage
  du move ([movement_handlers.py:2052](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py))
  et pool de montée de charge
  ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py),
  `_charge_model_climb_reachable_floor_cells`), ce dernier appelant désormais `footprint_within_floor`
  directement (hexes + polygones précalculés) au lieu de `validate_floor_placement` par case (supprime le
  re-check mot-clé et la reconstruction des hexes), miroir du move.
- **Optimalité** : euclidien seulement sur base ronde ; plateau sans étage → tout niveau 0 → résultat
  identique à l'ancien (non-régression 2D) ; RL/gym non touché.

### 8.2 Blocage de traversée filtré par NIVEAU — miroir move/fight (§7.4)

Le cheminement de charge au sol bloquait sur `enemy_occupied` **tous niveaux** (union `occupied_hexes` du
units_cache). Conséquence : un chargeur au sol ne pouvait pas passer ni **finir sous** l'empreinte d'une
cible/ennemi posé **en hauteur** (niveau ≥ 1), alors que deux figs à des niveaux différents ne se gênent
pas physiquement (§2.6, engagement 3D §2.7). Le déploiement de la conscience-niveau était **incomplet** :
les blocker socles finaux (`_charge_obstacle_socles`) étaient déjà filtrés par niveau dans 2 des 4
constructeurs de pool, mais la **traversée** ne l'était nulle part.

- **Corrigé** : la traversée sol et les obstacles-sol du climb bloquent désormais sur les ennemis **de
  niveau 0 uniquement**, via le helper partagé `build_enemy_occupied_positions_set(..., level=0)` (source
  par-figurine `models_cache`, déjà utilisé par le move et le fight §7.4 — **aucun doublon**).
- **Appliqué aux 4 constructeurs** de pool sol de charge
  ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)) :
  `charge_build_model_destinations_pool` (pool per-figurine PvP), `_compute_plan_context` (contexte mémoïsé
  + obstacles-sol du climb), `_charge_model_pos_is_closer` (validation d'une destination) et
  `charge_autoplace_plan` (autoplace).
- **Complément** : `_charge_obstacle_socles(..., level=0)` ajouté sur les 2 constructeurs où il manquait
  (pool per-figurine + autoplace ; déjà présent dans les 2 autres) → placement final cohérent sur les
  4 flux.
- **Conforme aux règles (PDF vérifié)** : engagement = **2" horizontal ET 5" vertical** (`03.04`) ; finir
  sous une cible à l'étage est légal et compte comme engagement si l'écart vertical ≤ 5", déjà géré par le
  gate 3D `entries_in_engagement_zone`. Seuls les sets de **blocage** ont changé ; cibles (`target_fps`) et
  interdiction d'engager un non-cible (AFTER MOVING) inchangées → aucune régression d'engagement.
- **Effet** : un chargeur au sol peut cheminer et **finir sous** la projection d'une cible en hauteur.
  — **✓ Validé runtime PvP.**

### 8.3 Outil de test — override de la distance de charge

Champ de saisie dans la barre des toggles de test (visible quand « bouton test Battle-shock » est activé
dans les settings), à côté de « Battle-shock test » et « A chargé test ». La valeur saisie (en pouces)
**remplace le jet 2D6** de charge — sert à tester des distances de charge déterministes (dont l'accès sous
un étage, §8.2). Vide → jet normal.

- **Front** : champ `chargeRollOverride` persisté en `localStorage`
  ([BoardWithAPI.tsx](file:///home/greg/40k/frontend/src/components/BoardWithAPI.tsx)) ; le hook envoie
  `charge_roll_override` (null si vide) à chaque action, même transport que `shoot_pool_require_los`
  ([useEngineAPI.ts](file:///home/greg/40k/frontend/src/hooks/useEngineAPI.ts)).
- **Backend** : la valeur est posée dans `game_state["charge_roll_override"]`
  ([api_server.py](file:///home/greg/40k/services/api_server.py)) ; aux 2 sites de jet 2D6
  (`charge_unit_execution_loop` à l'activation + `charge_target_selection_handler` en secours),
  l'override remplace le jet quand présent — **jamais en gym** (RL non impacté)
  ([charge_handlers.py](file:///home/greg/40k/engine/phase_handlers/charge_handlers.py)).
- **Usage** : la valeur est lue au moment de l'**activation** de l'unité (le jet est figé à l'activation) ;
  renseigner le champ **avant** d'activer l'unité qui charge.

## 9. Déploiement multi-niveaux — corrections (miroir move)

### 9.1 Clairance verticale (§2.11)

**Bug** : la clairance verticale (`low_clearance_ground_hexes` — une fig trop haute ne peut tenir **sous**
un étage trop bas, §2.11 / §13.06) était appliquée au move (§3.4) et au pile-in (§7.4) mais **absente du
déploiement**. Une fig `MODEL_HEIGHT` > hauteur libre d'un étage pouvait être posée au sol sous cet étage.

**Corrigé** — miroir move, sur les **3 surfaces** de placement du déploiement
([deployment_handlers.py](file:///home/greg/40k/engine/phase_handlers/deployment_handlers.py)) :
- `deployment_build_model_destinations_pool` (pool per-figurine) : `_low_clear` ajouté au blocage du
  **niveau 0** (`blocked_cube_by_level[0]`) — la case sous un étage bas n'est plus proposée.
- `deployment_preview_plan` (voile rouge) : une fig au sol (`lv == 0`) dont l'empreinte touche `_low_clear`
  est invalide (`low_clear_bad`).
- `generate_compact_formation` (auto-formation) : `_low_clear` bloqué dans `_legal_socle` (les figs qui ne
  rentrent pas tombent au centre, signalées rouge par le preview).

La pose **en surface** d'un étage (`lv >= 1`) n'est pas concernée (gérée par `validate_floor_placement`) ;
la clairance ne borne que le sol. `MODEL_HEIGHT` est `require_key` au chargement des unités
([game_state.py:189](file:///home/greg/40k/engine/game_state.py)) → toujours présent. Plateau sans étage
trop bas → `_low_clear` vide → non-régression 2D.

**Décision finale — méthode HEX uniforme (« comme le move niveau 0 »)** : les tests **euclidiens de bord
d'étage** que j'avais ajoutés (clairance `low_clearance_floor_polys` + straddle `_socle_overlaps_floor`) ont
été **retirés**. Ils créaient un **espace** visible au bord en vue étage (`disc_overlaps_polygon` compte la
tangence comme chevauchement, `≤ rayon` → la fig ne pouvait pas toucher le bord), alors que la méthode **hex**
`low_clearance_ground_hexes` donne le rendu voulu : la fig **touche** l'empreinte sans la **dépasser**.

Le bord et la clairance d'étage sont donc gérés **uniquement en hex**, à l'identique :
- **Deploy** — pool / preview / `generate_compact_formation` : seul `_low_clear` (hex) borne le sol.
- **Move** — `_socle_overlaps_floor` **retiré** du pool
  ([movement_handlers.py](file:///home/greg/40k/engine/phase_handlers/movement_handlers.py)) : les cases sol
  en vue ≥ 1 ne sont plus filtrées par un test euclidien de bord (`_ground_dests = eff == 0`), la clairance
  hex `_low_clear` (déjà dans les obstacles sol, toutes vues) suffit.

→ **deploy et move, vue 0 et vue 1, se comportent tous comme le move niveau 0** (touche sans dépasser, aucun
espace). La classification *sur l'étage* (§8.1, `footprint_within_floor` euclidien = empreinte entièrement
sur le plancher) reste inchangée. Base non-ronde : hex partout. 867 tests verts.
