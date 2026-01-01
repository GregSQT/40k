# Weapon Override in Scenarios - Implementation Plan

**Date**: 2025-01-XX  
**Status**: Planning  
**Priority**: Medium

---

## 📋 OBJECTIF

Permettre de spécifier des armes personnalisées directement dans les fichiers de scénario JSON, sans créer de nouvelles classes TypeScript pour chaque variante d'équipement.

**Avantages** :
- ✅ Flexibilité : plusieurs configurations d'armes dans un même scénario
- ✅ Simplicité : pas besoin de créer un fichier `.ts` par variante
- ✅ Rétrocompatibilité : scénarios existants fonctionnent sans modification
- ✅ Centralisation : les stats d'armes restent dans l'armory (single source of truth)

---

## 📐 FORMAT JSON

### Format proposé

```json
{
  "units": [
    {
      "id": 1,
      "unit_type": "Intercessor",
      "player": 0,
      "col": 14,
      "row": 14,
      "weapons": {
        "rng_weapon_codes": ["stalker_bolt_rifle", "bolt_pistol"],
        "cc_weapon_codes": ["close_combat_weapon"]
      }
    },
    {
      "id": 2,
      "unit_type": "Intercessor",
      "player": 0,
      "col": 20,
      "row": 7
      // Pas de "weapons" = utilise les armes par défaut de la classe
    }
  ]
}
```

### Règles

- **Champ optionnel** : Si `weapons` est absent, utiliser les armes par défaut de la classe
- **Codes d'armes** : Utiliser les codes exacts de l'armory (ex: `"bolt_rifle"`, `"stalker_bolt_rifle"`)
- **Validation stricte** : Si un code n'existe pas → erreur fatale
- **VALUE** : Toujours utiliser la `VALUE` de la classe (ignorer le changement d'armes)

---

## 🔍 DÉTECTION DE FACTION

### Approche recommandée

Utiliser le chemin depuis `unit_registry.json` (comme dans `main.py` ligne 108-113).

**Logique** :
- `unit_registry.json` contient : `"Intercessor": "spaceMarine/units/Intercessor"`
- Si le chemin commence par `"spaceMarine/"` → faction = `"SpaceMarine"`
- Si le chemin commence par `"tyranid/"` → faction = `"Tyranid"`
- Sinon → erreur fatale

**Avantages** :
- ✅ Simple et maintenable
- ✅ Déjà utilisé dans le code existant
- ✅ Pas besoin de modifier les classes TypeScript
- ✅ Fonctionne automatiquement pour toutes les factions

---

## 🛠️ MODIFICATIONS REQUISES

### 1. Frontend : `frontend/src/data/UnitFactory.ts`

#### A. Modifier l'interface `createUnit()`

**Ajouter les paramètres optionnels** :
```typescript
export function createUnit(params: {
  id: number;
  name: string;
  type: string;
  player: 0 | 1;
  col: number;
  row: number;
  color: number;
  // NOUVEAU
  rng_weapon_codes?: string[];
  cc_weapon_codes?: string[];
}): Unit
```

#### B. Ajouter la logique d'override

**Dans `createUnit()`** :
1. Charger la classe d'unité depuis `unitClassMap`
2. Si `rng_weapon_codes` ou `cc_weapon_codes` sont fournis :
   - Détecter la faction depuis `unit_registry.json`
   - Charger les armes depuis l'armory TypeScript correspondant
   - Valider que toutes les armes existent (erreur fatale si manquante)
3. Sinon : utiliser les armes par défaut de la classe

#### C. Fonction utilitaire : détection de faction

**Créer `_detectFactionFromUnitType(unitType: string)`** :
- Charger `unit_registry.json`
- Extraire le chemin pour `unitType`
- Dériver la faction depuis le chemin
- Retourner `"SpaceMarine"` ou `"Tyranid"`

#### D. Fonction utilitaire : chargement d'armes par faction

**Adapter `getWeapons()` pour accepter la faction** :
- Actuellement : `getWeapons(codeNames)` → charge toujours Space Marine
- Nouveau : `getWeapons(codeNames, faction)` → charge selon la faction
- Ou créer des fonctions séparées : `getSpaceMarineWeapons()`, `getTyranidWeapons()`

---

### 2. Frontend : `frontend/src/components/GameController.tsx`

#### Modifier le chargement des scénarios

**Dans `loadUnits()` (ligne 64-81)** :
1. Étendre l'interface `ScenarioUnit` :
```typescript
interface ScenarioUnit {
  id: number;
  unit_type: string;
  player: number;
  col: number;
  row: number;
  weapons?: {  // NOUVEAU
    rng_weapon_codes?: string[];
    cc_weapon_codes?: string[];
  };
}
```

2. Passer les armes à `createUnit()` :
```typescript
return createUnit({
  // ... champs existants ...
  rng_weapon_codes: unit.weapons?.rng_weapon_codes,
  cc_weapon_codes: unit.weapons?.cc_weapon_codes,
});
```

---

### 3. Backend : `engine/game_state.py`

#### Modifier `load_units_from_scenario()`

**Dans la boucle `for unit_data in basic_units:` (ligne 142-207)** :

1. **Après avoir chargé `full_unit_data`** (ligne 149) :
   - Vérifier si `"weapons"` existe dans `unit_data`
   
2. **Si `weapons` présent** :
   - Extraire `rng_weapon_codes` et `cc_weapon_codes`
   - Détecter la faction depuis `unit_registry` (utiliser le chemin)
   - Charger les armes depuis l'armory Python : `get_weapons(faction, codes)`
   - Valider : si une arme manque → `KeyError` (erreur fatale)
   
3. **Si `weapons` absent** :
   - Utiliser les armes par défaut : `full_unit_data.get("RNG_WEAPONS", [])`

4. **Validation finale** :
   - Au moins une arme requise (RNG ou CC)
   - Si aucune arme → `ValueError`

#### Fonction utilitaire : détection de faction

**Créer `_detect_faction_from_unit_type(unit_type: str, unit_registry)`** :
- Utiliser `unit_registry.get_unit_path(unit_type)` ou équivalent
- Extraire la faction depuis le chemin
- Retourner `"SpaceMarine"` ou `"Tyranid"`

---

### 4. Backend : `ai/unit_registry.py` (si nécessaire)

#### Ajouter méthode pour obtenir le chemin

**Si `UnitRegistry` n'a pas déjà une méthode** :
- `get_unit_path(unit_type: str) -> str` : retourne le chemin depuis `unit_registry.json`
- Ou utiliser directement `unit_registry["units"][unit_type]` si accessible

---

## ✅ VALIDATION

### Règles de validation

1. **Codes d'armes manquants** :
   - Si un code n'existe pas dans l'armory → **erreur fatale** (`KeyError` ou `ValueError`)
   - Message d'erreur clair : `"Weapon 'X' not found in {faction} armory"`

2. **Aucune arme** :
   - Si `rng_weapon_codes: []` ET `cc_weapon_codes: []` → **erreur fatale**
   - Message : `"Unit must have at least RNG_WEAPONS or CC_WEAPONS"`

3. **Faction inconnue** :
   - Si le chemin ne commence pas par `spaceMarine/` ou `tyranid/` → **erreur fatale**
   - Message : `"Unknown faction for unit type 'X': {path}"`

4. **Format JSON** :
   - `weapons` doit être un objet (pas un array)
   - `rng_weapon_codes` et `cc_weapon_codes` doivent être des arrays de strings

---

## 🧪 TESTS

### Scénarios de test

1. **Test basique** : Scénario avec override d'armes
   - Créer un scénario avec `weapons` spécifié
   - Vérifier que les armes sont correctement chargées

2. **Test rétrocompatibilité** : Scénario sans `weapons`
   - Utiliser un scénario existant
   - Vérifier que les armes par défaut sont utilisées

3. **Test validation** : Code d'arme invalide
   - Scénario avec un code d'arme qui n'existe pas
   - Vérifier que l'erreur est levée avec un message clair

4. **Test faction** : Détection correcte
   - Scénario avec unités Space Marine et Tyranid
   - Vérifier que les bonnes armories sont utilisées

5. **Test frontend/backend cohérence** :
   - Même scénario chargé côté frontend et backend
   - Vérifier que les armes sont identiques

---

## 📝 ORDRE D'IMPLÉMENTATION

### Phase 1 : Backend (priorité pour l'entraînement)

1. ✅ Modifier `engine/game_state.py` → `load_units_from_scenario()`
   - Ajouter la logique d'override
   - Ajouter la détection de faction
   - Ajouter la validation

2. ✅ Tester avec un scénario JSON simple
   - Créer un scénario de test avec override
   - Vérifier le chargement

3. ✅ Valider la cohérence
   - Vérifier que les unités ont les bonnes armes
   - Vérifier que l'entraînement fonctionne

### Phase 2 : Frontend (affichage)

4. ✅ Modifier `frontend/src/data/UnitFactory.ts`
   - Ajouter les paramètres optionnels
   - Ajouter la logique d'override
   - Ajouter la détection de faction

5. ✅ Modifier `frontend/src/components/GameController.tsx`
   - Étendre l'interface `ScenarioUnit`
   - Passer les armes à `createUnit()`

6. ✅ Adapter les armories TypeScript
   - S'assurer que `getWeapons()` peut charger selon la faction
   - Ou créer des fonctions séparées par faction

7. ✅ Tester l'affichage
   - Charger un scénario avec override
   - Vérifier que les armes sont correctement affichées

### Phase 3 : Documentation et tests

8. ✅ Documenter le format JSON
   - Ajouter des exemples dans la documentation
   - Mettre à jour `CONFIG_FILES.md` si nécessaire

9. ✅ Tests complets
   - Tous les scénarios de test
   - Tests de régression

---

## 🔄 RÉTROCOMPATIBILITÉ

### Garanties

- ✅ **Scénarios existants** : Fonctionnent sans modification
  - Si `weapons` est absent → utilise les armes par défaut
  - Aucun changement de comportement

- ✅ **Classes TypeScript** : Aucune modification requise
  - Les classes gardent leurs armes par défaut
  - L'override est optionnel

- ✅ **API** : Pas de breaking changes
  - Les fonctions existantes continuent de fonctionner
  - Nouveaux paramètres optionnels uniquement

---

## 📌 NOTES IMPORTANTES

### Valeur (VALUE)

- **Décision** : Toujours utiliser la `VALUE` de la classe
- **Raison** : Simplifie l'implémentation et l'entraînement
- **Impact** : Les unités avec armes différentes ont la même valeur
  - Acceptable pour l'entraînement (l'agent apprend les différences via les stats d'armes)

### Cohérence Frontend/Backend

- **Critique** : Les deux doivent interpréter le même format
- **Solution** : Utiliser la même logique de détection de faction
- **Validation** : Tests de cohérence obligatoires

### Performance

- **Impact** : Minimal
  - Détection de faction : O(1) (lookup dans `unit_registry.json`)
  - Chargement d'armes : O(n) où n = nombre de codes d'armes
  - Cache de l'armory : Déjà en place côté Python

---

## 🎯 CRITÈRES DE SUCCÈS

- ✅ Scénarios avec override d'armes fonctionnent (frontend + backend)
- ✅ Scénarios existants fonctionnent sans modification
- ✅ Validation stricte : erreurs claires si armes invalides
- ✅ Tests passent (rétrocompatibilité + nouvelles fonctionnalités)
- ✅ Documentation à jour

---

## 📚 RÉFÉRENCES

- `engine/game_state.py` : `load_units_from_scenario()`
- `frontend/src/data/UnitFactory.ts` : `createUnit()`
- `main.py` : Détection de faction (ligne 108-113)
- `engine/weapons/parser.py` : `get_weapons(faction, codes)`
- `config/unit_registry.json` : Mapping unit_type → chemin

