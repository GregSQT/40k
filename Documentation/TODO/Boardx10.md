# Board x10 - Migration vers granularité 10x

## Vue d'ensemble

Ce document décrit la migration du système de jeu vers une granularité 10x plus fine. Chaque hexagone existant est divisé en 10×10 sous-hexagones, permettant une représentation plus précise des unités et des distances.

**Date de création :** 2025-01-21  
**Version :** 1.0

---

## 1. Objectif et principe

### Objectif principal
Multiplier la granularité du plateau par 10 sans changer la taille physique du plateau. Chaque hexagone existant devient 10×10 sous-hexagones.

### Principe
- **Plateau actuel :** 25×21 = 525 hexagones
- **Nouveau plateau :** 250×210 = 52,500 hexagones
- **Distances :** Toutes multipliées par 10
  - MOVE: 6 → 60
  - RNG (armes): 24 → 240, 12 → 120
  - Charge max: 12 → 120
  - Melee range: 1 → 10

### Exemples de conversion
- Unité avec socle 1 inch → disque de 10 hexagones de diamètre
- Unité avec socle 1.5 inch → disque de 15 hexagones de diamètre
- Arme avec portée 24 → portée 240 hexagones

---

## 2. Système de position des unités

### Problématique
Avec la granularité x10, une unité occupe maintenant plusieurs hexagones au lieu d'un seul. Il faut un système pour représenter cette occupation et gérer les collisions efficacement.

### Solution retenue : Hybride avec support multi-formes

**Format de position :** `(col, row, base_shape, shape_params)` + `occupied_hexes` (set)

- `col, row` : Coordonnées de l'hexagone central de l'unité
- `base_shape` : Forme du socle (`"circle"`, `"oval"`, `"square"`, `"custom"`)
- `shape_params` : Paramètres selon la forme (voir ci-dessous)
- `occupied_hexes` : Set de tuples `{(col, row), ...}` précalculé pour collisions rapides

**Pourquoi cette solution hybride ?**

1. **Format compact pour logs/replays** : `(col, row, shape, params)` au lieu de liste complète
2. **Collisions rapides** : `occupied_hexes` pour vérifications O(1)
3. **Flexible** : Supporte cercles, ovales, carrés et formes personnalisées
4. **Rétrocompatible** : Cercles peuvent utiliser `radius` comme raccourci

### Formes de socles supportées

#### 1. Cercle (le plus commun)
```python
{
    "base_shape": "circle",
    "radius": 5  # Rayon en hexagones
}
```

#### 2. Ovale
```python
{
    "base_shape": "oval",
    "radius_x": 7,  # Rayon horizontal (en hexagones)
    "radius_y": 5   # Rayon vertical (en hexagones)
}
```

#### 3. Carré/Rectangle
```python
{
    "base_shape": "square",
    "width": 10,   # Largeur en hexagones
    "height": 10   # Hauteur en hexagones
}
```

#### 4. Forme personnalisée
```python
{
    "base_shape": "custom",
    "occupied_hexes": {(0,0), (1,0), (0,1), ...}  # Liste relative au centre
}
```

### Calcul des hex occupés

```python
def get_occupied_hexes(center_col, center_row, base_shape, shape_params):
    """Retourne tous les hexagones occupés selon la forme."""
    occupied = set()
    
    if base_shape == "circle":
        radius = shape_params["radius"]
        for col in range(center_col - radius, center_col + radius + 1):
            for row in range(center_row - radius, center_row + radius + 1):
                distance = calculate_hex_distance(center_col, center_row, col, row)
                if distance <= radius:
                    occupied.add((col, row))
    
    elif base_shape == "oval":
        radius_x = shape_params["radius_x"]
        radius_y = shape_params["radius_y"]
        for col in range(center_col - radius_x, center_col + radius_x + 1):
            for row in range(center_row - radius_y, center_row + radius_y + 1):
                # Distance elliptique (approximation hexagonale)
                dx = (col - center_col) / radius_x
                dy = (row - center_row) / radius_y
                if dx*dx + dy*dy <= 1.0:
                    occupied.add((col, row))
    
    elif base_shape == "square":
        width = shape_params["width"]
        height = shape_params["height"]
        half_w = width // 2
        half_h = height // 2
        for col in range(center_col - half_w, center_col + half_w + 1):
            for row in range(center_row - half_h, center_row + half_h + 1):
                occupied.add((col, row))
    
    elif base_shape == "custom":
        # Forme personnalisée : hex relatifs au centre
        for rel_col, rel_row in shape_params["occupied_hexes"]:
            occupied.add((center_col + rel_col, center_row + rel_row))
    
    return occupied
```

### Raccourci pour cercles (rétrocompatibilité)

Pour simplifier les cercles (cas le plus commun), on peut utiliser un raccourci :
```python
# Format court (cercles uniquement)
unit = {
    "col": 140,
    "row": 140,
    "radius": 5  # Implique base_shape="circle"
}

# Format complet (toutes formes)
unit = {
    "col": 140,
    "row": 140,
    "base_shape": "oval",
    "radius_x": 7,
    "radius_y": 5
}
```

### Gestion des collisions

**Avec `occupied_hexes` précalculé :**

```python
# Vérification collision entre deux unités = intersection de sets
def check_collision(unit1, unit2):
    return bool(unit1["occupied_hexes"] & unit2["occupied_hexes"])  # O(min(n1, n2))

# Vérification si un hex est occupé = lookup O(1)
occupied_all = set()
for unit in game_state["units"]:
    if unit["HP_CUR"] > 0:
        occupied_all |= unit["occupied_hexes"]

if (hex_col, hex_row) in occupied_all:  # O(1)
    return True
```

**Performance :**
- ✅ Vérification occupation : **O(1)** au lieu de O(n) par hex
- ✅ Détection collision : **O(min(n1, n2))** au lieu de calcul de distance
- ✅ Compatible avec code existant qui utilise déjà `occupied_positions` comme set

### Avantages de cette solution

1. **Logs compacts** : `(col, row, radius)` au lieu de liste complète
2. **Collisions rapides** : Set d'hex pour vérifications O(1)
3. **Naturel** : Correspond aux socles ronds de W40K
4. **Efficace** : Calculé une fois, mis à jour quand l'unité bouge
5. **Compatible** : S'intègre avec le système existant (`occupied_positions`)

### Alternatives considérées

| Solution | Avantages | Inconvénients | Statut |
|----------|----------|---------------|--------|
| **Hybride multi-formes** | Logs compacts + collisions rapides + flexible | Légèrement plus de mémoire | ✅ **Retenu** |
| Hex central + rayon uniquement | Très compact | Collisions O(n) par hex, cercles uniquement | ❌ Rejeté |
| Liste d'hex uniquement | Collisions rapides, formes arbitraires | Logs lourds | ❌ Rejeté |
| Hex central + forme_id simple | Simple | Pas assez flexible pour ovales/carrés | ❌ Rejeté |

### Implémentation

**Nouveau format dans les logs :**

**Cercles (format court) :**
```
Unit 1 (Intercessor) P0: Starting position (140, 140, 5)
```

**Autres formes (format complet) :**
```
Unit 2 (Tank) P0: Starting position (140, 140, oval, 7x5)
Unit 3 (Vehicle) P0: Starting position (140, 140, square, 10x10)
```

**Nouveau format dans les replays JSON :**

**Cercles (format court) :**
```json
{
  "col": 140,
  "row": 140,
  "radius": 5
}
```

**Autres formes (format complet) :**
```json
{
  "col": 140,
  "row": 140,
  "base_shape": "oval",
  "radius_x": 7,
  "radius_y": 5
}
```

**Nouveau format dans game_state :**
```python
# Cercles (format court - rétrocompatible)
unit = {
    "col": 140,
    "row": 140,
    "radius": 5,  # Raccourci pour base_shape="circle"
    "occupied_hexes": {(140, 140), (141, 140), ...},  # Calculé automatiquement
    # ... autres champs
}

# Autres formes (format complet)
unit = {
    "col": 140,
    "row": 140,
    "base_shape": "oval",
    "radius_x": 7,
    "radius_y": 5,
    "occupied_hexes": {(140, 140), (141, 140), ...},  # Calculé automatiquement
    # ... autres champs
}
```

**Mise à jour lors du mouvement :**
```python
def update_unit_position(unit, new_col, new_row):
    """Met à jour la position et recalcule occupied_hexes."""
    unit["col"] = new_col
    unit["row"] = new_row
    
    # Détecter la forme (rétrocompatibilité avec radius)
    if "radius" in unit:
        base_shape = "circle"
        shape_params = {"radius": unit["radius"]}
    else:
        base_shape = unit.get("base_shape", "circle")
        shape_params = {k: v for k, v in unit.items() 
                       if k in ["radius_x", "radius_y", "width", "height", "occupied_hexes"]}
    
    unit["occupied_hexes"] = get_occupied_hexes(new_col, new_row, base_shape, shape_params)
```

---

## 3. Modifications des distances

### Multiplications requises

| Élément | Ancien | Nouveau | Fichiers concernés |
|---------|--------|---------|-------------------|
| **MOVE** | 6 | 60 | Tous les fichiers d'unités `.ts` (~57 fichiers) |
| **RNG (armes)** | 24 → 240<br>12 → 120<br>6 → 60 | Multiplié par 10 | Tous les `armory.ts` (~5 fichiers) |
| **Charge max** | 12 | 120 | `charge_handlers.py` |
| **Melee range** | 1 | 10 | `weapon_helpers.py`, `charge_handlers.py` |
| **Perception radius** | 25 | 250 | `training_config.json` |
| **Max search distance** | 50 | 500 | `combat_utils.py` |

### Fichiers à modifier

#### Unités (MOVE)
- `frontend/src/roster/**/*.ts` (~57 fichiers)
- Exemple : `Intercessor.ts` : `MOVE = 6` → `MOVE = 60`

#### Armes (RNG)
- `frontend/src/roster/spaceMarine/armory.ts`
- `frontend/src/roster/tyranid/armory.ts`
- Tous les fichiers `armory.ts`
- Exemple : `RNG: 24` → `RNG: 240`

#### Code Python
- `engine/phase_handlers/charge_handlers.py` : `CHARGE_MAX_DISTANCE = 12` → `120`
- `engine/combat_utils.py` : `max_search_distance = 50` → `500`
- `engine/utils/weapon_helpers.py` : `get_melee_range()` → retourne `10`

---

## 4. Configuration du plateau

### Modifications dans `board_config.json`

**Ancien :**
```json
{
  "cols": 25,
  "rows": 21,
  "wall_hexes": [[2,5], [2,6], ...]
}
```

**Nouveau :**
```json
{
  "cols": 250,
  "rows": 210,
  "wall_hexes": [[20,50], [20,60], ...]  // Tous ×10
}
```

### Fichiers de configuration à modifier

1. `config/board_config.json`
2. `config/board_config_Objectives.json`
3. `config/board_config_big.json`
4. `frontend/public/config/board_config.json`

**Action :** Multiplier toutes les coordonnées par 10

---

## 5. Centralisation des constantes

### État actuel de `game_config.json`

```json
{
  "game_rules": {
    "charge_max_distance": 13,
    "advance_distance_range": 6
  }
}
```

### Valeurs hardcodées à centraliser

| Valeur | Fichier actuel | Action |
|--------|----------------|--------|
| `CHARGE_MAX_DISTANCE = 12` | `charge_handlers.py` | → `game_config.json` |
| `TARGET_MAX_DISTANCE = 13` | `charge_handlers.py` | → `game_config.json` |
| `max_search_distance = 50` | `combat_utils.py` | → `game_config.json` |
| `MOVE + 12` (charge safety) | Plusieurs fichiers | → Calculé depuis config |

### Nouveau `game_config.json`

```json
{
  "game_rules": {
    "max_turns": 5,
    "turn_limit_penalty": -1,
    "charge_max_distance": 130,           // 13 → 130 (×10)
    "charge_max_roll": 120,               // 12 → 120 (nouveau)
    "advance_distance_range": 60,         // 6 → 60 (×10)
    "max_search_distance": 500,            // 50 → 500 (nouveau)
    "melee_range": 10                     // 1 → 10 (nouveau)
  }
}
```

### Code à modifier

1. **`charge_handlers.py`**
   ```python
   # Avant
   CHARGE_MAX_DISTANCE = 12
   
   # Après
   charge_max_roll = game_config["game_rules"]["charge_max_roll"]
   ```

2. **`combat_utils.py`**
   ```python
   # Avant
   max_search_distance: int = 50
   
   # Après
   max_search_distance = game_config["game_rules"]["max_search_distance"]
   ```

3. **`weapon_helpers.py`**
   ```python
   def get_melee_range():
       return game_config["game_rules"]["melee_range"]
   ```

---

## 6. Scénarios

### Migration des positions

Tous les scénarios doivent avoir leurs positions multipliées par 10.

**Exemple :**
```json
// Avant
{
  "id": 1,
  "col": 14,
  "row": 14
}

// Après
{
  "id": 1,
  "col": 140,
  "row": 140,
  "radius": 5  // Nouveau champ
}
```

### Fichiers concernés

- Tous les fichiers dans `config/agents/*/scenarios/*.json`
- `config/scenario_game.json`
- `frontend/public/config/scenario.json`

**Action :** Script de migration automatique (à créer)

---

## 7. Logs et replays

### Nouveau format de logs

**Ancien format :**
```
[timestamp] Unit 1 (Intercessor) P0: Starting position (14, 14)
```

**Nouveau format :**
```
[timestamp] Unit 1 (Intercessor) P0: Starting position (140, 140, 5)
```

### Nouveau format de replay JSON

**Ancien :**
```json
{
  "col": 14,
  "row": 14
}
```

**Nouveau :**
```json
{
  "col": 140,
  "row": 140,
  "radius": 5
}
```

### Stratégie de migration

**Décision :** Pas de migration des anciens logs/replays. Seuls les nouveaux logs utiliseront le format x10.

**Raison :** 
- Simplifie l'implémentation
- Évite les erreurs de conversion
- Les anciens logs restent lisibles pour référence historique

### Formats de logs concernés

1. **`train_step.log`** (texte ligne par ligne)
   - Format : `[timestamp] T{turn} P{player} PHASE : Unit {id}({col}, {row}, {radius}) ACTION ...`

2. **Replay JSON** (format structuré)
   - `replay_converter.py` → JSON avec `initial_state.units[].col/row/radius`
   - `game_replay_logger.py` → JSON avec `combat_log` et positions

3. **Game states** (snapshots)
   - Positions d'unités dans les snapshots avec `radius`

### Fichiers à modifier

- `ai/step_logger.py` : Format des messages de log
- `ai/game_replay_logger.py` : Structure JSON des replays
- `ai/replay_converter.py` : Conversion steplog → replay
- `frontend/src/utils/replayParser.ts` : Parsing des logs
- `services/replay_parser.py` : Parsing Python

---

## 8. Modèles entraînés

### Impact

Les modèles PPO/DQN existants ne sont **pas compatibles** avec le nouveau système.

**Raisons :**
1. Les observations changent (distances normalisées différentes)
2. Les actions changent (distances de mouvement différentes)
3. La sémantique des features change

### Stratégie

**Décision :** Nouveaux modèles uniquement. Les anciens modèles ne seront pas utilisés.

**Action :** 
- Sauvegarder les anciens modèles dans un dossier `models/legacy/`
- Entraîner de nouveaux modèles avec le système x10
- Mettre à jour `training_config.json` avec `perception_radius: 250`

---

## 9. Frontend - Optimisations PIXI.js

### Problématique

52,500 hexagones à rendre = performance critique.

### Solution : Optimisations PIXI (Option 2)

#### 1. Culling (Viewport)
Ne rendre que les hexagones visibles dans le viewport.

```typescript
function isHexVisible(col: number, row: number, viewport: Viewport): boolean {
  const centerX = col * HEX_HORIZ_SPACING + HEX_WIDTH / 2;
  const centerY = row * HEX_VERT_SPACING + ((col % 2) * HEX_VERT_SPACING / 2);
  
  return viewport.contains(centerX, centerY, HEX_RADIUS);
}
```

#### 2. Batching
Regrouper les hexagones de même couleur en sprites.

```typescript
// Créer un sprite batch pour chaque couleur
const baseHexContainer = new PIXI.Container();
const batches = new Map<string, PIXI.Graphics>();

for (let col = 0; col < BOARD_COLS; col++) {
  for (let row = 0; row < BOARD_ROWS; row++) {
    if (!isHexVisible(col, row, viewport)) continue;
    
    const color = getHexColor(col, row);
    if (!batches.has(color)) {
      batches.set(color, new PIXI.Graphics());
    }
    const batch = batches.get(color);
    // Ajouter hex au batch
  }
}
```

#### 3. LOD (Level of Detail)
Réduire le détail des hexagones hors zoom.

#### 4. Pooling
Réutiliser les objets Graphics au lieu de les créer/détruire.

### Implémentation

**Fichiers à modifier :**
- `frontend/src/components/BoardDisplay.tsx` : Ajouter culling et batching
- `frontend/src/components/BoardPvp.tsx` : Optimiser le rendu

**Alternative PIXI :** Rester sur PIXI.js avec optimisations (recommandé)

---

## 10. Tests et validations

### Tests à effectuer

#### 1. Calculs de distance
- [ ] Hex distance : `calculate_hex_distance()` avec valeurs ×10
- [ ] Pathfinding : `calculate_pathfinding_distance()` avec `max_search_distance = 500`
- [ ] Charge distance : Vérifier que charge de 120 fonctionne

#### 2. Line of Sight (LoS)
- [ ] LoS entre unités avec positions (col, row, radius)
- [ ] LoS avec murs à nouvelles positions

#### 3. Mouvement et actions
- [ ] Mouvement de 60 hexagones
- [ ] Tir avec portée 240
- [ ] Charge avec distance 120
- [ ] Combat en mêlée (range 10)

#### 4. Observations AI
- [ ] `perception_radius = 250` fonctionne
- [ ] Normalisations correctes (distances / 250)
- [ ] Features d'observation cohérentes

#### 5. Frontend
- [ ] Rendu de 250×210 hexagones performant
- [ ] Culling fonctionne
- [ ] Interactions (hover, click) correctes
- [ ] Affichage des unités avec radius

#### 6. Logs et replays
- [ ] Format `(col, row, radius)` dans `train_step.log`
- [ ] Replay JSON avec nouvelles positions
- [ ] Parsing des logs fonctionne

### Scripts de validation

**À créer :**
- `check/validate_x10_migration.py` : Validation complète
- `check/test_distances_x10.py` : Tests de distances
- `check/test_positions_x10.py` : Tests de positions avec radius

---

## 11. Plan d'implémentation

### Phase 1 : Préparation
1. ✅ Centraliser les constantes dans `game_config.json`
2. ✅ Documenter les changements (ce document)
3. ⏳ Créer scripts de migration des scénarios

### Phase 2 : Modifications des distances
1. ⏳ Multiplier MOVE dans tous les fichiers d'unités (×10)
2. ⏳ Multiplier RNG dans tous les fichiers d'armes (×10)
3. ⏳ Modifier `charge_handlers.py` (charge max = 120)
4. ⏳ Modifier `combat_utils.py` (max_search_distance = 500)
5. ⏳ Modifier `weapon_helpers.py` (melee_range = 10)

### Phase 3 : Configuration et scénarios
1. ⏳ Modifier `board_config.json` (250×210, murs ×10)
2. ⏳ Migrer tous les scénarios (positions ×10 + radius)
3. ⏳ Modifier `training_config.json` (perception_radius = 250)

### Phase 4 : Système de position
1. ⏳ Ajouter champ `radius` dans `Unit` interface (TypeScript)
2. ⏳ Ajouter champ `radius` dans `create_unit()` (Python)
3. ⏳ Implémenter `get_occupied_hexes()` fonction
4. ⏳ Ajouter champ `occupied_hexes` (set) dans `Unit` et `game_state`
5. ⏳ Calculer `occupied_hexes` lors de la création/mouvement d'unité
6. ⏳ Modifier occupation checks (utiliser `occupied_hexes` set au lieu de calcul)
7. ⏳ Modifier collision checks (intersection de sets)

### Phase 5 : Logs et replays
1. ⏳ Modifier `step_logger.py` (format avec radius)
2. ⏳ Modifier `game_replay_logger.py` (JSON avec radius)
3. ⏳ Modifier `replayParser.ts` (parsing avec radius)
4. ⏳ Modifier `replay_parser.py` (parsing Python)

### Phase 6 : Frontend
1. ⏳ Optimisations PIXI (culling, batching)
2. ⏳ Affichage des unités avec radius (cercle)
3. ⏳ Interactions avec unités multi-hex

### Phase 7 : Tests
1. ⏳ Tests de distance
2. ⏳ Tests de position/occupation
3. ⏳ Tests de LoS
4. ⏳ Tests d'observations AI
5. ⏳ Tests frontend (performance)

---

## 12. Fichiers à modifier (checklist)

### Configuration
- [ ] `config/game_config.json` (constantes centralisées)
- [ ] `config/board_config.json` (250×210, murs ×10)
- [ ] `config/board_config_Objectives.json`
- [ ] `config/board_config_big.json`
- [ ] `frontend/public/config/board_config.json`
- [ ] `config/agents/*/training_config.json` (perception_radius = 250)

### Unités et armes
- [ ] `frontend/src/roster/**/*.ts` (~57 fichiers, MOVE ×10)
- [ ] `frontend/src/roster/**/armory.ts` (~5 fichiers, RNG ×10)

### Code Python
- [ ] `engine/phase_handlers/charge_handlers.py`
- [ ] `engine/combat_utils.py`
- [ ] `engine/utils/weapon_helpers.py`
- [ ] `engine/game_state.py` (ajouter radius)
- [ ] `engine/observation_builder.py` (normalisations)

### Logs et replays
- [ ] `ai/step_logger.py`
- [ ] `ai/game_replay_logger.py`
- [ ] `ai/replay_converter.py`
- [ ] `frontend/src/utils/replayParser.ts`
- [ ] `services/replay_parser.py`

### Frontend
- [ ] `frontend/src/components/BoardDisplay.tsx` (optimisations)
- [ ] `frontend/src/components/BoardPvp.tsx` (optimisations)
- [ ] `frontend/src/types/game.ts` (ajouter radius)
- [ ] `frontend/src/data/UnitFactory.ts` (radius)

### Scénarios
- [ ] Tous les fichiers `config/agents/*/scenarios/*.json`
- [ ] `config/scenario_game.json`
- [ ] `frontend/public/config/scenario.json`

---

## 13. Risques et mitigations

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| Performance frontend | Élevé | Moyen | Culling + batching PIXI |
| Erreurs de migration scénarios | Élevé | Faible | Script de migration + validation |
| Incompatibilité modèles | Moyen | Certain | Nouveaux modèles uniquement |
| Bugs dans occupation checks | Élevé | Moyen | Tests exhaustifs |
| Parsing logs cassé | Moyen | Faible | Tests de parsing |

---

## 14. Notes techniques

### Calcul de distance avec radius

Quand une unité a un radius > 0, la distance entre deux unités est calculée entre leurs centres, puis on soustrait les radius pour obtenir la distance réelle.

```python
def calculate_unit_distance(unit1, unit2):
    """Distance entre deux unités (centres - radius)."""
    center_dist = calculate_hex_distance(
        unit1["col"], unit1["row"],
        unit2["col"], unit2["row"]
    )
    radius1 = unit1.get("radius", 0)
    radius2 = unit2.get("radius", 0)
    return max(0, center_dist - radius1 - radius2)
```

### Occupation checks

Vérifier si un hex est occupé (avec `occupied_hexes` précalculé) :
```python
def is_hex_occupied(hex_col, hex_row, units):
    """Vérifie si un hex est occupé par une unité - O(1) avec set."""
    # Précalculer une fois au début de la phase
    occupied_all = set()
    for unit in units:
        if unit["HP_CUR"] > 0:
            occupied_all |= unit.get("occupied_hexes", set())
    
    # Vérification O(1)
    return (hex_col, hex_row) in occupied_all

# Alternative : vérification directe sans précalcul
def is_hex_occupied_direct(hex_col, hex_row, units):
    """Vérifie si un hex est occupé - itère sur les unités."""
    for unit in units:
        if unit["HP_CUR"] <= 0:
            continue
        if (hex_col, hex_row) in unit.get("occupied_hexes", set()):
            return True
    return False
```

### Détection de collision entre unités

```python
def check_collision(unit1, unit2):
    """Vérifie si deux unités entrent en collision - O(min(n1, n2))."""
    if unit1["HP_CUR"] <= 0 or unit2["HP_CUR"] <= 0:
        return False
    
    occupied1 = unit1.get("occupied_hexes", set())
    occupied2 = unit2.get("occupied_hexes", set())
    
    # Intersection de sets = collision
    return bool(occupied1 & occupied2)
```

### Normalisations dans observations

Les normalisations doivent utiliser les nouvelles valeurs :
- Distance / `perception_radius` (250 au lieu de 25)
- Position relative / `perception_radius * 2` (500 au lieu de 50)

---

## 15. Conclusion

Cette migration vers la granularité x10 apporte :
- ✅ Plus de précision dans les mouvements et positions
- ✅ Meilleure représentation des tailles de socles
- ✅ Gameplay plus fin et agréable

**Prochaines étapes :**
1. Valider ce document
2. Commencer Phase 1 (centralisation constantes)
3. Implémenter phase par phase avec tests à chaque étape

---

**Document créé le :** 2025-01-21  
**Dernière mise à jour :** 2025-01-21  
**Auteur :** AI Assistant + User

