# Implémentation Complète - Armes Multiples par Unité
## Version Mise à Jour avec Corrections des Audits 32 et 33

**Date:** 2025-01-XX  
**Base:** MULTIPLE_WEAPONS_IMPLEMENTATION.md  
**Corrections intégrées:** MULTIPLE_WEAPONS_AUDIT_32.md, MULTIPLE_WEAPONS_AUDIT_33.md  
**Statut:** Plan finalisé avec toutes les corrections critiques vérifiées

---

## Vue d'ensemble

Migration complète du système d'armes unique vers système d'armes multiples (3 armes à distance max, 2 armes de mêlée max) avec:
- Définitions centralisées dans des fichiers armory
- Sélection automatique de l'arme par l'IA
- Observations étendues montrant toutes les options d'armes
- Logs incluant le nom de l'arme utilisée
- UI avec affichage expandable des armes
- **Optimisations:** Cache pré-calcul, réduction features redondantes, lazy evaluation

---

## 📊 RÉSUMÉ DES CHANGEMENTS

### Observation Space
- **Taille:** 300 → **313 floats** (après optimisations)
- **Active Unit Capabilities:** 8 → 22 floats (toutes les armes)
- **Enemy Units:** 138 → 132 floats (6 × 22 features, suppression features redondantes)
- **Valid Targets:** 35 → 40 floats (5 × 8 features)

### Performance
- **Cache pré-calcul:** ~90% réduction calculs `kill_probability` pendant phase
- **Lazy evaluation:** ~30% réduction calculs pour unités hors portée
- **Total:** Performance ×2-3

---

## ⚠️ PHASE 0: PRÉREQUIS CRITIQUES (À FAIRE EN PREMIER)

### 0.1 Structure de Répertoires
- [ ] Créer `engine/roster/` si n'existe pas
- [ ] Créer `engine/roster/spaceMarine/` avec `__init__.py`
- [ ] Créer `engine/roster/tyranid/` avec `__init__.py`
- **CRITIQUE:** Sans ces répertoires, les imports Python échoueront

### 0.2 Observation Size - Mise à Jour Globale (Validation Stricte, NO DEFAULT)
- [ ] `engine/observation_builder.py` ligne 602: `obs = np.zeros(300, ...)` → `self.obs_size` (depuis config, **NO DEFAULT, raise error si manquant**)
- [ ] `engine/w40k_core.py` ligne 291: `obs_size = 300` → `obs_size = obs_params["obs_size"]` (**NO DEFAULT, raise error si manquant**)
- [ ] `check/test_observation.py` ligne 33: `assert obs.shape == (300,)` → Utiliser `engine.observation_space.shape[0]`
- [ ] `services/api_server.py` lignes 179, 289: **Validation stricte de `obs_size` dans config, raise error si manquant**
- [ ] Tous les `training_config.json`: **DOIT avoir `"obs_size": 313` dans `observation_params`**
- **Vérification:** `grep -r "obs_size.*300\|300.*obs"` pour trouver tous

### 0.3 Base Indices - Correction Immédiate
- [ ] `engine/observation_builder.py` ligne 644: `base_idx=23` → `base_idx=37` (Directional Terrain)
- [ ] `engine/observation_builder.py` ligne 647: `base_idx=55` → `base_idx=69` (Allied Units)
- [ ] `engine/observation_builder.py` ligne 650: `base_idx=127` → `base_idx=141` (Enemy Units)
- [ ] `engine/observation_builder.py` ligne 653: `base_idx=265` → `base_idx=273` (Valid Targets)
- **CRITIQUE:** Doit être fait AVANT toute modification de structure

### 0.4 Enemy Units Feature Count - Correction
- [ ] `engine/observation_builder.py` ligne 968: `i * 23` → `i * 22`
- [ ] `engine/observation_builder.py` ligne 1038: `range(23)` → `range(22)`
- [ ] Supprimer ligne 1020: Feature 17 (`can_be_meleed`)
- [ ] Supprimer ligne 1028: Feature 19 (`is_in_range`)
- [ ] Réindexer toutes les features suivantes (voir détails section 8)

---

## 1. DÉFINITIONS DE TYPES

### ✅ `frontend/src/types/game.ts`
- [ ] Créer interface `Weapon`:
  ```typescript
  interface Weapon {
    code_name: string;        // Nom utilisé dans le tableau de l'unité
    display_name: string;    // Nom affiché dans l'UI
    RNG?: number;            // Portée (armes à distance uniquement)
    NB: number;              // Nombre d'attaques
    ATK: number;             // Cible de toucher
    STR: number;             // Force
    AP: number;              // Pénétration d'armure
    DMG: number;             // Dégâts
  }
  ```
- [ ] Mettre à jour interface `Unit`:
  - [ ] Remplacer champs arme unique par:
    - `RNG_WEAPONS: Weapon[]`
    - `CC_WEAPONS: Weapon[]`
    - `selectedRngWeaponIndex?: number`
    - `selectedCcWeaponIndex?: number`
  - [ ] Supprimer champs dépréciés (migration immédiate, pas de compatibilité arrière)
  - [ ] **CRITIQUE:** Supprimer interface Unit dupliquée dans `UnitFactory.ts` (ligne 64)

---

## 2. ARMURERIES CENTRALISÉES

### ✅ `frontend/src/roster/spaceMarine/armory.ts` (NOUVEAU)
- [ ] Créer fichier avec:
  - `SPACE_MARINE_ARMORY: Record<string, Weapon>` - toutes les armes Space Marine
  - Fonction `getWeapon(codeName: string): Weapon | undefined`
  - Fonction `getWeapons(codeNames: string[]): Weapon[]`
  - **Validation:** `getWeapon()` raise error si arme manquante (pas de fallback)
- [ ] Définir armes à distance: `bolt_rifle`, `bolt_pistol`, `storm_bolter`, `heavy_bolter`, etc.
- [ ] Définir armes de mêlée: `close_combat_weapon`, `chainsword`, `power_sword`, `power_fist`, `thunder_hammer`, etc.
- [ ] **Synchronisation frontend/backend:**
  - [ ] Documenter format JSON: armes sérialisées comme objets avec tous les champs
  - [ ] Validation stricte: raise error si arme manquante dans armory
  - [ ] Même format que pour les unités (pas de transformation)

### ✅ `frontend/src/roster/tyranid/armory.ts` (NOUVEAU)
- [ ] Créer fichier avec même structure
- [ ] Définir armes Tyranid (ranged et melee)
- [ ] **Validation et synchronisation:** Même règles que spaceMarine

### ✅ `engine/roster/spaceMarine/armory.py` (NOUVEAU) - **CRITIQUE**
- [ ] Créer fichier Python équivalent de l'armory TypeScript
- [ ] Structure: `SPACE_MARINE_ARMORY: Dict[str, Dict]` - mêmes armes que TS
- [ ] Fonction `get_weapon(code_name: str) -> Dict | None`
- [ ] Fonction `get_weapons(code_names: List[str]) -> List[Dict]`
- [ ] **Utilisé par:** Parsing Python des fichiers TypeScript pour construire `RNG_WEAPONS[]` et `CC_WEAPONS[]`
- [ ] **Synchronisation:** Même structure que armory TS (copie manuelle ou script de génération)

### ✅ `engine/roster/tyranid/armory.py` (NOUVEAU) - **CRITIQUE**
- [ ] Créer fichier avec même structure
- [ ] Définir armes Tyranid (ranged et melee)
- [ ] **Validation et synchronisation:** Même règles que spaceMarine

---

## 3. CLASSES D'UNITÉS (9 fichiers)

### ✅ Space Marines
- [ ] `Intercessor.ts`, `AssaultIntercessor.ts`, `CaptainGravis.ts`, `Terminator.ts`

### ✅ Tyranids
- [ ] `Carnifex.ts`, `Genestealer.ts`, `GenestealerPrime.ts`, `Hormagaunt.ts`, `Termagant.ts`

**Structure à utiliser:**
```typescript
static RNG_WEAPON_CODES = ["bolt_rifle"];
static RNG_WEAPONS = getWeapons(Intercessor.RNG_WEAPON_CODES);
static CC_WEAPON_CODES = ["close_combat_weapon"];
static CC_WEAPONS = getWeapons(Intercessor.CC_WEAPON_CODES);
```

**Ordre des armes:** Ordre défini dans armory (ordre déclaratif, stable)

---

## 4. FACTORY ET GAME STATE

### ✅ `frontend/src/data/UnitFactory.ts`
- [ ] Mettre à jour `createUnit()`:
  - [ ] Remplir `RNG_WEAPONS` et `CC_WEAPONS` depuis la classe d'unité
  - [ ] **Validation:** Raise error si `RNG_WEAPONS.length === 0` ET `CC_WEAPONS.length === 0`
  - [ ] **Validation:** Raise error si arme manquante dans armory
  - [ ] Définir `selectedRngWeaponIndex = 0` si `RNG_WEAPONS.length > 0`, sinon undefined
  - [ ] Définir `selectedCcWeaponIndex = 0` si `CC_WEAPONS.length > 0`, sinon undefined
  - [ ] **PAS DE FALLBACK:** Toutes les erreurs doivent raise
- [ ] **CRITIQUE:** Supprimer interface Unit locale (ligne 64), importer depuis `types/game.ts`
- [ ] **CRITIQUE:** Supprimer `RNG_RNG`, `RNG_DMG`, `CC_DMG` de `requiredProps` (ligne 39)

### ✅ `engine/game_state.py`
- [ ] Mettre à jour `create_unit()`:
  - [ ] Gérer tableaux `RNG_WEAPONS[]` et `CC_WEAPONS[]`
  - [ ] **Validation:** Raise error si `RNG_WEAPONS` ET `CC_WEAPONS` vides
  - [ ] Ajouter champs `selectedRngWeaponIndex` et `selectedCcWeaponIndex`
  - [ ] Supprimer assignations des anciens champs arme unique
- [ ] Mettre à jour `validate_uppercase_fields()`:
  - [ ] Remplacer validation de `RNG_NB`, `RNG_RNG`, etc. par validation de `RNG_WEAPONS[]` et `CC_WEAPONS[]`
- [ ] Mettre à jour `load_units_from_scenario()` (lignes 140-171) - **CRITIQUE:**
  - [ ] Extraire `RNG_WEAPONS[]` et `CC_WEAPONS[]` depuis `full_unit_data`
  - [ ] Remplacer `"RNG_NB": full_unit_data["RNG_NB"]` par extraction depuis `RNG_WEAPONS[0]["NB"]` si existe
  - [ ] Remplacer `"CC_NB": full_unit_data["CC_NB"]` par extraction depuis `CC_WEAPONS[0]["NB"]` si existe
  - [ ] Remplacer `"SHOOT_LEFT": full_unit_data["RNG_NB"]` par extraction depuis arme sélectionnée
  - [ ] Remplacer `"ATTACK_LEFT": full_unit_data["CC_NB"]` par extraction depuis arme sélectionnée
  - [ ] Construire `RNG_WEAPONS[]` et `CC_WEAPONS[]` si manquants (depuis armory Python)

---

## 5. FONCTIONS HELPER ARMES

### ✅ `frontend/src/utils/weaponHelpers.ts` (NOUVEAU)
- [ ] `getSelectedRangedWeapon(unit: Unit): Weapon | null`
- [ ] `getSelectedMeleeWeapon(unit: Unit): Weapon | null`
- [ ] `getMeleeRange(): number` - retourne toujours 1
- [ ] `getMaxRangedRange(unit: Unit): number` - retourne max RNG des armes ranged

### ✅ `engine/utils/weapon_helpers.py` (NOUVEAU)
- [ ] `get_selected_ranged_weapon(unit: dict) -> dict | None`
- [ ] `get_selected_melee_weapon(unit: dict) -> dict | None`
- [ ] `get_melee_range() -> int` - retourne toujours 1
- [ ] `get_max_ranged_range(unit: dict) -> int` - retourne max RNG des armes ranged

**Code complet des helpers Python:**
```python
# engine/utils/weapon_helpers.py (NOUVEAU)

def get_selected_ranged_weapon(unit: Dict) -> Dict | None:
    """Get currently selected ranged weapon."""
    if "RNG_WEAPONS" not in unit:
        raise KeyError(f"Unit missing RNG_WEAPONS: {unit}")
    rng_weapons = unit.get("RNG_WEAPONS", [])
    if not rng_weapons:
        return None
    idx = unit.get("selectedRngWeaponIndex", 0)
    if idx < 0 or idx >= len(rng_weapons):
        raise IndexError(f"Invalid selectedRngWeaponIndex {idx} for unit {unit['id']}")
    return rng_weapons[idx]

def get_selected_melee_weapon(unit: Dict) -> Dict | None:
    """Get currently selected melee weapon."""
    if "CC_WEAPONS" not in unit:
        raise KeyError(f"Unit missing CC_WEAPONS: {unit}")
    cc_weapons = unit.get("CC_WEAPONS", [])
    if not cc_weapons:
        return None
    idx = unit.get("selectedCcWeaponIndex", 0)
    if idx < 0 or idx >= len(cc_weapons):
        raise IndexError(f"Invalid selectedCcWeaponIndex {idx} for unit {unit['id']}")
    return cc_weapons[idx]

def get_melee_range() -> int:
    """Melee range is always 1."""
    return 1

def get_max_ranged_range(unit: Dict) -> int:
    """Get maximum range of all ranged weapons."""
    rng_weapons = unit.get("RNG_WEAPONS", [])
    if not rng_weapons:
        return 0
    return max(w.get("RNG", 0) for w in rng_weapons)
```

---

## 6. HANDLERS DE COMBAT

### ✅ `engine/phase_handlers/shooting_handlers.py`

#### **CRITIQUE: SHOOT_LEFT Initialisation - DEUX Endroits**

**Découverte critique des audits:** SHOOT_LEFT est initialisé à **DEUX** endroits différents. Les deux doivent être modifiés.

##### Endroit 1: `shooting_phase_start()` ligne 36
- [ ] **CRITIQUE:** Remplacer `unit["SHOOT_LEFT"] = unit["RNG_NB"]` par:
  ```python
  from engine.weapon_helpers import get_selected_ranged_weapon
  rng_weapons = unit.get("RNG_WEAPONS", [])
  if rng_weapons:
      selected_idx = unit.get("selectedRngWeaponIndex", 0)
      if selected_idx < 0 or selected_idx >= len(rng_weapons):
          # Default to first weapon if index invalid (phase start, pas encore de sélection)
          selected_idx = 0
      weapon = rng_weapons[selected_idx]
      unit["SHOOT_LEFT"] = weapon["NB"]
  else:
      unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged
  ```

##### Endroit 2: `shooting_unit_activation_start()` ligne 381
- [ ] **CRITIQUE:** Remplacer `unit["SHOOT_LEFT"] = unit["RNG_NB"]` par:
  ```python
  from engine.weapon_helpers import get_selected_ranged_weapon
  rng_weapons = unit.get("RNG_WEAPONS", [])
  if rng_weapons:
      selected_idx = unit.get("selectedRngWeaponIndex", 0)
      if selected_idx < 0 or selected_idx >= len(rng_weapons):
          raise IndexError(f"Invalid selectedRngWeaponIndex {selected_idx} for unit {unit['id']}")
      weapon = rng_weapons[selected_idx]
      unit["SHOOT_LEFT"] = weapon["NB"]
  else:
      unit["SHOOT_LEFT"] = 0  # Pas d'armes ranged
  ```

#### Sélection d'arme - Timing Exact
- [ ] **Sélection d'arme:** Dans `shooting_target_selection_handler()`, **APRÈS** ligne 1218 (target validé), **AVANT** ligne 1221:
  ```python
  # === NOUVEAU: Sélection d'arme pour cette cible ===
  from engine.ai.weapon_selector import select_best_ranged_weapon
  best_weapon_idx = select_best_ranged_weapon(unit, target, game_state)
  
  if best_weapon_idx >= 0:
      unit["selectedRngWeaponIndex"] = best_weapon_idx
      # Mettre à jour SHOOT_LEFT avec la nouvelle arme (si pas déjà initialisé ou si arme change)
      weapon = unit["RNG_WEAPONS"][best_weapon_idx]
      current_shoot_left = unit.get("SHOOT_LEFT", 0)
      # Si SHOOT_LEFT n'est pas encore initialisé ou si l'arme a changé, réinitialiser
      if current_shoot_left == 0 or current_shoot_left == unit.get("RNG_NB", 0):
          unit["SHOOT_LEFT"] = weapon["NB"]
  else:
      # Pas d'armes disponibles
      unit["SHOOT_LEFT"] = 0
      return False, {"error": "no_weapons_available", "unitId": unit_id}
  # === FIN NOUVEAU ===
  ```
  - [ ] **Note importante:** Si SHOOT_LEFT > 1, l'arme reste la même pour tous les tirs sur cette cible. Pas de re-sélection à chaque tir.

#### Autres modifications
- [ ] Remplacer tous les accès directs `unit["RNG_NB"]` etc. par l'arme sélectionnée
- [ ] Mettre à jour `_attack_sequence_rng()` pour utiliser l'arme sélectionnée
- [ ] Mettre à jour `shooting_build_valid_target_pool()` pour utiliser armes
- [ ] **Cache invalidation:** Après `shooting_attack_controller()` quand `damage_dealt > 0`:
  - [ ] Invalider toutes les entrées de cache où `target_id` = unité affectée

### ✅ `engine/phase_handlers/fight_handlers.py`

#### ATTACK_LEFT Initialisation - Localisation Exacte
- [ ] **CRITIQUE:** Dans `_handle_fight_unit_activation()` ligne 1282 (PAS `fight_phase_start()`):
  ```python
  # AVANT:
  unit["ATTACK_LEFT"] = unit["CC_NB"]
  
  # APRÈS:
  from engine.weapon_helpers import get_selected_melee_weapon
  cc_weapons = unit.get("CC_WEAPONS", [])
  if cc_weapons:
      selected_idx = unit.get("selectedCcWeaponIndex", 0)
      if selected_idx < 0 or selected_idx >= len(cc_weapons):
          raise IndexError(f"Invalid selectedCcWeaponIndex {selected_idx} for unit {unit['id']}")
      weapon = cc_weapons[selected_idx]
      unit["ATTACK_LEFT"] = weapon["NB"]
  else:
      unit["ATTACK_LEFT"] = 0  # Pas d'armes melee
  ```

#### Sélection d'arme - Timing Exact
- [ ] **Sélection d'arme:** Dans `_handle_fight_attack()`, **APRÈS** ligne 1480 (target validé), **AVANT** ligne 1488:
  ```python
  # === NOUVEAU: Sélection d'arme pour cette cible ===
  target = _get_unit_by_id(game_state, target_id)
  if not target:
      return False, {"error": "target_not_found", "targetId": target_id}
  
  from engine.ai.weapon_selector import select_best_melee_weapon
  best_weapon_idx = select_best_melee_weapon(unit, target, game_state)
  
  if best_weapon_idx >= 0:
      unit["selectedCcWeaponIndex"] = best_weapon_idx
      # Mettre à jour ATTACK_LEFT avec la nouvelle arme (si pas déjà initialisé ou si arme change)
      weapon = unit["CC_WEAPONS"][best_weapon_idx]
      current_attack_left = unit.get("ATTACK_LEFT", 0)
      # Si ATTACK_LEFT n'est pas encore initialisé ou si l'arme a changé, réinitialiser
      if current_attack_left == 0 or current_attack_left == unit.get("CC_NB", 0):
          unit["ATTACK_LEFT"] = weapon["NB"]
  else:
      # Pas d'armes disponibles
      unit["ATTACK_LEFT"] = 0
      return False, {"error": "no_weapons_available", "unitId": unit["id"]}
  # === FIN NOUVEAU ===
  ```

#### Autres modifications
- [ ] Remplacer tous les accès directs `unit["CC_NB"]` etc. par l'arme sélectionnée
- [ ] CC_RNG est toujours 1 (hardcodé) - utiliser `get_melee_range()`
- [ ] Mettre à jour `_execute_fight_attack_sequence()` pour utiliser l'arme sélectionnée
- [ ] **Cache invalidation:** Après `_execute_fight_attack_sequence()` quand `damage_dealt > 0`:
  - [ ] Invalider toutes les entrées de cache où `target_id` = unité affectée

### ✅ `engine/phase_handlers/charge_handlers.py`
- [ ] Mettre à jour calcul de menace (lignes 322-328, 337):
  - [ ] Remplacer `target["RNG_STR"]`, `target["RNG_NB"]` par stats de la meilleure arme ranged
  - [ ] Remplacer `target["CC_STR"]`, `target["CC_NB"]` par stats de la meilleure arme melee
  - [ ] Calculer menace max de toutes les armes de la cible

---

## 7. SÉLECTION D'ARME PAR IA

### ✅ `engine/ai/weapon_selector.py` (NOUVEAU)

#### **CRITIQUE: Fonction `calculate_kill_probability` - Standalone Complète**

**Problème identifié par les audits:** Le code proposé utilise `calculate_kill_probability(unit, weapon, target, game_state)` mais cette fonction n'existe pas. Les audits recommandent une fonction standalone complète (pas un wrapper).

- [ ] **CRITIQUE:** Créer fonction `calculate_kill_probability(unit, weapon, target, game_state) -> float`:
  ```python
  # engine/ai/weapon_selector.py
  from shared.data_validation import require_key
  
  def calculate_kill_probability(unit: Dict[str, Any], weapon: Dict[str, Any], 
                                  target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
      """
      Calculate kill probability for a specific weapon against a target.
      Simple, standalone function - pas de dépendance complexe.
      
      AI_IMPLEMENTATION.md COMPLIANCE: No defaults - raise error if required data missing.
      """
      # Extraire stats de l'arme - NO DEFAULT, raise error si manquant
      hit_target = require_key(weapon, "ATK")
      strength = require_key(weapon, "STR")
      damage = require_key(weapon, "DMG")
      num_attacks = require_key(weapon, "NB")
      ap = require_key(weapon, "AP")
      
      # Calculs W40K standard
      p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
      
      # Wound probability - NO DEFAULT, raise error si T manquant
      toughness = require_key(target, "T")
      if strength >= toughness * 2:
          p_wound = 5/6
      elif strength > toughness:
          p_wound = 4/6
      elif strength == toughness:
          p_wound = 3/6
      else:
          p_wound = 2/6
      
      # Save probability
      # ARMOR_SAVE et INVUL_SAVE peuvent être optionnels (certaines unités n'ont pas d'invul save)
      # Utiliser .get() avec default raisonnable pour ces champs optionnels
      armor_save = target.get("ARMOR_SAVE", 7)  # Default 7 = pas de save
      invul_save = target.get("INVUL_SAVE", 7)  # Default 7 = pas d'invul save
      save_target = min(armor_save - ap, invul_save)
      p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
      
      # Expected damage
      p_damage_per_attack = p_hit * p_wound * p_fail_save
      expected_damage = num_attacks * p_damage_per_attack * damage
      
      # Kill probability - NO DEFAULT, raise error si HP_CUR manquant
      hp_cur = require_key(target, "HP_CUR")
      if expected_damage >= hp_cur:
          return 1.0
      else:
          return min(1.0, expected_damage / hp_cur)
  ```

- [ ] **Note:** Si `calculate_hex_distance` est utilisé dans d'autres fonctions de `weapon_selector.py` (ex: `recompute_cache_for_new_units_in_range`), ajouter l'import:
  ```python
  from engine.combat_utils import calculate_hex_distance
  ```

#### Fonctions Principales
- [ ] `select_best_ranged_weapon(unit, target, game_state) -> int`:
  - [ ] **Validation:** Raise error si `RNG_WEAPONS.length == 0`
  - [ ] Calcule `kill_probability` pour chaque arme contre la cible (utilise cache si disponible)
  - [ ] **Tie-breaking:** Retourne l'index de la première arme avec la meilleure probabilité (index le plus bas en cas d'égalité)
  - [ ] Retourne -1 si pas d'armes (géré par appelant)
  
- [ ] `select_best_melee_weapon(unit, target, game_state) -> int`:
  - [ ] **Validation:** Raise error si `CC_WEAPONS.length == 0`
  - [ ] Même logique pour armes de mêlée
  - [ ] Retourne -1 si pas d'armes (géré par appelant)
  
- [ ] `get_best_weapon_for_target(unit, target, game_state, is_ranged: bool) -> tuple[int, float]`:
  - [ ] Retourne (weapon_index, kill_probability) pour l'observation
  - [ ] Utilise cache pour éviter recalculs
  - [ ] Retourne (-1, 0.0) si pas d'armes disponibles

#### Cache Pré-calcul
- [ ] `precompute_kill_probability_cache(game_state, phase) -> Dict`:
  - [ ] Pré-calcule pour toutes les unités actives × toutes les cibles × toutes les armes
  - [ ] **Appel dans:** `shooting_phase_start()` et `fight_phase_start()` (après la création des pools d'activation)
  - [ ] Structure: `{(unit_id, weapon_index, target_id, hp_cur): kill_prob}`

#### Cache Invalidation
- [ ] Invalider après chaque modification de `HP_CUR`:
  - [ ] Après `shooting_attack_controller()` quand `damage_dealt > 0`
  - [ ] Après `_execute_fight_attack_sequence()` quand `damage_dealt > 0`
  - [ ] **Méthode simple:** Supprimer toutes les entrées où `target_id` = unité affectée
  - [ ] Supprimer toutes les entrées où `unit_id` = unité morte (ne peut plus attaquer)

#### Lazy Evaluation
- [ ] `recompute_cache_for_new_units_in_range(game_state) -> None`:
  - [ ] Recalcule pour unités qui entrent dans `perception_radius` après mouvement
  - [ ] **Appel dans:** `movement_phase_end()` (vérifier que fonction existe et est appelée)
  - [ ] Utiliser `game_state.get("perception_radius", 25)` avec fallback

**IMPORTANT:** 
- Chaque cible peut avoir une arme différente comme "meilleure". L'arme est sélectionnée automatiquement quand l'agent choisit une cible.
- **Timing:** Agent choisit cible (action RL) → Arme sélectionnée pour cette cible spécifique → Attaque exécutée avec cette arme
- Si SHOOT_LEFT > 1, même arme pour tous les tirs sur cette cible

---

## 8. EXPANSION ESPACE D'OBSERVATION

### ✅ `engine/observation_builder.py`

#### **CRITIQUE: Observation Size - Validation Stricte, NO DEFAULT**

- [ ] **CRITIQUE:** Mettre à jour `__init__()`:
  ```python
  def __init__(self, config: Dict[str, Any]):
      self.config = config
      
      # Load observation params
      obs_params = config.get("observation_params")
      if not obs_params:
          raise KeyError("Config missing required 'observation_params' field")
      
      # AI_OBSERVATION.md COMPLIANCE: No defaults - force explicit configuration
      self.perception_radius = obs_params["perception_radius"]  # No default
      self.max_nearby_units = obs_params.get("max_nearby_units", 10)
      self.max_valid_targets = obs_params.get("max_valid_targets", 5)
      
      # CRITIQUE: obs_size depuis config, NO DEFAULT - raise error si manquant
      if "obs_size" not in obs_params:
          raise KeyError(
              f"Config missing required 'obs_size' in observation_params. "
              f"Must be defined in training_config.json. Current obs_params: {obs_params}"
          )
      self.obs_size = obs_params["obs_size"]  # Source unique de vérité
  ```

- [ ] **CRITIQUE:** Mettre à jour `build_observation()`:
  ```python
  def build_observation(self, game_state: Dict[str, Any]) -> np.ndarray:
      obs = np.zeros(self.obs_size, dtype=np.float32)  # Utiliser self.obs_size
      # ... reste du code ...
  ```

**Taille: 300 → 313 floats** (après optimisations)

#### Structure Observation Space
- **Global Context:** [0:15] = 15 floats (inchangé)
- **Active Unit Capabilities:** [15:37] = 22 floats
- **Directional Terrain:** [37:69] = 32 floats
- **Allied Units:** [69:141] = 72 floats
- **Enemy Units:** [141:273] = 132 floats (6 × 22 features) - **OPTIMISÉ**
- **Valid Targets:** [273:313] = 40 floats (5 × 8 features)
- **Total = 313 floats**

#### Active Unit Capabilities [15:37] - 22 floats

**Code complet (corrigé selon audits):**
```python
# === SECTION 2: Active Unit Capabilities (22 floats) ===
obs[15] = active_unit.get("MOVE", 0) / 12.0

# RNG_WEAPONS[0] (3 floats: RNG, DMG, NB)
rng_weapons = active_unit.get("RNG_WEAPONS", [])
if len(rng_weapons) > 0:
    obs[16] = rng_weapons[0].get("RNG", 0) / 24.0
    obs[17] = rng_weapons[0].get("DMG", 0) / 5.0
    obs[18] = rng_weapons[0].get("NB", 0) / 10.0
else:
    obs[16] = obs[17] = obs[18] = 0.0

# RNG_WEAPONS[1] (3 floats)
if len(rng_weapons) > 1:
    obs[19] = rng_weapons[1].get("RNG", 0) / 24.0
    obs[20] = rng_weapons[1].get("DMG", 0) / 5.0
    obs[21] = rng_weapons[1].get("NB", 0) / 10.0
else:
    obs[19] = obs[20] = obs[21] = 0.0

# RNG_WEAPONS[2] (3 floats)
if len(rng_weapons) > 2:
    obs[22] = rng_weapons[2].get("RNG", 0) / 24.0
    obs[23] = rng_weapons[2].get("DMG", 0) / 5.0
    obs[24] = rng_weapons[2].get("NB", 0) / 10.0
else:
    obs[22] = obs[23] = obs[24] = 0.0

# CC_WEAPONS[0] (5 floats: NB, ATK, STR, AP, DMG)
cc_weapons = active_unit.get("CC_WEAPONS", [])
if len(cc_weapons) > 0:
    obs[25] = cc_weapons[0].get("NB", 0) / 10.0
    obs[26] = cc_weapons[0].get("ATK", 0) / 6.0
    obs[27] = cc_weapons[0].get("STR", 0) / 10.0
    obs[28] = cc_weapons[0].get("AP", 0) / 6.0
    obs[29] = cc_weapons[0].get("DMG", 0) / 5.0
else:
    obs[25] = obs[26] = obs[27] = obs[28] = obs[29] = 0.0

# CC_WEAPONS[1] (5 floats)
if len(cc_weapons) > 1:
    obs[30] = cc_weapons[1].get("NB", 0) / 10.0
    obs[31] = cc_weapons[1].get("ATK", 0) / 6.0
    obs[32] = cc_weapons[1].get("STR", 0) / 10.0
    obs[33] = cc_weapons[1].get("AP", 0) / 6.0
    obs[34] = cc_weapons[1].get("DMG", 0) / 5.0
else:
    obs[30] = obs[31] = obs[32] = obs[33] = obs[34] = 0.0

obs[35] = active_unit.get("T", 0) / 10.0
obs[36] = active_unit.get("ARMOR_SAVE", 0) / 6.0

# Vérification: 1 + 3×3 + 2×5 + 2 = 22 floats ✅
```

#### Enemy Units [141:273] - 132 floats (6 ennemis × 22 features) - **OPTIMISÉ**

**Structure finale (22 features):**
- Features 0-10: Position, health, movement, actions (11 floats) - **INCHANGÉ**
- Features 11-12: `best_weapon_index` + `best_kill_probability` (2 floats) - **NOUVEAU, REMPLACE feature 11**
- Feature 13: `danger_to_me` (était feature 12) - **DÉCALÉ**
- Features 14-16: Allied coordination (3 floats, était 13-15) - **DÉCALÉ**
  - Feature 14: `visibility_to_allies` (était feature 13)
  - Feature 15: `combined_friendly_threat` (était feature 14)
  - Feature 16: `melee_charge_preference` (était feature 15 `can_be_charged_by_melee`) - **AMÉLIORÉ POST-ÉTAPE 9**
- ~~Feature 17 originale: `can_melee_units_charge_target`~~ - **SUPPRIMÉ** (redondant avec Feature 16 améliorée)
- Feature 17: `target_efficiency` (était feature 16 `target_type_match`) - **AMÉLIORÉ POST-ÉTAPE 9**
- Feature 18: `is_adjacent` (était feature 18 originale) - **INCHANGÉ**
- Features 19-20: Enemy capabilities (2 floats, était 20-22) - **DÉCALÉ**

**Note:** Features 16 et 17 seront améliorées après l'étape 9 (voir section "AMÉLIORATIONS POST-ÉTAPE 9" ci-dessous).

**Modifications:**
- [ ] **Ligne 968:** Changer `feature_base = base_idx + i * 23` → `feature_base = base_idx + i * 22`
- [ ] **Ligne 1038:** Changer `for j in range(23):` → `for j in range(22):`
- [ ] **Supprimer ligne 1020:** Feature 17 (`can_be_meleed`)
- [ ] **Supprimer ligne 1028:** Feature 19 (`is_in_range`)
- [ ] **Ajouter features 11-12 AVANT feature 13:**
  ```python
  from engine.ai.weapon_selector import get_best_weapon_for_target
  best_weapon_idx, best_kill_prob = get_best_weapon_for_target(
      active_unit, enemy, game_state, is_ranged=True
  )
  obs[feature_base + 11] = best_weapon_idx / 2.0 if best_weapon_idx >= 0 else 0.0
  obs[feature_base + 12] = best_kill_prob
  ```
- [ ] **Réindexer toutes les features suivantes:**
  - Feature 12 (`danger_to_me`) → Feature 13
  - Features 13-15 (Allied coordination) → Features 14-16
    - Feature 13 → Feature 14 (`visibility_to_allies`)
    - Feature 14 → Feature 15 (`combined_friendly_threat`)
    - Feature 15 → Feature 16 (`melee_charge_preference`, amélioré post-étape 9)
  - Feature 17 originale (`can_melee_units_charge_target`) → **SUPPRIMÉ** (redondant avec Feature 16 améliorée)
  - Feature 16 (`target_type_match`) → Feature 17 (`target_efficiency`, amélioré post-étape 9)
  - Feature 18 (`is_adjacent`) → Feature 18 (inchangé)
  - Features 20-22 (Enemy capabilities) → Features 19-20 (2 floats)

#### ⚠️ AMÉLIORATIONS POST-ÉTAPE 9 (À FAIRE APRÈS CRÉATION DE `weapon_selector.py`)

**Note:** Ces améliorations nécessitent `weapon_selector.py` (créé à l'étape 7) et les fonctions de calcul TTK. Elles doivent être implémentées **APRÈS** l'étape 9 (calculateur de récompenses) car elles utilisent `_calculate_turns_to_kill()` de `reward_calculator.py`.

##### Feature 16: `melee_charge_preference` (remplace `can_be_charged_by_melee`)

**Problème actuel:** Feature 15 originale (`can_be_charged_by_melee`) vérifie uniquement si un allié melee peut charger (distance), mais ne vérifie pas si l'allié est vraiment melee ou si charger est tactiquement avantageux.

**Amélioration proposée:** Comparer Time-To-Kill (TTK) melee vs range pour le meilleur allié melee, pour déterminer si charger est préféré.

**Code à implémenter:**
```python
# Feature 16: melee_charge_preference (0.0-1.0)
# Compare TTK melee vs TTK range pour le meilleur allié melee
# 1.0 = melee est beaucoup plus efficace (charge préféré)
# 0.0 = range est plus efficace (ne chargerait pas)
# 0.5 = équivalent

from engine.utils.weapon_helpers import get_selected_melee_weapon, get_selected_ranged_weapon
from engine.ai.weapon_selector import get_best_weapon_for_target
from engine.reward_calculator import RewardCalculator
from engine.combat_utils import calculate_pathfinding_distance

reward_calc = RewardCalculator()  # Instance pour accès à _calculate_turns_to_kill
best_melee_ally = None
best_melee_ttk = float('inf')
best_range_ttk = float('inf')

current_player = game_state["current_player"]
for ally in game_state["units"]:
    if (ally["player"] == current_player and 
        ally["HP_CUR"] > 0 and
        ally.get("CC_WEAPONS") and len(ally["CC_WEAPONS"]) > 0 and  # A des armes melee
        ally.get("RNG_WEAPONS") and len(ally["RNG_WEAPONS"]) > 0):  # A aussi des armes range
        
        # Vérifier si peut charger (distance)
        distance = calculate_pathfinding_distance(
            ally["col"], ally["row"],
            enemy["col"], enemy["row"],
            game_state
        )
        if "MOVE" not in ally:
            raise KeyError(f"Unit missing required 'MOVE' field: {ally}")
        max_charge_range = ally["MOVE"] + 12  # Assume average 2d6 = 7, but use 12 for safety
        
        if distance <= max_charge_range:
            # TTK avec meilleure arme melee
            best_melee_weapon_idx, _ = get_best_weapon_for_target(
                ally, enemy, game_state, is_ranged=False
            )
            if best_melee_weapon_idx >= 0:
                melee_weapon = ally["CC_WEAPONS"][best_melee_weapon_idx]
                # Calculer expected damage avec arme melee
                # Utiliser calculate_kill_probability pour obtenir expected_damage
                from engine.ai.weapon_selector import calculate_kill_probability
                # Note: calculate_kill_probability retourne probabilité, pas TTK
                # Utiliser reward_calc._calculate_turns_to_kill() avec arme temporaire
                # OU créer fonction calculate_ttk_with_weapon(unit, weapon, target, game_state)
                melee_ttk = reward_calc._calculate_turns_to_kill(ally, enemy, game_state)
                # TODO: Adapter pour utiliser arme melee spécifique
                
            # TTK avec meilleure arme range
            best_range_weapon_idx, _ = get_best_weapon_for_target(
                ally, enemy, game_state, is_ranged=True
            )
            if best_range_weapon_idx >= 0:
                range_ttk = reward_calc._calculate_turns_to_kill(ally, enemy, game_state)
                # TODO: Adapter pour utiliser arme range spécifique
            
            if melee_ttk < best_melee_ttk:
                best_melee_ally = ally
                best_melee_ttk = melee_ttk
                best_range_ttk = range_ttk

if best_melee_ally and best_range_ttk > 0:
    # Normaliser: 1.0 si melee 2x plus rapide, 0.0 si range 2x plus rapide
    ratio = best_range_ttk / best_melee_ttk if best_melee_ttk > 0 else 0.0
    # Ratio > 1.0 = melee plus rapide (préféré)
    # Ratio < 1.0 = range plus rapide (ne chargerait pas)
    obs[feature_base + 16] = min(1.0, max(0.0, (ratio - 0.5) * 2.0))
else:
    obs[feature_base + 16] = 0.0  # Pas d'allié melee ou pas de comparaison possible
```

**Note d'implémentation:** 
- Nécessite fonction `calculate_ttk_with_weapon(unit, weapon, target, game_state)` dans `weapon_selector.py` ou `reward_calculator.py`
- Alternative: Créer fonction helper qui calcule TTK avec une arme spécifique (pas juste l'arme sélectionnée)

##### Feature 17: `target_efficiency` (remplace `target_type_match`)

**Problème actuel:** Feature 16 originale (`target_type_match`) parse `unitType` statiquement (ex: "RangedSwarm" → préfère swarm), ne tient pas compte de l'état réel (HP, distance, armes disponibles).

**Amélioration proposée:** Utiliser Time-To-Kill (TTK) avec la meilleure arme contre cette cible pour mesurer l'efficacité réelle.

**Code à implémenter:**
```python
# Feature 17: target_efficiency (0.0-1.0)
# TTK avec ma meilleure arme contre cette cible
# Normalisé: 1.0 = je peux tuer en 1 tour, 0.0 = je ne peux pas tuer (ou très lent)

from engine.ai.weapon_selector import get_best_weapon_for_target, calculate_kill_probability
from engine.reward_calculator import RewardCalculator

reward_calc = RewardCalculator()

best_weapon_idx, best_kill_prob = get_best_weapon_for_target(
    active_unit, enemy, game_state, is_ranged=True
)

if best_weapon_idx >= 0:
    weapon = active_unit["RNG_WEAPONS"][best_weapon_idx]
    
    # Calculer TTK avec cette arme spécifique
    # Option 1: Utiliser calculate_kill_probability pour obtenir expected_damage
    kill_prob = calculate_kill_probability(active_unit, weapon, enemy, game_state)
    
    # Option 2: Calculer expected_damage directement depuis weapon stats
    # (même logique que calculate_kill_probability mais retourner expected_damage)
    # OU créer fonction calculate_expected_damage_with_weapon(weapon, target, game_state)
    
    # Pour l'instant, utiliser reward_calc._calculate_turns_to_kill() avec arme temporaire
    # TODO: Créer fonction calculate_ttk_with_weapon(unit, weapon, target, game_state)
    ttk = reward_calc._calculate_turns_to_kill(active_unit, enemy, game_state)
    # TODO: Adapter pour utiliser weapon spécifique
    
    # Normaliser: 1.0 = ttk ≤ 1, 0.0 = ttk ≥ 5
    obs[feature_base + 17] = max(0.0, min(1.0, 1.0 - (ttk - 1.0) / 4.0))
else:
    obs[feature_base + 17] = 0.0  # Pas d'armes disponibles
```

**Note d'implémentation:**
- Nécessite fonction `calculate_ttk_with_weapon(unit, weapon, target, game_state)` dans `weapon_selector.py` ou `reward_calculator.py`
- Alternative: Utiliser `calculate_kill_probability` pour obtenir expected_damage, puis calculer TTK = `target["HP_CUR"] / expected_damage`

**Fonction helper recommandée à ajouter dans `weapon_selector.py`:**
```python
def calculate_ttk_with_weapon(unit: Dict[str, Any], weapon: Dict[str, Any],
                              target: Dict[str, Any], game_state: Dict[str, Any]) -> float:
    """
    Calculate Time-To-Kill (turns) for a specific weapon against a target.
    Returns: Number of turns (activations) needed to kill target, or 100.0 if can't kill.
    """
    from shared.data_validation import require_key
    
    # Calculer expected_damage avec cette arme
    hit_target = require_key(weapon, "ATK")
    strength = require_key(weapon, "STR")
    damage = require_key(weapon, "DMG")
    num_attacks = require_key(weapon, "NB")
    ap = require_key(weapon, "AP")
    
    # Calculs W40K standard
    p_hit = max(0.0, min(1.0, (7 - hit_target) / 6.0))
    
    toughness = require_key(target, "T")
    if strength >= toughness * 2:
        p_wound = 5/6
    elif strength > toughness:
        p_wound = 4/6
    elif strength == toughness:
        p_wound = 3/6
    else:
        p_wound = 2/6
    
    armor_save = target.get("ARMOR_SAVE", 7)
    invul_save = target.get("INVUL_SAVE", 7)
    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))
    
    # Expected damage
    p_damage_per_attack = p_hit * p_wound * p_fail_save
    expected_damage = num_attacks * p_damage_per_attack * damage
    
    if expected_damage <= 0:
        return 100.0  # Can't kill
    
    hp_cur = require_key(target, "HP_CUR")
    return hp_cur / expected_damage
```

**Ordre d'implémentation:**
1. ✅ Créer `weapon_selector.py` avec `calculate_kill_probability()` (étape 7)
2. ✅ Créer `calculate_ttk_with_weapon()` dans `weapon_selector.py` (après étape 7)
3. ✅ Implémenter Feature 16 améliorée (`melee_charge_preference`) dans `observation_builder.py` (après étape 9)
4. ✅ Implémenter Feature 17 améliorée (`target_efficiency`) dans `observation_builder.py` (après étape 9)

#### Valid Targets [273:313] - 40 floats (5 cibles × 8 features)

**Structure finale (8 features par cible):**
- Feature 0: `is_valid` (inchangée)
- Feature 1: `best_weapon_index` (NOUVEAU, 0-2, normalisé / 2.0)
- Feature 2: `best_kill_probability` (NOUVEAU, remplace ancien feature 1)
- Feature 3: `danger_to_me` (était feature 2) - **DÉCALÉ**
- Feature 4: `enemy_index` (était feature 3) - **DÉCALÉ**
- Feature 5: `distance_normalized` (était feature 4) - **DÉCALÉ**
- Feature 6: `is_priority_target` (était feature 5) - **DÉCALÉ**
- Feature 7: `coordination_bonus` (était feature 6) - **DÉCALÉ**

**Code complet:**
```python
# Feature 0: is_valid (inchangée)
obs[base + 0] = 1.0 if is_valid else 0.0

# Feature 1: best_weapon_index (NOUVEAU, 0-2, normalisé / 2.0)
from engine.ai.weapon_selector import get_best_weapon_for_target
best_weapon_idx, best_kill_prob = get_best_weapon_for_target(
    active_unit, target, game_state, is_ranged=True
)
obs[base + 1] = best_weapon_idx / 2.0 if best_weapon_idx >= 0 else 0.0

# Feature 2: best_kill_probability (NOUVEAU, remplace ancien feature 1)
obs[base + 2] = best_kill_prob

# Feature 3: danger_to_me (était feature 2) - DÉCALÉ
obs[base + 3] = danger_to_me

# Feature 4: enemy_index (était feature 3) - DÉCALÉ
obs[base + 4] = enemy_index / 5.0

# Feature 5: distance_normalized (était feature 4) - DÉCALÉ
obs[base + 5] = distance_normalized

# Feature 6: is_priority_target (était feature 5) - DÉCALÉ
obs[base + 6] = 1.0 if is_priority_target else 0.0

# Feature 7: coordination_bonus (était feature 6) - DÉCALÉ
obs[base + 7] = coordination_bonus

# Total = 8 features ✅ (0 + 1 + 2 + 3 + 4 + 5 + 6 + 7)
```

#### Mises à jour critiques
- [ ] **CRITIQUE:** Mettre à jour tous les `base_idx`:
  - [ ] Directional Terrain: `base_idx=37` (au lieu de 23) - ligne 644
  - [ ] Allied Units: `base_idx=69` (au lieu de 55) - ligne 647
  - [ ] Enemy Units: `base_idx=141` (au lieu de 127) - ligne 650
  - [ ] Valid Targets: `base_idx=273` (au lieu de 265) - ligne 653
- [ ] **CRITIQUE:** Mettre à jour tous les accès directs aux anciens champs:
  - [ ] Ligne 996: `distance <= active_unit["RNG_RNG"]` → utiliser `get_max_ranged_range(active_unit)`
  - [ ] Ligne 998: `distance <= active_unit["CC_RNG"]` → utiliser `get_melee_range()` (1)
  - [ ] Ligne 1024-1027: Vérifications `is_in_range` → utiliser armes
  - [ ] Ligne 1111-1116: Calcul `offensive_type` → comparer max RNG ranged vs 1
  - [ ] Ligne 1254-1269: Calcul `target_priority` → utiliser arme sélectionnée
  - [ ] Ligne 933-938: `_calculate_danger_probability` → utiliser armes
  - [ ] Fonction `_calculate_combat_mix_score()` → utiliser max DMG des armes
  - [ ] Fonction `_calculate_favorite_target()` → utiliser stats des armes

---

## 9. CALCULATEUR DE RÉCOMPENSES

### ✅ `engine/reward_calculator.py`
- [ ] Mettre à jour `_calculate_kill_probability()` pour utiliser arme sélectionnée
- [ ] Mettre à jour `_calculate_danger_probability()` pour considérer toutes les armes ennemies (menace max)
- [ ] Mettre à jour `_calculate_expected_damage_against()` (lignes 1861-1874) pour utiliser arme sélectionnée
- [ ] Mettre à jour toutes les références à `attacker["RNG_NB"]`, `attacker["RNG_ATK"]`, etc.
- [ ] **CRITIQUE:** Mettre à jour `_calculate_combat_mix_score()` (si existe) pour utiliser max DMG des armes

### ✅ `ai/target_selector.py` - **CRITIQUE**
- [ ] Mettre à jour `_estimate_kill_probability()` (lignes 106-146):
  - [ ] Remplacer accès `shooter["RNG_ATK"]`, `shooter["RNG_STR"]`, etc. par arme sélectionnée
  - [ ] Utiliser `get_selected_ranged_weapon(shooter)`

---

## 10. LOGS

### ✅ `ai/step_logger.py`
- [ ] Ajouter champ `weapon_name` à `log_action()` pour actions de combat
- [ ] Inclure `display_name` de l'arme dans messages train_step.log
- [ ] Format: `"Unit X SHOT Unit Y with [Weapon Name] : Hit ..."`

### ✅ `engine/phase_handlers/shooting_handlers.py`
- [ ] Ajouter `weapon_name` aux messages `attack_log`
- [ ] Inclure dans entrée `action_logs`: `"weaponName": weapon["display_name"]`
- [ ] Mettre à jour format: `"Unit X SHOT Unit Y with [Weapon Name] : ..."`

### ✅ `engine/phase_handlers/fight_handlers.py`
- [ ] Ajouter `weapon_name` aux messages `attack_log`
- [ ] Inclure dans entrée `action_logs`: `"weaponName": weapon["display_name"]`
- [ ] Mettre à jour format: `"Unit X ATTACKED Unit Y with [Weapon Name] : ..."`

### ✅ `ai/game_replay_logger.py`
- [ ] Inclure nom de l'arme dans logs de replay pour actions de combat

### ✅ `shared/gameLogStructure.ts` et `shared/gameLogStructure.py`
- [ ] Ajouter champ optionnel `weaponName?: string` aux structures de log

---

## 11. INTERFACE UTILISATEUR

### ✅ `frontend/src/hooks/useEngineAPI.ts` - **CRITIQUE**
- [ ] Mettre à jour interface `APIGameState` (lignes 28-64):
  - [ ] Remplacer `RNG_RNG`, `RNG_NB`, etc. par `RNG_WEAPONS: Weapon[]`
  - [ ] Remplacer `CC_RNG`, `CC_NB`, etc. par `CC_WEAPONS: Weapon[]`
  - [ ] Ajouter `selectedRngWeaponIndex?: number` et `selectedCcWeaponIndex?: number`
- [ ] Mettre à jour fonction `convertUnits()` (lignes 465-513):
  - [ ] Extraire `RNG_WEAPONS[]` et `CC_WEAPONS[]` depuis backend
  - [ ] Supprimer validation de `CC_RNG` (ligne 468) - utiliser `getMeleeRange()` si nécessaire
  - [ ] Mapper les armes correctement vers format frontend

### ✅ `frontend/src/components/BoardPvp.tsx` - **CRITIQUE**
- [ ] Mettre à jour validations CC_RNG (lignes 558-559, 858):
  - [ ] Remplacer `selectedUnit.CC_RNG` par vérification `CC_WEAPONS.length > 0`
  - [ ] Utiliser `getMeleeRange()` (toujours 1) pour la portée
- [ ] Mettre à jour validations RNG_RNG (lignes 576-577, 873):
  - [ ] Remplacer `selectedUnit.RNG_RNG` par `getSelectedRangedWeapon(selectedUnit)?.RNG`
  - [ ] Vérifier si unité a des armes ranged avant d'autoriser shooting

### ✅ `frontend/src/components/UnitStatusTable.tsx`
- [ ] **CRITIQUE:** Remplacer accès `unit.RNG_RNG` (ligne 81) par `getSelectedRangedWeapon(unit)?.RNG || 0`
- [ ] **CRITIQUE:** Remplacer accès `unit.RNG_NB` (ligne 86) par `getSelectedRangedWeapon(unit)?.NB || 0`
- [ ] **CRITIQUE:** Remplacer accès `unit.CC_NB` (ligne 111) par `getSelectedMeleeWeapon(unit)?.NB || 0`
- [ ] Ajouter bouton expand/collapse (+/-) à gauche de l'ID de l'unité
- [ ] Gérer état expanded/collapsed par unité
- [ ] Afficher section expandable des armes:
  - [ ] **Armes à distance:** 1 ligne par arme avec `display_name`, RNG, NB, ATK, STR, AP, DMG
  - [ ] **Armes de mêlée:** 1 ligne par arme avec `display_name`, NB, ATK, STR, AP, DMG
  - [ ] Indiquer arme sélectionnée (gras ou surbrillance)
- [ ] Animation smooth pour expand/collapse

### ✅ `frontend/src/components/BoardReplay.tsx` - **CRITIQUE**
- [ ] Mettre à jour `enrichUnitsWithStats()` (lignes 175-185):
  - [ ] Remplacer `RNG_RNG: UnitClass.RNG_RNG || 0` par extraction depuis `UnitClass.RNG_WEAPONS[0]?.RNG || 0`
  - [ ] Remplacer `RNG_NB: UnitClass.RNG_NB || 0` par extraction depuis `UnitClass.RNG_WEAPONS[0]?.NB || 0`
  - [ ] Remplacer tous les autres accès `RNG_*` et `CC_*` par extraction depuis armes
  - [ ] Gérer cas où pas d'armes ranged ou melee

### ✅ `frontend/src/utils/replayParser.ts` - **CRITIQUE**
- [ ] Mettre à jour parsing unit start (lignes 151-161):
  - [ ] Remplacer `RNG_RNG: 0, RNG_NB: 0, ...` par `RNG_WEAPONS: [], CC_WEAPONS: []`
  - [ ] Remplacer `MEL_*` (ancien format) par `CC_WEAPONS: []`

### ✅ `frontend/src/components/UnitRenderer.tsx` - **CRITIQUE**
- [ ] Mettre à jour tous les accès `unit.RNG_NB` (lignes 181, 327, 1038-1039):
  - [ ] Utiliser `getSelectedRangedWeapon(unit)?.NB || 0`
- [ ] Mettre à jour tous les accès `unit.CC_NB` (lignes 1104-1105):
  - [ ] Utiliser `getSelectedMeleeWeapon(unit)?.NB || 0`
- [ ] Mettre à jour accès `unit.CC_RNG` (ligne 1088):
  - [ ] Utiliser `getMeleeRange()` (toujours 1)

### ✅ `frontend/src/hooks/useGameState.ts`
- [ ] Mettre à jour validation (ligne 74):
  - [ ] Remplacer validation `RNG_NB` par validation de `RNG_WEAPONS.length > 0`

---

## 12. AUTRES FICHIERS CRITIQUES

### ✅ `engine/w40k_core.py` - **CRITIQUE**
- [ ] Mettre à jour `__init__()` (ligne 291):
  ```python
  # Load perception parameters from training config if available
  if hasattr(self, 'training_config') and self.training_config:
      obs_params = self.training_config.get("observation_params", {})
      
      # Validation stricte: obs_size DOIT être présent
      if "obs_size" not in obs_params:
          raise KeyError(
              f"training_config missing required 'obs_size' in observation_params. "
              f"Must be defined in training_config.json. "
              f"Config: {self.training_config_name if hasattr(self, 'training_config_name') else 'unknown'}"
          )
      
      self.perception_radius = obs_params.get("perception_radius", 25)
      self.max_nearby_units = obs_params.get("max_nearby_units", 10)
      self.max_valid_targets = obs_params.get("max_valid_targets", 5)
      obs_size = obs_params["obs_size"]  # NO DEFAULT - raise error si manquant
  else:
      # Pas de config = erreur (pas de fallback)
      raise ValueError(
          "W40KEngine requires training_config with observation_params.obs_size. "
          "No default value allowed."
      )

  self.observation_space = gym.spaces.Box(
      low=0.0, high=1.0, shape=(obs_size,), dtype=np.float32
  )
  ```
- [ ] Mettre à jour `reset()` (lignes 387-388):
  - [ ] Remplacer `unit["SHOOT_LEFT"] = unit["RNG_NB"]` par extraction depuis arme sélectionnée
  - [ ] Remplacer `unit["ATTACK_LEFT"] = unit["CC_NB"]` par extraction depuis arme sélectionnée

### ✅ `main.py` - **CRITIQUE**

#### Parsing TypeScript - Regex Robuste
- [ ] Mettre à jour `load_unit_definitions_from_ts()` (lignes 59-106):
  ```python
  def load_unit_definitions_from_ts(unit_registry):
      """Load unit definitions by parsing TypeScript static class properties."""
      import re
      import os
      from engine.roster.spaceMarine.armory import get_weapons as get_sm_weapons
      from engine.roster.tyranid.armory import get_weapons as get_ty_weapons
      
      unit_definitions = {}
      
      for unit_name, faction_path in unit_registry["units"].items():
          ts_file_path = f"frontend/src/roster/{faction_path}.ts"
          
          if not os.path.exists(ts_file_path):
              print(f"Warning: Unit file not found: {ts_file_path}")
              continue
          
          try:
              with open(ts_file_path, 'r', encoding='utf-8') as f:
                  content = f.read()
              
              unit_stats = {}
              
              # Pattern 1: Static properties simples (HP_MAX, MOVE, etc.)
              static_pattern = r'static\s+([A-Z_]+)\s*=\s*([^;]+);'
              matches = re.findall(static_pattern, content)
              
              for field_name, value_str in matches:
                  value_str = value_str.strip().strip('"\'')
                  if value_str.isdigit() or (value_str.startswith('-') and value_str[1:].isdigit()):
                      unit_stats[field_name] = int(value_str)
                  elif value_str.replace('.', '').isdigit():
                      unit_stats[field_name] = float(value_str)
                  else:
                      unit_stats[field_name] = value_str
              
              # Pattern 2: RNG_WEAPON_CODES = ["code1", "code2"] ou [] (robuste)
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
              
              # Validation: Au moins une arme requise
              if not unit_stats.get("RNG_WEAPONS") and not unit_stats.get("CC_WEAPONS"):
                  raise ValueError(f"Unit {unit_name} must have at least RNG_WEAPONS or CC_WEAPONS")
              
              # Initialiser selectedWeaponIndex
              if unit_stats.get("RNG_WEAPONS"):
                  unit_stats["selectedRngWeaponIndex"] = 0
              if unit_stats.get("CC_WEAPONS"):
                  unit_stats["selectedCcWeaponIndex"] = 0
              
              unit_definitions[unit_name] = unit_stats
              
          except Exception as e:
              print(f"Error parsing {ts_file_path}: {e}")
              continue
      
      return unit_definitions
  ```

- [ ] Mettre à jour `load_scenario_units()` (lignes 154-155):
  - [ ] Remplacer `"SHOOT_LEFT": unit_def.get("RNG_NB", 0)` par extraction depuis `RNG_WEAPONS[0]["NB"]` si existe
  - [ ] Remplacer `"ATTACK_LEFT": unit_def.get("CC_NB", 0)` par extraction depuis `CC_WEAPONS[0]["NB"]` si existe
  - [ ] Valider que `RNG_WEAPONS` ou `CC_WEAPONS` existe avant extraction

### ✅ `ai/unit_registry.py` - **CRITIQUE**
- [ ] Mettre à jour `_extract_static_properties()` (même logique que `main.py`):
  - [ ] Parser `RNG_WEAPON_CODES` avec regex robuste (`re.MULTILINE | re.DOTALL`)
  - [ ] Parser `CC_WEAPON_CODES` avec regex robuste
  - [ ] Détection faction avec `faction_path.startswith()` (pas `'spaceMarine' in faction_path`)
  - [ ] Construire `RNG_WEAPONS[]` et `CC_WEAPONS[]` depuis armory Python
- [ ] **CRITIQUE:** Mettre à jour `required_props` (ligne 117):
  - [ ] Supprimer `RNG_RNG`, `RNG_DMG`, `CC_DMG` de `required_props`
  - [ ] Ajouter validation: `RNG_WEAPONS.length > 0 || CC_WEAPONS.length > 0`

### ✅ `services/api_server.py` - **CRITIQUE**
- [ ] Mettre à jour `initialize_engine()` ou `initialize_pve_engine()`:
  ```python
  # CRITICAL FIX: Add observation_params from training_config
  obs_params = training_config.get("observation_params", {})

  # Validation stricte: obs_size DOIT être présent
  if "obs_size" not in obs_params:
      raise KeyError(
          f"training_config missing required 'obs_size' in observation_params. "
          f"Must be defined in training_config.json. "
          f"Config: {training_config.get('name', 'unknown')}"
      )

  config["observation_params"] = obs_params  # Inclut obs_size validé
  ```

### ✅ `check/test_observation.py` - **CRITIQUE**
- [ ] Mettre à jour ligne 33:
  ```python
  obs, info = engine.reset()

  # Utiliser obs_size depuis engine (pas hardcodé)
  expected_size = engine.observation_space.shape[0]
  assert obs.shape == (expected_size,), f'ERROR: Shape mismatch! Got {obs.shape}, expected ({expected_size},)'

  print(f'[OK] Observation shape: {obs.shape}')
  print(f'[OK] Expected: ({expected_size},)')
  print(f'[OK] obs_size from config: {expected_size}')
  ```

---

## 13. TESTS ET VALIDATION

### ✅ Tests fonctionnels
- [ ] Vérifier création d'unités avec armes multiples
- [ ] Vérifier parsing TypeScript fonctionne avec `RNG_WEAPON_CODES` (guillemets simples, doubles, multi-lignes, array vide)
- [ ] Vérifier armories Python sont synchronisées avec armories TS
- [ ] Vérifier sélection d'arme par IA
- [ ] Vérifier calculs de combat avec arme sélectionnée
- [ ] Vérifier observations incluent toutes les armes (313 floats)
- [ ] Vérifier logs incluent nom de l'arme
- [ ] Vérifier UI affiche/cache armes correctement
- [ ] Vérifier cache pré-calcul fonctionne correctement
- [ ] Vérifier invalidation cache après dégâts
- [ ] Vérifier lazy evaluation fonctionne après mouvement
- [ ] **CRITIQUE:** Vérifier que `obs_size` manquant dans config → raise error

### ✅ Tests de régression
- [ ] Vérifier compatibilité avec unités existantes
- [ ] Vérifier pas de régression dans calculs de combat
- [ ] Vérifier observations toujours valides (313 floats)
- [ ] Mettre à jour `check/test_observation.py` ligne 33: Utiliser `engine.observation_space.shape[0]`

---

## NOTES IMPORTANTES

1. **CC_RNG:** Toujours 1 pour toutes les armes de mêlée (hardcodé, pas stocké dans Weapon)

2. **Sélection d'arme:**
   - Automatique par IA avant chaque action de combat (shoot/fight)
   - L'arme est sélectionnée pour la cible spécifique choisie par l'agent
   - Chaque cible peut avoir une arme différente comme "meilleure"
   - Pas d'action supplémentaire nécessaire - l'agent choisit la cible, l'arme suit
   - **Timing:** Agent choisit cible (action RL) → Arme sélectionnée pour cette cible spécifique → Attaque exécutée avec cette arme
   - Si SHOOT_LEFT > 1, même arme pour tous les tirs sur cette cible

3. **Observation space:**
   - **Taille:** 300 → 313 floats (après optimisations)
   - **Active Unit Capabilities:** Stats brutes de toutes les armes (22 floats)
   - **Enemy Units:** 22 features (suppression features 17 et 19 redondantes)
   - **Valid Targets:** 8 features (best_weapon_index + best_kill_probability)
   - **Calcul détaillé:**
     - Global Context: [0:15] = 15 floats
     - Active Unit Capabilities: [15:37] = 22 floats
     - Directional Terrain: [37:69] = 32 floats
     - Allied Units: [69:141] = 72 floats
     - Enemy Units: [141:273] = 132 floats (6 × 22 features)
     - Valid Targets: [273:313] = 40 floats (5 × 8 features)

4. **Cache kill_probability:**
   - Structure: `{(unit_id, weapon_index, target_id, hp_cur): kill_prob}`
   - **Pré-calcul au début de phase:** ~90% réduction calculs
   - **Invalidation:** Dès qu'une unité perd des HP ou meurt
   - Recalcul uniquement des entrées affectées
   - **Note:** Structure simple pour MVP, accepter invalidation si HP change. Optimiser plus tard si nécessaire.

5. **Lazy evaluation:**
   - Calculer seulement les unités dans `perception_radius`
   - Recalculer après phase de mouvement pour nouvelles unités entrées dans portée
   - Gain: ~30% de réduction calculs
   - Utiliser `game_state.get("perception_radius", 25)` avec fallback

6. **Validation:**
   - **PAS DE FALLBACK:** Toutes les erreurs doivent raise, jamais de valeur par défaut
   - Points de validation:
     - Création d'unité: Au moins 1 arme requise (ranged OU melee)
     - Avant combat: `selectedRngWeaponIndex < RNG_WEAPONS.length`
     - Import armory: toutes les armes référencées existent
     - **obs_size:** DOIT être présent dans `training_config.json` → **raise error si manquant**

7. **Synchronisation frontend/backend:**
   - Format JSON: armes sérialisées comme objets avec tous les champs
   - Même structure que pour les unités (pas de transformation)
   - Validation stricte: raise error si arme manquante
   - **Format JSON explicite:**
     ```json
     {
       "RNG_WEAPONS": [
         {"code_name": "bolt_rifle", "display_name": "Bolt Rifle", "RNG": 24, "NB": 2, "ATK": 3, "STR": 4, "AP": -1, "DMG": 1}
       ],
       "CC_WEAPONS": [
         {"code_name": "close_combat_weapon", "display_name": "Close Combat Weapon", "NB": 3, "ATK": 3, "STR": 4, "AP": 0, "DMG": 1}
       ],
       "selectedRngWeaponIndex": 0,
       "selectedCcWeaponIndex": 0
     }
     ```

8. **Unités avec armes partielles:**
   - Une unité peut n'avoir QUE des armes ranged OU QUE des armes melee
   - Si pas d'armes ranged: obs[16-24] = 0.0
   - Si pas d'armes melee: obs[25-34] = 0.0
   - **Validation:** Au moins 1 arme requise (ranged OU melee)

9. **Ordre des armes:**
   - Ordre défini dans armory (ordre déclaratif, stable)
   - L'ordre n'a pas d'importance fonctionnelle (sélection par kill_probability)
   - Ordre stable = plus prévisible pour l'agent

10. **Migration:** Pas de compatibilité arrière - migration immédiate de tous les fichiers

11. **SHOOT_LEFT Initialisation - Découverte Critique:**
    - **DEUX endroits** doivent être modifiés:
      1. `shooting_phase_start()` ligne 36 - Pour toutes les unités au début de phase
      2. `shooting_unit_activation_start()` ligne 381 - Pour une unité spécifique lors de son activation
    - Les deux doivent utiliser l'arme sélectionnée (ou première arme si pas encore sélectionnée)

12. **Observation Size - Validation Stricte:**
    - Source unique de vérité: `training_config.json` → `observation_params.obs_size`
    - **NO DEFAULT:** Si `obs_size` manque dans `training_config.json` → **raise error immédiatement**
    - Cohérence: Tous les paramètres d'observation viennent du même endroit
    - Détection précoce: Erreur immédiate si config incomplet

---

## ORDRE D'IMPLÉMENTATION RECOMMANDÉ

1. ✅ **Phase 0: Préparation (AVANT TOUT)**
   - [ ] Créer `engine/roster/spaceMarine/` et `engine/roster/tyranid/` avec `__init__.py`
   - [ ] Mettre à jour `obs_size` partout (300 → 313) - **Validation stricte, NO DEFAULT**
   - [ ] Corriger tous les `base_idx` (23,55,127,265 → 37,69,141,273)
   - [ ] Corriger Enemy Units feature count (23 → 22)

2. ✅ **Créer armories Python** - **CRITIQUE: Bloque parsing TypeScript**
   - `engine/roster/spaceMarine/armory.py`
   - `engine/roster/tyranid/armory.py`

3. ✅ Définitions de types et interface Weapon

4. ✅ Fichiers armory TypeScript (spaceMarine, tyranid)

5. ✅ **Mettre à jour parsing TypeScript** - **CRITIQUE**
   - `main.py load_unit_definitions_from_ts()` - Regex robuste avec `re.MULTILINE | re.DOTALL`
   - `ai/unit_registry.py _extract_static_properties()` - Même logique
   - Détection faction avec `faction_path.startswith()` (pas `'spaceMarine' in faction_path`)

6. ✅ Mettre à jour classes d'unités (9 fichiers)

7. ✅ Factory d'unités et Python game_state

8. ✅ Fonctions helper armes (TS + Python)

9. ✅ **Créer `weapon_selector.py` avec `calculate_kill_probability()`** - **CRITIQUE**
   - Fonction standalone complète (pas wrapper)
   - Ajouter import `calculate_hex_distance`

10. ✅ Handlers de combat (shooting, fight, charge)
    - [ ] **CRITIQUE:** SHOOT_LEFT à 2 endroits
    - [ ] **CRITIQUE:** ATTACK_LEFT dans `_handle_fight_unit_activation()`
    - [ ] **CRITIQUE:** Sélection d'arme avec timing exact

11. ✅ Expansion builder d'observations (avec optimisations)
    - [ ] Structure Active Unit clarifiée (22 floats)
    - [ ] Enemy Units 22 features
    - [ ] Valid Targets 8 features

12. ✅ Mises à jour calculateur de récompenses

13. ✅ Mises à jour target_selector

14. ✅ Mises à jour logs (train_step.log, logs de combat, logs de replay)

15. ✅ Mises à jour UI (affichage expandable des armes, BoardReplay, UnitRenderer, UnitStatusTable)

16. ✅ Tests et validation

---

## FICHIERS À MODIFIER/CRÉER

### Nouveaux fichiers
- `frontend/src/roster/spaceMarine/armory.ts`
- `frontend/src/roster/tyranid/armory.ts`
- `frontend/src/utils/weaponHelpers.ts`
- `engine/roster/spaceMarine/armory.py` - **CRITIQUE: Manquant dans plan initial**
- `engine/roster/tyranid/armory.py` - **CRITIQUE: Manquant dans plan initial**
- `engine/utils/weapon_helpers.py`
- `engine/ai/weapon_selector.py`

### Fichiers à modifier
- `frontend/src/types/game.ts`
- `frontend/src/types/api.ts` - **CRITIQUE: AIActionRequest interface**
- `frontend/src/roster/*/units/*.ts` (9 fichiers)
- `frontend/src/data/UnitFactory.ts` - **CRITIQUE: Supprimer interface Unit dupliquée, requiredProps**
- `frontend/src/components/UnitStatusTable.tsx` - **CRITIQUE: Accès RNG_RNG, RNG_NB, CC_NB**
- `frontend/src/components/BoardReplay.tsx` - **CRITIQUE: enrichUnitsWithStats**
- `frontend/src/components/UnitRenderer.tsx` - **CRITIQUE: Accès RNG_NB, CC_NB, CC_RNG**
- `frontend/src/utils/replayParser.ts` - **CRITIQUE: Parsing unit start**
- `frontend/src/hooks/useEngineAPI.ts` - **CRITIQUE**
- `frontend/src/components/BoardPvp.tsx` - **CRITIQUE**
- `frontend/src/hooks/useGameState.ts`
- `engine/game_state.py` - **CRITIQUE: load_units_from_scenario**
- `engine/w40k_core.py` - **CRITIQUE: obs_size validation stricte NO DEFAULT**
- `engine/phase_handlers/shooting_handlers.py` - **CRITIQUE: SHOOT_LEFT à 2 endroits, sélection arme**
- `engine/phase_handlers/fight_handlers.py` - **CRITIQUE: ATTACK_LEFT, sélection arme**
- `engine/phase_handlers/charge_handlers.py`
- `engine/observation_builder.py` - **CRITIQUE: obs size NO DEFAULT, accès anciens champs, padding, base_idx**
- `engine/reward_calculator.py`
- `main.py` - **CRITIQUE: Parsing TS robuste, load_scenario_units**
- `ai/unit_registry.py` - **CRITIQUE: _extract_static_properties, required_props**
- `ai/target_selector.py` - **CRITIQUE: _estimate_kill_probability**
- `ai/step_logger.py`
- `ai/game_replay_logger.py`
- `shared/gameLogStructure.ts`
- `shared/gameLogStructure.py`
- `config/unit_definitions.json` - **CRITIQUE: required_properties**
- `frontend/public/config/unit_definitions.json` - **CRITIQUE: required_properties**
- Tous les `training_config.json` - **CRITIQUE: obs_size = 313 dans observation_params**
- `services/api_server.py` - **CRITIQUE: obs_size validation stricte NO DEFAULT**
- `check/test_observation.py` - **CRITIQUE: Utiliser engine.observation_space.shape[0]**

---

## 🔴 PROBLÈMES CRITIQUES IDENTIFIÉS ET RÉSOLUS

### ✅ SHOOT_LEFT/ATTACK_LEFT - Initialisation
- **Découverte critique:** SHOOT_LEFT initialisé à **DEUX** endroits:
  1. `shooting_phase_start()` ligne 36 - Pour toutes les unités au début de phase
  2. `shooting_unit_activation_start()` ligne 381 - Pour une unité spécifique lors de son activation
- **Solution:** Utiliser arme sélectionnée (ou première arme si pas sélectionnée) aux deux endroits
- **Fichiers:** `shooting_handlers.py` (2 endroits), `fight_handlers.py` (`_handle_fight_unit_activation()` ligne 1282), `w40k_core.py`, `main.py`

### ✅ calculate_kill_probability - Fonction Manquante
- **Problème:** Fonction utilisée partout mais n'existe pas
- **Solution:** Créer fonction standalone complète dans `weapon_selector.py` (pas wrapper RewardCalculator)
- **Code complet fourni dans section 7**

### ✅ Observation Size - Validation Stricte, NO DEFAULT
- **Problème:** obs_size hardcodé à 300 dans 5+ endroits, pas de source unique de vérité
- **Solution:** Source unique = `training_config.json` → `observation_params.obs_size`
- **NO DEFAULT:** Si `obs_size` manque → **raise error immédiatement**
- **Fichiers:** `observation_builder.py`, `w40k_core.py`, `api_server.py`, `test_observation.py`, tous les `training_config.json`

### ✅ Base Indices Incorrects
- **Solution:** Recalculer (37, 69, 141, 273)
- **Fichier:** `observation_builder.py` lignes 644, 647, 650, 653

### ✅ Enemy Units Feature Count (23 → 22)
- **Solution:** Supprimer features 17 et 19, réindexer
- **Fichier:** `observation_builder.py` lignes 968, 1038, 1020, 1028

### ✅ Regex Parsing Fragile
- **Solution:** Regex robuste avec `re.MULTILINE | re.DOTALL` et support guillemets simples/doubles
- **Fichiers:** `main.py`, `ai/unit_registry.py`

### ✅ Détection Faction Fragile
- **Solution:** Utiliser `faction_path.startswith()` au lieu de `'spaceMarine' in faction_path`
- **Fichiers:** `main.py`, `ai/unit_registry.py`

### ✅ Structure Active Unit Capabilities Incohérente
- **Solution:** Code complet fourni (22 floats, structure claire)
- **Fichier:** `observation_builder.py` section Active Unit Capabilities

### ✅ Valid Targets Structure (7 → 8 features)
- **Solution:** Structure complète 8 features documentée
- **Fichier:** `observation_builder.py` section Valid Targets

### ✅ convertUnits et APIGameState
- **Solution:** Mettre à jour interface et fonction pour accepter `RNG_WEAPONS[]` et `CC_WEAPONS[]`
- **Fichier:** `useEngineAPI.ts`

### ✅ Validations partout
- **Solution:** Mettre à jour toutes les validations pour utiliser armes au lieu d'anciens champs
- **Fichiers:** `UnitFactory.ts`, `game_state.py`, `BoardPvp.tsx`, `ai/unit_registry.py`, etc.

### ✅ Accès directs aux anciens champs
- **Solution:** Utiliser helpers d'armes partout
- **Fichiers:** `observation_builder.py`, `reward_calculator.py`, `target_selector.py`, `charge_handlers.py`, tous les fichiers frontend, etc.
- **Action:** Faire grep exhaustif: `grep -r "RNG_NB\|RNG_RNG\|RNG_ATK\|RNG_STR\|RNG_AP\|RNG_DMG\|CC_NB\|CC_RNG\|CC_ATK\|CC_STR\|CC_AP\|CC_DMG" --include="*.py" --include="*.ts" --include="*.tsx"`

### ✅ Required Properties Obsolètes
- **Solution:** Supprimer `RNG_RNG`, `RNG_DMG`, `CC_DMG` de `required_properties`
- **Fichiers:** `ai/unit_registry.py`, `frontend/src/data/UnitFactory.ts`, `config/unit_definitions.json`

### ✅ Interface Unit Obsolète
- **Solution:** Mettre à jour interface dans `types/game.ts`, supprimer dupliquée dans `UnitFactory.ts`
- **Fichiers:** `frontend/src/types/game.ts`, `frontend/src/data/UnitFactory.ts`

### ✅ Import calculate_hex_distance Manquant
- **Solution:** Ajouter import dans `weapon_selector.py`
- **Fichier:** `engine/ai/weapon_selector.py`

---

## OPTIMISATIONS INTÉGRÉES

### ✅ Cache pré-calcul
- Pré-calculer `kill_probability` au début de chaque phase
- Gain: ~90% de réduction calculs pendant la phase
- Invalidation: Dès qu'une unité perd des HP ou meurt
- Structure simple: `{(unit_id, weapon_index, target_id, hp_cur): kill_prob}` pour MVP

### ✅ Réduction Enemy Units
- Suppression features 17 (`can_be_meleed`) et 19 (`is_in_range`) redondantes
- Gain: 12 floats (144 → 132 floats)

### ✅ Lazy evaluation
- Calculer seulement les unités dans `perception_radius`
- Recalculer après phase de mouvement
- Gain: ~30% de réduction calculs

---

## ✅ DÉCISIONS OPTIMALES FINALES

### Cache Structure
**Décision:** Garder structure simple `(unit_id, weapon_index, target_id, hp_cur)` pour MVP.
- ✅ Simple et compréhensible
- ✅ Invalidation simple (supprimer par target_id)
- ⚠️ Accepte invalidation si HP change (acceptable pour MVP)
- 💡 Optimiser plus tard si performance devient problème

### Timing Sélection Arme
**Décision:** Sélection une fois par cible choisie.
- Agent choisit cible → Arme sélectionnée pour cette cible → Attaque
- Si SHOOT_LEFT > 1, même arme pour tous les tirs sur cette cible
- Pas de re-sélection à chaque tir

### Tie-Breaking Weapon Selection
**Décision:** Index le plus bas en cas d'égalité.
- Simple, déterministe
- Pas besoin de critères complexes

### Regex Parsing
**Décision:** Regex robuste avec `re.MULTILINE | re.DOTALL` et support guillemets simples/doubles.
- Simple, gère tous les cas essentiels
- Pas de parser TypeScript complet (over-engineering)

### Observation Size (obs_size)
**Décision:** Source unique de vérité = `training_config.json` → `observation_params.obs_size`
- ✅ **NO DEFAULT:** Si `obs_size` manque dans `training_config.json` → **raise error immédiatement**
- ✅ Cohérence: Tous les paramètres d'observation viennent du même endroit
- ✅ Détection précoce: Erreur immédiate si config incomplet
- ❌ Tests sans config: **RAISE ERROR** (pas de default)
- ❌ API server sans config: **RAISE ERROR** (pas de default)

### calculate_kill_probability
**Décision:** Fonction standalone complète (pas wrapper RewardCalculator).
- ✅ Simple et standalone (pas de dépendance complexe)
- ✅ Facile à tester
- ✅ Réutilisable partout
- ✅ Pas de dépendance sur RewardCalculator ou ObservationBuilder
- ✅ Code complet fourni

### Enemy Units Features - Améliorations Tactiques
**Décision:** Améliorer Feature 16 et Feature 17 (anciennes Features 15 et 16) avec calculs Time-To-Kill (TTK) au lieu de valeurs statiques.

#### Feature 16: `melee_charge_preference` (remplace `can_be_charged_by_melee`)
**Problème identifié:**
- Feature 15 originale (`can_be_charged_by_melee`) vérifiait uniquement si un allié melee peut charger (distance)
- Ne vérifiait pas si l'allié est vraiment melee (peut avoir `CC_DMG > 0` mais être principalement ranged)
- Ne vérifiait pas si charger est tactiquement avantageux

**Choix fait:**
- ✅ Remplacer par comparaison TTK melee vs range pour le meilleur allié melee
- ✅ Indique si charger est préféré (1.0 = melee beaucoup plus efficace, 0.0 = range plus efficace)
- ✅ Plus informatif: indique l'avantage tactique réel, pas juste la possibilité
- ✅ Plus précis: filtre les unités vraiment melee

**Implémentation:**
- Nécessite `weapon_selector.py` (créé étape 7) et fonctions TTK de `reward_calculator.py`
- À implémenter **APRÈS étape 9** (calculateur de récompenses)
- Code complet fourni dans section 8 "AMÉLIORATIONS POST-ÉTAPE 9"

#### Feature 17: `target_efficiency` (remplace `target_type_match`)
**Problème identifié:**
- Feature 16 originale (`target_type_match`) parse `unitType` statiquement (ex: "RangedSwarm" → préfère swarm)
- Ne tient pas compte de l'état réel (HP, distance, armes disponibles)
- Valeur binaire (1.0 ou 0.3) basée uniquement sur type d'unité

**Choix fait:**
- ✅ Remplacer par TTK avec la meilleure arme contre cette cible
- ✅ Plus dynamique: s'adapte à la situation réelle
- ✅ Plus précis: tient compte des armes disponibles et de l'état de la cible
- ✅ Valeur continue (0.0-1.0) normalisée: 1.0 = tuer en 1 tour, 0.0 = très lent/impossible

**Implémentation:**
- Nécessite `weapon_selector.py` (créé étape 7) et fonctions TTK de `reward_calculator.py`
- À implémenter **APRÈS étape 9** (calculateur de récompenses)
- Code complet fourni dans section 8 "AMÉLIORATIONS POST-ÉTAPE 9"

#### Feature 17 originale: `can_melee_units_charge_target`
**Choix fait:**
- ✅ **SUPPRIMÉ** (redondant avec Feature 16 améliorée)
- Feature 16 améliorée (`melee_charge_preference`) fournit déjà l'information nécessaire
- Feature 19 (`is_adjacent`) indique déjà si l'unité est en portée de mêlée

#### Stratégie d'implémentation
**Choix fait: Option A - Implémentation progressive**
- ✅ Phase 0: Garder structure actuelle avec placeholders
- ✅ Après étape 9: Implémenter les améliorations Feature 16 et Feature 17
- ✅ Avantages:
  - Évite dette technique (pas de fonctions temporaires)
  - Implémentation propre avec toutes les dépendances disponibles
  - Pas de code à refactoriser plus tard

**Fonction helper requise:**
- `calculate_ttk_with_weapon(unit, weapon, target, game_state)` dans `weapon_selector.py`
- Code complet fourni dans section 8 "AMÉLIORATIONS POST-ÉTAPE 9"

---

## 📊 RÉSUMÉ DES CORRECTIONS CRITIQUES

| # | Problème | Solution | Fichier | Ligne/Fonction |
|---|----------|----------|---------|----------------|
| 1 | `calculate_kill_probability` manquante | Fonction standalone complète | `engine/ai/weapon_selector.py` | NOUVEAU |
| 2 | `obs_size` hardcodé | Variable d'instance depuis config, **NO DEFAULT, raise error si manquant** | `engine/observation_builder.py` | `__init__()` |
| 3 | `base_idx` incorrects | Recalculer (37, 69, 141, 273) | `engine/observation_builder.py` | Multiple |
| 4 | Enemy Units (23 → 22) | Supprimer features 17 et 19, réindexer | `engine/observation_builder.py` | `_encode_enemy_units()` |
| 5 | Regex fragile | `re.MULTILINE \| re.DOTALL` + guillemets | `main.py`, `ai/unit_registry.py` | Parsing functions |
| 6 | Détection faction | `faction_path.startswith()` | `main.py`, `ai/unit_registry.py` | Parsing functions |
| 7 | Active Unit incohérent | Structure claire 22 floats | `engine/observation_builder.py` | `build_observation()` |
| 8 | SHOOT_LEFT init (phase_start) | Utiliser arme sélectionnée | `shooting_handlers.py` | `shooting_phase_start()` ligne 36 |
| 9 | SHOOT_LEFT init (unit_activation) | Utiliser arme sélectionnée | `shooting_handlers.py` | `shooting_unit_activation_start()` ligne 381 |
| 10 | ATTACK_LEFT init | Utiliser arme sélectionnée | `fight_handlers.py` | `_handle_fight_unit_activation()` ligne 1282 |
| 11 | Sélection arme shooting | Dans target_selection_handler | `shooting_handlers.py` | `shooting_target_selection_handler()` AVANT ligne 1221 |
| 12 | Sélection arme fight | Dans _handle_fight_attack | `fight_handlers.py` | `_handle_fight_attack()` AVANT ligne 1488 |
| 13 | Import calculate_hex_distance | Ajouter import | `engine/ai/weapon_selector.py` | Imports |
| 14 | Accès anciens champs | Remplacer par helpers | 49+ fichiers | Multiple |
| 15 | Required properties | Supprimer RNG_RNG, RNG_DMG, CC_DMG | `ai/unit_registry.py`, etc. | Multiple |
| 16 | Interface Unit | Mettre à jour interface | `frontend/src/types/game.ts` | Interface Unit |

---

## ⚠️ DÉCOUVERTE IMPORTANTE

**SHOOT_LEFT est initialisé à DEUX endroits:**
1. `shooting_phase_start()` ligne 36 - Pour toutes les unités au début de phase
2. `shooting_unit_activation_start()` ligne 381 - Pour une unité spécifique lors de son activation

**Les deux doivent être modifiés!** C'est une découverte critique qui n'était pas claire dans les audits précédents.

---

**Dernière mise à jour:** 2025-01-XX  
**Statut:** Plan finalisé avec toutes les corrections critiques des audits 32 et 33 intégrées  
**Corrections critiques:** 16 identifiées, toutes avec solutions simples et directes

---

**Fin du plan d'implémentation mis à jour**
