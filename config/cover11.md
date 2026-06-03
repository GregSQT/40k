# Plan d'implémentation — Système Cover / LoS / Hidden

## État actuel

- LoS basée sur `wall_hexes` (murs denses) + `visibility_ratio` (seuil `cover_ratio` = 0.95)
- Cover = `can_see=true` ET `visibility_ratio < cover_ratio`
- Les terrains polygon (obscuring) sont chargés depuis `terrain_ref` mais ne participent PAS au calcul LoS
- Les unités ont `UNIT_KEYWORDS: [{keywordId: "infantry"}, ...]` mais pas d'attribut `hideable` ni `hidden`
- Pas de tracking du tir au tour précédent

---

## Règles cibles (résumé)

| Concept | Règle |
|---|---|
| `hideable` | `true` si keyword `infantry`, `beast` ou `swarm` |
| `hidden` | `hideable=true` + dans terrain `obscuring` + pas tiré ce tour-ci ni le précédent |
| Cibler hidden | Impossible si tous les modèles du tireur sont à > `detection_range` (15") |
| LoS bloquée | TOUTES les lignes traversent un terrain `obscuring` (hors terrain occupé) ou mur `dense` |
| LoS partielle | Certaines lignes traversent un obscuring/dense → cover |
| Cover condition 1 | `hideable=true` ET dans un terrain (quelconque) |
| Cover condition 2 | Pas entièrement visible (LoS partiellement gênée) |
| Effet cover | -1 BS au tireur |

---

## Étapes d'implémentation

### Étape 1 — Charger les terrain areas dans game_state
**Fichier :** `engine/game_state.py`

Les terrain areas polygon sont déjà lus depuis `terrain_ref`, mais stockés uniquement pour les murs.
Ajouter `game_state["terrain_areas"]` : liste de dicts `{id, obscuring, polygon_vertices}` issus du JSON terrain.

---

### Étape 2 — Calcul terrain membership (utilitaire)
**Nouveau fichier :** `engine/terrain_utils.py`

Fonctions :
- `point_in_polygon(px, py, vertices) -> bool` — algorithme ray-casting
- `unit_in_terrain_area(unit, terrain_area) -> bool` — true si au moins un hex du footprint est dans le polygon
- `get_terrain_areas_for_unit(unit, terrain_areas) -> list[str]` — IDs des terrains contenant l'unité
- `unit_in_obscuring_terrain(unit, terrain_areas) -> bool` — true si dans au moins un terrain `obscuring=true`

Note sur les espaces de coordonnées (vérifié) :
- Les vertices terrain (`[[25,30]...]`) sont en **col/row space** (0–220 × 0–300), identique aux positions hex des unités → `point_in_polygon` utilisable directement sans conversion.
- Pour le calcul LoS (intersection rayon × polygon terrain), le code existant travaille en pixel-space via `_hex_to_pixel(col, row, hex_radius=21.0)`. Les vertices terrain devront être convertis avec la même fonction pour les checks LoS.

---

### Étape 3 — Attribut `hideable` à l'init des unités
**Fichier :** `engine/game_state.py`

À la création de chaque unité dans le game_state, calculer :
```
unit["hideable"] = any(kw["keywordId"] in ("infantry", "beast", "swarm") for kw in unit["UNIT_KEYWORDS"])
```
Initialiser également `unit["hidden"] = False`.

---

### Étape 4 — Tracking "a tiré au tour précédent"
**Fichiers :** `engine/phase_handlers/shooting_handlers.py` + `engine/phase_handlers/generic_handlers.py`

Mécanisme :
- Après qu'une unité tire : `unit["_shot_this_turn"] = True`
- En début de tour (turn start) : copier `_shot_this_turn` → `_shot_previous_turn`, puis reset `_shot_this_turn = False`
- `_unit_has_shot_with_any_weapon()` déjà existant — vérifier si on peut le réutiliser ou s'il faut le compléter

---

### Étape 5 — Calcul `hidden` en début de phase de tir
**Fichier :** `engine/phase_handlers/shooting_handlers.py`

Fonction `compute_hidden_status(unit, terrain_areas) -> bool` :
```
hideable=true
ET unit_in_obscuring_terrain(unit, terrain_areas)
ET NOT unit["_shot_this_turn"]
ET NOT unit["_shot_previous_turn"]
```
Appelée pour chaque unité ennemie au début du build du pool de cibles valides.

---

### Étape 6 — Filtre hidden dans valid_targets
**Fichier :** `engine/phase_handlers/shooting_handlers.py`

Lors du calcul des cibles valides pour un tireur :
- Si `target["hidden"] = True` : vérifier que la distance entre l'un des modèles du tireur et n'importe quelle partie du footprint cible est ≤ `detection_range` (15")
- Si toutes les distances sont > `detection_range` → exclure la cible du pool

---

### Étape 7 — Rework LoS : ajouter les terrains obscuring comme bloqueurs
**Fichier :** `engine/phase_handlers/shooting_handlers.py` + `engine/hex_utils.py`

Actuellement LoS = bloquée par `wall_hexes` (murs denses uniquement).

Nouveau comportement :
- Construire `obscuring_polygons` = liste des polygones des terrains `obscuring=true`
- Une ligne de vue est bloquée si elle traverse un polygon obscuring (ET ni le tireur ni la cible ne sont dans ce terrain)
- Résultat par ligne : `CLEAR`, `OBSCURED_BY_TERRAIN`, `BLOCKED_BY_WALL`

LoS finale entre deux modèles :
- `BLOCKED` = TOUTES les lignes sont bloquées (wall dense OU obscuring terrain)
- `PARTIAL` = au moins une ligne bloquée, pas toutes
- `CLEAR` = aucune ligne bloquée

Adapter `_get_los_visibility_state()` et `compute_los_visibility()` pour retourner ce nouvel état 3-valeurs.

---

### Étape 8 — Rework cover : nouvelles conditions
**Fichier :** `engine/phase_handlers/shooting_handlers.py`

Fonction `unit_has_cover(shooter, target, los_state, terrain_areas) -> bool` :

Pour chaque modèle de `target`, vérifier qu'il remplit au moins une condition :
1. `target["hideable"] = True` ET `unit_in_terrain_area(target, any_terrain)`
2. `los_state == PARTIAL` (pas entièrement visible)

Si TOUS les modèles remplissent au moins une condition → cover = True.

Remplace l'ancienne logique `visibility_ratio < cover_ratio`.

Supprimer `cover_ratio` de `game_config.json` et toutes ses références dans le code.

---

### Étape 9 — Appliquer l'effet cover (-1 BS)
**Fichier :** `engine/phase_handlers/shooting_handlers.py`

Lors du calcul des jets pour toucher :
- Si `cover = True` ET l'arme n'a pas la règle `IGNORES_COVER` → `effective_BS = weapon_BS + 1`

La règle `_weapon_has_ignores_cover_rule()` existe déjà (ligne 258). Conserver.

---

### Étape 10 — Frontend : mise à jour affichage
**Fichiers :** `frontend/src/utils/losPreviewHelpers.ts`, composants UI concernés

- Afficher les unités hidden avec un indicateur visuel
- Mettre à jour la légende cover (nouveau calcul)
- Afficher le rayon de détection autour des unités hidden si pertinent pour l'UX

---

## Ordre d'exécution recommandé

```
1 → 2 → 3 → 4 → 5 → 6    (hidden pipeline, backend)
        ↓
        7 → 8 → 9           (LoS/cover rework, backend)
                ↓
               10            (frontend)
```

Étapes 1-6 et 7-9 peuvent avancer en parallèle une fois l'étape 2 (terrain_utils) terminée.

---

## Points de vigilance

- **Coordonnées** (vérifié) : vertices terrain ET positions col/row des unités sont dans le **même espace sub-hex `0–220 × 0–300`** (board 44×60 pouces × `inches_to_subhex=5`). Donc `point_in_polygon(unit_col, unit_row, vertices)` utilisable **directement, sans conversion** (étape 2). Pour la LoS (étape 7), le code convertit tout en pixel-space via `_hex_to_pixel(col, row, hex_radius=21.0)` — valeur **codée en dur** dans `shooting_handlers.py:3748`, PAS le `2.78` du board_config ; convertir les vertices terrain avec la même fonction/valeur pour rester cohérent.
- **Cache LoS** : le `hex_los_cache` et `_wall_set_cache` existants devront être invalidés ou étendus pour inclure les obscuring areas.
- **Rétrocompatibilité observation** : `los_cover_cache` sur les unités est utilisé par l'IA — la sémantique change (cover = bool basé sur nouvelles conditions). Vérifier l'impact sur `observation_builder.py`.
- **Perf** : le point-in-polygon sur les footprints de toutes les unités à chaque phase de tir peut être coûteux. Mettre en cache `_terrain_area_ids` sur l'unité, invalidé à chaque déplacement.
