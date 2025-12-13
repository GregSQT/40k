# Audit Complet - Implémentation Armes Multiples

**Date:** 2025-01-XX  
**Audits analysés:** MULTIPLE_WEAPONS_AUDIT_11.md, MULTIPLE_WEAPONS_AUDIT_12.md, MULTIPLE_WEAPONS_AUDIT_13.md  
**Approche:** Expert, honnête, code simple et évolutif

---

## 🎯 ÉVALUATION GLOBALE

### ✅ Toutes les observations sont PERTINENTES

Les 3 audits convergent sur **les mêmes problèmes critiques**. C'est un excellent signe: les problèmes sont réels et bien identifiés.

**Convergence des audits:**
- ✅ 10 problèmes critiques identifiés par les 3 audits
- ✅ Solutions proposées similaires (avec quelques variations)
- ✅ Approche "simple et évolutif" validée par tous

**Convergence à 100%:**
1. ✅ Fonction `calculate_kill_probability` manquante
2. ✅ Observation size hardcodé (300 → 313)
3. ✅ Base indices incorrects
4. ✅ Enemy Units feature count (23 → 22)
5. ✅ Active Unit Capabilities structure incohérente
6. ✅ Regex parsing fragile
7. ✅ Détection faction fragile
8. ✅ Accès directs aux anciens champs
9. ✅ Structure de répertoires manquante
10. ✅ Required properties obsolètes

---

## 📊 COMPARAISON DES 3 AUDITS

### Points Communs (100% accord)

Tous les audits identifient les mêmes 10 problèmes critiques avec des solutions convergentes.

### Différences (Variations de solutions)

| Problème | AUDIT_11 | AUDIT_12 | AUDIT_13 | Solution Optimale |
|----------|----------|----------|----------|-------------------|
| **Cache structure** | Simple avec `hp_cur` | Simple sans `hp_cur` | Simple avec `hp_cur` | **Simple avec `hp_cur`** (limitation acceptée) |
| **Tie-breaking** | Index le plus bas | Index le plus bas | Index le plus bas | **Index le plus bas** ✅ |
| **Timing sélection** | Une fois par cible | Une fois par cible | Une fois par cible | **Une fois par cible** ✅ |
| **Regex amélioré** | Support guillemets simples/doubles | Support guillemets simples/doubles | Support guillemets simples/doubles | **Support guillemets simples/doubles** ✅ |

**Conclusion:** Les solutions convergent vers la même approche simple. ✅

---

## 🔴 PROBLÈMES CRITIQUES - SOLUTIONS OPTIMALES FINALES

### 1. **Fonction `calculate_kill_probability` Manquante - CRITIQUE**

**Convergence:** Les 3 audits identifient ce problème comme CRITIQUE.

**Solution OPTIMALE (Simple et Standalone):**
```python
# engine/ai/weapon_selector.py
def calculate_kill_probability(unit: Dict[str, Any], weapon: Dict[str, Any], 
                                target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """
    Calculate kill probability for a specific weapon against a target.
    Simple, standalone function - pas de dépendance complexe.
    """
    # Extraire stats de l'arme
    hit_target = weapon.get("ATK", 3)
    strength = weapon.get("STR", 4)
    damage = weapon.get("DMG", 1)
    num_attacks = weapon.get("NB", 1)
    ap = weapon.get("AP", 0)
    
    # Calculs W40K standard
    p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
    
    # Wound probability
    if "T" not in target:
        return 0.0
    toughness = target["T"]
    if strength >= toughness * 2:
        p_wound = 5/6
    elif strength > toughness:
        p_wound = 4/6
    elif strength == toughness:
        p_wound = 3/6
    else:
        p_wound = 2/6
    
    # Save probability
    armor_save = target.get("ARMOR_SAVE", 3)
    invul_save = target.get("INVUL_SAVE", 7)
    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
    
    # Expected damage
    p_damage_per_attack = p_hit * p_wound * p_fail_save
    expected_damage = num_attacks * p_damage_per_attack * damage
    
    # Kill probability
    hp_cur = target.get("HP_CUR", 1)
    if expected_damage >= hp_cur:
        return 1.0
    else:
        return min(1.0, expected_damage / hp_cur)
```

**Pourquoi cette solution:**
- ✅ Simple et standalone (pas de wrapper complexe)
- ✅ Facile à tester
- ✅ Réutilisable partout
- ✅ Pas de dépendance sur RewardCalculator ou ObservationBuilder

---

### 2. **Observation Size Hardcodé (300 → 313) - CRITIQUE**

**Convergence:** Les 3 audits identifient 5+ fichiers à modifier.

**Solution OPTIMALE:**
```markdown
### ✅ Fichiers à modifier (LISTE COMPLÈTE)
- [ ] `engine/observation_builder.py` ligne 602: `obs = np.zeros(300, ...)` → `obs = np.zeros(self.obs_size, ...)`
- [ ] `engine/observation_builder.py` `__init__()`: `self.obs_size = obs_params.get("obs_size", 313)`
- [ ] `engine/w40k_core.py` ligne 291: `obs_size = 300` → `obs_size = obs_params.get("obs_size", 313)`
- [ ] `check/test_observation.py`: `assert obs.shape == (300,)` → `(313,)`
- [ ] `services/api_server.py`: `"obs_size": 300` → `313`
- [ ] Tous les `training_config.json`: `"obs_size": 300` → `313`
- [ ] **Vérification:** `grep -r "obs_size.*300\|300.*obs"` pour trouver tous
```

---

### 3. **Base Indices Incorrects - CRITIQUE**

**Convergence:** Les 3 audits identifient les mêmes valeurs à corriger.

**Solution OPTIMALE:**
```markdown
### ✅ `engine/observation_builder.py` - Corrections base_idx
- [ ] **CRITIQUE:** Mettre à jour tous les `base_idx`:
  - [ ] Directional Terrain: `base_idx=37` (au lieu de 23) - dans `_encode_directional_terrain()`
  - [ ] Allied Units: `base_idx=69` (au lieu de 55) - dans `_encode_allied_units()`
  - [ ] Enemy Units: `base_idx=141` (au lieu de 127) - dans `_encode_enemy_units()`
  - [ ] Valid Targets: `base_idx=273` (au lieu de 265) - dans `_encode_valid_targets()`
```

**Vérification:**
- Global Context: [0:15] = 15
- Active Unit Capabilities: [15:37] = 22
- Directional Terrain: [37:69] = 32
- Allied Units: [69:141] = 72
- Enemy Units: [141:273] = 132
- Valid Targets: [273:313] = 40
- **Total: 313 ✅**

---

### 4. **Enemy Units Feature Count (23 → 22) - CRITIQUE**

**Convergence:** Les 3 audits identifient features 17 et 19 à supprimer.

**Solution OPTIMALE:**
```markdown
### ✅ `engine/observation_builder.py` - Enemy Units [141:273]
- [ ] **Ligne 968:** Changer `feature_base = base_idx + i * 23` → `i * 22`
- [ ] **Ligne 1038:** Changer `for j in range(23):` → `range(22)`
- [ ] **Supprimer ligne 1020:** Feature 17 (`can_be_meleed`)
- [ ] **Supprimer ligne 1028:** Feature 19 (`is_in_range`)
- [ ] **Réindexer toutes les features suivantes:**
  - Feature 12 (`danger_to_me`) → Feature 13
  - Features 13-15 (Allied coordination) → Features 14-16
  - Feature 15 (`can_melee_units_charge_target`) → Feature 17
  - Feature 16 (`target_type_match`) → Feature 18
  - Feature 18 (`is_adjacent`) → Feature 19
  - Features 20-22 (Enemy capabilities) → Features 20-21
- [ ] **Ajouter features 11-12:** `best_weapon_index` et `best_kill_probability`
```

---

### 5. **Active Unit Capabilities Structure - CRITIQUE**

**Convergence:** Les 3 audits identifient l'incohérence (double assignation).

**Solution OPTIMALE (Structure Exacte):**
```markdown
#### Active Unit Capabilities [15:37] - 22 floats
- [ ] `obs[15]` = MOVE / 12.0
- [ ] `obs[16]` = RNG_WEAPONS[0]["RNG"] / 24.0 ou 0.0 si manquant
- [ ] `obs[17]` = RNG_WEAPONS[0]["DMG"] / 5.0 ou 0.0 si manquant
- [ ] `obs[18]` = RNG_WEAPONS[0]["NB"] / 10.0 ou 0.0 si manquant
- [ ] `obs[19]` = RNG_WEAPONS[1]["RNG"] / 24.0 ou 0.0 si manquant
- [ ] `obs[20]` = RNG_WEAPONS[1]["DMG"] / 5.0 ou 0.0 si manquant
- [ ] `obs[21]` = RNG_WEAPONS[1]["NB"] / 10.0 ou 0.0 si manquant
- [ ] `obs[22]` = RNG_WEAPONS[2]["RNG"] / 24.0 ou 0.0 si manquant
- [ ] `obs[23]` = RNG_WEAPONS[2]["DMG"] / 5.0 ou 0.0 si manquant
- [ ] `obs[24]` = RNG_WEAPONS[2]["NB"] / 10.0 ou 0.0 si manquant
- [ ] `obs[25]` = CC_WEAPONS[0]["NB"] / 10.0 ou 0.0 si manquant
- [ ] `obs[26]` = CC_WEAPONS[0]["ATK"] / 6.0 ou 0.0 si manquant
- [ ] `obs[27]` = CC_WEAPONS[0]["STR"] / 10.0 ou 0.0 si manquant
- [ ] `obs[28]` = CC_WEAPONS[0]["AP"] / 6.0 ou 0.0 si manquant
- [ ] `obs[29]` = CC_WEAPONS[0]["DMG"] / 5.0 ou 0.0 si manquant
- [ ] `obs[30]` = CC_WEAPONS[1]["NB"] / 10.0 ou 0.0 si manquant
- [ ] `obs[31]` = CC_WEAPONS[1]["ATK"] / 6.0 ou 0.0 si manquant
- [ ] `obs[32]` = CC_WEAPONS[1]["STR"] / 10.0 ou 0.0 si manquant
- [ ] `obs[33]` = CC_WEAPONS[1]["AP"] / 6.0 ou 0.0 si manquant
- [ ] `obs[34]` = CC_WEAPONS[1]["DMG"] / 5.0 ou 0.0 si manquant
- [ ] `obs[35]` = T / 10.0
- [ ] `obs[36]` = ARMOR_SAVE / 6.0
- **Vérification:** 1 + 3×3 + 2×5 + 2 = 22 floats ✅
```

---

### 6. **Regex Parsing Fragile - CRITIQUE**

**Convergence:** Les 3 audits proposent la même amélioration.

**Solution OPTIMALE:**
```python
# Regex amélioré - robuste mais simple
rng_codes_match = re.search(
    r'static\s+RNG_WEAPON_CODES\s*=\s*\[([^\]]*)\];',
    content,
    re.MULTILINE | re.DOTALL  # Support multi-lignes
)
if rng_codes_match:
    codes_str = rng_codes_match.group(1).strip()
    if codes_str:
        # Gérer guillemets simples ET doubles
        codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
    else:
        codes = []  # Array vide
    
    # Détection faction robuste
    if faction_path.startswith('spaceMarine/'):
        unit_stats["RNG_WEAPONS"] = get_sm_weapons(codes)
    elif faction_path.startswith('tyranid/'):
        unit_stats["RNG_WEAPONS"] = get_ty_weapons(codes)
    else:
        raise ValueError(f"Unknown faction in path: {faction_path}")
```

---

### 7. **Détection Faction Fragile - CRITIQUE**

**Convergence:** Les 3 audits proposent `startswith()`.

**Solution OPTIMALE:**
```python
# Détection faction robuste
if faction_path.startswith('spaceMarine/'):
    faction = 'spaceMarine'
elif faction_path.startswith('tyranid/'):
    faction = 'tyranid'
else:
    raise ValueError(f"Unknown faction in path: {faction_path}")
```

---

### 8. **Structure de Répertoires Manquante - CRITIQUE**

**Convergence:** Les 3 audits identifient ce problème.

**Solution OPTIMALE:**
```markdown
### ✅ PHASE 0: PRÉREQUIS (AVANT TOUT)
- [ ] Créer `engine/roster/` si n'existe pas
- [ ] Créer `engine/roster/spaceMarine/` avec `__init__.py`
- [ ] Créer `engine/roster/tyranid/` avec `__init__.py`
- **CRITIQUE:** Sans ces répertoires, les imports Python échoueront
```

---

### 9. **Cache Structure - Décision Finale**

**Divergence:** AUDIT_12 propose sans `hp_cur`, AUDIT_11 et 13 avec `hp_cur`.

**Solution OPTIMALE (Pragmatique):**
```python
# Structure simple avec hp_cur (limitation acceptée pour MVP)
kill_probability_cache: Dict[Tuple[str, int, str, int], float] = {}
# Clé: (unit_id, weapon_index, target_id, hp_cur)
```

**Raisonnement:**
- ✅ Simple à implémenter
- ✅ Correct fonctionnellement
- ✅ Performance acceptable pour MVP
- ⚠️ Cache invalidé si HP change (limitation acceptée)
- 💡 Optimisation future possible: utiliser `hp_ratio` avec granularité

**À documenter:**
```markdown
- [ ] **Note performance:** Cache invalidé si HP change (limitation acceptée pour MVP)
- [ ] **Optimisation future possible:** Utiliser hp_ratio avec granularité (0.0, 0.25, 0.5, 0.75, 1.0)
```

---

### 10. **Tie-Breaking et Timing - Décision Finale**

**Convergence:** Les 3 audits proposent la même solution.

**Solution OPTIMALE:**
```markdown
**Tie-breaking weapon selection:**
- Si égalité de `kill_probability`, retourner index le plus bas (première arme)
- Comportement déterministe et simple

**Timing sélection arme:**
- Agent choisit cible (action RL)
- → Arme sélectionnée UNE FOIS pour cette cible au début de l'activation
- → Toutes les attaques de cette activation utilisent la même arme
- Si la cible change de HP pendant l'activation, l'arme reste la même (acceptable)
```

---

## 📋 SYNTHÈSE DES MISES À JOUR POUR MULTIPLE_WEAPONS_IMPLEMENTATION.md

### Section 0: PRÉAMBULE (À AJOUTER)

**Insérer au début du document, après "Vue d'ensemble":**

```markdown
## ⚠️ PRÉREQUIS CRITIQUES AVANT IMPLÉMENTATION

### PHASE 0: PRÉPARATION (À FAIRE EN PREMIER)

#### 1. Structure de Répertoires - CRITIQUE
- [ ] Créer `engine/roster/` si n'existe pas
- [ ] Créer `engine/roster/spaceMarine/` avec `__init__.py`
- [ ] Créer `engine/roster/tyranid/` avec `__init__.py`
- **CRITIQUE:** Sans ces répertoires, les imports Python échoueront avec `ModuleNotFoundError`

#### 2. Observation Size - Mise à Jour Globale - CRITIQUE
- [ ] `engine/observation_builder.py` ligne 602: `obs = np.zeros(300, ...)` → `obs = np.zeros(self.obs_size, ...)`
- [ ] `engine/observation_builder.py` `__init__()`: Ajouter `self.obs_size = obs_params.get("obs_size", 313)`
- [ ] `engine/w40k_core.py` ligne 291: `obs_size = 300` → `obs_size = obs_params.get("obs_size", 313)`
- [ ] `check/test_observation.py`: `assert obs.shape == (300,)` → `(313,)`
- [ ] `services/api_server.py`: `"obs_size": 300` → `313`
- [ ] Tous les `training_config.json`: `"obs_size": 300` → `313`
- [ ] **Vérification:** `grep -r "obs_size.*300\|300.*obs"` pour trouver tous

#### 3. Base Indices - Correction Immédiate - CRITIQUE
- [ ] `engine/observation_builder.py` - `_encode_directional_terrain()`: `base_idx=37` (au lieu de 23)
- [ ] `engine/observation_builder.py` - `_encode_allied_units()`: `base_idx=69` (au lieu de 55)
- [ ] `engine/observation_builder.py` - `_encode_enemy_units()`: `base_idx=141` (au lieu de 127)
- [ ] `engine/observation_builder.py` - `_encode_valid_targets()`: `base_idx=273` (au lieu de 265)
- **CRITIQUE:** Doit être fait AVANT toute modification de structure

#### 4. Enemy Units Feature Count - CRITIQUE
- [ ] `engine/observation_builder.py` ligne 968: `i * 23` → `i * 22`
- [ ] `engine/observation_builder.py` ligne 1038: `range(23)` → `range(22)`
- [ ] Supprimer feature 17 (`can_be_meleed`) - ligne 1020
- [ ] Supprimer feature 19 (`is_in_range`) - ligne 1028
- [ ] Réindexer toutes les features suivantes (voir détails section 8)
```

---

### Section 7: SÉLECTION D'ARME PAR IA (À CORRIGER)

**Remplacer la section existante par:**

```markdown
## 7. SÉLECTION D'ARME PAR IA

### ✅ `engine/ai/weapon_selector.py` (NOUVEAU)

#### Fonction `calculate_kill_probability` - CRITIQUE
- [ ] **CRITIQUE:** Créer fonction standalone `calculate_kill_probability(unit, weapon, target, game_state) -> float`
  - Code complet fourni ci-dessus (section 1)
  - Fonction simple, pas de dépendance complexe

#### Fonctions de Sélection
- [ ] `select_best_ranged_weapon(unit, target, game_state) -> int`:
  - [ ] Calcule `kill_probability` pour chaque arme (utilise cache si disponible)
  - [ ] **Tie-breaking:** Si égalité, retourner index le plus bas (première arme)
  - [ ] Retourne -1 si pas d'armes (géré par appelant)
  - [ ] **Timing:** Appelé APRÈS que l'agent choisit la cible, AVANT l'attaque
  
- [ ] `select_best_melee_weapon(unit, target, game_state) -> int`:
  - [ ] Même logique pour armes de mêlée
  
- [ ] `get_best_weapon_for_target(unit, target, game_state, is_ranged: bool) -> tuple[int, float]`:
  - [ ] Retourne (weapon_index, kill_probability) pour l'observation
  - [ ] Utilise cache pour éviter recalculs

#### Cache Structure - SIMPLIFIÉ
- [ ] Structure: `{(unit_id, weapon_index, target_id, hp_cur): kill_prob}`
  - [ ] **Note performance:** Cache invalidé si HP change (limitation acceptée pour MVP)
  - [ ] **Optimisation future possible:** Utiliser hp_ratio avec granularité (0.0, 0.25, 0.5, 0.75, 1.0)
- [ ] Pré-calcul au début de phase: `precompute_kill_probability_cache(game_state, phase)`
  - [ ] Appel dans `shooting_phase_start()` et `fight_phase_start()`
- [ ] Invalidation: Après `shooting_attack_controller()` et `_execute_fight_attack_sequence()` quand `damage_dealt > 0`
  - [ ] Invalider toutes les entrées où `target_id` = unité affectée
  - [ ] Invalider toutes les entrées où `unit_id` = unité morte

#### Lazy Evaluation (Optionnel)
- [ ] `recompute_cache_for_new_units_in_range(game_state, perception_radius: int = 25)`:
  - [ ] Recalcule pour unités entrées dans `perception_radius` après mouvement
  - [ ] **Appel dans:** `movement_phase_end()`
  - [ ] Utilise `game_state.get("perception_radius", 25)` avec fallback
```

---

### Section 8: EXPANSION ESPACE D'OBSERVATION (À CORRIGER)

#### Active Unit Capabilities - CORRIGER Structure

**Remplacer lignes 231-244 par:**

```markdown
#### Active Unit Capabilities [15:37] - 22 floats
- [ ] **Structure exacte (CORRIGÉE - pas de double assignation):**
  - [ ] `obs[15]` = MOVE / 12.0
  - [ ] `obs[16]` = RNG_WEAPONS[0]["RNG"] / 24.0 ou 0.0 si manquant
  - [ ] `obs[17]` = RNG_WEAPONS[0]["DMG"] / 5.0 ou 0.0 si manquant
  - [ ] `obs[18]` = RNG_WEAPONS[0]["NB"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[19]` = RNG_WEAPONS[1]["RNG"] / 24.0 ou 0.0 si manquant
  - [ ] `obs[20]` = RNG_WEAPONS[1]["DMG"] / 5.0 ou 0.0 si manquant
  - [ ] `obs[21]` = RNG_WEAPONS[1]["NB"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[22]` = RNG_WEAPONS[2]["RNG"] / 24.0 ou 0.0 si manquant
  - [ ] `obs[23]` = RNG_WEAPONS[2]["DMG"] / 5.0 ou 0.0 si manquant
  - [ ] `obs[24]` = RNG_WEAPONS[2]["NB"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[25]` = CC_WEAPONS[0]["NB"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[26]` = CC_WEAPONS[0]["ATK"] / 6.0 ou 0.0 si manquant
  - [ ] `obs[27]` = CC_WEAPONS[0]["STR"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[28]` = CC_WEAPONS[0]["AP"] / 6.0 ou 0.0 si manquant
  - [ ] `obs[29]` = CC_WEAPONS[0]["DMG"] / 5.0 ou 0.0 si manquant
  - [ ] `obs[30]` = CC_WEAPONS[1]["NB"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[31]` = CC_WEAPONS[1]["ATK"] / 6.0 ou 0.0 si manquant
  - [ ] `obs[32]` = CC_WEAPONS[1]["STR"] / 10.0 ou 0.0 si manquant
  - [ ] `obs[33]` = CC_WEAPONS[1]["AP"] / 6.0 ou 0.0 si manquant
  - [ ] `obs[34]` = CC_WEAPONS[1]["DMG"] / 5.0 ou 0.0 si manquant
  - [ ] `obs[35]` = T / 10.0
  - [ ] `obs[36]` = ARMOR_SAVE / 6.0
- **Vérification:** 1 + 3×3 + 2×5 + 2 = 22 floats ✅
```

#### Base Indices - CORRIGER

**Remplacer ligne 299 par:**

```markdown
- [ ] **CRITIQUE:** Mettre à jour tous les `base_idx`:
  - [ ] Directional Terrain: `base_idx=37` (au lieu de 23) - dans `_encode_directional_terrain()`
  - [ ] Allied Units: `base_idx=69` (au lieu de 55) - dans `_encode_allied_units()`
  - [ ] Enemy Units: `base_idx=141` (au lieu de 127) - dans `_encode_enemy_units()`
  - [ ] Valid Targets: `base_idx=273` (au lieu de 265) - dans `_encode_valid_targets()`
```

#### Enemy Units - CORRIGER Feature Count

**Remplacer lignes 246-266 par:**

```markdown
#### Enemy Units [141:273] - 132 floats (6 ennemis × 22 features) - **OPTIMISÉ**
- [ ] **CRITIQUE:** Changer `feature_base = base_idx + i * 23` → `i * 22` (ligne 968)
- [ ] **CRITIQUE:** Changer padding `for j in range(23):` → `range(22)` (ligne 1038)
- [ ] **CRITIQUE:** Supprimer feature 17 (`can_be_meleed`) - ligne 1020
- [ ] **CRITIQUE:** Supprimer feature 19 (`is_in_range`) - ligne 1028
- [ ] **Structure (22 features):**
  - Features 0-10: Position, health, movement, actions (11 floats) - **INCHANGÉ**
  - Features 11-12: `best_weapon_index` + `best_kill_probability` (2 floats) - **NOUVEAU**
  - Feature 13: `danger_to_me` (était feature 12) - **DÉCALÉ**
  - Features 14-16: Allied coordination (3 floats, était 13-15) - **DÉCALÉ**
  - Feature 17: `can_melee_units_charge_target` (était feature 15) - **DÉCALÉ**
  - Feature 18: `target_type_match` (était feature 16) - **DÉCALÉ**
  - Feature 19: `is_adjacent` (était feature 18) - **DÉCALÉ**
  - Features 20-21: Enemy capabilities (2 floats, était 20-22) - **DÉCALÉ**
```

#### Valid Targets - CLARIFIER

**Remplacer lignes 268-273 par:**

```markdown
#### Valid Targets [273:313] - 40 floats (5 cibles × 8 features)
- [ ] Feature 0: `is_valid` (inchangée)
- [ ] Feature 1: `best_weapon_index` (0-2, normalisé / 2.0) - **NOUVEAU**
- [ ] Feature 2: `best_kill_probability` - **NOUVEAU, remplace ancien feature 1**
- [ ] Features 3-7: Autres features existantes (décalées de +1)
- **Total: 8 features × 5 targets = 40 floats ✅**
```

---

### Section 1: PARSING TYPESCRIPT (À AMÉLIORER)

**Remplacer code proposé lignes 696-819 par:**

```python
# Pattern 2: RNG_WEAPON_CODES = ["code1", "code2"] - ROBUSTE
rng_codes_match = re.search(
    r'static\s+RNG_WEAPON_CODES\s*=\s*\[([^\]]*)\];',
    content,
    re.MULTILINE | re.DOTALL  # Support multi-lignes
)
if rng_codes_match:
    codes_str = rng_codes_match.group(1).strip()
    if codes_str:
        # Gérer guillemets simples ET doubles
        codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
    else:
        codes = []  # Array vide
    
    # Détection faction robuste
    if faction_path.startswith('spaceMarine/'):
        unit_stats["RNG_WEAPONS"] = get_sm_weapons(codes)
    elif faction_path.startswith('tyranid/'):
        unit_stats["RNG_WEAPONS"] = get_ty_weapons(codes)
    else:
        raise ValueError(f"Unknown faction in path: {faction_path}")

# Pattern 3: CC_WEAPON_CODES (même logique)
cc_codes_match = re.search(
    r'static\s+CC_WEAPON_CODES\s*=\s*\[([^\]]*)\];',
    content,
    re.MULTILINE | re.DOTALL
)
if cc_codes_match:
    codes_str = cc_codes_match.group(1).strip()
    if codes_str:
        codes = re.findall(r'["\']([^"\']+)["\']', codes_str)
    else:
        codes = []
    
    if faction_path.startswith('spaceMarine/'):
        unit_stats["CC_WEAPONS"] = get_sm_weapons(codes)
    elif faction_path.startswith('tyranid/'):
        unit_stats["CC_WEAPONS"] = get_ty_weapons(codes)
    else:
        raise ValueError(f"Unknown faction in path: {faction_path}")
```

**Même correction pour `ai/unit_registry.py` (lignes 799-816)**

---

### Section 6: HANDLERS DE COMBAT (À CORRIGER)

**Remplacer lignes 160 et 174 par:**

```markdown
### ✅ `engine/phase_handlers/shooting_handlers.py`
- [ ] **SHOOT_LEFT initialisation:** Dans `shooting_phase_start()`, ligne 36:
  - [ ] Remplacer `unit["SHOOT_LEFT"] = unit["RNG_NB"]` par:
  - [ ] `weapon = get_selected_ranged_weapon(unit)` puis `unit["SHOOT_LEFT"] = weapon["NB"]`
  - [ ] Si pas d'armes ranged, `SHOOT_LEFT = 0`
- [ ] **SHOOT_LEFT initialisation:** Dans `shooting_unit_activation_start()`, ligne 381:
  - [ ] Même correction que ci-dessus
- [ ] **Sélection d'arme:** Dans `shooting_target_selection_handler()`, AVANT `shooting_attack_controller()`:
  - [ ] Appeler `select_best_ranged_weapon(unit, target, game_state)` pour la cible choisie
  - [ ] Mettre à jour `selectedRngWeaponIndex` avec le résultat
  - [ ] **Note:** Sélection une fois par cible choisie (pas à chaque attaque si SHOOT_LEFT > 1)

### ✅ `engine/phase_handlers/fight_handlers.py`
- [ ] **ATTACK_LEFT initialisation:** Dans `fight_unit_activation_start()`, ligne 1282:
  - [ ] Remplacer `unit["ATTACK_LEFT"] = unit["CC_NB"]` par:
  - [ ] `weapon = get_selected_melee_weapon(unit)` puis `unit["ATTACK_LEFT"] = weapon["NB"]`
  - [ ] Si pas d'armes melee, `ATTACK_LEFT = 0`
- [ ] **Sélection d'arme:** Dans `_handle_fight_attack()`, AVANT `_execute_fight_attack_sequence()`:
  - [ ] Appeler `select_best_melee_weapon(unit, target, game_state)` pour la cible
  - [ ] Mettre à jour `selectedCcWeaponIndex` avec le résultat
```

---

### Section 4.1: VALIDATION ET REQUIRED PROPERTIES (À AJOUTER)

**Insérer après Section 4 (FACTORY ET GAME STATE):**

```markdown
## 4.1 VALIDATION ET REQUIRED PROPERTIES

### ✅ Mise à Jour Required Properties

**Fichiers à modifier:**
- [ ] `ai/unit_registry.py` ligne 117: Supprimer `RNG_RNG`, `RNG_DMG`, `CC_DMG` de `required_props`
- [ ] `frontend/src/data/UnitFactory.ts` ligne 39: Supprimer `RNG_RNG`, `RNG_DMG`, `CC_DMG` de `requiredProps`
- [ ] `config/unit_definitions.json`: Supprimer de `required_properties`
- [ ] `frontend/public/config/unit_definitions.json`: Supprimer de `required_properties`

**Nouvelle validation:**
- [ ] Au moins 1 arme requise: `RNG_WEAPONS.length > 0 || CC_WEAPONS.length > 0`
- [ ] Tous les codes d'armes doivent exister dans l'armory (raise error si manquant)
- [ ] `selectedRngWeaponIndex` doit être `undefined` (pas 0) si `RNG_WEAPONS.length === 0`
- [ ] `selectedCcWeaponIndex` doit être `undefined` (pas 0) si `CC_WEAPONS.length === 0`
```

---

### Section 8.1: CORRECTIONS OBSERVATION BUILDER (À AJOUTER)

**Insérer après Section 8 (EXPANSION ESPACE D'OBSERVATION):**

```markdown
## 8.1 CORRECTIONS CRITIQUES OBSERVATION BUILDER

### ✅ `engine/observation_builder.py` - Corrections Immédiates

#### Observation Size
- [ ] `__init__()`: Ajouter `self.obs_size = obs_params.get("obs_size", 313)`
- [ ] `build_observation()`: `obs = np.zeros(self.obs_size, dtype=np.float32)` (au lieu de 300)

#### Accès Anciens Champs - CRITIQUE
- [ ] **CRITIQUE:** Remplacer accès dans `_calculate_danger_probability()` (ligne 349):
  - [ ] `attacker["RNG_RNG"]`, `attacker["RNG_NB"]`, etc. → utiliser max DMG des armes ennemies
- [ ] **CRITIQUE:** Remplacer accès dans `_encode_allied_units()` (ligne 1116):
  - [ ] `offensive_type = 1.0 if unit["RNG_RNG"] > unit["CC_RNG"]` → `max(w.get("RNG", 0) for w in unit.get("RNG_WEAPONS", [])) > 1`
- [ ] **CRITIQUE:** Remplacer accès dans `_calculate_combat_mix_score()` (ligne 40):
  - [ ] `unit["RNG_NB"]`, `unit["RNG_ATK"]`, etc. → utiliser max DMG des armes
- [ ] **CRITIQUE:** Remplacer accès dans `_encode_valid_targets()` (ligne 1254):
  - [ ] `active_unit["RNG_NB"]`, `active_unit["RNG_ATK"]`, etc. → utiliser arme sélectionnée
- [ ] **CRITIQUE:** Remplacer accès dans `_calculate_favorite_target()` (ligne 158):
  - [ ] Utiliser stats des armes

#### Import Manquant
- [ ] Ajouter: `from engine.combat_utils import calculate_hex_distance`
```

---

### Section 14: CHECKLIST EXHAUSTIVE (À AJOUTER)

**Insérer après Section 13 (TESTS ET VALIDATION):**

```markdown
## 14. CHECKLIST EXHAUSTIVE - ACCÈS ANCIENS CHAMPS

### ✅ Vérification Complète Avant Migration

- [ ] Faire grep exhaustif: `grep -r "RNG_NB\|RNG_RNG\|RNG_ATK\|RNG_STR\|RNG_AP\|RNG_DMG\|CC_NB\|CC_RNG\|CC_ATK\|CC_STR\|CC_AP\|CC_DMG" --include="*.py" --include="*.ts" --include="*.tsx"`
- [ ] Lister TOUS les fichiers trouvés
- [ ] Pour chaque fichier, remplacer par helpers d'armes
- [ ] Vérifier qu'aucun ancien champ n'est utilisé après migration

### ✅ Fichiers Critiques Identifiés
- `engine/observation_builder.py` (multiple locations)
- `engine/game_state.py` (`load_units_from_scenario`)
- `engine/phase_handlers/shooting_handlers.py`
- `engine/phase_handlers/fight_handlers.py`
- `engine/phase_handlers/charge_handlers.py`
- `engine/reward_calculator.py`
- `ai/target_selector.py`
- `frontend/src/components/UnitStatusTable.tsx`
- `frontend/src/components/BoardReplay.tsx`
- `frontend/src/components/UnitRenderer.tsx`
- `frontend/src/utils/replayParser.ts`
- ... (voir grep results)
```

---

## ✅ RÉSUMÉ DES CORRECTIONS

### Corrections CRITIQUES (10)
1. ✅ Ajouter Section 0: PRÉAMBULE (structure répertoires, obs_size, base_idx)
2. ✅ Corriger Section 7: Fonction `calculate_kill_probability` (code complet)
3. ✅ Corriger Section 8: Structure Active Unit Capabilities (22 floats exacts)
4. ✅ Corriger Section 8: Base indices (37, 69, 141, 273)
5. ✅ Corriger Section 8: Enemy Units feature count (23 → 22)
6. ✅ Corriger Section 8: Valid Targets (8 features clarifiées)
7. ✅ Améliorer Section 1: Regex parsing (guillemets simples/doubles, multi-lignes)
8. ✅ Corriger Section 6: Noms de fonctions (shooting_phase_start, fight_unit_activation_start)
9. ✅ Ajouter Section 4.1: Validation et required_properties
10. ✅ Ajouter Section 8.1: Corrections observation_builder

### Ajouts IMPORTANTS (2)
1. ✅ Ajouter Section 14: Checklist exhaustive
2. ✅ Documenter cache limitation et tie-breaking

---

## 🎯 VALIDATION FINALE

**Toutes les observations des 3 audits sont pertinentes et doivent être intégrées.**

**Approche validée:**
- ✅ Code simple et lisible
- ✅ Pas de sur-engineering
- ✅ Solutions pragmatiques
- ✅ Évolutif (optimisations futures possibles)

**Points vérifiés:**
- ✅ Calcul observation space: 15 + 22 + 32 + 72 + 132 + 40 = 313 ✓
- ✅ Structure Active Unit Capabilities: 1 + 3×3 + 2×5 + 2 = 22 ✓
- ✅ Base indices: 37, 69, 141, 273 ✓
- ✅ Enemy Units: 6 × 22 = 132 ✓
- ✅ Valid Targets: 5 × 8 = 40 ✓

**Le plan doit être mis à jour avec ces corrections avant implémentation.**

---

## 📝 PRINCIPE DIRECTEUR

**Implémentation optimale = Simple + Correct + Évolutif**

1. **Fonction `calculate_kill_probability`:** Standalone simple (pas de wrapper complexe)
2. **Cache:** Structure tuple simple avec `hp_cur` (limitation acceptée)
3. **Regex:** Robuste mais simple (pas de parser TypeScript complet)
4. **Tie-breaking:** Index le plus bas (simple et déterministe)
5. **Timing:** Une fois par cible (simple et efficace)

**Priorité d'implémentation:**
1. Créer fonction `calculate_kill_probability` (bloque tout)
2. Corriger structure observation (base_idx, feature counts, obs_size)
3. Améliorer regex parsing
4. Remplacer tous les accès anciens champs
5. Implémenter cache (structure simple)

---

**Fin de l'audit complet**


