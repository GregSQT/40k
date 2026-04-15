# Board ×10 — architecture runtime & RL

**Statut :** **seule référence normative** ×10 — géométrie **B**, LoS, pathfinding, occupation, RL, migration.  
**Dernière mise à jour :** 2026-04-14  
**Archives remplacées :** `Boardx10-11` … `Boardx10-33`, ancien contenu de `Boardx10.md` (→ **§19**).  
**[Boardx10.md](Boardx10.md) :** redirect non normatif.  
**Contraintes projet :** erreurs explicites, pas de fallback silencieux ([`.cursorrules`](../../.cursorrules)).

**Lecture :** sauf mention **« legacy »**, les règles décrivent la **cible Board ×10** (socles multi-cellules sur micro-grille). Le dépôt peut implémenter un sous-ensemble ; l'alignement code est **hors scope**.

**Objectif produit :** augmenter la **granularité** du plateau (**plus de cellules** pour la même emprise physique), **sans** changer l'**échelle de jeu** en pouces. Les constantes (MOVE, RNG, etc.) sont portées en **sous-hex** par **×10**. Chaque **unité** = un **socle** (`occupied_hexes`) — la taille dépend du profil d'unité (**§2.5**).

---

## Résumé exécutif

Passer à une micro-maille à **beaucoup plus de cellules** qu'aujourd'hui (ex. ordre **~250×210**, **sans** figer cette taille — **§2.2 P2**) est **faisable** si l'on **abandonne** une topologie **dense globale** en **Θ(n²)**.

Stratégie cible : **(a)** validation moteur en **sous-hex** — affichage pouces comme **vue dérivée** ; **(b)** géométrie **B** figée (**§2.2**), **offset odd-q** ; module unique de primitives **§2.3** ; **(c)** LoS et pathfinding **à la demande**, **bornés** ; **(d)** obstacles et occupation **sparse** (chunks arithmétiques, hash) ; **(e)** RL : **macro-actions**, observations **multi-échelle**, **MaskablePPO**, masques **O(k)**.

---

## 1. Rôles des documents

| Document | Rôle |
|----------|------|
| **Boardx10-final.md (ce fichier)** | **Seule source de vérité** ×10 : géométrie **B**, `COLS×ROWS`, LoS, pathfinding, empreintes, **§9.0** (`game_rules` cibles), RL, perf, **§19** (checklist fichiers). |
| **[Boardx10.md](Boardx10.md)** | **Non normatif** : redirect. |

Toute règle nouvelle reste alignée avec **`Documentation/AI_TURN.md`** et **`Documentation/AI_IMPLEMENTATION.md`**.

---

## 2. Contexte et échelle

### 2.1 État actuel (référence)

- **1 hex = 1 inch** ; plateau typique **25×21** hex « macro ».
- **Pré-calcul (legacy, supprimé) :** l'ancien `scripts/los_topology_builder.py` produisait des matrices **denses** n×n — supprimé car incompatible ×10. Remplacé par LoS on-demand + BFS borné (`hex_utils.py`).

### 2.2 Géométrie et granularité — P1, P2, P3

#### P1 — Mesure physique du sous-hex : plat à plat = 0,1″

**Norme produit (figée) :** distance **plat à plat** (flat-to-flat) d'une cellule = **0,1″**.

**Pourquoi plat à plat ?** Sur un hex régulier, pointe à pointe > plat à plat. Fixer 0,1″ en plat à plat donne l'intuition directe « **~10 cellules ≈ ~1″** de largeur » (utile pour les socles). Pour un hex **pointy-top**, le plat à plat correspond à la **largeur** horizontale — **~10** hex côte à côte horizontalement ≈ **~1″**.

**Moteur :** entiers (pas sur le graphe des sous-hex) ; 0,1″ sert au **brief physique**, pas à injecter des flottants.

#### P2 — Approche B (figée) : offset odd-q, plateau dimensionnable

**Décision :** pavage hexagonal avec coordonnées **offset odd-q** (`(col, row)` avec les colonnes impaires décalées de +½ row vers le bas). Système **identique** au code existant (`engine/combat_utils.py`).

**Système de coordonnées (figé) : offset odd-q**  
`(col, row)` avec `0 ≤ col < COLS`, `0 ≤ row < ROWS`. Les colonnes **impaires** (`col % 2 == 1`) sont décalées de +½ rangée vers le bas.

**6 voisins (offset odd-q) :**

Pour une colonne **paire** (`col % 2 == 0`) :

| Direction | Δcol | Δrow |
|-----------|------|------|
| N         | 0    | −1   |
| NE        | +1   | −1   |
| SE        | +1   | 0    |
| S         | 0    | +1   |
| SO        | −1   | 0    |
| NO        | −1   | −1   |

Pour une colonne **impaire** (`col % 2 == 1`) :

| Direction | Δcol | Δrow |
|-----------|------|------|
| N         | 0    | −1   |
| NE        | +1   | 0    |
| SE        | +1   | +1   |
| S         | 0    | +1   |
| SO        | −1   | +1   |
| NO        | −1   | 0    |

**Distance hex :** convertir `(col, row)` offset → **cube** `(x, z, y)` puis `distance = max(|Δx|, |Δy|, |Δz|)`. Formule de conversion offset odd-q → cube :

```
x = col
z = row - (col - (col & 1)) / 2
y = -x - z
```

**Construction du plateau :** grille rectangulaire de **`COLS` × `ROWS`** cellules en offset odd-q. Bornes lues en **config**. Pas de subdivision de macro-hex : **un plateau neuf**.

**Dimensions configurables :** `COLS` et `ROWS` ne sont **pas** figés à 250×210 ; ce sont des **paramètres** de `board_config`.

**Approche A (non retenue) :** grille 10×10 logique par hex inch — rejetée pour éviter la rigidité 100 cellules/macro et le couplage legacy.

**Exigences :** voisinages et conversions **O(1)** ; aucun fallback silencieux hors plage ; tests de non-régression sur les **bords du plateau**.

#### P3 — Constantes numériques

**Approche retenue : conversion au chargement (inches → sub-hex).**

Les fichiers de données (rosters, armories, `game_config.json`) conservent les valeurs en **inches** (standard GW, lisible et vérifiable). Le moteur convertit **une seule fois** au chargement via `inches_to_subhex` (paramètre dans `board_config.json`, ex. **10** pour ×10).

- **`board_config.json`** : `"inches_to_subhex": 10`
- **`game_state.py` (`create_unit`)** : `MOVE *= scale`, `weapon.RNG *= scale`
- **`w40k_core.py` (init)** : `game_rules` distances (`engagement_zone`, `charge_max_distance`, etc.) `*= scale`
- **`observation_builder.py`** : normalisations RL (`/12.0`, `/24.0`) multipliées par `scale`

Exemples avec scale=10 : MOVE 6″ → **60** sub-hex en `game_state` ; RNG 24″ → **240** ; engagement 1″ → **10**.

**Observations RL :** normaliser par **`perception_radius`** en sous-hex, pas par la taille du plateau.

#### 2.2.1 Ancrage legacy, chunks et performance

- **Vérité simulation :** `(col, row)` global micro, bornes `COLS`/`ROWS` en config.
- **Chunks :** tailles entières fixes pour la perf (`K` documenté), **indépendantes** du legacy.
- **Vue « macro »** : calque dérivé **optionnel** pour UI / migration.

### 2.3 Coordonnées globales vs hiérarchiques

**Canonique :** `(col, row)` offset odd-q, `COLS`/`ROWS` en config.

**Hiérarchique (optionnel) :** `(chunk_i, chunk_j, local_i, local_j)` — uniquement si déduit du **même module** de conversions.

L'équipe maintient les **primitives** (bornes, voisins, distance, conversions) **dans un seul module**.

### 2.4 Complément par rapport aux seuls besoins « données »

Fin de la matrice LoS/path **pleine** à l'échelle ×10 ; empreintes cohérentes par phase ; leviers RL ; budgets ; plan par phases.

### 2.5 Unité et socle (modèle cible)

- **Unité :** entité de jeu identifiée (ex. `unit_id`).
- **Socle :** **`occupied_hexes`** = ensemble des cellules occupées **à une pose donnée** (centre + forme + orientation). Recalculé quand le **centre**, la **taille** ou l'**orientation** du socle changent.
- **`base_shape` / `BASE_SHAPE` :** dans les rosters TypeScript, **`static BASE_SHAPE = "round" | "oval" | "square"`** — forme du socle pour la discrétisation sur la grille hex. La quasi-totalité des unités GW sont **rondes** (`"round"`).
- **Taille du socle (`BASE_SIZE`) :** **diamètre en hex** de la base (entier). Défini dans chaque fichier d'unité après `BASE_SHAPE` (ex. `Intercessor.ts` : `BASE_SHAPE` puis `BASE_SIZE = 13`). En ×10, cela définit l'**empreinte** `occupied_hexes` sur la micro-grille. L'icône frontend s'étend pour couvrir cette empreinte — `ICON_SCALE` n'est plus utilisé en ×10.
- **Orientation / rotation :** le socle **peut** tourner (translation + rotation) pendant le déplacement — utile pour passer dans des couloirs étroits (formes non circulaires). Cependant, **aucune règle de jeu** ne dépend de l'orientation : pas de facing, pas de bonus directionnel. Pour les socles **ronds** (symétriques), la rotation ne change pas `occupied_hexes`. Pour les **ovales** et **carrés**, la rotation modifie `occupied_hexes` mais **n'affecte que** le pathfinding (traversabilité) et le placement, **pas** les règles de tir, charge, mêlée, etc. L'**angle** de rotation est **discrétisé** en **6 orientations** (pas de 60°, paramètre `hex_orientations` dans `board_config.json`).
- **Nombre d'hex du socle :** `|occupied_hexes|` (≥ 1). Un socle d'**un seul** hex = legacy.
- **Centre `(col, row)` :** point de référence de la pose — avec **forme** + **taille** + **orientation**, on **dérive** `occupied_hexes`.

Les §3 (distances), §7 (LoS), §8 (pathfinding) et §9 (phases) s'appuient sur ce modèle.

---

## 3. Spécification canonique — distances, portées et validation

### 3.1 Alignement données (rosters, armes, unités)

**Décision unifiée :** toutes les grandeurs de règles en **sous-hex** par **×10**.

- Pas deux systèmes parallèles macro vs micro sans documentation et tests.
- **Validation des actions** : comparaisons sur des **entiers sous-hex**.

### 3.2 Tranché : moteur vs affichage

| Couche | Rôle |
|--------|------|
| **Moteur** | Comparaisons de seuil en **entiers sous-hex** issus des datas. |
| **UI** | Affichage en pouces comme **projection** dérivée — pas une seconde source de vérité. |

**Arrondis d'affichage :** explicites pour éviter des écarts fantômes.

### 3.3 Distances entre unités

- **Une seule échelle** en sous-hex.
- **Distance « plus proche paire d'hex » (normatif) :** distance hex **minimale** entre une cellule de `occupied_hexes(A)` et une de `occupied_hexes(B)`. Mesure pour portée, charge, mêlée, engagement.
- **Cas 1 hex = 1 unité (legacy) :** coïncide avec distance entre centres.
- **Pas** de matrice globale ; fonctions **`distance(a, b)`** + A*/Dijkstra en **fenêtre locale** avec **`max_expansions`** et **early exit**.

---

## 4. Macro vs micro : rôles complémentaires

| Référentiel | Rôle |
|-------------|------|
| **Macro (inch / hex 1″)** | Planification grossière, affichage, corrélation « table » ; chemin « guide » pour pathfinding hiérarchique. |
| **Micro (sous-hex)** | Collisions, LoS fine, empreintes, pathfinding effectif, validation des règles (§3). |

**Règles :**

1. Toute métrique affichée en pouces est une **vue** dérivée (§3.2).
2. LoS hiérarchique (macro puis micro, **§7.4**) : les **seuils** restent des entiers sous-hex.
3. Tests de non-régression macro ↔ micro obligatoires pour éviter **R2** (**§14**).

---

## 5. Représentation spatiale cible

### 5.1 Grille : micro canonique, macro vue optionnelle

- **Micro (canonique) :** maille **B** odd-q sur `COLS × ROWS` cellules.
- **Macro (optionnelle) :** regroupement pour UI ou migration — pas requis pour la correction des règles.

### 5.2 Obstacles et occupation

- **Sparse :** dictionnaires ou chunks pour cellules occupées / bloquantes.
- **Statique :** compression par chunk arithmétique ou régions en config.

La micro-grille sert aux **cas limites** géométriques ; l'éligibilité des actions reste celle de §3.

---

## 6. Problème : topologie dense et coût n²

### 6.1 Comportement du builder actuel

- Matrice **dense** `(from_idx, to_idx)` (LoS + pathfinding) : mémoire **n²**, temps de build **Θ(n²)**.
- Runtime : lookup O(1) si la matrice tient en RAM — ok à petit `n`, pas à l'échelle ×10.

### 6.2 Ordres de grandeur

| Niveau | Exemple | **n = cells** |
|--------|---------|---------------|
| Actuel | 25 × 21 | **525** |
| ×10 | 250 × 210 | **52 500** |
| ×4 linéaire futur | 1000 × 840 | **840 000** |

### 6.3 Mémoire matrice « toutes paires »

`n = 52 500` → **n² ≈ 2,76×10⁹** entrées (**~2,76 Go** à 1 octet). Interdit à l'échelle ×10 ; les paires pertinentes sont **localisées** → §7 et §8.

---

## 7. Ligne de vue (LoS)

### 7.1 Principe

- **Abandon** de `los_topology` dense. **Calcul à la demande** avec sémantique **§7.2**.

### 7.2 Classification et géométrie (normatif — tir)

**Contexte :** plateau 2D ; obstacles on/off par cellule ; socles pleins, convexes (§2.5).

**Rayons :** centre → centre de cellule hex.

**Échantillonnage :** hex de **bordure** du tireur et de la cible. Pour chaque paire (Hₐ bordure tireur, Hₜ bordure cible), LoS **claire** si le segment ne traverse pas d'obstacle.

**Proportion V (côté cible) :** `V = (hex de bordure cible visibles) / |bordure cible|`.

**Seuils P et C** (figés — portés dans `game_rules` : `los_visibility_min_ratio` et `cover_ratio`) :

| Symbole | Valeur | Clé `game_rules` | Rôle |
|--------|--------|-------------------|------|
| **P** | **0,05** | `los_visibility_min_ratio` | V ≤ P → **pas de LoS** |
| **C** | **0,95** | `cover_ratio` | V > C → **à découvert** |

1. **Pas de LoS** si V ≤ 0,05.
2. Sinon, **à couvert** si V ≤ 0,95.
3. Sinon, **à découvert**.

Contraintes : `0 < P < C ≤ 1`.

**Note 1 hex (legacy) :** bordure = singleton → V ∈ {0, 1} ; les seuils agissent comme filtre binaire.

#### Écart legacy

La §7.2 est la **cible normative** (socles multi-cellules). Le moteur actuel (1 hex/unité) peut diverger ; l'alignement est un chantier d'implémentation.

### 7.3 Algorithmes

1. **Supercover / grid traversal** sur le segment ; test obstacle O(1) par cellule.
2. Option **hauteur** (2,5D).
3. **LoS hiérarchique** macro → micro.
4. **Accélérateurs** : DDA, quadtree si densité extrême.

**Complexité :** O(L) par requête, L borné par la portée max.

### 7.4 LoS hiérarchique (optionnel)

Étape rapide sur grille macro pour éliminer les cas impossibles ; résultat final identique à LoS micro pure (tests obligatoires).

### 7.5 Bornes et caches

- Paires pertinentes uniquement (portée arme, perception RL).
- Cache par activation/step ; option LRU — **pas** de matrice n².
- Invalidation par version d'obstacles.

### 7.6 Murs, bordure, tir, advance

- **Murs :** en sous-hex ; migration §19.
- **Bordure :** alignement moteur après changement `cols`/`rows`.
- **Advance :** mise à jour empreintes post-déplacement ; LoS à la demande.

---

## 8. Pathfinding

### 8.1 Principe

- **BFS** ou **A\*** sur cellules marchables (sous-hex), murs + occupation.
- **Pas** de matrice `pathfinding[i, j]` globale.

### 8.2 Fenêtre de recherche

- Disque ou corridor de rayon R = min(distance estimée + marge, budget mouvement sous-hex).
- Bounding macro puis raffinement micro.

### 8.3 Hiérarchique et options avancées

1. Chemin macro pour plan grossier.
2. Raffinement dans un tube (largeur k sous-hex).
3. A* heuristique admissible ; JPS possible ; HPA* si grandes maps.

**Budgets obligatoires :** `max_open_nodes`, `max_path_length`, time budget µs par unité.

### 8.4 Occupation

- Empreintes autres unités : non traversables par défaut.
- Mise à jour obstacles **avant** recalcul de chemin.

### 8.5 Contrainte d'`engagement_zone` (§9.0)

Le pathfinding en phase de **mouvement** et d'**advance** doit **exclure** les destinations qui placeraient l'empreinte de l'unité à une distance (**§3.3**) **≤ `engagement_zone`** d'une unité ennemie (sauf exception documentée : charge, fuite). En pratique : **dilater** les positions ennemies de `engagement_zone` hex dans le graphe de recherche, ou filtrer les destinations candidates après le path.

### 8.6 Traversabilité « corps épais » et rotation

Le pathfinding pour les socles multi-hex doit intégrer **l'empreinte complète** (Invariant II §9.2) : obstacles dilatés par la forme du socle, ou test de placement de la forme à chaque nœud candidat. Pour les formes **non circulaires** (ovale, carré), l'**espace de configuration** inclut l'**orientation** (§2.5) : le socle peut **tourner** pour passer dans un corridor étroit. L'angle est discrétisé selon la symétrie de la grille (§2.5).

### 8.7 Précalcul résiduel acceptable

- Chunks (ex. 32×32 à 128×128 sous-hex) avec bords.
- Précalcul macro entre centres macro + raffinement micro.
- Navmesh entre « portes » d'obstacles.

### 8.8 Macro-actions (RL)

La policy choisit une **destination** ou action dans un pool filtré ; le moteur exécute **un** pathfinding en interne, pas un step PPO par sous-hex.

---

## 9. Empreinte au sol (socles) — par phase

### 9.0 Zone d'engagement et `game_rules` — **implémenté**

Les clés ci-dessous sont dans `config/game_config.json` → `game_rules`. Les valeurs sont en **inches** (standard GW). Le moteur les convertit automatiquement en sub-hex via `inches_to_subhex` au chargement (§P3).

| Clé | Valeur (inches) | Sub-hex (×10) | Rôle |
|-----|-----------------|---------------|------|
| **`engagement_zone`** | **1** | **10** | Distance en inches (= **1″**). Définit un **périmètre** autour de l'empreinte (`occupied_hexes`) de chaque unité. Utilisé pour : (1) **mouvement** et **advance** — interdiction d'entrer dans la zone d'engagement ennemie (sauf charge) ; (2) **fight** — une unité est **engagée** au corps à corps si elle a au moins un ennemi dont un hex d'empreinte est à distance **≤ `engagement_zone`** (converti) de son propre hex d'empreinte (**§9.8**). |
| **`charge_max_distance`** | **12** | **120** | Distance max (§3.3) pour qu'une cible soit éligible comme cible de charge. |
| **`advance_distance_range`** | **6** | **60** | Portée max du déplacement advance. |
| **`max_search_distance`** | **50** | **500** | Rayon max de recherche pathfinding / cibles. |
| **`avg_charge_roll`** | **7** | **70** | Moyenne du jet de charge. |

**Note :** `melee_range` n'est plus une constante séparée — l'engagement au corps à corps est régi par **`engagement_zone`** (même seuil).

**Mouvement :** interdire les poses / chemins qui placeraient l'empreinte de l'unité dans la zone d'engagement d'un ennemi (§8.5).

**Advance (phase de tir) :** même interdiction que le mouvement. Budget max = `advance_distance_range` (60 sous-hex).

**Charge :** cibles à **≤ `charge_max_distance`** sous-hex (§3.3). Charge **réussie** lorsque l'unité termine dans la **zone d'engagement** de la cible (= distance min entre empreintes **≤ `engagement_zone`**).

**Fight :** unités **engagées** au corps à corps = celles qui ont au moins un ennemi **dans leur zone d'engagement** (§9.8).

### 9.1 Représentation

- **`(col, row)`** centre ; **`base_shape`** ; **orientation** (angle discret) ; **`occupied_hexes`** : `set` recalculé — source de vérité collision/occupation.
- **Index inverse :** `cell_micro → unit_id`.
- Recalcul : création, fin de mouvement (translation ou rotation), changement de taille.

**`units_cache` et empreinte**  
Chaque entrée `units_cache[unit_id]` contient `col`, `row`, `occupied_hexes` (ou `base_shape` + params + orientation avec fonction pure `occupied_hexes = f(centre, forme, orientation, params)`). L'index inverse se met à jour quand `occupied_hexes` change. Cohérence : `units_cache` reste la source position/vivant ; pas d'écriture `HP_CUR` hors pipeline.

### 9.2 Invariants normatifs (empreintes multi-cellules)

**Invariant I — Budget de déplacement par cellule du socle**  
Aucune cellule du socle ne doit parcourir une distance **supérieure** au budget de la phase (MOVE, advance, charge en sous-hex). Le socle se déplace comme un **corps rigide** : **translation + rotation** (§2.5). Le pathfinding opère dans l'**espace des configurations** (position du centre + orientation discrétisée) avec borne de coût, ou sous-approximation documentée si la spec l'autorise.

**Invariant II — Largeur minimale et passages**  
Le socle doit **passer** partout sur le chemin : obstacles dilatés par l'empreinte, ou test de placement complet. Pour les formes non circulaires, la **rotation** (§2.5) est un degré de liberté du pathfinding : un socle peut tourner pour emprunter un corridor étroit.

**Invariant III — Pas de chevauchement entre empreintes**  
`occupied_hexes(U) ∩ occupied_hexes(V) = ∅` pour toute paire d'unités vivantes distinctes (sauf règle spéciale).

### 9.3 Mouvement

- **Invariants I, II, III** ; chevauchement interdit ; path ne traverse pas les autres empreintes.
- **`engagement_zone`** (**§9.0**, **§8.5**) : interdiction d'entrer dans le périmètre de 10 hex autour d'un ennemi.

### 9.4 Tir (incl. advance)

- LoS : **§7.2** (seuils P/C) ; portée : **§3.3**.
- **Advance :** recalcul `occupied_hexes` post-déplacement ; Invariants I et III ; même interdiction `engagement_zone` que le mouvement ; budget max = `advance_distance_range` (§9.0).

### 9.5 Charge

- Éligibilité cibles : distance (§3.3) **≤ `charge_max_distance`** (§9.0). Invariant I sur le segment résolu.
- **Succès :** fin du mouvement avec distance min entre empreintes **≤ `engagement_zone`** (= dans la zone d'engagement de la cible).
- Traversabilité : Invariant II, dilatation morphologique locale.

### 9.6 Performance (cible par requête)

- O(taille empreinte) + O(L) LoS + O(n_local log n_local) A* fenêtré.
- Invalidation ciblée par chunks ; single source of truth `game_state`.

### 9.7 Implémentation future (moteur)

1. **Données :** `base_shape` + `occupied_hexes` dérivé du centre + orientation.
2. **Occupation globale :** `cell → unit_id` sparse.
3. **Validation destination :** `occupied_hexes_candidate` ; retirer U de la carte ; Invariant III.
4. **Invariant I :** planification dans l'espace des configurations (position + orientation) avec borne de coût.
5. **Invariant II :** obstacles dilatés par forme + rotation du socle.
6. **Phases :** mêmes `occupied_hexes` pour move, advance, charge.

### 9.8 Fight (mêlée) — zone d'engagement

- **Norme Board ×10 :** une unité est **engagée au corps à corps** avec une ennemie lorsque la distance minimale (§3.3) entre `occupied_hexes(A)` et `occupied_hexes(B)` est **≤ `engagement_zone`** (10 sous-hex, §9.0). C'est un **périmètre de 10 hex** autour de chaque socle — **pas** seulement l'adjacence directe (distance ≤ 1).
- **Legacy :** tant que le moteur est en 1 hex/unité avec adjacence ≤ 1, se référer à AI_TURN.md.
- **Perf :** tests O(taille empreinte) par paire de candidats si bornés par pools.

---

## 10. RL / PPO / Stable-Baselines3

### 10.1 Risques

- Horizon explosif si un pas = un micro-pas partout.
- Pas de tenseur dense `COLS×ROWS×C`.
- Pas « chaque sous-hex = action ».

### 10.2 Leviers

| Levier | Idée | Compromis |
|--------|------|-----------|
| **Action hiérarchique** | Destination macro/waypoint ; moteur exécute le chemin | Moins de contrôle fin |
| **Observations multi-échelle** | Carte macro + patch micro + vecteurs k plus proches | Moins de symétrie |
| **Frame skip** | Plusieurs micro-pas sans obs intermédiaire | Partial observability |
| **Curriculum** | Macro ou ×2/×5 puis ×10 | Effort pipeline |
| **Reward shaping** | Jalons macro | Reward hacking si mal calibré |
| **Masques (MaskablePPO)** | O(|A_réduit|) | Moins d'exploration brute |
| **Parallèle d'envs** | Si coût/step maîtrisé | Infra |
| **Horizon PPO** | `n_steps` aligné rythme tactique | Délicat si reward mixte |

### 10.3 SB3 / MaskablePPO

- Actions logiques **bornées** et stables. Masque O(1) ou O(k) — **jamais O(n)**.
- Goulot souvent `env.step` (LoS, path).

### 10.4 Modèles existants

Checkpoints **non** compatibles après changement d'échelle — nouveaux entraînements.

### 10.5 Métriques

| Métrique | Objectif |
|----------|----------|
| **SPS** | ≥ baseline après optimisations |
| **Steps par épisode** | Pas d'explosion vs baseline |
| **`env.step` p95** | Sous plafond sur scénario ×10 |
| **RAM** | Pas de structure Ω(n²) globale |
| **Obs size** | Stable ordre de grandeur |
| **Actions/logits** | Stable |
| **GPU vs CPU bound** | SB3 souvent CPU-bound si env lourd |

### 10.6 Limiter la perte de perf

1. **Actions de haut niveau** — pas un step PPO par micro-pas (§8.8).
2. **Observations bornées** — k plus proches, patch local, agrégats.
3. **Normalisation** par `perception_radius` fixe, pas par `cols × rows`.
4. **Caches** `occupied_hexes` dans `units_cache` (§9.1).
5. **Budgets** explicites pathfinding et LoS (§7, §8).
6. **Curriculum** : petites cartes d'abord.
7. **Parallélisation** : augmenter `n_envs`.
8. **Frame skip** si le produit le permet.
9. **Validation** : profiler régulièrement `env.step`.

### 10.7 Observations RL : spec vs code

**Invariants normatifs :**

| Invariant | Rôle |
|-----------|------|
| **Taille bornée** | Pas de O(n_cells) ; pas de tenseur COLS×ROWS×C |
| **Localité** | k plus proches, patch, agrégats |
| **Normalisation** | Échelles fixes (`perception_radius`, bornes d'armes) |
| **Masques** | Cardinalité O(k), pas O(n) |

**Table d'observation** (dans AI_OBSERVATION.md) : index → sens → plage → norme. Tests golden obligatoires.

### 10.8 GPU vs environnement Python

Si `env.step` domine le temps, GPU ne change rien. Matrice d'options :

| Ordre | Option | Efficacité | Difficulté |
|-------|--------|-----------|------------|
| 1 | Algorithmes + caches + budgets | Élevée | Faible |
| 2 | Plusieurs envs en parallèle | Élevée | Faible–Moyenne |
| 3 | Curriculum | Moyenne | Faible |
| 4 | JIT/Numba/Cython sur noyaux chauds | Moyenne–Élevée | Moyenne |
| 5 | Vectorisation NumPy | Variable | Moyenne |
| 6 | GPU plus large (si réseau = goulot) | Élevée | Faible |
| 7 | Pipelining CPU/GPU | Moyenne | Élevée |
| 8 | Noyau C++/Rust | Très élevée | Très élevée |
| 9 | Envs distribués | Élevée (agrégé) | Très élevée |

Enchaîner **1 → 2** avant 4–5 ; **6** si profiler montre forward dominant ; **8–9** en dernier.

### 10.9 Perte de performance : peut-on chiffrer ?

**Non** sans mesure. Estimation informelle : SPS par env divisé par **~2–4** si `env.step` double — compensable par `n_envs` + budgets (§7, §8). Méthode : baseline SPS vs cible SPS, même machine.

---

## 11. Extension plateau (~×4 linéaire futur)

Mêmes interdits : pas de matrice globale ; LoS/path bornés ; représentation compacte ; curriculum possible.

---

## 12. Hex ×10 vs espace continu

| Critère | Hex ×10 | Continu |
|--------|---------|---------|
| Moteur | Raster, LoS grille, A* | Polygones, SAT/GJK |
| Règles GW | Mapping pouces ↔ macro naturel | Tolérances float |
| Perf | Prévisible si chunké + budgets | Variable |
| RL | Masques + macro-actions | Souvent plus lourd |
| Migration | Incrémentale | Refonte forte |

**Verdict :** ×10 hiérarchisé = meilleur effort/contrôle/RL pour l'existant.

---

## 13. Plan de migration (phases A–F)

### Phase A — Cadrage

- [x] Convention géométrique §2.2 (P1–P3, **B** figé, **odd-q**, plat à plat 0,1″).
- [x] Unité canonique simulation : `(col, row)` global micro.
- [x] Paramètres perf figés dans `board_config.json` : `chunk_size` = 64, `hex_orientations` = 6, `pathfinding.max_open_nodes` = 2 000, `pathfinding.time_budget_us` = 5 000.
- [ ] Périmètre décisions vue macro vs micro (produit + RL).
- [x] Inventaire structures O(n²) — **terminé** : 2 matrices n×n (`los`, `pathfinding`) dans `.npz`, 1 builder (`scripts/los_topology_builder.py`), 4 fichiers runtime (`w40k_core.py`, `combat_utils.py`, `observation_builder.py`, `shooting_handlers.py`). Stratégie : remplacer par LoS à la demande (§7) + A* fenêtré (§8).

### Phase B — Moteur géométrique

- [x] **Module `engine/hex_utils.py`** créé — primitives hex odd-q : voisins, conversions offset↔cube, distance, hex line (grid traversal), LoS à la demande, BFS borné, wall set helper, empreintes (`compute_occupied_hexes`, `_footprint_round/oval/square`), occupation (`build_occupation_map`, `validate_placement`). 80 tests (`tests/unit/engine/test_hex_utils.py`).
- [x] **LoS à la demande** — `_get_los_visibility_state` (shooting_handlers), `_has_los_from_topology` (observation_builder) : fallback sur `hex_utils` quand `los_topology` absent. Diagnostic adapté.
- [x] **Pathfinding BFS borné** — `calculate_pathfinding_distance` (combat_utils) : fallback sur `hex_utils.pathfinding_distance` avec budgets (`max_open_nodes`, `max_search_distance`) quand `pathfinding_topology` absent.
- [x] **Chargement .npz optionnel** — `_load_topology_cached` (w40k_core) : log info au lieu de crash si .npz absent (mode Board ×10). Invalidation `_wall_set_cache` au reset.
- [ ] Chunks + coordonnées locales si besoin (optionnel — non bloquant pour Phase C).

### Phase C — Règles et socles

- [x] **Empreintes + occupation (socles ronds)** — `build_occupied_positions_set`, `compute_candidate_footprint`, `is_footprint_placement_valid` dans `shared_utils.py`. BFS mouvement/charge/advance vérifie l'empreinte complète à chaque position candidate. Commit-time checks footprint-aware. Flee detection via `min_distance_between_sets` entre empreintes. Dead code supprimé (`_is_valid_destination`, `_is_traversable_hex` remplacés).
- [x] **`engagement_zone` intégrée dans move/advance/charge/fight** — Toutes les fonctions d'adjacence/engagement utilisent `min_distance_between_sets(unit_fp, enemy_fp) <= engagement_zone` : `_is_adjacent_to_enemy_within_cc_range` (fight, shooting), `_is_adjacent_to_enemy_for_fight` (generic), `_is_adjacent_to_enemy` / `_is_adjacent_to_enemy_simple` (charge), target validation (PISTOL/friendly engagement), advance commit-time check, weapon range checks. Dead code supprimé (`_calculate_hex_distance_for_fight`).
- [x] **Déploiement / placement initial avec validation d'empreinte** — `game_state.py` : `used_hexes` stocke les empreintes complètes ; random deployment filtre les positions candidates par `_is_footprint_deployable` ; fixed deployment valide chaque cellule de l'empreinte (zone, murs, overlap). `deployment_handlers.py` : `execute_deployment_action` utilise `compute_candidate_footprint` + `build_occupied_positions_set` pour valider l'empreinte entière avant placement.

### Phase D — IA / RL

- [x] **Espace d'actions + masques** — Action space fixe (13 slots, stratégies + target slots), indépendant de la taille du plateau. Masque (13 bools) indépendant de la grille. Aucune modification nécessaire pour ×10.
- [x] **Observations** — Vecteur 355 floats stable. Normalisations MOVE/RNG déjà scalées par `inches_to_subhex`. `perception_radius` scalé au chargement dans `w40k_core`.
- [x] **Perf BFS : FLY** — Remplacé scan `O(cols×rows)` par BFS borné `O(reachable)` dans `movement_handlers.py` (éligibilité + pool builder). FLY ignore murs/occupation pour la traversée, valide la destination normalement.
- [x] **Perf BFS : deque** — Tous les BFS mouvement/charge utilisent `collections.deque` pour `O(1) popleft` au lieu de `list.pop(0)` `O(n)`.
- [x] **Dead code** — Import mort `_is_traversable_hex` supprimé de `shooting_handlers.py`.
- [ ] Profiler `env.step` sur board 360×312 ; seuils §10.5 (à faire en conditions réelles d'entraînement).

### Phase E — Outils et données

- [x] ~~Adapter `los_topology_builder`~~ — **supprimé** (builder incompatible ×10, remplacé par `hex_utils.py`).
- [ ] CI : maps références + golden LoS/path.
- [x] Replay : `BASE_SHAPE`, `BASE_SIZE`, `orientation` ajoutés dans `game_replay_logger.py` (3 chemins) et `step_logger.py`. Reconstruction `occupied_hexes` possible côté frontend via ces données.
- [x] Analyzer : `compute_occupied_hexes` et `min_distance_between_sets` disponibles dans `hex_utils.py` / `shared_utils.py`.

### Phase F — Rollout

- [x] Feature flag = `inches_to_subhex` dans `board_config.json` (valeur 10 pour ×10, 1 pour legacy). Le moteur scale dynamiquement.
- [x] Migration : `scenario_pvp_test.json` migré (360×312). Scénarios legacy restent sur board 25×21.

---

## 14. Risques, hypothèses, critères de succès

**Risques**

- **R1 —** LoS + path + RL sans budgets → lenteur.
- **R2 —** Double interprétation macro/micro.
- **R3 —** Régressions sans golden tests.
- **R4 —** Dette double système (dense + sparse en parallèle).
- **R5 —** Dégradation SPS masquée par parallélisme : surveiller `env.step` p95.

**Hypothèses**

- Portées et interactions bornées → fenêtres locales.
- PPO avec actions de haut niveau.
- Obstacles majoritairement statiques.
- Taille d'empreinte bornée par le design.

**Critères de succès**

- Pas de structure Ω(n²) globale.
- `env.step` p95 < seuil.
- Cardinalité actions et taille obs stables ordre de grandeur vs baseline.

---

## 15. Checklist d'implémentation + outils debug

- [ ] Remplacer topo denses par calculs bornés + caches locaux.
- [ ] Unifier distances, LoS, path en sous-hex (§3).
- [ ] `occupied_hexes` + occupation + rotation : mouvement, tir, charge, fight (§9).
- [ ] `engagement_zone` dans move, advance, charge, fight (§9.0, §8.5).
- [ ] Contrat RL : macro-actions, obs bornées, normalisations (§10).
- [ ] Configs murs / board ×10 (§19).
- [ ] Tests : murs, bord, occupation, perf §10.5.

**Outils debug :** visualisation double grille, overlay LoS, heatmaps de coût local.

---

## 16. Références internes

- [`.cursorrules`](../../.cursorrules)
- ~~`scripts/los_topology_builder.py`~~ — **supprimé** (remplacé par `engine/hex_utils.py`).
- `engine/w40k_core.py`, `engine/observation_builder.py`
- `Documentation/LOS_TOPOLOGY.md`
- `Documentation/AI_TURN.md`, `Documentation/AI_IMPLEMENTATION.md`, `Documentation/AI_OBSERVATION.md`, `Documentation/AI_TRAINING.md`

---

## 17. Notes finales

- Détails mêlée, LoS bloquée par unités : alignés AI_TURN.md.
- Archives `Boardx10-11` … `Boardx10-33` : contenu fusionné ici, ne pas maintenir en parallèle.

---

## 18. Replays, logs et analyzer (cible ×10)

### 18.1 Replays : hex central dans les logs, empreinte recalculée

- Logs portent le **hex central** `(col, row)` + **orientation** (si non circulaire) par unité.
- Paramètres de socle (`base_shape`, taille) viennent du roster — inchangés pendant la partie.
- Le replay/analyzer recalcule `occupied_hexes = f(centre, forme, orientation, params)` avec la même fonction que le moteur.
- Versionnement : changement de discrétisation = bump de version replay.

### 18.2 Analyzer : tests d'intersection

1. **Chevauchement unité/unité :** `occupied_hexes(U) ∩ occupied_hexes(V) = ∅`.
2. **Chevauchement unité/décor :** hex de `occupied_hexes(U)` doit être marchable.

### 18.3 Structures en runtime

Murs (statique) + `occupied_hexes(U)` par unité + carte inverse `cellule → unit_id`. Chevauchement : **O(|occupied_hexes|)** par validation (§9.1, §9.2).

---

## 19. Annexe — Checklist chemins fichiers (migration ×10)

Liste **indicative** de fichiers impactés.

### Configuration
- [x] `config/game_config.json` — **fait** : clés §9.0 en **inches** (`engagement_zone: 1`, `charge_max_distance: 12`, `advance_distance_range: 6`, `avg_charge_roll: 7`, `max_search_distance: 50`). Conversion sub-hex au chargement via `inches_to_subhex`.
- [x] `config/board/250x210/board_config.json` — **créé** : `cols`/`rows`, `chunk_size`, `hex_orientations`, `pathfinding.*`.
- [x] `config/board/360x312/board_config.json` — **créé** : idem + `inches_to_subhex: 10`, `hex_radius: 1.7`, background image.
- [ ] `config/board_config_Objectives.json`
- [ ] `config/board_config_big.json`
- [x] `frontend/public/config/board_config.json` — **fait** : synchronisé avec 360×312, ajout `inches_to_subhex: 10` + display avancé.
- [x] `config/agents/CoreAgent/CoreAgent_training_config.json` — **fait** : `perception_radius: 25` (inches), converti automatiquement au chargement via `inches_to_subhex`.

### Unités et armes (frontend)
- [x] `frontend/src/roster/**/*.ts` — valeurs en **inches** (standard GW). Conversion ×`inches_to_subhex` dans `game_state.py` (`create_unit`).
- [x] `frontend/src/roster/**/armory.ts` — idem, `RNG` en inches. Conversion au chargement.

### Code Python — migration O(n²) → calculs bornés (Phase B)
- [x] `scripts/los_topology_builder.py` — **supprimé** : matrices denses n×n impossibles à l'échelle ×10 (n²=12,6G pour 360×312). Remplacé par LoS on-demand et BFS borné via `hex_utils.py`. `build_topology.sh` et référence Dockerfile supprimés.
- [x] `engine/w40k_core.py` — chargement .npz **optionnel** ; log info si absent ; invalidation `_wall_set_cache` au reset ; **conversion `game_rules` inches→sub-hex** via `inches_to_subhex` ; stocke `inches_to_subhex` dans `game_state`.
- [x] `engine/combat_utils.py` — fallback sur `hex_utils.pathfinding_distance` (BFS borné) quand `pathfinding_topology` absent.
- [x] `engine/observation_builder.py` — fallback sur `hex_utils.compute_los_visibility` quand `los_topology` absent. **Normalisations RL** (`MOVE`, `RNG`, positions relatives) mises à l'échelle via `inches_to_subhex`. **Hardcoded `+12`** charge remplacé par `charge_max_distance` config.
- [x] `engine/phase_handlers/shooting_handlers.py` — fallback sur `hex_utils.compute_los_state` quand `los_topology` absent.
- [x] **`engine/hex_utils.py`** (nouveau) — module unique de primitives hex odd-q + LoS à la demande + BFS borné.

### Code Python — conversion inches→sub-hex (Phase B)
- [x] `engine/game_state.py` — `create_unit` : `MOVE *= scale`, `weapon.RNG *= scale` via `_get_inches_to_subhex()`.
- [x] `engine/phase_handlers/charge_handlers.py` — remplacé hardcoded `12`/`13` par `charge_max_distance` + `melee_range` depuis config.
- [x] `engine/action_decoder.py` — remplacé hardcoded `+12` par `charge_max_distance` config.
- [ ] `engine/utils/weapon_helpers.py`

### Logs et replays
- [ ] `ai/step_logger.py`
- [ ] `ai/game_replay_logger.py`
- [ ] `ai/replay_converter.py`
- [ ] `frontend/src/utils/replayParser.ts`
- [ ] `services/replay_parser.py`

### Frontend plateau
- [ ] `frontend/src/components/BoardDisplay.tsx`
- [ ] `frontend/src/components/BoardPvp.tsx`
- [ ] `frontend/src/types/game.ts`
- [ ] `frontend/src/data/UnitFactory.ts`

### Frontend UX — Drag & drop placement (implémenté)

Rendu PIXI.js (canvas WebGL). **Mode clic + preview** (select unit → hover hex → click pour confirmer).

- [x] **Ghost unit** : cercle semi-transparent + ID suivant le curseur, snappé au hex le plus proche (`pointermove` sur canvas).
- [x] **Footprint visible** : empreinte complète du socle (overlay hex polygones vert/rouge selon validité). Port TS de `compute_occupied_hexes` (round) dans `frontend/src/utils/hexFootprint.ts`.
- [x] **Pré-validation visuelle** : footprint **vert** si toutes les cellules sont valides (pas de mur, pas occupé, dans les bornes, dans le pool de déploiement). Footprint **rouge** sinon.
- [x] **Highlight objectif** : si `candidate_footprint ∩ objective_hexes ≠ ∅`, highlight jaune pulsant des hexes de l'objectif.
- [x] **Drop = commit** : clic gauche (pointerup) pour confirmer → appel `onDeployUnit` existant. Le backend reste l'autorité de validation.
- [x] **Hook** : `useDragPlacement` dans `frontend/src/hooks/useDragPlacement.ts` — input: `selectedUnit`, `mouseHex`, `gameState`, `boardConfig`, `objectives` ; output: PIXI overlay + `onDrop(col, row)`.
- [x] **Utilitaires** : `hexFootprint.ts` — `computeOccupiedHexes`, `pixelToHex`, `hexToPixel`, `buildOccupiedSet`, `getContestedObjectives`, etc.

### Scénarios
- [ ] `config/agents/*/scenarios/*.json`
- [ ] `config/scenario_game.json`
- [x] `frontend/public/config/scenario.json` — fichier legacy non référencé, peut être supprimé.

---

*Micro-grille **B** odd-q, **plat à plat = 0,1″**, `COLS × ROWS` configurables. Socles multi-cellules avec rotation (§2.5). Zone d'engagement **10** sous-hex (§9.0). **Une seule** spec ×10 : **ce fichier**.*
